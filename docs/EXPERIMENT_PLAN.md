# Experiment plan — mapping the rest of the memory, in parallel

The game now runs headless on artemis. Compute is no longer the constraint; **entry is**. Every
worker needs a *verified controllable* screen, and getting there costs ~3 minutes of loading plus
an unreliable menu path. So the plan separates **getting instances into a known state** (done
once, centrally) from **measuring one field each** (done by workers, in parallel).

## 0. Foundation first (blocks everything): `nidboot.py`

Boots N instances on N displays, walks each to the LOCAL READY screen, runs the control gate,
and writes a **session map** per surviving instance:

```json
{"tag": "b", "display": ":20", "pid": 12345, "game_dir": "...",
 "state": "ready", "gate": {"G1": true, "G3": true},
 "P1": {"addr": "0x191c400", "x_off": "0xEC", "y_off": "0xF0"},
 "P2": {"addr": "0x191bc00"},
 "type_value": "0x174f900",
 "siblings": {"sword": "0x191c800", "arm": "0x191c600"}}
```

Why this matters: **the type pointer changes per run**, and P1 identification needs eight `d`/`a`
transitions. Without a session map, six workers each spend their budget rediscovering the same
three facts — which is exactly what the last five rounds looked like.

Boot cost: ~25 s warm (measured) to ~3 min cold per instance, in parallel across instances.

## 1. How many workers

| resource | per worker | budget |
|---|---|---|
| game instance | 0.4–1.0 core, ~455 MB (software rendering on a GPU-less box) | — |
| pi agent (deepseek-flash) | ~0.3 core | — |
| **total** | **~1.5 core** | 384 cores, 1.1 TB |

The machine is not the limit — **merging is**. Each worker produces a JSON verdict plus notes I
have to reconcile into `docs/INTERFACE.md`, and past ~6 concurrent reports the merge stops being
careful. So: **wave 1 = 6 workers**, wave 2 as needed. Going to 20 would multiply noise, not
knowledge.

## 2. Wave 1 — six falsifiable targets, one per worker

Each brief states: the *stimulus*, the *oracle*, the *acceptance*, and what artifact to write.
No worker touches the menu, the shared docs, or `pkill -f`.

| # | target (contract rows) | stimulus | oracle |
|---|---|---|---|
| **W1** | animation/state field → keymap (rows 4,5,7,9: attack, crouch, roll, dive, facing, stun) | press each key in a fixed order from READY, one at a time | the candidate field `+0x58`/`+0x64` takes a **distinct value per key** and returns to idle; two passes must agree |
| **W2** | sword lifecycle (rows 1,2,6) | hold → attack → throw → stuck in wall → walk over it | sibling record (`body+0x400`): presence, `x/y`, and any state int; a thrown sword must appear as a **moving record**, and a stuck one must stop |
| **W3** | death & round (rows 3,10,11,12) | let the CPU win a round; then win one | type group drops below 2 on death; find a small int that **increments on round end** (score) and a counter that **decrements** (timer) |
| **W4** | room/stage id + address stability (rows 14,15) | play until the room changes (round end does it) | a field that changes **exactly when positions do**, and a table of which offsets survive the change |
| **W5** | action→observation latency + determinism (control contract) | hold `d` for N frames, sample `x` every tick | latency in ticks (first tick where `x` changes) **and** same-input reproducibility over 3 trials |
| **W6** | per-tick state file prototype (Phase 5) | none — engineering | extend `spy/nidspy.so` with `watch <addr>,<addr>,…` that appends `tick,x1,y1,x2,y2` to a file at frame rate; measure jitter over 10 s |

W1, W2 and W3 are independent. W4 depends on W3 happening (room changes at round end) but can
use any room change. W5 and W6 need only the session map.

Wave 2 (after merge, only if needed): resets (`write x/y` semantics), thrown-sword projectile
type enumeration, camera/view fields for observation-normalisation, and the HUD cross-check
(pixels vs memory for score).

## 3. Protocol (this is what keeps 6 workers from ruining each other)

1. **One instance each**, from the session map: `NIDFARM=~/.nidfarm-<tag>`, display band `:10·k`,
   `NID_GAME_DIR` = its own reflink copy. Never a second instance on the same display.
2. **Never kill by pattern.** `pkill -f` matches your own command line and has already killed one
   worker. Use `pkill -x <exact name>`, and never kill `wineserver` — other workers share the box.
3. **Only the worker's own farm/game copy is writable.** `game/` in the repo is read-only input;
   a worker that needs a different `data.win` or DLL makes its own copy.
4. **Artifacts**: `results/<tag>.json` (machine-readable verdict) + `results/<tag>.md` (3–10 lines
   of evidence: stimulus, oracle, numbers, what failed). Written **even on failure**.
5. **Provenance discipline**: a field is `proven` only with *two independent confirmations*
   (e.g. two stimuli, or two passes) and the numbers to show it. Otherwise `inferred`.
6. **Budget** 40 minutes; a negative with numbers is a full result.

## 4. Merge (me, after the wave)

For each report: move rows in `docs/INTERFACE.md` from `unknown` → `proven`/`inferred`, append the
evidence to `docs/MEMORY.md` under a dated section, and record any new trap in the "mistakes"
list. Then decide wave 2 from what is still `unknown`.

## 5. Sequencing

```
 nidboot.py (foundation, tested once)  ──►  wave 1: W1..W6  ──►  merge  ──►  wave 2 / Phase 5
                                              (6 workers, ~40 min)
```

Nothing in wave 1 needs the Docker container; that stays a Monday task for *scaling* instances,
not for discovery.
