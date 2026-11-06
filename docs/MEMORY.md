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
