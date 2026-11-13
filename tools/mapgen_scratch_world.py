r"""Brief 19: a skeleton made into brushes - the rock derived from the air, every face dressed by what it faces.

Per 64-unit cell the plan holds spans of air: a space's floor to its ceiling (a stair cell's from its lower step), a
door's through a wall, a window's. Every cell within one of an air cell is rock wherever it holds no air, from one
floor-thickness under the lowest floor to one over the highest ceiling, so the map is sealed by construction. Rock
of one height range with the same air under and over it merges into larger boxes; each face takes the texture of the
space it faces - a floor's top, a ceiling's (or the sky's) underside, a wall's side, a door's frame - by the length of
air it borders. The pieces a box cannot be come after: the upper step of each stair cell, chamfered corners, pillars,
lamp panels under the lights; then the entities.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from mapgen_scratch_build import (CELL, Entity, Brush, Surf, box, face, prism_tri, prism_poly, wedge, C_SOLID, C_WINDOW, C_DETAIL,  # noqa: E402
                                  C_TRANSLUCENT)

# the glass of the accepted windows (mapgen_geometry_edit.c WINDOW_TINTS): texture, translucency flag
TINTS = [("e2u3/window5_1", 0x10), ("e2u2/wndow1_1", 0x20), ("e3u3/windowc1_7", 0x10), ("e1u1/window1", 0x20),
         ("e1u1/wndow0_1", 0x10), ("e1u2/wndow1_2", 0x20), ("e2u3/window1", 0x10)]


def convex(planes, surf, contents=0, note="") -> Brush:
    """A brush from its planes: each (three points on it, the outward normal)."""
    b = Brush(note=note)
    for pts, out in planes:
        b.faces.append(face(pts, out, surf.tex, contents, surf.flags, surf.value, surf.scale))
    return b


def window_pieces(cells, z0, z1, kind, tint, wall_surf, along) -> list:
    """A window's glass and outline in its wall cells (`along` - the axis the wall runs on, its thickness across):
    the pane 4 u thick in the wall's middle; an arch's two top corners solid (the pane cut by their diagonals), a
    slit's two jambs (24 u of glass), a box's and a band's plain opening."""
    xs, ys = [c[0] for c in cells], [c[1] for c in cells]
    ax = along == "x"
    tex, flag = TINTS[tint % len(TINTS)]
    glass = Surf(tex, flag, 0)
    u0 = (min(xs) if ax else min(ys)) * CELL
    u1 = ((max(xs) if ax else max(ys)) + 1) * CELL
    t_mid = (ys[0] if ax else xs[0]) * CELL + CELL // 2
    t0, t1 = t_mid - 32, t_mid + 32

    def P3(u, t, z):
        return (u, t, z) if ax else (t, u, z)

    def N(nu, nt, nz):
        return (nu, nt, nz) if ax else (nt, nu, nz)
    out = []
    if kind == "slit":
        j = (u1 - u0 - 24) // 2
        for a_, b_ in ((u0, u0 + j), (u1 - j, u1)):
            lo, hi = P3(a_, t0, z0), P3(b_, t1, z1)
            out.append(box((min(lo[0], hi[0]), min(lo[1], hi[1]), z0), (max(lo[0], hi[0]), max(lo[1], hi[1]), z1),
                           {"default": wall_surf}, note="window jamb"))
        u0, u1 = u0 + j, u1 - j
    pane = [((P3(u0, t0, z0), P3(u0, t1, z0), P3(u0, t0, z1)), N(-1, 0, 0)),
            ((P3(u1, t0, z0), P3(u1, t1, z0), P3(u1, t0, z1)), N(1, 0, 0)),
            ((P3(u0, t_mid - 2, z0), P3(u1, t_mid - 2, z0), P3(u0, t_mid - 2, z1)), N(0, -1, 0)),
            ((P3(u0, t_mid + 2, z0), P3(u1, t_mid + 2, z0), P3(u0, t_mid + 2, z1)), N(0, 1, 0)),
            ((P3(u0, t0, z0), P3(u1, t0, z0), P3(u0, t1, z0)), N(0, 0, -1)),
            ((P3(u0, t0, z1), P3(u1, t0, z1), P3(u0, t1, z1)), N(0, 0, 1))]
    if kind == "arch":
        r = min(32, (u1 - u0) // 2)
        s2 = 0.7071
        for (ua, sign) in ((u0, 1), (u1, -1)):
            ub = ua + sign * r
            tri = [((P3(ua, t0, z1), P3(ua, t1, z1), P3(ua, t0, z1 - r)), N(-sign, 0, 0)),
                   ((P3(ua, t0, z1), P3(ub, t0, z1), P3(ua, t1, z1)), N(0, 0, 1)),
                   ((P3(ua, t0, z1), P3(ub, t0, z1), P3(ua, t0, z1 - r)), N(0, -1, 0)),
                   ((P3(ua, t1, z1), P3(ub, t1, z1), P3(ua, t1, z1 - r)), N(0, 1, 0)),
                   ((P3(ub, t0, z1), P3(ua, t0, z1 - r), P3(ub, t1, z1)), N(sign * s2, 0, -s2))]
            out.append(convex(tri, wall_surf, note="window arch"))
            pane.append(((P3(ub, t0, z1), P3(ua, t0, z1 - r), P3(ub, t1, z1)), N(-sign * s2, 0, s2)))
    out.append(convex(pane, glass, C_WINDOW | C_TRANSLUCENT, note="glass"))
    return out

C_LADDER = 0x20000000
SUN_LIGHT = 35          # the sun's light when the style's maps give none (brief 20 D3)
SUN_AMBIENT = 5
TONES = {"warm": (1.0, 0.86, 0.68), "cold": (0.74, 0.86, 1.0), "neutral": (1.0, 0.96, 0.9)}
# decorations per wall cell: none, few, default, many (brief 19 §4 «Украшения на стенах»)
DECOR_EVERY = {"none": 0, "few": 9, "some": 5, "default": 0, "many": 3}
import mapgen_scratch_plan as plan_mod  # noqa: E402


def detail(pal: dict, k: int):
    """The k-th detail texture of the style (its trims and accents), round the list when it is shorter."""
    t = pal.get("trim") or [pal["wall"][0]]
    return t[k % len(t)]


def space_slots(P, pal: dict | None = None) -> dict:
    """Brief 21 F1: which wall texture each space wears - the spaces of a kind take the style's walls in turn (halls
    from the first, rooms from the second, corridors from the third), so a map of four wall textures shows all four;
    3.42 gave every hall one wall, every room another (4..8 textures on a map, people's 9..38). Returns
    {space id: (wall slot, floor slot)}: the floors keep the halls on the first (people's maps lay one floor on most
    of their area), the rooms take the others in turn, the corridors the last."""
    out, seen = {}, {}
    base = {"hall": 0, "room": 1, "corridor": 2}
    live = sorted((s for s in P.spaces if not s.solid), key=lambda s: (-s.area(), s.id))
    if pal and pal.get("wall_w") and pal.get("floor_w"):
        # brief 21: by the source map's shares - each space, the largest first, takes the texture furthest under its
        # share of the area given so far (halls the dominant one, the small spaces the accents)
        def deal(weights):
            tot = sum(weights) or 1.0
            want = [w_ / tot for w_ in weights]
            got = [0.0] * len(weights)
            area = sum(s.area() for s in live) or 1
            res = {}
            for s in live:
                k = max(range(len(want)), key=lambda i: (want[i] - got[i] / area, -i))
                res[s.id] = k
                got[k] += s.area()
            return res
        wl, fl = deal(pal["wall_w"]), deal(pal["floor_w"])
        return {sid: (wl[sid], ("w", fl[sid])) for sid in wl}
    for s in live:
        k = base.get(s.kind, 1)
        n = seen.get(s.kind, 0)
        out[s.id] = (k + n, 0 if s.kind == "hall" else -1 if s.kind == "corridor" else 1 + n)
        seen[s.kind] = n + 1
    return out


def floor_slot(slot, n: int) -> int:
    if isinstance(slot, tuple):
        return slot[1] % max(1, n)
    if n <= 1 or slot == 0:
        return 0
    if slot < 0:
        return n - 1
    return 1 + (slot - 1) % (n - 1)


def dress_walls(P, pal: dict, spans: dict, spaces: dict, plat_cells: dict, lintels: set | None = None) -> list:
    """Brief 20 D4, the look: what people's maps put on a wall and nobody's generator did - a skirting along the floor
    and a cornice under the ceiling (8 proud), pilasters at a hall's corners and every five cells along its walls (16
    proud, floor to ceiling), beams across a high hall's ceiling, and a frame round a doorway (jambs and a lintel 8
    proud on both faces; every other doorway with its top corners cut on the diagonal, an arch's outline). Each piece
    touches a wall, a floor or a ceiling - nothing hangs (the PO, 04.11). Cells holding an item, a spawn or a mover are
    left plain: a brush beside a pickup made the engine's rebuild disagree with the base (04.11, ERR_BASELINE)."""
    # brief 21 F1: each kind of piece its own detail texture of the source map - the skirting and the cornice its
    # first trim, the pilasters and beams the second, the doorway frames the third (3.42 wore one trim on all of it)
    trim = {"default": detail(pal, 0)}
    post = {"default": detail(pal, 1)}
    frame = {"default": detail(pal, 2)}
    # detail, as people's trims are: solid to a player, but they do not cut the map's space into pieces (structural,
    # the trial FFA-8's base took the engine over 15 minutes to plan - the duel 78 s)
    DET = C_SOLID | C_DETAIL
    held = ({c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns} | set(P.no_items)
            | {c for (c, *_r) in P.chamfers} | {c for (c, *_r) in P.pillars} | set(plat_cells)
            | set(getattr(P, "rounded", ())) | plan_mod.button_cells(P)
            | {c for (*_r, front) in P.ladders for c in front} | {c for d in P.doors for c in d.cells}
            | {c for (src, dst, *_r) in P.pads for c in (src, dst)} | {c for t in P.teleports for c in t}
            | set(getattr(P, "fx_cells", ())))     # brief 32: the cells a bigger pad, frame or plate reaches
    wet = {c for (cells, *_r) in P.liquids for c in cells}

    def rock(c, lo, hi):
        return not any(sp[0] < hi and sp[1] > lo for sp in spans.get(c, []))

    out = []
    runs = {}                                    # (kind, dir, boundary, z0, z1) -> [along...]
    for s in spaces.values():
        for c, f in s.floor.items():
            if c in wet or c in plat_cells:
                continue
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + d[0], c[1] + d[1])
                b = (c[0] + (1 if d[0] > 0 else 0)) * CELL if d[0] else (c[1] + (1 if d[1] > 0 else 0)) * CELL
                along = c[1] if d[0] else c[0]
                if f[1] == "flat" and rock(n, f[0] + 1, f[0] + 12):
                    runs.setdefault(("skirt", d, b, f[0], f[0] + 12), []).append(along)
                if not s.sky and any(sp[1] == s.ceil for sp in spans.get(c, [])) and rock(n, s.ceil - 12, s.ceil - 1):
                    runs.setdefault(("cornice", d, b, s.ceil - 12, s.ceil), []).append(along)
    for (kind, d, b, z0, z1), alongs in runs.items():
        alongs = sorted(set(alongs))
        start = prev = alongs[0]
        for a in alongs[1:] + [None]:
            if a is not None and a == prev + 1:
                prev = a
                continue
            u0, u1 = start * CELL, (prev + 1) * CELL
            t0, t1 = (b - 8, b) if (d[0] > 0 or d[1] > 0) else (b, b + 8)
            lo, hi = ((t0, u0, z0), (t1, u1, z1)) if d[0] else ((u0, t0, z0), (u1, t1, z1))
            out.append(box(lo, hi, trim, contents=DET, note=kind))
            if a is not None:
                start = prev = a
    for s in spaces.values():
        r = s.rect
        # a hall of a corridor's width (a corridor piece that took a bay in, brief 21) keeps its passage clear
        if s.kind != "hall" or min(r.w, r.h) < 4:
            continue
        top = s.ceil

        def flat_at_base(c):
            f = s.floor.get(c)
            return f is not None and f[1] == "flat" and f[0] == s.base and c not in held and c not in wet
        # pilasters: the main rectangle's corners, and every five cells along each wall
        for (c, dx, dy) in (((r.x0, r.y0), -1, -1), ((r.x1 - 1, r.y0), 1, -1), ((r.x0, r.y1 - 1), -1, 1),
                            ((r.x1 - 1, r.y1 - 1), 1, 1)):
            if flat_at_base(c) and rock((c[0] + dx, c[1]), s.base, top) and rock((c[0], c[1] + dy), s.base, top):
                x0 = c[0] * CELL if dx < 0 else (c[0] + 1) * CELL - 24
                y0 = c[1] * CELL if dy < 0 else (c[1] + 1) * CELL - 24
                out.append(box((x0, y0, s.base), (x0 + 24, y0 + 24, top), post, contents=DET, note="pilaster"))
        for side in ("s", "n", "w", "e"):
            cells = ([(x, r.y0) for x in range(r.x0 + 2, r.x1 - 2, 5)] if side == "s" else
                     [(x, r.y1 - 1) for x in range(r.x0 + 2, r.x1 - 2, 5)] if side == "n" else
                     [(r.x0, y) for y in range(r.y0 + 2, r.y1 - 2, 5)] if side == "w" else
                     [(r.x1 - 1, y) for y in range(r.y0 + 2, r.y1 - 2, 5)])
            d = {"s": (0, -1), "n": (0, 1), "w": (-1, 0), "e": (1, 0)}[side]
            for c in cells:
                if not flat_at_base(c) or not rock((c[0] + d[0], c[1] + d[1]), s.base, top):
                    continue
                cx, cy = c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2
                if d[0]:
                    xw = (c[0] + 1) * CELL if d[0] > 0 else c[0] * CELL
                    x0, x1 = (xw - 16, xw) if d[0] > 0 else (xw, xw + 16)
                    out.append(box((x0, cy - 16, s.base), (x1, cy + 16, top), post, contents=DET, note="pilaster"))
                else:
                    yw = (c[1] + 1) * CELL if d[1] > 0 else c[1] * CELL
                    y0, y1 = (yw - 16, yw) if d[1] > 0 else (yw, yw + 16)
                    out.append(box((cx - 16, y0, s.base), (cx + 16, y1, top), post, contents=DET, note="pilaster"))
        # beams across a high roofed hall's shorter side, every four cells, wall to wall
        movers_here = any(c in s.floor for p in P.pads for c in p[:2]) or any(c in s.floor for t in P.teleports for c in t)
        if s.sky or top - s.base < 256 or min(r.w, r.h) < 5 or movers_here:
            continue
        wide = r.w >= r.h
        for k in range(3, (r.w if wide else r.h) - 2, 4):
            if wide:
                X = (r.x0 + k) * CELL
                under = [(r.x0 + k - 1, y) for y in range(r.y0, r.y1)] + [(r.x0 + k, y) for y in range(r.y0, r.y1)]
                ends = [(r.x0 + k - 1, r.y0 - 1), (r.x0 + k, r.y0 - 1), (r.x0 + k - 1, r.y1), (r.x0 + k, r.y1)]
            else:
                Y = (r.y0 + k) * CELL
                under = [(x, r.y0 + k - 1) for x in range(r.x0, r.x1)] + [(x, r.y0 + k) for x in range(r.x0, r.x1)]
                ends = [(r.x0 - 1, r.y0 + k - 1), (r.x0 - 1, r.y0 + k), (r.x1, r.y0 + k - 1), (r.x1, r.y0 + k)]
            if not all(P.owner.get(c) == s.id and c in s.floor and top - 24 - plan_mod.floor_top(s.floor[c]) >= 128
                       and any(sp[1] == top for sp in spans.get(c, [])) for c in under):
                continue
            if not all(rock(c, top - 24, top) for c in ends):
                continue
            if wide:
                out.append(box((X - 12, r.y0 * CELL, top - 24), (X + 12, r.y1 * CELL, top), post, contents=DET, note="beam"))
            else:
                out.append(box((r.x0 * CELL, Y - 12, top - 24), (r.x1 * CELL, Y + 12, top), post, contents=DET, note="beam"))
    # doorway frames on both faces; every other one with its top corners cut (an arch's outline)
    for i, d in enumerate(P.doors):
        if d.kind != "door" or d.mover or d.rj or not d.cells:
            continue
        xs, ys = [c[0] for c in d.cells], [c[1] for c in d.cells]
        # a doorway carrying two steps opens from its low end's steps to the top over its high end
        top_ = d.top or (d.z + 32 + plan_mod.DOOR_H if d.stair else d.z + plan_mod.DOOR_H)
        along_x = len(set(ys)) == 1 and (len(xs) > 1 or rock((xs[0], ys[0] - 1), d.z, top_) is False)
        if along_x:
            line, lo_u, hi_u = ys[0], min(xs), max(xs)
        else:
            line, lo_u, hi_u = xs[0], min(ys), max(ys)

        def C(u, t):
            return (u, t) if along_x else (t, u)
        L, R = lo_u * CELL, (hi_u + 1) * CELL
        for sgn in (-1, 1):
            # each face from its own room's floor (a doorway with steps joins two heights)
            front = [C(u, line + sgn) for u in range(lo_u - 1, hi_u + 2)]
            o0 = P.owner.get(front[0])
            f0 = spaces[o0].floor.get(front[0]) if o0 in spaces else None
            if f0 is None:
                continue
            zf = f0[0]
            ok = rock(C(lo_u - 1, line), zf, top_ + 16) and rock(C(hi_u + 1, line), zf, top_ + 16)
            for c in front:
                o = P.owner.get(c)
                f = spaces[o].floor.get(c) if o in spaces else None
                if not ok or f is None or f[1] != "flat" or f[0] != zf or c in held or c in wet or spaces[o].ceil < top_ + 24:
                    ok = False
                    break
            if not ok:
                continue
            face = (line + 1) * CELL if sgn > 0 else line * CELL
            t0, t1 = (face, face + 8) if sgn > 0 else (face - 8, face)

            def B(u0, u1, z0, z1, note):
                lo, hi = ((u0, t0, z0), (u1, t1, z1)) if along_x else ((t0, u0, z0), (t1, u1, z1))
                out.append(box(lo, hi, frame, contents=DET, note=note))
            B(L - 16, L, zf, top_ + 16, "door jamb")
            B(R, R + 16, zf, top_ + 16, "door jamb")
            B(L, R, top_, top_ + 16, "door lintel")
            if lintels is not None:
                lintels.add((i, sgn))
        # only where the wall stands on both sides of the opening at its top (04.11: a corner by an opening with air
        # beside it hung from the opening's top)
        if (i % 2 == 0 and R - L >= 64 and rock(C(lo_u - 1, line), top_ - 16, top_ + 16)
                and rock(C(hi_u + 1, line), top_ - 16, top_ + 16)):
            # the opening's top corners cut on the diagonal through the wall's thickness
            tw0, tw1 = line * CELL, (line + 1) * CELL
            r_ = 16
            s2 = 0.7071

            def P3(u, t, z):
                return (u, t, z) if along_x else (t, u, z)

            def N(nu, nt, nz):
                return (nu, nt, nz) if along_x else (nt, nu, nz)
            for (ua, sign) in ((L, 1), (R, -1)):
                ub = ua + sign * r_
                tri = [((P3(ua, tw0, top_), P3(ua, tw1, top_), P3(ua, tw0, top_ - r_)), N(-sign, 0, 0)),
                       ((P3(ua, tw0, top_), P3(ub, tw0, top_), P3(ua, tw1, top_)), N(0, 0, 1)),
                       ((P3(ua, tw0, top_), P3(ub, tw0, top_), P3(ua, tw0, top_ - r_)), N(0, -1, 0)),
                       ((P3(ua, tw1, top_), P3(ub, tw1, top_), P3(ua, tw1, top_ - r_)), N(0, 1, 0)),
                       ((P3(ub, tw0, top_), P3(ua, tw0, top_ - r_), P3(ub, tw1, top_)), N(sign * s2, 0, -s2))]
                out.append(convex(tri, frame["default"], contents=DET, note="door arch"))
    return out


