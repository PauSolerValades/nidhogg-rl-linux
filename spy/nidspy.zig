//! Injected into the game (LD_PRELOAD): reads/writes its own memory, and publishes
//! the proven state fields at tick rate. No ptrace, no permissions — the process
//! reads itself.
//!
//! Command file /tmp/nid_cmd_<pid>, one command per line, drained every `poll_ns`:
//!   dump <hexa> <hexlen> <path>   write len bytes from addr to path
//!   poke <hexa> <hexbytes>        write bytes
//!   hold <hexa> <hexbytes> <ms>   pin a value across frames
//!   add  <hexa> <hexf32|f64> <ms> accumulate (physics cannot undo a drift)
//!   key <keysym> [ms]             XTEST press+release, held ms (default 120)
//!   kd <keysym> / ku <keysym>     explicit key down / up (held actions)
//!   track <p1> <p2> <score> <tick>  start publishing /tmp/nid_state_<pid>
//!                                 (any field 0 = not tracked; all 0 = stop publishing)
//!   ping                          write "pong <pid>" to /tmp/nid_res_<pid>
//!
//! Two differences from the C version this replaces:
//!   * the poll is 2 ms, not 50 ms (measured 51 ms round trip -> 2.4 ms)
//!   * the state file is PUSHED by a thread that samples at 1 kHz and publishes once
//!     per game tick, so the consumer never waits for a round trip at all.
//!
//! The state file is 128 bytes, written to a temp path and renamed into place, so a
//! reader either sees the previous sample or the new one, never a half-written one.

const std = @import("std");
const linux = std.os.linux;

/// Command poll. At 50 ms this was the whole latency budget.
const poll_ns: u64 = 2 * std.time.ns_per_ms;
/// How often the publisher checks whether the game ticked. 1 ms = <=1 ms publish lag
/// on a 16.7 ms tick, for ~0.1% of a core.
const sample_ns: u64 = std.time.ns_per_ms;
/// Without a tick counter to sync to, publish at this interval (~125 Hz).
const fallback_publish_ns: u64 = 8 * std.time.ns_per_ms;
/// hold/add re-write the value this often so the game's 60 Hz tick cannot win.
const pin_ns: u64 = 500 * std.time.ns_per_us;

// Proven record offsets (docs/LAYOUT.md). One contiguous dump of a record would cover
// 0x88..0x100, but the publisher reads the five fields it needs instead.
const off_anim: usize = 0xBC;
const off_facing: usize = 0xD8;
const off_x: usize = 0xEC;
const off_y: usize = 0xF0;
/// Highest offset read, +4: used to check the whole sample stays inside one mapping.
const rec_end: usize = off_y + 4;

const magic: u32 = 0x4E494431; // "NID1"
const version: u32 = 1;

const flag_p1: u32 = 1 << 0;
const flag_p2: u32 = 1 << 1;
const flag_score: u32 = 1 << 2;
const flag_tick: u32 = 1 << 3;

/// Layout is mirrored in nidlinux.STATE_FMT — change both together.
const Snapshot = extern struct {
    magic: u32,
    version: u32,
    seq: u64,
    t_ns: u64,
    tick: u32,
    flags: u32,
    p1_x: f32,
    p1_y: f32,
    p1_facing: f32,
    p1_anim: u32,
    p2_x: f32,
    p2_y: f32,
    p2_facing: f32,
    p2_anim: u32,
    score_orange: u32,
    score_yellow: u32,
    _reserved: [56]u8,
};
comptime {
    std.debug.assert(@sizeOf(Snapshot) == 128);
}

var g_pid: i32 = 0;
var cmd_path_buf: [64:0]u8 = undefined;
var res_path_buf: [64:0]u8 = undefined;
var done_path_buf: [64:0]u8 = undefined;
var state_path_buf: [64:0]u8 = undefined;
var state_tmp_buf: [64:0]u8 = undefined;
var tmp_path_buf: [256:0]u8 = undefined;

var cmd_path: [:0]const u8 = undefined;
var res_path: [:0]const u8 = undefined;
var done_path: [:0]const u8 = undefined;
var state_path: [:0]const u8 = undefined;
var state_tmp: [:0]const u8 = undefined;

/// Tracked addresses and, for each, the end of the mapping it was found in. The end
/// bound is the crash guard: a pointer that outlives its round is skipped instead of
/// being dereferenced past an unmapped page and taking the game down.
const Tracked = struct {
    addr: usize = 0,
    end: usize = 0,
};

fn getAddr(t: *Tracked) usize {
    return @atomicLoad(usize, &t.addr, .monotonic);
}


