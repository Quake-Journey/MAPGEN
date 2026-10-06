"""Controlled damage to a compiled map, for proving a gate can see it.

A gate that has never failed is not known to work. Codex's baseline ruling of
2026-09-03 lists the damage each mandatory RED must do - world solid, reachable
empty space, liquid and hazard contents, a visible surface, a texture mapping,
model ownership, a mover target, a trigger, an areaportal, a spawn, item or
light, and a traversal obligation - and requires each one to still be a map the
tools accept, and to be refused for its OWN reason.

Every mutation here therefore produces a BSP that still loads: counts stay
consistent, indices stay in range, offsets are recomputed. What changes is the
meaning.

The same file also carries the equivalence-preserving changes, which must NOT
be refused: a face split in two, a plane duplicated, a texinfo duplicated, the
entities reordered and their numbers reformatted. Those are the compiler's own
freedoms, and a gate that fails them would be unusable.
"""
from __future__ import annotations

import struct
from pathlib import Path

NUM_LUMPS = 19
(L_ENTITIES, L_PLANES, L_VERTEXES, L_VISIBILITY, L_NODES, L_TEXINFO,
 L_FACES, L_LIGHTING, L_LEAFS, L_LEAFFACES, L_LEAFBRUSHES, L_EDGES,
 L_SURFEDGES, L_MODELS, L_BRUSHES, L_BRUSHSIDES, L_POP, L_AREAS,
 L_AREAPORTALS) = range(NUM_LUMPS)

CONTENTS_SOLID = 1
CONTENTS_WINDOW = 2
CONTENTS_LAVA = 8
CONTENTS_SLIME = 16
CONTENTS_WATER = 32
CONTENTS_AREAPORTAL = 0x8000
# What a player runs into and cannot see, and what changes how he moves. The
# equivalence gate compares these bit for bit, so the mutations need them.
CONTENTS_PLAYERCLIP = 0x10000
CONTENTS_MONSTERCLIP = 0x20000
CONTENTS_LADDER = 0x20000000

SZ_PLANE, SZ_NODE, SZ_LEAF = 20, 28, 28
SZ_TEXINFO, SZ_FACE, SZ_MODEL = 76, 20, 48
SZ_BRUSH, SZ_BRUSHSIDE, SZ_EDGE = 12, 4, 4
SZ_AREA, SZ_AREAPORTAL = 8, 8


class BspFile:
    """The nineteen lumps, held apart so any of them can be replaced."""

    def __init__(self, path: Path):
        raw = Path(path).read_bytes()
        self.ident, self.version = struct.unpack_from("<4si", raw, 0)
        self.lumps = []
        for i in range(NUM_LUMPS):
            off, length = struct.unpack_from("<ii", raw, 8 + i * 8)
            self.lumps.append(bytearray(raw[off:off + length]))

    def write(self, path: Path) -> Path:
        """Rebuild with recomputed offsets. Lump ORDER and padding are the
        compiler's business, so they are simply chosen here; the reader is
        required to follow the directory rather than assume a layout."""
        header = bytearray(8 + NUM_LUMPS * 8)
        struct.pack_into("<4si", header, 0, self.ident, self.version)
        body = bytearray()
        offset = len(header)
        for i, data in enumerate(self.lumps):
            while offset % 4:
                body += b"\0"
                offset += 1
            struct.pack_into("<ii", header, 8 + i * 8, offset, len(data))
            body += data
            offset += len(data)
        Path(path).write_bytes(bytes(header) + bytes(body))
        return Path(path)

    # ---- typed views ----------------------------------------------------

    def count(self, lump: int, size: int) -> int:
        return len(self.lumps[lump]) // size

    def leaf(self, i: int):
        # contents, cluster, area, mins[3], maxs[3], firstleafface,
        # numleaffaces, firstleafbrush, numleafbrushes - 28 bytes.
        return struct.unpack_from("<ihh6h4H", self.lumps[L_LEAFS],
                                  i * SZ_LEAF)

    def set_leaf_contents(self, i: int, contents: int) -> None:
        struct.pack_into("<i", self.lumps[L_LEAFS], i * SZ_LEAF, contents)

    def leaf_brushes(self, i: int) -> list[int]:
        leaf = self.leaf(i)
        first, num = leaf[11], leaf[12]
        return [struct.unpack_from("<H", self.lumps[L_LEAFBRUSHES], (first + k) * 2)[0]
                for k in range(num)]

    def set_brush_contents(self, i: int, contents: int) -> None:
        struct.pack_into("<i", self.lumps[L_BRUSHES], i * SZ_BRUSH + 8, contents)

    def brush_contents(self, i: int) -> int:
        return struct.unpack_from("<i", self.lumps[L_BRUSHES],
                                  i * SZ_BRUSH + 8)[0]

    def area(self, i: int) -> tuple:
        """(numareaportals, firstareaportal) - the run of portals this area
        declares. Q2 floods areas by walking exactly this range."""
        return struct.unpack_from("<ii", self.lumps[L_AREAS], i * SZ_AREA)

    def set_area(self, i: int, num: int, first: int) -> None:
        struct.pack_into("<ii", self.lumps[L_AREAS], i * SZ_AREA, num, first)

    def areaportal(self, i: int) -> tuple:
        """(portalnum, otherarea) - which portal, and the area on its far
        side."""
        return struct.unpack_from("<ii", self.lumps[L_AREAPORTALS],
                                  i * SZ_AREAPORTAL)

    def set_areaportal(self, i: int, portalnum: int, otherarea: int) -> None:
        struct.pack_into("<ii", self.lumps[L_AREAPORTALS],
                         i * SZ_AREAPORTAL, portalnum, otherarea)

    def area_graph(self) -> list[list[tuple]]:
        """Each area's portals, as the engine would walk them."""
        out = []
        for a in range(self.count(L_AREAS, SZ_AREA)):
            num, first = self.area(a)
            out.append([self.areaportal(first + k) for k in range(num)])
        return out

    def texinfo_name(self, i: int) -> str:
        raw = struct.unpack_from("<32s", self.lumps[L_TEXINFO],
                                 i * SZ_TEXINFO + 40)[0]
        return raw.split(b"\0")[0].decode("latin1")

    def set_texinfo_name(self, i: int, name: str) -> None:
        struct.pack_into("<32s", self.lumps[L_TEXINFO], i * SZ_TEXINFO + 40,
                         name.encode("latin1")[:31])

    def texinfo_axis(self, i: int) -> tuple:
        return struct.unpack_from("<8f", self.lumps[L_TEXINFO], i * SZ_TEXINFO)

    def set_texinfo_axis(self, i: int, axis) -> None:
        struct.pack_into("<8f", self.lumps[L_TEXINFO], i * SZ_TEXINFO, *axis)

    def face(self, i: int):
        return struct.unpack_from("<Hhihh4Bi", self.lumps[L_FACES],
                                  i * SZ_FACE)

    def set_face_texinfo(self, i: int, texinfo: int) -> None:
        struct.pack_into("<h", self.lumps[L_FACES], i * SZ_FACE + 10, texinfo)

    def model(self, i: int):
        return struct.unpack_from("<9f3i", self.lumps[L_MODELS], i * SZ_MODEL)

    def set_model_bounds(self, i: int, mins, maxs) -> None:
        struct.pack_into("<6f", self.lumps[L_MODELS], i * SZ_MODEL,
                         *mins, *maxs)

    @property
    def entities(self) -> str:
        return bytes(self.lumps[L_ENTITIES]).split(b"\0")[0].decode("latin1")

    @entities.setter
    def entities(self, text: str) -> None:
        self.lumps[L_ENTITIES] = bytearray(text.encode("latin1") + b"\0")


