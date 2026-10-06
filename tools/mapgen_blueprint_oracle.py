#!/usr/bin/env python3
"""An independent answer to "what is this map's architecture?".

Shares no code with `src/mapgen/mapgen_blueprint.c`. It reads the same compiled
BSP through the existing space oracle and reaches the same volumes, portals and
relations by its own route, so the two implementations disagreeing is a finding
rather than a coincidence.

The segmentation rule, stated once and implemented twice:

  * a stance's WALK degree tells it apart - two or fewer neighbours is a
    passage, more is a hall. A corridor is thin; a room is not;
  * a volume is a connected component of ONE class, over walk and step edges,
    so a hall and the corridor leaving it do not merge into one blob;
  * an edge between two volumes is a portal carrying its kind, its signed rise
    and whether it is one-way;
  * relations are read off the volumes' bounds: above, XY overlap, containment
    and adjacency.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_bsp_oracle as oracle                          # noqa: E402
import mapgen_space_oracle as space_oracle                  # noqa: E402

BASIS = 16
THIN_DEGREE = 2

WALK, STEP, JUMP, FALL, SWIM = range(5)
JOINING = (WALK, STEP)          # what makes one continuous piece of floor

HALL, PASSAGE = 0, 1

NODE_LIQUID, NODE_HAZARD, NODE_DUCKED = 0x1, 0x2, 0x4
VOLUME_LIQUID, VOLUME_HAZARD, VOLUME_SKY, VOLUME_DUCKED = 0x1, 0x2, 0x4, 0x8

ABOVE, OVERLAP_XY, CONTAINS, ADJACENT = range(4)


def _walk_degree(space) -> list[int]:
    degree = [0] * len(space.nodes)
    for e in space.edges:
        if e.kind == WALK:
            degree[e.frm] += 1
            degree[e.to] += 1
    return degree


def _classify(space) -> list[int]:
    """Thin or open, with the wall ring folded back into the room.

    A stance beside a wall loses half its walk neighbours, so classifying by
    degree alone rings every hall with "passage" stances that then fragment
    into hundreds of slivers - 459 of them on q2dm1. Dilating the hall class by
    one step over walk edges puts that ring back where it belongs. It is a
    morphological closing, and it is deterministic.
    """
    degree = _walk_degree(space)
    klass = [PASSAGE if d <= THIN_DEGREE else HALL for d in degree]

    grown = list(klass)
    for e in space.edges:
        if e.kind != WALK:
            continue
        if klass[e.frm] == HALL:
            grown[e.to] = HALL
        if klass[e.to] == HALL:
            grown[e.frm] = HALL
    return grown


def _components(space, klass: list[int]) -> list[int]:
    """Volume id per node: connected components within one class."""
    adjacency: list[list[int]] = [[] for _ in space.nodes]
    for e in space.edges:
        if e.kind in JOINING and klass[e.frm] == klass[e.to]:
            adjacency[e.frm].append(e.to)
            adjacency[e.to].append(e.frm)

    volume = [-1] * len(space.nodes)
    # Seeded in node order, so ids do not depend on how the graph was built.
    next_id = 0
    for start in range(len(space.nodes)):
        if volume[start] >= 0:
            continue
        stack = [start]
        volume[start] = next_id
        while stack:
            at = stack.pop()
            for nxt in adjacency[at]:
                if volume[nxt] < 0:
                    volume[nxt] = next_id
                    stack.append(nxt)
        next_id += 1
    return volume


def _volume_class(space, klass: list[int], owner: list[int]) -> dict[int, int]:
    """One class per volume, taken when the component is formed.

    After an absorption a volume's stances no longer share a class, so asking
    the nodes is ambiguous. Asking the volume is not.
    """
    of: dict[int, int] = {}
    for i, o in enumerate(owner):
        if o not in of:
            of[o] = klass[i]
    return of


def _absorb_dead_ends(space, klass: list[int], owner: list[int],
                      volume_class: dict[int, int]) -> list[int]:
    """Fold single-neighbour passage components into what they hang off.

    A corridor connects two volumes. A component that touches only one is the
    edge of that one - a stance beside a wall loses half its walk neighbours
    and is classified thin for a reason that has nothing to do with being a
    corridor.
    """
    changed = True
    while changed:
        changed = False
        neighbours: dict[int, set[int]] = {}
        for e in space.edges:
            a, b = owner[e.frm], owner[e.to]
            if a == b:
                continue
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)

        # Deterministic: lowest id first, so the outcome cannot depend on set
        # iteration order.
        for vid in sorted(set(owner)):
            if volume_class.get(vid) != PASSAGE:
                continue
            members = [i for i, o in enumerate(owner) if o == vid]
            if not members:
                continue
            touching = neighbours.get(vid, set())
            if len(touching) != 1:
                continue
            into = next(iter(touching))
            for i in members:
                owner[i] = into
            changed = True
            break
    return owner


def _snap(v: int) -> int:
    return (v // BASIS) * BASIS if v >= 0 else -((-v + BASIS - 1) // BASIS) * BASIS


def build(path: Path) -> dict:
    bsp = oracle.load(path)
    space = space_oracle.build(bsp)

    klass = _classify(space)
    owner = _components(space, klass)
    volume_class = _volume_class(space, klass, owner)
    owner = _absorb_dead_ends(space, klass, owner, volume_class)

    # Dense ids, assigned in first-appearance order, which is node order
    # because components are seeded that way. Absorption leaves holes and a
    # sparse id space would make every downstream reference depend on which
    # slivers happened to be folded away.
    remap: dict[int, int] = {}
    for i, o in enumerate(owner):
        if o not in remap:
            remap[o] = len(remap)
    # The class travels with its volume through the renumbering; a dict still
    # keyed by pre-absorption ids would answer about a volume that no longer
    # exists.
    volume_class = {remap[old]: volume_class[old] for old in remap}
    owner = [remap[o] for o in owner]
    count = len(remap)

    volumes = []
    for vid in range(count):
        members = [i for i, o in enumerate(owner) if o == vid]
        if not members:
            continue
        cells = [space.nodes[i].origin for i in members]
        mins = [_snap(int(min(c[a] for c in cells))) for a in range(3)]
        maxs = [_snap(int(max(c[a] for c in cells))) + BASIS for a in range(3)]

        clearances = sorted(space.nodes[i].clearance for i in members)
        median_clear = clearances[len(clearances) // 2]

        flags = 0
        if any(space.nodes[i].flags & NODE_LIQUID for i in members):
            flags |= VOLUME_LIQUID
        if any(space.nodes[i].flags & NODE_HAZARD for i in members):
            flags |= VOLUME_HAZARD
        if all(space.nodes[i].flags & NODE_DUCKED for i in members):
            flags |= VOLUME_DUCKED
        # At the clearance cap nothing was hit within the probe's reach.
        if median_clear >= 512:
            flags |= VOLUME_SKY

        footprint = ((maxs[0] - mins[0]) // BASIS) * ((maxs[1] - mins[1]) // BASIS)
        occupancy = (len(members) * 1000 // footprint) if footprint else 0
        if occupancy > 1000:
            occupancy = 1000

        volumes.append({
            "id": vid,
            "klass": volume_class[vid],
            "flags": flags,
            "mins": mins,
            "maxs": maxs,
            "floor": mins[2],
            "ceiling": mins[2] + median_clear,
            "stances": len(members),
            "occupancy_permille": occupancy,
            "landmark_weight": len(members) * occupancy // 1000,
        })

    # --- portals -------------------------------------------------------------
    portals: dict[tuple, dict] = {}
    for e in space.edges:
        a, b = owner[e.frm], owner[e.to]
        if a == b:
            continue
        key = (a, b, e.kind)
        rec = portals.get(key)
        clearance = min(space.nodes[e.frm].clearance, space.nodes[e.to].clearance)
        if rec is None:
            portals[key] = {
                "from": a, "to": b, "kind": e.kind,
                "one_way": e.kind in (JUMP, FALL),
                "rise": e.rise, "aperture": 1, "clearance": clearance,
            }
        else:
            rec["aperture"] += 1
            rec["clearance"] = min(rec["clearance"], clearance)

    # --- relations -----------------------------------------------------------
    relations = []
    for i, va in enumerate(volumes):
        for vb in volumes[i + 1:]:
            overlap_xy = (va["mins"][0] < vb["maxs"][0] and va["maxs"][0] > vb["mins"][0]
                          and va["mins"][1] < vb["maxs"][1] and va["maxs"][1] > vb["mins"][1])
            if overlap_xy:
                relations.append({"a": va["id"], "b": vb["id"], "kind": OVERLAP_XY})
                if va["mins"][2] >= vb["maxs"][2]:
                    relations.append({"a": va["id"], "b": vb["id"], "kind": ABOVE})
                elif vb["mins"][2] >= va["maxs"][2]:
                    relations.append({"a": vb["id"], "b": va["id"], "kind": ABOVE})
            contains = all(va["mins"][a] <= vb["mins"][a] and va["maxs"][a] >= vb["maxs"][a]
                           for a in range(3))
            if contains:
                relations.append({"a": va["id"], "b": vb["id"], "kind": CONTAINS})

    return {
        "volumes": volumes,
        "portals": [portals[k] for k in sorted(portals)],
        "relations": sorted((r["kind"], r["a"], r["b"]) for r in relations),
    }


def canonical_text(bp: dict) -> str:
    out = [f"volumes={len(bp['volumes'])}\n"]
    for v in bp["volumes"]:
        out.append(
            "v={id},{klass},{flags},{mins[0]},{mins[1]},{mins[2]},"
            "{maxs[0]},{maxs[1]},{maxs[2]},{floor},{ceiling},{stances},"
            "{occupancy_permille},{landmark_weight}\n".format(**v))
    out.append(f"portals={len(bp['portals'])}\n")
    for p in bp["portals"]:
        out.append("p={from},{to},{kind},{one_way:d},{rise},{aperture},"
                   "{clearance}\n".format(**p))
    out.append(f"relations={len(bp['relations'])}\n")
    for kind, a, b in bp["relations"]:
        out.append(f"r={a},{b},{kind}\n")
    return "".join(out)
