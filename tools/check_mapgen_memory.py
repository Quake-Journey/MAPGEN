r"""The generator works in memory and makes the same map (ledger row 411, Fable's brief 8 B).

With `--memory MB` the run's working files - each try's .map, .bsp, .prt, .pts, the base's, the light pass's - are
named sections the pinned compiler opens (patch P13), not files; the disk keeps the ledger, the progress, the finished
map and, unless `--checkpoints 0`, each accepted try's .map and .bsp once (what a stopped run resumes from).

On q2dm1, the Studio's request shape (fidelity 20, seed 42, the final profile, held to the donor, 4 attempts):

* in files and in memory the run accepts the same tries and finishes with the same map - byte for byte but the
  visibility lump (full vis on several threads is not the same from run to run, row 404);
* in memory with checkpoints the job folder holds the accepted tries' .map and .bsp and nothing else of a try - no
  rejected try, no .prt, no .pts;
* in memory without checkpoints it holds no try but the finished one, and the run writes under 1 MB to files per
  build, the finished map included (Windows' own count for the run and every compiler it starts, one job object,
  less the bytes the run says went through pipes from program to program - Windows counts those as written too);
* a run in memory stopped by a fault (the crash seam, at the thirteenth candidate - after
  three accepted tries, so the resume must read their checkpoints) resumes from its checkpoints and
  finishes with the map the run that was never stopped made;
* a share of memory too small for the sections: the run works in files and says so (`stage=memory mode=files`).
RED: the same generator with the checkpoint write taken out (a sandbox copy) - the stopped run cannot be resumed to
that map; the resume case goes red.

    python tools/check_mapgen_memory.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_pipeline import SOURCES  # noqa: E402
from mapgen_io_measure import BASIC_AND_IO, k32  # noqa: E402
from mapgen_memfile import compiler_has_memory_files  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
from mapgen_red_sandbox import Sandbox  # noqa: E402

REPO = TOOLS.parent
GAME = r"O:\Claude2\q2pro-release\baseq2"
DONOR = Path(r"O:\Claude2\MapgenStudio\engine\donors\q2dm1.bsp")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\memory_guard")
ARGS = ["q2mg", "20", "42", "--moddir", GAME, "--final", "--max-attempts", "4", "--hold-to-donor"]
LUMP_VISIBILITY = 3
CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def build(root: Path, out: Path) -> Path | None:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "pipeline.exe"
    r = subprocess.run(["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-I" + str(root / "inc"),
                        "-I" + str(root / "src" / "mapgen"), "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
                        "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                       + [str(root / s) for s in SOURCES] + ["-o", str(exe), "-lm", "-lz"],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:])
        return None
    return exe


def run(exe: Path, job: Path, *extra: str) -> dict:
    """One run in a job object of its own: its exit, progress, ledger rows and what Windows counted it writing."""
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    k32.CreateJobObjectW.restype = wt.HANDLE
    jo = k32.CreateJobObjectW(None, None)
    p = guard.popen([str(exe), str(pinned_compiler()[0]), str(DONOR), str(job), *ARGS, *extra],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1F0FFF, False, p.pid)
    k32.AssignProcessToJobObject(wt.HANDLE(jo), wt.HANDLE(h))
    out, _ = p.communicate(timeout=7200)
    info = BASIC_AND_IO()
    k32.QueryInformationJobObject(wt.HANDLE(jo), 8, ctypes.byref(info), ctypes.sizeof(info), None)
    k32.CloseHandle(wt.HANDLE(h))
    k32.CloseHandle(wt.HANDLE(jo))
    return outcome(job, p.returncode, out, info.IoInfo.WriteTransferCount)


def outcome(job: Path, code: int, out: str, written: int) -> dict:
    progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace") \
        if (job / "progress.txt").is_file() else ""
    ledger = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace") if (job / "ledger.txt").is_file() else ""
    finish = re.search(r'stage=finish result=(\S+).*bsp="([^"]*)"', progress)
    builds = max((int(x) for x in re.findall(r"compiles=(\d+)", progress)), default=0)
    return {"code": code, "out": out, "progress": progress, "written": written, "builds": builds,
            "rows": re.findall(r"^\s*\d+ \S+\s+(?:ACCEPTED|REJECTED_\S+)", ledger, re.M),
            "result": finish.group(1) if finish else "", "bsp": Path(finish.group(2)) if finish and finish.group(2) else None}


def but_vis(path: Path | None) -> list[bytes]:
    """The map's lumps but the visibility lump (its size may differ too, which moves every lump after it in the file:
    the lumps are compared, not the file)."""
    if not path or not path.is_file():
        return []
    d = path.read_bytes()
    return [d[o:o + n] for i, (o, n) in enumerate(struct.unpack_from("<ii", d, 8 + 8 * k) for k in range(19))
            if i != LUMP_VISIBILITY]


def files_of_tries(job: Path) -> list[str]:
    return sorted(str(f.relative_to(job)).replace("\\", "/") for f in job.glob("try_*/*") if f.is_file())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    guard.pin_self()
    a.work.mkdir(parents=True, exist_ok=True)
    compiler = pinned_compiler()[0]
    if not check("the pinned compiler has memory files (P13)", compiler_has_memory_files(compiler), str(compiler)):
        return 1
    exe = build(REPO, a.work / "bin")
    if not check("the generator builds", exe is not None):
        return 1

    files = run(exe, a.work / "files")
    mem = run(exe, a.work / "memory", "--memory", "4096")
    # four attempts do not reach fidelity 20's band: the run ends ERR_TARGET_UNREACHABLE with the map it made - the
    # same end, and the same map, whichever way it worked
    check("in files: the run finishes with a map", bool(files["result"]) and bool(files["bsp"]),
          f"{files['result']} {files['out'][-200:].strip() if not files['bsp'] else ''}")
    check("in memory: the run says it works in memory", "stage=memory mode=memory" in mem["progress"],
          next((ln for ln in mem["progress"].splitlines() if "stage=memory" in ln), "no memory line"))
    check("in memory: the run finishes as the run in files did, with a map", mem["result"] == files["result"]
          and bool(mem["bsp"]), f"{mem['result']} {mem['out'][-300:].strip() if not mem['bsp'] else ''}")
    check("in files and in memory the same tries are taken the same way", files["rows"] == mem["rows"]
          and len(files["rows"]) > 0, f"{len(files['rows'])} rows / {len(mem['rows'])} rows")
    check("the finished map is on the disk where a run in files puts it",
          bool(mem["bsp"]) and mem["bsp"].is_file() and not str(mem["bsp"]).startswith("mem:")
          and mem["bsp"].relative_to(a.work / "memory").as_posix()
          == (files["bsp"].relative_to(a.work / "files").as_posix() if files["bsp"] else ""), str(mem["bsp"]))
    same = but_vis(files["bsp"]) == but_vis(mem["bsp"]) and len(but_vis(mem["bsp"])) > 0
    check("in files and in memory the finished map is the same, byte for byte but the visibility lump", same,
          f"{sum(map(len, but_vis(files['bsp'])))} / {sum(map(len, but_vis(mem['bsp'])))} bytes")
    accepted = [r for r in mem["rows"] if "ACCEPTED" in r]
    left = files_of_tries(a.work / "memory")
    stray = [f for f in left if not f.endswith(("/q2mg.map", "/q2mg.bsp", "/q2mg.certificates.txt"))]
    check("in memory with checkpoints: the job folder holds the accepted tries' .map and .bsp, nothing else of a try",
          not stray and len({f.split("/")[0] for f in left}) == len(accepted),
          f"{len(accepted)} accepted; {len(left)} files: {', '.join(left[:8])}{'; stray ' + ', '.join(stray[:4]) if stray else ''}")

    bare = run(exe, a.work / "bare", "--memory", "4096", "--checkpoints", "0")
    left = files_of_tries(a.work / "bare")
    check("in memory without checkpoints: the run finishes with the same map", bare["result"] == mem["result"]
          and but_vis(bare["bsp"]) == but_vis(mem["bsp"]) and len(but_vis(bare["bsp"])) > 0, bare["result"])
    check("in memory without checkpoints: no try reaches the disk but the finished one",
          len({f.split("/")[0] for f in left}) <= 1, ", ".join(left))
    # row 411: Windows counts a pipe's bytes as written (measured: 10 MB through a pipe, 10 MB written) - the run
    # says how many went program to program in memory; the rest went to files
    def disk(r: dict) -> float:
        m = re.search(r"stage=memory-used pipes_mb=([\d.]+)", r["progress"])
        return r["written"] / 1048576 - (float(m.group(1)) if m else 0.0)
    finished = bare["bsp"].stat().st_size + bare["bsp"].with_suffix(".map").stat().st_size         if bare["bsp"] and bare["bsp"].is_file() else 0
    check("in memory without checkpoints: under 1 MB written to files per build, the finished map included",
          "stage=memory-used" in bare["progress"] and disk(bare) / max(1, bare["builds"]) < 1.0,
          f"{disk(bare):.2f} MB to files over {bare['builds']} builds ({disk(bare) / max(1, bare['builds']):.2f} MB a"
          f" build, the finished map {finished / 1048576:.2f} MB of it); in files {disk(files):.1f} MB"
          f" ({disk(files) / max(1, files['builds']):.2f} MB a build)")

    def stop_and_resume(exe_: Path, job: Path) -> tuple[dict, dict]:
        stopped = run(exe_, job, "--memory", "4096", "--crash-at", "13")
        log = (job / "progress.txt").read_text(encoding="utf-8", errors="replace") \
            if (job / "progress.txt").is_file() else ""
        (job / "progress_stopped.txt").write_text(log, encoding="utf-8")
        p = guard.popen([str(exe_), str(pinned_compiler()[0]), str(DONOR), str(job), *ARGS, "--memory", "4096",
                         "--resume"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        out, _ = p.communicate(timeout=7200)
        return stopped, outcome(job, p.returncode, out, 0)

    stopped, resumed = stop_and_resume(exe, a.work / "resume")
    taken = sum(1 for r in stopped["rows"] if "ACCEPTED" in r)
    check("in memory: the crash seam stops the run part way, after tries were accepted",
          stopped["result"] == "" and stopped["code"] != 0 and taken > 0,
          f"exit {stopped['code']}, {len(stopped['rows'])} rows, {taken} accepted")
    replayed = re.search(r"stage=resume replayed=(\d+)", resumed["progress"])
    check("in memory: the stopped run replays its ledger from the checkpoints and ends with the map the run never"
          " stopped made", bool(replayed) and int(replayed.group(1)) == len(stopped["rows"])
          and resumed["result"] == mem["result"] and len(but_vis(resumed["bsp"])) > 0
          and but_vis(resumed["bsp"]) == but_vis(mem["bsp"]),
          f"{resumed['result']}; " + " | ".join(ln[9:120] for ln in resumed["progress"].splitlines() if "resume" in ln))

    small = run(exe, a.work / "small", "--memory", "1", "--max-attempts", "1")
    line = next((ln for ln in small["progress"].splitlines() if "stage=memory" in ln), "")
    check("a share of memory too small: the run works in files and says why",
          "mode=files" in line and "not enough free memory" in line and small["result"] != "", line[:200])

    if not a.no_red:
        box = Sandbox(REPO, "memory")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_transaction.c"
            text = target.read_text(encoding="utf-8")
            anchor = "    if (!MapGenFs_IsMem(bsp_path) || !g_txn_checkpoints || !g_txn_disk_root[0])\n        return;\n"
            if check("RED: the checkpoint write is where the mutation says", text.count(anchor) == 1):
                target.write_text(text.replace(anchor, anchor.replace("    if (", "    if (true || ", 1)),
                                  encoding="utf-8")
                red = build(box.root, a.work / "red_bin")
                if check("RED: the generator without checkpoints builds", red is not None):
                    stopped, again = stop_and_resume(red, a.work / "red_resume")
                    gone = re.search(r"stage=resume replayed=(\d+)", again["progress"])
                    check("RED: without the checkpoints the stopped run cannot replay its accepted tries - the case"
                          " above goes red", not gone or int(gone.group(1)) != len(stopped["rows"])
                          or not (again["result"] == mem["result"] and but_vis(again["bsp"]) == but_vis(mem["bsp"])),
                          " | ".join(ln[9:120] for ln in again["progress"].splitlines() if "resume" in ln))
        finally:
            box.dispose()
    print(f"{CASES - FAILED}/{CASES} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
