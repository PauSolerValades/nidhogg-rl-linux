#!/usr/bin/env python3
"""Record a human session with nothing that can fail: screenshots + full memory dumps.

No identity, no CSV, no key presses. This exists because every identification attempt during a
live match is a way to lose a session: record_human.py needs a fixed camera to bind records to
sprites, and identity reallocates every round. For finding a memory field none of that is
needed — the dumps hold all of memory and the shots hold the tally, so the analysis can work out
which round ended when, and what changed.

    python3 scripts/record_core.py <instance> [--heap-every 15] [--seconds 3600]

Layout (~/nidhogg-record/<stamp>/):
  shots/   2 Hz screenshots
  heaps/   every rw region >= 1 MB, every --heap-every seconds, + regions.json
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--heap-every", type=float, default=15.0)
    ap.add_argument("--seconds", type=float, default=3600.0)
    a = ap.parse_args()
    i = a.instance
    pid = n._game_pid(i)
    assert pid, "no game process"
    assert n.ping(pid), f"spy not answering in {pid}"

    out = Path.home() / "nidhogg-record" / time.strftime("%Y%m%d-%H%M%S")
    (out / "shots").mkdir(parents=True, exist_ok=True)
    (out / "heaps").mkdir(parents=True, exist_ok=True)
    regions = [(x, y) for x, y in s.regions(pid, min_size=1 << 20)]
    (out / "regions.json").write_text(json.dumps(
        [{"base": hex(x), "size": y - x} for x, y in regions], indent=1))
    print(f"recording into {out}", flush=True)
    print(f"{len(regions)} regions, {sum(y - x for x, y in regions) / 2**30:.2f} GB per dump",
          flush=True)

    stop = [False]

    def shots():
        k = 0
        while not stop[0]:
            t = time.time() - t0
            try:
                n.grab(i, str(out / "shots" / f"{int(t * 1000):08d}.png"))
                k += 1
            except Exception as e:
                print(f"  shot failed: {e!r}", flush=True)
            time.sleep(0.45)

    t0 = time.time()
    th = threading.Thread(target=shots, daemon=True)
    th.start()

    last_heap = last_beat = 0.0
    heaps = 0
    while time.time() - t0 < a.seconds:
        now = time.time() - t0
        if now - last_heap > a.heap_every:
            last_heap = now
            path = out / "heaps" / f"{int(now * 1000):08d}.bin"
            with open(path, "wb") as hf:
                for x, y in regions:
                    hf.write(n.memory(pid, x, y - x, "/tmp/rc_h.bin") or b"")
            if path.stat().st_size:
                heaps += 1
            else:
                print("  heap dump failed (0 bytes)", flush=True)
                path.unlink(missing_ok=True)
        if now - last_beat > 10:
            last_beat = now
            d = sum(f.stat().st_size for f in (out / "heaps").glob("*.bin"))
            k = len(list((out / "shots").glob("*.png")))
            print(f"  t={now:6.1f}s shots={k:5d} heaps={heaps:3d} ({d / 2**30:5.1f} GB)",
                  flush=True)
        time.sleep(0.1)
    stop[0] = True
    print(f"done: {out}  ({heaps} heaps)", flush=True)


if __name__ == "__main__":
    main()
