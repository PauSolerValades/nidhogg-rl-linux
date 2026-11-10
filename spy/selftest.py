#!/usr/bin/env python3
"""Self-check for spy/nidspy.zig — no game needed.

dlopen()s the spy into THIS python process, so the process is the "game": the
constructor sees our pid, starts its poll thread, and the real protocol runs
against our own memory.

  python3 spy/selftest.py [path/to/spy.so]

Checks: ctor ran, ping, dump, poke, hold, add, contiguous record read, and the
one that matters — the round trip is no longer capped at 50 ms.
"""
import ctypes
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import nidlinux as n  # noqa: E402

SO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "nidspy.so")


def rt(pid, addr, size=4):
    t0 = time.perf_counter()
    raw = n.memory_many(pid, [(addr, size, "/tmp/selftest_dump.bin")])[0]
    return (time.perf_counter() - t0) * 1000.0, raw


def main():
    lib = ctypes.CDLL(SO)
    pid = os.getpid()
    lib.nid_spy_pid.restype = ctypes.c_int
    assert lib.nid_spy_pid() == pid, "constructor did not run (nid_spy_pid != getpid)"

    assert "pong" in n.ping(pid), "ping"

    # dump: a known buffer must come back byte-identical
    known = bytes(range(64))
    buf = ctypes.create_string_buffer(known, len(known))
    addr = ctypes.addressof(buf)
    _, raw = rt(pid, addr, len(known))
    assert raw == known, f"dump mismatch {raw!r}"

    # poke: write, then read back
    n.poke(pid, addr + 8, b"ZIGSPY")
    assert buf.raw[8:14] == b"ZIGSPY", f"poke mismatch {buf.raw[8:14]!r}"

    # hold: pinned across a window that the "game" would otherwise overwrite
    target = ctypes.c_uint32(0)
    taddr = ctypes.addressof(target)
    n.hold(pid, taddr, struct.pack("<I", 0xDEADBEEF), 150)
    assert target.value == 0xDEADBEEF, f"hold {target.value:#x}"

    # add: accumulates float32 instead of pinning
    vel = ctypes.c_float(0.0)
    vaddr = ctypes.addressof(vel)
    n.accumulate(pid, vaddr, 1.0, width=4, ms=150)
    assert 20.0 < vel.value < 400.0, f"add accumulated {vel.value}"

    # one contiguous read of a record (type..y = 0x88..0x100) is one request, not four
    rec = ctypes.create_string_buffer(0x80)
    _, raw = rt(pid, ctypes.addressof(rec), 0x80)
    assert len(raw) == 0x80, "contiguous record read"

    # a BIG dump must not come back truncated (waiting on the cmd file alone reads mid-write)
    big = ctypes.create_string_buffer(8 << 20)
    _, raw = rt(pid, ctypes.addressof(big), 8 << 20)
    assert len(raw) == 8 << 20, f"big dump truncated: {len(raw)} bytes"

    # pushed state file: a fake 0x200 record in our own memory, offsets from docs/LAYOUT.md
    rec = ctypes.create_string_buffer(0x200)
    rec_addr = ctypes.addressof(rec)
    struct.pack_into("<f", rec, 0xEC, 120.5)     # x
    struct.pack_into("<f", rec, 0xF0, 192.0)     # y
    struct.pack_into("<f", rec, 0xD8, -1.0)      # facing
    struct.pack_into("<I", rec, 0xBC, 461)       # anim
    rec2 = ctypes.create_string_buffer(0x200)
    struct.pack_into("<f", rec2, 0xEC, 200.0)
    struct.pack_into("<f", rec2, 0xF0, 128.0)
    struct.pack_into("<f", rec2, 0xD8, 1.0)

    # no tick counter -> free-running publish (~125 Hz), fields must match the record
    n.track(pid, p1=rec_addr, p2=ctypes.addressof(rec2))
    st = n.wait_state(pid, 0, timeout=1.0)
    assert st, "state file not published"
    assert st.flags & n.FLAG_P1 and st.flags & n.FLAG_P2, f"flags {st.flags:#x}"
    assert abs(st.p1_x - 120.5) < 1e-6 and abs(st.p1_y - 192.0) < 1e-6, "p1 x/y"
    assert st.p1_anim == 461 and st.p1_facing == -1.0, "p1 anim/facing"
    assert st.p2_x == 200.0 and st.p2_facing == 1.0, "p2"
    seqs = [st.seq]
    for _ in range(5):
        st = n.wait_state(pid, seqs[-1])
        assert st, "publisher stopped"
        seqs.append(st.seq)
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs))), f"seq gap {seqs}"

    # with a tick counter tracked, exactly ONE sample per tick change and none in between
    tickbuf = ctypes.c_uint32(5000)
    n.track(pid, p1=rec_addr, p2=ctypes.addressof(rec2), tick=ctypes.addressof(tickbuf))
    st = n.wait_state(pid, n.state(pid).seq, timeout=1.0)     # a sample NEWER than disk
    assert st and st.tick == 5000, f"tick not published: {st and st.tick}"
    before = st.seq
    time.sleep(0.05)                       # tick did not move: nothing new may appear
    assert n.state(pid).seq == before, "published without a tick change"
    for k in range(1, 4):
        tickbuf.value = 5000 + k
        st = n.wait_state(pid, before, timeout=1.0)
        assert st and st.tick == 5000 + k, f"tick {k} not published"
        assert st.seq == before + 1, f"seq jumped {before}->{st.seq} on one tick"
        before = st.seq

    # an unmapped address is refused instead of dereferenced (this would crash the game)
    n.track(pid, p1=0x8, p2=ctypes.addressof(rec2))
    time.sleep(0.05)
    st = n.state(pid)
    assert st and (st.flags & n.FLAG_P2), "publisher died on the bad pointer"
    assert not (st.flags & n.FLAG_P1), "unmapped pointer was accepted"
    n.untrack(pid)

    # THE point of the port: the poll is 2 ms, not 50 ms
    lat = sorted(rt(pid, addr)[0] for _ in range(100))
    p50, p99 = lat[50], lat[98]
    print(f"round trip: p50={p50:.2f} ms p99={p99:.2f} ms  ({1000/p50:.0f} pulls/s)")
    assert p50 < 5.0, f"poll still slow: p50={p50:.1f} ms (C version was 51 ms)"
    print("selftest OK")


if __name__ == "__main__":
    main()
