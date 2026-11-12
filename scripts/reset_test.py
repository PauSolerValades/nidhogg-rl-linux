#!/usr/bin/env python3
"""Can we reset an episode by writing x/y?  (docs/TMP_CURRENT_STATE.md §4, last open item)

The claim to test is narrow and falsifiable:
  * capture both fighters' x/y at the start of a live round (the game's own spawn),
  * move them (walk, so state is genuinely different),
  * write x/y back, and check the write SURVIVES the next frames (no snap-back),
  * the game keeps running (tick advances, anims change) and both fighters stay drivable.

    python3 scripts/reset_test.py 0 [--trials 8]

Writes are the point here, so this is the one script that is not read-only. Integers/floats at
proven offsets only (+0xEC, +0xF0). PASS = 8/8 trials, no crash, control still works.
"""
import argparse
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402

XO, YO, ANIM, FACE = 0xEC, 0xF0, 0xBC, 0xD8


def plausible(pid, rec):
    """The five discriminators. Never write to a record that fails these: find_players_by_input
    picks the largest mover, which in a live match can be a camera or a particle (anim ~1.1e9)."""
    raw = n.memory_many(pid, [(rec + 0x80, 0x80, "/tmp/rt_p.bin")])[0]
    if raw is None or len(raw) < 0x80:
        return False
    typ, anim = struct.unpack_from("<I", raw, 0x88 - 0x80)[0], struct.unpack_from("<I", raw, ANIM - 0x80)[0]
    facing, x, y = (struct.unpack_from("<f", raw, off - 0x80)[0] for off in (FACE, XO, YO))
    return (typ > 0x10000 and 0 < anim < 10000 and facing in (-1.0, 1.0)
            and 0.0 <= x <= 2200.0 and 15.0 <= y <= 300.0)


def players_verified(i, pid, tries=3):
    """Identify STRUCTURALLY (type pairs + the five discriminators), then CAUSALLY (one key).

    find_players_by_input() scans every record and picks the biggest mover — in a live match that
    is often the camera (it returned 48->501 px). Restricting the search to pairs that already
    look like fighters makes the causal step a confirmation instead of a discovery.
    """
    for _ in range(tries):
        groups = {}
        for addr, _x, _y, t in s.find_fighters(pid):
            if plausible(pid, addr):
                groups.setdefault(t, []).append(addr)
        for t, addrs in groups.items():
            if len(addrs) != 2:
                continue
            a, b = addrs
            x0 = {a: s.read_x(pid, a), b: s.read_x(pid, b)}
            n.spy_keydown(pid, "d"); time.sleep(0.30); n.spy_keyup(pid, "d"); time.sleep(0.15)
            x1 = {a: s.read_x(pid, a), b: s.read_x(pid, b)}
            if None in list(x0.values()) + list(x1.values()):
                continue
            moved = [r for r in (a, b) if abs(x1[r] - x0[r]) > 8]
            still = [r for r in (a, b) if abs(x1[r] - x0[r]) <= 2]
            if len(moved) == 1 and len(still) == 1:
                return moved[0], still[0]
        time.sleep(0.5)
    return None


def read_pair(pid, p1, p2):
    blobs = n.memory_many(pid, [(p1, 0x100, "/tmp/rt_a.bin"), (p2, 0x100, "/tmp/rt_b.bin")])
    out = []
    for b in blobs:
        if not b:
            out.append(None)
            continue
        x, y = struct.unpack_from("<f", b, XO)[0], struct.unpack_from("<f", b, YO)[0]
        anim = struct.unpack_from("<I", b, ANIM)[0]
        facing = struct.unpack_from("<f", b, FACE)[0]
        out.append({"x": x, "y": y, "anim": anim, "facing": facing})
    return out


def write_xy(pid, rec, x, y):
    n.poke(pid, rec + XO, struct.pack("<f", x))
    n.poke(pid, rec + YO, struct.pack("<f", y))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--trials", type=int, default=8)
    a = ap.parse_args()
    i = a.instance
    pid = n._game_pid(i)
    assert pid, "no game process"
    assert n.ping(pid), "spy not answering"

    pair = players_verified(i, pid)
    if not pair:
        print("no verified pair — entering a match…")
        assert s.ensure_match(i), "could not reach a match"
        pair = players_verified(i, pid)
    assert pair, "no pair passing the five discriminators (wrong screen?)"
    p1, p2 = pair
    print(f"P1 {p1:#x}  P2 {p2:#x}")

    time.sleep(1.0)
    spawn = read_pair(pid, p1, p2)
    assert all(spawn), "could not read the spawn state"
    print(f"spawn: P1 ({spawn[0]['x']:.1f},{spawn[0]['y']:.1f}) "
          f"P2 ({spawn[1]['x']:.1f},{spawn[1]['y']:.1f})")

    tick0 = s.find_tick(pid)
    ok = 0
    for t in range(a.trials):
        # move them somewhere else first, so "reset" is a real restore
        n.spy_keydown(pid, "d"); time.sleep(0.25); n.spy_keyup(pid, "d")
        time.sleep(0.05)
        moved = read_pair(pid, p1, p2)
        write_xy(pid, p1, spawn[0]["x"], spawn[0]["y"])
        write_xy(pid, p2, spawn[1]["x"], spawn[1]["y"])
        time.sleep(0.12)
        after = read_pair(pid, p1, p2)
        time.sleep(0.35)
        later = read_pair(pid, p1, p2)
        if not all(after) or not all(later):
            print(f"  trial {t}: read failed (crash?)")
            break
        d1 = abs(after[0]["x"] - spawn[0]["x"]) + abs(after[1]["x"] - spawn[1]["x"])
        d2 = abs(later[0]["x"] - spawn[0]["x"]) + abs(later[1]["x"] - spawn[1]["x"])
        stuck = d1 <= 3 and d2 <= 6
        alive = n.ping(pid) is not None
        print(f"  trial {t}: moved by {(moved[0]['x']-spawn[0]['x']):+.0f}px, "
              f"after write Δ={d1:.1f}px, 0.35s later Δ={d2:.1f}px, "
              f"anim {after[0]['anim']}->{later[0]['anim']}  "
              f"{'KEPT' if stuck else 'SNAPPED'}{'' if alive else '  SPY DEAD'}")
        if stuck and alive:
            ok += 1

    # does control still work after all that writing?
    b = read_pair(pid, p1, p2)
    n.spy_keydown(pid, "d"); time.sleep(0.3); n.spy_keyup(pid, "d"); time.sleep(0.15)
    c = read_pair(pid, p1, p2)
    ctrl = abs(c[0]["x"] - b[0]["x"])
    print(f"\nafter {ok}/{a.trials} resets: walking moves P1 {ctrl:+.1f}px")
    print("PASS" if ok == a.trials and ctrl > 5 else "FAIL")
    return 0 if ok == a.trials and ctrl > 5 else 1


if __name__ == "__main__":
    sys.exit(main())
