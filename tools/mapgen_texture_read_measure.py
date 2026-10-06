r"""What the compiler's texture reads cost a build (ledger row 411, Fable's brief 8 E).

    python tools/mapgen_texture_read_measure.py MAP WORK_DIR [--compiler EXE] [--repeat N]

The brief: a cache of textures only if it shows in the build time. So one try's build - `-bsp`, then `-vis -fast`,
the draft profile every try of a run takes - is run N times on MAP (a generator's .map) in a job object of its own,
and what Windows counts for it is printed per stage: the wall time, the bytes and operations read (the map, the
archives' directories and the texture entries it looks up).

Then the game's archives are read whole from the file cache by this process, timed: reading as many bytes as a stage
reads costs at most that rate - the most a texture cache could take off a build.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import shutil
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_io_measure import BASIC_AND_IO, k32  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

GAME = Path(r"O:\Claude2\q2pro-release\baseq2")


def stage(exe: Path, words: list[str], target: Path) -> tuple[float, int, int, int]:
    """(seconds, bytes read, read operations, exit code) of one stage, counted by its own job object."""
    k32.CreateJobObjectW.restype = wt.HANDLE
    job = k32.CreateJobObjectW(None, None)
    t0 = time.perf_counter()
    p = guard.popen([str(exe), *words, "-threads", "1", "-moddir", str(GAME), "-basedir", str(GAME),
                     "-gamedir", str(GAME), str(target)], stdout=__import__("subprocess").DEVNULL,
                    stderr=__import__("subprocess").DEVNULL)
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1F0FFF, False, p.pid)
    k32.AssignProcessToJobObject(wt.HANDLE(job), wt.HANDLE(h))
    code = p.wait(timeout=3600)
    took = time.perf_counter() - t0
    info = BASIC_AND_IO()
    k32.QueryInformationJobObject(wt.HANDLE(job), 8, ctypes.byref(info), ctypes.sizeof(info), None)
    k32.CloseHandle(wt.HANDLE(h))
    k32.CloseHandle(wt.HANDLE(job))
    return took, info.IoInfo.ReadTransferCount, info.IoInfo.ReadOperationCount, code


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--compiler", type=Path)
    ap.add_argument("--repeat", type=int, default=3)
    a = ap.parse_args()
    exe = a.compiler or pinned_compiler()[0]
    guard.pin_self()
    a.work.mkdir(parents=True, exist_ok=True)
    source = a.map.read_bytes()
    rows = []
    for n in range(a.repeat):
        d = a.work / f"r{n}"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        (d / "q2mg.map").write_bytes(source)
        for label, words in (("bsp", ["-bsp"]), ("vis -fast", ["-vis", "-fast"])):
            took, read, ops, code = stage(exe, words, d / "q2mg.map")
            rows.append((label, took, read, ops, code))
            print(f"  run {n} {label:10s} {took:6.2f} s, exit {code}, read {read / 1048576:6.1f} MB in {ops} operations",
                  flush=True)
    paks = sorted(GAME.glob("*.pak"))
    pak_bytes = sum(p.stat().st_size for p in paks)
    t0 = time.perf_counter()
    for p in paks:
        with p.open("rb") as f:
            while f.read(1 << 20):
                pass
    whole = time.perf_counter() - t0
    bsp = [r for r in rows if r[0] == "bsp"]
    mean_read = sum(r[2] for r in bsp) / len(bsp)
    mean_time = sum(r[1] for r in bsp) / len(bsp)
    per_mb = whole / max(1, pak_bytes / 1048576)
    print(f"  the archives: {len(paks)} files, {pak_bytes / 1048576:.0f} MB, read whole from the cache in {whole:.2f} s"
          f" ({per_mb * 1000:.2f} ms per MB)")
    print(f"  the bsp stage reads {mean_read / 1048576:.1f} MB a build in {mean_time:.2f} s; reading that much from the"
          f" cache costs {mean_read / 1048576 * per_mb:.3f} s - {100 * mean_read / 1048576 * per_mb / max(mean_time, 1e-6):.1f}"
          f" % of the stage, the most a texture cache could take off it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
