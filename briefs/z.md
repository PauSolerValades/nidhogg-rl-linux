## Common ground

* `docs/LAYOUT.md` — the consolidated memory map (proven vs inferred). Read it first.
* `docs/MEMORY.md` — every measurement, including the traps. Two that will bite you:
  **roles (P1/P2) swap**, so never infer role from an address; and **`+0x200`/`+0x400` reallocate**,
  so identify arm/sword by type+behaviour, not offset.
* `scripts/qprobe.py` — `identify(i)` / `roles()`; `scripts/hunt_field.py` — interval-delta hunter
  (`--float` for float32); `scripts/mine_session.py` — structural events from screenshots.
* Entry: `nidstate.enter_match_v2(i)` (~150 s), then wait 3 s (fighters fall from the sky).
* Recording sessions live in `~/nidhogg-record/<stamp>/`: `states.csv`, `shots/`, `heaps/`
  (284-386 MB each, ~60 dumps), `markers.txt` (human-narrated step times), `regions.json` (dump
  offset → base address map; **without it a dump offset is meaningless**).

## Rules

* Your own farm `~/.nidfarm-<tag>` / display band (env vars are set). **Never `pkill -f`** (it
  matches your own command line and has killed a worker); use `pkill -x`, never kill others' work.
* The human-recorded sessions are read-only data. Do not delete or overwrite them.
* Writing to arbitrary addresses **can kill the game** — that is an acceptable, reportable outcome,
  but never poke a range, poke one proven-plausible field at a time and check `ping` after.
* Do not edit shared files (`nidstate.py`, `nidlinux.py`, `docs/`); put diffs in `results/z.patch`.
* Budget **55 minutes**. A negative with numbers is a full result.

# Worker Z — find the score field by POKE + HUD, not by elimination

## Why you are doing it this way

Two sessions of interval-delta hunting produced 300-600 "candidates" that were all noise (timers
stepping by one). Elimination is the wrong tool. The game *draws the score on screen*
(`YELLOW WINS: n` / `ORANGE WINS: n`), so the field can be found by causality instead:

> poke a candidate to a distinctive value, screenshot, and see whether the HUD number changed.

That is a one-bit answer per candidate, it needs no statistics, and a false positive is impossible:
nothing else in the game draws that number.

## Data you have

`~/nidhogg-record/20261108-195634/` is the good one: 60 dumps (284 MB each), `regions.json`,
`markers.txt`, and screenshots at 2 Hz. The human won at least one round, killed and was killed,
and advanced two substages — all marked.

## Method

1. **Get the HUD geometry.** Boot your own instance, enter a match, screenshot, and locate the
   `WINS:` text region for both players (they sit in the top corners; the earlier sessions' shots
   are in the recordings if you want to look before booting). Record the exact rectangles and what
   "0", "1", "2" look like — a template per digit is enough, no OCR needed.
2. **Build the candidate list from the recording, cheaply.** Use `hunt_field.py`-style intersections
   over the marked intervals, but keep only slots that are constant within a round and change at a
   round boundary (session 2's `markers.txt` has one boundary plus the substage advances). Save the
   dump offsets and, via `regions.json`, their **base+offset** form.
3. **Verify by poke.** On your own live instance: read the candidate, write a distinctive value
   (e.g. `3` or `7`), screenshot, and compare the HUD digit templates. If the HUD changes, you have
   the score field — report the HUD evidence and the address. Restore the original value if you can.
4. **If the HUD approach fails**, fall back to a differential test with *short equal-length
   windows*: from a fresh match, snapshots every 2 s for 30 s; a score stays constant inside a round
   and steps only at a boundary, so require "constant over 10 consecutive same-length samples, then
   exactly one step". Report what survived.
5. Also worth 10 minutes: does the *round phase* show up as a small enum that changes exactly at the
   boundary (`markers.txt` gives you the time)? Same poke test applies: writing a phase value should
   visibly change the game's behaviour (e.g. make it think the round ended) — that is a strong oracle.

## Deliverable

`results/z.json`:

```json
{"ok": false,
 "hud": {"p1_rect": [0,0,0,0], "digits": {"0": "template path", "1": "..."}},
 "score": {"addr": "0x...", "hud_before": 0, "hud_after_poke": 0, "proven": false},
 "phase": {"addr": null, "values": {}, "proven": false},
 "candidates_tested": 0, "crashes": 0,
 "dead_ends": []}
```

Final message: 8 lines max.