# brief 34 follow-up: True draws a sky space's every rock underside as sky (the slab under a perch with it, 3.59/3.60's
# bug) and leaves a perch's well capped by its gallery's ceiling; check_mapgen_tower_ways.py's RED only
SKY_UNDERSIDES = False
# a pad's trigger: this far in from its cell's sides - 7 (8 before 3.61 put an axis-flying wedge's sides on its planes and
# the engine refused the base; check_mapgen_fixtures.py's RED sets 8)
PAD_TRIGGER_IN = 7

# Brief 36 (the PO 11.11, mg_new_91126 on 3.61: «баг с дверью в стене - у неё мерцает текстура при её движении»): a door
# was its doorway's whole cell, 64 across - the wall's own thickness - so its two broad faces lay in the wall's two
# planes and, rising 120 into the wall over the doorway, were drawn in one plane with the wall's faces. A door now stands
# DOOR_ACROSS thick in the middle of its wall, as people's are (q2dm3, q2dm8: 32; q2dm6: 16..80), and rises hidden in it.
# 64 gives back 3.60/3.61's door (the RED of tools/check_mapgen_doors.py).
DOOR_ACROSS = 32
# ... and its two ends 1 in from the doorway's ends, a fixed stop of the door's thickness standing in that unit from the
# floor to the opening's top: rising, the door's ends go up inside the wall over the doorway, never along a face of it
# seen from beyond the doorway's end - through a window there, or from a higher floor whose steps stand on the jamb (his
# request on 3.62's first build: 1 door of 8 each). 0 gives back the door's ends at the doorway's (the RED).
DOOR_END_IN = 1


