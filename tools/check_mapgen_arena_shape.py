"""An invented map is the SHAPE of its open air, and q2dm1 is that shape.

Three rounds went into the invented map and the PO said the same thing after
each one: a box. The first measure asked whether there was sky straight up and
a shaft with a lid passed it; the second asked how much sky a player owns from
where he stands and a yard with low walls passed that. Both are properties of
the LID. This one is about the space under it, measured by
`tools/mapgen_arena_shape.c`:

    the main open volume is ONE volume, not a row of yards;
    inside it the floors spread over hundreds of units on three storeys or
    more - ledges, walkways and a bridge standing IN the air;
    its walls are dozens of distinct planes, not four;
    no single storey holds more than half the map;
    and the footprint is q2dm1-sized.

    python tools/check_mapgen_arena_shape.py [MAP.bsp] [--red MAP.bsp]

Every threshold is a number q2dm1 answers, and q2dm1 is MEASURED here rather
than quoted. The RED is the map handed to the PO on 2026-09-07 evening.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260908\shape_gate")
RED_DEFAULT = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907"
                   r"\batch6\q2mg_f0\synth\try_0001\q2mg_f0.bsp")

PROBE_SRC = ["tools/mapgen_arena_shape.c", "src/mapgen/mapgen_bsp.c",
             "src/mapgen/mapgen_trace.c", "src/shared/shared.c",
             "tools/mapgen_host_stubs.c"]

FOOTPRINT = re.compile(r"^footprint (\d+) (\d+) (\d+)$", re.M)
BIGGEST = re.compile(r"^biggest storey (\d+) permille$", re.M)
VOLUMES = re.compile(r"^volumes (\d+)$", re.M)
MAIN = re.compile(r"^main places (\d+) size (\d+) (\d+) spread (\d+)"
                  r" storeys (\d+) planes (\d+)$", re.M)
LAMPS = re.compile(r"^lamps (\d+) sharing a sky plane (\d+)$", re.M)

# What an arena is, as numbers q2dm1 answers: its main open volume is 1408 by
# 1216 with its floors spread over 384 units on three storeys and 43 wall
# planes, and its biggest storey holds 286 permille of the map.
REFERENCE = (2496, 2272)
FOOTPRINT_TOLERANCE = 0.25
VOLUME_MIN = 1024
SPREAD_MIN = 384
STOREYS_MIN = 3
PLANES_MIN = 40
FLATTEST_MAX = 400

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def build(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "arena_shape.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / s) for s in PROBE_SRC] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the shape probe")
    return exe


def measure(exe: Path, bsp: Path) -> dict:
    run = subprocess.run([str(exe), str(bsp)], capture_output=True, text=True,
                         timeout=7200)
    out = run.stdout + run.stderr
    got = {"text": out}
    m = FOOTPRINT.search(out)
    got["x"], got["y"] = (int(m.group(1)), int(m.group(2))) if m else (-1, -1)
    m = BIGGEST.search(out)
    got["flattest"] = int(m.group(1)) if m else -1
    m = VOLUMES.search(out)
    got["volumes"] = int(m.group(1)) if m else -1
    m = MAIN.search(out)
    if m:
        got.update(places=int(m.group(1)), w=int(m.group(2)),
                   d=int(m.group(3)), spread=int(m.group(4)),
                   storeys=int(m.group(5)), planes=int(m.group(6)))
    else:
        got.update(places=0, w=0, d=0, spread=0, storeys=0, planes=0)
    m = LAMPS.search(out)
    got["lamps"], got["lamps_sky"] = (int(m.group(1)), int(m.group(2))) \
        if m else (-1, -1)
    return got


def faults(got: dict) -> list[str]:
    wrong = []
    for axis, want, name in ((got["x"], REFERENCE[0], "x"),
                             (got["y"], REFERENCE[1], "y")):
        lo = want * (1.0 - FOOTPRINT_TOLERANCE)
        hi = want * (1.0 + FOOTPRINT_TOLERANCE)
        if not (lo <= axis <= hi):
            wrong.append(f"{axis} units on {name}, not within a quarter of"
                         f" {want}")
    if got["w"] < VOLUME_MIN or got["d"] < VOLUME_MIN:
        wrong.append(f"its main open volume is {got['w']}x{got['d']}, under"
                     f" {VOLUME_MIN}")
    if got["spread"] < SPREAD_MIN:
        wrong.append(f"its floors spread {got['spread']} units, under"
                     f" {SPREAD_MIN} - nothing stands in the air")
    if got["storeys"] < STOREYS_MIN:
        wrong.append(f"{got['storeys']} storeys inside it, under"
                     f" {STOREYS_MIN}")
    if got["planes"] < PLANES_MIN:
        wrong.append(f"{got['planes']} wall planes, under {PLANES_MIN} - a box"
                     f" has four")
    if got["flattest"] > FLATTEST_MAX:
        wrong.append(f"one storey holds {got['flattest']} permille of the map,"
                     f" over {FLATTEST_MAX}")
    return wrong


def summary(got: dict) -> str:
    return (f"{got['x']}x{got['y']}, {got['volumes']} volume(s), main"
            f" {got['w']}x{got['d']} spread {got['spread']} storeys"
            f" {got['storeys']} planes {got['planes']}, flattest"
            f" {got['flattest']} permille, {got['lamps_sky']} of"
            f" {got['lamps']} lamps share a sky plane")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?", type=Path,
                    default=MAPS / "mgtest_f000.bsp")
    ap.add_argument("--red", type=Path, default=RED_DEFAULT)
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()

    exe = build(a.work)

    print("the reference, measured rather than quoted")
    ref = measure(exe, CORPUS / "q2dm1.bsp")
    check("q2dm1 is the arena these numbers describe", not faults(ref),
          summary(ref) if not faults(ref) else "; ".join(faults(ref)))

    if a.red and a.red.is_file():
        print("the map of 2026-09-07 evening, which is the RED")
        red = measure(exe, a.red)
        check("the invented map of 2026-09-07 is a box", bool(faults(red)),
              summary(red))
    else:
        check("the RED artifact is still on disk", False, str(a.red))

    print("and the invented map as it is built today")
    if not a.map.is_file():
        check(f"{a.map.name} is there to be judged", False, str(a.map))
    else:
        got = measure(exe, a.map)
        wrong = faults(got)
        check(f"{a.map.name} is the arena q2dm1 is", not wrong,
              summary(got) if not wrong else "; ".join(wrong))

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
