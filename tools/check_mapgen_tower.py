r"""Brief 25 B: a map of the shape «tower» (whole storeys over one footprint) through the whole chain - plan, the rooms'
builder, compile, the people's measure (floor over floor, levels, the storeys' reach by pads and drops) and, with
--engine, the generator's own first step on it (engine_accepts: --plan-only --memory, nothing on the disk).

    python tools/check_mapgen_tower.py [--players 4] [--seed 25101] [--params '{"storeys": 3}'] [--engine]
Writes into O:\Claude2\_agent_temp\claude\tower_check\<seed>\. Pinned by the load guard.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard  # noqa: E402
import mapgen_scratch_build as bm  # noqa: E402
import mapgen_scratch_plan as pm  # noqa: E402
import mapgen_scratch_style as st  # noqa: E402
import mapgen_scratch_world as wm  # noqa: E402
import mapgen_map_survey as sv  # noqa: E402
import mapgen_space_survey as ss  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\tower_check")
STUDIO = Path(r"O:\Claude2\MapgenStudio")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=4)
    ap.add_argument("--seed", type=int, default=25101)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--engine", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    params = dict(json.loads(a.params), players=a.players, shape="tower")
    q = pm.defaults(dict(params))
    out = WORK / str(a.seed)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    plans = pm.best_plan(dict(params), a.seed, 24, workers=1)
    if not plans:
        print("FAIL no plan")
        return 1
    P = plans[0]
    print("plan:", json.dumps({k: P.metrics.get(k) for k in ("storeys", "shafts", "perches", "pads", "floor_area", "score")}),
          f"{len(P.spaces)} spaces, {len(P.doors)} doors, {len(P.spawns)} spawns")
    pal = st.palette(P.params.get("style") or {}, P.seed, players=q["players"], game=GAME)
    world, brushes, ents = wm.build_plan(P, pal, title=f"tower {a.seed}")
    mp = out / "mg_tower.map"
    bm.write_map(mp, world, brushes, ents)
    t = time.time()
    ok, tail = bm.compile_map(mp, GAME, 4, log=out / "compile.log")
    print(f"compiled {ok} in {time.time() - t:.0f} s" + ("" if ok else " " + tail[-300:]))
    if not ok:
        return 1
    bsp = mp.with_suffix(".bsp")
    r = sv.survey(bsp)
    sp = ss.space_part(bsp)
    keys = ("walk_area_mu2", "footprint", "levels", "vertical_span", "stacked_share", "sky_share", "share_corridor", "share_medium",
            "share_open", "long_lines", "majors_at_height", "majors_unreachable", "spawns", "dark_floor_share", "floor_light_p50",
            "spawn_to_spawn_s", "spawn_to_spawn_max_nearest_s", "spawn_pairs_seen_under_300")
    print("measure:", json.dumps({k: r.get(k) for k in keys}, ensure_ascii=False))
    print("movers:", sp["movers"], "islands:", sp["islands"]["count_over_0.02mu2"], "void edge", sp["outline_void_share"])
    rows = [("floor over floor ≥ 0.5", (r.get("stacked_share") or 0) >= 0.5, r.get("stacked_share")),
            (f"levels = storeys ± 1", abs((r.get("levels") or 0) - q["storeys"]) <= 1, r.get("levels")),
            ("every major item reachable", not r.get("majors_unreachable"), r.get("majors_unreachable")),
            ("every pad flown", sum(1 for p_ in sp["pads"] if p_["points"] > 3) == sp["movers"]["pads"] and sp["movers"]["pads"] >= len(P.pads),
             f"{sp['movers']['pads']} landing of {len(P.pads)}")]
    if a.engine:
        import mapgen_scratch as sc
        os.environ["MAPGEN_Q2TOOL"] = str(STUDIO / "engine" / "q2tool.exe")
        t = time.time()
        acc, why = sc.engine_accepts(STUDIO / "engine" / "pipeline.exe", bsp, GAME, out / "probe")
        rows.append(("the engine takes it as a base", acc, f"{why} ({time.time() - t:.0f} s)"))
        shutil.rmtree(out / "probe", ignore_errors=True)
    for name, ok_, said in rows:
        print(f"{'PASS' if ok_ else 'FAIL'} {name}: {said}")
    allok = all(o for _, o, _ in rows)
    print("PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
