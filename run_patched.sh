#!/bin/bash
set -e
P="$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"
cp "$(dirname "$0")/prefs_pristine.ini" "$P"
pkill -f "NidhoggPatch.app" 2>/dev/null || true
pkill -f "MacOS/Nidhogg" 2>/dev/null || true
sleep 1.5
APP="$(dirname "$0")/work/NidhoggPatch.app/Contents/MacOS/Nidhogg"
rm -f /tmp/nid_inject.log /tmp/nid_keys.txt
: > /tmp/nid_out.log
SteamAppId=94400 NID_QUIET=1 NID_FOCUS=1 NID_THREAD=1 NID_HOOK=1 \
  DYLD_INSERT_LIBRARIES="$(dirname "$0")/hook/inject.dylib" \
  "$APP" > /tmp/nid_out.log 2>&1 &
echo "launched patched copy"
