"""No dug space stands open to the old map high above a doorway.

The PO, 2026-10-01, on mg_20o: «часть архитектуры в воздухе просто без стенки торчит ... Потолок есть и изнутри норм,
на снаружи какая то матрица, такого быть не должно». A dig's shell leaves a face open wherever the donor has air
outside it, so a passage's tall segment beside an end room - a lift shaft arriving at a courtyard - stood open its
whole height, 288 where a doorway is 128 (ledger row 343).

    python tools/check_mapgen_dig_walls.py MAP.bsp --digs DIGS.json [--donor q2dm1.bsp]

DIGS.json: {"MAP.bsp": [{"box": [...], ...}, ...]} - the accepted digs, as the delivery gates write it. On a 16-unit
lattice inside each dig's box: a point that is rock in the donor and air in the map (new space) beside a point that is
air in both (old space), with nothing solid between them, where the old point stands more than 176 over the donor's
floor under it - higher than any doorway the generator cuts - is refused; and so is a point that is AIR in the donor
and SOLID in the map more than 64 over the donor's floor under it - a tread, a slab or a lamp standing in the old air.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_mapgen_static import Bsp  # noqa: E402

DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
STEP = 16.0
DOORWAY = 176.0


def floor_under(b: Bsp, p, reach: float = 1024.0) -> float:
    z = p[2]
    while z > p[2] - reach:
        if b.solid((p[0], p[1], z)):
            return z
        z -= 4.0
    return p[2] - reach


def in_doorway(q, dig: dict) -> bool:
    """Row 345: is the old point in a doorway's band over one of its dig's ends - from 32 under to 160 over that
    end's floor, within 256 of it in plan - as the plan's dug rule allows?"""
    for k in ("from", "to"):
        e = dig.get(k)
        if not e:
            continue
        dz = q[2] - float(e[2])
        if -32.0 <= dz <= 160.0 and (q[0] - float(e[0])) ** 2 + (q[1] - float(e[1])) ** 2 <= 256.0 ** 2:
            return True
    return False


def open_around(d: Bsp, p, reach: float = 24.0) -> bool:
    """Row 352: is the donor air `reach` off the point on all four sides and above - open air, not a recess or the
    underside of a ceiling a lamp hangs from?"""
    return all(not d.solid((p[0] + dx, p[1] + dy, p[2] + dz))
               for dx, dy, dz in ((reach, 0, 0), (-reach, 0, 0), (0, reach, 0), (0, -reach, 0), (0, 0, reach)))


def on_floor(m: Bsp, p, floor: float) -> bool:
    """Row 356: is the map solid all the way from the point down to the donor's floor under it - a post or a block
    standing on the floor, not a piece hanging in the air?"""
    z = p[2]
    while z > floor + 2.0:
        if not m.solid((p[0], p[1], z)):
            return False
        z -= 8.0
    return True


def inside_any(p, boxes: list) -> bool:
    return any(all(b[i] <= p[i] <= b[3 + i] for i in range(3)) for b in boxes)


def open_high(bsp: Path, digs: list, donor: Path = DONOR, skip: list | None = None) -> list:
    """(new point, old point, height over the donor's floor) for every high opening inside the digs' boxes - not
    inside a `skip` box, another edit's (a window is new space by design), and not new space under the sky: the gap
    of a dig's sky skin, open over a courtyard wall to the courtyard's air, is the dig's outside seen as a building
    (row 354)."""
    from check_mapgen_sky_portal import SkyBsp, under_roof
    m, d = SkyBsp(bsp), Bsp(donor)
    skip = skip or []
    found, seen = [], set()
    for dig in digs:
        box = [float(v) for v in dig["box"]]
        x = box[0] + STEP / 2
        while x < box[3]:
            y = box[1] + STEP / 2
            while y < box[4]:
                z = box[2] + STEP / 2
                while z < box[5]:
                    key = (round(x), round(y), round(z))
                    p = (x, y, z)
                    if key not in seen and not m.solid(p) and d.solid(p) and not inside_any(p, skip)                             and under_roof(m, p):
                        seen.add(key)
                        for dx, dy in ((STEP, 0), (-STEP, 0), (0, STEP), (0, -STEP)):
                            q = (x + dx, y + dy, z)
                            mid = (x + dx / 2, y + dy / 2, z)
                            if not m.solid(q) and not d.solid(q) and not m.solid(mid):
                                h = q[2] - floor_under(d, q)
                                if h > DOORWAY and not in_doorway(q, dig):
                                    found.append((p, q, h))
                                break
                    z += STEP
                y += STEP
            x += STEP
    return found


def solid_in_air(bsp: Path, digs: list, donor: Path = DONOR, skip: list | None = None) -> list:
    """(point, height over the donor's floor) for every point of new solid in old air inside the digs' boxes - not
    inside a `skip` box, another edit's (a flood lays its basin in the old air by design)."""
    m, d = Bsp(bsp), Bsp(donor)
    skip = skip or []
    found, seen = [], set()
    for dig in digs:
        box = [float(v) for v in dig["box"]]
        x = box[0] + STEP / 2
        while x < box[3]:
            y = box[1] + STEP / 2
            while y < box[4]:
                z = box[2] + STEP / 2
                while z < box[5]:
                    key = (round(x), round(y), round(z))
                    p = (x, y, z)
                    if key not in seen and m.solid(p) and not d.solid(p) and not inside_any(p, skip):
                        seen.add(key)
                        f = floor_under(d, p)
                        h = z - f
                        if h > 64.0 and open_around(d, p) and not on_floor(m, p, f):
                            found.append((p, p, h))
                    z += STEP
                y += STEP
            x += STEP
    return found


def said(found: list) -> str:
    return "; ".join(f"new {' '.join(f'{v:.0f}' for v in p)} open to old {' '.join(f'{v:.0f}' for v in q)},"
                     f" {h:.0f} over its floor" for p, q, h in found[:4])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("--digs", type=Path, required=True)
    ap.add_argument("--donor", type=Path, default=DONOR)
    a = ap.parse_args()
    digs = json.loads(a.digs.read_text(encoding="utf-8")).get(a.map.name, [])
    found = open_high(a.map, digs, a.donor)
    ok = not found
    print(f"  {'PASS' if ok else 'FAIL'}  {a.map.name}: no dug space open to the old map higher than a doorway"
          f"  -- {len(digs)} digs, {len(found)} points" + (f": {said(found)}" if found else ""))
    standing = solid_in_air(a.map, digs, a.donor)
    ok2 = not standing
    print(f"  {'PASS' if ok2 else 'FAIL'}  {a.map.name}: nothing a dig built stands in the old air over 64 above its"
          f" floor  -- {len(standing)} points" + (f": {said(standing)}" if standing else ""))
    print(f"SUMMARY 2 cases asserted, {int(not ok) + int(not ok2)} failures")
    return 0 if ok and ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
