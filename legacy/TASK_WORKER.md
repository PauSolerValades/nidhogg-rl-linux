# TASK: test and time the match-recovery module

Read /Users/ruggsea/Projects/nidhogg-rl/recover.py first — it is already written.

A Nidhogg instance may or may not be running. Check with:
    pgrep -f "MacOS/Nidhogg"

If none is running, launch exactly one:
    cd /Users/ruggsea/Projects/nidhogg-rl
    cp prefs_muted.ini "$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"
    NID_ID=0 SteamAppId=94400 NID_QUIET=1 NID_FOCUS=1 NID_MAN=1 NID_THREAD=1 \
      DYLD_INSERT_LIBRARIES=$PWD/hook/inject.dylib \
      "/Users/ruggsea/Library/Application Support/Steam/steamapps/common/Nidhogg/Nidhogg.app/Contents/MacOS/Nidhogg" \
      >> /tmp/nid_out_i0.log 2>&1 &
    (use nohup/setsid or the process tool named nid-i0; wait 16 s after launch)

Then run:
    cd /Users/ruggsea/Projects/nidhogg-rl && source .venv/bin/activate
    python3 recover.py 0

recover.py's __main__ calls detect_screen() then ensure_match("0").

Report back, concisely:
1. whether ensure_match returned True
2. wall-clock seconds it took
3. what screen it got stuck on, if it failed
4. the state file contents at the end: cat /tmp/nid_state_0.txt

Rules:
- Do NOT edit recover.py or any other file. Only run things.
- Do NOT touch the Mac's volume. Game prefs are already muted; do not change them.
- Time limit: 6 minutes. If it has not succeeded by then, kill the game
  (pkill -f "MacOS/Nidhogg"), restore prefs
  (cp prefs_pristine.ini "$HOME/Library/Application Support/com.messhof.nidhogg/prefs.ini"),
  and report what happened.
