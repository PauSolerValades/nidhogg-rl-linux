#!/usr/bin/env python3
"""Hunt P1's position in a LIVE match, where the stimulus is finally real.

History that shapes this script:
  * xdotool's instant press/release may fall between two 60 Hz steps, so every key is
    HELD 120 ms here -- that alone made menu navigation 100% reliable.
  * motion in READY is camera scroll, not the fighter: worker A proved it. So entry is
    verified by a *live CPU* (orange moves) AND by the fighter responding to 'd'.
  * physics rewrites constants every tick, so verification uses `accumulate` (add), not
    `hold` (pin).

  python3 hunt_live.py [instance]
"""
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("s", Path(__file__).with_name("nidstate.py"))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
n = s.n

SAMPLES = 6
GAP = 0.25
MAX_REGION = 200 << 20


def held(i, keysym, wait=1.2):
    n.key(i, keysym, hold=0.12)
    time.sleep(wait)


def enter_live_match(i):
    """attract/title -> MENU -> SINGLE PLAYER -> mode ladder -> BEGIN.

    Adaptive at the front: the game may be sitting in attract mode or on the title, so
    press Return until the selection dot exists rather than assuming a fixed count.
    """
    for _ in range(5):
        if s.selected_y(i) is not None:
            break
        held(i, "Return", 2.0)
    else:
        print("  never reached a menu")
        return False
    print(f"  menu at dot y={s.selected_y(i)}")
    held(i, "Up", 1.0)                     # MULTIPLAYER -> SINGLE PLAYER
    print(f"  after Up: {s.selected_y(i)}")
    held(i, "Return", 1.6)                 # -> SINGLE PLAYER screen
    print(f"  single player screen: {s.selected_y(i)}")
    held(i, "Return", 1.6)                 # -> ladder / setup
    for _ in range(2):                      # BEGIN sits at the bottom
        for _ in range(4):
            held(i, "Down", 0.7)
        held(i, "Return", 2.0)
        if s.sprite_present(i):
            return True
        print("  no fighter after BEGIN — retrying")
        held(i, "Up", 0.7)
    return s.sprite_present(i)


def yellow(i):
    a = s.frame(i, "yl")
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 240) & (g > 240) & (b < 80)
    ys, xs = np.nonzero(m)
    return (float(xs.mean()), float(ys.mean())) if len(xs) > 20 else (None, None)


def regions(pid):
    out = []
    for line in open(f"/proc/{pid}/maps"):
        p = line.split()
        if p[1][:2] != "rw" or (len(p) > 5 and p[-1].startswith("/")):
            continue
        a, b = (int(x, 16) for x in p[0].split("-"))
        if 1 << 20 <= b - a <= MAX_REGION:
            out.append((a, b))
    return out


def sample(pid, regs, hold_key=None):
    if hold_key:
        n.keydown(pid_i, hold_key)
    snaps = []
    for _ in range(SAMPLES):
        row = {}
        for a, b in regs:
            row[(a, b)] = n.memory(pid, a, b - a, "/tmp/hl.bin")
        snaps.append(row)
        time.sleep(GAP)
    if hold_key:
        n.keyup(pid_i, hold_key)
    return snaps


def rising(snaps, lo, hi):
    """Slots that increased smoothly AND are not round bookkeeping constants."""
    hits = []
    for k in snaps[0]:
        if any(x[k] is None for x in snaps):
            continue
        m = min(len(x[k]) for x in snaps)
        for dt, w in (("<f4", 4), ("<f8", 8)):
            A = np.stack([np.frombuffer(x[k][: m // w * w], dt) for x in snaps])
            with np.errstate(invalid="ignore", over="ignore"):
                d = np.diff(A, axis=0)
                tot = A[-1] - A[0]
                good = (np.isfinite(A).all(0)
                        & (A >= 0).all(0) & (A < 1200).all(0)
                        & ((d > 0.005).mean(0) > 0.8)          # rising
                        & (tot > 20) & (tot < 700))
                idx = np.nonzero(good)[0]
            for i in idx:
                vals = A[:, i]
                # positions are fractional; 320.0 / 200.0 style churn is not
                if (vals != np.round(vals)).sum() >= 2:
                    hits.append((k[0] + int(i) * w, w, float(tot[i])))
    hits.sort(key=lambda t: -t[2])
    return hits


if __name__ == "__main__":
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    globals()["pid_i"] = i
    pid = s.pid_of(i)
    if not pid:
        sys.exit("game not running")

    time.sleep(15)
    if not enter_live_match(i):
        print("no fighter on screen — entry failed")
        sys.exit(1)
    s.grab(i, "/tmp/hl_match.png")
    y0 = yellow(i)
    cpu = s.cpu_motion(i, 3.0)
    print(f"in match: yellow at {y0}, CPU motion {cpu:.1f} px")

    n.keydown(i, "d")
    time.sleep(1.5)
    n.keyup(i, "d")
    y1 = yellow(i)
    moved = abs(y1[0] - y0[0]) if (y0[0] and y1[0]) else None
    print(f"after 1.5 s of 'd': yellow at {y1}  -> moved {moved} px")
    if not moved or moved < 3:
        print("WARNING: input does not appear to move the fighter in this state")

    regs = regions(pid)
    print(f"sampling {len(regs)} regions x{SAMPLES} while holding 'd'…")
    snaps = sample(pid, regs, hold_key="d")
    hits = rising(snaps, 20, 700)
    print(f"{len(hits)} rising coordinate-like slots")
    for addr, w, tot in hits[:12]:
        print(f"  {addr:#x} f{w*8} rose {tot:7.1f}")
    Path("/tmp/hl_candidates.txt").write_text("\n".join(f"{a:#x} f{w*8}" for a, w, _ in hits))
