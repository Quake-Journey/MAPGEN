"""How well-known maps build their scripted pieces: the knowledge base for movers, triggers and traps.

The PO, 13.11.2026 (clips O:\\Claude2\\q2pro\\Bugs\\2): q2dm3's trains riding over lava and slime and its glass room whose
doors close on two buttons while lava rises in it round the hyperblaster; q2dm4's rotating flap by the quad, its bent
bridge over lava, its ladder out of the water; q2dm6's shutters on a timer over the quad, the wall that turns when the
body armour is taken, the drum rotating over lava by the railgun's beam, the three platforms that sink into lava when
stepped on. «Всё такое должен уметь строить генератор ... Именно вариации, а не 100% повторение».

Each scripted entity of a map (its BSP read as the game reads it): class, size, travel, speed, wait, what fires it
(touch, a button, a floor plate, a timer, an item taken, a relay with its delay), what is under it (lava, slime,
water, a drop) and the valuable items within 384 u. Per map a list of «pieces» - the movers a trigger chain joins
into one - each sorted into a kind:
  train      - a func_train on path corners (riding platform): the path's length, corners, loop or there-and-back;
  plat       - a func_plat (lift);
  door       - a func_door opened by touch (a plain door);
  trap       - a chain that closes doors and moves a liquid (func_water) or hurts: q2dm3's glass room;
  timed      - doors a func_timer opens and closes: q2dm6's shutters;
  sink       - floor doors a plate under them lowers (into a liquid): q2dm6's platforms;
  pickup     - a mover fired by a plate where an item lies (or the item's own target): q2dm6's wall;
  button     - doors or movers a button fires;
  rotating   - a func_rotating (a drum, a flap, a fan): axis, speed, damage on touch.

    python tools/mapgen_mover_practice.py            # all the families -> tools/mapgen_mover_practice.json
    python tools/mapgen_mover_practice.py q2dm3 q2dm6
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_item_practice as ip  # noqa: E402

OUT = HERE / "mapgen_mover_practice.json"
LAVA, SLIME, WATER, SOLID = 8, 16, 32, 1
MOVERS = ("func_train", "func_door", "func_door_rotating", "func_plat", "func_rotating", "func_water", "func_button",
          "func_wall", "func_explosive", "func_conveyor", "func_killbox")
TRIGGERS = ("trigger_multiple", "trigger_once", "trigger_relay", "trigger_counter", "func_timer", "trigger_hurt",
            "trigger_push", "trigger_always", "target_explosion")


def vec(s: str) -> list:
    try:
        v = [float(x) for x in (s or "").split()]
        return v if len(v) == 3 else [0.0, 0.0, 0.0]
    except ValueError:
        return [0.0, 0.0, 0.0]


def move_dir(angle: float) -> list:
    """A door's way by its «angle» (-1 up, -2 down)."""
    if angle == -1:
        return [0.0, 0.0, 1.0]
    if angle == -2:
        return [0.0, 0.0, -1.0]
    a = math.radians(angle)
    return [round(math.cos(a), 3), round(math.sin(a), 3), 0.0]


def under(b, x, y, z0) -> str:
    """What is under a point: the first non-air going down 512 u - lava, slime, water, floor (with its depth) or a drop."""
    for dz in range(0, 512, 8):
        c = b.point_contents((x, y, z0 - dz))
        if c & LAVA:
            return f"lava {dz}"
        if c & SLIME:
            return f"slime {dz}"
        if c & WATER:
            return f"water {dz}"
        if c & SOLID:
            return f"floor {dz}"
    return "drop"


