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
