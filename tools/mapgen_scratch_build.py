r"""Brief 19: a map from scratch - the column world turned into brushes, entities, a `.map`, and a compiled map.

The skeleton (`mapgen_scratch_plan.py`) says, for every 64-unit cell of the plan, which spans of air it holds: a
hall's from its floor to its ceiling, a door's through a wall, a corridor's with its stairs, a shaft's for a lift.
Everything else inside the map's hull is rock. This module derives the rock from the air - per cell column, the
intervals between the air spans - merges equal columns into larger brushes, gives every face the texture of the space
it faces (a floor's top, a wall's side, a ceiling or the sky above), adds the shaped pieces a box cannot be (steps,
ramps, chamfers), the movers and triggers, the lights and the items, and writes a Quake II `.map` the pinned compiler
takes. `compile_map` runs that compiler's three passes the way `pipeline.exe` does (bsp on one thread, vis, rad with
`-maxdata 8388608`).

Plane points follow the compiler's own rule (qbsp `ParseBrush`): normal = (p0 - p1) x (p2 - p1), pointing out of the
brush; every plane is written from three integer points that lie on it.
"""
from __future__ import annotations

import math

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

CELL = 64

# Quake II contents and surface flags
C_SOLID, C_WINDOW, C_LAVA, C_SLIME, C_WATER = 1, 2, 8, 16, 32
C_PLAYERCLIP = 0x10000
C_DETAIL = 0x8000000
C_MIST = 0x40                 # brief 26: drawn, walked and shot through (q2_q3dm17's portal and pad sheets)
C_TRANSLUCENT = 0x10000000
S_LIGHT, S_SLICK, S_SKY, S_WARP, S_TRANS33, S_TRANS66, S_NODRAW = 1, 2, 4, 8, 16, 32, 128
S_FLOWING = 64                # brief 26: the engine scrolls the texture along its s axis (q2pro: 1.6 widths a second)
NO_WINDOW = 0x08000000


@dataclass
class Face:
    p0: tuple
    p1: tuple
    p2: tuple
    tex: str
    contents: int = 0
    flags: int = 0
    value: int = 0
    scale: float = 1.0
    shift: tuple = (0, 0)          # brief 26: the texture's offset (s, t) and rotation, as the map format gives them
    rot: float = 0


@dataclass
class Brush:
    faces: list = field(default_factory=list)
    note: str = ""


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def oriented(p0, p1, p2, outward) -> tuple:
    """Three points on a plane, ordered so the compiler's normal (p0-p1) x (p2-p1) points along `outward`."""
    n = _cross(_sub(p0, p1), _sub(p2, p1))
    if _dot(n, outward) < 0:
        return p2, p1, p0
    return p0, p1, p2


def face(points, outward, tex, contents=0, flags=0, value=0, scale=1.0, shift=(0, 0), rot=0) -> Face:
    a, b, c = oriented(points[0], points[1], points[2], outward)
    return Face(a, b, c, tex, contents, flags, value, scale, tuple(shift), rot)


@dataclass
class Surf:
    """What one side of a brush shows: a texture and, for sky, light and liquids, its flags."""
    tex: str
    flags: int = 0
    value: int = 0
    scale: float = 1.0
    shift: tuple = (0, 0)
    rot: float = 0


