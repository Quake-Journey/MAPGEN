"""The base's frame guard: the donor's plan stretched part by part before the first edit (src/mapgen/mapgen_warp.c).

The PO, 10.10.2026: «хочется именно менять донора и уже к нему пристраивать ... размеры карты могут меняться как
угодно»; «нужно чтобы генератор делал анализ до начала работ и не тратил время на бесконечные тесты». The warp is
planned on the donor, built once and walked once, before any edit. This asks it of q2dm1 at twice its area with
unequal parts (`--warp-size 200 --warp-shape 60`, seed 6686), the plan only - nothing of the edits is built:

  1 the first warped map builds: no leak where a cut splits a wall (a brush that ran past a cut and went whole with
    its middle's part ended 0.4 off its neighbour - every spread from 7 to 60 leaked, 10.10);
  2 it walks: every start reaches the others, no pickup out of reach - on the first try, not after giving the spread
    back (the walk's edge cap of 2097152 ran out on it, 10.10: ERR_MEMORY);
  3 it is what was asked: its area within 2 % of 200 %, its parts really unequal (the largest factor at least 1.5
    times the smallest);
  4 the plan is dealt on the warped base and says its word;
  5 (brief 16 D4) q2dm3 at the PO's own options (his run mg_10_6695) and the Studio's default frame (150 %, 50):
    at least four large edits (a room dug or built, a passage, a storey, a bridge) proved before a build - on the
    base as it was the plan proves two - and the plan's word at least 45 %.
  6 the turn and the ceilings: q2dm3 turned by 90 degrees on the default frame (its trains' paths moved with their
    turned boxes) and mirrored with its ceilings at 130 % - each held on its first try and accepted as the base;
  7 the shift: q2dm1's parts slid sideways by 60 % on the default frame - held, accepted (no fallback to the donor).
  8 (brief 18 D2, the PO 11.10: «масштабирование прошло более вширь … не сохраняя пропорции») q3t2 at his own frame
    (1000 %, spread 100, shift 100, ceilings 200 - his mg_10_6695), the frame alone (`--warp-only`):
      a the FIRST try stands as tall as it grew wide - its heights' factor within 5 % of sqrt(area) - and walks:
        every pickup in reach, every start, no place without a way back; no second try; AND the base it gave is
        held by its own rebuild (`stage=warp-held`: the run builds on it - a frame that only walks is given up for
        the donor as it was, which is how mg_b18_q3t2 on 3.31 came out at 100 % of its size);
      b the accepted base's Z extent over the donor's is that factor at least (the ceilings over it: what the game's
        coordinates have left of the 200 % asked, said as its `height`);
      c two of q3t2's flights (the 16-unit risers at 824 736 and the 8-unit ones at -528 128, 50 and 25 high once
        grown) walked in the base by `mapgen_dig_probe --walk`: every sample 18 of rise at the most, 128 of headroom;
      d every pickup and every player's start was put as high over its floor as it stood in the donor (`drops`;
        the base's starts asked the delivery gate's own question: a floor within 32 of a player's feet);
      e every push pad of the donor throws a player as high as it did times that factor (10 %) - the walk of the
        base against the walk of the donor (mapgen_reach_path --pushes); the falls over 250 that do not kill are
        said beside it (the report's number, not a verdict);
      f the same size with its parts equal (spread 0, no shift): every part's X and Y factor within 10 % of the
        others' and the heights' within 5 % of them - a round pillar stays round - and the first try walks;
      g the base can be MEASURED: the divergence oracle (mapgen_divergence_gate, the base against itself) holds a
        map this size - the run's every edit is held to that measure.
    RED, each alone and the first try only: `--red18` the heights kept (g_warp_tall off); `--red-solid` a body
    settled inside a solid is a place (q3t2's fillet at 701 -1882); `--red-drops` pickups grow away from their floors
    (the shotgun stacked 128 over its floor hangs out of reach); `--red-rooms` the rooms' lattice capped at 8388608
    cells (no rooms at that height: «a landmark out of reach»); `--red-ramps` the ramps ask a point's leaf (the
    flight at -528 128 gets none: c fails); `--red-flight` the walk follows a push for 180 frames only (the middle
    pad's throw lasts 3.05 s on the grown map: e fails); `--red-flat` a flat brush of the compiled base is read
    back as a brush («mirrored plane», the rebuilt world's bounds lost, its areas of another size: the base is not
    held by its rebuild - a fails) and `--red-mapping` texture mappings are compared by their raw numbers (26 of
    2219 walls «carry another mapping», over the one in a hundred allowed: not held - a fails); `--red-measure`
    the divergence lattice capped at 8388608 cells (the base cannot be measured, every edit of the run is
    REJECTED_UNMEASURED: g fails); `--red-starts` the starts grow away from their floors (46.6 over them, «over
    no floor»: d fails).

RED: `--red` builds the warp with the old split rule (a cut must cross a brush by 2 to split it) - 1 fails.

    python tools/check_mapgen_warp.py [--work DIR] [--red] [--red18] [--red-solid] [--red-drops] [--red-rooms]
                                      [--red-ramps] [--red-flight] [--red-flat] [--red-mapping] [--red-measure]
                                      [--red-starts] [--tall] [--keep]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_equivalence import PIPELINE_SOURCES, build  # noqa: E402

ENGINE = Path(r"O:\Claude2\MapgenStudio\engine")
MODDIR = Path(r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen_warp_guard")
NO_WINDOW = 0x08000000
FAILED = 0


# mapgen_dig_probe: the trace and the map, nothing of the generator
PROBE_SOURCES = ["src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_bsp.c", "src/mapgen/mapgen_digest.c",
                 "src/shared/shared.c", "tools/mapgen_host_stubs.c"]


def check(what: str, ok: bool, detail: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def fields(line: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|\S+)', line)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--red18", action="store_true")
    ap.add_argument("--red-solid", action="store_true")
    ap.add_argument("--red-drops", action="store_true")
    ap.add_argument("--red-rooms", action="store_true")
    ap.add_argument("--red-ramps", action="store_true")
    ap.add_argument("--red-flight", action="store_true")
    ap.add_argument("--red-flat", action="store_true")
    ap.add_argument("--red-mapping", action="store_true")
    ap.add_argument("--red-measure", action="store_true")
    ap.add_argument("--red-starts", action="store_true")
    ap.add_argument("--tall", action="store_true", help="case 8 alone")
    a = ap.parse_args()
    seam = [f for f, on in (("--solid-places", a.red_solid), ("--warp-drops-grow", a.red_drops),
                            ("--rooms-cap-old", a.red_rooms), ("--ramps-by-leaf", a.red_ramps),
                            ("--keep-flat-brushes", a.red_flat), ("--mapping-raw", a.red_mapping),
                            ("--warp-starts-grow", a.red_starts)) if on]
    if seam or a.tall or a.red_flight or a.red_measure:
        # brief 18 D2: case 8 alone - as it is, or with one rule of 13.10 taken out (the first try only)
        a.work.mkdir(parents=True, exist_ok=True)
        exe = build(a.work, "pipeline.exe", PIPELINE_SOURCES, strict=False)
        tall_case(a, exe, seam)
        print("FAIL" if FAILED else "PASS")
        return 1 if FAILED else 0
    if a.red18:
        # brief 18 D2's RED: the heights kept - case 8 only
        a.work.mkdir(parents=True, exist_ok=True)
        text = (REPO / "src" / "mapgen" / "mapgen_warp.c").read_text(encoding="utf-8")
        rule = "static const bool g_warp_tall = true;"
        if not check("RED18: the rule is where it says", text.count(rule) == 1):
            return 1
        red = a.work / "mapgen_warp_red18.c"
        red.write_text(text.replace(rule, "static const bool g_warp_tall = false;"), encoding="utf-8")
        exe = build(a.work, "pipeline_red18.exe",
                    [str(red) if s == "src/mapgen/mapgen_warp.c" else s for s in PIPELINE_SOURCES], strict=False)
        tall_case(a, exe, ["--warp-tries", "1"])
        print("FAIL" if FAILED else "PASS")
        return 1 if FAILED else 0
    donor = ENGINE / "donors" / "q2dm1.bsp"
    if not donor.is_file():
        print(f"no donor at {donor}")
        return 2
    a.work.mkdir(parents=True, exist_ok=True)
    sources = list(PIPELINE_SOURCES)
    if a.red:
        text = (REPO / "src" / "mapgen" / "mapgen_warp.c").read_text(encoding="utf-8")
        old = re.sub(r"#define WARP_SPLIT_INSIDE [0-9.]+f", "#define WARP_SPLIT_INSIDE 2.0f", text)
        if old == text:
            print("RED: the split rule was not found")
            return 2
        red = a.work / "mapgen_warp_red.c"
        red.write_text(old, encoding="utf-8")
        sources = [str(red) if s == "src/mapgen/mapgen_warp.c" else s for s in sources]
    exe = build(a.work, "pipeline_red.exe" if a.red else "pipeline.exe", sources, strict=False)
    job = a.work / ("red" if a.red else "job")
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)
    args = [str(exe), str(ENGINE / "q2tool.exe"), str(donor), str(job), "q2mg", "4", "6686",
            "--moddir", str(MODDIR), "--memory", "4000", "--checkpoints", "0", "--plan-only",
            "--warp-size", "200", "--warp-shape", "60"]
    print(f"warping q2dm1 to 200 %, spread 60{' (RED: the old split rule)' if a.red else ''}", flush=True)
    subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=1800)
    progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace")
    tries = [fields(l) for l in progress.splitlines() if "stage=warp " in l]
    done = [fields(l) for l in progress.splitlines() if "stage=warp-done" in l]
    first = tries[0] if tries else {}
    check("the first warped map builds", first.get("built") == "1",
          first.get("why", "no try") if first.get("built") != "1" else f"area {first.get('area')}")
    # brief 18 D2: a try may grow less tall (q2dm1's rocket-jump pedestals at x1.41) - the frame itself, its parts,
    # is not given back
    walked = next((t for t in tries if t.get("playable") == "1"), {})
    check("it walks without giving the frame back: every start reaches the others, no pickup out of reach - at most "
          "the heights grown less",
          walked.get("playable") == "1" and walked.get("pickups_out") == "0" and walked.get("stranded") == "0"
          and int(walked.get("pickups", "0")) > 0 and walked.get("parts", "").split(" area")[0]
          == first.get("parts", "").split(" area")[0],
          f"places {walked.get('places')}, pickups {walked.get('pickups')} ({walked.get('pickups_out')} out), "
          f"starts {walked.get('starts')} ({walked.get('stranded')} stranded); try {tries.index(walked) if walked else '-'}")
    parts = [float(v) for axis in re.findall(r"[xy]=([0-9.,]+)", first.get("parts", "")) for v in axis.split(",") if v]
    area = int(first.get("area", "0"))
    check("it is what was asked: area within 2 % of 200 %, parts unequal (largest at least 1.5 x the smallest)",
          abs(area - 2000) <= 40 and parts and max(parts) >= 1.5 * min(parts),
          f"area {area / 10:.1f} %, factors {min(parts) if parts else 0:.2f}..{max(parts) if parts else 0:.2f}")
    words = [fields(l) for l in progress.splitlines() if "stage=plan-value" in l]
    check("the plan is dealt on the warped base and says its word", bool(done) and bool(words),
          f"warp done {bool(done)}, plan word {words[0].get('can') if words else '-'}")
    if not a.red:
        run = Path(__file__).resolve().parent / "fixtures" / "mapgen_runs" / "mg_10_6695_q2dm3"
        launch = [l for l in (run / "launches.txt").read_text(encoding="utf-8").splitlines() if "pipeline.exe" in l]
        options = launch[-1].split(" --digs ", 1)[1].split(" --memory ")[0].split() if launch else []
        job3 = a.work / "job_q2dm3"
        shutil.rmtree(job3, ignore_errors=True)
        job3.mkdir(parents=True)
        print("dealing q2dm3's plan at the PO's options on the default frame (150 %, 50)", flush=True)
        subprocess.run([str(exe), str(ENGINE / "q2tool.exe"), str(ENGINE / "donors" / "q2dm3.bsp"), str(job3), "q2mg",
                        "10", "6695", "--moddir", str(MODDIR), "--memory", "4000", "--checkpoints", "0", "--plan-only",
                        "--digs"] + options + ["--warp-size", "150", "--warp-shape", "50"],
                       capture_output=True, text=True, creationflags=NO_WINDOW, timeout=1800)
        p3 = (job3 / "progress.txt").read_text(encoding="utf-8", errors="replace")
        w3 = [fields(l) for l in p3.splitlines() if "stage=plan-value" in l]
        large, can = (int(w3[0].get("large", "0")), int(w3[0].get("can", "0"))) if w3 else (0, 0)
        check("q2dm3 at the PO's options, default frame: at least 4 large edits proved, the word at least 45 %",
              large >= 4 and can >= 450, f"{large} large edits proved, the plan says up to {can / 10:.1f} %")
        if not a.keep:
            shutil.rmtree(job3, ignore_errors=True)
        # 6: the turn and the ceilings - q2dm3 turned by 90 degrees on the default frame, its three trains' paths
        # moved with their turned boxes (unmoved, they swept into the walls: «3 machines nothing can operate»), and
        # mirrored with its ceilings 30 % higher; 7: the shift - q2dm1's parts slid sideways (60 %) on the default
        # frame, its cuts placed off the walls' ends (a 5-unit slanted wedge came back from the rebuild a hundredth off
        # and the rebuilt base leaked, 10.10). Each held on its first try and accepted as the base.
        for donor, label, extra, want in (
                ("q2dm3", "turned 90", ["--warp-size", "150", "--warp-shape", "50", "--warp-turn", "1"],
                 "turn=90 mirror=0"),
                ("q2dm3", "mirrored, ceilings 130 %", ["--warp-turn", "4", "--warp-height", "130"],
                 "mirror=1 height=130"),
                ("q2dm1", "parts shifted 60 %", ["--warp-size", "150", "--warp-shape", "50", "--warp-shift", "60"],
                 "shift=60")):
            job4 = a.work / "job_turn"
            shutil.rmtree(job4, ignore_errors=True)
            job4.mkdir(parents=True)
            print(f"{donor} {label}", flush=True)
            subprocess.run([str(exe), str(ENGINE / "q2tool.exe"), str(ENGINE / "donors" / f"{donor}.bsp"), str(job4),
                            "q2mg", "10", "6695" if donor == "q2dm3" else "42", "--moddir", str(MODDIR), "--memory",
                            "4000", "--checkpoints", "0", "--plan-only"] + extra, capture_output=True, text=True,
                           creationflags=NO_WINDOW, timeout=1800)
            p4 = (job4 / "progress.txt").read_text(encoding="utf-8", errors="replace")
            tries4 = [fields(l) for l in p4.splitlines() if "stage=warp " in l]
            done4 = [fields(l) for l in p4.splitlines() if "stage=warp-done" in l]
            # a try walks with the frame asked (brief 18: at most the heights grown less), and what was accepted is what
            # was asked (the ceilings are the same attempt's second build, on the turned map); no fallback to the donor
            held = (any(t.get("playable") == "1" and t.get("parts", "").split(" area")[0]
                        == tries4[0].get("parts", "").split(" area")[0] for t in tries4) and bool(done4)
                    and want in done4[0].get("parts", "") and "stage=warp-kept" not in p4)
            check(f"{donor} {label}: held with the frame asked and accepted as the base",
                  held and "baseline-refused" not in p4 and "stage=plan-value" in p4,
                  f"accepted {done4[0].get('parts', '-') if done4 else '-'}; first try playable "
                  f"{tries4[0].get('playable', '-') if tries4 else '-'} {tries4[0].get('why', '') if tries4 else ''}")
            if not a.keep:
                shutil.rmtree(job4, ignore_errors=True)
        tall_case(a, exe)
    if not a.keep:
        shutil.rmtree(job, ignore_errors=True)
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


def z_extent(bsp: Path) -> float:
    """The world model's height (model 0's bounds)."""
    import struct
    d = bsp.read_bytes()
    off, _ = struct.unpack_from("<ii", d, 8 + 8 * 13)
    lo, hi = struct.unpack_from("<3f", d, off), struct.unpack_from("<3f", d, off + 12)
    return hi[2] - lo[2]


FLIGHTS = (("the flight at 824 736 (16-unit risers)", (824, 736, 128), (836, 1008, 256)),
           ("the flight at -528 128 (8-unit risers)", (-528, 128, 0), (-772, 124, 64)))


def through(pairs: list, v: float) -> float:
    """A donor coordinate through one axis of the warp's map (`stage=warp-map`: at:to pairs)."""
    i = 0
    while i + 2 < len(pairs) and v >= pairs[i + 1][0]:
        i += 1
    (a0, t0), (a1, t1) = pairs[i], pairs[i + 1]
    return t0 + (v - a0) * (t1 - t0) / (a1 - a0)


