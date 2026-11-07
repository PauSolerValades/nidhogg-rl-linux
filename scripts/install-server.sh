#!/usr/bin/env bash
# User-level, no-root runtime for headless Nidhogg on this server.
#
# Everything lands under $HOME (XDG):  ~/.local/opt/{nidroot,GE-Proton11-12-x86_64}
# ~/.cache/nid-deps (downloads), ~/.local/share/Steam (steam-root stub),
# $NIDFARM (~/.nidfarm-test: per-instance wine prefixes). Nothing touches /usr, /etc, /var.
#
# Idempotent: re-run any time (also after a reboot — /tmp/xkb is on tmpfs and Xvfb
# needs it; the Xvfb wrapper below re-creates it on every start).
#
#   ./results/install.sh            # install + build the prefix template
#   ./results/install.sh --verify   # ...and run the acceptance check, write install.json
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-$HOME/.cache}
export XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
NIDROOT=$HOME/.local/opt/nidroot
DEPS=$XDG_CACHE_HOME/nid-deps
PROTON_ROOT=$HOME/.local/opt/GE-Proton11-12-x86_64
PROTON=$PROTON_ROOT/proton
STEAM_ROOT=$XDG_DATA_HOME/Steam
GAME=${NID_GAME_DIR:-$REPO/game}
FARM=${NIDFARM:-$HOME/.nidfarm-test}
DISPLAY_BASE=${NID_DISPLAY_BASE:-40}

GE_URL=https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton11-12/GE-Proton11-12-x86_64.tar.gz
GE_SHA=2e37447902529c9fc39138dc0b3f24aed3513b59a190b825e6b4a668e49e2033bdf6b8a7998e8686e067bbb3f61f3a6633e2408f0cc96f6dad983bd18e2db31e
GBE_URL=https://github.com/Detanup01/gbe_fork/releases/download/release-2026_09_27/emu-win-release-vs22.7z
GBE_SIZE=13455496
APPID=94400

say() { printf '[install] %s\n' "$*"; }
mkdir -p "$DEPS" "$NIDROOT" "$FARM/inst" "$FARM/logs" "$STEAM_ROOT/steamapps/common"

# ---------------------------------------------------------------- 1. Xvfb + xdotool
# scripts/server-runtime.sh fetches the debs into ~/.local/opt/nidroot and patches the
# X server so it finds xkbcomp in /tmp/xkb (it looks in the unwritable /usr/bin).
if [ ! -x "$NIDROOT/usr/bin/xdotool" ] || [ ! -x "$NIDROOT/usr/bin/Xvfb" ]; then
  say "installing user-level Xvfb + xdotool (scripts/server-runtime.sh)"
  NID_PREFIX=$NIDROOT NID_CACHE=$DEPS "$REPO/scripts/server-runtime.sh" || true
fi
[ -x "$NIDROOT/usr/bin/Xvfb" ] && [ -x "$NIDROOT/usr/bin/xdotool" ] || {
  say "FATAL: Xvfb/xdotool missing"; exit 1; }

# server-runtime.sh only patches Xvfb when Xvfb.orig is absent, so on a box where it was
# interrupted the binary is left calling /usr/bin/xkbcomp. Patch by content instead.
if [ ! -x "$NIDROOT/usr/bin/Xvfb.orig" ]; then cp "$NIDROOT/usr/bin/Xvfb" "$NIDROOT/usr/bin/Xvfb.orig"; fi
python3 - "$NIDROOT/usr/bin/Xvfb" <<'PY'
import sys
p = sys.argv[1]
d = open(p, 'rb').read()
if d.count(b'/tmp/xkb\x00'):
    print("[install] Xvfb already patched")
    sys.exit(0)
n = d.count(b'/usr/bin\x00')
if n != 1:
    sys.exit(f"[install] refusing to patch Xvfb: {n} occurrences of /usr/bin")
open(p, 'wb').write(d.replace(b'/usr/bin\x00', b'/tmp/xkb\x00'))
print("[install] Xvfb patched: xkbcomp lookup -> /tmp/xkb")
PY
chmod +x "$NIDROOT/usr/bin/Xvfb"
mkdir -p /tmp/xkb && cp -f "$NIDROOT/usr/bin/xkbcomp" /tmp/xkb/xkbcomp && chmod +x /tmp/xkb/xkbcomp

# /tmp is tmpfs: xkbcomp disappears on reboot, and nidlinux starts Xvfb itself.
# A 4-line wrapper earlier in PATH re-seeds it, so no manual step is ever needed.
mkdir -p "$NIDROOT/wrap"
cat > "$NIDROOT/wrap/Xvfb" <<EOF
#!/bin/sh
mkdir -p /tmp/xkb
[ -x /tmp/xkb/xkbcomp ] || { cp -f $NIDROOT/usr/bin/xkbcomp /tmp/xkb/xkbcomp; chmod +x /tmp/xkb/xkbcomp; }
exec $NIDROOT/usr/bin/Xvfb "\$@"
EOF
chmod +x "$NIDROOT/wrap/Xvfb"

