r"""Brief 19: a base made from scratch is one the engine takes - its first step (the rebuild and the comparison of
every placement) holds it.

    python tools/check_mapgen_scratch_engine.py [--work DIR] [--engine pipeline.exe]

04.11: the Studio's first run from scratch ended in 12 seconds - ERR_BASELINE, «3 placements do not stand the same
way in both maps; first is ammo_grenades|empty|16»: a hall's corner was chamfered (a 45-degree wall across its
cell) AFTER the items were placed, an item stood on the diagonal, and the base and the engine's rebuild of it
disagreed by an epsilon about whether that point is rock. The fix: corners and pillars never take a cell that holds
an item, a spawn or a mover (`mapgen_scratch_plan.furnish`), and the scratch step asks the engine about every base
before it hands one over (`mapgen_scratch.engine_accepts`, `--engine`).

GREEN: the duel skeleton at the defaults (seed 7000) - the engine accepts it.
RED: the same skeleton with an item on every chamfered corner's diagonal (one diagonal flips by the rebuild's rounding
or not - the 04.11 base had three that did) - the engine must refuse it; the check must say so.
The engine runs in memory mode (`--memory`), `--plan-only`: nothing is built, nothing written to disk.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_scratch as scratch  # noqa: E402
import mapgen_scratch_build as build_mod  # noqa: E402
import mapgen_scratch_plan as plan_mod  # noqa: E402
import mapgen_scratch_style as style_mod  # noqa: E402
import mapgen_scratch_world as world_mod  # noqa: E402

ENGINE = Path(r"O:\Claude2\MapgenStudio\engine\pipeline.exe")
GAME = Path(os.environ.get("MAPGEN_GAME") or r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\b19\engine_guard")


def base(P, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    pal = style_mod.palette({}, P.seed)
    world, brushes, ents = world_mod.build_plan(P, pal, title=name)
    mp = out / f"{name}.map"
    build_mod.write_map(mp, world, brushes, ents)
    ok, tail = build_mod.compile_map(mp, GAME, 4, log=out / "compile.log")
    if not ok:
        raise SystemExit(f"{name} did not compile: {tail[-300:]}")
    return mp.with_suffix(".bsp")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--engine", type=Path, default=ENGINE)
    a = ap.parse_args()
    fails = 0
    P = plan_mod.make_plan({"players": 2}, 7000)
    green = base(P, a.work / "green", "green")
    ok, why = scratch.engine_accepts(a.engine, green, GAME, a.work / "probe_green")
    print(f"  {'PASS' if ok else 'FAIL'}  GREEN: the engine accepts the default duel base  -- {why or 'accepted'}")
    fails += 0 if ok else 1
    # RED: an item onto a chamfered corner's diagonal (the corner's cell centre lies on it)
    R = plan_mod.make_plan({"players": 2}, 7000)
    if not R.chamfers:
        print("  FAIL  RED: the skeleton has no chamfered corner to stand an item on")
        return 1
    for (c, corner, z0, z1) in R.chamfers:
        R.items.append(("ammo_grenades", c, z0, "RED: on the corner's diagonal"))
    red = base(R, a.work / "red", "red")
    ok, why = scratch.engine_accepts(a.engine, red, GAME, a.work / "probe_red")
    print(f"  {'PASS' if not ok else 'FAIL'}  RED: items on {len(R.chamfers)} corners' diagonals - the engine refuses the base  -- "
          f"{why or 'accepted (the check cannot see the defect)'}")
    fails += 1 if ok else 0
    print("PASS" if not fails else f"FAIL ({fails})")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
