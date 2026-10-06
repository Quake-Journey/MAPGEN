r"""A base the generator can rebuild is taken, and a base it refuses is refused with the reason said (ledger row 412).

The PO, 06.10, on q2duel1 refused at the first step in 7 seconds: «как копия могла выйти не такой если прошло 7
секунд?», «почему не пишет? нужен лог», «исправляй чтобы такие карты работали в генерации как доноры и чтобы студия
не писала левых ошибок», «пусть пишет точные причины». MEASURED: the copy differed only in q2duel1's trigger faces
(e1u3/trigger and the like, NODRAW, 112384 units, 2 planes) - faces its compiler kept and ours does not write, which no
player sees; and the pipeline said ERR_BASELINE and nothing else.

* q2duel1 passes the first step: the plan is dealt (`stage=plan`);
RED (a sandbox copy, NODRAW faces compared again): q2duel1 is refused, and the run's progress says why - a
`stage=baseline-refused` line naming the parts that differ (the surface) and the engine's own words.

    python tools/check_mapgen_base_refusal.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
import subprocess  # noqa: E402
from check_mapgen_pipeline import SOURCES  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = TOOLS.parent
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors\q2duel1.bsp")
GAME = r"O:\Claude2\q2pro-release\baseq2"
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\base_refusal")
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def build(work: Path, root: Path = None) -> Path:
    """The pipeline built from `root` (the tree, or a sandbox copy of it), as check_mapgen_pipeline builds it."""
    root = root or REPO
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "pipeline.exe"
    run = subprocess.run(["gcc", "-std=c17", "-O2", "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
                          "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                         + [str(root / s) for s in SOURCES] + ["-o", str(exe), "-lm", "-lz"],
                         capture_output=True, text=True)
    if run.returncode != 0 or not exe.is_file():
        raise SystemExit("cannot build the pipeline: " + (run.stderr or run.stdout)[-600:])
    return exe


def first_step(exe: Path, work: Path) -> str:
    """The run's progress after the first step and one try."""
    job = work / "job"
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)
    guard.run([str(exe), str(pinned_compiler()[0]), str(DONOR), str(job), "q2mg", "1", "666", "--moddir", GAME,
               "--final", "--hold-to-donor", "--max-attempts", "1"], capture_output=True, text=True, timeout=1800)
    p = job / "progress.txt"
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    green = first_step(build(a.work / "green_build"), a.work / "green")
    check("q2duel1: the first step passes - the plan is dealt", "stage=plan " in green,
          next((ln for ln in green.splitlines() if "stage=finish" in ln or "stage=plan " in ln), "no progress")[:200])
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "baserefusal")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_equivalence.c"
            data = target.read_bytes()
            line = b"return ti && (ti->flags & EQUIV_SURF_NODRAW);"
            if check("RED: the NODRAW rule is where the mutation says", data.count(line) == 1):
                target.write_bytes(data.replace(line, b"return false;", 1))
                red = first_step(build(a.work / "red_build", box.root), a.work / "red")
                said = next((ln for ln in red.splitlines() if "stage=baseline-refused" in ln), "")
                check("RED: with NODRAW faces compared, q2duel1 is refused at the first step",
                      "result=ERR_BASELINE" in red, "refused" if "result=ERR_BASELINE" in red else "not refused")
                check("RED: and the progress says why - the parts that differ and the engine's words",
                      "DIFF_SURFACE" in said and "trigger" in said and "what=\"" in said, said[:240] or "no line")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
