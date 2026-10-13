r"""A map made by a COPY of the Studio (a release run beside the installed one - brief 18's last queue, the PO's Studio
window being open) put where the installed Studio and the game look for it.

    python tools/mapgen_side_to_library.py NAME [--side DIR] [--studio DIR] [--game DIR]

Copies SIDE\data\bsp\NAME.bsp, data\maps\NAME.map, data\descriptions\NAME.*, data\runs\NAME\ and data\covers\NAME\
into the installed Studio's data folder, and the .bsp into GAME\baseq2\maps. Says the map's entities, starts, light
and hash; refuses a map with no start or no light.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--side", type=Path, default=Path(r"O:\Claude2\_agent_temp\claude\b18_side\MapgenStudio"))
    ap.add_argument("--studio", type=Path, default=Path(r"O:\Claude2\MapgenStudio"))
    ap.add_argument("--game", type=Path, default=Path(r"O:\Claude2\q2pro-release"))
    a = ap.parse_args()
    src, dst = a.side / "data", a.studio / "data"
    bsp = src / "bsp" / f"{a.name}.bsp"
    if not bsp.is_file():
        print(f"no map at {bsp}")
        return 1
    d = bsp.read_bytes()
    off, size = struct.unpack_from("<ii", d, 8)
    text = d[off:off + size].decode("latin-1")
    _, light = struct.unpack_from("<ii", d, 8 + 7 * 8)
    starts = text.count('"info_player_deathmatch"')
    print(f"{a.name}: {text.count('classname')} entities, {starts} starts, light {light}, "
          f"sha256 {hashlib.sha256(d).hexdigest()[:8]}")
    if not starts or not light:
        print("refused: no start or no light in it")
        return 1
    (dst / "bsp").mkdir(parents=True, exist_ok=True)
    shutil.copy2(bsp, dst / "bsp" / bsp.name)
    for f in (src / "maps").glob(f"{a.name}.map"):
        (dst / "maps").mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst / "maps" / f.name)
    for f in (src / "descriptions").glob(f"{a.name}.*"):
        (dst / "descriptions").mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst / "descriptions" / f.name)
    for sub in ("runs", "covers"):
        if (src / sub / a.name).is_dir():
            shutil.rmtree(dst / sub / a.name, ignore_errors=True)
            shutil.copytree(src / sub / a.name, dst / sub / a.name)
    shutil.copy2(bsp, a.game / "baseq2" / "maps" / bsp.name)
    print(f"in {dst} and {a.game / 'baseq2' / 'maps'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
