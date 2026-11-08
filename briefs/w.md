## Common ground (read before acting)

* `docs/INTERFACE.md` — the contract (15 rows) and its provenance rules. **Provenance admits only
  `proven` / `inferred` / `unknown`**, and `proven` needs both the *stimulus* that reveals a field
  and the *oracle* that confirmed it.
* `docs/MEMORY.md` — every measured fact: record stride `0x200`, `x@+0xEC`, `y@+0xF0`, `type@+0x88`,
  arm `+0x200`, sword `+0x400`; camera copies move 1000-2000 px per keypress and are the biggest
  movers; the heap base changes per process.
* `scripts/qprobe.py` — **the identification to reuse**: `identify(i)` picks P1/P2 by sign +
  walk-size + stop + sibling chain, `roles(p1, p2)` re-proves roles, `state(i)` reads
  `x, y, sword`. Run `python3 qprobe.py` for its synthetic self-check.
* Entry to a live match: `nidstate.enter_match_v2(i)` (~150 s). **Wait 3 s after it returns** — the
  fighters spawn high and fall. Probe within seconds: a round left alone ~10 min freezes and the
  winner walks off, which makes every "stopped" test fail.
* `nidstate.in_match(i)` = no menu + no wall + drivable. READY is drivable too, so drivability alone
  proves nothing.

## Rules (they exist because workers died this way)

* Your own farm `~/.nidfarm-<tag>`, own display band (env vars are set). Never share.
* **Never `pkill -f`** — it matches your own command line and has killed a worker. Use
  `pkill -x <exact name>`; never kill processes you did not start (other users share this box).
* Never reuse an address across processes or rooms; re-find by stimulus.
* Screenshots cost ~1 s under load; build timing on the memory path.
* Do not edit shared files (`nidstate.py`, `nidlinux.py`, `docs/`); put diffs in `results/<tag>.patch`.
* Budget **45 minutes**. A negative with numbers is a full result.

# Worker W — control timing, determinism, reset semantics

## Goal

Three numbers the RL loop needs: **action→observation latency**, **determinism**, and **what happens
when we write a position** (reset semantics).

1. Enter a live match, identify the bodies (`qprobe`).
2. **Latency.** Sample P1's `x` as fast as the spy allows; press `d` for one tick-ish duration; find
   the first sample where `x` moved and how many samples (→ ticks at ~60 Hz) after the key event.
   Repeat 10 times; report the distribution.
3. **Determinism.** From the same state run an identical key script twice (`d` 0.5 s, wait 0.5 s,
   `d` 0.5 s) and compare the two `x` traces. Report identical or the first divergence. The CPU
   opponent may break this — say so if that is what you see.
4. **Reset semantics.** With `nidlinux.accumulate`/`poke` on **P1's `x` only** (a proven field), move
   it +300 and watch 1 s: kept, snapped back, or crash? Twice. **If the game dies, that is a valid
   and important answer** — report it, do not retry blindly.

## Deliverable

`results/w.json`: `{"latency": {"samples": [], "median": 0, "p90": 0},
"determinism": {"identical": false, "first_divergence": "..."},
"reset": {"applied": false, "kept": false, "snapped_back": false, "crashed": false},
"dead_ends": []}`

Final message: 8 lines max.
