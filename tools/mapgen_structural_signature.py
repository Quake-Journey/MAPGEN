"""What a compiled map IS, with the paint stripped off.

Codex's seed-diversity ruling of 2026-09-03, section 10, asks for an expressive
range measured over *compiled structural signatures* - explicitly not BSP bytes
and explicitly not reskins, items or lights. Two maps that differ only in which
texture is on the walls are the same map for this purpose, and a signature over
file bytes would call them different; a signature over the whole entity lump
would call an item moved by eight units a new piece of architecture.

So the signature is built from the things a player's movement runs into:

    the architectural planes         every canonical plane that carries a drawn
                                     surface, sign-free, quantized to a unit
    the space, by class              solid, empty, liquid and hazard volume
                                     summed over the BSP tree's disjoint convex
                                     leaves - a property of the space, not of
                                     the brushwork that described it
    the surfaces, by orientation     drawn area per facing direction, in
                                     buckets, with no texture identity in it
    the machines                     brush models by their bounds, which is
                                     where a door or a lift can move you

Deliberately absent: texture names, flags and values; texture axes; entity
classnames, origins and keys; lighting; vis; lump order; face subdivision.

    python tools/mapgen_structural_signature.py MAP.bsp [MAP.bsp ...]
        [--verbose]

Prints one signature per map, and - given several - how many distinct ones
there were, which is the number the expressive-range gate is about.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapgen_equivalence_oracle import Bsp, area_and_centroid, lump  # noqa: E402

L_PLANES, L_NODES, L_LEAFS, L_MODELS = 1, 4, 8, 13

CONTENTS_SOLID = 1
CONTENTS_WINDOW = 2
CONTENTS_LAVA = 8
CONTENTS_SLIME = 16
CONTENTS_WATER = 32

CLASSES = ("solid", "empty", "liquid", "hazard")


def classify(contents: int) -> str:
    if contents & (CONTENTS_SOLID | CONTENTS_WINDOW):
        return "solid"
    if contents & (CONTENTS_LAVA | CONTENTS_SLIME):
        return "hazard"
    if contents & CONTENTS_WATER:
        return "liquid"
    return "empty"


def canon_plane(normal, dist):
    """Sign-free: the same wall described from either side is one plane."""
    best = max(range(3), key=lambda i: abs(normal[i]))
    if normal[best] < 0:
        return tuple(-n for n in normal), -dist
    return tuple(normal), dist


class Structure(Bsp):
    def __init__(self, path: Path):
        super().__init__(path)
        raw = self.raw
        p = lump(raw, L_LEAFS)
        self.leafs = [struct.unpack_from("<ihh6h4H", p, i * 28)
                      for i in range(len(p) // 28)]
        n = lump(raw, L_NODES)
        self.nodes = [struct.unpack_from("<i2i6h2H", n, i * 28)
                      for i in range(len(n) // 28)]

    def architectural_planes(self) -> list[tuple]:
        """Every canonical plane a drawn surface sits on, quantized."""
        seen = set()
        owner = self.face_owner()
        for index, face in enumerate(self.faces):
            if owner[index] is None:
                continue
            planenum, side, _, count, texinfo = face
            if count < 3:
                continue
            plane = self.planes[planenum]
            sign = -1.0 if side else 1.0
            normal, dist = canon_plane([sign * plane[k] for k in range(3)],
                                       sign * plane[3])
            seen.add((round(normal[0], 2), round(normal[1], 2),
                      round(normal[2], 2), round(dist)))
        return sorted(seen)

    def leaf_volumes(self) -> dict[str, float]:
        """The space itself, summed over the tree's disjoint convex leaves.

        Reached by clipping the world box down the tree, so the answer does not
        depend on how the compiler chose to split anything.
        """
        world = self.models[0]
        mins, maxs = world[0], world[1]
        region = []
        for a in range(3):
            hi = [0.0, 0.0, 0.0]
            hi[a] = 1.0
            region.append((tuple(hi), maxs[a] + 1.0))
            lo = [0.0, 0.0, 0.0]
            lo[a] = -1.0
            region.append((tuple(lo), -(mins[a] - 1.0)))

        totals = {name: 0.0 for name in CLASSES}
        self._walk(world[4], region, totals, 0)
        return totals

    def _walk(self, node, region, totals, depth):
        if depth > 160:
            return
        if node < 0:
            leaf = self.leafs[-1 - node]
            totals[classify(leaf[0])] += region_volume(region)
            return
        planenum = self.nodes[node][0]
        children = self.nodes[node][1:3]
        plane = self.planes[planenum]
        normal = (plane[0], plane[1], plane[2])
        front = (tuple(-n for n in normal), -plane[3])
        back = (normal, plane[3])
        self._walk(children[0], region + [front], totals, depth + 1)
        self._walk(children[1], region + [back], totals, depth + 1)

    def orientation_area(self) -> Counter:
        """Drawn area per facing, in buckets. No texture identity in it."""
        out: Counter = Counter()
        owner = self.face_owner()
        for index, face in enumerate(self.faces):
            if owner[index] is None:
                continue
            planenum, side, _, count, texinfo = face
            if count < 3:
                continue
            area, _ = area_and_centroid(self.face_points(face))
            if area <= 0:
                continue
            plane = self.planes[planenum]
            sign = -1.0 if side else 1.0
            normal = [sign * plane[k] for k in range(3)]
            bucket = (round(normal[0], 1), round(normal[1], 1),
                      round(normal[2], 1))
            out[bucket] += area
        return out

    def machines(self) -> list[tuple]:
        """Brush models by their bounds: where something can move you."""
        return sorted((tuple(round(v) for v in m[0]),
                       tuple(round(v) for v in m[1]))
                      for m in self.models[1:])


def base_polygon(plane, reach=131072.0):
    normal, dist = plane
    up = [0.0, 0.0, 1.0]
    if abs(normal[2]) > 0.9:
        up = [1.0, 0.0, 0.0]
    right = [up[1] * normal[2] - up[2] * normal[1],
             up[2] * normal[0] - up[0] * normal[2],
             up[0] * normal[1] - up[1] * normal[0]]
    length = math.sqrt(sum(c * c for c in right))
    if length < 1e-6:
        return []
    right = [c / length for c in right]
    up = [normal[1] * right[2] - normal[2] * right[1],
          normal[2] * right[0] - normal[0] * right[2],
          normal[0] * right[1] - normal[1] * right[0]]
    origin = [normal[k] * dist for k in range(3)]
    out = []
    for k in range(4):
        sx = -reach if k in (0, 3) else reach
        sy = -reach if k < 2 else reach
        out.append([origin[i] + right[i] * sx + up[i] * sy for i in range(3)])
    return out


def clip(poly, plane, eps=0.01):
    normal, dist = plane
    if not poly:
        return []
    d = [sum(p[k] * normal[k] for k in range(3)) - dist for p in poly]
    out = []
    for i in range(len(poly)):
        j = (i + 1) % len(poly)
        if d[i] <= eps:
            out.append(poly[i])
        if (d[i] > eps and d[j] < -eps) or (d[i] < -eps and d[j] > eps):
            t = d[i] / (d[i] - d[j])
            out.append([poly[i][k] + t * (poly[j][k] - poly[i][k])
                        for k in range(3)])
        if len(out) > 64:
            return []
    return out


def region_volume(region) -> float:
    total = 0.0
    for i, plane in enumerate(region):
        poly = base_polygon(plane)
        for j, other in enumerate(region):
            if j != i and poly:
                poly = clip(poly, other)
        if len(poly) < 3:
            continue
        area, _ = area_and_centroid(poly)
        total += area * plane[1]
    return abs(total) / 3.0


AXIS_BUCKETS = 48
FACING_BUCKETS = (
    (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1),
)


def descriptor(path: Path, verbose: bool = False) -> dict:
    """A fixed-length description of the architecture, with the paint off.

    Everything is a proportion of the map's own totals, so a bigger map is not
    automatically a more different one, and nothing here can be changed by a
    reskin, an item, a light or the compiler's choice of split planes.
    """
    s = Structure(path)
    planes = s.architectural_planes()
    volumes = s.leaf_volumes()
    orient = s.orientation_area()
    machines = s.machines()

    world = s.models[0]
    mins, maxs = world[0], world[1]

    # Where the walls are. One histogram per axis, over the map's own extent,
    # so a wall that moved shows up in a different bucket while an extra
    # sliver on an existing wall adds a fraction to the bucket it was already
    # in.
    walls = [[0.0] * AXIS_BUCKETS for _ in range(3)]
    for normal_x, normal_y, normal_z, dist in planes:
        normal = (normal_x, normal_y, normal_z)
        axis = max(range(3), key=lambda i: abs(normal[i]))
        span = maxs[axis] - mins[axis]
        if span <= 0:
            continue
        # The plane's offset along its own dominant axis.
        offset = dist / normal[axis] if abs(normal[axis]) > 1e-6 else dist
        at = (offset - mins[axis]) / span
        bucket = min(AXIS_BUCKETS - 1, max(0, int(at * AXIS_BUCKETS)))
        walls[axis][bucket] += 1.0
    for axis in range(3):
        total = sum(walls[axis]) or 1.0
        walls[axis] = [v / total for v in walls[axis]]

    # Which way the drawn surface points, over six fixed directions plus what
    # is in between. A ramp is not a floor and not a wall.
    facing = [0.0] * (len(FACING_BUCKETS) + 1)
    total_area = sum(orient.values()) or 1.0
    for bucket, area in orient.items():
        best, best_dot = len(FACING_BUCKETS), 0.7
        for i, direction in enumerate(FACING_BUCKETS):
            dot = sum(bucket[k] * direction[k] for k in range(3))
            if dot > best_dot:
                best, best_dot = i, dot
        facing[best] += area / total_area

    total_volume = sum(volumes.values()) or 1.0
    space = [volumes[name] / total_volume for name in CLASSES]

    machine_volume = 0.0
    for mn, mx in machines:
        machine_volume += max(0.0, (mx[0] - mn[0])) * max(0.0, (mx[1] - mn[1])) \
                        * max(0.0, (mx[2] - mn[2]))
    machine = [min(1.0, len(machines) / 16.0),
               min(1.0, machine_volume / total_volume * 100.0)]

    if verbose:
        print(f"  {path.name}: {len(planes)} architectural planes, "
              f"solid {space[0]:.4f}, empty {space[1]:.4f}, "
              f"{len(machines)} machines")

    return {"walls": walls, "facing": facing, "space": space,
            "machine": machine, "planes": len(planes)}


def distance(a: dict, b: dict) -> float:
    """Mean L1 distance over the four parts, each already normalized."""
    parts = []
    parts.append(sum(sum(abs(x - y) for x, y in zip(a["walls"][k],
                                                    b["walls"][k]))
                     for k in range(3)) / 3.0)
    parts.append(sum(abs(x - y) for x, y in zip(a["facing"], b["facing"])))
    parts.append(sum(abs(x - y) for x, y in zip(a["space"], b["space"])))
    parts.append(sum(abs(x - y) for x, y in zip(a["machine"], b["machine"])))
    return sum(parts) / len(parts)


def cluster(descriptors: list[dict], threshold: float) -> list[int]:
    """Which structure each map belongs to.

    Single-link: a map joins a cluster when it is within the threshold of any
    member. Two maps that differ only by what two compilations of the same
    architecture can differ by end up together, which is the point.
    """
    labels = [-1] * len(descriptors)
    next_label = 0
    for i in range(len(descriptors)):
        if labels[i] >= 0:
            continue
        labels[i] = next_label
        queue = [i]
        while queue:
            at = queue.pop()
            for k in range(len(descriptors)):
                if labels[k] >= 0:
                    continue
                if distance(descriptors[at], descriptors[k]) <= threshold:
                    labels[k] = next_label
                    queue.append(k)
        next_label += 1
    return labels


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", type=Path, nargs="+")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.02,
                    help="below this two maps are the same structure")
    ap.add_argument("--pairs", action="store_true",
                    help="print the pairwise distance distribution")
    args = ap.parse_args()

    paths, descriptors = [], []
    for path in args.maps:
        if not path.is_file():
            print(f"  MISSING {path}")
            continue
        paths.append(path)
        descriptors.append(descriptor(path, args.verbose))

    if len(paths) < 2:
        return 0

    labels = cluster(descriptors, args.threshold)
    for path, label in zip(paths, labels):
        print(f"structure {label:3d}  {path.name}")

    distances = []
    for i in range(len(paths)):
        for k in range(i + 1, len(paths)):
            distances.append((distance(descriptors[i], descriptors[k]),
                              paths[i].name, paths[k].name))
    distances.sort()

    counts = Counter(labels)
    total = len(labels)
    print(f"\n{len(counts)} distinct structures in {total} maps "
          f"at threshold {args.threshold}")
    print(f"the commonest structure occupies {counts.most_common(1)[0][1]} "
          f"of {total}")
    if distances:
        print(f"pairwise distance: min {distances[0][0]:.4f} "
              f"({distances[0][1]} vs {distances[0][2]}), "
              f"median {distances[len(distances) // 2][0]:.4f}, "
              f"max {distances[-1][0]:.4f}")
    if args.pairs:
        for d, a, b in distances:
            print(f"  {d:.4f}  {a}  {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
