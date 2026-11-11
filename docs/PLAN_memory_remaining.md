# Plan: the two remaining memory items (identity anchor, round phase)

Status: proposed. Companion to `docs/DECISION_sync_vs_async.md` (interface) and
`docs/TMP_CURRENT_STATE.md` §4 (what is missing before training).

---

## 0. What "done" means — and an uncomfortable fact

An episode loop needs three things from memory: **who** (records), **when** (round
boundaries), **what happened** (reward). Today, all three are available *without* the two
missing fields:

| need | today, without the missing fields | cost | weakness |
|---|---|---|---|
| who | re-prove identity by input at each round start (`find_players_by_input`, then verify with one spy press) | ~0.4 s per round | can pick a wrong pair on a churning screen (observed 5/5 failures in one session) |
| when | detect the `winner` screen / READY screen from a frame | ~15 ms per check, 5–10 Hz | needs screenshots; frame-cost is significant at 60 Hz |
| reward | count tally bars on the READY screen; delta per round | ~15 ms per round | only drawn on READY, so it is a per-round, not per-step, signal |

So neither missing field is a hard blocker — they remove two *fragile dependencies*
(guess-identity-by-input, screenshot-based phase). That matters because those dependencies are
exactly what produced the 5/5 identification failures and the wasted session on Gate A.

**Plan consequence: they are worth doing now, but they must not gate a first training run.**
Build the interim loop (§5) as soon as identity is reliable, and never wait on both.

## 1. Order: identity first, and not just for its own sake

The round-phase field is almost certainly a field of a live **instance** (a match/round
controller object). Once the instance list is readable, the phase hunt searches **the ~10–30
live instances** instead of 1.1 GB of heap. That is the difference between a 20-minute hunt and
the 2283-candidate dead end the project already paid for.

```
identity anchor  ->  instance list  ->  { record pointers,  object types }
                                              |              |
                                    round phase hunt   role (yellow/orange) without input
```

### What we already know about the list (measured 2026-11-09, two independent lists)

```
node stride 0x80
+0x18  object pointer      (identical for both players; NOT the record's own +0x88)
+0x30  prev node           (0 = head)
+0x38  next node
+0x40  instance id         (consecutive per creation)
+0x48  record pointer      -> the 0x200 record: x@+0xEC, y@+0xF0, facing@+0xD8, anim@+0xBC
```

