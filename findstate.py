#!/usr/bin/env python3
"""Find the fighter position by input-correlated motion.

Enter-only menu path (6 Enters from a cold start) lands in the LOCAL 2-player match.
The round never starts there -- but both fighters are drivable by us, which is all we
need: hold 'd' and keep the float32 slots that move right at fighter speed (~12 px/s).

Positions are float32 in this build; a float64 sweep of the heap finds only counters.

  python3 findstate.py [instance]
"""
import importlib.util
import struct
import sys
import time
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("n", Path(__file__).with_name("nidlinux.py"))
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)

HEAP = (0x16a0000, 0x8200000)      # anon rw region holding the game heap
SAMPLES = 12
GAP = 0.25
WARMUP = 15.0                      # the runner eats keys before ~frame 690


def cmd_path(pid):
    return Path(f"/tmp/nid_cmd_{pid}")


def dump(pid, addr, size, path="/tmp/nid_scan.bin"):
    out = Path(path)
    out.unlink(missing_ok=True)
    cmd = cmd_path(pid)
    cmd.write_text(f"dump {addr:x} {size:x} {path}\n")
    t0 = time.time()
    while cmd.exists() and time.time() - t0 < 20:
        time.sleep(0.02)
    return np.fromfile(path, dtype="<f4") if out.exists() else None


def poke_f32(pid, addr, value):
    cmd_path(pid).write_text(f"poke {addr:x} {struct.pack('<f', value).hex()}\n")
    time.sleep(0.2)


def sample(pid):
    """Dump the heap SAMPLES times (caller holds the key)."""
    rows = []
    for _ in range(SAMPLES):
        a = dump(pid, HEAP[0], HEAP[1] - HEAP[0])
        if a is None:
            return None
        rows.append(a)
        time.sleep(GAP)
    m = min(len(r) for r in rows)
    return np.stack([r[:m] for r in rows])


def enter_local_match(i):
    time.sleep(WARMUP)
    for k in range(8):
        n.key(i, "Return")
        time.sleep(1.5)
    return n.grab(i, "/tmp/nid_ready.png")


def moving_slots(A, lo, hi, min_total, max_step):
    with np.errstate(invalid="ignore", over="ignore"):
        ok = np.isfinite(A).all(0)
        d = np.diff(A, axis=0)
        step = np.abs(d)
        total = A[-1] - A[0]
        good = (
            ok
            & (np.abs(A) < 1200).all(0)
            & (step < max_step).all(0)          # never teleports
            & (total > lo)
            & (total < hi)
            & ((np.sign(d) == np.sign(total)).mean(0) > 0.8)   # monotone-ish
        )
        return np.nonzero(good)[0]


def main():
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pid = n._game_pid(i)
    if not pid:
        sys.exit("game not running")

    if "--skip" in sys.argv:
        print("skipping entry")
    else:
        print("entering local match (6 Enters)…")
        enter_local_match(i)

    print(f"holding 'd' and sampling {SAMPLES}×{GAP}s…")
    key(i, "d", hold=True)
    A = sample(pid)
    n.key(i, "d")          # release via keyup
    time.sleep(0.5)
    right = moving_slots(A, 20, 80, 3, 8)
    print(f"{len(right)} slots moved right at fighter speed")
    for k in right[:20]:
        print(f"  {HEAP[0] + k*4:#x}  {[round(float(v),1) for v in A[::3, k]]}")

    print("holding 'a' — the same slots must move left…")
    n.key(i, "a", hold=True)
    B = sample(pid)
    n.key(i, "a")
    left = set(moving_slots(B, -80, -20, 3, 8).tolist())
    confirmed = [k for k in right if k in left]
    print(f"{len(confirmed)} confirmed (right while 'd', left while 'a'):")
    for k in confirmed:
        print(f"  {HEAP[0] + k*4:#x}  now {float(B[-1, k]):8.2f}")
    Path("/tmp/nid_x_candidates.txt").write_text(
        "\n".join(f"{HEAP[0] + k*4:#x}" for k in confirmed))


def key(i, keysym, hold=False):
    """keydown/keyup without release, for 'hold this direction' sampling."""
    import os
    import subprocess
    env = dict(os.environ, DISPLAY=n._pids()[str(i)]["display"])
    w = n.window(i)
    if w:
        subprocess.run(["xdotool", "windowfocus", w], env=env, capture_output=True)
    subprocess.run(["xdotool", "keydown" if hold else "keyup", keysym], env=env,
                   capture_output=True)


if __name__ == "__main__":
    main()
