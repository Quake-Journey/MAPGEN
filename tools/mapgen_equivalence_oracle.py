"""An independent reading of what a compiled map draws and where.

This shares no code with `src/mapgen/mapgen_equivalence.c`. It parses the BSP
lumps itself, from the published on-disk layout, and computes the same
area-weighted signatures - area, area-centroid, facing, plane offset and
texture axes, summed per material - by its own arithmetic. Two implementations
that agree on those numbers are evidence; one implementation agreeing with
itself is not.

    python tools/mapgen_equivalence_oracle.py DONOR.bsp BASELINE.bsp
        [--material NAME] [--top N]

Primary source for the layout: id Software's own qfiles.h,
https://github.com/id-Software/Quake-2/blob/master/qcommon/qfiles.h
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path

LUMP_ENTITIES, LUMP_PLANES, LUMP_VERTEXES = 0, 1, 2
LUMP_NODES, LUMP_TEXINFO, LUMP_FACES = 4, 5, 6
LUMP_LEAFS, LUMP_LEAFFACES, LUMP_LEAFBRUSHES = 8, 9, 10
LUMP_EDGES, LUMP_SURFEDGES, LUMP_MODELS = 11, 12, 13
LUMP_BRUSHES, LUMP_BRUSHSIDES = 14, 15
LUMP_AREAS, LUMP_AREAPORTALS = 17, 18

# The contents that decide how a player may move. Everything else - detail,
# translucency, the origin marker - changes how a map is BUILT and not where a
# player may go, so it is deliberately absent.
MOVEMENT_MASK = (0x00000001 | 0x00000002 | 0x00000004 | 0x00000008
                 | 0x00000010 | 0x00000020 | 0x00000040 | 0x00008000
                 | 0x00010000 | 0x00020000 | 0x00040000 | 0x00080000
                 | 0x00100000 | 0x00200000 | 0x00400000 | 0x00800000
                 | 0x20000000)
CONTENTS_AREAPORTAL = 0x00008000
CONTENTS_DETAIL = 0x08000000


def lump(raw: bytes, index: int) -> bytes:
    off, length = struct.unpack_from("<ii", raw, 8 + index * 8)
    return raw[off:off + length]


class Bsp:
    def __init__(self, path: Path):
        raw = path.read_bytes()
        ident, version = struct.unpack_from("<4si", raw, 0)
        if ident != b"IBSP" or version != 38:
            raise SystemExit(f"{path}: not IBSP 38")
        self.raw = raw
        v = lump(raw, LUMP_VERTEXES)
        self.vertexes = [struct.unpack_from("<3f", v, i * 12)
                         for i in range(len(v) // 12)]
        p = lump(raw, LUMP_PLANES)
        self.planes = [struct.unpack_from("<4f", p, i * 20)
                       for i in range(len(p) // 20)]
        e = lump(raw, LUMP_EDGES)
        self.edges = [struct.unpack_from("<2H", e, i * 4)
                      for i in range(len(e) // 4)]
        s = lump(raw, LUMP_SURFEDGES)
        self.surfedges = [struct.unpack_from("<i", s, i * 4)[0]
                          for i in range(len(s) // 4)]
        t = lump(raw, LUMP_TEXINFO)
        self.texinfo = []
        for i in range(len(t) // 76):
            axis = struct.unpack_from("<8f", t, i * 76)
            flags, value = struct.unpack_from("<ii", t, i * 76 + 32)
            name = struct.unpack_from("<32s", t, i * 76 + 40)[0]
            self.texinfo.append((axis, flags, value,
                                 name.split(b"\0")[0].decode("latin1")))
        f = lump(raw, LUMP_FACES)
        self.faces = [struct.unpack_from("<Hhihh4Bi", f, i * 20)[:5]
                      for i in range(len(f) // 20)]
        m = lump(raw, LUMP_MODELS)
        self.models = []
        for i in range(len(m) // 48):
            vals = struct.unpack_from("<9f3i", m, i * 48)
            self.models.append((vals[0:3], vals[3:6], vals[6:9], vals[9],
                                vals[10], vals[11]))

        # --- and everything the other seven axes rest on -----------------
        n = lump(raw, LUMP_NODES)
        # planenum, children[2], mins[3], maxs[3], firstface, numfaces
        self.nodes = [struct.unpack_from("<i2i6h2H", n, i * 28)
                      for i in range(len(n) // 28)]
        lf = lump(raw, LUMP_LEAFS)
        # contents, cluster, area, mins[3], maxs[3], firstleafface,
        # numleaffaces, firstleafbrush, numleafbrushes
        self.leafs = [struct.unpack_from("<i2h6h4H", lf, i * 28)
                      for i in range(len(lf) // 28)]
        lb = lump(raw, LUMP_LEAFBRUSHES)
        self.leafbrushes = [struct.unpack_from("<H", lb, i * 2)[0]
                            for i in range(len(lb) // 2)]
        br = lump(raw, LUMP_BRUSHES)
        self.brushes = [struct.unpack_from("<3i", br, i * 12)
                        for i in range(len(br) // 12)]
        bs = lump(raw, LUMP_BRUSHSIDES)
        self.brushsides = [struct.unpack_from("<Hh", bs, i * 4)
                           for i in range(len(bs) // 4)]
        ar = lump(raw, LUMP_AREAS)
        self.areas = [struct.unpack_from("<2i", ar, i * 8)
                      for i in range(len(ar) // 8)]
        ap = lump(raw, LUMP_AREAPORTALS)
        self.areaportals = [struct.unpack_from("<2i", ap, i * 8)
                            for i in range(len(ap) // 8)]
        ents = lump(raw, LUMP_ENTITIES)
        self.entity_text = ents.split(b"\0")[0].decode("latin1")

    # ---- space and architecture -----------------------------------------

    def world_bounds(self) -> tuple[list[float], list[float]]:
        """The world model's own box - model 0, which is the map."""
        mins, maxs = self.models[0][0], self.models[0][1]
        return list(mins), list(maxs)

    def leaf_at(self, point) -> int:
        """Which leaf holds this point, by descending the tree.

        The tree is the map's own answer to that question, and following it is
        the one reading that needs no geometry of this file's own.
        """
        node = 0
        while node >= 0:
            planenum, front, back = self.nodes[node][0:3]
            nx, ny, nz, dist = self.planes[planenum]
            d = point[0] * nx + point[1] * ny + point[2] * nz - dist
            node = front if d >= 0 else back
        return -1 - node

    def leaf_movement(self) -> dict[int, int]:
        """What each leaf does to a player, structural bits and detail alike.

        The tree is split on structural brushes only, so a leaf's own contents
        are exact for those and say nothing reliable about detail - clip and
        ladder are detail in Q2. So the detail bits come from the brushes the
        leaf holds, which is where the compiler actually left them.
        """
        out = {}
        for i, leaf in enumerate(self.leafs):
            bits = leaf[0] & MOVEMENT_MASK & ~CONTENTS_DETAIL
            first, num = leaf[11], leaf[12]
            for k in range(num):
                b = self.leafbrushes[first + k]
                if b < len(self.brushes):
                    bits |= self.brushes[b][2] & MOVEMENT_MASK
            out[i] = bits
        return out

    def sample_classes(self, mins, maxs, step: float) -> dict[int, int]:
        """How many lattice points of each movement class this map holds.

        A count, not a volume: multiplied by the cell size it IS a volume, but
        the comparison only ever divides one count by another, and a count is
        the thing actually measured. Both maps are sampled on the same lattice
        by the caller, so a difference in these numbers is a difference in the
        maps and not in the grids.

        Offset by half a cell so no sample lands exactly on the axial planes a
        map is mostly built from - a point ON a plane belongs to whichever side
        the descent happens to take, and that is not a fact about the map.
        """
        move = self.leaf_movement()
        out: dict[int, int] = {}
        z = mins[2] + step * 0.5
        while z < maxs[2]:
            y = mins[1] + step * 0.5
            while y < maxs[1]:
                x = mins[0] + step * 0.5
                while x < maxs[0]:
                    cls = move.get(self.leaf_at((x, y, z)), 0)
                    out[cls] = out.get(cls, 0) + 1
                    x += step
                y += step
            z += step
        return out

    # ---- ownership -------------------------------------------------------

    def model_faces(self) -> dict[int, int]:
        return {i: m[5] for i, m in enumerate(self.models)}

    def model_extent(self) -> dict[int, tuple]:
        """Each model as where it is and how big it is - six numbers.

        Size alone is not enough: a trigger volume carried across the room has
        the same size and decides something completely different about what a
        player can reach. Position is a fact about the map, and the compiler
        does not move a submodel, so it belongs here.
        """
        out = {}
        for i, m in enumerate(self.models):
            mins, maxs = m[0], m[1]
            out[i] = (tuple(round(mins[k], 3) for k in range(3))
                      + tuple(round(maxs[k] - mins[k], 3) for k in range(3)))
        return out

    # ---- entities, movers ------------------------------------------------

    def entity_blocks(self) -> list[dict]:
        """Every block as a dict of its pairs, parsed strictly enough to
        FAIL rather than guess: an unterminated block, a key without a value
        or a duplicated key raises."""
        blocks, cur, depth = [], None, 0
        i, text = 0, self.entity_text
        while i < len(text):
            c = text[i]
            if c == "{":
                if depth:
                    raise ValueError("a block inside a block")
                depth, cur = 1, {}
                i += 1
                continue
            if c == "}":
                if not depth:
                    raise ValueError("a block that never opened")
                blocks.append(cur)
                depth, cur = 0, None
                i += 1
                continue
            if c == '"':
                end = text.find('"', i + 1)
                if end < 0:
                    raise ValueError("a string that never closes")
                key = text[i + 1:end]
                i = end + 1
                while i < len(text) and text[i] in " \t\r\n":
                    i += 1
                if i >= len(text) or text[i] != '"':
                    raise ValueError(f"key {key!r} without a value")
                end = text.find('"', i + 1)
                if end < 0:
                    raise ValueError("a value that never closes")
                if cur is None:
                    raise ValueError("a pair outside any block")
                if key in cur:
                    raise ValueError(f"the key {key!r} twice in one block")
                cur[key] = text[i + 1:end]
                i = end + 1
                continue
            i += 1
        if depth:
            raise ValueError("a block that never closes")
        return blocks

    @staticmethod
    def canon(value: str) -> str:
        """A value compared as what it IS.

        `-1` and `-1.0` are the same number written twice, and a map that says
        it the second way is the same map. Anything that is not a run of
        numbers is compared as the text it is.
        """
        parts = value.split()
        if not parts:
            return value
        try:
            return " ".join(f"{float(p):.3f}" for p in parts)
        except ValueError:
            return value

    def entity_facts(self) -> dict[str, int]:
        """Every entity as its classname and where it is, counted.

        The position matters: an item left hanging over a hole and a spawn
        pushed into the floor change nothing about how many entities a map has
        and everything about whether it can be played. Rounded to the unit -
        finer than anything a compiler moves, coarser than the last bit of a
        float.
        """
        out: dict[str, int] = {}
        for b in self.entity_blocks():
            name = b.get("classname", "")
            origin = b.get("origin", "")
            where = ""
            if origin:
                try:
                    where = " ".join(f"{round(float(p)):d}"
                                     for p in origin.split())
                except ValueError:
                    where = origin
            key = f"{name}@{where}"
            out[key] = out.get(key, 0) + 1
        return out

    def classnames(self) -> dict[str, int]:
        out = {}
        for b in self.entity_blocks():
            name = b.get("classname", "")
            out[name] = out.get(name, 0) + 1
        return out

    def movers(self) -> list[str]:
        """Each mover described by what it IS and what it is bound to, never
        by its ordinal - the compiler renumbers submodels freely.

        The model it owns is named by its SIZE, for the same reason.
        """
        extent = self.model_extent()
        out = []
        for b in self.entity_blocks():
            name = b.get("classname", "")
            if not name.startswith("func_") and not name.startswith("trigger_"):
                continue
            model = b.get("model", "")
            size = ""
            if model.startswith("*"):
                try:
                    size = "x".join(str(v) for v in extent[int(model[1:])][3:])
                except (ValueError, KeyError):
                    size = "?"
            keys = ",".join(f"{k}={self.canon(v)}"
                            for k, v in sorted(b.items())
                            if k not in ("model",))
            out.append(f"{name}|{size}|{keys}")
        return sorted(out)

    # ---- traversal -------------------------------------------------------

    def areaportal_leafs(self) -> int:
        return sum(1 for lf in self.leafs if lf[0] & CONTENTS_AREAPORTAL)

    def area_leaf_counts(self) -> dict[int, int]:
        """How many leaves each area holds.

        Used only to tell two areas APART inside one map, never to compare a
        number across maps: how many leaves a space is cut into is the
        compiler's decision. What crosses is the portal graph's shape, and
        there each end is named by its degree and by this count's RANK among
        the areas of its own map - a description that survives renumbering and
        does not pretend a leaf count is a volume.
        """
        out: dict[int, int] = {}
        for leaf in self.leafs:
            out[leaf[2]] = out.get(leaf[2], 0) + 1
        return out

    def portal_graph(self) -> list[tuple]:
        """Each portal as (degree, volume) of the area it leaves and of the
        area it reaches - never as an area NUMBER, which the compiler assigns
        in whatever order its flood happened to reach them.

        Built from what the areas REFERENCE. Every donor measured carries one
        trailing AREAPORTALS record that no area points at; the engine never
        walks outside `firstareaportal .. +numareaportals`, so that record
        cannot change how a map is sealed and does not appear here.
        """
        counts = self.area_leaf_counts()
        order = {a: r for r, a in
                 enumerate(sorted(counts, key=lambda k: (counts[k], k)))}
        out = []
        for a, (num, first) in enumerate(self.areas):
            for k in range(num):
                if first + k >= len(self.areaportals):
                    continue
                _, other = self.areaportals[first + k]
                if not 0 <= other < len(self.areas):
                    continue
                out.append((num, order.get(a, -1),
                            self.areas[other][0], order.get(other, -1)))
        return sorted(out)

    def face_points(self, face) -> list[tuple[float, float, float]]:
        _, _, first, count, _ = face
        pts = []
        for k in range(count):
            se = self.surfedges[first + k]
            a, b = self.edges[abs(se)]
            pts.append(self.vertexes[a if se >= 0 else b])
        return pts

    def unseen(self, index: int) -> bool:
        """Row 412 (the C oracle's `face_unseen`): a face whose texinfo says NODRAW is drawn by nobody - q2duel1's
        compiler kept its triggers' faces, ours writes none - and belongs to no model."""
        texinfo = self.faces[index][4]
        return 0 <= texinfo < len(self.texinfo) and bool(self.texinfo[texinfo][1] & 0x80)

    def face_owner(self, other: "Bsp | None" = None) -> list[int | None]:
        owner: list[int | None] = [None] * len(self.faces)
        for index, model in enumerate(self.models):
            _, _, _, _, firstface, numfaces = model
            for k in range(numfaces):
                if owner[firstface + k] is None and not self.unseen(firstface + k):
                    owner[firstface + k] = index
        if other is not None:
            # Row 400 (the C oracle's `seal_owners`): a face whose front - one unit off its middle - lies, in the
            # OTHER map, in a solid leaf yet inside none of that map's brushes faces that compiler's sealing, not
            # the map, and is compared by neither side.
            for index, face in enumerate(self.faces):
                if owner[index] is None:
                    continue
                planenum, side, _, count, _ = face
                if count < 3:
                    continue
                area, centroid = area_and_centroid(self.face_points(face))
                if area <= 0:
                    continue
                nx, ny, nz, _ = self.planes[planenum]
                s = -1.0 if side else 1.0
                probe = (centroid[0] + nx * s, centroid[1] + ny * s, centroid[2] + nz * s)
                if other.sealed_at(probe):
                    owner[index] = None
        return owner

    def sealed_at(self, point) -> bool:
        """Solid in this compiler's tree, inside none of this map's brushes: its fill."""
        leaf = self.leafs[self.leaf_at(point)]
        if not leaf[0] & 1:
            return False
        first, num = leaf[11], leaf[12]
        for k in range(num):
            first_side, count, contents = self.brushes[self.leafbrushes[first + k]]
            if not contents & 3:
                continue
            inside = True
            for j in range(count):
                planenum = self.brushsides[first_side + j][0]
                nx, ny, nz, dist = self.planes[planenum]
                if point[0] * nx + point[1] * ny + point[2] * nz - dist > 0.03:
                    inside = False
                    break
            if inside:
                return False
        return True


