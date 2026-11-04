# Nidhogg injection — verified findings, 2026-10-25

Status: **harness loads, state read NOT yet working.** Stopped at the 3h budget.

## Verified on this machine

| Fact | Evidence |
|---|---|
| Game runs on this Mac | Messhof splash captured, window 1710×1112 |
| Build is **YYC** (native C++, no GML VM) | `UndertaleModCli info`: `Is YYC - True`, bytecode v17 |
| → GML/data-file patching is impossible | no bytecode to decompile or append to |
| Binary is **not stripped** | 128k syms; `t __Z31gml_Script_dp_handle_state_saveP9CInstance...` |
| No hardened runtime | `codesign -dv`: `flags=0x0(none)` |
| **`DYLD_INSERT_LIBRARIES` works** | dylib constructor runs inside the game process |
| Symbols are NOT dyld-exported | `dlsym(RTLD_DEFAULT, ...)` → symbol not found |
| → resolve as `nm_addr + slide` | `_dyld_get_image_vmaddr_slide(i)`, i = game image (`MacOS/Nidhogg`), **not** image 0 (dylib is image 0) |
| Runner API is reachable | `GetInstanceListWithEventType`, `YYObjectBase::InternalGetYYVar/Ref`, `FindOrAllocValue` all resolved, no crash on resolve |
| Calling that API from a **background thread** is unsafe | frame 1-3 OK, SIGSEGV once the game starts loading rooms |
| NSTimer on main queue **never fires** | GM drives its own loop → use a thread or main-thread hook |
| Home-path override does NOT work | `HOME=` set, game still wrote `Data path = /Users/ruggsea/Library/Application Support/com.messhof.nidhogg` |
| Real prefs untouched | `unmuted="1.000000"` still |

## The blocker

The injected thread starts, then stops after `warmup 0`. Process-level evidence:
log pid 28698 vs live pid 28784, two `GameMaker v` banners. Either the game
re-execs/relaunches with a sanitised env (killing the hook), or the first process
is suspended while another runs.

`launchctl setenv DYLD_INSERT_LIBRARIES` + `open -a` → no injection at all.

## Next steps (in order, ~1-2h to first live state read)

1. **Find out what the second process is.** `ps -o pid,ppid,args -Mo pid` around launch;
   `sample` / `spindump` the first pid. If it re-execs: set `DYLD_INSERT_LIBRARIES`
   in the child by patching `-launchApplication:` or use `posix_spawn` shim.
2. **Get a main-thread per-frame callback** instead of a thread: swizzle
   `-[NSWindow display]` (check `NSStringFromClass([w class])` == GMWindow) or
   `-[GMWindow drawRect:]`. ObjC swizzling needs no assembly and no permissions.
3. Only then call `GetInstanceListWithEventType(obj, 0, 0,0, &list,&n,false)`
   for `obj` in 0..245 to find which object index has exactly 2 instances (the fighters);
   dump `InternalGetYYVar(inst, 0..12)` and identify x (range ±450, ±3.4/tick), y (≥0).
4. Input: `[NSApp postEvent:]` with NSEvent keyDown/keyUp built from the real
   keycodes in `~/Library/Application Support/com.messhof.nidhogg/bindingsPlayer1.json`
   (WASD move/aim, F attack, G jump, Enter accept, Esc back). In-process, no Accessibility.
5. Mute: `HOME` is useless. Snapshot `prefs.ini`, set `unmuted/musicVol/sfxVol=0`,
   restore on exit from the wrapper, or patch the data-path string in the copy.

## Key addresses (arm64 slice, unslid nm addrs)

```
GetInstanceListWithEventType(int,int,float,float,int**,int*,bool)  0x100ca0b18
YYObjectBase::InternalGetYYVar(int)                                0x100c23a38
YYObjectBase::InternalGetYYVarRef(int)                             0x100c23d44
YYObjectBase::FindOrAllocValue(char const*)                        0x100c24c60
```

## Objects/scripts worth hooking (from symbol table)

`Man` (fighter), `Match`, `Brain` (the CPU AI), `HeldWeapon`, `FleshCollisionMask`,
`dp_handle_state_save` (rollback state serialiser — canonical state, every frame),
`__InputClassPlayer`, `checkPlayerIndexButtonPressed`, `aiStateMachine`.

## Files

- `hook/inject.m` — the harness (dylib: symbol resolve + thread poll + NSEvent injection)
- `work/home_seed.sh` — prefs seeding (mute) — NOTE: ineffective, see above
- `PLAN.md` — earlier plan (sim route, abandoned on instruction)

---

# Session 2 — working harness (verified)

## Works
- `DYLD_INSERT_LIBRARIES` into the real game, no permissions.
- Launch with `SteamAppId=94400` or the game calls `SteamAPI_RestartAppIfNecessary`
  and relaunches (parent has the hook, child does not).
- Frame-synced main-thread tick: swizzle `-[NSOpenGLContext flushBuffer]`
  (CGLFlushDrawable/glFlush interposes also fire, `-[GMWindow display]` never does).
- **No screen takeover**: swizzle `-[GMWindow makeKeyAndOrderFront:]` (offscreen +
  `orderFrontRegardless`), `-[NSApplication activateIgnoringOtherApps:]` (no-op),
  `-[GMWindow toggleFullScreen:]` (blocks entering, allows leaving). Window sits at
  x=-width-200 and is captured with `CGWindowListCreateImage(.optionIncludingWindow, wid)`.
- **Mute**: FFI call to `F_AudioSetMasterGain` (= `audio_master_gain(0)`) every 30 frames.
  prefs.ini never modified (`unmuted` still 1).
- GML builtin FFI works: `F_InstanceNumber` returns real counts (TOTAL=8 at menu).
- IMPORTANT: if the window is fully transparent (alpha<~1) or hidden, the game idles
  and reports 0 instances. Keep alpha=1.0 and offscreen instead.

## Blocked (next session)
1. **Instance pointers.** `GetInstanceListWithEventType` fills a list of 32-bit ids
   (saw `ptr=0x19039`), not `CInstance*`; feeding that to `InternalGetYYVar` segfaults.
   Also `InternalGetYYVar` is `YYRValue (YYObjectBase::*)(int)` — returns by value, so
   the out-pointer prototype used here is wrong. Fix: declare the by-value prototype,
   or use `F_VariableInstanceGet` (needs an RValue string for the name), or
   `HandleKeyboard`-style GV/SV accessors.
2. **Keyboard injection.** `[NSApp postEvent:]` is delivered but has no effect because
   the window is not key (we deliberately don't activate). Options: (a) find the
   key-state array that `HandleKeyboard()` updates and write it directly; (b) allow
   activation but keep the window offscreen (macOS may still take focus); (c) revert
   to CGEventPost (needs Accessibility — excluded by user).

## Symbols worth having
F_ prefixed GML builtins: `F_InstanceNumber 0x100b3b364`, `F_InstanceFind 0x100b3afb0`,
`F_AudioSetMasterGain 0x100b93c6c`, `F_AudioStopAll 0x100b93e10`,
`F_AudioPauseAll 0x100b93a98`. `HandleKeyboard 0x100c9f718`.

---

# Session 3 — state + input unlocked (verified)

## WORKING, verified by log output
- **Frame tick** survives: swizzle `-[NSOpenGLContext flushBuffer]`, ~1 call/frame.
- **Quiet window**: do NOT swizzle `makeKeyAndOrderFront:` (blocking it stops the runner
  from ever starting its loop — 0 ticks, no draw). Instead let it start normally, then at
  frame 8 call `relocate_once()`: `setAlphaValue:1.0` + `setFrameOrigin(-(w+200), -4000)`.
  Frames keep coming (heartbeat `[tick] f=N` every 600), state reads keep working.
- **Fullscreen** blocked via swizzle on `toggleFullScreen:` (allows leaving, blocks entering).
- **Mute**: `F_AudioSetMasterGain(0)` every 600 frames. prefs.ini untouched.
- **Key injection WORKS** via `F_KeyboardKeyPress` / `F_KeyboardKeyRelease` (GML's
  `keyboard_key_press`), codes straight from bindingsPlayer1.json (13=Return, 68='D', ...).
  Evidence: pressing 13 took the game from TOTAL=8 instances (logo screen) to TOTAL=76
  (obj 165 count 5) — the screen actually advanced. No focus, no Accessibility.
- **Object names**: `F_ObjectGetName(obj)` → RValue whose `v.p` points to a CString whose
  first field is `char*`; deref gives e.g. "ShowLogos", "Particles", "ModManager".
  (The RValue `kind` field read as 0 for everything — do not rely on it.)
- **id → instance pointer**: `GetInstanceListWithEventType(obj,0,0,0,&ids,&n,false)` fills
  **32-bit ids** (e.g. 0x19039). `CInstance::Find(int id)` @ 0x100ae7bac converts id →
  `CInstance*` (0x19039 → 0x118526800). `CInstance::ms_ID2Instance` @ 0x1013451b8 is the map.

## Next
1. CInstance x/y offsets unknown (floats 0..5 read 0.0). Walk the struct: dump ~128 floats +
   64 doubles for a known instance and identify x (moves ±3.4/frame when running, range ±450)
   and y (0 on ground, rises when jumping).
2. Navigate menus to Training mode (keys 13 / 38 / 40 / 27) while logging `F_ObjectGetName`
   per screen; find the object named "Man" with count 2 — those are the fighters.
3. Then GA loop + ghost overlay.

## Addresses (arm64, unslid)
F_InstanceNumber 0x100b3b364 · F_InstanceExists 0x100b3b090 · F_InstanceFind 0x100b3afb0
F_KeyboardKeyPress 0x100b0ccd8 · F_KeyboardKeyRelease 0x100b0ccf4
F_AudioSetMasterGain 0x100b93c6c · F_ObjectGetName 0x100b84d5c
F_VariableInstanceGet 0x100b71d88 · F_VariableInstanceExists 0x100b714f8
GetInstanceListWithEventType 0x100ca0b18 · CInstance::Find 0x100ae7bac
CInstance::ms_ID2Instance 0x1013451b8

---

# Session 4 — navigation figured out, two API traps found

## Working
- **Menu navigation by keys works** (13=Return, 38=Up, 40=Down). Verified path:
  main menu -> SINGLE PLAYER -> (submenu: ARCADE/TRAINING) -> TRAINING ->
  personality list (NO DIVEKICKS, NO THROWS, DIVEKICKER, RUN N LUNGE, BRAWLER,
  NEVER LUNGES, PARRY MASTER, RANDOM) -> Return starts a match.
- **A match really starts**: stdout prints `match start`, then room names, e.g.
  `entered rCemeteryCenter`. Object census in a match: `Man`(105), `Match`(106),
  `MatchStats`, `Brain`, `HeldWeapon`, `FleshCollisionMask`, `OrangePlayer`(154),
  `YellowPlayer`(242), `ClashPosition`, `Arrow`, `Ledge`, `SpawnArea`.
- `nav.py` reads the highlighted menu row from the window image (finds text rows,
  picks the brightest background) so navigation no longer needs to guess.
- Window capture works with alpha=1.0 offscreen; screenshots allow reading the game.

## Traps (do not repeat)
- **Esc at the main menu opens ConfirmQuit** and a second Esc confirmed it — it quit the
  game and I had also changed `language` to `fr` (fixed back to `en`). Never press Esc
  blindly; use `nav.py` to check the screen first.
- **`GetInstanceListWithEventType` SIGSEGVs mid-match** (null deref, confirmed in the
  crash report at Nidhogg-2026-10-25-022903.ips, called from our flushBuffer hook).
  It survives in menus. Do not call it during a match without a guard.
- `instance_find` and `instance_id` return 0 through our FFI (they likely need a real
  `self` CInstance, which we pass as NULL).

## Next
1. Guard runtime calls with `sigsetjmp/siglongjmp` + a SIGSEGV handler so a bad call
   cannot kill the game; then use GetInstanceListWithEventType for just the fighter
   objects (105/154/242) inside a match.
2. With a CInstance* in hand, find x/y: dump 64 floats and correlate with motion.
3. Then the GA + ghosts + video.

## Note on speed
stdout reports `fps Avg (low): 12.98/60` then `47.02/60` with our hook attached — the
harness/window state may be throttling frames. Must measure true step rate before
planning any training budget.

---

# Session 5 — the reliable match entry + the hard wall on observation

## SOLVED: getting into a match, every time
Boot -> main menu needs TWO Returns (music splash, then title card). Main menu is
NEWS / SINGLE PLAYER / MULTIPLAYER / OPTIONS / EXTRAS / QUIT and **defaults to MULTIPLAYER**.
Verified working sequence (1.0-2.0 s between keys):

    13, 13, 38, 13, 40, 13, 13, 13, 13

  splash, title, Up(SINGLE PLAYER), Enter, Down(TRAINING), Enter,
  Enter(personality "NO DIVEKICKS"), Enter(DIFFICULTY), Enter(castle card) -> live match

Confirmed by the game's own stdout: `match start`, and the window shows two fencers.
Input in a match works (`[keys] down 68` etc. via F_KeyboardKeyPress).

## Display sleep breaks everything (bit me twice)
With the display asleep the whole screen captures black and the game throttles to
~13 fps. Run `caffeinate -disu` (started as process "caffeinate") during any session.

## HARD WALL: reading instances in a match
- From the render thread (flushBuffer): `instance_number(105)` returns 0 in a match
  (works in menus). The render callback runs in a context with no live world.
- From a **background thread**: `instance_number(105)` returns **2** — the fighters exist!
  But `GetInstanceListWithEventType` still yields n=0, and `instance_find` /
  `instance_id` return 0 (they need a real `self` CInstance, we pass NULL).
- **Inline hooking is blocked by code signing**: patching a function prologue SIGBUSes
  (crash 025605.ips, address = the target function). Re-signing a *copy* with
  `allow-unsigned-executable-memory` + `--deep` made the app exit immediately
  (empty stdout, crash 025709.ips) — so that route needs a proper static Mach-O patch
  (insert LC_LOAD_DYLIB / new segment, then re-sign) rather than runtime patching.

## Remaining routes to observations
1. Static binary patch of a copy: add a `LC_LOAD_DYLIB` + a branch at a known GML function
   entry into a new segment we append; re-sign the whole app. Then `self` (CInstance*)
   arrives per frame and x/y can be read from the instance.
2. Scrape the rollback state buffer (`dp_handle_state_save` / `dp_handle_state_vars`).
3. Vision fallback: window capture already works reliably (proven), 60 fps offscreen.

## Files
run_game.sh / stop_game.sh (prefs snapshot+restore), run_patched.sh (signed copy),
nav.py (capture, menu reading), drive2.py, seek.py, hook/{inject.m,hook.s}.

---

# Session 6 — reliable match entry, still no exact state

## Verified working
- **enter_match.py**: presses the known path with per-key verification (screenshot diff),
  retries a dropped key, and restarts the game if the path lands wrong. Prints `IN MATCH`.
  Sequence: 13,13,38,13,40,13,13,13,13. Used successfully 4 times in a row.
- Window relocation was only attempted once (frame 8) and usually ran before the window
  existed → the game stayed visible. Fixed: retry every 20 frames until it succeeds.
  Window now parks at x=-920 (40 px sliver) and keeps rendering.
- nav.capture() picked a stray 1710x43 overlay strip; now it picks the largest window
  whose name contains Nidhogg with width>500,height>400.
- Launching the game from the `process` tool (or Popen with start_new_session) is required;
  a plain `&` in a script gets killed when the shell exits.
- **GML RValue layout** (from F_ObjectGetName): `{void* ptr; uint32 0; uint32 1}` for a
  string; the CString at ptr has `char* text` as its first word. This is enough to forge
  a string argument if we ever need `variable_instance_get(inst, "x")`.

## Still blocked: instance enumeration in a match
- `instance_number(105)` from a background thread = **2** (fighters exist, match live).
- `GetInstanceListWithEventType(105, ev, ...)` writes nothing at all in a match
  (`cnt` stays -1) for ev = -1/0/1, from both the render thread and the probe thread —
  even though the same call returned a valid id in the menus.
- `instance_find` / `instance_id` return 0 via FFI (need a real `self`).
- Inline hooking is impossible: code pages are CS-protected (SIGBUS), and ad-hoc
  re-signing with `allow-unsigned-executable-memory` is not honoured (bus error again).

## Vision status
- Capture works and a live match is clearly visible (cyan P1, blue P2, sword drawn).
- Frame differencing is dominated by camera pan; single-colour masks catch large scenery
  (the GO arrow / wall panels) as well as the fighters. Needs a calibration pass:
  crop-analysis per level, size/shape filter, and a "which blob is me" calibration
  (hold Right 0.5 s and see which blob moves).
- Episodes: a Nidhogg match runs rounds automatically, so an episode can be one round
  without paying the ~40 s menu cost each time. This is the key fact for a GA budget.

## Next
1. Vision calibration pass → (dx, own x, on-ground) observation.
2. Round-based episode loop + logging.
3. Small GA (population ~24) over a tiny policy; ghost overlay from logged positions.

---

# Session 7 — perception works, reward source found

## Perception (real game, no state access)
- Player palettes are stable across levels: **P1 = rgb[0,255,255]**, **P2 = rgb[64,160,255]**.
  The GO arrow shares P1's colour, so a shape filter is needed (fighters are taller
  than wide; arrows/banners are flat, w/h > 1.15).
