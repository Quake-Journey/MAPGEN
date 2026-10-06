"""Synthetic maps that ask the geometry Module one question each.

q2dm1 is a bad first fixture. It is large, it takes minutes to compile, and
when a round trip loses three thousand square units of one rock wall there is
no way to tell which of a dozen mechanisms did it. These are small enough that
a failure has one candidate cause, and they are written rather than found so
that the awkward cases - an oblique plane, a texture axis that is not the
dominant one, two solids meeting exactly along a slanted seam - are present on
purpose instead of by luck.

Each fixture is a complete Valve 220 `.map` sealed by a hollow room, so the
pinned compiler will build it without a leak.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def oriented(points, outward):
    """Order three points so the compiler derives the normal we meant.

    q2tools computes (p0 - p1) x (p2 - p1). Guessing the order is how the first
    version of these fixtures came out inside-out - every plane faced inward,
    every brush enclosed nothing, and the compiler reported six brushes with no
    visible sides. So the intended normal is stated and the order is checked
    against it rather than assumed.
    """
    p0, p1, p2 = points
    t1 = tuple(p0[i] - p1[i] for i in range(3))
    t2 = tuple(p2[i] - p1[i] for i in range(3))
    n = _cross(t1, t2)
    if sum(n[i] * outward[i] for i in range(3)) < 0:
        p0, p2 = p2, p0
    return (p0, p1, p2)


@dataclass
class Side:
    """One plane, given as the three points a `.map` states it with."""
    points: tuple[tuple[float, float, float], ...]
    texture: str = "e1u1/c_met5_1"
    u_axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    v_axis: tuple[float, float, float] = (0.0, -1.0, 0.0)
    u_shift: float = 0.0
    v_shift: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)
    contents: int | None = None
    flags: int | None = None
    value: int | None = None

    def render(self) -> str:
        text = " ".join(f"( {x:g} {y:g} {z:g} )" for x, y, z in self.points)
        text += f" {self.texture}"
        text += (f" [ {self.u_axis[0]:g} {self.u_axis[1]:g} {self.u_axis[2]:g}"
                 f" {self.u_shift:g} ]")
        text += (f" [ {self.v_axis[0]:g} {self.v_axis[1]:g} {self.v_axis[2]:g}"
                 f" {self.v_shift:g} ]")
        text += f" 0 {self.scale[0]:g} {self.scale[1]:g}"
        if self.contents is not None:
            text += f" {self.contents} {self.flags or 0} {self.value or 0}"
        return text


@dataclass
class Brush:
    sides: list[Side] = field(default_factory=list)

    def render(self) -> str:
        return "{\n" + "\n".join(s.render() for s in self.sides) + "\n}\n"


def box(mins, maxs, texture="e1u1/c_met5_1", contents=None) -> Brush:
    """An axis-aligned solid, with each face stated the way a compiler reads
    it: the normal it derives is (p0 - p1) x (p2 - p1)."""
    x0, y0, z0 = mins
    x1, y1, z1 = maxs
    faces = [
        (((x1, y0, z0), (x1, y1, z0), (x1, y1, z1)), (1, 0, 0), (0, 1, 0), (0, 0, -1)),
        (((x0, y1, z0), (x0, y0, z0), (x0, y0, z1)), (-1, 0, 0), (0, 1, 0), (0, 0, -1)),
        (((x1, y1, z0), (x0, y1, z0), (x0, y1, z1)), (0, 1, 0), (1, 0, 0), (0, 0, -1)),
        (((x0, y0, z0), (x1, y0, z0), (x1, y0, z1)), (0, -1, 0), (1, 0, 0), (0, 0, -1)),
        (((x0, y0, z1), (x1, y0, z1), (x1, y1, z1)), (0, 0, 1), (1, 0, 0), (0, -1, 0)),
        (((x1, y0, z0), (x0, y0, z0), (x0, y1, z0)), (0, 0, -1), (1, 0, 0), (0, -1, 0)),
    ]
    return Brush([Side(points=oriented(p, n), texture=texture, u_axis=u,
                       v_axis=v, contents=contents)
                  for p, n, u, v in faces])


def hollow_room(mins, maxs, thickness=32, texture="e1u1/c_met5_1"):
    """Six slabs enclosing the volume, so the compiler has something to seal
    against and a fixture can be about its own subject."""
    x0, y0, z0 = mins
    x1, y1, z1 = maxs
    t = thickness
    return [
        box((x0 - t, y0 - t, z0 - t), (x0, y1 + t, z1 + t), texture),
        box((x1, y0 - t, z0 - t), (x1 + t, y1 + t, z1 + t), texture),
        box((x0, y0 - t, z0 - t), (x1, y0, z1 + t), texture),
        box((x0, y1, z0 - t), (x1, y1 + t, z1 + t), texture),
        box((x0, y0, z0 - t), (x1, y1, z0), texture),
        box((x0, y0, z1), (x1, y1, z1 + t), texture),
    ]


def wedge(mins, maxs, texture="e1u1/c_met5_1") -> Brush:
    """A solid whose top is one slope, high at -X and low at +X.

    The shape a box shell cannot express, and the one every seam defect so far
    has appeared on.
    """
    x0, y0, z0 = mins
    x1, y1, z1 = maxs
    run, rise = x1 - x0, z1 - z0
    faces = [
        (((x0, y1, z0), (x0, y0, z0), (x0, y0, z1)), (-1, 0, 0),
         (0, 1, 0), (0, 0, -1)),
        (((x0, y0, z0), (x1, y0, z0), (x1, y0, z1)), (0, -1, 0),
         (1, 0, 0), (0, 0, -1)),
        (((x1, y1, z0), (x0, y1, z0), (x0, y1, z1)), (0, 1, 0),
         (1, 0, 0), (0, 0, -1)),
        (((x1, y0, z0), (x0, y0, z0), (x0, y1, z0)), (0, 0, -1),
         (1, 0, 0), (0, -1, 0)),
        # the slope, from the low +X edge up to the high -X edge
        (((x1, y0, z0), (x1, y1, z0), (x0, y1, z1)), (rise, 0, run),
         (1, 0, 0), (0, -1, 0)),
    ]
    return Brush([Side(points=oriented(p, n), texture=texture, u_axis=u,
                       v_axis=v)
                  for p, n, u, v in faces])


def oblique_pair(origin=(0, 0, 0), texture="e1u1/c_met5_1") -> list[Brush]:
    """Two solids meeting exactly along one slanted seam.

    The fixture the whole seam question turns on. Both brushes name the SAME
    diagonal plane from opposite sides, so a round trip that reproduces it
    differently for the two of them opens a hairline between them even though
    neither brush has moved - which is what a wall of q2dm1's faceted rock is
    made of, and where the sky comes through.
    """
    ox, oy, oz = origin
    x0, x1 = ox, ox + 256
    y0, y1 = oy, oy + 256
    z0, z1 = oz, oz + 128
    seam = ((x0, y0, z0), (x1, y1, z0), (x1, y1, z1))

    left_faces = [
        (((x0, y0, z0), (x0, y1, z0), (x0, y1, z1)), (-1, 0, 0),
         (0, 1, 0), (0, 0, -1)),
        (((x0, y1, z0), (x1, y1, z0), (x1, y1, z1)), (0, 1, 0),
         (1, 0, 0), (0, 0, -1)),
        (((x1, y0, z0), (x0, y0, z0), (x0, y1, z0)), (0, 0, -1),
         (1, 0, 0), (0, -1, 0)),
        (((x0, y0, z1), (x1, y0, z1), (x1, y1, z1)), (0, 0, 1),
         (1, 0, 0), (0, -1, 0)),
        (seam, (1, -1, 0), (1, 1, 0), (0, 0, -1)),
    ]
    right_faces = [
        (((x1, y1, z0), (x1, y0, z0), (x1, y0, z1)), (1, 0, 0),
         (0, 1, 0), (0, 0, -1)),
        (((x0, y0, z0), (x1, y0, z0), (x1, y0, z1)), (0, -1, 0),
         (1, 0, 0), (0, 0, -1)),
        (((x1, y0, z0), (x0, y0, z0), (x0, y1, z0)), (0, 0, -1),
         (1, 0, 0), (0, -1, 0)),
        (((x0, y0, z1), (x1, y0, z1), (x1, y1, z1)), (0, 0, 1),
         (1, 0, 0), (0, -1, 0)),
        (seam, (-1, 1, 0), (1, 1, 0), (0, 0, -1)),
    ]
    return [Brush([Side(points=oriented(p, n), texture=texture, u_axis=u,
                        v_axis=v) for p, n, u, v in faces])
            for faces in (left_faces, right_faces)]


def write_map(path: Path, brushes, entities=(), message="fixture") -> None:
    lines = ["// Game: Quake 2", "// Format: Valve",
             "// Generated by Q2PRO-X MAPGEN-1 (fixture)", "{",
             '"classname" "worldspawn"', '"mapversion" "220"',
             f'"message" "{message}"']
    for b in brushes:
        lines.append(b.render().rstrip("\n"))
    lines.append("}")
    for ent in entities:
        lines.append("{")
        for k, v in ent.items():
            if k == "brushes":
                continue
            lines.append(f'"{k}" "{v}"')
        # A door is brushes. An entity that could only be keys and values could
        # not have one, and half the mandatory REDs are about movers.
        for b in ent.get("brushes", ()):
            lines.append(b.render().rstrip("\n"))
        lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def spawn(at=(0, 0, 32)):
    return {"classname": "info_player_deathmatch",
            "origin": f"{at[0]:g} {at[1]:g} {at[2]:g}"}


def light(at=(0, 0, 200), value=300):
    return {"classname": "light", "light": str(value),
            "origin": f"{at[0]:g} {at[1]:g} {at[2]:g}"}


FIXTURES = {}


def _register(name):
    def wrap(fn):
        FIXTURES[name] = fn
        return fn
    return wrap


@_register("oblique_seam")
def _oblique_seam(path: Path) -> None:
    """Two solids sharing one slanted seam, inside a sealed room.

    The subject of the seam RED: if a round trip can keep this hairline shut,
    it can keep q2dm1's rock walls shut."""
    brushes = hollow_room((-256, -256, 0), (512, 512, 384))
    brushes += oblique_pair((0, 0, 0))
    write_map(path, brushes, [spawn((-128, -128, 32)), light((128, 128, 300))],
              "oblique seam")


