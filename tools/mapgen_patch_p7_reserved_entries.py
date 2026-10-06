#!/usr/bin/env python3
"""Local patch P7 for the pinned compiler: clear the reserved lump entries.

WHAT IS WRONG

`BeginBSPFile` (writebsp.c) reserves index 0 of the edge and vertex lumps and
says so in its own comment - "edge 0 is not used, because 0 can't be negated"
and "leave vertex 0 as an error" - but it never CLEARS those entries. The lump
arrays come from `malloc` (bspfile.c), so index 0 ships whatever was in the
heap.

WHY IT MATTERS

Two ways, and the second is worse than the first:

  * Q2PRO validates every edge on load. When the heap garbage in `dedges[0]`
    happens to hold a vertex number past the end of the vertex lump, the
    engine refuses the map with `BSP_LoadEdges: Bad vertnum`. Measured: two of
    three generated maps were unloadable for exactly this reason, and the
    third only loaded because its garbage happened to be in range;

  * the same `.map` compiles to a DIFFERENT BSP every time. Measured: three
    runs of one file gave three SHA-256s, differing only at edge 0. Contract
    section 10 requires the same recipe to produce the same output, and this
    breaks it at the compiler, underneath everything the generator does to
    stay deterministic.

The M0Q qualification did not catch it because its fixtures are small and the
heap happened to be clean under them. That is recorded as a finding against
the qualification, not only against the compiler.

WHAT THE PATCH DOES

Clears both reserved entries, in the same place and the same way the function
already clears `dleafs[0].contents` two lines below. Nothing else changes.

    python tools/mapgen_patch_p7_reserved_entries.py <staging src dir> [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ANCHOR = """    // edge 0 is not used, because 0 can't be negated
    numedges            = 1;

    // leave vertex 0 as an error
    numvertexes         = 1;
"""

PATCHED = """    // edge 0 is not used, because 0 can't be negated
    numedges            = 1;
    // MAPGEN-1 P7: and it is not cleared either, so it shipped whatever the
    // heap held. Q2PRO rejects the map when that garbage indexes past the
    // vertex lump, and the same source compiled to a different BSP every run.
    memset(&dedges[0], 0, sizeof(dedges[0]));
    memset(&dedgesX[0], 0, sizeof(dedgesX[0]));

    // leave vertex 0 as an error
    numvertexes         = 1;
    // MAPGEN-1 P7: same reason.
    memset(&dvertexes[0], 0, sizeof(dvertexes[0]));
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="the staging src/ directory")
    parser.add_argument("--check", action="store_true",
                        help="report whether the patch is applied, change nothing")
    args = parser.parse_args()

    target = Path(args.src) / "src" / "writebsp.c"
    if not target.is_file():
        print(f"not found: {target}")
        return 2

    text = target.read_text(encoding="utf-8", errors="surrogateescape")
    applied = "MAPGEN-1 P7" in text

    if args.check:
        print("P7 applied" if applied else "P7 NOT applied")
        return 0 if applied else 1

    if applied:
        print("P7 is already applied; nothing to do")
        return 0
    if text.count(ANCHOR) != 1:
        print("the anchor does not appear exactly once; refusing to guess")
        return 1

    target.write_text(text.replace(ANCHOR, PATCHED, 1),
                      encoding="utf-8", errors="surrogateescape")
    print(f"P7 applied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
