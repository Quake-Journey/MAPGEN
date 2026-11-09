r"""Brief 26 D6: the jump pads' and teleporters' look (mapgen_scratch_fixtures) on three maps from scratch built the
Studio's way (mapgen_scratch.build_candidate: plan, style, build, compile, survey, judge) - an open space with two
teleporter pairs, a tower, a rooms map for 4 with a pad and two teleporter pairs. On each:
* the .map's brushes by their notes = the plan's pads (a disc or a wedge each) and teleporters (posts, a frame);
* the judge's rows «fixtures», «nothing hanging», «traps» (the engine's walk) PASS;
* the people's survey: every pad flown lands, every teleporter crossed (as many as the plan's discs);
* every teleporter's disc stands free - in the BSP a body's room over it (feet, waist, eye at its four corners) and
  its floor under it (the survey's crossing cannot see that: its search for the disc's floor reaches 3 grid cells,
  96..128 u, round the origin - a slab over the disc left floor in reach, 06.11);
* every slanted pad's wedge rises along its flight and its arrows point that way (the .map: the wedge's top plane
  and its texture's turn against the trigger's yaw);
* the five textures in the game; the cover views of a pad and a teleporter found (the Studio's `--fixture-views`);
* with --engine: the engine takes the map as a base (engine_accepts, plan-only, in memory).
Brief 32 (the PO 08.11: sizes of the round and slanted pads, the teleporters' frames and a plate under the spawns, 50 to
200 %): with --size PCT every case asks that size of all four (`pad_disc_size`, `pad_wedge_size`, `tele_frame_size`,
`spawn_plate_size`) and these rows join:
* the .map's plinths, frames' posts and plates measure the sizes the plan built them at (P.fx_size), each at most the
  size asked, and every pad, frame and plate counted;
* no plinth or plate stands over air: the share of its underside with no solid 4 under it at most 10 % (a 100 % plinth
  at an island's edge lips over by 12 - 5 % of it - as 3.53..3.58 built it);
* every spawn on a plate stands on it (its origin 24 over the plate's top).
RED (with --size over 100): the plan's footprint test switched off in this process (a plinth's or a plate's cells
never looked at) - they then grow to the size asked wherever they stand, over the tower's atrium too, and the «over air»
row must go red.
REDs (the same plan built again with a constant changed in the sandbox of this process - each must go red):
* D2: the arrows turned against the flight - the direction row fails. (The brief's own D2 RED, a wedge 64 tall at its
  far end, stays green: the people's survey launches a pad from the floor node under its trigger's base - mins + 24 -
  not from the wedge's top, so the wedge's height moves no take-off; measured 06.11 on the tower, 6 of 6 landing);
* D3: the back slab across the disc's own cell (80 across) - the disc no longer stands free.

    python tools/check_mapgen_fixtures.py [--engine] [--only space|tower|rooms] [--size 50..200]
Writes into O:\Claude2\_agent_temp\claude\fixtures_check\. Pinned by the load guard.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard  # noqa: E402
import mapgen_scratch as sc  # noqa: E402
import mapgen_scratch_fixtures as fix_mod  # noqa: E402
import mapgen_scratch_plan as pm  # noqa: E402
import mapgen_space_survey as ss  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
STUDIO = Path(r"O:\Claude2\MapgenStudio")
WORK = Path(r"O:\Claude2\_agent_temp\claude\fixtures_check")
STUDIO_BUILD = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\build\bin\MapgenStudio\Release\net10.0\win-x64\MapgenStudio.exe")
CASES = {"space": ({"players": 4, "shape": "space", "teleporters": 2}, 26101),
         "tower": ({"players": 4, "shape": "tower"}, 26102),
         # a rooms map whose best plan holds a pad (rooms pads come only where a terrace needs one: 1 of 4 seeds tried;
         # brief 34: and only where no stair is near - 26105's 64-high terrace with its stair 1.65 s away lost its pad,
         # 26107's keeps one)
         "rooms": ({"players": 4, "pads": 3, "teleporters": 2, "levels": 4}, 26107)}
FAILED = 0


def row(ok: bool, what: str, said: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {what}" + (f" -- {said}" if said else ""))
    return ok


def build(P, q, name, out):
    """One candidate the Studio's way; (bands {name: (ok, said)}, survey, the .map's text, pads landed, flown)."""
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    _k, said, entry = sc.build_candidate((0, P, q, name, out, GAME, 4))
    if entry is None:
        return None
    cdir = out / "cand0"
    bands = {}
    for line in (cdir / "bands.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"(PASS|FAIL)  (.*?)  -- (.*)", line)
        if m:
            bands[m.group(2)] = (m.group(1) == "PASS", m.group(3))
    r = entry[4]
    sp = ss.space_part(cdir / f"{name}.bsp")
    flown = sum(1 for p_ in sp.get("pads") or [] if p_.get("points", 0) > 3)
    return bands, r, (cdir / f"{name}.map").read_text(encoding="latin-1"), sp["movers"]["pads"], flown, cdir / f"{name}.bsp"


def notes(text: str) -> dict:
    out = {}
    for m in re.finditer(r"^// brush \d+ (pad \w+|portal \w+)$", text, re.M):
        out[m.group(1)] = out.get(m.group(1), 0) + 1
    return out


def wedge_dirs(text: str) -> tuple[int, list]:
    """Each slanted pad's wedge against its trigger: (wedges, [what is wrong]). The wedge's top face (the arrow
    texture) - its plane must rise along the trigger's yaw and its texture's turn equal that yaw."""
    import math
    face_re = re.compile(r"\( (\S+) (\S+) (\S+) \) \( (\S+) (\S+) (\S+) \) \( (\S+) (\S+) (\S+) \) (\S+) (\S+) (\S+) (\S+)")
    pushes = []
    for m in re.finditer(r'"classname" "trigger_push"\n"speed" "[^"]*"\n"angles" "(\S+) (\S+) \S+"\n// brush 0\n\{\n((?:\(.*\n)+)\}', text):
        pts = [tuple(map(float, p)) for p in re.findall(r"\( (\S+) (\S+) (\S+) \)", m.group(3))]
        pushes.append(((min(p[0] for p in pts) + max(p[0] for p in pts)) / 2, (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2,
                       float(m.group(2))))
    wedges, bad = 0, []
    for m in re.finditer(r"^// brush \d+ pad wedge\n\{\n((?:\(.*\n)+)\}", text, re.M):
        top = [f for f in (face_re.match(x) for x in m.group(1).splitlines()) if f and f.group(10).endswith("/padarrow")]
        allp = [tuple(map(float, p)) for p in re.findall(r"\( (\S+) (\S+) (\S+) \)", m.group(1))]
        if not top:
            bad.append("a wedge without its arrows")
            continue
        wedges += 1
        f = top[0]
        a, b, c = [tuple(float(f.group(i + k)) for k in range(3)) for i in (1, 4, 7)]
        u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        if n[2] < 0:
            n = tuple(-x for x in n)
        up = math.degrees(math.atan2(-n[1], -n[0]))         # the way the top rises
        rot = float(f.group(13))
        cx = sum(p[0] for p in allp) / len(allp)
        cy = sum(p[1] for p in allp) / len(allp)
        tr = min(pushes, key=lambda t: math.hypot(t[0] - cx, t[1] - cy), default=None)
        if tr is None or math.hypot(tr[0] - cx, tr[1] - cy) > 48:
            bad.append(f"a wedge at {cx:.0f} {cy:.0f} with no trigger over it")
            continue
        off = lambda x, y: abs((x - y + 180) % 360 - 180)  # noqa: E731
        if off(up, tr[2]) > 5 or off(rot, tr[2]) > 1:
            bad.append(f"at {cx:.0f} {cy:.0f}: flight {tr[2]:.0f}, rises to {up:.0f}, arrows {rot:.0f}")
    return wedges, bad


def discs_free(bsp: Path, text: str) -> tuple[int, list]:
    """Each misc_teleporter of the .map: a body's room over its disc and a floor under it, read from the BSP."""
    import mapgen_map_survey as sv
    w = sv.World(str(bsp))
    bad, n = [], 0
    for m in re.finditer(r'"classname" "misc_teleporter"\n(?:"[^"]*" "[^"]*"\n)*?"origin" "(\S+) (\S+) (\S+)"', text):
        x, y, z = (float(m.group(i)) for i in (1, 2, 3))
        n += 1
        room = all(not (w.contents(x + dx, y + dy, z + h) & 1) for dx in (-16, 16) for dy in (-16, 16) for h in (-16, 8, 30))
        floor = bool(w.contents(x, y, z - 32) & 1)
        if not (room and floor):
            bad.append(f"{x:.0f} {y:.0f} {z:.0f}: {'room' if room else 'no room'}, {'floor' if floor else 'no floor'}")
    return n, bad


