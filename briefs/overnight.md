## Common ground

* `docs/LAYOUT.md` — memory map, proven vs inferred. `docs/MEMORY.md` — all measurements + traps.
* `docs/workers/z_score.json` — read this first. Its conclusions are your starting point:
  * the HUD (`YELLOW WINS:` / `ORANGE WINS:`) is drawn **only on the READY screen**; score 0 draws
    **nothing**, 1 draws a 2 px bar. Digit rects: P1 `[56,14,80,30]`, P2 `[214,14,238,30]`.
  * 25 interval-candidates were all **eliminated by poking** (write landed, HUD unchanged).
  * **the score is NOT in the 15 regions the recorder dumped.** The live process has 7 more rw
    regions ≥1 MB (`0x8402000`, `0xa102000`, `0xa210000`, `0xc4f0000`, `0xd202000`, `0xd412000`,
    `0xece0000`) plus the 31 MB `[heap]`.
  * low-address regions keep **identical bases across processes** (`0x14a0000`, `0x16a0000`,
    `0xcd02000`, `0x102b2000`); high ones (`0x705a…`, `0x6fff…`) are ASLR'd and not mappable.
* `scripts/mine_session.py` — structural events from screenshots (fighter-presence, not motion).
* `scripts/qprobe.py` — `identify(i)` / `roles()`. `scripts/hunt_field.py` — interval-delta hunter
  (`--float`). `scripts/record.py` — records states/shots/heaps; `regions.json` maps offsets.

## Rules

* Your own farm `~/.nidfarm-<tag>`, own display band (env set). **Never `pkill -f`** (matches your own
  command line; it has killed a worker). Use `pkill -x`; never kill processes you did not start.
* Do not edit shared files; put diffs in `results/overnight.patch`.
* Poking arbitrary addresses can kill the game — one field at a time, `ping` after each, restore after.
* Disk: 9.8 TB free, keep the dumps. This is an overnight run: be systematic, log everything, and
  write intermediate results to `results/` as you go (do not save everything for the end).
* Budget: up to **7 hours**. A negative with numbers is a full result.

# Worker — overnight: record a round win with ALL regions, then find the score by poke+HUD

## The one thing that was wrong last time

The recorder dumped only the regions that contained 0x200 object records, so it **missed the 7 rw
regions (plus `[heap]`) where the score must live** — worker Z proved the score is absent from
everything we recorded. Fix that first, then repeat the experiment.

## Plan

**Step 1 — dump everything.** In your own copy of `scripts/record.py`, replace the region chooser
with *all* rw regions ≥ 1 MB plus `[heap]` (no "contains a record" filter), still writing
`regions.json`. Verify the dump size grows by roughly those 7 regions. Keep the 6 s cadence.

**Step 2 — win a round, recorded.** Boot a fresh instance (`nidstate.enter_match_v2`), get to a live
match, start the recorder, and then **win a round**:
* the cheapest attempt: walk ONE fighter toward its own goal line while the other stands still
  (try P1 with `d`, and if that fails, P2 with `Left`/`Right`);
* kills may be needed to pass substages — if so, walk into the opponent and press `f`;
* verify the boundary **structurally** (`scripts/mine_session.py` event kinds, or the HUD digit
  rect: blank → bar). Do not trust pixel motion for this.
If a round win proves impossible in the budget, fall back to: record whatever boundaries you do
reach (GO/winner screens count) and mine those.

**Step 3 — mine the new regions.** Slots that are `0` in every pre-boundary dump and `1` (or `1.0f`)
in every post-boundary dump, constant within each window. Last run this left 25 candidates *inside
the old region set* — restricted to the 7 new regions the list should be short.

**Step 4 — prove by poke + HUD.** For each survivor (and its neighbours ±0x20, since the score may
sit next to a partner field):
* get to the READY screen (HUD visible, score 0 → blank digits);
* write `1` (int) and `1.0f` (float) at the candidate, screenshot, and compare the two digit rects
  against a blank baseline: a **bar appearing** where there was nothing = the score field;
* then write `7` and check for a distinct glyph, to be sure it is really the drawn number;
* restore the original value, `ping` the process.
Return the address, the HUD evidence, and the offsets of the neighbouring fields you can name.

**Step 5 (bonus, if time).** Same treatment for the **round phase**: a field that is constant inside
a round and flips exactly at the boundary, verified by writing a different value and observing a
behavioural change (the game treating the round as ended, or the GO screen appearing).

## Deliverable

`results/overnight.json`:

```json
{"ok": false,
 "recorder":{"all_regions": true, "regions": 0, "dump_mb": 0},
 "round_win": {"achieved": false, "how": "", "boundary_time_s": 0},
 "candidates": {"pre_boundary_zero": 0, "post_boundary_one": 0, "in_new_regions": 0},
 "score": {"addr": "0x...", "hud_before": "blank", "hud_after": "bar", "glyph7": false, "proven": false},
 "phase": {"addr": null, "flips_at_boundary": false, "proven": false},
 "neighbours": [], "crashes": 0, "dead_ends": []}
```

Final message: 10 lines max — what changed, what was found, what is still unknown.
