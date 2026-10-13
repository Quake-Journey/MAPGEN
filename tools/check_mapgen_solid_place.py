"""Brief 18 D2 guard: a place of the walk is where a player stands CLEAR of every solid - and a start is put down as
the game puts a player down.

The walk settles every arrival («put a player there and let him stand»), trying a unit each way when he does not. A
body placed INSIDE a solid the engine calls «on the ground» (a trace that starts solid has a ground entity), so a
nudge into a wall «settled» - in the wall, in mid air: q3t2 at 1000 % and x3.11 tall kept a player falling past the
slanted fillet of its middle platform as a place at 701 -1882 -59, «with no way back», and the map was refused its
proportional height for it (check_mapgen_warp.py --red-solid shows that map). Since 13.10 such a body is no place
(a quarter of a unit in from every face: touching a floor is not being in it).

The rule alone broke the other end: q3t2's starts stand 15 over their floors, where a body is 9 inside the floor -
the walk had «settled» them there by the same quirk and walked out by the engine's step-up. So a start is put nine
over its origin, to fall to the floor, as the game does (PutClientInServer).

Asked, of the donors as installed (mapgen_reach_path's own account of the walk):
  1 q3t2 walks: 3000 places or more, every one of its 57 pickups in reach, no start stranded, it passes;
  2 q2dm1 and q2dm3 keep their verdicts and their pickups, and their places within 1 % of the walk before the rule
    (`--solid-places`): the rule takes out the handful of bodies that stood in a wall, nothing else;
  3 q3t2's three push pads each throw a player 300 up or more (they did before the rule, and must after).

RED: `--red` settles a start at its origin alone (`--no-spawn-lift`) - 1 and 3 fail: q3t2 has no place at all.

    python tools/check_mapgen_solid_place.py [--work DIR] [--red]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import check_mapgen_reach_gate as gate  # noqa: E402
from check_mapgen_equivalence import build  # noqa: E402

DONORS = Path(r"O:\Claude2\MapgenStudio\engine\donors")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen_solid_place")
NO_WINDOW = 0x08000000
FAILED = 0


def check(what: str, ok: bool, detail: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def walk(exe: Path, donor: str, *options: str) -> tuple[dict, list[float], str]:
    r = subprocess.run([str(exe), str(DONORS / f"{donor}.bsp"), "0", *options], capture_output=True, text=True,
                       creationflags=NO_WINDOW, timeout=3600)
    line = next((l for l in r.stdout.splitlines() if l.startswith("walk:")), "")
    m = re.search(r"places (\d+), no way back (\d+), of them lethal (\d+), pickups out of reach (\d+) of (\d+), starts "
                  r"stranded (\d+) of (\d+), passes (\d)", line)
    said = dict(zip(("places", "trapped", "lethal", "out", "pickups", "stranded", "starts", "passes"),
                    (int(v) for v in m.groups()))) if m else {}
    ups = [float(v) for v in re.findall(r"^push \d+ at [^:]*: up (-?\d+)", r.stdout, re.M)]
    return said, ups, line or r.stderr[-300:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    exe = build(a.work, "reach_path.exe",
                ["tools/mapgen_reach_path.c"] + [s for s in gate.SOURCES if not s.endswith("mapgen_reach_gate.c")],
                strict=False)
    red = ["--no-spawn-lift"] if a.red else []
    q, ups, line = walk(exe, "q3t2", "--pushes", *red)
    check("q3t2 walks: 3000 places or more, every pickup in reach, no start stranded",
          bool(q) and q["places"] >= 3000 and q["out"] == 0 and q["pickups"] == 57 and q["stranded"] == 0
          and q["passes"] == 1, line)
    for donor in ("q2dm1", "q2dm3"):
        now, _, l1 = walk(exe, donor, *red)
        was, _, l0 = walk(exe, donor, "--solid-places")
        check(f"{donor} keeps its verdict and its pickups, its places within 1 % of the walk before the rule",
              bool(now) and bool(was) and now["passes"] == was["passes"] and now["out"] == was["out"]
              and now["stranded"] == was["stranded"] and abs(now["places"] - was["places"]) <= 0.01 * was["places"]
              and now["trapped"] - now["lethal"] <= was["trapped"] - was["lethal"],
              f"{now.get('places')} places for {was.get('places')}, pickups out {now.get('out')} for {was.get('out')}, "
              f"no way back and alive {now.get('trapped', 0) - now.get('lethal', 0)} for "
              f"{was.get('trapped', 0) - was.get('lethal', 0)}")
    check("q3t2's three push pads each throw a player 300 up or more", len(ups) == 3 and min(ups) >= 300.0,
          ", ".join(f"{u:.0f}" for u in ups) or "no pad threw anybody")
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
