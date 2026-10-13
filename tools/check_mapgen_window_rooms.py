r"""Brief 18 (mg_b18_q2dm1, 12.10): a base made larger and taller keeps its windows.

Every stretched q2dm1 before this brief glazed the two walls of its corridor at x -208 and -63 and one or two more;
mg_b18_q2dm1 dealt one wall and its glass gate failed (no shot pane, no fixed glass). A window's wall had to have, 16
out from each face, a point IN a room - and the rooms' table (256 while the watershed runs) was full 3100 times over
on q2dm1 at 150 % and 1.16 taller, so the corridor was in no room at all. The wall's sides are now asked whose room
they are by the open cells from them (MapGenRooms_Near).

On that run's own first-round map (tools/fixtures/mapgen_prior_keep/mg_b18_q2dm1_baseline) at its options, seeds 6675,
1 and 2:
  PASS: each plan glazes four walls or more, the corridor's two among them, and deals a shot pane, a pane on a plate
        and a fixed one
  RED (--red, the driver's --window-room-exact): one wall, the corridor's none

    python tools/check_mapgen_window_rooms.py [--red] [--driver recut_driver.exe]
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
SEEDS = (6675, 1, 2)
CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--driver", type=Path)
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="window_rooms_"))
    try:
        exe = a.driver
        if not exe:
            from check_mapgen_recut import build_driver
            exe = build_driver(REPO, work)
        base = work / "q2dm1.bsp"
        base.write_bytes(gzip.decompress((FIX / "mg_b18_q2dm1_baseline.bsp.gz").read_bytes()))
        opts = (FIX / "plan_options_q2dm1.txt").read_text(encoding="utf-8").replace("# plan-options", "").split()
        for seed in SEEDS:
            r = subprocess.run([str(exe), str(base), "--seed", str(seed), "--ambition", "90", "--list", *opts]
                               + (["--window-room-exact"] if a.red else []), capture_output=True, text=True,
                               errors="replace", timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            m = re.search(r"window walls: \d+ questions put to the donor's own walls, (\d+) glazed", r.stdout)
            offered = [ln for ln in r.stdout.splitlines() if "window offered" in ln]
            walls = [ln for ln in offered if "WALL of room" in ln]
            corridor = [ln for ln in walls if "x thin, -208..-195" in ln or "x thin, -63..-50" in ln]
            kinds = {k for k in ("shot", "plate", "window fixed") if any(k in ln for ln in offered)}
            check(f"seed {seed}: four walls glazed or more, the corridor's two among them",
                  bool(m) and int(m.group(1)) >= 4 and len(corridor) == 2,
                  f"{m.group(1) if m else '-'} walls glazed, {len(corridor)} of the corridor's")
            check(f"seed {seed}: a shot pane, a pane on a plate and a fixed one are dealt", len(kinds) == 3,
                  ", ".join(sorted(kinds)) or "none")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{CASES} cases asserted, {FAILED} failures")
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
