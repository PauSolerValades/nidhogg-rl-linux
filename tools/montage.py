#!/usr/bin/env python3
"""Tile PNGs into one PNG using ffmpeg + numpy (ImageMagick is not installed on the server).

  python3 tools/montage.py out.png --cols 4 a.png b.png ...
  python3 tools/montage.py out.png --cols 4 --scale 2 a.png b.png ...
"""
import subprocess
import sys

import numpy as np


def load(p):
    w, h = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height", "-of", "csv=p=0", p],
                          capture_output=True, text=True).stdout.strip().split(",")
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", p,
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(int(h), int(w), 3)


def main():
    out = sys.argv[1]
    args = sys.argv[2:]
    cols, scale = 4, 1
    if "--cols" in args:
        i = args.index("--cols"); cols = int(args[i + 1]); del args[i:i + 2]
    if "--scale" in args:
        i = args.index("--scale"); scale = int(args[i + 1]); del args[i:i + 2]
    imgs = [load(p) for p in args]
    h = max(i.shape[0] for i in imgs)
    w = max(i.shape[1] for i in imgs)
    rows = (len(imgs) + cols - 1) // cols
    pad = 3
    canvas = np.full((rows * (h + pad) + pad, cols * (w + pad) + pad, 3), 34, np.uint8)
    for k, img in enumerate(imgs):
        r, c = divmod(k, cols)
        y, x = pad + r * (h + pad), pad + c * (w + pad)
        canvas[y:y + img.shape[0], x:x + img.shape[1]] = img
    if scale > 1:
        canvas = np.repeat(np.repeat(canvas, scale, axis=0), scale, axis=1)
    H, W = canvas.shape[:2]
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-i", "-",
                    out], input=canvas.tobytes(), check=True)
    print(f"{out} ({W}x{H}, {len(imgs)} tiles)")


if __name__ == "__main__":
    main()
