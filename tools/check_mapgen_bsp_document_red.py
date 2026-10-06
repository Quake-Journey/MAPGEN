#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_bsp_document.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect and passed again after byte-exact restoration.

Every mutation removes one protection from the headless BSP document - the
ceiling check, the 64-bit bounds sum, the odd-size rule, the ident and version
checks, an index rule, the texture sanitizer, the entity-string cut, the
locale-free float text - and each must go RED on its OWN named case.

One of them, `submodel-headnode-must-be-a-node`, re-introduces a real bug: the
first version of this reader rejected a negative submodel headnode and refused
four playable maps from the PO's own Release tree. That case exists so the
regression cannot come back quietly.

Exit 0 = every mutation detected, everything restored byte-identically.
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

SUITE = SANDBOX.path("tools/check_mapgen_bsp_document.py")
DOC = SANDBOX.path("src/mapgen/mapgen_bsp.c")
HDR = SANDBOX.path("inc/common/mapgen_bsp.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    (
        "submodel-headnode-must-be-a-node",
        DOC,
        b"        if (hn >= 0) {\n",
        b"        if (true) {\n",
        "the C document loads all 132 shipped maps",
    ),
    (
        # The defect the whole parity suite was blind to for a week: both
        # readers sent a point exactly ON a node plane to the back child, and
        # agreed with each other perfectly while disagreeing with the engine.
        "on-plane-point-goes-to-the-back-child",
        DOC,
        b"        num = n->children[d < 0];\n",
        b"        num = n->children[d > 0 ? 0 : 1];\n",
        "the document uses that same tie-break",
    ),
    (
        "counts-are-not-capped",
        DOC,
        b"        if (count > table[i].limit)\n            return MAPGEN_BSP_ERR_LIMIT_EXCEEDED;\n",
        b"        if (count > 0xFFFFFFFFu)\n            return MAPGEN_BSP_ERR_LIMIT_EXCEEDED;\n",
        "every count is checked against a ceiling BEFORE any allocation",
    ),
    (
        "lump-bounds-summed-in-32-bits",
        DOC,
        b"        if ((uint64_t)ofs + (uint64_t)len > (uint64_t)size)\n",
        b"        if (ofs + len > (uint32_t)size)\n",
        "an offset+length that would wrap 32 bits is refused",
    ),
    (
        "odd-lump-sizes-accepted",
        DOC,
        b"        if (len % table[i].size)\n            return MAPGEN_BSP_ERR_LUMP_ODD_SIZE;\n",
        b"        if (false)\n            return MAPGEN_BSP_ERR_LUMP_ODD_SIZE;\n",
        "a lump with an odd size is LUMP_ODD_SIZE",
    ),
    (
        "any-ident-accepted",
        DOC,
        b"    else\n        return MAPGEN_BSP_ERR_BAD_IDENT;\n",
        b"    else\n        extended = false;\n",
        "a wrong ident is BAD_IDENT",
    ),
    (
        "any-version-accepted",
        DOC,
        b"    if (rd_u32(data + 4) != MAPGEN_BSP_VERSION)\n        return MAPGEN_BSP_ERR_BAD_VERSION;\n",
        b"    if (false)\n        return MAPGEN_BSP_ERR_BAD_VERSION;\n",
        "a wrong version is BAD_VERSION",
    ),
    (
        "a-world-with-no-models-is-accepted",
        DOC,
        b"    if (!bsp->num_models) {\n",
        b"    if (false) {\n",
        "a file with no models is NO_MODELS",
    ),
    (
        "leaf-ranges-not-validated",
        DOC,
        b"        if ((uint64_t)lf->firstleafbrush + lf->numleafbrushes > bsp->num_leafbrushes ||\n"
        b"            (uint64_t)lf->firstleafface + lf->numleaffaces > bsp->num_leaffaces) {\n",
        # Keeps `lf` used so -Werror does not fail the BUILD instead of the check.
        b"        if ((uint64_t)lf->firstleafbrush + lf->numleafbrushes > 0xFFFFFFFFull) {\n",
        "a leaf pointing at leafbrushes that do not exist is BAD_INDEX",
    ),
    (
        "texture-names-not-sanitized",
        DOC,
        b"            if ((unsigned char)ti->texture[c] < 0x20)\n                ti->texture[c] = '?';\n",
        b"            if (false)\n                ti->texture[c] = '?';\n",
        "a control byte in a texture name is replaced",
    ),
    (
        "float-text-uses-printf",
        DOC,
        # Renaming the function would break its callers and fail the BUILD.
        # Reintroducing a printf format string is the actual defect the check
        # is about: a locale-dependent conversion sneaking back in.
        b"    double v = (double)value;\n",
        b"    const char *legacy = \"%f\"; (void)legacy;\n    double v = (double)value;\n",
        "float text is written without printf",
    ),
    (
        "the-tree-walk-is-unbounded",
        DOC,
        b"    for (uint32_t guard = 0; num >= 0 && guard <= b->num_nodes; guard++) {\n",
        b"    while (num >= 0) {\n",
        "the tree walk is bounded",
    ),
    (
        "areas-limit-raised-for-qbsp",
        HDR,
        b"#define MAPGEN_BSP_MAX_AREAS        256u\n",
        b"#define MAPGEN_BSP_MAX_AREAS        65536u\n",
        "MAX_MAP_AREAS stays at 256 even for QBSP",
    ),
    (
        "the-document-learns-about-USE_REF",
        DOC,
        b"#include <stdlib.h>\n#include <string.h>\n",
        b"#include <stdlib.h>\n#include <string.h>\n#if USE_REF\n#endif\n",
        "the document never mentions USE_REF",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True, cwd=str(REPO), timeout=2400
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 BspDocument controlled RED")

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
