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

# Worker S — death, round score, round phase, timer (contract rows 3, 10, 11, 12)

## Goal

Map the **round-level** state: is a player alive, who won the round, is the round live, how much time
is left.

1. Enter a live match, identify both bodies (`qprobe`), then **play a round out**: run a fighter into
   its goal so the round ends (the winner runs off with the "GO" arrows). Watch the screen at ~1 Hz
   so you know *when* it changed.
2. Before/after the transition, dump the heap and diff: find
   * what happens to the **body record** on death — destroyed? x frozen? a flag set?
   * an **int that increments** on a round win (cross-check the HUD's `YELLOW WINS: n` against a
     screenshot),
   * a **counter that decrements** over the round (the timer).
3. Play a second round and confirm each finding **twice** — same field, same direction.
4. Report round **phase** as a small enum if you can find it: READY / live / ended / stage-select, and
   say how these are distinguishable from memory alone (the RL episode logic needs this).

## Deliverable

`results/s.json`: `{"alive_field": {"offset": "0x..", "proof": "..."},
"score": {"addr": "0x..", "before": 0, "after": 1, "hud_agrees": true},
"timer": {"addr": "0x..", "t0": 0, "t1": 0},
"round_phase": {"addr": "0x..", "values": {"ready": 0, "live": 0, "ended": 0}},
"rounds_observed": 2, "dead_ends": []}`

Final message: 8 lines max.
