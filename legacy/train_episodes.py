"""Episode-managed parallel GA on the real game state (no vision).

Keeps 3 Nidhogg instances inside **live matches**:
  * each instance is owned by one worker thread;
  * a per-instance episode manager detects the end of a match (both fighters
    gone from the state file, or the board frozen), presses Enter to dismiss
    the stats screen, and re-runs the verified match-entry path;
  * a hung instance (stale state, dead process) is killed and relaunched
    without stalling the other two.

Individuals (5-param policies) are round-robined over the instances so three
run at once in wall-clock overlap. Reward = 3*(their deaths) - 2*(my deaths)
+ advance/100, advance = (best_me - start_me) - (start_them - worst_them).

Every individual is logged to /tmp/nid_train_state.jsonl with the fields the
video builder uses (fitness, my_deaths, their_deaths, advance, params,
trace, tag g<N>i<M>).

usage: python train_episodes.py --gens 10 --pop 10 --window 25 --instances 3
"""
import argparse
import json
import os
import random
import subprocess
import threading
import time

import numpy as np

import agent as A

HERE = os.path.dirname(os.path.abspath(__file__))
APP = "/Users/ruggsea/Library/Application Support/Steam/steamapps/common/Nidhogg/Nidhogg.app/Contents/MacOS/Nidhogg"
DYLD = os.path.join(HERE, "hook", "inject.dylib")
PREFS = os.path.expanduser("~/Library/Application Support/com.messhof.nidhogg/prefs.ini")

STATE = "/tmp/nid_state_{}.txt"
KEYS = "/tmp/nid_keys_{}.txt"
SPEED = "/tmp/nid_speed_{}.txt"
LOG_PATH = "/tmp/nid_train_state.jsonl"
OUT_LOG = "/tmp/nid_out_i{}.log"

SPAWN_JUMP = 200.0        # px: an x teleport this large is a respawn/death
EPOCH = 1.5               # s: both fighters missing for this long -> match over
FREEZE = 4.5              # s: board frozen this long -> match over (fallback)
STALE = 4.0               # s: state file this old -> instance hung
MATCH_READY_TO = 35.0     # s: max to wait for fighters after an entry sequence

# Verified match-entry path (task brief): 8x Up wraps to the top of the menu,
# then Down to SINGLE PLAYER, Enter, Down to TRAINING, 4x Enter.
ENTRY = [(38, 0.3)] * 8 + [(40, 1.0), (13, 2.5), (40, 1.5), (13, 2.5),
                           (13, 2.5), (13, 3.0), (13, 4.0)]

BOOT_WAIT = 16.0          # s between launch and the first key

_lock = threading.Lock()


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------- instance mgmt
_procs = {}               # iid -> Popen
_start = {}               # iid -> launch time (monotonic)
_ever_have = {}           # iid -> True once this process has shown players


def clean_files(iid):
    for stem in ("nid_keys", "nid_speed", "nid_room", "nid_state", "nid_inject", "nid_out_i"):
        p = f"/tmp/{stem}_{iid}.txt" if stem != "nid_out_i" else f"/tmp/nid_out_i{iid}.log"
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def launch_instance(iid):
    clean_files(iid)
    proc = subprocess.Popen(
        [APP],
        env=dict(os.environ, NID_ID=str(iid), SteamAppId="94400",
                 NID_QUIET="1", NID_FOCUS="1", NID_MAN="1", NID_THREAD="1",
                 DYLD_INSERT_LIBRARIES=DYLD),
        stdout=open(OUT_LOG.format(iid), "w"),
        stderr=subprocess.STDOUT, start_new_session=True)
    _procs[iid] = proc
    _start[iid] = time.monotonic()
    _ever_have[iid] = False
    with open(SPEED.format(iid), "w") as f:
        f.write("300\n")
    log(f"inst {iid}: launched pid {proc.pid}")


def kill_instance(iid):
    """SIGKILL and reap (poll() reaps zombies; os.kill(pid,0) lies about them)."""
    proc = _procs.get(iid)
    if proc and proc.poll() is None:
        pid = proc.pid
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        for _ in range(20):
            if proc.poll() is not None:
                break
            time.sleep(0.25)
    if proc:
        try:
            proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass


