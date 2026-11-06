r"""How high a ledge a player gets onto without help - measured by the engine's own walk (brief 20 D2).

The survey's walk (tools/mapgen_map_survey.py) jumps 44 units at most; the game's player jumps at 270 u/s against a
gravity of 800 (src/common/pmove/template.c 713/715) and steps 18 up during the arc (STEPSIZE, line 19). Which ledge he
really gets onto is asked of the engine's walk - the shared pmove over a compiled map (tools/mapgen_reach_gate.c): one
small room per height, a block from the floor to that height with a megahealth on it, no launcher (no rocket jump).

    python tools/mapgen_jump_height_probe.py [--work DIR] [--heights 40,44,...]

Prints, per height, whether the item on the block is in a player's reach.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_geometry_fixtures as fx  # noqa: E402
from check_mapgen_reach_gate import build_gate, compile_map  # noqa: E402


def room(path: Path, h: int) -> None:
    brushes = fx.hollow_room((-384, -384, 0), (384, 384, 384), thickness=64)
    brushes.append(fx.box((128, -64, 0), (256, 64, h)))
    ents = [fx.spawn((-256, 0, 32)), fx.light((0, 0, 320)),
            {"classname": "item_health_mega", "origin": f"192 0 {h + 16}"}]
    fx.write_map(path, brushes, ents, f"jump {h}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=Path(r"O:\Claude2\_agent_temp\claude\b19\jump_probe"))
    ap.add_argument("--heights", default="40,44,48,52,56,60,64,72")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    gate = build_gate(a.work)
    print("height  item on the block")
    for h in [int(x) for x in a.heights.split(",")]:
        m = a.work / f"jump_{h}.map"
        room(m, h)
        if (why := compile_map(m)) is not None:
            print(f"{h:6d}  the map did not build: {why}")
            continue
        run = subprocess.run([str(gate), str(m.with_suffix(".bsp"))], capture_output=True, text=True, timeout=600)
        out = run.stdout + run.stderr
        miss = re.search(r"(\d+) of (\d+) pickup\(s\) are where no player can get", out)
        print(f"{h:6d}  {'NOT reached' if miss and int(miss.group(1)) else 'reached'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
