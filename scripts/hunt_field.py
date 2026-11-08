#!/usr/bin/env python3
"""Find a field that behaves as expected across known event intervals.

Usage:  python3 scripts/hunt_field.py <session> spec.json
spec:   {"expect": [[t_from, t_to, delta], ...]}   deltas in u32 units (e.g. +1 per kill)

Method: intersect, over the whole dump, the slots whose u32 delta equals the expected delta in
every interval. 4-byte slots at the same file offset are comparable because the recorder dumps the
same region set every time. Chunked so a 386 MB dump never needs to be resident.
"""
import json
import sys
from pathlib import Path

import numpy as np

d = Path(sys.argv[1]).expanduser()
spec = json.load(open(sys.argv[2]))
hs = {round(int(h.stem) / 1000.0, 1): h for h in sorted((d / "heaps").glob("*.bin"))}
times = sorted(hs)


def nearest(t, before=True):
    c = [x for x in times if (x <= t if before else x >= t)]
    if not c:
        return None
    return c[-1] if before else c[0]


CH = 32 << 20


def delta_mask_f(fa, fb, expected, mask, dtype="<f4"):
    """Same intersection, but comparing FLOAT deltas (GameMaker stores numbers as floats/doubles,
    so a score of +1 shows up as +1.0f, i.e. u32 0 -> 1065353216, not u32 0 -> 1)."""
    w = 4 if dtype == "<f4" else 8
    with open(fa, "rb") as A, open(fb, "rb") as B:
        off = 0
        while True:
            ca, cb = A.read(CH), B.read(CH)
            if not ca or not cb:
                break
            n = min(len(ca), len(cb)) // w * w
            a = np.frombuffer(ca[:n], dtype).astype(np.float64)
            b = np.frombuffer(cb[:n], dtype).astype(np.float64)
            with np.errstate(invalid="ignore"):
                eq = np.isclose(b - a, expected, atol=1e-3, rtol=0)
                eq &= np.isfinite(a) & np.isfinite(b) & (np.abs(a) < 1e6)
            sl = slice(off // w, off // w + len(eq))
            mask[sl] &= eq
            off += n


def delta_mask(fa, fb, expected, mask):
    with open(fa, "rb") as A, open(fb, "rb") as B:
        off = 0
        while True:
            ca, cb = A.read(CH), B.read(CH)
            if not ca or not cb:
                break
            n = min(len(ca), len(cb)) // 4 * 4
            a = np.frombuffer(ca[:n], "<u4").astype(np.int64)
            b = np.frombuffer(cb[:n], "<u4").astype(np.int64)
            eq = (b - a) == expected
            sl = slice(off // 4, off // 4 + len(eq))
            mask[sl] &= eq
            off += n


n_slots = hs[times[0]].stat().st_size // 4
FLOAT = "--float" in sys.argv
w = 4 if FLOAT else 4
mask = np.ones(n_slots if not FLOAT else hs[times[0]].stat().st_size // 4, dtype=bool)
print(f"{len(times)} dumps, {n_slots} u32 slots")
for t0, t1, exp in spec["expect"]:
    a, b = nearest(t0, True), nearest(t1, False)
    if a is None or b is None or a == b:
        print(f"  interval {t0}-{t1}: skipped (no dump pair)")
        continue
    before = int(mask.sum())
    if FLOAT:
        delta_mask_f(hs[a], hs[b], float(exp), mask, "<f4")
    else:
        delta_mask(hs[a], hs[b], exp, mask)
    print(f"  {a:6.1f}->{b:6.1f}  expect {exp:+d}   survivors {before} -> {int(mask.sum())}")
idx = np.nonzero(mask)[0]
print(f"\n{len(idx)} slot(s) match every interval")
# recover a sample: read the values from the first and last dump
if len(idx):
    fa, fb = hs[times[0]], hs[times[-1]]
    for i in idx[:40]:
        off = int(i) * 4
        with open(fa, "rb") as A, open(fb, "rb") as B:
            A.seek(off); B.seek(off)
            v0 = np.frombuffer(A.read(4), "<u4")[0]
            v1 = np.frombuffer(B.read(4), "<u4")[0]
        print(f"  offset {off:#x}  {v0} -> {v1}")
