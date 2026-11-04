# Nidhogg neuroevolution — 3 hour sprint

Goal: GA/neuroevolution agent for Nidhogg, with BoxCar2D-style ghost-overlay
visualisation of a whole population training at once, cut into a watchable
video (general audience + research-honest).

## Deliverables
- [ ] sim/core.py — vectorised Nidhogg-inspired duel simulator
- [ ] GA over MLP weights, fitness vs fixed scripted opponents (fair across gens)
- [ ] learning curve + saved per-generation population trajectories
- [ ] render.py — ghost overlays, learning-curve HUD, narration via `say`, ffmpeg
- [ ] out/nidhogg_evolved.mp4
- [ ] README.md with numbers + honest "simulated, not the shipped game"

## Time boxes
- 0:00-0:30 research + sim design
- 0:30-1:10 sim + GA working, curve looks like learning
- 1:10-2:10 ghost renderer + scene assembly
- 2:10-2:45 polish, narration, music bed, re-render
- 2:45-3:00 README, numbers table, final check
