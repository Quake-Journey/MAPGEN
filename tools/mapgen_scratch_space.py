r"""Brief 25 A1 (the PO 06.11: «космическая карта с кучей мест для падения, воздушная, с джампадами и отдельными местами в
воздухе, куда можно добраться через jump pads … хочу, чтобы новые карты тоже делались в подобных стилях через отдельные
параметры»): the shape «space» of a map from scratch - islands in the void.

The measure it is made to (`tools/mapgen_space_survey.py` on q2_q3dm17, research_opus_2026-11-06_space_maps.json): no
rooms and no walls - 93 % of the floor open; half the floor's outline a deadly edge; a dozen islands at 0..1300 (one or
two big decks, mid platforms, small perches); jump pads across the air as the main way up (330-1670 units across,
200-810 up), the power items on perches only a pad reaches, a few teleporters, drops onto lower islands; the whole map in a
box of sky over a kill slab (the builder's part: mapgen_scratch_world.build_space).

Nothing of q2_q3dm17 is copied: every island, height, bridge, pad and item is drawn here from the run's number.

The plan it makes is the generator's own Plan: each walk-joined group of islands (an island, or islands joined by a
bridge) one Space of kind «island» with its floor cells, `P.pads` / `P.teleports` as for rooms, the drops onto a lower
island as `P.air_edges` (the walk graph takes them), `P.railings` for the builder, the items, spawns, pedestals and
lights placed here - the rooms' furniture steps (nooks, windows, round shapes, columns) do not apply to islands.
"""
from __future__ import annotations

import math
import random

import mapgen_scratch_plan as pm

CELL = pm.CELL
REACH = {"short": 512, "medium": 1024, "long": 1700}      # the farthest a pad throws, across
RAIL_H = 32                                               # a railing's height over the floor
SLAB = 64                                                 # an island's thickness under its floor
GRAVITY = 800.0

# what «space» means when the PO did not say: rooms' parameters left aside, the space's own at q2_q3dm17's measure
SPACE_DEFAULTS = {
    "openness": [0.05, 0.10, 0.85], "sky": 1.0, "sun": "no", "tone": "cold", "windows": 0, "doors": 0, "ladders": 0,
    "lifts": 0, "water": 0.0, "lava": 0.0, "slime": 0.0, "pits": 0, "decor": "none", "round": "", "ramps": 0,
    "stairs": 0, "drops": 0, "powerup_access": "easy", "items_at_height": 0.85,
    "pad_only": 2, "edges": "open", "height_spread": 800, "pad_reach": "medium", "bridges": "some",
}
SPACE_MECHANICS = ["small_health", "spawn_pressure"]
# 3.57 (Fable's review of 3.56; the PO's mg_new_66267 asked water 20 % and «many» round shapes and got neither): what an
# open space never builds - the form no longer offers them, and a request that still asks (an older preset) is told
SPACE_FORCED = ("water", "lava", "slime", "pits", "round", "windows", "doors", "lifts", "ladders", "ramps", "stairs", "decor")
SPACE_FORCED_WORDS = {"water": ("вода", "water"), "lava": ("лава", "lava"), "slime": ("кислота", "slime"),
                      "pits": ("смертельные ямы", "deadly pits"), "round": ("скругления", "round shapes"),
                      "windows": ("окна", "windows"), "doors": ("двери", "doors"), "lifts": ("лифты", "lifts"),
                      "ladders": ("лестницы-стремянки", "ladders"), "ramps": ("пандусы", "ramps"),
                      "stairs": ("лестницы", "flights of steps"), "decor": ("украшения на стенах", "wall decorations")}


def space_defaults(q: dict, params: dict) -> None:
    """The space's own defaults into the resolved request (before the rooms' generic ones fill what is left)."""
    for k, v in SPACE_DEFAULTS.items():
        if params.get(k) is None:
            q[k] = list(v) if isinstance(v, list) else v
    if params.get("islands") is None:
        q["islands"] = 8 if q["players"] <= 2 else 10 if q["players"] <= 4 else 12
    if params.get("teleporters") is None:
        q["teleporters"] = 0 if q["players"] <= 2 else 1
    if params.get("mechanics") is None:
        q["mechanics"] = list(SPACE_MECHANICS)
    q["islands"] = max(4, min(20, int(q["islands"])))
    q["pad_only"] = max(0, min(6, int(q["pad_only"])))
    q["height_spread"] = max(256, min(1600, int(q["height_spread"])))
    if q.get("edges") not in ("open", "some", "railings"):
        q["edges"] = "open"
    if q.get("pad_reach") not in REACH:
        q["pad_reach"] = "medium"
    if q.get("bridges") not in ("none", "some", "many"):
        q["bridges"] = "some"
    asked = [k for k in SPACE_FORCED if q.get(k) not in (None, SPACE_DEFAULTS[k], 0, 0.0, "", "none")]
    for k in SPACE_FORCED:
        q[k] = SPACE_DEFAULTS[k]
    if asked:
        ru = ", ".join(SPACE_FORCED_WORDS[k][0] for k in asked)
        en = ", ".join(SPACE_FORCED_WORDS[k][1] for k in asked)
        q["refused"] = list(q.get("refused") or []) + [
            f"{ru}: в открытом космосе не строятся - острова висят в пустоте ¦ {en}: not built in open space - the islands hang in the void"]


