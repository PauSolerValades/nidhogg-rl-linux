"""Adapter: live Nidhogg (nidenv.Env, two fighters) as a one-player env for train/train.py.

  python3 train/train.py --env nidtrain_env --seed 0 --ckpt_every 10

The trainer drives P1 (yellow) with an action index 0..6 (nidenv.ACTIONS[0..6]). P2 (orange)
is the scripted 'partner' from ~/nf-loop2/run_eps.py, copied verbatim below, drawing from a
numpy generator seeded once per episode (the trainer's env.seed(ep_seed) if it called it,
else base seed + episode counter, as run_eps.py does with SEED + e).

Reward: 0 on every non-terminal step; at the end +1 if nidenv says 'P1', -1 if 'P2',
0 for 'draw' or 'undecided'. info['outcome'] is mapped to env_iface's vocabulary
(P1 -> 'win', P2 -> 'loss', else unchanged); nidenv's own label stays in info['nid_outcome'].
Raw per-episode records: nidenv writes $NIDFARM/episodes.jsonl; this adapter also appends one
line per episode to $NIDFARM/train_eps.jsonl (trainer episode index, seed, reward, ticks).
"""
import json, os, sys, threading, time
from pathlib import Path

import numpy as np

import validity

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))                  # ~/nidhogg-main
FARM = Path(os.environ.get("NIDFARM") or (Path.home() / ".nidfarm"))
OUTCOME = {"P1": "win", "P2": "loss"}
REWARD = {"P1": 1.0, "P2": -1.0}


def partner(dx, rng, dy=0.0):              # dx = P1 - P2   (verbatim from run_eps.py)
    toward = 2 if dx > 0 else 1
    if abs(dy) > 10 and rng.random() < 0.25:
        return 3                            # different floor: jump
    if rng.random() < 0.10:
        return 0
    if abs(dx) > 40 + rng.integers(-8, 9):
        return toward
    if rng.random() < 0.20:
        return int(rng.choice([5, 6]))
    return 8 if dx > 0 else 7


def partner_v3(dx, rng, dy, st):
    """Scripted P2 that a stationary P1 cannot farm (NID_PARTNER=v3, version v3e). dx = P1 - P2.
    A walker dies on a held sword at about 32 px and walking slides on ~9 px per step even after
    the key is released. Inside 75 px: brake (press away) while closing faster than 3 px/step,
    otherwise tap toward; below 50 px strike standing (random stance, thrust, idle); below 36 px
    back off 2-3 steps."""
    d, toward = abs(dx), (2 if dx > 0 else 1)
    away = 3 - toward
    v = st.get("prev", d) - d                    # closing speed, px per step
    st["prev"] = d
    if st.get("retreat", 0) > 0:
        st["retreat"] -= 1
        return away
    if abs(dy) > 10 and rng.random() < 0.25:
        return 3
    if d < 36:
        st["retreat"] = int(rng.integers(2, 4))
        return away
    if d < 75 and v > 3:
        return away                              # brake
    if d < 50:
        st["n"] = st.get("n", 0) + 1
        return (int(rng.choice([5, 6, 0])), 4, 0)[st["n"] % 3]
    if d < 75:
        return toward if v <= 1 else 0
    return toward if rng.random() > 0.1 else 0


PARTNER = os.environ.get("NID_PARTNER", "v1")
MAX_TICKS = int(os.environ.get("NID_MAX_TICKS", "0"))      # 0 = only nidenv's step cap


def partner_random(rng, st):
    """Random P2: uniform action 0..6, held for 4-8 steps."""
    if st.get("hold", 0) <= 0:
        st["a"], st["hold"] = int(rng.integers(0, 7)), int(rng.integers(4, 9))
    st["hold"] -= 1
    return st["a"]


def reward_v1(row):
    """+1 P1 killed P2, -1 P1 died, 0 no kill; minus up to 0.1 for P1 standing still."""
    kills = row.get("kills") or []
    who = [k["who"] for k in kills]
    kill = 1.0 if who == ["P2"] else (-1.0 if who == ["P1"] else 0.0)
    mo = (row.get("motion") or {}).get("P1") or {}
    still = -0.1 * (1 - min(1.0, mo.get("moved_steps", 0) / 5))
    return {"kill_term": kill, "still_term": round(still, 4), "reward_v1": round(kill + still, 4)}


