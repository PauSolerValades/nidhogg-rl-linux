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
    "n", Path(__file__).resolve().parent / "nidlinux.py")
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


def held(i, keysym, wait=1.2):
    """Key press that ALWAYS registers.

    xdotool's instant press/release (~10 ms) can fall entirely between two 60 Hz steps,
    and GameMaker's keyboard_check_pressed then never sees it. Holding 120 ms made menu
    navigation 100% reliable where it used to be a coin flip.
    """
    n.key(i, keysym, hold=0.12)
    time.sleep(wait)


def ensure_menu(i, tries=5):
    """Press Return until a menu (selection dot) is on screen."""
    for _ in range(tries):
        if selected_y(i) is not None:
            return True
        held(i, "Return", 2.0)
    return selected_y(i) is not None


def enter_live_match(i, begin_attempts=2):
    """Reach a REAL match: MENU -> SINGLE PLAYER -> TRAINING -> ladder -> BEGIN.

    The READY screen from `enter_match` is NOT a fight: holding a direction only scrolls
    the camera there, and the fighters never move in world space. This path reaches a
    match with a live CPU (verify with cpu_motion()).
    """
    if not ensure_menu(i):
        return False
    held(i, "Up", 1.0)             # MULTIPLAYER (default) -> SINGLE PLAYER
    held(i, "Return", 1.6)         # -> SINGLE PLAYER screen (HOW TO PLAY / TRAINING)
    held(i, "Return", 1.6)         # TRAINING -> opponent ladder
    for _ in range(begin_attempts):
        for _ in range(4):         # BEGIN sits at the bottom of the ladder
            held(i, "Down", 0.7)
        held(i, "Return", 2.0)
        if sprite_present(i):
            return True
        held(i, "Up", 0.7)
    return sprite_present(i)


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


# ---------------------------------------------------------------- menu (verified by the ● marker)
#
# The selected menu item is marked by a yellow dot at x~200 while the labels stop at
# x~185. So the selected row is simply the row whose yellow pixels reach furthest right.
# Nothing is hardcoded about item order: enumerate_rows() learns it by pressing Down and
# watching where the dot lands.

def selected_y(i, name="sel"):
    a = frame(i, name)
    if a is None:
        return None
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 190) & (g > 170) & (b < 130)
    m[:108, :] = False      # the logo's tail reaches x~213 at y<105: never a menu dot
    m[182:, :] = False
    m[:, :95] = False
    m[:, 260:] = False
    xmax = np.zeros(m.shape[0], dtype=int)
    for y in range(95, 182):
        row = np.nonzero(m[y])[0]
        if len(row):
            xmax[y] = row.max()
    ys = np.nonzero((xmax > 197) & (xmax < 218))[0]
    return int(ys.mean()) if len(ys) else None


def enumerate_rows(i, presses=8):
    """Item y-positions in menu order, learned by pressing Down (the list wraps)."""
    seen = []
    y = selected_y(i)
    if y is None:
        return seen
    seen.append(y)
    for _ in range(presses):
        n.key(i, "Down")
        time.sleep(0.7)
        y = selected_y(i)
        if y is None:
            break
        if y in seen:
            break
        seen.append(y)
    return seen


def goto_row(i, rows, index, tries=12):
    """Press Down until the dot sits on rows[index]."""
    target = rows[index]
    for _ in range(tries):
        y = selected_y(i)
        if y is None:
            return False
        if abs(y - target) <= 2:
            return True
        n.key(i, "Down")
        time.sleep(0.7)
    return False


# ---------------------------------------------------------------- is it a real fight?

def orange_x(i, name="p2"):
    """P2 is orange (255,160,64); P1 is pure yellow, so they never alias."""
    a = frame(i, name)
    r, g, b = (a[:, :, k].astype(int) for k in range(3))
    m = (r > 200) & (g > 120) & (g < 205) & (b < 110)
    ys, xs = np.nonzero(m)
    return float(xs.mean()) if len(xs) > 30 else None


def cpu_motion(i, seconds=4.0):
    """A real TRAINING match has a CPU that plays; the READY screen never moves.

    This is the macOS harness's entry verifier, and it cannot be faked by an animation.
    """
    xs = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        x = orange_x(i, f"cpu{len(xs)}")
        if x is not None:
            xs.append(x)
        time.sleep(0.4)
    return (max(xs) - min(xs)) if len(xs) >= 3 else 0.0


# ---------------------------------------------------------------- fighter records (proven layout)
#
# Worker C proved this layout from attract-mode jump arcs, with no menu and no input:
#   record stride 0x200, x at +0xEC, y at +0xF0 (both float32, room space, fractional),
#   duplicates at +0xFC / +0x100, bbox candidates around +0x120..+0x12C.
# x@+0xEC was seen walking 787.4 -> 758.3; y@+0xF0 arcing 111.4 -> 12.1 -> 143.8.
# Addresses shift per room; the offsets do not.

REC = 0x200
X_OFF = 0xEC
Y_OFF = 0xF0


def biggest_heap(pid):
    return max(regions(pid), key=lambda r: r[1] - r[0])


def fighter_records(pid, heap=None):
    """[(base_addr, x, y)] for every 0x200 record with room-plausible fractional state."""
    a, b = heap or biggest_heap(pid)
    v = dump_f32(pid, a, b - a)
    if v is None:
        return []
    idx = np.arange(0, len(v) - (Y_OFF // 4) - 1, REC // 4)
    x = v[idx + X_OFF // 4]
    y = v[idx + Y_OFF // 4]
    with np.errstate(invalid="ignore"):
        ok = (np.isfinite(x) & np.isfinite(y)
              & (x > 0) & (x < 1100) & (y > 15) & (y < 260)
              & (x != np.round(x)) & (y != np.round(y)))
    sel = np.nonzero(ok)[0]
    return [(a + int(idx[j]) * 4, float(x[j]), float(y[j])) for j in sel]


def moving_fighters(pid, wait=0.45, lo=1.0, hi=120.0):
    """The records whose x moved between two dumps: those are the fighters."""
    heap = biggest_heap(pid)
    before = {a: (x, y) for a, x, y in fighter_records(pid, heap)}
    time.sleep(wait)
    after = {a: (x, y) for a, x, y in fighter_records(pid, heap)}
    out = []
    for a in before.keys() & after.keys():
        dx = after[a][0] - before[a][0]
        if lo <= abs(dx) <= hi:
            out.append((a, before[a], after[a], dx))
    return out
