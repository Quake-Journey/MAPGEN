"""Codex's mandatory carving REDs 7 to 9: what an edit LEAVES behind.

The closure fixtures answer the first six, which are all about what an edit is
allowed to TAKE - its own brush, the reserve beside it, the wedge, the seam, the
mixed closure, the mover's anchor - and `check_mapgen_closure.py` owns them. The
transaction's immutability self-check answers the tenth. These three are the
ones nobody could ask until there was a boundary to ask them of:

    7  an intentional leak, known only by its pointfile, is refused
    8  a visible seam or a face that does not reconstruct is refused
    9  an edit that breaks the map is refused on what CAME OUT of it

Seven and nine are answered by driving the real transaction: a compiler that
leaks silently and drops a .pts, and a room whose player starts stand exactly
where the block operator builds. Eight needed a new question - how many surfaces
of a map a compiler cannot build cleanly - and asking it found a real defect on
the product path the same day: every platform the block operator built came with
a step that split the platform's own face, which is the hairline that sparkles.

    python tools/check_mapgen_carving.py [--work DIR] [--no-red]
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\carving")

DRIVER = [
    "tools/mapgen_transaction_driver.c",
    "src/mapgen/mapgen_transaction.c",
    "src/mapgen/mapgen_equivalence.c",
    "src/mapgen/mapgen_compiler.c",
    "src/mapgen/mapgen_divergence.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_reach.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

PROBE = [
    "tools/mapgen_surface_probe.c",
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


def build(root: Path, sources: list[str], out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in sources] + ["-o", str(out), "-lm"],
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


FAULTS = re.compile(r"^surface faults: (\d+)", re.M)
# Only the attempt lines, which are indented: \s would eat the newline
# and swallow the next line into this one's tail.
STEP = re.compile(r"^ +(\d+) (\S+) +([A-Z_]+) *(.*)$", re.M)


def faults_of(probe: Path, bsp: Path) -> int:
    run = subprocess.run([str(probe), str(bsp)], capture_output=True,
                         text=True, timeout=600)
    m = FAULTS.search(run.stdout)
    return int(m.group(1)) if m else -1


def attempt(driver: Path, compiler: str, bsp: Path, job: Path, name: str,
            kind: str = "room-block", limit: int = 2,
            seed: int = 1) -> list[tuple[str, str]]:
    """Run the real transaction and return each attempt's verdict and tail.

    The seed decides the schedule - which edits are proposed and in what order -
    so a case that depends on a particular schedule says which one it means.
    """
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    #
    # `--crates` asks the planner for the room block, which no product
    # schedule deals any more: the PO rejected the heap of platforms it makes
    # in every batch he walked, on 2026-09-10 «это не часть архитектуры
    # измененной, это просто мусорница». This guard is not about the block. It
    # is about the transaction's gates - surface faults, the leak, the buried
    # spawn - and it drives them with the operator that builds the most
    # brushwork on a bare fixture, which is still that one. Retiring the
    # vehicle would leave every case here asking its question of an empty
    # schedule and PASSING for it.
    #
    run = subprocess.run([str(driver), compiler, str(bsp), str(job), name,
                          str(GAME), str(seed), str(limit), "--only", kind,
                          "--crates"],
                         capture_output=True, text=True, timeout=3600)
    return [(m.group(3), m.group(4).strip()) for m in STEP.finditer(run.stdout)]


def static_contract() -> None:
    print("\n=== the module owns the question, the transaction asks it")

    geometry = (REPO / "src" / "mapgen" / "mapgen_geometry.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry.h").read_text(
        encoding="utf-8", errors="replace")
    txn = (REPO / "src" / "mapgen" / "mapgen_transaction.c").read_text(
        encoding="utf-8", errors="replace")
    txn_h = (REPO / "inc" / "common" / "mapgen_transaction.h").read_text(
        encoding="utf-8", errors="replace")

    check("the count is the geometry module's, not an operator's",
          "uint32_t MapGenGeometry_SurfaceFaults(const mapgen_geometry_t *g,"
          in geometry and "MapGenGeometry_SurfaceFaults" in header)
    check("it counts a face that did not reconstruct",
          "if (!sides[s].bevel)" in geometry)
    check("planes that enclose nothing",
          "if (!shaped && brush->num_sides)" in geometry)
    check("and a vertex stranded in the middle of a neighbour's edge",
          "static bool splits_edge(" in geometry)
    check("a shared corner is how faces are SUPPOSED to meet",
          "(1.0 - t) * len <= OFF_CORNER" in geometry)
    check("only where somebody could stand in front of it",
          "anyone_can_see(space, v, pt->normal)" in geometry)

    #
    # The ORDER, not the spelling. The retain point now keeps the verdict in a
    # variable so a kept graft can be credited to the donor it came from, so
    # the call is the anchor rather than `return judge(...)`.
    #
    check("the transaction asks after the edit and before the write",
          txn.index("step->faults_after = MapGenGeometry_SurfaceFaults(candidate")
          < txn.index("judge(txn, candidate, attempt, true, step)"))
    check("what it is held to is the accepted candidate's own count",
          "if (step->faults_after > txn->accepted_faults)" in txn)
    check("a refusal on this ground has a verdict of its own",
          "MAPGEN_TXN_REJECTED_SURFACE" in txn_h
          and "return \"REJECTED_SURFACE\"" in txn)
    check("an accepted candidate carries the count that was taken of IT",
          "txn->accepted_faults = step->faults_after;" in txn)
    check("materialising carries it rather than retaking it",
          "step->faults_after = txn->accepted_faults;" in txn)


def behaviour(probe: Path, driver: Path, work: Path) -> None:
    print("\n=== what a T-junction is")
    flush = compile_fixture(work, "surface_flush")
    tee = compile_fixture(work, "surface_tee")
    if check("both fixtures compile", flush is not None and tee is not None):
        check("two blocks of the same height leave nothing to see",
              faults_of(probe, flush) == 0, str(faults_of(probe, flush)))
        check("one of them shorter splits the other's edge, on both sides",
              faults_of(probe, tee) == 2, str(faults_of(probe, tee)))

    print("\n=== RED 8: an edit may not leave one")
    plain = compile_fixture(work, "reshape_plain")
    if check("the plain room compiles", plain is not None):
        check("and it has nothing to see either", faults_of(probe, plain) == 0,
              str(faults_of(probe, plain)))
        got = attempt(driver, str(COMPILER), plain, work / "jobs" / "plain",
                      "reshape_plain")
        taken = [(v, tail) for v, tail in got if v == "ACCEPTED"]
        check("a platform built in it is accepted", bool(taken), str(got))
        #
        # The contract of RED 8, and the only thing this section is about: an
        # edit that goes in may not leave a T-junction behind it.
        #
        check("and it left nothing to see",
              bool(taken) and all("faults 0" in tail for _, tail in taken),
              str(got))
        #
        # And an attempt that is not accepted has to be REFUSED by name.
        #
        # This used to read "every attempt is accepted", which is a statement
        # about which edits the planner happens to pick and not about faults.
        # Since each edit family got its own substream, seed 1's second
        # room-block lands somewhere that changes nothing - and a transaction
        # that quietly counted that as a success would be the real defect.
        #
        refused = [v for v, _ in got if v != "ACCEPTED"]
        check("and anything that changed nothing is refused by name",
              all(v.startswith("REJECTED_") for v in refused), str(refused))

        #
        # The planner can still make a SECOND effective edit on this fixture -
        # measured, because otherwise the case above would pass just as well
        # for a planner that had stopped being able to.
        #
        # Seed 1 is the one this section runs, and its schedule happens to put
        # a no-op second. Another seed is asked here so that "the second edit
        # was refused" is known to be this schedule's shape rather than a
        # planner that can no longer build twice in the same room.
        #
        twice = attempt(driver, str(COMPILER), plain,
                        work / "jobs" / "plain_seed2", "reshape_plain",
                        seed=2)
        accepted_twice = [v for v, _ in twice if v == "ACCEPTED"]
        check("and the planner can still build twice in the same room",
              len(accepted_twice) >= 2, str(twice))
        check("both of those left nothing to see either",
              all("faults 0" in tail for v, tail in twice if v == "ACCEPTED"),
              str(twice))

    print("\n=== RED 7: a leak known only by its pointfile")
    #
    # It has to leak the CANDIDATE and not the baseline.
    #
    # A transaction's first compile is the reference it measures against, so a
    # compiler that leaks at every invocation never reaches an edit - the
    # transaction refuses to open, which is right and is the pipeline guard's
    # ERR_BASELINE case. RED 7 is about an edit whose own compile leaks, so
    # this succeeds once and leaks from then on.
    leaky = work / "leaky.cmd"
    shim = work / "leaky.py"
    shim.write_text(
        "import subprocess, sys\n"
        "# Which compile is this? The baseline goes in <job>/baseline and\n"
        "# every attempt in <job>/try_NNNN, and a draft profile runs more\n"
        "# than one stage - so counting invocations gave the baseline's\n"
        "# SECOND stage to the leaking compiler and the reference failed\n"
        "# before any edit was tried.\n"
        "baseline = any('baseline' in a for a in sys.argv[1:])\n"
        "if baseline:\n"
        "    sys.exit(subprocess.run([r'" + str(COMPILER) + "']\n"
        "                           + sys.argv[1:]).returncode)\n"
        "sys.exit(subprocess.run([sys.executable, r'"
        + str(REPO / "tools" / "mapgen_fake_compiler.py")
        + "', '--behavior', 'zero_exit_leak_pts_only']\n"
        "                       + sys.argv[1:]).returncode)\n",
        encoding="ascii")
    leaky.write_text(
        "@echo off\r\n"
        f'python "{shim}" %*\r\n', encoding="ascii")
    if plain:
        got = attempt(driver, str(leaky), plain, work / "jobs" / "leak",
                      "reshape_plain")
        check("every attempt is refused",
              bool(got) and all(v == "REJECTED_COMPILE" for v, _ in got),
              str(got))
        check("and the reason names the leak, not the exit code",
              bool(got) and all("ERR_LEAKED" in tail for _, tail in got),
              str(got))

    print("\n=== RED 9: an edit that breaks the map it came from")
    spawns = compile_fixture(work, "carve_spawns")
    if check("the four-corner fixture compiles", spawns is not None):
        got = attempt(driver, str(COMPILER), spawns, work / "jobs" / "spawns",
                      "carve_spawns")
        check("burying a player start is refused on the compiled candidate",
              bool(got) and all(v == "REJECTED_UNPLAYABLE" for v, _ in got),
              str(got))


SEAM_TEST = (
    b"""    return fabsf(a->normal[0] - b->normal[0]) <= SAME_NORMAL""",
    b"""    return false && fabsf(a->normal[0] - b->normal[0]) <= SAME_NORMAL""",
)

# The step's inset, as `shape_block` writes it today. It used to be spelled
# with the caller's local (`block.step[...]`) and the guard went on quoting
# that after the shaping moved into a function of its own, so the RED it is
# the anchor for silently stopped being applied - 0 occurrences, and a case
# that reported the drift rather than the contract.
STEP_INSET = (
    b"""    b->step[0][1] = b->mins[1] + 16.0f;
    b->step[1][1] = b->maxs[1] - 16.0f;""",
    b"""    b->step[0][1] = b->mins[1];
    b->step[1][1] = b->maxs[1];""",
)

THE_GATE = (
    b"""    if (step->faults_after > txn->accepted_faults) {""",
    b"""    if (false) {""",
)


def red(work: Path) -> None:
    before = hash_tree(REPO)
    box = Sandbox(REPO, "carving")
    try:
        geometry = box.root / "src" / "mapgen" / "mapgen_geometry.c"
        edit = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        transaction = box.root / "src" / "mapgen" / "mapgen_transaction.c"
        pristine = {p: p.read_bytes()
                    for p in (geometry, edit, transaction)}

        print("\n=== and the seam test is what sees the seam")
        data = pristine[geometry]
        anchor, patched, count = resolve_anchor(data, *SEAM_TEST)
        if check("the plane test is where it says", count == 1,
                 f"{count} occurrences"):
            geometry.write_bytes(data.replace(anchor, patched, 1))
            probe = box.root / "red_probe.exe"
            err = build(box.root, PROBE, probe)
            if check("the mutated probe compiles", not err, err):
                got = faults_of(probe, work / "surface_tee" / "surface_tee.bsp")
                check("without it the split fixture reads clean", got == 0,
                      str(got))
            geometry.write_bytes(data)

        print("\n=== and the step really was cracking the platform")
        data = pristine[edit]
        anchor, patched, count = resolve_anchor(data, *STEP_INSET)
        if not check("the step's clearance is where it says", count == 1,
                     f"{count} occurrences"):
            return
        edit.write_bytes(data.replace(anchor, patched, 1))
        driver = box.root / "red_driver.exe"
        err = build(box.root, DRIVER, driver)
        if check("the mutated driver compiles", not err, err):
            got = attempt(driver, str(COMPILER),
                          work / "reshape_plain" / "reshape_plain.bsp",
                          work / "jobs" / "red_step", "reshape_plain")
            check("a step flush with the platform is refused",
                  bool(got) and all(v == "REJECTED_SURFACE" for v, _ in got),
                  str(got))

            print("\n=== and it is the gate that refuses it, not the operator")
            tdata = pristine[transaction]
            gate, gone, count = resolve_anchor(tdata, *THE_GATE)
            if check("the gate is where it says", count == 1,
                     f"{count} occurrences"):
                transaction.write_bytes(tdata.replace(gate, gone, 1))
                ungated = box.root / "red_ungated.exe"
                err = build(box.root, DRIVER, ungated)
                if check("the ungated driver compiles", not err, err):
                    got = attempt(ungated, str(COMPILER),
                                  work / "reshape_plain" / "reshape_plain.bsp",
                                  work / "jobs" / "red_ungated",
                                  "reshape_plain")
                    check("without it the cracked platform is accepted",
                          bool(got) and any(v == "ACCEPTED" for v, _ in got),
                          str(got))
                transaction.write_bytes(tdata)
        edit.write_bytes(pristine[edit])
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

    print("=== what an edit leaves behind")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()

    probe = args.work / "bin" / "probe.exe"
    driver = args.work / "bin" / "driver.exe"
    err = build(REPO, PROBE, probe) or build(REPO, DRIVER, driver)
    if check("the probe and the transaction compile", not err, err):
        behaviour(probe, driver, args.work)
        if not args.no_red:
            red(args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
