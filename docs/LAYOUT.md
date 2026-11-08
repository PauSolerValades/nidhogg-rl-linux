# Memory layout — what we are sure of, and what we are guessing

Measured on the Windows build under Proton. Anything marked **proven** has a stimulus and an oracle
recorded in `docs/MEMORY.md`; anything marked **inferred** is a hypothesis with evidence but no
independent confirmation.

## Object records

```
stride 0x200, per-room, addresses change per process (heap base moves) AND per room
+0x000  ...           (not yet mapped)
+0x088  u32  type pointer       — one value per object type; heap pointer, changes per run
+0x0BC  u32  animation index    — proven (idle ~461-465, walk ~433-457, attack 443/445,
                                  jump 275-344, crouch/sword-down 255). Mirrored at +0x2BC, +0x4BC
+0x0D8  f32  facing             — proven: ±1.0, sign agrees with geometry; mirrored at +0x2D8
+0x0EC  f32  x                  — proven (1:1 with the sprite on a fixed-camera screen)
+0x0F0  f32  y                  — proven (192 = ground in the arena rooms, 128 = READY pads)
+0x0FC  f32  x duplicate        — provenance unknown (xprevious or a bbox copy)
+0x100  f32  y duplicate        — same
+0x200  object: "arm"           — different type pointer; moves with the body
+0x400  object: "sword"         — different type pointer; x,y bit-identical to the body while held
```

**The +0x200 / +0x400 offsets are NOT stable.** The chain reallocates during play (measured: the
arm slot disappeared and the sword slid from +0x400 to +0x200 inside one session). Identify the arm
and sword by their *type pointer* and by *behaviour*, never by offset arithmetic.

## Multiple swords

A sword can be thrown, and a dead player's sword stays on the ground, so **more than two sword
objects can exist** and they must be tracked as a *set*: held (moves exactly with the body),
flying (independent, fast, decelerating), stuck in scenery (independent, static), on the ground
(static, no owner). Not yet mapped: which type values distinguish them, and how many exist after a
throw.

## Input (measured on this build)

```
P1: a/d walk, w/s sword position (low -> mid -> up -> pre-throw), f attack, g jump
    f while in "pre-throw" throws the sword   (player-supplied; NOT yet confirmed in memory)
P2: arrow keys (Right/Left measured; i/j/k/l do nothing)
```

## Semantics measured so far

| thing | status |
|---|---|
| death | **no death byte**: the body record keeps its address and type and stops updating (x,y freeze) |
| score / rounds won | **unknown** — a candidate `0→1→2` was seen once (dump offset `0x7515168`, session 1) but not reproducible |
| round phase | **inferred** only: distinguishable by wall-present (READY) vs wall-absent + drivable (live) |
| room / substage | **unknown** — zone advances happen without ending the round (marked in session 2, not yet located in memory) |
| tick counter | proven to exist (a u32 at 60.0 Hz, 4 % jitter), address per process |
| action→observation latency | ~30 ms median ≈ 1.8 ticks (includes ~10-15 ms of xdotool spawn) |
| write semantics | `x += 300` on a proven body field is **kept** (no snap-back, no crash) |
| determinism | effectively yes: two identical scripts differ by a 3 px carried-in offset |
| role stability | **roles swap**: never infer P1/P2 from address order; re-prove by input after transitions |

## Ranges worth knowing

```
room widths seen: 320 (READY), 960, 1943 (castle)     arena ground: y = 192
READY pads: y = 128, at wall ± 0.333 W, firing band 0.28..0.42 W
tick: ~60 Hz          snapshot cost: 112 MB / 0.1 s per region, ~1.2 s for 1.1 GB
```

## The honest gap

Everything needed for *observations* is proven: both players' x/y, facing, anim, sword position,
plus a tick for timestamps. Everything needed for *episodes* is half-proven: resets work (writes are
kept), but the score and the round/room identity are still not located, so an episode cannot yet
know who won or where it is.
