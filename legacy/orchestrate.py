"""Bring up a hidden, muted, playing set of Nidhogg instances. One command.

Everything here has been verified individually:
  * window ordered out of the compositor  -> 0 on-screen frames measured
  * prefs audio zeroed for the game only  -> the Mac's volume is untouched
  * game_set_speed(300)                   -> faster stepping
  * the known key path gets each instance into a Training match

usage: python orchestrate.py [n_instances]
"""
import os
import subprocess
import sys
import time

import nav

HERE = os.path.dirname(os.path.abspath(__file__))
APP = ("/Users/ruggsea/Library/Application Support/Steam/steamapps/common/"
       "Nidhogg/Nidhogg.app/Contents/MacOS/Nidhogg")
PREFS = os.path.expanduser("~/Library/Application Support/com.messhof.nidhogg/prefs.ini")
ENV_BASE = dict(os.environ, SteamAppId="94400", NID_QUIET="1", NID_ORDERS="1",
                NID_FOCUS="1", DYLD_INSERT_LIBRARIES=os.path.join(HERE, "hook", "inject.dylib"))
SEQ = [13, 13, 38, 13, 40, 13, 13, 13, 13]


def wait_window(iid, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if str(iid) in nav.instance_wids():
            return True
        time.sleep(0.5)
    return False


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(f"bringing up {n} hidden instances", flush=True)
    subprocess.run(["cp", os.path.join(HERE, "prefs_muted.ini"), PREFS], check=True)
    subprocess.run(["pkill", "-f", "MacOS/Nidhogg"], capture_output=True)
    subprocess.run(["pkill", "-f", "capture_daemon.py"], capture_output=True)
    subprocess.run(["pkill", "-f", "supervisor.py"], capture_output=True)
    time.sleep(2)

    for i in range(n):
        env = dict(ENV_BASE, NID_ID=str(i))
        log = open(f"/tmp/nid_out_i{i}.log", "a")
        subprocess.Popen([APP], env=env, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
        time.sleep(0.8)

    for i in range(n):
        ok = wait_window(i)
        print(f"  instance {i}: window {'published' if ok else 'MISSING'}", flush=True)

    for i in range(n):
        subprocess.Popen([sys.executable, "-u", os.path.join(HERE, "supervisor.py"),
                          str(i), "25", "6"],
                         stdout=open(f"/tmp/nid_sup_{i}.log", "a"),
                         stderr=subprocess.STDOUT, start_new_session=True)

    # speed
    for i in range(n):
        open(f"/tmp/nid_speed_{i}.txt", "w").write("300\n")
    time.sleep(2)

    # drive every instance into a Training match
    for k in SEQ:
        for i in range(n):
            nav.press_instance(k, str(i), wait=0.0)
        time.sleep(1.3)
    time.sleep(3)

    for i in range(n):
        try:
            obs = open(f"/tmp/nid_obs_{i}.json").read()[:120]
        except OSError:
            obs = "no observations yet"
        print(f"  inst {i} obs: {obs}", flush=True)
    print("ready", flush=True)


if __name__ == "__main__":
    main()
