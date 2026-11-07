#!/bin/sh
# Build the instance image. Works with docker or podman; needs the docker group.
set -eu
cd "$(dirname "$0")/.."
GE="${GE_VERSION:-GE-Proton9-20}"
docker build -f docker/Dockerfile --build-arg "GE_VERSION=$GE" -t nidhogg-headless:latest .
