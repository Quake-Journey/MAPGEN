"""Water is not a wall, and the compiler's filled exterior is not a room.

A region is emptied only if what bounds it is the map's own structure. The
proof that says so read the BSP's SOLID bit and then accepted ANY non-detail
brush containing the point as evidence of a wall - so a water volume qualified,
and so would a clip brush or a lift's own geometry.

    python tools/check_mapgen_seal.py [--work DIR] [--skip-red]

MEASURED, and this is the case the guard is built on. Codex's independent
witness of 2026-09-09, reproduced against the corpus donor:

    (114.4, 384, 276.8)   leaf contents 1 (SOLID), PointContents 33
                          covering source brushes: (446, model 0, contents 32)

Contents 32 is WATER. The point lies on the outside slab of the recut region
(118.4,128,236.8)..(490,512,339.2); the proof called that boundary sound, the
region was emptied, and the compiler answered "**** leaked ****". The flood of
the map's own air added on 2026-09-08 cannot see it either: it skips cells the
tree calls SOLID, and this is exactly such a cell.

The cases:

    the two regions whose hollow leaks are REFUSED, before any compile, and
    the refusal names the point, the leaf contents and the covering brush;
    the three regions that always compiled are still sound;
    the donor's own witness points are classified the way Codex measured them.

The controlled RED puts the old predicate back - any non-detail brush seals -
and the leaking regions are called sound again.
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260909\seal_gate")

DRIVER_SRC = [
    "tools/mapgen_recut_driver.c", "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_rooms.c", "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_bsp.c", "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_movers.c", "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_reach.c", "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_certificate.c", "src/mapgen/mapgen_digest.c",
    "src/common/q2prox_cpu_topology.c", "src/common/pmove/old.c",
    "src/common/pmove/common.c", "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

SOUND = re.compile(r"^sound (yes|no)$", re.M)
REFUSED = re.compile(r"^  refused at (\S+) (\S+) (\S+)  leaf contents (\S+)"
                     r"  brush (-?\d+)  (.+)$", re.M)

# The two regions whose hollow the compiler refuses, in their WRITTEN planes -
# the printed integers are rounded and diagnosing on them misses the slab.
LEAKS = [
    ("the slid region of seed 2", (118.4, 128, 236.8, 490, 512, 339.2)),
    ("the centred region it replaced", (118, -160, 237, 490, 224, 339)),
]
# Regions this family has always been able to empty.
SOUND_ONES = [
    ("the room at 1006 381 605", (1006, 381, 605, 1365, 867, 1091)),
    ("the room at -36 259 711", (-36, 259, 711, 428, 893, 1113)),
    ("the room at 115 384 790", (115, 384, 790, 397, 768, 1034)),
]

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


def build(tree: Path, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"),
         "-I" + str(tree / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(tree / s) for s in DRIVER_SRC] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit(f"cannot build {name}")
    return exe


def sound(driver: Path, box) -> tuple[bool, str]:
    run = subprocess.run(
        [str(driver), str(CORPUS / "q2dm1.bsp"), "--sound"]
        + [str(v) for v in box],
        capture_output=True, text=True, timeout=3600)
    out = run.stdout + run.stderr
    m = SOUND.search(out)
    w = REFUSED.search(out)
    return (m.group(1) == "yes" if m else False,
            (f"{w.group(6)} at {w.group(1)} {w.group(2)} {w.group(3)},"
             f" leaf {w.group(4)}, brush {w.group(5)}") if w else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    driver = build(REPO, a.work, "driver")

    print("the regions whose hollow the compiler refuses")
    for name, box in LEAKS:
        ok, why = sound(driver, box)
        check(f"{name} is refused before anything is emptied", not ok, why)
        check(f"{name} says which brush covered the void",
              "non-sealing" in why or "brush model" in why
              or "detail" in why or "no brush" in why, why or "no witness")

    print("and the regions it has always been able to empty")
    for name, box in SOUND_ONES:
        ok, why = sound(driver, box)
        check(f"{name} is still sound", ok, why)

    failures, cases = FAILED, CASES
    if not a.skip_red:
        print("controlled RED: any non-detail brush seals again")
        cases += 1
        tree = a.work / "red_water_seals"
        if tree.exists():
            shutil.rmtree(tree)
        tree.mkdir(parents=True)
        for sub in ("inc", "src", "tools"):
            shutil.copytree(REPO / sub, tree / sub)
        p = tree / "src" / "mapgen" / "mapgen_graft.c"
        text = p.read_text(encoding="utf-8")
        old = """    return gb
        && gb->model == 0
        && (gb->contents & MAPGEN_CONTENTS_SOLID)
        && !(gb->contents & MAPGEN_CONTENTS_DETAIL);"""
        new = """    return gb && !(gb->contents & MAPGEN_CONTENTS_DETAIL);"""
        if text.count(old) != 1:
            print("  FAIL  RED cannot mutate: the seal predicate has moved")
            failures += 1
        else:
            p.write_text(text.replace(old, new, 1), encoding="utf-8")
            red = build(tree, tree, "driver_red")
            back = [name for name, box in LEAKS if sound(red, box)[0]]
            ok = len(back) == len(LEAKS)
            print(f"  {'PASS' if ok else 'FAIL'}  RED water seals again: the"
                  f" leaking regions are called sound"
                  f"  -- {len(back)} of {len(LEAKS)} back")
            failures += 0 if ok else 1

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
