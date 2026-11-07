#!/usr/bin/env bash
# Launch the two memory-hunt workers in parallel, each in its own farm + worktree:
#   A: P1.x via structural sweep     (display :10, farm ~/.nidfarm)
#   B: P1.y via the vertical axis    (display :20, farm ~/.nidfarm-b)
# Each gets its own git worktree so they cannot clobber each other's code.
set -uo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
BASE="$(dirname "$REPO")"
BUDGET="${BUDGET:-1800}"          # seconds per worker
mkdir -p "$REPO/results" "$REPO/logs"
[ -d "$REPO/results" ] && git -C "$REPO" check-ignore -q results 2>/dev/null || true

spawn() {  # $1=tag $2=display_base $3=farm
  local tag=$1 disp=$2 farm=$3 wt="$BASE/nidhogg-rl-$1"
  if [ ! -d "$wt" ]; then
    git -C "$REPO" worktree add --detach "$wt" HEAD >/dev/null 2>&1 || true
  fi
  # farm must have the patched game copy and the wine prefix template
  if [ ! -d "$farm/game" ]; then
    mkdir -p "$farm/logs"
    cp -a --reflink=always "$HOME/.nidfarm/game" "$farm/game"
    cp -a --reflink=always "$HOME/.nidfarm/template" "$farm/template"
  fi
  echo "[spawn] $tag: farm=$farm display=:$disp worktree=$wt"
  ( cd "$wt" && \
    NIDFARM="$farm" NID_DISPLAY_BASE="$disp" NIDTAG="$tag" \
    NIDART="/tmp/nidart-$tag" \
    timeout "$BUDGET" pi --print --no-session --model "${NID_MODEL:-deepseek-flash}" \
      --tools bash,read,write,edit \
      "$(cat "$REPO/briefs/$tag.md")" \
      > "$REPO/logs/worker_$tag.log" 2>&1 ; \
    echo "[worker $tag] exit $?" >> "$REPO/logs/worker_$tag.log" ) &
}

TAGS="${*:-a b c}"
pkill -x 'Nidhogg.exe' 2>/dev/null; sleep 2
for t in $TAGS; do
  case "$t" in
    a) spawn a 10 "$HOME/.nidfarm" ;;
    b) spawn b 20 "$HOME/.nidfarm-b" ;;
    c) spawn c 30 "$HOME/.nidfarm-c" ;;
    *) echo "[spawn] unknown tag $t" ;;
  esac
done
echo "[spawn] both launched; logs in $REPO/logs/worker_{a,b}.log"
wait
echo "[spawn] both finished"
