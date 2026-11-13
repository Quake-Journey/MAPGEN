"""Scripted pieces of our own on people's principles (the PO 13.11: «проявишь и творческую нотку ... уникальные
конструкции, которых в том числе не было в картах людей, но они основаны на тех же принципах - скрипты, движение,
интерес к посещению, доп опасности, чтобы такое было гармонично на картах»; «чтобы человек открыв твою карту был в
ахуе»). Each guards a valuable item or offers a way at a risk; their timings are people's (mapgen_scratch_pieces).

  lasers       - beams across a corridor (target_laser) a timer switches on and off: one crosses in the pause;
  pistons      - blocks out of a corridor's walls (or its ceiling) on timers out of phase: one runs them in time;
  pendulums    - an arm swinging over a bridge across a pit (func_door_rotating on a timer): it knocks one off;
  trapdoors    - a valuable item on a floor over a pit that drops a moment after the item is taken;
  geysers      - a column of lava rising from a hole in a hall's floor on a timer;
  turn_bridges - a plank over a pit turning a quarter on a timer: it joins one pair of sides, then the other;
  currents     - a bridge over a pit whose floor pushes sideways (or against the way): CURRENT contents;
  waves        - pillars in a pit sinking one after another on timers: one crosses on those up.
"""
from __future__ import annotations

import math
import random

import mapgen_scratch_pieces as base_mod
from mapgen_scratch_pieces import (CELL, Names, bx, cb, ent, edge, mid, node, passages, record, runs, speed, take_item,
                                   wait, _liq_ru, _remove_from_liquid, say)

LASER_DMG = 10             # a frame (a tenth of a second): 100 a second in the beam
LASER_WAIT = 2.5
PISTON_WAIT = 2.0
PISTON_DMG = 20
PENDULUM_SPEED = 90        # degrees a second
# a hammer's blow (the PO 13.11: «нехилый дамаж»): the heavy heads hurt most
HAMMER_DMG = {"hammer": 70, "sledge": 75, "spiked": 80, "mace": 75, "anchor": 65, "axe": 55, "labrys": 60, "sickle": 55,
              "saw": 55}
PENDULUM_WAIT = 0.5
TRAPDOOR_DELAY = 0.8
GEYSER_WAIT = 5.0
GEYSER_UP = 1.5
TURN_WAIT = 5.0
CURRENT_FLAGS = {(1, 0): 0x40000, (0, 1): 0x80000, (-1, 0): 0x100000, (0, -1): 0x200000}   # CURRENT_0/90/180/270
WAVE_STEP = 0.6


def after_items(P, rnd: random.Random, held: set, pits: list, used: set, times_of) -> None:
    q = P.params
    # the pieces that need a pit of a shape (a square one, a long one) before the trapdoor, which needs any pit's rim
    # cell - and takes the smallest pit (one piece a pit)
    for kind, fn in (("lasers", lasers), ("pistons", pistons), ("pendulums", pendulums), ("turn_bridges", turn_bridges),
                     ("currents", currents), ("waves", waves), ("trapdoors", trapdoors), ("geysers", geysers)):
        if kind == "pendulums" and not base_mod.OLD_PENDULUM_COUNT:
            # counted by their heads: a pair on one bridge is two (the test map mg_new_368_mach7: two asked, one bridge)
            heads, want = 0, int(q.get(kind, 0) or 0)
            while heads < want:
                n0 = len(P.pieces)
                if not pendulums(P, rnd, held, pits, used, times_of, need=want - heads):
                    P.notes.append(say(f"{NAMES_RU[kind]}: на этом каркасе для неё нет места",
                                       f"{kind}: no room for it on this skeleton"))
                    break
                heads += sum(len(r["cells"]) for r in P.pieces[n0:] if r["kind"] == "pendulums")
            continue
        for n in range(q.get(kind, 0)):
            if not fn(P, rnd, held, pits, used, times_of):
                P.notes.append(say(f"{NAMES_RU[kind]}: на этом каркасе для неё нет места",
                                   f"{kind}: no room for it on this skeleton"))
                break


NAMES_RU = {"lasers": "лазерный заслон", "pistons": "поршни в коридоре", "pendulums": "маятник над мостом",
            "trapdoors": "проваливающийся пол под предметом", "geysers": "лавовый гейзер",
            "turn_bridges": "поворотный мост", "currents": "мост-течение", "waves": "волна столбов"}


def _timer(name, w, delay=0.0, rand=0.0, origin=(0, 0, 0)) -> dict:
    keys = {"classname": "func_timer", "target": name, "spawnflags": 1, "wait": w,
            "origin": f"{origin[0]:.0f} {origin[1]:.0f} {origin[2]:.0f}"}
    if delay:
        keys["delay"] = round(delay, 2)
    if rand:
        keys["random"] = rand
    return ent(keys)


def _near_guarded(P, cands, key_cell):
    """Corridor (or other) candidates nearest a valuable item first."""
    its = [c for (cls, c, z, note) in P.items if cls in base_mod.GUARD_ITEMS]
    if not its:
        return cands
    return sorted(cands, key=lambda t: min(abs(key_cell(t)[0] - c[0]) + abs(key_cell(t)[1] - c[1]) for c in its))


