"""What the courtyard sees of a dig's building, the visibility lists.

Ledger rows 375 and 384. The PO's video of mg_20r (2026-10-02): from the courtyard the annex over the courtyard wall
is drawn as a building, but the left part of its face appears and disappears as the player moves. The renderer draws
through the sky only what the map's visibility (PVS) lists, and the PVS is computed through portals between air
leaves - a sky brush is solid and no portal passes it - so a building standing behind the sky is listed from some
places and not from others. The sky lift (row 384) stands it in real air instead.

    python tools/check_mapgen_lift_pvs.py MAP.bsp --base BASE.bsp --seg x0 y0 z0 x1 y1 z1 [--seg ...] [--reach 700]

POSITIONS: one per 32-unit column within REACH of the dig in plan, in the base map's courtyard air - straight up,
the first solid is a sky brush - at EYE over the floor, or just under the sky if that is lower; in air in MAP too.
TARGETS: the dig's new air OUTSIDE its building - air in MAP, solid in BASE, within the segments' box grown by 64 and
outside every segment grown by its shell - on a 32-unit lattice off the map's grid: the air in front of the
building's outer faces (the skin's gap, or the lifted air round it). A target is IN SIGHT from a position when the
straight line between them meets no drawn face: air into a solid that is not sky is a drawn face; air into sky is
not (the renderer draws the sky behind everything), and solid into solid is no face. A target in sight whose cluster
is NOT in the position's PVS is a MISS - the building's face there is not drawn and the sky shows through: the
flicker. PASS when there is none.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_mapgen_sky_portal import CONTENTS_SOLID, SkyBsp  # noqa: E402
from check_mapgen_static import Bsp  # noqa: E402

LATTICE = 32.0
EYE = 56.0
SHELL = 16.0


def positions(m: SkyBsp, base: SkyBsp, box: list, reach: float) -> list:
    """One eye per 32-unit column within reach of the box in plan, in the base's courtyard air."""
    out = []
    ztop, zbot = box[5] + 1024.0, box[2] - 1024.0
    x = box[0] - reach + LATTICE / 2 + 7.0
    while x < box[3] + reach:
        y = box[1] - reach + LATTICE / 2 + 11.0
        while y < box[4] + reach:
            dx = max(box[0] - x, 0.0, x - box[3])
            dy = max(box[1] - y, 0.0, y - box[4])
            if math.hypot(dx, dy) <= reach:
                z = ztop
                while z > zbot and base.solid((x, y, z)):
                    z -= 16.0
                if z > zbot:
                    while z < ztop + 1024.0 and not base.solid((x, y, z + 4.0)):
                        z += 4.0
                    if base.in_sky((x, y, z + 6.0)):
                        f = z
                        while f > zbot and not base.solid((x, y, f - 4.0)):
                            f -= 4.0
                        v = (x, y, min(z - 4.0, f + EYE))
                        # a player stands on ground, never on the sky laid over a wall top: the pocket between
                        # such a slope and the lid is no courtyard place (the first fixture's misses were there)
                        if not m.solid(v) and not base.in_sky((x, y, f - 2.0)):
                            out.append(v)
            y += LATTICE
        x += LATTICE
    return out


def targets(m: SkyBsp, base: Bsp, segs: list, box: list) -> list:
    """New air outside the building, near it."""
    out = []
    x = box[0] - 64.0 + 5.0
    while x < box[3] + 64.0:
        y = box[1] - 64.0 + 3.0
        while y < box[4] + 64.0:
            z = box[2] - 64.0 + 1.0
            while z < box[5] + 64.0:
                p = (x, y, z)
                inside = any(all(s[i] - SHELL <= p[i] <= s[3 + i] + SHELL for i in range(3)) for s in segs)
                if not inside and not m.solid(p) and base.solid(p):
                    out.append(p)
                z += LATTICE
            y += LATTICE
        x += LATTICE
    return out


def in_sight(m: SkyBsp, c, a) -> bool:
    """From c to a: does the line meet no drawn face?"""
    in_air = True
    length = math.dist(c, a)
    for t0, t1, leaf in m.leaves_along(c, a):
        if t1 - t0 <= 1e-6:
            continue
        if m.leafs[leaf][0] & CONTENTS_SOLID:
            tm = min(t0 + 0.5 / length, 0.5 * (t0 + t1)) if length > 0 else t0
            p = tuple(c[i] + (a[i] - c[i]) * tm for i in range(3))
            if in_air and not m.in_sky(p):
                return False
            in_air = False
        else:
            in_air = True
    return True


PLAYERCLIP = 0x10000


def _lifts(m: SkyBsp) -> list:
    out = []
    for e in m.ents:
        for key in ("mapgen_sky_lift", "mapgen_sky_lift_near"):
            v = e.get(key, "").split()
            if len(v) == 6:
                out.append([float(x) for x in v])
    return out