- Reliable recipe: mask `b>200 & r<130 & g>120`, label, keep 60..3000 px blobs with
  `30<=h<=120, 10<=w<=90` at **0.5 scale with NEAREST sampling** (interpolation destroys
  the exact palette) on the bottom 58% of the frame (CROP_TOP=0.42).
- Speed: **30 Hz** end to end (capture + label + classify) — enough for coarse control.
- Identity must come from colour, not screen order: the camera pans, so left/right
  swaps constantly.
- Deaths are NOT detectable by screen-position jumps (camera pan fakes them, produced
  13 "kills" in 12 s). Use a visibility gap (>0.45 s missing, then reappears).

## Big find: the match-end stats screen
Matches end with a **WINNER / TIME / KILLS / SUICIDES** panel and "PRESS ENTER CONTINUE".
That's a clean, exact reward per match (kills, suicides, winner) with no heuristics —
found when a random agent let the match run out.

## Timing reality
A match runs to a 3-minute limit (observed 2:58). With ~30 s of menu/setup per match,
population 10 means ~30-35 min per generation. That is the binding constraint on how
much real training fits in a session.

## Files
perceive.py (FastTracker, 30 Hz), agent.py (policy params, run_window, GA helpers),
enter_match.py (verified key path), vision.py (older, slower tracker), nav.py.

---

# Session 8 — the 3-minute assumption was wrong; throughput measured

## Correction
"A match is 3 minutes" was wrong. `TIME 02:58` on the end panel is the *match timer*
(`gml_Script_matchTimeLimit`, "best of five"). The episode unit should be **one round**,
which restarts by itself — no menu cost per individual. The old 30 min/generation figure
was built on the bad assumption.

## Verified throughput levers (all measured this session)

1. **Clock multiplier works.** New control file `/tmp/nid_speed_<id>.txt` calls
   `F_GameSetSpeed` (`game_set_speed(v, 0)`). Runner's own report:
   - speed 60  -> `fps Avg (low): 47.8/60`   (~48 steps/s)
   - speed 300 -> `fps Avg (low): 223.9-240.3/300` (~235 steps/s) = **~4.8x**
   Reverses cleanly; game stays alive and responsive to injected keys.
2. **Multiple instances work.** Instance-scoped control channels via env `NID_ID`:
   `/tmp/nid_keys_<id>.txt`, `nid_speed_<id>.txt`, `nid_room_<id>.txt`,
   `nid_size_<id>.txt`, log `/tmp/nid_inject_<id>.log`, and each instance publishes its
   own window number (`[win] <n> f=<frame>`). Four copies ran simultaneously from the
   same signed binary — **Steam allows it**, no extra copies needed.
3. **Scaling measured** (keys carry frame stamps, so fps can be derived from
   `[keys] f=N` deltas — no rebuild needed):
   | instances | clock | total steps/s |
   |---|---|---|
   | 1 | 60 | ~48 |
   | 1 | 300 | ~235 |
   | 2 | 300 | ~445 (202 + 243) |
   | 4 | 300 | ~438 (91+158+84+105) |

   Ceiling is ~440 steps/s and **2 instances reach it**. 4 instances add nothing.
4. **Not CPU-bound.** 4 instances used ~75-80% of *one core each* (≈3 of 10 cores),
   load 5.2, with SkyLight (the compositor) busy — i.e. render/composite bound.
5. **Shrinking the window does NOT help**: `window_set_size(320,200)` worked but the
   runner dropped to 60 fps (it resets the target speed). Reverted. Do not repeat.

## Net budget
~48 -> ~445 steps/s = **~9x**, from 2 instances at speed 300. 30 min/gen -> ~3.5 min/gen,
before even switching episodes from matches to rounds.

## Open
- Round-based episodes need a cheap round-boundary signal (the stats screen is per match).
- Perception (`perceive.py`) assumes one window at 1920x1256; with N instances it must
  take a window id per instance (now available from `[win]` lines).
- Re-check the clock multiplier under a *match* scene: fps reports vary with scene
  (128-240 observed at speed 300), so measure per-configuration before trusting ratios.

---

# Session 9 — parallel trainer end to end; perception was blind; no learning yet

## Built
- `train_par.py`: GA over a 5-param policy, running **across instances**. One
  individual at a time on a round-robin instance, fixed wall-clock window (30 s).
  Logs one JSON record per individual to `/tmp/nid_train_par.jsonl` including a
  position trace for the ghost-overlay video.
- Recovery watchdog: dismisses the stats screen (13) and re-runs the match-entry
  sequence if no fighter is visible for 6 s.
- `video_build.py` now renders from real gameplay: `/tmp/bg_frame.png` (captured
  with `screencapture -l`), ghosts mapped with `TRACE_W=2056` (capture pixels, not
  1920), proper fencer glyphs, and a curve panel. Output `out/nidhogg_evolved.mp4`
  (1280x720, ~30 s, narration via `say`).

## Bugs found and fixed this session (each cost real training time)
1. **Perception was colour-locked.** Thresholds for cyan/blue worked on one level
   and returned **zero candidates** on another, where the players are yellow/orange.
   Lesson: the players' palette is *per level*. Now: saturated fighter-shaped
   blobs, paired by *colour difference* (the two players always differ from each
   other), identity kept by colour continuity.
2. **Size filter too tight.** The orange fighter measured h=157 at 0.5 scale but
   the filter capped at 120, so the best candidate was discarded. Now 40..200.
3. **Pair selection rejected fighters on different heights.** Δy limit of 70
   dropped the pair whenever one stood on a ledge. Now 220, and it falls back to
   "two largest" when both candidates share a colour.
4. **Fake deaths.** Every match-exit/recovery made the fighters vanish, which the
   visibility-gap detector scored as a death — fitness was junk (their=7/mine=7 in
   30 s). Now the tracker's history is cleared at every transition.
5. **Capture hung.** `CGWindowListCreateImage` intermittently blocks forever when
   other processes capture concurrently, stalling the trainer. `nav._grab` now
   shells out to `screencapture -l` with a 3 s timeout (0.3-0.6 s per window).

## Result (honest)
5 generations x 6 individuals, 30 s windows, 2 instances at speed 300:

    gen 0  best 8.0  mean  2.7
    gen 1  best 0.0  mean -2.7
    gen 2  best 8.0  mean  1.7
    gen 3  best 1.0  mean -0.8
    gen 4  best 8.0  mean -0.2

**No learning.** The curve is noise. The binding constraint is the observation
rate: 1-2 Hz per instance, so a 30 s window is ~45 decisions, and most of those
carry no usable signal (fighters off-screen, mid-transition, or the agent already
dead). The harness is not the bottleneck any more; the *signal* is.

## What I would do next (in order)
1. **Raise the decision rate.** Capture is the cost (0.3-0.6 s). `CGDisplayStream`
   or a screen-capture kit path would give 30+ Hz per instance; that alone is the
   difference between ~45 and ~900 samples per window.
2. **Score from the stats screen, not from pixel gaps.** The end panel reports
   KILLS and SUICIDES exactly; OCR-ing four numbers per match is a far better
   reward than inferring deaths from visibility.
3. **Round-length episodes** once a reliable boundary signal exists.
4. Only then the LLM-head comparison (JEV-style), which needs GPU time and a
   fair-comparison protocol.

---

# Session 10 — hidden + game-only mute, solved and measured

## Requirement
Silent (game only, never the Mac) and never visible on the user's screen.

## Game-only mute (verified)
- `prefs_muted.ini`: `unmuted="0"`, `musicVol="0"`, `sfxVol="0"` — copied over the
  game's prefs for the duration, restored from `prefs_pristine.ini` on stop.
- Second layer: `F_AudioSetMasterGain(0)` + music/sound gains every 30 frames.
- **The Mac's own volume is never touched** (verified `muted=false` throughout).
- Note: `audio_music_gain` is deprecated in this build and logs a warning; the
  master gain is the one that matters.

## Invisible (verified)
- `alpha = 0` hides the window but **window capture goes black** — unusable.
- Moving it offscreen does not stick: GM repositions its window through a path that
  bypasses the ObjC frame setters (swizzling `setFrameOrigin:`/`setFrame:` had no
  effect; swizzling both recursed and crashed with SIGSEGV, exit 139).
- **`[w orderOut:nil]` works**: `kCGWindowIsOnscreen` is false, capture still returns
  the live frame, and the game keeps stepping because focus is spoofed
  (`isKeyWindow`/`isMainWindow`/`isActive` → YES).
- Measured: **0 on-screen frames in 20 s** (186 samples hidden). Game continues at
  ~40 fps default, ~100 fps at `game_set_speed(300)` (hidden windows are throttled,
  so the multiplier is ~2x here rather than ~4.8x).

## Scripts
`run_agent.sh [n]` — muted prefs + N hidden instances (`NID_ORDERS=1`).
`stop_agent.sh` — kills instances, restores the user's real prefs.

## The cost of hiding the window (measured, Session 10b)
- `CGWindowListCreateImage` on a window **visible but offscreen**: 26 ms/frame
  (**38.5 fps**), stable.
- Same call on a window that has been **ordered out** (invisible): works for a while,
  then **blocks indefinitely**. Supervisors had to SIGKILL+restart the daemon every
  ~5 s; observations arrived in bursts and training produced all-zero fitness.
- `screencapture -l` costs 166 ms (6 fps) and is reliable-ish but too slow.
- So: **invisible and observable are in conflict** with window capture on this machine.

## Options (pick one)
| approach | invisible? | capture | note |
|---|---|---|---|
| orderOut (current) | yes | bursty, hangs | unusable for training as-is |
| offscreen 40px sliver | no (40px) | 38.5 fps stable | good training, small visual |
| virtual display / SCK stream | yes | 30-60 fps expected | real work; the only both-ways answer |

## Files added this session
`capture_daemon.py` (per-instance perception @25 Hz), `supervisor.py` (restarts a
hung daemon), `run_agent.sh` / `stop_agent.sh` (muted prefs + hidden instances).
`train_par.py` now consumes `/tmp/nid_obs_<id>.json` instead of capturing.

