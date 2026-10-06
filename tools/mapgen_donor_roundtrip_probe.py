r"""Why the generator refuses a donor at its first step: what the rebuilt copy of the map draws differently, and
whether a player can see it (ledger row 399, the PO's first donors besides q2dm1 - q3t2 and cor, 2026-10-03).

    python tools/mapgen_donor_roundtrip_probe.py DONOR.bsp BASELINE.bsp [--equiv EQUIV_OUTPUT.txt]

The pipeline rebuilds the donor from its own BSP (brushes back to a .map, compiled again) and refuses the donor
(ERR_BASELINE) when the equivalence oracle finds the copy different. This reads both files and says, per texture
group that is only in one of them (the oracle's `surfdiff` lines when its output is given, else the faces' own
planes compared), where it is and what lies in front of it in EACH map - air (a player may see it) or rock (no
one can) - and, separately, the donor's brush sides with no texture and the brushes they belong to by contents
(the rebuilt .map writes such a side as e1u1/clip; on a solid brush the compiler then DRAWS it).
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

CONTENTS_SOLID = 0x1
CONTENTS_WINDOW = 0x2


class Bsp:
    def __init__(self, path: Path):
        self.d = d = path.read_bytes()
        if d[:4] != b"IBSP" or struct.unpack_from("<i", d, 4)[0] != 38:
            raise SystemExit(f"{path} is not a Quake II map")
        self.lump = [struct.unpack_from("<ii", d, 8 + 8 * i) for i in range(19)]
        self.planes = self._rows(1, 20, "<ffffi")
        self.vertices = self._rows(2, 12, "<fff")
        self.nodes = self._rows(4, 28, "<iii6hHH")
        self.texinfo = [(r[8], r[9], d[o + 40:o + 72].split(b"\0")[0].decode("latin1"))
                        for r, o in self._rows_at(5, 76, "<8fii")]
        self.faces = self._rows(6, 20, "<HhihhBBBBi")
        self.leafs = self._rows(8, 28, "<ihh6hHHHH")
        self.edges = self._rows(11, 4, "<HH")
        self.surfedges = self._rows(12, 4, "<i")
        self.models = self._rows(13, 48, "<9fiii")
        self.brushes = self._rows(14, 12, "<iii")
        self.sides = self._rows(15, 4, "<Hh")

    def _rows_at(self, lump: int, size: int, fmt: str):
        o, n = self.lump[lump]
        return [(struct.unpack_from(fmt, self.d, o + i * size), o + i * size) for i in range(n // size)]

    def _rows(self, lump: int, size: int, fmt: str):
        return [r for r, _ in self._rows_at(lump, size, fmt)]

    def contents(self, p) -> int:
        """The contents of the world leaf a point falls in."""
        n = self.models[0][9]
        while n >= 0:
            planenum, front, back = self.nodes[n][:3]
            nx, ny, nz, dist, _ = self.planes[planenum]
            n = front if p[0] * nx + p[1] * ny + p[2] * nz - dist >= 0 else back
        return self.leafs[-1 - n][0]

    def face_points(self, f):
        first, num = f[2], f[3]
        pts = []
        for k in range(num):
            e = self.surfedges[first + k][0]
            a, b = self.edges[abs(e)]
            pts.append(self.vertices[a if e >= 0 else b])
        return pts

    def face_normal(self, f):
        nx, ny, nz, dist, _ = self.planes[f[0]]
        return (-nx, -ny, -nz, -dist) if f[1] else (nx, ny, nz, dist)

    def world_faces(self):
        m = self.models[0]
        return range(m[10], m[10] + m[11])


def area(pts) -> float:
    if len(pts) < 3:
        return 0.0
    ax = ay = az = 0.0
    x0, y0, z0 = pts[0]
    for (x1, y1, z1), (x2, y2, z2) in zip(pts[1:], pts[2:]):
        ux, uy, uz = x1 - x0, y1 - y0, z1 - z0
        vx, vy, vz = x2 - x0, y2 - y0, z2 - z0
        ax += uy * vz - uz * vy
        ay += uz * vx - ux * vz
        az += ux * vy - uy * vx
    return 0.5 * (ax * ax + ay * ay + az * az) ** 0.5


def front_says(bsp: Bsp, pts, normal) -> str:
    """What is 2 units in front of the face's middle: «air» a player may stand or look in, or «rock»."""
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    cz = sum(p[2] for p in pts) / len(pts)
    q = (cx + normal[0] * 2, cy + normal[1] * 2, cz + normal[2] * 2)
    c = bsp.contents(q)
    return "rock" if c & (CONTENTS_SOLID | CONTENTS_WINDOW) else f"air(0x{c:x})"


