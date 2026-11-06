r"""Brief 26 (the PO 06.11, with two recordings of q2_q3dm17: «не просто кружочки подходи и прыгай, тут есть разный
дизайн, включая анимированное направление движения для наклонных джампадов … телепорты … красиво, эффектно, мощно. А у
нас что?»): the jump pads' and teleporters' look on a map from scratch, as people build them.

Measured on q2_q3dm17's BSP (brief 26 §1): a flat pad is a ring plate on an octagonal plinth; a slanted one an 8-sided
wedge with an arrow on top and a translucent FLOWING sheet over it (the engine scrolls such a texture along its s axis -
the «animated direction»); pro_q2t4's vertical pads are round lit discs; a teleporter is the game's disc inside a tall
frame with a mist portal (TRANS33 | FLOWING) and glow strips.

Here:
* a pad flying up steeply (|pitch| >= 75: a tower's shafts and atrium, a deck's lift) - a 16-sided disc 4 high with the
  ring (lit), on an octagonal plinth 8 high (12 together: a step);
* a slanted pad - a wedge turned along the flight's yaw, 2 high at the near end and 14 at the far one, the arrows on top
  pointing along the flight, a mist sheet 2 over it with the same arrows scrolling that way; on the same plinth;
* a teleporter's disc - two hexagonal posts 160 tall at the sides, a lintel, a back slab, a mist portal between the
  posts scrolling up, glow strips on the posts' inner faces; only where the cells beside and behind it allow (same
  floor or a wall); posts only without the slab where the floor behind is a closed pocket; a bare disc where neither.
The trigger and the teleporter entity are the builder's as before: the look changes no flight and no crossing (the
pads' take-off is 12 higher - mapgen_scratch_plan.PAD_TOP - which the planners' flights start from).
"""
from __future__ import annotations

import math

import mapgen_scratch_plan as plan_mod
from mapgen_scratch_build import (CELL, Brush, Surf, slab_poly, box, C_SOLID, C_DETAIL, C_MIST, S_LIGHT,  # noqa: F401
                                  S_TRANS33, S_TRANS66, S_FLOWING, S_NODRAW)

PLINTH_R, PLINTH_H = 44, 8          # the octagon under every pad
DISC_R, DISC_H = 28, 4              # a vertical pad's disc over it
# a slanted pad's wedge: half its side, its near and far heights over the plinth - 2..14, not the brief's 4..24: the
# people's survey launches a pad from the walk node nearest its trigger's middle, up to 32 over the trigger's base +
# 24 - on a wedge rising to 32 over the floor, its top: 25 over the planned take-off. The planners check a slanted
# pad's flight from its foot and from 18 higher (mapgen_scratch_plan.PAD_WEDGE_LIFT, what 2..14 gives) and keep
# columns off its flight and run-out (a column one cell past a landing stopped one, 06.11, plan 26249105014)
WEDGE_HALF, WEDGE_LOW, WEDGE_HIGH = 24, 2, 14
STEEP = plan_mod.PAD_STEEP          # a pad flying up steeper than this is a disc
ARROW_TURN = 0                      # the arrows' turn off the flight: 0 (a RED of check_mapgen_fixtures turns them 180)
FRAME_H = 160                       # a teleporter's posts and back slab
FRAME_TOP = 168                     # with the lintel; the space's ceiling must stand 8 over it
POST_ACROSS, POST_BEHIND, POST_R = 44, 24, 12
SLAB_FROM, SLAB_TO, SLAB_HALF = 36, 44, 48
PORTAL_FROM, PORTAL_TO, PORTAL_HALF, PORTAL_LOW, PORTAL_HIGH = 22, 26, 40, -8, 120
FX_TEX = 64                         # the fixtures' textures' size in the game's units (mapgen_texgen.FX_WAL)


def _poly(cx, cy, r, n, start):
    return [(cx + r * math.cos(start + 2 * math.pi * k / n), cy + r * math.sin(start + 2 * math.pi * k / n)) for k in range(n)]


def _centred(cx, cy, rot_deg):
    """The texture shift that puts a 64-unit texture's middle on (cx, cy) for a face whose s axis, turned by rot_deg,
    runs along (cos, sin) and t along (sin, -cos) (Quake II's map format on a floor-like face)."""
    a = math.radians(rot_deg)
    s = cx * math.cos(a) + cy * math.sin(a)
    t = cx * math.sin(a) - cy * math.cos(a)
    return (round((FX_TEX / 2 - s) % FX_TEX, 2), round((FX_TEX / 2 - t) % FX_TEX, 2))


