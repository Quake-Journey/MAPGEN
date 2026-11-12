"""How well-known maps build their water: the knowledge base for deep pools, underwater tubes and water on many levels.

The PO, 12.11, on his mg_new_7775 (3.66, «q2dm1 с призами под водой»): «никакого глубокого бассейна по типу как на q2dm1
в котором плывешь за рейлом - я не получил, только узкая небольшая подводная нычка под стенкой, и внутри ничего нет»,
«на q2dm1 там глубокий большой водоем через который нужно плыть и там еще и труба есть по которой плывут до выхода на
рейл», «на q2dm4 или q2dm5 там вообще многоуровневые конструкции с множеством глубоких водоемов через которые можно
плавать», «ничего подобного я в принципе у тебя не увидел, плоская карта». 3.66's dive was one 64 x 64 cell.

Each liquid of a map, read from its BSP as the game reads it (the contents at a point): a grid of 16 u across and 8 u up
over the liquid brushes' boxes. A column's liquid run is OPEN when air is right over it (one comes up and breathes) and
ROOFED when rock is (one swims under it: a tube, a passage under a ledge). A body is the runs joined side by side.
Per body: its kind, surface, bottom, open area, depth (open runs), roofed area, its tubes (roofed stretches: their
length along the swim) and its pools (open stretches: a body with two pools or more is swum through under a roof),
the items in it or at its rim. Per map: the deep bodies (one swims under: 64 deep or more) and their surface levels.

    python tools/mapgen_water_practice.py            # all the families, writes tools/mapgen_water_practice.json
    python tools/mapgen_water_practice.py q2dm1 q2dm5
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mapgen_map_survey as sv  # noqa: E402
import mapgen_item_practice as ip  # noqa: E402

OUT = HERE / "mapgen_water_practice.json"
H, V = 16, 8                       # the grid: across, up
SOLID, WINDOW, LAVA, SLIME, WATER = 1, 2, 8, 16, 32
LIQ = LAVA | SLIME | WATER
DEEP = 64                          # a man (56) goes under: one swims
MAJORS = ip.MAJOR if hasattr(ip, "MAJOR") else None


def kind_name(c: int) -> str:
    return "lava" if c & LAVA else "slime" if c & SLIME else "water"


def liquid_boxes(w: sv.World) -> list:
    """The boxes of the liquid brushes (their axial sides)."""
    b = w.bsp
    out = []
    for br in b.brushes:
        if not br.contents & LIQ:
            continue
        lo, hi = [-1e9] * 3, [1e9] * 3
        for s in range(br.firstside, br.firstside + br.numsides):
            p = b.planes[b.brushsides[s].planenum]
            for a in range(3):
                if abs(p.normal[a] - 1) < 1e-6:
                    hi[a] = min(hi[a], p.dist)
                elif abs(p.normal[a] + 1) < 1e-6:
                    lo[a] = max(lo[a], -p.dist)
        if all(-1e8 < lo[a] < hi[a] < 1e8 for a in range(3)):
            out.append((lo, hi, br.contents & LIQ))
    return out


def runs_of(w: sv.World, boxes: list) -> list:
    """Each column's liquid runs: (ix, iy, z0, z1, open, kind) - z0 the run's bottom, z1 its top (the surface)."""
    cols: dict = {}
    for lo, hi, _k in boxes:
        for ix in range(int(math.floor(lo[0] / H)), int(math.ceil(hi[0] / H))):
            for iy in range(int(math.floor(lo[1] / H)), int(math.ceil(hi[1] / H))):
                zs = cols.setdefault((ix, iy), set())
                for iz in range(int(math.floor(lo[2] / V)), int(math.ceil(hi[2] / V))):
                    zs.add(iz)
    out = []
    for (ix, iy), zs in cols.items():
        x, y = ix * H + H / 2, iy * H + H / 2
        wet = sorted(iz for iz in zs if w.contents_all(x, y, iz * V + V / 2) & LIQ)
        i = 0
        while i < len(wet):
            j = i
            while j + 1 < len(wet) and wet[j + 1] == wet[j] + 1:
                j += 1
            z0, z1 = wet[i] * V, (wet[j] + 1) * V
            above = w.contents_all(x, y, z1 + V / 2)
            k = w.contents_all(x, y, z1 - V / 2)
            out.append((ix, iy, z0, z1, not above & (SOLID | WINDOW | LIQ), kind_name(k)))
            i = j + 1
    return out


def groups(runs: list, idx: list) -> list:
    """The runs in `idx` joined side by side (4 neighbours, their heights overlapping 8 or more)."""
    at: dict = {}
    for i in idx:
        at.setdefault((runs[i][0], runs[i][1]), []).append(i)
    seen, out = set(), []
    for i in idx:
        if i in seen:
            continue
        comp, stack = [], [i]
        seen.add(i)
        while stack:
            a = stack.pop()
            comp.append(a)
            ax, ay, a0, a1 = runs[a][:4]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                for b in at.get((ax + dx, ay + dy), []):
                    if b not in seen and min(a1, runs[b][3]) - max(a0, runs[b][2]) >= V:
                        seen.add(b)
                        stack.append(b)
        out.append(comp)
    return out


def span(runs: list, comp: list) -> float:
    """A stretch's length along the swim: the longest of the shortest ways across it (two sweeps), in units."""
    cells = {(runs[i][0], runs[i][1]) for i in comp}

    def far(src):
        d = {src: 0}
        q = [src]
        for c in q:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n in cells and n not in d:
                    d[n] = d[c] + 1
                    q.append(n)
        t = max(d, key=d.get)
        return t, d[t]
    a, _ = far(next(iter(cells)))
    _b, n = far(a)
    return (n + 1) * H


