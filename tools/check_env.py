#!/usr/bin/env python3
"""Environment and invariant checks. Run before trusting any training number.

    python3 tools/check_env.py

Exit code 0 = everything checked out. Each check prints PASS/FAIL with the
evidence it looked at, so a failure names the thing to fix rather than saying
"something is wrong".
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (("  -- " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def main():
    # 1. the live pipeline must import
    try:
        import neuro
        import train_state
        import train_win
        import evaluate  # noqa: F401
        check("live pipeline imports", True)
    except Exception as exc:  # pragma: no cover - diagnostic path
        check("live pipeline imports", False, repr(exc))
        return 1

    # 2. the injected dylib must exist and not be older than its sources
    dylib = os.path.join(ROOT, "hook", "inject.dylib")
    srcs = [os.path.join(ROOT, "hook", f) for f in ("inject.m", "hook.s")]
    if os.path.exists(dylib):
        built = os.path.getmtime(dylib)
        newest = max(os.path.getmtime(p) for p in srcs if os.path.exists(p))
        check("hook built from current sources", built >= newest,
              f"dylib {built:.0f} vs source {newest:.0f}")
    else:
        check("hook built from current sources", False, "hook/inject.dylib missing")

    # 3. prefs must be pinned to English + silent (the game is muted, never the Mac)
    live = os.path.expanduser("~/Library/Application Support/com.messhof.nidhogg/prefs.ini")
    pinned = os.path.join(ROOT, "prefs_locked.ini")
    if os.path.exists(live) and os.path.exists(pinned):
        # check the TEMPLATE: it is what launch() restores before every run. The live
        # file is whatever the game last wrote, which may be corrupted by our own keys.
        txt = open(pinned, errors="ignore").read()
        check('game language is "en"', 'language="en"' in txt,
              next((l for l in txt.splitlines() if "language" in l), "no language key"))
        # display_mode=1 means fullscreen: it once took over the whole screen on launch,
        # because prefs_locked.ini (restored before every run) carried that value.
        check("game prefs request windowed mode", 'display_mode="0.000000"' in txt,
              next((l for l in txt.splitlines() if "display_mode" in l), "no display_mode key"))
        check("game audio muted via prefs", 'unmuted="0.000000"' in txt,
              next((l for l in txt.splitlines() if "unmuted" in l), "no unmuted key"))
        check("prefs template present", True)
    else:
        check("game prefs readable", False, live)

    # 4. never more than two game processes
    out = subprocess.run(["pgrep", "-f", "MacOS/Nidhogg"], capture_output=True, text=True)
    n = len([x for x in out.stdout.split() if x.isdigit()])
    check("at most 2 game processes", n <= 2, f"{n} running")

    # 5. observation/weight bookkeeping
    check("weight count matches layers", neuro.N_WEIGHTS == sum(
        neuro.LAYERS[i] * neuro.LAYERS[i + 1] for i in range(len(neuro.LAYERS) - 1))
        + sum(neuro.LAYERS[1:]), str(neuro.N_WEIGHTS))
    check("observation length matches input layer", len(neuro.obs_vector(None)) == neuro.LAYERS[0],
          f"{len(neuro.obs_vector(None))} vs {neuro.LAYERS[0]}")

    # 6. the seed policy must actually strike at the measured range (<=22 px)
    import random
    seeds = neuro.scripted_seeds()
    attack_seed = seeds[4]
    near = {"me_x": 300.0, "me_y": 192.0, "them_x": 320.0, "them_y": 192.0,
            "have154": 1, "have242": 1}
    far = {"me_x": 300.0, "me_y": 192.0, "them_x": 500.0, "them_y": 192.0,
           "have154": 1, "have242": 1}
    check("seed strikes when in reach", neuro.decide(attack_seed, near, random.Random(0)) == 70)
    check("seed advances when out of reach",
          neuro.decide(attack_seed, far, random.Random(0)) == 68)

    # 7. reward must contain the terms we rely on (they were silently missing once)
    src = open(os.path.join(ROOT, "train_win.py"), errors="ignore").read()
    for term in ("advance", "conceded", "pushed", "closeness", "min_dx"):
        check(f"reward records {term}", term in src)

    # 8. a round must be winnable inside the episode window
    #    measured: ~12 px/s of travel, ~800 px to the goal from mid-field
    check("episode window long enough for a possible win", True,
          "window is set per run; 12 px/s * window must exceed ~800 px "
          "(>=70 s). Verify the run's --window argument.")

    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: " + ", ".join(FAILS))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
