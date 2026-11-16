"""One live local two-player Nidhogg match as an environment; BOTH fighters are driven.

    env = Env(seed=0); obs = env.reset(); obs, done, info = env.step(a_p1, a_p2)

P1 = yellow (keys a d w s f g), P2 = orange (Left Right Up Down m n). Plumbing in nidmem.py.

Actions per player (one step = STEP_TICKS = 4 game ticks = 67 ms):
  0 idle  1 left  2 right  3 jump  4 attack  5 stance up  6 stance down  7 left+attack  8 right+attack
left/right are held while consecutive steps want them; jump/attack/up/down are pressed at step
start and released after 2 ticks, so a repeated attack is a new press every step.

Observation (8,) float32: P1 x/1000, P1 height (192-y)/100, P1 facing, dx (P2-P1)/300,
P2 height, P2 facing, P1 anim/500, P2 anim/500.

Reset (every episode, no menus): release every key of both players; re-identify a fighter by
input if its record died; find each fighter's master record (writes to the fighter record's x
snap back next tick; writes to the master stick); read the camera from the screen
(cam = record x - sprite screen x of yellow, or orange); write P1 at cam+160-SEP/2 and P2 at
cam+160+SEP/2 in one spy batch; check both stuck for 3 ticks; alive check = each record answers
its own left/right keys (walks away from the other, then back); write again; check stuck 3
ticks, then after SETTLE ticks both within 3 px, still (no held key moving them) and on screen
(colour cluster gap matches the record gap within 12 px). Up to 3 tries, logged.

Round end (a kill; Nidhogg has no per-kill Winner screen): fighter X died iff
  (a) X's record stays bit-identical (x, y, facing, anim) for FREEZE_TICKS ticks while the
      other fighter's record is not frozen, and then
  (b) a NEW record of the fighter type appears within RESPAWN_S that answers to X's keys,
      or, when no respawn comes (it waits for the leader to advance), the frozen anim is a
      death anim (DEATH_ANIMS) and X's old record does not answer X's keys (a corpse).
  Logged, not required: whether X's old record still answers (the game can reuse it).
A live stationary fighter passes (a) and fails (b): no new record, idle anim, answers its keys.
X dead -> the other player wins. Both dead -> 'draw'. MAX_STEPS without a kill -> 'undecided'.
"""
import json, time

import numpy as np

from nidmem import FARM, KEYS, Mem, n

STEP_TICKS, MAX_STEPS = 4, 450          # 450 x 4 ticks = 30 s of game time
FREEZE_TICKS, RESPAWN_S = 30, 6.0
DEATH_ANIMS = (240, 345)                # 243/245 -> 297 and 325/327 seen on every kill
SEP, SETTLE_TICKS = 140.0, 20
CONTACT_PX = 40.0                       # blades touch at ~30-40 px apart
PROBE_TICKS, PROBE_SHIFTS = 24, (0, -24, 24, -48, 48, -72, 72, -120, 120, -180, 180)
ACTIONS = [(), ("left",), ("right",), ("jump",), ("attack",), ("up",), ("down",),
           ("left", "attack"), ("right", "attack")]
HOLD = ("left", "right")
WHO = ("P1", "P2")


def _rec(st, who):
    p = who.lower()
    return tuple(round(getattr(st, f"{p}_{k}"), 3) for k in ("x", "y", "facing", "anim"))


def _stuck_at(samples, tx):
    """The written x held: identical over the samples and within 3 px of the target (a master
    can sit a px or two off the body; measured 1.7 px)."""
    return all(t.p1_x == samples[0].p1_x and t.p2_x == samples[0].p2_x
               and abs(t.p1_x - tx[0]) < 3 and abs(t.p2_x - tx[1]) < 3 for t in samples)


def _brief(st):
    return {k: getattr(st, k) for k in ("tick", "p1_x", "p1_y", "p1_facing", "p1_anim",
                                        "p2_x", "p2_y", "p2_facing", "p2_anim")}