def annotate_with_timeout(row):
    """validity.annotate, plus reason 'timeout' when the round hit nidenv's step cap unkilled."""
    import nidenv
    row = validity.annotate(row)
    if row.get("outcome") == "undecided" and (row.get("steps", 0) >= nidenv.MAX_STEPS
                                               or "timeout_ticks" in (row.get("evidence") or {})):
        row["invalid_reasons"] = row["invalid_reasons"] + ["timeout"]
        row["valid"] = False
    return row


def fitness(valid, raw, motion):
    """Training fitness; logged term by term. An invalid episode is -1 (never 0, never a win)."""
    win = (1.0 if raw == "P1" else -1.0) if valid else -1.0
    mo = motion or {}
    frac = min(1.0, mo.get("moved_steps", 0) / 5, mo.get("dir_dx", 0.0) / 40)
    move = 0.5 * max(0.0, frac)
    return {"win_term": win, "motion_term": round(move, 4), "fitness": round(win + move, 4)}


class TrainEnv:
    def __init__(self, seed=0, inst=0, env=None, log=None):
        if env is None:
            shim = FARM / "shim.py"                       # remaps fixed /tmp names first
            if shim.exists():
                sys.path.insert(0, str(FARM)); import shim as _  # noqa: F401
            import nidenv
            env = nidenv.Env(seed=seed, inst=inst)
            env.row_hook = annotate_with_timeout  # (a)-(d) on every row before it is logged
        self.env, self.base, self.count = env, seed, 0
        self.inst, self.need_restart = inst, False
        self.next_seed, self.log = None, log or FARM / "train_eps.jsonl"
        self.run_id = time.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
        self.frames_valid = 0               # valid episodes that have a kill-tick screenshot
        self.env.kill_frame_hook = self._kill_frame
        # stall watchdog: no episode progress for STALL_S -> exit non-zero (train.sh logs rc)
        self.last_progress = time.time()
        threading.Thread(target=self._watchdog, daemon=True).start()

    STALL_S = 900

    def _watchdog(self):
        while True:
            time.sleep(30)
            if time.time() - self.last_progress > self.STALL_S:
                print(f"STALL: no step or reset finished for {self.STALL_S} s; exiting 70",
                      file=sys.stderr, flush=True)
                os._exit(70)

    def _kill_frame(self, ep, who, tick):
        """Screenshot at the freeze that starts a death check, until 5 valid episodes have one."""
        if self.frames_valid >= 5:
            return None
        from nidmem import s
        name = f"kill_ep{ep:04d}_{who}_t{tick}"
        s.frame(self.inst, name)
        return name + ".png"

    def seed(self, s):
        """Called by the trainer before each episode: both members of a pair share a partner."""
        self.next_seed = int(s)

    def reset(self):
        s = self.next_seed if self.next_seed is not None else self.base + self.count
        self.next_seed, self.ep_seed = None, s
        self.rng = np.random.default_rng(s)
        self.pstate = {}
        self.env.seed = s                                   # lands in nidenv's episode row
        self.steps = 0
        self.last_progress = time.time()
        if self.need_restart:
            self._restart("previous episode left the arena rooms")
        try:
            return self.env.reset()
        except (AssertionError, RuntimeError) as e:   # reset could not settle or game hung: restart once
            self._restart(str(e))
            self.env.seed = s
            return self.env.reset()

    def _abort(self, err):
        """Game state lost mid-episode: log an invalid row (never a win or loss) and restart."""
        row = {"episode": getattr(self.env, "ep", -1), "seed": self.ep_seed, "outcome": "aborted",
               "steps": self.steps, "valid": False, "invalid_reasons": [f"aborted: {err[:300]}"],
               "rule": validity.RULE, "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(self.env.log, "a") as f:
            f.write(json.dumps(row) + "\n")
        self.env.ep += 1
        with open(self.log, "a") as f:
            f.write(json.dumps({"run": self.run_id, "i": self.count, "seed": self.ep_seed,
                                "outcome": "aborted", "reward": 0.0, "steps": self.steps,
                                **fitness(False, "aborted", None),
                                "valid": False, "invalid_reasons": row["invalid_reasons"],
                                "partner": PARTNER, "rule": validity.RULE,
                                "t": row["t"]}) + "\n")
        self.count += 1
        self.need_restart = True
        return np.zeros(8, np.float32), 0.0, True, {"outcome": "invalid", "valid": False,
                                                     "nid_outcome": "aborted",
                                                     **fitness(False, "aborted", None)}

    def _restart(self, why):
        """Restart this farm's game instance (nidlinux.clean_farm/stop_id only touch processes
        whose environment holds $NIDFARM) and re-enter a local match with the measured recipe.
        Logged to $NIDFARM/restarts.jsonl with the reason."""
        import nidenv
        from nidmem import n, s
        t0 = time.time()
        n.start_ids([self.inst])
        pid = None
        for _ in range(40):
            pid = n._game_pid(self.inst)
            if pid and n.ping(pid):
                break
            time.sleep(10)
        time.sleep(8)
        entered = s.enter_match_v2(self.inst)
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": self.run_id, "i": self.count,
               "why": why[:3000], "pid": pid, "entered": entered, "secs": round(time.time() - t0)}
        with open(FARM / "restarts.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
        assert entered, f"restart did not reach a live match: {rec}"
        old = self.env
        self.env = nidenv.Env(seed=old.seed, inst=self.inst, log=old.log)
        self.env.ep, self.env.row_hook = old.ep, old.row_hook
        self.env.kill_frame_hook = old.kill_frame_hook
        self.last_progress = time.time()
        self.need_restart = False

    def step(self, a):
        assert 0 <= int(a) <= 6, a
        last = self.env.last
        dx, dy = last.p2_x - last.p1_x, last.p2_y - last.p1_y
        a2 = (partner_v3(-dx, self.rng, dy, self.pstate) if PARTNER == "v3"
              else partner_random(self.rng, self.pstate) if PARTNER == "random"
              else partner(-dx, self.rng, dy))
        try:
            obs, done, info = self.env.step(int(a), a2)
        except (AssertionError, RuntimeError) as e:
            return self._abort(f"{type(e).__name__}: {e}")
        if not done and MAX_TICKS and self.env.last.tick - self.env.tick0 >= MAX_TICKS:
            obs, done, info = self.env._end({"tick": self.env.last.tick, "outcome": "undecided"},
                                            {"timeout_ticks": MAX_TICKS})
        self.steps += 1
        self.last_progress = time.time()
        if not done:
            return obs, 0.0, False, info
        raw = info["outcome"]
        row = info.pop("row", {})
        valid = bool(row.get("valid"))
        self.frames_valid += bool(valid and row.get("kill_frame"))
        # left the arenas (match over, menu): the next reset would run in a menu
        self.need_restart = any(x.startswith("a: non-arena") for x in row.get("invalid_reasons") or [])
        r = REWARD.get(raw, 0.0) if valid else 0.0     # an invalid episode is never a win/loss
        fit = dict(fitness(valid, raw, (row.get("motion") or {}).get("P1")), **reward_v1(row),
                   ticks=row.get("ticks"), rooms=row.get("rooms_rle"),
                   kills=row.get("kills"))
        info = dict(info, nid_outcome=raw, outcome=OUTCOME.get(raw, raw) if valid else "invalid", **fit,
                    valid=valid)
        with open(self.log, "a") as f:
            f.write(json.dumps({"run": self.run_id, "i": self.count, "seed": self.ep_seed,
                                "outcome": raw, "reward": r, "steps": self.steps, "valid": valid,
                                "invalid_reasons": row.get("invalid_reasons"),
                                "partner": PARTNER, "rule": row.get("rule"), **fit,
                                "motion_source": row.get("motion_source"),
                                "nid_episode": getattr(self.env, "ep", 0) - 1,
                                "t": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        self.count += 1
        return obs, r, True, info


def make(seed=0):
    return TrainEnv(seed)
