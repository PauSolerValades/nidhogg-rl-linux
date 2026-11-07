# The control gate — what it proves, and where it silently doesn't

`nidstate.control_gate()` currently checks three things, all read-only:

| check | what it measures | passes on |
|---|---|---|
| **A** drivable | yellow sprite moves >15 px when `d` is held | READY |
| **B** identify | one 0x200 record tracks the sprite 1:1 (median <2 px, max <4 px) | READY |
| **C** uniqueness | no other record tracks it that well | READY |

Evidence: `docs/gate/ready.json` (12/12 transitions, median 0.87 px) and
`docs/gate/attract.json` (A = 0.0). That is real, and it is what identified P1.

## The scope bug

**B and C only hold with a fixed camera.** They work by comparing a *record* delta to a
*sprite* delta — and in a match the camera follows P1, so the sprite barely moves while `x`
moves a lot. B fails by construction there, and `drivable()` (A) fails with it.

So the gate certifies **"P1 is identifiable and drivable on a fixed-camera screen"**. It does
not certify **"this match is under our control"** — which is what Phases 2–4 need. That is the
same mistake the docs warn about ("never reuse an oracle across game states"), one level up:
the gate itself is a state-specific oracle.

There is a second, subtler hole. **A can pass by luck.** In attract mode the demo fighters walk
on their own; if our 0.7 s window happens to land during a walk, A reads >15 px and the check
means nothing. It read 0.0 this time because the demo was mid-jump. Passing A today is
evidence, not proof.

## The gate we actually need: three checks, each tagged with its scope

**G1 — causality (camera-invariant).** Sample the candidate record's `x` for ~1 s idle, hold
`d` for ~1 s, release, sample ~1 s more. Pass only if:

```
|Δx during hold|  > 20 px        (it moved when asked)
|Δx after release| < 3 px        (it stopped when released)
and the sign flips for 'a'
```

An attract demo cannot pass: its fighters keep moving after we release. This is the check that
distinguishes *control* from *coincidence*, and it works in any state, camera or not.

**G2 — write survival (the original definition).** `add(x, +200)` for ~300 ms on the *proven*
address, then read back within 3 ticks: the value must have moved by ≈200. Only a live
simulation reads our write back, so a demo cannot pass. This was abandoned earlier because
writes "killed the game twice" — but those crashes were sweeping `add` across *arbitrary
candidate addresses*. On `body+0xEC` of a type-grouped fighter it is a targeted write to a
known field, which is a different risk class. Re-introduce it, guarded: read the value before
writing, refuse if it is not a plausible coordinate.

**G3 — sprite link (fixed-camera only, keep today's check).** Useful for *identity*, and the
only way to prove P1-vs-P2 without assuming start positions. Tag it `scope: fixed-camera` and
never use it in a match.

A gate result should therefore say what it proves:

```json
{"state": "match", "G1": true, "G2": true, "G3": "n/a (camera follows)", "cpu_motion": 61.2}
```

## Why this is exactly what the server is for

With 384 cores the question stops being "can we reason our way to a controllable match" and
becomes "measure 50 candidates and keep the ones that pass". Concretely:
`gate-filtered parallel entry` — spawn K instances, run entry attempts concurrently, and retain
only instances where **G1 ∧ G2 ∧ cpu_motion > 15**. Everything downstream (Phases 2–5) runs on
the surviving instances, so a failed entry costs a slot, not a session.

That is the honest division of labour: the gate is a *measurement* we can now afford to take
cheaply and often, instead of an inference we argue about.
