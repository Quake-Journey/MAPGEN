r"""Brief 25 B (the PO 06.11: «pro_q2t4 - не типичная архитектура для q2, тоже должны уметь такое строить … новые карты в
подобных стилях через отдельные параметры»): the shape «tower» of a map from scratch - whole storeys over one footprint.

The measure it is made to (`tools/mapgen_space_survey.py` on pro_q2t4): a compact block (1504 x 1632) of three whole
floors 152 apart, 73 % of the floor with floor above or below it (people's maps 0..57 %), medium widths, the storeys
open to each other through a middle hall and shafts (drops, sight down), jump pads straight up as its lifts, perches only a
pad reaches. Nothing of pro_q2t4 is copied: every room, opening, pad and item is drawn here from the run's number.

The plan (the generator's own Plan, built by the rooms' builder - its rock follows the air of every column, so the
storeys' floors come out of it):
  * a footprint W x H; in its middle the atrium - one hall on the ground storey whose air goes up through every storey
    (the storeys above have a hole there) under the sky;
  * round the atrium on every storey a gallery two cells wide (on the ground it is the atrium hall's own rim); the
    gallery's edge over the atrium is open - one steps off it down into the atrium;
  * the rest of each storey cut into rooms by walls, each with a door to its gallery, some to each other; each storey's
    cuts its own;
  * shafts (2 x 2, as many as asked less the atrium): on the ground a tall narrow space with a pad at its bottom and a
    door to a room; on a storey above a doorway in its wall where the pad's flight lands;
  * pads from the atrium's floor up to each gallery, from each gallery across the atrium to the one above; perches (2 x 2
    ledges on the atrium's wall between storeys) only a pad reaches;
  * storey k's cells on layer k of the plan (y + k x UP: mapgen_scratch_plan.layer_of / phys).
"""
from __future__ import annotations

import math
import random

import mapgen_scratch_plan as pm

CELL = pm.CELL
UP = pm.UP
SLAB = 16
GRAVITY = 800.0

# brief 34 (the PO 08.11: «можно же лестницы строить, лифты, а не напихивать джампады ради джампадов - всё хорошо в
# меру»; «лифты как в небоскрёбах - едут между этажами, останавливаются там»): a tower climbs by a flight of steps per
# storey («stairs» -1: one a storey), a lift stopping on every storey in a shaft («lifts»: shafts that hold one) and
# one express pad from a corner of the atrium to the top («pads»: pads beside the stairs and lifts); the perches by
# pads (only a pad reaches them, by design)
TOWER_DEFAULTS = {"storeys": 3, "storey_height": 192, "shafts": 2, "perches": 2, "openness": [0.28, 0.47, 0.25],
                  "pits": 0, "water": 0.0, "lava": 0.0, "slime": 0.0, "windows": 0, "lifts": 1, "ladders": 0,
                  "ramps": 0, "stairs": -1, "pads": 1, "drops": 0, "doors": 0, "round": "", "decor": "none", "sky": 0.05,
                  "items_at_height": 0.8}
# TOWER_DEFAULTS' openness is the one the tower gives (06.11, 24 candidates of six towers: corridor 0.16..0.31, medium 0.37..0.56, open 0.16..0.33;
# pro_q2t4 0.20 / 0.65 / 0.16) - its atrium and galleries, not a rooms map's split
TOWER_MECHANICS = ["small_health", "spawn_pressure"]


def tower_defaults(q: dict, params: dict) -> None:
    for k, v in TOWER_DEFAULTS.items():
        if params.get(k) is None:
            q[k] = list(v) if isinstance(v, list) else v
    if params.get("mechanics") is None:
        q["mechanics"] = list(TOWER_MECHANICS)
    if params.get("teleporters") is None:
        q["teleporters"] = 0 if q["players"] <= 2 else 1
    q["storeys"] = max(2, min(4, int(q["storeys"])))
    q["storey_height"] = max(160, min(256, int(q["storey_height"])))
    q["shafts"] = max(1, min(3, int(q["shafts"])))
    q["perches"] = max(0, min(3, int(q["perches"])))
    # 3.57: what a tower never builds (its own card says so: «Лестницы, лифты, окна и жидкости здесь не строятся») - the
    # form no longer offers them, and a request that still asks (an older preset) is told
    import mapgen_scratch_space as space_mod
    forced = [k for k in space_mod.SPACE_FORCED if k not in ("decor", "stairs", "lifts")]       # brief 34: its own
    asked = [k for k in forced if q.get(k) not in (None, TOWER_DEFAULTS.get(k), 0, 0.0, "", "none")]
    for k in forced:
        q[k] = TOWER_DEFAULTS.get(k, 0)
    if asked:
        ru = ", ".join(space_mod.SPACE_FORCED_WORDS[k][0] for k in asked)
        en = ", ".join(space_mod.SPACE_FORCED_WORDS[k][1] for k in asked)
        q["refused"] = list(q.get("refused") or []) + [
            f"{ru}: в башне не строятся - этажи вокруг атриума, наверх лестницами, лифтами и джампадами ¦ {en}: not built in a tower - storeys round an atrium, up by stairs, lifts and pads"]
    for k_ in ("stairs", "lifts", "pads"):
        if q.get(k_) is None:
            q[k_] = TOWER_DEFAULTS[k_]


def key(c, k: int):
    """Cell c of storey k as the plan keys it."""
    return (c[0], c[1] + k * UP) if k else c


# brief 34: a perch's pad from the atrium's rim keeps three cells from the corners no perch is over (the express's);
# off only for check_mapgen_tower_ways.py's RED
KEEP_FREE_CORNERS = True