# ---- entity text -------------------------------------------------------

def entity_blocks(text: str) -> list[str]:
    """The `{ ... }` blocks, as written, in order."""
    out, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start:i + 1])
                start = None
    return out


def blocks_to_text(blocks: list[str]) -> str:
    return "".join(b + "\n" for b in blocks)


def block_value(block: str, key: str) -> str | None:
    marker = f'"{key}"'
    at = block.find(marker)
    if at < 0:
        return None
    rest = block[at + len(marker):]
    first = rest.find('"')
    if first < 0:
        return None
    second = rest.find('"', first + 1)
    return rest[first + 1:second] if second > 0 else None


def set_block_value(block: str, key: str, value: str) -> str:
    marker = f'"{key}"'
    at = block.find(marker)
    if at < 0:
        head, tail = block[:-1].rstrip(), block[-1]
        return f'{head}\n"{key}" "{value}"\n{tail}'
    rest = block[at + len(marker):]
    first = rest.find('"')
    second = rest.find('"', first + 1)
    return (block[:at + len(marker)] + rest[:first + 1] + value
            + rest[second:])


def find_block(blocks: list[str], classname: str) -> int | None:
    for i, b in enumerate(blocks):
        if block_value(b, "classname") == classname:
            return i
    return None


def find_block_prefix(blocks: list[str], prefix: str) -> int | None:
    for i, b in enumerate(blocks):
        name = block_value(b, "classname") or ""
        if name.startswith(prefix):
            return i
    return None


# ---- leaves, picked by what they are ------------------------------------

def world_leaves(bsp: BspFile) -> set[int]:
    """The leaves the WORLD tree reaches.

    A brush model - a door, a lift - has leaves of its own in the same array,
    and `MapGenBsp_PointContents` walks model zero. Marking one of a door's
    leaves changes nothing anything will ever look at, which is how a mutation
    can be applied, be reported as applied, and prove nothing.
    """
    import struct as _struct
    nodes = bsp.lumps[L_NODES]
    world = bsp.model(0)
    out: set[int] = set()
    stack = [world[9]]                      # the world's headnode
    seen = set()
    while stack:
        node = stack.pop()
        if node < 0:
            out.add(-1 - node)
            continue
        if node in seen:
            continue
        seen.add(node)
        if node * SZ_NODE + SZ_NODE > len(nodes):
            continue
        children = _struct.unpack_from("<2i", nodes, node * SZ_NODE + 4)
        stack.extend(children)
    return out


def leaf_of_class(bsp: BspFile, wanted: str, min_brushes: int = 1) -> int | None:
    """A leaf whose contents put it in `wanted`, biggest first so the mutation
    lands somewhere the sampler will look."""
    best, best_size = None, -1.0
    for i in range(bsp.count(L_LEAFS, SZ_LEAF)):
        leaf = bsp.leaf(i)
        contents = leaf[0]
        if contents & (CONTENTS_SOLID | CONTENTS_WINDOW):
            cls = "solid"
        elif contents & (CONTENTS_LAVA | CONTENTS_SLIME):
            cls = "hazard"
        elif contents & CONTENTS_WATER:
            cls = "liquid"
        else:
            cls = "empty"
        if cls != wanted:
            continue
        if len(bsp.leaf_brushes(i)) < min_brushes:
            continue
        mins, maxs = leaf[3:6], leaf[6:9]
        size = 1.0
        for a in range(3):
            size *= max(1, maxs[a] - mins[a])
        if size > best_size:
            best, best_size = i, size
    return best
