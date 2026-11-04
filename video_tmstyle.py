"""TrackMania-AI-style video: cinematic training story for the Nidhogg agent.

Structure (mirroring the TrackMania AI series' arc):
  1. Hook: the agent entering a live match (real gameplay frames)
  2. What the AI sees: the exact state vector, visualized on the frame
  3. Training montage: every individual of a generation superimposed,
     brightest = fittest, evolving across generations
  4. The learning curve: best + mean per generation
  5. Best-agent showcase: its full trace played over real footage
  6. Honest limits

Narration via macOS `say`; rendered with ffmpeg at 1280x720.
"""
import json
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = "/Users/ruggsea/Projects/nidhogg-rl/out"
HIST = "/tmp/nid_neuro_history.json"
TRACE = "/tmp/nid_neuro_train.jsonl"
BG = "/tmp/bg_frame.png"
W, H = 1280, 720
FPS = 30

FONT = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"
F_TITLE = ImageFont.truetype(FONT, 58)
F_H2 = ImageFont.truetype(FONT, 30)
F_BODY = ImageFont.truetype(FONT, 23)
F_SMALL = ImageFont.truetype(FONT, 17)

INK = (12, 12, 16)
PAPER = (236, 232, 224)
CYAN = (0, 214, 214)
ORANGE = (255, 150, 40)
GREY = (150, 150, 158)
TRACE_W = 2056


def load_all():
    hist, runs = [], []
    if os.path.exists(HIST):
        hist = json.load(open(HIST)).get("history", [])
    if os.path.exists(TRACE):
        for line in open(TRACE):
            try:
                r = json.loads(line)
                if r.get("trace"):
                    runs.append(r)
            except json.JSONDecodeError:
                pass
    return hist, runs


def bg_frame():
    if os.path.exists(BG):
        return Image.open(BG).convert("RGB").resize((W, H))
    return Image.new("RGB", (W, H), INK)