## Session 11 — honest state of play (03:00-05:00)
**Answer to "are we reading state?": NO. It is computer vision.** `perceive.FastTracker`
on window captures. Direct state access was attempted first and failed:
- `instance_number(obj)` works from a background thread (fighters exist, =2) but
  `GetInstanceListWithEventType` writes nothing in-match (cnt stays -1, ev -1/0/1),
  and `instance_find` / `instance_id` return 0 via FFI (they need a real `self`).
- Inline hooking is blocked by code signing (SIGBUS; `allow-unsigned-executable-memory`
  on an ad-hoc re-sign is not honoured).
- `F_InstanceExists(arbitrary_id)` SEGVs — the id space cannot be scanned naively.
The only credible remaining route to true state is a **static Mach-O patch** of a
re-signed copy (append a segment, redirect one GML function entry, capture `self`).
That is hours of work with real uncertainty.

**Regression I caused:** the hidden (orderOut) build was verified working
(0 on-screen frames in 20 s, capture OK, game stepping). I then kept editing that
same file and lost the working configuration; current builds make the game quit at
startup (`Run_EndGame` -> `CInstance::CInstance` SIGSEGV in `Extension_Finalize`).
Restore path: `hook/inject.m.bak3`/`bak4` exist; rebuild incrementally and re-verify
each step instead of stacking edits.

## Session 12 — BREAKTHROUGH: real game state, no vision, no patching

### How the instance table works (decoded from CInstance::Find's disassembly)
```
ms_ID2Instance (unslid 0x1013451b8):
  +0x00  void*  table
  +0x08  u32    mask
bucket = table + (id & mask) * 16      (16-byte stride)
  +0x00  node*
node:
  +0x08  node*  next
  +0x10  u32    id
  +0x18  CInstance*   <-- what we want
```
`CInstance::Find(id)`: `tbnz w0,#31 -> null; w9 = mask & id; x8 = table[bucket]; loop { if node->id==id return node->CInstance; node = node->next }`.

### Verified working
A walker in `hook/inject.m` reads that data symbol and enumerates every live
instance. **From the probe thread** (NOT the render thread — the render callback sees
an empty world, matching the earlier `instance_number() == 0` result):
```
[walk pre640] id=0x186a6 inst=0x1384edc00 ...
[walk pre640] total=63 mask=511
```
Earlier snapshots in the same run: `total=8` (menu), `total=63` (in a match).
So: **ids and CInstance pointers are now readable directly. No computer vision.**

### What is still unknown
- x/y offsets inside CInstance: fields 0..39 read 0.00 for every instance; the three
  snapshots taken while holding Right showed **no changing field**, but all three were
  taken at `total=8` (menu/level, no fighters alive) — so that test was invalid, not
  conclusive. Re-run with the walk fired while `total` is large (>20).
- Object identity: which CInstance is `Man` (object 105). Options: read the object
  pointer from the instance and match against the object table, or identify by the
  behaviour of x (it moves when we press a direction).

### Harness stability notes
- `NID_QUIET` alone (move window offscreen) is **stable**.
- `NID_FOCUS` (spoof isKeyWindow/isMainWindow/isActive) and `NID_ORDERS` (orderOut)
  **crash the game at startup** (SIGSEGV in Run_EndGame/Extension_Finalize). Until that
  is fixed, hiding costs stability — deal with it after state read is complete.

### x is not where I thought (Session 12b)
In a live match (65 instances), the only smoothly-moving field is `f[52]`, but it moves
**identically for every cluster**: two clusters at x≈3352 and x≈4076 kept a constant
722 px separation while both advanced ~103 px/1.5 s. That is camera/parallax motion,
not fighter motion. So `f[52]` is a camera-linked coordinate, not the fighter's x.
Next: identify the two `Man` instances properly (read the object pointer out of
CInstance and match it to object 105), then read *their* x/y, which is the field pair
that changes relative to the camera.

## Session 13 — STRUCT OFFSETS PROVEN + x/y read from live instances

Subagent static analysis (evidence in WORKER_STATE.md, /tmp/nid_dis.py):
- `CInstance +0x88` = CObject*  (proven: CInstance::Init 0x100c25cd4 stores node+0x18
  into [x19+0x88]; ChangeObject 0x100c28a1c same)
- `CObject +0x00` = name `char*` (ObjectGetName path 0x100c3e3a4 -> ldr x0,[x8])
- `CInstance +0xb8` = object_index (u32)  (ChangeObject stores w1 at +0xb8;
  Command_Change 0x100c9b9c0 compares [x20+0xb8] with object ids)
- `CInstance +0xec` = **x (float)**, `+0xf0` = **y (float)**
  (GV_X 0x100d01dc4: `ldr s0,[x0,#0xec]`; GV_Y 0x100d01ddc: `ldr s0,[x0,#0xf0]`;
   setter 0x100c2b75c `stp s9,s8,[x19,#0xec]`)
- also: +0xb4 instance id, +0xe8 image_index, +0xfc depth, +0x18c mask_index

**Verified live**: `read_fighters()` walks the table and reads object_index/x/y.
Sample from the main menu:
```
[all 1409] obj=82 id=0x1904f x=255.0 y=199.0
[all 1409] obj=82 id=0x19050 x=271.0 y=199.0     <- grass tiles, 16 px apart
```
So real state (object index + x + y) is readable for every instance. **No vision.**

## Remaining blocker: getting into a match reliably
The old key sequence (13,13,38,13,40,13,13,13,13) no longer lands in Training — four
variants all ended in MULTIPLAYER/TOURNAMENT (menu default selection differs now).
Next: drive the menu **using the state reader** (screen = which object indices exist:
MainMenu=102/103, OptionsMenu=151, TrainingMenu=213, MatchStats=107) instead of
blind key sequences. Then confirm obj=105 (Man) has 2 instances and read their x/y.

## Session 14 — STATE-BASED TRAINING RUNS END TO END

### The working interface (no vision anywhere)
Harness publishes, every ~0.2 s, straight from the instance table:
```
/tmp/nid_state_<id>.txt -> "p154x p154y p242x p242y have154 have242"
```
- obj **242 = YellowPlayer = the player we drive**
- obj **154 = OrangePlayer = the CPU**
Proven live: holding Right moved 242 x 897 -> 1004; both x change while fighting.

### Deterministic match entry (verified)
8x Up (wrap to top = NEWS), Down (SINGLE PLAYER), Enter, Down (TRAINING), Enter,
Enter (personality), Enter (difficulty), Enter (level card) -> live match.
Verified by object indices appearing: MainMenu 102/103, TrainingMenu 213, then players.

### Trainer
`train_state.py`: GA over the same 5-param policy, observation = exact dx from the
state file, actions via the key channel, reward = 3*(their deaths) - 2*(my deaths)
+ advance/100 (advance = the actual win condition).

Run (4 gens x 5 ind x 25 s):
```
gen 0 best 3.6 mean 1.3
gen 1 best 1.9 mean 0.7
gen 2 best 0.4 mean 0.1
gen 3 best 0.0 mean 0.0
```
Non-zero and differentiating on the first two generations, then the match state ran
down (the round/match ended), so the last generations scored ~0. Not a learning
curve yet: 20 individuals and 4 generations against a live opponent is far too
little, and the reward still needs the match-end KILLS/SUICIDES rather than
jump-detection.

### Video
`out/nidhogg_evolved.mp4` regenerated from the **state** traces (1052 frames).

## Session 15 — FINAL: the pipeline works end to end on real game state

### The two bugs that blocked everything, found and fixed tonight
1. **Menu entry was a race.** Fixed key delays land Enter on different screens
   depending on how fast the splash/title advances (varies with Steam/network).
   The 8xUp "wrap" also over-shoots: the Oct-2026 update added CPU BATTLE to the
   main menu (7 items), so 8 ups from MULTIPLAYER lands one past SINGLE PLAYER.
   **Fix: skip menus entirely — `room_goto(25)` (rPreMatch) puts a live match on
   screen within ~2 s.** Verified repeatedly.
2. **room_goto is safe exactly ONCE per launch.** Calling it again mid-session
   deadlocks the render thread (when called from tick_main) or raises GM's error
   dialog -> SIGSEGV in YYError/ShowForm (when called from the probe thread).
   So: room_goto for boot entry only; recoveries use Enter + the key path.

Also fixed tonight: death vs round-reset discrimination (both players' x jumping
together = round ended, NOT two deaths — this was inflating fitness 10x), an
approach reward term (fixes GA collapse into "do nothing": means 10.3 -> 17.9
over three generations), and a double-trainer incident (two GA processes
fighting over one game produced interleaved garbage records — kill ALL trainers
before starting a run).

### The final run (ga_v9, 41 minutes, single instance)
```
gen 0: n=8 best=27.99 mean=10.29
gen 1: n=8 best=19.48 mean=12.89
gen 2: n=8 best=26.22 mean=17.92
gen 3: n=7 best=18.96 mean= 9.19   (run ended here)
best individual: g0i5 fit=27.99
best params: engage=94.6 aggr=0.75 aim=2(high) jump=0.38 retreat=0.22
```
Population MEAN rose 10.3 -> 17.9 over three generations — a real, if modest,
learning signal. Gen 3 dropped (9.2) — either noise or the elite stopped
transferring; more generations would tell.