# --------------------------------------------------------------------------------------------- lasers
def lasers(P, rnd, held, pits, used, times_of) -> bool:
    cands = _near_guarded(P, passages(P, held), lambda t: t[1][0])
    for s, cross, d in cands[:1]:
        c = cross[0]
        z = s.floor[c][0]
        names = Names(P)
        tn = names("laser")
        x0 = min(cb(x)[0] for x in cross)
        y0 = min(cb(x)[1] for x in cross)
        x1 = max(cb(x)[2] for x in cross)
        y1 = max(cb(x)[3] for x in cross)
        rec = record(P, "lasers", cells=list(cross), space=s.id)
        colour = rnd.choice((2, 32, 16))                     # red, orange, yellow
        beams = (24, 56) if rnd.random() < 0.6 else (40,)
        for k, h in enumerate(beams):
            far = names(f"laser_end{k}")
            if d[0]:                                          # the passage along x: the beam across it, along y
                a, b = (x0 + CELL / 2, y0 + 2, z + h), (x0 + CELL / 2, y1 - 2, z + h)
                lo, hi = (a[0] - 6, y0, z + h - 6), (a[0] + 6, y0 + 4, z + h + 6)
            else:
                a, b = (x0 + 2, y0 + CELL / 2, z + h), (x1 - 2, y0 + CELL / 2, z + h)
                lo, hi = (x0, a[1] - 6, z + h - 6), (x0 + 4, a[1] + 6, z + h + 6)
            rec["brushes"].append(bx(lo, hi, "button", contents=1, note="laser emitter"))
            rec["ents"].append(ent({"classname": "target_laser", "targetname": tn, "target": far, "dmg": LASER_DMG,
                                    "spawnflags": 1 | colour, "origin": f"{a[0]:.0f} {a[1]:.0f} {a[2]:.0f}"}))
            rec["ents"].append(ent({"classname": "info_notnull", "targetname": far,
                                    "origin": f"{b[0]:.0f} {b[1]:.0f} {b[2]:.0f}"}))
        rec["ents"].append(_timer(tn, wait(P, rnd.choice((LASER_WAIT, 2.0, 3.0))), origin=(x0 + 32, y0 + 32, z + 96)))
        held.update(cross)
        P.reasons.append(("target_laser", say("лазерный заслон в коридоре включается и гаснет по таймеру - проскочить в паузу",
                                              "a laser gate in a corridor switching on and off - one crosses in the pause")))
        return True
    return False


# --------------------------------------------------------------------------------------------- pistons
def pistons(P, rnd, held, pits, used, times_of) -> bool:
    plan_mod = base_mod.pm()
    by = {}
    for s, cross, d in passages(P, held, (1, 2)):
        c = cross[0]
        side_rock = len(cross) == 1 and all((c[0] + sg * d[1], c[1] + sg * d[0]) not in P.owner for sg in (1, -1))
        if side_rock or not plan_mod._stacked_over(P, cross):
            by.setdefault((s.id, d, len(cross), side_rock), set()).add(c)
    best = None
    for (sid, d, width, side_rock), cs in by.items():
        for c in sorted(cs):
            run = [c]
            while (run[-1][0] + d[0], run[-1][1] + d[1]) in cs:
                run.append((run[-1][0] + d[0], run[-1][1] + d[1]))
            if len(run) >= 3 and (best is None or len(run) > len(best[2])):
                best = (sid, d, run, width, side_rock)
    if not best:
        return False
    sid, d, run, width, side_rock = best
    s = P.spaces[sid]
    run = run[:4]
    names = Names(P)
    perp = (d[1], d[0])
    from_ceiling = (not side_rock or rnd.random() < 0.35) and s.ceil - s.floor[run[0]][0] <= 256
    w = wait(P, rnd.choice((PISTON_WAIT, 1.5, 2.5)))
    head = rnd.choice(("plate", "ram", "spiked"))
    rec = record(P, "pistons", cells=run, space=sid, variant=("ceiling" if from_ceiling else "walls") + "/" + head)
    for i, c in enumerate(run):
        z = s.floor[c][0]
        tn = names("piston")
        x0, y0, x1, y1 = cb(c)
        side = 1 if i % 2 else -1
        if from_ceiling:
            top = P.cell_ceil.get(c, s.ceil)
            far = (c[0] + perp[0] * (width - 1), c[1] + perp[1] * (width - 1))
            X0, Y0 = min(x0, cb(far)[0]), min(y0, cb(far)[1])
            X1, Y1 = max(x1, cb(far)[2]), max(y1, cb(far)[3])
            drop = top - z - 40                    # down to a crouch's height over the floor
            lo, hi = (X0 + 4, Y0 + 4, top), (X1 - 4, Y1 - 4, top + drop)
            keys = {"angle": -2, "lip": 8}
            move_note = "stomper"
        elif d[0]:                         # the corridor along x: the walls on the y sides
            wy0 = y1 if side > 0 else y0 - CELL
            lo, hi = (x0 + 6, wy0, z), (x1 - 6, wy0 + CELL, z + 112)
            keys = {"angle": 270 if side > 0 else 90, "lip": 12}
            move_note = "piston"
        else:
            wx0 = x1 if side > 0 else x0 - CELL
            lo, hi = (wx0, y0 + 6, z), (wx0 + CELL, y1 - 6, z + 112)
            keys = {"angle": 180 if side > 0 else 0, "lip": 12}
            move_note = "piston"
        if not base_mod.OLD_PISTON_HEADS_OUT:
            # the head back in the wall by what it stands out (a ram's cap 8, spikes 16): at rest its tip is the wall's
            # face, its stroke the same (the test map mg_new_368_mach6: spikes 16 out of both walls by turns left a
            # one-cell corridor 32 wide - a player's own width, four places the game's walk could not leave)
            # and 2 more: the face never in the wall's plane (the test map mg_new_368_mach12: a ram's cap flush with the
            # wall - «door faces: 2 of 7»)
            back = {"plate": 0, "ram": 8, "spiked": 16}[head] + 2
            ax_, sgn_ = {-2: (2, -1), -1: (2, 1), 0: (0, 1), 180: (0, -1), 90: (1, 1), 270: (1, -1)}[int(keys["angle"])]
            lo, hi = list(lo), list(hi)
            lo[ax_] -= sgn_ * back
            hi[ax_] -= sgn_ * back
            lo, hi = tuple(lo), tuple(hi)
        parts, grow = _piston_head(lo, hi, keys["angle"], head, rnd)
        keys = dict(keys, lip=keys["lip"] + grow)
        rec["ents"].append(ent({"classname": "func_door", "targetname": tn, "speed": speed(P, 250), "spawnflags": 32 | 4,
                                "dmg": PISTON_DMG, **keys}, parts))
        rec["ents"].append(_timer(tn, w, delay=0.5 + i * w / len(run), origin=(x0 + 32, y0 + 32, z + 64)))
        held.add(c)
    P.reasons.append(("func_door", say("поршни в коридоре выходят из стен по очереди - пробегать в такт",
                                       "pistons out of a corridor's walls in turn - one runs them in time")))
    return True


