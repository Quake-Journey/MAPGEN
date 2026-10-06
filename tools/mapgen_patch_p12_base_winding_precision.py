#!/usr/bin/env python3
"""Local patch P12 for the pinned compiler: every winding is cut out of a quad
a million units wide, in single precision.

WHAT IS WRONG

`BaseWindingForPlane` (src/polylib.c) builds the quad that every brush side,
every portal and every face is clipped out of:

    VectorScale(vup, BOGUS_RANGE, vup);
    VectorScale(vright, BOGUS_RANGE, vright);

`BOGUS_RANGE` is `1 << 20` = 1048576 (src/mathlib.h). The world is
`DEFAULT_MAP_SIZE` = 4096, so the quad is two hundred and fifty times wider
than anything that can be in it.

That would cost nothing in double precision, and this build does not have it.
`mathlib.h` says

    #ifdef BSP          // only do this for qbsp, ...
    #define DOUBLEVEC_T
    #endif

and nothing in `CMakeLists.txt` ever defines `BSP`, so `vec_t` is `float` in
the BSP stage as well. At exactly 2^20 a binary32's neighbours are 0.0625 below
and 0.125 above, so the representable values there are 0.0625 to 0.125 apart -
and every winding clipped out of that quad inherits that spacing.

MEASURED 2026-09-06, a two-brush fixture compiled with the pinned binary: a
brush corner whose exact position is (934, 128) comes back at (934, 128.0625) -
off its own plane by 0.054 units.

WHY IT MATTERS

On a flat wall 0.06 units is invisible. Where two wall panels meet at a shallow
angle it is not, because the position of their shared edge is the intersection
of two nearly-parallel planes: an error e in either moves the edge by
`e / sin(angle)`.

q2dm1's courtyard has two panels meeting at **1.1 degrees**, so the amplifier
is 52x, and 0.06 units of winding error becomes **up to three units** of
displaced crease. Neither panel's face reaches the other and a strip of the
wall is simply not drawn - the PO photographed it on 2026-09-01
(`Bugs/6/quake071.jpg`), filmed it again on 2026-09-06
(`Bugs/6/Desktop 2026.09.06 - 10.27.21.08.mp4`) and reported it for five days.

It is NOT the generator's writer. MEASURED on the same fixture with the same
pinned binary: the two panels spelled the way an editor would spell them -
integer points on the integer planes, which is what the original q2dm1.map
contained - still leave a 1.1-unit hole. No way of writing a `.map` can close
it, because the loss happens after the plane is read.

(The C comment inside the patch still says "ULP" for that spacing. It is left
verbatim on purpose: the block is the patch TEXT, so rewording it changes the
source the deployed compiler was built from, and a qualification receipt has to
name one source. It is corrected here, where the explanation lives.)

THE PATCH

The quad only has to swallow the world. Sized at `4 * max_bounds` it still
covers it with room to spare - the farthest a world point can project from a
plane's own foot is under `2 * sqrt(3) * max_bounds` - and at 2^14 the spacing
is 0.0009765625 down and 0.001953125 up instead of 0.0625 and 0.125, sixty-four
times tighter.

MEASURED with the patch, everything else identical:

    the fixture crease          898.674  ->  896.000   (exact is 896)
    q2dm1 fork at fidelity 100, undrawn drawn-surface area:
                                   4294  ->  0         square units
    q2dm1 solid grown where the donor had air:
                                   2458  ->  76        sampled points
    q2dm2, q2dm3, q2dm8 undrawn:      0  ->  0         (unchanged)

The patch does not touch `BOGUS_RANGE` itself, which is used elsewhere as a
"larger than any real value" sentinel and is correct there.

    python tools/mapgen_patch_p12_base_winding_precision.py <src> [--check]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARK = "MAPGEN-1 P12"

ANCHOR = """    VectorScale(vup, BOGUS_RANGE, vup);
    VectorScale(vright, BOGUS_RANGE, vright);"""

PATCHED = """    /*
     * MAPGEN-1 P12: the base quad only has to swallow the world.
     *
     * It was BOGUS_RANGE (1<<20), two hundred and fifty times wider than
     * DEFAULT_MAP_SIZE, and vec_t is float here because DOUBLEVEC_T is guarded
     * by #ifdef BSP and this build never defines it. A float's ULP at 2^20 is
     * 0.0625, and every winding clipped out of this quad inherits it - a brush
     * corner whose exact position is (934, 128) came back at (934, 128.0625).
     *
     * Where two walls meet at a shallow angle that error is multiplied by
     * 1/sin(angle): at q2dm1's 1.1-degree courtyard crease, 52x, which is up to
     * three units of displaced edge and a strip of wall that nothing draws.
     *
     * 4 * max_bounds still covers the world - the farthest a world point can
     * project from a plane's own foot is under 2*sqrt(3)*max_bounds - and its
     * ULP is 0.00098.
     */
    {
        vec_t extent = (vec_t)(4 * (max_bounds > 0 ? max_bounds : 4096));
        VectorScale(vup, extent, vup);
        VectorScale(vright, extent, vright);
    }"""

DECL = "extern int32_t max_bounds;   /* MAPGEN-1 P12 */\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="the q2tools source directory")
    ap.add_argument("--check", action="store_true",
                    help="report whether the patch is applied, change nothing")
    ap.add_argument("--revert", action="store_true",
                    help="put the original two lines back, for a controlled RED")
    args = ap.parse_args()

    poly = Path(args.src) / "src" / "polylib.c"
    if not poly.is_file():
        print(f"not found: {poly}")
        return 2

    text = poly.read_text(encoding="utf-8", errors="surrogateescape")
    # The block itself, not the marker: the marker also appears in the extern
    # declaration this patch adds, so testing for it made --revert leave the
    # file looking patched when the geometry change was already out of it.
    applied = PATCHED in text

    if args.check:
        print("P12 applied" if applied else "P12 NOT applied")
        return 0 if applied else 1

    if args.revert:
        #
        # For a controlled RED, and for nothing else.
        #
        # The guard has to build a compiler WITHOUT this patch to show that the
        # crease reopens; doing that by cutting text out of polylib.c from the
        # outside means the guard breaks the day this comment is reflowed. The
        # patch knows its own shape, so it undoes itself.
        #
        if not applied:
            print("P12 is not applied; nothing to revert")
            return 0
        if text.count(PATCHED) != 1:
            print("polylib.c: the patched block is not verbatim; refusing to guess")
            return 1
        text = text.replace(PATCHED, ANCHOR, 1)
        # and the declaration it brought with it, so that re-applying restores
        # the file byte for byte
        text = text.replace(chr(10) + DECL, "", 1)
        poly.write_text(text, encoding="utf-8", errors="surrogateescape")
        print("P12 reverted in polylib.c")
        return 0

    if applied:
        print("P12 is already applied; nothing to do")
        return 0

    if text.count(ANCHOR) != 1:
        print("polylib.c: the anchor does not appear exactly once; refusing to guess")
        return 1
    text = text.replace(ANCHOR, PATCHED, 1)

    if "extern int32_t max_bounds;" not in text:
        include = '#include "polylib.h"\n'
        if text.count(include) != 1:
            print("polylib.c: no place to declare max_bounds; refusing to guess")
            return 1
        text = text.replace(include, include + "\n" + DECL, 1)

    poly.write_text(text, encoding="utf-8", errors="surrogateescape")
    print("P12 applied to polylib.c")
    return 0


if __name__ == "__main__":
    sys.exit(main())
