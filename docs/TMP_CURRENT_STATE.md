# CURRENT STATE — snapshot after the overnight run (2026-11-09)

Read this first, then `docs/LAYOUT.md` (memory map) and `docs/MEMORY.md` (lab notebook).
This file answers three questions: **what we have, where it lives, what is missing.**

---

## 1. What this project is

Train an RL agent on the **real, installed copy of Nidhogg** (Windows build, YYC, under Proton,
headless, no gameplay code modified). The interface to the ML side is: read state, write state,
drive with keys, in parallel on a server.

**Status: the observation interface is proven; the episode interface is half-proven.**

---

## 2. What we HAVE (proven, with provenance)

### 2.1 Running the game headless

| thing | where | notes |
|---|---|---|
| User-level runtime (no sudo) | `scripts/server-runtime.sh`, env at `~/nidhogg-rl-install/results/env.sh` | Xvfb + xdotool extracted to `~/.local/opt/nidroot`; the X server is binary-patched so it finds `xkbcomp` in `/tmp/xkb` |
| Proton + game launch | `scripts/install-server.sh`, `nidlinux.py` | GE-Proton 11-12; **`proton run`, not `waitforexitrun`** (the latter blocks on `wineserver -w`); **Valve's original `steam_api64.dll`** — the Goldberg/gbe stubs hang `SteamAPI_Init` |
| Human-playable session | `scripts/vnc_play.sh` | Xtigervnc `:50` + noVNC on `:6080`; connect with `ssh -L 6080:localhost:6080` then `http://localhost:6080/vnc.html` |
| N instances in parallel | `scripts/loadtest.py`, `nlinux.start_ids` | measured: **15 instances = 43 cores, 6.3 GB RAM, 33–48 fps each**, no crashes |
| Farm hygiene | `nidlinux.clean_farm` | stale `wineserver`s silently wedge launches; the farm's own prefixes are killed, nobody else's |

### 2.2 Memory access

| thing | where | notes |
|---|---|---|
| In-process reader/writer | `spy/nidspy.so` (source `spy/nidspy.zig`, Zig 0.17.1) | `/proc/<pid>/mem` is refused (ptrace_scope + container + reparenting); the spy reads its own memory. Protocol: `/tmp/nid_cmd_<pid>` lines `dump/poke/hold/add/key/kd/ku/track/ping` |
| Bandwidth / cost | — | 112 MB in ~0.1 s; **round trip 2.4 ms p50 / 2.6 p99 at a 2 ms poll** (was 51 ms at 50 ms); batching is free |
| **Pushed state file (Phase 5, done)** | `/tmp/nid_state_<pid>`, `n.track(pid,p1,p2,score,tick)` + `n.state(pid)` | 128 bytes, tmp+rename, **one sample per game tick**: measured 61.4 samples/s, tick deltas `{1: 59}`, publish interval 16.37 ms p50 / 17.45 max. Reading it costs 13 µs |
| In-process input (XTEST) | `n.spy_key(pid, keysym, ms)` | p50 **0.17 ms** vs 15.8 ms for an `xdotool` fork+exec (93x). Causal proof on a frozen screen: idle 0 px changed, one spy `Down` = 9360 px |
| Fully-region recorder | `scripts/record_all.py`, `docs/workers/overnight.patch` | **117 regions / 1075 MB per dump** — the earlier recorder kept only 15 regions and that is why the score was missed for two sessions |

### 2.3 Object layout (see `docs/LAYOUT.md` for the table)

```
stride 0x200   x@+0xEC   y@+0xF0   facing f32@+0xD8   anim u32@+0xBC   type u32@+0x88
y = 192 on arena ground, 128 on the READY pads
```

### 2.4 Game state now located

