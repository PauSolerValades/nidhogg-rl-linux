#!/usr/bin/env python3
"""Is the observation interface fast enough to see every game tick?

Finds the game's 60 Hz counter (rate test, per process), then pulls it as fast as the
spy allows and reports the tick delta between consecutive samples.

    python3 scripts/tick_health.py 0            # instance id (finds the counter itself)
    python3 scripts/tick_health.py --pid 1234 --tick 0x5555897e7500

Pass = achieved rate > 60 pulls/s and no sample skipped a tick (delta <= 1).
Skipped ticks (delta 3) mean the loop is a 20 Hz sample of a 60 Hz game, which is what
the 50 ms spy poll used to cost.
"""
import argparse
import collections
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402


def heap_of(pid):
    for line in open(f"/proc/{pid}/maps"):
        if "[heap]" in line:
            a, b = (int(x, 16) for x in line.split()[0].split("-"))
            return a, b - a
    return None, 0


def find_tick(pid, windows=4, gap=0.9):
    """A u32 that advances by ~60/s in every window. Any single window is a coincidence."""
    base, size = heap_of(pid)
    if not base:
        return None
    seen = None
    prev = None
    stamps = []
    for k in range(windows):
        raw = n.memory(pid, base, size, f"/tmp/tickhealth_{k}.bin")
        t = time.time()
        if raw is None:
            return None
        cur = np.frombuffer(raw, "<u4")
        if prev is not None:
            dt = t - stamps[-1]
            want = 60.0 * dt
            d = cur.astype(np.int64) - prev.astype(np.int64)
            ok = np.nonzero((np.abs(d - want) < max(8, 0.2 * want)) & (prev < 0xFFFF0000))[0]
            seen = set(ok.tolist()) if seen is None else (seen & set(ok.tolist()))
        prev, _ = cur, stamps.append(t)
    if not seen:
        return None
    return base + min(seen) * 4


def measure(pid, tick, seconds=2.0):
    prev = None
    deltas = []
    t0 = time.time()
    pulls = 0
    while time.time() - t0 < seconds:
        raw = n.memory_many(pid, [(tick, 4, "/tmp/tickhealth.bin")])[0]
        if raw is None:
            return None
        v = int.from_bytes(raw, "little")
        pulls += 1
        if prev is not None:
            deltas.append(v - prev)
        prev = v
    return pulls / seconds, deltas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--pid", type=int)
    ap.add_argument("--tick", type=lambda s: int(s, 0))
    ap.add_argument("--seconds", type=float, default=2.0)
    a = ap.parse_args()

    pid = a.pid or n._game_pid(a.instance)
    assert pid, "no game process for that instance"
    assert n.ping(pid), f"spy not answering in pid {pid}"
    tick = a.tick or find_tick(pid)
    assert tick, "no 60 Hz counter found"
    print(f"pid {pid}  tick {tick:#x}")

    rate, deltas = measure(pid, tick, a.seconds)
    if rate is None:
        sys.exit("spy stopped answering mid-measurement")
    hist = collections.Counter(deltas)
    print(f"{rate:.0f} pulls/s over {a.seconds:.0f}s   tick deltas {dict(sorted(hist.items()))}")
    missed = sum(d - 1 for d in deltas if d > 1)
    seen = sum(1 for d in deltas if d > 0) + 1          # distinct advances, not samples
    print(f"ticks observed {seen} of {sum(deltas) + 1}  (missed {missed})")

    ok = rate > 60 and max(deltas, default=0) <= 1
    print("PASS — every tick observed" if ok else "FAIL — the loop is slower than the game")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
