#!/usr/bin/env python3
"""Stop the processes of one farm, by pid, as listed in <farm_dir>/procs.json.

Usage: stop_scoped.py <farm_dir> [--dry-run] [--force]

procs.json: {"<i>": {"wrapper": <pid>, "display": ":<n>"}}

For each wrapper pid, its process group is collected. Every pid is checked before
any signal: its real uid must equal ours, and its /proc/<pid>/environ must carry
the farm path (equal to it, or below it). Pids that fail are printed as REFUSED
and never signalled. Nothing is killed by name.

Prints every target and the count first. More than 50 targets need --force.
SIGTERM first; survivors get SIGKILL after 5 s (re-checked before the kill).
--dry-run prints the plan and exits 0 without signalling.
"""
import argparse
import json
import os
import signal
import sys
import time

MAX_WITHOUT_FORCE = 50
GRACE_S = 5.0


def proc_state(pid):
    """Return (uid, state) from /proc/<pid>/status, or None if the process is gone."""
    try:
        with open(f"/proc/{pid}/status") as f:
            fields = dict(line.split(":", 1) for line in f if ":" in line)
    except (FileNotFoundError, ProcessLookupError):
        return None
    return int(fields["Uid"].split()[0]), fields["State"].split()[0]


def verify(pid, farm):
    """Return (True, '') if pid is ours and carries the farm path; (False, why) if refused;
    (None, 'gone') if the process no longer exists or is a zombie."""
    st = proc_state(pid)
    if st is None or st[1] == "Z":
        return None, "gone"
    uid, _ = st
    if uid != os.getuid():
        return False, f"uid {uid} is not ours ({os.getuid()})"
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            env = f.read().split(b"\0")
    except PermissionError:
        return False, "environ not readable"
    except FileNotFoundError:
        return None, "gone"
    for entry in env:
        if b"=" not in entry:
            continue
        value = entry.split(b"=", 1)[1].decode(errors="replace")
        if value == farm or value.startswith(farm + "/"):
            return True, ""
    return False, f"environ has no farm path {farm}"


def group_members(pgid):
    pids = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                data = f.read()
        except OSError:
            continue
        # comm may contain spaces or parens: split after the last ')'
        fields = data.rsplit(")", 1)[1].split()
        if int(fields[2]) == pgid:  # fields: state, ppid, pgrp
            pids.append(int(name))
    return pids


def collect(farm, procs):
    """Return (targets, refused). targets: list of (pid, instance, role)."""
    targets, refused, seen = [], [], set()
    for inst in sorted(procs, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0, k)):
        wrapper = int(procs[inst]["wrapper"])
        ok, why = verify(wrapper, farm)
        if ok is None:
            print(f"GONE instance={inst} pid={wrapper}")
            continue
        if not ok:
            refused.append((wrapper, inst, why))
            continue
        try:
            pgid = os.getpgid(wrapper)
        except ProcessLookupError:
            print(f"GONE instance={inst} pid={wrapper}")
            continue
        if pgid == os.getpgrp():
            refused.append((wrapper, inst, "shares this script's process group"))
            continue
        if wrapper not in seen:
            seen.add(wrapper)
            targets.append((wrapper, inst, "wrapper"))
        for pid in group_members(pgid):
            if pid in seen:
                continue
            ok, why = verify(pid, farm)
            if ok is None:
                continue
            seen.add(pid)
            if ok:
                targets.append((pid, inst, f"group of {wrapper}"))
            else:
                refused.append((pid, inst, f"group of {wrapper}: {why}"))
    return targets, refused


def alive(pid):
    st = proc_state(pid)
    return st is not None and st[1] != "Z"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("farm_dir")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    farm = os.path.realpath(args.farm_dir)
    try:
        with open(os.path.join(farm, "procs.json")) as f:
            procs = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cannot read {farm}/procs.json: {e}", file=sys.stderr)
        return 2

    targets, refused = collect(farm, procs)
    for pid, inst, why in refused:
        print(f"REFUSED pid={pid} instance={inst} reason={why}")
    for pid, inst, role in targets:
        print(f"TARGET pid={pid} instance={inst} role={role}")
    print(f"count={len(targets)} pids={[t[0] for t in targets]}")

    if len(targets) > MAX_WITHOUT_FORCE and not args.force:
        print(f"refusing: {len(targets)} targets > {MAX_WITHOUT_FORCE}; rerun with --force", file=sys.stderr)
        return 3
    if args.dry_run:
        print("dry-run: no signal sent")
        return 0

    for pid, inst, role in targets:
        ok, why = verify(pid, farm)
        if ok:
            os.kill(pid, signal.SIGTERM)
            print(f"SIGTERM pid={pid} instance={inst}")
        else:
            print(f"SKIP pid={pid} instance={inst} reason={why or 'gone'}")

    deadline = time.time() + GRACE_S
    while time.time() < deadline and any(alive(p) for p, _, _ in targets):
        time.sleep(0.2)

    for pid in [p for p, _, _ in targets if alive(p)]:
        ok, why = verify(pid, farm)
        if ok:
            os.kill(pid, signal.SIGKILL)
            print(f"SIGKILL pid={pid} (still alive after {GRACE_S:.0f}s)")
        else:
            print(f"SKIP-KILL pid={pid} reason={why or 'gone'}")

    still = [p for p, _, _ in targets if alive(p)]
    for pid in still:
        print(f"STILL-ALIVE pid={pid}")
    print(f"stopped={len(targets) - len(still)} still_alive={len(still)} refused={len(refused)}")
    return 2 if (refused or still) else 0


if __name__ == "__main__":
    sys.exit(main())
