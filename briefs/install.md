# Worker — install the runtime, user-level only, and make Nidhogg.exe run

You are on a **fresh Ubuntu 24.04 server** (384 cores, 1.1 TB RAM, no GPU worth using).
The game is already unpacked at **`game/Nidhogg.exe`** (+ `game/data.win`). There is **no sudo**
(`sudo` asks for a password and you must not use it). Everything you install must live in the
user's home, **XDG-compliant** (`$XDG_DATA_HOME`, `$XDG_CACHE_HOME`, `$XDG_CONFIG_HOME`,
`~/.local/opt` for prefixes), and must not touch `/usr`, `/etc` or `/var`.

## Acceptance criteria (this is the job)

1. A **virtual display** works from your user-level install: `Xvfb :40` starts, and `xdotool`
   can query it.
2. **The game runs headless on that display.** The window appears, a screenshot is non-black
   (mean luminance > 5), and the process survives ≥60 s.
3. `python3` can drive it through the repo's own code:

   ```bash
   NID_PROTON=<your proton script>   NID_GAME_DIR=$PWD/game   NID_STEAM_ROOT=<steam root>   \
   NIDFARM=~/.nidfarm-test NID_DISPLAY_BASE=40  \
   python3 -c "import nidlinux as n; n.start_ids([0]); print(n.window(0))"
   python3 -c "import nidstate as s; s.grab(0,'/tmp/proof.png'); print(s.frame(0).mean())"
   ```
   `grab()` must produce a real image **without ImageMagick** — a fallback path using
   `ffmpeg -f x11grab` is already implemented, `ffprobe` is installed.
4. You leave behind a **repeatable script** `results/install.sh` that reproduces your install
   from scratch, and `results/install.json` with versions, paths and commands.

## What you will need (suggested, not exhaustive)

* **Virtual display:** `Xvfb` and its libs. No root → `apt-get download <pkg>` then
  `dpkg-deb -x pkg.deb ~/.local/opt/nidroot`, and run with
  `PATH=~/.local/opt/nidroot/usr/bin:$PATH` and
  `LD_LIBRARY_PATH=~/.local/opt/nidroot/usr/lib/x86_64-linux-gnu`. Pull dependencies the same
  way (`xserver-common`, `libxfont2`, `libpixman-1-0`, `libfontenc1`, `libunwind8`, `xkb-data`…).
  `apt-get download --print-uris <pkg>` tells you the URL if you prefer `curl`.
* **Input:** `xdotool` (needs `libxdo3`; `libX11`/`libXtst` are already present on the box).
* **Windows runtime:** a **user-level Proton**. Two options, try in this order:
  1. **Proton-GE** tarball from GitHub releases (no login needed) — unpack under
     `~/.local/opt/proton-ge`; the `proton` script inside is what `NID_PROTON` points at.
  2. **steamcmd** (Valve tarball, user-level) with anonymous login to fetch the Proton app
     (1493710), then `~/.steam/steam/steamapps/common/Proton - Experimental/proton`.
     `NID_STEAM_ROOT` points at that steam root.
* **Steam API stub:** the build needs `steam_api64.dll`. Since no Steam client runs here,
  install a **Goldberg-style stub**: back up the original `game/steam_api64.dll`, put the stub
  in its place, and add `game/steam_appid.txt` containing `94400`. `python3 -c "import
  zipfile"` can unpack a zip if `unzip` is missing.
* **Vulkan:** `lvp_icd.json` (lavapipe, software) is already present — DXVK only needs *a*
  Vulkan device at 320×200. If DXVK misbehaves, try `PROTON_USE_WINED3D=1` and report which
  worked and its cost.
* Already present: `ffmpeg`, `ffprobe`, `gcc`, `python3`, `numpy 2.4`, `curl`, `tar`, `xz`,
  `zstd`, `dpkg-deb`, `uv`.
* `game/data.win` should already be patched to a 320×200 window (GEN8 field at `0x10+60`).
  If it is not, patch your **own copy** and say so.

## Rules

* Work only in this worktree, and only under `~` for installs. Never write to `/usr`, `/etc`.
* Do **not** edit shared repo files (`nidstate.py`, `docs/`). If a code change is genuinely
  needed, put a `git diff` in `results/install.patch` and describe it; the supervisor merges.
* Prefer the smallest thing that satisfies the acceptance criteria. Do not build a distro.
* Note every download URL and version — the server must be reproducible for 10+ instances.
* Budget: **45 minutes wall clock**. If something cannot be done without root, stop, document
  the exact blocker and the workaround you would try next.

## Deliverables

* `results/install.sh` — idempotent, re-runnable, creates everything from scratch.
* `results/install.json`:

```json
{"ok": true,
 "prefixes": {"nidroot": "~/.local/opt/nidroot", "proton": "..."},
 "env": {"NID_PROTON": "...", "NID_STEAM_ROOT": "...", "PATH_PREPEND": "...", "LD_LIBRARY_PATH": "..."},
 "xvfb_works": true, "xdotool_works": true,
 "game": {"pid": 0, "window": "0x...", "frame_mean_luma": 0.0, "survived_s": 0},
 "steam_stub": "goldberg|none", "dxvk_or_wined3d": "", "blockers": []}
```

Final message: 10 lines max — what works, the env vars to export, the one command to launch,
and what still does not work.
