# Worker: authoritative instance identity (the engine's instance list)

## Why this is worth a session

The #1 operational failure in this project is **identity**: `find_fighters()` returns records
that may be frozen copies of the previous round, and roles (P1/P2) swap, so every transition
forces a re-identification by pressing keys (which costs 3–10 s and is unreliable on a
churning screen). That is not a measurement problem, it is a *lookup* problem — the engine
knows which instances exist, and this session proved that structure is visible from inside.

Your target is **not** to hook or patch game code. Everything here is read-only.

## What is already proven (2026-11-09, one session, two independent lists)

The engine keeps a **doubly-linked list of instances**. Node stride `0x80`:

```
+0x08  u64   flags        (0x101 seen)
+0x18  u64   object type pointer   <-- identical for both players in a pair
+0x30  u64   prev node     (0 = this is the head)
+0x38  u64   next node     (0 = this is the tail)
+0x40  u64   instance id   (consecutive: 0x1884f, 0x18850)
+0x48  u64   record pointer <-- the 0x200 record: x@+0xEC, y@+0xF0, facing@+0xD8, anim@+0xBC
```

Evidence:
* a 2-node list whose nodes shared type `0x16e8a00` and pointed at the two fighter records;
* a 10-node list of a different type whose records' x stepped by exactly 16 px (a spawn wave).
* The nodes live in region `0xece0000`, the records in `0x192da00`-ish (`0x16a0000` region).
* Globals **do** point at list heads (found 5 references to one head, all in the fixed-base
  regions `0xece0000` / `0x102b2000`) — the anchor exists but was not isolated.

**Node memory is recycled** across objects and rounds, so a node address is not an identity.
`find_fighters()` + pointer scan also works but costs ~1.2 s — that is a fallback, not an answer.

## Falsifiable targets, in order

**T1 — the anchor.** From a cold process, with no scanning, in < 1 ms, obtain the heads of the
instance lists. Acceptance: a function `nidstate.list_heads(pid) -> [node_addr, ...]` that is
stable for 10 s and whose walk contains every visible fighter.
Hints: `g_pObjectLists`-style array of head pointers (a short run of qwords pointing into the
node region, preceded/followed by plausible counts), or a single global head with `prev`/`next`
chaining all instances; the earlier naive cluster search produced 139k false hits because
records point at each other, so **discriminate**: a real *head* satisfies `prev == 0` and is
pointed to from a fixed-base region; a real node satisfies `node.x18` == the object-type pointer
of its own group and `node.x48` points at a `0x200` record with plausible x/y.

**T2 — identity survives a transition.** Get to a live match, note the player records, end the
round with the forfeit trick (pause → Down, Down → Enter → YES), and show that after the new
round starts the *same lookup* names the new player records **without pressing any key**.
Acceptance: two consecutive rounds, zero key presses used for identification.

**T3 — roles without input.** Decide which of the two is P1 (Yellow) without pressing keys, or
prove it cannot be decided and name the field that would decide it. Candidates: colour state in
the record, spawn order (ids are consecutive — which end of the id pair is Yellow?), the
`+0x18` type pointer if the two players are different objects after all (they were the *same*
type in every pair seen so far, which is itself a finding worth double-checking).

**T4 — generalise.** Given a type pointer, enumerate all live instances of that object
(`nidstate.instances_of(pid, type_ptr)`). This is what kills stale addresses everywhere.

## Method and traps

* Work on a **stable screen**: READY (fixed camera, pads) or a live match. The attract demo
  cycles every few seconds and every probe lands on a different list — that wasted a lot of
  this session.
* **Never read an unmapped address**: the spy reads through `fwrite`, so a bad pointer kills
  the GAME. Validate every candidate against `/proc/<pid>/maps` before reading (helper below).
* Roles swap; offsets reallocate; identify by structure + behaviour, never by address order.
* A one-off observation is not proof: every claim needs a second, independent pass.
* Budget **55 minutes**. A negative with numbers is a full result.

```python
# validated read helper — copy this, it prevents the crash above
def read(pid, addr, size):
    regs = nidstate.regions(pid, min_size=0x1000)
    if not any(lo <= addr and addr + size <= hi for lo, hi in regs):
        return None
    return nidlinux.memory_many(pid, [(addr, size, "/tmp/rd.bin")])[0]
```

## Deliverable

`results/<tag>.json`:

```json
{"ok": true,
 "anchor": {"addr": "0x...", "kind": "array|head-global", "walk_ms": 0.05},
 "player_type": "0x...",
 "T2": {"rounds": 2, "key_presses_for_identity": 0, "records": ["0x...", "0x..."]},
 "T3": {"role_decidable": false, "why": "..."},
 "T4": {"instances_of": 2},
 "dead_ends": []}
```

Plus a patch adding `nidstate.list_heads` / `instances_of` and one line in
`docs/TMP_CURRENT_STATE.md`. Final message: 8 lines max.
