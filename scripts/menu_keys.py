#!/usr/bin/env python3
"""Do the arrow keys move a menu selection, or are they ignored?

contrib/REPLICATION.md claims: "Up/Down/Left/Right produce no menu movement, while Return always
advances and W/S do move the selection." Measured here on the same farm/build: both work, and W/S
are aliases for Up/Down — one row per press, on the title menu and the pause menu.

    python3 scripts/menu_keys.py 1 menu     # title/main menu (uses nidstate.selected_y)
    python3 scripts/menu_keys.py 0 pause    # pause menu (frozen screen: pixel diff is exact)

Exit 0 when the arrows move the selection (i.e. the replication claim is false), 1 when they do
not. Also usable as a falsifier for the claim in state/claims.jsonl.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n  # noqa: E402
import nidstate as s  # noqa: E402

OPPOSITE = {"Down": "Up", "Up": "Down", "w": "s", "s": "w"}


def pause_menu(i, keys):
    def px():
        return n.frame(i, "/tmp/mk.png")

    def diff(a, b):
        return int((np.abs(a.astype(int) - b.astype(int)) > 10).sum())

    n._focus(i)
    n.key(i, "Escape", hold=0.12)
    time.sleep(1.6)
    a, b = px(), px()
    print(f"pause idle baseline: {diff(a, b)} px (a frozen screen)")
    moved = {}
    for key in keys:
        a = px()
        n.key(i, key, hold=0.12)
        time.sleep(0.55)
        b = px()
        px_changed = diff(a, b)
        moved[key] = px_changed > 500
        print(f"  {key:5s} -> {px_changed:6d} px  "
              f"{'MOVED' if moved[key] else 'no movement'}")
        n.key(i, OPPOSITE[key], hold=0.12)
        time.sleep(0.45)
    return moved


def main_menu(i, keys):
    def to_menu(tries=8):
        for _ in range(tries):
            if s.selected_y(i) is not None:
                return True
            n.key(i, "Return", hold=0.12)
            time.sleep(1.5)
        return s.selected_y(i) is not None

    n._focus(i)
    if not to_menu():
        print("could not reach a menu with a selection dot")
        return {}
    print(f"main menu row: {s.selected_y(i)}")
    moved = {}
    for key in keys:
        if not to_menu():
            break
        y0 = s.selected_y(i)
        n.key(i, key, hold=0.12)
        time.sleep(0.7)
        y1 = s.selected_y(i)
        moved[key] = bool(y0 and y1 and y1 != y0)
        print(f"  {key:5s}: row {y0} -> {y1}  {'ROW MOVED' if moved[key] else 'no row change'}")
        if moved[key]:
            n.key(i, OPPOSITE[key], hold=0.12)
            time.sleep(0.5)
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", nargs="?", type=int, default=0)
    ap.add_argument("mode", nargs="?", choices=("menu", "pause"), default="menu")
    ap.add_argument("--fresh", action="store_true",
                    help="restart the instance so it boots to the title screen (deterministic)")
    a = ap.parse_args()
    if a.fresh:
        n.stop_id(a.instance)
        n.start_ids([a.instance])
        time.sleep(10)
    if not n._game_pid(a.instance):          # self-contained, so a claim can record one command
        print(f"starting instance {a.instance} ...")
        n.start_ids([a.instance])
        for _ in range(40):
            if n._game_pid(a.instance):
                break
            time.sleep(3)
    assert n._game_pid(a.instance), "no game process"
    keys = ("Down", "Up", "w", "s")
    moved = pause_menu(a.instance, keys) if a.mode == "pause" else main_menu(a.instance, keys)
    if not moved:
        print("INCONCLUSIVE: no menu was reachable")
        return 2                                  # cannot run != claim false
    arrows = moved.get("Down") and moved.get("Up")
    print(f"\narrows move the selection: {bool(arrows)}   "
          f"(w/s: {moved.get('w')}/{moved.get('s')})")
    return 0 if arrows else 1                     # 1 = a menu WAS reachable and arrows did not move


if __name__ == "__main__":
    sys.exit(main())
