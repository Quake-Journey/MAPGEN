r"""One request run again and again, to catch a rare fault (ledger row 411, Fable's brief 8: the 0xC0000005 in the walk).

    python tools/mapgen_fault_loop.py PIPELINE.exe WORK_DIR [--runs 30] [-- the pipeline's words after the job dir]

Each run gets a fresh job folder; a run that leaves a crash record (`crash.txt`, the dump beside it) keeps its whole
folder as `crashed_<n>`, every other one is removed. One line per run: its exit code, how long, how it ended, and
for a fault the record's place. The words default to the request the fault was first seen on: q2dm1, fidelity 20,
seed 42, the final profile, held to the donor, 4 attempts.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

DONOR = r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors\q2dm1.bsp"
GAME = r"O:\Claude2\q2pro-release\baseq2"
WORDS = ["q2mg", "20", "42", "--moddir", GAME, "--final", "--max-attempts", "4", "--hold-to-donor"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pipeline", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("words", nargs="*")
    a = ap.parse_args()
    guard.pin_self()
    a.work.mkdir(parents=True, exist_ok=True)
    words = a.words or WORDS
    faults = 0
    for n in range(a.runs):
        job = a.work / "job"
        shutil.rmtree(job, ignore_errors=True)
        job.mkdir()
        t0 = time.time()
        r = guard.run([str(a.pipeline), str(pinned_compiler()[0]), DONOR, str(job), *words],
                      capture_output=True, text=True, errors="replace", timeout=7200)
        took = time.time() - t0
        progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace") \
            if (job / "progress.txt").is_file() else ""
        finish = next((ln for ln in progress.splitlines() if "stage=finish" in ln), "")
        crash = job / "crash.txt"
        if crash.is_file():
            faults += 1
            kept = a.work / f"crashed_{n:02d}"
            shutil.rmtree(kept, ignore_errors=True)
            job.rename(kept)
            at = " | ".join((kept / "crash.txt").read_text(errors="replace").splitlines()[:4])
            print(f"run {n:2d}: FAULT exit 0x{r.returncode & 0xffffffff:08x} after {took:.0f} s - {at}", flush=True)
        else:
            print(f"run {n:2d}: exit {r.returncode} after {took:.0f} s - {finish[9:120] if finish else 'no finish'}",
                  flush=True)
    shutil.rmtree(a.work / "job", ignore_errors=True)
    print(f"{faults} faults in {a.runs} runs")
    return 0 if faults == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
