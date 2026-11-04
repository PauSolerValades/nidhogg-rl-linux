"""Match detection and recovery for the Nidhogg state harness.

The game publishes the two fighters' positions via the injected dylib:
    /tmp/nid_state_<id>.txt -> "p154x p154y p242x p242y have154 have242"

"have154/have242 == 1" is the definitive signal that a match is live: the only
places where both player objects exist are inside a fight. Menus, the WINNER
stats screen and level transitions all lack one or both.
"""
import time

import nav

STATE = "/tmp/nid_state_{}.txt"

KEY_ENTER = 13
ENTRY_PATH = [(38, 0.3)] * 8 + [           # wrap selection to the top (NEWS)
    (40, 1.0),      # down: SINGLE PLAYER
    (13, 2.5),      # enter submenu
    (40, 1.5),      # down: TRAINING
    (13, 2.5),      # select
    (13, 2.5),      # personality (first entry)
    (13, 3.0),      # difficulty
    (13, 4.0),      # level card -> fight
]


def read_state(iid="0"):
    try:
        with open(STATE.format(iid)) as f:
            vals = f.read().split()
        if len(vals) < 6:
            return None
        o154x, o154y, p242x, p242y, h1, h2 = (float(v) for v in vals[:6])
        return {"them_x": o154x, "them_y": o154y, "me_x": p242x, "me_y": p242y,
                "have154": h1, "have242": h2}
    except (OSError, ValueError):
        return None


def is_match_live(iid="0", fresh_s=1.5):
    st = read_state(iid)
    if st is None:
        return False
    return st["have154"] == 1 and st["have242"] == 1


def detect_screen(iid="0"):
    """Best-effort screen classification from state alone."""
    if is_match_live(iid):
        return "in_match"
    # players absent: either a menu or the stats screen; both recover the same
    # way (Enter, then the entry path), so the distinction isn't load-bearing.
    return "menu_or_stats"


def press(iid, code, wait=0.0):
    open(nav.keys_path(iid), "w").write(f"{code}\n")
    if wait:
        time.sleep(wait)


def enter_match(iid="0", timeout_s=90, log=print):
    """Drive the entry key path, returning as soon as a match is live."""
    t0 = time.time()
    for code, wait in ENTRY_PATH:
        press(iid, code)
        if time.time() - t0 > timeout_s:
            break
        time.sleep(wait)
        if is_match_live(iid):
            log(f"[recover] match live after {time.time()-t0:.1f}s (early exit)")
            return True
    # final grace period: the last Enter may still be animating
    while time.time() - t0 < timeout_s:
        if is_match_live(iid):
            log(f"[recover] match live after {time.time()-t0:.1f}s")
            return True
        time.sleep(1.0)
    log(f"[recover] entry path failed after {time.time()-t0:.1f}s")
    return False


def ensure_match(iid="0", timeout_s=120, attempts=2, log=print):
    """Get into a live match however the game is currently sitting."""
    if is_match_live(iid):
        return True
    for attempt in range(attempts):
        t0 = time.time()
        press(iid, KEY_ENTER)            # dismiss stats screen / confirm dialog
        time.sleep(2.0)
        if enter_match(iid, timeout_s=max(20, timeout_s - (time.time() - t0)), log=log):
            return True
        log(f"[recover] attempt {attempt + 1}/{attempts} failed")
    return False


if __name__ == "__main__":
    import sys
    iid = sys.argv[1] if len(sys.argv) > 1 else "0"
    print("screen:", detect_screen(iid))
    ok = ensure_match(iid)
    print("ensure_match ->", ok)
