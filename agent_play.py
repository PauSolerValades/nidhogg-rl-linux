"""Human vs the trained agent — the playable demo.

Launches ONE VISIBLE Nidhogg instance (you need to see it), navigates into a
local 2-player match, and the agent takes P1 while YOU take P2:

    P2 (you)      arrow keys move/aim, PERIOD attacks, COMMA jumps
    P1 (agent)    driven by the best trained parameters

The agent auto-calibrates which fencer it controls by nudging right and watching
which one moves.

usage: python3 agent_play.py [--params /tmp/nid_best_params.json] [--seconds 600]
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent as A
import nav

HERE = os.path.dirname(os.path.abspath(__file__))
APP = ("/Users/ruggsea/Library/Application Support/Steam/steamapps/common/"
       "Nidhogg/Nidhogg.app/Contents/MacOS/Nidhogg")
STATE = "/tmp/nid_state_0.txt"
BEST = "/tmp/nid_best_params.json"


def read_state():
    try:
        vals = open(STATE).read().split()
        if len(vals) < 6:
            return None
        o154x, o154y, y242x, y242y, h1, h2 = (float(v) for v in vals[:6])
        if not (h1 and h2):
            return None
        return {"them_x": o154x, "them_y": o154y, "me_x": y242x, "me_y": y242y}
    except (OSError, ValueError):
        return None


def press(code, wait=0.0):
    open(nav.keys_path("0"), "w").write(f"{code}\n")
    if wait:
        time.sleep(wait)


def navigate_to_local_2p():
    """Main menu -> MULTIPLAYER (default) -> LOCAL (default) -> players 2 -> start."""
    print("navigating to a local 2-player match...")
    time.sleep(1.0)
    press(13, 3.0)               # main menu (title may need one)
    press(13, 3.0)               # into MULTIPLAYER (default selection)
    press(13, 3.0)               # into LOCAL (default)
    time.sleep(2.0)
    press(65, 1.0)               # PLAYERS 3 -> 2  (A decreases)
    press(40, 1.0)               # down to START
    press(13, 5.0)               # start
    press(13, 4.0)               # confirm / level card
    print("match should be starting - you are P2 (arrow keys, PERIOD attack, COMMA jump)")


def calibrate(rng):
    """Nudge right; whichever fencer moves is ours."""
    st0 = read_state()
    for _ in range(8):
        press(68)
        time.sleep(0.15)
    st1 = read_state()
    if not st0 or not st1:
        return None
    d_yellow = abs((st1["me_x"] or 0) - (st0["me_x"] or 0))
    d_orange = abs((st1["them_x"] or 0) - (st0["them_x"] or 0))
    print(f"calibration: yellow moved {d_yellow:.0f}px, orange moved {d_orange:.0f}px")
    return "yellow" if d_yellow >= d_orange else "orange"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default=BEST)
    ap.add_argument("--seconds", type=float, default=600)
    args = ap.parse_args()

    params = json.load(open(args.params)) if os.path.exists(args.params) else \
        {"engage": 95, "aggr": 0.75, "aim": 2, "jump": 0.38, "retreat": 0.22}
    print("agent params:", params)

    subprocess.run(["cp", os.path.join(HERE, "prefs_muted.ini"),
                    os.path.expanduser("~/Library/Application Support/"
                                       "com.messhof.nidhogg/prefs.ini")], check=True)
    env = dict(os.environ, NID_ID="0", SteamAppId="94400", NID_MAN="1",
               NID_THREAD="1", NID_FOCUS="1",
               DYLD_INSERT_LIBRARIES=os.path.join(HERE, "hook", "inject.dylib"))
    # NID_QUIET intentionally OFF: the window must be visible for the human
    subprocess.Popen([APP], env=env, stdout=open("/tmp/nid_out_i0.log", "a"),
                     stderr=subprocess.STDOUT, start_new_session=True)
    print("game launching - the window will appear (this one is for YOU)")
    time.sleep(16)

    navigate_to_local_2p()
    rng = random.Random(7)
    side = None
    for _ in range(3):
        side = calibrate(rng)
        if side:
            break
        time.sleep(2)
    if side is None:
        print("could not calibrate - is the match running?")
        return
    print(f"agent controls the {side} fencer. You have 10 minutes. Fight!")

    t0 = time.time()
    while time.time() - t0 < args.seconds:
        st = read_state()
        if st is None:
            time.sleep(0.1)
            continue
        if side == "orange":
            st = {"them_x": st["me_x"], "them_y": st["me_y"],
                  "me_x": st["them_x"], "me_y": st["them_y"]}
        code = A.act(params, st, rng)
        if isinstance(code, tuple):
            for c in code:
                press(c, 0.0); time.sleep(0.02)
        else:
            press(code, 0.0)
        time.sleep(0.05)
    print("demo over - restoring your settings")
    subprocess.run(["cp", os.path.join(HERE, "prefs_pristine.ini"),
                    os.path.expanduser("~/Library/Application Support/"
                                       "com.messhof.nidhogg/prefs.ini")], check=True)


if __name__ == "__main__":
    main()
