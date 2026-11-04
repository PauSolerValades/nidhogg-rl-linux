"""Parallel neuroevolution over N hidden Nidhogg instances.

Per-instance threads: each game plays a different network at the same time
(island parallelism). Generations breed from the shared fitness ranking.

usage: python train_neuro.py --instances 4 --gens 8 --pop 16 --window 25
"""
import argparse
import json
import os
import random
import threading
import time

import numpy as np

import neuro
import train_state as TS

LOG = "/tmp/nid_neuro_train.jsonl"
LOCK = threading.Lock()


def read_state(iid):
    try:
        vals = open(TS.STATE.format(iid)).read().split()
        if len(vals) < 6:
            return None
        o154x, o154y, y242x, y242y, h1, h2 = (float(v) for v in vals[:6])
        if not (h1 and h2):
            return None
        return {"them_x": o154x, "them_y": o154y, "me_x": y242x, "me_y": y242y}
    except (OSError, ValueError):
        return None


def play(mgr, w, seconds, seed, tag):
    """One episode: a fixed window inside a live match."""
    if not mgr.ensure_match():
        return {"fitness": -100.0, "trace": [], "tag": tag, "no_match": True}

    rng = np.random.default_rng(seed)
    t0 = time.time()
    mine = theirs = 0
    trace = []
    best_adv = 0.0
    start_me = start_them = None
    best_me = worst_them = None
    prev = None
    resets = 0
    while time.time() - t0 < seconds:
        st = read_state(mgr.iid)
        if st is None:
            time.sleep(0.05)
            continue
        if start_me is None:
            start_me = st["me_x"]; start_them = st["them_x"]
            best_me = st["me_x"]; worst_them = st["them_x"]
        best_me = max(best_me, st["me_x"])
        worst_them = min(worst_them, st["them_x"])
        if prev is not None:
            me_jump = abs(st["me_x"] - prev["me_x"]) > 300
            them_jump = abs(st["them_x"] - prev["them_x"]) > 300
            if me_jump and them_jump:
                resets += 1
                start_me, start_them = st["me_x"], st["them_x"]
                best_me, worst_them = st["me_x"], st["them_x"]
            elif me_jump:
                mine += 1
            elif them_jump:
                theirs += 1
        prev = st
        trace.append([round(time.time() - t0, 2), round(st["me_x"]), round(st["them_x"])])
        code = neuro.decide(w, st, rng)
        if code:
            mgr.press(code)
        time.sleep(0.05)
    advance = ((best_me or 0) - (start_me or 0)) - ((start_them or 0) - (worst_them or 0))
    fitness = 3.0 * theirs - 2.0 * mine + advance / 100.0
    return {"fitness": fitness, "advance": advance, "my_deaths": mine,
            "their_deaths": theirs, "rounds": resets,
            "trace": trace, "tag": tag, "weights": w.tolist()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, default=4)
    ap.add_argument("--gens", type=int, default=8)
    ap.add_argument("--pop", type=int, default=16)
    ap.add_argument("--window", type=float, default=25.0)
    ap.add_argument("--seed", type=int, default=77)
    args = ap.parse_args()

    os.environ["NID_ORDERS"] = "1"
    os.system('pkill -f "MacOS/Nidhogg" 2>/dev/null')
    os.system('pkill -f train_neuro.py 2>/dev/null')
    time.sleep(2)
    with open(TS.PREFS, "w") as f:
        f.write(open(TS.MUTED_PREFS).read())

    rng = np.random.default_rng(args.seed)
    pop = neuro.Population(size=args.pop, seed=args.seed)
    mgrs = [TS.InstanceManager(iid=i) for i in range(args.instances)]
    for mgr in mgrs:
        mgr.launch()
    time.sleep(TS.BOOT_WAIT)
    for mgr in mgrs:
        mgr.run_entry()
    for mgr in mgrs:
        mgr.wait_for_match()
    time.sleep(4)

    best_overall = None
    for gen in range(args.gens):
        results = []
        threads = []
        for i, w in enumerate(pop.W):
            mgr = mgrs[i % len(mgrs)]
            tag = f"g{gen}i{i}"
            # stagger starts so a single launch storm does not collide
            time.sleep(0.15)
            th = threading.Thread(target=lambda m=mgr, ww=w, t=tag: results.append(play(m, ww, args.window, gen * 997 + i, t)))
            th.start()
            threads.append(th)
        for th in threads:
            th.join()
        fit = [r["fitness"] for r in results]
        good = [r for r in results if not r.get("no_match")]
        if good:
            pop.next_gen(fit)
            best = max(results, key=lambda r: r["fitness"])
            if best_overall is None or best["fitness"] > best_overall["fitness"]:
                best_overall = best
            print(f"== gen {gen} best {max(fit):.2f} mean {np.mean(fit):.2f} "
                  f"n={len(fit)}", flush=True)
            with open("/tmp/nid_neuro_history.json", "w") as f:
                json.dump({"gens": [{"gen": gen, "best": float(max(fit)),
                                     "mean": float(np.mean(fit))}],
                           "best_fitness": float(best_overall["fitness"])}, f)
            for r in results:
                with open(LOG, "a") as f:
                    f.write(json.dumps(r) + "\n")
        else:
            print(f"== gen {gen}: all episodes failed", flush=True)

    if best_overall is not None:
        with open("/tmp/nid_best_neuro.json", "w") as f:
            json.dump({"fitness": best_overall["fitness"],
                       "weights": best_overall["weights"]}, f)
        print("best fitness:", best_overall["fitness"], flush=True)
    for mgr in mgrs:
        mgr.close()
    with open(TS.PREFS, "w") as f:
        f.write(open(TS.PRISTINE_PREFS).read())
    print("done, prefs restored", flush=True)


if __name__ == "__main__":
    main()
