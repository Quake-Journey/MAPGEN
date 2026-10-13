r"""Brief 18 (mg_b18_q2dm3, 12.10): a start the plan moves stands - its body in air, a floor under its feet.

The move-spawn family put a start where its floor scan stopped, 4..12 over the floor: a player's box reaches 24 under
the origin and the game lifts him 9, so his feet stood in the floor - the starts gate on that run: «259 318 -79
buried» (moved from 486 383 -68). The start now stands 24 over the floor found to the unit, its whole box in air.

On the runs' own first-round maps (tools/fixtures/mapgen_prior_keep/*_baseline) at their options, seeds as listed, the
recut driver lists every spawn move's destination; each is asked the starts gate's own question (ask_starts: the body
sampled from 9 over the origin, the floor within 32 under the feet, a free step 32 off):

  PASS: every destination stands
  RED (--red, the driver's --old-spawn-place): destinations are buried

    python tools/check_mapgen_spawn_moves.py [--red] [--driver recut_driver.exe]
"""
from __future__ import annotations

import argparse
import gzip
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
FIX = TOOLS / "fixtures" / "mapgen_prior_keep"
CASES = FAILED = 0
MAPS = (("q2dm3", "plan_options.txt", (6695, 1, 2)), ("q2dm1", "plan_options_q2dm1.txt", (6675, 1, 2)))


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


def stands(b, o: list) -> str:
    """The starts gate's question (mapgen_delivery_gates.ask_starts) of one origin: '' or what is wrong."""
    o = [o[0], o[1], o[2] + 9.0]
    body = [[o[0] + dx, o[1] + dy, o[2] + dz] for dx in (-14, 0, 14) for dy in (-14, 0, 14) for dz in (-20, 0, 28)]
    if any(b.solid(p) for p in body):
        return "buried"
    if not any(b.solid([o[0], o[1], o[2] - 24 - dz]) for dz in range(2, 34, 4)):
        return "over no floor"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--driver", type=Path)
    a = ap.parse_args()
    from check_mapgen_static import Bsp
    work = Path(tempfile.mkdtemp(prefix="spawn_moves_"))
    try:
        exe = a.driver
        if not exe:
            from check_mapgen_recut import build_driver
            exe = build_driver(REPO, work)
        for name, opts_file, seeds in MAPS:
            base = work / f"{name}.bsp"
            base.write_bytes(gzip.decompress((FIX / f"mg_b18_{name}_baseline.bsp.gz").read_bytes()))
            b = Bsp(base)
            opts = (FIX / opts_file).read_text(encoding="utf-8").replace("# plan-options", "").split()
            moves, bad = 0, []
            for seed in seeds:
                r = subprocess.run([str(exe), str(base), "--seed", str(seed), "--ambition", "90", "--list", *opts]
                                   + (["--old-spawn-place"] if a.red else []), capture_output=True, text=True,
                                   errors="replace", timeout=900,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for m in re.finditer(r"^  spawn-move (\d+) to (\S+) (\S+) (\S+)$", r.stdout, re.M):
                    moves += 1
                    o = [float(v) for v in m.groups()[1:]]
                    why = stands(b, o)
                    if why:
                        bad.append(f"seed {seed} edit {m.group(1)} {o[0]:.0f} {o[1]:.0f} {o[2]:.2f} {why}")
            check(f"{name}: the plans move starts", moves > 0, f"{moves} moves")
            check(f"{name}: every moved start stands in air on a floor", moves > 0 and not bad,
                  f"{len(bad)} of {moves}: " + "; ".join(bad[:3]) if bad else f"{moves} of {moves}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{CASES} cases asserted, {FAILED} failures")
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