@_register("wedge_room")
def _wedge_room(path: Path) -> None:
    """One wedge on the floor: an oblique face with nothing meeting it."""
    brushes = hollow_room((-256, -256, 0), (512, 512, 384))
    brushes.append(wedge((0, 0, 0), (256, 256, 128)))
    write_map(path, brushes, [spawn((-128, -128, 32)), light((128, 128, 300))],
              "wedge room")


@_register("stacked_space")
def _stacked_space(path: Path) -> None:
    """Two rooms one above the other, overlapping in XY - the arrangement a
    grid of cells cannot express."""
    brushes = hollow_room((-256, -256, 0), (512, 512, 640))
    brushes.append(box((-256, -256, 288), (512, 512, 320)))   # the floor between
    brushes.append(box((0, 0, 288), (128, 128, 320),
                       texture="e1u1/c_met5_1", contents=0))  # a hole in it
    write_map(path, brushes, [spawn((-128, -128, 32)), light((128, 128, 200)),
                              light((128, 128, 500))], "stacked space")


def _two_blocks(right_top: int):
    """A sealed room with two blocks standing shoulder to shoulder in it.

    Both of their long faces are open to the room, and each pair of them is one
    plane; `right_top` is how tall the right block is, and when that is not the
    left one's height the corner where they meet splits the other's edge, which
    is a T-junction on a face somebody can stand in front of - two of them, one
    on each side.
    """
    brushes = hollow_room((-256, -256, 0), (512, 512, 384))
    brushes.append(box((-192, 128, 0), (-64, 256, 192)))
    brushes.append(box((-64, 128, 0), (64, 256, right_top)))
    return brushes