def study(path: str) -> dict:
    b = oracle.load(Path(path))
    ents = b.entities()
    by_name: dict = {}
    for i, e in enumerate(ents):
        if e.get("targetname"):
            by_name.setdefault(e["targetname"], []).append(i)
    items = [(e["classname"], vec(e.get("origin"))) for e in ents if ip.kind_of(e.get("classname", ""))]

    def box(e):
        m = e.get("model", "")
        if m.startswith("*") and int(m[1:]) < len(b.models):
            md = b.models[int(m[1:])]
            o = vec(e.get("origin")) if e.get("classname") in ("func_rotating", "func_door_rotating") else [0, 0, 0]
            return [md.mins[k] + o[k] for k in range(3)], [md.maxs[k] + o[k] for k in range(3)]
        v = vec(e.get("origin"))
        return v, v

    rec = []
    for i, e in enumerate(ents):
        cl = e.get("classname", "")
        if cl not in MOVERS and cl not in TRIGGERS and not (cl == "path_corner"):
            continue
        if cl == "path_corner":
            continue
        lo, hi = box(e)
        size = [round(hi[k] - lo[k]) for k in range(3)]
        mid = [(lo[k] + hi[k]) / 2 for k in range(3)]
        r = {"i": i, "cls": cl, "size": size, "mid": [round(v) for v in mid], "target": e.get("target", ""),
             "targetname": e.get("targetname", ""), "speed": float(e.get("speed") or 0), "wait": float(e.get("wait") or 0),
             "delay": float(e.get("delay") or 0), "dmg": float(e.get("dmg") or 0), "spawnflags": int(float(e.get("spawnflags") or 0)),
             "team": e.get("team", "")}
        if cl in MOVERS and cl not in ("func_button",):
            r["under"] = under(b, mid[0], mid[1], lo[2] - 1)
        if cl in ("func_door", "func_water", "func_button"):
            d = move_dir(float(e.get("angle") or 0))
            lip = float(e.get("lip") or (8 if cl != "func_button" else 4))
            extent = abs(d[0]) * size[0] + abs(d[1]) * size[1] + abs(d[2]) * size[2]
            r["move"] = [round(v * (extent - lip)) for v in d]
        if cl == "func_door_rotating":
            r["distance"] = float(e.get("distance") or 90)
        if cl == "func_plat":
            r["height"] = float(e.get("height") or size[2] - 8)
        if cl == "func_rotating":
            sf = r["spawnflags"]
            r["axis"] = "x" if sf & 4 else "y" if sf & 8 else "z"
            r["touch_pain"] = bool(sf & 16)
            r["origin"] = vec(e.get("origin"))
        if cl == "func_train":
            pts, seen, t = [], set(), e.get("target", "")
            while t and t in by_name and t not in seen:
                seen.add(t)
                pc = ents[by_name[t][0]]
                pts.append(vec(pc.get("origin")))
                t = pc.get("target", "")
            r["path"] = [[round(v) for v in p] for p in pts]
            r["loop"] = bool(t and t in seen and t == e.get("target"))
            r["path_len"] = round(sum(math.dist(pts[k], pts[(k + 1) % len(pts)]) for k in range(len(pts)))) if len(pts) > 1 else 0
        near = sorted((math.dist(mid, o), c) for c, o in items if math.dist(mid, o) <= 384 and ip.MAJOR(c) if hasattr(ip, "MAJOR")) \
            if False else sorted((round(math.dist(mid, o)), c) for c, o in items if math.dist(mid, o) <= 384)
        r["near_items"] = [[c, d] for d, c in near[:4]]
        rec.append(r)
    # the chains: who fires whom
    fires = {r["i"]: [j for j in by_name.get(r["target"], []) if r["target"]] for r in rec}
    idx = {r["i"]: r for r in rec}
    for r in rec:
        r["fires"] = [ents[j].get("classname") for j in fires.get(r["i"], [])]
        r["fired_by"] = [idx[k]["cls"] for k, js in fires.items() if r["i"] in js]
    for i, e in enumerate(ents):
        if ip.kind_of(e.get("classname", "")) and e.get("target") and e["target"] in by_name:
            for j in by_name[e["target"]]:
                if j in idx:
                    idx[j]["fired_by"].append("item:" + e["classname"])
    return {"movers": rec, "pieces": pieces(rec, fires, idx)}


