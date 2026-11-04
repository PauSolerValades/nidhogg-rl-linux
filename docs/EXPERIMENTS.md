# What was tried, and why it did not work

The useful part of this repo is arguably this file. Each entry is a thing that looked like a
good idea, what measurement killed it, and what replaced it. Everything here was measured
against the real game.

## Reimplementing / simulating the game — rejected before building
A simulator would have been faster to train on, but the whole point was the real game (and a
sim built from a wrong model of the game teaches a policy that fails on the real one).
`legacy/sim_banned_NOTE/` is the empty shell that was never written.

## Computer vision for observations — rejected
Screen capture hit three problems immediately: the window must be visible to be captured (so
the Mac could not be used), capture costs were enormous, and the game renders at a reduced
frame rate when the window is occluded. Reading `CInstance` fields out of memory is exact,
~1 µs, and needs no permission. Vision code is in `legacy/vision.py`, `legacy/perceive.py`.

## Bright, visible, or focused window — all rejected
* Visible window: steals the screen.
* `orderOut` (fully hidden): the simulation stops.
* Alpha 0: capture and rendering break.
* Per-instance app bundle copies: break the code signature, GL fails.
Settled on a **2-pixel hairline at the screen edge** (measured maximum visible width: 2 px).

## Muting the Mac — rejected
`mute` on the system output would also silence everything else. Instead the game's own
`prefs.ini` is pinned (`unmuted=0`, music/sfx volume 0) and restored before every launch.

## `room_goto(25)` + `createBrainForPlayer(0)` as a menu bypass — rejected
Produces a match whose CPU is **passive** (0 px of movement over 12 s). The menu path
produces an active CPU. `startMatch(mode)` was then decompiled and swept over modes
0,1,2,3,5,6,7: none starts a real fight (best case 20 px of motion over 18 s vs 244 px in a
real match). The match also reads `trainingPersonality` / `trainingDifficulty` globals that
only the menu sets.

## Death detection by position teleport — rejected
A respawn often lands within the teleport threshold, so deaths read 0 for hours. Later
replaced by the round/ground-truth logic; the by-name variable route (`dead`,
`myroundswon`) was also tried and failed — `FindOrAllocValue` allocates a **new zeroed**
variable instead of resolving the existing one, so every value read 0 including `x`.

## Rewarding peak forward progress — rejected
Using `best_me` let one lucky frame satisfy the reward, and "advance 170 px" turned out to be
a single lunge, not sustained movement. Reward now uses **mean** position over the episode.
Measured honestly it was ~0 px of net movement.

## Longer action repeat (`HOLD_TICKS` 8 → 20) — rejected
Intuition said "be more decisive". Measurement said the opposite: advance fell from ~123 px to
14–24 px, because a committed direction drives the agent into the CPU and it gets stuck.

## Paying for closing distance — partially rejected
Strike range was believed to be 46 px; measurement showed **22 px**. Correcting the range
helped. But weighting proximity heavily (5.0) made the agent rush in and **lose every round**
(10/10), because closing paid more than surviving. Proximity is a precondition, not an
objective; it is now weighted 1.0 and the outcome terms carry the weight.

## Blind "just press Enter" recovery — actively harmful
After the entry sequence, pressing Enter repeatedly walks the main menu into
MULTIPLAYER → ONLINE. The game then sits in `rOnlineLobby` waiting for matchmaking forever —
visible in its own `online.log`. Recovery is now bounded: one confirm, then Escape and retry.

## A process watchdog that culled duplicates — rejected
Steam re-execs the game, so several processes appear. Culling to one by PID age killed the
process actually being driven: 13 launches in five minutes, zero games alive, no generation
finished. Duplicate suppression is now only `pkill` at the top of `launch()`.

## Frame-counter readiness check — rejected
Waiting for the harness to report ~700 rendered frames looked strictly better than sleeping,
but the log is not truncated per launch, so it reported "ready at frame 1080 (1s)" on
freshly started processes and entry looped. Reverted to a fixed boot; keys pressed before
~frame 690 are eaten, which is why the boot must be generous.

## Fire-and-forget key sequence — replaced
The same 8-key sequence reached a real fight sometimes and the ARCADE waiting room other
times. Two causes: (a) macOS starves the off-screen window of frames, so menu transitions
stall — forcing a render around each press helps; (b) the sequence had **one Enter too many**,
which flips the versus screen into 2-player ARCADE. Correct sequence: 7 keys.