def study(path: str) -> dict:
    w = sv.World(Path(path))
    runs = runs_of(w, liquid_boxes(w))
    items = []
    for e in w.ents:
        cls = e.get("classname", "")
        if ip.kind_of(cls):
            items.append((cls, sv.fvec(e.get("origin", ""))))
    bodies = []
    for comp in groups(runs, list(range(len(runs)))):
        if len(comp) * H * H < 64 * 64:
            continue                     # a trickle: not a body one moves in
        opens = [i for i in comp if runs[i][4]]
        roofed = [i for i in comp if not runs[i][4]]
        depths = sorted(runs[i][3] - runs[i][2] for i in opens)
        pools = sorted(([round(len(c) * H * H), max(runs[i][3] for i in c),
                         max(runs[i][3] - runs[i][2] for i in c)] for c in groups(runs, opens)
                        if len(c) * H * H >= 32 * 32), reverse=True)
        tubes = sorted(([span(runs, c), round(len(c) * H * H), min(runs[i][3] - runs[i][2] for i in c)]
                        for c in groups(runs, roofed) if len(c) * H * H >= 32 * 32), reverse=True)
        xs = [runs[i][0] for i in comp]
        ys = [runs[i][1] for i in comp]
        z0 = min(runs[i][2] for i in comp)
        z1 = max(runs[i][3] for i in comp)
        foot = {(runs[i][0], runs[i][1]): (runs[i][2], runs[i][3]) for i in comp}
        inside = []
        for cls, (x, y, z) in items:
            c = (int(math.floor(x / H)), int(math.floor(y / H)))
            near = [foot.get((c[0] + dx, c[1] + dy)) for dx in range(-4, 5) for dy in range(-4, 5)]
            near = [r for r in near if r]
            if near and min(r[0] for r in near) - 16 <= z <= max(r[1] for r in near) + 96:
                sub = c in foot and foot[c][0] - 8 <= z <= foot[c][1]
                inside.append([cls, "in" if sub else "rim"])
        bodies.append({
            "kind": kind_name(0) if not comp else runs[comp[0]][5],
            "surface": z1, "bottom": z0,
            "box": [min(xs) * H, min(ys) * H, (max(xs) + 1) * H, (max(ys) + 1) * H],
            "open_area": len(opens) * H * H, "roofed_area": len(roofed) * H * H,
            "depth_max": depths[-1] if depths else 0,
            "depth_p50": depths[len(depths) // 2] if depths else 0,
            "pools": pools, "tubes": tubes, "items": inside,
        })
    bodies.sort(key=lambda b: -(b["open_area"] + b["roofed_area"]))
    deep = [b for b in bodies if b["depth_max"] >= DEEP or b["roofed_area"] >= 64 * 64]
    levels = sorted({int(round(b["surface"] / 32.0) * 32) for b in deep})
    return {"bodies": bodies, "deep": len(deep), "levels": levels,
            "liquid_area": sum(b["open_area"] for b in bodies)}


def _work(p):
    name, path = p
    try:
        return name, study(str(path))
    except Exception as ex:          # a map the reader cannot take is said, not hidden
        return name, {"error": repr(ex)}


def summary(db: dict) -> str:
    lines = []
    for name, m in db.items():
        if "error" in m:
            lines.append(f"{name:12s} ERROR {m['error']}")
            continue
        if not m["bodies"]:
            continue
        lines.append(f"{name:12s} deep bodies {m['deep']}, their levels {m['levels']}, liquid {m['liquid_area'] / 4096:.0f} cells of 64")
        for b in m["bodies"][:6]:
            pools = ", ".join(f"{a / 4096:.1f}c@{s} d{d}" for a, s, d in b["pools"][:4])
            tubes = ", ".join(f"{L:.0f}u/{a / 4096:.1f}c h{h}" for L, a, h in b["tubes"][:4])
            it = ", ".join(f"{c}({w_})" for c, w_ in b["items"])
            lines.append(f"   {b['kind']:5s} surf {b['surface']:5.0f} bottom {b['bottom']:5.0f} depth max {b['depth_max']:3.0f} p50 {b['depth_p50']:3.0f}"
                         f"  open {b['open_area'] / 4096:5.1f}c roofed {b['roofed_area'] / 4096:4.1f}c | pools [{pools}] | tubes [{tubes}]"
                         + (f" | {it}" if it else ""))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("MAPGEN_PRESET_WORKERS", "4")))
    a = ap.parse_args()
    fam = ip.family_maps(ip.GAME)
    names = [m.lower() for m in a.maps] or list(fam)
    todo = [(n, fam[n]) for n in names if n in fam]
    with multiprocessing.Pool(max(1, min(a.workers, len(todo)))) as pool:
        db = dict(sorted(pool.map(_work, todo)))
    print(summary(db))
    if not a.maps:
        OUT.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
