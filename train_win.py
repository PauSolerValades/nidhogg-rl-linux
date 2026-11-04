"""Win-reward trainer: fitness = rounds won / lost / matches won.

Round logic, all from published state (no vision):
  * a single player's x teleporting => that player died this round
  * BOTH teleporting at once        => the round ended and reset
  * the round goes to whoever did NOT die
  * first to 3 round wins takes the match (Nidhogg is best-of-5)

Fitness = 10*rounds_won - 6*rounds_lost + 30*match_won + small shaping so early
random policies still get a gradient (advance toward the enemy goal).
"""
import argparse
import json
import os
import threading
import time

import numpy as np

import neuro
import train_state as TS

LOG = "/tmp/nid_win_train.jsonl"
RESET_LOCK = threading.Lock()


def reset_all(mgrs, log=print):
    """Kill every game process and relaunch the whole pool, serialized.

    Per-instance restarts orphaned processes (the runner re-execs itself via
    SteamAPI_RestartAppIfNecessary), which is how 2 instances became 10-19 games.
    A global sweep under a lock keeps the count exactly equal to len(mgrs).
    """
    # MUST use the same lock as InstanceManager.restart(), otherwise a global sweep
    # can kill a game another instance has just launched, which then reports
    # "process dead", restarts, and triggers another sweep (the restart cascade).
    with TS._RESTART_LOCK:
        log("  [reset] sweeping all game processes and relaunching the pool")
        os.system('pkill -f "MacOS/Nidhogg"')
        # WAIT for them to actually die before relaunching: relaunching while the
        # old ones were still exiting is what made the pool oscillate 2 -> 8.
        for _ in range(30):
            if not TS.InstanceManager._nidhogg_pids():
                break
            time.sleep(0.5)
        stragglers = TS.InstanceManager._nidhogg_pids()
        if stragglers:
            log(f"  [reset] {len(stragglers)} stragglers, SIGKILL")
            os.system('pkill -9 -f "MacOS/Nidhogg"')
            time.sleep(2)
        for m in mgrs:
            m.close()
        for m in mgrs:
            m.launch()
        time.sleep(TS.BOOT_WAIT)
        for m in mgrs:
            m.run_entry()
        for m in mgrs:
            m.wait_for_match()
            m.needs_reset = False
        time.sleep(2)
SPAWN_JUMP = 90.0   # px between consecutive ~70 Hz samples. Normal motion is <20 px
                   # per sample, so 90 catches a respawn teleport (300 missed the
                   # respawns that land close to the death spot)
ROUNDS_TO_WIN = 3
HOLD_TICKS = 8   # MEASURED: 8 -> advance 123-134 px per episode; 20 -> only 14-24 px.
                 # A longer hold makes the agent commit into the CPU and get stuck, so
                 # the intuitive 'be more decisive' change was wrong. Keep 8.   # 8 ticks (~0.16 s) made the agent change direction so often it
                 # travelled almost nowhere: advance varied only 11 px across a whole
                 # 70 s episode. 20 gives a sustained commitment.          # ~150 ms of held action per decision
GOAL_X = 1650.0        # our goal line is on the right
GOAL_X_OPP = 250.0    # the CPU goal line is on the left


def read_state(iid):
    try:
        v = open(TS.STATE.format(iid)).read().split()
        if len(v) < 6:
            return None
        o154x, o154y, y242x, y242y, h1, h2 = (float(x) for x in v[:6])
        if not (h1 and h2):
            return None
        # GATE: a (0,0) pair is a not-yet-initialised / frozen instance, not a
        # fighter standing at the goal. Without this the goal-crossing detector
        # counted every blank sample as a round loss (157/episode once).
        if y242x <= 1.0 and o154x <= 1.0:
            return None
        if not (0.0 <= y242x <= 3000.0 and 0.0 <= o154x <= 3000.0):
            return None
        return {"them_x": o154x, "them_y": o154y, "me_x": y242x, "me_y": y242y}
    except (OSError, ValueError):
        return None


