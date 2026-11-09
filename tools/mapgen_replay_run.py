r"""Replay the engine stage of a Studio run (brief 32, 08.11: the PO's mg_new_84162 - «Карта не собралась» after a
good skeleton): the run's own `launches.txt` command, with its paths moved to a copy of the run and a pipeline.exe of
choice, through the load guard (below normal, pinned to the hour's share, `--memory` as the Studio runs it).

    python tools/mapgen_replay_run.py RUN_COPY PIPELINE_EXE JOB_DIR [--skip-family NAME ...] [--max-attempts N]

RUN_COPY is a folder holding the run's `launches.txt` and its `scratch/` (the skeleton's .bsp and .light_fit.json),
copied out of the Studio's temp folder. Prints the engine's finish line (`stage=finish result=...`) and the artifact.
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard  # noqa: E402


def launch_args(run_copy: Path) -> list[str]:
    line = (run_copy / "launches.txt").read_text(encoding="utf-8").splitlines()[-1]
    words = shlex.split(line.split(" pipeline.exe ", 1)[1], posix=False)
    return words


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_copy", type=Path)
    ap.add_argument("pipeline", type=Path)
    ap.add_argument("job", type=Path)
    ap.add_argument("--skip-family", action="append", default=[])
    ap.add_argument("--max-attempts", type=int, default=0)
    a = ap.parse_args()
    words = launch_args(a.run_copy)
    # q2tool, the skeleton's bsp, the job: the first three words; the bsp moves to the copy's scratch folder
    q2tool, bsp = words[0], Path(words[1])
    words[1] = str(a.run_copy / "scratch" / bsp.name)
    a.job.mkdir(parents=True, exist_ok=True)
    words[2] = str(a.job)
    for f in a.skip_family:
        words += ["--skip-family", f]
    if a.max_attempts:
        i = words.index("--max-attempts")
        words[i + 1] = str(a.max_attempts)
    argv = [str(a.pipeline), q2tool] + words[1:]
    run = mapgen_load_guard.run(argv, capture_output=True, text=True, timeout=3600)
    (a.job / "replay_stdout.txt").write_text(run.stdout or "", encoding="utf-8")
    (a.job / "replay_stderr.txt").write_text(run.stderr or "", encoding="utf-8")
    progress = (a.job / "progress.txt").read_text(encoding="utf-8") if (a.job / "progress.txt").exists() else ""
    fin = [ln for ln in progress.splitlines() if "stage=finish" in ln]
    print(f"exit {run.returncode}")
    print(fin[-1] if fin else "no finish line")
    m = re.search(r'bsp="([^"]*)"', fin[-1]) if fin else None
    if m and m.group(1):
        print("artifact", m.group(1), "exists" if Path(m.group(1)).exists() else "MISSING")
    tried = re.findall(r"family=(\S+)", progress)
    print("families tried:", " ".join(sorted(set(tried))) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