def tall_case(a, exe: Path, extra: list | None = None) -> None:
    extra = list(extra or [])
    red = bool(extra)
    job = a.work / "job_tall"
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)
    print("q3t2 at the PO's own frame (1000 / 100 / 100, ceilings 200)" + (f" RED {' '.join(extra)}" if red else ""),
          flush=True)
    subprocess.run([str(exe), str(ENGINE / "q2tool.exe"), str(ENGINE / "donors" / "q3t2.bsp"), str(job), "q2mg", "10",
                    "6695", "--moddir", str(MODDIR), "--memory", "6000", "--checkpoints", "0", "--warp-only",
                    "--warp-size", "1000", "--warp-shape", "100", "--warp-shift", "100", "--warp-height", "200"]
                   + extra + (["--warp-tries", "1"] if red and "--warp-tries" not in extra else []),
                   capture_output=True, text=True, creationflags=NO_WINDOW, timeout=7200)
    p = (job / "progress.txt").read_text(encoding="utf-8", errors="replace")
    tries = [fields(l) for l in p.splitlines() if "stage=warp " in l]
    ramps = [fields(l) for l in p.splitlines() if "stage=warp-ramps" in l]
    maps = [l for l in p.splitlines() if "stage=warp-map" in l]
    base = job / "warped_base.bsp"
    first = tries[0] if tries else {}
    area = int(first.get("area", "0")) / 1000.0
    want = area ** 0.5
    tall0 = float(ramps[0].get("tall", "0")) if ramps else 0.0
    check("8a q3t2 at 1000 %: the first try stands as tall as it grew wide (sqrt of its area, 5 %) and walks",
          bool(tries) and abs(tall0 - want) <= 0.05 * want and first.get("playable") == "1"
          and first.get("pickups_out") == "0" and first.get("stranded") == "0"
          and all(t.get("try") == "0" for t in tries) and "stage=warp-held" in p,
          f"area x{area:.2f}, heights x{tall0:.2f} for x{want:.2f}; the first try playable {first.get('playable', '-')} "
          f"{first.get('why', '')}; tries {len(tries)}; "
          + ("held by its rebuild" if "stage=warp-held" in p
             else next((l.split("why=", 1)[1][:260] for l in p.splitlines() if "stage=warp-kept" in l), "not held")))
    grown = z_extent(base) / z_extent(ENGINE / "donors" / "q3t2.bsp") if base.is_file() else 0.0
    done = [fields(l) for l in p.splitlines() if "stage=warp-done" in l]
    given = re.search(r"height=(\d+)", done[0].get("parts", "")) if done else None
    check("8b the accepted base is that tall at least, its ceilings over it as far as the world holds",
          bool(done) and grown >= 0.95 * want and given is not None and 100 <= int(given.group(1)) <= 200,
          f"height x{grown:.2f}; ceilings {given.group(1) if given else '-'} % of the 200 asked")
    walked = []
    probe = build(a.work, "dig_probe.exe", ["tools/mapgen_dig_probe.c"] + PROBE_SOURCES, strict=False) \
        if base.is_file() and maps else None
    if probe:
        line = maps[-1]
        ax = {k: [tuple(float(v) for v in pr.split(":")) for pr in re.search(k + r'="([^"]*)"', line).group(1).split(",")]
              for k in ("x", "y", "z")}
        for name, lo, hi in FLIGHTS:
            ends = [through(ax["x"], lo[0]), through(ax["y"], lo[1]), through(ax["z"], lo[2]) + 40.0,
                    through(ax["x"], hi[0]), through(ax["y"], hi[1]), through(ax["z"], hi[2]) + 40.0]
            r = subprocess.run([str(probe), str(base), "--walk", *[f"{v:.0f}" for v in ends], "--step", "4"],
                               capture_output=True, text=True, creationflags=NO_WINDOW)
            said = next((l for l in r.stdout.splitlines() if l.startswith("walk ")), "")
            m = re.search(r"walk (\d+) samples: (\d+) with ground, (\d+) missing, (\d+) too steep, (\d+) with 128 of "
                          r"headroom; worst rise (\d+)", said)
            walked.append((name, m is not None and m.group(1) == m.group(2) == m.group(5) and m.group(3) == "0"
                           and m.group(4) == "0" and int(m.group(6)) <= 18, said[5:]))
    check("8c two of q3t2's flights walk in it: every sample 18 of rise at the most, 128 of headroom",
          len(walked) == len(FLIGHTS) and all(ok for _, ok, _ in walked),
          "; ".join(f"{n}: {s}" for n, _, s in walked) or "no base to walk")
    # ... and every start: the delivery gate's own question of the base (a floor within 32 of a player's feet)
    stood = (False, "no base")
    if base.is_file():
        import mapgen_delivery_gates as gates
        stood = gates.ask_starts(base)
    check("8d every pickup and every start was put as high over its floor as it stood in the donor",
          bool(ramps) and int(ramps[0].get("drops", "0")) >= 50 and any(int(r.get("ramps", "0")) > 0 for r in ramps)
          and stood[0],
          f"pickups and starts put {ramps[0].get('drops', '-') if ramps else '-'}, ramps and steps laid "
          f"{ramps[0].get('ramps', '-') if ramps else '-'}; the base's starts: {stood[1][:160]}")
    if not red:
        import check_mapgen_reach_gate as gate
        walker = build(a.work, "reach_path.exe", ["tools/mapgen_reach_path.c"]
                       + [s for s in gate.SOURCES if not s.endswith("mapgen_reach_gate.c")], strict=False)

        def pads(bsp: Path) -> tuple[list[float], str]:
            r = subprocess.run([str(walker), str(bsp), "0", "--pushes", "--drops", "250"]
                               + (["--short-flight"] if a.red_flight else []), capture_output=True,
                               text=True, creationflags=NO_WINDOW, timeout=3600)
            return ([float(v) for v in re.findall(r"^push \d+ at [^:]*: up (-?\d+)", r.stdout, re.M)],
                    next((l for l in r.stdout.splitlines() if l.startswith("drops over")), ""))

        theirs, fell0 = pads(ENGINE / "donors" / "q3t2.bsp")
        mine, fell1 = pads(base) if base.is_file() else ([], "")
        check("8e every push pad throws a player as high as in the donor times the heights' factor (10 %)",
              len(theirs) >= 3 and len(mine) == len(theirs)
              and all(abs(m - t * tall0) <= 0.1 * t * tall0 for m, t in zip(mine, theirs)),
              "; ".join(f"{t:.0f} -> {m:.0f}" for m, t in zip(mine, theirs)) + f" | the donor: {fell0}; the base: {fell1}")
        # g: the base can be MEASURED - the divergence oracle's lattice holds it (the run's every edit is held to it)
        import check_mapgen_divergence_oracle as oracle
        meter = build(a.work, "divergence_gate.exe", oracle.GATE_SRC, strict=False)
        r = subprocess.run([str(meter), str(base), str(base), "100"] + (["--cap-old"] if a.red_measure else []),
                           capture_output=True, text=True, creationflags=NO_WINDOW, timeout=3600) \
            if base.is_file() else None
        said = (r.stdout.strip().splitlines() or [""])[0] if r else "no base"
        check("8g the base can be measured: the divergence lattice holds a map this size (itself against itself: none)",
              r is not None and r.returncode == 0 and "ERR_" not in r.stdout and "permille" in r.stdout,
              " | ".join(l.strip() for l in (r.stdout.splitlines() if r else [said])[:4])[:220])
        # f: the parts equal - proportions kept on all three axes
        job0 = a.work / "job_tall_even"
        shutil.rmtree(job0, ignore_errors=True)
        job0.mkdir(parents=True)
        subprocess.run([str(exe), str(ENGINE / "q2tool.exe"), str(ENGINE / "donors" / "q3t2.bsp"), str(job0), "q2mg", "10",
                        "6695", "--moddir", str(MODDIR), "--memory", "6000", "--checkpoints", "0", "--warp-only",
                        "--warp-tries", "1", "--warp-size", "1000", "--warp-shape", "0"],
                       capture_output=True, text=True, creationflags=NO_WINDOW, timeout=7200)
        p0 = (job0 / "progress.txt").read_text(encoding="utf-8", errors="replace")
        t0 = [fields(l) for l in p0.splitlines() if "stage=warp " in l]
        r0 = [fields(l) for l in p0.splitlines() if "stage=warp-ramps" in l]
        parts = re.search(r"x=([\d.,]+) y=([\d.,]+)", t0[0].get("parts", "")) if t0 else None
        ks = [float(v) for g in parts.groups() for v in g.split(",")] if parts else []
        kz = float(r0[0].get("tall", "0")) if r0 else 0.0
        check("8f the parts equal: every X and Y factor within 10 % of the others', the heights' within 5 % - and it walks",
              bool(ks) and max(ks) <= 1.1 * min(ks) and abs(kz - sum(ks) / len(ks)) <= 0.05 * kz
              and t0[0].get("playable") == "1",
              f"X and Y x{min(ks) if ks else 0:.2f}..x{max(ks) if ks else 0:.2f}, heights x{kz:.2f}; playable "
              f"{t0[0].get('playable', '-') if t0 else '-'} {t0[0].get('why', '') if t0 else ''}")
        if not a.keep:
            shutil.rmtree(job0, ignore_errors=True)
    if not a.keep:
        shutil.rmtree(job, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
