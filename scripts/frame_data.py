#!/usr/bin/env python3
"""Gate A: does one frame of action latency matter for this game?

A1  frame windows: press a key, read `anim` on EVERY tick, get startup and duration in ticks
A2  the coin flip: is a 1-tick press registered deterministically, and one frame late or not?
A3  free fix: does a 2-tick press behave identically (i.e. can we buy determinism without a hook)?

    python3 scripts/frame_data.py 0

Writes results/gate_a.json. Read-only apart from key presses, all through the pushed state file.
Needs a live, drivable match (use nidstate.ensure_match first).
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402

KEYS = {"attack": "f", "walk": "d", "crouch": "s", "jump": "g"}

REGS = []
OFF_FACING, OFF_ANIM, OFF_X, OFF_Y, OFF_TYPE = 0xD8, 0xBC, 0xEC, 0xF0, 0x88


def _mapped(addr, size=8):
    global REGS
    if not REGS:
        REGS = s.regions(n._game_pid(0), min_size=0x1000)
    return any(lo <= addr and addr + size <= hi for lo, hi in REGS)


def _rec(pid, addr):
    """Plausible fighter record, or None. Junk memory fails every one of these."""
    if not _mapped(addr, 0x100):
        return None
    raw = n.memory_many(pid, [(addr + 0x80, 0x80, "/tmp/fd.bin")])[0]
    if raw is None or len(raw) < 0x80:
        return None
    import struct
    typ, anim = struct.unpack_from("<I", raw, OFF_TYPE - 0x80)[0], struct.unpack_from("<I", raw, OFF_ANIM - 0x80)[0]
    facing, x, y = struct.unpack_from("<f", raw, OFF_FACING - 0x80)[0], struct.unpack_from("<f", raw, OFF_X - 0x80)[0], struct.unpack_from("<f", raw, OFF_Y - 0x80)[0]
    if not _mapped(typ, 8) or typ < 0x10000:
        return None                      # +0x88 must be a real object-type pointer
    if not (0 < anim < 10000):
        return None                      # anim index, not 1.1 billion
    if facing not in (-1.0, 1.0):
        return None
    if not (0.0 <= x <= 2200.0 and 15.0 <= y <= 300.0):
        return None
    return dict(addr=addr, typ=typ, anim=anim, facing=facing, x=x, y=y)


def _xof(pid, addr):
    raw = n.memory_many(pid, [(addr + OFF_X, 4, "/tmp/fx.bin")])[0]
    import struct
    return struct.unpack("<f", raw)[0] if raw else None


def find_pair_strict(pid, verbose=True):
    """P1/P2 by causality: 'd' must move exactly one record, 'Right' exactly the other.

    Three traps this avoids, all hit for real during Gate A:
      * a pair member may BE P2 — testing only 'd' rejects a perfectly good pair;
      * junk records pass a single press by coincidence -> require sign, size, and stop;
      * find_fighters() only sees type-groups of size two, so a live round may have none.
    """
    groups = {}
    for addr, _x, _y, t in s.find_fighters(pid):
        r = _rec(pid, addr)
        if r:
            groups.setdefault(r["typ"], []).append(r)
    cands = [(t, g) for t, g in groups.items() if len(g) >= 2]
    if verbose:
        print(f"  {len(cands)} sane candidate pairs")

    def delta(key):                       # -> ({addr: dx}, stopped?)
        return None, None
    for typ, g in cands:
        a, b = g[0]["addr"], g[1]["addr"]
        if abs(g[0]["y"] - g[1]["y"]) > 25:
            continue
        moves = {}
        for key in ("d", "Right"):
            x0 = {a: _xof(pid, a), b: _xof(pid, b)}
            n.spy_keydown(pid, key); time.sleep(0.30); n.spy_keyup(pid, key); time.sleep(0.18)
            x1 = {a: _xof(pid, a), b: _xof(pid, b)}
            n.spy_keydown(pid, key); time.sleep(0.15); n.spy_keyup(pid, key); time.sleep(0.12)
            x2 = {a: _xof(pid, a), b: _xof(pid, b)}
            if None in (x0[a], x0[b], x1[a], x1[b], x2[a], x2[b]):
                moves = None
                break
            moves[key] = {k: (x1[k] - x0[k], x2[k] - x1[k]) for k in (a, b)}
        if verbose and moves:
            print(f"    type {typ:#x} a={a:#x} b={b:#x} "
                  f"d={ {hex(k): v for k, v in moves['d'].items()} } "
                  f"Right={ {hex(k): v for k, v in moves['Right'].items()} }")
        if not moves:
            continue
        d, r = moves["d"], moves["Right"]

        def one_mover(m):
            big = [k for k, (dx, _) in m.items() if 8 < abs(dx) < 150]
            quiet = [k for k, (dx, _) in m.items() if abs(dx) <= 3]
            return big[0] if len(big) == 1 and len(quiet) == 1 else None

        p1, p2 = one_mover(d), one_mover(r)
        if p1 and p2 and p1 != p2:
            return p1, p2, typ
    raise AssertionError(
        "no trustworthy pair: no pair passed 'd moves one, Right moves the other' — "
        "wrong screen, or the round moved the records (re-identify early in the match)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--p1", type=lambda x: int(x, 0))
    ap.add_argument("--p2", type=lambda x: int(x, 0))
    a = ap.parse_args()
    ind = a.instance
    pid = n._game_pid(ind)
    assert pid, "no game process"
    assert n.ping(pid), "spy not answering"

    print(f"  screen: ready={s.on_ready_screen(ind)} in_match={s.in_match(ind)}")
    n._focus(ind)          # XTEST, like xdotool, goes to the FOCUSED window
    if a.p1 and a.p2:
        p1, p2 = a.p1, a.p2
        r1 = _rec(pid, p1)
        ptype = r1["typ"] if r1 else 0
        # identify EARLY (docs): re-proving decays as a session runs, so verify once and reuse
        x0, y0 = _xof(pid, p1), _xof(pid, p2)
        n.spy_keydown(pid, "d"); time.sleep(0.3); n.spy_keyup(pid, "d"); time.sleep(0.1)
        dx, dy = _xof(pid, p1) - x0, _xof(pid, p2) - y0
        print(f"  given pair {p1:#x}/{p2:#x}: d -> P1 {dx:+.1f} px, P2 {dy:+.1f} px")
        assert 8 < dx < 150 and abs(dy) < 3, "given pair does not respond"
    else:
        p1, p2, ptype = find_pair_strict(pid)
    n.track(pid, p1=p1, p2=p2, tick=s.find_tick(pid) or 0)
    time.sleep(0.2)
    print(f"pair {p1:#x}/{p2:#x} type {ptype:#x}")

    report = {"type": hex(ptype), "A1": {}, "A2": {}, "A3": {}}

    print("\n== A1 frame windows (hold 6 ticks, so the action definitely registers)")
    for label, key in KEYS.items():
        tl, tp, tr = press(pid, key, hold_ticks=6)
        if not tl:
            print(f"  {label:7s} no samples")
            continue
        r = analyse(tl, tp, tr)
        if r["startup"] is None:
            print(f"  {label:7s} (key {key}) never left idle anim {r['idle']}")
            report["A1"][label] = {"startup": None}
            continue
        report["A1"][label] = {"key": key, "startup": r["startup"], "window": r["window"],
                               "idle_anim": r["idle"], "dx": round(r["x1"] - r["x0"], 1)}
        print(f"  {label:7s} (key {key}) idle anim {r['idle']:4d} -> startup {r['startup']} tick(s),"
              f" window {r['window']} tick(s), dx {r['x1'] - r['x0']:+.1f} px")

    print("\n== A2/A3 determinism: which tick shows the press, 1-tick vs 2-tick hold")
    for hold in (1, 2):
        results = []
        for trial in range(a.trials):
            k = "d" if trial % 2 == 0 else "a"   # stay put: walking one way ends rounds
            tl, tp, tr = press(pid, k, hold_ticks=hold, before=4, after=6)
            if not tl:
                continue
            r = analyse(tl, tp, tr)
            results.append(r["startup"])
        c = collections.Counter(results)
        key = "A2" if hold == 1 else "A3"
        report[key] = {"hold": hold, "trials": len(results),
                       "startup": {str(k): v for k, v in sorted(c.items(), key=lambda kv: (kv[0] is None, kv[0]))}}
        print(f"  hold={hold} tick: startup {dict(sorted(c.items(), key=lambda kv: (kv[0] is None, kv[0])))}"
              f"   ({len(results)} trials)")

    out = Path("results/gate_a.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    n.untrack(pid)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
