r"""Brief 36 (the PO 11.11, mg_new_91126 on 3.61: «баг с дверью в стене - у неё мерцает текстура при её движении»): a
door was its doorway's whole cell, 64 across - the wall's own thickness - so its broad faces lay in the planes of the wall
over the doorway, faces turned the same way, and the two were drawn in turn as it rose. Now a door stands
mapgen_scratch_world.DOOR_ACROSS (32) thick in the middle of its wall, as people's do.

* RED - his map of 3.61 (`data\bsp\mg_new_91126_361.bsp` of his library, or --old BSP): the row «door faces» of the
  map's check red, every door counted (mapgen_map_survey.door_planes on the BSP's faces);
* people's doors (q2dm3, q2dm6, q2dm8 among the Studio's bases): the same measure finds no door face in a wall's plane
  - it does not fault doors as people build them;
* his request (the run's own request.txt) built the Studio's way on this tree: every door DOOR_ACROSS across, the row
  green; RED - DOOR_ACROSS 64 (3.61's door) in this process, the same plan built again: the row red; RED - the
  door's ends at the doorway's (DOOR_END_IN 0, no stops): the row red where the wall over the doorway shows a face at
  an end (his request: a higher floor's steps on a jamb);
* the survey's door counts (doors, doors behind buttons) the same both ways - the walk still takes a door as a door;
* the engine takes the built map as a base (mapgen_scratch.engine_accepts, plan-only, in memory) - a mover's sides
  are what the rebuild dresses (3.61's pad trigger);
* the other movers on his map and his tower (lifts, trains, buttons): faces in a wall's plane said, not failed.

    python tools/check_mapgen_doors.py [--old BSP] [--no-build] [--no-engine]
Writes into O:\Claude2\_agent_temp\claude\doors_check\. Pinned by the load guard.
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

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
STUDIO = Path(r"O:\Claude2\MapgenStudio")
WORK = Path(r"O:\Claude2\_agent_temp\claude\doors_check")
FAILED = 0


def row(ok: bool, what: str, said: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {what}" + (f" -- {said}" if said else ""), flush=True)
    return ok


def request_of(name: str) -> dict:
    run = STUDIO / "data" / "runs" / name / "request.txt"
    return json.loads(run.read_text(encoding="utf-8").split("scratch=", 1)[1].split("\n", 1)[0])


def build(P, name: str, out: Path):
    import mapgen_scratch as sc
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    _k, said, entry = sc.build_candidate((0, P, P.params, name, out, GAME, 4))
    if not entry:
        return None, str(said)[-300:]
    return out / "cand0" / f"{name}.bsp", entry


def movers_said(bsp: Path) -> str:
    import mapgen_map_survey as sv
    got = {}
    for cls, _lo, _hi, _tr, hits in sv.door_planes(bsp, sv.MOVER_CLASSES):
        n, bad = got.get(cls, (0, 0))
        got[cls] = (n + 1, bad + (1 if hits else 0))
    return ", ".join(f"{c.replace('func_', '')} {b} of {n}" for c, (n, b) in sorted(got.items())) or "no movers"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", type=Path, default=None)
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--no-engine", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    os.environ["MAPGEN_HELPERS"] = str(STUDIO / "engine" / "helpers")
    os.environ["MAPGEN_Q2TOOL"] = str(STUDIO / "engine" / "q2tool.exe")
    WORK.mkdir(parents=True, exist_ok=True)
    import check_mapgen_new_map as nm
    import mapgen_map_survey as sv
    import mapgen_scratch_plan as pm
    import mapgen_scratch_world as wm
    # ---- RED: his map of 3.61 ----------------------------------------------------------------------------------------
    old = a.old or STUDIO / "data" / "bsp" / "mg_new_91126_361.bsp"
    if old.is_file():
        name, ok, said = nm.door_row_of(sv.door_planes(old))
        doors = [p for p in sv.door_planes(old) if p[0] == "func_door"]
        row(not ok and doors and all(p[4] for p in doors), f"RED his map of 3.61 ({old.name}): «{name.split(':')[0]}» red on every door",
            said)
    else:
        row(False, f"RED his map of 3.61: {old}", "not found")
    # ---- people's doors -----------------------------------------------------------------------------------------------
    for base in ("q2dm3", "q2dm6", "q2dm8"):
        p = STUDIO / "engine" / "donors" / f"{base}.bsp"
        if not p.is_file():
            row(False, f"people's doors: {p}", "not found")
            continue
        doors = [d for d in sv.door_planes(p) if d[0] == "func_door"]
        row(doors and not any(d[4] for d in doors), f"people's doors ({base}): no door face in a wall's plane",
            f"{len(doors)} doors, across {sorted(round(min(d[2][0] - d[1][0], d[2][1] - d[1][1])) for d in doors)}")
    if a.no_build:
        print("PASS" if not FAILED else f"FAIL ({FAILED})")
        return 0 if not FAILED else 1
    # ---- GREEN / RED: his request built, the door as 3.62 and as 3.61 build it -----------------------------------------
    import mapgen_scratch as sc
    his = request_of("mg_new_91126")
    P = pm.best_plan(dict(his), 91126, 24, workers=4)[0]
    plain = sum(1 for d in P.doors if d.mover and not getattr(d, "tname", None))
    button = sum(1 for d in P.doors if d.mover and getattr(d, "tname", None))
    built = {}
    for across in (wm.DOOR_ACROSS, 64):
        keep = wm.DOOR_ACROSS
        wm.DOOR_ACROSS = across
        try:
            bsp, entry = build(P, f"mg_dr_{across}", WORK / f"his_{across}")
        finally:
            wm.DOOR_ACROSS = keep
        if bsp is None:
            row(False, f"his request built with doors {across} across", entry)
            continue
        survey = entry[4]
        built[across] = (bsp, survey)
    if wm.DOOR_ACROSS in built:
        bsp, survey = built[wm.DOOR_ACROSS]
        doors = [d for d in sv.door_planes(bsp) if d[0] == "func_door"]
        across = sorted({round(min(d[2][0] - d[1][0], d[2][1] - d[1][1])) for d in doors})
        name, ok, said = nm.door_row_of(sv.door_planes(bsp))
        row(ok and across == [wm.DOOR_ACROSS] and len(doors) == plain + button,
            f"his request on this tree: {len(doors)} doors ({plain} plain, {button} behind buttons), each {wm.DOOR_ACROSS} across, "
            f"«{name.split(':')[0]}» green", f"{said}; across {across}")
        if not a.no_engine:
            acc, why = sc.engine_accepts(STUDIO / "engine" / "pipeline.exe", bsp, GAME, WORK / "probe")
            shutil.rmtree(WORK / "probe", ignore_errors=True)
            row(acc, "his request on this tree: the engine takes it as a base", why)
    if 64 in built:
        name, ok, said = nm.door_row_of(sv.door_planes(built[64][0]))
        row(not ok, f"RED the door 64 across (3.61's) on the same plan: «{name.split(':')[0]}» red", said)
    # RED: the door's ends at the doorway's ends (no stops) - the door 32 across all the same: an end rises along a face
    # of the wall over the doorway seen from beyond its end (a window there, a higher floor's steps on the jamb)
    keep_in = wm.DOOR_END_IN
    wm.DOOR_END_IN = 0
    try:
        bsp0, entry0 = build(P, "mg_dr_ends", WORK / "his_ends")
    finally:
        wm.DOOR_END_IN = keep_in
    if bsp0 is not None:
        name, ok, said = nm.door_row_of(sv.door_planes(bsp0))
        row(not ok, f"RED the door's ends at the doorway's (no stops), {wm.DOOR_ACROSS} across: «{name.split(':')[0]}» red", said)
    else:
        row(False, "RED the door's ends at the doorway's: built", entry0)
    if wm.DOOR_ACROSS in built and 64 in built:
        s32, s64 = built[wm.DOOR_ACROSS][1], built[64][1]
        keys = ("doors", "button_doors")
        row(all(s32.get(k) == s64.get(k) for k in keys),
            "the survey's door counts the same with the thinner door (the walk takes it as a door)",
            ", ".join(f"{k} {s32.get(k)} / {s64.get(k)}" for k in keys))
    # ---- the other movers, said ---------------------------------------------------------------------------------------
    if wm.DOOR_ACROSS in built:
        print(f"   his request's movers with a face in a wall's plane: {movers_said(built[wm.DOOR_ACROSS][0])}")
    try:
        tower = request_of("mg_new_18619")
        T = pm.best_plan(dict(tower), 18619, 24, workers=4)[0]
        bsp, entry = build(T, "mg_dr_tower", WORK / "tower")
        if bsp is not None:
            print(f"   his tower's movers with a face in a wall's plane: {movers_said(bsp)}")
            name, ok, said = nm.door_row_of(sv.door_planes(bsp))
            row(ok, f"his tower (18619) on this tree: «{name.split(':')[0]}»", said)
    except FileNotFoundError:
        print("   his tower: no run of mg_new_18619 in the library")
    print("PASS" if not FAILED else f"FAIL ({FAILED})")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
