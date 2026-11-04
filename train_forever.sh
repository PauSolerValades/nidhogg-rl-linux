#!/bin/bash
# Continuous training loop: train -> evaluate -> warm-start from best -> repeat.
# Stops when out/BEATS_CPU appears (policy wins >=60% of rounds in evaluation).
cd "$(dirname "$0")"
source .venv/bin/activate
mkdir -p out logs
CYCLE=0
while [ ! -f out/BEATS_CPU ]; do
  CYCLE=$((CYCLE+1))
  echo "=== cycle $CYCLE $(date +%H:%M:%S) ===" >> logs/train_forever.log
  # A sleeping display makes GL context creation fail ("Nil context detected") and
  # the runner aborts on launch - this was silently failing whole generations.
  caffeinate -dimsu -t 3600 2>/dev/null &
caffeinate -u -t 1 2>/dev/null
  pkill -f "MacOS/Nidhogg" 2>/dev/null
  sleep 3
  NGAMES=$(pgrep -f "MacOS/Nidhogg" | wc -l | tr -d " ")
  echo "games after sweep: $NGAMES" >> logs/train_forever.log
  INIT=""
  [ -f /tmp/nid_best_win.json ] && INIT="--init"
  python3 -u train_win.py --instances 1 --gens 12 --pop 12 --window 70 $INIT \
      >> logs/train_forever.log 2>&1
  pkill -f "MacOS/Nidhogg" 2>/dev/null
  sleep 2
  echo "--- evaluating $(date +%H:%M:%S) ---" >> logs/train_forever.log
  python3 -u evaluate.py >> logs/train_forever.log 2>&1
  # keep the user's settings clean between cycles
  cp prefs_locked.ini "$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"
  sleep 5
done
echo "BEATS_CPU reached" >> logs/train_forever.log
