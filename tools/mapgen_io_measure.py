r"""What a generation reads and writes, counted by Windows (ledger row 411).

    python tools/mapgen_io_measure.py DONOR.bsp WORK_DIR [--attempts N] [--pipeline EXE] [--compiler EXE] [-- extra pipeline words]

The PO, 05.10: «генератор пишет много данных на диск в процессе работы (и читает много очевидно)». The pipeline and
every compiler it spawns run in one Windows job object; the job's own accounting (JobObjectBasicAndIoAccountingInformation)
says how many read and write operations they made and how many bytes went each way - every file, whatever its folder.
Printed with what the job folder holds at the end, by kind of file, and the number of compiler launches.

The counts are of file operations as the programs asked for them: a read Windows answers from its cache and a write it
has not flushed yet are in them too. The bytes WRITTEN are the upper bound of what reaches the disk.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

GAME = r"O:\Claude2\q2pro-release\baseq2"
k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                  "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class BASIC_ACCOUNTING(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wt.DWORD), ("TotalProcesses", wt.DWORD), ("ActiveProcesses", wt.DWORD),
                ("TotalTerminatedProcesses", wt.DWORD)]


class BASIC_AND_IO(ctypes.Structure):
    _fields_ = [("BasicInfo", BASIC_ACCOUNTING), ("IoInfo", IO_COUNTERS)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("donor", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--attempts", default="4")
    ap.add_argument("--pipeline", type=Path)
    ap.add_argument("--compiler", type=Path, help="the map compiler (default: the pin's)")
    ap.add_argument("extra", nargs="*")
    a = ap.parse_args()
    exe = a.pipeline
    if exe is None:
        from check_mapgen_pipeline import build
        exe = build(a.work / "build")
        if exe is None:
            return 1
    job_dir = a.work / "job"
    if job_dir.exists():
        import shutil
        # a job that crashed is kept beside the next one: its record and dump are the only evidence of a rare fault
        if (job_dir / "crash.txt").is_file():
            job_dir.rename(a.work / f"job_crashed_{int(time.time())}")
        else:
            shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True)
    k32.CreateJobObjectW.restype = wt.HANDLE
    job = k32.CreateJobObjectW(None, None)
    guard.pin_self()
    t0 = time.time()
    p = guard.popen([str(exe), str(a.compiler or pinned_compiler(quiet=True)[0]), str(a.donor), str(job_dir), "q2mg", "20", "42",
                     "--moddir", GAME, "--final", "--max-attempts", a.attempts, "--hold-to-donor", *a.extra],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1F0FFF, False, p.pid)
    assigned = bool(k32.AssignProcessToJobObject(wt.HANDLE(job), wt.HANDLE(h)))
    out, _ = p.communicate(timeout=7200)
    info = BASIC_AND_IO()
    ok = k32.QueryInformationJobObject(wt.HANDLE(job), 8, ctypes.byref(info), ctypes.sizeof(info), None)
    took = time.time() - t0
    io = info.IoInfo
    print(f"ran {took:.0f} s, exit {p.returncode}, in the job: {assigned}, counted: {bool(ok)};"
          f" processes {info.BasicInfo.TotalProcesses}")
    print(f"  written: {io.WriteTransferCount / 1048576:.1f} MB in {io.WriteOperationCount} operations")
    print(f"  read:    {io.ReadTransferCount / 1048576:.1f} MB in {io.ReadOperationCount} operations")
    print(f"  other:   {io.OtherOperationCount} operations (opens, closes, deletes, directory reads)")
    progress = (job_dir / "progress.txt").read_text(encoding="utf-8", errors="replace") if (job_dir / "progress.txt").is_file() else ""
    builds = max((int(x) for x in __import__("re").findall(r"compiles=(\d+)", progress)), default=0)
    print(f"  builds {builds}, attempts {progress.count('stage=attempt')}; per build: "
          f"{io.WriteTransferCount / 1048576 / max(1, builds):.1f} MB written, {io.ReadTransferCount / 1048576 / max(1, builds):.1f} MB read")
    kinds, sizes = Counter(), Counter()
    for f in job_dir.rglob("*"):
        if f.is_file():
            kinds[f.suffix or f.name] += 1
            sizes[f.suffix or f.name] += f.stat().st_size
    print("  left in the job folder: " + ", ".join(f"{n} {k} ({sizes[k] / 1048576:.1f} MB)" for k, n in kinds.most_common()))
    print("  " + (out or "").strip().splitlines()[0] if out else "")
    for line in progress.splitlines():
        if "stage=memory" in line or "stage=finish" in line:
            print("  " + line.strip())
    # row 411: Windows counts a pipe's bytes as written - the run says how many went program to program
    pipes = __import__("re").search(r"stage=memory-used pipes_mb=([\d.]+)", progress)
    if pipes:
        disk = io.WriteTransferCount / 1048576 - float(pipes.group(1))
        print(f"  through pipes, memory to memory: {float(pipes.group(1)):.1f} MB; to files: {disk:.1f} MB"
              f" ({disk / max(1, builds):.2f} MB per build)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
