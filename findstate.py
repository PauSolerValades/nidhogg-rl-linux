#!/usr/bin/env python3
"""Find the fighter position, and confirm match entry, by memory alone.

There is no screen parsing here. A live match is defined as: holding 'd' makes a
float32 slot in the game heap move right at fighter speed (~12 px/s), and holding 'a'
makes the same slot move left. Animations cannot fake that, so it doubles as the
entry verifier -- which retires the menu-detection heuristic entirely.

Positions in this build are float32; a float64 sweep of the heap finds only counters.

  python3 findstate.py [instance]
"""
import importlib.util
import struct
import sys
import time
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("n", Path(__file__).with_name("nidlinux.py"))
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)

WARMUP = 13.0          # keys before ~frame 690 are eaten
SAMPLES = 10
GAP = 0.2
MAX_REGION = 200 << 20


def heap(pid):
    """Largest anonymous rw region: the game heap."""
    best = (0, 0)
    for line in open(f"/proc/{pid}/maps"):
        p = line.split()
        if p[1][:2] != "rw" or (len(p) > 5 and p[-1].startswith("/")):
            continue
        a, b = (int(x, 16) for x in p[0].split("-"))
        if 4096 <= b - a <= MAX_REGION and b - a > best[1] - best[0]:
            best = (a, b)
    return best


def dump(pid, addr, size):
    raw = n.memory(pid, addr, size, "/tmp/nid_scan.bin")
    return np.frombuffer(raw, "<f4") if raw else None


def sample(pid, addr, size):
    rows = []
    for _ in range(SAMPLES):
        a = dump(pid, addr, size)
        if a is None:
            return None
        rows.append(a)
        time.sleep(GAP)
    m = min(len(r) for r in rows)
    return np.stack([r[:m] for r in rows])


def drift(A, lo, hi, max_step):
    """Slots that moved monotonically by (lo, hi) over the whole window."""
    with np.errstate(invalid="ignore", over="ignore"):
        ok = np.isfinite(A).all(0) & (np.abs(A) < 1200).all(0)
        d = np.diff(A, axis=0)
        total = A[-1] - A[0]
        good = (ok
                & (np.abs(d) < max_step).all(0)          # never teleports
                & (total > lo) & (total < hi)            # fighter speed, not a timer
                & ((np.sign(d) == np.sign(total)).mean(0) > 0.8))
    return np.nonzero(good)[0]


def park(i, keysym, seconds=1.6):
    """Walk into the wall first, so the sampling move has room to happen.

    Without this the scan can start with the fighter already against the far wall:
    the key is held, the game clamps x, and nothing moves -- which looks exactly
    like "no controllable fighter".
    """
    n.keydown(i, keysym)
    time.sleep(seconds)
    n.keyup(i, keysym)
    time.sleep(0.3)


def scan_motion(i, pid, addr, size):
    """Confirmed fighter slots: right while 'd', left while 'a'."""
    park(i, "a")
    n.keydown(i, "d")
    right = drift(sample(pid, addr, size), 5, 700, 60)
    n.keyup(i, "d")
    if not len(right):
        return []
    time.sleep(0.4)
    n.keydown(i, "a")
    left = set(drift(sample(pid, addr, size), -700, -5, 60).tolist())
    n.keyup(i, "a")
    return [(addr + k * 4, k) for k in right if k in left]


def try_entry(i, seq):
    for keysym, repeat in seq:
        for _ in range(repeat):
            n.key(i, keysym)
            time.sleep(1.4)


# Enter-only lands in LOCAL 2-player: the round never starts there, but both
# fighters are ours and drivable, which is enough to identify x against input.
VARIANTS = [
    ("enter-only (LOCAL 2P)", [("Return", 6)]),
    ("single player", [("Return", 2), ("Up", 1), ("Return", 4)]),
    ("single player, 2 down", [("Return", 2), ("Down", 2), ("Return", 4)]),
]


def main():
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pid = n._game_pid(i)
    if not pid:
        sys.exit("game not running")
    addr, end = heap(pid)
    print(f"pid {pid} heap {addr:#x}-{end:#x} ({(end-addr)/1e6:.0f} MB)")

    time.sleep(0 if "--now" in sys.argv else WARMUP)
    if "--now" in sys.argv:
        found = scan_motion(i, pid, addr, end - addr)
        print(f"{len(found)} confirmed slots")
        for a, _ in found:
            print(f"  {a:#x}")
        return
    for label, seq in VARIANTS:
        print(f"trying {label}…")
        try_entry(i, seq)
        found = scan_motion(i, pid, addr, end - addr)
        n.grab(i, f"/tmp/nid_try_{label.split()[0]}.png")
        if found:
            print(f"MATCH CONFIRMED by motion — {len(found)} slots")
            for a, _ in found:
                print(f"  {a:#x}")
            Path("/tmp/nid_x_candidates.txt").write_text(
                "\n".join(f"{a:#x}" for a, _ in found))
            return
        print("  no motion — not a live match")
    print("no variant produced a controllable fighter")


if __name__ == "__main__":
    main()
