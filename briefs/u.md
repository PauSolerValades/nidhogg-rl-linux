# Worker U — sword lifecycle (contract rows 1, 6)

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

Four distinguishable sword states: **held**, **thrown (in flight)**, **stuck in scenery**, **on the
ground**. Row 1 (held or not) and row 6 (thrown sword = a projectile the opponent must avoid).

Method:
1. Enter a live match and identify the bodies. The sword is `body+0x400` and already provable: it
   moves with the body.
2. Find the **attack and throw keys** yourself if worker R's keymap is not in `docs/INTERFACE.md`
   yet: sweep `f`, `g`, `h`, `j`, `k`, `l`, `space`, `w`, `q`, `e` with 0.3 s holds and watch
   whether the sword record (a) swings with the body, (b) stops following the body, (c) disappears.
3. For each state, record: sword `x/y` relative to the body, whether the `+0x400` record still
   exists, and any field that changes (a state int, a velocity, a "thrown" flag).
4. For the projectile: after a throw, search the heap for a record of a **different object type**
   (u32@+0x88) that moves fast and then stops — that is the flying sword. Report its type value and
   how to distinguish "in flight" from "stuck".

## Deliverable

`results/u.json`: `{"keys": {"attack": "?", "throw": "?"},`
`"states": {"held": {"sword_x_equals_body": true}, "thrown": {"new_type": "0x..", "speed_px_s": 0},`
`"stuck": {"how_to_tell": "..."}, "on_ground": {"how_to_tell": "..."}},`
`"held_flag": {"offset": "0x..", "proof": "..."}, "dead_ends": []}`

Final message: 8 lines max.
