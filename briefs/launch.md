# Worker — make Nidhogg.exe create a window under Proton-GE on this server

## State: everything is installed, the game hangs instead of showing a window

Verified working already (do not redo):

```bash
cd ~/Developement/nidhogg-rl-install        # your worktree
. results/env.sh                            # NID_PROTON, NID_GAME_DIR, NID_STEAM_ROOT, NIDFARM
Xvfb :41 -screen 0 640x480x24 -nolisten tcp &   # works (user-level, patched for xkbcomp)
DISPLAY=:41 xdotool getdisplaygeometry          # -> 640 480
```

* GE-Proton 11-12 at `~/.local/opt/GE-Proton11-12-x86_64` (glibc, fine on Ubuntu 24.04)
* wine prefix template already built at `~/.nidfarm-test/template`
* `game/data.win` patched to a 320×200 window
* `game/steam_appid.txt` = `94400`
* **gbe_fork** stub installed as `game/steam_api64.dll` (plain Goldberg lacks
  `SteamInternal_SteamAPI_Init`, which is what the game imports; original kept as `.orig`)

Launch that hangs:

```bash
DISPLAY=:41 STEAM_COMPAT_CLIENT_INSTALL_PATH=$NID_STEAM_ROOT \
STEAM_COMPAT_DATA_PATH=~/.nidfarm-test/template SteamAppId=94400 SteamGameId=94400 \
timeout 90 $NID_PROTON waitforexitandrun $NID_GAME_DIR/Nidhogg.exe
# -> runs for the full 90 s (exit=124), never creates a window
```

`DISPLAY=:41 xdotool search --name '.'` returns **0 windows** — not even a Wine dialog.
`PROTON_LOG=1` output stops right after `dxgkrnl.sys` / `dxgmms1.sys` load, with only
harmless `err:service:validate_context_handle` and ALSA noise. `PROTON_USE_WINED3D=1` and
explicit `VK_ICD_FILENAMES=.../lvp_icd.json` (lavapipe is installed and valid) change nothing,
so it is **not** a graphics-device problem.

## Hypotheses to test (pick your own order)

1. **The stub blocks.** gbe_fork's "regular" variant may be waiting on an IPC object that never
   arrives. Test with the original DLL (`game/steam_api64.dll.orig`) to see whether the failure
   mode changes; check whether gbe writes a log or expects a `steam_settings/` directory
   (`configs.appid`, `configs.user.ini`) next to the exe. Also try the `steamclient` variant.
2. **Nothing is actually launched.** Confirm with `ps -eo pid,stat,wchan:24,args | grep -i nidhogg`
   during a run: is the process alive, is it a `wine-preloader` child, what is it waiting on
   (`/proc/<pid>/stack` may be unavailable, `cat /proc/<pid>/wchan`, `/proc/<pid>/status`).
3. **Wine wants a desktop.** Try `wine explorer /desktop=nd,320x200 Nidhogg.exe` via
   `$NID_PROTON run …` or by invoking `~/.local/opt/GE-Proton11-12-x86_64/files/bin/wine`
   directly with `WINEPREFIX=~/.nidfarm-test/template/pfx` — bypasses Proton's wrapper and gives
   clearer errors.
4. **Missing runtime dep.** `WINEDEBUG=+loaddll,+module` and look for the last module loaded
   before the hang; check for a missing `d3dcompiler_47`, `xinput`, `mfplat`, etc.
5. **Prefix sanity.** Run `winecfg`/`wineboot -u` in that prefix; a partially-built prefix can
   hang exactly like this.

## Acceptance

One command (on :41) that results in `xdotool search --name '[Nn]idhogg'` returning a window id
for ≥60 s, plus a screenshot whose mean luminance > 5, using the repo's own code:

```bash
python3 -c "import nidstate as s; s.grab(0,'/tmp/proof.png'); print(s.frame(0).mean())"
```

## Rules

* User-level only: no sudo, nothing outside `$HOME` and `/tmp`.
* Do not edit shared repo files (`nidstate.py`, `nidlinux.py`, `docs/`); propose changes in
  `results/launch.patch`.
* Budget **40 minutes**. Report the *working launch environment* even if it needs a workaround
  (e.g. `PROTON_USE_WINED3D=1`, wine desktop, a different stub variant).

## Deliverable

`results/launch.json`: `{"ok": bool, "env": {...extra vars...}, "cmd": "...", "window": "0x…",
"luma": 0.0, "survived_s": 0, "root_cause": "…", "workaround": "…", "blockers": []}`
plus `results/launch.sh` that reproduces it. Final message: 6 lines max.

## Never kill by pattern (this killed an earlier worker)

Your brief is passed on stdin, but **an agent's own process carries the whole brief in its
command line** when it is passed as an argument — and even now, `pkill -f <word>` can match
your own shell. So:

* use `pkill -x <exact-process-name>` (e.g. `pkill -x Xvfb`, `pkill -x Nidhogg.exe`) — never
  `pkill -f`;
* if you must match a pattern, exclude yourself: `pgrep -f 'Xvf[b] :41'` (the bracket trick).
