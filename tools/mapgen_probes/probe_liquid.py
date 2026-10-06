"""Is there liquid in this column, and where - on one compiled map or two.

The question that settled which room a flood actually filled (ledger rows
173-174): the candidate had ten liquid samples over the third room's centre and
none over the arena's, which is how a whole slice's conclusions turned out to
name the wrong room. Cheap, exact, and it needs no compiler.

    python probe_liquid.py <a.bsp> [b.bsp] x y z [--span N] [--step N]

Walks the column around z (default -96..+32 in eights, the window the flood's
own forgiveness used to sample) and prints the contents at each height, naming
water, slime and lava.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bsp_reader import Bsp  # noqa: E402

SOLID, LAVA, SLIME, WATER = 0x01, 0x08, 0x10, 0x20
LIQUID = LAVA | SLIME | WATER


def name(c: int) -> str:
    if c & SOLID:
        return "SOLID"
    bits = [n for bit, n in ((LAVA, "LAVA"), (SLIME, "SLIME"), (WATER, "WATER"))
            if c & bit]
    return "+".join(bits) if bits else ("EMPTY" if c == 0 else f"0x{c:x}")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    span, step = 96.0, 8.0
    for flag, setter in (("--span", "span"), ("--step", "step")):
        if flag in args:
            i = args.index(flag)
            value = float(args[i + 1])
            if setter == "span":
                span = value
            else:
                step = value
            del args[i:i + 2]
    maps = [Path(a) for a in args if a.lower().endswith(".bsp")]
    nums = [float(a) for a in args if not a.lower().endswith(".bsp")]
    if not maps or len(nums) < 3:
        print(__doc__)
        return 2
    x, y, z = nums[0], nums[1], nums[2]
    for path in maps:
        bsp = Bsp(path)
        print(f"=== {path.parent.name}/{path.name} at {x:.0f} {y:.0f}"
              f" {z:.0f} ===")
        first = None
        n = int(span / step)
        for k in range(-n, int(32.0 / step) + 1):
            zz = z + k * step
            c = bsp.contents(x, y, zz)
            mark = ""
            if c & LIQUID and first is None:
                first = zz
                mark = "   <-- first liquid"
            print(f"   z {zz:7.0f}  contents 0x{c:04x}  {name(c)}{mark}")
        print("   no liquid in the window" if first is None
              else f"   first liquid at z {first:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
