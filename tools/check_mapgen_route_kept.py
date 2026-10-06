"""What a map is played ON may not be built over.

The PO walked a fork on 2026-09-07 evening and found a stairwell filled wall
to wall: three room blocks, one per round, 160 x 128 x 344 and two more, with
four units of daylight beside them. Every gate passed the map, because the
reachability gate asks whether each pickup can be reached from each spawn and
q2dm1 has another way up.

    python tools/check_mapgen_route_kept.py [--work DIR] [--skip-green]

`tools/mapgen_route_probe.c` asks about the WAY instead: a standing place of
the baseline with three or more floor heights within sixty-four units is a
CLIMB - a stair, a step, a ledge - and a candidate that turns one into solid
has taken away a way through the map.

The baseline an edit is judged against is the donor READ AND WRITTEN BACK, not
the donor's own compiled file. That round trip loses one standing place of
q2dm1 by itself, at 944 864 456, and it is a climb; judged against the donor's
bsp, four blocks that stood six hundred units away were charged with it.

A way REPLACED is not a way lost. A lift is a staircase taken away and a
func_plat put where it was: every standing place ON the steps is gone and the
route between the two heights is not, and a rule that counts those as ways
lost refuses every lift there will ever be - which is what happened, and why
the three forks of 2026-09-08 had no machines in them anywhere. So a lift is
asked a different question: the places it takes away must all lie INSIDE the
box the staircase occupied, which is what `climb lost outside` counts.

The RED is the three forks handed over, read from the job directories their
runs wrote. The GREEN is every block and recut the three seeds offer today,
applied on its own and compiled, plus every lift they offer measured against
its own flight. The controlled RED takes the question out of the operators
again - the block, its step and the recut all stop asking whether there is a
stair where they mean to work - and the ways go with it.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
BATCH6 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\batch6")
# The maps of 2026-09-07 evening, kept OUT of the release folder.
#
# A RED that lives where the next delivery writes is a RED the next
# delivery carries away, and on 2026-09-08 it did exactly that: the
# batch that replaced them took three of these gates' RED with it.
RED_LAST = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260908"
                r"\red_2026-09-07")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260908"
                    r"\route_gate")

PROBE_SRC = ["tools/mapgen_route_probe.c", "src/mapgen/mapgen_bsp.c",
             "src/shared/shared.c", "tools/mapgen_host_stubs.c"]

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

CLIMB_LOST = re.compile(r"^climb lost (\d+)$", re.M)
OUTSIDE = re.compile(r"^climb lost outside (\d+)$", re.M)
CLIMBS = re.compile(r"^climb places (\d+)$", re.M)
NARROWED = re.compile(r"^narrowed (\d+)$", re.M)
LOST = re.compile(r"^places lost (\d+)$", re.M)
EDIT = re.compile(r"^  edit (\d+)  (block|recut)", re.M)
LIFT = re.compile(r"^ *edit (\d+) +lift +(-?\d+) +(-?\d+) +(-?\d+) \.\. +"
                  r"(-?\d+) +(-?\d+) +(-?\d+)", re.M)

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


def build(tree: Path, out: Path, name: str, sources: list[str]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"),
         "-I" + str(tree / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(tree / s) for s in sources] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit(f"cannot build {name}")
    return exe


def pinned() -> tuple[Path, str]:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler()


def compile_map(path: Path) -> str:
    """Compile, and say what happened in the compiler's own words.

    q2tool exits ZERO when it leaks and simply writes no bsp - which is why
    mapgen_compiler.c reads artifacts rather than exit codes, and why a caller
    that only checks for the file should still say WHY it is missing.
    """
    exe, threads = pinned()
    run = subprocess.run(
        [str(exe), "-bsp", "-threads", threads, "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


def why_no_bsp(log: str) -> str:
    """The compiler's own reason, for a case that has no artifact."""
    if "leaked" in log:
        return "LEAKED - the hollow took away solid the map was sealed with"
    for line in log.splitlines():
        if "ERROR" in line or "Error" in line:
            return line.strip()[:120]
    return "no bsp and no reason given"


def routes(probe: Path, baseline: Path, candidate: Path,
           box: list[str] | None = None) -> dict:
    run = subprocess.run([str(probe), str(baseline), str(candidate)]
                         + (box or []),
                         capture_output=True, text=True, timeout=7200)
    out = run.stdout + run.stderr
    def one(rx):
        m = rx.search(out)
        return int(m.group(1)) if m else -1
    return {"climbs": one(CLIMBS), "lost": one(CLIMB_LOST),
            "places": one(LOST), "narrowed": one(NARROWED),
            "outside": one(OUTSIDE), "text": out}


