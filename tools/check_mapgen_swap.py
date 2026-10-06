"""GF6C: two rooms of the same donor change places.

Fourth in Codex's operator order, and the first that moves whole PIECES of a
map about rather than editing one in place. It creates and destroys nothing:
two compatible bundles are disjoint sets of brushes and entities, and
exchanging them is two translations through the same transform the turn uses,
so texture axes, anchors and angles travel with the geometry.

Compatible means nothing outside the two could tell, and the fixtures differ in
exactly that:

    swap_twins   two chambers with one way out each, facing each other
    swap_odd     the same two, one chamber a third shorter

    python tools/check_mapgen_swap.py [--work DIR] [--no-red]
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\swap")

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


COUNT = re.compile(r"^\s+swap-bundles\s+(\d+)")
EDIT = re.compile(r"^edit (\d+) swap-bundles: (\w+)")


def planned(exe: Path, bsp: Path) -> int:
    run = subprocess.run([str(exe), str(bsp), "1"], capture_output=True,
                         text=True, timeout=600)
    for line in run.stdout.splitlines():
        m = COUNT.match(line)
        if m:
            return int(m.group(1))
    return -1


def applied(exe: Path, bsp: Path) -> tuple[bool, str]:
    run = subprocess.run([str(exe), str(bsp), "1", "--only", "swap-bundles",
                          "--apply", "0"], capture_output=True, text=True,
                         timeout=600)
    for line in run.stdout.splitlines():
        m = EDIT.match(line)
        if m:
            return m.group(2) == "applied", run.stdout
    return False, run.stdout


def static_contract() -> None:
    print("\n=== what makes two rooms exchangeable")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry_edit.h").read_text(
        encoding="utf-8", errors="replace")

    check("both have to be able to carry their own shells",
          "!MapGenBundle_Movable(a)" in impl and "!MapGenBundle_Movable(b)"
          in impl)
    check("the same number of ways out",
          "sockets != MapGenBundle_NumSockets(b)" in impl)
    check("in the same directions, with the same kinds",
          "socket_way(yours, there, theirs)" in impl
          and "yours->kind != mine->kind" in impl)
    check("after whichever of the eight turns lines them up",
          "for (uint32_t which = 0; which < 8; which++)" in impl)
    check("and no obligation lost",
          "mine->obligation && !yours->obligation" in impl)
    # Asked per TRANSFORM, because a quarter turn swaps the two floor axes and
    # a room 256 by 512 is a room 512 by 256 turned.
    check("each one's air fits where the other's was, turned the way this"
          " candidate turns it",
          "fabsf(turned[k] - b_span[k]) <= 64.0f" in impl
          and "(exchange && (q & 1u)) ? a_span[1] : a_span[0]" in impl)
    # And one for one: b's ways out may not answer for two of a's. The graft
    # asks the same predicate with `exchange` false - it clears a region grown
    # to hold what arrives rather than exchanging anything - so the bijection
    # and the turned-size test are both conditioned on it.
    check("the ways out pair off one for one when the rooms are exchanged",
          "bool taken[MAPGEN_BUNDLE_MAX_SOCKETS]" in impl
          and "if (exchange && taken[o])" in impl
          and "taken[o] = true;" in impl)
    check("a pair is planned once, from the lower of the two",
          "for (uint32_t j = i + 1;" in impl)
    # One question, asked by both operators. Two spellings of it is how two
    # operators come to disagree about what compatible means.
    check("the test is written once and the swap asks it",
          "static bool interchangeable(const mapgen_bundle_t *a," in impl
          and "if (!interchangeable(a, b, true, &chosen_quarter," in impl)

    print("\n=== and what the exchange does")

    check("nothing is created and nothing destroyed",
          "MapGenGeometry_TransformSubset(candidate, a_brush" in impl
          and "MapGenGeometry_TransformSubset(candidate, b_brush" in impl)
    check("what both of them own stays where it is",
          "a_brush[i] = 0;" in impl and "b_brush[i] = 0;" in impl)
    check("a brush that went missing stops the whole swap",
          "named == s->a_num_brushes + s->b_num_brushes" in impl)
    check("the header says why this operator is worth its size",
          "different arrangement" in header)


def behaviour(exe: Path, work: Path) -> None:
    print("\n=== two chambers with the same way out")
    twins = compile_fixture(work, "swap_twins")
    if check("the twins fixture compiles", twins is not None):
        offered = planned(exe, twins)
        check("the pair is offered a swap", offered > 0, f"{offered} planned")
        did, out = applied(exe, twins)
        check("and exchanging them changes the map", did, out[-300:])

    print("\n=== and one of them a third shorter")
    odd = compile_fixture(work, "swap_odd")
    if check("the odd fixture compiles", odd is not None):
        offered = planned(exe, odd)
        check("no swap of that pair is offered", offered == 0,
              f"{offered} planned")


# The size test, because that is what refuses this pair. The direction test was
# mutated first and the pair still refused - the odd fixture differs in size,
# not in where its ways out point - so that mutation could not fail here.
#
# The test moved INSIDE the per-transform loop on 2026-09-09: a quarter turn
# swaps the two floor axes, so comparing untransformed extents refused a room
# that is another room turned and accepted pairs on turns that do not fit.
MUTATION = (
    b"""                same_size = fabsf(turned[k] - b_span[k]) <= 64.0f;""",
    b"""                same_size = true; (void)turned;""",
)


def red(exe: Path, work: Path) -> None:
    print("\n=== and the size is what refuses the odd pair")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "swap")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        data = target.read_bytes()
        anchor, replacement, count = resolve_anchor(data, *MUTATION)
        if not check("the size test is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(data.replace(anchor, replacement, 1))
        red_exe = box.root / "red.exe"
        err = build(box.root, red_exe)
        if not check("the mutated planner still compiles", not err, err):
            return
        offered = planned(red_exe, work / "swap_odd" / "swap_odd.bsp")
        check("without it the odd pair is offered a swap anyway", offered > 0,
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

    print("=== exchanging two rooms of one donor")
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
