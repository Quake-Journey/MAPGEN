"""GF6C: the closure a carving edit reasons about, and the six shapes it must get right.

Codex, 2026-09-02, binding ruling Q2: self-exclusion applies to the entire
dependency closure of a proposed edit, not to one brush index. Getting that
wrong fails in two opposite directions from the same mistake - a wall the
compiler cut into three blocks its own edit, and a staircase whose steps are
separate brushes reports itself sealed while a step is carved out from under a
player - so both directions are asserted here.

Six of Codex's ten mandatory REDs are shapes a map can have, so each is a map:

    1  the source brush falsely blocks its own intended edit
    2  adjacent independent reserve solid remains protected
    3  an oblique wedge where AABB reasoning gives the wrong answer
    4  a shared/coplanar seam between logical structures
    5  detail, clip, support and structural brushes in one closure
    6  a mover/model/entity anchor dependency

The remaining four are about the edit rather than the closure and belong to the
transaction: 7 and 8 to the compiler and the render audit, 9 to the reach and
mover gates, and 10 is already asserted in check_mapgen_transaction.py.

    python tools/check_mapgen_closure.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_geometry_fixtures as fixtures  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402
from mapgen_red_support import resolve_anchor  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\closure")

SOURCES = [
    "tools/mapgen_closure_dump.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

FIXTURES = ("closure_split_wall", "closure_reserve", "closure_oblique",
            "closure_seam", "closure_mixed", "closure_mover")

CASES = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
        FAILURES.append(name)
    return bool(ok)


def build(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in SOURCES] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def compile_fixture(work: Path, name: str) -> Path | None:
    """Compile one fixture once; a rebuild costs six seconds and changes
    nothing, so a fixture already built is used as it stands."""
    job = work / name
    bsp = job / f"{name}.bsp"
    if bsp.exists():
        return bsp
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    source = job / f"{name}.map"
    fixtures.FIXTURES[name](source)
    subprocess.run([str(COMPILER), "-bsp", "-threads", "4",
                    "-moddir", str(GAME), "-basedir", str(GAME),
                    "-gamedir", str(GAME), str(source)],
                   capture_output=True, text=True, timeout=1800)
    return bsp if bsp.exists() else None


BRUSH = re.compile(r"^\s+brush\s+(\d+)\s+(\S+)")
ENTITY = re.compile(r"^\s+entity\s+(\d+)\s+(\S+)")


def closure_of(exe: Path, bsp: Path, seed: str, depth: int = 1,
               at: tuple[float, float, float] | None = None) -> dict:
    args = [str(exe), str(bsp), seed, str(depth)]
    if at:
        args += ["--at", f"{at[0]:g}", f"{at[1]:g}", f"{at[2]:g}"]
    run = subprocess.run(args, capture_output=True, text=True, timeout=600)
    out = {"brushes": {}, "entities": {}, "raw": run.stdout,
           "other_solid": None, "seals": None, "error": ""}
    for line in run.stdout.splitlines():
        m = BRUSH.match(line)
        if m:
            out["brushes"][int(m.group(1))] = m.group(2)
            continue
        m = ENTITY.match(line)
        if m:
            out["entities"][int(m.group(1))] = m.group(2)
            continue
        if line.startswith("other solid at"):
            out["other_solid"] = line.strip().endswith("yes")
        elif line.startswith("seals:"):
            out["seals"] = line.strip().endswith("yes")
        elif line.startswith("ERR_"):
            out["error"] = line.strip()
    return out


# The places each fixture put things. Places rather than indices, so the guard
# survives the compiler ordering its brushes differently.
MIDDLE_PIECE = "@192,16,96"
LEFT_PIECE = (64, 16, 96)
RESERVE = (192, 176, 96)
WEDGE = "@32,128,32"
PILLAR = (216, 216, 96)
SEAM_PILLAR = "@32,32,96"
SEAM_WALL = (80, 200, 200)
LEDGE = "@96,48,112"
CLIP = (96, 108, 128)
TRIM = (96, 100, 104)
POST = (96, 48, 48)
DOOR = "@48,16,96"


def behaviour(exe: Path, work: Path) -> None:
    built = {}
    for name in FIXTURES:
        bsp = compile_fixture(work, name)
        if check(f"the {name} fixture compiles", bsp is not None):
            built[name] = bsp

    print("\n=== 1: a wall does not block its own edit")
    if "closure_split_wall" in built:
        c = closure_of(exe, built["closure_split_wall"], MIDDLE_PIECE)
        check("the whole wall is one closure", len(c["brushes"]) >= 3,
              str(c["brushes"]))
        check("the pieces beside the seed came in as coplanar",
              sum(1 for r in c["brushes"].values() if r == "coplanar") >= 2,
              str(c["brushes"]))
        check("there is no other solid inside the seed's own piece",
              c["other_solid"] is False, c["raw"][-200:])
        beside = closure_of(exe, built["closure_split_wall"], MIDDLE_PIECE,
                            at=LEFT_PIECE)
        check("nor inside the piece next to it",
              beside["other_solid"] is False, beside["raw"][-200:])

    print("\n=== 2: the reserve solid beside it stays protected")
    if "closure_reserve" in built:
        c = closure_of(exe, built["closure_reserve"], MIDDLE_PIECE,
                       at=RESERVE)
        check("the independent wall is other solid", c["other_solid"] is True,
              c["raw"][-200:])
        check("and it is not in the closure", len(c["brushes"]) <= 4,
              str(c["brushes"]))

    print("\n=== 3: an oblique wedge, where the bounding box lies")
    if "closure_oblique" in built:
        c = closure_of(exe, built["closure_oblique"], WEDGE, at=PILLAR)
        check("the pillar inside the wedge's box is other solid",
              c["other_solid"] is True, c["raw"][-200:])

    print("\n=== 4: a seam between two structures is not a merge")
    if "closure_seam" in built:
        c = closure_of(exe, built["closure_seam"], SEAM_PILLAR, at=SEAM_WALL)
        check("the wall the pillar leans on is other solid",
              c["other_solid"] is True, c["raw"][-200:])

    print("\n=== 5: detail, clip, support and structural, in one closure")
    if "closure_mixed" in built:
        c = closure_of(exe, built["closure_mixed"], LEDGE)
        for what, place in (("its clip", CLIP), ("its trim", TRIM),
                            ("the post under it", POST)):
            probe = closure_of(exe, built["closure_mixed"], LEDGE, at=place)
            check(f"{what} comes with the ledge", probe["other_solid"] is False,
                  probe["raw"][-200:])
        check("and the closure says so by name",
              len(c["brushes"]) >= 4, str(c["brushes"]))

    print("\n=== 6: a mover, its model and what works it")
    if "closure_mover" in built:
        c = closure_of(exe, built["closure_mover"], DOOR)
        kinds = set(c["entities"].values())
        check("the door itself is in the closure", "func_door" in kinds,
              str(c["entities"]))
        check("so is the button that opens it", "func_button" in kinds,
              str(c["entities"]))

    print("\n=== and it does not run away into the map")
    if CORPUS.joinpath("q2dm1.bsp").exists():
        c = closure_of(exe, CORPUS / "q2dm1.bsp", "200")
        check("a closure on a real donor is a structure, not the level",
              0 < len(c["brushes"]) < 200, str(len(c["brushes"])))


MUTATIONS = {
    "self-exclusion of the seed brush alone": (
        b"""        if (b < c->num_donor_brushes && c->reason[b])
            continue;                    /* it is us; that is the whole point */""",
        b"""        if (b < c->num_donor_brushes
            && c->reason[b] == (uint8_t)(MAPGEN_CLOSURE_SEED + 1))
            continue;                    /* it is us; that is the whole point */""",
    ),
    "a surface that merges on one shared plane": (
        b"""                if (planes_shared(geometry, planes, num_planes, cand) >= 2) {""",
        b"""                if (planes_shared(geometry, planes, num_planes, cand) >= 1) {""",
    ),
    "an entity closure that stops at the door": (
        b"""                if (named(target, on) || named(kill, on) || named(ot, name)
                    || named(ok, name)) {""",
        b"""                if (false) {""",
    ),
}


def red(work: Path) -> None:
    print("\n=== and each of those is load-bearing")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "closure")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_closure.c"
        pristine = target.read_bytes()
        exe = box.root / "red.exe"
        for name, (anchor, replacement) in MUTATIONS.items():
            found, patched, count = resolve_anchor(pristine, anchor,
                                                   replacement)
            if not check(f"{name}: the anchor is where it says", count == 1,
                         f"{count} occurrences"):
                continue
            target.write_bytes(pristine.replace(found, patched, 1))
            err = build(box.root, exe)
            if not check(f"{name}: it still compiles", not err, err):
                target.write_bytes(pristine)
                continue

            if name.startswith("self-exclusion"):
                c = closure_of(exe, work / "closure_split_wall"
                               / "closure_split_wall.bsp", MIDDLE_PIECE,
                               at=LEFT_PIECE)
                check(f"{name}: the wall now blocks its own edit",
                      c["other_solid"] is True, c["raw"][-200:])
            elif name.startswith("a surface"):
                c = closure_of(exe, work / "closure_seam" / "closure_seam.bsp",
                               SEAM_PILLAR, at=SEAM_WALL)
                check(f"{name}: the pillar swallows the wall it leans on",
                      c["other_solid"] is False, c["raw"][-200:])
            else:
                c = closure_of(exe, work / "closure_mover"
                               / "closure_mover.bsp", DOOR)
                check(f"{name}: the button is left behind",
                      "func_button" not in set(c["entities"].values()),
                      str(c["entities"]))
            target.write_bytes(pristine)
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing",
              hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--no-red", action="store_true")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    print("=== the closure module")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1

    exe = args.work / "bin" / "closure.exe"
    err = build(REPO, exe)
    if check("it compiles", not err, err):
        behaviour(exe, args.work)
        if not args.no_red:
            red(args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
