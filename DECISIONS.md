# DECISIONS

## D-2026-11-15-step01: re-scope plan step 01 to a live local two-player match

- **Chosen:** step 01 (attestation, three consecutive ATTESTED runs) is measured against a live local two-player match on artemis, both fighters drivable, with direction, dose-response and the 40/30 px floor. The live CPU match moves to a new step 25, an evaluation milestone.
- **Alternatives:** (B) wait for a game fix in a newer Steam build; (C) binary-patch the CPU Brain-creation path (Windows build, no symbols, weeks of work).
- **Why:** on build 108 no route reaches a live CPU match. Measured: TRAINING crashes at the map pick, ARCADE crashes on entry, -net* routes give a frozen opponent with no Brain (state/VERDICT_step01_route_exhausted.md). A live local two-player match is verified (state/claims.jsonl, 2026-11-09 to 11-10): both fighters bound by response, round boundaries from death teleports and forfeits, a reset that works 20 times with 0 crashes.
- **Decided by:** Ruggero, via a question put to him in session on 2026-11-15 ("Re-scope to local two-player (Recommended)").
- **Change if:** a route to a live CPU match is found (Steam build newer than 10/30/2026, a Proton/wined3d fix, or the Mac evaluator), or a two-player match stops being attestable on artemis.
- **Evidence:** state/claims.jsonl (live match, forfeit boundary, reset lanes); state/attest_runs.log shows the earlier "ATTESTED" streak was a substring match on "NOT ATTESTED" and was not three genuine passes.
- **Ruggero's words:** the question put to him was: "May step 01 instead be re-scoped to a live two-player match on artemis (both fighters drivable, dose-response, 40/30 px floor), with the CPU as a later evaluation milestone?" Answer: "Re-scope to local two-player (Recommended)".
- **Correction (gold review, 2026-11-15):** the local two-player opponent is a frozen human P2, so "both fighters bound by response" does not mean an acting opponent. The re-scope only works if P2 is driven by a scripted or learned partner on the P2 keys. Claim 123 ("enter_match_v2 reaches a verified live match") records rc=1 and enter_match_v2=False in its own output, while claim 1794269370 records True; this conflict is unresolved.
- **Note:** a claim that the score address is stable at 0xd5d9648 conflicts with a Lane C note that it varies per process. Not yet resolved; step 02 of the contract must test it in two fresh processes before any score is reported.
