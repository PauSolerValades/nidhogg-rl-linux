# Worker C — structural census of the fighter records (no menu, no input)

GameMaker YYC game, headless under Proton, no symbol table. Read `docs/FINDINGS.md` and
`docs/MEMORY.md` first.

## Why you are different from the other two workers

They need a *controllable* match, which means fighting the menu. **You do not.** The
title screen plays an attract-mode demo: two fighters fight, jump and die by themselves,
with no input from us. That is enough to census the data structure.

## What is already known (do not re-derive)

* Positions are **float32** and **fractional** (round-integer slots in 0..200 are screen
  draw records at `0x818xxxx`, not instance state).
* A previous worker found a full jump arc in room space:
  `0x19004f0` y `191.8 -> 52.4 -> 172.5`, with `x` at **4 bytes before** it
  (`939.3 -> 936.6`). Room widths are 320 and 960, so these are room-space coordinates.
  Addresses change per run and per room — find them again, do not trust the number.
* The camera follows P1 horizontally, so **screen position is not a reliable proxy** for
  the fighter's own motion. Use the *values* in memory, not the sprite.
* Screen oracles: P1 is pure yellow `(255,255,0)`, P2 orange `(255,160,64)`. Warning: in
  dark arenas the **goal flag is also a big yellow blob** — filter by blob size and y.
* `nidlinux.memory(pid, addr, size)` reads via the in-process spy;
  `nidlinux.poke(pid, addr, bytes)` writes. `/proc/<pid>/mem` does not work here.

## Your goal

Produce a **structural map** of the fighter records, reliable enough to re-find them after
a room change.

Suggested procedure:
1. Confirm you are in attract mode (`nidstate.sprite_present(0)` true while you press
   nothing). No menu work.
2. Census: dump every rw region under ~16 MB (`nidstate.regions`) and collect f32 slots
   whose *fractional* value lies in `0..1000`, together with a partner 4 bytes earlier in
   `0..260`. Group them by the address distance between the pair and by the distance
   between consecutive records. Report the strides you see.
3. Record N=12 dumps ~0.15 s apart. Classify each candidate record by its motion profile:
   smooth bounded drift in room range (a fighter walking), V-shape (a jump), constant
   (a wall/decoration). Identify the **two** records that move independently, like the two
   demo fighters.
4. Neighbour scan: around a confirmed fighter record, dump ±0x80 bytes and describe every
   field you can justify — small integers (0..10) that could be health/score/facing,
   floats in [-1,1] (facing/anim), pointers into the same heap. **Mark each field proven or
   inferred**; do not guess silently.
5. Write a concrete re-find recipe: the minimal scan that locates the record again after a
   room change (e.g. "f32 in 0..960 with partner-4 in 0..260, record stride 0x200, region
   base found by value"). This recipe is the deliverable that matters most.

## Rules

* Only your own farm/worktree/display (env vars are set). `nidstate.restart(0)` after a
  segfault.
* Do not waste budget on the menu — you never need it. Avoid writes unless a pause-free
  attribution is possible; in attract mode the AI moves both fighters, so prefer structure
  and motion profiles over poke-and-watch.
* Budget: **25 minutes**. One `census.py` you iterate on; terse output.

## Deliverable

`results/c.json`:

```json
{"tag": "c", "goal": "fighter record layout", "records": [{"addr": "0x...", "role": "P1|P2|unknown",
  "x": "0x...", "y": "0x...", "motion": "walk|jump|static"}],
 "strides": [0], "fields": [{"addr": "0x...", "what": "health?", "proven": false}],
 "refind": "minimal scan to locate again"}
```

Final message: 5 lines max (records found / strides / best proven fields / re-find recipe /
dead ends). Stop there.
