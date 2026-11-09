r"""Brief 34 (the PO 08.11 on his tower mg_new_18619: «джампады вот так наставлены - как кучу говна выкатили в одном
месте»; «можно же лестницы строить, лифты, а не напихивать джампады ради джампадов - всё хорошо в меру»; «лифты как в
небоскрёбах - едут между этажами, останавливаются там»; «нужно проявлять мозги, а не просто напихивать на уровне кучу
повторяемых объектов»): the ways a map climbs by, on maps built the Studio's way (mapgen_scratch.build_candidate).

* RED - his 3.59 map (data\bsp\mg_new_18619_359.bsp of his library, or --old BSP): the pads apart and the like-things rows
  red (five take-offs a cell apart on the atrium's floor);
* GREEN - his request on this tree: built, both rows green, every storey climbed by a flight, the lift stopping on every
  storey, the express from a corner, the perches by pad; the ways in the record;
* a tower of a lift alone (no stairs, no pads, no perches): the people's survey rides the lift - every storey's floor
  reached from the spawns; RED: the survey not riding trains (mapgen_map_survey.TRAINS_RIDDEN off) - the storeys only
  the lift reaches go out of reach; the engine takes the map as a base;
* the express (his tower on 3.60's first build: «джампадов с пола атриума 0 из 1»): his request over 30 seeds - every
  plan has its express pad from a free corner; RED: a perch's rim pad not kept off the free corners
  (mapgen_scratch_tower.KEEP_FREE_CORNERS off) - some plans lose the express;
* the perch wells' lamps (his tower on 3.60's second build: 3 candidates of 10 «nothing hanging … in the air», a
  lamp panel set at the gallery's ceiling over a well open to the sky): his request's map - nothing hanging (the
  people's survey); over his run's candidate seeds no lamp panel over a well; RED: the lamp not taking its cell's own
  ceiling (mapgen_scratch_plan.FREE_LAMP_CELL_CEIL off) - panels over wells;
* the run's own check as the Studio runs it (check_mapgen_new_map.py MAP --asked --plan, the scratch folder): the rows
  «pads apart» and «repetition» on his request's map; RED: without the skeleton's map beside the plan the rows are not
  written (3.60's first install: his map's checks had neither);
* the ledges' undersides (the PO 08.11, mg_new_594: «у двух площадок наверху уровня снизу небо просвечивает вместо
  текстуры плиты»; seen on 3.59 too): on his request's map no rock underside is sky below the map's top, and every
  well over the top gallery ends in the sky; RED: the old rule (mapgen_scratch_world.SKY_UNDERSIDES on) - the ledges'
  slabs drawn as sky from below, the wells capped by the gallery's ceiling;
* «ways with no reason»: RED - the rooms planner's reason test off (NO_REASON_S -1) on seed 26105, a pad 1.65 s from its
  landing on foot comes back and the plan's measure counts it; GREEN - with the test, none.

    python tools/check_mapgen_tower_ways.py [--old MAP]
Writes into O:\Claude2\_agent_temp\claude\tower_ways_check\. Pinned by the load guard.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard  # noqa: E402
import mapgen_map_survey as sv  # noqa: E402
import mapgen_scratch as sc  # noqa: E402
import mapgen_scratch_fixtures as fix_mod  # noqa: E402
import mapgen_scratch_plan as pm  # noqa: E402
import mapgen_scratch_tower as tw  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
STUDIO = Path(r"O:\Claude2\MapgenStudio")
WORK = Path(r"O:\Claude2\_agent_temp\claude\tower_ways_check")
FAILED = 0


def row(ok: bool, what: str, said: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {what}" + (f" -- {said}" if said else ""), flush=True)
    return ok


def sky_bottoms(text: str) -> list:
    """The builder's .map: (z, x0, y0, x1, y1) of every brush's bottom face with the sky flag (S_SKY 4 - the style's sky
    texture is any name: e2u1/w_white on a q2duel1 style)."""
    import re
    out = []
    for block in re.findall(r"\{\n((?:\(.*\n)+)\}", text):
        faces = []
        for ln in block.splitlines():
            m = re.match(r"\(\s*(\S+) (\S+) (\S+)\s*\)\s*\(\s*(\S+) (\S+) (\S+)\s*\)\s*\(\s*(\S+) (\S+) (\S+)\s*\)"
                         r"\s+(\S+)((?:\s+\S+){8})", ln)
            if m:
                v = [float(x) for x in m.groups()[:9]]
                rest = m.group(11).split()
                faces.append(((v[0:3], v[3:6], v[6:9]), int(rest[6]) & 4))
        if not faces:
            continue
        zs = [p[2] for (pts, _s) in faces for p in pts]
        xs = [p[0] for (pts, _s) in faces for p in pts]
        ys = [p[1] for (pts, _s) in faces for p in pts]
        for (pts, sky) in faces:
            if sky and all(p[2] == min(zs) for p in pts):
                out.append((min(zs), min(xs), min(ys), max(xs), max(ys)))
    return out


def build(P, name):
    out = WORK / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    _k, said, entry = sc.build_candidate((0, P, P.params, name, out, GAME, 4))
    return (out / "cand0", entry) if entry else (None, said)


def main() -> int:
    ap = argparse.ArgumentParser()
    # his 3.59 map: kept as mg_new_18619_359 beside the 3.60 one since 08.11
    ap.add_argument("--old", type=Path, default=STUDIO / "data" / "bsp" / "mg_new_18619_359.bsp")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    os.environ["MAPGEN_HELPERS"] = str(STUDIO / "engine" / "helpers")
    os.environ["MAPGEN_Q2TOOL"] = str(STUDIO / "engine" / "q2tool.exe")
    WORK.mkdir(parents=True, exist_ok=True)
    # ---- his tower: 3.59's map (RED) and his request on this tree (GREEN) ------------------------------------------
    run = STUDIO / "data" / "runs" / "mg_new_18619" / "request.txt"
    req = json.loads(run.read_text(encoding="utf-8").split("scratch=", 1)[1].split("\n", 1)[0])
    if a.old.is_file():
        fm = fix_mod.measure_bsp_pads(a.old)
        row(fm["pads_min_apart"] is not None and fm["pads_min_apart"] < 192,
            "RED his 3.59 tower: two pads on one floor closer than 192 - the pads-apart row goes red", f"nearest {fm['pads_min_apart']}")
        row(fm["pads_together"] > fix_mod.REPEAT_MAX, "RED his 3.59 tower: more than two pads together - the repetition row goes red",
            f"{fm['pads_together']} within four cells")
    else:
        row(False, f"RED his 3.59 tower: its map {a.old}", "not found")
    P = pm.best_plan(dict(req), 18619, 24, workers=4)[0]
    cdir, entry = build(P, "mg_tw_his")
    if cdir is None:
        row(False, "his request on this tree: built", str(entry)[-300:])
    else:
        text = (cdir / "mg_tw_his.map").read_text(encoding="latin-1")
        fm = fix_mod.measure_map(text)
        w = P.metrics.get("ways") or {}
        row(fm["pads_min_apart"] is None or fm["pads_min_apart"] >= 191, "his request: two pads on one floor at least 192 apart",
            f"nearest {fm['pads_min_apart']}")
        row(fm["worst"][1] <= fix_mod.REPEAT_MAX, "his request: no more than two like things within four cells", f"{fm['worst']}")
        n = int(P.params["storeys"])
        row(w.get("stairs") == n - 1, f"his request: a flight to every storey ({n - 1})", str(w))
        row(w.get("lifts", 0) >= 1 and all(len(stops) == n for (_c, stops, _d, _n) in P.trains), "his request: a lift stopping on every storey",
            f"{len(P.trains)} lifts, stops {[len(t[1]) for t in P.trains]}")
        ground = [(a_, t_) for (a_, t_, *_r) in P.pads if pm.layer_of(a_) == 0 and P.pad_why.get((a_, t_)) != "perch"]
        row(len(ground) <= 2 and all(P.pad_why.get(g) in ("express", "chain", "shortcut", "shaft") for g in ground),
            "his request: at most two pads from the ground, each with its reason", f"{[P.pad_why.get(g) for g in ground]}")
        row(int(P.metrics.get("pads_no_reason", 0)) == 0, "his request: no pad beside another way to the same place",
            str(P.metrics.get("pads_no_reason")))
        # the run's own check, as the Studio calls it: the skeleton's map beside skeleton.txt, named as the request
        import contextlib
        import io
        import check_mapgen_new_map as nm
        sdir = WORK / "his_scratch"
        shutil.rmtree(sdir, ignore_errors=True)
        sdir.mkdir()
        (sdir / "skeleton.txt").write_bytes((cdir / "skeleton.txt").read_bytes())
        (sdir / "request.json").write_text(json.dumps({"name": "mg_new_18619", **req}), encoding="utf-8")

        def own_rows() -> str:
            buf = io.StringIO()
            asked = json.loads((sdir / "request.json").read_text(encoding="utf-8"))
            plan = next(json.loads(ln[8:]) for ln in (sdir / "skeleton.txt").read_text(encoding="utf-8").splitlines()
                        if ln.startswith("metrics "))
            with contextlib.redirect_stdout(buf):
                nm.report(cdir / "mg_tw_his.bsp", 2, asked, plan, None, sdir / "mg_new_18619.map")
            return buf.getvalue()
        (sdir / "mg_new_18619.map").write_bytes((cdir / "mg_tw_his.map").read_bytes())
        out_ = own_rows()
        row("PASS  pads apart" in out_ and "PASS  repetition" in out_,
            "his request: the run's own check writes «pads apart» and «repetition», both passed",
            "; ".join(ln.strip()[:70] for ln in out_.splitlines() if "pads apart" in ln or "repetition" in ln))
        (sdir / "mg_new_18619.map").unlink()
        out0 = own_rows()
        row("pads apart" not in out0 and "repetition" not in out0,
            "RED without the skeleton's map the run's own check writes neither row", "absent" if "pads apart" not in out0 else "present")
        # the ledges' undersides and the wells' tops, on the map the builder wrote
        import mapgen_scratch_world as world_mod
        top_z = max(s_.ceil for s_ in P.spaces)
        mtext = (cdir / "mg_tw_his.map").read_text(encoding="latin-1")
        skies = sky_bottoms(mtext)
        low = [b_ for b_ in skies if b_[0] < top_z]
        wells = [pm.phys(k_) for k_, cz in P.cell_ceil.items() if k_ in P.owner and cz > P.spaces[P.owner[k_]].ceil]
        capped = [w_ for w_ in wells if not any(b_[0] >= top_z and b_[1] <= w_[0] * 64 and b_[3] >= (w_[0] + 1) * 64
                                                and b_[2] <= w_[1] * 64 and b_[4] >= (w_[1] + 1) * 64
                                                for b_ in skies)]
        perches = [s_ for s_ in P.spaces if s_.kind == "perch"]
        row(perches and wells and not low and not capped,
            "his request: no rock underside is sky below the map's top, every ledge's well ends in the sky",
            f"{len(perches)} ledges, {len(wells)} wells; sky undersides below {top_z}: {low[:3]}; wells capped: {capped}")
        world_mod.SKY_UNDERSIDES = True
        try:
            _r = build(P, "mg_tw_his_red")
        finally:
            world_mod.SKY_UNDERSIDES = False
        if _r[0] is None:
            row(False, "RED the old rule: built", str(_r[1])[-200:])
        else:
            mt0 = (_r[0] / "mg_tw_his_red.map").read_text(encoding="latin-1")
            low0 = [b_ for b_ in sky_bottoms(mt0) if b_[0] < top_z]
            row(len(low0) >= len(perches), "RED the old rule: the ledges' slabs drawn as sky from below",
                f"{len(low0)} sky undersides below {top_z}: {low0[:3]}")
        hs = sv.hanging_brushes(sv.World(str(cdir / "mg_tw_his.bsp")))
        row(not hs, "his request: nothing hanging (the people's survey)", str(hs[:3]))
        rec = json.loads((cdir / "survey.json").read_text(encoding="utf-8"))
        row(not rec.get("majors_unreachable"), "his request: every major item reachable (the people's survey)",
            ", ".join(rec.get("majors_unreachable") or []) or "all")
    # ---- the express from a free corner, over 30 seeds -----------------------------------------------------------------
    def expresses() -> tuple[int, int]:
        got = made = 0
        for s in range(18619, 18649):
            P_ = pm.make_plan(dict(req), s)
            if P_.failed:
                continue
            made += 1
            got += "express" in P_.pad_why.values()
        return got, made
    got, made = expresses()
    row(made > 0 and got == made, "his request over 30 seeds: every plan has its express pad from a free corner", f"{got} of {made}")
    tw.KEEP_FREE_CORNERS = False
    try:
        got0, made0 = expresses()
    finally:
        tw.KEEP_FREE_CORNERS = True
    row(got0 < made0, "RED a perch's rim pad not kept off the free corners: some plans lose the express", f"{got0} of {made0}")
    # ---- the perch wells' lamps, over his run's candidate seeds -------------------------------------------------------
    def panels_over_wells() -> tuple[int, int]:
        n_ = wells = 0
        for s in range(1861994107000, 1861994107020):
            P_ = pm.make_plan(dict(req), s)
            if P_.failed:
                continue
            SH = int(P_.params["storey_height"])
            for kk, ceil in P_.cell_ceil.items():
                sp = P_.spaces[P_.owner[kk]] if kk in P_.owner else None
                if sp is None or ceil <= sp.ceil:
                    continue
                wells += 1
                cx, cy = pm.phys(kk)
                lay = pm.layer_of(kk)
                for (x, y, z, _v, mount) in P_.lights:
                    if (int(x // 64), int(y // 64)) == (cx, cy) and lay * SH <= z < (lay + 1) * SH and mount[0] == "free"                             and not mount[2] and mount[1] - z <= 48:
                        n_ += 1
        return n_, wells
    got, wells = panels_over_wells()
    row(wells > 0 and got == 0, "his request over 20 candidate seeds: no lamp panel over a perch's well", f"{got} panels, {wells} wells")
    pm.FREE_LAMP_CELL_CEIL = False
    try:
        got0, wells0 = panels_over_wells()
    finally:
        pm.FREE_LAMP_CELL_CEIL = True
    row(got0 > 0, "RED the lamp not taking its cell's own ceiling: panels over the wells", f"{got0} panels, {wells0} wells")
    # ---- a tower of a lift alone ---------------------------------------------------------------------------------------
    lift_only = {"players": 2, "shape": "tower", "stairs": 0, "pads": 0, "perches": 0, "lifts": 1, "teleporters": 0}
    P = pm.best_plan(dict(lift_only), 34001, 24, workers=4)[0]
    row(not P.failed and len(P.trains) == 1 and not P.pads, "a tower of a lift alone: planned, its storeys joined by the lift only",
        f"{len(P.trains)} lifts, {len(P.pads)} pads, {P.metrics.get('ways')}")
    cdir, entry = build(P, "mg_tw_lift")
    if cdir is None:
        row(False, "a tower of a lift alone: built", str(entry)[-300:])
    else:
        bsp = cdir / "mg_tw_lift.bsp"
        r = sv.survey(bsp)
        row(r.get("movers", {}).get("trains") == 1 and not r.get("majors_unreachable"),
            "a tower of a lift alone: the people's survey rides it - every major item reached", f"{r.get('movers')}; unreachable {r.get('majors_unreachable')}")
        sv.TRAINS_RIDDEN = False
        try:
            r0 = sv.survey(bsp)
        finally:
            sv.TRAINS_RIDDEN = True
        # from the ground's floor (a spawn stands on every storey - each storey reaches itself): the top storey's floor
        def up_from_ground() -> int:
            w = sv.World(str(bsp))
            hurt = [mb for e in w.ents if e.get("classname") == "trigger_hurt" and (mb := sv.model_bounds(w, e))]
            g = sv.build_graph(w, hurt)
            sv.link_graph(g, w)
            sv.movers(g, w)
            ground = [i for i, (_x, _y, z) in enumerate(g.nodes) if z < 40]
            got = sv.dijkstra(g, ground)
            top_z = (int(P.params["storeys"]) - 1) * int(P.params["storey_height"])
            return sum(1 for i, d in enumerate(got) if d < float('inf') and g.nodes[i][2] >= top_z - 8)
        up = up_from_ground()
        sv.TRAINS_RIDDEN = False
        try:
            up0 = up_from_ground()
        finally:
            sv.TRAINS_RIDDEN = True
        row(up > 0, "a tower of a lift alone: from the ground's floor the survey rides up to the top storey", f"{up} points of the top storey")
        row(up0 == 0, "RED a tower of a lift alone: the survey not riding trains does not get up from the ground",
            f"{up0} points of the top storey reached without it")
        acc, why = sc.engine_accepts(STUDIO / "engine" / "pipeline.exe", bsp, GAME, WORK / "lift_probe")
        row(acc, "a tower of a lift alone: the engine takes it as a base", why)
        shutil.rmtree(WORK / "lift_probe", ignore_errors=True)
    # ---- ways with no reason --------------------------------------------------------------------------------------------
    rooms = {"players": 4, "pads": 3, "teleporters": 2, "levels": 4}
    keep = pm.NO_REASON_S
    pm.NO_REASON_S = -1.0
    try:
        P0 = pm.best_plan(dict(rooms), 26105, 24, workers=1)[0]     # one process: the test off where the plan is made
    finally:
        pm.NO_REASON_S = keep
    row(len(pm.pads_without_reason(P0)) > 0, "RED the reason test off (seed 26105): a pad beside a stair to the same terrace, counted",
        f"{pm.pads_without_reason(P0)}")
    P1 = pm.best_plan(dict(rooms), 26105, 24, workers=4)[0]
    row(int(P1.metrics.get("pads_no_reason", 0)) == 0, "with the reason test: no pad without a reason", str(P1.metrics.get("pads_no_reason")))
    print("PASS" if not FAILED else f"FAIL ({FAILED})")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
