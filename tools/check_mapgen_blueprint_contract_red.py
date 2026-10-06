#!/usr/bin/env python3
"""Controlled RED for the spatial blueprint.

Codex, 2026-09-01, gate R3: "Demonstrate controlled RED by independently
dropping a portal, flattening Z, removing XY overlap, and collapsing motif
identity." Those four are here by name, with three more for the properties the
segmentation rests on.

The point of each is that it produces a blueprint that still LOOKS like one -
volumes with sensible bounds, portals joining real volumes, ids dense and in
order - and is wrong about the architecture in exactly one way. A fidelity
control built on a blueprint that quietly loses a portal would report 100 while
handing the player a wall.

Every mutation runs in a disposable copy under the task's own temp root
(R1), so a killed process cannot leave one behind. Exit 0 = every mutation
detected on its OWN named case, every file restored byte-identically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mapgen_red_sandbox import Sandbox  # noqa: E402
from mapgen_red_support import resolve_anchor, sha256  # noqa: E402

SANDBOX = Sandbox(REPO, Path(__file__).stem)

SUITE = SANDBOX.path("tools/check_mapgen_blueprint_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_blueprint.c")
HDR = SANDBOX.path("inc/common/mapgen_blueprint.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the four the directive names ----------------------------------------
    (
        "a-portal-may-be-dropped",
        SRC,
        b"        const uint32_t a = owner[edge->from], b = owner[edge->to];\n"
        b"        if (a == b)\n"
        b"            continue;\n"
        b"        const mapgen_space_node_t *na = MapGenSpace_Node(space, edge->from);\n",
        # One traversal kind stops producing portals. Every remaining portal is
        # valid, the ids stay dense, and the map has lost a way through.
        b"        const uint32_t a = owner[edge->from], b = owner[edge->to];\n"
        b"        if (a == b || edge->kind == MAPGEN_EDGE_STEP)\n"
        b"            continue;\n"
        b"        const mapgen_space_node_t *na = MapGenSpace_Node(space, edge->from);\n",
        "q2dm1: the two implementations agree exactly",
    ),
    (
        "the-vertical-axis-is-flattened",
        SRC,
        b"        for (int axis = 0; axis < 3; axis++) {\n"
        b"            vol->mins[axis] = snap_down(vol->mins[axis]);\n"
        b"            vol->maxs[axis] = snap_down(vol->maxs[axis]) + MAPGEN_BLUEPRINT_BASIS;\n"
        b"        }\n",
        # Z collapses to a single band: every volume claims the same height, so
        # above/below vanishes and a stacked map reads as a flat one.
        b"        for (int axis = 0; axis < 3; axis++) {\n"
        b"            vol->mins[axis] = snap_down(vol->mins[axis]);\n"
        b"            vol->maxs[axis] = snap_down(vol->maxs[axis]) + MAPGEN_BLUEPRINT_BASIS;\n"
        b"        }\n"
        b"        vol->mins[2] = 0;\n"
        b"        vol->maxs[2] = MAPGEN_BLUEPRINT_BASIS;\n",
        "q2dm1: the two implementations agree exactly",
    ),
    (
        "xy-overlap-is-never-recorded",
        SRC,
        b"            const bool overlap_xy =\n"
        b"                va->mins[0] < vb->maxs[0] && va->maxs[0] > vb->mins[0]\n"
        b"                && va->mins[1] < vb->maxs[1] && va->maxs[1] > vb->mins[1];\n",
        # Two volumes stacked over one another stop being related at all, which
        # is the relation a fidelity control needs to preserve stacking.
        b"            const bool overlap_xy = false\n"
        b"                && va->mins[0] < vb->maxs[0] && va->maxs[0] > vb->mins[0]\n"
        b"                && va->mins[1] < vb->maxs[1] && va->maxs[1] > vb->mins[1];\n",
        "q2dm1: the two implementations agree exactly",
    ),
    (
        "volume-identity-collapses",
        SRC,
        b"    for (uint32_t i = 0; i < nodes; i++)\n"
        b"        klass[i] = degree[i] <= MAPGEN_BLUEPRINT_THIN_DEGREE\n"
        b"                 ? MAPGEN_VOLUME_PASSAGE : MAPGEN_VOLUME_HALL;\n",
        # Everything is one class, so a hall and the corridor leaving it merge
        # into a single blob and the map loses every landmark it had.
        b"    for (uint32_t i = 0; i < nodes; i++)\n"
        b"        klass[i] = MAPGEN_VOLUME_HALL;\n",
        "q2dm1: the two implementations agree exactly",
    ),

    # --- what the segmentation rests on --------------------------------------
    (
        "a-jump-merges-two-volumes-into-one",
        SRC,
        b"    return kind == MAPGEN_EDGE_WALK || kind == MAPGEN_EDGE_STEP;\n",
        # A ledge you can only jump to stops being its own volume.
        b"    return kind != MAPGEN_EDGE_SWIM;\n",
        "only walk and step edges merge two stances into one volume",
    ),
    (
        "the-wall-ring-is-not-folded-back",
        SRC,
        b"    memcpy(klass, grown, nodes);\n",
        # The dilation still runs; its result is simply never adopted, so every
        # hall goes back to being ringed with slivers. Disabling one of the two
        # directions proved nothing - the other one covered it.
        b"    (void)grown;\n",
        "q2dm1: the two implementations agree exactly",
    ),
    (
        "a-volume-need-not-sit-on-the-basis",
        HDR,
        b"#define MAPGEN_BLUEPRINT_BASIS        16\n",
        # 24 is not a divisor of the layout grid, so a preserved volume would
        # land between the cells it has to be rebuilt on.
        b"#define MAPGEN_BLUEPRINT_BASIS        24\n",
        "the basis is the layout grid",
    ),
    (
        "the-canonical-form-depends-on-edge-order",
        SRC,
        b"    for (uint32_t i = 1; i < bp->num_portals; i++) {\n",
        # The loop never runs, so the portals keep whatever order the
        # stance graph handed them out in. Done by the BOUND: touching the
        # predicate trips -Wparentheses and a constant comparison trips
        # -Wtype-limits, and either fails the BUILD rather than the case.
        b"    for (uint32_t i = bp->num_portals; i < bp->num_portals; i++) {\n",
        "q2dm1: the two implementations agree exactly",
    ),
]


def run_suite() -> tuple[int, str]:
    result = subprocess.run([sys.executable, str(SUITE)],
                            capture_output=True, text=True, timeout=7200)
    return result.returncode, result.stdout + result.stderr


def main() -> int:
    print("=== MAPGEN-1 R3 blueprint controlled RED")

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  baseline is not GREEN; refusing to mutate anything")
        print(out[-3000:])
        return 1
    print("  OK    baseline GREEN")

    failures = 0
    for name, path, anchor, replacement, expected_fail in CASES:
        original = path.read_bytes()
        original_hash = sha256(path)

        anchor, replacement, occurrences = resolve_anchor(original, anchor, replacement)
        if occurrences != 1:
            print(f"  FAIL  {name}: anchor occurs {occurrences} times in "
                  f"{path.name} (need exactly 1); the matrix is invalid, not skipped")
            failures += 1
            continue

        mutated = original.replace(anchor, replacement, 1)
        if mutated == original:
            print(f"  FAIL  {name}: mutation did not change {path.name}")
            failures += 1
            continue

        try:
            path.write_bytes(mutated)
            rc, out = run_suite()
            if rc == 0:
                print(f"  FAIL  {name}: suite stayed GREEN under the mutation")
                failures += 1
            elif f"FAIL  {expected_fail}" not in out:
                shown = [ln.strip() for ln in out.splitlines()
                         if ln.startswith("  FAIL")][:3]
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
        failures += 1
    else:
        print("  OK    restored GREEN")

    print(f"\n=== {len(CASES)} controlled-RED cases, {failures} failures")
    print("RESULT: " + ("PASS" if not failures else "FAIL"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
