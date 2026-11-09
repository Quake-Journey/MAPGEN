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
# brief 32 (the PO 08.11: «для джампадов - круглых и наклонных нужно чтобы в студии были параметры для регулировки их
# размеров, по умолчанию как сейчас, но можно сделать меньше на 50% либо больше на 200% … по местам спавнов также …
# по телепортам также»): the request's sizes in percent, each its own key. Only the footprint grows - the heights the
# flights start from (PAD_TOP, PAD_WEDGE_LIFT) and the triggers stay as the planners proved them. A size over 100 is
# built only where every cell it reaches is the same flat floor of its own space and nobody else's; else the next
# smaller step (150, then 100 - today's, always built) and the record says so. The spawns' plate is new (nothing
# stood under a spawn before): «нет» by default, a step 8 high when asked.
SIZE_KEYS = {"disc": "pad_disc_size", "wedge": "pad_wedge_size", "tele": "tele_frame_size", "spawn": "spawn_plate_size"}
SIZE_STEPS = (200, 150, 100, 75, 50)
PLATE_R, PLATE_H = 44, 8            # a spawn's plate at 100 %: the pads' plinth


def asked_size(q: dict, what: str) -> int:
    """The size asked for `what` (disc | wedge | tele | spawn) in percent: 100 (the spawn's plate 0 - none) when not
    asked; else the nearest of SIZE_STEPS."""
    v = q.get(SIZE_KEYS[what])
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return 0 if what == "spawn" else 100
    if what == "spawn" and v <= 0:
        return 0
    return min(SIZE_STEPS, key=lambda s: (abs(s - v), -s))


def _poly(cx, cy, r, n, start):
    return [(cx + r * math.cos(start + 2 * math.pi * k / n), cy + r * math.sin(start + 2 * math.pi * k / n)) for k in range(n)]


def _centred(cx, cy, rot_deg, k: float = 1.0):
    """The texture shift that puts a 64-unit texture's middle on (cx, cy) for a face whose s axis, turned by rot_deg,
    runs along (cos, sin) and t along (sin, -cos) (Quake II's map format on a floor-like face) - drawn `k` times its
    size (brief 32: a pad twice as big keeps one ring and one set of arrows)."""
    a = math.radians(rot_deg)
    s = (cx * math.cos(a) + cy * math.sin(a)) / k
    t = (cx * math.sin(a) - cy * math.cos(a)) / k
    return (round((FX_TEX / 2 - s) % FX_TEX, 2), round((FX_TEX / 2 - t) % FX_TEX, 2))


def pad_kind(pitch: float) -> str:
    """«disc» for a pad flying up steeply, else «wedge»."""
    return "disc" if abs(pitch) >= STEEP else "wedge"


def pad_brushes(pal: dict, cell, zf: int, pitch: float, yaw: float, k: float = 1.0) -> tuple[list, str]:
    """The look of one pad at physical cell `cell` with floor zf: (brushes, «disc» | «wedge»), `k` times its size
    across (brief 32; the heights stay - the flight starts from them)."""
    fx = pal["fx"]
    trim = pal["trim"][0]
    cx, cy = (cell[0] + 0.5) * CELL, (cell[1] + 0.5) * CELL
    out = [slab_poly(_poly(cx, cy, PLINTH_R * k, 8, math.pi / 8), zf, zf + PLINTH_H, {"default": trim},
                     contents=C_SOLID | C_DETAIL, note="pad plinth")]
    z0 = zf + PLINTH_H
    if pad_kind(pitch) == "disc":
        ring = Surf(fx["padring"], S_LIGHT, 300, k, _centred(cx, cy, 0, k), 0)
        out.append(slab_poly(_poly(cx, cy, DISC_R * k, 16, 0.0), z0, z0 + DISC_H, {"default": trim, "+z": ring},
                             contents=C_SOLID | C_DETAIL, note="pad disc"))
        return out, "disc"
    u = (math.cos(math.radians(yaw)), math.sin(math.radians(yaw)))
    v = (-u[1], u[0])
    h = WEDGE_HALF * k
    sq = [(cx + a * u[0] * h + b * v[0] * h, cy + a * u[1] * h + b * v[1] * h) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]

    def top(x, y, lift=0.0):
        along = (x - cx) * u[0] + (y - cy) * u[1]          # -h at the near end .. +h at the far one
        return z0 + WEDGE_LOW + (along + h) / (2 * h) * (WEDGE_HIGH - WEDGE_LOW) + lift

    rot = round((yaw + ARROW_TURN) % 360, 2)
    arrow = Surf(fx["padarrow"], 0, 0, k, _centred(cx, cy, rot, k), rot)
    out.append(slab_poly(sq, z0, top, {"default": trim, "+z": arrow}, contents=C_SOLID | C_DETAIL, note="pad wedge"))
    # the sheet over it: the arrows again, translucent, scrolling along the flight (FLOWING moves a texture to +s)
    flow = Surf(fx["flowarrow"], S_TRANS33 | S_FLOWING, 0, k, _centred(cx, cy, rot, k), rot)
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


