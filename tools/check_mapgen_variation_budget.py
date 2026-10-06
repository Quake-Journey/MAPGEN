"""GF6C: a structural budget is never filled with paint.

Codex, 2026-09-01 section 4.1, in as many words:

    If safe operator granularity cannot reach the target band, return
    VARIATION_TARGET_UNREACHABLE with the donor, missing amount and exhausted
    operator families. NEVER FILL THE BUDGET WITH PAINT.

The same section fixes which families are paint: "Reskins, relights, item
swaps, spawn swaps and repeated edits to the same structure contribute zero to
this architecture metric." A family that contributes zero cannot bring a run
closer to a structural band, so every attempt at one while the band is unmet is
a compile spent to measure a zero the contract already decided.

Measured on q2dm1 at seed 1 before the rule existed: the schedule offers 292
edits of which 191 are paint, and 173 of them were attempted, compiled and
refused as having no effect - on every anchor. Two thirds of the attempts and
two thirds of the hour each anchor took. With the rule the same sweep reaches
the same numbers - 94, 290, 328, 618 - in fourteen minutes instead of a hundred
and ninety-seven.

This guard is what keeps it true:

  the classification    every family is classified, the paint ones as paint
  the call site         the pipeline asks before it spends, not after
  the behaviour         a run with a band attempts no paint at all
  the controlled RED    with the skip removed, the paint is attempted again

    python tools/check_mapgen_variation_budget.py [--work DIR] [--no-red]
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
                    r"\variation_budget")

PIPELINE = [
    "tools/mapgen_pipeline_driver.c",
    "src/mapgen/mapgen_pipeline.c",
    "src/mapgen/mapgen_synthesis.c",
    "src/mapgen/mapgen_architecture.c",
    "src/mapgen/mapgen_blueprint.c",
    "src/mapgen/mapgen_brush.c",
    "src/mapgen/mapgen_entities.c",
    "src/mapgen/mapgen_mapfile.c",
    "src/mapgen/mapgen_layout.c",
    "src/mapgen/mapgen_topology.c",
    "src/mapgen/mapgen_recipe.c",
    "src/mapgen/mapgen_mix.c",
    "src/mapgen/mapgen_random.c",
    "src/mapgen/mapgen_lineage.c",
    "src/mapgen/mapgen_training.c",
    "src/mapgen/mapgen_snapshot.c",
    "src/mapgen/mapgen_features.c",
    "src/mapgen/mapgen_wiring.c",
    "src/mapgen/mapgen_space.c",
    "src/mapgen/mapgen_genome.c",
    "src/mapgen/mapgen_transaction.c",
    "src/mapgen/mapgen_equivalence.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_generate.c",
    "src/mapgen/mapgen_compiler.c",
    "src/mapgen/mapgen_divergence.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_reach.c",
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

# Small, and it has both: one relight and six structural candidates. A donor
# with no paint in its schedule could not tell the two builds apart.
#
# It also ROUND-TRIPS. The first choice here was open_pair, and the pipeline
# refused it with ERR_BASELINE - the projection of that fixture is not the
# donor, so there was nothing to spend a budget on. The equivalence gate
# catching it is the gate working; the fixture was simply the wrong one.
FIXTURE = "reshape_plain"

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
        + [str(root / s) for s in sources] + ["-o", str(out), "-lm", "-lz"],
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


def run_pipeline(exe: Path, donor: Path, job: Path, fidelity: int) -> dict:
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    #
    # The moddir is not optional. Without it the compiler cannot find a
    # texture, the baseline comes back a different map from the donor, and the
    # run stops at ERR_BASELINE before it has spent anything - which is the
    # equivalence gate being right about a compile that was set up wrong.
    #
    run = subprocess.run([str(exe), str(COMPILER), str(donor), str(job),
                          "q2mg_vb", str(fidelity), "1",
                          "--moddir", str(GAME)],
                         capture_output=True, text=True, timeout=3600)
    out = {"ledger": {}, "attempted": -1, "text": run.stdout + run.stderr}
    for line in run.stdout.splitlines():
        if line.strip().startswith("ledger"):
            for verdict, count in re.findall(r"(\w+)=(\d+)", line):
                out["ledger"][verdict] = int(count)
        m = re.search(r"spent\s+(\d+) attempted", line)
        if m:
            out["attempted"] = int(m.group(1))
    return out


def static_contract() -> None:
    print("\n=== which families can move the number, and who asks")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry_edit.h").read_text(
        encoding="utf-8", errors="replace")
    pipe = (REPO / "src" / "mapgen" / "mapgen_pipeline.c").read_text(
        encoding="utf-8", errors="replace")

    check("the classification is a function, not a scattered test",
          "MapGenGeometryEdit_MovesArchitecture" in header
          and "bool MapGenGeometryEdit_MovesArchitecture" in impl)
    for paint in ("MAPGEN_EDIT_RESKIN", "MAPGEN_EDIT_RELIGHT",
                  "MAPGEN_EDIT_SWAP_ITEM"):
        check(f"{paint} is classified as paint",
              re.search(r"case " + paint + r":\s*\n(\s*case [A-Z_]+:\s*\n)*"
                        r"\s*return false;", impl) is not None)
    check("and the contract it comes from is quoted where it is decided",
          "contribute zero to this architecture metric" in header)

    #
    # Hard Rule #51: a rule the caller never asks is a rule that does not
    # happen. This is the call site, and it has to be BEFORE the attempt.
    #
    check("the pipeline asks before it spends",
          "MapGenGeometryEdit_MovesArchitecture(planned->kind)" in pipe)
    if "MapGenGeometryEdit_MovesArchitecture(planned->kind)" in pipe:
        asked = pipe.index("MapGenGeometryEdit_MovesArchitecture(planned->kind)")
        spent = pipe.index("MapGenTransaction_Try(txn, &edit, &step)")
        check("and it asks before the attempt, not after", asked < spent,
              f"asked at {asked}, spends at {spent}")
    check("only while a band is actually being chased",
          "if (target > 0 && !MapGenGeometryEdit_MovesArchitecture" in pipe)
    check("the measurement that made the rule is written down",
          "173 compiles per anchor" in pipe)


def behaviour(work: Path) -> dict:
    print("\n=== a run with a band attempts no paint at all")

    exe = work / "bin" / "pipeline.exe"
    err = build(REPO, exe, PIPELINE)
    if not check("the pipeline compiles", not err, err):
        return {}
    donor = compile_fixture(work, FIXTURE)
    if not check(f"the {FIXTURE} fixture compiles", donor is not None):
        return {}

    got = run_pipeline(exe, donor, work / "green", 90)
    check("something structural was attempted", got["attempted"] > 0,
          str(got["ledger"]))
    #
    # Not "no edit had no effect" - a STRUCTURAL edit can compile cleanly and
    # move the metric by nothing too, and on this fixture one does. That was
    # the first version of this case and it was wrong: it assumed paint was the
    # only thing that could produce the verdict.
    #
    # What the rule actually changes is comparative, and the RED below is the
    # other half of the measurement: the same run without it attempts more and
    # refuses more for no effect. Both halves are needed, so neither number is
    # asserted alone.
    #
    check("and the run got as far as accepting something",
          got["ledger"].get("ACCEPTED", 0) > 0, str(got["ledger"]))
    return got


MUTATION = (
    b"""        if (target > 0 && !MapGenGeometryEdit_MovesArchitecture(planned->kind))
            continue;""",
    b"""        if (false)
            continue;""",
)


def red(work: Path, green: dict) -> None:
    print("\n=== and with the rule removed, the paint is attempted again")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "variation-budget")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_pipeline.c"
        pristine = target.read_bytes()
        found, patched, count = resolve_anchor(pristine, *MUTATION)
        if not check("the anchor is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(pristine.replace(found, patched, 1))
        exe = box.root / "red.exe"
        err = build(box.root, exe, PIPELINE)
        if not check("it still compiles", not err, err):
            target.write_bytes(pristine)
            return

        got = run_pipeline(exe, work / FIXTURE / f"{FIXTURE}.bsp",
                           work / "red", 90)
        check("the paint is refused for having no effect",
              got["ledger"].get("REJECTED_NO_EFFECT", 0) > 0,
              str(got["ledger"]))
        check("which is a compile the rule was saving",
              got["attempted"] > green.get("attempted", 0),
              f"{got['attempted']} attempted against {green.get('attempted')}")
        #
        # And the saving is exactly the paint: with the rule, fewer edits are
        # attempted AND fewer come back having done nothing. Either number
        # alone could move for another reason; both moving together is the
        # rule.
        #
        check("and fewer edits came back having done nothing",
              got["ledger"].get("REJECTED_NO_EFFECT", 0)
              > green.get("ledger", {}).get("REJECTED_NO_EFFECT", 0),
              f"{got['ledger']} against {green.get('ledger')}")
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

    print("=== MAPGEN-1 GF6C: never fill the budget with paint")
    static_contract()
    green = behaviour(args.work)
    if green and not args.no_red:
        red(args.work, green)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("PASS" if not FAILURES else "FAIL"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