# --------------------------------------------------------------------------------------------- pendulums
def _bridge_runs(P, held):
    """Bridges across a pit (a row of floor cells at the hall's base with the pit on both sides)."""
    out = []
    for r in getattr(P, "pieces", []):
        if r["kind"] in ("bent_bridges", "currents"):
            out.append((r["space"], r["cells"]))
    for s in P.spaces:
        if s.solid or s.pattern != "bridge":
            continue
        cells = [c for c, f in s.floor.items() if f == (s.base, "flat", 0, 0)
                 and any((c[0] + dx, c[1] + dy) in set(s.pit) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
        if len(cells) >= 3:
            out.append((s.id, cells))
    return out


def _reach_along(parts, axis: str) -> tuple:
    """How far a body of forms (prisms, boxes) reaches along a world axis: its least and greatest coordinate."""
    i = "xyz".index(axis)
    j = {"x": {"y": 0, "z": 1}, "y": {"x": 0, "z": 1}, "z": {"x": 0, "y": 1}}
    vals = []
    for b in parts:
        pr = b.get("prism")
        if pr:
            if pr["axis"] == axis:
                vals += [pr["lo"], pr["hi"]]
            else:
                vals += [p[j[pr["axis"]][axis]] for p in pr["poly"]]
        elif "lo" in b:
            vals += [b["lo"][i], b["hi"][i]]
    return (min(vals), max(vals)) if vals else (0.0, 0.0)


def _apart_along(a, b, axis: str, gap: float) -> bool:
    """Two pendulums turning about one axis never meet when their reaches along it are `gap` apart: a turn about an
    axis keeps every point's coordinate along it."""
    a0, a1 = _reach_along(a, axis)
    b0, b1 = _reach_along(b, axis)
    return b0 - a1 >= gap or a0 - b1 >= gap


def pendulums(P, rnd, held, pits, used, times_of, need: int = 1) -> bool:
    """A pendulum - a «молот» - over a bridge across a pit, swinging across it on a timer: it knocks one off. The PO 13.11
    after the first try: «молот - он должен варьироваться, не быть одной формы ... серп например ... двойной молот,
    может молот, на котором что то интересное еще есть». Its head one of mapgen_scratch_forms.PENDULUM_FORMS (a hammer,
    a two-headed sledge, a spiked hammer, an axe, a double axe, a sickle, a mace, a saw, an anchor), its rod one rod, a
    fork or a chain, its swing 90..130 degrees, its sizes drawn - and now and then a second one on the same bridge
    swinging against it (scissors) or after it (in turn)."""
    import mapgen_scratch_forms as forms
    q = P.params
    for sid, cells in _bridge_runs(P, held):
        s = P.spaces[sid]
        free = [c for c in cells if c not in held]
        if not free:
            continue
        if base_mod.OLD_SWEEP:
            c = free[len(free) // 2]
            along_x = (c[0] + 1, c[1]) in cells or (c[0] - 1, c[1]) in cells
            if P.cell_ceil.get(c, s.ceil) - 8 - (s.base + 24) < 96:
                continue
        form = q.get("pendulum_kind") or "mix"
        if form not in forms.PENDULUM_FORMS:
            form = rnd.choice(forms.PENDULUM_FORMS)
        rod = rnd.choice(forms.ROD_STYLES)
        # the swing twice the rest angle the head is drawn at - an exact one (mapgen_scratch_forms.exact_rest: 74 or
        # 106 degrees for 90..130 asked), its faces on whole units
        amp = 2 * forms.exact_rest(rnd.choice((90, 110, 130)) / 2)
        heavy = form in ("hammer", "sledge", "spiked", "mace", "anchor")
        spd = speed(P, PENDULUM_SPEED * (0.75 if heavy else 1.15) * amp / 90)
        w = wait(P, rnd.choice((1.2, 1.5, 2.0)))

        def build_at(k, cc, ax_x, pv_=None):
            cx_, cy_ = mid(cc)
            pv_ = P.cell_ceil.get(cc, s.ceil) - 8 if pv_ is None else pv_
            pu_, pa_ = (cy_, cx_) if ax_x else (cx_, cy_)
            return forms.pendulum(form, rod, "x" if ax_x else "y", pu_, pv_, pv_ - (s.base + 24),
                                  amp / 2 * (1 if k == 0 else -1), pa_, rnd)

        def clear(parts_, k, cc, ax_x, pv_=None, own_=()):
            # the PO 13.11 (Bugs/4: a saw swinging through a glass trap room and a pillar): its whole swing in air
            if base_mod.OLD_SWEEP:
                return True
            cx_, cy_ = mid(cc)
            pv_ = P.cell_ceil.get(cc, s.ceil) - 8 if pv_ is None else pv_
            armk_ = pv_ - (s.base + 24)
            rest_ = amp / 2 * (1 if k == 0 else -1)
            fl_ = (64 if ax_x else 128) | 32
            r_ = math.radians(abs(rest_))
            sd_ = 1 if rest_ > 0 else -1
            head_ = (sd_ * math.sin(r_) * armk_, 0.0, -math.cos(r_) * armk_) if not ax_x else                 (0.0, sd_ * math.sin(r_) * armk_, -math.cos(r_) * armk_)
            dist_ = next(d for d in (-amp, amp) if swing_end(head_, fl_, d)[2] < -0.3 * armk_
                         and swing_end(head_, fl_, d)[0 if not ax_x else 1] * sd_ < 0)
            n_ = max(2, int(abs(dist_) // 6))
            hits_, cells_, cuts_ = base_mod.sweep(P, s.id, parts_, (cx_, cy_, pv_), fl_,
                                                  [dist_ * i / n_ for i in range(1, n_ + 1)],
                                                  own=own_, carve_min_z=s.base + 72)
            if not hits_:
                swept.update(cells_)
                for c_, (z0_, z1_) in cuts_.items():
                    cut.setdefault(c_, [z0_, z1_])
                    cut[c_] = [min(cut[c_][0], z0_), max(cut[c_][1], z1_)]
            return not hits_
        swept = set()
        cut = {}
        doorish_ = {x for d_ in P.doors for x in d_.cells} | {x for (cs_, *_w) in P.windows for x in cs_}
        pillars_ = {x for (x, *_r) in P.pillars}

        def beam_for(cc, ax_x, pv_):
            """The PO 13.11 (Bugs/4: a tall hall's long pendulum swung into the rooms beside it): a pivot lower than the
            ceiling, on a beam along the bridge from wall to wall at its height (held at both ends: nothing hangs) -
            or None where an end would stand in a doorway, a window or another room, or a piece is in its way."""
            step = (1, 0) if ax_x else (0, 1)
            run_ = [cc]
            for sg in (-1, 1):
                x = cc
                while True:
                    n_ = (x[0] + sg * step[0], x[1] + sg * step[1])
                    if P.owner.get(n_) == s.id and n_ not in pillars_ and P.cell_ceil.get(n_, s.ceil) >= pv_ + 40:
                        run_.append(n_)
                        x = n_
                        continue
                    if n_ in doorish_ or (P.owner.get(n_) is not None and n_ not in pillars_):
                        return None, []     # a doorway, a window, another room or a lower ceiling: no end there
                    break                   # rock or a column: the beam's end rests in it
            xs_ = [cb(x)[0] for x in run_] + [cb(x)[2] for x in run_]
            ys_ = [cb(x)[1] for x in run_] + [cb(x)[3] for x in run_]
            cx_, cy_ = mid(cc)
            # 8 into the rock at both ends: no end face in a wall's plane (a candidate with a beam ending flush was
            # refused by the engine's round trip, «the baseline draws 8192 units … that the donor does not»)
            # just over the pivot, the rod's top turning under it (a rod through a beam was drawn otherwise by the round
            # trip)
            if ax_x:
                lo_, hi_ = (min(xs_) - 8, cy_ - 8, pv_ + 8), (max(xs_) + 8, cy_ + 8, pv_ + 20)
            else:
                lo_, hi_ = (cx_ - 8, min(ys_) - 8, pv_ + 8), (cx_ + 8, max(ys_) + 8, pv_ + 20)
            for r_ in P.pieces:
                for bb in r_["brushes"] + [b2 for e_ in r_["ents"] if not str(e_["keys"].get("classname", "")).startswith("trigger_")
                                           for b2 in e_["brushes"]]:
                    cs_ = base_mod._corners(bb)
                    if cs_ and all(min(c_[k_] for c_ in cs_) <= hi_[k_] and max(c_[k_] for c_ in cs_) >= lo_[k_] for k_ in range(3)):
                        return None, []
            return bx(lo_, hi_, "trim", contents=1, note="pendulum beam"), run_
        beam_sel, beam_run, pv_sel = None, [], None
        if base_mod.OLD_SWEEP:
            built = [build_at(0, c, along_x)]
        else:
            # the bridge's cells from its middle out: the first whose whole swing is clear
            mid_i = len(free) // 2
            c = None
            # the swing drawn first, then the smaller one (74) where the larger meets something on every cell
            for amp_try in ([amp] + ([2 * forms.exact_rest(37)] if amp > 2 * forms.exact_rest(37) + 1 else [])):
                amp = amp_try
                for c0 in sorted(free, key=lambda x: (abs(free.index(x) - mid_i), x)):
                    top0 = P.cell_ceil.get(c0, s.ceil)
                    if top0 - 8 - (s.base + 24) < 96:
                        continue
                    ax0 = (c0[0] + 1, c0[1]) in cells or (c0[0] - 1, c0[1]) in cells
                    # from the ceiling first, then from a beam lower and lower (a shorter arm, a narrower swing)
                    pivots = [None] + ([] if base_mod.OLD_SWEEP else
                                       [s.base + 24 + a for a in (240, 200, 160, 128) if s.base + 24 + a < top0 - 8 - 32])
                    for pv0 in pivots:
                        beam0, run0 = (None, []) if pv0 is None else beam_for(c0, ax0, pv0)
                        if pv0 is not None and beam0 is None:
                            continue
                        st = rnd.getstate()
                        parts0 = build_at(0, c0, ax0, pv0)
                        cut.clear()
                        swept.clear()
                        if clear(parts0, 0, c0, ax0, pv0, [beam0] if beam0 else ()):
                            c, along_x, built = c0, ax0, [parts0]
                            beam_sel, beam_run, pv_sel = beam0, run0, pv0
                            break
                        rnd.setstate(st)
                    if c is not None:
                        break
                if c is not None:
                    break
            if c is None:
                continue
            spd = speed(P, PENDULUM_SPEED * (0.75 if heavy else 1.15) * amp / 90)
        axis = "x" if along_x else "y"

        def build(k, cc):
            return build_at(k, cc, along_x, pv_sel)
        # the second one: on the same bridge two cells off at least, mirrored (scissors) or in turn
        twin = None
        # a pair when two or more are still asked and no other bridge is free for them (or one in three anyway)
        lone = need >= 2 and not any(sid2 != sid and any(x not in held for x in cells2)
                                     for sid2, cells2 in _bridge_runs(P, held))
        if (lone and not base_mod.OLD_PENDULUM_COUNT) or rnd.random() < 0.35:
            if base_mod.OLD_PENDULUMS_CLOSE:
                twin = next((x for x in free if abs(x[0] - c[0]) + abs(x[1] - c[1]) >= 2
                             and P.cell_ceil.get(x, s.ceil) - 8 - (s.base + 24) >= 96), None)
                if twin:
                    built.append(build(1, twin))
            else:
                # in line with the first along the bridge, its head clear of the first's all the swing long (the test
                # map mg_new_368_mach4: a twin a cell aside, the next pendulum on the cell beside - heads through heads)
                line = sorted((x for x in free if (x[1] == c[1] if along_x else x[0] == c[0])
                               and abs(x[0] - c[0]) + abs(x[1] - c[1]) >= 2
                               and P.cell_ceil.get(x, s.ceil) - 8 - (s.base + 24) >= 96),
                              key=lambda x: (abs(x[0] - c[0]) + abs(x[1] - c[1]), x))
                for x in line[:3]:
                    parts2 = build(1, x)
                    if (beam_sel is None or x in beam_run) and _apart_along(built[0], parts2, axis, 16) \
                            and clear(parts2, 1, x, along_x, pv_sel, [beam_sel] if beam_sel else ()):
                        twin = x
                        built.append(parts2)
                        break
        names = Names(P)
        rec = record(P, "pendulums", cells=[c] + ([twin] if twin else []), space=sid,
                     variant=f"{form}/{rod}/{round(amp)}" + ("/twin" if twin else ""))
        if beam_sel is not None:
            rec["brushes"].append(beam_sel)
            held.update(beam_run)
        for k, cc in enumerate([c] + ([twin] if twin else [])):
            cx, cy = mid(cc)
            topk = P.cell_ceil.get(cc, s.ceil)
            pv = topk - 8 if pv_sel is None else pv_sel
            armk = pv - (s.base + 24)
            rest = amp / 2 * (1 if k == 0 else -1)
            parts = built[k]
            flags = (64 if along_x else 128) | 32           # X_AXIS or Y_AXIS, TOGGLE
            # the swing's way: the one the game turns the head DOWN through the bridge to the other side (the PO 13.11 on
            # mg_new_368_ffa8: «не корректную дугу делает улетая в небо где исчезает» - chosen by the game's own turn)
            r_ = math.radians(abs(rest))
            side = 1 if rest > 0 else -1
            head = (side * math.sin(r_) * armk, 0.0, -math.cos(r_) * armk) if not along_x else \
                (0.0, side * math.sin(r_) * armk, -math.cos(r_) * armk)
            distance = next(d for d in (-amp, amp) if swing_end(head, flags, d)[2] < -0.3 * armk
                            and swing_end(head, flags, d)[0 if not along_x else 1] * side < 0)
            tn = names("pendulum")
            # one body per group of parts that do not overlap, all of one name: one timer swings them as one
            for grp in base_mod.body_groups(parts):
                rec["ents"].append(ent({"classname": "func_door_rotating", "targetname": tn,
                                        "origin": f"{cx:.0f} {cy:.0f} {pv:.0f}", "distance": round(distance, 2), "speed": spd,
                                        "spawnflags": flags, "dmg": 40}, grp))
            half = 24 if rod != "fork" else 32
            if pv_sel is None:          # hung from the ceiling: its plate; from a beam: the beam is its mount
                rec["brushes"].append(bx((cx - half, cy - half, pv), (cx + half, cy + half, topk), "trim", contents=1,
                                         note="pendulum mount"))
            delay = 0.0 if k == 0 or rnd.random() < 0.5 else w / 2
            rec["ents"].append(_timer(tn, w, delay=delay, origin=(cx, cy, pv - 8)))
            # the PO 13.11: «молоты они же должны при ударе наносить нехилый дамаж если попадают в тельце игрока» - the
            # game hurts with a door only when it is blocked; a field over the bridge cell is switched on while the head
            # sweeps the bottom of its arc (the same timer, through two relays: on, off), and hurts once a second
            hurt = names("hammer_hit")
            t_mid = (amp / 2) / max(1.0, spd)
            x0_, y0_, x1_, y1_ = cb(cc)
            # «чем больше молот относительно игрока тем сильней дамаж» (the PO 13.11): the blow by the head's bulk
            bulk = sum(_prism_volume(pp) for pp in parts)
            blow = int(max(35, min(120, 25 + bulk / 6000 + (15 if form in ("axe", "labrys", "sickle", "saw") else 0))))
            rec["ents"].append(ent({"classname": "trigger_hurt", "targetname": hurt, "spawnflags": 1 | 2 | 16,
                                    "dmg": blow},
                                   [bx((x0_ + 4, y0_ + 4, s.base), (x1_ - 4, y1_ - 4, s.base + 72), "trigger")]))
            for dt in (max(0.0, t_mid - 0.18), t_mid + 0.18):
                rec["ents"].append(ent({"classname": "trigger_relay", "targetname": tn, "target": hurt, "delay": round(dt, 2),
                                        "origin": f"{cx:.0f} {cy:.0f} {s.base + 96:.0f}"}))
            if q.get("hammer_blast"):
                # the blow's shock wave at the bottom of the arc (the PO 13.11: «выталкивать с силой, чтобы игрок отлетал»,
                # «чем больше молот ... тем сильней дамаж и толкание»): the game's own explosion, its blast as strong as
                # the head is big - the only throw the game has without a mod
                bang = names("hammer_blast")
                rec["ents"].append(ent({"classname": "target_explosion", "targetname": bang, "dmg": max(20, blow // 2),
                                        "origin": f"{cx:.0f} {cy:.0f} {s.base + 40:.0f}"}))
                rec["ents"].append(ent({"classname": "trigger_relay", "targetname": tn, "target": bang, "delay": round(t_mid, 2),
                                        "origin": f"{cx:.0f} {cy:.0f} {s.base + 104:.0f}"}))
            if base_mod.OLD_PENDULUMS_CLOSE:
                held.add(cc)
            else:
                # the cells its swing passes: no other piece, item, lamp or pilaster there
                held.update(swept)
                P.no_items.update(swept)
                # the cuts in the rock behind the walls its swing reaches: a slot the head goes into, 16 round it
                if cut:
                    if not hasattr(P, "slots"):
                        P.slots = []
                    for c_, (z0_, z1_) in cut.items():
                        P.slots.append((c_, int(z0_) - 16, int(z1_) + 16, s.id))
                        held.add(c_)
                    rec["cuts"] = sorted(cut)
                    cut.clear()
                # the next pendulum two cells off at least (its swing and the head's reach along the bridge)
                held.update({(cc[0] + dx, cc[1] + dy) for dx in range(-2, 3) for dy in range(-2, 3)})
        what = forms.FORM_RU.get(form, form)
        P.reasons.append(("func_door_rotating", say(f"{'два маятника' if twin else 'маятник'} ({what}) над мостом через яму - сбивает вниз",
                                                    f"{'two pendulums' if twin else 'a pendulum'} ({form}) over a bridge across a pit - it knocks one off")))
        return True
    return False


def _piston_head(lo, hi, angle, head, rnd) -> tuple:
    """A piston's parts and how far its head stands out of its box (the lip grows by it - the same stroke): a plain
    plate, a ram (a cap on its face, two bands round it) or spikes on its face."""
    import mapgen_scratch_forms as forms
    parts = [bx(lo, hi, "trim", note="piston")]
    if head == "plate":
        return parts, 0
    # the face that leads: the side the piston moves to
    ax, sgn = {-2: (2, -1), -1: (2, 1), 0: (0, 1), 180: (0, -1), 90: (1, 1), 270: (1, -1)}[int(angle)]
    face = hi[ax] if sgn > 0 else lo[ax]
    grow = 0
    if head == "ram":
        cap_lo, cap_hi = list(lo), list(hi)
        for a in range(3):
            if a != ax:
                cap_lo[a] -= 4
                cap_hi[a] += 4
        cap_lo[ax], cap_hi[ax] = (face, face + 8) if sgn > 0 else (face - 8, face)
        parts.append(bx(tuple(cap_lo), tuple(cap_hi), "trim", note="ram cap"))
        span = hi[ax] - lo[ax]
        for f in (0.3, 0.6):
            b_lo, b_hi = list(lo), list(hi)
            for a in range(3):
                if a != ax:
                    b_lo[a] -= 2
                    b_hi[a] += 2
            at = lo[ax] + span * f
            b_lo[ax], b_hi[ax] = at, at + 6
            parts.append(bx(tuple(b_lo), tuple(b_hi), "trim", note="ram band"))
        grow = 8
    elif head == "spiked":
        others = [a for a in range(3) if a != ax]
        u, v = others
        n = 3
        for i in range(n):
            for j in range(2 if (hi[v] - lo[v]) > 40 else 1):
                cu = lo[u] + (i + 0.5) * (hi[u] - lo[u]) / n
                cv = lo[v] + (j + 0.5) * (hi[v] - lo[v]) / (2 if (hi[v] - lo[v]) > 40 else 1)
                tip = face + sgn * 16
                axis_name = "xyz"[v]
                # a spike: a triangle in the plane of the move and u, extruded along v a little
                tri = []
                for (pu, pm) in ((cu - 6, face), (cu + 6, face), (cu, tip)):
                    tri.append((pu, pm) if u < ax else (pm, pu))
                # prism axis is v; its polygon in the other two axes in their order
                poly = [(p[0], p[1]) for p in tri]
                parts.append(forms.prism(axis_name, poly, cv - 4, cv + 4, "trim", 1, "piston spike"))
        grow = 16
    return parts, grow


def _prism_volume(b: dict) -> float:
    pr = b.get("prism")
    if not pr:
        return 0.0
    pts = pr["poly"]
    area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2
    return area * (pr["hi"] - pr["lo"])


def swing_end(p, flags: int, deg: float) -> tuple:
    """Where a point `p` of a func_door_rotating (about its origin) ends when the game turns it `deg` about its axis:
    X_AXIS (64) turns the roll, Y_AXIS (128) the pitch, else the yaw (g_func.c SP_func_door_rotating); the model is drawn
    on AngleVectors' forward, left (the right turned back) and up (q_shared AngleVectors, refresh AnglesToAxis)."""
    pitch = deg if flags & 128 else 0.0
    roll = deg if flags & 64 else 0.0
    yaw = deg if not flags & (64 | 128) else 0.0
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    fwd = (cp * cy, cp * sy, -sp)
    right = (-sr * sp * cy + cr * sy, -sr * sp * sy - cr * cy, -sr * cp)
    up = (cr * sp * cy + sr * sy, cr * sp * sy - sr * cy, cr * cp)
    left = tuple(-v for v in right)
    return tuple(p[0] * fwd[k] + p[1] * left[k] + p[2] * up[k] for k in range(3))


def _tilted(span_axis, u_range, z_range, half_w, axis) -> dict:
    """A convex slab from (u0, z0) to (u1, z1) in the plane across `axis`, `half_w` thick there, spanning span_axis
    along the axis: its eight corners (the world builder makes a brush of their hull)."""
    a0, a1 = span_axis
    (u0, u1), (z0, z1) = u_range, z_range
    du, dz = u1 - u0, z1 - z0
    L = math.hypot(du, dz) or 1.0
    nu, nz = -dz / L * half_w, du / L * half_w
    pts2 = [(u0 + nu, z0 + nz), (u1 + nu, z1 + nz), (u1 - nu, z1 - nz), (u0 - nu, z0 - nz)]
    corners = []
    for a_ in (a0, a1):
        for (u, z) in pts2:
            corners.append((a_, u, z) if axis == "x" else (u, a_, z))
    return {"hull": [[round(v, 1) for v in p] for p in corners], "role": "trim", "contents": 1, "note": "pendulum"}


# --------------------------------------------------------------------------------------------- trapdoors
def trapdoors(P, rnd, held, pits, used, times_of) -> bool:
    # a pit of its own first, the smallest; then one a piece shares that sweeps nothing over the rim and guards no item
    # (stones, pillar waves, a current, a drum). Never a ride's pit nor a turning bridge's (the showcase of 13.11: a
    # trapdoor beside the island a ride serves - its grenade launcher a jump from the island's hyperblaster, 1.0 s on
    # the finished map)
    shared_ok = {r["space"] for r in P.pieces if r["kind"] in ("stones", "waves", "currents", "rotators")}
    shared_no = {r["space"] for r in P.pieces if r["kind"] in ("trains", "turn_bridges", "traps")}
    order = sorted((p for p in pits if p["space"] not in used), key=lambda p: len(p["cells"])) +         sorted((p for p in pits if p["space"] in shared_ok and p["space"] not in shared_no), key=lambda p: len(p["cells"]))
    for pit in order:
        s = P.spaces[pit["space"]]
        for c in sorted(pit["cells"]):
            rims = [(c[0] + dx, c[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
            rim = next((x for x in rims if s.floor.get(x) == (pit["base"], "flat", 0, 0) and x not in pit["cells"]
                        and x not in held), None)
            if rim is None or c in held:
                continue
            base = pit["base"]
            if not take_item(P, None, c, base, "a trapdoor", times_of):
                continue
            names = Names(P)
            tn = names("trapdoor")
            x0, y0, x1, y1 = cb(c, 2)
            low = pit["level"] if pit["level"] is not None else base - 160
            # the plate (16 deep) drops 32 under the liquid's surface: the game moves a door by its size less its lip, so
            # the lip is negative (3.68's first build clamped it to 8 - the floor dropped 8 and one stood on)
            rec = record(P, "trapdoors", cells=[c], space=pit["space"], over=pit["kind"])
            rec["ents"].append(ent({"classname": "func_door", "targetname": tn, "angle": -2, "speed": speed(P, 300),
                                    "wait": wait(P, 3.0), "lip": 16 - (base - low + 32), "_mapgen_floor": 1},
                                   [bx((x0, y0, base - 16), (x1, y1, base), "plate", note="trapdoor")]))
            relay = names("trapdoor_go")
            rec["ents"].append(ent({"classname": "trigger_relay", "targetname": relay, "target": tn,
                                    "delay": round(rnd.choice((TRAPDOOR_DELAY, 0.6, 1.0)), 1),
                                    "origin": f"{mid(c)[0]:.0f} {mid(c)[1]:.0f} {base + 48}"}))
            rec["item_target"] = (c, relay)
            node(P, c, base)
            held.update({c, rim})
            used.add(pit["space"])
            P.reasons.append(("func_door", say(f"ценный предмет на полу над {_liq_ru(pit)}: взял - через мгновение пол проваливается",
                                               f"a valuable item on a floor over the {pit['kind']}: taken, the floor drops a moment later")))
            return True
    return False


# --------------------------------------------------------------------------------------------- geysers
def geysers(P, rnd, held, pits, used, times_of) -> bool:
    plan_mod = base_mod.pm()
    door_cells = {c for d in P.doors for c in d.cells}
    halls = [s for s in P.spaces if not s.solid and s.kind == "hall" and s.floor and s.ceil - s.base >= 224
             and plan_mod.layer_of(next(iter(s.floor))) == 0]
    rnd.shuffle(halls)
    its = [c for (cls, c, z, note) in P.items if cls in base_mod.GUARD_ITEMS]
    for s in halls:
        cand = [c for c, f in s.floor.items() if f == (s.base, "flat", 0, 0) and c not in held and c not in door_cells
                and all(s.floor.get((c[0] + dx, c[1] + dy)) == (s.base, "flat", 0, 0)
                        for dx in (-1, 0, 1) for dy in (-1, 0, 1))]
        if not cand:
            continue
        cand.sort(key=lambda c: min((abs(c[0] - i[0]) + abs(c[1] - i[1]) for i in its), default=0))
        near = [c for c in cand if min((abs(c[0] - i[0]) + abs(c[1] - i[1]) for i in its), default=9) >= 2]
        c = (near or cand)[0]
        names = Names(P)
        tn = names("geyser")
        z = s.base
        x0, y0, x1, y1 = cb(c, 12)
        # the hole: the cell's floor 32 down, lava in it; the column rising out of it (func_water, lava)
        s.floor[c] = (z - 32, "flat", 0, 0)
        P.liquids.append(([c], "lava", z - 32, z - 12))
        P.no_items.add(c)
        rise = min(160, s.ceil - z - 48)
        rec = record(P, "geysers", cells=[c], space=s.id)
        rec["brushes"].append(bx((cb(c)[0], cb(c)[1], z - 8), (cb(c)[2], cb(c)[3], z), "trim", contents=0, note="geyser rim"))
        rec["ents"].append(ent({"classname": "func_water", "targetname": tn, "angle": -1, "lip": 0,
                                "speed": speed(P, 160), "wait": wait(P, GEYSER_UP)},
                               [bx((x0, y0, z - 12 - rise), (x1, y1, z - 12), "lava", contents=8, note="geyser")]))
        rec["ents"].append(_timer(tn, wait(P, rnd.choice((GEYSER_WAIT, 4.0, 6.0))), rand=1.0, origin=(mid(c)[0], mid(c)[1], z + 64)))
        held.add(c)
        P.reasons.append(("func_water", say(f"лавовый гейзер в полу зала {s.id} бьёт вверх по таймеру",
                                            f"a lava geyser in hall {s.id}'s floor erupting on a timer")))
        return True
    return False


# --------------------------------------------------------------------------------------------- turning bridges
def turn_bridges(P, rnd, held, pits, used, times_of) -> bool:
    for pit in sorted(pits, key=lambda p: -len(p["cells"])):
        if pit["space"] in used:
            continue
        rs = runs(P, pit, held)
        xs = {tuple(r[0]): r for r in rs if r[3] == (1, 0)}
        ys = {tuple(r[0]): r for r in rs if r[3] == (0, 1)}
        for rx in xs.values():
            for ry in ys.values():
                common = set(rx[0]) & set(ry[0])
                if len(common) != 1 or len(rx[0]) != len(ry[0]):
                    continue
                centre = common.pop()
                n_ = len(rx[0])
                # the plank turns about the pit's middle: the cell's middle (odd) or its corner (even)
                if rx[0].index(centre) not in (n_ // 2, (n_ - 1) // 2) or ry[0].index(centre) not in (n_ // 2, (n_ - 1) // 2):
                    continue
                base = pit["base"]
                xs_ = [cb(x)[0] for x in rx[0]] + [cb(x)[2] for x in rx[0]]
                ys_ = [cb(x)[1] for x in ry[0]] + [cb(x)[3] for x in ry[0]]
                cx, cy = (min(xs_) + max(xs_)) / 2, (min(ys_) + max(ys_)) / 2
                half = len(rx[0]) * CELL / 2 - 4
                names = Names(P)
                tn = names("turnbridge")
                a, b, c_, d = rx[1], rx[2], ry[1], ry[2]
                link = (f"{mid(a)[0]:.0f} {mid(a)[1]:.0f} {base} {mid(b)[0]:.0f} {mid(b)[1]:.0f} {base};"
                        f"{mid(c_)[0]:.0f} {mid(c_)[1]:.0f} {base} {mid(d)[0]:.0f} {mid(d)[1]:.0f} {base}")
                rec = record(P, "turn_bridges", cells=list(set(rx[0]) | set(ry[0])), space=pit["space"], over=pit["kind"])
                rec["ents"].append(ent({"classname": "func_door_rotating", "targetname": tn, "origin": f"{cx:.0f} {cy:.0f} {base - 8:.0f}",
                                        "distance": 90, "speed": speed(P, 30), "spawnflags": 32, "_mapgen_link": link},
                                       [bx((cx - half, cy - 24, base - 16), (cx + half, cy + 24, base), "plate", note="turning bridge")]))
                rec["ents"].append(_timer(tn, wait(P, rnd.choice((TURN_WAIT, 4.0, 6.0))), origin=(cx, cy, base + 96)))
                edge(P, a, b, len(rx[0]) * CELL / 250 + 2)
                edge(P, c_, d, len(ry[0]) * CELL / 250 + 4)
                held.update(set(rx[0]) | set(ry[0]))
                used.add(pit["space"])
                P.reasons.append(("func_door_rotating", say(f"поворотный мост над {_liq_ru(pit)}: соединяет то одни берега, то другие",
                                                            f"a turning bridge over the {pit['kind']}: it joins one pair of sides, then the other")))
                return True
    return False


# --------------------------------------------------------------------------------------------- current floors
def currents(P, rnd, held, pits, used, times_of) -> bool:
    for pit in sorted(pits, key=lambda p: -len(p["cells"])):
        if pit["space"] in used:
            continue
        for cells, rim_a, rim_b, d in sorted(runs(P, pit, held), key=lambda r: (-len(r[0]), r[1])):
            if len(cells) < 3:
                continue
            s = P.spaces[pit["space"]]
            base = pit["base"]
            _remove_from_liquid(P, pit, set(cells))
            for c in cells:
                s.floor[c] = (base, "flat", 0, 0)
            sideways = rnd.random() < 0.6
            push = (d[1], d[0]) if sideways else (-d[0], -d[1])
            if sideways and rnd.random() < 0.5:
                push = (-push[0], -push[1])
            flag = CURRENT_FLAGS[push]
            rec = record(P, "currents", cells=list(cells), space=pit["space"], over=pit["kind"],
                         variant="sideways" if sideways else "against")
            xs = [cb(c)[0] for c in cells] + [cb(c)[2] for c in cells]
            ys = [cb(c)[1] for c in cells] + [cb(c)[3] for c in cells]
            rec["brushes"].append(bx((min(xs), min(ys), base - 2), (max(xs), max(ys), base), "current",
                                     contents=1 | flag, note=f"current {push}"))
            rec["push"] = list(push)
            held.update(cells)
            used.add(pit["space"])
            P.reasons.append(("current", say(f"мост через {_liq_ru(pit)} с течением: пол тянет {'вбок' if sideways else 'назад'}",
                                             f"a bridge over the {pit['kind']} with a current: its floor pulls {'sideways' if sideways else 'back'}")))
            return True
    return False


# --------------------------------------------------------------------------------------------- pillar waves
def waves(P, rnd, held, pits, used, times_of) -> bool:
    for pit in sorted(pits, key=lambda p: -len(p["cells"])):
        if pit["space"] in used or pit["kind"] == "chasm":
            continue
        for cells, rim_a, rim_b, d in sorted(runs(P, pit, held), key=lambda r: (-len(r[0]), r[1])):
            if len(cells) < 3:
                continue
            base = pit["base"]
            names = Names(P)
            w = wait(P, rnd.choice((3.0, 4.0)))
            step = round(rnd.choice((WAVE_STEP, 0.5, 0.8)), 1)
            down = wait(P, 1.5)
            sink = base - pit["level"] + 40
            rec = record(P, "waves", cells=list(cells), space=pit["space"], over=pit["kind"])
            for i, c in enumerate(cells):
                tn = names("pillar")
                x0, y0, x1, y1 = cb(c, 8)
                rec["ents"].append(ent({"classname": "func_door", "targetname": tn, "angle": -2, "speed": speed(P, 120),
                                        "wait": down, "lip": max(8, base - pit["floor"] - sink), "_mapgen_floor": 1},
                                       [bx((x0, y0, pit["floor"]), (x1, y1, base), "plate", note="wave pillar")]))
                rec["ents"].append(_timer(tn, w, delay=1.0 + i * step, origin=(mid(c)[0], mid(c)[1], base + 64)))
                node(P, c, base)
            held.update(cells)
            used.add(pit["space"])
            P.reasons.append(("func_door", say(f"столбы в {_liq_ru(pit)} уходят вниз волной один за другим - перебегать по поднятым",
                                               f"pillars in the {pit['kind']} sink in a wave one after another - one crosses on those up")))
            return True
    return False
