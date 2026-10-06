#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_layout_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

The mutations that carry the most weight are the ones that still produce a
map:

  * `a-passage-runs-down-the-middle-of-a-row` takes the lane routing away and
    runs a passage straight between two room centres. Every map it makes is
    connected and looks right, and some of them have a corridor punched
    through a room nobody planned to connect;

  * `the-junction-count-is-always-zero` keeps every box exactly where it was
    and only stops counting. The number would be reported as "no unplanned
    connectivity" while the map has plenty;

  * `rooms-may-be-half-a-unit-off-the-grid` produces coordinates a compiler
    still accepts, and a map whose reproducibility depends on how the
    arithmetic rounded.

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

SUITE = SANDBOX.path("tools/check_mapgen_layout_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_layout.c")
HDR = SANDBOX.path("inc/common/mapgen_layout.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the lane argument ---------------------------------------------------
    (
        "a-passage-runs-down-the-middle-of-a-row",
        SRC,
        b"        const int32_t lane_y = from->cell[1] * MAPGEN_LAYOUT_CELL\n"
        b"            + ((to->cell[1] >= from->cell[1]) ? MAPGEN_LAYOUT_CELL / 2\n"
        b"                                              : -MAPGEN_LAYOUT_CELL / 2);\n",
        b"        const int32_t lane_y = from->cell[1] * MAPGEN_LAYOUT_CELL;\n",
        # The module NOTICES this - by refusing the embedding, which is the
        # breach check doing its job. A refused layout never reaches the case
        # that inspects a successful one, so the case that goes red is the
        # embed rate.
        "thirty-two attempts all embed",
    ),
    (
        "a-passage-runs-down-the-middle-of-a-column",
        SRC,
        b"        const int32_t lane_x = to->cell[0] * MAPGEN_LAYOUT_CELL\n"
        b"            + ((from->cell[0] >= to->cell[0]) ? MAPGEN_LAYOUT_CELL / 2\n"
        b"                                              : -MAPGEN_LAYOUT_CELL / 2);\n",
        b"        const int32_t lane_x = to->cell[0] * MAPGEN_LAYOUT_CELL;\n",
        "thirty-two attempts all embed",
    ),
    (
        "the-room-breach-check-is-gone",
        SRC,
        b"                if (boxes_overlap(&l->passages[p].segments[s], &l->rooms[i].space)) {\n"
        b"                    MapGenLayout_Free(l);\n"
        b"                    return MAPGEN_LAYOUT_ERR_INTERSECTION;\n"
        b"                }\n",
        b"                if (false) {\n"
        b"                    MapGenLayout_Free(l);\n"
        b"                    return MAPGEN_LAYOUT_ERR_INTERSECTION;\n"
        b"                }\n",
        # With lane routing intact nothing breaches a room, so removing the
        # check changes no RESULT. What it removes is the proof, and the
        # static case has to look at the comparison rather than at the error
        # constant the mutation leaves sitting there.
        "a passage breaching an unrelated room is still refused",
    ),

    # --- the junction count --------------------------------------------------
    (
        "the-junction-count-is-always-zero",
        SRC,
        b"                    if (boxes_overlap(&l->passages[p].segments[s],\n"
        b"                                      &l->passages[q].segments[t]))\n"
        b"                        l->num_junctions++;\n",
        b"                    if (false)\n"
        b"                        l->num_junctions++;\n",
        "and every crossing between unrelated passages is counted",
    ),
    (
        "passages-sharing-a-room-are-counted-as-junctions",
        SRC,
        b"                if (share_room)\n"
        b"                    continue;\n",
        b"                if (!share_room)\n"
        b"                    continue;\n",
        "and every crossing between unrelated passages is counted",
    ),

    # --- the grid ------------------------------------------------------------
    (
        "rooms-may-be-half-a-unit-off-the-grid",
        SRC,
        b"        room->space.mins[0] = snap(centre_x - size / 2);\n",
        b"        room->space.mins[0] = centre_x - size / 2 + 1;\n",
        "every room corner is on the 16-unit grid",
    ),
    (
        "passages-may-be-off-the-grid",
        SRC,
        b"            seg.mins[1] = snap(lane_y - half);\n"
        b"            seg.maxs[1] = seg.mins[1] + corridor_width;\n"
        b"            seg.mins[2] = from->space.mins[2];\n",
        b"            seg.mins[1] = lane_y - half + 1;\n"
        b"            seg.maxs[1] = seg.mins[1] + corridor_width;\n"
        b"            seg.mins[2] = from->space.mins[2];\n",
        "every passage segment is on the grid too",
    ),
    (
        "the-grid-is-coarser-below-the-origin",
        SRC,
        b"    return (v >= 0 ? (v / g) : ((v - g + 1) / g)) * g;\n",
        b"    return (v / g) * g;\n",
        "and the snap works the same on both sides of the origin",
    ),

    # --- rooms ---------------------------------------------------------------
    (
        "two-rooms-may-share-a-cell",
        SRC,
        b"                    if (cell_taken(slots, nodes, cx, cy))\n"
        b"                        continue;\n",
        # `cell_taken` stays called: `if (false)` leaves it unused and fails
        # the BUILD under -Werror rather than the check under test.
        b"                    if (cell_taken(slots, nodes, cx, cy) && false)\n"
        b"                        continue;\n",
        # Two rooms in one cell overlap, and the module refuses the layout for
        # it - so the case that goes red is the embed rate, not the case that
        # inspects a layout it never gets to see. With rooms this large every
        # attempt is refused, so the run stops at the FIRST embedding rather
        # than reaching the thirty-two-attempt sweep further down.
        "an embedding is found inside contract 16's 32 attempts",
    ),
    (
        "a-room-may-be-too-small-to-fight-in",
        SRC,
        # The DEPTH clamp, not the size one: `size` is built up from MIN_ROOM
        # and can never fall below it, so its clamp is unreachable and
        # mutating it proves nothing. Depth is size plus a draw that can be
        # negative, so its clamp is the one holding the floor up.
        b"        if (depth < MAPGEN_LAYOUT_MIN_ROOM)\n"
        b"            depth = MAPGEN_LAYOUT_MIN_ROOM;\n",
        b"        if (depth < 0)\n"
        b"            depth = MAPGEN_LAYOUT_MIN_ROOM;\n",
        "and big enough to hold a fight, not just a player",
    ),
    (
        "a-corridor-may-be-narrower-than-the-player",
        HDR,
        b"#define MAPGEN_LAYOUT_CORRIDOR_WIDTH  128\n",
        b"#define MAPGEN_LAYOUT_CORRIDOR_WIDTH  16\n",
        "and admits a standing player in all three axes",
    ),
    (
        "the-world-is-smaller-than-the-map",
        HDR,
        # Removing the check proves nothing: the cell bound already keeps every
        # room inside, so the check never fires. Shrinking the world does fire
        # it, which is what proves it is load-bearing.
        b"#define MAPGEN_LAYOUT_WORLD_LIMIT     4096\n",
        b"#define MAPGEN_LAYOUT_WORLD_LIMIT     1024\n",
        "an embedding is found inside contract 16's 32 attempts",
    ),

    # --- passages ------------------------------------------------------------
    (
        "a-planned-route-may-get-no-passage",
        SRC,
        b"    for (uint32_t r = 0; r < routes; r++) {\n",
        b"    for (uint32_t r = 0; r + 1 < routes; r++) {\n",
        "there is one passage per planned route",
    ),
    (
        "a-passage-need-not-reach-the-second-room",
        SRC,
        b"            seg.mins[0] = snap((lane_x < to_x ? lane_x : to_x) - half);\n"
        b"            seg.maxs[0] = snap((lane_x < to_x ? to_x : lane_x) + half);\n",
        # `to_x` stays used: dropping it leaves the local unused and fails
        # the BUILD under -Werror rather than the check under test.
        b"            seg.mins[0] = snap((lane_x < to_x ? lane_x : to_x) - half);\n"
        b"            seg.maxs[0] = seg.mins[0] + MAPGEN_LAYOUT_CORRIDOR_WIDTH;\n",
        "every passage reaches both of the rooms it connects",
    ),
    (
        "the-bounds-forget-the-passages",
        SRC,
        b"            box_grow(&l->bounds, &p->segments[s]);\n",
        b"            (void)0;\n",
        "the reported bounds contain everything",
    ),

    # --- refusals ------------------------------------------------------------
    (
        "a-refused-build-leaves-a-layout-behind",
        SRC,
        b"    if (out)\n"
        b"        *out = NULL;\n"
        b"    if (!topology || !recipe || !out)\n"
        b"        return MAPGEN_LAYOUT_ERR_ARGS;\n",
        b"    if (!topology || !recipe || !out)\n"
        b"        return MAPGEN_LAYOUT_ERR_ARGS;\n"
        b"    *out = NULL;\n",
        "a missing topology is refused rather than dereferenced",
    ),

    # --- determinism ---------------------------------------------------------
    (
        "the-attempt-index-is-ignored",
        SRC,
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,\n"
        b"                        MAPGEN_RANDOM_BRUSHES);\n",
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,\n"
        b"                        MAPGEN_RANDOM_TOPOLOGY);\n",
        "the geometry stream is the brush stream",
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
    print("=== MAPGEN-1 M4 layout controlled RED")

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
