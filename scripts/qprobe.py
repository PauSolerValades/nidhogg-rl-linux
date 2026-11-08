#!/usr/bin/env python3
"""Worker q: reliable P1/P2 identification in a LIVE match.

Identification = four independent, falsifiable tests on one 0x200 record:
  sign    d moves x up, a moves x down (a camera/view copy moves the wrong way)
  size    15..300 px while held (rejects the ~1000 px screen-space copies)
  stop    |dx| <= 3 px after release (rejects AI/attract drift)
  reverse  |dd + da| small: 'a' undoes exactly what 'd' did
  sword   the sibling at +0x200 (arm) AND +0x400 (sword) move by the same delta
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np

import nidstate as ns
n = ns.n

REC, XO, YO = 0x200, 0xEC, 0xF0
HEAPS = {}


def heaps_of(pid):
    if pid not in HEAPS:
        HEAPS[pid] = [r for r in ns.regions(pid) if r[1] - r[0] >= (1 << 20)]
    return HEAPS[pid]


def snap(pid, xlo=-800.0, xhi=4000.0, ylo=0.0, yhi=700.0):
    """{record: (x, y)} over every 0x200 slot in every rw region (wide bounds)."""
    hs = heaps_of(pid)
    reqs = [(a, b - a, f"/tmp/qs_{pid}_{i}.bin") for i, (a, b) in enumerate(hs)]
    out = {}
    for (a, b), raw in zip(hs, n.memory_many(pid, reqs)):
        if raw is None:
            continue
        f = np.frombuffer(raw[: len(raw) // 4 * 4], "<f4")
        idx = np.arange(0, len(f) - YO // 4 - 1, REC // 4)
        xs, ys = f[idx + XO // 4], f[idx + YO // 4]
        with np.errstate(invalid="ignore"):
            ok = (np.isfinite(xs) & np.isfinite(ys)
                  & (xs > xlo) & (xs < xhi) & (ys > ylo) & (ys < yhi))
        for j in np.nonzero(ok)[0]:
            out[a + int(idx[j]) * 4] = (float(xs[j]), float(ys[j]))
    return out


def probe(i, pid, key, hold=0.4, settle=0.4):
    """dx while held, dx after release, dy while held -- for every record."""
    s0 = snap(pid)
    n.key(i, key, hold=hold)
    s1 = snap(pid)
    time.sleep(settle)
    s2 = snap(pid)
    out = {}
    for a, v0 in s0.items():
        if a in s1 and a in s2:
            out[a] = (s1[a][0] - v0[0], s2[a][0] - s1[a][0], s1[a][1] - v0[1], v0)
    return out


def sel(pr, sign, lo=15.0, hi=300.0, stop=3.0, dy=3.0):
    """Records that moved walk-sized in the key's own direction and then stopped."""
    return {a: v for a, v in pr.items()
            if sign * v[0] >= lo and abs(v[0]) <= hi
            and abs(v[1]) <= stop and abs(v[2]) <= dy}


def report(pr, k=12):
    top = sorted(pr.items(), key=lambda kv: -abs(kv[1][0]))[:k]
    return [(hex(a), round(v[0], 1), round(v[1], 1), round(v[2], 1),
             round(v[3][0], 1), round(v[3][1], 1)) for a, v in top]


def evaluate(probes, verbose=False):
    """(P1 candidates, P2 candidates) from the four probes. Pure, so it can be re-run."""
    D, A = probes["d"], probes["a"]
    cd, ca = sel(D, +1), sel(A, -1)

    def sib(a, pr):
        """arm (+0x200) and sword (+0x400) follow the body? body is the head of the chain."""
        da = pr[a + 0x200][0] if a + 0x200 in pr else None
        ds = pr[a + 0x400][0] if a + 0x400 in pr else None
        ok = (da is not None and ds is not None
              and abs(da - pr[a][0]) <= 4 and abs(ds - pr[a][0]) <= 4)
        head = not (a - 0x200 in pr and abs(pr[a - 0x200][0] - pr[a][0]) <= 4)
        return ok and head

    p1 = [(a, vd[0], ca[a][0]) for a, vd in cd.items()
          if a in ca and abs(vd[0] + ca[a][0]) <= max(6.0, 0.25 * abs(vd[0]))
          and sib(a, D)]
    p1a = {x[0] for x in p1}
    p2 = []
    for key_r, key_l in ALT_KEYS:
        R, L = probes.get(key_r), probes.get(key_l)
        if not R or not L:
            continue
        for sr in (-1, +1):                    # sign is learned from the data, size+stop is not
            for a, vr in sel(R, sr).items():
                if a not in L or a in p1a:
                    continue
                if abs(vr[0] + L[a][0]) <= max(6.0, 0.25 * abs(vr[0])) and sib(a, R):
                    p2.append((a, sr, vr[0], L[a][0]))
        if p2:
            break
    if verbose:
        print("  d movers   :", report(D, 6))
        print("  R movers   :", report(probes["Right"], 6))
        print("  walk+stop: d=%d a=%d walk+rev+sword P1=%d P2=%d"
              % (len(cd), len(ca), len(p1), len(p2)))
    return p1, p2


