#!/usr/bin/env bash
# User-level runtime for the server: no sudo, no root, everything under $HOME (+ a tiny
# helper dir in /tmp, which the X server insists on for its xkbcomp binary).
#
# Why this exists:
#   * there is no Xvfb, xdotool or ImageMagick on the box;
#   * the X server execs `xkbcomp` from a path compiled into the binary (/usr/bin), which we
#     cannot write. /tmp/xkb is exactly the same length as /usr/bin, so the binary is patched
#     to point there. One occurrence, verified before patching.
#
# Re-runnable. Idempotent. Run it once per machine, then `source` the env file it writes.
set -euo pipefail

PREFIX="${NID_PREFIX:-$HOME/.local/opt/nidroot}"
CACHE="${NID_CACHE:-$HOME/.cache/nid-debs}"
XKB_BIN=/tmp/xkb                      # must be 8 chars: same length as "/usr/bin"
mkdir -p "$PREFIX" "$CACHE" "$XKB_BIN"

say() { printf '[runtime] %s\n' "$*"; }

# ---------------------------------------------------------------- 1. packages, no root
fetch_extract() {
  local pkgs=("$@")
  cd "$CACHE"
  apt-get install --print-uris -y --no-install-recommends "${pkgs[@]}" 2>/dev/null \
    | grep -oE "'http[^']+\.deb'" | tr -d "'" | sort -u > urls.txt || true
  if [ -s urls.txt ]; then
    xargs -n1 -P8 curl -sSLO < urls.txt 2>/dev/null || true
  fi
  # `apt-get download` is the reliable path when --print-uris yields nothing
  apt-get download "${pkgs[@]}" >/dev/null 2>&1 || true
  local n=0
  for f in *.deb; do
    [ -e "$f" ] || continue
    dpkg-deb -x "$f" "$PREFIX" 2>/dev/null && n=$((n + 1))
  done
  say "extracted $n package(s) into $PREFIX"
}

if [ ! -x "$PREFIX/usr/bin/Xvfb" ]; then
  say "fetching X server + input tooling"
  fetch_extract xvfb xdotool x11-xkb-utils
fi
[ -x "$PREFIX/usr/bin/Xvfb" ] || { say "FATAL: Xvfb not obtained"; exit 1; }

# ---------------------------------------------------------------- 2. xkbcomp reachable
if [ ! -x "$PREFIX/usr/bin/Xvfb.orig" ]; then
  cp "$PREFIX/usr/bin/Xvfb" "$PREFIX/usr/bin/Xvfb.orig"
  python3 - "$PREFIX/usr/bin/Xvfb" <<'PY'
import sys
p = sys.argv[1]
d = open(p, 'rb').read()
n = d.count(b'/usr/bin\x00')
if n != 1:
    sys.exit(f"refusing to patch: {n} occurrences of /usr/bin")
open(p, 'wb').write(d.replace(b'/usr/bin\x00', b'/tmp/xkb\x00'))
print("[runtime] Xvfb patched: xkbcomp lookup -> /tmp/xkb")
PY
  chmod +x "$PREFIX/usr/bin/Xvfb"
fi
if [ ! -x "$XKB_BIN/xkbcomp" ]; then
  cp "$PREFIX/usr/bin/xkbcomp" "$XKB_BIN/xkbcomp" 2>/dev/null || {
    say "xkbcomp missing — fetching x11-xkb-utils"; fetch_extract x11-xkb-utils; cp "$PREFIX/usr/bin/xkbcomp" "$XKB_BIN/xkbcomp"; }
  chmod +x "$XKB_BIN/xkbcomp"
fi

# ---------------------------------------------------------------- 3. env file
cat > "$PREFIX/env.sh" <<EOF
# source me:  . $PREFIX/env.sh
export NID_ROOT=$PREFIX
export PATH=$PREFIX/usr/bin:\$PATH
export LD_LIBRARY_PATH=$PREFIX/usr/lib/x86_64-linux-gnu:$PREFIX/usr/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
export NID_XVFB=Xvfb
EOF

# ---------------------------------------------------------------- 4. verify
. "$PREFIX/env.sh"
pkill -x Xvfb 2>/dev/null || true
sleep 1
Xvfb :44 -screen 0 640x480x24 -nolisten tcp >/tmp/xvfb_verify.log 2>&1 &
for _ in $(seq 1 20); do sleep 0.5; DISPLAY=:44 xdotool getdisplaygeometry >/dev/null 2>&1 && break; done
if DISPLAY=:44 xdotool getdisplaygeometry 2>/dev/null; then
  say "OK: Xvfb + xdotool working on :44"
else
  say "FAILED: X server did not come up"; tail -5 /tmp/xvfb_verify.log; exit 1
fi
pkill -x Xvfb 2>/dev/null || true
say "env:  . $PREFIX/env.sh"