@_register("surface_flush")
def _surface_flush(path: Path) -> None:
    """The two blocks the same height: one edge, shared end to end."""
    write_map(path, _two_blocks(192),
              [spawn((0, -128, 32)), light((0, 0, 320))], "surface flush")


@_register("surface_tee")
def _surface_tee(path: Path) -> None:
    """The right one half as tall: its top corner splits the other's edge."""
    write_map(path, _two_blocks(96),
              [spawn((0, -128, 32)), light((0, 0, 320))], "surface tee")


@_register("carve_spawns")
def _carve_spawns(path: Path) -> None:
    """A player start in each corner, where the platform goes."""
    brushes = hollow_room((-192, -192, 0), (192, 192, 256))
    starts = [spawn((x, y, 32)) for x in (-160, 160) for y in (-160, 160)]
    write_map(path, brushes, starts + [light((0, 0, 200))], "carve spawns")


def main(argv=None) -> int:
    import sys
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 1:
        print("usage: mapgen_geometry_fixtures.py <out dir> [name ...]")
        print("fixtures: " + ", ".join(sorted(FIXTURES)))
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    names = argv[1:] or sorted(FIXTURES)
    for name in names:
        if name not in FIXTURES:
            print(f"no fixture {name}")
            return 2
        path = out / f"{name}.map"
        FIXTURES[name](path)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def faceted_arc(centre=(0, 0), radius=384, z0=0, z1=256, segments=12,
                span=math.pi, thickness=96, texture="e1u1/c_met5_1"):
    """A curved wall built the way a level designer builds one: a run of
    wedges, each sharing a shallow oblique plane with its neighbour.

    Every joint is a place two solids have to agree exactly, and the plane
    distances are whatever the trigonometry makes them - which is the case the
    integer-cornered fixtures never exercise.
    """
    cx, cy = centre
    brushes = []
    for i in range(segments):
        a0 = span * i / segments
        a1 = span * (i + 1) / segments
        inner = [(cx + radius * math.cos(a), cy + radius * math.sin(a))
                 for a in (a0, a1)]
        outer = [(cx + (radius + thickness) * math.cos(a),
                  cy + (radius + thickness) * math.sin(a))
                 for a in (a0, a1)]

        # A four-sided column: two radial cuts, an inner face and an outer one.
        p_in0, p_in1 = inner
        p_out0, p_out1 = outer

        def face(a, b, outward, u, v):
            return (((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1)),
                    outward, u, v)

        # Outward normals: the inner face looks toward the centre, the outer
        # away from it, and each radial cut looks along the arc.
        mid_in = ((p_in0[0] + p_in1[0]) / 2, (p_in0[1] + p_in1[1]) / 2)
        inward = (cx - mid_in[0], cy - mid_in[1], 0)
        outward = (-inward[0], -inward[1], 0)
        cut0 = (math.sin(a0), -math.cos(a0), 0)
        cut1 = (-math.sin(a1), math.cos(a1), 0)

        faces = [
            face(p_in0, p_in1, inward, (1, 0, 0), (0, 0, -1)),
            face(p_out0, p_out1, outward, (1, 0, 0), (0, 0, -1)),
            face(p_in0, p_out0, cut0, (0, 1, 0), (0, 0, -1)),
            face(p_in1, p_out1, cut1, (0, 1, 0), (0, 0, -1)),
            (((p_in0[0], p_in0[1], z1), (p_in1[0], p_in1[1], z1),
              (p_out1[0], p_out1[1], z1)), (0, 0, 1), (1, 0, 0), (0, -1, 0)),
            (((p_out1[0], p_out1[1], z0), (p_in1[0], p_in1[1], z0),
              (p_in0[0], p_in0[1], z0)), (0, 0, -1), (1, 0, 0), (0, -1, 0)),
        ]
        brushes.append(Brush([Side(points=oriented(p, n), texture=texture,
                                   u_axis=u, v_axis=v)
                              for p, n, u, v in faces]))
    return brushes


@_register("faceted_wall")
def _faceted_wall(path: Path) -> None:
    """A curved wall of twelve wedges inside a sealed room.

    If a round trip can keep these dozen shallow seams shut, it can keep
    q2dm1's rock walls shut; if it cannot, this is where to look, and it
    compiles in seconds instead of minutes.
    """
    brushes = hollow_room((-640, -640, 0), (640, 640, 384))
    brushes += faceted_arc(centre=(0, 0), radius=320, z0=0, z1=256,
                           segments=12, span=math.pi)
    write_map(path, brushes, [spawn((0, -448, 32)), light((0, 0, 300)),
                              light((0, -320, 300))], "faceted wall")


@_register("faceted_wall_short")
def _faceted_wall_short(path: Path) -> None:
    """The faceted wall, eight units shorter, and nothing else.

    Not a fixture the round trip is run on: a REFERENCE for the render
    contract. Compared against `faceted_wall` it must be refused, because every
    facet has genuinely lost a strip - same planes, same materials, same count,
    three per cent less of each. A contract that accepted this would accept a
    map that quietly shed a strip from every wall in it.
    """
    brushes = hollow_room((-640, -640, 0), (640, 640, 384))
    brushes += faceted_arc(centre=(0, 0), radius=320, z0=0, z1=248,
                           segments=12, span=math.pi)
    write_map(path, brushes, [spawn((0, -448, 32)), light((0, 0, 300)),
                              light((0, -320, 300))], "faceted wall short")


