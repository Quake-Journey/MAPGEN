#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_topology_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

The mutations that carry the most weight are the ones that still produce a
graph:

  * `none-is-a-small-weight-not-a-prohibition` turns contract 14's absolute
    None into "rarely". Every graph it builds is connected and looks right;
    only a user who asked for no teleporters gets teleporters;

  * `the-skeleton-may-use-a-one-way-kind` keeps the graph connected in the
    undirected sense and breaks it in the directed one - a route you can fall
    down and not climb out of. A connectivity check that ignored direction
    would pass;

  * `the-area-count-is-the-samples-region-count` produces a perfectly
    reasonable-looking map with forty small boxes in it, because it reads the
    sample's `regions` statistic - connected components of the stance graph,
    63 of them in aerowalk - as though it were a room count. That was the
    real defect, and it is what "corridors instead of arenas" was made of.

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

SUITE = SANDBOX.path("tools/check_mapgen_topology_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_topology.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- contract 14: None is absolute --------------------------------------
    (
        "none-is-a-small-weight-not-a-prohibition",
        SRC,
        b"        if (level <= 0) {\n"
        b"            p->weight[k] = 0;               /* None is absolute */\n"
        b"            continue;\n"
        b"        }\n",
        # Not `level < 0`: that lets None fall through to the provenance
        # check and turns the baseline into a refusal, which tests nothing.
        # This keeps every other rule intact and makes None mean "rarely".
        b"        if (level <= 0) {\n"
        b"            p->weight[k] = 1;               /* None is absolute */\n"
        b"            continue;\n"
        b"        }\n",
        "None emits zero routes of that kind, for every control in turn",
    ),
    # --- contract 15: provenance --------------------------------------------
    (
        "an-unlearned-motif-is-emitted-anyway",
        SRC,
        b"        if (rule->role && !MapGenMix_RoleIsLearned(model, rule->role)) {\n",
        # `model` stays used: `if (false)` leaves it unused and fails the BUILD
        # under -Werror rather than the check under test.
        b"        if (rule->role && !MapGenMix_RoleIsLearned(model, rule->role)\n"
        b"            && false) {\n",
        "asking for a motif the corpus never learned is refused, every time",
    ),
    (
        "the-conflict-is-not-named",
        SRC,
        b"            if (conflict)\n"
        b"                *conflict = rule->control;\n",
        b"            if (false)\n"
        b"                *conflict = rule->control;\n",
        "and the conflict is named exactly",
    ),
    (
        "a-motif-nobody-asked-for-is-reported-as-a-conflict",
        SRC,
        b"        const int32_t level = MapGenRecipe_ResolvedValue(recipe, rule->control, 2);\n"
        b"        if (level <= 0) {\n"
        b"            p->weight[k] = 0;               /* None is absolute */\n"
        b"            continue;\n"
        b"        }\n"
        b"\n"
        b"        if (rule->role && !MapGenMix_RoleIsLearned(model, rule->role)) {\n",
        # The order matters: checking provenance before None turns "the corpus
        # has no trains and nobody wanted any" into a refusal.
        b"        const int32_t level = MapGenRecipe_ResolvedValue(recipe, rule->control, 2);\n"
        b"\n"
        b"        if (rule->role && !MapGenMix_RoleIsLearned(model, rule->role)) {\n",
        "a graph is built from a real mixed model",
    ),

    # --- connectivity --------------------------------------------------------
    (
        "the-skeleton-may-use-a-one-way-kind",
        SRC,
        b"            if (!palette.weight[k] || ROUTE_RULES[k].one_way)\n"
        b"                continue;\n",
        b"            if (!palette.weight[k])\n"
        b"                continue;\n",
        "and reachable both ways once direction is respected",
    ),
    (
        "the-skeleton-does-not-span",
        SRC,
        b"    for (uint32_t i = 1; i < nodes; i++) {\n"
        b"        const uint32_t j = MapGenRandom_Below(&rng, i);\n",
        b"    for (uint32_t i = 1; i + 1 < nodes; i++) {\n"
        b"        const uint32_t j = MapGenRandom_Below(&rng, i);\n",
        "every node is reachable from every other, ignoring direction",
    ),
    (
        "a-node-may-connect-to-itself",
        SRC,
        b"        if (a == b || route_exists(t, a, b))\n"
        b"            continue;\n"
        b"        const int32_t delta = (int32_t)t->nodes[b].band - (int32_t)t->nodes[a].band;\n"
        b"        if (!kinds_for_delta(&palette, delta, true, weights))\n",
        b"        if (route_exists(t, a, b))\n"
        b"            continue;\n"
        b"        const int32_t delta = (int32_t)t->nodes[b].band - (int32_t)t->nodes[a].band;\n"
        b"        if (!kinds_for_delta(&palette, delta, true, weights))\n",
        "no node connects to itself, in any of them",
    ),
    (
        "a-pair-may-be-connected-twice",
        SRC,
        b"        const mapgen_topology_route_t *e = &t->routes[i];\n"
        b"        if ((e->from == a && e->to == b) || (e->from == b && e->to == a))\n"
        b"            return true;\n",
        b"        const mapgen_topology_route_t *e = &t->routes[i];\n"
        b"        if (e->from == a && e->to == b && e->kind == 0xFFFFFFFFu)\n"
        b"            return true;\n",
        "and no pair is connected twice, in any of them",
    ),

    # --- redundancy ----------------------------------------------------------
    (
        "there-is-only-one-way-around",
        SRC,
        b"    const uint32_t loops = loop_target(MapGenRecipe_Goal(recipe), nodes);\n",
        b"    const uint32_t loops = 0u * loop_target(MapGenRecipe_Goal(recipe), nodes);\n",
        "there is more than one way around",
    ),
    (
        "every-goal-gets-the-same-redundancy",
        SRC,
        b"    case MAPGEN_GOAL_SINGLE_PLAYER:\n"
        b"        return 1;                           /* one optional branch at least  */\n"
        b"    case MAPGEN_GOAL_DUEL:\n"
        b"        return nodes / 3u + 1u;             /* duel control loops            */\n",
        b"    case MAPGEN_GOAL_SINGLE_PLAYER:\n"
        b"        return nodes / 4u + 1u;\n"
        b"    case MAPGEN_GOAL_DUEL:\n"
        b"        return nodes / 4u + 1u;\n",
        "a duel graph has more loops than a single-player one",
    ),

    # --- contract 19: the size is measured ----------------------------------
    (
        "the-area-count-is-the-samples-region-count",
        SRC,
        b"    const uint32_t nodes = clamp_u32(AREAS[scale >= 0 && scale < 4 ? scale : 1],\n"
        b"                                     MAPGEN_TOPOLOGY_MIN_NODES,\n"
        b"                                     MAPGEN_TOPOLOGY_MAX_NODES);\n",
        # aerowalk reports 63 regions and campgrounds 98. Every graph this
        # builds is connected and valid; it is just made of forty small boxes.
        b"    (void)AREAS;\n"
        b"    (void)scale;\n"
        b"    const uint32_t nodes = clamp_u32(\n"
        b"        MapGenMix_SampleValue(model, sample, MAPGEN_MIX_STAT_REGIONS),\n"
        b"                                     MAPGEN_TOPOLOGY_MIN_NODES,\n"
        b"                                     MAPGEN_TOPOLOGY_MAX_NODES);\n",
        # The behavioural case notices too, but only because a map in THIS
        # corpus reports more than twenty-five regions. The static one reads
        # the source and notices either way.
        "and the region count is NOT read as a room count",
    ),
    (
        "map-scale-does-not-scale",
        SRC,
        b"    static const uint32_t AREAS[4] = { 6, 10, 14, 18 };\n",
        b"    static const uint32_t AREAS[4] = { 10, 10, 10, 10 };\n",
        "and rises with the scale",
    ),
    (
        "the-sample-it-used-is-not-recorded",
        SRC,
        b"    if (source)\n"
        b"        memcpy(t->sample, source, sizeof(t->sample) - 1);\n",
        # Not `if (!source)`: that is a memcpy from NULL, which the build
        # rejects under -Wnonnull before the check under test can run.
        b"    if (source)\n"
        b"        t->sample[0] = '\\0';\n",
        "the graph records which learned map it was sized from",
    ),

    # --- verticality ---------------------------------------------------------
    (
        "verticality-none-still-builds-upstairs",
        SRC,
        b"    if (verticality <= 0)\n"
        b"        bands = 1;\n",
        b"    if (verticality < 0)\n"
        b"        bands = 1;\n",
        "verticality None puts every region on one level",
    ),

    # --- determinism ---------------------------------------------------------
    (
        "the-attempt-index-is-ignored",
        SRC,
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,\n"
        b"                        MAPGEN_RANDOM_TOPOLOGY);\n",
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt & 0u,\n"
        b"                        MAPGEN_RANDOM_TOPOLOGY);\n",
        "and a different attempt gives a different one",
    ),
    (
        "the-seed-is-ignored",
        SRC,
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,\n"
        b"                        MAPGEN_RANDOM_TOPOLOGY);\n",
        b"    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe) & 0u, attempt,\n"
        b"                        MAPGEN_RANDOM_TOPOLOGY);\n",
        "a different seed gives a different graph",
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
    print("=== MAPGEN-1 M4 topology controlled RED")

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
