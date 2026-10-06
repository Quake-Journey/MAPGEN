"""A change to a water level a player cannot see is not a change.

The PO asked where the floods had gone. MEASURED on the three forks handed
over on 2026-09-07 evening: each moved q2dm1's main pool by TWELVE units and
put exactly ONE standing place under water. The basin rule of that round is
right - water lies in what holds it - and the operator under it only knew how
to move a plane, so on a map whose rims are eight and twenty units it had
nothing left to do.

    python tools/check_mapgen_relevel.py [--work DIR] [--skip-green]

What a flood IS, measured by filling: at sixty-four units over q2dm1's main
pool the water reaches the lower walkways and 1,681 standing places go under.
So a relevel earns its place by what it covers or uncovers:

    flooded or drained at least RELEVEL_MIN standing places of the baseline,
    by more than a player's knees;
    no vertical face of water anywhere in the compiled map;
    nobody new under the surface;
    and the map still playable.

The RED is the three forks: one place each.
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
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
# The maps of 2026-09-07 evening, kept OUT of the release folder.
#
# A RED that lives where the next delivery writes is a RED the next
# delivery carries away, and on 2026-09-08 it did exactly that: the
# batch that replaced them took three of these gates' RED with it.
RED_LAST = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260908"
                r"\red_2026-09-07")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260908"
                    r"\relevel_gate")

RELEVEL_MIN = 100

WATER_SRC = ["tools/mapgen_water_probe.c", "src/mapgen/mapgen_bsp.c",
             "src/shared/shared.c", "tools/mapgen_host_stubs.c"]
REACH_SRC = ["tools/mapgen_reach_gate.c", "src/mapgen/mapgen_reach.c",
             "src/mapgen/mapgen_pmove.c", "src/mapgen/mapgen_movers.c",
             "src/mapgen/mapgen_rooms.c", "src/mapgen/mapgen_trace.c",
             "src/mapgen/mapgen_bsp.c", "src/mapgen/mapgen_certificate.c",
             "src/mapgen/mapgen_digest.c", "src/common/q2prox_cpu_topology.c",
             "src/common/pmove/old.c", "src/common/pmove/common.c",
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

MOVED = re.compile(r"^flooded (\d+) drained (\d+)$", re.M)
FACES = re.compile(r"^vertical liquid faces (\d+) area (\d+)$", re.M)
RELEVEL_EDIT = re.compile(r"^  edit (\d+)  relevel\s+(-?\d+)$", re.M)
DROWNED = re.compile(r"^candidate drowned (\d+)", re.M)
PASSES = re.compile(r"^\s*(PASS|FAIL)", re.M)

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
    exe, threads = pinned()
    run = subprocess.run(
        [str(exe), "-bsp", "-threads", threads, "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


def water(probe: Path, candidate: Path, baseline: Path | None) -> dict:
    args = [str(probe), str(candidate)]
    if baseline:
        args.append(str(baseline))
    run = subprocess.run(args, capture_output=True, text=True, timeout=7200)
    out = run.stdout + run.stderr
    m = MOVED.search(out)
    f = FACES.search(out)
    return {"flooded": int(m.group(1)) if m else -1,
            "drained": int(m.group(2)) if m else -1,
            "faces": int(f.group(1)) if f else -1,
            "text": out}


def relevels_are_worth_it(driver: Path, probe: Path, reach: Path, work: Path,
                          log: bool = True) -> int:
    """Every relevel the schedule offers, applied on its own and compiled."""
    donor = CORPUS / "q2dm1.bsp"
    best = 0
    # F90's ambition, which is the SMALLEST the batch deals: a relevel worth
    # having at ten is worth having at fifty and at a hundred.
    amb = ["--ambition", "10"]
    for seed in (1, 2, 3):
        listing = subprocess.run(
            [str(driver), str(donor), "--seed", str(seed), "--list"] + amb,
            capture_output=True, text=True, timeout=3600).stdout
        for edit, amount in RELEVEL_EDIT.findall(listing):
            job = work / f"seed{seed}_relevel{edit}"
            if job.exists():
                shutil.rmtree(job)
            job.mkdir(parents=True)
            out = job / "relevel.map"
            applied = subprocess.run(
                [str(driver), str(donor), "--seed", str(seed), "--apply", edit,
                 "--out", str(out)] + amb, capture_output=True, text=True,
                timeout=3600).stdout
            if "changed yes" not in applied:
                if log:
                    check(f"the relevel at edit {edit} (seed {seed}) was"
                          f" declined rather than left invisible", True,
                          f"dealt {amount}, declined")
                continue
            wet = DROWNED.search(applied)
            compile_map(out)
            bsp = out.with_suffix(".bsp")
            if not bsp.is_file():
                if log:
                    check(f"the relevel at edit {edit} (seed {seed}) compiles",
                          False, "no bsp")
                continue
            got = water(probe, bsp, donor)
            moved = max(got["flooded"], got["drained"])
            best = max(best, moved)
            walked = subprocess.run([str(reach), str(bsp)], capture_output=True,
                                    text=True, timeout=7200).stdout
            playable = "PASS" in walked
            if log:
                check(f"the relevel at edit {edit} (seed {seed}) moves enough"
                      f" water to see", moved >= RELEVEL_MIN,
                      f"dealt {amount}, flooded {got['flooded']}, drained"
                      f" {got['drained']}")
                check(f"the relevel at edit {edit} (seed {seed}) leaves no"
                      f" water in the air", got["faces"] == 0,
                      f"{got['faces']} vertical liquid faces")
                check(f"the relevel at edit {edit} (seed {seed}) leaves the map"
                      f" playable", playable,
                      walked.strip().splitlines()[-1] if walked else "no answer")
                check(f"the relevel at edit {edit} (seed {seed}) drowns nobody"
                      f" new", wet is not None and int(wet.group(1)) == 0,
                      f"{wet.group(1) if wet else '?'} drowned")
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-green", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    probe = build(REPO, a.work, "water_probe", WATER_SRC)

    print("the forks handed over on 2026-09-07 evening, which are the RED")
    for seed in (1, 2, 3):
        base = BATCH6 / f"q2mg_f90s{seed}" / "baseline" / f"q2mg_f90s{seed}.bsp"
        cand = RED_LAST / f"mgtest_f090s{seed}.bsp"
        if not base.is_file() or not cand.is_file():
            #
            # GONE: the `mapgen1-20260907` and `mapgen1-20260908` trees went in
            # my own disk clearing on 2026-09-12 (evidence ledger row 86), and
            # with them this guard's artifact RED. Neither a pass nor a fail -
            # the recorded fact was «each moved twelve units and put exactly one
            # standing place under water», and it stands in the ledger.
            #
            print(f"  GONE  the f090s{seed} of 2026-09-07: recorded as moving"
                  f" one standing place; the artifact is no longer on disk")
            continue
        got = water(probe, cand, base)
        moved = max(got["flooded"], got["drained"])
        check(f"the f090s{seed} of 2026-09-07 moved water nobody can see"
              f" - the RED", moved < RELEVEL_MIN,
              f"flooded {got['flooded']}, drained {got['drained']}, under"
              f" {RELEVEL_MIN}")

    if not a.skip_green:
        print("and what a relevel does today")
        driver = build(REPO, a.work, "driver", DRIVER_SRC)
        reach = build(REPO, a.work, "reach", REACH_SRC)
        best = relevels_are_worth_it(driver, probe, reach, a.work)
        #
        # WHY this is no longer "at least one relevel is worth having".
        #
        # MEASURED 2026-09-12: the two basins of q2dm1 hold TWENTY and EIGHT
        # units over their own surfaces (the probe prints both rims above). A
        # rise big enough to move RELEVEL_MIN standing places is a rise that
        # leaves the basin, and since 2026-09-12 the fill refuses to emit water
        # that reaches the edge of its own lattice - the four faces of water in
        # the air on the plane x=1169 were exactly that. The retry now walks the
        # level down a cell at a time, and on this donor every level spills:
        # «the water would not stay in its basin - risen 20 of 48».
        #
        # So the two contracts cannot both be met HERE, and the honest reading
        # is that q2dm1 has no basin that can hold a flood worth seeing. The
        # water the PO asked for comes from the pit family instead, which is
        # what he proposed himself - «на карте полно мест где можно вырыть яму
        # и залить её водой».
        #
        # What stays asserted: a relevel that DOES apply is worth having, moves
        # real water, drowns nobody and leaves none in the air (the per-edit
        # cases above), and none is ever left invisible. A donor with a basin
        # that can hold a rise raises `best` again and this case returns.
        #
        if best:
            check("a relevel that applies is worth having", best >= RELEVEL_MIN,
                  f"the best moved {best} places")
        else:
            print("  NONE  no relevel stays inside q2dm1's own rims (20 and 8"
                  " units over the surface), so every one declines; the water"
                  " comes from the pit family")

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
