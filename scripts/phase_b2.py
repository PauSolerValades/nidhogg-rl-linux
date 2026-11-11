#!/usr/bin/env python3
"""B2: the round-boundary diff, restricted to LIVE INSTANCES.

B1 compared all 2.7 GB of rw memory across boundaries and was saturated by draw/freed state
(763 survivors, the top cluster being HUD text alpha). The phase field is almost certainly a
field of a controller *instance*, and since identity now comes from the instance list
(docs/PLAN_memory_remaining.md §2.9) we can restrict the comparison to instance state only:

  type structs -> head (type+0xa0) -> chain -> records -> diff those 0x200 bytes (and the
  0x80 node headers) across a round boundary

That is tens of KB instead of 2.7 GB, and every candidate is inside a live object.

    python3 scripts/phase_b2.py 0

Needs a live match (`nidstate.ensure_match`). Read-only; dumps are deleted afterwards.
"""
import argparse
import json
import struct
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402

NODE = 0x80
OFF_TYPE, OFF_PREV, OFF_NEXT, OFF_ID, OFF_REC = 0x18, 0x30, 0x38, 0x40, 0x48
HEAD_OFF = s.TYPE_LIST_HEAD


class Mem:
    def __init__(self, pid):
        self.blobs = []
        ranges, reqs = [], []
        for i, (a, b) in enumerate(s.regions(pid, min_size=1 << 20)):
            ranges.append((a, b))
            reqs.append((a, b - a, f"/tmp/b2_{i}.bin"))
        for (a, b), raw in zip(ranges, n.memory_many(pid, reqs, timeout=240)):
            if raw:
                self.blobs.append((a, b, raw))
        self.by_base = {a: (b, raw) for a, b, raw in self.blobs}

    def region_of(self, addr, size=8):
        for a, b, raw in self.blobs:
            if a <= addr and addr + size <= b:
                return a, raw
        return None

    def u64(self, addr):
        r = self.region_of(addr, 8)
        return struct.unpack_from("<Q", r[1], addr - r[0])[0] if r else None

    def node(self, addr):
        r = self.region_of(addr, NODE)
        if r is None:
            return None
        f = struct.unpack_from("<16Q", r[1], addr - r[0])
        return {"addr": addr, "type": f[OFF_TYPE // 8], "prev": f[OFF_PREV // 8],
                "next": f[OFF_NEXT // 8], "id": f[OFF_ID // 8], "rec": f[OFF_REC // 8]}


def type_structs(mem):
    """Every candidate object definition: (holder - 0xa0) whose u64(+0xa0) is a valid head."""
    out = {}
    for a, b, raw in mem.blobs:
        w = np.frombuffer(raw[: len(raw) // 8 * 8], "<u8")
        for i in np.nonzero(w > 0x10000)[0]:
            head = int(w[i])
            if head % 8:
                continue
            if mem.region_of(head, NODE) is None:
                continue
            nd = mem.node(head)
            if nd and nd["prev"] == 0:
                out[a + int(i) * 8 - HEAD_OFF] = head
    return out


def chain(mem, head, limit=128):
    out, seen, cur = [], set(), head
    while cur and cur not in seen and len(out) < limit:
        nd = mem.node(cur)
        if nd is None:
            break
        out.append(nd)
        seen.add(cur)
        nxt = nd["next"]
        if not nxt or nxt % 8 or mem.region_of(nxt, NODE) is None:
            break
        fw = mem.node(nxt)
        if fw is None or fw["prev"] != cur:
            break
        cur = nxt
    return out


def snapshot(pid, instances):
    """{addr: 0x200 bytes} for the records plus the node headers, in one batch."""
    reqs = [(inst["rec"], 0x200, f"/tmp/b2r_{k}.bin") for k, inst in enumerate(instances)]
    reqs += [(inst["node"], NODE, f"/tmp/b2n_{k}.bin") for k, inst in enumerate(instances)]
    blobs = n.memory_many(pid, reqs, timeout=60)
    out = {}
    for inst, r_blob, n_blob in zip(instances, blobs[:len(instances)], blobs[len(instances):]):
        if r_blob:
            out[inst["rec"]] = r_blob
        if n_blob:
            out[inst["node"]] = n_blob
    return out


def forfeit_to_ready(i, tries=2):
    """End the round and continue to READY. READY only exists between rounds, so reaching it is
    the unambiguous proof that the boundary happened (in_match stays True on the winner screen,
    which is why checking it was wrong)."""
    for _ in range(tries):
        n._focus(i)
        n.key(i, "Escape", hold=0.12)
        time.sleep(1.6)
        for _ in range(2):             # the pause menu swallows one of the two Downs
            n.key(i, "Down", hold=0.12)
            time.sleep(0.65)
        n.key(i, "Return", hold=0.12)
        time.sleep(1.3)
        n.key(i, "Right", hold=0.12)   # the dialog cursor starts on NO
        n.key(i, "Return", hold=0.12)
        time.sleep(2.6)                # winner screen
        n.key(i, "Return", hold=0.12)  # continue
        time.sleep(3.0)
        if s.on_ready_screen(i):
            return True
        n.key(i, "Return", hold=0.12)  # sometimes the winner screen needs one more
        time.sleep(2.0)
        if s.on_ready_screen(i):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=4,
                    help="snapshots per phase; a phase field must be CONSTANT across them")
    a = ap.parse_args()
    i = a.instance
    pid = n._game_pid(i)
    assert pid, "no game process"
    assert n.ping(pid), "spy not answering"
    # a live, drivable match: a verified player pair, not the weak in_match heuristic
    assert s.find_players_by_input(i, hold=0.4, min_move=8), "needs a live, drivable match"

    print("1) enumerate live instances (type structs -> head -> chain)")
    mem = Mem(pid)
    types = type_structs(mem)
    print(f"   {len(types)} candidate object definitions over {sum(len(r) for *_, r in mem.blobs) / 2**30:.2f} GB")
    instances, seen = [], set()
    for typ, head in types.items():
        ch = chain(mem, head)
        if not ch:
            continue
        for nd in ch:
            if nd["rec"] in seen or not (0x10000 < nd["type"] < 0x100000000):
                continue
            seen.add(nd["rec"])
            instances.append({"rec": nd["rec"], "node": nd["addr"], "id": nd["id"], "type": typ})
    print(f"   {len(instances)} live instances (records + node headers = "
          f"{len(instances) * (0x200 + NODE) / 1024:.0f} KB)")

    print(f"2) snapshot the live phase ({a.repeats}x, 0.4 s apart)")
    live = [snapshot(pid, instances) for _ in range(a.repeats)]
    for _ in range(a.repeats):
        time.sleep(0.4)
        live.append(snapshot(pid, instances))
    print("3) forfeit -> READY (READY only exists between rounds)")
    ended = forfeit_to_ready(i)
    print(f"   reached READY: {ended}")
    assert ended, "could not leave the round (pause menu/forfeit recipe drifted)"
    print(f"4) snapshot the READY phase ({a.repeats}x)")
    ready = []
    for _ in range(a.repeats):
        ready.append(snapshot(pid, instances))
        time.sleep(0.4)

    print("5) diff: constant within a phase, different between phases")
    cands = []
    for addr, b0 in live[0].items():
        series_l = [b0] + [snap.get(addr) for snap in live[1:]]
        series_r = [snap.get(addr) for snap in ready]
        if any(x is None or len(x) != len(b0) for x in series_l + series_r):
            continue
        arr = [np.frombuffer(x[: len(x) // 4 * 4], "<u4") for x in series_l + series_r]
        stable = np.ones(len(arr[0]), bool)
        for x in arr[1:]:
            stable &= (x == arr[0])
        if not stable.any():
            continue
        w0 = arr[0]
        for k in np.nonzero(stable)[0]:
            vals = {int(x[k]) for x in arr}
            if len(vals) < 2:                     # constant across BOTH phases: not the phase
                continue
            cands.append({"addr": addr + int(k) * 4,
                          "region": "rec" if len(b0) == 0x200 else "node",
                          "offset": int(k) * 4, "before": int(w0[k]),
                          "after": int(arr[-1][k]),
                          "phase_vals": [sorted({int(x[k]) for x in series_l}),
                                         sorted({int(x[k]) for x in series_r})]})
    # what object does each hit belong to?
    owner = {}
    for inst in instances:
        for base, span in ((inst["rec"], 0x200), (inst["node"], NODE)):
            owner[base] = (inst["type"], inst["id"], span)
    for c in cands:
        base = c["addr"] - c["offset"]
        t = owner.get(base)
        c["object"], c["instance_id"] = (t[0], t[1]) if t else (None, None)

    print(f"   {len(cands)} slots constant within each phase and different between them")
    by_obj = {}
    for c in cands:
        by_obj.setdefault(hex(c["object"] or 0), []).append(c)
    for obj, lst in sorted(by_obj.items(), key=lambda kv: -len(kv[1]))[:10]:
        kinds = sorted({f'{c["region"]}+{c["offset"]:#04x}' for c in lst})
        print(f"     object {obj}: {len(lst):4d} slots   {kinds[:6]}")
    print("\n   small values only (likely flags/enums, not pointers/positions):")
    small = [c for c in cands if c["before"] < 0x10000 and c["after"] < 0x10000]
    for c in small[:20]:
        print(f"     {c['addr']:#x} {c['region']}+{c['offset']:#04x} "
              f"{c['before']} -> {c['after']}   object {c['object'] and hex(c['object'])}")

    out = Path("results/b2.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"instances": len(instances), "changed": len(cands),
                               "small": len(small), "candidates": cands[:2000]}, indent=1))
    print(f"\nwrote {out}")
    for f in list(Path("/tmp").glob("b2_*.bin")) + list(Path("/tmp").glob("b2r_*.bin")) \
            + list(Path("/tmp").glob("b2n_*.bin")):
        f.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
