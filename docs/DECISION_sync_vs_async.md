# Decision: external (async, read-only) interface over an in-engine hook

**Status: DECIDED, 2026-11-09.** The loop reads memory and injects input *without* waiting for the
engine. An in-process frame hook is not scheduled. This document is the reasoning, the evidence
that killed the alternative, and the narrow conditions under which the decision reopens.

Replaces `docs/PLAN_frame_sync.md` (the gate plan this came out of).

---

## 1. The question, and why "three paths" was the wrong framing

The proposed alternatives were: (P1) dump memory asynchronously, (P2) hook the engine's update
function so our code runs inside the frame, (P3) a "middle ground". But the paths were bundling
**two independent axes**, which is what made the comparison confusing:

|  | identity: we infer it | identity: the engine gives it |
|---|---|---|
| **clock: async** | P1 — what we had | P3 — instance list (found, see §4) |
| **clock: in-frame** | pointless: perfect timing, wrong record | P2 — both, and the corner P2 was reaching for |

P2 as described ("find the update function, replace it, run the agent there") needs the engine to
give us identity *and* the clock. P3 gives only identity. So the real question is not "which path"
but "**does the clock half justify its own cost, given identity is obtainable without it?**"

That is answerable, and the answer is no — for four reasons, in §5.

## 2. What the async interface actually delivers (measured, not argued)

| property | number | how |
|---|---|---|
| observation completeness | **61.4 samples/s, `tick deltas {1: 59}`** | one published sample per game tick, zero missed |
| publish alignment | **16.37 ms p50 / 17.45 max** between samples | game tick is 16.67 ms |
| cost to read the whole state | **13 µs** | 128-byte fixed-size file, tmp+rename |
| cost to act | **0.17 ms p50** | XTEST from inside the game process (~93x cheaper than an `xdotool` fork+exec at 15.8 ms) |
| command round trip | **2.4 ms p50** (was 51 ms) | 2 ms poll, was a hard-coded 50 ms |
| our own per-step overhead | **~0.2 ms of a 16.7 ms budget** | read + act |

So the loop is not merely "good enough": it occupies ~1% of the frame, and observation is
provably complete. There is no missing data and no timing debt being accumulated.

## 3. What killed the in-engine hook (P2)

The expensive half of P2 is *finding* the update function. On this build it is not findable
cheaply, and the target it would give us does not exist:

| check | result |
|---|---|
| `gml_*` name strings in `Nidhogg.exe` | 15,666 |
| PE export table for game code | **none** |
| COFF symbol table (`objdump -t`) | empty |
| PDB | referenced (`G:\GIT_REPOS\...\Nidhogg.pdb`) — **not shipped** |
| pointers to those name strings in the file | **0** — the names are debug strings with no address table |
| `gml_Object_YellowPlayer_Step_0` | **does not exist**; the players have only Create + Destroy |
| the input poll (`__InputUpdateController_Step_1`) | exists by name, has no address |

The prize of a Step hook was `self` (the instance pointer) in RCX on every frame. There is no Step
event to hook, and the runner's frame loop is unsymbolised code inside a 25 MB stripped binary —
days of reverse engineering, with a real chance of a dead end.

Two more things that don't survive scrutiny:

* **The hook does not remove memory work.** `x` is still at `+0xEC`. A hook is a *clock*, not an
  interface: it changes when you read, not how.
* **"The game stops, so writes are precise"** was the other stated benefit. We do not write memory
  in the loop at all; and episode resets do not need a freeze, because the game reads x/y once per
  tick — write every field inside one frame window (each write is ~1 µs) and the game never sees a
  half-reset world.

## 4. What we found instead — and it is better than the hook's identity half

GameMaker keeps a **doubly-linked list of instances** (node stride `0x80`):

```
+0x18  object type pointer      identical for both players
+0x30  prev node (0 = head)
+0x38  next node
+0x40  instance id              consecutive: 0x1884f, 0x18850
+0x48  record pointer           the 0x200 record: x@+0xEC, y@+0xF0, facing@+0xD8, anim@+0xBC
```

Verified on two independent lists (a 2-node player pair; a 10-node spawn wave whose x stepped 16
px). It is **read-only** — no code patching, no crash risk, no data.win coupling.

Open work: node memory is recycled between rounds, and the anchor (the global that points at the
head) is not isolated yet. That is a bounded task, not research — `briefs/instance-list.md`.

## 5. Why the clock half still does not justify a hook

**1. `step()` already exists.** One decision per frame = wait for tick T → send input (0.17 ms) →
wait for tick T+1 → return obs, with zero missed frames. The tick counter provides the
coordination; the hook was never what provided the API.

**2. The hook fixes none of the blockers.** Round phase, episode reset, reward: all remain. It
would not fix identity either (§3). A plan that starts with the hook spends days before it can
begin on what actually blocks training.

