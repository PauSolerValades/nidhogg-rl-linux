#!/usr/bin/env python3
"""Headless Nidhogg on Linux: owns the process tree, reads state from /proc/<pid>/mem.

Why python owns the launch: /proc/kernel/yama/ptrace_scope is 1 here, so only an
ANCESTOR may attach. If we spawn proton, we are the game's ancestor and memory reads
need no root and no injection.

  ./farm.sh init            # once: reflinked game copy + wine prefix template
  python3 nidlinux.py start 4
  python3 nidlinux.py status
  python3 nidlinux.py shot 0 out.png
  python3 nidlinux.py key 0 Return
  python3 nidlinux.py scan 0
  python3 nidlinux.py stop
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HOME = Path.home()
FARM = HOME / ".nidfarm"
STEAM = HOME / ".local/share/Steam"
PROTON = STEAM / "steamapps/common/Proton - Experimental/proton"
GAME = FARM / "game/Nidhogg.exe"
PROCS = FARM / "procs.json"
DISPLAY_BASE = 10
Xvfb = "Xvfb"

# ---------------------------------------------------------------- launch / keys


def _pids():
    return json.loads(PROCS.read_text()) if PROCS.exists() else {}


def _ensure_display(disp, size="640x480x24"):
    """Every instance needs its own Xvfb: no window is ever visible."""
    if subprocess.run(["pgrep", "-f", f"Xvfb {disp} "], capture_output=True).returncode == 0:
        return
    subprocess.Popen(["Xvfb", disp, "-screen", "0", size, "-nolisten", "tcp"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    time.sleep(1.5)


def start(n):
    procs = {}
    for i in range(n):
        disp = f":{DISPLAY_BASE + i}"
        _ensure_display(disp)
        prefix = FARM / f"inst/{i}"
        env = dict(os.environ)
        env.pop("WAYLAND_DISPLAY", None)
        env.update(
            DISPLAY=disp,
            STEAM_COMPAT_CLIENT_INSTALL_PATH=str(STEAM),
            STEAM_COMPAT_DATA_PATH=str(prefix),
            SteamAppId="94400",
            SteamGameId="94400",
            LD_PRELOAD=str(Path(__file__).parent / "spy/nidspy.so"),
        )
        if prefix.exists():
            for lock in ("pfx.lock", "pfx/dosdevices/z:"):
                (prefix / lock).unlink(missing_ok=True)
        else:
            # reflink copy of the initialised template: instant, ~0 bytes on btrfs
            subprocess.run(["cp", "-a", "--reflink=always", str(FARM / "template"), str(prefix)],
                           check=True)
        log = open(FARM / f"logs/py_{i}.log", "ab")
        p = subprocess.Popen(
            [str(PROTON), "waitforexitandrun", str(GAME)],
            env=env, stdout=log, stderr=log, start_new_session=True,
        )
        procs[str(i)] = {"wrapper": p.pid, "display": disp}
        print(f"instance {i}: display {disp}, wrapper {p.pid}")
    PROCS.write_text(json.dumps(procs, indent=1))
    time.sleep(20)
    for i in procs:
        print(f"instance {i}: game pid {_game_pid(i)}")


def stop():
    subprocess.run(["pkill", "-x", "Nidhogg.exe"])
    subprocess.run(["pkill", "-f", "proton[ ]waitforexitandrun"])
    PROCS.unlink(missing_ok=True)
    print("stopped")


def _game_pid(i):
    """The wine process for instance i: the Nidhogg.exe whose DISPLAY matches."""
    disp = _pids()[str(i)]["display"]
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if (d / "comm").read_text().strip() != "Nidhogg.exe":
                continue
            env = (d / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        if f"DISPLAY={disp}".encode() in env:
            return int(d.name)
    return None


def window(i):
    env = dict(os.environ, DISPLAY=_pids()[str(i)]["display"])
    w = subprocess.run(
        ["xdotool", "search", "--onlyvisible", "--name", "[Nn]idhogg"],
        env=env, capture_output=True, text=True,
    ).stdout.split()
    return w[0] if w else None


def key(i, keysym, hold=0.0):
    env = dict(os.environ, DISPLAY=_pids()[str(i)]["display"])
    w = window(i)
    if w:
        subprocess.run(["xdotool", "windowfocus", w], env=env, capture_output=True)
    if hold:
        subprocess.run(["xdotool", "keydown", keysym], env=env)
        time.sleep(hold)
        subprocess.run(["xdotool", "keyup", keysym], env=env)
    else:
        subprocess.run(["xdotool", "key", "--clearmodifiers", keysym], env=env, capture_output=True)


def grab(i, path="/tmp/nid_grab.png"):
    """Instant window-only screenshot (ImageMagick import; ffmpeg x11grab lags)."""
    w = window(i)
    if not w:
        return None
    subprocess.run(["import", "-display", _pids()[str(i)]["display"], "-window", w, path],
                   check=True, capture_output=True)
    return path


def frame(i, path="/tmp/nid_f.png"):
    """Screenshot as an RGB numpy array (ImageMagick -> raw, no PIL needed)."""
    p = grab(i, path)
    if not p:
        return None
    w, h = subprocess.run(["magick", "identify", "-format", "%w %h", p],
                          capture_output=True, text=True).stdout.split()
    raw = subprocess.run(["magick", p, "-depth", "8", "rgb:-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(int(h), int(w), 3)


def stable_change(base, after):
    """Pixels that changed AND were static in the baseline (immune to animated backgrounds).

    The title/menus have animated birds/grass: a plain frame diff reports ~10k changed
    pixels every second with no input at all. Passing two consecutive baseline frames
    excludes exactly those noisy pixels.
    """
    if base is None or after is None:
        return 0
    b1, b2 = base
    still = np.abs(b1.astype(int) - b2.astype(int)).max(2) < 6
    moved = np.abs(after.astype(int) - b1.astype(int)).max(2) > 24
    return int((still & moved).sum())


def press(i, keysym, tries=6, wait=0.9, thresh=60):
    """Press until the screen really changes, not until an animation happens."""
    b1 = frame(i, "/tmp/nid_b1.png")
    time.sleep(0.35)
    b2 = frame(i, "/tmp/nid_b2.png")
    for _ in range(tries):
        key(i, keysym)
        time.sleep(wait)
        cur = frame(i, "/tmp/nid_b3.png")
        n = stable_change((b1, b2), cur)
        if n > thresh:
            return n
    return 0


# ---------------------------------------------------------------- memory


def regions(pid):
    out = []
    with open(f"/proc/{pid}/maps") as f:
        for line in f:
            parts = line.split()
            if parts[1][0] != "r" or parts[1][1] != "w":
                continue
            a, b = (int(x, 16) for x in parts[0].split("-"))
            if 4096 <= b - a <= 512 << 20:
                out.append((a, b))
    return out


def snap(pid, regs):
    """{region: np.float64 array of every 8-byte slot}"""
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    out = {}
    try:
        for a, b in regs:
            try:
                buf = os.pread(fd, b - a, a)
            except OSError:
                continue
            n = len(buf) // 8
            if n:
                out[(a, b)] = np.frombuffer(buf[: n * 8], "<f8").copy()
    finally:
        os.close(fd)
    return out


def moving(s0, s1, lo, hi):
    """addresses whose double moved into (lo, hi) between snapshots"""
    hits = []
    for k in s0.keys() & s1.keys():
        x, y = s0[k], s1[k]
        # plausible game values only: finite, small magnitude, both sides
        ok = (np.abs(x) < 1e5) & (np.abs(y) < 1e5) & np.isfinite(x) & np.isfinite(y)
        d = np.where(ok, y - x, 0.0)
        for i in np.nonzero((d > lo) & (d < hi))[0]:
            hits.append((k[0] + i * 8, float(x[i]), float(y[i])))
    return hits


def scan(i):
    pid = _game_pid(i)
    if not pid:
        sys.exit("no game process for instance (is it running?)")
    regs = regions(pid)
    print(f"pid {pid}: {len(regs)} rw regions, {sum(b - a for a, b in regs)/1e6:.0f} MB")
    t = time.time()
    s0 = snap(pid, regs)
    print(f"snapshot 0 in {time.time() - t:.1f}s")
    key(i, "d", hold=2.0)
    s1 = snap(pid, regs)
    key(i, "a", hold=2.0)
    s2 = snap(pid, regs)
    right = moving(s0, s1, 5, 60)
    left = {a for a, _, _ in moving(s1, s2, -60, -5)}
    cand = [(a, v0, v1) for a, v0, v1 in right if a in left]
    print(f"moved right then left by fighter-speed: {len(cand)} candidates")
    for a, v0, v1 in cand[:40]:
        print(f"  0x{a:x}  {v0:9.2f} -> {v1:9.2f}")
    return cand


# ---------------------------------------------------------------- entry


def enter(i):
    """title -> main menu -> SINGLE PLAYER, one verified press at a time."""
    steps = [("Return", "main menu"), ("Up", "up to SINGLE PLAYER"), ("Return", "single player")]
    for k, label in steps:
        n = press(i, k)
        print(f"  {label}: {n} px changed{'  <-- NO CHANGE' if not n else ''}")
        grab(i, f"/tmp/nid_step_{label.replace(' ', '_')}.png")
    return grab(i, f"/tmp/nid_entry_{i}.png")


def probe():
    """Launch one instance and everything below must run in THIS process (ancestor rule)."""
    stop()
    time.sleep(2)
    start(1)
    for _ in range(40):
        if window(0):
            break
        time.sleep(2)
    entry(0)
    scan(0)


def shot(i, path):
    env = dict(os.environ, DISPLAY=_pids()[str(i)]["display"])
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "x11grab",
         "-video_size", "640x480", "-i", _pids()[str(i)]["display"],
         "-frames:v", "1", "-y", path],
        env=env, check=True,
    )
    return path


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "start":
        start(int(sys.argv[2]))
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        for i in _pids():
            pid = _game_pid(i)
            print(f"{i}: display {_pids()[i]['display']} pid {pid}")
    elif cmd == "shot":
        print(grab(int(sys.argv[2]), sys.argv[3]))
    elif cmd == "key":
        key(int(sys.argv[2]), sys.argv[3])
    elif cmd == "entry":
        enter(int(sys.argv[2]))
    elif cmd == "probe":
        probe()
    elif cmd == "scan":
        scan(int(sys.argv[2]))
    else:
        print(__doc__)