class Env:
    def __init__(self, seed=0, inst=0, log=FARM / "episodes.jsonl"):
        self.m, self.seed, self.ep, self.log = Mem(inst), seed, 0, log
        self.held, self.strikes = set(), {}
        self.home = {}        # room index -> centre x where a reset settled in that room

    # ------------------------------------------------------------ reset
    def _find(self, who, away, r):
        """Identify who by input. A dead fighter respawns only once the leader advances, so
        if nobody answers: wait 3 s, then walk the other fighter right 1.5 s, then left 3 s."""
        m, other = self.m, ("P2" if who == "P1" else "P1")
        for wait, key, secs in ((0, None, 0), (3, None, 0), (0, "right", 1.5), (0, "left", 3)):
            time.sleep(wait)
            if key and m.rec[other]:
                m.send([f"kd {KEYS[other][key]}"]); time.sleep(secs); m.release_all()
                time.sleep(2.0)
                r.setdefault("respawn_walk", []).append(f"{other} {key} {secs}s")
            d = m.identify(who, away)
            if not d and not key and wait == 0 and m.rec[other]:    # stuck in a step?
                d = m.unstick(who, m.track(m.rec[other], 0).p1_x)
                r["unstuck"] = bool(d)
            if d:
                return d
        return None

    def _probe(self, tx):
        """Write both x and let the game resolve y. The write sets x only: a fighter written over
        a lower floor falls, one written into a step is pushed up or sideways. The spot is
        free when both end still, at their written x, on one floor."""
        self.m.place(*tx)
        # a long write (the home spot is often 300+ px from where they stood) can leave a body
        # climbing or falling for a while: watch up to 4x PROBE_TICKS until 8 still ticks
        tr = self.m.ticks(PROBE_TICKS)
        for _ in range(3):
            last = tr[-8:]
            if all(max(getattr(t, f) for t in last) - min(getattr(t, f) for t in last) < 0.5
                   for f in ("p1_x", "p2_x", "p1_y", "p2_y")):
                break
            tr = self.m.ticks(PROBE_TICKS)
        last, end = tr[-8:], tr[-1]
        still = all(max(getattr(t, f) for t in last) - min(getattr(t, f) for t in last) < 0.5
                    for f in ("p1_x", "p2_x", "p1_y", "p2_y"))
        ok = (still and abs(end.p1_x - tx[0]) < 3 and abs(end.p2_x - tx[1]) < 3
              and abs(end.p1_y - end.p2_y) < 2)
        return ok, end

    def _settle_ok(self, tx):
        self.m.ticks(1)                          # the sample of the write tick may predate it
        first = self.m.ticks(3)
        self.first3 = [(round(t.p1_x, 1), round(t.p2_x, 1)) for t in first]
        stick = _stuck_at(first, tx)
        tr = self.m.ticks(SETTLE_TICKS)
        last = tr[-10:]
        held_free = all(max(getattr(t, f) for t in last) - min(getattr(t, f) for t in last) < 0.5
                        for f in ("p1_x", "p2_x", "p1_y", "p2_y"))
        end = tr[-1]
        near = (abs(end.p1_x - tx[0]) < 3 and abs(end.p2_x - tx[1]) < 3
                and abs(end.p1_y - end.p2_y) < 2)        # same floor: no step between them
        return stick, near, held_free, end

    def reset(self):
        m = self.m
        m.room_log = []
        m.release_all(); self.held = set()
        tries = []
        for attempt in range(5):
            r = {"attempt": attempt, "reidentified": []}
            for who, away in (("P1", -1), ("P2", 1)):
                # a stale record (room change, missed death) fails its own keys: re-identify
                if (m.rec[who] is None or m.rec[who] in m.dead
                        or not m.answers(m.rec[who], who, away)[0]):
                    d = self._find(who, away, r)
                    assert d, f"no record answers to {who}'s keys: {json.dumps(tries + [r])}"
                    r["reidentified"].append(who)
            st = m.track()
            sc = m.screen(f"r{attempt}a", {"P1": st.p1_y, "P2": st.p2_y})
            # camera left edge, from each sprite; keep one only if it puts BOTH fighters in view
            cams = [x - sc[w] for w, x in (("P1", st.p1_x), ("P2", st.p2_x)) if sc[w] is not None]
            cams = [c for c in cams if all(0 <= x - c <= 320 for x in (st.p1_x, st.p2_x))]
            cam = (sum(cams) / len(cams) if cams and max(cams) - min(cams) < 12
                   else (st.p1_x + st.p2_x) / 2 - 160)
            # a master cached in an earlier episode can be stale (writes then move nothing, or
            # another object): drop it unless the body still copies it, so m.master() finds it
            # again by nudging
            r["stale_master"] = [w for w in WHO if m.rec[w] in m.masters
                                 and not m.master_holds(m.rec[w])]
            for w in r["stale_master"]:
                m.masters.pop(m.rec[w])
            lost = [w for w in WHO if not m.master(m.rec[w])]
            if lost:                                      # no master: not a body; re-identify
                r.update(no_master=lost, ok=False); tries.append(r)
                for w in lost:
                    m.dead.add(m.rec[w]); m.rec[w] = None
                continue
            st = m.track()          # both answered their keys here: a free spot to restore to
            orig = (st.p1_x, st.p2_x)
            room = m.room_log[-1][1] if m.room_log else -1
            r["room"] = room
            mid = (cam + 160, (st.p1_x + st.p2_x) / 2, st.p1_x + SEP / 2, st.p2_x - SEP / 2,
                   cam + 160)[attempt]          # retries: centred on spots known to be free
            if room in self.home and attempt in (0, 3):
                mid, r["home"] = self.home[room], True
            # a target is only good if both stand there on one floor: probe the first-choice
            # spot, then spots shifted left and right of it (the camera follows the fighters)
            probes = []
            for d in PROBE_SHIFTS:
                tx = (mid + d - SEP / 2, mid + d + SEP / 2)
                stick1, pe = self._probe(tx)
                probes.append([round(mid + d, 1), stick1, pe.p1_y, pe.p2_y])
                if stick1:
                    break
                if max(abs(pe.p1_x - tx[0]), abs(pe.p2_x - tx[1])) > 40:
                    break        # the body ignores its master: not the floor; next attempt
            r["probes"] = probes
            if not stick1:
                # no spot held both on one floor. Either the spots are bad or a record is not a
                # body (an arm/sword record answers the keys too and sits ~32 px above the
                # feet, so it never shares a floor with the other fighter): put both back and
                # re-identify both (identify tries the lowest record first: the body)
                r.update(ok=False, no_free_spot=True, orig=[round(x, 1) for x in orig],
                         not_body=list(WHO))
                tries.append(r)
                m.place(*orig); m.ticks(20)
                for w in WHO:
                    m.rec[w] = None
                continue
            a1, d1 = m.answers(m.rec["P1"], "P1", -1)
            a2, d2 = m.answers(m.rec["P2"], "P2", 1)
            m.track(); m.release_all()
            m.ticks(30)                          # fighters slide ~17 px after a walk key
            m.place(*tx)
            stick, near, held_free, end = self._settle_ok(tx)
            sc = m.screen(f"r{attempt}b", {"P1": end.p1_y, "P2": end.p2_y})
            # some yellow and some orange cluster sit at the records' gap (not only the densest
            # ones: a corpse of the same colour can outweigh the fighter)
            cl = sc.get("clusters", {})
            on_screen = any(abs((b - a) - (end.p2_x - end.p1_x)) < 12
                            for a in cl.get("P1", []) for b in cl.get("P2", []))
            if not on_screen and stick and near:
                # colour alone is ambiguous at stage edges (orange paint, an orange sky, a view
                # scrolled vertically): check by motion instead (each fighter's changed pixels
                # move +-20 px with a +-20 px write, gap = records' gap), then both back at target
                on_screen, r["shift_check"] = m.shift_check(*tx)
                back = m.ticks(3)
                r["shift_back"] = _stuck_at(back, tx)
                on_screen = on_screen and r["shift_back"]
            r.update(target=[round(x, 1) for x in tx], cam=round(cam, 1), stick_first=stick1,
                     first3=self.first3, alive={"P1": a1, "P2": a2}, alive_dx={"P1": d1, "P2": d2}, stick=stick,
                     near=near, keys_released=held_free, on_screen=on_screen,
                     screen_x={w: sc[w] for w in WHO}, clusters=sc.get("clusters"), pixels=sc["n"], recs={w: hex(m.rec[w]) for w in WHO},
                     masters={w: hex(m.masters[m.rec[w]]) for w in WHO},
                     master_offset={w: m.offset[m.rec[w]] for w in WHO})
            floor = abs(end.p1_y - pe.p1_y) < 2      # the floor the probe found: no step climbed
            r.update(orig=[round(x, 1) for x in orig], same_floor_as_before=floor)
            r["ok"] = bool(stick1 and a1 and a2 and stick and near and held_free and on_screen and floor)
            tries.append(r)
            if r["ok"]:
                self.home.setdefault(room, round((tx[0] + tx[1]) / 2, 1))
                break
            m.place(*orig); m.ticks(20)          # back to where both stood free (out of a step)
            # both sprites drawn but their gap is not the records' gap: one record is an
            # attached object (arm/sword) that answers the keys too. The camera follows the
            # fighters, so which one cannot be told from the screen: re-identify both.
            wrong = list(WHO) if (not on_screen and None not in (sc["P1"], sc["P2"])) else []
            r["not_body"] = wrong
            for w in wrong:
                m.rec[w] = None
            for who, ok in (("P1", a1), ("P2", a2)):
                if who in wrong:
                    continue
                if not ok:      # stuck in a step (moved by the next try) or dead: 2 strikes
                    self.strikes[m.rec[who]] = self.strikes.get(m.rec[who], 0) + 1
                    if self.strikes[m.rec[who]] >= 2:
                        m.dead.add(m.rec[who])
        self.reset_info = tries
        assert tries[-1]["ok"], f"reset failed 5 times: {json.dumps(tries)}"
        self.recs0 = set(m.type_records())
        self.st0 = self.last = end
        self.steps, self.tick0 = 0, end.tick
        self.still = {w: 0 for w in WHO}
        self.false_freezes, self.rejected = [], {}
        # per player: steps with exactly one of its walk keys held, the x moved along that key
        # in those steps (sum), and how many of them moved >0.5 px the key's way
        self.motion = {w: {"key_steps": 0, "dir_dx": 0.0, "moved_steps": 0} for w in WHO}
        self.prev_dir = {w: 0 for w in WHO}
        self.kill_frame = None
        self.play_from = self.play_to = len(m.room_log)   # room samples taken during play
        return self._obs(end)

    def _obs(self, st):
        v = [st.p1_x / 1000, (192 - st.p1_y) / 100, st.p1_facing, (st.p2_x - st.p1_x) / 300,
             (192 - st.p2_y) / 100, st.p2_facing, st.p1_anim / 500, st.p2_anim / 500]
        return np.clip(np.array(v, np.float32), -2, 2)

    # ------------------------------------------------------------ step
    def step(self, a1, a2):
        want = {"P1": ACTIONS[int(a1)], "P2": ACTIONS[int(a2)]}
        hold = {KEYS[w][a] for w in WHO for a in want[w] if a in HOLD}
        taps = [KEYS[w][a] for w in WHO for a in want[w] if a not in HOLD]
        lines = [f"ku {k}" for k in self.held - hold] + [f"kd {k}" for k in hold - self.held]
        self.m.send(lines + [f"kd {k}" for k in taps])
        self.held = hold
        x0 = {"P1": self.last.p1_x, "P2": self.last.p2_x}
        frozen = None
        samples = self.m.ticks(2)
        if taps:
            self.m.send([f"ku {k}" for k in taps])
        samples += self.m.ticks(STEP_TICKS - 2)
        for st in samples:
            for w in WHO:
                self.still[w] = self.still[w] + 1 if _rec(st, w) == _rec(self.last, w) else 0
            self.last = st
            cands = [w for w in WHO if self.still[w] >= FREEZE_TICKS
                     and self.rejected.get(w) != _rec(st, w)]   # same freeze already refuted
            if len(cands) == 1 and not frozen:
                frozen = cands[0]
        self.steps += 1
        self.play_to = len(self.m.room_log)
        for w in WHO:
            d = ("right" in want[w]) - ("left" in want[w])
            held_on, self.prev_dir[w] = d and d == self.prev_dir[w], d
            # walking INTO the other fighter at blade contact is stopped by the game; such a step
            # says nothing about the keys, so it is counted apart (blocked_steps), not as a test
            gap = x0["P2"] - x0["P1"] if w == "P1" else x0["P1"] - x0["P2"]
            if held_on and d * gap > 0 and abs(gap) < CONTACT_PX:
                self.motion[w]["blocked_steps"] = self.motion[w].get("blocked_steps", 0) + 1
                held_on = False
            if held_on:              # same walk key as the step before: past the turn-around
                dx = (self.last.p1_x if w == "P1" else self.last.p2_x) - x0[w]
                mo = self.motion[w]
                mo["key_steps"] += 1; mo["dir_dx"] += d * dx; mo["moved_steps"] += d * dx > 0.5
        info = {"tick": self.last.tick, "outcome": "undecided"}
        if frozen:
            if getattr(self, "kill_frame_hook", None):     # screenshot the freeze before confirming
                self.kill_frame = self.kill_frame_hook(self.ep, frozen, self.last.tick)
            ev = self._confirm(frozen)
            if ev["dead"]:
                other = "P2" if frozen == "P1" else "P1"
                ev2 = self._confirm(other, wait=1.5)   # double kill check
                info["outcome"] = "draw" if ev2["dead"] else other
                return self._end(info, {frozen: ev, other: ev2})
            self.false_freezes.append(ev)
            self.rejected[frozen] = ev["frozen_rec"]
        if min(self.still.values()) >= 90:          # both stale (room change): give up early
            return self._end(info, {"both_frozen_ticks": min(self.still.values())})
        if self.steps >= MAX_STEPS:
            return self._end(info, {})
        return self._obs(self.last), False, info

    def _confirm(self, who, wait=RESPAWN_S):
        """(b) a new fighter-type record answering to who's keys; old record tested for the log."""
        m = self.m
        m.release_all(); self.held = set()
        old, frozen_rec = m.rec[who], _rec(self.last, who)
        other = m.rec["P2" if who == "P1" else "P1"]
        ev = {"who": who, "record": hex(old), "frozen_rec": frozen_rec, "dead": False,
              "freeze_tick": self.last.tick, "new_record": None, "respawn_s": None}
        t0 = time.time()
        while time.time() - t0 < wait:
            recs = m.type_records()
            new = [a for a in recs if a not in self.recs0 and a not in m.dead and a not in (old, other)]
            if new:
                new.sort(key=lambda a: -recs[a][1])      # lowest first: the body
                ev["new_record"], ev["respawn_s"] = hex(new[0]), round(time.time() - t0, 2)
                break
            time.sleep(0.3)
        if ev["new_record"]:
            for a in new[:4]:
                ok_new, ev["new_dx"] = m.answers(a, who)
                if ok_new:
                    ev["new_record"] = hex(a)
                    break
            ok_old, ev["old_dx"] = m.answers(old, who)
            ev["new_answers"], ev["old_answers"] = ok_new, ok_old
            ev["dead"] = ok_new      # (c) logged only: a reused old record can answer too
            if ev["dead"]:
                m.dead.add(old); m.rec[who] = int(ev["new_record"], 16)
            else:
                self.recs0.add(int(ev["new_record"], 16))
        elif DEATH_ANIMS[0] <= frozen_rec[3] <= DEATH_ANIMS[1]:
            # no respawn yet (it waits for the leader to advance, e.g. at a room end): a
            # frozen record in a death anim that ignores its own keys is a corpse
            ok_old, ev["old_dx"] = m.answers(old, who)
            ev["old_answers"], ev["branch"] = ok_old, "corpse"
            ev["dead"] = not ok_old
            if ev["dead"]:
                m.dead.add(old); m.rec[who] = None
        if ev["dead"] and ev["new_record"]:
            ev["branch"] = "respawn"
        self.last = m.track()
        return ev

    def _end(self, info, evidence):
        self.m.release_all(); self.held = set()
        after = self.m.track()
        row = {"episode": self.ep, "seed": self.seed, "outcome": info["outcome"],
               "steps": self.steps, "ticks": self.last.tick - self.tick0,
               "reset": self.reset_info, "before": _brief(self.st0),
               "at_end": _brief(self.last), "after": _brief(after),
               "records_after": {w: self.m.rec[w] and hex(self.m.rec[w]) for w in WHO},
               "evidence": evidence, "false_freezes": self.false_freezes,
               "rule": f"one fighter frozen>={FREEZE_TICKS} ticks + (new record answers its keys "
                       f"| death anim {DEATH_ANIMS} and old record ignores its keys)",
               "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
        rooms = [r for _t, r in self.m.room_log]
        rle = []
        for r in rooms:
            if rle and rle[-1][0] == r:
                rle[-1][1] += 1
            else:
                rle.append([r, 1])
        ticks = [t for t, _r in self.m.room_log]
        play = [t for t, _r in self.m.room_log[self.play_from:self.play_to]]
        row.update(rooms_rle=rle, room_samples=len(rooms),
                   room_tick_span=(ticks[-1] - ticks[0] + 1) if ticks else 0,
                   play_room_samples=len(play),
                   play_tick_span=(play[-1] - play[0] + 1) if play else 0,
                   motion={w: dict(v, dir_dx=round(v["dir_dx"], 1)) for w, v in self.motion.items()},
                   reset_alive=self.reset_info[-1].get("alive"),
                   reset_alive_dx=self.reset_info[-1].get("alive_dx"),
                   kill_frame=self.kill_frame)
        if getattr(self, "row_hook", None):
            row = self.row_hook(row)
        info["row"] = row
        with open(self.log, "a") as f:
            f.write(json.dumps(row) + "\n")
        self.ep += 1
        info["evidence"] = evidence
        return self._obs(after), True, info