# --------------------------------------------------------------------------------------------- islands
class Isle:
    def __init__(self, kind: str, rect: pm.Rect, z: int):
        self.kind = kind          # deck | mid | perch
        self.rect = rect
        self.z = z
        self.group = -1

    def cells(self):
        return list(self.rect.cells())


def gap(a: pm.Rect, b: pm.Rect) -> int:
    """Void cells between two rectangles (Chebyshev): 0 when they touch or overlap."""
    dx = max(b.x0 - a.x1, a.x0 - b.x1, 0)
    dy = max(b.y0 - a.y1, a.y0 - b.y1, 0)
    return max(dx, dy)


def round32(v: float) -> int:
    return int(round(v / 32.0)) * 32


def make_isles(P: pm.Plan, rnd: random.Random) -> list[Isle] | None:
    """The islands: sizes from the floor asked, placed with void between, heights over the spread asked."""
    q = P.params
    floor_cells = q["floor_area"] * 1e6 / (CELL * CELL)
    bridges_want = {"none": 0, "some": max(1, q["islands"] // 5), "many": max(2, q["islands"] // 3)}[q["bridges"]]
    n_groups = q["islands"]
    n_plat = n_groups + bridges_want
    decks = 2 if q["players"] >= 8 else 1
    perches = max(q["pad_only"], int(round(n_plat * 0.25)), 2)
    mids = max(1, n_plat - decks - perches)
    perch_cells = [rnd.choice((9, 12, 12, 16)) for _ in range(perches)]
    rest = max(60.0, floor_cells - sum(perch_cells))
    deck_total = rest * rnd.uniform(0.48, 0.6)
    mid_total = rest - deck_total
    w_mid = [rnd.uniform(0.6, 1.4) for _ in range(mids)]
    mid_cells = [max(16, int(mid_total * w / sum(w_mid))) for w in w_mid]
    deck_cells = [int(deck_total / decks * rnd.uniform(0.85, 1.15)) for _ in range(decks)]
    side = math.sqrt(floor_cells * 2.6)
    aw, ah = rnd.uniform(0.9, 1.15), rnd.uniform(0.9, 1.15)
    spread = q["height_spread"]
    # the farthest void to the nearest island a pad of the reach asked still crosses (two cells in at each end)
    far = max(3, min(9, int(REACH[q["pad_reach"]] // CELL) - 4))

    def dims(area: int, lo: float = 1.0, hi: float = 1.9):
        a = rnd.uniform(lo, hi)
        w = max(3, int(round(math.sqrt(area * a))))
        h = max(3, int(round(area / w)))
        return (w, h) if rnd.random() < 0.5 else (h, w)

    isles: list[Isle] = []
    W = H = 0

    def place(kind: str, area: int, centre: bool) -> bool:
        w, h = dims(area, 1.0, 1.6 if kind == "deck" else 1.9)
        for k_ in range(600):
            if centre:
                x0 = int(W / 2 - w / 2 + rnd.uniform(-0.18, 0.18) * W)
                y0 = int(H / 2 - h / 2 + rnd.uniform(-0.18, 0.18) * H)
            else:
                x0 = rnd.randint(1, max(1, W - w - 1))
                y0 = rnd.randint(1, max(1, H - h - 1))
            r = pm.Rect(x0, y0, x0 + w, y0 + h)
            if r.x0 < 1 or r.y0 < 1 or r.x1 > W - 1 or r.y1 > H - 1:
                continue
            gaps = [gap(r, o.rect) for o in isles]
            # close first (2..3 cells of void to the nearest: a jump down or a short pad between), farther when it will not go
            if gaps and (min(gaps) < 2 or min(gaps) > (3 if k_ < 400 else far)):
                continue
            isles.append(Isle(kind, r, 0))
            return True
        return False

    # the footprint grows a tenth a try until every island has its place (void of 3..9 cells to its nearest)
    for grow in range(8):
        W = max(20, int(side * aw * (1 + 0.1 * grow)))
        H = max(20, int(side * ah * (1 + 0.1 * grow)))
        isles.clear()
        ok = all(place("deck", a, True) for a in deck_cells)             and all(place("mid", a, False) for a in sorted(mid_cells, reverse=True))             and all(place("perch", a, False) for a in perch_cells)
        if ok:
            break
    else:
        return None
    # heights: the decks low (a second deck 40 % up), the mids spread under 70 %, the perches high
    for k, it in enumerate(i for i in isles if i.kind == "deck"):
        it.z = 0 if k == 0 else round32(spread * rnd.uniform(0.35, 0.5))
    for it in isles:
        if it.kind == "mid":
            it.z = round32(rnd.uniform(96, spread * 0.7))
        elif it.kind == "perch":
            it.z = round32(rnd.uniform(spread * 0.55, spread))
    # steps down between neighbours (q2_q3dm17: two islands of twelve entered only by dropping, most by a drop and a pad):
    # a mid three cells of void from a higher island sits 352..448 under it - a running jump off that edge lands on it
    # (300 a second for 1.4 s: 350 across; three cells and one in are 320)
    # steps down between neighbours, as the people's measure walks them (mapgen_map_survey's running gap jump: straight
    # on over up to 256 units of no floor, landing 20..160 lower): a mid three cells of void from a higher island sits
    # 64..160 under it - one way down; islands that close never at one height (the jump would join them both ways)
    mids = sorted((it for it in isles if it.kind == "mid"), key=lambda it: it.z)
    fixed = set()
    for m in mids:
        near = [o for o in isles if o is not m and o.kind != "deck" and gap(o.rect, m.rect) in (2, 3)]
        if not near or any(64 <= o.z - m.z <= 160 for o in near):
            continue
        perch = [o for o in near if o.kind == "perch" and o.z - 160 >= 32]
        free_mid = [o for o in near if o.kind == "mid" and id(o) not in fixed and m.z + 160 <= spread]
        if perch:
            m.z = max(perch, key=lambda o: o.z).z - rnd.choice((64, 96, 128, 160))
        elif free_mid:
            n = rnd.choice(free_mid)
            n.z = m.z + rnd.choice((64, 96, 128, 160))
            fixed.add(id(n))
        fixed.add(id(m))
    for i, a in enumerate(isles):
        for b in isles[i + 1:]:
            if gap(a.rect, b.rect) <= 3 and abs(a.z - b.z) <= 20:
                (b if b.kind != "deck" else a).z += 32
    P.W, P.H = W, H
    P.metrics["bridges_asked"] = bridges_want
    return isles


def bridge(P: pm.Plan, isles: list[Isle], rnd: random.Random) -> list[tuple[int, int, list]]:
    """Walkways between islands that face each other across a short gap (not the perches: they stay apart). A bridged
    pair takes one height (the lower one's), the walkway 2 cells wide at it."""
    want = P.metrics.get("bridges_asked", 0)
    out = []
    used = set()
    pairs = []
    for i, a in enumerate(isles):
        for j, b in enumerate(isles):
            if j <= i or "perch" in (a.kind, b.kind):
                continue
            ra, rb = a.rect, b.rect
            g = gap(ra, rb)
            if not 3 <= g <= 6:
                continue
            ox = min(ra.x1, rb.x1) - max(ra.x0, rb.x0)
            oy = min(ra.y1, rb.y1) - max(ra.y0, rb.y0)
            if ox >= 2 and (rb.y0 >= ra.y1 or ra.y0 >= rb.y1):
                pairs.append((g + rnd.random(), i, j, "y", ox))
            elif oy >= 2 and (rb.x0 >= ra.x1 or ra.x0 >= rb.x1):
                pairs.append((g + rnd.random(), i, j, "x", oy))
    pairs.sort()
    for _g, i, j, axis, _ov in pairs:
        if len(out) >= want or i in used or j in used:
            continue
        a, b = isles[i], isles[j]
        if a.kind == "deck" and b.kind == "deck":
            continue
        # the lower one's height for both (a deck keeps its own)
        z = a.z if a.kind == "deck" else b.z if b.kind == "deck" else min(a.z, b.z)
        a.z = b.z = z
        ra, rb = a.rect, b.rect
        cells = []
        if axis == "y":
            lo, hi = max(ra.x0, rb.x0), min(ra.x1, rb.x1)
            x = rnd.randint(lo, hi - 2)
            y0, y1 = (ra.y1, rb.y0) if rb.y0 >= ra.y1 else (rb.y1, ra.y0)
            cells = [(xx, y) for y in range(y0, y1) for xx in (x, x + 1)]
        else:
            lo, hi = max(ra.y0, rb.y0), min(ra.y1, rb.y1)
            y = rnd.randint(lo, hi - 2)
            x0, x1 = (ra.x1, rb.x0) if rb.x0 >= ra.x1 else (rb.x1, ra.x0)
            cells = [(x, yy) for x in range(x0, x1) for yy in (y, y + 1)]
        out.append((i, j, cells))
        used.update({i, j})
    return out


# --------------------------------------------------------------------------------------------- the plan's spaces
def groups_of(P: pm.Plan, isles: list[Isle], bridges: list) -> None:
    """Each walk-joined group (an island, or islands joined by a bridge) one Space of kind «island»."""
    parent = list(range(len(isles)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, j, _c in bridges:
        parent[find(i)] = find(j)
    roots = sorted({find(i) for i in range(len(isles))})
    gid = {r: k for k, r in enumerate(roots)}
    top = max(it.z for it in isles) + 1024
    P.spaces = []
    for r in roots:
        members = [k for k in range(len(isles)) if find(k) == r]
        floor = {}
        for k in members:
            isles[k].group = gid[r]
            for c in isles[k].cells():
                floor[c] = (isles[k].z, "flat", 0, 0)
        for i, j, cells in bridges:
            if find(i) == r:
                for c in cells:
                    floor[c] = (isles[i].z, "flat", 0, 0)
        xs = [c[0] for c in floor]
        ys = [c[1] for c in floor]
        kinds = {isles[k].kind for k in members}
        s = pm.Space(gid[r], "island", pm.Rect(min(xs), min(ys), max(xs) + 1, max(ys) + 1),
                     base=min(f[0] for f in floor.values()), sky=True, ceil=top)
        s.floor = floor
        s.pattern = "deck" if "deck" in kinds else "mid" if "mid" in kinds else "perch"
        P.spaces.append(s)
        for c in floor:
            P.owner[c] = s.id
    P.metrics["platforms"] = len(isles)
    P.metrics["bridges"] = len(bridges)


def floor_z(P: pm.Plan, c) -> int | None:
    o = P.owner.get(c)
    return None if o is None else P.spaces[o].floor[c][0]


def inner(P: pm.Plan, c, r: int) -> bool:
    """The cell with floor of its own height all round to r cells."""
    z = floor_z(P, c)
    if z is None:
        return False
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if floor_z(P, (c[0] + dx, c[1] + dy)) != z:
                return False
    return True


def edge_cells(P: pm.Plan, s: pm.Space) -> list:
    return [c for c in s.floor if any((c[0] + dx, c[1] + dy) not in s.floor for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]


# --------------------------------------------------------------------------------------------- the ways between
def flight_clear(P: pm.Plan, a, t, vx: float, vy: float, vz: float, T: float, top: int, lift: float = 0.0) -> bool:
    """A pad's flight from cell a: under the sky; over any other island the body passes above its railing or under its
    slab; over its own target the feet stay above the floor until, coming down, they reach it - the landing (the
    people's measure lands a flight on the first floor point it meets descending, within 24)."""
    za = floor_z(P, a)
    x0, y0, z0 = (a[0] + 0.5) * CELL, (a[1] + 0.5) * CELL, za + 24.0 + pm.PAD_TOP + lift   # on the pad's plinth (brief 26)
    tgt = P.owner.get(t)
    src = P.owner.get(a)
    tt, dt = 0.0, 0.02
    while tt < T + 0.6:
        tt += dt
        x, y = x0 + vx * tt, y0 + vy * tt
        z = z0 + vz * tt - 0.5 * GRAVITY * tt * tt
        down = vz - GRAVITY * tt < 0
        feet, head = z - 24, z + 32
        if head > top - 64:
            return False
        under = P.owner.get((int(x // CELL), int(y // CELL)))
        if down and under == tgt:
            fz = P.spaces[tgt].floor[(int(x // CELL), int(y // CELL))][0]
            if feet <= fz + 8:
                return feet >= fz - 8 and tt > 0.3
        for ox in (-16, 16):
            for oy in (-16, 16):
                cc = (int((x + ox) // CELL), int((y + oy) // CELL))
                o = P.owner.get(cc)
                if o is None:
                    continue
                fz = P.spaces[o].floor[cc][0]
                if o == src and tt < 0.3 and feet >= fz - 1:
                    continue
                if o == tgt:
                    if feet < fz - 1:
                        return False          # through the target's edge, not onto it
                    continue
                if feet < fz + RAIL_H + 8 and head > fz - SLAB:
                    return False
    return False


def pad_between(P: pm.Plan, a, t, reach: float, top: int):
    """(T, speed/10, pitch, yaw) of a pad on cell a landing on cell t, or None: across 128..reach, a flight 0.7..2.2 s
    high enough to clear the edges, at most 1500 units a second (q2_q3dm17's pads: 730..1350)."""
    za, zt = floor_z(P, a), floor_z(P, t)
    dxu, dyu = (t[0] - a[0]) * CELL, (t[1] - a[1]) * CELL
    D = math.hypot(dxu, dyu)
    if D < 128 or D > reach:
        return None
    H = zt - za - pm.PAD_TOP          # from the take-off on the pad's plinth (brief 26)
    for T in (0.9, 1.0, 1.1, 1.2, 0.8, 1.3, 1.4, 1.6, 0.7, 1.8, 2.0, 2.2):
        vz = (H + 0.5 * GRAVITY * T * T) / T
        vh = D / T
        sp = math.hypot(vh, vz)
        if sp > 1500 or vz <= 0:
            continue
        apex = za + vz * vz / (2 * GRAVITY)
        if apex < max(za, zt) + 96:
            continue
        steep = math.degrees(math.atan2(vz, max(vh, 1e-6))) >= pm.PAD_STEEP
        if flight_clear(P, a, t, dxu / D * vh, dyu / D * vh, vz, T, top) and (
                steep or flight_clear(P, a, t, dxu / D * vh, dyu / D * vh, vz, T, top, pm.PAD_WEDGE_LIFT)):
            return (T, round(sp / 10.0, 1), round(math.degrees(math.atan2(vz, vh)), 2), round(math.degrees(math.atan2(dyu, dxu)), 2))
    return None


def drop_time(dz: float) -> float:
    """A running jump off an edge falling dz: its time in the air (jump 270 up)."""
    return (270.0 + math.sqrt(270.0 ** 2 + 2 * GRAVITY * dz)) / GRAVITY


def find_drops(P: pm.Plan, pad_only: set) -> list:
    """Running jumps off an edge onto a lower island, as the people's measure takes them (mapgen_map_survey's gap
    jump): straight on from an edge cell along one of eight directions over void cells only, up to 256 units, onto a
    cell of another group 32..160 lower; one per pair of groups (the shortest); never onto a pad-only perch."""
    found = {}
    for s in P.spaces:
        for e in edge_cells(P, s):
            ze = s.floor[e][0]
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                step = math.hypot(dx, dy) * CELL
                for k in range(2, 6):
                    if k * step > 256 + 16:
                        break
                    c = (e[0] + dx * k, e[1] + dy * k)
                    o = P.owner.get(c)
                    if o is None:
                        continue
                    if o == s.id or o in pad_only:
                        break
                    if not all(P.owner.get((e[0] + dx * j, e[1] + dy * j)) is None for j in range(1, k)):
                        break
                    dz = ze - P.spaces[o].floor[c][0]
                    if 32 <= dz <= 160:
                        t = k * step / 300.0 + math.sqrt(2 * dz / GRAVITY)
                        if (s.id, o) not in found or t < found[(s.id, o)][2]:
                            found[(s.id, o)] = (e, c, round(t, 2), s.id, o)
                    break
    return list(found.values())


def link(P: pm.Plan, isles: list[Isle], rnd: random.Random) -> bool:
    """Every group reached from the decks and every group back to them: drops where they fall, pads for the rest
    (perches by pads only, as many as asked), teleporters back from far groups; then pads for loops."""
    q = P.params
    reach = REACH[q["pad_reach"]]
    top = max(s.ceil for s in P.spaces)
    n = len(P.spaces)
    decks = {s.id for s in P.spaces if s.pattern == "deck"}
    # every group reached from ONE deck and back to it: the whole map one strongly joined graph, whichever island a
    # player starts on (8 players, 06.11: rooted at both decks, the second deck's side was out of the spawns' reach)
    root = {min(decks, key=lambda d: P.spaces[d].base)} if decks else {0}
    perches = sorted((s for s in P.spaces if s.pattern == "perch"), key=lambda s: -s.base)
    pad_only = {s.id for s in perches[:q["pad_only"]]}
    drops = find_drops(P, pad_only)
    # one drop per pair of groups (the shortest), the rest are the same way
    seen = {}
    for e, c, t, a, b in drops:
        if (a, b) not in seen or t < seen[(a, b)][2]:
            seen[(a, b)] = (e, c, t, a, b)
    P.air_edges = [(e, c, t) for (e, c, t, a, b) in seen.values()]
    adj = {i: set() for i in range(n)}
    for (a, b) in seen:
        adj[a].add(b)

    def reached(src: set, rev: bool = False) -> set:
        g = adj if not rev else {i: {a for a in range(n) if i in adj[a]} for i in range(n)}
        out_, stack = set(src), list(src)
        while stack:
            v = stack.pop()
            for w in g[v]:
                if w not in out_:
                    out_.add(w)
                    stack.append(w)
        return out_

    used_cells = set()

    def add_pad(a_id: int, b_id: int) -> bool:
        sa, sb = P.spaces[a_id], P.spaces[b_id]
        srcs = [c for c in sa.floor if inner(P, c, 1) and c not in used_cells]             or [c for c in sa.floor if inner(P, c, 0) and c not in used_cells]
        # a landing well inside its island: two cells from the void where it is that big, else one, else any
        tgts = []
        for r_ in (2, 1, 0):
            tgts = [c for c in sb.floor if inner(P, c, r_) and c not in used_cells]
            if tgts:
                break
        if not srcs or not tgts:
            return False
        # the landings nearest the island it flies from (still two cells in), the middle ones among them first - a
        # big deck's middle is out of a short pad's reach (06.11: every «short» plan failed)
        cx = sum(c[0] for c in sb.floor) / len(sb.floor)
        cy = sum(c[1] for c in sb.floor) / len(sb.floor)
        ax = sum(c[0] for c in sa.floor) / len(sa.floor)
        ay = sum(c[1] for c in sa.floor) / len(sa.floor)
        tgts.sort(key=lambda c: math.hypot(c[0] - ax, c[1] - ay) + 0.3 * math.hypot(c[0] - cx, c[1] - cy))
        tgts = tgts[:8]
        srcs.sort(key=lambda c: min((c[0] - t[0]) ** 2 + (c[1] - t[1]) ** 2 for t in tgts))
        # brief 34: the take-offs on an island apart, none beside a teleporter or a spawn
        srcs = [c for c in srcs if pm.pad_spot_ok(P, c, floor_z(P, c))]
        for a in srcs[:30]:
            for t in tgts:
                f = pad_between(P, a, t, reach, top)
                if f:
                    T, speed, pitch, yaw = f
                    P.pads.append((a, t, T + 0.1, speed, pitch, yaw, floor_z(P, a)))
                    P.pad_why[(a, t)] = "perch" if b_id in pad_only else "link"
                    used_cells.update({a, t})
                    P.no_items.update({a, t})
                    adj[a_id].add(b_id)
                    return True
        return False

    def pad_cost(a_id, b_id):
        sa, sb = P.spaces[a_id], P.spaces[b_id]
        ca = ((sa.rect.x0 + sa.rect.x1) / 2, (sa.rect.y0 + sa.rect.y1) / 2)
        cb = ((sb.rect.x0 + sb.rect.x1) / 2, (sb.rect.y0 + sb.rect.y1) / 2)
        return math.hypot(ca[0] - cb[0], ca[1] - cb[1]) + max(0, sa.base - sb.base) / 64.0 + rnd.random()

    # 1. every group reached from the decks
    for _ in range(4 * n):
        r = reached(root)
        if len(r) == n:
            break
        missing = sorted((i for i in range(n) if i not in r), key=lambda i: P.spaces[i].base)
        done = False
        for b in missing:
            for a in sorted(r, key=lambda a: pad_cost(a, b)):
                if add_pad(a, b):
                    done = True
                    break
            if done:
                break
        if not done:
            P.failed = f"space: islands no pad reaches ({len(missing)})"
            return False
    # 2. every group back to the decks: a pad to a group that returns (lower first), else a teleporter
    tele_left = int(q.get("teleporters") or 0)
    for _ in range(4 * n):
        back = reached(root, rev=True)
        if len(back) == n:
            break
        stuck = sorted((i for i in range(n) if i not in back), key=lambda i: -P.spaces[i].base)
        done = False
        for a in stuck:
            for b in sorted(back, key=lambda b: (P.spaces[b].base > P.spaces[a].base, pad_cost(a, b))):
                if b in pad_only:
                    continue
                if add_pad(a, b):
                    done = True
                    break
            if done:
                break
        if not done:
            P.failed = f"space: islands with no way back ({len(stuck)})"
            return False
    # 3. loops: pads until about one a group (q2_q3dm17: 10 for 12), the ones that join far groups first
    want = max(n - 1, int(round(n * 0.9)))
    tries = 0
    while len(P.pads) < want and tries < 4 * n:
        tries += 1
        a = rnd.randrange(n)
        cands = [b for b in range(n) if b != a and b not in adj[a] and (b not in pad_only or a not in pad_only)]
        if not cands:
            continue
        b = min(cands, key=lambda b: pad_cost(a, b))
        add_pad(a, b)
    # 4. teleporters: from the farthest groups that are not pad-only back to a deck (a pair, both ways)
    far = sorted((s for s in P.spaces if s.id not in pad_only and s.id not in decks), key=lambda s: -s.base)
    deck_cells = [c for d in decks for c in P.spaces[d].floor if inner(P, c, 1) and c not in used_cells]
    for s in far[:tele_left]:
        a_cells = [c for c in s.floor if inner(P, c, 1) and c not in used_cells]
        if not a_cells or not deck_cells:
            break
        a = rnd.choice(a_cells)
        b = deck_cells.pop(rnd.randrange(len(deck_cells)))
        # brief 26: the frames' posts stand beside the discs - their cells kept first; the exit then 2 cells off its
        # disc on its island, past the frame (beside the disc it stood inside its frame, one step off the disc back - a
        # cover of 06.11); 3..5 off when 2 has no room, beside it only on the smallest island. Not 3..5 first, as the
        # rooms' exit_cell: on a dense open space an exit further out took the spawns' room (8 players, 3 pairs: 6
        # plans of 60 short of spawns; 3.52 2)
        import mapgen_scratch_fixtures as fix_mod
        keep = set(P.no_items)
        P.no_items.update({a, b})
        fix_mod.reserve_frame(P, a)
        fix_mod.reserve_frame(P, b)

        def ring_cell(c, ring):
            for n_ in sorted(P.spaces[P.owner[c]].floor):
                if max(abs(n_[0] - c[0]), abs(n_[1] - c[1])) == ring and floor_z(P, n_) == floor_z(P, c) \
                        and n_ not in used_cells and (ring == 1 or n_ not in P.no_items):
                    return n_
            return None

        def exit_near(c):
            e = ring_cell(c, 2)
            if e is None:
                e = pm.exit_cell(P, c)
                e = e if e is not None and e not in used_cells else None
            return e if e is not None else ring_cell(c, 1)
        da, db = exit_near(a), exit_near(b)
        if da is None or db is None:
            P.no_items.clear()
            P.no_items.update(keep)
            continue
        P.teleports.append((a, b, da, db))
        used_cells.update({a, b, da, db})
        P.no_items.update({a, b, da, db})
        adj[s.id].update(decks)
        for d in decks:
            adj[d].add(s.id)
    # what each group is entered by
    into = {i: set() for i in range(n)}
    for (a, b) in seen:
        into[b].add("drop")
    for (a, t, *_r) in P.pads:
        into[P.owner[t]].add("pad")
    for (a, b, da, db) in P.teleports:
        into[P.owner[db]].add("teleport")
        into[P.owner[da]].add("teleport")
    P.metrics["pad_only_groups"] = sorted(i for i in range(n) if into[i] == {"pad"} and i not in decks)
    P.metrics["pad_only"] = len(P.metrics["pad_only_groups"])
    P.metrics["pad_only_asked"] = q["pad_only"]
    P.metrics["islands"] = n
    P.metrics["pads"] = len(P.pads)
    P.metrics["drops"] = len(P.air_edges)
    P.metrics["teleporters"] = len(P.teleports)
    return True


def railings(P: pm.Plan, rnd: random.Random) -> None:
    """The edges asked: open - none; some - every other run of an edge; railings - all but where a pad lands or takes
    off, and where a drop leaves an island. A railing stands on the cell's outer side, 32 high."""
    mode = P.params["edges"]
    P.railings = []
    if mode == "open":
        P.metrics["railing_share"] = 0.0
        return
    keep = set()
    for (a, t, *_r) in P.pads:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                keep.update({(a[0] + dx, a[1] + dy), (t[0] + dx, t[1] + dy)})
    keep.update(e for (e, _c, _t) in P.air_edges)
    total = 0
    for s in P.spaces:
        for c in sorted(s.floor):
            for side, (dx, dy) in (("+x", (1, 0)), ("-x", (-1, 0)), ("+y", (0, 1)), ("-y", (0, -1))):
                n = (c[0] + dx, c[1] + dy)
                if n in s.floor:
                    continue
                total += 1
                if c in keep:
                    continue
                if mode == "some" and ((c[0] // 3 + c[1] // 3) % 2):
                    continue
                P.railings.append((c, side, s.floor[c][0]))
    P.metrics["railing_share"] = round(len(P.railings) / max(1, total), 2)


# --------------------------------------------------------------------------------------------- items and spawns
def place_items(P: pm.Plan, rnd: random.Random) -> bool:
    """Spawns on the decks and mids, spread; the power items on the pad-only perches (the quad highest), the armour and
    the main guns on the islands, ammo by its gun, small health and shards spread; powerups on pedestals."""
    q = P.params
    nodes, edges = pm.plan_graph(P)
    taken = set(P.no_items)
    pad_only = set(P.metrics.get("pad_only_groups") or [])

    def free(s: pm.Space, r: int = 1) -> list:
        return [c for c in s.floor if c not in taken and inner(P, c, r)] or [c for c in s.floor if c not in taken and inner(P, c, 0)]

    def put(cls: str, c, note: str = "") -> None:
        P.items.append((cls, c, floor_z(P, c), note))
        taken.add(c)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                taken.add((c[0] + dx, c[1] + dy)) if cls.startswith(("weapon", "item_armor_body", "item_health_mega", "item_quad", "item_invul")) else None

    spaces = sorted(P.spaces, key=lambda s: s.base)
    # the spawns' islands: the decks and the mids (a perch is a prize, not a start)
    walkers = [s for s in spaces if s.pattern != "perch"]
    # spawns (the mechanic «spawn pressure», people's: 1..3 s from the nearest, none over 4): each next one 1.5..3 s by
    # the walk graph (pads and drops in it) from the nearest one placed, the farthest such, 5 cells apart at least
    want_sp = int(q["spawns"])
    movers = [a for (a, t, *_r) in P.pads] + [t for (a, t, *_r) in P.pads] + \
        [c for tp in P.teleports for c in tp]
    cands = [c for s in walkers for c in free(s, 1) if c in edges
             and all(max(abs(c[0] - m[0]), abs(c[1] - m[1])) > 3 for m in movers)]
    rnd.shuffle(cands)
    spawns = []
    t_from: dict = {}

    def nearest_t(c):
        return min((t_from[s_].get(c, 1e9) for s_ in spawns), default=1e9)
    while len(spawns) < want_sp and cands:
        if not spawns:
            deck_c = [c for c in cands if P.spaces[P.owner[c]].pattern == "deck"] or cands
            c = deck_c[0]
        else:
            ok_ = [c for c in cands if all(abs(c[0] - s_[0]) + abs(c[1] - s_[1]) >= 5 or floor_z(P, c) != floor_z(P, s_) for s_ in spawns)]
            win = [c for c in ok_ if 1.2 <= nearest_t(c) <= 2.4]
            if win:
                c = max(win, key=lambda c: nearest_t(c) + rnd.random() * 0.3)
            elif ok_:
                c = min(ok_, key=lambda c: abs(nearest_t(c) - 2.2))
            else:
                break
        cands.remove(c)
        spawns.append(c)
        t_from[c] = pm.dijkstra(edges, c)
        taken.add(c)
    if len(spawns) < max(2, want_sp // 2):
        P.failed = f"space: room for {len(spawns)} spawns of {want_sp}"
        return False
    mx = sum(c[0] for c in nodes) / max(1, len(nodes))
    my = sum(c[1] for c in nodes) / max(1, len(nodes))
    for c in spawns:
        P.spawns.append((c, floor_z(P, c), int(round(math.degrees(math.atan2(my - c[1], mx - c[0])))) % 360))
    # the stack and the guns
    stack = pm.STACK_SETS.get(q["stack"], pm.STACK_SETS["ra_mh"]) if isinstance(q["stack"], str) else dict(q["stack"])
    perch_spaces = sorted((s for s in spaces if s.id in pad_only), key=lambda s: -s.base)
    mids = sorted((s for s in spaces if s.pattern == "mid" and s.id not in pad_only), key=lambda s: -s.base)
    decks = [s for s in spaces if s.pattern == "deck"]
    order = []
    for cls in ("item_invulnerability", "item_quad", "item_health_mega", "item_armor_body", "item_power_shield"):
        order += [cls] * int(stack.get(cls, 0))
    weapons = []
    for cls, k in (q.get("weapons") or {}).items():
        weapons += [cls] * int(k)
    # the power items to the perches (highest first), then the rail if a perch is left
    hosts = list(perch_spaces)
    sites = []
    for cls in order:
        pool = hosts or mids or decks
        s = pool.pop(0) if hosts else pool[0]
        c = free(s, 1)
        if not c:
            continue
        cc = rnd.choice(c)
        put(cls, cc, "on a perch only a pad reaches" if s.id in pad_only else "on an island")
        P.pedestals = getattr(P, "pedestals", [])
        if cls in pm.POWERUPS:
            P.pedestals.append((cc, floor_z(P, cc), cls))
            sites.append((cls, "easy"))
    if "weapon_railgun" in weapons and hosts:
        s = hosts.pop(0)
        c = free(s, 1)
        if c:
            put("weapon_railgun", rnd.choice(c), "on a perch only a pad reaches")
            weapons.remove("weapon_railgun")
    # the armours and the rest of the guns over the walkers: at most two majors to a group, mids first
    others = [cls for cls in ("item_armor_combat", "item_armor_jacket", "item_adrenaline") for _ in range(int(stack.get(cls, 0)))]
    count = {s.id: 0 for s in P.spaces}
    for cls, k_ in P.items and [(it[0], P.owner[it[1]]) for it in P.items] or []:
        count[k_] += 1
    pool_spaces = mids + decks
    for cls in others + weapons:
        if cls == "item_adrenaline":
            s = min(walkers, key=lambda s: s.base)
        else:
            pool_spaces.sort(key=lambda s: (count[s.id], rnd.random()))
            s = pool_spaces[0]
        c = free(s, 1)
        if not c:
            continue
        cc = rnd.choice(c)
        put(cls, cc, "on an island")
        count[s.id] += 1
        ammo = pm.AMMO_OF.get(cls)
        if ammo:
            near = [n_ for n_ in free(s, 0) if abs(n_[0] - cc[0]) + abs(n_[1] - cc[1]) <= 4]
            if near:
                put(ammo, rnd.choice(near), "ammo by its gun")
    # small health, more ammo and shards over every group (the pad-only ones too)
    n_health = max(5, int(round(q["spawns"] * float(q.get("health_per_spawn") or 1.3))))
    groups = list(P.spaces)
    for k in range(n_health):
        s = groups[k % len(groups)]
        c = free(s, 0)
        if c:
            put("item_health_large" if rnd.random() < 0.3 else "item_health", rnd.choice(c), "small health")
    extra = max(0, int(q["spawns"] * float(q.get("ammo_per_spawn") or 2.5)) - sum(1 for it in P.items if it[0].startswith("ammo_")))
    ammos = [pm.AMMO_OF[w] for w in (q.get("weapons") or {}) if w in pm.AMMO_OF] or ["ammo_shells"]
    for k in range(extra):
        s = groups[(k * 3 + 1) % len(groups)]
        c = free(s, 0)
        if c:
            put(ammos[k % len(ammos)], rnd.choice(c), "ammo")
    for k in range(int(q.get("shards") or 0)):
        s = groups[(k * 5 + 2) % len(groups)]
        c = free(s, 0)
        if c:
            put("item_armor_shard", rnd.choice(c), "")
    P.metrics["powerup_sites"] = sites
    return True


def lights(P: pm.Plan) -> None:
    """No sun and no ceiling: a light every three cells over each island (200, 128 over its floor), one at least over
    the smallest. Measured 06.11: 300 gave the floor's median 130 under a style's light flags (people's 60..117,
    check_mapgen_new_map «lit»); 240 every four cells left 40 % of a duel's floor dark."""
    for s in P.spaces:
        cells = sorted(s.floor)
        placed = set()
        for c in cells:
            if c[0] % 3 == 1 and c[1] % 3 == 1:
                placed.add(c)
        if not placed:
            xs, ys = [c[0] for c in cells], [c[1] for c in cells]
            mid = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            placed.add(min(cells, key=lambda c: (c[0] - mid[0]) ** 2 + (c[1] - mid[1]) ** 2))
        for c in sorted(placed):
            z = s.floor[c][0]
            P.lights.append(((c[0] + 0.5) * CELL, (c[1] + 0.5) * CELL, z + 128, 200))


# --------------------------------------------------------------------------------------------- the plan
def plan(P: pm.Plan, rnd: random.Random) -> None:
    """The whole plan of a space map into P (P.failed says why when it cannot be made)."""
    isles = make_isles(P, rnd)
    if not isles:
        P.failed = "space: the islands do not fit the footprint"
        return
    br = bridge(P, isles, rnd)
    groups_of(P, isles, br)
    if not link(P, isles, rnd):
        return
    railings(P, rnd)
    if not place_items(P, rnd):
        return
    import mapgen_scratch_fixtures as fix_mod     # brief 32: the pads', frames' and plates' sizes
    fix_mod.plan_sizes(P)
    lights(P)
    P.metrics["pads_no_reason"] = len(pm.pads_without_reason(P))     # brief 34
    zs = [f[0] for s in P.spaces for f in s.floor.values()]
    m = P.metrics
    m["floor_area"] = round(sum(len(s.floor) for s in P.spaces) * CELL * CELL / 1e6, 2)
    m["vertical_span"] = max(zs) - min(zs)
    for k in ("stairs_got", "ramps_got", "drops_got", "windows_got", "stacked_rooms", "corridor_turns"):
        m.setdefault(k, 0)
    m["drops_got"] = len(P.air_edges)
    m.setdefault("round", {})
    m.setdefault("mech_missing", [])
    m["score"] = round(score(P), 2)


def score(P: pm.Plan) -> float:
    """Penalties against what was asked (lower is better): the islands, the pad-only perches, the floor, the height
    span, the pads, the spawns' spread."""
    q, m = P.params, P.metrics
    pen = 3.0 * abs(m.get("islands", 0) - q["islands"])
    # «только по джампаду» is a floor: at least the perches asked; more than half the islands so is no longer a map one
    # walks (q2_q3dm17: 4 of 12)
    pen += 4.0 * max(0, q["pad_only"] - m.get("pad_only", 0))
    pen += 2.0 * max(0, m.get("pad_only", 0) - max(q["pad_only"] + 1, int(0.5 * m.get("islands", 1))))
    pen += 8.0 * max(0.0, abs(m.get("floor_area", 0) - q["floor_area"]) / q["floor_area"] - 0.12)
    pen += 4.0 * max(0.0, abs(m.get("vertical_span", 0) - q["height_spread"]) / q["height_spread"] - 0.15)
    n = max(1, m.get("islands", 1))
    pen += 1.5 * max(0, n - 1 - m.get("pads", 0))
    sp = [c for (c, _z, _a) in P.spawns]
    if len(sp) >= 2:
        near = min(math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(sp) for b in sp[i + 1:])
        pen += 2.0 * max(0.0, 5.0 - near)
    return pen