FACES = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}


def _frame_shapes(c, face: int, k: float, slab: bool) -> dict:
    """Brief 32: the frame's pieces at plan key c facing `face`, `k` times their size, as polygons in x, y - what the
    brushes are built from and what the footprint is read from: {"posts": [p, p], "glow": [p, p], "lintel": p,
    "slab": p, "portal": p}. At k 1 exactly the pieces of 3.53..3.58."""
    pc = plan_mod.phys(c)
    ox, oy = (pc[0] + 0.5) * CELL, (pc[1] + 0.5) * CELL
    f = FACES[face]
    lft = (-f[1], f[0])

    def at(across, behind):
        return (ox + across * lft[0] - behind * f[0], oy + across * lft[1] - behind * f[1])

    def quad(a0, a1, b0, b1):
        """The rectangle across a0..a1 and behind b0..b1 (convex, any order round it)."""
        return [at(a0, b0), at(a1, b0), at(a1, b1), at(a0, b1)]

    across_deg = math.atan2(lft[1], lft[0])
    out = {"posts": [], "glow": []}
    for side in (1, -1):
        px, py = at(side * POST_ACROSS * k, POST_BEHIND * k)
        # a hexagon with a flat face towards the portal (its vertices 30 degrees off the across line)
        out["posts"].append(_poly(px, py, POST_R * k, 6, across_deg + math.pi / 6))
        inner = side * (POST_ACROSS - POST_R * math.cos(math.pi / 6)) * k
        out["glow"].append(quad(inner - 2 * k * side, inner + 0.5 * k * side, (POST_BEHIND - 4) * k, (POST_BEHIND + 4) * k))
    # the lintel ends inside the posts (held at both ends - a lintel over the posts' outer faces measured «in the air»
    # where no slab stood under it, 06.11) and runs back onto the slab when there is one
    back = SLAB_TO * k if slab else (POST_BEHIND + 5) * k
    out["lintel"] = quad(-(POST_ACROSS + 6) * k, (POST_ACROSS + 6) * k, (POST_BEHIND - 5) * k, back)
    out["slab"] = quad(-SLAB_HALF * k, SLAB_HALF * k, SLAB_FROM * k, SLAB_TO * k)
    out["portal"] = quad(-PORTAL_HALF * k, PORTAL_HALF * k, PORTAL_FROM * k, PORTAL_TO * k)
    return out


def _inside(poly, x, y) -> bool:
    """A point strictly inside a convex polygon (either winding)."""
    sign = 0
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        cr = (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)
        if abs(cr) < 1e-9:
            return False
        s_ = 1 if cr > 0 else -1
        if sign and s_ != sign:
            return False
        sign = s_
    return True


