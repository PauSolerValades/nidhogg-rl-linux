# Worker A — find P1's record on the READY screen (fixed camera, 1:1 mapping)

GameMaker YYC game, headless under Proton, no symbol table. Read `docs/MEMORY.md` first.

## The layout is proven; the arena in previous rounds was wrong

```
record stride 0x200    x @ +0xEC    y @ +0xF0     (float32, fractional, room space)
duplicates            x @ +0xFC    y @ +0x100
```

Previous rounds failed because they used the **attract demo**, which changes rooms every
few seconds — records teleport (`x 944 -> 79` between dumps 0.3 s apart) so nothing stays
comparable, and pair-matching on geometry alone is chance (a small sprite delta matched 562
record pairs).

**Use the LOCAL READY screen instead.** It has been measured drivable — yellow screen x
`22 -> 90 -> 22` under `d` then `a` — and its camera is **fixed** (world shift 0). A fixed
camera means room `x` equals screen `x` 1:1, so you do not need any camera algebra:

```
the fighter record is the one whose x@+0xEC changes by the SAME amount as
the yellow sprite's screen x, every single time, while you alternate d/a
```

## Getting there (and proving it)

`nidstate.enter_match(0)` presses Return six times with held keys and returns only if the
fighter is drivable (`drivable(0,'d') > 15`). If it returns False, restart
(`nidstate.restart(0)`) and retry — do not debug the menu, and never use attract mode.

Then prove the two preconditions yourself, before any memory work:
1. `drivable(0,'d') > 15` and then `drivable(0,'a') > 15` (P1 responds to both).
2. **Fixed camera**: capture a frame, hold `d` 0.7 s, capture again, and compare a
   background strip (rows 20..80) — it must NOT shift. If it does shift, you are on the
   wrong screen and the 1:1 assumption is void: restart.

## Your goal

Identify the one record whose `x@+0xEC` tracks the yellow sprite 1:1, and report it.

Suggested procedure:
1. Reach and verify READY as above.
2. Robust sprite x with `nidstate.yellow_screen_x(0)` (pure yellow, play area, densest
   24-px cluster — the goal flag is a big yellow blob and breaks a plain centroid).
3. Alternate: hold `d` 0.5 s, sample; hold `a` 0.5 s, sample. Do this 8 times. After each
   hold, record the sprite x **and** read every candidate record's `x@+0xEC`
   (`nidstate.fighter_records` gives you the list; cache the addresses for the session
   since READY does not change rooms).
4. Match: the fighter's record must satisfy `|Δrecord_x − Δsprite_x| < 3 px` on at least
   7 of the 8 transitions, with a constant offset (that offset is the camera letterbox).
   Report the record, the offset, and the per-transition errors.
5. If it also works vertically, verify `y@+0xF0` with a jump (`space` is the jump key) and
   report both.

## Rules

* **No writes.** Do not use `poke`, `hold` or `accumulate` — this task needs none, and the
  spy's write path has burned three rounds.
* Only your own farm/worktree/display (env vars are set). `nidstate.restart(0)` if the game
  dies or the gate fails.
* Budget: **25 minutes**. One `readyhunt.py` you iterate on; terse output.
* A negative with numbers is valid. Never report an unproven record.

## Deliverable

`results/a.json`:

```json
{"tag": "a", "goal": "P1 record on READY", "found": false,
 "addr": null, "x_offset": "0xEC", "y_offset": "0xF0", "camera_offset": 0,
 "errors_px": [0, 0, 0, 0, 0, 0, 0, 0], "sprite_x_series": [], "record_x_series": [],
 "refind": "how to pick it again", "dead_ends": ["short notes"]}
```

Final message: 5 lines max (record / offset / worst error / vertical check / dead ends).
