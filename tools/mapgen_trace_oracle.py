#!/usr/bin/env python3
"""Independent box/hull trace, for cross-checking src/mapgen/mapgen_trace.c.

Written from the Quake II algorithm rather than from the C in this repository,
for the same reason the BSP oracle was: a second reading of a format or an
algorithm is evidence only when it is arrived at separately. If both agree on
tens of thousands of rays across the shipped maps, both are very likely right;
if they disagree on one, that is a finding about one of them.

--- Why it is parameterised by precision -----------------------------------

This algorithm subtracts two nearly equal large numbers. On `kaktus.bsp` there
is a real ray where the distance from the sweep's start to a brush side comes
out as 3.814697265625e-06 in double and as exactly 0.0 in float32 - the
cancellation eats every significant bit. That one bit decides `startsolid`,
which then prunes the rest of the traversal, so the two answers end up nowhere
near each other. The engine, and therefore the C module, works in float.

So the reference runs at BOTH precisions. That turns one fuzzy comparison into
two sharp ones:

  * against the float32 reference the C must agree EXACTLY - same algorithm,
    same arithmetic, so nothing at all may differ;
  * against the double reference it may differ only on rays where the float32
    and the double reference ALSO differ, which is precisely the definition of
    a ray whose answer is decided by precision rather than by geometry.

No tolerance is chosen by hand anywhere, and a future disagreement cannot be
waved through as rounding unless the references themselves say it is.

It is a reference, not a worker: clarity over speed, and no attempt to be
usable at Training scale.
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_bsp_oracle as oracle  # noqa: E402

DIST_EPSILON = 0.03125

_PACK = struct.Struct("<f").pack
_UNPACK = struct.Struct("<f").unpack


def f64(x: float) -> float:
    """Full precision - what Python does anyway."""
    return x


def f32(x: float) -> float:
    """Round to the precision the engine and the C module actually use."""
    return _UNPACK(_PACK(x))[0]


Round = Callable[[float], float]


@dataclass
class TraceResult:
    allsolid: bool = False
    startsolid: bool = False
    fraction: float = 1.0
    endpos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    contents: int = 0
    surface_flags: int = 0
    plane_normal: tuple[float, float, float] | None = None

    def key(self) -> tuple:
        """Exactly what the C driver prints, so the two answers compare as one
        value rather than field by field with a different rule for each."""
        return (self.fraction, int(self.allsolid), int(self.startsolid),
                self.contents, self.surface_flags, tuple(self.endpos))


@dataclass
class _Sweep:
    bsp: oracle.Bsp
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    mins: tuple[float, float, float]
    maxs: tuple[float, float, float]
    extents: tuple[float, float, float]
    ispoint: bool
    brushmask: int
    trace: TraceResult
    r: Round
    seen: set[int] = field(default_factory=set)


def _dot(a, b, r: Round) -> float:
    """Left to right, rounding after every operation, because that is how the
    C expression `a[0]*b[0] + a[1]*b[1] + a[2]*b[2]` evaluates."""
    return r(r(r(a[0] * b[0]) + r(a[1] * b[1])) + r(a[2] * b[2]))


def _clip_box_to_brush(s: _Sweep, brush) -> None:
    if not brush.numsides:
        return
    r = s.r

    enterfrac = -1.0
    leavefrac = 1.0
    clipplane = None
    getout = False
    startout = False
    leadside = None

    for i in range(brush.numsides):
        side = s.bsp.brushsides[brush.firstside + i]
        plane = s.bsp.planes[side.planenum]

        if not s.ispoint:
            # The plane is pushed out to account for the box: the corner that
            # leads into the plane is the one that decides.
            ofs = tuple(
                s.maxs[j] if plane.normal[j] < 0 else s.mins[j] for j in range(3)
            )
            dist = r(plane.dist - _dot(ofs, plane.normal, r))
        else:
            dist = plane.dist

        d1 = r(_dot(s.start, plane.normal, r) - dist)
        d2 = r(_dot(s.end, plane.normal, r) - dist)

        if d2 > 0:
            getout = True       # the endpoint is outside this brush
        if d1 > 0:
            startout = True

        # Wholly in front of this face: the sweep misses the brush entirely.
        if d1 > 0 and d2 >= d1:
            return
        # Wholly behind it: this face cannot be the one we enter through.
        if d1 <= 0 and d2 <= 0:
            continue

        if d1 > d2:
            f = r(r(d1 - DIST_EPSILON) / r(d1 - d2))
            if f > enterfrac:
                enterfrac = f
                clipplane = plane
                leadside = side
        else:
            f = r(r(d1 + DIST_EPSILON) / r(d1 - d2))
            if f < leavefrac:
                leavefrac = f

    if not startout:
        # The sweep began inside this brush.
        s.trace.startsolid = True
        if not getout:
            s.trace.allsolid = True
        s.trace.contents |= brush.contents
        return

    if -1.0 < enterfrac < leavefrac and enterfrac < s.trace.fraction:
        if enterfrac < 0:
            enterfrac = 0.0
        s.trace.fraction = enterfrac
        if clipplane is not None:
            s.trace.plane_normal = clipplane.normal
        s.trace.contents = brush.contents
        if leadside is not None and leadside.texinfo >= 0:
            s.trace.surface_flags = s.bsp.texinfo[leadside.texinfo].flags


def _test_box_in_brush(s: _Sweep, brush) -> None:
    if not brush.numsides:
        return
    r = s.r
    for i in range(brush.numsides):
        side = s.bsp.brushsides[brush.firstside + i]
        plane = s.bsp.planes[side.planenum]
        ofs = tuple(s.maxs[j] if plane.normal[j] < 0 else s.mins[j] for j in range(3))
        dist = r(plane.dist - _dot(ofs, plane.normal, r))
        if r(_dot(s.start, plane.normal, r) - dist) > 0:
            return              # outside one face, so outside the brush
    s.trace.startsolid = True
    s.trace.allsolid = True
    s.trace.fraction = 0.0
    s.trace.contents = brush.contents


def _trace_to_leaf(s: _Sweep, leafnum: int, position_test: bool) -> None:
    leaf = s.bsp.leafs[leafnum]
    if not (leaf.contents & s.brushmask):
        return
    for i in range(leaf.numleafbrushes):
        brushnum = s.bsp.leafbrushes[leaf.firstleafbrush + i]
        if brushnum in s.seen:
            continue
        s.seen.add(brushnum)
        brush = s.bsp.brushes[brushnum]
        if not (brush.contents & s.brushmask):
            continue
        if position_test:
            _test_box_in_brush(s, brush)
        else:
            _clip_box_to_brush(s, brush)
        if s.trace.fraction <= 0.0:
            return


def _recursive_hull_check(s: _Sweep, num: int, p1f: float, p2f: float,
                          p1, p2, depth: int = 0) -> None:
    if s.trace.fraction <= p1f or depth > 1024:
        return
    if num < 0:
        _trace_to_leaf(s, -1 - num, False)
        return

    r = s.r
    node = s.bsp.nodes[num]
    plane = s.bsp.planes[node.planenum]

    if plane.type < 3:
        t1 = r(p1[plane.type] - plane.dist)
        t2 = r(p2[plane.type] - plane.dist)
        offset = s.extents[plane.type]
    else:
        t1 = r(_dot(plane.normal, p1, r) - plane.dist)
        t2 = r(_dot(plane.normal, p2, r) - plane.dist)
        if s.ispoint:
            offset = 0.0
        else:
            offset = r(r(r(abs(r(s.extents[0] * plane.normal[0])))
                         + r(abs(r(s.extents[1] * plane.normal[1]))))
                       + r(abs(r(s.extents[2] * plane.normal[2]))))

    if t1 >= offset and t2 >= offset:
        _recursive_hull_check(s, node.children[0], p1f, p2f, p1, p2, depth + 1)
        return
    if t1 < -offset and t2 < -offset:
        _recursive_hull_check(s, node.children[1], p1f, p2f, p1, p2, depth + 1)
        return

    # The sweep straddles the plane, so it has to be split.
    if t1 < t2:
        idist = r(1.0 / r(t1 - t2))
        side = 1
        frac2 = r(r(r(t1 + offset) + DIST_EPSILON) * idist)
        frac = r(r(r(t1 - offset) + DIST_EPSILON) * idist)
    elif t1 > t2:
        idist = r(1.0 / r(t1 - t2))
        side = 0
        frac2 = r(r(r(t1 - offset) - DIST_EPSILON) * idist)
        frac = r(r(r(t1 + offset) + DIST_EPSILON) * idist)
    else:
        side = 0
        frac = 1.0
        frac2 = 0.0

    frac = min(1.0, max(0.0, frac))
    midf = r(p1f + r(r(p2f - p1f) * frac))
    mid = tuple(r(p1[i] + r(frac * r(p2[i] - p1[i]))) for i in range(3))
    _recursive_hull_check(s, node.children[side], p1f, midf, p1, mid, depth + 1)

    frac2 = min(1.0, max(0.0, frac2))
    midf = r(p1f + r(r(p2f - p1f) * frac2))
    mid = tuple(r(p1[i] + r(frac2 * r(p2[i] - p1[i]))) for i in range(3))
    _recursive_hull_check(s, node.children[side ^ 1], midf, p2f, mid, p2, depth + 1)


def _box_leafs(s: _Sweep, num: int, mins, maxs, depth: int = 0) -> None:
    if depth > 1024:
        return
    if num < 0:
        _trace_to_leaf(s, -1 - num, True)
        return
    r = s.r
    node = s.bsp.nodes[num]
    plane = s.bsp.planes[node.planenum]

    if plane.type < 3:
        dmin = r(mins[plane.type] - plane.dist)
        dmax = r(maxs[plane.type] - plane.dist)
    else:
        corner_min = tuple(maxs[i] if plane.normal[i] < 0 else mins[i] for i in range(3))
        corner_max = tuple(mins[i] if plane.normal[i] < 0 else maxs[i] for i in range(3))
        dmin = r(_dot(corner_min, plane.normal, r) - plane.dist)
        dmax = r(_dot(corner_max, plane.normal, r) - plane.dist)

    if dmin >= 0:
        _box_leafs(s, node.children[0], mins, maxs, depth + 1)
    elif dmax < 0:
        _box_leafs(s, node.children[1], mins, maxs, depth + 1)
    else:
        _box_leafs(s, node.children[0], mins, maxs, depth + 1)
        _box_leafs(s, node.children[1], mins, maxs, depth + 1)


def box_trace(bsp: oracle.Bsp, start, end, mins, maxs, brushmask: int,
              r: Round = f32) -> TraceResult:
    """Sweep a box through the world model. `r` selects the arithmetic: `f32`
    is what the engine and the C module do, `f64` is the more exact answer."""
    trace = TraceResult(endpos=tuple(start))
    if not bsp.models:
        return trace

    ispoint = all(v == 0 for v in mins) and all(v == 0 for v in maxs)
    extents = tuple(max(-mins[i], maxs[i]) for i in range(3))
    s = _Sweep(bsp, tuple(start), tuple(end), tuple(mins), tuple(maxs),
               extents, ispoint, brushmask, trace, r)

    headnode = bsp.models[0].headnode
    if tuple(start) == tuple(end):
        # A zero-length sweep is a containment question, not a sweep.
        bmins = tuple(r(r(start[i] + mins[i]) - 1.0) for i in range(3))
        bmaxs = tuple(r(r(start[i] + maxs[i]) + 1.0) for i in range(3))
        _box_leafs(s, headnode, bmins, bmaxs)
        trace.endpos = tuple(start)
        return trace

    _recursive_hull_check(s, headnode, 0.0, 1.0, tuple(start), tuple(end))

    if trace.fraction == 1.0:
        trace.endpos = tuple(end)
    else:
        trace.endpos = tuple(
            r(start[i] + r(trace.fraction * r(end[i] - start[i]))) for i in range(3)
        )
    return trace


# --- deterministic ray sets ------------------------------------------------
#
# Both implementations must see bit-identical inputs, so the rays are generated
# once, here, on integer coordinates (exactly representable in float32 and in
# double alike) and written to a file the C driver reads back.

PLAYER_MINS = (-16.0, -16.0, -24.0)
PLAYER_MAXS = (16.0, 16.0, 32.0)

HULLS = [
    ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),         # point
    (PLAYER_MINS, PLAYER_MAXS),                  # standing player
    ((-16.0, -16.0, -24.0), (16.0, 16.0, 4.0)),  # crouched player
    ((-4.0, -4.0, -4.0), (4.0, 4.0, 4.0)),       # small entity
]

MASK_PLAYERSOLID = 0x1 | 0x10000 | 0x2 | 0x2000000
MASK_SOLID = 0x1 | 0x2
MASK_WATER = 0x8 | 0x10 | 0x20


def generate_rays(bsp: oracle.Bsp, seed: int, count: int):
    """A reproducible ray set covering the world model's bounds."""
    import random

    rng = random.Random(seed)
    model = bsp.models[0]
    lo = [int(model.mins[i]) for i in range(3)]
    hi = [int(model.maxs[i]) for i in range(3)]
    for i in range(3):
        if hi[i] <= lo[i]:
            hi[i] = lo[i] + 1

    masks = [MASK_PLAYERSOLID, MASK_SOLID, MASK_WATER]
    rays = []
    for i in range(count):
        start = tuple(float(rng.randint(lo[j], hi[j])) for j in range(3))
        if i % 8 == 5:
            # A zero-length sweep takes the containment path instead of the
            # sweep path. Without these the position test is dead code that no
            # amount of random ray casting would ever reach.
            end = start
        elif i % 4 == 3:
            # Short sweeps stress the near-plane epsilon, which is where two
            # implementations of this algorithm disagree if they ever do.
            end = tuple(start[j] + float(rng.randint(-64, 64)) for j in range(3))
        else:
            end = tuple(float(rng.randint(lo[j], hi[j])) for j in range(3))
        mins, maxs = HULLS[i % len(HULLS)]
        rays.append((start, end, mins, maxs, masks[i % len(masks)]))
    return rays


