#!/bin/sh
# Injected into the game process (LD_PRELOAD): dumps its own memory on request.
set -e
cd "$(dirname "$0")"
gcc -shared -fPIC -O2 -pthread -o nidspy.so nidspy.c
echo "built $(pwd)/nidspy.so"
