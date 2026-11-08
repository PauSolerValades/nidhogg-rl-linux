#!/usr/bin/env python3
"""Walk each fighter onto its pad using the WALL as the landmark, not the pad colour.

Geometry (from the human player, who can see the screen):
  * the wall is the vertical block in the middle of the screen;
  * each pad sits at the middle of its own half, i.e. a quarter-screen from the wall;
  * yellow walks left from the wall, orange walks right.
This is robust to camera panning because the wall and the fighters move together.

  python3 scripts/wall_walk.py <instance>
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

GROUND_FRAC = 0.62          # below this row it is floor/pads, not fighters


def frame(i, name):
    return s.frame(i, f"/tmp/{name}.png")


def fighter_x(i, which):
    """Screen x of the fighter blob (above the ground line)."""
    a = frame(i, f"fx_{which}")
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 200) & (g > 200) & (b < 90) if which == "yellow" else \
        (r > 200) & (g > 105) & (g < 205) & (b < 115)
    h = m.shape[0]
    m[int(h * GROUND_FRAC):, :] = False          # ignore pads and floor
    ys, xs = np.nonzero(m)
    return float(xs.mean()) if len(xs) > 20 else None


def wall_x(i):
    """Screen x of the central wall: a tall light-grey vertical band."""
    a = frame(i, "wall")
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    light = (r > 150) & (r < 235) & (np.abs(r - g) < 18) & (np.abs(g - b) < 18)
    h, w = light.shape
    band = light[int(h * 0.05):int(h * 0.55), :].mean(0)   # fraction of the upper half
    cols = np.nonzero(band > 0.6)[0]
    if len(cols) < 8:
        return None
    groups = np.split(cols, np.nonzero(np.diff(cols) > 4)[0] + 1)
    g0 = max(groups, key=len)
    return float(g0.mean()), len(g0)


def walk_to(i, which, target, left, right, tol=8, max_steps=40):
    for step in range(max_steps):
        fx = fighter_x(i, which)
        if fx is None:
            print(f"  {which}: fighter not visible")
            return False
        off = target - fx
        if abs(off) <= tol:
            print(f"  {which}: reached {fx:.0f} (target {target:.0f}) in {step} steps")
            return True
        n.key(i, right if off > 0 else left, hold=min(0.30, max(0.05, abs(off) / 600.0)))
        time.sleep(0.10)
    print(f"  {which}: gave up at {fighter_x(i, which)} (target {target:.0f})")
    return False


if __name__ == "__main__":
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not s.on_ready_screen(i):
        print("not on READY; pressing Return to get back")
        s.enter_ready(i)
    a = frame(i, "geometry")
    w = a.shape[1]
    wx = wall_x(i)
    print(f"frame width {w}; wall at x={wx}")
    if wx is None:
        sys.exit("wall not found — cannot place pads")
    # measured on-screen: the pads sit ~0.32*W from the wall (a quarter-screen, W/4, leaves the
    # fighters standing a couple of dozen pixels short of the pad)
    OFF = 0.32 * w
    target_y = wx[0] - OFF
    target_o = wx[0] + OFF
    ok1 = walk_to(i, "yellow", target_y, "a", "d")
    ok2 = walk_to(i, "orange", target_o, "Left", "Right")
    print(f"on pads: yellow={ok1} orange={ok2}; standing 2.5 s")
    time.sleep(2.5)
    s.grab(i, "/tmp/wall_walk_done.png")
    print("pads still visible (True = still on READY):", s.on_ready_screen(i))