def text(d, xy, s, font, fill=PAPER, anchor="la"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def card(title, sub=None, body=None):
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)
    text(d, (W // 2, H // 2 - 60), title, F_TITLE, CYAN, "ma")
    if sub:
        text(d, (W // 2, H // 2 + 10), sub, F_H2, PAPER, "ma")
    if body:
        text(d, (W // 2, H // 2 + 60), body, F_BODY, GREY, "ma")
    return im


def fencer(d, x, y, colour, alpha, scale=1.0):
    h = int(86 * scale)
    lw = max(3, int(4 * scale))
    col = colour + (alpha,)
    d.ellipse([x - 9, y - h, x + 9, y - h + 18], fill=col)
    d.line([x, y - h + 18, x, y - h // 3], fill=col, width=lw)
    d.line([x, y - h // 3, x - 11, y], fill=col, width=lw)
    d.line([x, y - h // 3, x + 11, y], fill=col, width=lw)
    d.line([x, y - h // 2, x + 30, y - h // 2 - 7], fill=col, width=lw)


def ghost_frame(bg, runs, t_frac, title, sub, gen_label):
    base = bg.copy().convert("RGBA")
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    gy = int(base.height * 0.78)
    fits = [r["fitness"] for r in runs] or [0]
    lo, hi = min(fits), max(fits)
    for r in runs:
        tr = r["trace"]
        if not tr:
            continue
        i = min(len(tr) - 1, int(t_frac * (len(tr) - 1)))
        me, them = tr[i][1], tr[i][2]
        norm = (r["fitness"] - lo) / (hi - lo) if hi > lo else 0.5
        alpha = int(110 + 120 * norm)
        for px, colour in ((me, CYAN), (them, ORANGE)):
            if px is None or px < 0:
                continue
            x = float(np.clip(px / TRACE_W * base.width, 10, base.width - 10))
            fencer(d, x, gy, colour, alpha)
    base = Image.alpha_composite(base, ov).convert("RGB")
    d2 = ImageDraw.Draw(base)
    d2.rectangle([0, 0, W, 96], fill=(10, 10, 14))
    text(d2, (28, 16), title, F_H2, CYAN)
    text(d2, (28, 54), sub, F_SMALL, GREY)
    text(d2, (W - 28, 16), gen_label, F_H2, ORANGE, "ra")
    # fitness readout
    if runs:
        text(d2, (W - 28, 54), f"best {max(fits):.0f}  mean {sum(fits)/len(fits):.0f}",
             F_SMALL, GREY, "ra")
    return base


def curve_frame(hist, title="the learning curve"):
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)
    text(d, (28, 24), title, F_H2, CYAN)
    if not hist:
        text(d, (W // 2, H // 2), "no data", F_BODY, GREY, "ma")
        return im
    l, b, r, t = 110, H - 130, W - 90, 130
    bests = [h["best"] for h in hist]
    means = [h["mean"] for h in hist]
    lo = min(min(bests), min(means), 0)
    hi = max(max(bests), max(means)) * 1.1 + 1
    d.line([l, b, r, b], fill=GREY, width=2)
    d.line([l, t, l, b], fill=GREY, width=2)
    for v, lab in ((hi, f"{hi:.0f}"), (lo, f"{lo:.0f}")):
        y = b - (v - lo) / (hi - lo) * (b - t)
        text(d, (l - 12, y), lab, F_SMALL, GREY, "rm")
    n = len(hist)
    pts_b, pts_m = [], []
    for i, h in enumerate(hist):
        x = l + (i + 1) / n * (r - l)
        yb = b - (h["best"] - lo) / (hi - lo) * (b - t)
        ym = b - (h["mean"] - lo) / (hi - lo) * (b - t)
        pts_b.append((x, yb)); pts_m.append((x, ym))
        d.ellipse([x - 5, yb - 5, x + 5, yb + 5], fill=CYAN)
        d.ellipse([x - 4, ym - 4, x + 4, ym + 4], fill=GREY)
        text(d, (x, b + 20), f"g{i}", F_SMALL, GREY, "ma")
    d.line(pts_b, fill=CYAN, width=3)
    d.line(pts_m, fill=GREY, width=2)
    text(d, (l, b + 52), "cyan = best individual    grey = population mean",
         F_SMALL, GREY)
    text(d, (r, t + 4), f"{sum(h['n'] for h in hist)} individuals", F_SMALL, GREY, "ra")
    return im


def state_frame(bg):
    """What the AI sees: the observation numbers, drawn over the frame."""
    im = bg.copy()
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 96], fill=(10, 10, 14))
    text(d, (28, 16), "what the AI sees", F_H2, CYAN)
    text(d, (28, 54), "read straight from the game's memory - not pixels",
         F_SMALL, GREY)
    lines = [
        "state = [orange_x, orange_y, yellow_x, yellow_y]",
        "actions = {left, right, aim up/down, attack, jump}",
        "reward = 3*(cpu deaths) - 2*(own deaths) + advance",
        "",
        "each generation: 16 policies, 25 s each, 4 game copies in parallel",
    ]
    y = 130
    for ln in lines:
        text(d, (30, y), ln, F_BODY, PAPER)
        y += 34
    return im


def say(text_, out):
    subprocess.run(["say", "-v", "Samantha", "-o", out, text_], check=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", out], capture_output=True, text=True)
    return float(r.stdout.strip() or 3.0)


def main():
    os.makedirs(OUT, exist_ok=True)
    hist, runs = load_all()
    bg = bg_frame()
    gens = sorted({r["tag"].split("i")[0] for r in runs})

    tmp = tempfile.mkdtemp(prefix="nidtm")
    frames_dir = os.path.join(tmp, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    scenes = []  # (frames, duration, name)

    def add(frames, narration, name):
        a = os.path.join(tmp, f"{name}.aiff")
        dur = say(narration, a) if narration else 3.0
        scenes.append((frames, max(dur + 0.7, 2.2), name, a))

    add([card("NIDHOGG, EVOLVED", "a genetic algorithm learns to fence",
              "in the real game - four copies at once")],
        "A genetic algorithm, learning to fence. In the real game - four copies "
        "of it running at once, hidden, muted, reading the game's memory.", "s0")

    add([state_frame(bg)],
        "The agent does not look at pixels. It reads the position of both fencers "
        "straight from the game's memory, and presses keys into the game's own "
        "keyboard handler.", "s1")

    # training montage: last three generations, superimposed
    for gtag in gens[-3:]:
        gruns = [r for r in runs if r["tag"].startswith(gtag)]
        if not gruns:
            continue
        frames = [ghost_frame(bg, gruns, f, "training - one generation, superimposed",
                              "every policy of this generation at the same moment - "
                              "brighter means fitter", gtag)
                  for f in np.linspace(0.05, 0.95, 26)]
        add(frames, f"Generation {gtag[1:]}. Each faint fencer is one policy from the "
            f"population, at the same moment. They start together. They do not "
            f"finish together.", f"gen_{gtag}")

    add([curve_frame(hist)],
        "The learning curve. Sixteen policies per generation, scored by how far "
        "they push the opponent back, minus their own deaths. The population mean "
        "climbs - slowly, honestly.", "s2")

    # showcase: best individual's full trace
    if runs:
        best = max(runs, key=lambda r: r["fitness"])
        frames = [ghost_frame(bg, [best], f, "the best policy, replayed",
                              f"fitness {best['fitness']:.0f} - {best['tag']}",
                              best["tag"])
                  for f in np.linspace(0, 1, 40)]
        add(frames, "The best policy found so far, replaying its round. It advances, "
            "it pressures the opponent. It is not yet good. That is the honest "
            "part.", "s3")

    add([card("what this is", "memory-read state, keyboard injection,",
              "4 hidden game copies, zero computer vision")],
        "No computer vision. No game modification. The agent reads memory and "
        "presses keys - and the game never knows.", "s4")
    add([card("next", "more generations, a better reward,",
              "and a human opponent")],
        "Next: read the real score from the game, train for hours instead of "
        "minutes, and put a human on the other side.", "s5")

    # render frames
    idx = 0
    for frames, dur, name, _ in scenes:
        n = max(2, int(dur * FPS))
        for k in range(n):
            f = frames[min(len(frames) - 1, int(k / (n - 1) * len(frames)))] if len(frames) > 1 else frames[0]
            f.save(os.path.join(frames_dir, f"f{idx:06d}.png"))
            idx += 1
    print("frames:", idx)

    # audio concat
    lst = os.path.join(tmp, "a.txt")
    sil = os.path.join(tmp, "sil.wav")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", "0.5", sil], capture_output=True)
    with open(lst, "w") as fh:
        for _, _, name, a in scenes:
            if os.path.exists(a):
                fh.write(f"file '{a}'\nfile '{sil}'\n")
    audio = os.path.join(tmp, "narration.wav")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-ar", "44100", "-ac", "1", audio], capture_output=True)

    out = os.path.join(OUT, "nidhogg_evolved.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS),
                        "-i", os.path.join(frames_dir, "f%06d.png"),
                        "-i", audio, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1200:])
    print("wrote", out)


if __name__ == "__main__":
    main()
