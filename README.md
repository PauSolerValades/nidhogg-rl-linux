# nidhogg-rl

An agent that learns to play **the real, locally installed copy of Nidhogg** — not a
simulator. It reads the game's state out of process memory (no computer vision) and drives
it with injected keystrokes, so the candidate policy is always playing the actual game.

**Status: not yet beating the CPU.** The plumbing works end to end (it enters a Training
match against the CPU, plays it, scores it, evolves, and repeats). The learned policy does
not yet win rounds. Every number in this repo is measured; see `docs/STATE.md` for what is
verified, and `docs/EXPERIMENTS.md` for what was tried and abandoned.

---

## How it works

```
┌────────────────────────┐         ┌───────────────────────────┐
│ Nidhogg (real binary)  │         │ Python trainer            │
│  hook/inject.dylib     │         │  train_win.py             │
│   ├ reads fighter x/y  │──state──▶  ├ observation: 8 numbers  │
│   ├ injects keys       │◀─keys────  ├ policy: neuro.py (935 w)│
│   └ parks window 2 px  │  files    ├ fitness → GA            │
└────────────────────────┘         └───────────────────────────┘
```

State and commands are plain files in `/tmp` (`nid_state_<id>.txt`, `nid_keys_<id>.txt`, …),
so the Python side needs no IPC and the game side never blocks.

| File | Role |
|---|---|
| `hook/inject.m`, `hook/hook.s` | Injected dylib: memory reads, key injection, window hiding, mute |
| `train_state.py` | Launches the game, enters a Training match, reads state, sends keys |
| `neuro.py` | 8→32→16→7 network (tanh), GA, and hand-written seed policies |
| `train_win.py` | Episode loop, reward, generational training |
| `evaluate.py` | Win-rate measurement (the only number that counts) |
| `agent_play.py` + `play_vs_agent.sh` | Human vs. trained agent |
| `train_forever.sh` | Unattended train → evaluate → repeat loop |
| `NOTES.md` | Lab notebook: every experiment, including the failures |

## Running it

```bash
uv venv .venv && source .venv/bin/activate      # Python 3.12
uv pip install numpy matplotlib pyobjc

clang -dynamiclib -fobjc-arc -O1 -arch arm64 \
  -framework Cocoa -framework OpenGL -framework CoreVideo \
  -o hook/inject.dylib hook/inject.m hook/hook.s
codesign --force -s - hook/inject.dylib

python3 train_win.py --instances 1 --gens 60 --pop 10 --window 60
```

Requirements and constraints baked into the code:

* Nidhogg installed through Steam (path configured in `train_state.py`).
* **Nothing appears on screen.** The game window is resized to a 2-pixel hairline parked at
  the screen edge; no focus stealing, no fullscreen, no dialogs.
* **The game is muted, never the Mac.** `prefs_locked.ini` is restored before every launch
  (audio zeroed, language forced to English).
* **At most two game processes.** `launch()` kills leftovers first; Steam's re-exec chain is
  the reason this needs enforcing.

## Design decisions worth knowing

* **Memory, not vision.** Reading `CInstance` x/y out of the process at ~40 Hz is exact and
  needs no permissions. `legacy/` contains the abandoned screen-capture approach.
* **The Training menu, not `room_goto`.** Jumping rooms directly produces a match with an
  *inert* CPU; the menu path produces one that actually plays. The entry is
  `13, W, 13, S, S, 13, 13, 13` — **two** S presses select TRAINING, one selects the
  2-player ARCADE room, which waits forever for a second human.
* **Entry is verified by CPU motion**, not by the fighter's y: a live training match and the
  ARCADE waiting room both show fighters at y≈128.
* **A Training match is one round.** Re-entry per episode is required; accepting into the
  next round does not work.
* **Speed is raised only after entry.** At speed 180 the game runs ~47 fps, but the menu
  timing is calibrated at the default ~24 fps, so raising it earlier makes entry overshoot.

## What has been measured

Short version; details and dates in `docs/STATE.md`.

* Keyboard control works: holding a direction moves the fighter at ~12 px/s.
* Strikes only land at horizontal distance **≤ 22 px** (at 59 px they miss entirely).
* Running alone does **not** win: holding right for 120 s gains ~366 px and is then pushed
  back to the start — the CPU has to be beaten, not outrun.
* Training matches are one round; the CPU wins by crossing the goal line at x=250.

## Repo layout

```
hook/          injected dylib (state reader, key injector, window handling)
docs/          STATE.md (verified facts) and EXPERIMENTS.md (what failed and why)
legacy/        abandoned approaches, kept for the record (incl. a banned simulator)
NOTES.md       chronological lab notebook
```
