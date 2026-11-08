# Worker W — control timing, determinism and reset semantics

## Common ground (read before acting)

* `docs/INTERFACE.md` — the contract (15 rows) and its provenance rules. **Provenance admits only
  `proven` / `inferred` / `unknown`**, and `proven` needs both the *stimulus* that reveals a field
  and the *oracle* that confirmed it.
* `docs/MEMORY.md` — every measured fact: record stride `0x200`, `x@+0xEC`, `y@+0xF0`, `type@+0x88`,
  arm `+0x200`, sword `+0x400`; camera copies move 1000-2000 px per keypress and are the biggest
  movers; the heap base changes per process.
* `scripts/qprobe.py` — **the identification to reuse**: `identify(i)` picks P1/P2 by sign +
  walk-size + stop + sibling chain, `roles(i, p1, p2)` re-proves roles, `state(i)` reads
  `x,y,sword`. Run `python3 qprobe.py` for its synthetic self-check.
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


## Goal

Three numbers the RL loop needs: **action→observation latency**, **determinism**, and **what happens
when we write a position** (reset semantics).

Method:
1. Enter a live match and identify the bodies (`qprobe`).
2. **Latency.** Sample `x` of P1 as fast as the spy allows; press `d` for exactly one tick-ish
   duration; find the first sample where `x` moved, and how many samples (→ ticks at ~60 Hz) that
   took after the key event. Repeat 10 times, report the distribution.
3. **Determinism.** From the same state, run the identical key script twice (e.g. `d` for 0.5 s,
   wait 0.5 s, `d` for 0.5 s) and compare the two `x` traces. Report whether they are identical,
   and if not, the divergence. Note that other actors (the CPU opponent) may break this — say so if
   that is what you see.
4. **Reset semantics.** Using `nidlinux.accumulate`/`poke` on **P1's `x` only** (a proven field),
   move it by +300 and watch for 1 s: does the game keep it, snap it back, or crash? Repeat twice.
   **If the game dies, that is a valid and important answer** — report it and do not retry blindly.

## Deliverable

`results/w.json`: `{"latency": {"samples": [], "median": 0, "p90": 0},`
`"determinism": {"identical": false, "first_divergence": "..."},`
`"reset": {"applied": false, "kept": false, "snapped_back": false, "crashed": false},`
`"dead_ends": []}`

Final message: 8 lines max.
