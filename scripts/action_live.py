#!/usr/bin/env python3
"""Live check of the spy's own input path (XTEST from inside the game process).

    python3 scripts/action_live.py 0

Compares the two ways of sending one key -- an `xdotool` fork+exec (~16 ms) and the spy's
in-process XTEST (~0.2 ms) -- then proves the spy's press is CAUSAL: of every candidate
fighter pair, exactly one member of one group must move on a spy-sent `d` and the other
must stay put. The pair is chosen by that test, not by offset or address order, because
records reallocate between rounds (docs/MEMORY.md).

Run it in a live, drivable match (nidstate.enter_match_v2), not on the GO screen.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402


def bench(fn, k=50):
    xs = []
    for _ in range(k):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000)
    xs.sort()
    return xs[k // 2], xs[int(k * 0.98)]


def find_pair_by_input(pid, hold=200, tries=2):
    """The pair the spy's own key press moves. Roles are re-proved here, never remembered."""
    for _ in range(tries):
        groups = {}
        for a, _x, _y, t in s.find_fighters(pid):
            groups.setdefault(t, []).append(a)
        for t, addrs in groups.items():
            if len(addrs) != 2:
                continue
            a1, a2 = addrs
            b1, b2 = s.read_x(pid, a1), s.read_x(pid, a2)
            n.spy_key(pid, "d", hold)
            time.sleep(0.3)
            n1, n2 = s.read_x(pid, a1), s.read_x(pid, a2)
            moved = [abs(n1 - b1) > 10, abs(n2 - b2) > 10]
            still = [abs(n1 - b1) <= 2, abs(n2 - b2) <= 2]
            if moved == [True, False] and still == [False, True]:
                return a1, a2, t, (b1, n1, b2, n2)
            if moved == [False, True] and still == [True, False]:
                return a2, a1, t, (b2, n2, b1, n1)
        time.sleep(0.5)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    a = ap.parse_args()
    ind = a.instance
    pid = n._game_pid(ind)
    assert pid, "no game process"
    assert n.ping(pid), "spy not answering"

    p50_xt, p99_xt = bench(lambda: subprocess.run(["xdotool", "keydown", "a"],
                                                 env=n._env(ind), capture_output=True))
    p50_spy, p99_spy = bench(lambda: n.spy_key(pid, "a", ms=20))
    print(f"xdotool keydown (fork+exec):   p50 {p50_xt:6.2f} ms  p99 {p99_xt:6.2f} ms")
    print(f"spy XTEST press (in-process):  p50 {p50_spy:6.3f} ms  p99 {p99_spy:6.3f} ms"
          f"   {p50_xt / max(p50_spy, 1e-6):.0f}x")
    assert p50_spy < 2.0, "spy input is not in-process"

    n._focus(ind)
    found = find_pair_by_input(pid)
    assert found, ("no pair moved on a spy-sent 'd' -- wrong screen (GO / menu / round over), "
                   "or the round ended mid-scan")
    p1, p2, t, (b1, n1, b2, n2) = found
    print(f"causal pair type {t:#x}: P1 {p1:#x} x {b1:.0f}->{n1:.0f}, "
          f"P2 {p2:#x} x {b2:.0f}->{n2:.0f}")

    n.track(pid, p1=p1, p2=p2, tick=s.find_tick(pid) or 0)
    # `track` is async and the game keeps moving, so a single agreement check can pass on a
    # pair that is stale by the time we press. Check against a direct read BEFORE and AFTER:
    # if the round turned over mid-test, that fails here instead of passing on garbage.
    def agrees(st):
        return (st and st.flags & n.FLAG_P1 and st.flags & n.FLAG_P2
                and abs(st.p1_x - s.read_x(pid, p1)) < 3
                and abs(st.p2_x - s.read_x(pid, p2)) < 3)

    st = None
    for _ in range(40):
        st = n.wait_state(pid, 0, 0.3)
        if agrees(st):
            break
    assert agrees(st), "state file is not tracking the pair we just validated"

    a0 = st
    n.spy_key(pid, "d", 300)
    time.sleep(0.4)
    a1 = n.state(pid)
    print(f"state file  : p1.x {a0.p1_x:7.1f} -> {a1.p1_x:7.1f}, "
          f"p2.x {a0.p2_x:7.1f} -> {a1.p2_x:7.1f}")
    assert agrees(a1), "addresses went stale during the test (round transition?) -- re-run"
    assert a1.p1_x - a0.p1_x > 5, "P1 did not move on a spy-sent 'd'"
    assert abs(a1.p2_x - a0.p2_x) <= 3, "both fighters moved: press was not causal"
    n.untrack(pid)
    print("PASS — in-process input is causal, ~2 orders of magnitude cheaper than xdotool")


if __name__ == "__main__":
    main()