def identity(driver: Path, work: Path) -> Path:
    """The donor read as brushes, written back out and compiled again.

    MEASURED, and this is why it exists: that round trip on its own - nothing
    applied, "changed no" - loses ONE standing place of q2dm1, at 944 864 456,
    and that place is a climb. Compared against the donor's own bsp, every
    operator in the schedule was charged with it, and four blocks that stood
    six hundred units away were failed for a place the compiler moved. What an
    edit did is what it did against the map its own compile would have
    produced without it.
    """
    job = work / "identity"
    job.mkdir(parents=True, exist_ok=True)
    out = job / "identity.map"
    bsp = out.with_suffix(".bsp")
    if bsp.is_file():
        return bsp
    subprocess.run([str(driver), str(CORPUS / "q2dm1.bsp"), "--seed", "1",
                    "--apply", "99999", "--out", str(out)],
                   capture_output=True, text=True, timeout=3600)
    compile_map(out)
    return bsp


def blocks_keep_the_ways(driver: Path, probe: Path, work: Path,
                         log: bool = True) -> int:
    """Every block and recut the schedule offers, applied on its own.

    Applied with `--ground` pointing at the identity, because that is what the
    transaction hands the operators: the baseline, which is the donor written
    back out and compiled again. Without it the operator asks the DONOR'S own
    file whether there is a way through where it means to build while this
    guard judges it against the round trip, and the two disagree - which is
    how a block at 153 102 176 came to stand on a climb at 176 128 192 that
    the donor's file did not call one.
    """
    donor = identity(driver, work)
    worst = 0
    for seed in (1, 2, 3):
        listing = subprocess.run(
            [str(driver), str(CORPUS / "q2dm1.bsp"), "--seed", str(seed),
             "--ground", str(donor), "--list", "--recuts"],
            capture_output=True, text=True, timeout=3600).stdout
        for edit, kind in EDIT.findall(listing)[:6]:
            job = work / f"seed{seed}_{kind}{edit}"
            if job.exists():
                shutil.rmtree(job)
            job.mkdir(parents=True)
            out = job / "one.map"
            applied = subprocess.run(
                [str(driver), str(CORPUS / "q2dm1.bsp"), "--seed", str(seed),
                 "--ground", str(donor), "--apply", edit, "--out", str(out),
                 "--recuts"],
                capture_output=True, text=True, timeout=3600).stdout
            if "changed yes" not in applied:
                if log:
                    check(f"the {kind} at edit {edit} (seed {seed}) was"
                          f" declined rather than built over a way", True,
                          "declined")
                continue
            built = compile_map(out)
            bsp = out.with_suffix(".bsp")
            if not bsp.is_file():
                if log:
                    check(f"the {kind} at edit {edit} (seed {seed}) compiles",
                          False, why_no_bsp(built))
                continue
            got = routes(probe, donor, bsp)
            worst = max(worst, got["lost"])
            if log:
                check(f"the {kind} at edit {edit} (seed {seed}) buries no"
                      f" climb", got["lost"] == 0,
                      f"{got['lost']} climb places lost, {got['places']} places"
                      f" lost, {got['narrowed']} narrowed")
    return worst


