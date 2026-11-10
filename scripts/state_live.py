#!/usr/bin/env python3
"""Live check of the pushed 60 Hz state file.

    python3 scripts/state_live.py 0        # instance id (or --pid)

Finds the two fighter records structurally (no key presses), hands them plus the game's
tick counter to the spy, then reads /tmp/nid_state_<pid> and checks the property that
matters: one published sample per game tick, with sane values.

Exit 1 if the sample stream is not tick-aligned or the fields look wrong.
"""
import argparse
import collections
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--pid", type=int)
    ap.add_argument("--samples", type=int, default=60)
    a = ap.parse_args()

    pid = a.pid or n._game_pid(a.instance)
    assert pid, "no game process"
    assert n.ping(pid), f"spy not answering in {pid}"

    recs = s.find_fighters(pid)
    assert len(recs) >= 2, f"only {len(recs)} fighter records found"
    (p1, p2) = recs[0][0], recs[1][0]
    tick = s.find_tick(pid)
    print(f"pid {pid}  p1 {p1:#x} (x={recs[0][1]:.1f} y={recs[0][2]:.1f})"
          f"  p2 {p2:#x} (x={recs[1][1]:.1f} y={recs[1][2]:.1f})  tick {tick and hex(tick)}")

    n.untrack(pid)
    n.track(pid, p1=p1, p2=p2, tick=tick or 0)
    first = None
    t0 = time.time()
    while time.time() - t0 < 3.0:            # skip a sample caught mid-reconfigure
        st = n.wait_state(pid, first.seq if first else 0)
        first = st
        if st and st.flags & n.FLAG_P1 and st.flags & n.FLAG_P2:
            break
    assert first and first.flags & n.FLAG_P1 and first.flags & n.FLAG_P2, \
        f"nothing usable published after track (flags {first and first.flags:#x})"
    print(f"flags {first.flags:#x} (p1={bool(first.flags & n.FLAG_P1)}"
          f" p2={bool(first.flags & n.FLAG_P2)} tick={bool(first.flags & n.FLAG_TICK)})")

    samples, deltas, gaps = [], [], []
    t0 = time.time()
    prev = None
    while len(samples) < a.samples and time.time() - t0 < 10.0:
        st = n.wait_state(pid, prev.seq if prev else 0)
        assert st, "sample stream stopped"
        if prev is not None:
            deltas.append(st.tick - prev.tick)
            gaps.append(st.t_ns - prev.t_ns)
        samples.append(st)
        prev = st

    wall = samples[-1].t - samples[0].t
    print(f"{len(samples)} samples in {wall:.2f}s = {len(samples) / wall:.1f}/s"
          f"   tick deltas {dict(sorted(collections.Counter(deltas).items()))}")
    gaps.sort()
    print(f"publish interval: p50 {gaps[len(gaps) // 2] / 1e6:.2f} ms"
          f"  max {gaps[-1] / 1e6:.2f} ms")
    print(f"last: p1=({prev.p1_x:.2f},{prev.p1_y:.2f}) facing={prev.p1_facing:+.0f}"
          f" anim={prev.p1_anim}  p2=({prev.p2_x:.2f},{prev.p2_y:.2f}) anim={prev.p2_anim}")

    bad = [d for d in deltas if d != 1]
    assert not bad, f"not one sample per tick: deltas {bad[:10]}"
    assert prev.flags & n.FLAG_P1 and prev.flags & n.FLAG_P2, "fighters not sampled"
    assert prev.p1_y > 0 and prev.p2_y > 0, "y looks empty"
    assert abs(prev.p1_facing) == 1.0, f"facing {prev.p1_facing}"
    print("PASS — one sample per tick, fields sane")
    n.untrack(pid)


if __name__ == "__main__":
    main()
