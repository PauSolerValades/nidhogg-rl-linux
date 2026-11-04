# WORKER_STATE — single-instance state GA (2026-10-29)

## Goal
Run the requested 6-generation x 8-individual GA, 25 s per individual, on ONE Nidhogg instance using `/tmp/nid_state_0.txt`; reward `3*their_deaths - 2*my_deaths + advance/100`. Leave `/tmp/nid_train_state.jsonl`, stdout log, best params and a run summary. Clean up only processes started for this run and restore `prefs_pristine.ini`.

## Current state
- Read NOTES.md sessions 12-14, train_state.py, train_episodes.py and prior WORKER_STATE.
- Prior 3-instance run is dead. No Nidhogg or trainer processes remain. Its log has only g0i0..g0i2, all fitness -100 because match entry failed.
- Existing game prefs currently match `prefs_pristine.ini` (verified SHA256 93fd3718...).
- Existing caffeinate processes belong to `unigraz-vpn`; DO NOT kill them.

## Next / resume
- `train_state.py` has been replaced with the sequential one-instance trainer and passed `py_compile` + `--help`.
- Dedicated caffeinate started: process `nid-ga-caffeinate` / `proc_8a78`, pid 60262. Do not kill the older VPN caffeinate processes.
- Start trainer now with process name `nid-state-ga`: `.venv/bin/python -u train_state.py --gens 6 --pop 8 --window 25 --seed 23`, stdout/stderr to `/tmp/nid_train_state_run.log`.
- After completion verify 48 records/tags and per-gen stats, best params, recovery/restart counts; stop `proc_8a78`, confirm no owned Nidhogg/python, prefs pristine.

## Key decisions
- Use the exact launch env from the brief: NID_QUIET, NID_FOCUS, NID_MAN, NID_THREAD; never NID_ORDERS.
- Count match re-entry recovery separately from hard instance restarts; report episodes needing either as well as hard-restart count.
- Pause an individual's 25 s gameplay clock while episode recovery/relaunch is underway so every individual gets 25 s of actual control.
- Preserve old `/tmp/nid_train_state.jsonl` as a timestamped backup before starting the new log.

## Artifacts (planned)
- `/tmp/nid_train_state.jsonl` — 48 individual records
- `/tmp/nid_train_state_run.log` — trainer stdout/stderr
- `/tmp/nid_train_state_summary.json` — global best, per-gen stats, recovery counts
- `/tmp/nid_best_params.json` — winning parameter vector
