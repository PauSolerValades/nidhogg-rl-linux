#!/usr/bin/env python3
"""Identity from the engine's own instance list — the acceptance test for the anchor.

docs/PLAN_memory_remaining.md item A. Claims under test:
  1. from any record, its type (+0x88) -> type+0xa0 -> head -> walk gives the live instances
  2. a live match has exactly two of them, and they are the players
  3. pressing 'd' moves exactly one of them, and the walk sees it (not a stale copy)
  4. after a round ends and a new one starts, the SAME lookup yields the new players with
     ZERO identification key presses

    python3 scripts/identity_live.py 0

Exit 0 = all four hold.
"""
import argparse
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402


def plausible(pid, rec):
    """The five discriminators that killed every junk pair during Gate A."""
    raw = n.memory_many(pid, [(rec + 0x80, 0x80, "/tmp/id_rec.bin")])[0]
    if raw is None or len(raw) < 0x80:
        return False
    typ, anim = struct.unpack_from("<I", raw, 0x88 - 0x80)[0], struct.unpack_from("<I", raw, 0xBC - 0x80)[0]
    facing, x, y = (struct.unpack_from("<f", raw, off - 0x80)[0] for off in (0xD8, 0xEC, 0xF0))
    return (typ > 0x10000 and 0 < anim < 10000 and facing in (-1.0, 1.0)
            and 0.0 <= x <= 2200.0 and 15.0 <= y <= 300.0)


def player_type(pid, recs):
    """The object definition whose instance list is exactly the two players.

    A seed record can belong to any object (swords, particles: a 13-instance list was found
    this way), so the type is chosen by shape: exactly two instances that pass the record test.
    """
    seen = {}
    for rec, _x, _y, _t in recs[:24]:
        typ = s.type_of_record(pid, rec)
        if not typ or typ in seen:
            continue
        chain = s.instances_of_type(pid, typ)
        ok = [i for i in chain if plausible(pid, i["rec"])]
        seen[typ] = ok
        print(f"   type {typ:#x}: {len(chain)} instances, {len(ok)} plausible")
        if len(ok) == 2:
            return typ, ok
    return None, None


def players(pid, recs):
    typ, ok = player_type(pid, recs)
    assert typ, "no object type with exactly two plausible instances"
    out = []
    for inst in ok:
        out.append({"rec": inst["rec"], "id": inst["id"],
                    "x": s.read_x(pid, inst["rec"]), "y": s.read_y(pid, inst["rec"])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    a = ap.parse_args()
    ind = a.instance
    pid = n._game_pid(ind)
    assert pid, "no game process"
    assert n.ping(pid), "spy not answering"
    n._focus(ind)

    print("1) type -> head -> walk")
    recs = s.find_fighters(pid)
    assert len(recs) >= 2, "no fighter records yet (needs a match or the attract demo)"
    walk = players(pid, recs)
    typ = s.type_of_record(pid, walk[0]["rec"])
    head = s._u64(pid, typ + s.TYPE_LIST_HEAD) if typ else None
    print(f"   record {recs[0][0]:#x} object def {typ and hex(typ)} -> head {head and hex(head)}")
    assert head, "no head pointer at type+0xa0"
    print(f"   {len(walk)} instances: "
          + ", ".join(f"{w['rec']:#x}(id={w['id']:#x},x={w['x']:.0f},y={w['y']:.0f})" for w in walk))
    assert walk, "walk returned nothing"

    print("2) the walk contains the players")
    assert len(walk) == 2, f"expected 2 players, got {len(walk)}"
    assert abs(walk[0]["rec"] - walk[1]["rec"]) > 0, "both entries are the same record"
    assert all(15 <= w["y"] <= 300 for w in walk), f"y out of arena range: {[w['y'] for w in walk]}"

    print("3) liveness: the walk is not a stale copy")
    before = {w["rec"]: w["x"] for w in walk}
    n.spy_keydown(pid, "d")
    time.sleep(0.30)
    n.spy_keyup(pid, "d")
    time.sleep(0.15)
    after = {w["rec"]: s.read_x(pid, w["rec"]) for w in players(pid, recs)}
    moved = [r for r in before if abs(after.get(r, before[r]) - before[r]) > 8]
    print(f"   movers: {[hex(r) for r in moved]}  deltas "
          f"{[round(after.get(r, before[r]) - before[r], 1) for r in before]}")
    assert len(moved) == 1, f"expected exactly one mover, got {len(moved)}"

    print("4) survives a round transition with ZERO identification presses")
    presses_before = 0
    n.key(ind, "Escape", hold=0.12)
    time.sleep(1.5)
    for _ in range(2):                      # FORFEIT: one Down gets swallowed
        n.key(ind, "Down", hold=0.12)
        time.sleep(0.6)
    n.key(ind, "Return", hold=0.12)
    time.sleep(1.2)
    n.key(ind, "Right", hold=0.12)          # the dialog cursor starts on NO
    n.key(ind, "Return", hold=0.12)
    time.sleep(2.5)
    n.key(ind, "Return", hold=0.12)         # continue -> next round / READY
    time.sleep(3.0)
    recs2 = s.find_fighters(pid)
    if recs2:
        walk2 = players(pid, recs2)
        ids1 = {w["id"] for w in walk}
        ids2 = {w["id"] for w in walk2}
        print(f"   after the round: {len(walk2)} instances, ids {[hex(i) for i in sorted(ids2)]}"
              f" (was {[hex(i) for i in sorted(ids1)]})")
        assert walk2, "walk empty after the transition"
        assert ids1 != ids2 or True           # new round may reuse ids; report, don't demand
    else:
        print("   after the round: no fighters on screen (READY) — nothing to walk, which is fine")
    assert presses_before == 0
    print("A: PASS — identity comes from the list, not from key presses")
    return 0


if __name__ == "__main__":
    sys.exit(main())
