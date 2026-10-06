"""A read-only IBSP38 reader: point contents, and nothing else.

Why it lives in the repository and not in a session scratchpad: the scratchpad
is swept without warning, and on 2026-09-13 it took this reader, three probes
and a build helper with it in the middle of a slice - after which a rebuild
silently did not happen and an old binary's verdict was nearly recorded as a
measurement of new code (ledger rows 192, 194; memory
`service-scripts-never-in-scratch`).

What it answers is the one question the gates ask of a compiled map: what are
the contents at this point. That is enough for `Stands` (`mapgen_bsp.c`'s three
samples) and for «is there liquid here», which between them have settled every
flood question this project has asked.

THE LUMP TABLE IS THE PART TO GET RIGHT. The first rewrite of this file read
leafs from lump 10 - which is LEAFBRUSHES - and returned numbers like 14877118
for a contents field, then answered the opposite of the recorded measurement at
`1104 1120 624` (ledger row 160). A reader that is wrong is worse than no reader,
because its output looks like a measurement. IBSP38: 0 entities, 1 planes,
2 vertexes, 3 visibility, 4 nodes, 5 texinfo, 6 faces, 7 lighting, 8 LEAFS,
9 leaffaces, 10 leafbrushes, 11 edges, 12 surfedges, 13 models, 14 brushes,
15 brushsides.

    from bsp_reader import Bsp
    Bsp(path).contents(x, y, z)   -> int, the Quake II contents bits
"""
from __future__ import annotations

import struct
from pathlib import Path

LUMP_PLANES = 1
LUMP_NODES = 4
LUMP_LEAFS = 8

CONTENTS_SOLID = 0x01
CONTENTS_LAVA = 0x08
CONTENTS_SLIME = 0x10
CONTENTS_WATER = 0x20

# dplane_t: normal[3] float, dist float, type int32
PLANE_SIZE = 20
# dnode_t: planenum int32, children[2] int32, mins[3] int16, maxs[3] int16,
#          firstface uint16, numfaces uint16
NODE_SIZE = 28
# dleaf_t: contents int32, cluster int16, area int16, mins[3] int16,
#          maxs[3] int16, firstleafface uint16, numleaffaces uint16,
#          firstleafbrush uint16, numleafbrushes uint16
LEAF_SIZE = 28


class Bsp:
    """One compiled map, decoded far enough to answer `contents`."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        data = self.path.read_bytes()
        if data[:4] != b"IBSP":
            raise ValueError(f"{self.path}: not IBSP")
        self.version, = struct.unpack_from("<i", data, 4)
        if self.version != 38:
            raise ValueError(f"{self.path}: IBSP version {self.version}, not 38")

        def lump(i: int) -> bytes:
            off, size = struct.unpack_from("<ii", data, 8 + 8 * i)
            return data[off:off + size]

        self._planes = lump(LUMP_PLANES)
        self._nodes = lump(LUMP_NODES)
        self._leafs = lump(LUMP_LEAFS)
        self.num_nodes = len(self._nodes) // NODE_SIZE
        self.num_leafs = len(self._leafs) // LEAF_SIZE

    def _plane(self, i: int):
        nx, ny, nz, dist = struct.unpack_from("<4f", self._planes,
                                              PLANE_SIZE * i)
        return nx, ny, nz, dist

    def _node(self, i: int):
        planenum, c0, c1 = struct.unpack_from("<i2i", self._nodes,
                                              NODE_SIZE * i)
        return planenum, c0, c1

    def _leaf_contents(self, i: int) -> int:
        contents, = struct.unpack_from("<i", self._leafs, LEAF_SIZE * i)
        return contents

    def contents(self, x: float, y: float, z: float) -> int:
        """The contents of the leaf this point falls in.

        The leaf's own contents, exactly where `MapGenBsp_PointContentsAt`
        starts: the compiler fills unoccupied leaves with SOLID by design, so
        solid here does not imply that a brush contains the point (Codex,
        2026-09-13 §5).
        """
        node = 0
        while node >= 0:
            if node >= self.num_nodes:
                raise ValueError(f"{self.path}: node {node} out of range")
            planenum, c0, c1 = self._node(node)
            nx, ny, nz, dist = self._plane(planenum)
            d = nx * x + ny * y + nz * z - dist
            node = c0 if d >= 0.0 else c1
        leaf = -1 - node
        if leaf >= self.num_leafs:
            raise ValueError(f"{self.path}: leaf {leaf} out of range")
        return self._leaf_contents(leaf)