def door_across(P, d) -> int | None:
    """The axis one walks through a door along (mapgen_scratch_plan.door_across)."""
    return plan_mod.door_across(P, d)


def door_box(P, d) -> tuple:
    """A moving door's box (lo, hi): along its wall the doorway's whole width, DOOR_ACROSS thick in the middle of the
    wall, from its floor DOOR_H up."""
    pcs_ = [plan_mod.phys(c) for c in d.cells]
    lo = [min(c[0] for c in pcs_) * CELL, min(c[1] for c in pcs_) * CELL, d.z]
    hi = [(max(c[0] for c in pcs_) + 1) * CELL, (max(c[1] for c in pcs_) + 1) * CELL, d.z + plan_mod.DOOR_H]
    ax = door_across(P, d)
    if ax is not None and hi[ax] - lo[ax] > DOOR_ACROSS:
        mid = (lo[ax] + hi[ax]) / 2
        lo[ax], hi[ax] = mid - DOOR_ACROSS / 2, mid + DOOR_ACROSS / 2
        along = 1 - ax
        lo[along] += DOOR_END_IN
        hi[along] -= DOOR_END_IN
    return tuple(lo), tuple(hi)


def door_stops(P, d) -> list:
    """The two fixed stops in the units a door leaves at its doorway's ends: (lo, hi) boxes, none for a door built a whole
    cell."""
    lo, hi = door_box(P, d)
    ax = door_across(P, d)
    if ax is None or not DOOR_END_IN or hi[ax] - lo[ax] >= CELL:
        return []
    along = 1 - ax
    out = []
    for end, sign in ((lo[along], -1), (hi[along], 1)):
        a_, b_ = list(lo), list(hi)
        if sign < 0:
            a_[along], b_[along] = end - DOOR_END_IN, end
        else:
            a_[along], b_[along] = end, end + DOOR_END_IN
        out.append((tuple(a_), tuple(b_)))
    return out


FIXTURE_GLOW = 100


def lamp_fixture(P, pal: dict, x: float, y: float, z: float, mount: tuple, lintels: set) -> list:
    """Brief 21 (brief 20 D4's lamps): the fixture of a wall lamp, its glowing face toward the room - under the
    cornice (it reaches the ceiling: held by the wall and the ceiling), on a post standing on the floor at the wall,
    or on a doorway's lintel (only where the lintel was built). Nothing hangs (the PO, 04.11)."""
    from mapgen_scratch_plan import LAMP_OFF_WALL, DOOR_H
    # the face glows, the light entity in front of it lights the room: at the panels' 600 the fixtures added a fifth to
    # the floor's light (a trial duel 05.11: median 75 -> 94, top tenth 196 against the band's 200)
    lamp = Surf(pal["lamp"][0].tex, pal["lamp"][0].flags, FIXTURE_GLOW)
    DET = C_SOLID | C_DETAIL
    kind = mount[0]
    if kind in ("cornice", "post"):
        dx, dy = mount[1], mount[2]
        fx, fy = x + dx * LAMP_OFF_WALL, y + dy * LAMP_OFF_WALL        # the wall's face (one of them is the light's)
        front = {(1, 0): "-x", (-1, 0): "+x", (0, 1): "-y", (0, -1): "+y"}[(dx, dy)]
        proud = 8 if kind == "cornice" else 12
        half = 16 if kind == "cornice" else 8
        if dx:
            x0, x1 = (fx - proud, fx) if dx > 0 else (fx, fx + proud)
            y0, y1 = y - half, y + half
        else:
            y0, y1 = (fy - proud, fy) if dy > 0 else (fy, fy + proud)
            x0, x1 = x - half, x + half
        if kind == "cornice":
            top = mount[3]
            return [box((x0, y0, top - 28), (x1, y1, top), {"default": detail(pal, 0), front: lamp, "-z": lamp},
                        contents=DET, note="wall lamp")]
        floor_z = mount[3]
        return [box((x0, y0, floor_z), (x1, y1, z - 8), {"default": detail(pal, 1)}, contents=DET, note="lamp post"),
                box((x0, y0, z - 8), (x1, y1, z + 8), {"default": detail(pal, 1), front: lamp}, contents=DET,
                    note="post lamp")]
    if kind == "free":
        top, sky = mount[1], mount[2]
        # the PO, 04.11: nothing hangs in the air - a lamp panel set into a ceiling just over its light; a light
        # lower down (a high hall, a court under the sky) shines with no fixture, as in people's maps
        if not sky and top - z <= 48:
            return [box((int(x) - 16, int(y) - 16, top - 4), (int(x) + 16, int(y) + 16, top),
                        {"default": detail(pal, 0), "-z": pal["lamp"][0]}, note="lamp")]
        return []
    if kind == "door":
        i, sgn = mount[1], mount[2]
        if (i, sgn) not in lintels:
            return []
        d = P.doors[i]
        pcs = [plan_mod.phys(c) for c in d.cells]
        xs, ys = [c[0] for c in pcs], [c[1] for c in pcs]
        top_ = d.top or (d.z + 32 + DOOR_H if d.stair else d.z + DOOR_H)
        along_x = len(set(ys)) == 1
        line = ys[0] if along_x else xs[0]
        face = (line + 1) * CELL if sgn > 0 else line * CELL
        t0, t1 = (face, face + 8) if sgn > 0 else (face - 8, face)
        if along_x:
            lo, hi, front = (x - 16, t0, top_ + 16), (x + 16, t1, top_ + 28), ("+y" if sgn > 0 else "-y")
        else:
            lo, hi, front = (t0, y - 16, top_ + 16), (t1, y + 16, top_ + 28), ("+x" if sgn > 0 else "-x")
        return [box(lo, hi, {"default": detail(pal, 2), front: lamp}, contents=DET, note="door lamp")]
    return []


