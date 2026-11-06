# Worker B — find P1's vertical position (`y`) in the process memory

You are a reverse-engineering worker on a GameMaker (YYC, native, no symbol table) game
running headless under Proton. A previous session proved the tooling; your job is one
concrete result, approached through the **vertical axis on purpose**.

## Why you go after `y` and not `x`

Another worker is hunting `x` via horizontal motion. The horizontal axis is contaminated:
the camera follows P1, so writing a horizontal value moves the whole world and "the sprite
moved" becomes ambiguous. The vertical axis has no such confound — there is no vertical
camera follow during a match. So: identify the fighter's `y`, then walk the struct from
`y` to `x`. Two independent routes to the same struct is how we get confidence.

## Setup you already have

* `nidlinux.py` — launches the game, sends keys, takes screenshots, talks to `spy/nidspy.so`
  (preloaded into the game, reads/writes its own memory: `/proc/<pid>/mem` is refused here).
* `nidstate.py` — the shared measurement library. **Use it, don't re-invent it.**
  `enter_match`, `pause`, `frozen_noise`, `pin`, `effect`, `sprite_bbox`, `regions`,
  `coord_pairs`, `dump_f32`, `read_f`, `restart`.
* `docs/FINDINGS.md` — everything already measured (read it first, it is short).
* Your farm is isolated: `NIDFARM`, `NID_DISPLAY_BASE`, `NIDTAG`, `NIDART` are already set.
  Your game instance is **id 0 of your own farm**. Nothing else uses your display.

## The method

Pause the game (`Escape` → pause menu): the simulation freezes, the renderer keeps drawing.
Nothing drifts (measured 0 px between frames), and a write only changes the picture if the
renderer reads it as state. A position write repaints a **sprite-sized box**; camera/view/
surface writes repaint the whole frame.

## Your goal

Find the float32 holding **P1's y**, and prove it. Then find `x` relative to it.

Suggested procedure:
1. `nidstate.enter_match(0)` → LOCAL 2-player match (round never starts; fighters drivable).
2. Pause. Confirm `frozen_noise(0) == 0`. Note `sprite_bbox(0)` as the baseline: you need
   the sprite's **y extent** to move, not just any pixels to change.
3. Candidates: floats whose value lies in a plausible `y` range (roughly 0..250) — you may
   use `coord_pairs` (it returns `(x, y)` pair candidates) or sweep your own way.
4. Test while paused: `pin(..., value=30)` (a value clearly above the ground line) and
   require the **sprite's y box to shift up** by a convincing margin, reproducibly
   (pin 30, then the original, then 30 again — same result twice). A change that moves the
   whole frame is a view/surface write, not `y`.
5. Once `y` is proven, dump the surrounding memory and locate `x` at a fixed offset from
   it (report the offset). Verify `x` the same way but along the horizontal axis.

## Rules

* Work only inside this worktree. Use `nidstate.restart(0)` / `nidlinux.stop_id(0)`; do not
  `pkill` globally.
* Writing arbitrary addresses **will** sometimes segfault the game. Expected:
  `nidstate.restart(0)` and continue.
* Time budget: **25 minutes wall clock**. Prefer one script (`probe.py`) you iterate on.
  Keep output terse.
* A negative result with numbers is valid and useful. Never report an unproven offset.

## Deliverable

`results/b.json`:

```json
{"tag": "b", "goal": "P1.y", "found": true, "addr": "0x...", "width": 4,
 "x_offset_from_y": 16,
 "evidence": {"probe_values": [30, 0, 30], "sprite_y": [0, 0, 0],
              "bbox_wh": [[0,0],[0,0],[0,0]]},
 "refind": "how to locate it again after a room change",
 "dead_ends": ["short notes on what did not work"]}
```

Then stop: your final message must be a 5-line summary (found / address / proof / x offset /
dead ends). Do not start a new line of investigation after writing the file.