def area_and_centroid(pts) -> tuple[float, tuple[float, float, float]]:
    """Triangle-fan area and the true area-centroid, which is additive: split
    the polygon and the area-weighted sum of the parts is unchanged."""
    if len(pts) < 3:
        return 0.0, (0.0, 0.0, 0.0)
    total = 0.0
    acc = [0.0, 0.0, 0.0]
    p0 = pts[0]
    for i in range(1, len(pts) - 1):
        a = [pts[i][k] - p0[k] for k in range(3)]
        b = [pts[i + 1][k] - p0[k] for k in range(3)]
        cross = (a[1] * b[2] - a[2] * b[1],
                 a[2] * b[0] - a[0] * b[2],
                 a[0] * b[1] - a[1] * b[0])
        tri = 0.5 * math.sqrt(sum(c * c for c in cross))
        for k in range(3):
            acc[k] += tri * (p0[k] + pts[i][k] + pts[i + 1][k]) / 3.0
        total += tri
    if total > 0:
        acc = [c / total for c in acc]
    return total, tuple(acc)


def signatures(bsp: Bsp, other: "Bsp | None" = None):
    """Per (texture, flags, value, model): area, area*centroid, area*normal,
    area*offset and area*texture-axis."""
    out = defaultdict(lambda: {
        "area": 0.0, "centroid": [0.0] * 3, "normal": [0.0] * 3,
        "offset": 0.0, "axis": [0.0] * 8, "faces": 0,
    })
    owner = bsp.face_owner(other)
    for index, face in enumerate(bsp.faces):
        model = owner[index]
        if model is None:
            continue
        planenum, side, _, count, texinfo = face
        if count < 3 or texinfo < 0 or texinfo >= len(bsp.texinfo):
            continue
        pts = bsp.face_points(face)
        area, centroid = area_and_centroid(pts)
        if area <= 0:
            continue
        axis, flags, value, name = bsp.texinfo[texinfo]
        plane = bsp.planes[planenum]
        sign = -1.0 if side else 1.0
        row = out[(name, flags, value, model)]
        row["area"] += area
        row["faces"] += 1
        for k in range(3):
            row["centroid"][k] += area * centroid[k]
            row["normal"][k] += area * sign * plane[k]
        row["offset"] += area * sign * plane[3]
        for k in range(8):
            row["axis"][k] += area * axis[k]
    return out


