> **Historical**: this describes the macOS era. For the current Linux/server state see
> [TMP_CURRENT_STATE.md](TMP_CURRENT_STATE.md).

# Nidhogg RL — what we are doing and what we can do

This is the structured view. `docs/MEMORY.md` is the lab notebook (chronological, including
the dead ends); this file is the map.

---

## 1. Objective

Train an RL agent on the **real, locally installed game** — not a re-implementation — without
modifying any gameplay code. The deliverable for the ML side is an interface:

* **read** the game state (positions of both fighters, sword) cheaply and exactly,
* **write** the state (for episode resets and scenario setup),
* **drive** the game with keystrokes like a human would,
* do all of it **headless and in parallel**, so it can run on a server.

The original repo (macOS) reached "the plumbing works, the policy never wins" — 0 rounds won
over 50 sessions. Its own notes blame throughput: one round per episode, ~50 s of menu
re-entry, a 23.8 fps ceiling, and round detection by a goal-line heuristic that once reported
10 phantom wins. Everything below is in service of removing those four constraints.

## 2. Why it is hard (the constraints that shaped the design)

| constraint | consequence |
|---|---|
| The 2026 port is **YYC** (native x64, no VM, no bytecode, no symbol table) | no decompilation, no code patching, no GML hooks — only memory and input |
| Runs as a Windows exe under **Proton** | `/proc/<pid>/mem` is refused (ptrace_scope=1 + container + the process reparents to systemd) |
| GameMaker needs a real window and a render surface | there is no "headless mode" to enable |
| GM polls input at 60 Hz with `keyboard_check_pressed` | an instant `xdotool` press can fall **between frames** and vanish |
| Everything is animation-heavy | naive screen diffing reports ~10 000 changed pixels per second with no input at all |

## 3. Architecture

```
farm.sh                     one wine prefix + one Xvfb display per instance
  └─ nidlinux.py            the hands and the eyes
       ├─ start / stop_id   owns the process tree (so ptrace and isolation are ours)
       ├─ key / held        xdotool key events, held 120 ms  → 100% reliable
       ├─ grab / frame      ImageMagick window capture → numpy
       └─ memory / poke     posts a request to …
            └─ spy/nidspy.so      ~90 lines, LD_PRELOADed INTO the game
                                  reads/writes its own address space, no permissions
                                  protocol: /tmp/nid_cmd_<pid>
                                    dump <addr> <len> <path>
                                    poke <addr> <hexbytes>
                                    hold <addr> <hex> <ms>     (pin across frames)
                                    add  <addr> <hex> <ms>     (accumulate, beats physics)
```

The split is deliberate: the game can read itself at full speed with no privilege, and Python
never needs to attach to anything.

## 4. How we got there (discovery chain, each step unlocking the next)

**a. Headless at all.** `Xvfb :N` per instance; the game renders to a display nobody sees.
Then the render cost: patching the window size in `data.win` (GEN8 field at `0x10+60`,
`960x600 → 320x200`) in a *copy* of the game — config, not gameplay. Result: **25 → 60 fps**
and **112% → 41% CPU** per instance. Audio silenced at the Wine layer
(`[Software\\Wine\\Drivers] "Audio"=""`), which also removed an audio thread.

**b. Reading memory at all.** `/proc/<pid>/mem` is refused here on three counts
(`ptrace_scope=1`, Proton's container, and the game reparenting to systemd — so it is not even
our descendant). `PR_SET_PTRACER`/`PR_SET_DUMPABLE` from inside did not change that. Solution:
read from **inside** — an `LD_PRELOAD`ed `.so` that dumps its own memory on request.
Measured: **112 MB in 100 ms (1.1 GB/s)**; a per-tick read would cost ~20 µs.

**c. Input that actually lands.** `xdotool key` presses and releases in ~10 ms; at 60 Hz a step
is 16 ms, so half the presses never existed inside a frame. Holding each key **120 ms** made
menu navigation move exactly one item per press, every time. This single bug explains most of
the flakiness in the original repo's notes.

**d. Knowing which screen you are on.** The selected menu item is marked by a small yellow dot
at `x≈200` (labels stop at `x≈185`), so selection is readable without OCR. The main-menu box
**scrolls**, so the dot's y-position tracks scroll, not item index. The menu also **times out**
back to the title after idle. Path used: `MENU → SINGLE PLAYER → TRAINING → opponent ladder →
BEGIN`. `READY` (local 2-player) is reached with six held Returns.

**e. Three game states, three different truths.** This is the single most important lesson of
the project:

| state | camera | positions | what it is good for |
|---|---|---|---|
| **attract** (title demo) | follows, **changes rooms every few seconds** | fractional **room space** | free motion data — no input needed |
| **READY** (local 2P) | **fixed** | **integer screen space** | identification: room x == screen x, 1:1 |
| **match** | follows P1 | fractional room space | the actual training environment |

**f. Oracles and how each one lied to us.**

| oracle | verdict |
|---|---|
| `cpu_motion > 15 && sprite_present` | **invalid** — passes on the attract demo too |
| world shift while holding a direction | **useless** — only ±4 px; the camera absorbs it |
| yellow sprite centroid | **breaks** in dark arenas (goal flag is a huge yellow blob) and near the floor strip at y≈126 |
| paused write → visible change | **unsound** — the pause screen appears to be a frozen snapshot |
| drift/motion scan of the heap | **returns derived state**: camera, views, surface dims, draw quads, dirty rects, timers |
| **pinning a value while paused** | good in principle, but was a no-op for two rounds (see below) |

