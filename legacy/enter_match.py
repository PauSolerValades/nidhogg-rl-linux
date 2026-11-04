"""Press the known key path into a Training match, verifying each step changed
the screen, and restarting the game if the path lands somewhere unexpected."""
import os, subprocess, sys, time
import numpy as np
import nav

APP = "/Users/ruggsea/Library/Application Support/Steam/steamapps/common/Nidhogg/Nidhogg.app/Contents/MacOS/Nidhogg"
DYLD = "/Users/ruggsea/Projects/nidhogg-rl/hook/inject.dylib"
HOME_PREFS = os.path.expanduser("~/Library/Application Support/com.messhof.nidhogg/prefs.ini")
SEQ = [13, 13, 38, 13, 40, 13, 13, 13, 13]


def restore_prefs():
    here = os.path.dirname(os.path.abspath(__file__))
    open(HOME_PREFS, "w").write(open(os.path.join(here, "prefs_pristine.ini")).read())


def launch():
    subprocess.run(["pkill", "-f", "MacOS/Nidhogg"], capture_output=True)
    time.sleep(2)
    restore_prefs()
    for p in ("/tmp/nid_inject.log", "/tmp/nid_keys.txt"):
        try: os.remove(p)
        except FileNotFoundError: pass
    open("/tmp/nid_out.log", "w").close()
    env = dict(os.environ, SteamAppId="94400", NID_QUIET="1", NID_FOCUS="1",
               NID_THREAD="1", NID_RV="1", NID_MENU="1",
               DYLD_INSERT_LIBRARIES=DYLD)
    subprocess.Popen([APP], env=env, stdout=open("/tmp/nid_out.log", "w"),
                     stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(13)


def shot():
    return nav.capture()


def changed(a, b, thr=0.8):
    if a is None or b is None:
        return False
    h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
    return float(np.abs(a[:h, :w].astype(int) - b[:h, :w].astype(int)).mean()) > thr


def press_verified(code, tries=3):
    for _ in range(tries):
        before = shot()
        nav.press(code, 1.5)
        after = shot()
        if changed(before, after):
            return True
    return False


def in_match():
    try:
        return "match start" in open("/tmp/nid_out.log", "rb").read().decode("utf-8", "replace")
    except FileNotFoundError:
        return False


def attempt():
    launch()
    for i, k in enumerate(SEQ):
        ok = press_verified(k)
        print(f"  key {i} ({k}) changed={ok}", flush=True)
        if in_match():
            return True
    return in_match()


for n in range(3):
    print(f"attempt {n + 1}", flush=True)
    if attempt():
        print("IN MATCH")
        sys.exit(0)
    print("  no match, retrying")
print("failed")
sys.exit(1)
