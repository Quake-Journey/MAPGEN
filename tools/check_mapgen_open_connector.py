"""GF6C: the operator that makes a way through where the donor had none.

Codex's operator order, 2026-09-01 section 4.2, operator two: "widening/
narrowing an explicit connector AND ADDING A NEW ROUTE only at geometry-proven
sockets". The widen half has been in since GF6B and has its own guard; this is
the other half - the ConnectorAdapter the phase ledger records as missing.

A socket here is PROVEN, not declared. Five fixtures, each the same shape with
one thing changed, so the answer cannot be attributed to two differences at
once:

    open_pair     two rooms, one dividing wall, rock nowhere else. The case the
                  operator exists for, and the only one it may take.
    open_solid    the same wall with rock instead of a room behind it. A
                  doorway there opens into stone.
    open_narrow   the same division in a corridor eighty units across, so a
                  doorway would leave slivers where the jambs should be.
    open_low      a wall a hundred units tall, too short to carry a lintel over
                  a ninety-six-unit doorway.
    open_step     one floor raised sixty-four units, well past a step. A
                  doorway onto a drop is a hole, not a route.

The claim this guard makes is not that carving a doorway is safe. It is that
this operator declines unless the compiled donor shows it the ground - and that
when it does act, the map gains a route rather than a hole: the donor's two
spawns are in different components and the candidate's are in one.

    python tools/check_mapgen_open_connector.py [--work DIR] [--no-red]
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260904"
                    r"\open_connector")

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

WALK = [
    "tools/mapgen_reach_matrix.c",
    "src/mapgen/mapgen_reach.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_digest.c",
    "src/common/q2prox_cpu_topology.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

# The one it must take, and the four it must not.
TAKES = "open_pair"
REFUSES = ("open_solid", "open_narrow", "open_low", "open_step")
FIXTURES = (TAKES,) + REFUSES

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


def build(root: Path, out: Path, sources: list[str]) -> str:
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


TALLY = re.compile(r"^(\d+) attempted, (\d+) accepted; divergence (\d+)")


def transact(exe: Path, bsp: Path, job: Path, name: str,
             seed: int = 1) -> dict:
    """Run the real transaction, restricted to this one operator."""
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    run = subprocess.run([str(exe), str(COMPILER), str(bsp), str(job), name,
                          str(GAME), str(seed), "3", "--only",
                          "open-connector"],
                         capture_output=True, text=True, timeout=3600)
    out = {"attempted": -1, "accepted": -1, "divergence": -1,
           "faults": None, "text": run.stdout + run.stderr,
           "candidate": None}
    for line in run.stdout.splitlines():
        m = TALLY.match(line)
        if m:
            out["attempted"] = int(m.group(1))
            out["accepted"] = int(m.group(2))
            out["divergence"] = int(m.group(3))
        if line.startswith("accepted candidate: "):
            out["candidate"] = Path(line.split(": ", 1)[1].strip())
        m2 = re.search(r"faults (\d+)", line)
        if m2 and " open-connector " in line:
            out["faults"] = int(m2.group(1))
    return out


def walk(exe: Path, bsp: Path) -> dict:
    run = subprocess.run([str(exe), str(bsp), "--workers", "0", "--quiet"],
                         capture_output=True, text=True, timeout=3600)
    out = {"spawns": -1, "stranded": -1, "component": -1, "states": -1}
    for line in run.stdout.splitlines():
        m = re.match(r"^report spawns (\d+) stranded (\d+) component (\d+)",
                     line)
        if m:
            out["spawns"] = int(m.group(1))
            out["stranded"] = int(m.group(2))
            out["component"] = int(m.group(3))
        m2 = re.match(r"^states (\d+)", line)
        if m2:
            out["states"] = int(m2.group(1))
    return out


def static_contract() -> None:
    print("\n=== what the operator has to be able to show")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry_edit.h").read_text(
        encoding="utf-8", errors="replace")

    check("the kind exists and is named",
          "MAPGEN_EDIT_OPEN_CONNECTOR" in header
          and '"open-connector"' in impl)
    check("it only cuts a shape whose remainder is boxes",
          "static bool brush_is_box(" in impl)
    check("it is recorded as a BOX, not as a brush index",
          "opening_t" in impl and "an operator that then cut a" in impl)
    check("a mover is never cut", "brush->model != 0" in impl)

    print("\n=== and it declines when it cannot")

    check("air is required on both sides",
          "Air on BOTH sides, across the doorway's own rectangle" in impl)
    check("across the doorway, not merely at the wall's centre",
          "an end buried in rock" in impl)
    check("the wall has to be a wall and not a block",
          "WALL_THIN_MIN" in impl and "WALL_THIN_MAX" in impl)
    check("a jamb and a lintel have to remain",
          "DOOR_JAMB" in impl and "DOOR_LINTEL" in impl)
    check("the doorway's foot has to be at the floor on both sides",
          "DOOR_STEP" in impl and "A doorway onto a drop is a hole" in impl)
    #
    # And the check that could never refuse anything is gone rather than left
    # in to look like safety. The RED matrix is what found it.
    #
    check("and the check that could never fire was removed, not kept",
          "side_floor[0] - side_floor[1]" not in impl
          and "An unreachable check is not safety" in impl)
    check("and the wall really is rock where the doorway will be",
          "already carving that space" in impl)

    print("\n=== and the cut itself leaves no T-junction")
    check("the five-box construction is the one used",
          "Five boxes, not three" in impl)
    check("and why three was wrong is written down",
          "a vertex in the middle of an edge is a" in impl.lower()
          or "in the middle of\n     * a jamb's vertical edge" in impl)


def behaviour(work: Path) -> dict:
    print("\n=== one wall it may open, and four it may not")

    exe = work / "bin" / "transaction.exe"
    err = build(REPO, exe, TRANSACTION)
    if not check("the transaction compiles", not err, err):
        return {}

    seen = {}
    for name in FIXTURES:
        bsp = compile_fixture(work, name)
        if not check(f"the {name} fixture compiles", bsp is not None):
            continue
        seen[name] = transact(exe, bsp, work / f"job_{name}", name)

    got = seen.get(TAKES)
    if got:
        check("the wall with a room on each side is opened",
              got["accepted"] == 1, str(got["text"][-400:]))
        check("and the cut left no T-junction", got["faults"] == 0,
              f"faults {got['faults']}")
        check("and it counts as architectural divergence",
              got["divergence"] > 0, f"{got['divergence']} permille")

    for name in REFUSES:
        got = seen.get(name)
        if got is None:
            continue
        #
        # Not merely rejected: never PROPOSED. The proof is made before the
        # compile, so a refusal that had to be compiled to be discovered would
        # be the operator failing to answer its own question.
        #
        check(f"{name} is never even attempted", got["attempted"] == 0,
              f"attempted {got['attempted']}, accepted {got['accepted']}")
    return seen


def the_route(work: Path, seen: dict) -> None:
    print("\n=== and what it made is a route, not a hole")

    got = seen.get(TAKES)
    if not got or not got.get("candidate"):
        check("there is a candidate to walk", False, "nothing was accepted")
        return

    exe = work / "bin" / "walk.exe"
    err = build(REPO, exe, WALK)
    if not check("the walk compiles", not err, err):
        return

    donor = walk(exe, work / TAKES / f"{TAKES}.bsp")
    after = walk(exe, got["candidate"])

    #
    # The whole claim, in two numbers each. The donor's two spawns are in
    # different components - it is one chamber with a wall across it - and the
    # candidate's are in one. Nothing else in the map changed.
    #
    check("the donor's spawns are in different components",
          donor["spawns"] == 2 and donor["stranded"] == 1, str(donor))
    check("the candidate's are in the same one",
          after["spawns"] == 2 and after["stranded"] == 0, str(after))
    check("and every place a player can stand is now reachable",
          after["component"] == after["states"] and after["states"] > 0,
          str(after))
    check("the donor's were not", donor["component"] < donor["states"],
          str(donor))


MUTATIONS = {
    "an operator that does not look at the far side": (
        b"""                if (!donor_air(donor, p[0], p[1], p[2]))
                    return false;""",
        b"""                if (!donor_air(donor, p[0], p[1], p[2]))
                    { /* mutated: the far side is not looked at */ }""",
        "open_solid",
    ),
    "an operator that leaves no jamb": (
        b"""    if (o->maxs[c] - o->mins[c] < DOOR_WIDE + 2.0f * DOOR_JAMB)
        return false;""",
        b"""    if (o->maxs[c] - o->mins[c] < 0.0f)
        return false;""",
        "open_narrow",
    ),
    "an operator that leaves no lintel": (
        b"""    if (o->maxs[2] - o->mins[2] < DOOR_TALL + DOOR_LINTEL)
        return false;""",
        b"""    if (o->maxs[2] - o->mins[2] < 0.0f)
        return false;""",
        "open_low",
    ),
    "an operator that lets a doorway hang over a drop": (
        b"""        if (fabsf(side_floor[which] - o->mins[2]) > DOOR_STEP)
            return false;""",
        b"""        if (fabsf(side_floor[which] - o->mins[2]) > 1e9f)
            return false;""",
        "open_step",
    ),
}


def red(work: Path) -> None:
    print("\n=== and each refusal is load-bearing")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "open-connector")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        pristine = target.read_bytes()
        exe = box.root / "red.exe"
        for name, (anchor, replacement, fixture) in MUTATIONS.items():
            found, patched, count = resolve_anchor(pristine, anchor,
                                                   replacement)
            if not check(f"{name}: the anchor is where it says", count == 1,
                         f"{count} occurrences"):
                continue
            target.write_bytes(pristine.replace(found, patched, 1))
            err = build(box.root, exe, TRANSACTION)
            if not check(f"{name}: it still compiles", not err, err):
                target.write_bytes(pristine)
                continue

            #
            # With the check gone, the fixture that exists to be refused is
            # offered instead. It does not have to be ACCEPTED - the compile
            # and the hard gates may still catch it, and on some of these they
            # will - what matters is that the operator stopped declining, which
            # is what the check was doing.
            #
            got = transact(exe, work / fixture / f"{fixture}.bsp",
                           work / f"red_{fixture}", fixture)
            check(f"{name}: {fixture} is now offered",
                  got["attempted"] > 0,
                  f"attempted {got['attempted']}")
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

    print("=== MAPGEN-1 GF6C: a new route at a geometry-proven socket")
    static_contract()
    seen = behaviour(args.work)
    if seen:
        the_route(args.work, seen)
    if not args.no_red:
        red(args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("PASS" if not FAILURES else "FAIL"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
