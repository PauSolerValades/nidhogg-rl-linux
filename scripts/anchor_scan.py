#!/usr/bin/env python3
"""Find the anchor: the global that points at the head of an instance list.

The engine keeps instances in doubly-linked lists of 0x80-byte nodes (type@+0x18, prev@+0x30,
next@+0x38, id@+0x40, record@+0x48). Node memory is recycled every round, so a node address is
never an identity — only the *walk from a head* is.

Nothing here is hardcoded: region bases differ between processes and prefixes, which is exactly
why an earlier version of this script found zero heads. The chain is discovered from the records
outwards:

    records (proven x@+0xEC) -> qwords equal to a record address -> those are node+0x48
    -> the node's prev/next must form a consistent chain -> walk prev to the head (prev == 0)
    -> qwords equal to the head address -> those are the candidate ANCHOR globals

Everything is done on local copies of the dumps, so no remote read can fault the game.

    python3 scripts/anchor_scan.py 0
    python3 scripts/anchor_scan.py --pid 1234
"""
import argparse
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402

NODE = 0x80
OFF_TYPE, OFF_PREV, OFF_NEXT, OFF_ID, OFF_REC = 0x18, 0x30, 0x38, 0x40, 0x48
REC_X, REC_Y, REC_ANIM, REC_FACING, REC_TYPE = 0xEC, 0xF0, 0xBC, 0xD8, 0x88


class Mem:
    """Local copy of every rw region: all lookups are answered from RAM, never from the game."""

    def __init__(self, pid):
        self.blobs = []
        ranges, reqs = [], []
        for i, (a, b) in enumerate(s.regions(pid, min_size=1 << 20)):
            ranges.append((a, b))
            reqs.append((a, b - a, f"/tmp/anchor_{i}.bin"))
        raws = n.memory_many(pid, reqs, timeout=120)
        for (a, b), raw in zip(ranges, raws):
            if raw:
                self.blobs.append((a, b, raw))
        self.by_base = {(a, b): raw for a, b, raw in self.blobs}

    def region_of(self, addr, size=8):
        for a, b, raw in self.blobs:
            if a <= addr and addr + size <= b:
                return a, b, raw
        return None

    def q(self, addr):
        r = self.region_of(addr, 8)
        return struct.unpack_from("<Q", r[2], addr - r[0])[0] if r else None

    def node(self, addr):
        r = self.region_of(addr, NODE)
        if r is None:
            return None
        f = struct.unpack_from("<16Q", r[2], addr - r[0])
        return {"addr": addr, "type": f[OFF_TYPE // 8], "prev": f[OFF_PREV // 8],
                "next": f[OFF_NEXT // 8], "id": f[OFF_ID // 8], "rec": f[OFF_REC // 8]}

    def record_ok(self, rec):
        r = self.region_of(rec + REC_TYPE, 4)
        if r is None:
            return False
        typ = struct.unpack_from("<I", r[2], rec + REC_TYPE - r[0])[0]
        anim = struct.unpack_from("<I", r[2], rec + REC_ANIM - r[0])[0] if self.region_of(rec + REC_ANIM, 4) else 0
        facing, x, y = (struct.unpack_from("<f", r[2], rec + off - r[0])[0]
                        if self.region_of(rec + off, 4) else 0.0
                        for off in (REC_FACING, REC_X, REC_Y))
        return (typ > 0x10000 and 0 < anim < 10000 and facing in (-1.0, 1.0)
                and 0.0 <= x <= 2200.0 and 15.0 <= y <= 300.0)

    def xy(self, rec):
        r = self.region_of(rec + REC_X, 8)
        return struct.unpack_from("<ff", r[2], rec + REC_X - r[0]) if r else (0.0, 0.0)

    def find_qword(self, value):
        """Every location whose 8 bytes equal `value`."""
        hits = []
        want = np.uint64(value)
        for a, b, raw in self.blobs:
            w = np.frombuffer(raw[: len(raw) // 8 * 8], "<u8")
            for i in np.nonzero(w == want)[0]:
                hits.append(a + int(i) * 8)
        return hits


def chain_from(mem, node_addr, limit=64):
    """Walk a consistent chain in both directions; returns (head, nodes) or None."""
    start = mem.node(node_addr)
    if start is None:
        return None
    cur, seen = node_addr, set()
    while True:                                    # back to the head
        nd = mem.node(cur)
        if nd is None or cur in seen or len(seen) > limit:
            return None
        seen.add(cur)
        if nd["prev"] == 0:
            head = cur
            break
        cur = nd["prev"]
    chain, cur = [], head
    while cur and len(chain) < limit:
        nd = mem.node(cur)
        if nd is None:
            break
        chain.append(nd)
        nxt = nd["next"]
        if nxt == 0:
            break
        fw = mem.node(nxt)
        if fw is None or fw["prev"] != cur:
            break
        cur = nxt
    return head, chain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--pid", type=int)
    a = ap.parse_args()
    pid = a.pid or n._game_pid(a.instance)
    assert pid, "no game process"
    assert n.ping(pid), f"spy not answering in {pid}"

    mem = Mem(pid)
    print(f"  {len(mem.blobs)} regions / {sum(len(r) for _, _, r in mem.blobs) / 2**30:.2f} GB in RAM")

    recs = s.find_fighters(pid)
    records = [r[0] for r in recs]
    print(f"  {len(records)} candidate records from find_fighters")
    nodes = {}
    for rec in records:
        for hit in mem.find_qword(rec):
            base = hit - OFF_REC
            if base % 8:
                continue
            nd = mem.node(base)
            if nd and nd["rec"] == rec:
                nodes[base] = rec
    print(f"  {len(nodes)} node bases point at those records")

    anchors = {}
    for base in nodes:
        got = chain_from(mem, base)
        if not got:
            continue
        head, chain = got
        plausible = [nd for nd in chain if mem.record_ok(nd["rec"])]
        if len(plausible) < 2:
            continue
        types = {nd["type"] for nd in plausible}
        anchors.setdefault((head, len(chain), len(plausible), tuple(sorted(types))), chain)

    for (head, ln, npl, types), chain in sorted(anchors.items(), key=lambda kv: -kv[0][2]):
        holders = mem.find_qword(head)
        print(f"\n  head {head:#x}: {ln} nodes, {npl} plausible records, "
              f"types {[hex(t) for t in types]}")
        for nd in chain[:8]:
            print(f"     node {nd['addr']:#x} id={nd['id']:#06x} type={nd['type']:#x} "
                  f"rec={nd['rec']:#x} xy={tuple(round(v, 1) for v in mem.xy(nd['rec']))}")
        for h in holders:
            r = mem.region_of(h)
            fixed = r and not h.to_bytes(8, "little").count(b"\0") and r[0] < 0x2000000
            print(f"     ANCHOR candidate {h:#x}  (region {r[0]:#x})"
                  f"{'   <- fixed-base region' if fixed else ''}")
        if not holders:
            print("     (no global points at this head: it is reached via prev/next only)")

    if not anchors:
        print("\n  NO ANCHOR: no chain with two plausible records")
        return 1
    print(f"\n  {len(anchors)} anchor chain(s) found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
