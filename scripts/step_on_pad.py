#!/usr/bin/env python3
"""Walk each fighter onto its coloured pad and hold still, which triggers stage select.

Mechanic (from the human player): standing on your own pad for ~2 s lights the pad's bottom
edge; when BOTH players stand on their pads the stage-selection screen appears.

  python3 scripts/step_on_pad.py 1         # instance id

P1 = yellow, keys a/d.  P2 = orange, keys Left/Right (measured: arrows).
"""
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "s", Path(__file__).resolve().parent.parent / "nidstate.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
n = s.n


def runs(mask_row):
    """Longest contiguous True run in a boolean row -> (start, end) or None."""
    idx = np.nonzero(mask_row)[0]
    if not len(idx):
        return None
    best, cur = None, [idx[0], idx[0]]
    for a, b in zip(idx, idx[1:]):
        if b - a <= 2:
            cur[1] = b
        else:
            if best is None or cur[1] - cur[0] > best[1] - best[0]:
                best = list(cur)
            cur = [b, b]
    if best is None or cur[1] - cur[0] > best[1] - best[0]:
        best = cur
    return best


def locate(i, which):
    """(pad_x0, pad_x1, pad_y, fighter_x) for 'yellow' or 'orange'."""
    a = s.frame(i, f"loc_{which}.png")
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    if which == "yellow":
        m = (r > 200) & (g > 200) & (b < 90)
    else:
        m = (r > 200) & (g > 105) & (g < 205) & (b < 115)
    h, w = m.shape
    pad_row, pad_run = None, None
    for y in range(int(h * 0.55), h):                 # pads live in the lower part
        rn = runs(m[y])
        if rn and rn[1] - rn[0] > 25:                 # a pad is a wide horizontal bar
            if pad_run is None or rn[1] - rn[0] > pad_run[1] - pad_run[0]:
                pad_row, pad_run = y, rn
    if pad_run is None:
        return None
    body = m.copy()
    body[max(0, (pad_row or h) - 4):, :] = False      # drop the pad itself
    ys, xs = np.nonzero(body)
    fx = float(xs.mean()) if len(xs) > 20 else None
    return pad_run[0], pad_run[1], int(pad_row), fx


def walk_onto(i, which, left_key, right_key, tol=7, max_steps=25):
    for step in range(max_steps):
        loc = locate(i, which)
        if not loc:
            print(f"  {which}: pad not found")
            return False
        px0, px1, py, fx = loc
        centre = (px0 + px1) / 2
        if fx is None:
            print(f"  {which}: fighter not found (pad {px0}-{px1})")
            return False
        off = centre - fx
        if abs(off) <= tol:
            print(f"  {which}: on pad (fighter {fx:.0f}, pad centre {centre:.0f}) after {step} steps")
            return True
        key = right_key if off > 0 else left_key
        n.key(i, key, hold=min(0.35, max(0.06, abs(off) / 400.0)))
        time.sleep(0.12)
    print(f"  {which}: gave up (fighter {fx:.0f}, centre {centre:.0f})")
    return False


if __name__ == "__main__":
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    ok1 = walk_onto(i, "yellow", "a", "d")
    ok2 = walk_onto(i, "orange", "Left", "Right")
    print(f"on pads: yellow={ok1} orange={ok2}; holding still 2.5 s (pad bottoms light up)")
    time.sleep(2.5)
    s.grab(i, "/tmp/pads_done.png")
    print("menu after standing:", s.menu_geometry(i, "pads_menu"))