def instance_alive(iid):
    proc = _procs.get(iid)
    return bool(proc) and proc.poll() is None


def kill_all_games():
    """Make sure no Nidhogg is running before we start (stale instances would
    fight us over the /tmp control files)."""
    subprocess.run(["pkill", "-9", "-f", "MacOS/Nidhogg"],
                   capture_output=True)
    time.sleep(1.5)


# ----------------------------------------------------------------- state
def read_state(iid):
    """Returns (dict|None, ok, stale). None means the file says no players."""
    try:
        mtime = os.path.getmtime(STATE.format(iid))
        with open(STATE.format(iid)) as f:
            vals = f.read().split()
        stale = (time.time() - mtime) > STALE
        if len(vals) < 6:
            return None, True, stale
        o154x, o154y, p242x, p242y, h1, h2 = (float(v) for v in vals[:6])
        if not (h1 and h2):
            return None, True, stale
        return {"them_x": o154x, "them_y": o154y, "me_x": p242x, "me_y": p242y,
                "have154": int(h1), "have242": int(h2)}, True, stale
    except OSError:
        return None, False, True


def raw_have(iid):
    try:
        with open(STATE.format(iid)) as f:
            vals = f.read().split()
        if len(vals) < 6:
            return False
        return float(vals[4]) and float(vals[5])
    except (OSError, ValueError):
        return False


def press(iid, code, hold=0.0):
    if isinstance(code, tuple):
        for c in code:
            with open(KEYS.format(iid), "w") as f:
                f.write(f"{c}\n")
            time.sleep(0.03)
        return
    with open(KEYS.format(iid), "w") as f:
        f.write(f"{code}\n")
    if hold:
        time.sleep(hold)


class HangError(Exception):
    pass


# ------------------------------------------------------------ match management
def run_entry(iid):
    log(f"inst {iid}: match-entry sequence")
    for code, wait in ENTRY:
        press(iid, code)
        time.sleep(wait)


def restart_instance(iid, why):
    """Kill, relaunch, boot, entry. Returns True if a match was reached."""
    log(f"inst {iid}: RESTART ({why})")
    kill_instance(iid)
    time.sleep(1.0)
    launch_instance(iid)
    time.sleep(BOOT_WAIT)
    run_entry(iid)
    return wait_for_match(iid, MATCH_READY_TO)


