"""Scripted pieces of maps from scratch: movers, triggers, traps (the PO 13.11).

The PO, 13.11.2026 (clips O:\\Claude2\\q2pro\\Bugs\\2): q2dm3's trains over lava and slime and its glass room whose doors
close on buttons while lava rises round the hyperblaster; q2dm4's bent bridge, ladder out of the water, rotating flap
by the quad; q2dm6's shutters on a timer, wall that turns when the body armour is taken, drum over lava by the railgun's
beam, platforms that sink into lava when stepped on, steps up a wall to the chaingun. «Всё такое должен уметь строить
генератор ... Именно вариации»; «нам не хватает архитектурного уникального для карт лоска ... постройками, которые
имеют движение и/или интерактивность с игроком и вносят доп опасность, но и доп интерес к их посещению»; «проявишь и
творческую нотку ... уникальные конструкции, которых в том числе не было в картах людей»; «чтобы человек открыв твою
карту был в ахуе». Design: doc/reports/design_opus_2026-11-13_mapgen_scripted_pieces.md; people's numbers:
tools/mapgen_mover_practice.json.

Two passes, called by mapgen_scratch_plan.make_plan:
  before_liquids(P, rnd) - the bent bridges (a pit's shape), the pits the pieces ask;
  after_items(P, rnd)    - everything else, the items placed (a piece takes a valuable item to guard).
Each piece is a record in P.pieces: its kind, its cells, the brushes and entities the world builds (`world(P, pal)`
turns their roles into the style's textures), the plan's walk (P.piece_nodes, P.piece_edges) and what the survey
needs to walk it on the finished map (the entity keys `_mapgen_floor` and `_mapgen_link`).
"""
from __future__ import annotations

import math
import random

CELL = 64
# people's numbers (tools/mapgen_mover_practice.json)
TRAIN_SPEED = 60          # q2dm3's trains over lava and slime
ISLAND_RISE = 80                # an island over the rim: past the game's jump (45) and a step (18) - one rides up
STONE_DELAY = 2.0         # q2dm6's platforms: the plate fires them 2 s after the step
STONE_WAIT = 1.0          # ... they stay down 1 s
STONE_SPEED = 100
TRAP_DOOR_SPEED = 300     # q2dm3's room: the doors rise at 300, stay 5 s
TRAP_DOOR_WAIT = 5.0
TRAP_HAZARD_DELAY = 1.0   # ... the lava rises 1 s after them, 56 at 100, stays 3 s
TRAP_HAZARD_WAIT = 3.0
TRAP_HAZARD_SPEED = 100
TRAP_DOOR_DMG = 1000      # q2dm3's doors crush whoever stands in the doorway
SHUTTER_WAIT = 3.0        # q2dm6's shutters: a timer every 3 s (random 0.5)
SHUTTER_RANDOM = 0.5
SHUTTER_SPEED = 50
DRUM_SPEED = 20           # q2dm6's drum over lava
FLAP_SPEED = 60           # q2dm4's flap by the quad
FAN_SPEED = 300           # q2rdm7's fans, 2 a touch
FAN_DMG = 2
WALL_SPEED = 30           # q2dm6's wall turning when the body armour is taken (q2rdm12's 400)

# what a piece takes to guard, the most valuable first (a prize no mechanic holds, then a weapon or an armour)
GUARD_ITEMS = ("item_quad", "item_invulnerability", "weapon_railgun", "item_health_mega", "item_armor_body",
               "weapon_hyperblaster", "weapon_rocketlauncher", "item_armor_combat", "weapon_grenadelauncher",
               "weapon_chaingun", "weapon_supershotgun", "item_armor_jacket", "item_adrenaline")
FIXED_NOTES = ("stack", "key gun", "asymmetry", "lift as", "ladder", "dead-end", "teleport to", "armour by",
               "adrenaline tucked", "in a nook", "under water", "only a", "in the open", "cycle", "clock", "guarded by")

KINDS = ("trains", "stones", "traps", "rotators", "shutters", "pickup_walls", "bent_bridges", "pool_ladders",
         "wall_steps", "lasers", "pistons", "pendulums", "trapdoors", "geysers", "turn_bridges", "currents", "waves",
         # the PO 13.11, after the first try (mapgen_scratch_pieces3): drilling rigs, cogs on walls, blaster turrets,
         # conveyors with crates
         "drills", "cogs", "turrets", "conveyors")


def pm():
    import mapgen_scratch_plan as plan_mod
    return plan_mod


def say(ru: str, en: str) -> str:
    return pm().say(ru, en)


# --------------------------------------------------------------------------------------------- the request
def defaults(q: dict) -> dict:
    """The form's rows for the pieces, each a count (0 none) and a variation."""
    for k, hi in (("trains", 3), ("stones", 3), ("traps", 2), ("rotators", 3), ("shutters", 2), ("pickup_walls", 2),
                  ("bent_bridges", 2), ("wall_steps", 3), ("lasers", 2), ("pistons", 2), ("pendulums", 2),
                  ("trapdoors", 2), ("geysers", 3), ("turn_bridges", 2), ("currents", 2), ("waves", 2)):
        try:
            q[k] = max(0, min(hi, int(q.get(k) or 0)))
        except (TypeError, ValueError):
            q[k] = 0
    q["pool_ladders"] = bool(q.get("pool_ladders"))
    if q.get("train_path") not in ("mix", "across", "loop", "island"):
        q["train_path"] = "mix"
    if q.get("stone_shape") not in ("mix", "row", "gaps", "zigzag"):
        q["stone_shape"] = "mix"
    if q.get("trap_trigger") not in ("mix", "buttons", "plate", "item"):
        q["trap_trigger"] = "mix"
    if q.get("trap_hazard") not in ("mix", "lava", "slime", "crusher"):
        q["trap_hazard"] = "mix"
    if q.get("rotator_kind") not in ("mix", "drum", "flap", "fan"):
        q["rotator_kind"] = "mix"
    try:
        q["piece_speed"] = max(50, min(200, int(q.get("piece_speed") or 100)))     # % of people's speeds
    except (TypeError, ValueError):
        q["piece_speed"] = 100
    try:
        q["piece_wait"] = max(50, min(300, int(q.get("piece_wait") or 100)))       # % of people's waits
    except (TypeError, ValueError):
        q["piece_wait"] = 100
    import mapgen_scratch_forms as forms
    import mapgen_scratch_pieces3 as third
    third.defaults(q)
    if q.get("pendulum_kind") not in ("mix",) + forms.PENDULUM_FORMS:
        q["pendulum_kind"] = "mix"
    # the PO 13.11 («как реальная физика работает», «мы делаем не мод, а карты»): what the game itself can do - the
    # pieces that move straight start and stop gently (a door's accel and decel), «smooth»; «even» as people's maps
    if q.get("piece_motion") not in ("smooth", "even"):
        q["piece_motion"] = "smooth"
    # a hammer's blow with a shock wave (an explosion's blast throws whom it hits - the only throw the game has)
    q["hammer_blast"] = bool(q.get("hammer_blast"))
    return q


def wants_pits(q: dict) -> int:
    """How many pits of a liquid (or a chasm) the pieces over one ask: the trains, the stones, the drums, the turning
    bridges, the current floors, the pillar waves, the trapdoors (one piece a pit)."""
    drums = q.get("rotators", 0) if q.get("rotator_kind") in ("drum", "mix") else 0
    return (q.get("trains", 0) + q.get("stones", 0) + (drums + 1) // 2 + q.get("turn_bridges", 0) + q.get("currents", 0)
            + q.get("waves", 0) + q.get("pendulums", 0) + q.get("trapdoors", 0))


def any_asked(q: dict) -> bool:
    return any(q.get(k) for k in KINDS)


# --------------------------------------------------------------------------------------------- geometry helpers
def cb(c, inset=0):
    """A cell's box in units (x0, y0, x1, y1)."""
    p = pm().phys(c)
    return (p[0] * CELL + inset, p[1] * CELL + inset, (p[0] + 1) * CELL - inset, (p[1] + 1) * CELL - inset)


def mid(c):
    p = pm().phys(c)
    return ((p[0] + 0.5) * CELL, (p[1] + 0.5) * CELL)


def bx(lo, hi, role="trim", contents=0, note=""):
    return {"lo": [round(v) for v in lo], "hi": [round(v) for v in hi], "role": role, "contents": contents, "note": note}


def ent(keys: dict, brushes=None) -> dict:
    return {"keys": {k: str(v) for k, v in keys.items()}, "brushes": list(brushes or [])}


class Names:
    """Target names unique in a map: «mg_<kind><n>_<what>»."""
    def __init__(self, P):
        self.P = P

    def __call__(self, what: str) -> str:
        n = getattr(self.P, "_piece_names", 0) + 1
        self.P._piece_names = n
        return f"mgp{n}_{what}"


def speed(P, v: float) -> int:
    return max(10, round(v * P.params.get("piece_speed", 100) / 100))


def wait(P, v: float) -> float:
    return round(v * P.params.get("piece_wait", 100) / 100, 1)


# the RED: the plain rooms counted before the pieces and the machines' halls drawn at random (the test map
# mg_new_368_mach3: «plain rooms: 1» with cogs and a drill in other halls); MAPGEN_OLD_PLAIN_PIECES=1 for a process
OLD_PLAIN_PIECES = __import__("os").environ.get("MAPGEN_OLD_PLAIN_PIECES") == "1"


# the RED of the test map mg_new_368_mach4 (13.11): a conveyor's belt over an item in its line, two pendulums on
# neighbouring cells of one bridge (their heads through each other), a trap button 4 into its pane;
# MAPGEN_OLD_MACH4=1 for a process
OLD_BELT_OVER_ITEMS = OLD_PENDULUMS_CLOSE = OLD_TRAP_BUTTON = __import__("os").environ.get("MAPGEN_OLD_MACH4") == "1"
# the RED of the test map mg_new_368_mach6: a piston's head standing out of the wall at rest; MAPGEN_OLD_PISTON_HEADS=1
OLD_PISTON_HEADS_OUT = __import__("os").environ.get("MAPGEN_OLD_PISTON_HEADS") == "1"
# the RED of the test map mg_new_368_mach7: pendulums counted by their records - two asked, one bridge, one pendulum
# (the next one two cells off found no room); MAPGEN_OLD_PENDULUM_COUNT=1 for a process
OLD_PENDULUM_COUNT = __import__("os").environ.get("MAPGEN_OLD_PENDULUM_COUNT") == "1"


# the RED: a moving piece's part wholly inside another of its parts kept (the test map mg_new_368_mach5: the compiler
# hangs it on no leaf, the engine's round trip puts it in the world - three candidates «baseline-refused»);
# MAPGEN_OLD_HIDDEN_PARTS=1 for a process
OLD_HIDDEN_PARTS = __import__("os").environ.get("MAPGEN_OLD_HIDDEN_PARTS") == "1"


def _corners(b):
    """A form's corners (a prism's polygon at both ends, a box's eight), or None for another kind."""
    if "prism" in b:
        pr = b["prism"]
        ax = pr["axis"]
        out = []
        for w in (pr["lo"], pr["hi"]):
            for a, c in pr["poly"]:
                out.append((w, a, c) if ax == "x" else (a, w, c) if ax == "y" else (a, c, w))
        return out
    if "lo" in b and "hi" in b and len(b["lo"]) == 3:
        return [(x, y, z) for x in (b["lo"][0], b["hi"][0]) for y in (b["lo"][1], b["hi"][1]) for z in (b["lo"][2], b["hi"][2])]
    return None


