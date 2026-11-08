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

# Worker T — room/stage identity and a tick counter (contract rows 15, 14)

## Goal

Two load-bearing fields: **which room are we in** (so cached addresses are invalidated correctly) and
**a monotone tick counter** (so observations can be timestamped).

1. Enter a live match, identify the bodies. Snapshot the heap (all rw regions ≥1 MB) twice, 1 s apart,
   and keep fields that **incremented by ~60** in that second → tick candidates. Verify by sampling
   once every ~0.5 s for 10 s: the rate must stay ~60/s (±20%).
2. For the room: force a transition **without quitting the game** — let a round end (winner walks off,
   stage select follows). Snapshot before/after and look for a field that changes **exactly once** at
   the transition and is the same value when you return to the same stage. Say whether it looks like
   an index (small int) or a pointer.
3. State what must be re-resolved when it changes: body addresses, heap base, or nothing.

## Deliverable

`results/t.json`: `{"tick": {"addr": "0x..", "rate_hz": 0.0, "jitter": ".."},
"room": {"addr": "0x..", "kind": "index|pointer", "value_before": 0, "value_after": 0},
"invalidates": "addresses|heap base|nothing", "dead_ends": []}`

Final message: 8 lines max.
