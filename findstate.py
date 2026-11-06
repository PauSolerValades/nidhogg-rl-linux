#!/usr/bin/env python3
"""Find the fighter position in the running game's memory.

Works on the attract-mode demo, which needs no menu at all: the game plays
itself on the title screen, so two fighters move without any input from us.

Method: dump one heap region repeatedly and keep the 8-byte slots that
  * hold a plausible coordinate the whole time,
  * move in small steps (fighters run at ~12 px/s, never teleport),
  * have a partner slot 16 bytes away holding a plausible y (RValue pairs).
Verification is by writing: poke the candidate to 300 and see the fighter jump.

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

SAMPLES = 8
STEP = 0.6


def biggest_anon(pid, limit=200 << 20):
    best = None
    for line in open(f"/proc/{pid}/maps"):
        p = line.split()
        if p[1][:2] != "rw" or len(p) > 5 and p[-1].startswith("/"):
            continue
        a, b = (int(x, 16) for x in p[0].split("-"))
        if 4096 <= b - a <= limit and (best is None or b - a > best[1] - best[0]):
            best = (a, b)
    return best


def dump(pid, addr, size, path="/tmp/nid_scan.bin"):
    out = Path(path)
    out.unlink(missing_ok=True)
    Path(f"/tmp/nid_cmd_{pid}").write_text(f"dump {addr:x} {size:x} {path}\n")
    for _ in range(120):
        time.sleep(0.1)
        if out.exists():
            return np.fromfile(path, dtype="<f8")
    return None


def poke(pid, addr, value):
    Path(f"/tmp/nid_cmd_{pid}").write_text(
        f"poke {addr:x} {struct.pack('<d', value).hex()}\n")


def main():
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pid = n._game_pid(i)
    if not pid:
        sys.exit("game not running")
    addr, end = biggest_anon(pid)
    print(f"pid {pid} heap {addr:#x}-{end:#x} ({(end-addr)/1e6:.0f} MB)")

    frames = []
    for k in range(SAMPLES):
        a = dump(pid, addr, end - addr)
        if a is None:
            sys.exit("dump failed")
        frames.append(a)
        print(f"  sample {k}: {len(a)} slots, t={k*STEP:.1f}s")
        time.sleep(STEP)
    m = min(len(f) for f in frames)
    fs = np.stack([f[:m] for f in frames])

    ok = (np.abs(fs) < 500).all(0) & np.isfinite(fs).all(0)
    d = np.diff(fs, axis=0)
    smooth = (np.abs(d) < 40).all(0) & (np.abs(d) > 0.2).any(0)
    idx = np.nonzero(ok & smooth)[0]
    print(f"{len(idx)} smooth moving coordinate-like slots")

    # partner 2 slots (16 bytes) later must be a plausible y the whole time
    y = np.abs(fs[:, idx + 2]) if idx.max() + 2 < m else None
    print("all smooth candidates:", [(hex(addr + k*8), round(float(fs[-1, k]), 1)) for k in idx[:30]])
    keep = []
    for j, k in enumerate(idx):
        if k + 2 >= m:
            continue
        ys = np.abs(fs[:, k + 2])
        if (ys < 260).all() and (ys > 20).any():
            keep.append((k, float(fs[-1, k]), float(ys[-1])))
    print(f"{len(keep)} with a y-like neighbour:")
    for k, xv, yv in keep[:25]:
        print(f"  {addr + k*8:#x}  x={xv:8.2f}  y={yv:8.2f}")
    Path("/tmp/nid_candidates.txt").write_text(
        "\n".join(f"{addr + k*8:#x}" for k, _, _ in keep))


if __name__ == "__main__":
    main()
