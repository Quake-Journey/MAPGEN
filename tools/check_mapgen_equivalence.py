"""The baseline-equivalence gate, and whether two implementations agree.

The gate decides whether B - the donor's own geometry compiled by the frozen
toolchain with nothing applied - is still the donor. Until it says so, a
fidelity-100 divergence of zero means only that the pipeline agrees with
itself.

    python tools/check_mapgen_equivalence.py [--work DIR] [--donors a.bsp b.bsp]

What is asserted:

  * the compiler's own freedoms are LISTED, not inferred from a build that
    succeeded, and the list names the ones the ruling calls out;
  * a map compared with itself is equivalent, on every donor - a gate that
    could not say that would be measuring its own arithmetic;
  * the C gate and an independent Python reading of the same two files agree
    on area, centroid, facing and texture axes for every material;
  * every axis runs and is reported, whether it failed or not;
  * the donors that pass, and the donors that do not, with the numbers.

The controlled REDs live in check_mapgen_equivalence_red.py: a gate that has
never failed is not known to work, and this file does not pretend otherwise.
"""
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapgen_equivalence_oracle import (Bsp, AXIS_BITS, mean,  # noqa: E402
                                       signatures, verdicts)

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260903"
                    r"\equivgate\green")

# Enough of the pipeline to open a transaction, which is where the gate lives.
PIPELINE_SOURCES = [
    "tools/mapgen_pipeline_driver.c", "src/mapgen/mapgen_pipeline.c",
    "src/mapgen/mapgen_synthesis.c", "src/mapgen/mapgen_architecture.c",
    "src/mapgen/mapgen_blueprint.c", "src/mapgen/mapgen_brush.c",
    "src/mapgen/mapgen_layout.c", "src/mapgen/mapgen_mix.c",
    "src/mapgen/mapgen_snapshot.c", "src/mapgen/mapgen_training.c",
    "src/mapgen/mapgen_features.c", "src/mapgen/mapgen_space.c",
    "src/mapgen/mapgen_topology.c", "src/mapgen/mapgen_wiring.c",
    "src/mapgen/mapgen_entities.c", "src/mapgen/mapgen_genome.c",
    "src/mapgen/mapgen_lineage.c", "src/mapgen/mapgen_random.c",
    "src/mapgen/mapgen_transaction.c", "src/mapgen/mapgen_equivalence.c",
    "src/mapgen/mapgen_divergence.c", "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c", "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_reach.c", "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_pmove.c", "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_mapfile.c", "src/mapgen/mapgen_compiler.c",
    "src/mapgen/mapgen_digest.c", "src/mapgen/mapgen_report.c",
    "src/mapgen/mapgen_recipe.c",
    "src/common/q2prox_cpu_topology.c", "src/common/pmove/old.c",
    "src/common/pmove/common.c", "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED += 1
    return ok


def build(work: Path, name: str, files: list[str], strict: bool = True) -> Path:
    exe = work / name
    flags = ["-std=c17", "-O2", "-Wall", "-Wextra"] + (["-Werror"] if strict
                                                       else [])
    flags += ["-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
              "-DUSE_NEW_GAME_API=0", "-I" + str(REPO / "src" / "mapgen")]
    run = subprocess.run(
        ["gcc", *flags, "-I" + str(REPO / "inc")]
        + [str(REPO / f) for f in files]
        + ["-o", str(exe), "-lm", "-lz"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2000:])
        raise SystemExit(f"cannot build {name}")
    return exe


def make_baseline(fork: Path, donor: Path, work: Path) -> Path | None:
    out = work / f"{donor.stem}_base.map"
    bsp = out.with_suffix(".bsp")
    if bsp.is_file():
        return bsp
    run = subprocess.run([str(fork), str(donor), str(out), "100"],
                         capture_output=True, text=True)
    if run.returncode != 0:
        return None
    run = subprocess.run(
        [str(COMPILER), "-bsp", "-threads", "8", "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(out)],
        capture_output=True, text=True, timeout=3600)
    return bsp if bsp.is_file() else None


def run_gate(exe: Path, donor: Path, baseline: Path) -> dict:
    run = subprocess.run([str(exe), str(donor), str(baseline)],
                         capture_output=True, text=True, timeout=900)
    out = {"axes": {}, "mask": 0, "result": "?", "detail": "",
           "materials": (0, 0), "text": run.stdout}
    for line in run.stdout.splitlines():
        if line.startswith("equivalence "):
            out["result"] = line.split(maxsplit=1)[1]
        elif line.startswith("failed_axes "):
            out["mask"] = int(line.split()[1], 16)
        elif line.startswith("detail "):
            out["detail"] = line[7:]
        elif line.startswith("axis DIFF_"):
            parts = line.split()
            out["axes"][parts[1]] = parts[2]
        elif line.startswith("materials "):
            parts = line.split()
            out["materials"] = (int(parts[1]), int(parts[2]))
    return out


def cross_check(donor: Path, baseline: Path, gate: dict) -> tuple[bool, str]:
    """The Python reading of the same two files, against the C gate's counts.

    Only quantities both sides publish can be compared, which is the material
    count and the worst area drift; the rest of the agreement is proved by
    computing the same signatures here and requiring the same verdict about
    which materials are out of tolerance.
    """
    bd, bb = Bsp(donor), Bsp(baseline)
    d, b = signatures(bd, bb), signatures(bb, bd)
    if gate["materials"] != (len(d), len(b)):
        return False, (f"materials {gate['materials']} from C, "
                       f"{(len(d), len(b))} from Python")
    worst_pm, worst_name = 0.0, ""
    for key in d:
        if key not in b:
            continue
        md, mb = mean(d[key]), mean(b[key])
        delta = abs(md["area"] - mb["area"])
        pm = 1000.0 * delta / max(md["area"], mb["area"], 1e-9)
        if pm > worst_pm:
            worst_pm, worst_name = pm, key[0]
    for line in gate["text"].splitlines():
        if line.startswith("materials "):
            parts = line.split()
            # materials N N area A A mismatched M worst P permille NAME ...
            c_pm = float(parts[9])
            if abs(c_pm - worst_pm) > 0.02:
                return False, (f"worst area drift {c_pm:.2f} from C, "
                               f"{worst_pm:.2f} from Python on {worst_name}")
    # And the axis the two implementations actually disagree about, if any.
    #
    # Codex, section 1.7: comparing published counters compares what the C gate
    # chose to print. This asks the second implementation the same QUESTION -
    # does this axis hold between these two files - and requires the same
    # answer. A difference either one sees and the other does not fails here,
    # whichever of them is right.
    own = verdicts(Bsp(donor), Bsp(baseline))
    for axis, (holds, why) in sorted(own.items()):
        c_holds = not (gate["mask"] & AXIS_BITS[axis])
        if c_holds != holds:
            return False, (f"{axis}: C says "
                           f"{'it holds' if c_holds else 'it does not'}, "
                           f"Python says "
                           f"{'it holds' if holds else 'it does not'} - {why}")
    return True, (f"worst area drift {worst_pm:.2f} permille agreed, "
                  f"and all eight axes agree")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--donors", type=Path, nargs="*",
                    default=[CORPUS / "q2dm1.bsp", CORPUS / "q2dm2.bsp",
                             CORPUS / "q2dm3.bsp", CORPUS / "q2dm8.bsp"])
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    exe = build(args.work, "equiv.exe",
                ["tools/mapgen_equivalence_driver.c",
                 "src/mapgen/mapgen_equivalence.c", "src/mapgen/mapgen_bsp.c",
                 "src/mapgen/mapgen_movers.c", "src/mapgen/mapgen_trace.c"])
    fork = build(args.work, "fork.exe",
                 ["tools/mapgen_geometry_fork.c", "src/mapgen/mapgen_geometry.c",
                  "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_bsp.c",
                  "src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_rooms.c",
                  "src/mapgen/mapgen_bundle.c", "src/mapgen/mapgen_closure.c"],
                 strict=False)

    print("what the compiler is allowed to change, listed")
    listed = subprocess.run([str(exe), "--allowed"], capture_output=True,
                            text=True).stdout
    allowed = [line[8:] for line in listed.splitlines()
               if line.startswith("allowed ")]
    check("the list is published rather than implied", len(allowed) >= 8,
          f"{len(allowed)} entries")
    for phrase in ("face subdivision", "plane order", "entity order",
                   "texinfo de-duplication", "lightmap bytes",
                   "brush and brush-side ordering"):
        check(f"the list names {phrase}",
              any(phrase in entry for entry in allowed))
    check("a lost surface is never allowed",
          any("never lost" in entry for entry in allowed))

    print("\na map compared with itself")
    for donor in args.donors:
        if not donor.is_file():
            print(f"  SKIP  {donor.name} is not here")
            continue
        gate = run_gate(exe, donor, donor)
        check(f"{donor.name} is equivalent to itself",
              gate["mask"] == 0 and gate["result"] == "OK", gate["detail"])
        check(f"{donor.name}: every axis ran and reported",
              len(gate["axes"]) == 8, f"{len(gate['axes'])} axes")

    print("\nthe donor against its own no-edit round trip")
    verdicts = {}
    for donor in args.donors:
        if not donor.is_file():
            continue
        baseline = make_baseline(fork, donor, args.work)
        if baseline is None:
            print(f"  SKIP  {donor.name}: no baseline could be built")
            continue
        gate = run_gate(exe, donor, baseline)
        verdicts[donor.name] = gate
        ok, detail = cross_check(donor, baseline, gate)
        check(f"{donor.name}: C and Python agree on the same two files", ok,
              detail)
        print(f"        {donor.name}: {gate['result']}"
              + (f" -- {gate['detail']}" if gate["detail"] else ""))

    print("\nand the product refuses a baseline that is not the donor")
    #
    # The gate exists in MapGenTransaction_Begin, not only in its own driver.
    # A compiler that answers with a synthetic cube gives a baseline that is
    # not q2dm1 by any measure, and the pipeline must refuse to measure
    # anything against it.
    #
    pipeline = build(args.work, "pipeline.exe", PIPELINE_SOURCES, strict=False)
    job = args.work / "not_the_donor"
    if job.exists():
        shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)
    run = subprocess.run(
        [str(pipeline), str(REPO / "tools" / "mapgen_fake_compiler.py"),
         str(args.donors[0]), str(job), "test", "100", "1",
         "--fake", sys.executable, "success"],
        capture_output=True, text=True, timeout=1800)
    verdict = (run.stdout.strip().splitlines() or ["?"])[0].split()[0]
    check("the pipeline refuses a baseline that is not the donor",
          verdict == "ERR_BASELINE", f"got {verdict!r}")

    print("\nwhere the product path stands today")
    for name, gate in verdicts.items():
        failing = [axis for axis, state in gate["axes"].items()
                   if state == "FAILED"]
        if failing:
            print(f"  OPEN  {name}: {', '.join(failing)}")
        else:
            print(f"  GOOD  {name}: the baseline is the donor")
    #
    # NOT an assertion that a donor passes.
    #
    # As of 2026-09-03 none of the three does: with the space axis probing
    # every leaf and comparing the whole movement mask, the round trip gains
    # solid on q2dm1 and moves clip and ladder content on all three. That is a
    # projection defect, it is Codex's prerequisite for step 5, and writing an
    # assertion that currently fails would only make this guard useless as a
    # regression net for everything else it checks.
    #
    # What IS asserted is that the gate works: a map is equivalent to itself,
    # every axis runs, the two implementations agree, and the product refuses
    # a baseline that is not the donor. The donors' own state is reported
    # above, in numbers, every run.
    #
    passing = [name for name, g in verdicts.items() if g["mask"] == 0]
    print(f"        {len(passing)} of {len(verdicts)} donors currently "
          f"produce a baseline that IS the donor"
          + (f": {', '.join(passing)}" if passing else ""))

    print(f"\n{CASES} cases, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