KEYS4 = ("d", "a", "Right", "Left")
# P2's binding on READY is the arrows (measured). These are only probed if the arrows fail.
ALT_KEYS = (("Right", "Left"), ("l", "j"), ("k", "i"), ("d", "a"))


def identify(i, tries=4, verbose=False, settle=0.4):
    """Identification with a retry: a fighter can be pinned against scenery, in which case
    the reversal test finds nothing. Reposition and probe again."""
    pid = ns.pid_of(i)
    used = 0
    for t in range(tries):
        used = t + 1
        probes = {k: probe(i, pid, k) for k in KEYS4}
        if not any(k in probes for k in ("l", "j")):
            p1, p2 = evaluate(probes, verbose)
        if not p2:                              # arrows did not answer: try the alt bindings
            for k in ("l", "j", "k", "i"):
                probes[k] = probe(i, pid, k)
            p1, p2 = evaluate(probes, verbose)
        if p1 and p2:
            break
        else:
            probes = {k: probes[k] for k in KEYS4}
        for k in (("a", "Left") if t % 2 == 0 else ("d", "Right")):
            n.key(i, k, hold=0.7)
            time.sleep(0.15)
    if verbose:
        print(f"  P1: {[(hex(a), round(x,1)) for a, x, _ in p1]}"
              f"  P2: {[(hex(a), s, round(x,1)) for a, s, x, _ in p2]}  tries={used}")
    return {"pid": pid, "probes": probes, "p1": p1, "p2": p2, "tries": used}


def roles(i, p1, p2, tries=3, hold=0.4):
    """Re-prove the roles on the SAME addresses: d moves p1 only, Right moves p2 only.

    A fighter standing against scenery cannot walk that way, so a failed round nudges both
    players in the blocked direction and retries. Returns (ok, d_probe, right_probe).
    """
    pid = ns.pid_of(i)
    for t in range(tries):
        D, R = probe(i, pid, "d", hold=hold), probe(i, pid, "Right", hold=hold)
        d1, d2 = D.get(p1, (0.0,))[0], D.get(p2, (0.0,))[0]
        r1, r2 = R.get(p1, (0.0,))[0], R.get(p2, (0.0,))[0]
        if d1 >= 12 and abs(d2) <= 3 and r2 >= 12 and abs(r1) <= 3:
            return True, D, R
        for key, stuck in (("d", d1 < 12), ("Right", r2 < 12)):
            if stuck:                           # back off the obstacle, then retry
                n.key(i, "a" if key == "d" else "Left", hold=0.7)
                time.sleep(0.15)
    return False, D, R


def state(i):
    """read_state_recipe, literally: (P1 x,y,sword) and (P2 x,y,sword) or None."""
    pid = ns.pid_of(i)
    r = json.loads(Path("/tmp/qmap.json").read_text()) if Path("/tmp/qmap.json").exists() else None
    if not r:
        return None
    out = {}
    for who in ("P1", "P2"):
        a = int(r[who]["addr"], 16)
        x, y = ns.read_f(pid, a + XO), ns.read_f(pid, a + YO)
        sx, sy = ns.read_f(pid, a + 0x400 + XO), ns.read_f(pid, a + 0x400 + YO)
        out[who] = (x, y, sx, sy)
    return out


def _selfcheck():
    """Synthetic probes: a body triple must win, its arm/sword and a camera copy must lose."""
    def key(dx, free=0.0, dy=0.0, x=500.0):
        return (dx, free, dy, (x, 192.0))

    B, B2, CAM = 0x100000, 0x100800, 0x200000
    mk = lambda dd: {B: key(dd), B + 0x200: key(dd), B + 0x400: key(dd),
                     B2: key(0.0), B2 + 0x200: key(0.0), B2 + 0x400: key(0.0),
                     CAM: key(-156.0)}          # camera copy: big, reverses, wrong sign
    p_d, p_a = mk(40.0), mk(-40.0)
    for a in (B, B + 0x200, B + 0x400):
        p_d[a] = key(40.0)
        p_a[a] = key(-40.0)
    # P2: arrows, mirror of P1
    for base, d1, d2 in ((B, 40.0, -40.0), (B2, 40.0, -40.0)):
        for off in (0, 0x200, 0x400):
            p_d[base + off] = key(d1 if base == B else 0.0)
            p_a[base + off] = key(d2 if base == B else 0.0)
    p_R = {a: key(40.0 if B2 <= a <= B2 + 0x400 else 0.0) for a in p_d}
    p_L = {a: key(-40.0 if B2 <= a <= B2 + 0x400 else 0.0) for a in p_d}
    probes = {"d": p_d, "a": p_a, "Right": p_R, "Left": p_L}
    p1, p2 = evaluate(probes)
    print("p1", [hex(a) for a, *_ in p1], "p2", [hex(a) for a, *_ in p2])
    assert [a for a, *_ in p1] == [B], p1          # not arm, not sword, not the camera copy
    assert [a for a, *_ in p2] == [B2], p2
    # blocked body (pinned to a wall) must NOT be accepted on symmetry alone
    p_a[B] = key(0.0)
    assert not [a for a, *_ in evaluate(probes)[0]], "blocked body must not pass"
    print("selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