def _brush_boxes(text: str, note: str) -> list:
    """The .map's brushes with this note: [(points, lo, hi)]."""
    out = []
    for b in re.findall(r"// brush \d+ " + re.escape(note) + r"\n\{\n((?:\(.*\n)+)\}", text):
        pts = [tuple(map(float, p)) for p in re.findall(r"\( (\S+) (\S+) (\S+) \)", b)]
        out.append((pts, [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]))
    return out


def octagon_sizes(text: str, note: str, r100: float) -> list:
    """Brief 32: the sizes (percent) of the .map's octagons with this note - an octagon turned 22.5 degrees whose
    circumradius at 100 % is r100 spans 2 r cos(22.5) across."""
    import math
    return sorted(round((hi[0] - lo[0]) / (2 * math.cos(math.pi / 8)) / r100 * 100) for (_p, lo, hi) in _brush_boxes(text, note))


def frame_sizes(text: str) -> list:
    """Brief 32: each frame's size (percent) from its portal sheet: 2 x 40 across at 100 % (posts paired by distance
    mixed two frames standing near each other)."""
    return sorted(round(max(hi[0] - lo[0], hi[1] - lo[1]) / (2 * fix_mod.PORTAL_HALF) * 100)
                  for (_p, lo, hi) in _brush_boxes(text, "portal sheet"))


