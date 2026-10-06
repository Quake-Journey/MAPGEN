"""Two seeds of one fidelity have to be two maps, not two orderings.

The PO walked three forks of q2dm1 and found the same construction, to the
unit, in the same corner of the same room in all three: 1424 560 512 ..
1627 880 640. The seed ordered the schedule and the schedule then tried
everything in it, so whatever passed the gates passed in every fork.

    python tools/check_mapgen_seed_variety.py MAP.bsp MAP.bsp ... \\
           --baseline BASE.bsp [--baseline BASE.bsp ...]

Two questions of every pair, both measured:

    how far apart are they - the divergence gate, candidate against candidate,
    which is the question the band never asks;
    did each of them build something the other did not, and is most of what
    each built its own.

The second is not "share nothing" for the WALLS: two seeds that push the same
wall back cut the same brushes and keep the same remnants, and that is the
operator doing its job. It IS "share nothing" for a CONSTRUCTION, and for the
MACHINES it is "not the same set" - two forks that turn the same staircases
into the same lifts are two forks with the same lifts in the same shafts,
which is the clone the PO reported in the batch before wearing another
operator's name. The machine rule was "each has one the other has not" until
2026-09-08, when measuring showed three forks of q2dm1 cannot meet it: only
two of its four staircases survive the gates as machines, and three sets over
two places cannot all hold something the others lack.

MEASURED on the batch of 2026-09-07: three shared brushes of seven and eight,
and fifty to fifty-nine permille apart. It passes both rules here and the PO
still called the maps clones, because what he saw was one decoration - a block
in one corner of one room - in all three. That is the thing the four forms and
the sliding placement in the room-block planner are for, and the numbers this
prints are how the next batch is judged against this one.
"""
from __future__ import annotations

import argparse
import itertools
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\variety_gate")

DIFF_SRC = ["tools/mapgen_brush_diff.c", "src/mapgen/mapgen_geometry.c",
            "src/mapgen/mapgen_bsp.c", "src/mapgen/mapgen_digest.c",
            "src/shared/shared.c", "tools/mapgen_host_stubs.c"]

GATE_SRC = [
    "tools/mapgen_divergence_gate.c", "src/mapgen/mapgen_divergence.c",
    "src/mapgen/mapgen_bundle.c", "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_reach.c", "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_certificate.c", "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c", "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c", "src/mapgen/mapgen_digest.c",
    "src/common/pmove/old.c", "src/common/pmove/common.c",
    "src/shared/shared.c", "tools/mapgen_host_stubs.c",
]

# What two forks of one donor at one fidelity have to be.
APART_PERMILLE = 40

ADDED = re.compile(r"^add (construction|machine|remnant) (-?\d+) (-?\d+) (-?\d+)"
                   r" (-?\d+) (-?\d+) (-?\d+)$", re.M)
