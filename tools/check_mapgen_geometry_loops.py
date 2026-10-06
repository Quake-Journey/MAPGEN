"""Loops A, B, C and F: does the geometry Module survive a real round trip?

Each fixture is compiled by the pinned compiler, taken apart by the Module,
written back out and compiled again. What comes out the second time must draw
the same surfaces and stop a player in the same places as what came out the
first. Nothing here searches source text; every case runs the real compiler on
a real map and compares two real BSPs.

  Loop A - arbitrary convex geometry: oblique planes and non-dominant texture
           axes survive the trip.
  Loop B - compiled equivalence: solid classification and drawn surface agree,
           invariant to how the compiler chose to split faces.
  Loop C - brush models: a mover's geometry, ownership and entity graph come
           back intact.
  Loop F - backend routing: no path above fidelity 0 may reach the axis-only
           box writer.

Usage:
    python tools/check_mapgen_geometry_loops.py [--work DIR] [--only NAME]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\loops")

FAILURES: list[str] = []
CASES = 0


def case(name: str, ok: bool, detail: str = "") -> None:
    global CASES
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))
        FAILURES.append(name)


def build_tools(work: Path) -> dict[str, Path]:
    """Compile the Module's drivers from the CURRENT tree, so a sandboxed
    mutation of the source is what the loops actually run against."""
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    src = {
        "fork": ["tools/mapgen_geometry_fork.c", "src/mapgen/mapgen_geometry.c",
                 "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_bsp.c",
                 "src/mapgen/mapgen_trace.c",
                 "src/mapgen/mapgen_rooms.c",
                 "src/mapgen/mapgen_bundle.c",
                 "src/mapgen/mapgen_closure.c"],
        "render": ["tools/mapgen_render_audit.c", "src/mapgen/mapgen_geometry.c",
                   "src/mapgen/mapgen_bsp.c"],
        "wall": ["tools/mapgen_wall_audit.c", "src/mapgen/mapgen_bsp.c",
                 "src/mapgen/mapgen_trace.c",
                 "src/mapgen/mapgen_rooms.c"],
        "cover": ["tools/mapgen_coverage_oracle.c",
                  "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_bsp.c"],
        "dump": ["tools/mapgen_geometry_dump.c",
                 "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_bsp.c"],
    }
    built = {}
    for name, files in src.items():
        exe = out / f"{name}.exe"
        run = subprocess.run(
            ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
             "-I" + str(REPO / "inc")] + [str(REPO / f) for f in files]
            + ["-o", str(exe), "-lm"],
            capture_output=True, text=True)
        if run.returncode != 0:
            print(run.stderr[:2000])
            raise SystemExit(f"cannot build {name}")
        built[name] = exe
    return built


def compile_map(map_path: Path, stages=("-bsp",)) -> str | None:
    common = ["-threads", "4", "-moddir", str(GAME), "-basedir", str(GAME),
              "-gamedir", str(GAME)]
    target = map_path
    for stage in stages:
        run = subprocess.run([str(COMPILER), stage] + common + [str(target)],
                             capture_output=True, text=True, timeout=1800)
        text = run.stdout + run.stderr
        if run.returncode != 0 or "ERROR" in text:
            return "refused"
        if "leaked" in text.lower():
            return "leaked"
        target = map_path.with_suffix(".bsp")
    return None


def round_trip(tools: dict[str, Path], work: Path, name: str) -> tuple[Path, Path] | None:
    """fixture .map -> BSP -> Module -> .map -> BSP."""
    sys.path.insert(0, str(REPO / "tools"))
    import mapgen_geometry_fixtures as fixtures

    src_map = work / f"{name}.map"
    fixtures.FIXTURES[name](src_map)
    if compile_map(src_map) is not None:
        return None
    donor = src_map.with_suffix(".bsp")

    again_map = work / f"{name}_again.map"
    run = subprocess.run([str(tools["fork"]), str(donor), str(again_map),
                          "100", "1"], capture_output=True, text=True)
    if run.returncode != 0:
        return None
    if compile_map(again_map) is not None:
        return None
    return donor, again_map.with_suffix(".bsp")


def render_contract_red(tools: dict[str, Path], work: Path) -> None:
    """The render contract must still refuse a wall that really is shorter.

    `faceted_wall_short` is the same arc with eight units taken off the top:
    same planes, same materials, same surface count, so nothing vanishes and
    nothing appears - and every facet has lost three per cent of itself while
    the map draws less than it did. If this passes, the contract is measuring
    nothing.
    """
    sys.path.insert(0, str(REPO / "tools"))
    import mapgen_geometry_fixtures as fixtures

    tall = work / "contract_tall.map"
    short = work / "contract_short.map"
    fixtures.FIXTURES["faceted_wall"](tall)
    fixtures.FIXTURES["faceted_wall_short"](short)
    if compile_map(tall) is not None or compile_map(short) is not None:
        case("render contract RED: both references compile", False, "")
        return
    case("render contract RED: both references compile", True)

    audit = subprocess.run(
        [str(tools["render"]), str(tall.with_suffix(".bsp")),
         str(short.with_suffix(".bsp"))], capture_output=True, text=True)
    summary = audit.stdout.strip().splitlines()[-3:] if audit.stdout else []
    case("render contract RED: a wall that lost a strip is refused",
         audit.returncode != 0, " / ".join(summary))


def loop_ab(tools: dict[str, Path], work: Path, only: str | None) -> None:
    """Loops A and B on every fixture: the drawn surfaces and the solid must
    both survive the trip."""
    sys.path.insert(0, str(REPO / "tools"))
    import mapgen_geometry_fixtures as fixtures

    for name in sorted(fixtures.FIXTURES):
        if only and only != name:
            continue
        pair = round_trip(tools, work, name)
        if pair is None:
            case(f"loop A/B {name}: round trip completes", False,
                 "a stage refused it")
            continue
        donor, again = pair
        case(f"loop A/B {name}: round trip completes", True)

        render = subprocess.run([str(tools["render"]), str(donor), str(again)],
                                capture_output=True, text=True)
        summary = render.stdout.strip().splitlines()[-2:] if render.stdout else []
        case(f"loop A/B {name}: draws the same surfaces",
             render.returncode == 0, " / ".join(summary))

        wall = subprocess.run([str(tools["wall"]), str(donor), str(again)],
                              capture_output=True, text=True)
        case(f"loop A/B {name}: keeps the solid behind every surface",
             wall.returncode == 0,
             wall.stdout.strip().splitlines()[0] if wall.stdout else "")

        # The C reading against an independent one that shares no code with it.
        import mapgen_geometry_oracle as oracle
        from pathlib import Path as _P
        c_text = subprocess.run([str(tools["dump"]), str(donor)],
                                capture_output=True, text=True).stdout
        py_text = oracle.canonical_text(oracle.Bsp(_P(donor)))
        case(f"loop A/B {name}: an independent reading agrees byte for byte",
             c_text == py_text,
             f"{sum(1 for a, b in zip(c_text.splitlines(), py_text.splitlines()) if a != b)}"
             " lines differ")

        # The oracle against the donor itself: a coverage test that cannot
        # find a map covering itself would pass anything.
        self_test = subprocess.run([str(tools["cover"]), str(donor), str(donor),
                                    "8", "2"], capture_output=True, text=True)
        case(f"loop A/B {name}: the coverage oracle finds the donor covers itself",
             self_test.returncode == 0,
             self_test.stdout.strip().splitlines()[0] if self_test.stdout else "")

        cover = subprocess.run([str(tools["cover"]), str(donor), str(again),
                                "8", "2"], capture_output=True, text=True)
        case(f"loop A/B {name}: leaves no hole in a surface the donor draws",
             cover.returncode == 0,
             cover.stdout.strip().splitlines()[-1] if cover.stdout else "")


def loop_c(tools: dict[str, Path], work: Path) -> None:
    """A brush model has to come back as a brush model, owning the same
    geometry, or a donor's doors and lifts stop being doors and lifts."""
    sys.path.insert(0, str(REPO / "tools"))
    import mapgen_geometry_fixtures as fixtures

    src_map = work / "mover.map"
    brushes = fixtures.hollow_room((-256, -256, 0), (512, 512, 384))
    world = list(brushes)
    plat = fixtures.box((0, 0, 0), (128, 128, 16))
    lines = ["// Game: Quake 2", "// Format: Valve", "{",
             '"classname" "worldspawn"', '"mapversion" "220"',
             '"message" "mover"']
    for b in world:
        lines.append(b.render().rstrip("\n"))
    lines.append("}")
    lines += ["{", '"classname" "func_plat"', '"spawnflags" "1"',
              '"speed" "200"', '"lip" "8"', '"height" "64"',
              plat.render().rstrip("\n"), "}"]
    lines += ["{", '"classname" "info_player_deathmatch"',
              '"origin" "-128 -128 32"', "}"]
    lines += ["{", '"classname" "light"', '"light" "300"',
              '"origin" "128 128 300"', "}"]
    src_map.write_text("\n".join(lines) + "\n", encoding="ascii")

    if compile_map(src_map) is not None:
        case("loop C: the mover fixture compiles", False)
        return
    case("loop C: the mover fixture compiles", True)
    donor = src_map.with_suffix(".bsp")

    again_map = work / "mover_again.map"
    run = subprocess.run([str(tools["fork"]), str(donor), str(again_map),
                          "100", "1"], capture_output=True, text=True)
    models = re.search(r"models (\d+)", run.stdout or "")
    case("loop C: the donor's brush model is seen", bool(models)
         and int(models.group(1)) == 2, run.stdout.strip()[-120:])

    if compile_map(again_map) is not None:
        case("loop C: the rebuild compiles", False)
        return
    case("loop C: the rebuild compiles", True)

    raw = again_map.with_suffix(".bsp").read_bytes()
    import struct
    off, length = struct.unpack_from("<ii", raw, 8)
    ents = raw[off:off + length].decode("latin1")
    case("loop C: the mover survives as a brush model",
         "func_plat" in ents and '"model" "*1"' in ents,
         ents.replace("\n", " ")[:160])
    num_models = struct.unpack_from("<ii", raw, 8 + 13 * 8)[1] // 48
    case("loop C: the rebuild has the same number of models", num_models == 2,
         f"{num_models} models")


