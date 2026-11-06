# State extraction on Linux — what works, what does not

## Works

| Piece | Mechanism | Evidence |
|---|---|---|
| Headless instances | `Xvfb :N` + Proton, no window anywhere | 4 instances, 60 fps each |
| Silence | `[Software\\Wine\\Drivers] "Audio"=""` in prefix `user.reg` | 0 audio threads, 0 pulse sink-inputs |
| Cheap rendering | GEN8 window size `960x600` → `320x200` | 112% → 41% CPU, 25 → 60 fps |
| Parallelism | reflinked wine prefix + display per instance | `farm.sh init` / `start N` |
| Keyboard | `xdotool windowfocus` + XTEST, no WM needed | title→menu→submenu reached |
| **Memory read** | `spy/nidspy.so` via `LD_PRELOAD`, dumps **its own** memory on request | 112 MB dump in 0.1 s |
| **Memory write** | same `.so`, `poke <addr> <hexbytes>` | writing `0x1910af0` scrolled the view |

`/proc/<pid>/mem` does **not** work here: `ptrace_scope=1` and Proton's container both
refuse (EACCES on every region), and the game process reparents to systemd, so it is not
even an ancestor. `PR_SET_PTRACER`/`PR_SET_DUMPABLE` from the injected `.so` did not help.
In-process access sidesteps all of it and needs no root.

Protocol (`spy/nidspy.c`, ~50 lines):
```
/tmp/nid_cmd_<pid>   "dump <hexaddr> <hexlen> <abs-path>"   -> writes the bytes
                     "poke <hexaddr> <hexbytes>"            -> writes them
                     "ping"                                 -> /tmp/nid_res_<pid>
```

## Attract mode is the free test case

The title screen plays a demo fight: two live fighters, no input, no menu. That is enough
to hunt for state without solving menu entry first.

## Where the state is: first real lead

Positions are **float32**, not float64 (a float64 scan of the heap finds only counters).
Candidates found by motion, sampled at ~4 Hz on the heap at `0x16a0000`:

* `0x1910af0` walked `131 → 52` while a fighter walked left; `0x1910b24` (same block) sat
  7 px below it — consistent with `x` and `bbox_left` of the same instance.
* Poking `0x1910af0 = 260` scrolled the world, so the block is instance/view state, not
  a copy.
* Heap layout inside the region shows **512-byte (0x200) structures** containing repeated
  `(x, y)` float pairs in `[0, 960] x [0, 220]`, e.g. `(825,148)` and `(621,83)`; room
  widths are 320 and 960, so both fit as room coordinates.

Not yet proven: which offset is the player's `x` (as opposed to the CPU's, the camera's,
or a draw record), and where `y` and the round/health state live.

## Next, in order

1. **Close the identification with a controlled input.** Enter a match (menu entry needs a
   state machine, not fixed timings — the menu cycles back to attract mode), hold `d`, and
   keep the float32 slots that move right at ~12 px/s. Input-caused motion removes every
   ambiguity (camera, CPU, draw records).
2. **Enumerate instances by structure**: scan for the 0x200-stride blocks holding an
   `(x,y)` pair, and confirm exactly two of them move like fighters.
3. **Read per-tick instead of dumping**: once 4–8 offsets are known, extend the `.so` to
   sample just those addresses each tick into `/tmp/nid_state_<i>.txt` — the same file
   contract the macOS harness used, so `train_state.py`'s consumer side can be ported
   nearly unchanged.
4. Menu entry last: with the symbol table (name → function) the `.so` can call
   `localTestTraining` directly and the whole 7-key dance disappears.

## Cost per instance@320x200

~40–56% of one core, ~455 MB RSS, 60 steps/s, silent, no window.
8 cores ≈ 14 instances ≈ 840 steps/s.

## Menu entry — measured map (2026-11)

Screens, in the order the Enter-only path visits them:

