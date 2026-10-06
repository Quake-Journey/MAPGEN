r"""One light pass run again and again on the same input, per compiler - to tell a fault of the input from a rare one
(ledger row 411: q3t2's light pass through files exited 0xC0000005 once in tools/check_q2tools_memory_files.py).

    python tools/mapgen_rad_repeat.py MAP WORK_DIR --compiler EXE [--compiler EXE ...] [--runs N] [--flags "..."]

MAP is built once with the first compiler (-bsp, -vis -fast, one thread), and that .bsp and .prt are the input of
every run: each compiler's `-rad -maxdata 8388608 <flags> -threads 1` on a fresh copy, N times. One line per run:
the exit code and the output's sha256 (the same input must light to the same bytes).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402

GAME = r"O:\Claude2\q2pro-release\baseq2"


def stage(exe: Path, words: list[str], target: Path):
    return guard.run([str(exe), *words, "-threads", "1", "-moddir", GAME, "-basedir", GAME, "-gamedir", GAME,
                      str(target)], capture_output=True, text=True, errors="replace", timeout=7200)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--compiler", type=Path, action="append", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--flags", default="")
    a = ap.parse_args()
    guard.pin_self()
    base = a.work / "input"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    shutil.copyfile(a.map, base / "q2mg.map")
    for words in (["-bsp"], ["-vis", "-fast"]):
        r = stage(a.compiler[0], words, base / "q2mg.map")
        print(f"input {' '.join(words)}: exit {r.returncode}", flush=True)
    faults = 0
    for c, exe in enumerate(a.compiler):
        for n in range(a.runs):
            d = a.work / f"c{c}_r{n}"
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir()
            for ext in ("map", "bsp", "prt"):
                if (base / f"q2mg.{ext}").is_file():
                    shutil.copyfile(base / f"q2mg.{ext}", d / f"q2mg.{ext}")
            r = stage(exe, ["-rad", "-maxdata", "8388608", *a.flags.split()], d / "q2mg.map")
            out = d / "q2mg.bsp"
            sha = hashlib.sha256(out.read_bytes()).hexdigest()[:16] if out.is_file() else "-"
            faults += r.returncode != 0
            (d / "rad.log").write_text(r.stdout + r.stderr, encoding="utf-8")
            print(f"{exe.parent.name}/{exe.name} run {n}: exit 0x{r.returncode & 0xffffffff:x}, output {sha}",
                  flush=True)
    print(f"{faults} faulted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
