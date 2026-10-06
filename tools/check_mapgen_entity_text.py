r"""Row 403: an entity key or value written from the entity text block itself survives the block growing.

    python tools/check_mapgen_entity_text.py [--work DIR]

The Studio guard's resumed q2dm1 run swapped two pickups, wrote spoiled bytes as an ammo_grenades' class and then
crashed: the swap edit reads the second classname with MapGenGeometry_EntityValue - a pointer into the block - and
MapGenGeometry_SetEntityValue grew the block, which can move it, before copying from that pointer. Whether it moved
depended on the allocator, so the uninterrupted run of the same job was fine.

`tools/mapgen_entity_text_probe.c` is built with MAPGEN_GEOMETRY_TEXT_ALWAYS_MOVES (every growth moves the block and
spoils the old one) and swaps two of q2dm1's pickups until the block has moved twice. GREEN: both names right after
every swap. RED: the same probe against a copy of mapgen_geometry.c whose `text_offset` never finds a string in the
block - the names come out spoiled.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\entity_text")
ANCHOR = b"    return g->text && at >= lo && at < lo + g->text_cap ? (ptrdiff_t)(at - lo) : -1;"

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CASES, FAILED
    CASES += 1
    FAILED += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


def build(geometry: Path, exe: Path) -> str:
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-I" + str(REPO / "inc"),
         "-DMAPGEN_GEOMETRY_TEXT_ALWAYS_MOVES", "-DUSE_LITTLE_ENDIAN=1",
         str(REPO / "tools" / "mapgen_entity_text_probe.c"), str(geometry), str(REPO / "src" / "mapgen" / "mapgen_bsp.c"),
         "-o", str(exe), "-lm", "-lz"], capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-800:]


def probe(exe: Path) -> tuple[int, str]:
    run = subprocess.run([str(exe), str(DONOR)], capture_output=True, text=True, errors="replace", timeout=600)
    return run.returncode, run.stdout.strip().replace("\n", " | ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    print("a pickup's class written from the block, while the block moves")
    green = a.work / "probe.exe"
    err = build(REPO / "src" / "mapgen" / "mapgen_geometry.c", green)
    check("the probe builds against the tree", not err, err)
    if not err:
        rc, out = probe(green)
        check("every swap keeps both names while the block moves", rc == 0, out)

    print("\nRED: the block's strings not re-found after it grows")
    pristine = (REPO / "src" / "mapgen" / "mapgen_geometry.c").read_bytes()
    check("the condition is where it says", pristine.count(ANCHOR) == 1, f"{pristine.count(ANCHOR)} occurrences")
    if pristine.count(ANCHOR) == 1:
        mutated = a.work / "mapgen_geometry.c"
        mutated.write_bytes(pristine.replace(ANCHOR, b"    return -1;", 1))
        red = a.work / "probe_red.exe"
        err = build(mutated, red)
        check("it still builds", not err, err)
        if not err:
            rc, out = probe(red)
            check("a name comes out spoiled - the case above goes red", rc != 0 and "FAIL" in out, out)
    check("the tree was not written", (REPO / "src" / "mapgen" / "mapgen_geometry.c").read_bytes() == pristine)

    print(f"\n{CASES} cases, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