```
attract demo (fighters play themselves)
  -> title "PRESS ____"
  -> MENU:  ARCADE / SINGLE PLAYER / MULTIPLAYER(selected) / OPTIONS / EXIT TO DESKTOP
       MULTIPLAYER -> LOCAL(selected) / ONLINE
       LOCAL -> READY screen (YELLOW vs ORANGE)      <-- traps: round never starts
  in a match: ESC -> PAUSE: CHANGE COLOR / JEN TOLERANT / OPTIONS / EXIT
       EXIT -> "QUIT TO DESKTOP? NO / YES"           <-- hazard: Escape spam can land here
```

What is reliable:

* `Down` / `Up` move the selection one item per press (verified in the pause menu and,
  with screenshots, in the main menu). No wrap surprises other than the list wrapping.
* `Return` confirms — **but it is silently dropped** when it arrives during a transition
  or during the title fade. This is the whole reason fixed key sequences are flaky.
* Both input paths work: XTEST (`xdotool key`) and XSendEvent (`xdotool key --window`);
  neither is immune to the dropped-key problem.
* Keys sent in the first ~15 s after launch go nowhere (`WARMUP`).

Consequences baked into the tooling:

* Never send a bare key sequence: every step must be **verified against the screen**, and
  retried when nothing changed. `nidlinux.py press()` does this (stable-pixel diff, immune
  to the animated backgrounds).
* Prefer the LOCAL 2-player match for state discovery: both fighters are ours, and the
  round not starting does not matter for finding `x`.
* The selection is readable without OCR: the selected row is drawn on a lighter bar
  (detector works on the pause menu; the main menu box sits lower and needs its own
  thresholds).

## Where the state hunt stands

`findstate.py` (hold `d`, keep float32 slots moving right at 12 px/s, confirm with `a`)
returns 0 candidates while entry is unconfirmed — the scan needs a real match, so entry
determinism is now the blocking item. The physics has been observed directly: `d`/`a`
move YELLOW at fighter speed on the READY screen, which is the ground truth the scan
should latch onto.

Next: a `goto_row(i, k)` built on the bar detector (press `Down`, verify the bar moved,
retry when dropped) — that turns menu entry into a retried state machine instead of a
timed key dump, and unblocks the scan.

## 2026-11: `in_menu()` is not trustworthy yet

`darkfrac > 0.35` in the box region separates menus (0.39–0.47) from the title (0.00) and
the bright attract levels (0.22–0.25) — but the **castle attract level is dark enough to
false-positive**. A live run returned "menu: True" on the attract screen, so `ensure_menu`
stopped pressing too early and the following Up/Return were spent on the title fade.

Fix candidates, cheapest first:

1. Use the **scan itself as the entry verifier**: a match exists iff holding `d` makes a
   float32 slot move right at fighter speed. Then entry does not need to know which screen
   it is on — it tries an entry variant and asks the *game state* whether it worked. This
   is the macOS harness's "verify by CPU motion" idea, but with a signal that cannot be
   faked by an animation.
2. Require the menu box to have bright text pixels inside the dark block
   (`brightfrac` small but nonzero) and a straight border, which the castle level lacks.
3. Detect the selection bar (works on the pause menu) and use "the bar moved by exactly
   one row" as the acknowledgement that a Down landed.

## 2026-11: motion found, but it was the camera

Widening the drift window (fighter moves **~115 px/s**, not the 12 px/s the macOS notes
recorded) finally produced candidates while holding `d`:

```
0x191c0d0  f4  688 -> 749   (rising ~20 per 0.2 s sample)
0x191c4d0  f4  (same values, exactly 0x400 higher)
```

Both look like `x`... and are **not**: holding a sustained write (`x = 60` for 2 s, 30
writes/s to beat the physics) does not move the sprite at all. Their values agree to
within 1 px and are 1024 bytes apart, which is what two *view* variables (one per player)
look like — the runner recomputes them from the instance's real position every frame.

Lessons:

* A drift-only filter cannot tell an instance position from a value *derived* from it.
  Every moving thing (camera, draw record, bbox, xprevious) becomes a candidate.
* **Poke-and-watch is the only proof.** One write is useless (the next frame overwrites
  it); the test has to hold the value across several frames and check the sprite moved.

## Next: brute-force proof loop

