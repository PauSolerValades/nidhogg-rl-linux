#!/usr/bin/env python3
"""Record a human session without ever touching the player's input.

Why this exists next to record.py: identification by key presses fights a human, addresses go
stale every round, and a silent recorder that writes nothing is worse than none. This one

  * identifies with the ENGINE's instance list (no keys at all),
  * re-resolves identity when the pair changes (round transitions recycle records),
  * prints a heartbeat every 5 s so you can see it working before you start playing,
  * dumps EVERY rw region >= 1 MB (a filtered region set is how the ORANGE wins field was
    missed for two sessions — see docs/TMP_CURRENT_STATE.md §2.4b).

    python3 scripts/record_human.py <instance> [--heap-every 12] [--seconds 3600]

Writes ~/nidhogg-record/<stamp>/:
  states.csv   20 Hz: tick, both bodies' x,y + anim/facing, and the round index
  shots/       2 Hz screenshots (the READY tally, the winner screen, everything)
  heaps/       full memory dumps + regions.json (offsets are meaningless without it)
  rounds.json  per round: the two record addresses, which of them was LEFT at round start
               (= yellow, by every READY/GO frame measured so far)
"""
import argparse
import csv
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402

XO, YO, ANIM, FACE = 0xEC, 0xF0, 0xBC, 0xD8


def plausible(pid, rec):
    raw = n.memory_many(pid, [(rec + 0x80, 0x80, "/tmp/rh_p.bin")])[0]
    if raw is None or len(raw) < 0x80:
        return False
    typ, anim = struct.unpack_from("<I", raw, 8)[0], struct.unpack_from("<I", raw, 0x3C)[0]
    facing, x, y = (struct.unpack_from("<f", raw, o)[0] for o in (0x58, 0x6C, 0x70))
    return (typ > 0x10000 and 0 < anim < 10000 and facing in (-1.0, 1.0)
            and 0.0 <= x <= 2200.0 and 15.0 <= y <= 300.0)


class Identity:
    """The player pair, from the instance list, re-resolved when it goes stale."""

    def __init__(self, pid, type_ptr=None):
        self.pid = pid
        self.type = type_ptr        # pinned: never guess when the caller already knows
        self.pair = None
        self.pinned = None

    def _walk(self):
        if not self.type:
            return None
        inst = s.instances_of_type(self.pid, self.type)
        ok = [i["rec"] for i in inst if plausible(self.pid, i["rec"])]
        return ok if len(ok) == 2 else None

    def _resolve(self):
        """Bootstrap from the instance list itself.

        find_fighters() cannot be the bootstrap: it demands exactly two instances per type, and
        on READY the player type has a third (so it returns 0 and a recorder sits there writing
        nothing). Instead enumerate object definitions, walk each list, and take the pair that is
        furthest apart in x — the two fighters stand at opposite ends, nothing else does.
        """
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import phase_b2 as b2
        mem = b2.Mem(self.pid)
        best = (-1.0, None, None)
        seen = set()
        for a0, b0, raw in mem.blobs:
            if not (0x1600000 <= a0 <= 0x1A00000):
                continue
            for off in range(0, len(raw) - 8, 8):
                cand = a0 + off
                if cand in seen:
                    continue
                r = mem.region_of(cand + 0xa0, 8)
                if r is None:
                    continue
                head = struct.unpack_from("<Q", r[1], cand + 0xa0 - r[0])[0]
                if not head or head % 8 or mem.region_of(head, 0x80) is None:
                    continue
                ch = b2.chain(mem, head)
                if not ch or len(ch) != 2 or ch[0]["type"] != cand:
                    continue
                seen.add(cand)
                recs = [nd["rec"] for nd in ch]
                if not all(plausible(self.pid, r0) for r0 in recs):
                    continue
                xs = [s.read_x(self.pid, r0) or 0 for r0 in recs]
                if abs(xs[0] - xs[1]) > best[0]:
                    best = (abs(xs[0] - xs[1]), cand, recs)
        if best[1] is None:
            print("    resolve: no two-instance object looked like the players", flush=True)
            return None
        self.type = best[1]
        print(f"    resolve: type {best[1]:#x} -> players at x={best[0]:.0f} apart", flush=True)
        return best[2]

    def get(self):
        if self.pinned and all(plausible(self.pid, r) for r in self.pinned):
            return list(self.pinned)
        self.pinned = None
        got = self._walk() or self._resolve()
        self.pair = got
        return got


def sprite_xs(pid_ind):
    """Pixel x of the yellow and orange sprites. The READY screen is fixed-camera, so a record's
    world x maps 1:1 to the sprite's pixel x — that is what makes this identification key-free."""
    import subprocess
    import numpy as np
    p = n.grab(pid_ind, "/tmp/rh_sprite.png")
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(p),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    if not raw:
        return None
    f = np.frombuffer(raw, np.uint8).reshape(200, 320, 3).astype(int)
    out = {}
    for name, colour in (("yellow", (255, 232, 0)), ("orange", (255, 140, 40))):
        m = np.abs(f - np.array(colour)).max(axis=2) <= 60
        m[:100, :] = False                     # skip the HUD band
        ys, xs = np.nonzero(m)
        if len(xs) < 40:
            return None
        out[name] = float(np.median(xs))
    return out