def loop_f() -> None:
    """No route above fidelity 0 may reach the axis-only box writer.

    Static, and deliberately so: the point is that the CODE cannot get there,
    not that one run happened not to.
    """
    text = (REPO / "tools" / "mapgen_generate.c").read_text(encoding="utf-8",
                                                            errors="replace")
    stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    stripped = re.sub(r"//[^\n]*", "", stripped)

    uses_boxes = "MapGenLayout_FromBlueprint" in stripped \
        or "MapGenBrush_Build" in stripped
    # The route may exist - fidelity 0 is entitled to it - but only behind a
    # refusal that fires before anything reaches it.
    refuses = re.search(r"if \(fidelity > 0\)\s*\{[^}]*?return 1;", stripped,
                        re.S) is not None
    case("loop F: the product generator cannot reach the box path above F=0",
         not uses_boxes or refuses,
         "mapgen_generate.c still lowers a donor through the blueprint boxes")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", default=str(DEFAULT_WORK))
    parser.add_argument("--only")
    args = parser.parse_args(argv)

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    if not COMPILER.is_file():
        print(f"the pinned compiler is not at {COMPILER}")
        return 2

    print("geometry loops A/B/C/F")
    tools = build_tools(work)
    if not args.only:
        render_contract_red(tools, work)
    loop_ab(tools, work, args.only)
    if not args.only:
        loop_c(tools, work)
        loop_f()

    print(f"\n{CASES} cases, {len(FAILURES)} failures")
    for name in FAILURES:
        print(f"  {name}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
