r"""Keep a Studio run's judging evidence before the Studio clears its temp folder (brief 18: mg_b18_q3t2's digwalls and
clips findings could not be read - its job folder was gone when the run ended).

    python tools/mapgen_keep_job.py NAME OUT [--every SECONDS] [--temp DIR]

Waits for O:\Claude2\MapgenStudio\temp\NAME_* to appear, then while it stands copies into OUT what the delivery
gates read: request.txt, gates.txt, candidate.bsp, candidate.destroyed.json, gates/*, job/*.txt, job/warped_base.bsp,
job/baseline/*, job/lit/*.txt - each file again whenever it changed. Ends when the folder is gone (the run ended)
or after a day. Copies only; never touches the run.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

TEMP = Path(r"O:\Claude2\MapgenStudio\temp")
KEEP = ["request.txt", "gates.txt", "candidate.bsp", "candidate.destroyed.json", "gates/*", "job/*.txt",
        "job/warped_base.bsp", "job/baseline/*", "job/lit/*.txt"]


def sync(run: Path, out: Path) -> int:
    n = 0
    for pattern in KEEP:
        for f in run.glob(pattern):
            if not f.is_file():
                continue
            to = out / f.relative_to(run)
            try:
                st = f.stat()
                if to.is_file() and to.stat().st_size == st.st_size and to.stat().st_mtime >= st.st_mtime:
                    continue
                to.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, to)
                n += 1
            except OSError:
                pass                    # being written or just removed - the next pass takes it
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("out", type=Path)
    ap.add_argument("--every", type=float, default=60.0)
    ap.add_argument("--temp", type=Path, default=TEMP, help="another Studio's temp folder (a copy run beside the installed one)")
    a = ap.parse_args()
    began = time.time()
    run = None
    while time.time() - began < 86400:
        if run is None:
            found = sorted(a.temp.glob(f"{a.name}_*"))
            run = found[-1] if found else None
        if run is not None:
            if not run.is_dir():
                print(f"{run.name} ended; kept in {a.out}", flush=True)
                return 0
            out = a.out / run.name
            n = sync(run, out)
            if n:
                print(f"{time.strftime('%H:%M:%S')} {n} files", flush=True)
        time.sleep(a.every)
    return 1


if __name__ == "__main__":
    sys.exit(main())
