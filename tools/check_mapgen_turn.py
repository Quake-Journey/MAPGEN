"""GF6C: turning a sealed room in place, which nobody outside can notice.

First in Codex's operator order, and the only structural operator that cannot
change connectivity at all when its precondition holds: the transform has to
map every socket of the bundle onto a socket of the same kind, so every way in
and out ends up where one already was.

Two fixtures, the same chamber, differing in the only thing the legality
depends on:

    turn_cross   four ways out at ninety degrees - every quarter turn is legal
    turn_tee     three - no turn of a square maps three onto themselves

    python tools/check_mapgen_turn.py [--work DIR] [--no-red]
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\turn")

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


CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")

# The transaction, because the shell case asks what the operator does to a REAL
# map rather than what the planner offers about a fixture.
TRANSACTION = [
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


def build_transaction(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in TRANSACTION] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def turns_on(exe: Path, donor: Path, job: Path) -> dict[str, int]:
    """Every planned turn on this donor, and what became of each."""
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    run = subprocess.run([str(exe), str(COMPILER), str(donor), str(job),
                          "q2mg_turn", str(GAME), "1", "20", "--only",
                          "turn-bundle"],
                         capture_output=True, text=True, timeout=7200)
    out: dict[str, int] = {}
    for line in run.stdout.splitlines():
        if line.startswith("ledger:"):
            for verdict, count in re.findall(r"(\w+)=(\d+)", line):
                out[verdict] = int(count)
    return out


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


TURN = re.compile(r"^turn (\d+) room (\d+) quarter (\d+)( mirrored)?")


def planned(exe: Path, bsp: Path) -> dict[int, int]:
    """How many turns were planned, per room."""
    run = subprocess.run([str(exe), str(bsp), "1"], capture_output=True,
                         text=True, timeout=600)
    per_room: dict[int, int] = {}
    for line in run.stdout.splitlines():
        m = TURN.match(line)
        if m:
            room = int(m.group(2))
            per_room[room] = per_room.get(room, 0) + 1
    return per_room


def busiest(per_room: dict[int, int]) -> int:
    """The room with the most ways out is the one both fixtures are about."""
    return max(per_room.values()) if per_room else 0


def applied(exe: Path, bsp: Path, index: int = 0) -> tuple[bool, str]:
    run = subprocess.run([str(exe), str(bsp), "1", "--only", "turn-bundle",
                          "--apply", str(index)], capture_output=True,
                         text=True, timeout=600)
    return "applied" in run.stdout, run.stdout


def static_contract() -> None:
    print("\n=== what makes a turn legal")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8", errors="replace")
    geometry = (REPO / "src" / "mapgen" / "mapgen_geometry.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry.h").read_text(
        encoding="utf-8", errors="replace")

    check("only a movable bundle may be turned",
          "!MapGenBundle_Movable(bundle)" in impl)
    check("every way out has to land on a way out of the same kind",
          "o->kind != s->kind" in impl)
    check("and it has to end up going where one already goes",
          "socket_way(o, pivot, theirs)" in impl)
    check("a way out is a direction, because a saddle point is not stable",
          "static void socket_way(" in impl)
    check("the sockets and the walls use one arithmetic",
          "static void turn_xy(" in impl)
    check("the turn is about the room's own centre",
          "turn.pivot" in impl and "MapGenBundle_Mins(bundle)" in impl)

    print("\n=== and what moves when it does")

    check("a named part of the map turns, not the whole of it",
          "MapGenGeometry_TransformSubset" in header)
    check("the brushes take their own sides with them",
          "brush_mask" in geometry and "the unit of movement is the brush"
          in header)
    check("texture axes turn with the surface",
          "rotate_xy(axis, quarter_turns, mirror_x)" in geometry)
    check("so do the face samples and anchors a later edit will read",
          "side->sample[k][a] = sample[a]" in geometry
          and "side->anchor[k][a] = anchor[a]" in geometry)
    check("and so do entity ANGLES, which the whole-map transform never moved",
          "turn_entity_angles" in geometry)
    check("up and down are not angles and are left alone",
          "-1.0f || degrees == -2.0f" in geometry)


def behaviour(exe: Path, work: Path) -> None:
    print("\n=== four ways out at ninety degrees")
    cross = compile_fixture(work, "turn_cross")
    if check("the cross fixture compiles", cross is not None):
        per_room = planned(exe, cross)
        # Four ways out at ninety degrees are symmetric under every
        # non-identity element of the square's group, so all seven are legal.
        check("its chamber may take every turn there is",
              busiest(per_room) == 7, str(per_room))
        did, out = applied(exe, cross)
        check("and turning it changes the map", did, out[-300:])

    print("\n=== three ways out")
    tee = compile_fixture(work, "turn_tee")
    if check("the tee fixture compiles", tee is not None):
        per_room = planned(exe, tee)
        # Three ways out are symmetric under exactly one thing: the mirror
        # across their own axis. Everything else moves a way out to where
        # there is not one, and is not offered.
        check("its chamber may take exactly the one its shape allows",
              busiest(per_room) == 1, str(per_room))


# The test that actually decides. The KIND test was mutated first and it
# changes nothing on a map whose ways out are all halls - a mutation that
# cannot fail is not a RED.
MUTATION = (
    b"""                            landed = theirs[0] == way[0] && theirs[1] == way[1]
                                  && theirs[2] == way[2];""",
    b"""                            landed = true;""",
)


def red(exe: Path, work: Path) -> None:
    print("\n=== and the socket test is what refuses the tee")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "turn")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        data = target.read_bytes()
        anchor, replacement, count = resolve_anchor(data, *MUTATION)
        if not check("the socket test is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(data.replace(anchor, replacement, 1))
        red_exe = box.root / "red.exe"
        err = build(box.root, red_exe)
        if not check("the mutated planner still compiles", not err, err):
            return
        per_room = planned(red_exe, work / "turn_tee" / "turn_tee.bsp")
        check("without it the tee is offered turns that move its ways out",
              busiest(per_room) > 1, str(per_room))
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing",
              hash_tree(REPO) == before)


SHELL_MUTATION = (
    b"""    if (!shell_survives_turn(candidate, donor, turn))
        return false;""",
    b"""    if (false)
        return false;""",
)


def the_shell(work: Path) -> None:
    """On the real donor, a turn only happens inside a shell that turns too.

    q2dm1 rather than a fixture, because a fixture built for this operator is a
    map somebody made symmetric on purpose. What the operator meets in the
    product is a map nobody designed for it, and there the incomplete
    precondition was making the compiler refuse six maps out of fourteen.
    """
    print("\n=== and on the real donor, nothing turns inside a shell that "
          "does not")

    donor = CORPUS / "q2dm1.bsp"
    if not check("the donor is present", donor.is_file(), str(donor)):
        return
    exe = work / "bin" / "txn.exe"
    err = build_transaction(REPO, exe)
    if not check("the transaction compiles", not err, err):
        return

    got = turns_on(exe, donor, work / "q2dm1_green")
    #
    # Declined, not refused: the proof is made before the compile, so a map
    # that would leak is never handed to the compiler at all.
    #
    check("every planned turn is declined before it is compiled",
          got.get("REJECTED_COMPILE", 0) == 0
          and got.get("REJECTED_SURFACE", 0) == 0
          and got.get("REJECTED_NOT_APPLIED", 0) > 0, str(got))

    before = hash_tree(REPO)
    box = Sandbox(REPO, "turn-shell")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        data = target.read_bytes()
        anchor, replacement, count = resolve_anchor(data, *SHELL_MUTATION)
        if not check("the shell test is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(data.replace(anchor, replacement, 1))
        red_exe = box.root / "red_txn.exe"
        err = build_transaction(box.root, red_exe)
        if not check("the mutated operator still compiles", not err, err):
            return
        bad = turns_on(red_exe, donor, work / "q2dm1_red")
        #
        # The whole point. Without the test the operator builds maps the
        # compiler will not accept, and it costs a compile each to find out.
        #
        check("without it the compiler is handed maps it refuses",
              bad.get("REJECTED_COMPILE", 0) > 0, str(bad))
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing (shell)",
              hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--no-red", action="store_true")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    print("=== turning a sealed room in place")
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
            the_shell(args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
