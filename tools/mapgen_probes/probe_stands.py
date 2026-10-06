"""`MapGenBsp_Stands`, exactly as the gate asks it, on two compiled maps.

Three questions and nothing else (`src/mapgen/mapgen_bsp.c`, `MapGenBsp_Stands`):
the point itself is not solid, EIGHT below it is solid, and FORTY-SIX above it is
not solid. The z+46 sample is deliberately off the world's eight-unit lattice, and
it is the one a contents column stepping in eights can never see - which cost
three measurements on 2026-09-13 before the head sample was asked (ledger row
160, assignment 19's rule R7: ask the gate's own three questions first).

    python probe_stands.py <a.bsp> <b.bsp> x y z [x y z ...]

Prints, per point, whether each map stands there and all three samples, marking
every place where A stands and B does not - which is the shape of «this edit took
a way away».
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bsp_reader import Bsp  # noqa: E402

SOLID = 0x01


def stands(bsp: Bsp, x: float, y: float, z: float):
    here = bsp.contents(x, y, z)
    below = bsp.contents(x, y, z - 8.0)
    head = bsp.contents(x, y, z + 46.0)
    ok = not (here & SOLID) and bool(below & SOLID) and not (head & SOLID)
    return ok, here, below, head


def main() -> int:
    if len(sys.argv) < 6:
        print(__doc__)
        return 2
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    nums = [float(v) for v in sys.argv[3:]]
    if len(nums) % 3:
        print("points come in threes")
        return 2
    ba, bb = Bsp(a), Bsp(b)
    print(f"A = {a.parent.name}/{a.name}")
    print(f"B = {b.parent.name}/{b.name}")
    print()
    print(f"{'point':>22}  {'A':>6} {'here':>6} {'below':>6} {'head':>6}"
          f"   {'B':>6} {'here':>6} {'below':>6} {'head':>6}")
    lost = 0
    for i in range(0, len(nums), 3):
        x, y, z = nums[i], nums[i + 1], nums[i + 2]
        oa, ha, la, da = stands(ba, x, y, z)
        ob, hb, lb, db = stands(bb, x, y, z)
        flag = ""
        if oa and not ob:
            flag = "   <-- A stands, B does NOT"
            lost += 1
        print(f"{x:7.0f} {y:7.0f} {z:6.0f}  {str(oa):>6} {ha:6d} {la:6d}"
              f" {da:6d}   {str(ob):>6} {hb:6d} {lb:6d} {db:6d}{flag}")
    print()
    print(f"{lost} of {len(nums) // 3} sampled places stand in A and not in B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
