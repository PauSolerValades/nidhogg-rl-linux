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