/// Seqlock over the tracking config: odd = a reconfigure is in flight, so a sample taken
/// now would mix old and new. The publisher refuses to publish across a change.
var g_gen: usize = 0;

var g_p1: Tracked = .{};
var g_p2: Tracked = .{};
var g_score: Tracked = .{};
var g_tick: Tracked = .{};

// ------------------------------------------------------------------ syscall helpers

fn now() u64 {
    var ts: linux.timespec = undefined;
    _ = linux.clock_gettime(.MONOTONIC, &ts);
    return @as(u64, @intCast(ts.sec)) * std.time.ns_per_s + @as(u64, @intCast(ts.nsec));
}

fn ok(r: usize) bool {
    return @as(isize, @bitCast(r)) >= 0;
}

fn fd_of(r: usize) linux.fd_t {
    return @intCast(r);
}

fn sleepNs(ns: u64) void {
    var ts: linux.timespec = .{
        .sec = @intCast(ns / std.time.ns_per_s),
        .nsec = @intCast(ns % std.time.ns_per_s),
    };
    _ = linux.nanosleep(&ts, null);
}

/// Write `data` to an absolute path, replacing it. Returns false on any failure.
fn writeFile(path: [*:0]const u8, data: []const u8) bool {
    const r = linux.openat(linux.AT.FDCWD, path,
        .{ .ACCMODE = .WRONLY, .CREAT = true, .TRUNC = true }, 0o644);
    if (!ok(r)) return false;
    const fd = fd_of(r);
    defer _ = linux.close(fd);
    var off: usize = 0;
    while (off < data.len) {
        const w = linux.write(fd, data.ptr + off, data.len - off);
        if (!ok(w) or w == 0) return false;
        off += w;
    }
    return true;
}

/// Read at most buf.len bytes from an absolute path. Returns the byte count, or null.
fn readFile(path: [*:0]const u8, buf: []u8) ?usize {
    const r = linux.openat(linux.AT.FDCWD, path, .{ .ACCMODE = .RDONLY }, 0);
    if (!ok(r)) return null;
    const fd = fd_of(r);
    defer _ = linux.close(fd);
    var off: usize = 0;
    while (off < buf.len) {
        const n = linux.read(fd, buf.ptr + off, buf.len - off);
        if (!ok(n)) return null;
        if (n == 0) break;
        off += n;
    }
    return off;
}

/// End of the mapping containing `addr` in /proc/self/maps, or 0 if it is not mapped.
/// Called once per `track`, never in the sampling loop.
fn regionEnd(addr: usize) usize {
    const n = readFile("/proc/self/maps", &maps_buf) orelse return 0;
    var it = std.mem.splitScalar(u8, maps_buf[0..n], '\n');
    while (it.next()) |line| {
        const sp = std.mem.indexOfScalar(u8, line, ' ') orelse continue;
        const range = line[0..sp];
        const dash = std.mem.indexOfScalar(u8, range, '-') orelse continue;
        const start = std.fmt.parseInt(usize, range[0..dash], 16) catch continue;
        const end = std.fmt.parseInt(usize, range[dash + 1 ..], 16) catch continue;
        if (addr >= start and addr < end) return end;
    }
    return 0;
}
var maps_buf: [128 * 1024]u8 = undefined;

// ------------------------------------------------------------------ memory access

fn loadU32(p: [*]const u8, off: usize) u32 {
    return std.mem.readInt(u32, p[off..][0..4], .little);
}

fn loadF32(p: [*]const u8, off: usize) f32 {
    return @bitCast(loadU32(p, off));
}

/// True if the whole record lives inside the mapping recorded at track time.
fn inRange(t: *Tracked) bool {
    const a = getAddr(t);
    return a != 0 and a + rec_end <= @atomicLoad(usize, &t.end, .monotonic) and a % 4 == 0;
}

fn doDump(addr_tok: []const u8, len_tok: []const u8, path_tok: []const u8) void {
    const addr = std.fmt.parseInt(usize, addr_tok, 16) catch return;
    const len = std.fmt.parseInt(usize, len_tok, 16) catch return;
    const path = std.mem.printSentinel(&tmp_path_buf, "{s}", .{path_tok}, 0) catch return;
    const bytes: []const u8 = @as([*]const u8, @ptrFromInt(addr))[0..len];
    if (!writeFile(path, bytes)) _ = linux.unlink(path);
}

fn parseBytes(tok: []const u8, buf: []u8) []u8 {
    return std.fmt.hexToBytes(buf, tok) catch buf[0..0];
}

