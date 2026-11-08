# docs/INTERFACE.md — the contract (skeleton, to be filled)

**Provenance admits only `proven` / `inferred` / `unknown`.**
A field is `proven` only if the row names the *stimulus* that reveals it and the *oracle* that
confirmed it. Everything else stays `unknown`, however plausible it looks.

| # | field | source | stimulus | oracle | provenance |
|---|---|---|---|---|---|
| 1 | sword held / not held | `body+0x400` record | — | — | unknown |
| 2 | sword x, y (both players) | sibling `+0x400` `+0xEC`/`+0xF0` | walk / turn | sword Δ == body Δ (40 px, 3/3 runs) | **proven** (worker q) |
| 3 | alive / dead | type group size < 2 | — | — | unknown |
| 4 | attack key | animation field `+0x58`/`+0x64` | — | — | unknown |
| 5 | crouch / roll | animation field | — | — | unknown |
| 6 | thrown sword (projectile) | new object type | — | — | unknown |
| 7 | facing | ±1 float / sprite flip | — | — | unknown |
| 8 | velocity | derived: Δx between two reads | none | 40 px per 0.4 s hold measured | **proven** as derived (worker q) |
| 9 | stun / hit | animation field | — | — | unknown |
| 10 | round score | HUD pips / int that increments | — | — | unknown |
| 11 | round phase | READY / live / ended | — | — | unknown |
| 12 | round timer | counting int | — | — | unknown |
| 13 | which instance is us (P1/P2) | input only: d/a vs arrows | hold the key | sign + walk-size + stop + sibling chain; 3/3 fresh instances | **proven** (worker q) |
| 14 | tick / frame counter | monotone int | — | — | unknown |
| 15 | room / stage id | invalidates cached addresses | — | — | unknown |

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
| action→observation latency | ticks from held key to visible state | unknown |
| reset semantics | writing `x`/`y`: does physics snap back? | unknown |
| address stability | stable within a room (re-proved after 10 s); after a room change re-find by input, never reuse | **proven within a room**, inferred across rooms |
| writes | `poke`/`hold`/`add` work on some fields but have **killed the game twice**; not used by any gate | unsafe, untested on the proven body record |
| state read cost | 6 reads ≈ **10 ms** (x, y, arm_x, sword x/y per player) | **proven** (worker q recipe) |
| death reallocation | do records move/allocate on death? | unknown |
| determinism | identical inputs from one reset → identical trajectory? | unknown |
