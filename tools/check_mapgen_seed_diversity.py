"""Do two seeds build different maps, and does one seed build the same one?

Codex's ruling of 2026-09-03, section 10: determinism means "same Recipe, same
seed, same toolchain, same artifact". It does not mean different seeds should
collapse to one artifact, and the measured seeds 75 and 67 producing the same
F75 BSP demonstrated a degenerate selection policy.

The selection happens in one place. The transaction takes the planned schedule
in order and stops when it reaches the fidelity it was asked for, so the
schedule IS what a fidelity spends, and whether two seeds can build different
maps is decided there - before any compile. This measures the schedule, which
is fast and necessary; the compiled expressive-range gate over 16 seeds at four
anchors is a separate and much slower measurement.

    python tools/check_mapgen_seed_diversity.py [--work DIR] [--donor PATH]

What is asserted:

  * one seed produces one schedule, twice running;
  * the plan does not take a fidelity, which is what makes the schedule for a
    seed a single list that every anchor takes a prefix of - the strict prefix
    schedule the ruling requires;
  * sixteen fixed seeds produce at least eight distinct schedules and no one
    schedule occupies more than four of the sixteen;
  * and the same holds for the STRUCTURAL prefix alone, because a difference
    that is only in which texture went where is not a different map.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260903\seeds")

SEEDS = [1, 7, 13, 42, 67, 75, 101, 233, 512, 777, 1024, 2026, 4096, 8191,
         31337, 65537]

# The kinds the schedule sorts first, because they are the ones that change
# what a map IS rather than what it looks like.
# Spelled exactly as MapGenGeometryEdit_KindName prints them. The first
# version of this set used underscores, matched nothing, and reported one
# distinct structural prefix for every seed - a filter that selects nothing
# makes every map look identical, which is the answer it was written to find.
STRUCTURAL = {"stairs-to-ramp", "stairs-to-lift", "room-block",
              "widen-connector", "turn-bundle", "reshape-room",
              "swap-bundles", "recompose-bundles"}

SOURCES = [
    "tools/mapgen_schedule_dump.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
]

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  -- {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


def build(work: Path) -> Path:
    exe = work / "schedule.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(REPO / "inc")] + [str(REPO / s) for s in SOURCES]
        + ["-o", str(exe), "-lm"], capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the schedule dumper")
    return exe


def schedule(exe: Path, donor: Path, seed: int) -> list[str]:
    run = subprocess.run([str(exe), str(donor), str(seed)],
                         capture_output=True, text=True, timeout=1800)
    if run.returncode != 0:
        raise SystemExit(f"the dumper refused seed {seed}: {run.stderr[-400:]}")
    return [line for line in run.stdout.splitlines()
            if re.match(r"^\s*\d+ ", line)]


def digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def structural_only(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) > 1 and parts[1] in STRUCTURAL:
            out.append(line)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--donor", type=Path, default=CORPUS / "q2dm1.bsp")
    ap.add_argument("--prefix", type=int, default=24,
                    help="how much of the schedule a low fidelity spends")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    if not args.donor.is_file():
        check("the donor is where it should be", False, str(args.donor))
        print(f"\n{CASES} cases asserted, {FAILED} failures")
        return 1

    exe = build(args.work)

    print("one seed, one schedule")
    once = schedule(exe, args.donor, SEEDS[0])
    twice = schedule(exe, args.donor, SEEDS[0])
    check("the same seed produces the same schedule, twice running",
          once == twice and once != [], f"{len(once)} vs {len(twice)} edits")

    print("\nthe schedule does not depend on the fidelity")
    source = (REPO / "inc" / "common" / "mapgen_geometry_edit.h").read_text(
        encoding="utf-8")
    plan_decl = re.search(r"MapGenGeometryEdit_Plan\s*\(([^;]*)\)", source,
                          re.S)
    check("the plan is declared where it should be", plan_decl is not None)
    if plan_decl:
        check("planning takes no fidelity, so one seed has ONE schedule that "
              "every anchor takes a prefix of",
              "fidelity" not in plan_decl.group(1).lower(),
              plan_decl.group(1).replace("\n", " "))

    print(f"\nsixteen seeds on {args.donor.name}")
    schedules, structural = {}, {}
    for seed in SEEDS:
        lines = schedule(exe, args.donor, seed)
        schedules[seed] = digest(lines)
        structural[seed] = digest(structural_only(lines)[:args.prefix])

    whole = Counter(schedules.values())
    check(f"at least eight distinct schedules in {len(SEEDS)} seeds",
          len(whole) >= 8, f"{len(whole)} distinct")
    check("no schedule occupies more than four of sixteen",
          whole.most_common(1)[0][1] <= 4,
          f"the commonest occupies {whole.most_common(1)[0][1]}")

    print(f"\nand the first {args.prefix} STRUCTURAL edits, which is what a "
          f"low fidelity actually spends")
    prefix = Counter(structural.values())
    check(f"at least eight distinct structural prefixes in {len(SEEDS)} seeds",
          len(prefix) >= 8, f"{len(prefix)} distinct")
    check("no structural prefix occupies more than four of sixteen",
          prefix.most_common(1)[0][1] <= 4,
          f"the commonest occupies {prefix.most_common(1)[0][1]}")

    print(f"\n  {len(whole)} distinct schedules, {len(prefix)} distinct "
          f"structural prefixes, over {len(SEEDS)} seeds")
    print(f"\n{CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
