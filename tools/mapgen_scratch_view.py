r"""Brief 19: the skeleton seen in three dimensions - an isometric cut-away of every floor at its height, the walls
cut low, the doors, flights, overlooks, items and spawns - so a plan is judged by eye before a brush is written
(and Fable reviews the first skeletons as pictures, brief 19 §7.1).

    python tools/mapgen_scratch_view.py --players 2 --seed 7 --out view.png
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_scratch_plan as pm  # noqa: E402

ITEM_COLOURS = {"weapon_": (235, 60, 50), "item_armor_body": (255, 60, 200), "item_armor_combat": (250, 220, 40),
                "item_armor_jacket": (120, 200, 60), "item_health_mega": (60, 140, 255), "item_adrenaline": (240, 240, 240),
                "item_quad": (110, 80, 255)}


def item_colour(cls):
    for k, v in ITEM_COLOURS.items():
        if cls.startswith(k):
            return v
    return None


def view(P, path: Path, cell_px: int = 16, angle: int = 0) -> None:
    from PIL import Image, ImageDraw
    cols = {}            # cell -> (top z, kind, colour)
    zmax = 1
    for s in P.spaces:
        if s.solid:
            continue
        for c, f in s.floor.items():
            z = pm.floor_top(f)
            zmax = max(zmax, z)
    for s in P.spaces:
        if s.solid:
            continue
        for c, f in s.floor.items():
            z, kind, sx, sy = f
            t = pm.floor_top(f) / max(1, zmax)
            base = (int(70 + 150 * t), int(110 + 80 * math.sin(math.pi * t)), int(210 - 150 * t))
            if s.sky:
                base = tuple(min(255, v + 30) for v in base)
            if kind == "stair":
                base = (225, 225, 215)
            cols[c] = (pm.floor_top(f) if kind != "stair" else z + 16, "floor", base, s.id)
    for d in P.doors:
        for c in d.cells:
            colour = {"door": (240, 200, 70), "drop": (240, 120, 60), "overlook": (200, 120, 240)}.get(d.kind,
                                                                                                    (240, 200, 70))
            cols[c] = (d.z + (16 if d.stair else 0), "door", colour, -1)
    # walls: every cell next to a floor that is not floor, cut low over the floors beside it
    walls = {}
    for (x, y), (z, k, colour, sid) in list(cols.items()):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if n in cols:
                    continue
                walls[n] = max(walls.get(n, -9999), z + 112)
    for (cells, z0, z1, *_w) in P.windows:
        for c in cells:
            if c in walls:
                walls[c] = min(walls[c], z0)
    zmin = min(z for z, *_ in cols.values()) - 64
    a = cell_px * 0.866
    bpx = cell_px * 0.5
    kz = cell_px / 64.0
    allc = list(cols) + list(walls)
    minx = min(c[0] for c in allc)
    maxx = max(c[0] for c in allc)
    miny = min(c[1] for c in allc)
    maxy = max(c[1] for c in allc)

    def proj(x, y, z):
        return ((x - y) * a, -(x + y) * bpx - z * kz)

    xs, ys = [], []
    for x in (minx, maxx + 1):
        for y in (miny, maxy + 1):
            for z in (zmin, zmax + 200):
                px, py = proj(x, y, z)
                xs.append(px)
                ys.append(py)
    ox, oy = -min(xs) + 20, -min(ys) + 20
    W = int(max(xs) - min(xs) + 40)
    H = int(max(ys) - min(ys) + 40)
    img = Image.new("RGB", (W, H), (22, 22, 26))
    dr = ImageDraw.Draw(img)

    def P2(x, y, z):
        px, py = proj(x, y, z)
        return (px + ox, py + oy)

    def shade(colour, f):
        return tuple(max(0, min(255, int(v * f))) for v in colour)

    blocks = []
    for c, (z, k, colour, sid) in cols.items():
        blocks.append((c, z, colour))
    for c, z in walls.items():
        blocks.append((c, z, (95, 95, 100)))
    # far to near: the viewer stands at low x+y (screen bottom is x+y small after the minus); draw high x+y first
    blocks.sort(key=lambda t: -(t[0][0] + t[0][1]))
    for (x, y), z, colour in blocks:
        top = [P2(x, y, z), P2(x + 1, y, z), P2(x + 1, y + 1, z), P2(x, y + 1, z)]
        # the faces toward the viewer: -x and -y sides
        side_x = [P2(x, y, z), P2(x, y + 1, z), P2(x, y + 1, zmin), P2(x, y, zmin)]
        side_y = [P2(x, y, z), P2(x + 1, y, z), P2(x + 1, y, zmin), P2(x, y, zmin)]
        dr.polygon(side_x, fill=shade(colour, 0.55), outline=shade(colour, 0.4))
        dr.polygon(side_y, fill=shade(colour, 0.75), outline=shade(colour, 0.5))
        dr.polygon(top, fill=colour, outline=shade(colour, 0.8))
    for (cls, c, z, note) in P.items:
        col = item_colour(cls)
        if not col:
            continue
        px, py = P2(c[0] + 0.5, c[1] + 0.5, z + 24)
        dr.ellipse([px - 5, py - 5, px + 5, py + 5], fill=col, outline=(0, 0, 0))
    for (c, z, ang) in P.spawns:
        px, py = P2(c[0] + 0.5, c[1] + 0.5, z + 24)
        dr.polygon([(px, py - 7), (px + 6, py), (px, py + 7), (px - 6, py)], fill=(40, 240, 240), outline=(0, 0, 0))
    img.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--tries", type=int, default=40)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    plans = pm.best_plan({"players": a.players}, a.seed, a.tries)
    view(plans[0], a.out)
    print(plans[0].seed, plans[0].metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
