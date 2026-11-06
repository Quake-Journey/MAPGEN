r"""What makes an «open space» map (the PO 06.11: q2_q3dm17 - «космическая карта с кучей мест для падения, воздушная, с
джампадами и отдельными местами в воздухе, куда можно добраться через jump pads»; pro_q2t4 - «не типичная архитектура
для q2»), measured from its compiled BSP on the same floor graph as `mapgen_map_survey` (people's maps' method).

Beside the survey's own numbers (floor, levels, widths, sky, sight lines, majors at height), per map:
  * islands: the floor's strongly connected parts when only walking, jumping, gap jumps and drops are allowed (no pad,
    teleporter, lift or ladder) - each its size, height, and how it is reached (a pad, a teleporter, only by dropping
    onto it, or walking from a spawn);
  * the edge over the void: each reachable floor point's four sides - more floor, a wall, a drop onto floor below, or
    a fall with no standing place under it (out of the world, into a `trigger_hurt`, lava or slime) - and the share
    of the floor's outline that is a deadly fall, and of the floor that stands within 64 of one;
  * the pads: each `trigger_push` - its speed, its flight (across, up, time), from which island to which;
  * the teleporters, the lifts, the kill volumes, the gravity and the sky;
  * the major items: on which island each lies, and whether that island is reached only by a pad or a teleporter.

    python tools/mapgen_space_survey.py MAP.bsp [MAP.bsp ...] [--json OUT.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_map_survey as sv  # noqa: E402

GRID = sv.GRID
WALKING = {"walk", "jump", "drop", "gap", "swim"}


def sccs(n: int, edges) -> list[int]:
    """Strongly connected components (iterative Tarjan) over the walking edges; a component id per node."""
    index = [-1] * n
    low = [0] * n
    on = [False] * n
    comp = [-1] * n
    stack: list[int] = []
    counter = 0
    ncomp = 0
    for root in range(n):
        if index[root] != -1:
            continue
        work = [(root, 0)]
        while work:
            v, i = work[-1]
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on[v] = True
            nbrs = edges[v]
            if i < len(nbrs):
                work[-1] = (v, i + 1)
                u = nbrs[i]
                if index[u] == -1:
                    work.append((u, 0))
                elif on[u]:
                    low[v] = min(low[v], index[u])
                continue
            work.pop()
            if work:
                p = work[-1][0]
                low[p] = min(low[p], low[v])
            if low[v] == index[v]:
                while True:
                    u = stack.pop()
                    on[u] = False
                    comp[u] = ncomp
                    if u == v:
                        break
                ncomp += 1
    return comp


def analyse(path: Path) -> dict:
    out = space_part(path)
    base = sv.survey(path)
    keep = ("walk_area_mu2", "footprint", "levels", "vertical_span", "stacked_share", "sky_share", "share_corridor",
            "share_medium", "share_open", "long_lines", "majors_at_height", "spawns")
    out["survey"] = {k: base.get(k) for k in keep if k in base}
    return out


def space_part(path: Path) -> dict:
    """The open space's own measure (brief 25 A3: the judge of a space candidate calls it beside the people's survey)."""
    w = sv.World(path)
    hurt = [mb for e in w.ents if e.get("classname") == "trigger_hurt" and (mb := sv.model_bounds(w, e))]
    g = sv.build_graph(w, hurt)
    sv.link_graph(g, w)
    mv = sv.movers(g, w)
    n = len(g.nodes)
    spawns = [sv.fvec(e.get("origin", "")) for e in w.ents if e.get("classname") == "info_player_deathmatch"]
    spawn_nodes = [s for s in (g.nearest(p, below=96) for p in spawns) if s is not None]
    reach = sv.dijkstra(g, spawn_nodes)
    R = [i for i in range(n) if reach[i] < math.inf]
    Rset = set(R)

    # islands: walking only
    walk_edges = [[b for (b, _c) in g.edges[a] if g.edge_kind.get((a, b)) is None] for a in range(n)]
    comp = sccs(n, walk_edges)
    size: dict[int, int] = {}
    for i in R:
        size[comp[i]] = size.get(comp[i], 0) + 1
    # how each island is entered: the kinds of edges coming into it from another island
    into: dict[int, set] = {}
    for a in R:
        for (b, _c) in g.edges[a]:
            if b in Rset and comp[a] != comp[b]:
                into.setdefault(comp[b], set()).add(g.edge_kind.get((a, b), "drop/walk"))
    spawn_islands = {comp[s] for s in spawn_nodes}
    big = sorted((c for c in size if size[c] * GRID * GRID >= 0.02e6), key=lambda c: -size[c])
    islands = []
    for c in big:
        pts = [g.nodes[i] for i in R if comp[i] == c]
        zs = sorted(p[2] for p in pts)
        islands.append({
            "area_mu2": round(size[c] * GRID * GRID / 1e6, 3),
            "z": round(zs[len(zs) // 2]),
            "spawn": c in spawn_islands,
            "entered_by": sorted(into.get(c, set())),
        })
    pad_only = [x for x in islands if x["entered_by"] and set(x["entered_by"]) <= {"push", "teleport"}]
    drop_only = [x for x in islands if x["entered_by"] == ["drop/walk"] and not x["spawn"]]

    # the edge over the void: each reachable point's four sides
    def cell_nodes(x, y):
        return g.at.get((int(math.floor(x / GRID)), int(math.floor(y / GRID))), [])

    sides = {"floor": 0, "wall": 0, "drop": 0, "void": 0}
    void_points = set()
    for i in R:
        x, y, z = g.nodes[i]
        for dx, dy in ((GRID, 0), (-GRID, 0), (0, GRID), (0, -GRID)):
            nx, ny = x + dx, y + dy
            here = cell_nodes(nx, ny)
            if any(abs(g.nodes[j][2] - z) <= 20 for j in here):
                sides["floor"] += 1
            elif w.contents_all(nx, ny, z + 28.0) & sv.BLOCK_BODY:
                sides["wall"] += 1
            elif any(g.nodes[j][2] < z - 20 for j in here):
                sides["drop"] += 1
            else:
                sides["void"] += 1
                void_points.add(i)
    outline = sides["wall"] + sides["drop"] + sides["void"]
    near_void = 0
    vp = [g.nodes[i] for i in void_points]
    vcells: dict[tuple[int, int], list] = {}
    for p in vp:
        vcells.setdefault((int(p[0] // 64), int(p[1] // 64)), []).append(p)
    for i in R:
        x, y, z = g.nodes[i]
        cx, cy = int(x // 64), int(y // 64)
        if any(abs(q[2] - z) <= 64 and (q[0] - x) ** 2 + (q[1] - y) ** 2 <= 64 * 64
               for ix in (cx - 1, cx, cx + 1) for iy in (cy - 1, cy, cy + 1) for q in vcells.get((ix, iy), [])):
            near_void += 1

    # the pads: their flights
    pads = []
    for path_ in g.push_paths:
        if not path_:
            continue
        a, b = path_[0], path_[-1]
        top = max(p[2] for p in path_)
        pads.append({"from_z": round(a[2]), "to_z": round(b[2]), "across": round(math.hypot(b[0] - a[0], b[1] - a[1])),
                     "apex_over_start": round(top - a[2]), "points": len(path_)})
    push_ents = [e for e in w.ents if e.get("classname") == "trigger_push"]
    speeds = sorted({e.get("speed", "1000") for e in push_ents})

    # major items: their island and how it is reached
    majors = []
    for e in w.ents:
        cls = e.get("classname", "")
        if cls in sv.MAJORS or cls.startswith("item_power") or cls == "item_adrenaline":
            i = g.nearest(sv.fvec(e.get("origin", "")))
            if i is None or i not in Rset:
                majors.append({"item": cls, "island": None})
                continue
            c = comp[i]
            majors.append({"item": cls, "z": round(g.nodes[i][2]), "island_mu2": round(size.get(c, 0) * GRID * GRID / 1e6, 3),
                           "reached_by": "spawn island" if c in spawn_islands else ",".join(sorted(into.get(c, set()))) or "-",
                           "next_to_void": i in void_points})
    ws = w.ents[0] if w.ents else {}
    kill = []
    for (a, b) in hurt:
        kill.append([round(b[0] - a[0]), round(b[1] - a[1]), round(b[2] - a[2]), round(a[2])])
    return {
        "map": path.stem,
        "gravity": w.gravity, "sky": ws.get("sky", ""),
        "movers": mv, "pad_speeds": speeds, "kill_volumes": kill,
        "islands": {"count_over_0.02mu2": len(islands), "reached_only_by_pad_or_teleport": len(pad_only),
                    "reached_only_by_dropping": len(drop_only), "list": islands[:24]},
        "outline": {k: v for k, v in sides.items() if k != "floor"},
        "outline_void_share": round(sides["void"] / max(1, outline), 3),
        "floor_within_64_of_void": round(near_void / max(1, len(R)), 3),
        "pads": pads,
        "majors": majors,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    out = [analyse(p) for p in a.maps]
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if a.json:
        a.json.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
