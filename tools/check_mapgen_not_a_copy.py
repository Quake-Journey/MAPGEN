r"""Brief 19 D6: a map made from scratch is not a copy - by proof, against every map the generator knows.

    python tools/check_mapgen_not_a_copy.py MAP.bsp [--style A.bsp B.bsp ...]
    python tools/check_mapgen_not_a_copy.py --calibrate     people's maps against each other: the bars
    python tools/check_mapgen_not_a_copy.py --red           the composer's seed 3 (q2dm1 in a shell) must FAIL
                                                            (built from this tree on first use: needs gcc)

The corpus is every base map of the Studio (engine\donors) and the people's maps of the D7 bands, plus the maps a
style names. Three measures, each against each corpus map:

1. **A room carried whole.** Every solid brush is an axial box (its axial sides; other brushes skipped); a PAIR of
   brushes within 192 u of each other has a signature that turning, mirroring and moving cannot change: both boxes'
   sizes (sorted, to 8 u) and the pair's horizontal and vertical distance (to 8 u). A brush whose two or more pairs
   are found in the corpus map is CARRIED; carried brushes joined by matched pairs make a cluster. The measure is the
   largest cluster - a room brought across whole (the composer's q2dm1: hundreds) against what people's maps share
   with each other by chance (steps and frames of one size).
2. **A route copied.** Between every two major items the walk's route is cut into straight runs (the 32-u grid's
   eight directions, runs under 96 u merged into their neighbours); three runs in a row with their two turns (lengths
   to 16 u, turns to 45 degrees) are a piece of route. The measure is the share of the map's pieces found among the
   corpus map's.
3. **The item graph.** The times between every two majors, sorted and read at twenty quantiles: the distance between
   two maps is the mean difference. The new map must be farther from every corpus map than the two NEAREST people's
   maps are from each other.

Bars (--calibrate writes check_mapgen_not_a_copy.json), each people's own extreme over every pair of their maps: the
carried room no more distinct pieces than two people's maps share at most (04.11: q2duel5/ztn2dm3 17, koldduel1/q2dm6
12, every other pair 8 or fewer - the composer's map: 289 of q2dm1), routes no more shared than people's maps share by
chance at most, and the item graph farther than the two nearest people's maps.
The REDs: the composer of 08.09, seed 3 - «it is its donor», q2dm1 turned and mirrored inside a shell - must fail
the carried room; a plain copy of q2dm1 under another name must fail all three.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_map_survey as survey  # noqa: E402
from check_mapgen_new_map import HUMANS, MAPS, DONORS  # noqa: E402

RED = Path(r"O:\Claude2\_agent_temp\claude\b19\compose\compose3.bsp")
CALIBRATION = TOOLS / "check_mapgen_not_a_copy.json"
PAIR_R = 192.0


# ------------------------------------------------------------------------------------------------ 1. carried rooms
def boxes(path: Path) -> list:
    b = oracle.load(path)
    out = []
    for br in b.brushes:
        if not (br.contents & 1):
            continue
        mins, maxs = [-1e9] * 3, [1e9] * 3
        axial = 0
        for s in range(br.firstside, br.firstside + br.numsides):
            pl = b.planes[b.brushsides[s].planenum]
            for a in range(3):
                if abs(pl.normal[a]) > 0.999:
                    axial += 1
                    if pl.normal[a] > 0:
                        maxs[a] = min(maxs[a], pl.dist)
                    else:
                        mins[a] = max(mins[a], -pl.dist)
        if br.numsides != 6 or axial != 6 or any(abs(v) > 1e8 for v in mins + maxs):
            continue
        out.append((mins, maxs))
    return out


def pair_sigs(bx: list) -> tuple[dict, list, list]:
    """(signature -> count, per brush the list of (signature, other brush), per brush its sorted size)."""
    cells: dict = {}
    cen = []
    dims = []
    for i, (lo, hi) in enumerate(bx):
        c = [(lo[a] + hi[a]) / 2 for a in range(3)]
        cen.append(c)
        dims.append(tuple(sorted(int(round((hi[a] - lo[a]) / 8.0)) for a in range(3))))
        cells.setdefault((int(c[0] // PAIR_R), int(c[1] // PAIR_R)), []).append(i)
    sigs: dict = {}
    per = [[] for _ in bx]
    for i, c in enumerate(cen):
        cx, cy = int(c[0] // PAIR_R), int(c[1] // PAIR_R)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cells.get((cx + dx, cy + dy), ()):
                    if j <= i:
                        continue
                    h = math.hypot(cen[j][0] - c[0], cen[j][1] - c[1])
                    v = abs(cen[j][2] - c[2])
                    if h > PAIR_R or v > PAIR_R:
                        continue
                    a_, b_ = sorted((dims[i], dims[j]))
                    s = (a_, b_, int(round(h / 8.0)), int(round(v / 8.0)))
                    sigs[s] = sigs.get(s, 0) + 1
                    per[i].append((s, j))
                    per[j].append((s, i))
    return sigs, per, dims


def carried(new: tuple, old_sigs: dict) -> int:
    """The largest cluster of the new map's brushes carried from the old one, counted in DISTINCT brush shapes: a room
    carried whole brings many different pieces (the composer's q2dm1: hundreds); a flight of identical steps or a row
    of identical frames matches any map with steps of that size and brings one or two (04.11: a scratch map's stairs
    made a «62-brush room of omf» counted in brushes)."""
    per = new[1]
    dims = new[2]
    is_c = [sum(1 for s, _ in p if s in old_sigs) >= 2 for p in per]
    seen = [False] * len(per)
    best = 0
    for i in range(len(per)):
        if not is_c[i] or seen[i]:
            continue
        stack, shapes = [i], set()
        seen[i] = True
        while stack:
            k = stack.pop()
            shapes.add(dims[k])
            for s, j in per[k]:
                if is_c[j] and not seen[j] and s in old_sigs:
                    seen[j] = True
                    stack.append(j)
        best = max(best, len(shapes))
    return best


# ------------------------------------------------------------------------------------------------ 2. and 3. the walk
def walk(path: Path):
    w = survey.World(path)
    hurt = [mb for e in w.ents if e.get("classname") == "trigger_hurt" for mb in [survey.model_bounds(w, e)] if mb]
    g = survey.build_graph(w, hurt)
    survey.link_graph(g, w)
    survey.movers(g, w)
    majors = []
    for e in w.ents:
        if e.get("classname") in survey.MAJORS:
            nd = g.nearest(survey.fvec(e.get("origin", "")), below=120)
            if nd is not None and nd not in majors:
                majors.append(nd)
    return g, majors


def route_pieces(g, majors) -> tuple[set, list]:
    """(the set of three-run route pieces, the sorted times between every two majors)."""
    pieces, times = set(), []
    for ia, a in enumerate(majors):
        prev = [-1] * len(g.nodes)
        d = survey.dijkstra(g, [a], prev=prev)
        for b in majors[ia + 1:]:
            if d[b] == math.inf:
                continue
            times.append(d[b])
            path = []
            k = b
            while k != -1 and len(path) < 4000:
                path.append(g.nodes[k])
                k = prev[k] if k != a else -1
            runs = []
            for p0, p1 in zip(path, path[1:]):
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                L = math.hypot(dx, dy)
                if L < 1:
                    continue
                ang = int(round(math.degrees(math.atan2(dy, dx)) / 45.0)) % 8
                if runs and runs[-1][0] == ang:
                    runs[-1][1] += L
                else:
                    runs.append([ang, L])
            # short runs fold into the run before them (a step round a pillar is no turn of the route)
            merged = []
            for ang, L in runs:
                if merged and L < 96:
                    merged[-1][1] += L
                else:
                    merged.append([ang, L])
            for k3 in range(len(merged) - 2):
                (a0, l0), (a1, l1), (a2, l2) = merged[k3:k3 + 3]
                t1, t2 = (a1 - a0) % 8, (a2 - a1) % 8
                q = lambda L: int(round(L / 16.0))  # noqa: E731
                pieces.add((q(l0), t1, q(l1), t2, q(l2)))
                pieces.add((q(l2), (-t2) % 8, q(l1), (-t1) % 8, q(l0)))     # the same piece walked back
                # mirrored: the turns the other way
                pieces.add((q(l0), (-t1) % 8, q(l1), (-t2) % 8, q(l2)))
    return pieces, sorted(times)


def quantiles(ts: list, n: int = 20) -> list:
    if not ts:
        return [0.0] * n
    return [ts[min(len(ts) - 1, int(i * (len(ts) - 1) / (n - 1)))] for i in range(n)]


def graph_dist(a: list, b: list) -> float:
    qa, qb = quantiles(a), quantiles(b)
    return sum(abs(x - y) for x, y in zip(qa, qb)) / len(qa)


# ------------------------------------------------------------------------------------------------ the corpus
def corpus(style: list | None = None) -> list[Path]:
    out, seen = [], set()
    for p in sorted(DONORS.glob("*.bsp")) + [MAPS / f"{n}.bsp" for names in HUMANS.values() for n in names] + \
            [Path(s) for s in (style or [])]:
        if p.is_file() and p.stem not in seen:
            seen.add(p.stem)
            out.append(p)
    return out


_CACHE: dict = {}


def facts(path: Path) -> dict:
    key = str(path)
    if key not in _CACHE:
        bx = boxes(path)
        sigs, per, dims = pair_sigs(bx)
        g, majors = walk(path)
        pieces, times = route_pieces(g, majors)
        _CACHE[key] = {"sigs": sigs, "per": per, "dims": dims, "pieces": pieces, "times": times, "brushes": len(bx)}
    return _CACHE[key]


def compare(new: dict, old: dict) -> dict:
    share = len(new["pieces"] & old["pieces"]) / max(1, len(new["pieces"]))
    return {"carried": carried((new["sigs"], new["per"], new["dims"]), old["sigs"]), "route_share": round(share, 3),
            "graph_dist": round(graph_dist(new["times"], old["times"]), 3)}


def bars() -> dict:
    return json.loads(CALIBRATION.read_text(encoding="utf-8")) if CALIBRATION.is_file() else {}


def judge(path: Path, style: list | None = None, log=print) -> list[tuple[str, bool, str]]:
    b = bars()
    if not b:
        raise SystemExit(f"no calibration: python tools/check_mapgen_not_a_copy.py --calibrate (writes {CALIBRATION.name})")
    new = facts(path)
    rows = []
    worst = {"carried": (0, ""), "route_share": (0.0, ""), "graph_dist": (math.inf, "")}
    for p in corpus(style):
        if p.resolve() == path.resolve():
            continue
        c = compare(new, facts(p))
        log(f"    vs {p.stem:12s} carried {c['carried']:4d}  route pieces {c['route_share']:.3f}  item graph {c['graph_dist']:.2f}")
        if c["carried"] > worst["carried"][0]:
            worst["carried"] = (c["carried"], p.stem)
        if c["route_share"] > worst["route_share"][0]:
            worst["route_share"] = (c["route_share"], p.stem)
        if c["graph_dist"] < worst["graph_dist"][0]:
            worst["graph_dist"] = (c["graph_dist"], p.stem)
    v, n = worst["carried"]
    rows.append((f"not a copy, rooms: no room carried whole (largest carried cluster <= {b['carried']} distinct pieces, people's maps' own)",
                 v <= b["carried"], f"{v} distinct pieces from {n or '-'}"))
    v, n = worst["route_share"]
    rows.append((f"not a copy, routes: no route copied (pieces shared <= {b['route_share']:.3f}, people's maps' own)",
                 v <= b["route_share"], f"{v:.3f} with {n or '-'}"))
    v, n = worst["graph_dist"]
    rows.append((f"not a copy, item graph: its own (distance > {b['graph_dist']:.2f} s, the two nearest people's maps')",
                 v > b["graph_dist"], f"{v:.2f} s from {n or '-'}"))
    return rows


def calibrate() -> int:
    maps = [p for p in corpus() if p.stem in {n for names in HUMANS.values() for n in names} or p.parent == DONORS]
    got = {"carried": [], "route_share": [], "graph_dist": []}
    for i, a in enumerate(maps):
        for b_ in maps:
            if a == b_ or a.stem == b_.stem:
                continue
            c = compare(facts(a), facts(b_))
            print(f"{a.stem:12s} vs {b_.stem:12s} carried {c['carried']:4d}  route {c['route_share']:.3f}  "
                  f"graph {c['graph_dist']:.2f}", flush=True)
            for k in got:
                got[k].append((c[k], f"{a.stem}/{b_.stem}"))
    best = {}
    for k, vals in got.items():
        vals.sort(key=lambda t: t[0], reverse=(k != "graph_dist"))
        # each bar is people's own extreme: the most two of their maps share (04.11, in distinct pieces: q2duel5 and
        # ztn2dm3 17, koldduel1 and q2dm6 12, every other pair 8 or fewer; the composer's map carries 289 of q2dm1)
        at = 0
        best[k] = vals[at][0]
        best[f"{k}_beyond"] = [f"{v} {n}" for v, n in vals[:max(at, 3)]]
    best["pairs"] = len(got["carried"])
    best["maps"] = [p.stem for p in maps]
    CALIBRATION.write_text(json.dumps(best, indent=1), encoding="utf-8")
    print(json.dumps(best, indent=1))
    return 0


def build_red() -> None:
    """The composer of 08.09 built from this tree (gcc), run at seed 3 on q2dm1, q2dm3, q2dm8 and compiled (bsp
    only) - q2dm1's outdoors turned and mirrored inside a shell: «it is its donor»."""
    import subprocess
    import mapgen_scratch_build as build_mod
    repo = TOOLS.parent
    RED.parent.mkdir(parents=True, exist_ok=True)
    exe = RED.parent / "compose.exe"
    src = ["tools/mapgen_compose_driver.c", "src/mapgen/mapgen_compose.c", "src/mapgen/mapgen_bsp.c",
           "src/mapgen/mapgen_bundle.c", "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_graft.c",
           "src/mapgen/mapgen_rooms.c", "src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_digest.c",
           "src/shared/shared.c", "tools/mapgen_host_stubs.c"]
    r = subprocess.run(["gcc", "-std=c17", "-O2", "-I" + str(repo / "inc"), "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
                        "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"] + [str(repo / s) for s in src] + ["-o", str(exe), "-lm"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("the composer did not build:\n" + r.stderr[-1500:])
    mp = RED.with_suffix(".map")
    r = subprocess.run([str(exe), "--seed", "3", "--out", str(mp)] + [str(DONORS / f"{n}.bsp") for n in ("q2dm1", "q2dm3", "q2dm8")],
                       capture_output=True, text=True, cwd=str(RED.parent))
    if r.returncode != 0 or not mp.is_file():
        raise SystemExit("the composer did not run:\n" + r.stdout[-800:] + r.stderr[-800:])
    ok, tail = build_mod.compile_map(mp, MAPS.parent, 1, stages=("bsp",), log=RED.parent / "compile.log")
    if not ok:
        raise SystemExit("the composer's map did not compile:\n" + tail[-800:])


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?", type=Path)
    ap.add_argument("--style", nargs="*", default=[])
    ap.add_argument("--asked", type=Path, help="the run's request (JSON): its style's maps join the corpus")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--red", action="store_true")
    a = ap.parse_args()
    if a.calibrate:
        return calibrate()
    if a.red:
        if not RED.is_file():
            build_red()
        print(f"RED 1: {RED.name} (the composer's seed 3, q2dm1 in a shell) must fail the carried room")
        rows = judge(RED, log=lambda *_: None)
        for name, ok, said in rows:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}  -- {said}")
        ok1 = not rows[0][1]
        copy = RED.parent / "q2dm1_renamed.bsp"
        copy.write_bytes((DONORS / "q2dm1.bsp").read_bytes())
        print(f"RED 2: {copy.name} (q2dm1 under another name) must fail all three")
        rows = judge(copy, log=lambda *_: None)
        for name, ok, said in rows:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}  -- {said}")
        ok2 = all(not ok for _, ok, _ in rows)
        print(f"{'PASS' if ok1 and ok2 else 'FAIL'}: the REDs fail as they must")
        return 0 if ok1 and ok2 else 1
    if not a.map:
        ap.print_help()
        return 2
    style = list(a.style)
    if a.asked and a.asked.is_file():
        style += list(((json.loads(a.asked.read_text(encoding="utf-8")).get("style") or {}).get("maps")) or [])
    print(f"not a copy (brief 19 D6): {a.map.name} against {len(corpus(style))} maps")
    rows = judge(a.map, style)
    fails = 0
    for name, ok, said in rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  -- {said}")
        fails += 0 if ok else 1
    print(f"SUMMARY not a copy: {fails} failed")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
