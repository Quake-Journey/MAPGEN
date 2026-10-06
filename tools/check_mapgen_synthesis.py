"""GF7: fidelity zero is a product path, not a tool somebody runs by hand.

The chain that invents a map out of what a corpus taught has been driven from
the command line since M4. That made the F0 anchor the one anchor the product's
own oracle had never seen - and an anchor nobody gated is an anchor nobody can
publish.

What this asserts is the wiring and its refusals:

    the module refuses any fidelity but zero, by name;
    the pipeline branches on that and on nothing else;
    a request with nothing to learn from is ERR_SYNTHESIS, not a map;
    a request naming a snapshot that is not one is ERR_SYNTHESIS;
    and a real fidelity-zero run produces a map, compiles it, and is judged
    by the same gates every other fidelity is judged by.

The RED is the fidelity check itself. Without it the synthesis path answers for
fidelity 100 - a donor's architecture re-emitted as fresh axis-aligned rooms,
which is exactly the delivery Codex rejected.

    python tools/check_mapgen_synthesis.py [--work DIR] [--no-red] [--quick]
"""
from __future__ import annotations

import argparse
import re
import shutil
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831"
                    r"\synthesis")

MAPGEN = [
    "src/mapgen/mapgen_pipeline.c",
    "src/mapgen/mapgen_transaction.c",
    "src/mapgen/mapgen_equivalence.c",
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
    "src/mapgen/mapgen_compiler.c",
    "src/mapgen/mapgen_divergence.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_reach.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_generate.c",
    "src/mapgen/mapgen_features.c",
    "src/mapgen/mapgen_wiring.c",
    "src/mapgen/mapgen_space.c",
    "src/mapgen/mapgen_genome.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

PIPELINE = ["tools/mapgen_pipeline_driver.c"] + MAPGEN
TRAINER = ["tools/mapgen_training_test_driver.c", "src/mapgen/mapgen_training.c",
           "src/mapgen/mapgen_snapshot.c", "src/mapgen/mapgen_digest.c",
           "src/mapgen/mapgen_features.c", "src/mapgen/mapgen_wiring.c",
           "src/mapgen/mapgen_space.c", "src/mapgen/mapgen_trace.c",
           "src/mapgen/mapgen_genome.c", "src/mapgen/mapgen_bsp.c",
           "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_blueprint.c",
           "src/shared/shared.c", "tools/mapgen_host_stubs.c"]

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
        ["gcc", "-std=c17", "-O2", "-I" + str(root / "inc"),
         "-I" + str(root / "src" / "mapgen"), "-DUSE_LITTLE_ENDIAN=1",
         "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in sources] + ["-o", str(out), "-lm", "-lz"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


VERDICT = re.compile(r"^([A-Z_]+)$", re.M)


def run_pipeline(exe: Path, donor: Path, job: Path, name: str, fidelity: int,
                 extra: list[str]) -> tuple[str, str]:
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    run = subprocess.run([str(exe), str(COMPILER), str(donor), str(job), name,
                          str(fidelity), "7", "--moddir", str(GAME)] + extra,
                         capture_output=True, text=True, timeout=7200)
    m = VERDICT.search(run.stdout)
    return (m.group(1) if m else ""), run.stdout + run.stderr


def static_contract() -> None:
    print("\n=== what fidelity zero is, and is not")

    module = (REPO / "src" / "mapgen" / "mapgen_synthesis.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_synthesis.h").read_text(
        encoding="utf-8", errors="replace")
    pipeline = (REPO / "src" / "mapgen" / "mapgen_pipeline.c").read_text(
        encoding="utf-8", errors="replace")
    tool = (REPO / "tools" / "mapgen_generate.c").read_text(
        encoding="utf-8", errors="replace")

    check("the module refuses any fidelity but zero",
          "if (fidelity != 0)" in module
          and "MAPGEN_SYNTHESIS_ERR_NOT_ZERO" in module)
    check("and the header says why that is not a limitation",
          "rejected" in header and "axis-aligned rooms" in header)
    check("the pipeline branches on fidelity zero and nothing else",
          "if (request->generate.fidelity == 0) {" in pipeline)
    check("both halves build the baseline the same way",
          "MapGenTransaction_BuildBaseline" in pipeline)
    check("the loadout lives in one place",
          "weapon_rocketlauncher" in module
          and "weapon_rocketlauncher" not in tool)
    check("and the tool is a driver over the module",
          "MapGenSynthesis_Write(mix, recipe" in tool)


def target_manifest(trainer: Path, work: Path) -> Path:
    """Every material the corpus names, as a frozen target manifest would.

    Derived from the corpus rather than typed by hand, so it cannot drift from
    what the donors actually use - and used by every case here, because a
    generator with nothing to build with refuses for a reason that has nothing
    to do with what is being tested."""
    materials = work / "materials.txt"
    if materials.exists() and materials.stat().st_size:
        return materials
    names = subprocess.run([str(trainer), "chunks",
                            str(CORPUS / "q2dm1.bsp"),
                            str(CORPUS / "q2dm2.bsp"),
                            str(CORPUS / "q2dm3.bsp")],
                           capture_output=True, text=True, timeout=3600)
    found = sorted({m.group(1) for m in
                    re.finditer(r"^m=([^,]+),", names.stdout, re.M)})
    materials.write_text("\n".join(found) + "\n", encoding="ascii")
    return materials


def behaviour(exe: Path, trainer: Path, work: Path, quick: bool) -> None:
    donor = CORPUS / "q2dm1.bsp"
    if not check("the donor is in the corpus", donor.exists(), str(donor)):
        return

    manifest = target_manifest(trainer, work)
    check("the corpus yields a target manifest",
          manifest.exists() and manifest.stat().st_size > 0, str(manifest))

    print("\n=== a request with nothing to learn from")
    got, out = run_pipeline(exe, donor, work / "nosnap", "q2mg_none", 0, [])
    check("no snapshot -> ERR_SYNTHESIS", got == "ERR_SYNTHESIS",
          f"got {got!r}\n{out[-300:]}")

    junk = work / "not_a_snapshot.q2ts"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_bytes(b"this is not a snapshot")
    got, out = run_pipeline(exe, donor, work / "badsnap", "q2mg_bad", 0,
                            ["--snapshot", str(junk), "--manifest",
                             str(manifest)])
    check("a snapshot that is not one -> ERR_SYNTHESIS",
          got == "ERR_SYNTHESIS", f"got {got!r}\n{out[-300:]}")

    if quick:
        print("\n(the full fidelity-zero run was not asked for)")
        return

    print("\n=== and a real one, judged like every other fidelity")
    snapshot = work / "corpus.q2ts"
    run = subprocess.run([str(trainer), "train", str(snapshot),
                          str(CORPUS / "q2dm1.bsp"),
                          str(CORPUS / "q2dm2.bsp"),
                          str(CORPUS / "q2dm3.bsp")],
                         capture_output=True, text=True, timeout=3600)
    if not check("the corpus makes a snapshot", snapshot.exists(),
                 run.stdout[-200:]):
        return
    materials = manifest

    got, out = run_pipeline(exe, donor, work / "f0", "q2mg_f0", 0,
                            ["--snapshot", str(snapshot), "--manifest",
                             str(materials), "--scale", "0", "--goal", "4"])
    check("it invents a map", "invented" in out, out[-400:])
    # OK, not "one of the verdicts a run might legitimately produce": the
    # invented map passes the product's own gates. It did not the first time -
    # a lift drawn where it started and a climb built as a shaft cost it four
    # player starts - and accepting a refusal here would accept those back.
    check("and the product accepts it", got == "OK",
          f"got {got!r}\n{out[-400:]}")
    check("the gates ran on what came out",
          "playable" in out and "divergence" in out, out[-400:])
    check("nothing of the donor is left in it, which is what zero means",
          "in band" in out, out[-400:])


MUTATION = (
    b"""    if (fidelity != 0)
        return MAPGEN_SYNTHESIS_ERR_NOT_ZERO;""",
    b"""    if (false)
        return MAPGEN_SYNTHESIS_ERR_NOT_ZERO;""",
)


def red(work: Path) -> None:
    print("\n=== and the refusal is what keeps the boxes out of high fidelity")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "synthesis")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_synthesis.c"
        data = target.read_bytes()
        anchor, patched, count = resolve_anchor(data, *MUTATION)
        if not check("the fidelity test is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(data.replace(anchor, patched, 1))
        red_exe = box.root / "red.exe"
        err = build(box.root, ["tools/mapgen_generate.c"] + [
            s for s in MAPGEN if s not in ("src/mapgen/mapgen_pipeline.c",
                                           "src/mapgen/mapgen_transaction.c",
                                           "src/mapgen/mapgen_compiler.c",
                                           "src/mapgen/mapgen_divergence.c",
                                           "src/mapgen/mapgen_bundle.c",
                                           "src/mapgen/mapgen_closure.c",
                                           "src/mapgen/mapgen_certificate.c",
                                           "src/mapgen/mapgen_reach.c",
                                           "src/mapgen/mapgen_pmove.c",
                                           # NOT mapgen_movers.c: the
                                           # equivalence gate reads mover
                                           # records, so the module that
                                           # defines them has to be in any
                                           # link that has the gate in it.
                                           "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
                                           "src/mapgen/mapgen_generate.c",
                                           "src/common/pmove/old.c",
                                           "src/common/pmove/common.c")],
            red_exe)
        if not check("the mutated generator compiles", not err, err):
            return
        # The corpus's own materials, not the two-line file the bad-snapshot
        # case wrote: a generator with nothing to build with refuses for a
        # reason that has nothing to do with the mutation.
        manifest = work / "materials.txt"
        run = subprocess.run(
            [str(red_exe), str(work / "red.map"), str(manifest), "7", "0", "4",
             str(CORPUS / "q2dm1.bsp")],
            capture_output=True, text=True, timeout=3600,
            env={**__import__("os").environ, "MAPGEN_FIDELITY": "100"})
        check("without it fidelity 100 is answered with invented boxes",
              "refused" not in run.stdout, run.stdout[-300:])
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing",
              hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--no-red", action="store_true")
    ap.add_argument("--quick", action="store_true",
                    help="skip the full fidelity-zero run, which compiles")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    print("=== a map out of what was learned")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()

    exe = args.work / "bin" / "pipeline.exe"
    trainer = args.work / "bin" / "trainer.exe"
    err = build(REPO, PIPELINE, exe) or build(REPO, TRAINER, trainer)
    if check("the pipeline and the trainer compile", not err, err):
        behaviour(exe, trainer, args.work, args.quick)
        if not args.no_red:
            red(args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