def _holds(b, p, eps: float = 0.01) -> bool:
    """Whether the form `b` (a prism or a box) holds the point `p`, its surface included."""
    if "prism" in b:
        pr = b["prism"]
        i = "xyz".index(pr["axis"])
        if not (pr["lo"] - eps <= p[i] <= pr["hi"] + eps):
            return False
        a_, c_ = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}[pr["axis"]]
        q = (p[a_], p[c_])
        poly = pr["poly"]
        n = len(poly)
        area = sum(poly[k][0] * poly[(k + 1) % n][1] - poly[(k + 1) % n][0] * poly[k][1] for k in range(n))
        sgn = 1 if area > 0 else -1
        for k in range(n):
            (x0, y0), (x1, y1) = poly[k], poly[(k + 1) % n]
            ln = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 or 1.0
            if sgn * ((x1 - x0) * (q[1] - y0) - (y1 - y0) * (q[0] - x0)) / ln < -eps:
                return False
        return True
    if "lo" in b and "hi" in b:
        return all(b["lo"][k] - eps <= p[k] <= b["hi"][k] + eps for k in range(3))
    return False


def _poly_overlap(a, b, eps: float = -0.5) -> bool:
    """Two convex polygons share an inside or touch (closer than half a unit): no separating axis among their edges'
    normals with a gap."""
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
            nx, ny = y1 - y0, x0 - x1
            pa = [nx * p[0] + ny * p[1] for p in a]
            pb = [nx * p[0] + ny * p[1] for p in b]
            ln = (nx * nx + ny * ny) ** 0.5 or 1.0
            if max(pa) <= min(pb) + eps * ln or max(pb) <= min(pa) + eps * ln:
                return False
    return True


def _parts_overlap(a, b) -> bool:
    """Two forms (prisms across one axis, or boxes) share an inside - conservatively for anything else."""
    pa, pb = a.get("prism"), b.get("prism")
    if pa and pb and pa["axis"] == pb["axis"]:
        if min(pa["hi"], pb["hi"]) - max(pa["lo"], pb["lo"]) < -0.5:
            return False
        return _poly_overlap(pa["poly"], pb["poly"])
    ca, cb_ = _corners(a), _corners(b)
    if not ca or not cb_:
        return True
    return all(min(max(c[k] for c in ca), max(c[k] for c in cb_)) - max(min(c[k] for c in ca), min(c[k] for c in cb_)) >= -0.5
               for k in range(3))


def body_groups(parts: list) -> list:
    """A moving piece's parts in groups none of whose parts overlaps or touches another of its group (each group one
    moving body, all moved as one - one name, one speed): the engine's round trip draws a body's overlapping or touching
    parts otherwise (the test map mg_new_368_mach12's candidate: a pendulum's rod into its head, «3 walls are covered
    differently»; a cog's hub cap on its rim)."""
    if OLD_BODY_GROUPS or len(parts) < 2:
        return [parts]
    groups = []
    for b in parts:
        for g in groups:
            if not any(_parts_overlap(b, x) for x in g):
                g.append(b)
                break
        else:
            groups.append([b])
    return groups


# the RED: a pendulum's parts in one body, overlapping; MAPGEN_OLD_BODY_GROUPS=1 for a process
OLD_BODY_GROUPS = __import__("os").environ.get("MAPGEN_OLD_BODY_GROUPS") == "1"


def shown_parts(parts: list) -> list:
    """A moving piece's parts less those wholly inside another of its parts (the first of two alike kept): the compiler
    carves such a part to nothing and hangs it on no leaf of the piece's model, and the engine's round trip of the
    finished map (map -> source -> map) gives a brush on no model to the world - the base differs, the candidate is
    refused (the test map mg_new_368_mach5: a hammer's head piece inside its head, «4 of 822 planes ... no
    counterpart», its crates' records with it)."""
    if OLD_HIDDEN_PARTS or len(parts) < 2:
        return parts
    corners = [_corners(b) for b in parts]
    keep = []
    for i, b in enumerate(parts):
        ci = corners[i]
        inside = ci is not None and any(
            j != i and corners[j] is not None and all(_holds(parts[j], p) for p in ci)
            and not (j > i and all(_holds(b, p) for p in corners[j]))        # two alike: the first one stays
            for j in range(len(parts)))
        if not inside:
            keep.append(b)
    return keep or parts[:1]


# the RED: turning pieces placed with no look at their swing (the PO 13.11, Bugs/4: «конструкции сквозь стенки и
# пристройки крутятся» - a saw through a glass trap room and a pillar, cogs through pilasters); MAPGEN_OLD_SWEEP=1
OLD_SWEEP = __import__("os").environ.get("MAPGEN_OLD_SWEEP") == "1"