def cells_under(c, polys) -> set:
    """Brief 32: the plan keys (on c's layer) whose cell a polygon's inside reaches, sampled every 4 units."""
    pc = plan_mod.phys(c)
    out = set()
    for poly in polys:
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        x = min(xs) + 2
        while x < max(xs):
            y = min(ys) + 2
            while y < max(ys):
                if _inside(poly, x, y):
                    out.add((c[0] + int(x // CELL) - pc[0], c[1] + int(y // CELL) - pc[1]))
                y += 4
            x += 4
    return out


def frame_fit(P, c, busy: set, k: float, held: set = frozenset()):
    """Brief 32: where a frame `k` (> 1) times its size stands round the teleporter's disc at plan key c - (face, slab,
    H, cells) - or None. Every cell its posts, lintel, glow and portal reach is the disc's own flat floor at its height
    (none of `busy` or `held`, not in front of a doorway) or a wall; the slab goes up when its cells are too; an open
    front of the same space; the ceiling over all of it 16 over the frame, never under 120."""
    sid = P.owner.get(c)
    s = P.spaces[sid]
    z = s.floor[c][0]
    doors = {d_ for d in P.doors for d_ in d.cells}
    mouths = {(x + dx, y + dy) for (x, y) in doors for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}

    def ok(n) -> bool:
        if n == c:
            return True
        kind = _kind(P, n, z, sid, busy | set(held))
        return kind == "wall" or (kind == "floor" and n not in mouths)

    first = plan_mod.facing(P, c)
    for face in (first, (first + 90) % 360, (first + 270) % 360, (first + 180) % 360):
        f_ = FACES[face]
        front = (c[0] + f_[0], c[1] + f_[1])
        if P.owner.get(front) != sid or front in P.voids:
            continue
        sh = _frame_shapes(c, face, k, True)
        main = cells_under(c, sh["posts"] + sh["glow"] + [sh["portal"], _frame_shapes(c, face, k, False)["lintel"]])
        if not all(ok(n) for n in main):
            continue
        back = cells_under(c, [sh["slab"], sh["lintel"]])
        slab = all(ok(n) for n in back)
        cells = main | (back if slab else set())
        ceil = min(P.cell_ceil.get(n, s.ceil) if P.owner.get(n) == sid else s.ceil for n in cells | {c})
        H = min(FRAME_H * k, ceil - z - 16)
        if H < 120:
            continue
        return face, slab, H, cells - {c}
    return None


def teleporter_frame(P, pal: dict, c, busy: set, k: float = 1.0, fit=None) -> tuple[list, str, str, int]:
    """The frame round a teleporter's disc at plan key c: (brushes, «frame» | «posts» | «bare», why, facing). Brief 32:
    `k` times its size - over 1 only with the `fit` the plan found for it (frame_fit), else as 3.58 placed it."""
    sid = P.owner.get(c)
    s = P.spaces[sid]
    z = s.floor[c][0]
    if fit is not None:
        face, slab, H, _cells = fit
        why = "" if slab else "behind it: no room for the slab (posts only)"
    else:
        k = min(k, 1.0)
        # the facing the disc's space opens to first; when a side there is another room (its wall on the cell's edge),
        # the other ways round with an open front (a third of the rooms maps' discs came out bare by the first alone,
        # 06.11)
        first = plan_mod.facing(P, c)
        for face in (first, (first + 90) % 360, (first + 270) % 360, (first + 180) % 360):
            face, cells = frame_cells(P, c, face)
            kinds = {k_: _kind(P, v, z, sid, busy) for k_, v in cells.items()}
            f_ = FACES[face]
            front = (c[0] + f_[0], c[1] + f_[1])
            if kinds["L"] != "other" and kinds["R"] != "other" and P.owner.get(front) == sid and front not in P.voids:
                break
        else:
            face, cells = frame_cells(P, c, first)
            kinds = {k_: _kind(P, v, z, sid, busy) for k_, v in cells.items()}
        ceil = min(P.cell_ceil.get(k_, s.ceil) if P.owner.get(k_) == sid else s.ceil for k_ in [c] + list(cells.values()))
        if kinds["L"] == "other" or kinds["R"] == "other":
            return [], "bare", "beside it: " + ", ".join(f"{k_} {kinds[k_]}" for k_ in ("L", "R") if kinds[k_] == "other"), face
        # the frame as tall as the room lets it: 160 posts, lower under a low ceiling (a tower's storeys of 160), never
        # under 120 (the portal's own height) - k times both for a smaller frame (brief 32)
        H = min(FRAME_H * k, ceil - z - 16)
        if H < 120 * k:
            return [], "bare", f"the ceiling {ceil - z} over the floor (the frame needs {round(136 * k)})", face
        slab = kinds["B"] == "wall" or (kinds["B"] == "floor" and "floor" in (kinds["BL"], kinds["BR"]))
        why = "" if slab else f"behind it: {kinds['B']}, {kinds['BL']}/{kinds['BR']} (posts only)"
    f = FACES[face]
    sh = _frame_shapes(c, face, k, slab)
    fx = pal["fx"]
    trim = pal["trim"][0]
    wall = pal["wall"][0]
    glow = Surf(fx["glow"], S_LIGHT | S_TRANS66, 200)
    portal = Surf(fx["portal"], S_TRANS33 | S_FLOWING, 0, k, (0, 0), 90)   # turned: s runs up, the streaks rise
    hidden = Surf(fx["portal"], S_NODRAW, 0)
    out = []
    lid = 8 * k                                                        # the lintel's thickness
    for post, strip in zip(sh["posts"], sh["glow"]):
        # the posts run up through the lintel's height: its ends sit in them
        out.append(slab_poly(post, z, z + H + lid, {"default": trim}, contents=C_SOLID | C_DETAIL, note="portal post"))
        out.append(slab_poly(strip, z + 16 * k, z + H - 16 * k, {"default": glow}, contents=C_MIST | C_DETAIL,
                             note="portal glow"))
    out.append(slab_poly(sh["lintel"], z + H, z + H + lid, {"default": trim}, contents=C_SOLID | C_DETAIL,
                         note="portal lintel"))
    if slab:
        out.append(slab_poly(sh["slab"], z, z + H, {"default": wall}, contents=C_SOLID | C_DETAIL, note="portal slab"))
    out.append(slab_poly(sh["portal"], z + PORTAL_LOW * k, z + min(PORTAL_HIGH * k, H - 8),
                         {"default": hidden, "side": portal}, contents=C_MIST | C_DETAIL, note="portal sheet",
                         side_surf=lambda i, n: portal if abs(n[0] * f[0] + n[1] * f[1]) > 0.5 * math.hypot(*n)
                         else hidden))
    return out, ("frame" if slab else "posts"), why, face


# brief 34 (the PO 08.11: «нужно проявлять мозги, а не просто напихивать на уровне кучу повторяемых объектов, которые
# смотреть невозможно»): like things standing together - the .map's own words (its notes, its entities). Lamps are not
# among them: people's maps hang their lights in rows (up to 14 within four cells on q2duel5, 5..11 on most of them).
# People's pads: one a place (pro_q2t4 527 u apart at least); q2_q3dm17's one hub - a pad up and four out in a cross -
# is a composition our generator does not build.
LIKE_KINDS = {"pad": "trigger_push", "teleporter": "misc_teleporter", "pedestal": "pedestal", "column": "pillar",
              "panel": "decor", "plate": "spawn plate", "landing": "pad landing", "podium": "podium"}
REPEAT_MAX = 2          # like things within REPEAT_CELLS of one on its floor, itself included
REPEAT_CELLS = 4


def crowded(placed: list, q: tuple) -> bool:
    """Brief 34: would a like thing at q make more than REPEAT_MAX of them within REPEAT_CELLS of one on its floor (q's
    own neighbourhood or a neighbour's)? `placed` and q: (x, y, z)."""
    reach = REPEAT_CELLS * CELL

    def near(a, b):
        return abs(a[2] - b[2]) < 64 and math.hypot(a[0] - b[0], a[1] - b[1]) <= reach
    around = [p for p in placed if near(p, q)]
    if len(around) + 1 > REPEAT_MAX:
        return True
    return any(sum(1 for o in placed if near(o, p)) + 1 > REPEAT_MAX for p in around)


def measure_map(text: str) -> dict:
    """Brief 34: on a .map the builder wrote - the nearest two pads on one floor (|dz| < 64; their triggers' middles)
    and, per kind of like thing, the most of them within four cells of one on its floor:
    {"pads_min_apart": u | None, "repeats": {kind: count}, "worst": (kind, count)}."""
    import re
    pts = {k: [] for k in LIKE_KINDS}
    # the builder's .map («// brush N» before each brush) and the engine's own (no such line)
    for m in re.finditer(r'"classname" "(trigger_push|misc_teleporter)"\n((?:"[^"]*" "[^"]*"\n)*)(?:// brush \d+\n)?(?:\{\n((?:\(.*\n)+)\})?', text):
        cls, keys, faces = m.group(1), m.group(2), m.group(3)
        if cls == "trigger_push" and faces:
            v = [tuple(map(float, q)) for q in re.findall(r"\( (\S+) (\S+) (\S+) \)", faces)]
            pts["pad"].append(((min(p[0] for p in v) + max(p[0] for p in v)) / 2, (min(p[1] for p in v) + max(p[1] for p in v)) / 2,
                               min(p[2] for p in v)))
        elif cls == "misc_teleporter":
            o = re.search(r'"origin" "(\S+) (\S+) (\S+)"', keys)
            if o:
                pts["teleporter"].append(tuple(float(o.group(i)) for i in (1, 2, 3)))
    notes = {v: k for k, v in LIKE_KINDS.items() if k not in ("pad", "teleporter")}
    for m in re.finditer(r"^// brush \d+ ([a-z ]+)\n\{\n((?:\(.*\n)+)\}", text, re.M):
        kind = notes.get(m.group(1))
        if not kind:
            continue
        v = [tuple(map(float, q)) for q in re.findall(r"\( (\S+) (\S+) (\S+) \)", m.group(2))]
        pts[kind].append(((min(p[0] for p in v) + max(p[0] for p in v)) / 2, (min(p[1] for p in v) + max(p[1] for p in v)) / 2,
                          min(p[2] for p in v)))
    reach = REPEAT_CELLS * CELL
    repeats = {}
    for kind, ps in pts.items():
        repeats[kind] = max((sum(1 for q in ps if abs(q[2] - p[2]) < 64 and math.hypot(q[0] - p[0], q[1] - p[1]) <= reach)
                             for p in ps), default=0)
    pads = pts["pad"]
    gaps = [math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(pads) for b in pads[i + 1:] if abs(a[2] - b[2]) < 64]
    worst = max(repeats.items(), key=lambda kv: kv[1], default=("pad", 0))
    return {"pads_min_apart": round(min(gaps)) if gaps else None, "repeats": repeats, "worst": list(worst)}


def measure_bsp_pads(bsp) -> dict:
    """Brief 34: the pads on a compiled map (any map: its trigger_push models' boxes) - the nearest two on one floor and
    the most within four cells of one: {"pads_min_apart": u | None, "pads_together": n}. A .map the engine rewrote gives
    its faces by three points of each plane (not its corners), so a map's pads are read from its BSP."""
    import mapgen_map_survey as sv
    w = sv.World(str(bsp))
    pads = []
    for e in w.ents:
        if e.get("classname") == "trigger_push" and e.get("model", "").startswith("*"):
            m = w.bsp.models[int(e["model"][1:])]
            pads.append(((m.mins[0] + m.maxs[0]) / 2, (m.mins[1] + m.maxs[1]) / 2, m.mins[2]))
    gaps = [math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(pads) for b in pads[i + 1:] if abs(a[2] - b[2]) < 64]
    most = max((sum(1 for q in pads if abs(q[2] - p[2]) < 64 and math.hypot(q[0] - p[0], q[1] - p[1]) <= REPEAT_CELLS * CELL)
                for p in pads), default=0)
    return {"pads_min_apart": round(min(gaps)) if gaps else None, "pads_together": most}


def landing_mark(pal: dict, cell, zf: int) -> list:
    """Brief 34: a pad's landing - a thin octagon (2 high) of the trim with the style's lamp on top, 20 across the
    cell's middle: lit, flat underfoot, not a pad (no ring, no plinth)."""
    cx, cy = (cell[0] + 0.5) * CELL, (cell[1] + 0.5) * CELL
    # the lamp's look, not its light (a lit plate a landing made the screen brighter than people's maps)
    top = Surf(pal["lamp"][0].tex, 0, 0)
    return [slab_poly(_poly(cx, cy, 20, 8, math.pi / 8), zf, zf + 2, {"default": pal["trim"][0], "+z": top},
                      contents=C_SOLID | C_DETAIL, note="pad landing")]


def spawn_plate(pal: dict, cell, zf: int, k: float) -> list:
    """Brief 32: the plate under a spawn - an octagon of the trim, PLATE_H (a step) high, PLATE_R times k across."""
    cx, cy = (cell[0] + 0.5) * CELL, (cell[1] + 0.5) * CELL
    trim = pal["trim"][0]
    return [slab_poly(_poly(cx, cy, PLATE_R * k, 8, math.pi / 8), zf, zf + PLATE_H, {"default": trim},
                      contents=C_SOLID | C_DETAIL, note="spawn plate")]


def disc_cells(c, r: float) -> set:
    """Brief 32: the plan keys round c (its layer) a disc of radius r about c's middle reaches into, c itself aside."""
    out = set()
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            if (dx, dy) == (0, 0):
                continue
            ddx, ddy = max(0, abs(dx) * CELL - CELL / 2), max(0, abs(dy) * CELL - CELL / 2)
            if math.hypot(ddx, ddy) < r - 0.5:
                out.add((c[0] + dx, c[1] + dy))
    return out


def _flat_own(P, n, sid, z) -> bool:
    """A cell a plinth or a plate may reach into: the same flat floor of space sid at z, or rock (a wall - the piece
    runs on under it, at most 56 into a 64 cell) - not air (an open space's void, a tower's atrium), not a pit, not
    another room's floor or another height."""
    if n in P.voids:
        return False
    o = P.owner.get(n)
    if o is None:
        return P.params.get("shape") != "space"
    if o != sid:
        return False
    f = P.spaces[sid].floor.get(n)
    return f is not None and f[1] == "flat" and f[0] == z


def _air_beside(P, c, z) -> int:
    """Brief 34: how many of a cell's four neighbours are air at its height - open air (an atrium, a stair's opening, an
    island's void) or a floor well below."""
    n_ = 0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (c[0] + dx, c[1] + dy)
        o = P.owner.get(n)
        if n in P.voids or (o is None and P.params.get("shape") == "space"):
            n_ += 1
        elif o is not None:
            f = P.spaces[o].floor.get(n)
            if f is not None and f[0] < z - 16:
                n_ += 1
    return n_


def plan_sizes(P) -> None:
    """Brief 32: the size each pad, teleporter frame and spawn plate is built at (P.fx_size), and the cells the bigger
    ones reach (P.fx_cells: the lamps, columns, round shapes and the walls' dressing leave them alone - every later
    stage holds them). Run by the planners once the items and spawns are placed, before the dressing.
    * a pad (disc or wedge) over 100 %: its plinth's cells all the pad's own flat floor at its height or rock, and
      nobody's (items, spawns, movers, doorways, buttons, pits, liquids, chamfers, round shapes, other fixtures) - else
      150, else 100 (as 3.58: always built); at 100 % and under as 3.58;
    * a teleporter frame over 100 %: frame_fit - else the next step; at 100 % and under as 3.58 (at build);
    * a spawn plate (none unless asked): its cells the spawn's own flat floor at its height or rock, and not a mover, a
      pit, a liquid or another fixture - else the next smaller step, down to 50; none fits - no plate there.
    Every step down is said in P.metrics["fx_sizes"]["said"] (the description's line)."""
    q = P.params
    asked = {w: asked_size(q, w) for w in SIZE_KEYS}
    P.fx_size = {}
    P.fx_cells = set()
    said = []
    base = busy_cells(P) | {c for (c, *_r) in P.chamfers} | set(getattr(P, "rounded", ()))
    base |= {c for (c, *_r) in P.pillars} | {c for (cells, *_w) in P.windows for c in cells}
    movers = base - {c for (_cls, c, _z, _n) in P.items} - {c for (c, _z, _a) in P.spawns}
    steps_down = lambda a: [s_ for s_ in SIZE_STEPS if s_ <= a]  # noqa: E731
    built = {"disc": [], "wedge": [], "tele": [], "spawn": []}
    for i, (a, t, _T, _sp, pitch, _yaw, zf) in enumerate(P.pads):
        kind = pad_kind(pitch)
        want = asked[kind]
        got = want
        if want > 100:
            sid = P.owner.get(a)
            got = 100
            for s_ in steps_down(want):
                if s_ <= 100:
                    break
                cells = disc_cells(a, PLINTH_R * s_ / 100)
                if all(_flat_own(P, n, sid, zf) and n not in base and n not in P.fx_cells for n in cells):
                    got = s_
                    P.fx_cells |= cells
                    break
        # brief 34: a 100 % plinth lips over its cell by 12 - over air on two sides (a stair's opening beside a gallery's
        # edge over the atrium) a tenth of it hangs (the fixtures check, 08.11): three quarters there, inside its cell
        if got == 100 and _air_beside(P, a, zf) >= 2:
            got = 75
        P.fx_size[("pad", i)] = got
        built[kind].append(got)
    want = asked["tele"]
    for k_, (a, b_, _da, _db) in enumerate(P.teleports):
        for src in (a, b_):
            got, fit = min(want, 100), None
            if want > 100:
                for s_ in steps_down(want):
                    if s_ <= 100:
                        break
                    fit = frame_fit(P, src, busy_cells(P), s_ / 100, held=base | P.fx_cells)
                    if fit is not None:
                        got = s_
                        P.fx_cells |= fit[3]
                        break
            P.fx_size[("tele", src)] = (got, fit)
            built["tele"].append(got)
    want = asked["spawn"]
    if want:
        for i, (c, z, _ang) in enumerate(P.spawns):
            sid = P.owner.get(c)
            got = 0
            for s_ in steps_down(want):
                cells = disc_cells(c, PLATE_R * s_ / 100)
                if all(_flat_own(P, n, sid, z) and n not in movers and n not in P.fx_cells for n in cells):
                    got = s_
                    P.fx_cells |= cells
                    break
            P.fx_size[("spawn", i)] = got
            built["spawn"].append(got)
    words = {"disc": ("круглых джампадов", "round jump pads"), "wedge": ("наклонных джампадов", "slanted jump pads"),
             "tele": ("рам телепортов", "teleporter frames"), "spawn": ("площадок под точками появления",
                                                                     "plates under the spawn points")}
    for w, got in built.items():
        short = [g for g in got if g < asked[w]]
        if short and asked[w] > 100 or w == "spawn" and short:
            ru, en = words[w]
            smaller = sorted(set(short), reverse=True)
            said.append(plan_mod.say(
                f"{len(short)} из {len(got)} {ru} меньше заказанных {asked[w]} %: "
                + ", ".join(f"{g} %" if g else "без площадки" for g in smaller) + " — рядом не хватило ровного пола",
                f"{len(short)} of {len(got)} {en} smaller than the {asked[w]} % asked: "
                + ", ".join(f"{g} %" if g else "no plate" for g in smaller) + " - not enough level floor round them"))
    P.metrics["fx_sizes"] = {"asked": asked, "built": built, "said": said}
