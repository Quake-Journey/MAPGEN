#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_lineage_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Three mutations carry the weight:

  * `a-rename-may-change-what-was-learned` lets a Rename rewrite a learned
    chunk. Contract 8 makes Rename metadata-only, and the behavioural case
    compares all six non-META chunks byte for byte;

  * `a-derived-revision-forgets-its-parent` drops the parent payload hash, so a
    revision could no longer say what it came from - which is the whole point
    of a lineage;

  * `a-rebuild-does-not-reproduce` perturbs the derived payload, breaking the
    property that a Rebuild of the same sources under the same schema yields
    the same learned content.

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

SUITE = SANDBOX.path("tools/check_mapgen_lineage_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_lineage.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- copy-on-write ------------------------------------------------------
    (
        "a-rename-may-change-what-was-learned",
        SRC,
        b"        if (type != MAPGEN_CHUNK_META) {\n",
        b"        if (type != MAPGEN_CHUNK_META && type != MAPGEN_CHUNK_QUALITY) {\n",
        "every learned chunk survives a rename untouched",
    ),
    (
        "a-derived-revision-forgets-its-parent",
        SRC,
        b"    MapGenSnapshot_SetIdentity(b, h->lineage_uuid, revision, h->payload_sha256);\n"
        b"    MapGenSnapshot_SetProvenance(b, NULL, NULL, created_utc_ms,\n"
        b"                                 MapGenTraining_NumSources(training));\n",
        b"    MapGenSnapshot_SetIdentity(b, h->lineage_uuid, revision, NULL);\n"
        b"    MapGenSnapshot_SetProvenance(b, NULL, NULL, created_utc_ms,\n"
        b"                                 MapGenTraining_NumSources(training));\n",
        "and records the parent's payload hash",
    ),
    (
        "a-derived-revision-starts-a-new-lineage",
        SRC,
        b"    MapGenSnapshot_SetIdentity(b, h->lineage_uuid, revision, h->payload_sha256);\n"
        b"    MapGenSnapshot_SetProvenance(b, NULL, NULL, created_utc_ms,\n"
        b"                                 MapGenTraining_NumSources(training));\n",
        b"    MapGenSnapshot_SetIdentity(b, revision, revision, h->payload_sha256);\n"
        b"    MapGenSnapshot_SetProvenance(b, NULL, NULL, created_utc_ms,\n"
        b"                                 MapGenTraining_NumSources(training));\n",
        "the extension keeps the lineage",
    ),
    (
        "a-new-lineage-claims-a-parent",
        SRC,
        b"    MapGenSnapshot_SetIdentity(b, lineage, revision, NULL);\n",
        # A 32-byte compound literal, not `revision`: the parameter is
        # `const uint8_t[32]` and passing a 16-byte array fails the BUILD under
        # -Werror=array-parameter rather than the check under test.
        b"    MapGenSnapshot_SetIdentity(b, lineage, revision, (const uint8_t[32]){ 1 });\n",
        "a new lineage has no parent payload",
    ),
    (
        "a-revision-may-reuse-its-parents-identity",
        SRC,
        b"    if (!memcmp(h->revision_uuid, revision, MAPGEN_SNAPSHOT_UUID_BYTES))\n"
        b"        return MAPGEN_LINEAGE_ERR_SAME_REVISION;\n"
        b"\n"
        b"    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();\n"
        b"    if (!b)\n"
        b"        return MAPGEN_LINEAGE_ERR_MEMORY;\n"
        b"    if (MapGenTraining_FillSnapshot(training, b, compression) != MAPGEN_TRAINING_OK) {\n",
        b"    if (false)\n"
        b"        return MAPGEN_LINEAGE_ERR_SAME_REVISION;\n"
        b"\n"
        b"    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();\n"
        b"    if (!b)\n"
        b"        return MAPGEN_LINEAGE_ERR_MEMORY;\n"
        b"    if (MapGenTraining_FillSnapshot(training, b, compression) != MAPGEN_TRAINING_OK) {\n",
        "a new revision may not reuse its parent's identity",
    ),

    # --- the title ----------------------------------------------------------
    (
        "a-title-may-contain-a-newline",
        SRC,
        b"        if (*p < 0x20 || *p == 0x7F)\n",
        b"        if (false)\n",
        "a title containing a control byte is refused",
    ),
    (
        "an-empty-title-is-accepted",
        SRC,
        b"    if (!length || length >= MAPGEN_LINEAGE_TITLE_BYTES)\n",
        b"    if (length >= MAPGEN_LINEAGE_TITLE_BYTES)\n",
        "an empty title is refused",
    ),
    (
        "the-old-title-is-left-in-place",
        SRC,
        b"            const bool is_title = (end - line) >= 6 && !memcmp(data + line, \"title=\", 6);\n",
        b"            const bool is_title = false;\n",
        # Only the SECOND rename can see this. The first put a title where the
        # parent had none, so keeping the old line changed nothing - which is
        # why the driver renames twice.
        "the second title replaces the first",
    ),

    # --- slugs --------------------------------------------------------------
    (
        "a-slug-passes-non-ascii-through",
        SRC,
        b"        else if ((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9'))\n"
        b"            c = (char)*p;\n",
        b"        else\n"
        b"            c = (char)*p;\n",
        "and it contains nothing a filesystem could object to",
    ),
    (
        "a-slug-keeps-repeated-separators",
        SRC,
        # `if (false)` would leave `last_was_break` set but never read, and
        # -Wunused-but-set-variable would fail the BUILD instead of the check.
        b"            if (last_was_break)\n                continue;\n",
        b"            if (last_was_break && false)\n                continue;\n",
        "separators collapse and never trail",
    ),
    (
        "a-slug-may-come-out-empty",
        SRC,
        b"        const char *fallback = \"snapshot\";\n",
        b"        const char *fallback = \"\";\n",
        "a title with no usable characters still yields something",
    ),

    # --- hygiene ------------------------------------------------------------
    (
        "the-module-learns-to-tell-the-time",
        SRC,
        b"static mapgen_lineage_result_t finish(mapgen_snapshot_builder_t *b,\n",
        b"#include <time.h>\n"
        b"static uint64_t unused_now(void) { return (uint64_t)time(NULL); }\n"
        b"static mapgen_lineage_result_t finish(mapgen_snapshot_builder_t *b,\n",
        "identity is a parameter, never invented here",
    ),
    (
        "lineage-state-at-file-scope",
        SRC,
        b"static mapgen_lineage_result_t finish(mapgen_snapshot_builder_t *b,\n",
        b"static uint32_t g_revisions_built;\n\n"
        b"static mapgen_lineage_result_t finish(mapgen_snapshot_builder_t *b,\n",
        "no mutable file-scope state",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=3600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 lineage controlled RED")

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
