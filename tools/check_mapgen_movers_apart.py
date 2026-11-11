r"""Brief 35 (the PO 11.11 on mg_new_91126: «снова рядом два телепорта. А я говорил что ни телепорты ни джампады ни точки
спавна рядом не делать»; «напиханы как грибы»; «это делает нормальную в целом карту дерьмовой»): teleporters, their exits,
jump pads and spawn points never together - on the plans of every shape, on the finished map, and on his own.

* RED - his map of 3.60 (`data\bsp\mg_new_91126_360.bsp` of his library - 3.61 made it again under its name - or
  --old BSP): the three rows of the map's check red - two discs 91 / 143 u apart, two exits 64 u, five plates within
  384 u (check_mapgen_new_map.mover_rows on the BSP's entities);
* the plans (make_plan over seeds) of his request (a 12-player ring, 2 pairs, 4 pads), his tower request (18619) and an
  open space with three pairs: no two teleporter ends of different pairs within TELE_PAIRS_APART, no two of disc /
  exit / pad / spawn within MOVER_APART (two pads: brief 34's PAD_APART), no third plate within PLATES_NEAR; the spawns
  asked all made; RED per planner: mapgen_scratch_plan.OLD_MOVER_RULES on - a second pair within TELE_PAIRS_APART of
  the first or ends together on some seed;
* GREEN on a built map: his request's best plan built the Studio's way - the three rows of the map's check green.

    python tools/check_mapgen_movers_apart.py [--old BSP] [--seeds N]
Writes into O:\Claude2\_agent_temp\claude\movers_apart_check\. Pinned by the load guard.
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
import mapgen_scratch_plan as pm  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
STUDIO = Path(r"O:\Claude2\MapgenStudio")
WORK = Path(r"O:\Claude2\_agent_temp\claude\movers_apart_check")
FAILED = 0


def row(ok: bool, what: str, said: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {what}" + (f" -- {said}" if said else ""), flush=True)
    return ok


def plan_measure(P) -> dict:
    """The plan's own marks: nearest ends of two pairs, nearest two marks of the four kinds (pads among pads aside),
    the most plates near one, teleporters and spawns made."""
    ms = [m for m in pm.mover_marks(P) if m[0] != "land"]     # a pad's landing is held by spot_ok, measured by its flight
    pairs_near = movers_near = None
    worst_plates = 0
    for i, (k1, m1, z1, p1) in enumerate(ms):
        for (k2, m2, z2, p2) in ms[i + 1:]:
            if pm.layer_of(m1) != pm.layer_of(m2) or abs(z1 - z2) >= pm.ONE_FLOOR_DZ:
                continue
            d = pm._cheb(m1, m2)
            if k1 in ("disc", "exit") and k2 in ("disc", "exit") and p1 != p2:
                pairs_near = d if pairs_near is None else min(pairs_near, d)
            if not (k1 == "pad" and k2 == "pad") and not (p1 is not None and p1 == p2):
                movers_near = d if movers_near is None else min(movers_near, d)
        if k1 in ("exit", "spawn"):
            # the plates' radius the plan kept (it gives only for the spawns asked - brief 35 item 20)
            r_ = int(P.metrics.get("plates_near", pm.PLATES_NEAR))
            n = sum(1 for (k2, m2, z2, _p) in ms if k2 in ("exit", "spawn") and pm.layer_of(m2) == pm.layer_of(m1)
                    and abs(z2 - z1) < pm.ONE_FLOOR_DZ and pm._cheb(m1, m2) <= r_)
            worst_plates = max(worst_plates, n)
    own = [pm._cheb(a, da) for (a, b, da, db) in P.teleports] + [pm._cheb(b, db) for (a, b, da, db) in P.teleports]
    return {"pairs_near": pairs_near, "movers_near": movers_near, "plates": worst_plates, "teleports": len(P.teleports),
            "spawns": len(P.spawns), "own_exit": (min(own), max(own)) if own else None}


def plans(req: dict, seeds: list[int]) -> list:
    out = []
    for s in seeds:
        P = pm.make_plan(dict(req), s)
        if P.failed:
            continue
        out.append((s, P, plan_measure(P)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    # his map of 3.60 - kept as mg_new_91126_360 since 3.61 made it again under its name
    ap.add_argument("--old", type=Path, default=STUDIO / "data" / "bsp" / "mg_new_91126_360.bsp")
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--no-build", action="store_true")
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
    # ---- RED: his map of 3.60 -----------------------------------------------------------------------------------------
    if a.old.is_file():
        rows = {name: (ok, said) for name, ok, said in nm.mover_rows(sv.World(str(a.old)))}
        reds = [n for n, (ok, _s) in rows.items() if not ok]
        row(len(reds) == 3, "RED his map of 3.60: the three rows of the map's check red",
            "; ".join(f"{n.split(':')[0]} {s}" for n, (ok, s) in rows.items()))
    else:
        row(False, f"RED his map of 3.60: {a.old}", "not found")
    # ---- the plans of three shapes, and the RED of the old rules -------------------------------------------------------
    run = STUDIO / "data" / "runs" / "mg_new_91126" / "request.txt"
    his = json.loads(run.read_text(encoding="utf-8").split("scratch=", 1)[1].split("\n", 1)[0])
    tower_run = STUDIO / "data" / "runs" / "mg_new_18619" / "request.txt"
    tower = json.loads(tower_run.read_text(encoding="utf-8").split("scratch=", 1)[1].split("\n", 1)[0])
    space = {"players": 8, "shape": "space", "teleporters": 3}
    seeds = list(range(91126, 91126 + a.seeds))
    for name, req in (("his ring (12 players, 2 pairs, 4 pads)", his), ("his tower (18619)", tower),
                      ("an open space, 3 pairs", space)):
        got = plans(req, seeds)
        bad = []
        for s, P, m in got:
            if m["pairs_near"] is not None and m["pairs_near"] < pm.TELE_PAIRS_APART:
                bad.append(f"{s}: pairs {m['pairs_near']}")
            if m["movers_near"] is not None and m["movers_near"] < pm.MOVER_APART:
                bad.append(f"{s}: movers {m['movers_near']}")
            if m["plates"] > pm.PLATES_MAX:
                bad.append(f"{s}: plates {m['plates']}")
            if m["own_exit"] and not (pm.EXIT_RING[0] <= m["own_exit"][0] and m["own_exit"][1] <= pm.EXIT_RING[1]):
                bad.append(f"{s}: own exit {m['own_exit']}")
        tele = [m["teleports"] for _s, _P, m in got]
        radii = [int(P.metrics.get("plates_near", pm.PLATES_NEAR)) for _s, P, _m in got]
        row(len(got) >= a.seeds // 2 and not bad,
            f"{name}: {len(got)} plans of {a.seeds}, every teleporter end, exit, pad and spawn apart, no third plate within the radius kept",
            f"pairs made {tele}; plates' radius {radii}; broken {bad[:4]}")
        # the Studio's choice (best_plan): the spawns asked all made
        best = [pm.best_plan(dict(req), s_, 24, workers=4)[0] for s_ in seeds[:2]]
        best = [P for P in best if not P.failed]
        short = [f"{len(P.spawns)}/{P.params['spawns']}" for P in best if len(P.spawns) < int(P.params["spawns"])]
        row(best and not short,
            f"{name}: the Studio's choice of plan makes the spawns asked ({[len(P.spawns) for P in best]}), pairs {[len(P.teleports) for P in best]}, "
            f"plates' radius {[P.metrics.get('plates_near') for P in best]}",
            f"the Studio's choice short of spawns: {short}")
        pm.OLD_MOVER_RULES = True
        try:
            got0 = plans(req, seeds)
        finally:
            pm.OLD_MOVER_RULES = False
        bad0 = [s for s, P, m in got0 if (m["pairs_near"] is not None and m["pairs_near"] < pm.TELE_PAIRS_APART)
                or (m["movers_near"] is not None and m["movers_near"] < pm.MOVER_APART) or m["plates"] > pm.PLATES_MAX]
        row(len(bad0) > 0, f"RED {name}: 3.60's rules put ends, exits, pads or spawns together on some plans",
            f"{len(bad0)} of {len(got0)} plans")
    # ---- GREEN: his request built, the map's check -------------------------------------------------------------------
    if not a.no_build:
        import mapgen_scratch as sc
        P = pm.best_plan(dict(his), 91126, 24, workers=4)[0]
        out = WORK / "his"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        _k, said, entry = sc.build_candidate((0, P, P.params, "mg_ma_his", out, GAME, 4))
        if not entry:
            row(False, "his request on this tree: built", str(said)[-300:])
        else:
            rows = nm.mover_rows(sv.World(str(out / "cand0" / "mg_ma_his.bsp")))
            row(all(ok for _n, ok, _s in rows), "his request on this tree, built: the three rows of the map's check green",
                "; ".join(f"{n.split(':')[0]} {s}" for n, ok, s in rows))
    print("PASS" if not FAILED else f"FAIL ({FAILED})")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
