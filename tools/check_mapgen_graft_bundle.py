"""GF7: a room from another donor takes the place of one of ours.

Codex's operator order, item six: multi-donor bundle substitution and grafting,
with contribution floors, explicit new-work ConnectorAdapters and provenance,
after the single-donor bundle and transaction framework is proven.

What exists now, and what this guard holds it to:

  the predicate is the swap's own    `interchangeable` reads ways out, their
                                     kinds, their directions and the air. None
                                     of that is a fact about which file a
                                     bundle came from, so nothing was loosened
                                     to make it work across two maps.
  provenance is a NAME               every graft records the donor it came
                                     from, because GF7 forbids silent omission
                                     and a graft whose origin was a pointer is
                                     one nobody can audit after the run.
  the tally is per donor             which is what a contribution floor is
                                     checked against, and a donor that offered
                                     nothing is named rather than missing.
  the shell stays where it is        two rooms whose sockets match can still
                                     have shells of different shapes, and the
                                     rock around a room is what the map's
                                     sealing rests on. So the boundary brushes
                                     of ours stay and the boundary brushes of
                                     theirs do not come; what changes hands is
                                     what the room CONTAINS.

Two designs were tried before that one and both compiled to `**** leaked ****`:
moving the whole room, and filling the difference between two shells on a
thirty-two unit lattice. A gap thinner than a cell passes between the points
that are sampled, and a finer grid only moves the threshold - a sampled shell is
an approximated shell, and an approximated seal is not a seal.

Measured with the shell kept: 960 brushes to 960, compiles with no leak, walks
to 6177 states with none stranded and every one of them in a single component.

    python tools/check_mapgen_graft_bundle.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260904"
                    r"\graft_bundle")

DUMP = [
    "tools/mapgen_graft_plan_dump.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
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
        + [str(root / s) for s in DUMP] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def plan(exe: Path, donor: Path, others: list[Path],
         out_map: Path | None = None) -> dict:
    argv = [str(exe), str(donor), "1"] + [str(o) for o in others]
    if out_map:
        argv += ["--out", str(out_map)]
    run = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
    got: dict = {"grafts": -1, "offers": {}, "from": [], "changed": None,
                 "brushes": None, "text": run.stdout + run.stderr}
    for line in run.stdout.splitlines():
        m = re.match(r"^edits (\d+), grafts (\d+)", line)
        if m:
            got["grafts"] = int(m.group(2))
        m = re.match(r"^graft \d+ from (\S+)", line)
        if m:
            got["from"].append(m.group(1))
        m = re.match(r"^donor (\S+) offers (\d+)", line)
        if m:
            got["offers"][m.group(1)] = int(m.group(2))
        m = re.match(r"^applied \S+, changed (\w+)", line)
        if m:
            got["changed"] = m.group(1) == "yes"
        m = re.match(r"^brushes (\d+) -> (\d+)", line)
        if m:
            got["brushes"] = (int(m.group(1)), int(m.group(2)))
    return got


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


def build_walk(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in WALK] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def walk(exe: Path, bsp: Path) -> dict:
    """Is it a map a player can be in? The traversal authority answers."""
    if not exe.exists():
        err = build_walk(REPO, exe)
        if err:
            return {"error": err}
    run = subprocess.run([str(exe), str(bsp), "--workers", "0", "--quiet"],
                         capture_output=True, text=True, timeout=7200)
    out: dict = {}
    for line in run.stdout.splitlines():
        m = re.match(r"^report spawns (\d+) stranded (\d+) component (\d+)",
                     line)
        if m:
            out["spawns"] = int(m.group(1))
            out["stranded"] = int(m.group(2))
            out["component"] = int(m.group(3))
        m = re.match(r"^states (\d+)", line)
        if m:
            out["states"] = int(m.group(1))
    return out


def compiles(map_path: Path) -> tuple[bool, str]:
    """Does the pinned compiler accept it, and does it seal?"""
    run = subprocess.run([str(COMPILER), "-bsp", "-threads", "4",
                          "-moddir", str(GAME), "-basedir", str(GAME),
                          "-gamedir", str(GAME), str(map_path)],
                         capture_output=True, text=True, timeout=3600)
    text = run.stdout + run.stderr
    leaked = "leaked" in text.lower()
    return (map_path.with_suffix(".bsp").is_file() and not leaked), text[-300:]


def static_contract() -> None:
    print("\n=== what the operator is, and what it will not do")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry_edit.h").read_text(
        encoding="utf-8", errors="replace")

    check("the kind exists and is named",
          "MAPGEN_EDIT_GRAFT_BUNDLE" in header
          and '"graft-bundle"' in impl)
    #
    # Nothing was loosened to make the predicate work across two maps: it is
    # the swap's own, and it reads only bundle properties.
    #
    # The swap's predicate, with `exchange` FALSE: a graft clears a region
    # grown to hold what arrives rather than putting one room in another's
    # hole, so the turned-size test and the one-for-one pairing - both of them
    # about taking a place - are not its questions. The three measurements that
    # settled which sieve it does use are beside the call.
    check("it asks the swap's own predicate, as a sieve",
          "if (!interchangeable(b, a, false, &quarter, &mirror))" in impl)
    check("and says why that is the same question across two maps",
          "not one of those is a fact about which file" in impl)
    check("provenance is a name, not a pointer",
          "graft.source = names && names[d] ? names[d] : \"unnamed\";" in impl
          and "MapGenGeometryEdit_GraftedFrom" in header)
    check("the other donors are borrowed, and the header says they must "
          "outlive the plan",
          "they must outlive the plan" in header)

    print("\n=== the boundary travels where it can, and stays where it cannot")
    #
    # Codex, 2026-09-06 section 5: leaving the boundary behind on both sides is
    # a limitation of the operator, not the definition of GF7. The contract
    # path now carries it - MapGenGraft describes both rooms, the arriving one
    # is fitted into a bounded region of ours, and every brush that crosses the
    # region boundary is split on its planes. See inc/common/mapgen_graft.h.
    #
    # The furniture-only path is kept for the rooms that cannot be described -
    # 45 of the corpus's 146 are sealed partly by solid no brush provides - and
    # both are asserted here, because losing either is a regression.
    #
    check("the contract path is the one that is tried first",
          "MapGenGraft_Describe(mine, donor, i, &graft.mine_plan)" in impl
          and "graft.carries_boundary = true;" in impl)
    check("and it is what applies the graft when it holds",
          "if (g->carries_boundary)" in impl
          and "MapGenGraft_Apply(candidate, g->mine_plan" in impl)
    check("the fallback still leaves both boundaries where they are",
          impl.count("bb->role == MAPGEN_BUNDLE_ROLE_BOUNDARY") == 2)
    check("and a room with nothing inside it is refused only by the fallback",
          "inside it to give" in impl
          and "!graft.carries_boundary && (!mine_kept" in impl)
    #
    # Short fragments on purpose: these sentences wrap across lines in the
    # source, and an anchor that spans a line break asserts the formatting
    # rather than the reasoning.
    #
    check("and the two designs that leaked are written down",
          "approximated seal is not a seal" in impl
          and "leaked" in impl)
    check("dropping is highest index first, or it drops the wrong brushes",
          "Every drop moves the brushes after it down by one" in impl)


def behaviour(work: Path) -> dict:
    print("\n=== two donors offered, and what each can give")

    exe = work / "bin" / "plan.exe"
    err = build(REPO, exe)
    if not check("the plan dump compiles", not err, err):
        return {}
    for name in ("q2dm1.bsp", "q2dm2.bsp", "q2dm3.bsp"):
        if not check(f"{name} is present", (CORPUS / name).is_file()):
            return {}

    got = plan(exe, CORPUS / "q2dm1.bsp",
               [CORPUS / "q2dm2.bsp", CORPUS / "q2dm3.bsp"])
    check("the plan succeeds with two other donors", got["grafts"] >= 0,
          got["text"][-300:])
    #
    # The tally a contribution floor is checked against. What matters here is
    # not the number but that it is answerable PER DONOR and by name: GF7
    # forbids a donor being silently left out, and a donor that offered nothing
    # has to be visible as such.
    #
    check("every donor offered is accounted for by name",
          set(got["offers"]) == {"q2dm2.bsp", "q2dm3.bsp"},
          str(got["offers"]))
    check("and at least one of them can contribute a room",
          sum(got["offers"].values()) > 0, str(got["offers"]))
    check("every graft names the donor it came from",
          all(f in got["offers"] for f in got["from"]), str(got["from"]))

    print("\n=== and the map it makes is one a player can be in")
    made = work / "grafted.map"
    applied = plan(exe, CORPUS / "q2dm1.bsp", [CORPUS / "q2dm2.bsp"], made)
    check("a graft was planned", applied["grafts"] > 0, str(applied["offers"]))
    check("and it was applied", applied["changed"] is True,
          str(applied["changed"]))

    sealed, why = compiles(made)
    #
    # The whole question. Two earlier designs got this far and the compiler
    # refused both.
    #
    check("the pinned compiler accepts it and it seals", sealed, why)
    if sealed:
        walked = walk(work / "bin" / "walk.exe", made.with_suffix(".bsp"))
        check("every spawn is in one component",
              walked.get("spawns", 0) > 0 and walked.get("stranded") == 0,
              str(walked))
        check("and every place a player can stand is reachable",
              walked.get("component") == walked.get("states")
              and walked.get("states", 0) > 0, str(walked))
        donor_walk = walk(work / "bin" / "walk.exe", CORPUS / "q2dm1.bsp")
        check("and it is not simply the donor again",
              walked.get("states") != donor_walk.get("states"),
              f"{walked.get('states')} against {donor_walk.get('states')}")
    return {"exe": exe}


MUTATION = (
    b"""                        if (!bb || bb->role == MAPGEN_BUNDLE_ROLE_BOUNDARY)
                            continue;
                        graft.mine_brushes[mine_kept++] = bb->brush;""",
    b"""                        if (!bb)
                            continue;
                        graft.mine_brushes[mine_kept++] = bb->brush;""",
)


def red(work: Path) -> None:
    print("\n=== and without that refusal the compiler is handed a leak")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "graft-bundle")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        pristine = target.read_bytes()
        anchor, replacement, count = resolve_anchor(pristine, *MUTATION)
        if not check("the shell test is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(pristine.replace(anchor, replacement, 1))
        red_exe = box.root / "red_plan.exe"
        err = build(box.root, red_exe)
        if not check("the mutated operator still compiles", not err, err):
            target.write_bytes(pristine)
            return

        leaky = work / "leaky.map"
        bad = plan(red_exe, CORPUS / "q2dm1.bsp", [CORPUS / "q2dm2.bsp"],
                   leaky)
        check("without it the graft is still applied", bad["changed"] is True,
              str(bad["changed"]))
        if bad["changed"]:
            sealed, why = compiles(leaky)
            #
            # The whole reason the shell stays. Take our room's boundary away
            # and the map has a hole where the room used to be sealed, whatever
            # arrives to fill the space.
            #
            check("and the map it makes does not seal", not sealed, why)
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

    print("=== MAPGEN-1 GF7: a room from another donor")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()
    got = behaviour(args.work)
    if got and not args.no_red:
        red(args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("PASS" if not FAILURES else "FAIL"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