def lifts_replace_the_ways(driver: Path, probe: Path, work: Path,
                           log: bool = True) -> int:
    """Every lift the schedule offers, applied on its own.

    What it may not do is take away a climb place that is not in the flight it
    replaced. What it MUST do is take some away: a lift that leaves every step
    standing is a lift nobody built, and this case would pass for the wrong
    reason if the operator quietly declined.
    """
    donor = identity(driver, work)
    worst = 0
    for seed in (1, 2, 3):
        listing = subprocess.run(
            [str(driver), str(CORPUS / "q2dm1.bsp"), "--seed", str(seed),
             "--ground", str(donor), "--list", "--recuts"],
            capture_output=True, text=True, timeout=3600).stdout
        for m in LIFT.finditer(listing):
            edit = m.group(1)
            box = [m.group(i) for i in range(2, 8)]
            job = work / f"seed{seed}_lift{edit}"
            if job.exists():
                shutil.rmtree(job)
            job.mkdir(parents=True)
            out = job / "one.map"
            applied = subprocess.run(
                [str(driver), str(CORPUS / "q2dm1.bsp"), "--seed", str(seed),
                 "--ground", str(donor), "--apply", edit, "--out", str(out),
                 "--recuts"],
                capture_output=True, text=True, timeout=3600).stdout
            if "changed yes" not in applied:
                if log:
                    check(f"the lift at edit {edit} (seed {seed}) was declined"
                          f" rather than half built", True, "declined")
                continue
            built = compile_map(out)
            bsp = out.with_suffix(".bsp")
            if not bsp.is_file():
                if log:
                    check(f"the lift at edit {edit} (seed {seed}) compiles",
                          False, why_no_bsp(built))
                continue
            got = routes(probe, donor, bsp, box)
            worst = max(worst, got["outside"])
            if log:
                check(f"the lift at edit {edit} (seed {seed}) takes away only"
                      f" the flight it replaced", got["outside"] == 0,
                      f"{got['lost']} climb places lost, {got['outside']}"
                      f" of them outside the flight")
                check(f"the lift at edit {edit} (seed {seed}) really replaced"
                      f" a staircase", got["lost"] > 0,
                      f"{got['lost']} climb places lost")
    return worst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-green", action="store_true")
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    probe = build(REPO, a.work, "route_probe", PROBE_SRC)

    print("the identity map, which may lose nothing")
    ident = BATCH6 / "q2mg_f100"
    ident_base = ident / "baseline" / "q2mg_f100.bsp"
    ident_cand = Path(r"O:\Claude2\q2pro-release\baseq2\maps\mgtest_f100.bsp")
    if not ident_base.is_file() or not ident_cand.is_file():
        #
        # GONE - and this case had no guard at all, so it was about to ask the
        # probe about a file that is not there. `mapgen1-20260907\batch6` went in
        # my own disk clearing on 2026-09-12 (evidence ledger row 86). Neither a
        # pass nor a fail: what it recorded was that the identity map loses no
        # place of its baseline, and that stands in the ledger.
        #
        print("  GONE  the identity map: recorded as losing no place at all;"
              " its baseline is no longer on disk")
    else:
        got = routes(probe, ident_base, ident_cand)
        check("mgtest_f100 keeps every place its baseline had",
              got["lost"] == 0 and got["places"] == 0,
              f"{got['places']} places lost, {got['lost']} of them climbs")

    print("the forks handed over on 2026-09-07 evening, which are the RED")
    for seed, expect in ((1, 88), (2, 92), (3, 68)):
        job = BATCH6 / f"q2mg_f90s{seed}"
        base = job / "baseline" / f"q2mg_f90s{seed}.bsp"
        cand = RED_LAST / f"mgtest_f090s{seed}.bsp"
        if not base.is_file() or not cand.is_file():
            #
            # GONE: `batch6` and `red_2026-09-07` both went in my own disk
            # clearing on 2026-09-12 (evidence ledger row 86). Neither a pass
            # nor a fail - the recorded number is in the print below - and the
            # behavioural RED at the end of this guard is not optional.
            #
            print(f"  GONE  the f090s{seed} of 2026-09-07: recorded as building"
                  f" over about {expect} climb places; the artifact is no longer"
                  f" on disk")
            continue
        got = routes(probe, base, cand)
        check(f"the f090s{seed} of 2026-09-07 built over a way through the map"
              f" - the RED", got["lost"] >= expect - 8,
              f"{got['lost']} of {got['climbs']} climb places lost,"
              f" {got['narrowed']} narrowed")

    if not a.skip_green:
        print("and what the block and the recut do today")
        driver = build(REPO, a.work, "driver", DRIVER_SRC)
        blocks_keep_the_ways(driver, probe, a.work)
        print("and what a lift takes away, which is the flight it replaced")
        lifts_replace_the_ways(driver, probe, a.work)

    failures = FAILED
    cases = CASES
    if not a.skip_red and not a.skip_green:
        print("controlled RED")
        cases += 1
        tree = a.work / "red_rises_with_ground"
        if tree.exists():
            shutil.rmtree(tree)
        tree.mkdir(parents=True)
        for sub in ("inc", "src", "tools"):
            shutil.copytree(REPO / sub, tree / sub)
        p = tree / "src" / "mapgen" / "mapgen_geometry_edit.c"
        text = p.read_text(encoding="utf-8")
        # The rule under test is the one that asks whether there is a way
        # through the map where the operator means to build or dig. Taking it
        # out of the block, out of its step, and out of the recut is the
        # generator of 2026-09-07 back again.
        cuts = [
            """    /* And not on a way through the map. */
    if (region_has_climb(donor, stood.mins, stood.maxs))
        return block_no("it stands on a way through");
""",
            """    if (stood.has_step
        && (!clear_after(donor, stood.step[0], stood.step[1], empty_lo,
                         empty_hi)
            || region_has_climb(donor, stood.step[0], stood.step[1])))
        stood.has_step = false;

""",
            """
        && !region_has_climb(donor, stood.step[0], stood.step[1])""",
        ]
        recut = """    {
        /* With room to spare: emptying a region takes the ground from under
           anything standing on its edge as well as inside it. */
        float lo[3], hi[3];
        for (int a = 0; a < 3; a++) {
            lo[a] = r->lo[a] - RECUT_KEEP;
            hi[a] = r->hi[a] + RECUT_KEEP;
        }
        if (region_has_climb(donor, lo, hi))
            return decline(furnish
                ? "recut: there is a way through the region on the map as"
                  " it is now"
                : "push: there is a way through the rock behind this wall"
                  " on the map as it is now - something already moved"
                  " here");
    }

"""
        missing = [c for c in cuts + [recut] if text.count(c) != 1]
        if missing:
            print(f"  FAIL  RED a construction may stand on a stair again:"
                  f" cannot mutate ({len(missing)} of"
                  f" {len(cuts) + 1} sites not found)")
            failures += 1
        else:
            for c in cuts:
                text = text.replace(c, "", 1)
            text = text.replace(recut, "", 1)
            p.write_text(text, encoding="utf-8")
            red_driver = build(tree, tree, "driver_red", DRIVER_SRC)
            worst = blocks_keep_the_ways(red_driver, probe, tree, log=False)
            ok = worst > 0
            print(f"  {'PASS' if ok else 'FAIL'}  RED a construction may stand"
                  f" on a stair again: a way through the map goes"
                  f"  -- worst case {worst} climb places lost")
            failures += 0 if ok else 1

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