class LayerView:
    """Brief 21: the plan as the wall dressing reads it, one layer at a time and in world cells - a room over a room
    keeps its cells on the plan's upper layer (mapgen_scratch_plan.UP), where an owner, an item or a doorway would
    otherwise answer for the cell under it. The doors of the other layer stay in the list (their numbers are the
    lintels' names) as nothing to dress."""

    class _None:
        kind = "none"
        mover = rj = False
        cells = []

    def __init__(self, P, upper):
        import dataclasses
        # brief 25 B: a layer by its number (a tower's storeys); False / True the ground and the room over a room
        layer = int(upper)
        on = lambda c: plan_mod.layer_of(c) == layer  # noqa: E731
        ph = plan_mod.phys
        self.owner = {ph(c): o for c, o in P.owner.items() if on(c)}
        self.items = [(cls, ph(c), z, n) for (cls, c, z, n) in P.items if on(c)]
        self.spawns = [(ph(c), z, a) for (c, z, a) in P.spawns if on(c)]
        self.no_items = {ph(c) for c in P.no_items if on(c)}
        lower = not upper
        self.chamfers = list(P.chamfers) if lower else []
        self.pillars = [(ph(c), z0, z1) for (c, z0, z1) in P.pillars if on(c)]
        self.ladders = list(P.ladders) if lower else []
        self.pads = list(P.pads) if lower else []
        self.teleports = list(P.teleports) if lower else []
        self.liquids = list(P.liquids) if lower else []
        # brief 22 D1: the powerups' buttons and the round shapes' cells, kept bare by the dressing too - the view had
        # neither, so a pilaster went up through a button (3 of 202 after the plan's own sets were fixed) and the
        # skirting ran into a rounded corner's fill
        self.buttons = [(ph(c), *rest) for (c, *rest) in getattr(P, "buttons", []) if on(c)]
        self.rounded = {ph(c) for c in getattr(P, "rounded", ()) if on(c)}
        self.fx_cells = {ph(c) for c in getattr(P, "fx_cells", ()) if on(c)}     # brief 32
        self.doors = [dataclasses.replace(d, cells=[ph(c) for c in d.cells]) if d.cells and on(d.cells[0])
                      else LayerView._None() for d in P.doors]
        self.spaces = {}
        for s in P.spaces:
            if s.solid or not s.floor or on(next(iter(s.floor))) is False:
                continue
            if upper:
                r = s.rect
                s = dataclasses.replace(s, floor={ph(c): f for c, f in s.floor.items()},
                                        rect=plan_mod.Rect(r.x0, r.y0 - plan_mod.UP, r.x1, r.y1 - plan_mod.UP))
            self.spaces[s.id] = s


def rects_of(cells: set) -> list:
    """A set of cells as greedy rectangles (x0, y0, x1, y1), half-open."""
    left = set(cells)
    out = []
    while left:
        x0, y0 = min(left)
        x1 = x0
        while (x1 + 1, y0) in left:
            x1 += 1
        y1 = y0
        while all((x, y1 + 1) in left for x in range(x0, x1 + 1)):
            y1 += 1
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                left.discard((x, y))
        out.append((x0, y0, x1 + 1, y1 + 1))
    return out


def build_plan(P, pal: dict, title: str = "") -> tuple:
    """(worldspawn keys, world brushes, entities) for a plan - moved towards the world's middle when it is wider than
    the compiler's world lets it stand from 0 (`mapgen_scratch_build.world_shift`; the shift kept in the metrics, the
    measures that take places from the plan add it)."""
    import mapgen_scratch_build as build_mod
    shift = build_mod.world_shift(P)
    world, brushes, ents = _build_plan(P, pal, title)
    if shift != (0, 0):
        build_mod.move_world(brushes, ents, shift)
        P.metrics["world_shift"] = list(shift)
    else:
        P.metrics.pop("world_shift", None)
    return world, brushes, ents


