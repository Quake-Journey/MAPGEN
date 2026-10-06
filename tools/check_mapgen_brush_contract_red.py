#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_brush_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

The mutations that carry the most weight are the ones that still produce a map
somebody could compile:

  * `there-is-no-wall-at-all` and `the-shell-forgets-the-empty-space-it-
    surrounds` both leave a map full of brushes and full of holes. The module
    catches them itself, by refusing with ERR_LEAK, which is the seal check
    doing its job - so the case that goes red is the build;

  * `a-brush-may-stand-in-a-room` puts solid where a player was meant to walk,
    in a map that still compiles and still looks sealed from outside;

  * `a-texture-is-drawn-for-every-brush` produces a perfectly legal map made
    of forty different walls, which is not what the corpus looks like.

THREE mutations are NOT in this matrix and are recorded rather than hidden,
because this corpus cannot reach the path they break:

  * removing the seal check, and seeding the flood from the inside instead of
    the outside - with an intact shell nothing leaks, so neither changes any
    result. They are observable only alongside a second defect that creates a
    leak, and a controlled-RED case applies one mutation;

  * removing the refusal when no material fits a role - every snapshot here
    contains solid materials, so a build never runs out of one.

All three are checked statically instead, in a form a mutation cannot leave
standing. A static check that looks for a CALL survives an `&& false` written
beside it, which is exactly how several of the checks here first failed to
notice anything at all.

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

