# Worker — identify both players' memory records in a LIVE match, reliably

## Entry is solved — use it, don't re-derive it

`nidstate.enter_match_v2(i)` gets from boot to a verified live match in ~58 s:

```
3 presses (title -> MENU -> MULTIPLAYER -> LOCAL/READY)
park yellow at wall - 0.333*W, orange at wall + 0.333*W   (measured firing band 0.28..0.42 W)
hold ~1.6 s  -> stage select (lit chandelier + castle preview)
Return       -> live match (fighters spawn high and FALL, ~3 s)
```

`nidstate.in_match(i)` = no menu AND no wall AND drivable (the wall exists only on READY).

## Known-good memory layout (from the laptop and from worker `m`)

```
record stride 0x200   x @ +0xEC   y @ +0xF0   object-type u32 @ +0x88   (float32/u32)
sword sibling = body + 0x400 (moves with the player)   arm = body + 0x200
```

Helpers you have: `nidstate._all_record_xs(pid)` → `{addr: (x, y)}` for every plausible record;
`nidstate.read_x(pid, addr)`; `nidstate.find_players_by_input(i)` (naive — see below);
`nidstate.find_fighters(pid)` (type grouping — candidate generator only).

## The problem: right now identification returns teleports, not players

A probe immediately after entering returned `P1: d 33 -> 1143` and `P2: Right 149 -> 1943`. Those are
not walks. In a wide room the camera scrolls and **hundreds of screen-space copies move ~1000 px**,
and right after `GO` the fighters are still spawning/falling. The whole difficulty is telling the
player record apart from its derived copies.

## Your job

Produce a **reliable** identification and a session map, then prove it repeats.

Suggested method:
1. `enter_match_v2(i)`, then **wait ~3 s for the fighters to land** before probing anything.
2. Snapshot `_all_record_xs`, hold `d` for ~0.4 s, snapshot, release, snapshot.
3. A record is P1 only if it satisfies *all* of:
   * moves by a **walk-sized** amount while held (roughly 15..200 px — reject the ~1000 px camera
     copies),
   * **stops** after release (|Δ| ≤ ~3 px),
   * **comes back** when `a` is held for the same time (|Δd + Δa| small) — this is what kills
     camera-derived and decay/lerp values, which do not reverse symmetrically;
   * its value stays in a sane room range and its y stays constant while walking on flat ground.
4. Repeat for P2 with `Right`/`Left` and require the record to be *different* from P1.
5. Confirm the sword: the record at `P1 + 0x400` should move by the same Δ as P1 while walking.
6. Re-read both addresses ~10 s later: they must still be the same records with the same roles
   (addresses are stable within a room; the heap base changes per process, never across rooms).
7. Repeat the whole thing on **2 more fresh instances** and report how many of 3 attempts succeeded.
   A method that works 1-in-3 is not a method.

## Rules

* Your own farm `~/.nidfarm-q`, display band `:160`. Source env first, then override:

  ```bash
  . ~/Developement/nidhogg-rl-install/results/env.sh
  export NIDFARM=$HOME/.nidfarm-q NID_DISPLAY_BASE=160 NID_GAME_DIR=$HOME/.nidfarm-q/game
  ```
* **Never `pkill -f`** (it matches your own command line and has killed a worker). Use
  `pkill -x <exact name>`; never kill processes you did not start — other users share this box.
* The heap base changes per process: never hardcode an address, always re-find.
* Screenshots cost ~1 s; `_all_record_xs` costs ~0.3 s cached. Build timing on the memory path, not
  on screenshots.
* Do not edit shared files; put diffs in `results/q.patch`.
* Budget **40 minutes**. A negative with numbers is a valid result.

## Deliverable

`results/q.json`:

```json
{"ok": false, "success_rate": "x/3",
 "players": {"P1": {"addr": "0x...", "x": 0.0, "y": 0.0, "sword": "0x..."},
             "P2": {"addr": "0x...", "x": 0.0, "y": 0.0, "sword": "0x..."}},
 "traces": {"d": [], "a": [], "Right": [], "Left": [], "sword_delta": 0.0},
 "recheck_10s": {"same_records": false, "same_roles": false},
 "refind_recipe": "how to find both players again after a room change",
 "read_state_recipe": "pseudocode returning both players' x,y and sword position",
 "dead_ends": []}
```

Final message: 8 lines max.

## Extra evidence from a quick manual run (use it)

After `enter_match_v2` + 3 s, holding `d`/`a` gave **2** symmetric candidates and **0** for the
arrows:

```
0x71512c6dca00   d -156.0   back +151.3   stop 0.0     <- symmetric but WRONG DIRECTION (camera-ish)
0x71512c5e6400   d  +22.1   back  -22.6   stop 0.0     <- walk-sized, plausible P1
P2: 0 candidates with Right/Left
```

So: (a) symmetry alone is not enough — also require the **sign** to match the key (`d` must increase
x, `a` must decrease it; a camera copy moves the other way), and (b) **P2 may not answer the arrow
keys in a match** the way it does on READY. Check whether P2 is alive/spawned at all, and try
`Left/Right`, `Up/Down`, `i/j/k/l`, and the pause menu's OPTIONS screen (which shows the bindings)
before concluding P2 is absent. If P2 really is not drivable in a local match, say so explicitly —
that changes the whole RL plan (self-play would need two instances instead of one).
