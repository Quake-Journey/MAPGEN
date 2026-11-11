r"""What a Quake II deathmatch map IS, measured from its compiled BSP the way people's maps were measured (brief 19 D7).

Fable's research of 04.11 (`doc/reports/research_fable_2026-11-04_mapgen_from_scratch_human_maps.md`) measured 120
human-made maps with one method and gave the bands a map made from scratch is held to: how much floor, how many
height levels, how wide the places are, how far one sees, how many ways lead from an item, how long it takes to get
from a spawn to a gun. The bands only mean something if the new map is measured the SAME way, so the method is here
as code, and `--calibrate` measures the reference maps again beside the numbers the research printed.

The method:
  * floor points on a 32-unit grid: a vertical ray through the world's tree (and each `func_wall`'s) finds every
    surface with solid under it and air over it; a point counts where a player fits (not SOLID|WINDOW|PLAYERCLIP at
    +2, +28, +54) and the surface faces up (normal z >= 0.7);
  * edges, at 300 units a second: walk/step (rise <= 20, the body clear between); jump up (<= 44); running gap jumps
    (up to 256 across, no floor in between); drops (one way); swimming in water; a `func_plat` from its lowered
    position to its top; ladders; `misc_teleporter` and `trigger_teleport` to their destination; `trigger_push` as a
    ballistic flight (velocity = movedir x speed x 10, gravity 800) with a landing steered within 448 units when the
    pad throws mostly up. Lava, slime and `trigger_hurt` volumes are out of the graph;
  * reachable = forward from the deathmatch spawns. Not modelled: trains, door elevators, rocket and strafe jumps;
  * levels = clusters of floor height holding >= 5 % of the floor; vertical span = p5..p95 of floor height;
  * width = the narrowest of four opposite ray pairs at +40 from 900 floor points: corridor <= 192, medium <= 448,
    open beyond; headroom straight up;
  * sight = 8000 random pairs of floor points at eye height (+46), blocked by SOLID|WINDOW;
  * majors = weapons from the super shotgun up, body and combat armour, mega health, quad, invulnerability; «at
    height» = 64 or more above the lowest level holding 10 % of the floor; exits = separate groups of floor reached
    1.4..1.6 s from the item; a route's alternative = the detour when a 96-unit disc at its half-way point is closed.

    python tools/mapgen_map_survey.py MAP.bsp [--json] [--seed N]
    python tools/mapgen_map_survey.py --calibrate          the reference maps against the research's numbers

Pure Python on purpose: it ships with the Studio's tools and a user's Python has no numpy.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import random
import struct
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_bsp_oracle as oracle  # noqa: E402

SOLID, WINDOW, LAVA, SLIME, WATER = 1, 2, 8, 16, 32
PLAYERCLIP, LADDER = 0x10000, 0x20000000
BLOCK_BODY = SOLID | WINDOW | PLAYERCLIP
BLOCK_SIGHT = SOLID | WINDOW
GRID = 32
SPEED = 300.0
GRAVITY = 800.0

MAJORS = {"weapon_supershotgun", "weapon_machinegun", "weapon_chaingun", "weapon_grenadelauncher",
          "weapon_rocketlauncher", "weapon_hyperblaster", "weapon_railgun", "weapon_bfg",
          "item_armor_body", "item_armor_combat", "item_health_mega", "item_quad", "item_invulnerability"}
MAIN_WEAPONS = {"weapon_supershotgun", "weapon_chaingun", "weapon_grenadelauncher", "weapon_rocketlauncher",
                "weapon_hyperblaster", "weapon_railgun", "weapon_bfg", "weapon_machinegun"}
STACK = {"item_armor_body", "item_armor_combat", "item_health_mega"}


# --------------------------------------------------------------------------------------------- the compiled world
class World:
    """The planes, nodes and leaves of a BSP in flat lists, for point and segment queries in pure Python."""

    def __init__(self, path: Path):
        self.bsp = oracle.load(Path(path))
        b = self.bsp
        self.pn = [(p.normal[0], p.normal[1], p.normal[2], p.dist, p.type) for p in b.planes]
        self.nodes = [(n.planenum, n.children[0], n.children[1]) for n in b.nodes]
        self.leaf_contents = [lf.contents for lf in b.leafs]
        self.ents = b.entities()
        self.heads = [b.models[0].headnode] + [b.models[int(e["model"][1:])].headnode
                                               for e in self.ents
                                               if e.get("classname") == "func_wall" and e.get("model", "").startswith("*")]
        ws = next((e for e in self.ents if e.get("classname") == "worldspawn"), {})
        try:
            self.gravity = float(ws.get("gravity", "800") or 800)
        except ValueError:
            self.gravity = GRAVITY

    def contents(self, x: float, y: float, z: float, head: int | None = None) -> int:
        n = self.bsp.models[0].headnode if head is None else head
        pn, nodes = self.pn, self.nodes
        while n >= 0:
            pl, c0, c1 = nodes[n]
            nx, ny, nz, d, t = pn[pl]
            v = (x if t == 0 else y if t == 1 else z if t == 2 else x * nx + y * ny + z * nz) - d
            n = c0 if v >= 0 else c1
        return self.leaf_contents[-1 - n]

    def contents_all(self, x: float, y: float, z: float) -> int:
        c = 0
        for h in self.heads:
            c |= self.contents(x, y, z, h)
        return c

    def column(self, x: float, y: float, top: float, bottom: float, head: int):
        """Leaf intervals down a vertical line: [(z_high, z_low, contents, normal_z_at_low)] top to bottom."""
        out = []
        pn, nodes, lc = self.pn, self.nodes, self.leaf_contents

        def walk(n, za, zb, nza):
            # za > zb: the part of the line from za down to zb lies in node n's subtree
            while n >= 0:
                pl, c0, c1 = nodes[n]
                nx, ny, nz, d, t = pn[pl]
                if t == 0:
                    v = x - d
                    n = c0 if v >= 0 else c1
                    continue
                if t == 1:
                    v = y - d
                    n = c0 if v >= 0 else c1
                    continue
                base = x * nx + y * ny - d
                va, vb = base + za * nz, base + zb * nz
                if va >= 0 and vb >= 0:
                    n = c0
                    continue
                if va < 0 and vb < 0:
                    n = c1
                    continue
                zm = za + (zb - za) * (va / (va - vb))
                near, far = (c0, c1) if va >= 0 else (c1, c0)
                walk(near, za, zm, nza)
                walk(far, zm, zb, abs(nz))
                return
            out.append((za, zb, lc[-1 - n], nza))

        walk(head, top, bottom, 1.0)
        # the normal recorded at an interval's TOP is the plane it was split at; shift it so each interval carries
        # the normal of the boundary at its LOW end (the surface a player would stand on below it is the next one's top)
        res = []
        for i, (za, zb, c, _) in enumerate(out):
            low_n = out[i + 1][3] if i + 1 < len(out) else 1.0
            res.append((za, zb, c, low_n))
        return res

    def blocked(self, a, b, mask: int = BLOCK_SIGHT) -> bool:
        """Does the segment a-b cross a leaf whose contents hit `mask` (world tree only)?"""
        pn, nodes, lc = self.pn, self.nodes, self.leaf_contents
        stack = [(self.bsp.models[0].headnode, 0.0, 1.0)]
        ax, ay, az = a
        dx, dy, dz = b[0] - ax, b[1] - ay, b[2] - az
        while stack:
            n, t0, t1 = stack.pop()
            while n >= 0:
                pl, c0, c1 = nodes[n]
                nx, ny, nz, d, t = pn[pl]
                if t == 0:
                    v0, v1 = ax + dx * t0 - d, ax + dx * t1 - d
                elif t == 1:
                    v0, v1 = ay + dy * t0 - d, ay + dy * t1 - d
                elif t == 2:
                    v0, v1 = az + dz * t0 - d, az + dz * t1 - d
                else:
                    base = ax * nx + ay * ny + az * nz - d
                    step = dx * nx + dy * ny + dz * nz
                    v0, v1 = base + step * t0, base + step * t1
                if v0 >= 0 and v1 >= 0:
                    n = c0
                elif v0 < 0 and v1 < 0:
                    n = c1
                else:
                    tm = t0 + (t1 - t0) * (v0 / (v0 - v1))
                    near, far = (c0, c1) if v0 >= 0 else (c1, c0)
                    stack.append((far, tm, t1))
                    n, t1 = near, tm
            if lc[-1 - n] & mask:
                return True
        return False

    def ray_length(self, a, direction, limit: float = 4096.0, mask: int = BLOCK_BODY) -> float:
        """Distance along `direction` from `a` to the first leaf hitting `mask` (bisection on `blocked`)."""
        lo, hi = 0.0, limit
        far = (a[0] + direction[0] * limit, a[1] + direction[1] * limit, a[2] + direction[2] * limit)
        if not self.blocked(a, far, mask):
            return limit
        for _ in range(14):
            mid = (lo + hi) / 2
            p = (a[0] + direction[0] * mid, a[1] + direction[1] * mid, a[2] + direction[2] * mid)
            if self.blocked(a, p, mask):
                hi = mid
            else:
                lo = mid
        return lo


def model_bounds(w: World, e: dict):
    m = e.get("model", "")
    if not m.startswith("*"):
        return None
    mo = w.bsp.models[int(m[1:])]
    return mo.mins, mo.maxs


def fvec(s: str, default=(0.0, 0.0, 0.0)):
    try:
        v = [float(t) for t in s.split()]
        return tuple(v[:3]) if len(v) >= 3 else default
    except (ValueError, AttributeError):
        return default


# --------------------------------------------------------------------------------------------- the floor graph
# brief 34: the stopping trains ridden by the walk (a RED switches it off: the storeys only a lift reaches go out of reach)
TRAINS_RIDDEN = True


class Graph:
    def __init__(self, w: World):
        self.w = w
        self.nodes: list[tuple[float, float, float]] = []    # x, y, z of a standing point
        self.water: list[bool] = []
        self.flat: list[bool] = []
        self.at: dict[tuple[int, int], list[int]] = {}       # grid cell -> node ids
        self.edges: list[list[tuple[int, float]]] = []
        self.kinds: dict[str, int] = {}
        self.lava_points = 0
        self.slime_points = 0
        # brief 19 §6: what the movers' mechanics are measured by
        self.edge_kind: dict = {}          # (a, b) -> plat | ladder | teleport | push
        self.push_paths: list = []         # each pad's flight, points (x, y, z) until it lands
        self.tele_dests: list = []         # (dest node, dest origin, dest yaw)
        self.ladder_tops: list = []        # (x, y, z) of each ladder's top

    def add(self, x, y, z, water, flat):
        i = len(self.nodes)
        self.nodes.append((x, y, z))
        self.water.append(water)
        self.flat.append(flat)
        self.at.setdefault((int(math.floor(x / GRID)), int(math.floor(y / GRID))), []).append(i)
        self.edges.append([])
        return i

    def link(self, a, b, cost, kind):
        self.edges[a].append((b, cost))
        self.kinds[kind] = self.kinds.get(kind, 0) + 1
        if kind in ("plat", "ladder", "teleport", "push"):
            self.edge_kind[(a, b)] = kind

    def nearest(self, p, below: float = 200.0, radius: float = 48.0):
        """The standing point closest under a point (an item or a spawn sits a little above its floor)."""
        best, bd = None, 1e18
        cx, cy = int(math.floor(p[0] / GRID)), int(math.floor(p[1] / GRID))
        r = int(math.ceil(radius / GRID)) + 1
        for ix in range(cx - r, cx + r + 1):
            for iy in range(cy - r, cy + r + 1):
                for i in self.at.get((ix, iy), ()):
                    x, y, z = self.nodes[i]
                    dzv = p[2] - z
                    if dzv < -32 or dzv > below:
                        continue
                    d = (x - p[0]) ** 2 + (y - p[1]) ** 2 + (dzv * 0.25) ** 2
                    if d < bd:
                        best, bd = i, d
        return best


def build_graph(w: World, hurt_boxes) -> Graph:
    g = Graph(w)
    m0 = w.bsp.models[0]
    lo = [max(m0.mins[a], -8192.0) for a in range(3)]
    hi = [min(m0.maxs[a], 8192.0) for a in range(3)]
    top, bottom = hi[2] + 64.0, lo[2] - 64.0

    def in_hurt(x, y, z):
        for (a, b) in hurt_boxes:
            if a[0] <= x <= b[0] and a[1] <= y <= b[1] and a[2] - 32 <= z <= b[2]:
                return True
        return False

    x0 = math.floor(lo[0] / GRID) * GRID + GRID / 2
    y0 = math.floor(lo[1] / GRID) * GRID + GRID / 2
    x = x0
    while x < hi[0]:
        y = y0
        while y < hi[1]:
            surfaces = []
            for head in w.heads:
                iv = w.column(x, y, top, bottom, head)
                for k in range(len(iv) - 1):
                    za, zb, c, nlow = iv[k]
                    below = iv[k + 1][2]
                    if not (c & BLOCK_BODY) and (below & (SOLID | PLAYERCLIP | WINDOW)) and nlow >= 0.7:
                        surfaces.append((zb, nlow))
            for z, nz in surfaces:
                ok = True
                for h in (2.0, 28.0, 54.0):
                    if w.contents_all(x, y, z + h) & BLOCK_BODY:
                        ok = False
                        break
                if not ok:
                    continue
                c2 = w.contents(x, y, z + 2.0)
                if c2 & LAVA:
                    g.lava_points += 1
                if c2 & SLIME:
                    g.slime_points += 1
                if c2 & (LAVA | SLIME) or in_hurt(x, y, z):
                    continue
                g.add(x, y, z, bool(c2 & WATER) or bool(w.contents(x, y, z + 28.0) & WATER), nz >= 0.95)
            y += GRID
        x += GRID
    return g


def clear_between(w: World, a, b, z) -> bool:
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    for h in (8.0, 28.0, 54.0):
        if w.contents_all(mx, my, z + h) & BLOCK_BODY:
            return False
    return True


def fall_clear(w: World, x: float, y: float, z_top: float, z_floor: float) -> bool:
    """Brief 21: the column a drop falls down is open from the height it leaves to a man's head over the floor it
    lands on - a drop's edge checked the air at the ledge only, and a floor over a floor (a room over a room, a
    bridge over a corridor) let the walk fall through the upper floor (05.11: RG->RA 3.5 s on a map whose only way
    is 12.9 s, a «drop» from a doorway's step through the room over the corridor into the corridor)."""
    h = z_floor + 60.0
    while h < z_top - 2.0:
        if w.contents_all(x, y, h) & BLOCK_BODY:
            return False
        h += 6.0           # under the thinnest floor (our slab 16, a people's bridge 8)
    return True


def link_graph(g: Graph, w: World):
    nodes = g.nodes
    for i, (x, y, z) in enumerate(nodes):
        cx, cy = int(math.floor(x / GRID)), int(math.floor(y / GRID))
        for dxi in (-1, 0, 1):
            for dyi in (-1, 0, 1):
                if not dxi and not dyi:
                    continue
                cell = g.at.get((cx + dxi, cy + dyi))
                if not cell:
                    continue
                dist = GRID * (1.4142 if dxi and dyi else 1.0)
                for j in cell:
                    nx_, ny_, nzz = nodes[j]
                    dz = nzz - z
                    if g.water[i] and g.water[j] and abs(dz) <= 96:
                        if clear_between(w, nodes[i], nodes[j], max(z, nzz)):
                            g.link(i, j, dist / (SPEED * 0.6), "swim")
                        continue
                    if abs(dz) <= 20:
                        if clear_between(w, nodes[i], nodes[j], max(z, nzz)):
                            g.link(i, j, dist / SPEED, "walk")
                    elif 20 < dz <= 44:
                        if clear_between(w, nodes[i], nodes[j], nzz) and \
                                not (w.contents_all(x, y, z + 54 + dz) & BLOCK_BODY):
                            g.link(i, j, dist / SPEED + 0.2, "jump")
                    elif dz < -20:
                        if clear_between(w, nodes[i], nodes[j], z) and fall_clear(w, nx_, ny_, z, nzz):
                            g.link(i, j, dist / SPEED + math.sqrt(2 * -dz / w.gravity), "drop")
        # running gap jumps: straight on over a gap where the next column holds no floor near this height
        for dxi, dyi in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            near = g.at.get((cx + dxi, cy + dyi), ())
            if any(abs(nodes[j][2] - z) <= 44 for j in near):
                continue
            step = math.hypot(dxi, dyi) * GRID
            for k in range(2, 9):
                if k * step > 256:
                    break
                far = g.at.get((cx + dxi * k, cy + dyi * k), ())
                hit = [j for j in far if -160 <= nodes[j][2] - z <= 20]
                if not hit:
                    continue
                j = max(hit, key=lambda q: nodes[q][2])
                path_clear = fall_clear(w, nodes[j][0], nodes[j][1], z + 40, nodes[j][2])
                for s in range(1, k):
                    px, py = x + dxi * GRID * s, y + dyi * GRID * s
                    if w.contents_all(px, py, z + 40) & BLOCK_BODY or w.contents_all(px, py, z + 70) & BLOCK_BODY:
                        path_clear = False
                        break
                if path_clear:
                    g.link(i, j, k * step / SPEED + 0.1, "gap")
                break


def movers(g: Graph, w: World):
    """Plats, ladders, teleporters and pads as extra edges."""
    ents = w.ents
    named = {}
    for e in ents:
        if e.get("targetname"):
            named.setdefault(e["targetname"], []).append(e)
    n_plat = n_tel = n_push = n_ladder = n_train = 0
    for e in ents:
        cls = e.get("classname", "")
        if cls == "func_train" and TRAINS_RIDDEN:
            # brief 34 (the PO 08.11: «лифты как в небоскрёбах - едут между этажами, останавливаются там»): a train
            # whose path corners stop it at floors - its mins go to each corner (the game's train_next); a man at a
            # stop's floor beside the cabin rides to every other stop (the wait and the ride)
            mb = model_bounds(w, e)
            if not mb:
                continue
            mins, maxs = mb
            size = [maxs[k] - mins[k] for k in range(3)]
            stops, seen, at = [], set(), e.get("target", "")
            while at and at not in seen and named.get(at):
                seen.add(at)
                c = named[at][0]
                o = fvec(c.get("origin", ""))
                stops.append((o[0], o[1], o[2] + size[2]))
                at = c.get("target", "")
            try:
                speed = float(e.get("speed", "100") or 100)
            except ValueError:
                speed = 100.0
            groups = []
            for (ox, oy, top) in {(round(x), round(y), round(z)) for (x, y, z) in stops}:
                near = [i for i, (x, y, z) in enumerate(g.nodes)
                        if ox - 64 <= x <= ox + size[0] + 64 and oy - 64 <= y <= oy + size[1] + 64 and abs(z - top) <= 24]
                if near:
                    groups.append((top, near))
            for (za, na) in groups:
                for (zb, nb) in groups:
                    if za == zb:
                        continue
                    ride = 2.0 + abs(za - zb) / max(speed, 1.0)
                    for a_ in na:
                        for b_ in nb:
                            g.link(a_, b_, ride, "train")
            if len(groups) >= 2:
                n_train += 1
            continue
        if cls == "func_plat":
            mb = model_bounds(w, e)
            if not mb:
                continue
            mins, maxs = mb
            try:
                lip = float(e.get("lip", "8"))
            except ValueError:
                lip = 8.0
            try:
                height = float(e["height"]) if e.get("height") else (maxs[2] - mins[2]) - lip
            except ValueError:
                height = (maxs[2] - mins[2]) - lip
            top = maxs[2]
            low = top - height
            cx, cy = (mins[0] + maxs[0]) / 2, (mins[1] + maxs[1]) / 2
            ups = [i for i, (x, y, z) in enumerate(g.nodes)
                   if mins[0] - 64 <= x <= maxs[0] + 64 and mins[1] - 64 <= y <= maxs[1] + 64 and abs(z - top) <= 24]
            downs = [i for i, (x, y, z) in enumerate(g.nodes)
                     if mins[0] - 16 <= x <= maxs[0] + 16 and mins[1] - 16 <= y <= maxs[1] + 16
                     and z <= low + 24]
            if ups and downs:
                d = max(downs, key=lambda q: g.nodes[q][2])
                ride = 0.35 + height / 220.0
                for u in ups:
                    g.link(d, u, ride, "plat")
                    g.link(u, d, ride, "plat")
                n_plat += 1
        elif cls in ("misc_teleporter", "trigger_teleport"):
            dest = named.get(e.get("target", ""), [])
            if not dest:
                continue
            if cls == "misc_teleporter":
                src = fvec(e.get("origin", ""))
                a = g.nearest(src, below=96, radius=64)
            else:
                mb = model_bounds(w, e)
                if not mb:
                    continue
                src = tuple((mb[0][k] + mb[1][k]) / 2 for k in range(3))
                a = g.nearest((src[0], src[1], mb[0][2] + 24), below=160, radius=96)
            b = g.nearest(fvec(dest[0].get("origin", "")), below=160, radius=64)
            if a is not None and b is not None:
                g.link(a, b, 0.05, "teleport")
                n_tel += 1
                try:
                    yaw_d = float(dest[0].get("angle", "0") or 0)
                except ValueError:
                    yaw_d = 0.0
                g.tele_dests.append((b, fvec(dest[0].get("origin", "")), yaw_d))
        elif cls == "trigger_push":
            mb = model_bounds(w, e)
            if not mb:
                continue
            mins, maxs = mb
            try:
                speed = float(e.get("speed", "1000") or 1000)
            except ValueError:
                speed = 1000.0
            ang = e.get("angles")
            if ang:
                pitch, yaw, _ = fvec(ang)
            else:
                try:
                    yaw = float(e.get("angle", "0"))
                except ValueError:
                    yaw = 0.0
                pitch = 0.0
                if yaw == -1:
                    pitch, yaw = -90.0, 0.0
                elif yaw == -2:
                    pitch, yaw = 90.0, 0.0
            pr, yr = math.radians(pitch), math.radians(yaw)
            vx = math.cos(pr) * math.cos(yr) * speed * 10
            vy = math.cos(pr) * math.sin(yr) * speed * 10
            vz = -math.sin(pr) * speed * 10
            sx, sy = (mins[0] + maxs[0]) / 2, (mins[1] + maxs[1]) / 2
            src = g.nearest((sx, sy, mins[2] + 24), below=160, radius=96)
            if src is None:
                continue
            x, y, z = g.nodes[src]
            z += 24
            landings = set()
            steer = math.hypot(vx, vy) < abs(vz) * 0.5
            t, dt = 0.0, 0.025
            px, py, pz, pvz = x, y, z, vz
            apex = None
            path = []
            g.push_paths.append(path)
            while t < 4.0:
                px += vx * dt
                py += vy * dt
                pz += pvz * dt
                pvz -= w.gravity * dt
                t += dt
                path.append((px, py, pz))
                if w.contents_all(px, py, pz + 28) & BLOCK_BODY:
                    break
                if pvz < 0 and apex is None:
                    apex = (px, py, pz, t)
                if pvz < 0:
                    j = g.nearest((px, py, pz), below=24, radius=24)
                    if j is not None:
                        landings.add((j, t))
                        break
            if steer and apex:
                ax, ay, az, at_ = apex
                for j, (nx_, ny_, nzz) in enumerate(g.nodes):
                    if nzz < az - 24 and math.hypot(nx_ - ax, ny_ - ay) <= 448:
                        fall = math.sqrt(2 * (az - nzz) / w.gravity)
                        landings.add((j, at_ + fall))
            for j, tt in landings:
                g.link(src, j, tt, "push")
            if landings:
                n_push += 1
    # ladders: brushes with ladder contents join the floor under them to the floor at their top
    b = w.bsp
    for br in b.brushes:
        if not (br.contents & LADDER):
            continue
        xs, ys, zs = [], [], []
        # bounds of a brush from its axial sides
        mins, maxs = [-1e9] * 3, [1e9] * 3
        for s in range(br.firstside, br.firstside + br.numsides):
            p = b.planes[b.brushsides[s].planenum]
            for a in range(3):
                if abs(p.normal[a]) > 0.999:
                    if p.normal[a] > 0:
                        maxs[a] = min(maxs[a], p.dist)
                    else:
                        mins[a] = max(mins[a], -p.dist)
        if any(abs(v) > 1e8 for v in mins + maxs):
            continue
        low = [i for i, (x, y, z) in enumerate(g.nodes)
               if mins[0] - 48 <= x <= maxs[0] + 48 and mins[1] - 48 <= y <= maxs[1] + 48 and abs(z - mins[2]) <= 40]
        up = [i for i, (x, y, z) in enumerate(g.nodes)
              if mins[0] - 64 <= x <= maxs[0] + 64 and mins[1] - 64 <= y <= maxs[1] + 64 and abs(z - maxs[2]) <= 48]
        if low and up:
            g.ladder_tops.append(((mins[0] + maxs[0]) / 2, (mins[1] + maxs[1]) / 2, maxs[2]))
            rise = maxs[2] - mins[2]
            for a_ in low[:4]:
                for u in up[:4]:
                    g.link(a_, u, rise / 200.0, "ladder")
                    g.link(u, a_, rise / 300.0, "ladder")
            n_ladder += 1
    return {"plats": n_plat, "teleporters": n_tel, "pads": n_push, "ladders": n_ladder, "trains": n_train}


def dijkstra(g: Graph, sources, blocked: set | None = None, prev: list | None = None):
    dist = [math.inf] * len(g.nodes)
    pq = []
    for s in sources:
        if s is not None and (not blocked or s not in blocked):
            dist[s] = 0.0
            pq.append((0.0, s))
    heapq.heapify(pq)
    while pq:
        d, i = heapq.heappop(pq)
        if d > dist[i]:
            continue
        for j, c in g.edges[i]:
            if blocked and j in blocked:
                continue
            nd = d + c
            if nd < dist[j]:
                dist[j] = nd
                if prev is not None:
                    prev[j] = i
                heapq.heappush(pq, (nd, j))
    return dist


# --------------------------------------------------------------------------------------------- the measures
def percentile(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def levels_of(zs, share=0.05, reach=16.0):
    """Floor heights that hold a share of the floor: the z of every point in 8-unit bins; the fullest bin not yet
    taken gathers the bins within `reach` of it, and the group is a level when it holds >= `share` of the floor.
    A flight of stairs spreads its floor over many bins and makes no level; a hall's floor is one."""
    if not zs:
        return []
    hist: dict[int, int] = {}
    for z in zs:
        k = int(round(z / 8.0))
        hist[k] = hist.get(k, 0) + 1
    taken: set[int] = set()
    n = len(zs)
    out = []
    span = int(reach / 8)
    for k, _ in sorted(hist.items(), key=lambda kv: -kv[1]):
        if k in taken:
            continue
        grp = [q for q in range(k - span, k + span + 1) if q in hist and q not in taken]
        taken.update(grp)
        cnt = sum(hist[q] for q in grp)
        if cnt / n >= share:
            out.append((k * 8, cnt / n))
    return sorted(out)


def survey(path: Path, seed: int = 1, doors: list | None = None) -> dict:
    rnd = random.Random(seed)
    w = World(path)
    hurt = []
    for e in w.ents:
        if e.get("classname") == "trigger_hurt":
            mb = model_bounds(w, e)
            if mb:
                hurt.append(mb)
    g = build_graph(w, hurt)
    link_graph(g, w)
    mv = movers(g, w)

    spawns = [fvec(e.get("origin", "")) for e in w.ents if e.get("classname") == "info_player_deathmatch"
              and not (int(e.get("spawnflags", "0") or 0) & 0x800)]
    spawn_nodes = [g.nearest(s, below=96) for s in spawns]
    reach = dijkstra(g, [s for s in spawn_nodes if s is not None])
    R = [i for i in range(len(g.nodes)) if reach[i] < math.inf]
    Rset = set(R)
    out: dict = {"map": Path(path).stem, "spawns": len(spawns), "floor_points": len(g.nodes),
                 "reachable_points": len(R), "edge_kinds": g.kinds, "movers": mv}
    if not R:
        out["error"] = "no floor reachable from the spawns"
        return out
    zs = [g.nodes[i][2] for i in R]
    out["walk_area_mu2"] = round(len(R) * GRID * GRID / 1e6, 2)
    xs = [g.nodes[i][0] for i in R]
    ys = [g.nodes[i][1] for i in R]
    out["footprint"] = [round(max(xs) - min(xs) + GRID), round(max(ys) - min(ys) + GRID),
                        round(max(zs) - min(zs))]
    lv = levels_of(zs)
    out["levels"] = len(lv)
    out["level_heights"] = [z for z, _ in lv]
    out["vertical_span"] = round(percentile(zs, 0.95) - percentile(zs, 0.05))
    base = min((z for z, sh in levels_of(zs, 0.10)), default=min(zs))
    out["base_level"] = base
    # brief 21 (brief 20 D5): floor over floor - a reachable dry standing place with another one at least 128 above
    # or below it in the same column (a room over a room, a bridge over a corridor; a lift's plat is no world brush)
    st = stacked_points(g, R)
    out["stacked_points"] = st
    out["stacked_area_mu2"] = round(st * GRID * GRID / 1e6, 3)
    out["stacked_share"] = round(st / len(R), 3)

    # widths and headroom
    sample = R if len(R) <= 900 else rnd.sample(R, 900)
    dirs = [(1, 0), (0, 1), (0.7071, 0.7071), (0.7071, -0.7071)]
    widths, heads = [], []
    for i in sample:
        x, y, z = g.nodes[i]
        p = (x, y, z + 40)
        wmin = 1e9
        for dx_, dy_ in dirs:
            a = w.ray_length(p, (dx_, dy_, 0.0), 2048.0)
            b = w.ray_length(p, (-dx_, -dy_, 0.0), 2048.0)
            wmin = min(wmin, a + b)
        widths.append(wmin)
        heads.append(w.ray_length((x, y, z + 2), (0.0, 0.0, 1.0), 2048.0, SOLID | WINDOW))
    out["width_median"] = round(percentile(widths, 0.5))
    out["width_p25"] = round(percentile(widths, 0.25))
    n = len(widths)
    out["share_corridor"] = round(sum(1 for v in widths if v <= 192) / n, 3)
    out["share_medium"] = round(sum(1 for v in widths if 192 < v <= 448) / n, 3)
    out["share_open"] = round(sum(1 for v in widths if v > 448) / n, 3)
    out["headroom_median"] = round(percentile(heads, 0.5))

    # sight
    pairs = 8000
    vis, vd = 0, []
    long_pairs = []
    cross = 0
    for _ in range(pairs):
        a, b = rnd.choice(R), rnd.choice(R)
        if a == b:
            continue
        pa, pb = g.nodes[a], g.nodes[b]
        ea, eb = (pa[0], pa[1], pa[2] + 46), (pb[0], pb[1], pb[2] + 46)
        if not w.blocked(ea, eb, BLOCK_SIGHT):
            vis += 1
            # brief 21 D5: of what one sees, how much stands on another level (128 u and more up or down)
            if abs(pa[2] - pb[2]) >= 128:
                cross += 1
            vd.append(math.dist(ea, eb))
            if vd[-1] > 1000:
                long_pairs.append((ea, eb))
    out["visible_pairs"] = round(vis / pairs, 3)
    out["cross_level_seen"] = round(cross / max(1, vis), 3)
    out["visible_p95"] = round(percentile(vd, 0.95))
    out["visible_max"] = round(max(vd) if vd else 0)
    out["visible_over_1000"] = round(sum(1 for d in vd if d > 1000) / pairs, 4)
    out["long_lines"] = len(distinct_lines(long_pairs))
    out["long_line_ends"] = [[[round(v) for v in a], [round(v) for v in b]] for a, b in long_pairs]
    out["visible_over_1000_of_visible"] = round(sum(1 for d in vd if d > 1000) / max(1, len(vd)), 3)

    # items
    items = []
    for e in w.ents:
        cls = e.get("classname", "")
        if (cls.startswith(("weapon_", "item_", "ammo_"))) and not (int(e.get("spawnflags", "0") or 0) & 0x800):
            o = fvec(e.get("origin", ""))
            items.append((cls, o, g.nearest(o, below=120)))
    # sites: one class within 48 units counts once
    sites = []
    for cls, o, nd in items:
        if any(c == cls and math.hypot(o[0] - p[0], o[1] - p[1]) <= 48 for c, p, _ in sites):
            continue
        sites.append((cls, o, nd))
    counts: dict[str, int] = {}
    for cls, _, _ in sites:
        counts[cls] = counts.get(cls, 0) + 1
    out["sites"] = dict(sorted(counts.items()))
    majors = [(c, o, nd) for c, o, nd in sites if c in MAJORS and nd is not None and nd in Rset]
    out["majors"] = len(majors)
    out["majors_unreachable"] = sorted(c for c, o, nd in sites if c in MAJORS and (nd is None or nd not in Rset))
    if majors:
        out["majors_at_height"] = round(sum(1 for _, _, nd in majors if g.nodes[nd][2] >= base + 64) / len(majors), 2)
    sp_ok = [s for s in spawn_nodes if s is not None and s in Rset]
    if sp_ok:
        out["spawns_at_height"] = round(sum(1 for s in sp_ok if g.nodes[s][2] >= base + 64) / len(sp_ok), 2)

    # sight from majors
    seen = []
    for c, o, nd in majors:
        x, y, z = g.nodes[nd]
        eye = (x, y, z + 46)
        tries = rnd.sample(R, min(400, len(R)))
        seen.append(sum(1 for t in tries if not w.blocked(eye, (g.nodes[t][0], g.nodes[t][1], g.nodes[t][2] + 46))) / len(tries))
    out["major_sees_median"] = round(percentile(seen, 0.5), 3) if seen else 0.0

    # times
    dist_from = {}
    for c, o, nd in majors:
        dist_from[nd] = dijkstra(g, [nd])
    exits = []
    for c, o, nd in majors:
        d = dist_from[nd]
        ring = [i for i in R if 1.4 <= d[i] <= 1.6]
        exits.append(groups_of(g, ring))
    out["exits_median"] = percentile(exits, 0.5) if exits else 0
    out["dead_end_majors"] = round(sum(1 for e in exits if e <= 1) / len(exits), 2) if exits else 0.0
    mm = []
    alt, alt_ok = [], 0
    for ia in range(len(majors)):
        for ib in range(ia + 1, len(majors)):
            a, b = majors[ia][2], majors[ib][2]
            t, ratio = detour(g, a, b)
            if t < math.inf:
                mm.append(t)
                alt.append(ratio)
                if ratio <= 1.5:
                    alt_ok += 1
    out["major_major_median_s"] = round(percentile(mm, 0.5), 2) if mm else 0.0
    out["route_detour_median"] = round(percentile([r for r in alt if r < math.inf], 0.5), 2) if alt else 0.0
    out["pairs_with_alternative"] = round(alt_ok / len(alt), 2) if alt else 0.0
    main_w = [nd for c, o, nd in majors if c in MAIN_WEAPONS]
    stack = [nd for c, o, nd in majors if c in STACK]
    t_w, t_s, t_sp = [], [], []
    for s in sp_ok:
        d = dijkstra(g, [s])
        if main_w:
            t_w.append(min(d[x] for x in main_w))
        if stack:
            t_s.append(min(d[x] for x in stack))
        others = [d[o] for o in sp_ok if o != s and d[o] < math.inf]
        if others:
            t_sp.append(min(others))
    out["spawn_to_weapon_s"] = round(percentile([t for t in t_w if t < math.inf], 0.5), 2) if t_w else None
    out["spawn_to_stack_s"] = round(percentile([t for t in t_s if t < math.inf], 0.5), 2) if t_s else None
    out["spawn_to_spawn_s"] = round(percentile(t_sp, 0.5), 2) if t_sp else None
    out["spawn_to_spawn_max_nearest_s"] = round(max(t_sp), 2) if t_sp else None
    # the items one by one, for the mechanics (brief 19 §6): class, height over the base level, exits, and the times
    # between every two of the stack items, the guns and the armours, both ways (a route can be one way)
    keyed = [(c, o, nd) for c, o, nd in sites if nd is not None and nd in Rset
             and (c in MAJORS or c in ("item_armor_jacket", "item_adrenaline"))]
    ex_of = {nd: e for (c, o, nd), e in zip(majors, exits)}
    def above_around(nd):
        # brief 19 §6 «above the floor around»: over the lowest floor the walk reaches within 384 u of it
        x0, y0, z0 = g.nodes[nd]
        zs_ = [g.nodes[i][2] for i in R if abs(g.nodes[i][0] - x0) <= 384 and abs(g.nodes[i][1] - y0) <= 384]
        return round(z0 - min(zs_)) if zs_ else 0
    out["items"] = [{"class": c, "at": [round(v) for v in o], "height": round(g.nodes[nd][2] - base),
                     "above_around": above_around(nd), "exits": ex_of.get(nd)} for c, o, nd in keyed]
    tmat = []
    for c, o, nd in keyed:
        d = dist_from.get(nd) or dijkstra(g, [nd])
        tmat.append([round(d[x], 2) if d[x] < math.inf else None for _, _, x in keyed])
    out["item_times"] = tmat
    out["small_health_sites"] = sum(v for k, v in counts.items() if k in ("item_health", "item_health_small",
                                                                           "item_health_large"))
    # brief 19 §4 «Свет»: no dark place - the share of the floors' lightmap under 25 (people's maps 04.11: q2duel5
    # 0.01, ztn2dm3 0.06, q2duel1 0.08, omf 0.08, koldduel1 0.09, q2dm8 0.10, q2dm3 0.14, q2dm1 0.15)
    try:
        import mapgen_light_profile as lp
        lit = lp.lit_faces(Path(path))
        fl = [f for f in lit if f["kind"] == 1]
        tot = sum(f["n"] for f in fl)
        if tot:
            out["dark_floor_share"] = round(sum(1 for f in fl for t in f["tops"] if t < 25) / tot, 3)
            # brief 20 D3: and not burnt white - people's floors 04.11: none at 255 on eight maps, the median 61..86,
            # the top tenth from 130..196; the 3.40 duel 31 % at 255, median 140
            tops = sorted(t for f in fl for t in f["tops"])
            out["floor_burnt_share"] = round(sum(1 for t in tops if t >= 255) / len(tops), 3)
            out["floor_light_p50"] = tops[len(tops) // 2]
            out["floor_light_p90"] = tops[len(tops) * 9 // 10]
        sides = sorted(t for f in lit if f["kind"] == 0 for t in f["tops"])
        if sides:
            out["side_burnt_share"] = round(sum(1 for t in sides if t >= 255) / len(sides), 3)
    except Exception:  # noqa: BLE001 - an unlit map has no lightmap to read
        pass
    # brief 19 §4: what the parameters ask, measured on the map
    allp = len(g.nodes) + g.lava_points + g.slime_points
    out["water_share"] = round(sum(1 for i in range(len(g.nodes)) if g.water[i]) / max(1, allp), 3)
    out["lava_share"] = round(g.lava_points / max(1, allp), 3)
    out["slime_share"] = round(g.slime_points / max(1, allp), 3)
    # the doors one walks through; a door its buttons open (a powerup's, brief 21+) is counted apart
    out["doors"] = sum(1 for e in w.ents if e.get("classname") in ("func_door", "func_door_rotating")
                       and not e.get("targetname"))
    out["button_doors"] = sum(1 for e in w.ents if e.get("classname") in ("func_door", "func_door_rotating")
                              and e.get("targetname"))
    out["vertical_liquid_faces"], out["vertical_liquid_area"] = vertical_liquid_faces(Path(path))
    # the PO, 04.11 (mg_new_duel): «платформа ездит сквозь ступеньки и мерцает в полу» - a lift's plat sweeps from its
    # lowered place to its top; rock anywhere in that column (inset 4 u) is the plat riding through it
    through = []
    for e in w.ents:
        if e.get("classname") != "func_plat":
            continue
        mb = model_bounds(w, e)
        if not mb:
            continue
        mins, maxs = mb
        try:
            h = float(e.get("height") or 0) or (maxs[2] - mins[2])
        except ValueError:
            h = maxs[2] - mins[2]
        low_bottom, top = mins[2] - h, maxs[2]
        hit = 0
        x = mins[0] + 4
        while x <= maxs[0] - 4:
            y = mins[1] + 4
            while y <= maxs[1] - 4:
                z = low_bottom + 2
                while z <= top - 2:
                    if w.contents(x, y, z) & SOLID:
                        hit += 1
                    z += 8
                y += 16
            x += 16
        if hit:
            through.append(f"plat at {round((mins[0] + maxs[0]) / 2)} {round((mins[1] + maxs[1]) / 2)}: {hit} points of rock")
    out["lifts_through_rock"] = through
    # brief 21 D1, the PO 05.11 («лифт накладывается на другую конструкцию - второй лифт рядом … мерцает»): no two
    # movers whose swept volumes overlap - a plat's column from its lowered place to its top, a door's own box
    swept = []
    for e in w.ents:
        cls = e.get("classname", "")
        if cls not in ("func_plat", "func_door", "func_train", "func_door_rotating"):
            continue
        mb = model_bounds(w, e)
        if not mb:
            continue
        mins, maxs = list(mb[0]), list(mb[1])
        if cls == "func_plat":
            try:
                h = float(e.get("height") or 0) or (maxs[2] - mins[2])
            except ValueError:
                h = maxs[2] - mins[2]
            mins[2] -= h
        swept.append((cls, mins, maxs))
    overlap = []
    for i in range(len(swept)):
        for j in range(i + 1, len(swept)):
            a, b = swept[i], swept[j]
            if all(min(a[2][k], b[2][k]) - max(a[1][k], b[1][k]) > 1 for k in range(3)):
                overlap.append(f"{a[0]} at {round((a[1][0] + a[2][0]) / 2)} {round((a[1][1] + a[2][1]) / 2)} and "
                               f"{b[0]} at {round((b[1][0] + b[2][0]) / 2)} {round((b[1][1] + b[2][1]) / 2)}")
    out["movers_overlap"] = overlap
    # brief 21+ (the PO 05.11): each powerup's place - lit (a light within 128 u), housed (narrow: a span of 200 u or
    # less through it at 40 up), shut by a door a button opens (a func_door with a name within 192 u that a func_button
    # targets), on a pedestal (solid 4 under it, air 4 under the floor 40 u off it on some side)
    named = {e.get("targetname") for e in w.ents if e.get("classname") == "func_door" and e.get("targetname")}
    fired = {e.get("target") for e in w.ents if e.get("classname") == "func_button" and e.get("target")}
    lights_ = [fvec(e.get("origin", "")) for e in w.ents if e.get("classname") == "light"]
    pws = []
    for e in w.ents:
        cls = e.get("classname", "")
        if cls not in ("item_quad", "item_invulnerability", "item_health_mega", "item_armor_body", "item_power_shield"):
            continue
        o = fvec(e.get("origin", ""))
        p = (o[0], o[1], o[2] - 16 + 40)
        span = min(w.ray_length(p, (dx_, dy_, 0.0), 1024.0) + w.ray_length(p, (-dx_, -dy_, 0.0), 1024.0)
                   for dx_, dy_ in ((1, 0), (0, 1)))
        doors_ = []
        for e2 in w.ents:
            if e2.get("classname") == "func_door" and e2.get("targetname") in named:
                mb = model_bounds(w, e2)
                if mb and math.dist(((mb[0][0] + mb[1][0]) / 2, (mb[0][1] + mb[1][1]) / 2, (mb[0][2] + mb[1][2]) / 2), o) < 192:
                    doors_.append(e2["targetname"])
        pws.append({"class": cls, "lit": sum(1 for L in lights_ if math.dist(L, o) < 128),
                    "span": round(span), "door": bool(doors_), "button": any(t in fired for t in doors_),
                    "team": e.get("team") or ""})
    out["powerups"] = pws
    # brief 22 D1 (Fable 06.11): a powerup's button standing free on its wall - no wall piece of the map (a lamp post, a
    # pilaster, a decor panel, a chamfer) inside its box. Its model's box (the compiler pads it by 1) less 2 u each way,
    # a grid of 4 x 4 x 4 points in it, none in the world's solid. RED: 15 of 102 buttons in 3.46's plans
    buried = []
    for e in w.ents:
        if e.get("classname") != "func_button":
            continue
        mb = model_bounds(w, e)
        if not mb:
            continue
        lo = [mb[0][k] + 2 for k in range(3)]
        hi = [mb[1][k] - 2 for k in range(3)]
        if any(hi[k] <= lo[k] for k in range(3)):
            continue
        hit = 0
        for i in range(4):
            for j in range(4):
                for k in range(4):
                    x = lo[0] + (hi[0] - lo[0]) * i / 3
                    y = lo[1] + (hi[1] - lo[1]) * j / 3
                    z = lo[2] + (hi[2] - lo[2]) * k / 3
                    if w.contents(x, y, z) & SOLID:
                        hit += 1
        if hit:
            buried.append(f"button at {round((mb[0][0] + mb[1][0]) / 2)} {round((mb[0][1] + mb[1][1]) / 2)} "
                          f"{round(mb[0][2])}: {hit} of 64 points in a wall piece")
    out["buttons"] = sum(1 for e in w.ents if e.get("classname") == "func_button")
    out["buttons_buried"] = buried
    hang = hanging_brushes(w)
    out["hanging_brushes"] = len(hang)
    out["hanging_at"] = [list(h) for h in hang[:40]]
    # how the map looks next to people's (the PO, 05.11: «монохромное», «глаза выбеливают»): the colour of what it
    # wears, how bright its textures are, how bright a surface comes out on screen, the colour of its light
    try:
        import mapgen_people_style as people
        out["look"] = people.measure(Path(path), people.Colours(people.Game()))
    except Exception as e:  # noqa: BLE001 - a measure that cannot run is said, the rows then read it
        out["look"] = {"error": str(e)[:200]}
    # the PO, 04.11 (mg_new_ffa8): «телепорт и два места спавна рядом» - spawns within 192 u of a teleporter, its exit or
    # a jump pad, and of each other under 192
    marks = [fvec(e.get("origin", "")) for e in w.ents if e.get("classname") in ("misc_teleporter", "misc_teleporter_dest")]
    for e in w.ents:
        if e.get("classname") == "trigger_push":
            mb = model_bounds(w, e)
            if mb:
                marks.append(tuple((mb[0][k] + mb[1][k]) / 2 for k in range(3)))
    out["spawns_by_movers"] = sum(1 for sp in spawns for m in marks
                                  if math.hypot(sp[0] - m[0], sp[1] - m[1]) < 192 and abs(sp[2] - m[2]) < 96)
    # brief 35 (the PO 11.11, mg_new_91126): every teleporter disc and exit, jump pad and spawn point, for the map's rows
    out["mover_marks"] = mover_marks(w)
    # brief 36 (the PO 11.11, mg_new_91126: «у двери мерцает текстура при её движении»): a door's faces on a wall's plane
    out["door_planes"] = door_planes(path)
    out["deadly_volumes"] = len(hurt)
    # spawns seen at once from another within 300 u (eye to eye)
    sp_eyes = [(s[0], s[1], s[2] + 22) for s in spawns]
    out["spawn_pairs_seen_under_300"] = sum(1 for i in range(len(sp_eyes)) for j in range(i + 1, len(sp_eyes))
                                            if math.dist(sp_eyes[i], sp_eyes[j]) < 300
                                            and not w.blocked(sp_eyes[i], sp_eyes[j], BLOCK_SIGHT))
    # brief 19 §6, the movers' mechanics on the map
    spawn_src = [s for s in spawn_nodes if s is not None]
    no_plat = reach_without(g, spawn_src, "plat")
    # places a player reaches from a spawn and cannot leave for any spawn (a deadly volume's points are not counted:
    # dying there is its way out) - 04.11 mg_new_ffa8: half a pit beside a bridge with no steps out
    R = reach_without(g, spawn_src, "-")
    in_hurt = {i for i in R if any(a[0] <= g.nodes[i][0] <= b[0] and a[1] <= g.nodes[i][1] <= b[1]
                                   and a[2] - 64 <= g.nodes[i][2] <= b[2] for a, b in hurt)}
    rev = [[] for _ in g.nodes]
    for i, es in enumerate(g.edges):
        for j, _c in es:
            rev[j].append(i)
    back = set(spawn_src)
    todo = list(back)
    while todo:
        i = todo.pop()
        for j in rev[i]:
            if j not in back:
                back.add(j)
                todo.append(j)
    trapped = [i for i in R if i not in back and i not in in_hurt]
    out["trapped_points"] = len(trapped)
    # where they are (brief 20 D2: an asked dead end is told from a trap elsewhere by its room's box)
    out["trapped_at"] = [[round(c) for c in g.nodes[i]] for i in trapped[:4000]]
    out["majors_lift_only"] = sorted(c for c, o, nd in majors if nd not in no_plat)
    out["majors_by_ladder"] = sorted(c for c, o, nd in majors for (lx, ly, lz) in g.ladder_tops
                                     if math.hypot(g.nodes[nd][0] - lx, g.nodes[nd][1] - ly) <= 256
                                     and abs(g.nodes[nd][2] - lz) <= 48)
    over = 0
    for path in g.push_paths:
        hit = False
        for (px, py, pz) in path[::4]:
            if any(a[0] <= px <= b[0] and a[1] <= py <= b[1] and a[2] - 64 <= pz for a, b in hurt):
                hit = True
                break
            for dz in range(32, 640, 32):
                cz = w.contents(px, py, pz - dz)
                if cz & (LAVA | SLIME):
                    hit = True
                    break
                if cz & SOLID:
                    break
            if hit:
                break
        over += 1 if hit else 0
    out["pads_over_deadly"] = over
    armour = [nd for c, o, nd in sites if nd is not None and c in ("item_armor_combat", "item_armor_jacket", "item_armor_body")]
    health = [nd for c, o, nd in sites if nd is not None and c.startswith("item_health")]
    ends = []
    for (bn, borg, byaw) in g.tele_dests:
        d = dijkstra(g, [bn])
        ta = min((d[x] for x in armour), default=math.inf)
        th = min((d[x] for x in health), default=math.inf)
        # what the exit faces: a key gun within 400 u, within 45 degrees of its yaw
        faces = []
        for c, o, nd in sites:
            if c in ("weapon_chaingun", "weapon_railgun"):
                dx, dy = o[0] - borg[0], o[1] - borg[1]
                dist = math.hypot(dx, dy)
                ang = math.degrees(math.atan2(dy, dx)) - byaw
                ang = (ang + 180) % 360 - 180
                if dist <= 400 and abs(ang) <= 45:
                    faces.append(c)
        ends.append({"armour_s": round(ta, 2) if ta < math.inf else None,
                     "health_s": round(th, 2) if th < math.inf else None, "faces": faces})
    out["tele_ends"] = ends
    # sky straight up over standing places: the ray up ends in a brush with a sky side
    sky_boxes = sky_brush_bounds(w)
    if sky_boxes:
        n_sky = 0
        pts = sample[:400]
        for i in pts:
            x, y, z = g.nodes[i]
            up = w.ray_length((x, y, z + 2), (0.0, 0.0, 1.0), 4096.0, SOLID | WINDOW)
            hz = z + 2 + up + 2
            if any(a[0] - 1 <= x <= b[0] + 1 and a[1] - 1 <= y <= b[1] + 1 and a[2] - 1 <= hz <= b[2] + 1
                   for a, b in sky_boxes):
                n_sky += 1
        out["sky_share"] = round(n_sky / max(1, len(pts)), 3)
    else:
        out["sky_share"] = 0.0
    if doors is not None:
        out["dead_ends"] = dead_ends(g, R, doors)
    return out


def dead_ends(g: Graph, R, doors: list) -> list:
    """Brief 21 D2, on the map's walk: a doorway closed (its opening's nodes, half its width and 24 more round its
    middle, 64 up and down from its sill) - is there floor, a room's worth (24 points of 32 u, 0.025 M u²), that can
    then no longer reach the map's far side, nor be reached from it? That floor was reachable through this doorway
    only: a dead end. `doors` are the skeleton's (x, y, z, half width, what) in map units; a doorway marked asked
    (the dead-end stack's) is not closed. Returns [(what, points)] of the dead ends found."""
    rs = set(R)
    rev = [[] for _ in g.nodes]
    for i, es in enumerate(g.edges):
        for j, _c in es:
            rev[j].append(i)

    def reach(src, adj, blocked):
        seen = set(s_ for s_ in src if s_ not in blocked)
        todo = list(seen)
        while todo:
            i = todo.pop()
            for j in adj(i):
                if j in rs and j not in seen and j not in blocked:
                    seen.add(j)
                    todo.append(j)
        return seen
    # joined either way: a room one drops into and walks out of is on a loop, not a dead end
    both = lambda i: [j for j, _c in g.edges[i]] + rev[i]
    out = []
    # with every doorway open, one piece: a part with its own spawns that nothing joins to the rest is reachable «from
    # a spawn» and passes the traps row (05.11: an FFA-8 candidate's bay, 344 points, four spawns)
    if R:
        whole = reach([next(iter(rs))], both, set())
        if len(whole) < len(rs):
            rest_ = rs - whole
            out.append(("cut off from the rest", min(len(whole), len(rest_))))
    for (x, y, z, half, what) in doors:
        blocked = {i for i in rs if math.hypot(g.nodes[i][0] - x, g.nodes[i][1] - y) <= half + 24
                   and abs(g.nodes[i][2] - z) <= 64}
        if not blocked:
            continue
        far = max((i for i in rs if i not in blocked), key=lambda i: math.hypot(g.nodes[i][0] - x, g.nodes[i][1] - y),
                  default=None)
        if far is None:
            continue
        # the far side: what is joined to the farthest point with the doorway closed; the larger of the two parts is
        # the map, the smaller the dead end
        main = reach([far], both, blocked)
        others = [i for i in rs if i not in blocked and i not in main]
        if others:
            other = reach([others[0]], both, blocked)
            if len(other) > len(main):
                main = other
        lost = [i for i in rs if i not in blocked and i not in main]
        # the lost floor near the doorway on its own is the doorway's own sill or a step: a room's worth counts
        if len(lost) >= 24:
            out.append((what, len(lost)))
    return out


def vertical_liquid_faces(path: Path) -> tuple[int, int]:
    """(count, area) of drawn liquid faces within 30 degrees of vertical: the compiler draws no face between liquid
    and rock, so such a face is water (lava, slime) meeting air - liquid standing above a floor (the PO, 04.11:
    «вода вылезла над краем поверхности и торчит как желе»)."""
    import struct as _s
    d = Path(path).read_bytes()

    def lump(i):
        return _s.unpack_from("<ii", d, 8 + i * 8)
    po, pn = lump(1)
    planes = [_s.unpack_from("<4f", d, po + i * 20) for i in range(pn // 20)]
    to, tn = lump(5)
    flags = [_s.unpack_from("<i", d, to + i * 76 + 32)[0] for i in range(tn // 76)]
    vo, vn = lump(2)
    verts = [_s.unpack_from("<3f", d, vo + i * 12) for i in range(vn // 12)]
    eo, en = lump(11)
    edges = [_s.unpack_from("<2H", d, eo + i * 4) for i in range(en // 4)]
    so, sn = lump(12)
    se = _s.unpack_from(f"<{sn // 4}i", d, so)
    fo, fn = lump(6)
    count = area = 0
    for i in range(fn // 20):
        pnum, side, fe, ne, ti = _s.unpack_from("<HhiHh", d, fo + i * 20)
        if not (0 <= ti < len(flags)) or not flags[ti] & 0x8 or flags[ti] & 0x4:
            continue
        if abs(planes[pnum][2]) >= 0.5:
            continue
        pts = [verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]] for e in (se[fe + k] for k in range(ne))]
        a = 0.0
        for k in range(1, len(pts) - 1):
            u = [pts[k][j] - pts[0][j] for j in range(3)]
            v = [pts[k + 1][j] - pts[0][j] for j in range(3)]
            cx = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            a += 0.5 * math.sqrt(sum(c * c for c in cx))
        count += 1
        area += int(a)
    return count, area


MOVER_CLASSES = ("func_door", "func_plat", "func_train", "func_button", "func_door_rotating")


def door_planes(path: Path, classes: tuple = ("func_door",)) -> list:
    """Brief 36 (the PO 11.11, mg_new_91126 on 3.61: «у двери мерцает текстура при её движении»): for every brush mover
    of `classes`, the world's drawn faces lying on the planes of its upright faces inside the box its travel sweeps -
    two faces in one plane are drawn in turn, the flicker. [(class, mins, maxs, travel, [(texture, axis, side, area,
    z_lo, z_hi)])]. A door's travel: up its height less its lip (angle -1), down alike (-2), else none counted; a plat's
    its height; a train's and a button's none (their place only)."""
    import re as _re
    import struct as _s
    d = Path(path).read_bytes()

    def lump(i):
        return _s.unpack_from("<ii", d, 8 + i * 8)
    po, pn = lump(1)
    planes = [_s.unpack_from("<4f", d, po + i * 20) for i in range(pn // 20)]
    to, tn = lump(5)
    tex = [(_s.unpack_from("<i", d, to + i * 76 + 32)[0], d[to + i * 76 + 40:to + i * 76 + 72].split(b"\0")[0].decode("latin-1"))
           for i in range(tn // 76)]
    vo, vn = lump(2)
    verts = [_s.unpack_from("<3f", d, vo + i * 12) for i in range(vn // 12)]
    eo, en = lump(11)
    edges = [_s.unpack_from("<2H", d, eo + i * 4) for i in range(en // 4)]
    so, sn = lump(12)
    se = _s.unpack_from(f"<{sn // 4}i", d, so)
    fo, fn = lump(6)
    mo, mn = lump(13)
    models = [_s.unpack_from("<9f3i", d, mo + i * 48) for i in range(mn // 48)]
    eno, enl = lump(0)
    text = d[eno:eno + enl].split(b"\0")[0].decode("latin-1")
    ents = [dict(_re.findall(r'"([^"]*)"\s+"([^"]*)"', blk)) for blk in _re.findall(r"\{([^{}]*)\}", text)]
    # the world's drawn upright faces, by the way they face: (axis, +1|-1, coordinate) -> [(lo, hi, texture)]. Only a face
    # turned the same way as the mover's is drawn over it - one turned the other way is its back (a jamb against a
    # door's end, a wall against a button's back) and is never seen with it
    world = {}
    first, count = models[0][10], models[0][11]
    for i in range(first, first + count):
        pnum, side, fe, ne, ti = _s.unpack_from("<HhiHh", d, fo + i * 20)
        if not (0 <= ti < len(tex)) or tex[ti][0] & (0x80 | 0x4):          # nodraw, sky
            continue
        n = planes[pnum]
        ax = 0 if abs(n[0]) > 0.999 else 1 if abs(n[1]) > 0.999 else None
        if ax is None:
            continue
        facing = (1 if n[ax] > 0 else -1) * (-1 if side else 1)
        pts = [verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]] for e in (se[fe + k] for k in range(ne))]
        lo = [min(p[j] for p in pts) for j in range(3)]
        hi = [max(p[j] for p in pts) for j in range(3)]
        world.setdefault((ax, facing, round(lo[ax] * 8) / 8), []).append((lo, hi, tex[ti][1]))
    out = []
    for e in ents:
        cls = e.get("classname", "")
        if cls not in classes or not e.get("model", "").startswith("*"):
            continue
        m = models[int(e["model"][1:])]
        lo, hi = list(m[0:3]), list(m[3:6])
        travel = 0.0
        if cls == "func_door" and e.get("angle") in ("-1", "-2"):
            travel = (hi[2] - lo[2]) - float(e.get("lip", 8) or 8)
        elif cls == "func_plat":
            travel = float(e.get("height", 0) or 0) or (hi[2] - lo[2]) - 8
        z0, z1 = (lo[2], hi[2] + travel) if e.get("angle") != "-2" and cls != "func_plat" else (lo[2] - travel, hi[2])
        if cls == "func_plat":
            z0, z1 = lo[2] - travel, hi[2]
        hits = []
        for ax in (0, 1):
            wide = 1 - ax
            for side, facing in ((lo[ax], -1), (hi[ax], 1)):
                for (flo, fhi, t) in world.get((ax, facing, round(side * 8) / 8), []):
                    ow = min(fhi[wide], hi[wide]) - max(flo[wide], lo[wide])
                    oz = min(fhi[2], z1) - max(flo[2], z0)
                    if ow > 0.5 and oz > 0.5:
                        hits.append((t, ax, round(side, 1), round(ow * oz), round(max(flo[2], z0)), round(min(fhi[2], z1))))
        out.append((cls, tuple(round(v, 1) for v in lo), tuple(round(v, 1) for v in hi), travel, hits))
    return out


def sky_share_of(path: Path, seed: int = 1) -> float:
    """The share of standing places with sky straight up - alone, for a style taken from maps (brief 19 §4: the sky
    «by style»)."""
    w = World(path)
    g = build_graph(w, [])
    boxes = sky_brush_bounds(w)
    if not boxes or not g.nodes:
        return 0.0
    rnd = random.Random(seed)
    pts = rnd.sample(range(len(g.nodes)), min(400, len(g.nodes)))
    n = 0
    for i in pts:
        x, y, z = g.nodes[i]
        up = w.ray_length((x, y, z + 2), (0.0, 0.0, 1.0), 4096.0, SOLID | WINDOW)
        hz = z + 2 + up + 2
        if any(a[0] - 1 <= x <= b[0] + 1 and a[1] - 1 <= y <= b[1] + 1 and a[2] - 1 <= hz <= b[2] + 1 for a, b in boxes):
            n += 1
    return round(n / len(pts), 3)


def reach_without(g: Graph, sources, kind: str) -> set:
    """What the walk reaches from `sources` when no edge of `kind` may be taken (a lift's ride, a ladder's climb)."""
    seen = set(s for s in sources if s is not None)
    todo = list(seen)
    while todo:
        i = todo.pop()
        for j, _c in g.edges[i]:
            if j in seen or g.edge_kind.get((i, j)) == kind:
                continue
            seen.add(j)
            todo.append(j)
    return seen


def stacked_points(g: Graph, R) -> int:
    """How many of the reachable dry standing points have another reachable dry one 128 or more over or under them."""
    rs = set(R)
    n = 0
    for col in g.at.values():
        zs = [g.nodes[i][2] for i in col if i in rs and not g.water[i]]
        if len(zs) < 2:
            continue
        zs.sort()
        for k, z in enumerate(zs):
            if any(abs(z - o) >= 128 for o in zs):
                n += 1
    return n


def mover_marks(w: "World") -> list:
    """Brief 35: [(kind, x, y, z, pair)] of the map's teleporter discs («disc»: misc_teleporter, or a trigger_teleport's
    middle), their exits («exit»: misc_teleporter_dest), jump pads («pad»: a trigger_push's middle) and spawn points
    («spawn»); `pair` ties a disc to its exit (the disc's target), else None."""
    out = []
    dests = {e.get("targetname"): e for e in w.ents if e.get("classname") == "misc_teleporter_dest"}
    for e in w.ents:
        cls = e.get("classname", "")
        if cls == "misc_teleporter":
            o = fvec(e.get("origin", ""))
            out.append(("disc", o[0], o[1], o[2], e.get("target")))
        elif cls == "trigger_teleport":
            mb = model_bounds(w, e)
            if mb:
                out.append(("disc", (mb[0][0] + mb[1][0]) / 2, (mb[0][1] + mb[1][1]) / 2, mb[0][2], e.get("target")))
        elif cls == "misc_teleporter_dest":
            o = fvec(e.get("origin", ""))
            out.append(("exit", o[0], o[1], o[2], e.get("targetname")))
        elif cls == "trigger_push":
            mb = model_bounds(w, e)
            if mb:
                out.append(("pad", (mb[0][0] + mb[1][0]) / 2, (mb[0][1] + mb[1][1]) / 2, mb[0][2], None))
        elif cls == "info_player_deathmatch":
            o = fvec(e.get("origin", ""))
            out.append(("spawn", o[0], o[1], o[2], None))
    _ = dests
    return out


def hanging_brushes(w: World) -> list:
    """Brief 20 D4, the PO 04.11 («много подобных висящих в воздухе архитектурных штучек. В картах которые делают люди
    такого нет», his pictures of the 3.36 maps: panels and lamp boxes standing out of a wall half way up, a lamp on a
    rod): a solid brush with air under it (nothing within 64 below most of its underside) that is held by at most one
    side and not by the ceiling - a shelf out of a wall - or that hangs from the ceiling with no wall beside it, taller
    than a panel set into the ceiling and small (a lamp on a rod). A skirting stands on the floor, a cornice and a
    beam touch the ceiling, a pilaster runs floor to ceiling, a lintel rests on its jambs: none of them hang.
    Returns [(x, y, z, why)] - the brushes' middles."""
    b = w.bsp
    out = []
    # the world's own brushes only: a lift's plat is stored at its top, over its shaft, and lowered by the game at
    # its start (04.11: the two «slabs in the air» on a trial duel were its lifts)
    world = set()
    todo = [b.models[0].headnode if b.models else 0]
    while todo:
        n = todo.pop()
        if n < 0:
            leaf = b.leafs[-1 - n]
            world.update(b.leafbrushes[i] for i in range(leaf.firstleafbrush, leaf.firstleafbrush + leaf.numleafbrushes))
            continue
        todo.extend(b.nodes[n].children)
    for bi, br in enumerate(b.brushes):
        if bi not in world or not (br.contents & SOLID):
            continue
        mins, maxs = [-1e9] * 3, [1e9] * 3
        for s in range(br.firstside, br.firstside + br.numsides):
            pl = b.planes[b.brushsides[s].planenum]
            for a in range(3):
                if abs(pl.normal[a]) > 0.999:
                    if pl.normal[a] > 0:
                        maxs[a] = min(maxs[a], pl.dist)
                    else:
                        mins[a] = max(mins[a], -pl.dist)
        if not all(abs(v) < 1e8 for v in mins + maxs):
            continue
        dx, dy, dz = maxs[0] - mins[0], maxs[1] - mins[1], maxs[2] - mins[2]
        if dz < 2 or max(dx, dy) > 1024 or (min(dx, dy) > 256 and dz > 256):
            continue

        def grid(lo, hi, n=4):
            if hi - lo <= 4:
                return [(lo + hi) / 2]
            return [lo + 2 + (hi - lo - 4) * k / (n - 1) for k in range(n)]
        xs, ys, zs = grid(mins[0], maxs[0]), grid(mins[1], maxs[1]), grid(mins[2], maxs[2], 3)
        under = [(x, y) for x in xs for y in ys]
        held_below = sum(1 for (x, y) in under
                         if any(w.contents(x, y, mins[2] - d) & SOLID for d in (4, 24, 48, 64)))
        if held_below >= len(under) / 2:
            continue
        top = sum(1 for (x, y) in under if w.contents(x, y, maxs[2] + 2) & SOLID) >= len(under) / 2
        sides = 0
        for (axis, at, along) in ((0, mins[0] - 2, ys), (0, maxs[0] + 2, ys), (1, mins[1] - 2, xs), (1, maxs[1] + 2, xs)):
            pts = [(at, u, z) if axis == 0 else (u, at, z) for u in along for z in zs]
            if sum(1 for p in pts if w.contents(*p) & SOLID) >= len(pts) / 2:
                sides += 1
        mid = tuple(round((mins[k] + maxs[k]) / 2) for k in range(3))
        if top:
            if dz > 8 and max(dx, dy) <= 64 and sides == 0:
                out.append((*mid, "hangs from the ceiling"))
        elif sides <= 1:
            out.append((*mid, "stands out of a wall" if sides else "in the air"))
    return out


def sky_brush_bounds(w: World) -> list:
    """The axial bounds of the world's brushes that carry a sky side (a sky box, as our maps make them)."""
    b = w.bsp
    out = []
    for br in b.brushes:
        sky = any(b.texinfo[b.brushsides[s].texinfo].flags & 4 for s in range(br.firstside, br.firstside + br.numsides)
                  if 0 <= b.brushsides[s].texinfo < len(b.texinfo))
        if not sky:
            continue
        mins, maxs = [-1e9] * 3, [1e9] * 3
        for s in range(br.firstside, br.firstside + br.numsides):
            pl = b.planes[b.brushsides[s].planenum]
            for a in range(3):
                if abs(pl.normal[a]) > 0.999:
                    if pl.normal[a] > 0:
                        maxs[a] = min(maxs[a], pl.dist)
                    else:
                        mins[a] = max(mins[a], -pl.dist)
        if all(abs(v) < 1e8 for v in mins + maxs):
            out.append((mins, maxs))
    return out


def distinct_lines(pairs: list) -> list:
    """Long sight lines as distinct corridors of sight: segments within 25 degrees of each other whose middles lie
    within 384 u of the other's line, overlapping along it, are one line (brief 19 §4 «Длинные линии прострела»).
    Calibrated 04.11 on people's maps: duel 2..3 (ztn2dm3 3, q2duel5 2, koldduel1 2, q2duel1 3; omf 7), FFA 4..8
    (q2dm3 4, q2dm8 5, q2dm1 8)."""
    lines = []
    for a, b in pairs:
        d = (b[0] - a[0], b[1] - a[1])
        L = math.hypot(*d) or 1.0
        u = (d[0] / L, d[1] / L)
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        for ln in lines:
            cu = abs(u[0] * ln["u"][0] + u[1] * ln["u"][1])
            if cu < math.cos(math.radians(25)):
                continue
            off = abs((m[0] - ln["m"][0]) * ln["u"][1] - (m[1] - ln["m"][1]) * ln["u"][0])
            along = (m[0] - ln["m"][0]) * ln["u"][0] + (m[1] - ln["m"][1]) * ln["u"][1]
            if off <= 384 and abs(along) <= (ln["len"] + L) / 2:
                break
        else:
            lines.append({"u": u, "m": m, "len": L, "a": a, "b": b})
    return lines


def groups_of(g: Graph, ring) -> int:
    """How many separate groups the points of a ring make (8-neighbours within two cells and 64 in height)."""
    left = set(ring)
    cells = {}
    for i in ring:
        x, y, z = g.nodes[i]
        cells.setdefault((int(x // GRID), int(y // GRID)), []).append(i)
    count = 0
    while left:
        count += 1
        stack = [left.pop()]
        while stack:
            i = stack.pop()
            x, y, z = g.nodes[i]
            cx, cy = int(x // GRID), int(y // GRID)
            for dx_ in range(-2, 3):
                for dy_ in range(-2, 3):
                    for j in cells.get((cx + dx_, cy + dy_), ()):
                        if j in left and abs(g.nodes[j][2] - z) <= 64:
                            left.discard(j)
                            stack.append(j)
    return count


def detour(g: Graph, a, b) -> tuple[float, float]:
    """The route a->b, and its time with a 96-unit disc closed at its half-way point divided by the route's own."""
    prev = [-1] * len(g.nodes)
    da = dijkstra(g, [a], None, prev)
    t = da[b]
    if t == math.inf or t <= 0:
        return t, math.inf
    half = b
    while prev[half] >= 0 and da[half] > t / 2:
        half = prev[half]
    hx, hy, hz = g.nodes[half]
    blocked = {i for i, (x, y, z) in enumerate(g.nodes) if math.hypot(x - hx, y - hy) <= 96 and abs(z - hz) <= 64}
    if a in blocked or b in blocked:
        return t, 1.0
    d2 = dijkstra(g, [a], blocked)
    return t, (d2[b] / t if d2[b] < math.inf else math.inf)


CALIBRATION = {
    # the research's own numbers (walk M u², or None where the research marked the graph partial)
    "q2duel5": 1.1, "ztn2dm3": 1.8, "omf": 2.7, "q2duel1": 1.6, "pro_q2t4": 3.1, "q2rdm2": 2.3, "trdm01a": 3.1,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--calibrate", action="store_true")
    a = ap.parse_args()
    if a.calibrate:
        maps = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
        for name, want in CALIBRATION.items():
            r = survey(maps / f"{name}.bsp", a.seed)
            print(f"{name:10s} walk {r.get('walk_area_mu2')} (research {want})  levels {r.get('levels')} "
                  f"{r.get('level_heights')}  span {r.get('vertical_span')}  width {r.get('width_median')} "
                  f"corr/med/open {r.get('share_corridor')}/{r.get('share_medium')}/{r.get('share_open')}  "
                  f"vis {r.get('visible_pairs')} >1000 {r.get('visible_over_1000_of_visible')}  "
                  f"exits {r.get('exits_median')}  alt {r.get('pairs_with_alternative')}  "
                  f"sp->w {r.get('spawn_to_weapon_s')} sp->st {r.get('spawn_to_stack_s')} "
                  f"sp->sp {r.get('spawn_to_spawn_s')} mm {r.get('major_major_median_s')}", flush=True)
        return 0
    if not a.map:
        ap.print_help()
        return 2
    r = survey(a.map, a.seed)
    print(json.dumps(r, indent=None if a.json else 1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
