#!/usr/bin/env python3
"""Poke-and-watch: prove which memory slot is the fighter's x.

A drift filter alone cannot tell a position from anything derived from it (camera,
draw record, bbox, xprevious all drift too). The only proof is writing a value,
pinning it across frames, and watching the sprite move.

Oracle: P1 is the only pure-yellow (255,255,0) thing on screen — P2 is orange
(255,160,64) and the goal line is dim yellow (166,166,0). So the fighter's screen x
comes straight out of a screenshot, no ML, no OCR.

  python3 pokehunt.py [instance]
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

SAMPLES = 8
GAP = 0.2
HOLD_MS = 500
PARK = 1.6          # walk into the wall first: a clamped x looks like "no motion"
VALUE = 60.0        # far enough to be unmistakable
MAX_CANDIDATES = 250


def yellow_x(a):
    """Screen x of P1, or None. Pure yellow only, so P2 and the goal line are out."""
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    m = (r > 240) & (g > 240) & (b < 80)
    ys, xs = np.nonzero(m)
    return (int(xs.mean()) if len(xs) >= 20 else None), int(len(xs))


def regions(pid, min_size=1 << 20):
    out = []
    for line in open(f"/proc/{pid}/maps"):
        p = line.split()
        if p[1][:2] != "rw" or (len(p) > 5 and p[-1].startswith("/")):
            continue
        a, b = (int(x, 16) for x in p[0].split("-"))
        if min_size <= b - a <= 200 << 20:
            out.append((a, b))
    return out


def baseline_noise(i):
    """Pixels that change in 0.5 s with no input at all (birds, grass, torch flicker)."""
    a = n.frame(i, "/tmp/nid_n1.png")
    time.sleep(0.5)
    b = n.frame(i, "/tmp/nid_n2.png")
    return n.stable_change((a, b), b)


def candidates(i, pid, regs):
    """Slots that march with the fighter while 'd' is held."""
    n.keydown(i, "a")
    time.sleep(PARK)
    n.keyup(i, "a")
    time.sleep(0.3)
    n.keydown(i, "d")
    snaps = []
    for _ in range(SAMPLES):
        row = {}
        for a, b in regs:
            row[(a, b)] = n.memory(pid, a, b - a, "/tmp/nid_stim.bin")
        snaps.append(row)
        time.sleep(GAP)
    n.keyup(i, "d")
    found = []
    for a, b in regs:
        if any(s[(a, b)] is None for s in snaps):
            continue
        m = min(len(s[(a, b)]) for s in snaps)
        for dt, w in (("<f4", 4), ("<f8", 8)):
            A = np.stack([np.frombuffer(s[(a, b)][: m // w * w], dt) for s in snaps])
            with np.errstate(invalid="ignore", over="ignore"):
                ok = np.isfinite(A).all(0) & (np.abs(A) < 4000).all(0)
                d = np.diff(A, axis=0)
                tot = A[-1] - A[0]
                good = (ok & (np.abs(d) < 150).all(0)
                        & (tot > 20) & (tot < 1200)
                        & ((np.sign(d) == np.sign(tot)).mean(0) > 0.75))
                idx = np.nonzero(good)[0]
            for k in idx:
                found.append((a + k * w, w, float(tot[k])))
    found.sort(key=lambda t: -abs(t[2]))
    return found[:MAX_CANDIDATES]


def probe(i, pid, addr, width, noise):
    """Pin a value across frames and report whether the sprite or the view reacted."""
    fmt = "<f" if width == 4 else "<d"
    before = n.frame(i, "/tmp/nid_p1.png")
    y0, _ = yellow_x(before)
    cmd = Path(f"/tmp/nid_cmd_{pid}")
    cmd.write_text(f"hold {addr:x} {struct.pack(fmt, VALUE).hex()} {HOLD_MS}\n")
    time.sleep(HOLD_MS / 1000 + 0.05)
    after = n.frame(i, "/tmp/nid_p2.png")
    time.sleep(0.6)                                  # let the game settle again
    y1, _ = yellow_x(after)
    moved = abs(y1 - y0) if (y0 is not None and y1 is not None) else 0
    changed = n.stable_change((before, after), after)
    return moved, changed, noise


def main():
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pid = n._game_pid(i)
    if not pid:
        sys.exit("game not running")
    regs = regions(pid)
    print(f"pid {pid}: {len(regs)} regions, {sum(b-a for a,b in regs)/1e6:.0f} MB")

    noise = baseline_noise(i)
    print(f"baseline animation noise: {noise} px per 0.5 s")

    cands = candidates(i, pid, regs)
    print(f"{len(cands)} candidates")
    for k, (addr, width, tot) in enumerate(cands):
        if n._game_pid(i) != pid:
            print("game died — stopping")
            return
        moved, changed, _ = probe(i, pid, addr, width, noise)
        flag = ""
        if moved > 25:
            flag = "  <== SPRITE MOVED"
        elif changed > noise * 3 + 2000:
            flag = "  <== VIEW REACTED"
        print(f"  [{k+1}/{len(cands)}] {addr:#x} f{width*8} drift={tot:8.1f} "
              f"yellow_dx={moved:4d} changed={changed:6d}{flag}")
        if moved > 25:
            Path("/tmp/nid_x_confirmed.txt").write_text(f"{addr:#x} f{width*8}\n")
            print(f"\nCONFIRMED: {addr:#x} is a coordinate of P1 (f{width*8})")
            return
    print("no candidate moved the sprite")


if __name__ == "__main__":
    main()
