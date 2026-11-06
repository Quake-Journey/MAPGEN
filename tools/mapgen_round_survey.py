r"""How a people's map uses round shapes (the PO, 05.11: «добавь опыт для новых карт с medusa_b1 - тут необычная
архитектура, есть закругленные части, возвышения над уровнем ниже тоже закругленные плоские и т.д. - я хочу, чтобы
подобное тоже можно было выбирать и настраивать в студии для генерации новых карт»).

From the compiled brushes: the walls' directions (a round wall is many short faces turning a little each, an
axis-aligned map has four), the brushes whose top is a flat cap with many sides (a round or polygonal platform -
its side count, its radius, its height over the floor around it), the curved runs of wall faces (an arc: neighbouring
faces 5..30 degrees apart, their radius from the turn), and the share of the walls not on the two axes.

    python tools/mapgen_round_survey.py MAP.bsp [MAP2.bsp ...] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_bsp_oracle as oracle  # noqa: E402

C_SOLID = 1
C_DETAIL = 0x8000000


def brush_planes(b, br):
    out = []
    for s in range(br.firstside, br.firstside + br.numsides):
        side = b.brushsides[s]
        pl = b.planes[side.planenum]
        n = pl.normal
        d = pl.dist
        out.append((n, d, side))
    return out


def brush_box(planes):
    """The brush's box from its axial planes (Quake II brushes carry the six axial sides)."""
    lo = [-1e9, -1e9, -1e9]
    hi = [1e9, 1e9, 1e9]
    for n, d, _s in planes:
        for k in range(3):
            if abs(n[k] - 1) < 1e-6 and abs(n[(k + 1) % 3]) < 1e-6 and abs(n[(k + 2) % 3]) < 1e-6:
                hi[k] = min(hi[k], d)
            elif abs(n[k] + 1) < 1e-6 and abs(n[(k + 1) % 3]) < 1e-6 and abs(n[(k + 2) % 3]) < 1e-6:
                lo[k] = max(lo[k], -d)
    return lo, hi


def survey(path: Path) -> dict:
    b = oracle.load(path)
    world = b.models[0]
    first, count = world.firstbrush if hasattr(world, "firstbrush") else 0, len(b.brushes)
    walls_dirs = {}
    caps = []                     # (sides, radius, height, top z, centre)
    wall_area_axis = wall_area_off = 0.0
    for br in b.brushes:
        if not (br.contents & C_SOLID):
            continue
        planes = brush_planes(b, br)
        lo, hi = brush_box(planes)
        if any(abs(v) >= 1e8 for v in lo + hi):
            continue
        size = [hi[k] - lo[k] for k in range(3)]
        # vertical sides not on the axes: their directions (degrees, folded to 0..180)
        vert = [(n, d) for n, d, _s in planes if abs(n[2]) < 0.05]
        off = [(n, d) for n, d in vert if not (abs(abs(n[0]) - 1) < 1e-4 or abs(abs(n[1]) - 1) < 1e-4)]
        for n, _d in vert:
            ang = round(math.degrees(math.atan2(n[1], n[0])) % 180)
            walls_dirs[ang] = walls_dirs.get(ang, 0) + 1
        face = size[2] * (size[0] + size[1])
        if off:
            wall_area_off += face
        else:
            wall_area_axis += face
        # a cap: a flat-topped brush with 6 or more vertical sides (axial ones included), wider than tall
        if len(vert) >= 6 and size[2] <= max(size[0], size[1]) and min(size[0], size[1]) >= 48:
            cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
            caps.append({"sides": len(vert), "w": round(size[0]), "d": round(size[1]), "h": round(size[2]),
                         "top": round(hi[2]), "at": [round(cx), round(cy)]})
    dirs = sorted(walls_dirs.items(), key=lambda kv: -kv[1])
    on_axes = sum(v for a, v in walls_dirs.items() if a in (0, 90, 180))
    allv = sum(walls_dirs.values()) or 1
    caps.sort(key=lambda c: -c["w"] * c["d"])
    ents = b.entities()
    return {"map": path.stem, "brushes": len(b.brushes), "wall_dirs_top": dirs[:16], "walls_on_axes": round(on_axes / allv, 3),
            "distinct_dirs": len(walls_dirs), "round_caps": len(caps), "caps": caps[:25],
            "wall_area_off_axes": round(wall_area_off / max(1.0, wall_area_off + wall_area_axis), 3),
            "worldspawn": {k: v for k, v in (ents[0] if ents else {}).items() if k in ("message", "sky")}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    out = [survey(p) for p in a.maps]
    for r in out:
        print(f"== {r['map']}: {r['brushes']} brushes, walls on the axes {r['walls_on_axes']:.0%}, "
              f"{r['distinct_dirs']} directions, off-axis wall area {r['wall_area_off_axes']:.0%}, {r['round_caps']} many-sided caps")
        print("   directions:", r["wall_dirs_top"])
        for c in r["caps"][:15]:
            print("   cap", c)
    if a.json:
        a.json.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