def _clip_at(b: SkyBsp, p) -> bool:
    """Is the point inside a player-clip brush of this map - by the brush's planes, not by the leaf's contents
    (a leaf takes the contents of every brush that reaches into it, so a leaf half under a clip post reads clip all
    through; row 390)."""
    lf = b.leafs[b.leaf(p)]
    return any(b.brushes[b.leafbrushes[k]][2] & PLAYERCLIP and not b.brushes[b.leafbrushes[k]][2] & CONTENTS_SOLID
               and b._inside(b.leafbrushes[k], p) for k in range(lf[11], lf[11] + lf[12]))


def clip_overreach(mp: Path, bp: Path, step: float = 8.0) -> tuple[int, int, list]:
    """Row 390 (Fable's brief 3, W1): the lift lays player clip of the very shape of each piece of sky it takes, so
    no player is stopped anywhere he could go before. On a lattice through every player-clip brush of the map inside
    a recorded lift volume: (points sampled, points where the BASE was open - not solid, no player clip - a few of
    them). Solid in the base is no overreach: a sky brush overlapping a wall left its clip inside the wall."""
    m, base = SkyBsp(mp), SkyBsp(bp)
    lifts = _lifts(m)
    sampled, over, said = 0, 0, []
    for bi, (first, num, contents) in enumerate(m.brushes):
        if not contents & PLAYERCLIP or contents & CONTENTS_SOLID:
            continue
        lo, hi = [None] * 3, [None] * 3
        for s in range(first, first + num):
            pl = m.planes[m.brushsides[s][0]]
            for a in range(3):
                if abs(abs(pl[a]) - 1.0) < 1e-4 and all(abs(pl[k]) < 1e-4 for k in range(3) if k != a):
                    if pl[a] > 0:
                        hi[a] = pl[3]
                    else:
                        lo[a] = -pl[3]
        if None in lo or None in hi:
            continue
        if not any(all(v[i] - 0.5 <= lo[i] and hi[i] <= v[3 + i] + 0.5 for i in range(3)) for v in lifts):
            continue
        x = lo[0] + 1.0
        while x < hi[0]:
            y = lo[1] + 1.0
            while y < hi[1]:
                z = lo[2] + 1.0
                while z < hi[2]:
                    p = (x, y, z)
                    if m._inside(bi, p):
                        sampled += 1
                        if not base.solid(p) and not _clip_at(base, p):
                            over += 1
                            if len(said) < 4:
                                said.append(p)
                    z += step
                y += step
            x += step
    return sampled, over, said


def measure(mp: Path, bp: Path, segs: list, reach: float) -> dict:
    m, base = SkyBsp(mp), SkyBsp(bp)
    box = [min(s[i] for s in segs) for i in range(3)] + [max(s[3 + i] for s in segs) for i in range(3)]
    ps, ts = positions(m, base, box, reach), targets(m, base, segs, box)
    tcl = [m.cluster(t) for t in ts]
    clusters = sorted(set(c for c in tcl if c >= 0))
    misses, miss_positions, shown = 0, 0, []
    per_position = []
    for p in ps:
        cp = m.cluster(p)
        seen_cl, missed_cl = set(), set()
        for t, ct in zip(ts, tcl):
            if ct < 0 or ct in seen_cl:
                continue
            if m.sees(cp, ct):
                if in_sight(m, p, t):
                    seen_cl.add(ct)
                continue
            if ct in missed_cl:
                continue
            if in_sight(m, p, t):
                missed_cl.add(ct)
                misses += 1
                if len(shown) < 4:
                    shown.append((p, t))
        if missed_cl:
            miss_positions += 1
        if seen_cl or missed_cl:
            per_position.append((len(seen_cl), len(seen_cl) + len(missed_cl)))
    return {"positions": len(ps), "targets": len(ts), "clusters": len(clusters), "misses": misses,
            "miss_positions": miss_positions, "shown": shown, "per_position": per_position}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--seg", type=float, nargs=6, action="append", required=True)
    ap.add_argument("--reach", type=float, default=700.0)
    a = ap.parse_args()
    r = measure(a.map, a.base, a.seg, a.reach)
    full = sum(1 for s, t in r["per_position"] if s == t)
    print(f"  {'PASS' if not r['misses'] else 'FAIL'}  {a.map.name}: the building is in the visibility wherever it is in"
          f" sight -- {r['positions']} courtyard positions within {a.reach:.0f}, {r['targets']} points of new air round"
          f" it in {r['clusters']} clusters; {len(r['per_position'])} positions see some of it, {full} have every"
          f" cluster in sight in their PVS; {r['misses']} (position, cluster) pairs in sight and NOT in the PVS from"
          f" {r['miss_positions']} positions"
          + ("".join(f"; e.g. {' '.join(f'{v:.0f}' for v in t)} from {' '.join(f'{v:.0f}' for v in p)}"
                     for p, t in r["shown"][:2])))
    print(f"SUMMARY 1 cases asserted, {int(bool(r['misses']))} failures")
    return 0 if not r["misses"] else 1


if __name__ == "__main__":
    sys.exit(main())
