"""Drive Nidhogg into a Training match using the injected harness."""
import re, subprocess, sys, time

LOG = "/tmp/nid_inject.log"
KEYS = "/tmp/nid_keys.txt"

def screen():
    try:
        lines = open(LOG, "rb").read().decode("utf-8", "replace").splitlines()
    except FileNotFoundError:
        return set()
    idx = [i for i, l in enumerate(lines) if l.startswith("[name]")]
    if not idx:
        return set()
    start = idx[0]
    blk = [l for l in lines[start:] if l.startswith("[name]")]
    return {m.group(1) for l in blk if (m := re.search(r"deref=(\S+)", l))}

def key(code, wait=0.9):
    open(KEYS, "w").write(f"{code}\n")
    time.sleep(wait)

def wait_for(pred, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = screen()
        if pred(s):
            return s
        time.sleep(0.5)
    return screen()

print("waiting for menu...", wait_for(lambda s: "MainMenu" in s))
key(27); key(27)                      # back out to main menu
for _ in range(3): key(38, 0.5)       # top item = SINGLE PLAYER
key(13, 1.2)
s = screen(); print("submenu:", sorted(s)[:6])
if "TrainingMenu" not in s:
    key(40, 0.8)                      # TRAINING
key(13, 1.2)
s = screen(); print("personality list:", sorted(s)[:6])
key(13, 2.0)                          # pick first personality -> start
s = wait_for(lambda s: "Man" in s, timeout=20)
print("IN MATCH" if "Man" in s else "no match", sorted(x for x in s if x in
      {"Man","Match","Brain","OrangePlayer","YellowPlayer","HeldWeapon"}))
