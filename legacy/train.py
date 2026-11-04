"""Train a policy on the real game: one individual per match, GA across matches.

Episode = one Nidhogg match. It ends on the stats screen (WINNER / KILLS /
SUICIDES / PRESS ENTER CONTINUE). Reward comes from the deaths we can actually
see during the match; the stats screen is kept as an image for auditing.

Run:  python train.py --gens 3 --pop 6 --match-sec 165
"""
import argparse
import json
import os
import random
import time

import numpy as np
from scipy import ndimage

import agent as A
import nav
import perceive

LOG = "/tmp/nid_train.jsonl"
SHOTS = "/tmp/nid_stats"
os.makedirs(SHOTS, exist_ok=True)


def is_stats_screen(img):
    """The match-end panel: dark frame, wide cyan label row, white CONTINUE text."""
    r, g, b = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    cyan = (b > 190) & (g > 170) & (r < 120)
    H = img.shape[0]
    band = cyan[int(H * 0.62):int(H * 0.72), :]
    white = ((r > 200) & (g > 200) & (b > 200))[int(H * 0.80):int(H * 0.90), :]
    return band.sum() > 400 and white.sum() > 150 and img.mean() < 60


def play_match(params, seconds, seed=0, tag=""):
    """Play one match with `params`, return the record."""
    rng = random.Random(seed)
    tr = perceive.FastTracker()
    trace, t0, prev = [], time.time(), time.time()
    while time.time() - t0 < seconds:
        img = nav.capture()
        if img is None:
            time.sleep(0.05)
            continue
        now = time.time()
        if is_stats_screen(img):
            break
        obs = tr.update(img, now - prev)
        prev = now
        trace.append([now - t0, obs["p1"], obs["p2"]])
        A.press(A.act(params, obs, rng))
        time.sleep(0.045)
    mine = tr.events.count("my_death")
    theirs = tr.events.count("their_death")
    return {"fitness": 3.0 * theirs - 2.0 * mine, "my_deaths": mine,
            "their_deaths": theirs, "params": params, "trace": trace,
            "seconds": round(time.time() - t0, 1), "tag": tag}


def continue_match():
    """Dismiss the stats screen so the next match starts."""
    A.press(A.KEYS["attack"] if False else 13, 0.05)
    time.sleep(2.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=3)
    ap.add_argument("--pop", type=int, default=6)
    ap.add_argument("--match-sec", type=float, default=165)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    pop = [A.rand_params(rng) for _ in range(args.pop)]
    best = None
    for gen in range(args.gens):
        results = []
        for i, p in enumerate(pop):
            img = nav.capture()
            if img is not None and is_stats_screen(img):
                continue_match()
            rec = A.run_window  # placeholder to keep linters quiet
            rec = play_match(p, args.match_sec, seed=args.seed + 100 * gen + i,
                             tag=f"g{gen}i{i}")
            results.append(rec)
            A.log(rec)
            shot = nav.capture()
            if shot is not None:
                from PIL import Image
                Image.fromarray(shot).save(os.path.join(SHOTS, f"g{gen}i{i}.png"))
            print(f"gen {gen} ind {i}: fit={rec['fitness']:.1f} "
                  f"(their {rec['their_deaths']} / my {rec['my_deaths']}) "
                  f"{rec['seconds']}s", flush=True)
            continue_match()
        results.sort(key=lambda r: -r["fitness"])
        best = results[0]
        print(f"== gen {gen} best {best['fitness']:.1f} "
              f"mean {np.mean([r['fitness'] for r in results]):.1f}", flush=True)
        # next generation: elites + mutated copies
        elite = [r["params"] for r in results[: max(2, args.pop // 3)]]
        nxt = list(elite)
        while len(nxt) < args.pop:
            a, b = rng.sample(elite, 2) if len(elite) > 1 else (elite[0], elite[0])
            nxt.append(A.mutate(A.crossover(a, b, rng), rng))
        pop = nxt
    print("best params:", json.dumps(best["params"]), flush=True)


if __name__ == "__main__":
    main()
