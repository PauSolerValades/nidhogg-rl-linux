"""Parallel GA across N hidden Nidhogg instances (state from memory, no vision).

Every instance is headless: the window is ordered out of the compositor
(NID_ORDERS), the game is muted through its own prefs + in-process gain, and the
Mac's volume is never touched. State comes from the instance table the injected
dylib publishes; capture is never used.

Islands: each instance runs a DIFFERENT individual at the same time (real
parallel training of multiple policies). Fitness results are collected centrally
and the GA breeds after each generation.

usage: python train_multinode.py --instances 4 --gens 10 --pop 16 --window 25
"""
import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import agent as A
import train_state as TS

RESULTS_LOCK = threading.Lock()
RESULTS = []


def worker_boot(mgr, log=print):
    """Launch one hidden instance and get it into a live match."""
    mgr.launch()
    time.sleep(TS.BOOT_WAIT)
    mgr.run_entry()
    ok = mgr.wait_for_match()
    log(f"[boot {mgr.iid}] match live: {ok}")
    return ok


def worker_task(mgr, params, seconds, seed, tag, log=print):
    """Run one individual on this instance's game."""
    # keep the clock multiplier applied (a restarted process resets it)
    try:
        with open(TS.KEYS.format(mgr.iid).replace("keys", "speed"), "w") as f:
            f.write("300\n")
    except OSError:
        pass
    if not mgr.ensure_match():
        rec = TS.failed_record(params, tag)
        rec["instance"] = mgr.iid
        rec["no_match"] = True
        return rec
    rec = TS.run_individual(mgr, params, seconds, seed, tag)
    rec["instance"] = mgr.iid
    with RESULTS_LOCK:
        RESULTS.append(rec)
        TS.append_record(rec)
    log(f"  {tag} (inst {mgr.iid}): fit={rec['fitness']:.2f} "
        f"adv={rec.get('advance', 0):.0f} appr={rec.get('approach', 0):.0f}")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, default=4)
    ap.add_argument("--gens", type=int, default=10)
    ap.add_argument("--pop", type=int, default=16)
    ap.add_argument("--window", type=float, default=25.0)
    ap.add_argument("--seed", type=int, default=101)
    args = ap.parse_args()

    # headless: hide the windows entirely (verified: 0 on-screen frames,
    # game keeps stepping; capture is never needed in this pipeline)
    os.environ["NID_ORDERS"] = "1"

    here = os.path.dirname(os.path.abspath(__file__))
    # clean slate
    os.system('pkill -f "MacOS/Nidhogg" 2>/dev/null')
    os.system('pkill -f train_state.py 2>/dev/null')
    os.system('pkill -f train_multinode.py 2>/dev/null')
    time.sleep(2)
    with open(TS.PREFS, "w") as f:
        f.write(open(TS.MUTED_PREFS).read())

    managers = [TS.InstanceManager(iid=i) for i in range(args.instances)]
    log = print
    for mgr in managers:
        worker_boot(mgr, log=log)

    rng = random.Random(args.seed)
    pop = [A.rand_params(rng) for _ in range(args.pop)]
    history = []
    best_overall = None

    for gen in range(args.gens):
        gen_t0 = time.time()
        tasks = []
        for i, params in enumerate(pop):
            mgr = managers[i % len(managers)]
            tasks.append((mgr, params, args.window,
                          args.seed + gen * 977 + i, f"g{gen}i{i}"))
        with ThreadPoolExecutor(max_workers=len(managers)) as pool:
            futures = [pool.submit(worker_task, *t, log=log) for t in tasks]
            recs = [f.result() for f in futures]
        recs = [r for r in recs if r is not None]
        good = [r for r in recs if not r.get("no_match")]
        if not good:
            log(f"== gen {gen}: no usable episodes, skipping")
            continue
        good.sort(key=lambda r: -r["fitness"])
        best = good[0]
        mean = statistics.mean(r["fitness"] for r in good)
        history.append({"gen": gen, "best": best["fitness"], "mean": mean,
                        "n": len(good),
                        "recoveries": sum(m.match_recoveries for m in managers),
                        "restarts": sum(m.hard_restarts for m in managers)})
        log(f"== gen {gen} best {best['fitness']:.2f} mean {mean:.2f} "
            f"({time.time()-gen_t0:.0f}s)")
        if best_overall is None or best["fitness"] > best_overall["fitness"]:
            best_overall = best
        with open("/tmp/nid_multinode_history.json", "w") as f:
            json.dump({"history": history,
                       "best_params": best_overall["params"],
                       "best_fitness": best_overall["fitness"]}, f, indent=1)

        elite = [r["params"] for r in good[: max(2, len(good) // 4)]]
        nxt = list(elite)
        while len(nxt) < args.pop:
            a, b = rng.sample(elite, 2) if len(elite) > 1 else (elite[0], elite[0])
            nxt.append(A.mutate(A.crossover(a, b, rng), rng))
        pop = nxt

    log(f"BEST fitness {best_overall['fitness']:.2f} params "
        f"{json.dumps(best_overall['params'])}")

    # cleanup: stop all owned games, restore the user's real settings
    for mgr in managers:
        mgr.close()
    time.sleep(1.5)
    with open(TS.PREFS, "w") as f:
        f.write(open(TS.PRISTINE_PREFS).read())
    log("all instances stopped; pristine prefs restored")


if __name__ == "__main__":
    main()
