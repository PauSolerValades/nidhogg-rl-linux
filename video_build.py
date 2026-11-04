"""Cut the Nidhogg video: real game frames, ghost overlays of the population,
the learning curve, and narration generated with macOS `say`.

Usage:  python video_build.py            # writes out/nidhogg_evolved.mp4
"""
import json
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import nav

OUT = "/Users/ruggsea/Projects/nidhogg-rl/out"
TRACE_LOG = "/tmp/nid_train_state.jsonl"
W, H = 1280, 720
FPS = 30
BG_PATH = "/tmp/bg_frame.png"
TRACE_W = 2056          # trace x coords are in capture pixels

FONT = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"
try:
    F_TITLE = ImageFont.truetype(FONT, 64)
    F_H2 = ImageFont.truetype(FONT, 30)
    F_BODY = ImageFont.truetype(FONT, 24)
    F_SMALL = ImageFont.truetype(FONT, 18)
except OSError:
    F_TITLE = F_H2 = F_BODY = F_SMALL = ImageFont.load_default()

INK = (12, 12, 16)
PAPER = (236, 232, 224)
CYAN = (0, 214, 214)
BLUE = (86, 156, 255)
GREY = (150, 150, 158)


# ------------------------------------------------------------------ utilities
def load_bg():
    if os.path.exists(BG_PATH):
        im = Image.open(BG_PATH).convert("RGB")
    else:
        try:
            f = nav.capture()
            im = Image.fromarray(f) if f is not None else Image.new("RGB", (W, H), INK)
        except Exception:
            im = Image.new("RGB", (W, H), INK)
    return im.resize((W, H))


def fit_contain(im, w, h):
    r = min(w / im.width, h / im.height)
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))))


