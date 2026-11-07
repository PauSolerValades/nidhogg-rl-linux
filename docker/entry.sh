#!/bin/sh
# One instance: virtual display -> private game copy -> proton -> Nidhogg.exe
# Everything the harness reads/writes lives in /state (bind-mount it to the host).
set -eu

INSTANCE="${NID_INSTANCE:-0}"
DISP=":$((10 + INSTANCE))"
STATE=/state/$INSTANCE
mkdir -p "$STATE/logs" /opt/steamroot

# writable copy of the game (reflink when the filesystem supports it, else plain copy)
if [ ! -x "$STATE/game/Nidhogg.exe" ]; then
  cp -a --reflink=auto /game "$STATE/game"
  # 320x200 window: GEN8 header field at 0x10+60. Config, not gameplay -- and it is the
  # difference between 25 fps at 112% CPU and 60 fps at 41% (measured).
  python3 - "$STATE/game/data.win" <<'PY' || true
import struct, sys
p = sys.argv[1]
d = bytearray(open(p, 'rb').read())
if d[:4] == b'FORM':
    struct.pack_into('<II', d, 0x10 + 60, 320, 200)
    open(p, 'wb').write(d)
    print("[entry] data.win window -> 320x200")
PY
fi

Xvfb "$DISP" -screen 0 640x480x24 -nolisten tcp >"$STATE/logs/xvfb.log" 2>&1 &
sleep 1

export DISPLAY="$DISP"
export STEAM_COMPAT_DATA_PATH="$STATE/prefix"
export STEAM_COMPAT_CLIENT_INSTALL_PATH=/opt/steamroot
export SteamAppId=94400 SteamGameId=94400
# spy .so (built here so it matches this glibc): reads/writes the game's own memory
if [ -x /repo/spy/build.sh ]; then /repo/spy/build.sh >/dev/null 2>&1 || true; fi
[ -f /repo/spy/nidspy.so ] && export LD_PRELOAD=/repo/spy/nidspy.so

mkdir -p "$STEAM_COMPAT_DATA_PATH"
echo "[entry] instance $INSTANCE on $DISP"
exec "$NID_PROTON" waitforexitandrun "$STATE/game/Nidhogg.exe"