def over_air(bsp: Path, text: str) -> list:
    """Brief 32: each plinth and plate whose underside is over air at more than 10 % of it (points every 4 units inside
    its outline, the BSP's contents 4 under its bottom)."""
    import mapgen_map_survey as sv
    w = sv.World(str(bsp))
    out = []
    for note in ("pad plinth", "spawn plate"):
        for pts, lo, hi in _brush_boxes(text, note):
            ring = sorted({(round(p[0], 1), round(p[1], 1)) for p in pts})
            cx, cy = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
            r = max(((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5 for p in ring) * 0.92   # the octagon's inside
            n = air = 0
            x = lo[0] + 2
            while x < hi[0]:
                y = lo[1] + 2
                while y < hi[1]:
                    if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                        n += 1
                        air += 0 if w.contents(x, y, lo[2] - 4) & 1 else 1
                    y += 4
                x += 4
            if n and air / n > 0.10:
                out.append(f"{note} at {cx:.0f} {cy:.0f} {lo[2]:.0f}: {100 * air / n:.0f} % over air")
    return out


def spawns_on_plates(text: str) -> tuple:
    """Brief 32: (spawns over a plate, [the ones not standing on it])."""
    plates = _brush_boxes(text, "spawn plate")
    on, bad = 0, []
    for m in re.finditer(r'"classname" "info_player_deathmatch"\n"origin" "(\S+) (\S+) (\S+)"', text):
        x, y, z = (float(m.group(i)) for i in (1, 2, 3))
        for _p, lo, hi in plates:
            # brief 34: and at its height - a tower's storeys stand over each other
            if lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] and lo[2] - 8 <= z - 24 <= hi[2] + 8:
                on += 1
                if abs(z - (hi[2] + 24)) > 0.5:
                    bad.append(f"{x:.0f} {y:.0f}: origin {z:.0f}, plate top {hi[2]:.0f}")
                break
    return on, bad


def fixtures_hanging(bsp: Path, text: str) -> list:
    """The hanging measure's brushes that are a pad's or a frame's (by the .map's notes round each one's middle)."""
    import mapgen_map_survey as sv
    blocks = re.findall(r"// brush \d+ ((?:pad|portal|spawn) \w+)\n\{\n((?:\(.*\n)+)\}", text)
    boxes = []
    for note, b in blocks:
        pts = [tuple(map(float, p)) for p in re.findall(r"\( (\S+) (\S+) (\S+) \)", b)]
        boxes.append((note, [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]))
    out = []
    for (x, y, z, why) in sv.hanging_brushes(sv.World(str(bsp))):
        for note, lo, hi in boxes:
            if all(lo[i] - 1 <= v <= hi[i] + 1 for i, v in enumerate((x, y, z))):
                out.append(f"{note} {why} at {x} {y} {z}")
                break
    return out


def band(bands, start):
    hit = [(n, v) for n, v in bands.items() if n.startswith(start)]
    return hit[0] if hit else (start, (False, "no such row"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", action="store_true")
    ap.add_argument("--only", choices=list(CASES))
    ap.add_argument("--size", type=int, default=0, help="brief 32: ask this size (percent) of every pad, frame and plate")
    a = ap.parse_args()
    sizes = {k: a.size for k in fix_mod.SIZE_KEYS.values()} if a.size else {}
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    os.environ["MAPGEN_HELPERS"] = str(STUDIO / "engine" / "helpers")
    os.environ["MAPGEN_Q2TOOL"] = str(STUDIO / "engine" / "q2tool.exe")
    plans = {}
    for label, (params, seed) in CASES.items():
        if a.only and label != a.only:
            continue
        print(f"== {label} {params} seed {seed}")
        P = pm.best_plan(dict(params, **sizes), seed, 24, workers=1)[0]
        plans[label] = P
        q = P.params
        t = time.time()
        got = build(P, q, f"mg_fx_{label}", WORK / label)
        if got is None:
            row(False, f"{label}: compiled")
            continue
        bands, r, text, landed, flown, bsp = got
        fx = P.metrics.get("fixtures") or {}
        n = notes(text)
        tele = 2 * len(P.teleports)
        print(f"   built in {time.time() - t:.0f} s; plan: {len(P.pads)} pads, {tele} teleporter discs; fixtures {fx}; notes {n}")
        row(n.get("pad disc", 0) + n.get("pad wedge", 0) == len(P.pads) == n.get("pad plinth", 0)
            and n.get("pad flow", 0) == n.get("pad wedge", 0),
            f"{label}: every pad its plinth and a disc or a wedge (with its sheet) in the .map", f"{n}")
        row(n.get("portal post", 0) == 2 * (fx.get("frames", 0) + fx.get("posts", 0)) and n.get("portal sheet", 0) == fx.get("frames", 0) + fx.get("posts", 0)
            and fx.get("teleporters") == tele, f"{label}: the teleporters' frames in the .map as the record counts them",
            f"{fx.get('frames')} framed, {fx.get('posts')} posts only, {fx.get('bare')} bare of {tele}")
        # brief 34: every pad's landing marked on its floor (a shaft's pad lands in a doorway: no mark there)
        floor_lands = sum(1 for (a_, t_, *_r) in P.pads if t_ in P.owner and P.spaces[P.owner[t_]].floor.get(t_, (0, ""))[1] == "flat")
        row(n.get("pad landing", 0) == fx.get("landings", 0) == floor_lands,
            f"{label}: every pad's landing marked on its floor", f"{n.get('pad landing', 0)} marks, {floor_lands} landings on a floor of {len(P.pads)} pads")
        fm = fix_mod.measure_map(text)
        row(fm["pads_min_apart"] is None or fm["pads_min_apart"] >= 191,
            f"{label}: two pads on one floor at least 192 apart (brief 34)", f"nearest {fm['pads_min_apart']}")
        row(fm["worst"][1] <= fix_mod.REPEAT_MAX, f"{label}: no more than two like things within four cells (brief 34)",
            f"{fm['worst']}; all {fm['repeats']}")
        nw, bad = wedge_dirs(text)
        row(nw == n.get("pad wedge", 0) and not bad, f"{label}: every wedge rises along its flight, its arrows point that way",
            f"{nw} wedges" + (f"; {'; '.join(bad[:3])}" if bad else ""))
        hung = fixtures_hanging(bsp, text)
        row(not hung, f"{label}: no piece of a pad or a frame in the air (the hanging measure, even on an open space)",
            "; ".join(hung[:3]) or "none")
        for start in ("fixtures:", "nothing hanging", "traps"):
            name, (ok, said) = band(bands, start)
            row(ok, f"{label}: the judge's «{name[:60]}»", said[:160])
        row(landed == flown == len(P.pads), f"{label}: every pad flown lands (the people's survey)", f"{landed} of {flown}, {len(P.pads)} planned")
        row((r.get("movers") or {}).get("teleporters", 0) == tele, f"{label}: every teleporter crossed (the people's survey)",
            f"{(r.get('movers') or {}).get('teleporters')} of {tele}")
        nd, bad = discs_free(bsp, text)
        row(nd == tele and not bad, f"{label}: every teleporter's disc stands free (the BSP)", f"{nd} discs" + (f"; {'; '.join(bad)}" if bad else ""))
        names = (sc.style_mod.palette(q.get("style") or {}, P.seed, players=q["players"], game=GAME).get("fx") or {})
        row(len(names) == 5 and all((GAME / "textures" / f"{p}.wal").is_file() and (GAME / "textures" / f"{p}.jpg").is_file()
                                    for p in names.values()), f"{label}: the five fixture textures in the game")
        if STUDIO_BUILD.is_file():
            fv = WORK / f"{label}_views.txt"
            subprocess.run([str(STUDIO_BUILD), "--fixture-views", str(bsp), str(fv)], timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            views = fv.read_text(encoding="utf-8").split("\n") if fv.is_file() else []
            kinds = {v.split()[0] for v in views if v.strip()}
            want = ({"pad"} if P.pads else set()) | ({"teleporter"} if fx.get("frames", 0) + fx.get("posts", 0) else set())
            row(want <= kinds, f"{label}: the covers find a pad and a teleporter to look at", "; ".join(v for v in views if v))
        if a.size:
            fs = P.fx_size
            want_pads = sorted(fs[("pad", i)] for i in range(len(P.pads)))
            got_plinth = octagon_sizes(text, "pad plinth", fix_mod.PLINTH_R)
            row(got_plinth == want_pads and all(v <= max(a.size, 100) for v in got_plinth),
                f"{label}: the pads' plinths measure the sizes planned", f"{got_plinth} planned {want_pads}")
            want_tele = sorted(v[0] for k_, v in fs.items() if k_[0] == "tele")
            framed = fx.get("frames", 0) + fx.get("posts", 0)
            got_tele = frame_sizes(text)
            row(len(got_tele) == framed and all(g in want_tele for g in got_tele),
                f"{label}: the frames measure the sizes planned", f"{got_tele} planned {want_tele}, {framed} built")
            want_plate = sorted(v for k_, v in fs.items() if k_[0] == "spawn" and v)
            got_plate = octagon_sizes(text, "spawn plate", fix_mod.PLATE_R)
            row(got_plate == want_plate and fx.get("plates", 0) == len(want_plate) and (len(want_plate) > 0) == (a.size > 0),
                f"{label}: the spawns' plates measure the sizes planned", f"{len(got_plate)} plates {got_plate[:8]}, "
                f"{len(P.spawns) - len(want_plate)} spawns without one")
            on, bad = spawns_on_plates(text)
            row(on == len(want_plate) and not bad, f"{label}: every spawn on a plate stands on it", f"{on}" + (f"; {bad[:2]}" if bad else ""))
            air = over_air(bsp, text)
            row(not air, f"{label}: no plinth or plate over air (at most 10 % of its underside)", "; ".join(air[:3]) or "none")
            said = (P.metrics.get("fx_sizes") or {}).get("said") or []
            print(f"   the record's line on the sizes: {' | '.join(said) or 'every one as asked'}")
        if a.engine:
            t = time.time()
            acc, why = sc.engine_accepts(STUDIO / "engine" / "pipeline.exe", bsp, GAME, WORK / f"{label}_probe")
            row(acc, f"{label}: the engine takes it as a base", f"{why} ({time.time() - t:.0f} s)")
            shutil.rmtree(WORK / f"{label}_probe", ignore_errors=True)
    # brief 32's RED: the footprint test off - a plinth or a plate reaches over an edge
    if a.size > 100 and plans:
        # the tower: its galleries edge the atrium (a space's pads and spawns stand two cells in from its islands' edges)
        label = next(lb for lb in ("tower", "rooms", "space") if lb in plans)
        keep = fix_mod.disc_cells
        fix_mod.disc_cells = lambda *_a: set()
        try:
            P4 = pm.best_plan(dict(CASES[label][0], **sizes), CASES[label][1], 24, workers=1)[0]
            got = build(P4, P4.params, f"mg_fx_red4_{label}", WORK / f"red4_{label}")
        finally:
            fix_mod.disc_cells = keep
        if got:
            air = over_air(got[5], got[2])
            row(bool(air), f"RED 32 ({label}): with the footprint test off a plinth or a plate reaches over air - goes red",
                f"{len(air)}: " + ("; ".join(air[:2]) or "nothing over air"))
    # the REDs: the same plans, a constant changed in this process
    if "space" in plans or "tower" in plans:
        label = "tower" if "tower" in plans else "space"
        P = plans[label]
        fix_mod.ARROW_TURN = 180
        try:
            P2 = pm.best_plan(dict(CASES[label][0]), CASES[label][1], 24, workers=1)[0]
            got = build(P2, P2.params, f"mg_fx_red2_{label}", WORK / f"red2_{label}")
        finally:
            fix_mod.ARROW_TURN = 0
        if got:
            nw, bad = wedge_dirs(got[2])
            row(nw > 0 and len(bad) == nw, f"RED D2 ({label}): the arrows turned against the flight go red",
                f"{len(bad)} of {nw} wedges said wrong")
    if plans:
        label = next(lb for lb in ("space", "rooms", "tower") if lb in plans and plans[lb].teleports)
        keep = (fix_mod.SLAB_FROM, fix_mod.SLAB_TO, fix_mod.SLAB_HALF)
        fix_mod.SLAB_FROM, fix_mod.SLAB_TO, fix_mod.SLAB_HALF = -40, 40, 40
        try:
            P3 = pm.best_plan(dict(CASES[label][0]), CASES[label][1], 24, workers=1)[0]
            got = build(P3, P3.params, f"mg_fx_red3_{label}", WORK / f"red3_{label}")
        finally:
            fix_mod.SLAB_FROM, fix_mod.SLAB_TO, fix_mod.SLAB_HALF = keep
        if got:
            bands, r, text, landed, flown, bsp3 = got
            framed = (P3.metrics.get("fixtures") or {}).get("frames", 0)
            nd, bad = discs_free(bsp3, text)
            row(framed > 0 and len(bad) >= framed, f"RED D3 ({label}): the slab across the disc goes red",
                f"{len(bad)} of {nd} discs said buried, {framed} framed")
    print("PASS" if not FAILED else f"FAIL ({FAILED})")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
