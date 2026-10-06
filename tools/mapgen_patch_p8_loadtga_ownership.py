#!/usr/bin/env python3
"""Local patch P8 for the pinned compiler: LoadTGA frees what it returns.

WHAT IS WRONG

`LoadTGA` (lbmlib.c) allocates the pixel buffer, hands it to the caller
through `*pixels`, and then frees it before returning:

    free(targa_rgba); // qb: memory leak
    fclose(fin);

Every caller therefore receives a dangling pointer, and both of them use it:

  * `CalcTextureReflectivity` (patches.c) reads width*height*4 bytes out of
    it to average the texture colour. Its own line 280 carries the matching
    comment - "qb: freed in LoadTGA now.  free(pbuffer);" - so the free was
    moved deliberately and the ownership was simply lost;

  * `Cmd_Environment` (images.c) reads 256x256 pixels out of it and then
    frees it AGAIN, which is a double free on top of the use-after-free.

WHY IT MATTERS

The light pass dies. MEASURED: with the -rad stage run on generated maps,
sixteen of eighteen candidates crashed with a Windows access violation
(0xC0000005), always in `CalcTextureReflectivity` at patches.c:254, always on
the first texture that has a loose `.tga` replacement beside it - this tree
has 114 of them. The buffer had been freed, the heap had decommitted the
page, and the read walked off the end of it 64 pixels in.

It is invisible under a debugger. Windows gives a debugged process the debug
heap, which keeps freed blocks mapped, so the identical binary on the
identical input completes normally under gdb and faults without it. Two
instrumented builds were written off as "does not reproduce" for that reason
before the heap was taken out of the picture with _NO_DEBUG_HEAP.

The compiler prefers a loose `.tga` over the `.wal` beside it (patches.c:190),
so which maps die depends only on which textures they happen to use. That is
also why this surfaced late: while a map was built out of one texture set it
usually missed all 114, and it stopped missing them as soon as the generator
started drawing a set per room.

WHAT THE PATCH DOES

Deletes the free, so the buffer belongs to the caller as its two call sites
already assume, and frees it in `CalcTextureReflectivity` where the removed
free used to be. `Cmd_Environment` already frees it and is left alone.
Nothing else changes.

    python tools/mapgen_patch_p8_loadtga_ownership.py <staging src dir> [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARK = "MAPGEN-1 P8"

TGA_ANCHOR = """    free(targa_rgba); // qb: memory leak
    fclose(fin);
"""

TGA_PATCHED = """    // MAPGEN-1 P8: this used to free targa_rgba - the buffer it has just
    // returned through *pixels - and both callers then read it. The light
    // pass died in CalcTextureReflectivity on any map using a texture with a
    // loose .tga beside it. The buffer belongs to the caller.
    fclose(fin);
"""

PATCH_ANCHOR = """            // qb: freed in LoadTGA now.  free(pbuffer);
"""

PATCH_PATCHED = """            // MAPGEN-1 P8: it was NOT freed in LoadTGA, it was freed there
            // and returned anyway. LoadTGA no longer frees it, so this does.
            free(pbuffer);
            pbuffer = NULL;
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="the staging src/ directory")
    parser.add_argument("--check", action="store_true",
                        help="report whether the patch is applied, change nothing")
    args = parser.parse_args()

    root = Path(args.src) / "src"
    edits = [(root / "lbmlib.c", TGA_ANCHOR, TGA_PATCHED),
             (root / "patches.c", PATCH_ANCHOR, PATCH_PATCHED)]

    for target, _, _ in edits:
        if not target.is_file():
            print(f"not found: {target}")
            return 2

    applied = [MARK in t.read_text(encoding="utf-8", errors="surrogateescape")
               for t, _, _ in edits]

    if args.check:
        print("P8 applied" if all(applied) else "P8 NOT applied")
        return 0 if all(applied) else 1

    if all(applied):
        print("P8 is already applied; nothing to do")
        return 0
    if any(applied):
        print("P8 is applied to some files and not others; refusing to guess")
        return 1

    for target, anchor, patched in edits:
        text = target.read_text(encoding="utf-8", errors="surrogateescape")
        if text.count(anchor) != 1:
            print(f"{target.name}: the anchor does not appear exactly once; "
                  "refusing to guess")
            return 1

    for target, anchor, patched in edits:
        text = target.read_text(encoding="utf-8", errors="surrogateescape")
        target.write_text(text.replace(anchor, patched, 1),
                          encoding="utf-8", errors="surrogateescape")
        print(f"P8 applied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