def drawn_walls(bsp: Bsp, other: "Bsp | None" = None,
                plane_epsilon: float = 0.5, normal_epsilon: float = 0.002):
    """Per (texture, flags, value, model): every wall it is drawn on, as
    [nx, ny, nz, d, area] with the plane turned the way the face looks.

    Existence, not amount: q2dm2's rebuild drew the 2048 units of
    e3u3/metal15_2 at x 832 as the metal20_2 lying on the same plane - the
    material's summed area moved by 2.76 permille, inside any area tolerance,
    and the wall was gone all the same.
    """
    out = defaultdict(list)
    owner = bsp.face_owner(other)
    for index, face in enumerate(bsp.faces):
        model = owner[index]
        if model is None:
            continue
        planenum, side, _, count, texinfo = face
        if count < 3 or texinfo < 0 or texinfo >= len(bsp.texinfo):
            continue
        area, _ = area_and_centroid(bsp.face_points(face))
        if area <= 0:
            continue
        _, flags, value, name = bsp.texinfo[texinfo]
        plane = bsp.planes[planenum]
        sign = -1.0 if side else 1.0
        wall = [sign * plane[0], sign * plane[1], sign * plane[2],
                sign * plane[3]]
        walls = out[(name, flags, value, model)]
        for w in walls:
            if abs(w[3] - wall[3]) <= plane_epsilon and all(
                    abs(w[k] - wall[k]) <= normal_epsilon for k in range(3)):
                w[4] += area
                break
        else:
            walls.append(wall + [area])
    return out


