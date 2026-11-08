## Common ground (read before acting)

* `docs/INTERFACE.md` — the contract and its provenance rules: **`proven` needs both the stimulus
  that reveals a field and the oracle that confirmed it**, twice, or it stays `inferred`/`unknown`.
* `docs/MEMORY.md` — every measured fact. The ones you will use: record stride `0x200`,
  `x@+0xEC`, `y@+0xF0`, `type@+0x88`, anim field `0xbc`, facing `0xd8`; the **tick counter runs at
  60 Hz** and can be found by its rate; **camera copies move 1000–2000 px per keypress** and are the
  biggest movers; the heap base changes per process, and **body addresses go stale after a
  transition** (they read frozen values).
* `scripts/qprobe.py` — identification to reuse: `identify(i)` (sign + walk-size + stop + sibling
  chain), `roles()`.
* Entry: `nidstate.enter_match_v2(i)` (~150 s), then wait 3 s (fighters fall from the sky).
* **Known trap**: a round left alone ~10 min freezes — bodies stop updating while the tick keeps
  running. That is your memory-only "frozen" test.

## Rules

* Your own farm `~/.nidfarm-<tag>`, own display band (env vars are set).
* **Never `pkill -f`** (it matches your own command line and has killed a worker). Use
  `pkill -x <exact name>`; never kill processes you did not start.
* Never reuse an address across processes or rooms.
* Do not edit shared files; put diffs in `results/<tag>.patch`.
* Budget **55 minutes**. A negative with numbers is a full result.

# Worker X — memory-only round and room identity (contract rows 11 and 15)

## Why this is the blocking job

`nidstate.in_match()` is **vision-based**: 2 of its 3 checks are screenshots (dark menu box, light-grey
wall column) and it costs ~1 s under load. It also flipped `False → True` across a *frozen* round.
"Drivable" cannot replace it — **READY is drivable too**. So a memory-only notion of "we are in a live
round, in room R" has to be found, and every other probe gets faster and more reliable once it exists.

## Goal

Two fields, both proven by a **controlled repeat-visit comparison**:

1. **room / stage identity** — a value that is the *same* every time we are in the same stage and
   *different* in another room (READY, stage select, castle).
2. **round phase** — an enum or small field distinguishing READY / live / ended, from memory alone.

## Method (the comparison is the whole trick)

Worker T failed at this because it compared only one transition (42 270 candidate slots). Do **two
cycles** so there is something to intersect:

```
READY  -> snapshot A1
match (castle) -> snapshot B1        # live round, after the 3 s settle
round ends (walk a fighter into its goal) -> back to READY/stage select -> snapshot A2
match (castle) again -> snapshot B2
keep slots where  A1 == A2  !=  B1 == B2
```

* Both directions must hold, otherwise a counter that happens to move will pass by luck.
* Snapshot cost: ~1.2 GB / ~2 s via one queued spy command file (`nidlinux.memory_many`). Do not take
  a screenshot in the middle of a comparison.
* For **round phase**, stay inside one castle visit and snapshot at: just after `GO` (live), and just
  after the round ends (ended). Any field that changes exactly at those boundaries is a candidate;
  then check it again on the second castle visit (B2) to prove it is phase, not noise.
* Confirm each candidate by **reading it in a third cycle**, or by showing it is stable across 10 s
  within a phase and flips within one sample across a phase change.

## Deliverable that matters most

A drop-in replacement for the vision check:

```python
def in_round(pid):        # memory only, no screenshots
    ...
```

Report the exact expression (which address, which comparison) plus its failure modes: what does it
say in READY, in stage select, in a frozen round, and when a body record has gone stale?

## Deliverable

`results/x.json`: `{"ok": false,
 "room": {"addr": "0x..", "kind": "index|pointer", "ready": 0, "castle": 0, "same_stage_stable": true},
 "phase": {"addr": "0x..", "values": {"ready": 0, "live": 0, "ended": 0}},
 "in_round_recipe": "the memory-only predicate, as code",
 "cycles": 2, "failures": {"ready": "", "stage_select": "", "frozen": "", "stale_body": ""},
 "dead_ends": []}`

Final message: 8 lines max.
