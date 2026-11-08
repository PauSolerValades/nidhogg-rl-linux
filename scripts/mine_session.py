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


def events(shots, min_px=30, settle=1.0):
    """Event times from STRUCTURE, not motion: are both fighters drawn?

    Camera scroll makes frame-to-frame motion useless as an event detector (55 of 127 frames
    "changed" during ordinary walking). Presence does not lie:
        orange vanishes, yellow stays -> P2 died
        yellow vanishes, orange stays -> P1 died
        neither present               -> a UI screen (stage select / menus)
    Returns [(time_s, kind)] where kind is one of p2_gone / p1_gone / ui / resume.
    """
    files = sorted(shots.glob("*.png"))
    state = {}
    out = []
    last = None
    for f in files:
        raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(f),
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout
        a = np.frombuffer(raw, np.uint8)
        if not a.size:
            continue
        a = a.reshape(-1, 3).astype(int)
        r, g, b = a[:, 0], a[:, 1], a[:, 2]
        y = int(((r > 240) & (g > 240) & (b < 80)).sum())
        o = int(((r > 240) & (g > 105) & (g < 205) & (b < 115)).sum())
        t = int(f.stem) / 1000.0
        cur = "both" if (y > min_px and o > min_px) else (
            "none" if y + o < min_px else ("p1" if y > min_px else "p2"))
        if last is not None and cur != last[0] and t - last[1] > settle * 0.5:
            kind = {"p2": "p2_gone", "p1": "p1_gone", "none": "ui", "both": "resume"}.get(cur, cur)
            out.append((t, kind))
        last = (cur, t)
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
