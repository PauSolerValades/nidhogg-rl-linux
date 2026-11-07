#!/usr/bin/env python3
"""Boot N instances in parallel, reach each menu, and report what the menu actually says.

  python3 scripts/menutest.py 3        # instances 0..2 in this farm

Success = every instance has a window, one Return lands in a menu, and the highlight bar is
readable (bar_row not None) on each.
"""
import importlib.util
import sys
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "s", Path(__file__).resolve().parent.parent / "nidstate.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

n = s.n

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
ids = list(range(N))

print(f"booting {N} instance(s) in farm {n.FARM.name}, displays "
      f":{n.DISPLAY_BASE}..:{n.DISPLAY_BASE + N - 1}")
n.start_ids(ids, fresh=True)

for k in ids:
    t0 = time.time()
    while time.time() - t0 < 300:
        if n.window(k):
            print(f"  instance {k}: window after {time.time() - t0:.0f}s")
            break
        time.sleep(5)
    else:
        print(f"  instance {k}: NO WINDOW after 300s")

time.sleep(8)          # let the splash finish (state 0 ignores input for ~10 s)
for k in ids:
    n.key(k, "Return", hold=0.12)
    time.sleep(1.2)
    geo = s.menu_geometry(k, f"menu{k}")
    print(f"  instance {k}: menu box/bar = {geo}")
print("\nfps per instance (streamed capture):")
for k in ids:
    if n.window(k):
        print(f"  instance {k}: {n.fps(k, secs=3.0):.1f} fps")
