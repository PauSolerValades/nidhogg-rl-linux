# Cold launch of Nidhogg on artemis (workstream A, 2026-11-15)

Result: 5 of 5 cold launches reached a game process and a spy ping, each in about 88 s.

## Recipe

```
cp -a --reflink=always ~/nidfarm/prefixes/1 ~/nf-launch/template && rm -f ~/nf-launch/template/pfx.lock
cd ~/nidhogg-main && source ~/nf-launch/env.sh && python3 -c "import nidlinux as n; n.start_ids([0])"
```

- Prefix source: a reflink copy of `~/nidfarm/prefixes/1` (291 MB). The original was not modified.
- Proton verb: `waitforexitandrun` (the origin/main default). It did not block. `proton run` was not tested.
  To test it: `NID_PROTON_VERB=run`.
- `~/nf-launch/env.sh` sets NIDFARM, NID_DISPLAY_BASE=220, NID_PROTON (GE-Proton11-12),
  NID_GAME_DIR=~/nidfarm/game, NID_PROTON_VERB and PATH with ~/nidroot/wrap-bin first.
- Game dir has the gbe stub steam_api64.dll (md5 240d8c3d2988d66d1329d38a92525bf4); it worked,
  contrary to docs/TMP_CURRENT_STATE.md.
- `~/nidfarm/prefix-template` was not tested by this run.

## Test

`~/nf-launch/coldtest.py N`, run from ~/nidhogg-main after sourcing env.sh.
Each launch:
1. Delete inst/0 and copy it again from the template.
2. Run `start_ids([0])`.
3. Wait up to 300 s for the Nidhogg.exe pid on :220 and a `ping` answer.
4. Run `stop()`.
5. Kill each pid owned by my uid whose environment contains exactly `NIDFARM=$HOME/nf-launch` (refuses above 40 pids).

0 pids were left after every launch.
Time is counted from the start of the launch; the first check comes after the 20 s sleep inside start_ids.

| launch | verb | game pid | spy ping | time (s) |
|---|---|---|---|---|
| 1 | waitforexitandrun | 1453399 | pong 1453399 | 88.5 |
| 2 | waitforexitandrun | 1470064 | pong 1470064 | 87.6 |
| 3 | waitforexitandrun | 1498823 | pong 1498823 | 87.9 |
| 4 | waitforexitandrun | 1519458 | pong 1519458 | 87.6 |
| 5 | waitforexitandrun | 1540248 | pong 1540248 | 87.9 |

An earlier single trial (17:51) also passed: pid 1429954, 88.0 s. Raw lines are in `~/nf-launch/results.jsonl`.

## Code change

`nidlinux.py` line 138: the proton verb is read from `NID_PROTON_VERB`, with default `waitforexitandrun`.
