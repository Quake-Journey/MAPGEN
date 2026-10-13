r"""The brushes of a .map (Valve or standard) inside a box, with their true bounds (from the planes' corners) and
textures - for reading the PO's finished maps where a screenshot shows something wrong (the PO, 08.10, quake239:
architecture hanging in the sky).

    python tools/mapgen_map_brushes_in_box.py MAP.map X0 Y0 Z0 X1 Y1 Z1 [--all-entities]
"""
from __future__ import annotations

import itertools
import re
import sys

PT = re.compile(r"\( ([-\d.e+]+) ([-\d.e+]+) ([-\d.e+]+) \)")


def planes_of(block: str) -> list[tuple[tuple[float, float, float], float, str]]:
    out = []
    for line in block.strip().split("\n"):
        p = [tuple(float(v) for v in m) for m in PT.findall(line)]
        if len(p) < 3:
            continue
        a, b, c = p[:3]
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        # quake's planes: the normal from (c - a) x (b - a) points out of the brush
        n = (v[1] * u[2] - v[2] * u[1], v[2] * u[0] - v[0] * u[2], v[0] * u[1] - v[1] * u[0])
        L = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
        if L < 1e-9:
            continue
        n = (n[0] / L, n[1] / L, n[2] / L)
        tex = line.split(")")[3].split()[0]
        out.append((n, n[0] * a[0] + n[1] * a[1] + n[2] * a[2], tex))
    return out


def corners(planes) -> list[tuple[float, float, float]]:
    pts = []
    for (n1, d1, _), (n2, d2, _), (n3, d3, _) in itertools.combinations(planes, 3):
        det = (n1[0] * (n2[1] * n3[2] - n2[2] * n3[1]) - n1[1] * (n2[0] * n3[2] - n2[2] * n3[0])
               + n1[2] * (n2[0] * n3[1] - n2[1] * n3[0]))
        if abs(det) < 1e-9:
            continue
        # Cramer's rule
        def col(i, j):
            return [[d1, n1[1], n1[2]], [d2, n2[1], n2[2]], [d3, n3[1], n3[2]]] if j == 0 else None
        x = (d1 * (n2[1] * n3[2] - n2[2] * n3[1]) - n1[1] * (d2 * n3[2] - n2[2] * d3) + n1[2] * (d2 * n3[1] - n2[1] * d3)) / det
        y = (n1[0] * (d2 * n3[2] - n2[2] * d3) - d1 * (n2[0] * n3[2] - n2[2] * n3[0]) + n1[2] * (n2[0] * d3 - d2 * n3[0])) / det
        z = (n1[0] * (n2[1] * d3 - d2 * n3[1]) - n1[1] * (n2[0] * d3 - d2 * n3[0]) + d1 * (n2[0] * n3[1] - n2[1] * n3[0])) / det
        if all(n[0] * x + n[1] * y + n[2] * z <= d + 0.05 for n, d, _ in planes):
            pts.append((x, y, z))
    return pts


def main() -> int:
    if len(sys.argv) < 8:
        print(__doc__)
        return 2
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    box = [float(v) for v in sys.argv[2:8]]
    every = "--all-entities" in sys.argv
    world_end = len(text) if every else text.find('\n"classname"', text.find('"classname" "worldspawn"') + 10)
    world = text[:world_end if world_end > 0 else len(text)]
    n = 0
    for block in re.findall(r"\{\n((?:\( [^\n]*\n)+)\}", world):
        planes = planes_of(block)
        pts = corners(planes)
        if not pts:
            continue
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        if all(hi[i] >= box[i] and lo[i] <= box[3 + i] for i in range(3)):
            tex = sorted({t for _, _, t in planes})
            print(f"{lo[0]:7.0f} {lo[1]:7.0f} {lo[2]:6.0f} .. {hi[0]:7.0f} {hi[1]:7.0f} {hi[2]:6.0f}  {' '.join(tex)}")
            n += 1
    print(f"{n} brushes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
