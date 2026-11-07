# Next steps — from proof of concept to a training interface

Read `docs/OVERVIEW.md` first (what exists and why), then this.

## 0. Is moving to the server the right call?

**Yes — with one correction of expectation.** Compute is not what is blocking us. We have a
proven state reader, a proven writer, and a reliable input path; what we do *not* have is a
**falsifiable definition of "the match is under our control"**. More machines do not fix that;
they multiply whatever the workers conclude.

What the server *does* buy is exactly what got us this far: **cheap parallel hypotheses**. Six
25-minute workers produced the layout, the P1 identification and the type field — most of the
project's progress — and they cost nothing but wall clock. On a server we can run ten at once
and iterate on the contract in a day instead of a week.

So: move, but move with **Phase 1 (the gate) as a written, falsifiable test**, and with
`docs/INTERFACE.md` as the artifact every worker edits. Otherwise ten workers will produce ten
mutually inconsistent "discoveries", which is a slower version of what we just did.

## 1. The one blocker: a control gate that survives scrutiny

Every oracle we built for "we are in a real match" was wrong at least once:

| attempted gate | why it fails |
|---|---|
| `sprite_present && cpu_motion > 15` | the attract demo passes both |
| world shift while holding a direction | ±4 px — the camera absorbs it |
| yellow centroid moves | confounded by camera follow, goal flag, floor strip |
| paused write changes pixels | pause appears to be a frozen snapshot |

**Required gate (falsifiable):** a write must *survive into the simulation*. Concretely:

1. read `x` of P1 (proven offset `+0xEC`) and the sprite's screen x;
2. `add(x, +200)` for ~300 ms — an accumulating write, which physics cannot silently undo;
3. **pass** only if the read-back value moved by ≈200 *and* the sprite moved accordingly on
   the next frames; **fail** otherwise.

An attract demo cannot pass this, because we are not controlling anything there. This gate is
the definition of "drivable" for the whole contract, and it must be written down before any
worker uses it.

## 2. The contract to fill: `docs/INTERFACE.md`

One row per field. **Provenance admits only `proven` / `inferred` / `unknown`**, and `proven`
requires both a *stimulus* and an *oracle*. A field without a stimulus stays `unknown` — that
rule cost us five dead ends to learn.

