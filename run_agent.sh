#!/bin/bash
# Launch N hidden, game-only-muted Nidhogg instances.
#  - window is ordered out of the compositor (verified: 0 on-screen frames in 20 s)
#  - game audio muted via prefs (unmuted/musicVol/sfxVol = 0) AND in-process gain
#  - the Mac's own volume is never touched
# usage: ./run_agent.sh [n]
set -e
N=${1:-2}
HERE="$(cd "$(dirname "$0")" && pwd)"
PREFS="$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"
APP="/Users/ruggsea/Library/Application Support/Steam/steamapps/common/Nidhogg/Nidhogg.app/Contents/MacOS/Nidhogg"
cp "$HERE/prefs_muted.ini" "$PREFS"          # silent for the duration
for i in $(seq 0 $((N-1))); do
  NID_ID=$i SteamAppId=94400 NID_QUIET=1 NID_ORDERS=1 NID_FOCUS=1 \
    DYLD_INSERT_LIBRARIES="$HERE/hook/inject.dylib" \
    nohup "$APP" >> "/tmp/nid_out_i$i.log" 2>&1 &
  sleep 0.6
done
echo "launched $N hidden instances; prefs audio = 0"
