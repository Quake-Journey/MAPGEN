"""An invented map has to be an ARENA, and q2dm1 is the shape of one.

The PO walked the map this generator invented and called it a corridor map:
"придумай мне с нуля нормальную карту у которой красивая архитектура, много
неба над головой и не огромную, а нормальных размеров как q2dm1 с не более чем
четырьмя уровнями высоты над поверхностью воды и не более чем одним уровнем под
водой".

So the reference is q2dm1, measured by `tools/mapgen_arena_probe.c` rather
than described:

    footprint          2496 x 2272
    under sky          531 permille of the standing places
    storeys            5   (four above its upper pool and one below)
    material families  3

    python tools/check_mapgen_arena.py [MAP.bsp] [--red MAP.bsp]

With no argument it judges the invented map that is installed for the PO. The
RED is the one that was handed over on 2026-09-07: 5,184 units deep, 80
permille of its floor outdoors, two storeys and four episodes' textures. It
fails every one of these, which is what makes them worth checking.
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
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\arena_gate")

PROBE_SRC = ["tools/mapgen_arena_probe.c", "src/mapgen/mapgen_bsp.c",
             "src/shared/shared.c", "tools/mapgen_host_stubs.c"]

FOOTPRINT = re.compile(r"footprint (\d+) x (\d+) x (\d+)")
SKY = re.compile(r"standing places (\d+), under sky (\d+) \((\d+) permille\)")
LEVELS = re.compile(r"floor levels (\d+)")
FAMILIES = re.compile(r"material families (\d+)")

# What the arena has to be, as a share of what the reference is. Everything
# here is a number q2dm1 itself meets.
FOOTPRINT_TOLERANCE = 0.25
SKY_FLOOR_PERMILLE = 400
STOREYS_MIN = 3

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
    exe = out / "arena_probe.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-I" + str(REPO / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / s) for s in PROBE_SRC] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the arena probe")
    return exe


def measure(probe: Path, bsp: Path) -> dict:
    run = subprocess.run([str(probe), str(bsp)], capture_output=True,
                         text=True, timeout=3600)
    out = run.stdout
    f = FOOTPRINT.search(out)
    s = SKY.search(out)
    l = LEVELS.search(out)
    m = FAMILIES.search(out)
    if not (f and s and l and m):
        return {"error": (run.stdout + run.stderr)[-300:]}
    return {"x": int(f.group(1)), "y": int(f.group(2)),
            "stands": int(s.group(1)), "sky": int(s.group(3)),
            "storeys": int(l.group(1)), "families": int(m.group(1))}


def judge(name: str, got: dict, ref: dict, log: bool = True) -> list[str]:
    """Every way this map is not the arena the reference is."""
    wrong = []
    for axis, key in ((0, "x"), (1, "y")):
        lo = ref[key] * (1.0 - FOOTPRINT_TOLERANCE)
        hi = ref[key] * (1.0 + FOOTPRINT_TOLERANCE)
        if not (lo <= got[key] <= hi):
            wrong.append(f"{got[key]} units on {'xy'[axis]}, not within a"
                         f" quarter of {ref[key]}")
    if got["sky"] < SKY_FLOOR_PERMILLE:
        wrong.append(f"{got['sky']} permille of the floor is outdoors,"
                     f" under {SKY_FLOOR_PERMILLE}")
    if got["storeys"] > ref["storeys"]:
        wrong.append(f"{got['storeys']} storeys, more than {ref['storeys']}")
    if got["storeys"] < STOREYS_MIN:
        wrong.append(f"{got['storeys']} storeys, fewer than {STOREYS_MIN}")
    if got["families"] > ref["families"]:
        wrong.append(f"{got['families']} material families, more than"
                     f" {ref['families']}")
    if log:
        check(f"{name} is the arena q2dm1 is", not wrong,
              "; ".join(wrong) if wrong
              else f"{got['x']}x{got['y']}, {got['sky']} permille outdoors,"
                   f" {got['storeys']} storeys, {got['families']} families")
    return wrong


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?", type=Path,
                    default=MAPS / "mgtest_f000.bsp")
    ap.add_argument("--red", type=Path, default=MAPS / "mgtest_f000.bsp")
    ap.add_argument("--donor", type=Path, default=CORPUS / "q2dm1.bsp")
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()

    probe = build(a.work)

    print("the reference")
    ref = measure(probe, a.donor)
    if "error" in ref:
        check("q2dm1 can be measured", False, ref["error"])
        return 1
    check("q2dm1 measures as the arena it is",
          ref["sky"] >= SKY_FLOOR_PERMILLE and ref["storeys"] >= STOREYS_MIN,
          f"{ref['x']}x{ref['y']}, {ref['sky']} permille outdoors,"
          f" {ref['storeys']} storeys, {ref['families']} families")

    print("the invented map")
    if not a.map.is_file():
        check(f"{a.map.name} is there to be judged", False, str(a.map))
        return 1
    got = measure(probe, a.map)
    if "error" in got:
        check(f"{a.map.name} can be measured", False, got["error"])
        return 1
    judge(a.map.stem, got, ref)

    failures = FAILED
    cases = CASES
    if not a.skip_red and a.red.is_file() and a.red.resolve() != a.map.resolve():
        print("the map that was handed over - the RED")
        cases += 1
        red = measure(probe, a.red)
        wrong = judge(a.red.stem, red, ref, log=False)
        ok = bool(wrong)
        print(f"  {'PASS' if ok else 'FAIL'}  {a.red.stem} as delivered is not"
              f" an arena  -- " + ("; ".join(wrong) if wrong
                                   else "it passes, so this proves nothing"))
        failures += 0 if ok else 1

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
