> Structured view (objective, method, capabilities, limits): **docs/OVERVIEW.md**
> This file is the chronological lab notebook.

# Process memory: what is proven, what is not

## Proven

| fact | evidence |
|---|---|
| Memory can be read and written in-process, no root, no ptrace | `spy/nidspy.so` via `LD_PRELOAD`; `/proc/<pid>/mem` is refused (EACCES: `ptrace_scope=1` + Proton container + reparent to systemd) |
| Read bandwidth | 112 MB in 100 ms (~1.1 GB/s); per-tick reads would be ~20 µs |
| Arbitrary writes land | `poke` / `hold` commands; a view-variable write scrolls the world |
| Positions are **float32**, not float64 | two independent whole-heap float64 sweeps returned 0 moving slots |
| The LOCAL 2-player match is **not controllable** | holding `d` scrolls the *view*; the fighters' instance x does not move; a 112 MB heap diff during a `d` hold returned only draw quads (0x200 stride), dirty rects and counters |
| Pause looks like a frozen snapshot | writes to a known view variable while paused changed ~59 px (menu chrome only), never the scene |

## Not proven

* P1's `x`, `y`, facing, health, round state. **No offset in this repo is confirmed.**
* Whether a paused write can ever be observed — the pause screen may be a captured frame,
  which would make the paused oracle structurally invalid rather than merely noisy.

## Two workers, two negatives, one shared wall

Worker A (`docs/workers/a.json`, x via structural sweep) and worker B
(`docs/workers/b.json`, y via the vertical axis) each ran 25 minutes and both returned
`found: false`. They independently hit the same wall: **the state they measured was not a
live fight.**

* A: motion-based candidate generation returns camera / draw / dirty-rect state, never the
  instance. Pinning every candidate left the sprite exactly where it was.
* B: found `0x8188614` rewritten by physics every frame (`127.0`) and `0x8188610` (`313.0`)
  moving with P1 — but both read `0.0` once the game moved to another room, so they are
  draw/rect bookkeeping in screen space, not instance state.
* B also showed constant pins lose to physics: at 60 Hz the game rewrites the value; the
  2 kHz hold only wins for bytes the renderer reads immediately.

## Consequences for the next attempt

1. **Reach a real fight first.** The macOS notes measured one: holding `A`/`D` moved `me_x`
   142 -> 8 and 8 -> 245. The READY screen never does that. Entry must be verified by
   *world-space motion*, not by "a sprite is on screen".
2. **Verify unpaused with accumulating writes.** Add `add <addr> <delta> <ms>` to the spy
   (read, add, write at ~2 kHz). A constant pin is overwritten each tick; an accumulating
   delta forces the position to run away and stays visible.
3. **Or hook the renderer.** `LD_PRELOAD` is already inside the process; hooking
   `DrawIndexed` / `Present` yields exact drawn positions *and* the instance pointer held by
   the draw record — turning "find x by poking" into "read the pointer, then scan the
   struct".

## Round 2 workers (live matches) — still no proven offset, but the noise is mapped

Both ran 25 min against a *live* match and returned `found: false`. What they eliminated
is now specific:

* **The `+130 rising` pair from the previous run is a timer**, not camera or position: it
  rises monotonically under `a` as well as `d` (worker A).
* **Every motion candidate repaints a wide or full frame** under `accumulate +300`
  (bbox 8..319 × 4..177): they are view/surface/draw state, and none isolates the sprite.
* **World shift is tiny**: holding `d` for 1.25 s shifts the background strip by only
  −4 px (`a`: +4 px). The camera absorbs nearly all of the fighter's motion, so
  "world shifted a lot" is not a usable oracle either.
* **The pure-yellow centroid is unreliable**: in dark arenas the goal flag is a huge
  yellow blob and the fighter is small — a blob-size filter is required (worker A).
* **Screen-space draw records live at `0x818xxxx`** — round integers in 0..200 that change
  with the room. Not instance state (worker B).

### The one live lead

Worker B found fractional, V-shaped jump arcs in a *live* attract demo:

```
0x19004f0 (f32)  y: 191.8 -> 52.4 -> 172.5      (a full jump, room space 0..~200)
0x19004ec (f32)  x: 939.3 -> 936.6              (x sits 4 bytes BEFORE y)
```

Room widths are 320 and 960, so those are plausible room-space coordinates of a fighter.
Unproven: verification needs a *controllable* fighter (attract-mode AI moves by itself and
changes rooms mid-trial, which swamps any write).

### Menu: the workers contradict each other, and that is the real blocker