def _build_plan(P, pal: dict, title: str = "") -> tuple:
    if P.params.get("shape") == "space":
        return build_space(P, pal, title)
    DOOR_H = plan_mod.DOOR_H
    spaces = {s.id: s for s in P.spaces if not s.solid}
    slots = space_slots(P, pal)

    def pal_of(sid):
        s = spaces[sid]
        return {"hall": 0, "room": 1, "corridor": 2}.get(s.kind, 1)

    def surf(role, what):
        kind, idx = role
        if kind == "door":
            if idx < 0:
                return pal["trim"][0]
            d = P.doors[idx]
            if what == "floor":
                return pal["floor"][pal_of(d.a) % len(pal["floor"])]
            # a doorway's sides in the wall's thickness: the frames' texture (brief 21 F1)
            return detail(pal, 2)
        s = spaces[idx]
        k = pal_of(idx)
        if what == "floor":
            return pal["floor"][floor_slot(slots[idx][1], len(pal["floor"])) if idx in slots else k % len(pal["floor"])]
        if what in ("ceil", "slab", "sky"):
            # «slab»: rock with more air over it - a ceiling even under the sky (a ledge over a court); «sky»: the top of a
            # well a roofed space opens to the sky (a tower's perch well)
            if what == "sky" or (what == "ceil" and s.sky):
                return pal["sky"][0]
            return pal["ceil"][k % len(pal["ceil"])]
        return pal["wall"][(slots[idx][0] if idx in slots else k) % len(pal["wall"])]

    air = defaultdict(list)
    steps = []
    ph = plan_mod.phys
    plat_cells = {c: zl for (plat, zl, zh, bottom, top) in P.lifts for c in plat}
    # brief 34: a stopping lift's cabin rests in the same recess at its ground stop
    plat_cells.update({ph(c): stops[0] for (cells, stops, _d, _n) in getattr(P, "trains", []) for c in cells})
    for s in spaces.values():
        role = ("space", s.id)
        for c0, f in s.floor.items():
            c = ph(c0)
            z, kind, sx, sy = f
            if kind == "stair":
                air[c].append([z if c in P.ramps else z + 16, s.ceil, role, role])
                steps.append((c, z, sx, sy, role))
            else:
                # a lift's plat rests in a recess 16 deep: at rest its top is the floor (it flickered inside the floor)
                air[c].append([z - 16 if c in plat_cells else z, P.cell_ceil.get(c0, s.ceil), role, role])
    for i, d in enumerate(P.doors):
        role = ("door", i)
        for c in map(ph, d.cells):
            if d.stair:
                air[c].append([d.z if c in P.ramps else d.z + 16, d.z + 32 + DOOR_H, role, role])
                steps.append((c, d.z, d.stair[0], d.stair[1], role))
            else:
                air[c].append([d.z, plan_mod.door_top(d) if d.kind == "swim" else (d.top or d.z + DOOR_H), role, role])
    for (cells, z0, z1, *_w) in P.windows:
        for c in cells:
            air[c].append([z0, z1, ("door", -1), ("door", -1)])
    # the PO 13.11 (Bugs/4): the slots cut in the rock for a pendulum's swing (mapgen_scratch_pieces.sweep), the room's
    # own air - its walls dressed as the room's
    for (c0, z0, z1, sid) in getattr(P, "slots", []):
        if sid in spaces:
            air[ph(c0)].append([z0, min(z1, spaces[sid].ceil), ("space", sid), ("space", sid)])
    zmin = min(a[0] for v in air.values() for a in v) - 32
    zmax = max(a[1] for v in air.values() for a in v) + 32
    spans = {}
    for c, v in air.items():
        v.sort(key=lambda a: a[0])
        out = []
        for a in v:
            if out and a[0] <= out[-1][1]:
                if a[1] > out[-1][1]:
                    out[-1][1] = a[1]
                    out[-1][3] = a[3]
            else:
                out.append(list(a))
        spans[c] = out
    hull = set()
    for (x, y) in spans:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                hull.add((x + dx, y + dy))
    # rock intervals: (bottom, top, role of the air under it, role of the air over it)
    by_sig = defaultdict(set)
    for c in hull:
        z = zmin
        below = None
        for a in spans.get(c, []):
            if a[0] > z:
                by_sig[(z, a[0], below, a[2])].add(c)
            z = a[1]
            below = a[3]
        if z < zmax:
            by_sig[(z, zmax, below, None)].add(c)

    def side_surf(cells_on_edge, outward, a, b):
        votes = {}
        for (x, y) in cells_on_edge:
            n = (x + outward[0], y + outward[1])
            for sp in spans.get(n, []):
                lo, hi = max(a, sp[0]), min(b, sp[1])
                if hi > lo:
                    votes[sp[2]] = votes.get(sp[2], 0) + (hi - lo)
        if not votes:
            return pal["wall"][0]
        return surf(max(votes.items(), key=lambda kv: kv[1])[0], "wall")

    # brief 34 follow-up (the PO 08.11, mg_new_594: «у двух площадок наверху уровня снизу небо просвечивает вместо
    # текстуры плиты»): the cells whose own ceiling is the sky over a roofed space - a perch's well over the top gallery
    wells = {ph(c0) for c0, cz in P.cell_ceil.items() if c0 in P.owner and cz > spaces[P.owner[c0]].ceil}
    brushes = []
    for sig, cells in by_sig.items():
        a, b, below, above = sig
        left = set(cells)
        while left:
            x0, y0 = min(left)
            x1 = x0
            while (x1 + 1, y0) in left:
                x1 += 1
            y1 = y0
            while all((x, y1 + 1) in left for x in range(x0, x1 + 1)):
                y1 += 1
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    left.discard((x, y))
            top = surf(above, "floor") if above else pal["wall"][0]
            # the rock's underside: the sky only where no air is over it (the map's top), never under a ledge's slab
            if not below:
                bot = pal["wall"][0]
            elif above is not None and not SKY_UNDERSIDES:
                bot = surf(below, "slab")
            elif above is None and not SKY_UNDERSIDES and all((x, y) in wells for x in range(x0, x1 + 1)
                                                               for y in range(y0, y1 + 1)):
                bot = surf(below, "sky")
            else:
                bot = surf(below, "ceil")
            sides = {
                "+x": side_surf([(x1, y) for y in range(y0, y1 + 1)], (1, 0), a, b),
                "-x": side_surf([(x0, y) for y in range(y0, y1 + 1)], (-1, 0), a, b),
                "+y": side_surf([(x, y1) for x in range(x0, x1 + 1)], (0, 1), a, b),
                "-y": side_surf([(x, y0) for x in range(x0, x1 + 1)], (0, -1), a, b),
            }
            brushes.append(box((x0 * CELL, y0 * CELL, a), ((x1 + 1) * CELL, (y1 + 1) * CELL, b),
                               {"+z": top, "-z": bot, **sides}))
    def tread(role):
        # brief 21 F1: the steps' treads in a floor accent of the style's maps (their stair or grating texture)
        return pal["tread"][0] if pal.get("tread") else surf(role, "floor")
    for (c, z, sx, sy, role) in steps:
        x0, y0 = c[0] * CELL, c[1] * CELL
        x1, y1 = x0 + CELL, y0 + CELL
        if c in P.ramps:
            # a ramp: 32 up over the cell along (sx, sy); its foot sinks 16 into the rock (no sliver of a side)
            axis = "x" if sx else "y"
            up = sx if sx else sy
            brushes.append(wedge((x0, y0, z - 16), (x1, y1, z + 32), axis, z if up > 0 else z + 32,
                                 z + 32 if up > 0 else z, {"default": detail(pal, 3), "+z": tread(role)},
                                 note="ramp"))
            continue
        if sx > 0:
            x0 += CELL // 2
        elif sx < 0:
            x1 -= CELL // 2
        if sy > 0:
            y0 += CELL // 2
        elif sy < 0:
            y1 -= CELL // 2
        brushes.append(box((x0, y0, z + 16), (x1, y1, z + 32), {"default": detail(pal, 3),
                                                                "+z": tread(role)}, note="step"))
    for (c, corner, z0, z1) in P.chamfers:
        w = surf(("space", P.owner[c]), "wall")
        brushes.append(prism_tri((c[0] * CELL, c[1] * CELL, z0), ((c[0] + 1) * CELL, (c[1] + 1) * CELL, z1),
                                 corner, {"default": w, "diag": w}, note="chamfer"))
    # 3.46, medusa_b1's round architecture: a rounded corner or an apse as a fan of triangles from the corner point
    # (each convex), floor to ceiling in the space's wall; a podium's tiers as octagons of the floor, detail
    for (pt, arc, z0, z1, sid, _kind) in getattr(P, "rounds", []):
        w = surf(("space", sid), "wall")
        for i in range(len(arc) - 1):
            tri = [pt, arc[i], arc[i + 1]]
            if len({tuple(v) for v in tri}) < 3:
                continue
            brushes.append(prism_poly(tri, z0, z1, {"default": w}, note="round corner"))
    for (outer, inner, z, sid) in getattr(P, "podiums", []):
        fl = surf(("space", sid), "floor")
        brushes.append(prism_poly(outer, z - 8, z + 16, {"default": detail(pal, 0), "+z": fl},
                                            contents=C_SOLID | C_DETAIL, note="podium"))
        if inner:
            brushes.append(prism_poly(inner, z + 16, z + 32, {"default": detail(pal, 1), "+z": fl},
                                                contents=C_SOLID | C_DETAIL, note="podium tier"))
    for (c, z0, z1) in P.pillars:
        c = ph(c)
        cx, cy = c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2
        brushes.append(box((cx - 24, cy - 24, z0), (cx + 24, cy + 24, z1), {"default": detail(pal, 1)},
                           note="pillar"))
    # brief 20 D4: the walls' finish - each layer of the plan in world cells (brief 21: a room over a room)
    lintels = set()
    layers = max(2, 1 + max((plan_mod.layer_of(c) for c in P.owner), default=0))
    for upper in range(layers):
        V = LayerView(P, upper)
        if V.spaces:
            brushes.extend(dress_walls(V, pal, spans, V.spaces, plat_cells if not upper else {}, lintels))
    ents = []
    lamp = pal["lamp"][0]
    q = P.params
    for (cells, z0, z1, *w) in P.windows:
        kind, tint = (list(w) + ["box", 0])[:2]
        if len(cells) > 1:
            along = "x" if len({c[1] for c in cells}) == 1 else "y"
        else:
            c = cells[0]
            along = "x" if (P.owner.get((c[0], c[1] - 1)) is not None and P.owner.get((c[0], c[1] + 1)) is not None) else "y"
        brushes.extend(window_pieces(cells, z0, z1, kind, tint, pal["trim"][0], along))
    for (cells, into, zl, zh, front) in P.ladders:
        xs, ys = [c[0] for c in front], [c[1] for c in front]
        x0, x1 = min(xs) * CELL + 4, (max(xs) + 1) * CELL - 4
        y0, y1 = min(ys) * CELL + 4, (max(ys) + 1) * CELL - 4
        if into == (1, 0):
            x0, x1 = min(xs) * CELL, min(xs) * CELL + 8
        elif into == (-1, 0):
            x0, x1 = (max(xs) + 1) * CELL - 8, (max(xs) + 1) * CELL
        elif into == (0, 1):
            y0, y1 = min(ys) * CELL, min(ys) * CELL + 8
        else:
            y0, y1 = (max(ys) + 1) * CELL - 8, (max(ys) + 1) * CELL
        brushes.append(box((x0, y0, zl), (x1, y1, zh), {"default": pal["trim"][0]}, contents=C_SOLID | C_LADDER,
                           note="ladder"))
    for d in P.doors:
        if not d.mover:
            continue
        lo, hi = door_box(P, d)
        for (sa, sb) in door_stops(P, d):
            brushes.append(box(sa, sb, {"default": pal["trim"][0]}, note="door stop"))
        if getattr(d, "tname", None):
            # a powerup's door: opened by its buttons only, for five seconds (brief 21+)
            ents.append(Entity({"classname": "func_door", "angle": "-1", "speed": "150", "wait": "5", "lip": "8",
                                "targetname": d.tname},
                               [box(lo, hi, {"default": detail(pal, 2)})]))
            continue
        ents.append(Entity({"classname": "func_door", "angle": "-1", "speed": "200", "wait": "2", "lip": "8"},
                           [box(lo, hi, {"default": pal["trim"][0]})]))
    # the PO 13.11: the scripted pieces (trains, stones, traps, rotators...)
    import mapgen_scratch_pieces as pieces_mod
    pieces_mod.world(P, pal, brushes, ents)
    return finish_entities(P, pal, spaces, brushes, ents, lintels, spans, title)