def _brush_bounds(bsp: oracle.Bsp, brush):
    """The axis-aligned box of a brush, read off its own axial sides.

    Brushes do not store bounds; six axial planes are how a box brush states
    them, and a brush without all six simply is not a box and is skipped.
    """
    lo = [None, None, None]
    hi = [None, None, None]
    for i in range(brush.numsides):
        plane = bsp.planes[bsp.brushsides[brush.firstside + i].planenum]
        n = plane.normal
        for axis in range(3):
            if n[axis] == 1.0 and n[(axis + 1) % 3] == 0.0 and n[(axis + 2) % 3] == 0.0:
                hi[axis] = plane.dist
            elif n[axis] == -1.0 and n[(axis + 1) % 3] == 0.0 and n[(axis + 2) % 3] == 0.0:
                lo[axis] = -plane.dist
    if any(v is None for v in lo) or any(v is None for v in hi):
        return None
    if any(hi[a] <= lo[a] for a in range(3)):
        return None
    return lo, hi


# Offsets smaller than DIST_EPSILON, so a sweep starting this far in front of
# a face produces a NEGATIVE entry fraction - the case the clamp exists for,
# and one that random rays across a map essentially never reach.
GRAZE_OFFSETS = (1.0 / 64.0, 1.0 / 128.0, 1.0 / 256.0, 0.0)


