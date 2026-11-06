r"""Brief 25 A0-A3: a map of the shape «space» (islands in the void) through the whole chain - plan, brushes, compile,
the people's measure (`mapgen_space_survey`: islands, pads flown, the edge over the void, where the power items lie)
and, with `--engine`, the generator's own first step on it (`mapgen_scratch.engine_accepts`: pipeline.exe
`--plan-only --memory`, nothing built, nothing on the disk) - the base the Studio's run would hand it.

PASS when the compiled map: has the islands asked (± 2, the survey's walk-joined parts of 0.02 mu² and more), at least the
pad-only islands asked, every island reached from the spawns and back, an edge over the void at least what the edges
asked (open 0.30, some 0.15, railings 0.05 of the outline), every pad flown to a landing, the major items reachable, no
spawn on a pad-only island, and (with --engine) the engine takes it.

    python tools/check_mapgen_space.py [--players 4] [--seed 25001] [--params '{"edges": "some"}'] [--engine]
Writes into O:\Claude2\_agent_temp\claude\space_check\<seed>\ (map, bsp, plan.png, measure.json). Pinned by the load
guard; no pipeline run without --engine.
"""
from __future__ import annotations

import argparse
import json
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
import mapgen_space_survey as ss  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\space_check")
STUDIO = Path(r"O:\Claude2\MapgenStudio")
VOID_MIN = {"open": 0.30, "some": 0.15, "railings": 0.05}


def check(params: dict, seed: int, engine: bool, keep: bool = True, tries: int = 24, workers: int = 4) -> tuple[bool, dict]:
    out = WORK / str(seed)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    q = pm.defaults(dict(params, shape="space"))
    plans = pm.best_plan(dict(params, shape="space"), seed, tries, workers=workers)
    if not plans:
        return False, {"why": "no plan"}
    P = plans[0]
    pal = st.palette(P.params.get("style") or {}, P.seed, players=q["players"], game=GAME)
    world, brushes, ents = wm.build_plan(P, pal, title=f"space {seed}")
    mp = out / "mg_space.map"
    bm.write_map(mp, world, brushes, ents)
    try:
        pm.draw(P, out / "plan.png")
    except Exception as e:  # noqa: BLE001
        print(f"  (no picture: {e})")
    t = time.time()
    ok, tail = bm.compile_map(mp, GAME, 4, log=out / "compile.log")
    res = {"plan": {k: P.metrics.get(k) for k in ("islands", "platforms", "bridges", "pad_only", "pads", "drops",
                                                   "teleporters", "floor_area", "vertical_span", "railing_share", "score")},
           "compile_s": round(time.time() - t), "compiled": ok}
    if not ok:
        res["why"] = tail[-300:]
        return False, res
    r = ss.analyse(mp.with_suffix(".bsp"))
    isl = r["islands"]
    reach_all = all(x.get("entered_by") or x.get("spawn") for x in isl["list"])
    unreach = [m["item"] for m in r["majors"] if m.get("island") is None and "reached_by" not in m]
    pads_flown = sum(1 for p in r["pads"] if p["points"] > 3)
    po = set(P.metrics.get("pad_only_groups") or [])
    spawn_on_pad_only = any(P.owner.get(c) in po and P.spaces[P.owner[c]].pattern == "perch" for (c, _z, _a) in P.spawns)
    rows = [
        ("islands asked ± 2", abs(isl["count_over_0.02mu2"] - q["islands"]) <= 2, f"{isl['count_over_0.02mu2']} of {q['islands']}"),
        ("pad-only islands ≥ asked", isl["reached_only_by_pad_or_teleport"] >= q["pad_only"],
         f"{isl['reached_only_by_pad_or_teleport']} (asked {q['pad_only']})"),
        ("every island entered from another (or a spawn's)", reach_all, ""),
        (f"edge over the void ≥ {VOID_MIN[q['edges']]:.2f} ({q['edges']})", r["outline_void_share"] >= VOID_MIN[q["edges"]],
         f"{r['outline_void_share']}"),
        ("every pad flown", pads_flown == r["movers"]["pads"] and r["movers"]["pads"] >= len(P.pads),
         f"{pads_flown} flown, {r['movers']['pads']} landing, {len(P.pads)} planned"),
        ("every major item reachable", not unreach, ", ".join(unreach) or "all"),
        ("no spawn on a perch only a pad reaches", not spawn_on_pad_only, ""),
    ]
    if engine:
        import mapgen_scratch as sc
        import os
        os.environ["MAPGEN_Q2TOOL"] = str(STUDIO / "engine" / "q2tool.exe")
        t = time.time()
        acc, why = sc.engine_accepts(STUDIO / "engine" / "pipeline.exe", mp.with_suffix(".bsp"), GAME, out / "probe")
        rows.append(("the engine takes it as a base", acc, f"{why} ({time.time() - t:.0f} s)"))
        shutil.rmtree(out / "probe", ignore_errors=True)
    res["rows"] = rows
    res["measure"] = {"survey": r["survey"], "movers": r["movers"], "outline_void_share": r["outline_void_share"],
                      "floor_within_64_of_void": r["floor_within_64_of_void"], "islands": isl,
                      "majors": r["majors"], "pads": r["pads"]}
    (out / "measure.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return all(ok_ for _, ok_, _ in rows), res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=4)
    ap.add_argument("--seed", type=int, default=25001)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--engine", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    params = dict(json.loads(a.params), players=a.players)
    ok, res = check(params, a.seed, a.engine)
    print("plan:", json.dumps(res.get("plan"), ensure_ascii=False), f"compile {res.get('compile_s')} s")
    if "why" in res:
        print("FAIL", res["why"])
        return 1
    s = res["measure"]["survey"]
    print("measure:", json.dumps({k: s.get(k) for k in ("walk_area_mu2", "footprint", "levels", "vertical_span", "sky_share",
                                                        "share_open", "long_lines", "majors_at_height")}),
          "movers", res["measure"]["movers"])
    for name, ok_, said in res["rows"]:
        print(f"{'PASS' if ok_ else 'FAIL'} {name}: {said}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
