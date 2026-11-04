#!/bin/bash
# Kill agent instances and restore the user's real settings.
HERE="$(cd "$(dirname "$0")" && pwd)"
pkill -f "MacOS/Nidhogg" 2>/dev/null || true
sleep 1.5
cp "$HERE/prefs_pristine.ini" "$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"
echo "stopped; user prefs restored"
