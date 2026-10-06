#!/usr/bin/env python3
"""Local patch P9 for the pinned compiler: radiosity is structurally dead.

WHAT IS WRONG

`lightmap.c` declares two arrays and reads them:

    int32_t facelinks[MAX_MAP_FACES_QBSP];              // line 71
    int32_t planelinks[2][MAX_MAP_PLANES_QBSP];         // line 72

    for (pfacenum = planelinks[f->side][f->planenum]; pfacenum;
         pfacenum = facelinks[pfacenum]) { ... }         // lines 2569, 2695

Nothing in the tree ever WRITES either of them, and `LinkPlaneFaces()` - the
function that fills them in id's original qrad3 - does not exist here at all.
Both arrays are static, so both are all zeroes, so the loop body never
executes.

That loop is what gathers the patches of every face on a plane into the
triangulation the bounce is sampled from. With no patches gathered,
`trian->numpoints` is 0, `SampleTriangulation` returns nothing, and the
radiosity contribution added at

    if (numbounce > 0 && st == 0) { SampleTriangulation(...); VectorAdd(...); }

is exactly zero for every sample of every face of every map.

WHY IT MATTERS

Every map this compiler produces is direct-lighting only.

MEASURED 2026-09-01: `-rad -bounce 0` and `-rad -bounce 8` produce
BYTE-IDENTICAL lightmaps - on generated maps and on the M0Q `sealed_room`
fixture alike, so it is not a property of the generator's geometry. The bounce
pass itself runs: the header prints `bounce : 4`, and it reports 11357 patches
and 306 direct lights. It just has nowhere to deposit the result.

Consequences the PO reported directly, both of which are what bounce is for:

  * "the textures look washed out, as if there were no lightmaps ... exactly
    like gl_coloredlightmaps 0, though it is 1". MEASURED: 100% of lightmap
    texels in a generated map have r == g == b. Bounce is what carries wall
    colour into every texel - aerowalk and q2dm1e are 96-99% coloured while
    carrying NO `_color` lights whatsoever, entirely from bounced light;

  * "there are still many dark places". MEASURED: a generated map has 59% of
    its texels in the darkest histogram bucket against 26 to 35 for a real
    map, and nothing in the middle. Bounce is what fills the middle.

WHAT THE PATCH DOES

Restores `LinkPlaneFaces` and calls it once, before the facelights are built.
It is id's original function, extended to the QBSP face array this tree also
supports. Note that face 0 can never be linked, because 0 terminates the list -
that is the original behaviour and is left exactly as it was.

    python tools/mapgen_patch_p9_link_plane_faces.py <staging src dir> [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARK = "MAPGEN-1 P9"

ANCHOR_DECL = """int32_t facelinks[MAX_MAP_FACES_QBSP];
"""

PATCHED_DECL = """int32_t facelinks[MAX_MAP_FACES_QBSP];
"""

ANCHOR_CALL = """    // build initial facelights
    printf("--- Build Facelights ---\\n");
"""

PATCHED_CALL = """    // MAPGEN-1 P9: without this, planelinks and facelinks are all zeroes -
    // nothing in the tree ever wrote them - so the patch triangulation every
    // face's bounce is sampled from has no points in it and the radiosity
    // contribution is exactly zero. Every map came out direct-lit only.
    LinkPlaneFaces();

    // build initial facelights
    printf("--- Build Facelights ---\\n");
"""

FUNCTION = """
/*
=============
LinkPlaneFaces

MAPGEN-1 P9. Chain every face onto the list for the plane and side it lies on,
so FinalLightFace can walk the faces sharing a plane and collect their patches
into the triangulation the bounce is sampled from.

This is id's original qrad3 function, restored. It was absent from this tree
while the two arrays it fills were still declared and still read, which made
the radiosity pass run and deposit nothing.

Face 0 can never be linked, because 0 terminates the list. That is the original
behaviour and is deliberately unchanged.
=============
*/
void LinkPlaneFaces(void) {
    int32_t i;

    memset(facelinks, 0, sizeof(facelinks));
    memset(planelinks, 0, sizeof(planelinks));

    if (use_qbsp) {
        for (i = 0; i < numfaces; i++) {
            dface_tx *f = &dfacesX[i];
            facelinks[i] = planelinks[f->side][f->planenum];
            planelinks[f->side][f->planenum] = i;
        }
    } else {
        for (i = 0; i < numfaces; i++) {
            dface_t *f = &dfaces[i];
            facelinks[i] = planelinks[f->side][f->planenum];
            planelinks[f->side][f->planenum] = i;
        }
    }
}

"""

FUNCTION_ANCHOR = "void FinalLightFace(int32_t facenum) {"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="the staging src/ directory")
    parser.add_argument("--check", action="store_true",
                        help="report whether the patch is applied, change nothing")
    args = parser.parse_args()

    lightmap = Path(args.src) / "src" / "lightmap.c"
    rad = Path(args.src) / "src" / "rad.c"
    header = Path(args.src) / "src" / "qrad.h"
    for target in (lightmap, rad, header):
        if not target.is_file():
            print(f"not found: {target}")
            return 2

    applied = all(MARK in t.read_text(encoding="utf-8", errors="surrogateescape")
                  for t in (lightmap, rad))

    if args.check:
        print("P9 applied" if applied else "P9 NOT applied")
        return 0 if applied else 1
    if applied:
        print("P9 is already applied; nothing to do")
        return 0

    text = lightmap.read_text(encoding="utf-8", errors="surrogateescape")
    if text.count(FUNCTION_ANCHOR) != 1:
        print("lightmap.c: the anchor does not appear exactly once; refusing to guess")
        return 1
    lightmap.write_text(text.replace(FUNCTION_ANCHOR, FUNCTION + FUNCTION_ANCHOR, 1),
                        encoding="utf-8", errors="surrogateescape")

    text = rad.read_text(encoding="utf-8", errors="surrogateescape")
    if text.count(ANCHOR_CALL) != 1:
        print("rad.c: the anchor does not appear exactly once; refusing to guess")
        return 1
    rad.write_text(text.replace(ANCHOR_CALL, PATCHED_CALL, 1),
                   encoding="utf-8", errors="surrogateescape")

    text = header.read_text(encoding="utf-8", errors="surrogateescape")
    if "LinkPlaneFaces" not in text:
        anchor = "void FinalLightFace(int32_t facenum);"
        if text.count(anchor) != 1:
            anchor = "void BuildFacelights(int32_t facenum);"
        if text.count(anchor) != 1:
            print("qrad.h: no anchor for the declaration; refusing to guess")
            return 1
        header.write_text(
            text.replace(anchor, "void LinkPlaneFaces(void);   /* MAPGEN-1 P9 */\n"
                         + anchor, 1),
            encoding="utf-8", errors="surrogateescape")

    print("P9 applied to lightmap.c, rad.c and qrad.h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
