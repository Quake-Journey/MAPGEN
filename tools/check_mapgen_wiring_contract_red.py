#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_wiring_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Three mutations carry the weight:

  * `a-target-fires-only-the-first-match` breaks the one-to-many rule that 77
    shared targetnames in the corpus depend on;
  * `dangling-links-are-dropped` makes 47 real broken links in shipped maps
    disappear, which is exactly the kind of silence this layer exists to
    prevent;
  * `cycles-found-by-unwinding-the-dfs-stack` puts back the first, wrong
    implementation - it answers a different question and disagreed with the
    independent build on four maps.

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

SUITE = SANDBOX.path("tools/check_mapgen_wiring_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_wiring.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the linking rules ------------------------------------------------
    (
        "a-target-fires-only-the-first-match",
        SRC,
        b"                w->entities[i].out_links++;\n"
        b"                w->entities[j].in_links++;\n"
        b"                matched++;\n",
        b"                w->entities[i].out_links++;\n"
        b"                w->entities[j].in_links++;\n"
        b"                matched++;\n"
        b"                break;\n",
        "a target naming two entities fires both",
    ),
    (
        "dangling-links-are-dropped",
        SRC,
        b"            if (!matched && !push_dangling(w, &dangle_cap, i, (uint8_t)k, want)) {\n",
        b"            if (false && !push_dangling(w, &dangle_cap, i, (uint8_t)k, want)) {\n",
        "a target naming nothing is kept as a dangling link",
    ),
    (
        "only-target-counts-as-a-link",
        SRC,
        b'        "target", "killtarget", "pathtarget",\n',
        b'        "target", "target", "target",\n',
        "killtarget and pathtarget are links too",
    ),
    (
        "a-shared-name-is-counted-once-per-entity",
        SRC,
        # Mutating the inner test rather than the outer one keeps
        # `first_of_its_name` used, so -Werror does not fail the BUILD instead
        # of the check under test.
        b"            if (j < i) {\n",
        b"            if (j < i && false) {\n",
        "a name shared by two entities is counted once",
    ),

    # --- cycles ------------------------------------------------------------
    (
        "cycles-found-by-unwinding-the-dfs-stack",
        SRC,
        b"    bool cyclic = size > 1;\n",
        b"    bool cyclic = size > 0;\n",
        "a chain that does not close is not a cycle",
    ),
    (
        "a-self-target-is-not-a-cycle",
        SRC,
        b"        for (uint32_t k = t->first[root]; k < t->first[root + 1]; k++)\n"
        b"            if (w->links[t->sorted[k]].to == root) {\n",
        b"        for (uint32_t k = t->first[root]; k < t->first[root]; k++)\n"
        b"            if (w->links[t->sorted[k]].to == root) {\n",
        "an entity that targets itself is on a cycle",
    ),
    (
        "a-ring-is-not-a-cycle",
        SRC,
        b"                } else if (t.on_component[next] &&\n"
        b"                           t.index[next] < t.lowlink[v]) {\n",
        b"                } else if (false &&\n"
        b"                           t.index[next] < t.lowlink[v]) {\n",
        "a three-entity ring is a cycle",
    ),

    # --- classification ---------------------------------------------------
    (
        "a-prefix-overrules-the-exact-table",
        SRC,
        b"    for (size_t i = 0; i < sizeof(EXACT_ROLES) / sizeof(EXACT_ROLES[0]); i++)\n"
        b"        if (!strcmp(EXACT_ROLES[i].name, classname))\n"
        b"            return EXACT_ROLES[i].roles;\n",
        b"    for (size_t i = 0; i < sizeof(EXACT_ROLES) / sizeof(EXACT_ROLES[0]); i++)\n"
        b"        if (!strcmp(EXACT_ROLES[i].name, classname) && classname[0] == '@')\n"
        b"            return EXACT_ROLES[i].roles;\n",
        "the exact table beats the prefix that also matches",
    ),
    (
        "a-classname-is-matched-as-a-substring",
        SRC,
        b"        if (!strncmp(PREFIX_ROLES[i].name, classname, n))\n",
        b"        if (strstr(classname, PREFIX_ROLES[i].name))\n",
        "a classname is never matched as a substring",
    ),
    (
        "an-editor-leftover-is-classified-as-a-mover",
        SRC,
        b'    { "func_group",               MAPGEN_ENTROLE_EDITOR_LEFTOVER },\n',
        b'    { "func_group_x",             MAPGEN_ENTROLE_EDITOR_LEFTOVER },\n',
        "24 classnames classify to exactly the right roles",
    ),
    (
        "the-tag-token-goes-back-to-meaning-nothing",
        SRC,
        b'    { "dm_tag_token",             MAPGEN_ENTROLE_POWERUP | MAPGEN_ENTROLE_ITEM },\n',
        b'    { "dm_tag_token_x",           MAPGEN_ENTROLE_POWERUP | MAPGEN_ENTROLE_ITEM },\n',
        "all 94 classnames in the corpus classify to something",
    ),

    # --- submodels ---------------------------------------------------------
    (
        "a-submodel-index-is-not-validated",
        SRC,
        b"        if (e->submodel >= 0 && bsp && (uint32_t)e->submodel >= models) {\n",
        b"        if (e->submodel >= 0 && bsp && (uint32_t)e->submodel >= models + 4096u) {\n",
        "a submodel index past the end of the document is refused",
    ),
    (
        "a-model-value-is-parsed-loosely",
        SRC,
        b"        if (*p < '0' || *p > '9')\n            return -1;\n",
        b"        if (*p < '0' || *p > '9')\n            break;\n",
        # "*0a", not "*12a": a loose parser reads 12 as out of range and the
        # submodel validation quietly rescues it, so that case proves nothing.
        "a model of '*0a' yields submodel -1",
    ),
    (
        "a-bare-star-is-submodel-zero",
        SRC,
        b"    if (!model || model[0] != '*' || !model[1])\n        return -1;\n",
        b"    if (!model || model[0] != '*')\n        return -1;\n",
        "a model of '*' yields submodel -1",
    ),

    # --- teams -------------------------------------------------------------
    (
        "every-team-member-starts-a-new-group",
        SRC,
        b"        if (!team || !*team || w->entities[i].team != UINT32_MAX)\n",
        b"        if (!team || !*team)\n",
        "two entities sharing a team form one group",
    ),

    # --- state -------------------------------------------------------------
    (
        "wiring-state-at-file-scope",
        SRC,
        b"static int32_t parse_submodel(const char *model)\n{\n",
        b"static uint32_t g_models_parsed;\n\n"
        b"static int32_t parse_submodel(const char *model)\n{\n"
        b"    g_models_parsed++;\n",
        "no mutable file-scope state",
    ),
    (
        "wiring-state-in-a-function-local-static",
        SRC,
        b"    int64_t v = 0;\n",
        b"    static int64_t v;\n    v = 0;\n",
        "no function-local mutable state",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=3600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 MapGenWiring controlled RED")

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