| field | address / offset | how proven |
|---|---|---|
| ~~**ORANGE WINS (score)**~~ | ~~`0xd5f57c8`~~ | **REFUTED 2026-11-10** — the write lands, the tally never moves. Stronger than "disputed": writing 0/1/2 to it *and* to the three documented copies leaves the bar count unchanged (12 writes, direct bar count), including `0xf3c63e8`, whose value equalled the display at the time. See §2.4b. |
| score copies (not displayed) | `0xf3c6368`, `0xf3c63e8`, `0xf3c6468` (0x80 stride, region `0xece0000`) | they track 0→1→2 but poking them never changes the HUD |
| tick counter | per-process, find by rate test (~60 Hz, 4 % jitter) | rate measurement |
| fighters P1/P2 x,y,facing,anim,sword | offsets above | input causality (sign+size+stop+reverse), 3/3 fresh instances |

### 2.4c Claims ledger and what it caught (2026-11-11)

`state/claims.jsonl` + `tools/claim.py` (from the collaborator's PR) now hold the score and menu
claims; `verify` re-runs each command and each falsifier. Two protocol rules were learned the
hard way while recording them:

1. **A falsifier must distinguish "refuted" from "could not run".** Two of my claims were first
   marked REFUTED because their falsifier fired on a script that merely failed to reach READY.
   Scripts used as falsifiers exit `2` for "inconclusive" and `1` only for "claim false".
2. **Evidence must be stable, and farms must be isolated.** A recorded `cmd` that prints a pid or
   a bar count drifts on every run; and `start_ids()` calls `clean_farm()`, which stops *every*
   instance in that farm — so two claims sharing a farm destroy each other. One farm per claim.

Also fixed, because three scripts had to work around it: `_game_pid` returned a `KeyError` on a
cold farm (now `None`), and it returned the *first* process matching `DISPLAY=` (now the newest,
preferring one whose spy answers) — a leftover instance on the same display made every read
return `None` while the screen never changed.

### 2.4b The displayed tally is not driven by any known int (2026-11-10)

`scripts/score_state.py` counts the tally bars straight from the frame (one tall bright column
run per win) instead of diffing pixels, so it reads the number the player sees.

* Writing 0/1/2 to `0xd5f57c8` **and** to the three documented copies (`0xf3c6368`,
  `0xf3c63e8`, `0xf3c6468`) leaves the bar count unchanged: 12 writes, readback confirmed each
  landed, zero display changes.
* That includes `0xf3c63e8`, whose value was **exactly the displayed count** (1) at the time —
  so the draw does not read even the field that matches the screen.
* After a forfeit round win the display showed one ORANGE bar while `0xd5f57c8` read **0**
  (provisional: observed once, not yet replayed).

Likely shape: the tally is **not a counter the draw reads every frame**. A non-integer write to
that address kills the process (a glyph/frame index), and the display ignores writes to the
value it matches — consistent with the bars being *instances* (one object per win) or a cached
glyph index, not `repeat(wins)`.

Consequences:
* **Reward must be observed, not written** — read the tally or detect the `winner` screen.
* The field will not fall to poke-and-look. It needs a round-boundary diff (dump, win, dump).
* `state/claims.jsonl` holds the two verification claims; `python3 tools/claim.py verify` → 2/2 OK.

### 2.4d Identity: the engine's instance list (PROVEN 2026-11-11)

Finding out "which record is the player, right now" no longer needs key presses. Every object has
a linked list of live instances; the head is at `object_definition + 0xa0` (see `docs/LAYOUT.md`).
Node = 0x80 bytes, `type@+0x18`, `prev@+0x30`, `next@+0x38`, `id@+0x40`, `record@+0x48`.

`nidstate.type_of_record(pid, rec)` + `nidstate.instances_of_type(pid, type)` + a 1.2 s one-time
scan. Acceptance (`scripts/identity_live.py 0`, live match):

* the walk of the player type held **exactly 2** instances and they were the players;
* pressing `d` moved exactly one of them (the walk is live, not a stale copy);
* after a forfeit and a new round the same lookup returned the new players
  (ids `0x186a7/8` -> `0x18760/61`) with **zero identification presses**.

Caveats: the object-definition pointer changes across a round, so re-resolve per round; bootstrapping
(record -> node) costs one full rw dump (~1.2 s) once per process.

### 2.4e YELLOW score: shortlist of 69, not yet verified (2026-11-11)

A human session (LOCAL 2P, fresh match so WINS reset) produced the first recorded yellow wins.
Ground truth came from `scripts/tally.py`, which reads the two documented digit rectangles with the
documented text colours — it is calibrated (a verified 3–1 frame reads `ready=True 3 1`, a GO frame
reads `ready=False 0 0`).

Session: `~/nidhogg-record/20261111-234917` (then `-235954`).
`t=165.5s 1-0 -> 2-0 YELLOW`, `t=258.4s 2-0 -> 2-1 ORANGE`.

Rule on the full-region dumps (2.44 M slots changed at the boundary):

```
+1 across the YELLOW win  AND  unchanged across the ORANGE win   ->  622
restricted to the tally's own 1 -> 2 delta                        ->   69
```

`results/yellow_score_candidates.json`. **Not verified**: the second session's yellow win happened
in the ~40 s between "turn on the recorder" and the recorder attaching, so the 69 slots were never
observed across a yellow increment. The orange win *was* covered by the live watcher and none of
the 69 moved — consistent with them being yellow-specific, but that is not proof.

Dead end worth recording: `0xf3c65e8` looked attractive because it sits in the `0x80`-stride array
of the documented score copies (`0xf3c6368`), and it did go 1→2 at the yellow win. But with the
tally at 3–2 **no entry of that array reads 3**, so that array is not the score table and the
prior is void.

Instrument lessons (each one cost a session):

* **attach first, prove samples are flowing, then say "go"** — a 40 s setup gap is enough to lose
  the one boundary you needed.
* **dump-diffing across a round boundary is the wrong instrument**: a 12 s window around a round
  end changes 2.9 M slots. Diff for *candidates*, then watch the candidates live
  (`scripts/watch_slots.py`, one batched read at 2 Hz, no screenshots, no key presses).

### 2.4f YELLOW score: three approaches disproven (2026-11-11, later)

The tally reader works (`scripts/tally.py`): with the count at 4–3 it prints `ready=True
YELLOW=4 ORANGE=3`. What does not work is finding the field:

| approach | result |
|---|---|
| **69 candidates** from "delta +1 at a yellow win, 0 at an orange win" (session `-234917`) | **DISPROVEN**: the tally is 4–3 now and **no slot in that set reads 4**. The rule matched the boundary's commonest delta, not the score. |
| the `0x80`-stride array of the "score copies" (`0xf3c6368`…) | **DISPROVEN**: with the tally at 3–2 no entry reads 3. `0xf3c65e8`'s 1→2 was coincidence. |
| dump-diff across a round boundary | **UNUSABLE**: live→READY changed 2.44 M slots; even **READY→READY across one round** changes 7 234 slots by +1 (6 793 of them 0→1). A round transition touches too much state. |
| live watcher, 69 slots, across a yellow win (`scripts/watch_slots.py`) | no candidate moved to the tally's value; two slots did a clean 1→2 (t=45.5, t=101.3) that do not match any count. |

**What is needed next — anchor on the absolute value, not on a delta.** The tally is an integer
the screen shows; require the field to *equal* it at two points:

1. dump at READY with the tally at N,
2. one round won as yellow (tally N+1),
3. dump again at READY,
4. keep slots with `v1 == N` **and** `v2 == N+1`.

That constrains both ends, which is what every previous attempt lacked. The watcher (`watch_slots.py`)
can then hold the survivors at 2 Hz for a third confirmation without another dump.

### 2.4g YELLOW score: the absolute-value rule works, the field is per-room (2026-11-12)

Session `~/nidhogg-record/20261112-002609` (81 dumps, 162 GB), ground truth from the shots:

```
t=  0.0.. 41.9s   4-3
t= 97.5..104.9s   5-3   YELLOW won
t=171.4..181.2s   5-4   ORANGE won
```

Anchoring on the **absolute value** at three dumps (t=40, 105, 193) instead of on a delta:

| rule | candidates |
|---|---|
| `4 -> 5 -> 5` (yellow) | **31** |
| `3 -> 3 -> 4` (orange) | **23** |

from 622 delta-+1 candidates and 2.4 M slots that changed at all. Two structural hints fell out:
yellow candidates come in **pairs 0x84 apart**, orange ones at **0x200 stride** (the fighter-record
stride).

**Then the decisive check failed in an informative way:** walking yellow into a goal and reading
those 54 addresses *inside the match room* gave different values (5→4, 5→2, 4→0 …). So they are
**per-room instance copies, not a persistent counter** — which fits the observation that the tally
is only painted on READY. A `tally` field inside the current fighter records does not exist either
(0 offsets where yellow==5 and orange==4).

**Conclusion — stop hunting the field.** For training, reward needs the *displayed* tally, and
`scripts/tally.py` reads it in ~15 ms with the documented colours (`ready=True YELLOW=5 ORANGE=4`
verified repeatedly). The memory field would be a micro-optimisation with no effect on what the
agent can learn, and it has now cost four sessions and ~500 GB of dumps.

### 2.4h Round phase: still no field, and my two candidates were an artifact (2026-11-12)

Worker B3/B4 (own farm, `~/nidhogg-rl-b3/results/b4.json`) tested the two slots that
`scripts/phase_filter.py` had produced (`node+0x08` on a "singleton controller": 0x1 live ↔ 0x101
over; `rec+0xfc`: 0 ↔ 117). Every claim failed to reproduce:

* re-running `phase_filter.py` on a fresh instance gives **0 candidates** (6 496 instances);
* **0 of 2 952** live instances read 117 at `rec+0xfc` on a real winner screen;
* the one `0x1` singleton's `node+0x08` reads **0x1 on a real winner screen too** — it does not flip;
* writing `0x101` there changes **1 428 px vs 1 489 px for a no-op control** (a winner screen is
  52 986–115 093 px): the round does not end.

**Why my result looked good:** `phase_filter.py` accepts `changed > 2000` as "the winner screen",
so it accepted a 6 387 px repaint; and `find_players_by_input` is truthy on the attract demo and on
the winner screen, so "a live drivable match" was not checked properly. Both are threshold bugs in
my harness, not properties of the game.

**What *is* validated for round end (worker, 8/8):** the exact forfeit recipe plus a window frame
diff **≥ 12 000 px** (failed forfeits: 1 670–6 387 px). Together with the tally transition
(`scripts/tally.py`, exact counts at READY) that is the round-end oracle we actually have.

**Status: no round-phase field is proven, and the only candidate set produced so far is disproven.**

### 2.4i Room / substage id: monotone-step hunt is negative (2026-11-12)

Human session `~/nidhogg-record/20261112-004654`: three loops of
*yellow crosses → orange kills yellow → orange crosses → yellow kills orange*, 62 full dumps
(2.08 GB each, every 8 s) + 165 screenshots.

Rule used: a room id must be a **clean monotone step function** across the dumps — constant inside
a room, +1..+4 at an advance, never decreasing, small values. Applied to 557 M slots over 31 dumps:

| rule | survivors |
|---|---|
| only +1 steps, 3..12 changes, final < 16 | **0** |
| +1..+4 steps, 3..12 changes, 0 ≤ first < 8, final < 16 | **5** |

The 5 are noise: `0x6edf0d0/250/280` sit inside an **audio waveform buffer** (neighbouring dwords
are float bit patterns that sweep), and `0xa96e7d0/800` read 0 on inspection.

**Why this instrument cannot settle it:**

* dumps 8 s apart: a room can advance twice in between, so the step size is unknown a priori;
* **no room-boundary ground truth** — a frame diff cannot separate a room change from camera
  panning (median 112 px, p90 11 323 px, and room changes land in the same 25–32 k range);
* the room id may be per-room state (recreated on entry), in which case no slot survives to
  compare — the same shape as the score (`§2.4g`) and the phase (`§2.4h`).

**Verdict: three independent memory approaches to "which room / is the round over" are now
negative** (phase field, global boundary diff, monotone room-id step). The validated oracle for
round end remains **visual**: winner-screen frame diff ≥ 12 000 px (8/8, failed forfeits
1 670–6 387 px) or the tally transition at READY (`scripts/tally.py`).

The recording is still useful: 62 dumps covering repeated crossings *and kills* in one match, which
is the data a kill/death or camera-field hunt would need.

### 2.4j Reset: a single write does NOT survive — physics rewrites it every tick (2026-11-12)

`scripts/reset_test.py` on a live, causality-verified match (P1 `0x1906c00`, P2 `0x1906000`,
both `y=192`, `anim 465`): six trials of read → walk → write `x`/`y` back to spawn → read back.

```
trial 0: moved by +8px,  after write Δ=8.0px,  0.35s later Δ=8.0px
trial 1: moved by +16px, after write Δ=17.0px, 0.35s later Δ=17.0px
trial 2: moved by +24px, after write Δ=25.0px, 0.35s later Δ=25.0px   ... (Δ keeps growing)
```

**The write is overwritten within one tick.** The value never came back — Δ is exactly where
walking left it, and grows each trial because each trial walks further.

**This corrects a long-standing entry**: `INTERFACE.md` / `MEMORY.md` record "writes are kept
(`x += 300` does not snap back)" — but that measurement used `add`, which re-writes at ~2 kHz for
`ms`, i.e. it wins *because it accumulates*, not because a write survives. A single `poke` loses
to the 60 Hz physics write immediately.

Consequence for episode reset: **`poke` is the wrong primitive.** The candidates are

* `hold <addr> <bytes> <ms>` — pin at 2 kHz for N ms (the spy already implements it), then release
  and check whether physics continues *from the pinned value* (it should: it integrates from the
  current x, so a 250 ms pin at the target should leave the fighter there);
* or find the game's own respawn/spawn trigger instead of writing position.

The one-line test for tomorrow: `n.hold(pid, p1+0xEC, pack("<f", 280.0), 250)` then read after
0.4 s — keep the result if x is still ~280.

### 2.5 Game behaviour measured (matters for the RL loop)

* **Entry**: menu → `Enter×3` → READY → walk both onto pads (wall ± 0.333·W) → stage select → `Enter`.
  Full automated path in `nidstate.enter_match_v2()` (~58 s).
* **Round win without fighting**: pause (`Escape`) → `Down, Down` → `Enter` → **FORFEIT → YES**. The
  round ends with a real *Winner* screen and the wins tally increments. **This is how we generate
  boundaries on demand now** — no fencing required.
* **Death** = the body record stops updating (no flag byte). Record keeps its address and type.
* **Writes are kept**: `x += 300` does not snap back and does not crash → **episode resets are viable**.
* **Latency** ≈ 30 ms median ≈ 1.8 ticks. **Determinism**: effectively yes (3 px carried-in offset).
* **Roles (P1/P2) SWAP** — never infer role from an address; re-prove by input after every transition.
* **`+0x200`/`+0x400` (arm/sword) reallocate** — identify them by type + behaviour, not offset.
* **Swords are a set**: held / flying / stuck / on the ground, and a dead player's sword persists.

### 2.6 HUD oracle (cheap, vision-only for score ground truth)

```
drawn ONLY on the READY screen; score 0 draws NOTHING, each win is one bar
P1 digit rect [56,14,80,30]     P2 digit rect [214,14,238,30]
```
Writing a non-integer (float) into the score field **kills the process**; integers are safe.
Writing a score before the wins cell is allocated (brand-new READY) also crashes.

---

## 3. What we HAVE (inferred, not proven)

* **Round phase**: 2283 slots flip `0` (READY) → `1` (live) → `0` (READY), but poking them (8 at
  READY, 15 mid-round) produced no behavioural change. Unproven.
* **YELLOW WINS counter**: `+4`/`+8` from the orange one were ruled out by poking; its address is
  still unknown, so the two scores are *separate* fields, not an adjacent pair.
* **Room / substage id**: the human advanced two substages without ending the round (marked in
  session 2) — no field located.
* **Score cap rule**: writing 7 or 100 draws the same bars as 2 — the tally is "one bar per win,
  capped by rounds played", but whether the cap is a frame index or a separate field is unknown.

---

## 4. What is MISSING before training

1. **Round phase in memory** — needed to know *when* a round is live/over without screenshots.
2. **YELLOW score** — needed for a symmetric reward/observation.
3. **Room/substage id** — needed to know when cached addresses are invalid.
4. **Per-tick state file** (Phase 5): the spy should push `x, y, facing, anim, sword, score, phase`
   at 60 Hz into `/tmp/nid_state_<i>.txt`. Everything on that list except score/phase is proven.
5. **Reset semantics in practice**: writes are kept; nobody has yet built "reset an episode by
   writing x/y" and verified the game continues sanely (needed to drop the 58 s menu entry per
   episode).