def groups(bsp: Bsp):
    """World faces by (texture, plane rounded) -> [(points, normal)]."""
    out = defaultdict(list)
    for i in bsp.world_faces():
        f = bsp.faces[i]
        nx, ny, nz, dist = bsp.face_normal(f)
        name = bsp.texinfo[f[4]][2].lower() if f[4] >= 0 else "-"
        key = (name, round(nx, 3), round(ny, 3), round(nz, 3), round(dist, 1))
        out[key].append((bsp.face_points(f), (nx, ny, nz)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("donor", type=Path)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("--equiv", type=Path, help="the equivalence driver's output, for its surfdiff lines")
    a = ap.parse_args()
    donor, base = Bsp(a.donor), Bsp(a.baseline)
    gd, gb = groups(donor), groups(base)

    print(f"donor {a.donor.name}: {len(donor.brushes)} brushes, {len(donor.sides)} sides")
    untextured = Counter()
    for first, n, contents in donor.brushes:
        k = sum(1 for j in range(n) if donor.sides[first + j][1] < 0)
        if k:
            untextured[contents] += 1
    for contents, count in sorted(untextured.items()):
        drawn = "SOLID - the rebuilt copy draws these sides as e1u1/clip" if contents & (CONTENTS_SOLID | CONTENTS_WINDOW) \
            else "not drawn either way"
        print(f"  brushes with untextured sides, contents 0x{contents:x}: {count}  ({drawn})")

    def report(title, only_in, other, key_set):
        total = Counter()
        print(f"\n{title}")
        for key in key_set:
            faces = only_in[key]
            a_sum = sum(area(p) for p, _ in faces)
            says = Counter(front_says(other_bsp, p, n) + "/" + front_says(own_bsp, p, n) for p, n in faces)
            total[next(iter(says))] += a_sum
            print(f"  {key[0]:28s} normal {key[1]:+.3f} {key[2]:+.3f} {key[3]:+.3f} dist {key[4]:8.1f} area {a_sum:9.1f}"
                  f"  in front (other map / this map): {dict(says)}")
        return total

    # by the oracle's own lines when given: the groups it named; else every group on one side only
    named = set()
    if a.equiv and a.equiv.is_file():
        for m in re.finditer(r"^surfdiff (donor-only|baseline-only)\s+(\S+)\s+flags \S+ value \S+ model 0 normal "
                             r"(\S+) (\S+) (\S+) dist (\S+)", a.equiv.read_text(encoding="utf-8", errors="replace"), re.M):
            named.add((m.group(1), m.group(2).lower(), round(float(m.group(3)), 3), round(float(m.group(4)), 3),
                       round(float(m.group(5)), 3), round(float(m.group(6)), 1)))
    only_donor = [k for k in gd if k not in gb]
    only_base = [k for k in gb if k not in gd]
    if named:
        only_donor = [k for k in only_donor if ("donor-only",) + k in named] or only_donor
        only_base = [k for k in only_base if ("baseline-only",) + k in named] or only_base
    global own_bsp, other_bsp
    own_bsp, other_bsp = donor, base
    t1 = report("drawn in the DONOR only:", gd, gb, sorted(only_donor, key=lambda k: -sum(area(p) for p, _ in gd[k])))
    own_bsp, other_bsp = base, donor
    t2 = report("drawn in the REBUILT COPY only:", gb, gd, sorted(only_base, key=lambda k: -sum(area(p) for p, _ in gb[k])))
    print("\narea by what is in front (other map / this map):")
    for title, t in (("donor only", t1), ("copy only", t2)):
        for k, v in t.most_common():
            print(f"  {title:10s} {k:28s} {v:10.1f}")
    return 0


own_bsp = other_bsp = None

if __name__ == "__main__":
    sys.exit(main())
