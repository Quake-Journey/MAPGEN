"""The anchors, run through the product path, with everything Codex asks about.

Contract 14.0.1 sets a TARGET rather than a maximum, and the anchors are what
the PO actually chooses between:

    F100  target    0 permille - the donor, exactly, by construction
    F90   target  100
    F75   target  250
    F50   target  500
    F25   target  750
    F0    target 1000

Three things have to be true of a run of them, and this measures all three
rather than asserting any:

  * F100 is EXACTLY zero. Not within fifty of zero - zero, because at fidelity
    100 the candidate is the donor's own geometry and there is nothing for a
    tolerance to hide;
  * the schedule is a strict prefix: a lower fidelity spends a superset of what
    a higher one spent, so nothing a fidelity did can be undone by asking for
    more of it;
  * each anchor rises by at least fifty permille over the one above it, which
    is what makes the control a control rather than a label.

Everything the report needs comes out of one run: the donor and seed, the
artifact and its SHA-256, the whole ledger with per-verdict counts, what was
reached and what was missing, and the wall-clock cost - which is a compile per
attempt and is meant to be visible.

    python tools/mapgen_anchor_sweep.py <donor.bsp> <work dir>
                                        [--fidelities 100,90,75,50,25,0]
                                        [--seed N] [--max-attempts N]
                                        [--json FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")

SOURCES = [
    "tools/mapgen_pipeline_driver.c",
    "src/mapgen/mapgen_pipeline.c",
    # The pipeline invents a map at fidelity zero, so everything the
    # chain is built on is linked with it.
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
    # The gate that decides whether the baseline is still the donor, and the
    # CPU count the parallel walk asks for. Both landed after this list was
    # last touched, so the sweep stopped linking and nothing said so until it
    # was next run.
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

SPENT = re.compile(r"^\s+spent\s+(\d+) attempted, (\d+) accepted,"
                   r" (\d+) permille reached, (\d+) missing")
LEDGER = re.compile(r"^\s+ledger\s+(.*)$")
DIVERGENCE = re.compile(r"^\s+divergence (\d+) permille, target (\d+), (.*)$")
BSP = re.compile(r"^\s+compiled\s+(\S+)\s+(\d+) bytes, sha256 (\S*)")
# The run names the file it judged, and says what is in it. Both lines
# come from the driver rather than from the shape of the job directory.
ARTIFACT = re.compile(r"^\s+artifact\s+(.+)$")
IDENTITY = re.compile(r"^\s+(\d+) bytes, sha256 (\S+), lighting (\d+)"
                      r" bytes, vis (\d+) bytes")


def build(out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2",
         "-I" + str(REPO / "inc"), "-I" + str(REPO / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / s) for s in SOURCES] + ["-o", str(out), "-lm", "-lz"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def sha256_of(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def one_anchor(exe: Path, donor: Path, work: Path, fidelity: int, seed: int,
               max_attempts: int, snapshot: str = "", manifest: str = "",
               scale: int = 0, goal: int = 4) -> dict:
    job = work / f"f{fidelity:03d}"
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)

    args = [str(exe), str(COMPILER), str(donor), str(job), f"q2mg_f{fidelity}",
            str(fidelity), str(seed), "--moddir", str(GAME)]
    if max_attempts:
        args += ["--max-attempts", str(max_attempts)]
    if fidelity == 0 and snapshot and manifest:
        # Zero invents a map out of what a corpus taught rather than forking
        # the donor, and the pipeline needs both to do it.
        args += ["--snapshot", snapshot, "--manifest", manifest,
                 "--scale", str(scale), "--goal", str(goal)]

    began = time.time()
    run = subprocess.run(args, capture_output=True, text=True, timeout=86400)
    seconds = time.time() - began

    out = run.stdout
    row = {"fidelity": fidelity, "seed": seed, "seconds": round(seconds, 1),
           "verdict": out.splitlines()[0].strip() if out.splitlines() else "",
           "command": " ".join(args), "stdout": out}
    for line in out.splitlines():
        m = SPENT.match(line)
        if m:
            row.update(attempted=int(m.group(1)), accepted=int(m.group(2)),
                       reached=int(m.group(3)), missing=int(m.group(4)))
            continue
        m = LEDGER.match(line)
        if m:
            row["ledger"] = m.group(1).strip()
            continue
        m = DIVERGENCE.match(line)
        if m:
            row.update(divergence=int(m.group(1)), target=int(m.group(2)),
                       band=m.group(3).strip())
            continue
        m = BSP.match(line)
        if m:
            row["bsp_bytes"] = int(m.group(2))
            continue
        m = ARTIFACT.match(line)
        if m:
            row["bsp_path"] = m.group(1).strip()
            continue
        m = IDENTITY.match(line)
        if m:
            row["artifact_bytes"] = int(m.group(1))
            row["artifact_sha256_short"] = m.group(2)
            row["lighting_bytes"] = int(m.group(3))
            row["vis_bytes"] = int(m.group(4))

    # The artifact the run actually judged - which the run now NAMES.
    #
    # This used to take sorted(glob("try_*/*.bsp"))[-1], the last attempt by
    # directory order, on the assumption that the last one compiled is the one
    # that was kept. It is not: the transaction keeps whichever attempt was
    # ACCEPTED and the pipeline writes the lit artifact over that one, so at
    # F50 and F25 on q2dm1 the accepted map was try_0037 and the last directory
    # was try_0100 - a rejected attempt, compiled DRAFT, no lighting at all.
    # Two of the six maps handed to the PO on 2026-09-07 were that draft.
    if row.get("bsp_path"):
        here = Path(row["bsp_path"])
        if here.is_file():
            row["bsp_sha256"] = sha256_of(here)
            # The hash the run printed is of the bytes it judged; if the file
            # has changed underneath, the row says so rather than hiding it.
            if row.get("artifact_sha256")                     and row["artifact_sha256"] != row["bsp_sha256"]:
                row["artifact_moved"] = True
        else:
            row["artifact_missing"] = True
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("donor", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--fidelities", default="100,90,75,50,25,0")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-attempts", type=int, default=0)
    ap.add_argument("--json", default="")
    # Fidelity zero only: what was learned, and what the target can resolve.
    ap.add_argument("--snapshot", default="")
    ap.add_argument("--manifest", default="")
    ap.add_argument("--scale", type=int, default=0)
    ap.add_argument("--goal", type=int, default=4)
    args = ap.parse_args(argv)

    args.work.mkdir(parents=True, exist_ok=True)
    exe = args.work / "bin" / "pipeline.exe"
    err = build(exe)
    if err:
        print(err)
        return 2

    print(f"donor {args.donor}")
    print(f"  sha256 {sha256_of(args.donor)}")
    print(f"  seed {args.seed}\n")

    rows = []
    for fidelity in [int(f) for f in args.fidelities.split(",")]:
        if fidelity == 0 and not (args.snapshot and args.manifest):
            print("F0   SKIPPED: fidelity zero invents a map and needs a"
                  " snapshot and a target manifest; without them this would"
                  " report the fork path's answer to a question it was never"
                  " asked\n")
            continue
        row = one_anchor(exe, args.donor, args.work, fidelity, args.seed,
                         args.max_attempts, args.snapshot, args.manifest,
                         args.scale, args.goal)
        rows.append(row)
        print(f"F{fidelity:<3} {row['verdict']:<26} "
              f"reached {row.get('reached', 0):4} of {row.get('target', 0):4}"
              f"  attempted {row.get('attempted', 0):3}"
              f"  accepted {row.get('accepted', 0):3}"
              f"  {row['seconds']:8.1f}s")
        if row.get("ledger"):
            print(f"       ledger {row['ledger']}")
        if row.get("bsp_sha256"):
            print(f"       {row['bsp_sha256']}")

    print("\n--- what the anchors have to be")
    hundred = next((r for r in rows if r["fidelity"] == 100), None)
    if hundred:
        exact = hundred.get("reached", -1) == 0
        print(f"F100 is exactly zero: {'yes' if exact else 'NO'}"
              f" ({hundred.get('reached')})")

    ordered = sorted([r for r in rows if r["fidelity"] != 100],
                     key=lambda r: -r["fidelity"])
    ok = True
    for above, below in zip(ordered, ordered[1:]):
        rise = below.get("reached", 0) - above.get("reached", 0)
        good = rise >= 50
        ok = ok and good
        print(f"F{above['fidelity']} -> F{below['fidelity']}: "
              f"{above.get('reached', 0)} -> {below.get('reached', 0)}"
              f"  (+{rise}) {'' if good else '  SHORT OF FIFTY'}")
    print(f"every anchor rises by fifty or more: {'yes' if ok else 'NO'}")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nwritten to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
