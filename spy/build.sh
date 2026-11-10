#!/bin/sh
# Injected into the game process (LD_PRELOAD): reads/writes its own memory on request.
#
# Zig 0.17.1 via anyzig (`~/.local/bin/zig` picks the version up from here).
# nidspy.c is the C version this replaces, kept as the reference.
set -e
cd "$(dirname "$0")"
zig 0.17.1 build-lib -dynamic -fPIC -OReleaseFast -lc --name nidspy nidspy.zig
mv -f libnidspy.so nidspy.so
echo "built $(pwd)/nidspy.so"
