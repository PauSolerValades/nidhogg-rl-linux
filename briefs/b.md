# Worker B — find P1's `y`, then `x` from the same struct

GameMaker YYC game, headless under Proton, no symbol table. Read `docs/FINDINGS.md` and
`docs/MEMORY.md` first — they are short and list four previous dead ends.

## What is already known (do not re-derive)

* **Keys must be held.** `xdotool`'s instant press (~10 ms) can fall between two 60 Hz
  steps and GameMaker never sees it. Use `nidstate.held(i, key)` (holds 120 ms) for every
  key press. This made menu navigation 100% reliable.
* **`nidstate.enter_live_match(0)`** reaches a real match (MENU → SINGLE PLAYER → TRAINING
  → ladder → BEGIN). Verify with `cpu_motion(0,3) > 15` and `sprite_present(0)`.
* **The camera follows P1 horizontally** — which is exactly why you are given the
  **vertical axis**: there is no vertical camera follow in a jump, so a jump is a clean,
  unambiguous stimulus on screen.
* Physics rewrites constants every tick, so `hold` (pin) can lose; `nidlinux.accumulate`
  (`add`) cannot be undone.
* Pause may render a frozen snapshot — do not rely on paused writes.

## Your goal

Find P1's `y` in memory using the jump as the stimulus, then report `x` from the same
struct. You are the independent route: worker A is going after `x` horizontally, so if you
land on the same struct by finding `y`, that is mutual confirmation.

Suggested procedure:
1. Enter a live match; confirm the CPU plays.
2. Find the jump key. Candidates: `w`, `Up`, `space`, `j`, `k`, `l`, `i`. Test each with
   `held(i, key, 0.5)` and measure the **yellow sprite's screen y** (rows only). A jump
   moves it up tens of pixels in ~0.2 s. (Ignore horizontal motion; the camera lies.)
3. With the jump key known: take 6 heap dumps ~0.15 s apart while the fighter is airborne
   and keep f32 slots that **fall then rise** (a ballistic arc) within 0..300.
4. Verify with `accumulate` on the candidate: a negative delta while airborne should make
   the sprite climb; a positive one should push it down. Compare sprite y before/after.
5. Then dump ±0x40 around `y` and look for a neighbouring float in 0..1100 that tracks the
   fighter horizontally (hold the move key, watch it change) — that is `x`. Report its
   offset from `y`.
6. If the jump turns out not to be drivable in that match, say so with the evidence
   (sprite y before/after for every key you tried) — that is a useful negative.

## Rules

* Only your own farm/worktree/display (env vars are set). `nidstate.restart(0)` after a
  segfault — expected.
* Budget: **25 minutes wall clock**. One `probe.py` you iterate on; terse output.
* Never report an unproven address; a negative with numbers is a valid answer.

## Deliverable

`results/b.json`:

```json
{"tag": "b", "goal": "P1.y", "found": false, "addr": null, "width": 4,
 "jump_key": null, "sprite_y": {"before": 0, "after": 0},
 "x_offset_from_y": null,
 "refind": "how to locate it again",
 "dead_ends": ["short notes"]}
```

Final message: 5 lines max (verdict / jump key / address / proof / dead ends). Stop there.

## Never kill by pattern (this killed an earlier worker)

Your brief is passed on stdin, but **an agent's own process carries the whole brief in its
command line** when it is passed as an argument — and even now, `pkill -f <word>` can match
your own shell. So:

* use `pkill -x <exact-process-name>` (e.g. `pkill -x Xvfb`, `pkill -x Nidhogg.exe`) — never
  `pkill -f`;
* if you must match a pattern, exclude yourself: `pgrep -f 'Xvf[b] :41'` (the bracket trick).
