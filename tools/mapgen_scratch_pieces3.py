"""Scripted pieces, part 3 - the PO 13.11 after the first try: «я просил тебя подойти творчески ... делать вариации»,
«буры ... что тоннели в землю роют - для колодцев и фундамента», «вот на той же q2dm8 есть движущееся полотно наверху
карты где ящики ездят ... это может быть как полезное, так и декоративное, но на выходе получаться интересные и
уникальные карты», «посмотри вот например в синг картах тоже приемчики» (tools/mapgen_sp_mover_practice.py: the
game's own 39 single-player maps - timers firing sparks and explosions, lasers, blasters, sounds of machines),
«ты можешь вообще подходить так творчески к генерации что получать что то невообразимое ... главное чтобы играть потом
можно было».

* drills - a rig over an auger boring into the floor: the auger spins (func_rotating, it hurts), a collar rides up and
  down it on a timer, sparks fly at its foot (target_splash on a timer), the drill's own sound (target_speaker). The rig
  a four-post tower, an A-frame, a cross frame or a gantry; the auger's radius, flights, starts and height drawn.
* cogs - two or three cog wheels high on a hall's wall, meshing: each turns against its neighbour at the speed its
  teeth give (a machine's sound by them). Decoration that moves.
* turrets - blasters in a passage's wall (target_blaster) firing across it on timers out of phase: one runs between the
  bolts (single-player's blaster traps, base3).
* conveyors - a belt along a hall's wall (its floor pulls: CURRENT) with crates riding it out of one wall and into the
  other (func_train through the walls), as on q2dm8; one rides the crates. The belt on the floor or on a ledge; the
  crates boxes, banded crates or barrels, two to four of them.

Each kind's form and sizes are drawn from the plan's own numbers - no two maps hold the same piece.
"""
from __future__ import annotations

import math
import random

import mapgen_scratch_forms as forms
import mapgen_scratch_pieces as base_mod
from mapgen_scratch_pieces import CELL, Names, bx, cb, ent, mid, record, say, speed, wait

KINDS3 = ("drills", "cogs", "turrets", "conveyors")
NAMES_RU = {"drills": "буровая установка", "cogs": "шестерни на стене", "turrets": "турели в проходе",
            "conveyors": "конвейер с грузами"}


# the RED: 3.68's conveyors before the housings - the crates turned back through the wall, their teleport corners in
# rock (the test map mg_new_368_mach5: the engine's round trip drops a path_corner in rock, «4 mover records have no
# counterpart», three of its four best candidates refused); MAPGEN_OLD_BELT_CORNERS=1 for a process
OLD_BELT_CORNERS = __import__("os").environ.get("MAPGEN_OLD_BELT_CORNERS") == "1"


def defaults(q: dict) -> None:
    for k, hi in (("drills", 3), ("cogs", 3), ("turrets", 2), ("conveyors", 2)):
        try:
            q[k] = max(0, min(hi, int(q.get(k) or 0)))
        except (TypeError, ValueError):
            q[k] = 0


def after_items(P, rnd: random.Random, held: set, pits: list, used: set, times_of) -> None:
    q = P.params
    for kind, fn in (("conveyors", conveyors), ("drills", drills), ("turrets", turrets), ("cogs", cogs)):
        for _ in range(q.get(kind, 0)):
            if not fn(P, rnd, held):
                P.notes.append(say(f"{NAMES_RU[kind]}: на этом каркасе для неё нет места",
                                   f"{kind}: no room for it on this skeleton"))
                break


def _speaker(noise: str, at, volume: float = 0.8, atten: int = 2) -> dict:
    """A looped sound of a machine (target_speaker, spawnflags 1: on from the start)."""
    return ent({"classname": "target_speaker", "noise": noise, "spawnflags": 1, "volume": volume, "attenuation": atten,
                "origin": f"{at[0]:.0f} {at[1]:.0f} {at[2]:.0f}"})


def _timer(name, w, delay=0.0, rand=0.0, origin=(0, 0, 0)) -> dict:
    keys = {"classname": "func_timer", "target": name, "spawnflags": 1, "wait": round(w, 2),
            "origin": f"{origin[0]:.0f} {origin[1]:.0f} {origin[2]:.0f}"}
    if delay:
        keys["delay"] = round(delay, 2)
    if rand:
        keys["random"] = round(rand, 2)
    return ent(keys)


