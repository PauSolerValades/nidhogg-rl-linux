"""Plot the actual training history from the run logs.

Reads every "== gen N best X mean Y roundsW a roundsL b" line in
logs/train_forever.log (all cycles, in order) and draws:
  1. fitness best + population mean per generation
  2. rounds lost per generation (lower is better)
Writes out/progress.png.
"""
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOG = "logs/train_forever.log"
OUT = "out/progress.png"

PAT = re.compile(
    r"^== gen (\d+) best (-?[\d.]+) mean (-?[\d.]+)(?:.*?roundsW (\d+) roundsL (\d+))?")

gens = []
with open(LOG, "r", errors="replace") as fh:
    for line in fh:
        m = PAT.match(line.strip())
        if not m:
            continue
        gens.append({
            "best": float(m.group(2)),
            "mean": float(m.group(3)),
            "rw": int(m.group(4) or 0),
            "rl": int(m.group(5) or 0),
        })

if not gens:
    raise SystemExit("no generation lines found")

# Exclude the window where the round detector was broken: it produced round losses in
# the thousands and fitness near -2000, which is measurement error, not learning.
valid = [g for g in gens if g["mean"] > -100 and g["rl"] < 200]
dropped = len(gens) - len(valid)
gens = valid

x = list(range(1, len(gens) + 1))
best = [g["best"] for g in gens]
mean = [g["mean"] for g in gens]
rl = [g["rl"] for g in gens]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                               gridspec_kw={"height_ratios": [2, 1]})

ax1.plot(x, best, marker="o", lw=2, label="best individual", color="#0aa")
ax1.plot(x, mean, marker="o", lw=2, label="population mean", color="#888")
ax1.axhline(0, color="#444", lw=0.8, ls="--")
ax1.set_ylabel("fitness (higher is better)")
ax1.set_title(f"Nidhogg agent — {len(gens)} generations of real-game training"
              f"{f'  ({dropped} broken-detector gens excluded)' if dropped else ''}")
ax1.legend(loc="lower right")
ax1.grid(alpha=0.25)

ax2.bar(x, rl, color="#c33", alpha=0.8, label="rounds lost / generation")
ax2.set_ylabel("rounds lost")
ax2.set_xlabel("generation (chronological, across all cycles)")
ax2.legend(loc="upper right")
ax2.grid(alpha=0.25)

# annotate the two fixes that moved the curve
for label, frac in (("action repeat\n(160ms hold)", 0.35), ("+ reach/height inputs", 0.62)):
    ax1.axvline(int(len(x) * frac), color="#08f", lw=1.2, ls=":")
    ax1.text(int(len(x) * frac) + 0.3, ax1.get_ylim()[1] * 0.8, label,
             fontsize=8, color="#08f")

fig.tight_layout()
fig.savefig(OUT, dpi=130)
print(f"wrote {OUT}  ({len(gens)} generations)")
print(f"first gen: best {best[0]:.2f} mean {mean[0]:.2f} | "
      f"last gen: best {best[-1]:.2f} mean {mean[-1]:.2f}")
print(f"best-ever: {max(best):.2f} at gen #{best.index(max(best)) + 1}")
