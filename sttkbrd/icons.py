import os

from PIL import Image, ImageDraw, ImageOps

from . import paths
from .log import log

SOURCE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "art", "icon.png")
CACHE = os.path.join(paths.cache_dir(), "icons2")
SIZE = 128
BADGES = {"idle": None, "auto": (30, 120, 255), "rec": (230, 40, 40), "busy": (255, 170, 0), "error": None}
WHOLE_RED = "error"  # no badge: the whole icon turns red


def _transparent_corners(img):
    """The black background outside the rounded square becomes transparent."""
    img = img.convert("RGBA")
    w, h = img.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(img, corner, (0, 0, 0, 0), thresh=40)
    return img


def build():
    """Build icon variants and return {state: path}. Falls back to a theme icon name."""
    paths = {}
    try:
        os.makedirs(CACHE, exist_ok=True)
        stamp = os.path.getmtime(SOURCE)
        base = None
        for state, color in BADGES.items():
            path = os.path.join(CACHE, state + ".png")
            if not os.path.exists(path) or os.path.getmtime(path) < stamp:
                if base is None:
                    base = _transparent_corners(Image.open(SOURCE).resize((SIZE, SIZE), Image.LANCZOS))
                img = base.copy()
                if state == WHOLE_RED:
                    alpha = img.getchannel("A")
                    img = ImageOps.colorize(ImageOps.grayscale(img), black=(70, 0, 0), white=(255, 90, 90)).convert("RGBA")
                    img.putalpha(alpha)
                if color:
                    d = ImageDraw.Draw(img)
                    r = SIZE * 0.20
                    box = (SIZE - r * 2 - 2, SIZE - r * 2 - 2, SIZE - 2, SIZE - 2)
                    d.ellipse(box, fill=color + (255,), outline=(255, 255, 255, 255), width=4)
                img.save(path)
            paths[state] = path
    except Exception:
        log.exception("Could not build icons from %s", SOURCE)
        return {s: "audio-input-microphone-symbolic" for s in BADGES}
    return paths
