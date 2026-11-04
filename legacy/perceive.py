"""Perception for the real game, from window captures only.

Identity comes from the players' palettes, which are stable across levels:
    P1 (us)   pure cyan    rgb ~ [0, 255, 255]
    P2 (CPU)  light blue   rgb ~ [64, 160, 255]
The GO arrow shares P1's colour, so a shape filter (fighters are taller than
wide, arrows are flat) separates them.

A death is visible as the fighter's blob jumping back to its spawn side.
"""
import numpy as np
from scipy import ndimage

W, H = 1920, 1256


def _players_mask(img):
    r, g, b = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    return ((b > 200) & (r < 130) & (g > 120))


def candidates(img):
    """Fighter-like blobs with a colour class: 'p1' or 'p2'."""
    m = _players_mask(img)
    lab, n = ndimage.label(m)
    out = []
    if n == 0:
        return out
    objs = ndimage.find_objects(lab)
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        ys, xs = sl
        h = ys.stop - ys.start
        w = xs.stop - xs.start
        area = int((lab[sl] == i).sum())
        if area < 300 or area > 9000:
            continue
        if h < 70 or h > 260 or w < 25 or w > 200:
            continue
        if w / max(h, 1) > 1.15:          # arrows and banners are flat
            continue
        if ys.start < H * 0.40:           # must be near the ground
            continue
        px = img[sl][lab[sl] == i].mean(axis=0)
        r, g, b = float(px[0]), float(px[1]), float(px[2])
        if r < 40 and g > 225:
            cls = "p1"
        elif 40 <= r < 120 and 120 <= g < 210:
            cls = "p2"
        else:
            continue
        out.append({"cls": cls, "x": (xs.start + xs.stop) / 2,
                    "y": (ys.start + ys.stop) / 2, "area": area,
                    "w": w, "h": h, "rgb": (round(r), round(g), round(b))})
    return out


class Tracker:
    def __init__(self):
        self.p1 = None
        self.p2 = None
        self.events = []

    def update(self, img):
        cands = candidates(img)
        p1 = next((c for c in cands if c["cls"] == "p1"), None)
        p2 = next((c for c in cands if c["cls"] == "p2"), None)
        new1 = p1["x"] if p1 else None
        new2 = p2["x"] if p2 else None

        # a spawn jump = teleport of >260 px while still visible
        if new1 is not None and self.p1 is not None and abs(new1 - self.p1) > 260:
            self.events.append("my_death")
        if new2 is not None and self.p2 is not None and abs(new2 - self.p2) > 260:
            self.events.append("their_death")

        if new1 is not None:
            self.p1 = new1
        if new2 is not None:
            self.p2 = new2

        dx = None if (self.p1 is None or self.p2 is None) else (self.p2 - self.p1)
        return {"p1": self.p1, "p2": self.p2, "dx": dx,
                "seen1": p1 is not None, "seen2": p2 is not None,
                "blobs": [(c["cls"], round(c["x"]), c["rgb"]) for c in cands]}


# ---------------------------------------------------------------- fast variant
from PIL import Image

SCALE = 0.5            # nearest-neighbour keeps the palette exact
CROP_TOP = 0.42        # fighters live below this line


