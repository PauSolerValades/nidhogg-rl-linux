#!/usr/bin/env python3
"""Shared measurement primitives for the memory-hunt workers.

Every experiment in this project ends up needing the same five things, so they live
here once and both workers run *identical* measurement code — only their strategy
differs, which is what makes their results comparable.

Environment (set by spawn_workers.sh):
  NIDFARM            farm root for this worker (own prefixes, procs.json, logs)
  NID_DISPLAY_BASE   Xvfb display base for this worker (:10 for A, :20 for B)
  NIDTAG             worker tag, namespaces artifact files
  NIDART             artifact directory

The method that matters: **pause the game, then write**. Pausing freezes the
simulation while the renderer keeps drawing, so
  * nothing drifts on its own (measured: 0 px between frames), and
  * a written value only changes the picture if the renderer reads it as state —
    velocities and accumulators do nothing without ticks.
A real position write repaints a sprite-sized box. Camera/view/surface writes repaint
the whole frame, which is how they identify themselves.
"""
import importlib.util
import os
import struct
import time
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "n", Path(__file__).resolve().parent / "nidlinux.py")
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)

TAG = os.environ.get("NIDTAG", "")
ART = Path(os.environ.get("NIDART", f"/tmp/nidart-{TAG or 'x'}"))
ART.mkdir(parents=True, exist_ok=True)

PAUSE_BOX = (120, 110, 205, 180)     # x0, y0, x1, y1 of the pause menu, excluded from diffs
WARMUP = 13.0


# ---------------------------------------------------------------- lifecycle


def pid_of(i):
    return n._game_pid(i)


def restart(i):
    n.stop_id(i)
    n.start_ids([i])
    return pid_of(i)


def held(i, keysym, wait=1.2):
    """Key press that ALWAYS registers.

    xdotool's instant press/release (~10 ms) can fall entirely between two 60 Hz steps,
    and GameMaker's keyboard_check_pressed then never sees it. Holding 120 ms made menu
    navigation 100% reliable where it used to be a coin flip.
    """
    n.key(i, keysym, hold=0.12)
    time.sleep(wait)


def ensure_menu(i, tries=5):
    """Press Return until a menu (selection dot) is on screen."""
    for _ in range(tries):
        if selected_y(i) is not None:
            return True
        held(i, "Return", 2.0)
    return selected_y(i) is not None


def enter_live_match(i, begin_attempts=2):
    """Reach a REAL match: MENU -> SINGLE PLAYER -> TRAINING -> ladder -> BEGIN.

    The READY screen from `enter_match` is NOT a fight: holding a direction only scrolls
    the camera there, and the fighters never move in world space. This path reaches a
    match with a live CPU (verify with cpu_motion()).
    """
    if not ensure_menu(i):
        return False
    held(i, "Up", 1.0)             # MULTIPLAYER (default) -> SINGLE PLAYER
    held(i, "Return", 1.6)         # -> SINGLE PLAYER screen (HOW TO PLAY / TRAINING)
    held(i, "Return", 1.6)         # TRAINING -> opponent ladder
    for _ in range(begin_attempts):
        for _ in range(4):         # BEGIN sits at the bottom of the ladder
            held(i, "Down", 0.7)
        held(i, "Return", 2.0)
        if sprite_present(i):
            return True
        held(i, "Up", 0.7)
    return sprite_present(i)


def yellow_screen_x(i, name="yx", y0=40, y1=165):
    """Robust screen x of P1: pure yellow, play area only, densest 24-px column cluster.

    A plain centroid is not enough: in dark arenas the goal flag is a huge yellow blob and
    the fighter is small, so the centroid lands between them.
    """
    a = frame(i, name)
    if a is None:
        return None
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 240) & (g > 240) & (b < 80)
    m[:y0, :] = False
    m[y1:, :] = False
    ys, xs = np.nonzero(m)
    if len(xs) < 15:
        return None
    hist = np.bincount(xs, minlength=320)
    win = np.convolve(hist, np.ones(24), "same")
    peak = int(np.argmax(win))
    lo, hi = max(0, peak - 14), min(320, peak + 14)
    sel = xs[(xs >= lo) & (xs <= hi)]
    return float(sel.mean()) if len(sel) else None


def _sign_of_delta(i, key, hold=0.45):
    x0 = yellow_screen_x(i, "dr0")
    if x0 is None:
        return 0.0
    n.key(i, key, hold=hold)
    time.sleep(0.25)
    x1 = yellow_screen_x(i, "dr1")
    return 0.0 if x1 is None else x1 - x0


def drivable(i, hold=0.45, min_px=8.0):
    """Does our input actually move P1? Requires the delta to *reverse* with the key.

    A plain magnitude is not enough: the attract demo's own AI moves the fighter ~10-12 px
    per 0.7 s, which passes any magnitude threshold. Our keys, by contrast, must produce
    opposite-sign deltas for `d` and `a`, twice in a row. Chance of that happening on its own
    is ~6%.
    """
    n.key(i, "a", hold=1.4)                      # park against the left wall first
    time.sleep(0.3)
    deltas = [_sign_of_delta(i, "d", hold), _sign_of_delta(i, "a", hold),
              _sign_of_delta(i, "d", hold), _sign_of_delta(i, "a", hold)]
    ok = (deltas[0] > min_px and deltas[1] < -min_px
          and deltas[2] > min_px and deltas[3] < -min_px)
    return max(deltas) - min(deltas) if ok else 0.0


def enter_match(i, tries=4):
    """Enter-only menu path -> LOCAL READY screen, verified drivable with held keys."""
    for _ in range(tries):
        time.sleep(WARMUP)
        for _ in range(6):
            held(i, "Return", 1.5)
        time.sleep(0.5)
        if sprite_present(i) and drivable(i, "d") > 15:
            return True
    return False


def sprite_present(i):
    """P1 is the only pure-yellow thing on screen (P2 is orange, goal line dim)."""
    a = frame(i, "present")
    if a is None:
        return False
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    return int(((r > 240) & (g > 240) & (b < 80)).sum()) >= 20


