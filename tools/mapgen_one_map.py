r"""One map, asked the way MAPGEN Studio asks it (ledger row 412) - for a check of one hypothesis on one map.

    python tools/mapgen_one_map.py PIPELINE.exe WORK_DIR --donor q3t2 [--second koldduel1] [--fidelity 10]
                                   [--seed 45] [--decor 100] [-- more of the pipeline's words]

The engine's donors and their light calibration come from the installed Studio's `engine` folder, the compiler is the
pinned one, the textures the client's `baseq2`; the job goes to WORK_DIR\job and the pipeline's own account to
WORK_DIR\pipeline_out.txt. Started through the load guard (its CPU share by the clock); a run of the PO's machine is
one run - never a loop.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

ENGINE = Path(r"O:\Claude2\MapgenStudio\engine")
GAME = r"O:\Claude2\q2pro-release\baseq2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pipeline", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--donor", required=True)
    ap.add_argument("--second")
    ap.add_argument("--fidelity", type=int, default=10)
    ap.add_argument("--seed", type=int, default=45)
    ap.add_argument("--decor", type=int)
    ap.add_argument("more", nargs="*")
    a = ap.parse_args()
    guard.pin_self()
    (a.work / "job").mkdir(parents=True, exist_ok=True)      # the pipeline writes into it, it does not make it
    donors = ENGINE / "donors"
    base = donors / f"{a.donor}.bsp"
    words = [str(a.pipeline), str(pinned_compiler()[0]), str(base), str(a.work / "job"), "q2mg", str(a.fidelity),
             str(a.seed), "--moddir", GAME, "--final"]
    if a.second:
        words += ["--donor", str(donors / f"{a.second}.bsp")]
    words.append("--hold-to-donor")
    light = base.with_suffix(".light.txt")
    if light.is_file() and light.read_text(encoding="utf-8").strip():
        words += ["--light-flags", light.read_text(encoding="utf-8").strip()]
    keys = base.with_suffix(".light_keys.txt")
    if keys.is_file() and keys.read_text(encoding="utf-8").strip():
        words += ["--light-keys", keys.read_text(encoding="utf-8").strip()]
    if a.decor is not None:
        words += ["--decor", str(a.decor)]
    words += ["--checkpoints", "0"] + a.more
    (a.work / "words.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
    t = time.time()
    with open(a.work / "pipeline_out.txt", "w", encoding="utf-8", errors="replace") as out:
        r = guard.run(words, stdout=out, stderr=out, timeout=4 * 3600)
    print("exit", r.returncode, "in", int(time.time() - t), "s")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
