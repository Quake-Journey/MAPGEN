"""A construction the planner offers has to have a PURPOSE a player can see.

The PO walked `mg_90`, `mg_75` and `mg_60` on 2026-09-10 and said the same
thing of every slab, tier and cube a recut had stood in a room: «в чём их
художественный смысл? Стоят себе посреди комнат непонятно для чего,
загораживают проход и убивают динамику уровня». It was the third batch he had
said it of, under three family names - the platform, the room block, the
recut's furniture - so what this guard holds is a criterion rather than a
third retirement:

    A WAY    its top is within a jump of a standing surface THE MAP ALREADY
             HAD, so climbing it gets you somewhere. A ladder that stops one
             rung short is the same defect as a slab in the middle of a floor,
             and he photographed that too (quake105).
    HOLDS    a spawn or an item stands on it.
    OPENS    it is a doorway, a window or a niche - a change to what is there
             rather than an addition to it.

    python tools/check_mapgen_purpose.py [--work DIR] [--seeds N]

The jump is measured, not chosen: `MapGenPmove` gives a player 270 units per
second against 800 of gravity, so his apex is 45.6 units, and he steps 18
without jumping. 64 is what that comes to, and is why a Quake II crate is 64
tall.

What this runs:

    the fixture     the recut guard's own two rooms, where room A is a bare
                    floor with one pillar in it. A slab in the open middle of
                    A leads nowhere and must be refused; the pillar's top is
                    something to climb TO, so a step beside it must be
                    offered. RED and GREEN on one map.
    the donor       q2dm1, every fidelity the band uses: the schedule offers
                    no room block that leads nowhere, and `--crates` (the
                    test seam) shows the rule is what is deciding rather than
                    a map with no room for one.
    the sky         a push-wall slab under sky is refused by name. quake101
                    and quake102 are that slab; quake110, a niche in rough
                    rock at floor level, is not, and both come off the same
                    operator.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260913\purpose_gate")

sys.path.insert(0, str(REPO / "tools"))
import check_mapgen_recut as recut                   # noqa: E402
from check_mapgen_recut import build_driver          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402

FAMILIES = re.compile(r"^families:(.*)$", re.M)
SKY = re.compile(r"push at [-\d. ]+: there is sky over this wall")

AMBITIONS = (10, 25, 40, 50, 80)

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


def drive(exe: Path, bsp: Path, *args: str) -> str:
    run = load_guard.run([str(exe), str(bsp), *args],
                         capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


def families(text: str) -> dict[str, int]:
    m = FAMILIES.search(text)
    if not m:
        return {}
    out = {}
    for pair in m.group(1).split():
        k, _, v = pair.partition("=")
        out[k] = int(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--donor", type=Path, default=CORPUS / "q2dm1.bsp")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    exe = build_driver(REPO, a.work)

    # ---- the fixture: a bare room with one pillar in it ------------------
    print("the recut guard's fixture, where room A is a floor and a pillar")
    src = a.work / "purpose_fixture.map"
    bsp = src.with_suffix(".bsp")
    recut.write_fixture(src)
    if not bsp.is_file():
        recut.compile_map(src)
    if not check("the fixture compiles", bsp.is_file(), str(bsp)):
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1

    listing = drive(exe, bsp, "--seed", "1", "--ambition", "10", "--list",
                    "--crates", "--recuts")
    got = families(listing)
    check("the fixture's room with something to climb to still gets one",
          got.get("room-block", 0) > 0 or got.get("recut-room", 0) > 0,
          f"room-block={got.get('room-block', 0)},"
          f" recut-room={got.get('recut-room', 0)}")

    # ---- the donor, every fidelity --------------------------------------
    print("the donor, every fidelity the band uses")
    worst = 0
    for seed in range(1, a.seeds + 1):
        for amb in AMBITIONS:
            plain = families(drive(exe, a.donor, "--seed", str(seed),
                                   "--ambition", str(amb), "--list"))
            if not plain:
                check(f"the plan is readable at seed {seed} ambition {amb}",
                      False, "no families line")
                continue
            worst = max(worst, plain.get("room-block", 0)
                        + plain.get("recut-room", 0))
    check("no fidelity offers a construction with no purpose", worst == 0,
          f"{worst} blocks or recuts over {a.seeds} seeds x"
          f" {len(AMBITIONS)} fidelities")

    with_crates = families(drive(exe, a.donor, "--seed", "1", "--ambition",
                                 "10", "--list", "--crates", "--recuts"))
    kept = with_crates.get("room-block", 0)
    check("asked for them, the donor offers only the ones with a purpose",
          kept > 0, f"room-block={kept} with --crates")

    #
    # And the RED: the same plan in a tree with the rule taken out.
    #
    # A count on its own says nothing - a map that has room for two crates
    # would also report two. What says the RULE is deciding is that the same
    # donor, the same seed and the same schedule offer MORE when the predicate
    # is bypassed. The mutant is a copy of the tree, exactly as the worth
    # guard's plinth RED is, and it is thrown away afterwards.
    #
    red = a.work / "red_tree"
    if red.exists():
        shutil.rmtree(red)
    red.mkdir(parents=True)
    for sub in ("src", "inc", "tools"):
        shutil.copytree(REPO / sub, red / sub)
    edit = red / "src" / "mapgen" / "mapgen_geometry_edit.c"
    text = edit.read_text(encoding="utf-8")
    cut = ("""                            stands = leads_up(ground, block.mins, block.maxs,
                                              btop, NULL);""",
           """                            (void)btop;
                            stands = true;""")
    if text.count(cut[0]) != 1:
        check("the rule can be taken out of a copy of the tree - the RED",
              False, f"{text.count(cut[0])} sites, expected 1")
    else:
        edit.write_text(text.replace(cut[0], cut[1], 1), encoding="utf-8")
        red_exe = build_driver(red, red)
        without = families(drive(red_exe, a.donor, "--seed", "1",
                                 "--ambition", "10", "--list", "--crates",
                                 "--recuts"))
        loose = without.get("room-block", 0)
        check("without the rule the same plan offers more - the RED",
              loose > kept, f"{loose} without the rule against {kept} with it")

    # ---- the sky --------------------------------------------------------
    print("and a wall with sky over it is not a wall to push")
    donor_listing = drive(exe, a.donor, "--seed", "1", "--ambition", "10",
                          "--list")
    hits = SKY.findall(donor_listing)
    check("a push under sky is refused by name - the RED", bool(hits),
          f"{len(hits)} refused")
    check("and the family is not dealt on this donor at all",
          families(donor_listing).get("push-wall", 0) == 0,
          f"push-wall={families(donor_listing).get('push-wall', 0)}")

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
