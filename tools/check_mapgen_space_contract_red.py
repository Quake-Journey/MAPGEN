#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_space_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Three mutations carry the weight:

  * `world-extent-taken-from-the-model-box` puts back the assumption that cost
    three shipped maps - `2box4`, `airport2` and `aqnitro` all declare a world
    model of +-99999, and asking for 39 million columns is not a small map;
  * `the-landing-is-not-checked` loosens the last of the three motion traces,
    so an edge would "arrive" wherever the drop happened to stop. No string
    comparison can see that; only the cross-implementation build can;
  * `the-jump-height-stops-following-from-the-physics` replaces a derived
    number with a plausible round one, which is the failure a guard that only
    compares against itself never catches.

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

SUITE = SANDBOX.path("tools/check_mapgen_space_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_space.c")
HDR = SANDBOX.path("inc/common/mapgen_space.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the world's extent ----------------------------------------------
    (
        # Mutated INSIDE world_bounds, so the function stays called and -Werror
        # does not fail the build instead of the check under test.
        "world-extent-taken-from-the-model-box",
        SRC,
        b"    if (world->headnode < 0) {\n",
        b"    for (int i = 0; i < 3; i++) {\n"
        b"        lo[i] = (int32_t)world->mins[i];\n"
        b"        hi[i] = (int32_t)world->maxs[i];\n"
        b"    }\n"
        b"    return hi[0] > lo[0] && hi[1] > lo[1] && hi[2] > lo[2];\n"
        b"    if (world->headnode < 0) {\n",
        "2box4.bsp builds despite its +-99999 world model",
    ),
    (
        "the-model-box-may-widen-the-tree",
        SRC,
        b"        if (world->mins[i] > (float)lo[i] && world->mins[i] < (float)hi[i])\n",
        b"        if (world->mins[i] < (float)hi[i])\n",
        "2box4.bsp builds despite its +-99999 world model",
    ),

    # --- the geometry, which only the reference build can judge ----------
    (
        "the-landing-is-not-checked",
        SRC,
        b"    const float landed = tr.endpos[2] - to->origin[2];\n"
        b"    return landed > -1.0f && landed < 1.0f;\n",
        b"    const float landed = tr.endpos[2] - to->origin[2];\n"
        b"    return landed > -1000.0f && landed < 1000.0f;\n",
        "2box4.bsp: the two builds are byte-identical",
    ),
    (
        "a-step-up-is-not-attempted",
        SRC,
        b"                             : (float)MAPGEN_SPACE_STEPSIZE;\n",
        b"                             : 0.0f;\n",
        "2box4.bsp: the two builds are byte-identical",
    ),
    (
        "the-crossing-may-be-obstructed",
        SRC,
        b"    MapGenTrace_Box(&b->trace, raised, across, b->mins, b->maxs,\n"
        b"                    MAPGEN_MASK_PLAYERSOLID, &tr);\n"
        b"    if (tr.fraction < 1.0f)\n        return false;\n",
        b"    MapGenTrace_Box(&b->trace, raised, across, b->mins, b->maxs,\n"
        b"                    MAPGEN_MASK_PLAYERSOLID, &tr);\n"
        b"    if (tr.fraction < 0.0f)\n        return false;\n",
        "redyard.bsp: the two builds are byte-identical",
    ),
    (
        "a-slope-counts-as-ground",
        SRC,
        b"    return (int32_t)(tr->plane_normal[2] * 1000.0f) >= MAPGEN_SPACE_GROUND_NORMAL_Z_MILLI;\n",
        b"    return (int32_t)(tr->plane_normal[2] * 1000.0f) >= 1;\n",
        "2box4.bsp: the two builds are byte-identical",
    ),
    (
        # Only `rcdm17` reaches this: three of its stances fit a crouch and
        # nothing else. It is in the reference set for exactly this reason.
        "a-ducked-stance-is-not-recorded",
        SRC,
        b"            ducked = hull_fits(b, stance, b->duck_maxs);\n",
        b"            ducked = false;\n",
        "rcdm17.bsp: the two builds are byte-identical",
    ),
    (
        "region-labels-follow-the-union-find-roots",
        SRC,
        b"        if (label[root] == UINT32_MAX)\n            label[root] = next++;\n",
        b"        if (label[root] == UINT32_MAX)\n            label[root] = root;\n",
        "2box4.bsp: the two builds are byte-identical",
    ),

    # --- classification and invariants ------------------------------------
    (
        "a-jump-is-classified-as-a-step",
        SRC,
        b"    if (rise > MAPGEN_SPACE_STEPSIZE)\n        return MAPGEN_EDGE_JUMP;\n",
        b"    if (rise > MAPGEN_SPACE_STEPSIZE + 4)\n        return MAPGEN_EDGE_JUMP;\n",
        "every edge's kind follows from its rise and its ends",
    ),
    (
        "a-rise-beyond-the-jump-height-is-allowed",
        SRC,
        b"            if (rise > MAPGEN_SPACE_JUMP_RISE)\n                continue;\n",
        b"            if (rise > MAPGEN_SPACE_JUMP_RISE + 64)\n                continue;\n",
        "every rise is inside the jump and fall bounds",
    ),
    (
        "a-node-links-to-itself",
        SRC,
        b"        const int32_t nx = from.cell[0] + NEIGHBOUR_DX[n];\n"
        b"        const int32_t ny = from.cell[1] + NEIGHBOUR_DY[n];\n",
        b"        const int32_t nx = from.cell[0] + NEIGHBOUR_DX[n] * 0;\n"
        b"        const int32_t ny = from.cell[1] + NEIGHBOUR_DY[n] * 0;\n",
        "no node has an edge to itself",
    ),
    (
        "jumps-and-falls-merge-regions",
        SRC,
        b"    return kind == MAPGEN_EDGE_WALK || kind == MAPGEN_EDGE_STEP ||\n"
        b"           kind == MAPGEN_EDGE_SWIM;\n",
        b"    return kind != MAPGEN_EDGE_KIND_COUNT;\n",
        "regions are joined only by symmetric motions",
    ),

    # --- lifecycle and refusals ------------------------------------------
    (
        "the-column-ceiling-is-checked-after-allocating",
        SRC,
        b"        if (cols <= 0 || cols > (int64_t)MAPGEN_SPACE_MAX_COLUMNS)\n"
        b"            return MAPGEN_SPACE_ERR_TOO_LARGE;\n",
        b"        if (cols <= 0)\n"
        b"            return MAPGEN_SPACE_ERR_TOO_LARGE;\n",
        "the column ceiling is checked BEFORE anything is allocated",
    ),
    (
        "a-failed-allocation-reads-as-a-small-map",
        SRC,
        b"        if (!grown) {\n            b->out_of_memory = true;\n"
        b"            return false;\n        }\n        sp->nodes = grown;\n",
        b"        if (!grown) {\n            return false;\n        }\n"
        b"        sp->nodes = grown;\n",
        "a failed allocation is not reported as a small map",
    ),
    (
        "the-column-scan-is-unbounded",
        SRC,
        b"    while (z > b->world_bottom && floors < MAPGEN_SPACE_MAX_FLOORS_PER_COLUMN) {\n",
        b"    while (z > b->world_bottom) {\n",
        "the column scan is bounded",
    ),
    (
        "graph-state-in-a-function-local-static",
        SRC,
        b"    float z = b->world_top;\n",
        b"    static float z;\n    z = b->world_top;\n",
        "no function-local static state",
    ),
    (
        "graph-state-at-file-scope",
        SRC,
        b"static void scan_column(build_t *b, int32_t ix, int32_t iy, bool include_liquids)\n{\n",
        b"static uint32_t g_columns_scanned;\n\n"
        b"static void scan_column(build_t *b, int32_t ix, int32_t iy, bool include_liquids)\n{\n"
        b"    g_columns_scanned++;\n",
        "no mutable file-scope state",
    ),
    (
        "the-cell-range-is-not-enforced",
        SRC,
        b"    if (p.cell < MAPGEN_SPACE_MIN_CELL || p.cell > MAPGEN_SPACE_MAX_CELL)\n"
        b"        return MAPGEN_SPACE_ERR_CELL_SIZE;\n",
        b"    if (p.cell < 1)\n        return MAPGEN_SPACE_ERR_CELL_SIZE;\n",
        "cell 257 is refused",
    ),

    # --- identity ---------------------------------------------------------
    (
        "the-step-height-drifts-from-the-engine",
        HDR,
        b"#define MAPGEN_SPACE_STEPSIZE       18\n",
        b"#define MAPGEN_SPACE_STEPSIZE       24\n",
        "MAPGEN_SPACE_STEPSIZE is the engine's step height",
    ),
    (
        "the-jump-height-stops-following-from-the-physics",
        HDR,
        b"#define MAPGEN_SPACE_JUMP_RISE      45\n",
        b"#define MAPGEN_SPACE_JUMP_RISE      64\n",
        "MAPGEN_SPACE_JUMP_RISE follows from the jump speed and gravity",
    ),
    (
        "the-ground-threshold-drifts-from-the-engine",
        HDR,
        b"#define MAPGEN_SPACE_GROUND_NORMAL_Z_MILLI  700\n",
        b"#define MAPGEN_SPACE_GROUND_NORMAL_Z_MILLI  500\n",
        "the ground test is PM_CategorizePosition's 0.7",
    ),
    (
        "the-hull-is-not-the-engine-s",
        HDR,
        b"#define MAPGEN_SPACE_HULL_TOP       32\n",
        b"#define MAPGEN_SPACE_HULL_TOP       28\n",
        "the hull is the engine's standing hull",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=3600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 MapGenSpace controlled RED")

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
