"""Brief 16 D5 measured on the PO's own run: every accepted row of his ledger JUDGED again as a run judges it.

`pipeline.exe --replay-dry --replay-judge N` replays a run's ledger with no generation: each of the first N accepted
rows is built again from its edit and judged - the build, the walk from its parent's walk, every gate - and timed;
the ledger's verdict must come out again. This prints how long an attempt takes now against what the run took, and
what a run of B builds would take at that pace (brief 16 D5: a mean attempt within 10 s on q2dm3, a 140-build run
within 45 minutes).

    python tools/mapgen_judge_timing.py [--run DIR] [--rows N] [--builds B] [--work DIR] [--keep]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_equivalence import PIPELINE_SOURCES, build  # noqa: E402
from check_mapgen_plan_proof import ENGINE, MODDIR, launch_args  # noqa: E402

NO_WINDOW = 0x08000000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=Path(__file__).resolve().parent / "fixtures" / "mapgen_runs" / "mg_10_6695_q2dm3")
    ap.add_argument("--rows", type=int, default=64)
    ap.add_argument("--builds", type=int, default=140)
    ap.add_argument("--work", type=Path, default=Path(r"O:\Claude2\_agent_temp\claude\mapgen_judge_timing"))
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    if not (a.run / "ledger.txt").is_file():
        print(f"no ledger at {a.run}")
        return 2
    a.work.mkdir(parents=True, exist_ok=True)
    exe = build(a.work, "pipeline.exe", PIPELINE_SOURCES, strict=False)
    job = a.work / "job"
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)
    shutil.copy(a.run / "ledger.txt", job / "ledger.txt")
    args = launch_args(a.run)
    args[0], args[1], args[2] = str(ENGINE / "q2tool.exe"), str(ENGINE / "donors" / Path(args[1]).name), str(job)
    keep, i = [], 0
    while i < len(args):
        if args[i] in ("--memory", "--checkpoints"):
            i += 2
            continue
        if args[i] == "--moddir":
            keep += ["--moddir", str(MODDIR)]
            i += 2
            continue
        keep.append(args[i])
        i += 1
    keep += ["--memory", "4000", "--checkpoints", "0", "--replay-dry", "--replay-judge", str(a.rows)]
    print(f"judging {a.rows} accepted rows of {a.run.name} again", flush=True)
    began = time.time()
    subprocess.run([str(exe)] + keep, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=7200)
    wall = time.time() - began
    progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace")
    lines = progress.splitlines()
    rows, was = [], []
    for k, line in enumerate(lines):
        if "stage=dry-judged" not in line:
            continue
        r = dict(re.findall(r'(\w+)=("[^"]*"|\S+)', line))
        rows.append(r)
        # the run's own time for the row: the ledger's, on its dry-row line just before or after
        near = lines[max(0, k - 3):k + 4]
        row = next((dict(re.findall(r'(\w+)=("[^"]*"|\S+)', m)) for m in near
                    if "stage=dry-row" in m and f"edit={r['edit']} " in m), {})
        was.append(int(row.get("ms", "0")))
    if not rows:
        print("no judged rows - the replay said:")
        print("\n".join(lines[-8:]))
        return 1
    now = [int(r["ms"]) for r in rows]
    same = sum(1 for r in rows if r.get("verdict") == "ACCEPTED" and r.get("divergence") == r.get("ledger"))
    mean = sum(now) / len(now) / 1000.0
    print(f"  judged {len(rows)} rows: the same verdict and difference on {same}")
    print(f"  an attempt now {mean:.1f} s on average (median {sorted(now)[len(now) // 2] / 1000:.1f} s, "
          f"longest {max(now) / 1000:.1f} s); the run took {sum(was) / len(was) / 1000:.1f} s")
    print(f"  a run of {a.builds} builds at this pace: {a.builds * mean / 60:.0f} min of builds and walks "
          f"(the whole replay took {wall / 60:.1f} min)")
    whole = [r for r in rows if r.get("changed") == "4294967295"]
    if whole:
        why = {"1": "the parent kept nothing", "2": "its machines differ", "3": "a machine's own brush changed",
               "4": "too many brushes changed"}
        print("  walked whole: " + "; ".join(f"edit {r['edit']} {r['family']} {int(r['ms']) / 1000:.1f} s - "
                                              f"{why.get(r.get('refused', ''), 'reason ' + r.get('refused', '?'))}"
                                              for r in whole))
    # Fable's measure (brief 16 D5, «now 33 s»): the run's whole time over EVERY row of its ledger. Now: an accepted
    # row costs its judged time; a row the plan refuses before a build - by its proof, as tried before, or not
    # applying - costs none (the plan's own proving is counted apart); any other row still costs a build and a walk,
    # taken at the ledger's time scaled by what judging an accepted row now takes against what it took.
    dry = [dict(re.findall(r'(\w+)=("[^"]*"|\S+)', l)) for l in lines if "stage=dry-row" in l]
    proving = sum(int(dict(re.findall(r'(\w+)=(\S+)', l)).get("ms", "0")) for l in lines if "stage=plan-value" in l)
    scale = sum(now) / max(1, sum(was))
    built_rows = 0
    other = 0.0
    for d in dry:
        if d.get("was") == "ACCEPTED" or d.get("was") == "REJECTED_NOT_APPLIED":
            continue
        if d.get("proof", "-") not in ("passed", "-") or d.get("repeat") == "1":
            continue
        built_rows += 1
        other += int(d.get("ms", "0")) * scale
    total = sum(now) + other + proving
    ledger_s = sum(int(d.get("ms", "0")) for d in dry) / 1000.0
    print(f"  as Fable measures it (the run's time over all {len(dry)} rows of its ledger): now {total / 1000.0:.0f} s, "
          f"{total / 1000.0 / max(1, len(dry)):.1f} s a row ({len(rows)} judged, {built_rows} others still built, "
          f"the plan's proving {proving / 1000.0:.0f} s); the run's ledger {ledger_s:.0f} s, "
          f"{ledger_s / max(1, len(dry)):.1f} s a row")
    if not a.keep:
        shutil.rmtree(job, ignore_errors=True)
    return 0 if same == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