def finish_entities(P, pal: dict, spaces: dict, brushes: list, ents: list, lintels: set, spans: dict, title: str = "") -> tuple:
    """What every map gets after its brushes (brief 25 A2: shared by the rooms' builder and the open space's): the
    chasms' kill volumes, the wall decorations, the liquids, the lifts, the pads, the teleporters, the lights, the
    pedestals, the items, the buttons, the spawns and the worldspawn with its sun."""
    q = P.params
    ph = plan_mod.phys
    lamp = pal["lamp"][0]
    for (cells, bottom, sid) in P.pits:
        # one trigger_hurt per chasm, its brushes the chasm's rectangles (a bridge splits it in two)
        ents.append(Entity({"classname": "trigger_hurt", "dmg": "1000", "spawnflags": "8"},
                           [box((x0 * CELL, y0 * CELL, bottom), (x1 * CELL, y1 * CELL, bottom + 64),
                                {"default": TRIGGER_SURF()}) for (x0, y0, x1, y1) in rects_of(set(cells))]))
    # wall decorations: a panel of the trim (and, for «many», a lamp strip) every few cells of plain wall
    every = DECOR_EVERY.get(q.get("decor") or "default", 5)
    import math
    import mapgen_scratch_fixtures as fix_mod_
    placed_decor = []
    hung = 0
    if every:
        busy = ({c for (c, *_r) in P.chamfers} | {c for (c, *_r) in P.pillars} | set(getattr(P, "rounded", ()))
                | plan_mod.button_cells(P) | set(getattr(P, "fx_cells", ())))
        busy |= {c for (*_r, front) in P.ladders for c in front}
        k = 0
        for s in spaces.values():
            if s.floor and plan_mod.is_up(next(iter(s.floor))):
                continue       # brief 21: no panels in a room over a room (decor is asked only by name)
            for c in sorted(s.floor):
                z, kind, _, _ = s.floor[c]
                if kind != "flat" or c in busy:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (c[0] + dx, c[1] + dy)
                    lo, hi = z + 48, z + 144
                    if any(a[0] < hi and a[1] > lo for a in spans.get(n, [])) or hi > s.ceil - 16:
                        continue
                    k += 1
                    if k % every:
                        continue
                    cx, cy = c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2
                    fx = (c[0] + (1 if dx > 0 else 0)) * CELL if dx else None
                    fy = (c[1] + (1 if dy > 0 else 0)) * CELL if dy else None
                    lamp_strip = q.get("decor") == "many" and (k // every) % 2 == 0
                    surf_ = lamp if lamp_strip else pal["trim"][0]
                    if dx:
                        lo_, hi_ = ((fx - 6, cy - 20, z + 56), (fx, cy + 20, z + 136)) if dx > 0 else \
                            ((fx, cy - 20, z + 56), (fx + 6, cy + 20, z + 136))
                    else:
                        lo_, hi_ = ((cx - 20, fy - 6, z + 56), (cx + 20, fy, z + 136)) if dy > 0 else \
                            ((cx - 20, fy, z + 56), (cx + 20, fy + 6, z + 136))
                    # brief 34 (the PO 08.11: «не просто напихивать на уровне кучу повторяемых объектов»): no third
                    # piece within four cells of two on this floor - «many» is as many as stand apart (the piece's own
                    # middle, as the measure reads it)
                    mid = ((lo_[0] + hi_[0]) / 2, (lo_[1] + hi_[1]) / 2, lo_[2])
                    if fix_mod_.crowded(placed_decor, mid):
                        continue
                    placed_decor.append(mid)
                    brushes.append(box(lo_, hi_, {"default": pal["trim"][0], **({"+x": surf_, "-x": surf_, "+y": surf_,
                                                                                  "-y": surf_} if lamp_strip else {})},
                                       note="decor"))
                    hung += 1
                    break
    P.metrics["decor_pieces"] = hung
    from mapgen_scratch_build import C_WATER, C_LAVA, C_SLIME, C_TRANSLUCENT
    for (cells, kind, z0, level) in P.liquids:
        sf = pal[kind][0]
        contents = {"water": C_WATER | C_TRANSLUCENT, "lava": C_LAVA, "slime": C_SLIME}[kind]
        # the world's cells (the PO 12.11: a tube under the floors has its cells on a layer of its own)
        for (x0, y0, x1, y1) in rects_of({ph(c) for c in cells}):
            brushes.append(box((x0 * CELL, y0 * CELL, z0), (x1 * CELL, y1 * CELL, level), {"default": sf},
                               contents=contents, note=kind))
    for (plat, zl, zh, bottom, top) in P.lifts:
        xs = [c[0] for c in plat]
        ys = [c[1] for c in plat]
        lo = (min(xs) * CELL + 1, min(ys) * CELL + 1, zh - 16)
        hi = ((max(xs) + 1) * CELL - 1, (max(ys) + 1) * CELL - 1, zh)
        ents.append(Entity({"classname": "func_plat", "height": str(zh - zl), "speed": "200", "lip": "0"},
                           [box(lo, hi, {"default": pal["trim"][0], "+z": pal["floor"][0]})]))
    # brief 34 (the PO 08.11: «лифты как в небоскрёбах - едут между этажами, останавливаются там»): a cabin the shaft's
    # size riding path corners - one a storey, up and back down - waiting at each; its top at a stop is that storey's
    # floor (the corner takes its mins: the game's train_next), at the ground in the plats' recess
    for (cells, stops, _doors, name) in getattr(P, "trains", []):
        pcs = [ph(c) for c in cells]
        x0, y0 = min(c[0] for c in pcs) * CELL + 1, min(c[1] for c in pcs) * CELL + 1
        x1, y1 = (max(c[0] for c in pcs) + 1) * CELL - 1, (max(c[1] for c in pcs) + 1) * CELL - 1
        order = list(range(len(stops))) + list(range(len(stops) - 2, 0, -1))
        names = [f"{name}_{i}" for i in range(len(order))]
        ents.append(Entity({"classname": "func_train", "target": names[0], "speed": str(int(plan_mod.TRAIN_SPEED)),
                            "spawnflags": "1", "dmg": "10"},
                           [box((x0, y0, stops[0] - 16), (x1, y1, stops[0]),
                                {"default": pal["trim"][0], "+z": pal["floor"][0]}, note="lift cabin")]))
        for i, si in enumerate(order):
            ents.append(Entity({"classname": "path_corner", "targetname": names[i], "target": names[(i + 1) % len(names)],
                                "wait": str(int(plan_mod.TRAIN_WAIT)), "origin": f"{x0} {y0} {stops[si] - 16}"}))
    from mapgen_scratch_style import TRIGGER
    import mapgen_scratch_fixtures as fix_mod
    # brief 26: the pads' and teleporters' look as people build them (mapgen_scratch_fixtures) - with the style's own
    # fixture textures; without them (no game palette to write them by) the plate of before
    fx_on = bool(pal.get("fx"))
    fxm = {"pads": len(P.pads), "discs": 0, "wedges": 0, "teleporters": 0, "frames": 0, "posts": 0, "bare": 0, "why": []}
    # brief 32: each at the size the plan found room for (mapgen_scratch_fixtures.plan_sizes; 100 % without it)
    sizes = getattr(P, "fx_size", {}) or {}
    for i, (a, t, T, speed, pitch, yaw, zf) in enumerate(P.pads):
        x0, y0 = ph(a)[0] * CELL, ph(a)[1] * CELL
        if fx_on:
            bs, kind = fix_mod.pad_brushes(pal, ph(a), zf, pitch, yaw, sizes.get(("pad", i), 100) / 100)
            brushes.extend(bs)
            fxm["discs" if kind == "disc" else "wedges"] += 1
        else:
            brushes.append(box((x0 + 8, y0 + 8, zf), (x0 + CELL - 8, y0 + CELL - 8, zf + 4),
                               {"default": pal["trim"][0], "+z": lamp}, note="pad"))
        # 7 in, not 8 (11.11, the fixtures check of brief 35): a slanted pad flying along an axis has its wedge's sides
        # (fix_mod.WEDGE_HALF, 24 off the middle) on the very planes of a 48-wide trigger's, and the engine's rebuild of
        # the base dresses the trigger's unseen sides in the wedge's drawn texture - «the baseline draws 5184 units of
        # e1u1/box1_3 that the donor does not», the base refused (seed 26101: 4 of 13 pads along an axis). One unit wider
        # on each side puts no trigger side on a pad's face at any size (wedge 12..48, plinth 20..81, disc 14..55 off)
        ents.append(Entity({"classname": "trigger_push", "speed": str(speed), "angles": f"{-pitch} {yaw} 0"},
                           [box((x0 + PAD_TRIGGER_IN, y0 + PAD_TRIGGER_IN, zf + 4),
                                (x0 + CELL - PAD_TRIGGER_IN, y0 + CELL - PAD_TRIGGER_IN, zf + 40), {"default": TRIGGER})]))
        # brief 34 (the PO: «непонятно для чего»): where it lands is marked - a thin lit plate on the landing's floor,
        # not a pad's look (no ring), so the floor shows where each pad goes
        if fx_on and t in P.owner and P.spaces[P.owner[t]].floor.get(t, (0, ""))[1] == "flat":
            brushes.extend(fix_mod.landing_mark(pal, ph(t), P.spaces[P.owner[t]].floor[t][0]))
            fxm["landings"] = fxm.get("landings", 0) + 1
    fx_busy = fix_mod.busy_cells(P) if fx_on else set()
    for k, (a, b_, da, db) in enumerate(P.teleports):
        for src, dst, name in ((a, db, f"tele{k}a"), (b_, da, f"tele{k}b")):
            zs = P.spaces[P.owner[src]].floor[src][0]
            zd = P.spaces[P.owner[dst]].floor[dst][0]
            # the exit faces what the mechanic named (a key item), else the longest open run - never a wall
            ang = P.dest_face.get(dst, plan_mod.facing(P, dst))
            ps, pd = ph(src), ph(dst)
            keys = {"classname": "misc_teleporter", "target": name,
                    "origin": f"{ps[0] * CELL + CELL // 2} {ps[1] * CELL + CELL // 2} {zs + 24}"}
            fxm["teleporters"] += 1
            if fx_on:
                got, fit = sizes.get(("tele", src), (100, None))
                bs, kind, why, face_ = fix_mod.teleporter_frame(P, pal, src, fx_busy, got / 100, fit)
                brushes.extend(bs)
                fxm[{"frame": "frames", "posts": "posts", "bare": "bare"}[kind]] += 1
                if why:
                    fxm["why"].append(f"{ps[0]} {ps[1]}: {why}")
                if kind == "bare":
                    # the record says why (brief 26 D3)
                    ru = "потолок низко" if why.startswith("the ceiling") else "по бокам нет места под стойки"
                    P.metrics["refused"] = list(P.metrics.get("refused") or []) + [plan_mod.say(
                        f"телепорт в клетке {ps[0]} {ps[1]} без рамы: {ru}", f"the teleporter at cell {ps[0]} {ps[1]} has no frame: {why}")]
                keys["angle"] = str(face_)          # the frame's open side (the covers look at it from there)
            ents.append(Entity(keys))
            ents.append(Entity({"classname": "misc_teleporter_dest", "targetname": name, "angle": str(ang % 360),
                                "origin": f"{pd[0] * CELL + CELL // 2} {pd[1] * CELL + CELL // 2} {zd + 24}"}))
    tone = q.get("tone") or "style"
    tone = pal.get("tone", "neutral") if tone == "style" else tone
    # «people»: the colour of the light of the people's map the style took (their lightmaps' mean, 05.11 - 3.41 lit
    # every map white, people's light is tinted: q2dm1 orange, ztn2dm3 brown)
    colour = tuple(pal["light_colour"]) if tone == "people" and pal.get("light_colour") else TONES.get(tone, TONES["neutral"])
    for (x, y, z, v, *mnt) in P.lights:
        mount = mnt[0] if mnt else None
        keys = {"classname": "light", "origin": f"{int(x)} {int(y)} {int(z)}", "light": str(int(v))}
        if tone in ("warm", "cold", "people"):
            # a tone asked colours the lamps; neutral is plain white - the dressing's new rooms are lit white and their
            # tint is judged against the rooms round them (04.11: B/R 0.50 against 0.69)
            keys["_color"] = " ".join(f"{c:.2f}" for c in colour)
        ents.append(Entity(keys))
        if mount is not None:
            brushes.extend(lamp_fixture(P, pal, x, y, z, mount, lintels))
            continue
        o = P.owner.get((int(x // CELL), int(y // CELL)))
        if o is not None:
            top = spaces[o].ceil
            # the PO, 04.11: nothing hangs in the air - a lamp panel set into a ceiling just over its light; a light
            # lower down (a high hall, a court under the sky) shines with no fixture, as in people's maps
            if not spaces[o].sky and top - z <= 48:
                brushes.append(box((int(x) - 16, int(y) - 16, top - 4), (int(x) + 16, int(y) + 16, top),
                                   {"default": pal["trim"][0], "-z": lamp}, note="lamp"))
    # the powerups' places (brief 21+, the PO 05.11 «помечать такие места, делая их значимыми»): a pedestal of the trim
    # 8 high under each, the tread on top, and a light of the item's colour over it; items taking turns in one place
    # (the cycle) share an item team, as q2dm8's mega, body armour and power shield
    ped = {}
    for (pc, pz, pcls) in getattr(P, "pedestals", []):
        ped[pc] = pz
        x0, y0 = ph(pc)[0] * CELL + 8, ph(pc)[1] * CELL + 8
        brushes.append(box((x0, y0, pz), (x0 + CELL - 16, y0 + CELL - 16, pz + 8),
                           {"default": detail(pal, 0), "+z": pal["tread"][0] if pal.get("tread") else pal["floor"][0]},
                           contents=C_SOLID | C_DETAIL, note="pedestal"))
        col = plan_mod.POWERUP_LIGHT.get(pcls, (1.0, 1.0, 1.0))
        ents.append(Entity({"classname": "light", "light": "160",
                            "origin": f"{ph(pc)[0] * CELL + CELL // 2} {ph(pc)[1] * CELL + CELL // 2} {pz + 96}",
                            "_color": " ".join(f"{v:.2f}" for v in col)}))
    import mapgen_scratch_pieces as pieces_mod
    item_targets = pieces_mod.items_targets(P)
    teams = {}
    for (cls, c, z, note) in P.items:
        if cls in plan_mod.POWERUPS:
            teams.setdefault(c, []).append(cls)
    team_of = {c: f"mg_cycle{k}" for k, (c, v) in enumerate(sorted(teams.items())) if len(v) > 1}
    for (cls, c, z, note) in P.items:
        keys = {"classname": cls}
        if cls in plan_mod.POWERUPS and c in team_of:
            keys["team"] = team_of[c]
        # on its pedestal, whatever it is: the railgun in its room past a tube stood 16 over the floor on a pedestal 8
        # high - its box in the pedestal, the game freed it at spawn (the PO 12.11 on mg_new_7775_367: «приплыл сюда,
        # а там пусто»; his mg_new_7775 of 3.66: «внутри ничего нет»)
        lift = 8 if c in ped else 0
        # the PO 13.11: an item a piece fires when taken (a trap room, a wall opening)
        tgt = item_targets.get(tuple(c))
        if tgt:
            keys["target"] = tgt
        c = ph(c)
        keys["origin"] = f"{c[0] * CELL + CELL // 2} {c[1] * CELL + CELL // 2} {z + 16 + lift}"
        ents.append(Entity(keys))
    # the buttons that open a powerup's door (one outside on the room's wall, one inside the nook): a small block on
    # the wall's face at hand height, its face the lamp's, pushed in when touched
    for (bc, (bdx, bdy), bz, tname) in getattr(P, "buttons", []):
        cx, cy = ph(bc)[0] * CELL + CELL // 2, ph(bc)[1] * CELL + CELL // 2
        fx, fy = cx + bdx * CELL // 2, cy + bdy * CELL // 2
        if bdx:
            lo_, hi_ = ((fx - 8, cy - 16, bz + 40), (fx, cy + 16, bz + 72)) if bdx > 0 else ((fx, cy - 16, bz + 40), (fx + 8, cy + 16, bz + 72))
        else:
            lo_, hi_ = ((cx - 16, fy - 8, bz + 40), (cx + 16, fy, bz + 72)) if bdy > 0 else ((cx - 16, fy, bz + 40), (cx + 16, fy + 8, bz + 72))
        face = {(1, 0): "-x", (-1, 0): "+x", (0, 1): "-y", (0, -1): "+y"}[(bdx, bdy)]
        yaw = {(1, 0): 0, (0, 1): 90, (-1, 0): 180, (0, -1): 270}[(bdx, bdy)]
        ents.append(Entity({"classname": "func_button", "target": tname, "angle": str(yaw), "wait": "4", "lip": "4",
                            "speed": "40"}, [box(lo_, hi_, {"default": detail(pal, 2), face: pal["lamp"][0]})]))
    plates = 0
    for i, (c, z, ang) in enumerate(P.spawns):
        c = ph(c)
        # brief 32: a plate under it when asked and it found room (the spawn stands on it: 8 higher)
        plate = sizes.get(("spawn", i), 0)
        if plate:
            brushes.extend(fix_mod.spawn_plate(pal, c, z, plate / 100))
            plates += 1
        lift = fix_mod.PLATE_H if plate else 0
        ents.append(Entity({"classname": "info_player_deathmatch",
                            "origin": f"{c[0] * CELL + CELL // 2} {c[1] * CELL + CELL // 2} {z + 24 + lift}",
                            "angle": str(ang)}))
    fxm["plates"] = plates
    P.metrics["fixtures"] = fxm
    # the PO 06.11: the single-player game's ships over the map when asked (mapgen_scratch_ships)
    import mapgen_scratch_ships as ships_mod
    ents += ships_mod.ship_entities(P, spaces, spans, getattr(P, "_sky_box", None), getattr(P, "_islands_z", None))
    world = {"classname": "worldspawn", "message": title or f"MAPGEN {P.seed}", "sky": pal["sky_env"],
             "sounds": "6"}
    # the sun (brief 19 §4 «Свет»): by the style unless asked; only over a map with sky. Written the way the engine's
    # light compile gives a donor its sun (mapgen_pipeline.c: "_sun" names a target, a light 8 u towards the sun)
    sun = q.get("sun") or "style"
    sunny = pal.get("sun", True) if sun == "style" else sun == "yes"
    if sunny and any(s.sky for s in spaces.values()) and P.spawns:
        import math
        import random as _r
        rs = _r.Random(P.seed * 31 + 7)
        sk = pal.get("sun_keys") or {}
        yaw, pitch = (float(v) for v in (sk.get("_sun_angle") or f"{rs.choice((30, 60, 120, 210, 300))} -{rs.choice((50, 60, 70))}").split())
        sc = sk.get("_sun_color") or " ".join(f"{c:.2f}" for c in colour)
        # brief 20 D3: a sun of 150 with an ambient of 40 burnt a third of the floors white (the 3.40 duel: 31 % at 255,
        # people's floors none); with the lamps alone the floors sit in people's band (median 83, top tenth 176) - the
        # sun only warms the courts (a duel trial, 04.11: 50/10 burnt 2.4 %, 0 burnt none). A source map's own keys stand
        world.update({"_sun": "mapgen_sun", "_sun_angle": f"{yaw:g} {pitch:g}", "_sun_light": str(sk.get("_sun_light", SUN_LIGHT)),
                      "_sun_color": sc, "_sun_ambient": str(sk.get("_sun_ambient", SUN_AMBIENT))})
        c, z, _a = P.spawns[0]
        c = ph(c)
        at = (c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2, z + 24)
        r_ = math.pi / 180.0
        to = (-math.cos(pitch * r_) * math.cos(yaw * r_), -math.cos(pitch * r_) * math.sin(yaw * r_), -math.sin(pitch * r_))
        ents.append(Entity({"classname": "light", "target": "mapgen_sun",
                            "origin": " ".join(f"{at[i] + to[i] * 8.0:.1f}" for i in range(3))}))
        ents.append(Entity({"classname": "info_null", "targetname": "mapgen_sun",
                            "origin": " ".join(f"{v:.1f}" for v in at)}))
    # ambience where the style has one (brief 19 D3): the source maps' looped speakers, in the atrium
    for k_, noise in enumerate((pal.get("ambience") or [])[:2]):
        at_ = next((s for s in spaces.values() if s.atrium), None)
        if at_:
            cx = (at_.rect.x0 + at_.rect.x1) * CELL // 2
            cy = (at_.rect.y0 + at_.rect.y1) * CELL // 2
            ents.append(Entity({"classname": "target_speaker", "noise": noise, "spawnflags": "1",
                                "origin": f"{cx + 64 * k_} {cy} {at_.base + 96}"}))
    return world, brushes, ents


# brief 25 A2: the space's sky - Quake II's own «space1» (PAK0's env), lit softly: no sun and no ceiling over the
# islands, the sky box's faces give the light that falls on them from every side (the measure decides the value)
SPACE_SKY_ENV = "space1"
SPACE_SKY_LIGHT = 60


def build_space(P, pal: dict, title: str = "") -> tuple:
    """Brief 25 A2: an open-space plan into brushes - each island a slab 64 thick under its floor (no wall beside it, no
    ceiling over it), the railings asked on its edges, the whole world sealed in a box of sky 512 beyond the islands
    each way, a kill volume over the box's floor 384 under the lowest island; then the entities every map gets
    (finish_entities: pads, teleporters, lights, pedestals, items, spawns, worldspawn - no sun)."""
    from mapgen_scratch_build import S_SKY, S_NODRAW, S_LIGHT
    spaces = {s.id: s for s in P.spaces if not s.solid}
    pal = dict(pal)
    pal["sky_env"] = SPACE_SKY_ENV
    sky = Surf(pal["sky"][0].tex, S_SKY | S_NODRAW | S_LIGHT, SPACE_SKY_LIGHT)
    brushes = []
    slab = 64
    floors = pal["floor"]
    walls = pal["wall"]
    trim = pal["trim"][0]
    xs, ys, zs = [], [], []
    ceils = pal.get("ceil") or walls
    for s in spaces.values():
        k = s.id
        # each island its own floor, sides and underside out of the style's sets (people's maps wear 9..38 textures;
        # one floor and one wall for all gave 7)
        fl = floors[k % len(floors)]
        wl = walls[(k * 3 + 1) % len(walls)]
        under = ceils[k % len(ceils)]
        by_z = defaultdict(set)
        for c, f in s.floor.items():
            by_z[f[0]].add(c)
            xs.append(c[0])
            ys.append(c[1])
            zs.append(f[0])
        for z, cells in by_z.items():
            for j, (x0, y0, x1, y1) in enumerate(rects_of(cells)):
                # the slab's rim: a band of the trim on its sides over the wall below it
                brushes.append(box((x0 * CELL, y0 * CELL, z - slab), (x1 * CELL, y1 * CELL, z - 16),
                                   {"default": wl, "-z": under}, note="island"))
                brushes.append(box((x0 * CELL, y0 * CELL, z - 16), (x1 * CELL, y1 * CELL, z),
                                   {"default": detail(pal, k + j), "+z": fl, "-z": under}, note="island rim"))
    # the railings: a strip of the trim 8 thick, 32 high, on the cell's outer side
    for (c, side, z) in getattr(P, "railings", []):
        x0, y0 = c[0] * CELL, c[1] * CELL
        x1, y1 = x0 + CELL, y0 + CELL
        if side == "+x":
            lo, hi = (x1 - 8, y0, z), (x1, y1, z + 32)
        elif side == "-x":
            lo, hi = (x0, y0, z), (x0 + 8, y1, z + 32)
        elif side == "+y":
            lo, hi = (x0, y1 - 8, z), (x1, y1, z + 32)
        else:
            lo, hi = (x0, y0, z), (x1, y0 + 8, z + 32)
        brushes.append(box(lo, hi, {"default": trim}, contents=C_SOLID | C_DETAIL, note="railing"))
    # the sky box: six slabs 16 thick, 512 beyond the islands each way, 1024 over the highest
    m = 512
    # ... but inside the compiler's world (±4096, its slabs 16 thick): an 8-player space of 3.52 reached 4176 and its
    # candidate «leaked» (bounds out of range, 06.11) - the margin on that side the less
    lim = 4096 - 16
    # the PO 06.11: an 8-player space wider than the world's positive half is moved to its middle after the build
    # (build_plan) - the box clipped where the moved world ends
    import mapgen_scratch_build as build_mod
    sx, sy = build_mod.world_shift(P)
    X0, Y0 = max(min(xs) * CELL - m, -lim - sx), max(min(ys) * CELL - m, -lim - sy)
    X1, Y1 = min((max(xs) + 1) * CELL + m, lim - sx), min((max(ys) + 1) * CELL + m, lim - sy)
    Z0, Z1 = max(min(zs) - slab - m, -lim), min(max(zs) + 1024, lim)
    t = 16
    for lo, hi in (((X0 - t, Y0 - t, Z0 - t), (X1 + t, Y1 + t, Z0)), ((X0 - t, Y0 - t, Z1), (X1 + t, Y1 + t, Z1 + t)),
                   ((X0 - t, Y0 - t, Z0), (X0, Y1 + t, Z1)), ((X1, Y0 - t, Z0), (X1 + t, Y1 + t, Z1)),
                   ((X0, Y0 - t, Z0), (X1, Y0, Z1)), ((X0, Y1, Z0), (X1, Y1 + t, Z1))):
        brushes.append(box(lo, hi, {"default": sky}, note="sky box"))
    ents = []
    # the fall: a kill volume from the box's floor up to 384 under the lowest island (q2_q3dm17's slabs are 128 thick
    # 672 under its base) - standing on the box's floor is inside it, so nobody lives down there and the measure counts
    # no floor there
    ents.append(Entity({"classname": "trigger_hurt", "dmg": "1000", "spawnflags": "8"},
                       [box((X0, Y0, Z0), (X1, Y1, min(zs) - 384), {"default": TRIGGER_SURF()})]))
    P.metrics["decor_pieces"] = 0
    P._sky_box = (X0, Y0, Z0, X1, Y1, Z1)       # the ships' sky (mapgen_scratch_ships)
    P._islands_z = (min(zs), max(zs))
    return finish_entities(P, pal, spaces, brushes, ents, set(), {}, title)


def TRIGGER_SURF():
    from mapgen_scratch_style import TRIGGER
    return TRIGGER
