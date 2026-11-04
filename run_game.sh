#!/bin/bash
# Launch Nidhogg with the harness. prefs.ini is snapshotted and restored so
# experiments can never leak into the real game settings.
set -e
P="$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"
cp "$(dirname "$0")/prefs_pristine.ini" "$P"
pkill -f MacOS/Nidhogg 2>/dev/null || true
sleep 1.5
APP="/Users/ruggsea/Library/Application Support/Steam/steamapps/common/Nidhogg/Nidhogg.app/Contents/MacOS/Nidhogg"
rm -f /tmp/nid_inject.log /tmp/nid_keys.txt
: > /tmp/nid_out.log
SteamAppId=94400 NID_QUIET=1 NID_FOCUS=1 NID_FIGHTERS=1 NID_MENU=1 NID_THREAD=1 NID_HOOK=1 \
  DYLD_INSERT_LIBRARIES="$(dirname "$0")/hook/inject.dylib" \
  "$APP" > /tmp/nid_out.log 2>&1 &
echo "launched"
