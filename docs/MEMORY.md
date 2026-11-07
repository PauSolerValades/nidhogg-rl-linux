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
