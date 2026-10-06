#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_features_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Three mutations carry the weight:

  * `a-symmetric-connection-is-counted-twice` inflates the cyclomatic number
    and hides every bridge, which is the single easiest way to get a
    "redundancy" feature that is quietly meaningless;
  * `the-sight-line-is-blocked-by-water` changes what "cover" means without
    changing anything a static check could see;
  * `an-entity-binds-to-the-nearest-stance-anywhere` turns "unbound" into a
    number that never happens, which would read as a map with nothing out of
    place rather than as a broken measurement.

A mutation may trip more than one case; what is being proven is that the NAMED
case detects it. Exit 0 = every mutation detected on its own case, every file
restored byte-identically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mapgen_red_sandbox import Sandbox  # noqa: E402
from mapgen_red_support import resolve_anchor, sha256  # noqa: E402

# R1: every mutation happens in a disposable copy under the task's own
# temp root. The shared worktree is never opened for writing, so a killed
# process cannot leave a mutation behind - twice it did.
SANDBOX = Sandbox(REPO, Path(__file__).stem)

SUITE = SANDBOX.path("tools/check_mapgen_features_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_features.c")
HDR = SANDBOX.path("inc/common/mapgen_features.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- connectivity ------------------------------------------------------
    (
        "a-symmetric-connection-is-counted-twice",
        SRC,
        b"        if (!joins(e->kind) || e->from == e->to || e->from > e->to)\n"
        b"            continue;\n        const uint32_t id = g->num_edges++;\n",
        b"        if (!joins(e->kind) || e->from == e->to)\n"
        b"            continue;\n        const uint32_t id = g->num_edges++;\n",
        "2box4.bsp: the two vectors are identical",
    ),
    (
        "jumps-and-falls-join-the-walk-graph",
        SRC,
        b"    return kind == MAPGEN_EDGE_WALK || kind == MAPGEN_EDGE_STEP ||\n"
        b"           kind == MAPGEN_EDGE_SWIM;\n",
        b"    return kind != MAPGEN_EDGE_KIND_COUNT;\n",
        "2box4.bsp: the two vectors are identical",
    ),
    (
        "the-root-is-never-a-chokepoint",
        SRC,
        b"        if (children[root] > 1)\n            is_articulation[root] = 1;\n",
        b"        if (children[root] > 2000000000u)\n            is_articulation[root] = 1;\n",
        # Only `ztn2dm1` reaches this branch: it is the one small map whose
        # depth-first search has a root with two children. On the others the
        # mutation changes nothing, which is a coverage fact, not a pass.
        "ztn2dm1.bsp: the two vectors are identical",
    ),
    (
        "a-bridge-is-any-tree-edge",
        SRC,
        b"            if (low[child] > disc[parent])\n                out->bridges++;\n",
        b"            if (low[child] >= disc[parent])\n                out->bridges++;\n",
        "2box4.bsp: the two vectors are identical",
    ),
    (
        "the-cyclomatic-number-forgets-the-components",
        SRC,
        b"    f->v.loops = g.num_edges + conn.components >= n\n"
        b"               ? g.num_edges + conn.components - n : 0;\n",
        b"    f->v.loops = g.num_edges >= n ? g.num_edges - n : 0;\n",
        "2box4.bsp: the two vectors are identical",
    ),

    # --- visibility --------------------------------------------------------
    (
        "the-sight-line-is-blocked-by-water",
        SRC,
        b"                            MAPGEN_TRACE_SOLID | MAPGEN_TRACE_WINDOW, &tr);\n",
        b"                            MAPGEN_TRACE_SOLID | MAPGEN_TRACE_WINDOW |\n"
        b"                            MAPGEN_TRACE_WATER, &tr);\n",
        "a sight line is stopped by solid and by window, and nothing else",
    ),
    (
        "the-eye-is-on-the-floor",
        HDR,
        b"#define MAPGEN_FEATURES_VIEWHEIGHT   22\n",
        b"#define MAPGEN_FEATURES_VIEWHEIGHT   0\n",
        "MAPGEN_FEATURES_VIEWHEIGHT is the engine's standing view height",
    ),
    (
        "the-sight-sample-uses-a-box-not-a-point",
        SRC,
        b"            static const float zero[3] = { 0.0f, 0.0f, 0.0f };\n",
        b"            static const float notzero[3] = { 0.0f, 0.0f, 0.0f };\n"
        b"            const float *zero = notzero;\n",
        "the sight line is a point trace",
    ),
    (
        "cover-is-computed-from-the-wrong-denominator",
        SRC,
        b"            (uint32_t)((uint64_t)v->sight_open * 1000u / v->sight_pairs);\n",
        b"            (uint32_t)((uint64_t)v->sight_open * 1000u / (v->sight_pairs + 1u));\n",
        "cover follows from the sample it names",
    ),
    (
        "the-sample-is-not-chosen-by-stride",
        SRC,
        b"    const uint32_t observer_stride = n / observers;\n",
        b"    const uint32_t observer_stride = 1;\n",
        "2box4.bsp: the two vectors are identical",
    ),

    # --- shape -------------------------------------------------------------
    (
        "height-bands-truncate-towards-zero",
        SRC,
        b"    const int32_t q = value / divisor;\n"
        b"    return (value % divisor != 0 && (value < 0) != (divisor < 0)) ? q - 1 : q;\n",
        b"    return value / divisor;\n",
        "height bands use floor division",
    ),
    (
        "openness-is-measured-below-the-probe",
        SRC,
        b"        if (clearances[i] >= 512)\n",
        b"        if (clearances[i] >= 256)\n",
        "redyard.bsp: the two vectors are identical",
    ),
    (
        "the-median-is-the-mean",
        SRC,
        b"    v->median_clearance = clearances[n / 2];\n",
        b"    v->median_clearance = clearances[n / 4];\n",
        "2box4.bsp: the two vectors are identical",
    ),

    # --- entity binding ----------------------------------------------------
    (
        "an-entity-binds-to-the-nearest-stance-anywhere",
        SRC,
        b"            if (dx > MAPGEN_FEATURES_BIND_RADIUS_XY || dx < -MAPGEN_FEATURES_BIND_RADIUS_XY ||\n"
        b"                dy > MAPGEN_FEATURES_BIND_RADIUS_XY || dy < -MAPGEN_FEATURES_BIND_RADIUS_XY ||\n"
        b"                dz > MAPGEN_FEATURES_BIND_RADIUS_Z  || dz < -MAPGEN_FEATURES_BIND_RADIUS_Z)\n"
        b"                continue;\n",
        b"            if (dx > 100000 || dy > 100000 || dz > 100000)\n"
        b"                continue;\n",
        "an entity binds only inside a stated radius",
    ),
    (
        "a-binding-tie-goes-to-the-later-stance",
        SRC,
        b"            if (d < best_d) {\n",
        b"            if (d <= best_d) {\n",
        # The vector carries only counts, so a tie resolving to a different
        # stance is observable in the binding list and nowhere else.
        "2box4.bsp: the two agree on which stance each entity stands on",
    ),
    (
        "an-unbound-entity-is-still-counted-as-bound",
        SRC,
        b"        if (bound)\n            v->bound_entities++;\n"
        b"        else\n            v->unbound_entities++;\n",
        b"        if (true)\n            v->bound_entities++;\n"
        b"        else\n            v->unbound_entities++;\n",
        # bound + unbound still equals positioned, so the self-consistency rule
        # cannot see this one. The reference build can.
        "2box4.bsp: the two vectors are identical",
    ),

    # --- integers and state ------------------------------------------------
    (
        "a-length-comes-from-libm",
        SRC,
        b"static uint32_t isqrt32(uint64_t v)\n"
        b"{\n"
        b"    if (v == 0)\n"
        b"        return 0;\n"
        b"    uint64_t x = v, y = (x + 1) / 2;\n"
        b"    while (y < x) {\n"
        b"        x = y;\n"
        b"        y = (x + v / x) / 2;\n"
        b"    }\n"
        b"    return (uint32_t)x;\n"
        b"}\n",
        b"#include <math.h>\n"
        b"static uint32_t isqrt32(uint64_t v)\n"
        b"{\n"
        b"    return (uint32_t)sqrt((double)v);\n"
        b"}\n",
        "the square root is integer",
    ),
    (
        "features-state-at-file-scope",
        SRC,
        b"static int cmp_u32(const void *a, const void *b)\n{\n",
        b"static uint32_t g_comparisons;\n\n"
        b"static int cmp_u32(const void *a, const void *b)\n{\n"
        b"    g_comparisons++;\n",
        "no mutable file-scope state",
    ),
    (
        "a-float-appears-in-the-vector",
        HDR,
        b"    uint32_t mean_item_separation;      /* nearest other item, whole units  */\n",
        b"    float    mean_item_separation;      /* nearest other item, whole units  */\n",
        "not one float leaves the interface",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=3600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 MapGenFeatures controlled RED")

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  baseline is not GREEN; refusing to mutate anything")
        print(out[-4000:])
        return 1
    print("  OK    baseline GREEN")

    failures = 0
    for name, path, anchor, replacement, expected_fail in CASES:
        original = path.read_bytes()
        original_hash = sha256(path)

        anchor, replacement, occurrences = resolve_anchor(original, anchor, replacement)
        if occurrences != 1:
            print(
                f"  FAIL  {name}: anchor occurs {occurrences} times in {path.name} "
                "(need exactly 1); the matrix is invalid, not skipped"
            )
            failures += 1
            continue

        mutated = original.replace(anchor, replacement, 1)
        if mutated == original:
            print(f"  FAIL  {name}: mutation did not change {path.name}")
            failures += 1
            continue

        try:
            path.write_bytes(mutated)
            if path.read_bytes() == original:
                print(f"  FAIL  {name}: mutation did not reach disk")
                failures += 1
                continue

            rc, out = run_suite()
            if rc == 0:
                print(f"  FAIL  {name}: suite stayed GREEN under the mutation")
                failures += 1
            elif f"FAIL  {expected_fail}" not in out:
                shown = [ln.strip() for ln in out.splitlines() if ln.startswith("  FAIL")][:4]
                print(f"  FAIL  {name}: went RED but not on '{expected_fail}'; got {shown}")
                failures += 1
            else:
                print(f"  RED   {name} -> {expected_fail}")
        finally:
            # From the pristine tree, not from a value this run computed.
            SANDBOX.restore(SANDBOX.relative(path))

        if sha256(path) != original_hash:
            print(f"  FAIL  {name}: {path.name} was not restored byte-identically")
            failures += 1

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  suite is not GREEN again after restoration")
        print(out[-4000:])
        failures += 1
    else:
        print("  OK    restored GREEN")

    print(f"\n=== {len(CASES)} controlled-RED cases, {failures} failures")
    if failures:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
