#!/usr/bin/env python3
"""MAPGEN-1 M4 - the topology graph.

Contract section 16, stages 3 to 5: a typed graph sized for the goal and the
player envelope, learned motifs connected through compatible sockets, and
traversal routes of the kinds the corpus actually contained. Contract 14's
"None is absolute" and its "name the exact conflict" land here, and so does
contract 15's provenance rule.

Two halves:

  * STATIC - the properties that hold by construction. One table decides both
    what a route kind requires of the corpus and what control gates it, so the
    two rules cannot drift apart; the graph is built connected rather than
    repaired into connectivity; and the size is drawn from a learned sample
    instead of computed from the player count;

  * BEHAVIOUR - the compiled module against a real mixed model trained on four
    real maps. Connectivity is checked by WALKING the graph in the driver, in
    both the undirected and the directed sense, rather than by asking the
    module whether it kept its promise. "None is absolute" is checked for
    every gated control in turn, not for a convenient one.

Run: python tools/check_mapgen_topology_contract.py
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

HEADER = REPO / "inc" / "common" / "mapgen_topology.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_topology.c"
DRIVER = REPO / "tools" / "mapgen_topology_test_driver.c"
PARTS = [
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
MAPS = ["2box4.bsp", "redyard.bsp", "rcdm17.bsp", "lbrdm1.bsp"]

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
    head("static: one table, and connectivity by construction")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    check(
        "one table carries both the learned role and the control",
        "ROUTE_RULES[MAPGEN_ROUTE_KIND_COUNT]" in src
        and "const char *control;" in src and "uint32_t    role;" in src,
        "contract 14's None and contract 15's provenance are one lookup here, "
        "not two lists that agree today",
    )
    check(
        "every route kind is in it",
        all(f"[MAPGEN_ROUTE_{k}]" in src for k in
            ("WALK", "RAMP", "JUMP", "DROP", "SWIM", "DOOR", "LIFT", "TRAIN",
             "TELEPORT", "PUSH")),
        "",
    )
    check(
        "the kind that needs no control is the one that always works",
        '[MAPGEN_ROUTE_WALK]     = { "walk",     NULL,' in src,
        "with every other kind at None a map still has to be connected",
    )

    palette = src[src.find("static mapgen_topology_result_t build_palette"):]
    check(
        "None sets the weight to zero, before anything is drawn",
        "if (level <= 0)" in palette and "p->weight[k] = 0;" in palette,
        "a zero weight is never drawn, which the PRNG guard proves, so this "
        "is the prohibition and not a small chance",
    )
    check(
        "and there is no second flag beside the weight to disagree with it",
        "forbidden" not in src,
        "two names for one state is how the two drift apart",
    )
    check(
        "and an unlearned motif is refused with the control named",
        "MapGenMix_RoleIsLearned" in palette
        and "*conflict = rule->control;" in palette
        and "MAPGEN_TOPOLOGY_ERR_UNLEARNED_MOTIF" in palette,
        "contract 14 wants the exact conflict, not that one exists",
    )
    check(
        "a corpus without a motif nobody asked for is not a conflict",
        palette.find("if (level <= 0)") < palette.find("MapGenMix_RoleIsLearned"),
        "the check is reached only when the user asked for it",
    )

    build = src[src.find("mapgen_topology_result_t MapGenTopology_Build"):]
    check(
        "the shape is drawn from a learned sample",
        "MapGenMix_DrawSample" in build
        and "MAPGEN_MIX_STAT_HEIGHT_BANDS" in build
        and "MAPGEN_MIX_STAT_LARGEST_REGION_PERMILLE" in build,
        "contract 19: the band count and the largest area's share are "
        "measured evidence, not a curve of someone's invention",
    )
    check(
        "and the region count is NOT read as a room count",
        "MAPGEN_MIX_STAT_REGIONS" not in build,
        "`regions` counts connected components of the stance graph - aerowalk "
        "has 63 - and taking it for a room count built forty small boxes "
        "where the corpus has a dozen places",
    )
    check(
        "and the sample it used is recorded",
        "MapGenMix_SampleSource" in build,
        "a number in a report needs a source",
    )
    # Anchored on CODE, not on the pass comments: the comments are stripped
    # before this runs, so `find` would return -1 for all three and the
    # ordering would compare -1 against -1 and mean nothing.
    skeleton_at = build.find("for (uint32_t i = 1; i < nodes; i++)")
    loops_at = build.find("loop_target(MapGenRecipe_Goal(recipe), nodes)")
    one_way_at = build.find("only_one_way")
    check(
        "the skeleton is spanning and refuses one-way kinds",
        skeleton_at >= 0
        and "ROUTE_RULES[k].one_way" in build[skeleton_at:loops_at if loops_at > 0
                                              else len(build)],
        "connectivity is built in, not repaired afterwards",
    )
    check(
        "the three passes run skeleton, then loops, then one-way extras",
        skeleton_at >= 0 and loops_at >= 0 and one_way_at >= 0
        and skeleton_at < loops_at < one_way_at,
        "a drop added to an already connected graph cannot strand anybody",
    )
    check(
        "the stream is the topology stream and nothing else",
        "MAPGEN_RANDOM_TOPOLOGY" in build and src.count("MapGenRandom_Stream") == 1,
        "another stage's draws must not move the graph",
    )
    check(
        "the attempt index selects the stream",
        "MapGenRecipe_Seed(recipe), attempt" in build,
        "attempt N is the same graph however many ran beside it",
    )
    check(
        "there is no clock and no libc generator",
        not re.search(r"\b(time|clock|rand|srand)\s*\(", src),
        "",
    )
    check(
        "and no floating point",
        not re.search(r"\b(float|double)\b", src),
        "",
    )
    check(
        "the recipe is const to it",
        "mapgen_recipe_t *recipe" not in src.replace("const mapgen_recipe_t *recipe", ""),
        "a generator that could edit its recipe is not reproducible",
    )
    check(
        "and so is the model",
        "mapgen_mix_t *model" not in src.replace("const mapgen_mix_t *model", ""),
        "",
    )
    check(
        "it reads only the resolved half of a control",
        "MapGenRecipe_ResolvedValue" in src
        and "MapGenRecipe_Control(" not in src,
        "contract 10: Generate Again must not re-resolve an old Auto",
    )
    # The rule protects the PO's binary, not the generator: a module
    # the packaged helper runs has to be linked somewhere, and
    # mapgen_src is the somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_topology.c")
    check("the module reaches no build the PO runs", in_helper, why)
    check(
        "the header says why connectivity is not a fitness score",
        # The phrase wraps across a line in the header, so only the part that
        # sits on one line is matched.
        "a fitness score to be traded off" in HEADER.read_text(encoding="utf-8"),
        "",
    )
    check(
        "and the route kinds are declared where callers can see them",
        "MAPGEN_ROUTE_KIND_COUNT" in hdr and "MapGenTopology_RouteControl" in hdr,
        "",
    )


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("topology.exe" if os.name == "nt" else "topology")
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
    head("behaviour: a graph from a real model, walked rather than trusted")
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
    print("=== MAPGEN-1 M4 topology contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_topology_") as td:
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
