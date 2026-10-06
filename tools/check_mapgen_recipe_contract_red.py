#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_recipe_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

The mutations that carry the most weight are the ones that leave a working
program behind:

  * `the-checksum-covers-only-the-header` still refuses a damaged header and
    still round-trips every valid file. It only stops noticing when a control
    or a snapshot pin is changed - which is exactly the gap the snapshot
    container shipped with until a test found it;

  * `an-unread-component-counts-as-a-match` turns a failed toolchain read into
    a successful reuse, on the one machine where that matters most;

  * `a-control-may-be-overwritten` and `the-tables-are-not-sorted` both keep
    every value correct and make the result depend on the order the user
    clicked in.

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

SUITE = SANDBOX.path("tools/check_mapgen_recipe_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_recipe.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the file's own integrity -------------------------------------------
    (
        "the-checksum-covers-only-the-header",
        SRC,
        b"    if (size > OFF_CRC + 4)\n"
        b"        state = MapGenDigest_Crc32Update(state, image + OFF_CRC + 4,\n"
        b"                                         size - (OFF_CRC + 4));\n",
        b"    (void)size;\n",
        "and so is a change to a control the header never mentions",
    ),
    (
        "a-damaged-file-is-read-anyway",
        SRC,
        b"    if (image_crc(bytes, size) != rd_u32(bytes + OFF_CRC))\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_CRC;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_CRC;\n",
        "a checksum that does not describe the file is refused",
    ),
    (
        "a-file-need-not-be-the-size-it-says",
        SRC,
        b"    if (declared != (uint64_t)size)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_FILE_BYTES;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_FILE_BYTES;\n",
        "a file with slack after its tables says its size is wrong",
    ),
    (
        "the-magic-is-not-checked",
        SRC,
        b"    if (memcmp(bytes + OFF_MAGIC, MAPGEN_RECIPE_MAGIC, MAPGEN_RECIPE_MAGIC_BYTES))\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_MAGIC;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_MAGIC;\n",
        "a file with the wrong magic says so",
    ),
    (
        "a-future-schema-is-read-as-this-one",
        SRC,
        b"    if (rd_u16(bytes + OFF_SCHEMA_MAJOR) != MAPGEN_RECIPE_SCHEMA_MAJOR)\n"
        b"        return MAPGEN_RECIPE_ERR_UNSUPPORTED_MAJOR;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_UNSUPPORTED_MAJOR;\n",
        "a future schema major is refused as unsupported",
    ),
    (
        "the-reserved-bytes-may-say-anything",
        SRC,
        b"    if (rd_u16(bytes + OFF_RESERVED) != 0)\n"
        b"        return MAPGEN_RECIPE_ERR_RESERVED_NOT_ZERO;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_RESERVED_NOT_ZERO;\n",
        "a reserved byte that is not zero is refused",
    ),

    # --- a well-formed file may still be wrong ------------------------------
    (
        "a-file-may-carry-one-control-twice",
        SRC,
        b"        for (uint32_t j = 0; j < i; j++) {\n"
        b"            if (!strcmp(r->controls[j].key, r->controls[i].key)) {\n"
        b"                MapGenRecipe_Free(r);\n"
        b"                return MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL;\n"
        b"            }\n"
        b"        }\n",
        # Not `j < 0u`: an always-false comparison on an unsigned counter
        # fails the BUILD under -Werror rather than the check under test.
        b"        for (uint32_t j = i; j < i; j++) {\n"
        b"            if (!strcmp(r->controls[j].key, r->controls[i].key)) {\n"
        b"                MapGenRecipe_Free(r);\n"
        b"                return MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL;\n"
        b"            }\n"
        b"        }\n",
        "a file carrying one control twice is refused",
    ),
    (
        "a-file-may-carry-an-unresolved-control",
        SRC,
        b"        if (r->controls[i].resolved == MAPGEN_RECIPE_AUTO) {\n"
        b"            MapGenRecipe_Free(r);\n"
        b"            return MAPGEN_RECIPE_ERR_UNRESOLVED;\n"
        b"        }\n",
        b"        if (false) {\n"
        b"            MapGenRecipe_Free(r);\n"
        b"            return MAPGEN_RECIPE_ERR_UNRESOLVED;\n"
        b"        }\n",
        "and one whose control was never resolved",
    ),
    (
        "a-file-may-carry-any-weight",
        SRC,
        b"        if (r->snapshots[i].weight < 1u || r->snapshots[i].weight > 100u) {\n",
        b"        if (false) {\n",
        "and one whose snapshot weight is out of range",
    ),

    # --- what the builder must refuse ---------------------------------------
    (
        "an-unresolved-control-may-be-stored",
        SRC,
        b"    if (resolved == MAPGEN_RECIPE_AUTO)\n"
        b"        return MAPGEN_RECIPE_ERR_UNRESOLVED;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_UNRESOLVED;\n",
        "a control with an unresolved value is refused",
    ),
    (
        "a-control-may-be-overwritten",
        SRC,
        b"    for (uint32_t i = 0; i < b->num_controls; i++)\n"
        b"        if (!strcmp(b->controls[i].key, key))\n"
        b"            return MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL;\n",
        # Not `j < 0u`: an always-false comparison on an unsigned counter
        # fails the BUILD under -Werror rather than the check under test.
        b"    for (uint32_t i = b->num_controls; i < b->num_controls; i++)\n"
        b"        if (!strcmp(b->controls[i].key, key))\n"
        b"            return MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL;\n",
        "the same key twice is refused, not overwritten",
    ),
    (
        "the-same-snapshot-may-be-selected-twice",
        SRC,
        b"    for (uint32_t i = 0; i < b->num_snapshots; i++)\n"
        b"        if (!memcmp(b->snapshots[i].revision_uuid, snapshot->revision_uuid,\n"
        b"                    MAPGEN_RECIPE_UUID_BYTES))\n"
        b"            return MAPGEN_RECIPE_ERR_DUPLICATE_SNAPSHOT;\n",
        # Not `j < 0u`: an always-false comparison on an unsigned counter
        # fails the BUILD under -Werror rather than the check under test.
        b"    for (uint32_t i = b->num_snapshots; i < b->num_snapshots; i++)\n"
        b"        if (!memcmp(b->snapshots[i].revision_uuid, snapshot->revision_uuid,\n"
        b"                    MAPGEN_RECIPE_UUID_BYTES))\n"
        b"            return MAPGEN_RECIPE_ERR_DUPLICATE_SNAPSHOT;\n",
        "the same revision twice is refused",
    ),
    (
        "a-weight-outside-the-range-is-stored",
        SRC,
        b"    if (snapshot->weight < 1u || snapshot->weight > 100u)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_WEIGHT;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_WEIGHT;\n",
        "a zero weight is refused",
    ),
    (
        "a-recipe-may-have-no-source-at-all",
        SRC,
        b"    if (!b->num_snapshots && !b->donor[0])\n"
        b"        return MAPGEN_RECIPE_ERR_NO_SOURCE;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_NO_SOURCE;\n",
        "a recipe with no source at all is refused",
    ),

    # --- the resolved envelope ----------------------------------------------
    (
        "a-duel-may-resolve-to-a-crowd",
        SRC,
        b"    if (goal == MAPGEN_GOAL_DUEL && (players_min != 2u || players_max != 2u))\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_ENVELOPE;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_ENVELOPE;\n",
        "a duel that did not resolve to exactly two is refused",
    ),
    (
        "a-team-game-may-resolve-to-an-odd-envelope",
        SRC,
        b"    if (goal == MAPGEN_GOAL_TDM &&\n"
        b"        (players_min < 4u || (players_min & 1u) || (players_max & 1u)))\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_ENVELOPE;\n",
        b"    if (goal == MAPGEN_GOAL_TDM && players_min < 4u)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_ENVELOPE;\n",
        "and a team game with an odd envelope",
    ),
    (
        "the-attempt-limit-is-not-bounded",
        SRC,
        b"    if (attempt_limit < MAPGEN_RECIPE_MIN_ATTEMPTS ||\n"
        b"        attempt_limit > MAPGEN_RECIPE_MAX_ATTEMPTS)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_ATTEMPTS;\n",
        b"    if (false)\n"
        b"        return MAPGEN_RECIPE_ERR_BAD_ATTEMPTS;\n",
        "an attempt limit outside 1..256",
    ),

    # --- names that become filenames ----------------------------------------
    (
        "a-slug-may-contain-path-syntax",
        SRC,
        b"        const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';\n"
        b"        if (!ok)\n"
        b"            return false;\n"
        b"    }\n"
        b"    return true;\n"
        b"}\n"
        b"\n"
        b"/* A control key is an identifier",
        b"        const bool ok = c != 0;\n"
        b"        if (!ok)\n"
        b"            return false;\n"
        b"    }\n"
        b"    return true;\n"
        b"}\n"
        b"\n"
        b"/* A control key is an identifier",
        "every unsafe slug is refused, including `..` and drive syntax",
    ),
    (
        "a-display-name-may-carry-control-bytes",
        SRC,
        b"        if (c < 0x20 || c == 0x7F)\n"
        b"            return false;\n",
        b"        if (c == 0xFFu)\n"
        b"            return false;\n",
        "a display name with a control byte is refused",
    ),

    # --- canonical order ----------------------------------------------------
    (
        "the-controls-are-not-sorted",
        SRC,
        b"    if (b->num_controls)\n"
        b"        qsort(b->controls, b->num_controls, sizeof(*b->controls), compare_controls);\n",
        b"    if (b->num_controls)\n"
        b"        (void)compare_controls;\n",
        "to the very same bytes",
    ),
    (
        "the-snapshots-are-not-sorted",
        SRC,
        b"    qsort(b->snapshots, b->num_snapshots, sizeof(*b->snapshots), compare_snapshots);\n",
        b"    (void)compare_snapshots;\n",
        "to the very same bytes",
    ),

    # --- reuse ---------------------------------------------------------------
    (
        "an-unread-component-counts-as-a-match",
        SRC,
        b"    if (!hash_is_present(installed->compiler_build_sha256)) {\n"
        b"        if (which) *which = \"compiler\";\n"
        b"        return MAPGEN_REUSE_UNAVAILABLE_VERSION;\n"
        b"    }\n",
        b"    if (false) {\n"
        b"        if (which) *which = \"compiler\";\n"
        b"        return MAPGEN_REUSE_UNAVAILABLE_VERSION;\n"
        b"    }\n",
        "a component that could not be read is UNAVAILABLE, not a match",
    ),
    (
        "the-entity-schema-hash-is-not-compared",
        SRC,
        b"    if (pinned->entity_schema_version != installed->entity_schema_version ||\n"
        b"        memcmp(pinned->entity_schema_sha256, installed->entity_schema_sha256,\n"
        b"               MAPGEN_SHA256_BYTES)) {\n",
        b"    if (pinned->entity_schema_version != installed->entity_schema_version) {\n",
        "each of the four pinned components blocks a rerun when it changes",
    ),
    (
        "the-report-does-not-say-which-component",
        SRC,
        b"    if (memcmp(pinned->compiler_build_sha256, installed->compiler_build_sha256,\n"
        b"               MAPGEN_SHA256_BYTES)) {\n"
        b"        if (which) *which = \"compiler\";\n"
        b"        return MAPGEN_REUSE_NEEDS_MIGRATION;\n"
        b"    }\n",
        b"    if (memcmp(pinned->compiler_build_sha256, installed->compiler_build_sha256,\n"
        b"               MAPGEN_SHA256_BYTES)) {\n"
        b"        return MAPGEN_REUSE_NEEDS_MIGRATION;\n"
        b"    }\n",
        "and the report says which one",
    ),

    # --- what the generator is handed ---------------------------------------
    (
        "the-generator-is-handed-the-request",
        SRC,
        b"    return c ? c->resolved : fallback;\n",
        b"    return c ? c->requested : fallback;\n",
        "the generator is handed the resolved value",
    ),
]


def run_suite() -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(SUITE)], capture_output=True, text=True,
            cwd=str(REPO), timeout=1200,
        )
    except subprocess.TimeoutExpired:
        return 1, "  FAIL  the behavioural suite reported a result  -- timed out"
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 M4 recipe controlled RED")

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
