"""Where a glass pane can fit in a donor's own walls, and what stops the rest.

The planner's wall census (`deal_windows`, `opening_is_safe_why` in
`src/mapgen/mapgen_geometry_edit.c`) asks every solid BOX brush of the donor
whether it is a wall a window can be cut through: its thickness, its length
along the wall, its height over a sill, air on both sides of the opening and
rock in its middle. On q2dm1 at seed 1 it glazes four walls, and the PO asked
for «много стекол». This repeats the census's size and air questions in
Python, under the planner's own limits and under named relaxations, so the
decision about which limit to move is taken on counts rather than on taste.

It does NOT ask the questions only the C planner can: the room finder's rooms
on both sides, the per-room cap, whether the region is all box brushes, the
other openings already dealt. A count here is an upper bound on what the
planner would glaze, per variant.

    python probe_window_sites.py <map.bsp>
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bsp_reader import Bsp  # noqa: E402

CONTENTS_SOLID = 1


def lump(data: bytes, i: int) -> bytes:
    off, size = struct.unpack_from("<ii", data, 8 + 8 * i)
    return data[off:off + size]


def box_brushes(path: Path):
    """Every solid brush whose sides are all axial, as (mins, maxs)."""
    data = path.read_bytes()
    planes, brushes, sides = lump(data, 1), lump(data, 14), lump(data, 15)
    out = []
    for b in range(len(brushes) // 12):
        first, count, contents = struct.unpack_from("<iii", brushes, 12 * b)
        if not contents & CONTENTS_SOLID:
            continue
        mins = [None, None, None]
        maxs = [None, None, None]
        axial = True
        for s in range(first, first + count):
            planenum, _tex = struct.unpack_from("<Hh", sides, 4 * s)
            nx, ny, nz, dist, _t = struct.unpack_from("<4fi", planes,
                                                      20 * planenum)
            n = (nx, ny, nz)
            axis = next((a for a in range(3) if abs(abs(n[a]) - 1.0) < 1e-4),
                        None)
            if axis is None:
                axial = False
                break
            if n[axis] > 0:
                maxs[axis] = dist if maxs[axis] is None else min(maxs[axis],
                                                                 dist)
            else:
                mins[axis] = -dist if mins[axis] is None else max(mins[axis],
                                                                  -dist)
        if axial and None not in mins and None not in maxs:
            out.append((mins, maxs))
    return out


def sites(bsp: Bsp, walls, wide: float, jamb: float, thin_max: float,
          rows: bool):
    """Panes the census's own questions would admit, and refusals by name."""
    why = {"not a wall": 0, "no room across": 0, "not tall enough": 0,
           "no air on a side": 0, "no rock in the middle": 0}
    panes = walls_glazed = 0
    for mins, maxs in walls:
        for thin in (0, 1):
            across = 1 - thin
            thick = maxs[thin] - mins[thin]
            if thick < 8.0 or thick > thin_max:
                why["not a wall"] += 1
                continue
            length = maxs[across] - mins[across]
            if length < wide + 2.0 * jamb:
                why["no room across"] += 1
                continue
            tall = maxs[2] - mins[2]
            sill = max(24.0, tall / 3.0)
            if tall < sill + 64.0 + 16.0:
                why["not tall enough"] += 1
                continue
            foot, top = mins[2] + sill, mins[2] + sill + 64.0
            # as many openings along the wall as fit with a 16 pier between
            count = 1
            if rows:
                count = max(1, int((length - 2.0 * jamb + 16.0)
                                   // (wide + 16.0)))
            span = count * wide + (count - 1) * 16.0
            start = 0.5 * (mins[across] + maxs[across]) - 0.5 * span
            good = 0
            refused = None
            for k in range(count):
                lo = start + k * (wide + 16.0)
                hi = lo + wide
                ok = True
                for side in (mins[thin] - 4.0, maxs[thin] + 4.0):
                    u = lo + 8.0
                    while u <= hi - 8.0 and ok:
                        z = foot + 8.0
                        while z <= top - 8.0 and ok:
                            p = [0.0, 0.0, z]
                            p[thin], p[across] = side, u
                            if bsp.contents(*p) & CONTENTS_SOLID:
                                ok = False
                                refused = "no air on a side"
                            z += 16.0
                        u += 16.0
                if ok:
                    u = lo + 8.0
                    while u <= hi - 8.0 and ok:
                        z = foot + 8.0
                        while z <= top - 8.0 and ok:
                            p = [0.0, 0.0, z]
                            p[thin] = 0.5 * (mins[thin] + maxs[thin])
                            p[across] = u
                            if not bsp.contents(*p) & CONTENTS_SOLID:
                                ok = False
                                refused = "no rock in the middle"
                            z += 16.0
                        u += 16.0
                if ok:
                    good += 1
            if good:
                panes += good
                walls_glazed += 1
                break          # one axis per brush, as the census does
            why[refused or "no air on a side"] += 1
    return walls_glazed, panes, why


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    bsp = Bsp(path)
    walls = box_brushes(path)
    print(f"{path.name}: {len(walls)} solid box brushes")
    variants = [
        ("the planner's limits: 64 wide, 16 jambs, 8..80 thick, one pane",
         64.0, 16.0, 80.0, False),
        ("a row of panes along each wall, same sizes", 64.0, 16.0, 80.0, True),
        ("48 wide with 8 jambs, one pane", 48.0, 8.0, 80.0, False),
        ("walls up to 128 thick, one pane", 64.0, 16.0, 128.0, False),
        ("48 wide, 8 jambs, up to 128 thick, rows", 48.0, 8.0, 128.0, True),
    ]
    for name, wide, jamb, thin_max, rows in variants:
        glazed, panes, why = sites(bsp, walls, wide, jamb, thin_max, rows)
        refusals = ", ".join(f"{n} {why[n]}" for n in why)
        print(f"  {name}: {glazed} walls, {panes} panes; refused {refusals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
