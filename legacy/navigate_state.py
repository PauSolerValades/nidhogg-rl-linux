"""State-driven menu navigation for Nidhogg.

Screen identity comes from the object census the harness publishes:
    MainMenu 102/103, TrainingMenu 213, MatchStats 107, players 154/242.
Unknown screens are backed out of with single Esc presses, checking the census
after each one (double-Esc on the main menu opens the quit dialog, so we stop
as soon as the main-menu signature appears).
"""
import time
from collections import Counter

import nav

OBJ_MAINMENU = {"102", "103"}
OBJ_TRAINING = "213"
OBJ_STATS = "107"
OBJ_PLAYERS = {"154", "242"}


def census(iid="0", tail=400):
    """Object indices seen in the last `tail` reader lines."""
    path = f"/tmp/nid_inject_{iid}.log"
    try:
        lines = open(path, "rb").read().decode("utf-8", "replace").splitlines()[-tail:]
    except OSError:
        return Counter()
    c = Counter()
    for ln in lines:
        if ln.startswith("[all "):
            parts = ln.split()
            for p in parts:
                if p.startswith("obj="):
                    c[p[4:]] += 1
    return c


def wait_census_change(iid="0", timeout=2.5):
    before = census(iid)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if census(iid) != before:
            return True
        time.sleep(0.25)
    return False


def screen(iid="0"):
    c = census(iid)
    if OBJ_PLAYERS <= set(c):
        return "in_match"
    if OBJ_TRAINING in c:
        return "training_menu"
    if OBJ_STATS in c:
        return "stats"
    if OBJ_MAINMENU <= set(c):
        return "main_menu"
    return "unknown"


def esc_to_main(iid="0", max_esc=6, log=print):
    """Single-Esc until the main menu signature appears."""
    for i in range(max_esc):
        if screen(iid) == "main_menu":
            return True
        nav.press_instance(27, iid, wait=0.0)
        time.sleep(1.6)
        wait_census_change(iid)
        log(f"  esc {i+1}: now {screen(iid)}")
    return screen(iid) == "main_menu"


def enter_training_match(iid="0", log=print):
    """From anywhere: end up in a live Training match."""
    if screen(iid) == "in_match":
        return True
    log("[nav] backing out to main menu")
    if not esc_to_main(iid, log=log):
        log("[nav] could not reach main menu")
        return False
    # main menu: NEWS is selected by default? verified earlier: default MULTIPLAYER.
    # SINGLE PLAYER sits directly above it -> one Up, then Enter.
    nav.press_instance(38, iid, wait=0.0)
    time.sleep(1.0)
    nav.press_instance(13, iid, wait=0.0)
    time.sleep(2.5)
    wait_census_change(iid, 3.0)
    sc = screen(iid)
    log(f"[nav] after SINGLE PLAYER enter: {sc}")
    if sc == "training_menu":
        pass                      # already in the training list
    else:
        # submenu may default to ARCADE: one Down to TRAINING, then Enter
        nav.press_instance(40, iid, wait=0.0)
        time.sleep(1.2)
        nav.press_instance(13, iid, wait=0.0)
        time.sleep(2.5)
        wait_census_change(iid, 3.0)
        sc = screen(iid)
        log(f"[nav] after down+enter: {sc}")
    if sc != "training_menu":
        # one more attempt: we may be on the training personality screen already
        pass
    # personality -> difficulty -> level card -> fight
    for _ in range(4):
        if screen(iid) == "in_match":
            return True
        nav.press_instance(13, iid, wait=0.0)
        time.sleep(3.0)
        wait_census_change(iid, 4.0)
        log(f"[nav] enter loop: {screen(iid)}")
    return screen(iid) == "in_match"


if __name__ == "__main__":
    import sys
    iid = sys.argv[1] if len(sys.argv) > 1 else "0"
    ok = enter_training_match(iid)
    print("enter_training_match ->", ok)
    print("census tail:", dict(list(census(iid).items())[:10]))
