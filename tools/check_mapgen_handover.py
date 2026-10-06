"""Every guard, on the FILES in the maps folder, before anybody is told to
walk them.

A guard that exists and is not run is a guard that does not exist. The batch
the PO refused on 2026-09-08 had a seed-variety guard written, sitting beside
it in the tools directory, never executed: it would have failed six of its nine
cases - the three forks were seventeen to thirty-nine permille apart against a
required forty, and one construction stood in all three of them - and the maps
went out anyway.

    python tools/check_mapgen_handover.py [--maps DIR] [--skip-load]
                                          [--baseline BASE.bsp ...]

This runs, in order, and on the installed artifacts rather than on any run's
saved report:

    check_mapgen_delivery.py        finished maps, receipts, the bands they
                                    claim, water in basins, machines clear,
                                    and the real client loading them;
    check_mapgen_seed_variety.py    the forks of one fidelity are different
                                    maps and share no construction;
    check_mapgen_drowned.py         nothing spawns or stands in a liquid;
    check_mapgen_openness.py        no map leaks to the void;
    check_mapgen_texture_axes.py    no drawn face smears one column of texels
                                    along itself, which is the streak the PO
                                    photographed on 2026-09-10.

It reports one SUMMARY over all of them and exits non-zero if any failed, so
"the batch is checked" is a single command with a single answer. The
per-fidelity baselines the variety gate needs come from `--baseline`, or from
the receipt, which records the job directory each map was built in.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
RECEIPT = "mgtest_delivery.json"

SUMMARY = re.compile(r"^SUMMARY (\d+) cases asserted, (\d+) failures$", re.M)


def run(name: str, args: list[str]) -> tuple[int, int, str]:
    """One guard, its own summary line read back."""
    print(f"\n===== {name} {' '.join(args)}")
    proc = subprocess.run([sys.executable, str(REPO / "tools" / name)] + args,
                          capture_output=True, text=True, timeout=14400)
    out = proc.stdout + proc.stderr
    print(out.rstrip()[-8000:])
    m = SUMMARY.search(out)
    if not m:
        # A guard that did not reach its own summary has not answered, and an
        # unanswered guard is a failure rather than a silence.
        return 1, 1, f"{name}: no SUMMARY line (exit {proc.returncode})"
    cases, failures = int(m.group(1)), int(m.group(2))
    if proc.returncode and not failures:
        return cases, 1, f"{name}: exit {proc.returncode} with no failure"
    return cases, failures, ""


def families(maps: Path) -> dict[str, list[Path]]:
    """The forks, by fidelity: mgtest_f090s1..3 are one family, and the
    identity is not a family at all."""
    out: dict[str, list[Path]] = {}
    for bsp in sorted(maps.glob("mgtest_f*.bsp")):
        m = re.match(r"mgtest_(f\d+)s\d+$", bsp.stem)
        if m:
            out.setdefault(m.group(1), []).append(bsp)
    return {k: v for k, v in out.items() if len(v) > 1}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", type=Path, default=MAPS)
    ap.add_argument("--skip-load", action="store_true")
    ap.add_argument("--baseline", type=Path, action="append", default=[])
    a = ap.parse_args()

    cases = failures = 0
    broken: list[str] = []

    args = ["--maps", str(a.maps)]
    if a.skip_load:
        args.append("--skip-load")
    c, f, why = run("check_mapgen_delivery.py", args)
    cases += c
    failures += f
    if why:
        broken.append(why)

    receipt_path = a.maps / RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) \
        if receipt_path.is_file() else {}

    for fid, maps in sorted(families(a.maps).items()):
        base = list(a.baseline)
        if not base:
            for bsp in maps:
                said = receipt.get(bsp.stem, {})
                if said.get("baseline"):
                    base.append(Path(said["baseline"]))
        args = [str(m) for m in maps]
        for b in base:
            args += ["--baseline", str(b)]
        c, f, why = run("check_mapgen_seed_variety.py", args)
        cases += c
        failures += f
        if why:
            broken.append(f"{fid}: {why}")

    # The drowned gate reads the maps folder itself; the openness gate takes
    # one map at a time, so every handed-over file is put to it by name.
    c, f, why = run("check_mapgen_drowned.py", [])
    cases += c
    failures += f
    if why:
        broken.append(why)

    for bsp in sorted(a.maps.glob("mgtest_*.bsp")):
        c, f, why = run("check_mapgen_openness.py", [str(bsp)])
        cases += c
        failures += f
        if why:
            broken.append(f"{bsp.stem}: {why}")

    # And every drawn face wearing its texture rather than smearing one column
    # of texels along itself. This form compiles nothing: it reads the faces of
    # the artifacts about to be installed. The PO photographed the streak on
    # 2026-09-10 on maps that had passed every other gate here, because no gate
    # here looked at a texinfo.
    installed = sorted(a.maps.glob("mgtest_*.bsp"))
    if installed:
        args = []
        for bsp in installed:
            args += ["--map", str(bsp)]
        c, f, why = run("check_mapgen_texture_axes.py", args)
        cases += c
        failures += f
        if why:
            broken.append(why)

    print("\n===== the batch")
    for line in broken:
        print(f"  BROKEN  {line}")
    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
