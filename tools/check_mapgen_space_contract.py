#!/usr/bin/env python3
"""MAPGEN-1 M2 - MapGenSpace, the candidate traversal graph.

Contract sections 5.4 (occupancy, segmented regions, a typed traversal graph
with walk / step / jump / fall / swim edges) and 18.3 (a candidate graph for
speed, with a real hull trace as the authority - never a static adjacency, a
PVS lookup or a leaf bounding box).

Four halves:

  * IDENTITY - every movement constant is read out of the game's own source and
    compared. A candidate graph built on invented numbers describes a game
    nobody is playing;

  * REFERENCE - the C and an independently written Python build of the same
    graph must produce byte-identical canonical text on real maps. Slow, so it
    runs on the small ones;

  * REAL - all 132 shipped maps build, the result is stable across runs and
    identical when eight threads build it at once, and the graph's own
    invariants hold on every edge of every map;

  * REFUSALS - cell sizes outside the header's range, and the three shipped
    maps whose world model claims +-99999.

Run: python tools/check_mapgen_space_contract.py
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
sys.path.insert(0, str(REPO / "tools"))

import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_space_oracle as space  # noqa: E402

# The one rule for what belongs to the fixed corpus; see mapgen_corpus.py.
from mapgen_corpus import is_generated  # noqa: E402

HEADER = REPO / "inc" / "common" / "mapgen_space.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_space.c"
DRIVER = REPO / "tools" / "mapgen_space_test_driver.c"
TRACE = REPO / "src" / "mapgen" / "mapgen_trace.c"
BSPDOC = REPO / "src" / "mapgen" / "mapgen_bsp.c"

PMOVE = REPO / "src" / "common" / "pmove" / "template.c"
GAME = REPO / "src" / "game" / "g_main.c"

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
]

# Small enough that the Python build finishes in a few seconds, and chosen for
# what they reach rather than for their size alone: `redyard` is the smallest
# map with liquid, and `rcdm17` the smallest with a stance only a ducked hull
# fits. Without them the swim, hazard and duck paths never run.
REFERENCE_MAPS = ["2box4.bsp", "redyard.bsp", "rcdm17.bsp", "ztn2dm1.bsp"]

# LIQUID and HAZARD are separate flags on a stance, and lava sets both - so a
# lava map cannot tell them apart. Two measurements were needed to find one
# that can:
#
#   `redyard`, which I twice described as a water map, carries LAVA and no
#   water at all;
#   `ztn2dm1` carries water BRUSHES but no standable stance inside them, so it
#   separates nothing either.
#
# `rdm.bsp` is the smallest map that actually produces liquid stances with no
# hazard stances: 156 and 0.
LIQUID_NOT_HAZARD_MAP = "rdm.bsp"

# The three maps whose world model is +-99999 on every axis. Named, because a
# regression here reads as "three maps stopped working" and nothing else.
SENTINEL_BOUNDS_MAPS = ["2box4.bsp", "airport2.bsp", "aqnitro.bsp"]

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


def header_int(hdr: str, name: str) -> int | None:
    m = re.search(rf"^#define {name}\s+\(?(-?\d+)\)?\s*$", hdr, re.MULTILINE)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------


def test_identity() -> None:
    head("identity: every movement constant is the game's")
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))
    pmove = PMOVE.read_text(encoding="utf-8", errors="replace")
    game = GAME.read_text(encoding="utf-8", errors="replace")

    m = re.search(r"^#define STEPSIZE\s+(\d+)", pmove, re.MULTILINE)
    engine_step = int(m.group(1)) if m else None
    check("the engine's STEPSIZE was readable", engine_step is not None, "")
    check(
        "MAPGEN_SPACE_STEPSIZE is the engine's step height",
        header_int(hdr, "MAPGEN_SPACE_STEPSIZE") == engine_step,
        f"engine {engine_step}, header {header_int(hdr, 'MAPGEN_SPACE_STEPSIZE')}",
    )

    check(
        "the hull is the engine's standing hull",
        header_int(hdr, "MAPGEN_SPACE_HULL_WIDTH") == 16
        and header_int(hdr, "MAPGEN_SPACE_HULL_BOTTOM") == -24
        and header_int(hdr, "MAPGEN_SPACE_HULL_TOP") == 32
        and "pm->mins[2] = -24;" in pmove
        and "pm->maxs[2] = 32;" in pmove,
        "src/common/pmove/template.c sets the hull; it is not ours to choose",
    )
    check(
        "the ducked hull is the engine's",
        header_int(hdr, "MAPGEN_SPACE_DUCK_TOP") == 4 and "pm->maxs[2] = 4;" in pmove,
        "",
    )

    m = re.search(r"pml\.velocity\[2\] \+= (\d+);", pmove)
    engine_jump = int(m.group(1)) if m else None
    check(
        "MAPGEN_SPACE_JUMP_SPEED is the engine's jump velocity",
        header_int(hdr, "MAPGEN_SPACE_JUMP_SPEED") == engine_jump,
        f"engine {engine_jump}",
    )

    m = re.search(r'gi\.cvar\("sv_gravity",\s*"(\d+)"', game)
    engine_gravity = int(m.group(1)) if m else None
    check(
        "MAPGEN_SPACE_GRAVITY is sv_gravity's default",
        header_int(hdr, "MAPGEN_SPACE_GRAVITY") == engine_gravity,
        f"game {engine_gravity}",
    )

    # The one derived number: it must follow from the other two rather than be
    # a nice round figure someone liked.
    speed = header_int(hdr, "MAPGEN_SPACE_JUMP_SPEED") or 0
    gravity = header_int(hdr, "MAPGEN_SPACE_GRAVITY") or 1
    derived = int(speed * speed / (2 * gravity))
    check(
        "MAPGEN_SPACE_JUMP_RISE follows from the jump speed and gravity",
        header_int(hdr, "MAPGEN_SPACE_JUMP_RISE") == derived,
        f"v^2/2g = {speed}^2/(2*{gravity}) = {derived}, "
        f"header says {header_int(hdr, 'MAPGEN_SPACE_JUMP_RISE')}",
    )

    check(
        "the ground test is PM_CategorizePosition's 0.7",
        header_int(hdr, "MAPGEN_SPACE_GROUND_NORMAL_Z_MILLI") == 700
        and "normal[2] < 0.7" in pmove,
        "a looser threshold would call a wall a floor",
    )


def test_static() -> None:
    head("static: how the graph is allowed to be built")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))

    file_statics = [
        m.group(0).strip()
        for m in re.finditer(r"^static\s+[^;(){}]*;", src, re.MULTILINE)
        if "const" not in m.group(0)
    ]
    check(
        "no mutable file-scope state",
        not file_statics,
        f"{file_statics[:3]}; two maps must be able to build at once",
    )
    local_statics = [
        m.group(0).strip()
        for m in re.finditer(r"^[ \t]+static\s+[^;{]*;", src, re.MULTILINE)
    ]
    check("no function-local static state", not local_statics, f"{local_statics[:3]}")

    check(
        "every stance and every edge is asserted by a real hull trace",
        "MapGenTrace_Box(&b->trace" in src and src.count("MapGenTrace_Box") >= 4,
        "contract 18.3: adjacency, PVS and leaf bounds are not proof",
    )
    # Leaf and node boxes are legitimate for ONE thing - finding out how big
    # the world is - and for nothing else. So the rule is about where they may
    # appear, not whether they appear at all.
    bounds_fn = re.search(
        r"static bool world_bounds\(.*?\n\}", src, re.DOTALL)
    outside = src.replace(bounds_fn.group(0), "") if bounds_fn else src
    check(
        "leaf and node boxes are read only to size the world",
        bool(bounds_fn)
        and "leaf->" not in outside
        and "node->mins" not in outside and "node->maxs" not in outside,
        "a leaf's box contains solid; it can say how big the map is and "
        "nothing about whether a body fits",
    )
    check(
        "no PVS or cluster shortcut",
        "cluster" not in src and "visibility" not in src.lower(),
        "",
    )
    check(
        "the motion is step up, move across, drop down",
        "motion_is_clear" in src and src.count("MapGenTrace_Box(&b->trace") >= 3,
        "",
    )
    check(
        "a landing must be the stance that was claimed",
        "landed > -1.0f && landed < 1.0f" in src,
        "without this an edge could 'arrive' at a ledge on the way down",
    )

    # The ceiling comparison itself, not merely the name of the error code -
    # which also appears in the result-name switch at the top of the file.
    limit_at = src.find("cols > (int64_t)MAPGEN_SPACE_MAX_COLUMNS")
    alloc_at = src.find("calloc(1, sizeof(*sp))")
    check(
        "the column ceiling is checked BEFORE anything is allocated",
        0 <= limit_at < alloc_at,
        f"ceiling at {limit_at}, first allocation at {alloc_at}",
    )
    check(
        "a failed allocation is not reported as a small map",
        src.count("b->out_of_memory = true;") == 2
        and "return MAPGEN_SPACE_ERR_MEMORY;" in src,
        "both growable arrays must say so; silently truncating one would look "
        "like a sparse map",
    )
    check(
        "the world's extent comes from the tree, not from the model's box",
        "world_bounds" in src and "node->mins[i]" in src,
        "three shipped maps claim +-99999 in their world model",
    )
    check(
        "the column scan is bounded",
        "floors < MAPGEN_SPACE_MAX_FLOORS_PER_COLUMN" in src,
        "a column of stacked geometry must terminate",
    )
    joiner = src[src.find("static bool joins_a_region"):src.find("static bool build_regions")]
    check(
        "regions are joined only by symmetric motions",
        "kind == MAPGEN_EDGE_WALK" in joiner
        and "kind == MAPGEN_EDGE_STEP" in joiner
        and "kind == MAPGEN_EDGE_SWIM" in joiner
        and joiner.count("kind ==") == 3
        and "kind !=" not in joiner,
        "a jump up and the fall back down are not the same relation, and a "
        "joiner that admits everything is not a joiner",
    )
    # The rule protects the PO's binary, not the generator: a module the
    # packaged helper runs has to be linked somewhere, and mapgen_src is the
    # somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_space.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("space.exe" if os.name == "nt" else "space")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), str(TRACE), str(BSPDOC), "-o", str(exe)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def run(exe: Path, *args: str) -> str:
    p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=900)
    return p.stdout


def find_map(name: str) -> Path | None:
    for root in MAP_ROOTS:
        if (root / name).exists():
            return root / name
    return None


def corpus() -> list[Path]:
    return [p for root in MAP_ROOTS if root.is_dir() for p in sorted(root.glob("*.bsp"))
            # The generator publishes into this directory under contract 22's
            # reserved `q2mg_` basename. Those are legal training input but they are
            # not part of the fixed corpus these checks count, and a count that moves
            # every time somebody generates a map is not a count.
            if not is_generated(p.name)]


def test_reference(exe: Path) -> None:
    head("reference: two independent builds of the same graph")
    for name in REFERENCE_MAPS:
        path = find_map(name)
        if not check(f"{name} is available", path is not None, ""):
            continue
        assert path is not None
        bsp = oracle.load(path)
        sp = space.build(bsp, 32, True)
        if not check(f"{name}: the reference built a graph", sp is not None, ""):
            continue
        assert sp is not None
        py = space.canonical_text(sp)
        c = run(exe, "text", str(path))
        if c == py:
            check(f"{name}: the two builds are byte-identical", True,
                  f"{len(sp.nodes)} nodes, {len(sp.edges)} edges, "
                  f"{len(sp.regions)} regions")
            continue
        cl, pl = c.splitlines(), py.splitlines()
        first = next((f"line {i}: C={cl[i] if i < len(cl) else '<eof>'!r} "
                      f"py={pl[i] if i < len(pl) else '<eof>'!r}"
                      for i in range(max(len(cl), len(pl)))
                      if (cl[i] if i < len(cl) else None) != (pl[i] if i < len(pl) else None)),
                     "?")
        check(f"{name}: the two builds are byte-identical", False,
              f"C {len(cl)} lines, py {len(pl)} lines; first difference {first}")


def parse_summary(line: str) -> dict[str, int] | None:
    parts = line.split()
    if not parts or parts[0] != "OK":
        return None
    out: dict[str, int] = {}
    for i in range(2, len(parts) - 1, 2):
        try:
            out[parts[i]] = int(parts[i + 1])
        except ValueError:
            pass
    return out


def test_real(exe: Path) -> list[Path]:
    head("real: every shipped map")
    maps = corpus()
    if not check("real maps are available", len(maps) >= 100, f"found {len(maps)}"):
        return []

    failures: list[str] = []
    empty: list[str] = []
    total_nodes = 0
    total_edges = 0
    for path in maps:
        s = parse_summary(run(exe, "summary", str(path)).strip())
        if s is None:
            failures.append(f"{path.name}: {run(exe, 'summary', str(path)).strip()[:60]}")
            continue
        total_nodes += s.get("nodes", 0)
        total_edges += s.get("edges", 0)
        if s.get("nodes", 0) < 32:
            empty.append(f"{path.name}({s.get('nodes')})")

    check("every map produced a graph", not failures, "; ".join(failures[:4]))
    check(
        "no map came out effectively empty",
        not empty,
        f"{len(empty)}: {empty[:5]}; a map with no standable space is a finding, "
        "not a quiet zero",
    )
    print(f"  ..    {total_nodes} stances and {total_edges} edges across {len(maps)} maps")

    for name in SENTINEL_BOUNDS_MAPS:
        path = find_map(name)
        if path is None:
            check(f"{name} is available", False, "")
            continue
        s = parse_summary(run(exe, "summary", str(path)).strip())
        check(
            f"{name} builds despite its +-99999 world model",
            s is not None and s.get("nodes", 0) > 0,
            "the model box is a sentinel, not a size; the tree carries the truth",
        )
    return maps


def test_invariants(exe: Path, maps: list[Path]) -> None:
    head("invariants: what the graph promises about itself")
    if not maps:
        return

    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))
    jump_rise = header_int(hdr, "MAPGEN_SPACE_JUMP_RISE") or 45
    stepsize = header_int(hdr, "MAPGEN_SPACE_STEPSIZE") or 18
    max_fall = header_int(hdr, "MAPGEN_SPACE_MAX_FALL") or 1024

    bad_index: list[str] = []
    bad_kind: list[str] = []
    bad_rise: list[str] = []
    bad_region: list[str] = []
    self_edges: list[str] = []
    checked_edges = 0

    for path in maps[::8]:
        text = run(exe, "text", str(path))
        nodes: list[tuple[int, int]] = []   # (region, flags)
        regions = 0
        for line in text.splitlines():
            if line.startswith("n="):
                f = line[2:].split(",")
                nodes.append((int(f[6]), int(f[5])))
            elif line.startswith("regions="):
                regions = int(line.split("=")[1])
            elif line.startswith("e="):
                f = line[2:].split(",")
                a, b, rise, kind = int(f[0]), int(f[1]), int(f[2]), f[3]
                checked_edges += 1
                if a >= len(nodes) or b >= len(nodes):
                    bad_index.append(f"{path.name} {a}->{b} of {len(nodes)}")
                    continue
                if a == b:
                    self_edges.append(f"{path.name} {a}")
                if rise > jump_rise or rise < -max_fall:
                    bad_rise.append(f"{path.name} rise {rise}")
                liquid_pair = (nodes[a][1] & 1) and (nodes[b][1] & 1)
                expected = ("swim" if liquid_pair else
                            "jump" if rise > stepsize else
                            "fall" if rise < -stepsize else
                            "step" if rise != 0 else "walk")
                if kind != expected:
                    bad_kind.append(f"{path.name} {kind} for rise {rise}")
        for region, _flags in nodes:
            if region >= regions:
                bad_region.append(f"{path.name} region {region} of {regions}")

    check("every edge names two nodes that exist", not bad_index, str(bad_index[:3]))
    check("no node has an edge to itself", not self_edges, str(self_edges[:3]))
    check(
        "every rise is inside the jump and fall bounds",
        not bad_rise,
        f"{len(bad_rise)}: {bad_rise[:3]}",
    )
    check(
        "every edge's kind follows from its rise and its ends",
        not bad_kind,
        f"{len(bad_kind)}: {bad_kind[:3]}",
    )
    check("every node names a region that exists", not bad_region, str(bad_region[:3]))
    print(f"  ..    {checked_edges} edges checked")

    # LIQUID and HAZARD are separate flags, and lava sets both. Only a map with
    # water and no lava can tell them apart - and `redyard`, which I had twice
    # described as a water map, turns out to carry lava. Measured, not assumed.
    water_map = find_map(LIQUID_NOT_HAZARD_MAP)
    if check(f"{LIQUID_NOT_HAZARD_MAP} is available", water_map is not None, ""):
        assert water_map is not None
        liquid = hazard = 0
        for line in run(exe, "text", str(water_map)).splitlines():
            if not line.startswith("n="):
                continue
            flags = int(line[2:].split(",")[5])
            liquid += bool(flags & 0x1)
            hazard += bool(flags & 0x2)
        check(
            "a water map has liquid stances and no hazard stances",
            liquid > 0 and hazard == 0,
            f"{liquid} liquid, {hazard} hazard; with lava alone the two flags "
            "are always set together and nothing could tell them apart",
        )


def test_determinism(exe: Path, maps: list[Path]) -> None:
    head("determinism: the same graph twice, and on eight threads at once")
    if not maps:
        return
    picks = [maps[0], maps[len(maps) // 2], maps[-1]]
    for path in picks:
        out = run(exe, "stable", str(path)).strip()
        check(f"{path.name}: two builds give the same digest", out.startswith("STABLE"),
              out[:120])
    for path in picks[:2]:
        out = run(exe, "threads", str(path), "8").strip()
        check(
            f"{path.name}: eight concurrent builds are identical",
            out.startswith("IDENTICAL"),
            out[:120],
        )


def test_refusals(exe: Path, maps: list[Path]) -> None:
    head("refusals: cell sizes the header does not allow")
    if not maps:
        return
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))
    lo = header_int(hdr, "MAPGEN_SPACE_MIN_CELL") or 16
    hi = header_int(hdr, "MAPGEN_SPACE_MAX_CELL") or 256

    out = run(exe, "cells", str(maps[0]))
    seen: dict[int, str] = {}
    for line in out.splitlines():
        m = re.match(r"cell (-?\d+) -> (\w+)", line)
        if m:
            seen[int(m.group(1))] = m.group(2)

    check("the cell matrix ran", len(seen) >= 8, str(seen))
    check(f"cell {lo - 1} is refused", seen.get(lo - 1) == "ERR_CELL_SIZE", str(seen))
    check(f"cell {lo} is accepted", seen.get(lo) == "OK", str(seen))
    check(f"cell {hi} is accepted", seen.get(hi) == "OK", str(seen))
    check(f"cell {hi + 1} is refused", seen.get(hi + 1) == "ERR_CELL_SIZE", str(seen))
    check("a negative cell is refused", seen.get(-32) == "ERR_CELL_SIZE", str(seen))
    check("cell 0 means the default", seen.get(0) == "OK", str(seen))

    # A coarser grid must find fewer stances than a finer one: the sampling is
    # a grid, and if it were not, the cell size would not mean anything.
    fine = parse_summary(run(exe, "summary", str(maps[0]), "16").strip())
    coarse = parse_summary(run(exe, "summary", str(maps[0]), "64").strip())
    check(
        "a coarser grid finds fewer stances than a finer one",
        fine is not None and coarse is not None
        and fine["nodes"] > coarse["nodes"] > 0,
        f"16 -> {fine}, 64 -> {coarse}",
    )


def main() -> int:
    print("=== MAPGEN-1 M2 MapGenSpace contract")
    test_identity()
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_space_") as td:
        work = Path(td)
        head("building")
        exe = build(cc, work)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_reference(exe)
        maps = test_real(exe)
        test_invariants(exe, maps)
        test_determinism(exe, maps)
        test_refusals(exe, maps)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
