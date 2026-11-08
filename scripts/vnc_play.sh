#!/bin/sh
# Human-playable VNC session: Xtigervnc on :50 + the game on it, recorded if asked.
#
#   ./scripts/vnc_play.sh            # start VNC + game
#   ./scripts/vnc_play.sh record     # ...and record state + heap snapshots while you play
#
# Connect from your laptop:   ssh -L 5950:localhost:5950 psoler@artemis
# then point any VNC client at  localhost:5950   (macOS: Finder → Go → Connect to Server →
# vnc://localhost:5950)
#
# Controls: P1 = W/A/S/D move+sword position, F attack, G jump. P2 = arrow keys.
# You drive the menus yourself: Up/Down + Enter. For a CPU opponent use
# SINGLE PLAYER -> TRAINING (local multiplayer gives you a second, idle human).
set -eu
cd "$(dirname "$0")/.."
. "$HOME/nidhogg-rl-install/results/env.sh"
ROOT=$HOME/.nidfarm-vnc
mkdir -p "$ROOT"
if [ ! -d "$ROOT/game" ]; then
  cp -a --reflink=auto "$HOME/.nidfarm/game" "$ROOT/game"
  cp -a --reflink=auto "$HOME/.nidfarm/template" "$ROOT/template"
fi

if ! (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q ':5950'; then
  echo "[vnc] starting Xtigervnc on :50 (port 5950)"
  Xtigervnc :50 -geometry 960x600 -depth 24 -SecurityTypes None -AlwaysShared -rfbport 5950 \
    > "$ROOT/vnc.log" 2>&1 &
  sleep 3
fi

if ! DISPLAY=:50 xdotool search --name '[Nn]idhogg' >/dev/null 2>&1; then
  echo "[vnc] launching the game on :50 (~65 s to the window)"
  NIDFARM="$ROOT" NID_DISPLAY_BASE=50 NID_GAME_DIR="$ROOT/game" \
    python3 -c "import nidlinux as n; n.start_ids([0])" >/dev/null 2>&1 || true
fi

echo
echo "connect:  ssh -L 5950:localhost:5950 $(whoami)@$(hostname -s)"
echo "then open: vnc://localhost:5950"
echo
case "${1:-}" in
  record) exec python3 scripts/record.py 0 "$@" ;;
  *) (sleep 2; DISPLAY=:50 xdotool search --name '[Nn]idhogg' | head -1 | xargs -r DISPLAY=:50 xdotool windowfocus) ;;
esac