---

## 5. Where everything lives

```
repo (this one)                 code, docs, worker briefs
scripts/                        runtime, entry, identification, recording, mining
  server-runtime.sh             user-level Xvfb + xdotool (patched xkbcomp path)
  install-server.sh             Proton-GE + game + prefix template
  vnc_play.sh                   human-playable VNC session
  qprobe.py                     identify P1/P2 by input causality; synthetic self-check
  identify.py, wall_walk.py     entry helpers (pads at wall ∓ 0.333 W)
  record.py, record_all.py      session recorders (state 20 Hz, shots 2 Hz, heap dumps)
  mine_session.py               structural events from screenshots (fighter presence)
  hunt_field.py                 interval-delta field hunter (u32 and --float)
  loadtest.py                   how many instances the box carries
spy/nidspy.zig                  the in-process reader/writer (C original: nidspy.c)
spy/selftest.py, scripts/tick_health.py   protocol + per-tick regression checks
docs/LAYOUT.md                  memory map (this file's technical companion)
docs/MEMORY.md                  chronological lab notebook, incl. every trap
docs/OVERVIEW.md                the structured "why" document
docs/INTERFACE.md               the 15-row contract with provenance
docs/workers/*.json             raw reports from 9 workers (m, p, q, r, s, t, u, w, z, overnight)
~/nidhogg-record/<stamp>/       recordings: states.csv, shots/, heaps/, markers.txt, regions.json
  (three sessions kept; the 2026-11-08-195634 one has human markers, 76 GB)
~/.nidfarm*/                    one farm per worker: game copy, prefix template, logs, procs.json
~/nidhogg-rl-<tag>/             worker worktrees (results/, out/, scripts/)
```

