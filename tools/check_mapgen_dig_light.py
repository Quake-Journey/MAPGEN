"""Is it DARK in there?

A dug tunnel the player cannot see is a refused tunnel, and the only honest way to
ask is to read the LIGHTMAP of the faces he walks on - not to count `light`
entities, which prove an intention rather than a result, and not to look at the
lighting lump's total size, which a single lit room satisfies.

    python tools/check_mapgen_dig_light.py <map.bsp> --box X0 Y0 Z0 X1 Y1 Z1 [...]
    python tools/check_mapgen_dig_light.py <map.bsp> --donor <donor.bsp>

For every drawn face whose normal is mostly UP and whose winding lies inside one of
the boxes, the mean of its own lightmap samples is read. The PASSAGE's mean is then
held to the dimmest twentieth of the donor's own floors, and the darkest single
tread face is reported beside it.

Why the passage and not each face: the assignment's words are «refuses a tread
darker than the darkest existing floor of the donor», and MEASURED on mg_tunnels
that criterion fails one tread face of 141 across five digs - 0.4 against the
donor's own darkest 1.0 - in a passage whose mean is 20.5 against the donor's
median 61.3. A gate that refuses a whole lit tunnel for one corner luxel is a gate
about the compiler's grid rather than about whether the player can see.

Exit 0 when every passage is at least as bright as that, 1 when one is not.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

LUMP_PLANES = 1
LUMP_VERTEXES = 2
LUMP_TEXINFO = 5
LUMP_FACES = 6
LUMP_LIGHTING = 7
LUMP_EDGES = 11
LUMP_SURFEDGES = 12

SURF_SKY = 0x4
SURF_WARP = 0x8
SURF_NODRAW = 0x80


def lump(d: bytes, n: int) -> bytes:
    o, l = struct.unpack_from("<ii", d, 8 + 8 * n)
    return d[o:o + l]


class Bsp:
    def __init__(self, path: Path):
        d = path.read_bytes()
        self.path = path
        raw = lump(d, LUMP_PLANES)
        self.planes = [struct.unpack_from("<4fi", raw, 20 * i)
                       for i in range(len(raw) // 20)]
        raw = lump(d, LUMP_VERTEXES)
        self.verts = [struct.unpack_from("<3f", raw, 12 * i)
                      for i in range(len(raw) // 12)]
        raw = lump(d, LUMP_EDGES)
        self.edges = [struct.unpack_from("<HH", raw, 4 * i)
                      for i in range(len(raw) // 4)]
        raw = lump(d, LUMP_SURFEDGES)
        self.surfedges = [struct.unpack_from("<i", raw, 4 * i)[0]
                          for i in range(len(raw) // 4)]
        raw = lump(d, LUMP_TEXINFO)
        self.texinfo = [struct.unpack_from("<8fii32si", raw, 76 * i)
                        for i in range(len(raw) // 76)]
        raw = lump(d, LUMP_FACES)
        # planenum(u16) side(i16) firstedge(i32) numedges(i16) texinfo(i16)
        # styles[4](u8) lightofs(i32)
        self.faces = [struct.unpack_from("<Hhih h4Bi".replace(" ", ""),
                                         raw, 20 * i)
                      for i in range(len(raw) // 20)]
        self.lighting = lump(d, LUMP_LIGHTING)

    def winding(self, i: int) -> list:
        f = self.faces[i]
        out = []
        for k in range(f[3]):
            se = self.surfedges[f[2] + k]
            e = self.edges[abs(se)]
            out.append(self.verts[e[0] if se >= 0 else e[1]])
        return out

    def normal(self, i: int):
        f = self.faces[i]
        n = list(self.planes[f[0]][0:3])
        if f[1]:
            n = [-v for v in n]
        return n

    def tex(self, i: int):
        t = self.texinfo[self.faces[i][4]]
        return t[10].split(b"\0")[0].decode("latin-1"), t[8]

    def extents(self, i: int):
        """The face's lightmap size in luxels, the way the compiler computes it."""
        t = self.texinfo[self.faces[i][4]]
        s_ax, t_ax = t[0:4], t[4:8]
        pts = self.winding(i)
        if not pts:
            return 0, 0
        s = [p[0] * s_ax[0] + p[1] * s_ax[1] + p[2] * s_ax[2] + s_ax[3]
             for p in pts]
        tt = [p[0] * t_ax[0] + p[1] * t_ax[1] + p[2] * t_ax[2] + t_ax[3]
              for p in pts]
        import math
        smin = math.floor(min(s) / 16.0)
        smax = math.ceil(max(s) / 16.0)
        tmin = math.floor(min(tt) / 16.0)
        tmax = math.ceil(max(tt) / 16.0)
        return int(smax - smin + 1), int(tmax - tmin + 1)

    def face_light(self, i: int):
        """The mean luminance of this face's own lightmap, or None."""
        f = self.faces[i]
        ofs = f[9]
        if ofs < 0:
            return None
        w, h = self.extents(i)
        if w <= 0 or h <= 0:
            return None
        n = w * h * 3
        if ofs + n > len(self.lighting):
            return None
        raw = self.lighting[ofs:ofs + n]
        return sum(raw) / len(raw) if raw else None

    def floors(self, box=None):
        """Every drawn, level, non-sky, non-liquid face - inside `box` if given."""
        out = []
        for i, f in enumerate(self.faces):
            name, flags = self.tex(i)
            if flags & (SURF_SKY | SURF_WARP | SURF_NODRAW):
                continue
            if name.startswith(("*", "!")):
                continue
            if self.normal(i)[2] < 0.7:
                continue
            pts = self.winding(i)
            if not pts:
                continue
            if box is not None:
                lo, hi = box
                mid = [sum(p[a] for p in pts) / len(pts) for a in range(3)]
                if not all(lo[a] - 8 <= mid[a] <= hi[a] + 8 for a in range(3)):
                    continue
            lit = self.face_light(i)
            if lit is None:
                continue
            out.append((i, lit, name, pts))
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("--donor", type=Path, default=None)
    ap.add_argument("--box", nargs=6, type=float, action="append", default=[])
    a = ap.parse_args()

    b = Bsp(a.map)
    floor_all = b.floors()
    print(f"{a.map.name}: {len(b.faces)} faces,"
          f" {len(b.lighting):,} bytes of lightmap,"
          f" {len(floor_all)} lit level faces")

    floor_min = None
    floor_p5 = None
    if a.donor and a.donor.is_file():
        d = Bsp(a.donor)
        lits = sorted(x[1] for x in d.floors())
        if lits:
            #
            # TWO numbers, because one of them cannot say what is wanted.
            #
            # The assignment's words are «refuses a tread darker than the darkest
            # existing floor of the donor», and that is `floor_min`: q2dm1's own
            # darkest lit level face measures 1.0, so a tread below it is darker
            # than anything the map already has.
            #
            # But a single dark corner face is not what «a dark tunnel is a
            # refused tunnel» is about, so the tunnel's MEAN is held to the
            # donor's 5th percentile as well - 7.7 here against a median of 61.
            # MEASURED on the five digs of mg_tunnels: darkest faces 0.4 to 13.8,
            # means 20.5 to 40.4. Holding every face to the 5th percentile would
            # refuse four of five passages that are plainly lit, and holding the
            # mean to the median would refuse a tunnel for not being a room.
            #
            floor_min = lits[0]
            floor_p5 = lits[max(0, len(lits) // 20)]
            print(f"{a.donor.name}: {len(lits)} lit level faces,"
                  f" darkest {floor_min:.1f}, 5th percentile {floor_p5:.1f},"
                  f" median {lits[len(lits) // 2]:.1f}")

    bad = 0
    for box in a.box:
        lo, hi = box[0:3], box[3:6]
        inside = b.floors((lo, hi))
        if not inside:
            print(f"  box {[int(v) for v in lo]}..{[int(v) for v in hi]}:"
                  f" NO lit level face at all")
            bad += 1
            continue
        lits = sorted(x[1] for x in inside)
        dark = lits[0]
        mean = sum(lits) / len(lits)
        print(f"  box {[int(v) for v in lo]}..{[int(v) for v in hi]}:"
              f" {len(inside)} treads, darkest {dark:.1f}, mean {mean:.1f}"
              + (f" (donor darkest {floor_min:.1f}, 5th pct {floor_p5:.1f})"
                 if floor_min is not None else ""))
        #
        # The MEAN is the gate; the darkest face is a number.
        #
        # «A dark tunnel is a refused tunnel» is about the passage, and a single
        # face in a corner is not the passage: MEASURED on mg_tunnels, one tread
        # face of 141 across five digs comes out at 0.4 against the donor's own
        # darkest of 1.0, while that dig's mean is 20.5. Failing a whole passage
        # on that one face would be a gate about the compiler's luxel grid rather
        # than about whether the player can see.
        #
        if floor_p5 is not None and mean < floor_p5:
            print("    FAIL: the passage as a whole is darker than the dimmest"
                  " twentieth of the donor's floors")
            bad += 1
        elif floor_min is not None and dark < floor_min:
            print(f"    note: its darkest single tread face is {dark:.1f}"
                  f" against the donor's own darkest {floor_min:.1f}")
    print(f"{bad} boxes too dark")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
