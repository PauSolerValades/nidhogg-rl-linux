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
| In-process reader/writer | `spy/nidspy.so` (source `spy/nidspy.c`) | `/proc/<pid>/mem` is refused (ptrace_scope + container + reparenting); the spy reads its own memory. Protocol: `/tmp/nid_cmd_<pid>` lines `dump/poke/hold/add` |
| Bandwidth / cost | — | 112 MB in ~0.1 s; a state read is ~10 ms; **one spy round trip costs ~50 ms of poll** (batch everything) |
| Fully-region recorder | `scripts/record_all.py`, `docs/workers/overnight.patch` | **117 regions / 1075 MB per dump** — the earlier recorder kept only 15 regions and that is why the score was missed for two sessions |

### 2.3 Object layout (see `docs/LAYOUT.md` for the table)

```
stride 0x200   x@+0xEC   y@+0xF0   facing f32@+0xD8   anim u32@+0xBC   type u32@+0x88
y = 192 on arena ground, 128 on the READY pads
```

### 2.4 Game state now located

| field | address / offset | how proven |
|---|---|---|
| **ORANGE WINS (score)** | **`0xd5f57c8`**, region `0xd412000–0xdd10000`, u32 | write 0 → tally blank, 1 → one bar, 2 → two bars; reproduced in two processes; same absolute address across processes (region base is not ASLR'd) |
| score copies (not displayed) | `0xf3c6368`, `0xf3c63e8`, `0xf3c6468` (0x80 stride, region `0xece0000`) | they track 0→1→2 but poking them never changes the HUD |
| tick counter | per-process, find by rate test (~60 Hz, 4 % jitter) | rate measurement |
| fighters P1/P2 x,y,facing,anim,sword | offsets above | input causality (sign+size+stop+reverse), 3/3 fresh instances |

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
spy/nidspy.c                    the in-process reader/writer (~90 lines)
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
3. **Per-tick state file** — pin the proven offsets in the spy and write the state file at 60 Hz;
   this is the actual RL interface and everything it needs is known.
4. **Episode reset** — write both fighters' x/y, verify the game continues sanely, and drop the 58 s
   menu entry from the loop.
5. Only then: pick the trainer (the old GA or PPO) and start measuring rounds won per hour.