def wait_for_match(iid, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, ok, stale = read_state(iid)
        if st is not None and not stale:
            _ever_have[iid] = True
            return True
        if not instance_alive(iid):
            return False
        time.sleep(0.4)
    return False


def recover_match(iid):
    """Dismiss the stats screen and re-enter a match. No restart unless botched."""
    log(f"inst {iid}: match over -> dismiss + re-enter")
    press(iid, 13)                 # Enter: dismiss WINNER/PRESS-ENTER screen
    time.sleep(2.5)
    run_entry(iid)
    if wait_for_match(iid, MATCH_READY_TO):
        return
    log(f"inst {iid}: entry after stats screen did not land; restarting")
    restart_instance(iid, "re-entry failed")


def ensure_match(iid):
    """Before a new individual: make sure this instance is in a live match.
    Never raises; returns True/False. May take ~2 min on a broken instance
    (3 attempts, each entry + restart)."""
    for attempt in range(3):
        if instance_alive(iid) and raw_have(iid):
            st, ok, stale = read_state(iid)
            if ok and not stale and st is not None:
                return True
        if not instance_alive(iid):
            log(f"inst {iid}: process dead at ensure (attempt {attempt + 1}); relaunching")
            if restart_instance(iid, "dead at ensure"):
                return True
            continue
        # a freshly launched game needs ~16 s before the menu answers keys
        uptime = time.monotonic() - _start.get(iid, time.monotonic())
        if uptime < BOOT_WAIT:
            time.sleep(BOOT_WAIT - uptime)
        # alive but fighters absent: dismiss a leftover stats screen, but only
        # if this process has actually played a match (else a stray 13 would
        # open the default menu item and break the entry path)
        if _ever_have.get(iid):
            press(iid, 13)
            time.sleep(2.0)
        run_entry(iid)
        if wait_for_match(iid, MATCH_READY_TO):
            return True
        if restart_instance(iid, "entry failed at ensure"):
            return True
    log(f"inst {iid}: could not reach a match after 3 attempts")
    return False


# ------------------------------------------------------------------ policy
def act(params, st, rng):
    dx = st["them_x"] - st["me_x"]
    toward = 68 if dx > 0 else 65             # D / A
    away = 65 if dx > 0 else 68
    if abs(dx) > params["engage"]:
        if rng.random() < params["jump"]:
            return 71                         # G jump
        return toward
    if rng.random() < params["aggr"]:
        aim = {0: 83, 1: 87, 2: 87}[params["aim"]]
        return (aim, 70)                      # aim (S/W) then F attack
    if rng.random() < params["retreat"]:
        return away
    return 87 if params["aim"] >= 1 else 83


# ------------------------------------------------------------------ episode
def run_individual(iid, params, seconds, seed, tag):
    """One fixed wall-clock window on one instance; recovers matches mid-window."""
    rng = random.Random(seed)
    t0 = time.time()
    trace = []
    mine = theirs = 0
    prev = None
    last_seen_st = time.time()          # last time we had a fresh usable read
    last_live = time.time()             # last time we saw both fighters moving
    last_motion = time.time()           # last time any coord changed
    last_coords = None
    no_have_since = None                # when both-have-0 streak started

    while time.time() - t0 < seconds:
        st, ok, stale = read_state(iid)
        now = time.time()
        if not instance_alive(iid):
            raise HangError(f"inst {iid}: game process died during window")

        if not ok or stale:
            if now - last_seen_st > STALE + 1.0:
                raise HangError(f"inst {iid}: state file stale for {now-last_seen_st:.0f}s")
            time.sleep(0.1)
            continue

        if st is None:
            # both fighters gone from the state file
            if no_have_since is None:
                no_have_since = now
            elif now - no_have_since >= EPOCH and now - last_live < 90:
                recover_match(iid)
                prev = None
                no_have_since = None
                last_live = now
                last_motion = now
                last_coords = None
            time.sleep(0.1)
            continue
        no_have_since = None
        last_seen_st = now

        coords = (st["me_x"], st["me_y"], st["them_x"], st["them_y"])
        moved = last_coords is not None and any(
            abs(a - b) > 1.0 for a, b in zip(coords, last_coords))
        if moved:
            last_motion = now
            last_live = now
        elif now - last_motion > FREEZE and now - last_live < 90:
            # board frozen but file alive: match over and state stale-sticky
            recover_match(iid)
            prev = None
            last_motion = now
            last_live = now
            last_coords = None
            time.sleep(0.2)
            continue
        last_coords = coords

        if prev is not None:
            if abs(st["me_x"] - prev["me_x"]) > SPAWN_JUMP:
                mine += 1
            if abs(st["them_x"] - prev["them_x"]) > SPAWN_JUMP:
                theirs += 1
        prev = dict(st)

        trace.append([round(now - t0, 2), round(st["me_x"]), round(st["them_x"])])
        press(iid, act(params, st, rng))
        time.sleep(0.05)

    start_me = trace[0][1] if trace else 0.0
    start_them = trace[0][2] if trace else 0.0
    best_me = max((t[1] for t in trace), default=0.0)
    worst_them = min((t[2] for t in trace), default=0.0)
    advance = (best_me - start_me) - (start_them - worst_them)
    fit = 3.0 * theirs - 2.0 * mine + advance / 100.0
    return {"fitness": round(fit, 2), "advance": round(advance, 1),
            "my_deaths": mine, "their_deaths": theirs,
            "params": params, "trace": trace, "tag": tag}


def zero_rec(params, tag):
    return {"fitness": -100.0, "advance": 0.0, "my_deaths": 0,
            "their_deaths": 0, "params": params, "trace": [], "tag": tag}


def log_rec(rec):
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(rec) + "\n")