def slab_poly(points, bottom, top, surf_by_side: dict, contents: int = 0, note: str = "", side_surf=None) -> Brush:
    """Brief 26: a prism over a convex polygon (`points` in x, y, any order round it) between two planes, each
    `z(x, y)` - a flat one a constant, a sloped one a pad's wedge top. Its top takes '+z', its bottom '-z', its sides
    'side' (or 'default'), or `side_surf(i, (nx, ny))` per side when given."""
    d = surf_by_side.get("default") or next(iter(surf_by_side.values()))

    def s(k):
        return surf_by_side.get(k, d)

    zb = bottom if callable(bottom) else (lambda x, y, z=bottom: z)
    zt = top if callable(top) else (lambda x, y, z=top: z)
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    r3 = lambda v: round(v, 3)  # noqa: E731
    b = Brush(note=note)
    st, sb = s("+z"), s("-z")
    p3 = points[:3]
    b.faces.append(face(tuple((r3(p[0]), r3(p[1]), r3(zt(p[0], p[1]))) for p in p3), (0, 0, 1), st.tex, contents,
                        st.flags, st.value, st.scale, st.shift, st.rot))
    b.faces.append(face(tuple((r3(p[0]), r3(p[1]), r3(zb(p[0], p[1]))) for p in p3), (0, 0, -1), sb.tex, contents,
                        sb.flags, sb.value, sb.scale, sb.shift, sb.rot))
    lo = min(zb(p[0], p[1]) for p in points)
    hi = max(zt(p[0], p[1]) for p in points)
    for i in range(len(points)):
        a, c = points[i], points[(i + 1) % len(points)]
        if a == c:
            continue
        mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
        nx, ny = c[1] - a[1], -(c[0] - a[0])
        if nx * (mx - cx) + ny * (my - cy) < 0:
            nx, ny = -nx, -ny
        ss = side_surf(i, (nx, ny)) if side_surf else s("side")
        b.faces.append(face(((r3(a[0]), r3(a[1]), r3(lo)), (r3(c[0]), r3(c[1]), r3(lo)), (r3(a[0]), r3(a[1]), r3(hi))),
                            (nx, ny, 0), ss.tex, contents, ss.flags, ss.value, ss.scale, ss.shift, ss.rot))
    return b


def box(lo, hi, surf_by_side: dict, contents: int = 0, note: str = "") -> Brush:
    """An axis box. `surf_by_side` keys: '+x' '-x' '+y' '-y' '+z' '-z' (missing ones take 'default')."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    d = surf_by_side.get("default") or next(iter(surf_by_side.values()))

    def s(k):
        return surf_by_side.get(k, d)

    b = Brush(note=note)
    for key, pts, out in (
        ("+x", ((x1, y0, z0), (x1, y1, z0), (x1, y0, z1)), (1, 0, 0)),
        ("-x", ((x0, y0, z0), (x0, y1, z0), (x0, y0, z1)), (-1, 0, 0)),
        ("+y", ((x0, y1, z0), (x1, y1, z0), (x0, y1, z1)), (0, 1, 0)),
        ("-y", ((x0, y0, z0), (x1, y0, z0), (x0, y0, z1)), (0, -1, 0)),
        ("+z", ((x0, y0, z1), (x1, y0, z1), (x0, y1, z1)), (0, 0, 1)),
        ("-z", ((x0, y0, z0), (x1, y0, z0), (x0, y1, z0)), (0, 0, -1)),
    ):
        sf = s(key)
        b.faces.append(face(pts, out, sf.tex, contents, sf.flags, sf.value, sf.scale))
    return b


def wedge(lo, hi, axis: str, z_at_lo: int, z_at_hi: int, surf_by_side: dict, contents: int = 0,
          note: str = "") -> Brush:
    """A box whose top is a slope rising along `axis` ('x' or 'y') from `z_at_lo` (at lo) to `z_at_hi` (at hi).
    lo[2] is the bottom; both tops must stand above it."""
    x0, y0, z0 = lo
    x1, y1, _ = hi
    d = surf_by_side.get("default") or next(iter(surf_by_side.values()))

    def s(k):
        return surf_by_side.get(k, d)

    b = Brush(note=note)
    zt = max(z_at_lo, z_at_hi)
    # four vertical sides and the bottom, clipped by the slope above (the planes reach past it; the slope cuts them)
    for key, pts, out in (
        ("+x", ((x1, y0, z0), (x1, y1, z0), (x1, y0, zt)), (1, 0, 0)),
        ("-x", ((x0, y0, z0), (x0, y1, z0), (x0, y0, zt)), (-1, 0, 0)),
        ("+y", ((x0, y1, z0), (x1, y1, z0), (x0, y1, zt)), (0, 1, 0)),
        ("-y", ((x0, y0, z0), (x1, y0, z0), (x0, y0, zt)), (0, -1, 0)),
        ("-z", ((x0, y0, z0), (x1, y0, z0), (x0, y1, z0)), (0, 0, -1)),
    ):
        sf = s(key)
        b.faces.append(face(pts, out, sf.tex, contents, sf.flags, sf.value, sf.scale))
    sf = s("+z")
    if axis == "x":
        pts = ((x0, y0, z_at_lo), (x1, y0, z_at_hi), (x0, y1, z_at_lo))
    else:
        pts = ((x0, y0, z_at_lo), (x0, y1, z_at_hi), (x1, y0, z_at_lo))
    b.faces.append(face(pts, (0, 0, 1), sf.tex, contents, sf.flags, sf.value, sf.scale))
    return b


def prism_poly(points, z0: int, z1: int, surf_by_side: dict, contents: int = 0, note: str = "") -> Brush:
    """A vertical prism over a convex polygon (`points` in x, y; any order round it), from z0 to z1: its sides take
    'side' (or 'default'), its top '+z', its bottom '-z'. 3.46: the round shapes of a map from scratch - a corner's
    arc in fans of triangles, a podium's octagon."""
    d = surf_by_side.get("default") or next(iter(surf_by_side.values()))

    def s(k):
        return surf_by_side.get(k, d)

    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    b = Brush(note=note)
    st, sb, ss = s("+z"), s("-z"), s("side")
    b.faces.append(face(((points[0][0], points[0][1], z1), (points[1][0], points[1][1], z1), (points[2][0], points[2][1], z1)),
                        (0, 0, 1), st.tex, contents, st.flags, st.value, st.scale))
    b.faces.append(face(((points[0][0], points[0][1], z0), (points[1][0], points[1][1], z0), (points[2][0], points[2][1], z0)),
                        (0, 0, -1), sb.tex, contents, sb.flags, sb.value, sb.scale))
    for i in range(len(points)):
        a, c = points[i], points[(i + 1) % len(points)]
        if a == c:
            continue
        mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
        nx, ny = c[1] - a[1], -(c[0] - a[0])
        if nx * (mx - cx) + ny * (my - cy) < 0:
            nx, ny = -nx, -ny
        b.faces.append(face(((a[0], a[1], z0), (c[0], c[1], z0), (a[0], a[1], z1)), (nx, ny, 0), ss.tex, contents,
                            ss.flags, ss.value, ss.scale))
    return b