@_register("faceted_wall_clear")
def _faceted_wall_clear(path: Path) -> None:
    """The same arc, lifted clear of the floor and the ceiling.

    A control for the one thing the sealed room forces on the first version:
    the arc sits ON the floor, so its underside and the floor's top face are
    coincident, and which of two coincident faces a compiler keeps is its own
    business. Lifting the arc removes every such pair, and whatever difference
    survives is about the arc itself.
    """
    brushes = hollow_room((-640, -640, 0), (640, 640, 512))
    brushes += faceted_arc(centre=(0, 0), radius=320, z0=64, z1=320,
                           segments=12, span=math.pi)
    write_map(path, brushes, [spawn((0, -448, 32)), light((0, 0, 400)),
                              light((0, -320, 300))], "faceted wall clear")


# ---- the closures the carving REDs are about --------------------------------
#
# Codex, 2026-09-02, section 6: the mandatory carving REDs. Each of the first
# six is a shape a map can have, so each is a map.


def _room_with(*groups, message="closure", spawn_at=(-160, -160, 32)):
    brushes = hollow_room((-256, -256, 0), (512, 512, 384))
    for group in groups:
        brushes += group
    return brushes, [spawn(spawn_at), light((128, 128, 300))], message


def _wall_in_three(x0=0, y=0, z0=0, height=192, thickness=32, run=128):
    """One wall, built the way a level designer builds one: pieces in a row
    sharing their front and back planes. In the compiled brush lump this is
    indistinguishable from a wall the compiler cut up, which is the point."""
    return [box((x0 + i * run, y, z0),
                (x0 + (i + 1) * run, y + thickness, z0 + height))
            for i in range(3)]


@_register("closure_split_wall")
def _closure_split_wall(path: Path) -> None:
    """RED 1: the source brush must not block its own edit.

    Ask "is there other solid inside this wall" of the middle piece and the
    answer has to be no. A query that excluded only the nominal brush would
    find the two pieces either side of it and report rock."""
    brushes, ents, msg = _room_with(_wall_in_three())
    write_map(path, brushes, ents, msg)


@_register("closure_reserve")
def _closure_reserve(path: Path) -> None:
    """RED 2: adjacent independent reserve solid stays protected.

    The same wall, and a second one standing well clear of it. Nothing about
    the first may take the second, and a point inside the second is other
    solid however the first is queried."""
    brushes, ents, msg = _room_with(_wall_in_three(),
                                    [box((0, 160, 0), (384, 192, 192))])
    write_map(path, brushes, ents, msg)


@_register("closure_oblique")
def _closure_oblique(path: Path) -> None:
    """RED 3: an oblique wedge where the bounding box gives the wrong answer.

    The wedge's box covers the corner the pillar stands in and its solid does
    not come near it. Anything reasoning from boxes takes the pillar."""
    brushes, ents, msg = _room_with([wedge((0, 0, 0), (256, 256, 192))],
                                    [box((200, 200, 0), (232, 232, 192))])
    write_map(path, brushes, ents, msg)


@_register("closure_seam")
def _closure_seam(path: Path) -> None:
    """RED 4: a shared seam between two logical structures.

    A pillar standing against a wall that runs the length of the room. They
    meet on one plane, facing opposite ways, and they are two things. Taking
    the wall with the pillar would make every closure the map."""
    brushes, ents, msg = _room_with([box((0, 0, 0), (64, 64, 192))],
                                    [box((64, -224, 0), (96, 480, 384))])
    write_map(path, brushes, ents, msg)


@_register("closure_mixed")
def _closure_mixed(path: Path) -> None:
    """RED 5: detail, clip, support and structural in one closure.

    A ledge, the trim along its edge, the invisible brush that stops a player
    short of it, and the post holding it up. Carving the ledge and leaving the
    clip behind leaves a wall a player cannot walk through and cannot see."""
    ledge = box((0, 0, 96), (192, 96, 128))
    trim = box((0, 96, 96), (192, 104, 112))
    post = box((80, 32, 0), (112, 64, 96))
    clip = box((0, 104, 96), (192, 112, 160), texture="e1u1/clip")
    brushes, ents, msg = _room_with([ledge, trim, post, clip])
    write_map(path, brushes, ents, msg)


@_register("closure_mover")
def _closure_mover(path: Path) -> None:
    """RED 6: a mover, its model and the entity that works it.

    Half a door is not a door, and a door whose button is left behind is a
    door nobody can open."""
    frame = [box((-32, 0, 0), (0, 32, 192)), box((96, 0, 0), (128, 32, 192))]
    door = {"classname": "func_door", "targetname": "gate", "angle": "-1",
            "speed": "100", "wait": "3",
            "brushes": [box((0, 0, 0), (96, 32, 192))]}
    button = {"classname": "func_button", "target": "gate", "angle": "-2",
              "speed": "40", "wait": "3",
              "brushes": [box((-192, 96, 32), (-160, 128, 64))]}
    brushes, ents, msg = _room_with(frame)
    write_map(path, brushes, ents + [door, button], msg)


# ---- the two walls the widen operator has to tell apart ---------------------


