"""Interface every environment must satisfy (replay_stub.py, later nidenv.py)."""
from typing import Protocol, Tuple
import numpy as np

N_OBS = 8      # obs shape (8,), values roughly in [-1, 1]
N_ACTIONS = 7  # action int in 0..6 (keys)


class Env(Protocol):
    def reset(self) -> np.ndarray:
        """Start an episode; return obs of shape (8,)."""

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, dict]:
        """Return (obs, reward, done, info). info has 'outcome' in
        {'win','loss','undecided'} and 'tick'. done=True at episode end."""