1. Stimulus: hold `d` 1.5 s, keep slots that changed by 100–400 px (fighter travel).
2. Oracle: the fighter is the **only bright-yellow blob** on screen; its centroid `x` is
   trivially extractable from a screenshot.
3. For each candidate: hold `x = 60` for ~0.5 s, screenshot, measure the yellow centroid.
   A jump to the left wall proves the slot. Restore, next candidate.
   ~50 candidates × 1.5 s ≈ 1–2 min per pass, fully automatic.
4. The confirmed slot also gives the struct layout: `y` and neighbours are then found by
   reading around it, and the second fighter by scanning for the same offsets elsewhere.

## 2026-11: poke-and-watch works mechanically, but the oracle is confounded

The loop runs end to end: 39 candidates from the drift stimulus, pinned with the spy's new
`hold <addr> <bytes> <ms>` (pins a value across frames at 2 kHz so the game cannot
overwrite it), sprite position read from the pure-yellow mask. It "confirmed"
`0x1920ccc` twice, on two fresh instances.

It is wrong. Controls:

```
slot value 0.0 while the sprite sat at screen x=85   -> not a position
held -60 -> sprite 89 | held 0 -> 95 | held +60 -> 136
```

The sprite **drifts on its own** between probes (89 -> 95 untouched), so "moved 39 px"
cannot be attributed to the write. The slot behaves like a velocity/offset input.

Two things to fix before the hunt is worth re-running:

1. **Kill autonomous motion.** The READY screen looks static but is not. Cleanest fix
   available: `Escape` opens the PAUSE menu, which freezes the simulation while the
   renderer keeps drawing. Poke while paused and the sprite can only move because of our
   write — zero drift, zero noise (baseline noise already measured as 0 px there).
2. **Use a monotone, multi-point criterion, not one jump.** Pin the candidate to
   v-120 / v / v+120 in alternating order twice, and require the sprite position to be an
   injective function of the pinned value (A B A B on two levels). A drifting value fails
   this; a real position passes.

Also worth noting: with the game paused, the same harness can find `y` (poke to 40 and
the sprite should rise), and the P2 instance by repeating the protocol for the orange
player.

## 2026-11: paused oracle is clean; the candidate generator is the weak link

The paused protocol works and is worth keeping:

* paused screen drift: **0 px** (measured), so any changed pixel is caused by our write;
* a write that affects nothing is provably not read by the renderer, which instantly
  eliminates velocities/accumulators (no ticks while paused);
* three-point probe (`60 / 300 / 60`) with a restore afterwards catches non-reproducible
  (drifting) values.

What it showed: **every drift candidate repaints the whole 320×200 frame**
(bbox 319×199), i.e. they are view/surface state — their neighbours are surface
dimensions (`1018.49, 208.66`), so writing them rescales or re-blits the surface. That is
also why the earlier "poke moved the sprite" readings were junk: the whole scene moved.

Conclusion: **drift is the wrong candidate generator.** It finds everything *derived* from
the position (view, camera, surface, draw records) and buries the instance itself.

Options for the next attempt, in order of effort:

1. **Sweep, don't drift.** With the game paused, walk float32 slots whose value looks like
   a coordinate (0..1000) inside the heap regions, one write each, and keep any that
   repaints a *sprite-sized* bbox. The paused oracle makes each test unambiguous; the cost
   is ~1 s per slot, so the candidate set has to be pruned by structure, not motion.
2. **Use the instance structure.** The heap holds repeated 512-byte records with `(x, y)`
   pairs. Locate them by shape (two floats in plausible ranges at a fixed offset), then
   test the x of each with the paused protocol. Structure, not motion, generates candidates.
3. **Stop looking, start training.** The yellow/orange centroid oracle already gives both
   fighters' screen positions from a screenshot at ~0 cost, headless, no permissions. That
   is a usable observation channel today. Memory RE is then only needed for *episode
   resets*, not for observations.
4. **Hook the renderer.** In-process code execution is already ours (`LD_PRELOAD`); hooking
   `DrawIndexed`/`Present` would yield every sprite's screen position exactly. Heaviest,
   most complete.
