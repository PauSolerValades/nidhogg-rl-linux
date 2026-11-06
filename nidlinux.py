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

import numpy as np

HOME = Path.home()
# One farm per worker: own prefixes, own procs.json, own logs -> agents cannot collide.
FARM = Path(os.environ.get("NIDFARM") or (HOME / ".nidfarm"))
STEAM = HOME / ".local/share/Steam"
PROTON = STEAM / "steamapps/common/Proton - Experimental/proton"
GAME = FARM / "game/Nidhogg.exe"
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


def start_ids(ids):
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
        env.update(DISPLAY=disp, STEAM_COMPAT_CLIENT_INSTALL_PATH=str(STEAM),
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


def grab(i, path="/tmp/nid_grab.png"):
    """Instant window-only screenshot (ImageMagick import; ffmpeg x11grab lags)."""
    w = _focus(i)
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
    while cmd.exists() and time.time() - t0 < 20:
        time.sleep(0.02)
    return out.read_bytes() if out.exists() else None


def poke(pid, addr, raw):
    Path(f"/tmp/nid_cmd_{pid}").write_text(f"poke {addr:x} {raw.hex()}\n")
    time.sleep(0.2)


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
    elif cmd == "ping":
        print(ping(_game_pid(int(sys.argv[2]))))
    else:
        print(__doc__)
