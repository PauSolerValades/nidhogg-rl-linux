# Worker — find the pad trigger by sweeping symmetric offsets, in window fractions

## Goal

Produce a **reliable, resolution-independent recipe** that gets the game from the READY screen into
a live match, by sweeping how far the two fighters stand from the centre wall.

## The mechanic (from the human player who owns the game — treat as ground truth)

* The wall is in the middle of the screen; each fighter's pad is in the middle of its own half.
* **BOTH** fighters must be standing on their pads. One alone does nothing, forever.
* They must stand there for ~**1.5 s**; then an audio cue plays, the floor **chandeliers light up**,
  and the **stage-select** screen appears.
* P1 = yellow, keys `a`/`d`. P2 = orange, keys **arrow** `Left`/`Right` (i/j/k/l do nothing).

## What is measured already (use it, don't re-derive)

* Wall: a ~32 px light-grey vertical band, detected as "column is >60 % light grey in the upper
  half" → `nidstate._wall_x(i)`.
* Pads appear at wall ± **0.32 × window width** (measured on a 320×200 window: wall 159.5, pads
  ≈57 and ≈262). But the *trigger zone* is clearly smaller than the visual bar: fighters parked at
  ±0.32W did **not** trigger it in one run, and did in another.
* `nidstate` has: `enter_ready(i)` (presses Return until fighters+wall are on screen), `_wall_x`,
  `_mask` (colour masks per player), `pad_and_fighter`, `on_stage_select` (pads gone AND fighters
  gone), `find_players_by_input`, `nidlinux.fps`.

## What to do

1. Boot one instance, wait for the window (~65 s) and ~12 s for the splash, then `enter_ready(0)`.
   Confirm READY by eye once (save the screenshot) — the attract demo also draws fighters, so the
   wall test is what distinguishes them.
2. **Sweep.** For `d` from a small offset outward (e.g. 0.10·W to 0.45·W in steps of ~6 px):
   * park both fighters at wall − d (yellow) and wall + d (orange) using colour-blob feedback;
   * hold still ~1.6 s;
   * check for the transition: `on_stage_select(0)` true, or fighters gone, or a screenshot that
     looks like the stage preview ("castle");
   * record `d/W`, both fighters' x/W, whether it fired, and save the screenshot.
3. Report the **range** of `d` that fires, not just one value, plus the tolerance on each side.
4. Verify: from a *fresh* instance, use the best `d` and show the transition firing **twice in a
   row**, with timings. Then press `Return` and confirm you land in a live match
   (`find_players_by_input` succeeds and the screen is not READY — note that READY is drivable too,
   so drivability alone does not prove a match).
5. Write the recipe as pseudocode with **window-fraction constants only** (no pixel constants), so it
   survives a resize.

## Recommended shape of the loop (the human's idea — better than solving for coordinates)

Nudge both fighters symmetrically outward in small increments and re-check after each step, instead
of computing a target position and hoping:

```python
for step in range(40):
    tap('d', 0.05); tap('Right', 0.05)      # move both outward a little
    time.sleep(0.3)
    if on_stage_select(i):  break
```

Whichever way you do it, the deliverable is the same: the offset that fires, its tolerance, and
proof it repeats.

## Rules

* Your own farm `~/.nidfarm-p`, display band `:150`. Source the runtime env first, then override:

  ```bash
  . ~/Developement/nidhogg-rl-install/results/env.sh
  export NIDFARM=$HOME/.nidfarm-p NID_DISPLAY_BASE=150 NID_GAME_DIR=$HOME/.nidfarm-p/game
  ```
* **Never `pkill -f`** (it matches your own command line and has killed a worker before). Use
  `pkill -x <exact name>`; never kill processes you did not start — other users share this box.
  Note: the **heap base and instance addresses change per process**, so never reuse an address.
* Screenshots cost ~1 s each under load; do not build timing assumptions on them.
* Do not edit shared files; put diffs in `results/p.patch`.
* Budget **40 minutes**. A negative with numbers is a full result.

## Deliverable

`results/p.json`:

```json
{"ok": false, "fired_at": {"d_over_W": [0.0], "range": [0.0, 0.0]},
 "runs": [{"steps": 0, "d_over_W": 0.0, "fired": false, "to_match": false, "seconds": 0}],
 "ready_confirm": "how you verified READY", "transition_cue": "what you saw (chandelier/castle/audio)",
 "recipe": "pseudocode with window fractions", "dead_ends": []}
```

Final message: 8 lines max.