class FastTracker:
    """Palette-agnostic fighter tracking.

    Colour thresholds do NOT transfer between levels: Nidhogg recolours the
    players per level (cyan/blue in one, yellow/orange in another). So instead we
    take the most saturated, fighter-shaped blobs and keep identity by colour
    continuity across frames.
    """

    def __init__(self, gap_s=0.45):
        self.p1 = self.p2 = None
        self.col1 = self.col2 = None
        self.gap = gap_s
        self.last1 = self.last2 = None
        self.t = 0.0
        self.events = []

    def _blobs(self, small):
        rgb = small.astype(int)
        mx = rgb.max(axis=2)
        mn = rgb.min(axis=2)
        m = ((mx - mn) > 70) & (mx > 150)
        lab, n = ndimage.label(m)
        out = []
        if not n:
            return out
        H2, W2 = m.shape
        for i, sl in enumerate(ndimage.find_objects(lab), start=1):
            if sl is None:
                continue
            ys, xs = sl
            hh, ww = ys.stop - ys.start, xs.stop - xs.start
            area = int((lab[sl] == i).sum())
            if area < 100 or area > 6000:
                continue
            if hh < 40 or hh > 200 or ww < 12 or ww > 120:
                continue
            if ww / max(hh, 1) > 1.25:          # arrows / banners are flat
                continue
            if ys.start < H2 * 0.02:            # must be in the play area
                continue
            col = rgb[sl][lab[sl] == i].mean(axis=0)
            out.append({"x": (xs.start + xs.stop) / 2 / SCALE,
                        "y": (ys.start + ys.stop) / 2 / SCALE,
                        "area": area, "col": col})
        out.sort(key=lambda b: -b["area"])
        return out

    def update(self, img, dt=0.05):
        self.t += dt
        h, w = img.shape[:2]
        crop = img[int(h * CROP_TOP):]
        small = np.asarray(Image.fromarray(crop).resize(
            (int(w * SCALE), int(crop.shape[0] * SCALE)), resample=0))
        blobs = self._blobs(small)

        def dist(a, b):
            return float(np.abs(a - b).sum()) if b is not None else 0.0

        assigned = {"p1": None, "p2": None}
        if len(blobs) >= 2:
            # The two fighters differ in colour from each other and stand at
            # similar heights; scenery (arrows, lamps) does not pair up that way.
            best, best_score = None, -1.0
            for i in range(len(blobs)):
                for j in range(i + 1, len(blobs)):
                    a, b = blobs[i], blobs[j]
                    if abs(a["y"] - b["y"]) > 220:      # fighters can stand on ledges
                        continue
                    ratio = max(a["area"], b["area"]) / max(1, min(a["area"], b["area"]))
                    if ratio > 3.0:
                        continue
                    score = float(np.abs(a["col"] - b["col"]).sum())
                    if score > best_score:
                        best_score, best = score, (a, b)
            if best is not None and best_score >= 40:
                blobs = list(best) + [z for z in blobs if z not in best]
            elif best is not None:
                blobs = sorted(blobs, key=lambda z: -z["area"])

        if blobs:
            if len(blobs) >= 2:
                b = blobs[:2]
                # keep identity by colour when we know it
                if self.col1 is not None and self.col2 is not None:
                    d_same = dist(b[0]["col"], self.col1) + dist(b[1]["col"], self.col2)
                    d_swap = dist(b[0]["col"], self.col2) + dist(b[1]["col"], self.col1)
                    if d_swap < d_same:
                        b = [b[1], b[0]]
                else:
                    b = sorted(b, key=lambda z: z["x"])
                assigned["p1"], assigned["p2"] = b[0], b[1]
                self.col1, self.col2 = b[0]["col"], b[1]["col"]
            else:
                z = blobs[0]
                if self.col1 is not None and dist(z["col"], self.col1) <= dist(z["col"], self.col2):
                    assigned["p1"] = z
                elif self.col2 is not None:
                    assigned["p2"] = z
                else:
                    assigned["p1"] = z
                    self.col1 = z["col"]

        for cls, last, key in (("p1", "last1", "p1"), ("p2", "last2", "p2")):
            z = assigned[cls]
            prev_t = getattr(self, last)
            if z is not None:
                if prev_t is not None and (self.t - prev_t) > self.gap:
                    self.events.append("my_death" if cls == "p1" else "their_death")
                setattr(self, key, z["x"])
                setattr(self, last, self.t)
            else:
                if prev_t is not None and (self.t - prev_t) > self.gap:
                    setattr(self, key, None)

        dx = None if (self.p1 is None or self.p2 is None) else (self.p2 - self.p1)
        return {"p1": self.p1, "p2": self.p2, "dx": dx,
                "n": len(blobs),
                "cols": [None if c is None else c.round().astype(int).tolist()
                         for c in (self.col1, self.col2)]}
