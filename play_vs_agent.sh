#!/bin/bash
# Play against the trained agent. The game window appears; you are P2.
#   move/aim: arrow keys   attack: PERIOD   jump: COMMA
# The agent takes P1 and plays with the best trained parameters.
cd "$(dirname "$0")"
pkill -f train_multinode 2>/dev/null; pkill -f train_state 2>/dev/null
sleep 1
source .venv/bin/activate
exec python3 -u agent_play.py --params /tmp/nid_best_params.json --seconds 900
