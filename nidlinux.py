#!/usr/bin/env python3
"""Headless Nidhogg on Linux: the hands and eyes.

This file never touches game memory. It owns the processes (so each instance is
isolated), sends keys, takes screenshots, and talks to `spy/nidspy.so` — which is
preloaded INTO the game and reads/writes its own address space, because
/proc/<pid>/mem is refused here (ptrace_scope=1 + Proton's container + the process
reparenting to systemd).

  ./farm.sh init                 # once: reflinked game copy + wine prefix template
  python3 nidlinux.py start 4
  python3 nidlinux.py status
  python3 nidlinux.py menu 0     # press Return until a menu is on screen
  python3 nidlinux.py key 0 Down
  python3 nidlinux.py peek 0     # one window screenshot
  python3 nidlinux.py stop
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import struct

import numpy as np

HOME = Path.home()
# One farm per worker: own prefixes, own procs.json, own logs -> agents cannot collide.
FARM = Path(os.environ.get("NIDFARM") or (HOME / ".nidfarm"))
STEAM = HOME / ".local/share/Steam"
# Both are overridable so a user-level (no sudo, no Steam client) install can be plugged in
# without editing this file: NID_PROTON=<path to the proton script> NID_GAME_DIR=<game dir>.
PROTON = Path(os.environ.get("NID_PROTON")
              or STEAM / "steamapps/common/Proton - Experimental/proton")
GAME_DIR = Path(os.environ.get("NID_GAME_DIR") or (FARM / "game"))
GAME = GAME_DIR / "Nidhogg.exe"
PROCS = FARM / "procs.json"
SPY = Path(__file__).parent / "spy/nidspy.so"
DISPLAY_BASE = int(os.environ.get("NID_DISPLAY_BASE", "10"))
TAG = os.environ.get("NIDTAG", "")
ART = Path(os.environ.get("NIDART", "/tmp/nidart" + (f"-{TAG}" if TAG else "")))

# ---------------------------------------------------------------- launch


def _pids():
    return json.loads(PROCS.read_text()) if PROCS.exists() else {}


def _ensure_display(disp, size="640x480x24"):
    """Every instance gets its own Xvfb: no window is ever visible."""
    if subprocess.run(["pgrep", "-f", f"Xvfb {disp} "], capture_output=True).returncode == 0:
        return
    subprocess.Popen(["Xvfb", disp, "-screen", "0", size, "-nolisten", "tcp"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    time.sleep(1.5)


def start(n):
    start_ids(list(range(n)))


def _env_of(pid):
    try:
        return Path(f"/proc/{pid}/environ").read_bytes().decode("latin1")
    except OSError:
        return ""


def clean_farm(fresh=False):
    """Kill only THIS farm's wine processes and clear stale locks.

    Six accumulated `wineserver` processes made every new launch sit at a black window for
    300 s with no error in the log. Matching on the farm path in /proc/<pid>/environ means
    other farms (other workers, other experiments) are never touched.
    """
    farm = str(FARM)
    killed = 0
    for name in ("wineserver", "wineserver64", "services.exe", "plugplay.exe"):
        for pid in subprocess.run(["pgrep", "-x", name], capture_output=True,
                                  text=True).stdout.split():
            if farm in _env_of(pid):
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    killed += 1
                except (ProcessLookupError, PermissionError, ValueError):
                    pass
    for i in list(_pids()):
        stop_id(i)
    for lock in FARM.glob("inst/*/pfx.lock"):
        lock.unlink(missing_ok=True)
    if fresh:
        for d in FARM.glob("inst/*"):
            subprocess.run(["rm", "-rf", str(d)])
    if killed:
        print(f"[clean] killed {killed} stale wine process(es) for {FARM.name}")
    return killed


def start_ids(ids, fresh=False):
    clean_farm(fresh=fresh)
    procs = _pids()
    for i in ids:
        disp = f":{DISPLAY_BASE + i}"
        _ensure_display(disp)
        prefix = FARM / f"inst/{i}"
        if prefix.exists():
            for lock in ("pfx.lock", "pfx/dosdevices/z:"):
                (prefix / lock).unlink(missing_ok=True)
        else:
            # reflink copy of the initialised template: instant, ~0 bytes on btrfs
            subprocess.run(["cp", "-a", "--reflink=always", str(FARM / "template"), str(prefix)],
                           check=True)
        env = dict(os.environ)
        env.pop("WAYLAND_DISPLAY", None)
        env.update(DISPLAY=disp,
                   STEAM_COMPAT_CLIENT_INSTALL_PATH=str(
                       Path(os.environ.get("NID_STEAM_ROOT") or STEAM)),
                   STEAM_COMPAT_DATA_PATH=str(prefix), SteamAppId="94400",
                   SteamGameId="94400", LD_PRELOAD=str(SPY))
        log = open(FARM / f"logs/py_{i}.log", "ab")
        p = subprocess.Popen([str(PROTON), "waitforexitandrun", str(GAME)],
                             env=env, stdout=log, stderr=log, start_new_session=True)
        procs[str(i)] = {"wrapper": p.pid, "display": disp}
        print(f"instance {i}: display {disp}, wrapper {p.pid}")
    PROCS.write_text(json.dumps(procs, indent=1))
    time.sleep(20)
    for i in ids:
        print(f"instance {i}: game pid {_game_pid(i)}")


def stop():
    """Kill everything in THIS farm only (never touches another worker's farm)."""
    for i in list(_pids()):
        stop_id(i)
    PROCS.unlink(missing_ok=True)
    print("stopped")


def stop_id(i):
    """Restart-your-own-instance: kills instance i and nothing else."""
    procs = _pids()
    info = procs.pop(str(i), None)
    targets = [info["wrapper"]] if info else []
    game = _game_pid(i)
    if game:
        targets.append(game)
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    PROCS.write_text(json.dumps(procs, indent=1))
    time.sleep(2)


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


# ---------------------------------------------------------------- input


def _env(i):
    return dict(os.environ, DISPLAY=_pids()[str(i)]["display"])


def window(i):
    w = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "[Nn]idhogg"],
                       env=_env(i), capture_output=True, text=True).stdout.split()
    return w[0] if w else None


