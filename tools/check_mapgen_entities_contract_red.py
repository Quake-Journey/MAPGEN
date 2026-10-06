#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_entities_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

The mutations that carry the most weight are the ones that produce a map you
could load and play for a while before noticing:

  * `an-exact-count-is-quietly-reduced` places as many as it can and reports
    success. Contract 13 calls an exact count a hard constraint, and a
    generator that treats it as a target is lying in its own report;

  * `a-spawn-is-buried-in-the-floor` is off by the player's own mins and puts
    everybody 24 units inside the ground;

  * `two-things-may-share-a-spot` produces a map where the first spawn of the
    match is a telefrag.

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

SUITE = SANDBOX.path("tools/check_mapgen_entities_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_entities.c")
HDR = SANDBOX.path("inc/common/mapgen_entities.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- contract 13 ---------------------------------------------------------
    (
        "an-exact-count-is-quietly-reduced",
        SRC,
        b"            if (!placed) {\n"
        b"                /* Contract 13: an exact count is a hard constraint. It is\n"
        b"                   refused with the control named, never quietly reduced. */\n"
        b"                if (conflict)\n"
        b"                    *conflict = ITEM_RULES[k].control;\n"
        b"                MapGenEntities_Free(e);\n"
        b"                return MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE;\n"
        b"            }\n",
        b"            if (!placed) {\n"
        b"                break;\n"
        b"            }\n",
        "a count the map cannot hold is refused",
    ),
    (
        "a-count-is-placed-one-short",
        SRC,
        b"        for (int32_t n = 0; n < wanted; n++) {\n",
        b"        for (int32_t n = 1; n < wanted; n++) {\n",
        "and five health",
    ),
    (
        "custom-zero-places-one-anyway",
        SRC,
        b"        if (wanted <= 0)\n"
        b"            continue;                       /* None is absolute */\n",
        b"        if (wanted < 0)\n"
        b"            continue;                       /* None is absolute */\n",
        # A count of zero falls through to a loop that runs zero times, so
        # nothing is placed either way and no run can tell. The static case is
        # what notices the guard being gone.
        "a resolved count of zero places nothing",
    ),
    (
        "a-control-nobody-set-is-placed-anyway",
        SRC,
        b"            MapGenRecipe_ResolvedValue(recipe, ITEM_RULES[k].control, 0);\n",
        b"            MapGenRecipe_ResolvedValue(recipe, ITEM_RULES[k].control, 1);\n",
        "and nothing was placed that was never asked for",
    ),
    (
        "the-conflict-is-not-named",
        SRC,
        b"                if (conflict)\n"
        b"                    *conflict = ITEM_RULES[k].control;\n",
        b"                if (false)\n"
        b"                    *conflict = ITEM_RULES[k].control;\n",
        "with the control named",
    ),
    (
        "a-refused-build-hands-back-what-it-managed",
        SRC,
        b"                MapGenEntities_Free(e);\n"
        b"                return MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE;\n"
        b"            }\n"
        b"            room_at = (room_at + 1) % rooms;\n",
        b"                *out = e;\n"
        b"                return MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE;\n"
        b"            }\n"
        b"            room_at = (room_at + 1) % rooms;\n",
        "and nothing handed back",
    ),

    # --- spawns ---------------------------------------------------------------
    (
        "a-spawn-is-buried-in-the-floor",
        HDR,
        b"#define MAPGEN_PLACEMENT_FLOOR_OFFSET    24\n",
        b"#define MAPGEN_PLACEMENT_FLOOR_OFFSET    0\n",
        "the feet offset is the engine's own hull",
    ),
    (
        "a-deathmatch-map-may-have-one-spawn",
        SRC,
        b"    else if (spawns < 2)\n"
        b"        spawns = 2;\n",
        b"    else if (spawns < 0)\n"
        b"        spawns = 2;\n",
        "a multiplayer map never gets fewer than two spawns",
    ),
    (
        "the-envelope-is-not-what-decides-the-spawn-count",
        SRC,
        b"    uint32_t spawns = MapGenRecipe_PlayersMax(recipe);\n",
        b"    uint32_t spawns = MapGenRecipe_PlayersMax(recipe) / 2u;\n",
        "there is one deathmatch spawn per player the envelope resolved to",
    ),
    (
        "a-deathmatch-map-gets-single-player-starts",
        SRC,
        b'                            ? "info_player_start" : "info_player_deathmatch";\n',
        b'                            ? "info_player_deathmatch" : "info_player_start";\n',
        "and no single-player start in a deathmatch map",
    ),
    (
        "every-spawn-goes-in-the-same-room",
        SRC,
        b"        room_at = (room_at + stride) % rooms;\n",
        b"        room_at = (room_at + 0u) % rooms;\n",
        "the spawns are spread over more than one room",
    ),

    # --- safety ---------------------------------------------------------------
    (
        "two-things-may-share-a-spot",
        SRC,
        b"        if (d < PLACEMENT_CLEARANCE)\n"
        b"            return true;\n",
        b"        if (d < 0)\n"
        b"            return true;\n",
        "no two placements share a spot, in any of them",
    ),
    (
        "a-placement-may-sit-in-a-wall",
        SRC,
        b"    const int32_t margin = MAPGEN_LAYOUT_HULL_WIDTH;\n",
        b"    const int32_t margin = -MAPGEN_LAYOUT_HULL_WIDTH;\n",
        "every entity is inside the room it says it is in",
    ),
    (
        "an-item-floats-above-the-floor",
        HDR,
        b"#define MAPGEN_PLACEMENT_ITEM_OFFSET     16\n",
        b"#define MAPGEN_PLACEMENT_ITEM_OFFSET     96\n",
        "and standing on that room's floor, not in it",
    ),

    # --- lights ----------------------------------------------------------------
    (
        "a-room-may-be-left-dark",
        SRC,
        b"        for (uint32_t room = 0; room < rooms; room++) {\n"
        b"            const mapgen_layout_box_t *box =\n"
        b"                &MapGenLayout_Room(layout, room)->space;\n"
        b"            int32_t z = box->maxs[2] - MAPGEN_LAYOUT_GRID * 2;\n",
        b"        for (uint32_t room = 1; room < rooms; room++) {\n"
        b"            const mapgen_layout_box_t *box =\n"
        b"                &MapGenLayout_Room(layout, room)->space;\n"
        b"            int32_t z = box->maxs[2] - MAPGEN_LAYOUT_GRID * 2;\n",
        "every room has a light",
    ),

    # --- determinism ------------------------------------------------------------
    (
        "the-placements-come-from-another-stages-stream",
        SRC,
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,\n"
        b"                        MAPGEN_RANDOM_ITEMS);\n",
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,\n"
        b"                        MAPGEN_RANDOM_SPAWNS);\n",
        "the placement stream is the item stream",
    ),

    # --- refusals ----------------------------------------------------------------
    (
        "a-refused-build-leaves-entities-behind",
        SRC,
        b"    if (out)\n"
        b"        *out = NULL;\n"
        b"    if (!layout || !topology || !model || !recipe || !out)\n"
        b"        return MAPGEN_ENTITIES_ERR_ARGS;\n",
        b"    if (!layout || !topology || !model || !recipe || !out)\n"
        b"        return MAPGEN_ENTITIES_ERR_ARGS;\n"
        b"    if (out)\n"
        b"        *out = NULL;\n",
        "a missing layout is refused rather than dereferenced",
    ),

    # --- the item table -----------------------------------------------------------
    (
        "an-item-row-loses-its-classname",
        SRC,
        b'    { "item_quad",             "item_quad" },\n',
        b'    { "item_quad",             NULL },\n',
        "every item row has both a control and a classname",
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
    print("=== MAPGEN-1 M4 entity placement controlled RED")

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