A's `enter_live_match` worked for me (CPU motion 52.8) but for B it landed in
MULTIPLAYER → LOCAL → READY (CPU motion 0). B reports the main-menu rows are **inverted**
(`Up` moves the selection down) and that the default row is SINGLE PLAYER (dot y=124)
whose submenu defaults to TRAINING (dot y=139). The scrolling menu box means the dot's
y-position tracks scroll, not item index — so neither of us can name the selected row from
`dot_y` alone.

Fix for next round: stop deriving the entry from timings/positions. Try the two plausible
variants (with and without a leading `Up`), and accept the one where **`cpu_motion > 15`
and a held direction produces a measurable sprite displacement** — a positive gate, not a
screen guess.

## Round 3 — the layout is proven; every oracle is now in doubt

### Proven (worker C, no menu, no input — attract demo only)

```
record stride 0x200   x @ +0xEC   y @ +0xF0        (float32, fractional, room space)
duplicates           x @ +0xFC   y @ +0x100
```

Evidence: a full jump arc `y 111.4 -> 12.1 -> 143.8` and a walk `x 787.4 -> 758.3`,
captured with no writes at all, by motion profile alone. Re-find recipe: dump the ~109 MB
anonymous rw region as f32, step 0x200, keep records with `x@+0xEC` in (0,960) and
`y@+0xF0` in (15,260), both fractional; the fighters are the ones that move. Addresses
move per room, offsets do not.

### Not proven: which of the ~300 records are the two fighters

The layout is shared by **particles and decoration** (a trail of records stepping x
106→113 at y≈16, chandeliers with a 21×42 box at x=904 but bbox at x=613). The bbox filter
(`+0x120..+0x12C`) leaves 15 records, all integer-valued — static decoration, not fighters.

### The spy was silently broken until worker B fixed it

`add`/`hold` parsed `addr ms hex` while the Python side sends `addr hex ms`. So:
`add` wrote nothing (a no-op), and `hold` blocked the spy thread for ~0x3f800000 ms
(≈12 days) per call, which is what made later memory reads time out. Fixed in `spy/nidspy.c`
and committed. **Consequence: worker A's round-3 poke conclusions are void** — it was
testing with a no-op accumulate.

### Both of my entry gates were wrong (worker A)

> `cpu_motion + sprite_present` pass in the attract demo too.

So "CPU moved 52 px" never proved we were in a match. And A measured `world_shift = 0` on
every screen it reached: we have **never** had a verified controllable fighter. Worker B's
`space`-jump result (`sprite_y 113 -> 52`) is therefore suspect too — either it was a
genuine controllable state or the demo jumping on its own.

### Next discriminator (cheap, input-free, camera-invariant)

Subtract, don't compare. The two fighters' room-space `x` difference must equal the
**screen-space** `x` difference between the yellow and orange sprites (a pure camera
translate cancels out). So: for every pair of records, check
`|(x_i - x_j) - (sprite_x_yellow - sprite_x_orange)| < few px`, and require the pair to
share an object-type field. ~300 records = 45k pairs, one dump, no input, no menu.
Confirm with the jump: both fighters arc together, so `y_i - y_j` should track the sprites'
vertical difference.

## Round 4 — the pair discriminator needs a stable arena; attract mode is not one

Worker A (single worker, no writes, no menu) tested the camera-invariant difference
`(x_i - x_j) == (sprite_yellow - sprite_orange)` and it does not close:

* **Per-sample matches are chance.** A clean sample matched 9 record pairs at error < 4 px;
  another matched 9; a small sprite delta (18 px) matched **562** pairs. Static decorations
  sit at regular spacings (a y=52 row stepping ~197 px), so geometry alone is not selective.
* **Multi-sample consistency returns 0.** The attract demo **changes rooms every few
  seconds**: records teleport (`x 944 -> 79`, `y 96 -> 199`) between two dumps 0.3 s apart,
  so "same address, consistent offset" never holds for 6 samples.
* The one pair that was camera-consistent over time (implied camera offset (63,38), scale
  1:1) was *static* — decoration.
* While the fighters visibly moved, no record passing the filter (fractional x∈(0,960),
  y∈(15,260)) moved smoothly: the only movers were integer particle/debris records that
  reset on room change. So either the filter excludes the fighter records or the scale
  assumption is wrong — both are testable.

## The arena the next attempt should use

Round 3's worker A established something valuable that round 4 did not use:

> the LOCAL READY screen is **drivable** — yellow screen x 22 -> 90 -> 22 under `d` then
> `a` — and the camera there is **fixed** (world shift 0).