# ---------------------------------------------------------------- eyes


def _path(name):
    """Don't double-suffix: '/tmp/x.png' stays as given, 'shot' becomes '<ART>/shot.png'."""
    p = str(ART / name) if not str(name).startswith("/") else str(name)
    return p if p.lower().endswith(".png") else p + ".png"


def grab(i, name):
    return n.grab(i, _path(name))


def frame(i, name="f"):
    return n.frame(i, _path(name))


def frozen_noise(i):
    """Two frames of a paused game must be identical; returns changed pixel count."""
    a = frame(i, "fz1")
    time.sleep(0.45)
    b = frame(i, "fz2")
    return n.stable_change((a, b), b)


def pause(i):
    n.key(i, "Escape")
    time.sleep(1.2)
    return frozen_noise(i)


def effect(base, after, box=PAUSE_BOX):
    """(changed pixel count, bbox (w, h)) outside the pause box."""
    if base is None or after is None:
        return 0, None
    diff = np.abs(after.astype(int) - base.astype(int)).max(2) > 24
    x0, y0, x1, y1 = box
    diff[y0:y1, x0:x1] = False
    ys, xs = np.nonzero(diff)
    if not len(xs):
        return 0, None
    return len(xs), (int(xs.max() - xs.min()), int(ys.max() - ys.min()))


def sprite_bbox(i):
    """Bounding box of P1 while paused (dimmed to ~(123,92,0))."""
    a = frame(i, "spr")
    if a is None:
        return None
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 100) & (r < 160) & (g > 70) & (g < 115) & (b < 25)
    x0, y0, x1, y1 = PAUSE_BOX
    m[y0:y1, x0:x1] = False
    ys, xs = np.nonzero(m)
    if len(xs) < 30:
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


# ---------------------------------------------------------------- memory


def pin(i, pid, addr, value, width=4, ms=400):
    """Pin a value across frames (spy writes at 2 kHz) and return the frame it caused."""
    fmt = "<f" if width == 4 else "<d"
    Path(f"/tmp/nid_cmd_{pid}").write_text(
        f"hold {addr:x} {struct.pack(fmt, value).hex()} {ms}\n")
    time.sleep(0.2)
    return frame(i, f"pin{addr:x}")


def read_f(pid, addr, width=4):
    raw = n.memory(pid, addr, width, str(ART / "read.bin"), )
    return struct.unpack("<f" if width == 4 else "<d", raw)[0] if raw else None


def read_x(pid, rec_addr):
    """P1/P2 x for a record base returned by find_fighters (field at +0xEC, not the base)."""
    return read_f(pid, rec_addr + X_OFF)


def read_y(pid, rec_addr):
    return read_f(pid, rec_addr + Y_OFF)


def regions(pid, min_size=1 << 20, max_size=200 << 20):
    out = []
    for line in open(f"/proc/{pid}/maps"):
        p = line.split()
        if p[1][:2] != "rw" or (len(p) > 5 and p[-1].startswith("/")):
            continue
        a, b = (int(x, 16) for x in p[0].split("-"))
        if min_size <= b - a <= max_size:
            out.append((a, b))
    return out


def dump_f32(pid, addr, size):
    raw = n.memory(pid, addr, size, str(ART / "dump.bin"))
    return np.frombuffer(raw, "<f4") if raw else None


def coord_pairs(pid, regions_, xmax=1100.0, ymax=260.0):
    """Structural candidate generator: (x, y) float pairs in plausible ranges.

    Motion-based candidate generation is a trap: it finds everything *derived* from the
    position (camera, view, surface, draw records) and buries the instance. Shape does
    not move, so it cannot be fooled.
    """
    pairs = []
    for a, b in regions_:
        v = dump_f32(pid, a, b - a)
        if v is None:
            continue
        for stride in (1, 2, 4):
            if len(v) <= stride:
                continue
            xs = v[:-stride]
            ys = v[stride:]
            with np.errstate(invalid="ignore"):
                hit = ((xs > 0) & (xs < xmax) & (ys > 20) & (ys < ymax)
                       & (ys < xs) & np.isfinite(xs) & np.isfinite(ys))
            for k in np.nonzero(hit)[0][:20000]:
                pairs.append((a + int(k) * 4, stride * 4))
    return pairs


# ---------------------------------------------------------------- menu (verified by the ● marker)
#
# The selected menu item is marked by a yellow dot at x~200 while the labels stop at
# x~185. So the selected row is simply the row whose yellow pixels reach furthest right.
# Nothing is hardcoded about item order: enumerate_rows() learns it by pressing Down and
# watching where the dot lands.

def menu_geometry(i, name="geo"):
    """(box_top, box_bottom, bar_row) for a menu box, or None.

    The selection is the **grey highlight bar**, not the yellow ● dots: every row carries a
    dot, so a dot-based detector is meaningless (this cost several rounds of contradictory
    "the selection moved" observations).

    Sanity checks matter: the title screen also has large dark areas, so a box must look like
    a box (30..90 px tall, mostly dark, bar strictly inside it) or we report None.
    """
    a = frame(i, name if str(name).endswith(".png") else _path(name + ".png"))
    if a is None:
        return None
    lum = a.mean(2)
    dark = (lum < 30).mean(1)
    rows = np.nonzero(dark > 0.55)[0]          # a menu box is dense dark, not a sky gradient
    if len(rows) < 15:
        return None
    groups = np.split(rows, np.nonzero(np.diff(rows) > 3)[0] + 1)
    groups = [g for g in groups if len(g) >= 15]
    if not groups:
        return None
    g = max(groups, key=len)
    top, bot = int(g.min()), int(g.max())
    if not (30 <= bot - top <= 90):
        return None
    box = lum[top:bot + 1]
    grey = ((box > 55) & (box < 215)).mean(1)
    cand = np.nonzero(grey > 0.55)[0]
    if not len(cand):
        return top, bot, None
    cg = np.split(cand, np.nonzero(np.diff(cand) > 2)[0] + 1)
    bar = max(cg, key=len)
    if not (3 <= len(bar) <= 20):
        return top, bot, None
    return top, bot, int(top + bar.mean())


