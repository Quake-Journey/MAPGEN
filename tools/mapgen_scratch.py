r"""Brief 19: a NEW map from scratch - parameters in, a compiled, lit, measured map out.

    python tools/mapgen_scratch.py OUT_DIR [--params params.json] [--players N] [--seed S] [--name NAME]
                                   [--candidates K] [--game DIR] [--threads T]

The chain:
  1. the parameters with every «по умолчанию» resolved (`mapgen_scratch_plan.defaults`) - written to `request.json`;
  2. skeletons of many seeds derived from the one asked, scored on their own walk graphs against the human bands,
     best first (`mapgen_scratch_plan.best_plan`);
  3. for the best K: the style's palette (`mapgen_scratch_style`), the brushes and entities (`mapgen_scratch_world`),
     a `.map`, the pinned compiler's three passes (`mapgen_scratch_build.compile_map`), and the measure people's maps
     were taken with (`mapgen_map_survey`) held to the bands (`check_mapgen_new_map.judge`);
  4. the first that holds every band - else the one that fails fewest - is the map: `NAME.map`, `NAME.bsp`,
     `skeleton.txt`, `plan.png`, `survey.json`, `bands.txt`, `style.txt` in OUT_DIR, and one line per candidate in
     `candidates.txt` with why it was or was not taken.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_scratch_plan as plan_mod  # noqa: E402
import mapgen_scratch_words as words_mod  # noqa: E402
import mapgen_scratch_style as style_mod  # noqa: E402
import mapgen_scratch_world as world_mod  # noqa: E402
import mapgen_scratch_build as build_mod  # noqa: E402
import mapgen_map_survey as survey_mod  # noqa: E402
import check_mapgen_new_map as bands_mod  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")



# the PO 13.11: the scripted pieces' names in the description's rows (the form's words)
PIECE_WORDS = {
    "trains": ("ездящих платформ", "riding platforms"), "stones": ("рядов тонущих плит", "rows of sinking stones"),
    "traps": ("комнат-ловушек", "trap rooms"), "rotators": ("вращающихся", "rotating pieces"),
    "shutters": ("створок по таймеру", "timed shutters"), "pickup_walls": ("стен от предмета", "walls opened by an item"),
    "bent_bridges": ("изогнутых мостов", "bent bridges"), "pool_ladders": ("лесенки из бассейнов", "ladders out of pools"),
    "wall_steps": ("ступеней по стене", "wall steps"), "lasers": ("лазерных заслонов", "laser gates"),
    "pistons": ("поршней в проходе", "pistons in a passage"), "pendulums": ("маятников", "pendulums"),
    "trapdoors": ("проваливающихся полов", "trapdoors"), "geysers": ("лавовых гейзеров", "lava geysers"),
    "turn_bridges": ("поворотных мостов", "turning bridges"), "currents": ("мостов-течений", "current bridges"),
    "waves": ("волн столбов", "pillar waves"),
    "drills": ("буровых установок", "drilling rigs"), "cogs": ("шестерён на стенах", "cogs on walls"),
    "turrets": ("турелей в проходах", "turret passages"), "conveyors": ("конвейеров с грузами", "conveyors with crates"),
}

def engine_accepts(engine: Path, bsp: Path, game: Path, work: Path) -> tuple[bool, str]:
    """The engine's own first step on this base - its rebuild and the plan (`--plan-only`: nothing built): a base it
    refuses (an item standing otherwise in its rebuild, 04.11) would end the Studio's run at once."""
    import os
    import shutil
    import subprocess
    q2tool = os.environ.get("MAPGEN_Q2TOOL") or str(build_mod.compiler()[0])
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    cmd = [str(engine), q2tool, str(bsp), str(work / "job"), "q2mg", "70", "1", "--moddir", str(game), "--plan-only",
           "--memory", "2000", "--checkpoints", "1"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=900,
                           creationflags=build_mod.NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        # brief 20, 05.11: a skeleton the engine took over 15 minutes to plan ended the whole run with a traceback -
        # it is a candidate refused, the next one is asked
        return False, "the engine took over 15 minutes over this base"
    # memory mode keeps the progress in memory: the engine's summary says it. A base it refuses ends as ERR_BASELINE
    # (mapgen_pipeline.c, before the plan); one it cannot open says «the donor was not opened»; a base it holds goes
    # on to the plan, which under --plan-only ends as ERR_GENERATE by design («nothing is built»)
    first = next((ln.strip() for ln in r.stdout.splitlines() if ln.strip()), "")
    if first == "ERR_BASELINE":
        return False, "ERR_BASELINE: its rebuild of the base differs (an item, a floor or an area)"
    if "the donor was not opened" in r.stderr or first not in ("ERR_GENERATE", "OK", "ERR_TARGET_UNREACHABLE"):
        return False, (first + " " + r.stderr.strip()[-200:]).strip()
    return True, ""


def build_candidate(job: tuple) -> tuple:
    """One candidate of `make`: its map written, compiled, surveyed and judged in its own folder `candK` - a worker of
    the candidates' pool (brief 24 D3.2), or called in turn. Returns (k, its log lines, its entry for the choice or None
    when it did not compile); the entry is (failed bands, sight lines over the asked, k, plan, survey, palette)."""
    k, P, q, name, out, game, threads = job
    os.environ["MAPGEN_GAME"] = str(game)
    said = []
    cdir = out / f"cand{k}"
    cdir.mkdir(exist_ok=True)
    pal = style_mod.palette(q.get("style") or {}, P.seed, players=q["players"], game=game)
    world, brushes, ents = world_mod.build_plan(P, pal, title=name)
    mp = cdir / f"{name}.map"
    build_mod.write_map(mp, world, brushes, ents)
    (cdir / "skeleton.txt").write_text(plan_mod.skeleton_text(P), encoding="utf-8")
    try:
        plan_mod.draw(P, cdir / "plan.png")
    except Exception as e:  # noqa: BLE001 - a picture is a help, never a reason to stop
        said.append(f"  (no picture: {e})")
    t1 = time.time()
    # the light: the style's own calibration (the source maps' fitted light, D4) or the compiler's defaults
    ok, tail = build_mod.compile_map(mp, game, threads, rad_flags=pal.get("rad_flags") or "", log=cdir / "compile.log")
    if not ok:
        said.append(f"cand{k} seed {P.seed}: did not compile: {tail[-200:]!r}")
        return k, said, None
    r = survey_mod.survey(mp.with_suffix(".bsp"), doors=plan_doors(P))
    r["decor_pieces"] = P.metrics.get("decor_pieces")
    # brief 34: the pads apart and like things together, on the map as written
    import mapgen_scratch_fixtures as fx_mod
    r["fx_measure"] = fx_mod.measure_map(mp.read_text(encoding="latin-1"))
    if q.get("shape") in ("space", "tower"):
        # brief 25: the space's islands and both shapes' pads' flights
        import mapgen_space_survey as space_survey
        r["space"] = space_survey.space_part(mp.with_suffix(".bsp"))
    res = bands_mod.judge(r, q["players"], q, P.metrics)
    # the PO 12.11: the candidates are held to the items' worth and the water's too - the test map of 12.11 was chosen
    # with a pool of 10 cells and a mega 1.8 s from an armour, rows only the finished map's check measured
    try:
        bsp_ = mp.with_suffix(".bsp")
        res = list(res) + bands_mod.item_rows(bsp_, q, P.metrics)
        res += bands_mod.water_rows(bsp_, q, P.metrics, bands_mod.ITEM_STUDY.pop(str(bsp_), None))
        res += bands_mod.piece_rows(bsp_, q, P.metrics)
    except Exception as e:  # noqa: BLE001 - a measure not taken is said, the bands stand
        said.append(f"  (items and water not measured: {type(e).__name__}: {e})")
    fails = [n for n, ok_, _ in res if not ok_]
    (cdir / "survey.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    (cdir / "bands.txt").write_text("\n".join(f"{'PASS' if o else 'FAIL'}  {n}  -- {s}" for n, o, s in res),
                                    encoding="utf-8")
    # brief 25 item 1: its style beside it, so the Studio can make it the base later without building it again
    (cdir / "style.txt").write_text(style_mod.describe(pal) + "\n", encoding="utf-8")
    (cdir / "light.txt").write_text((pal.get("rad_flags") or "").strip() + "\n", encoding="utf-8")
    (cdir / "style.json").write_text(json.dumps({"source": pal.get("source"), "maps": pal.get("maps") or [],
                                                 "tone": pal.get("tone"), "sun": pal.get("sun", True)},
                                                ensure_ascii=False), encoding="utf-8")
    said.append(f"cand{k} seed {P.seed}: compiled in {time.time() - t1:.0f} s, {len(brushes)} brushes, "
                f"bands failed {len(fails)}: {', '.join(fails) or '-'}; plan score {P.metrics.get('score')}")
    # the engine's dressing opens a sight line now and then (05.11: a styled duel at 3 for 2 asked came out at 4) -
    # among candidates failing as many checks, the one with fewer lines over the asked count first
    over = max(0, int(r.get("long_lines") or 0) - int(q.get("long_lines") or 0))
    # the PO 13.11: the scripted pieces asked and not built weigh three checks - a skeleton that holds every piece he
    # asked comes first (3.68's test map mg_new_368_mach11 was taken with both pendulums missing, one check failed)
    weight = len(fails) + (2 if any(n.startswith("scripted pieces: every one asked") for n in fails)
                           and os.environ.get("MAPGEN_OLD_PIECE_WEIGHT") != "1" else 0)
    return k, said, (weight, over, k, P, r, pal)


def show_skeleton(params: dict, P, root: str, log=print) -> bool:
    """The PO 11.11: «визуализировать построение каркаса … как он строится». The chosen skeleton made again with each
    step's state kept (mapgen_scratch_plan.RECORD) - the same seed gives the same plan, checked by its text - and handed
    to the Studio in memory (`Local\\q2mem_<root>/skeleton_show.json`, held while this tool runs: the skeleton's stage).
    Nothing on the disk (the PO: «SSD не очень любит много записей»)."""
    steps = []
    plan_mod.RECORD = lambda step, Q: steps.append({"step": step, **plan_mod.show_state(Q)})
    try:
        Q = plan_mod.make_plan(params, P.seed)
    finally:
        plan_mod.RECORD = None
    # the same places, routes, items and movers (the score adds its metrics and «refused» lines to the chosen one)
    def shape(R) -> list:
        return [ln for ln in plan_mod.skeleton_text(R).splitlines()
                if ln.split(" ", 1)[0] in ("space", "route", "place", "spawn", "lift", "ladder", "pad", "teleporter",
                                           "door", "pit", "flights")]
    if Q.failed or shape(Q) != shape(P) or not steps:
        log("  (the skeleton's steps: the plan made again is not the one chosen - not shown)")
        return False
    final = plan_mod.show_state(P)
    if not steps or steps[-1]["step"] != "done":
        steps.append({"step": "done", **final})
    text = json.dumps({"version": 1, "shape": P.params.get("shape") or "rooms", "steps": steps}, separators=(",", ":"))
    ok = survey_mod.mem_publish(root, "skeleton_show.json", text.encode("utf-8"))
    log(f"the skeleton's steps for the Studio: {len(steps)} ({len(text) // 1024} KB in memory)" if ok else
        "  (the skeleton's steps: no memory section)")
    return ok


def live_tries(root: str, every: float = 0.5):
    """The PO 12.11 («когда 27 сек который шел Каркас карты то было вот так» - an empty scheme: the steps came only
    after the planner's 15 s of trying): `best_plan`'s `seen` - each skeleton tried, as it comes back, handed to the
    Studio in memory (`skeleton_live.json`, rewritten in place, at most one each `every` seconds and the last one
    always): how many are tried of how many, how many made a plan, the one just tried and the best so far."""
    state = {"at": 0.0, "made": 0, "best": None, "plan": None, "is_best": False}

    def seen(done: int, tries: int, r) -> None:
        if r is not None:
            state["made"] += 1
            if state["best"] is None or r[0] < state["best"]:
                state["best"] = r[0]
        now = time.time()
        last = done >= tries
        # the last count always goes (a last seed that made no plan keeps the picture before it)
        if (r is None and not (last and state["plan"])) or (now - state["at"] < every and not last):
            return
        state["at"] = now
        if r is not None:
            state["plan"] = json.dumps({"step": "try", **plan_mod.show_state(r[1])}, separators=(",", ":"))
            state["is_best"] = r[0] <= state["best"]
        text = (f'{{"version":1,"done":{done},"tries":{tries},"made":{state["made"]},'
                f'"best":{"true" if state["is_best"] else "false"},"plan":{state["plan"]}}}')
        survey_mod.mem_update(root, "skeleton_live.json", text.encode("utf-8"))
    return seen


def make(out: Path, params: dict, seed: int, name: str, candidates: int, game: Path, threads: int,
         tries: int = 60, log=print, engine: Path | None = None, workers: int = 0, show_mem: str = "") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    # the colour reads (the look rows) from the client the map is made for: the Studio's own textures lie there (3.45)
    os.environ["MAPGEN_GAME"] = str(game)
    st = params.get("style") or {}
    if st.get("source") == "generated":
        # the Studio's own textures (3.45): one set for the run (its number, its parameters), made before the
        # candidates - each candidate wears the same, the set is made once
        try:
            import mapgen_texgen as tg
        except ImportError as e:
            # numpy and Pillow paint them; a user's Python may have neither (mapgen_destroy.install's note)
            return {"ok": False, "why": f"the Studio's own textures need numpy and Pillow in Python "
                                        f"(pip install numpy pillow): {e}"}
        gen = dict(st.get("gen") or {})
        gen.setdefault("seed", seed)
        gen["theme"] = tg.theme_of(gen, int(gen["seed"]))
        st = dict(st, gen=gen)
        params = dict(params, style=st)
        t_ = time.time()
        key, _roles = tg.install_set(Path(game), gen, int(gen["seed"]))
        log(f"the Studio's textures: set {key} ({', '.join(f'{k_}={gen.get(k_)}' for k_ in ('theme', 'colour', 'wear', 'scale', 'relief', 'share') if gen.get(k_))}) in {time.time() - t_:.0f} s")
    if params.get("sky") is None and st.get("source") in ("maps", "mixed") and st.get("maps"):
        # «Небо над головой» by the style (brief 19 §4): the source maps' own share of standing places under sky
        shares = [survey_mod.sky_share_of(Path(m)) for m in st["maps"] if Path(m).is_file()]
        if shares:
            params = dict(params, sky=round(sum(shares) / len(shares), 2), sky_by_style=True)
            log(f"sky by the style's maps: {params['sky']:.0%} ({', '.join(f'{s_:.0%}' for s_ in shares)})")
    q = plan_mod.defaults(params)
    (out / "request.json").write_text(json.dumps({"seed": seed, "name": name, **q}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    t0 = time.time()
    # brief 20 D5: the parameters change the plan, not only its furniture - the run's number is mixed with the request
    # (its resolved parameters, name and number aside): the same request and number give the same map, another
    # request another one (3.40: the default duel and the styled one were both «seed 7038, 27 x 28»)
    import hashlib
    key = json.dumps({k: v for k, v in q.items() if k not in ("name", "seed")}, sort_keys=True, ensure_ascii=False,
                     default=str)
    plan_seed = seed * 100003 + int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 100000
    plans = plan_mod.best_plan(params, plan_seed, tries, workers=max(1, workers or threads),
                               progress=lambda d, n: log(f"plans: {d} of {n}"),
                               seen=live_tries(show_mem) if show_mem else None)
    log(f"skeletons: {len(plans)} of {tries} seeds made a plan ({time.time() - t0:.1f} s)")
    if not plans:
        return {"ok": False, "why": "no skeleton"}
    # the generator's own textures (style «generator» or «mixed») must be in the game the compiler reads: a fresh
    # client has no textures/mapgen - the same plain copy the destroyed maps use
    if (q.get("style") or {}).get("source", "generator") in ("mixed", "pack"):
        from mapgen_destroy import install, pack_dir
        try:
            install(game, pack_dir(None))
        except SystemExit as e:
            return {"ok": False, "why": str(e)}
    # the skeleton first (brief 19 D9): the Studio draws it before any brush exists, so a wrong map is seen early
    try:
        plan_mod.draw(plans[0], out / "plan.png")
        (out / "skeleton.txt").write_text(plan_mod.skeleton_text(plans[0]), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log(f"  (no early picture: {e})")
    if show_mem:
        try:
            show_skeleton(params, plans[0], show_mem, log)
        except Exception as e:  # noqa: BLE001 - a picture is a help, never a reason to stop
            log(f"  (the skeleton's steps: {e})")
    best = None
    made = []
    lines = []
    # brief 24 D3.2: the candidates built side by side, `workers` at a time, each compile on threads // workers; their
    # lines and the choice in the candidates' order, as the loop had them (tools/check_mapgen_scratch_parallel.py)
    chosen = plans[:candidates]
    workers = max(1, min(workers or threads, len(chosen)))
    cthreads = max(1, threads // workers)
    jobs = [(k, P, q, name, out, game, cthreads) for k, P in enumerate(chosen)]
    if workers > 1:
        import multiprocessing
        import mapgen_scratch as self_mod     # by its own name: the pool's workers import it (this file runs as __main__)
        results = {}
        with multiprocessing.Pool(workers) as pool:
            for done, (k, said, entry) in enumerate(pool.imap_unordered(self_mod.build_candidate, jobs, chunksize=1), 1):
                results[k] = (said, entry)
                log(f"candidates built: {done} of {len(jobs)}")
        ordered = [(k, *results[k]) for k in sorted(results)]
    else:
        ordered = []
        for n, job in enumerate(jobs, 1):
            k, said, entry = build_candidate(job)
            ordered.append((k, said, entry))
            log(f"candidates built: {n} of {len(jobs)}")
            if entry is not None and entry[0] == 0 and engine is None:
                break       # with the engine named, every candidate is made: one it refuses leaves the next
    for k, said, entry in ordered:
        for line in said:
            if line.startswith("  ("):
                log(line)
                continue
            lines.append(line)
            log(line)
        if entry is not None:
            made.append(entry)
            if entry[0] == 0 and engine is None:
                break       # as the one-by-one loop: no candidate after the first that fails nothing
    if not made:
        (out / "candidates.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"ok": False, "why": "no candidate compiled"}
    # the fewest failed bands first. Brief 25 item 1 (the PO's ly3, 06.11: the skeleton stage 309 s, ~270 of them the
    # engine's probe of the chosen candidate - its rebuild and plan, which its own first stage then did again): no
    # probe here; the order of merit is written (order.json) and the Studio hands the engine the first, the next when
    # the engine refuses one (its «baseline-refused» line) - what the probe would have said, the run says
    made.sort(key=lambda t: (t[0], t[1], t[2]))
    order = [t[2] for t in made]
    (out / "order.json").write_text(json.dumps(order), encoding="utf-8")
    lines.append("candidates in order of merit: " + ", ".join(f"cand{k}" for k in order))
    log(lines[-1])
    (out / "candidates.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    nf, _over, k, P, r, pal = made[0]
    promote(out, name, k, q)
    return {"ok": nf == 0, "candidate": k, "seed": P.seed, "bands_failed": nf, "survey": r}


def promote(out: Path, name: str, k: int, q: dict | None = None) -> int:
    """Candidate k made the base: its map, skeleton, picture, measure and style into the skeleton's folder, its light
    flags beside the base (Generation.cs, row 405: <base>.light.txt -> --light-flags: the finished map relit with the
    flags the base was judged with - 3.42: people's dark textures take x1.8 under 196), its record written. The Studio
    calls it again (`--promote K`) for the next candidate when the engine refuses one (brief 25 item 1)."""
    cdir = out / f"cand{k}"
    if not (cdir / f"{name}.bsp").is_file():
        print(f"no candidate {k} in {out}")
        return 1
    q = q or json.loads((out / "request.json").read_text(encoding="utf-8"))
    for f in (f"{name}.map", f"{name}.bsp", "skeleton.txt", "plan.png", "survey.json", "bands.txt", "style.txt",
              "style.json"):
        if (cdir / f).is_file():
            (out / f).write_bytes((cdir / f).read_bytes())
    lt = out / f"{name}.light.txt"
    flags = (cdir / "light.txt").read_text(encoding="utf-8").strip() if (cdir / "light.txt").is_file() else ""
    if flags:
        lt.write_text(flags + "\n", encoding="utf-8")
    elif lt.is_file():
        lt.unlink()
    # brief 29 D2 (Fable's review of 3.54): the light the base was judged with is ITS calibration, in the form the light
    # chain after the generation reads (mapgen_light_calibrate.donor_light: `<base>.light_fit.json` of this very file).
    # Without it the chain took the base for a donor never calibrated: the fit relit the map against itself and kept
    # '-scale 1.858' without the style's '-maxlight 196' - 2 % of the PO's space floor burnt white (mg_new_26301; the
    # run's own row, measured before that relight, said 0 %) - and the ruin lit its cracks with the compiler's defaults
    import hashlib
    (out / f"{name}.light_fit.json").write_text(json.dumps(
        {"sha256": hashlib.sha256((out / f"{name}.bsp").read_bytes()).hexdigest(), "name": name, "flags": flags,
         "keys": {}, "faithful": True, "score": 0.0, "source": "the style of the map from scratch (mapgen_scratch promote)",
         "table": []}, indent=1), encoding="utf-8")
    r = json.loads((cdir / "survey.json").read_text(encoding="utf-8"))
    m = {}
    for line in (cdir / "skeleton.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("metrics "):
            m = json.loads(line[8:])
    pal = json.loads((cdir / "style.json").read_text(encoding="utf-8")) if (cdir / "style.json").is_file() else {}
    write_record(out, q, m, r, pal, bands_mod.judge(r, q["players"], q, m))
    (out / "promoted.txt").write_text(f"cand{k}\n", encoding="utf-8")
    print(f"cand{k} is the base")
    return 0


def plan_doors(P) -> list:
    """Brief 21 D2: the skeleton's doorways in map units for the dead-end measure (`mapgen_map_survey.dead_ends`) -
    the middle of each, its sill, half its width; the asked dead end's drop is left open."""
    out = []
    for i, d in enumerate(P.doors):
        if d.rj or not d.cells or d.kind == "swim":
            continue                # a tube under water is not a doorway (the PO 12.11)
        pcs = [plan_mod.phys(c) for c in d.cells]
        xs, ys = [c[0] for c in pcs], [c[1] for c in pcs]
        x, y = (min(xs) + max(xs) + 1) * plan_mod.CELL / 2, (min(ys) + max(ys) + 1) * plan_mod.CELL / 2
        half = (max(max(xs) - min(xs), max(ys) - min(ys)) + 1) * plan_mod.CELL / 2
        sx, sy = P.metrics.get("world_shift") or (0, 0)      # a plan moved to the world's middle (build_plan)
        out.append((x + sx, y + sy, d.z + (plan_mod.RISE_PER_CELL if d.stair else 0), half, f"{d.kind} {d.a}-{d.b}"))
    return out


def skeleton_doors(path: Path) -> list:
    """The same from a skeleton's text («route a b kind cells x,y x,y z Z sides za zb»): the finished map's record."""
    import re
    out = []
    if not path.is_file():
        return out
    sx = sy = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("metrics "):
            sx, sy = json.loads(line[8:]).get("world_shift") or (0, 0)
    for line in path.read_text(encoding="utf-8").splitlines():
        m_ = re.match(r"route (\d+) (\d+) (\w+) cells ([-\d, ]+) z (-?\d+)", line)
        if not m_ or m_.group(3) == "swim" or line.rstrip().endswith(" rj"):
            continue                # a tube under water; the dead-end stack's drop, left open as plan_doors leaves it
        cells = [tuple(int(v) for v in c.split(",")) for c in m_.group(4).split()]
        if not cells:
            continue
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        x, y = (min(xs) + max(xs) + 1) * plan_mod.CELL / 2, (min(ys) + max(ys) + 1) * plan_mod.CELL / 2
        half = (max(max(xs) - min(xs), max(ys) - min(ys)) + 1) * plan_mod.CELL / 2
        out.append((x + sx, y + sy, int(m_.group(5)), half, f"{m_.group(3)} {m_.group(1)}-{m_.group(2)}"))
    return out


MECH_RU = {"clock": "два главных предмета на часах", "halves": "две половины карты",
           "key_gun_ledge": "ключевая пушка на уступе", "asymmetry": "асимметрия маршрута",
           "small_health": "много мелких аптечек", "spawn_pressure": "точки появления под давлением",
           "three_approaches": "три подхода и выход телепорта напротив", "tele_mirror": "телепорт к зеркальному стеку",
           "pad_pit": "джампад над пропастью", "lift_exposure": "лифт как уязвимость",
           "ladder_item": "стремянка под удерживаемым предметом", "dead_end_stack": "тупик со стеком"}
MECH_EN = {"clock": "two stack items on a clock", "halves": "two halves", "key_gun_ledge": "key gun on a ledge",
           "asymmetry": "route asymmetry", "small_health": "many small health spots",
           "spawn_pressure": "spawns under pressure", "three_approaches": "three approaches and a teleporter exit opposite",
           "tele_mirror": "teleport to a mirrored stack", "pad_pit": "jump pad over a chasm",
           "lift_exposure": "lift as exposure", "ladder_item": "ladder under a held item",
           "dead_end_stack": "dead-end stack"}


def final_record(out: Path, bsp: Path) -> int:
    """The record again, measured on the map as the generation finished it (after the dressing edits): what the
    Studio's description says is the map the PO plays, not its base."""
    req = json.loads((out / "request.json").read_text(encoding="utf-8"))
    metrics = {}
    for line in (out / "skeleton.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("metrics "):
            metrics = json.loads(line[8:])
    st = req.get("style") or {}
    pal = {"source": st.get("source", "generator"), "maps": [Path(m).stem for m in st.get("maps") or []]}
    if (out / "style.json").is_file():
        pal = json.loads((out / "style.json").read_text(encoding="utf-8"))
    r = survey_mod.survey(bsp, doors=skeleton_doors(out / "skeleton.txt"))
    # brief 34: the pads apart and like things together - the map the skeleton wrote (the engine moves none of them on a
    # map from scratch: its moving families are skipped)
    base_map = out / f"{req.get('name') or bsp.stem}.map"
    if base_map.is_file():
        import mapgen_scratch_fixtures as fx_mod
        r["fx_measure"] = fx_mod.measure_map(base_map.read_text(encoding="latin-1"))
    if req.get("shape") in ("space", "tower"):
        # 3.57: the islands' and pads' own measure on the finished map, as the candidates had it (build_candidate) - without
        # it the record said «Дальность джампадов: … → 0» and its check failed «space: its own measure»
        import mapgen_space_survey as space_survey
        r["space"] = space_survey.space_part(bsp)
    write_record(out, req, metrics, r, pal, bands_mod.judge(r, req["players"], req, metrics), final=True)
    print(f"record of the finished map written to {out}")
    return 0


def write_record(out: Path, q: dict, m: dict, r: dict, pal: dict, res: list, final: bool = False) -> None:
    """Brief 19 D5: what was asked and what came out, per parameter, in the PO's words (RU) and in English - the
    Studio puts it in the map's description; record.json keeps the numbers."""
    mv = r.get("movers") or {}
    rows = [  # key, RU, EN, asked, got
        ("players", "Игроков", "Players", q["players"], q["players"]),
        ("spawns", "Точек появления", "Spawns", q["spawns"], r.get("spawns")),
        ("floor_area", "Площадь пола, млн ед²", "Floor area, M u²", q["floor_area"], r.get("walk_area_mu2")),
        ("levels", "Уровней высоты", "Height levels", q["levels"], r.get("levels")),
        ("vertical_span", "Вертикальный размах", "Vertical span", q.get("vertical_span") or "-", r.get("vertical_span")),
        ("sky", "Небо над головой", "Sky overhead", f"{float(q['sky']):.0%}", f"{float(r.get('sky_share') or 0):.0%}"),
        ("long_lines", "Длинных линий прострела", "Long sight lines",
         words_mod.known("≤4" if q.get("players", 2) <= 2 else "≤6") if q.get("long_lines_default") else q["long_lines"],
         r.get("long_lines")),
        ("shape", "Форма", "Shape", q["shape"], q["shape"]),
        ("stairs", "Лестниц (пролётов)", "Flights of steps", q["stairs"], m.get("stairs_got")),
        ("ramps", "Пандусов", "Ramps", q["ramps"], m.get("ramps_got")),
        ("lifts", "Лифтов", "Lifts", q["lifts"], mv.get("plats")),
        ("pads", "Джампадов", "Jump pads", q["pads"], mv.get("pads")),
        ("teleporters", "Телепортов (пар)", "Teleporter pairs", q["teleporters"], (mv.get("teleporters") or 0) // 2),
        ("ladders", "Лестниц-стремянок", "Ladders", q["ladders"], mv.get("ladders")),
        ("drops", "Спусков (в одну сторону)", "One-way drops", q["drops"], m.get("drops_got")),
        ("doors", "Дверей", "Doors", q["doors"], r.get("doors")),
        ("windows", "Окон", "Windows", q["windows"], m.get("windows_got")),
        # brief 21+: where the powerups lie, asked → made (in words)
        ("powerup_access", "Главные предметы", "Powerups",
         words_mod.access(q.get("powerup_access"), bool(q.get("powerup_cycle"))),
         words_mod.powerup_sites(m.get("powerup_sites") or [])),
        # 3.46: medusa_b1's round shapes, asked → made
        ("round", "Скругления", "Round shapes",
         words_mod.ROUND.get(q.get("round") or "", words_mod.NONE),
         words_mod.round_made(m.get("round") or {})),
        # brief 21: the new pieces of the skeleton, said in the description
        ("rooms_over", "Комнат над комнатами", "Rooms over rooms", m.get("stacked_asked", "-"), m.get("stacked_rooms", 0)),
        ("corridor_turns", "Коридоров с поворотом", "Corridors with a turn", "≥1", m.get("corridor_turns", 0)),
        ("water", "Вода", "Water", f"{float(q['water']):.0%}", f"{float(r.get('water_share') or 0):.0%}"),
        ("lava", "Лава", "Lava", f"{float(q['lava']):.0%}", f"{float(r.get('lava_share') or 0):.0%}"),
        ("slime", "Кислота", "Slime", f"{float(q['slime']):.0%}", f"{float(r.get('slime_share') or 0):.0%}"),
        ("pits", "Смертельных ям", "Deadly pits", q["pits"], r.get("deadly_volumes")),
        ("items_at_height", "Главных предметов на высоте", "Major items at height",
         f"{float(q['items_at_height']):.0%}", f"{float(r.get('majors_at_height') or 0):.0%}"),
        ("decor", "Украшений на стенах", "Wall decorations", q.get("decor"), m.get("decor_pieces")),
        ("mode", "Режим", "Mode", q.get("mode"), q.get("mode")),
        ("openness", "Коридоры / залы / открытые", "Corridors / halls / open",
         "/".join(f"{float(v):.0%}" for v in q["openness"]) if q.get("openness") else "-",
         "/".join(f"{float(r.get(k) or 0):.0%}" for k in ("share_corridor", "share_medium", "share_open"))),
        ("spawns_at_height", "Точек появления на высоте", "Spawns at height", ("≥50% (план 67%)", "≥50% (plan 67%)"),
         f"{float(r.get('spawns_at_height') or 0):.0%}"),
        ("shards", "Осколков брони", "Armour shards", q.get("shards"), (r.get("sites") or {}).get("item_armor_shard", 0)),
        ("ammo_per_spawn", "Патронов на точку появления", "Ammo per spawn", q.get("ammo_per_spawn"),
         round(sum(v for k, v in (r.get("sites") or {}).items() if k.startswith("ammo_")) / max(1, r.get("spawns") or 1), 1)),
        ("health_per_spawn", "Аптечек на точку появления", "Health per spawn", q.get("health_per_spawn"),
         round((r.get("small_health_sites") or 0) / max(1, r.get("spawns") or 1), 1)),
        ("dark_floor_share", "Тёмного пола", "Dark floor", "≤16%", f"{float(r.get('dark_floor_share') or 0):.0%}"),
        ("sun", "Солнце", "Sun", q.get("sun"), "yes" if pal.get("sun", True) else "no"),
        ("tone", "Цвет света", "Light colour", q.get("tone"), pal.get("tone", "neutral")),
    ]
    # the PO 12.11: the water as well-known maps build it and the prizes under it, asked → made
    if q.get("shape") not in ("space", "tower") and (float(q.get("water") or 0) > 0 or int(q.get("underwater") or 0) > 0):
        at = next((i for i, row in enumerate(rows) if row[0] == "slime"), len(rows) - 1) + 1
        rows[at:at] = [("water_body", "Водоёмы", "Water bodies", words_mod.water_body(q.get("water_body")),
                        words_mod.water_made(m.get("pools") or [], m.get("water_tubes") or [], m.get("prize_tubes") or [])),
                       ("underwater", "Призов под водой", "Prizes under water", int(q.get("underwater") or 0),
                        words_mod.under_made(m.get("prize_kinds") or [], m.get("prize_tubes") or []))]
    # the PO 13.11: the scripted pieces, asked → built (each kind in the form's words)
    import mapgen_scratch_pieces as pieces_mod
    qp = pieces_mod.defaults(dict(q))
    if q.get("shape") not in ("space", "tower") and pieces_mod.any_asked(qp):
        built = m.get("pieces_count") or {}
        a_ru, a_en, g_ru, g_en = [], [], [], []
        for k in pieces_mod.KINDS:
            want = (1 if qp.get(k) else 0) if k == "pool_ladders" else int(qp.get(k) or 0)
            if not want:
                continue
            ru_w, en_w = PIECE_WORDS.get(k, (k, k))
            got = int(built.get(k, 0))
            if k == "pool_ladders":
                a_ru.append(f"{ru_w}: да"); a_en.append(f"{en_w}: yes")
            else:
                a_ru.append(f"{ru_w}: {want}"); a_en.append(f"{en_w}: {want}")
            g_ru.append(f"{ru_w}: {got}"); g_en.append(f"{en_w}: {got}")
        rows.append(("pieces", "Скриптовые конструкции", "Scripted pieces", ("; ".join(a_ru), "; ".join(a_en)),
                     ("; ".join(g_ru), "; ".join(g_en))))
    look = r.get("look") or {}
    if look.get("coloured") is not None:
        rows += [
            ("coloured", "Цветных поверхностей", "Coloured surfaces", words_mod.known("50..100%"), f"{float(look['coloured']):.0%}"),
            ("seen", "Яркость на экране (середина)", "On-screen brightness (median)", words_mod.known("7..25"),
             f"{float(look['seen_p50']):.0f}"),
            ("textures", "Текстур", "Textures", words_mod.known("9..38"), look.get("textures")),
        ]
    if r.get("stacked_share") is not None:
        rows.append(("stacked", "Пол над полом", "Floor over floor",
                     ("не меньше 50%", "50% at least") if q.get("shape") == "tower" else words_mod.known("0..64%"),
                     f"{float(r['stacked_share']):.0%}"))
    if q.get("shape") == "space":
        # brief 25 A4: the open space's own, asked → made (the survey's part when measured, else the plan's)
        sp = r.get("space") or {}
        isl = sp.get("islands") or {}
        edges = words_mod.EDGES
        rows += [
            ("islands", "Островов", "Islands", q.get("islands"), isl.get("count_over_0.02mu2", m.get("islands"))),
            ("pad_only", "Только по джампаду (не меньше)", "Only by a jump pad (at least)", q.get("pad_only"),
             isl.get("reached_only_by_pad_or_teleport", m.get("pad_only"))),
            ("edges", "Края", "Edges", edges.get(q.get("edges"), ("-", "-")),
             (f"{float(sp.get('outline_void_share', 1.0)):.0%} края над пустотой",
              f"{float(sp.get('outline_void_share', 1.0)):.0%} of the edge over the void")),
            ("height_spread", "Разброс высот", "Height spread", q.get("height_spread"), r.get("vertical_span")),
            ("pad_reach", "Дальность джампадов", "Jump pads' reach", q.get("pad_reach"),
             max((p_.get("across", 0) for p_ in sp.get("pads") or []), default=0)),
            ("bridges", "Мостики", "Bridges", q.get("bridges"), m.get("bridges", 0)),
            ("isle_drops", "Спрыгиваний с острова на остров", "Jumps down between islands", "-", m.get("drops", 0)),
        ]
    fx = m.get("fixtures")
    if fx and (fx["pads"] or fx["teleporters"]):
        # brief 26: the pads' and teleporters' look
        rows += [
            ("pads_look", "Джампады: диски / наклонные со стрелками", "Jump pads: discs / slanted with arrows", fx["pads"],
             f"{fx['discs']} / {fx['wedges']}"),
            ("tele_frames", "Телепорты в раме с порталом", "Teleporters in a frame with a portal", fx["teleporters"],
             fx["frames"] + fx["posts"]),
        ]
    # brief 32: the sizes asked of the pads, the frames and the spawns' plates, and how many came out at which
    fs = m.get("fx_sizes") or {}
    for key, what, ru_, en_ in words_mod.SIZE_ROWS:
        if q.get(key) is None:
            continue
        rows.append((key, ru_, en_, words_mod.size_asked(what, (fs.get("asked") or {}).get(what)),
                     words_mod.size_made((fs.get("built") or {}).get(what) or [])))
    ways = m.get("ways")
    if ways:
        # brief 34: the ways up by kind - «Наверх: лестниц 2, лифтов 1, джампадов 1 (+3 на площадки)»
        rows.append(("ways", "Наверх", "Up", words_mod.ways_asked(q), words_mod.ways_made(ways)))
    if q.get("shape") == "tower":
        # brief 25 B: the tower's own, asked → made
        sp = r.get("space") or {}
        rows += [
            ("storeys", "Этажей", "Storeys", q.get("storeys"), m.get("storeys")),
            ("storey_height", "Высота этажа", "Storey height", q.get("storey_height"), q.get("storey_height")),
            ("shafts", "Шахт вместе с атриумом", "Shafts with the atrium", q.get("shafts"), m.get("shafts")),
            ("perches", "Площадок только по джампаду", "Ledges only a jump pad reaches", q.get("perches"), m.get("perches")),
            ("pads_landed", "Джампадов, долетающих до пола", "Jump pads landing on a floor", m.get("pads"),
             (sp.get("movers") or {}).get("pads")),
        ]
    stack = q.get("stack")
    # the set's counts, asked by name or by numbers (brief 21: «ra_mh_quad → 1» said the key, not the count)
    stack_set = stack if isinstance(stack, dict) else dict(plan_mod.STACK_SETS.get(stack, {}))
    for cls in ("item_armor_body", "item_armor_combat", "item_armor_jacket", "item_health_mega", "item_quad",
                "item_invulnerability", "item_adrenaline", "item_pack"):
        n = (r.get("sites") or {}).get(cls, 0)
        if n or stack_set.get(cls):
            rows.append((cls, words_mod.item(cls, True), words_mod.item(cls, False), stack_set.get(cls, 0), n))
    sites = r.get("sites") or {}
    for cls, n in (q.get("weapons") or {}).items():
        rows.append((cls, words_mod.item(cls, True), words_mod.item(cls, False), n, sites.get(cls, 0)))
    failed = [n for n, ok, _ in res if not ok]
    for lang, names, mech_names in (("ru", 1, MECH_RU), ("en", 2, MECH_EN)):
        ru = lang == "ru"
        # 3.57 (the PO 07.11: English in the Russian description): the players, the mode, the dressing in the form's words
        theme = (((q.get("style") or {}).get("gen") or {}).get("theme")) if isinstance(q.get("style"), dict) else None
        lines = [("Сделано с нуля" if ru else "Made from scratch") + ": " + words_mod.players(int(q["players"]), ru) + ", "
                 + words_mod.pick(words_mod.MODES, q.get("mode"), ru, str(q.get("mode"))) + ", "
                 + words_mod.source(pal.get("source"), theme, list(pal.get("maps") or []), ru) + "."]
        on = [mech_names.get(x, x) for x in q.get("mechanics") or []]
        if on:
            lines.append(("Механики: " if ru else "Mechanics: ") + ", ".join(on) + ".")
        lines.append(("Просили → получилось на готовой карте:" if final else "Просили → получилось на каркасе (до отделки правками):")
                     if ru else ("Asked → made, on the finished map:" if final else "Asked → made, on the skeleton (before the dressing edits):"))
        # the sun's and the light's values in words, not the request's keys (05.11: «Цвет света: style → people»)
        words = {"style": ("по стилю", "by the style"), "yes": ("есть", "yes"), "no": ("нет", "no"),
                 "people": ("как у известной карты", "as on the well-known map"), "neutral": ("белый", "white"),
                 "warm": ("тёплый", "warm"), "cold": ("холодный", "cold"), None: ("по стилю", "by the style")}

        def said(key, v):
            if key in ("sun", "tone") and (v is None or isinstance(v, str)):
                return words.get(v, (v, v))[0 if ru else 1]
            return words_mod.value(key, v, ru)
        skip = words_mod.SPACE_SKIP if q.get("shape") == "space" else words_mod.TOWER_SKIP if q.get("shape") == "tower" else set()
        for row in rows:
            # an open space or a tower has no stairs, liquids, windows, round shapes … (SPACE_FORCED): not said
            if row[0] in skip:
                continue
            lines.append(f"  {row[names]}: {said(row[0], row[3])} → {said(row[0], row[4])}")
        for why in (q.get("refused") or []) + list(m.get("mech_missing") or []) + list(m.get("refused") or []):
            half = why.split(" ¦ ")
            text = half[0] if ru or len(half) == 1 else half[1]
            # a mechanic not made is named by its key («asymmetry: …»): its words (3.57)
            key, _, rest = text.partition(": ")
            if rest and key in mech_names:
                text = f"{mech_names[key]}: {rest}"
            lines.append(("  Не сделано: " if ru else "  Not made: ") + text)
        if m.get("opening_race"):
            ts = m["opening_race"]
            lines.append((f"Первый бросок: от точек появления к ключевой пушке {ts[0]}..{ts[-1]} с"
                          if ru else f"Opening race: from the spawns to the key gun {ts[0]}..{ts[-1]} s"))
        if failed:
            # the rows by name and why - in the map's checks, in words (GateSaid); here only how many
            lines.append(f"Проверка карты с нуля: не прошло {len(failed)} — что именно и почему, сказано в «Проверках карты»."
                         if ru else f"From-scratch check: {len(failed)} failed - which and why, in the map's checks.")
        else:
            lines.append("Проверка карты с нуля: всё прошло." if ru else "From-scratch check: all passed.")
        (out / f"record.{lang}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "record.json").write_text(json.dumps({"asked": {k: v for k, v in q.items() if k != "style"},
                                                 "rows": [{"key": k, "asked": a[0] if isinstance(a, tuple) else a,
                                                           "got": g[0] if isinstance(g, tuple) else g}
                                                          for k, _, _, a, g in rows],
                                                 "failed": failed}, ensure_ascii=False, indent=1, default=str),
                                     encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    if len(sys.argv) == 4 and sys.argv[1] == "--final":
        return final_record(Path(sys.argv[3]), Path(sys.argv[2]))
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--params", type=Path)
    ap.add_argument("--players", type=int)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--name", default="mg_scratch")
    ap.add_argument("--candidates", type=int, default=4)
    ap.add_argument("--tries", type=int, default=60)
    ap.add_argument("--game", type=Path, default=GAME)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--workers", type=int, default=0,
                    help="processes for the plans and the candidates (brief 24 D3; 0 = as many as --threads)")
    ap.add_argument("--engine", type=Path, help="the Studio's run: every candidate built, their order written (order.json)")
    ap.add_argument("--promote", type=int, help="make candidate K of OUT the base (the engine refused the one before)")
    ap.add_argument("--show-mem", default="", help="the Studio's root: the skeleton's steps into memory as it builds")
    a = ap.parse_args()
    if a.promote is not None:
        return promote(a.out, a.name, a.promote)
    params = json.loads(a.params.read_text(encoding="utf-8")) if a.params else {}
    if a.players:
        params["players"] = a.players
    res = make(a.out, params, a.seed, a.name, a.candidates, a.game, a.threads, a.tries, engine=a.engine,
               workers=a.workers, show_mem=a.show_mem)
    print(json.dumps({k: v for k, v in res.items() if k != "survey"}, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
