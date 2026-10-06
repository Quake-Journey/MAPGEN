#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_mapfile_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Every mutation here produces a file that LOOKS right. That is the whole point
of this stage's tests: a `.map` is text, and text that parses is not text that
compiles into the map somebody meant.

  * `the-winding-is-reversed` writes the same six planes with two points
    swapped. Every line is valid, every number is in range, and the compiler
    builds a room with its walls facing the wrong way;

  * `a-face-sits-on-the-wrong-side-of-the-brush` keeps all six normals correct
    and puts three of the planes at the opposite coordinate, which is a brush
    with no inside;

  * `a-texture-axis-lies-along-the-face` divides by zero inside the compiler
    and reads perfectly ordinarily.

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

SUITE = SANDBOX.path("tools/check_mapgen_mapfile_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_mapfile.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the winding ---------------------------------------------------------
    (
        "the-winding-is-reversed",
        SRC,
        b"    if (sign > 0) {\n"
        b"        points[0][u] = brush->maxs[u];\n"
        b"        points[2][v] = brush->maxs[v];\n"
        b"    } else {\n"
        b"        points[0][v] = brush->maxs[v];\n"
        b"        points[2][u] = brush->maxs[u];\n"
        b"    }\n",
        b"    if (sign > 0) {\n"
        b"        points[0][v] = brush->maxs[v];\n"
        b"        points[2][u] = brush->maxs[u];\n"
        b"    } else {\n"
        b"        points[0][u] = brush->maxs[u];\n"
        b"        points[2][v] = brush->maxs[v];\n"
        b"    }\n",
        # Every face still has a direction of its own - they are all just
        # inverted - so the case that notices is the one asking whether the
        # +face sits above the -face.
        "every brush has an inside",
    ),
    (
        "a-face-sits-on-the-wrong-side-of-the-brush",
        SRC,
        b"    const int32_t plane = sign > 0 ? brush->maxs[axis] : brush->mins[axis];\n",
        b"    const int32_t plane = sign > 0 ? brush->mins[axis] : brush->maxs[axis];\n",
        "every brush has an inside",
    ),
    (
        "two-faces-share-a-direction",
        SRC,
        b"    case MAPGEN_FACE_WEST:   *axis = 0; *sign = -1; break;\n",
        b"    case MAPGEN_FACE_WEST:   *axis = 0; *sign = +1; break;\n",
        "every plane's normal is axis-aligned, and a brush has all six",
    ),
    (
        "a-plane-is-not-flat",
        SRC,
        b"    for (int p = 0; p < 3; p++) {\n"
        b"        points[p][axis] = plane;\n",
        b"    for (int p = 0; p < 3; p++) {\n"
        b"        points[p][axis] = plane + p;\n",
        "and every face's three points lie on it",
    ),

    # --- the texture axes ------------------------------------------------------
    (
        "a-texture-axis-lies-along-the-face",
        SRC,
        b"    case MAPGEN_FACE_TOP:\n"
        b"    case MAPGEN_FACE_BOTTOM:\n"
        b"        u_axis[0] = 1;\n"
        b"        v_axis[1] = -1;\n"
        b"        break;\n",
        b"    case MAPGEN_FACE_TOP:\n"
        b"    case MAPGEN_FACE_BOTTOM:\n"
        b"        u_axis[2] = 1;\n"
        b"        v_axis[1] = -1;\n"
        b"        break;\n",
        "and every texture axis is usable",
    ),
    (
        "a-texture-axis-is-all-zero",
        SRC,
        b"    case MAPGEN_FACE_NORTH:\n"
        b"    case MAPGEN_FACE_SOUTH:\n"
        b"    default:\n"
        b"        u_axis[0] = 1;\n"
        b"        v_axis[2] = -1;\n"
        b"        break;\n",
        b"    case MAPGEN_FACE_NORTH:\n"
        b"    case MAPGEN_FACE_SOUTH:\n"
        b"    default:\n"
        b"        v_axis[2] = -1;\n"
        b"        break;\n",
        "and every texture axis is usable",
    ),

    # --- the text --------------------------------------------------------------
    (
        "the-file-gets-windows-line-endings",
        SRC,
        b'    emit(o, "}\\n");\n'
        b"    return true;\n",
        b'    emit(o, "}\\r\\n");\n'
        b"    return true;\n",
        "the file has no carriage returns",
    ),
    (
        "the-display-name-goes-into-the-map",
        SRC,
        b"    emit(&o, MapGenRecipe_Slug(recipe) ? MapGenRecipe_Slug(recipe) : \"q2mg\");\n",
        b"    emit(&o, MapGenRecipe_DisplayName(recipe)\n"
        b"             ? MapGenRecipe_DisplayName(recipe) : \"q2mg\");\n",
        "and the message is the slug",
    ),
    (
        "a-brush-loses-a-face",
        SRC,
        b"        for (uint32_t f = 0; f < MAPGEN_FACE_COUNT; f++) {\n",
        b"        for (uint32_t f = 1; f < MAPGEN_FACE_COUNT; f++) {\n",
        "every brush has exactly six faces",
    ),
    (
        "a-brush-is-left-out",
        SRC,
        b"    for (uint32_t i = 0; i < MapGenBrush_Count(work); i++) {\n"
        b"        if (!emit_brush(&o, MapGenBrush_At(work, i), model)) {\n",
        b"    for (uint32_t i = 1; i < MapGenBrush_Count(work); i++) {\n"
        b"        if (!emit_brush(&o, MapGenBrush_At(work, i), model)) {\n",
        "the worldspawn holds every brush",
    ),

    # --- the entities ------------------------------------------------------------
    (
        "an-entity-loses-its-origin",
        SRC,
        b'        emit(&o, "\\"\\n\\"origin\\" \\"");\n'
        b"        for (int axis = 0; axis < 3; axis++) {\n"
        b"            emit_i32(&o, e->origin[axis]);\n",
        b'        emit(&o, "\\"\\n\\"notorigin\\" \\"");\n'
        b"        for (int axis = 0; axis < 3; axis++) {\n"
        b"            emit_i32(&o, e->origin[axis]);\n",
        "every point entity has an origin",
    ),
    (
        "an-entity-is-left-out",
        SRC,
        b"    for (uint32_t i = 0; i < MapGenEntities_Count(entities); i++) {\n",
        b"    for (uint32_t i = 1; i < MapGenEntities_Count(entities); i++) {\n",
        "and there are as many point entities as were placed",
    ),
    (
        "a-brush-entity-is-left-out",
        SRC,
        b"    for (uint32_t i = 0; i < MapGenBrush_NumFixtures(work); i++) {\n",
        b"    for (uint32_t i = 1; i < MapGenBrush_NumFixtures(work); i++) {\n",
        # A door that is not written is a doorway with nothing in it, and the
        # compiler is perfectly happy with that.
        "and as many brush entities as were built",
    ),
    (
        "a-brush-entity-loses-its-brush",
        SRC,
        b"        if (!emit_brush(&o, &f->brush, model)) {\n"
        b"            free(o.text);\n"
        b"            return MAPGEN_MAPFILE_ERR_NO_MATERIAL;\n"
        b"        }\n",
        b"        if (false) {\n"
        b"            (void)emit_brush(&o, &f->brush, model);\n"
        b"            free(o.text);\n"
        b"            return MAPGEN_MAPFILE_ERR_NO_MATERIAL;\n"
        b"        }\n",
        "every brush entity has a classname and exactly one brush",
    ),
    (
        "a-teleporter-loses-its-destination",
        SRC,
        b"    for (uint32_t i = 0; i < MapGenBrush_NumMarkers(work); i++) {\n",
        b"    for (uint32_t i = 1; i < MapGenBrush_NumMarkers(work); i++) {\n",
        # The trigger is still written; what it targets is not. The player
        # walks in and arrives nowhere, and nothing in the compile says so.
        "a teleport trigger names a destination that exists",
    ),
    (
        "the-item-that-was-asked-for-is-not-written",
        SRC,
        b"        emit(&o, e->classname);\n",
        b'        emit(&o, strcmp(e->classname, "weapon_railgun") ? e->classname\n'
        b'                                                       : "item_health");\n',
        "the railgun that was asked for is in the file",
    ),

    # --- determinism ---------------------------------------------------------------
    (
        "the-writer-is-not-a-function-of-its-inputs",
        SRC,
        b"    emit(&o, \"// Generated by Q2PRO-X MAPGEN-1\\n\");\n",
        b"    static int called;\n"
        b"    emit(&o, \"// Generated by Q2PRO-X MAPGEN-1\\n\");\n"
        b"    if (called++)\n"
        b"        emit(&o, \"// again\\n\");\n",
        "and wrote the same bytes when asked twice",
    ),

    # --- refusals -----------------------------------------------------------------
    (
        "a-refused-write-leaves-a-stale-pointer",
        SRC,
        b"    if (out_text)\n"
        b"        *out_text = NULL;\n"
        b"    if (out_size)\n"
        b"        *out_size = 0;\n"
        b"    if (!work || !entities || !model || !recipe || !out_text || !out_size)\n"
        b"        return MAPGEN_MAPFILE_ERR_ARGS;\n",
        b"    if (!work || !entities || !model || !recipe || !out_text || !out_size)\n"
        b"        return MAPGEN_MAPFILE_ERR_ARGS;\n"
        b"    if (out_text)\n"
        b"        *out_text = NULL;\n"
        b"    if (out_size)\n"
        b"        *out_size = 0;\n",
        "the out-parameters are cleared before anything can fail",
    ),
]


def run_suite() -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(SUITE)], capture_output=True, text=True,
            cwd=str(REPO), timeout=2400,
        )
    except subprocess.TimeoutExpired:
        return 1, "  FAIL  the writer produced a file  -- timed out"
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 M4 map-file controlled RED")

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
