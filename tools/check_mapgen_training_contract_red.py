#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_training_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Two mutations carry the weight:

  * `the-duplicate-is-decided-on-arrival` puts back the defect the order case
    found. Five pairs of byte-identical maps ship in the corpus, and whichever
    arrived first used to become the accepted one - so the same maps offered
    in two orders produced two different payloads;

  * `sources-are-serialized-in-arrival-order` breaks the canonical order
    outright, which is the same failure wearing its own name.

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

SUITE = SANDBOX.path("tools/check_mapgen_training_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_training.c")
HDR = SANDBOX.path("inc/common/mapgen_training.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- order independence ------------------------------------------------
    (
        # The "have I seen this hash already" test consults the ARRIVAL array,
        # so which of two byte-identical maps wins depends on who finished
        # first again. An earlier attempt only reassigned a status the next
        # loop overwrote - an equivalent mutant that proved nothing.
        "the-duplicate-is-decided-on-arrival",
        SRC,
        b"            if (copy[j].identity.status == MAPGEN_SOURCE_ACCEPTED &&\n"
        b"                !memcmp(copy[j].identity.sha256, copy[i].identity.sha256,\n",
        b"            if (t->sources[j].identity.status != MAPGEN_SOURCE_REJECTED &&\n"
        b"                !memcmp(t->sources[j].identity.sha256, copy[i].identity.sha256,\n",
        "the whole corpus trains identically in either order",
    ),
    (
        "sources-are-serialized-in-arrival-order",
        SRC,
        b"    qsort(copy, t->num_sources, sizeof(source_t), compare_sources);\n",
        b"    (void)compare_sources;\n",
        "sources are serialized in SHA-256 order",
    ),
    (
        "the-canonical-order-ignores-the-qpath",
        SRC,
        b"    return strcmp(x->identity.qpath, y->identity.qpath);\n",
        b"    return 0;\n",
        "the canonical order is (SHA-256, provider, qpath)",
    ),

    # --- the duplicate rule ------------------------------------------------
    (
        "duplicates-are-accepted-twice",
        SRC,
        b"                copy[i].identity.status = MAPGEN_SOURCE_DUPLICATE;\n",
        b"                copy[i].identity.status = MAPGEN_SOURCE_ACCEPTED;\n",
        "exactly the five byte-identical pairs were deduplicated",
    ),
    (
        "a-duplicate-is-matched-on-the-first-half-of-the-hash",
        SRC,
        # A shorter anchor than the case above, so the two do not collide.
        b"                        MAPGEN_SHA256_BYTES)) {\n",
        b"                        1)) {\n",
        "exactly the five byte-identical pairs were deduplicated",
    ),
    (
        "a-rejected-source-can-become-a-duplicate",
        SRC,
        b"        if (copy[i].identity.status == MAPGEN_SOURCE_REJECTED)\n"
        b"            continue;               /* a rejection is not a duplicate */\n",
        b"        if (false)\n"
        b"            continue;\n",
        "a rejected source is never reclassified as a duplicate",
    ),

    # --- counts and warnings ------------------------------------------------
    (
        "the-counts-are-incremented-on-arrival",
        SRC,
        b"static void tally(const mapgen_training_t *t, uint32_t *accepted,\n",
        b"static void tally_unused(const mapgen_training_t *t, uint32_t *accepted,\n",
        "the counts are derived, not incremented on arrival",
    ),
    (
        "low-diversity-never-fires",
        HDR,
        b"#define MAPGEN_TRAINING_LOW_DIVERSITY   4u\n",
        b"#define MAPGEN_TRAINING_LOW_DIVERSITY   1u\n",
        "and carries the low-diversity warning",
    ),
    (
        "low-diversity-always-fires",
        HDR,
        b"#define MAPGEN_TRAINING_LOW_DIVERSITY   4u\n",
        b"#define MAPGEN_TRAINING_LOW_DIVERSITY   1000u\n",
        "a 127-source snapshot is not low diversity",
    ),
    (
        "the-warning-is-a-counter-and-nothing-else",
        SRC,
        b"        sink_str(&s, MapGenTraining_LowDiversity(t)\n"
        b"                 ? \"few_sources_low_confidence\" : \"none\");\n",
        b"        sink_str(&s, \"none\");\n",
        "the warning is in the QUALITY chunk, not only in a counter",
    ),
    (
        "quality-does-not-account-for-every-source",
        SRC,
        b"        row_i64(&s, \"duplicates\", duplicates);\n",
        b"        row_i64(&s, \"duplicates\", 0);\n",
        "QUALITY accounts for every source",
    ),

    # --- the chunk payloads -------------------------------------------------
    (
        "an-empty-corpus-produces-a-snapshot",
        SRC,
        b"    if (!MapGenTraining_NumAccepted(t))\n"
        b"        return MAPGEN_TRAINING_ERR_NO_SOURCES;\n",
        b"    if (false)\n"
        b"        return MAPGEN_TRAINING_ERR_NO_SOURCES;\n",
        "a corpus with nothing in it is refused, not written",
    ),
    (
        "duplicates-are-dropped-from-the-record",
        SRC,
        b"        for (uint32_t i = 0; i < t->num_sources && sorted; i++) {\n"
        b"            const mapgen_training_source_t *id = &sorted[i].identity;\n",
        b"        for (uint32_t i = 0; i < t->num_sources && sorted; i++) {\n"
        b"            const mapgen_training_source_t *id = &sorted[i].identity;\n"
        b"            if (id->status == MAPGEN_SOURCE_DUPLICATE) continue;\n",
        "every source is recorded, duplicates included",
    ),
    (
        "the-material-list-is-not-sorted",
        SRC,
        b"                qsort(materials, t->num_materials, sizeof(material_t),\n"
        b"                      compare_materials);\n",
        b"                (void)compare_materials;\n",
        "the material allowlist is exact and sorted",
    ),
    (
        "the-median-is-not-the-middle",
        SRC,
        b"    agg.median = scratch[n / 2];\n",
        b"    agg.median = scratch[0] ? scratch[0] - 1 : scratch[n - 1];\n",
        "every statistic is min <= median <= max",
    ),
    (
        "the-mean-divides-by-the-wrong-population",
        SRC,
        b"            sink_i64(&s, accepted ? (int64_t)(agg.total / accepted) : 0);\n",
        b"            sink_i64(&s, accepted ? (int64_t)(agg.total / accepted + 1u) : 0);\n",
        "each statistic is exactly what the per-source rows say it is",
    ),
    (
        "duplicates-contribute-to-the-statistics",
        SRC,
        b"        if (sorted[i].identity.status != MAPGEN_SOURCE_ACCEPTED || !sorted[i].has_features)\n",
        b"        if (!sorted[i].has_features)\n",
        "each statistic is exactly what the per-source rows say it is",
    ),

    # --- hygiene ------------------------------------------------------------
    (
        "a-qpath-is-not-sanitized",
        SRC,
        b"        dst[i] = ((unsigned char)src[i] < 0x20 || src[i] == '\\n') ? '?' : src[i];\n",
        b"        dst[i] = src[i];\n",
        "a qpath is sanitized once, where it enters",
    ),
    (
        "training-state-at-file-scope",
        SRC,
        b"static int compare_materials(const void *a, const void *b)\n{\n",
        b"static uint32_t g_material_comparisons;\n\n"
        b"static int compare_materials(const void *a, const void *b)\n{\n"
        b"    g_material_comparisons++;\n",
        "no mutable file-scope state",
    ),
    (
        "the-accessor-returns-per-thread-scratch",
        SRC,
        b"    if (!t || !out || index >= t->num_sources)\n",
        b"    static _Thread_local uint32_t unused_scratch;\n"
        b"    unused_scratch = index;\n"
        b"    if (!t || !out || index >= t->num_sources)\n",
        "no per-thread scratch either",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=5400,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 Training aggregation controlled RED")

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