fn doPoke(addr_tok: []const u8, it: *std.mem.TokenIterator(u8, .scalar)) void {
    const addr = std.fmt.parseInt(usize, addr_tok, 16) catch return;
    const dst: [*]u8 = @ptrFromInt(addr);
    var written: usize = 0;
    while (it.next()) |tok| {
        var scratch: [256]u8 = undefined;
        const bytes = parseBytes(tok, &scratch);
        @memcpy(dst[written..][0..bytes.len], bytes);
        written += bytes.len;
    }
}

/// hold: pin `val` at `addr` for `ms`.
fn doHold(addr_tok: []const u8, val_tok: []const u8, ms_tok: []const u8) void {
    const addr = std.fmt.parseInt(usize, addr_tok, 16) catch return;
    const ms = std.fmt.parseInt(u64, ms_tok, 10) catch return;
    var buf: [32]u8 = undefined;
    const bytes = parseBytes(val_tok, &buf);
    if (bytes.len == 0) return;
    const dst: [*]u8 = @ptrFromInt(addr);
    const deadline = now() + ms * std.time.ns_per_ms;
    while (now() < deadline) {
        @memcpy(dst[0..bytes.len], bytes);
        sleepNs(pin_ns);
    }
}

/// add: accumulate a float32/float64 delta for `ms`. Physics rewrites constants every
/// tick; it cannot ignore a value that keeps running away.
fn doAdd(addr_tok: []const u8, val_tok: []const u8, ms_tok: []const u8) void {
    const addr = std.fmt.parseInt(usize, addr_tok, 16) catch return;
    const ms = std.fmt.parseInt(u64, ms_tok, 10) catch return;
    var buf: [8]u8 = undefined;
    const bytes = parseBytes(val_tok, &buf);
    const deadline = now() + ms * std.time.ns_per_ms;
    if (bytes.len == 4) {
        const delta: f32 = @bitCast(std.mem.readInt(u32, bytes[0..4], .little));
        const dst: *f32 = @ptrFromInt(addr);
        while (now() < deadline) {
            dst.* += delta;
            sleepNs(pin_ns);
        }
    } else if (bytes.len == 8) {
        const delta: f64 = @bitCast(std.mem.readInt(u64, bytes[0..8], .little));
        const dst: *f64 = @ptrFromInt(addr);
        while (now() < deadline) {
            dst.* += delta;
            sleepNs(pin_ns);
        }
    }
}

/// track: set (or clear) what the publisher samples.
///
/// Reconfiguring is a window in which addresses and bounds disagree, and a sample taken
/// inside it would be half old, half new. So: drop every bound first (nothing is in range,
/// nothing gets published), set all addresses, then set the bounds.
fn doTrack(toks: *std.mem.TokenIterator(u8, .scalar)) void {
    const g = @atomicLoad(usize, &g_gen, .monotonic);
    @atomicStore(usize, &g_gen, g + 1, .monotonic); // odd: reconfiguring
    defer @atomicStore(usize, &g_gen, g + 2, .monotonic);
    const all = .{ &g_p1, &g_p2, &g_score, &g_tick };
    var addrs: [all.len]usize = undefined;
    inline for (0..all.len) |k| {
        const tok = toks.next() orelse "";
        addrs[k] = std.fmt.parseInt(usize, tok, 16) catch 0;
    }
    inline for (all) |t| @atomicStore(usize, &t.end, 0, .monotonic);
    inline for (all, 0..) |t, k| @atomicStore(usize, &t.addr, addrs[k], .monotonic);
    inline for (all, 0..) |t, k| {
        const end = if (addrs[k] == 0) 0 else regionEnd(addrs[k]);
        @atomicStore(usize, &t.end, end, .monotonic);
    }
}

// ------------------------------------------------------------------ the publisher