def turn_of(keys: dict):
    """A turning entity's (origin, the game's axis flags as func_door_rotating's, the angles it passes) - or None."""
    cls = keys.get("classname")
    if cls not in ("func_rotating", "func_door_rotating"):
        return None
    o = tuple(float(v) for v in str(keys.get("origin", "0 0 0")).split())
    fl = int(float(keys.get("spawnflags", 0) or 0))
    if cls == "func_rotating":
        return o, (64 if fl & 4 else 0) | (128 if fl & 8 else 0), [float(a) for a in range(15, 360, 15)]
    d = float(keys.get("distance", 90) or 90)
    d = -d if fl & 2 else d
    n = max(2, int(abs(d) // 6))
    return o, fl & (64 | 128), [d * i / n for i in range(1, n + 1)]


def _samples(parts, origin) -> list:
    """A body's points to follow: each part's corners, its edges' middles and quarters, its faces' middles and its own
    middle - a wall's edge can cut into a face that no corner enters (the PO 13.11, Bugs/4 again)."""
    out = []
    for b in parts:
        if "prism" in b:
            pr = b["prism"]
            ax, poly = pr["axis"], pr["poly"]
            n = len(poly)

            def P3(a_, c_, w):
                return (w, a_, c_) if ax == "x" else (a_, w, c_) if ax == "y" else (a_, c_, w)
            caps = []
            for w in (pr["lo"], pr["hi"]):
                ring = [P3(q[0], q[1], w) for q in poly]
                caps.append(ring)
            pts = caps[0] + caps[1]
            for ring in caps:
                for i in range(n):
                    p0, p1 = ring[i], ring[(i + 1) % n]
                    pts += [tuple(p0[k] + (p1[k] - p0[k]) * t for k in range(3)) for t in (0.25, 0.5, 0.75)]
                pts.append(tuple(sum(q[k] for q in ring) / n for k in range(3)))
            for i in range(n):
                p0, p1 = caps[0][i], caps[1][i]
                pts.append(tuple((p0[k] + p1[k]) / 2 for k in range(3)))
                q0, q1 = caps[0][(i + 1) % n], caps[1][(i + 1) % n]
                pts.append(tuple((p0[k] + p1[k] + q0[k] + q1[k]) / 4 for k in range(3)))
            pts.append(tuple(sum(q[k] for q in caps[0] + caps[1]) / (2 * n) for k in range(3)))
        elif "lo" in b and "hi" in b:
            lo_, hi_ = b["lo"], b["hi"]
            vals = [(lo_[k], (lo_[k] + hi_[k]) / 2, hi_[k]) for k in range(3)]
            pts = [(x, y, z) for x in vals[0] for y in vals[1] for z in vals[2]]
        else:
            continue
        out += [tuple(p[k] - origin[k] for k in range(3)) for p in pts]
    return out


def sweep(P, space_id, parts, origin, flags, angles, own=(), skip=None, carve_min_z=None):
    """A turning body carried over its angles (the game's own turn, pieces2.swing_end) against the plan: rock and other
    rooms, floors, ceilings, the plan's columns, every other piece's brushes (`own`: the same piece's fixed brushes -
    a rig, a mount). A point that is inside something at one angle and in the air at another passes through it
    (the PO 13.11, Bugs/4 twice: «он никогда не должен ходить сквозь другую твердую поверхность полностью или
    частично»; the first sweep let a pendulum's head drawn in a wall at its rest - the end of its swing - go); one
    inside the same thing all the way (a rod's top in its plate, an auger's bit in the floor) is where it is made to be.
    With `carve_min_z`, plain rock behind the room's wall (no room, doorway or window beside it, not the map's edge) at
    that height or higher is no stop: it is cut for the body to pass (P.slots, `mapgen_scratch_world` leaves it air).
    Returns (points that pass through something, the cells swept, the cuts wanted {cell: [z0, z1]})."""
    import mapgen_scratch_pieces2 as second
    plan_mod = pm()
    s = P.spaces[space_id] if space_id is not None else None
    upper = bool(s and s.floor and plan_mod.layer_of(next(iter(s.floor))))
    pts = _samples(parts, origin)
    if not pts:
        return 0, set(), {}
    R = max((p[0] ** 2 + p[1] ** 2 + p[2] ** 2) ** 0.5 for p in pts) + 8
    lo = [origin[k] - R for k in range(3)]
    hi = [origin[k] + R for k in range(3)]

    def near(b):
        cs = _corners(b)
        if not cs:
            return False
        return all(min(c[k] for c in cs) <= hi[k] and max(c[k] for c in cs) >= lo[k] for k in range(3))
    skip = skip or set()
    blockers = [b for b in own if near(b)]
    for r in getattr(P, "pieces", []):
        if id(r) in skip:
            continue
        blockers += [b for b in r["brushes"] if near(b)]
        for e in r["ents"]:
            if str(e["keys"].get("classname", "")).startswith("trigger_"):
                continue
            blockers += [b for b in e["brushes"] if near(b)]
    boxes = []
    for b in blockers:
        cs = _corners(b)
        boxes.append((tuple(min(c[k] for c in cs) - 1 for k in range(3)), tuple(max(c[k] for c in cs) + 1 for k in range(3)), b))
    pillars = {c for (c, *_r) in P.pillars}
    opened = {}
    for (c, z0, z1, _sid) in getattr(P, "slots", []):
        opened.setdefault(c, []).append((z0, z1))
    doorish = {c for d in P.doors for c in d.cells} | {c for (cells, *_w) in P.windows for c in cells}

    def cuttable(cell):
        if cell in doorish or cell in pillars or not (0 < cell[0] < P.W - 1):
            return False
        y = cell[1] - plan_mod.UP if upper else cell[1]
        if not (0 < y < P.H - 1):
            return False
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (cell[0] + dx, cell[1] + dy)
            if n in doorish or P.owner.get(n) not in (None, s.id if s is not None else None):
                return False
        return True

    def state(p):
        """None in the air; ("rock", cell) in plain rock a cut may open; "hard" anything else."""
        cell = (int(math.floor(p[0] / CELL)), int(math.floor(p[1] / CELL)))
        if upper:
            cell = (cell[0], cell[1] + plan_mod.UP)
        if any(z0 <= p[2] <= z1 for (z0, z1) in opened.get(cell, ())):
            return None
        sid = P.owner.get(cell)
        if sid is None:
            return ("rock", cell)
        if (s is not None and sid != s.id) or cell in pillars:
            return "hard"
        sp = P.spaces[sid]
        f = sp.floor.get(cell)
        if f is not None and p[2] < plan_mod.floor_top(f) - 0.5:
            return "hard"
        if p[2] > P.cell_ceil.get(cell, sp.ceil) + 0.5:
            return "hard"
        for (mn, mx, b) in boxes:
            if mn[0] <= p[0] <= mx[0] and mn[1] <= p[1] <= mx[1] and mn[2] <= p[2] <= mx[2] and _holds(b, p, eps=-1.0):
                return "hard"
        return None
    hits = 0
    cells = set()
    cuts = {}
    for p in pts:
        # a point by the axis turns in place (a rod's top in its plate, a hub): not followed
        if (p[0] ** 2 + p[1] ** 2 + p[2] ** 2) ** 0.5 < 24:
            continue
        path = []
        for a in [0.0] + list(angles):
            q = second.swing_end(p, flags, a) if a else p
            w = tuple(origin[k] + q[k] for k in range(3))
            c = (int(math.floor(w[0] / CELL)), int(math.floor(w[1] / CELL)))
            cells.add((c[0], c[1] + plan_mod.UP) if upper else c)
            path.append((w, state(w)))
        kinds = {("rock" if isinstance(st, tuple) else st) for _w, st in path}
        if len(kinds) == 1:
            continue                                  # in the air all the way, or in one thing all the way
        if "hard" in kinds:
            hits += 1
            continue
        # air and plain rock: cut the rock, or it passes through it
        rock = [(w, st[1]) for w, st in path if isinstance(st, tuple)]
        if carve_min_z is not None and all(cuttable(c) and w[2] >= carve_min_z for w, c in rock):
            for w, c in rock:
                z0, z1 = cuts.get(c, [w[2], w[2]])
                cuts[c] = [min(z0, w[2]), max(z1, w[2])]
        else:
            hits += 1
    return hits, cells, cuts


def turning_check(P) -> list:
    """Every turning piece built, swept: [(kind, corners that go into something)] for those that do; the cells each
    sweeps kept off by the items, the lamps and the walls' dressing that come after (P.no_items)."""
    out = []
    for r in getattr(P, "pieces", []):
        mine = [b for b in r["brushes"]]
        for e in r["ents"]:
            t = turn_of(e["keys"])
            if not t:
                continue
            hits, cells, _cuts = sweep(P, r.get("space"), e["brushes"], t[0], t[1], t[2], own=mine, skip={id(r)})
            P.no_items.update(cells)
            if hits:
                out.append((r["kind"], hits))
    return out


def record(P, kind: str, **kw) -> dict:
    r = {"kind": kind, "brushes": [], "ents": [], **kw}
    P.pieces.append(r)
    return r


def node(P, c, z):
    P.piece_nodes[c] = (z, "flat", 0, 0)


def edge(P, a, b, t, both=True):
    P.piece_edges.append((a, b, round(t, 2), both))


# --------------------------------------------------------------------------------------------- the pits
def pits_of(P) -> list:
    """Each sunken part of a hall holding lava, slime (or a chasm): {space, cells, base, kind, level, floor, liq}."""
    out = []
    for i, (cells, kind, z0, level) in enumerate(P.liquids):
        if kind not in ("lava", "slime"):
            continue
        sid = P.owner.get(cells[0]) if cells else None
        if sid is None:
            continue
        s = P.spaces[sid]
        out.append({"space": sid, "cells": set(cells), "base": s.base, "kind": kind, "level": level, "floor": z0, "liq": i})
    for j, (cells, bottom, sid) in enumerate(P.pits):
        s = P.spaces[sid]
        out.append({"space": sid, "cells": set(cells), "base": s.base, "kind": "chasm", "level": None, "floor": bottom,
                    "pit": j})
    return out


def runs(P, pit: dict, held: set) -> list:
    """Straight ways across a pit: a row (a column) of its cells whose two ends lie beside the hall's floor at its
    base - (cells, rim at the start, rim at the end, step)."""
    s = P.spaces[pit["space"]]
    cells = pit["cells"]
    out = []

    def rim(c):
        f = s.floor.get(c)
        return f is not None and f == (pit["base"], "flat", 0, 0) and c not in cells and c not in held

    for c in sorted(cells):
        for d in ((1, 0), (0, 1)):
            back = (c[0] - d[0], c[1] - d[1])
            if not rim(back):
                continue
            row, x = [], c
            while x in cells:
                row.append(x)
                x = (x[0] + d[0], x[1] + d[1])
            if rim(x) and len(row) >= 2:
                out.append((row, back, x, d))
    return out


def _remove_from_liquid(P, pit: dict, cells: set) -> None:
    if "liq" in pit:
        lc, kind, z0, level = P.liquids[pit["liq"]]
        P.liquids[pit["liq"]] = ([c for c in lc if c not in cells], kind, z0, level)
    else:
        pc, bottom, sid = P.pits[pit["pit"]]
        P.pits[pit["pit"]] = ([c for c in pc if c not in cells], bottom, sid)
    pit["cells"] -= set(cells)


# --------------------------------------------------------------------------------------------- the guarded item
def take_item(P, k_or_none, cell, z, why: str, times_of=None) -> bool:
    """Move a valuable item that no mechanic holds to `cell` (the piece's place), keeping the majors apart."""
    plan_mod = pm()
    cands = []
    for cls in GUARD_ITEMS:
        for k, (c_, c, z_, note) in enumerate(P.items):
            if c_ == cls and k not in P.prize_kind and not any(f in note for f in FIXED_NOTES):
                cands.append(k)
    if k_or_none is not None:
        cands = [k_or_none] + [k for k in cands if k != k_or_none]
    for k in cands:
        cls, c0, z0, note = P.items[k]
        if times_of is not None and not plan_mod.majors_apart(P, cls, cell, z, times_of, skip=k):
            continue
        P.items[k] = (cls, cell, z, (f"{note}; " if note else "") + f"guarded by {why}")
        P.no_items.add(cell)
        return True
    return False


def times_fn(P):
    """The plan's seconds from a cell - on the walk with every piece built so far (the showcase of 13.11: the pieces
    took their items on the walk from before any piece, and the rides and stones built after brought two guns near)."""
    plan_mod = pm()
    state = {"key": None, "edges": None, "cache": {}}

    def times_of(c):
        key = (len(P.piece_edges), len(P.piece_nodes))
        if key != state["key"]:
            state["key"], state["edges"], state["cache"] = key, plan_mod.plan_graph(P)[1], {}
        cache = state["cache"]
        if c not in cache:
            cache[c] = plan_mod.dijkstra(state["edges"], c)
        return cache[c]
    return times_of


# --------------------------------------------------------------------------------------------- 1. riding platforms
def trains(P, rnd, held, pits, used) -> None:
    q = P.params
    for n in range(q["trains"]):
        variant = q["train_path"] if q["train_path"] != "mix" else rnd.choice(("across", "loop", "island", "across"))
        done = False
        for pit in sorted(pits, key=lambda p: -len(p["cells"])):
            if pit["space"] in used:
                continue
            rs = sorted(runs(P, pit, held), key=lambda r: (-len(r[0]), r[1]))
            if not rs:
                continue
            if variant == "loop" and len(pit["cells"]) >= 9:
                done = _train_loop(P, rnd, pit, held)
            elif variant == "island":
                done = _train_island(P, rnd, pit, rs, held)
            if not done:
                done = _train_across(P, rnd, pit, rs[0], held)
            if done:
                used.add(pit["space"])
                break
        if not done:
            P.notes.append(say("ездящая платформа не построена: на каркасе нет ямы с лавой или кислотой поперёк зала",
                               "a riding platform not built: no pit of lava or slime across a hall on this skeleton"))


def _train_ent(P, cells, z_top, corners, spd, w, name, loop: bool, link=None) -> dict:
    """A func_train of `cells` (its top at z_top) riding path corners at the cells' boxes (its mins go to each)."""
    xs = [cb(c)[0] for c in cells] + [cb(c)[2] for c in cells]
    ys = [cb(c)[1] for c in cells] + [cb(c)[3] for c in cells]
    x0, y0, x1, y1 = min(xs) + 4, min(ys) + 4, max(xs) - 4, max(ys) - 4
    lo, hi = (x0, y0, z_top - 16), (x1, y1, z_top)
    keys = {"classname": "func_train", "target": f"{name}_0", "speed": spd, "spawnflags": 1, "dmg": 10}
    if link:
        keys["_mapgen_link"] = link
    out = [ent(keys, [bx(lo, hi, "plate", note="train")])]
    for i, corner in enumerate(corners):
        cx, cy = corner[0], corner[1]
        zc = corner[2] if len(corner) > 2 else z_top       # a corner may carry its own top (a ride up to an island)
        nxt = (i + 1) % len(corners)
        out.append(ent({"classname": "path_corner", "targetname": f"{name}_{i}", "target": f"{name}_{nxt}",
                        "wait": w, "origin": f"{round(cx + 4)} {round(cy + 4)} {zc - 16}"}))
    return out


def _train_across(P, rnd, pit, run, held) -> bool:
    cells, rim_a, rim_b, d = run
    names = Names(P)
    spd = speed(P, rnd.choice((TRAIN_SPEED, TRAIN_SPEED, 80, 100)))
    w = wait(P, rnd.choice((0.0, 1.0, 2.0)))
    first, last = cells[0], cells[-1]
    corners = [(cb(first)[0], cb(first)[1]), (cb(last)[0], cb(last)[1])]
    link = f"{mid(rim_a)[0]:.0f} {mid(rim_a)[1]:.0f} {pit['base']} {mid(rim_b)[0]:.0f} {mid(rim_b)[1]:.0f} {pit['base']}"
    r = record(P, "trains", variant="across", cells=list(cells), space=pit["space"], over=pit["kind"])
    r["ents"] += _train_ent(P, [first], pit["base"], corners, spd, w, names("train"), False, link)
    t = len(cells) * CELL / spd + w + 1
    edge(P, rim_a, rim_b, t)
    held.update(cells)
    P.reasons.append(("func_train", say(f"ездящая платформа над {_liq_ru(pit)} поперёк зала {pit['space']}",
                                        f"a platform riding across the {pit['kind']} of hall {pit['space']}")))
    return True


def _train_island(P, rnd, pit, rs, held) -> bool:
    plan_mod = pm()
    s = P.spaces[pit["space"]]
    for cells, rim_a, rim_b, d in rs:
        if len(cells) < 5:
            continue
        isl = cells[len(cells) // 2]
        # the island off the rims and its sides in the pit too (one rides to it, nobody walks)
        side = [(isl[0] + d[1], isl[1] + d[0]), (isl[0] - d[1], isl[1] - d[0])]
        if not all(x in pit["cells"] for x in side):
            continue
        ride = cells[:len(cells) // 2]
        _remove_from_liquid(P, pit, {isl})
        # the island stands ISLAND_RISE over the rim - over any jump (the game's 45 and a step): the ride is the only
        # way on (the showcase of 13.11: an island one pit cell off the side's rim was a running jump from a
        # shotgun, 1.2 s); one jumps down off it
        top = pit["base"] + ISLAND_RISE
        s.floor[isl] = (top, "flat", 0, 0)
        names = Names(P)
        spd = speed(P, rnd.choice((TRAIN_SPEED, 80)))
        w = wait(P, rnd.choice((1.0, 2.0)))
        corners = [(cb(ride[0])[0], cb(ride[0])[1], pit["base"]), (cb(ride[-1])[0], cb(ride[-1])[1], top)]
        link = f"{mid(rim_a)[0]:.0f} {mid(rim_a)[1]:.0f} {pit['base']} {mid(isl)[0]:.0f} {mid(isl)[1]:.0f} {top}"
        r = record(P, "trains", variant="island", cells=list(ride), island=isl, space=pit["space"], over=pit["kind"])
        r["ents"] += _train_ent(P, [ride[0]], pit["base"], corners, spd, w, names("train"), False, link)
        r["brushes"].append(bx((cb(isl, 8)[0], cb(isl, 8)[1], top - 8), (cb(isl, 8)[2], cb(isl, 8)[3], top),
                               "tread", note="island tread"))
        node(P, isl, top)
        edge(P, rim_a, isl, len(ride) * CELL / spd + w + 1)
        # off the island one jumps down to any rim within a running jump (the walk's 256 u): one way, and the majors
        # are kept apart on it too (the showcase of 13.11: the island's hyperblaster a jump down from a shotgun, 1.2 s)
        for c2, f2 in s.floor.items():
            if c2 in pit["cells"] or c2 == isl or f2[1] != "flat" or f2[0] > top - 24:
                continue
            gap = max(abs(c2[0] - isl[0]), abs(c2[1] - isl[1]))
            if gap <= 4:
                edge(P, isl, c2, math.hypot(c2[0] - isl[0], c2[1] - isl[1]) * CELL / 300.0 + 0.3, both=False)
        held.update(ride + [isl])
        take_item(P, None, isl, top, "a ride to an island")
        P.reasons.append(("func_train", say(f"платформа возит на островок с ценным предметом посреди {_liq_ru(pit)}",
                                            f"a platform rides to an island holding a valuable item in the {pit['kind']}")))
        return True
    return False


def _train_loop(P, rnd, pit, held) -> bool:
    """A loop round the pit's ring (q2dm3's slime): the platform rides the cells by the rim, round and round."""
    cells = pit["cells"]
    xs, ys = [c[0] for c in cells], [c[1] for c in cells]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return False
    ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if not all(c in cells for c in ring):
        return False
    s = P.spaces[pit["space"]]
    names = Names(P)
    spd = speed(P, rnd.choice((TRAIN_SPEED, 80)))
    corners = [(cb(c)[0], cb(c)[1]) for c in ring]
    # the rims beside each corner: one boards anywhere, gets off at the next corner
    rims = []
    for c in ring:
        near = [(c[0] + dx, c[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        rims.append(next((x for x in near if s.floor.get(x) == (pit["base"], "flat", 0, 0) and x not in cells), None))
    if sum(1 for r_ in rims if r_) < 2:
        return False
    link = " ".join(f"{mid(r_)[0]:.0f} {mid(r_)[1]:.0f} {pit['base']}" for r_ in rims if r_)
    r = record(P, "trains", variant="loop", cells=ring, space=pit["space"], over=pit["kind"])
    r["ents"] += _train_ent(P, [ring[0]], pit["base"], corners, spd, 0, names("train"), True, link)
    on = [r_ for r_ in rims if r_]
    for i, a in enumerate(on):
        b = on[(i + 1) % len(on)]
        edge(P, a, b, (abs(a[0] - b[0]) + abs(a[1] - b[1])) * CELL / spd + 1, both=False)
    held.update(ring)
    P.reasons.append(("func_train", say(f"платформа кружит над {_liq_ru(pit)} по кругу",
                                        f"a platform riding a loop over the {pit['kind']}")))
    return True


def _liq_ru(pit) -> str:
    return {"lava": "лавой", "slime": "кислотой", "chasm": "пропастью"}.get(pit["kind"], pit["kind"])


# --------------------------------------------------------------------------------------------- 2. sinking stones
def stones(P, rnd, held, pits, used) -> None:
    q = P.params
    for n in range(q["stones"]):
        shape = q["stone_shape"] if q["stone_shape"] != "mix" else rnd.choice(("row", "gaps", "zigzag"))
        done = False
        for pit in sorted(pits, key=lambda p: -len(p["cells"])):
            if pit["space"] in used or pit["kind"] == "chasm" and shape == "gaps":
                continue
            for cells, rim_a, rim_b, d in sorted(runs(P, pit, held), key=lambda r: (-len(r[0]), r[1])):
                if len(cells) < 3:
                    continue
                path = list(cells)
                if shape == "zigzag":
                    side = (d[1], d[0])
                    zz = [c if i % 2 == 0 else (c[0] + side[0], c[1] + side[1]) for i, c in enumerate(cells)]
                    if all(c in pit["cells"] for c in zz):
                        path = zz
                stones_at = path[::2] if shape == "gaps" and len(path) >= 5 else path
                _lay_stones(P, rnd, pit, stones_at, rim_a, rim_b, shape)
                held.update(path)
                used.add(pit["space"])
                done = True
                break
            if done:
                break
        if not done:
            P.notes.append(say("тонущие плиты не построены: нет ямы с лавой или кислотой длиной 3 клетки и больше",
                               "sinking stones not built: no pit of lava or slime 3 cells long or more"))


def _lay_stones(P, rnd, pit, cells, rim_a, rim_b, shape) -> None:
    names = Names(P)
    base = pit["base"]
    low = pit["level"] if pit["level"] is not None else base - 160
    sink = base - low + 40                  # the cap 40 under the surface (into the chasm: out of reach)
    delay = round(rnd.choice((STONE_DELAY, 1.5, 1.0, 2.5)) * P.params.get("piece_wait", 100) / 100, 1)
    w = wait(P, rnd.choice((STONE_WAIT, 1.0, 2.0)))
    spd = speed(P, STONE_SPEED)
    r = record(P, "stones", variant=shape, cells=list(cells), space=pit["space"], over=pit["kind"])
    for c in cells:
        tn = names("stone")
        x0, y0, x1, y1 = cb(c, 6)
        stem = cb(c, 22)
        # a cap on a stem (q2dm6's mushrooms): both ride down together; its top at rest is a floor to the survey
        r["ents"].append(ent({"classname": "func_door", "targetname": tn, "angle": -2, "speed": spd, "wait": w,
                              "lip": max(8, base - pit["floor"] - sink), "_mapgen_floor": 1},
                             [bx((x0, y0, base - 16), (x1, y1, base), "plate", note="stone cap"),
                              bx((stem[0], stem[1], pit["floor"]), (stem[2], stem[3], base - 16), "trim", note="stone stem")]))
        r["ents"].append(ent({"classname": "trigger_multiple", "target": tn, "delay": delay, "wait": 0.5},
                             [bx((x0 + 4, y0 + 4, base), (x1 - 4, y1 - 4, base + 16), "trigger")]))
        node(P, c, base)
    # the plan walks stone to stone (a gap of one cell is jumped)
    seq = [rim_a] + list(cells) + [rim_b]
    for a, b in zip(seq, seq[1:]):
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1:
            edge(P, a, b, 0.6)
    P.reasons.append(("func_door", say(f"тонущие плиты над {_liq_ru(pit)}: наступил - через {delay} с уходят вниз на {w} с",
                                       f"stones over the {pit['kind']}: stepped on, in {delay} s they sink for {w} s")))


# --------------------------------------------------------------------------------------------- 3. trap rooms
def traps(P, rnd, held, times_of) -> None:
    q = P.params
    for n in range(q["traps"]):
        trig = q["trap_trigger"] if q["trap_trigger"] != "mix" else rnd.choice(("buttons", "plate", "item"))
        hazard = q["trap_hazard"] if q["trap_hazard"] != "mix" else rnd.choice(("lava", "slime", "crusher", "lava"))
        if not _trap_room(P, rnd, held, times_of, trig, hazard):
            P.notes.append(say("комната-ловушка не построена: нет зала со свободным ровным местом 4 на 4 клетки",
                               "a trap room not built: no hall with a free flat place of 4 by 4 cells"))


def _trap_room(P, rnd, held, times_of, trig, hazard) -> bool:
    plan_mod = pm()
    halls = [s for s in P.spaces if not s.solid and s.kind in ("hall", "room") and not s.atrium and s.floor
             and plan_mod.layer_of(next(iter(s.floor))) == 0]
    rnd.shuffle(halls)
    halls.sort(key=lambda s: -len(s.floor))
    door_cells = {c for d in P.doors for c in d.cells}
    # the PO 13.11: «закрывающиеся комнаты чтобы были разных размеров и формы (и не повторялись из карты в карту)» -
    # the footprint drawn from rectangles of 2..4 cells a side, the shape and the roof in _build_trap
    sizes = [(2, 2), (2, 3), (3, 2), (3, 3), (3, 4), (4, 3), (2, 4), (4, 2)]
    rnd.shuffle(sizes)
    for s in halls:
        for kx, ky in sizes:
            k = min(kx, ky)
            for c in sorted(s.floor):
                room = [(c[0] + i, c[1] + j) for i in range(kx) for j in range(ky)]
                ring = {(x[0] + dx, x[1] + dy) for x in room for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - set(room)
                if any(s.floor.get(x) != (s.base, "flat", 0, 0) or x in held for x in room):
                    continue
                if any(s.floor.get(x) != (s.base, "flat", 0, 0) or x in held or x in door_cells
                       or any((x[0] + dx, x[1] + dy) in door_cells for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                       for x in ring):
                    continue
                if plan_mod._stacked_over(P, room) or s.ceil - s.base < 192:
                    continue
                centre = (c[0] + kx // 2, c[1] + ky // 2) if kx % 2 or ky % 2 else (c[0] + kx // 2 - rnd.randint(0, 1), c[1] + ky // 2 - rnd.randint(0, 1))
                if not take_item(P, None, centre, s.base, "a trap room", times_of):
                    continue
                _build_trap(P, rnd, s, room, k, trig, hazard, centre)
                held.update(room | ring if isinstance(room, set) else set(room) | ring)
                return True
    return False


def _build_trap(P, rnd, s, room, k, trig, hazard, centre) -> None:
    names = Names(P)
    base = s.base
    xs = [cb(c)[0] for c in room] + [cb(c)[2] for c in room]
    ys = [cb(c)[1] for c in room] + [cb(c)[3] for c in room]
    X0, Y0, X1, Y1 = min(xs), min(ys), max(xs), max(ys)
    import mapgen_scratch_forms as forms
    # the PO 13.11: each trap room its own - its height, its plan (a box, or its corners cut: an octagon), its roof (flat,
    # stepped, a gable, a pyramid of slabs), mullions or none
    H = rnd.choice((112, 128, 144, 160, 176))
    H = max(112, min(H, s.ceil - s.base - 56))
    shape = rnd.choice(("box", "chamfer", "chamfer"))
    roof = rnd.choice(("flat", "stepped", "gable", "pyramid"))
    mullions = rnd.random() < 0.5
    t_go, t_doors, t_haz = names("trap"), names("doors"), names("hazard")
    r = record(P, "traps", variant=f"{trig}/{hazard}/{shape}/{roof}/{len(set(xs)) - 1}x{len(set(ys)) - 1}",
               cells=list(room), space=s.id, trigger=trig, hazard=hazard)
    # the doorways: the middle of two opposite sides (one side when the room is small)
    sides = [("x0", (X0, (Y0 + Y1) / 2)), ("x1", (X1, (Y0 + Y1) / 2))] if rnd.random() < 0.5 else \
            [("y0", ((X0 + X1) / 2, Y0)), ("y1", ((X0 + X1) / 2, Y1))]
    if k == 2 and rnd.random() < 0.5:
        sides = sides[:1]
    door_w = 64
    t = 4                                             # the glass's thickness
    L = 16                                            # the lintels' height
    # the plan: the box's corners, or cut (the straight part of each side keeps its doorway and a pane beside it)
    ch = 0
    if shape == "chamfer":
        ch = min(rnd.choice((24, 32, 48)), (min(X1 - X0, Y1 - Y0) - door_w - 16) / 2)
        if trig == "buttons" and not OLD_TRAP_BUTTON:
            # a button beside a doorway stands on the straight part of its side, clear of the corner's post (the
            # button 16 wide from 8 past the doorway, the post 8 each way of the corner)
            dl = (Y1 - Y0) if sides[0][0][0] == "x" else (X1 - X0)
            ch = min(ch, dl / 2 - door_w / 2 - 8 - 16 - 10)
        if ch < 16:
            shape, ch = "box", 0
    def outline(d):
        """The plan moved out by d (in for a negative d): its sides d off, its cut corners the same cut."""
        x0, y0, x1, y1 = X0 - d, Y0 - d, X1 + d, Y1 + d
        if ch:
            c_ = max(1.0, ch + d * 0.41)
            return [(x0 + c_, y0), (x1 - c_, y0), (x1, y0 + c_), (x1, y1 - c_), (x1 - c_, y1), (x0 + c_, y1), (x0, y1 - c_), (x0, y0 + c_)]
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    poly = outline(0)

    def side_of(a, b):
        if abs(a[0] - b[0]) < 0.5:
            return "x0" if abs(a[0] - X0) < 0.5 else "x1" if abs(a[0] - X1) < 0.5 else ""
        if abs(a[1] - b[1]) < 0.5:
            return "y0" if abs(a[1] - Y0) < 0.5 else "y1" if abs(a[1] - Y1) < 0.5 else ""
        return ""
    # the walls: glass panes along each side, the doorways' gaps left; a post at each corner; lintels from post to post
    # over the panes and the doorways (a roof on posts alone stood «in the air» - the rule of nothing hanging)
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        name_ = side_of(a, b)
        gap = next((p for n_, p in sides if n_ == name_), None)
        segs = [(a, b)]
        if gap is not None:
            if name_[0] == "x":
                lo_, hi_ = sorted((a[1], b[1]))
                segs = [((a[0], lo_), (a[0], gap[1] - door_w / 2)), ((a[0], gap[1] + door_w / 2), (a[0], hi_))]
            else:
                lo_, hi_ = sorted((a[0], b[0]))
                segs = [((lo_, a[1]), (gap[0] - door_w / 2, a[1])), ((gap[0] + door_w / 2, a[1]), (hi_, a[1]))]
        for p0, p1 in segs:
            if abs(p1[0] - p0[0]) + abs(p1[1] - p0[1]) > 2:
                r["brushes"].append(forms.prism("z", forms.thin_bar(p0, p1, t / 2), base, base + H - L, "glass", 0, "trap glass"))
                if mullions and gap is None and abs(p1[0] - p0[0]) + abs(p1[1] - p0[1]) >= 128:
                    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
                    r["brushes"].append(bx((mx - 4, my - 4, base), (mx + 4, my + 4, base + H - L), "trim", note="trap mullion"))
        r["brushes"].append(forms.prism("z", forms.thin_bar(a, b, 8), base + H - L, base + H, "trim", 1, "trap lintel"))
    for (px, py) in poly:
        r["brushes"].append(bx((px - 8, py - 8, base), (px + 8, py + 8, base + H + 8), "trim", note="trap post"))
    r["brushes"].append(forms.prism("z", outline(8), base + H, base + H + 8, "trim", 1, "trap roof"))
    # the roof over it: a step, a pyramid of slabs, or a gable along the longer side
    if roof == "stepped":
        r["brushes"].append(forms.prism("z", outline(-24), base + H + 8, base + H + 20, "trim", 1, "trap roof"))
    elif roof == "pyramid":
        for k_, d_ in enumerate((16, 36, 56)):
            pp = outline(-d_)
            if min(max(p[0] for p in pp) - min(p[0] for p in pp), max(p[1] for p in pp) - min(p[1] for p in pp)) > 24:
                r["brushes"].append(forms.prism("z", pp, base + H + 8 + 10 * k_, base + H + 18 + 10 * k_, "trim", 1, "trap roof"))
    elif roof == "gable":
        rise = min(48, (min(X1 - X0, Y1 - Y0)) / 3)
        z0 = base + H + 8
        if X1 - X0 >= Y1 - Y0:
            r["brushes"].append(forms.prism("x", [(Y0 - 8, z0), (Y1 + 8, z0), ((Y0 + Y1) / 2, z0 + rise)], X0 - 8, X1 + 8,
                                            "trim", 1, "trap roof"))
        else:
            r["brushes"].append(forms.prism("y", [(X0 - 8, z0), (X1 + 8, z0), ((X0 + X1) / 2, z0 + rise)], Y0 - 8, Y1 + 8,
                                            "trim", 1, "trap roof"))
    # the doors: rising from under the floor into each doorway (q2dm3's), crushing whoever stands in it
    d_wait = wait(P, TRAP_DOOR_WAIT)
    h_wait = wait(P, TRAP_HAZARD_WAIT)
    for name_, (gx, gy) in sides:
        if name_.startswith("x"):
            lo, hi = (gx - 6, gy - door_w / 2, base - H), (gx + 6, gy + door_w / 2, base - 8)
        else:
            lo, hi = (gx - door_w / 2, gy - 6, base - H), (gx + door_w / 2, gy + 6, base - 8)
        r["ents"].append(ent({"classname": "func_door", "targetname": t_doors, "angle": -1, "lip": 8,
                              "speed": speed(P, TRAP_DOOR_SPEED), "wait": d_wait, "dmg": TRAP_DOOR_DMG, "spawnflags": 4},
                             [bx(lo, hi, "trim", note="trap door")]))
        # the button by each doorway, on the room's outside (q2dm3: one from each side)
        if trig == "buttons":
            # its back on the pane's outer face (the test map mg_new_368_mach4: 4 into the pane, «16 of 64 points in a
            # wall piece»), 20 out of it; pressed, it goes into the pane as people's buttons into their walls
            out_ = -1 if name_ in ("x0", "y0") else 1
            face = (gx if name_.startswith("x") else gy) + out_ * (t / 2 if not OLD_TRAP_BUTTON else -4)
            depth = 20 if not OLD_TRAP_BUTTON else 24
            a_, b_ = sorted((face, face + out_ * depth))
            if name_.startswith("x"):
                blo, bhi = (a_, gy + door_w / 2 + 8, base + 40), (b_, gy + door_w / 2 + 24, base + 64)
                ang = 0 if name_ == "x0" else 180
            else:
                blo, bhi = (gx + door_w / 2 + 8, a_, base + 40), (gx + door_w / 2 + 24, b_, base + 64)
                ang = 90 if name_ == "y0" else 270
            r["ents"].append(ent({"classname": "func_button", "target": t_go, "angle": ang, "wait": d_wait + 1,
                                  "speed": 200, "lip": 4}, [bx(blo, bhi, "button", note="trap button")]))
    if trig == "plate":
        # a plate in the room's floor round the item: stepping in closes it
        cx, cy = mid(centre)
        r["ents"].append(ent({"classname": "trigger_multiple", "target": t_go, "wait": d_wait + 2},
                             [bx((cx - 40, cy - 40, base), (cx + 40, cy + 40, base + 24), "trigger")]))
        # the plate's mark a frame round the item, 2 high: a mark under the item itself put it 2 into a brush and the
        # game removed it at the start (the showcase of 13.11: its rocket launcher «lost at spawn»)
        for (lo, hi) in (((cx - 40, cy - 40), (cx + 40, cy - 28)), ((cx - 40, cy + 28), (cx + 40, cy + 40)),
                         ((cx - 40, cy - 28), (cx - 28, cy + 28)), ((cx + 28, cy - 28), (cx + 40, cy + 28))):
            r["brushes"].append(bx((lo[0], lo[1], base), (hi[0], hi[1], base + 2), "plate_mark", note="trap plate"))
    if trig == "item":
        r["item_target"] = (centre, t_go)
    # the relay: the doors at once, the hazard after its delay
    r["ents"].append(ent({"classname": "trigger_relay", "targetname": t_go, "target": t_doors,
                          "origin": f"{(X0 + X1) / 2:.0f} {(Y0 + Y1) / 2:.0f} {base + 64}"}))
    r["ents"].append(ent({"classname": "trigger_relay", "targetname": t_go, "target": t_haz, "delay": TRAP_HAZARD_DELAY,
                          "origin": f"{(X0 + X1) / 2:.0f} {(Y0 + Y1) / 2 + 8:.0f} {base + 64}"}))
    if hazard in ("lava", "slime"):
        # the liquid under the floor rises 56 through it (q2dm3's func_water), stays, sinks back
        r["ents"].append(ent({"classname": "func_water", "targetname": t_haz, "angle": -1, "lip": 0,
                              "speed": speed(P, TRAP_HAZARD_SPEED), "wait": h_wait},
                             [forms.prism("z", outline(-2), base - 64, base - 8, hazard,
                                          {"lava": 8, "slime": 16}[hazard], "trap liquid")]))
    else:
        # the roof's inner slab comes down to a crouch's height and hurts: 64 down, from 104 over the floor to 40 (one
        # crouching lives). The game moves a door by its size less its lip - the slab is 20 deep, so the lip is -44
        # (3.68's first build had 40: the slab went 20 UP into the roof)
        r["ents"].append(ent({"classname": "func_door", "targetname": t_haz, "angle": -2, "lip": -44,
                              "speed": speed(P, 80), "wait": h_wait, "dmg": 15, "spawnflags": 4},
                             [forms.prism("z", outline(-10), base + H - 24 - L, base + H - 4 - L, "trim", 1, "trap crusher")]))
    P.reasons.append(("func_door", say(f"комната-ловушка в зале {s.id}: {_trig_ru(trig)} закрывают её двери, через секунду - {_haz_ru(hazard)}",
                                       f"a trap room in hall {s.id}: {trig} close its doors, a second later the {hazard}")))


def _trig_ru(t):
    return {"buttons": "кнопки", "plate": "плита в полу", "item": "взятый предмет"}[t]


def _haz_ru(h):
    return {"lava": "поднимается лава", "slime": "поднимается кислота", "crusher": "опускается потолок"}[h]


# --------------------------------------------------------------------------------------------- 4. rotating pieces
def rotators(P, rnd, held, pits, used, times_of) -> None:
    q = P.params
    for n in range(q["rotators"]):
        kind = q["rotator_kind"] if q["rotator_kind"] != "mix" else rnd.choice(("drum", "flap", "fan"))
        done = False
        if kind == "drum":
            done = _drum(P, rnd, held, pits, used)
        if kind == "flap" or (kind == "drum" and not done):
            done = _flap(P, rnd, held)
        if kind == "fan" or not done:
            done = _fan(P, rnd, held)
        if not done:
            P.notes.append(say("вращающаяся конструкция не построена: на каркасе нет для неё места",
                               "a rotating piece not built: no room for it on this skeleton"))


def _octagon(cx, cy, cz, r, along, half_len) -> dict:
    """An octagonal prism about an axis (x or y) through (cx, cy, cz): its planes (the world builder makes it)."""
    return {"octagon": [round(cx), round(cy), round(cz), round(r), along, round(half_len)], "role": "drum", "contents": 0}


def _drum(P, rnd, held, pits, used) -> bool:
    for pit in sorted(pits, key=lambda p: -len(p["cells"])):
        if pit["space"] in used:
            continue
        for cells, rim_a, rim_b, d in sorted(runs(P, pit, held), key=lambda r: (-len(r[0]), r[1])):
            if len(cells) < 2:
                continue
            base = pit["base"]
            r_ = 48
            xs = [cb(c)[0] for c in cells] + [cb(c)[2] for c in cells]
            ys = [cb(c)[1] for c in cells] + [cb(c)[3] for c in cells]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            along = "x" if d[0] else "y"
            half = ((max(xs) - min(xs)) if along == "x" else (max(ys) - min(ys))) / 2 - 2
            spd = speed(P, rnd.choice((DRUM_SPEED, 30, 40)))
            # its axis along the way across: one walks its top while it rolls under the feet (q2dm6's)
            flags = 1 | (2 if rnd.random() < 0.5 else 0) | (4 if along == "x" else 8)
            link = f"{mid(rim_a)[0]:.0f} {mid(rim_a)[1]:.0f} {base} {mid(rim_b)[0]:.0f} {mid(rim_b)[1]:.0f} {base}"
            rec = record(P, "rotators", variant="drum", cells=list(cells), space=pit["space"], over=pit["kind"])
            rec["ents"].append(ent({"classname": "func_rotating", "origin": f"{cx:.0f} {cy:.0f} {base - r_}", "speed": spd,
                                    "spawnflags": flags, "_mapgen_link": link},
                                   [_octagon(cx, cy, base - r_, r_, along, half)]))
            for c in cells:
                node(P, c, base)
            edge(P, rim_a, rim_b, len(cells) * CELL / 200 + 0.5)
            held.update(cells)
            used.add(pit["space"])
            P.reasons.append(("func_rotating", say(f"вращающийся барабан над {_liq_ru(pit)} - по нему переходят",
                                                   f"a drum rotating over the {pit['kind']} - one walks across it")))
            return True
    return False


def passages(P, held, widths=(1, 2, 3)) -> list:
    """Straight passages a piece spans across: (space, the cross-section's cells, the way along) - a cross-section 1 to
    3 cells wide, walls on both its ends, the floor going on before and after each of its cells (a corridor, a hall's
    narrow part), all at one height, off doorways and held cells."""
    plan_mod = pm()
    out = []
    door_cells = {c for d in P.doors for c in d.cells}
    for s in P.spaces:
        if s.solid or not s.floor or s.kind not in ("corridor", "room", "hall") or \
                plan_mod.layer_of(next(iter(s.floor))) != 0:
            continue
        for c, f in s.floor.items():
            if f[1] != "flat":
                continue
            for d in ((1, 0), (0, 1)):
                perp = (d[1], d[0])
                if (c[0] - perp[0], c[1] - perp[1]) in s.floor:
                    continue                      # not the cross-section's first cell
                cross, x = [], c
                while x in s.floor and s.floor[x] == f and len(cross) <= 3:
                    cross.append(x)
                    x = (x[0] + perp[0], x[1] + perp[1])
                if len(cross) not in widths or x in s.floor:
                    continue
                ok = all((y[0] + d[0], y[1] + d[1]) in s.floor and (y[0] - d[0], y[1] - d[1]) in s.floor
                         and s.floor[(y[0] + d[0], y[1] + d[1])][0] == f[0] == s.floor[(y[0] - d[0], y[1] - d[1])][0]
                         and y not in held and y not in door_cells for y in cross)
                if ok:
                    out.append((s, cross, d))
    return out


def _corridor_cells(P, held):
    """Straight corridor cells (2 neighbours of its space in a line, the others not), off doorways and items."""
    plan_mod = pm()
    out = []
    door_cells = {c for d in P.doors for c in d.cells}
    for s in P.spaces:
        if s.solid or s.kind != "corridor" or plan_mod.layer_of(next(iter(s.floor or {(0, 0): 0}))) != 0:
            continue
        for c, f in s.floor.items():
            if f[1] != "flat" or c in held or c in door_cells:
                continue
            for d in ((1, 0), (0, 1)):
                a, b = (c[0] - d[0], c[1] - d[1]), (c[0] + d[0], c[1] + d[1])
                sa, sb = (c[0] + d[1], c[1] + d[0]), (c[0] - d[1], c[1] - d[0])
                if a in s.floor and b in s.floor and sa not in s.floor and sb not in s.floor and \
                        s.floor[a][0] == f[0] == s.floor[b][0]:
                    out.append((s, c, d))
    return out


def _flap(P, rnd, held) -> bool:
    """A flap across a passage turning about a level axis across it (q2dm4's by the quad): one passes when it lies flat."""
    cands = passages(P, held, (1, 2))
    rnd.shuffle(cands)
    for s, cross, d in cands[:1]:
        z = s.floor[cross[0]][0]
        xs = [cb(x)[0] for x in cross] + [cb(x)[2] for x in cross]
        ys = [cb(x)[1] for x in cross] + [cb(x)[3] for x in cross]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        h = min(112, s.ceil - z - 24)
        along = "y" if d[0] else "x"           # the axis across the passage
        if along == "x":
            lo, hi = (min(xs) + 2, cy - 4, z + 8), (max(xs) - 2, cy + 4, z + 8 + h)
            flags = 1 | 4
        else:
            lo, hi = (cx - 4, min(ys) + 2, z + 8), (cx + 4, max(ys) - 2, z + 8 + h)
            flags = 1 | 8
        c = cross[0]
        rec = record(P, "rotators", variant="flap", cells=list(cross), space=s.id)
        rec["ents"].append(ent({"classname": "func_rotating", "origin": f"{cx:.0f} {cy:.0f} {z + 8 + h / 2:.0f}",
                                "speed": speed(P, rnd.choice((FLAP_SPEED, 45, 90))), "spawnflags": flags, "dmg": 5},
                               [bx(lo, hi, "trim", note="flap")]))
        held.update(cross)
        P.reasons.append(("func_rotating", say("вращающаяся заслонка поперёк коридора - проходить, когда она легла",
                                               "a flap turning across a corridor - one passes when it lies flat")))
        return True
    return False


def _fan(P, rnd, held) -> bool:
    """A fan on the floor by a valuable item (q2rdm7's): two bars turning fast at the knees, it hurts on touch."""
    plan_mod = pm()
    for (cls, c, z, note) in sorted(P.items, key=lambda it: GUARD_ITEMS.index(it[0]) if it[0] in GUARD_ITEMS else 99):
        if cls not in GUARD_ITEMS or c not in P.owner:
            continue
        s = P.spaces[P.owner[c]]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + dx, c[1] + dy)
            if s.floor.get(n) != (z, "flat", 0, 0) or n in held:
                continue
            cx, cy = mid(n)
            rec = record(P, "rotators", variant="fan", cells=[n], space=s.id)
            rec["ents"].append(ent({"classname": "func_rotating", "origin": f"{cx:.0f} {cy:.0f} {z + 20}",
                                    "speed": speed(P, FAN_SPEED), "spawnflags": 1 | 16, "dmg": FAN_DMG},
                                   [bx((cx - 28, cy - 4, z + 14), (cx + 28, cy + 4, z + 26), "trim", note="fan"),
                                    bx((cx - 4, cy - 28, z + 14), (cx + 4, cy + 28, z + 26), "trim", note="fan")]))
            held.add(n)
            P.reasons.append(("func_rotating", say(f"вентилятор у {cls}: задевает - больно", f"a fan by the {cls}: it hurts on touch")))
            return True
    return False


# --------------------------------------------------------------------------------------------- 5. timed shutters
def shutters(P, rnd, held) -> None:
    for n in range(P.params["shutters"]):
        if not _shutter(P, rnd, held):
            P.notes.append(say("створки по таймеру не построены: нет прямого прохода в комнату с ценным предметом",
                               "timed shutters not built: no straight doorway into a room with a valuable item"))


def _guarded_spaces(P) -> dict:
    """The places holding a valuable item no nook of a prize holds (a prize's way is the form's row, not a shutter)."""
    out = {}
    for k, (cls, c, z, note) in enumerate(P.items):
        if cls in GUARD_ITEMS and c in P.owner and k not in P.prize_kind and P.spaces[P.owner[c]].kind != "nook":
            out.setdefault(P.owner[c], cls)
    return out


def _shutter(P, rnd, held) -> bool:
    worth = _guarded_spaces(P)
    used = {tuple(x) for r in P.pieces for x in r.get("door_cells", [])}
    for d in sorted(P.doors, key=lambda d: (d.b not in worth and d.a not in worth, len(d.cells))):
        if d.kind != "door" or d.mover or d.stair or d.cross or len(d.cells) > 2 or tuple(d.cells[0]) in used:
            continue
        if d.a not in worth and d.b not in worth:
            continue
        xs, ys = {c[0] for c in d.cells}, {c[1] for c in d.cells}
        if len(xs) > 1 and len(ys) > 1:
            continue
        names = Names(P)
        tn = names("shutter")
        x0 = min(cb(c)[0] for c in d.cells)
        x1 = max(cb(c)[2] for c in d.cells)
        y0 = min(cb(c)[1] for c in d.cells)
        y1 = max(cb(c)[3] for c in d.cells)
        z0, z1 = d.z, pm().door_top(d)
        # the wall runs along x when the doorway's cells lie in a row along x - or its single cell: by its spaces
        along_x = len(xs) > 1 or (len(xs) == 1 and len(ys) == 1 and _wall_along_x(P, d))
        rec = record(P, "shutters", cells=[list(c) for c in d.cells], door_cells=[list(c) for c in d.cells])
        team = names("team")
        if along_x:
            ym = (y0 + y1) / 2
            halves = [((x0, ym - 4, z0), ((x0 + x1) / 2, ym + 4, z1), 180), (((x0 + x1) / 2, ym - 4, z0), (x1, ym + 4, z1), 0)]
        else:
            xm = (x0 + x1) / 2
            halves = [((xm - 4, y0, z0), (xm + 4, (y0 + y1) / 2, z1), 270), ((xm - 4, (y0 + y1) / 2, z0), (xm + 4, y1, z1), 90)]
        for lo, hi, ang in halves:
            rec["ents"].append(ent({"classname": "func_door", "targetname": tn, "angle": ang, "speed": speed(P, SHUTTER_SPEED),
                                    "spawnflags": 32, "team": team, "lip": 4}, [bx(lo, hi, "trim", note="shutter")]))
        rec["ents"].append(ent({"classname": "func_timer", "target": tn, "spawnflags": 1,
                                "wait": wait(P, rnd.choice((SHUTTER_WAIT, 3.0, 4.0, 5.0))), "random": SHUTTER_RANDOM,
                                "delay": 2, "origin": f"{(x0 + x1) / 2:.0f} {(y0 + y1) / 2:.0f} {z1 + 8}"}))
        held.update(d.cells)
        P.reasons.append(("func_door", say("створки на таймере открывают и закрывают проход к ценному предмету",
                                           "shutters on a timer open and close the way to a valuable item")))
        return True
    return False


def _wall_along_x(P, d) -> bool:
    c = d.cells[0]
    return (c[0], c[1] - 1) in P.owner or (c[0], c[1] + 1) in P.owner


# --------------------------------------------------------------------------------------------- 6. pickup walls
def pickup_walls(P, rnd, held) -> None:
    for n in range(P.params["pickup_walls"]):
        if not _pickup_wall(P, rnd, held):
            P.notes.append(say("стена от предмета не построена: рядом с ценными предметами нет стены между двумя комнатами",
                               "a pickup wall not built: no wall between two rooms near a valuable item"))


def _pickup_wall(P, rnd, held) -> bool:
    """Taking a valuable item opens a wall nearby (q2dm6's body armour, q2duel2's mega): a shortcut between two places
    shows for a while (or for good)."""
    plan_mod = pm()
    door_cells = {c for d in P.doors for c in d.cells}
    taken = {r.get("item_cell") for r in P.pieces if r.get("item_cell")}
    for k, (cls, c, z, note) in enumerate(P.items):
        if cls not in GUARD_ITEMS or c not in P.owner or c in taken:
            continue
        for w_ in sorted(((c[0] + dx, c[1] + dy) for dx in range(-5, 6) for dy in range(-5, 6)),
                         key=lambda x: abs(x[0] - c[0]) + abs(x[1] - c[1])):
            if w_ in P.owner or w_ in door_cells or w_ in held or plan_mod.layer_of(w_) != 0:
                continue
            for dd in ((1, 0), (0, 1)):
                a, b = (w_[0] - dd[0], w_[1] - dd[1]), (w_[0] + dd[0], w_[1] + dd[1])
                sa, sb = P.owner.get(a), P.owner.get(b)
                if sa is None or sb is None or sa == sb:
                    continue
                fa, fb = P.spaces[sa].floor.get(a), P.spaces[sb].floor.get(b)
                if not fa or not fb or fa[1] != "flat" or fb[1] != "flat" or abs(fa[0] - fb[0]) > 16 or a in held or b in held:
                    continue
                # nobody's next to it across (a lone wall cell between the two places)
                if (w_[0] + dd[1], w_[1] + dd[0]) in P.owner or (w_[0] - dd[1], w_[1] - dd[0]) in P.owner:
                    continue
                zf = max(fa[0], fb[0])
                names = Names(P)
                tn = names("wall")
                d = plan_mod.Door(sa, sb, [w_], za=fa[0], zb=fb[0], z=zf, kind="secret")
                P.doors.append(d)
                x0, y0, x1, y1 = cb(w_)
                stay = rnd.random() < 0.3
                rec = record(P, "pickup_walls", cells=[w_], item_cell=c, item=cls, stays=stay)
                rec["ents"].append(ent({"classname": "func_door", "targetname": tn, "angle": -2, "lip": 8, "_mapgen_floor": 1,
                                        "speed": speed(P, rnd.choice((WALL_SPEED * 3, 150, 200))),
                                        "wait": -1 if stay else wait(P, rnd.choice((8.0, 12.0, 15.0)))},
                                       [bx((x0, y0, zf), (x1, y1, zf + plan_mod.DOOR_H), "wall", note="pickup wall")]))
                rec["item_target"] = (c, tn)
                held.add(w_)
                P.reasons.append(("func_door", say(f"взял {cls} - рядом опускается стена и открывает короткий путь",
                                                   f"taking the {cls} sinks a wall nearby - a shortcut opens")))
                return True
    return False


# --------------------------------------------------------------------------------------------- 7. bent bridges
def bent_bridges(P, rnd) -> None:
    n = P.params["bent_bridges"]
    halls = [s for s in P.spaces if not s.solid and s.pattern == "pit" and len(s.pit) >= 9]
    rnd.shuffle(halls)
    made = 0
    for s in halls:
        if made >= n:
            break
        # a few tries: the Z's turns at other places (a pit's own flights of steps take some of its cells)
        if any(_bend(P, rnd, s) for _ in range(12)):
            made += 1
    if made < n:
        P.notes.append(say(f"изогнутых мостов: {made} из {n} - в ямах залов больше места нет",
                           f"bent bridges: {made} of {n} - no more room in the halls' pits"))


def _bend(P, rnd, s) -> bool:
    pit = set(s.pit)
    xs, ys = [c[0] for c in pit], [c[1] for c in pit]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return False
    along_x = (x1 - x0) >= (y1 - y0)
    # a Z: in on one long side, across, sideways, on to the other side (q2dm4's turns)
    if along_x:
        ya, yb = y0 - 1, y1 + 1
        xa = rnd.randint(x0, x0 + (x1 - x0) // 3)
        xb = rnd.randint(x1 - (x1 - x0) // 3, x1)
        ym = rnd.randint(y0, y1)
        path = [(xa, y) for y in range(y0, ym + 1)] + [(x, ym) for x in range(min(xa, xb), max(xa, xb) + 1)] + \
               [(xb, y) for y in range(ym, y1 + 1)]
        ends = [(xa, ya), (xb, yb)]
    else:
        xa_, xb_ = x0 - 1, x1 + 1
        ya_ = rnd.randint(y0, y0 + (y1 - y0) // 3)
        yb_ = rnd.randint(y1 - (y1 - y0) // 3, y1)
        xm = rnd.randint(x0, x1)
        path = [(x, ya_) for x in range(x0, xm + 1)] + [(xm, y) for y in range(min(ya_, yb_), max(ya_, yb_) + 1)] + \
               [(x, yb_) for x in range(xm, x1 + 1)]
        ends = [(xa_, ya_), (xb_, yb_)]
    if not all(c in pit for c in path) or not all(s.floor.get(e) == (s.base, "flat", 0, 0) for e in ends):
        return False
    path = list(dict.fromkeys(path))
    for c in path:
        s.floor[c] = (s.base, "flat", 0, 0)
    s.pit = [c for c in s.pit if c not in set(path)]
    record(P, "bent_bridges", cells=path, space=s.id)
    P.reasons.append(("bridge", say(f"изогнутый мостик через яму зала {s.id}", f"a bent bridge across the pit of hall {s.id}")))
    return True


# --------------------------------------------------------------------------------------------- 8. ladders out of pools
def pool_ladders(P) -> None:
    if not P.params.get("pool_ladders"):
        return
    for pool in P.pools:
        s = P.spaces[pool["space"]]
        cells = set(pool["cells"])
        for c in sorted(cells):
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n in cells or s.floor.get(n) != (s.base, "flat", 0, 0):
                    continue
                x0, y0, x1, y1 = cb(c)
                if dx == 1:
                    lo, hi = (x1 - 8, y0 + 12, pool["bottom"]), (x1, y1 - 12, s.base)
                elif dx == -1:
                    lo, hi = (x0, y0 + 12, pool["bottom"]), (x0 + 8, y1 - 12, s.base)
                elif dy == 1:
                    lo, hi = (x0 + 12, y1 - 8, pool["bottom"]), (x1 - 12, y1, s.base)
                else:
                    lo, hi = (x0 + 12, y0, pool["bottom"]), (x1 - 12, y0 + 8, s.base)
                rec = record(P, "pool_ladders", cells=[c], space=s.id)
                rec["brushes"].append(bx(lo, hi, "ladder", contents=1 | 0x20000000, note="pool ladder"))
                break
            else:
                continue
            break
    if P.pools:
        P.reasons.append(("ladder", say("лесенка из глубокого бассейна на край", "a ladder out of a deep pool onto its rim")))


# --------------------------------------------------------------------------------------------- 9. wall steps
def wall_steps(P, rnd, held, times_of) -> None:
    for n in range(P.params["wall_steps"]):
        if not _wall_steps(P, rnd, held, times_of):
            P.notes.append(say("ступени по стене не построены: нет прямой стены 4 клетки с местом под площадку",
                               "wall steps not built: no straight wall of 4 cells with room for a ledge"))


def _wall_steps(P, rnd, held, times_of) -> bool:
    """Blocks out of a wall rising 32 each to a ledge 128 up with a valuable item (q2dm6's to the chaingun)."""
    plan_mod = pm()
    door_cells = {c for d in P.doors for c in d.cells}
    halls = [s for s in P.spaces if not s.solid and s.kind in ("hall", "room") and s.floor and s.ceil - s.base >= 256
             and plan_mod.layer_of(next(iter(s.floor))) == 0]
    rnd.shuffle(halls)
    for s in halls:
        for c in sorted(s.floor):
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                out_ = (c[0] - d[1], c[1] - d[0])            # the wall's side: rock
                run = [(c[0] + d[0] * i, c[1] + d[1] * i) for i in range(4)]
                walls = [(x[0] - d[1], x[1] - d[0]) for x in run]
                if any(s.floor.get(x) != (s.base, "flat", 0, 0) or x in held or x in door_cells for x in run):
                    continue
                if any(w_ in P.owner or w_ in door_cells for w_ in walls):
                    continue
                ledge = run[-1]
                zl = s.base + 128
                if not take_item(P, None, ledge, zl, "steps up a wall", times_of):
                    continue
                # the ledge: the cell's floor raised (a block by the wall), the steps on the three before it
                s.floor[ledge] = (zl, "flat", 0, 0)
                rec = record(P, "wall_steps", cells=run, space=s.id)
                wx = [(x, w_) for x, w_ in zip(run[:-1], walls[:-1])]
                for i, (x, w_) in enumerate(wx):
                    x0, y0, x1, y1 = cb(x)
                    top = s.base + 32 * (i + 1)
                    # a block 24 deep out of the wall face, 40 along, its top `top`
                    if d[1] == 0:                      # the wall is on the y side
                        fy = y0 if w_[1] < x[1] else y1
                        lo, hi = (x0 + 12, min(fy, fy + (24 if w_[1] < x[1] else -24)), top - 16), \
                                 (x1 - 12, max(fy, fy + (24 if w_[1] < x[1] else -24)), top)
                    else:
                        fx = x0 if w_[0] < x[0] else x1
                        lo, hi = (min(fx, fx + (24 if w_[0] < x[0] else -24)), y0 + 12, top - 16), \
                                 (max(fx, fx + (24 if w_[0] < x[0] else -24)), y1 - 12, top)
                    # a func_wall each (q2dm6's are blocks out of the wall): not the world's decor the «nothing hanging»
                    # row keeps off walls - a step has its use; the survey stands on a func_wall
                    rec["ents"].append(ent({"classname": "func_wall"}, [bx(lo, hi, "trim", contents=1, note="wall step")]))
                    node(P, x, s.base)
                edge(P, run[0], ledge, 2.0)
                held.update(run)
                P.reasons.append(("steps", say("ступени-выступы по стене на площадку с ценным предметом",
                                               "steps out of a wall up to a ledge with a valuable item")))
                return True
    return False


# --------------------------------------------------------------------------------------------- the passes
def before_liquids(P, rnd: random.Random) -> None:
    if not hasattr(P, "pieces"):
        P.pieces = []
    if P.params.get("bent_bridges"):
        bent_bridges(P, rnd)


def after_items(P, rnd: random.Random) -> None:
    q = P.params
    if not hasattr(P, "pieces"):
        P.pieces = []
    if not any_asked(q):
        return
    plan_mod = pm()
    pits = pits_of(P)
    # what the pieces keep off: items, spawns, doorways, movers... - not the pits' own cells (a piece is built over
    # them; each pit takes one piece, `used`)
    held = plan_mod._water_held(P) - {c for pit in pits for c in pit["cells"]}
    times_of = times_fn(P)
    used: set = set()
    trains(P, rnd, held, pits, used)
    stones(P, rnd, held, pits, used)
    rotators(P, rnd, held, pits, used, times_of)
    traps(P, rnd, held, times_of)
    shutters(P, rnd, held)
    pickup_walls(P, rnd, held)
    pool_ladders(P)
    wall_steps(P, rnd, held, times_of)
    try:
        import mapgen_scratch_pieces2 as more
        more.after_items(P, rnd, held, pits, used, times_of)
        import mapgen_scratch_pieces3 as third
        third.after_items(P, rnd, held, pits, used, times_of)
    except ImportError:
        pass
    respace_majors(P, held)
    ease(P, rnd)
    if not OLD_SWEEP:
        # the PO 13.11 (Bugs/4): what still turns into something counts against the skeleton (a cleaner one is taken)
        tb = turning_check(P)
        P.metrics["turning_blocked"] = [f"{k} {n}" for k, n in tb]
    if not OLD_PLAIN_PIECES:
        # the PO 05.11 «голые стены»: a hall or room with a machine in it is no closed box any more
        taken = {r.get("space") for r in P.pieces}
        P.metrics["plain_rooms"] = sum(1 for s in plan_mod.plain_spaces(P) if s.id not in taken)
    P.metrics["pieces"] = sorted({r["kind"] for r in P.pieces})
    built = {k: sum((len(r.get("cells") or [1]) if k == "pendulums" and not OLD_PENDULUM_COUNT else 1)
                    for r in P.pieces if r["kind"] == k) for k in KINDS if q.get(k)}
    # the rotators count by their records; the pool ladders are one switch (on: every deep pool)
    asked = {k: (1 if k == "pool_ladders" else int(q.get(k) or 0)) for k in built}
    P.metrics["pieces_count"] = built
    P.metrics["pieces_missing"] = sum(max(0, asked[k] - min(built[k], asked[k])) for k in built
                                      if not (k == "pool_ladders" and not P.pools))


def ease(P, rnd) -> None:
    """The PO 13.11: «как реальная физика работает» - in the game itself (no mod: «мы делаем не мод, а карты») a door
    that moves straight starts and stops by its accel and decel (g_func.c Think_AccelMove); a turn cannot. Every straight
    mover of the pieces (a piston, a stone, a wall, a shutter, a pillar, a collar, a trap's lava) gets them - a heavy one
    slower to start - unless the form asks «even»."""
    if P.params.get("piece_motion") == "even":
        return
    for r in getattr(P, "pieces", []):
        for e in r["ents"]:
            k = e["keys"]
            if k.get("classname") not in ("func_door", "func_water") or "accel" in k:
                continue
            try:
                spd = float(k.get("speed") or 100)
            except ValueError:
                continue
            # never the speed itself: the game moves a door at an even speed when its accel and decel equal its speed
            f = rnd.choice((0.6, 0.8, 1.3)) if r["kind"] in ("pistons", "waves", "pickup_walls", "stones") else rnd.choice((1.3, 1.6, 2.0))
            k["accel"] = str(round(spd * f))
            k["decel"] = str(round(spd * f))


def respace_majors(P, held) -> None:
    """The PO 12.11's rule (majors apart) kept after the pieces. The showcase of 13.11: the rides, stones and bridges,
    built after the items, gave the walk ways the items' placement had not seen - three pairs of guns a second or so
    apart on the finished map. A gun of a pair found near on the walk with every piece (with the placement's slack:
    the finished map walks quicker) moves to the nearest place, from where it was, that keeps it apart from every
    major - no piece holds it, no mechanic placed it, it is no prize."""
    plan_mod = pm()
    if plan_mod.OLD_MAJORS:
        return
    nodes, edges = plan_mod.plan_graph(P)
    cache: dict = {}

    def tim(c):
        if c not in cache:
            cache[c] = plan_mod.dijkstra(edges, c)
        return cache[c]
    doorish = {c for c in nodes if P.owner.get(c) is None}
    moved = 0

    def movable(k):
        cls, _c, _z, note = P.items[k]
        return (cls.startswith("weapon_") and k not in P.prize_kind and "guarded by" not in note
                and not any(f in note for f in FIXED_NOTES))

    def move(k) -> bool:
        cls, c0, z0, note = P.items[k]
        taken = {c for (_cls, c, _z, _n) in P.items} | {c for (c, _z, _a) in P.spawns}
        from_c0 = tim(c0)

        def free(c):
            f = nodes.get(c)
            if f is None or f[1] != "flat" or P.owner.get(c) is None or c in P.no_items or c in held or c not in from_c0:
                return False
            if any((c[0] + dx, c[1] + dy) in taken for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                return False
            return not any((c[0] + dx, c[1] + dy) in doorish for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        cands = sorted((c for c in nodes if free(c)), key=lambda c: (from_c0[c], c))
        to = next((c for c in cands if plan_mod.majors_apart(P, cls, c, nodes[c][0], tim, skip=k)), None)
        if to is None:
            return False
        P.items[k] = (cls, to, nodes[to][0], (f"{note}; " if note else "") + "moved apart after the pieces")
        return True
    for _round in range(8):
        majors = [(k, cls, c, z) for k, (cls, c, z, _n) in enumerate(P.items) if plan_mod.major_kind(cls)]
        near = []
        for i, (ka, a, ca, za) in enumerate(majors):
            for kb, b, cb_, zb in majors[i + 1:]:
                if ca == cb_:
                    continue
                t_need, d_need = plan_mod.majors_need(a, b, P.params)
                d = math.dist(plan_mod._item_at(ca, za), plan_mod._item_at(cb_, zb))
                t = min(tim(ca).get(cb_, 99.0), tim(cb_).get(ca, 99.0))
                if plan_mod.majors_close(d, t, t_need * plan_mod.MAJORS_PLAN_SLACK, d_need):
                    near.append((ka, kb))
        # each near pair: one of its guns moved, if either may be and has a place; the next round sees the new places
        if not any(move(k) for pair in near for k in pair if movable(k)):
            break
        moved += 1
    P.metrics["majors_moved_after_pieces"] = moved


def items_targets(P) -> dict:
    """The items that fire a piece when taken: cell -> target name."""
    out = {}
    for r in getattr(P, "pieces", []):
        it = r.get("item_target")
        if it:
            out[tuple(it[0])] = it[1]
    return out


# --------------------------------------------------------------------------------------------- the world
def world(P, pal: dict, brushes: list, ents: list) -> None:
    """The pieces' brushes (into the world) and entities, their roles in the style's textures."""
    from mapgen_scratch_build import Entity, box, C_DETAIL, C_SOLID, C_WINDOW, Surf, S_FLOWING
    import mapgen_scratch_world as world_mod
    from mapgen_scratch_style import TRIGGER
    tint = world_mod.TINTS[(P.seed or 0) % len(world_mod.TINTS)]
    glass = Surf(tint[0], tint[1], 0)
    lamp = pal["lamp"][0]

    def surf(role):
        if role == "glass":
            return {"default": glass}
        if role == "trigger":
            return {"default": TRIGGER}
        if role in ("lava", "slime", "water"):
            return {"default": pal[role][0]}
        if role == "plate":
            return {"default": world_mod.detail(pal, 2), "+z": pal["tread"][0] if pal.get("tread") else pal["floor"][0]}
        if role == "tread":
            return {"default": world_mod.detail(pal, 0), "+z": pal["tread"][0] if pal.get("tread") else pal["floor"][0]}
        if role == "button":
            return {"default": world_mod.detail(pal, 2), "+x": lamp, "-x": lamp, "+y": lamp, "-y": lamp}
        if role == "plate_mark":
            return {"default": lamp}
        if role == "wall":
            return {"default": pal["wall"][0]}
        if role == "ladder":
            return {"default": pal["trim"][0]}
        if role == "drum":
            return {"default": world_mod.detail(pal, 1)}
        if role == "current":
            import dataclasses
            fl = pal["floor"][0]
            return {"default": world_mod.detail(pal, 2), "+z": dataclasses.replace(fl, flags=fl.flags | S_FLOWING)}
        return {"default": pal["trim"][0]}

    def make(b):
        if "octagon" in b:
            return octagon(b)
        if "hull" in b:
            return hull(b)
        if "prism" in b:
            return prism_brush(b)
        contents = b["contents"]
        if b["role"] == "glass":
            contents = C_WINDOW | 0x10000000
        elif b["role"] == "trigger":
            contents = 0
        elif b["role"] in ("trim", "plate", "tread", "button", "plate_mark") and not contents:
            contents = C_SOLID | C_DETAIL
        return box(tuple(b["lo"]), tuple(b["hi"]), surf(b["role"]), contents=contents, note=b["note"])

    def octagon(b):
        cx, cy, cz, r, along, half = b["octagon"]
        s_ = surf("drum")["default"]
        planes = []
        for i in range(8):
            a = math.radians(22.5 + 45 * i)
            nu, nz = math.cos(a), math.sin(a)
            # a point on the face and two along it (one along the axis)
            pu, pz = r * nu, r * nz
            tu, tz = -nz, nu
            if along == "x":
                p0 = (cx, cy + pu, cz + pz)
                pts = (p0, (cx + 16, cy + pu, cz + pz), (cx, cy + pu + 16 * tu, cz + pz + 16 * tz))
                n_ = (0, nu, nz)
            else:
                p0 = (cx + pu, cy, cz + pz)
                pts = (p0, (cx + pu, cy + 16, cz + pz), (cx + pu + 16 * tu, cy, cz + pz + 16 * tz))
                n_ = (nu, 0, nz)
            planes.append((pts, n_))
        if along == "x":
            planes.append((((cx - half, cy, cz), (cx - half, cy + 16, cz), (cx - half, cy, cz + 16)), (-1, 0, 0)))
            planes.append((((cx + half, cy, cz), (cx + half, cy + 16, cz), (cx + half, cy, cz + 16)), (1, 0, 0)))
        else:
            planes.append((((cx, cy - half, cz), (cx + 16, cy - half, cz), (cx, cy - half, cz + 16)), (0, -1, 0)))
            planes.append((((cx, cy + half, cz), (cx + 16, cy + half, cz), (cx, cy + half, cz + 16)), (0, 1, 0)))
        return world_mod.convex(planes, s_, C_SOLID, note="drum")

    def prism_brush(b):
        """A convex polygon across an axis extruded along it (mapgen_scratch_forms.prism): a side plane on each edge,
        two caps. A liquid's role makes a liquid brush (a trap's lava, a geyser's), glass a window."""
        pr = b["prism"]
        ax, poly, lo, hi = pr["axis"], [tuple(p) for p in pr["poly"]], float(pr["lo"]), float(pr["hi"])

        def P3(a_, b_, w):
            return (w, a_, b_) if ax == "x" else (a_, w, b_) if ax == "y" else (a_, b_, w)
        k = {"x": 0, "y": 1, "z": 2}[ax]
        ca = sum(p[0] for p in poly) / len(poly)
        cb = sum(p[1] for p in poly) / len(poly)
        c3 = P3(ca, cb, (lo + hi) / 2)
        planes = []
        for i in range(len(poly)):
            a_, b_ = poly[i], poly[(i + 1) % len(poly)]
            p0, p1, p2 = P3(a_[0], a_[1], lo), P3(b_[0], b_[1], lo), P3(a_[0], a_[1], hi)
            u = [p1[j] - p0[j] for j in range(3)]
            v = [p2[j] - p0[j] for j in range(3)]
            n_ = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            ln = math.sqrt(sum(x * x for x in n_)) or 1.0
            n_ = [x / ln for x in n_]
            if sum(n_[j] * (p0[j] - c3[j]) for j in range(3)) < 0:
                n_ = [-x for x in n_]
            planes.append(((p0, p1, p2), tuple(n_)))
        lo_n = [0, 0, 0]
        lo_n[k] = -1
        hi_n = [0, 0, 0]
        hi_n[k] = 1
        planes.append(((P3(poly[0][0], poly[0][1], lo), P3(poly[1][0], poly[1][1], lo), P3(poly[2][0], poly[2][1], lo)), tuple(lo_n)))
        planes.append(((P3(poly[0][0], poly[0][1], hi), P3(poly[1][0], poly[1][1], hi), P3(poly[2][0], poly[2][1], hi)), tuple(hi_n)))
        role = b.get("role", "trim")
        contents = {"lava": 8, "slime": 16, "water": 32}.get(role) or (C_WINDOW | 0x10000000 if role == "glass" else C_SOLID)
        return world_mod.convex(planes, surf(role)["default"], contents, note=b.get("note", "prism"))

    def hull(b):
        """A hexahedron from its eight corners (four at each end, in order round the slab)."""
        pts = [tuple(v) for v in b["hull"]]
        c0 = [sum(p[k] for p in pts) / 8 for k in range(3)]
        quads = [pts[0:4], pts[4:8]] + [[pts[i], pts[(i + 1) % 4], pts[4 + (i + 1) % 4], pts[4 + i]] for i in range(4)]
        planes = []
        for qd in quads:
            a_, b_, c_ = qd[0], qd[1], qd[2]
            u = [b_[k] - a_[k] for k in range(3)]
            v = [c_[k] - a_[k] for k in range(3)]
            n_ = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            ln = math.sqrt(sum(x * x for x in n_)) or 1.0
            n_ = [x / ln for x in n_]
            if sum(n_[k] * (a_[k] - c0[k]) for k in range(3)) < 0:
                n_ = [-x for x in n_]
            planes.append(((a_, b_, c_), tuple(n_)))
        return world_mod.convex(planes, surf(b["role"])["default"], C_SOLID, note=b.get("note", "hull"))

    for r in getattr(P, "pieces", []):
        for b in r["brushes"]:
            brushes.append(make(b))
        for e in r["ents"]:
            ents.append(Entity(dict(e["keys"]), [make(b) for b in shown_parts(e["brushes"])]))