SUITE = SANDBOX.path("tools/check_mapgen_brush_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_brush.c")
HDR = SANDBOX.path("inc/common/mapgen_brush.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the seal ------------------------------------------------------------
    (
        "the-world-has-no-margin-of-rock-around-it",
        HDR,
        b"#define MAPGEN_BRUSH_WALL_VOXELS  2\n",
        # The solid is every non-empty voxel now, so this constant no longer
        # sets a wall thickness - it sets how much rock the grid keeps around
        # the map. At zero the outermost empty voxels sit on the grid boundary
        # and the map has no enclosing material.
        b"#define MAPGEN_BRUSH_WALL_VOXELS  0\n",
        "the solid world is derived from the empty space",
    ),
    # --- the shell -----------------------------------------------------------
    (
        "the-rock-is-full-of-holes",
        SRC,
        b"                g.cell[at] = VOXEL_SHELL;\n",
        b"                if (x & 1u)\n"
        b"                    g.cell[at] = VOXEL_SHELL;\n",
        # Half the rock stops being solid, which is the shell defect in its
        # purest form: the map stops being carved out of anything. The module
        # notices it itself and refuses with ERR_LEAK, so the case that goes
        # red is the build.
        "the solid world is derived from the empty space",
    ),
    (
        "a-brush-may-stand-in-a-room",
        SRC,
        b"                if (g.cell[at] == VOXEL_EMPTY)\n"
        b"                    continue;\n",
        b"                if (g.cell[at] == VOXEL_EMPTY && (x & 1u))\n"
        b"                    continue;\n",
        "no brush stands inside a room",
    ),

    # --- the brushes ---------------------------------------------------------
    (
        "a-brush-may-have-no-volume",
        SRC,
        b"                b->maxs[0] = g.origin[0] + (int32_t)x1 * v;\n",
        b"                b->maxs[0] = g.origin[0] + (int32_t)x * v;\n",
        "every brush is a box with a volume",
    ),
    (
        "a-brush-may-be-off-the-grid",
        SRC,
        b"                b->mins[2] = g.origin[2] + (int32_t)z * v;\n",
        b"                b->mins[2] = g.origin[2] + (int32_t)z * v + 1;\n",
        "and every corner is on the grid",
    ),
    (
        "the-merge-claims-voxels-it-did-not-emit",
        SRC,
        b"                claim(&g, x, x1, y, y1, z, z1);\n",
        b"                claim(&g, x, x1 + 1, y, y1, z, z1);\n",
        "and a flood from outside never reaches it",
    ),

    # --- provenance ----------------------------------------------------------
    (
        "a-liquid-may-be-used-as-a-wall",
        SRC,
        b"    const uint32_t forbidden = MAPGEN_ROLE_SKY | MAPGEN_ROLE_WATER\n"
        b"                             | MAPGEN_ROLE_LAVA | MAPGEN_ROLE_SLIME\n"
        b"                             | MAPGEN_ROLE_NODRAW | MAPGEN_ROLE_CLIP\n"
        b"                             | MAPGEN_ROLE_TRANSLUCENT | MAPGEN_ROLE_LIGHT;\n",
        b"    const uint32_t forbidden = MAPGEN_ROLE_NODRAW | MAPGEN_ROLE_CLIP;\n",
        # Whether a LIQUID is then actually chosen depends on the draw, so the
        # case that reliably notices is the static one, which requires the
        # exclusion list in its exact form.
        "the sky and the liquids are excluded from every solid surface",
    ),
    (
        "a-material-need-not-have-been-used-as-a-solid",
        SRC,
        b"        if (wanted && !(roles & wanted))\n"
        b"            continue;\n",
        b"        if (wanted && !(roles & wanted) && false)\n"
        b"            continue;\n",
        # Whether an unsuitable material is then drawn depends on the weights,
        # so the case that reliably notices is the static one - and it has to
        # match the exact statement, because `&& false` beside the condition
        # leaves any looser check standing.
        "a role the material must have, and roles that rule it out",
    ),
    (
        "the-forbidden-roles-are-not-excluded",
        SRC,
        b"        if (roles & forbidden)\n"
        b"            continue;\n",
        b"        if (roles & forbidden & 0u)\n"
        b"            continue;\n",
        "a role the material must have, and roles that rule it out",
    ),
    (
        "a-texture-is-drawn-for-every-brush",
        SRC,
        b"                b->material[MAPGEN_FACE_EAST] = wall_of[nearest];\n",
        b"                b->material[MAPGEN_FACE_EAST] =\n"
        b"                    pick_material(model, &rng, MAPGEN_ROLE_SOLID, forbidden);\n",
        "and there are no more sets than there are rooms",
    ),
    (
        "every-room-gets-the-same-texture-set",
        SRC,
        b"        floor_of[r] = pick_material(model, &rng, MAPGEN_ROLE_SOLID, forbidden);\n",
        b"        floor_of[r] = floor_of[0];\n",
        # The map goes back to being one room repeated, which is the defect the
        # per-room set exists to fix.
        "a texture set per room, drawn once per room and not once per brush",
    ),
    (
        "a-brush-wears-one-rooms-floor-and-anothers-wall",
        SRC,
        b"                b->material[MAPGEN_FACE_NORTH] = wall_of[nearest];\n",
        b"                b->material[MAPGEN_FACE_NORTH] =\n"
        b"                    wall_of[nearest + 1 < num_rooms ? nearest + 1 : 0];\n",
        "and every brush wears one room's set whole",
    ),
    (
        "a-pool-is-filled-with-whatever-was-drawn",
        SRC,
        b"        const uint32_t liquid = pick_material(model, &rng, pool->role, 0);\n",
        b"        const uint32_t liquid =\n"
        b"            pick_material(model, &rng, MAPGEN_ROLE_SOLID, forbidden);\n",
        # A lava pit filled with a wall texture is a pit that does not burn.
        "a pool is filled with a material of the pool's own role",
    ),
    (
        "the-sky-goes-on-any-face",
        SRC,
        b"                    b->material[MAPGEN_FACE_BOTTOM] = sky;\n",
        # The same brushes, the same condition - a wall face instead of the
        # ceiling, where a sky is a hole rather than a courtyard.
        # Deliberately the UPWARD face. The wall materials are assigned
        # two lines below the sky block, so a sky put on a wall would be
        # overwritten and the mutation would prove nothing.
        b"                    b->material[MAPGEN_FACE_TOP] = sky;\n",
        "the sky only ever looks down, and only over an outdoor room",
    ),
    (
        "no-room-is-ever-open-to-the-sky",
        SANDBOX.path("src/mapgen/mapgen_layout.c"),
        b"        const bool outdoor = sky_material_learned\n",
        b"        const bool outdoor = false && sky_material_learned\n",
        # Back to a map of closed boxes, which is where this started.
        "a corpus with sky in it opens some rooms to it",
    ),
    (
        "a-fixtures-brush-is-left-untextured",
        SRC,
        b"    for (uint32_t face = 0; face < MAPGEN_FACE_COUNT; face++)\n"
        b"        f->brush.material[face] = material;\n",
        b"    f->brush.material[MAPGEN_FACE_TOP] = material;\n",
        "and a fixture's brush is textured on every face like any other",
    ),
    # --- determinism ---------------------------------------------------------
    (
        "the-textures-come-from-another-stages-stream",
        SRC,
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,\n"
        b"                        MAPGEN_RANDOM_MATERIALS);\n",
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,\n"
        b"                        MAPGEN_RANDOM_BRUSHES);\n",
        "the material stream is the material stream",
    ),

    # --- refusals ------------------------------------------------------------
    (
        "a-refused-build-leaves-brushwork-behind",
        SRC,
        b"    if (out)\n"
        b"        *out = NULL;\n"
        b"    if (!layout || !model || !recipe || !out)\n"
        b"        return MAPGEN_BRUSH_ERR_ARGS;\n",
        b"    if (!layout || !model || !recipe || !out)\n"
        b"        return MAPGEN_BRUSH_ERR_ARGS;\n"
        b"    *out = NULL;\n",
        "a missing layout is refused rather than dereferenced",
    ),
    (
        "the-empty-space-is-not-counted",
        SRC,
        b"    uint64_t empty = 0;\n"
        b"    for (uint64_t i = 0; i < voxels; i++)\n"
        b"        if (g.cell[i] == VOXEL_EMPTY)\n"
        b"            empty++;\n",
        b"    uint64_t empty = 1;\n"
        b"    for (uint64_t i = 0; i < voxels; i++)\n"
        b"        if (g.cell[i] == VOXEL_EMPTY)\n"
        b"            empty += 0;\n",
        "the empty space survives the brushes intact",
    ),
]


def run_suite() -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(SUITE)], capture_output=True, text=True,
            cwd=str(REPO), timeout=2400,
        )
    except subprocess.TimeoutExpired:
        return 1, "  FAIL  the behavioural suite reported a result  -- timed out"
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 M4 brush controlled RED")

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
