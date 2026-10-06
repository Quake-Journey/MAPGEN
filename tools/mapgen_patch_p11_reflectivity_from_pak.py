#!/usr/bin/env python3
"""Local patch P11 for the pinned compiler: the light pass cannot read archives.

Two hunks, one defect wearing two faces. `CalcTextureReflectivity` (patches.c)
cannot see anything that lives inside a `.pak`, so a map built from stock
Quake II textures is lit entirely by neutral grey.

HUNK 1 — no archive fallback for the texture itself

The function resolves a texture with `FileExists` and `TryLoadFile` only. The
BSP stage, in the same tree, does fall back:

    /* textures.c, qbsp */
    if (TryLoadFile(path, (void **)&mt, false) != -1
        || TryLoadFileFromPak(pakpath, (void **)&mt, moddir) != -1)

So qbsp reads a stock texture's flags and contents out of `pak0.pak`, the map
compiles without one "couldn't locate texture" warning, and the LIGHT pass
silently fails to find the same texture and leaves it at the default:

    texture_reflectivity[i][0..2] = 0.5;

which is a perfectly neutral grey. Every bounced ray and every surface light in
the map then carries that grey.

HUNK 2 — the palette pointer runs backwards out of its buffer

Where the palette itself comes from an archive:

    palette = palette_frompak - (i - 768);

`i` is the file's length and the palette is its LAST 768 bytes, so the address
wanted is `buffer + (length - 768)`. The minus sign walks roughly forty-three
kilobytes BEFORE the allocation and reads whatever is there. Every `.wal`
texture consequently reported an average colour of exactly 0, 0, 0 - visible in
this tree even before hunk 1, on a map whose `.tga` textures resolved normally
- and once hunk 1 started routing textures through the palette path in earnest,
the light pass segfaulted.

WHY IT MATTERS

MEASURED 2026-09-01, learning from q2dm1 alone: a generated map wears exactly
q2dm1's own textures - floor1_2 on 859 brush sides, then blume4_2, rocks19_1,
lead1_2, ceil1_4, blum12_1 - and its lightmap is 100% grey, r == g == b in
every texel, while q2dm1's own lightmap is 1% grey at 215% mean saturation.
`e2u3` is not loose on disk in this tree; it is inside `pak0.pak`, and so is
`pics/colormap.pcx`. Running the light pass with `-v` printed no `avg rgb` line
at all for these textures, because not one of them was found.

q2dm1 looks warm because its lightmap was baked decades ago by id's tools from
the real textures. A map compiled today from the same textures gets grey light,
and no amount of generator work changes that.

The PO's report of the batch before this: "архитектура по прежнему серая без
лайтмапов". It is this.

    python tools/mapgen_patch_p11_reflectivity_from_pak.py <staging src dir> [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARK = "MAPGEN-1 P11"

HUNKS = [
    # (a line that proves the hunk is present, anchor, replacement)
    (
        "TryLoadFileFromPak(pakpath, (void **)&mt, moddir)",
        """                    if (FileExists(path)) // qb: linux segfault if not exist
                    {
                        if (TryLoadFile(path, (void **)&mt, false) != -1)
                            wal_tex = true;
                    } else {
                        qprintf("NOT FOUND %s\\n", path);
                        continue;
                    }
""",
        """                    if (FileExists(path)) // qb: linux segfault if not exist
                    {
                        if (TryLoadFile(path, (void **)&mt, false) != -1)
                            wal_tex = true;
                    } else {
                        /*
                         * MAPGEN-1 P11: and then the archives, which this
                         * function never looked in. The BSP stage does exactly
                         * this (textures.c), so qbsp read a stock texture's
                         * flags out of pak0 while the light pass failed to find
                         * the same texture and left its reflectivity at the
                         * neutral 0.5 default - every bounce and every surface
                         * light in a map built from stock textures came out
                         * grey.
                         */
                        char pakpath[1024];
                        sprintf(pakpath, "textures/%s.wal", texinfo[i].texture);
                        if (TryLoadFileFromPak(pakpath, (void **)&mt, moddir) != -1
                            || TryLoadFileFromPak(pakpath, (void **)&mt, basedir) != -1) {
                            wal_tex = true;
                        } else {
                            qprintf("NOT FOUND %s\\n", path);
                            continue;
                        }
                    }
""",
    ),
    (
        "palette = palette_frompak + (i - 768);",
        """            // unicat: load from pack files, palette is loaded from the last 768 bytes
            palette = palette_frompak - (i - 768);
""",
        """            /*
             * MAPGEN-1 P11: this said `palette_frompak - (i - 768)`, which
             * walks about forty-three kilobytes BEFORE the allocation and
             * reads whatever is there. `i` is the file's length and the
             * palette is its LAST 768 bytes, so the address wanted is
             * buffer + (length - 768). Every .wal texture reported an average
             * colour of exactly 0, 0, 0 because of it.
             */
            palette = palette_frompak + (i - 768);
""",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="the staging src/ directory")
    parser.add_argument("--check", action="store_true",
                        help="report whether the patch is applied, change nothing")
    args = parser.parse_args()

    target = Path(args.src) / "src" / "patches.c"
    if not target.is_file():
        print(f"not found: {target}")
        return 2

    text = target.read_text(encoding="utf-8", errors="surrogateescape")
    missing = [h for h in HUNKS if h[0] not in text]

    if args.check:
        print("P11 applied" if not missing else
              f"P11 NOT applied ({len(missing)} of {len(HUNKS)} hunks missing)")
        return 0 if not missing else 1
    if not missing:
        print("P11 is already applied; nothing to do")
        return 0

    for present, anchor, replacement in missing:
        if text.count(anchor) != 1:
            print(f"the anchor for '{present[:40]}' does not appear exactly "
                  "once; refusing to guess")
            return 1
        text = text.replace(anchor, replacement, 1)

    target.write_text(text, encoding="utf-8", errors="surrogateescape")
    print(f"P11 applied to {target} ({len(missing)} hunk(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
