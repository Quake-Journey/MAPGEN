"""An independent reading of a donor's geometry, for the C one to be checked
against.

Sharing no code with `src/mapgen/mapgen_geometry.c` is the whole point. Both
answer the same question from the same bytes, and where they disagree one of
them is wrong - which is how the segmentation work found that a volume's class
depended on which member you asked, and how the clipping here found that a
brush's shape depends on the order its planes are applied in only if you get it
wrong.

    python tools/mapgen_geometry_oracle.py <map.bsp> [--text]

Prints the canonical geometry digest, or the canonical text itself.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

LUMP_ENTITIES, LUMP_PLANES, LUMP_VERTEXES = 0, 1, 2
LUMP_NODES, LUMP_TEXINFO, LUMP_FACES = 4, 5, 6
LUMP_LEAFS, LUMP_LEAFBRUSHES = 8, 10
LUMP_EDGES, LUMP_SURFEDGES, LUMP_MODELS = 11, 12, 13
LUMP_BRUSHES, LUMP_BRUSHSIDES = 14, 15

WORLD_EXTENT = 65536.0
WINDING_EPSILON = 0.01
FACE_SAMPLES = 9
CANON_SCALE = 10000.0


def lump(raw: bytes, index: int) -> bytes:
    off, length = struct.unpack_from("<ii", raw, 8 + index * 8)
    return raw[off:off + length]


class Bsp:
    def __init__(self, path: Path):
        raw = path.read_bytes()
        self.planes = [struct.unpack_from("<ffffi", lump(raw, LUMP_PLANES), i * 20)
                       for i in range(len(lump(raw, LUMP_PLANES)) // 20)]
        self.brushes = [struct.unpack_from("<iii", lump(raw, LUMP_BRUSHES), i * 12)
                        for i in range(len(lump(raw, LUMP_BRUSHES)) // 12)]
        sides = lump(raw, LUMP_BRUSHSIDES)
        self.sides = [struct.unpack_from("<Hh", sides, i * 4)
                      for i in range(len(sides) // 4)]
        ti = lump(raw, LUMP_TEXINFO)
        self.texinfo = []
        for i in range(len(ti) // 76):
            axis = struct.unpack_from("<8f", ti, i * 76)
            flags, value = struct.unpack_from("<ii", ti, i * 76 + 32)
            name = struct.unpack_from("<32s", ti, i * 76 + 40)[0]
            self.texinfo.append((axis, flags, value,
                                 name.split(b"\0")[0].decode("latin1")))
        models = lump(raw, LUMP_MODELS)
        self.models = [struct.unpack_from("<9f3i", models, i * 48)
                       for i in range(len(models) // 48)]
        nodes = lump(raw, LUMP_NODES)
        # dnode_t begins with an INT planenum, not a short: read as a short,
        # both children come from the wrong offsets and the tree walk goes
        # nowhere - which reported every brush in the map as an orphan.
        self.nodes = [struct.unpack_from("<i2i6h2H", nodes, i * 28)
                      for i in range(len(nodes) // 28)]
        leafs = lump(raw, LUMP_LEAFS)
        self.leafs = [struct.unpack_from("<ihh6hHHHH", leafs, i * 28)
                      for i in range(len(leafs) // 28)]
        lb = lump(raw, LUMP_LEAFBRUSHES)
        self.leafbrushes = [struct.unpack_from("<H", lb, i * 2)[0]
                            for i in range(len(lb) // 2)]
        self.entities = lump(raw, LUMP_ENTITIES).split(b"\0")[0].decode("latin1")


def owners(bsp: Bsp) -> tuple[list[int], int]:
    """Which model's collision tree reaches each brush - never proximity."""
    owner = [0] * len(bsp.brushes)
    claimed = [False] * len(bsp.brushes)
    for m, model in enumerate(bsp.models):
        stack = [model[9]]                     # headnode
        seen = set()
        while stack:
            at = stack.pop()
            if at < 0:
                leaf = -1 - at
                if leaf >= len(bsp.leafs):
                    continue
                # dleaf_t is contents, cluster, area, mins[3], maxs[3],
                # firstleafface, numleaffaces, firstleafbrush, numleafbrushes:
                # the BRUSH range is the last pair, not the first. Reading the
                # face range instead put every brush in model 0 and quietly
                # agreed with nothing.
                first, count = bsp.leafs[leaf][11], bsp.leafs[leaf][12]
                for i in range(count):
                    b = bsp.leafbrushes[first + i]
                    if b < len(bsp.brushes):
                        owner[b], claimed[b] = m, True
                continue
            if at in seen or at >= len(bsp.nodes):
                continue
            seen.add(at)
            stack.append(bsp.nodes[at][1])
            stack.append(bsp.nodes[at][2])
    return owner, sum(1 for c in claimed if not c)


