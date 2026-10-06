#!/usr/bin/env python3
"""Independent build of the candidate traversal graph.

The same relationship to `src/mapgen/mapgen_space.c` that
`mapgen_trace_oracle.py` has to the tracer: written from the description of
what the graph IS - drop through every column, then join neighbours by
stepping up, moving across and dropping down - rather than from the C, so that
agreement is evidence and not a shared assumption.

It runs on the float32 tracer, because the C does, and it renders the same
canonical text. Two implementations producing the same digest for a real map
is the only check available here: there is no third party who knows what
`aerowalk.bsp`'s walkable space should look like.

Slow by construction. The guard uses it on the smallest maps only.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_trace_oracle as tracer  # noqa: E402

f32 = tracer.f32

STEPSIZE = 18
HULL_WIDTH = 16
HULL_BOTTOM = -24
HULL_TOP = 32
DUCK_TOP = 4
JUMP_RISE = 45
MAX_FALL = 1024
GROUND_NORMAL_Z_MILLI = 700
MAX_FLOORS_PER_COLUMN = 64

MASK_PLAYERSOLID = tracer.MASK_PLAYERSOLID
LIQUID_MASK = 0x8 | 0x10 | 0x20
HAZARD_MASK = 0x8 | 0x10

NODE_LIQUID = 0x0001
NODE_HAZARD = 0x0002
NODE_DUCKED = 0x0004

WALK, STEP, JUMP, FALL, SWIM = range(5)
KIND_NAMES = ("walk", "step", "jump", "fall", "swim")

NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class Node:
    cell: tuple[int, int, int]
    origin: tuple[float, float, float]
    contents: int
    clearance: int
    flags: int
    region: int = 0xFFFFFFFF


@dataclass
class Edge:
    frm: int
    to: int
    rise: int
    kind: int


@dataclass
class Region:
    nodes: int = 0
    mins: list[int] = field(default_factory=lambda: [2**31 - 1] * 3)
    maxs: list[int] = field(default_factory=lambda: [-(2**31)] * 3)
    liquid_nodes: int = 0
    hazard_nodes: int = 0
    thin_nodes: int = 0


class Space:
    def __init__(self, cell: int, base: tuple[int, int, int], span: tuple[int, int]):
        self.cell = cell
        self.base = base
        self.span = span
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.regions: list[Region] = []
        self.kind_counts = [0] * 5


def _round_unit(v: float) -> int:
    """C's `(int32_t)(v < 0 ? v - 0.5f : v + 0.5f)`: round away from zero, then
    truncate. Python's round() is not this - it rounds half to even."""
    return int(f32(v - 0.5) if v < 0 else f32(v + 0.5))


def world_bounds(bsp: oracle.Bsp):
    """The tree's root bounds, tightened by the model's box but never widened.

    Three shipped maps carry a world model of +-99999, which is a sentinel and
    not a size.
    """
    model = bsp.models[0]
    if model.headnode < 0:
        leaf = bsp.leafs[-1 - model.headnode]
        lo = list(leaf.mins)
        hi = list(leaf.maxs)
    else:
        node = bsp.nodes[model.headnode]
        lo = list(node.mins)
        hi = list(node.maxs)
    for i in range(3):
        if lo[i] < model.mins[i] < hi[i]:
            lo[i] = int(model.mins[i])
        if lo[i] < model.maxs[i] < hi[i]:
            hi[i] = int(model.maxs[i])
        if hi[i] <= lo[i]:
            return None
    return lo, hi


class _Builder:
    def __init__(self, bsp: oracle.Bsp, cell: int, include_liquids: bool):
        self.bsp = bsp
        self.mins = (-float(HULL_WIDTH), -float(HULL_WIDTH), float(HULL_BOTTOM))
        self.maxs = (float(HULL_WIDTH), float(HULL_WIDTH), float(HULL_TOP))
        self.duck_maxs = (self.maxs[0], self.maxs[1], float(DUCK_TOP))
        self.include_liquids = include_liquids
        self.cell = cell

    def trace(self, start, end, maxs=None):
        return tracer.box_trace(self.bsp, start, end, self.mins,
                                maxs if maxs is not None else self.maxs,
                                MASK_PLAYERSOLID, tracer.f32)

    @staticmethod
    def is_ground(tr) -> bool:
        if tr.plane_normal is None:
            return False
        return int(f32(tr.plane_normal[2] * 1000.0)) >= GROUND_NORMAL_Z_MILLI

    def hull_fits(self, origin, maxs) -> bool:
        tr = self.trace(origin, origin, maxs)
        return not tr.allsolid and not tr.startsolid

    def clearance_above(self, origin) -> int:
        up = (origin[0], origin[1], f32(origin[2] + 512.0))
        tr = self.trace(origin, up)
        d = f32(tr.endpos[2] - origin[2])
        d = min(512.0, max(0.0, d))
        return int(d)