A fixed camera removes the camera algebra entirely: room `x` maps **1:1** to screen `x`,
so the fighter record is simply the one whose `x` delta equals the sprite's screen-x delta
while `d`/`a` is held, verified over many samples with no room changes. That is a far
stronger test than the difference trick, and it needs no writes.

## Round 5 — P1's record is identified and proven (READY, fixed camera)

```
P1 record: 0x191c400     x @ +0xEC     y @ +0xF0 (=128, feet)     dup x @ +0xFC
siblings:  idem 0x191c800 (sword, same position)   0x191c600 (arm, x offset -8)
```

Method: on the LOCAL READY screen the camera is **fixed** (`world shift 0`), so room x maps
1:1 to screen x. Alternate `d`/`a` eight times and keep the record whose `x` delta equals
the yellow sprite's screen-x delta:

| transition | sprite x | record x | error |
|---|---|---|---|
| 1..8 | 21.7 ↔ 78.1 | 21 ↔ 78 | **0.15 – 1.78 px** (8/8 pass) |

Worst error 1.78 px, camera offset 0.1 px. That is the first *proven* fighter address in
this project.

### Two traps this exposed

* **READY positions are integers** (screen space). The `fighter_records` fractional filter
  (calibrated on attract-mode room coords) misses it entirely — scan all 0x200 records and
  match deltas instead.
* The default yellow centroid is biased ~1.5 px near the left wall by the yellow floor
  strip at y≈126–127: crop above it.

### What is still missing, and the shortest way to it

`y` is unverified here (`space` does not jump on READY), and addresses move per room. But
round 5 hands us the thing every previous round lacked: **a ground-truth fighter record**.

Next step is therefore small: read the **object-type field** from `0x191c400` (compare it
with the sword at `0x191c800`, the arm at `0x191c600` and a particle record), then find
instances by type in any room. That is the discriminator that has blocked identification
since round 1 — and it converts to the full state map (P1, P2, sword) immediately.

## Round 6 — the state interface is complete

Worker A found the discriminator: **`u32 @ +0x88`** on each 0x200 record holds a pointer to
the object definition. Grouping records by that value yields the two fighter bodies, and
nothing else matched at similar positions:

```
type 0x174f900 → 0x191c400  x =   8.0  y = 128      ← matches the yellow sprite (8.7 px)
                 0x191bc00  x = 202.0  y = 128
type 0x1731e00 → 0x191d800  x =  24.0  y = 112      (second pair, same layout)
                 0x191d600  x = 248.0  y = 112
```

P1's identity was independent of memory: 8 alternating `d`/`a` holds tracked the yellow
sprite 1:1 with worst error 1.78 px, and P2's record matched the orange centroid within
1.4–1.6 px in worker A's own cross-check.

```
record stride 0x200      x @ +0xEC      y @ +0xF0      type @ +0x88
duplicates               x @ +0xFC      y @ +0x100
siblings                 sword = body + 0x400     arm = body + 0x200
```

`nidstate.find_fighters(pid)` implements it: scan the heap at 0x200 stride, group by
`u32@+0x88`, keep groups of exactly two whose members stand on the same ground line and are
apart. Two pairs survive on this screen; the tie-break is free — the member whose `x`
matches the yellow sprite's screen x is P1 (fixed-camera screens only).

### Known limits (be honest with the ML side)

* The type pointer's *value* changes per run, so it must be re-derived (round 6's recipe).
* Verified on the READY screen, whose positions are **integer screen space**. In a real
  match positions are fractional room space and the camera follows — the record is the same
  structure, but P1-vs-P2 labelling there needs the type grouping, not the sprite.
* `y` was never verified by input (nothing jumps on READY); it is 128 = ground for P1 at the
  start line, consistent with worker C's attract-mode arcs.

## Round 7 — the control gate exists and both controls behave

`nidstate.control_gate(i)` — **read-only**, three independent checks, and it has been run in
both directions:

| check | attract (must fail) | READY (must pass) |
|---|---|---|
| **A control**: holding `d`/`a` moves the sprite in the key's direction, twice in a row | **0.0 px** → fail | **100.8 px** → pass |
| **B identify**: the record's `x` delta equals the sprite's on every transition, sampled in the *same pass* | no record tracks | `0x1918a00`, 12/12 transitions, errors 0.44–1.98 px, **median 0.87** |
| **C negative**: no other record tracks it that well | — | next best **51.18 px** |

Evidence files: `docs/gate/attract.json`, `docs/gate/ready.json`.

### Writes are deliberately *not* part of the gate

