"""GF6A: what a demo saw, carried in the snapshot, bound to the map it is about.

The parser has been able to read a demo since the ingestion slice landed, and
nothing downstream could see it. Codex's review of 2026-09-02 said so: a demo
that stops at the tool that printed it is an adapter, not evidence. Movement is
now a chunk of the training snapshot, and this is the chain end to end -

    a demo of the corpus            ->  a record of what it saw
    that record                     ->  Training, against the map's own hash
    Training                        ->  a MOVEMENT chunk in the snapshot
    the snapshot, reopened          ->  the same bytes

- with the two refusals that make the binding mean anything: evidence for a map
this corpus does not have, and evidence with no physics behind it.

    python tools/check_mapgen_movement_evidence.py [--work DIR]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\Demos\q2dm1")
MAPS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831"
                    r"\movement")

INGEST = [
    "tools/mapgen_demo_ingest.c",
    "src/mapgen/mapgen_demo.c",
    "src/mapgen/mapgen_digest.c",
    "src/client/demo_offline_decoder.c",
    "src/common/msg.c",
    "src/common/sizebuf.c",
    "src/common/math.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

TRAINING = [
    "tools/mapgen_training_test_driver.c",
    "src/mapgen/mapgen_training.c",
    "src/mapgen/mapgen_snapshot.c",
    "src/mapgen/mapgen_digest.c",
    "src/mapgen/mapgen_features.c",
    "src/mapgen/mapgen_wiring.c",
    "src/mapgen/mapgen_space.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_genome.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_blueprint.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

PHYSICS = [
    "tools/mapgen_reach_gate.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_reach.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_digest.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
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


def build(sources: list[str], out: Path, client: bool = False) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    defines = (["-DUSE_CLIENT=1", "-DUSE_NEW_GAME_API=1", "-DUSE_MVD_CLIENT=1"]
               if client else ["-DUSE_CLIENT=0", "-DUSE_NEW_GAME_API=0"])
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-I" + str(REPO / "src" / "mapgen"), "-DUSE_LITTLE_ENDIAN=1",
         "-DUSE_SERVER=0"] + defines
        + [str(REPO / s) for s in sources] + ["-o", str(out), "-lm", "-lz"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def a_good_demo(work: Path, ingest: Path, evidence: Path) -> Path | None:
    """The first corpus member the ingester accepts WHOLE.

    Chosen by asking rather than by picking a name: the corpus has members
    whose archive paths are longer than the provenance schema allows and
    members that stop half way, and a fixture built on one of those would be
    testing a refusal this file is not about.
    """
    import mapgen_demo_unpack as unpack

    laid_out = work / "corpus"
    if laid_out.exists():
        shutil.rmtree(laid_out)
    demos, _ = unpack.unpack(CORPUS, laid_out)
    for demo in demos:
        if evidence.exists():
            evidence.unlink()
        subprocess.run([str(ingest), str(demo), "--map", "q2dm1",
                        "--evidence", str(evidence)],
                       capture_output=True, text=True, timeout=600)
        if evidence.exists():
            return demo
    return None


HELD = re.compile(r"^movement (\w+), held (\d+)", re.M)
SOURCE = re.compile(r"^source (\w+)", re.M)
CARRIED = re.compile(r"^carried (\d+) bytes", re.M)
SNAPSHOT = re.compile(r"^snapshot (\w+)", re.M)


def movement(exe: Path, snapshot: Path, evidence: Path, physics: str,
             maps: list[Path]) -> str:
    run = subprocess.run([str(exe), "movement", str(snapshot), str(evidence),
                          physics] + [str(m) for m in maps],
                         capture_output=True, text=True, timeout=1800)
    return run.stdout + run.stderr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    args = ap.parse_args()
    work = args.work
    work.mkdir(parents=True, exist_ok=True)

    print("=== a demo of the corpus, kept where what was learned is kept")
    if not check("the demo corpus and the maps are where they should be",
                 CORPUS.is_dir() and MAPS.is_dir()):
        return 1

    ingest = work / "bin" / "ingest.exe"
    training = work / "bin" / "training.exe"
    physics_exe = work / "bin" / "physics.exe"
    err = (build(INGEST, ingest, client=True) or build(TRAINING, training)
           or build(PHYSICS, physics_exe))
    if not check("the three tools compile", not err, err):
        return 1

    run = subprocess.run([str(physics_exe), "x", "--physics"],
                         capture_output=True, text=True)
    physics = run.stdout.split()[-1] if run.stdout.strip() else ""
    check("the build says which physics it computes with",
          len(physics) == 64, physics)

    evidence = work / "evidence.txt"
    demo = a_good_demo(work, ingest, evidence)
    if not check("the corpus lays out and offers a demo it accepts whole",
                 demo is not None):
        return 1
    assert demo

    print("\n=== the record the ingester writes")
    print(f"  from {demo.name}")
    if check("it wrote one", evidence.exists()):
        text = evidence.read_text(encoding="utf-8", errors="replace")
        for field in ("map", "gamedir", "source", "digest", "protocol", "pov",
                      "quality", "duration_ms", "samples", "cells", "jumps",
                      "drops", "rides"):
            check(f"the record carries {field}",
                  re.search(rf"^{field} \S", text, re.M) is not None, text)

    donor = MAPS / "q2dm1.bsp"
    if not check("the map the demo was recorded on is in the corpus",
                 donor.exists(), str(donor)):
        return 1

    print("\n=== held against the map it is about")
    out = movement(training, work / "with.q2ts", evidence, physics, [donor])
    m = SOURCE.search(out)
    check("the source it belongs to is found", bool(m) and m.group(1) == "found",
          out[-400:])
    m = HELD.search(out)
    check("and the evidence is held", bool(m) and m.group(1) == "OK"
          and int(m.group(2)) == 1, out[-400:])
    check("the chunk carries the provenance and the counts",
          "--- MOVEMENT" in out and "count=1" in out
          and physics[:16] in out, out[-600:])
    m = SNAPSHOT.search(out)
    check("the snapshot it goes into opens", bool(m) and m.group(1) == "OK",
          out[-300:])
    m = CARRIED.search(out)
    check("and carries the movement back out",
          bool(m) and int(m.group(1)) > 0, out[-300:])

    print("\n=== RED: evidence for a map this corpus does not have")
    other = work / "other.txt"
    other.write_text(
        evidence.read_text(encoding="utf-8").replace("map q2dm1",
                                                     "map q2dm9zzz"),
        encoding="utf-8")
    out = movement(training, work / "other.q2ts", other, physics, [donor])
    m = SOURCE.search(out)
    check("no source claims it", bool(m) and m.group(1) == "unknown",
          out[-300:])
    m = HELD.search(out)
    check("and it is refused rather than filed under nothing",
          bool(m) and m.group(1) != "OK" and int(m.group(2)) == 0, out[-400:])

    print("\n=== RED: evidence with no physics behind it")
    out = movement(training, work / "nophysics.q2ts", evidence, "", [donor])
    m = HELD.search(out)
    check("a trace with no movement rules behind it is refused",
          bool(m) and m.group(1) != "OK" and int(m.group(2)) == 0, out[-400:])

    print("\n=== and a corpus nobody has demos for is not broken")
    run = subprocess.run([str(training), "chunks", str(donor)],
                         capture_output=True, text=True, timeout=1800)
    check("its chunks render without a movement row",
          "MOVEMENT" not in run.stdout or "count=0" in run.stdout,
          run.stdout[-300:])

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