# ------------------------------------------------------------------- GA
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=10)
    ap.add_argument("--pop", type=int, default=10)
    ap.add_argument("--window", type=float, default=25.0)
    ap.add_argument("--instances", type=int, default=3)
    ap.add_argument("--seed", type=int, default=23)
    args = ap.parse_args()

    kill_all_games()
    for iid in range(args.instances):
        launch_instance(iid)                   # staggered to ease Steam contention
        time.sleep(2.0 + iid)
    log(f"launched {args.instances} instances; workers self-bootstrap into "
        f"matches, then run the GA ({args.pop} ind x {args.gens} gens, "
        f"{args.window}s windows)")

    jobs, results, stop = [], {}, threading.Event()
    counter = [0]

    def pop_job():
        with _lock:
            return jobs.pop(0) if jobs else None

    def worker(iid):
        while not stop.is_set():
            item = pop_job()
            if item is None:
                time.sleep(0.25)
                continue
            tag, params, seed_ = item
            rec = None
            for attempt in range(2):
                try:
                    if not ensure_match(iid):
                        rec = zero_rec(params, tag)
                        log(f"inst {iid}: {tag} zeroed, instance unavailable")
                        break
                    rec = run_individual(iid, params, args.window, seed_, tag)
                    break
                except HangError as e:
                    log(str(e))
                    if not restart_instance(iid, str(e)):
                        rec = zero_rec(params, tag)
                        log(f"inst {iid}: {tag} zeroed, restart failed")
                        break
                    continue
            if rec is None:
                log(f"inst {iid}: {tag} failed twice, logging zero")
                rec = zero_rec(params, tag)
            rec["instance"] = iid
            with _lock:
                results[tag] = rec
                counter[0] += 1
            log_rec(rec)
            with _lock:
                print(f"gen {tag[1]} ind {tag[3]}: fit={rec['fitness']:.1f} "
                      f"their={rec['their_deaths']} mine={rec['my_deaths']} "
                      f"adv={rec['advance']:.0f} (inst {iid})", flush=True)

    threads = [threading.Thread(target=worker, args=(iid,), daemon=True)
               for iid in range(args.instances)]
    for t in threads:
        t.start()

    rng = random.Random(args.seed)
    pop = [A.rand_params(rng) for _ in range(args.pop)]
    best = None

    for gen in range(args.gens):
        with _lock:
            before = counter[0]
            for i, p in enumerate(pop):
                jobs.append((f"g{gen}i{i}", p, args.seed + gen * 97 + i))
        while True:
            with _lock:
                done_here = counter[0] - before
            if done_here >= args.pop:
                break
            time.sleep(0.5)

        with _lock:
            gen_results = [results[f"g{gen}i{i}"] for i in range(args.pop)]
        gen_results.sort(key=lambda r: -r["fitness"])
        best = gen_results[0]
        mean = float(np.mean([r["fitness"] for r in gen_results]))
        print(f"== gen {gen} best {best['fitness']:.1f} mean {mean:.1f} "
              f"(their {best['their_deaths']} mine {best['my_deaths']})", flush=True)

        elite = [r["params"] for r in gen_results[: max(2, args.pop // 3)]]
        nxt = list(elite)
        ngen_rng = random.Random(args.seed + gen * 503)
        while len(nxt) < args.pop:
            a, b = ngen_rng.sample(elite, 2) if len(elite) > 1 else (elite[0], elite[0])
            nxt.append(A.mutate(A.crossover(a, b, ngen_rng), ngen_rng))
        pop = nxt

    stop.set()
    for t in threads:
        t.join(timeout=5)
    if best:
        print("best params:", json.dumps(best["params"]), flush=True)
        print(f"best tag {best['tag']} fit {best['fitness']} "
              f"(their {best['their_deaths']}, mine {best['my_deaths']}, "
              f"advance {best['advance']})", flush=True)
    log("DONE")


if __name__ == "__main__":
    main()