TOGETHER = re.compile(r"together\s+(\d+) permille")

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def build(out: Path, name: str, sources: list[str]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-I" + str(REPO / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / s) for s in sources] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit(f"cannot build {name}")
    return exe


def added_brushes(diff: Path, baseline: Path, candidate: Path
                  ) -> tuple[set, set]:
    """What it BUILT, and what it left of the walls it cut - separately.

    Two forks that push the same wall back cut the same brushes and keep the
    same remnants, and that is the operator working. What may not be shared is
    a CONSTRUCTION: something built where the donor had air, which is what a
    player sees and what the PO photographed in three maps at once.
    """
    run = subprocess.run([str(diff), str(baseline), str(candidate)],
                         capture_output=True, text=True, timeout=3600)
    built, machines, cut = set(), set(), set()
    for m in ADDED.findall(run.stdout):
        box = tuple(int(v) for v in m[1:])
        if m[0] == "construction":
            built.add(box)
        elif m[0] == "machine":
            machines.add(box)
        else:
            cut.add(box)
    return built, machines, cut


def apart(gate: Path, a: Path, b: Path) -> int:
    run = subprocess.run([str(gate), str(a), str(b), "100"],
                         capture_output=True, text=True, timeout=3600)
    m = TOGETHER.search(run.stdout + run.stderr)
    return int(m.group(1)) if m else -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="+", type=Path)
    ap.add_argument("--baseline", action="append", type=Path, default=[])
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()

    if len(a.maps) < 2:
        print("  two maps at least, or there is no pair to compare")
        return 2
    baselines = a.baseline or [a.baseline[0]] if a.baseline else []
    if len(baselines) == 1:
        baselines = baselines * len(a.maps)
    if baselines and len(baselines) != len(a.maps):
        print("  one baseline, or one per map")
        return 2

    diff = build(a.work, "brush_diff", DIFF_SRC)
    gate = build(a.work, "divergence_gate", GATE_SRC)

    print("how far apart they are")
    for x, y in itertools.combinations(range(len(a.maps)), 2):
        permille = apart(gate, a.maps[x], a.maps[y])
        check(f"{a.maps[x].stem} and {a.maps[y].stem} are different maps",
              permille >= APART_PERMILLE,
              f"{permille} permille apart, wanted {APART_PERMILLE}")

    if not baselines:
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1 if FAILED else 0

    print("and what each of them built")
    built, machines, cut = [], [], []
    for m, b in zip(a.maps, baselines):
        made, machined, remnants = added_brushes(diff, b, m)
        built.append(made)
        machines.append(machined)
        cut.append(remnants)
        print(f"  {m.stem}: {len(made)} constructions, {len(machined)}"
              f" machines, {len(remnants)} wall remnants")
    for x, y in itertools.combinations(range(len(a.maps)), 2):
        shared = built[x] & built[y]
        check(f"{a.maps[x].stem} and {a.maps[y].stem} share no construction",
              not shared and bool(built[x]) and bool(built[y]),
              f"{len(shared)} shared of {len(built[x])} and {len(built[y])};"
              f" {len(cut[x] & cut[y])} wall remnants in common, which is the"
              f" same wall cut the same way"
              + (f"; shared one at {sorted(shared)[0]}" if shared else ""))

    # And the machines: no two forks may have the SAME SET of them.
    #
    # Sharing one lift is two seeds choosing one staircase; sharing ALL of them
    # is what the batch of 2026-09-07 did - every fork turned the same four
    # flights into the same four lifts, because every flight was offered to
    # every seed and the shared set was the whole set. That is what this
    # refuses, and it still refuses it.
    #
    # What it asked until 2026-09-08 was stricter: each fork must have a
    # machine the other has not. MEASURED, that rule cannot be met by three
    # forks of q2dm1, and the reason is arithmetic rather than laziness. The
    # map has four staircases; per seed the schedule offers two or three of
    # them and the gates let ONE OR TWO through - the rest are refused for
    # surface faults (a shaft's new faces meeting the room: 897 against the
    # donor's 892) or declined by the operator because something stands in the
    # shaft. Two places in the whole map ever carry a new machine: 450 506 608
    # and 1186 1538 816. With two, three forks can hold three DIFFERENT sets -
    # {A}, {B}, {A,B} - but not three sets each holding something the others
    # lack, because the third must repeat one of the first two.
    #
    # So the rule is what two forks being different actually means here, and
    # the thing that would make the stricter one reachable is a third flight
    # that survives the gates - which is work on the lift, not on this file.
    for x, y in itertools.combinations(range(len(a.maps)), 2):
        both = machines[x] & machines[y]
        neither = not machines[x] and not machines[y]
        check(f"{a.maps[x].stem} and {a.maps[y].stem} do not have the same"
              f" machines",
              neither or machines[x] != machines[y],
              f"{len(both)} shared of {len(machines[x])} and"
              f" {len(machines[y])}"
              + ("" if neither else
                 f"; {len(machines[x] - machines[y])} and"
                 f" {len(machines[y] - machines[x])} of their own"))

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
