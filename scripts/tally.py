#!/usr/bin/env python3
"""Read the READY-screen tally: how many wins does each player show?

Every experiment that needed a round boundary died on screen-state detection (on_ready_screen
was too strict for the winner screen, and a brightness threshold counted the "WINS:" text as
bars). This reads the two documented digit rectangles with the documented TEXT COLOURS, so a
glyph of the wrong colour cannot be mistaken for a bar.

    python3 scripts/tally.py 0            # live: grab the window and read it
    python3 scripts/tally.py --image /tmp/shot.png

Returns {"ready": bool, "yellow": n, "orange": n}. `ready` is true only when BOTH digit rects
contain the player's text colour somewhere — i.e. the HUD is actually drawn.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402

# documented in docs/TMP_CURRENT_STATE.md §2.6 (HUD oracle)
RECTS = {"yellow": (56, 14, 80, 30), "orange": (214, 14, 238, 30)}
COLOURS = {"yellow": (166, 166, 0), "orange": (166, 104, 42)}
TOL = 40          # per-channel tolerance
BAR_ROWS = 9      # a bar is a tall run; the "WINS:" text is short
BAR_MIN = 8       # columns-pixels a column needs to count as a bar


def load(path=None):
    if path is None:
        p = tempfile.mktemp(suffix=".png")
        n.grab(0, p)
        path = p
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if not raw:
        return None
    return np.frombuffer(raw, np.uint8).reshape(len(raw) // (320 * 3), 320, 3)


def read(img):
    out = {"ready": False}
    drawn = 0
    for who, (x0, y0, x1, y1) in RECTS.items():
        reg = img[y0:y1, x0:x1].astype(int)
        col = COLOURS[who]
        mask = (np.abs(reg - np.array(col)).max(axis=2) <= TOL)
        if mask.any():
            drawn += 1
        runs, prev = 0, False
        for c in range(mask.shape[1]):
            on = mask[:, c].sum() >= BAR_MIN
            if on and not prev:
                runs += 1
            prev = on
        out[who] = runs
    out["ready"] = drawn == 2       # both rects show their text colour => the HUD is drawn
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--image")
    a = ap.parse_args()
    img = load(a.image)
    if img is None:
        print("could not read the screen")
        return 2
    r = read(img)
    print(f"ready={r['ready']}  YELLOW={r['yellow']}  ORANGE={r['orange']}")
    return 0 if r["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
