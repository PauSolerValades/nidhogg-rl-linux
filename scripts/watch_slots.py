#!/usr/bin/env python3
"""Log a fixed set of u32 addresses at ~2 Hz while a human plays.

Zero interference: one batched spy round trip per sample, no screenshots, no key presses, no
focus changes. Used to see exactly which candidate moves at a round boundary.

    python3 scripts/watch_slots.py candidates.json --interval 0.5 --seconds 900 --out /tmp/slots.csv
"""
import argparse
import csv
import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--seconds", type=float, default=900.0)
    ap.add_argument("--out", default="/tmp/slots.csv")
    a = ap.parse_args()
    cands = [int(x["addr"], 16) for x in json.load(open(a.candidates))["candidates"]]
    pid = n._game_pid(a.instance)
    assert pid and n.ping(pid), "no game / no spy"
    print(f"watching {len(cands)} slots at {1/a.interval:.1f} Hz -> {a.out}", flush=True)
    t0 = time.time()
    with open(a.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t"] + [hex(c) for c in cands])
        while time.time() - t0 < a.seconds:
            reqs = [(c, 4, f"/tmp/ws_{k}.bin") for k, c in enumerate(cands)]
            vals = []
            for k, raw in enumerate(n.memory_many(pid, reqs, timeout=20)):
                vals.append(int.from_bytes(raw, "little") if raw else -1)
            w.writerow([round(time.time() - t0, 2)] + vals)
            if int(time.time() - t0) % 20 == 0:
                fh.flush()
                print(f"  t={time.time()-t0:5.1f}s samples logged", flush=True)
            time.sleep(a.interval)
    print("done", flush=True)


if __name__ == "__main__":
    main()
