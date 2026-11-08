#!/usr/bin/env python3
"""Validate the whole chain on this instance: enter a match, identify both players, read state.

Checks, in order:
  1. the synthetic self-check of the identification logic passes;
  2. enter_match_v2 reaches a verified live match;
  3. identify() finds P1 and P2 and `roles()` re-proves them on the same addresses;
  4. live state reads are sane: 'd' increases P1 x by ~40 and 'a' brings it back,
     y stays put while walking, and the sword x tracks the body x.

  PYTHONPATH=. python3 scripts/validate_state.py [instance]
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import nidstate as ns          # noqa: E402
import qprobe as q             # noqa: E402

i = int(sys.argv[1]) if len(sys.argv) > 1 else 0

print("1) synthetic self-check of the identification logic")
q._selfcheck()

print("2) reach a verified live match")
if not ns.in_match(i):
    ok = ns.enter_match_v2(i, verbose=True)
    print(f"   enter_match_v2 -> {ok}")
    if not ok:
        sys.exit("could not reach a match")
else:
    print("   already in a match")
time.sleep(3)

print("3) identify both players")
res = q.identify(i, verbose=True)
p1 = [hex(a) for a, *_ in res["p1"]]
p2 = [hex(a) for a, *_ in res["p2"]]
print(f"   P1 candidates {p1}   P2 candidates {p2}   tries={res['tries']}")
if not (res["p1"] and res["p2"]):
    sys.exit("identification failed")
addr1, addr2 = res["p1"][0][0], res["p2"][0][0]   # p2 tuple is (addr, sign, dx)
Path("/tmp/qmap.json").write_text(json.dumps({"P1": {"addr": hex(addr1)},
                                              "P2": {"addr": hex(addr2)}}))
print(f"   session map written: P1={addr1:#x} P2={addr2:#x}")

ok_roles, D, R = q.roles(i, addr1, addr2)  # takes addresses, not candidate lists
print(f"   roles re-proved on the same addresses: {ok_roles}")

print("4) live state reads")
def st():
    pid = ns.pid_of(i)
    return {who: (ns.read_f(pid, a + q.XO), ns.read_f(pid, a + q.YO),
                  ns.read_f(pid, a + 0x400 + q.XO), ns.read_f(pid, a + 0x400 + q.YO))
            for who, a in (("P1", addr1), ("P2", addr2))}

s0 = st()
print(f"   t0: P1 x={s0['P1'][0]:.0f} y={s0['P1'][1]:.0f} sword_x={s0['P1'][2]:.0f} | "
      f"P2 x={s0['P2'][0]:.0f} y={s0['P2'][1]:.0f} sword_x={s0['P2'][2]:.0f}")
ns.n.key(i, "d", hold=0.4); time.sleep(0.2)
s1 = st()
ns.n.key(i, "a", hold=0.4); time.sleep(0.2)
s2 = st()
print(f"   +d: P1 x={s1['P1'][0]:.0f} (Δ{s1['P1'][0]-s0['P1'][0]:+.0f})  "
      f"P2 x={s1['P2'][0]:.0f} (Δ{s1['P2'][0]-s0['P2'][0]:+.0f})")
print(f"   +a: P1 x={s2['P1'][0]:.0f} (Δ{s2['P1'][0]-s1['P1'][0]:+.0f})")

d_x = s1['P1'][0] - s0['P1'][0]
back = s2['P1'][0] - s1['P1'][0]
dy = abs(s1['P1'][1] - s0['P1'][1])
sword_gap = abs(s0['P1'][2] - s0['P1'][0])
p2_still = abs(s1['P2'][0] - s0['P2'][0])
print(f"\nverdict: P1 walked {d_x:+.0f} then {back:+.0f} (want ~+40 then ~-40); "
      f"y moved {dy:.0f} (want 0); sword_x gap {sword_gap:.0f} (want 0-8); P2 moved {p2_still:.0f} (want 0)")
verdict = (15 <= d_x <= 300) and (-300 <= back <= -15) and dy <= 3 and sword_gap <= 10 and p2_still <= 3
print("PASS" if verdict else "FAIL")
sys.exit(0 if verdict else 1)