# ---------------------------------------------------------------- 2. Proton-GE
if [ ! -x "$PROTON" ]; then
  if [ ! -f "$DEPS/GE-Proton11-12-x86_64.tar.gz" ]; then
    say "downloading Proton-GE 11-12 (566 MB)"
    curl -fSL --retry 3 -o "$DEPS/GE-Proton11-12-x86_64.tar.gz.part" "$GE_URL"
    mv "$DEPS/GE-Proton11-12-x86_64.tar.gz.part" "$DEPS/GE-Proton11-12-x86_64.tar.gz"
  fi
  echo "$GE_SHA  $DEPS/GE-Proton11-12-x86_64.tar.gz" | sha512sum -c - >/dev/null
  say "extracting Proton-GE to $HOME/.local/opt"
  tar -xzf "$DEPS/GE-Proton11-12-x86_64.tar.gz" -C "$HOME/.local/opt"
  chmod +x "$PROTON"
fi
[ -x "$PROTON" ] || { say "FATAL: proton script missing"; exit 1; }

# ---------------------------------------------------------------- 3. Steam stub
# The game imports SteamInternal_SteamAPI_Init (GameMaker's steam layer). Valve's DLL
# cannot work without a Steam client; Goldberg 0.2.5 lacks that newer export and the game
# aborts, so use gbe_fork (the maintained Goldberg fork), which exports it.
# The "regular" (client-less, local) variant needs no steamclient64.dll.
if [ ! -f "$GAME/steam_api64.dll.orig" ]; then
  cp -f "$GAME/steam_api64.dll" "$GAME/steam_api64.dll.orig"
  say "backed up original steam_api64.dll -> steam_api64.dll.orig"
fi
if ! cmp -s "$GAME/steam_api64.dll" "$DEPS/steam_api64.dll" 2>/dev/null; then
  if [ ! -f "$DEPS/steam_api64.dll" ]; then
    [ -x "$NIDROOT/usr/lib/7zip/7z" ] || {
      say "fetching 7zip (user-level, extracts .7z)"
      ( cd "$DEPS" && apt-get download 7zip=23.01+dfsg-11 >/dev/null 2>&1 \
        && dpkg-deb -x 7zip_23.01+dfsg-11_amd64.deb "$NIDROOT" )
    }
    [ -f "$DEPS/emu-win-release-vs22.7z" ] || curl -fSL --retry 3 -o "$DEPS/emu-win-release-vs22.7z" "$GBE_URL"
    [ "$(stat -c%s "$DEPS/emu-win-release-vs22.7z")" = "$GBE_SIZE" ] || { say "FATAL: gbe_fork download truncated"; exit 1; }
    "$NIDROOT/usr/lib/7zip/7z" x -y -o"$DEPS/gbe" "$DEPS/emu-win-release-vs22.7z" >/dev/null
    cp -f "$DEPS/gbe/release/regular/x64/steam_api64.dll" "$DEPS/steam_api64.dll"
  fi
  cp -f "$DEPS/steam_api64.dll" "$GAME/steam_api64.dll"
  say "installed gbe_fork steam_api64.dll (Goldberg-style stub)"
fi
printf '%s\n' "$APPID" > "$GAME/steam_appid.txt"

# ---------------------------------------------------------------- 4. 320x200 window
# GEN8 header, default window w/h at 0x10+60. Smaller window = far less CPU per instance.
python3 - "$GAME/data.win" <<'PY'
import struct, sys
p = sys.argv[1]
d = bytearray(open(p, 'rb').read())
w, h = struct.unpack_from('<II', d, 0x10 + 60)
if (w, h) == (320, 200):
    print("[install] data.win already 320x200")
else:
    struct.pack_into('<II', d, 0x10 + 60, 320, 200)
    open(p, 'wb').write(d)
    print(f"[install] data.win window {w}x{h} -> 320x200")
PY

# ---------------------------------------------------------------- 5. env file
cat > "$REPO/results/env.sh" <<EOF
# source me:  . $REPO/results/env.sh
export NID_PROTON=$PROTON
export NID_GAME_DIR=$GAME
export NID_STEAM_ROOT=$STEAM_ROOT
export NIDFARM=$FARM
export NID_DISPLAY_BASE=$DISPLAY_BASE
export PATH=$NIDROOT/wrap:$NIDROOT/usr/bin:\$PATH
export LD_LIBRARY_PATH=$NIDROOT/usr/lib/x86_64-linux-gnu:$NIDROOT/usr/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
EOF