def _flat_halls(P, min_h: int):
    plan_mod = base_mod.pm()
    return [s for s in P.spaces if not s.solid and s.kind in ("hall", "room") and s.floor and s.ceil - s.base >= min_h
            and not s.atrium and plan_mod.layer_of(next(iter(s.floor))) == 0]


def _plain_first(P, halls: list) -> list:
    """The halls shuffled already, the plain ones (closed boxes: «голые стены, аптечка в конце», the PO 05.11) first and
    those with no piece yet next: a machine gives a bare room something to look at (the test map mg_new_368_mach3 kept
    a plain room while its cogs and drill stood in others)."""
    if base_mod.OLD_PLAIN_PIECES:
        return halls
    plain = {s.id for s in base_mod.pm().plain_spaces(P)}
    taken = {r.get("space") for r in getattr(P, "pieces", [])}
    halls.sort(key=lambda s: (s.id not in plain, s.id in taken))
    return halls


# --------------------------------------------------------------------------------------------- drills
def drills(P, rnd, held) -> bool:
    door_cells = {c for d in P.doors for c in d.cells}
    halls = _flat_halls(P, 224)
    rnd.shuffle(halls)
    _plain_first(P, halls)
    its = [c for (cls, c, z, note) in P.items if cls in base_mod.GUARD_ITEMS]
    for s in halls:
        flat = (s.base, "flat", 0, 0)
        cand = [c for c, f in s.floor.items() if f == flat and c not in held and c not in P.no_items
                and all(s.floor.get((c[0] + dx, c[1] + dy)) == flat and (c[0] + dx, c[1] + dy) not in held
                        and (c[0] + dx, c[1] + dy) not in door_cells for dx in (-1, 0, 1) for dy in (-1, 0, 1))]
        if not cand:
            continue
        # by a valuable item when one is near (a drill boring by the prize), else anywhere free
        cand.sort(key=lambda c: (min((abs(c[0] - i[0]) + abs(c[1] - i[1]) for i in its), default=9) < 2,
                                 min((abs(c[0] - i[0]) + abs(c[1] - i[1]) for i in its), default=9), rnd.random()))
        c = cand[0]
        cx, cy = base_mod.mid(c)
        base = s.base
        top_room = P.cell_ceil.get(c, s.ceil)
        r = rnd.choice((18, 22, 26, 30))
        height = min(rnd.choice((112, 136, 160, 184)), top_room - base - 72)
        z0, z1 = base - 40, base + height
        rig = rnd.choice(forms.DRILL_RIGS)
        rig_top = min(top_room - 16, z1 + rnd.choice((24, 40, 56)))
        names = Names(P)
        rec = record(P, "drills", cells=[c], space=s.id, variant=f"{rig}/r{r}")
        auger = forms.drill_auger(cx, cy, z0, z1, r, rnd.choice((3, 4, 5)), rnd.choice((1, 2, 2, 3)), rnd)
        spin = rnd.choice((160, 240, 320))
        fl_auger = 1 | 16 | (2 if rnd.random() < 0.5 else 0)
        for grp in base_mod.body_groups(auger):          # bodies apart, turning as one
            rec["ents"].append(ent({"classname": "func_rotating", "origin": f"{cx:.0f} {cy:.0f} {base:.0f}",
                                    "speed": spin, "spawnflags": fl_auger, "dmg": 8}, grp))
        # the collar riding the auger on a timer: up the drill and back (as the rig pushes it down)
        tn = names("collar")
        travel = max(48, (z1 - base) * 0.55)
        ring = [] if forms.OLD_NEAR_FACES else forms.nice_ring(cx, cy, r + 6, r + 14, "z", base + 24, base + 36, "drill collar")
        for k in (range(8) if forms.OLD_NEAR_FACES else ()):
            a0 = 2 * math.pi * k / 8
            a1 = 2 * math.pi * (k + 1) / 8
            p0 = (cx + (r + 10) * math.cos(a0), cy + (r + 10) * math.sin(a0))
            p1 = (cx + (r + 10) * math.cos(a1), cy + (r + 10) * math.sin(a1))
            ring.append(forms.prism("z", forms.thin_bar(p0, p1, 4), base + 24, base + 36, "trim", 1, "drill collar"))
        sp_collar = speed(P, rnd.choice((40, 60, 80)))
        for grp in base_mod.body_groups(ring):           # bodies apart, one name: they ride as one
            rec["ents"].append(ent({"classname": "func_door", "targetname": tn, "angle": -1, "lip": 12 - travel,
                                    "speed": sp_collar, "spawnflags": 32}, grp))
        rec["ents"].append(_timer(tn, wait(P, rnd.choice((2.0, 2.5, 3.0))), origin=(cx, cy, base + 48)))
        # sparks at its foot, now and then; its sound
        sp = names("sparks")
        rec["ents"].append(ent({"classname": "target_splash", "targetname": sp, "sounds": 1, "count": rnd.choice((8, 12, 16)),
                                "angle": -1, "origin": f"{cx + r + 6:.0f} {cy:.0f} {base + 4:.0f}"}))
        rec["ents"].append(_timer(sp, rnd.choice((0.6, 0.9, 1.3)), rand=0.4, origin=(cx, cy, base + 16)))
        rec["ents"].append(_speaker(rnd.choice(("world/drill1.wav", "world/drill2a.wav", "world/driller1.wav")),
                                    (cx, cy, base + 64)))
        rec["brushes"] += forms.drill_rig(rig, cx, cy, base, rig_top, rnd.choice((40, 48, 56)))
        held.update({(c[0] + dx, c[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)})
        P.no_items.add(c)
        P.reasons.append(("func_rotating", say(f"буровая установка ({_rig_ru(rig)}) в зале {s.id}: бур вращается и ранит, хомут ездит по нему",
                                               f"a drilling rig ({rig}) in hall {s.id}: the auger spins and hurts, a collar rides it")))
        return True
    return False


def _rig_ru(k):
    return {"tower": "вышка", "aframe": "А-образная рама", "cross": "крестовина", "tripod": "тренога",
            "gantry": "портал"}.get(k, k)


# --------------------------------------------------------------------------------------------- cogs
def _walls(P, s, held):
    """A hall's wall runs: (cells along the wall, the outward step, the wall face coordinate) with rock behind, no door,
    no window, nothing held - three cells long at least."""
    windows = {c for (cs, *_w) in P.windows for c in cs}
    doors = {c for d in P.doors for c in d.cells}
    out = []
    for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        line = sorted(c for c, f in s.floor.items() if (c[0] + d[0], c[1] + d[1]) not in s.floor
                      and P.owner.get((c[0] + d[0], c[1] + d[1])) is None
                      and (c[0] + d[0], c[1] + d[1]) not in windows and (c[0] + d[0], c[1] + d[1]) not in doors
                      and c not in doors)
        run = []
        for c in line + [None]:
            if c is not None and run and (abs(c[0] - run[-1][0]) + abs(c[1] - run[-1][1]) == 1):
                run.append(c)
                continue
            if len(run) >= 3:
                out.append((run, d))
            run = [c] if c is not None else []
    return out


def cogs(P, rnd, held) -> bool:
    halls = _flat_halls(P, 256)
    rnd.shuffle(halls)
    _plain_first(P, halls)
    for s in halls:
        for run, d in _walls(P, s, held):
            n = rnd.choice((2, 2, 3))
            if len(run) < 2 * n - 1:
                continue
            k0 = rnd.randint(0, len(run) - (2 * n - 1))
            c0 = run[k0]
            x0, y0, x1, y1 = cb(c0)
            face = x1 if d == (1, 0) else x0 if d == (-1, 0) else y1 if d == (0, 1) else y0
            axis = "x" if d[0] else "y"
            out = -1 if (d[0] > 0 or d[1] > 0) else 1          # into the room from the wall
            # the cogs along the wall: radii drawn, centres touching tooth to tooth, high over the floor
            top = P.cell_ceil.get(c0, s.ceil)
            # the top tooth under the cornice (12 under the ceiling, 8 proud): 92 under the ceiling at most
            zc = rnd.uniform(s.base + 128, max(s.base + 136, top - (72 if base_mod.OLD_SWEEP else 92)))
            along0 = (mid(c0)[1] if d[0] else mid(c0)[0]) - CELL / 2 + 8
            names = Names(P)
            rec = record(P, "cogs", cells=list(run[k0:k0 + 2 * n - 1]), space=s.id, variant=f"{n}")
            ab = along0
            teeth_prev = None
            spin0 = rnd.choice((24, 36, 48))
            reverse = rnd.random() < 0.5
            room_len = (2 * n - 1) * CELL - 16
            radii = [rnd.choice((32, 40, 48, 56)) for _ in range(n)]
            need = sum(2 * r + 10 for r in radii)
            if need > room_len:
                radii = [max(24, int(r * room_len / need)) for r in radii]
            for i in range(n):
                r = radii[i]
                teeth = max(8, int(r / 4.5))
                ab = ab + r if i == 0 else ab + r + 10
                zz = zc + (rnd.choice((-24, 0, 24)) if i else 0)
                lo = face + out * 2
                hi = face + out * rnd.choice((10, 14))
                parts = forms.cog(axis, ab, zz, r, teeth, min(lo, hi), max(lo, hi))
                # meshing: each turns against its neighbour, at the speed its teeth give
                sp = spin0 * (14 / teeth) if forms.OLD_NEAR_FACES else spin0 * (40.0 / r)   # eight teeth each: by its size
                flags = 1 | (4 if axis == "x" else 8) | (2 if (reverse ^ (i % 2 == 1)) else 0)
                ox, oy = (face, ab) if axis == "x" else (ab, face)
                for grp in base_mod.body_groups(parts):  # bodies apart, turning as one
                    rec["ents"].append(ent({"classname": "func_rotating", "origin": f"{(lo + hi) / 2 if axis == 'x' else ox:.0f} "
                                            f"{oy if axis == 'x' else (lo + hi) / 2:.0f} {zz:.0f}",
                                            "speed": round(sp, 1), "spawnflags": flags}, grp))
                ab += r
                teeth_prev = teeth
            if not base_mod.OLD_SWEEP:
                # the PO 13.11 (Bugs/4: cogs turning through a pilaster): each wheel turned all the way round must
                # meet nothing; else this run is given up and the cells stay free
                bad = False
                for e_ in rec["ents"]:
                    t_ = base_mod.turn_of(e_["keys"])
                    if t_ and base_mod.sweep(P, s.id, e_["brushes"], t_[0], t_[1], t_[2], skip={id(rec)})[0]:
                        bad = True
                        break
                if bad:
                    P.pieces.remove(rec)
                    continue
                held.update(rec["cells"])
                P.no_items.update(rec["cells"])
            mz = zc
            mx, my = (face + out * 24, along0 + 64) if axis == "x" else (along0 + 64, face + out * 24)
            rec["ents"].append(_speaker(rnd.choice(("world/mach1.wav", "world/mach2.wav", "world/mach3.wav")), (mx, my, mz), 0.6, 3))
            P.reasons.append(("func_rotating", say(f"{n} шестерни на стене зала {s.id} крутятся, сцепленные зубьями",
                                                   f"{n} cogs on hall {s.id}'s wall turning, meshed tooth to tooth")))
            return True
    return False


# --------------------------------------------------------------------------------------------- turrets
def turrets(P, rnd, held) -> bool:
    cands = base_mod.passages(P, held, (1, 2))
    rnd.shuffle(cands)
    for s, cross, d in cands:
        # the wall at one end of the passage's cross-section (rock beyond it): two or three blasters in it, side by
        # side along the passage, firing across it in turn
        crossdir = (0, 1) if d[0] else (1, 0)
        side = rnd.choice((1, -1))
        e = cross[-1] if side > 0 else cross[0]
        w_ = (e[0] + side * crossdir[0], e[1] + side * crossdir[1])
        if w_ in s.floor or P.owner.get(w_) is not None:
            side = -side
            e = cross[-1] if side > 0 else cross[0]
            w_ = (e[0] + side * crossdir[0], e[1] + side * crossdir[1])
            if w_ in s.floor or P.owner.get(w_) is not None:
                continue
        z = s.floor[e][0]
        n = rnd.choice((2, 3))
        names = Names(P)
        rec = record(P, "turrets", cells=list(cross), space=s.id, variant=f"{n}")
        w = wait(P, rnd.choice((1.5, 2.0, 2.5)))
        x0, y0, x1, y1 = cb(e)
        zz = z + rnd.choice((32, 40, 48))
        for i in range(n):
            if crossdir == (0, 1):
                face = y1 if side > 0 else y0
                px = x0 + (i + 1) * (x1 - x0) / (n + 1)
                house = bx((px - 9, min(face, face - side * 12), zz - 9), (px + 9, max(face, face - side * 12), zz + 9), "trim",
                           note="turret")
                origin = (px, face - side * 18, zz)
                angle = 270 if side > 0 else 90
            else:
                face = x1 if side > 0 else x0
                py = y0 + (i + 1) * (y1 - y0) / (n + 1)
                house = bx((min(face, face - side * 12), py - 9, zz - 9), (max(face, face - side * 12), py + 9, zz + 9), "trim",
                           note="turret")
                origin = (face - side * 18, py, zz)
                angle = 180 if side > 0 else 0
            rec["brushes"].append(house)
            tn = names("blaster")
            rec["ents"].append(ent({"classname": "target_blaster", "targetname": tn, "angle": angle, "dmg": 12,
                                    "speed": 900, "origin": f"{origin[0]:.0f} {origin[1]:.0f} {origin[2]:.0f}"}))
            rec["ents"].append(_timer(tn, w, delay=0.4 + i * w / n, origin=origin))
        held.update(cross)
        P.reasons.append(("target_blaster", say("турели в стене прохода стреляют по очереди - пробегать между выстрелами",
                                                "turrets in a passage's wall firing in turn - one runs between the bolts")))
        return True
    return False


# --------------------------------------------------------------------------------------------- conveyors
def conveyors(P, rnd, held) -> bool:
    halls = _flat_halls(P, 224)
    rnd.shuffle(halls)
    _plain_first(P, halls)
    door_cells = {c for d in P.doors for c in d.cells}
    for s in halls:
        flat = (s.base, "flat", 0, 0)
        for run, d in _walls(P, s, held):
            # the belt along the wall: the whole run, both ends at a wall across it (rock beyond the run's ends)
            keep = [c for c in run if s.floor.get(c) == flat and c not in held and c not in P.no_items]
            if base_mod.OLD_BELT_OVER_ITEMS:
                run = keep
            else:
                # the free cells in one unbroken line: a held cell in the middle splits it (the test map
                # mg_new_368_mach4: the cell of its shotgun dropped out of the run, the belt laid from end to end over
                # it - the gun «lost at spawn» in the belt)
                chunks, cur = [], []
                for c in keep:
                    if cur and abs(c[0] - cur[-1][0]) + abs(c[1] - cur[-1][1]) != 1:
                        chunks.append(cur)
                        cur = []
                    cur.append(c)
                if cur:
                    chunks.append(cur)
                run = max(chunks, key=len) if chunks else []
            if len(run) < 4:
                continue
            ax = 0 if run[0][1] == run[-1][1] else 1           # the belt's way: along x (0) or y (1)
            a_end = (run[0][0] - (1 if ax == 0 else 0), run[0][1] - (1 if ax == 1 else 0))
            b_end = (run[-1][0] + (1 if ax == 0 else 0), run[-1][1] + (1 if ax == 1 else 0))
            if a_end in s.floor or b_end in s.floor or P.owner.get(a_end) is not None or P.owner.get(b_end) is not None:
                continue
            if any((c[0] - d[0], c[1] - d[1]) in door_cells for c in run):
                continue
            raised = rnd.random() < 0.45
            h = rnd.choice((64, 96)) if raised else 8
            if raised and P.cell_ceil.get(run[0], s.ceil) - s.base < h + 160:
                raised, h = False, 8
            base = s.base
            xs = [cb(c)[0] for c in run] + [cb(c)[2] for c in run]
            ys = [cb(c)[1] for c in run] + [cb(c)[3] for c in run]
            X0, Y0, X1, Y1 = min(xs), min(ys), max(xs), max(ys)
            names = Names(P)
            rec = record(P, "conveyors", cells=list(run), space=s.id, variant=f"{'ledge' if raised else 'floor'}/{len(run)}")
            if raised:
                rec["brushes"].append(bx((X0, Y0, base), (X1, Y1, base + h - 2), "trim", contents=1, note="conveyor ledge"))
            # the belt: its floor pulls the way the crates ride (CURRENT, a flowing texture)
            import mapgen_scratch_pieces2 as second
            flag = second.CURRENT_FLAGS[(1, 0) if ax == 0 else (0, 1)]
            rec["brushes"].append(bx((X0, Y0, base + h - 2), (X1, Y1, base + h), "current", contents=1 | flag,
                                     note="conveyor belt"))
            # the crates: their kind, number, size and speed
            kind = rnd.choice(("box", "banded", "barrel"))
            n = rnd.choice((2, 3, 4))
            size = rnd.choice((40, 48))
            spd = speed(P, rnd.choice((48, 64, 80)))
            # the housings at both ends (q2dm8's crates come out of a box and go into one), over the belt's end cells:
            # side walls on the belt, a roof on them, open toward the belt's middle; the crates turn back inside them -
            # their corners in air, which the engine's round trip of the finished map keeps
            tall = int(size * 1.2) if kind == "barrel" else size
            top_ = base + h + 1 + tall + 10
            for c_end in (() if OLD_BELT_CORNERS else (run[0], run[-1])):
                x0c, y0c, x1c, y1c = cb(c_end)
                if ax == 0:
                    sides_ = (((x0c, y0c, base + h), (x1c, y0c + 4, top_)), ((x0c, y1c - 4, base + h), (x1c, y1c, top_)))
                else:
                    sides_ = (((x0c, y0c, base + h), (x0c + 4, y1c, top_)), ((x1c - 4, y0c, base + h), (x1c, y1c, top_)))
                for lo_, hi_ in sides_:
                    rec["brushes"].append(bx(lo_, hi_, "trim", contents=1, note="conveyor housing"))
                rec["brushes"].append(bx((x0c, y0c, top_), (x1c, y1c, top_ + 8), "trim", contents=1, note="conveyor housing roof"))
            for e_ in ((0, 1) if OLD_BELT_CORNERS else ()):
                fx = X0 if e_ == 0 else X1
                fy = Y0 if e_ == 0 else Y1
                # a frame round the opening: two jambs on the belt and a lintel on them (nothing hangs)
                if ax == 0:
                    rec["brushes"].append(bx((fx - 4, Y0, base + h), (fx + 4, Y0 + 8, base + h + 64), "trim", note="tunnel jamb"))
                    rec["brushes"].append(bx((fx - 4, Y1 - 8, base + h), (fx + 4, Y1, base + h + 64), "trim", note="tunnel jamb"))
                    rec["brushes"].append(bx((fx - 4, Y0, base + h + 64), (fx + 4, Y1, base + h + 76), "trim", note="tunnel lintel"))
                else:
                    rec["brushes"].append(bx((X0, fy - 4, base + h), (X0 + 8, fy + 4, base + h + 64), "trim", note="tunnel jamb"))
                    rec["brushes"].append(bx((X1 - 8, fy - 4, base + h), (X1, fy + 4, base + h + 64), "trim", note="tunnel jamb"))
                    rec["brushes"].append(bx((X0, fy - 4, base + h + 64), (X1, fy + 4, base + h + 76), "trim", note="tunnel lintel"))
            # each crate out of the start housing, along the belt, into the end one - and back to the start in no time (a
            # path_corner's teleport, spawnflags 1): never through the void under the floor (a test map of 13.11: the
            # crates' way under the floor - its base refused, «6 mover records have no counterpart»), nor through rock
            if OLD_BELT_CORNERS:
                if ax == 0:
                    yc = (Y0 + Y1) / 2 - size / 2
                    a_pt, b_pt = (X0 - size - 8, yc, base + h), (X1 + 8, yc, base + h)
                else:
                    xc = (X0 + X1) / 2 - size / 2
                    a_pt, b_pt = (xc, Y0 - size - 8, base + h), (xc, Y1 + 8, base + h)
            else:
                z_ = base + h + 1
                if ax == 0:
                    yc = (Y0 + Y1) / 2 - size / 2
                    a_pt, b_pt = (X0 + 4, yc, z_), (X1 - 4 - size, yc, z_)
                else:
                    xc = (X0 + X1) / 2 - size / 2
                    a_pt, b_pt = (xc, Y0 + 4, z_), (xc, Y1 - 4 - size, z_)
            for k in range(n):
                cp = names("belt")
                frac = k / n
                start = tuple(a_pt[i] + (b_pt[i] - a_pt[i]) * frac for i in range(3))
                parts = _crate(kind, start, size, rnd)
                # the first crate from the start wall; the others from along the belt, each loop closed by the start
                # wall's teleport corner leading to the end wall (B)
                loop = [(start, 0, 1), (b_pt, 0, 2), (a_pt, 1, 1)] if k else [(a_pt, 1, 1), (b_pt, 0, 0)]
                for i, (p_, tele, nxt) in enumerate(loop):
                    keys = {"classname": "path_corner", "targetname": f"{cp}_{i}", "target": f"{cp}_{nxt}",
                            "origin": f"{p_[0]:.0f} {p_[1]:.0f} {p_[2]:.0f}"}
                    if tele:
                        keys["spawnflags"] = 1
                    rec["ents"].append(ent(keys))
                rec["ents"].append(ent({"classname": "func_train", "target": f"{cp}_0", "speed": spd, "spawnflags": 1, "dmg": 2},
                                       parts))
            rec["ents"].append(_speaker(rnd.choice(("world/train1.wav", "world/mach2.wav", "world/turbine1.wav")),
                                        ((X0 + X1) / 2, (Y0 + Y1) / 2, base + h + 48), 0.6, 3))
            held.update(run)
            P.no_items.update(run)
            P.reasons.append(("func_train", say(f"конвейер вдоль стены зала {s.id}: {n} {_crate_ru(kind)} едут из стены в стену, на них можно прокатиться",
                                                f"a conveyor along hall {s.id}'s wall: {n} {kind} crates ride from wall to wall - one can ride them")))
            if not OLD_BELT_CORNERS:
                P.reasons[-1] = ("func_train", say(f"конвейер вдоль стены зала {s.id}: {n} {_crate_ru(kind)} выезжают из короба у одной стены и уезжают в короб у другой, на них можно прокатиться",
                                                   f"a conveyor along hall {s.id}'s wall: {n} {kind} crates come out of a housing at one wall and ride into one at the other - one can ride them"))
            return True
    return False


def _crate(kind, lo, size, rnd) -> list:
    x, y, z = lo
    if not forms.OLD_NEAR_FACES:
        # its body in segments with the bands between them, nothing through anything (a train's parts overlapping were
        # drawn otherwise by the engine's round trip); a barrel of plain slopes (forms.flat_oct)
        # one brush each (a train's parts ride to their corners each by its own corner, they cannot be bodies apart;
        # touching parts in one body were drawn otherwise by the round trip): a box, a box with its edges cut, a barrel
        if kind == "barrel":
            r = size / 2
            return [forms.prism("z", forms.flat_oct(x + r, y + r, r), z, z + int(round(size * 1.2)), "trim", 1, "crate")]
        if kind == "banded":
            ch = 6
            return [forms.prism("z", [(x + ch, y), (x + size - ch, y), (x + size, y + ch), (x + size, y + size - ch),
                                      (x + size - ch, y + size), (x + ch, y + size), (x, y + size - ch), (x, y + ch)],
                                z, z + size, "trim", 1, "crate")]
        return [bx((x, y, z), (x + size, y + size, z + size), "trim", contents=1, note="crate")]
    if kind == "barrel":
        r = size / 2
        return [forms.prism("z", forms.ngon(x + r, y + r, r, 8, math.pi / 8), z, z + size * 1.2, "trim", 1, "crate"),
                forms.prism("z", forms.ngon(x + r, y + r, r + 2, 8, math.pi / 8), z + size * 0.35, z + size * 0.42, "trim", 1, "crate band"),
                forms.prism("z", forms.ngon(x + r, y + r, r + 2, 8, math.pi / 8), z + size * 0.78, z + size * 0.85, "trim", 1, "crate band")]
    out = [bx((x, y, z), (x + size, y + size, z + size), "trim", contents=1, note="crate")]
    if kind == "banded":
        for f in (0.3, 0.7):
            out.append(bx((x - 2, y - 2, z + size * f - 3), (x + size + 2, y + size + 2, z + size * f + 3), "trim", contents=1,
                          note="crate band"))
    return out


def _crate_ru(k):
    return {"box": "ящика", "banded": "ящика в обвязке", "barrel": "бочки"}.get(k, k)
