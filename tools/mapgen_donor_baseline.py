r"""Will the generator take this donor? Its first step alone, and what the oracle says about it (ledger rows 399-400).

    python tools/mapgen_donor_baseline.py PIPELINE.exe DONOR.bsp WORK_DIR [--equiv EQUIV.exe] [--max-attempts N]

Runs the pipeline on the donor with a budget of one attempt (N with --max-attempts, and then the verdicts of every
attempt are listed) (so a donor that passes its first step stops right
after the plan), prints the pipeline's verdict line and, when the run was refused at its baseline and an
equivalence driver is given, the oracle's account of the rebuilt copy against the donor - every axis, and the
counts this generator's own fixes are judged by (planes missing, clip drawn, interior space differences).
Heavy launches go through the load guard.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")


def main() -> int:
    args = sys.argv[1:]
    equiv = None
    attempts = "1"
    if "--max-attempts" in args:
        k = args.index("--max-attempts")
        attempts = args[k + 1]
        del args[k:k + 2]
    if "--equiv" in args:
        k = args.index("--equiv")
        equiv = Path(args[k + 1])
        del args[k:k + 2]
    if len(args) != 3:
        print(__doc__)
        return 2
    exe, donor, work = Path(args[0]), Path(args[1]), Path(args[2])
    job = work / (donor.stem + "_job")
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    compiler, _ = pinned_compiler(quiet=True)
    r = load_guard.run([str(exe), str(compiler), str(donor), str(job), "q2mg", "20", "42", "--max-attempts", attempts,
                        "--moddir", str(GAME)], capture_output=True, text=True, timeout=7200)
    progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace") if (job / "progress.txt").is_file() else ""
    stages = re.findall(r"stage=(\w+)", progress)
    print(f"{donor.name}: exit {r.returncode & 0xFFFFFFFF:#x}, stages {' '.join(dict.fromkeys(stages))}")
    print("  " + (r.stdout.splitlines()[0] if r.stdout else "(no output)"))
    baseline = job / "baseline" / "q2mg.bsp"
    if "stage=plan" in progress:
        print("  the donor passed its first step")
        finish = [ln for ln in progress.splitlines() if "stage=finish" in ln]
        print("  " + (finish[0][:230] if finish else "(no finish line)"))
        ledger = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace") if (job / "ledger.txt").is_file() else ""
        from collections import Counter
        rows = re.findall(r"^\s*\d+ (\S+)\s+(\S+)(.*)$", ledger, re.M)
        for (fam, verdict), n in Counter((f, v) for f, v, _ in rows).most_common():
            print(f"    {n:3d} {fam} {verdict}")
        for fam, verdict, rest in rows:
            if verdict not in ("ACCEPTED", "REJECTED_NOT_APPLIED"):
                print(f"      {fam} {verdict}: {rest.split('  ms ')[0].strip()[:160]}")
        return 0
    if equiv and baseline.is_file():
        e = subprocess.run([str(equiv), str(donor), str(baseline)], capture_output=True, text=True, timeout=3600)
        out = e.stdout
        (work / (donor.stem + "_equiv.txt")).write_text(out, encoding="utf-8")
        for line in out.splitlines():
            if line.startswith(("axis ", "space ", "planes ", "groups ", "materials ", "mapping ")):
                print("  " + line[:230])
    return 1


if __name__ == "__main__":
    sys.exit(main())