def text(d, xy, s, font, fill=PAPER, anchor="la"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def card(lines, sub=None, bg=None, accent=CYAN):
    """Simple title/explainer card."""
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)
    y = H // 2 - len(lines) * 34
    for i, ln in enumerate(lines):
        text(d, (W // 2, y), ln, F_TITLE if i == 0 else F_H2,
             accent if i == 0 else PAPER, "ma")
        y += 76 if i == 0 else 52
    if sub:
        text(d, (W // 2, y + 24), sub, F_BODY, GREY, "ma")
    return im


def load_runs():
    runs = []
    if not os.path.exists(TRACE_LOG):
        return runs
    for line in open(TRACE_LOG):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("trace"):
            runs.append(r)
    return runs


# ------------------------------------------------------------------- drawing
def ground_y(bg):
    """Rule of thumb: the floor sits at ~80% of the frame in Nidhogg levels."""
    return int(bg.height * 0.78)


def draw_fencer(d, x, y, colour, alpha=200, scale=1.0):
    """A small fencer: head, body, legs, sword. Big enough to read as a person."""
    h = int(86 * scale)
    w = int(9 * scale)
    lw = max(3, int(4 * scale))
    col = colour + (alpha,)
    d.ellipse([x - w, y - h, x + w, y - h + 2 * w], fill=col)              # head
    d.line([x, y - h + 2 * w, x, y - h // 3], fill=col, width=lw)          # body
    d.line([x, y - h // 3, x - int(11 * scale), y], fill=col, width=lw)    # back leg
    d.line([x, y - h // 3, x + int(11 * scale), y], fill=col, width=lw)    # front leg
    d.line([x, y - h // 2, x + int(30 * scale), y - h // 2 - int(7 * scale)],
           fill=col, width=lw)                                             # sword


def ghost_scene(bg, runs, t_frac, title, sub):
    """All individuals of the current generation, superimposed at the same moment."""
    base = bg.copy()
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    gy = ground_y(base)
    if not runs:
        return card(["no episodes logged yet"], None, accent=GREY)
    fits = np.array([r["fitness"] for r in runs], dtype=float)
    if fits.size == 0:
        return card(["no episodes logged yet"], None, accent=GREY)
    lo, hi = float(fits.min()), float(fits.max())
    for r in runs:
        tr = r["trace"]
        if not tr:
            continue
        i = min(len(tr) - 1, max(0, int(t_frac * (len(tr) - 1))))
        _, p1, p2 = tr[i]
        norm = (r["fitness"] - lo) / (hi - lo) if hi > lo else 0.5
        alpha = int(110 + 120 * norm)
        for px, colour in ((p1, CYAN), (p2, BLUE)):
            if px is None or px < 0:
                continue
            x = float(np.clip(px / TRACE_W * base.width, 10, base.width - 10))
            draw_fencer(d, x, gy, colour, alpha, scale=1.0)
    base = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
    d2 = ImageDraw.Draw(base)
    d2.rectangle([0, 0, W, 92], fill=(10, 10, 14))
    text(d2, (28, 18), title, F_H2, CYAN)
    text(d2, (28, 56), sub, F_SMALL, GREY)
    return base


def curve_scene(bg, runs, gens_done, title):
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)
    text(d, (28, 24), title, F_H2, CYAN)
    if not runs:
        text(d, (W // 2, H // 2), "no episodes logged yet", F_BODY, GREY, "ma")
        return im
    per_gen = {}
    for r in runs:
        g = int("".join(c for c in r["tag"].split("g")[1].split("i")[0] if c.isdigit()) or 0)
        per_gen.setdefault(g, []).append(r["fitness"])
    xs = sorted(per_gen)
    fit_axes = (110, H - 110, W - 90, 120)          # l, b, r, t
    l, b, r_, t = fit_axes
    vals = [v for g in xs for v in per_gen[g]]
    if not vals:
        text(d, (W // 2, H // 2), "no data yet", F_BODY, GREY, "ma")
        return im
    lo, hi = min(vals), max(vals)
    rng = max(1e-6, hi - lo)
    d.line([l, b, r_, b], fill=GREY, width=2)
    d.line([l, t, l, b], fill=GREY, width=2)
    for label, v in ((f"{hi:.0f}", hi), (f"{lo:.0f}", lo)):
        y = b - (v - lo) / rng * (b - t)
        text(d, (l - 12, y), label, F_SMALL, GREY, "rm")
    best_xs, best_ys = [], []
    for g in xs:
        fs = per_gen[g]
        mean = float(np.mean(fs))
        best = float(np.max(fs))
        x = l + (g + 1) / (max(xs) + 1) * (r_ - l)
        for v, colour in ((mean, GREY), (best, CYAN)):
            y = b - (v - lo) / rng * (b - t)
            d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=colour)
            if colour == CYAN:
                best_xs.append(x); best_ys.append(y)
        text(d, (x, b + 26), f"gen {g}", F_SMALL, GREY, "ma")
    if len(best_xs) > 1:
        d.line(list(zip(best_xs, best_ys)), fill=CYAN, width=3)
    text(d, (l, b + 60), "grey = generation mean    cyan = best individual",
         F_SMALL, GREY)
    text(d, (r_, t + 8), f"{len(runs)} matches", F_SMALL, GREY, "ra")
    return im


def overlay_detect(bg, runs, src_img=None):
    """One frame showing what perception sees: boxes on both fighters."""
    p1 = p2 = None
    try:
        import perceive
        if src_img is not None:
            tr = perceive.FastTracker()
            for _ in range(3):
                obs = tr.update(src_img, 0.1)
            p1, p2 = obs["p1"], obs["p2"]
    except Exception:
        p1 = p2 = None
    if p1 is None and runs and runs[-1].get("trace"):
        _, p1, p2 = runs[-1]["trace"][len(runs[-1]["trace"]) // 2]
    im = bg.copy()
    d = ImageDraw.Draw(im)
    gy = ground_y(im)
    for px, colour, name in ((p1, CYAN, "P1 us"), (p2, BLUE, "P2 cpu")):
        if px is None or px < 0:
            continue
        x = float(np.clip(px / TRACE_W * im.width, 20, im.width - 20))
        d.rectangle([x - 34, gy - 96, x + 34, gy + 6], outline=colour, width=3)
        text(d, (x, gy - 122), name, F_SMALL, colour, "ma")
    d.rectangle([0, 0, W, 92], fill=(10, 10, 14))
    text(d, (28, 18), "Perception: pixels only - no game memory", F_H2, CYAN)
    text(d, (28, 56), "saturated shape + colour pairing (palette changes per level)", F_SMALL, GREY)
    return im


# ------------------------------------------------------------------- assembly
SCENES = []


def say(text_, out):
    subprocess.run(["say", "-v", "Samantha", "-o", out, text_], check=True)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of",
                        "default=nw=1:nk=1", out], capture_output=True, text=True)
    return float(d.stdout.strip() or 3.0)


def main():
    os.makedirs(OUT, exist_ok=True)
    bg = load_bg()
    runs = load_runs()
    gens = sorted({r["tag"].split("i")[0] for r in runs}) if runs else []
    last_gen_runs = [r for r in runs if gens and r["tag"].startswith(gens[-1])] or runs

    tmp = tempfile.mkdtemp(prefix="nidvid")
    frames_dir = os.path.join(tmp, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    audio_parts = []
    timeline = []

    def add_scene(frames, narration, name):
        a = os.path.join(tmp, f"{name}.aiff")
        dur = say(narration, a) if narration else 3.0
        audio_parts.append(a)
        timeline.append((frames, max(dur + 0.6, 2.0), name))

    add_scene([card(["NIDHOGG, EVOLVED"],
                    "a genetic algorithm learns to fence - in the real game",
                    accent=CYAN)], "A genetic algorithm, trying to learn to fence. In the real game.", "s0")

    add_scene([overlay_detect(bg, runs)],
              "No game memory, no cheats. I watch the screen and press the keys, "
              "the same way you would.", "s1")

    ghost_titles = []
    for i, frac in enumerate(np.linspace(0.05, 0.95, 40)):
        ghost_titles.append(ghost_scene(
            bg, last_gen_runs, frac,
            "one generation, superimposed",
            f"every individual of {gens[-1] if gens else 'gen 0'} at the same moment - brighter means fitter"))
    add_scene(ghost_titles,
              "Each faint fencer is one individual from the same generation. "
              "They all start together. Most of them just walk into the CPU.", "s2")

    add_scene([curve_scene(bg, runs, len(gens), "fitness across generations")],
              "Fitness is their deaths minus mine. Five generations, thirty individuals: "
              "the line bounces between nothing and eight, and that is noise, not learning.", "s3")

    add_scene([card(["what did not happen"],
                    "no learning yet - the signal is too thin at 1-2 frames a second",
                    accent=GREY)], "", "s4")
    add_scene([card(["what comes next"],
                    "an LLM policy head (JEV-style) + longer training runs",
                    accent=CYAN)], "", "s5")

    # render frames
    idx = 0
    for frames, dur, name in timeline:
        n = int(dur * FPS)
        for k in range(n):
            f = frames[min(len(frames) - 1, int(k / max(1, n - 1) * len(frames)))]
            f.save(os.path.join(frames_dir, f"f{idx:06d}.png"))
            idx += 1
    print("frames:", idx)

    # audio: concat narration with padding
    sil = os.path.join(tmp, "sil.wav")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=mono", "-t", "0.6", sil],
                   capture_output=True)
    lst = os.path.join(tmp, "a.txt")
    with open(lst, "w") as fh:
        for (frames, dur, name), a in zip(timeline, audio_parts):
            if os.path.exists(a):
                fh.write(f"file '{a}'\nfile '{sil}'\n")
    audio = os.path.join(tmp, "narration.wav")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-ar", "44100", "-ac", "1", audio], capture_output=True)

    out = os.path.join(OUT, "nidhogg_evolved.mp4")
    r = subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS),
        "-i", os.path.join(frames_dir, "f%06d.png"),
        "-i", audio, "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", out], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:])
    print("wrote", out)
    open(os.path.join(OUT, "VIDEO_DONE"), "w").write("ok")


if __name__ == "__main__":
    main()
