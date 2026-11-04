"""Find a key sequence that reaches a Training match, verified by game stdout."""
import os, subprocess, time, sys

APP = "/Users/ruggsea/Library/Application Support/Steam/steamapps/common/Nidhogg/Nidhogg.app/Contents/MacOS/Nidhogg"
DYLD = "/Users/ruggsea/Projects/nidhogg-rl/hook/inject.dylib"
OUT = "/tmp/nid_out.log"
KEYS = "/tmp/nid_keys.txt"

CANDS = [
    [13, 13, 13],
    [13, 13, 40, 13],
    [13, 40, 13, 13],
    [13, 40, 13, 13, 13],
    [13, 13, 40, 13, 13],
    [13, 38, 13, 13],
    [13, 13, 38, 13, 13],
]

def launch():
    subprocess.run(["pkill", "-f", "MacOS/Nidhogg"], capture_output=True)
    time.sleep(1.5)
    env = dict(os.environ, SteamAppId="94400", NID_QUIET="1",
               NID_FIGHTERS="1", DYLD_INSERT_LIBRARIES=DYLD)
    open(OUT, "w").close()
    p = subprocess.Popen([APP], env=env, stdout=open(OUT, "w"), stderr=subprocess.STDOUT)
    time.sleep(10)
    return p

def send(seq):
    for k in seq:
        open(KEYS, "w").write(f"{k}\n")
        time.sleep(1.1)

def in_match():
    txt = open(OUT, "rb").read().decode("utf-8", "replace")
    return "match start" in txt

for i, seq in enumerate(CANDS):
    launch()
    send(seq)
    time.sleep(3)
    ok = in_match()
    print(f"seq {seq} -> match_start={ok}", flush=True)
    if ok:
        print("WORKING_SEQUENCE", seq, flush=True)
        sys.exit(0)
print("none worked")