def prism_tri(lo, hi, solid_corner: str, surf_by_side: dict, note: str = "") -> Brush:
    """A cell's solid corner triangle (a chamfer): the half of the box on the side of `solid_corner`
    ('ne', 'nw', 'se', 'sw') cut by the diagonal that does not pass through it."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    d = surf_by_side.get("default") or next(iter(surf_by_side.values()))

    def s(k):
        return surf_by_side.get(k, d)

    b = Brush(note=note)
    sf_top, sf_bot = s("+z"), s("-z")
    b.faces.append(face(((x0, y0, z1), (x1, y0, z1), (x0, y1, z1)), (0, 0, 1), sf_top.tex, 0, sf_top.flags,
                        sf_top.value, sf_top.scale))
    b.faces.append(face(((x0, y0, z0), (x1, y0, z0), (x0, y1, z0)), (0, 0, -1), sf_bot.tex, 0, sf_bot.flags,
                        sf_bot.value, sf_bot.scale))
    diag = s("diag")
    if solid_corner == "ne":     # solid where x and y are high: the two outer sides +x, +y and the diagonal
        sides = [("+x", ((x1, y0, z0), (x1, y1, z0), (x1, y0, z1)), (1, 0, 0)),
                 ("+y", ((x0, y1, z0), (x1, y1, z0), (x0, y1, z1)), (0, 1, 0))]
        dpts, dout = ((x1, y0, z0), (x0, y1, z0), (x1, y0, z1)), (-1, -1, 0)
    elif solid_corner == "nw":
        sides = [("-x", ((x0, y0, z0), (x0, y1, z0), (x0, y0, z1)), (-1, 0, 0)),
                 ("+y", ((x0, y1, z0), (x1, y1, z0), (x0, y1, z1)), (0, 1, 0))]
        dpts, dout = ((x0, y0, z0), (x1, y1, z0), (x0, y0, z1)), (1, -1, 0)
    elif solid_corner == "se":
        sides = [("+x", ((x1, y0, z0), (x1, y1, z0), (x1, y0, z1)), (1, 0, 0)),
                 ("-y", ((x0, y0, z0), (x1, y0, z0), (x0, y0, z1)), (0, -1, 0))]
        dpts, dout = ((x0, y0, z0), (x1, y1, z0), (x0, y0, z1)), (-1, 1, 0)
    else:  # sw
        sides = [("-x", ((x0, y0, z0), (x0, y1, z0), (x0, y0, z1)), (-1, 0, 0)),
                 ("-y", ((x0, y0, z0), (x1, y0, z0), (x0, y0, z1)), (0, -1, 0))]
        dpts, dout = ((x1, y0, z0), (x0, y1, z0), (x1, y0, z1)), (1, 1, 0)
    for key, pts, out in sides:
        sf = s(key)
        b.faces.append(face(pts, out, sf.tex, 0, sf.flags, sf.value, sf.scale))
    b.faces.append(face(dpts, dout, diag.tex, 0, diag.flags, diag.value, diag.scale))
    return b


@dataclass
class Entity:
    keys: dict
    brushes: list = field(default_factory=list)


def _num(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


WORLD_LIM = 4096 - 16          # the compiler's world (q2tool: «bounds out of range» past 4096), the sky's slabs 16 thick
WORLD_MARGIN = 512             # what stands beyond the footprint: a space's sky box (512 out), a map's outer walls


def world_shift(P) -> tuple:
    """The PO, 06.11 (an 8-player open space, 6 million square units, 16 islands: «эта карта у меня не стала
    генерироваться»): a plan's cells start at 0, so its world ran from 0 to W x 64 - over 4096 on that map, and all ten
    candidates «did not compile: bounds out of range» while the world's other half stood empty. A plan wider than the
    world's positive half is moved towards the middle by whole 1024s (a texture's tile divides 1024: a face not turned
    keeps its look without a word; a turned one gets its shift made good, `move_world`). A plan that fits is not moved."""
    def one(cells: int) -> int:
        span = cells * CELL
        if span + WORLD_MARGIN <= WORLD_LIM:
            return 0
        return -1024 * round(span / 2 / 1024)
    return one(P.W), one(P.H)


_BASE_AXIS = (((0, 0, 1), (1, 0, 0), (0, -1, 0)), ((0, 0, -1), (1, 0, 0), (0, -1, 0)),
              ((1, 0, 0), (0, 1, 0), (0, 0, -1)), ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
              ((0, 1, 0), (1, 0, 0), (0, 0, -1)), ((0, -1, 0), (1, 0, 0), (0, 0, -1)))


def tex_vecs(f) -> tuple:
    """A face's texture axes as Quake II's compiler takes them from the map format (TextureAxisFromPlane, then the
    face's turn, then its scale): s = point . vs + shift_s. The plane's side does not matter - the floor's and the
    ceiling's axes are the same, and so each pair of walls'."""
    n = _cross(_sub(f.p0, f.p1), _sub(f.p2, f.p1))
    best, bi = 0.0, 0
    for i, (nv, _, _) in enumerate(_BASE_AXIS):
        d = n[0] * nv[0] + n[1] * nv[1] + n[2] * nv[2]
        if d > best:
            best, bi = d, i
    xv, yv = list(_BASE_AXIS[bi][1]), list(_BASE_AXIS[bi][2])
    rot = float(getattr(f, "rot", 0) or 0)
    if rot == 0:
        sn, cs = 0.0, 1.0
    elif rot == 90:
        sn, cs = 1.0, 0.0
    elif rot == 180:
        sn, cs = 0.0, -1.0
    elif rot == 270:
        sn, cs = -1.0, 0.0
    else:
        a = math.radians(rot)
        sn, cs = math.sin(a), math.cos(a)
    sv = 0 if xv[0] else (1 if xv[1] else 2)
    tv = 0 if yv[0] else (1 if yv[1] else 2)
    for v in (xv, yv):
        ns, nt = cs * v[sv] - sn * v[tv], sn * v[sv] + cs * v[tv]
        v[sv], v[tv] = ns, nt
    sc = float(f.scale or 1.0)
    return [c / sc for c in xv], [c / sc for c in yv]


def move_world(brushes: list, entities: list, shift: tuple) -> None:
    """Every brush and every entity's origin moved by (dx, dy); each face's texture shift made good so the texture
    stands where it stood on the face (a turned face - the pads' arrows - would slide otherwise)."""
    dx, dy = shift
    if not dx and not dy:
        return
    d = (dx, dy, 0)

    def move_brush(b):
        for f in b.faces:
            vs, vt = tex_vecs(f)
            sh = getattr(f, "shift", (0, 0)) or (0, 0)
            f.shift = (round(sh[0] - (d[0] * vs[0] + d[1] * vs[1])), round(sh[1] - (d[0] * vt[0] + d[1] * vt[1])))
            f.p0 = (f.p0[0] + dx, f.p0[1] + dy, f.p0[2])
            f.p1 = (f.p1[0] + dx, f.p1[1] + dy, f.p1[2])
            f.p2 = (f.p2[0] + dx, f.p2[1] + dy, f.p2[2])

    for b in brushes:
        move_brush(b)
    for e in entities:
        for b in e.brushes:
            move_brush(b)
        o = e.keys.get("origin")
        if o:
            x, y, z = (float(v) for v in str(o).split())
            e.keys["origin"] = f"{_num(x + dx)} {_num(y + dy)} {_num(z)}"


def write_map(path: Path, world: dict, world_brushes: list, entities: list) -> None:
    lines = []

    def brush_text(b: Brush, i: int):
        lines.append(f"// brush {i}{(' ' + b.note) if b.note else ''}")
        lines.append("{")
        for f in b.faces:
            pts = " ".join(f"( {_num(p[0])} {_num(p[1])} {_num(p[2])} )" for p in (f.p0, f.p1, f.p2))
            sc = _num(f.scale)
            sh = getattr(f, "shift", (0, 0))
            lines.append(f"{pts} {f.tex} {_num(sh[0])} {_num(sh[1])} {_num(getattr(f, 'rot', 0))} {sc} {sc} "
                         f"{f.contents} {f.flags} {f.value}")
        lines.append("}")

    lines.append("// entity 0")
    lines.append("{")
    for k, v in world.items():
        lines.append(f'"{k}" "{v}"')
    for i, b in enumerate(world_brushes):
        brush_text(b, i)
    lines.append("}")
    for n, e in enumerate(entities, 1):
        lines.append(f"// entity {n}")
        lines.append("{")
        for k, v in e.keys.items():
            lines.append(f'"{k}" "{v}"')
        for i, b in enumerate(e.brushes):
            brush_text(b, i)
        lines.append("}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="latin-1")


def compiler() -> tuple[Path, str]:
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler()


def compile_map(map_path: Path, game: Path, threads: int = 4, rad_flags: str = "", log: Path | None = None,
                stages=("bsp", "vis", "rad")) -> tuple[bool, str]:
    """The three passes `pipeline.exe` runs, on this `.map`; (a .bsp came out with light, the log's tail)."""
    exe, _ = compiler()
    said = []
    flags = {"bsp": ["-bsp"], "vis": ["-vis"], "rad": ["-rad", "-maxdata", "8388608", *rad_flags.split()]}
    for st in stages:
        th = "1" if st == "bsp" else str(threads)
        cmd = [str(exe), *flags[st], "-threads", th, "-moddir", str(game), "-basedir", str(game),
               "-gamedir", str(game), str(map_path)]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           creationflags=NO_WINDOW if os.name == "nt" else 0)
        said.append(f"==== {st} (exit {r.returncode})\n{r.stdout[-6000:]}{r.stderr[-2000:]}")
        if r.returncode != 0:
            break
        if st == "bsp" and "LEAKED" in (r.stdout + r.stderr).upper():
            said.append("LEAKED")
            break
    text = "\n".join(said)
    if log:
        Path(log).write_text(text, encoding="utf-8")
    bsp = Path(map_path).with_suffix(".bsp")
    ok = bsp.is_file() and "LEAKED" not in text
    return ok, text[-3000:]
