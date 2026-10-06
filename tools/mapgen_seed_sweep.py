"""Sixteen seeds at an anchor: how many different maps come out?

Codex's ruling of 2026-09-03, section 10, sets the expressive-range gate:

  * ten repeats of one Recipe and seed are byte-identical;
  * for each donor, sixteen fixed seeds at F90/F75/F50/F25 must each yield at
    least eight distinct compiled structural signatures, and no one signature
    may occupy more than four of the sixteen;
  * every sample stays in its fidelity band and passes all hard gates;
  * report the pairwise structural-divergence distribution, and pick
    representative and extreme samples by a declared rule rather than by hand.

This runs it. Each sample is a real generation through the real pinned
compiler, so an anchor of sixteen seeds is measured in tens of minutes, not
seconds; `--anchors` and `--seeds` cut it down while something is being
developed, and finished runs are reused unless `--fresh` is given.

    python tools/mapgen_seed_sweep.py [--donor PATH] [--anchors 90 75 50 25]
        [--seeds N] [--work DIR] [--repeats 10] [--fresh]

Structure is compared by the descriptor in mapgen_structural_signature.py -
walls, facings, space shares and machines - which is deliberately blind to
textures, items and lights, and whose noise floor is calibrated against a donor
compared with its own no-edit round trip: 0.0000 to 0.0007 there, against 0.31
and more between genuinely different maps.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapgen_structural_signature import cluster, descriptor, distance  # noqa

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260903\sweep")

SEEDS = [1, 7, 13, 42, 67, 75, 101, 233, 512, 777, 1024, 2026, 4096, 8191,
         31337, 65537]

SOURCES = [
    "tools/mapgen_pipeline_driver.c",
    "src/mapgen/mapgen_pipeline.c",
    "src/mapgen/mapgen_synthesis.c",
    "src/mapgen/mapgen_architecture.c",
    "src/mapgen/mapgen_blueprint.c",
    "src/mapgen/mapgen_brush.c",
    "src/mapgen/mapgen_layout.c",
    "src/mapgen/mapgen_mix.c",
    "src/mapgen/mapgen_snapshot.c",
    "src/mapgen/mapgen_training.c",
    "src/mapgen/mapgen_features.c",
    "src/mapgen/mapgen_space.c",
    "src/mapgen/mapgen_topology.c",
    "src/mapgen/mapgen_wiring.c",
    "src/mapgen/mapgen_entities.c",
    "src/mapgen/mapgen_genome.c",
    "src/mapgen/mapgen_lineage.c",
    "src/mapgen/mapgen_random.c",
    "src/mapgen/mapgen_transaction.c",
    "src/mapgen/mapgen_equivalence.c",
    "src/mapgen/mapgen_divergence.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_reach.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_mapfile.c",
    "src/mapgen/mapgen_compiler.c",
    "src/mapgen/mapgen_digest.c",
    "src/mapgen/mapgen_report.c",
    "src/common/q2prox_cpu_topology.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]


def build(work: Path) -> Path:
    exe = work / "pipeline.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-w", "-DUSE_LITTLE_ENDIAN=1",
         "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0",
         "-I" + str(REPO / "inc"), "-I" + str(REPO / "src" / "mapgen")]
        + [str(REPO / s) for s in SOURCES] + ["-o", str(exe), "-lm", "-lz"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-3000:])
        raise SystemExit("cannot build the pipeline driver")
    return exe


def generate(exe: Path, donor: Path, job: Path, fidelity: int,
             seed: int) -> dict:
    """One sample. Returns what came out, including where the map is."""
    job.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run = subprocess.run(
        [str(exe), str(COMPILER), str(donor), str(job), "q2mg",
         str(fidelity), str(seed), "--moddir", str(GAME)],
        capture_output=True, text=True, timeout=7200)
    text = run.stdout + run.stderr
    verdict = text.strip().splitlines()[0].split()[0] if text.strip() else "?"
    bsp = None
    for candidate in sorted(job.rglob("q2mg.bsp")):
        if "baseline" not in candidate.parts:
            bsp = candidate
    return {"verdict": verdict, "bsp": bsp, "seconds": time.time() - started,
            "text": text}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--donor", type=Path, default=CORPUS / "q2dm1.bsp")
    ap.add_argument("--anchors", type=int, nargs="*", default=[90, 75, 50, 25])
    ap.add_argument("--seeds", type=int, default=len(SEEDS))
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--repeats", type=int, default=0,
                    help="prove N repeats of one seed are byte-identical")
    ap.add_argument("--threshold", type=float, default=0.02)
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    if args.fresh and args.work.exists():
        shutil.rmtree(args.work, ignore_errors=True)
    args.work.mkdir(parents=True, exist_ok=True)
    exe = build(args.work)
    seeds = SEEDS[:args.seeds]

    if args.repeats:
        print(f"{args.repeats} repeats of one seed")
        hashes = set()
        for repeat in range(args.repeats):
            job = args.work / f"repeat_{repeat}"
            if job.exists():
                shutil.rmtree(job, ignore_errors=True)
            out = generate(exe, args.donor, job, args.anchors[0], seeds[0])
            if out["bsp"]:
                hashes.add(sha256(out["bsp"]))
            print(f"  repeat {repeat}: {out['verdict']} "
                  f"{out['seconds']:.0f}s "
                  f"{sha256(out['bsp'])[:16] if out['bsp'] else '(no map)'}")
        print(f"  {len(hashes)} distinct artifacts in {args.repeats} repeats "
              f"- must be 1\n")

    for fidelity in args.anchors:
        print(f"=== fidelity {fidelity}, {len(seeds)} seeds")
        maps, verdicts = [], Counter()
        for seed in seeds:
            job = args.work / f"f{fidelity}_s{seed}"
            done = job / "done.txt"
            if done.is_file() and not args.fresh:
                verdict, path = done.read_text(encoding="utf-8").split("\n")[:2]
                out = {"verdict": verdict,
                       "bsp": Path(path) if path else None, "seconds": 0.0}
            else:
                out = generate(exe, args.donor, job, fidelity, seed)
                done.write_text(f"{out['verdict']}\n"
                                f"{out['bsp'] if out['bsp'] else ''}\n",
                                encoding="utf-8")
            verdicts[out["verdict"]] += 1
            print(f"  seed {seed:6d}: {out['verdict']:24s} "
                  f"{out['seconds']:6.0f}s "
                  f"{sha256(out['bsp'])[:16] if out['bsp'] and out['bsp'].is_file() else '(no map)'}")
            if out["bsp"] and out["bsp"].is_file():
                maps.append((seed, out["bsp"]))

        if len(maps) < 2:
            print(f"  only {len(maps)} maps came out; nothing to compare\n")
            continue

        descriptors = [descriptor(path) for _, path in maps]
        labels = cluster(descriptors, args.threshold)
        counts = Counter(labels)
        pairs = sorted(distance(descriptors[i], descriptors[k])
                       for i in range(len(maps))
                       for k in range(i + 1, len(maps)))
        print(f"  verdicts: {dict(verdicts)}")
        print(f"  {len(counts)} distinct structures in {len(maps)} maps; "
              f"the commonest occupies {counts.most_common(1)[0][1]}")
        print(f"  pairwise distance: min {pairs[0]:.4f}, "
              f"median {pairs[len(pairs) // 2]:.4f}, max {pairs[-1]:.4f}")
        # The declared rule, so nothing is chosen by hand: the representative
        # is the map closest to every other, the extreme is the furthest.
        totals = [sum(distance(d, other) for other in descriptors)
                  for d in descriptors]
        rep = min(range(len(maps)), key=lambda i: totals[i])
        far = max(range(len(maps)), key=lambda i: totals[i])
        print(f"  representative: seed {maps[rep][0]}   "
              f"extreme: seed {maps[far][0]}")
        want = 8 if fidelity else 12
        cap = 4 if fidelity else 2
        ok = len(counts) >= want and counts.most_common(1)[0][1] <= cap
        print(f"  {'PASS' if ok else 'FAIL'}  the expressive-range gate at "
              f"F{fidelity} wants >= {want} distinct and <= {cap} of "
              f"{len(maps)} alike\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