fn publish(seq: u64, tick: u32) void {
    const gen = @atomicLoad(usize, &g_gen, .monotonic);
    if (gen % 2 != 0) return; // a reconfigure is in flight
    var snap: Snapshot = std.mem.zeroes(Snapshot);
    snap.magic = magic;
    snap.version = version;
    snap.seq = seq;
    snap.t_ns = now();
    snap.tick = tick;
    if (getAddr(&g_tick) != 0) snap.flags |= flag_tick;
    if (inRange(&g_p1)) {
        const p: [*]const u8 = @ptrFromInt(getAddr(&g_p1));
        snap.p1_x = loadF32(p, off_x);
        snap.p1_y = loadF32(p, off_y);
        snap.p1_facing = loadF32(p, off_facing);
        snap.p1_anim = loadU32(p, off_anim);
        snap.flags |= flag_p1;
    }
    if (inRange(&g_p2)) {
        const p: [*]const u8 = @ptrFromInt(getAddr(&g_p2));
        snap.p2_x = loadF32(p, off_x);
        snap.p2_y = loadF32(p, off_y);
        snap.p2_facing = loadF32(p, off_facing);
        snap.p2_anim = loadU32(p, off_anim);
        snap.flags |= flag_p2;
    }
    if (inRange(&g_score)) {
        snap.score_orange = loadU32(@ptrFromInt(getAddr(&g_score)), 0);
        snap.flags |= flag_score;
    }
    // Publish nothing without a fighter: untracked, or a reconfigure caught mid-flight
    // (addresses/bounds disagree for a few microseconds). A consumer waiting for a new seq
    // then times out instead of reading a sample it has to second-guess.
    if (snap.flags & (flag_p1 | flag_p2) == 0) return;
    if (@atomicLoad(usize, &g_gen, .monotonic) != gen) return; // reconfigured while sampling
    // temp + rename: a reader sees the old sample or the new one, never half of either
    if (!writeFile(state_tmp, std.mem.asBytes(&snap))) return;
    _ = linux.renameat(linux.AT.FDCWD, state_tmp, linux.AT.FDCWD, state_path);
}

fn publisher() void {
    var seq: u64 = 0;
    var last_tick: u32 = 0;
    var last_pub: u64 = 0;
    while (true) {
        sleepNs(sample_ns);
        if (getAddr(&g_p1) == 0 and getAddr(&g_p2) == 0) continue;
        const t = now();
        var tick: u32 = 0;
        if (inRange(&g_tick)) {
            tick = loadU32(@ptrFromInt(getAddr(&g_tick)), 0);
            if (tick == last_tick) continue; // one sample per game tick, not per wakeup
            last_tick = tick;
        } else if (t - last_pub < fallback_publish_ns) {
            continue;
        }
        last_pub = t;
        seq += 1;
        publish(seq, tick);
    }
}

// ------------------------------------------------------------------ input (XTEST)
//
// xdotool spends 16 ms forking and exec'ing before it sends anything; the event it sends
// is an XTEST fake key. We are already inside the process with DISPLAY set, so we can send
// the same event ourselves for ~50 us. The libraries are dlopen'd (no link dependency, no
// dev headers needed) and only on the first key command; if either is missing, `key` is a
// no-op and the caller keeps using xdotool.
const x11 = struct {
    const Display = anyopaque;

    var XOpenDisplay: ?*const fn (?[*:0]const u8) callconv(.c) ?*Display = null;
    var XStringToKeysym: ?*const fn ([*:0]const u8) callconv(.c) c_ulong = null;
    var XKeysymToKeycode: ?*const fn (*Display, c_ulong) callconv(.c) u8 = null;
    var XTestFakeKeyEvent: ?*const fn (*Display, c_uint, c_int, c_ulong) callconv(.c) c_int = null;
    var XFlush: ?*const fn (*Display) callconv(.c) c_int = null;
    var display: ?*Display = null;
    var tried = false;

    fn ready() bool {
        if (display != null) return true;
        if (tried) return false;
        tried = true;
        var xl = std.DynLib.open("libX11.so.6") catch return false;
        var xt = std.DynLib.open("libXtst.so.6") catch return false;
        XOpenDisplay = xl.lookup(@TypeOf(XOpenDisplay.?), "XOpenDisplay") orelse return false;
        XStringToKeysym = xl.lookup(@TypeOf(XStringToKeysym.?), "XStringToKeysym") orelse return false;
        XKeysymToKeycode = xl.lookup(@TypeOf(XKeysymToKeycode.?), "XKeysymToKeycode") orelse return false;
        XFlush = xl.lookup(@TypeOf(XFlush.?), "XFlush") orelse return false;
        XTestFakeKeyEvent = xt.lookup(@TypeOf(XTestFakeKeyEvent.?), "XTestFakeKeyEvent") orelse return false;
        display = XOpenDisplay.?(null) orelse return false; // null = $DISPLAY
        return true;
    }

    fn keycode(name: []const u8) ?c_uint {
        var buf: [64:0]u8 = undefined;
        const z = std.mem.printSentinel(&buf, "{s}", .{name}, 0) catch return null;
        const ks = XStringToKeysym.?(z);
        if (ks == 0) return null;
        const kc = XKeysymToKeycode.?(display.?, ks);
        return if (kc == 0) null else kc;
    }

    fn event(kc: c_uint, press: bool) void {
        _ = XTestFakeKeyEvent.?(display.?, kc, @intFromBool(press), 0);
        _ = XFlush.?(display.?);
    }
};

