# Worker A — find P1's horizontal position (`x`) in the process memory

You are a reverse-engineering worker on a GameMaker (YYC, native, no symbol table) game
running headless under Proton. A previous session proved the tooling; your job is one
concrete result.

## Setup you already have

* `nidlinux.py` — launches the game, sends keys, takes screenshots, talks to `spy/nidspy.so`
  (preloaded into the game, reads/writes its own memory: `/proc/<pid>/mem` is refused here).
* `nidstate.py` — the shared measurement library. **Use it, don't re-invent it.**
  `enter_match`, `pause`, `frozen_noise`, `pin`, `effect`, `sprite_bbox`, `regions`,
  `coord_pairs`, `dump_f32`, `read_f`, `restart`.
* `docs/FINDINGS.md` — everything already measured (read it first, it is short).
* Your farm is isolated: `NIDFARM`, `NID_DISPLAY_BASE`, `NIDTAG`, `NIDART` are already set
  in your environment. Your game instance is **id 0 of your own farm**. No other instance
  exists and nothing else touches your display.

## The one method that works

Pause the game (`Escape` → pause menu). The simulation freezes, the renderer keeps
drawing. Therefore: nothing drifts by itself (measured 0 px between frames), and a write
only changes the picture if the renderer reads it as *state* — velocities do nothing
without ticks. A real position write repaints a **sprite-sized box**; camera/view/surface
writes repaint the whole 320×200 frame (that is how they identify themselves and how four
earlier "confirmations" were correctly rejected).

## Your goal

Find the float32 in the game heap that holds **P1's x**, and prove it.

Suggested procedure:
1. `nidstate.enter_match(0)` → a LOCAL 2-player match. Fighters are drivable there even
   though the round never starts. Verify with `sprite_present`.
2. Pause. Confirm `frozen_noise(0) == 0`.
3. Candidate generation is the hard part, and motion is the wrong generator (it returns
   camera/view/surface state). Use **structure**: `coord_pairs` gives float32 pairs whose
   values look like `(x, y)` coordinates. Prune further however you like (stride, value
   ranges, tag words nearby, records of equal stride).
4. Test each candidate while paused: `pin(..., value=60)` then `effect(baseline, frame)`.
   Keep only **sprite-sized** repaints (bbox both sides < 70). Then confirm: pin 300
   (must repaint differently), pin 60 again (must reproduce the first result exactly),
   and pin the original value back.
5. Report the address, the width, and the numbers that prove it.

## Rules

* Work only inside this worktree. Never modify `~/.nidfarm*` other than through
  `nidlinux.py`, and never run `pkill` on `Nidhogg.exe` (that would be fine here but you
  should still use `nidstate.restart(0)` / `nidlinux.stop_id(0)` so the habit is safe).
* Writing arbitrary addresses **will** sometimes segfault the game. That is expected:
  `nidstate.restart(0)` and carry on.
* Time budget: **25 minutes wall clock**. Prefer one script (`probe.py`) you iterate on
  over long one-liners. Keep output terse.
* A negative result with numbers is a valid, useful result. Do not fake a confirmation —
  a wrong offset is worse than nothing, because downstream training will trust it.

## Deliverable

`results/a.json`:

```json
{"tag": "a", "goal": "P1.x", "found": true, "addr": "0x...", "width": 4,
 "value_when_found": 0.0,
 "evidence": {"probe_values": [60, 300, 60], "changed_px": [0, 0, 0],
              "bbox": [[0,0],[0,0],[0,0]]},
 "refind": "how to locate it again after a room change",
 "dead_ends": ["short notes on what did not work"]}
```

Then stop: your final message must be a 5-line summary (found / address / proof / refind /
dead ends). Do not start any new line of investigation after writing the file.
