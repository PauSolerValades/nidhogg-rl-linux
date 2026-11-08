#!/usr/bin/env python3
"""Identify both players' records in a LIVE match by symmetric movement.

A record is a player only if, while a key is held, it moves by a WALK-sized amount (not the
~1000 px camera copies), STOPS when released, and RETURNS when the opposite key is held. The
return test is what kills camera-derived and decay/lerp values.

  python3 scripts/identify.py [instance]
"""
import importlib.util
import sys
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "s", Path(__file__).resolve().parent.parent / "nidstate.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
n = s.n

WALK = (12.0, 260.0)      # px a fighter moves in 0.4 s (camera copies move ~1000)
STOP = 3.0                # px of drift allowed after release
RETURN = 6.0              # |d_forward + d_back| allowed for symmetry


def snap(i):
    return {a: v for a, v in s._all_record_xs(s.pid_of(i)).items()}


def probe(i, key, back_key, hold=0.4):
    """{addr: (d_forward, d_back, d_stop)} for records that moved forward at all."""
    x0 = snap(i)
    n.key(i, key, hold=hold)
    x1 = snap(i)
    time.sleep(0.45)
    x2 = snap(i)
    n.key(i, back_key, hold=hold)
    time.sleep(0.35)
    x3 = snap(i)
    out = {}
    for a, v0 in x0.items():
        if a not in x1 or a not in x2 or a not in x3:
            continue
        d_fwd = x1[a][0] - v0[0]
        d_stop = x2[a][0] - x1[a][0]
        d_back = x3[a][0] - x2[a][0]
        out[a] = (d_fwd, d_back, d_stop, v0[0], x1[a][0], x2[a][0], x3[a][0])
    return out


def pick(rows, exclude=()):
    best = []
    for a, (d_fwd, d_back, d_stop, v0, v1, v2, v3) in rows.items():
        if a in exclude:
            continue
        if not (WALK[0] <= abs(d_fwd) <= WALK[1]):
            continue
        if abs(d_stop) > STOP:
            continue
        if abs(d_fwd + d_back) > RETURN:
            continue
        best.append((abs(d_fwd), a, d_fwd, d_back, d_stop, v0, v1, v2, v3))
    best.sort(reverse=True)
    return best


if __name__ == "__main__":
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not s.in_match(i):
        print("entering a match…")
        if not s.enter_match_v2(i):
            sys.exit("could not reach a verified match")
    print("waiting 3 s for the fighters to land")
    time.sleep(3)

    p1_rows = probe(i, "d", "a")
    p1 = pick(p1_rows)
    print(f"P1 candidates: {len(p1)}")
    for mag, a, df, db, ds, v0, v1, v2, v3 in p1[:4]:
        print(f"   {a:#x}: d {df:+7.1f} back {db:+7.1f} stop {ds:+6.1f}  "
              f"x {v0:.0f}->{v1:.0f}->{v2:.0f}->{v3:.0f}")
    if not p1:
        sys.exit("no P1 candidate")
    p1_addr = p1[0][1]

    p2_rows = probe(i, "Right", "Left")
    p2 = pick(p2_rows, exclude={a for _m, a, *_ in p1[:6]})
    print(f"P2 candidates: {len(p2)}")
    for mag, a, df, db, ds, v0, v1, v2, v3 in p2[:4]:
        print(f"   {a:#x}: d {df:+7.1f} back {db:+7.1f} stop {ds:+6.1f}")
    if not p2:
        sys.exit("no P2 candidate")
    p2_addr = p2[0][1]

    print("\nrecheck after 10 s (same records, same roles?)")
    time.sleep(10)
    again = pick(probe(i, "d", "a"))
    ok1 = any(a == p1_addr for _m, a, *_ in again)
    again2 = pick(probe(i, "Right", "Left"))
    ok2 = any(a == p2_addr for _m, a, *_ in again2)
    print(f"   P1 {p1_addr:#x} still P1: {ok1}   P2 {p2_addr:#x} still P2: {ok2}")

    sword = p1_addr + 0x400
    px0 = s.read_x(s.pid_of(i), p1_addr)
    sx0 = s.read_x(s.pid_of(i), sword)
    n.key(i, "d", hold=0.4)
    time.sleep(0.2)
    px1 = s.read_x(s.pid_of(i), p1_addr)
    sx1 = s.read_x(s.pid_of(i), sword)
    print(f"\nsword at P1+0x400 ({sword:#x}): x {sx0} -> {sx1}  (P1 {px0} -> {px1})")
    print(f"\nP1={p1_addr:#x}  P2={p2_addr:#x}")