def pad_brushes(pal: dict, cell, zf: int, pitch: float, yaw: float) -> tuple[list, str]:
    """The look of one pad at physical cell `cell` with floor zf: (brushes, «disc» | «wedge»)."""
    fx = pal["fx"]
    trim = pal["trim"][0]
    cx, cy = (cell[0] + 0.5) * CELL, (cell[1] + 0.5) * CELL
    out = [slab_poly(_poly(cx, cy, PLINTH_R, 8, math.pi / 8), zf, zf + PLINTH_H, {"default": trim},
                     contents=C_SOLID | C_DETAIL, note="pad plinth")]
    z0 = zf + PLINTH_H
    if abs(pitch) >= STEEP:
        ring = Surf(fx["padring"], S_LIGHT, 300, 1.0, _centred(cx, cy, 0), 0)
        out.append(slab_poly(_poly(cx, cy, DISC_R, 16, 0.0), z0, z0 + DISC_H, {"default": trim, "+z": ring},
                             contents=C_SOLID | C_DETAIL, note="pad disc"))
        return out, "disc"
    u = (math.cos(math.radians(yaw)), math.sin(math.radians(yaw)))
    v = (-u[1], u[0])
    h = WEDGE_HALF
    sq = [(cx + a * u[0] * h + b * v[0] * h, cy + a * u[1] * h + b * v[1] * h) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]

    def top(x, y, lift=0.0):
        along = (x - cx) * u[0] + (y - cy) * u[1]          # -h at the near end .. +h at the far one
        return z0 + WEDGE_LOW + (along + h) / (2 * h) * (WEDGE_HIGH - WEDGE_LOW) + lift

    rot = round((yaw + ARROW_TURN) % 360, 2)
    arrow = Surf(fx["padarrow"], 0, 0, 1.0, _centred(cx, cy, rot), rot)
    out.append(slab_poly(sq, z0, top, {"default": trim, "+z": arrow}, contents=C_SOLID | C_DETAIL, note="pad wedge"))
    # the sheet over it: the arrows again, translucent, scrolling along the flight (FLOWING moves a texture to +s)
    flow = Surf(fx["flowarrow"], S_TRANS33 | S_FLOWING, 0, 1.0, _centred(cx, cy, rot), rot)
    hidden = Surf(fx["flowarrow"], S_NODRAW, 0)
    inset = [(cx + a * u[0] * (h - 2) + b * v[0] * (h - 2), cy + a * u[1] * (h - 2) + b * v[1] * (h - 2))
             for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    out.append(slab_poly(inset, lambda x, y: top(x, y, 2), lambda x, y: top(x, y, 4),
                         {"default": hidden, "+z": flow}, contents=C_MIST | C_DETAIL, note="pad flow"))
    return out, "wedge"


def _kind(P, k, z, sid, busy) -> str:
    """What a cell next to a teleporter's disc is for its frame: «floor» (the disc's space, flat at its height, free),
    «wall» (rock: no space there - but over the void of an open space or a tower's atrium it is air), else «other»."""
    if k in busy or k in P.voids:
        return "other"
    o = P.owner.get(k)
    if o is None:
        return "other" if P.params.get("shape") == "space" else "wall"
    s = P.spaces[o]
    f = s.floor.get(k)
    if o != sid or f is None or f[1] != "flat" or f[0] != z:
        return "other"
    return "floor"


def frame_cells(P, c, face=None):
    """The facing (0/90/180/270: the longest open run of its space, as a spawn faces) and the cells beside and behind
    a teleporter's disc at plan key c: {"L", "R", "B", "BL", "BR"}."""
    face = plan_mod.facing(P, c) if face is None else face
    fx, fy = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[face]
    lx, ly = -fy, fx
    cells = {"L": (c[0] + lx, c[1] + ly), "R": (c[0] - lx, c[1] - ly), "B": (c[0] - fx, c[1] - fy),
             "BL": (c[0] - fx + lx, c[1] - fy + ly), "BR": (c[0] - fx - lx, c[1] - fy - ly)}
    return face, cells


def reserve_frame(P, c) -> None:
    """The planners, when they place a teleporter's disc: no item and no spawn beside or behind it (its frame's posts
    stand in the side cells)."""
    _face, cells = frame_cells(P, c)
    P.no_items.update(k for k in cells.values() if P.owner.get(k) is not None)
    # the sides of the other ways it may face (teleporter_frame turns it when a side is another room)
    P.no_items.update(k for k in ((c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1))
                      if P.owner.get(k) is not None)


def busy_cells(P) -> set:
    """Cells something else stands on or uses: items, spawns, pads, teleporters and their exits, lifts, ladders, pits,
    liquids, doorways, buttons."""
    out = {c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns}
    out |= {x for (a, t, *_r) in P.pads for x in (a, t)}
    out |= {x for tp in P.teleports for x in tp}
    out |= {c for (plat, *_r) in P.lifts for c in plat}
    out |= {c for (cells, *_r) in P.ladders for c in cells} | {c for (*_r, front) in P.ladders for c in front}
    out |= {c for (cells, *_r) in P.pits for c in cells} | {c for (cells, *_r) in P.liquids for c in cells}
    out |= {c for d in P.doors for c in d.cells}
    out |= set(plan_mod.button_cells(P))
    return out


def teleporter_frame(P, pal: dict, c, busy: set) -> tuple[list, str, str, int]:
    """The frame round a teleporter's disc at plan key c: (brushes, «frame» | «posts» | «bare», why, facing)."""
    sid = P.owner.get(c)
    s = P.spaces[sid]
    z = s.floor[c][0]
    # the facing the disc's space opens to first; when a side there is another room (its wall on the cell's edge), the
    # other ways round with an open front (a third of the rooms maps' discs came out bare by the first alone, 06.11)
    first = plan_mod.facing(P, c)
    for face in (first, (first + 90) % 360, (first + 270) % 360, (first + 180) % 360):
        face, cells = frame_cells(P, c, face)
        kinds = {k: _kind(P, v, z, sid, busy) for k, v in cells.items()}
        f_ = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[face]
        front = (c[0] + f_[0], c[1] + f_[1])
        if kinds["L"] != "other" and kinds["R"] != "other" and P.owner.get(front) == sid and front not in P.voids:
            break
    else:
        face, cells = frame_cells(P, c, first)
        kinds = {k: _kind(P, v, z, sid, busy) for k, v in cells.items()}
    ceil = min(P.cell_ceil.get(k, s.ceil) if P.owner.get(k) == sid else s.ceil for k in [c] + list(cells.values()))
    if kinds["L"] == "other" or kinds["R"] == "other":
        return [], "bare", "beside it: " + ", ".join(f"{k} {kinds[k]}" for k in ("L", "R") if kinds[k] == "other"), face
    # the frame as tall as the room lets it: 160 posts, lower under a low ceiling (a tower's storeys of 160), never
    # under 120 (the portal's own height)
    H = min(FRAME_H, ceil - z - 16)
    if H < 120:
        return [], "bare", f"the ceiling {ceil - z} over the floor (the frame needs 136)", face
    slab = kinds["B"] == "wall" or (kinds["B"] == "floor" and "floor" in (kinds["BL"], kinds["BR"]))
    why = "" if slab else f"behind it: {kinds['B']}, {kinds['BL']}/{kinds['BR']} (posts only)"
    pc = plan_mod.phys(c)
    ox, oy = (pc[0] + 0.5) * CELL, (pc[1] + 0.5) * CELL
    f = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[face]
    lft = (-f[1], f[0])

    def at(across, behind):
        return (ox + across * lft[0] - behind * f[0], oy + across * lft[1] - behind * f[1])

    def quad(a0, a1, b0, b1):
        """The rectangle across a0..a1 and behind b0..b1 (convex, any order round it)."""
        return [at(a0, b0), at(a1, b0), at(a1, b1), at(a0, b1)]

    fx = pal["fx"]
    trim = pal["trim"][0]
    wall = pal["wall"][0]
    glow = Surf(fx["glow"], S_LIGHT | S_TRANS66, 200)
    portal = Surf(fx["portal"], S_TRANS33 | S_FLOWING, 0, 1.0, (0, 0), 90)   # turned: s runs up, the streaks rise
    hidden = Surf(fx["portal"], S_NODRAW, 0)
    out = []
    across_deg = math.atan2(lft[1], lft[0])
    for side in (1, -1):
        px, py = at(side * POST_ACROSS, POST_BEHIND)
        # a hexagon with a flat face towards the portal (its vertices 30 degrees off the across line)
        # the posts run up through the lintel's height: its ends sit in them
        out.append(slab_poly(_poly(px, py, POST_R, 6, across_deg + math.pi / 6), z, z + H + 8, {"default": trim},
                             contents=C_SOLID | C_DETAIL, note="portal post"))
        inner = side * (POST_ACROSS - POST_R * math.cos(math.pi / 6))
        out.append(slab_poly(quad(inner - 2 * side, inner + 0.5 * side, POST_BEHIND - 4, POST_BEHIND + 4), z + 16,
                             z + H - 16, {"default": glow}, contents=C_MIST | C_DETAIL, note="portal glow"))
    # the lintel ends inside the posts (held at both ends - a lintel over the posts' outer faces measured «in the air»
    # where no slab stood under it, 06.11) and runs back onto the slab when there is one
    back = SLAB_TO if slab else POST_BEHIND + 5
    out.append(slab_poly(quad(-(POST_ACROSS + 6), POST_ACROSS + 6, POST_BEHIND - 5, back), z + H, z + H + 8,
                         {"default": trim}, contents=C_SOLID | C_DETAIL, note="portal lintel"))
    if slab:
        out.append(slab_poly(quad(-SLAB_HALF, SLAB_HALF, SLAB_FROM, SLAB_TO), z, z + H, {"default": wall},
                             contents=C_SOLID | C_DETAIL, note="portal slab"))
    out.append(slab_poly(quad(-PORTAL_HALF, PORTAL_HALF, PORTAL_FROM, PORTAL_TO), z + PORTAL_LOW, z + min(PORTAL_HIGH, H - 8),
                         {"default": hidden, "side": portal}, contents=C_MIST | C_DETAIL, note="portal sheet",
                         side_surf=lambda i, n: portal if abs(n[0] * f[0] + n[1] * f[1]) > 0.5 * math.hypot(*n)
                         else hidden))
    return out, ("frame" if slab else "posts"), why, face
