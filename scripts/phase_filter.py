#!/usr/bin/env python3
"""Filter the round-phase candidates: instance state that is CONSTANT within a phase and flips
between phases, consistently over two cycles in both directions.

B1's global diff was saturated (763 survivors, 702 of them HUD draw alpha). B2's first cut was
4395 changed slots / 209 enum-like, because a single live-vs-READY pair catches every animation
that happens to differ. This adds the two missing requirements:

  * constant across 4 snapshots, 0.4 s apart, inside EACH phase (kills animation and counters)
  * the same phase -> value mapping in TWO consecutive cycles (kills one-way state)

    python3 scripts/phase_filter.py 0

Writes results/phase_candidates.json. Read-only apart from the forfeit keys.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402
import phase_b2 as b2  # noqa: E402

REPEATS = 4
GAP = 0.4


def phase_snaps(pid, instances, tag, repeats=REPEATS):
    snap = b2.snapshot(pid, instances)
    out = [snap]
    for _ in range(repeats - 1):
        time.sleep(GAP)
        out.append(b2.snapshot(pid, instances))
    print(f"   {tag}: {len(out)} snapshots")
    return out


def stable_slots(series):
    """{addr: array} of slots identical across every snapshot in the series."""
    base = series[0]
    out = {}
    for addr, raw in base.items():
        if any(snap.get(addr) is None or len(snap[addr]) != len(raw) for snap in series):
            continue
        arrs = [np.frombuffer(snap[addr][: len(raw) // 4 * 4], "<u4") for snap in series]
        ok = np.ones(len(arrs[0]), bool)
        for a in arrs[1:]:
            ok &= (a == arrs[0])
        if ok.any():
            out[addr] = (arrs[0], ok)
    return out


def forfeit_confirm(i):
    """End the round. Returns True if the screen changed away from the match."""
    n._focus(i)
    before = s.frame(i, "/tmp/pf_before.png")
    n.key(i, "Escape", hold=0.12)
    time.sleep(1.6)
    for _ in range(2):
        n.key(i, "Down", hold=0.12)
        time.sleep(0.65)
    n.key(i, "Return", hold=0.12)
    time.sleep(1.3)
    n.key(i, "Right", hold=0.12)      # dialog cursor starts on NO
    n.key(i, "Return", hold=0.12)
    time.sleep(2.5)
    after = s.frame(i, "/tmp/pf_after.png")
    if before is None or after is None:
        return False, 0
    changed = int((np.abs(before.astype(int) - after.astype(int)) > 24).sum())
    n.grab(i, f"/tmp/pf_winner_{int(time.time()) % 10000}.png")
    return changed > 2000, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--cycles", type=int, default=2)
    a = ap.parse_args()
    i = a.instance
    pid = n._game_pid(i)
    assert pid, "no game process"
    assert n.ping(pid), "spy not answering"
    assert s.find_players_by_input(i, hold=0.4, min_move=8), "needs a live, drivable match"

    print("enumerate live instances")
    mem = b2.Mem(pid)
    instances, seen = [], set()
    for typ, head in b2.type_structs(mem).items():
        for nd in b2.chain(mem, head):
            if nd["rec"] in seen or not (0x10000 < nd["type"] < 0x100000000):
                continue
            seen.add(nd["rec"])
            instances.append({"rec": nd["rec"], "node": nd["addr"], "id": nd["id"], "type": typ})
    print(f"   {len(instances)} instances")

    per_cycle = []
    for c in range(a.cycles):
        print(f"\ncycle {c + 1}")
        live = stable_slots(phase_snaps(pid, instances, "live"))
        ok, changed = forfeit_confirm(i)
        print(f"   forfeit changed {changed} px -> {'winner screen' if ok else 'REFUSED/UNCHANGED'}")
        if not ok:
            print("   (forfeit did not register; skipping this cycle)")
            continue
        over = stable_slots(phase_snaps(pid, instances, "round-over"))
        per_cycle.append((live, over))
        n.key(i, "Return", hold=0.12)     # continue
        time.sleep(3)
        if not s.ensure_match(i, verbose=False):
            print("   could not start the next round; stopping")
            break

    if len(per_cycle) < 2:
        print(f"\nINCONCLUSIVE: {len(per_cycle)} usable cycle(s), need 2 for the both-ways rule")
        return 2

    print("\nintersect the cycles (constant within a phase, same flip both times)")
    cands = []
    (l1, o1), (l2, o2) = per_cycle[0], per_cycle[1]
    for addr, (arr, ok) in l1.items():
        if addr not in o1 or addr not in l2 or addr not in o2:
            continue
        a1, ok1 = o1[addr]
        a2, ok2 = l2[addr]
        a3, ok3 = o2[addr]
        ok = ok & ok1 & ok2 & ok3
        if not ok.any():
            continue
        for k in np.nonzero(ok)[0]:
            v = [int(arr[k]), int(a1[k]), int(a2[k]), int(a3[k])]
            if v[0] == v[1] or v[2] == v[3] or v[0] != v[2] or v[1] != v[3]:
                continue                                   # not a repeatable phase flip
            cands.append({"addr": addr + int(k) * 4,
                          "region": "rec" if len(arr) * 4 == 0x200 else "node",
                          "offset": int(k) * 4, "live": v[0], "over": v[1],
                          "cycle2": [v[2], v[3]]})

    print(f"   {len(cands)} candidates flip exactly like a phase, twice")
    for c in cands[:25]:
        print(f"     {c['addr']:#x} {c['region']}+{c['offset']:#04x}  "
              f"live={c['live']} over={c['over']}")
    small = [c for c in cands if c["live"] < 0x10000 and c["over"] < 0x10000]
    print(f"   {len(small)} with enum-like values")
    out = Path("results/phase_candidates.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"candidates": cands, "small": small}, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