def pieces(rec, fires, idx) -> list:
    """The movers a chain of triggers joins, each piece with its kind."""
    out = []
    used = set()
    for r in rec:
        if r["cls"] in ("func_train", "func_plat", "func_rotating"):
            out.append({"kind": {"func_train": "train", "func_plat": "plat", "func_rotating": "rotating"}[r["cls"]],
                        "movers": [r["i"]]})
            used.add(r["i"])
    for r in rec:
        if r["cls"] not in ("func_button", "trigger_multiple", "trigger_once", "func_timer") or r["fired_by"]:
            continue
        chain, todo, delays = [], [r["i"]], []
        while todo:
            k = todo.pop()
            if k in chain:
                continue
            chain.append(k)
            if idx[k]["delay"]:
                delays.append(idx[k]["delay"])
            todo += [j for j in fires.get(k, []) if j in idx]
        movs = [k for k in chain if idx[k]["cls"] in MOVERS and idx[k]["cls"] != "func_button"]
        if not movs:
            continue
        cls = {idx[k]["cls"] for k in movs}
        trig = r["cls"]
        downs = all(idx[k].get("move", [0, 0, 0])[2] < 0 for k in movs if idx[k]["cls"] == "func_door")
        if "func_water" in cls:
            kind = "trap"
        elif trig == "func_timer":
            kind = "timed"
        elif trig in ("trigger_multiple", "trigger_once") and cls == {"func_door"} and downs and \
                any("lava" in idx[k].get("under", "") or "slime" in idx[k].get("under", "") for k in movs):
            kind = "sink"
        elif trig in ("trigger_multiple", "trigger_once") and any(d < 160 for _c, d in idx[r["i"]]["near_items"]):
            kind = "pickup"
        elif trig == "func_button":
            kind = "button"
        else:
            kind = "plate"
        out.append({"kind": kind, "trigger": trig, "movers": movs, "delays": delays,
                    "mover_classes": sorted(cls), "items": idx[r["i"]]["near_items"]})
        used.update(movs)
    for r in rec:
        if r["cls"] in ("func_door", "func_door_rotating") and r["i"] not in used and not r["targetname"]:
            out.append({"kind": "door", "movers": [r["i"]]})
    return out


def _work(p):
    name, path = p
    try:
        return name, study(str(path))
    except Exception as ex:  # noqa: BLE001 - a map the reader cannot take is said
        return name, {"error": repr(ex)}


def summary(db: dict) -> str:
    from collections import Counter
    kinds = Counter()
    lines = []
    for name, m in db.items():
        if "error" in m:
            lines.append(f"{name}: ERROR {m['error']}")
            continue
        ks = Counter(p["kind"] for p in m["pieces"] if p["kind"] != "door")
        kinds.update(ks)
        if ks:
            lines.append(f"{name:10s} " + ", ".join(f"{k} {n}" for k, n in sorted(ks.items())))
        for r in m["movers"]:
            if r["cls"] == "func_train":
                lines.append(f"     train size {r['size']} speed {r['speed']:.0f} wait {r['wait']:.0f} path {len(r['path'])} corners "
                             f"{r['path_len']} u {'loop' if r['loop'] else 'there-and-back'} under {r.get('under')} team {r['team'] or '-'}")
            if r["cls"] == "func_rotating":
                lines.append(f"     rotating size {r['size']} axis {r['axis']} speed {r['speed']:.0f} pain {r['touch_pain']} dmg {r['dmg']:.0f} "
                             f"under {r.get('under')} items {r['near_items'][:2]}")
        for p in m["pieces"]:
            if p["kind"] in ("trap", "timed", "sink", "pickup", "button", "plate"):
                ms = [next(r for r in m["movers"] if r["i"] == k) for k in p["movers"]]
                lines.append(f"     {p['kind']}: {p['trigger']} -> {', '.join(r['cls'] + ' ' + str(r.get('move', r.get('distance', ''))) + ' s' + str(int(r['speed'])) + ' w' + str(int(r['wait'])) for r in ms)}"
                             f" delays {p['delays']} items {p['items'][:2]}")
    lines.append("kinds over the maps: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common()))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("MAPGEN_PRESET_WORKERS", "4")))
    a = ap.parse_args()
    fam = ip.family_maps(ip.GAME)
    names = [m.lower() for m in a.maps] or list(fam)
    todo = [(n, fam[n]) for n in names if n in fam]
    with multiprocessing.Pool(max(1, min(a.workers, len(todo)))) as pool:
        db = dict(sorted(pool.map(_work, todo)))
    print(summary(db))
    if not a.maps:
        OUT.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
