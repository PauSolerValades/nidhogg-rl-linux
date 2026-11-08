#!/usr/bin/env python3
"""Mine a human play session: find event times from screenshots, then diff the heap around them.

The body pointers we recorded go stale (the heap repurposes those addresses within a minute), so
this deliberately ignores them: `shots/` gives the *when*, `heaps/` gives the *what*.

  python3 scripts/mine_session.py ~/nidhogg-record/<stamp>            # list detected events
  python3 scripts/mine_session.py <dir> --diff                        # diff heaps around each event
  python3 scripts/mine_session.py <dir> --diff --top 12
"""
import subprocess
import sys
from pathlib import Path

import numpy as np


def frame(p):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(p),
                          "-vf", "scale=40:25", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8)


def events(shots, thresh=18.0):
    """Screenshot-to-screenshot change magnitude -> (time_s, magnitude, path_before, path_after)."""
    files = sorted(shots.glob("*.png"))
    out = []
    prev = None
    for f in files:
        cur = frame(f)
        if prev is not None and cur.size == prev[1].size:
            mag = float(np.abs(cur.astype(int) - prev[1].astype(int)).mean())
            if mag > thresh:
                out.append((int(f.stem) / 1000.0, mag, prev[0], f))
        prev = (f, cur)
    return out


def heaps(d):
    hs = sorted(d.glob("*.bin"))
    return [(int(h.stem) / 1000.0, h) for h in hs]


def around(hs, t):
    before = [h for h in hs if h[0] <= t]
    after = [h for h in hs if h[0] > t]
    return (before[-1] if before else None, after[0] if after else None)


def diff_pairs(pair, chunk=64 << 20, top=200):
    """int32/u32 slots whose 4-byte value changed between two dump files (chunked, low RAM)."""
    (t0, fa), (t1, fb) = pair
    hits = []
    a, b = fa.open("rb"), fb.open("rb")
    off = 0
    while True:
        ca, cb = a.read(chunk), b.read(chunk)
        if not ca or not cb:
            break
        n = min(len(ca), len(cb)) // 4 * 4
        ua = np.frombuffer(ca[:n], "<u4")
        ub = np.frombuffer(cb[:n], "<u4")
        neq = np.nonzero(ua != ub)[0]
        for i in neq:
            hits.append((off + int(i) * 4, int(ua[i]), int(ub[i])))
            if len(hits) > 400000:
                break
        off += n
    return hits


if __name__ == "__main__":
    d = Path(sys.argv[1]).expanduser()
    do_diff = "--diff" in sys.argv
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 8
    ev = events(d / "shots")
    hs = heaps(d / "heaps")
    print(f"session {d.name}: {len(list((d/'shots').glob('*.png')))} shots, {len(hs)} heaps, "
          f"{len(ev)} candidate events")
    for t, mag, fa, fb in ev[:20]:
        print(f"  event {t:7.1f}s  magnitude {mag:5.1f}")
    if do_diff and hs:
        print("\ndiffing heaps around the first events:")
        for t, mag, fa, fb in ev[:top]:
            pair = around(hs, t)
            if not pair[0] or not pair[1]:
                print(f"  {t:7.1f}s: no heap pair")
                continue
            hits = diff_pairs(pair)
            small = [h for h in hits if 0 <= h[1] < 100000 and 0 <= h[2] < 100000]
            stepped = [h for h in small if abs(h[2] - h[1]) <= 3]
            print(f"  {t:7.1f}s  heaps {pair[0][0]:.0f}s->{pair[1][0]:.0f}s  "
                  f"changed {len(hits)} slots, {len(small)} small-int, {len(stepped)} stepped 1..3")
            for off, a, b in stepped[:6]:
                print(f"      +{off:#x}  {a} -> {b}")
