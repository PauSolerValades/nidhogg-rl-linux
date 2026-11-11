#!/usr/bin/env python3
"""What does the READY screen actually display, and which field drives it?

The pixel-diff oracle in score_oracle.py can only say "something changed". This reads the
tally itself: the WINS blocks are bright text on a dark panel, and each win is one tall
vertical bar, so counting tall column runs gives the displayed number directly.

    python3 scripts/score_state.py 0            # snapshot: candidate fields + bar counts
    python3 scripts/score_state.py 0 --poke     # write 0/1/2 to each candidate, re-read bars

Exit codes for --poke: 0 when no candidate drives the display (the documented refutation
reproduces), 1 when one of them does (i.e. the refutation is false and we have the field).

Needs the READY screen — the only screen that draws the tally.
"""
import argparse
import subprocess
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402

# what docs/TMP_CURRENT_STATE.md claims to be the score, and its documented copies
CANDIDATES = (0xD5F57C8, 0xF3C6368, 0xF3C63E8, 0xF3C6468)
# HUD blocks on the 320x200 window: "YELLOW / WINS:" left, "ORANGE / WINS:" right
BLOCKS = {"yellow": (30, 95), "orange": (196, 255)}
BAR_ROWS = (17, 30)      # rows that only a tally bar occupies (below the "WINS:" text)


def frame(pid_ind):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "/tmp/ss.png",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if not raw:
        return None
    w, h = 320, len(raw) // (320 * 3)
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def bars(img):
    """{player: count} — tall bright column runs in the tally row band."""
    out = {}
    for name, (c0, c1) in BLOCKS.items():
        region = img[BAR_ROWS[0]:BAR_ROWS[1], c0:c1]
        bright = region.max(axis=2) > 110
        count, prev = 0, False
        for c in range(bright.shape[1]):
            on = bright[:, c].sum() >= 8      # a bar is tall, text is short
            if on and not prev:
                count += 1
            prev = on
        out[name] = count
    return out


def shoot(i):
    n.grab(i, "/tmp/ss.png")
    img = frame(i)
    return bars(img) if img is not None else None


def read_u32(pid, addr):
    raw = n.memory(pid, addr, 4)
    return struct.unpack("<I", raw)[0] if raw else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--poke", action="store_true")
    a = ap.parse_args()
    i = a.instance
    pid = n._game_pid(i)
    if not pid:                                # self-contained: a claim records one command
        print(f"starting instance {i} ...")
        n.start_ids([i])
        for _ in range(40):
            pid = n._game_pid(i)
            if pid:
                break
            time.sleep(3)
    if not pid:
        print("NO INSTANCE")
        return 2
    if not s.on_ready_screen(i) and not s.enter_ready(i):
        print("NOT READY (the tally is only drawn there)")
        return 2                                # cannot run != field found

    shown = shoot(i)
    print(f"pid {pid}  DISPLAYED: yellow {shown['yellow']} bar(s), orange {shown['orange']} bar(s)")
    print("candidate fields:")
    for addr in CANDIDATES:
        print(f"  {addr:#x} = {read_u32(pid, addr)}")

    if not a.poke:
        return 0

    print("\nwriting 0/1/2 to each candidate, re-reading the display:")
    original = {addr: read_u32(pid, addr) for addr in CANDIDATES}
    detected = []
    for addr in CANDIDATES:
        for v in (0, 1, 2):
            n.poke(pid, addr, struct.pack("<I", v))
            time.sleep(0.12)
            b = shoot(i)
            mark = ""
            if b["orange"] != shown["orange"] or b["yellow"] != shown["yellow"]:
                mark = "   <== DISPLAY CHANGED"
                detected.append((addr, v, b))
            print(f"  {addr:#x} := {v}: yellow {b['yellow']}, orange {b['orange']}{mark}")
    for addr, v in original.items():          # put the fields back
        n.poke(pid, addr, struct.pack("<I", v if v is not None else 0))
    time.sleep(0.15)
    after = shoot(i)
    print(f"\nrestored -> displayed: yellow {after['yellow']}, orange {after['orange']}")
    if detected:
        print("FOUND: the display follows", ", ".join(f"{hex(x)}(={v})" for x, v, _ in detected))
        return 1                                # a field drives it: the claim is false
    print("REFUTATION HOLDS: no candidate field drives the displayed tally")
    return 0


if __name__ == "__main__":
    import time
    sys.exit(main())