def read_raw(iid):
    """Raw published state, flags included: (o_x, o_y, y_x, y_y, have_o, have_y)."""
    try:
        v = open(TS.STATE.format(iid)).read().split()
        if len(v) < 6:
            return None
        return (float(v[0]), float(v[1]), float(v[2]), float(v[3]),
                float(v[4]), float(v[5]))
    except (OSError, ValueError):
        return None


def play(mgr, w, seconds, seed, tag, log=print):
    if not mgr.ensure_match():
        # Do NOT restart here: the generation loop does one global reset instead.
        return {"fitness": -100.0, "rounds_won": 0, "rounds_lost": 0,
                "match_won": 0, "trace": [], "tag": tag, "no_match": True}

    rng = np.random.default_rng(seed)
    # A match is ONE round. After it ends the fighters stay on screen but inert, so
    # ensure_match() sees "live" and every later individual reuses the same dead match -
    # measured: 54 episodes ran on a single entry, and all 12 individuals in a generation
    # scored an identical -19.11 because they saw identical, action-independent state.
    # Re-enter whenever the match is not actually moving.
    # SPEED. The game sat at 9.5 fps during play because the speed control file was never
    # written (the only caller was the entry path, which the cached-entry route skips).
    # At that rate a 120 s episode yielded 116-143 state samples instead of ~2400, so with
    # HOLD_TICKS=8 each decision lasted ~8 real seconds and the agent had no control.
    # Setting it per episode makes it independent of which entry branch ran.
    try:
        mgr._raise_speed()
    except Exception:
        pass
    st0 = read_state(mgr.iid)
    inert = st0 is None
    if not inert:
        xs = []
        tt = time.time()
        while time.time() - tt < 1.5:
            s2 = read_state(mgr.iid)
            if s2:
                xs.append(s2["them_x"])
            time.sleep(0.1)
        inert = len(xs) < 4 or (max(xs) - min(xs)) < 2.0
    if inert:
        mgr.press(27); time.sleep(1.5)
        mgr.press(27); time.sleep(1.5)
        mgr.run_entry()

    t0 = time.time()
    trace = []
    prev = None
    held_code = None
    hold_left = 0
    died_me = died_them = False          # deaths since the current round began
    me_deaths = them_deaths = 0          # TOTAL deaths this episode (for shaping)
    prev_flags = None
    rounds_won = rounds_lost = 0
    me_crossed = them_crossed = False
    me_armed = them_armed = False
    last_round_t = 0.0
    matches_won = matches_lost = 0
    match_rounds_won = match_rounds_lost = 0
    best_me = start_me = best_them = worst_them = None
    start_them = None
    next_accept_t = 0.0                  # when to press Enter to start the next round

    def end_round(log=log):
        nonlocal died_me, died_them, rounds_won, rounds_lost
        nonlocal match_rounds_won, match_rounds_lost, matches_won, matches_lost
        # ROUNDS ARE NO LONGER AWARDED HERE. This path attributed round wins to the
        # teleport-based death detector, and that detector is broken: one 120 s episode
        # recorded kills=485 deaths=402 (every position jump counts as a death). That
        # produced "roundsW 7 / roundsL 9" in a generation whose fighter never got past
        # x=604 on a 1650 goal line - phantom wins, exactly like the earlier 10-0.
        # Rounds are now counted ONLY from genuine goal-line crossings below.
        died_me = died_them = False
        if match_rounds_won >= ROUNDS_TO_WIN:
            matches_won += 1
            match_rounds_won = match_rounds_lost = 0
        elif match_rounds_lost >= ROUNDS_TO_WIN:
            matches_lost += 1
            match_rounds_won = match_rounds_lost = 0

    saw_player = False
    gone_since = None
    accept_tries = [0]
    real_samples = 0
    sum_me = 0.0
    min_abs_dx = None
    while time.time() - t0 < seconds:
        # DEATH = the fighter's existence flag drops. read_state() deliberately
        # returns None when a flag is 0, so this check MUST run before that gate -
        # otherwise the death is never observed (measured: 0 deaths in 10 episodes).
        raw = read_raw(mgr.iid)
        if raw is not None and prev_flags is not None:
            if prev_flags[0] > 0.5 and raw[4] < 0.5:
                them_deaths += 1
            if prev_flags[1] > 0.5 and raw[5] < 0.5:
                me_deaths += 1
        if raw is not None:
            prev_flags = (raw[4], raw[5])
        st = read_state(mgr.iid)
        if st is None:
            # once we have seen a live fighter, a sustained absence means the match
            # ended: stop the window and let the manager start a fresh process.
            if saw_player:
                gone_since = gone_since or time.time()
                # 8 s, not 2.5: a ROUND transition also hides both fighters for a
                # moment, and 2.5 s cut every episode off after a single round, so
                # a best-of-5 match only ever yielded one round of signal.
                if time.time() - gone_since > 2.5:
                    # A round just ended. Press accept to start the NEXT round instead
                    # of closing the episode: with one round per episode every episode
                    # was exactly "rounds 0-1", which gives the GA almost no signal.
                    accept_tries[0] += 1
                    if accept_tries[0] <= 2:
                        print(f"  {tag}: round over, accepting next "
                              f"(try {accept_tries[0]})", flush=True)
                        mgr.press(13)
                        gone_since = None
                        time.sleep(1.2)
                        continue
                    print(f"  {tag}: match over, ending window", flush=True)
                    break
            time.sleep(0.05)
            continue
        saw_player = True
        real_samples += 1
        sum_me += st["me_x"]
        adx = abs(st["them_x"] - st["me_x"])
        min_abs_dx = adx if min_abs_dx is None else min(min_abs_dx, adx)
        gone_since = None
        if start_me is None:
            start_me, best_them = st["me_x"], st["them_x"]
            start_them = st["them_x"]
            best_me, worst_them = st["me_x"], st["them_x"]
        best_me = max(best_me, st["me_x"])
        worst_them = min(worst_them, st["them_x"])
        best_them = max(best_them, st["them_x"]) if best_them is not None else st["them_x"]
        max_them = best_them
        if prev is not None:
            me_jump = abs(st["me_x"] - prev["me_x"]) > SPAWN_JUMP
            them_jump = abs(st["them_x"] - prev["them_x"]) > SPAWN_JUMP
            if me_jump and them_jump:
                end_round()                       # full reset: attribute it
                start_me, best_them = st["me_x"], st["them_x"]
                start_them = st["them_x"]
                best_me, worst_them = st["me_x"], st["them_x"]
            elif me_jump:
                died_me = True                    # we respawned => we died
                me_deaths += 1
            elif them_jump:
                died_them = True
                them_deaths += 1

        # WINNING THE ROUND IS CROSSING TO THE FAR END, not a kill. In Nidhogg
        # you win a round by reaching your opponent's goal. Rooms span ~0..1920,
        # so crossing beyond GOAL_X is a round win for whoever crossed.
        # A round is won/lost only on a genuine TRANSITION toward that goal line.
        # A respawning fighter sits at x ~ 0 (the CPU's spawn side), which used to
        # be read as "crossed our goal" and produced 1110 phantom losses in 10
        # episodes. Track approach from deep in the field, then require the cross.
        if st["me_x"] > GOAL_X - 700:
            me_armed = True
        now_t = time.time()
        # A round win must be a GENUINE crossing between consecutive samples, not a
        # respawn that happens to land past the goal line. Measured: a fresh population
        # reported 10 wins in 10 rounds while its fighter never left x=808..897, which
        # is exactly this bug. Requiring prev sample < GOAL_X-150 kills the phantom.
        genuine_cross = (prev is not None and prev["me_x"] < GOAL_X - 150
                         and st["me_x"] >= GOAL_X and now_t - t0 > 3.0)
        if genuine_cross and me_armed and not me_crossed and now_t - last_round_t > 6.0:
            rounds_won += 1; match_rounds_won += 1
            me_crossed = True; me_armed = False
            last_round_t = now_t
            next_accept_t = now_t + 2.5
            if match_rounds_won >= ROUNDS_TO_WIN:
                matches_won += 1
                match_rounds_won = match_rounds_lost = 0
        if st["me_x"] < GOAL_X - 400:
            me_crossed = False
        if st["them_x"] < GOAL_X_OPP + 700:
            them_armed = True
        genuine_cross_them = (prev is not None and prev["them_x"] > GOAL_X_OPP + 150
                              and st["them_x"] <= GOAL_X_OPP and now_t - t0 > 3.0)
        if genuine_cross_them and them_armed and not them_crossed and now_t - last_round_t > 6.0:
            rounds_lost += 1; match_rounds_lost += 1
            them_crossed = True; them_armed = False
            last_round_t = now_t
            next_accept_t = now_t + 2.5
            if match_rounds_lost >= ROUNDS_TO_WIN:
                matches_lost += 1
                match_rounds_won = match_rounds_lost = 0
        if st["them_x"] > GOAL_X_OPP + 400:
            them_crossed = False
        # After a round ends the game waits on a READY screen. Pressing accept starts
        # the next round, which is the only way to get more than ONE round of signal
        # into a 45 s window (measured: every episode was exactly 1 round, 42/42).
        if next_accept_t and time.time() >= next_accept_t:
            mgr.press(13)
            next_accept_t = 0.0
        # relative approach speed, for strike timing (see neuro.obs_vector input 5)
        if prev is not None:
            gap_now = st["them_x"] - st["me_x"]
            gap_prev = prev["them_x"] - prev["me_x"]
            dt = max(1e-3, time.time() - prev.get("_t", time.time()))
            vel = (gap_now - gap_prev) / dt
            st["dx_vel"] = 0.7 * st.get("dx_vel", 0.0) + 0.3 * vel
        st["_t"] = time.time()
        prev = st
        trace.append([round(time.time() - t0, 2), round(st["me_x"]), round(st["them_x"])])
        # ACTION REPEAT: hold each decision for HOLD_TICKS samples. Deciding at
        # 50 Hz meant the aim changed between pressing attack and the swing
        # landing, so no attack ever resolved coherently.
        if hold_left <= 0 or held_code is None:
            held_code = neuro.decide(w, st, rng)
            hold_left = HOLD_TICKS
        hold_left -= 1
        if held_code:
            mgr.press(held_code)
        time.sleep(0.02)

    progress = 0.0
    if start_me is not None:
        progress = ((best_me - start_me) - (best_them - worst_them)) / 100.0
    # NOTE: a kill/death shaping term was tried here and REMOVED. Measured: 0 deaths
    # were detected across 20 episodes even though 10 rounds were lost, because a
    # respawn often lands within SPAWN_JUMP(300 px) of where the fighter died, so the
    # teleport test misses it. A permanently-zero term is noise, not signal. Death
    # detection needs the visibility-gap signal instead (fighter vanishes, then
    # reappears) - that is the next thing to build.
    # DIAGNOSTIC ONLY - never in fitness. Measured: 485 "kills" in one episode from the
    # teleport detector, which would contribute +249 and swamp every real term.
    kills_reward = 0.0
    # TERRITORY IS THE LEARNING SIGNAL. Measured: every individual scored an identical
    # -8.3 because a Training match is ONE round, so the win/loss term is a single bit
    # and the GA has nothing to differentiate on. These continuous terms give a gradient
    # inside that round: ground gained, ground conceded, and how far we got at best.
    advance = 0.0
    conceded = 0.0
    if start_me is not None and best_me is not None:
        # SUSTAINED advance, not peak: using best_me rewarded one lucky frame, and the
        # measured advance sat at 170-182 px over a whole 70 s episode (~2.5 px/s) while
        # holding a direction reaches ~17 px/s. Mean position rewards actually holding
        # ground toward the goal instead of twitching.
        mean_me = sum_me / max(1, real_samples)
        advance = (mean_me - start_me) / 100.0          # px converted to "metres"
        # must use the CPU's START x: best_them is now a running MAX (see pushed below)
        conceded = (start_them - worst_them) / 100.0 if start_them is not None else 0.0
    # GOAL PROXIMITY: with the current window no round resolves (30/30 episodes ended
    # 0-0), so nothing rewarded actually approaching the goal line. This term does, and
    # it is the only path by which a crossing - and therefore a round win - can appear.
    proximity = 0.0
    if best_me is not None:
        proximity = 4.0 * (best_me / float(GOAL_X))
    # PUSH THEM BACK. Measured: running alone gains ~366 px and then gets shoved back to
    # the start, so the only way to hold ground is to win exchanges. Nothing rewarded
    # that: `conceded` only punishes being pushed. This term pays for driving the CPU
    # toward its own goal, which is what attacking is for.
    pushed = 0.0
    if start_them is not None and best_them is not None:
        pushed = (best_them - start_them) / 100.0
    # CLOSE TO STRIKING DISTANCE. Measured: a strike only lands at |dx| <= 22 px
    # (+51 px of push at 22, 0 px at 59), and `pushed` was 0.00 in every episode - the
    # agent never closes. This pays for getting near the opponent, which is the
    # precondition for ever winning an exchange.
    closeness = 0.0
    if min_abs_dx is not None:
        # Weight cut 5.0 -> 1.0. Measured with 5.0: the agent engaged and LOST every
        # round (roundsL 10/10, CPU crossing our line each time) - closing distance was
        # worth more than surviving the contact, so it learned to rush in and die.
        # Closing is a precondition, not the objective; the outcome has to pay more.
        closeness = 1.0 * max(0.0, 1.0 - min_abs_dx / 200.0)
    territory = (2.0 * advance - 4.0 * conceded + proximity
                 + 6.0 * pushed + closeness)
    fitness = (10.0 * rounds_won - 6.0 * rounds_lost
               + 30.0 * matches_won - 20.0 * matches_lost
               + kills_reward
               + float(np.clip(progress, -5, 5))
               + float(np.clip(territory, -12, 12)))
    no_match = real_samples < 20
    rec = {"no_match": no_match, "real_samples": real_samples,
           "advance": round(advance, 2), "conceded": round(conceded, 2),
           "territory": round(territory, 2), "fitness": round(fitness, 2),
           "pushed": round(pushed, 2), "closeness": round(closeness, 2),
           "min_dx": (round(min_abs_dx, 0) if min_abs_dx is not None else None),
           "kills": them_deaths, "deaths": me_deaths, "rounds_won": rounds_won,
           "rounds_lost": rounds_lost, "matches_won": matches_won,
           "matches_lost": matches_lost, "progress": round(progress, 2),
           "trace": trace, "tag": tag, "weights": w.tolist()}
    log(f"  {tag} (inst {mgr.iid}): fit={fitness:.1f} rounds {rounds_won}-{rounds_lost} "
        f"matches {matches_won}-{matches_lost}")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, default=4)
    ap.add_argument("--gens", type=int, default=10)
    ap.add_argument("--pop", type=int, default=16)
    ap.add_argument("--window", type=float, default=45.0)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--init", action="store_true")
    args = ap.parse_args()

    os.environ["NID_ORDERS"] = "1"
    os.system('pkill -f "MacOS/Nidhogg" 2>/dev/null')
    os.system('pkill -f train_win.py 2>/dev/null')
    time.sleep(2)
    # the prefs file is chmod 444 while a run is active (so injected menu keys cannot
    # rewrite the user's settings); unlock before writing, launch() re-locks it.
    try:
        os.chmod(TS.PREFS, 0o644)
    except OSError:
        pass
    with open(TS.PREFS, "w") as f:
        f.write(open(TS.MUTED_PREFS).read())

    pop = neuro.Population(size=args.pop, seed=args.seed)
    # warm start: if a previous run left a best policy, seed the population with it
    import os as _os
    seed_path = "/tmp/nid_best_win.json"
    if args.init and _os.path.exists(seed_path):
        try:
            prev = json.load(open(seed_path))["weights"]
            w0 = np.array(prev, dtype=float)
            if w0.shape[0] == neuro.N_WEIGHTS:
                pop.W[0] = w0
                for i in range(1, 4):
                    pop.W[i] = w0 + np.random.default_rng(args.seed + i).normal(0, 0.06, w0.shape)
                print(f"warm start from previous best (fitness {json.load(open(seed_path)).get('fitness')})", flush=True)
        except Exception as exc:
            print("warm start skipped:", exc, flush=True)
    mgrs = [TS.InstanceManager(iid=i) for i in range(args.instances)]
    for m in mgrs:
        m.launch()
    time.sleep(TS.BOOT_WAIT)
    for m in mgrs:
        m.run_entry()
    for m in mgrs:
        m.wait_for_match()
    # 600 is the measured sweet spot: 226 fps in game, vs 124 at 1200 and 154 at 2000
    for m in mgrs:
        try:
            with open(TS.SPEED.format(m.iid), "w") as f:
                f.write("600\n")
        except OSError:
            pass
    time.sleep(3)

    best_overall = None
    for gen in range(args.gens):
        # process hygiene: the runner re-execs itself, and any missed child would
        # accumulate across restarts. At each generation boundary, if the count has
        # drifted above 2x our instances, sweep everything and let ensure_match
        # relaunch cleanly (it is designed to).
        if any(m.needs_reset for m in mgrs):
            reset_all(mgrs)
            for m in mgrs:
                m.needs_reset = False
        pids = TS.InstanceManager._nidhogg_pids()
        if len(pids) > 2 * len(mgrs) + 2:
            print(f"== sweep: {len(pids)} game processes, resetting", flush=True)
            os.system('pkill -f "MacOS/Nidhogg"')
            time.sleep(3)
        results = []
        threads = []
        for i, w in enumerate(pop.W):
            mgr = mgrs[i % len(mgrs)]
            tag = f"g{gen}i{i}"
            time.sleep(0.15)
            th = threading.Thread(target=lambda m=mgr, ww=w, t=tag:
                                  results.append(play(m, ww, args.window, gen*997+i, t)))
            th.start(); threads.append(th)
        for th in threads:
            th.join()
        good = [r for r in results if not r.get("no_match")]
        if len(good) < len(results):
            # one global reset, then re-run only the individuals that had no match
            missing = [i for i, r in enumerate(results) if r.get("no_match")]
            print(f"== gen {gen}: {len(missing)} individuals had no match, resetting",
                  flush=True)
            reset_all(mgrs)
            for i in missing:
                w = pop.W[i]
                tag = f"g{gen}i{i}"
                results[i] = play(mgrs[i % len(mgrs)], w, args.window,
                                  gen * 997 + i, tag)
            good = [r for r in results if not r.get("no_match")]
        if not good:
            print(f"== gen {gen}: all failed", flush=True)
            continue
        pop.next_gen([r["fitness"] for r in results])
        best = max(good, key=lambda r: r["fitness"])
        mean = float(np.mean([r["fitness"] for r in good]))
        print(f"== gen {gen} best {best['fitness']:.2f} mean {mean:.2f} "
              f"roundsW {sum(r['rounds_won'] for r in good)} "
              f"roundsL {sum(r['rounds_lost'] for r in good)} "
              f"matchW {sum(r['matches_won'] for r in good)}", flush=True)
        if best_overall is None or best["fitness"] > best_overall["fitness"]:
            best_overall = best
        with open("/tmp/nid_win_history.json", "w") as f:
            json.dump({"gen": gen, "best": best["fitness"], "mean": mean}, f)
        for r in results:
            with open(LOG, "a") as f:
                f.write(json.dumps(r) + "\n")
        if best_overall:
            with open("/tmp/nid_best_win.json", "w") as f:
                json.dump({"fitness": best_overall["fitness"],
                           "weights": best_overall["weights"],
                           "rounds_won": best_overall["rounds_won"],
                           "rounds_lost": best_overall["rounds_lost"]}, f)

    print("best:", best_overall["fitness"] if best_overall else None, flush=True)
    for m in mgrs:
        m.close()
    with open(TS.PREFS, "w") as f:
        f.write(open(TS.PRISTINE_PREFS).read())
    print("done; prefs restored", flush=True)


if __name__ == "__main__":
    main()
