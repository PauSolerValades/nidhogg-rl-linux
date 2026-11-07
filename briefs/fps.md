# Worker — get Nidhogg running at ≥30 fps on this server (currently ~1 fps)

## Why this matters

At 1 fps the game cannot be driven: a 120 ms keypress can fall entirely between two frames, so
*no* keystroke reliably lands. Every navigation and state-mapping experiment is blocked on this.
Target: **≥30 fps measured by frame-change counting**, at 320×200, with one instance.

## Current state (all measured, do not re-litigate)

```bash
cd ~/Developement/nidhogg-rl-linux
. ../nidhogg-rl-install/results/env.sh      # NID_PROTON, NID_GAME_DIR, NID_STEAM_ROOT, NIDFARM
export NIDFARM=$HOME/.nidfarm-test NID_DISPLAY_BASE=41 NID_GAME_DIR=$PWD/game
Xvfb :41 -screen 0 320x200x24 -nolisten tcp &
timeout 120 python3 nidlinux.py start 1     # launches: proton run Nidhogg.exe
timeout 300 python3 nidlinux.py await 0     # window appears ~25 s after launch
```

Game: GameMaker YYC x64, `data.win` 105 MB, window patched to 320×200. Proton-GE 11-12.
No GPU on this box (`lavapipe` software Vulkan + mesa `llvmpipe` are installed and valid).
Box: 384 cores, load ~70–110 from other tenants, but CPU/IO pressure ≈ 0 (we are not starved).

Measured ~**1.0 fps**, with the process using 200–850% CPU, spread across `Nidhogg.exe`,
`wined3d_cs`, and several `llvmpipe-*` threads. Window is up, content renders, luma ~60.

Already tried, each still ~1 fps:

* DXVK + lavapipe (default) — 847% CPU, 2 fps
* `PROTON_USE_WINED3D=1` — 197% CPU, 1 fps
* `data.win` window 960×600 → 320×200, Xvfb screen 640×480 → 320×200
* audio disabled in the prefix registry (`[Software\\Wine\\Drivers] "Audio"=""`)
* `PROTON_NO_FSYNC=1 PROTON_NO_ESYNC=1`
* `vblank_mode=0 __GL_SYNC_TO_VBLANK=0 MESA_GLTHREAD=true`

## Hypotheses (your call on order, but be systematic)

1. **No usable GLX/Vulkan path** → wined3d falling back to GDI, or lavapipe doing something
   pathological. Check what the X server advertises (`xdpyinfo`, `glxinfo` from mesa-utils; both
   can be extracted user-level with `apt-get download` + `dpkg-deb -x` as in
   `scripts/server-runtime.sh`). Compare `LIBGL_ALWAYS_SOFTWARE=1` vs default.
2. **The game itself is slow, not the renderer.** Test with the frame rate measured *in game
   terms*: put the fighter in motion (hold `d`) and measure how far `x@+0xEC` moves per second —
   `nidstate.find_fighters()` gives the records. If the *logic* runs at 60 steps/s while the
   *picture* updates at 1 Hz, the problem is present/blit, not the game.
3. **Per-frame cost inside the game**: 105 MB `data.win`, 100 MB of it audio. Try a copy with the
   AUDO chunk stripped or `SYNTH`/audio extensions disabled, to see if audio mixing is the cost.
4. **Different display server**: `Xtigervnc` (in `~/.cache/nid-debs`, needs the same xkbcomp
   patch, see the workaround in `scripts/server-runtime.sh`) instead of Xvfb — it ships its own
   GLX/Xvnc paths and may present much faster.
5. **Different Wine**: plain Debian/Ubuntu `wine` 9 (user-level extract) instead of GE-Proton.
6. **`SleepMargin` / vsync inside the game**: `game/options.ini` has `SleepMargin=1`; GM's frame
   limiter with a broken timer can sleep far too long. Try larger values, and try
   `WINEDLLOVERRIDES` for `d3d11`/`dxgi`.

## Rules

* User-level only. **Never `pkill -f`** (it matches your own command line — this has killed a
  worker before). Use `pkill -x <exact name>`; never kill `wineserver` unless it is yours.
* Do not edit shared repo files (`nidstate.py`, `nidlinux.py`, `docs/`); propose changes in
  `results/fps.patch`.
* Budget **40 minutes**. Report the winning environment even if the number is only 10–15 fps.

## Acceptance

≥30 fps by frame-change counting at 320×200, reproducible from `results/fps.sh`, plus the
root cause in one sentence. If you cannot reach 30, report the best number and *why*.

## Deliverable

`results/fps.json`: `{"ok": bool, "fps": 0.0, "env": {...}, "cmd": "...", "root_cause": "...",
"what_did_not_help": [...], "blockers": []}` and `results/fps.sh`. Final message: 6 lines max.