**g. Two bugs in my own tooling, both found by workers.** The spy parsed `addr ms hex` while
Python sent `addr hex ms`: `add` became a **no-op**, and `hold` blocked the spy thread for
`0x3f800000` ms ≈ **12 days** per call — which is why memory reads started timing out. And
`fighter_records()` filtered for *fractional* positions, which silently excluded READY's
integer ones. Both are fixed; both invalidated a round of conclusions.

**h. The layout.** Worker C, working in **attract mode with no input and no writes**, captured
a complete jump arc and a walk and derived:

```
record stride 0x200    x @ +0xEC    y @ +0xF0     (float32, room space)
duplicates            x @ +0xFC    y @ +0x100
siblings              sword = body + 0x400      arm = body + 0x200
```

**i. Which record is P1.** On READY the camera is fixed, so room x maps 1:1 to screen x.
Alternate `d`/`a` eight times and keep the record whose `x` delta equals the yellow sprite's
delta — **8/8 transitions, worst error 1.78 px**.

**j. Which records are the fighters, in any room.** `u32 @ +0x88` points at the object
definition; grouping records by that value leaves the two fighter bodies and nothing else in a
comparable position. P2's record was cross-checked against the orange sprite (1.4–1.6 px).

## 5. Capabilities today

**Read state** — `nidstate.find_fighters(pid)` → the fighter bodies with `x`, `y`, type:

```
type 0x174f900 → 0x191c400  x =   8.0  y = 128     (P1: yellow sprite at 8.7 px)
                 0x191bc00  x = 202.0  y = 128     (P2)
siblings: sword = body + 0x400, arm = body + 0x200
```

**Write state** — `poke` (one write), `hold` (pin across frames at 2 kHz), `add`
(accumulate, which physics cannot undo). Verified: writing a view variable visibly scrolls
the world; writing a position moves the sprite.

**Drive** — held keys via XTEST, per-display, no root, no `uinput`, no focus stealing. Jump is
`space`; movement is `d`/`a` (measured 21.7 ↔ 78.1 px on READY).

**Scale** — per instance at 320×200: 60 fps, ~41–56% of one core, ~455 MB.
8 cores ≈ 14 instances ≈ 840 steps/s; 16 cores/32 GB ≈ 28 ≈ 1700 steps/s.
For reference, the original macOS harness topped out at **23.8 fps on one instance**.

**Cheap observation** — the reason to prefer memory over pixels:

| channel | cost per sample |
|---|---|
| screenshot + decode | **56 ms** (39 ms `import` + decode) |
| memory, spy pushing per tick (planned) | **~20 µs** file read |
| raw dump bandwidth | 112 MB / 100 ms |

**Isolation** — `farm.sh init`, `start N`, `stop`; one farm/prefix/display per worker, so
several agents or trainers can run side by side without interference.

## 6. Known limits (state these to whoever uses it)

1. **The type pointer's value changes per run** — re-derive it at session start with the
   round-6 recipe; do not hardcode `0x174f900`.
2. **P1-vs-P2 labelling is proven on READY only** (fixed camera + sprite). In a real match,
   label by type grouping, and expect fractional room-space coordinates.
3. **`y` was never input-verified** — nothing jumps on READY. `y = 128` is ground at the start
   line, consistent with worker C's attract arcs, but that is consistency, not proof.
4. **No per-tick state file yet.** The spy can dump on demand; it does not yet push
   `x, y` at 60 Hz into `/tmp/nid_state_<i>.txt`.
5. **Entry into a *verified controllable* match is still not automated.** READY is verified
   drivable; the `BEGIN` path reaches a match, but "this match is controllable" has no gate
   that survives scrutiny yet (see 4f).

## 7. File map

```
farm.sh                 farm lifecycle (init / start N / stop)
nidlinux.py             launch, keys, screenshots, spy protocol
nidstate.py             measurement library: game states, oracles, fighter enumeration
spy/nidspy.c            the in-process reader/writer (+ build.sh → nidspy.so)
hunt_live.py            live-match scan experiment
findstate.py            motion-based candidate generator (attract mode)
pokehunt.py             poke-and-watch experiment (paused, superseded)
hunt_paused.py          paused-oracle experiment (superseded)
docs/MEMORY.md          lab notebook: everything measured, including failures
docs/LINUX.md           measured farm numbers (fps, CPU, patch offsets, silencing)
docs/workers/*.json     raw reports from six headless workers
docs/OVERVIEW.md        this file
```

## 8. Next steps, in order

1. **Per-tick state file**: extend the spy to sample `find_fighters()`' addresses at 60 Hz and
   write `/tmp/nid_state_<i>.txt` — the existing `train_state.py` consumer already speaks that
   contract.
2. **Verify in a real match**: confirm the same offsets produce fractional room-space values,
   and verify `y` by holding `space` (jump) once entry is controllable.
3. **Episode resets**: write `x`/`y` for both fighters to reset a scenario in one frame,
   eliminating menu re-entry per episode.
4. **A control gate that survives scrutiny**: something that fails on the attract demo and
   passes only on a match we can drive — probably `add`-based (a written delta must survive
   into the next frame).
