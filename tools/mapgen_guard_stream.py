r"""Run guards one after another on a given set of logical CPUs, below normal priority, with no window - beside a
generation that holds its own cores (brief 18's last queue: the Studio's run on 2..5, every guard again on 6..11,
all inside the PO's share).

    python tools/mapgen_guard_stream.py OUT MASK NAME=check_x.py[,ARG,...] [NAME=...]

Each guard's output goes to OUT\NAME.log; OUT\summary_<MASK>.txt gets one line per guard as it ends
(NAME, exit code, seconds, its last line) and OUT\done_<MASK> when the stream is through. MASK is hex (3c0).

The load guard would pin a guard's children to its own cores of the hour (the generation's); here it is told this
stream's mask instead, so the two never share a core.
"""
from __future__ import annotations

import ctypes
import runpy
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
BELOW_NORMAL = 0x00004000
NO_WINDOW = 0x08000000


def one(mask: int, script: str, args: list[str]) -> None:
    """This process pinned, the load guard told the same mask, the guard run here as its own main."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.GetCurrentProcess()
    k32.SetProcessAffinityMask(h, ctypes.c_size_t(mask))
    k32.SetPriorityClass(h, BELOW_NORMAL)
    sys.path.insert(0, str(TOOLS))
    import mapgen_load_guard as load_guard
    load_guard.affinity_mask = lambda now=None: mask
    sys.argv = [script] + args
    runpy.run_path(script, run_name="__main__")


def main() -> int:
    if len(sys.argv) > 3 and sys.argv[1] == "--one":
        one(int(sys.argv[2], 16), sys.argv[3], sys.argv[4:])
        return 0
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    out, mask = Path(sys.argv[1]), sys.argv[2].lower()
    out.mkdir(parents=True, exist_ok=True)
    summary = out / f"summary_{mask}.txt"
    for spec in sys.argv[3:]:
        name, _, rest = spec.partition("=")
        parts = rest.split(",")
        log = out / f"{name}.log"
        began = time.time()
        with open(log, "wb") as f:
            code = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--one", mask,
                                   str(TOOLS / parts[0])] + parts[1:], cwd=str(REPO), stdout=f,
                                  stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                  creationflags=BELOW_NORMAL | NO_WINDOW).returncode
        lines = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        with open(summary, "a", encoding="utf-8") as s:
            s.write(f"{name}\texit {code}\t{time.time() - began:.0f}s\t{lines[-1][:200] if lines else ''}\n")
    (out / f"done_{mask}").write_text("done\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