Player fields (from the user's list, plus what RL actually needs):

| # | field | likely source | needs |
|---|---|---|---|
| 1 | sword held / not held | sword record = `body+0x400`; presence + own state | throw & pick-up stimulus |
| 2 | sword position (both) | `x@+0xEC`, `y@+0xF0` of the sibling record | proven layout, unverified link |
| 3 | alive / dead | GM destroys the instance → type group drops below 2 members | a kill in both directions |
| 4 | attack / throw / dive keys | animation index changes per key (`+0x58`, `+0x64` candidates) | full key sweep |
| 5 | crouch / roll | same animation field | same sweep |
| 6 | thrown sword = projectile | its own object type; enumerate like fighters | throw, then find the new type |
| 7 | **facing** direction | ±1 float or sprite flip; derivable from sprite/side | turn stimulus |
| 8 | **velocity** | derive by differencing `x` across two ticks (cheap) | none — computed |
| 9 | **stun / hit state** | animation field | get hit |
| 10 | **round score** | HUD pips; small int that increments | win and lose a round |
| 11 | **round phase** | READY / live / ended | observe transitions |
| 12 | **round timer** | HUD `00:00`; an int counting | watch it tick |
| 13 | **which instance is us** | P1 vs P2 by type group + start position | none — structural |
| 14 | **tick/frame counter** | for timestamped observations | find any monotone int |
| 15 | **room/stage id** | to invalidate cached addresses on room change | room change while watching |

Control-side contract (equally binding):

| item | requirement |
|---|---|
| action timing | how many ticks after a held key until the state reflects it |
| reset semantics | writing `x`/`y` → what the next frame does (does physics snap back?) |
| address stability | within a room: stable; on room change: re-bind by type |
| death | do instance records reallocate? cached addresses must be re-validated |
| determinism | same inputs from the same reset state → same trajectory? (needed for eval) |

## 3. Server setup checklist

Packages: `xvfb`, `xdotool`, `imagemagick`, `ffmpeg`, `gcc`, `python3-numpy`, a **Vulkan ICD**
(`mesa-vulkan-drivers` / lavapipe for GPU-less boxes — DXVK needs *a* Vulkan device even at
320×200).

Good news: **no ptrace, no root, no CAP_SYS_PTRACE required.** The reader lives inside the
process (`LD_PRELOAD`), which is precisely why this design ports cleanly to a server. Do *not*
plan on `ptrace_scope=0`.

Steam: the build needs `steam_api64.dll` satisfied. Either Steam running in offline mode, or a
Goldberg-style stub — the latter removes Steam from the equation entirely and is the sane choice
for 10+ instances.

Per-worker isolation (already implemented, just set the env):

```bash
NIDFARM=~/.nidfarm-$TAG          # own wine prefixes, procs.json, logs
NID_DISPLAY_BASE=<10*tag>        # own Xvfb display
NIDTAG=$TAG  NIDART=/tmp/nidart-$TAG
```

Disk: each farm needs the game copy (reflink ≈ 0 on btrfs, else ~180 MB) + one wine prefix per
instance (~377 MB, reflink if the FS allows).

Budget per instance at 320×200: **0.4–0.6 core, ~455 MB, 60 steps/s**. A 16-core/32 GB box
runs ~28 instances (~1700 steps/s) comfortably; 8 cores ≈ 14. Start at **cores/2** instances
and leave headroom — every worker also runs a game plus an agent.

## 4. Worker protocol

`./spawn_workers.sh a b c` runs one headless pi per tag in its own worktree + farm + display.

Rules that made the last rounds productive:

1. **One falsifiable target per worker**, with the stimulus and oracle named in the brief.
2. **Workers never touch the menu unless the brief is about the menu.** Four rounds died there.
3. **No writes unless the task requires them.**
4. Results go to `results/<tag>.json` **even on failure**, plus a 5-line final message.
5. 25-minute budget; a negative with numbers is a valid answer.
6. The supervisor (me/human) merges into `docs/INTERFACE.md` and `docs/MEMORY.md` — workers do
   not edit the shared docs, so they cannot collide.

## 5. Phase plan

**Phase 0 — port and verify (½ day).** Farm up on the server; `find_fighters()` returns P1/P2
whose `x` matches the sprites on READY; `dump` bandwidth sanity-checked. No new science.

**Phase 1 — the gate (§1). DONE.** `nidstate.control_gate(i)` is read-only and has been run in
both directions: attract fails (0.0 px of direction control), READY passes (12/12 transitions,
median 0.87 px, next-best record 51 px). Evidence in `docs/gate/`. Note: a write-based gate was
abandoned after it killed the game twice.

**Phase 2 — player state machine.** Full key sweep against the animation field. *Acceptance:*
a table `key → animation values` that names attack, crouch, roll, throw, jump, dive; rows 4/5/7/9
of the contract move to `proven`.

**Phase 3 — sword lifecycle.** Hold → throw → wall → pick up. *Acceptance:* rows 1/2/6 proven,
including how to distinguish "held" from "on the ground" from "in flight".

**Phase 4 — death and round.** Kill and be killed. *Acceptance:* rows 3/10/11/12 proven; the
death→record-disappearance inference tested at least once.

**Phase 5 — per-tick state file.** Extend the spy to sample the proven offsets at 60 Hz into
`/tmp/nid_state_<i>.txt` (the format `train_state.py` already consumes) and add the tick counter
(row 14). *Acceptance:* 60 samples/s with <1 tick of jitter, and a documented action→observation
latency.

**Phase 6 — resets and determinism.** Write `x`/`y` for both fighters; verify the game continues
sanely; measure same-input reproducibility. *Acceptance:* an episode can be reset without the
menu, and two identical runs from one reset are compared.

**Phase 7 — freeze the interface.** `docs/INTERFACE.md` becomes the spec with guarantees,
invariants, failure modes and an example env wrapper; then the ML side writes against it.

## 6. Mistakes not to repeat (each cost a round)

* **Never reuse an oracle across game states.** Attract / READY / match have different cameras
  and different coordinate spaces (see the table in `docs/OVERVIEW.md` §4e).
* **Never trust a single sample.** Two independent confirmations, or it is not proven.
* **Never trust "the sprite moved".** The camera follows P1; measure the world or the value.
* **Check the wire format.** Two rounds were lost to `add`/`hold` parsing `addr ms hex` while
  Python sent `addr hex ms`; `hold` then blocked the spy thread for ~12 days per call.
* **A "negative" result is a deliverable** — every worker that reported one moved the project
  forward.

## 7. Already cheap (measured, for the ML side)

| channel | cost |
|---|---|
| memory sample (once the spy pushes) | ~20 µs |
| memory dump bandwidth | 112 MB / 100 ms |
| screenshot + decode | 56 ms |
| instance cost | 0.4–0.6 core, 455 MB, 60 steps/s |
| farm throughput | 8 cores ≈ 840 steps/s; 16 cores ≈ 1700 steps/s |

## 8. Files to carry to the server

```
farm.sh  nidlinux.py  nidstate.py  spy/  spawn_workers.sh  briefs/  tools/
docs/OVERVIEW.md  docs/NEXT_STEPS.md  docs/MEMORY.md  docs/INTERFACE.md (to be written)
docs/SESSION_LOG.md  docs/SESSION_LOG.jsonl.gz   (this conversation, for context)
```

`docs/SESSION_LOG.jsonl.gz` is the full transcript; `docs/SESSION_LOG.md` is the readable,
tool-output-truncated version. Drop the `.gz` from the repo if size matters — it is context,
not code.
