"""Plumbing for nidenv: batched spy commands, fighter records, master records, screen check.

Every spy command goes through send(): one atomic batch, and we wait until the spy has run
it. Separate _send calls overwrite /tmp/nid_cmd_<pid> if the spy has not claimed the previous
one yet, so back-to-back keydown/keyup calls can be lost (a stuck key).
"""
import os, struct, sys, threading, time
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nidstate as s

n = s.n
FARM = Path(os.environ.get("NIDFARM") or (Path.home() / ".nidfarm"))
ART = os.environ.get("NIDART") or str(FARM / "art")
os.makedirs(ART, exist_ok=True)
# nidstate/nidlinux use fixed /tmp scratch names that another user owns on artemis.
_mm, _m, _fr = n.memory_many, n.memory, n.frame
_fix = lambda p: ART + "/" + os.path.basename(str(p)) if str(p).startswith("/tmp/") else p
n.memory_many = lambda pid, req, timeout=15.0: _mm(pid, [(a, z, _fix(p)) for a, z, p in req], timeout)
n.memory = lambda pid, addr, size, path="/tmp/nid_dump.bin": _m(pid, addr, size, _fix(path))
n.frame = lambda i, path="/tmp/nid_f.png": _fr(i, _fix(path))

KEYS = {"P1": dict(left="a", right="d", up="w", down="s", attack="f", jump="g"),
        "P2": dict(left="Left", right="Right", up="Up", down="Down", attack="m", jump="n")}
ALL_KEYS = [k for p in KEYS.values() for k in p.values()]
COLOUR = {"P1": "yellow", "P2": "orange"}
# Current room index (GameMaker room order in data.win's ROOM chunk): an int32 in Nidhogg.exe's
# .data section at image base + ROOM_OFF. Found 2026-11-16 by diffing that section between the
# main menu (cell == 2, rMainMenu) and a match (== 29, rCastleCenter): exactly one cell matched.
# The spy publishes it every tick in its "score" slot (NidState.score_orange).
ROOM_OFF = 0x1ace918
ARENA_ROOMS = range(26, 78)   # rCastleLeftEnd .. rCemeterySuddenDeath
MENU_ROOMS = {1: "rLogos", 2: "rMainMenu", 3: "rMultiMenu", 4: "rOnlineLobby", 17: "rLevelSelect",
              20: "rMatchStats", 25: "rPreMatch"}


def exe_base(pid):
    for line in open(f"/proc/{pid}/maps"):
        if line.rstrip().endswith("/Nidhogg.exe"):
            return int(line.split("-")[0], 16)
    raise AssertionError(f"Nidhogg.exe not mapped in pid {pid}")


