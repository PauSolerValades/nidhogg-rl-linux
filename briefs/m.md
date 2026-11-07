# Worker — make the memory session map work in a MATCH room, not just READY

## Where the project is

The game runs headless here (Proton-GE, `wined3d`, ~60 fps), the menu is navigable, and there is a
working entry path to a **real match**:

```
title --Return--> MENU (MULTIPLAYER selected) --Return--> submenu (LOCAL) --Return--> READY
READY: walk each fighter onto its own coloured pad (P1 yellow: a/d. P2 orange: arrow keys),
       stand still ~2 s. When BOTH stand on their pads, stage select appears -> match.
```

`scripts/step_on_pad.py <instance>` already walks both fighters onto their pads using pixel
feedback (pad = widest colour run in the lower half; fighter = its own colour blob; closed loop).

## The proven memory layout (do not re-derive)

```
record stride 0x200    x @ +0xEC    y @ +0xF0    object-type pointer @ +0x88  (all float32/u32)
duplicates             x @ +0xFC    y @ +0x100
siblings               sword = body + 0x400      arm = body + 0x200
```

`nidstate.find_fighters(pid)` groups records by `u32@+0x88`, keeps groups of exactly two whose
members stand on the same ground line, and returns `(addr, x, y, type)`. **This works on READY.**

## The problem you are solving

On the match screen, `find_fighters()` returns **[]**. So one of these is false in a match room:

* "exactly two records share the type pointer" (a match may add instances of the same object),
* the type pointer itself may differ between rooms (it is a pointer into the heap),
* or the fighter records are allocated elsewhere / at a different alignment.

Your job: produce a **room-independent way to find the two fighters**, and a session map that
survives READY → match.

Suggested procedure:
1. Boot your instance, get to READY (three `Return`s from the title, ~12 s after the window for
   the splash). Confirm with `nidstate.menu_geometry` returning None plus a pad being detected.
2. On READY: run `find_fighters`, record the type value, addresses, x/y. **This is your anchor.**
3. `scripts/step_on_pad.py <i>` → match. Confirm the screen changed (fighters present, no pads).
4. Re-enumerate every 0x200 record and group by `u32@+0x88`. Report every group of size 1..8 whose
   members have plausible `x@+0xEC ∈ (0,1100)` and `y@+0xF0 ∈ (15,300)`, and whether the anchor
   type value still appears — and with how many members.
5. Identify the two fighters by **behaviour, not position**: hold `d` for 0.6 s and require a
   record's `x` to change *and then stop changing* when released (camera-follow makes the sprite
   useless as an oracle; `x` causality does not lie). Repeat with `Right` for P2.
6. Report the recipe: how to find the fighters in any room, and whether the type pointer is stable
   across the transition.

## Rules

* Your own farm `~/.nidfarm-m`, display band starting `:130`. Source the runtime env **first** and
  then override:

  ```bash
  . ~/Developement/nidhogg-rl-install/results/env.sh
  export NIDFARM=$HOME/.nidfarm-m NID_DISPLAY_BASE=130 NID_GAME_DIR=$HOME/.nidfarm-m/game
  ```
* **Never `pkill -f`** (it matches your own command line — this killed a worker once). Use
  `pkill -x <exact name>`; other workers share this box, so never kill processes you did not start.
* Do not edit shared files (`nidstate.py`, `nidlinux.py`, `docs/`); put a diff in
  `results/m.patch` instead.
* Budget **40 minutes**. A negative with numbers is a valid answer.

## Deliverable

`results/m.json`:

```json
{"tag": "m", "found": false,
 "ready": {"p1": "0x...", "p2": "0x...", "type": "0x..."},
 "match": {"p1": "0x...", "p2": "0x...", "type": "0x...", "group_sizes": {}},
 "type_stable_across_rooms": null,
 "causality": {"d": {"addr": "0x...", "moved_px": 0, "stopped": true},
               "Right": {"addr": "0x...", "moved_px": 0, "stopped": true}},
 "recipe": "how to find the fighters in any room",
 "dead_ends": []}
```

Final message: 6 lines max.