/// key: press and release `name` with `ms` held. Blocking on purpose — the hold is what
/// makes the press survive the game's 60 Hz input poll.
fn doKey(name: []const u8, ms: u64) void {
    if (!x11.ready()) return;
    const kc = x11.keycode(name) orelse return;
    x11.event(kc, true);
    sleepNs(ms * std.time.ns_per_ms);
    x11.event(kc, false);
}

fn doKeyEdge(name: []const u8, press: bool) void {
    if (!x11.ready()) return;
    const kc = x11.keycode(name) orelse return;
    x11.event(kc, press);
}

// ------------------------------------------------------------------ the poll loop

fn dispatch(line: []const u8) void {
    var it = std.mem.tokenizeScalar(u8, line, ' ');
    const verb = it.next() orelse return;
    if (std.mem.eql(u8, verb, "dump")) {
        const a = it.next() orelse return;
        const l = it.next() orelse return;
        const p = it.next() orelse return;
        doDump(a, l, p);
    } else if (std.mem.eql(u8, verb, "poke")) {
        const a = it.next() orelse return;
        doPoke(a, &it);
    } else if (std.mem.eql(u8, verb, "hold")) {
        const a = it.next() orelse return;
        const v = it.next() orelse return;
        const ms = it.next() orelse return;
        doHold(a, v, ms);
    } else if (std.mem.eql(u8, verb, "add")) {
        const a = it.next() orelse return;
        const v = it.next() orelse return;
        const ms = it.next() orelse return;
        doAdd(a, v, ms);
    } else if (std.mem.eql(u8, verb, "key")) {
        const name = it.next() orelse return;
        const ms = std.fmt.parseInt(u64, it.next() orelse "120", 10) catch 120;
        doKey(name, ms);
    } else if (std.mem.eql(u8, verb, "kd")) {
        doKeyEdge(it.next() orelse return, true);
    } else if (std.mem.eql(u8, verb, "ku")) {
        doKeyEdge(it.next() orelse return, false);
    } else if (std.mem.eql(u8, verb, "track")) {
        doTrack(&it);
    } else if (std.mem.eql(u8, verb, "ping")) {
        var buf: [64]u8 = undefined;
        const msg = std.mem.print(&buf, "pong {d}\n", .{g_pid}) catch return;
        _ = writeFile(res_path, msg);
    }
}

fn loop() void {
    var file: [max_line * 8]u8 = undefined;
    while (true) {
        sleepNs(poll_ns);
        // CLAIM FIRST, then read. Reading first and renaming afterwards loses a command
        // written in between (rename moves whatever is at the path now). After a
        // successful rename the file is ours alone and a new write survives.
        if (!ok(linux.renameat(linux.AT.FDCWD, cmd_path, linux.AT.FDCWD, done_path))) continue;
        claim: {
            defer _ = linux.unlink(done_path); // deleted only after the batch has run
            const n = readFile(done_path, &file) orelse break :claim;
            var rest = file[0..n];
            while (std.mem.indexOfScalar(u8, rest, '\n')) |nl| {
                dispatch(std.mem.trimEnd(u8, rest[0..nl], "\r"));
                rest = rest[nl + 1 ..];
            }
            if (std.mem.trim(u8, rest, " \t\r").len > 0) dispatch(rest);
        }
    }
}
const max_line = 512;

// ------------------------------------------------------------------ entry point

fn boot() callconv(.c) void {
    g_pid = @intCast(linux.getpid());
    cmd_path = std.mem.printSentinel(&cmd_path_buf, "/tmp/nid_cmd_{d}", .{g_pid}, 0) catch return;
    res_path = std.mem.printSentinel(&res_path_buf, "/tmp/nid_res_{d}", .{g_pid}, 0) catch return;
    done_path = std.mem.printSentinel(&done_path_buf, "/tmp/nid_cmd_{d}.done", .{g_pid}, 0) catch return;
    state_path = std.mem.printSentinel(&state_path_buf, "/tmp/nid_state_{d}", .{g_pid}, 0) catch return;
    state_tmp = std.mem.printSentinel(&state_tmp_buf, "/tmp/nid_state_{d}.tmp", .{g_pid}, 0) catch return;
    if (std.Thread.spawn(.{}, loop, .{})) |t| t.detach() else |_| {}
    if (std.Thread.spawn(.{}, publisher, .{})) |t| t.detach() else |_| {}
}

export const nid_ctors: [1]*const fn () callconv(.c) void linksection(".init_array") = .{&boot};

/// Exported so a test can prove the library loaded and ran its constructor.
export fn nid_spy_pid() callconv(.c) i32 {
    return g_pid;
}