def _focus(i):
    w = window(i)
    if w:
        subprocess.run(["xdotool", "windowfocus", w], env=_env(i), capture_output=True)
    return w


def key(i, keysym, hold=0.0):
    """One key press, or keydown+keyup held for `hold` seconds."""
    _focus(i)
    if hold:
        subprocess.run(["xdotool", "keydown", keysym], env=_env(i), capture_output=True)
        time.sleep(hold)
        subprocess.run(["xdotool", "keyup", keysym], env=_env(i), capture_output=True)
    else:
        subprocess.run(["xdotool", "key", "--clearmodifiers", keysym],
                       env=_env(i), capture_output=True)


def keydown(i, keysym):
    _focus(i)
    subprocess.run(["xdotool", "keydown", keysym], env=_env(i), capture_output=True)


def keyup(i, keysym):
    subprocess.run(["xdotool", "keyup", keysym], env=_env(i), capture_output=True)


# ---------------------------------------------------------------- eyes


def _which(*names):
    for name in names:
        if subprocess.run(["sh", "-c", f"command -v {name}"],
                          capture_output=True).returncode == 0:
            return name
    return None


IMPORT = None          # resolved lazily; ImageMagick is optional
CAN_IMAGEMAGICK = None


def _geometry(i):
    """Window x, y, w, h as ints (needed by the ffmpeg capture path)."""
    w = window(i)
    if not w:
        return None
    out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", w],
                         env=_env(i), capture_output=True, text=True).stdout
    vals = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    try:
        return (int(vals["X"]), int(vals["Y"]), int(vals["WIDTH"]), int(vals["HEIGHT"]))
    except (KeyError, ValueError):
        return None


def grab(i, path="/tmp/nid_grab.png"):
    """Window-only screenshot. ImageMagick `import` when available, else ffmpeg x11grab
    of the window rectangle -- a server install without sudo has no ImageMagick."""
    global IMPORT
    if IMPORT is None:
        IMPORT = _which("import") or ""
    w = _focus(i)
    if not w:
        return None
    if IMPORT:
        subprocess.run([IMPORT, "-display", _pids()[str(i)]["display"],
                        "-window", w, path], check=True, capture_output=True)
        return path
    geo = _geometry(i)
    if not geo:
        return None
    x, y, ww, hh = geo
    disp = _pids()[str(i)]["display"]
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "x11grab",
                    "-video_size", f"{ww}x{hh}", "-i", f"{disp}+{x},{y}",
                    "-frames:v", "1", "-y", path], check=True, capture_output=True)
    return path


def frame(i, path="/tmp/nid_f.png"):
    """Screenshot as an RGB numpy array (ImageMagick -> raw, no PIL needed)."""
    p = grab(i, path)
    if not p:
        return None
    magick = _which("magick", "convert")
    if magick:
        w, h = subprocess.run([magick, "identify", "-format", "%w %h", p],
                              capture_output=True, text=True).stdout.split()
        raw = subprocess.run([magick, p, "-depth", "8", "rgb:-"],
                             capture_output=True).stdout
    else:
        w, h = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                               "-show_entries", "stream=width,height", "-of", "csv=p=0", p],
                              capture_output=True, text=True).stdout.strip().split(",")
        raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", p,
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(int(h), int(w), 3)


def fps(i, secs=6.0, rate=120):
    """Frames per second that actually change on screen.

    Do NOT measure this by calling frame() in a loop: one screenshot round trip costs
    ~0.9 s, so a per-shot loop reports 1.0 fps no matter how fast the game runs (measured:
    12 shots in 11.2 s while the same window was changing 60x/s). Capture one stream
    instead and diff consecutive frames.
    """
    geo = _geometry(i) or (0, 0, 320, 200)
    x, y, w, h = geo
    disp = _pids()[str(i)]["display"]
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "x11grab",
                          "-video_size", f"{w}x{h}", "-framerate", str(rate),
                          "-i", f"{disp}+{x},{y}", "-t", str(secs),
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, h, w)
    changed = int((np.abs(np.diff(f.astype(np.int16), axis=0)).max((1, 2)) > 4).sum())
    return changed / secs


