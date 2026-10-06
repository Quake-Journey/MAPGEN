#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_report_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Two mutations carry the weight:

  * `the-report-reaches-a-verdict` adds the one word contract 19 names. It
    changes no number and breaks no structure - the report simply starts
    claiming something it is not entitled to claim, which is exactly the
    failure the section exists to prevent;

  * `the-unlearned-list-is-dropped` removes the half of the report that says
    what the sources did NOT contain, leaving a document that is true in every
    line and misleading as a whole.

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

SUITE = SANDBOX.path("tools/check_mapgen_report_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_report.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- contract 19 --------------------------------------------------------
    (
        "the-report-reaches-a-verdict",
        SRC,
        b'    put(&s, "Measured structure\\n------------------\\n");\n',
        b'    put(&s, "Measured structure (balanced)\\n------------------\\n");\n',
        "the rendered report contains no judgement word",
    ),
    (
        "the-verdict-hides-in-a-string-the-guard-does-not-render",
        SRC,
        b'    put(&s, "Warnings\\n--------\\n");\n',
        b'    put(&s, "Warnings\\n--------\\n");\n'
        b'    if (false) put(&s, "this map is good\\n");\n',
        "no judgement word appears in any string the report can emit",
    ),
    (
        "the-report-decides-the-question-itself",
        SRC,
        b'    put(&s, "These are measurements of the source maps. Whether a generated map\\n"\n'
        b'            "plays well is decided by playing it.\\n");\n',
        b'    put(&s, "These are measurements of the source maps.\\n");\n',
        "it ends by handing the question back to playing the map",
    ),

    # --- what was not learned ------------------------------------------------
    (
        "the-unlearned-list-is-dropped",
        SRC,
        b'    put(&s, "NOT present in these sources, and therefore not learned\\n"\n'
        b'            "-------------------------------------------------------\\n");\n',
        b'    put(&s, "Other categories\\n----------------\\n");\n',
        "the report has a section for what it did not learn",
    ),
    (
        "an-absent-category-is-listed-as-learned",
        SRC,
        b"        if (!*((const bool *)((const uint8_t *)&caps + CAPS[i].offset)))\n"
        b"            continue;\n"
        b'        put(&s, "- ");\n'
        b'        put(&s, CAPS[i].name);\n'
        b'        put(&s, "\\n");\n'
        b"        any_learned = true;\n",

        b"        if (false)\n"
        b"            continue;\n"
        b'        put(&s, "- ");\n'
        b'        put(&s, CAPS[i].name);\n'
        b'        put(&s, "\\n");\n'
        b"        any_learned = true;\n",
        "the two lists do not overlap",
    ),
    (
        "monsters-are-assumed-present",
        SRC,
        b'    out->monsters = role_total(snap, "monster") > 0;\n',
        # `>= 0` on an unsigned is -Werror=type-limits, which fails the BUILD
        # rather than the check under test.
        b'    out->monsters = true;\n',
        "a deathmatch corpus reports monsters as unlearned",
    ),
    (
        "sp-progression-needs-only-a-monster",
        SRC,
        b'    out->sp_progression = out->monsters && role_total(snap, "changelevel") > 0;\n',
        b'    out->sp_progression = true;\n',
        "and single-player progression as unlearned",
    ),
    (
        "liquid-is-inferred-from-hazards",
        SRC,
        b"        if (contents & (0x8 | 0x10 | 0x20))\n",
        b"        if (contents & 0x8)\n",
        # `redyard`'s liquid is LAVA, so masking down to lava alone changes
        # nothing for it - the behavioural case cannot see this one, and the
        # static check is what does.
        "liquid is read from the material contents, not inferred from hazards",
    ),

    # --- accounting -----------------------------------------------------------
    (
        "the-duplicate-count-is-not-reported",
        SRC,
        b'    row(&s, "Duplicates skipped", field(snap, MAPGEN_CHUNK_QUALITY, "duplicates", NULL));\n',
        b'    row(&s, "Duplicates skipped", 0);\n',
        "the counts account for every offered source",
    ),
    (
        "no-warning-for-a-deduplicated-source",
        SRC,
        b'    if (field(snap, MAPGEN_CHUNK_QUALITY, "duplicates", NULL)) {\n',
        b'    if (false) {\n',
        "a duplicate produces a warning",
    ),
    (
        "no-warning-for-a-small-corpus",
        SRC,
        b'    if (field(snap, MAPGEN_CHUNK_QUALITY, "low_diversity", NULL)) {\n',
        b'    if (false) {\n',
        "so does a small corpus",
    ),
    (
        "the-small-corpus-warning-blames-the-maps",
        SRC,
        b'        put(&s, "- Few distinct sources. Measured distributions rest on a small\\n"\n'
        b'                "  sample; this is a statement about the sample size, not about\\n"\n'
        b'                "  the maps.\\n");\n',
        b'        put(&s, "- Few distinct sources.\\n");\n',
        "the small-corpus warning says what it is about",
    ),

    # --- hygiene --------------------------------------------------------------
    (
        "report-state-at-file-scope",
        SRC,
        b"static void put(sink_t *s, const char *text)\n{\n",
        b"static uint32_t g_reports_rendered;\n\n"
        b"static void put(sink_t *s, const char *text)\n{\n"
        b"    g_reports_rendered++;\n",
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
    print("=== MAPGEN-1 Training report controlled RED")

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