def walls_lost(wd: dict, wb: dict, sliver: float = 64.0,
               plane_epsilon: float = 0.5, normal_epsilon: float = 0.002):
    """The donor's walls of at least `sliver` units its material is no longer
    drawn on in the baseline, largest first, as (area, texture)."""
    lost = []
    for key, walls in wd.items():
        there = wb.get(key, [])
        for w in walls:
            if w[4] < sliver:
                continue
            if not any(abs(o[3] - w[3]) <= plane_epsilon and all(
                    abs(o[k] - w[k]) <= normal_epsilon for k in range(3))
                    for o in there):
                lost.append((w[4], key[0]))
    return sorted(lost, reverse=True)


AXIS_BITS = {
    "space": 1 << 0, "architecture": 1 << 1, "surface": 1 << 2,
    "mapping": 1 << 3, "ownership": 1 << 4, "entity": 1 << 5,
    "mover": 1 << 6, "traversal": 1 << 7,
}


def _permille(a: float, b: float) -> float:
    big = max(abs(a), abs(b), 1e-9)
    return 1000.0 * abs(a - b) / big


def verdicts(d: "Bsp", b: "Bsp", tolerance: float = 5.0,
             step: float = 32.0, lattice_tolerance: float = 12.0) -> dict:
    """This file's own answer for each axis: (holds, why).

    Independent of `src/mapgen/mapgen_equivalence.c` in reading, in arithmetic
    and in the questions asked. Where the product measures union coverage of a
    material's surfaces, this measures summed area; where the product probes
    every leaf with five offsets, this compares the space each movement class
    holds. Two different measurements agreeing is evidence; the same
    measurement written twice is not.
    """
    out = {}

    # space: every movement class, sampled on one lattice over both maps.
    #
    # The tolerance is the lattice's, not the map's: a boundary that falls
    # inside a cell is resolved one way in one map and possibly the other way
    # in the other, and the number of such cells grows with the surface area,
    # not with the volume. So the bar is on the SHARE of samples that changed
    # class, which is what a player would notice, rather than on each class's
    # own permille - a class holding four cells cannot be measured to five
    # parts in a thousand by a grid.
    mins_d, maxs_d = d.world_bounds()
    mins_b, maxs_b = b.world_bounds()
    mins = [min(mins_d[i], mins_b[i]) for i in range(3)]
    maxs = [max(maxs_d[i], maxs_b[i]) for i in range(3)]
    vd = d.sample_classes(mins, maxs, step)
    vb = b.sample_classes(mins, maxs, step)
    total = max(sum(vd.values()), 1)
    moved = sum(abs(vd.get(k, 0) - vb.get(k, 0))
                for k in set(vd) | set(vb)) / 2.0
    share = 1000.0 * moved / total
    # A class that is there on one side and gone on the other is a difference
    # whatever its share: "this map has water and that one does not" is not a
    # matter of degree. Eight samples, so that a class which exists only where
    # the grid happened to fall does not raise one.
    gone = sorted(k for k in set(vd) | set(vb)
                  if (vd.get(k, 0) >= 8) != (vb.get(k, 0) >= 8))
    if gone:
        out["space"] = (False, "a movement class is on one side only: "
                               + ", ".join(f"0x{k:x} ({vd.get(k, 0)} vs "
                                           f"{vb.get(k, 0)})" for k in gone[:3]))
    else:
        out["space"] = (share <= lattice_tolerance,
                        f"{moved:.0f} of {total} samples changed class, "
                        f"{share:.2f} permille, on a {step:.0f}-unit lattice")

    # architecture: how much of the map a player can be in at all.
    open_d = sum(v for k, v in vd.items() if not k & 1)
    open_b = sum(v for k, v in vb.items() if not k & 1)
    pm = _permille(open_d, open_b)
    out["architecture"] = (pm <= lattice_tolerance,
                           f"open space {open_d} vs {open_b} samples, "
                           f"{pm:.2f} permille")

    # surface and mapping: the aggregates, by summed area rather than by the
    # product's union coverage.
    sd, sb = signatures(d, b), signatures(b, d)
    only = sorted({k[0] for k in sd} ^ {k[0] for k in sb})
    if only:
        out["surface"] = (False, f"materials only on one side: {only[:3]}")
        out["mapping"] = (False, "no common material set to compare")
    else:
        worst_a, worst_m, name_a, name_m = 0.0, 0.0, "", ""
        for key in sd:
            if key not in sb:
                continue
            md, mb = mean(sd[key]), mean(sb[key])
            pm = _permille(md["area"], mb["area"])
            if pm > worst_a:
                worst_a, name_a = pm, key[0]
            # Four of the eight are DIRECTIONS and four are OFFSETS. A
            # permille against an offset that is legitimately near zero is
            # 1000 whatever the real difference is, so each is compared as
            # what it is: directions relatively, offsets in units.
            for i in range(8):
                is_offset = i in (3, 7)
                if is_offset:
                    delta = abs(md["axis"][i] - mb["axis"][i])
                    pm = delta * 1000.0 / max(abs(md["axis"][i]),
                                              abs(mb["axis"][i]), 64.0)
                else:
                    # Directions are unit-scale, and a component that is
                    # legitimately zero - a texture axis lying in a plane -
                    # would make a permille 1000 for a difference of a ten
                    # thousandth. Measured against unity, which is the scale
                    # these numbers actually live on.
                    delta = abs(md["axis"][i] - mb["axis"][i])
                    pm = delta * 1000.0 / max(abs(md["axis"][i]),
                                              abs(mb["axis"][i]), 1.0)
                if pm > worst_m:
                    worst_m, name_m = pm, key[0]
        lost = walls_lost(drawn_walls(d, b), drawn_walls(b, d))
        if lost:
            out["surface"] = (False,
                              f"{len(lost)} walls the donor draws a material "
                              f"on lost it; the largest is {lost[0][0]:.0f} "
                              f"units of {lost[0][1]}")
        else:
            out["surface"] = (worst_a <= tolerance,
                              f"worst area {worst_a:.2f} permille on {name_a}")
        out["mapping"] = (worst_m <= tolerance,
                          f"worst texture axis {worst_m:.2f} permille "
                          f"on {name_m}")

    # ownership: how many models, and what size each one is.
    ed, eb = d.model_extent(), b.model_extent()
    sd2, sb2 = sorted(ed.values()), sorted(eb.values())
    same = len(sd2) == len(sb2) and all(
        all(abs(x[k] - y[k]) <= 1.0 for k in range(6))
        for x, y in zip(sd2, sb2))
    worst = 0.0
    for x, y in zip(sd2, sb2):
        for k in range(6):
            worst = max(worst, abs(x[k] - y[k]))
    out["ownership"] = (same, f"{len(ed)} models vs {len(eb)}, "
                              f"worst corner differs by {worst:.3f} units")

    # entity: every classname counted, from a parse that fails rather than
    # guesses.
    try:
        cd, cb = d.entity_facts(), b.entity_facts()
        only = sorted(set(cd) ^ set(cb))
        out["entity"] = (cd == cb,
                         f"{sum(cd.values())} entities vs {sum(cb.values())}"
                         + (f"; first difference {only[0]}" if only else ""))
    except ValueError as exc:
        out["entity"] = (False, f"the entity string does not parse: {exc}")

    # mover: each machine by its binding, never by its ordinal.
    try:
        md2, mb2 = d.movers(), b.movers()
        out["mover"] = (md2 == mb2, f"{len(md2)} movers vs {len(mb2)}")
    except ValueError as exc:
        out["mover"] = (False, f"the entity string does not parse: {exc}")

    # traversal: the areas, the areaportal leaves, and which areas each portal
    # joins.
    same_graph = d.portal_graph() == b.portal_graph()
    out["traversal"] = (
        len(d.areas) == len(b.areas)
        and d.areaportal_leafs() == b.areaportal_leafs()
        and same_graph,
        f"{len(d.areas)} areas / {d.areaportal_leafs()} portal leaves / "
        f"{len(d.portal_graph())} portal ends"
        + ("" if same_graph else "; the graphs differ"))
    return out


