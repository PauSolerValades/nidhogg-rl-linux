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

# Worker R — keymap and animation/state fields (contract rows 4, 5, 7, 9)

## Goal

Discover **which key does what**, and which record field encodes the resulting action state. This
unblocks the sword and timing workers, so it is the highest-value brief.

1. Enter a live match, wait 3 s, run `qprobe.identify(i)` → session map (P1, P2 bodies).
2. For every plausible key (`f`, `g`, `h`, `j`, `k`, `l`, `space`, `w`, `a`, `s`, `d`, `q`, `e`,
   `Return`, arrows) — press once (0.3 s hold) and after each press dump a *wide* neighbourhood of
   the P1 body (±0x180 bytes) recording every 4-byte field that **changed and returned to its idle
   value within ~2 s**.
3. A field is the animation/state index if it takes a **distinct value per action** and returns to
   idle. Report offset, the value-per-key table, and repeat the sweep once to confirm the values agree.
4. Name actions from behaviour: which key swings the sword (attack), ducks (crouch/roll), turns the
   fighter (facing), launches it (jump), throws the sword (it should vanish from `body+0x400`).
5. Facing: a ±1 float, a sprite-flip flag, or a sign bit — say which, and prove it by turning around.

## Deliverable

`results/r.json`: `{"keymap": {"attack": "?", "jump": "?", "roll": "?", "throw": "?"},
"anim_field": {"offset": "0x..", "values": {"idle": 0, "walk": 0, "attack": 0}},
"facing_field": {"offset": "0x..", "kind": "float|flag", "proof": "..."},
"two_passes_agree": true, "dead_ends": []}`

Final message: 8 lines max.
