#!/usr/bin/env python3
"""MAPGEN-1 R3 - the spatial blueprint, checked against an independent oracle.

Contract section 5.4.1. This is the module that made the PO's fidelity control
possible at all: Training used to keep only aggregates - how many regions, how
many height bands, what share is sky - and threw the map's shape away, so a
0..100 control had nothing to interpolate towards at any setting.

Two halves, as everywhere else in this tree:

  * STATIC - properties that hold by construction, read off comment-stripped
    source in a form a mutation cannot leave standing;
  * BEHAVIOURAL - the real compiled module run over real shipped maps, and
    every number compared against `tools/mapgen_blueprint_oracle.py`, which
    shares no code with it.

A `region` is not a volume, and this guard says so explicitly: the stance
graph's connected components number 81 on q2dm1 and not one of them is a room.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_build_target as build_target  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import mapgen_blueprint_oracle as oracle                    # noqa: E402

MAP_DIRS = [
    Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus"),
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
]
# Deliberately several shapes: a stock deathmatch map, a duel map, a large
# converted one. Retail q2dm1 is never the only fixture (Codex, 2026-09-01).
MAPS = ["q2dm1.bsp", "q2duel1.bsp", "ptrip.bsp"]

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def find_map(name: str) -> Path | None:
    for directory in MAP_DIRS:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    print("=== MAPGEN-1 R3 blueprint contract")

    src = strip_comments((REPO / "src" / "mapgen" / "mapgen_blueprint.c")
                         .read_text(encoding="utf-8", errors="surrogateescape"))
    hdr = strip_comments((REPO / "inc" / "common" / "mapgen_blueprint.h")
                         .read_text(encoding="utf-8", errors="surrogateescape"))

    # --- static ------------------------------------------------------------
    check("a volume is not the stance graph's region",
          "->region" not in src,
          "`region` is a connected component over walk/step/swim edges - 81 of "
          "them on q2dm1 - and renaming it to a room is the same mistake in "
          "new words")
    check("the hall class is dilated before components are taken",
          "grown[edge->to] = MAPGEN_VOLUME_HALL" in src
          and src.index("grown[edge->to] = MAPGEN_VOLUME_HALL")
              < src.index("for (uint32_t start = 0; start < nodes; start++)"),
          "a stance beside a wall loses half its walk neighbours; without the "
          "dilation every hall is ringed with slivers - 459 of them on q2dm1")
    check("only walk and step edges merge two stances into one volume",
          "return kind == MAPGEN_EDGE_WALK || kind == MAPGEN_EDGE_STEP;" in src,
          "in that exact form: a jump or a drop REACHES another volume, it "
          "does not make two into one")
    check("a dead-end passage is absorbed into what it hangs off",
          "absorb_dead_ends" in src and "touches[v] != 1" in src,
          "a corridor connects two volumes; a component touching one is the "
          "edge of that one")
    check("the basis is the layout grid",
          "#define MAPGEN_BLUEPRINT_BASIS        16" in hdr,
          "a volume quantized to anything else lands off the grid it will be "
          "rebuilt on")
    check("raw source geometry is never stored",
          not any(word in src for word in ("dbrushes", "dplanes", "brushsides",
                                           "MapGenBsp_Brush")),
          "contract 15: a blueprint is the project's own description of "
          "playable space, not the source's brushwork")
    # The rule protects the PO's binary, not the generator: a module the
    # packaged helper runs has to be linked somewhere, and mapgen_src is the
    # somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_blueprint.c")
    check("the module reaches no build the PO runs", in_helper, why)

    # --- behavioural -------------------------------------------------------
    driver = REPO / "tools" / "mapgen_blueprint_test_driver.c"
    exe = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\blueprint_driver.exe")
    exe.parent.mkdir(parents=True, exist_ok=True)
    sources = [driver] + [REPO / "src" / "mapgen" / f"mapgen_{n}.c"
                          for n in ("blueprint", "space", "trace", "genome", "bsp")]
    build = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I", str(REPO / "inc"), *[str(s) for s in sources], "-o", str(exe), "-lz"],
        capture_output=True, text=True)
    check("it compiles with -Wall -Wextra -Werror", build.returncode == 0,
          (build.stdout + build.stderr)[-400:])
    if build.returncode != 0:
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1

    for name in MAPS:
        path = find_map(name)
        if not path:
            check(f"{name}: present", False, "not found in any map directory")
            continue

        run = subprocess.run([str(exe), str(path)], capture_output=True, text=True,
                             timeout=1800)
        for line in run.stdout.splitlines():
            if line.startswith("CASE "):
                verdict, case, detail = line[5:].split("|", 2)
                check(f"{path.stem}: {case}", verdict == "PASS", detail)

        body = run.stdout.partition("BLUEPRINT-BEGIN\n")[2].partition("BLUEPRINT-END")[0]
        want = oracle.canonical_text(oracle.build(path))
        if body == want:
            check(f"{path.stem}: the two implementations agree exactly", True, "")
            continue

        mine = body.splitlines()
        theirs = want.splitlines()
        first = next((i for i in range(max(len(mine), len(theirs)))
                      if (mine[i] if i < len(mine) else None)
                      != (theirs[i] if i < len(theirs) else None)), 0)
        check(f"{path.stem}: the two implementations agree exactly", False,
              f"line {first + 1}: C={mine[first] if first < len(mine) else '<eof>'} "
              f"py={theirs[first] if first < len(theirs) else '<eof>'}")

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    print("RESULT: " + ("PASS" if not FAILED else "FAIL"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
