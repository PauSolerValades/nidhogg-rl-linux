"""Track the two fighters in Nidhogg from window captures, without game state.

The fighters are the only things that move, so a running background model plus
frame differencing isolates them regardless of the level's colours. Their screen
x is what a policy actually needs (the camera follows the fight, so the pair is
always centred).
"""
import numpy as np
from PIL import Image
import nav

W_TARGET = 480


class Tracker:
    def __init__(self, history=12, min_area=25):
        self.history = history
        self.min_area = min_area
        self.prev = None

    def frame(self):
        img = nav.capture()
        if img is None:
            return None, None
        h, w = img.shape[:2]
        s = W_TARGET / w
        small = np.asarray(Image.fromarray(img).resize(
            (W_TARGET, max(1, int(h * s))), resample=1))
        return img, small.astype(np.int16)

    def blobs(self, small):
        """Return up to two (x, y, area, colour) blobs, biggest first."""
        g = small.mean(axis=2)
        if self.prev is None:
            self.prev = g
            return []
        diff = np.abs(g - self.prev)
        self.prev = 0.7 * self.prev + 0.3 * g          # slow background model
        mask = diff > 26
        if mask.sum() < self.min_area:
            return []
        # collect connected components with a cheap two-pass flood fill
        H, W = mask.shape
        seen = np.zeros_like(mask, dtype=bool)
        out = []
        for y0 in range(0, H, 4):
            for x0 in range(0, W, 4):
                if not mask[y0, x0] or seen[y0, x0]:
                    continue
                stack = [(y0, x0)]
                seen[y0, x0] = True
                pts = []
                while stack:
                    y, x = stack.pop()
                    pts.append((y, x))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                if len(pts) < self.min_area:
                    continue
                ys = np.array([p[0] for p in pts])
                xs = np.array([p[1] for p in pts])
                col = small[ys, xs].mean(axis=0)
                out.append((float(xs.mean()), float(ys.mean()), len(pts), col))
        out.sort(key=lambda b: -b[2])
        return out[:2]


def describe(small, blobs):
    if not blobs:
        return "no movement"
    parts = []
    for x, y, a, col in blobs:
        parts.append(f"x={x / W_TARGET:.3f} y={y / small.shape[0]:.2f} area={a} rgb={col.astype(int).tolist()}")
    return " | ".join(parts)
