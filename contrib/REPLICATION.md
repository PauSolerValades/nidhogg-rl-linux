# Independent replication on a fresh checkout — what reproduced, what did not

All results below were produced on **artemis** (384-core server, GE-Proton 11-12) from a
**byte-identical build** — `data.win` sha256 `42969eea1ed383fb…`, `Nidhogg.exe` `5b87efafdd9f99e1…`
— using your modules unmodified: `nidlinux.py`, `nidstate.py` and `spy/nidspy.so` from this repo.

**Correction (post-merge):** this is not a different machine from the one the repo lives on — it is
`artemis` itself, where the probe was just re-run from this checkout. So the four non-reproductions
below cannot be explained away as "a different environment", which makes item 1 stronger, not weaker.

Nothing here is a claim about your machine; it is what a second pair of hands measured with your tools.

> **Verification pass (2026-11-11):** item 1 confirmed and strengthened (no documented int drives
> the tally — see `docs/TMP_CURRENT_STATE.md` §2.4b), item 2 refuted (below), items 3 and 4 not
> tested. Note that testing left the `-score` farm wedged (the game dies during start-up and
> `/tmp/nid_cmd_<pid>` keeps an unconsumed poke); `rm -rf ~/.nidfarm-score/inst/0` resets it.
Each item is followed by how to refute it.

## Reproduced ✅

* **`enter_match_v2(i)` reaches a verified live local-2P match** on a fresh host, and
  `find_players_by_input` binds **both** fighters by response (P1 moved +392 px on `d`, P2 +499 px on
  `Right`). Entry survived on a cold start of the whole stack.
* **Writes persist** — `add(x, +200)`-style writes survive into the simulation on our instances.
* **`proton run` is required**; `waitforexitandrun` blocks, exactly as documented.
* **Valve's original `steam_api64.dll`** — stub/replacement DLLs hang `SteamAPI_Init`.
* **The per-tick state file** (`n.track` / `n.state`) publishes at ~60 Hz and reading it is cheap.

## Did NOT reproduce ❌

### 1. The ORANGE score address does not drive the displayed score on our instance
**CONFIRMED on this host** (`artemis`, GE-Proton 11-12, `data.win` `42969eea1ed383fb`) by
`scripts/score_oracle.py`, recorded and re-verified cold in `state/claims.jsonl`. Control A: the write
lands (readback 0/1/2/0 exact). Control B: the same pixel oracle sees the pause overlay (28 188 static
px change), so a flat result is not a blind instrument. Test: 0 static pixels differ between any two of
0/1/2, whole frame, READY screen.

Writing `u32` 0 → 1 → 2 to **`0xd5f57c8`** lands in memory (readback confirms) but the **P2 HUD digit
does not change** (measured rect `[214,14,238,30]`: 479 → 479 px), **including on the READY screen**,
where the HUD is drawn, with a forced redraw between writes.
*Refute by:* repeating on a READY screen with the HUD oracle; if your bars move, our instance differs for
a reason worth finding (adjacent-state difference, prefix, or allocation order).

### 2. Menu arrows are ignored on our instances — **REFUTED 2026-11-11**

Re-measured on the same farm and build, from a cold boot, with the selection dot as the oracle
(`nidstate.selected_y`, which ignores the animated background):

```
Down : row 124 -> 114   ROW MOVED
Up   : row 124 -> 134   ROW MOVED
w    : row 124 -> 134   ROW MOVED      <- w/s are ALIASES for Up/Down, same row delta
s    : row 124 -> 114   ROW MOVED
```

The pause menu behaves the same (frozen screen, 0 px idle baseline, one row = 9360 px per key,
for Down/Up/w/s alike). So on this build arrows **do** move menu selections, and W/S are not an
alternative binding — they are the same action. Recorded as a claim in `state/claims.jsonl`;
replay with `python3 scripts/menu_keys.py 0 menu --fresh`.

*How it could have been missed:* a whole-frame signature on an animated menu changes every frame
whether or not a key was pressed, so a row move can hide inside the noise. `selected_y` avoids
that; for the pause menu the frozen-screen diff is exact.

### 3. `-localtest` matches are AI-vs-AI and not drivable
The 478-step `-localtest` harness does reach real arenas (`rWildsCenter`, `rMinesCenter`) and writes
`lt_*.png` screenshots (including a genuine two-fighter `lt_match1.png`), but **no fighter responds to
input** in those matches. Useful as a rendering/oracle fixture, not as a training episode.

### 4. The room id is not statically findable
The heap holds **~290,000 stable int32 slots** whose values equal plausible room indices, so value
matching cannot isolate the field. Only navigation-correlated differencing has a chance.

## Extends your sword work ➕

Holding `d` moves **exactly three records in lockstep** — the P1 body (`type 0x174f900`, `anim 465` idle,
`y=192`) and its **held sword** — which gives a behavioural signature for the "held" state of the sword
set. We have not finished the flying/stuck/ground transitions.

## Two process notes that cost us a day

* **`pgrep -f Nidhogg.exe` matches the Proton wrapper and `steam.exe`, not the game.** Use
  `pgrep -x Nidhogg.exe` (or `comm == "Nidhogg.exe"`).
* **A game window with no title still needs focusing.** Our farm instances exposed a case where
  `xdotool search --name [Nn]idhogg` returned nothing while a healthy window existed; enumerate visible
  windows and pick by geometry rather than by name when the name search comes up empty.

## Proposed addition: a double-check protocol for memory discoveries

Every field claim in this project has been wrong at least once on first reading, so we now require four
conditions before a field is treated as found:

1. **Two processes** — identical behaviour at the same absolute address in two fresh games.
2. **Two directions** — observed changing on its own **and** written, with the behaviour changing.
3. **A written falsifier** recorded with the claim.
4. **Cross-worker replay** — a *different* person/machine re-runs the claim's command; a claim replayed
   only by its author stays marked unverified.

`tools/claim.py` in this PR implements the ledger for 3 and 4 (claims carry their command and falsifier,
`verify` re-runs the command, `fixtures` replays known-false historical claims to prove the checker bites).

---

*Corrections to this file are welcome — if any "did not reproduce" item turns out to be our environment,
we would rather know.*
