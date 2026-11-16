"""Fake envs with the env_iface interface, for testing the trainer without the game.

chase: 1-D. Player at x, target at t, both in [-1,1]. Action 1 = left, 2 = right,
0 and 3-6 = stay. Reward = -|x - t| each step. Target drifts slowly.
noise: same obs/dynamics, reward is random noise independent of the action.
"""
import numpy as np
from env_iface import N_OBS

STEP = 0.1


class ChaseEnv:
    def __init__(self, seed=0, ep_len=20, noise_reward=False):
        self.rng = np.random.default_rng(seed)
        self.noise_rng = np.random.default_rng(seed + 12345)  # never reseeded
        self.ep_len, self.noise_reward = ep_len, noise_reward

    def seed(self, s):
        """Optional: lets the trainer give both members of a pair the same episode."""
        self.rng = np.random.default_rng(s)

    def _obs(self):
        o = np.zeros(N_OBS)
        o[0], o[1], o[2] = self.x, self.t, self.t - self.x
        o[3] = np.sign(self.t - self.x)
        o[4] = self.tick / self.ep_len
        return o

    def reset(self):
        self.x, self.t = self.rng.uniform(-1, 1, 2)
        self.v = self.rng.uniform(-0.02, 0.02)
        self.tick = 0
        return self._obs()

    def step(self, action):
        assert 0 <= action <= 6
        if action == 1:
            self.x -= STEP
        elif action == 2:
            self.x += STEP
        self.x = float(np.clip(self.x, -1, 1))
        self.t = float(np.clip(self.t + self.v, -1, 1))
        self.tick += 1
        r = self.noise_rng.normal() if self.noise_reward else -abs(self.x - self.t)
        done = self.tick >= self.ep_len
        outcome = ("win" if abs(self.x - self.t) < 0.1 else "loss") if done else "undecided"
        return self._obs(), float(r), done, {"outcome": outcome, "tick": self.tick}


def make(name, seed=0):
    if name == "replay_stub":
        return ChaseEnv(seed)
    if name == "noise_stub":
        return ChaseEnv(seed, noise_reward=True)
    raise ValueError(name)
