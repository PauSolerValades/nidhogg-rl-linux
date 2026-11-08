#!/usr/bin/env python3
"""Record a human play session: state at ~20 Hz, screenshots at 2 Hz, heap snapshots periodically.

  python3 scripts/record.py <instance> [--heap-every 10] [--seconds 1800]

Everything lands in ~/nidhogg-record/<timestamp>/:
  states.csv     t_ms, tick, P1 x,y, P2 x,y, sword1 x,y, sword2 x,y, anim, facing
  shots/         window PNGs, numbered by t_ms
  heaps/         full dumps of the 112 MB instance region (for offline diffing)
The point: a human produces the events we cannot script (kills, throws, zone advances, round
ends), and we mine them afterwards with zero vision in the measurement path.
"""
import csv
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import nidstate as ns          # noqa: E402
import qprobe as q             # noqa: E402

i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
heap_every = float(sys.argv[sys.argv.index("--heap-every") + 1]) if "--heap-every" in sys.argv else 10.0
seconds = float(sys.argv[sys.argv.index("--seconds") + 1]) if "--seconds" in sys.argv else 1800.0

out = Path.home() / "nidhogg-record" / time.strftime("%Y%m%d-%H%M%S")
(out / "shots").mkdir(parents=True, exist_ok=True)
(out / "heaps").mkdir(parents=True, exist_ok=True)
print(f"recording into {out}")

pid = ns.pid_of(i)
# IMPORTANT: identification presses d/a/Right/Left. If a human is playing, those presses move
# their fighter and their own presses break the "stopped after release" test, so identification
# can never succeed while keys are being pressed. Therefore: wait for a *quiet* stretch (the
# fighter is not moving on its own) and only then probe, with long gaps between attempts.
# --p1/--p2 <hex>: skip identification and record these addresses (use when they are already
# proven for this process — identification itself presses keys, which a human will feel).
_argp1 = sys.argv[sys.argv.index("--p1") + 1] if "--p1" in sys.argv else None
_argp2 = sys.argv[sys.argv.index("--p2") + 1] if "--p2" in sys.argv else None

if _argp1 and _argp2:
    # Addresses already proven for this process: skip identification entirely. Identification
    # itself presses d/a/Right/Left, which a human player feels as "someone is moving my
    # character" — so by default we never do it while someone is playing.
    p1, p2 = int(_argp1, 16), int(_argp2, 16)
    print(f"using given addresses: P1 {p1:#x}  P2 {p2:#x} (no probing)")
    ident = {"p1": [(p1,)], "p2": [(p2,)]}
else:
    print("identifying players — this presses keys; do not play for ~25 s")
    ident = None
    t_end = time.time() + 1800
    while time.time() < t_end and ident is None:
        try:
            ident = q.identify(i, verbose=False)
        except Exception as e:
            print("  probe error:", e)
            ident = None
        if ident and ident.get("p1") and ident.get("p2"):
            break
        ident = None
        time.sleep(8)

if not ident:
    sys.exit("could not identify players — start a match first")
p1 = ident["p1"][0][0]
p2 = ident["p2"][0][0]
print(f"P1 {p1:#x}  P2 {p2:#x}")

XO, YO = q.XO, q.YO
ANIM, FACE = 0xBC, 0xD8


def f(addr):
    return ns.read_f(pid, addr)


def _find_tick():
    """A counter that runs at ~60 Hz: scan once, then reuse its address for the session."""
    import struct

    import numpy as np
    pid0 = ns.pid_of(i)
    a, b = ns.biggest_heap(pid0)
    raw = ns.n.memory(pid0, a, b - a, "/tmp/rec_t1.bin")
    if raw is None:
        return 0
    v0 = np.frombuffer(raw[: len(raw) // 4 * 4], "<u4").copy()
    time.sleep(1.0)
    raw = ns.n.memory(pid0, a, b - a, "/tmp/rec_t2.bin")
    if raw is None:
        return 0
    v1 = np.frombuffer(raw[: len(v0) * 4], "<u4")
    d = v1.astype(np.int64) - v0.astype(np.int64)
    cand = np.nonzero((d > 48) & (d < 72))[0]
    return a + int(cand[0]) * 4 if len(cand) else 0


def tick(pid0=None):
    import struct
    global TICK
    if TICK is None:
        TICK = _find_tick()
        print(f"tick field {TICK:#x}" if TICK else "tick field not found (recording without it)")
    if not TICK:
        return 0
    raw = ns.n.memory(ns.pid_of(i), TICK, 4, "/tmp/rec_t3.bin")
    return struct.unpack("<I", raw)[0] if raw else 0


TICK = None
csv_path = out / "states.csv"
with open(csv_path, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["t_ms", "tick", "p1x", "p1y", "p2x", "p2y",
                "sw1x", "sw1y", "sw2x", "sw2y", "anim", "facing"])
    t0 = time.time()
    last_heap = last_shot = 0.0
    while time.time() - t0 < seconds:
        now = time.time() - t0
        t = tick()
        # ONE spy round trip for both bodies: 12 individual reads cost 12 x 50 ms of poll
        # latency (measured: the recorder managed 0.8 Hz), a 0x600-byte block per body costs one.
        import struct
        blobs = ns.n.memory_many(pid, [(p1, 0x600, "/tmp/rec_b1.bin"),
                                       (p2, 0x600, "/tmp/rec_b2.bin")])
        def g(blob, off):
            if not blob or off + 4 > len(blob):
                return 0.0
            return struct.unpack("<f", blob[off:off + 4])[0]
        b1, b2 = (blobs + [None, None])[:2]
        w.writerow([f"{now:.3f}", t,
                    g(b1, XO), g(b1, YO), g(b2, XO), g(b2, YO),
                    g(b1, 0x400 + XO), g(b1, 0x400 + YO),
                    g(b2, 0x400 + XO), g(b2, 0x400 + YO),
                    g(b1, ANIM), g(b1, FACE)])
        fh.flush()
        if now - last_shot > 0.5:
            last_shot = now
            ns.grab(i, str(out / "shots" / f"{int(now*1000):08d}.png"))
        if now - last_heap > heap_every:
            last_heap = now
            a, b = ns.biggest_heap(pid)
            ns.n.memory(pid, a, b - a, str(out / "heaps" / f"{int(now*1000):08d}.bin"))
        time.sleep(0.05)
print(f"done: {csv_path}")
