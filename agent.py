"""Genetic algorithm over a small policy, trained directly on the real game.

An "individual" plays for a fixed window inside a live match (rounds continue on
their own, so there is no menu cost between individuals). Fitness comes from the
only events we can see: our fighter's spawn-jump (death) and the CPU's.

Policy parameters (all evolve):
    engage      distance at which we stop closing and attack      (px)
    aggr        probability of attacking when in range            (0-1)
    aim         sword height held: 0 low, 1 mid, 2 high           (0-2)
    jump        probability of jumping while closing               (0-1)
    retreat     probability of backing off after a death            (0-1)
"""
import json
import random
import time

import nav
import perceive

KEYS = {"left": 65, "right": 68, "up": 87, "down": 83, "attack": 70, "jump": 71}
LOG = "/tmp/nid_train.jsonl"


def press(code, hold=0.06):
    open("/tmp/nid_keys.txt", "w").write(f"{code}\n")
    time.sleep(hold)


def act(params, obs, rng):
    """Choose one action from the observation. Returns the key code."""
    dx = obs["dx"]
    if dx is None:
        return KEYS["right"]
    away = dx > 0                    # opponent to our right -> we must go right
    if abs(dx) > params["engage"]:
        if rng.random() < params["jump"]:
            return KEYS["jump"]
        return KEYS["right"] if away else KEYS["left"]
    if rng.random() < params["aggr"]:
        aim = ["down", "up", "up"][params["aim"]]
        press(KEYS[aim], 0.02)
        return KEYS["attack"]
    if rng.random() < params["retreat"]:
        return KEYS["left"] if away else KEYS["right"]
    return KEYS["up"] if params["aim"] >= 1 else KEYS["down"]


def run_window(params, seconds=20.0, sample=0.12, seed=0):
    rng = random.Random(seed)
    tr = perceive.Tracker()
    trace = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        img = nav.capture()
        if img is None:
            time.sleep(0.05)
            continue
        obs = tr.update(img)
        trace.append([round(obs["p1"] or -1), round(obs["p2"] or -1)])
        press(act(params, obs, rng))
        time.sleep(sample)
    mine = tr.events.count("my_death")
    theirs = tr.events.count("their_death")
    fit = 3.0 * theirs - 2.0 * mine
    return {"fitness": fit, "my_deaths": mine, "their_deaths": theirs,
            "trace": trace, "params": params}


def rand_params(rng):
    return {"engage": rng.uniform(60, 220),
            "aggr": rng.uniform(0.2, 0.95),
            "aim": rng.randrange(3),
            "jump": rng.uniform(0.0, 0.5),
            "retreat": rng.uniform(0.0, 0.6)}


def mutate(p, rng, scale=0.35):
    q = dict(p)
    q["engage"] = max(30, min(320, q["engage"] + rng.gauss(0, 40 * scale)))
    q["aggr"] = min(1.0, max(0.05, q["aggr"] + rng.gauss(0, 0.15 * scale)))
    q["jump"] = min(0.8, max(0.0, q["jump"] + rng.gauss(0, 0.12 * scale)))
    q["retreat"] = min(0.9, max(0.0, q["retreat"] + rng.gauss(0, 0.12 * scale)))
    if rng.random() < 0.25 * scale:
        q["aim"] = rng.randrange(3)
    return q


def crossover(a, b, rng):
    return {k: (a[k] if rng.random() < 0.5 else b[k]) for k in a}


def log(rec):
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