Two attempts to include a write-based check (accumulate +40 px on P1's `x` at 2 kHz) **killed
the game** — once for worker A in round 3, once here. Writes remain a separate capability with
their own risk profile; no automation should depend on them until the crash is understood.

### Four bugs this exercise surfaced (all mine, all fixed)

1. `drivable()` used a magnitude threshold — but the attract demo's own AI moves the fighter
   10–12 px per 0.7 s, which *passes* any magnitude test. Now it requires the delta to
   **reverse sign with the key**, twice. Chance of a false pass: ~6%.
2. `find_fighters()` returns the **record base**, and the gate was reading `x` at the base
   instead of `base + 0xEC` — so it kept measuring the constant `10.4024` and reported zero
   drift. Helper `read_x()` now exists for exactly this.
3. The sprite series and the record series were sampled in **two separate passes**, so they
   were misaligned in time (~4.7 px of pure error). Now one pass reads sprite + all candidates
   back to back.
4. `identify_p1(..., verbose)` passed positionally into `cycles`, silently running 2
   transitions instead of 12.

### What the gate means for the project

It is now possible to assert, mechanically, *"this game state is under our control and the
memory we read is the object that is drawn"* — with a negative control that fails on the
attract demo. That assertion is the precondition for every remaining contract row (sword,
death, rounds, animation states), and it is what makes parallel workers safe: they can refuse
to work in a bad state instead of spending 25 minutes measuring noise.

## The game runs on the server (artemis, Ubuntu 24.04, 384 cores, no GPU, no sudo)

First working launch, verified through our own code (`nidstate.grab` → luma 21–25, window
alive):

```
window after 25 s (warm prefix; ~2.5–3 min cold, loading data.win is 105 MB)
DISPLAY=:41  PROTON_USE_WINED3D=1  proton run  ->  Nidhogg.exe
```

### Three root causes, in order of how much time they cost

1. **The Steam stub was the bug, not the fix.** `gbe_fork` (and plain Goldberg) hang inside
   `SteamAPI_Init` — the game stays at 2 threads in `do_select` and never creates a window.
   With **Valve's original `steam_api64.dll`** the init call simply *fails* and the game
   carries on. We do not need a stub at all.
2. **`proton waitforexitandrun` runs `wineserver -w` first**, which blocks forever if any
   wineserver persists on the box. Use **`proton run`**.
3. **Loading takes 2.5–3 minutes and our waits were 90 s** — and worse, *workers' own cleanup
   scripts* (`pkill -9 -x Nidhogg.exe`, `pkill -f 'proton waitforexitandrun'`) were killing
   every launch ~60 s in. No launch could ever have survived. `NID_WINDOW_WAIT` is now 300 s
   and `nidlinux.py await <i>` waits properly.

Server-specific notes: `PROTON_USE_WINED3D=1` avoids DXVK/lavapipe shader-compile stalls on a
GPU-less box (lavapipe *is* installed and valid; the stalls were shader compilation, not a
missing device). `xdotool` needs the runtime env (`PATH` + `libxdo.so.3`) or it exits silently.
`data.win` at 320×200 makes the window cheap; the game renders at 640×480 screen with a
320×200 window.

## Server session — three corrections, one of them embarrassing

**1. "1 fps" was a measurement artifact.** Counting frame changes by calling `frame()` in a loop
measures the *capture* rate: one screenshot round-trip is ~0.9 s under load. Using a single
streamed `x11grab` capture and diffing consecutive frames: **59.9 fps at the title, 57.2 fps in a
live training match** (34.5 fps when the box is busy with other tenants). `nidlinux.fps()` now
does it correctly. Lesson: never measure frame rate one screenshot at a time.

**2. The menu's yellow ● dots are decoration, not the selection.** Every row has one. The actual
selection is the **grey highlight bar** across the row. Our `selected_y()` has been reading the
dots since the laptop, which is why "Up/Down moved the selection" observations kept contradicting
each other and why navigation was never reliable. The navigator must detect the bar row.

**3. Stale `wineserver` processes wedge new launches.** Six had accumulated from killed runs; a
new instance then never creates a window (300 s timeout, no error in the log). Clean boot recipe:
kill wineservers whose `/proc/<pid>/environ` mentions *our* farm, delete `inst/<i>`, relaunch — the
instance is re-copied from the template. This belongs in `start_ids()`.

Otherwise the user's menu state machine checks out on the first try: one `Return` (120 ms) from
the title lands in the menu, whose items are NEWS / SINGLE PLAYER / MULTIPLAYER / OPTIONS / EXIT /
EXTRAS / QUIT TO DESKTOP — the user's list plus EXIT.
