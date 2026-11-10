# Independent replication on a second host — what reproduced, what did not

All results below were produced on a **different machine** (artemis, 384-core server, GE-Proton 11-12)
from a **byte-identical build** — `data.win` sha256 `42969eea1ed383fb…`, `Nidhogg.exe` `5b87efafdd9f99e1…`
— using your modules unmodified: `nidlinux.py`, `nidstate.py` and `spy/nidspy.so` from this repo.

Nothing here is a claim about your machine; it is what a second pair of hands measured with your tools.
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
Writing `u32` 0 → 1 → 2 to **`0xd5f57c8`** lands in memory (readback confirms) but the **P2 HUD digit
does not change** (measured rect `[214,14,238,30]`: 479 → 479 px), **including on the READY screen**,
where the HUD is drawn, with a forced redraw between writes.
*Refute by:* repeating on a READY screen with the HUD oracle; if your bars move, our instance differs for
a reason worth finding (adjacent-state difference, prefix, or allocation order).

### 2. Menu arrows are ignored on our instances
`Up`/`Down`/`Left`/`Right` produce **no** menu movement (frame signature unchanged across all four),
while `Return` always advances and `W`/`S` do move the selection. The macOS build used the arrow keys;
this build does not.

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
