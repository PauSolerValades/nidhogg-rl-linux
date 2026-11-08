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
    p1, p2 = int(_argp1, 16), int(_argp2, 16)
    print(f"using given addresses: P1 {p1:#x}  P2 {p2:#x}")
    ident = {"p1": [(p1,)], "p2": [(p2,)]}
    print("waiting for a QUIET stretch in a live match — please stand still ~25 s once the round starts")
ident = None
t_end = time.time() + 1800
attempt = 0
while time.time() < t_end and ident is None:
    attempt += 1
    # "quiet" = almost nothing on screen is moving: count records whose x changes in 0.6 s.
    # A human in a live match moves many; an idle round moves few. This is the signal that the
    # probe's d/a presses will not be confused with the player's own input.
    q_ok = False
    try:
        pid0 = ns.pid_of(i)
        a1 = {a: v[0] for a, v in q._all_record_xs(pid0).items()} if hasattr(q, "_all_record_xs") else None
        if a1 is None:
            x1 = {a: v[0] for a, v in ns._all_record_xs(pid0).items()}
        else:
            x1 = a1
        time.sleep(0.6)
        x2 = {a: v[0] for a, v in ns._all_record_xs(pid0).items()}
        movers = sum(1 for a, v in x1.items() if a in x2 and abs(x2[a] - v) > 2.0)
        q_ok = True   # ambient animation also moves records; do not gate on this
        if not q_ok:
            print(f"  ({movers} records moving — you are playing; waiting for still)")
    except Exception as e:
        print(f"  quiet check failed: {e}")
    if q_ok:
        ident = q.identify(i, verbose=False)
        if ident and ident.get("p1") and ident.get("p2"):
            break
        ident = None
    else:
        print(f"  (not quiet — someone is playing; waiting) attempt {attempt}")
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


def tick():
    """A counter that runs at ~60 Hz: search once, then reuse."""
    global TICK
    if TICK is None:
        import numpy as np
        raw = ns.n.memory(pid, *ns.biggest_heap(pid), "/tmp/rec_t.bin")
        a = np.frombuffer(raw[: len(raw) // 4 * 4], "<u4")
        v0 = a.copy()
        time.sleep(1.0)
        raw = ns.n.memory(pid, *ns.biggest_heap(pid), "/tmp/rec_t.bin")
        b = np.frombuffer(raw[: min(len(raw), len(v0) * 4)] // 4 * 4, "<u4")
        d = b[: len(v0)].astype(np.int64) - v0.astype(np.int64)
        cand = np.nonzero((d > 48) & (d < 72))[0]
        TICK = ns.biggest_heap(pid)[0] + int(cand[0]) * 4 if len(cand) else 0
        print(f"tick field {TICK:#x}")
    raw = ns.n.memory(pid, TICK, 4, "/tmp/rec_t2.bin")
    import struct
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
        t = tick() if TICK is None or now % 5 < 0.1 else tick()
        w.writerow([f"{now:.3f}", t,
                    *(f(p1 + XO) or 0, f(p1 + YO) or 0, f(p2 + XO) or 0, f(p2 + YO) or 0),
                    *(f(p1 + 0x400 + XO) or 0, f(p1 + 0x400 + YO) or 0,
                      f(p2 + 0x400 + XO) or 0, f(p2 + 0x400 + YO) or 0),
                    f(p1 + ANIM) or 0, f(p1 + FACE) or 0])
        if now - last_shot > 0.5:
            last_shot = now
            ns.grab(i, str(out / "shots" / f"{int(now*1000):08d}.png"))
        if now - last_heap > heap_every:
            last_heap = now
            a, b = ns.biggest_heap(pid)
            ns.n.memory(pid, a, b - a, str(out / "heaps" / f"{int(now*1000):08d}.bin"))
        time.sleep(0.05)
print(f"done: {csv_path}")
