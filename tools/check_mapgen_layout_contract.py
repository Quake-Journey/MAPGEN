#!/usr/bin/env python3
"""MAPGEN-1 M4 - placing the graph in space.

Contract section 16, stage 6. The topology graph becomes rooms and the
passages between them, on a 16-unit integer grid, inside Quake II's world.

Two halves:

  * STATIC - the properties that hold by construction. Integers only, so
    contract 10's "the same recipe makes the same source.map" has no rounding
    to get wrong; passages routed along cell-boundary lanes, so a passage
    cannot breach a room it does not connect; and the brush stream, so nothing
    another stage draws can move the geometry;

  * BEHAVIOUR - the compiled module against a layout built from a real model.
    Every geometric claim is re-measured in the driver from the boxes
    themselves: rooms disjoint and on the grid, passages reaching both ends
    and admitting a standing player, and the junction count checked against a
    crossing count computed independently.

Run: python tools/check_mapgen_layout_contract.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_build_target as build_target  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

HEADER = REPO / "inc" / "common" / "mapgen_layout.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_layout.c"
DRIVER = REPO / "tools" / "mapgen_layout_test_driver.c"
PARTS = [
    REPO / "src" / "mapgen" / "mapgen_topology.c",
    REPO / "src" / "mapgen" / "mapgen_recipe.c",
    REPO / "src" / "mapgen" / "mapgen_mix.c",
    REPO / "src" / "mapgen" / "mapgen_random.c",
    REPO / "src" / "mapgen" / "mapgen_lineage.c",
    REPO / "src" / "mapgen" / "mapgen_training.c",
    REPO / "src" / "mapgen" / "mapgen_snapshot.c",
    REPO / "src" / "mapgen" / "mapgen_digest.c",
    REPO / "src" / "mapgen" / "mapgen_features.c",
    REPO / "src" / "mapgen" / "mapgen_wiring.c",
    REPO / "src" / "mapgen" / "mapgen_space.c",
    REPO / "src" / "mapgen" / "mapgen_trace.c",
    REPO / "src" / "mapgen" / "mapgen_genome.c",
    REPO / "src" / "mapgen" / "mapgen_bsp.c",
    REPO / "src" / "mapgen" / "mapgen_geometry.c",
    REPO / "src" / "mapgen" / "mapgen_blueprint.c",
]

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
]
MAPS = ["2box4.bsp", "rcdm17.bsp", "lbrdm1.bsp"]

CASES = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if condition:
        print(f"  PASS  {name}")
        return True
    print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    FAILED += 1
    return False


def head(text: str) -> None:
    print(f"\n=== {text}")


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


# --------------------------------------------------------------------------


def test_static() -> None:
    head("static: integers on a grid, and lanes no room can reach")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))
    hdr_prose = HEADER.read_text(encoding="utf-8")

    check(
        "there is no floating point anywhere in it",
        not re.search(r"\b(float|double)\b", src),
        "contract 10 wants the same source.map on every machine, and the "
        "surest way is to have no rounding to get wrong",
    )
    check(
        "and no clock and no libc generator",
        not re.search(r"\b(time|clock|rand|srand)\s*\(", src),
        "",
    )
    check(
        "every coordinate is snapped to the grid",
        "static int32_t snap(int32_t v)" in src
        and "MAPGEN_LAYOUT_GRID" in src,
        "",
    )
    check(
        "and the snap works the same on both sides of the origin",
        "(v - g + 1) / g" in src,
        "truncation toward zero would make the grid coarser for negatives",
    )
    check(
        "the geometry stream is the brush stream",
        "MAPGEN_RANDOM_BRUSHES" in src and src.count("MapGenRandom_Stream") == 1,
        "another stage's draws must not move the rooms",
    )
    check(
        "and the attempt index selects it",
        "MapGenRecipe_Seed(recipe), attempt" in src,
        "",
    )

    # --- the lane argument -------------------------------------------------
    check(
        "a cell is wider than the largest room by more than a corridor",
        int(re.search(r"MAPGEN_LAYOUT_CELL\s+(\d+)", hdr).group(1))
        - int(re.search(r"MAPGEN_LAYOUT_MAX_ROOM\s+(\d+)", hdr).group(1))
        > int(re.search(r"MAPGEN_LAYOUT_CORRIDOR_WIDTH\s+(\d+)", hdr).group(1)),
        "that gap is what makes the boundary lane clear of every room",
    )
    check(
        "passages are routed on cell boundaries",
        "MAPGEN_LAYOUT_CELL / 2" in src and "lane_y" in src and "lane_x" in src,
        "",
    )
    check(
        "a passage breaching an unrelated room is still refused",
        "boxes_overlap(&l->passages[p].segments[s], &l->rooms[i].space)" in src
        and "MAPGEN_LAYOUT_ERR_INTERSECTION" in src,
        "the COMPARISON, not just the error constant beside it: a mutation "
        "that guts the test leaves the constant sitting there",
    )
    check(
        "and a crossing between two passages is counted, not refused",
        "l->num_junctions++" in src,
        "a junction adds walk adjacency and describes what real maps do",
    )
    check(
        "the header says why that distinction is drawn",
        "A crossing is a junction; a hole in a wall is not" in hdr_prose,
        "",
    )
    check(
        "the junction count is reported rather than left implied",
        "MapGenLayout_NumJunctions" in hdr and "junctions=" in src,
        "",
    )

    # --- refusals -----------------------------------------------------------
    build = src[src.find("mapgen_layout_result_t MapGenLayout_Build"):]
    check(
        "the out-parameter is cleared before anything can fail",
        build.find("*out = NULL") >= 0
        and build.find("*out = NULL") < build.find("MAPGEN_LAYOUT_ERR_ARGS"),
        "a refused build must not leave a stale layout in the caller's hands",
    )
    check(
        "everything is checked against the world limit",
        "inside_world" in src and "MAPGEN_LAYOUT_WORLD_LIMIT" in src,
        "",
    )
    check(
        "the sizes come from the engine's own hull",
        "MAPGEN_LAYOUT_HULL_WIDTH      32" in hdr
        and "MAPGEN_LAYOUT_HULL_HEIGHT     56" in hdr,
        "a corridor narrower than the hull is not a corridor",
    )
    check(
        "the topology is const to it",
        "mapgen_topology_t *topology" not in
        src.replace("const mapgen_topology_t *topology", ""),
        "",
    )
    check(
        "and so is the recipe",
        "mapgen_recipe_t *recipe" not in
        src.replace("const mapgen_recipe_t *recipe", ""),
        "",
    )
    # The rule protects the PO's binary, not the generator: a module
    # the packaged helper runs has to be linked somewhere, and
    # mapgen_src is the somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_layout.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("layout.exe" if os.name == "nt" else "layout")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), *[str(x) for x in PARTS], "-o", str(exe), "-lz"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def find_map(name: str) -> Path | None:
    for root in MAP_ROOTS:
        if (root / name).exists():
            return root / name
    return None


def test_behaviour(exe: Path) -> None:
    head("behaviour: the boxes measured, not the promise asked for")
    paths = [find_map(n) for n in MAPS]
    paths = [p for p in paths if p]
    if not check("the maps are available", len(paths) == len(MAPS),
                 f"{len(paths)} of {len(MAPS)}"):
        return

    try:
        p = subprocess.run([str(exe), "run", *[str(x) for x in paths]],
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        check("the behavioural suite reported a result", False, "timed out")
        return
    for line in p.stdout.splitlines():
        if line.startswith(("  PASS", "  FAIL")):
            print(line)
    m = re.search(r"=== (\d+) cases asserted, (\d+) failures", p.stdout)
    if not check("the behavioural suite reported a result", m is not None,
                 (p.stdout + p.stderr)[-600:]):
        return
    assert m is not None
    global CASES, FAILED
    CASES += int(m.group(1))
    FAILED += int(m.group(2))


def main() -> int:
    print("=== MAPGEN-1 M4 layout contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_layout_") as td:
        head("building")
        exe = build(cc, Path(td))
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_behaviour(exe)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
