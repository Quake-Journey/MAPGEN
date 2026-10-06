#!/usr/bin/env python3
"""Local patch P10 for the pinned compiler: EndOfScript frees the same buffer twice.

WHAT IS WRONG

`EndOfScript` (scriplib.c) releases the script's text buffer and then, when the
script is the outermost one, marks the end and returns WITHOUT clearing the
pointer and without popping the script off the stack:

    free(script->buffer);
    if (script == scriptstack + 1) {
        endofscript = true;
        return false;
    }

`script->buffer` still points at the freed block. A parser that keeps asking
for tokens after the end - which is exactly what an unclosed brace makes
`ParseEntity` do - reaches `EndOfScript` a second time on the same script and
frees the same block again.

WHY IT MATTERS

It is the M0Q `malformed_unclosed_brace` failure, and the contract does not
allow that gate to stay red.

MEASURED 2026-09-01: an instrumented build that quarantines freed blocks
instead of returning them reports, on that fixture:

    PROBE DOUBLE FREE: block of 210 bytes from cmdlib.c:692,
                       seen at scriplib.c:150

210 bytes is the fixture's own size: the block is the map text loaded by
`LoadFile`. The CRT raises STATUS_HEAP_CORRUPTION (0xC0000374) when the second
free lands on a block the allocator has already handed out again, which is why
it needed the child's stdout to be a real pipe to reproduce - a pipe makes the
CRT allocate a stdio buffer, and that is what got handed the freed memory.
MEASURED: 20 of 20 under a pipe, 0 of 50 to a console or a file.

Four earlier hypotheses were tested and refuted before this one: a stack
overflow, optimization-sensitive UB from a -Wstringop-overflow warning, the
ChopWindingInPlace estimate overflow, and an over- or underflow of any
allocation the compiler makes (64-byte head and tail guard bands: 0 damaged).

WHAT THE PATCH DOES

Clears the pointer after releasing it, so a second visit frees NULL, which is a
no-op. The script is also popped in the outermost case, so the stack does not
keep a spent entry. Nothing else changes, and the error behaviour is unchanged:
the compiler still refuses the malformed map with a non-zero exit.

    python tools/mapgen_patch_p10_script_double_free.py <staging src dir> [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARK = "MAPGEN-1 P10"

ANCHOR = """    free(script->buffer);
    if (script == scriptstack + 1) {
        endofscript = true;
        return false;
    }
"""

PATCHED = """    /*
     * MAPGEN-1 P10: the pointer used to be left dangling here. A parser that
     * keeps asking for tokens past the end - which an unclosed brace makes
     * ParseEntity do - came back and freed the same block a second time, and
     * the CRT raised STATUS_HEAP_CORRUPTION once the allocator had handed that
     * memory out again.
     */
    free(script->buffer);
    script->buffer = NULL;
    script->script_p = NULL;
    script->end_p = NULL;
    if (script == scriptstack + 1) {
        endofscript = true;
        return false;
    }
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="the staging src/ directory")
    parser.add_argument("--check", action="store_true",
                        help="report whether the patch is applied, change nothing")
    args = parser.parse_args()

    target = Path(args.src) / "src" / "scriplib.c"
    if not target.is_file():
        print(f"not found: {target}")
        return 2

    text = target.read_text(encoding="utf-8", errors="surrogateescape")
    applied = MARK in text

    if args.check:
        print("P10 applied" if applied else "P10 NOT applied")
        return 0 if applied else 1
    if applied:
        print("P10 is already applied; nothing to do")
        return 0
    if text.count(ANCHOR) != 1:
        print("the anchor does not appear exactly once; refusing to guess")
        return 1

    target.write_text(text.replace(ANCHOR, PATCHED, 1),
                      encoding="utf-8", errors="surrogateescape")
    print(f"P10 applied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
