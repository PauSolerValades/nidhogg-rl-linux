# Verified state, and what is not verified

Every line here was measured on the real game. The second half lists the checks that are
**not** done, because knowing which claims are load-bearing matters more than the claims.

## Verified by measurement

| Claim | Evidence |
|---|---|
| Keys control the fighter | Holding `A`: me_x 142 → 8. Holding `D` 20 s: 8 → 245 (+237 px, ~12 px/s) |
| Strikes land only at close range | At dx=22: CPU 246 → 297 (+51 px). At dx=59: 0 px in 15 s |
| Running alone cannot win | 120 s of holding right: start 114, peak 480, end 71 — pushed back |
| Entry lands in TRAINING (active CPU) | CPU moves 29–244 px while the agent does nothing; ARCADE shows 0 px |
| A Training match is one round | Accept presses never restart a round; re-entry per episode is required |
| State reads at ~40 Hz | 2,400+ samples per 60 s episode |
| The game runs at 47.7 fps at speed 180 | vs a throttled 23.8 fps before the latency-critical activity assertion |
| Console keys/values are exact | player positions correlate with visible gameplay; `A` moves left, `D` right |

## Current performance (honest)

* **Rounds won: 0.** In every run, to date.
* Rounds lost: 0 in most runs; 10 in the run where the agent was rewarded for closing
  distance (it rushed in and died).
* Best policy behaviour measured so far: `min_dx` 15–26 px (it does reach striking range)
  and `pushed` up to 3.00 (300 px of CPU displacement) — i.e. it can win exchanges
  occasionally, but not convert them into rounds.
* Fitness numbers (`best 12.13`, etc.) are a *designed reward*, not a win rate. They are not
  comparable across reward changes.

## Checks that have NOT been done (be appropriately paranoid here)

1. **Is the opponent really the CPU?** Entry goes through the Training menu, and the
   opponent moves on its own (29–244 px measured while we stand still), which a waiting
   room does not do. But we have never read the CPU's personality/difficulty setting back
   out of the game, so "it is the CPU" is inference, not proof.
2. **Are kills and deaths counted correctly?** No. `kills`/`deaths` are always 0 because
   death detection was never made reliable (see `docs/EXPERIMENTS.md`). Round outcomes are
   counted from goal-line crossings between consecutive samples, which caught a phantom
   10-win generation once and was then tightened — but it is still a heuristic.
3. **Is the agent improving?** Mixed. Behavioural metrics improve and then regress when the
   reward changes (min_dx 90 → 15–26 px is a real behavioural change). Win rate — the only
   metric that matters — has been 0 throughout, so "improving" cannot be claimed yet.
4. **Are the weights meaningful?** The population is diverse (12 nets, 5 distinct actions on
   a fixed observation, mean pairwise weight distance 30.3), but no analysis of what the
   trained weights encode has been done. That was planned as a later phase.
5. **Is the game fully decompiled?** No. We have the symbol table (142,869 symbols, 28,289
   `gml_*`), so scripts can be named and called, and `startMatch`'s one-int signature was
   recovered from its call site. We cannot yet read GML variables by name, and the room list
   is not recoverable from strings.

## Environment pitfalls that produced false conclusions

* The off-screen window is occluded and throttled to ~24 fps; screenshots can take minutes
  when the machine is loaded, which once made entry "hang for 18 minutes".
* The game's own `online.log` revealed that a recovery heuristic had walked into the online
  lobby — a failure that looked exactly like a broken key sequence.
* Stale game processes from Steam's re-exec chain inflated load to 19 and made timing
  assumptions fail intermittently.
* Files in `/tmp` persist across launches (`nid_state_*.txt`, `nid_inject_*.log`), which
  caused a readiness check to read previous runs' frame counters.
