#!/bin/bash
mkdir -p "$HOME/Library/Application Support/com.messhof.nidhogg"
SRC="/Users/ruggsea/Library/Application Support/com.messhof.nidhogg"
for f in bindingsPlayer1.json bindingsPlayer2.json misc.ini prefs.ini; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$HOME/Library/Application Support/com.messhof.nidhogg/$f"
done
P="$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"
sed -i '' 's/^unmuted=.*/unmuted="0.000000"/; s/^musicVol=.*/musicVol="0.000000"/; s/^sfxVol=.*/sfxVol="0.000000"/' "$P" 2>/dev/null
grep -E "unmuted|musicVol|sfxVol" "$P"
