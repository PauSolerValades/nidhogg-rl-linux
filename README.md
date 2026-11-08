# nidhogg-rl

Train an RL agent on the **real, installed Nidhogg** — headless, in parallel, on a Linux server —
without modifying gameplay code. The Windows build (GameMaker YYC) runs under Proton; state comes
out of process memory, actions go in as key presses.

> **Start with [`docs/TMP_CURRENT_STATE.md`](docs/TMP_CURRENT_STATE.md)** — what is proven, where it
> lives, what is missing. Then [`docs/LAYOUT.md`](docs/LAYOUT.md) (memory map) and
> [`docs/MEMORY.md`](docs/MEMORY.md) (lab notebook, including every trap).

## Status in one line

The observation interface is proven (both fighters' `x,y`, facing, animation, sword, a 60 Hz tick,
and the ORANGE wins counter), writes are kept so episode resets are viable, and **round phase is the
last missing field**.

## Quickstart

```bash
./scripts/server-runtime.sh                 # user-level Xvfb + xdotool (no sudo)
. ~/nidhogg-rl-install/results/env.sh       # NID_PROTON, PATH, LD_LIBRARY_PATH
./scripts/install-server.sh                 # Proton-GE + game copy + wine prefix template

python3 -c "import nidlinux as n; n.start_ids([0])"            # launch one instance
python3 -c "import nidstate as s; print(s.enter_match_v2(0))"   # menu -> pads -> live match (~58 s)
```

Human playable (VNC in a browser, no client needed):

```bash
./scripts/vnc_play.sh                       # then: ssh -L 6080:localhost:6080 <you>@<host>
                                            #       http://localhost:6080/vnc.html
```

Record a session and mine it:

```bash
python3 scripts/record_all.py 0 --p1 0x<addr> --p2 0x<addr>     # states, shots, full heap dumps
python3 scripts/mine_session.py ~/nidhogg-record/<stamp>        # structural events (kills, round end)
python3 scripts/hunt_field.py  ~/nidhogg-record/<stamp> spec.json [--float]   # field hunt
```

## Layout

```
nidlinux.py        launch/stop instances, keys, screenshots, spy protocol
nidstate.py        measurement library: entry, identification, oracles, field readers
spy/nidspy.c       in-process memory reader/writer (~90 lines; /proc/<pid>/mem is refused here)
scripts/           runtime install, VNC play, recorders, mining, load test
briefs/            worker briefs (headless pi agents, one falsifiable target each)
docs/               TMP_CURRENT_STATE, LAYOUT, MEMORY, OVERVIEW, INTERFACE, workers/, archive/
docs/archive/       the macOS era: NOTES_macos.md, STATE_macos.md, EXPERIMENTS_macos.md
docker/             per-instance image (written, builds when the host grants docker access)
```

## Rules that cost a session each

* **Never `pkill -f`** — it matches your own command line (it has killed a worker and the
  supervisor shell). Use `pkill -x`, or match `/proc/<pid>/environ`.
* **Never probe while a human plays** — identification presses `d/a/arrows`.
* **Identify early in a match** — identification decays as a session runs.
* **A dump offset is meaningless without `regions.json`**; low regions keep their bases across
  processes, high ones are ASLR'd.
* **Measure the measurement** — a per-screenshot fps loop reports 1 fps on a 60 fps game.

The full list, with what each one broke, is in `docs/TMP_CURRENT_STATE.md` §6.
