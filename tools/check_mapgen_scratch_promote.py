r"""Brief 25 item 1: the skeleton's candidates handed to the engine in their order of merit, no engine probe.

`mapgen_scratch.make` as the Studio runs it (the engine named: every candidate built) on a small request, then
`--promote` of the second candidate in the order, as the Studio does when the engine refuses the first:
  * order.json lists every built candidate, the first is the base (its map, skeleton, measure, style in the folder);
  * no «the engine accepts it» / «refuses it» line - the engine was not run;
  * after `--promote K2` the base is candidate K2's files byte for byte, its light flags beside it, its record written.
No generator (pipeline.exe) runs - the engine's path is a name only. Pinned by tools/mapgen_load_guard.py.

    python tools/check_mapgen_scratch_promote.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard  # noqa: E402
import mapgen_scratch  # noqa: E402

WORK = Path(r"O:\Claude2\_agent_temp\claude\scratch_promote")
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    said: list[str] = []
    res = mapgen_scratch.make(WORK, {"players": 2}, 7, "mg_pr", 3, GAME, 3, 12, log=said.append,
                              engine=Path("pipeline.exe"), workers=3)
    order = json.loads((WORK / "order.json").read_text(encoding="utf-8")) if (WORK / "order.json").is_file() else []
    first = order[0] if order else None
    same_first = first is not None and (WORK / "mg_pr.bsp").read_bytes() == (WORK / f"cand{first}" / "mg_pr.bsp").read_bytes()
    no_probe = not any("the engine" in ln for ln in said)
    ok1 = len(order) >= 2 and same_first and no_probe and res.get("candidate") == first
    print(f"{'PASS' if ok1 else 'FAIL'} the order {order}, the first (cand{first}) is the base, no engine probe ({len(said)} log lines)")
    if len(order) < 2:
        print("FAIL fewer than two candidates built")
        return 1
    k2 = order[1]
    r = subprocess.run([sys.executable, str(TOOLS / "mapgen_scratch.py"), str(WORK), "--name", "mg_pr", "--promote", str(k2)],
                       capture_output=True, text=True)
    files = ("mg_pr.bsp", "mg_pr.map", "skeleton.txt", "survey.json", "style.json", "style.txt")
    same = all((WORK / f).read_bytes() == (WORK / f"cand{k2}" / f).read_bytes() for f in files)
    rec = json.loads((WORK / "record.json").read_text(encoding="utf-8")) if (WORK / "record.json").is_file() else {}
    ok2 = r.returncode == 0 and same and bool(rec.get("rows")) and (WORK / "promoted.txt").read_text().strip() == f"cand{k2}"
    print(f"{'PASS' if ok2 else 'FAIL'} --promote {k2}: the base is cand{k2}'s files, its record written (exit {r.returncode})")
    shutil.rmtree(WORK, ignore_errors=True)
    print("PASS" if ok1 and ok2 else "FAIL")
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
