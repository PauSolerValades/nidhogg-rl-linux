#!/usr/bin/env python3
"""Shared measurement primitives for the memory-hunt workers.

Every experiment in this project ends up needing the same five things, so they live
here once and both workers run *identical* measurement code — only their strategy
differs, which is what makes their results comparable.

Environment (set by spawn_workers.sh):
  NIDFARM            farm root for this worker (own prefixes, procs.json, logs)
  NID_DISPLAY_BASE   Xvfb display base for this worker (:10 for A, :20 for B)
  NIDTAG             worker tag, namespaces artifact files
  NIDART             artifact directory

The method that matters: **pause the game, then write**. Pausing freezes the
simulation while the renderer keeps drawing, so
  * nothing drifts on its own (measured: 0 px between frames), and
  * a written value only changes the picture if the renderer reads it as state —
    velocities and accumulators do nothing without ticks.
A real position write repaints a sprite-sized box. Camera/view/surface writes repaint
the whole frame, which is how they identify themselves.
"""
import importlib.util
import os
import struct
import time
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "n", Path(__file__).resolve().parent.with_name("nidlinux.py"))
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)

TAG = os.environ.get("NIDTAG", "")
ART = Path(os.environ.get("NIDART", f"/tmp/nidart-{TAG or 'x'}"))
ART.mkdir(parents=True, exist_ok=True)

PAUSE_BOX = (120, 110, 205, 180)     # x0, y0, x1, y1 of the pause menu, excluded from diffs
WARMUP = 13.0


# ---------------------------------------------------------------- lifecycle


def pid_of(i):
    return n._game_pid(i)


def restart(i):
    n.stop_id(i)
    n.start_ids([i])
    return pid_of(i)


def enter_match(i, tries=3):
    """Enter-only menu path -> LOCAL 2-player match (fighters are drivable there)."""
    for _ in range(tries):
        time.sleep(WARMUP)
        for _ in range(6):
            n.key(i, "Return")
            time.sleep(1.5)
        time.sleep(0.5)
        if sprite_present(i):
            return True
    return False


def sprite_present(i):
    """P1 is the only pure-yellow thing on screen (P2 is orange, goal line dim)."""
    a = frame(i, "present")
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    return int(((r > 240) & (g > 240) & (b < 80)).sum()) >= 20


# ---------------------------------------------------------------- eyes


def grab(i, name):
    return n.grab(i, str(ART / f"{name}.png"))


def frame(i, name="f"):
    return n.frame(i, str(ART / f"{name}.png"))


def frozen_noise(i):
    """Two frames of a paused game must be identical; returns changed pixel count."""
    a = frame(i, "fz1")
    time.sleep(0.45)
    b = frame(i, "fz2")
    return n.stable_change((a, b), b)


def pause(i):
    n.key(i, "Escape")
    time.sleep(1.2)
    return frozen_noise(i)


def effect(base, after, box=PAUSE_BOX):
    """(changed pixel count, bbox (w, h)) outside the pause box."""
    if base is None or after is None:
        return 0, None
    diff = np.abs(after.astype(int) - base.astype(int)).max(2) > 24
    x0, y0, x1, y1 = box
    diff[y0:y1, x0:x1] = False
    ys, xs = np.nonzero(diff)
    if not len(xs):
        return 0, None
    return len(xs), (int(xs.max() - xs.min()), int(ys.max() - ys.min()))


def sprite_bbox(i):
    """Bounding box of P1 while paused (dimmed to ~(123,92,0))."""
    a = frame(i, "spr")
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 100) & (r < 160) & (g > 70) & (g < 115) & (b < 25)
    x0, y0, x1, y1 = PAUSE_BOX
    m[y0:y1, x0:x1] = False
    ys, xs = np.nonzero(m)
    if len(xs) < 30:
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


# ---------------------------------------------------------------- memory


def pin(i, pid, addr, value, width=4, ms=400):
    """Pin a value across frames (spy writes at 2 kHz) and return the frame it caused."""
    fmt = "<f" if width == 4 else "<d"
    Path(f"/tmp/nid_cmd_{pid}").write_text(
        f"hold {addr:x} {struct.pack(fmt, value).hex()} {ms}\n")
    time.sleep(0.2)
    return frame(i, f"pin{addr:x}")


def read_f(pid, addr, width=4):
    raw = n.memory(pid, addr, width, str(ART / "read.bin"), )
    return struct.unpack("<f" if width == 4 else "<d", raw)[0] if raw else None


def regions(pid, min_size=1 << 20, max_size=200 << 20):
    out = []
    for line in open(f"/proc/{pid}/maps"):
        p = line.split()
        if p[1][:2] != "rw" or (len(p) > 5 and p[-1].startswith("/")):
            continue
        a, b = (int(x, 16) for x in p[0].split("-"))
        if min_size <= b - a <= max_size:
            out.append((a, b))
    return out


def dump_f32(pid, addr, size):
    raw = n.memory(pid, addr, size, str(ART / "dump.bin"))
    return np.frombuffer(raw, "<f4") if raw else None


def coord_pairs(pid, regions_, xmax=1100.0, ymax=260.0):
    """Structural candidate generator: (x, y) float pairs in plausible ranges.

    Motion-based candidate generation is a trap: it finds everything *derived* from the
    position (camera, view, surface, draw records) and buries the instance. Shape does
    not move, so it cannot be fooled.
    """
    pairs = []
    for a, b in regions_:
        v = dump_f32(pid, a, b - a)
        if v is None:
            continue
        for stride in (1, 2, 4):
            if len(v) <= stride:
                continue
            xs = v[:-stride]
            ys = v[stride:]
            with np.errstate(invalid="ignore"):
                hit = ((xs > 0) & (xs < xmax) & (ys > 20) & (ys < ymax)
                       & (ys < xs) & np.isfinite(xs) & np.isfinite(ys))
            for k in np.nonzero(hit)[0][:20000]:
                pairs.append((a + int(k) * 4, stride * 4))
    return pairs
