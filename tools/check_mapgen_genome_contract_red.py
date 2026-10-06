#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_genome_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect and passed again after byte-exact restoration.

The headline mutation is `roles-classified-by-name`: it puts back the exact
defect contract section 7.7 forbids - deciding what a surface IS from what it
is CALLED. It must be caught by the crafted cases where name and flags
deliberately disagree, and by nothing else.

`entity-values-capped-below-the-format` re-introduces the 256-byte cap that
refused `urbanjungle.bsp`, a real shipped map, so that regression cannot come
back quietly either.

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

SUITE = SANDBOX.path("tools/check_mapgen_genome_contract.py")
GEN = SANDBOX.path("src/mapgen/mapgen_genome.c")
HDR = SANDBOX.path("inc/common/mapgen_genome.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    (
        "roles-classified-by-name",
        GEN,
        # Puts back the exact defect contract 7.7 forbids: deciding what a
        # surface IS from what it is CALLED.
        b"        m->roles = roles_from(m->surface_flags, m->contents, animated);\n",
        b"        m->roles = roles_from(m->surface_flags, m->contents, animated);\n"
        b"        if (strstr(m->name, \"water\"))\n            m->roles |= MAPGEN_ROLE_WATER;\n",
        "a texture NAMED water with solid contents is not water",
    ),
    (
        "water-not-recognised-from-contents",
        GEN,
        b"    if (contents & MAPGEN_CONTENTS_WATER)  roles |= MAPGEN_ROLE_WATER;\n",
        b"    if (false)  roles |= MAPGEN_ROLE_WATER;\n",
        "a texture NAMED floor with water contents IS water",
    ),
    (
        "sky-not-recognised-from-flags",
        GEN,
        b"    if (surface_flags & MAPGEN_SURF_SKY)      roles |= MAPGEN_ROLE_SKY;\n",
        b"    if (false)      roles |= MAPGEN_ROLE_SKY;\n",
        "a texture NAMED brick with SURF_SKY IS sky",
    ),
    (
        "clip-collapsed-into-lava",
        GEN,
        b"    if (contents & MAPGEN_CONTENTS_LAVA)   roles |= MAPGEN_ROLE_LAVA;\n",
        b"    if (contents & (MAPGEN_CONTENTS_LAVA | MAPGEN_CONTENTS_PLAYERCLIP))   roles |= MAPGEN_ROLE_LAVA;\n",
        "a texture NAMED lavafall with clip contents is clip, not lava",
    ),
    (
        "contents-taken-from-texinfo-not-brushes",
        GEN,
        b"            g->materials[index].contents |= brush->contents;\n",
        b"            g->materials[index].contents |= ti->flags;\n",
        "contents come from the brushes, not from the texinfo",
    ),
    (
        "material-lookup-becomes-a-prefix-match",
        GEN,
        b"        if (!strcmp(g->materials[i].name, name))\n",
        b"        if (!strncmp(g->materials[i].name, name, strlen(name)))\n",
        "material lookup is exact",
    ),
    (
        "animation-chains-ignored",
        GEN,
        b"        if (ti->nexttexinfo >= 0)\n",
        b"        if (false)\n",
        "a texinfo with a next link marks its material animated",
    ),
    (
        "entity-values-capped-below-the-format",
        HDR,
        b"#define MAPGEN_GENOME_VALUE_BYTES     1024\n",
        b"#define MAPGEN_GENOME_VALUE_BYTES     256\n",
        "entity values are capped at the FORMAT's limit",
    ),
    (
        "overlong-values-truncated-silently",
        GEN,
        b"        if (n + 1 >= capacity) {\n            *too_long = true;\n            return false;\n        }\n",
        b"        if (n + 1 >= capacity) {\n            break;\n        }\n",
        "an overlong value is an error, not a truncation",
    ),
    (
        "malformed-entities-accepted",
        GEN,
        # Keeps `closed` used, so -Werror does not fail the BUILD instead of
        # the check under test.
        b"            bool closed = false;\n",
        b"            bool closed = true;\n",
        "unterminated block is refused",
    ),
    (
        "control-bytes-survive-in-values",
        GEN,
        b"        out[n++] = ((unsigned char)c < 0x20) ? '?' : c;\n",
        b"        out[n++] = c;\n",
        "control bytes are stripped from entity values",
    ),
    (
        "digest-follows-the-texinfo-order",
        GEN,
        b"        while (j > 0 && strcmp(g->materials[order[j - 1]].name, g->materials[key].name) > 0) {\n",
        b"        while (false) {\n",
        "the texinfo lump's ORDER does not change the digest",
    ),
    (
        "origin-not-parsed",
        GEN,
        b"                    ent->has_origin = parse_origin(value, ent->origin);\n",
        b"                    ent->has_origin = parse_origin(value, ent->origin) && false;\n",
        "origin is parsed",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True, cwd=str(REPO), timeout=2400
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 MapGenome controlled RED")

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
