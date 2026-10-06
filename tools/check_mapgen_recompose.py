"""GF7 groundwork: a CYCLE of rooms of one donor changes places at once.

The swap moves a pair, and a map rearranged pair by pair is still the donor's
arrangement with some pairs exchanged - which is why the schedule spends its
whole budget at fidelity 25 and lands short of the band. A recomposition moves
three or more rooms round a cycle as ONE typed edit with one verdict, so what
changed is the arrangement itself.

It is the swap's safety at the swap's price: nothing is created and nothing is
destroyed, every pair in the cycle passes the swap's own interchangeability
test, and anything two members both own stays where it is.

The fixtures differ in exactly what the operator is about:

    recompose_ring   four chambers round one hub, all interchangeable
    recompose_pair   the same ring with two chambers made shorter, so only
                     two are left - which is a swap, not a recomposition

    python tools/check_mapgen_recompose.py [--work DIR] [--no-red]
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\recompose")

PROBE = [
    "tools/mapgen_edit_probe.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

CASES = 0
FAILURES: list[str] = []

COUNT = re.compile(r"^\s+recompose-bundles\s+(\d+)")
EDIT = re.compile(r"^edit (\d+) recompose-bundles: (\w+)")


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
        + [str(root / s) for s in PROBE] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def compile_fixture(work: Path, name: str) -> Path | None:
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


def planned(exe: Path, bsp: Path) -> int:
    run = subprocess.run([str(exe), str(bsp), "1"], capture_output=True,
                         text=True, timeout=600)
    for line in run.stdout.splitlines():
        m = COUNT.match(line)
        if m:
            return int(m.group(1))
    return -1


def applied(exe: Path, bsp: Path) -> tuple[bool, str]:
    run = subprocess.run([str(exe), str(bsp), "1", "--only",
                          "recompose-bundles", "--apply", "0"],
                         capture_output=True, text=True, timeout=600)
    for line in run.stdout.splitlines():
        m = EDIT.match(line)
        if m:
            return m.group(2) == "applied", run.stdout
    return False, run.stdout


def static_contract() -> None:
    print("\n=== what a cycle is, and what it costs")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry_edit.h").read_text(
        encoding="utf-8", errors="replace")

    check("the operator exists and is structural",
          "MAPGEN_EDIT_RECOMPOSE_BUNDLES" in header
          and "[MAPGEN_EDIT_RECOMPOSE_BUNDLES] = 0," in impl,
          "an edit that cannot move an axis cannot reach a band")
    check("three is the least that is a cycle rather than a pair",
          "#define RECOMPOSE_MIN   3" in impl
          and "r->count < RECOMPOSE_MIN" in impl)
    check("it asks the swap's own question of every pair",
          "if (interchangeable(last, MapGenBundleSet_At(set, j), true," in impl,
          "two spellings of one question is how two operators disagree")
    check("a chain that has to close",
          "while (members >= RECOMPOSE_MIN" in impl
          and "MapGenBundleSet_At(set, member[0]), true," in impl,
          "a cycle needs each member to take the NEXT one's place and the "
          "last to take the first's - four edges for four members, not six")
    check("every member travels to the next one's middle",
          "const uint32_t next = (m + 1) % r->count;" in impl)
    check("nothing is created and nothing destroyed",
          "MapGenGeometry_TransformSubset(candidate, brush_of[m]," in impl)
    check("what more than one member owns stays where it is",
          "if (owners > 1)" in impl)
    check("a brush that went missing stops the whole cycle",
          "ok = named == wanted;" in impl)
    check("the header says why this operator is worth its size",
          "A cycle rearranges the" in header)


def behaviour(exe: Path, work: Path) -> None:
    print("\n=== four chambers round one hub")
    ring = compile_fixture(work, "recompose_ring")
    if check("the ring fixture compiles", ring is not None):
        offered = planned(exe, ring)
        check("a cycle is offered", offered > 0, f"{offered} planned")
        did, out = applied(exe, ring)
        check("and recomposing them changes the map", did, out[-400:])

    print("\n=== and the same ring with only two left")
    pair = compile_fixture(work, "recompose_pair")
    if check("the pair fixture compiles", pair is not None):
        offered = planned(exe, pair)
        check("no cycle is offered where only two are interchangeable",
              offered == 0, f"{offered} planned")


# Three is what makes it a cycle. With the floor at two the pair fixture -
# which is a swap and nothing more - is offered a "recomposition", and the
# operator stops being the thing it exists to be.
MUTATION = (
    b"""#define RECOMPOSE_MIN   3""",
    b"""#define RECOMPOSE_MIN   2""",
)


def red(exe: Path, work: Path) -> None:
    print("\n=== and three is what makes it a cycle")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "recompose")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        data = target.read_bytes()
        anchor, replacement, count = resolve_anchor(data, *MUTATION)
        if not check("the floor is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(data.replace(anchor, replacement, 1))
        red_exe = box.root / "red.exe"
        err = build(box.root, red_exe)
        if not check("the mutated planner still compiles", not err, err):
            return
        offered = planned(red_exe,
                          work / "recompose_pair" / "recompose_pair.bsp")
        check("without it a mere pair is called a recomposition", offered > 0,
              f"{offered} planned")
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

    print("=== recomposing a cycle of rooms")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()

    exe = args.work / "bin" / "probe.exe"
    err = build(REPO, exe)
    if check("the probe compiles", not err, err):
        behaviour(exe, args.work)
        if not args.no_red:
            red(exe, args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
