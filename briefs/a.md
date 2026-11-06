# Worker A — camera or position? Then find P1's x

GameMaker YYC game, headless under Proton, no symbol table. Read
`docs/FINDINGS.md` and `docs/MEMORY.md` first — they are short and they list four
previous dead ends you must not repeat.

## What is already known (do not re-derive)

* **Keys must be held.** `xdotool`'s instant press lasts ~10 ms and can fall between two
  60 Hz steps; GameMaker then never sees it. `nidstate.held(i, key)` holds 120 ms and is
  100% reliable. Every key press you make must go through it.
* **`nidstate.enter_live_match(0)`** reaches a real match (MENU → SINGLE PLAYER → TRAINING
  → ladder → BEGIN). Verify with `nidstate.cpu_motion(0, 3) > 15` and `sprite_present(0)`.
  The older `enter_match` lands on a READY screen that is **not a fight**.
* **The camera follows P1.** The fighter keeps its screen position while the world
  scrolls. Therefore the yellow centroid is *not* an oracle for input or for motion.
  A previous worker's whole sweep failed because of this.
* **Physics rewrites constants every tick** (~60 Hz), so `hold` (pin) can be overwritten.
  `nidlinux.accumulate(pid, addr, delta, width, ms)` uses `add`, which the game cannot undo.
* **Pause is suspect**: the pause screen may render a frozen snapshot, so a write while
  paused may be invisible. Prefer live verification.
* Addresses change between runs and between rooms. The pair `0x94544e0 / 0x9459be0` from a
  previous run is a *hint*, not a fact: re-derive candidates yourself.

## Your goal

Two rising float32 slots were observed in a live match, rising `+130` while `d` was held
1.2 s (`0x94544e0`, `0x9459be0`, `0x50000` apart). Decide for each: **camera value or
instance position?** Then report P1's `x`.

Suggested procedure:
1. Enter a live match; confirm the CPU plays.
2. Confirm input works at the *world* level: capture a frame, `held(i,'d',1.2)`, capture
   again, and measure the shift of a background strip (e.g. rows 20..80, columns 0..319)
   with `numpy`: a real hold must shift the world. Do the same with `'a'` and require the
   shift to reverse. Note in your notes that the sprite's **centroid will not move** —
   that is the camera following, not a failure.
3. Re-derive candidates: while holding `d`, take 6 heap dumps ~0.25 s apart
   (`nidstate.regions`, `nidstate.dump_f32`) and keep f32 slots that rise monotonically by
   20..700 and are fractional (positions are not round numbers).
4. Direction check: holding `a` must make the same slots fall by a similar amount.
5. **Discriminator.** Use `accumulate` with a large delta (e.g. +300 over 400 ms) on one
   candidate at a time, and compare frames: if the *world* jumps but the fighter stays at
   the same screen offset, it is camera/view state; if the *fighter's screen position*
   changes, it is the instance position. Record the frames.
6. Report every candidate's verdict. If you find a position, also report whether
   `instance_x - camera_value` is a constant across two different fighter positions — if it
   is, that constant is the screen offset and the relationship can be used to re-find `x`.

## Rules

* Only your own farm/worktree/display (env vars are set). Restart with
  `nidstate.restart(0)` when a poke segfaults — expected.
* Budget: **25 minutes wall clock**. One script (`probe.py`) you iterate on; terse output.
* A negative result with numbers is a valid answer. Never report an unproven address.

## Deliverable

`results/a.json`:

```json
{"tag": "a", "goal": "P1.x", "found": false, "addr": null, "width": 4,
 "camera_vs_position": {"0x...": "camera: accumulate moved the world, sprite stayed"},
 "world_shift": {"d": 0, "a": 0},
 "refind": "how to locate it again",
 "dead_ends": ["short notes"]}
```

Final message: 5 lines max (verdict / address / proof / refind / dead ends). Stop there.
