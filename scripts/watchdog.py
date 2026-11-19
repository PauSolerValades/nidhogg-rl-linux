#!/usr/bin/env python3
"""Report how fresh each instance's state file is. Restarts nothing.

Usage: watchdog.py <farm_dir> <state_file_pattern> [--timeout 120]

state_file_pattern: a path (relative to farm_dir unless absolute) in which
"{instance}" is replaced by each instance key from <farm_dir>/procs.json.
Prints one JSON line per instance: {"instance", "stale_seconds", "status"},
status = ok | stale | missing. Exit 0 if all ok, 1 if any stale or missing.
"""
import argparse
import json
import os
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("farm_dir")
    ap.add_argument("state_file_pattern")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    farm = os.path.realpath(args.farm_dir)
    try:
        with open(os.path.join(farm, "procs.json")) as f:
            procs = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cannot read {farm}/procs.json: {e}", file=sys.stderr)
        return 2
    if not procs:
        print("procs.json lists no instances", file=sys.stderr)
        return 1

    now = time.time()
    bad = False
    for inst in sorted(procs, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0, k)):
        path = os.path.join(farm, args.state_file_pattern.replace("{instance}", inst))
        try:
            age = now - os.stat(path).st_mtime
        except FileNotFoundError:
            age = None
        if age is None:
            status = "missing"
        elif age > args.timeout:
            status = "stale"
        else:
            status = "ok"
        bad = bad or status != "ok"
        print(json.dumps({
            "instance": inst,
            "stale_seconds": None if age is None else round(age, 1),
            "status": status,
        }))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
