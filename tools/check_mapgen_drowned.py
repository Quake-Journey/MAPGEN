"""Nobody spawns in the water, and nothing a player needs is under it.

The flood raises a pool and used to move nothing. On q2dm1 at fidelity 90 that
left one deathmatch start, the railgun, its slugs, two large healths and four
armour shards under the new surface - and every gate passed, because the
compiler does not care, the see-through oracle does not care, and the
reachability explorer SWIMS: it reported all eighty-three pickups reachable.
The PO spawned in the water and said so.

    python tools/check_mapgen_drowned.py [--work DIR] [--skip-red]

The RED is the two maps that were handed over. The GREEN is the same operator
on the same donor today: it raises the pool as far as it can, carries what the
new surface would cover to the nearest dry ledge, and if it cannot carry
something it does not rise.

Nothing here compiles anything: the question is about geometry, and the
transaction asks it before it spends a compile.
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
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
BATCH = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\batch")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907"
                    r"\drowned_gate")

DRIVER_SRC = [
    "tools/mapgen_recut_driver.c", "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_geometry.c", "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_rooms.c", "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_bsp.c", "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_movers.c", "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_reach.c", "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_certificate.c", "src/mapgen/mapgen_digest.c",
    "src/common/q2prox_cpu_topology.c", "src/common/pmove/old.c",
    "src/common/pmove/common.c", "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

CASES = 0
FAILED = 0

DROWNED = re.compile(r"^drowned (\d+)(?:: (.*))?$", re.M)
CANDIDATE = re.compile(r"^candidate drowned (\d+)(?:: (.*))?$", re.M)
FLOODS = re.compile(r"edit (\d+)\s+relevel")


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def build(tree: Path, out: Path, name: str) -> Path:
    exe = out / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"),
         "-I" + str(tree / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(tree / s) for s in DRIVER_SRC] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit(f"cannot build {name}")
    return exe


def drive(exe: Path, target: Path, *args: str) -> str:
    run = subprocess.run([str(exe), str(target), *args],
                         capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


def wet_in(exe: Path, target: Path) -> tuple[int, str]:
    m = DROWNED.search(drive(exe, target))
    return (int(m.group(1)), m.group(2) or "") if m else (-1, "unreadable")


# Two donors, because one of them cannot flood at all.
#
# q2dm1's basins hold eight and twenty units above their surfaces, so since the
# basin cap of 2026-09-07 evening the only level change it offers is a fall -
# and a pool that FALLS strands nobody, so a mutation that breaks the carry is
# invisible on this map. q2dm2 has seven pools, one of them with a rim of
# forty, and it rises; that is where the carry is exercised. (q2dm3's liquid is
# slime and lava, which the flood does not touch.)
DONORS = ("q2dm1.bsp", "q2dm2.bsp")


def floods_stay_dry(exe: Path, log: bool = True) -> int:
    """Every flood the schedule offers, applied on its own.

    Held to the DONOR's own count and not to zero, which is the same rule the
    transaction applies: q2dm2's designer left five boxes of bullets in a pool
    and a fork of q2dm2 may keep them there. What no edit may do is put
    something in the water that was dry. Returns the worst EXCESS.
    """
    worst = 0
    for name in DONORS:
        donor = CORPUS / name
        if not donor.is_file():
            continue
        floor, _ = wet_in(exe, donor)
        for seed in (1, 2, 3):
            listing = drive(exe, donor, "--seed", str(seed), "--list")
            for which in FLOODS.findall(listing):
                out = drive(exe, donor, "--seed", str(seed), "--apply", which)
                m = CANDIDATE.search(out)
                wet = int(m.group(1)) if m else -1
                applied = "changed yes" in out
                excess = wet - floor
                worst = max(worst, excess)
                if log:
                    check(f"the flood at edit {which} (seed {seed},"
                          f" {name[:-4]}) puts nobody new in the water",
                          excess <= 0,
                          f"{'moved' if applied else 'declined'},"
                          f" {wet} drowned against the donor's {floor}"
                          + (f": {m.group(2)}" if m and m.group(2) else ""))
    return worst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    exe = build(REPO, a.work, "driver")

    print("the donors, and the maps that were handed over")
    # What each donor itself keeps in the water is the floor an edit is held
    # to, not a failure: q2dm1 has nobody in its pools and q2dm2 has five
    # boxes of bullets in one of them, and both are maps this may fork.
    for name in DONORS:
        wet, who = wet_in(exe, CORPUS / name)
        check(f"{name[:-4]} can be read, and what it keeps in the water is"
              f" the floor", wet >= 0, f"{wet} drowned{': ' + who if wet else ''}")
    # The ARTIFACTS of 2026-09-07, not the installed files: the maps directory
    # is replaced by every delivery, and a RED the next batch can overwrite
    # stops proving anything the moment it starts passing.
    for name, expect, bsp in (
            ("the f090s1 of 2026-09-07", 0,
             BATCH / "q2mg_f90s1" / "try_0042" / "q2mg_f90s1.bsp"),
            ("the f090s2 of 2026-09-07", 9,
             BATCH / "q2mg_f90s2" / "try_0115" / "q2mg_f90s2.bsp"),
            ("the f090s3 of 2026-09-07", 9,
             BATCH / "q2mg_f90s3b" / "try_0112" / "q2mg_f90s3.bsp")):
        if not bsp.is_file():
            #
            # GONE, which is neither a pass nor a fail.
            #
            # The whole `mapgen1-20260907` tree went in my own disk clearing on
            # 2026-09-12 (evidence ledger row 86), and with it this guard's
            # artifact RED. Failing here would report a defect that is not
            # there; passing would claim a proof that no longer exists. The
            # recorded number stands in the ledger, and what keeps the contract
            # honest is the behavioural RED below - which is not optional.
            #
            print(f"  GONE  {name}: recorded at {expect} drowned; the artifact"
                  f" is no longer on disk")
            continue
        wet, who = wet_in(exe, bsp)
        if expect:
            check(f"{name} as delivered drowns {expect} - the RED this guard"
                  f" was written for", wet == expect, f"{wet} drowned: {who}")
        else:
            check(f"{name} as delivered drowns nobody", wet == 0,
                  f"{wet} drowned")

    print("and what the flood does today")
    floods_stay_dry(exe)

    failures = FAILED
    cases = CASES
    if not a.skip_red:
        """Two mutations, because one of them alone proves nothing now.

        The basin cap of 2026-09-07 evening means q2dm1 offers only a FALL and
        q2dm2 only a forty-unit rise, and neither strands anything - so
        removing the carry on its own changes no number on this corpus, which
        is a guard that has stopped testing what it claims to. The pair
        separates the two rules: (a) take the basin away and the water rises
        as far as it was dealt, and the carry still moves everything it
        covers, so nobody new is in it; (b) take the carry away too and they
        stay under the surface. (b) minus (a) IS the carry.

        Both now begin by removing the spill check of 2026-09-12 as well,
        because the fill refuses before either mutation is reached: see the
        comment in `mutate`.
        """
        print("controlled RED")

        def mutate(name: str, no_carry: bool, lying_carry: bool) -> int:
            tree = a.work / name
            if tree.exists():
                shutil.rmtree(tree)
            tree.mkdir(parents=True)
            for sub in ("inc", "src", "tools"):
                shutil.copytree(REPO / sub, tree / sub)
            p = tree / "src" / "mapgen" / "mapgen_geometry_edit.c"
            text = p.read_text(encoding="utf-8")
            #
            # FIRST, and for BOTH mutations: let the water out of its basin.
            #
            # Since the spill rule of 2026-09-12 the fill refuses any level
            # whose water reaches the edge of its own lattice, so no flood on
            # either donor emits a box - every q2dm2 edit now prints «declined,
            # 5 drowned against the donor's 5» - and a mutation of the CARRY
            # never executes. Both REDs below duly reported «0 more drowned than
            # the donor had»: a RED aiming at unreachable code. Removing the
            # spill check puts the water back over the floor and the carry back
            # in play, so the two mutations mean again what they say.
            #
            spill = """            if (x == lo_x || x == hi_x - 1 || y == lo_y || y == hi_y - 1) {
                if (out_spilled)
                    *out_spilled = true;
                free(wet);
                free(queue);
                return 0;
            }"""
            if text.count(spill) != 1:
                return -1
            text = text.replace(spill, "            (void)out_spilled;", 1)
            if no_carry:
                # The water rises and whatever it covers stays where it was,
                # which is what the PO spawned into.
                was = """            const bool is_player = !strncmp(cls, "info_player", 11);
            if (dry_ground_near(ground, g, boxes, num_boxes, ent->origin,
                                level, is_player, moved[moves])) {"""
                now = """            const bool is_player = !strncmp(cls, "info_player", 11);
            (void)is_player;
            continue;
            if (false) {"""
                if text.count(was) != 1:
                    return -1
                text = text.replace(was, now, 1)
            if lying_carry:
                # The carry runs and calls the spot the thing is already
                # standing in dry. A carry is only worth anything if what it
                # picks is ABOVE the water.
                was = """                who[moves] = e;
                moves++;
                continue;"""
                now = """                moved[moves][0] = ent->origin[0];
                moved[moves][1] = ent->origin[1];
                moved[moves][2] = ent->origin[2];
                who[moves] = e;
                moves++;
                continue;"""
                if text.count(was) != 1:
                    return -1
                text = text.replace(was, now, 1)
            p.write_text(text, encoding="utf-8")
            return floods_stay_dry(build(tree, tree, "driver_" + name),
                                   log=False)

        cases += 2
        adrift = mutate("red_no_carry", True, False)
        ok = adrift > 0
        print(f"  {'PASS' if ok else 'FAIL'}  RED the water rises and carries"
              f" nothing: somebody is under it"
              f"  -- {adrift} more drowned than the donor had")
        failures += 0 if ok else 1

        lying = mutate("red_lying_carry", False, True)
        ok = lying > 0
        print(f"  {'PASS' if ok else 'FAIL'}  RED the carry calls where they"
              f" already stand dry: somebody is under it"
              f"  -- {lying} more drowned than the donor had")
        failures += 0 if ok else 1

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
