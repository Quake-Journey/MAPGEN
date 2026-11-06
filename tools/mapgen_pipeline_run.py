r"""Run `pipeline.exe` once with the arguments given, its output to a file and a done-file at the end - for a
generation started on its own (by `tools/mapgen_detached.ps1`, under `tools/mapgen_guard_stream.py --one MASK` so
it keeps to its cores), never from the IDE.

    python tools/mapgen_pipeline_run.py OUT_DIR -- PIPELINE.EXE ARG...

OUT_DIR gets `out.txt` (the pipeline's stdout and stderr), `exit.txt` (its exit code) and `done` when it ends.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

NO_WINDOW = 0x08000000


def main() -> int:
    if "--" not in sys.argv or len(sys.argv) < 4:
        print(__doc__)
        return 2
    k = sys.argv.index("--")
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    args = sys.argv[k + 1:]
    with open(out / "out.txt", "wb") as f:
        code = subprocess.run(args, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              creationflags=NO_WINDOW).returncode
    (out / "exit.txt").write_text(str(code), encoding="utf-8")
    (out / "done").write_text("done\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
