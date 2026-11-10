# docs/INTERFACE.md — the contract (skeleton, to be filled)

**Provenance admits only `proven` / `inferred` / `unknown`.**
A field is `proven` only if the row names the *stimulus* that reveals it and the *oracle* that
confirmed it. Everything else stays `unknown`, however plausible it looks.

| # | field | source | stimulus | oracle | provenance |
|---|---|---|---|---|---|
| 1 | sword held / not held | sword object (own type) | attack / throw | **negative**: the sword record's x,y are bit-identical to the body's, so it is a body-anchored copy and cannot show "held" | unknown (negative) |
| 2 | sword x, y (both players) | sword object (type 0x1738b00/0x1720a00), *not* a fixed offset | walk | x,y bit-identical to the body in 200+ samples; **`body+0x400` is not stable** — the 0x200 chain reallocates (sword slid to +0x200 after minutes of play) | **proven** (+ offset caveat, worker U) |
| 3 | alive / dead | body record | kill the opponent | **negative + proven**: death is NOT a byte — the record keeps its address and type pointer and simply **stops updating** (x,y freeze forever) | proven (worker S) |
| 4 | attack key | `f` (also `g` jump, `s` crouch, `w` guard, `a`/`d` walk) | press it | arm extends +18 px, anim `0xbc` departs idle and returns; two passes agree | **proven** (workers R+U) |
| 5 | crouch / roll | anim field `0xbc` | press `s` | anim value 255 during the press, idle otherwise; **roll: not found** | crouch proven, roll unknown |
| 6 | thrown sword (projectile) | new object type | — | — | unknown |
| 7 | facing | **f32 @ +0xd8**, mirror at `arm+0xd8` | walk past the opponent | ±1.0 agrees with geometry for both players; flips on turn; 3 independent checks | **proven** (worker R) |
| 8 | velocity | derived: Δx between two reads | none | 40 px per 0.4 s hold measured | **proven** as derived (worker q) |
| 9 | stun / hit | anim field `0xbc` (candidate) | get hit | not yet isolated — the field exists and is mirrored at `+0x2bc`/`+0x4bc` | unknown |
| 10 | round score | HUD pips / int that increments | — | — | unknown |
| 11 | round phase | READY / live / ended | — | — | unknown |
| 12 | round timer | counting int | let it tick | **negative**: 878 int32 slots decrement at 60 Hz, none is selective | unknown |
| 13 | which instance is us (P1/P2) | input only: d/a vs arrows | hold the key | sign + walk-size + stop + sibling chain; 3/3 fresh instances. **Roles are NOT bound to addresses: they swap** (worker q attempt 4; human observation) — re-prove after every transition | **proven, must be re-proved per round** |
| 14 | tick / frame counter | **u32 @ heap-relative**, found by rate test | nothing (it ticks by itself) | 60.0 Hz, 4 % jitter over 10 s; 320 duplicate slots | **proven** (worker T; address is per process) |
| 15 | room / stage id | — | force a transition | **negative**: 42 270 stable-and-differing slots at the boundary; needs a second same-stage return to compare | unknown |

## Proven facts this table rests on

```
record stride 0x200   x @ +0xEC   y @ +0xF0   type @ +0x88
duplicates            x @ +0xFC   y @ +0x100
siblings              sword = body + 0x400   arm = body + 0x200
```

Known instance (one run, one room — the type pointer changes per run):

```
type 0x174f900 → 0x191c400  x=8.0   y=128   P1 (yellow sprite 8.7 px)
                 0x191bc00  x=202.0 y=128   P2
```

## Control-side contract

| item | requirement | status |
|---|---|---|
| control gate | **read-only**: input direction control (A) + record tracks sprite 1:1 (B) + no other record does (C) | **proven** — `nidstate.control_gate`; attracts fail A (0.0 px), READY passes 12/12 with median 0.87 px error; evidence in `docs/gate/` |
| action→observation latency | ticks from held key to visible state | **action send 0.17 ms** (`n.spy_key`, XTEST in-process; xdotool was 15.8 ms). Observer side is tick-aligned: `state()` costs 13 µs and a new sample appears within 1 ms of the game tick. Key-hold→visible-state is still ~30 ms (1.8 ticks) — that is the GAME's input poll, not ours |
| reset semantics | writing `x`/`y`: does physics snap back? | **proven: `x += 300` is KEPT** (no snap-back, no crash, 3 trials) — resets are viable (worker W) |
| address stability | stable within a room (re-proved after 10 s); **after a room/round transition the old addresses read frozen stale values** and the heap base does NOT move | proven both ways (workers T, W) |
| writes | `poke`/`hold`/`add` work on some fields but have **killed the game twice**; not used by any gate | unsafe, untested on the proven body record |
| state read cost | 6 reads ≈ **10 ms** (x, y, arm_x, sword x/y per player) | **proven** (worker q recipe) |
| death reallocation | do records move/allocate on death? | unknown |
| determinism | identical inputs from one reset → identical trajectory? | **effectively yes**: two identical scripts differ only by a constant 8 px carried-in offset, 3 px after removing it (worker W) |