def resolve_by_sprite(pid, ind):
    """The PAIR of records whose world x matches the two sprites, searched inside every chain.

    It must not demand a chain of exactly two: on READY the player type has a third instance (a
    controller), and filtering on len==2 silently skipped the players and tracked markers instead.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import phase_b2 as b2
    got = sprite_xs(ind)
    if not got:
        return None
    a_want, b_want = got["yellow"], got["orange"]      # colour, not side
    mem = b2.Mem(pid)
    best = (1e9, None)
    tried = set()
    scanned = 0
    for a0, b0, raw in mem.blobs:
        if not (0x1600000 <= a0 <= 0x1A00000):
            continue
        for off in range(0, len(raw) - 8, 8):
            cand = a0 + off
            if cand in tried:
                continue
            r = mem.region_of(cand + 0xa0, 8)
            if r is None:
                continue
            head = struct.unpack_from("<Q", r[1], cand + 0xa0 - r[0])[0]
            if not head or head % 8 or mem.region_of(head, 0x80) is None:
                continue
            ch = b2.chain(mem, head)
            if not ch or len(ch) < 2 or ch[0]["type"] != cand:
                continue
            tried.add(cand)
            scanned += 1
            if scanned % 100 == 0:
                print(f"    scanning… {scanned} chains, best {best[0]:.0f} px", flush=True)
            recs = [nd["rec"] for nd in ch if plausible(pid, nd["rec"])]
            if not (2 <= len(recs) <= 12):
                continue
            xs_of = {r0: (s.read_x(pid, r0) or 0) for r0 in recs}    # one read each, not per pair
            for i1 in range(len(recs)):
                for i2 in range(i1 + 1, len(recs)):
                    x1, x2 = xs_of[recs[i1]], xs_of[recs[i2]]
                    # ROLE BY COLOUR: the sprites swap sides between rounds (measured: yellow was
                    # right, orange left), so "leftmost = yellow" is wrong. Pair each record with
                    # whichever sprite it sits under.
                    e_a = abs(x1 - a_want) + abs(x2 - b_want)
                    e_b = abs(x1 - b_want) + abs(x2 - a_want)
                    if e_a <= e_b:
                        err, p1, p2 = e_a, recs[i1], recs[i2]
                    else:
                        err, p1, p2 = e_b, recs[i2], recs[i1]
                    if err < best[0]:
                        best = (err, (p1, p2, cand, [x1, x2]))
    if best[1] is None or best[0] > 12:
        print(f"    sprite match failed (best {best[0]:.0f} px)", flush=True)
        return None
    err, (r1, r2, typ, xs) = best
    print(f"    sprite match: yellow={r1:#x} orange={r2:#x} type {typ:#x} "
          f"records x={xs} vs yellow/orange sprites at "
          f"{[round(got['yellow']), round(got['orange'])]} (err {err:.0f} px)", flush=True)
    return {"p1": r1, "p2": r2, "type": typ}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("--heap-every", type=float, default=15.0)
    ap.add_argument("--seconds", type=float, default=3600.0)
    ap.add_argument("--no-tick", action="store_true", help="skip the tick scan (starts instantly)")
    ap.add_argument("--sprite", action="store_true",
                    help="bootstrap identity by matching records to the sprites (fixed camera)")
    ap.add_argument("--type", type=lambda x: int(x, 0), default=None,
                    help="pin the object definition pointer (bootstrap by input once, then reuse)")
    a = ap.parse_args()
    i = a.instance
    pid = n._game_pid(i)
    assert pid, "no game process"
    assert n.ping(pid), f"spy not answering in {pid}"

    out = Path.home() / "nidhogg-record" / time.strftime("%Y%m%d-%H%M%S")
    (out / "shots").mkdir(parents=True, exist_ok=True)
    (out / "heaps").mkdir(parents=True, exist_ok=True)
    print(f"recording into {out}", flush=True)

    ident = Identity(pid, a.type)
    if a.sprite and not a.type:
        m = resolve_by_sprite(pid, i)
        if m:
            ident.type = m["type"]
            ident.pinned = (m["p1"], m["p2"])
    print("identifying from the instance list (no key presses)…", flush=True)
    pair = ident.get()          # one attempt; the main loop keeps retrying
    print(f"identity: {[hex(p) for p in pair] if pair else 'not yet (will retry in the loop)'}",
          flush=True)

    regions = [(a0, b0) for a0, b0 in s.regions(pid, min_size=1 << 20)]
    (out / "regions.json").write_text(json.dumps(
        [{"base": hex(a0), "size": b0 - a0} for a0, b0 in regions], indent=1))
    print(f"{len(regions)} regions, {sum(b - a for a, b in regions) / 2**30:.2f} GB per dump",
          flush=True)

    rounds, cur = [], None
    csv_path = out / "states.csv"
    t0 = time.time()
    last_heap = last_beat = 0.0
    rows = shots = heaps = 0
    stop = [False]

    def shoot(stop_flag):
        """Screenshots in a thread: a grab costs ~100 ms, which would otherwise cap the
        state loop at ~1 Hz (it did, before this)."""
        k = 0
        while not stop_flag[0]:
            now = time.time() - t0
            n.grab(i, str(out / "shots" / f"{int(now * 1000):08d}.png"))
            k += 1
            time.sleep(0.4)
        return k

    import threading
    th = threading.Thread(target=shoot, args=(stop,), daemon=True)
    th.start()

    # The tick address is per process and finding it costs 4 heap dumps; it is a nice-to-have
    # (a stable timestamp per row), not a requirement. Without it the spy publishes on its 8 ms
    # fallback and the rows still carry x/y/anim/facing.
    tickaddr = 0 if a.no_tick else (s.find_tick(pid) or 0)
    print(f"tick field: {tickaddr and hex(tickaddr)}", flush=True)
    if pair:
        n.track(pid, p1=pair[0], p2=pair[1], tick=tickaddr)
        cur = len(rounds)
        xs = [s.read_x(pid, r) or 0 for r in pair]
        rounds.append({"round": cur, "a": hex(pair[0]), "b": hex(pair[1]),
                       "start_x": [round(x, 1) for x in xs],
                       "left_is": "a" if xs[0] <= xs[1] else "b"})
        (out / "rounds.json").write_text(json.dumps(rounds, indent=1))
        print(f"  round {cur}: {[hex(p) for p in pair]} left={'a' if xs[0] <= xs[1] else 'b'}", flush=True)

    last_tick = 0
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t_ms", "tick", "ax", "ay", "a_anim", "a_face",
                    "bx", "by", "b_anim", "b_face", "round"])
        while time.time() - t0 < a.seconds:
            now = time.time() - t0
            got = ident.get() if now - getattr(ident, "stamp", -1e9) > 5 else pair
            ident.stamp = now
            if got and got != pair:
                pair = got
                cur = len(rounds)
                xs = [s.read_x(pid, r) or 0 for r in pair]
                rounds.append({"round": cur, "a": hex(pair[0]), "b": hex(pair[1]),
                               "start_x": [round(x, 1) for x in xs],
                               "left_is": "a" if xs[0] <= xs[1] else "b"})
                (out / "rounds.json").write_text(json.dumps(rounds, indent=1))
                n.track(pid, p1=pair[0], p2=pair[1], tick=tickaddr)
                print(f"  round {cur}: {[hex(p) for p in pair]} "
                      f"left={'a' if xs[0] <= xs[1] else 'b'}", flush=True)

            blobs = n.memory_many(pid, [(pair[0], 0x100, "/tmp/rh_a.bin"),
                                        (pair[1], 0x100, "/tmp/rh_b.bin")])
            b1, b2 = (blobs + [None, None])[:2]

            def g(b, off):
                return struct.unpack_from("<f", b, off)[0] if b and off + 4 <= len(b) else 0.0

            if b1 and b2:
                w.writerow([f"{now:.3f}", 0,
                            round(g(b1, XO), 2), round(g(b1, YO), 2), int(g(b1, ANIM)), int(g(b1, FACE)),
                            round(g(b2, XO), 2), round(g(b2, YO), 2), int(g(b2, ANIM)), int(g(b2, FACE)),
                            cur if cur is not None else -1])
                rows += 1
                if rows % 30 == 0:
                    fh.flush()

            if now - last_heap > a.heap_every:
                last_heap = now
                path = out / "heaps" / f"{int(now * 1000):08d}.bin"
                with open(path, "wb") as hf:
                    for a0, b0 in regions:
                        blob = n.memory(pid, a0, b0 - a0, "/tmp/rh_h.bin")
                        hf.write(blob if blob else b"")
                if path.stat().st_size:
                    heaps += 1
                    path.with_suffix(".json").write_text(json.dumps(
                        {"t": round(now, 2), "round": cur, "bytes": path.stat().st_size}))

            if now - last_beat > 5:
                last_beat = now
                fh.flush()
                db = sum(f.stat().st_size for f in (out / "heaps").glob("*.bin"))
                shots = len(list((out / "shots").glob("*.png")))
                print(f"  t={now:6.1f}s rows={rows:6d} ({rows / max(now, 1):4.1f}/s) "
                      f"shots={shots:5d} heaps={heaps:3d} ({db / 2**30:5.1f} GB) round={cur}",
                      flush=True)
            time.sleep(0.004)

    stop[0] = True
    th.join(timeout=2)
    (out / "rounds.json").write_text(json.dumps(rounds, indent=1))
    print(f"done: {csv_path}  ({rows} rows, {heaps} heaps, {len(rounds)} rounds)", flush=True)


if __name__ == "__main__":
    main()
