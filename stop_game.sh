#!/bin/bash
# Kill the game and restore the user's real settings.
pkill -f MacOS/Nidhogg 2>/dev/null || true
sleep 1.5
cp "$(dirname "$0")/prefs_pristine.ini" "$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"
echo "stopped, prefs restored"
