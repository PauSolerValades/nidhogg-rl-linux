#!/usr/bin/env bash
# Headless Nidhogg farm (Windows build under Proton, no visible window).
#   ./farm.sh init        # one-time: patched game copy + wine prefix template
#   ./farm.sh start 8     # 8 isolated instances
#   ./farm.sh status
#   ./farm.sh stop
set -uo pipefail

ROOT="$HOME/.nidfarm"
STEAM="$HOME/.local/share/Steam"
GAME="$STEAM/steamapps/common/Nidhogg"
PROTON="$STEAM/steamapps/common/Proton - Experimental/proton"
FARMGAME="$ROOT/game"
TPL="$ROOT/template"
INST="$ROOT/inst"
LOGS="$ROOT/logs"
DISPLAY_BASE=10
mkdir -p "$FARMGAME" "$INST" "$LOGS"

log() { printf '[farm] %s\n' "$*"; }

launch_one() {  # $1 = instance index
  local i=$1 disp=$((DISPLAY_BASE + $1)) prefix="$INST/$i"
  pgrep -f "Xvfb :$disp " >/dev/null ||
    Xvfb ":$disp" -screen 0 640x480x24 -nolisten tcp >"$LOGS/xvfb_$i.log" 2>&1 &
  [ -d "$prefix" ] || cp -a --reflink=always "$TPL" "$prefix" 2>/dev/null
  rm -f "$prefix/pfx.lock" "$prefix/pfx/dosdevices/z:" 2>/dev/null
  env -u WAYLAND_DISPLAY DISPLAY=":$disp" \
      STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM" \
      STEAM_COMPAT_DATA_PATH="$prefix" \
      SteamAppId=94400 SteamGameId=94400 \
      "$PROTON" waitforexitandrun "$FARMGAME/Nidhogg.exe" \
      >>"$LOGS/game_$i.log" 2>&1 &
  printf '%s %s\n' "$i" "$disp" >>"$LOGS/pids"
}

case "${1:-}" in
init)
  if [ ! -f "$FARMGAME/data.win" ]; then
    log "copying game (reflink) and shrinking window 960x600 -> 320x200"
    cp -a --reflink=always "$GAME/." "$FARMGAME/"
    python3 - "$FARMGAME/data.win" <<'EOF'
import struct, sys
p = sys.argv[1]; d = bytearray(open(p, 'rb').read())
struct.pack_into('<II', d, 0x10 + 60, 320, 200)      # GEN8: default window w/h
open(p, 'wb').write(d)
EOF
  fi
  if [ ! -d "$TPL/pfx" ]; then
    log "building wine prefix template (first run, ~60s)"
    mkdir -p "$TPL"
    pgrep -f "Xvfb :99 " >/dev/null || Xvfb :99 -screen 0 640x480x24 -nolisten tcp &>/dev/null &
    sleep 1
    env -u WAYLAND_DISPLAY DISPLAY=:99 STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM" \
        STEAM_COMPAT_DATA_PATH="$TPL" SteamAppId=94400 \
        "$PROTON" waitforexitandrun "$FARMGAME/Nidhogg.exe" >"$LOGS/template.log" 2>&1 &
    for _ in $(seq 1 45); do
      sleep 2; pgrep -x 'Nidhogg.exe' >/dev/null && break
    done
    sleep 5; pkill -x 'Nidhogg.exe'; pkill -f 'proton[ ]waitforexitandrun'; sleep 3
    [ -f "$TPL/pfx/user.reg" ] || { log "FAILED: prefix not created, see $LOGS/template.log"; exit 1; }
    python3 - "$TPL/pfx/user.reg" <<'EOF'
import sys
p = sys.argv[1]; t = open(p, encoding='latin1').read()
sec = '[Software\\\\Wine\\\\Drivers]'
if sec not in t:
    open(p, 'w', encoding='latin1').write(t + f'\n{sec} 1700000000\n"Audio"=""\n')
EOF
    log "template ready (audio off)"
  fi
  ;;
start)
  n=${2:-1}; : >"$LOGS/pids"
  log "starting $n instance(s), displays :$DISPLAY_BASE..:$((DISPLAY_BASE + n - 1))"
  for i in $(seq 0 $((n - 1))); do launch_one "$i"; done
  sleep 20
  log "up: $(pgrep -x 'Nidhogg.exe' | wc -l) game process(es)"
  ;;
stop)
  pkill -x 'Nidhogg.exe'; pkill -f 'proton[ ]waitforexitandrun'
  log "stopped"
  ;;
status)
  printf '%-8s %-6s %-8s\n' pid cpu% rssMB
  for p in $(pgrep -x 'Nidhogg.exe'); do
    ps -o pid=,pcpu=,rss= -p "$p" | awk -v p="$p" '{printf "%-8s %-6s %-8.0f\n", p, $2, $3/1024}'
  done
  echo "total: $(pgrep -x 'Nidhogg.exe' | wc -l) instances, $(ps -o pcpu= -C Nidhogg.exe 2>/dev/null | awk '{s+=$1} END {printf "%.0f", s}')% cpu"
  ;;
*)
  sed -n '2,6p' "$0"; exit 1 ;;
esac