---

## 6. Operating rules (each one cost a session)

1. **Never `pkill -f`** — it matches your own command line and has killed a worker *and* the
   supervisor shell. Use `pkill -x`, or match via `/proc/<pid>/environ`.
2. **Never probe (press keys) while a human plays** — identification presses `d/a/arrows`; the
   player feels it and their input breaks the "stops when released" test. Identify once, in a
   controlled pause, then pass `--p1/--p2`.
3. **Identify early in a match**: identification works on a fresh match and decays as the session
   runs (the 0x200 chain reallocates).
4. **A dump offset is meaningless without `regions.json`**; low regions keep their bases across
   processes, high ones are ASLR'd.
5. **A flipping bit passes any single ±1 test** — every hunt needs several intervals, in both
   directions (+1 at events, 0 between them).
6. **Measure the measurement**: a per-screenshot fps loop reports 1 fps on a 60 fps game; a capture
   that costs 0.9 s makes everything look slow. Verify an oracle with a *known* case before
   believing a negative.
7. **`biggest_heap()` may be a zero-filled reservation** — that produced 42 dumps of zeros.
8. **Roles swap; offsets reallocate.** Re-prove rather than cache.

---

## 7. Immediate next steps, in order

1. **Round phase** — use the forfeit trick to generate boundaries at will, then poke the 2283
   candidates *while watching for a behavioural change* (the round ending, the GO screen, the HUD)
   rather than a value change.
2. **YELLOW score** — same mining as the orange one, restricted to `0xd412000`/`0xece0000`, with the
   HUD's P1 rect `[56,14,80,30]` as oracle.
3. ~~Per-tick state file~~ — **done**, see §2.2. Remaining work here: add sword position once the
   sword set is mapped, and round phase once it is found.
4. **Episode reset** — write both fighters' x/y, verify the game continues sanely, and drop the 58 s
   menu entry from the loop.
5. Only then: pick the trainer (the old GA or PPO) and start measuring rounds won per hour.
