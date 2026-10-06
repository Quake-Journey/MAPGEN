#!/usr/bin/env python3
"""Independent Quake II BSP reader and canonical semantic digest for MAPGEN-1.

This is the M0 ORACLE. It exists to answer "what does the compiled map actually
contain?" without using either of the two things that could be wrong:

  * not the compiler's own log or exit code - an unqualified compiler cannot be
    its own golden oracle (contract section 17), and this particular compiler
    exits 0 on a leaked map (C0 finding F1);
  * not the engine's C loader - the engine and the worker will later share that
    parser, so a bug in it would be invisible to a test that used it to check
    itself. Semantic parity between this reader and src/common/bsp.c is a
    RESULT the M2 parity fixture must prove, not an assumption made here.

It reads only the lumps needed for collision and entity truth, which is exactly
the set contract section 18 requires reconstructed from the compiled BSP:
planes, nodes, leafs, leafbrushes, brushes, brushsides, texinfo, models,
visibility presence, areas and the entity string.

Both IBSP (standard) and QBSP (extended) v38 are supported: they differ only in
the on-disk width of node/leaf/face/brushside/leafbrush records.

Usage:
    python tools/mapgen_bsp_oracle.py <file.bsp> [--json]
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

IDBSPHEADER = 0x50534249  # 'IBSP'
QBSPHEADER = 0x50534251  # 'QBSP'
BSPVERSION = 38
HEADER_LUMPS = 19

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

CONTENTS = {
    "CONTENTS_SOLID": 1,
    "CONTENTS_WINDOW": 2,
    "CONTENTS_AUX": 4,
    "CONTENTS_LAVA": 8,
    "CONTENTS_SLIME": 16,
    "CONTENTS_WATER": 32,
    "CONTENTS_MIST": 64,
    "CONTENTS_AREAPORTAL": 0x8000,
    "CONTENTS_PLAYERCLIP": 0x10000,
    "CONTENTS_MONSTERCLIP": 0x20000,
    "CONTENTS_ORIGIN": 0x1000000,
    "CONTENTS_MONSTER": 0x2000000,
    "CONTENTS_DEADMONSTER": 0x4000000,
    "CONTENTS_DETAIL": 0x8000000,
    "CONTENTS_TRANSLUCENT": 0x10000000,
    "CONTENTS_LADDER": 0x20000000,
}

SURF = {
    "SURF_LIGHT": 0x1,
    "SURF_SLICK": 0x2,
    "SURF_SKY": 0x4,
    "SURF_WARP": 0x8,
    "SURF_TRANS33": 0x10,
    "SURF_TRANS66": 0x20,
    "SURF_FLOWING": 0x40,
    "SURF_NODRAW": 0x80,
    "SURF_HINT": 0x100,
    "SURF_SKIP": 0x200,
}

MASK_LIQUID = CONTENTS["CONTENTS_LAVA"] | CONTENTS["CONTENTS_SLIME"] | CONTENTS["CONTENTS_WATER"]


class BspError(Exception):
    """The file is not a BSP this oracle will vouch for."""


@dataclass
class Plane:
    normal: tuple[float, float, float]
    dist: float
    type: int


@dataclass
class Node:
    planenum: int
    children: tuple[int, int]
    mins: tuple[int, int, int]
    maxs: tuple[int, int, int]


@dataclass
class Leaf:
    contents: int
    cluster: int
    area: int
    mins: tuple[int, int, int]
    maxs: tuple[int, int, int]
    firstleafbrush: int
    numleafbrushes: int


@dataclass
class Brush:
    firstside: int
    numsides: int
    contents: int


@dataclass
class BrushSide:
    planenum: int
    texinfo: int


@dataclass
class TexInfo:
    texture: str
    flags: int
    value: int
    nexttexinfo: int


@dataclass
class Model:
    mins: tuple[float, float, float]
    maxs: tuple[float, float, float]
    origin: tuple[float, float, float]
    headnode: int


@dataclass
class Bsp:
    path: Path
    extended: bool
    file_bytes: int
    planes: list[Plane] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    leafs: list[Leaf] = field(default_factory=list)
    leafbrushes: list[int] = field(default_factory=list)
    brushes: list[Brush] = field(default_factory=list)
    brushsides: list[BrushSide] = field(default_factory=list)
    texinfo: list[TexInfo] = field(default_factory=list)
    models: list[Model] = field(default_factory=list)
    entities_raw: str = ""
    visibility_bytes: int = 0
    lighting_bytes: int = 0
    num_faces: int = 0
    num_areas: int = 0
    num_areaportals: int = 0

    # ---------------------------------------------------------------- queries
    def entities(self) -> list[dict[str, str]]:
        """Parse the entity string into ordered key/value dicts.

        Deliberately strict: an unterminated block or a key outside a block is
        an error, because "the compiler emitted something almost parseable" is
        exactly the state a validator must reject.
        """
        out: list[dict[str, str]] = []
        text = self.entities_raw
        i = 0
        n = len(text)
        current: dict[str, str] | None = None
        while i < n:
            ch = text[i]
            if ch in " \t\r\n":
                i += 1
                continue
            if ch == "{":
                if current is not None:
                    raise BspError("nested '{' in entity string")
                current = {}
                i += 1
                continue
            if ch == "}":
                if current is None:
                    raise BspError("unmatched '}' in entity string")
                out.append(current)
                current = None
                i += 1
                continue
            if ch == '"':
                if current is None:
                    raise BspError("key/value outside an entity block")
                key, i = self._quoted(text, i)
                while i < n and text[i] in " \t\r\n":
                    i += 1
                if i >= n or text[i] != '"':
                    raise BspError(f"key {key!r} has no value")
                value, i = self._quoted(text, i)
                current[key] = value
                continue
            if ch == "\0":
                break
            raise BspError(f"unexpected character {ch!r} at offset {i} of the entity string")
        if current is not None:
            raise BspError("unterminated entity block")
        return out

    @staticmethod
    def _quoted(text: str, i: int) -> tuple[str, int]:
        assert text[i] == '"'
        j = text.index('"', i + 1)
        return text[i + 1 : j], j + 1

    def point_leaf(self, point) -> Leaf:
        """Walk the BSP tree of model 0 exactly as the engine does."""
        if not self.nodes:
            return self.leafs[0]
        num = self.models[0].headnode if self.models else 0
        while num >= 0:
            node = self.nodes[num]
            plane = self.planes[node.planenum]
            d = (
                point[0] * plane.normal[0]
                + point[1] * plane.normal[1]
                + point[2] * plane.normal[2]
                - plane.dist
            )
            # A point exactly on the plane goes to the FRONT, which is what
            # BSP_PointLeaf does (src/common/bsp.c:1127-1136).
            num = node.children[1] if d < 0 else node.children[0]
        return self.leafs[-1 - num]

    def point_contents(self, point) -> int:
        """Leaf contents OR the contents of any brush in that leaf containing the point.

        Leaf contents alone are not the whole truth: detail brushes keep their
        contents on the brush, which is why the engine checks leafbrushes too.
        """
        leaf = self.point_leaf(point)
        contents = leaf.contents
        for i in range(leaf.firstleafbrush, leaf.firstleafbrush + leaf.numleafbrushes):
            brush = self.brushes[self.leafbrushes[i]]
            inside = True
            for s in range(brush.firstside, brush.firstside + brush.numsides):
                side = self.brushsides[s]
                plane = self.planes[side.planenum]
                d = (
                    point[0] * plane.normal[0]
                    + point[1] * plane.normal[1]
                    + point[2] * plane.normal[2]
                    - plane.dist
                )
                if d > 0:
                    inside = False
                    break
            if inside:
                contents |= brush.contents
        return contents

    def contents_names(self, mask: int) -> list[str]:
        return sorted(name for name, bit in CONTENTS.items() if mask & bit)

    def surface_flag_names(self) -> list[str]:
        seen = 0
        for ti in self.texinfo:
            seen |= ti.flags
        return sorted(name for name, bit in SURF.items() if seen & bit)

    def texture_names(self) -> list[str]:
        return sorted({ti.texture for ti in self.texinfo})

    def leaf_contents_histogram(self) -> dict[str, int]:
        hist: dict[str, int] = {}
        for leaf in self.leafs:
            key = ",".join(self.contents_names(leaf.contents)) or "EMPTY"
            hist[key] = hist.get(key, 0) + 1
        return dict(sorted(hist.items()))

    def cluster_count(self) -> int:
        clusters = {leaf.cluster for leaf in self.leafs if leaf.cluster >= 0}
        return len(clusters)

    # -------------------------------------------------------------- digesting
    def semantic_digest(self) -> str:
        """A canonical digest of MEANING, not of bytes.

        Excluded on purpose: lightmap bytes, vis bytes, file padding and lump
        offsets. Contract section 10 pins determinism to canonical semantic
        content, and a byte digest of the whole file would flag a harmless
        lighting difference as a determinism failure while missing a swapped
        brush contents value.
        """
        parts: list[str] = []
        parts.append(f"format={'QBSP' if self.extended else 'IBSP'}")
        parts.append(f"planes={len(self.planes)}")
        for p in self.planes:
            parts.append(
                "plane=%s,%s,%s,%s,%d"
                % (_num(p.normal[0]), _num(p.normal[1]), _num(p.normal[2]), _num(p.dist), p.type)
            )
        parts.append(f"brushes={len(self.brushes)}")
        for b in self.brushes:
            parts.append(f"brush={b.firstside},{b.numsides},{b.contents}")
        parts.append(f"brushsides={len(self.brushsides)}")
        for s in self.brushsides:
            parts.append(f"side={s.planenum},{s.texinfo}")
        parts.append(f"texinfo={len(self.texinfo)}")
        for t in self.texinfo:
            parts.append(f"tex={t.texture},{t.flags},{t.value},{t.nexttexinfo}")
        parts.append(f"nodes={len(self.nodes)}")
        for n in self.nodes:
            parts.append(f"node={n.planenum},{n.children[0]},{n.children[1]}")
        parts.append(f"leafs={len(self.leafs)}")
        for lf in self.leafs:
            parts.append(
                f"leaf={lf.contents},{lf.cluster},{lf.area},{lf.firstleafbrush},{lf.numleafbrushes}"
            )
        parts.append(f"leafbrushes={len(self.leafbrushes)}")
        parts.append("lb=" + ",".join(str(x) for x in self.leafbrushes))
        parts.append(f"models={len(self.models)}")
        for m in self.models:
            parts.append(
                "model=%s,%s,%s,%s,%s,%s,%d"
                % (
                    _num(m.mins[0]),
                    _num(m.mins[1]),
                    _num(m.mins[2]),
                    _num(m.maxs[0]),
                    _num(m.maxs[1]),
                    _num(m.maxs[2]),
                    m.headnode,
                )
            )
        ents = self.entities()
        parts.append(f"entities={len(ents)}")
        for ent in ents:
            kv = ";".join(f"{k}={v}" for k, v in sorted(ent.items()))
            parts.append(f"ent={kv}")
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def canonical_text(self) -> str:
        """The same canonical text `MapGenBsp_CanonicalText` produces.

        Two independent readers of the same file must agree here. This is the
        cross-check that makes either believable: this reader is validated
        against 132 real shipped maps, and the C document is then validated
        against this reader on the same 132.
        """
        out: list[str] = []
        out.append(f"format={'QBSP' if self.extended else 'IBSP'}")
        out.append(f"planes={len(self.planes)}")
        for p in self.planes:
            out.append("plane=%s,%s,%s,%s,%d" % (
                canon_float(p.normal[0]), canon_float(p.normal[1]),
                canon_float(p.normal[2]), canon_float(p.dist), p.type))
        out.append(f"brushes={len(self.brushes)}")
        for b in self.brushes:
            out.append(f"brush={b.firstside},{b.numsides},{b.contents}")
        out.append(f"brushsides={len(self.brushsides)}")
        for s in self.brushsides:
            out.append(f"side={s.planenum},{s.texinfo}")
        out.append(f"texinfo={len(self.texinfo)}")
        for ti in self.texinfo:
            out.append(f"tex={ti.texture},{ti.flags},{ti.value},{ti.nexttexinfo}")
        out.append(f"nodes={len(self.nodes)}")
        for n in self.nodes:
            out.append(f"node={n.planenum},{n.children[0]},{n.children[1]}")
        out.append(f"leafs={len(self.leafs)}")
        for lf in self.leafs:
            out.append(f"leaf={lf.contents},{lf.cluster},{lf.area},"
                       f"{lf.firstleafbrush},{lf.numleafbrushes}")
        out.append(f"leafbrushes={len(self.leafbrushes)}")
        out.append("lb=" + ",".join(str(x) for x in self.leafbrushes))
        out.append(f"models={len(self.models)}")
        for m in self.models:
            out.append("model=%s,%s,%s,%s,%s,%s,%d" % (
                canon_float(m.mins[0]), canon_float(m.mins[1]), canon_float(m.mins[2]),
                canon_float(m.maxs[0]), canon_float(m.maxs[1]), canon_float(m.maxs[2]),
                m.headnode))
        out.append(f"faces={self.num_faces}")
        out.append(f"entitychars={len(self.entities_raw)}")
        return "\n".join(out) + "\n"

    def canonical_digest(self) -> int:
        return fnv1a64(self.canonical_text().encode("utf-8"))

    def summary(self) -> dict:
        ents = self.entities()
        classnames: dict[str, int] = {}
        for ent in ents:
            cn = ent.get("classname", "<none>")
            classnames[cn] = classnames.get(cn, 0) + 1
        return {
            "path": str(self.path),
            "format": "QBSP" if self.extended else "IBSP",
            "file_bytes": self.file_bytes,
            "counts": {
                "planes": len(self.planes),
                "nodes": len(self.nodes),
                "leafs": len(self.leafs),
                "leafbrushes": len(self.leafbrushes),
                "brushes": len(self.brushes),
                "brushsides": len(self.brushsides),
                "texinfo": len(self.texinfo),
                "models": len(self.models),
                "faces": self.num_faces,
                "areas": self.num_areas,
                "areaportals": self.num_areaportals,
                "entities": len(ents),
                "clusters": self.cluster_count(),
            },
            "visibility_bytes": self.visibility_bytes,
            "lighting_bytes": self.lighting_bytes,
            "entity_classnames": dict(sorted(classnames.items())),
            "textures": self.texture_names(),
            "surface_flags": self.surface_flag_names(),
            "leaf_contents": self.leaf_contents_histogram(),
            "semantic_digest": self.semantic_digest(),
        }


def canon_float(v: float) -> str:
    """Canonical float text, matching src/mapgen/mapgen_bsp.c exactly.

    Deliberately NOT `f"{v:.6f}"`: that rounds half-to-even on the decimal
    representation, while the C writes the integer algorithm below. Two
    implementations of "the same" digest that disagree on one tie would look
    like a parsing difference, which is the one thing this comparison must not
    manufacture.
    """
    negative = v < 0.0
    if negative:
        v = -v
    scaled = v * 1000000.0 + 0.5
    if not (scaled < 9.0e18):
        scaled = 0.0
    units = int(scaled)
    whole, frac = divmod(units, 1000000)
    if whole == 0 and frac == 0:
        negative = False
    return f"{'-' if negative else ''}{whole}.{frac:06d}"


def fnv1a64(data: bytes) -> int:
    h = 1469598103934665603
    for byte in data:
        h ^= byte
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def _num(v: float) -> str:
    """Canonical float text: fixed precision, no negative zero, locale-free."""
    text = f"{v:.6f}"
    if float(text) == 0.0:
        return "0.000000"
    return text


def load(path: Path) -> Bsp:
    data = path.read_bytes()
    if len(data) < 4 + 4 + HEADER_LUMPS * 8:
        raise BspError(f"file is {len(data)} bytes, smaller than a BSP header")
    ident, version = struct.unpack_from("<II", data, 0)
    if ident == IDBSPHEADER:
        extended = False
    elif ident == QBSPHEADER:
        extended = True
    else:
        raise BspError(f"unknown ident 0x{ident:08x} (expected IBSP or QBSP)")
    if version != BSPVERSION:
        raise BspError(f"version {version}, expected {BSPVERSION}")

    lumps = []
    for i in range(HEADER_LUMPS):
        ofs, length = struct.unpack_from("<II", data, 8 + i * 8)
        if ofs + length > len(data):
            raise BspError(f"lump {i} out of bounds: ofs={ofs} len={length} file={len(data)}")
        lumps.append((ofs, length))

    bsp = Bsp(path=path, extended=extended, file_bytes=len(data))

    def blob(index: int) -> bytes:
        ofs, length = lumps[index]
        return data[ofs : ofs + length]

    def records(index: int, size: int, name: str) -> int:
        _, length = lumps[index]
        if size and length % size:
            raise BspError(f"{name} lump has odd size {length} for record size {size}")
        return length // size if size else 0

    # planes: normal[3], dist, type
    pdata = blob(LUMP_PLANES)
    for i in range(records(LUMP_PLANES, 20, "planes")):
        nx, ny, nz, dist, ptype = struct.unpack_from("<ffffi", pdata, i * 20)
        bsp.planes.append(Plane((nx, ny, nz), dist, ptype))

    # nodes: IBSP 28 bytes (int children, short bbox), QBSP 44 (int children, int bbox)
    ndata = blob(LUMP_NODES)
    if extended:
        for i in range(records(LUMP_NODES, 44, "nodes")):
            pn, c0, c1, x0, y0, z0, x1, y1, z1, _ff, _nf = struct.unpack_from("<Iii6iII", ndata, i * 44)
            bsp.nodes.append(Node(pn, (c0, c1), (x0, y0, z0), (x1, y1, z1)))
    else:
        for i in range(records(LUMP_NODES, 28, "nodes")):
            pn, c0, c1, x0, y0, z0, x1, y1, z1, _ff, _nf = struct.unpack_from("<Iii6hHH", ndata, i * 28)
            bsp.nodes.append(Node(pn, (c0, c1), (x0, y0, z0), (x1, y1, z1)))

    # leafs: IBSP 28, QBSP 52
    ldata = blob(LUMP_LEAFS)
    if extended:
        for i in range(records(LUMP_LEAFS, 52, "leafs")):
            (
                contents,
                cluster,
                area,
                x0,
                y0,
                z0,
                x1,
                y1,
                z1,
                flf,
                nlf,
                flb,
                nlb,
            ) = struct.unpack_from("<Iii6iIIII", ldata, i * 52)
            bsp.leafs.append(Leaf(contents, cluster, area, (x0, y0, z0), (x1, y1, z1), flb, nlb))
    else:
        for i in range(records(LUMP_LEAFS, 28, "leafs")):
            (
                contents,
                cluster,
                area,
                x0,
                y0,
                z0,
                x1,
                y1,
                z1,
                flf,
                nlf,
                flb,
                nlb,
            ) = struct.unpack_from("<Ihh6hHHHH", ldata, i * 28)
            bsp.leafs.append(Leaf(contents, cluster, area, (x0, y0, z0), (x1, y1, z1), flb, nlb))

    # leafbrushes: IBSP uint16, QBSP uint32
    lbdata = blob(LUMP_LEAFBRUSHES)
    if extended:
        bsp.leafbrushes = list(struct.unpack_from(f"<{len(lbdata)//4}I", lbdata, 0)) if lbdata else []
    else:
        bsp.leafbrushes = list(struct.unpack_from(f"<{len(lbdata)//2}H", lbdata, 0)) if lbdata else []

    # brushes: firstside, numsides, contents (always 12 bytes)
    bdata = blob(LUMP_BRUSHES)
    for i in range(records(LUMP_BRUSHES, 12, "brushes")):
        fs, ns, contents = struct.unpack_from("<iii", bdata, i * 12)
        bsp.brushes.append(Brush(fs, ns, contents))

    # brushsides: IBSP (uint16 planenum, int16 texinfo) = 4, QBSP (uint32, int32) = 8
    bsdata = blob(LUMP_BRUSHSIDES)
    if extended:
        for i in range(records(LUMP_BRUSHSIDES, 8, "brushsides")):
            pn, ti = struct.unpack_from("<Ii", bsdata, i * 8)
            bsp.brushsides.append(BrushSide(pn, ti))
    else:
        for i in range(records(LUMP_BRUSHSIDES, 4, "brushsides")):
            pn, ti = struct.unpack_from("<Hh", bsdata, i * 4)
            bsp.brushsides.append(BrushSide(pn, ti))

    # texinfo: 76 bytes in both formats
    tdata = blob(LUMP_TEXINFO)
    for i in range(records(LUMP_TEXINFO, 76, "texinfo")):
        base = i * 76
        flags, value = struct.unpack_from("<ii", tdata, base + 32)
        raw = tdata[base + 40 : base + 72]
        # Control bytes never belong in a texture reference and would go on to
        # reach a log, a UI and a compiler command line. The C document
        # replaces them with '?'; this must match, or the cross-check would
        # report a difference that is only a difference in hygiene.
        name = "".join(
            "?" if byte < 0x20 else chr(byte)
            for byte in raw.split(b"\0", 1)[0]
        )
        nxt = struct.unpack_from("<i", tdata, base + 72)[0]
        bsp.texinfo.append(TexInfo(name, flags, value, nxt))

    # models: 48 bytes in both formats
    mdata = blob(LUMP_MODELS)
    for i in range(records(LUMP_MODELS, 48, "models")):
        vals = struct.unpack_from("<9f i i i", mdata, i * 48)
        bsp.models.append(
            Model((vals[0], vals[1], vals[2]), (vals[3], vals[4], vals[5]), (vals[6], vals[7], vals[8]), vals[9])
        )

    raw_ents = blob(LUMP_ENTITIES)
    bsp.entities_raw = raw_ents.split(b"\0", 1)[0].decode("ascii", "replace")
    bsp.visibility_bytes = lumps[LUMP_VISIBILITY][1]
    bsp.lighting_bytes = lumps[LUMP_LIGHTING][1]
    face_size = 28 if extended else 20
    bsp.num_faces = records(LUMP_FACES, face_size, "faces")
    bsp.num_areas = records(LUMP_AREAS, 8, "areas")
    bsp.num_areaportals = records(LUMP_AREAPORTALS, 8, "areaportals")

    if not bsp.models:
        raise BspError("no models: a BSP without model 0 has no world")

    # Index validation. Contract section 6.2 requires indices, models, faces,
    # brushes and portals to be checked before anything trusts them, and this
    # oracle is what everything downstream trusts. Without it a malformed file
    # makes the reader raise IndexError deep inside a tree walk, which a caller
    # cannot distinguish from a bug in the reader itself - a crash is not a
    # rejection.
    for i, leaf in enumerate(bsp.leafs):
        if leaf.numleafbrushes < 0 or leaf.firstleafbrush < 0:
            raise BspError(f"leaf {i} has a negative leafbrush range")
        if leaf.firstleafbrush + leaf.numleafbrushes > len(bsp.leafbrushes):
            raise BspError(
                f"leaf {i} references leafbrushes "
                f"{leaf.firstleafbrush}..{leaf.firstleafbrush + leaf.numleafbrushes} "
                f"but only {len(bsp.leafbrushes)} exist"
            )
    for i, index in enumerate(bsp.leafbrushes):
        if index >= len(bsp.brushes):
            raise BspError(f"leafbrush {i} references brush {index} of {len(bsp.brushes)}")
    for i, brush in enumerate(bsp.brushes):
        if brush.firstside < 0 or brush.numsides < 0:
            raise BspError(f"brush {i} has a negative side range")
        if brush.firstside + brush.numsides > len(bsp.brushsides):
            raise BspError(
                f"brush {i} references brushsides "
                f"{brush.firstside}..{brush.firstside + brush.numsides} "
                f"but only {len(bsp.brushsides)} exist"
            )
    for i, side in enumerate(bsp.brushsides):
        if side.planenum >= len(bsp.planes):
            raise BspError(f"brushside {i} references plane {side.planenum} of {len(bsp.planes)}")
        if side.texinfo >= len(bsp.texinfo):
            raise BspError(f"brushside {i} references texinfo {side.texinfo} of {len(bsp.texinfo)}")
    for i, node in enumerate(bsp.nodes):
        if node.planenum >= len(bsp.planes):
            raise BspError(f"node {i} references plane {node.planenum} of {len(bsp.planes)}")
        for child in node.children:
            if child >= 0:
                if child >= len(bsp.nodes):
                    raise BspError(f"node {i} references node {child} of {len(bsp.nodes)}")
            elif (-1 - child) >= len(bsp.leafs):
                raise BspError(f"node {i} references leaf {-1 - child} of {len(bsp.leafs)}")
    for i, model in enumerate(bsp.models):
        if model.headnode >= len(bsp.nodes) and bsp.nodes:
            raise BspError(f"model {i} references node {model.headnode} of {len(bsp.nodes)}")

    return bsp


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    try:
        bsp = load(path)
    except BspError as exc:
        print(f"BspError: {exc}")
        return 1
    summary = bsp.summary()
    if "--json" in argv:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for key, value in summary.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
