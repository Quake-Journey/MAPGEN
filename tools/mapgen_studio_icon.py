"""
MAPGEN Studio's own icon (Fable's brief 13 W6; the PO, 07.10: «у окошка программы нет иконки»).

A map's plan seen from above - rooms joined by corridors, in the Studio's blue on its dark ground - with a crack
across it (the generator breaks what it builds). Each size is drawn on its own, at four times its size and brought
down, so the lines stay whole at 16 and 24 instead of a 256 picture shrunk to mush. One .ico, sizes 16..256:

    python tools/mapgen_studio_icon.py          -> tools/mapgen_studio/MapgenStudio/Assets/mapgen_studio.ico

The .ico is kept in the repository; this script is how it was made, and how to make it again.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "mapgen_studio" / "MapgenStudio" / "Assets" / "mapgen_studio.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)
GROUND = (24, 32, 48, 255)
EDGE = (52, 68, 96, 255)
BLUE = (59, 142, 234, 255)
FLOOR = (59, 142, 234, 70)
CRACK = (255, 176, 64, 255)

# the plan, in a unit square: rooms (x0, y0, x1, y1) and the corridors between them (polylines)
ROOMS = [(0.16, 0.16, 0.44, 0.40), (0.58, 0.18, 0.84, 0.46), (0.16, 0.58, 0.40, 0.84), (0.56, 0.62, 0.84, 0.84)]
CORRIDORS = [[(0.44, 0.28), (0.58, 0.28)], [(0.28, 0.40), (0.28, 0.58)], [(0.71, 0.46), (0.71, 0.62)],
             [(0.40, 0.73), (0.56, 0.73)]]
CRACKLINE = [(0.80, 0.06), (0.70, 0.22), (0.76, 0.30), (0.58, 0.46), (0.62, 0.54), (0.44, 0.62), (0.48, 0.72),
             (0.30, 0.94)]


def draw(size: int) -> Image.Image:
    k = 4
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # line widths in final pixels, never under what survives at that size
    line = max(1.25, size / 40.0) * k
    crack = max(1.5, size / 28.0) * k
    small = size <= 24
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.18, fill=GROUND, outline=EDGE, width=max(k, int(s / 64)))

    def p(x: float, y: float) -> tuple[float, float]:
        return x * s, y * s

    rooms = ROOMS if not small else [(0.14, 0.14, 0.44, 0.42), (0.56, 0.58, 0.86, 0.86)]
    corridors = CORRIDORS if not small else [[(0.44, 0.28), (0.71, 0.28), (0.71, 0.58)]]
    for r in rooms:
        d.rectangle((*p(r[0], r[1]), *p(r[2], r[3])), fill=FLOOR, outline=BLUE, width=int(line))
    for c in corridors:
        d.line([p(*q) for q in c], fill=BLUE, width=int(line * (1.6 if not small else 1.0)), joint="curve")
    # the crack: a dark fissure through the plan, its edges glowing - a tapering polygon, wide in the middle
    def fissure(w: float, colour: tuple) -> None:
        n = len(CRACKLINE)
        left, right = [], []
        for i, (x, y) in enumerate(CRACKLINE):
            a, b = CRACKLINE[max(i - 1, 0)], CRACKLINE[min(i + 1, n - 1)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln = (dx * dx + dy * dy) ** 0.5 or 1.0
            half = w * (0.25 + 0.75 * (1.0 - abs(2.0 * i / (n - 1) - 1.0))) / s
            left.append(p(x - dy / ln * half, y + dx / ln * half))
            right.append(p(x + dy / ln * half, y - dx / ln * half))
        d.polygon(left + right[::-1], fill=colour)
    fissure(crack * 1.3, CRACK)
    fissure(crack * 0.55, GROUND)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [draw(n) for n in SIZES]
    big = frames[-1]
    big.save(OUT, format="ICO", sizes=[(n, n) for n in SIZES], append_images=frames[:-1])
    got = sorted(Image.open(OUT).info.get("sizes", set()))
    want = sorted((n, n) for n in SIZES)
    if got != want:
        print(f"the icon holds {got}, not {want}", file=sys.stderr)
        return 1
    print(f"{OUT}: {', '.join(str(n) for n in SIZES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
