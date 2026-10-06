#!/usr/bin/env python3
"""Independent computation of the per-map feature vector.

Written from the definitions in `inc/common/mapgen_features.h` rather than from
the C: articulation points and bridges by depth-first lowpoint, the cyclomatic
number as E - V + C, cover as the share of sampled stance pairs that cannot see
each other, and entity binding as the nearest stance inside a stated radius.

Every value is an integer here too. Nothing is sampled randomly - the pairs are
chosen by the same index arithmetic the definition specifies, because a feature
chosen by a generator is not a feature two runs can compare.

Slow: it re-uses the Python space build and the Python tracer, so the guard
runs it on the small maps only.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_space_oracle as space_oracle  # noqa: E402
import mapgen_trace_oracle as tracer  # noqa: E402
import mapgen_wiring_oracle as wiring_oracle  # noqa: E402

VIEWHEIGHT = 22
MAX_OBSERVERS = 512
PARTNERS = 32
BIND_RADIUS_XY = 64
BIND_RADIUS_Z = 96
HEIGHT_BAND = 64
CLEARANCE_PROBE = 512

MASK_SIGHT = 0x1 | 0x2          # solid | window

WALK, STEP, JUMP, FALL, SWIM = range(5)
KIND_NAMES = ("walk", "step", "jump", "fall", "swim")
JOINING = (WALK, STEP, SWIM)

SURF_SKY = 0x4
LIGHT_COLOURS = 4


def _pack_colour(text: str) -> int:
    """One `_color` value as 0xRRGGBB, or 0 if it is not one.

    The corpus writes both conventions and they are told apart the only way
    available: if every component is at most 1, it is the 0..1 form. That is
    not a guess about intent, it is what the two formats look like.
    """
    parts = text.split()
    if len(parts) < 3:
        return 0
    try:
        values = [float(parts[i]) for i in range(3)]
    except ValueError:
        return 0

    packed = 0
    unit_scale = all(int(v) <= 1 for v in values)
    for value in values:
        if unit_scale:
            # Integer arithmetic, matching the C exactly: whole*255 plus the
            # fraction scaled by the digits that were actually written.
            head, _, tail = f"{value:.6f}".partition(".")
            digits = tail.rstrip("0")[:6]
            scale = 10 ** len(digits) if digits else 0
            component = int(head) * 255 + (int(digits) * 255 // scale if scale else 0)
        else:
            component = int(value)
        packed = (packed << 8) | max(0, min(255, component))
    return packed


ROLE_ITEM = 0x00000200
ROLE_SPAWNS = 0x00000001 | 0x00000002 | 0x00000004


def _round_unit(v: float) -> int:
    return space_oracle._round_unit(v)


def _isqrt(v: int) -> int:
    return math.isqrt(v)


def _distance(a, b) -> int:
    return _isqrt(sum(int(a[i] - b[i]) ** 2 for i in range(3)))


def _undirected(space) -> tuple[list[list[tuple[int, int]]], int]:
    """One undirected edge per unordered pair.

    The space graph emits a symmetric motion from both ends, so the same
    connection arrives twice; counting it twice would inflate the cyclomatic
    number and hide every bridge.
    """
    adjacency: list[list[tuple[int, int]]] = [[] for _ in space.nodes]
    edges = 0
    for e in space.edges:
        if e.kind not in JOINING or e.frm == e.to or e.frm > e.to:
            continue
        adjacency[e.frm].append((e.to, edges))
        adjacency[e.to].append((e.frm, edges))
        edges += 1
    return adjacency, edges


def _connectivity(adjacency, n: int) -> tuple[int, int, int]:
    """Articulation points, bridges and components, by lowpoint."""
    disc: list[int | None] = [None] * n
    low = [0] * n
    parent_edge: list[int | None] = [None] * n
    children = [0] * n
    articulation = [False] * n
    bridges = 0
    components = 0
    timer = 0

    for root in range(n):
        if disc[root] is not None:
            continue
        components += 1
        disc[root] = low[root] = timer
        timer += 1
        stack = [[root, 0]]

        while stack:
            v, cursor = stack[-1]
            if cursor < len(adjacency[v]):
                stack[-1][1] += 1
                w, edge_id = adjacency[v][cursor]
                if edge_id == parent_edge[v]:
                    continue
                if disc[w] is None:
                    children[v] += 1
                    parent_edge[w] = edge_id
                    disc[w] = low[w] = timer
                    timer += 1
                    stack.append([w, 0])
                else:
                    low[v] = min(low[v], disc[w])
                continue

            stack.pop()
            if stack:
                parent = stack[-1][0]
                low[parent] = min(low[parent], low[v])
                if low[v] > disc[parent]:
                    bridges += 1
                if parent != root and low[v] >= disc[parent]:
                    articulation[parent] = True
        if children[root] > 1:
            articulation[root] = True

    return sum(articulation), bridges, components


def _sight(bsp, space) -> tuple[int, int, int, int, int]:
    n = len(space.nodes)
    if n < 2:
        return 0, 0, 0, 0, 0

    observers = min(n, MAX_OBSERVERS)
    observer_stride = n // observers
    partner_stride = max(1, n // PARTNERS)

    pairs = opened = total_length = longest = 0
    zero = (0.0, 0.0, 0.0)

    for o in range(observers):
        i = o * observer_stride
        a = space.nodes[i].origin
        eye_a = (a[0], a[1], tracer.f32(a[2] + float(VIEWHEIGHT)))
        for p in range(PARTNERS):
            j = (i + (p + 1) * partner_stride) % n
            if j == i:
                continue
            b = space.nodes[j].origin
            eye_b = (b[0], b[1], tracer.f32(b[2] + float(VIEWHEIGHT)))
            tr = tracer.box_trace(bsp, eye_a, eye_b, zero, zero, MASK_SIGHT, tracer.f32)
            pairs += 1
            if tr.fraction >= 1.0:
                d = _distance(eye_a, eye_b)
                opened += 1
                total_length += d
                longest = max(longest, d)

    cover = 1000 - (opened * 1000 // pairs) if pairs else 0
    mean = total_length // opened if opened else 0
    return pairs, opened, cover, mean, longest


def build(path: Path) -> dict[str, int]:
    bsp = oracle.load(path)
    space = space_oracle.build(bsp, 32, True)
    ents = list(bsp.entities())
    wiring = wiring_oracle.build(ents, len(bsp.models))

    n = len(space.nodes)
    v: dict[str, int] = {}
    v["nodes"] = n
    v["regions"] = len(space.regions)

    largest = 0
    for i, r in enumerate(space.regions):
        if r.nodes > space.regions[largest].nodes:
            largest = i
    v["largest_region_nodes"] = space.regions[largest].nodes if space.regions else 0
    v["largest_region_permille"] = (v["largest_region_nodes"] * 1000 // n) if n else 0

    if n:
        lo = [min(_round_unit(nd.origin[k]) for nd in space.nodes) for k in range(3)]
        hi = [max(_round_unit(nd.origin[k]) for nd in space.nodes) for k in range(3)]
    else:
        lo = hi = [0, 0, 0]
    for k, name in enumerate(("extent_x", "extent_y", "extent_z")):
        v[name] = hi[k] - lo[k]

    clearances = sorted(nd.clearance for nd in space.nodes)
    v["median_clearance"] = clearances[n // 2] if n else 0
    v["open_permille"] = (
        sum(1 for c in clearances if c >= CLEARANCE_PROBE) * 1000 // n) if n else 0
    v["vertical_span"] = v["extent_z"]

    bands = {(_round_unit(nd.origin[2]) // HEIGHT_BAND) for nd in space.nodes}
    v["height_bands"] = len(bands)

    v["edges"] = len(space.edges)
    for k, name in enumerate(KIND_NAMES):
        v[f"edges_{name}"] = space.kind_counts[k]

    adjacency, undirected_edges = _undirected(space)
    arcs = sum(len(a) for a in adjacency)
    v["mean_walk_degree_milli"] = (arcs * 1000 // n) if n else 0

    articulation, bridges, components = _connectivity(adjacency, n)
    v["chokepoints"] = articulation
    v["bridges"] = bridges
    v["loops"] = max(0, undirected_edges + components - n)
    v["bridge_permille"] = (bridges * 1000 // undirected_edges) if undirected_edges else 0

    pairs, opened, cover, mean, longest = _sight(bsp, space)
    v["sight_pairs"] = pairs
    v["sight_open"] = opened
    v["cover_permille"] = cover
    v["mean_sight_length"] = mean
    v["max_sight_length"] = longest

    v["liquid_nodes"] = sum(1 for nd in space.nodes
                            if nd.flags & space_oracle.NODE_LIQUID)
    v["hazard_nodes"] = sum(1 for nd in space.nodes
                            if nd.flags & space_oracle.NODE_HAZARD)
    v["hazard_permille"] = (v["hazard_nodes"] * 1000 // n) if n else 0

    positioned = bound = unbound = 0
    items_bound = items_unbound = spawns_bound = spawns_unbound = 0
    item_origins: list[tuple[float, float, float]] = []

    for i, ent in enumerate(ents):
        if "origin" not in ent:
            continue
        try:
            origin = tuple(float(x) for x in ent["origin"].split()[:3])
        except ValueError:
            continue
        if len(origin) != 3:
            continue
        positioned += 1

        best = None
        best_d = None
        for k, nd in enumerate(space.nodes):
            dx = int(nd.origin[0] - origin[0])
            dy = int(nd.origin[1] - origin[1])
            dz = int(nd.origin[2] - origin[2])
            if abs(dx) > BIND_RADIUS_XY or abs(dy) > BIND_RADIUS_XY or abs(dz) > BIND_RADIUS_Z:
                continue
            d = _isqrt(dx * dx + dy * dy + dz * dz)
            if best_d is None or d < best_d:
                best_d, best = d, k

        roles = wiring.entities[i].roles
        if best is not None:
            bound += 1
        else:
            unbound += 1
        if roles & ROLE_ITEM:
            item_origins.append(origin)
            if best is not None:
                items_bound += 1
            else:
                items_unbound += 1
        if roles & ROLE_SPAWNS:
            if best is not None:
                spawns_bound += 1
            else:
                spawns_unbound += 1

    v["positioned_entities"] = positioned
    v["bound_entities"] = bound
    v["unbound_entities"] = unbound
    v["items_bound"] = items_bound
    v["items_unbound"] = items_unbound
    v["spawns_bound"] = spawns_bound
    v["spawns_unbound"] = spawns_unbound

    if len(item_origins) > 1:
        total = 0
        for i, a in enumerate(item_origins):
            total += min(_distance(a, b) for j, b in enumerate(item_origins) if j != i)
        v["mean_item_separation"] = total // len(item_origins)
    else:
        v["mean_item_separation"] = 0

    # Contract 7.7's lighting evidence, read the same way the C does: the
    # `light` key, then `_light`, then the compiler's own default of 300 -
    # which is what an entity carrying neither will actually be given.
    intensities = []
    for ent in ents:
        if not ent.get("classname", "").startswith("light"):
            continue
        text = ent.get("light", ent.get("_light"))
        intensity = 300
        if text is not None:
            body = text.strip()
            negative = body.startswith("-")
            digits = ""
            for ch in body[1:] if negative else body:
                if not ch.isdigit():
                    break
                digits += ch
            if digits:
                intensity = -int(digits) if negative else int(digits)
        intensities.append(intensity)

    if intensities:
        intensities.sort()
        n = len(intensities)
        middle = intensities[n // 2]
        low = intensities[n // 4]
        high = intensities[(3 * n) // 4]
        v["lights"] = n
        v["light_median"] = middle if middle > 0 else 0
        # Clamped at zero: the corpus contains negative lights - campgrounds
        # has a -500 - and a subtractive light is a motif of its own, not
        # something to sample an ordinary light from.
        v["light_lower"] = low if low > 0 else 0
        v["light_upper"] = high if high > 0 else v["light_median"]
    else:
        v["lights"] = 0
        v["light_median"] = 0
        v["light_lower"] = 0
        v["light_upper"] = 0

    # The four commonest light colours, packed 0xRRGGBB, most common first.
    counts: dict[int, int] = {}
    for ent in ents:
        if not ent.get("classname", "").startswith("light"):
            continue
        raw = ent.get("_color", ent.get("color"))
        if raw is None:
            continue
        packed = _pack_colour(raw)
        if packed:
            counts[packed] = counts.get(packed, 0) + 1
    # Most common first; ties broken by the order they were first seen, which
    # is the order the C's linear scan finds them in too.
    ranked = sorted(counts, key=lambda c: -counts[c])
    for slot in range(LIGHT_COLOURS):
        v[f"light_colour_{slot}"] = ranked[slot] if slot < len(ranked) else 0

    # How much of the map is open to the sky, per thousand textured brush
    # sides. Counted over SIDES rather than faces, because that is what the
    # genome records and because a side is there whether or not the compiler
    # drew it.
    sky = sides = 0
    for s in bsp.brushsides:
        if not 0 <= s.texinfo < len(bsp.texinfo):
            continue
        sides += 1
        if bsp.texinfo[s.texinfo].flags & SURF_SKY:
            sky += 1
    v["sky_permille"] = (sky * 1000) // sides if sides else 0
    return v


ORDER = [
    "nodes", "regions", "largest_region_nodes", "largest_region_permille",
    "extent_x", "extent_y", "extent_z", "median_clearance", "open_permille",
    "vertical_span", "height_bands", "edges",
    *[f"edges_{k}" for k in KIND_NAMES],
    "mean_walk_degree_milli", "chokepoints", "bridges", "loops",
    "bridge_permille", "sight_pairs", "sight_open", "cover_permille",
    "mean_sight_length", "max_sight_length", "liquid_nodes", "hazard_nodes",
    "hazard_permille", "positioned_entities", "bound_entities",
    "unbound_entities", "items_bound", "items_unbound", "spawns_bound",
    "spawns_unbound", "mean_item_separation", "lights", "light_median",
    "light_lower", "light_upper",
    *[f"light_colour_{i}" for i in range(LIGHT_COLOURS)],
    "sky_permille",
]


def canonical_text(v: dict[str, int]) -> str:
    return "".join(f"{name}={v[name]}\n" for name in ORDER)


def bindings(path: Path) -> list[tuple[str, int]]:
    """Which stance each positioned entity stands on.

    Separate from the vector on purpose: the vector only carries COUNTS, so a
    tie-break that picks a different stance is invisible in it. The binding
    list is where that rule is observable at all.
    """
    bsp = oracle.load(path)
    space = space_oracle.build(bsp, 32, True)
    out: list[tuple[str, int]] = []
    for ent in bsp.entities():
        if "origin" not in ent:
            continue
        try:
            origin = tuple(float(x) for x in ent["origin"].split()[:3])
        except ValueError:
            continue
        if len(origin) != 3:
            continue
        best = -1
        best_d = None
        for k, nd in enumerate(space.nodes):
            dx = int(nd.origin[0] - origin[0])
            dy = int(nd.origin[1] - origin[1])
            dz = int(nd.origin[2] - origin[2])
            if abs(dx) > BIND_RADIUS_XY or abs(dy) > BIND_RADIUS_XY or abs(dz) > BIND_RADIUS_Z:
                continue
            d = _isqrt(dx * dx + dy * dy + dz * dz)
            # Ties go to the LOWER index, so the answer cannot depend on the
            # order the stances happen to be in.
            if best_d is None or d < best_d:
                best_d, best = d, k
        out.append((ent.get("classname", ""), best))
    return out
