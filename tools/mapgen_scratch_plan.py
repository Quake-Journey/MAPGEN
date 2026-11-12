r"""Brief 19 D1: the skeleton of a map made from scratch - places, levels, routes - before a brush exists.

A Quake II deathmatch map, measured (Fable's research of 04.11), is a compact floor plan: a duel walks 1.6-2.7 M u²
of floor in a 1.2-2.4k square, on three or four standing levels 64-128 apart, 40 % of the floor corridors 128-192
wide, half rooms, a tenth open; its items stand on ledges with two or three ways out and a route around every
choke. The September generator put one box in a 1536-unit cell with tubes between; this one does what a mapper's
plan does:

  * the footprint is SPLIT, wall by wall, into halls, rooms and corridor strips that share their walls - packed,
    not spread (`split_plan`);
  * the walls get doors where a route is wanted: a spanning tree, then loops until most places have two ways out
    (`connect`);
  * each part takes a floor level, each hall a terrace pattern inside it - a balcony along a wall, a platform, a
    split level, a pit - and every height difference becomes a flight of steps, a corridor's stairs, a lift or a
    drop (`heights`, `realise`);
  * the items and the spawns are placed by the mechanics people play (`places`), the times between them measured
    on the plan's own walk graph, and the whole plan is scored against the human bands (`score`); the best of many
    seeds is built.

Everything is in 64-unit cells; heights in units. The world it hands the builder is per cell a list of air spans
(`Air`), plus shaped pieces, movers, lights and entities (`to_world`).

    python tools/mapgen_scratch_plan.py --players 2 --seed 7 --png plan.png
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

CELL = 64
DOOR_H = 128
STEP = 16
RISE_PER_CELL = 32            # two 16-unit steps over a 64-unit cell (32-unit treads)
# brief 21 (brief 20 D5): a room over another room. The plan's cells have one owner each; the room on top lives on a
# second layer of cell keys, its y shifted by UP - the walk graph, the places and the scores step within a layer by
# the same arithmetic, a door marked `cross` joins the layers, and the builder takes every cell back by `phys`
UP = 4096
SLAB = 16                     # the floor between a room and the room over it (people's floors 16..32)


def is_up(c) -> bool:
    return c[1] >= UP // 2


def phys(c):
    """A plan cell's place in the world (the upper layers' cells over the lower's). Brief 25 B: a tower keeps each
    storey on a layer of its own, its cells' y shifted by UP times the storey - the world cell is y modulo UP."""
    return (c[0], c[1] % UP) if c[1] >= UP // 2 else c


# --------------------------------------------------------------------------------------------- the majors apart
# The PO 12.11 on his mg_new_84719 (a yellow and a green armour 231 u / 0.8 s apart in one room, the railgun 270 u off -
# the green one «armour by the key gun», brief 19's key_gun_ledge): «нельзя класть рядом предметы одного класса - это же
# глупо. Арморы должны лежать далеко друг от друга, так же как оружия далеко друг от друга и не близко к арморам, и
# паверапы так же»; «айтемы, оружие, броня, паверапы, они должны иметь ценность подбора. Когда ты пихаешь их рядом то
# ценность становится равна почти нулю»; «люди выстраивают тактику в подборе айтемов, а тут пришел, сел около них и почти
# ничего больше делать не надо»; «туже рельсу класть в шаге от двух арморов - глупо». His rule, not people's: people's
# maps put a gun by an armour now and then (q2duel1 HB 237 u from the GA, koldduel1 SSG 197 u) - none near, here.
ARMOURS = ("item_armor_body", "item_armor_combat", "item_armor_jacket")
POWER_ITEMS = ("item_quad", "item_invulnerability", "item_power_shield", "item_power_screen", "item_health_mega",
               "item_adrenaline")
MAJORS_APART_SAME = (2.5, 512.0)     # two of one class (armours, guns, powerups): seconds on foot, units straight
MAJORS_APART_CROSS = (1.5, 384.0)    # a gun and an armour, a powerup and either
MAJORS_PLAN_SLACK = 1.2              # the compiled map walks quicker than the plan's cells (a duel of 12.11: 1.47 s
                                     # measured for 1.65 planned) - the plan asks 20 % more
# the RED: 3.65's placement (an armour by the key gun, nothing kept apart); MAPGEN_OLD_MAJORS=1 sets it for a process
OLD_MAJORS = __import__("os").environ.get("MAPGEN_OLD_MAJORS") == "1"
# the knowledge base's rules (tools/mapgen_item_practice.py --rules): each pair of classes no nearer than people's lower
# quartile (the median with «item_spacing» wide), each prize's ways as people's take them; per family for
# «item_practice» (a family of few pairs takes the whole base's number for that pair)
ITEM_PRACTICES = ("mix", "q2dm", "q2duel", "q2rdm", "ztn2dm", "omf", "koldduel1", "ptrip", "match1",
                  "q2duel+ztn2dm", "q2dm+q2rdm", "q2duel+koldduel1", "q2dm+ztn2dm", "q2rdm+omf", "ptrip+match1",
                  "q2dm+q2duel", "ztn2dm+q2rdm")
PRIZE_ACCESS = ("people", "nooks", "movers", "water", "exposed")
PRIZE_ORDER = ("item_invulnerability", "item_quad", "weapon_railgun", "item_health_mega", "item_armor_body",
               "item_power_shield")
DIVE_DEPTH = 160                     # a dive: the well's floor under the room's (a man of 56 under water, his eyes too)
# The PO 12.11 on his mg_new_7775 («q2dm1 с призами под водой»): «никакого глубокого бассейна по типу как на q2dm1 в
# котором плывешь за рейлом - я не получил, только узкая небольшая подводная нычка под стенкой», «на q2dm1 там глубокий
# большой водоем через который нужно плыть и там еще и труба есть по которой плывут до выхода на рейл», «на q2dm4 или
# q2dm5 там вообще многоуровневые конструкции с множеством глубоких водоемов через которые можно плавать», «плоская
# карта». Water as well-known maps build it (tools/mapgen_water_practice.py, the BSPs of his 40 maps): the deep bodies
# q2dm1 248 deep (a pool of 55 cells, a tube 368 u long, 112 high, to the railgun's room and its own pool), q2dm2 120
# and 216 (three pools joined by tubes of 528..752 u), q2dm4 232 and 432 (pools on four levels, tubes of 720..1024 u),
# q2dm5 208 (two levels, a tube 784 u, 128 high), q2rdm13 224 (two levels, a tube 384 u). Ours to 3.66: pits 48 deep.
WATER_BODIES = ("people", "levels", "shallow")
POOL_DEPTH = 224         # the water's depth: people's deep bodies' median (120 208 216 224 232 248 432)
POOL_SURFACE = 8         # the water under the rim's floor (q2dm1's 8): one climbs out anywhere round the pool - the
                         # game's jump out of water needs the floor under 20 over the man's middle; at 24 under the
                         # rim nobody came out (a test map of 12.11: 1392 trapped places by the game's movement)
POOL_MIN = 12            # a pool's cells at least: people's deep pools 14..195 (a room's own pool past a tube aside) - the check
                         # asks 12 (a duel's pool of 10 cells read as a well, 12.11)
TUBE_H = 96              # people's tubes 64..128 high (q2dm1 112, q2dm2 80 and 96, q2dm4 64 and 96, q2dm5 128)
TUBE_CELLS = (6, 12)     # a tube's cells: 384..768 u - people's 368..1024; a breath is 12 s, one swims 150 u/s
VAULT_CEIL = DOOR_H + 16       # the prize's room: a doorway's height and a slab
# the RED: 3.66's water (pits 48 deep, a dive 64 x 64 into a vault one cell wide); MAPGEN_OLD_WATER=1 for a process
OLD_WATER = os.environ.get("MAPGEN_OLD_WATER") == "1"


def door_top(d) -> int:
    """A doorway's top: a tube's roof (the PO 12.11 - its top may be 0, which `top` cannot say), an overlook's own, or
    the doorway's height over its sill."""
    if d.kind == "swim":
        return d.z + TUBE_H
    return d.top or (d.z + 32 + DOOR_H if d.stair else d.z + DOOR_H)


def beside_water(P, cells) -> bool:
    """A window's cells beside water (the PO 12.11: a deep pool's floor is its bottom - a window over it opened under
    its surface, a test plan of 12.11)."""
    if OLD_WATER:
        return False
    wet = {c for (cs, kind, _z0, _lv) in P.liquids for c in cs}
    return any((c[0] + dx, c[1] + dy) in wet for c in cells for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def water_deep(q: dict) -> bool:
    """Water as well-known maps have it - deep pools one swims in (the PO 12.11) - unless 3.66's shallow pits asked."""
    return not OLD_WATER and (q or {}).get("water_body", "people") != "shallow"


def deep_pools_only(q: dict) -> bool:
    """Every sunken middle asked is a deep pool of water: water (or a prize under water) and no lava, slime or chasm."""
    q = q or {}
    return (water_deep(q) and (float(q.get("water") or 0) > 0 or int(q.get("underwater") or 0) > 0)
            and not float(q.get("lava") or 0) and not float(q.get("slime") or 0) and not int(q.get("pits") or 0))


POOL_SHARE = 0.45        # a deep pool's share of its hall at most (brief 20 D4's third for the pits of before: a pool
                         # one swims across is a way of its own - q2dm1's is most of its hall)


def _item_rules() -> dict:
    try:
        return json.loads((Path(__file__).resolve().parent / "mapgen_item_rules.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


ITEM_RULES = _item_rules()


def item_rules(q: dict | None) -> dict:
    """The rules of the practice asked (the whole base by default; two families joined by «+» - a mix of them: the
    distances their mean, the prizes' ways both families' together)."""
    fam = (q or {}).get("item_practice") or "mix"
    fams = ITEM_RULES.get("families") or {}
    if fam == "mix":
        return ITEM_RULES
    if "+" not in fam:
        return fams.get(fam) or ITEM_RULES
    parts = [fams[f] for f in fam.split("+") if f in fams]
    if not parts:
        return ITEM_RULES
    out = {"apart": {}, "prizes": {}}
    for key in {k for p_ in parts for k in (p_.get("apart") or {})}:
        rs = [p_["apart"][key] for p_ in parts if key in (p_.get("apart") or {}) and p_["apart"][key].get("units")]
        if not rs:
            continue
        merged = {"n": sum(r.get("n") or 0 for r in rs)}
        for f_ in ("units", "s", "p10_units", "p10_s", "median_units", "median_s"):
            vals = [float(r[f_]) for r in rs if r.get(f_) is not None]
            merged[f_] = round(sum(vals) / len(vals), 2) if vals else None
        out["apart"][key] = merged
    for cls in {c for p_ in parts for c in (p_.get("prizes") or {})}:
        rs = [p_["prizes"][cls] for p_ in parts if cls in (p_.get("prizes") or {})]
        n = sum(r.get("n") or 0 for r in rs)
        moves = {}
        for r in rs:
            for k, v in (r.get("moves") or {}).items():
                moves[k] = moves.get(k, 0) + v
        out["prizes"][cls] = {"n": n, "moves": moves,
                              "exposed": round(sum((r.get("exposed") or 0) * (r.get("n") or 0) for r in rs) / max(1, n), 2)}
    return out


def major_kind(cls: str) -> str | None:
    """«armour», «weapon», «power» - the items whose worth is picking them up; None for the rest."""
    if cls in ARMOURS:
        return "armour"
    if cls in POWER_ITEMS:
        return "power"
    if cls.startswith("weapon_") and cls != "weapon_blaster":
        return "weapon"
    return None


def majors_need(a: str, b: str, q: dict | None = None) -> tuple:
    """The distance two major items keep: (seconds on foot, units straight) - people's lower quartile for their two
    classes (the knowledge base), the median with «item_spacing» wide."""
    ka, kb = major_kind(a), major_kind(b)
    if ka is None or kb is None:
        return (0.0, 0.0)
    order = ("power", "weapon", "armour")
    x, y = sorted((ka, kb), key=order.index)
    wide = (q or {}).get("item_spacing") == "wide"
    key_s, key_u = ("median_s", "median_units") if wide else ("s", "units")
    whole = (ITEM_RULES.get("apart") or {}).get(f"{x}-{y}") or {}
    for src in (item_rules(q), ITEM_RULES):
        r = (src.get("apart") or {}).get(f"{x}-{y}")
        if r and (r.get("n") or 0) >= 8 and r.get(key_u) and r.get(key_s):
            t, u = float(r[key_s]), float(r[key_u])
            if whole.get("p10_s") and whole.get("p10_units"):
                # a family never nearer than the whole base's tenth; two armours never nearer than its quarter (the PO
                # 12.11: «никогда арморы не лежат рядом !!! Никогда !»)
                floor_ = (whole["s"], whole["units"]) if x == y == "armour" else (whole["p10_s"], whole["p10_units"])
                t, u = max(t, float(floor_[0])), max(u, float(floor_[1]))
            return (t, u)
    return MAJORS_APART_SAME if ka == kb else MAJORS_APART_CROSS


def _item_at(c, z) -> tuple:
    pc = phys(c)
    return ((pc[0] + 0.5) * CELL, (pc[1] + 0.5) * CELL, z)


def majors_apart(P: Plan, cls: str, c, z, times_of, skip: int | None = None, extra: float = 0.0, at=None) -> bool:
    """Whether `cls` at cell `c` (floor `z`) keeps the PO's distance from every major item already placed - on foot
    (`times_of(cell)`: the plan's seconds from that cell) and straight (through a wall or a floor it is near too);
    `skip`: the item's own index when it moves; `extra`, `at`: a place not in the plan's walk yet (a room past a tube
    under water) - its seconds past `c` and where it stands."""
    if OLD_MAJORS or major_kind(cls) is None:
        return True
    at = at or _item_at(c, z)
    for k2, (cls2, c2, z2, _n) in enumerate(P.items):
        if major_kind(cls2) is None or k2 == skip:
            continue
        t_need, d_need = majors_need(cls, cls2, P.params)
        if majors_close(math.dist(at, _item_at(c2, z2)), times_of(c2).get(c, 99.0) + extra, t_need * MAJORS_PLAN_SLACK, d_need):
            return False
    return True


def farthest_from_majors(P: Plan, cells, z_of):
    """Where nothing keeps the rule (a small map, many majors): the cell farthest straight from every major placed."""
    its = [_item_at(c2, z2) for cls2, c2, z2, _n in P.items if major_kind(cls2)]
    if not its or not cells:
        return cells[0] if cells else None
    return max(cells, key=lambda x: min(math.dist(_item_at(x, z_of(x)), a) for a in its))


def majors_close(units: float, seconds: float, t_need: float, d_need: float) -> bool:
    """Near: a short walk from one to the other, or near straight and not far on foot either (a prize through a wall
    that takes 5 s to walk round to is not taken with the other - its pick-up worth stays)."""
    return seconds < t_need or (units < d_need and seconds < t_need * 1.5)


def majors_near(P: Plan, edges) -> list:
    """Every pair of major items nearer than the rule, on the plan: «cls/cls2 seconds s units u»."""
    cache: dict = {}

    def tim(c):
        if c not in cache:
            cache[c] = dijkstra(edges, c)
        return cache[c]
    its = [(cls, c, z) for cls, c, z, _n in P.items if major_kind(cls)]
    out = []
    for i, (a, ca, za) in enumerate(its):
        for b, cb, zb in its[i + 1:]:
            if ca == cb:
                continue            # an item team taking turns on one spot (the powerups' cycle, q2dm8's)
            t_need, d_need = majors_need(a, b, P.params)
            d = math.dist(_item_at(ca, za), _item_at(cb, zb))
            t = min(tim(ca).get(cb, 99.0), tim(cb).get(ca, 99.0))
            if majors_close(d, t, t_need, d_need):
                out.append(f"{a}/{b} {t:.1f} s {d:.0f} u")
    return out


def layer_of(c) -> int:
    """The layer a plan cell is on: 0 the ground, 1 a room over a room (or a tower's first storey), k a tower's k-th."""
    return c[1] // UP if c[1] >= UP // 2 else 0


def up(c):
    return (c[0], c[1] + UP)


# --------------------------------------------------------------------------------------------- parameters
CLASS_ITEMS = {
    # weapon sites, armour, health and ammo per player class (research §4: the medians, sites per map)
    "duel": {"weapon_supershotgun": 1, "weapon_chaingun": 1, "weapon_grenadelauncher": 1, "weapon_rocketlauncher": 1,
             "weapon_hyperblaster": 1, "weapon_railgun": 1},
    "ffa8": {"weapon_shotgun": 1, "weapon_supershotgun": 1, "weapon_machinegun": 1, "weapon_chaingun": 1,
             "weapon_grenadelauncher": 1, "weapon_rocketlauncher": 1, "weapon_hyperblaster": 1, "weapon_railgun": 1},
    "ffa11": {"weapon_shotgun": 1, "weapon_supershotgun": 2, "weapon_machinegun": 1, "weapon_chaingun": 1,
              "weapon_grenadelauncher": 1, "weapon_rocketlauncher": 2, "weapon_hyperblaster": 1, "weapon_railgun": 1},
    "ffa16": {"weapon_shotgun": 2, "weapon_supershotgun": 2, "weapon_machinegun": 2, "weapon_chaingun": 1,
              "weapon_grenadelauncher": 1, "weapon_rocketlauncher": 2, "weapon_hyperblaster": 1, "weapon_railgun": 1,
              "weapon_bfg": 1},
}
STACK_SETS = {
    "ra_mh": {"item_armor_body": 1, "item_health_mega": 1, "item_armor_combat": 1, "item_armor_jacket": 1},
    # brief 21 D6, the PO 05.11 («для ffa карты вообще ни одного паверапа не увидел - где там квад?»): 5 of the 8 q2dm
    # hold a quad (q2dm2..6) - the FFA default
    "ra_mh_quad": {"item_armor_body": 1, "item_health_mega": 1, "item_armor_combat": 1, "item_quad": 1},
    "mh_adren_2ya": {"item_health_mega": 1, "item_adrenaline": 1, "item_armor_combat": 2},
    "2ya_adren_quad": {"item_armor_combat": 2, "item_adrenaline": 1, "item_quad": 1},
}
AMMO_OF = {"weapon_shotgun": "ammo_shells", "weapon_supershotgun": "ammo_shells", "weapon_machinegun": "ammo_bullets",
           "weapon_chaingun": "ammo_bullets", "weapon_grenadelauncher": "ammo_grenades",
           "weapon_rocketlauncher": "ammo_rockets", "weapon_hyperblaster": "ammo_cells", "weapon_railgun": "ammo_slugs",
           "weapon_bfg": "ammo_cells"}
DUEL_MECHANICS = ["clock", "halves", "key_gun_ledge", "asymmetry", "small_health", "spawn_pressure"]
# brief 19 §6: every mechanic a switch (the Studio's names); «adrenaline tucked» is a rule, not a switch, and the
# opening race is a note in the record
ALL_MECHANICS = DUEL_MECHANICS + ["three_approaches", "tele_mirror", "pad_pit", "lift_exposure", "ladder_item",
                                  "dead_end_stack"]
SHAPES = ("halves", "arena", "ring", "space", "tower")
MAJOR_ITEMS = ("item_armor_body", "item_armor_combat", "item_health_mega", "item_quad", "item_invulnerability")


def say(ru: str, en: str) -> str:
    """A line of the record in both languages: «ru ¦ en» - write_record takes the half of the description's language."""
    return f"{ru} ¦ {en}"


def player_class(players: int) -> str:
    return "duel" if players <= 2 else "ffa8" if players <= 8 else "ffa11" if players <= 11 else "ffa16"


def defaults(p: dict) -> dict:
    """Every parameter the PO named, with «по умолчанию» resolved from the player count (and said in the record)."""
    q = dict(p)
    players = int(q.get("players") or 2)
    q["players"] = players
    cls = player_class(players)
    q["class"] = cls
    q.setdefault("spawns", None)
    if not q["spawns"]:
        q["spawns"] = {"duel": 7, "ffa8": 8, "ffa11": 10, "ffa16": 13}[cls]
    if q.get("floor_area"):
        q["floor_area_asked"] = True
    else:
        q["floor_area"] = {"duel": 2.0, "ffa8": 3.0, "ffa11": 3.6, "ffa16": 4.6}[cls]
    if not q.get("levels"):
        q["levels"] = 4
    q.setdefault("sky", 0.3)
    if q.get("sky") is None:
        q["sky"] = 0.3
    if not q.get("mode"):
        q["mode"] = "duel" if cls == "duel" else "ffa"
    if not q.get("shape"):
        q["shape"] = "halves" if (cls == "duel" or q["mode"] == "tdm") else "arena"
    if q["shape"] == "space":
        # brief 25 A1: islands in the void - its own defaults before the rooms' generic ones fill what is left
        import mapgen_scratch_space as space_mod
        space_mod.space_defaults(q, p)
    elif q["shape"] == "tower":
        # brief 25 B: whole storeys over one footprint - its own defaults likewise
        import mapgen_scratch_tower as tower_mod
        tower_mod.tower_defaults(q, p)
    if q["shape"] not in SHAPES:
        # a tower (levels stacked over one footprint) is not what a plan of one floor per cell can make: said, and
        # the map is made as one arena (D5: refused with the reason, never silently changed)
        q["refused"] = list(q.get("refused") or []) + [
            say(f"форма «{q['shape']}»: план из одного пола на клетку не ставит этажи друг над другом - сделана одна арена",
                f"shape «{q['shape']}»: a plan of one floor per cell cannot stack storeys over each other - one arena was made")]
        q["shape"] = "arena"
    # brief 21: the long lines not asked are held to people's, not to one number (people's 18 duels: 0..7, 14 of them 4
    # or fewer; 8 FFA: 1..6) - asked N, the check holds N..N+1 / N..N+3 as before
    if q.get("long_lines") is None:
        q["long_lines_default"] = True
    for k, v in (("lifts", 2 if cls == "duel" else 2), ("pads", 0 if cls == "duel" else 1),
                 ("teleporters", 0 if cls == "duel" else 1), ("ladders", 0), ("doors", 0),
                 ("long_lines", 2 if cls == "duel" else 4),
                 ("water", 0.05), ("lava", 0.0), ("slime", 0.0), ("pits", 0), ("windows", 4),
                 ("stairs", None), ("ramps", 0), ("drops", None), ("vertical_span", None), ("openness", None),
                 ("shards", 6 if cls == "duel" else 8), ("ammo_per_spawn", 2.5), ("health_per_spawn", 1.3),
                 ("decor", "default"), ("sun", "style"), ("tone", "style")):
        if q.get(k) is None:
            q[k] = v
    # «по умолчанию by levels»: a flight per level change at least, a drop per two
    if q["stairs"] is None:
        q["stairs_default"] = True
        q["stairs"] = max(2, int(q.get("levels") or 4) - 1)
    if q["drops"] is None:
        q["drops_default"] = True
        q["drops"] = max(1, (int(q.get("levels") or 4) - 1) // 2)
    if not q.get("weapons"):
        q["weapons"] = dict(CLASS_ITEMS[cls])
    if not q.get("stack"):
        q["stack"] = "ra_mh_quad" if cls != "duel" else "ra_mh"
    if q.get("items_at_height") is None:
        q["items_at_height"] = 0.67
    if q.get("mechanics") is None:
        q["mechanics"] = list(DUEL_MECHANICS) if cls == "duel" else ["clock", "small_health", "spawn_pressure"]
        if q["shape"] == "halves" and "halves" not in q["mechanics"]:
            q["mechanics"].append("halves")
    q.setdefault("style", {"source": "generator"})
    # the PO, 04.11: «висящих в воздухе архитектурных штучек ... в картах людей такого нет» - no wall panels unless asked
    q.setdefault("decor", "none")
    q.setdefault("water_above_floor", False)
    q.setdefault("light", "default")
    # the PO 06.11: the single-player game's ships flying over the map (mapgen_scratch_ships) - none unless asked
    q["ships"] = max(0, min(3, int(q.get("ships") or 0)))
    # brief 21+ (the PO 05.11): how hard the powerups are to get - easy | medium | hard | mixed (default)
    if q.get("powerup_access") not in ("easy", "medium", "hard", "mixed"):
        q["powerup_access"] = "mixed"
    # the PO 12.11: the items' pick-up worth - how the prizes are earned, how many under water, how far apart the
    # majors keep, whose practice (tools/mapgen_item_rules.json)
    if q.get("prize_access") not in PRIZE_ACCESS:
        q["prize_access"] = "people"
    q["underwater"] = max(0, min(3, int(q.get("underwater") or 0)))
    if q.get("item_spacing") not in ("people", "wide"):
        q["item_spacing"] = "people"
    if q.get("item_practice") not in ITEM_PRACTICES:
        q["item_practice"] = "mix"
    # the PO 12.11: water as well-known maps build it - deep pools (people), pools on several floors joined by tubes
    # under water (levels: q2dm4, q2dm5), or 3.66's pits 48 deep (shallow)
    if q.get("water_body") not in WATER_BODIES:
        q["water_body"] = "people"
    q["powerup_cycle"] = bool(q.get("powerup_cycle"))
    # 3.46: medusa_b1's round shapes - none unless asked
    if q.get("round") not in ("few", "some", "many"):
        q["round"] = ""
    kinds_ = [k_ for k_ in (q.get("round_kinds") or []) if k_ in ("corners", "apses", "podiums")]
    q["round_kinds"] = kinds_ or ["corners", "apses", "podiums"]
    if q["powerup_cycle"] and "clock" in (q.get("mechanics") or []):
        # the stack's armour and mega take turns in one nook: there is no clock between them
        q["mechanics"] = [m_ for m_ in q["mechanics"] if m_ != "clock"]
        q["refused"] = list(q.get("refused") or []) + [
            say("механика «два главных предмета на часах» не делалась: броня и мега меняются в одной нише (цикл)",
                "the «clock» mechanic was not made: the armour and the mega take turns in one nook (the cycle)")]
    return q


# --------------------------------------------------------------------------------------------- the plan's parts
@dataclass
class Rect:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    def cells(self):
        for x in range(self.x0, self.x1):
            for y in range(self.y0, self.y1):
                yield (x, y)

    def has(self, c):
        return self.x0 <= c[0] < self.x1 and self.y0 <= c[1] < self.y1


@dataclass
class Space:
    id: int
    kind: str                      # hall, room, corridor, shaft
    rect: Rect
    base: int = 0
    pattern: str = "flat"
    sky: bool = False
    ceil: int = 0
    floor: dict = field(default_factory=dict)      # cell -> (z, kind, dx, dy): kind flat | stair (rises 32 along dx,dy)
    tex: str = "a"                                 # which of the style's palettes
    solid: bool = False                            # a piece left as rock (massing), not a space
    extra: list = field(default_factory=list)      # cells merged in beyond the main rectangle (L, T, U shapes)
    atrium: bool = False
    pit: list = field(default_factory=list)        # the sunken cells of a pit or a bridge pattern
    wet: bool = False                              # chosen for a liquid or a chasm: its pit sized to the share
    rim: int = 2                                   # the walkway round a pit, in cells

    def has(self, c) -> bool:
        return c in self.floor if self.floor else (self.rect.has(c) or c in self.extra)

    def cells(self):
        yield from self.rect.cells()
        yield from self.extra

    def area(self) -> int:
        return self.rect.w * self.rect.h + len(self.extra)


@dataclass
class Door:
    a: int
    b: int
    cells: list                    # wall cells
    za: int = 0                    # floor at a's side
    zb: int = 0
    z: int = 0                     # the door's own floor (its low end when it carries steps)
    kind: str = "door"             # door | drop | overlook
    stair: tuple | None = None     # (dx, dy) when the door cell itself carries two steps rising that way
    top: int = 0                   # the opening's top when it is not the door's own height (an overlook)
    loop: bool = False             # a loop of the routes, not the spanning tree (a one-way drop here traps no one)
    mover: bool = False            # a func_door closes it (brief 19 §4 «Двери»)
    rj: bool = False               # a drop into a dead end, left by a rocket jump (brief 19 §6 «тупик со стеком»)
    cross: bool = False            # brief 21: its cells on the upper layer (a room over a room), its other side below
    laid: list = field(default_factory=list)   # brief 21 D2: (space id, cell, floor before) of the flight it laid


@dataclass
class Plan:
    params: dict
    seed: int
    W: int
    H: int
    spaces: list = field(default_factory=list)
    doors: list = field(default_factory=list)
    walls: set = field(default_factory=set)        # wall cells between spaces (rock unless a door/window opens them)
    items: list = field(default_factory=list)      # (classname, cell, z, note)
    spawns: list = field(default_factory=list)     # (cell, z, angle)
    lifts: list = field(default_factory=list)      # (plat cells, z_low, z_high, bottom cells, top cells)
    no_items: set = field(default_factory=set)     # cells an item or a spawn must not take (plats, pads, liquids)
    pads: list = field(default_factory=list)
    teleports: list = field(default_factory=list)
    liquids: list = field(default_factory=list)    # (cells, kind, z_floor, level)
    prize_kind: dict = field(default_factory=dict)  # the PO 12.11: an item's index -> how its prize is earned
    pillars: list = field(default_factory=list)    # (cell, z0, z1)
    chamfers: list = field(default_factory=list)   # (cell, corner, z0, z1)
    windows: list = field(default_factory=list)    # (cells, z0, z1)
    overlooks: list = field(default_factory=list)  # (cells, z_floor, z_top, high space, low space)
    lights: list = field(default_factory=list)     # (x, y, z, value, mount): mount None | (kind, ...) - lamp_sites
    ladders: list = field(default_factory=list)    # (door cells, into the low space, z_low, z_high, front cells)
    pits: list = field(default_factory=list)       # (cells, z_bottom, space id): a deadly drop, trigger_hurt
    ramps: set = field(default_factory=set)        # stair cells laid as a slope (a ramp) instead of two steps
    flights: list = field(default_factory=list)    # the flights of steps: sets of stair cells (a ramp's too)
    half: dict = field(default_factory=dict)       # space id -> 0 | 1 when the map is two halves
    dest_face: dict = field(default_factory=dict)  # a teleporter exit -> the yaw it faces (a key item, an open run)
    reasons: list = field(default_factory=list)    # (what, why) for every entity the mechanics placed
    owner: dict = field(default_factory=dict)      # cell -> space id
    notes: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    failed: str = ""
    asked: set = field(default_factory=set)        # brief 21 D2: the leaves a mechanic asked for (dead end, lift ledge)
    # 3.46 (medusa_b1's round architecture): corners and apses as fans of triangles from the corner point, podiums as
    # octagons in tiers; `rounded` - the cells they take a part of (nothing else goes there)
    rounds: list = field(default_factory=list)     # (corner point, [arc points], z0, z1, space id, kind)
    podiums: list = field(default_factory=list)    # ([outer octagon], [inner octagon] or None, z, space id)
    rounded: set = field(default_factory=set)
    # brief 25 A1 (shape «space»): running jumps off an island's edge onto a lower one - (edge cell, landing cell, time)
    # - in the walk graph; the railings the builder stands on the edges - (cell, side, floor z)
    air_edges: list = field(default_factory=list)
    railings: list = field(default_factory=list)
    # brief 25 B: pairs of spaces open to each other with no wall or door between (a tower's atrium and the ground
    # gallery round it: one floor, two ceilings)
    joined: set = field(default_factory=set)
    # brief 25 B: plan keys that are open air, not a wall - a tower's atrium on the storeys over the ground (a lamp
    # by such an edge would hang in the air, the PO 04.11)
    voids: set = field(default_factory=set)
    # brief 25 B: a cell's air stops under its space's ceiling here (plan key -> z): the atrium's column under a
    # tower's perch, the perch's slab between them
    cell_ceil: dict = field(default_factory=dict)
    # brief 32: the size each pad, teleporter frame and spawn plate is built at (mapgen_scratch_fixtures.plan_sizes)
    # and the cells the bigger ones reach - every stage after it leaves them alone
    fx_size: dict = field(default_factory=dict)
    fx_cells: set = field(default_factory=set)
    # brief 34 (the PO 08.11: «лифты как в небоскрёбах — едут между этажами, останавливаются там»): a lift that stops on
    # every storey - (platform cells (ground keys), [stop floor z], [the doorway's key on each stop], name)
    trains: list = field(default_factory=list)
    # brief 34: why each pad is there - (take-off, landing) -> «express» | «chain» | «perch» | «shaft» | «pit» |
    # «shortcut» | «link» (the description says the ways by it; «perch» and «pit» are pads by design)
    pad_why: dict = field(default_factory=dict)
    # the PO 12.11: the deep pools of water ({space, cells, bottom, surface}) and the tubes under water between them
    pools: list = field(default_factory=list)


# --------------------------------------------------------------------------------------------- 1. the floor plan
def split_plan(P: Plan, rnd: random.Random) -> None:
    """The footprint split wall by wall into pieces; thin pieces are corridors, big ones halls; a few left rock."""
    q = P.params
    floor_cells = q["floor_area"] * 1e6 / (CELL * CELL)
    # brief 21: 1.55 until the corridor pieces turned some rooms partly to rock (a duel planned 1.65..1.85 for 2.0)
    side = math.sqrt(floor_cells * 1.85)   # 1.85 since brief 21: leaves turned to bays and rock took more floor
    aspect = rnd.uniform(0.85, 1.25)
    P.W = max(16, int(round(side * math.sqrt(aspect))))
    P.H = max(16, int(round(side / math.sqrt(aspect))))
    pieces: list[tuple[Rect, str]] = []
    # brief 21 D3: a duel hall of 12 cells held a sight line across its own diagonal (12 x 8: 1100 u); 10 at most
    max_room = 10 if q["class"] == "duel" else 14

    def rec(r: Rect, depth: int):
        w, h = r.w, r.h
        # a corridor strip cut off along the longer side, now and then
        if min(w, h) >= 9 and max(w, h) <= 16 and depth >= 1 and rnd.random() < 0.35 and depth < 6:
            cw = rnd.choice((2, 2, 3))
            along_x = w >= h
            if along_x:   # strip spans x, cut in y
                at = rnd.choice((r.y0 + 3 + rnd.randrange(max(1, h - 3 - cw - 3)), ))
                strip = Rect(r.x0, at, r.x1, at + cw)
                a = Rect(r.x0, r.y0, r.x1, at - 1)
                b = Rect(r.x0, at + cw + 1, r.x1, r.y1)
            else:
                at = r.x0 + 3 + rnd.randrange(max(1, w - 3 - cw - 3))
                strip = Rect(at, r.y0, at + cw, r.y1)
                a = Rect(r.x0, r.y0, at - 1, r.y1)
                b = Rect(at + cw + 1, r.y0, r.x1, r.y1)
            if min(a.w, a.h) >= 3 and min(b.w, b.h) >= 3:
                pieces.append((strip, "corridor"))
                rec(a, depth + 1)
                rec(b, depth + 1)
                return
        big = max(w, h)
        stop = big <= max_room and (min(w, h) <= 6 or rnd.random() < (0.25 + 0.12 * depth))
        if stop or big < 9:
            if min(w, h) <= 3:
                pieces.append((r, "corridor"))
            elif min(w, h) >= 7 and w * h >= 56:
                pieces.append((r, "hall"))
            else:
                pieces.append((r, "room"))
            return
        if w > h or (w == h and rnd.random() < 0.5):
            cut = r.x0 + rnd.randint(4, w - 5) if w >= 10 else r.x0 + w // 2
            rec(Rect(r.x0, r.y0, cut, r.y1), depth + 1)
            rec(Rect(cut + 1, r.y0, r.x1, r.y1), depth + 1)
        else:
            cut = r.y0 + rnd.randint(4, h - 5) if h >= 10 else r.y0 + h // 2
            rec(Rect(r.x0, r.y0, r.x1, cut), depth + 1)
            rec(Rect(r.x0, cut + 1, r.x1, r.y1), depth + 1)

    rec(Rect(1, 1, P.W - 1, P.H - 1), 0)
    # a few pieces become rock - massing, so the plan is not a full grid of rooms - most of them on the edge, which
    # breaks the outline's rectangle
    def on_edge(r):
        return r.x0 <= 1 or r.y0 <= 1 or r.x1 >= P.W - 1 or r.y1 >= P.H - 1
    rooms = [i for i, (r, k) in enumerate(pieces) if k in ("room", "corridor") and r.w * r.h <= 40]
    rnd.shuffle(rooms)
    rooms.sort(key=lambda i: (not on_edge(pieces[i][0]), rnd.random()))
    rock = set(rooms[: max(1, len(pieces) // 7)])
    for i, (r, k) in enumerate(pieces):
        sp = Space(len(P.spaces), k, r, solid=i in rock)
        P.spaces.append(sp)
        if not sp.solid:
            for c in r.cells():
                P.owner[c] = sp.id


def neighbours(P: Plan):
    """Pairs of spaces that share a wall: (a, b) -> runs of wall cells (each run straight and contiguous) a door
    could take. A wall cell joins the two spaces on its opposite sides."""
    found = {}
    for x in range(0, P.W + 1):
        for y in range(0, P.H + 1):
            c = (x, y)
            if c in P.owner:
                continue
            for (dx, dy), orient in (((1, 0), "x"), ((0, 1), "y")):
                o1, o2 = P.owner.get((x - dx, y - dy)), P.owner.get((x + dx, y + dy))
                if o1 is None or o2 is None or o1 == o2:
                    continue
                key = (min(o1, o2), max(o1, o2))
                found.setdefault((key, orient), []).append(c)
    out = {}
    for (key, orient), cells in found.items():
        # split into straight contiguous runs along the wall
        axis = 1 if orient == "x" else 0
        cells.sort(key=lambda c: (c[1 - axis], c[axis]))
        run = [cells[0]]
        for c in cells[1:]:
            p_ = run[-1]
            if c[1 - axis] == p_[1 - axis] and c[axis] == p_[axis] + 1:
                run.append(c)
            else:
                out.setdefault(key, []).append(run)
                run = [c]
        out.setdefault(key, []).append(run)
    return {k: max(v, key=len) for k, v in out.items()}


def merge_pieces(P: Plan, rnd: random.Random) -> None:
    """Some neighbours become one space: the wall between them opens along their shared run (but its two ends),
    making L, T and U shapes - a corridor that turns, a room with a bay, a hall with a wing."""
    merges = 0
    want = max(2, len([s for s in P.spaces if not s.solid]) // 5)
    for _ in range(40):
        if merges >= want:
            break
        nb = neighbours(P)
        pairs = [(k, run) for k, run in nb.items() if len(run) >= 3]
        if not pairs:
            break
        (a, b), run = rnd.choice(pairs)
        sa, sb = P.spaces[a], P.spaces[b]
        if sa.solid or sb.solid or sa.area() + sb.area() > 150:
            continue
        kinds = {sa.kind, sb.kind}
        if kinds == {"hall"}:
            continue
        keep, gone = (sa, sb) if sa.area() >= sb.area() else (sb, sa)
        opening = run[1:-1] if len(run) >= 4 else run
        for c in list(gone.cells()) + opening:
            keep.extra.append(c)
            P.owner[c] = keep.id
        gone.solid = True
        gone.merged_into = keep.id
        if keep.kind == "corridor" and gone.kind != "corridor":
            keep.kind = gone.kind
        if keep.area() >= 70 and keep.kind == "room":
            keep.kind = "hall"
        merges += 1


CORRIDOR_W = 2              # a corridor piece's width in cells (128 u; people's corridors 128..192)


def corridor_pieces(P: Plan, rnd: random.Random) -> None:
    """Brief 20 D5's corridors, done in brief 21: people's 40 % of corridor floor comes from real corridors - pieces
    two cells wide between the halls, with a turn - and ours from the narrow ends of rooms (26..30 %; the styled duel
    of 05.11 failed the band at 24.9 %). Some rooms become an L (two of their sides, CORRIDOR_W wide, meeting at a
    corner) or, when long, a U (three sides): the rest of the room is rock, the corridor keeps the room's walls with
    its neighbours, so the doors the routes give it lead round the turn. The share is asked by the openness (corridors
    0.40 by default) - the conversions are as many as bring the plan's narrow floor up to it, a room at a time."""
    want = float((P.params.get("openness") or (0.40, 0.50, 0.10))[0])
    live = [s for s in P.spaces if not s.solid]
    total = sum(s.area() for s in live) or 1
    narrow = sum(s.area() for s in live if s.kind == "corridor") + 0.35 * sum(s.area() for s in live if s.kind == "room")
    cands = [s for s in live if s.kind == "room" and not s.extra and 4 <= min(s.rect.w, s.rect.h)
             and max(s.rect.w, s.rect.h) <= 10 and s.area() <= 60]
    rnd.shuffle(cands)
    turns = 0
    for s in cands:
        # one piece with a turn at least whenever corridors are asked at all (a plan of narrow room ends already at
        # the share has no real corridor); then as many as the share asks
        if (turns >= 1 or want < 0.25) and narrow / total >= want * 0.85:
            break
        r = s.rect
        corner = rnd.choice(("sw", "se", "nw", "ne"))
        u_shape = max(r.w, r.h) >= 7 and min(r.w, r.h) >= 5 and rnd.random() < 0.35
        cw = CORRIDOR_W
        xs = range(r.x0, r.x0 + cw) if corner in ("sw", "nw") else range(r.x1 - cw, r.x1)
        ys = range(r.y0, r.y0 + cw) if corner in ("sw", "se") else range(r.y1 - cw, r.y1)
        keep = {(x, y) for x in xs for y in range(r.y0, r.y1)} | {(x, y) for x in range(r.x0, r.x1) for y in ys}
        if u_shape:
            # the third side: opposite the first arm along the longer axis
            if r.w >= r.h:
                xs2 = range(r.x1 - cw, r.x1) if corner in ("sw", "nw") else range(r.x0, r.x0 + cw)
                keep |= {(x, y) for x in xs2 for y in range(r.y0, r.y1)}
            else:
                ys2 = range(r.y1 - cw, r.y1) if corner in ("sw", "se") else range(r.y0, r.y0 + cw)
                keep |= {(x, y) for x in range(r.x0, r.x1) for y in ys2}
        rock = [c for c in r.cells() if c not in keep]
        if len(rock) < 4:
            continue
        # the first arm is the space's rectangle, the rest its extra cells (an L or a U as merge_pieces makes them)
        arm = Rect(min(xs), r.y0, max(xs) + 1, r.y1)
        s.rect = arm
        s.extra = sorted(c for c in keep if not arm.has(c))
        for c in rock:
            P.owner.pop(c, None)
        s.kind = "corridor"
        s.turned = "U" if u_shape else "L"
        narrow += s.area() * 0.65 - len(rock) * 0.35
        total -= len(rock)
        turns += 1
    P.metrics["corridor_turns"] = turns


def bridges(nodes, links) -> list:
    """The links whose loss cuts the graph in two: [(link, the smaller side's nodes)]. `links` are (a, b, key)."""
    out = []
    for k, (a, b, key) in enumerate(links):
        adj = {n: [] for n in nodes}
        for j, (x, y, _k) in enumerate(links):
            if j != k and x in adj and y in adj:
                adj[x].append(y)
                adj[y].append(x)
        seen, todo = {a}, [a]
        while todo:
            n = todo.pop()
            for m_ in adj[n]:
                if m_ not in seen:
                    seen.add(m_)
                    todo.append(m_)
        if b not in seen:
            other = set(nodes) - seen
            out.append(((a, b, key), seen if len(seen) <= len(other) else other))
    return out


# --------------------------------------------------------------------------------------------- 2. the routes
def connect(P: Plan, rnd: random.Random) -> None:
    """A spanning tree over the shared walls, then loops: most places get two ways out."""
    nb = neighbours(P)
    live = [s.id for s in P.spaces if not s.solid]
    if not live:
        P.failed = "no spaces"
        return
    # two halves (brief 19 §6, «две половины карты»; TDM's two bases): the footprint cut across its longer side,
    # every space on the side of its middle; the routes across are at most two (the chokepoints)
    halves = P.params.get("shape") == "halves"
    if halves:
        along_x = P.W >= P.H
        for s in P.spaces:
            if s.solid:
                continue
            m = (s.rect.x0 + s.rect.x1) / 2 if along_x else (s.rect.y0 + s.rect.y1) / 2
            P.half[s.id] = 0 if m < (P.W if along_x else P.H) / 2 else 1
    edges = []
    for (a, b), cells in nb.items():
        if len(cells) < 2 or P.spaces[a].solid or P.spaces[b].solid:
            continue
        sa, sb = P.spaces[a], P.spaces[b]
        # corridors and halls are the arteries: prefer them in the tree
        w = rnd.random() + (0 if "corridor" in (sa.kind, sb.kind) else 0.4) + (0 if "hall" in (sa.kind, sb.kind) else 0.2)
        if halves and P.half.get(a) != P.half.get(b):
            w += 5.0          # the tree crosses once, at its cheapest crossing
        edges.append((w, a, b, cells))
    edges.sort()
    parent = {i: i for i in live}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    chosen, rest = [], []
    for e in edges:
        ra, rb = find(e[1]), find(e[2])
        if ra != rb:
            parent[ra] = rb
            chosen.append(e)
        else:
            rest.append(e)
    roots = {find(i) for i in live}
    if len(roots) > 1:
        # pieces the walls left unreachable become rock
        main = max(roots, key=lambda r: sum(1 for i in live if find(i) == r))
        for i in live:
            if find(i) != main:
                P.spaces[i].solid = True
                for c in P.spaces[i].cells():
                    P.owner.pop(c, None)
        chosen = [e for e in chosen if not P.spaces[e[1]].solid and not P.spaces[e[2]].solid]
        rest = [e for e in rest if not P.spaces[e[1]].solid and not P.spaces[e[2]].solid]
    deg = {i: 0 for i in live}
    for _, a, b, _ in chosen:
        deg[a] += 1
        deg[b] += 1
    # loops: give single-door places a second way first, then a share of the rest
    rnd.shuffle(rest)
    rest.sort(key=lambda e: min(deg.get(e[1], 9), deg.get(e[2], 9)))
    # a ring (every major on a loop) takes most of the loops there are
    want_loops = int(len(rest) * (0.8 if P.params.get("shape") == "ring" else 0.45)) + 1
    crossing = sum(1 for e in chosen if halves and P.half.get(e[1]) != P.half.get(e[2]))
    n_tree = len(chosen)
    # the mechanics that need a room with one way in (a dead end under a drop, a ledge only a lift reaches) keep a
    # leaf of the tree each out of the loops
    mech = set(P.params.get("mechanics") or [])
    need = sum(1 for m_ in ("dead_end_stack", "lift_exposure") if m_ in mech)
    leaves = [i for i in live if deg.get(i, 0) == 1 and P.spaces[i].kind != "corridor" and not P.spaces[i].solid]
    rnd.shuffle(leaves)
    keep_leaf = set(leaves[:need])
    for e in rest:
        if want_loops <= 0:
            break
        if e[1] in keep_leaf or e[2] in keep_leaf:
            continue
        if deg.get(e[1], 0) >= 4 and deg.get(e[2], 0) >= 4:
            continue
        if halves and P.half.get(e[1]) != P.half.get(e[2]):
            if crossing >= 2:
                continue
            crossing += 1
        chosen.append(e)
        deg[e[1]] = deg.get(e[1], 0) + 1
        deg[e[2]] = deg.get(e[2], 0) + 1
        want_loops -= 1
    # brief 21 D2, the PO 05.11 («из неё нет выхода кроме как входа … скучная до невозможности»): no space keeps one
    # doorway unless a mechanic asked for it - a second wall to a neighbour opens, or the space is left rock
    pairs = {(min(e[1], e[2]), max(e[1], e[2])) for e in chosen}
    changed = True
    while changed:
        changed = False
        for i in live:
            sp = P.spaces[i]
            if sp.solid or i in keep_leaf or deg.get(i, 0) >= 2:
                continue
            opts = [e for e in rest if i in (e[1], e[2]) and (min(e[1], e[2]), max(e[1], e[2])) not in pairs
                    and not P.spaces[e[1]].solid and not P.spaces[e[2]].solid]
            opts.sort(key=lambda e: (halves and P.half.get(e[1]) != P.half.get(e[2]), e[0]))
            pick = None
            for e in opts:
                if halves and P.half.get(e[1]) != P.half.get(e[2]):
                    if crossing >= 2:
                        continue
                    crossing += 1
                pick = e
                break
            if pick:
                chosen.append(pick)
                pairs.add((min(pick[1], pick[2]), max(pick[1], pick[2])))
                deg[pick[1]] = deg.get(pick[1], 0) + 1
                deg[pick[2]] = deg.get(pick[2], 0) + 1
                changed = True
                continue
            if deg.get(i, 0) == 0 and len([j for j in live if not P.spaces[j].solid]) <= 1:
                continue
            # no second wall to open: the space joins its one neighbour as a bay - the wall between them opens along
            # their whole run, as merge_pieces makes an L or a T (turned to rock it shrank the duel from 10 spaces
            # to 6 and every half lost its rooms)
            mine = [e for e in chosen if i in (e[1], e[2])]
            span_ok = False
            if len(mine) == 1:
                e = mine[0]
                nid_ = e[2] if e[1] == i else e[1]
                cells_ = list(P.spaces[nid_].cells()) + list(sp.cells())
                xs_, ys_ = [c[0] for c in cells_], [c[1] for c in cells_]
                # ... unless the bay makes the space longer than a hall may be: a duel hall of 10 cells holds no sight
                # line across itself, a bay made it 20 (24 of 88 plan lines on 30 duel plans ran inside one hall)
                lim = (10 if P.params.get("class") == "duel" else 14) + 2
                span_ok = max(xs_) - min(xs_) + 1 <= lim and max(ys_) - min(ys_) + 1 <= lim
            if len(mine) == 1 and span_ok:
                e = mine[0]
                nid = e[2] if e[1] == i else e[1]
                N = P.spaces[nid]
                run = e[3]
                opening = run[1:-1] if len(run) >= 4 else run
                for c in list(sp.cells()) + list(opening):
                    if c not in N.extra:
                        N.extra.append(c)
                    P.owner[c] = nid
                sp.solid = True
                sp.merged_into = nid
                if N.kind == "corridor" and sp.kind != "corridor":
                    N.kind = sp.kind
                if N.kind == "room" and N.area() >= 70:
                    N.kind = "hall"
                chosen.remove(e)
                for j in (e[1], e[2]):
                    deg[j] = deg.get(j, 0) - 1
                deg[nid] = deg.get(nid, 0)
                P.metrics["leaves_as_bays"] = int(P.metrics.get("leaves_as_bays") or 0) + 1
                changed = True
                continue
            sp.solid = True
            for c in sp.cells():
                P.owner.pop(c, None)
            for e in mine:
                chosen.remove(e)
                if halves and P.half.get(e[1]) != P.half.get(e[2]):
                    crossing -= 1
                for j in (e[1], e[2]):
                    deg[j] = deg.get(j, 0) - 1
            changed = True
    # ... nor a group of spaces hanging off the rest by one doorway (brief 21 D2 on the map's walk: three of the 3.43
    # duel's doorways each cut a room's worth of floor off) - a loop from the group to the rest
    for _ in range(12):
        nodes_ = [j for j in live if not P.spaces[j].solid]
        found_ = [(lk, side) for lk, side in bridges(nodes_, [(e[1], e[2], k) for k, e in enumerate(chosen)])
                  if not (side & keep_leaf)]
        if not found_:
            break
        added = False
        for (_a, _b, _k), side in found_:
            opts = [e for e in rest if (e[1] in side) != (e[2] in side)
                    and (min(e[1], e[2]), max(e[1], e[2])) not in pairs
                    and not P.spaces[e[1]].solid and not P.spaces[e[2]].solid]
            opts.sort(key=lambda e: (halves and P.half.get(e[1]) != P.half.get(e[2]), e[0]))
            for e in opts:
                if halves and P.half.get(e[1]) != P.half.get(e[2]):
                    if crossing >= 2:
                        continue
                    crossing += 1
                chosen.append(e)
                pairs.add((min(e[1], e[2]), max(e[1], e[2])))
                deg[e[1]] = deg.get(e[1], 0) + 1
                deg[e[2]] = deg.get(e[2], 0) + 1
                added = True
                break
            if added:
                break
        if not added:
            break
    n_tree = min(n_tree, len(chosen))
    P.metrics["half_crossings"] = crossing if halves else None
    placed_ = {}                     # space -> the doorways' cells it has so far
    for k_, (_, a, b, cells) in enumerate(chosen):
        cells = sorted(cells)
        sa, sb = P.spaces[a], P.spaces[b]
        width = 3 if ("hall" in (sa.kind, sb.kind) and len(cells) >= 6 and rnd.random() < 0.5) else 2
        width = min(width, len(cells) - (1 if len(cells) > 3 else 0))
        # keep a door off the very corner of a room
        lo = 1 if len(cells) - width >= 2 else 0
        hi = len(cells) - width - lo
        # brief 21 D3: doorways off each other's axis - a doorway facing another across a room is a sight line
        # through both (the 3.43 maps: 64 of 67 duel plans over the asked lines once the columns were capped);
        # people offset them. The start whose cells line up least with the two spaces' other doorways, then random
        along_x = len({c[1] for c in cells}) == 1

        def aligned(st):
            mine = cells[st:st + width]
            u = [c[0] if along_x else c[1] for c in mine]
            n = 0
            for sid in (a, b):
                for dc in placed_.get(sid, []):
                    for c in dc:
                        if (c[0] if along_x else c[1]) in u and (c[1] if along_x else c[0]) != (mine[0][1] if along_x else mine[0][0]):
                            n += 1
            return n
        starts = list(range(lo, max(lo, hi) + 1))
        rnd.shuffle(starts)
        start = min(starts, key=aligned)
        dcells = cells[start:start + width]
        placed_.setdefault(a, []).append(dcells)
        placed_.setdefault(b, []).append(dcells)
        P.doors.append(Door(a, b, dcells, loop=k_ >= n_tree))


# --------------------------------------------------------------------------------------------- 3. the heights
PATTERNS = ["flat", "balcony", "platform", "split", "pit", "tiers"]


def heights(P: Plan, rnd: random.Random) -> None:
    """Floor levels by the routes; terraces inside halls; ceilings; sky courts."""
    q = P.params
    nlev = max(2, int(q["levels"]))
    top_level = 64 * (nlev - 1) + (64 if nlev >= 4 else 0)
    if q.get("vertical_span"):
        # the span asked is the floors' p5..p95: the routes' top level under it by a terrace's rise
        top_level = max(64, (int(q["vertical_span"]) - 128) // 64 * 64)
    live = [s for s in P.spaces if not s.solid]
    adj = {s.id: [] for s in live}
    for d in P.doors:
        adj[d.a].append(d.b)
        adj[d.b].append(d.a)
    # the atrium: the hall nearest the middle - tall, under the sky, balconies round it, the others look into it
    cx, cy = P.W / 2, P.H / 2
    halls = [s for s in live if s.kind == "hall"] or live
    atrium = min(halls, key=lambda s: math.hypot((s.rect.x0 + s.rect.x1) / 2 - cx, (s.rect.y0 + s.rect.y1) / 2 - cy)
                 - 0.15 * s.area() ** 0.5)
    atrium.atrium = True
    # start from it, BFS: a door changes level by a step that a flight in the next room can take
    start = atrium.id
    lvl = {start: 0}
    order = [start]
    seen = {start}
    while order:
        cur = order.pop(0)
        for o in adj[cur]:
            if o in seen:
                continue
            seen.add(o)
            so = P.spaces[o]
            if so.kind == "corridor":
                step = rnd.choice((0, 64, 64, 128, -64))
            else:
                step = rnd.choice((0, 0, 64, 128, -64, 192))
            lvl[o] = max(0, min(top_level, lvl[cur] + step))
            order.append(o)
    for s in live:
        s.base = lvl.get(s.id, 0)
    # halls and some rooms get a terrace pattern; the liquids and chasms asked take sunken middles first - as many
    # halls (then big rooms) as the share asked needs, the biggest first
    wet = float(q.get("water") or 0) + float(q.get("lava") or 0) + float(q.get("slime") or 0)
    need = wet * sum(s.area() for s in live) * 1.25
    wet_halls = set()
    n_pits = int(q.get("pits") or 0)
    # every liquid asked gets a hall of its own at least (04.11: lava 10 % took every pool, the 5 % of water got none)
    n_kinds = sum(1 for k in ("water", "lava", "slime") if float(q.get(k) or 0) > 0)
    # the PO 12.11: a prize under water asks a pool though no water is asked; «levels» asks pools on three floors
    deep_w = water_deep(q)
    wants_w = float(q.get("water") or 0) > 0 or (deep_w and int(q.get("underwater") or 0) > 0)
    if deep_w and wants_w and not float(q.get("water") or 0) > 0:
        n_kinds += 1
    if deep_w and wants_w and q.get("water_body") == "levels":
        n_kinds += 2
    order_ = sorted(live, key=lambda s: -s.area())
    if deep_w and wants_w and q.get("water_body") == "levels":
        # a hall of each floor first: a pool a floor
        seen_, first_, rest_ = set(), [], []
        for s in order_:
            if not (s.atrium or s.kind == "corridor" or min(s.rect.w, s.rect.h) < 6) and s.base not in seen_:
                seen_.add(s.base)
                first_.append(s)
            else:
                rest_.append(s)
        order_ = first_ + rest_
    for s in order_:
        if need <= 0 and n_pits <= 0 and len(wet_halls) >= n_kinds + int(q.get("pits") or 0):
            break
        if s.atrium or s.kind == "corridor" or min(s.rect.w, s.rect.h) < 6:
            continue
        wet_halls.add(s.id)
        # the walkway round the pit chosen so the pit holds what is still wanted (a chasm: the widest pit)
        if n_pits > 0 or (deep_w and wants_w and need <= 0):
            s.rim = 1           # a deep pool: as big as a third of its hall lets it (the pit's cap)
        else:
            s.rim = min((1, 2, 3), key=lambda rr: abs(max(0, s.rect.w - 2 * rr) * max(0, s.rect.h - 2 * rr) - need)
                        if min(s.rect.w, s.rect.h) - 2 * rr >= 2 else 1e9)
        need -= max(0, s.rect.w - 2 * s.rim) * max(0, s.rect.h - 2 * s.rim)
        n_pits -= 1
    for s in live:
        if s.id in wet_halls:
            s.wet = True
            # a deep pool whole (a bridge would cut it in two)
            s.pattern = rnd.choice(["pit", "bridge"]) if min(s.rect.w, s.rect.h) >= 7 and not deep_pools_only(q) else "pit"
            terrace(s, rnd, q)
            continue
        if s.atrium:
            s.pattern = rnd.choice(["balcony_u", "balcony_l", "bridge", "balcony_l"])
        elif s.kind == "hall":
            wet = float(q.get("water") or 0) + float(q.get("lava") or 0) + float(q.get("slime") or 0)
            if (wet > 0 or q.get("pits")) and rnd.random() < min(0.92, 0.25 + 6 * wet + 0.3 * int(q.get("pits") or 0)):
                s.pattern = rnd.choice(["pit", "bridge", "bridge"])
            else:
                # brief 21 D4 (the PO 08.10 and 05.11: «башенки … из уровня в уровень - это же бред»): no mound in a
                # hall's middle - a terrace stands against a wall or sinks
                s.pattern = rnd.choice(["balcony", "balcony_l", "split", "bridge", "pit", "tiers", "balcony", "split"])
        elif s.kind == "room" and min(s.rect.w, s.rect.h) >= 5 and rnd.random() < 0.4:
            s.pattern = rnd.choice(["split", "balcony", "split"])
        else:
            s.pattern = "flat"
        terrace(s, rnd, q)
    # sky courts: the largest halls first, until the share asked of the floor is under sky
    total = sum(s.area() for s in live)
    want = q["sky"] * total
    got = 0
    for s in sorted(live, key=lambda s: (not s.atrium, -s.area())):
        if got >= want * 0.9:
            break
        if s.kind in ("hall", "room") and s.area() >= 30 and got + s.area() <= want + 0.08 * total:
            s.sky = True
            got += s.area()


def flight_up(s: Space, top_cell, d, n: int, z_hi: int, need_flat_at=None) -> bool:
    """A flight of n stair cells ending at `top_cell`, rising along d (d points from the flight to the upper floor),
    its top edge at z_hi. The cells must be plain floor of the space (at `need_flat_at` when given)."""
    cells = [(top_cell[0] - d[0] * k, top_cell[1] - d[1] * k) for k in range(n)]
    for c in cells:
        f = s.floor.get(c)
        if f is None or f[1] != "flat" or (need_flat_at is not None and f[0] != need_flat_at):
            return False
    # the cell below the flight's foot must be floor at the low level, to step on from
    foot = (cells[-1][0] - d[0], cells[-1][1] - d[1])
    if foot not in s.floor or s.floor[foot][1] != "flat" or s.floor[foot][0] != z_hi - RISE_PER_CELL * n:
        return False
    for k, c in enumerate(cells):
        s.floor[c] = (z_hi - RISE_PER_CELL * (k + 1), "stair", d[0], d[1])
    return True


def terrace(s: Space, rnd: random.Random, q: dict) -> None:
    """Fill s.floor: every cell of the space with its floor, the pattern's terraces joined by flights of steps.

    The patterns (in a hall; rooms get the smaller ones): a balcony along one wall, an L of balconies on two walls,
    a U on three; a split level; tiers; a pit, with a bridge across it or steps into it; a platform (rare - a mound
    in the middle with an item on top is the pattern the PO named as boring, 08.10)."""
    r = s.rect
    for c in s.cells():
        s.floor[c] = (s.base, "flat", 0, 0)
    w, h = r.w, r.h
    if s.pattern == "flat" or min(w, h) < 4:
        s.pattern = "flat"
        return
    base = s.base

    def band(side, depth, z):
        """The cells of a band `depth` deep along one wall of the main rectangle."""
        if side == "s":
            cells = [(x, y) for x in range(r.x0, r.x1) for y in range(r.y0, r.y0 + depth)]
            inward = (0, 1)
        elif side == "n":
            cells = [(x, y) for x in range(r.x0, r.x1) for y in range(r.y1 - depth, r.y1)]
            inward = (0, -1)
        elif side == "w":
            cells = [(x, y) for x in range(r.x0, r.x0 + depth) for y in range(r.y0, r.y1)]
            inward = (1, 0)
        else:
            cells = [(x, y) for x in range(r.x1 - depth, r.x1) for y in range(r.y0, r.y1)]
            inward = (-1, 0)
        for c in cells:
            s.floor[c] = (z, "flat", 0, 0)
        return cells, inward

    def stairs_to_band(cells, inward, z_hi, width=2):
        """A flight up to a band from the floor in front of it, perpendicular to the band, `width` wide."""
        n = (z_hi - base) // RISE_PER_CELL
        edge = [c for c in cells if (c[0] + inward[0], c[1] + inward[1]) in s.floor
                and s.floor[(c[0] + inward[0], c[1] + inward[1])][0] == base]
        rnd.shuffle(edge)
        for c in edge:
            top = (c[0] + inward[0], c[1] + inward[1])
            d = (-inward[0], -inward[1])
            side = (inward[1], inward[0])
            tops = [(top[0] + side[0] * k, top[1] + side[1] * k) for k in range(width)]
            if all(flight_ok(s, t, d, n, z_hi, base) for t in tops):
                for t in tops:
                    flight_up(s, t, d, n, z_hi, base)
                return True
        return False

    up = rnd.choice((128, 128, 192)) if s.kind == "hall" else 64
    sides = ["s", "n", "w", "e"]
    rnd.shuffle(sides)
    if s.pattern in ("balcony", "balcony_l", "balcony_u"):
        nwalls = {"balcony": 1, "balcony_l": 2, "balcony_u": 3}[s.pattern]
        depth = 2 if min(w, h) < 10 else 3
        chosen = []
        if nwalls == 2:
            a = sides[0]
            b_ = next(x for x in sides[1:] if {a, x} not in ({"s", "n"}, {"w", "e"}))
            chosen = [a, b_]
        elif nwalls == 3:
            gone = sides[0]
            chosen = [x for x in ("s", "n", "w", "e") if x != gone]
        else:
            chosen = [sides[0]]
        z_hi = base + up
        bands = [band(sd, depth, z_hi) for sd in chosen]
        ok = False
        for cells, inward in bands:
            if stairs_to_band(cells, inward, z_hi):
                ok = True
                break
        if not ok:
            for c in s.cells():
                s.floor[c] = (base, "flat", 0, 0)
            s.pattern = "flat"
    elif s.pattern == "split":
        along_x = w >= h
        z_hi = base + 64
        if along_x:
            cut = r.x0 + w // 2
            hi_cells = [(x, y) for x in range(cut, r.x1) for y in range(r.y0, r.y1)]
            d = (1, 0)
            tops = [(cut - 1, y) for y in range(r.y0 + 1, r.y1 - 1)]
        else:
            cut = r.y0 + h // 2
            hi_cells = [(x, y) for y in range(cut, r.y1) for x in range(r.x0, r.x1)]
            d = (0, 1)
            tops = [(x, cut - 1) for x in range(r.x0 + 1, r.x1 - 1)]
        for c in hi_cells:
            s.floor[c] = (z_hi, "flat", 0, 0)
        rnd.shuffle(tops)
        made = 0
        for t in tops:
            if made >= 2:
                break
            if flight_ok(s, t, d, 2, z_hi, base) and flight_ok(s, (t[0] + d[1], t[1] + d[0]), d, 2, z_hi, base):
                flight_up(s, t, d, 2, z_hi, base)
                flight_up(s, (t[0] + d[1], t[1] + d[0]), d, 2, z_hi, base)
                made += 1
        if not made:
            for c in s.cells():
                s.floor[c] = (base, "flat", 0, 0)
            s.pattern = "flat"
    elif s.pattern in ("pit", "bridge"):
        # the sunken middle; a bridge crosses it at the floor's level, or steps lead down into it
        rim = s.rim if s.wet else 2
        pw, ph = max(2, w - 2 * rim), max(2, h - 2 * rim)
        px, py = r.x0 + rim, r.y0 + rim
        if s.wet:
            # brief 20 D4: a pool takes a third of its hall at most (the 3.40 FFA-8's rocket hall: two pools, half
            # the floor) - the rest of the hall stays a floor to fight on
            share = POOL_SHARE if deep_pools_only(q) else 1 / 3
            while pw * ph > (w * h) * share and max(pw, ph) > 2:
                if pw >= ph:
                    pw -= 1
                    px += pw % 2
                else:
                    ph -= 1
                    py += ph % 2
        down = 64
        pit = [(x, y) for x in range(px, px + pw) for y in range(py, py + ph)]
        if s.wet and pw >= 4 and ph >= 3 and not deep_pools_only(q):
            # and not a plain rectangle: one corner of it stays floor (an L), on a side the seed picks
            cx_ = px if rnd.random() < 0.5 else px + pw - 2
            cy_ = py if rnd.random() < 0.5 else py + ph - 1
            notch = {(cx_, cy_), (cx_ + 1, cy_)}
            pit = [c for c in pit if c not in notch]
        for c in pit:
            s.floor[c] = (base - down, "flat", 0, 0)
        if s.pattern == "bridge" and min(pw, ph) >= 3:
            if pw >= ph:
                mid = py + ph // 2
                for x in range(px, px + pw):
                    for y in (mid - 1, mid):
                        s.floor[(x, y)] = (base, "flat", 0, 0)
            else:
                mid = px + pw // 2
                for y in range(py, py + ph):
                    for x in (mid - 1, mid):
                        s.floor[(x, y)] = (base, "flat", 0, 0)
        # steps out of EVERY part of the pit - a bridge splits it in two, and a part with no steps is a trap (04.11:
        # mg_new_ffa8, five cells 64 deep one could fall into and never leave); a part no flight fits is filled back
        sunk = {c for c in pit if s.floor[c][0] == base - down}
        parts = []
        while sunk:
            part, todo = set(), [sunk.pop()]
            while todo:
                c = todo.pop()
                part.add(c)
                for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n_ = (c[0] + d[0], c[1] + d[1])
                    if n_ in sunk:
                        sunk.discard(n_)
                        todo.append(n_)
            parts.append(part)
        made = 0
        for part in sorted(parts, key=min):
            cand = []
            for c in part:
                for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nb_ = (c[0] + d[0], c[1] + d[1])
                    if nb_ in s.floor and s.floor[nb_][0] == base and s.floor[nb_][1] == "flat":
                        cand.append((c, d))
            cand.sort()
            rnd.shuffle(cand)
            out_ = 0
            for c, d in cand:
                if out_ >= (2 if len(part) >= 12 else 1):
                    break
                # the top stair cell is the pit cell at the rim, the flight goes back into the pit
                if flight_ok(s, c, d, 2, base, base - down):
                    flight_up(s, c, d, 2, base, base - down)
                    out_ += 1
            if not out_:
                for c in part:
                    s.floor[c] = (base, "flat", 0, 0)
            made += out_
        s.pit = [c for c in pit if s.floor[c] == (base - down, "flat", 0, 0)]
        if not made:
            for c in s.cells():
                s.floor[c] = (base, "flat", 0, 0)
            s.pattern = "flat"
            s.pit = []
    elif s.pattern == "tiers":
        along_x = w >= h
        n = 3
        if along_x:
            bw = max(3, w // n)
            for i in range(n):
                for x in range(r.x0 + i * bw, r.x1 if i == n - 1 else r.x0 + (i + 1) * bw):
                    for y in range(r.y0, r.y1):
                        s.floor[(x, y)] = (base + 64 * i, "flat", 0, 0)
            for i in range(1, n):
                ys = list(range(r.y0, r.y1 - 1))
                rnd.shuffle(ys)
                for y in ys:
                    t = (r.x0 + i * bw - 1, y)
                    if flight_ok(s, t, (1, 0), 2, base + 64 * i, base + 64 * (i - 1)) and \
                            flight_ok(s, (t[0], y + 1), (1, 0), 2, base + 64 * i, base + 64 * (i - 1)):
                        flight_up(s, t, (1, 0), 2, base + 64 * i, base + 64 * (i - 1))
                        flight_up(s, (t[0], y + 1), (1, 0), 2, base + 64 * i, base + 64 * (i - 1))
                        break
        else:
            bh = max(3, h // n)
            for i in range(n):
                for y in range(r.y0 + i * bh, r.y1 if i == n - 1 else r.y0 + (i + 1) * bh):
                    for x in range(r.x0, r.x1):
                        s.floor[(x, y)] = (base + 64 * i, "flat", 0, 0)
            for i in range(1, n):
                xs = list(range(r.x0, r.x1 - 1))
                rnd.shuffle(xs)
                for x in xs:
                    t = (x, r.y0 + i * bh - 1)
                    if flight_ok(s, t, (0, 1), 2, base + 64 * i, base + 64 * (i - 1)) and \
                            flight_ok(s, (x + 1, t[1]), (0, 1), 2, base + 64 * i, base + 64 * (i - 1)):
                        flight_up(s, t, (0, 1), 2, base + 64 * i, base + 64 * (i - 1))
                        flight_up(s, (x + 1, t[1]), (0, 1), 2, base + 64 * i, base + 64 * (i - 1))
                        break
    elif s.pattern == "platform":
        pw, ph = max(2, w // 3), max(2, h // 3)
        px, py = r.x0 + (w - pw) // 2, r.y0 + (h - ph) // 2
        z_hi = base + 64
        top = [(x, y) for x in range(px, px + pw) for y in range(py, py + ph)]
        for c in top:
            s.floor[c] = (z_hi, "flat", 0, 0)
        d = rnd.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        edge = [c for c in top if (c[0] - d[0], c[1] - d[1]) not in top]
        made = False
        for c in edge:
            t = (c[0] - d[0], c[1] - d[1])
            if flight_ok(s, t, d, 2, z_hi, base):
                flight_up(s, t, d, 2, z_hi, base)
                made = True
                break
        if not made:
            for c in s.cells():
                s.floor[c] = (base, "flat", 0, 0)
            s.pattern = "flat"


def flight_ok(s: Space, top_cell, d, n: int, z_hi: int, z_lo: int) -> bool:
    cells = [(top_cell[0] - d[0] * k, top_cell[1] - d[1] * k) for k in range(n)]
    for c in cells:
        f = s.floor.get(c)
        if f is None or f[1] != "flat" or f[0] != z_lo:
            return False
    foot = (cells[-1][0] - d[0], cells[-1][1] - d[1])
    f = s.floor.get(foot)
    return f is not None and f[1] == "flat" and f[0] == z_lo and z_hi - z_lo == RISE_PER_CELL * n


def floor_top(f) -> int:
    """The highest standing height of a floor cell (a stair cell's upper step)."""
    z, kind, _, _ = f
    return z + RISE_PER_CELL if kind == "stair" else z


def realise(P: Plan, rnd: random.Random) -> None:
    """Door heights and the flights they need; ceilings.

    A rise of n x 32 between the two sides is one flight of n stair cells, each rising 32 toward the high side; the
    door cell is one of them. The other n-1 lie inside the low space (climbing to the door, case A) or inside the high
    space (sunk into it from the door, case B) - wherever the floor there is plain at the side's height."""
    lifts_left = int(P.params.get("lifts") or 0)
    shape_leaves(P, rnd)
    lifts_left -= sum(1 for d in P.doors if d.kind == "lift")
    rises = []
    # brief 24 D3 (06.11): a door by its place in the plan, never by `id(d)` - equal rises were ordered by the objects'
    # memory addresses, so the same request and number made another map in another process (or after other plans in
    # the same one): 3 of 12 plans differed between two runs of one request (tools/check_mapgen_scratch_parallel.py)
    for i, d in enumerate(P.doors):
        sa, sb = P.spaces[d.a], P.spaces[d.b]
        rises.append((abs(door_side_floor(P, d, sa) - door_side_floor(P, d, sb)), i))
    lift_first = {k for r_, k in sorted(rises, reverse=True)[:lifts_left * 3] if r_ >= 128}
    ladders_left = int(P.params.get("ladders") or 0)
    ladder_first = [k for r_, k in sorted(rises, reverse=True) if 96 <= r_ <= 320 and k not in lift_first]
    ladder_first = set(ladder_first[:ladders_left * 3])
    drops_left = int(P.params.get("drops") or 0) if not P.params.get("drops_default") else 0
    for i, d in enumerate(P.doors):
        if d.rj or d.kind == "lift":
            continue            # shaped by shape_leaves
        sa, sb = P.spaces[d.a], P.spaces[d.b]
        za, zb = door_side_floor(P, d, sa), door_side_floor(P, d, sb)
        d.za, d.zb = za, zb
        if za == zb:
            d.z = za
            continue
        if i in lift_first and lifts_left > 0:
            low, high = (sa, sb) if za < zb else (sb, sa)
            if lift_in(P, d, low, min(za, zb), max(za, zb)):
                lifts_left -= 1
                continue
        if i in ladder_first and ladders_left > 0:
            low, high = (sa, sb) if za < zb else (sb, sa)
            if ladder_in(P, d, low, min(za, zb), max(za, zb)):
                ladders_left -= 1
                continue
        if drops_left > 0 and d.loop and 64 <= abs(za - zb) <= 192:
            d.kind, d.z = "drop", max(za, zb)
            drops_left -= 1
            continue
        low, high = (sa, sb) if za < zb else (sb, sa)
        zl, zh = min(za, zb), max(za, zb)
        rise = zh - zl
        n = -(-rise // RISE_PER_CELL)
        up = door_dir(P, d, low, high)
        if rise % RISE_PER_CELL:
            # an odd rise: the low side's cells by the door are lifted to make it a whole number of steps
            zl = zh - n * RISE_PER_CELL
        if n == 1:
            d.z, d.stair = zl, up
            continue
        if flight_in(P, d, low, n - 1, zl, up, sunk=False):
            d.z, d.stair = zh - RISE_PER_CELL, up
            continue
        if flight_in(P, d, high, n - 1, zl, up, sunk=True):
            d.z, d.stair = zl, up
            continue
        # neither side has room for the flight: a lift when lifts are left, else a drop (one way) when the high side
        # is at most 192 over the low
        if lifts_left > 0 and rise >= 128 and lift_in(P, d, low, zl, zh):
            lifts_left -= 1
            continue
        if ladders_left > 0 and 96 <= rise <= 320 and ladder_in(P, d, low, zl, zh):
            ladders_left -= 1
            continue
        if rise <= 192 and d.loop:
            d.kind = "drop"
            d.z = zh
        else:
            # on the tree a one-way drop would trap whoever falls (Fable's review 04.11): the route is given up, the
            # score pays for every cell it leaves out of reach
            d.kind = "none"
    for d in P.doors:
        if d.kind == "none":
            # the flight it may have laid on one side goes back to floor
            for (sp_id, c, f0) in d.laid:
                if c in P.spaces[sp_id].floor:
                    P.spaces[sp_id].floor[c] = f0
    P.doors = [d for d in P.doors if d.kind != "none"]
    prune_dead_ends(P)
    repair_bridges(P)
    repair_traps(P)
    for s in P.spaces:
        if s.solid:
            continue
        top = max(floor_top(f) for f in s.floor.values())
        # headroom over the highest terrace, and over the base floor (people's maps: 160 median, 128..256)
        over_top = {"hall": rnd.choice((160, 176, 192)), "room": rnd.choice((160, 176, 192)),
                    "corridor": 144, "shaft": 160}[s.kind]
        over_base = {"hall": rnd.choice((224, 256, 288)), "room": rnd.choice((160, 176)),
                     "corridor": 144, "shaft": 160}[s.kind]
        if s.atrium:
            over_top, over_base = rnd.choice((192, 224)), rnd.choice((320, 352, 384))
        s.ceil = max(top + over_top, s.base + over_base)
    # a lift's shaft clears its top by a man's height and more
    for (cells, zl, zh, bottom, top) in P.lifts:
        s = P.spaces[P.owner[cells[0]]]
        s.ceil = max(s.ceil, zh + 176)
    # a drop door opens high in the low space's wall: that space's ceiling clears the opening
    for d in P.doors:
        if d.kind in ("drop", "ladder"):
            for sid in (d.a, d.b):
                s = P.spaces[sid]
                s.ceil = max(s.ceil, d.z + DOOR_H + 16)


def exits_of(P: Plan, ways_out: bool = False) -> dict:
    """Brief 21 D2: how many doorways each space has - of every kind (a doorway, a lift, a ladder, a drop, an overlook);
    with `ways_out` only those one can leave by (a drop or an overlook from its high side). A room one drops into and
    walks out of has two doorways: it is on a loop, one way round (the route asymmetry of q2duel5), not a dead end."""
    out = {s.id: 0 for s in P.spaces if not s.solid}
    for d in P.doors:
        if ways_out and d.kind in ("drop", "overlook"):
            hi = d.a if (d.za or 0) >= (d.zb or 0) else d.b
            if hi in out:
                out[hi] += 1
        elif d.kind in ("door", "lift", "ladder", "drop", "overlook"):
            for x in (d.a, d.b):
                if x in out:
                    out[x] += 1
    return out


def add_doorway(P: Plan, sid: int, targets: set | None = None) -> bool:
    """Brief 21 D2: a second doorway for a space the heights left with one - to another neighbour across a wall run
    clear of doorways, level, with two steps in the doorway or a flight laid on either side - both ways (a drop added
    here made rooms one falls into and cannot leave: 12 of 100 duel plans refused for floor with no way back); the
    halves keep their two crossings."""
    nb = neighbours(P)
    paired = {(min(d.a, d.b), max(d.a, d.b)) for d in P.doors}
    taken = {c for d in P.doors for c in d.cells}
    crossings = sum(1 for d in P.doors if P.half and P.half.get(d.a) != P.half.get(d.b))
    s = P.spaces[sid]
    opts = []
    for (a, b), run in nb.items():
        if sid not in (a, b) or (a, b) in paired:
            continue
        o = b if a == sid else a
        O = P.spaces[o]
        if O.solid or len(run) < 2 or (targets is not None and o not in targets):
            continue
        cross = bool(P.half) and P.half.get(sid) != P.half.get(o)
        if cross and crossings >= 2:
            continue
        run = sorted(run)
        for k in range(len(run) - 1):
            cells = run[k:k + 2]
            if set(cells) & taken or any(abs(c[0] - t[0]) + abs(c[1] - t[1]) < 2 for c in cells for t in taken):
                continue
            za, zb = side_floor_at(s, cells), side_floor_at(O, cells)
            if za is None or zb is None:
                continue
            opts.append((abs(za - zb), cross, o, cells, za, zb))
    opts.sort(key=lambda t: (t[1], t[0]))
    for rise, cross, o, cells, za, zb in opts:
        O = P.spaces[o]
        d = Door(sid, o, list(cells), za=za, zb=zb, loop=True)
        lo, hi = (s, O) if za < zb else (O, s)
        zl, zh = min(za, zb), max(za, zb)
        n = -(-rise // RISE_PER_CELL) if rise else 0
        if rise % RISE_PER_CELL:
            continue
        ok = False
        if rise == 0:
            d.z, ok = za, True
        elif n == 1:
            d.z, d.stair, ok = zl, door_dir(P, d, lo, hi), True
        else:
            up = door_dir(P, d, lo, hi)
            if flight_in(P, d, lo, n - 1, zl, up, sunk=False):
                d.z, d.stair, ok = zh - RISE_PER_CELL, up, True
            elif flight_in(P, d, hi, n - 1, zl, up, sunk=True):
                d.z, d.stair, ok = zl, up, True
        if ok:
            P.doors.append(d)
            P.metrics["doorways_added"] = int(P.metrics.get("doorways_added") or 0) + 1
            return True
    return False


def door_bridges(P: Plan) -> list:
    """The doorways (of any kind) whose loss leaves a group of spaces joined to the rest by none (brief 21 D2), the
    asked dead end aside: [(door index, the smaller side)]."""
    nodes = [s.id for s in P.spaces if not s.solid]
    return [(k, side) for (a, b, k), side in bridges(nodes, [(d.a, d.b, k) for k, d in enumerate(P.doors)])
            if not (side & P.asked)]


def repair_bridges(P: Plan) -> None:
    """Brief 21 D2: a group hanging off the rest by one doorway after the heights (a loop's doorway given up for want
    of room for its flight) gets a second doorway to the rest where a wall allows it."""
    for _ in range(8):
        found = door_bridges(P)
        if not found:
            return
        fixed = False
        for k, side in found:
            nodes = {s.id for s in P.spaces if not s.solid}
            for sid in sorted(side):
                if add_doorway(P, sid, targets=nodes - side):
                    fixed = True
                    break
            if fixed:
                break
        if not fixed:
            return


def repair_traps(P: Plan) -> None:
    """Brief 21 D2: a part one drops into and cannot climb out of (a loop's doorway made a drop for want of room for
    its flight) gets a doorway of its own back out - else the plan is refused later for its floor with no way back
    (45 of 100 duel plans on 05.11 once every space had two doorways)."""
    for _ in range(6):
        nodes, edges = plan_graph(P)
        if not nodes:
            return
        big = max((s for s in P.spaces if not s.solid and s.floor), key=lambda s: len(s.floor))
        start = next((c for c in big.floor if c in nodes), None)
        if start is None:
            return
        there = dijkstra(edges, start)
        rev = {}
        for c, es in edges.items():
            for n, w in es:
                rev.setdefault(n, []).append((c, w))
        back = dijkstra(rev, start)
        bad = []
        for s in P.spaces:
            if s.solid or s.id in P.asked:
                continue
            if any(c in nodes and nodes[c][1] == "flat" and (c not in there or c not in back) for c in s.floor):
                bad.append(s.id)
        if not bad:
            return
        fixed = False
        for sid in bad:
            if add_doorway(P, sid):
                fixed = True
                P.metrics["traps_repaired"] = int(P.metrics.get("traps_repaired") or 0) + 1
                break
        if not fixed:
            return


def prune_dead_ends(P: Plan) -> None:
    """Brief 21 D2: after the heights a doorway with no room for its flight is given up and a loop's may become a
    drop one way - a space left with one way out (none asked for it) is turned to rock, its doorways closed and the
    flights, lifts and ladders they had laid taken back. The PO, 05.11: a long room, one doorway, a health at its end."""
    while True:
        ex = exits_of(P)
        out_ = exits_of(P, ways_out=True)
        # one doorway, or no way out at all (a room only dropped into)
        bad = [sid for sid, n in ex.items() if (n < 2 or out_.get(sid, 0) < 1) and sid not in P.asked]
        if not bad:
            return
        sid = bad[0]
        if add_doorway(P, sid):
            continue
        s = P.spaces[sid]
        s.solid = True
        for c in list(s.cells()):
            P.owner.pop(c, None)
        gone = [d for d in P.doors if sid in (d.a, d.b)]
        for d in gone:
            for (sp_id, c, f0) in d.laid:
                sp = P.spaces[sp_id]
                if not sp.solid and c in sp.floor:
                    sp.floor[c] = f0
            cells = set(d.cells)
            for L in [L for L in P.lifts if set(L[4]) & cells]:
                P.lifts.remove(L)
                P.no_items.difference_update(L[0])
            for L in [L for L in P.ladders if set(L[0]) & cells]:
                P.ladders.remove(L)
                P.no_items.difference_update(L[4])
        P.doors = [d for d in P.doors if d not in gone]
        P.metrics["pruned_dead_ends"] = int(P.metrics.get("pruned_dead_ends") or 0) + 1


def lift_in(P: Plan, d: Door, low: Space, zl: int, zh: int) -> bool:
    """A lift in front of the door inside the low space: a plat two cells deep and the door's width, at rest flush
    with the low floor, riding up to the door's level (brief 19 §6: «лифт как уязвимость» - the door it rises to is
    the only way up there when it is the only route)."""
    into = None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if (d.cells[0][0] + dx, d.cells[0][1] + dy) in low.floor:
            into = (dx, dy)
    if into is None:
        return False
    plat = [(c[0] + into[0] * k, c[1] + into[1] * k) for c in d.cells for k in (1, 2)]
    beyond = [(c[0] + into[0] * 3, c[1] + into[1] * 3) for c in d.cells]
    # brief 21 D1 (the PO 05.11: «лифт накладывается на … второй лифт рядом … мерцает»): a plat never takes a cell
    # another mover, a ladder's foot or another lift's step-off holds - two lifts of one room shared a cell
    taken = set(P.no_items) | {c for (_p, _zl, _zh, _b, top) in P.lifts for c in top}
    taken |= {(c[0] + dx, c[1] + dy) for (pl, *_r) in P.lifts for c in pl for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    # the PO 12.11: a plat rests in a recess 16 deep - beside a deep pool (its water 8 under the floor) the water would
    # stand in it: no plat at a pool's side
    taken |= {(c[0] + dx, c[1] + dy) for pool in P.pools for c in pool["cells"] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
    for c in plat + beyond:
        f = low.floor.get(c)
        if f is None or f[1] != "flat" or f[0] != zl or c in taken:
            return False
    d.z, d.stair, d.kind = zh, None, "lift"
    P.lifts.append((plat, zl, zh, plat, list(d.cells)))
    P.no_items.update(plat)
    return True


def shift_space(s: Space, dz: int) -> None:
    s.base += dz
    for c, f in list(s.floor.items()):
        s.floor[c] = (f[0] + dz, f[1], f[2], f[3])
    s.pit = list(s.pit)


def shape_leaves(P: Plan, rnd: random.Random) -> None:
    """Brief 19 §6, two mechanics that need a room with one way in: the dead-end stack (a room under a drop of 128,
    left by a rocket jump - koldduel1's mega) and the lift as exposure (a ledge room 192 up that only a lift reaches -
    omf's east lift). The leaf's floors move as one; its door becomes the drop or the lift."""
    mech = set(P.params.get("mechanics") or [])
    deg = {}
    for d in P.doors:
        deg[d.a] = deg.get(d.a, 0) + 1
        deg[d.b] = deg.get(d.b, 0) + 1
    leaves = [(d, d.a if deg.get(d.a) == 1 else d.b) for d in P.doors
              if (deg.get(d.a) == 1) != (deg.get(d.b) == 1) and d.kind == "door"]
    rnd.shuffle(leaves)
    leaves.sort(key=lambda t: P.spaces[t[1]].kind == "hall")
    used = set()
    if "dead_end_stack" in mech:
        for d, leaf in leaves:
            L, N = P.spaces[leaf], P.spaces[d.b if d.a == leaf else d.a]
            if L.atrium or L.pit:
                continue
            zn, zl = door_side_floor(P, d, N), door_side_floor(P, d, L)
            shift_space(L, (zn - 128) - zl)
            d.kind, d.z, d.rj = "drop", zn, True
            d.za, d.zb = door_side_floor(P, d, P.spaces[d.a]), door_side_floor(P, d, P.spaces[d.b])
            used.add(leaf)
            P.asked.add(leaf)
            # the walk of a compiled map rides no rocket jump: this room is the one place it may find no way out of -
            # its cells, and its box in map units (x0 y0 x1 y1 z0 z1) for the check to tell it from a trap elsewhere
            P.metrics["dead_end_cells"] = len(L.floor)
            xs = [c[0] for c in L.floor]
            ys = [c[1] for c in L.floor]
            zs_ = [f[0] for f in L.floor.values()]
            P.metrics["dead_end_box"] = [min(xs) * CELL, min(ys) * CELL, (max(xs) + 1) * CELL, (max(ys) + 1) * CELL,
                                         min(zs_) - 16, max(zs_) + 96]
            P.reasons.append(("drop", f"тупик {leaf}: спуск 128 внутрь, выход рокет-джампом"))
            break
    if "lift_exposure" in mech and int(P.params.get("lifts") or 0) > 0:
        for d, leaf in leaves:
            if leaf in used:
                continue
            L, N = P.spaces[leaf], P.spaces[d.b if d.a == leaf else d.a]
            if L.atrium or L.pit:
                continue
            zn, zl = door_side_floor(P, d, N), door_side_floor(P, d, L)
            dz = (zn + 192) - zl
            shift_space(L, dz)
            if lift_in(P, d, N, zn, zn + 192):
                d.za, d.zb = door_side_floor(P, d, P.spaces[d.a]), door_side_floor(P, d, P.spaces[d.b])
                used.add(leaf)
                P.asked.add(leaf)
                P.reasons.append(("func_plat", f"лифт - единственный путь в зал {leaf} (192 вверх)"))
                break
            shift_space(L, -dz)


def ladder_in(P: Plan, d: Door, low: Space, zl: int, zh: int) -> bool:
    """A ladder up the low space's wall to the door (brief 19 §4 «Лестницы-стремянки»): the door opens at the high
    floor, the wall under it carries a ladder brush (solid + ladder contents) from the low floor to the door's sill.
    The cells in front of it must be plain floor at the low level - one climbs from there."""
    into = None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if (d.cells[0][0] + dx, d.cells[0][1] + dy) in low.floor:
            into = (dx, dy)
    if into is None:
        return False
    front = [(c[0] + into[0], c[1] + into[1]) for c in d.cells]
    for c in front:
        f = low.floor.get(c)
        if f is None or f[1] != "flat" or f[0] != zl or c in P.no_items:
            return False
    d.z, d.stair, d.kind = zh, None, "ladder"
    P.ladders.append((list(d.cells), into, zl, zh, front))
    P.no_items.update(front)
    return True


def door_side_floor(P: Plan, d: Door, s: Space) -> int:
    """The floor of the space's cells just inside the door (their flat level; a stair cell's top)."""
    zs = []
    for c in d.cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if n in s.floor:
                zs.append(floor_top(s.floor[n]))
    return max(zs) if zs else s.base


def door_dir(P: Plan, d: Door, frm: Space, to: Space) -> tuple:
    c = d.cells[0]
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if (c[0] + dx, c[1] + dy) in to.floor:
            return (dx, dy)
    return (1, 0)


def flight_in(P: Plan, d: Door, s: Space, k: int, zl: int, up: tuple, sunk: bool) -> bool:
    """Lay the k stair cells of a door's flight inside `s`, in front of the door. Not sunk (case A, s is the low
    space): the cells climb toward the door from zl. Sunk (case B, s is the high space): the cells continue the
    flight from the door into s, from zl + 32. Refused unless those cells are plain floor of s at one height."""
    into = None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if (d.cells[0][0] + dx, d.cells[0][1] + dy) in s.floor:
            into = (dx, dy)
    if into is None:
        return False
    rows = [[(c[0] + into[0] * (j + 1), c[1] + into[1] * (j + 1)) for j in range(k)] for c in d.cells]
    want = None
    for row in rows:
        for c in row:
            # a lift's plat (or a ladder's foot) holds its cells: steps laid on them made the PO's lift ride through
            # them (04.11, mg_new_duel)
            if c not in s.floor or s.floor[c][1] != "flat" or c in P.no_items:
                return False
            if want is None:
                want = s.floor[c][0]
            elif s.floor[c][0] != want:
                return False
        # one plain cell beyond the flight to step on/off
        beyond = (row[-1][0] + into[0], row[-1][1] + into[1])
        if beyond not in s.floor or s.floor[beyond][1] != "flat" or s.floor[beyond][0] != want or beyond in P.no_items:
            return False
    for row in rows:
        for c in row:
            d.laid.append((s.id, c, s.floor[c]))
    for row in rows:
        for j, c in enumerate(row):
            if not sunk:
                # the j-th cell from the door: the door starts at zl + 32 k, this one 32 (j + 1) lower
                s.floor[c] = (zl + RISE_PER_CELL * (k - 1 - j), "stair", up[0], up[1])
            else:
                s.floor[c] = (zl + RISE_PER_CELL * (j + 1), "stair", up[0], up[1])
    return True


def side_floor_at(s: Space, run) -> int | None:
    zs = []
    for c in run:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if n in s.floor:
                zs.append(s.floor[n])
    if not zs:
        return None
    if any(f[1] != "flat" for f in zs) or len({f[0] for f in zs}) != 1:
        return None
    return zs[0][0]


def deadly_pits(P: Plan, rnd: random.Random) -> None:
    """«Пропасть / смертельная яма» (brief 19 §4): a hall's sunken middle made a chasm - its floor 320 under the hall's,
    no steps down, a trigger_hurt at its bottom. A bridge across it first (the pattern people know); a pit after."""
    want = int(P.params.get("pits") or 0)
    if want <= 0:
        return
    cands = [s for s in P.spaces if not s.solid and s.pit]
    cands.sort(key=lambda s: (s.pattern != "bridge", rnd.random()))
    for s in cands[:want]:
        bottom = s.base - 320
        cells = list(s.pit)
        for c, f in list(s.floor.items()):
            if f[1] == "stair" and f[0] < s.base:
                cells.append(c)
        for c in cells:
            s.floor[c] = (bottom, "flat", 0, 0)
        s.pit = []
        P.pits.append((cells, bottom, s.id))
        P.no_items.update(cells)
        P.reasons.append(("trigger_hurt", f"смертельная яма в зале {s.id}" + (" под мостом" if s.pattern == "bridge" else "")))


def liquids(P: Plan, rnd: random.Random) -> None:
    """Pits take the liquids asked, by share of the floor: lava and slime first (no steps into them - nobody goes in
    on purpose), then water (the pit keeps its steps: one swims out)."""
    q = P.params
    live = [s for s in P.spaces if not s.solid]
    total = sum(len(s.floor) for s in live) or 1
    pits = [s for s in live if s.pit]
    rnd.shuffle(pits)
    deep = water_deep(q)
    for kind in ("lava", "slime", "water"):
        want = float(q.get(kind) or 0) * total
        if kind == "water" and want <= 0 and deep and int(q.get("underwater") or 0) > 0:
            want = max((len(s_.pit) for s_ in pits), default=1)     # the PO 12.11: a prize under water - one pool
        if want <= 0:
            continue
        got = 0
        pits.sort(key=lambda s: abs(len(s.pit) - want))
        levels = kind == "water" and deep and q.get("water_body") == "levels"
        if levels:
            # pools on three floors at least: a hall of each floor first, the biggest pits first
            seen_, first_, rest_ = set(), [], []
            for s in sorted(pits, key=lambda s: -len(s.pit)):
                (first_ if s.base not in seen_ else rest_).append(s)
                seen_.add(s.base)
            pits[:] = first_ + rest_
        made_ = 0
        later = [k for k in ("lava", "slime", "water")[("lava", "slime", "water").index(kind) + 1:]
                 if float(q.get(k) or 0) > 0]
        for s in list(pits):
            if got >= want * 0.85 and not (levels and made_ < 3):
                break
            if got > 0 and len(pits) <= len(later):
                break               # a pit is left for each liquid still to come
            if got > 0 and got + len(s.pit) > want * 1.8 and not (levels and made_ < 3):
                continue            # this pit would take far more than asked: a smaller one, or a flooded room
            pits.remove(s)
            made_ += 1
            cells = list(s.pit)
            z0 = min(s.floor[c][0] for c in cells)
            if kind == "water" and deep:
                # the pit's own steps go into the pool - those joined to it; a flight of the hall down to a doorway
                # stays (the test plan of 12.11: a flight to the hall's door became a well 224 deep)
                pitset = set(cells)
                bx0, bx1 = min(c[0] for c in cells) - 1, max(c[0] for c in cells) + 1
                by0, by1 = min(c[1] for c in cells) - 1, max(c[1] for c in cells) + 1
                grew = True
                while grew:
                    grew = False
                    for c, f in s.floor.items():
                        if f[1] == "stair" and f[0] < s.base and c not in pitset and bx0 <= c[0] <= bx1                                 and by0 <= c[1] <= by1 and any((c[0] + dx, c[1] + dy) in pitset
                                                               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                            pitset.add(c)
                            grew = True
                # the water keeps off what is lower than the rim beside it - a flight of the hall down to a doorway, a
                # doorway, a window (the test plans of 12.11: water stood in a doorway's opening and behind a window):
                # a pool's cell beside such a one is the rim's floor
                low = {c for d in P.doors for c in d.cells} | {c for (cs, *_w) in P.windows for c in cs}
                low |= {c for (pl, *_r) in P.lifts for c in pl}       # a plat's recess, 16 under the floor
                bad = True
                while bad:
                    bad = [c for c in pitset if any(
                        n not in pitset and (n in low or (n in s.floor and (s.floor[n][1] == "stair" or s.floor[n][0] < s.base)))
                        for n in ((c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)))]
                    for c in bad:
                        pitset.discard(c)
                        # a flight stays the flight it was (duel_big, seed 708: a hall's flight made flat floor cut
                        # its terrace off); the pit's own floor comes up to the rim's
                        if s.floor[c][1] != "stair":
                            s.floor[c] = (s.base, "flat", 0, 0)
                cells = sorted(pitset)
                if len(cells) < POOL_MIN:
                    # what the doorways and flights left is a well, not a pool (the PO 12.11: «узкая небольшая подводная
                    # нычка»): the pit is filled to the rim's floor, no water here
                    for c in cells:
                        s.floor[c] = (s.base, "flat", 0, 0)
                    continue
                # the PO 12.11: a pool as people's - its water 224 deep, 8 under the rim's floor; no steps: one swims
                # up and climbs out anywhere round it (q2dm1, q2dm5)
                z0, level = s.base - POOL_SURFACE - POOL_DEPTH, s.base - POOL_SURFACE
                for c in cells:
                    s.floor[c] = (z0, "flat", 0, 0)
                P.pools.append({"space": s.id, "cells": list(cells), "bottom": z0, "surface": level,
                                "liq": len(P.liquids)})
            elif kind != "water":
                # the steps into it go: the whole sunken part is liquid
                for c, f in list(s.floor.items()):
                    if f[1] == "stair" and f[0] < s.base:
                        s.floor[c] = (z0, "flat", 0, 0)
                        cells.append(c)
                level = z0 + 32
            else:
                level = z0 + 48
                # the water fills over the pit's steps too - stopped at the pit's flat cells it stood beside the steps
                # as a wall of water in the air (04.11: 16 vertical faces in each pool)
                cells = cells + [c for c, f in s.floor.items() if f[1] == "stair" and f[0] < s.base]
            P.liquids.append((cells, kind, z0, level))
            P.no_items.update(cells)
            got += len(cells)
            # brief 20 D4: what share of its hall a pool takes (the check holds a third at most)
            P.metrics["pool_share_max"] = max(P.metrics.get("pool_share_max", 0.0), round(len(cells) / max(1, len(s.floor)), 2))
        if kind == "water" and got < want * 0.85 and not q.get("water_above_floor"):
            P.notes.append(say(f"вода: {got / max(1, total):.0%} из {want / max(1, total):.0%} - в ямах залов больше места нет; "
                               f"затопить комнаты поверх пола можно, включив «Разрешить воде возвышаться над полом»",
                               f"water: {got / max(1, total):.0%} of {want / max(1, total):.0%} - the halls' pits hold no more; "
                               f"rooms are flooded over their floor only with «Let water stand above the floor»"))
        if kind == "water" and got < want * 0.85 and q.get("water_above_floor"):
            # much water asked: whole room floors flooded ankle-deep (32: one wades, slower - no swimming), the
            # biggest flat rooms first, never the atrium nor a corridor
            rooms = sorted((s for s in live if not s.atrium and s.kind != "corridor" and not s.pit),
                           key=lambda s: -len(s.floor))
            for s in rooms:
                if got >= want * 0.85:
                    break
                cells = [c for c, f in s.floor.items() if f[1] == "flat" and f[0] == s.base and c not in P.no_items]
                if len(cells) < 8:
                    continue
                P.liquids.append((cells, "water", s.base, s.base + 32))
                P.no_items.update(cells)
                got += len(cells)


# --------------------------------------------------------------------------------------------- the water under rock
# A tube runs under the rooms' floors, as q2dm1's does: its cells are keys of a layer of their own (phys() puts them in
# the ground cell's column, the world builds them as a second span of air under the floor) - the plan's walk keeps
# the room's floor and the tube apart. A slab of 16 at least between a tube and any air round it.
WATER_LAYER = 15


def wl(c):
    """A ground cell's key on the tubes' layer."""
    return (c[0], c[1] + UP * WATER_LAYER)


def air_spans(P: Plan) -> dict:
    """What air each world cell holds (its spans low..high): the spaces' floors to their ceilings, the doorways, the
    windows, the overlooks - what a tube or a room carved into the rock keeps off; "_taken": the cells a carved room
    never takes (doorways, windows, overlooks)."""
    occ: dict = {}
    for s in P.spaces:
        if s.solid:
            continue
        for c0, f in s.floor.items():
            occ.setdefault(phys(c0), []).append((f[0] - 16, P.cell_ceil.get(c0, s.ceil)))
    for d in P.doors:
        for c0 in d.cells:
            occ.setdefault(phys(c0), []).append((d.z, door_top(d)))
    for (cells, z0, z1, *_w) in P.windows:
        for c in cells:
            occ.setdefault(phys(c), []).append((z0, z1))
    for (cells, z0, z1, *_r) in P.overlooks:
        for c in cells:
            occ.setdefault(phys(c), []).append((z0, z1))
    occ["_taken"] = ({phys(c) for d in P.doors for c in d.cells} | {phys(c) for (cs, *_w) in P.windows for c in cs}
                     | {phys(c) for (cs, *_r) in P.overlooks for c in cs})
    return occ


def _free(P: Plan, occ: dict, c, lo: int, hi: int, keep=frozenset()) -> bool:
    """Air from lo to hi fits at the ground cell `c` with a slab of 16 to any air in it or beside it (the cells of
    `keep` aside - what it is meant to open into)."""
    if not (1 <= c[0] < P.W - 1 and 1 <= c[1] < P.H - 1):
        return False
    for n in (c, (c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)):
        if n != c and n in keep:
            continue
        if any(a < hi + 16 and b > lo - 16 for (a, b) in occ.get(n, ())):
            return False
    return True


def _rock(P: Plan, occ: dict, c, lo: int, hi: int, keep=frozenset()) -> bool:
    """A ground cell of rock a room may be carved in: nobody's, no doorway or window, its air free (`_free`)."""
    return c not in P.owner and c not in occ["_taken"] and _free(P, occ, c, lo, hi, keep)


def _water_held(P: Plan) -> set:
    held = _prize_held(P) | {c for (src, dst, *_r) in P.pads for c in (src, dst)} | {c for t in P.teleports for c in t}
    held |= {c for (*_r, front) in P.ladders for c in front} | button_cells(P) | set(P.fx_cells)
    return held


def _tube_bfs(P: Plan, occ: dict, pool: dict, zt: int, most: int, goal=None):
    """Through the rock (under the floors) from the side of a pool: each reached ground cell's (steps, the cell it came
    from). The first cell opens into the pool; the others keep off it and off all air. `goal`: the cells another pool
    holds - a cell beside them that may open into them arrives (it goes no farther)."""
    lo, hi = zt, zt + TUBE_H
    mine = frozenset(phys(c) for c in pool["cells"])
    goal = frozenset(goal or ())
    seen, q, came = {}, [], set()
    for p in sorted(mine):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (p[0] + dx, p[1] + dy)
            if n in mine or n in seen or not _free(P, occ, n, lo, hi, mine):
                continue
            seen[n] = (1, None)
            q.append(n)
    for c in q:
        n0 = seen[c][0]
        if n0 >= most or c in came:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if n in seen or n in mine or n in goal:
                continue
            if _free(P, occ, n, lo, hi):
                seen[n] = (n0 + 1, c)
                q.append(n)
            elif goal and _free(P, occ, n, lo, hi, goal):
                seen[n] = (n0 + 1, c)
                came.add(n)
    return seen, came


def _path_to(seen: dict, c) -> list:
    out = []
    while c is not None:
        out.append(c)
        c = seen[c][1]
    return out[::-1]


def _tube_z(a: dict, b: dict) -> int | None:
    """The tube's floor: in both pools' water, its roof under both surfaces. A pool on a far higher floor is sunk to
    it (q2dm4's water 432 deep); more than 256 apart - a breath is not enough."""
    if abs(a["surface"] - b["surface"]) > 256:
        return None
    zt = max(a["bottom"], b["bottom"])
    # its roof 40 under the lower surface at least: it passes under the rims' floors (a slab and the plats' recess)
    top = min(a["surface"], b["surface"]) - TUBE_H - 40
    return zt if zt <= top else top


def _sink(P: Plan, pool: dict, zt: int) -> None:
    """A pool's floor down to `zt` (its water too)."""
    if zt >= pool["bottom"]:
        return
    s = P.spaces[pool["space"]]
    for c in pool["cells"]:
        s.floor[c] = (zt, "flat", 0, 0)
    i = pool.get("liq")
    if i is not None and i < len(P.liquids):
        cells, kind, _z0, level = P.liquids[i]
        P.liquids[i] = (cells, kind, zt, level)
    pool["bottom"] = zt


def _lay_tube(P: Plan, occ: dict, path: list, zt: int, a: int, b: int) -> Door:
    cells = [wl(c) for c in path]
    d = Door(a, b, cells, za=zt, zb=zt, z=zt, kind="swim", top=zt + TUBE_H, cross=True)
    P.doors.append(d)
    P.liquids.append((list(cells), "water", zt, zt + TUBE_H))
    for c in path:
        occ.setdefault(c, []).append((zt, zt + TUBE_H))
    return d


def water_network(P: Plan, rnd: random.Random) -> None:
    """The PO 12.11 («на q2dm4 или q2dm5 там вообще многоуровневые конструкции с множеством глубоких водоемов через
    которые можно плавать»): the deep pools joined by tubes under water, as people join theirs (q2dm2, q2dm4, q2dm5,
    q2rdm13 - every map of his families with two deep pools or more) - the nearest pairs first, a tree."""
    pools = [p for p in P.pools if len(p["cells"]) >= 2]
    tubes = []
    if len(pools) >= 2 and water_deep(P.params):
        occ = air_spans(P)

        def mid(p):
            return (sum(c[0] for c in p["cells"]) / len(p["cells"]), sum(c[1] for c in p["cells"]) / len(p["cells"]))
        pairs = sorted(((abs(mid(a)[0] - mid(b)[0]) + abs(mid(a)[1] - mid(b)[1]), i, j)
                        for i, a in enumerate(pools) for j, b in enumerate(pools) if i < j))
        root = list(range(len(pools)))

        def find(i):
            while root[i] != i:
                i = root[i]
            return i
        for _d, i, j in pairs:
            if find(i) == find(j):
                continue
            a, b = pools[i], pools[j]
            zt = _tube_z(a, b)
            if zt is None:
                continue
            # the higher pool sunk to the tube first: its water then holds the tube's mouth whole
            keep_a, keep_b = a["bottom"], b["bottom"]
            _sink(P, a, zt)
            _sink(P, b, zt)
            occ = air_spans(P)
            seen, came = _tube_bfs(P, occ, a, zt, TUBE_CELLS[1], [phys(c) for c in b["cells"]])
            ends = sorted((c for c in came if seen[c][0] >= 4), key=lambda c: (seen[c][0], c))
            if not ends:
                # no tube: the pools as they were
                for p, z_ in ((a, keep_a), (b, keep_b)):
                    if p["bottom"] != z_:
                        s = P.spaces[p["space"]]
                        for c in p["cells"]:
                            s.floor[c] = (z_, "flat", 0, 0)
                        cells, kind, _z0, level = P.liquids[p["liq"]]
                        P.liquids[p["liq"]] = (cells, kind, z_, level)
                        p["bottom"] = z_
                continue
            path = _path_to(seen, ends[0])
            _lay_tube(P, occ, path, zt, a["space"], b["space"])
            root[find(i)] = find(j)
            tubes.append(len(path))
            P.reasons.append(("water", say(f"подводная труба {len(path) * CELL} ед. между бассейнами залов {a['space']} и {b['space']}",
                                           f"a tube under water {len(path) * CELL} u long between the pools of halls {a['space']} and {b['space']}")))
    P.metrics["water_tubes"] = tubes
    P.metrics["pools"] = [[len(p["cells"]), p["surface"] - p["bottom"], p["surface"]] for p in P.pools]
    if P.params.get("water_body") == "levels" and P.pools:
        lv = sorted({p["surface"] for p in P.pools})
        if len(lv) < 3 or len(tubes) < len(P.pools) - 1:
            P.notes.append(say(f"вода на разных уровнях: бассейнов на разных высотах {len(lv)}, подводных труб {len(tubes)} - на этом каркасе больше не нашлось места",
                               f"water on several levels: pools at {len(lv)} heights, {len(tubes)} tubes under water - no more room on this skeleton"))


def flights_and_ramps(P: Plan, rnd: random.Random) -> None:
    """The flights of steps as groups of stair cells (one direction, side by side or in a row; a door's own cell with
    them); as many as asked laid as ramps (brief 19 §4 «Пандусы»): the same rise, a slope instead of two steps."""
    stair = {}
    for s in P.spaces:
        if s.solid:
            continue
        for c, f in s.floor.items():
            if f[1] == "stair":
                stair[c] = (f[2], f[3])
    for d in P.doors:
        if d.stair:
            for c in d.cells:
                stair[c] = d.stair
    left = set(stair)
    groups = []
    while left:
        c0 = left.pop()
        g, todo = {c0}, [c0]
        while todo:
            c = todo.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n in left and stair[n] == stair[c0]:
                    left.discard(n)
                    g.add(n)
                    todo.append(n)
        groups.append(g)
    P.flights = groups
    want = int(P.params.get("ramps") or 0)
    if want > 0:
        door_cells = {c for d in P.doors if d.stair for c in d.cells}
        order = sorted(groups, key=lambda g: (not (g & door_cells), rnd.random()))
        for g in order[:want]:
            P.ramps |= g
    P.metrics["stairs_got"] = sum(1 for g in groups if not (g & P.ramps))
    P.metrics["ramps_got"] = sum(1 for g in groups if g & P.ramps)


# Brief 36 (the PO 11.11: «у двери мерцает текстура при её движении»): which way one walks through a door - the world
# builder stands a door in the middle of its wall by it (mapgen_scratch_world.door_box)
def door_across(P: Plan, d) -> int | None:
    """The axis one walks through a door along (0: x, 1: y): its cells lie along the wall, so across is the other axis;
    one cell by which of its sides its two spaces hold - one on each side is the way through (a powerup's nook opening
    stands in its room's corner: the room holds three sides of it, the nook the fourth - duel_highrise 702). None when
    nothing tells."""
    xs = {c[0] for c in d.cells}
    ys = {c[1] for c in d.cells}
    if len(ys) == 1 and len(xs) > 1:
        return 1
    if len(xs) == 1 and len(ys) > 1:
        return 0
    sides = {d.a, d.b}
    by_x = by_y = 0
    for c in d.cells:
        nx = (P.owner.get((c[0] - 1, c[1])), P.owner.get((c[0] + 1, c[1])))
        ny = (P.owner.get((c[0], c[1] - 1)), P.owner.get((c[0], c[1] + 1)))
        by_x += 4 * (set(nx) == sides and d.a != d.b) + sum(o in sides for o in nx)
        by_y += 4 * (set(ny) == sides and d.a != d.b) + sum(o in sides for o in ny)
    if by_x > by_y:
        return 0
    if by_y > by_x:
        return 1
    return None


def moving_doors(P: Plan, rnd: random.Random) -> None:
    """«Двери» (brief 19 §4): as many func_door as asked, each in a level doorway of the routes (two or three cells
    wide), opening upward when one comes near - a door on a route, never a wall."""
    want = int(P.params.get("doors") or 0)
    cands = [d for d in P.doors if d.kind == "door" and not d.stair and d.za == d.zb == d.z and 2 <= len(d.cells) <= 3]
    rnd.shuffle(cands)
    for d in cands[:want]:
        d.mover = True
        P.no_items.update(d.cells)
        P.reasons.append(("func_door", f"дверь между {d.a} и {d.b}"))


def movers(P: Plan, rnd: random.Random) -> None:
    """Jump pads in tall spaces throwing up to a higher terrace of the same space, and teleporter pairs between far
    places; both as many as asked."""
    q = P.params
    nodes, edges = plan_graph(P)
    live = [s for s in P.spaces if not s.solid]
    want = int(q.get("pads") or 0)
    pit_halls = {sid for (_, _, sid) in P.pits}
    over_pit = "pad_pit" in (q.get("mechanics") or []) and pit_halls
    tall = sorted([s for s in live if (s.ceil - s.base >= 256 and s.kind == "hall") or (over_pit and s.id in pit_halls)],
                  key=lambda s: (not (over_pit and s.id in pit_halls), rnd.random()))
    for s in tall:
        if want <= 0:
            break
        lows = [c for c, f in s.floor.items() if f[1] == "flat" and f[0] == s.base and c not in P.no_items]
        highs = [c for c, f in s.floor.items() if f[1] == "flat" and f[0] >= s.base + 64 and c not in P.no_items]
        pit_cells = {c for (cells, _, sid) in P.pits if sid == s.id for c in cells}
        if over_pit and pit_cells:
            # across the chasm, on the rim at the same level: the flight crosses the pit (brief 19 §6 «джампад над ямой»)
            highs = [c for c, f in s.floor.items() if f[1] == "flat" and f[0] == s.base and c not in P.no_items
                     and any((c[0] + dx, c[1] + dy) in pit_cells for dx in (-2, 2, 0) for dy in (-2, 2, 0))]
        rnd.shuffle(lows)
        # a target well inside its terrace (two cells from any lower floor), so the flight does not graze an edge
        def inner(c):
            z = s.floor[c][0]
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    f = s.floor.get((c[0] + dx, c[1] + dy))
                    if f is None or f[0] < z or f[1] != "flat":
                        return False
            return True
        if not (over_pit and pit_cells):
            highs = [c for c in highs if inner(c)]
        done = False
        # brief 34: the take-offs apart, none beside a teleporter or a spawn
        lows = [c for c in lows if pad_spot_ok(P, c, s.base)]
        # brief 34 §3: the take-off at the terrace's foot (the nearest to its floor first), the landing on its far side
        # (the farthest from the take-off first) - two random cells read as a pad for nothing
        if highs and not (over_pit and pit_cells):
            lows.sort(key=lambda c: min(max(abs(c[0] - h[0]), abs(c[1] - h[1])) for h in highs))
        for a in lows[:80]:
            from_a = None
            far = highs if over_pit and pit_cells else sorted(highs, key=lambda t: -math.hypot(t[0] - a[0], t[1] - a[1]))
            for t in far:
                dxu, dyu = (t[0] - a[0]) * CELL, (t[1] - a[1]) * CELL
                D = math.hypot(dxu, dyu)
                H = s.floor[t][0] - s.base - PAD_TOP     # from the take-off on the pad's plinth (brief 26)
                if not (192 <= D <= 704):
                    continue
                if over_pit and pit_cells:
                    mid = (int((a[0] + t[0]) / 2 + 0.5), int((a[1] + t[1]) / 2 + 0.5))
                    if mid not in pit_cells:
                        continue
                for T in (0.9, 1.1, 1.3, 0.75):
                    vz = (H + 0.5 * 800 * T * T) / T
                    vh = D / T
                    pitch = math.degrees(math.atan2(vz, vh))
                    vxy = (dxu / D * vh, dyu / D * vh)
                    if pad_flight_clear(P, s, a, vxy, vz, T, s.floor[t][0]) and (
                            pitch >= PAD_STEEP or pad_flight_clear(P, s, a, vxy, vz, T, s.floor[t][0], PAD_WEDGE_LIFT)):
                        # brief 34: a terrace a stair already joins near by is no pad's reason (a chasm's pad is)
                        if not (over_pit and pit_cells):
                            if from_a is None:
                                from_a = dijkstra(edges, a)
                            if from_a.get(t, 1e9) <= NO_REASON_S:
                                break
                        speed = math.hypot(vh, vz) / 10.0
                        yaw = math.degrees(math.atan2(dyu, dxu))
                        P.pads.append((a, t, T + 0.1, round(speed, 1), round(pitch, 2), round(yaw, 2), s.base))
                        P.pad_why[(a, t)] = "pit" if over_pit and pit_cells else "shortcut"
                        P.no_items.update({a, t})
                        reserve_flight(P, a, t)
                        P.reasons.append(("trigger_push", f"джампад в зале {s.id}: полёт {T + 0.1:.1f} с"
                                          + (" над пропастью" if over_pit and pit_cells else f" на {H} вверх")))
                        want -= 1
                        done = True
                        break
                if done:
                    break
            if done:
                break
    want = int(q.get("teleporters") or 0)
    flat = [c for c, f in nodes.items() if f[1] == "flat" and P.owner.get(c) is not None and c not in P.no_items]
    # brief 34: no teleporter beside a pad
    flat = [c for c in flat if all(layer_of(c) != layer_of(a) or max(abs(phys(c)[0] - phys(a)[0]), abs(phys(c)[1] - phys(a)[1])) > 1
                                   for (a, *_r) in P.pads)]
    rnd.shuffle(flat)
    for _ in range(want):
        if OLD_MOVER_RULES:
            best = None
            for a in flat[:40]:
                ta = dijkstra(edges, a)
                for b_ in flat[:200]:
                    if P.owner.get(b_) == P.owner.get(a) or b_ not in ta:
                        continue
                    if best is None or ta[b_] > best[0]:
                        best = (ta[b_], a, b_)
            if not best:
                break
            walk_s, a, b_ = best
            da = exit_cell(P, a)
            db = exit_cell(P, b_)
            if da is None or db is None:
                continue
        else:
            # brief 35: the farthest pair on foot whose four ends keep apart from every disc, exit, pad and spawn -
            # and from every other pair's (TELE_PAIRS_APART): a second pair never joins the places the first joins
            found = pair_of_ends(P, flat[:40], flat[:200], edges)
            if found is None:
                break
            walk_s, a, b_, da, db = found
        P.teleports.append((a, b_, da, db))
        P.no_items.update({a, b_, da, db})
        import mapgen_scratch_fixtures as fix_mod     # brief 26: the frames' posts stand beside the discs
        fix_mod.reserve_frame(P, a)
        fix_mod.reserve_frame(P, b_)
        P.reasons.append(("misc_teleporter", f"пара телепортов между дальними местами, {walk_s:.1f} с пешком"))
        flat = [c for c in flat if c not in P.no_items]
        # brief 34: no third teleporter within four cells of two (teleports4 put three discs together, 08.11)
        discs = [((phys(c)[0] + 0.5) * CELL, (phys(c)[1] + 0.5) * CELL, nodes[c][0]) for tp in P.teleports for c in tp[:2] if c in nodes]
        flat = [c for c in flat if not fix_mod.crowded(discs, ((phys(c)[0] + 0.5) * CELL, (phys(c)[1] + 0.5) * CELL, nodes[c][0]))]


# brief 26: a pad's disc or wedge stands on a plinth - the take-off is this far over the floor (8 + 4: a step), the
# flights start from there (mapgen_scratch_fixtures)
PAD_TOP = 12
# ... a pad flying up steeper than this is a disc (flat); a slanted one a wedge rising to its far end, and the take-off
# runs from its foot (the game: the trigger is touched from the plinth) to over its top (the people's survey launches
# from the walk node nearest the trigger's middle - on the wedge 18 over the disc's height, 06.11: a rooms pad that
# landed from the foot flew past its landing from there). A slanted pad's flight must land from both
PAD_STEEP = 75
PAD_WEDGE_LIFT = 18


def reserve_flight(P: Plan, a, t) -> None:
    """Brief 26: the cells under a pad's flight and two cells on past its landing kept free (no item, no column - the
    columns that break long sight lines come after the pads: one stood one cell past a landing, and the flight from
    over the pad's wedge, a little longer, hit it, 06.11)."""
    dx, dy = t[0] - a[0], t[1] - a[1]
    n = max(abs(dx), abs(dy), 1)
    ux, uy = dx / n, dy / n
    for k in range(1, n + 3):
        c = (int(round(a[0] + ux * k)), int(round(a[1] + uy * k)))
        if c != t and c != a and P.owner.get(c) is not None:
            P.no_items.add(c)


# brief 34 (the PO 08.11 on his tower mg_new_18619, five pads a cell apart on the atrium's floor: «джампады вот так
# наставлены - как кучу говна выкатили в одном месте … навалено куча джампадов непонятно для чего»; «всё хорошо в
# меру»; «каждый уровень … архитектурным шедевром, а не набором напиханного»): two take-offs on one floor at least
# PAD_APART cells apart (192 u - pro_q2t4's nearest two are 527 apart, one pad a corner), none beside a teleporter's
# disc or exit or a spawn; a pad whose landing is NO_REASON_S or less away on foot is a second way beside the first -
# not built (a pad over a chasm and a pad to a ledge only a pad reaches are pads by design)
PAD_APART = 3
# brief 34: a lamp over the floor takes its cell's own ceiling (a tower's perch well); off only for
# check_mapgen_tower_ways.py's RED
FREE_LAMP_CELL_CEIL = True
NO_REASON_S = 2.5
TRAIN_SPEED = 160.0     # brief 34: the stopping lift's speed (u/s) and its wait at each stop (s)
TRAIN_WAIT = 2.0


def same_floor(P: Plan, a, b, za: float, zb: float) -> bool:
    """Two plan keys standing on one floor: one layer, within 64 in height, one space or two joined ones."""
    if layer_of(a) != layer_of(b) or abs(za - zb) >= 64:
        return False
    oa, ob = P.owner.get(a), P.owner.get(b)
    return oa == ob or frozenset((oa, ob)) in P.joined


# Brief 35 (the PO 11.11, mg_new_91126: «ни телепорты ни джампады ни точки спавна рядом не делать», «напиханы как
# грибы», «это делает нормальную в целом карту дерьмовой»): two teleporter pairs joined the same two places - discs 91
# and 143 u apart, exits 64 u - and the exits, which the game draws as a spawn point's plate, stood in a row with spawn
# points. Brief 34's «more than two like things» let two stand side by side. The PO's own rule, stricter than people's
# maps (q2duel1 stands a spawn 162 u from an exit):
MOVER_APART = 4          # cells between any two of a teleporter's disc, its exit, a jump pad's take-off, a spawn point
TELE_PAIRS_APART = 8     # cells between a pair's disc or exit and another pair's
PLATES_NEAR = 6          # cells: spawn points and teleporter exits (one plate to the eye) - no more than PLATES_MAX
PLATES_MAX = 2
ONE_FLOOR_DZ = 96        # one floor to the eye: a flight of steps is the same place
EXIT_RING = (4, 6)       # a teleporter's exit from its own disc, in cells
# the RED: 3.60's rules (a third disc only, exits 3..5 off, a spawn 4 cells off a mover); MAPGEN_OLD_MOVER_RULES=1 sets it
# for a process importing the planner (a check, a replay) - the Studio's skeleton step does not pass it on
OLD_MOVER_RULES = __import__("os").environ.get("MAPGEN_OLD_MOVER_RULES") == "1"


def cell_z(P: Plan, c) -> float:
    """The floor a plan key stands on."""
    if c in P.owner:
        return P.spaces[P.owner[c]].floor[c][0]
    return getattr(P, "_door_z", {}).get(c, 0)


def mover_marks(P: Plan, spawns=None) -> list:
    """Brief 35: every teleporter disc and exit, jump pad take-off and spawn point - (kind, key, z, pair); `spawns` the
    spawn keys being placed (else the plan's)."""
    out = []
    for i, (a, b, da, db) in enumerate(P.teleports):
        out += [("disc", a, cell_z(P, a), i), ("disc", b, cell_z(P, b), i), ("exit", da, cell_z(P, da), i),
                ("exit", db, cell_z(P, db), i)]
    out += [("pad", a, z, None) for (a, _t, _T, _sp, _pi, _ya, z) in P.pads]
    # a pad's landing: where its flight comes down - no teleporter, exit or spawn in its way (the fixtures check at 200 %,
    # 11.11: a frame twice its size stood at a landing on an open space and the flight flew past it into the void)
    out += [("land", t, cell_z(P, t), None) for (_a, t, *_r) in P.pads]
    if spawns is None:
        out += [("spawn", c, z, None) for (c, z, _ang) in P.spawns]
    else:
        out += [("spawn", c, cell_z(P, c), None) for c in spawns]
    return out


def _cheb(a, b) -> int:
    pa, pb = phys(a), phys(b)
    return max(abs(pa[0] - pb[0]), abs(pa[1] - pb[1]))


# the spawns asked are never cut for the plates' rule (brief 35 item 20): the radius gives, step by step, and the plan
# says the one it kept (P.metrics["plates_near"])
PLATES_STEPS = (6, 5, 4, 3, 0)


def spot_ok(P: Plan, c, kind: str, marks=None, z=None, plates_near: int | None = None) -> bool:
    """Brief 35: may a «disc», «exit», «pad» (take-off) or «spawn» stand at c - MOVER_APART cells from every other mark
    on its floor (two pads keep brief 34's own PAD_APART), a teleporter's end TELE_PAIRS_APART from every other pair's,
    and an exit or a spawn not making a third plate within PLATES_NEAR. `marks`: mover_marks(P, ...) when the caller
    holds marks the plan does not yet (a pair being chosen, spawns being picked)."""
    if OLD_MOVER_RULES:
        return True
    zc = cell_z(P, c) if z is None else z
    ms = mover_marks(P) if marks is None else marks
    near_r = PLATES_NEAR if plates_near is None else plates_near
    plates = []
    for (k, m, zm, _pair) in ms:
        if m == c:
            return False
        if layer_of(m) != layer_of(c) or abs(zm - zc) >= ONE_FLOOR_DZ:
            continue
        d = _cheb(c, m)
        if k == "land":
            if kind in ("disc", "exit", "spawn") and d < MOVER_APART:
                return False
            continue
        if not (kind == "pad" and k == "pad") and d < MOVER_APART:
            return False
        if kind in ("disc", "exit") and k in ("disc", "exit") and d < TELE_PAIRS_APART:
            return False
        if k in ("exit", "spawn") and d <= near_r:
            plates.append(m)
    if kind in ("exit", "spawn") and plates:
        if len(plates) + 1 > PLATES_MAX:
            return False
        # nor the third plate of one already there
        for p_ in plates:
            around = sum(1 for (k, m, zm, _pair) in ms if k in ("exit", "spawn") and m != p_ and layer_of(m) == layer_of(p_)
                         and abs(zm - cell_z(P, p_)) < ONE_FLOOR_DZ and _cheb(m, p_) <= near_r)
            if around + 2 > PLATES_MAX:
                return False
    return True


def pad_spot_ok(P: Plan, a, za: float) -> bool:
    """Brief 34: a pad may take off at a - PAD_APART cells from every other take-off on its floor; brief 35: and
    MOVER_APART from every teleporter's disc and exit and every spawn (spot_ok)."""
    pa = phys(a)

    def near(c, d) -> bool:
        pc = phys(c)
        return layer_of(c) == layer_of(a) and max(abs(pa[0] - pc[0]), abs(pa[1] - pc[1])) <= d

    for (a2, _t, _T, _sp, _pi, _ya, z2) in P.pads:
        if same_floor(P, a, a2, za, z2) and near(a2, PAD_APART - 1):
            return False
    if OLD_MOVER_RULES:
        if any(near(c, 1) for tp in P.teleports for c in tp):
            return False
        return not any(near(c, 1) for (c, _z, _ang) in P.spawns)
    return spot_ok(P, a, "pad", z=za)


def pads_without_reason(P: Plan) -> list:
    """Brief 34: the pads whose landing is NO_REASON_S or less from their take-off on foot (no pad, no teleporter on
    the way) - a stair or a door is right there; (take-off, landing, seconds). Pads by design (a perch, a chasm) aside."""
    nodes, edges = plan_graph(P)
    skip = {(a, t) for (a, t, *_r) in P.pads}
    for (a, b, da, db) in P.teleports:
        skip |= {(a, db), (b, da)}
    foot = {c: [(n, w) for (n, w) in es if (c, n) not in skip] for c, es in edges.items()}
    out = []
    for (a, t, *_r) in P.pads:
        if P.pad_why.get((a, t)) in ("perch", "pit"):
            continue
        d = dijkstra(foot, a)
        if t in d and d[t] <= NO_REASON_S:
            out.append((a, t, round(d[t], 2)))
    return out


def foot_time(P: Plan, edges: dict, a, t) -> float | None:
    """The walk from a to t on the graph given (None when it does not get there)."""
    d = dijkstra(edges, a)
    return d.get(t)


def pad_flight_clear(P: Plan, s: Space, a, vh, vz, T, z_land, lift: float = 0.0) -> bool:
    """The flight from the pad: feet over every floor it passes (with a body's margin), head under the ceiling, every
    sample over a cell of this space - until it comes down onto the target's floor."""
    x0, y0 = (a[0] + 0.5) * CELL, (a[1] + 0.5) * CELL
    z0 = s.base + 24.0 + PAD_TOP + lift     # the player's origin over the pad (on its plinth, brief 26)
    t, dt = 0.0, 0.02
    while t < T + 0.4:
        t += dt
        x, y = x0 + vh[0] * t, y0 + vh[1] * t
        z = z0 + vz * t - 400.0 * t * t
        feet, head = z - 24, z + 32
        c = (int(x // CELL), int(y // CELL))
        f = s.floor.get(c)
        if f is None or head > s.ceil - 8:
            return False
        # the body's box: the floors under its four corners
        for ox in (-16, 16):
            for oy in (-16, 16):
                cc = (int((x + ox) // CELL), int((y + oy) // CELL))
                ff = s.floor.get(cc)
                if ff is None:
                    return False
                if feet < floor_top(ff) - 1 and t < T - 0.05:
                    return False
        if t >= T - 0.05 and feet <= z_land + 2 and f[0] == z_land:
            return True
    return False


def pair_of_ends(P: Plan, firsts, seconds, edges, same_space_ok=False, tries: int = 400, pair_ok=None):
    """Brief 35: the teleporter pair the farthest apart on foot - first end among `firsts`, the other among `seconds` in
    another space - whose discs and exits all pass spot_ok (with the pair's own ends as marks); None when none does.
    Returns (walk seconds, a, b, exit of a, exit of b)."""
    cands = []
    for a in firsts:
        if not spot_ok(P, a, "disc"):
            continue
        ta = dijkstra(edges, a)
        for b in seconds:
            if b == a or b not in ta or (not same_space_ok and P.owner.get(b) == P.owner.get(a)):
                continue
            if pair_ok is not None and not pair_ok(a, b):
                continue
            cands.append((ta[b], a, b))
    cands.sort(key=lambda t: -t[0])
    base = mover_marks(P)
    for (walk_s, a, b) in cands[:tries]:
        marks = base + [("disc", a, cell_z(P, a), -1)]
        if not spot_ok(P, b, "disc", marks):
            continue
        marks = marks + [("disc", b, cell_z(P, b), -1)]
        da = exit_cell(P, a, lambda n: _end_ok(P, n, marks, a))
        if da is None:
            continue
        marks2 = marks + [("exit", da, cell_z(P, da), -1)]
        db = exit_cell(P, b, lambda n: _end_ok(P, n, marks2, b))
        if db is None:
            continue
        return walk_s, a, b, da, db
    return None


def _end_ok(P: Plan, n, marks, own) -> bool:
    """An exit at n for the disc `own`: spot_ok against everything but its own disc (4..6 off by exit_cell's ring), and
    TELE_PAIRS_APART from the other pairs' ends - its own pair's far end is far by the pair's choice."""
    others = [m for m in marks if not (m[3] == -1)]
    if not spot_ok(P, n, "exit", others):
        return False
    pair = [m for m in marks if m[3] == -1 and m[1] != own]
    return all(_cheb(n, m[1]) >= MOVER_APART or layer_of(n) != layer_of(m[1]) for m in pair)


def exit_cell(P: Plan, c, ok=None):
    """Where one arrives from the other pad: in the pad's space, 3..5 cells from it (brief 35: EXIT_RING, 4..6), on plain
    floor nobody else holds - not beside the pad (the PO, 04.11: «такие вещи нужно разносить подальше друг от друга»);
    `ok`: brief 35's spot rule for the exit (spot_ok with the pair's marks)."""
    s = P.spaces[P.owner[c]]
    lo, hi = (3, 5) if OLD_MOVER_RULES else EXIT_RING
    best = None
    for n, f in s.floor.items():
        dist = max(abs(n[0] - c[0]), abs(n[1] - c[1]))
        if not (lo <= dist <= hi) or f[1] != "flat" or n in P.no_items or (ok is not None and not ok(n)):
            continue
        clear = all(s.floor.get((n[0] + dx, n[1] + dy), (None, "x"))[1] == "flat"
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        key = (not clear, abs(dist - 4), n)
        if best is None or key < best[0]:
            best = (key, n)
    return best[1] if best else None


def openings(P: Plan, rnd: random.Random) -> None:
    """Overlooks - a higher room or corridor opens wide onto a hall below at its own floor (a ledge one can drop
    from, a line of sight down) - and windows between rooms that share a wall and no door (sill 64 over the higher
    floor: seen through, not walked through)."""
    q = P.params
    nb = neighbours(P)
    paired = {(min(d.a, d.b), max(d.a, d.b)) for d in P.doors}
    taken = {c for d in P.doors for c in d.cells}
    cands = []
    for (a, b), run in nb.items():
        sa, sb = P.spaces[a], P.spaces[b]
        if sa.solid or sb.solid or len(run) < 4:
            continue
        cells = [c for c in run[1:-1] if c not in taken]
        if len(cells) < 2:
            continue
        za, zb = side_floor_at(sa, cells), side_floor_at(sb, cells)
        if za is None or zb is None or not (96 <= abs(za - zb) <= 200):
            continue
        hi, lo = (sa, sb) if za > zb else (sb, sa)
        zh = max(za, zb)
        if lo.kind != "hall":
            continue
        top = min(hi.ceil, lo.ceil) - 16
        if top < zh + 112:
            lo.ceil = max(lo.ceil, zh + 144)
            top = min(hi.ceil, lo.ceil) - 16
            if top < zh + 112:
                continue
        cands.append((0 if lo.atrium else 1, rnd.random(), hi.id, lo.id, cells, zh, top))
    cands.sort()
    want = 3 if q["class"] == "duel" else 4
    used_pairs = set()
    for _, _, h, l_, cells, zh, top in cands:
        if want <= 0:
            break
        key = (min(h, l_), max(h, l_))
        if key in used_pairs:
            continue
        used_pairs.add(key)
        P.doors.append(Door(h, l_, cells[:6], zh, min(zh, 9999), zh, "overlook", None, top))
        taken.update(cells[:6])
        want -= 1
    # windows (brief 19 §4 «Окна»; Fable 11.10: several outlines and glass colours, not one rectangle): a wall
    # between two spaces - also one with a doorway, two cells clear of it - gets a glazed opening, sill 64 over the
    # higher floor; the outlines go round: box, arch, slit, band; each its own tint
    n = int(q.get("windows") or 0)
    outlines = ["box", "arch", "slit", "band"]
    rnd.shuffle(outlines)
    pairs = list(nb.items())
    rnd.shuffle(pairs)
    pairs.sort(key=lambda kv: (min(kv[0][0], kv[0][1]), max(kv[0][0], kv[0][1])) in paired)
    pairs = pairs + [kv for kv in pairs if len(kv[1]) >= 9]      # a second pass: long walls take a second window
    k_win = 0
    for (a, b), run in pairs:
        if n <= 0:
            break
        key = (min(a, b), max(a, b))
        if (key in used_pairs and len(run) < 9) or len(run) < 3:
            continue
        sa, sb = P.spaces[a], P.spaces[b]
        if sa.solid or sb.solid:
            continue
        kind = outlines[k_win % len(outlines)]
        width = {"box": 2, "arch": 1, "slit": 1, "band": 3}[kind]
        clear = [c for c in run[1:-1] if all(abs(c[0] - t[0]) + abs(c[1] - t[1]) >= 2 for t in taken)]
        if len(clear) < width:
            if kind == "band" and len(clear) >= 2:
                width = 2
            elif len(clear) >= 1:
                kind, width = "arch", 1
            else:
                continue
        mid = len(clear) // 2
        cells = clear[max(0, mid - width // 2): max(0, mid - width // 2) + width]
        za, zb = side_floor_at(sa, cells), side_floor_at(sb, cells)
        if len(cells) < width or za is None or zb is None or beside_water(P, cells):
            continue
        z0 = max(za, zb) + 64
        z1 = z0 + {"box": 64, "arch": 96, "slit": 96, "band": 48}[kind]
        if z1 > min(sa.ceil, sb.ceil) - 16:
            continue
        P.windows.append((cells, z0, z1, kind, rnd.randrange(7)))
        taken.update(cells)
        used_pairs.add(key)
        k_win += 1
        n -= 1
    if n > 0:
        # D5: said, not clipped in silence
        P.notes.append(say(f"окна: {len(P.windows)} из {len(P.windows) + n} - на стенах этой планировки больше нет "
                           f"места вдали от проходов",
                           f"windows: {len(P.windows)} of {len(P.windows) + n} - the walls of this plan have no more room "
                           f"away from the doorways"))


# --------------------------------------------------------------------------------------------- 4. the walk graph of the plan
def plan_graph(P: Plan):
    """Nodes: every floor cell and door cell (top height); edges: neighbours within a step, flights, drops, doors."""
    nodes = {}
    for s in P.spaces:
        if s.solid:
            continue
        for c, f in s.floor.items():
            nodes[c] = f
    door_of = {}
    for (cells, kind, z0, level) in P.liquids:
        if kind != "water":
            for c in cells:
                nodes.pop(c, None)
    # nobody walks through a column (brief 21: close_lines puts them on rooms' floors too)
    for (c, _z0, _z1) in P.pillars:
        nodes.pop(c, None)
    for i, d in enumerate(P.doors):
        for c in d.cells:
            if d.stair:
                nodes[c] = (d.z, "stair", d.stair[0], d.stair[1])
            else:
                nodes[c] = (d.z, "flat", 0, 0)
            door_of[c] = i
    edges = {c: [] for c in nodes}
    for c, f in nodes.items():
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            n = (c[0] + dx, c[1] + dy)
            g = nodes.get(n)
            if g is None:
                continue
            if dx and dy:
                # diagonals only inside one space's open floor
                if (c[0] + dx, c[1]) not in nodes or (c[0], c[1] + dy) not in nodes:
                    continue
            # a door cell joins only its two sides; a wall is not crossed elsewhere
            if (c in door_of) != (n in door_of) or (c in door_of and door_of[c] != door_of.get(n)):
                if not door_link(P, c, n, door_of):
                    continue
            elif P.owner.get(c) != P.owner.get(n) and c not in door_of and n not in door_of                     and frozenset((P.owner.get(c), P.owner.get(n))) not in P.joined:
                continue
            za, zb = edge_heights(f, g, dx, dy)
            dist = 1.4142 if dx and dy else 1.0
            t = dist * CELL / 300.0
            dz = zb - za
            if abs(dz) <= 20:
                edges[c].append((n, t * (1.15 if f[1] == "stair" or g[1] == "stair" else 1.0)))
            elif dz < -20:
                edges[c].append((n, t + math.sqrt(2 * -dz / 800.0)))     # a drop, one way
    # brief 21: a doorway of a room over a room - its cells on the upper layer, the neighbour's floor below them in
    # the keys (the arithmetic above never steps between the layers)
    for i, d in enumerate(P.doors):
        if not d.cross:
            continue
        for c in d.cells:
            if c not in edges:
                continue
            p = phys(c)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (p[0] + dx, p[1] + dy)
                g = nodes.get(n)
                if g is None or n not in edges or P.owner.get(n) not in (d.a, d.b) or n in door_of:
                    continue
                za, zb = edge_heights(nodes[c], g, dx, dy)
                if d.kind == "overlook" and za - zb > 20:
                    edges[c].append((n, CELL / 300.0 + math.sqrt(2 * (za - zb) / 800.0)))     # a drop, one way
                    continue
                if abs(zb - za) > 20:
                    continue
                t = CELL / 300.0 * (1.15 if nodes[c][1] == "stair" or g[1] == "stair" else 1.0)
                edges[c].append((n, t))
                edges[n].append((c, t))
    for (cells, zl, zh, bottom, top) in P.lifts:
        for b in bottom:
            for t_ in top:
                if b in edges and t_ in edges:
                    edges[b].append((t_, 0.4 + (zh - zl) / 220.0))
    # the PO 12.11: a nook raised 40 is jumped into (the map's walk jumps up to 44) - the plan's walk took it for a wall
    # and missed an armour in it 2.2 s from a gun (the test map of 12.11)
    if not OLD_MAJORS:
        for i_, d in enumerate(P.doors):
            if d.mover or d.stair or not (20 < d.z - min(d.za, d.zb) <= 44):
                continue
            low = d.a if d.za <= d.zb else d.b
            for c in d.cells:
                if c not in edges:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (c[0] + dx, c[1] + dy)
                    if n in edges and P.owner.get(n) == low and n not in door_of and abs(nodes[n][0] - min(d.za, d.zb)) <= 20:
                        edges[n].append((c, CELL / 300.0 + 0.2))
                        edges[c].append((n, CELL / 300.0))
    # the PO 12.11 (a dive, q2dm1's and q2dm5's): out of a deep pool up onto the floor at its surface
    for (cells, kind, z0, level) in P.liquids:
        if kind != "water" or level - z0 < 96:
            continue
        cs = set(cells)
        for c in cells:
            if c not in edges:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                g = nodes.get(n)
                if n in cs or g is None or n not in edges or not (level - 24 <= g[0] <= level + 48):
                    continue
                edges[c].append((n, (g[0] - z0) / 180.0 + 0.4))
    # the PO 12.11: under water one swims any way - up a tube's step, up a channel to the pool, along a tube (150 u/s)
    if not OLD_WATER:
        deep_ = {}
        for (cells, kind, z0, level) in P.liquids:
            if kind == "water" and level - z0 >= 64:
                for c in cells:
                    deep_[c] = level
        for c in deep_:
            if c not in edges:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n not in deep_ or n not in edges:
                    continue
                if (c in door_of) != (n in door_of) or (c in door_of and door_of[c] != door_of.get(n)):
                    if not door_link(P, c, n, door_of):
                        continue
                elif P.owner.get(c) != P.owner.get(n) and c not in door_of and n not in door_of \
                        and frozenset((P.owner.get(c), P.owner.get(n))) not in P.joined:
                    continue
                edges[c].append((n, CELL / 150.0 + abs(nodes[n][0] - nodes[c][0]) / 150.0))
        for i_, d in enumerate(P.doors):
            if d.kind != "swim":
                continue
            for c in d.cells:
                if c not in edges:
                    continue
                p = phys(c)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (p[0] + dx, p[1] + dy)
                    if n in edges and n in deep_ and P.owner.get(n) in (d.a, d.b) and n not in door_of:
                        t_ = CELL / 150.0 + abs(nodes[n][0] - nodes[c][0]) / 150.0
                        edges[c].append((n, t_))
                        edges[n].append((c, t_))
    # brief 34: a lift stopping on every storey - from any stop's doorway to any other's (the wait and the ride)
    for (_cells, stops, doors, _name) in P.trains:
        for i, a_ in enumerate(doors):
            for j, b_ in enumerate(doors):
                if i != j and a_ in edges and b_ in edges:
                    edges[a_].append((b_, TRAIN_WAIT + abs(stops[i] - stops[j]) / TRAIN_SPEED))
    for d in P.doors:
        if d.rj:
            for c in d.cells:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (c[0] + dx, c[1] + dy)
                    if n in edges and c in edges and nodes[n][0] < d.z - 64:
                        edges[n].append((c, 1.2))      # a rocket jump up to the sill
    for (a_, b_, t_) in P.air_edges:
        if a_ in edges and b_ in edges:
            edges[a_].append((b_, t_))
    for (src, dst, tt, *_rest) in P.pads:
        if src in edges and dst in edges:
            edges[src].append((dst, tt))
    for (a, b, da, db) in P.teleports:
        if a in edges and db in edges:
            edges[a].append((db, 0.1))
        if b in edges and da in edges:
            edges[b].append((da, 0.1))
    return nodes, edges


def door_link(P, c, n, door_of) -> bool:
    """A step between a door cell and a floor cell is allowed only to the door's own two spaces."""
    dc = c if c in door_of else n
    other = n if dc == c else c
    d = P.doors[door_of[dc]]
    o = P.owner.get(other)
    if other in door_of:
        return door_of[other] == door_of[dc]
    return o in (d.a, d.b)


def edge_heights(f, g, dx, dy):
    """The heights a player stands at leaving f and arriving on g across their common edge."""
    def at(fl, ex, ey):
        z, kind, sx, sy = fl
        if kind != "stair":
            return z
        # the stair rises 32 across the cell along (sx, sy); the edge toward (ex, ey)
        along = ex * sx + ey * sy
        return z + (RISE_PER_CELL if along > 0 else 0) if along else z + RISE_PER_CELL // 2
    return at(f, dx, dy), at(g, -dx, -dy)


def detour_est(edges, a, b):
    """The plan's form of the map's detour: the route a->b, a disc of 1.5 cells (96 u) closed round its half-way
    cell, the time round it over the route's own; None when a and b are not joined."""
    dist, prev = {a: 0.0}, {}
    pq = [(0.0, a)]
    while pq:
        d, c = heapq.heappop(pq)
        if d > dist.get(c, 1e18):
            continue
        if c == b:
            break
        for n, w in edges.get(c, ()):
            nd = d + w
            if nd < dist.get(n, 1e18):
                dist[n] = nd
                prev[n] = c
                heapq.heappush(pq, (nd, n))
    t = dist.get(b)
    if t is None or t <= 0:
        return None
    half = b
    while half in prev and dist[half] > t / 2:
        half = prev[half]
    hp = phys(half)
    blocked = {c for c in edges if abs(phys(c)[0] - hp[0]) <= 1 and abs(phys(c)[1] - hp[1]) <= 1
               and is_up(c) == is_up(half)}
    if a in blocked or b in blocked:
        return 1.0
    t2 = dijkstra(edges, a, blocked).get(b)
    return t2 / t if t2 is not None else 99.0


def dijkstra(edges, src, blocked=None):
    dist = {src: 0.0}
    pq = [(0.0, src)]
    while pq:
        d, c = heapq.heappop(pq)
        if d > dist.get(c, 1e18):
            continue
        for n, w in edges.get(c, ()):
            if blocked and n in blocked:
                continue
            nd = d + w
            if nd < dist.get(n, 1e18):
                dist[n] = nd
                heapq.heappush(pq, (nd, n))
    return dist


# --------------------------------------------------------------------------------------------- 4a. rooms over rooms
def stack_rooms(P: Plan, rnd: random.Random) -> None:
    """Brief 20 D5's rooms over rooms, done in brief 21: «a room whose floor is another's ceiling + a slab, reached by
    a flight or a lift» - people's maps stack a corridor or a room over a lower one. Below: a level room or corridor
    (no lift, pad, pool, drop or overlook in it). Over its rectangle the new room, SLAB over the lower one's lowered
    ceiling, 144 of headroom kept below and the lower room's doorways under the slab. A doorway joins it to a
    neighbour across their common wall: level when the neighbour stands that high, else up a flight of steps laid in
    the neighbour's floor in front of the doorway (the routes' own flights, `flight_in`) - at most five steps' cells.
    A second doorway where another neighbour stands at the new floor's height (a room on the way, not a dead end).
    One on a duel or an FFA-8 map and two on a larger one when the levels asked are four or more (brief 20 D5; the
    PO's «интересная геометрия»), none under four: people's 26 maps keep 0..64 % of their floor over or under
    another floor (median 35 %, 05.11), one pair of ours 3..18 %. Its doorways stay on the lower room's half of the
    map (a level shortcut across the halves undid them and the route asymmetry, 05.11 trials). Runs after the movers (none of them knows the upper layer) and before the places
    (items may go up there). On 40 duel plans of 05.11 a neighbour 176 over a level room stood beside it once - hence
    the flights."""
    q = P.params
    nlev = int(q.get("levels") or 4)
    want = q.get("rooms_over")
    want = int(want) if want is not None else (0 if nlev < 4 else 1 if q["class"] in ("duel", "ffa8") else 2)
    P.metrics["stacked_asked"] = want
    P.metrics["stacked_cells"] = 0
    P.metrics["stacked_rooms"] = 0
    if want <= 0:
        return
    live = [s for s in P.spaces if not s.solid]
    door_cells = {c for d in P.doors for c in d.cells}
    busy = ({c for (plat, *_r) in P.lifts for c in plat} | {c for p in P.pads for c in p[:2]}
            | {c for t in P.teleports for c in t} | {c for (cells, *_r) in P.liquids for c in cells}
            | {c for (cs, _b, _sid) in P.pits for c in cs} | {c for (*_r, front) in P.ladders for c in front})
    glass = {c: (z0, z1) for (cells, z0, z1, *_w) in P.windows for c in cells}

    def top_of(d):
        return d.top or (d.z + 32 + DOOR_H if d.stair else d.z + DOOR_H)
    found = []
    for R in live:
        # a room, a corridor or a hall of up to 120 cells under a roof (05.11: rooms and corridors alone gave 29 of 68
        # duel plans a room over a room once the halves kept it on one side)
        if R.kind not in ("room", "corridor", "hall") or R.sky or R.atrium or R.wet:
            continue
        r = R.rect
        cells = list(r.cells())
        if len(cells) < 6 or min(r.w, r.h) < 2 or (R.kind == "hall" and len(cells) > 120):
            continue
        if any(c in busy for c in R.floor):
            continue
        rd = [d for d in P.doors if R.id in (d.a, d.b)]
        # its doorways of every kind stay under the slab (a drop's sill, an overlook's top: top_of); a lift's door
        # rises past it
        if any(d.kind == "lift" for d in rd):
            continue
        # the new floor: the lower room keeps 144 over its highest floor (a terrace, a flight's top - 05.11: level rooms
        # alone left 6 of 10 duel plans without a room over a room) and its doorways under the slab
        z_min = max([max(floor_top(f) for f in R.floor.values()) + 144 + SLAB] + [top_of(d) + SLAB for d in rd])
        z_min = -(-z_min // RISE_PER_CELL) * RISE_PER_CELL
        runs = {}
        for c in cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                w = (c[0] + dx, c[1] + dy)
                if R.has(w) or P.owner.get(w) is not None or w in door_cells:
                    continue
                n = (w[0] + dx, w[1] + dy)
                o = P.owner.get(n)
                if o is None or o == R.id:
                    continue
                f = P.spaces[o].floor.get(n)
                if f is None or f[1] != "flat" or n in busy or n in door_cells:
                    continue
                runs.setdefault((o, f[0], dx, dy), []).append(w)
        for (o, zn, dx, dy), ws in runs.items():
            N = P.spaces[o]
            if N.solid:
                continue
            z = zn if zn >= z_min else z_min
            # a flight of up to eight steps' cells in the neighbour (05.11: at six, 1146 runs of 100 duel plans stopped
            # here - the slab over a room's doorways stands 160 over its floor, the neighbours mostly 0..128)
            if z - R.base > 512 or z - zn > 8 * RISE_PER_CELL:
                continue
            # the neighbour's ceiling is raised over the doorway when it is lower (a room is made taller, never
            # lower; 05.11: kept as a filter, it left 7 of 39 duel plans a room over a room) - a court's sky too: it
            # is its ceiling (05.11: a flight under a court's sky left 48 over its top step, the railgun up there unreached)
            if z + DOOR_H + 48 > N.base + 512:
                continue
            # ... by 96 at most: whole halls raised by 150 and more took the styled duel's headroom to 294..302
            # (people's median 112..288)
            if z + DOOR_H + 64 - N.ceil > 128:
                continue
            ws = sorted(set(ws))
            axis = 1 if dx else 0
            for k in range(len(ws) - 1):
                a, b = ws[k], ws[k + 1]
                if a[1 - axis] == b[1 - axis] and b[axis] == a[axis] + 1:
                    if any(g in glass and glass[g][1] > z - SLAB for g in (a, b)):
                        continue
                    found.append((z - zn, rnd.random(), R, o, zn, z, (dx, dy), [a, b]))
    # level doorways first, then the larger lower rooms (a bigger room over a room), then the shortest flights
    found.sort(key=lambda t: (t[0] > 0, -t[2].rect.w * t[2].rect.h, t[0], t[1]))
    made = []

    def doorway(uid, o, zn, z, dxy, run, loop=False):
        """The doorway from neighbour o (floor zn) up to the room over the lower one (floor z): level, two steps in
        the doorway, or a flight laid in the neighbour's floor in front of it. None when no flight fits."""
        N = P.spaces[o]
        upd = (-dxy[0], -dxy[1])                  # from the neighbour toward the room over the lower one
        d = Door(o, uid, list(run), za=zn, zb=z, z=z, kind="door", cross=True, loop=loop)
        rise = z - zn
        if rise > 0:
            n_ = -(-rise // RISE_PER_CELL)
            if n_ == 1:
                d.z, d.stair = zn, upd
            else:
                saved = dict(N.floor)
                if not flight_in(P, d, N, n_ - 1, zn, upd, sunk=False):
                    N.floor = saved
                    return None
                d.z, d.stair = z - RISE_PER_CELL, upd
        if N.ceil < top_of(d) + 32:
            N.ceil = top_of(d) + 32
        return d
    for (_rise, _r, R, o, zn, z, dxy, run) in found:
        if len(made) >= want:
            break
        if any(R.id in (m_[0].id, m_[1]) or o in (m_[0].id, m_[1]) for m_ in made):
            continue
        if set(run) & door_cells:
            continue
        if P.half and P.half.get(o) != P.half.get(R.id):
            continue                              # the halves keep their two crossings (brief 19 §6)
        uid = len(P.spaces)
        ceils = {s_.id: s_.ceil for s_ in P.spaces}
        d = doorway(uid, o, zn, z, dxy, run)
        if d is None:
            continue
        # brief 21 D2: the room up there has a second way out before it is made - another doorway (level or up a
        # flight), else an overlook onto a lower neighbour one drops from (q2dm1's and ztn2dm3's galleries look into
        # their halls); with neither it is not made (the PO, 05.11: a room 2 x 9 with one doorway and a health at its
        # end, over a corridor with one doorway)
        second, said2 = None, ""
        for (_r2, _rr2, R2, o2, zn2, _z2, dxy2, run2) in found:
            if R2 is not R or zn2 > z or set(run2) & door_cells or set(run2) & set(run):
                continue
            # the same neighbour by another wall, or three cells along the same one: a gallery with two ways up
            if o2 == o and dxy2 == dxy and min(abs(a_[0] - b_[0]) + abs(a_[1] - b_[1]) for a_ in run for b_ in run2) < 3:
                continue
            if P.half and P.half.get(o2) != P.half.get(R.id):
                continue
            if z - zn2 <= 8 * RISE_PER_CELL:
                d2 = doorway(uid, o2, zn2, z, dxy2, run2, loop=True)
                if d2 is not None:
                    second = d2
                    said2 = f", второй вход из {o2}" + (f" по ступеням (+{z - zn2})" if z > zn2 else "")
                    break
            if 96 <= z - zn2 <= 288:
                N2 = P.spaces[o2]
                top = z + 112
                if N2.ceil < top + 16:
                    if top + 16 - N2.ceil > 128:
                        continue
                    N2.ceil = top + 16
                second = Door(uid, o2, list(run2), za=z, zb=zn2, z=z, kind="overlook", top=top, cross=True)
                said2 = f", открыта на {o2} ниже на {z - zn2}"
                break
        if second is None:
            for (sp_id, c, f0) in d.laid:
                P.spaces[sp_id].floor[c] = f0
            for s_ in P.spaces:
                if s_.id in ceils:
                    s_.ceil = ceils[s_.id]
            continue
        U = Space(uid, "room", Rect(R.rect.x0, R.rect.y0 + UP, R.rect.x1, R.rect.y1 + UP), base=z)
        U.floor = {up(c): (z, "flat", 0, 0) for c in R.rect.cells()}
        U.ceil = z + rnd.choice((160, 176))
        U.over = R.id
        R.ceil = min(R.ceil, z - SLAB)
        R.under = U.id
        P.spaces.append(U)
        for c in U.floor:
            P.owner[c] = U.id
        if R.id in P.half:
            P.half[U.id] = P.half[R.id]
        d.cells = [up(w) for w in run]
        P.doors.append(d)
        door_cells.update(run)
        made.append((R, o, U))
        said = f"вход из {o}" + (f" по ступеням (+{z - zn})" if z > zn else "") + said2
        second.cells = [up(w) for w in second.cells]
        P.doors.append(second)
        door_cells.update(phys(c) for c in second.cells)
        P.reasons.append(("room over a room", f"комната над комнатой {R.id}: пол {z}, потолок нижней {R.ceil}, {said}"))
    P.metrics["stacked_rooms"] = len(made)
    P.metrics["stacked_cells"] = sum(len(U.floor) for *_r, U in made)


# --------------------------------------------------------------------------------------------- 4b. no plain box
def plain_spaces(P: Plan) -> list:
    """Brief 21 D5: the halls and rooms that are closed boxes - a level floor, no window, no overlook, no bay, nothing
    over or under them, no arcade: what the PO walked through on 05.11 («голые стены, аптечка в конце»)."""
    wins = {c for (cells, *_w) in P.windows for c in cells}
    over = {d.a for d in P.doors if d.kind == "overlook"} | {d.b for d in P.doors if d.kind == "overlook"}
    out = []
    for s in P.spaces:
        if s.solid or s.kind not in ("hall", "room") or not s.floor:
            continue
        if s.pattern != "flat" or s.extra or s.id in over or getattr(s, "over", None) is not None \
                or getattr(s, "under", None) is not None or getattr(s, "arcade", False):
            continue
        if any((phys(c)[0] + dx, phys(c)[1] + dy) in wins for c in s.floor for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            continue
        if len({f[0] for f in s.floor.values()}) > 1:
            continue
        out.append(s)
    return out


def show_more(P: Plan, rnd: random.Random) -> None:
    """Brief 21 D5, «every space shows another one»: a plain hall or room gets a window to a neighbour across a wall
    clear of its doorways (sill 64 over the higher floor), else - a hall nine cells long and more - an arcade: columns
    one cell in from its long wall every other cell, a side aisle (people's halls: q2dm1's, q2dm6's colonnades)."""
    nb = neighbours(P)
    taken = {c for d in P.doors for c in d.cells} | {c for (cells, *_w) in P.windows for c in cells}
    for s in plain_spaces(P):
        done = False
        pairs = [(k, run) for k, run in nb.items() if s.id in k and len(run) >= 3]
        rnd.shuffle(pairs)
        for (a, b), run in pairs:
            o = P.spaces[b if a == s.id else a]
            if o.solid:
                continue
            # beside a doorway too (a wall of four cells with a doorway of two left no cell two away from it - 21 of 34
            # tries on duel plans of 05.11)
            clear = [c for c in run[1:-1] if c not in taken]
            if len(clear) < 1:
                continue
            kind = rnd.choice(("box", "arch", "slit")) if len(clear) >= 2 else rnd.choice(("arch", "slit"))
            width = {"box": 2, "arch": 1, "slit": 1}[kind]
            mid = len(clear) // 2
            cells = clear[max(0, mid - width // 2): max(0, mid - width // 2) + width]
            za, zb = side_floor_at(s, cells), side_floor_at(o, cells)
            if len(cells) < width or za is None or zb is None or beside_water(P, cells):
                continue
            z0 = max(za, zb) + 64
            z1 = z0 + {"box": 64, "arch": 96, "slit": 96}[kind]
            if z1 > min(s.ceil, o.ceil) - 16:
                kind, z1 = "box", z0 + 48
                if z1 > min(s.ceil, o.ceil) - 16:
                    continue
            P.windows.append((cells, z0, z1, kind, rnd.randrange(7)))
            taken.update(cells)
            P.metrics["windows_shown"] = int(P.metrics.get("windows_shown") or 0) + 1
            done = True
            break
        if done or s.kind != "hall":
            continue
        r = s.rect
        long_x = r.w >= r.h
        if max(r.w, r.h) < 9 or min(r.w, r.h) < 5:
            continue
        held = ({c for (_cls, c, _z, _n) in P.items} | set(P.no_items) | {c for d in P.doors for c in d.cells}
                | {c for (c, *_r) in P.pillars})
        near_door = {(c[0] + dx, c[1] + dy) for d in P.doors for c in d.cells for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        for side in (0, 1):
            if long_x:
                line = [(x, r.y0 + 1 if side == 0 else r.y1 - 2) for x in range(r.x0 + 2, r.x1 - 2, 2)]
            else:
                line = [(r.x0 + 1 if side == 0 else r.x1 - 2, y) for y in range(r.y0 + 2, r.y1 - 2, 2)]
            if any(c not in s.floor or s.floor[c][1] != "flat" or c in held or c in near_door for c in line):
                continue
            for c in line:
                P.pillars.append((c, s.floor[c][0], s.ceil))
            if cut_off_any(P):
                del P.pillars[-len(line):]
                continue
            s.arcade = True
            P.metrics["arcades"] = int(P.metrics.get("arcades") or 0) + 1
            P.reasons.append(("arcade", f"колоннада в зале {s.id}: {len(line)} колонн вдоль стены"))
            break
    P.metrics["plain_rooms"] = len(plain_spaces(P))


def cut_off_any(P: Plan) -> bool:
    """Before the places: is any floor cut off from the rest (both ways), from the largest space's first cell."""
    nodes, edges = plan_graph(P)
    if not nodes:
        return True
    big = max((s for s in P.spaces if not s.solid and s.floor), key=lambda s: len(s.floor))
    start = next((c for c in big.floor if c in nodes), None)
    if start is None:
        return True
    there = dijkstra(edges, start)
    rev = {}
    for c, es in edges.items():
        for n, w in es:
            rev.setdefault(n, []).append((c, w))
    back = dijkstra(rev, start)
    return any(f[1] == "flat" and P.owner.get(c) is not None and c not in P.no_items and (c not in there or c not in back)
               for c, f in nodes.items())


# --------------------------------------------------------------------------------------------- 5. the places
MAJOR_W = ["weapon_railgun", "weapon_rocketlauncher", "weapon_chaingun", "weapon_grenadelauncher",
           "weapon_hyperblaster", "weapon_supershotgun", "weapon_machinegun", "weapon_bfg", "weapon_shotgun"]


def places(P: Plan, rnd: random.Random) -> None:
    """Stack items far apart on a clock, the key gun on a ledge with its armour near, the other guns spread, spawns
    near a gun and near each other, small health in many rooms, ammo by its gun."""
    q = P.params
    nodes, edges = plan_graph(P)
    if not nodes:
        P.failed = "no floor"
        return
    # the main component
    start = next(iter(nodes))
    comp = dijkstra(edges, start)
    if len(comp) < len(nodes) * 0.6:
        # try from the largest space
        big = max((s for s in P.spaces if not s.solid), key=lambda s: s.rect.w * s.rect.h)
        start = next(iter(big.floor))
        comp = dijkstra(edges, start)
    # back-reachability: every place one can stand must lead back (no trap)
    rev = {}
    for c, es in edges.items():
        for n, w in es:
            rev.setdefault(n, []).append((c, w))
    back = dijkstra(rev, start)
    good = [c for c in comp if c in back and nodes[c][1] == "flat" and P.owner.get(c) is not None]
    if len(good) < 40:
        P.failed = "too little walkable floor joined up"
        return
    goodset = set(good)
    P.metrics["stranded_cells"] = sum(1 for c in nodes if nodes[c][1] == "flat" and P.owner.get(c) is not None
                                      and c not in goodset and c not in P.no_items)
    # brief 20 D2: a plan that strands any floor is refused, not marked down. The causes found on six seeds (04.11):
    # a space left with no doorway at all, the lower floor of a balcony or pit hall with no flight to its own doors,
    # a part reached only by a drop or a lift up with no way back - each is a room a player falls into or never sees
    if P.metrics["stranded_cells"]:
        unreached = sum(1 for c in nodes if nodes[c][1] == "flat" and P.owner.get(c) is not None
                        and c not in comp and c not in P.no_items)
        P.failed = say(f"отрезанный пол: {P.metrics['stranded_cells']} клеток ({unreached} недостижимы, остальные без пути назад)",
                       f"floor cut off: {P.metrics['stranded_cells']} cells ({unreached} unreachable, the rest with no way back)")
        return
    base = min(nodes[c][0] for c in good)
    zs = sorted(nodes[c][0] for c in good)
    lowband = zs[len(zs) // 10]

    def high(c):
        return nodes[c][0] >= lowband + 64

    used: set = set()
    times_cache = {}

    def times(c):
        if c not in times_cache:
            times_cache[c] = dijkstra(edges, c)
        return times_cache[c]

    def free(c, r=1):
        if c not in goodset or c in P.no_items:
            return False
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if (c[0] + dx, c[1] + dy) in used:
                    return False
        # not in front of a door (a door cell next to it)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if n in nodes and P.owner.get(n) is None:
                return False
        return True

    def put(cls, c, note=""):
        used.add(c)
        P.items.append((cls, c, nodes[c][0], note))

    def apart(cls, c):
        return majors_apart(P, cls, c, nodes[c][0], times)

    cands = [c for c in good if free(c)]
    rnd.shuffle(cands)
    stack = STACK_SETS.get(q["stack"], STACK_SETS["ra_mh"]) if isinstance(q["stack"], str) else dict(q["stack"])
    mech = set(q.get("mechanics") or [])
    # 0. the mechanics that need a room with one way in hold their item first (brief 19 §6)
    spots, missing = mech_spots(P, q, mech, nodes, free)
    P.metrics["mech_missing_spots"] = missing
    # 1. the two stack items of the clock as far apart as the map allows within 5..9 s (duel)
    first = "item_armor_body" if stack.get("item_armor_body") else (
        "item_health_mega" if stack.get("item_health_mega") else "item_quad" if stack.get("item_quad") else "item_armor_combat")
    second = "item_health_mega" if first == "item_armor_body" and stack.get("item_health_mega") else "item_armor_combat"
    P.metrics["stack_pair"] = [first, second]
    # brief 22 D3: the powerups' nooks put a pair item two cells back behind its doorway (0.5..1.3 s more each, three
    # trial duels 06.11) - the pair is aimed that much shorter for each of it that will go into a nook
    access = q.get("powerup_access") or "mixed"
    present = [c_ for c_ in POWERUPS if stack.get(c_)]
    nooked = set(present) if access in ("medium", "hard") else set(present[:2]) if access == "mixed" else set()
    nook_allow = 0.6 * sum(1 for c_ in (first, second) if c_ in nooked)
    P.metrics["stack_nook_allow_s"] = round(nook_allow, 2)
    halves = bool(P.half) and ("halves" in mech or q.get("mode") == "tdm")

    def half_of(c):
        return P.half.get(P.owner.get(c))
    # a major item stands where two ways meet at least (brief 19 §6 clock: each with two exits; D7: dead-end majors
    # few): spaces with two doorways or more
    deg_ = {}
    for d in P.doors:
        deg_[d.a] = deg_.get(d.a, 0) + 1
        deg_[d.b] = deg_.get(d.b, 0) + 1

    exits_cache = {}

    def exits(c):
        """The groups of places 1.4..1.6 s from c (the map's measure: a major's ways out)."""
        if c not in exits_cache:
            tc = times(c)
            ring = {x for x, t_ in tc.items() if 1.4 <= t_ <= 1.6 and x in nodes}
            groups = 0
            while ring:
                groups += 1
                todo = [ring.pop()]
                while todo:
                    x = todo.pop()
                    for dx in (-2, -1, 0, 1, 2):
                        for dy in (-2, -1, 0, 1, 2):
                            y_ = (x[0] + dx, x[1] + dy)
                            if y_ in ring and abs(nodes[y_][0] - nodes[x][0]) <= 64:
                                ring.discard(y_)
                                todo.append(y_)
            exits_cache[c] = groups
        return exits_cache[c]

    def two_ways(c):
        return deg_.get(P.owner.get(c), 0) >= 2 and exits(c) >= 2
    hi_c = [c for c in cands if high(c) and two_ways(c)] or [c for c in cands if high(c)] or cands
    weapons0 = {k: v for k, v in dict(q["weapons"]).items() if v}
    key0 = "weapon_railgun" if weapons0.get("weapon_railgun") else next(iter(weapons0), None)
    pinned = {}
    if spots.get("dead_end"):
        pinned["item_health_mega" if stack.get("item_health_mega") else first] = (spots["dead_end"][0],
                                                                                 "dead-end stack: drop in, RJ out")
    if spots.get("ladder"):
        cls_ = "item_armor_body" if stack.get("item_armor_body") and "item_armor_body" not in pinned else "item_armor_combat"
        pinned[cls_] = (spots["ladder"][0], "ladder under a held item")
    if spots.get("lift") and key0:
        cls_ = key0 if key0 not in pinned else "weapon_rocketlauncher"
        pinned[cls_] = (spots["lift"][0], "lift as exposure: the only way up")
    best = None
    a_list = [pinned[first][0]] if first in pinned else hi_c[:80]
    b_list = [pinned[second][0]] if second in pinned else hi_c
    for a in a_list:
        ta = times(a)
        for b in b_list:
            if b == a or b not in ta:
                continue
            if q.get("mode") == "tdm" and halves and half_of(a) == half_of(b):
                continue
            t = ta[b]
            target = (5.0, 9.0) if "clock" in mech else (3.0, 12.0)
            # the compiled map walks about 8 % quicker than the plan's cells (r9/r10, 04.11: 7.0 -> 6.3..6.6): aim
            # half a second over the band's middle
            sc = -abs(t + nook_allow - (target[0] + target[1]) / 2 - 0.5) + (0.5 if P.owner.get(a) != P.owner.get(b) else 0)
            if not OLD_MAJORS and math.dist(_item_at(a, nodes[a][0]), _item_at(b, nodes[b][0])) < majors_need(first, second)[1]:
                sc -= 50.0          # the PO 12.11: the pair seen side by side through a wall or a floor
            if best is None or sc > best[0]:
                best = (sc, a, b, t)
    if not best:
        P.failed = "no place for the stack"
        return
    _, a, b, t = best
    put(first, a, pinned[first][1] if first in pinned else f"stack, {t:.1f} s from its pair")
    for cls_, (c_, note_) in pinned.items():
        if cls_ not in (first, second):
            put(cls_, c_, note_)
    if q.get("mode") == "tdm" and halves:
        # TDM: the stack in two mirrored halves - each base holds the same set (brief 19 §4 «Режим»)
        put(first, b, "stack of the other base")
        for cls, n in stack.items():
            if cls == first:
                n -= 1
            for h in (0, 1):
                for _ in range(max(0, n)):
                    c = farthest(cands, used, times, free, prefer=lambda c, h=h: half_of(c) == h and high(c),
                                 ok=lambda c, cls=cls: apart(cls, c))
                    if c and half_of(c) == h:
                        put(cls, c, f"stack of base {h + 1}")
    else:
        put(second, b, pinned[second][1] if second in pinned else "stack")
        for cls, n in stack.items():
            if cls in (first, second):
                n -= 1
            if cls in pinned and cls not in (first, second):
                n -= 1
            if cls == "item_adrenaline":
                continue            # tucked low, after the guns (brief 19 §6 «adrenaline tucked»)
            for _ in range(max(0, n)):
                c = farthest(cands, used, times, free, prefer=lambda c: high(c) and two_ways(c),
                             ok=lambda c, cls=cls: apart(cls, c))
                if c:
                    put(cls, c, "stack")
    # 2. the key gun on a ledge with an armour within 2 s
    weapons = {k: v for k, v in dict(q["weapons"]).items() if v}
    for cls_ in pinned:
        if cls_ in weapons:
            weapons[cls_] -= 1          # already placed by its mechanic
    key = "weapon_railgun" if weapons.get("weapon_railgun") else next(iter(weapons), None)
    if "three_approaches" in mech and weapons.get("weapon_chaingun"):
        key = "weapon_chaingun"
    if key0 in pinned and "key_gun_ledge" in mech:
        # the key gun is on the lift's ledge: its armour beside it (3.65; the PO 12.11 - «рельсу класть в шаге от двух
        # арморов - глупо»: no armour by a gun now)
        tk = times(pinned[key0][0])
        near = [c for c in cands if free(c) and 0.6 <= tk.get(c, 99) <= 2.0]
        if near and OLD_MAJORS:
            put("item_armor_combat" if "item_armor_combat" not in stack else "item_armor_jacket", near[0],
                "armour by the key gun")
        key = None
    if key and weapons.get(key, 0) > 0:
        ledge = [c for c in cands if free(c) and high(c)]
        if "key_gun_ledge" in mech:
            # 128 over the floor AROUND it (brief 19 §6): a floor that much lower within six cells
            def over_around(c):
                z = nodes[c][0]
                return z - min((nodes[n][0] for n in nodes if abs(n[0] - c[0]) <= 6 and abs(n[1] - c[1]) <= 6
                                and nodes[n][1] == "flat"), default=z)
            ledge = [c for c in ledge if over_around(c) >= 128] or [c for c in ledge if nodes[c][0] >= lowband + 128] or ledge
        if halves and "halves" in mech and q.get("mode") != "tdm":
            # the key gun in the other half from the stack, as far from it as that half allows (brief 19 §6: >= 7 s)
            other = [c for c in ledge if half_of(c) is not None and half_of(c) != half_of(a)]
            ledge = other or ledge
            ta_ = times(a)
            ledge.sort(key=lambda c: -min(ta_.get(c, 0), 9.0))
        if "three_approaches" in mech:
            # the key item where three ways meet: a space with three doors or more
            deg = {}
            for d in P.doors:
                deg[d.a] = deg.get(d.a, 0) + 1
                deg[d.b] = deg.get(d.b, 0) + 1
            three = [c for c in ledge if deg.get(P.owner.get(c), 0) >= 3] or \
                    [c for c in cands if free(c) and deg.get(P.owner.get(c), 0) >= 3]
            ledge = three or ledge
        if halves and "halves" in mech and q.get("mode") != "tdm":
            # brief 21: the halves' order first (as far from the stack as 9 s), then away from the rest - the sort
            # below alone undid it (RG<->RA 6.3 s median on the duel plans of 05.11, 7 asked of the map)
            ta_ = times(a)
            ledge.sort(key=lambda c: (-min(ta_.get(c, 0), 9.0), -min((times(c).get(u, 99) for u in used), default=0)))
        else:
            ledge.sort(key=lambda c: -min(times(c).get(u, 99) for u in used) if used else 0)
        # the PO 12.11: the key gun apart from every major placed, when a ledge allows it (the order kept)
        ledge = [c for c in ledge if apart(key, c)] or ledge
        if ledge:
            kc = ledge[0]
            put(key, kc, "key gun on a ledge" if "key_gun_ledge" in mech else "key gun")
            weapons[key] -= 1
            if "key_gun_ledge" in mech and OLD_MAJORS:
                # 3.65: an armour by the key gun - the PO 12.11 «туже рельсу класть в шаге от двух арморов - глупо»
                tk = times(kc)
                near = [c for c in cands if free(c) and 0.6 <= tk.get(c, 99) <= 2.0]
                if near:
                    put("item_armor_combat" if "item_armor_combat" not in stack else "item_armor_jacket",
                        near[0], "armour by the key gun")
    # 3a. route asymmetry (brief 19 §6, q2duel5: 6.3 s up, 2.1 s down): a gun on the ledge an overlook drops from
    if "asymmetry" in mech:
        for d in P.doors:
            if d.kind != "overlook":
                continue
            hi_s = d.a if door_side_floor(P, d, P.spaces[d.a]) >= d.z - 8 else d.b
            ledge_c = sorted((c for c in P.spaces[hi_s].floor if c in nodes and free(c) and nodes[c][0] >= d.z - 8),
                             key=lambda c: min(abs(c[0] - x[0]) + abs(c[1] - x[1]) for x in d.cells))[:6]
            gun = next((g_ for g_ in ("weapon_hyperblaster", "weapon_grenadelauncher", "weapon_supershotgun",
                                       "weapon_rocketlauncher") if weapons.get(g_, 0) > 0), None)
            if gun:
                ledge_c = [c for c in ledge_c if apart(gun, c)]     # the PO 12.11: apart, or by another overlook
            if ledge_c and gun:
                put(gun, ledge_c[0], "asymmetry: down by the ledge, up the long way")
                weapons[gun] -= 1
                break
    # 3. the other guns spread: each as far from what is placed as can be
    for cls in MAJOR_W:
        for _ in range(weapons.get(cls, 0)):
            at_h = rnd.random() < q["items_at_height"]
            # the others low: the share at height follows the asked one (brief 21 - with the rooms over rooms most
            # «anywhere» places were high, majors at height came out 100 % for 67 % asked)
            c = farthest(cands, used, times, free, prefer=(lambda c: high(c) and two_ways(c)) if at_h
                         else (lambda c: not high(c) and two_ways(c)), ok=lambda c, cls=cls: apart(cls, c))
            if c:
                put(cls, c, "")
    # 4. spawns: each within 2.5 s of a gun, spawns 1.5 s apart at least, two thirds at height
    guns = [c for (cls, c, z, n) in P.items if cls.startswith("weapon_")]
    want = int(q["spawns"])
    # nor beside a lift's plat (the PO's maps from scratch: six spawns stood in a lift's column - the pickups' gate
    # excused them as the donor's own until 3.67)
    by_plat = {(c[0] + dx, c[1] + dy) for (pl, *_r) in P.lifts for c in map(phys, pl) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    by_plat |= {(c[0] + dx, c[1] + dy) for (cs, *_r) in getattr(P, "trains", []) for c in map(phys, cs)
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    sp_c = [c for c in cands if free(c, 1) and (OLD_WATER or phys(c) not in by_plat)]
    # two thirds at height (brief 19 §4): the high cells first, until two thirds are taken; nearer the stack first
    stack_at = [c for (cls, c, z, n) in P.items if cls in MAJOR_ITEMS]

    def to_stack(c):
        tc = times(c)
        return min((tc.get(s_, 99) for s_ in stack_at), default=0)
    sp_c.sort(key=lambda c: (not high(c), to_stack(c) > 3.2, rnd.random()))
    picked = []

    movers_at = [x for (a_, b_, da_, db_) in P.teleports for x in (a_, b_, da_, db_)] + \
        [x for (a_, t_, *_r) in P.pads for x in (a_, t_)]

    def near_seen(c):
        """Another spawn within 320 u, in any space (brief 19 §4: none in another's sight under 300 u). Sight alone was
        not enough: the dressing's remodels open walls, and two spawns 260 u apart through a wall saw each other on the
        finished map (04.11)."""
        pc = phys(c)
        for p_ in picked:
            pp = phys(p_)
            if math.dist((pc[0] * CELL, pc[1] * CELL, nodes[c][0]), (pp[0] * CELL, pp[1] * CELL, nodes[p_][0])) < 320:
                return True
        # nor beside a teleporter, its exit or a jump pad (one spawns into another's arrival); brief 35: nor a third
        # plate - spawn points and teleporter exits look alike - within PLATES_NEAR (his mg_new_91126: five in a row)
        if OLD_MOVER_RULES:
            return any(max(abs(pc[0] - m_[0]), abs(pc[1] - m_[1])) < 4 for m_ in movers_at)
        return not spot_ok(P, c, "spawn", mover_marks(P, spawns=picked), plates_near=plates_r[0])
    plates_r = [PLATES_NEAR]
    for c in sp_c:
        if len(picked) >= want:
            break
        if high(c) and sum(1 for p_ in picked if high(p_)) >= (2 * want + 2) // 3:
            continue
        tc = times(c)
        if not guns or min(tc.get(g, 99) for g in guns) > 2.6:
            continue
        if any(tc.get(p_, 99) < 1.2 for p_ in picked) or near_seen(c):
            continue
        # the check holds 4 s on the finished map, which walks a little slower than the plan where its trims stand
        # (05.11: 4.04 on a duel planned under 4) - the plan keeps 3.4
        if picked and min(tc.get(p_, 99) for p_ in picked) > 3.4 and "spawn_pressure" in mech:
            continue
        picked.append(c)
        used.add(c)
    # brief 35: the spawns asked are never cut - the plates' radius gives, step by step
    for r_ in (PLATES_STEPS if not OLD_MOVER_RULES else (PLATES_NEAR,)):
        if len(picked) >= want:
            break
        plates_r[0] = r_
        for c in sp_c:
            if len(picked) >= want:
                break
            if c in used:
                continue
            tc = times(c)
            if any(tc.get(p_, 99) < 1.0 for p_ in picked) or near_seen(c):
                continue
            if picked and min(tc.get(p_, 99) for p_ in picked) > 3.6 and "spawn_pressure" in mech:
                continue
            picked.append(c)
            used.add(c)
    P.metrics["plates_near"] = plates_r[0]
    for c in picked:
        P.spawns.append((c, nodes[c][0], facing(P, c)))
    # 5. ammo by its gun, small health in many rooms, shards in corridors
    for (cls, c, z, n) in list(P.items):
        if cls in AMMO_OF:
            tc = times(c)
            near = [x for x in cands if free(x, 0) and 0.4 <= tc.get(x, 99) <= 2.5]
            if near:
                put(AMMO_OF[cls], rnd.choice(near), "")
    rooms_done = set()
    majors_at = [c for (cls, c, z, n) in P.items if cls in MAJOR_W or cls in MAJOR_ITEMS]
    n_health = int(round(q["spawns"] * float(q.get("health_per_spawn") or 1.3)))
    for c in cands:
        if n_health <= 0:
            break
        o = P.owner.get(c)
        if o in rooms_done or not free(c, 1):
            continue
        # none within 2 s of a major (brief 19 §6 «много мелких аптечек»: where a wounded man goes)
        if "small_health" in mech and any(times(m_).get(c, 99) < 2.0 for m_ in majors_at):
            continue
        rooms_done.add(o)
        put("item_health_large" if rnd.random() < 0.35 else "item_health", c, "small health")
        n_health -= 1
    for c in cands:
        if n_health <= 0:
            break
        if not free(c, 2) or ("small_health" in mech and any(times(m_).get(c, 99) < 2.0 for m_ in majors_at)):
            continue
        put("item_health", c, "small health")
        n_health -= 1
    shards = int(q.get("shards") or 0)
    for pass_ in (0, 1):
        for c in cands:
            if shards <= 0:
                break
            if (pass_ or P.spaces[P.owner[c]].kind == "corridor") and free(c, 1):
                put("item_armor_shard", c, "")
                shards -= 1
    extra_ammo = max(0, int(q["spawns"] * float(q.get("ammo_per_spawn") or 2.5)) - sum(
        1 for (cls, *_r) in P.items if cls.startswith("ammo_")))
    for c in cands:
        if extra_ammo <= 0:
            break
        if free(c, 2):
            put(rnd.choice(["ammo_shells", "ammo_bullets", "ammo_rockets", "ammo_grenades", "ammo_cells",
                            "ammo_slugs"]), c, "")
            extra_ammo -= 1
    # the adrenaline tucked: the lowest level, 3 s or more from every major (brief 19 §6)
    for _ in range(int(stack.get("item_adrenaline") or 0)):
        majors_at = [c for (cls, c, z, n) in P.items if cls in MAJOR_W or cls in MAJOR_ITEMS]
        low = [c for c in cands if free(c) and nodes[c][0] <= lowband and all(times(m_).get(c, 99) >= 3.0 for m_ in majors_at)
               and apart("item_adrenaline", c)]
        low = low or [c for c in cands if free(c) and nodes[c][0] <= lowband]
        if low:
            put("item_adrenaline", low[0], "adrenaline tucked low")
    mech_places(P, q, mech, nodes, times, cands, free, put, used)
    P.metrics["base"] = base
    P.metrics["stack_apart_s"] = round(t, 2)


def mech_spots(P: Plan, q: dict, mech: set, nodes, free) -> tuple[dict, list]:
    """Where the mechanics that need a room with one way in put their item: the dead end under the drop, the ledge
    only the lift reaches, the ledge over the ladder - free cells, nearest the room's middle first. What could not be
    had on this seed is said (D5), and the score prefers a seed that has it."""
    spots, missing = {}, []
    deg = {}
    for d in P.doors:
        if d.kind == "overlook":
            continue        # a ledge one drops from: no way in from below
        deg[d.a] = deg.get(d.a, 0) + 1
        deg[d.b] = deg.get(d.b, 0) + 1

    def room_cells(sid, away_from, z=None):
        s = P.spaces[sid]
        out = [c for c in s.floor if c in nodes and nodes[c][1] == "flat" and free(c)
               and (z is None or nodes[c][0] == z)
               and min(max(abs(c[0] - t[0]), abs(c[1] - t[1])) for t in away_from) >= 2]
        cx, cy = (s.rect.x0 + s.rect.x1) / 2, (s.rect.y0 + s.rect.y1) / 2
        return sorted(out, key=lambda c: abs(c[0] + 0.5 - cx) + abs(c[1] + 0.5 - cy))
    if "dead_end_stack" in mech:
        d = next((d for d in P.doors if d.rj), None)
        cells = []
        if d:
            leaf = d.a if door_side_floor(P, d, P.spaces[d.a]) < d.z - 32 else d.b
            cells = room_cells(leaf, d.cells)
        if cells:
            spots["dead_end"] = cells
        else:
            missing.append(say("dead_end_stack: нет тупика, куда ведёт только спуск", "dead_end_stack: no dead end that only a drop leads into"))
    if "lift_exposure" in mech:
        if not int(q.get("lifts") or 0):
            missing.append(say("lift_exposure: лифтов не просили (0)", "lift_exposure: no lifts were asked (0)"))
        else:
            for (plat, zl, zh, bottom, top) in P.lifts:
                d = next((d for d in P.doors if d.kind == "lift" and list(d.cells) == list(top)), None)
                if d is None:
                    continue
                hi = d.b if d.a == P.owner.get(plat[0]) else d.a
                if deg.get(hi, 0) != 1:
                    continue
                cells = room_cells(hi, d.cells)
                if cells:
                    spots["lift"] = cells
                    break
            if "lift" not in spots:
                missing.append(say("lift_exposure: ни один лифт не ведёт в место с единственным входом", "lift_exposure: no lift leads to a place with one way in"))
    if "ladder_item" in mech:
        for (cells, into, zl, zh, front) in P.ladders:
            d = next((d for d in P.doors if d.kind == "ladder" and list(d.cells) == list(cells)), None)
            if d is None:
                continue
            hi = d.a if P.owner.get(front[0]) == d.b else d.b
            near = [c for c in room_cells(hi, cells, zh)
                    if min(max(abs(c[0] - t[0]), abs(c[1] - t[1])) for t in cells) <= 4]
            if near:
                spots["ladder"] = near
                break
        if "ladder" not in spots:
            missing.append(say("ladder_item: нет стремянки к уступу", "ladder_item: no ladder up to a ledge") if not P.ladders
                           else say("ladder_item: у стремянки нет места", "ladder_item: no room by the ladder's top"))
    return spots, missing


def mech_places(P: Plan, q: dict, mech: set, nodes, times, cands, free, put, used) -> None:
    """Brief 19 §6, the mechanics that hang on a mover or a route: each either placed (its reason in the record) or
    named in P.metrics["mech_missing"] with why - the score then prefers a seed that has it (D5: never silent)."""
    missing = list(P.metrics.get("mech_missing_spots") or [])
    if "tele_mirror" in mech:
        if not P.teleports:
            missing.append(say("tele_mirror: нет телепортов", "tele_mirror: no teleporters"))
        for (a, b_, da, db) in P.teleports[:1]:
            for end in (da, db):
                te = times(end)
                near = sorted((c for c in cands if free(c, 0) and 0.5 <= te.get(c, 99) <= 3.0), key=lambda c: te[c])
                for cls in ("item_armor_combat", "item_health_large"):
                    # the PO 12.11: the armour apart from every major placed
                    fit = [c for c in near if majors_apart(P, cls, c, nodes[c][0], times)]
                    if fit:
                        near.remove(fit[0])
                        put(cls, fit[0], "teleport to a mirrored stack")
            P.reasons.append(("misc_teleporter", "у обоих концов телепорта броня и аптечка в 3 с"))
    if "three_approaches" in mech and not P.teleports:
        missing.append(say("three_approaches: выход телепорта напротив не поставлен - телепортов 0",
                           "three_approaches: no teleporter exit opposite - 0 teleporters"))
    if "pad_pit" in mech and not any(True for _ in P.pads) or "pad_pit" in mech and not P.pits:
        missing.append(say(f"pad_pit: джампадов {len(P.pads)}, смертельных ям {len(P.pits)} - джампада над пропастью нет",
                           f"pad_pit: {len(P.pads)} pads, {len(P.pits)} deadly pits - no pad over a chasm"))
    if "tele_mirror" in mech and P.teleports:
        P.notes.append(say("телепорт к зеркальному стеку: у обоих концов добавлены жёлтая броня и аптечка сверх заказанного набора",
                           "teleport to a mirrored stack: a combat armour and a health added at both ends beyond the set asked"))
    if "three_approaches" in mech and P.teleports:
        key = next(((cls, c) for (cls, c, z, n) in P.items if cls == "weapon_chaingun"), None) or \
            next(((cls, c) for (cls, c, z, n) in P.items if cls == "weapon_railgun"), None)
        if key:
            a, b_, da, db = P.teleports[0]
            s = P.spaces[P.owner[key[1]]]
            near = [c for c in s.floor if c in nodes and nodes[c][1] == "flat" and c not in P.no_items
                    and c not in used and 3 <= max(abs(c[0] - key[1][0]), abs(c[1] - key[1][1])) <= 6]
            if not OLD_MOVER_RULES:
                # brief 35 (the presets' check, mech_ffa_all 700: this exit moved beside the other pair's end and made a
                # third plate with two spawns): the moved exit keeps the movers' rule too - its own pair's ends
                # MOVER_APART off, the other pairs' TELE_PAIRS_APART, no third plate
                marks = [(k, m, z, -1 if pair == 0 else pair) for (k, m, z, pair) in mover_marks(P)
                         if not (k == "exit" and m == db and pair == 0)]
                near = [c for c in near if _end_ok(P, c, marks, None)]
                if not near:
                    from mapgen_scratch_words import item as item_word
                    missing.append(say(f"three_approaches: выход телепорта напротив оружия «{item_word(key[0], True)}» не "
                                       "поставлен - у него нет места вдали от других телепортов, джампадов и точек появления",
                                       f"three_approaches: no teleporter exit opposite the {item_word(key[0], False)} - no "
                                       "room by it away from the other teleporters, jump pads and spawn points"))
            if near:
                nd = near[0]
                P.teleports[0] = (a, b_, da, nd)
                P.no_items.add(nd)
                P.dest_face[nd] = int(math.degrees(math.atan2(key[1][1] - nd[1], key[1][0] - nd[0]))) % 360
                P.reasons.append(("misc_teleporter_dest", f"выход телепорта напротив {key[0]} (в {CELL * max(abs(nd[0] - key[1][0]), abs(nd[1] - key[1][1]))} u)"))
    P.metrics["mech_missing"] = missing


def farthest(cands, used, times, free, prefer=None, ok=None):
    best, bd = None, -1
    pool = [c for c in cands if free(c)]
    if ok:
        # the PO 12.11: the places that keep the majors apart, when there are any
        pool = [c for c in pool if ok(c)] or pool
    if prefer:
        pref = [c for c in pool if prefer(c)]
        pool = pref or pool
    for c in pool[:150]:
        tc = times(c)
        d = min((tc.get(u, 99) for u in used), default=99)
        if d > bd:
            best, bd = c, d
    return best


def facing(P: Plan, c) -> int:
    """Face the longest open run from a spawn."""
    best, ang = -1, 0
    o = P.owner.get(c)
    for a, (dx, dy) in ((0, (1, 0)), (90, (0, 1)), (180, (-1, 0)), (270, (0, -1))):
        n, k = c, 0
        while P.owner.get((n[0] + dx, n[1] + dy)) == o:
            n = (n[0] + dx, n[1] + dy)
            k += 1
        if k > best:
            best, ang = k, a
    return ang


# --------------------------------------------------------------------------------------------- 6. lights, lifts, sky
LIGHT_VALUE = 300          # a lamp's light (Quake II: falls off by one per unit)
COURT_DAYLIGHT = 0.5       # what share of a floor cell's light a court has from the daylight (brief 20 D3)
LIGHT_OVER_COURT = 112     # a court's lamp hangs this far over its floor
LIGHT_VALUE_COURT = 300    # a lamp in a court under the sky (brief 20 D3: 200 only made more lamps - 162 against 58 - and burnt more wall)
LIGHT_FLOOR = 125          # what every floor cell of a room gets at least, by the falloff's sum (110 until the wall lamps
                           # of brief 21: from the walls the floors measured a median 60..68, people's 61..86)
LIGHT_FLOOR_MAPS = 270     # ... in a style by maps or mixed (brief 20 D3; 240 until brief 21's wall lamps: median 53..57)
LIGHT_OVER = 176           # a lamp hangs this far over the floor it lights, under the ceiling
LAMP_OFF_WALL = 24         # a wall lamp's light stands this far out of the wall's face (its fixture 8 proud)
LAMP_APART = 160           # two wall lamps of a space at least this far apart (along the wall, not a cluster)
CORNICE_LAMP_UNDER = 224   # a lamp goes under the cornice when the ceiling is at most this far over its floor


def lamp_sites(P: Plan, s: Space, held: set) -> list:
    """Brief 20 D4's lamps, done in brief 21: where people's maps put a light - along the wall under its cornice, on
    a post at the wall where the ceiling is high or open to the sky, over a doorway on its lintel; never over the
    middle of a cell on a grid. Each site: (x, y, z, mount, cell) with mount ("cornice", dx, dy) | ("post", dx, dy,
    floor z) | ("door", door index, side) - the builder makes the fixture, every one touching a wall, a ceiling or a
    lintel (nothing hangs, the PO 04.11)."""
    out = []
    doors = {c for d in P.doors for c in d.cells}
    glass = {c for (cells, *_r) in P.windows for c in cells}
    pits = {c for (cs, _b, _sid) in P.pits for c in cs}
    wet = {c for (cells, *_r) in P.liquids for c in cells}
    for c, f in s.floor.items():
        if f[1] != "flat" or c in pits or c in wet:
            continue
        ft = floor_top(f)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if n in s.floor or P.owner.get(n) is not None or n in doors or n in glass or n in P.voids:
                continue
            pc = phys(c)
            x = (pc[0] + 0.5) * CELL + dx * (CELL / 2 - LAMP_OFF_WALL)
            y = (pc[1] + 0.5) * CELL + dy * (CELL / 2 - LAMP_OFF_WALL)
            if not s.sky and s.ceil - ft <= CORNICE_LAMP_UNDER:
                out.append((x, y, s.ceil - 20, ("cornice", dx, dy, s.ceil), c))
            elif c not in held:
                out.append((x, y, ft + min(LIGHT_OVER_COURT if s.sky else LIGHT_OVER, s.ceil - ft - 40), ("post", dx, dy, ft), c))
    for i, d in enumerate(P.doors):
        if d.kind != "door" or d.mover or d.rj or len(d.cells) < 2:
            continue
        pcs = [phys(c) for c in d.cells]
        xs, ys = [c[0] for c in pcs], [c[1] for c in pcs]
        along_x = len(set(ys)) == 1
        top_ = door_top(d)
        for sgn in (-1, 1):
            front = (sum(xs) / len(xs), ys[0] + sgn) if along_x else (xs[0] + sgn, sum(ys) / len(ys))
            fc = (int(front[0]), int(front[1]))
            if s.floor and is_up(next(iter(s.floor))):
                fc = up(fc)
            if P.owner.get(fc) != s.id or s.floor.get(fc) is None or (not s.sky and s.ceil < top_ + 48):
                continue
            wx = (sum(xs) / len(xs) + 0.5) * CELL if along_x else (xs[0] + (1 if sgn > 0 else 0)) * CELL + sgn * LAMP_OFF_WALL
            wy = (ys[0] + (1 if sgn > 0 else 0)) * CELL + sgn * LAMP_OFF_WALL if along_x else (sum(ys) / len(ys) + 0.5) * CELL
            out.append((wx, wy, top_ + 24, ("door", i, sgn), fc))
    return out


def light_space(P: Plan, s: Space) -> None:
    """Lamps until no floor of the space is dark (brief 19 §4 «Свет»: no dark room). The first lamps of 04.11 - one in
    four cells under the ceiling - left 43 % of the floor's lightmap under 25 (people's maps: 1..15 %): a lamp under
    a hall's high ceiling lights a pool and nothing round it. Each lamp lights the darkest cell left, until every cell
    has LIGHT_FLOOR from the lamps' linear falloff; since brief 21 it stands at the wall site (`lamp_sites`) nearest
    that cell, apart from the others, and over the floor itself only where no wall lamp reaches (a hall's middle). A
    court under the sky starts from what the sun gives (half)."""
    cells = [c for c in s.floor if c not in {c_ for (cs, _b, _sid) in P.pits for c_ in cs}]
    if not cells:
        return
    # a court under the sky has the daylight (the sun, the sky's own light) - its lamps only fill in, low: lamps
    # 176 up by a court's walls burnt the upper courses white (brief 20 D3, a trial duel 04.11: every wall luxel at
    # 255 was in a court, at 240..352)
    # ... only when a sun shines: a style by maps with no sun of their own (q2dm1, ztn2dm3) has none, and its courts
    # came out a fifth dark (05.11)
    q = P.params
    sun = q.get("sun") or "style"
    src = (q.get("style") or {}).get("source", "generator")
    lit_by_day = sun == "yes" or (sun == "style" and src == "generator")
    # a style by maps wears their darker skins, which give back less of the light (the styled duel 05.11: the
    # generator's target left its floor's median at 35..54, people's 60..117; at 230 - 61)
    target = LIGHT_FLOOR if src == "generator" else LIGHT_FLOOR_MAPS
    have = {c: (target * COURT_DAYLIGHT if s.sky and lit_by_day else 0.0) for c in cells}
    lamps = []

    def add(lx, ly, lz, v):
        lamps.append((lx, ly, lz))
        for c in cells:
            pc = phys(c)
            px, py, pz = (pc[0] + 0.5) * CELL, (pc[1] + 0.5) * CELL, floor_top(s.floor[c])
            d = math.dist((lx, ly, lz), (px, py, pz))
            have[c] += max(0.0, v - d)
    held = ({c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns} | set(P.no_items)
            | {c for (c, *_r) in P.pillars} | set(P.rounded) | button_cells(P) | P.fx_cells)
    corners = {c for (c, *_r) in P.chamfers} | set(P.rounded) | button_cells(P)
    sites = [st for st in lamp_sites(P, s, held) if st[4] not in corners]
    v = LIGHT_VALUE_COURT if s.sky else LIGHT_VALUE
    for _ in range(len(cells)):
        dark = min(cells, key=lambda c: (have[c], c))
        if have[dark] >= target:
            break
        pd = phys(dark)
        px, py, pz = (pd[0] + 0.5) * CELL, (pd[1] + 0.5) * CELL, floor_top(s.floor[dark])
        # brief 21 (brief 20 D4): the lamp at the wall, a post or a doorway nearest the darkest floor, apart from the
        # lamps there are; over the floor itself only where no wall lamp reaches it (a hall's middle)
        best, bg = None, 0.0
        for k, (lx, ly, lz, mount, _c) in enumerate(sites):
            if any(math.dist((lx, ly), (ax, ay)) < LAMP_APART for (ax, ay, _az) in lamps):
                continue
            g = v - math.dist((lx, ly, lz), (px, py, pz))
            if g > bg:
                best, bg = k, g
        if best is not None and bg >= 0.25 * v:
            lx, ly, lz, mount, _c = sites.pop(best)
            add(lx, ly, lz, v)
            P.lights.append((lx, ly, lz, v, mount))
            continue
        # brief 34: the cell's own ceiling where the plan set one - a tower's perch well is open to the sky over one
        # gallery cell, and the lamp panel set at the gallery's ceiling there hung in the air (his tower on 3.60, 3
        # candidates of 10: «nothing hanging … in the air» at the well)
        ceil_here = P.cell_ceil.get(dark, s.ceil) if FREE_LAMP_CELL_CEIL else s.ceil
        z = min(min(s.ceil, ceil_here) - 24, pz + (LIGHT_OVER_COURT if s.sky else LIGHT_OVER))
        # brief 20 D3: a court's lamps hang high by its walls with no ceiling over them - at 300 they burnt the walls'
        # upper courses white (a trial duel, 04.11: every wall luxel at 255 was in a court, 50..70 from a lamp)
        add(px, py, z, v)
        P.lights.append((px, py, z, v, ("free", ceil_here, s.sky or ceil_here > s.ceil)))


# --------------------------------------------------------------------------------------------- 5a. the powerups' places
POWERUPS = ("item_invulnerability", "item_quad", "item_health_mega", "item_armor_body", "item_power_shield")
POWERUP_LIGHT = {"item_quad": (0.45, 0.55, 1.0), "item_invulnerability": (1.0, 0.85, 0.4),
                 "item_health_mega": (0.6, 0.8, 1.0), "item_armor_body": (1.0, 0.45, 0.35),
                 "item_power_shield": (0.45, 1.0, 0.5)}


def nook_spot(P: Plan, s: Space, near, width: int, depth: int, taken: set, min_z=None, rank=None):
    """A nook to carve out of the rock behind space `s`, near cell `near`: the wall cells between (its opening) and the
    rock cells behind them, all of them owned by nobody, the rock round the nook too (a wall stays between it and any
    other space); the cell in front of the opening level floor of `s`. Returns (front cells, opening cells, nook cells,
    direction) or None."""
    best = None
    for c, f in s.floor.items():
        if f[1] != "flat" or c in taken or abs(c[0] - near[0]) + abs(c[1] - near[1]) > 6:
            continue
        if min_z is not None and f[0] < min_z:
            continue                              # not down off the item's terrace (its height is asked)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            px, py = (-dy, dx)                    # along the wall
            fronts = [(c[0] + px * k, c[1] + py * k) for k in range(width)]
            if any(s.floor.get(x, (None, "x"))[1] != "flat" or s.floor[x][0] != f[0] or x in taken for x in fronts):
                continue
            opening = [(x[0] + dx, x[1] + dy) for x in fronts]
            cells = [(x[0] + dx * (1 + j), x[1] + dy * (1 + j)) for x in fronts for j in range(1, depth + 1)]
            ring = set()
            for x in opening + cells:
                for ex in (-1, 0, 1):
                    for ey in (-1, 0, 1):
                        ring.add((x[0] + ex, x[1] + ey))
            ring -= set(opening) | set(cells) | set(fronts)
            if any(P.owner.get(x) is not None or x in taken for x in opening + cells):
                continue
            # the ring round it: rock, or the front space itself beside the opening (its own wall cells are rock)
            if any(P.owner.get(x) not in (None, s.id) for x in ring):
                continue
            if any(P.owner.get(x) == s.id and x not in s.floor for x in ring):
                continue
            # not over or under anything of the upper layer, and inside the map
            if any(x[0] < 1 or x[1] < 1 or x[0] >= P.W - 1 or x[1] >= P.H - 1 for x in cells + opening):
                continue
            # brief 22 D3: `rank` of the front cell first (the clock's band for its pair), then the nearest
            d = (rank(c) if rank else 0, abs(c[0] - near[0]) + abs(c[1] - near[1]))
            if best is None or d < best[0]:
                best = (d, fronts, opening, cells, (dx, dy))
    return best[1:] if best else None


def inner_nook(P: Plan, s: Space, near, taken: set, min_z=None, rank=None):
    """Where no rock lies behind the wall (the spaces are packed), the nook is walled off inside the space itself: two
    cells along a wall with rock behind them (its interior), the row in front of them and the cells at its sides turned
    to rock, one of the front row left as its opening (the PO's q2dm5 mega: a nook 56 wide at a room's side). Returns
    (front cell, opening cells, nook cells, direction, cells turned to rock) or None; nothing is changed here."""
    best = None
    for c, f in s.floor.items():
        if f[1] != "flat" or c in taken or abs(c[0] - near[0]) + abs(c[1] - near[1]) > 10:
            continue
        if min_z is not None and f[0] < min_z:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            px, py = (-dy, dx)
            X = [c, (c[0] + px, c[1] + py)]
            if any(s.floor.get(x, (None, "x")) != (f[0], "flat", 0, 0) or x in taken for x in X):
                continue
            if any(P.owner.get((x[0] + dx, x[1] + dy)) is not None for x in X):
                continue                                   # rock behind both
            F = [(x[0] - dx, x[1] - dy) for x in X]
            caps = [(X[0][0] - px, X[0][1] - py), (X[1][0] + px, X[1][1] + py),
                    (F[0][0] - px, F[0][1] - py), (F[1][0] + px, F[1][1] + py)]
            opening = F[0]
            front = (opening[0] - dx, opening[1] - dy)
            rock = [F[1]] + [x for x in caps if x in s.floor]
            if any(x not in s.floor or s.floor[x] != (f[0], "flat", 0, 0) or x in taken for x in F):
                continue
            if any(x in taken or s.floor.get(x, (None, "x"))[1] != "flat" for x in rock):
                continue
            # the caps that are not the space's own must be rock already
            if any(x not in s.floor and P.owner.get(x) is not None for x in caps):
                continue
            if s.floor.get(front) != (f[0], "flat", 0, 0) or front in taken:
                continue
            if len(s.floor) - len(rock) - 3 < 12:
                continue
            d = (rank(front) if rank else 0, abs(c[0] - near[0]) + abs(c[1] - near[1]))
            if best is None or d < best[0]:
                best = (d, front, [opening], X, (dx, dy), rock)
    return best[1:] if best else None


def wall_spot(P: Plan, s: Space, far_from, taken: set, z: int):
    """A cell of `s` at its edge with rock behind, on floor z, 3..8 cells from `far_from`: where a button goes."""
    out = []
    for c, f in s.floor.items():
        if f[1] != "flat" or f[0] != z or c in taken:
            continue
        dist = abs(c[0] - far_from[0]) + abs(c[1] - far_from[1])
        if not (3 <= dist <= 8):
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if P.owner.get(n) is None and n not in taken and n not in s.floor:
                out.append((dist, c, (dx, dy)))
    out.sort()
    return out[0][1:] if out else None


def powerup_sites(P: Plan, rnd: random.Random) -> None:
    """The PO, 05.11: «у людей на картах обычно обособленное место есть и бывает что с повышенной степенью трудности
    добирания … на высокой сложности чтобы забрать паверап нужно нажать на кнопку и что-то открыть … или залезть в
    нычку … а на простом на полу лежат. Но нужно помечать такие места, делая их значимыми» - q2duel5's quad on a lit
    ledge, q2dm5's mega in a nook 56 wide, q2dm3's mega behind a door its buttons open, q2dm8's mega / body armour /
    power shield taking turns in one nook (measured 05.11, scratchpad powerups.txt). Each powerup gets its place by
    the access asked (`powerup_access`):
      easy   - where it lies, on a pedestal under its own light;
      medium - a nook carved into the wall beside it, framed, on a pedestal, lit;
      hard   - the same nook shut by a door that a button on the room's wall opens for a few seconds (a second button
               inside lets one out);
      mixed  - the most valuable hard, the next medium, the rest easy (an invulnerability or a quad first).
    With `powerup_cycle` the stack's body armour and mega (and a power shield on a larger map) take turns in one nook
    (an item team, as q2dm8's). A nook is a dead end by design: a space of its own, asked."""
    q = P.params
    access = q.get("powerup_access") or "mixed"
    held = ({c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns} | set(P.no_items)
            | {c for d in P.doors for c in d.cells} | {c for (cs, *_r) in P.lifts for c in cs}
            | {c for (cs, _b, _sid) in P.pits for c in cs} | {c for (c, *_r) in P.pillars}
            | {c for (cells, *_r) in P.liquids for c in cells} | {c for (cells, *_w) in P.windows for c in cells})
    for d in P.doors:
        for c in d.cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                held.add((c[0] + dx, c[1] + dy))
    order = {cls: k for k, cls in enumerate(POWERUPS)}
    kinds = {} if OLD_MAJORS else dict(P.prize_kind)
    # the PO 12.11: the prizes earned (prize_sites put the dives, the movers' ledges and the open spots already) - the
    # nooks' kinds here, the key gun among them
    pw = [(k, it) for k, it in enumerate(P.items)
          if (it[0] in order or k in kinds) and kinds.get(k, "jump") in ("jump", "hard", "easy")]
    pw.sort(key=lambda t: order.get(t[1][0], len(order)))
    levels = {}
    for rank, (k, it) in enumerate(pw):
        if k in kinds:
            levels[k] = {"jump": "medium", "hard": "hard", "easy": "easy"}[kinds[k]]
        elif access == "mixed":
            levels[k] = "hard" if rank == 0 else "medium" if rank == 1 else "easy"
        else:
            levels[k] = access
    cycle = bool(q.get("powerup_cycle"))
    team_cells = []
    sites = []
    P.buttons = []
    P.pedestals = list(getattr(P, "pedestals", None) or [])     # a vault's prize has its own already (prize_sites)
    nook_no = 0
    for rank, (k, it) in enumerate(pw):
        cls, c, z, note = P.items[k]
        level = levels[k]
        s = P.spaces[P.owner[c]] if c in P.owner else None
        if cycle and cls in ("item_armor_body", "item_power_shield") and team_cells:
            # the cycle: this one takes turns with the mega in its nook
            tc, tz = team_cells[0]
            P.items[k] = (cls, tc, tz, "cycle with the mega")
            sites.append((cls, "cycle"))
            continue
        made = None
        # brief 22 D3: one of the clock's pair keeps its band to its mate where a nook allows (its nook moves it: 28
        # of 32 pairs in the band where placed, 23 after the nooks)
        rank = None
        pair_ = P.metrics.get("stack_pair") or []
        if "clock" in (q.get("mechanics") or []) and cls in pair_:
            mate = next((c2 for (cl2, c2, _z2, _n2) in P.items if cl2 in pair_ and cl2 != cls), None)
            if mate is not None:
                tm_ = dijkstra(plan_graph(P)[1], mate)
                lo_b, hi_b = (5.0, 9.0) if q["class"] == "duel" else (4.0, 12.0)
                # the front cell's time, a nook's two cells (about 0.4 s) on top
                rank = lambda fc, tm_=tm_, lo_b=lo_b, hi_b=hi_b: 0 if lo_b <= tm_.get(fc, 99) + 0.4 <= hi_b else 1  # noqa: E731

        def find_spot(sp, near):
            width = 2 if sp.kind == "hall" else 1
            spot_ = (nook_spot(P, sp, near, width, 2, held, z - 16, rank) or nook_spot(P, sp, near, 1, 2, held, z - 16, rank)
                     or nook_spot(P, sp, near, 1, 1, held, z - 16, rank))
            if not spot_ and sp.kind in ("hall", "room", "corridor"):
                inner = inner_nook(P, sp, near, held, z - 16, rank)
                if inner:
                    front, opening_, cells_, dir_, rock = inner
                    before_ = cut_off(P)
                    saved_ = {x: sp.floor[x] for x in rock + opening_ + cells_}
                    for x in rock + opening_ + cells_:
                        sp.floor.pop(x, None)
                        P.owner.pop(x, None)
                        if x in sp.extra:
                            sp.extra.remove(x)
                    if cut_off(P) > before_:
                        for x, f0 in saved_.items():
                            sp.floor[x] = f0
                            P.owner[x] = sp.id
                    else:
                        spot_ = ([front], opening_, cells_, dir_)
            return spot_
        spot = None
        if level in ("medium", "hard") and s is not None and not s.solid:
            spot = find_spot(s, c)
            if not spot:
                # no nook by it (05.11: a duel's mega had none in 9 of 26 skeletons): the nearest other room or hall
                # of its half that has one - the powerup moves there, its place still its own
                others = []
                for o_ in P.spaces:
                    if (o_.id == s.id or o_.solid or o_.kind not in ("hall", "room", "corridor") or not o_.floor
                            or (s.id in P.half and P.half.get(o_.id) != P.half[s.id])):
                        continue
                    # on its own level or higher: the clock's stack stands 64 up (brief 19 §6), the items' height
                    # share is asked - a mega moved down into a low room broke both (the tech duel 05.11: 72/8)
                    at = [x for x in o_.floor if o_.floor[x][1] == "flat" and o_.floor[x][0] >= z - 16]
                    if not at:
                        continue
                    cc = min(at, key=lambda x: abs(x[0] - c[0]) + abs(x[1] - c[1]))
                    others.append((abs(cc[0] - c[0]) + abs(cc[1] - c[1]), o_.id, cc))
                # brief 22 D3: one of the clock's pair moving - the rooms that keep the pair 5..9 s (duel) / 4..12 s
                # apart first, the nearest of them first
                pair = P.metrics.get("stack_pair") or []
                if "clock" in (q.get("mechanics") or []) and cls in pair and others:
                    mate = next((c2 for (cl2, c2, _z2, _n2) in P.items if cl2 in pair and cl2 != cls), None)
                    if mate is not None:
                        _nodes_, edges_ = plan_graph(P)
                        tm = dijkstra(edges_, mate)
                        lo_b, hi_b = (5.0, 9.0) if q["class"] == "duel" else (4.0, 12.0)
                        others = [(0 if lo_b <= tm.get(cc, 99) <= hi_b else 1, d_, oid_, cc)
                                  for (d_, oid_, cc) in others]
                        others = [(b_ * 1000 + d_, oid_, cc) for (b_, d_, oid_, cc) in others]
                _nodes_h, edges_h = plan_graph(P)
                cache_h: dict = {}

                def times_h(c_):
                    if c_ not in cache_h:
                        cache_h[c_] = dijkstra(edges_h, c_)
                    return cache_h[c_]
                for _d, oid, cc in sorted(others)[:5]:
                    if not OLD_MAJORS and not _halves_ok(P, k, cc, times_h):
                        continue        # the PO 12.11: a nook in a room that brings the key gun and the stack near
                    spot = find_spot(P.spaces[oid], cc)
                    if spot:
                        s = P.spaces[oid]
                        break
            if spot:
                fronts, opening, cells, (dx, dy) = spot
                zf = s.floor[fronts[0]][0]
                # medium, every other one: the nook raised 40 over the floor - jumped into (the walk's jump up is 44),
                # as people's ledges (q2duel5's quad, q2dm5's quad 368 up by steps; ours a jump, never a climb)
                # the PO 12.11 («рельса должна быть заслуженной … в нычку в стене прыгать», q2dm8): every medium
                # nook a jump now (3.65: every other)
                raise_ = 40 if level == "medium" and (not OLD_MAJORS or rnd.random() < 0.5) else 0
                zf_in = zf + raise_
                N = Space(len(P.spaces), "nook", Rect(min(x[0] for x in cells), min(x[1] for x in cells),
                                                      max(x[0] for x in cells) + 1, max(x[1] for x in cells) + 1), base=zf_in)
                N.floor = {x: (zf_in, "flat", 0, 0) for x in cells}
                N.ceil = zf_in + DOOR_H + 16
                N.pattern = "flat"
                P.spaces.append(N)
                for x in cells:
                    P.owner[x] = N.id
                if s.id in P.half:
                    P.half[N.id] = P.half[s.id]
                d = Door(s.id, N.id, list(opening), za=zf, zb=zf_in, z=zf_in, kind="door")
                P.asked.add(N.id)
                back = cells[-1]
                if level == "hard":
                    nook_no += 1
                    d.mover = True
                    d.tname = f"mg_pw{nook_no}"
                    btn = wall_spot(P, s, fronts[0], held | set(opening), zf)
                    if btn is None:
                        d.mover = False
                        level = "medium"
                    else:
                        bc, bdir = btn
                        P.buttons.append((bc, bdir, zf, d.tname))
                        held.add(bc)
                        # a second button inside, on the nook's back wall, so nobody is shut in
                        P.buttons.append((back, (dx, dy), zf, d.tname))
                P.doors.append(d)
                held.update(opening + cells + fronts)
                P.items[k] = (cls, back, zf_in, (f"{note}; " if note else "") + f"{level}: in a nook"
                              + (" raised 40, jumped into" if raise_ else ""))
                P.pedestals.append((back, zf_in, cls))
                made = level + (" (jump in)" if raise_ else "")
                if cycle and cls == "item_health_mega":
                    team_cells.append((back, zf_in))
        if made is None:
            # easy (or no nook fits): a pedestal where it lies, under its own light
            if s is not None and s.floor.get(c, (None, "x"))[1] == "flat":
                P.pedestals.append((c, z, cls))
            made = "easy" if level == "easy" else "easy (no nook)"
            if cycle and cls == "item_health_mega":
                team_cells.append((c, z))
        sites.append((cls, made))
    P.metrics["powerup_sites"] = sites
    P.metrics["powerup_access"] = access
    P.metrics["powerup_cycle"] = cycle


# --------------------------------------------------------------------------------------------- the prizes earned
# The PO 12.11: «рельса должна быть заслуженной - заработанной, достанной не просто так, а через усилия … на q2dm1 -
# там плыть нужно. На ztn2dm3 нужно прыгать за ней. На q2duel5 … пройти через обстрел аж с трех сторон», «на q2rdm2
# через пропасть нужно прыгать», «на q2dm8 прыгать в нычку в стене», «не видел пока у тебя карт аналогичных q2dm1 -
# чтобы нужно было плыть под водой … Или как q2dm5». People's (tools/mapgen_item_rules.json, 40 maps): the railgun
# earned on 27 of 41 (a gap jump, a jump up, a teleporter, a lift, a swim), the mega 26 of 30, the quad 13 of 15, the
# body armour 16 of 25; ours 0..0.15 of the spawns needed anything. Each prize gets a way:
#   jump    - a nook in the wall raised 40, jumped into (q2dm8); hard - the nook shut by a door a button opens
#   lift / ladder - a ledge only a lift (a ladder) reaches
#   water   - a dive: a well 160 deep with the prize at its bottom (q2dm5's mega), or a vault behind the wall reached by
#             a drowned doorway at a well's bottom, its own well up into it (q2dm1's railgun)
#   exposed - the open middle of a place where three ways meet (q2duel5's railgun, under fire from three sides)
def prize_plan(P: Plan, rnd: random.Random) -> None:
    """How each prize is earned: «prize_access» people (the knowledge base's ways for its class, by their shares), nooks,
    movers, water, exposed; the first «underwater» prizes by worth under water; a nook kind takes the powerups' access
    asked (the form's «Доступ к усилителям»)."""
    if OLD_MAJORS:
        return
    q = P.params
    key = next((k for k, it in enumerate(P.items) if it[0].startswith("weapon_") and it[3].startswith("key gun")), None)
    if key is None:
        key = next((k for k, it in enumerate(P.items) if it[0] == "weapon_railgun"), None)
    prizes = {k for k, it in enumerate(P.items) if it[0] in PRIZE_ORDER and it[0] != "weapon_railgun"}
    if key is not None:
        prizes.add(key)

    def worth(k):
        cls = P.items[k][0]
        return PRIZE_ORDER.index(cls) if cls in PRIZE_ORDER else PRIZE_ORDER.index("weapon_railgun")
    prizes = sorted(prizes, key=lambda k: (worth(k), k))
    access = q.get("prize_access") or "people"
    rules = item_rules(q).get("prizes") or ITEM_RULES.get("prizes") or {}
    move_kind = {"gap": "jump", "jump": "jump", "teleport": "jump", "push": "jump", "plat": "lift", "ladder": "ladder",
                 "swim": "water"}
    # a ledge only a lift (a ladder) reaches is rare on our skeletons (a stair leads up too): people's lift is then the
    # nearest we build - a nook jumped into - not a way asked and refused
    has_ledge = {k_: bool(_mover_ledges(P, k_)) for k_ in ("lift", "ladder")}
    kinds = {}
    for k in prizes:
        cls, c, z, note = P.items[k]
        if note.startswith("lift as exposure"):
            kinds[k] = "lift"
            continue
        if note.startswith("ladder under"):
            kinds[k] = "ladder"
            continue
        if note.startswith("dead-end stack"):
            kinds[k] = "kept"           # dropped into, left by a rocket jump: earned already
            continue
        if access == "people":
            r = rules.get(cls) or rules.get("item_health_mega") or {}
            w = {"jump": 0.0, "lift": 0.0, "ladder": 0.0, "water": 0.0, "exposed": 0.0}
            for mv, n in (r.get("moves") or {}).items():
                w[move_kind.get(mv, "jump")] += float(n)
            if cls.startswith("weapon_") or cls == "item_armor_body":
                w["exposed"] += float(r.get("exposed") or 0) * float(r.get("n") or 0)
            if sum(w.values()) <= 0:
                w["jump"] = 1.0
            pick = rnd.random() * sum(w.values())
            for kind_, v in w.items():
                pick -= v
                if pick <= 0:
                    break
            if kind_ in has_ledge and not has_ledge[kind_]:
                kind_ = "jump"
            kinds[k] = kind_
        elif access == "nooks":
            kinds[k] = "jump"
        elif access == "movers":
            kinds[k] = "lift" if P.lifts and (not P.ladders or rnd.random() < 0.6) else "ladder" if P.ladders else "lift"
        elif access == "water":
            kinds[k] = "water"
        else:   # exposed: a gun and an armour in the open, the powerups in their nooks
            kinds[k] = "exposed" if cls.startswith("weapon_") or cls.startswith("item_armor") else "jump"
    for k in [k for k in prizes if kinds.get(k) != "kept"][:int(q.get("underwater") or 0)]:
        kinds[k] = "water"
    # the PO 12.11 on mg_new_7775_367: «глубокие бассейны ... не несут никакого смысла для того чтобы туда плыть - а
    # там должны лежать важнейшие на карте айтемы - например как рейлган на q2dm1 или мега или красный армор»: each
    # water of pools joined by tubes takes a prize, the most valuable first (people's deep water: 9 bodies of 10 hold
    # majors - q2dm1's railgun, q2dm2's quad, q2dm4's quad, mega, BFG and body armour, q2dm5's mega)
    if water_deep(q) and access in ("people", "water"):
        need = len(water_systems(P)) - sum(1 for k in prizes if kinds.get(k) == "water")
        for k in prizes:
            if need <= 0:
                break
            if kinds.get(k) in ("kept", "water", "lift", "ladder"):
                continue
            # the stack on a clock stays up high where the mechanic wants it (64 up, two ways out); the next prize goes
            if "clock" in (q.get("mechanics") or []) and P.items[k][0] in (P.metrics.get("stack_pair") or []):
                continue
            kinds[k] = "water"
            need -= 1
    nooked = [k for k in prizes if kinds[k] == "jump" and P.items[k][0] in POWERUPS]
    pw_access = q.get("powerup_access") or "mixed"
    for j, k in enumerate(nooked):
        if pw_access == "hard" or (pw_access == "mixed" and j == 0):
            kinds[k] = "hard"
        elif pw_access == "easy":
            kinds[k] = "easy"           # the form asks them on the floor (the PO 05.11: «на простом на полу лежат»)
    P.prize_kind = kinds
    P.metrics["prize_kinds"] = [[P.items[k][0], kinds[k]] for k in prizes]


HALVES_S = 7.0           # brief 19 §6 «halves»: the key gun and the stack's first item at least this far on foot


def _halves_ok(P: Plan, k: int, cell, times_of, extra: float = 0.0) -> bool:
    """The PO 12.11, his test map: a prize moved into a vault (a nook in the next room) took «halves» from 7.9 s to
    4.6 s - the key gun and the stack's first item keep HALVES_S (with the plan's slack) when either moves."""
    q = P.params
    if "halves" not in (q.get("mechanics") or []) or not P.half or q.get("mode") == "tdm":
        return True
    pair = P.metrics.get("stack_pair") or []
    key_k = next((j for j, it in enumerate(P.items) if it[0].startswith("weapon_") and it[3].startswith("key gun")), None)
    first_k = next((j for j, it in enumerate(P.items) if pair and it[0] == pair[0]), None)
    if key_k is None or first_k is None or k not in (key_k, first_k):
        return True
    other = P.items[first_k if k == key_k else key_k][1]
    return times_of(other).get(cell, 0.0) + extra >= HALVES_S * MAJORS_PLAN_SLACK


def _prize_held(P: Plan) -> set:
    """What a prize's new place must keep off: items, spawns, movers, doors and their sides, pits, liquids, windows."""
    held = ({c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns} | set(P.no_items)
            | {c for d in P.doors for c in d.cells} | {c for (cs, *_r) in P.lifts for c in cs}
            | {c for (cs, _b, _sid) in P.pits for c in cs} | {c for (c, *_r) in P.pillars}
            | {c for (cells, *_r) in P.liquids for c in cells} | {c for (cells, *_w) in P.windows for c in cells})
    for d in P.doors:
        for c in d.cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                held.add((c[0] + dx, c[1] + dy))
    return held


def _stacked_over(P: Plan, cells) -> bool:
    """A cell with another layer's floor in its column (a room over a room, a tower's storey)."""
    for c in cells:
        p = phys(c)
        for j in range(0, 4):
            y = (p[0], p[1] + UP * j)
            if y != c and y in P.owner:
                return True
    return False


def prize_sites(P: Plan, rnd: random.Random) -> None:
    """The prizes' ways that are not a nook: the dives, the movers' ledges, the open spots. A way that finds no room
    falls back to a nook jumped into (said in the record)."""
    if OLD_MAJORS or not P.prize_kind:
        return
    nodes, edges = plan_graph(P)
    cache: dict = {}

    def times_of(c):
        if c not in cache:
            cache[c] = dijkstra(edges, c)
        return cache[c]
    held = _prize_held(P)
    fell = []
    for k, kind in sorted(P.prize_kind.items(), key=lambda t: t[0]):
        if kind in ("jump", "hard", "easy", "kept"):
            continue
        cls = P.items[k][0]
        made = False
        if kind == "water":
            if OLD_WATER or not water_deep(P.params):
                # 3.66: the swim to a vault for the railgun and the powerups first (q2dm1), a well else (q2dm5)
                first = (_dive_vault, _dive_well) if cls in ("weapon_railgun", "item_quad", "item_invulnerability") \
                    else (_dive_well, _dive_vault)
            else:
                # the PO 12.11: a pool, a tube under the rock, the prize's room above its own water (q2dm1's railgun);
                # at a deep pool's bottom else (q2dm2's quad)
                first = (_dive_tube, _dive_pool) if cls in ("weapon_railgun", "item_quad", "item_invulnerability") \
                    else (_dive_pool, _dive_tube)
            made = any(f(P, k, held, times_of) for f in first)
        elif kind in ("lift", "ladder"):
            made = _mover_ledge(P, k, kind, held, times_of)
        elif kind == "exposed":
            made = _open_spot(P, k, held, times_of)
        if not made:
            P.prize_kind[k] = "jump"
            fell.append((cls, kind))
    if fell:
        import mapgen_scratch_words as words_mod
        words = {"water": ("под водой", "under water"), "lift": ("только лифтом", "by a lift only"),
                 "ladder": ("только по лестнице", "by a ladder only"), "exposed": ("на открытом месте", "in the open")}
        # the items by their names (his mg_new_56432 of 12.11 said «weapon_railgun под водой» in Russian)
        P.notes.append(say("призы в нише с прыжком вместо: "
                           + ", ".join(f"{words_mod.item(c_, True).lower()} {words[k_][0]}" for c_, k_ in fell)
                           + " - на этом каркасе для них нет места",
                           "prizes in a nook jumped into instead of: "
                           + ", ".join(f"{words_mod.item(c_, False).lower()} {words[k_][1]}" for c_, k_ in fell)
                           + " - no room for it on this skeleton"))
    P.metrics["prize_fell_back"] = [[c_, k_] for c_, k_ in fell]
    P.metrics["prize_kinds"] = [[P.items[k][0], P.prize_kind[k]] for k in sorted(P.prize_kind)]


def _spaces_near(P: Plan, c, kinds=("hall", "room")) -> list:
    """The places to try for a prize at `c`: its own first, then the nearest - halls and rooms of the ground layer."""
    own = P.owner.get(c)
    out = [s for s in P.spaces if not s.solid and s.kind in kinds and not getattr(s, "atrium", False) and s.floor
           and layer_of(next(iter(s.floor))) == 0]

    def dist(s):
        return 0 if s.id == own else min(abs(x[0] - c[0]) + abs(x[1] - c[1]) for x in s.floor)
    return sorted(out, key=dist)


def _dive_well(P: Plan, k: int, held: set, times_of) -> bool:
    """A well 160 deep, 2 x 2 cells, in the floor of a hall or a room - surrounded by that floor, off the doors and the
    items - water up to 8 under the floor; the prize at its bottom (q2dm5's mega)."""
    cls, c, z, note = P.items[k]
    for s in _spaces_near(P, c)[:6]:
        best = None
        for x, f, block in ((x, f, b_) for x, f in s.floor.items() for b_ in (
                [x, (x[0] + 1, x[1]), (x[0], x[1] + 1), (x[0] + 1, x[1] + 1)], [x, (x[0] + 1, x[1])], [x, (x[0], x[1] + 1)])):
            if f[1] != "flat":
                continue
            if any(s.floor.get(b) != (f[0], "flat", 0, 0) or b in held for b in block):
                continue
            ring = {(b[0] + dx, b[1] + dy) for b in block for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - set(block)
            # in a hollow of the floor: round it that floor itself or rock - no step, no other place, no door or
            # item beside it
            bad = False
            for r in ring:
                if r in s.floor:
                    bad = s.floor[r][0] != f[0] or r in held
                else:
                    bad = P.owner.get(r) is not None or r in held
                if bad:
                    break
            if bad:
                continue
            if _stacked_over(P, block):
                continue
            zb = f[0] - DIVE_DEPTH
            if not majors_apart(P, cls, block[-1], zb, times_of, skip=k) or not _halves_ok(P, k, block[-1], times_of):
                continue
            # the 2 x 2 well first (room to turn in), then the nearest
            d = (0 if len(block) == 4 else 1, abs(x[0] - c[0]) + abs(x[1] - c[1]))
            if best is None or d < best[0]:
                best = (d, block, f[0])
        if best:
            _d, block, zf = best
            zb = zf - DIVE_DEPTH
            for b in block:
                s.floor[b] = (zb, "flat", 0, 0)
            P.liquids.append((list(block), "water", zb, zf - 8))
            P.no_items.update(block)
            held.update(block)
            P.items[k] = (cls, block[-1], zb, (f"{note}; " if note else "") + "under water: a dive into a well (q2dm5)")
            P.reasons.append((cls, say("приз на дне колодца - за ним нырять", "the prize at a well's bottom - one dives for it")))
            return True
    return False


def _dive_vault(P: Plan, k: int, held: set, times_of) -> bool:
    """A vault carved into the rock behind a wall, its only way in under water (q2dm1's railgun): a well in the room at
    the wall, a drowned doorway through the wall at the well's bottom, the vault's own well up into it, its dry floor
    with the prize."""
    cls, c, z, note = P.items[k]
    for s in _spaces_near(P, c)[:6]:
        near = min(s.floor, key=lambda x: abs(x[0] - c[0]) + abs(x[1] - c[1]))
        spot = nook_spot(P, s, near, 1, 3, held, None, None)
        if not spot:
            continue
        fronts, opening, cells, (dx, dy) = spot
        if _stacked_over(P, fronts + opening + cells):
            continue
        zf = s.floor[fronts[0]][0]
        zb = zf - DIVE_DEPTH
        # the front cell's sides: that floor too (a well in a hollow, not at a step)
        side = [(fronts[0][0] + ex, fronts[0][1] + ey) for ex, ey in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        if any(x in s.floor and s.floor[x][0] != zf for x in side):
            continue
        if not majors_apart(P, cls, cells[-1], zf, times_of, skip=k) or not _halves_ok(P, k, fronts[0], times_of):
            continue
        s.floor[fronts[0]] = (zb, "flat", 0, 0)
        V = Space(len(P.spaces), "nook", Rect(min(x[0] for x in cells), min(x[1] for x in cells),
                                              max(x[0] for x in cells) + 1, max(x[1] for x in cells) + 1), base=zf)
        V.floor = {cells[0]: (zb, "flat", 0, 0), cells[1]: (zf, "flat", 0, 0), cells[2]: (zf, "flat", 0, 0)}
        V.ceil = zf + DOOR_H + 16
        V.pattern = "flat"
        P.spaces.append(V)
        for x in cells:
            P.owner[x] = V.id
        if s.id in P.half:
            P.half[V.id] = P.half[s.id]
        d = Door(s.id, V.id, list(opening), za=zb, zb=zb, z=zb, kind="door", top=zb + 96)
        P.doors.append(d)
        P.asked.add(V.id)
        P.liquids.append(([fronts[0]], "water", zb, zf - 8))
        P.liquids.append((list(opening), "water", zb, zb + 96))
        P.liquids.append(([cells[0]], "water", zb, zf - 8))
        P.no_items.update(fronts + opening + cells[:1])
        held.update(fronts + opening + cells)
        P.items[k] = (cls, cells[-1], zf, (f"{note}; " if note else "") + "under water: a swim to a vault (q2dm1)")
        P.pedestals = list(getattr(P, "pedestals", None) or []) + [(cells[-1], zf, cls)]
        P.reasons.append((cls, say("приз в тайнике за стеной - вход только под водой",
                                   "the prize in a vault behind the wall - the only way in under water")))
        return True
    return False


def _pools_near(P: Plan, c) -> list:
    """The pools to dive from: those of a water no valuable item is in yet first (the PO 12.11), then the nearest."""
    def dist(p):
        return min(abs(x[0] - c[0]) + abs(x[1] - c[1]) for x in p["cells"])
    served = _served_systems(P)
    sys_of = {i: n for n, g in enumerate(water_systems(P)) for i in g}
    return sorted((p for p in P.pools if len(p["cells"]) >= 2),
                  key=lambda p: (sys_of.get(P.pools.index(p)) in served, dist(p)))


def water_systems(P: Plan) -> list:
    """The deep pools joined by tubes under water: each a set of pools' indexes (one water to swim in)."""
    idx = [i for i, p in enumerate(P.pools) if len(p["cells"]) >= POOL_MIN]
    root = {i: i for i in idx}

    def find(i):
        while root[i] != i:
            i = root[i]
        return i
    of_space = {}
    for i in idx:
        of_space.setdefault(P.pools[i]["space"], []).append(i)
    for d in P.doors:
        if d.kind == "swim" and d.a in of_space and d.b in of_space:
            root[find(of_space[d.a][0])] = find(of_space[d.b][0])
    for ids in of_space.values():
        for i in ids[1:]:
            root[find(i)] = find(ids[0])
    groups: dict = {}
    for i in idx:
        groups.setdefault(find(i), set()).add(i)
    return sorted(groups.values(), key=min)


def _served_systems(P: Plan) -> set:
    """The waters a valuable item is reached through already (its pool's index kept by the dive)."""
    sys_of = {i: n for n, g in enumerate(water_systems(P)) for i in g}
    return {sys_of[i] for i in getattr(P, "pool_served", set()) if i in sys_of}


def _serve(P: Plan, pool: dict) -> None:
    if not hasattr(P, "pool_served"):
        P.pool_served = set()
    P.pool_served.add(P.pools.index(pool))


# what an empty water takes when the prizes are placed (the PO 12.11), the most valuable first; people's: q2dm2's
# chaingun in its water, q2dm5's grenade launcher and chaingun at its rim, q2dm4's shotguns
POOL_ITEMS = ("weapon_rocketlauncher", "item_armor_combat", "weapon_hyperblaster", "weapon_grenadelauncher",
              "weapon_chaingun", "weapon_supershotgun", "item_armor_jacket", "weapon_bfg", "weapon_machinegun")


def pool_purpose(P: Plan) -> None:
    """The PO 12.11 («вот приплыл сюда, а там пусто»): a water no prize went into takes a valuable item that no
    mechanic holds - by a tube to its room (q2dm1) or at the pool's bottom (q2dm2), apart from the other majors as
    the rule asks. Said in the record when none can."""
    if OLD_MAJORS or OLD_WATER or not water_deep(P.params):
        return
    systems = water_systems(P)
    nodes, edges = plan_graph(P)
    cache: dict = {}

    def times_of(c):
        if c not in cache:
            cache[c] = dijkstra(edges, c)
        return cache[c]
    fixed = ("stack", "key gun", "asymmetry", "lift as", "ladder", "dead-end", "teleport to", "armour by",
             "adrenaline tucked", "in a nook", "under water", "only a", "in the open", "cycle", "clock")
    held = _prize_held(P)
    empty = 0
    for n, g in enumerate(systems):
        if n in _served_systems(P):
            continue
        pools = sorted((P.pools[i] for i in g), key=lambda p: -len(p["cells"]))
        done = False
        for cls in POOL_ITEMS:
            for k, (c_, cell, z, note) in enumerate(P.items):
                if c_ != cls or k in P.prize_kind or any(f in note for f in fixed):
                    continue
                if _dive_tube(P, k, held, times_of, pools=pools) or _dive_pool(P, k, held, times_of, pools=pools):
                    done = True
                    break
            if done:
                break
        if not done:
            empty += 1
    P.metrics["pools_empty"] = empty
    if empty:
        P.notes.append(say(f"водоёмов без ценного предмета: {empty} - на этом каркасе ни одному не нашлось места",
                           f"waters with no valuable item: {empty} - no room for one on this skeleton"))


def _dive_tube(P: Plan, k: int, held: set, times_of, pools=None) -> bool:
    """The PO 12.11 («на q2dm1 там глубокий большой водоем через который нужно плыть и там еще и труба есть по которой
    плывут до выхода на рейл»): from a deep pool's side a tube under the floors, 6..12 cells (q2dm1's 368 u), into the
    prize's room carved in the rock - the tube comes up in the room's own pool (q2dm1's rail room has one at the big
    pool's surface), the prize at the back of its dry floor. The room has no other way in."""
    cls, c, z, note = P.items[k]
    for pool in (pools if pools is not None else _pools_near(P, c)[:4]):
        s = P.spaces[pool["space"]]
        zt, zv = pool["bottom"], s.base
        occ = air_spans(P)
        seen, _came = _tube_bfs(P, occ, pool, zt, TUBE_CELLS[1])
        lo, hi = zt, zv + VAULT_CEIL
        found = None
        for e in sorted((e for e, v_ in seen.items() if v_[0] >= TUBE_CELLS[0]), key=lambda e: (abs(seen[e][0] - 8), e)):
            path = _path_to(seen, e)
            on = set(path)
            for (w, h) in ((3, 3), (3, 2), (2, 3)):
                for ox in range(-w, 2):
                    for oy in range(-h, 2):
                        R = [(e[0] + ox + i_, e[1] + oy + j_) for i_ in range(w) for j_ in range(h)]
                        if on & set(R):
                            continue
                        side = [r for r in R if abs(r[0] - e[0]) + abs(r[1] - e[1]) == 1]
                        if len(side) != 1:
                            continue
                        v = side[0]
                        # the room's pool: the row (the column) the tube comes up into
                        wet = [r for r in R if r[0] == v[0]] if v[0] != e[0] else [r for r in R if r[1] == v[1]]
                        dry = [r for r in R if r not in wet]
                        if len(dry) < 3:
                            continue
                        if not all(_rock(P, occ, r, lo, hi, frozenset(R)) for r in R):
                            continue
                        # the tube's other cells keep off the room (its water opens into the room's pool alone)
                        if any(abs(p_[0] - r[0]) + abs(p_[1] - r[1]) == 1 for p_ in path[:-1] for r in R):
                            continue
                        far = max(dry, key=lambda r: (min(abs(r[0] - x[0]) + abs(r[1] - x[1]) for x in wet), -abs(r[0] - v[0]) - abs(r[1] - v[1])))
                        # the prize's seconds and place past the tube's mouth: the swim (150 u/s), up the room's pool
                        mouth = min((x for x in pool["cells"] if abs(phys(x)[0] - path[0][0]) + abs(phys(x)[1] - path[0][1]) == 1),
                                    default=pool["cells"][0])
                        extra = (len(path) + 2) * CELL / 150.0 + (zv - zt) / 150.0
                        at = _item_at(far, zv)
                        if not majors_apart(P, cls, mouth, zt, times_of, skip=k, extra=extra, at=at)                                 or not _halves_ok(P, k, mouth, times_of, extra=extra):
                            continue
                        found = (path, R, wet, dry, far)
                        break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        if not found:
            continue
        path, R, wet, dry, far = found
        V = Space(len(P.spaces), "nook", Rect(min(x[0] for x in R), min(x[1] for x in R),
                                              max(x[0] for x in R) + 1, max(x[1] for x in R) + 1), base=zv)
        V.floor = {r: ((zt, "flat", 0, 0) if r in wet else (zv, "flat", 0, 0)) for r in R}
        V.ceil = zv + VAULT_CEIL
        V.pattern = "flat"
        P.spaces.append(V)
        for r in R:
            P.owner[r] = V.id
        if s.id in P.half:
            P.half[V.id] = P.half[s.id]
        _lay_tube(P, occ, path, zt, s.id, V.id)
        P.asked.add(V.id)
        P.liquids.append((list(wet), "water", zt, zv - POOL_SURFACE))
        P.no_items.update(wet)
        held.update(list(R) + [wl(x) for x in path])
        P.items[k] = (cls, far, zv, (f"{note}; " if note else "") + f"under water: a tube {len(path) * CELL} u from a pool to its room (q2dm1)")
        P.pedestals = list(getattr(P, "pedestals", None) or []) + [(far, zv, cls)]
        P.metrics.setdefault("prize_tubes", []).append([cls, len(path)])
        _serve(P, pool)
        P.reasons.append((cls, say(f"приз в комнате за подводной трубой {len(path) * CELL} ед. из бассейна зала {s.id} - туда только плыть",
                                   f"the prize in a room past a tube {len(path) * CELL} u under water from hall {s.id}'s pool - one swims there")))
        return True
    return False


def _dive_pool(P: Plan, k: int, held: set, times_of, pools=None) -> bool:
    """At a deep pool's bottom, off its sides (q2dm2's quad in a pool 216 deep): one dives for it."""
    cls, c, z, note = P.items[k]
    for pool in (pools if pools is not None else _pools_near(P, c)[:4]):
        cells = set(pool["cells"])
        sp = P.spaces[pool["space"]]
        inner = [x for x in cells if x not in held and sp.floor.get(x, (None,))[0] == pool["bottom"]]
        inner.sort(key=lambda x: (-sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (x[0] + dx, x[1] + dy) in cells),
                                  abs(x[0] - c[0]) + abs(x[1] - c[1])))
        for x in inner[:6]:
            if majors_apart(P, cls, x, pool["bottom"], times_of, skip=k) and _halves_ok(P, k, x, times_of):
                held.add(x)
                P.items[k] = (cls, x, pool["bottom"], (f"{note}; " if note else "") + f"under water: at a pool's bottom {pool['surface'] - pool['bottom']} deep (q2dm2)")
                P.reasons.append((cls, say("приз на дне глубокого бассейна - за ним нырять",
                                           "the prize at a deep pool's bottom - one dives for it")))
                _serve(P, pool)
                return True
    return False


def _mover_ledges(P: Plan, kind: str) -> list:
    """The places only a lift (a ladder) leads into: (space id, the mover's cells, the ledge's floor or None)."""
    deg = {}
    for d in P.doors:
        if d.kind == "overlook":
            continue
        deg[d.a] = deg.get(d.a, 0) + 1
        deg[d.b] = deg.get(d.b, 0) + 1
    found = []
    if kind == "lift":
        for (plat, zl, zh, bottom, top) in P.lifts:
            d = next((d for d in P.doors if d.kind == "lift" and list(d.cells) == list(top)), None)
            if d is None:
                continue
            hi = d.b if d.a == P.owner.get(plat[0]) else d.a
            if deg.get(hi, 0) == 1:
                found.append((hi, list(d.cells), None))
    else:
        for (cells, into, zl, zh, front) in P.ladders:
            d = next((d for d in P.doors if d.kind == "ladder" and list(d.cells) == list(cells)), None)
            if d is None:
                continue
            hi = d.a if P.owner.get(front[0]) == d.b else d.b
            if deg.get(hi, 0) == 1:
                found.append((hi, list(cells), zh))
    return found


def _mover_ledge(P: Plan, k: int, kind: str, held: set, times_of) -> bool:
    """A ledge only a lift (a ladder) reaches - its place has that one way in - the cell nearest its middle."""
    cls, c, z, note = P.items[k]
    if note.startswith("lift as exposure") or note.startswith("ladder under"):
        return True
    for sid, away, zz in _mover_ledges(P, kind):
        s = P.spaces[sid]
        cx, cy = (s.rect.x0 + s.rect.x1) / 2, (s.rect.y0 + s.rect.y1) / 2
        cand = sorted((x for x, f in s.floor.items() if f[1] == "flat" and x not in held and (zz is None or f[0] == zz)
                       and min(max(abs(x[0] - t[0]), abs(x[1] - t[1])) for t in away) >= 2),
                      key=lambda x: abs(x[0] + 0.5 - cx) + abs(x[1] + 0.5 - cy))
        for x in cand:
            if majors_apart(P, cls, x, s.floor[x][0], times_of, skip=k) and _halves_ok(P, k, x, times_of):
                held.add(x)
                P.items[k] = (cls, x, s.floor[x][0], (f"{note}; " if note else "") + f"only a {kind} reaches it")
                return True
    return False


def _open_spot(P: Plan, k: int, held: set, times_of) -> bool:
    """The open middle of a place three ways or more lead into (q2duel5's railgun under fire from three sides)."""
    cls, c, z, note = P.items[k]
    deg = {}
    for d in P.doors:
        deg[d.a] = deg.get(d.a, 0) + 1
        deg[d.b] = deg.get(d.b, 0) + 1
    for s in sorted((s for s in P.spaces if not s.solid and deg.get(s.id, 0) >= 3 and s.kind in ("hall", "room")
                     and s.floor and layer_of(next(iter(s.floor))) == 0),
                    key=lambda s: (-deg.get(s.id, 0), -len(s.floor))):
        cx, cy = (s.rect.x0 + s.rect.x1) / 2, (s.rect.y0 + s.rect.y1) / 2
        cand = sorted((x for x, f in s.floor.items() if f[1] == "flat" and x not in held
                       and all((x[0] + dx, x[1] + dy) in s.floor for dx in (-1, 0, 1) for dy in (-1, 0, 1))),
                      key=lambda x: abs(x[0] + 0.5 - cx) + abs(x[1] + 0.5 - cy))
        for x in cand[:40]:
            if majors_apart(P, cls, x, s.floor[x][0], times_of, skip=k) and _halves_ok(P, k, x, times_of):
                held.add(x)
                P.items[k] = (cls, x, s.floor[x][0], (f"{note}; " if note else "") + "in the open where three ways meet")
                return True
    return False


def majors_repair(P: Plan) -> None:
    """The PO 12.11 («никогда арморы не лежат рядом»): a nook takes its prize two cells back and sometimes into the next
    room - and a weapon or an armour placed before is then near it. Each pair still near: the one that is neither a
    prize nor held by a mechanic (a nook, a dive, a mover's ledge, the open spot, the key gun, the asymmetry's gun, the
    mechanics' pinned places, the stack's own) moves to the free floor farthest on foot from every major that keeps the
    rule. A few rounds; what cannot move is left for the score and the map's check to say."""
    if OLD_MAJORS or P.prize_kind is None:
        return
    nodes, edges = plan_graph(P)
    cache: dict = {}

    def times_of(c):
        if c not in cache:
            cache[c] = dijkstra(edges, c)
        return cache[c]
    fixed_notes = ("stack of", "key gun", "asymmetry", "lift as", "ladder", "dead-end", "teleport to", "armour by",
                   "adrenaline tucked", "in a nook", "under water", "only a", "in the open", "cycle")

    def movable(k):
        cls, c, z, note = P.items[k]
        return (major_kind(cls) is not None and k not in P.prize_kind
                and not any(note.startswith(f) or f"; {f}" in note for f in fixed_notes) and cls not in POWERUPS)

    def near_pairs():
        out = []
        its = [k for k, it in enumerate(P.items) if major_kind(it[0])]
        for i, a in enumerate(its):
            ca, za = P.items[a][1], P.items[a][2]
            for b in its[i + 1:]:
                cb, zb = P.items[b][1], P.items[b][2]
                if ca == cb:
                    continue
                t_need, d_need = majors_need(P.items[a][0], P.items[b][0], P.params)
                t = min(times_of(ca).get(cb, 99.0), times_of(cb).get(ca, 99.0))
                if majors_close(math.dist(_item_at(ca, za), _item_at(cb, zb)), t, t_need, d_need):
                    out.append((a, b))
        return out
    moved = 0
    for _round in range(4):
        pairs = near_pairs()
        if not pairs:
            break
        held = _prize_held(P)
        floor = [c for c, f in nodes.items() if f[1] == "flat" and c in edges and c not in held and P.owner.get(c) is not None
                 and P.spaces[P.owner[c]].kind != "nook" and len(edges.get(c, [])) >= 3]
        done = set()
        for a, b in pairs:
            k = b if movable(b) else a if movable(a) else None
            if k is None or k in done:
                continue
            cls = P.items[k][0]

            def spread(c):
                # on foot from every other major to it (their walks are kept; a walk from each candidate is not)
                return min((times_of(it[1]).get(c, 99.0) for j, it in enumerate(P.items) if j != k and major_kind(it[0])),
                           default=99.0)
            best, loose = None, None
            for c in floor:
                if c in held:
                    continue
                score_ = spread(c)
                if loose is None or score_ > loose[0]:
                    loose = (score_, c)
                if (best is None or score_ > best[0]) and majors_apart(P, cls, c, nodes[c][0], times_of, skip=k):
                    best = (score_, c)
            if best is None and loose is not None and loose[0] > spread(P.items[k][1]) + 0.3:
                best = loose            # nothing keeps the rule on this skeleton: at least farther than it stands
            if best is None:
                continue
            c = best[1]
            cls_, _c0, _z0, note = P.items[k]
            P.items[k] = (cls_, c, nodes[c][0], (f"{note}; " if note else "") + "moved apart from the majors")
            held.add(c)
            done.add(k)
            moved += 1
    P.metrics["majors_moved"] = moved


ROUND_KINDS = ("corners", "apses", "podiums")
ROUND_AMOUNT = {"few": (0.3, 0.5, 1, 1), "some": (0.6, 0.75, 2, 2), "many": (0.9, 1.0, 4, 3)}


def stack_pair_time(P: Plan, edges=None):
    """Brief 22 D3 (Fable 06.11): the walk time between the clock's two stack items as they stand now (the plan's
    graph), or None. `places` measured it where it put them; a powerup moved to a nook of another room changed it and
    the score went on with the old one (a trial FFA-8 failed its clock row at 4.5 s with a plan scored fine)."""
    pair = P.metrics.get("stack_pair") or []
    if len(pair) != 2:
        return None
    at = {}
    for (cls, c, _z, _n) in P.items:
        if cls in pair and cls not in at:
            at[cls] = c
    if len(at) != 2:
        return None
    if edges is None:
        _nodes, edges = plan_graph(P)
    t = dijkstra(edges, at[pair[0]]).get(at[pair[1]])
    return None if t is None else round(t, 2)


def button_cells(P: Plan) -> set:
    """Brief 22 D1 (Fable 06.11): the cells of the powerups' buttons - their wall is kept bare (no lamp post, pilaster,
    decor panel, chamfer, jog or column): 15 of 102 buttons were built into one in 3.46's plans."""
    return {c for (c, *_r) in getattr(P, "buttons", [])}


def _round_held(P: Plan) -> set:
    """Cells a round shape keeps off: what stands there and what a doorway, a window or a ladder needs before it."""
    held = ({c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns} | set(P.no_items)
            | {c for d in P.doors for c in d.cells} | {c for (cs, *_r) in P.lifts for c in cs}
            | {c for (cs, _b, _sid) in P.pits for c in cs} | {c for (c, *_r) in P.pillars}
            | {c for (cells, *_r) in P.liquids for c in cells} | {c for (cells, *_w) in P.windows for c in cells}
            | {c for (*_r, front) in P.ladders for c in front} | {c for (src, dst, *_r) in P.pads for c in (src, dst)}
            | {c for t in P.teleports for c in t} | {c for (c, *_r) in getattr(P, "pedestals", [])}
            | {c for (c, *_r) in getattr(P, "buttons", [])} | set(P.rounded) | P.fx_cells)
    for d in P.doors:
        for c in d.cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                held.add((c[0] + dx, c[1] + dy))
    for (cells, *_w) in P.windows:
        for c in cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                held.add((c[0] + dx, c[1] + dy))
    for (cells, *_r) in P.overlooks:
        for c in cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                held.add((c[0] + dx, c[1] + dy))
    return held


def _arc(corner: str, cx: float, cy: float, r: float, segs: int):
    """The quarter arc of a rounded corner: the corner point and the arc from one wall to the other (integer points).
    `corner` names the room's corner: sw, se, ne, nw; (cx, cy) its point in units."""
    o = {"sw": (cx + r, cy + r, 180), "se": (cx - r, cy + r, 270), "ne": (cx - r, cy - r, 0), "nw": (cx + r, cy - r, 90)}[corner]
    pts = []
    for i in range(segs + 1):
        a = math.radians(o[2] + 90 * i / segs)
        pts.append((int(round(o[0] + r * math.cos(a))), int(round(o[1] + r * math.sin(a)))))
    return (int(cx), int(cy)), pts


def _arc_cells(corner_pt, arc_pts):
    """The cells the fill between a corner and its arc takes a part of: a cell is kept when the fill does not reach its
    middle nor its four points 16 u in from its corners - a sliver of 16 u or less at its edge (where an apse's arc
    meets the end wall's middle) takes neither a doorway's room nor an item's: an apse was refused for its door's front
    cell in 179 of 208 tries (05.11)."""
    xs = [corner_pt[0]] + [p[0] for p in arc_pts]
    ys = [corner_pt[1]] + [p[1] for p in arc_pts]
    out = set()
    tris = [(corner_pt, arc_pts[i], arc_pts[i + 1]) for i in range(len(arc_pts) - 1)]

    def inside(px, py):
        for a, b, c in tris:
            d1 = (px - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (py - b[1])
            d2 = (px - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (py - c[1])
            d3 = (px - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (py - a[1])
            neg = d1 < 0 or d2 < 0 or d3 < 0
            pos = d1 > 0 or d2 > 0 or d3 > 0
            if not (neg and pos):
                return True
        return False
    for gx in range(int(min(xs)) // CELL - 1, int(max(xs)) // CELL + 1):
        for gy in range(int(min(ys)) // CELL - 1, int(max(ys)) // CELL + 1):
            probes = [(gx * CELL + CELL / 2, gy * CELL + CELL / 2)] + [
                (gx * CELL + u, gy * CELL + v) for u in (16, CELL - 16) for v in (16, CELL - 16)]
            if any(inside(px, py) for px, py in probes):
                out.add((gx, gy))
    return out


def _octagon(x0: float, y0: float, x1: float, y1: float, cut: float):
    c = cut
    return [(int(x0 + c), int(y0)), (int(x1 - c), int(y0)), (int(x1), int(y0 + c)), (int(x1), int(y1 - c)),
            (int(x1 - c), int(y1)), (int(x0 + c), int(y1)), (int(x0), int(y1 - c)), (int(x0), int(y0 + c))]


def round_shapes(P: Plan, rnd: random.Random) -> None:
    """medusa_b1's round architecture (measured 05.11, tools/mapgen_round_survey.py: 38 % of its wall area off the two
    axes, 39 directions, 113 many-sided flat-topped brushes): its halls end in half-polygons (apses), a gallery runs
    round them, its corners are cut and rounded, its stage and daises are octagons a step or two over the floor. By
    `round` (none, few, some, many) and `round_kinds` (corners, apses, podiums):
      corners - a room's or a hall's corner filled to a quarter arc of 2..3 cells (3..4 straight pieces);
      apses   - a hall's or a room's short end, 4..8 cells wide, made a half-polygon (two quarter arcs of half its width);
      podiums - an octagon 3..4 cells across, 16 over the floor (a step, walked onto), a second tier 16 more inside it;
                under an item of the hall when one stands clear (the item on top, as medusa's stage), else in the hall's
                open floor.
    Only where nothing stands, no doorway, window, ladder or lift needs the room, the floor is level and one space's;
    not in a room over a room."""
    q = P.params
    amount = q.get("round") or ""
    if amount not in ROUND_AMOUNT:
        P.metrics["round"] = None
        return
    kinds = set(q.get("round_kinds") or ROUND_KINDS)
    p_space, p_corner, n_apse, n_pod = ROUND_AMOUNT[amount]
    held = _round_held(P)
    made = {"corners": 0, "apses": 0, "podiums": 0}

    def level_block(s, cells):
        zs = set()
        for c in cells:
            f = s.floor.get(c)
            if f is None or f[1] != "flat":
                return None
            zs.add(f[0])
        return zs.pop() if len(zs) == 1 else None

    def try_corner(s, corner, r_units, segs, kind):
        # under a roof only: a court's walls stand lower than its sky, and the fill up to the sky stuck out over them
        # as a thin spike against the sky (the first round maps' covers, 05.11)
        if s.sky:
            return False
        r = s.rect
        x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
        cx, cy = {"sw": (x0, y0), "se": (x1, y0), "ne": (x1, y1), "nw": (x0, y1)}[corner]
        pt, arc = _arc(corner, cx * CELL, cy * CELL, r_units, segs)
        cells = _arc_cells(pt, arc)
        if not cells or any(c not in s.floor or c in held or is_up(c) for c in cells):
            return False
        # a real corner: the cells beyond the two walls are not this space's
        for c in cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n not in s.floor and (n in held or P.owner.get(n) == s.id):
                    return False
        z = level_block(s, cells)
        if z is None:
            return False
        P.rounds.append((pt, arc, z, s.ceil, s.id, kind))
        P.rounded.update(cells)
        held.update(cells)
        return True

    live = [s for s in P.spaces if not s.solid and s.kind in ("hall", "room") and s.floor
            and not any(is_up(c) for c in s.floor)]
    rnd.shuffle(live)
    # apses first: a short end made a half-polygon
    if "apses" in kinds:
        for s in sorted(live, key=lambda s_: -s_.area()):
            if made["apses"] >= n_apse:
                break
            r = s.rect
            w_, h_ = r.w, r.h
            ends = []
            if 3 <= w_ <= 8 and h_ >= w_ // 2 + 2:
                ends += [("sw", "se"), ("nw", "ne")]          # the ends across x (bottom, top)
            if 3 <= h_ <= 8 and w_ >= h_ // 2 + 2:
                ends += [("sw", "nw"), ("se", "ne")]          # the ends across y (left, right)
            rnd.shuffle(ends)
            for a, b in ends:
                half = (w_ if a[0] == b[0] else h_) * CELL / 2
                snap = (list(P.rounds), set(P.rounded), set(held))
                if try_corner(s, a, half, 4, "apse") and try_corner(s, b, half, 4, "apse"):
                    made["apses"] += 1
                    break
                P.rounds[:], P.rounded, held = snap[0], snap[1], snap[2]
    if "corners" in kinds:
        for s in live:
            if rnd.random() > p_space:
                continue
            r = s.rect
            if min(r.w, r.h) < 5:
                continue
            for corner in ("sw", "se", "ne", "nw"):
                if rnd.random() > p_corner:
                    continue
                rc = 3 if min(r.w, r.h) >= 9 and rnd.random() < 0.5 else 2
                if try_corner(s, corner, rc * CELL, 3 if rc == 2 else 4, "corner"):
                    made["corners"] += 1
    if "podiums" in kinds:
        halls = [s for s in live if s.kind in ("hall", "room") and min(s.rect.w, s.rect.h) >= 5]
        rnd.shuffle(halls)
        items_at = {}
        for k, (cls, c, z, note) in enumerate(P.items):
            items_at.setdefault(c, []).append(k)
        spawns_at = {c for (c, _z, _a) in P.spawns}
        for s in halls:
            if made["podiums"] >= n_pod:
                break
            size = 4 if min(s.rect.w, s.rect.h) >= 9 else 3
            # an item of this hall standing clear first (the stage under it), then the hall's open floor
            spots = []
            for c, ks in items_at.items():
                if P.owner.get(c) == s.id and not any(P.items[k][0] in POWERUPS for k in ks):
                    spots.append((0, c))
            for c in s.floor:
                spots.append((1 + rnd.random(), c))
            spots.sort()
            for _p, c in spots:
                x0c, y0c = c[0] - (size - 1) // 2, c[1] - (size - 1) // 2
                foot = [(x, y) for x in range(x0c, x0c + size) for y in range(y0c, y0c + size)]
                ring = [(x, y) for x in range(x0c - 1, x0c + size + 1) for y in range(y0c - 1, y0c + size + 1)]
                if any(f not in s.floor for f in ring):
                    continue
                z = level_block(s, ring)
                if z is None:
                    continue
                # nothing round it but an item of its own foot (not a powerup - those have their places): the item
                # rides up with the podium
                def rides(f):
                    return (f in foot and f in items_at and f not in P.no_items and f not in P.rounded
                            and not any(P.items[k][0] in POWERUPS for k in items_at[f]))
                # its foot clear (an item of its own riding up); round it no doorway's, ladder's or lift's room taken -
                # an item or a spawn beside it is no matter
                if any(f in spawns_at or (f in held and not rides(f)) for f in foot):
                    continue
                if any(f in held and f not in items_at and f not in spawns_at for f in ring if f not in foot):
                    continue
                X0, Y0, X1, Y1 = x0c * CELL, y0c * CELL, (x0c + size) * CELL, (y0c + size) * CELL
                outer = _octagon(X0 + 8, Y0 + 8, X1 - 8, Y1 - 8, (X1 - X0) * 0.29)
                two = amount != "few" and rnd.random() < (0.5 if amount == "some" else 1.0)
                inner = _octagon(X0 + 56, Y0 + 56, X1 - 56, Y1 - 56, (X1 - X0 - 96) * 0.29) if two else None
                top = z + (32 if inner else 16)
                # the items on it stand on its top (an item on the lower tier where the inner one does not reach)
                for f in foot:
                    for k in items_at.get(f, []):
                        cls, cc, zz, note = P.items[k]
                        px, py = f[0] * CELL + CELL / 2, f[1] * CELL + CELL / 2
                        on_inner = inner is not None and (X0 + 56 + 24 <= px <= X1 - 56 - 24 and Y0 + 56 + 24 <= py <= Y1 - 56 - 24)
                        P.items[k] = (cls, cc, z + (32 if on_inner else 16), (f"{note}; " if note else "") + "on a podium")
                P.podiums.append((outer, inner, z, s.id))
                P.rounded.update(foot)
                held.update(ring)
                made["podiums"] += 1
                break
    P.metrics["round"] = made
    # brief 22 D7 (Fable 06.11): a kind asked and not made is said, with why (the record's refused lines)
    if "apses" in kinds and not made["apses"]:
        P.notes.append(say("полукруглый торец: ни у одного зала или комнаты нет свободного короткого конца шириной 3–8 "
                           "клеток под крышей (у концов проходы, предметы или лестницы)",
                           "half-round end: no hall or room has a free short end 3..8 cells wide under a roof "
                           "(doorways, items or flights at the ends)"))
    if "podiums" in kinds and not made["podiums"]:
        P.notes.append(say("круглое возвышение: ни в одном зале или комнате нет свободного ровного места 5 × 5 клеток",
                           "round platform: no hall or room has free level floor 5 x 5 cells"))
    if "corners" in kinds and not made["corners"]:
        P.notes.append(say("скруглённые углы: ни одного свободного угла под крышей",
                           "rounded corners: no free corner under a roof"))
    P.metrics["round_asked"] = amount


def furnish(P: Plan, rnd: random.Random) -> None:
    # a chamfered corner or a pillar never takes a cell that holds an item, a spawn or a mover: an item on a
    # corner's diagonal stood «empty» in the base and «solid» in the engine's rebuild of it (04.11, ERR_BASELINE
    # «placements do not stand the same way»)
    held = ({c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns} | set(P.no_items)
            | set(P.rounded) | button_cells(P) | P.fx_cells)
    for s in P.spaces:
        if s.solid:
            continue
        r = s.rect
        # chamfer the corners of halls (a 45-degree wall across a corner cell)
        if s.kind == "hall" and rnd.random() < 0.7:
            for corner, c in (("sw", (r.x0, r.y0)), ("se", (r.x1 - 1, r.y0)), ("nw", (r.x0, r.y1 - 1)),
                              ("ne", (r.x1 - 1, r.y1 - 1))):
                f = s.floor.get(c)
                if f is None:
                    continue                    # a corner a powerup's nook took (brief 21+)
                if f[1] == "flat" and c not in held and rnd.random() < 0.75:
                    P.chamfers.append((c, corner, f[0], s.ceil))
        # pillars in big halls, off the terraces' edges
        if s.kind == "hall" and r.w >= 8 and r.h >= 8 and rnd.random() < 0.5:
            for c in ((r.x0 + 2, r.y0 + 2), (r.x1 - 3, r.y0 + 2), (r.x0 + 2, r.y1 - 3), (r.x1 - 3, r.y1 - 3)):
                f = s.floor.get(c)
                if f and f[1] == "flat" and c not in held and all(s.floor.get((c[0] + dx, c[1] + dy), (None, "x"))[1] == "flat"
                                               and s.floor[(c[0] + dx, c[1] + dy)][0] == f[0]
                                               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    P.pillars.append((c, f[0], s.ceil))
        # the lamps last: a wall lamp never stands in a chamfered corner or a pillar (brief 21)
        light_space(P, s)


# --------------------------------------------------------------------------------------------- 7. the score
def score(P: Plan) -> float:
    if P.params.get("shape") in ("space", "tower"):
        return P.metrics.get("score", 999.0)       # brief 25: the space and the tower plans score themselves
    """Penalties against the human bands, measured on the plan's own graph."""
    q = P.params
    nodes, edges = plan_graph(P)
    pen = 0.0
    m = P.metrics
    live = [s for s in P.spaces if not s.solid]
    floor_cells = sum(len(s.floor) for s in live)
    area = floor_cells * CELL * CELL / 1e6
    m["floor_area"] = round(area, 2)
    pen += 4 * max(0.0, abs(area - q["floor_area"]) / q["floor_area"] - 0.1)
    # widths the way the map's measure takes them (mapgen_map_survey: at 40 over the floor, the narrowest of four
    # directions, both ways; <= 192 a corridor, > 448 open) - on the cells of the plan
    widths = plan_widths(P)
    if widths:
        n_w = len(widths)
        widths.sort()
        m["width_median"] = widths[n_w // 2]
        m["share_corridor"] = round(sum(1 for v in widths if v <= 192) / n_w, 2)
        m["share_open"] = round(sum(1 for v in widths if v > 448) / n_w, 2)
        m["share_medium"] = round(1 - m["share_corridor"] - m["share_open"], 2)
        want_o = q.get("openness") or (0.40, 0.50, 0.10)
        pen += 6 * max(0.0, abs(m["share_corridor"] - float(want_o[0])) - 0.12)
        pen += 6 * max(0.0, abs(m["share_medium"] - float(want_o[1])) - 0.12)
        pen += 6 * max(0.0, abs(m["share_open"] - float(want_o[2])) - 0.12)
        pen += 0.03 * max(0.0, 190 - m["width_median"]) + 0.03 * max(0.0, m["width_median"] - 290)
        # and the check's own bands with a margin (corridors 0.25..0.55, halls 0.35..0.65): inside ±12 points of the
        # asked share nothing pushed a plan off the band's edge - the styled duel of 05.11 measured 0.249 / 0.733
        if not q.get("openness"):
            pen += 40 * max(0.0, 0.29 - m["share_corridor"]) + 40 * max(0.0, m["share_medium"] - 0.61)
    # levels
    hist = {}
    for c, f in nodes.items():
        if f[1] == "flat":
            hist[f[0]] = hist.get(f[0], 0) + 1
    tot = sum(hist.values()) or 1
    lv = [z for z, n in hist.items() if n / tot >= 0.05]
    m["levels"] = len(lv)
    pen += 1.5 * abs(len(lv) - q["levels"])
    # items: times
    majors = [(cls, c) for (cls, c, z, n) in P.items if cls in MAJOR_W or cls in ("item_armor_body",
              "item_armor_combat", "item_health_mega", "item_quad")]
    if len(majors) < 4:
        return 1e9
    tm = []
    alt_ok = alt_n = 0
    for i in range(len(majors)):
        ti = dijkstra(edges, majors[i][1])
        for j in range(i + 1, len(majors)):
            t = ti.get(majors[j][1])
            if t is None:
                pen += 20
                continue
            tm.append(t)
    tm.sort()
    m["major_major_median_s"] = round(tm[len(tm) // 2], 2) if tm else 0
    # brief 21: the pairs of majors with another way, as the map's measure takes it (mapgen_map_survey.detour: a disc
    # of 96 u closed half way along the route, another route at most 1.5 times as long) - the corridors with a turn
    # and the rooms over rooms put routes through one lane, and 4 of 10 duel candidates of 05.11 measured 0.39..0.58
    # (band 0.6)
    alt_ok = alt_n = 0
    for i in range(len(majors)):
        for j in range(i + 1, len(majors)):
            r_ = detour_est(edges, majors[i][1], majors[j][1])
            if r_ is None:
                continue
            alt_n += 1
            alt_ok += 1 if r_ <= 1.5 else 0
    m["alt_pairs_est"] = round(alt_ok / alt_n, 2) if alt_n else 1.0
    # on 30 candidates of 05.11 the plan's share ran 0.1 under the map's (correlation 0.71): 0.55 here for the map's 0.6
    pen += 12 * max(0.0, 0.55 - m["alt_pairs_est"])
    lo, hi = (2.5, 7.0) if q["class"] == "duel" else (3.0, 9.0)
    pen += 2 * max(0.0, lo - m["major_major_median_s"]) + 2 * max(0.0, m["major_major_median_s"] - hi)
    # two ways out: the share of spaces with two doors or more
    deg = {}
    for d in P.doors:
        deg[d.a] = deg.get(d.a, 0) + 1
        deg[d.b] = deg.get(d.b, 0) + 1
    m["two_way_spaces"] = round(sum(1 for s in live if deg.get(s.id, 0) >= 2) / max(1, len(live)), 2)
    pen += 4 * max(0.0, 0.7 - m["two_way_spaces"])
    # spawns
    if len(P.spawns) < q["spawns"]:
        pen += 3 * (q["spawns"] - len(P.spawns))
    # brief 35: the plates' radius the spawns kept (PLATES_NEAR unless the spawns asked needed it to give)
    pen += 0.3 * max(0, PLATES_NEAR - int(m.get("plates_near", PLATES_NEAR)))
    pen += 0.5 * max(0, 3 - sum(1 for s in live if s.kind == "hall"))
    # what was asked by count: every lift, pad and teleporter pair short is a heavy penalty
    got = {"lifts": len(P.lifts), "pads": len(P.pads), "teleporters": len(P.teleports), "ladders": len(P.ladders),
           "doors": sum(1 for d in P.doors if d.mover), "pits": len(P.pits), "ramps": m.get("ramps_got", 0)}
    for k, n in got.items():
        want = int(q.get(k) or 0)
        m[f"{k}_got"] = n
        pen += 6 * abs(want - n)
    # minimums: flights of steps and one-way drops (by levels when not asked)
    m["drops_got"] = sum(1 for d in P.doors if d.kind in ("drop", "overlook"))
    for k in ("stairs", "drops"):
        want = int(q.get(k) or 0)
        n = m.get(f"{k}_got", 0)
        pen += (1 if q.get(f"{k}_default") else 4) * max(0, want - n)
    # the long sight lines (estimated on the plan; the survey measures them on the map)
    m["long_lines_est"] = long_lines(P)
    # the share of places that see each other (D7: 6..20 % duel, 5..20 % FFA), on the same sampling
    vp = m.get("visible_pairs_est", 0.13)
    pen += 40 * max(0.0, vp - 0.18) + 40 * max(0.0, 0.07 - vp)
    want = int(q.get("long_lines") or 0)
    # the check holds asked .. asked + 3 (none asked: two at most); the plan's sampling finds a little less than the map
    # a line over the cap the column did not close costs as a failed check would (05.11: 8 of the styled duel's 10
    # candidates measured over N+1)
    pen += (0 if q.get("long_lines_default") else 3) * max(0, want - m["long_lines_est"])         + 8 * max(0, m["long_lines_est"] - lines_cap(P))
    # the mechanics that could not be placed on this seed
    pen += 5 * len(m.get("mech_missing") or [])
    if P.half and m.get("half_crossings") is not None and not (1 <= m["half_crossings"] <= 2):
        pen += 5
    total = sum(len(s.floor) for s in live) or 1
    for kind in ("water", "lava", "slime"):
        share = sum(len(c) for c, k, _, _ in P.liquids if k == kind) / total
        m[f"{kind}_share"] = round(share, 3)
        want = float(q.get(kind) or 0)
        if want > 0:
            pen += 60 * max(0.0, want * 0.7 - share) + 20 * max(0.0, share - want * 1.8)
    # brief 22 D3: the pair as it stands on the finished plan (the powerups' nooks, the jogs and columns after them)
    t_now = stack_pair_time(P, edges)
    if t_now is not None and m.get("stack_apart_s") is not None:
        m["stack_apart_s"] = t_now
    if "clock" in (q.get("mechanics") or []) and m.get("stack_apart_s") is not None:
        lo_c, hi_c = (5.0, 9.0) if q["class"] == "duel" else (4.0, 12.0)
        pen += 2 * max(0.0, lo_c - m["stack_apart_s"]) + 2 * max(0.0, m["stack_apart_s"] - hi_c)
    stack_at = [c for (cls, c, z, n) in P.items if cls in MAJOR_ITEMS]
    if P.spawns and stack_at:
        ts = sorted(min(dijkstra(edges, sp).get(s_, 99) for s_ in stack_at) for (sp, _z, _a) in P.spawns)
        m["spawn_to_stack_est"] = round(ts[len(ts) // 2], 2)
        pen += 2 * max(0.0, m["spawn_to_stack_est"] - (3.3 if q["class"] == "duel" else 4.7))
    if "halves" in (q.get("mechanics") or []):
        rg = next((c for (cls, c, z, n) in P.items if cls == "weapon_railgun"), None)
        ra = next((c for (cls, c, z, n) in P.items if cls in ("item_armor_body", "item_health_mega")), None)
        if rg and ra:
            m["rg_ra_est"] = round(dijkstra(edges, rg).get(ra, 99), 2)
            # the map's walk takes 0.83..0.97 of the plan's time (ten duels of 05.11) - 7 s on the map asks 8.5 here
            pen += 3 * max(0.0, 8.5 - m["rg_ra_est"])
    mech = set(q.get("mechanics") or [])
    missing = list(m.get("mech_missing") or [])
    # route asymmetry (brief 19 §6: one major pair A->B at least 2.5 times B->A)
    if "asymmetry" in mech:
        tt = {i: dijkstra(edges, majors[i][1]) for i in range(len(majors))}
        best_r = 0.0
        for i in range(len(majors)):
            for j in range(len(majors)):
                if i != j:
                    tij, tji = tt[i].get(majors[j][1]), tt[j].get(majors[i][1])
                    if tij and tji and tji >= 0.6:
                        best_r = max(best_r, tij / tji)
        m["asymmetry_est"] = round(best_r, 2)
        if best_r < 2.6:
            pen += 4 + 2 * (2.6 - best_r)
            text = say(f"asymmetry: самая неравная пара главных предметов {best_r:.1f}x (нужно 2.5x)",
                       f"asymmetry: the most unequal pair of majors is {best_r:.1f}x (2.5x asked)")
            if not any(x.startswith("asymmetry") for x in missing):
                missing.append(text)
    m["mech_missing"] = missing
    # cells a route lost leaves out of reach
    pen += 3.0 * m.get("stranded_cells", 0)
    # brief 21: the rooms over rooms asked (by the levels) and not made
    st_want, st_got = int(m.get("stacked_asked") or 0), int(m.get("stacked_rooms") or 0)
    pen += 6 * max(0, min(1, st_want) - st_got) + 2 * max(0, st_want - max(1, st_got))
    # the counts asked and not had, with their reason
    reasons = {"lifts": ("меньше подъёмов в 128 и выше с ровным полом перед проходом", "fewer rises of 128 or more with level floor before the doorway"),
               # brief 34: the pads' own rules said too - three cells apart, none beside a stair to the same ledge
               "pads": ("меньше мест, где полёт джампада не задевает стен и потолка, до другого джампада не меньше трёх клеток "
                        "и к площадке рядом не ведёт лестница",
                        "fewer places where a pad's flight misses walls and ceiling, three cells from another pad at least "
                        "and no stair near by leading to the ledge"),
               # brief 35: a pair is made only where it joins other places than the pairs before it
               "teleporters": ("ещё одна пара вела бы в те же места, что уже связанные, или стояла бы рядом с джампадом "
                               "или точкой появления",
                               "one more pair would join the places already joined, or stand beside a jump pad or a spawn "
                               "point"),
               "ladders": ("меньше подъёмов 96..320 с ровным полом у стены", "fewer rises of 96..320 with level floor at the wall"),
               "doors": ("меньше ровных проходов в 2-3 клетки", "fewer level doorways two or three cells wide"),
               "pits": ("меньше залов с провалом посередине", "fewer halls with a sunken middle"),
               "ramps": ("меньше пролётов ступеней", "fewer flights of steps")}
    notes = [n_ for n_ in P.notes if not any(n_.startswith(k_) for k_ in ("лифт", "джампад", "телепорт", "стремян", "двер", "смерт", "пандус"))]
    words = {"lifts": ("лифтов", "lifts"), "pads": ("джампадов", "jump pads"), "teleporters": ("телепортов (пар)", "teleporter pairs"),
             "ladders": ("стремянок", "ladders"), "doors": ("дверей", "doors"), "pits": ("смертельных ям", "deadly pits"),
             "ramps": ("пандусов", "ramps")}
    for k, (ru, en) in reasons.items():
        want_k, got_k = int(q.get(k) or 0), int(m.get(f"{k}_got") or 0)
        if got_k < want_k:
            notes.append(say(f"{words[k][0]}: {got_k} из {want_k} - {ru}", f"{words[k][1]}: {got_k} of {want_k} - {en}"))
    # the opening race (brief 19 §6): from the spawns to the key gun
    key_at = next((c for (cls, c, z, n) in P.items if cls == "weapon_railgun"), None) or \
        next((c for (cls, c, z, n) in P.items if cls in MAJOR_W), None)
    if key_at and P.spawns:
        rev = {}
        for c_, es in edges.items():
            for n_, w_ in es:
                rev.setdefault(n_, []).append((c_, w_))
        tk = dijkstra(rev, key_at)
        ts = sorted(round(tk.get(c, 99), 1) for (c, _z, _a) in P.spawns)
        m["opening_race"] = ts
    P.notes[:] = notes
    # the windows asked are the skeleton's: those `show_more` adds to a plain room (brief 21 D5) are its own, not the
    # parameter's (the default FFA-8 05.11: 5 for 4 asked - one shown into a bare box)
    m["windows_got"] = len(P.windows) - int(m.get("windows_shown") or 0)
    # 3.46: the round shapes asked - «some» and «many» want each kind ticked on the map (the first FFA-8 «many» chose
    # a skeleton with five corners, no apse, no podium); «few» one of any kind
    rm = m.get("round")
    if q.get("round") and rm is not None:
        if q["round"] == "few":
            pen += 4 * (sum(rm.values()) == 0)
        else:
            pen += (8 if q["round"] == "many" else 5) * sum(1 for k_ in q.get("round_kinds") or [] if not rm.get(k_))
    m["refused"] = list(P.notes)
    pen += 2 * max(0, int(q.get("windows") or 0) - len(P.windows))
    # the major items at height as the map's measure takes it (brief 21: the base is the lowest level holding a tenth
    # of the floor; 7 of 20 candidates of 05.11 measured 100 % for 67 % asked)
    zs_all = sorted(nodes[c][0] for c in nodes if nodes[c][1] == "flat")
    if zs_all:
        import mapgen_map_survey as _sv
        base_lv = min((z for z, _sh in _sv.levels_of(zs_all, 0.10)), default=zs_all[0])
        mj = [z for (cls, c, z, n_) in P.items if cls in _sv.MAJORS]
        if mj:
            m["majors_high"] = round(sum(1 for z in mj if z >= base_lv + 64) / len(mj), 2)
            pen += 6 * max(0.0, abs(m["majors_high"] - float(q.get("items_at_height") or 0.67)) - 0.15)
    # two thirds of the spawns at height (D7 band: half at least)
    if P.spawns:
        zs_ = sorted(nodes[c][0] for c in nodes if nodes[c][1] == "flat")
        # the map's base (brief 21), else the tenth of the floor's heights
        low_ = base_lv if zs_all else (zs_[len(zs_) // 10] if zs_ else 0)
        m["spawns_high"] = round(sum(1 for (c, z, a) in P.spawns if z >= low_ + 64) / len(P.spawns), 2)
        # brief 20 D5: and not every one - people's maps hold 50..90 % (the 3.3x duel had 7 of 7 up)
        pen += 6 * max(0.0, 0.6 - m["spawns_high"]) + 6 * max(0.0, m["spawns_high"] - 0.9)
    # brief 21: the rows the map's check holds as pass or fail, estimated on the plan - each a step of its own, so a
    # plan estimated to pass them all comes before one a little better on the soft numbers that fails one (05.11:
    # 0 of 10 duel candidates passed every row; each failed one or two of these)
    mech_ = set(q.get("mechanics") or [])
    fails = []
    if "asymmetry" in mech_ and float(m.get("asymmetry_est") or 0) < 2.6:
        fails.append("asymmetry")
    if "halves" in mech_ and m.get("rg_ra_est") is not None and float(m["rg_ra_est"]) < 8.5:
        fails.append("halves")
    lw = int(q.get("long_lines") or 0)
    if m.get("long_lines_est", 0) > lines_cap(P) or (lw and not q.get("long_lines_default") and m.get("long_lines_est", 0) < lw):
        fails.append("long lines")
    if int(m.get("stacked_asked") or 0) and not int(m.get("stacked_rooms") or 0):
        fails.append("rooms over rooms")
    if float(m.get("alt_pairs_est", 1.0)) < 0.55:
        fails.append("alternatives")
    if m.get("majors_high") is not None and abs(float(m["majors_high"]) - float(q.get("items_at_height") or 0.67)) > 0.22:
        fails.append("majors at height")
    if m.get("spawns_high") is not None and not (0.5 <= float(m["spawns_high"]) <= 0.9):
        fails.append("spawns at height")
    for kind in ("water", "lava", "slime"):
        want_l = float(q.get(kind) or 0)
        # the check: within half of the share asked, never over twice (05.11: a styled duel planned at 5 % of 10 %
        # lava came first and measured 4.8 %)
        got_l = float(m.get(f"{kind}_share") or 0)
        # water short of the share is said in the record (the check lets it pass then); over it is not
        if want_l >= 0.05 and (got_l > want_l * 1.8 or (kind != "water" and got_l < want_l * 0.6)):
            fails.append(kind)
    if int(m.get("plain_rooms") or 0):
        fails.append("plain rooms")
    if any("no nook" in k_ for _c, k_ in (m.get("powerup_sites") or [])):
        fails.append("powerups")
    # the PO 12.11: the majors' pick-up worth - none near another (majors_apart)
    m["majors_near"] = [] if OLD_MAJORS else majors_near(P, edges)
    if m["majors_near"]:
        fails.append("majors near")
        pen += 4 * len(m["majors_near"])
    m["dead_end_groups"] = len(door_bridges(P))
    if m["dead_end_groups"]:
        fails.append("dead ends")
    # the PO 12.11 («вот приплыл сюда, а там пусто»): a deep water with no valuable item - a skeleton that has room for
    # one in every water is taken first
    if m.get("pools_empty"):
        fails.append("empty water")
    # and water asked (or a prize under it) with no deep pool at all, or a prize under water fallen back to a nook
    if water_deep(q) and (float(q.get("water") or 0) > 0 or int(q.get("underwater") or 0) > 0) and not P.pools:
        fails.append("no pool")
    if any(k_ == "water" for _c, k_ in (m.get("prize_fell_back") or [])):
        fails.append("prize not under water")
    m["plan_fails"] = fails
    pen += 8 * len(fails)
    m["score"] = round(pen, 2)
    return pen


def plan_widths(P: Plan) -> list:
    """Each standing cell's width as the map's measure takes it: from 40 over its floor, the air reaches along each
    of four directions both ways until a wall, a floor higher than 40 - 8 over it or a ceiling under 56 over it; the
    narrowest direction's span (cells x 64, a diagonal's x 1.41)."""
    air = {}
    for s in P.spaces:
        if s.solid:
            continue
        for c, f in s.floor.items():
            air[c] = (floor_top(f), s.ceil)
    for d in P.doors:
        for c in d.cells:
            air[c] = (d.z + (RISE_PER_CELL if d.stair else 0), d.z + TUBE_H if d.kind == "swim" else (d.top or d.z + DOOR_H))
    for (c, _z0, _z1) in P.pillars:
        air.pop(c, None)
    # nobody stands in lava, slime or a chasm: the map's measure takes no width there (05.11: with 10 % lava the
    # plan counted the pits' narrow floors as corridors - 0.35 planned, 0.249 on the map)
    unstood = {c for (cells, kind, *_r) in P.liquids if kind != "water" for c in cells}
    unstood |= {c for (cells, _b, _sid) in P.pits for c in cells}
    out = []
    for s in P.spaces:
        if s.solid:
            continue
        for c, f in s.floor.items():
            if f[1] != "flat" or c not in air or c in unstood:
                continue
            z = f[0] + 40
            best = 1e9
            for dx, dy, unit in ((1, 0, 64), (0, 1, 64), (1, 1, 90.5), (1, -1, 90.5)):
                span = 1
                for sgn in (1, -1):
                    k = 1
                    while True:
                        n = (c[0] + sgn * dx * k, c[1] + sgn * dy * k)
                        a = air.get(n)
                        if a is None or a[0] > z - 8 or a[1] < z + 16:
                            break
                        span += 1
                        k += 1
                        if k > 40:
                            break
                best = min(best, span * unit)
            out.append(best)
    return out


def long_lines(P: Plan, pairs: int | None = None, lines: bool = False):
    """Distinct long sight lines on the plan, the way the map's measure finds them (mapgen_map_survey: random pairs
    of standing places, eye 46 over each floor, seen when the line between keeps in the air of every cell it
    crosses, pairs over 1000 u grouped into corridors of sight by `distinct_lines`). The first estimate counted rows
    and columns only - 2 where the map had 7 (04.11)."""
    import mapgen_map_survey as sv
    # brief 21: the air of each world cell as spans - a room over a room puts two in one cell, and a line seen
    # through the upper room's doorways was missed while the plan kept its cells apart (05.11: 1..3 planned, the map
    # measured 4..6)
    air = {}
    for s in P.spaces:
        if s.solid:
            continue
        for c, f in s.floor.items():
            air.setdefault(phys(c), []).append((floor_top(f), s.ceil))
    for d in P.doors:
        for c in d.cells:
            air.setdefault(phys(c), []).append((d.z + (RISE_PER_CELL if d.stair else 0),
                                                d.z + TUBE_H if d.kind == "swim" else (d.top or d.z + DOOR_H)))
    for (cells, z0, z1, *_w) in P.windows:
        for c in cells:
            air.pop(c, None)            # glass: not seen through by the measure (WINDOW blocks sight)
    for (c, _z0, _z1) in P.pillars:
        pc = phys(c)
        f = P.spaces[P.owner[c]].floor.get(c) if c in P.owner else None
        # a column stands in its own layer's air only
        air[pc] = [sp for sp in air.get(pc, []) if f is None or not (sp[0] <= floor_top(f) < sp[1])]
    stand = [(phys(c), floor_top(f)) for s in P.spaces if not s.solid for c, f in s.floor.items()
             if f[1] == "flat" and phys(c) in air]
    if len(stand) < 2:
        return 0
    rnd = random.Random(P.seed * 13 + 5)
    found = []
    seen = tried = 0
    if pairs is None:
        # a duel's band is N..N+1: 30000 pairs; a larger map's N..N+3 holds with 15000 (its lines are long and many -
        # 30000 took its skeleton step to 4 minutes)
        pairs = 30000 if P.params.get("class") == "duel" else 15000
    for i_ in range(pairs):
        (a, fa), (b, fb) = rnd.choice(stand), rnd.choice(stand)
        dx, dy = b[0] - a[0], b[1] - a[1]
        if a == b and fa == fb:
            continue
        za, zb = fa + 46, fb + 46
        # over 1000 u between the eyes, as the map's measure (it took 16 cells, 1024 u, until brief 21: a styled duel's
        # line of 1024.5 u by the map was 15 x 4 cells to the plan - 6 lines on the map, 3 planned)
        long_ = (dx * CELL) ** 2 + (dy * CELL) ** 2 + (zb - za) ** 2 > 1000 * 1000
        # the share of places that see each other on the first 8000 pairs (the map's count); after them only the long
        # pairs are walked, for the lines (an FFA-8's skeleton step took 4 minutes walking every pair)
        if i_ >= 8000 and not long_:
            continue
        n = int(max(abs(dx), abs(dy)) * 2) + 1
        ok = True
        for k in range(1, n):
            t = k / n
            c = (int(a[0] + 0.5 + dx * t), int(a[1] + 0.5 + dy * t))
            z = za + (zb - za) * t
            if not any(lo < z < hi - 4 for lo, hi in air.get(c, ())):
                ok = False
                break
        if i_ < 8000:
            tried += 1
            seen += 1 if ok else 0
        if ok and long_:
            found.append((((a[0] + 0.5) * CELL, (a[1] + 0.5) * CELL, za), ((b[0] + 0.5) * CELL, (b[1] + 0.5) * CELL, zb)))
    P.metrics["visible_pairs_est"] = round(seen / max(1, tried), 3)
    groups = sv.distinct_lines(found)
    return groups if lines else len(groups)


def lines_cap(P: Plan) -> int:
    """How many long sight lines a plan may keep: asked N - a duel N or N + 1 (brief 20 D5: «2 asked gave 5»), a
    larger map N .. N + 3 (people's FFA maps hold 4..8); none asked - one on a duel, two elsewhere."""
    want = int(P.params.get("long_lines") or 0)
    duel = P.params.get("class") == "duel"
    if P.params.get("long_lines_default"):
        # people's: a duel 4 at most (the map finds one more than the plan now and then), a larger map 6
        return 3 if duel else 5
    if not want:
        return 1 if duel else 2
    # brief 21: the plan samples 30000 pairs of its cells (8000 until then found 2..3 where the map's 8000 points
    # found 4..5 - every line of the map was open on the plan, the plan's sampling missed it). The map still finds one
    # more now and then (its points 32 apart, the plan's 64): a duel's plan keeps N for the check's N..N+1, a larger
    # map's N + 1 for N..N+3
    return want + (0 if duel else 1)


def cut_off(P: Plan) -> int:
    """Floor cells a player cannot get to from the first spawn and back (the plan's walk both ways)."""
    nodes, edges = plan_graph(P)
    if not P.spawns or P.spawns[0][0] not in nodes:
        return 0
    start = P.spawns[0][0]
    there = dijkstra(edges, start)
    rev = {}
    for c, es in edges.items():
        for n, w in es:
            rev.setdefault(n, []).append((c, w))
    back = dijkstra(rev, start)
    return sum(1 for c, f in nodes.items() if f[1] == "flat" and P.owner.get(c) is not None and c not in P.no_items
               and (c not in there or c not in back))


COLUMNS_PER_SPACE = 1      # brief 21 D3 (the PO 05.11: «нагромождение каких-то странных столбов»)
COLUMNS_PER_HALL = 1
COLUMNS_PER_MAP = 3
COLUMN_ROOM_MIN = 6        # no column in a room under 6 cells a side
JOGS_PER_SPACE = 2
JOGS_PER_MAP = 6


def close_lines(P: Plan) -> None:
    """A long sight line beyond what was asked is closed as people close one (brief 21 D3): first by a jog of the wall
    - a cell of a hall's or a room's edge the line crosses turned to rock, the wall stepping in there (an alcove seen
    from the other side) - and only then by a column, floor to ceiling, at most one per space and three per map and
    none in a room under 6 cells a side (the PO 05.11: two columns three cells apart in a 5 x 11 room, ten on the
    styled duel). Never on a held cell, a doorway or in front of one, a stair, a pit or a lift; never a cell whose
    loss cuts a way (`cut_off`); the jog's lamps go with it."""
    held = ({c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns} | set(P.no_items)
            | {c for d in P.doors for c in d.cells} | {c for (cs, *_r) in P.lifts for c in cs}
            | {c for (cs, _b, _sid) in P.pits for c in cs} | {c for (c, _z0, _z1) in P.pillars}
            | {c for (c, *_r) in P.chamfers} | {c for (cells, *_r) in P.liquids for c in cells} | set(P.rounded)
            | P.fx_cells
            | button_cells(P))
    # nor in front of a doorway, a window or a ladder
    for d in P.doors:
        for c in d.cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                held.add((c[0] + dx, c[1] + dy))
    for (cells, *_w) in P.windows:
        for c in cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                held.add((c[0] + dx, c[1] + dy))
    cap = lines_cap(P)
    columns = {}
    jogs = {}

    def level_sides(s, c, f):
        sides = [(c[0] + dx, c[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        return sides, [n for n in sides if n in s.floor and s.floor[n][1] == "flat" and s.floor[n][0] == f[0]
                       and n not in held]

    def jog_cell(c):
        o = P.owner.get(c)
        if o is None or c in held:
            return None
        s = P.spaces[o]
        f = s.floor.get(c)
        if s.solid or s.kind == "corridor" or not f or f[1] != "flat" or len(s.floor) < 12:
            return None
        if min(s.rect.w, s.rect.h) < 4:
            return None
        if jogs.get(s.id, 0) >= JOGS_PER_SPACE or sum(jogs.values()) >= JOGS_PER_MAP:
            return None
        sides, level = level_sides(s, c, f)
        # at the space's edge: a side on rock (no owner, no doorway or window there)
        rocky = [(n[0] - c[0], n[1] - c[1]) for n in sides if n not in s.floor and P.owner.get(n) is None]
        if not rocky:
            return None
        # and the room stays three cells wide past it (05.11: a jog in a two-cell passage left one cell, and a
        # pilaster in the passage's corner a gap of 24 u - the FFA-8's bay cut off from the rest on the map)
        dx_, dy_ = rocky[0]
        if any((c[0] - dx_ * k, c[1] - dy_ * k) not in s.floor for k in (1, 2, 3)):
            return None
        if len(level) < 1:
            return None
        return s

    def column_cell(c):
        o = P.owner.get(c)
        if o is None or c in held:
            return None
        s = P.spaces[o]
        f = s.floor.get(c)
        if s.solid or s.kind == "corridor" or not f or f[1] != "flat":
            return None
        per = COLUMNS_PER_HALL if s.kind == "hall" and min(s.rect.w, s.rect.h) >= 8 else COLUMNS_PER_SPACE
        if min(s.rect.w, s.rect.h) < COLUMN_ROOM_MIN or columns.get(s.id, 0) >= per:
            return None
        if any(P.owner.get(p) == s.id and abs(phys(p)[0] - phys(c)[0]) + abs(phys(p)[1] - phys(c)[1]) < 4
               for (p, _z0, _z1) in P.pillars):
            return None
        if sum(columns.values()) >= COLUMNS_PER_MAP:
            return None
        sides, level = level_sides(s, c, f)
        if any(n not in s.floor and P.owner.get(n) is not None for n in sides):
            return None
        if len(level) < 2 or sum(1 for n in sides if n in s.floor) < 3:
            return None
        return s, f

    def jog(c, s):
        f = s.floor.pop(c)
        was_owner = P.owner.pop(c, None)
        in_extra = c in s.extra
        if in_extra:
            s.extra.remove(c)
        if cut_off(P) > before:
            s.floor[c] = f
            if was_owner is not None:
                P.owner[c] = was_owner
            if in_extra:
                s.extra.append(c)
            return False
        pc = phys(c)
        x0, y0 = pc[0] * CELL, pc[1] * CELL
        P.lights[:] = [L for L in P.lights if not (x0 <= L[0] < x0 + CELL and y0 <= L[1] < y0 + CELL)]
        P.metrics["wall_jogs"] = int(P.metrics.get("wall_jogs") or 0) + 1
        jogs[s.id] = jogs.get(s.id, 0) + 1
        P.reasons.append(("wall jog", f"уступ стены в {pc}: закрывает линию прострела сверх заказанного"))
        return True
    before = cut_off(P)
    for _ in range(12):
        groups = long_lines(P, lines=True)
        if len(groups) <= cap:
            break
        placed = False
        # the lines found last are the least crowded ones: close from the end
        for ln in reversed(groups):
            a, b = ln["a"], ln["b"]
            mz = (a[2] + b[2]) / 2 - 46
            along = []
            for k in range(1, 48):
                t = k / 48
                c = (int((a[0] + (b[0] - a[0]) * t) // CELL), int((a[1] + (b[1] - a[1]) * t) // CELL))
                if c not in along:
                    along.append(c)
            mx, my = ln["m"][0] / CELL, ln["m"][1] / CELL
            along.sort(key=lambda c: (c[0] + 0.5 - mx) ** 2 + (c[1] + 0.5 - my) ** 2)

            def layer(c):
                # a line over a room over a room runs in the upper one (brief 21)
                o_up = P.owner.get(up(c))
                return up(c) if o_up is not None and mz >= P.spaces[o_up].base - 8 else c
            edge = set()
            for c in map(layer, along):
                o = P.owner.get(c)
                if o is not None and any(P.owner.get((c[0] + dx, c[1] + dy)) is None and (c[0] + dx, c[1] + dy) not in P.spaces[o].floor
                                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    edge.add(c)
            for c in map(layer, along):
                # the line hugs this wall (a neighbour along it is on the line and on the edge too): a jog blocks it
                if not any((c[0] + dx, c[1] + dy) in edge for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    continue
                s = jog_cell(c)
                if s and jog(c, s):
                    held.add(c)
                    placed = True
                    break
            if not placed:
                for c in map(layer, along):
                    got = column_cell(c)
                    if not got:
                        continue
                    s, f = got
                    P.pillars.append((c, f[0], s.ceil))
                    if cut_off(P) > before:
                        P.pillars.pop()
                        held.add(c)
                        continue
                    held.add(c)
                    columns[s.id] = columns.get(s.id, 0) + 1
                    P.reasons.append(("pillar", f"колонна в {phys(c)}: закрывает линию прострела сверх заказанного"))
                    placed = True
                    break
            if placed:
                break
        if not placed:
            break
    P.metrics["line_columns"] = sum(columns.values())


# --------------------------------------------------------------------------------------------- the whole skeleton
# The PO 11.11 (the skeleton's stage of a run): «было бы неплохо визуализировать построение каркаса - там же наверное
# тоже есть что показать как он строится в реальном времени». A plan made again with RECORD set (mapgen_scratch.make,
# for the chosen skeleton only) hands each step's state to it: rec(step, P). None - nothing kept (every plan of the
# 60 a run tries).
RECORD = None


def rec(step: str, P: Plan) -> None:
    if RECORD is not None and not P.failed:
        RECORD(step, P)


def show_state(P: Plan) -> dict:
    """The plan as the Studio draws a step of it: every place's cells at their floor (x, y physical; z; the place's
    kind; its id), the doorways, liquids and pits, lifts, pads, teleporters, items and spawn points so far."""
    kinds = {}

    def kind_of(k: str) -> int:
        return kinds.setdefault(k, len(kinds))
    cells = []
    for s in P.spaces:
        if s.solid:
            continue
        k = kind_of(s.kind)
        if s.floor:
            for c, f in s.floor.items():
                x, y = phys(c)
                cells.append([x, y, int(f[0]), kind_of("stair") if f[1] == "stair" else k, s.id])
        else:
            for c in s.cells():
                x, y = phys(c)
                cells.append([x, y, int(s.base), k, s.id])
    P2 = lambda c: list(phys(c))
    return {
        "kinds": [k for k, _ in sorted(kinds.items(), key=lambda kv: kv[1])],
        "cells": cells,
        "doors": [[*P2(c), int(d.z), 1 if d.mover else 0] for d in P.doors if d.kind != "swim" for c in d.cells],
        "liquids": [[*P2(c), int(level), kind] for (cs, kind, _zf, level) in P.liquids for c in cs
                    if layer_of(c) != WATER_LAYER],
        # the PO 12.11: the tubes under water (under the floors): each cell and the tube's roof
        "tubes": [[*P2(c), int(d.top)] for d in P.doors if d.kind == "swim" for c in d.cells],
        "pits": [[*P2(c), int(bottom)] for (cs, bottom, _sid) in P.pits for c in cs],
        "lifts": [[*P2(plat[0]), int(zl), int(zh)] for (plat, zl, zh, _b, _t) in P.lifts],
        "pads": [[*P2(a), *P2(t)] for (a, t, *_r) in P.pads],
        "teleports": [[*P2(a), *P2(b)] for (a, b, _da, _db) in P.teleports],
        "items": [[cls, *P2(c), int(z)] for (cls, c, z, _n) in P.items],
        "spawns": [[*P2(c), int(z)] for (c, z, _a) in P.spawns],
    }


def make_plan(params: dict, seed: int) -> Plan:
    q = defaults(params)
    rnd = random.Random(seed)
    P = Plan(q, seed, 0, 0)
    if q["shape"] == "space":
        import mapgen_scratch_space as space_mod
        space_mod.plan(P, rnd)
        return P
    if q["shape"] == "tower":
        import mapgen_scratch_tower as tower_mod
        tower_mod.plan(P, rnd)
        return P
    split_plan(P, rnd)
    rec("rooms", P)
    merge_pieces(P, rnd)
    rec("merge", P)
    corridor_pieces(P, rnd)
    rec("corridors", P)
    connect(P, rnd)
    if P.failed:
        return P
    rec("doors", P)
    heights(P, rnd)
    realise(P, rnd)
    rec("heights", P)
    deadly_pits(P, rnd)
    liquids(P, rnd)
    rec("liquids", P)
    openings(P, rnd)
    flights_and_ramps(P, rnd)
    rec("stairs", P)
    moving_doors(P, rnd)
    movers(P, rnd)
    rec("movers", P)
    stack_rooms(P, rnd)
    show_more(P, rnd)
    water_network(P, rnd)       # the PO 12.11: the deep pools joined under water (q2dm2, q2dm4, q2dm5)
    rec("stacked", P)
    places(P, rnd)
    if P.failed:
        return P
    prize_plan(P, rnd)          # the PO 12.11: how each prize is earned
    prize_sites(P, rnd)         # the dives, the movers' ledges, the open spots (the nooks next)
    powerup_sites(P, rnd)
    majors_repair(P)            # the PO 12.11: what the nooks brought near moved apart
    pool_purpose(P)             # the PO 12.11: no deep water without a valuable item in it
    rec("items", P)
    # brief 22 D3: the clock's pair measured again where the powerups' places left them
    if P.metrics.get("stack_apart_s") is not None:
        P.metrics["stack_apart_placed_s"] = P.metrics["stack_apart_s"]
        t_ = stack_pair_time(P)
        if t_ is not None:
            P.metrics["stack_apart_s"] = t_
    # brief 32: the pads', frames' and spawn plates' sizes - before the round shapes, lamps and columns, which keep off
    # the cells the bigger ones reach
    import mapgen_scratch_fixtures as fix_mod
    fix_mod.plan_sizes(P)
    round_shapes(P, rnd)
    furnish(P, rnd)
    close_lines(P)
    P.metrics["pads_no_reason"] = len(pads_without_reason(P))     # brief 34
    return P


def _plan_of(args: tuple) -> tuple | None:
    """One seed's plan and its score, or None when it failed - a worker of `best_plan`'s pool."""
    params, s = args
    P = make_plan(params, s)
    return None if P.failed else (score(P), P)


def best_plan(params: dict, seed: int, tries: int = 60, workers: int = 1, progress=None, seen=None) -> list:
    """Plans of `tries` seeds derived from the one asked, best first.

    Brief 24 D3.1 (Fable 06.11, the PO: «ограничение процессора 80 %, а реально студия юзает гораздо меньше»): the seeds
    over a pool of `workers` processes. Each seed's plan is made exactly as the loop makes it (its own `random.Random`,
    no shared state - checked 06.11), the results come back in the seeds' order (`imap`), and the same stable sort
    gives the same list: tools/check_mapgen_scratch_parallel.py proves pool 1 = pool N. `progress(done, tries)` is
    called every ten seeds (the Studio's run page reads it from the tool's log). `seen(done, tries, result)` (the PO
    12.11: the skeleton's stage shown from its first second) gets every seed's result as it comes back - (score, plan)
    or None - and changes nothing of the list."""
    seeds = [seed * 1000 + k for k in range(tries)]
    out = []

    def step(k: int, r=None) -> None:
        if seen:
            try:
                seen(k + 1, tries, r)
            except Exception:  # noqa: BLE001 - a picture is a help, never a reason to stop
                pass
        if progress and ((k + 1) % 10 == 0 or k + 1 == tries):
            progress(k + 1, tries)

    if workers > 1 and tries > 1:
        import multiprocessing
        with multiprocessing.Pool(min(workers, tries)) as pool:
            for k, r in enumerate(pool.imap(_plan_of, [(params, s) for s in seeds], chunksize=1)):
                if r is not None:
                    out.append(r)
                step(k, r)
    else:
        for k, s in enumerate(seeds):
            r = _plan_of((params, s))
            if r is not None:
                out.append(r)
            step(k, r)
    out.sort(key=lambda t: t[0])
    return [p for _, p in out]


# --------------------------------------------------------------------------------------------- the record and a picture
def skeleton_text(P: Plan) -> str:
    q = P.params
    lines = [f"# skeleton of a map from scratch - seed {P.seed}, {P.W} x {P.H} cells of {CELL}",
             "params " + json.dumps({k: v for k, v in q.items() if k != "style"}, ensure_ascii=False),
             "metrics " + json.dumps(P.metrics, ensure_ascii=False)]
    for s in P.spaces:
        if s.solid:
            continue
        r = s.rect
        over = getattr(s, "over", None)
        y0, y1 = (r.y0 - UP, r.y1 - UP) if over is not None else (r.y0, r.y1)
        lines.append(f"space {s.id} {s.kind} {r.x0} {y0} {r.x1} {y1} base {s.base} ceil {s.ceil} "
                     f"pattern {s.pattern} sky {int(s.sky)}" + (f" over {over}" if over is not None else "")
                     + (f" turn {s.turned}" if getattr(s, "turned", None) else ""))
    for d in P.doors:
        lines.append(f"route {d.a} {d.b} {d.kind} cells {' '.join(f'{phys(c)[0]},{phys(c)[1]}' for c in d.cells)} "
                     f"z {d.z} sides {d.za} {d.zb}")
    for cls, c, z, note in P.items:
        lines.append(f"place {cls} {phys(c)[0]} {phys(c)[1]} z {z}{(' # ' + note) if note else ''}")
    for c, z, a in P.spawns:
        lines.append(f"spawn {phys(c)[0]} {phys(c)[1]} z {z} angle {a}")
    for (plat, zl, zh, bottom, top) in P.lifts:
        lines.append(f"lift func_plat {plat[0][0]},{plat[0][1]} rides {zl}..{zh} # a rise of {zh - zl} without room for a flight")
    for (cells, into, zl, zh, front) in P.ladders:
        lines.append(f"ladder {cells[0][0]},{cells[0][1]} climbs {zl}..{zh} # a ladder up the wall to the door")
    for (a, t, T, speed, pitch, yaw, zf) in P.pads:
        lines.append(f"pad trigger_push {a[0]},{a[1]} -> {t[0]},{t[1]} speed {speed} pitch {pitch} yaw {yaw} flight {T:.2f} s")
    for (a, b_, da, db) in P.teleports:
        lines.append(f"teleporter {a[0]},{a[1]} <-> {b_[0]},{b_[1]} exits {da[0]},{da[1]} / {db[0]},{db[1]}")
    for d in P.doors:
        if d.mover:
            lines.append(f"door func_door {d.cells[0][0]},{d.cells[0][1]} between {d.a} and {d.b}")
    for (cells, bottom, sid) in P.pits:
        lines.append(f"pit trigger_hurt space {sid} cells {len(cells)} bottom {bottom}")
    lines.append(f"flights {len(P.flights)} ramps {sum(1 for g in P.flights if g & P.ramps)}")
    for what, why in P.reasons:
        lines.append(f"reason {what}: {why}")
    for r_ in (q.get("refused") or []) + list(P.metrics.get("mech_missing") or []) + list(P.notes):
        lines.append(f"refused {r_}")
    return "\n".join(lines) + "\n"


ITEM_MARK = {  # what the picture writes on an item: letters, the circle's colour
    "weapon_railgun": ("RG", (230, 60, 60)), "weapon_rocketlauncher": ("RL", (230, 60, 60)),
    "weapon_chaingun": ("CG", (230, 60, 60)), "weapon_grenadelauncher": ("GL", (230, 60, 60)),
    "weapon_hyperblaster": ("HB", (230, 60, 60)), "weapon_supershotgun": ("SS", (230, 60, 60)),
    "weapon_shotgun": ("SG", (230, 60, 60)), "weapon_machinegun": ("MG", (230, 60, 60)),
    "weapon_bfg": ("BF", (230, 60, 60)),
    "item_armor_body": ("RA", (200, 30, 30)), "item_armor_combat": ("YA", (220, 190, 30)),
    "item_armor_jacket": ("GA", (60, 170, 60)), "item_health_mega": ("MH", (40, 110, 230)),
    "item_quad": ("Q", (120, 60, 230)), "item_invulnerability": ("I", (230, 60, 200)),
    "item_adrenaline": ("A", (240, 140, 30)), "item_pack": ("P", (150, 110, 70)),
}


def draw(P: Plan, path: Path, scale: int = 22) -> None:
    """The skeleton as a picture for people (brief 19 §7: Fable reviews it; the Studio shows it before the first
    brush): floor height light-on-dark, steps and ramps, doorways, drops, ladders, lifts, pads, teleporters, liquids
    and chasms, windows, the items lettered, the spawns as arrows - and a legend."""
    import math as _m
    from PIL import Image, ImageDraw, ImageFont

    def face(size):
        # a font with Cyrillic: Pillow's own default (Aileron) has none - the PO's Studio showed the Russian legend as
        # boxes (05.11, «Каркас карты»). Windows' fonts first, then the usual Linux ones, Pillow's last
        for name in ("segoeui.ttf", "arial.ttf", "tahoma.ttf", "verdana.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
            for d in (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu"),
                      Path("/usr/share/fonts/truetype/liberation")):
                f_ = d / name
                if f_.is_file():
                    try:
                        return ImageFont.truetype(str(f_), size)
                    except OSError:
                        continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()
    font = face(max(10, scale // 2))
    small = face(13)
    big = face(17)
    legend_w = 300
    W, H = P.W * scale, P.H * scale
    img = Image.new("RGB", (W + legend_w, max(H, 620)), (22, 22, 26))
    dr = ImageDraw.Draw(img)
    floors = [floor_top(f) for s in P.spaces if not s.solid for f in s.floor.values()]
    pit_cells = {c for (cells, _b, _s) in P.pits for c in cells}
    zlo = min((z for z in floors), default=0)
    zhi = max(floors, default=1)
    live_z = [z for s in P.spaces if not s.solid for c, f in s.floor.items() if c not in pit_cells for z in [floor_top(f)]]
    if live_z:
        zlo = min(live_z)
    span = max(1, zhi - zlo)

    def ramp(z):
        t = max(0.0, min(1.0, (z - zlo) / span))
        lo, hi = (38, 52, 96), (240, 226, 186)
        return tuple(int(lo[i] + (hi[i] - lo[i]) * t) for i in range(3))

    def box(c, inset=0):
        x, y = phys(c)
        Y = P.H - 1 - y
        return [x * scale + inset, Y * scale + inset, (x + 1) * scale - 1 - inset, (Y + 1) * scale - 1 - inset]

    def centre(c):
        b = box(c)
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    liquid_of = {}
    for (cells, kind, z0, level) in P.liquids:
        for c in cells:
            liquid_of[c] = kind
    # floors
    for s in P.spaces:
        if s.solid:
            continue
        for c, f in s.floor.items():
            dr.rectangle(box(c), fill=ramp(floor_top(f) - (16 if f[1] == "stair" else 0)))
            if c in pit_cells:
                dr.rectangle(box(c), fill=(8, 8, 8))
                b = box(c, scale // 4)
                dr.line([b[0], b[1], b[2], b[3]], fill=(200, 40, 40), width=2)
                dr.line([b[0], b[3], b[2], b[1]], fill=(200, 40, 40), width=2)
            elif c in liquid_of:
                col = {"water": (40, 110, 230), "lava": (235, 95, 20), "slime": (100, 200, 40)}[liquid_of[c]]
                dr.rectangle(box(c, 2), fill=col)
            if f[1] == "stair":
                b = box(c)
                if c in P.ramps:
                    a, e = centre(c), centre(c)
                    a = (a[0] - f[2] * scale * 0.3, a[1] + f[3] * scale * 0.3)
                    e = (e[0] + f[2] * scale * 0.3, e[1] - f[3] * scale * 0.3)
                    dr.line([a, e], fill=(20, 20, 20), width=3)
                    dr.ellipse([e[0] - 3, e[1] - 3, e[0] + 3, e[1] + 3], fill=(20, 20, 20))
                else:
                    for k in (1, 2, 3):
                        if f[2]:
                            x = b[0] + (b[2] - b[0]) * k / 4
                            dr.line([x, b[1] + 2, x, b[3] - 2], fill=(25, 25, 25), width=1)
                        else:
                            yy = b[1] + (b[3] - b[1]) * k / 4
                            dr.line([b[0] + 2, yy, b[2] - 2, yy], fill=(25, 25, 25), width=1)
        if s.sky:
            r = s.rect
            dr.rectangle([r.x0 * scale + 1, (P.H - r.y1) * scale + 1, r.x1 * scale - 2, (P.H - r.y0) * scale - 2],
                         outline=(120, 210, 255), width=2)
        if getattr(s, "over", None) is not None:
            # a room over a room: its floor drawn over the lower one's, outlined in white and crossed
            r = s.rect
            b = [r.x0 * scale + 2, (P.H - (r.y1 - UP)) * scale + 2, r.x1 * scale - 3, (P.H - (r.y0 - UP)) * scale - 3]
            dr.rectangle(b, outline=(255, 255, 255), width=3)
            dr.line([b[0], b[1], b[2], b[3]], fill=(255, 255, 255), width=1)
    # doorways and what is in them
    for d in P.doors:
        if d.kind == "swim":
            # the PO 12.11: a tube under water under the floors - a blue band along it, the floors over it seen
            pts = [centre(c) for c in d.cells]
            if len(pts) > 1:
                dr.line(pts, fill=(40, 110, 230), width=max(3, scale // 3))
            for c in d.cells:
                b = box(c, scale // 3)
                dr.rectangle(b, outline=(40, 110, 230), width=2)
            continue
        for c in d.cells:
            z = d.z + (RISE_PER_CELL // 2 if d.stair else 0)
            dr.rectangle(box(c), fill=ramp(z))
            if d.kind == "overlook":
                dr.rectangle(box(c, 3), outline=(250, 140, 50), width=2)
            elif d.kind == "drop":
                cx, cy = centre(c)
                dr.polygon([(cx - 6, cy - 4), (cx + 6, cy - 4), (cx, cy + 6)], fill=(250, 140, 50))
            elif d.kind == "ladder":
                b = box(c, 4)
                dr.line([b[0] + 3, b[1], b[0] + 3, b[3]], fill=(30, 30, 30), width=2)
                dr.line([b[2] - 3, b[1], b[2] - 3, b[3]], fill=(30, 30, 30), width=2)
                for k in range(1, 4):
                    yy = b[1] + (b[3] - b[1]) * k / 4
                    dr.line([b[0] + 3, yy, b[2] - 3, yy], fill=(30, 30, 30), width=2)
            elif d.mover:
                b = box(c, 3)
                dr.rectangle(b, outline=(150, 90, 40), width=3)
            elif d.stair:
                b = box(c)
                for k in (1, 2, 3):
                    if d.stair[0]:
                        x = b[0] + (b[2] - b[0]) * k / 4
                        dr.line([x, b[1] + 2, x, b[3] - 2], fill=(25, 25, 25), width=1)
                    else:
                        yy = b[1] + (b[3] - b[1]) * k / 4
                        dr.line([b[0] + 2, yy, b[2] - 2, yy], fill=(25, 25, 25), width=1)
    for (cells, z0, z1, *w) in P.windows:
        for c in cells:
            b = box(c, scale // 3)
            dr.rectangle(b, fill=(150, 230, 255))
    # 3.46: the round shapes - a corner's or an apse's fill dark, a podium's tiers outlined
    def at(px, py):
        return (px / CELL * scale, (P.H - py / CELL) * scale)
    for (pt, arc, _z0, _z1, _sid, _kind) in P.rounds:
        dr.polygon([at(*pt)] + [at(*a_) for a_ in arc], fill=(14, 14, 16), outline=(235, 200, 120))
    for (outer, inner, _z, _sid) in P.podiums:
        dr.polygon([at(*v) for v in outer], outline=(235, 200, 120), width=2)
        if inner:
            dr.polygon([at(*v) for v in inner], outline=(235, 200, 120), width=2)
    for (plat, zl, zh, bottom, top) in P.lifts:
        for c in plat:
            dr.rectangle(box(c, 2), outline=(230, 60, 230), width=3)
        cx, cy = centre(plat[0])
        dr.text((cx - 4, cy - 7), "L", fill=(230, 60, 230), font=font)
    for (a, t, T, speed, pitch, yaw, zf) in P.pads:
        ca, ct = centre(a), centre(t)
        dr.line([ca, ct], fill=(60, 230, 120), width=2)
        dr.ellipse([ca[0] - 7, ca[1] - 7, ca[0] + 7, ca[1] + 7], fill=(60, 230, 120))
        dr.ellipse([ct[0] - 4, ct[1] - 4, ct[0] + 4, ct[1] + 4], outline=(60, 230, 120), width=2)
    for (a, b_, da, db) in P.teleports:
        for src, dst in ((a, db), (b_, da)):
            cs, cd = centre(src), centre(dst)
            dr.ellipse([cs[0] - 8, cs[1] - 8, cs[0] + 8, cs[1] + 8], outline=(190, 90, 255), width=3)
            dr.ellipse([cd[0] - 3, cd[1] - 3, cd[0] + 3, cd[1] + 3], fill=(190, 90, 255))
    # items and spawns
    for cls, c, z, n in P.items:
        cx, cy = centre(c)
        if cls in ITEM_MARK:
            word, col = ITEM_MARK[cls]
            r_ = scale * 0.48
            dr.ellipse([cx - r_, cy - r_, cx + r_, cy + r_], fill=col, outline=(15, 15, 15))
            tw = dr.textlength(word, font=font)
            dr.text((cx - tw / 2, cy - scale * 0.3), word, fill=(255, 255, 255), font=font)
        elif cls.startswith("item_health"):
            dr.rectangle([cx - 5, cy - 1.5, cx + 5, cy + 1.5], fill=(255, 255, 255))
            dr.rectangle([cx - 1.5, cy - 5, cx + 1.5, cy + 5], fill=(255, 255, 255))
        elif cls == "item_armor_shard":
            dr.polygon([(cx, cy - 4), (cx + 3, cy), (cx, cy + 4), (cx - 3, cy)], fill=(220, 190, 30))
        else:
            dr.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(150, 150, 150))
    for c, z, ang in P.spawns:
        cx, cy = centre(c)
        a_ = _m.radians(ang)
        tip = (cx + _m.cos(a_) * scale * 0.45, cy - _m.sin(a_) * scale * 0.45)
        l_ = (cx + _m.cos(a_ + 2.5) * scale * 0.35, cy - _m.sin(a_ + 2.5) * scale * 0.35)
        r_ = (cx + _m.cos(a_ - 2.5) * scale * 0.35, cy - _m.sin(a_ - 2.5) * scale * 0.35)
        dr.polygon([tip, l_, r_], fill=(255, 255, 255), outline=(10, 10, 10))
    # the legend, in the Studio's language (the parameters carry it)
    x0 = W + 18
    y = 14
    q = P.params
    ru = q.get("lang") == "ru"
    RU = {"steps (lines across)": "ступени (поперечные линии)", "ramp (arrow uphill)": "пандус (стрелка вверх)",
          "drop down / ledge": "спуск вниз / уступ", "ladder": "лестница-стремянка", "lift": "лифт", "door": "дверь",
          "window": "окно", "jump pad -> landing": "джампад -> приземление", "teleporter -> exit": "телепорт -> выход",
          "water / lava / slime": "вода / лава / кислота", "deadly chasm": "смертельная яма",
          "tube under water (under the floors)": "подводная труба (под полом)",
          "open to the sky (blue frame)": "под открытым небом (голубая рамка)", "spawn (facing)": "точка появления (взгляд)",
          "room over a room (white frame)": "комната над комнатой (белая рамка)",
          "small health / shard / ammo": "аптечка / осколок брони / патроны",
          "rounded corner / podium": "скругление / круглое возвышение"}
    tr = (lambda s: RU.get(s, s)) if ru else (lambda s: s)
    dr.text((x0, y), (f"каркас, вариант {P.seed}" if ru else f"skeleton, seed {P.seed}"), fill=(235, 235, 235), font=big)
    y += 24
    dr.text((x0, y), (f"{P.W} x {P.H} клеток по {CELL} ед., игроков {q.get('players')}" if ru
                      else f"{P.W} x {P.H} cells of {CELL} u, {q.get('players')} players"), fill=(180, 180, 180), font=small)
    y += 26
    dr.text((x0, y), "высота пола" if ru else "floor height", fill=(235, 235, 235), font=small)
    y += 18
    for k in range(101):
        dr.line([x0 + k * 2, y, x0 + k * 2, y + 14], fill=ramp(zlo + span * k / 100), width=2)
    dr.text((x0, y + 16), f"{zlo}", fill=(180, 180, 180), font=small)
    tw = dr.textlength(f"{zhi}", font=small)
    dr.text((x0 + 202 - tw, y + 16), f"{zhi}", fill=(180, 180, 180), font=small)
    y += 42
    rows = [
        ("steps (lines across)", lambda b: [dr.rectangle(b, fill=ramp(zlo + span / 2))] + [
            dr.line([b[0] + (b[2] - b[0]) * k / 4, b[1] + 2, b[0] + (b[2] - b[0]) * k / 4, b[3] - 2], fill=(25, 25, 25))
            for k in (1, 2, 3)]),
        ("ramp (arrow uphill)", lambda b: [dr.rectangle(b, fill=ramp(zlo + span / 2)),
                                           dr.line([b[0] + 4, (b[1] + b[3]) / 2, b[2] - 4, (b[1] + b[3]) / 2], fill=(20, 20, 20), width=3)]),
        ("drop down / ledge", lambda b: [dr.polygon([(b[0] + 4, b[1] + 5), (b[2] - 4, b[1] + 5), ((b[0] + b[2]) / 2, b[3] - 4)], fill=(250, 140, 50))]),
        ("ladder", lambda b: [dr.line([b[0] + 6, b[1], b[0] + 6, b[3]], fill=(200, 200, 200), width=2),
                              dr.line([b[2] - 6, b[1], b[2] - 6, b[3]], fill=(200, 200, 200), width=2),
                              dr.line([b[0] + 6, (b[1] + b[3]) / 2, b[2] - 6, (b[1] + b[3]) / 2], fill=(200, 200, 200), width=2)]),
        ("lift", lambda b: [dr.rectangle(b, outline=(230, 60, 230), width=3)]),
        ("door", lambda b: [dr.rectangle(b, outline=(150, 90, 40), width=3)]),
        ("window", lambda b: [dr.rectangle([b[0] + 6, b[1] + 6, b[2] - 6, b[3] - 6], fill=(150, 230, 255))]),
        ("jump pad -> landing", lambda b: [dr.ellipse([b[0] + 4, b[1] + 4, b[2] - 4, b[3] - 4], fill=(60, 230, 120))]),
        ("teleporter -> exit", lambda b: [dr.ellipse([b[0] + 3, b[1] + 3, b[2] - 3, b[3] - 3], outline=(190, 90, 255), width=3)]),
        ("water / lava / slime", lambda b: [dr.rectangle([b[0], b[1], b[0] + 7, b[3]], fill=(40, 110, 230)),
                                            dr.rectangle([b[0] + 8, b[1], b[0] + 15, b[3]], fill=(235, 95, 20)),
                                            dr.rectangle([b[0] + 16, b[1], b[2], b[3]], fill=(100, 200, 40))]),
        ("tube under water (under the floors)", lambda b: [dr.line([b[0], (b[1] + b[3]) / 2, b[2], (b[1] + b[3]) / 2], fill=(40, 110, 230), width=6)]),
        ("deadly chasm", lambda b: [dr.rectangle(b, fill=(8, 8, 8)), dr.line([b[0], b[1], b[2], b[3]], fill=(200, 40, 40), width=2)]),
        ("open to the sky (blue frame)", lambda b: [dr.rectangle(b, outline=(120, 210, 255), width=2)]),
        ("room over a room (white frame)", lambda b: [dr.rectangle(b, outline=(255, 255, 255), width=3),
                                                      dr.line([b[0], b[1], b[2], b[3]], fill=(255, 255, 255), width=1)]),
        ("rounded corner / podium", lambda b: [dr.polygon([(b[0], b[1]), (b[2] - 6, b[1]), (b[0] + 4, b[3] - 4), (b[0], b[3])], fill=(14, 14, 16), outline=(235, 200, 120)),
                                               dr.polygon([(b[2] - 9, b[1] + 6), (b[2] - 3, b[1] + 6), (b[2], b[1] + 10), (b[2] - 3, b[3] - 2), (b[2] - 9, b[3] - 2)], outline=(235, 200, 120))]),
        ("spawn (facing)", lambda b: [dr.polygon([(b[2] - 2, (b[1] + b[3]) / 2), (b[0] + 4, b[1] + 4), (b[0] + 4, b[3] - 4)], fill=(255, 255, 255))]),
        ("small health / shard / ammo", lambda b: [dr.rectangle([b[0] + 2, (b[1] + b[3]) / 2 - 1, b[0] + 10, (b[1] + b[3]) / 2 + 1], fill=(255, 255, 255)),
                                                   dr.rectangle([b[0] + 5, b[1] + 6, b[0] + 7, b[3] - 6], fill=(255, 255, 255)),
                                                   dr.ellipse([b[2] - 6, (b[1] + b[3]) / 2 - 2, b[2] - 2, (b[1] + b[3]) / 2 + 2], fill=(150, 150, 150))]),
    ]
    for label, paint in rows:
        b = [x0, y, x0 + 24, y + 20]
        paint(b)
        dr.text((x0 + 34, y + 2), tr(label), fill=(220, 220, 220), font=small)
        y += 26
    y += 6
    dr.text((x0, y), "RG RL CG GL HB SS SG MG  " + ("оружие" if ru else "guns"), fill=(230, 120, 120), font=small)
    y += 20
    dr.text((x0, y), "RA YA GA MH Q A  " + ("броня, мега, квад, адрен." if ru else "armour, mega, quad, adren."),
            fill=(200, 200, 120), font=small)
    img.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tries", type=int, default=40)
    ap.add_argument("--png", type=Path)
    ap.add_argument("--txt", type=Path)
    a = ap.parse_args()
    plans = best_plan({"players": a.players}, a.seed, a.tries)
    if not plans:
        print("no plan")
        return 1
    P = plans[0]
    print(json.dumps(P.metrics), f"{len(plans)} plans, size {P.W}x{P.H}")
    if a.png:
        draw(P, a.png)
    if a.txt:
        a.txt.write_text(skeleton_text(P), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