Nodes live in region `0xece0000` (fixed base, not ASLR'd). **Node memory is recycled** between
rounds, so a node address is never an identity — only the walk from the anchor is.

---

## 2. Item A — the identity anchor

### A0. Tool: one spy extension worth having for every future hunt

`watch <addr> [<addr> ...]` (up to 16 u32s) → the publisher also writes
`/tmp/nid_watch_<pid>`: for each sample, the tick and those 16 values (fixed 128-byte record).
~40 lines in `spy/nidspy.zig`, reusing the existing 1 kHz sampler and tmp+rename publish.

Why: any candidate set becomes a **60 Hz time series**, so "does this field step exactly when
the round ends" stops being a guess. It is the instrument both remaining hunts need, and it is
also how the score hunt should be redone.

### A1. Find the anchor (structural signature search, not brute force)

The head pointers we saw live in the two fixed regions (`0xece0000`, `0x102b2000`) — 24 MB
total, ~100 ms to dump. A naive "points into the node region" search gives 139k false hits
(records point at each other), so **validate structurally instead of counting**:

```
for q in fixed_regions:                       # qword-aligned
    if not points_into(0xece0000 .. 0xf400000): continue
    if q % 8 != 0: continue
    n = node(q)
    if n.prev != 0: continue                  # must be a HEAD
    walk = follow_next(n, max=32)             # each step: next must be 8-aligned, in region,
                                              #   and node(next).prev == current
    if not chain_is_consistent(walk): continue
    if not any(record_is_plausible(n.record) for n in walk): continue
    -> candidate anchor
```

`record_is_plausible` = the discriminators we already use (mapped type pointer, `0 < anim <
10000`, `facing in {-1, +1}`, `0 <= x <= 2200`, `15 <= y <= 300`) — those five killed every
junk pair in the Gate A attempts.

### A2. Acceptance (all four, in order — any failure means not done)

1. **Cold process**: from `start_ids`, `instance_list(pid)` returns a walk containing both
   fighters within 200 ms, with **no key presses**.
2. **Cross-process**: the anchor address is the same in a second fresh process (fixed region ⇒
   it should be; if it differs, fall back to A1's search per round, still ~100 ms).
3. **Liveness**: press `d` via the spy, and the record read *through the walk* moves by the
   same delta as a direct read (proves the walk is not a stale copy).
4. **Survives a transition**: win a round (forfeit), start the next, and the walk again contains
   the players **without any identification key press**. Repeat for 2 rounds.

### A3. Fallback (do not treat as failure)

If no stable anchor exists: run the signature search **once per round** (~100 ms). Identity is
needed per round, not per frame, so 100 ms is free. The anchor's real value is that it makes
identity cheap enough to also use *per frame* for safety checks.

### A4. Traps (each has already cost this project time)

* Never read an unmapped address — the spy reads via `fwrite`, so a bad pointer kills the game.
  Validate every candidate against `/proc/<pid>/maps` and re-check the bound at track time.
* Node addresses are recycled: never cache a node, always walk from the anchor.
* Roles still swap: the list gives *which two*, not *which is yellow*. Getting yellow/orange
  without input is a separate, smaller question (candidates: list order, id order, a colour
  field). If none is structural, one 0.17 ms press per round is acceptable — but say which.

---

## 2.9 Item A — DONE 2026-11-11

Solved, and not in the shape the plan guessed (that is the point of writing it down):

* **The anchor is per object type, not a global**: the head of a type's instance list is stored
  at `object_definition + 0xa0`, the same offset for every type checked.
* **Bootstrap** costs one full rw dump (~1.2 s) once per process: record -> node -> node.type.
* **Then identity is a lookup**: `nidstate.type_of_record` + `instances_of_type`, a handful of
  reads per round.
* The object-definition pointer **changes across a round** (`0x16e9900` -> `0x16e8c00`), so
  re-resolve per round instead of caching. Node memory is recycled as expected.
* `scripts/anchor_scan.py` is the discovery tool (structural chain validation, no hardcoded
  regions); `scripts/identity_live.py` is the acceptance test, and it passes all four criteria —
  including a round transition with zero identification key presses.

## 3. Item B — round phase

### B1. Boundary diff, with exact timing and both directions

The previous hunt failed by matching *values*; the fix is to require the value to **step exactly
at the boundary, in both directions**:

1. Live match → dump all rw regions → `D0`.
2. Note the tick (`n.state(pid).tick`).
3. Forfeit → winner screen (confirm by frame) → dump `D1`.
4. Continue → READY → dump `D2`.
5. Start the next round → dump `D3`.

A phase field must satisfy: `v(D0) != v(D1)`, `v(D1) == v(D2)`, `v(D2) != v(D3)`. That is one
comparison per 4-byte slot over ~1.1 GB of dumps — seconds, and it removes every monotone
counter and every one-way flag. Then require the surviving set to be small (< 50); if not, add a
third boundary and intersect.

### B2. Constrain the search with the instance list (why A comes first)

Intersect the B1 candidates with the address ranges of the live instances found by A. The phase
lives in one of them; this typically cuts hundreds of candidates to single digits. If A is not
done yet, skip this and accept a bigger candidate set.

### B3. Watch the candidates at 60 Hz (uses A0)

Put the survivors into `watch`. Over 5 boundaries check which one steps on exactly the tick the
winner screen appears, and never in between. A field that steps at the boundary *and* is stable
inside a round is the phase field; anything that steps more often is a counter.

### B4. Behavioural write test — the decisive one

Read-only correlation is necessary, not sufficient (the score taught us that a value can match
the screen and drive nothing). So:

* At the winner screen, write the candidate's "live" value → the round should resume immediately.
* At READY, write "round over" → the GO/winner transition should happen.
* Integers only, one candidate at a time, `ping` after every write, restore between.
* PASS = the *behaviour* changes, twice, in both directions.
* FAIL = the value changes but nothing happens (that is what the 2283 poke attempt found).

### B5. Interim, so training is never blocked

Detect the round end from the frame: the `winner` screen is a full-screen state with a bright
centred wordmark and no fighters. A 5 Hz check costs ~75 ms/s of CPU (0.4% of a core) and is
enough for per-round reward. Ship this if B1–B4 overrun.

---

## 3.9 Item B — first two passes: what happened (2026-11-11)

**B1 (worker, `briefs/b1.md` → `~/nidhogg-rl-b1/results/b1.json`): honest negative, three findings.**

* 3 boundaries / 15 dumps / 276 M u32 slots: 2.44 M changed at a boundary → 691 k idle-stable →
  206 k after the second boundary → 763 under the strict cycle rule. The top cluster (702 of 763)
  is **HUD text draw alpha** — a *consequence* of the boundary, not the phase. Shortlist of 33
  non-graphics slots decodes as string/alpha fragments and sizes.
* **Finding 1 (a real bug, now fixed):** the spy's command loop read into a **4 KiB** buffer, so a
  large `memory_many` batch silently lost its tail — 29 of 119 regions were missing from its first
  dump and nothing reported it. Buffer is now 1 MiB and the client chunks by *bytes*; proven with
  a 4000-request batch (4000/4000, previously ~160).
* **Finding 2:** region identity is the **base alone** — a region at `0x102b2000` grows and
  shrinks (6.9→7.5 MB), so keying dumps by base+size hides megabytes between comparisons.
* **Finding 3:** the forfeit dialog **repaints nothing** when `Right` moves the cursor, so a pixel
  diff calls the press "swallowed" when it landed (3/3 forfeits did work, verified by the winner
  screen). Do not use a frame diff to check that dialog.

**B2 (here, `scripts/phase_b2.py`): instance-scoped boundary diff.** Enumerates live instances
(type structs → `type+0xa0` → chain, 6120 records = 3.7 MB) and diffs only those across the
boundary — 2.7 GB → 3.8 MB. First cut: 4395 changed slots, **209 with small (enum-like) values**.
Then adding "constant within a phase" reduced it further, but the run could not complete:
**`forfeit → READY` was not reliable enough to assert on**, and that is the point —

> the boundary oracle is the thing being hunted. Use the worker's verified oracle (the **winner
> screen**, detected from the frame) instead of `on_ready_screen`, which is too strict.

**Next pass for B3/B4:** take the 209 small-value candidates, put them in `watch` (16 at a time),
and record over ~10 boundaries with the winner screen as the ground truth. Keep what flips exactly
once per boundary in both directions; then write-test the survivors.

## 4. Parallelisation — two lanes, one farm each

The two items are independent *except* that B2 wants A's output. So:

| lane | owns | can start | must not touch |
|---|---|---|---|
| **A (identity)** | `nidstate.instance_list`, `scripts/anchor_scan.py`, spy `watch` | immediately | `docs/`, `nidstate.find_fighters` |
| **B (phase)** | `scripts/phase_hunt.py`, boundary diff, write test | immediately on B1 (dumps + directions); B2 waits for A | `docs/`, `nidlinux.py`, `nidstate.py` |

Rules that today's session proved the hard way:

* **One farm per lane**, with its own `NIDTAG` and display band. `start_ids()` calls
  `clean_farm()`, which stops *every* instance in that farm — two lanes in one farm kill each
  other.
* A new farm needs a `template` (`cp -a --reflink=always ~/.nidfarm-score/template <farm>/`), or
  `start_ids` fails with `cp: cannot stat .../template`.
* Never `pkill -x Nidhogg.exe`: the box is shared and a broad kill is not ours to run.
* Every claim goes into `state/claims.jsonl` with a **stable** `cmd` (no pids, no counts) and a
  falsifier that exits `2` for "could not run", `1` only for "claim false".

## 5. Definition of done

```
[ ] A: nidstate.instance_list(pid) -> the player records, no key presses, < 200 ms
[ ] A: survives a round win, twice, zero identification presses
[ ] A: cross-process (same anchor, or per-round search)
[ ] B: candidates step exactly at the boundary in both directions (60 Hz watch)
[ ] B: writing the field changes the behaviour, both directions, twice
[ ] both: recorded in state/claims.jsonl, verify -> OK
[ ] one interim path exists (screenshot phase oracle) so the trainer is never blocked
```

## 6. Effort and stop rules

| item | estimate | stop rule |
|---|---|---|
| A0 `watch` | 30 min | — |
| A1 anchor search + A2 acceptance | 60–90 min | if no anchor validates in 90 min, take A3 (per-round search) and move on |
| B1 boundary diff | 45 min | if > 200 candidates after 3 boundaries, add the instance-list constraint (B2) rather than more boundaries |
| B2 + B3 watch validation | 45 min | — |
| B4 write test | 30 min | **if 20 candidates fail the behaviour test, stop and use B5** — that would mean the phase is not a plain writable field, and the screenshot oracle is the answer |

Total ≈ 3 h of agent time, ≈ 2 h wall clock if A and B run in parallel. Both are *memory
quality of life*: if either overruns its stop rule, the training loop still ships with the
interim path.
