# Worker A — extract the object-type field and enumerate the fighters

GameMaker YYC game, headless under Proton, no symbol table. Read `docs/MEMORY.md` first.

## Where we are

Layout proven (worker C) and **P1's record identified** (round 5):

```
record stride 0x200    x @ +0xEC    y @ +0xF0 (feet)     dup x @ +0xFC
round 5 found P1 at 0x191c400 on the READY screen, with 8/8 `d`/`a` transitions
tracking the yellow sprite 1:1 (worst error 1.78 px, camera fixed).
siblings: 0x191c800 = sword (same position), 0x191c600 = arm (x offset -8)
```

Addresses change per room and per run, so do not reuse `0x191c400` — re-derive it.

**Your job is the last missing piece:** find the field that identifies the *object type*, so
instances can be enumerated in any room without any camera or sprite logic. That unlocks
P1, P2 and the sword as a state interface.

## Procedure

1. `nidstate.enter_match(0)` → LOCAL READY, gated so it returns True only if P1 is
   drivable. If False: `nidstate.restart(0)` and retry. Do not debug the menu.
2. Prove the preconditions yourself: `drivable(0,'d') > 15`, `drivable(0,'a') > 15`, and
   the background must NOT shift when the sprite moves (fixed camera).
3. Re-find P1's record: alternate `d`/`a` 8 times (hold 0.5 s), and over **all** 0x200
   records in the ~109 MB rw heap keep the one whose `x@+0xEC` delta equals the sprite's
   delta (`nidstate.yellow_screen_x`) within 3 px on ≥7 of 8 transitions. Note: READY
   positions are **integer screen space**, so do not filter for fractional values.
4. Dump ±0x120 bytes around P1's record and around the sword/arm siblings. Identify a
   candidate **type field**: an int or pointer whose value is *equal for the two fighter
   records* and *different* for the sword, the arm, and a particle record. Look at small
   ints near the start of the record, and at any 8-byte value that points into the same
   heap.
5. Enumerate: scan all 0x200 records for that exact type value. The set should contain
   P1's record, and its members' `x@+0xEC` must match the visible fighters.
6. **Cross-check with P2.** The orange sprite `(255,160,64)` is not drivable on READY, but
   with a fixed camera its centroid x must equal the other fighter record's `x@+0xEC` 1:1
   (compare `nidstate.orange_x` against each candidate). If the type set contains a record
   that tracks orange, the type field is right.
7. Report the recipe: "scan 0x200 records in heap H, keep those with type field T == V;
   x@+0xEC / y@+0xF0 are positions; sword instance is the sibling at +0x400".

## Rules

* **No writes.** No `poke`/`hold`/`accumulate` — not needed, and that path has burned
  three rounds.
* Only your own farm/worktree/display (env vars are set). `nidstate.restart(0)` on trouble.
* Budget: **25 minutes**. One `typehunt.py` you iterate on; terse output.
* A negative with numbers is valid. Never report an unproven field.

## Deliverable

`results/a.json`:

```json
{"tag": "a", "goal": "object-type field + instance enumeration", "found": false,
 "p1_record": "0x...", "type_field": {"offset": "0x...", "value": "0x...", "width": 4},
 "instances": [{"addr": "0x...", "x": 0, "y": 0, "role": "P1|P2|sword"}],
 "p2_cross_check_px": [], "refind": "scan recipe", "dead_ends": ["short notes"]}
```

Final message: 5 lines max (P1 record / type field / instances found / P2 cross-check error /
dead ends).

## Never kill by pattern (this killed an earlier worker)

Your brief is passed on stdin, but **an agent's own process carries the whole brief in its
command line** when it is passed as an argument — and even now, `pkill -f <word>` can match
your own shell. So:

* use `pkill -x <exact-process-name>` (e.g. `pkill -x Xvfb`, `pkill -x Nidhogg.exe`) — never
  `pkill -f`;
* if you must match a pattern, exclude yourself: `pgrep -f 'Xvf[b] :41'` (the bracket trick).
