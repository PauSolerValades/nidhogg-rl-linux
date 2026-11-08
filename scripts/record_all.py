#!/usr/bin/env python3
"""Overnight recorder: dump EVERY rw region >=1 MB (plus [heap]) every --heap-every seconds.

Copy of scripts/record.py with the region chooser replaced (ns.regions, no
"contains-object-record" filter) and memory_many so ~120 regions cost one spy round trip.

  python3 record_all.py <instance> [--heap-every 6] [--seconds 1200] [--p1 HEX --p2 HEX]
"""
import csv
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/psoler/nidhogg-rl-on")
sys.path.insert(0, str(REPO))
import nidstate as ns          # noqa: E402

i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
heap_every = float(sys.argv[sys.argv.index("--heap-every") + 1]) if "--heap-every" in sys.argv else 6.0
seconds = float(sys.argv[sys.argv.index("--seconds") + 1]) if "--seconds" in sys.argv else 1800.0
out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else (
    Path.home() / "nidhogg-record" / time.strftime("%Y%m%d-%H%M%S"))
(out / "shots").mkdir(parents=True, exist_ok=True)
(out / "heaps").mkdir(parents=True, exist_ok=True)

pid = ns.pid_of(i)
p1 = int(sys.argv[sys.argv.index("--p1") + 1], 16) if "--p1" in sys.argv else None
p2 = int(sys.argv[sys.argv.index("--p2") + 1], 16) if "--p2" in sys.argv else None
print(f"recording into {out}  pid={pid} p1={p1 and hex(p1)} p2={p2 and hex(p2)}", flush=True)

XO, YO = 0xEC, 0xF0
REGIONS = []


def state_row():
    import struct
    if not p1 or not p2:
        return ["", "", "", "", "", "", "", "", ""]
    blobs = ns.n.memory_many(pid, [(p1, 0x120, "/tmp/ra_b1.bin"),
                                   (p2, 0x120, "/tmp/ra_b2.bin")])
    def x(blob, off):
        return struct.unpack("<f", blob[off:off + 4])[0] if blob else 0.0
    b1, b2 = (blobs + [None, None])[:2]
    return [x(b1, XO), x(b1, YO), x(b2, XO), x(b2, YO),
            x(b1, 0x400 + XO), x(b1, 0x400 + YO), x(b2, 0x400 + XO), x(b2, 0x400 + YO),
            x(b1, 0xBC)]


csv_path = out / "states.csv"
with open(csv_path, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["t_ms", "p1x", "p1y", "p2x", "p2y", "sw1x", "sw1y", "sw2x", "sw2y", "anim"])
    t0 = time.time()
    print(f"t0_wall={t0:.3f}", flush=True)
    last_heap = last_shot = 0.0
    while time.time() - t0 < seconds:
        now = time.time() - t0
        w.writerow([f"{now:.3f}"] + state_row())
        fh.flush()
        if now - last_shot > 0.5:
            last_shot = now
            ns.grab(i, str(out / "shots" / f"{int(now*1000):08d}.png"))
        if now - last_heap >= heap_every:
            last_heap = now
            if not REGIONS:
                REGIONS.extend(ns.regions(pid))
                print(f"dumping {len(REGIONS)} region(s), "
                      f"{sum(b-a for a,b in REGIONS)/1e6:.0f} MB total", flush=True)
                (out / "regions.json").write_text(json.dumps(
                    [{"base": hex(a), "size": b - a} for a, b in REGIONS], indent=1))
            t1 = time.time()
            reqs = [(a, b - a, f"/tmp/ra_h{k}.bin") for k, (a, b) in enumerate(REGIONS)]
            blobs = ns.n.memory_many(pid, reqs, timeout=30.0)
            path = out / "heaps" / f"{int(now*1000):08d}.bin"
            missing = []
            with open(path, "wb") as hf:
                for k, ((a, b), blob) in enumerate(zip(REGIONS, blobs)):
                    if blob is None or len(blob) != b - a:
                        missing.append(k)
                        blob = b"\0" * (b - a)   # pad: keep every dump's offsets identical
                    hf.write(blob)
            with open(out / "layout.jsonl", "a") as lf:
                lf.write(json.dumps({"t_ms": int(now*1000), "missing": missing}) + "\n")
            print(f"dump {now:6.1f}s {path.stat().st_size/1e6:.0f} MB "
                  f"(read {time.time()-t1:.2f}s)", flush=True)
        time.sleep(0.05)
print(f"done: {csv_path}", flush=True)
