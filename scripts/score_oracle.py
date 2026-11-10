#!/usr/bin/env python3
"""Settle the ORANGE score address: does writing it repaint the P2 HUD digit on THIS box?

The disagreement this exists for: docs/TMP_CURRENT_STATE.md says `0xd5f57c8` u32 changes the P2
bars (0 blank, 1 one bar, 2 two bars). contrib/REPLICATION.md says the write lands but the HUD
does not change. Both cannot be true on the same box.

Three measurements, and the negative one only counts because of the first two:

  1. CONTROL A  the write lands - read the u32 back after writing it.
  2. CONTROL B  the oracle is not blind - a known screen change (the pause overlay) must show up
                as changed pixels through the same code path.
  3. TEST       write 0 / 1 / 2 / 0, take the MEDIAN of several frames at each value, and diff
                only pixels that are stable within each value. Median kills the animated
                background tint; the stability mask kills the idle fighter animation. No HUD rect
                is hardcoded: a stale rect measured on a 640x480 window is mid-screen wall on this
                320x200 one, which is how a real change gets missed.

  python3 scripts/score_oracle.py [instance] [addr]

PASS = pixels change between two score values. FAIL = nothing changes while both controls hold.
"""
import importlib.util
import struct
import sys
import time
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "s", Path(__file__).resolve().parent.parent / "nidstate.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
n = s.n

VALUES = (0, 1, 2, 0)
FRAMES = 6
STABLE = 6          # max per-pixel spread allowed inside one value's frames
CHANGE = 24         # per-channel difference that counts as a changed pixel


def game_pid(i):
    """pid_of raises KeyError on a farm with no procs.json (every cold start), not None."""
    try:
        return s.pid_of(i)
    except KeyError:
        return None


def read_u32(pid, addr):
    raw = n.memory(pid, addr, 4)
    return struct.unpack("<I", raw)[0] if raw else None


def median_frames(i, tag):
    fs = np.stack([s.frame(i, f"{tag}{j}").astype(np.int16) for j in range(FRAMES)])
    return np.median(fs, axis=0), (fs.max(0) - fs.min(0)).max(axis=2)


def diff(a, b, stable, label):
    d = (np.abs(a - b).max(axis=2) > CHANGE) & stable
    ys, xs = np.where(d)
    where = f"x {xs.min()}..{xs.max()}, y {ys.min()}..{ys.max()}" if len(xs) else "none"
    print(f"  {label}: {int(d.sum()):5d} static px changed   ({where})")
    return int(d.sum()), (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


def main():
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    addr = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0xD5F57C8
    pid = game_pid(i)
    if pid is None:                            # self-contained so a claim can record one command
        print(f"starting instance {i} ...")
        n.start_ids([i])
        for _ in range(60):                    # first spawn measured ~50 s, WARMUP is not enough
            pid = game_pid(i)
            if pid:
                break
            time.sleep(3)
    if pid is None:
        print("no game process for this instance")
        return 2
    if not s.enter_ready(i):
        print("could not reach the READY screen (the only screen that draws the HUD)")
        return 2
    f = s.frame(i, "sz")
    print(f"instance {i} pid {pid} addr {addr:#x} frame {f.shape[1]}x{f.shape[0]}\n")

    # ---- control A -----------------------------------------------------------------------
    print("control A - does the write land?")
    lands = True
    for v in VALUES:
        n.poke(pid, addr, struct.pack("<I", v))
        time.sleep(0.25)
        got = read_u32(pid, addr)
        lands &= (got == v)
        print(f"  wrote {v} -> readback {got}")
    if not lands:
        print("FAIL: the write does not stick, so nothing can be concluded about the HUD")
        return 1

    # ---- control B -----------------------------------------------------------------------
    print("\ncontrol B - can the oracle see a known screen change?")
    base, sd_base = median_frames(i, "b")
    n.key(i, "Escape", hold=0.12)
    time.sleep(1.2)
    paused, sd_paused = median_frames(i, "p")
    ctrl_px, _ = diff(base, paused, (sd_base <= STABLE) & (sd_paused <= STABLE), "Escape (pause)")
    n.key(i, "Escape", hold=0.12)
    time.sleep(1.2)
    if ctrl_px < 200:
        print("FAIL: a known screen change was invisible to this oracle, so a negative result would mean nothing")
        return 1

    # ---- the test ------------------------------------------------------------------------
    print(f"\nwrite {VALUES} and diff the medians")
    meds, sds = [], []
    for v in VALUES:
        n.poke(pid, addr, struct.pack("<I", v))
        time.sleep(0.25)
        m, sd = median_frames(i, f"v{v}")
        meds.append(m)
        sds.append(sd)
        print(f"  v={v}: median taken, {int((sd <= STABLE).sum())} stable px")
    stable = np.ones_like(meds[0][:, :, 0], bool)
    for sd in sds:
        stable &= (sd <= STABLE)
    print(f"  static in every value: {int(stable.sum())} of {stable.size} px")
    changed = []
    for a in range(len(VALUES)):
        for b in range(a + 1, len(VALUES)):
            if VALUES[a] == VALUES[b]:
                continue
            px, _ = diff(meds[a], meds[b], stable, f"v{VALUES[a]} vs v{VALUES[b]}")
            changed.append(px)

    print(f"\nP2 HUD {'RESPONDS to the write' if max(changed) else 'DID NOT CHANGE'}")
    print("verdict:", "PASS" if max(changed) else "FAIL")
    return 0 if max(changed) else 1


if __name__ == "__main__":
    sys.exit(main())
