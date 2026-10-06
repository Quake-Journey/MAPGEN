"""Liquids made other liquids, look and harm both (ledger row 410).

The PO, 05.10: «замена воды на лаву или кислоту и наоборот ... важно только не визуал менять, а физические свойства -
в лаве горят, в кислоте сжигает, в воде тонут ... то есть и визуал меняем и свойства». The game reads a liquid's harm
from the compiled contents, not its texture: the RELIQUID edit sets the brushes' contents (MapGenGeometry_SetLiquid)
and their warped sides' look; the run's choice (`--liquids`) also says what a new FLOOD holds.

On q2dm1 (its one pool of water, the low ground), at fidelity 20, seed 42, every other family skipped:
* `--liquids water-lava`, the reliquid alone: the plan deals one, and the judge refuses it as LETHAL - over a thousand
  places with no way back, lethal - which the walk only finds when the compiled leaves are lava: the harm changed;
* `--liquids water-lava`, the floods alone: what they lay is lava (the made map's brushes carry lava, the donor none),
  the donor's own water left as it was.
RED: MapGenGeometry_SetLiquid that changes nothing (a sandbox) - the reliquid is no longer refused for lethal places.

    python tools/check_mapgen_liquids.py [--work DIR]
"""
from __future__ import annotations

import argparse
import re
import shutil
import struct
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as load_guard  # noqa: E402
from check_mapgen_pipeline import SOURCES  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\liquids_guard")
Q2DM1 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
KINDS = ("reskin stairs-to-ramp stairs-to-lift relevel drop-detail relight swap-item room-block widen-connector "
         "open-connector turn-bundle reshape-room swap-bundles recompose-bundles graft-bundle recut-room push-wall "
         "move-spawn window dig pit flood span reliquid").split()
CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def build(tree: Path, out: Path) -> Path | None:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "pipeline.exe"
    r = load_guard.run(["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"), "-I" + str(tree / "src" / "mapgen"),
                        "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                       + [str(tree / s) for s in SOURCES] + ["-o", str(exe), "-lm", "-lz"], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-1500:])
        return None
    return exe


def liquids(bsp: Path) -> dict:
    d = bsp.read_bytes()
    o, n = struct.unpack_from("<ii", d, 8 + 8 * 14)
    c = {"lava": 0, "slime": 0, "water": 0}
    for i in range(n // 12):
        cont = struct.unpack_from("<iii", d, o + 12 * i)[2]
        c["lava"] += bool(cont & 8)
        c["slime"] += bool(cont & 16)
        c["water"] += bool(cont & 32)
    return c


def run(exe: Path, job: Path, keep: str, attempts: int) -> tuple[str, str, str]:
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    skip = [a for k in KINDS if k != keep for a in ("--skip-family", k)]
    r = load_guard.run([str(exe), str(pinned_compiler(quiet=True)[0]), str(Q2DM1), str(job), "q2mg", "20", "42",
                        "--moddir", str(GAME), "--max-attempts", str(attempts), "--hold-to-donor",
                        "--liquids", "water-lava"] + skip, capture_output=True, text=True, timeout=5400)
    progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace") if (job / "progress.txt").is_file() else ""
    ledger = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace") if (job / "ledger.txt").is_file() else ""
    return r.stdout, progress, ledger


def lethal(ledger: str) -> int:
    m = re.search(r"reliquid\s+REJECTED_UNPLAYABLE.*?\((\d+) lethal\)", ledger)
    return int(m.group(1)) if m else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    exe = build(REPO, a.work / "green")
    if not check("the generator builds", exe is not None):
        return 1
    out, progress, ledger = run(exe, a.work / "reliquid", "reliquid", 1)
    plan = re.search(r"stage=plan .*?reliquids=(\d+)", progress)
    check("water-lava: the plan deals q2dm1's pool", bool(plan) and int(plan.group(1)) == 1, plan.group(0) if plan else "")
    n = lethal(ledger)
    check("and the judge finds the lava LETHAL - the harm changed, not only the look", n > 1000,
          next((ln.strip()[:220] for ln in ledger.splitlines() if "reliquid" in ln), "no attempt"))
    out, progress, ledger = run(exe, a.work / "flood", "flood", 2)
    art = re.search(r"artifact\s+(\S+\.bsp)", out)
    made = liquids(Path(art.group(1))) if art and Path(art.group(1)).is_file() else {}
    donor = liquids(Q2DM1)
    check("water-lava: what the floods laid is lava, the donor's water left as it was",
          "ACCEPTED" in ledger and made.get("lava", 0) > 0 and made.get("water") == donor["water"],
          f"donor {donor}, made {made}")
    # RED: the contents left alone - the look alone changed
    sandbox = a.work / "red_src"
    shutil.rmtree(sandbox, ignore_errors=True)
    for d in ("src", "inc", "tools"):
        shutil.copytree(REPO / d, sandbox / d, ignore=shutil.ignore_patterns("mapgen_studio", "__pycache__"))
    geo = sandbox / "src" / "mapgen" / "mapgen_geometry.c"
    text = geo.read_text(encoding="utf-8")
    anchor = "    g->brushes[brush].contents = (g->brushes[brush].contents & ~mask) | liquid;\n"
    if check("RED: the mutation is where it says", text.count(anchor) == 1):
        geo.write_text(text.replace(anchor, ""), encoding="utf-8")
        red = build(sandbox, a.work / "red")
        if check("RED: the mutated generator builds", red is not None):
            _, _, ledger = run(red, a.work / "reliquid_red", "reliquid", 1)
            check("RED: with the contents left alone the pool is not found lethal - the case above goes red",
                  lethal(ledger) <= 1000, next((ln.strip()[:200] for ln in ledger.splitlines() if "reliquid" in ln), "none"))
    print(f"{CASES - FAILED}/{CASES} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
