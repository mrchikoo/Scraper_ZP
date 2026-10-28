"""Generate the placeholder app icon (packaging/build/app.ico) with Pillow.

Original artwork drawn from simple shapes: a rounded teal square with a white
paper-plane-ish "Z". No fonts or third-party assets are used, so it renders the
same on every build machine. Replace with a real icon later by dropping a
file at packaging/icon.ico (it is preferred when present).

Usage:  python packaging/make_icon.py   -> prints the path of the .ico
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "build"
OUT = OUT_DIR / "app.ico"
CUSTOM = HERE / "icon.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size: int = 256):
    from PIL import Image, ImageDraw

    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = round(s * 0.04)
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=round(s * 0.22), fill=(15, 118, 110, 255))
    # A bold "Z" built from three polygons.
    m = s * 0.24          # margin inside the tile
    t = s * 0.13          # stroke thickness
    left, right, top, bottom = m, s - m, m, s - m
    white = (255, 255, 255, 255)
    d.rectangle([left, top, right, top + t], fill=white)
    d.rectangle([left, bottom - t, right, bottom], fill=white)
    d.polygon([(right - t * 1.25, top + t), (right, top + t),
               (left + t * 1.25, bottom - t), (left, bottom - t)], fill=white)
    return img


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if CUSTOM.is_file():
        shutil.copyfile(CUSTOM, OUT)
    else:
        try:
            img = draw(256)
        except ImportError:
            print("Pillow is required: pip install pillow", file=sys.stderr)
            return 1
        img.save(OUT, format="ICO", sizes=[(n, n) for n in SIZES])
        img.save(OUT_DIR / "app.png")
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
