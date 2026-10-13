r"""A finished map's player starts put back over their floors (brief 18, mg_b18_q3t2 of 13.10; the PO's rule: a small
defect is fixed in the finished map, the generator after).

    python tools/mapgen_starts_to_floor.py MAP.bsp [MAP.bsp ...] [--over 15] [--dry]

A base grown tall carried its starts up with everything else: q3t2's stand 15 over their floors, and at x3.11 that
is 46.6 - the game puts a player nine over a start and he falls 31 to the floor, harmless, but the delivery gate asks
a floor within 32 of his feet and said «over no floor» of 12 starts of 13. The generator now puts a start, like a
pickup, as high over its floor as it stood in the donor (MapGenWarp_KeepDrops); this does the same to a map already
made: every `info_player_*` whose floor lies more than 24 and no more than 96 under its origin is set OVER (15: the
donor's own; 24 is a start on its feet) above that floor. The entity text alone is written; nothing is compiled.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_mapgen_static import Bsp  # noqa: E402
from mapgen_light_calibrate import entity_text, with_entities  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="+", type=Path)
    ap.add_argument("--over", type=float, default=15.0)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    for path in a.maps:
        raw = path.read_bytes()
        text = entity_text(raw)
        b = Bsp(path)
        moved, said = 0, []

        def put(m: re.Match) -> str:
            nonlocal moved
            block = m.group(0)
            cls = re.search(r'"classname"\s+"(info_player_[a-z_]+)"', block)
            org = re.search(r'"origin"\s+"(-?[\d.]+) (-?[\d.]+) (-?[\d.]+)"', block)
            if not cls or not org:
                return block
            x, y, z = (float(v) for v in org.groups())
            if b.solid([x, y, z + 9.0]):
                return block                        # in a solid as it stands: not this tool's
            floor = next((z - d for d in range(1, 97) if b.solid([x, y, z - d])), None)
            if floor is None or z - floor <= 24.0:
                return block
            new = floor + 1.0 + a.over              # the first solid unit is one under the floor's top
            moved += 1
            said.append(f"{cls.group(1)} {x:g} {y:g} {z:g} -> {new:g} ({z - floor - 1:.0f} over its floor)")
            return block.replace(org.group(0), f'"origin" "{x:g} {y:g} {new:g}"')

        out = re.sub(r"\{[^{}]*\}", put, text)
        print(f"{path.name}: {moved} starts put {a.over:g} over their floors" + (" (dry)" if a.dry else ""))
        for line in said:
            print("  " + line)
        if moved and not a.dry:
            path.write_bytes(with_entities(raw, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