def stable_change(base, after):
    """Pixels that changed AND were static in the baseline (immune to animated art).

    The title and menus have animated birds and grass: a plain frame diff reports ~10k
    changed pixels every second with no input at all. Two consecutive baseline frames
    mark exactly those noisy pixels, so they can be excluded.
    """
    if base is None or after is None:
        return 0
    b1, b2 = base
    still = np.abs(b1.astype(int) - b2.astype(int)).max(2) < 6
    moved = np.abs(after.astype(int) - b1.astype(int)).max(2) > 24
    return int((still & moved).sum())


def press(i, keysym, tries=6, wait=0.9, thresh=60):
    """Press until the screen really changes — keys are dropped mid-transition."""
    b1 = frame(i, "/tmp/nid_b1.png")
    time.sleep(0.35)
    b2 = frame(i, "/tmp/nid_b2.png")
    for _ in range(tries):
        key(i, keysym)
        time.sleep(wait)
        if stable_change((b1, b2), frame(i, "/tmp/nid_b3.png")) > thresh:
            return True
    return False


def in_menu(i):
    """A menu is on screen: the dialogue box is a big block of near-black pixels."""
    a = frame(i, "/tmp/nid_menu.png")
    if a is None:
        return False
    lum = a.mean(2)[100:175, 100:295]
    return (lum < 25).mean() > 0.35


def ensure_menu(i, tries=8):
    """Get a menu on screen (from attract: Return -> title -> Return -> main menu)."""
    for _ in range(tries):
        if in_menu(i):
            return True
        key(i, "Return")
        time.sleep(1.6)
    return in_menu(i)


# ---------------------------------------------------------------- spy protocol


def memory(pid, addr, size, path="/tmp/nid_dump.bin"):
    """Ask the in-process spy for a byte range (it reads its own memory)."""
    out = Path(path)
    out.unlink(missing_ok=True)
    cmd = Path(f"/tmp/nid_cmd_{pid}")
    cmd.write_text(f"dump {addr:x} {size:x} {path}\n")
    t0 = time.time()
    while cmd.exists() and time.time() - t0 < 10:     # a 112 MB dump takes ~0.2 s idle, more under load
        time.sleep(0.02)
    if cmd.exists():
        cmd.unlink(missing_ok=True)
        return None
    return out.read_bytes() if out.exists() else None


def poke(pid, addr, raw):
    Path(f"/tmp/nid_cmd_{pid}").write_text(f"poke {addr:x} {raw.hex()}\n")
    time.sleep(0.2)


def accumulate(pid, addr, delta, width=4, ms=400):
    """Nudge a value repeatedly: physics overwrites constants, it cannot undo a drift."""
    fmt = "<f" if width == 4 else "<d"
    Path(f"/tmp/nid_cmd_{pid}").write_text(
        f"add {addr:x} {struct.pack(fmt, delta).hex()} {ms}\n")
    time.sleep(ms / 1000 + 0.05)


def ping(pid):
    res = Path(f"/tmp/nid_res_{pid}")
    res.unlink(missing_ok=True)
    Path(f"/tmp/nid_cmd_{pid}").write_text("ping\n")
    for _ in range(40):
        time.sleep(0.05)
        if res.exists():
            return res.read_text().strip()
    return None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "start":
        start(int(sys.argv[2]))
    elif cmd == "stop":
        stop()
    elif cmd == "start-id":
        start_ids([int(sys.argv[2])])
    elif cmd == "stop-id":
        stop_id(int(sys.argv[2]))
    elif cmd == "status":
        for i in _pids():
            print(f"{i}: display {_pids()[i]['display']} pid {_game_pid(i)}")
    elif cmd == "key":
        key(int(sys.argv[2]), sys.argv[3])
    elif cmd == "peek":
        print(grab(int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "/tmp/nid_grab.png"))
    elif cmd == "menu":
        print("menu reached" if ensure_menu(int(sys.argv[2])) else "no menu")
    elif cmd == "await":
        # loading 105 MB of data.win takes 2.5-3 minutes on this box: never assume 20 s
        limit = float(os.environ.get("NID_WINDOW_WAIT", "300"))
        t0 = time.time()
        while time.time() - t0 < limit:
            if window(int(sys.argv[2])):
                print(f"window after {time.time()-t0:.0f}s")
                break
            time.sleep(5)
        else:
            print(f"no window after {limit:.0f}s")
    elif cmd == "fps":
        print(f"{fps(int(sys.argv[2])):.1f}")
    elif cmd == "ping":
        print(ping(_game_pid(int(sys.argv[2]))))
    else:
        print(__doc__)
