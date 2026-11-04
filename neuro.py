"""Neural policy + GA (evolution strategies style), pure numpy.

State (all read from memory by the injected harness):
    [dx, me_x, them_x, me_y, them_y, |dx|, alive_me, alive_them]
  normalised; dx = them_x - me_x in screen/room pixels.

Policy: 8 -> tanh(32) -> tanh(16) -> 7 actions (left, right, up, down, attack,
jump, idle). Weights evolve by tournament selection + crossover + gaussian
mutation, same loop shape as the parametric version.
"""
import numpy as np

ACTIONS = [65, 68, 87, 83, 70, 71, 0]  # A,D,W,S,F,G,nothing

LAYERS = [8, 32, 16, 7]
SIZES = [LAYERS[i] * LAYERS[i + 1] for i in range(len(LAYERS) - 1)]
N_WEIGHTS = sum(SIZES) + sum(LAYERS[1:])


def unpack(w):
    mats = []
    off = 0
    for i in range(len(LAYERS) - 1):
        r, c = LAYERS[i], LAYERS[i + 1]
        size = r * c
        mats.append(w[off:off + size].reshape(r, c))
        off += size
        b = w[off:off + c]
        off += c
        mats.append(b)
    return mats


def forward(w, obs):
    h = np.asarray(obs, dtype=np.float64)
    mats = unpack(w)
    for i in range(0, len(mats), 2):
        h = np.tanh(h @ mats[i] + mats[i + 1])
    return h


def obs_vector(st):
    if not st:
        return np.zeros(8)
    dx = st["them_x"] - st["me_x"]
    # Inputs 6 and 7 used to be hardcoded 1.0 (dead inputs - the policy could not
    # see whether it was actually in striking range). They now carry the two
    # signals that matter for timing a hit: a reach flag and the height gap.
    REACH = 22.0 / 400.0
    v = np.array([
        dx / 400.0,                     # signed horizontal gap
        st["me_x"] / 2000.0,
        # (was them_x/2000 - redundant, since them_x == me_x + dx). This slot now
        # carries the actual objective: how far we still are from OUR goal line.
        np.clip((1650.0 - st["me_x"]) / 1500.0, -1.0, 1.0),
        st["me_y"] / 250.0,
        st["them_y"] / 250.0,
        # WAS abs(dx)/400 - redundant with inputs 0 and 6 (dx already encodes the gap
        # and the reach flag marks strike range). MEASURED CEILING: the best hand-written
        # policy (walk + strike) advanced only 114..232 px in 120 s and pushed 47 px,
        # because the CPU blocks and it cannot time its swings. This slot now carries the
        # RELATIVE APPROACH SPEED (px/s of the gap closing, sign = who is closing), which
        # is what you need to time a strike against an incoming opponent.
        float(np.clip(st.get("dx_vel", 0.0) / 400.0, -1.0, 1.0)),
        # MEASURED: striking at dx=22 drove the CPU from 246 to 297 (+51 px); striking at
        # dx=59 moved it 0 px over 15 s. So the usable reach is ~22 px, not 46 - the
        # network was being told to attack from nearly double the range and whiffing.
        1.0 if abs(dx) <= 22.0 else 0.0,       # IN REACH -> time to strike
        np.clip((st["me_y"] - st["them_y"]) / 60.0, -1.0, 1.0),   # height gap
    ], dtype=np.float64)
    return np.clip(v, -3.0, 3.0)


class Population:
    def __init__(self, size=24, seed=0, scripted=True):
        self.rng = np.random.default_rng(seed)
        self.W = self.rng.normal(0.0, 0.7, size=(size, N_WEIGHTS))
        if scripted:
            # CURRICULUM SEEDS. Measured: holding a direction moves the fighter at
            # ~12 px/s, but the evolved net managed ~0.1 px of net movement - it never
            # learned even to walk. Rather than wait for that to emerge, start the
            # population from hand-written policies so selection has something that
            # already moves and strikes to recombine from.
            for i, w in enumerate(scripted_seeds()[:size]):
                self.W[i] = w

    def next_gen(self, fitness):
        order = np.argsort(-np.asarray(fitness))
        elite = self.W[order[: max(2, self.W.shape[0] // 4)]]
        n = self.W.shape[0]
        kids = list(elite)
        while len(kids) < n:
            a, b = self.rng.choice(elite.shape[0], 2)
            w = np.where(self.rng.random(N_WEIGHTS) < 0.5, elite[a], elite[b]).copy()
            mut = self.rng.random(N_WEIGHTS) < 0.06
            w += mut * self.rng.normal(0.0, 0.22, N_WEIGHTS)
            kids.append(w)
        # ANCHOR THE SEEDS. The hand-written "walk in, strike when in reach" policy is
        # the only thing that ever lands a hit, but plain tournament selection drops it
        # long before a better variant appears (measured: min_dx 90 px, i.e. nothing ever
        # closes). Keeping two scripted anchors in every generation gives selection
        # something attack-capable to recombine from instead of rediscovering it.
        seeds = scripted_seeds()
        anchors = [seeds[4], seeds[5]] if len(seeds) > 5 else seeds[-2:]
        for k, w in enumerate(anchors):
            kids[-(k + 1)] = w
        self.W = np.array(kids)


def scripted_seeds():
    """Hand-written policies expressed as weights, for the initial population.

    Bias-only seeds force a constant action (hidden units are all tanh(0)=0, so the
    last-layer bias alone decides the argmax). The reach-conditional seed instead
    routes the "in reach" observation through one hidden unit, so it walks right and
    strikes exactly when the opponent is within sword range.
    """
    W1 = slice(0, 8 * 32)
    B1 = slice(256, 288)
    W2 = slice(288, 800)
    B2 = slice(800, 816)
    W3 = slice(816, 928)
    B3 = slice(928, 935)
    seeds = []

    def base():
        return np.zeros(N_WEIGHTS)

    for idx in (1, 0, 4, 5):          # always right / left / attack / jump
        w = base(); w[B3][idx] = 3.0; seeds.append(w.copy())

    # walk right, attack when in reach (obs[6] is the 1.0/0.0 reach flag)
    w = base()
    w[6 * 32 + 0] = 10.0              # input 'reach' -> hidden L1 unit 0
    w[288 + 0 * 16 + 0] = 10.0        # L1 unit 0 -> L2 unit 0 (pass-through; without
                                      # this the all-zero middle layer zeroes it out)
    w[W3][0 * 7 + 4] = 5.0            # unit 0 -> attack
    w[B3][1] = 1.5                    # otherwise: move right
    seeds.append(w)

    # same but strafe left when in reach (feint), attack otherwise
    w = base()
    w[6 * 32 + 0] = 10.0
    w[W3][0 * 7 + 0] = 5.0
    w[B3][1] = 1.5
    seeds.append(w)
    return seeds


def rand_policy(rng):
    return rng.normal(0.0, 0.7, size=N_WEIGHTS)


IDLE_INDEX = 6          # ACTIONS[6] is "nothing"


def decide(w, st, rng):
    out = forward(w, obs_vector(st))
    a = int(np.argmax(out))
    if rng.random() < 0.03:           # small exploration floor
        a = int(rng.integers(0, len(ACTIONS)))
    # Standing still is never useful in Nidhogg: a whole generation converged on the
    # idle output and scored exactly 0.00 (no progress, no kills, no rounds). Replace
    # idle with "advance on the opponent" so every policy always does something.
    if a == IDLE_INDEX and st:
        return 68 if st["them_x"] > st["me_x"] else 65
    return ACTIONS[a]
