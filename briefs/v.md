# Worker — make entry + verified session map work end-to-end, twice in a row

## What is already proven (do not re-derive)

* Game runs at ~60 fps here (Proton-GE + wined3d, no GPU). Menu is navigable; the entry path is
  title → `Return`×3 → READY (multiplayer local) → walk each fighter onto its own coloured pad →
  stand ~2 s → match.
* Memory layout: stride `0x200`, `x@+0xEC`, `y@+0xF0`, object-type `u32@+0x88` (all float32/u32).
* A previous worker **verified** the fighter pair by causality in a live match:

  ```
  'd'     -> P1 x 897 -> 967 (+70), then stops;  P2 x 1023 bit-identical
  'Right' -> P2 x 1023 -> 1095 (+72), then stops; P1 x 967 bit-identical
  ready pair 0x191c400/0x191bc00   match pair 0x190dc00/0x190d400   type 0x174f900
  ```

  Their full report: `~/Developement/nidhogg-rl-m/results/m.json` (read it — it lists five dead
  ends that will otherwise cost you the session).
* **Two traps they documented:** a match left alone ~10 min ends its round and all fighter records
  freeze; and pressing `Return` during play burns the round. Probe within seconds of entering.
* `nidstate.py` already has: `ensure_match(i)`, `find_fighters(pid)`, `find_fighters_verified(i)`,
  `pad_and_fighter(i, which)`, `walk_onto_pad(i, which)`, `match_state(i)`, plus `nidlinux.fps(i)`.

## What is broken

Running it on a fresh instance in farm `~/.nidfarm-test` fails:

```
state=unknown → enter_ready ok → "on pads: yellow=True orange=False"
→ "advanced past READY: True" (FALSE POSITIVE) → restart → repeat 3× → give up
find_fighters -> 0 records
```

So: (a) the **orange pad is never detected** by `pad_and_fighter` (its colour may differ from the
orange *fighter* `(255,160,64)`), (b) "advanced past READY" is measured with the yellow pad, which
the fighter covers once standing on it — so it reports success when nothing happened, and
(c) after all that, `find_fighters` returns nothing.

## Your job

Make this work end-to-end, twice consecutively, from a cold instance:

```python
n.start_ids([0]); wait for window; sleep 12          # splash ignores input
s.ensure_match(0)                                     # -> True
s.find_fighters_verified(0)                           # -> {"P1":…, "P2":…, "trace":…}
```

Suggested order:
1. Get to READY and **measure the pads**: dump the actual RGB colours of the yellow pad, the orange
   pad, and both fighters (they are not necessarily the same colours). Fix the mask.
2. Replace the "advanced" signal with something real — e.g. pads gone **and** `find_fighters_verified`
   succeeding, or the fighter records moving on a key press.
3. Debug why `find_fighters` returns 0 records in this farm while worker `m` got results in theirs.
   Check `nidstate.regions(pid)`: how many regions ≥1 MB, their sizes, and whether the record
   pattern exists in any of them. Report the region that contains the records.
4. Prove it twice in a row (a restart in between), and print timings for each stage.

## Rules

* Your own farm `~/.nidfarm-v`, display band `:220`. Source env first, then override:

  ```bash
  . ~/Developement/nidhogg-rl-install/results/env.sh
  export NIDFARM=$HOME/.nidfarm-v NID_DISPLAY_BASE=220 NID_GAME_DIR=$HOME/.nidfarm-v/game
  ```
* **Never `pkill -f`** (it matches your own command line). Use `pkill -x <exact name>` and never
  kill processes you did not start — other workers share this box.
* Do not edit shared files; put diffs in `results/v.patch`.
* Budget **40 minutes**.

## Deliverable

`results/v.json`: `{"ok": bool, "runs": [{"enter_s": 0, "verified": {}, "fps": 0}], "pad_colours":
{"yellow": [0,0,0], "orange": [0,0,0]}, "advanced_signal": "...", "records_region": "0x...",
"root_cause": "...", "blockers": []}` and `results/v.sh`. Final message: 8 lines max.
