r"""Does the generator take every map of the game as its base? (the PO, 09.10, after q2dm6 was refused at its first
step: «Генератор же должен быть универсален ... у меня еще таких карт 100500, что каждый раз к тебе обращаться?»)

For each .bsp of the game's maps folder and of the Studio's donors (q2dm1..q2dm8 live in the paks) (the generator's own maps and test outputs left out) the pipeline runs as the Studio
runs it - in memory, one map at a time, below normal priority, no window - until its first step has said its word and
the plan of edits is made: «taken» (the rebuilt copy is the donor), «taken-faithful» (taken by the faithful rebuild,
its residue small), «refused» (with the axes and the oracle's words), «no-plan», «error» or «timeout». The process
tree is stopped there; nothing is compiled past the baseline. Resumable: a map already in the table is not run again.

    python tools/mapgen_donor_survey.py [--maps DIR ...] [--pipeline EXE] [--q2tool EXE] [--out DIR] [--only a,b]
                                        [--limit N] [--timeout S]

Writes OUT/survey.tsv (one row a map) and OUT/summary.txt; a refused map keeps its progress.txt and run.txt in
OUT/jobs/NAME, every other job folder is removed.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
STUDIO = Path(r"O:\Claude2\MapgenStudio\engine")
OUT = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\survey")
SKIP = re.compile(r"^(mg_|q2mg_|mgtest_|new_f\d|.*_test|test_)", re.I)
BELOW_NORMAL, NO_WINDOW = 0x00004000, 0x08000000


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)


def run_one(exe: Path, q2tool: Path, bsp: Path, job: Path, timeout: float) -> tuple[str, str, float]:
    if job.exists():
        shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)
    log = (job / "run.txt").open("w", encoding="utf-8", errors="replace")
    began = time.time()
    p = subprocess.Popen([str(exe), str(q2tool), str(bsp), str(job), "q2mg", "10", "1", "--moddir", str(GAME),
                          "--max-attempts", "1", "--memory", "1500", "--checkpoints", "0"],
                         stdout=log, stderr=subprocess.STDOUT, creationflags=BELOW_NORMAL | NO_WINDOW)
    prog = job / "progress.txt"
    verdict, what = "", ""
    try:
        while True:
            text = prog.read_text(encoding="utf-8", errors="replace") if prog.exists() else ""
            if "stage=baseline-refused" in text:
                m = re.search(r"stage=baseline-refused axes=(\S+) what=\"([^\"]*)", text)
                verdict, what = "refused", (m.group(1) + " | " + m.group(2)) if m else "refused"
            elif re.search(r"stage=plan ", text):
                m = re.search(r"stage=plan offered=(\d+)", text)
                verdict = "taken-faithful" if "stage=baseline-faithful" in text else "taken"
                what = f"offered {m.group(1) if m else '?'}"
                f = re.search(r"stage=baseline-faithful (planes_missing=\S+ planes_added=\S+ residue_area=\S+ "
                              r"drawn=\S+ mapping=\S+)", text)
                if f:
                    what += " | " + f.group(1)
            elif "stage=finish" in text:
                m = re.search(r"stage=finish result=(\S+)", text)
                verdict, what = ("no-plan" if m and m.group(1) == "OK" else "error"), (m.group(1) if m else "")
            if verdict:
                break
            if p.poll() is not None:
                verdict, what = "error", f"exit {p.returncode} before a verdict"
                break
            if time.time() - began > timeout:
                verdict, what = "timeout", f"no verdict in {timeout:.0f} s"
                break
            time.sleep(1.0)
    finally:
        if p.poll() is None:
            kill_tree(p.pid)
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
        log.close()
    return verdict, what.replace("\t", " ").replace("\n", " "), time.time() - began


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", type=Path, action="append", default=[])
    ap.add_argument("--pipeline", type=Path, default=STUDIO / "pipeline.exe")
    ap.add_argument("--q2tool", type=Path, default=STUDIO / "q2tool.exe")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=420.0)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    table = a.out / "survey.tsv"
    done = {}
    if table.exists():
        for line in table.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 2:
                done[parts[0]] = parts[1]
    else:
        table.write_text("map\tverdict\tseconds\twhat\n", encoding="utf-8")
    only = {x.strip().lower() for x in a.only.split(",") if x.strip()}
    folders = a.maps or [MAPS, STUDIO / "donors"]
    seen, maps = set(), []
    for folder in folders:
        for p in sorted(folder.glob("*.bsp")):
            if SKIP.match(p.stem) or (only and p.stem.lower() not in only) or p.stem.lower() in seen:
                continue
            seen.add(p.stem.lower())
            maps.append(p)
    ran = 0
    for bsp in maps:
        if bsp.stem in done:
            continue
        if a.limit and ran >= a.limit:
            break
        job = a.out / "jobs" / bsp.stem
        verdict, what, secs = run_one(a.pipeline, a.q2tool, bsp, job, a.timeout)
        with table.open("a", encoding="utf-8") as f:
            f.write(f"{bsp.stem}\t{verdict}\t{secs:.0f}\t{what}\n")
        if verdict in ("taken", "taken-faithful", "no-plan"):
            shutil.rmtree(job, ignore_errors=True)
        else:
            for x in job.iterdir():
                if x.name not in ("progress.txt", "run.txt"):
                    shutil.rmtree(x, ignore_errors=True) if x.is_dir() else x.unlink(missing_ok=True)
        done[bsp.stem] = verdict
        ran += 1
    rows = [l.split("\t") for l in table.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    counts = {}
    for r in rows:
        counts[r[1]] = counts.get(r[1], 0) + 1
    summary = [f"{len(rows)} maps: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))]
    summary += [f"  {r[0]}: {r[1]} - {r[3][:300]}" for r in rows if r[1] not in ("taken", "taken-faithful")]
    (a.out / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    (a.out / "survey.done").write_text("done\n", encoding="utf-8")
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
