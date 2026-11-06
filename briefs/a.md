# Worker A — which two of the ~300 records are P1 and P2?

GameMaker YYC game, headless under Proton, no symbol table. Read `docs/MEMORY.md` first.

## The layout is proven. Your job is to pick the fighters out of the crowd.

```
record stride 0x200    x @ +0xEC    y @ +0xF0      (float32, fractional, room space)
duplicates            x @ +0xFC    y @ +0x100
```

Proven by worker C from attract-mode jump arcs and walks, with no writes and no menu.
But ~300 records share this layout: particles (a trail stepping x 106→113 at y≈16),
chandeliers (21×42 box at x=904 whose bbox sits at x=613), arrows, decorations. A bbox
filter left 15 records and all were integer-valued props, so bbox is not the answer.

## Do NOT do any of these — they have burned four workers already

* **Do not touch the menu.** No entry attempt has ever been verified controllable, and
  `cpu_motion + sprite_present` both pass on the attract demo, so they prove nothing.
* **Do not use `poke` / `hold` / `accumulate`.** You do not need a single write. (The spy
  had an argument-order bug that made `add` a no-op and `hold` block for ~12 days; it is
  fixed, but writes are not your tool here.)

## Your discriminator: subtract, don't compare

A camera translate cancels in a difference. So for the true fighters:

```
(x_i - x_j)  ==  (sprite_x_yellow - sprite_x_orange)      (same for y)
```

The sprites give you that difference with no memory at all:
P1 is pure yellow `(255,255,0)`, P2 is orange `(255,160,64)`.

Suggested procedure:
1. Fresh instance, **attract mode** — just wait ~20 s, touch nothing. The demo fighters
   move on their own.
2. Sprite positions: build both masks and take a **robust centroid** — the goal flag is a
   big yellow blob too, so reject blobs far larger than a fighter (size and y filters).
   Sanity-check: the difference must be roughly stable across consecutive frames.
3. Records: dump the ~109 MB anonymous rw region as f32, step 0x200, keep records with
   fractional `x@+0xEC ∈ (0,960)` and `y@+0xF0 ∈ (15,260)`.
4. Pair search: all pairs, keep those where `|(x_i - x_j) - dx_sprites| < 4`  **and**
   `|(y_i - y_j) - dy_sprites| < 4`. Expect a handful.
5. Confirm over time, not once: take 6 samples ~0.4 s apart and require the *same* pair to
   keep matching the sprite difference as the fighters move. That is the real test — the
   camera changes between samples and must cancel every time.
6. Then look for a field that marks both as the same object type (compare bytes near +0x00
   and around the bbox at +0x120..+0x12C between your two records vs a particle record).
   Report the offset and whether it is shared by exactly two records.

## Rules

* Only your own farm/worktree/display (env vars are set). `nidstate.restart(0)` if needed.
* Budget: **25 minutes**. One `pairhunt.py` you iterate on; terse output.
* A negative with numbers is a valid answer. Never report an unproven pair as proven.

## Deliverable

`results/a.json`:

```json
{"tag": "a", "goal": "identify P1/P2 records", "found": false,
 "pair": [{"addr": "0x...", "x": 0, "y": 0}, {"addr": "0x...", "x": 0, "y": 0}],
 "sprite_delta": [0, 0], "match_error_px": [0, 0, 0, 0, 0, 0],
 "type_field": {"offset": "0x...", "shared_by_two": false},
 "refind": "how to pick the fighters again after a room change",
 "dead_ends": ["short notes"]}
```

Final message: 5 lines max (pair found / addresses / error across samples / type field /
dead ends). Stop there.
