"""People's item practice - the knowledge base the generator places its items by (the PO 12.11).

The PO 12.11 on his mg_new_84719 (a yellow and a green armour side by side, the railgun a step off, on the floor):
«нельзя класть рядом предметы одного класса»; «айтемы, оружие, броня, паверапы, они должны иметь ценность подбора»;
«рельса должна быть заслуженной … на q2dm1 - там плыть нужно. На ztn2dm3 нужно прыгать за ней. На q2duel5 чтобы её
забрать нужно пройти через обстрел аж с трех сторон»; «давно нужно было best practice по всем айтемам, оружию, арморам,
паверапам изучить»; «собрал такую базу знаний и на основе неё сформировал логику расположения и делал миксы пресетов» -
from q2dmX, q2duelX, q2rdmX, ztn2dmX, omf, koldduel1, ptrip, match1.

For every weapon, armour and powerup of each map, measured on the map itself (the walk graph of mapgen_map_survey, with
the swim up a water column the survey does not model):
  * the way from EVERY spawn point (not the nearest - a spawn on the item's own ledge says nothing of the rest):
    seconds; whether plain walking (walk, step, drop) gets there and how much longer; the special moves the shortest
    way takes (swim, jump up, gap jump, lift, ladder, jump pad, teleporter) - `effort`: the share of spawns that cannot
    reach it by plain walking within 0.5 s of the best way;
  * `sides`: of eight 45-degree sides around it, how many hold floor that sees it (eye to eye, 96..1200 u) - the
    exposure one crosses to take it; `seen`: those floor points;
  * `height`: over the lowest floor within 512 u; `water`: water within 192 u; `pocket`: the floor within 0.6 s of
    it by plain walking (a nook is small); `exits`: the ways out (groups of floor 1.4..1.6 s away, the survey's measure);
  * the nearest other major of each class: straight units and seconds on foot.

    python tools/mapgen_item_practice.py                  study the PO's families, write tools/mapgen_item_practice.json
    python tools/mapgen_item_practice.py --maps a.bsp ..  study these (the json's maps replaced by name)
    python tools/mapgen_item_practice.py --summary         the classes' practice from the json, in words and numbers
    python tools/mapgen_item_practice.py --rules           the rules the generator keeps, from the json: each pair of
                                                           classes no nearer than people's lower quartile (straight and
                                                           on foot), each prize's share earned - tools/mapgen_item_rules.json

Reads the maps where they are (the game's maps folder, its pak1 for q2dm1..8 - read into memory, nothing written
there); writes only the json beside this file.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import multiprocessing
import os
import re
import struct
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mapgen_map_survey as sv  # noqa: E402

OUT = HERE / "mapgen_item_practice.json"
RULES = HERE / "mapgen_item_rules.json"          # what the planner and the map's checks read (`--rules` makes it)
GAME = Path(os.environ.get("MAPGEN_GAME") or r"O:\Claude2\q2pro-release\baseq2")
# the PO's families (12.11): q2dmX, q2duelX, q2rdmX, ztn2dmX, omf, koldduel1, ptrip, match1
FAMILIES = re.compile(r"^(q2dm[1-8]|q2duel[1-8]|q2rdm[0-9]+|ztn2dm[1-5]|omf|koldduel1|ptrip|match1)$")

ARMOURS = ("item_armor_body", "item_armor_combat", "item_armor_jacket")
POWERS = ("item_quad", "item_invulnerability", "item_health_mega", "item_power_shield", "item_power_screen",
          "item_adrenaline")
WEAPONS = ("weapon_supershotgun", "weapon_chaingun", "weapon_grenadelauncher", "weapon_rocketlauncher",
           "weapon_hyperblaster", "weapon_railgun", "weapon_bfg", "weapon_shotgun", "weapon_machinegun")
PLAIN = {"walk", "drop"}
SPECIAL = ("swim", "jump", "gap", "plat", "ladder", "push", "teleport")


def kind_of(cls: str) -> str | None:
    if cls in ARMOURS:
        return "armour"
    if cls in POWERS:
        return "power"
    if cls in WEAPONS:
        return "weapon"
    return None


# ------------------------------------------------------------------------------------------------ the maps
def pak_maps(game: Path) -> dict:
    """The maps inside the game's pak files: name -> (pak, offset, length)."""
    out = {}
    for pk in sorted(game.glob("*.pak")) + sorted(game.glob("*.PAK")):
        try:
            with open(pk, "rb") as f:
                head = f.read(12)
                if head[:4] != b"PACK":
                    continue
                off, ln = struct.unpack_from("<ii", head, 4)
                f.seek(off)
                d = f.read(ln)
        except OSError:
            continue
        for i in range(ln // 64):
            name, o, l = struct.unpack_from("<56sii", d, 64 * i)
            n = name.split(b"\0")[0].decode("latin1").lower()
            if n.startswith("maps/") and n.endswith(".bsp"):
                out.setdefault(Path(n).stem, (pk, o, l))
    return out


def family_maps(game: Path) -> dict:
    """The PO's families: name -> a path to read (a loose map first, else extracted from its pak into the temp dir)."""
    maps = {}
    for p in sorted((game / "maps").glob("*.bsp")):
        if FAMILIES.match(p.stem.lower()):
            maps[p.stem.lower()] = p
    for name, (pk, o, l) in pak_maps(game).items():
        if FAMILIES.match(name) and name not in maps:
            tmp = Path(tempfile.gettempdir()) / "mapgen_item_practice"
            tmp.mkdir(exist_ok=True)
            p = tmp / f"{name}.bsp"
            if not p.is_file() or p.stat().st_size != l:
                with open(pk, "rb") as f:
                    f.seek(o)
                    p.write_bytes(f.read(l))
            maps[name] = p
    return dict(sorted(maps.items()))


# ------------------------------------------------------------------------------------------------ the walk
class Kinds:
    """Every link's kind (the survey keeps only the movers')."""
    def __init__(self):
        self.k = {}
        orig = sv.Graph.link

        def link(g, a, b, cost, kind, _o=orig, _k=self.k):
            _o(g, a, b, cost, kind)
            if (a, b) not in _k or kind in PLAIN:
                _k[(a, b)] = kind
        sv.Graph.link = link


def dij(g, src, kinds, plain_only=False, prev=False):
    dist = {src: 0.0}
    back = {src: -1} if prev else None
    pq = [(0.0, src)]
    while pq:
        d, i = heapq.heappop(pq)
        if d > dist.get(i, 1e18):
            continue
        for j, c in g.edges[i]:
            if plain_only and kinds.get((i, j), "walk") not in PLAIN:
                continue
            nd = d + c
            if nd < dist.get(j, 1e18):
                dist[j] = nd
                if back is not None:
                    back[j] = i
                heapq.heappush(pq, (nd, j))
    return (dist, back) if prev else dist


def study(path: str) -> dict:
    t0 = time.time()
    kinds = Kinds().k
    w = sv.World(Path(path))
    hurt = [mb for e in w.ents if e.get("classname") == "trigger_hurt" for mb in [sv.model_bounds(w, e)] if mb]
    g = sv.build_graph(w, hurt)
    sv.link_graph(g, w)
    swum = sv.movers(g, w).get("swims", 0)
    spawns = [s for s in (g.nearest(sv.fvec(e.get("origin", "")), below=96) for e in w.ents
                          if e.get("classname") == "info_player_deathmatch") if s is not None]
    spawns = list(dict.fromkeys(spawns))
    full = [dij(g, s, kinds, prev=True) for s in spawns]
    plain = [dij(g, s, kinds, plain_only=True) for s in spawns]
    # doors a button opens (q2dm3's mega, our «hard» nooks): the walk passes a func_door (not in the world's tree), so
    # an item behind one is marked - the way to it takes the button
    buttons = {e.get("target") for e in w.ents if e.get("classname") == "func_button" and e.get("target")}
    shut = []
    for e in w.ents:
        if e.get("classname") == "func_door" and e.get("targetname") in buttons:
            mb = sv.model_bounds(w, e)
            if mb:
                shut.append(mb)
    items = []
    for e in w.ents:
        cls = e.get("classname", "")
        if not kind_of(cls) or int(e.get("spawnflags", "0") or 0) & 0x700 == 0x700:
            continue
        o = sv.fvec(e.get("origin", ""))
        n = g.nearest(o, below=96)
        rec = {"cls": cls, "kind": kind_of(cls), "at": [round(v) for v in o], "team": e.get("team", ""),
               "button_door": any(math.dist(o, ((m[0][0] + m[1][0]) / 2, (m[0][1] + m[1][1]) / 2, (m[0][2] + m[1][2]) / 2)) <= 192
                                  for m in shut)}
        if n is None:
            rec["floor"] = False
            items.append(rec)
            continue
        z = g.nodes[n][2]
        ways = []
        moves = {}
        for (dist, back), pdist in zip(full, plain):
            t = dist.get(n, math.inf)
            tp = pdist.get(n, math.inf)
            if t < math.inf:
                way, j = [], n
                while back.get(j, -1) >= 0:
                    way.append((back[j], j))
                    j = back[j]
                used = {kinds.get(e_, "walk") for e_ in way} - PLAIN
                for k in used:
                    moves[k] = moves.get(k, 0) + 1
            ways.append((t, tp))
        reach = [(t, tp) for t, tp in ways if t < math.inf]
        rec["spawns"] = len(spawns)
        rec["reached"] = len(reach)
        rec["t_nearest"] = round(min((t for t, _ in reach), default=math.inf), 2) if reach else None
        rec["t_median"] = round(sorted(t for t, _ in reach)[len(reach) // 2], 2) if reach else None
        # effort: the share of spawns that cannot take it by plain walking within 0.5 s of the best way
        rec["effort"] = round(sum(1 for t, tp in ways if t == math.inf or tp > t + 0.5) / max(1, len(ways)), 2)
        rec["plain_never"] = round(sum(1 for t, tp in ways if tp == math.inf) / max(1, len(ways)), 2)
        rec["moves"] = {k: round(v / max(1, len(reach)), 2) for k, v in sorted(moves.items())}
        # exposure: the sides that see it
        eye = (o[0], o[1], z + 46)
        sectors = [0] * 8
        cand = [i for i, (x, y, zz) in enumerate(g.nodes) if 96 <= math.dist((x, y), (o[0], o[1])) <= 1200]
        step = max(1, len(cand) // 1500)
        for i in cand[::step]:
            x, y, zz = g.nodes[i]
            if not w.blocked(eye, (x, y, zz + 46)):
                sectors[int(((math.degrees(math.atan2(y - o[1], x - o[0])) + 360) % 360) // 45)] += step
        seen = sum(sectors)
        rec["seen"] = seen
        rec["sides"] = sum(1 for s_ in sectors if s_ >= max(8, seen * 0.06))
        near = [g.nodes[i][2] for i in cand if math.dist(g.nodes[i][:2], o[:2]) <= 512] + [z]
        rec["height"] = round(z - min(near))
        rec["water"] = any(g.water[i] for i in cand if math.dist(g.nodes[i], (o[0], o[1], z)) <= 192) or g.water[n]
        # lying in water: one falls in, and swims to come out (q2dm5's mega at a pool's bottom)
        rec["submerged"] = bool(g.water[n])
        mine = dij(g, n, kinds, plain_only=True)
        rec["pocket"] = sum(1 for t in mine.values() if t <= 0.6)
        ring = [i for i, t in mine.items() if 1.4 <= t <= 1.6]
        groups, left = 0, set(ring)
        while left:
            groups += 1
            todo = [left.pop()]
            while todo:
                a = todo.pop()
                for b, _c in g.edges[a]:
                    if b in left:
                        left.discard(b)
                        todo.append(b)
        rec["exits"] = groups
        rec["_node"] = n
        items.append(rec)
    # the nearest other major of each class
    on = [r for r in items if "_node" in r]
    times = {id(r): dij(g, r["_node"], kinds) for r in on}
    for r in on:
        for k in ("armour", "weapon", "power"):
            best = None
            for r2 in on:
                if r2 is r or r2["kind"] != k:
                    continue
                d = math.dist(r["at"], r2["at"])
                t = min(times[id(r)].get(r2["_node"], math.inf), times[id(r2)].get(r["_node"], math.inf))
                if best is None or d < best[0]:
                    best = (d, t, r2["cls"])
            if best:
                r[f"near_{k}"] = {"units": round(best[0]), "s": round(best[1], 2) if best[1] < math.inf else None,
                                  "cls": best[2]}
    # every pair of majors on a floor: straight units and seconds on foot (the quicker way)
    pairs = []
    for i, r in enumerate(on):
        for r2 in on[i + 1:]:
            t = min(times[id(r)].get(r2["_node"], math.inf), times[id(r2)].get(r["_node"], math.inf))
            pairs.append([r["cls"], r2["cls"], round(math.dist(r["at"], r2["at"])), round(t, 2) if t < math.inf else None])
    for r in on:
        r.pop("_node", None)
    return {"map": Path(path).stem.lower(), "spawns": len(spawns), "points": len(g.nodes), "swim_columns": swum,
            "items": items, "pairs": pairs, "seconds": round(time.time() - t0, 1)}


def _work(p):
    try:
        return study(p)
    except Exception as e:  # noqa: BLE001 - one map's fault is said, the others go on
        return {"map": Path(p).stem.lower(), "error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------------------------------------ the practice
def q(vals, f):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return vals[min(len(vals) - 1, int(f * len(vals)))]


def summary(db: dict) -> str:
    rows = [r | {"map": m["map"]} for m in db["maps"].values() if "items" in m for r in m["items"] if "effort" in r]
    out = [f"{len(db['maps'])} maps, {len(rows)} weapons, armours and powerups on a floor"]
    for cls in WEAPONS + ARMOURS + POWERS:
        rs = [r for r in rows if r["cls"] == cls]
        if not rs:
            continue
        earned = [r for r in rs if r["effort"] >= 0.5 or r["sides"] >= 4 or r["water"] or r["height"] >= 128]
        mv = {}
        for r in rs:
            for k, v in r["moves"].items():
                if v >= 0.5:
                    mv[k] = mv.get(k, 0) + 1
        out.append(f"{cls:22} n={len(rs):3}  effort>=.5 {sum(1 for r in rs if r['effort'] >= 0.5):3}  sides>=3 "
                   f"{sum(1 for r in rs if r['sides'] >= 3):3}  height>=64 {sum(1 for r in rs if r['height'] >= 64):3}  "
                   f"water {sum(1 for r in rs if r['water']):3}  pocket<=20 {sum(1 for r in rs if r['pocket'] <= 20):3}  "
                   f"dead-end {sum(1 for r in rs if r['exits'] <= 1):3}  moves {mv}  any of these {len(earned)}")
    for a, b in (("armour", "armour"), ("weapon", "weapon"), ("weapon", "armour"), ("power", "power"),
                 ("power", "armour"), ("power", "weapon")):
        us = [r[f"near_{b}"]["units"] for r in rows if r["kind"] == a and f"near_{b}" in r]
        ss = [r[f"near_{b}"]["s"] for r in rows if r["kind"] == a and f"near_{b}" in r]
        out.append(f"nearest {b:6} to a {a:6}: units p5 {q(us, .05)} p10 {q(us, .1)} p25 {q(us, .25)} p50 {q(us, .5)};"
                   f"  seconds p5 {q(ss, .05)} p10 {q(ss, .1)} p25 {q(ss, .25)} p50 {q(ss, .5)}  (n={len(us)})")
    return "\n".join(out)


PAIRS = (("armour", "armour"), ("weapon", "weapon"), ("weapon", "armour"), ("power", "power"), ("power", "armour"),
         ("power", "weapon"))
PRIZES = ("weapon_railgun", "item_health_mega", "item_quad", "item_invulnerability", "item_armor_body",
          "item_power_shield")


def rules(db: dict) -> dict:
    """The rules from the knowledge base: for each pair of classes the lower quartile of people's nearest distances (an
    item with nothing of the other class nearer than three in four of people's items have it); for each prize the share
    of people's taken with effort (most spawns cannot walk to it) - and the moves those took."""
    rows = [r for m in db["maps"].values() if "items" in m for r in m["items"] if "effort" in r]
    out = {"_about": "from tools/mapgen_item_practice.json (--rules); the PO 12.11: pick-up worth - nothing near, prizes earned",
           "maps": len(db["maps"]), "apart": {}, "prizes": {}}
    for a, b in PAIRS:
        near = [r[f"near_{b}"] for r in rows if r["kind"] == a and f"near_{b}" in r]
        # an item team (q2dm8's mega, armour and shield taking turns on one spot) is one place, not two near
        near = [x for x in near if x["units"] > 32]
        us = [x["units"] for x in near]
        ss = [x["s"] for x in near if x["s"] is not None]
        out["apart"][f"{a}-{b}"] = {"units": q(us, 0.25), "s": q(ss, 0.25), "p10_units": q(us, 0.1), "p10_s": q(ss, 0.1),
                                    "median_units": q(us, 0.5), "median_s": q(ss, 0.5), "n": len(near)}
    for cls in PRIZES:
        rs = [r for r in rows if r["cls"] == cls]
        if not rs:
            continue
        out["prizes"][cls] = prize_rule(rs)
    # per family (the presets' «item_practice»): the same, from its maps only
    fams = {}
    for name in db["maps"]:
        m = re.match(r"^(q2dm|q2duel|q2rdm|ztn2dm)\d+$", name)
        fams.setdefault(m.group(1) if m else name, []).append(name)
    out["families"] = {}
    for fam, names in sorted(fams.items()):
        sub = {"maps": {n: db["maps"][n] for n in names}}
        r = rules_of(sub)
        out["families"][fam] = {"maps": sorted(names), "apart": r["apart"], "prizes": r["prizes"]}
    return out


def prize_rule(rs: list) -> dict:
    mv = {}
    for r in rs:
        for k, v in r["moves"].items():
            if v >= 0.3:
                mv[k] = mv.get(k, 0) + 1
    return {"n": len(rs), "earned": round(sum(1 for r in rs if r["effort"] >= 0.5) / len(rs), 2),
            "exposed": round(sum(1 for r in rs if r["effort"] < 0.5 and r["sides"] >= 5) / len(rs), 2),
            "height_median": q([r["height"] for r in rs], 0.5),
            "pocket_median": q([r["pocket"] for r in rs], 0.5),
            "dead_end": round(sum(1 for r in rs if r["exits"] <= 1) / len(rs), 2),
            "moves": dict(sorted(mv.items(), key=lambda t: -t[1]))}


def rules_of(db: dict) -> dict:
    """The apart and prizes of a set of maps (one family)."""
    rows = [r for m in db["maps"].values() if "items" in m for r in m["items"] if "effort" in r]
    out = {"apart": {}, "prizes": {}}
    for a, b in PAIRS:
        near = [r[f"near_{b}"] for r in rows if r["kind"] == a and f"near_{b}" in r and r[f"near_{b}"]["units"] > 32]
        us = [x["units"] for x in near]
        ss = [x["s"] for x in near if x["s"] is not None]
        out["apart"][f"{a}-{b}"] = {"units": q(us, 0.25), "s": q(ss, 0.25), "p10_units": q(us, 0.1), "p10_s": q(ss, 0.1),
                                    "median_units": q(us, 0.5), "median_s": q(ss, 0.5), "n": len(near)}
    for cls in PRIZES:
        rs = [r for r in rows if r["cls"] == cls]
        if rs:
            out["prizes"][cls] = prize_rule(rs)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=max(1, min(6, (os.cpu_count() or 4) // 4)))
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--rules", action="store_true")
    a = ap.parse_args()
    if a.summary:
        print(summary(json.loads(OUT.read_text(encoding="utf-8"))))
        return 0
    if a.rules:
        r = rules(json.loads(OUT.read_text(encoding="utf-8")))
        RULES.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    todo = {Path(p).stem.lower(): Path(p) for p in a.maps} if a.maps else family_maps(GAME)
    db = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() and a.maps else {"maps": {}}
    print(f"{len(todo)} maps: {', '.join(todo)}", flush=True)
    with multiprocessing.Pool(a.workers) as pool:
        for r in pool.imap_unordered(_work, [str(p) for p in todo.values()]):
            db["maps"][r["map"]] = r
            print(f"  {r['map']}: " + (r.get("error") or f"{len(r['items'])} items, {r['spawns']} spawns, "
                                                         f"{r['swim_columns']} swims, {r['seconds']} s"), flush=True)
    db["maps"] = dict(sorted(db["maps"].items()))
    db["_about"] = "people's item practice (tools/mapgen_item_practice.py); the PO 12.11"
    OUT.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    print(summary(db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