class Mem:
    def __init__(self, inst=0):
        self.inst = inst
        self.pid = n._game_pid(inst)
        assert self.pid and n.ping(self.pid), "no game / no spy on this instance"
        # find_tick can return a counter that later stalls (seen once: no samples for 8 s), so
        # a tick address that has served a whole run is cached per game pid and reused
        cache = FARM / f"tick_{self.pid}.txt"
        self.tick_addr = int(cache.read_text(), 16) if cache.exists() else s.find_tick(self.pid)
        assert self.tick_addr, "tick counter not found"
        self.room_addr = exe_base(self.pid) + ROOM_OFF
        raw = n.memory(self.pid, self.room_addr, 4, "/tmp/nmem_room.bin")
        assert raw and 0 <= struct.unpack("<i", raw)[0] < 82, f"room index unreadable: {raw}"
        # (tick, room) of every published sample, in order. The game runs free between agent
        # steps (~4 of every 5 ticks pass while the agent thinks), so a thread polls the spy's
        # state file every 0.5 ms and keeps each new tick; reading it costs ~20 us.
        self.room_log = []
        threading.Thread(target=self._watch_rooms, daemon=True).start()
        self.rec = {"P1": None, "P2": None}
        self.otypes, self.dead, self.masters, self.offset = set(), set(), {}, {}

    def send(self, lines):
        assert n._wait_idle(self.pid, 2.0), "spy busy"
        n._send(self.pid, "\n".join(lines))
        assert n._wait_idle(self.pid, 2.0), "spy did not run the batch"

    def release_all(self):
        self.send([f"ku {k}" for k in ALL_KEYS])

    def track(self, a=None, b=None):
        a = self.rec["P1"] if a is None else a
        b = self.rec["P2"] if b is None else b
        for _ in range(4):               # seen once: no sample for 2 s right after a big scan
            self.send([f"track {a or 0:x} {b or 0:x} {self.room_addr:x} {self.tick_addr:x}"])
            n.wait_state(self.pid, timeout=1.0)
            st = n.wait_state(self.pid, timeout=1.0)
            if st:
                return st
        raise AssertionError("state file not updating")

    def ticks(self, k):
        """Every sample for the next k ticks (the spy publishes one per tick)."""
        first = n.state(self.pid)
        out, seq = [], first.seq
        while not out or out[-1].tick < first.tick + k:
            st = n.wait_state(self.pid, seq, timeout=1.0)
            if st is None:
                raise RuntimeError("state file stopped updating (game hung or exited)")
            out.append(st); seq = st.seq
        return out

    def _watch_rooms(self):
        last = None
        while True:
            st = n.state(self.pid)
            if st is not None and st.tick != last:
                last = st.tick
                self.room_log.append((st.tick, st.score_orange if st.flags & n.FLAG_SCORE else -1))
            time.sleep(0.0005)

    def scan(self):
        """[(addr, type, x, y)] for every 0x200 record with fighter-plausible coordinates."""
        heaps = s._cached_heaps(self.pid) or [r for r in s.regions(self.pid) if r[1] - r[0] >= 1 << 20]
        reqs = [(a, b - a, f"/tmp/nmem_{k}.bin") for k, (a, b) in enumerate(heaps)]
        out = []
        for (a, _b), raw in zip(heaps, n.memory_many(self.pid, reqs)):
            if raw is None:
                continue
            u = np.frombuffer(raw[: len(raw) // 4 * 4], "<u4")
            f = u.view("<f4")
            idx = np.arange(0, len(u) - s.Y_OFF // 4 - 1, s.REC // 4)
            xs, ys, ts = f[idx + s.X_OFF // 4], f[idx + s.Y_OFF // 4], u[idx + s.TYPE_OFF // 4]
            with np.errstate(invalid="ignore"):
                ok = np.isfinite(xs) & np.isfinite(ys) & (xs > 0) & (xs < 2200) & (ys > 15) & (ys < 300)
            for j in np.nonzero(ok & (ts != 0))[0]:
                out.append((a + int(idx[j]) * 4, int(ts[j]), float(xs[j]), float(ys[j])))
        return out

    def type_records(self):
        return {a: (x, y) for a, t, x, y in self.scan() if t in self.otypes}

    def dx_on(self, addr, key, ticks=24):
        """x displacement of `addr` while `key` is held for `ticks` ticks (then released)."""
        x0 = self.track(addr, 0).p1_x
        self.send([f"kd {key}"])
        x1 = self.ticks(ticks)[-1].p1_x
        self.send([f"ku {key}"])
        self.ticks(8)
        return x1 - x0

    def answers(self, addr, who, away=-1):
        """Causal test: who's left key moves addr left AND right key moves it right (a corpse
        or a drifting prop fails). Walks `away` first, then back, so the net shift is ~0."""
        k = KEYS[who]
        first, second = (k["left"], k["right"]) if away < 0 else (k["right"], k["left"])
        d1, d2 = self.dx_on(addr, first), self.dx_on(addr, second)
        dl, dr = (d1, d2) if away < 0 else (d2, d1)
        # one side may be blocked (screen edge, wall): then the other key must move it the
        # right way and the blocked key must not move it the wrong way (a drifting prop fails)
        ok = (dl < -5 and dr > -1) or (dr > 5 and dl < 1)
        return ok, (round(dl, 1), round(dr, 1))

    def identify(self, who, away):
        """The record that answers to who's keys. Candidates: the fighter type if known, else
        types with 2..6 records in the ground band (fighters + corpses)."""
        recs = self.scan()
        count = {}
        for _a, t, _x, _y in recs:
            count[t] = count.get(t, 0) + 1
        other = self.rec["P2" if who == "P1" else "P1"]
        cands = [(a, t, y) for a, t, _x, y in recs if a != other
                 and (t in self.otypes or (2 <= count[t] <= 6 and 100 <= y <= 200))]
        # known fighter types first, then lowest (feet = largest y: the body, not arm/sword);
        # records once dropped go last, not out: the game reuses records for respawns
        # a fighter type has 2..6 records (2 bodies + corpses); a type with many is scenery
        cands.sort(key=lambda c: (c[0] in self.dead, c[0] != self.rec[who],
                                  not 2 <= count[c[1]] <= 6, c[1] not in self.otypes, -c[2]))
        for a, t, _y in cands[:40]:
            ok, d = self.answers(a, who, away)
            if ok:
                self.rec[who] = a
                self.otypes.add(t)
                return d
        return None

    def master(self, addr):
        """The record whose x the fighter record copies every tick. Writes to the fighter
        record's own x are overwritten next tick; writes to the master are kept. Found by
        nudging each neighbour's x by -4 and watching the tracked x follow."""
        if addr in self.masters:
            return self.masters[addr]
        self.track(addr, 0)
        self.ticks(10)
        st = n.state(self.pid)
        near = [addr + k * s.REC for k in (2, 1, -1, -2, 3, -3, 4, -4)]
        same = [a for a, _t, x, y in self.scan() if a != addr and a not in near
                and abs(x - st.p1_x) < 12 and abs(y - st.p1_y) < 25]
        for b in near + same:
            x = n.state(self.pid).p1_x
            raw = n.memory(self.pid, b + s.X_OFF, 4, "/tmp/nmem_m.bin")
            if not raw or abs(struct.unpack("<f", raw)[0] - x) > 12:
                continue
            mx = struct.unpack("<f", raw)[0] - 4
            self.send([f"poke {b + s.X_OFF:x} {struct.pack('<f', mx).hex()}"])
            x1 = self.ticks(4)[-1].p1_x
            if -6 < x1 - x < -2:
                self.masters[addr] = b
                self.offset[addr] = round(x1 - mx, 2)    # body x - master x (0 for most)
                return b
        return None

    def master_holds(self, addr):
        """The cached master still drives addr: body x = master x + offset (read only). The
        game reuses a record for a respawn with a new master, and a record's address can turn
        up later as another fighter's master, so a cached master can go stale."""
        raw = n.memory(self.pid, self.masters[addr] + s.X_OFF, 4, "/tmp/nmem_m.bin")
        body = n.memory(self.pid, addr + s.X_OFF, 4, "/tmp/nmem_b.bin")
        return bool(raw and body and abs(struct.unpack("<f", raw)[0] + self.offset[addr]
                                         - struct.unpack("<f", body)[0]) < 1)

    def unstick(self, who, free_x, max_tries=6):
        """A fighter written into a step stops answering. Move each other fighter-type record
        (via its master) next to the free fighter and keep the one that answers who's keys."""
        other = self.rec["P2" if who == "P1" else "P1"]
        for a in list(self.type_records())[: max_tries]:
            if a == other or not self.master(a):
                continue
            for dx in (60, -60):
                self.send([f"poke {self.masters[a] + s.X_OFF:x} "
                           f"{struct.pack('<f', free_x + dx - self.offset[a]).hex()}"])
                self.ticks(30)
                ok, d = self.answers(a, who)
                if ok:
                    self.rec[who] = a
                    self.dead.discard(a)
                    return d
        return None

    def place(self, x1, x2):
        """Write both fighters' x into their master records in ONE spy batch (same tick).
        The body can sit a few px off its master (0, 1.7, 8 and 28 px measured, it changes with
        state), so read the body back and correct the offset, up to 3 writes. Needs both
        fighters tracked."""
        for _ in range(3):
            lines = []
            for who, x in (("P1", x1), ("P2", x2)):
                r = self.rec[who]
                lines.append(f"poke {self.masters[r] + s.X_OFF:x} "
                             f"{struct.pack('<f', x - self.offset[r]).hex()}")
            self.send(lines)
            prev, got = self.ticks(4)[-2:]
            err = {"P1": got.p1_x - x1, "P2": got.p2_x - x2}
            if all(abs(e) < 0.5 for e in err.values()):
                return
            # learn an offset only from a body standing still: a body that is falling, sliding
            # or pushed out of a step is still moving, and its error is not an offset (an error
            # learned that way stayed in self.offset and shifted every later write)
            moving = {"P1": got.p1_x != prev.p1_x or got.p1_y != prev.p1_y,
                      "P2": got.p2_x != prev.p2_x or got.p2_y != prev.p2_y}
            for who, e in err.items():
                if abs(e) < 40 and not moving[who]:   # 28 px seen; more is a wall or a step
                    self.offset[self.rec[who]] += e

    def screen(self, name="scr", ys_rec=None):
        """{who: x of the densest colour cluster in world units from the left edge of the
        view (or None), 'n': pixel counts}."""
        a = s.frame(self.inst, name)
        out = {"n": {}}
        k = a.shape[1] / 320 if a is not None else 1.0      # the 320-unit view is drawn at 2x
        for who in ("P1", "P2"):
            m = s._mask(a, COLOUR[who]) if a is not None else np.zeros((1, 1), bool)
            y = (ys_rec or {}).get(who, 192.0)  # body rows only: y-32..y-3 (feet at record y);
            m[: int((y - 32) * k), :] = False  # excludes the GO arrow and blood on the floor
            m[int((y - 3) * k):, :] = False
            ys, xs = np.nonzero(m)
            out["n"][who] = int(len(xs))
            if len(xs) < 15 * k * k:
                out[who] = None
                continue
            w = int(24 * k)
            win = np.convolve(np.bincount(xs, minlength=m.shape[1]), np.ones(w), "same")
            peak = int(np.argmax(win))
            sel = xs[(xs >= peak - w // 2 - 2) & (xs <= peak + w // 2 + 2)]
            out[who] = round(float(sel.mean()) / k, 1)        # world units from the view's left edge
            # every cluster of this colour, densest first: a corpse lying in the body rows is
            # the same colour and can be denser than the fighter
            cl, win = [], win.copy()
            while len(cl) < 4 and win.max() >= 15 * k * k:
                p = int(np.argmax(win))
                sel = xs[(xs >= p - w // 2 - 2) & (xs <= p + w // 2 + 2)]
                cl.append(round(float(sel.mean()) / k, 1))
                win[max(0, p - w):p + w] = 0
            out.setdefault("clusters", {})[who] = cl
        return out

    def shift_check(self, x1, x2, d=20, name="sh"):
        """Screen check by motion, for views where colour alone cannot place the bodies:
        orange paint on the floor (more orange clusters than the 4 kept), an orange or yellow
        background, a room whose view is scrolled vertically (the body rows miss the body).
        Moves P1 +d and P2 -d in one write (toward each other: the pair's midpoint, which the
        camera follows, stays put), grabs a frame before and after, and keeps only the pixels
        of each colour that changed: background and paint cancel. Passes when each fighter's
        changed pixels moved by about +d / -d and the gap between them is the records' gap.
        Puts both back at (x1, x2). Returns (ok, info)."""
        a = s.frame(self.inst, name + "0")
        self.place(x1 + d, x2 - d)
        self.ticks(6)
        b = s.frame(self.inst, name + "1")
        self.place(x1, x2)
        self.ticks(6)
        if a is None or b is None:
            return False, {"error": "no frame"}
        k = a.shape[1] / 320
        w = int(24 * k)
        info, pos = {}, {}
        for who in ("P1", "P2"):
            ma, mb = s._mask(a, COLOUR[who]), s._mask(b, COLOUR[who])
            for tag, m in (("old", ma & ~mb), ("new", mb & ~ma)):
                xs = np.nonzero(m)[1]
                info[f"{who}_{tag}_n"] = int(len(xs))
                if len(xs) < 15 * k * k:
                    pos[who, tag] = None
                    continue
                win = np.convolve(np.bincount(xs, minlength=m.shape[1]), np.ones(w), "same")
                p = int(np.argmax(win))
                sel = xs[(xs >= p - w // 2 - 2) & (xs <= p + w // 2 + 2)]
                pos[who, tag] = round(float(sel.mean()) / k, 1)
        info["pos"] = {f"{who}_{tag}": v for (who, tag), v in pos.items()}
        if None in pos.values():
            return False, info
        moved1 = pos["P1", "new"] - pos["P1", "old"]
        moved2 = pos["P2", "new"] - pos["P2", "old"]
        gap = pos["P2", "old"] - pos["P1", "old"]
        info.update(moved=[round(moved1, 1), round(moved2, 1)], gap=round(gap, 1),
                    gap_rec=round(x2 - x1, 1))
        ok = abs(moved1 - d) < 8 and abs(moved2 + d) < 8 and abs(gap - (x2 - x1)) < 12
        return ok, info
