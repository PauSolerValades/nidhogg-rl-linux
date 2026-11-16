"""Is a logged nidenv episode a real fight? An episode counts for training only if all hold:

 (a) room: every sampled tick from reset start to round end read a room index (from memory,
     nidmem.ROOM_OFF) inside the arenas 26..77 (no menu, lobby, level select, title);
 (b) motion: each fighter's x moved the way its own walk key pointed. From play when the
     fighter held the same walk key two steps running, not into blade contact, on >=
     MIN_KEY_STEPS steps (then x moved along the key on >= MIN_MOVED_STEPS of them and by
     >= MIN_DIR_DX px in total, or on >= 2 and at least half of them with a net shift > 0);
     from the reset's causal probe of the same
     episode (left key moves it left and right key right, nidmem.answers) only when the
     fighter never held a walk key long enough to judge from play;
 (c) kill: one death event confirmed by nidenv's rule (a new record answering the dead
     fighter's keys = respawn, or a corpse in a death anim that ignores its keys);
 (d) outcome is P1 or P2 (draw and undecided are invalid).
An invalid episode keeps its raw outcome in the log and is never turned into a win or loss.
"""
ARENA_ROOMS = range(26, 78)  # same as nidmem.ARENA_ROOMS; not imported so the shim loads first

MIN_KEY_STEPS = 3
# absolute, not per-step: a policy that walks into a wall keeps holding the key with no motion
# (run 3: 38 px in 5 steps, then 30-50 steps pinned), which says nothing against its keys.
# Dead-key falsifiers on the same counting: 0 and 1 moved steps, 0.0 and -9 px.
MIN_MOVED_STEPS, MIN_DIR_DX = 3, 15.0
# rule v3 (2026-11-16, coordinator): P1 (and P2) must walk under their own keys in play on
# >= 5 steps and >= 40 px; the reset probe is not motion evidence. Selected by NID_RULE=v3.
import os as _os
RULE = _os.environ.get("NID_RULE", "v2")
V3_MOVED_STEPS, V3_DIR_DX = 5, 40.0
# rule v2 (2026-11-16, within the first 10 episodes of the run): a policy that walks only 3-5
# steps cannot reach 15 px, so 6 of 8 real fights were rejected (key_steps 3, moved 2, 2-4 px).
# A short sample also passes when the body moved the key's way on at least half the steps
# (and >= 2 of them) with a positive net shift. Dead keys measured: (5 steps, 0 moved, 0.0 px),
# (24, 1, -9 px): both still fail.
MIN_ROOM_COVERAGE = 0.9      # play ticks with a room read / play tick span


def check(row):
    reasons = []
    rooms = [r for r, _n in row.get("rooms_rle", [])]
    if not rooms:
        reasons.append("a: no room samples")
    else:
        bad = sorted({r for r in rooms if r not in ARENA_ROOMS})
        if bad:
            reasons.append(f"a: non-arena room(s) {bad}")
        # every tick of play (reset end .. last step) must have been read; the reset and the
        # death confirmation sleep between reads, but a menu cannot be left again without
        # re-entering a match, so a visit there would still show in the samples after it
        cov = row.get("play_room_samples", 0) / max(1, row.get("play_tick_span", 0))
        if cov < MIN_ROOM_COVERAGE:
            reasons.append(f"a: room read on {cov:.2f} of play ticks")
    src = {}
    if RULE == "v3":
        # v3: motion evidence from play only, for both fighters; the reset probe does not count
        for w in ("P1", "P2"):
            mo = row.get("motion", {}).get(w) or {}
            src[w] = "play"
            if mo.get("moved_steps", 0) < V3_MOVED_STEPS or mo.get("dir_dx", 0.0) < V3_DIR_DX:
                reasons.append(f"b: {w} walked under its own keys on {mo.get('moved_steps', 0)} steps, "
                               f"{mo.get('dir_dx', 0.0)} px (needs {V3_MOVED_STEPS} steps and "
                               f"{V3_DIR_DX} px; reset probe not accepted)")
    for w in (() if RULE == "v3" else ("P1", "P2")):
        mo = row.get("motion", {}).get(w)
        if mo is None:
            reasons.append(f"b: {w} no motion record"); continue
        if mo["key_steps"] >= MIN_KEY_STEPS:
            src[w] = "play"
            long_ok = mo["dir_dx"] >= MIN_DIR_DX and mo["moved_steps"] >= MIN_MOVED_STEPS
            short_ok = (mo["moved_steps"] >= 2 and mo["moved_steps"] * 2 >= mo["key_steps"]
                        and mo["dir_dx"] > 0)
            if not (long_ok or short_ok):
                reasons.append(f"b: {w} keys did not move it in play ({mo})")
        else:
            src[w] = "reset_probe"
            alive = (row.get("reset_alive") or {}).get(w)
            if not alive:
                reasons.append(f"b: {w} held no walk key in play and reset probe failed "
                               f"({(row.get('reset_alive_dx') or {}).get(w)})")
    ev = row.get("evidence", {})
    deaths = [w for w in ("P1", "P2") if isinstance(ev.get(w), dict) and ev[w].get("dead")]
    if not deaths:
        reasons.append("c: no confirmed death event")
    if row.get("outcome") not in ("P1", "P2"):
        reasons.append(f"d: outcome {row.get('outcome')}")
    return {"valid": not reasons, "invalid_reasons": reasons, "motion_source": src, "rule": RULE,
            "kills": [{"who": w, "branch": ev[w].get("branch"), "new_record": ev[w].get("new_record")}
                      for w in deaths]}


def annotate(row):
    return dict(row, **check(row))