def _two_rooms(gap: int, wall_thickness: int = 64):
    """Two chambers separated by one wall with a doorway through it.

    `gap` is how wide the doorway is, which decides how much WALL is left
    beside it - and that pier is what the widen operator cuts into. The wall's
    thickness across the passage is the same in both, because it is not what
    the operator touches and a fixture that varied it would be asking a
    question nobody is asked."""
    outer = hollow_room((-320, -320, 0), (320, 320, 256))
    x0, x1 = -wall_thickness // 2, wall_thickness // 2
    # Right into the outer wall at both ends: a wall that stops short of it
    # leaves a slot the rooms are joined through, and then the doorway is not
    # the only way between them and its flanks are not what they seem.
    wall = [box((x0, -352, 0), (x1, -gap // 2, 256)),
            box((x0, gap // 2, 0), (x1, 352, 256))]
    return outer + wall


@_register("widen_thick")
def _widen_thick(path: Path) -> None:
    """A doorway sixty-four wide, with two hundred and fifty-six units of pier
    on each side of it. Taking thirty-two of that back leaves plenty."""
    write_map(path, _two_rooms(64),
              [spawn((-192, 0, 32)), spawn((192, 0, 32)),
               light((0, 0, 200))], "widen thick")


@_register("widen_thin")
def _widen_thin(path: Path) -> None:
    """One doorway with a long pier on one side and a short one on the other.

    Both flanks of one way through, differing in the only thing the operator
    cares about: how much wall there is to take. Four hundred and eighty units
    on one side, thirty-two on the other, and thirty-two is less than what is
    taken plus what has to remain. One flank has to move and the other has to
    decline, in the same map, on the same run."""
    outer = hollow_room((-320, -320, 0), (320, 320, 256))
    # The pier is forty deep and the wall behind it is a different brush, so
    # what refuses the edit is how little pier there is rather than something
    # flush against it or the outer shell standing in the way.
    wall = [box((-32, -352, 0), (32, 192, 256)),
            box((-32, 288, 0), (32, 328, 256)),
            box((-32, 328, 0), (32, 392, 256))]
    write_map(path, outer + wall,
              [spawn((-192, 0, 32)), spawn((192, 0, 32)),
               light((0, 0, 200))], "widen thin")


@_register("widen_clipped")
def _widen_clipped(path: Path) -> None:
    """The wide doorway again, with an invisible brush flush against one flank.

    A playerclip is a wall for a player and nothing for the compiler, so the
    test that asks whether there is SOLID beyond a face walks straight past it.
    Take the flank back and the clip stays where it was: an invisible wall
    standing in the middle of the passage that was just widened."""
    outer = hollow_room((-320, -320, 0), (320, 320, 256))
    wall = [box((-32, -352, 0), (32, -32, 256)),
            box((-32, 32, 0), (32, 352, 256))]
    clip = box((-32, -40, 0), (32, -32, 256), texture="e1u1/clip")
    write_map(path, outer + wall + [clip],
              [spawn((-192, 0, 32)), spawn((192, 0, 32)),
               light((0, 0, 200))], "widen clipped")


# ---- rooms that can be turned, and one that cannot --------------------------


def _chamber_with_arms(arms, hall=192, corridor=48, cell=128, height=192):
    """A central chamber with corridors to small chambers in the named
    directions.

    Every distance is a half-width: the chamber reaches `hall` from the middle,
    a corridor is `corridor` half-wide, and the chamber at the end of one is
    `cell` half-wide. `arms` is any of "+x", "-x", "+y", "-y", and it is the
    ONLY thing that differs between the fixtures, because it is the only thing
    a turn's legality depends on.

    The solid is one quadrant's worth of fill, turned four times. Written out
    by hand for each side it came out subtly asymmetric - one set of boxes
    clipping a corner off another - and the operator refused the quarter turns
    for the good reason that the map did not have them.

    A corridor also has to arrive somewhere. A dead-end arm is a bump on the
    room it left, the watershed merges it back, and there is no socket at all.
    """
    near = hall + 192          # where a corridor ends and its chamber begins
    far = near + 256           # the outer wall
    brushes = hollow_room((-far, -far, 0), (far, far, height))

    # The solid of one quadrant: everything outside the chamber, its two
    # corridors and their two chambers.
    quadrant = [
        (hall, corridor, near, cell),
        (hall, cell, far, hall),
        (corridor, hall, far, near),
        (cell, near, far, far),
    ]

    def turned(x0, y0, x1, y1, quarter):
        """The same rectangle, a quarter turn round, as (x,y) -> (-y,x)."""
        corners = [(x0, y0), (x1, y1)]
        for _ in range(quarter):
            corners = [(-y, x) for x, y in corners]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return min(xs), min(ys), max(xs), max(ys)

    for quarter in range(4):
        for rect in quadrant:
            x0, y0, x1, y1 = turned(*rect, quarter)
            brushes.append(box((x0, y0, 0), (x1, y1, height)))

    # And an arm nobody asked for is plugged, flush with the chamber.
    for side in ("+x", "-x", "+y", "-y"):
        if side in arms:
            continue
        if side == "+x":
            brushes.append(box((hall, -corridor, 0), (far, corridor, height)))
        elif side == "-x":
            brushes.append(box((-far, -corridor, 0), (-hall, corridor, height)))
        elif side == "+y":
            brushes.append(box((-corridor, hall, 0), (corridor, far, height)))
        else:
            brushes.append(box((-corridor, -far, 0), (corridor, -hall, height)))

    return brushes


@_register("turn_cross")
def _turn_cross(path: Path) -> None:
    """Four ways out at ninety degrees. Every quarter turn is legal."""
    brushes = _chamber_with_arms(("+x", "-x", "+y", "-y"))
    write_map(path, brushes,
              [spawn((0, 0, 32)), spawn((512, 0, 32)),
               light((0, 0, 160))], "turn cross")


@_register("turn_tee")
def _turn_tee(path: Path) -> None:
    """The same chamber with one arm walled off. No turn maps three ways out
    onto themselves, so the operator has to decline."""
    brushes = _chamber_with_arms(("+x", "-x", "+y"))
    write_map(path, brushes,
              [spawn((0, 0, 32)), spawn((512, 0, 32)),
               light((0, 0, 160))], "turn tee")


# --------------------------------------------------------------------------
# a way through a wall that had none
# --------------------------------------------------------------------------

def _divided(wall_x=32, wall_top=256, floor_lift=0):
    """One chamber cut in two by a single solid wall, with no way between.

    The wall is ONE box, which is what the operator needs: it turns that box
    into its two jambs and its lintel. `wall_x` is its half-thickness across
    the passage, `wall_top` how high it stands, and `floor_lift` raises the far
    room's floor - the three things the four refusals vary one at a time.
    """
    brushes = hollow_room((-320, -320, 0), (320, 320, 256))
    brushes.append(box((-wall_x, -352, 0), (wall_x, 352, wall_top)))
    if floor_lift:
        brushes.append(box((wall_x, -320, 0), (320, 320, floor_lift)))
    return brushes


@_register("open_pair")
def _open_pair(path: Path) -> None:
    """Two rooms, one wall, and everything the operator needs to prove.

    Air on both sides across the whole doorway rectangle, both floors at zero,
    six hundred and forty units of wall across so there is a jamb to spare, and
    two hundred and fifty-six of height so there is a lintel. This is the one
    it must take."""
    write_map(path, _divided(),
              [spawn((-192, 0, 32)), spawn((192, 0, 32)),
               light((0, 0, 200))], "open pair")


@_register("open_solid")
def _open_solid(path: Path) -> None:
    """The same wall with rock behind it instead of a room.

    The far half of the chamber is filled in, so a doorway cut through the wall
    opens into stone. Nothing about the wall itself changed - only what is on
    the other side of it - which is why the operator has to ask the compiled
    map rather than the brush."""
    brushes = _divided()
    brushes.append(box((32, -320, 0), (320, 320, 256)))
    write_map(path, brushes,
              [spawn((-192, 0, 32)), light((-192, 0, 200))], "open solid")


@_register("open_narrow")
def _open_narrow(path: Path) -> None:
    """A corridor divided by a plug too narrow to leave a jamb.

    The chamber is eighty units across, so the wall that plugs it is eighty
    across too - and a sixty-four-wide doorway would leave eight units at each
    end, slivers rather than jambs. Made narrow by making the ROOM narrow, so
    the plug is the only box in the map with air on both sides and there is no
    second candidate to confuse the answer with."""
    brushes = hollow_room((-320, -40, 0), (320, 40, 256))
    brushes.append(box((-32, -40, 0), (32, 40, 256)))
    write_map(path, brushes,
              [spawn((-192, 0, 32)), spawn((192, 0, 32)),
               light((0, 0, 200))], "open narrow")


@_register("open_low")
def _open_low(path: Path) -> None:
    """The same two rooms, and a wall too low to carry a lintel.

    The wall is a hundred units tall against a doorway that wants ninety-six
    plus sixteen above it. The room above the wall is open, so the two halves
    are already joined over the top - which is exactly why an operator that
    cut this one would be adding nothing and removing the wall's head."""
    write_map(path, _divided(wall_top=100),
              [spawn((-192, 0, 32)), spawn((192, 0, 32)),
               light((0, 0, 200))], "open low")


@_register("open_step")
def _open_step(path: Path) -> None:
    """The same two rooms with the far floor sixty-four units LOWER.

    A drop rather than a rise, and the difference matters: a raised floor is
    refused by the air test, because the doorway's lowest samples are inside it,
    and the fixture would then be proving nothing about floors. Dropped, the
    doorway rectangle is clear on both sides and the only thing wrong is what a
    player would step into - a fall of sixty-four, well past the twenty-four he
    steps."""
    brushes = hollow_room((-320, -320, -64), (320, 320, 256))
    # The near half keeps its floor at zero; the far half does not have one.
    brushes.append(box((-352, -352, -64), (-32, 352, 0)))
    brushes.append(box((-32, -352, 0), (32, 352, 256)))
    write_map(path, brushes,
              [spawn((-192, 0, 32)), spawn((192, 0, -32)),
               light((0, 0, 200))], "open step")


@_register("reshape_plain")
def _reshape_plain(path: Path) -> None:
    """A plain room with two hundred and fifty-six units of rock all round it.

    Nothing stands against its walls, so a whole wall can go back into the rock
    and the room is simply bigger. It is the case the operator exists for, and
    on a real donor it is the rare one: q2dm1's walls have things against them
    and are shared with the rooms next door."""
    write_map(path, hollow_room((-256, -256, 0), (256, 256, 256), thickness=256),
              [spawn((0, 0, 32)), light((0, 0, 200))], "reshape plain")


@_register("reshape_pillar")
def _reshape_pillar(path: Path) -> None:
    """The plain room with a pillar built against its -X wall.

    The pillar's own face is flush against the wall's, so taking that wall back
    would leave the pillar standing a gap away from the thing it was built
    against. The other three walls have nothing against them and are free to
    go."""
    brushes = hollow_room((-256, -256, 0), (256, 256, 256), thickness=256)
    brushes.append(box((-256, -64, 0), (-192, 64, 256)))
    write_map(path, brushes, [spawn((0, 0, 32)), light((0, 0, 200))],
              "reshape pillar")


@_register("reshape_niche")
def _reshape_niche(path: Path) -> None:
    """A room whose -X wall is three pieces, the middle one too thin to move.

    The three share their inner plane, so they are one wall and one surface.
    The middle piece has forty units of rock behind it where its neighbours
    have two hundred and fifty-six, and forty is less than the thirty-two that
    would be taken plus the sixteen that has to remain. A wall moves whole or
    not at all, so none of the three moves - which is the operator's own claim
    and the only thing this fixture is for."""
    t = 256
    x0 = y0 = z0 = -256
    x1 = y1 = z1 = 256
    brushes = [
        # every slab but the -X wall
        box((x1, y0 - t, z0 - t), (x1 + t, y1 + t, z1 + t)),
        box((x0, y0 - t, z0 - t), (x1, y0, z1 + t)),
        box((x0, y1, z0 - t), (x1, y1 + t, z1 + t)),
        box((x0, y0, z0 - t), (x1, y1, z0)),
        box((x0, y0, z1), (x1, y1, z1 + t)),
        # the -X wall, in three, with the middle piece forty deep
        box((x0 - t, y0 - t, z0 - t), (x0, -64, z1 + t)),
        box((x0 - 40, -64, z0 - t), (x0, 64, z1 + t)),
        box((x0 - t, 64, z0 - t), (x0, y1 + t, z1 + t)),
        # and the rock behind the thin piece, so the map still closes
        box((x0 - t, -64, z0 - t), (x0 - 40, 64, z1 + t)),
    ]
    write_map(path, brushes, [spawn((0, 0, 32)), light((0, 0, 200))],
              "reshape niche")


# ---- ledges for the rocket jump ---------------------------------------------


def _ledge_room(ceiling=512, with_launcher=True, with_rockets=True,
                pit=False):
    """A room with a ledge two hundred units up and an item on it.

    The floor is where a player starts and where the launcher lies; the ledge
    is out of reach of any ordinary jump, which tops out at about sixty units
    of rise. `ceiling` lowers the roof to squash the flight; `pit` replaces the
    landing floor with a hole he cannot climb out of."""
    brushes = hollow_room((-384, -384, 0), (384, 384, ceiling), thickness=64)
    # The ledge: a shelf against the +X wall, two hundred units up.
    brushes.append(box((256, -128, 176), (384, 128, 200)))
    if pit:
        # A trench across the room that a player cannot climb out of, so
        # anything that comes down lands in it.
        brushes.append(box((-384, -384, 0), (-320, 384, 320)))
        brushes.append(box((-320, -384, 200), (256, 384, 320)))

    ents = [spawn((-256, 0, 32)), light((0, 0, ceiling - 64))]
    ents.append({"classname": "item_health_mega", "origin": "320 0 224"})
    if with_launcher:
        ents.append({"classname": "weapon_rocketlauncher",
                     "origin": "-256 -128 32"})
    if with_rockets:
        ents.append({"classname": "ammo_rockets", "origin": "-256 128 32"})
    return brushes, ents


@_register("rocketjump_ledge")
def _rocketjump_ledge(path: Path) -> None:
    """The case the operator exists for: a ledge walking cannot reach, with
    the means to reach it lying on the floor."""
    brushes, ents = _ledge_room()
    write_map(path, brushes, ents, "rocketjump ledge")


@_register("rocketjump_unarmed")
def _rocketjump_unarmed(path: Path) -> None:
    """The same ledge with no launcher anywhere. A player cannot rocket jump
    without a rocket launcher, so the item is simply unreachable."""
    brushes, ents = _ledge_room(with_launcher=False)
    write_map(path, brushes, ents, "rocketjump unarmed")


@_register("rocketjump_dry")
def _rocketjump_dry(path: Path) -> None:
    """The same ledge, a launcher, and nothing to fire from it."""
    brushes, ents = _ledge_room(with_rockets=False)
    write_map(path, brushes, ents, "rocketjump dry")


@_register("rocketjump_lidded")
def _rocketjump_lidded(path: Path) -> None:
    """The same ledge under a roof too low to fly to it. The impulse is the
    same; the room refuses it."""
    brushes, ents = _ledge_room(ceiling=224)
    write_map(path, brushes, ents, "rocketjump lidded")


@_register("rocketjump_pit")
def _rocketjump_pit(path: Path) -> None:
    """The same ledge, and every way down is into a trench he cannot leave.
    Touching a thing on the way to being stuck is not reaching it."""
    brushes, ents = _ledge_room(pit=True)
    write_map(path, brushes, ents, "rocketjump pit")


# ---- two rooms that could change places -------------------------------------


def _two_chambers(extra_arm):
    """Two chambers joined by a corridor, optionally with a stub off one.

    Each chamber is 256 square, the corridor between them 96 wide, and the
    whole thing sealed in rock. With `extra_arm` the right-hand chamber gets a
    second way out, which is the one thing that makes the two of them
    different."""
    far = 704
    brushes = hollow_room((-far, -256, 0), (far, 256, 192))

    def fill(x0, y0, x1, y1):
        if x1 > x0 and y1 > y0:
            brushes.append(box((x0, y0, 0), (x1, y1, 192)))

    # Solid between the chambers except a corridor 96 wide on the axis.
    # A short wall, so the corridor between them is too small to skew which
    # chamber the watershed gives its air to: at three hundred and eighty-four
    # units long the whole corridor went to one of them and the twins came out
    # a hundred and eighty cells apart.
    fill(-32, 48, 32, 256)
    fill(-32, -256, 32, -48)
    # The chambers themselves are the space left at each end.
    fill(-far, 256, far, 256)          # nothing; keeps the shape explicit

    if extra_arm:
        # One chamber made shorter than the other. A second way out was tried
        # first and it kept merging back into the room it left - a dead end is
        # a bump, not an arm - and this asks the same question of the same
        # precondition: each one's air has to fit where the other's was.
        brushes.append(box((-far, -256, 0), (-400, 256, 192)))
    return brushes


# ---- a ring of rooms that can be recomposed ---------------------------------

# The hub is 320 square, each chamber is 320 square, the wall between them is
# 32 thick and the doorway through it is 96 wide. No corridors: air that
# belongs to nobody is air the watershed has to give to somebody, and it gave
# the north one away differently from the east one.
_RING_HUB = 160         # the hub reaches this far from the middle
_RING_WALL = 32         # and the wall between hub and chamber is this thick
_RING_ROOM = 320        # each chamber is this square
_RING_DOOR = 48         # the doorway reaches this far either side of the axis


def _ring(short=()):
    """A hub with four chambers around it, one doorway each.

    `short` names chambers (0 north, 1 east, 2 south, 3 west) to take 96 units
    off the depth of one - more than the sixty-four the operator allows two
    rooms to differ by, which is the one thing that stops them being
    interchangeable.
    """
    inner = _RING_HUB + _RING_WALL          # 192: where a chamber begins
    far = inner + _RING_ROOM                # 512: and where it ends
    brushes = hollow_room((-far, -far, 0), (far, far, 192))

    def fill(x0, y0, x1, y1):
        if x1 > x0 and y1 > y0:
            brushes.append(box((x0, y0, 0), (x1, y1, 192)))

    # The four corners are rock all the way out.
    for sx in (-1, 1):
        for sy in (-1, 1):
            fill(_RING_HUB if sx > 0 else -far, _RING_HUB if sy > 0 else -far,
                 far if sx > 0 else -_RING_HUB, far if sy > 0 else -_RING_HUB)

    # Each wall, with its doorway left out of it.
    fill(-_RING_HUB, _RING_HUB, -_RING_DOOR, inner)     # north wall
    fill(_RING_DOOR, _RING_HUB, _RING_HUB, inner)
    fill(-_RING_HUB, -inner, -_RING_DOOR, -_RING_HUB)   # south wall
    fill(_RING_DOOR, -inner, _RING_HUB, -_RING_HUB)
    fill(_RING_HUB, -_RING_HUB, inner, -_RING_DOOR)     # east wall
    fill(_RING_HUB, _RING_DOOR, inner, _RING_HUB)
    fill(-inner, -_RING_HUB, -_RING_HUB, -_RING_DOOR)   # west wall
    fill(-inner, _RING_DOOR, -_RING_HUB, _RING_HUB)

    # A shortened chamber gets its own far WALL, 32 thick, and plain rock
    # beyond it. Filling the whole tail instead made the fill part of the
    # room's shell, so its bounding box still reached the outer wall and the
    # four chambers measured the same size after all.
    give = 128
    for which in short:
        if which == 0:                      # north
            fill(-_RING_HUB, far - give, _RING_HUB, far - give + _RING_WALL)
            fill(-_RING_HUB, far - give + _RING_WALL, _RING_HUB, far)
        elif which == 1:                    # east
            fill(far - give, -_RING_HUB, far - give + _RING_WALL, _RING_HUB)
            fill(far - give + _RING_WALL, -_RING_HUB, far, _RING_HUB)
        elif which == 2:                    # south
            fill(-_RING_HUB, -far + give - _RING_WALL, _RING_HUB, -far + give)
            fill(-_RING_HUB, -far, _RING_HUB, -far + give - _RING_WALL)
        elif which == 3:                    # west
            fill(-far + give - _RING_WALL, -_RING_HUB, -far + give, _RING_HUB)
            fill(-far, -_RING_HUB, -far + give - _RING_WALL, _RING_HUB)
    return brushes


@_register("recompose_ring")
def _recompose_ring(path: Path) -> None:
    """Four interchangeable chambers around one hub."""
    write_map(path, _ring(),
              [spawn((0, 0, 32)), spawn((0, 352, 32)), spawn((352, 0, 32)),
               light((0, 0, 160))], "recompose ring")


@_register("recompose_pair")
def _recompose_pair(path: Path) -> None:
    """The same ring with two chambers made shorter.

    Two rooms that can change places are a swap. A recomposition needs three,
    and there are only two left."""
    write_map(path, _ring(short=(1, 3)),
              [spawn((0, 0, 32)), spawn((0, 352, 32)),
               light((0, 0, 160))], "recompose pair")


@_register("swap_twins")
def _swap_twins(path: Path) -> None:
    """Two chambers with one way out each, facing each other."""
    write_map(path, _two_chambers(False),
              [spawn((-448, 0, 32)), spawn((448, 0, 32)),
               light((0, 0, 160))], "swap twins")


@_register("swap_odd")
def _swap_odd(path: Path) -> None:
    """The same two, except one chamber is a third shorter than the other.

    Exchanging them would put a room where it does not fit, and everything
    around them would notice at once."""
    write_map(path, _two_chambers(True),
              [spawn((-448, 0, 32)), spawn((448, 0, 32)),
               light((0, 0, 160))], "swap odd")


@_register("courses_wall")
def _courses_wall(path: Path) -> None:
    """Two rooms on one floor and, between them, a wall of three 64-high courses up to the ceiling (row 405, W3).

    No course is a window's wall on its own - 64 holds no sill, opening and head - so the window, if any, is the
    wall's: the courses merged, its foot WINDOW_SILL over the floor beside it (not a third of the slab), and its jambs
    clear of the room's side walls the slab runs into."""
    brushes = hollow_room((-320, -320, 0), (320, 320, 192))
    for z in (0, 64, 128):
        brushes.append(box((-8, -352, z), (8, 352, z + 64)))
    write_map(path, brushes,
              [spawn((-192, 0, 32)), spawn((192, 0, 32)),
               light((-160, 0, 160)), light((160, 0, 160))], "courses wall")


@_register("span_pit")
def _span_pit(path: Path) -> None:
    """Two ledges 144 over a pit, 384 apart, and the only way between them round its north end: down into the pit and
    up a stair of nine treads, 32 deep and 16 high, to the east ledge (row 405, brief 5 W5). A bridge across halves
    the walk; without one the plan deals none."""
    brushes = hollow_room((-640, -640, 0), (640, 640, 384))
    brushes.append(box((-640, -640, 0), (-192, 640, 144)))
    brushes.append(box((192, -640, 0), (640, 640, 144)))
    for i in range(9):
        brushes.append(box((-96 + 32 * i, 512, 0), (192, 640, 16 * (i + 1))))
    write_map(path, brushes,
              [spawn((-400, 0, 168)), spawn((400, 0, 168)),
               light((-400, 0, 320)), light((400, 0, 320)), light((0, 0, 300)), light((0, 500, 200))], "span pit")
