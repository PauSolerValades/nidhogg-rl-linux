#!/usr/bin/env python3
"""How many headless instances can this box actually carry? Measure, don't guess.

  python3 scripts/loadtest.py 15 [--display-base 300] [--farm ~/.nidfarm-load]

Boots N instances in parallel, waits for windows, then reports per-instance fps, totals for
CPU/RAM, and whether any process died while we watched.
"""
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
BASE = int(sys.argv[3]) if len(sys.argv) > 3 else 300
FARM = Path(sys.argv[5]).expanduser() if len(sys.argv) > 5 else Path.home() / ".nidfarm-load"

os.environ["NIDFARM"] = str(FARM)
os.environ["NID_DISPLAY_BASE"] = str(BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nidlinux as n            # noqa: E402

FARM.mkdir(parents=True, exist_ok=True)
if not (FARM / "game").exists():
    src = Path.home() / ".nidfarm"
    subprocess.run(["cp", "-a", "--reflink=auto", str(src / "game"), str(FARM / "game")], check=True)
    subprocess.run(["cp", "-a", "--reflink=auto", str(src / "template"), str(FARM / "template")], check=True)
    print(f"seeded {FARM} from {src}")

ids = list(range(N))
print(f"booting {N} instances on :{BASE}..:{BASE + N - 1} (farm {FARM.name})")
t0 = time.time()
n.start_ids(ids)
print(f"  start_ids returned after {time.time() - t0:.0f}s")

up = {}
deadline = time.time() + 420
while time.time() < deadline and len(up) < N:
    for k in ids:
        if k not in up and n.window(k):
            up[k] = time.time() - t0
    time.sleep(5)
print(f"  {len(up)}/{N} windows up; first {min(up.values()):.0f}s, last {max(up.values()):.0f}s")
missing = [k for k in ids if k not in up]
if missing:
    print(f"  NO WINDOW for instances {missing}")

print("\nwaiting 15 s for the splash, then sampling fps per instance (3 s each)")
time.sleep(15)
fps = {}
for k in sorted(up):
    try:
        fps[k] = n.fps(k, secs=3.0)
    except Exception as e:
        fps[k] = -1.0
        print(f"  instance {k}: fps probe failed ({e})")

def stat_total(name):
    out = subprocess.run(["ps", "-C", name, "-o", "pcpu=,rss="], capture_output=True,
                         text=True).stdout.split()
    cpu = sum(float(out[i]) for i in range(0, len(out), 2)) if out else 0.0
    rss = sum(int(out[i + 1]) for i in range(0, len(out), 2)) if out else 0
    return cpu, rss / 1024 / 1024

game_cpu, game_rss = stat_total("Nidhogg.exe")
xv_cpu, xv_rss = stat_total("Xvfb")
xvfb_n = subprocess.run(["pgrep", "-c", "-x", "Xvfb"], capture_output=True, text=True).stdout.strip()

print(f"\n{'inst':>4} {'fps':>6}")
for k in sorted(fps):
    print(f"{k:>4} {fps[k]:>6.1f}")
good = [v for v in fps.values() if v > 20]
print(f"\ninstances >20 fps: {len(good)}/{len(fps)}   median {sorted(good)[len(good)//2]:.1f} fps" if good else "\nnone above 20 fps")
print(f"game processes: {len(fps) + len(missing)}   Xvfb: {xvfb_n}")
print(f"game CPU total: {game_cpu:.0f}%  ({game_cpu / max(1, len(up)):.0f}%/instance)   "
      f"game RSS: {game_rss:.1f} GB")
print(f"Xvfb CPU total: {xv_cpu:.0f}%   RSS {xv_rss:.1f} GB")
load = Path("/proc/loadavg").read_text().split()[:3]
mem = subprocess.run(["free", "-g"], capture_output=True, text=True).stdout.splitlines()[1].split()
print(f"load {load}   mem used {mem[2]}G / {mem[1]}G")

print("\nwatching for crashes for 30 s")
before = {k for k in up if n.window(k)}
time.sleep(30)
after = {k for k in up if n.window(k)}
died = sorted(before - after)
print(f"  still alive: {len(after)}/{len(up)}   died: {died if died else 'none'}")
print("\nleave running or clean up with: python3 -c \"import nidlinux as n; n.stop()\" "
      f"(NIDFARM={FARM})")
