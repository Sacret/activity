#!/usr/bin/env python3
"""Write icons/: the three-bar mark as SVG plus PNG sizes for browsers, iOS and Android."""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "icons")
BLUE = "#2a78d6"
SURFACE = "#fcfcfb"

# Bars on a 16-unit grid: (x, top), all 3 wide, ending at y=15, corner radius 1.
BARS = [(1, 9), (6.5, 5), (12, 1)]

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
{}
</svg>
""".format("\n".join(f'  <rect x="{x}" y="{y}" width="3" height="{15 - y}" rx="1" fill="{BLUE}"/>' for x, y in BARS))


def png(size, background, pad):
    """Draw at 4x and downsample for smooth edges. pad = share of the canvas left empty on each side."""
    s = size * 4
    img = Image.new("RGBA", (s, s), background or (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    unit = s * (1 - 2 * pad) / 16
    off = s * pad
    for x, y in BARS:
        d.rounded_rectangle([off + x * unit, off + y * unit, off + (x + 3) * unit, off + 15 * unit],
                            radius=unit, fill=BLUE)
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "favicon.svg"), "w").write(SVG)
    png(32, None, 0).save(os.path.join(OUT, "favicon-32.png"))
    # Home-screen icons need an opaque background and room around the mark (iOS/Android crop the corners).
    png(180, SURFACE, 0.2).save(os.path.join(OUT, "apple-touch-icon.png"))
    png(192, SURFACE, 0.2).save(os.path.join(OUT, "icon-192.png"))
    png(512, SURFACE, 0.2).save(os.path.join(OUT, "icon-512.png"))
    print("icons:", ", ".join(sorted(os.listdir(OUT))))


if __name__ == "__main__":
    main()
