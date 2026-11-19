"""Evolution-strategy trainer. Policy: MLP 8 -> 16 tanh -> 7 logits, greedy action.
Each generation: K antithetic noise pairs, one episode per perturbed policy, theta moves
along the reward-difference-weighted noise. Every episode (perturbed ones included) is logged.

  python3 train/train.py --env replay_stub --steps 10000 --seed 0
  python3 train/train.py --env nidenv      # needs nidenv.py importable, else fails loudly
"""
import argparse, importlib, pickle, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_iface import N_OBS, N_ACTIONS

H = 16
SHAPES = [(N_OBS, H), (H,), (H, N_ACTIONS), (N_ACTIONS,)]
SIZES = [int(np.prod(s)) for s in SHAPES]


def act(theta, obs):
    i, parts = 0, []
    for s, n in zip(SHAPES, SIZES):
        parts.append(theta[i:i + n].reshape(s)); i += n
    w1, b1, w2, b2 = parts
    return int(np.argmax(np.tanh(obs @ w1 + b1) @ w2 + b2))


def episode(env, theta, max_invalid=10, give_up=None, score_all=False):
    """One VALID episode. An env that marks episodes valid/invalid (nidtrain_env: a real fight
    in an arena, see validity.py) gets an invalid one replayed with the same partner seed; the
    invalid one never reaches the rewards. Too many invalid in a row stops the run."""
    for _ in range(max_invalid):
        obs, total, steps, info, done = env.reset(), 0.0, 0, {}, False
        while not done:
            obs, r, done, info = env.step(act(theta, obs))
            total += r; steps += 1
        if score_all:                   # every episode scored once by the env's fitness
            return info.get("fitness", total), steps, info["outcome"]
        if info.get("valid", True):
            return total, steps, info["outcome"]
        if give_up and _ + 1 >= give_up:
            return None                 # this perturbation never produced a valid episode: skip it
        if hasattr(env, "ep_seed") and hasattr(env, "seed") and _ == 0:
            env.seed(env.ep_seed)       # one replay with the same partner; then fresh seeds
    raise SystemExit(f"{max_invalid} invalid episodes in a row; last: {info}")


def load_env(name, seed):
    if name in ("replay_stub", "noise_stub"):
        return importlib.import_module("replay_stub").make(name, seed)
    try:
        mod = importlib.import_module(name)
    except ImportError as e:
        raise SystemExit(f"cannot import env module '{name}': {e}. "
                         "No fallback to the stub is done on purpose.")
    return mod.make(seed) if hasattr(mod, "make") else mod.Env(seed)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--env", default="replay_stub")
    p.add_argument("--steps", type=int, default=10000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--pairs", type=int, default=5)
    p.add_argument("--sigma", type=float, default=0.3)
    p.add_argument("--lr", type=float, default=0.3)
    p.add_argument("--ckpt_every", type=int, default=50, help="episodes")
    p.add_argument("--max_episodes", type=int, default=0, help="stop after this many (0 = no cap)")
    p.add_argument("--eval", type=int, default=20, help="greedy evaluation episodes after training")
    p.add_argument("--score_all", action="store_true",
                   help="score every episode by info['fitness'] (no replay, no skipping)")
    p.add_argument("--give_up", type=int, default=0,
                   help="tries per perturbation before it is left out of the update (0 = never)")
    p.add_argument("--ckpt_dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "ckpt"))
    a = p.parse_args()

    os.makedirs(a.ckpt_dir, exist_ok=True)
    path = os.path.join(a.ckpt_dir, f"{a.env}_s{a.seed}.pkl")
    env = load_env(a.env, a.seed)
    rng = np.random.default_rng(a.seed)
    st = dict(theta=rng.normal(0, 0.5, sum(SIZES)), rewards=[], steps=0, rng=rng.bit_generator.state)
    if os.path.exists(path):
        st = pickle.load(open(path, "rb")); rng.bit_generator.state = st["rng"]
        print(f"resumed {path}: {len(st['rewards'])} episodes, {st['steps']} steps")

    def save():
        st["rng"] = rng.bit_generator.state
        pickle.dump(st, open(path + ".tmp", "wb")); os.replace(path + ".tmp", path)

    last_save = len(st["rewards"])
    while st["steps"] < a.steps and not (a.max_episodes and len(st["rewards"]) >= a.max_episodes):
        eps = rng.normal(size=(a.pairs, len(st["theta"])))
        scores = np.zeros((a.pairs, 2))
        for k in range(a.pairs):
            ep_seed = int(rng.integers(2**31))
            for j, sgn in enumerate((1, -1)):
                if hasattr(env, 'seed'):  # optional: same start for both pair members
                    env.seed(ep_seed)
                out = episode(env, st["theta"] + sgn * a.sigma * eps[k], give_up=a.give_up,
                              score_all=a.score_all)
                if out is None:
                    scores[k, j] = np.nan; continue
                r, n, _ = out
                st["rewards"].append(r); st["steps"] += n; scores[k, j] = r
        adv = scores[:, 0] - scores[:, 1]
        adv = np.where(np.isnan(adv), 0.0, adv)        # a pair with a skipped member: no vote
        st.setdefault("skipped", []).append(int(np.isnan(scores).sum()))
        adv = adv / (adv.std() + 1e-8)
        st["theta"] = st["theta"] + a.lr / a.pairs * (adv[:, None] * eps).sum(0)
        if len(st["rewards"]) - last_save >= a.ckpt_every:
            save(); last_save = len(st["rewards"])
    save()
    R = np.array(st["rewards"])
    print(f"env={a.env} seed={a.seed} episodes={len(R)} steps={st['steps']}")
    print(f"first20 mean={R[:20].mean():.3f}  last20 mean={R[-20:].mean():.3f}")
    ev = [e for e in (episode(env, st["theta"], give_up=a.give_up, score_all=a.score_all)
                      for _ in range(a.eval)) if e is not None]
    if ev:
        print(f"greedy unperturbed eval ({len(ev)} eps): mean={np.mean([e[0] for e in ev]):.3f} wins={sum(e[2]=='win' for e in ev)}")


if __name__ == "__main__":
    main()