def generate_grazing_rays(bsp: oracle.Bsp, count: int):
    """Sweeps that begin resting on a brush face, pointing into it.

    This is what a reachability check does all day - stand on the floor, step
    down - and it is the only way the entry-fraction clamp is ever exercised.
    """
    rays = []
    for brushnum, brush in enumerate(bsp.brushes):
        if len(rays) >= count:
            break
        if not (brush.contents & 0x1):
            continue
        bounds = _brush_bounds(bsp, brush)
        if bounds is None:
            continue
        lo, hi = bounds
        if hi[2] - lo[2] < 1.0 or hi[0] - lo[0] < 64.0 or hi[1] - lo[1] < 64.0:
            continue

        mins, maxs = PLAYER_MINS, PLAYER_MAXS
        cx = f32(f32(lo[0] + hi[0]) * 0.5)
        cy = f32(f32(lo[1] + hi[1]) * 0.5)
        # The plane the hull is actually clipped against sits one hull-bottom
        # above the face, because the box is offset before the sweep.
        face = f32(hi[2] - mins[2])
        off = GRAZE_OFFSETS[brushnum % len(GRAZE_OFFSETS)]
        start = (cx, cy, f32(face + off))
        end = (cx, cy, f32(start[2] - 64.0))
        rays.append((start, end, mins, maxs, MASK_PLAYERSOLID))
    return rays


def write_rays(rays, path) -> None:
    """%.9g round-trips a float32 exactly, which %.1f does not - and the
    grazing rays live in the last few bits."""
    lines = []
    for start, end, mins, maxs, mask in rays:
        vals = list(start) + list(end) + list(mins) + list(maxs)
        lines.append(" ".join(f"{v:.9g}" for v in vals) + f" {mask}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")