**3. At its best, it buys a constant.** One tick of delay instead of "one tick, occasionally two".
A *constant* lag is an MDP with a fixed delay: learnable, and compensable by acting one tick
early. A training run that needs sub-frame precision but cannot tolerate a fixed one-tick lag is
close to a contradiction.

**4. The costs are asymmetric, and that is the tiebreaker.**

| | build it now | defer it |
|---|---|---|
| if unnecessary | days + a patched renderer permanently in the loop, 15-instance farm becomes hook-dependent | nothing lost |
| if necessary | ahead | add it later — it is **additive**: same spy, same `step()`, same state file |

When one branch is reversible and the other is not, and the evidence is incomplete, take the
reversible one. That is not a compromise; it is the correct move under uncertainty.

## 6. Verdict

**The async, read-only loop is the approach.** Not "the safest of three" — the only one that can
carry the project to a first training run, with the hook as an optional accelerator on top.

**D1 (build the frame hook) = NO, and it is not scheduled.**

Next work, in order: identity (worker), round phase, episode reset, reward, then a trainer.

## 7. What reopens this — exactly two things

1. **A policy that cannot decide inside 16.7 ms.** MCTS, or a large net on a contended GPU. Then
   per-frame decisions require *stalling* the game, and that needs the hook. Note this is a
   **compute** argument, not a latency one — and it is the strongest reason the hook could return.
2. **Training evidence.** A run where the agent loses exchanges it should win, and the losses
   correlate with 1-frame timing skew.

Both presuppose that we can train, which is exactly why they cannot justify work now.

If either fires, measure these two before touching the renderer:

```
D   action delay in ticks, and its spread over 30 phase-locked trials
L   shortest decision-relevant window: time-to-hit, and stun duration
```

| result | action |
|---|---|
| `D` constant (spread 0) | never build the hook — act one tick early instead |
| `D` random, mean `D` < 0.25 * `L` | no hook; absorb it with action repeat |
| `D` random, mean `D` >= 0.25 * `L` | 90-minute spike on `D3D11CreateDevice` -> swapchain `Present` vtable, then stop either way |

The `Present` route, if ever taken, is a real frame boundary (once per frame, after the update),
found from the import table with certainty — no RE, and patch a pointer we were handed rather
than game code. Stalling at the renderer seam is safe; stalling **mid-update** is not, because
GameMaker uses delta time and a 200 ms frame can skip physics.

## 8. Dead ends — do not revisit

* Finding GameMaker's update function (§3). No symbols, no PDB, no address table, and no player
  Step event.
* `timeGetTime` / `QueryPerformanceCounter` as a frame anchor: called many times per frame, so it
  is a tick, not a boundary; picking the right call site is itself RE.
* Stalling the game mid-update (§7).
* Hunting a PDB for the shipped binary.

## 9. Operational lessons this cost us (all measured the hard way)

1. **XTEST needs focus.** `spy_key` silently does nothing if the window is not focused — 60 trials
   of a determinism test measured nothing at all before this was noticed.
2. **Pressing `d` repeatedly walks P1 into the goal and ends the round you are measuring.** Any
   automated measurement must alternate `d`/`a`, or work on READY, where the walls stop you.
3. **Identity is a prerequisite, not a parallel chore.** Gate A (measure the delay) was blocked
   5/5 attempts: junk pairs (`type 0xeffffff`, `anim` ~1.1e9), stale pairs frozen at old READY
   coordinates, respawns read as walks, and a valid pair rejected because only the orange fighter
   was in it. You cannot measure latency at a record you cannot trust.
4. **This box is shared.** Another user runs ~20 Nidhogg/steam processes. Broad `pkill` is off the
   table here; cleanup must be farm-scoped (match the farm path in `/proc/<pid>/environ`), which is
   what `clean_farm` now does — it also sweeps leaked `Nidhogg.exe`/`steam.exe`/`explorer.exe`,
   because `stop()` only ever knew the *current* `procs.json` (5 instances leaked in one session).
5. **`wait_state(pid, 0)` means "the next sample"**, not "whatever is on disk" — the old behaviour
   silently returned pre-write state twice during this investigation.

## 10. Artifacts

```
spy/nidspy.zig                 the spy: 2 ms poll, pushed state file, XTEST input (Zig 0.17.1)
spy/selftest.py                protocol + state file + latency self-check, no game needed
scripts/tick_health.py         one sample per tick? (exit 1 if the property regresses)
scripts/state_live.py          live check of the pushed state against direct reads
scripts/action_live.py         in-process input: latency + causality
scripts/frame_data.py          Gate A instrument (D, L) — ready for when identity lands
scripts/ptr_scan.py            who points at a record (how the instance list was found)
briefs/instance-list.md        the identity worker brief
docs/TMP_CURRENT_STATE.md §2.2 the numbers, in the place people read first
```
