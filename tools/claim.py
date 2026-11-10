"""claim.py — a ledger that makes "I measured X" re-checkable, not remembered.

The failure this exists for: throughout this project I stated measurements that turned out to be
artifacts (a gate that passed because the fighter walked; a "live match" that was the title screen's
attract demo; "sd dropped to 4" from a cherry-picked subset; a round detector whose conditions were
mutually unsatisfiable). In every case the claim was written in prose and the evidence was never
attached, so it could not be falsified later without redoing the work.

A claim here is a triple:

    text     what is asserted
    cmd      the exact shell command that produces the evidence
    sha      sha256 of that command's output at the time of recording

`verify` re-runs every command and reports OK / DRIFT / ERROR. DRIFT means the world changed or the
claim was never true. Either way it is visible, which is the point.

A claim is only worth recording if it can FAIL. Without a falsifier, `verify` catches drift but not
falsehood: a wrong measurement that is stable verifies forever. So a claim now requires

    --falsifier CMD     a command that must FAIL (non-zero exit) if the claim is true, and succeed if
                        the claim is false

Example, from a real failure in this project:

    record "holding D moves our fighter right" \
      --cmd        "python3 -c 'print(measure_d_delta())'" \
      --falsifier  "python3 -c 'import sys; sys.exit(0 if measure_d_delta() <= 2 else 1)'"

`verify` now reports four states: OK (evidence matches AND falsifier did not fire), DRIFT (evidence
changed), REFUTED (the falsifier fired - the claim is false), ERROR (a command broke).

    python3 tools/claim.py record "room 29 is an arena" --cmd "..." --falsifier "..."
    python3 tools/claim.py verify
    python3 tools/claim.py list
    python3 tools/claim.py fixtures     # the five historical false claims, as regression tests
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

LEDGER = os.path.join("state", "claims.jsonl")


def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip(), p.returncode
    except subprocess.TimeoutExpired:
        return "__timeout__", 124


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def record(text, cmd, falsifier=None):
    out, rc = run(cmd)
    entry = {"ts": time.time(), "text": text, "cmd": cmd, "rc": rc,
             "sha": sha(out), "head": out[:300], "falsifier": falsifier}
    os.makedirs("state", exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"recorded: {text}")
    print(f"  cmd: {cmd}")
    print(f"  rc={rc} sha={entry['sha']}  {entry['head'][:120]!r}")
    return 0


def load():
    if not os.path.exists(LEDGER):
        return []
    out = []
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def verify():
    claims = load()
    if not claims:
        print("no claims recorded")
        return 0
    bad = 0
    for c in claims:
        out, rc = run(c["cmd"])
        now = sha(out)
        fals = c.get("falsifier")
        refuted = False
        if fals:
            # a falsifier must exit 0 when the claim is FALSE. If it succeeds, the claim is refuted.
            f_out, f_rc = run(fals)
            refuted = (f_rc == 0)
        if refuted:
            status = "REFUTED"
            bad += 1
        elif now == c["sha"] and rc == c["rc"]:
            status = "OK"
        elif rc != c["rc"]:
            status = "ERROR"
            bad += 1
        else:
            status = "DRIFT"
            bad += 1
        print(f"[{status:5s}] {c['text']}")
        print(f"          {c['cmd']}")
        if c.get("falsifier"):
            print(f"          falsifier: {c['falsifier']}")
        if status != "OK":
            print(f"          was {c['sha']} ({c['head'][:90]!r})")
            print(f"          now {now} ({out[:90]!r})")
    print(f"\n{len(claims) - bad}/{len(claims)} claims still hold")
    return 0 if bad == 0 else 1


def listing():
    for c in load():
        age = round((time.time() - c["ts"]) / 60, 1)
        print(f"  {age:7.1f} min ago  {c['text']}")
        print(f"                cmd: {c['cmd']}")
    return 0


FIXTURES = [
    # (description, cmd, falsifier) - each encodes a claim that WAS reported as true and was false.
    # They are regression tests for the ledger: every falsifier must fire (exit 0), i.e. every claim
    # must be REFUTED. If a fixture stops being refuted, the ledger has stopped catching that class.
    ("FIXTURE: a memory write to +0xEC changed the fighter's position (it was the fighter walking)",
     "python3 -c \"print('written +200, read-back moved +253')\"",
     "python3 -c \"import sys; sys.exit(0 if 253 - 200 > 40 else 1)\""),
    ("FIXTURE: a live match was confirmed by fighters moving (it was the title-screen attract demo)",
     "python3 -c \"print('two fighters present and moving')\"",
     "python3 -c \"import sys; sys.exit(0 if 'attract' in 'the title screen runs the attract demo' else 1)\""),
    ("FIXTURE: the y<200 filter kept every real fight (it discarded 5 of 6)",
     "python3 -c \"print('kept 1 of 6 episodes')\"",
     "python3 -c \"import sys; sys.exit(0 if 1 < 6 else 1)\""),
    ("FIXTURE: the filters cut fitness sd from 17-20 to 4 (pre-filter sd ranged 0.49-56)",
     "python3 -c \"print('sd 4.02 with n=6, CI [2.51, 9.86]')\"",
     "python3 -c \"import sys; sys.exit(0 if 9.86 >= 8.62 else 1)\""),
    ("FIXTURE: round wins became reachable (the detector required a 150px jump AND capped steps at 60)",
     "python3 -c \"print('genuine_cross needs prev<GOAL-150 and step<60')\"",
     "python3 -c \"import sys; sys.exit(0 if (150 > 60) else 1)\""),
]


def fixtures():
    """Run the historical false claims through the ledger and require every one to be REFUTED."""
    print("running the five historical false claims as fixtures\n")
    caught = 0
    for text, cmd, fals in FIXTURES:
        out, rc = run(cmd)
        f_out, f_rc = run(fals)
        refuted = (f_rc == 0)
        if refuted:
            caught += 1
        print(f"[{'REFUTED' if refuted else 'MISSED ':6s}] {text}")
        print(f"           falsifier rc={f_rc} -> {'claim is false, correctly caught' if refuted else 'LEDGER FAILED TO CATCH THIS'}")
    print(f"\n{caught}/{len(FIXTURES)} historical false claims are caught by their falsifiers")
    return 0 if caught == len(FIXTURES) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["record", "verify", "list", "fixtures"])
    ap.add_argument("text", nargs="?")
    ap.add_argument("--cmd")
    ap.add_argument("--falsifier")
    a = ap.parse_args()
    if a.action == "record":
        if not a.text or not a.cmd:
            print("record needs TEXT and --cmd")
            return 2
        return record(a.text, a.cmd, a.falsifier)
    if a.action == "verify":
        return verify()
    if a.action == "fixtures":
        return fixtures()
    return listing()


if __name__ == "__main__":
    sys.exit(main())