def ensure_menu(i, tries=6, wait=0.6):
    """Get a menu on screen and keep it: the menu times out back to the title on idle.

    Returns the geometry, or None. Deliberately fast: every second spent measuring is a second
    of the timeout budget spent.
    """
    for _ in range(tries):
        geo = menu_geometry(i, f"em{_}")
        if geo and geo[2] is not None:
            return geo
        n.key(i, "Return", hold=0.12)
        time.sleep(wait)
    return menu_geometry(i, "em_last")


def menu_step(i, keysym, wait=0.45):
    """Press one menu key and report the bar before/after (bar None = cell/screen, not a row)."""
    before = menu_geometry(i, "ms_a")
    n.key(i, keysym, hold=0.12)
    time.sleep(wait)
    after = menu_geometry(i, "ms_b")
    return before, after


def screen_sig(i, name="sig"):
    """Compact fingerprint of the menu box: (height, bar_row, coarse pixel code).

    Used to recognise a screen instead of guessing it from timing. Calibrated once, then the
    navigator can tell "the key did nothing" from "we are somewhere else now".
    """
    geo = menu_geometry(i, name)
    if geo is None:
        return None
    top, bot, bar = geo
    a = frame(i, _path(name + "s.png") if not str(name).endswith(".png") else name)
    lum = a.mean(2)[top:bot + 1]
    h, w = lum.shape
    cells = lum[: (h // 8) * 8, : (w // 8) * 8].reshape(h // 8, 8, w // 8, 8).mean((1, 3))
    code = tuple(int(c // 32) for c in cells.flatten())
    return {"top": top, "bottom": bot, "bar": bar, "h": bot - top, "code": code}


def selected_y(i, name="sel"):
    a = frame(i, name)
    if a is None:
        return None
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 190) & (g > 170) & (b < 130)
    m[:108, :] = False      # the logo's tail reaches x~213 at y<105: never a menu dot
    m[182:, :] = False
    m[:, :95] = False
    m[:, 260:] = False
    xmax = np.zeros(m.shape[0], dtype=int)
    for y in range(95, 182):
        row = np.nonzero(m[y])[0]
        if len(row):
            xmax[y] = row.max()
    ys = np.nonzero((xmax > 197) & (xmax < 218))[0]
    return int(ys.mean()) if len(ys) else None


def enumerate_rows(i, presses=8):
    """Item y-positions in menu order, learned by pressing Down (the list wraps)."""
    seen = []
    y = selected_y(i)
    if y is None:
        return seen
    seen.append(y)
    for _ in range(presses):
        n.key(i, "Down")
        time.sleep(0.7)
        y = selected_y(i)
        if y is None:
            break
        if y in seen:
            break
        seen.append(y)
    return seen


def goto_row(i, rows, index, tries=12):
    """Press Down until the dot sits on rows[index]."""
    target = rows[index]
    for _ in range(tries):
        y = selected_y(i)
        if y is None:
            return False
        if abs(y - target) <= 2:
            return True
        n.key(i, "Down")
        time.sleep(0.7)
    return False


# ---------------------------------------------------------------- is it a real fight?

def orange_x(i, name="p2"):
    """P2 is orange (255,160,64); P1 is pure yellow, so they never alias."""
    a = frame(i, name)
    if a is None:
        return None
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 200) & (g > 120) & (g < 205) & (b < 110)
    ys, xs = np.nonzero(m)
    return float(xs.mean()) if len(xs) > 30 else None


def cpu_motion(i, seconds=4.0):
    """A real TRAINING match has a CPU that plays; the READY screen never moves.

    This is the macOS harness's entry verifier, and it cannot be faked by an animation.
    """
    xs = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        x = orange_x(i, f"cpu{len(xs)}")
        if x is not None:
            xs.append(x)
        time.sleep(0.4)
    return (max(xs) - min(xs)) if len(xs) >= 3 else 0.0


# ---------------------------------------------------------------- fighter records (proven layout)
#
# Worker C proved this layout from attract-mode jump arcs, with no menu and no input:
#   record stride 0x200, x at +0xEC, y at +0xF0 (both float32, room space, fractional),
#   duplicates at +0xFC / +0x100, bbox candidates around +0x120..+0x12C.
# x@+0xEC was seen walking 787.4 -> 758.3; y@+0xF0 arcing 111.4 -> 12.1 -> 143.8.
# Addresses shift per room; the offsets do not.

REC = 0x200
X_OFF = 0xEC
Y_OFF = 0xF0


def biggest_heap(pid):
    """DEPRECATED for dumping: on some prefixes the largest rw mapping is a 133 MB zero-filled
    reservation (worker m measured this), so dumping it yields 34M zeros. Use record_regions()."""
    return max(regions(pid), key=lambda r: r[1] - r[0])


def record_regions(pid, min_size=1 << 20):
    """Regions worth dumping: those that actually contain object records.

    Three traps this avoids, all measured today:
      * the largest rw mapping can be a 133 MB zero-filled reservation (worker m);
      * sampling a few pages lets mostly-empty regions through (only 9 nonzero u32 in 1 MB);
      * the object heap can move between rooms, so "the" heap must be re-discovered.
    A region qualifies only if a 0x200-stride record in it has plausible coordinates.
    """
    cands = [r for r in regions(pid) if r[1] - r[0] >= min_size]
    reqs = [(a, b - a, f"/tmp/rr_{k}.bin") for k, (a, b) in enumerate(cands)]
    out = []
    for (a, b), raw in zip(cands, n.memory_many(pid, reqs)):
        if not raw:
            continue
        f = np.frombuffer(raw[: len(raw) // 4 * 4], "<f4")
        idx = np.arange(0, len(f) - Y_OFF // 4 - 1, REC // 4)
        xs, ys = f[idx + X_OFF // 4], f[idx + Y_OFF // 4]
        with np.errstate(invalid="ignore"):
            ok = (np.isfinite(xs) & np.isfinite(ys)
                  & (xs > 0) & (xs < 2400) & (ys > 15) & (ys < 400))
        if ok.any():
            out.append((a, b))
    return out


def fighter_records(pid, heap=None):
    """[(base_addr, x, y)] for every 0x200 record with room-plausible fractional state."""
    a, b = heap or biggest_heap(pid)
    v = dump_f32(pid, a, b - a)
    if v is None:
        return []
    idx = np.arange(0, len(v) - (Y_OFF // 4) - 1, REC // 4)
    x = v[idx + X_OFF // 4]
    y = v[idx + Y_OFF // 4]
    with np.errstate(invalid="ignore"):
        ok = (np.isfinite(x) & np.isfinite(y)
              & (x > 0) & (x < 1100) & (y > 15) & (y < 260)
              & (x != np.round(x)) & (y != np.round(y)))
    sel = np.nonzero(ok)[0]
    return [(a + int(idx[j]) * 4, float(x[j]), float(y[j])) for j in sel]


def moving_fighters(pid, wait=0.45, lo=1.0, hi=120.0):
    """The records whose x moved between two dumps: those are the fighters."""
    heap = biggest_heap(pid)
    before = {a: (x, y) for a, x, y in fighter_records(pid, heap)}
    time.sleep(wait)
    after = {a: (x, y) for a, x, y in fighter_records(pid, heap)}
    out = []
    for a in before.keys() & after.keys():
        dx = after[a][0] - before[a][0]
        if lo <= abs(dx) <= hi:
            out.append((a, before[a], after[a], dx))
    return out


# ---------------------------------------------------------------- proven fighter enumeration
#
# Round 6 proved the object-type discriminator:
#   u32 @ +0x88 holds a pointer to the object definition. Two records share it: the two
#   fighter bodies (P1 and P2). The sword has body+0x400, the arm body+0x200, particles
#   differ. The pointer value itself changes per run, so it is discovered by grouping.
TYPE_OFF = 0x88


_HEAP_CACHE = {}


def _cached_heaps(pid):
    """Regions that produced records last time (validated against /proc/<pid>/maps)."""
    hit = _HEAP_CACHE.get(pid)
    if not hit:
        return None
    live = set(regions(pid))
    keep = [r for r in hit if r in live]
    return keep or None


def find_fighters(pid, heap=None):
    """[(addr, x, y, type_ptr)] for the fighter bodies — type found by grouping, not by ID.

    Verified against the orange sprite's on-screen x within 1.4..1.6 px (fixed camera), and
    P1's x tracked the yellow sprite 1:1 over 8/8 `d`/`a` transitions.
    """
    # biggest_heap() is not the object heap: on some prefixes the largest rw mapping is a
    # 133 MB zero-filled reservation, and scanning only that returns [] in EVERY room
    # (measured on READY and in a match).  Scan every rw region and merge the findings.
    if heap:
        heaps = [heap]
    else:
        heaps = _cached_heaps(pid) or [r for r in regions(pid) if r[1] - r[0] >= (1 << 20)]
    # one round trip for all regions instead of one per region (saves ~50 ms x N)
    reqs = [(a, b - a, f"/tmp/ff_{i}.bin") for i, (a, b) in enumerate(heaps)]
    blobs = n.memory_many(pid, reqs)
    out = []
    for (a, b), raw in zip(heaps, blobs):
        if raw is None:
            continue
        u32 = np.frombuffer(raw[: len(raw) // 4 * 4], "<u4")
        idx = np.arange(0, min(len(u32) - TYPE_OFF // 4, len(u32)), REC // 4)
        types = u32[idx + TYPE_OFF // 4]
        vals, counts = np.unique(types, return_counts=True)
        for v, c in zip(vals, counts):
            if c != 2 or v == 0:
                continue
            for j in np.nonzero(types == v)[0]:
                o = int(idx[j]) * 4
                x = np.frombuffer(raw[o + X_OFF: o + X_OFF + 4], "<f4")[0]
                y = np.frombuffer(raw[o + Y_OFF: o + Y_OFF + 4], "<f4")[0]
                if not (np.isfinite(x) and np.isfinite(y)):
                    continue
                # rooms differ in width: the READY room is ~320/960 wide, a castle match was
                # measured with x up to 1856. A hard 1100 cap silently hid the fighters there.
                if not (0.0 <= x <= 2200.0 and 15.0 <= y <= 300.0):
                    continue
                out.append((a + o, float(x), float(y), int(v)))
    # two instances of one object type only count as fighters if they stand on the same
    # ground line and are actually apart -- this kills the hundreds of junk "pairs" that
    # merely happen to share whatever sits at +0x88 (zero-filled records, decorations).
    pairs = {}
    for rec in out:
        pairs.setdefault(rec[3], []).append(rec)
    pairs_out = [r for g in pairs.values()
                 if len(g) == 2 and abs(g[0][2] - g[1][2]) < 25 and abs(g[0][1] - g[1][1]) > 1
                 for r in g]
    if pairs_out and not heap:
        hit = {r for r in heaps if any(r[0] <= a < r[1] for a, _x, _y, _t in pairs_out)}
        if hit:
            _HEAP_CACHE[pid] = sorted(hit)
    return pairs_out


# ---------------------------------------------------------------- tick counter
#
# A u32 that advances ~60 times a second, proven to exist (worker T: 60.0 Hz, 4% jitter).
# Its address is per process, so it is re-found here instead of cached. Two windows are
# not enough — a one-off step passes any single interval — so every window must agree.

def main_heap(pid):
    """[heap] base and size, or (0, 0). Do not confuse it with biggest_heap()."""
    for line in open(f"/proc/{pid}/maps"):
        if "[heap]" in line:
            a, b = (int(x, 16) for x in line.split()[0].split("-"))
            return a, b - a
    return 0, 0


def find_tick(pid, windows=4, gap=0.9):
    """Address of the 60 Hz counter, or None. Costs `windows` heap dumps (~3 s)."""
    base, size = main_heap(pid)
    if not base:
        return None
    prev = None
    stamp = 0.0
    seen = None
    for k in range(windows):
        raw = n.memory(pid, base, size, str(ART / f"tick{k}.bin"))
        t = time.time()
        if raw is None:
            return None
        cur = np.frombuffer(raw[: len(raw) // 4 * 4], "<u4").astype(np.int64)
        if prev is not None:
            want = 60.0 * (t - stamp)
            d = cur - prev
            ok = np.nonzero((np.abs(d - want) < max(8, 0.2 * want)) & (prev < 0xFFFF0000))[0]
            seen = set(ok.tolist()) if seen is None else (seen & set(ok.tolist()))
        prev, stamp = cur, t
        time.sleep(gap)
    if not seen:
        return None
    return base + min(seen) * 4


# ---------------------------------------------------------------- CONTROL GATE
#
# Falsifiable and READ-ONLY. Writing to a fighter's x at 2 kHz killed the game twice, so the
# gate cannot depend on writes. Three independent, non-destructive checks:
#
#   A control   holding d/a moves the sprite in the key's direction, twice in a row
#               (attract mode's AI also moves fighters -> magnitude alone proves nothing)
#   B identify  among the candidate records, one tracks the sprite's screen x 1:1 on every
#               transition. Selecting by *tracking* (not by a coincidental value match) is
#               what makes this sound: a static prop can sit at the same x and never move.
#   C negative  no second record tracks the yellow sprite equally well
#
# Writes (poke/hold/add) remain a separate capability with their own risk profile.

def identify_p1(i, pid, cycles=6, hold=0.45, settle=0.25, verbose=True):
    """Find the record whose x delta matches the sprite's, sampling BOTH in the same pass.

    Sampling the sprite and the records in separate passes misaligns them in time (one
    transition read 4.7 px of error purely from that). Here every sample reads the sprite
    and all candidate records back to back, so the comparison is like-for-like.
    """
    cands = [r[0] for r in find_fighters(pid)]
    if not cands:
        return None, [], [], []
    n.key(i, "a", hold=1.3)                      # park: room to move right
    time.sleep(0.3)
    sprite = [yellow_screen_x(i, "ip0")]
    recs = {c: [read_x(pid, c)] for c in cands}
    for k in range(cycles * 2):
        n.key(i, "d" if k % 2 == 0 else "a", hold=hold)
        time.sleep(settle)
        sprite.append(yellow_screen_x(i, f"ip{k+1}"))
        for c in cands:
            recs[c].append(read_x(pid, c))
    if any(v is None for v in sprite):
        return None, [], sprite, cands
    sdx = [b - a for a, b in zip(sprite, sprite[1:])]
    scored = []
    for c in cands:
        r = recs[c]
        if any(v is None for v in r):
            continue
        rdx = [b - a for a, b in zip(r, r[1:])]
        errs = [abs(a - b) for a, b in zip(sdx, rdx)]
        scored.append((max(errs), c, errs))
    scored.sort()
    if verbose:
        for score, c, errs in scored:
            print(f"    candidate {c:#x}: max err {score:6.2f} px, "
                  f"median {sorted(errs)[len(errs)//2]:5.2f}")
    if not scored:
        return None, [], sprite, cands
    best = scored[0]
    others = [o for o in scored[1:]]
    return best[1], best[2], sprite, others


def control_gate(i, verbose=True):
    """Returns (ok, evidence). Read-only: safe to run constantly, including from workers."""
    pid = pid_of(i)
    ev = {"A_drivable": 0.0, "P1": None, "errors_px": [], "runners_up": [],
          "C_second_best_error": None}
    if not pid:
        return False, ev

    ev["A_drivable"] = drivable(i)
    if verbose:
        print(f"  A control: {ev['A_drivable']:.1f} px of direction-controlled travel "
              f"(need >15)")

    addr, errs, xs, others = identify_p1(i, pid, verbose=verbose)
    if addr is None:
        if verbose:
            print("  B identify: no record tracks the sprite")
        return False, ev
    med = sorted(errs)[len(errs) // 2] if errs else 99.0
    ev["P1"] = {"addr": f"{addr:#x}", "x": read_x(pid, addr)}
    ev["errors_px"] = [round(e, 2) for e in errs]
    ev["error_median"] = round(med, 2)
    b_ok = len(errs) >= 8 and med < 2.0 and max(errs) < 4.0
    if verbose:
        print(f"  B identify: {addr:#x} tracks the sprite "
              f"(median {ev['error_median']} px, max {max(errs):.2f} px; need median <2, max <4)")

    # C: no other record may track the sprite this well (same pass — free)
    if others:
        ev["runners_up"] = [(f"{a:#x}", round(float(m), 2)) for m, a, _e in others]
        ev["C_second_best_error"] = round(float(others[0][0]), 2)
    c_ok = ev["C_second_best_error"] is not None and ev["C_second_best_error"] > 4.0
    if verbose:
        print(f"  C negative: next-best record error {ev['C_second_best_error']} "
              f"({'ok' if c_ok else 'PROBLEM'})")

    return ev["A_drivable"] > 15 and b_ok and c_ok, ev


# ---------------------------------------------------------------- entry: menu -> READY -> match
#
# The multiplayer-local path is the most useful one for RL: it ends in a match where BOTH
# fighters are ours (self-play on one instance), and the only menu step is "Return x3" from the
# title. The READY screen gates the match: each player stands on their own coloured pad for ~2 s
# and when both are on, stage select appears and a match starts.
#
# All of it is closed-loop on pixels: pads are the widest colour run in the lower half, fighters
# are colour blobs, and "am I on the pad" is a distance comparison. Nothing depends on menu timing.

PAD_COLOURS = {"yellow": (200, 200, 90), "orange": (200, 105, 205, 115)}
P1_KEYS = ("a", "d")          # yellow, measured
P2_KEYS = ("Left", "Right")   # orange: arrows, measured (i/j/k/l do nothing)


def _mask(a, which):
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    if which == "yellow":
        return (r > 200) & (g > 200) & (b < 90)
    return (r > 200) & (g > 105) & (g < 205) & (b < 115)


def _longest_run(row):
    idx = np.nonzero(row)[0]
    if not len(idx):
        return None
    best = cur = [idx[0], idx[0]]
    for a, b in zip(idx, idx[1:]):
        if b - a <= 2:
            cur[1] = b
        else:
            if cur[1] - cur[0] > best[1] - best[0]:
                best = list(cur)
            cur = [b, b]
    if cur[1] - cur[0] > best[1] - best[0]:
        best = list(cur)
    return best


def pad_and_fighter(i, which, name="pad"):
    """(pad_x0, pad_x1, pad_y, fighter_x) or None. None means 'no pad on screen'."""
    a = frame(i, name)
    if a is None:
        return None
    m = _mask(a, which)
    h, w = m.shape
    # A pad is a wide colour run, but a fighter STANDING on it splits the run in two, so
    # measure the whole row (spread + total pixels) instead of the longest single run.
    pad_y, pad_run = None, None
    for y in range(int(h * 0.55), h):
        xs_row = np.nonzero(m[y])[0]
        if len(xs_row) < 25:
            continue
        spread = xs_row.max() - xs_row.min()
        if spread < 25:
            continue
        if pad_run is None or spread > pad_run[1] - pad_run[0]:
            pad_y, pad_run = y, [int(xs_row.min()), int(xs_row.max())]
    if pad_run is None:
        return None
    body = m.copy()
    body[max(0, pad_y - 4):, :] = False
    ys, xs = np.nonzero(body)
    fx = float(xs.mean()) if len(xs) > 20 else None
    return pad_run[0], pad_run[1], int(pad_y), fx


def on_ready_screen(i):
    return pad_and_fighter(i, "yellow", "rd1") is not None


def enter_ready(i, tries=8, wait=1.0):
    """Press Return until fighters are on screen (READY, or a match).

    Deliberately does NOT use pad detection: a fighter standing on its pad *is* the pad's colour,
    so pads vanish exactly when the walk succeeds — which made the old check report failure at the
    moment of success (and "advanced" when nothing had happened).
    """
    for _ in range(tries):
        # READY = both fighters drawn AND the central wall present. The attract demo also draws
        # fighters, so "fighters visible" alone matches the title screen (that false positive
        # made enter_match fail on "wall not found" two seconds later).
        if _fighters_visible(i, "er") and _wall_x(i, "erw") is not None:
            return True
        n.key(i, "Return", hold=0.12)
        time.sleep(wait)
    return _fighters_visible(i, "er_end") and _wall_x(i, "erw2") is not None


def walk_onto_pad(i, which, tol=7, max_steps=30):
    left, right = P1_KEYS if which == "yellow" else P2_KEYS
    for step in range(max_steps):
        loc = pad_and_fighter(i, which, f"w{which}")
        if not loc:
            return False
        px0, px1, _py, fx = loc
        if fx is None:
            return False
        centre = (px0 + px1) / 2
        off = centre - fx
        if abs(off) <= tol:
            return True
        n.key(i, right if off > 0 else left, hold=min(0.35, max(0.06, abs(off) / 400.0)))
        time.sleep(0.12)
    return False


def _wall_x(i, name="wall"):
    """Screen x of the central wall: a tall light-grey vertical band (camera-relative landmark)."""
    a = frame(i, name)
    if a is None:
        return None
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    light = (r > 150) & (r < 235) & (np.abs(r - g) < 18) & (np.abs(g - b) < 18)
    h = light.shape[0]
    band = light[int(h * 0.05):int(h * 0.55), :].mean(0)
    cols = np.nonzero(band > 0.6)[0]
    if len(cols) < 8:
        return None
    groups = np.split(cols, np.nonzero(np.diff(cols) > 4)[0] + 1)
    return float(max(groups, key=len).mean())


def _walk_to_x(i, which, target, tol=8, max_steps=30):
    left, right = P1_KEYS if which == "yellow" else P2_KEYS
    for _ in range(max_steps):
        a = frame(i, f"wx_{which}")
        if a is None:
            return False
        m = _mask(a, which)
        m[int(m.shape[0] * 0.62):, :] = False         # ignore pads/floor
        ys, xs = np.nonzero(m)
        if len(xs) < 20:
            return False
        off = target - float(xs.mean())
        if abs(off) <= tol:
            return True
        n.key(i, right if off > 0 else left, hold=min(0.30, max(0.05, abs(off) / 600.0)))
        time.sleep(0.10)
    return False


def _fighters_visible(i, name="fv"):
    """Are both fighters drawn? (the stage-select preview draws none.)"""
    a = frame(i, name)
    if a is None:
        return False
    h = a.shape[0]
    counts = []
    for which in ("yellow", "orange"):
        m = _mask(a, which)
        m[int(h * 0.62):, :] = False
        counts.append(int(m.sum()))
    return counts[0] > 20 and counts[1] > 20


def _pads_visible(i, name="pv"):
    return (pad_and_fighter(i, "yellow", name + "y") is not None or
            pad_and_fighter(i, "orange", name + "o") is not None)


def on_stage_select(i, name="ss"):
    return not _pads_visible(i, name) and not _fighters_visible(i, name)


def enter_match(i, verbose=True, stand=1.6, tries=3):
    """READY -> BOTH fighters on their pads -> ~1.5 s -> stage select -> match.

    Confirmed by the player who wrote the state machine, and by a controlled test here: ONE
    fighter on its pad does nothing (the game waits on READY indefinitely). Both must stand on
    their pads for ~1.5 s; then an audio cue plays, the floor chandeliers light up and stage
    select appears. A single-pad run only ever looked like success because the other fighter
    happened to be inside its pad's trigger zone already.

    Returns True only when a live match is verified by input.
    """
    for attempt in range(tries):
        if not enter_ready(i):
            if verbose:
                print("  could not reach READY")
            return False
        wx = _wall_x(i)
        if wx is None:
            if verbose:
                print("  wall not found on READY")
            return False
        off = 0.32 * frame(i, "geom").shape[1]
        if find_players_by_input(i, hold=0.4):
            return True                        # already in a live match
        ok1 = _walk_to_x(i, "yellow", wx - off)
        ok2 = _walk_to_x(i, "orange", wx + off)
        if verbose:
            print(f"  pads: yellow={ok1} orange={ok2}; standing {stand}s")
        if not (ok1 and ok2):
            if verbose:
                print(f"  attempt {attempt}: a walk failed, retrying")
            time.sleep(0.5)
            continue
        t0 = time.time()
        seen = False
        while time.time() - t0 < stand + 1.5:
            if on_stage_select(i, f"ss{attempt}"):
                seen = True
                if verbose:
                    print(f"  stage select after {time.time()-t0:.1f}s")
                break
            time.sleep(0.3)
        if not seen:
            if verbose:
                print(f"  attempt {attempt}: no stage select "
                      f"(pads={_pads_visible(i)}, fighters={_fighters_visible(i)})")
            continue
        n.key(i, "Return", hold=0.12)
        time.sleep(2.5)                     # fighters spawn high and fall
        if find_players_by_input(i, hold=0.5):
            return True
        if verbose:
            print("  stage accepted but players not controllable yet")
    return False


def find_fighters_verified(i, hold=0.5, min_move=20.0):
    """The fighter pair, chosen by BEHAVIOUR: P1 moves on 'd' while P2 stays bit-identical.

    `find_fighters()` returns every type-group of two with plausible coordinates — including
    static props. The only reliable discriminator is causality: press a player's key, and exactly
    one member of the pair must move and then stop. Verified in a live match:
    'd' -> x 897 -> 967 (+70, other member constant 1023), 'Right' -> 1023 -> 1095 (+72).

    Returns {"P1": addr, "P2": addr, "type": t, "trace": {...}} or None.
    """
    pid = pid_of(i)
    groups = {}
    for a, x, y, t in find_fighters(pid):
        groups.setdefault(t, []).append(a)
    for t, addrs in groups.items():
        if len(addrs) != 2:
            continue
        a1, a2 = addrs
        before = {a: read_x(pid, a) for a in (a1, a2)}
        n.key(i, "d", hold=hold)
        time.sleep(0.2)
        after_d = {a: read_x(pid, a) for a in (a1, a2)}
        if None in before.values() or None in after_d.values():
            continue
        moved_d = [a for a in (a1, a2) if abs(after_d[a] - before[a]) > min_move]
        still_d = [a for a in (a1, a2) if abs(after_d[a] - before[a]) <= 2.0]
        if len(moved_d) != 1 or len(still_d) != 1:
            continue
        p1, p2 = moved_d[0], still_d[0]
        # the other player's key must move the OTHER record (and leave P1 alone)
        before2 = {a: read_x(pid, a) for a in (a1, a2)}
        n.key(i, "Right", hold=hold)
        time.sleep(0.2)
        after_r = {a: read_x(pid, a) for a in (a1, a2)}
        if None in after_r.values():
            continue
        if abs(after_r[p2] - before2[p2]) > min_move and abs(after_r[p1] - before2[p1]) <= 2.0:
            return {"P1": p1, "P2": p2, "type": t,
                    "trace": {"d": {"p1": [round(before[p1], 1), round(after_d[p1], 1)],
                                    "p2": [round(before[p2], 1), round(after_d[p2], 1)]},
                              "Right": {"p1": [round(before2[p1], 1), round(after_r[p1], 1)],
                                        "p2": [round(before2[p2], 1), round(after_r[p2], 1)]}}}
    return None


def match_state(i):
    """'live' | 'ready' | 'menu' | 'unknown' — so entry never blindly presses keys."""
    if find_fighters_verified(i):
        return "live"
    if on_ready_screen(i):
        return "ready"
    if menu_geometry(i, f"st{i}") is not None:
        return "menu"
    return "unknown"


def ensure_match(i, attempts=3, verbose=True):
    """Get to a *verified live* match from any state, restarting the instance if stale.

    A match left alone for ~10 minutes ends its round and every fighter record freezes, so
    "already in a match" is not the same as "usable". Only the causal test can tell.
    """
    for attempt in range(attempts):
        if find_players_by_input(i, hold=0.4):
            return True
        st = match_state(i)
        if verbose:
            print(f"  attempt {attempt}: state={st}")
        if st == "live":
            return True
        if st == "ready":
            if enter_match(i, verbose=verbose):
                if find_fighters_verified(i):
                    return True
        else:
            if enter_ready(i):
                if enter_match(i, verbose=verbose) and find_players_by_input(i, hold=0.4):
                    return True
        if verbose:
            print("  restarting instance (stale round or wrong screen)")
        n.stop_id(i)
        n.start_ids([i])
        t0 = time.time()
        while time.time() - t0 < 300 and not n.window(i):
            time.sleep(5)
        time.sleep(12)                     # splash is ~10 s of ignored input
    return bool(find_players_by_input(i, hold=0.4))


# ---------------------------------------------------------------- players by input, not by type
#
# find_fighters() groups records by the object-type pointer at +0x88 — a good *candidate*
# generator, but it is not the truth: in a live match P2's records were in a different type group
# than P1's (measured: P1 type 0x174f900 at x 1112; P2 at 0x1908400, x 958 -> 1028 on 'Right').
# The only reliable identification is the input itself:
#
#   press P1's key   -> exactly one record's x advances and then stops  = P1
#   press P2's key   -> another record does the same                    = P2
#
# This also survives room changes, different objects per skin, and duplicates at the same x.

def _all_record_xs(pid, heap=None):
    """{record_addr: x} for every 0x200 record with a plausible coordinate."""
    heaps = [heap] if heap else (_cached_heaps(pid) or
                                 [r for r in regions(pid) if r[1] - r[0] >= (1 << 20)])
    reqs = [(a, b - a, f"/tmp/ax_{i}.bin") for i, (a, b) in enumerate(heaps)]
    out = {}
    for (a, b), raw in zip(heaps, n.memory_many(pid, reqs)):
        if raw is None:
            continue
        f = np.frombuffer(raw[: len(raw) // 4 * 4], "<f4")
        idx = np.arange(0, len(f) - Y_OFF // 4 - 1, REC // 4)
        xs = f[idx + X_OFF // 4]
        ys = f[idx + Y_OFF // 4]
        with np.errstate(invalid="ignore"):
            ok = (np.isfinite(xs) & np.isfinite(ys)
                  & (xs > 0) & (xs < 2200) & (ys > 15) & (ys < 300))
        for j in np.nonzero(ok)[0]:
            out[a + int(idx[j]) * 4] = (float(xs[j]), float(ys[j]))
    return out


def find_players_by_input(i, hold=0.6, min_move=15.0):
    """{'P1': addr, 'P2': addr, 'trace': …} by pressing each player's key. None if not drivable."""
    pid = pid_of(i)
    base = _all_record_xs(pid)
    if not base:
        return None

    def moved(key, exclude=()):
        """Records that move WHILE the key is held and STOP when it is released.

        The stop half is not optional: the attract demo's AI walks fighters by itself, so
        "a record moved while I held d" is also true on the title screen. This is the check
        that separates control from coincidence.
        """
        before = {a: v[0] for a, v in base.items() if a not in exclude}
        n.key(i, key, hold=hold)
        during = _all_record_xs(pid)
        time.sleep(0.35)
        after = _all_record_xs(pid)
        deltas = []
        for a, x0 in before.items():
            if a not in during or a not in after:
                continue
            d_hold = during[a][0] - x0
            d_free = after[a][0] - during[a][0]
            if abs(d_hold) >= min_move and abs(d_free) <= 2.5:
                deltas.append((abs(d_hold), a, d_hold, x0, during[a][0]))
        deltas.sort(reverse=True)
        return deltas

    d_moves = moved("d")
    if not d_moves:
        return None
    p1 = d_moves[0][1]
    r_moves = moved("Right", exclude={a for _m, a, *_ in d_moves[:4]})
    if not r_moves:
        return {"P1": p1, "P2": None,
                "trace": {"d": {"addr": p1, "delta": round(d_moves[0][2], 1)}}}
    p2 = r_moves[0][1]
    return {"P1": p1, "P2": p2,
            "trace": {"d": {"addr": p1, "from": round(d_moves[0][3], 1),
                            "to": round(d_moves[0][4], 1)},
                      "Right": {"addr": p2, "from": round(r_moves[0][3], 1),
                                "to": round(r_moves[0][4], 1)}}}


# ---------------------------------------------------------------- measured pad trigger (worker p)
#
# Swept on 4 parallel instances, verified on 2 fresh ones:
#   firing band      d = 0.28 .. 0.42 W      (0.28, 0.30, 0.333, 0.36, 0.38, 0.42 all fired)
#   best             d = 0.333 W             (repeat 2.74 s / 2.69 s)
#   dead inner zone  d = 0.267 W             (32 s, never fired — the inner third of each pad)
#   outside          d >= 0.44 W
#   stage select appears ~1.5-2.7 s after the last movement key
# The painted pads are at wall ∓ 0.33 W (yellow bar 24..85 px, orange 243..295 px on 320 W).
# The "widest colour run" pad detector is contaminated by the fighter standing on the pad — it
# reported a 100 px bar — which is what made 0.32 W look unreliable for a whole afternoon.

PAD_OFFSET_FRAC = 0.333
PAD_OFFSET_BAND = (0.28, 0.42)


def in_match(i, name="im"):
    """A live match: no menu, no READY wall, and pressing keys moves exactly one record each.

    Drivability alone is NOT enough — READY is drivable and so are the pause/OPTIONS screens.
    The wall is the discriminator: it exists only on READY.
    """
    if menu_geometry(i, name + "m") is not None:
        return False
    if _wall_x(i, name + "w") is not None:
        return False
    return bool(find_players_by_input(i, hold=0.4))


def enter_match_v2(i, verbose=True, stand=1.6, tries=2):
    """The measured recipe. Returns True only for a verified live match.

    READY -> park both at wall ∓ 0.333 W -> hold ~1.5 s -> stage select -> Return -> match.
    """
    for attempt in range(tries):
        if not enter_ready(i):
            if verbose:
                print("  not on READY")
            return False
        if in_match(i):                      # already live
            return True
        wx = _wall_x(i, "v2w")
        if wx is None:
            if verbose:
                print("  wall missing")
            return False
        off = PAD_OFFSET_FRAC * frame(i, "v2g").shape[1]
        ok1 = _walk_to_x(i, "yellow", wx - off)
        ok2 = _walk_to_x(i, "orange", wx + off)
        if verbose:
            print(f"  parked at wall ∓{PAD_OFFSET_FRAC:.3f}W (yellow={ok1} orange={ok2}); holding")
        t0 = time.time()
        fired = False
        while time.time() - t0 < stand + 1.8:
            if on_stage_select(i, f"v2s{attempt}"):
                fired = True
                if verbose:
                    print(f"  stage select after {time.time()-t0:.1f}s")
                break
            time.sleep(0.3)
        if not fired:
            if verbose:
                print(f"  attempt {attempt}: no stage select")
            continue
        n.key(i, "Return", hold=0.12)
        time.sleep(3.0)                       # spawn + fall
        if in_match(i):
            return True
        if verbose:
            print("  stage select accepted but not a live match yet")
    return False