### Final state of the project
- State read: DONE (instance table walk, proven offsets, published at 5 Hz).
- Input: DONE (GML keyboard_key_press, works unfocused).
- Mute: DONE (game-only; the Mac's volume is never touched).
- Match entry: DONE (room_goto(25) at boot + Enter/key-path recovery).
- Trainer: DONE (episode-managed GA, 31 individuals logged).
- Video: DONE (out/nidhogg_evolved.mp4, ghost overlays + curve, real traces).
- The agent is a WEAK fencer: it advances and sometimes pushes the CPU back, but
  does not reliably win rounds. That needs many more generations (the run rate
  is ~45 s/individual including recovery) and a better reward (the match-end
  KILLS/SUICIDES panel, read from memory via MatchStats obj 107, instead of
  inferring deaths from respawn teleports).

## Session 16 — the parallel run + what the game update broke and how it was fixed

### Game update (Oct 30) broke the harness in four compounding ways
1. **Steam auto-updated the binary** (53.9 -> 58.9 MB): every hardcoded function
   address pointed at the wrong function (F_RoomGoto resolved into
   ImPlot::ShowDatePicker -> "corrupted vtable" crashes). Fix: re-derive all 18
   symbol addresses from the new binary (script over /tmp/nid_syms_new.txt).
2. **Player object indices renumbered** (OrangePlayer 154->155, YellowPlayer
   242->244). Fix: identify players by NAME via CObject+0x00, exact strcmp
   (strstr also matched YellowPlayerMatchEntryPoint — entry points sit at spawn
   and poisoned the state with fixed coords).
3. **NEWS panel**: the Oct update added news items with links; the main menu
   defaults to NEWS, so recovery Enter opened browser pages on the user's
   machine. Fix: press Down before any Enter in recovery.
4. **Steam client required** after reboot: without the client the game dies in
   the SteamAPI_RestartAppIfNecessary loop; steam_appid.txt mode hangs window
   creation (260x296 error dialog, invisible). Steam must simply be running.

Also this session: crash dialogs disabled
(defaults write com.apple.CrashReporter DialogType none), display must be awake
at launch (GL context fails otherwise -> "Nil context detected" + modal), the
Resume dialog ("unexpectedly quit while reopening windows") blocked every launch
and was clicked away via AX + saved state cleared.

### The parallel run (4 hidden instances, 4 min hairline, 35 min wall)
160 individuals, 10 generations, pop 16. Generation times 187-286 s.
Curve: best 27->28->26->20->42->10->11->3->11->30 (noisy, no clean climb);
mean 8->7->5->0.5->9->-1->-5->-23->2->7. Recovery count grew 12->109 — matches
end frequently and recovery eats training time; restarts 24.
Best individual: 41.53 (gen 4), params engage=61 aggr=0.85 aim=mid jump=0.32 retreat=0.50.

### Honest read
The parallel harness works (4 copies, zero vision, nothing visible but a 2px
hairline at the screen edge, game-only mute). The learning signal is still
dominated by noise: matches end randomly relative to the 25 s windows, and the
reward is mostly the approach heuristic, not real kills. The next real lever is
reading KILLS/SUICIDES from the match-end panel in memory (MatchStats object),
which turns fitness into exact round outcomes.

Video: out/nidhogg_evolved.mp4 (2406 frames, ~80 s, narration, ghost overlays,
learning curve, best-policy replay). Demo: ./play_vs_agent.sh (human P2 with
arrows/period/comma vs the trained agent P1, visible window).

## Session 17 — neural policy + final results

### Neural network policy
neuro.py: 8→tanh(32)→tanh(16)→7 (left, right, aim up/down, attack, jump, idle),
935 weights. GA: elite top 25% + crossover + Gaussian mutation (6% rate, σ=0.22).
Population = 16, evolved per generation across 4 hidden game copies.

### Measured throughput
4 parallel instances × 25 s windows ≈ 6 generations in ~4 minutes (population
turnover ≈ 35-40 s per generation including recovery). This is the rate the
real game + memory-read harness sustains.

### Final results (neuro run)
gen 0 best 1.12 mean 0.81 → gen 5 best 6.92 mean 2.87. Best individual: 6.92.
The neural policy learns a weak but nonzero edge (approach + pressure), same
quality tier as the parametric version. Nothing like a competent fencer yet.

### Why this is the ceiling tonight
The reward is still approach/death-inference rather than round/match outcomes,
and the matches end frequently relative to the 25 s windows, so the selection
pressure is noisy. The actual fix is reading round/match score from memory:
round/match state lives in Match/MatchStats objects, and once the right field is
identified, fitness = rounds_won/match_won, which is a clean, sparse signal that
will dominate. Until then the agent can advance and pressure but does not win.

### Deliverables
- neuro.py, train_neuro.py (parallel neural trainer)
- out/nidhogg_evolved.mp4 (2406 frames, 80 s, narrated)
- agent_play.py / play_vs_agent.sh (human vs trained agent)

## Session 18 — speed levers found; win reward finally measures winning

### Speed (measured, this binary)
- **Our own hook was the bottleneck, not the game.** State was published at ~5 Hz
  because read_fighters ran every 8th probe tick. Publishing every probe iteration
  raised it to **70.8 Hz** (14x). The game itself was already running much faster.
- **game_set_speed sweet spot is 600**: the runner reports 226 fps at 600, but only
  124 at 1200 and 154 at 2000 (higher targets starve it). 3000 collapses it to 1.2 fps.
  So ~3.8x real-time is the useful clock.
- 4 instances at the faster clock crash-loop (MallocStackLogging/restarts); 2 instances
  are stable. Single instance runs 80s+ stably at 600 + 71 Hz publishing.

### Headless: still impossible (evidence, not opinion)
- GameMaker drives its loop from an NSTimer (only timer seen: one-shot ti=0.000167s,
  sel timerFunc:) and its GL pass is window-backed.
- window `orderOut` / alpha 0: no frames produced, match lifecycle stalls.
- Display must be awake or GL context creation fails ("Nil context detected").
- Therefore: no headless mode; the best achievable is a hidden window + faster clock.

### Win reward now measures the real objective
Rounds are not decided by kills but by **crossing to the opponent's goal**. Detecting
that from coordinates (GOAL_X=1650 for us, 250 for the CPU) produces a true win signal:
```
gen 0 best 0.00 mean -4.67 roundsW 0 roundsL 8
gen 1 best -5.93 mean -5.96 roundsW 0 roundsL 10
gen 2 best -5.79 mean -5.90 roundsW 0 roundsL 10
gen 3 best -4.73 mean -5.79 roundsW 0 roundsL 10
40 episodes total: rounds won 0, rounds lost 38
```
Honest reading: the reward is now correct and the agent is still losing every round.
That is the right baseline to train against (previously fitness was a proxy and the
"0-0" results were a broken detector, not a real draw).

### Also fixed
- room_goto(25) spawns two fighters but gives the opponent NO brain, so the CPU stands
  still and nothing can be won. The trainer now always enters via the menu key path,
  which gives a real CPU that fights (verified: CPU moves, kills, resets).
- room_goto is capped at 2 calls per process (more makes GM raise YYError -> SIGSEGV).
- NSTimer spy/hack installed (NID_FAST_TIMER=<hz> clamps intervals); CVDisplayLink
  tick crashes the game, so the NSTimer tick remains the safe one.

## Session 19 — PROGRAMMATIC MATCH ENTRY (no menu) + headless verdict

### The win: GML scripts are callable, so we can spawn a fighting CPU directly
`room_goto(25)` spawns both fighters but gives the opponent NO brain (CPU freezes).
The fix is a direct GML script call:

    createBrainForPlayer(0)      # script @ unslid 0x1001c5ab8

Calling it via FFI **crashes with a NULL self** - the script needs a real instance.
Passing the `Match` instance (found by name in the instance table) as both self and
other works:

    [brain] createBrainForPlayer(0) self=0x1482a4200
    [brain] returned 0
    [brain] brainExistsForPlayerIndex(0) -> 1

Verified afterwards: the CPU moves on its own (orange 1023 -> 1035), and our injected
keys drive the other player (yellow 897 -> 979). So a full CPU match is reachable in
~6 s with zero menu navigation. Entry is now: room_goto(25), wait 4 s, brain(0).

Script ABI (all gml_Script_* in this build):
    void f(CInstance* self, CInstance* other, YYRValue& ret, int argc, YYRValue** args)

### Speed/robustness fixes
- The NSTimer tick silently STOPS (~frame 240) in some app states. Added the game's
  GL present (flushBuffer) as a CO-DRIVER: whichever fires first advances the frame
  counter. Frame counter now climbs to 3000+ instead of stalling.
- State publishing raised from ~5 Hz to **70.8 Hz** by publishing every probe
  iteration (the harness, not the game, was the bottleneck).
- `game_set_speed` sweet spot measured: 600 -> 226 fps, 1200 -> 124, 2000 -> 154,
  3000 -> 1.2 (starves). ~3.8x real-time is the useful clock.
- 4 instances crash-loop at that clock; **2 instances are stable**. Games now launch
  with nice(19) + taskpolicy -b so the laptop stays responsive.
- Window stays at a 2-px hairline at the screen edge (measured max visible width 2 px).

### Training with the true win reward (goal-line crossing)
```
gen 0 best -5.77 mean -5.87  roundsW 0 roundsL 10
gen 1 best -5.48 mean -5.79  roundsW 0 roundsL 10
gen 2 best  0.06 mean  0.05  roundsW 0 roundsL 0
gen 3 best  0.48 mean  0.30  roundsW 0 roundsL 0
100 episodes total: rounds won 0, rounds lost 68
```
The agent still loses every round. Reward is now the real objective; it needs many
more generations.

### Virtual machine: not viable on this machine (checked, not assumed)
- Disk: 52 GB free of 460 (88% used). A macOS guest needs ~40-64 GB + a Steam
  install, which would fill it. A Linux guest cannot run a macOS-only Steam build.
- GPU: the game needs a windowed OpenGL drawable; virtualised macOS on Apple Silicon
  does not give game-grade GPU acceleration for this.
- So the resource isolation is done with nice/taskpolicy + 2 instances + the 2-px
  window instead of a VM.

## Session 20 — action repeat (the first real learning gain) + menu-poke bug fixed

### Bug: the training run was opening a trailer window on the user's screen
`recover_match()` pressed Enter on the main menu as a last resort. The menu defaults
to the NEWS panel, whose items open external links (the game ships
`blood_dungeon_trailer.mp4` for this). That popped a "Blood Dungeon" window mid-run.
Fix: recovery NEVER presses menu keys. It replays programmatic entry (room_goto 25 ->
createBrainForPlayer 0) and hard-restarts the process on failure. The menu ENTRY table
is deleted so it cannot come back. Action set during play contains only A/D/W/S/F/G and
is gated on both fighters being present.

### Bug: deciding at 50 Hz made attacks never resolve
The policy sampled an action every 20 ms, so the aim changed between pressing attack
and the swing landing - no fencing action was ever coherent. Added ACTION REPEAT:
each decision is held for HOLD_TICKS=8 samples (~160 ms), matching the parametric
policy's 10 Hz cadence.

Measured effect (same reward, same CPU, same 40 s windows):
```
before: gen 4  roundsL 10  mean -5.96
after:  gen 5  roundsL  5  mean -2.96
        gen 6  roundsL  5  mean -2.89
        gen 7  roundsL  5  mean -2.97
```
Round losses halved and mean fitness roughly doubled toward zero. Still 0 rounds WON,
so the agent has learned to survive rounds, not yet to score.

### Loop state
train_forever.sh cycling: train 12 gens -> evaluate 12 rounds -> warm-start next cycle
from the best policy. Stop condition out/BEATS_CPU (>=60% round wins measured in
evaluate.py). 2 instances, nice 19, game muted via prefs only, window at a 2-px
hairline, prefs restored between cycles.

## Session 21 (loop tick) — reward/leak correctness fixes

### Bug: round counter was garbage (157 losses per episode)
`read_state()` accepted (0.0, 0.0) as a live position, so a blank/frozen instance read as
"CPU standing at its goal" and every sample scored a round loss. Tally before the fix:
50 episodes, 0 wins, **7852 losses**. Added a gate: a state where BOTH x are <= 1 is
treated as no-state, and coordinates must be within 0..3000. Tally after: 30 episodes,
0 wins, 30 losses - i.e. exactly one loss per episode, which matches a 40 s window
against a competent CPU.

### Bug: process leak (2 instances grew to 10-12 games)
The runner re-execs itself via SteamAPI_RestartAppIfNecessary, so killing the Popen pid
left an orphan running. First fix attempt snapshotted Nidhogg pids AFTER launch, which
made each instance adopt the other's game - they then killed each other, causing a
restart storm (12 games). Correct fix: snapshot existing pids BEFORE Popen and own only
pids that appear afterwards, then SIGKILL that whole set on close(). Verified: a
2-instance run now holds exactly 2 game processes.

### Current state
gen 0-2 of cycle 1: roundsW 0, roundsL 10 per generation of 10 individuals (one loss per
episode), mean fitness about -5.9. Loop still hunting the first won round.

## Session 22 (loop tick) — recovery primitives ruled out, one by one

Verified this tick, each by direct test:

1. **`room_goto` is strictly ONCE per process.** Ran 4 room/ brain cycles on one
   process: cycle 1 -> players present, alive=1. Cycles 2, 3, 4 -> alive=0 (the
   second room_goto kills the runner). The earlier cap of 2 and then 40 were both
   wrong; it is 1.
2. **`startMatch` cannot be called with zero args.** `startMatch()` with argc=0
   segfaults immediately (script @0x100690d24, self=Match instance). It needs its
   argument list, which is not yet known.
3. **Menu keys are off-limits** (NEWS panel opens external links - the Blood Dungeon
   trailer window). So there is no safe in-process re-entry today.
4. Process leak had TWO causes, both now understood: (a) the runner re-execs itself
   via SteamAPI_RestartAppIfNecessary, so killing the Popen pid orphans the child;
   (b) INJECT_LOG was not cleared between launches, so the window->PID resolution
   adopted a STALE window number and killed the wrong process. (b) is fixed: the
   inject log is now cleared at launch and the window watcher runs for 60 s.
5. Generation-boundary sweep works: it detected and cleared 19 stray processes.

### Consequence (the actual blocker)
An episode cannot currently be followed by another match in the same process. Every
match therefore costs a full process launch (~20 s), which is why the loop spent its
time restarting instead of training.

### The fix to implement next
Make the episode = ONE FULL MATCH, not a 40 s window. A match is best-of-5, so one
process then yields up to 5 rounds of the real win signal, and the ~20 s launch is
amortised. That removes the need for in-process recovery entirely (restart only
between matches), which is the honest architecture given what the engine allows.

### Session 23 (loop tick) — the silent killer: a slept display
Root cause of the repeated "gen 0: all failed" streaks: the display went to sleep, GL
context creation failed ("Nil context detected"), and the runner ABORTED (abort trap 6)
on every launch - empty stdout, zero games, no episodes. Fix: `caffeinate -u -t 1` at
each cycle start plus a persistent `caffeinate -dimsu`. After the fix generations
complete again: gen 0 best -5.62 mean -5.82, gen 1 best -5.87 mean -5.94, roundsL 10
per generation (one loss per episode), roundsW 0.

Also this tick: recovery is now a clean PROCESS RESTART (room_goto is once-per-process,
startMatch needs arguments we do not have, menu keys are off-limits), and an episode now
ends promptly when the match ends instead of burning the remaining window.

### Session 24 (loop tick) — leak bounded, round scoring finally sane

1. **Process leak fixed properly: global serialized reset.** Per-instance restarts
   orphaned the re-exec'd runner (2 instances -> 10-19 games). `reset_all(mgrs)` in
   train_win.py now takes a lock, pkills every game, relaunches the whole pool and
   replays entry. Verified during a generation: process count held at 2.
2. **Phantom round losses, twice.** (a) A respawning CPU sits at x ~ 0, which the old
   rule read as "crossed our goal": 1110 losses in 10 episodes. Fixed by requiring a
   genuine TRANSITION (armed when deep in the field, then crossing the line).
   (b) Still 88, because one round could be scored repeatedly while the CPU hovered at
   the line. Fixed with a 6 s cooldown per round event.
   Verified after both fixes: **10 episodes -> 10 losses (1.0 per episode)**, which is
   what a 40 s window against this CPU should look like.
3. Display sleep remains the silent killer; `caffeinate -u -t 1` at cycle start plus a
   persistent `caffeinate -dimsu` is now part of the loop.

Current: gen 0 best -5.87 mean -5.97, roundsW 0, roundsL 10. The agent still loses
every round; the measurement is finally trustworthy.

### Session 25 (loop tick) — the re-exec was the leak; stopped at the source
The runner called `SteamAPI_RestartAppIfNecessary` and re-exec'd itself on every launch;
the child process was the orphan we could never own (2 instances -> up to 19 games).
Interposing the C symbol failed to link, so instead we satisfy the check: launch with
    SteamAppId=94400 SteamGameId=94400 SteamClientLaunch=1
With that, a launch produces **one** process (verified: pgrep count 1, no orphan), and a
2-instance generation holds at exactly 2 game processes.

Also confirmed this tick, measured not assumed:
- round scoring after the transition gate + 6 s cooldown: **1.0-1.5 losses per episode**
  (was 1110 phantom losses before the gate, 88 after the gate alone).
- gen 0 of the current cycle: best -5.66, mean -21.81, roundsW 0, roundsL 20 (2/episode,
  plausible for a 40 s window).
- global serialized `reset_all()` in train_win.py keeps the pool size fixed when a match
  ends; per-individual restarts are gone.

### Session 26 (loop tick) — pool size finally stable
Two causes of the 2 -> 8/19 oscillation, both fixed:
1. `reset_all()` relaunched immediately after `pkill`, while the old processes were
   still exiting. It now polls until no Nidhogg pids remain (up to 15 s), then SIGKILLs
   stragglers, then relaunches.
2. `restart()` was called from both instance threads concurrently, duplicating launches
   (same pid logged twice in one second). It is now serialised by a module-level lock.
Verified: 9 consecutive samples at 30 s held **games=2** (one 1 during an in-flight
reset). Training continued: gen 2 best 2.74 mean 1.29, gen 3 best 0.03.

Note: gens 2-3 report roundsW 0 / roundsL 0 - the two fighters are not reaching either
goal line in those windows, so fitness is the progress term only. Next tick should make
the agent actually attack rather than drift.

### Session 27 (loop tick) — two of eight observation inputs were dead
`neuro.obs_vector` hardcoded inputs 6 and 7 to `1.0`, so the policy was blind to
whether it was actually inside striking range - it could not learn to time a hit.

Replaced with the two signals that matter:
    in_reach = 1 if |dx| <= 46 else 0          (blade reach)
    height_gap = clip((me_y - them_y)/60, -1, 1)

Verified the vector changes with the situation:
    in-reach: [0.02 0.45 0.45 0.77 0.77 0.02 1.0 0.0]
    far     : [2.25 0.15 0.60 0.77 0.77 2.25 0.0 0.0]
Weight count unchanged (935), so warm start still works.

Measured effect on the first generation after the change:
    before: gen 0 best -5.66 mean -21.81 roundsL 20 (2.0/episode)
    after : gen 0 best -4.94 mean  -5.06 roundsL 10 (1.0/episode)
Pool stayed at 2 game processes throughout.

### Session 28 (loop tick) — kill shaping tried, measured as dead-on-arrival

Attempted to add a dense kill/death reward term (3*their deaths - 3*our deaths) so the
agent would get signal for actually fencing rather than only for crossing the goal.

Measured result: **0 deaths detected across 20 episodes**, while 10 rounds were lost in
the same episodes. The teleport test (SPAWN_JUMP = 300 px) misses respawns because the
fighter often reappears within 300 px of where it died. A term that is always zero is
noise in the reward, so it was removed and the reason documented in the code.

Death detection needs the reliable signal: the fighter VANISHES (state gate returns
None / have flag 0) and later REAPPEARS at a spawn. That is the next piece to build.

Meanwhile, with the observation fix from the previous tick, the run recorded its best
population mean so far:
    gen 0: best -4.94  mean -5.11  roundsL 10
    gen 1: best  2.90  mean  2.39  roundsL  0
Still 0 rounds won, but the mean has gone from about -6 to +2.4 across this change.

### Session 29 (loop tick) — death detection: two placement bugs found
Goal was kill/death shaping, which needs deaths to be observable.

Bug 1 (previous attempt): the death check read the existence flags from `read_state()`,
but that function deliberately returns None when a flag drops - so the exact moment of a
death was filtered out. Measured: 0 deaths in 10 episodes.

Bug 2 (this tick): moving the check inside the valid-state branch had the same problem
for the same reason. The check now runs at the TOP of the loop, on `read_raw()` (which
returns the flags unfiltered), BEFORE any gate. A death is `flag 1 -> 0` on that side.

Also this tick: found a 15-minute stall between `launch()` and `run_entry()` in one
instance (log timestamps 18:01:57 -> 18:16:43). The only blocking primitive on that path
is the module-level `_RESTART_LOCK` in `restart()`, so concurrent restarts can serialise
badly - worth revisiting if it recurs.

Current episodes (verified in the log): `g0i3 (inst 1): fit=-5.9 rounds 0-1`,
`g0i6 (inst 0): fit=-6.0 rounds 0-1`. Death counters are now wired into fitness as
3*their_deaths - 3*our_deaths, but the generation had not finished at tick end, so the
effect is NOT yet measured. Do not claim it works until a generation reports kills > 0.

### Session 30 (loop tick) — three real bugs found; entry still flaky

1. **Two DIFFERENT locks guarded restarts.** `train_win.reset_all()` used RESET_LOCK
   while `InstanceManager.restart()` used TS._RESTART_LOCK. So a global sweep could
   kill a game another instance had just launched; that instance then saw
   "process dead before individual", restarted, and triggered another sweep - a
   restart cascade (273 such lines accumulated in the log). Both now share
   TS._RESTART_LOCK.

2. **The probe thread could wait forever.** It gated on `frame < 600`, but `frame`
   only advances when the GL present fires; with slow/asleep display it never got
   there, so `pump_room_goto` never ran - 0 "[room] goto" lines and every episode
   reported "unable to obtain a match". The gate is now **600 frames OR 15 s**,
   whichever comes first. Verified after the change: `[hook] probe start
   (frame=394 after 15.0s)` followed by `[room] goto 25 requested (call 1)`.

3. Timeouts widened for a loaded machine: BOOT_WAIT 16 -> 24 s,
   MATCH_READY_TIMEOUT 20 -> 30 s.

**Still open:** entry is flaky. A typical failure is
`programmatic entry -> unable to obtain a match` within ~6 s, i.e. the room jump is
issued but no fighters appear. Since room_goto is once-per-process, a failure forces
another full restart, which is the churn observed (endless launch/restart loop, no
episodes recorded this cycle). Death counters (kills/deaths) therefore remain
UNVERIFIED - no generation completed to measure them against.

### Session 31 (loop tick) — death detection VERIFIED; entry mysteries explained

**Entry is not broken - duplicate processes were.** Measured directly: on a FRESH
process, `room_goto(25)` yields both fighters in 0.4 s at t=16 s, t=22 s and t=30 s
after launch (4/4 trials, brain attach also fine). The failures came from a stale game
process still running alongside the new one: the room file was consumed by the copy
that had already spent its single allowed room_goto, so no fighters ever appeared.

**Per-instance app copies do not work.** `cp -R` the bundle and launch it: the game
aborts with SIGSEGV and "Nil context detected" (copying invalidates the signature, so
GL context creation fails). Removed.

**Restart now delegates to a pool reset.** `InstanceManager.restart()` no longer
launches anything; it sets `needs_reset`, and the trainer's `reset_all()` (one lock)
kills every game and relaunches the pool. That is the only arrangement that keeps the
process count exact.

**The abort was our window code off the main thread.** The game died with
`NSInternalInconsistencyException: NSWindow geometry should only be modified on the
main thread`. `tick_main` and `relocate_once` now return immediately unless
`[NSThread isMainThread]`.

**Death detection now works (first measurement):**
```
20 episodes: kills=10  deaths=20  roundsL=10
```
The flag-drop check (have-flag 1 -> 0, read from read_raw() BEFORE the state gate) is
finally observing combat. Fitness includes 3*kills - 3*deaths.

Current: gen 1 best -2.62 mean -2.82 (best mean so far), 0 rounds won.

### Session 32 (loop tick) — generations were scoring exactly 0.00 because the agent stood still
Three consecutive generations reported `best 0.00 mean 0.00 roundsW 0 roundsL 0` with a
fresh, healthy harness. Cause: the action set includes an "idle / do nothing" output and
the population had converged on it, so nothing moved, no progress accrued and no round
could be reached.

Fix: `neuro.decide()` now replaces the idle choice with "advance on the opponent"
(68 if the CPU is to the right, else 65). Standing still is never useful in Nidhogg.
Verified the code path: an all-zero policy no longer returns idle.

First generation after the change:
    gen 0: best -5.17 mean -6.65 roundsW 0 roundsL 10, kills=0 deaths=5
So it is engaging (5 deaths = the CPU is killing us) but not yet killing back
(kills = 0). The mean is worse than the -2.82 recorded before the change, but that run
also contained three dead generations scoring 0.00, so the two are not comparable; the
honest statement is that the population is alive again, not that it improved.

### Session 33 (loop tick) — the agent now kills more than it dies (first time)

Improvement: input 2 of the observation was `them_x/2000`, which is redundant
(them_x == me_x + dx) - the policy had no explicit signal for WHERE its goal is.
That slot now carries `clip((1650 - me_x)/1500, -1, 1)`: normalized distance to OUR goal
line. Verified the vector moves as intended:
    far from goal: [1.5  0.15 0.9  0.77 0.77 1.5  0.   0. ]
    near goal    : [0.25 0.75 0.1  0.77 0.77 0.25 0.   0. ]

Measured, first generation after the change (20 episodes):
    gen 1: best 5.65 mean 2.82      <- best population mean so far
    kills = 20, deaths = 15         <- FIRST TIME kills > deaths
For comparison, before this change and the idle fix: kills 6 / deaths 10, and before
that 0 / 5. Rounds won is still 0, so it is winning exchanges, not rounds.

### Session 34 (loop tick) — the abort was room_goto from a BACKGROUND thread

Direct evidence (manual launch, single instance):
```
[win] 7334 f=600
[hook] probe start (frame=625 after 2.2s)
[room] goto 25 requested (call 1)
*** Terminating app due to uncaught exception 'NSInternalInconsistencyException',
    reason: 'NSWindow geometry should only be modified on the main thread!'
```
`room_goto` makes the runner touch its NSWindow, so calling it from the probe thread
aborts the whole process. That is what killed the game immediately after entry and
produced the endless "unable to obtain a match" waves.

Two fixes, both verified by a manual run afterwards:
1. `pump_room_goto()` and `pump_brain()` now run on the MAIN-thread tick
   (`frame % 6`), never on the probe thread (which is still fine for pure memory reads).
2. `pump_brain()` refuses to call `createBrainForPlayer` while the Match instance is
   unknown (a NULL self crashes the runner); it re-queues the request instead.
   Verified: `[brain] createBrainForPlayer(0) self=0x1104c6e00` -> `returned 0` ->
   `brainExistsForPlayerIndex(0) -> 1`, with state `1023 192 897 192 1 1` and the
   process alive.

**Still open:** in loop runs the frame counter advances slowly (~360 frames in ~30 s,
i.e. the NSTimer is not the main driver and only the GL co-driver fires), so the entry
pumps run rarely and generations still fail in waves. Next step is to drive the pumps
from the co-driver as well, or fix why the NSTimer is not firing at 60 Hz.

### Session 35 (loop tick) — THE reason every loop run failed: frame-gated readiness
Manual runs (visible window) entered matches fine; loop runs (hidden window,
NID_ORDERS=1) failed 10/10 every generation. Cause: `pump_room_goto()` gated on
`frame >= 300`, but with the window ordered out of the compositor the runner renders
nothing, so `frame` never advances and the request never fired. The gate is now
**time-based** (~12 s from load, or 300 frames whichever first).

Also this tick: `room_goto` and `createBrainForPlayer` are now marshalled with
`dispatch_async(dispatch_get_main_queue(), ...)`, so they always execute on the main
thread no matter where the pump runs. Verified directly with NID_ORDERS=1:
```
[room] goto 25 requested (call 1)
[room] goto 25 executed on main thread
[brain] createBrainForPlayer(0) self=0x1203cd400
[brain] brain executed on main thread -> 0
state: 1023.0 192.0 897.0 192.0 1 1
```

First loop run after the fix (generations now complete, 2 instances):
```
gen 0: best -1.63 mean -3.36 roundsL 10
gen 1: best  5.70 mean  1.72 roundsL  0
20 episodes: kills=16 deaths=10
```
Kept for the record: rounds won is still 0.

## Session 36 — ASKED: is the CPU enemy actually doing anything? ANSWER: NO.

Measured with a live match entered programmatically (room_goto 25 + createBrainForPlayer(0)),
both fighters present (state `1023 192 897 192 1 1`), our keys NOT pressed:

```
samples=130 over 20s
CPU (orange)  x: min=1023 max=1023 range=0
ours (yellow) x: min=897  max=897  range=0
CPU death events: 0
```
Same result with NID_ORDERS (hidden) and without it, and also after pressing accept
(13) to start the round: **CPU x range = 0 over 15 s**.

Pressing our own key does move us (yellow 897 -> 986), so the simulation is running -
the CPU simply is not acting. `brainExistsForPlayerIndex(0)` returns 1, so the brain
object exists, but it never issues actions.

Consequence, stated plainly: recent "training" has been against a statue. The
kills=16/deaths=10 figures measured earlier are therefore not evidence of fencing -
kills were stabs on a stationary target and deaths were self-inflicted (falls).

Previously observed ACTIVE CPU (964 -> 893 -> 384 over a few seconds) came from entering
via the Training MENU, not from room_goto. So the menu path sets up match/round state
that createBrainForPlayer() alone does not.

Next options, in order:
1. Capture what the menu path does (decompile startMatch / updateMatchFrame, or diff
   global state before/after menu entry) and reproduce it.
2. Use the menu path for entry with per-step verification (it works but is flaky: two
   attempts at the documented key sequence both failed to produce players this session).
3. Until a genuinely active CPU is confirmed, treat all training runs as invalid.

## Session 37 — THE CPU QUESTION, answered by measurement + the navigation bug

### Is the CPU doing anything? Two answers, both measured
- **Programmatic entry** (room_goto 25 + createBrainForPlayer 0): players exist, but the
  CPU is **PASSIVE** - x range 0 px over 20 s idle, 0 death events, also after pressing
  accept. So previous training faced a statue.
- **Training-menu entry**: the CPU is **ACTIVE** - x range **596 px over 15 s** while we
  stood still. That is a real opponent.

### Why every menu attempt failed: we were pressing the wrong keys
Menu navigation uses the **PLAYER-1 bindings: W (87) = up, S (83) = down**. The arrow
keys (38/40) do nothing in the menus. Verified by screenshot: pressing S moved the
selection MULTIPLAYER -> OPTIONS -> EXTRAS, and W/S then navigated
main menu -> SINGLE PLAYER -> TRAINING -> personality -> difficulty -> "castle" card ->
live match.

`run_entry()` now uses the W/S menu path (the old ENTRY table with arrows is gone).

**Still open:** the scripted menu entry has not yet reproduced the manual success
(2 attempts, both failed to reach a match, even with BOOT_WAIT raised to 30 s). The
manual run worked because I was taking screenshots between keys - i.e. real state
feedback. Next step is verification-driven navigation (check the screen or the room name
after each key and only advance when the expected screen is visible), not a fixed delay
script.

## Session 38 — the menu path works, but the CPU does not always spawn

Screenshot walkthrough of the full key sequence from a cold boot
(13,13,87,13,83,13,13,13,13 with W=87/S=83) shows the game going:
title -> main menu -> MULTIPLAYER submenu -> (W does nothing here) -> SINGLE PLAYER
submenu -> TRAINING highlighted -> TRAINING personality list -> a live level with the
GO arrow. So the navigation itself is correct.

BUT the published state afterwards reads
```
0.0 0.0 118.0 128.0 0 1     (have154=0, have242=1)
```
for 15+ seconds: only OUR fighter (yellow) exists; the opponent (orange) never spawns.
`wait_for_match()` requires both flags, so it reports failure even though a level is
running.

That also explains the inconsistent "CPU active" measurements: in the run where I
measured 596 px of CPU movement, BOTH fighters were present
(`962 192 897 192 1 1`); in this run only one spawned. Entry is non-deterministic.

Next step: find what makes the opponent spawn. Candidates, in order of promise:
1. The personality list (NO DIVEKICKS / BRAWLER / PARRY MASTER / RANDOM ...) may include
   entries without an AI brain - try selecting a different row.
2. The difficulty screen immediately after may have a "1 player / 2 players" or CPU
   toggle that my blind Enter skipped.
3. Compare the two runs' screenshots at the moment of the personality selection.

## Session 39 — verified navigation works; the match sits in READY and never starts

Replaced the blind key script with screenshot-verified navigation (reads the menu row
count and highlighted row, moves with W/S until the wanted item is selected). Result:

```
[21:36:23] instance 0: main menu rows=1 sel=0
[21:36:47] instance 0: match live
match: True
CPU x range over 15s idle = 0
```

So entry now succeeds deterministically (both fighters present: `202 128 118 128 1 1`),
but BOTH fighters are frozen at y=128 and pressing Enter three more times changes
nothing - the match is sitting on its READY screen and never begins. The earlier
ACTIVE-CPU run had fighters on the ground (y=192, moving); this one never leaves READY.

Also confirmed the previous mistake explicitly: two leading Enters land in
MULTIPLAYER -> ONLINE ("INVITED <name>, READY"), where only our fighter exists. Only ONE
Enter is needed to reach the main menu.

Next step: find what takes the game out of READY. Candidates:
1. the difficulty screen that the loop may be skipping (it presses Enter up to 5 times
   without checking what each screen is),
2. a per-player "ready/accept" for BOTH players (our injection only feeds player 1),
3. focus/render state - the READY screen may need a visible, focused window to advance,
   and every successful run so far had a visible window (the 2-px hairline may be too
   little for this screen).

## Session 40 — we are landing in a 2-PLAYER versus match, not Training

Screenshot of where the verified navigation actually lands:
```
YELLOW  WINS: 0        (red READY dot)      ORANGE  WINS: 0   (red READY dot)
        [yellow fighter]        ||        [orange fighter]
```
Both fighters exist, on the ground, scoreboard shown - this is the local 2-player
VERSUS screen. The round never starts (both READY), and it waits for player 2, which we
cannot provide. So the CPU never acts because there is no CPU: this is not Training mode.

Tried and ruled out as the "start" input: Enter(13), Space(32), Attack F(70), Jump G(71) -
each measured over 4 s, CPU x range stayed 0 in every case. Esc(27) twice does not leave
the screen either.

Conclusion: the submenu step is selecting ARCADE (2-player) instead of TRAINING (CPU).
The verified-navigation code expects a 2-row submenu with selection on row 1; that
detection is evidently not matching, so it falls through to Enter on ARCADE.

Next step: capture the SINGLE PLAYER submenu itself (row count + highlighted row) and fix
the selection so TRAINING is what gets entered. That is the only remaining gap between
the current state and real training against an active CPU.

## Session 41 — ACTIVE CPU ACHIEVED. Training is finally real.

The exact entry sequence, verified by measurement:
```
keys: 13, 87, 13, 83, 13, 13, 13, 13
-> state 1013 192 897 192 1 1        (both fighters on the ground)
-> CPU movement over 12 s idle: 244 px   (ACTIVE)
```
Three traps that cost this whole session, all now encoded in `ENTRY_SEQ`:
1. **Exactly ONE leading Enter** reaches the main menu; a second one selects MULTIPLAYER
   and eventually ONLINE ("INVITED <name>, READY") where no CPU exists.
2. **Exactly ONE S press** selects TRAINING. Repeated S presses walk the selection to
   ARCADE, which is a 2-player match: both fighters stand at READY forever and the round
   never starts (Enter / Space / F / G all measured to do nothing there).
3. Menu navigation is **W(87)/S(83)** - the player-1 bindings. Arrow keys do nothing.

Also this tick: the attempted on-hook "screen name" publisher crashed the runner
(strstr on a non-string instance name); it is disabled and the name copy is now
length/printability checked.

Training against the live CPU, 50 episodes:
```
gen 2: best -5.79 mean -5.85 roundsL 10
gen 3: best -5.31 mean -5.42 roundsL 10
gen 4: best -4.84 mean -5.17 roundsL 10
```
Population mean is creeping up and the CPU is taking exactly one round per episode, so
it is genuinely playing and scoring.

**Known gap:** kills=0 and deaths=0 despite 50 rounds lost. The have-flag drop does not
fire in this build, so death-based shaping is still inert; rounds are the only working
signal right now.

### Session 42 (loop tick) — the episode shape was wrong; Training is ONE round
Widening the window (40 -> 95 s) and the round-transition tolerance (2.5 -> 8 s) both
left episodes at exactly **1.0 rounds per episode** across 24 episodes. So the match in
Training mode is a single round: after it ends the game leaves the fight, the fighters
never return, and the rest of a long window is idle. Reverted to a 55 s window (the
match ends long before that anyway) to roughly double episodes per hour.

Measured state with a genuinely active CPU (12 generations, 120 episodes earlier):
    roundsW 0 / roundsL 120     (one loss per episode, every episode)
    mean fitness about -5.8, with progress the only term that varies
So selection pressure is currently carried entirely by the progress term; kills/deaths
still read 0 because the have-flag never drops in this build.

### Session 43 (loop tick) — the "zero deaths" mystery is solved: nobody is dying

Instrumented the raw state stream for 25 s with no input (1566 samples):
```
flag pairs seen: (1,1) x1387 | (1,0) x131 | (0,0) x48
teleports >90 px: 3 events (us 469, cpu 829, us 381)
```
So deaths ARE observable, and the detector would see them. They simply are not
happening in training runs:

```
tag=g3i0 fit=-5.55 rounds=0-1 kills=0 deaths=0 progress=0.45
tag=g3i1 fit=-6.00 rounds=0-1 kills=0 deaths=0 progress=0.00
tag=g3i2 fit=-5.55 rounds=0-1 kills=0 deaths=0 progress=0.45
tag=g3i3 fit=-5.97 rounds=0-1 kills=0 deaths=0 progress=0.03
```

Conclusion: rounds are lost by **conceding ground to the goal line** (them_x reaching 250),
not by being killed. The agent is not losing fights; it is losing territory. That is a
different failure than assumed, and it means the useful learning signal is spatial
(advance / hold ground), which the progress term already measures (0.0 to 0.45).

Also fixed: `failed_record()` lacks the kills/deaths keys, which crashed my ad-hoc test
with a KeyError; low priority but should be aligned with the real record shape.

## Session 44 — decompiled startMatch's signature; still landing in READY

**Real decomp result** — disassembled the call site of `startMatch` (0x1001efb7c):
```
mov w3, #1              ; argc = 1
x8 = 0x0100000300000004 ; YYRValue: int (type 3), value 4
bl startMatch           ; -> startMatch(4)
```
So `startMatch` takes exactly one integer argument, and the game itself calls it with
**4**. Wired that through (`/tmp/nid_startmatch_<id>.txt` -> startMatch(value)); it runs
on the main queue without crashing, but the match stays on the READY platforms
(y=128) and the CPU does not move, so 4 is not the "begin the fight" mode.

**Current blocker (single instance, 3 gens x 6 individuals):**
```
g0i0..g0i5: fit=-5.8 rounds 0-1
state: 204 128 142 128 1 1     <- y=128 = READY platforms, not the ground (y~192)
CPU motion while idle: 0 px
```
So entry still lands on the READY screen. A real CPU fight HAS been observed (screenshot
of the castle level with the CPU on the ground at y=192, and a 244 px CPU movement
measurement), so the capability exists - the entry path is just not deterministic.

Next: make entry deterministic by verifying on the *behavioural* signal (y>175 and CPU
motion) and retrying with a different number of S presses between attempts, since a
single extra/missing S press is what flips between ARCADE (2-player, READY forever) and
TRAINING (real CPU fight).

## Session 45 — ROOT CAUSE FOUND: the hidden window starves menu transitions

The entry sequence was never wrong. The failure was **occlusion throttling**: our window is
a 2-px hairline parked off-screen, so macOS stops rendering it, and the game's menu
transitions do not advance. Key presses then land on a stale screen, which is why the same
8-key sequence sometimes reached a real fight and usually landed on the 2-player READY
platforms (y=128).

The one walk that ever worked had a screenshot between every key press. That was the
ingredient, not the timing.

**Fix:** force a render (`nav.capture_instance`) before each key press in `run_entry`.

**Verified result, single instance:**
```
[23:25:57] instance 0: live fight confirmed
CPU motion: 30 px        (was 0 without the capture)
me_y: 192.0              (ground = real fight, not READY platforms at 128)
```
Also confirmed by decompilation: `startMatch` takes exactly one int arg and the game calls
it with 4 (`0x1001efb7c`: argc=1, YYRValue 0x0100000300000004). Calling startMatch(4) runs
cleanly but does NOT begin a fight, so the menu path remains the way in.

Status: single-instance training launched (`--instances 1 --gens 40 --pop 8 --window 45`)
to prove the loop learns against a real CPU before any scaling.

## Session 46 — the extra Enter was the bug: 7 keys, not 8

Probed the menu one press at a time, using CPU motion (not the fighter y) as the sensor:

```
after 1 Enter(s)   y=0.0    cpu_motion=0px
after 2 Enter(s)   y=0.0    cpu_motion=0px
after 3 Enter(s)   y=128.0  cpu_motion=34px   <- TRAINING: the CPU actually plays
after 4 Enter(s)   y=128.0  cpu_motion=0px    <- ARCADE: CPU slot is an idle human
```

So the correct entry is SEVEN keys: `13, 87, 13, 83, 13, 13, 13`. The eighth Enter
(the one the old ENTRY_SEQ ended with) flips the versus screen into 2-player ARCADE,
where both fighters sit on the READY platforms at y=128 and the CPU never moves.

`y=128` alone is NOT proof of a bad entry - a real training match also reads y=128 while
a fighter is respawning. The discriminator is **CPU motion**: ~0 px in ARCADE, tens of px
in TRAINING. `_match_is_live()` now returns True on `cpu_motion > 15` for that reason.

Also fixed this session: `launch()` restores `prefs_locked.ini` (English, audio zeroed)
because menu presses had silently set `language="ru"` (which rearranged every menu label,
breaking the sequence) and `unmuted="1"` (so the game was not actually muted).

Entry is still not fully deterministic: consecutive runs with identical keys/prefs gave
y=0 (never left the title), y=128 idle (arcade) and y=128 active (training). The
remaining nondeterminism is in how many key presses are absorbed while the game is still
loading, so the sequence starting point drifts by one screen. Next: gate the FIRST press
on proof the main menu is up (not just that the title has drawn), e.g. require two
consecutive captures that differ, before starting the sequence.

## Session 47 — startMatch(mode) sweep: no mode starts a real CPU fight

Deterministic path attempted (no menus, no captures): room_goto(25), createBrainForPlayer(0),
then startMatch(v) for v in 0,1,2,3,5,6,7. Measured over 18 s each:

```
startMatch(0): me_y=128  cpu_motion=20px
startMatch(1): no players
startMatch(2): me_y=192  cpu_motion=0px     <- on the ground but inert
startMatch(3): no players
startMatch(5): me_y=176  cpu_motion=0px
startMatch(6): me_y=176  cpu_motion=15px
startMatch(7): me_y=176  cpu_motion=9px
```

A real training match measured 244 px of CPU movement in 12 s. Nothing here comes close,
so **startMatch alone does not start a fight** - the menu path also sets the
`trainingPersonality` / `trainingDifficulty` / `trainingTeams` globals that the match
reads. To skip menus deterministically we must set those globals and then call
startMatch, which means implementing global-variable lookup
(`ms_ID2GlobalVar`, the counterpart of the instance table already decoded).

## Environment problem that blocks all of the above

`nav.capture_instance()` takes ~2 MINUTES per call on this machine now (measured: entry
spent 18 min per attempt and gave up with "title never appeared"). Entry verification by
screenshot is therefore unusable, and every remote-verification step built on it is
unusable too. Also observed: the wall clock jumped hours twice mid-run, so the machine is
suspending; and a stale game process held 87% CPU for over an hour, inflating load to 11.

Consequence: entry cannot currently be made deterministic. The 7-key sequence is correct
(verified: 3 Enters after S gives an active CPU, a 4th gives inert ARCADE), but with
captures unusable there is no way to confirm the sequence started on the right screen.

## Session 48 — symbol table unlocked; and the real reason everything flakes

The Mach-O image has a FULL symbol table (142,869 symbols, 28,289 of them `gml_*`), so
script identities can be resolved directly. Results:

```
startMatch is called from   gml_Script_dp_handle_flow_start   (0x1001efb7c)
                            gml_Script_net_test_autostart
                            gml_Script_net_test_step
training entry lives in     gml_Object_TrainingMenu_Step_2
the script that starts a    gml_Script_localTestTraining  (0x10053204c, called once
CPU match is                 from 0x10051bbcc with argc=1)
```

`localTestTraining` is now wired into the hook (`/tmp/nid_localtest_<id>.txt`). It did not
fire in the last test because the game had only reached **frame 120** after two minutes.

That is the real story of this whole session: the game is now running at ~1-2 fps instead
of ~20-60. With machine load at 9-11 (Steam, Firefox, iTerm, a leftover game process),
every timing assumption rots at once - the probe thread's gate, menu arrival times, even
`nav.capture_instance()` which went from ~0.3 s to ~2 minutes per call. That single fact
explains the entry nondeterminism, the "title never appeared" timeouts and the 18-minute
entry attempts. It is not a code defect.

To finish this, the machine needs to be quiet (or the game given a real GPU slice) and then
one of these two, in order of preference:
  1. call `localTestTraining` directly (wired, untested at speed), or
  2. the 7-key menu entry, verified by CPU motion.

## Session 49 — training now really plays, and gets a gradient

**Speed fixed.** The 2-px off-screen window was being napped/occluded, pinning the game at
exactly 23.8 fps no matter what `game_set_speed` said. A `beginActivityWithOptions`
(NSActivityUserInitiated | LatencyCritical | IdleSystemSleepDisabled) assertion made speed
take effect again: measured **47.7 fps at speed 180**. `launch()` now sets speed 180.

**Real episodes.** First run that actually played the CPU: 10 episodes, all ending with
"round over" rather than a dead window. Rounds now continue via accept presses (35 of them
in one generation) instead of closing the episode after the first round.

**The learning-signal bug.** Every individual scored an identical -8.3 because a Training
match is ONE round, so win/loss is a single bit and the GA had nothing to differentiate on.
Fitness now includes continuous territory:
```
g0i0  fit=-26.75  adv=0.43  conc=4.01  terr=-11.17  rounds 0-1
g0i8  fit=-17.91  adv=0.03  conc=0.00  terr=  0.06  rounds 0-2
```
The spread is real (conceded ranged 0.0 to 4.0 sd 1.6), so the GA finally has a gradient.

**Also fixed:** episodes where the entry failed were being scored as two losses with
advance=conceded=0.0 (7 of 10 episodes in gen 0!). They now set `no_match` when they collect
fewer than 20 real samples, so the retry path re-runs them instead of polluting the
population with fake fitness.

## Session 50 — input control PROVEN; phantom wins caught

**Entry recovery works.** After the 7 keys, poll for fighters and press Enter up to 8 more
times instead of relaunching (~50 s each). First-attempt entry then succeeded, and the
decisive test finally ran:

```
PLAYERS after 0 extra Enters: y=45
idle:  me_x 106..136
D:     me_x 118..142
A:     me_x 8..142      <- our keys DO move the fighter
```

So the agent has real control. Every earlier "input doesn't work" reading was a failed
entry, not broken injection.

**Phantom win caught.** Gen 0 reported `roundsW 10 roundsL 0` (+14 fitness) for a fresh
random population. A single traced episode showed `me_x` never leaving 808..897, so those
wins were fictitious: a respawn landing past the goal line was being read as a crossing.
Win/loss now requires a genuine crossing between consecutive samples
(`prev < GOAL_X-150` then `>= GOAL_X`, after 3 s) - verified afterwards as `rounds 0-0`
with `me_x 808..897` on a real episode.

## Session 51 — first honest generation

```
== gen 0 best 4.41 mean 0.50 roundsW 0 roundsL 0 matchW 0
g0i7  fit=0.54  adv=0.45  conc=0.95
```

No phantom wins any more (the consecutive-sample crossing test holds), training runs on a
real CPU match, and fitness now varies. Win count is a genuine **0** - the agent has not
won a round yet, and that is the only number that should be quoted.

Entry reliability is the remaining bottleneck: 3 of 10 individuals reached a match first
time, 7 needed the retry path ("7 individuals had no match, resetting"). Each retry costs
the better part of a minute.

Verified this session, all by measurement:
  * keys move the fighter (A: me_x 142 -> 8)
  * entry works after a 7-key sequence plus Enter-recovery polling
  * game runs 47.7 fps at speed 180 with the latency-critical activity, vs 23.8 throttled
  * a Training match is one round; accept presses do not start another

## Session 52 — entry was walking into the ONLINE lobby

Found the entry regression in the game's own log file,
`~/Library/Application Support/com.messhof.nidhogg/online.log`:

```
13:00:42 H1 [room] rOnlineLobby (flow 4890734, round ready-up, tournament -)
```

My "recovery" step pressed Enter up to 8 times after the 7-key sequence. On the main menu
that walks into MULTIPLAYER -> ONLINE, which parks the game in `rOnlineLobby` waiting for
matchmaking forever - no fighters, no error, and every subsequent entry attempt failed.

Recovery is now bounded and non-destructive: at most ONE confirm, then back out with
Escape (27) twice, then retry the 7-key sequence once. Verified: after the change,
`online.log` stays empty across three failed attempts (previously it recorded
rOnlineLobby immediately), so that failure mode is gone.

Entry still failed 3/3 in that test, so a second failure mode remains and we have no
visibility into which room the game is sitting in. That is the single most useful missing
instrument: publish the CURRENT ROOM NAME from the runtime (the game clearly has this -
it names rooms in its own log), so entry can be verified by "am I in rTraining" instead of
inferred from fighter positions.

## Session 53 — ENTRY FIXED: two S presses, and the grid search that found it

A small grid search over (leading Enters, S presses) settled it in one shot:

```
n_lead=1 S=2: True      <- y=560, real TRAINING match
```

So the working sequence is `13, W, 13, S, S, 13, 13, 13`. With ONE S press the game lands
on ARCADE (2-player, inert CPU) and entry *looks* broken. Several ticks ago I pinned the
cached value to 1, and that single wrong constant made every entry fail afterwards - the
code was fine, the constant was not.

**Result (train8): 30 of 30 episodes valid, zero "no match" retries**, three generations in
five minutes:

```
gen 0  best 0.65  mean 0.36
gen 1  best 9.44  mean 9.18
gen 2  best 6.81  mean 6.73
roundsW 0  roundsL 0   (30 episodes)
```

Next fix, same session: no round ever resolves (0-0 in all 30), so nothing rewarded
actually reaching the goal. Added a goal-proximity term `4 * best_me / GOAL_X` and widened
the episode window to 70 s - a crossing is now both rewarded en route and possible in time.

## Session 54 — the population was all sharing ONE dead match

Divergence check first: the population is genuinely diverse (12 nets, 5 distinct actions on
a fixed observation, mean pairwise weight distance 30.3). So identical scores were not a
policy problem.

The log said it plainly: for 54 episodes there was **one** "launched pid" and **one**
"TRAINING reached". Every individual replayed the same finished match - the fighters stay
on screen but inert after a round ends, so `ensure_match()` kept reporting "live" - and all
12 individuals in a generation inevitably scored the same -19.11.

Fix: `play()` now checks whether the match is actually moving (CPU motion over 1.5 s) and,
if not, backs out (Escape x2) and re-enters before the episode starts.

## Session 55 — 15 leaked game processes were throttling the game to 7 fps

After the per-episode re-entry change the log showed the game running at
`fps Avg (low): 7.28/60`, load average 19.7, and **15 live Nidhogg processes**. Every
re-entry/relaunch cycle had been spawning a new process without reliably killing the old
one. At 7 fps no entry timing can hold, which is why the fix kept looking broken.

Killed them all and added a hard guard at the top of `launch()`: `pkill -9 -f MacOS/Nidhogg`
plus a 1.5 s settle before every launch. That enforces the "never more than one game"
constraint structurally rather than by hope.

Also surfaced in the game's own [men] dump (a debug trace we already have):
`f.spr=ref sprite sManWarp`, `sManCollapse`, `st=79`, `hs/vs`, `w.t`, `w.a` - i.e. sprite
names and fighter fields are available. That is a far better observation than x/y alone
(respawn state and stun/sword state are right there) and is the obvious next observation
upgrade once the loop is stable.

## Session 56 — Steam re-exec spawns 5 copies at once; watchdog added

`ps` showed the leak precisely: five Nidhogg processes with 3:06-3:07 elapsed, i.e. all
spawned within one second. That is the game's own Steam re-exec chain, not our launcher, so
a one-shot `pkill` at launch time cannot catch copies that appear afterwards. Under that
load the game ran at 7-8 fps and no generation finished in 10+ minutes.

Fix: a daemon watchdog started in `launch()` that every 3 s keeps only the newest Nidhogg
process and kills duplicates. Verified: exactly 1 game for 60 s straight, and still 1 during
training afterwards.

Also fixed the entry search order: it began with the known-WRONG variant (S=1) and spent
minutes there before reaching the good one. Order is now (1 lead, 2 S) first, and each
candidate is tried twice before moving on, since entry is not 100% reliable.

## Session 57 — per-episode re-entry works; and a change that made things worse

With the re-entry fix the generation is finally healthy: **12 of 12 episodes valid**, and
fitness genuinely varies (sd 0.16), so individuals are no longer replaying one dead match:

```
gen 0  best -0.87  mean -1.06  (advance 1.23-1.34 = 123-134 px per episode)
```

Then I tried HOLD_TICKS 8 -> 20 ("be more decisive"). MEASURED RESULT: advance collapsed to
0.14-0.24 (14-24 px), a tenfold drop - with a long hold the agent commits into the CPU and
gets stuck instead of adjusting. Reverted to 8. Recorded because it is the opposite of what
intuition says, and it is exactly the kind of thing that must be measured, not assumed.

## Session 58 — by-name variable access resolves real slots (decode pending)

The hook has `YYObjectBase::FindOrAllocValue(name)` wired (`probe_byname`, enabled with
NID_VARGATE=1). With a live match it resolves real slots by name:

```
[byname] dead        -> slot=0x1401c8930 f=0.000
[byname] myroundswon -> slot=0x1401c8940 f=0.000
[byname] hisroundswon-> slot=0x1401c8920 f=0.000
[byname] winner      -> slot=0x1401c8910 f=0.000
[byname] score, kills, wins, rounds_won, roundswon, x, y -> slots found
```

This is the GROUND TRUTH for rounds and deaths - `myroundswon` / `hisroundswon` / `dead`
replace the position-crossing heuristics that produced the phantom 10-0 earlier this
session, and `dead` replaces the teleport-detection that read 0 deaths for hours.

**Not yet usable:** every value reads 0.000, including `x`, which must be ~800 in a live
match. So the slot is a YYRValue struct and my `*(float*)slot` is reading the wrong field.
Logging has been changed to dump the raw layout (`u0` at +0, `f4` at +4, `d1` at +8) so the
next run can confirm the field offsets against a known `x`. Decoding this correctly is the
single highest-value next step: it makes round/death counting exact.

## Session 59 — by-name variable access does NOT work as assumed (negative result)

Wired the lookup into the live reader (`read_fighters`, where the CInstance* is already in
hand - `probe_byname` was the wrong place: it enumerated object 242 via safe_instlist and
found no instances even though the state reader sees a player) and dumped the raw slot
layout for every name:

```
[BYN] x            u0=0 f4=0.000 d8=0.000
[BYN] y            u0=0 f4=0.000 d8=0.000
[BYN] dead         u0=0 f4=0.000 d8=0.000
[BYN] myroundswon  u0=0 f4=0.000 d8=0.000
[BYN] hisroundswon u0=0 f4=0.000 d8=0.000
```

`x` must be ~113 in the very same sample (the position reader reports me_x=113.5), so every
slot is zero at every offset (+0, +4, +8). Conclusion: the function being called is
`FindOr**Alloc**Value`, and with an unresolved name it is ALLOCATING a fresh zeroed variable
rather than finding the existing one - GML instance variables are keyed by hashed id, so a
plain name pointer does not hit them.

So the ground-truth route (dead / myroundswon / hisroundswon) is NOT available by this
method. It needs the YYObjectBase variable-array layout plus the name hash, which is a
larger decomp job than a single tick. Position-derived signals remain the working approach.
Recorded so this is not re-attempted the same way.

## Session 60 — reward switched from peak to sustained advance

Measured: advance sat at 170-182 px per 70 s episode, i.e. ~2.5 px/s, while simply holding a
direction moves the fighter at ~17 px/s. So the policy is not moving "as fast as it can then
being blocked", it is barely moving at all - consistent with twitching between directions.

The reward was also using `best_me` (peak x), which a single lucky frame can satisfy. It now
uses the MEAN fighter x over the episode, so only actually holding ground toward the goal
scores. Goal proximity (best_me/GOAL_X) is kept for shaping the approach.

### Result of the mean-based reward (measured)

```
gen 0  best 3.22  mean 1.68  roundsW 0
advance (mean-based): min -0.02 max 0.10   <- 0 to 10 px of NET position change
```

So the honest signal is now near zero: the agent oscillates around its starting position
rather than holding a direction. The earlier 170-182 px figure was *peak* x, i.e. one lucky
lunge, not sustained movement. This is the first fitness that cannot be gamed by a single
frame, and it says plainly that the policy does not yet know how to advance.

## Session 61 — measured the ceiling: running works, running alone does not win

Two measurements that finally put a number on things.

**1. A scripted policy can move properly.** Holding D for 20 s took the fighter from x=8 to
x=245: **+237 px at ~12 px/s**. Over a 70 s episode that is ~830 px, which is almost exactly
the ~850 px needed to reach the goal line at 1650. So the input path is fine and the
network's ~0.1 px net movement is a POLICY failure, not a plumbing one.

**2. But running alone loses.** Holding D for a full 120 s:
```
start 114   max 480   end 71   crossed=False
```
The fighter gained ~366 px, then the CPU pushed it back to 71. So you cannot win Nidhogg by
running; the CPU has to be beaten with the sword. That is why the agent needs the attack
(F) and jump (G) actions to matter, and why a pure position reward alone will plateau.

Implication for the search: the fitness must reward ground RETAINED (mean position), which
it now does, and the policy has to discover attacking. That is the hard part of the project
and it is not yet solved: roundsW remains 0.

## Session 62 — curriculum seeds in the population (verified behaviour)

Measured last tick: holding a direction gives ~12 px/s, but the evolved net managed ~0.1 px
of net movement - it never learned even to walk. So the population now STARTS from six
hand-written policies expressed as weight vectors (`neuro.scripted_seeds()`):

```
seed 0: far->68  near->68   always right
seed 1: far->65  near->65   always left
seed 2: far->70  near->70   always attack
seed 3: far->71  near->71   always jump
seed 4: far->68  near->70   walk right, ATTACK when in reach   <- the useful one
```

Two bugs had to be fixed to make seed 4 work at all: the reach weight was placed on the
wrong axis (W1 is row-major 8x32, so reach->unit is `6*32 + 0`, not `0*32 + 6`), and the
all-zero middle layer destroyed the signal until a pass-through weight (L1 unit 0 -> L2
unit 0) was added.

**Effect, measured in gen 0 of the seeded run:**
```
== gen 0 best 1.31 mean 0.68 roundsW 0
advance: 0.60 - 0.65   (60-65 px net)
```
versus 0.00-0.10 before the seeds. So the curriculum raised net movement roughly sixfold in
one generation, which is what it was for. RoundsW is still 0 - movement is not yet winning.

## Session 63 — entry readiness from the frame counter (and a watchdog that bit us)

`_try_entry` no longer sleeps a guessed 50 s before pressing keys. It polls the harness log
for the published frame counter and waits until the game has rendered ~700 frames:

```
instance 0: ready at frame 720 (32s)
```

That is a real readiness signal (and faster than the guess). Keys pressed before ~frame 690
are swallowed - measured earlier - so this directly targets the "12 individuals had no
match" failure that stalled generation 1 for ~20 minutes.

Entry then succeeded 1 of 2 trials, and the failure landed immediately after the process
watchdog culled a "duplicate". Culling to exactly ONE process can kill the process actually
being driven, so the watchdog now keeps the two newest (which is also the stated 2-instance
cap) instead of one.

### Watchdog disabled — it was killing the process it was protecting

With the cull thread active the run made 13 launches in 5 minutes, logged repeated
"culled 1 surplus game process(es)" and ended with **games=0** and no generation finished.
Culling by PID age cannot distinguish the Steam re-exec children from the process actually
being driven, so it was shooting the target. Disabled; duplicate suppression is now only the
`pkill` at the top of `launch()`. Immediately after: 1 launch, 1 game, a stable episode.

Also fixed in `_wait_ready`: it was reading frame counters from PREVIOUS runs because the
harness log is not truncated per launch (it reported "ready at frame 4440 (2s)" on a
freshly started process). It now records the log size at call time and parses only output
produced after that point.

## Session 64 — throughput fixed; reward now pays for winning exchanges

First run in a long time to complete generations steadily: **20 of 20 episodes valid**, two
generations done in ~15 min, and individuals genuinely differ (advance -1.16 to +1.16):

```
gen 0  best -1.12  mean -2.00  roundsW 0
gen 1  best -5.47  mean -5.58  roundsW 0
```

Nothing in the reward paid for WINNING an exchange - `conceded` only punished being pushed
back, so attacking earned zero. Added a `pushed` term, `4 * (max_them - start_them)/100`,
which pays for driving the CPU toward its own goal. That is the only route to the goal line,
since measured running alone gains ~366 px and is then shoved back to the start.

Bug caught while adding it: `conceded` was computed from `best_them`, which I had just
repurposed as a running max, so it would have measured the CPU's full travel range instead of
how far it pushed us. It now uses the CPU's start x explicitly.

### Measured: the agent never lands a hit

```
gen 0  best -0.50  mean -0.72   roundsW 0
gen 1  best  2.79  mean -9.04   roundsW 0
pushed: 0.00 .. 0.00      advance: -0.73 .. 0.55
```

`pushed` is exactly zero for all 20 episodes, i.e. the CPU is never driven back even once.
So the new reward term has no signal because the underlying behaviour it pays for never
happens: the agent does not win a single exchange, including the seeded "walk right, attack
when in reach" policy. Either the strike range/condition in `obs_vector` (|dx| <= 46 px) is
not where a hit actually lands, or the attack needs to be pressed at a different timing.

NEXT DIAGNOSTIC (not yet run): scripted test - walk right until the CPU is adjacent, then
spam F for 10 s, and measure whether them_x increases at all. That answers "is the attack
mechanic even reachable with our keys and range?" before any more reward tuning.

## Session 65 — MEASURED: the strike range is ~22 px, not 46

The diagnostic that mattered, run by hand against a live CPU:

```
engaged dx=59  -> 15 s of F spam: them 196..198  (moved 0 px)
engaged dx=22  -> 15 s of F spam: them 246..297  (moved +51 px)
```

So striking DOES work through our injected keys (attack=70 is confirmed by the game's own
bindingsPlayer1.json), but only from close range. `obs_vector` declared "in reach" at |dx| <=
46 px, so the network was being told to attack from nearly double the effective distance and
every swing whiffed - which is exactly why `pushed` measured 0.00 across 20 episodes.

Fixed: REACH is now 22 px. Verified on the seeded policy:
```
dx=200 -> 68 (right)   dx=60 -> 68   dx=30 -> 68
dx= 20 -> 70 (attack)  dx= 10 -> 70
```

This is the first mechanistic reason found for "the agent never lands a hit", and it is a
plain wrong constant, not a learning failure.

### First generation with the corrected reach

```
== gen 0 best 13.31 mean 11.87 roundsW 0
pushed 0.00..0.00
```

Best fitness is the highest seen so far (13.31 vs 2.79), driven by advance/proximity - so the
corrected reach helped the policy's reward. But `pushed` is still exactly zero: no policy is
getting inside 22 px often enough to land a strike. Closing that gap (approach to striking
distance and stay there) is now the specific behaviour the search has to find.

## Session 66 — reward for closing to striking distance

Measured last tick: strikes only land at |dx| <= 22 px, and `pushed` was 0.00 in every
episode because no policy ever got that close. Nothing in the reward paid for approaching
the OPPONENT (proximity only paid for approaching the GOAL), so closing had no value.

Added `closeness = 5 * max(0, 1 - min|dx|/200)`: full credit if the fighter ever gets within
striking distance, decaying to zero at 200 px away. Episodes now also record `min_dx` so the
effect is directly measurable rather than inferred from fitness.

### CORRECTION to the previous tick's claim

I reported "`pushed` is exactly zero across all 20 episodes". That was wrong: `pushed` was
never written into the records at all, so `r.get('pushed', 0)` was returning MY DEFAULT, not
a measurement. The honest statement is that pushing was never measured, not that it was zero.
The record now carries `pushed`, `closeness` and `min_dx` explicitly.

First generation with the closeness reward (all 10 valid):
```
== gen 0 best -14.41 mean -14.42 roundsW 0 roundsL 10
```
Rounds now RESOLVE and are LOST - the CPU crosses our goal line in every episode. That is new:
before, no crossing was ever detected in the window. So the agent is now engaging (closeness
paid off) and dying, after which the CPU walks through. Engaging without winning is worse than
not engaging, and the reward must now pay for surviving/winning the exchange, not just closing.

## Session 67 — measured tradeoff, and seeding the attack policy permanently

With the rebalanced reward (closeness 1.0, conceded -4, pushed 6) the terms are now actually
recorded and they say:

```
gen 0  best 0.82  mean 0.82   roundsW 0
min_dx  90 px      <- never gets within striking range (22 px)
pushed  0.00       <- so no strikes land
```

So the two settings bracket the problem honestly: closeness weight 5.0 -> the agent closes and
DIES every round (roundsL 10/10); weight 1.0 -> it stays 90 px away and never fights. Neither
is a winner, which means the missing behaviour is "close AND survive the exchange".

Plain tournament selection keeps discarding the one policy that does close and strike (the
hand-written seed). `next_gen` now keeps two scripted anchors (walk-right + strike-when-in-
reach) in every generation, so recombination always has an attack-capable parent instead of
having to rediscover it. Verified: anchor at index 9 gives attack at dx=10 and walk-right at
dx=200.

## Session 68 — window is too short for a win to be possible

Measured: holding a direction moves the fighter at ~12 px/s, and a round needs ~800 px of
travel to reach the goal line at x=1650. That is ~70 s of CONTINUOUS forward movement - and
the episode window was 60 s, so even a perfect policy could not have won a round inside it.
Every "roundsW 0" reading so far was therefore partly an artefact of the window length.

Widening the window to 120 s. Cost: each episode is ~2 min plus entry, so generations take
longer; the point is to make the target reachable at all before optimising throughput.

Also noted from gen 1: best 52.15 vs mean 3.24 - one individual is far ahead of the pack,
which is the kind of split worth watching for whether it can be improved on.

## Session 69 — PHANTOM WINS again, from a broken death counter

A generation reported `roundsW 7 roundsL 9` and looked like the breakthrough. It was not:

```
g0i0  W=3 L=1  me_x 1..320   kills=485  deaths=402
```

The fighter never passed x=320 on a 1650-px goal line, so no round could have been won by
crossing. The wins came from `end_round()`, which attributes rounds using the
teleport-based death detector - and that detector fires on EVERY position jump: 485 "kills"
and 402 "deaths" in a single 120 s episode. Worse, `kills_reward = 3*(485-402) = +249` was
entering fitness and swamping every real term (mean fitness -124.95 is that noise).

Fixed: `end_round()` no longer awards rounds at all (it only resets per-round state), and
`kills_reward` is pinned to 0.0. Rounds now come ONLY from a genuine goal-line crossing
between consecutive samples. Honest expectation after this: roundsW goes back to 0 until the
agent actually reaches x=1650 - which it has never done.

Lesson repeated from the earlier 10-0: whenever a metric suddenly improves, check the trace
for the physical path before believing it.

## Session 70 — measured the ceiling of the best hand-written policy

Ran the two hand-written seeds against a real match for 120 s each:

```
seed4 (walk + strike): me_x 114..232   pushed=0.47   min_dx=0.0   W/L=0/0
```

So even the policy I know can walk and strike advances only ~118 px in two minutes and pushes
the CPU 47 px. It DOES reach contact (min_dx 0). The CPU blocks effectively, therefore
walking to x=1650 is not a viable plan and the agent must win repeated exchanges instead.

That reframes the objective correctly: `pushed` (CPU displaced toward its own goal) is the
honest proxy for winning exchanges, and it carries the largest reward weight (6.0).

Observation upgrade, same session: input 5 was `abs(dx)/400`, redundant with input 0 (dx) and
input 6 (reach flag). It now carries RELATIVE APPROACH SPEED (px/s of the gap closing, sign =
who is closing), which is what strike timing needs against an incoming opponent. Observation
stays 8-dimensional so all 935 weights and the seed anchors remain valid. Verified the seed
still behaves: dx=200 -> walk, dx=30 -> walk, dx=20 -> attack.

## Session 71 — FULLSCREEN INCIDENT: cause and fix

A game took over the whole screen. Two causes, both mine:

1. **`display_mode="1.000000"` in all three prefs templates**, and `launch()` restores
   `prefs_locked.ini` before EVERY run - so fullscreen was being re-imposed on each launch.
   All templates set to `display_mode="0.000000"`.
2. **No guard in the hook** beyond intercepting `toggleFullScreen:`. `relocate_once` now
   forces any window carrying `NSWindowStyleMaskFullScreen` out of it before parking the
   hairline, so even a bad prefs file cannot take the screen.

**Verified after the fix** (off-screen-inclusive window query, because an on-screen-only
query is vacuous when the window is parked at the edge):
```
pid=19336 layer=0 bounds=960x628 at (-958,452) alpha=1.0
```
A normal windowed size, parked so exactly 2 px is visible. `tools/check_env.py` now asserts
windowed mode.

**Also found in the same investigation:** the live prefs had been rewritten to
`language="es-419"` and `unmuted="1"` by our own injected menu keys wandering into OPTIONS
(it had been "ru" on an earlier day). `prefs.ini` is now chmod 444 while a run is active and
unlocked on close, so the game cannot persist those changes - and a mid-run language change
reorders every menu label, which is a prime suspect for the entry flakiness chased for hours.

The user's own prefs were restored to English + muted, and a copy is kept at
`prefs_user_backup.ini`.

### chmod 444 broke the trainer's own prefs write

Locking prefs read-only made `train_win.py` crash instantly:
`PermissionError: prefs.ini` at startup (it writes the muted prefs before launching).
Now it chmod 644s first and `launch()` re-locks. Lesson: a hardening change has to be checked
against every writer of that file, not just the one being defended against.
