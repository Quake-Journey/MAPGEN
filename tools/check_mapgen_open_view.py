"""Can a player see out of a map? Asked of the map alone, and it must be no.

This is the PO's defect stated without a donor. Every other oracle here asks
whether a candidate still draws what the map it came from drew, which is the
right question for a fidelity-100 fork and the wrong one for a map that was
MEANT to change: at fidelity 75 a wall that moved is the operator working.

    from somewhere a player can stand, looking in any direction,
    the eye must reach some drawn surface - a wall, a floor, a sky.

A ray that reaches the edge of the world without meeting one is the strip of
nothing in the middle of a wall that was photographed on 2026-09-01.

    python tools/check_mapgen_open_view.py [--work DIR] [--skip-red]

Cases: the four donors, which are shipped maps and must be clean; and every
mgtest_ map installed for the PO, which must be as clean as they are.

Then two controlled REDs on the check itself, each of which reproduces a number
this instrument actually measured while it was being made wrong:

    counting the sky as undrawn - its faces carry NODRAW, because the compiler
    builds it no lightmap - makes every upward ray in an outdoor map a hole,
    and q2dm1 goes to 45;

    dropping the requirement that the eye be a player's half-width clear of
    the walls puts it ON a wall's own plane, where every ray into that wall
    meets the face at zero distance and reads as nothing at all: q2dm1 goes
    to 29.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\openview")

SOURCES = ["tools/mapgen_open_view.c", "src/mapgen/mapgen_bsp.c",
           "src/shared/shared.c", "tools/mapgen_host_stubs.c"]

DONORS = ["q2dm1", "q2dm2", "q2dm3", "q2dm8"]

# Coarse enough to run in seconds, fine enough that a gap a player would notice
# cannot hide between two standing places.
STEP = "128"
RAYS = "42"

HEAD = re.compile(r"^(\d+) standing places .*?, (\d+) rays each,"
                  r" (\d+) that meet no drawn surface, in (\d+) places", re.M)

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail
                                                     else ""))
    if not ok:
        FAILED += 1
    return ok


def build(tree: Path, out: Path) -> Path:
    exe = out / "open_view.exe"
    if exe.exists():
        exe.unlink()
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"),
         "-I" + str(tree / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(tree / s) for s in SOURCES] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the open-view oracle")
    return exe


def measure(exe: Path, bsp: Path) -> tuple[int, int, int]:
    """Standing places, blind rays, and the places they were seen from."""
    run = subprocess.run([str(exe), str(bsp), "--step", STEP, "--rays", RAYS],
                         capture_output=True, text=True, timeout=3600)
    m = HEAD.search(run.stdout + run.stderr)
    return (int(m.group(1)), int(m.group(3)), int(m.group(4))) if m \
        else (-1, -1, -1)


REDS = [
    ("the sky is counted as undrawn",
     "tools/mapgen_open_view.c",
     "    if ((flags & SURF_NODRAW_BIT) && !(flags & SURF_SKY_BIT))\n"
     "        return false;",
     "    if (flags & SURF_NODRAW_BIT)\n        return false;"),
    ("the eye may stand against a wall",
     "tools/mapgen_open_view.c",
     "            if (boxed_in)\n                continue;",
     "            if (false && boxed_in)\n                continue;"),
]


def red(work: Path) -> int:
    failures = 0
    for name, rel, old, new in REDS:
        tree = work / "red" / re.sub(r"\W+", "_", name)
        if tree.exists():
            shutil.rmtree(tree)
        tree.mkdir(parents=True)
        for sub in ("inc", "src", "tools"):
            shutil.copytree(REPO / sub, tree / sub)
        p = tree / rel
        t = p.read_text(encoding="utf-8")
        if t.count(old) != 1:
            print(f"  FAIL  RED {name}: cannot mutate ({t.count(old)} matches)")
            failures += 1
            continue
        p.write_text(t.replace(old, new, 1), encoding="utf-8")

        exe = build(tree, tree)
        _, blind, _ = measure(exe, CORPUS / "q2dm1.bsp")
        ok = blind > 0
        print(f"  {'PASS' if ok else 'FAIL'}  RED {name}: q2dm1 stops being"
              f" clean  -- {blind} blind rays")
        failures += 0 if ok else 1
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    exe = build(REPO, a.work)

    print("the maps this generator learns from")
    for name in DONORS:
        bsp = CORPUS / f"{name}.bsp"
        if not bsp.is_file():
            check(f"{name} is in the corpus", False, str(bsp))
            continue
        places, blind, spots = measure(exe, bsp)
        check(f"{name}: nowhere to see out of",
              blind == 0 and places > 0,
              f"{places} standing places, {blind} blind rays in {spots} places")

    print("and the maps handed over for testing")
    handed = sorted(MAPS.glob("mgtest_*.bsp"))
    check("there are maps to check", bool(handed), str(MAPS))
    for bsp in handed:
        places, blind, spots = measure(exe, bsp)
        check(f"{bsp.stem}: nowhere to see out of",
              blind == 0 and places > 0,
              f"{places} standing places, {blind} blind rays in {spots} places")

    failures = FAILED
    cases = CASES
    if not a.skip_red:
        print("controlled RED")
        failures += red(a.work)
        cases += len(REDS)

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
