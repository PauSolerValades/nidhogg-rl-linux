"""Evaluate a policy against the CPU: play N rounds, report round/match wins.

Writes /tmp/nid_eval.json and touches out/BEATS_CPU when the policy wins matches
consistently (>= 60% of matches over the sample).
"""
import json
import os
import sys
import time

import numpy as np

import neuro
import train_state as TS
import train_win as W

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "BEATS_CPU")
GOAL_X = W.GOAL_X
GOAL_X_OPP = W.GOAL_X_OPP


def evaluate(mgr, weights, rounds=12, seed=999):
    w = np.array(weights, dtype=float)
    rng = np.random.default_rng(seed)
    if not mgr.ensure_match():
        return None
    won = lost = 0
    me_crossed = them_crossed = False
    t0 = time.time()
    deadline = t0 + 240
    while won + lost < rounds and time.time() < deadline:
        st = W.read_state(mgr.iid)
        if st is None:
            time.sleep(0.05)
            continue
        if st["me_x"] >= GOAL_X and not me_crossed:
            won += 1
            me_crossed = True
            print(f"  ROUND WON ({won}-{lost})", flush=True)
        elif st["me_x"] < GOAL_X - 200:
            me_crossed = False
        if st["them_x"] <= GOAL_X_OPP and not them_crossed:
            lost += 1
            them_crossed = True
            print(f"  round lost ({won}-{lost})", flush=True)
        elif st["them_x"] > GOAL_X_OPP + 200:
            them_crossed = False
        code = neuro.decide(w, st, rng)
        if code:
            mgr.press(code)
        time.sleep(0.02)
    return {"rounds_won": won, "rounds_lost": lost,
            "win_rate": won / max(1, won + lost)}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/nid_best_win.json"
    if not os.path.exists(path):
        print("no policy to evaluate:", path)
        return
    d = json.load(open(path))
    with open(TS.PREFS, "w") as f:
        f.write(open(TS.MUTED_PREFS).read())
    mgr = TS.InstanceManager(iid=0)
    mgr.launch()
    time.sleep(TS.BOOT_WAIT)
    res = evaluate(mgr, d["weights"])
    mgr.close()
    time.sleep(1)
    with open(TS.PREFS, "w") as f:
        f.write(open(TS.PRISTINE_PREFS).read())
    json.dump(res or {}, open("/tmp/nid_eval.json", "w"), indent=1)
    print("eval:", res, flush=True)
    if res and res["win_rate"] >= 0.6 and res["rounds_won"] >= 6:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        open(OUT, "w").write(json.dumps(res))
        print("BEATS_CPU flag written", flush=True)


if __name__ == "__main__":
    main()
