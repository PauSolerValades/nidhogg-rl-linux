#!/usr/bin/env python3
"""Identify P1's x by poking while the game is PAUSED.

Why pausing is the whole trick: the pause menu freezes the simulation but keeps
drawing. So with the game paused

  * nothing drifts on its own (the READY screen otherwise moves the fighter by itself,
    which is what made the earlier "confirmation" worthless), and
  * a value only *affects* the picture if the renderer reads it as a position --
    a velocity or accumulator write does nothing at all without simulation ticks.

Oracle: paused P1 is (123,92,0) after the menu dim, while P2 is (122,77,31) -- so a
narrow band around P1's colour isolates him.

  python3 hunt_paused.py [instance]
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
spec2 = importlib.util.spec_from_file_location("p", Path(__file__).with_name("pokehunt.py"))
p = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(p)

WARMUP = 13.0
PROBES = (60.0, 300.0, 60.0)   # A B A: reproducible AND injective, or it is drift
TOL = 12


def effect(base, after, box=(120, 110, 205, 180)):
    """Changed pixels outside the pause box, and their centroid x.

    The paused screen is perfectly static (measured 0 px of drift), so every changed
    pixel is caused by our write -- no sprite colour detection needed.
    """
    if base is None or after is None:
        return None, None
    diff = np.abs(after.astype(int) - base.astype(int)).max(2) > 24
    x0, y0, x1, y1 = box
    diff[y0:y1, x0:x1] = False
    ys, xs = np.nonzero(diff)
    if not len(xs):
        return 0, None
    # sprite-sized change only: with the game paused the camera cannot follow, so a
    # position write must repaint a small region, not the whole scene
    return len(xs), (int(xs.max() - xs.min()), int(ys.max() - ys.min()))


def read_f(pid, addr, width=4):
    raw = n.memory(pid, addr, width, "/tmp/hp_rd.bin")
    return struct.unpack("<f" if width == 4 else "<d", raw)[0] if raw else None


def frozen(i):
    """Two footage of a paused game must be identical."""
    a = n.frame(i, "/tmp/hp_f1.png")
    time.sleep(0.45)
    b = n.frame(i, "/tmp/hp_f2.png")
    return n.stable_change((a, b), b)


def pin(pid, addr, value, width=4, ms=400):
    fmt = "<f" if width == 4 else "<d"
    Path(f"/tmp/nid_cmd_{pid}").write_text(
        f"hold {addr:x} {struct.pack(fmt, value).hex()} {ms}\n")
    time.sleep(0.2)
    return n.frame(0, "/tmp/hp_probe.png")


def main():
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pid = n._game_pid(i)
    if not pid:
        sys.exit("game not running")

    # get into the controllable local match (Enter-only path)
    time.sleep(WARMUP)
    for _ in range(6):
        n.key(i, "Return")
        time.sleep(1.5)
    time.sleep(0.5)

    regs = p.regions(pid)
    print(f"pid {pid}: {len(regs)} regions")
    cands = p.candidates(i, pid, regs)
    print(f"{len(cands)} motion candidates")

    n.key(i, "Escape")
    time.sleep(1.2)
    noise = frozen(i)
    print(f"paused; two frames differ by {noise} px")
    if noise > 50:
        print("NOT frozen — pause did not take")
        return
    base = n.frame(i, "/tmp/hp_base.png")
    print("baseline frame captured")

    for k, (addr, width, drift) in enumerate(cands):
        if n._game_pid(i) != pid:
            print("game died")
            return
        v0 = read_f(pid, addr, width)
        if v0 is None:
            continue
        counts, bboxes = [], []
        for v in (60.0, 300.0, 60.0):
            c, bb = effect(base, pin(pid, addr, v, width))
            counts.append(c or 0)
            bboxes.append(bb)
            time.sleep(0.15)
        pin(pid, addr, v0, width, ms=200)          # restore: paused, so it persists
        c1, c2, c3 = counts
        sprite_sized = all(bb and bb[0] < 70 and bb[1] < 70 for bb in bboxes if bb)
        verdict = ""
        if min(c1, c2) > 80 and abs(c1 - c2) > 40 and abs(c1 - c3) < 0.3 * max(c1, 1):
            verdict = "  <== VALUE DEPENDENT" + (" (sprite-sized)" if sprite_sized else " (FULL SCREEN)")
        print(f"  [{k+1}/{len(cands)}] {addr:#x} f{width*8} drift={drift:7.1f} "
              f"changed={counts} bbox={bboxes}{verdict}")
        if verdict:
            Path("/tmp/nid_x_confirmed.txt").write_text(f"{addr:#x} f{width*8}\n")
            print(f"\nCONFIRMED while paused: {addr:#x} drives the drawn picture")
            return
    print("nothing confirmed — pause protocol did not find x")


if __name__ == "__main__":
    main()
