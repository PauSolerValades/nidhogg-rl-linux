#!/usr/bin/env python3
"""Who holds pointers to the fighter records?

The fighters' addresses are known (proven x/y offsets), but their identity is not: after a
round or room transition the old records freeze and new ones appear, so "which record is P1"
has to be re-proved by pressing keys. If the ENGINE keeps a pointer to each instance, that
re-proof is unnecessary — read the pointer instead.

This scans every readable region for the 8-byte value of each fighter address. A hit is
something that references the instance: the instance list linkage, a manager object, or a
GML variable holding a `with`/id. Hits that contain BOTH schools within a small window are
the interesting ones — that is a match/player manager, i.e. authoritative identity.

    python3 scripts/ptr_scan.py 0            # instance id
    python3 scripts/ptr_scan.py --pid 1234 --addr 0x7e8c2c5ec400 --addr 0x7e8c2c718400

Read-only, no input, safe to run on any screen that has fighters (attract demo included).
"""
import argparse
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402

WINDOW = 0x100          # how close two pointers must be to be called "one structure"


def scan(pid, targets, min_size=0x1000):
    """{target: [(region_base, byte_offset), ...]} over every readable rw region."""
    regions = [r for r in s.regions(pid, min_size=min_size) if r[1] - r[0] >= min_size]
    reqs = [(a, b - a, f"/tmp/pscan_{i}.bin") for i, (a, b) in enumerate(regions)]
    blobs = n.memory_many(pid, reqs, timeout=60)
    hits = {t: [] for t in targets}
    scanned = 0
    for (a, b), raw in zip(regions, blobs):
        if raw is None:
            continue
        scanned += len(raw)
        words = np.frombuffer(raw[: len(raw) // 8 * 8], "<u8")
        for t in targets:
            for idx in np.nonzero(words == t)[0]:
                hits[t].append((a, int(idx) * 8))
    return hits, scanned, regions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--pid", type=int)
    ap.add_argument("--addr", action="append", type=lambda x: int(x, 0))
    a = ap.parse_args()

    pid = a.pid or n._game_pid(a.instance)
    assert pid, "no game process"
    assert n.ping(pid), f"spy not answering in {pid}"

    if a.addr:
        targets = a.addr[:2]
        print("targets given:", [hex(t) for t in targets])
    else:
        recs = s.find_fighters(pid)
        assert len(recs) >= 2, f"only {len(recs)} fighter records — need fighters on screen"
        # the two members of the pair that share a type pointer and stand on one ground line
        groups = {}
        for rec in recs:
            groups.setdefault(rec[3], []).append(rec)
        pair = next(g for g in groups.values() if len(g) == 2)
        targets = [pair[0][0], pair[1][0]]
        print(f"fighters: {targets[0]:#x} x={pair[0][1]:.1f}  {targets[1]:#x} x={pair[1][1]:.1f}"
              f"  (type {pair[0][3]:#x})")

    hits, scanned, regions = scan(pid, targets)
    print(f"scanned {len(regions)} regions / {scanned / 2**20:.0f} MB")
    for t in targets:
        hs = hits[t]
        print(f"\n{t:#x}: {len(hs)} references")
        for base, off in hs[:12]:
            print(f"   {base + off:#x}   (region {base:#x} +{off:#x})")

    # a reference block that holds BOTH fighters, close together = a manager/instance list
    print("\nblocks holding both:")
    found = 0
    for base, off in hits[targets[0]]:
        for base2, off2 in hits[targets[1]]:
            if base == base2 and abs(off - off2) <= WINDOW:
                found += 1
                lo = max(0, min(off, off2) - 0x40) // 8 * 8
                hi = max(off, off2) + 0x40
                raw = Path(f"/tmp/pscan_{[i for i, r in enumerate(regions) if r[0] == base][0]}.bin").read_bytes()
                print(f"  at {base + lo:#x}:")
                for p in range(lo, min(hi, len(raw) - 8), 8):
                    v = struct.unpack_from("<Q", raw, p)[0]
                    tag = ""
                    if v in targets:
                        tag = "  <== fighter"
                    print(f"    +{p - lo:#05x} {v:#018x}{tag}")
                if found >= 3:
                    break
        if found >= 3:
            break
    if not found:
        print("  none — no engine structure references both fighters within "
              f"{WINDOW:#x} bytes")


if __name__ == "__main__":
    main()
