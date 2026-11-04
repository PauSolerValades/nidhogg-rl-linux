"""Per-instance perception daemon.

Captures one hidden game window with Quartz (~38 fps measured on this machine),
runs the fighter tracker, and publishes the latest observation to
/tmp/nid_obs_<id>.json atomically. Keeping capture out of the trainer means a
slow or stuck capture can never stall training; the trainer just reads a value.

usage: python capture_daemon.py <instance_id> [target_hz]
"""
import json
import os
import sys
import time

import numpy as np

import nav
import perceive

OBS = "/tmp/nid_obs_{}.json"


def window_id_for(iid):
    """Read the window number the injected harness published for this instance."""
    path = f"/tmp/nid_inject_{iid}.log"
    try:
        data = open(path, "rb").read().decode("utf-8", "replace")
    except OSError:
        return None
    hits = [ln.split("[win] ")[1].split()[0] for ln in data.splitlines() if "[win] " in ln]
    return int(hits[-1]) if hits else None


def grab(wid):
    """screencapture -l under a timeout.

    Quartz' CGWindowListCreateImage is ~6x faster but blocks forever once the
    window has been ordered out of the compositor; the subprocess path is the only
    one that keeps working while the game stays invisible.
    """
    return nav._grab(wid)


def main():
    iid = sys.argv[1] if len(sys.argv) > 1 else "0"
    hz = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
    period = 1.0 / hz
    out = OBS.format(iid)
    tr = perceive.FastTracker()
    wid = None
    last_t = time.time()
    frames = 0
    t0 = time.time()
    while True:
        start = time.time()
        if wid is None:
            wid = window_id_for(iid)
        img = grab(wid) if wid else None
        if img is None:
            wid = None
            time.sleep(0.25)
            continue
        now = time.time()
        obs = tr.update(img, now - last_t)
        last_t = now
        frames += 1
        rec = {"t": now, "iid": iid, "p1": obs["p1"], "p2": obs["p2"],
               "dx": obs["dx"], "n": obs["n"],
               "my_deaths": tr.events.count("my_death"),
               "their_deaths": tr.events.count("their_death"),
               "fps": round(frames / max(1e-6, now - t0), 1)}
        tmp = out + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f)
        os.replace(tmp, out)
        sleep = period - (time.time() - start)
        if sleep > 0:
            time.sleep(sleep)


if __name__ == "__main__":
    main()