def build(bsp: oracle.Bsp, cell: int = 32, include_liquids: bool = True):
    if not bsp.models:
        return None
    bounds = world_bounds(bsp)
    if bounds is None:
        return None
    lo, hi = bounds

    base = []
    for i in range(3):
        v = lo[i]
        base.append((v // cell if v >= 0 else -((-v + cell - 1) // cell)) * cell)
    span = []
    for i in range(2):
        width = hi[i] - base[i]
        if width <= 0:
            return None
        span.append((width + cell - 1) // cell)

    sp = Space(cell, tuple(base), tuple(span))
    b = _Builder(bsp, cell, include_liquids)

    top = f32(float(hi[2]) - 1.0)
    bottom = f32(float(lo[2]) + 1.0)
    half = f32(cell * 0.5)

    col_first = [0] * (span[0] * span[1] + 1)

    for ix in range(span[0]):
        for iy in range(span[1]):
            col = ix * span[1] + iy
            col_first[col] = len(sp.nodes)
            x = f32(float(base[0] + ix * cell) + half)
            y = f32(float(base[1] + iy * cell) + half)
            _scan_column(b, sp, ix, iy, x, y, top, bottom)
            # Generated top down; the canonical order is bottom up.
            sp.nodes[col_first[col]:] = list(reversed(sp.nodes[col_first[col]:]))
    col_first[span[0] * span[1]] = len(sp.nodes)

    for i in range(len(sp.nodes)):
        _link(b, sp, col_first, i)

    for e in sp.edges:
        sp.kind_counts[e.kind] += 1

    _regions(sp)
    return sp


def _scan_column(b: _Builder, sp: Space, ix: int, iy: int,
                 x: float, y: float, top: float, bottom: float) -> None:
    z = top
    floors = 0
    while z > bottom and floors < MAX_FLOORS_PER_COLUMN:
        tr = b.trace((x, y, z), (x, y, bottom))
        if tr.startsolid:
            z = f32(z - sp.cell)
            continue
        if tr.fraction >= 1.0:
            break

        stance = tuple(tr.endpos)
        ground = b.is_ground(tr)
        ducked = False
        if ground and not b.hull_fits(stance, b.maxs):
            ducked = b.hull_fits(stance, b.duck_maxs)
            ground = ducked

        if ground:
            contents = point_contents(b.bsp, stance)
            liquid = bool(contents & LIQUID_MASK)
            if not liquid or b.include_liquids:
                flags = 0
                if liquid:
                    flags |= NODE_LIQUID
                if contents & HAZARD_MASK:
                    flags |= NODE_HAZARD
                if ducked:
                    flags |= NODE_DUCKED
                cz = int(f32(f32(stance[2] - sp.base[2]) / float(sp.cell)))
                sp.nodes.append(Node((ix, iy, cz), stance, contents,
                                     b.clearance_above(stance), flags))

        z = f32(stance[2] - sp.cell)
        floors += 1


def point_contents(bsp: oracle.Bsp, point) -> int:
    """Delegated on purpose.

    The point query is not this module's claim to make: it has its own
    implementation and its own cross-check in the document layer, including
    the on-plane tie-break that `BSP_PointLeaf` decides. Writing a third one
    here would only give a third chance to get it wrong.
    """
    return bsp.point_contents(point)


def _motion_is_clear(b: _Builder, frm: Node, to: Node, lift: float) -> bool:
    a = frm.origin
    raised = (a[0], a[1], f32(a[2] + lift))
    if b.trace(a, raised).fraction < 1.0:
        return False

    across = (to.origin[0], to.origin[1], raised[2])
    if b.trace(raised, across).fraction < 1.0:
        return False

    below = (across[0], across[1], f32(to.origin[2] - 1.0))
    tr = b.trace(across, below)
    if tr.fraction >= 1.0 or not b.is_ground(tr):
        return False
    landed = f32(tr.endpos[2] - to.origin[2])
    return -1.0 < landed < 1.0


def _classify(frm: Node, to: Node, rise: int) -> int:
    if (frm.flags & NODE_LIQUID) and (to.flags & NODE_LIQUID):
        return SWIM
    if rise > STEPSIZE:
        return JUMP
    if rise < -STEPSIZE:
        return FALL
    if rise != 0:
        return STEP
    return WALK


def _link(b: _Builder, sp: Space, col_first, index: int) -> None:
    frm = sp.nodes[index]
    for dx, dy in NEIGHBOURS:
        nx, ny = frm.cell[0] + dx, frm.cell[1] + dy
        if nx < 0 or ny < 0 or nx >= sp.span[0] or ny >= sp.span[1]:
            continue
        col = nx * sp.span[1] + ny
        for j in range(col_first[col], col_first[col + 1]):
            to = sp.nodes[j]
            rise = _round_unit(f32(to.origin[2] - frm.origin[2]))
            if rise > JUMP_RISE or rise < -MAX_FALL:
                continue
            lift = f32(float(rise) + 1.0) if rise > STEPSIZE else float(STEPSIZE)
            if not _motion_is_clear(b, frm, to, lift):
                continue
            sp.edges.append(Edge(index, j, rise, _classify(frm, to, rise)))


def _regions(sp: Space) -> None:
    if not sp.nodes:
        return
    parent = list(range(len(sp.nodes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    degree = [0] * len(sp.nodes)
    for e in sp.edges:
        if e.kind not in (WALK, STEP, SWIM):
            continue
        a, b_ = find(e.frm), find(e.to)
        if a != b_:
            parent[max(a, b_)] = min(a, b_)
        degree[e.frm] += 1

    label: dict[int, int] = {}
    for i in range(len(sp.nodes)):
        root = find(i)
        if root not in label:
            label[root] = len(label)
        sp.nodes[i].region = label[root]

    sp.regions = [Region() for _ in range(len(label))]
    for i, nd in enumerate(sp.nodes):
        rg = sp.regions[nd.region]
        rg.nodes += 1
        for k in range(3):
            v = _round_unit(nd.origin[k])
            rg.mins[k] = min(rg.mins[k], v)
            rg.maxs[k] = max(rg.maxs[k], v)
        if nd.flags & NODE_LIQUID:
            rg.liquid_nodes += 1
        if nd.flags & NODE_HAZARD:
            rg.hazard_nodes += 1
        if degree[i] <= 2:
            rg.thin_nodes += 1


def canonical_text(sp: Space) -> str:
    out = [f"cell={sp.cell}",
           f"base={sp.base[0]},{sp.base[1]},{sp.base[2]}",
           f"span={sp.span[0]},{sp.span[1]}",
           f"nodes={len(sp.nodes)}"]
    for n in sp.nodes:
        out.append("n=%d,%d,%d,%d,%d,%d,%d" % (
            _round_unit(n.origin[0]), _round_unit(n.origin[1]),
            _round_unit(n.origin[2]), n.contents, n.clearance, n.flags, n.region))
    out.append(f"edges={len(sp.edges)}")
    for e in sp.edges:
        out.append("e=%d,%d,%d,%s" % (e.frm, e.to, e.rise, KIND_NAMES[e.kind]))
    out.append(f"regions={len(sp.regions)}")
    for r in sp.regions:
        out.append("r=%d,%d,%d,%d,%d,%d,%d,%d,%d,%d" % (
            r.nodes, r.mins[0], r.mins[1], r.mins[2],
            r.maxs[0], r.maxs[1], r.maxs[2],
            r.liquid_nodes, r.hazard_nodes, r.thin_nodes))
    for k, name in enumerate(KIND_NAMES):
        out.append(f"kind={name},{sp.kind_counts[k]}")
    return "\n".join(out) + "\n"


def canonical_digest(sp: Space) -> int:
    h = 1469598103934665603
    for byte in canonical_text(sp).encode("ascii"):
        h ^= byte
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h