def mean(row):
    a = row["area"] or 1.0
    return {
        "area": row["area"],
        "faces": row["faces"],
        "centroid": [c / a for c in row["centroid"]],
        "normal": [n / a for n in row["normal"]],
        "offset": row["offset"] / a,
        "axis": [x / a for x in row["axis"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("donor", type=Path)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("--material", default=None)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    bd, bb = Bsp(args.donor), Bsp(args.baseline)
    d, b = signatures(bd, bb), signatures(bb, bd)
    keys = sorted(set(d) | set(b))

    total_d = sum(r["area"] for r in d.values())
    total_b = sum(r["area"] for r in b.values())
    print(f"materials {len(d)} {len(b)}  area {total_d:.1f} {total_b:.1f}")

    rows = []
    for key in keys:
        if args.material and key[0] != args.material:
            continue
        md = mean(d[key]) if key in d else None
        mb = mean(b[key]) if key in b else None
        if md is None or mb is None:
            rows.append((abs((md or mb)["area"]), key, md, mb))
            continue
        delta = abs(md["area"] - mb["area"])
        rows.append((delta, key, md, mb))
    rows.sort(key=lambda r: -r[0])

    for delta, key, md, mb in rows[:args.top]:
        name, flags, value, model = key
        if md is None or mb is None:
            side = "baseline-only" if md is None else "donor-only"
            print(f"  {side} {name} flags {flags} value {value} model {model}")
            continue
        shift = math.dist(md["centroid"], mb["centroid"])
        turn = math.dist(md["normal"], mb["normal"])
        axis = max(abs(x - y) for x, y in zip(md["axis"], mb["axis"]))
        pm = 1000.0 * delta / max(md["area"], mb["area"], 1e-9)
        print(f"  {name:24s} model {model} faces {md['faces']}/{mb['faces']} "
              f"area {md['area']:.1f}/{mb['area']:.1f} ({pm:.2f} permille) "
              f"centroid {shift:.3f} facing {turn:.4f} "
              f"offset {abs(md['offset'] - mb['offset']):.3f} axis {axis:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