def base_winding(normal, dist):
    minor = min(range(3), key=lambda i: abs(normal[i]))
    t = [0.0, 0.0, 0.0]
    t[minor] = 1.0
    d = sum(t[i] * normal[i] for i in range(3))
    u = [t[i] - normal[i] * d for i in range(3)]
    ulen = sum(c * c for c in u) ** 0.5
    u = [c / ulen for c in u]
    v = [normal[1] * u[2] - normal[2] * u[1],
         normal[2] * u[0] - normal[0] * u[2],
         normal[0] * u[1] - normal[1] * u[0]]
    c = [normal[i] * dist for i in range(3)]
    su, sv = (-1, 1, 1, -1), (-1, -1, 1, 1)
    return [[c[i] + u[i] * su[k] * WORLD_EXTENT + v[i] * sv[k] * WORLD_EXTENT
             for i in range(3)] for k in range(4)]


def clip(points, normal, dist):
    if not points:
        return points
    dists = [sum(p[i] * normal[i] for i in range(3)) - dist for p in points]
    sides = [0 if d > WINDING_EPSILON else (1 if d < -WINDING_EPSILON else 2)
             for d in dists]
    if 0 not in sides:
        return points
    if 1 not in sides:
        return []
    out = []
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        if sides[i] != 0:
            out.append(points[i])
        if sides[i] == 2 or sides[j] == 2 or sides[i] == sides[j]:
            continue
        f = dists[i] / (dists[i] - dists[j])
        mid = []
        for a in range(3):
            if normal[a] == 1.0:
                mid.append(dist)
            elif normal[a] == -1.0:
                mid.append(-dist)
            else:
                mid.append(points[i][a] + f * (points[j][a] - points[i][a]))
        out.append(mid)
    return out


def canonical_text(bsp: Bsp) -> str:
    owner, orphan = owners(bsp)
    lines = ["geometry 1"]
    body = []
    num_sides = 0

    for b, (first, count, contents) in enumerate(bsp.brushes):
        rows = []
        for s in range(first, first + count):
            planenum, ti = bsp.sides[s]
            nx, ny, nz, d, _ = bsp.planes[planenum]
            normal = (nx, ny, nz)
            w = base_winding(normal, d)
            for o in range(first, first + count):
                if o == s or bsp.sides[o][0] == planenum:
                    continue
                on = bsp.planes[bsp.sides[o][0]]
                w = clip(w, (on[0], on[1], on[2]), on[3])
                if not w:
                    break
            bevel = len(w) < 3
            if 0 <= ti < len(bsp.texinfo):
                axis, flags, value, name = bsp.texinfo[ti]
            else:
                axis = (1.0, 0, 0, 0, 0, 0, -1.0, 0)
                flags, value, name = 0, 0, ""
            rows.append((normal, d, flags, value, bevel, axis, name))
        num_sides += count

        body.append(f"B {contents} {owner[b]} {count}")
        for normal, d, flags, value, bevel, axis, name in rows:
            parts = [f"S"]
            parts += [str(q(normal[a])) for a in range(3)]
            parts.append(str(q(d)))
            parts += [str(flags), str(value), "1" if bevel else "0"]
            parts += [str(q(axis[i])) for i in range(8)]
            parts.append(name)
            body.append(" ".join(parts))

    lines.append(f"b={len(bsp.brushes)} s={num_sides} m={len(bsp.models)}"
                 f" e={len(entities(bsp))} orphan={orphan}")

    # The entity rows, in the order they appear, key/values verbatim.
    for pairs in entities(bsp):
        model = 0
        for key, value in pairs:
            if key == "model" and value.startswith("*"):
                model = int(value[1:] or 0)
        body.append(f"E {model} {len(pairs)}")
        for key, value in pairs:
            body.append(f"K {key}={value}")

    return "\n".join(lines + body) + "\n"


def entities(bsp: "Bsp"):
    """Every entity block as an ordered list of key/value pairs."""
    out, cursor = [], 0
    text = bsp.entities
    while True:
        start = text.find("{", cursor)
        if start < 0:
            break
        end = text.find("}", start)
        if end < 0:
            break
        pairs = []
        at = start + 1
        while at < end:
            k0 = text.find('"', at)
            if k0 < 0 or k0 > end:
                break
            k1 = text.find('"', k0 + 1)
            v0 = text.find('"', k1 + 1)
            v1 = text.find('"', v0 + 1)
            if min(k1, v0, v1) < 0 or v1 > end:
                break
            pairs.append((text[k0 + 1:k1], text[v0 + 1:v1]))
            at = v1 + 1
        out.append(pairs)
        cursor = end + 1
    return out


def q(value: float) -> int:
    scaled = value * CANON_SCALE
    return int(scaled + 0.5) if scaled >= 0 else int(scaled - 0.5)


def count_entities(bsp: Bsp) -> int:
    return bsp.entities.count("{")


def fnv1a(text: str) -> int:
    h = 14695981039346656037
    for ch in text.encode("latin1"):
        h ^= ch
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bsp")
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args(argv)

    bsp = Bsp(Path(args.bsp))
    text = canonical_text(bsp)
    if args.text:
        sys.stdout.write(text)
    else:
        print(f"{Path(args.bsp).name}: {len(bsp.brushes)} brushes,"
              f" {len(bsp.models)} models, digest {fnv1a(text):016x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
