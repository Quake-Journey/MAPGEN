r"""The PO 06.11 («можно делать так чтобы в мультиплейере летали корабли космические из сингла? … в космических картах
включать траектории полётов кораблей - опционально, и не только в космических»): ships of the single-player game
flying over a map from scratch - the parameter «ships» (0..3, none unless asked), any shape.

The game's own: `misc_viper` and `misc_strogg_ship` (g_misc.c, kept in deathmatch - only the NOT_DEATHMATCH spawnflag
drops an entity there) are trains that stay unseen (SVF_NOCLIENT) until used; used, they show and ride their
path_corners at their speed. One `trigger_always` uses them all at the start. Each flies one straight line and starts
it again: its first corner has spawnflag 1 (TELEPORT), so on reaching the far one the ship is put back at the start
and flies on (no wait anywhere - a ship waiting at a corner would hang in view). Solid to nothing: they push nobody.

Where: an open space's ships cross the whole sky box - over the highest island or under the lowest; a rooms map's (and
a tower's) over its largest courts under the sky, along the court's longest run of cells, under the sky with headroom
for the model, high over the players' heads. No court tall enough: no ship, and the record says so.
"""
from __future__ import annotations

import math
import random

from mapgen_scratch_build import CELL, Entity

import mapgen_scratch_plan as plan_mod

SHIP_CLASSES = ("misc_viper", "misc_strogg_ship")
SHIP_UNDER_SKY = 96         # the ship's origin this far under the sky (the model reaches some 60 over its origin)
SHIP_OVER_FLOOR = 192       # and at least this far over the court's floor (over a standing man's head and his jump)
SHIP_RUN_MIN = 6            # cells: a court shorter than this along its longest line gets no ship


def runs(cells: set) -> list:
    """The straight runs of cells (rows and columns), longest first: (length, start cell, end cell, axis)."""
    out = []
    for axis in (0, 1):
        lines = {}
        for c in cells:
            lines.setdefault(c[1 - axis], []).append(c[axis])
        for other, vs in lines.items():
            vs.sort()
            start = prev = vs[0]
            for v in vs[1:] + [None]:
                if v is not None and v == prev + 1:
                    prev = v
                    continue
                a = (start, other) if axis == 0 else (other, start)
                b = (prev, other) if axis == 0 else (other, prev)
                out.append((prev - start + 1, a, b, axis))
                if v is not None:
                    start = prev = v
    out.sort(key=lambda r: -r[0])
    return out


def court_lines(P, spaces: dict, spans: dict, want: int, rnd: random.Random) -> list:
    """Up to `want` lines (x0, y0, x1, y1, z) under the sky of the map's courts, the largest courts first, one a court
    while there are courts, then a second height in the same ones."""
    ph = plan_mod.phys
    courts = []
    for s in spaces.values():
        if not getattr(s, "sky", False) or not s.floor:
            continue
        floor = max(f[0] for f in s.floor.values())
        z = s.ceil - SHIP_UNDER_SKY
        if z - floor < SHIP_OVER_FLOOR:
            continue
        # the cells whose air reaches the ship's height (a perch's slab or a cell's own lower ceiling stops it)
        cells = {ph(c) for c in s.floor if any(a[0] <= z - 8 and a[1] >= z + 64 for a in spans.get(ph(c), []))} if spans \
            else {ph(c) for c in s.floor}
        rs = [r for r in runs(cells) if r[0] >= SHIP_RUN_MIN]
        if rs:
            courts.append((len(s.floor), rs, z, floor))
    courts.sort(key=lambda c: -c[0])
    out = []
    for level in range(2):
        for _n, rs, z, floor in courts:
            if len(out) >= want:
                return out
            zz = z - 64 * level
            if zz - floor < SHIP_OVER_FLOOR:
                continue
            length, a, b, axis = rs[min(level, len(rs) - 1)] if level == 0 else rs[len(rs) // 2]
            ax, ay = (a[0] + 0.5) * CELL, (a[1] + 0.5) * CELL
            bx, by = (b[0] + 0.5) * CELL, (b[1] + 0.5) * CELL
            if rnd.random() < 0.5:
                ax, ay, bx, by = bx, by, ax, ay
            out.append((ax, ay, bx, by, zz))
    return out


def box_lines(sky_box: tuple, islands_z: tuple, want: int, rnd: random.Random) -> list:
    """An open space's ships: lines across the sky box from wall to wall, over the highest island or under the lowest."""
    X0, Y0, Z0, X1, Y1, Z1 = sky_box
    lo, hi = islands_z
    heights = [h for h in (hi + 320, hi + 560, lo - 300) if Z0 + 96 <= h <= Z1 - 160]
    out = []
    for i in range(want):
        z = heights[i % len(heights)] if heights else (Z0 + Z1) / 2
        if rnd.random() < 0.5:
            y = rnd.uniform(Y0 + 0.25 * (Y1 - Y0), Y0 + 0.75 * (Y1 - Y0))
            a, b = (X0 + 96, y), (X1 - 96, y)
        else:
            x = rnd.uniform(X0 + 0.25 * (X1 - X0), X0 + 0.75 * (X1 - X0))
            a, b = (x, Y0 + 96), (x, Y1 - 96)
        if rnd.random() < 0.5:
            a, b = b, a
        out.append((a[0], a[1], b[0], b[1], z))
    return out


def ship_entities(P, spaces: dict, spans: dict, sky_box: tuple | None = None, islands_z: tuple | None = None) -> list:
    """The ships asked (P.params["ships"]) as entities; P.metrics["ships"] the number flying, a note when fewer."""
    want = max(0, min(3, int(P.params.get("ships") or 0)))
    P.metrics["ships"] = 0
    if not want:
        return []
    rnd = random.Random(P.seed * 7 + 11)
    lines = box_lines(sky_box, islands_z, want, rnd) if sky_box else court_lines(P, spaces, spans, want, rnd)
    ents = []
    for i, (ax, ay, bx, by, z) in enumerate(lines):
        name = f"mg_ship{i + 1}"
        yaw = round(math.degrees(math.atan2(by - ay, bx - ax))) % 360
        ents.append(Entity({"classname": SHIP_CLASSES[i % len(SHIP_CLASSES)], "targetname": "mg_ships",
                            "target": f"{name}_a", "speed": str(rnd.choice((250, 300, 350, 400))), "angle": str(yaw)}))
        # the start: TELEPORT - reaching the end, the ship is put back here and flies on
        ents.append(Entity({"classname": "path_corner", "targetname": f"{name}_a", "target": f"{name}_b", "spawnflags": "1",
                            "origin": f"{int(ax)} {int(ay)} {int(z)}"}))
        ents.append(Entity({"classname": "path_corner", "targetname": f"{name}_b", "target": f"{name}_a",
                            "origin": f"{int(bx)} {int(by)} {int(z)}"}))
    if ents:
        ents.append(Entity({"classname": "trigger_always", "target": "mg_ships"}))
    P.metrics["ships"] = len(lines)
    if len(lines) < want:
        P.metrics["refused"] = list(P.metrics.get("refused") or []) + [plan_mod.say(
            f"корабли в небе: {len(lines)} из {want} - над картой нет двора под небом достаточно высокого и длинного",
            f"ships in the sky: {len(lines)} of {want} - the map has no court under the sky tall and long enough")]
    return ents
