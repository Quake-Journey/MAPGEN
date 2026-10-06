"""Nothing new is seen through the sky.

The PO, 2026-10-01, on mg_20q: «по прежнему у некоторых комнат если смотреть на них снаружи отсутствуют стенки» and «у
тебя в них как будто небо вместо стенок/потолка снаружи лежит»; and «делать нужно всё что позволяет редактирование карты,
но чтобы карта не выглядела как области с порталом» (ledger rows 350-351). q2dm1's solid mass is mostly the void outside
its hull, and over a courtyard that void begins at the sky. A room dug past the sky plane has no outer faces - they face
the void and the compiler drops them - and the renderer draws the sky without hiding what lies behind it, so from the
courtyard the room's far inner walls show where the sky should be: a portal into the void.

    python tools/check_mapgen_sky_portal.py MAP.bsp --digs DIGS.json [--donor q2dm1.bsp]

DIGS.json: {"MAP.bsp": [{"box": [...]}, ...]} - the accepted digs, as the delivery gates write it. VIEWERS are the
points of the map's air under a sky face, one per 32-unit column within REACH of the digs in plan, at the
highest a player's eye can be there - EYE over the floor, or just under the sky if that is lower - and in the
donor's air (a dig's own sealed spaces are no place to look from). TARGETS are
the points of NEW space - solid in the donor, air in the map, a roof and not the sky straight over them - inside the
digs' boxes, on a 32-unit lattice. A target
is SEEN THROUGH THE SKY when the target's cluster is in the viewer's potentially visible set - what the renderer itself
draws from there - and the straight line from the viewer to it passes a sky brush and meets no DRAWN FACE on the way:
refused. The renderer draws the sky behind everything, so a sky brush hides nothing; a face is drawn where the line
goes from air into a solid that is not sky, and such a face hides the target. Solid to solid - the void into a wall
whose outer side faces it - is no face: that is how a dig with no outer faces shows its inner walls (row 353).
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_mapgen_static import Bsp  # noqa: E402

DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
SURF_SKY = 0x4
CONTENTS_SOLID = 1
REACH = 2048.0
LATTICE = 32.0
MARCH = 8.0
EYE = 96.0


class SkyBsp(Bsp):
    """A BSP that can also say whether a solid point is inside a sky brush."""

    def __init__(self, path: Path):
        super().__init__(path)
        self.leafbrushes = [x[0] for x in self._arr(10, "<H", 2)]
        self.brushes = self._arr(14, "<iii", 12)
        self.brushsides = self._arr(15, "<Hh", 4)
        self.pvs_rows: dict = {}
        o, n = self.lumps[3]
        self.numclusters = struct.unpack_from("<i", self.d, o)[0] if n >= 4 else 0
        self.sky_brush = []
        for first, num, _contents in self.brushes:
            self.sky_brush.append(any(
                0 <= self.brushsides[s][1] < len(self.texinfo) and self.texinfo[self.brushsides[s][1]][0] & SURF_SKY
                for s in range(first, first + num)))

    def leaf(self, p) -> int:
        node = self.models[0][9]
        while node >= 0:
            n = self.nodes[node]
            pl = self.planes[n[0]]
            node = n[1] if (p[0] * pl[0] + p[1] * pl[1] + p[2] * pl[2] - pl[3]) >= 0 else n[2]
        return -(node + 1)

    def cluster(self, p) -> int:
        return self.leafs[self.leaf(p)][1]

    def sees(self, c1: int, c2: int) -> bool:
        """Is cluster c2 in cluster c1's potentially visible set? Without visibility data every cluster is."""
        if c1 < 0 or c2 < 0 or not self.numclusters:
            return True
        row = self.pvs_rows.get(c1)
        if row is None:
            o, _ = self.lumps[3]
            ofs = struct.unpack_from("<i", self.d, o + 4 + 8 * c1)[0]
            row, i, k = bytearray((self.numclusters + 7) // 8), o + ofs, 0
            while k < len(row):
                b = self.d[i]
                if b:
                    row[k] = b
                    k += 1
                    i += 1
                else:
                    k += self.d[i + 1]
                    i += 2
            self.pvs_rows[c1] = row
        return bool(row[c2 >> 3] & (1 << (c2 & 7)))

    def leaves_along(self, p0, p1) -> list:
        """The leaves the segment p0-p1 passes through, in order, each with its stretch (t0, t1) - exact, by the
        tree's own planes, so a corner of a wall four units thick is not stepped over (row 353)."""
        out = []

        def walk(node, a, b, ta, tb):
            while node >= 0:
                n = self.nodes[node]
                pl = self.planes[n[0]]
                da = a[0] * pl[0] + a[1] * pl[1] + a[2] * pl[2] - pl[3]
                db = b[0] * pl[0] + b[1] * pl[1] + b[2] * pl[2] - pl[3]
                if da >= 0 and db >= 0:
                    node = n[1]
                elif da < 0 and db < 0:
                    node = n[2]
                else:
                    f = da / (da - db)
                    mid = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
                    tm = ta + (tb - ta) * f
                    first, second = (n[1], n[2]) if da >= 0 else (n[2], n[1])
                    walk(first, a, mid, ta, tm)
                    walk(second, mid, b, tm, tb)
                    return
            out.append((ta, tb, -(node + 1)))

        walk(self.models[0][9], p0, p1, 0.0, 1.0)
        return out

    def _inside(self, bi: int, p) -> bool:
        f, n, _ = self.brushes[bi]
        for s in range(f, f + n):
            pl = self.planes[self.brushsides[s][0]]
            if p[0] * pl[0] + p[1] * pl[1] + p[2] * pl[2] - pl[3] > 0.01:
                return False
        return True

    def in_sky(self, p) -> bool:
        """Is this point inside a sky brush and inside no other solid brush? Where a sky brush overlaps a wall the
        wall's face is what is drawn (row 354: the skin's enclosure inside an old wall read as sky)."""
        lf = self.leafs[self.leaf(p)]
        first, num = lf[11], lf[12]
        sky = False
        for k in range(first, first + num):
            bi = self.leafbrushes[k]
            if not (self.brushes[bi][2] & CONTENTS_SOLID) or not self._inside(bi, p):
                continue
            if not self.sky_brush[bi]:
                return False
            sky = True
        return sky


def viewers(m: SkyBsp, digs: list, d: Bsp | None = None) -> list:
    """One point per 32-unit column within REACH of the digs in plan: the highest air right under a sky face."""
    if not digs:
        return []
    boxes = [[float(v) for v in d["box"]] for d in digs]
    lo = [min(b[i] for b in boxes) - REACH for i in range(2)]
    hi = [max(b[3 + i] for b in boxes) + REACH for i in range(2)]
    ztop = max(b[5] for b in boxes) + 1024.0
    zbot = min(b[2] for b in boxes) - 1024.0
    out = []
    x = lo[0] + LATTICE / 2 + 7.0
    while x < hi[0]:
        y = lo[1] + LATTICE / 2 + 11.0
        while y < hi[1]:
            near = any(b[0] - REACH <= x <= b[3] + REACH and b[1] - REACH <= y <= b[4] + REACH for b in boxes)
            if near:
                z = ztop
                while z > zbot and m.solid((x, y, z)):
                    z -= 16.0
                if z > zbot:
                    # up from this air to the first solid, and is it the sky
                    while z < ztop + 1024.0 and not m.solid((x, y, z + 4.0)):
                        z += 4.0
                    if m.in_sky((x, y, z + 6.0)):
                        # row 353: where a player's eye can be - EYE over the floor at most, standing or jumping -
                        # not the top of the air: a line from right under the sky grazes it, and no player is there
                        f = z
                        while f > zbot and not m.solid((x, y, f - 4.0)):
                            f -= 4.0
                        v = (x, y, min(z - 4.0, f + EYE))
                        # row 354: in the OLD map's air - a sky skin's sealed gap is under the sky too, and nobody
                        # stands there
                        if d is None or not d.solid(v):
                            out.append(v)
            y += LATTICE
        x += LATTICE
    return out


def under_roof(m: SkyBsp, p, reach: float = 4096.0) -> bool:
    """Row 353: is the first solid straight over this point a roof - not the sky? The air of a sky lift round a dig is
    new space under the sky, and what the courtyard sees through the sky there is the dig's outside, drawn."""
    z = p[2] + 8.0
    while z < p[2] + reach:
        if m.solid((p[0], p[1], z)):
            return not m.in_sky((p[0], p[1], z))
        z += 8.0
    return False


def targets(m: SkyBsp, d: Bsp, digs: list) -> list:
    """New space inside the digs' boxes under a roof: solid in the donor, air in the map, a roof over it."""
    out, seen = [], set()
    for dig in digs:
        b = [float(v) for v in dig["box"]]
        # off the 32-unit grid the map is built on, so no line runs exactly along a wall's edge (row 353: the
        # first face-aware pass counted lines through the corner of a shell as seeing past it)
        x = b[0] + LATTICE / 2 + 5.0
        while x < b[3]:
            y = b[1] + LATTICE / 2 + 3.0
            while y < b[4]:
                z = b[2] + LATTICE / 2 + 1.0
                while z < b[5]:
                    key = (round(x), round(y), round(z))
                    if key not in seen and not m.solid((x, y, z)) and d.solid((x, y, z))                             and under_roof(m, (x, y, z)):
                        seen.add(key)
                        out.append((x, y, z))
                    z += LATTICE
                y += LATTICE
            x += LATTICE
    return out


def through_sky(m: SkyBsp, c, a) -> bool:
    """From the viewer c to the target a: does the line pass a sky brush and meet no drawn face?"""
    in_air, sky = True, False
    for t0, t1, leaf in m.leaves_along(c, a):
        if t1 - t0 <= 1e-6:
            continue
        if m.leafs[leaf][0] & CONTENTS_SOLID:
            # just inside where the line enters: that is the face it meets
            length = math.dist(c, a)
            tm = min(t0 + 0.5 / length, 0.5 * (t0 + t1)) if length > 0 else t0
            p = tuple(c[i] + (a[i] - c[i]) * tm for i in range(3))
            if m.in_sky(p):
                sky = True
            elif in_air:
                return False          # air into a wall: a drawn face hides it
            in_air = False
        else:
            in_air = True
    return sky


def seen_through_sky(bsp: Path, digs: list, donor: Path = DONOR, limit: int = 0) -> tuple[list, int, int]:
    """(target, viewer) pairs where new space is seen through the sky; and the viewer and target counts."""
    m, d = SkyBsp(bsp), Bsp(donor)
    vs, ts = viewers(m, digs, d), targets(m, d, digs)
    found = []
    vcl = [m.cluster(c) for c in vs]
    for a in ts:
        acl = m.cluster(a)
        for c, cl in zip(vs, vcl):
            if math.hypot(a[0] - c[0], a[1] - c[1]) > REACH or c[2] >= a[2] or not m.sees(cl, acl):
                continue
            if through_sky(m, c, a):
                found.append((a, c))
                break
        if limit and len(found) >= limit:
            break
    return found, len(vs), len(ts)


def said(found: list) -> str:
    return "; ".join(f"new {' '.join(f'{v:.0f}' for v in a)} seen through the sky from {' '.join(f'{v:.0f}' for v in c)}"
                     for a, c in found[:4])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("--digs", type=Path, required=True)
    ap.add_argument("--donor", type=Path, default=DONOR)
    a = ap.parse_args()
    digs = json.loads(a.digs.read_text(encoding="utf-8")).get(a.map.name, [])
    found, nv, nt = seen_through_sky(a.map, digs, a.donor)
    ok = not found
    print(f"  {'PASS' if ok else 'FAIL'}  {a.map.name}: nothing new is seen through the sky  -- {len(digs)} digs,"
          f" {nv} viewers under the sky, {nt} points of new space, {len(found)} seen through it"
          + (f": {said(found)}" if found else ""))
    print(f"SUMMARY 1 cases asserted, {int(not ok)} failures")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