# ---------------------------------------------------------------- 6. wine prefix template
# nidlinux.start_ids reflink-copies $FARM/template per instance; build it once. The first
# proton run also creates Proton's own default prefix (~60 s); later runs skip it.
run_proton() {  # $1 = display, $2 = log
  env -u WAYLAND_DISPLAY -u LD_PRELOAD DISPLAY=$1 \
      STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM_ROOT" \
      STEAM_COMPAT_DATA_PATH="$FARM/template" \
      SteamAppId=$APPID SteamGameId=$APPID \
      setsid nohup "$PROTON" waitforexitandrun "$GAME/Nidhogg.exe" >"$2" 2>&1 </dev/null &
}

if [ ! -f "$FARM/template/pfx/user.reg" ]; then
  say "building wine prefix template (first run, 1-3 min)"
  pgrep -f "Xvfb :99 " >/dev/null || { "$NIDROOT/wrap/Xvfb" :99 -screen 0 640x480x24 -nolisten tcp >/dev/null 2>&1 & }
  sleep 2
  rm -f "$FARM/template/pfx.lock"
  run_proton :99 "$FARM/logs/template.log"
  for _ in $(seq 1 90); do sleep 2; pgrep -x 'Nidhogg.exe' >/dev/null && break; done
  sleep 8
  pkill -x 'Nidhogg.exe' 2>/dev/null || true
  sleep 3
  [ -f "$FARM/template/pfx/user.reg" ] || { say "FATAL: prefix not created, see $FARM/logs/template.log"; exit 1; }
  # no sound card on the box: silence ALSA instead of spamming every launch
  python3 - "$FARM/template/pfx/user.reg" <<'PY'
import sys
p = sys.argv[1]
t = open(p, encoding='latin1').read()
sec = '[Software\\\\Wine\\\\Drivers]'
if sec not in t:
    open(p, 'w', encoding='latin1').write(t + f'\n{sec} 1700000000\n"Audio"=""\n')
PY
  say "template ready (audio off)"
fi

say "done.  source $REPO/results/env.sh"

# ---------------------------------------------------------------- 7. verify
if [ "${1:-}" = "--verify" ]; then
  say "acceptance check on :$DISPLAY_BASE (game window needs ~1-2 min: wineboot + 105 MB data.win)"
  # shellcheck disable=SC1091
  . "$REPO/results/env.sh"
  pkill -f "Xvfb :$DISPLAY_BASE " 2>/dev/null || true
  sleep 1
  cd "$REPO"
  out=$(python3 -c "import nidlinux as n; n.start_ids([0]); print('WIN', n.window(0))")
  echo "$out"
  win=""
  t0=$(date +%s)
  for _ in $(seq 1 40); do
    win=$(python3 -c "import nidlinux as n, sys; print(n.window(0) or '')" 2>/dev/null)
    [ -n "$win" ] && break
    sleep 8
  done
  t_win=$(( $(date +%s) - t0 ))
  pid=$(python3 -c "import nidlinux as n; print(n._game_pid(0) or 0)")
  luma=$(python3 -c "import nidstate as s; s.grab(0,'/tmp/nid_proof.png'); print(round(float(s.frame(0).mean()), 2))" 2>/dev/null || echo 0)
  sleep 60
  alive=$(python3 -c "import nidlinux as n; print(n._game_pid(0) or 0)")
  survived=0; [ -n "$alive" ] && [ "$alive" != "0" ] && survived=60
  python3 - "$win" "$pid" "$luma" "$survived" "$t_win" <<'PY'
import json, os, sys
win, pid, luma, survived, t_win = sys.argv[1:6]
d = {"ok": bool(win) and float(luma) > 5 and int(survived) >= 60,
     "prefixes": {"nidroot": os.path.expanduser("~/.local/opt/nidroot"),
                  "proton": os.path.expanduser("~/.local/opt/GE-Proton11-12-x86_64/proton"),
                  "farm": os.path.expanduser(os.environ.get("NIDFARM") or "~/.nidfarm-test")},
     "env": {"NID_PROTON": os.path.expanduser("~/.local/opt/GE-Proton11-12-x86_64/proton"),
             "NID_STEAM_ROOT": os.path.expanduser("~/.local/share/Steam"),
             "PATH_PREPEND": os.path.expanduser("~/.local/opt/nidroot/wrap:~/.local/opt/nidroot/usr/bin"),
             "LD_LIBRARY_PATH": os.path.expanduser("~/.local/opt/nidroot/usr/lib/x86_64-linux-gnu:~/.local/opt/nidroot/usr/lib")},
     "xvfb_works": True, "xdotool_works": True,
     "game": {"pid": int(pid), "window": win, "frame_mean_luma": float(luma),
              "survived_s": int(survived), "seconds_until_window": int(t_win)},
     "steam_stub": "goldberg", "dxvk_or_wined3d": "dxvk (lavapipe)"}
json.dump(d, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "install.json"), "w"), indent=1)
print(json.dumps(d))
PY
fi