def flight_ok(P: pm.Plan, a, t, za: int, zt: int, vx: float, vy: float, vz: float, T: float, top: int,
              lift: float = 0.0) -> bool:
    """A pad's flight in world units: from a's floor at za; it must stay out of every storey's slab and every wall (a
    column with no air at that height) until, coming down, its feet reach the target's floor zt."""
    x0, y0, z0 = (a[0] + 0.5) * CELL, (a[1] + 0.5) * CELL, za + 24.0 + pm.PAD_TOP + lift   # on the pad's plinth (brief 26)
    tt, dt = 0.0, 0.02
    while tt < T + 0.6:
        tt += dt
        x, y = x0 + vx * tt, y0 + vy * tt
        z = z0 + vz * tt - 0.5 * GRAVITY * tt * tt
        # the head as the survey tests it (its flight starts 24 higher and tests a point 28 over it): a perch pad off
        # the next cell passed this with the head at +32 and stopped at the perch's slab in the survey (06.11)
        feet, head = z - 24, z + 56
        if head > top - 48:          # under the sky with room to spare: a perch's flight hit the sky (06.11)
            return False
        down = vz - GRAVITY * tt < 0
        here = (int(x // CELL), int(y // CELL))
        # from over a wedge (lift) the flight comes down a little further on: the target's floor or the next cell's
        near = here == t or (lift and max(abs(here[0] - t[0]), abs(here[1] - t[1])) <= 1
                             and any(abs(lo - zt) <= 1 for (lo, _hi) in P._air.get(here, ())))
        if down and near and feet <= zt + 8:
            return feet >= zt - 8 and tt > 0.3
        for ox in (-16, 16):
            for oy in (-16, 16):
                cc = (int((x + ox) // CELL), int((y + oy) // CELL))
                if not any(lo - 1 <= feet and head <= hi + 1 for (lo, hi) in P._air.get(cc, ())):
                    return False
    return False


def pad(P: pm.Plan, a_key, t_key, top: int, reach: float = 1100, margin: bool = False) -> bool:
    """A pad on cell a_key landing on t_key (plan keys; their storeys' floors), if a flight clears. `margin` (brief 34:
    a perch's pad from the top gallery): the flight clears from 30 higher too - the people's survey launches it 24 over
    the planned take-off, and a short throw under a perch's slab missed by that much (the fixtures check, 08.11)."""
    a, t = pm.phys(a_key), pm.phys(t_key)
    za = P.spaces[P.owner[a_key]].floor[a_key][0] if a_key in P.owner else P._door_z[a_key]
    zt = P.spaces[P.owner[t_key]].floor[t_key][0] if t_key in P.owner else P._door_z[t_key]
    dxu, dyu = (t[0] - a[0]) * CELL, (t[1] - a[1]) * CELL
    D = math.hypot(dxu, dyu)
    if D > reach:
        return False
    H = zt - za - pm.PAD_TOP          # from the take-off on the pad's plinth (brief 26)
    for T in (0.8, 0.9, 1.0, 1.1, 0.7, 1.2, 1.3, 1.5, 1.7, 1.9, 2.1):
        vz = (H + 0.5 * GRAVITY * T * T) / T
        vh = D / T
        sp = math.hypot(vh, vz)
        if sp > 1500 or vz <= 0:
            continue
        ux, uy = (dxu / D, dyu / D) if D > 0 else (0.0, 0.0)
        steep = math.degrees(math.atan2(vz, max(vh, 1e-6))) >= pm.PAD_STEEP
        if flight_ok(P, a, t, za, zt, ux * vh, uy * vh, vz, T, top) and (
                steep or flight_ok(P, a, t, za, zt, ux * vh, uy * vh, vz, T, top, pm.PAD_WEDGE_LIFT)) and (
                not margin or flight_ok(P, a, t, za, zt, ux * vh, uy * vh, vz, T, top, 30.0)):
            P.pads.append((a_key, t_key, T + 0.1, round(sp / 10.0, 1), round(math.degrees(math.atan2(vz, max(vh, 1e-6))), 2),
                           round(math.degrees(math.atan2(dyu, dxu)), 2) if D > 0 else 0.0, za))
            P.no_items.update({a_key, t_key})
            return True
    return False


def plan(P: pm.Plan, rnd: random.Random) -> None:
    q = P.params
    n = q["storeys"]
    SH = q["storey_height"]
    per = q["floor_area"] * 1e6 / (CELL * CELL) / n          # floor cells a storey
    side = math.sqrt(per * 1.55)                             # the atrium's hole and the walls take the rest
    # the atrium a third of the side, the gallery round it (three cells, 192: a medium width - pro_q2t4's corridors
    # are 0.20 of its floor), then a band of rooms four cells deep at least (three is 192 across, a corridor's width)
    aw = max(4, int(side * rnd.uniform(0.26, 0.34)))
    ah = max(4, int(side * rnd.uniform(0.26, 0.34)))
    gw = 3
    # under 1 M u2 a storey (a duel's) the rooms stand on two sides only, the galleries' other two sides against the
    # outer wall: a ring of rooms round a duel's atrium came out corridors (3 deep) or too large (4 deep: 3.3..3.6 M u2
    # of walk, the duel's band to 3.2 - pro_q2t4, a duel, has 3.11), 06.11; for more players (1.3 tried) the compact
    # tower's walks were too narrow (width median, sight pairs under their bands)
    compact = q["floor_area"] / n < 1.0
    w_side, h_side = int(side * rnd.uniform(0.92, 1.1)), int(side * rnd.uniform(0.92, 1.1))
    w_min = aw + 2 * gw + 2 if compact else aw + 2 * gw + 2 * 4 + 4
    h_min = ah + 2 * gw + 2 * 4 + 4
    W = w_min if compact else max(w_side, w_min)
    H = max(h_side, h_min)
    # a small floor asked of many storeys: the smallest tower (its atrium, galleries and a band of rooms) is larger -
    # the score does not hold that against the plan
    P.metrics["area_forced"] = W > w_side or H > h_side
    P.W, P.H = W, H
    ax0 = (W - aw) // 2 + (rnd.randint(-1, 1) if W > w_min + 1 else 0)
    ay0 = (H - ah) // 2 + (rnd.randint(-1, 1) if H > h_min + 1 else 0)
    A = pm.Rect(ax0, ay0, ax0 + aw, ay0 + ah)
    G = pm.Rect(A.x0 - gw, A.y0 - gw, A.x1 + gw, A.y1 + gw)  # gallery's outer edge (exclusive)
    inner = pm.Rect(1, 1, W - 1, H - 1)                      # inside the outer wall
    x_band = not compact
    if (x_band and (G.x0 < 6 or G.x1 > W - 6)) or G.y0 < 6 or G.y1 > H - 6:
        P.failed = "tower: no room round the atrium"
        return
    ceil_top = (n - 1) * SH + SH - SLAB                      # the top storey's ceiling
    top = ceil_top + 256                                     # the atrium's air over the top storey (under the sky)
    P._air = {}
    P._door_z = {}
    # shafts: two cells wide across the room band's whole depth (from the outer wall's side to the gallery's), apart
    # from each other - a 2 x 2 shaft in a deeper band left a strip of floor a cell wide round it (06.11); in a
    # compact tower at a band's end (a shaft in its middle cut a room two cells wide off, 06.11)
    shafts = []
    sides = []                       # brief 34: each shaft's band («y0» … «x1»): its gallery end
    # brief 34: a lift asked brings its shaft (the PO's «Небоскрёб» needs no shaft asked first); a shaft with neither a
    # lift nor a pad is not built (no pads asked, no lifts: «Башня с лестницами»)
    n_shafts = max(q["shafts"] - 1, max(0, int(q.get("lifts") or 0)))
    if not int(q.get("lifts") or 0) and not int(q.get("pads") or 0):
        n_shafts = 0
    for _ in range(n_shafts):
        for _try in range(200):
            band = rnd.choice(("y0", "y1", "x0", "x1") if x_band else ("y0", "y1"))
            if band in ("y0", "y1"):
                sx = rnd.choice((inner.x0, inner.x1 - 2)) if compact else rnd.randint(inner.x0 + 1, inner.x1 - 3)
                # its wall on the gallery's side is the gallery's own: a doorway onto the gallery (a shaft at a
                # band's end had no room beside it, 06.11)
                r = pm.Rect(sx, inner.y0 + 1, sx + 2, G.y0 - 1) if band == "y0" else pm.Rect(sx, G.y1 + 1, sx + 2, inner.y1 - 1)
            else:
                sy = rnd.randint(G.y0, G.y1 - 2)
                r = pm.Rect(inner.x0 + 1, sy, G.x0 - 1, sy + 2) if band == "x0" else pm.Rect(G.x1 + 1, sy, inner.x1 - 1, sy + 2)
            if r.x1 - r.x0 < 2 or r.y1 - r.y0 < 2:
                continue
            if all(pm_gap(r, o) >= 3 for o in shafts):
                shafts.append(r)
                sides.append(band)
                break
    # brief 34: the first «lifts» shafts hold a lift stopping on every storey - the shaft two cells square at its
    # gallery end (the cabin's size), the rest of the band its rooms'
    n_lifts = max(0, min(int(q.get("lifts") or 0), len(shafts)))
    for i in range(n_lifts):
        r, band = shafts[i], sides[i]
        shafts[i] = {"y0": pm.Rect(r.x0, G.y0 - 3, r.x0 + 2, G.y0 - 1), "y1": pm.Rect(r.x0, G.y1 + 1, r.x0 + 2, G.y1 + 3),
                     "x0": pm.Rect(G.x0 - 3, r.y0, G.x0 - 1, r.y0 + 2), "x1": pm.Rect(G.x1 + 1, r.y0, G.x1 + 3, r.y0 + 2)}[band]
    P.spaces = []
    sid = 0

    def new_space(kind, rect, k, cells, ceil, sky=False, atrium=False):
        nonlocal sid
        s = pm.Space(sid, kind, rect, base=k * SH, sky=sky, ceil=ceil)
        s.atrium = atrium
        s.floor = {key(c, k): (k * SH, "flat", 0, 0) for c in cells}
        P.spaces.append(s)
        for c in s.floor:
            P.owner[c] = sid
        for c in cells:
            P._air.setdefault(c, []).append((k * SH, ceil))
        sid += 1
        return s

    storeys = []
    for k in range(n):
        z = k * SH
        ceil = z + SH - SLAB
        rooms_cells = set(inner.cells()) - set(G.cells())
        wall = set()
        # the gallery's own wall: a line of cells round it, outside it
        ring_wall = {c for c in pm.Rect(G.x0 - 1, G.y0 - 1, G.x1 + 1, G.y1 + 1).cells() if not G.has(c)}
        wall |= ring_wall
        for r in shafts:
            wall |= {c for c in pm.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1).cells()}
        rooms_cells -= wall
        # rooms: the band cut by radial walls - a cut every 5..9 cells along each side
        cuts = set()
        for x in range(inner.x0 + rnd.randint(5, 8), inner.x1 - 4, rnd.randint(6, 10)):
            for y in list(range(inner.y0, G.y0 - 1)) + list(range(G.y1 + 1, inner.y1)):
                cuts.add((x, y))
        for y in range(inner.y0 + rnd.randint(5, 8), inner.y1 - 4, rnd.randint(6, 10)):
            for x in list(range(inner.x0, G.x0 - 1)) + list(range(G.x1 + 1, inner.x1)):
                cuts.add((x, y))
        rooms_cells -= cuts
        wall |= cuts
        # the rooms: the band's connected parts
        rooms = []
        left = set(rooms_cells)
        while left:
            seed_c = min(left)
            part, stack = set(), [seed_c]
            while stack:
                c = stack.pop()
                if c in part or c not in left:
                    continue
                part.add(c)
                stack.extend([(c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)])
            left -= part
            # a strip a cell or two across is no room (its doorways would be a corridor's): rock
            xs_, ys_ = [c[0] for c in part], [c[1] for c in part]
            if len(part) >= 9 and min(max(xs_) - min(xs_), max(ys_) - min(ys_)) >= 2:
                rooms.append(part)
        if k == 0:
            # the atrium: its air up through every storey under the sky; the ground gallery round it under the first
            # storey's floor - one floor, two ceilings, open to each other (P.joined)
            atrium = new_space("hall", A, 0, set(A.cells()), top, sky=True, atrium=True)
            gallery = new_space("corridor", G, 0, set(G.cells()) - set(A.cells()), ceil)
            P.joined.add(frozenset((atrium.id, gallery.id)))
        else:
            gal_cells = set(G.cells()) - set(A.cells())
            gallery = new_space("corridor", G, k, gal_cells, ceil)
        room_spaces = []
        for part in rooms:
            xs, ys = [c[0] for c in part], [c[1] for c in part]
            room_spaces.append(new_space("room", pm.Rect(min(xs), min(ys), max(xs) + 1, max(ys) + 1), k, part, ceil))
        storeys.append({"z": z, "ceil": ceil, "gallery": gallery, "rooms": room_spaces, "wall": wall})
    # the shafts: on the ground a tall narrow space (its air to the top), walled on the storeys above
    shaft_spaces = []
    for r in shafts:
        s = new_space("shaft", r, 0, set(r.cells()), top)
        shaft_spaces.append(s)
    # brief 34: the lifts' doorways - one on every storey, the cabin's width, onto the gallery (the cells in front of
    # them kept off the stairs)
    lift_doors = []
    for i in range(n_lifts):
        s_, band = shaft_spaces[i], sides[i]
        r = s_.rect
        if band in ("y0", "y1"):
            wall_y, out_y = (G.y0 - 1, G.y0) if band == "y0" else (G.y1, G.y1 - 1)
            wall_cells = [(r.x0, wall_y), (r.x0 + 1, wall_y)]
            fronts = [(r.x0, out_y), (r.x0 + 1, out_y)]
        else:
            wall_x, out_x = (G.x0 - 1, G.x0) if band == "x0" else (G.x1, G.x1 - 1)
            wall_cells = [(wall_x, r.y0), (wall_x, r.y0 + 1)]
            fronts = [(out_x, r.y0), (out_x, r.y0 + 1)]
        lift_doors.append((s_, wall_cells, fronts))
    keep_free = {c for (_s, _w, fr) in lift_doors for c in fr}
    # brief 34: a flight of steps from each storey's gallery up to the next one's (along the gallery's outer side, under
    # an opening in the floor above, two storeys tall), alternate storeys on opposite sides - the climb walks round
    n_stairs = n - 1 if int(q.get("stairs") if q.get("stairs") is not None else -1) < 0 else max(0, min(int(q["stairs"]), n - 1))
    run = SH // pm.RISE_PER_CELL
    stairs_made = []

    def doorable(k_, taken: set) -> dict:
        """Brief 34: each room of storey k_ - how many wall cells could hold its doorway onto the gallery (a room behind
        a stair's run lost them all and was left with one way in: 7 of 12 «Небоскрёб» plans, 08.11)."""
        gal = storeys[k_]["gallery"]
        out_ = {}
        for rs in storeys[k_]["rooms"]:
            n_ = 0
            for w in storeys[k_]["wall"]:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    a_, b_ = (w[0] - dx, w[1] - dy), (w[0] + dx, w[1] + dy)
                    if key(a_, k_) in rs.floor and key(b_, k_) in gal.floor and b_ not in taken:
                        n_ += 1
                        break
            out_[rs.id] = n_
        return out_
    side_order = ["y0", "y1", "x0", "x1"] if rnd.random() < 0.5 else ["x0", "x1", "y0", "y1"]
    for k in range(n_stairs):
        gal_lo, gal_hi = storeys[k]["gallery"], storeys[k + 1]["gallery"]
        ceil_hi = storeys[k + 1]["ceil"]
        placed_flight = False
        # the gallery's outer row first (the stair along the wall), then its middle row (a stair in the wide gallery,
        # a row to walk on each side of it) - an outer row the rooms' doorways need is left to them
        lines_ = []
        for depth in (0, 1):
            for side in side_order[k % 2::2] + side_order[(k + 1) % 2::2]:
                if side in ("y0", "y1"):
                    y = G.y0 + depth if side == "y0" else G.y1 - 1 - depth
                    lines_.append([(x, y) for x in range(G.x0, G.x1)])
                else:
                    x = G.x0 + depth if side == "x0" else G.x1 - 1 - depth
                    lines_.append([(x, y) for y in range(G.y0, G.y1)])
        for line in lines_:
            if rnd.random() < 0.5:
                line.reverse()
            for st0 in range(1, len(line) - run - 1):
                cells = line[st0:st0 + run]
                bottom, arrival = line[st0 - 1], line[st0 + run]
                if any(c in keep_free for c in cells + [bottom, arrival]):
                    continue
                if not all(key(c, k) in gal_lo.floor and key(c, k + 1) in gal_hi.floor for c in cells):
                    continue
                if key(bottom, k) not in gal_lo.floor or key(arrival, k + 1) not in gal_hi.floor:
                    continue
                # every room behind the run keeps three cells for its doorways on both storeys (or what it had)
                spoils = False
                for k_ in (k, k + 1):
                    before, after = doorable(k_, set(keep_free)), doorable(k_, set(keep_free) | set(cells))
                    if any(after[i] < min(3, before[i]) for i in before):
                        spoils = True
                        break
                if spoils:
                    continue
                ux, uy = cells[1][0] - cells[0][0], cells[1][1] - cells[0][1]
                for c in cells:
                    del gal_lo.floor[key(c, k)]
                    del P.owner[key(c, k)]
                    del gal_hi.floor[key(c, k + 1)]
                    del P.owner[key(c, k + 1)]
                    P._air[c] = [iv for iv in P._air.get(c, []) if iv[0] not in (k * SH, (k + 1) * SH)] + [(k * SH, ceil_hi)]
                xs, ys = [c[0] for c in cells], [c[1] for c in cells]
                sw = pm.Space(sid, "stair", pm.Rect(min(xs), min(ys), max(xs) + 1, max(ys) + 1), base=k * SH, ceil=ceil_hi)
                sw.floor = {key(c, k): (k * SH + pm.RISE_PER_CELL * j, "stair", ux, uy) for j, c in enumerate(cells)}
                P.spaces.append(sw)
                for c_ in sw.floor:
                    P.owner[c_] = sid
                sid += 1
                # walked onto at its foot from this storey, off at its top onto the next (two layers of the plan: the
                # graph's own arithmetic never steps between them)
                P.air_edges += [(key(bottom, k), key(cells[0], k), 0.25), (key(cells[0], k), key(bottom, k), 0.25),
                                (key(cells[-1], k), key(arrival, k + 1), 0.25), (key(arrival, k + 1), key(cells[-1], k), 0.25)]
                P.flights.append(set(sw.floor))
                # the opening in the floor over the stair is air there: a lamp by its edge would hang (the fixtures check)
                P.voids.update(key(c, k + 1) for c in cells)
                P.no_items.update(set(sw.floor) | {key(bottom, k), key(arrival, k + 1)})
                keep_free.update(cells + [bottom, arrival])
                stairs_made.append(k)
                P.reasons.append(("stair", f"лестница с этажа {k} на этаж {k + 1}"))
                placed_flight = True
                break
            if placed_flight:
                break
    P.metrics["stairs_got"] = len(stairs_made)
    if len(stairs_made) < n_stairs:
        P.metrics["refused"] = list(P.metrics.get("refused") or []) + [pm.say(
            f"лестниц между этажами {len(stairs_made)} из {n_stairs}: вдоль галерей не нашлось места, где пролёт не закрыл бы двери комнат",
            f"stairs between storeys {len(stairs_made)} of {n_stairs}: no room along the galleries where a flight would not close the rooms' doors")]
    # doors: each room to its gallery (one or two), some rooms to a neighbour, each shaft to a room on the ground
    doors_made = 0

    def door_between(sa, sb, k, cells_wall, away=None):
        """A one-cell doorway in the wall between two spaces of storey k: a wall cell with sa on one side, sb across
        (`away`: a door's cell this one is not beside - a room's second way in is another doorway)."""
        nonlocal doors_made
        opts = []
        door_cells_now = {dc for d_ in P.doors for dc in d_.cells}
        for c in cells_wall:
            if away is not None and abs(c[0] - away[0]) + abs(c[1] - away[1]) < 2:
                continue
            if key(c, k) in door_cells_now:
                continue
            for dx, dy in ((1, 0), (0, 1)):
                c1, c2 = (c[0] - dx, c[1] - dy), (c[0] + dx, c[1] + dy)
                o1, o2 = P.owner.get(key(c1, k)), P.owner.get(key(c2, k))
                # walled both sides along its wall: a doorway at a wall's end holds its lintel by one side - it
                # stood out of the wall (a duel 06.11, a room reaching round the cut's end)
                j1, j2 = (c[0] - dy, c[1] - dx), (c[0] + dy, c[1] + dx)
                jambs = all(P.owner.get(key(j, k)) is None and key(j, k) not in door_cells_now for j in (j1, j2))
                if {o1, o2} == {sa.id, sb.id} and jambs:
                    opts.append((c, o1, o2))
        if not opts:
            return None
        c, o1, o2 = rnd.choice(opts)
        d = pm.Door(sa.id, sb.id, [key(c, k)], za=k * SH, zb=k * SH, z=k * SH)
        P.doors.append(d)
        P._air.setdefault(c, []).append((k * SH, k * SH + pm.DOOR_H))
        doors_made += 1
        return d

    def ways(rs):
        return sum(1 for d_ in P.doors if rs.id in (d_.a, d_.b))

    # every room two ways in at least (the PO 05.11: «из неё нет выхода кроме как входа» - no dead-end room): its
    # gallery's door, then a neighbour's, else a second door to the gallery away from the first
    for k, st in enumerate(storeys):
        for rs in st["rooms"]:
            d1 = door_between(rs, st["gallery"], k, st["wall"])
            others = [o for o in st["rooms"] if o is not rs]
            rnd.shuffle(others)
            for other in others:
                if ways(rs) >= (3 if rnd.random() < 0.3 else 2):
                    break
                if any({d_.a, d_.b} == {rs.id, other.id} for d_ in P.doors):
                    continue
                door_between(rs, other, k, st["wall"])
            # one way so far: a second doorway, not beside the first, to the gallery or any neighbour (a room
            # hemmed in by a shaft's walls has one neighbour only, 06.11)
            first = next((d_ for d_ in P.doors if rs.id in (d_.a, d_.b)), None)
            for other in [st["gallery"]] + others:
                if ways(rs) >= 2 or first is None:
                    break
                door_between(rs, other, k, st["wall"], away=pm.phys(first.cells[0]))
            if ways(rs) < 2:
                P.failed = f"tower: a room of storey {k} with one way in"
                return
    for s in shaft_spaces[n_lifts:]:
        st0 = storeys[0]
        cells_wall = {c for c in pm.Rect(s.rect.x0 - 1, s.rect.y0 - 1, s.rect.x1 + 1, s.rect.y1 + 1).cells() if not s.rect.has(c)}
        for rs in st0["rooms"] + [st0["gallery"]]:
            if door_between(s, rs, 0, cells_wall):
                break
    # brief 34: the lifts - a cabin two cells square riding the shaft, stopping on every storey at its doorway (a
    # func_train on path corners, the builder's), the doorway the cabin's width onto the gallery
    for i, (s_, wall_cells, fronts) in enumerate(lift_doors):
        doors_k = []
        for k in range(n):
            if not all(key(f_, k) in storeys[k]["gallery"].floor for f_ in fronts):
                break
            d = pm.Door(s_.id, storeys[k]["gallery"].id, [key(c, k) for c in wall_cells], za=k * SH, zb=k * SH, z=k * SH)
            P.doors.append(d)
            for c in wall_cells:
                P._door_z[key(c, k)] = k * SH
                P._air.setdefault(c, []).append((k * SH, k * SH + pm.DOOR_H))
            doors_k.append(key(wall_cells[0], k))
        if len(doors_k) == n:
            P.trains.append((sorted(s_.floor), [k * SH for k in range(n)], doors_k, f"lift{i}"))
            P.no_items.update(key(f_, k) for f_ in fronts for k in range(n))
            P.reasons.append(("func_train", f"лифт в шахте: остановки на всех {n} этажах"))
    P.metrics["lifts_got"] = len(P.trains)
    # every room reached on its storey from its gallery (rooms behind rooms through their doors)
    nodes, edges = pm.plan_graph(P)
    for k, st in enumerate(storeys):
        g0 = next(iter(st["gallery"].floor))
        reach = pm.dijkstra(edges, g0)
        for rs in st["rooms"]:
            if not any(c in reach for c in rs.floor):
                P.failed = f"tower: a room of storey {k} with no door"
                return
    P.metrics["corridor_turns"] = n          # every gallery a ring round the atrium (four turns)
    # drops: from each gallery's inner edge down into the atrium (the ground's atrium cells under the hole)
    for k in range(1, n):
        gal = storeys[k]["gallery"]
        for c in gal.floor:
            pc = pm.phys(c)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n_ = (pc[0] + dx, pc[1] + dy)
                if A.has(n_) and n_ in P.owner:
                    P.air_edges.append((c, n_, round(CELL / 300.0 + math.sqrt(2 * k * SH / GRAVITY), 2)))
    # pads (brief 34, the PO 08.11: five pads a cell apart on the atrium's floor - «как кучу … выкатили в одном месте»;
    # pro_q2t4: one pad a corner, 527 u apart): from the atrium's corners only, one a corner, apart from each other;
    # the perches from the top gallery when a flight clears, else from a corner
    atrium_floor = list(A.cells())
    rnd.shuffle(atrium_floor)

    def z_of(c):
        return P.spaces[P.owner[c]].floor[c][0] if c in P.owner else P._door_z[c]

    def try_pads(srcs, tgts, why) -> bool:
        for a in srcs:
            if a in P.no_items or not pm.pad_spot_ok(P, a, z_of(a)):
                continue
            for t in tgts:
                if pad(P, a, t, top, margin=why == "perch"):
                    P.pad_why[(a, t)] = why
                    return True
        return False

    def gallery_landings(k):
        """Gallery cells of storey k next to the atrium's hole (the flight comes up through it and steps onto them)."""
        gal = storeys[k]["gallery"]
        out = []
        for c in gal.floor:
            pc = pm.phys(c)
            if any(A.has((pc[0] + dx, pc[1] + dy)) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                out.append(c)
        rnd.shuffle(out)
        return out

    # perches: 2 x 2 ledges in the atrium's corners over the top storey's ceiling - the rock over the galleries holds
    # each on two sides (a ledge between the storeys stood free in the air over the atrium and the builder, its column
    # one with the atrium's, gave it no slab - its powerup hung in the air, 06.11); only a pad reaches them
    perch_spaces = []
    corners = [(A.x0, A.y0), (A.x1 - 2, A.y0), (A.x0, A.y1 - 2), (A.x1 - 2, A.y1 - 2)]
    rnd.shuffle(corners)
    # placed before the pads: every flight is checked against the perches' slabs (a perch put over an earlier
    # pad's take-off stopped its flight at the slab, 06.11) - and no pad takes off under a perch
    rects = [pm.Rect(x, y, x + 2, y + 2) for (x, y) in corners[:min(q["perches"], len(corners))]]
    under = {c for r_ in rects for c in r_.cells()}
    atrium_floor[:] = [c for c in atrium_floor if c not in under]
    # brief 34: every perch's slab in the air first - a pad planned for one perch flew under the next one's slab,
    # put up after it (the fixtures check, 08.11: 2 of 3 pads landed)
    kept, zps = [], {}
    for i, r in enumerate(rects):
        zp = ceil_top + 32 + rnd.choice((0, 16, 32))
        if any(pm_gap(r, o) < 1 for (_i, o) in kept):
            continue
        kept.append((i, r))
        zps[i] = zp
    # brief 34: the corners no perch is over - the ground's lifts (the express); a perch's pad from the rim keeps three
    # cells from them (his tower 08.11: the third perch's rim pad took the free corner's room, the express not made)
    free_corners = [c for c in ((A.x0, A.y0), (A.x1 - 1, A.y0), (A.x0, A.y1 - 1), (A.x1 - 1, A.y1 - 1))
                    if c in atrium_floor and not any(r.has(c) for (_i, r) in kept)]
    was_all = {}
    for i, r in kept:
        for c in r.cells():
            was_all[c] = list(P._air.get(c, []))
            P.cell_ceil[c] = zps[i] - 32
            # the perch's air from its floor up; the atrium's column under it air up to its slab
            P._air[c] = [(lo, min(hi, zps[i] - 32)) for (lo, hi) in was_all[c] if lo < zps[i] - 32] + [(zps[i], top)]
    for i, r in kept:
        zp = zps[i]
        layer = n + i
        s = pm.Space(sid, "perch", r, base=zp, sky=True, ceil=top)
        s.floor = {key(c, layer): (zp, "flat", 0, 0) for c in r.cells()}
        was = {c: was_all[c] for c in r.cells()}
        P.spaces.append(s)
        for c in s.floor:
            P.owner[c] = sid
        sid += 1
        # the pad lands on the perch's cell off the corner (the atrium's middle side)
        mx, my = (A.x0 + A.x1) / 2, (A.y0 + A.y1) / 2
        tgt = min(s.floor, key=lambda c: abs(c[0] + 0.5 - mx) + abs(pm.phys(c)[1] + 0.5 - my))
        # brief 34: from the top gallery's edge over the atrium (the perch is a ledge over it), else from a corner
        top_edge = sorted(gallery_landings(n - 1), key=lambda c: abs(pm.phys(c)[0] - pm.phys(tgt)[0]) + abs(pm.phys(c)[1] - pm.phys(tgt)[1]))
        corner_cells = [c for c in ((A.x0, A.y0), (A.x1 - 1, A.y0), (A.x0, A.y1 - 1), (A.x1 - 1, A.y1 - 1)) if c in atrium_floor]
        # the corners stay the ground's lifts (pro_q2t4's): a perch's pad from the atrium's rim beside it, not a corner
        rim = sorted((c for c in atrium_floor if c not in corner_cells
                      and (not KEEP_FREE_CORNERS
                           or all(max(abs(c[0] - f[0]), abs(c[1] - f[1])) >= pm.PAD_APART for f in free_corners))),
                     key=lambda c: abs(c[0] - pm.phys(tgt)[0]) + abs(c[1] - pm.phys(tgt)[1]))
        # brief 34: from the top gallery beside the perch, up a well opened over that one cell to the sky (its
        # ceiling would stop the flight - a gallery pad has to clear it in a hand's breadth); the atrium's floor stays
        # the ground's (its corners: pro_q2t4's lifts)
        flew = False
        # the gallery's cells by the atrium within three cells of the perch, the nearer first - the flight rises over
        # open air (the well, the atrium) and comes down onto the ledge from above, never under its slab
        def gap_to_perch(c):
            return max(max(r.x0 - c[0], 0, c[0] - (r.x1 - 1)), max(r.y0 - c[1], 0, c[1] - (r.y1 - 1)))
        beside = sorted((pm.phys(c) for c in gallery_landings(n - 1) if 2 <= gap_to_perch(pm.phys(c)) <= 5), key=gap_to_perch)
        for nb in beside:
            kk = key(nb, n - 1)
            if kk in P.no_items or not pm.pad_spot_ok(P, kk, (n - 1) * SH):
                continue
            was_air = list(P._air.get(nb, []))
            P._air[nb] = [(lo, top if lo == (n - 1) * SH else hi) for (lo, hi) in was_air]
            P.cell_ceil[kk] = top
            if pad(P, kk, tgt, top, margin=True):
                P.pad_why[(kk, tgt)] = "perch"
                P.reasons.append(("trigger_push", f"на площадку над атриумом: с верхней галереи, в колодце к небу"))
                flew = True
                break
            P._air[nb] = was_air
            del P.cell_ceil[kk]
        if flew or try_pads(rim[:30], [tgt], "perch"):
            perch_spaces.append(s)
            # a way off: a drop back into the atrium
            P.air_edges.append((tgt, atrium_floor[0], round(math.sqrt(2 * zp / GRAVITY) + 0.2, 2)))
        else:
            P.spaces.pop()
            for c in s.floor:
                del P.owner[c]
            sid -= 1
            for c in r.cells():
                P._air[c] = was[c]
                del P.cell_ceil[c]
    corners = list(free_corners)
    rnd.shuffle(corners)

    def reach_k():
        """The storeys a man on the ground's gallery walks, rides and flies to (stairs, lifts, pads so far)."""
        nodes_, edges_ = pm.plan_graph(P)
        got = pm.dijkstra(edges_, next(iter(storeys[0]["gallery"].floor)))
        return {k for k in range(n) if any(c in got for c in storeys[k]["gallery"].floor)}

    def corner_pad(k, why) -> bool:
        lands = sorted(gallery_landings(k), key=lambda t: min(abs(pm.phys(t)[0] - c[0]) + abs(pm.phys(t)[1] - c[1]) for c in corners or [(0, 0)]))
        return try_pads(corners, lands[:16], why)

    want_pads = max(0, int(q.get("pads") or 0))
    # 1. the express: a corner up to the top gallery (q3dm17's long pads), when pads are asked
    made_pads = 0
    if want_pads and n >= 2 and corner_pad(n - 1, "express"):
        made_pads += 1
        P.reasons.append(("trigger_push", f"экспресс: из угла атриума на этаж {n - 1}"))
    # 2. a storey nothing else reaches: a pad up to it (a chain from the gallery under it, else a corner) - the only way
    only = 0
    for k in range(1, n):
        if k in reach_k():
            continue
        lower = [c for c in gallery_landings(k - 1)] if k - 1 in reach_k() and k >= 2 else []
        if (lower and try_pads(lower[:16], gallery_landings(k)[:16], "chain")) or corner_pad(k, "chain"):
            only += 1
            P.reasons.append(("trigger_push", f"джампад на этаж {k}: другого пути туда нет"))
    if only and not stairs_made and not P.trains:
        P.metrics["refused"] = list(P.metrics.get("refused") or []) + [pm.say(
            "наверх только джампадами: лестниц и лифтов не заказано", "up by jump pads only: no stairs and no lifts asked")]
    # 3. more pads asked: a corner each, to a storey no pad reaches yet - never two to one storey
    flown = {P.spaces[P.owner[t]].base // SH for (_a, t, *_r) in P.pads if t in P.owner}
    for k in range(1, n):
        if made_pads >= want_pads:
            break
        if k in flown:
            continue
        if corner_pad(k, "shortcut"):
            made_pads += 1
            flown.add(k)
    if want_pads > made_pads:
        P.metrics["refused"] = list(P.metrics.get("refused") or []) + [pm.say(
            f"джампадов с пола атриума {made_pads} из {want_pads}: по одному в углу, не больше одного на этаж",
            f"pads from the atrium's floor {made_pads} of {want_pads}: one a corner, one a storey at most")]
    if reach_k() != set(range(n)):
        P.failed = f"tower: storeys nothing reaches ({n - len(reach_k())})"
        return
    # the shafts' pads: from the shaft's bottom up through it to a doorway on an upper storey (a shaft with no lift)
    for s in shaft_spaces[n_lifts:]:
        k = rnd.randint(1, n - 1)
        st = storeys[k]
        # a doorway in the shaft's wall at storey k, onto a room or the gallery there
        cells_wall = {c for c in pm.Rect(s.rect.x0 - 1, s.rect.y0 - 1, s.rect.x1 + 1, s.rect.y1 + 1).cells() if not s.rect.has(c)}
        opts = []
        for c in cells_wall:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                inside, out = (c[0] - dx, c[1] - dy), (c[0] + dx, c[1] + dy)
                if s.rect.has(inside) and key(out, k) in P.owner:
                    opts.append((c, inside, out))
        rnd.shuffle(opts)
        for c, inside, out in opts:
            dk = key(c, k)
            d = pm.Door(s.id, P.owner[key(out, k)], [dk], za=k * SH, zb=k * SH, z=k * SH, kind="door")
            P._door_z[dk] = k * SH
            P._air.setdefault(c, []).append((k * SH, k * SH + pm.DOOR_H))
            far = (inside[0] - (c[0] - inside[0]), inside[1] - (c[1] - inside[1]))
            src = far if s.rect.has(far) else inside
            if pad(P, src, dk, top):
                P.pad_why[(src, dk)] = "shaft"
                P.doors.append(d)
                break
            P._air[c].pop()
            del P._door_z[dk]
    # the atrium over the ground is air on every storey and perch layer: no wall there for a lamp
    for k in range(1, n + q["perches"]):
        P.voids.update(key(c, k) for c in A.cells())
    P.metrics["perches"] = len(perch_spaces)
    if len(perch_spaces) < q["perches"]:
        P.metrics["refused"] = list(P.metrics.get("refused") or []) + [pm.say(
            f"площадок над атриумом {len(perch_spaces)} из {q['perches']}: к остальным не нашлось ни полёта джампада с "
            "верхней галереи, ни места на полу атриума в трёх клетках от других джампадов",
            f"ledges over the atrium {len(perch_spaces)} of {q['perches']}: no pad's flight from the top gallery reaches "
            "the rest, and the atrium's floor has no place three cells from the other pads")]
    P.metrics["shafts"] = 1 + len(shaft_spaces)
    P.metrics["storeys"] = n
    # every storey back down (drops) and up (pads): the whole tower strongly joined
    nodes, edges = pm.plan_graph(P)
    start = next(iter(storeys[0]["gallery"].floor))
    fwd = pm.dijkstra(edges, start)
    rev_edges = {}
    for a, es in edges.items():
        for b, w in es:
            rev_edges.setdefault(b, []).append((a, w))
    back = pm.dijkstra(rev_edges, start)
    lost = [s.id for s in P.spaces if not any(c in fwd and c in back for c in s.floor)]
    if lost:
        P.failed = f"tower: spaces not joined both ways ({len(lost)}: {', '.join(P.spaces[i].kind for i in lost)})"
        return
    teleporters(P, rnd, storeys)
    place(P, rnd, storeys, perch_spaces, shaft_spaces)
    if P.failed:
        return
    import mapgen_scratch_fixtures as fix_mod     # brief 32: the pads', frames' and plates' sizes
    fix_mod.plan_sizes(P)
    # the rooms' own lamps (mapgen_scratch_plan.light_space: lamps at the walls until no floor is dark) - a grid of
    # lamps under the ceilings left 84 % of a tower's floor dark (06.11, no sky to fill in)
    for s_ in P.spaces:
        # brief 34: a stair's slot is lit from the two galleries it joins - lamps of its own made a tower's screen
        # brighter than people's (his mg_new_18619 on 3.60: on screen 26, people's 7..25)
        if s_.kind != "stair":
            pm.light_space(P, s_)
    m = P.metrics
    m["floor_area"] = round(sum(len(s.floor) for s in P.spaces) * CELL * CELL / 1e6, 2)
    for k_ in ("stairs_got", "ramps_got", "drops_got", "windows_got", "stacked_rooms", "corridor_turns"):
        m.setdefault(k_, 0)
    m.setdefault("round", {})
    m.setdefault("mech_missing", [])
    m["pads"] = len(P.pads)
    # brief 34: the ways up by kind (the description's «Наверх»)
    m["ways"] = {"stairs": len(stairs_made), "lifts": len(P.trains),
                 "pads": sum(1 for (a, t, *_r) in P.pads if P.pad_why.get((a, t)) != "perch"),
                 "perch_pads": sum(1 for (a, t, *_r) in P.pads if P.pad_why.get((a, t)) == "perch")}
    m["pads_no_reason"] = len(pm.pads_without_reason(P))
    m["score"] = round(score(P), 2)
    del P._air
    del P._door_z


def teleporters(P: pm.Plan, rnd: random.Random, storeys: list) -> None:
    """As many pairs as asked, each between two rooms on different storeys the farthest apart on foot (a ground room
    and one high up): both ways, each arriving 3..5 cells from the other's pad (mapgen_scratch_plan.exit_cell)."""
    want = int(P.params.get("teleporters") or 0)
    if not want:
        P.metrics["teleporters"] = 0
        return
    import mapgen_scratch_fixtures as fix_mod
    nodes, edges = pm.plan_graph(P)
    rooms = [(k, c) for k, st in enumerate(storeys) for r in st["rooms"] for c in r.floor
             if c in edges and c not in P.no_items]
    rnd.shuffle(rooms)
    made = 0
    storey_of = {c: k for (k, c) in rooms}
    for _ in range(want):
        if pm.OLD_MOVER_RULES:
            best = None
            for ka, a in rooms[:30]:
                ta = pm.dijkstra(edges, a)
                for kb, b in rooms[:300]:
                    if kb == ka or P.owner[b] == P.owner[a] or b not in ta:
                        continue
                    if best is None or ta[b] > best[0]:
                        best = (ta[b], a, b)
            if not best:
                break
            walk_s, a, b = best
            da, db = pm.exit_cell(P, a), pm.exit_cell(P, b)
            if da is None or db is None:
                rooms = [r for r in rooms if r[1] not in (a, b)]
                continue
        else:
            # brief 35: the farthest pair whose ends keep apart from every mover and spawn and from the other pairs
            found = pm.pair_of_ends(P, [c for (_k, c) in rooms[:30]], [c for (_k, c) in rooms[:300]], edges,
                                    pair_ok=lambda a_, b_: storey_of.get(a_) != storey_of.get(b_))
            if found is None:
                break
            walk_s, a, b, da, db = found
        P.teleports.append((a, b, da, db))
        P.no_items.update({a, b, da, db})
        import mapgen_scratch_fixtures as fix_mod     # brief 26: the frames' posts stand beside the discs
        fix_mod.reserve_frame(P, a)
        fix_mod.reserve_frame(P, b)
        P.reasons.append(("misc_teleporter", f"пара телепортов между этажами, {walk_s:.1f} с пешком"))
        made += 1
        rooms = [r for r in rooms if r[1] not in P.no_items]
        # brief 34: no third teleporter within four cells of two
        discs = [((pm.phys(c)[0] + 0.5) * CELL, (pm.phys(c)[1] + 0.5) * CELL, nodes[c][0]) for tp in P.teleports for c in tp[:2] if c in nodes]
        rooms = [r for r in rooms if not fix_mod.crowded(discs, ((pm.phys(r[1])[0] + 0.5) * CELL, (pm.phys(r[1])[1] + 0.5) * CELL, nodes[r[1]][0]))]
    P.metrics["teleporters"] = made
    if made < want and not pm.OLD_MOVER_RULES:
        # brief 35: a pair not made is said (the rule keeps it from the places the others join)
        got = made
        P.metrics["refused"] = list(P.metrics.get("refused") or []) + [pm.say(f"телепортов (пар) {got} из {want}: ещё одна пара вела бы в те же места, что уже связанные, или стояла бы рядом "
               "с джампадом или точкой появления",
               f"teleporter pairs {got} of {want}: one more pair would join the places already joined, or stand beside a jump "
               "pad or a spawn point")]


def pm_gap(a: pm.Rect, b: pm.Rect) -> int:
    dx = max(b.x0 - a.x1, a.x0 - b.x1, 0)
    dy = max(b.y0 - a.y1, a.y0 - b.y1, 0)
    return max(dx, dy)


def place(P: pm.Plan, rnd: random.Random, storeys: list, perches: list, shafts: list) -> None:
    """Spawns on the rooms and galleries of every storey (1.2..2.4 s apart), the power items on the perches and the top
    storey, the guns over the storeys, ammo by its gun, small health and shards spread; powerups on pedestals."""
    q = P.params
    nodes, edges = pm.plan_graph(P)
    taken = set(P.no_items)
    door_cells = {c for d in P.doors for c in d.cells}
    movers = [a for (a, t, *_r) in P.pads] + [t for (a, t, *_r) in P.pads] + [c for tp in P.teleports for c in tp]

    def free(s) -> list:
        out = []
        for c in s.floor:
            if c in taken or c in door_cells or c not in edges:
                continue
            pc = pm.phys(c)
            near_door = any(pm.phys(d)[0] == pc[0] and abs(pm.phys(d)[1] - pc[1]) <= 1 or pm.phys(d)[1] == pc[1]
                            and abs(pm.phys(d)[0] - pc[0]) <= 1 for d in door_cells if pm.layer_of(d) == pm.layer_of(c))
            if not near_door:
                out.append(c)
        return out

    def put(cls, c, note=""):
        P.items.append((cls, c, P.spaces[P.owner[c]].floor[c][0], note))
        taken.add(c)

    walk = [s for st in storeys for s in [st["gallery"]] + st["rooms"]]
    want_sp = int(q["spawns"])
    def at(c):
        z = P.spaces[P.owner[c]].floor[c][0] if c in P.owner else P._door_z.get(c, 0)
        pc = pm.phys(c)
        return ((pc[0] + 0.5) * CELL, (pc[1] + 0.5) * CELL, z)
    # no spawn within 192 of a pad, its landing, a teleporter or its exit - in the world, storeys over each other
    # too (the judge's row; a spawn 2 x 2 cells off a pad is 181 away, 06.11)
    mover_at = [at(m) for m in movers]
    cands = [c for s in walk for c in free(s) if all(math.dist(at(c), m) > 224 for m in mover_at)]
    if not pm.OLD_MOVER_RULES:
        # brief 35: MOVER_APART from every disc, exit and pad (and no third plate - checked as each is picked)
        cands = [c for c in cands if pm.spot_ok(P, c, "spawn", pm.mover_marks(P, spawns=[]))]
    plates_steps = list(pm.PLATES_STEPS)
    rnd.shuffle(cands)
    spawns, t_from = [], {}

    def nearest_t(c):
        return min((t_from[s_].get(c, 1e9) for s_ in spawns), default=1e9)
    # the storeys in turn, the ground first (one starts on every storey: people's towers - pro_q2t4 - spawn on all
    # three; one by one by the time window ground spawns took 62..100 % of them, 06.11)
    turn = list(range(len(storeys)))
    i_turn = rnd.randrange(len(turn))
    pool = cands                 # every spot still free; `cands` - those of it the rule passes now
    while len(spawns) < want_sp and pool:
        k = turn[i_turn % len(turn)]
        i_turn += 1
        cands = pool
        if not pm.OLD_MOVER_RULES:
            # the spawns asked are never cut: the plates' radius gives when nothing is left at it (brief 35 item 20) -
            # each time from every free spot, not only those a stricter radius had left
            marks_now = pm.mover_marks(P, spawns=spawns)
            cands = [c for c in pool if pm.spot_ok(P, c, "spawn", marks_now, plates_near=plates_steps[0])]
            while not cands and len(plates_steps) > 1:
                plates_steps.pop(0)
                cands = [c for c in pool if pm.spot_ok(P, c, "spawn", marks_now, plates_near=plates_steps[0])]
            if not cands:
                break
        here = [c for c in cands if pm.layer_of(c) == k] or cands
        if not spawns:
            c = here[0]
        else:
            win = [c for c in here if 1.2 <= nearest_t(c) <= 2.4]
            c = max(win, key=lambda c: nearest_t(c) + rnd.random() * 0.3) if win else max(here, key=lambda c: min(nearest_t(c), 3.0) + rnd.random() * 0.3)
        pool.remove(c)
        spawns.append(c)
        t_from[c] = pm.dijkstra(edges, c)
        taken.add(c)
    if len(spawns) < max(2, want_sp // 2):
        P.failed = f"tower: room for {len(spawns)} spawns of {want_sp}"
        return
    P.metrics["plates_near"] = pm.PLATES_NEAR if pm.OLD_MOVER_RULES else plates_steps[0]
    for c in spawns:
        pc = pm.phys(c)
        P.spawns.append((c, P.spaces[P.owner[c]].floor[c][0], int(round(math.degrees(math.atan2(P.H / 2 - pc[1], P.W / 2 - pc[0])))) % 360))
    stack = pm.STACK_SETS.get(q["stack"], pm.STACK_SETS["ra_mh"]) if isinstance(q["stack"], str) else dict(q["stack"])
    order = []
    for cls in ("item_invulnerability", "item_quad", "item_health_mega", "item_armor_body"):
        order += [cls] * int(stack.get(cls, 0))
    hosts = list(perches) + [storeys[-1]["gallery"]] + list(reversed([r for st in storeys for r in st["rooms"]]))
    # the mega and the body armour on the storeys over the ground, in the spaces the spawns reach soonest (pro_q2t4:
    # majors at height 0.86, spawn to stack 2.8 s; on the perches and the top our duel towers' stack was 3.5..4.2 s
    # off, 06.11) - the perches and the top keep the powerups
    def soon(s):
        ts = sorted(min(t_from[sp].get(c, 1e9) for c in s.floor) for sp in spawns)
        return ts[len(ts) // 2]
    upper = sorted((sp_ for st in storeys[1:] for sp_ in [st["gallery"]] + st["rooms"]), key=lambda s: (soon(s), rnd.random()))
    P.pedestals = []
    sites = []
    for cls in order:
        near = cls in ("item_health_mega", "item_armor_body")
        for s in ([u for u in upper if u in hosts] if near else hosts):
            c = free(s)
            if c:
                cc = rnd.choice(c)
                put(cls, cc, "on a perch only a pad reaches" if s in perches else "high in the tower")
                if cls in pm.POWERUPS:
                    P.pedestals.append((cc, P.spaces[P.owner[cc]].floor[cc][0], cls))
                    sites.append((cls, "easy"))
                hosts.remove(s)
                break
    weapons = []
    for cls, k in (q.get("weapons") or {}).items():
        weapons += [cls] * int(k)
    # a perch no powerup took holds the railgun, then the rocket launcher (q3dm17's rail on a pad's island) - an
    # empty ledge only a pad reaches is a trip for nothing; one left after that, shards
    for s in [p_ for p_ in perches if p_ in hosts]:
        for cls in ("weapon_railgun", "weapon_rocketlauncher"):
            if cls in weapons and free(s):
                cc = rnd.choice(free(s))
                put(cls, cc, "on a perch only a pad reaches")
                weapons.remove(cls)
                ammo = pm.AMMO_OF.get(cls)
                if ammo and free(s):
                    put(ammo, rnd.choice(free(s)), "ammo by its gun")
                break
        else:
            for _ in range(2):
                if free(s):
                    put("item_armor_shard", rnd.choice(free(s)), "on a perch only a pad reaches")
        hosts.remove(s)
    others = [cls for cls in ("item_armor_combat", "item_armor_jacket", "item_adrenaline") for _ in range(int(stack.get(cls, 0)))]
    count = {s.id: 0 for s in P.spaces}
    pool = [s for st in storeys for s in st["rooms"] + [st["gallery"]]]
    for cls in others + weapons:
        pool.sort(key=lambda s: (count[s.id], rnd.random()))
        s = pool[0]
        c = free(s)
        if not c:
            continue
        cc = rnd.choice(c)
        put(cls, cc, "")
        count[s.id] += 1
        ammo = pm.AMMO_OF.get(cls)
        if ammo:
            near = [n_ for n_ in free(s) if abs(pm.phys(n_)[0] - pm.phys(cc)[0]) + abs(pm.phys(n_)[1] - pm.phys(cc)[1]) <= 4]
            if near:
                put(ammo, rnd.choice(near), "ammo by its gun")
    n_health = max(5, int(round(q["spawns"] * float(q.get("health_per_spawn") or 1.3))))
    for k in range(n_health):
        s = pool[k % len(pool)]
        c = free(s)
        if c:
            put("item_health_large" if rnd.random() < 0.3 else "item_health", rnd.choice(c), "small health")
    extra = max(0, int(q["spawns"] * float(q.get("ammo_per_spawn") or 2.5)) - sum(1 for it in P.items if it[0].startswith("ammo_")))
    ammos = [pm.AMMO_OF[w] for w in (q.get("weapons") or {}) if w in pm.AMMO_OF] or ["ammo_shells"]
    for k in range(extra):
        s = pool[(k * 3 + 1) % len(pool)]
        c = free(s)
        if c:
            put(ammos[k % len(ammos)], rnd.choice(c), "ammo")
    for k in range(int(q.get("shards") or 0)):
        s = pool[(k * 5 + 2) % len(pool)]
        c = free(s)
        if c:
            put("item_armor_shard", rnd.choice(c), "")
    P.metrics["powerup_sites"] = sites


def lights(P: pm.Plan) -> None:
    """A light every three cells under each storey's ceiling (and over the atrium's floor), 200."""
    for s in P.spaces:
        for c in s.floor:
            pc = pm.phys(c)
            if pc[0] % 3 == 1 and pc[1] % 3 == 1:
                z = s.floor[c][0]
                hz = min(z + 112, (s.ceil - 24) if not s.atrium else z + 160)
                P.lights.append(((pc[0] + 0.5) * CELL, (pc[1] + 0.5) * CELL, hz, 200))


def score(P: pm.Plan) -> float:
    q, m = P.params, P.metrics
    over = m.get("floor_area", 0) - q["floor_area"]
    # a tower forced larger than asked (its smallest form) is not held to the asked floor, but the smaller of them first
    # (4-player towers of 4.5..4.7 M u2 for 3.0 asked, the class's band to 4.6, 06.11)
    rel = max(0.0, abs(over) / q["floor_area"] - 0.15)
    pen = (1.5 * rel) if over > 0 and m.get("area_forced") else 6.0 * rel
    pen += 3.0 * max(0, q["perches"] - m.get("perches", 0))
    pen += 2.0 * max(0, q["shafts"] - m.get("shafts", 0))
    # brief 34: the ways asked and not made - the stairs, the lifts, the pads from the atrium's floor (a candidate with
    # more pads scored better here till 3.59: «джампады ради джампадов»)
    w, n = m.get("ways") or {}, q["storeys"]
    st = q.get("stairs")
    st_want = n - 1 if st is None or int(st) < 0 else min(int(st), n - 1)
    pen += 1.0 * max(0, st_want - w.get("stairs", 0))
    pen += 1.0 * max(0, int(q.get("lifts") or 0) - w.get("lifts", 0))
    pen += 1.0 * max(0, int(q.get("pads") or 0) - w.get("pads", 0))
    # brief 35: the spawns asked first (never cut for the movers' rule), then the pairs asked, then the plates' radius kept
    pen += 3.0 * max(0, int(q.get("spawns") or 0) - len(P.spawns))
    pen += 1.0 * max(0, int(q.get("teleporters") or 0) - len(P.teleports))
    pen += 0.3 * max(0, pm.PLATES_NEAR - int(m.get("plates_near", pm.PLATES_NEAR)))
    return pen
