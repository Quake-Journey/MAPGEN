#!/usr/bin/env python3
"""Synthesize a minimal structurally valid Quake II BSP (IBSP/QBSP v38).

Why this exists: the M0 qualification harness has to be exercised against
process and protocol failure modes - zero exit with no output, zero exit with a
leak, damaged output, stale output, timeout, crash, log flood - BEFORE any real
compiler is qualified. Doing that needs a "compiled" artifact that the oracle
will genuinely parse, and it must not be a copied retail map: contract section
15 forbids copying game content into fixtures, and a retail map would also make
the fake's success case depend on the PO's installed data.

Trust chain, stated plainly so it is not mistaken for something stronger:

  * tools/mapgen_bsp_oracle.py is validated against 132 REAL Quake II BSPs
    shipped in the Release tree - external ground truth this repository did not
    write;
  * this synthesizer is then validated by that oracle.

So the synthesizer is NOT independent evidence about the BSP format. It is a
controlled input for testing the harness. Real format truth arrives at M0Q from
the qualified compiler, checked by the oracle.

Shape: one solid axis-aligned cube in otherwise empty space. Points inside the
cube are CONTENTS_SOLID, points outside are empty. That is the smallest tree
whose correctness can be reasoned about by hand.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

HEADER_LUMPS = 19
IDBSPHEADER = 0x50534249
QBSPHEADER = 0x50534251
BSPVERSION = 38

LUMP_ENTITIES = 0
LUMP_PLANES = 1
LUMP_VERTEXES = 2
LUMP_VISIBILITY = 3
LUMP_NODES = 4
LUMP_TEXINFO = 5
LUMP_FACES = 6
LUMP_LIGHTING = 7
LUMP_LEAFS = 8
LUMP_LEAFFACES = 9
LUMP_LEAFBRUSHES = 10
LUMP_EDGES = 11
LUMP_SURFEDGES = 12
LUMP_MODELS = 13
LUMP_BRUSHES = 14
LUMP_BRUSHSIDES = 15
LUMP_POP = 16
LUMP_AREAS = 17
LUMP_AREAPORTALS = 18

CONTENTS_SOLID = 1

# Outward plane definitions of an axis-aligned box, in a fixed order.
_AXES = (
    ((1.0, 0.0, 0.0), 0, +1, 0),
    ((-1.0, 0.0, 0.0), 0, -1, 0),
    ((0.0, 1.0, 0.0), 1, +1, 1),
    ((0.0, -1.0, 0.0), 1, -1, 1),
    ((0.0, 0.0, 1.0), 2, +1, 2),
    ((0.0, 0.0, -1.0), 2, -1, 2),
)


def _entity_string(entities: list[dict[str, str]]) -> bytes:
    out = []
    for ent in entities:
        out.append("{\n")
        for key, value in ent.items():
            out.append(f'"{key}" "{value}"\n')
        out.append("}\n")
    return ("".join(out)).encode("ascii") + b"\0"


def synth_solid_cube(
    mins=(-64.0, -64.0, -64.0),
    maxs=(64.0, 64.0, 64.0),
    texture="q2mgfx/wall",
    entities: list[dict[str, str]] | None = None,
    extended: bool = False,
    surface_flags: int = 0,
    brush_contents: int = CONTENTS_SOLID,
    with_visibility: bool = True,
    with_lighting: bool = True,
) -> bytes:
    if entities is None:
        entities = [
            {"classname": "worldspawn", "message": "mapgen synthetic fixture"},
            {"classname": "info_player_start", "origin": "0 0 128", "angle": "0"},
        ]

    planes: list[tuple[tuple[float, float, float], float, int]] = []
    for normal, axis, sign, ptype in _AXES:
        dist = maxs[axis] if sign > 0 else -mins[axis]
        planes.append((normal, float(dist), ptype))

    # Node chain: front of any box plane leaves the cube (empty leaf 1); behind
    # all six is inside the cube (solid leaf 0).
    # Leaf 0 is solid by engine convention.
    nodes = []
    for i in range(6):
        back = -(0 + 1) if i == 5 else (i + 1)  # last node's back child is leaf 0 (solid)
        front = -(1 + 1)  # leaf 1 (empty)
        nodes.append((i, front, back))

    # Face geometry. A BSP with zero faces is not a map - the qualification
    # runner rejects one unconditionally - so the synthesizer emits the cube's
    # six quads with their vertices, edges and surfedges rather than leaving
    # the render lumps empty.
    x0, y0, z0 = mins
    x1, y1, z1 = maxs
    corners = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    # One quad per plane, in the same order as _AXES.
    quads = [
        (1, 2, 6, 5),   # +X
        (3, 0, 4, 7),   # -X
        (2, 3, 7, 6),   # +Y
        (0, 1, 5, 4),   # -Y
        (4, 5, 6, 7),   # +Z
        (3, 2, 1, 0),   # -Z
    ]
    edges: list[tuple[int, int]] = [(0, 0)]      # edge 0 is reserved by convention
    surfedges: list[int] = []
    faces: list[tuple[int, int, int, int, int]] = []
    for plane_index, quad in enumerate(quads):
        first_edge = len(surfedges)
        for i in range(4):
            a = quad[i]
            b = quad[(i + 1) % 4]
            surfedges.append(len(edges))
            edges.append((a, b))
        faces.append((plane_index, 0, first_edge, 4, 0))

    leafs = [
        # (contents, cluster, area, firstleafface, numleaffaces,
        #  firstleafbrush, numleafbrushes)
        (brush_contents, -1, 0, 0, 0, 0, 1),
        (0, 0, 1, 0, len(faces), 0, 0),
    ]
    leaffaces = list(range(len(faces)))
    leafbrushes = [0]
    brushes = [(0, 6, brush_contents)]
    brushsides = [(i, 0) for i in range(6)]

    world_mins = tuple(v - 16.0 for v in mins)
    world_maxs = tuple(v + 16.0 for v in maxs)

    lumps: dict[int, bytes] = {}

    lumps[LUMP_ENTITIES] = _entity_string(entities)

    blob = bytearray()
    for normal, dist, ptype in planes:
        blob += struct.pack("<ffffi", normal[0], normal[1], normal[2], dist, ptype)
    lumps[LUMP_PLANES] = bytes(blob)

    blob = bytearray()
    for pn, front, back in nodes:
        if extended:
            blob += struct.pack(
                "<Iii6iII", pn, front, back,
                int(world_mins[0]), int(world_mins[1]), int(world_mins[2]),
                int(world_maxs[0]), int(world_maxs[1]), int(world_maxs[2]),
                0, 0,
            )
        else:
            blob += struct.pack(
                "<Iii6hHH", pn, front, back,
                int(world_mins[0]), int(world_mins[1]), int(world_mins[2]),
                int(world_maxs[0]), int(world_maxs[1]), int(world_maxs[2]),
                0, 0,
            )
    lumps[LUMP_NODES] = bytes(blob)

    blob = bytearray()
    for contents, cluster, area, flf, nlf, flb, nlb in leafs:
        if extended:
            blob += struct.pack(
                "<Iii6iIIII", contents, cluster, area,
                int(world_mins[0]), int(world_mins[1]), int(world_mins[2]),
                int(world_maxs[0]), int(world_maxs[1]), int(world_maxs[2]),
                flf, nlf, flb, nlb,
            )
        else:
            blob += struct.pack(
                "<Ihh6hHHHH", contents, cluster, area,
                int(world_mins[0]), int(world_mins[1]), int(world_mins[2]),
                int(world_maxs[0]), int(world_maxs[1]), int(world_maxs[2]),
                flf, nlf, flb, nlb,
            )
    lumps[LUMP_LEAFS] = bytes(blob)

    lumps[LUMP_VERTEXES] = b"".join(struct.pack("<3f", *c) for c in corners)
    lumps[LUMP_SURFEDGES] = b"".join(struct.pack("<i", e) for e in surfedges)
    if extended:
        lumps[LUMP_EDGES] = b"".join(struct.pack("<II", a, b) for a, b in edges)
        lumps[LUMP_LEAFFACES] = b"".join(struct.pack("<I", f) for f in leaffaces)
        lumps[LUMP_FACES] = b"".join(
            struct.pack("<IiiiiBBBBi", pn, side, fe, ne, ti, 0, 255, 255, 255, 0)
            for pn, side, fe, ne, ti in faces
        )
    else:
        lumps[LUMP_EDGES] = b"".join(struct.pack("<HH", a, b) for a, b in edges)
        lumps[LUMP_LEAFFACES] = b"".join(struct.pack("<H", f) for f in leaffaces)
        lumps[LUMP_FACES] = b"".join(
            struct.pack("<HhihhBBBBi", pn, side, fe, ne, ti, 0, 255, 255, 255, 0)
            for pn, side, fe, ne, ti in faces
        )

    if extended:
        lumps[LUMP_LEAFBRUSHES] = b"".join(struct.pack("<I", x) for x in leafbrushes)
        lumps[LUMP_BRUSHSIDES] = b"".join(struct.pack("<Ii", pn, ti) for pn, ti in brushsides)
    else:
        lumps[LUMP_LEAFBRUSHES] = b"".join(struct.pack("<H", x) for x in leafbrushes)
        lumps[LUMP_BRUSHSIDES] = b"".join(struct.pack("<Hh", pn, ti) for pn, ti in brushsides)

    lumps[LUMP_BRUSHES] = b"".join(struct.pack("<iii", fs, ns, c) for fs, ns, c in brushes)

    ti = bytearray()
    ti += struct.pack("<8f", 1, 0, 0, 0, 0, 0, -1, 0)   # u/v vectors
    ti += struct.pack("<ii", surface_flags, 0)          # flags, value
    ti += texture.encode("ascii").ljust(32, b"\0")[:32]  # texture name
    ti += struct.pack("<i", -1)                          # nexttexinfo
    assert len(ti) == 76, len(ti)
    lumps[LUMP_TEXINFO] = bytes(ti)

    lumps[LUMP_MODELS] = struct.pack(
        "<9fiii",
        world_mins[0], world_mins[1], world_mins[2],
        world_maxs[0], world_maxs[1], world_maxs[2],
        0.0, 0.0, 0.0,
        0,             # headnode
        0,             # firstface
        len(faces),    # numfaces
    )

    # A single cluster with a trivial "everything visible" PVS row, so the file
    # carries real visibility data rather than an empty lump.
    if with_visibility:
        numclusters = 1
        vis = bytearray(struct.pack("<i", numclusters))
        vis += struct.pack("<ii", 4 + 8 * numclusters, 4 + 8 * numclusters)
        vis += b"\xff"
        lumps[LUMP_VISIBILITY] = bytes(vis)
    else:
        lumps[LUMP_VISIBILITY] = b""

    lumps[LUMP_LIGHTING] = (b"\x40" * 3072) if with_lighting else b""

    lumps[LUMP_AREAS] = struct.pack("<ii", 0, 0) * 2
    lumps[LUMP_AREAPORTALS] = b""
    lumps[LUMP_POP] = b""

    header_size = 8 + HEADER_LUMPS * 8
    body = bytearray()
    directory: list[tuple[int, int]] = []
    for i in range(HEADER_LUMPS):
        data = lumps.get(i, b"")
        while len(body) % 4:
            body += b"\0"
        directory.append((header_size + len(body), len(data)))
        body += data

    out = bytearray()
    out += struct.pack("<II", QBSPHEADER if extended else IDBSPHEADER, BSPVERSION)
    for ofs, length in directory:
        out += struct.pack("<II", ofs, length)
    assert len(out) == header_size
    out += body
    return bytes(out)


def synth_empty_world(extended: bool = False, entities: list[dict[str, str]] | None = None) -> bytes:
    """A readable BSP with no world in it.

    MEASURED on q2tools-220 07d8d893: a worldspawn with zero brushes compiles
    with exit code ZERO into exactly this shape - one leaf, no nodes, no faces,
    no brushes - and only the VIS pass refuses it afterwards. The qualification
    runner therefore carries an unconditional floor, and this is the input that
    proves the floor fires.
    """
    blob = bytearray(synth_solid_cube(extended=extended, entities=entities))
    header_size = 8 + HEADER_LUMPS * 8
    for lump in (LUMP_NODES, LUMP_FACES, LUMP_BRUSHES, LUMP_BRUSHSIDES,
                 LUMP_LEAFFACES, LUMP_LEAFBRUSHES, LUMP_EDGES, LUMP_SURFEDGES,
                 LUMP_VERTEXES):
        off = 8 + lump * 8
        blob[off + 4 : off + 8] = (0).to_bytes(4, "little")
    # Exactly one leaf, and it references nothing at all.
    off = 8 + LUMP_LEAFS * 8
    leaf_ofs = int.from_bytes(blob[off : off + 4], "little")
    leaf_size = 52 if extended else 28
    blob[off + 4 : off + 8] = leaf_size.to_bytes(4, "little")
    if extended:
        record = struct.pack("<Iii6iIIII", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    else:
        record = struct.pack("<Ihh6hHHHH", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    blob[leaf_ofs : leaf_ofs + leaf_size] = record
    return bytes(blob)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    extended = "--qbsp" in argv
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(synth_solid_cube(extended=extended))
    print(f"wrote {path} ({path.stat().st_size} bytes, {'QBSP' if extended else 'IBSP'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
