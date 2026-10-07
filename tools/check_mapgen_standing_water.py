"""Water lies in a basin, or it is not water.

The PO looked at a fork of q2dm1 on 2026-09-07 and said the water could not
lie like that, as if it were part of the architecture - it would run off at
once. The flood had raised the lower pool a hundred and ninety-five units,
three floods over three rounds, out of a basin whose lowest rim is eight.

    python tools/check_mapgen_standing_water.py [--work DIR] [--skip-red]

The contract is measured on the compiled artifact by
`tools/mapgen_water_probe.c`: a face with liquid on one side and open air on
the other, within thirty degrees of vertical. The compiler draws no face
between water and solid, so a pool in a basin has none of them, and q2dm1 has
none. A vertical face of water is water meeting air.

The RED is the three maps that were handed to the PO, read from the job
directories their runs wrote rather than from the maps folder - which every
delivery replaces, and a RED the next batch can overwrite proves nothing.

The GREEN is today's operator on the same donor: every flood the schedule
offers at seeds 1, 2 and 3, applied on its own, compiled, and measured. And a
controlled RED lets the water stop at the edge of its own lattice, which puts
it back in the air.
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
from mapgen_load_guard import game_dir  # noqa: E402  (brief 13 W1: the game folder of this run)
GAME = Path(game_dir())
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
BATCH5 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\batch5")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907"
                    r"\water_gate")

PROBE_SRC = ["tools/mapgen_water_probe.c", "src/mapgen/mapgen_bsp.c",
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

EXPOSED = re.compile(r"^vertical liquid faces (\d+) area (\d+)$", re.M)
POOL = re.compile(r"^pool .* surface (-?\d+)\s+depth (\d+)\s+rim (\d+)$", re.M)
FLOOD_EDIT = re.compile(r"^  edit (\d+)  relevel\s+(-?\d+)$", re.M)

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


def exposed_faces(probe: Path, bsp: Path) -> tuple[int, int, str]:
    run = subprocess.run([str(probe), str(bsp)], capture_output=True,
                         text=True, timeout=3600)
    out = run.stdout + run.stderr
    m = EXPOSED.search(out)
    return (int(m.group(1)), int(m.group(2)), out) if m else (-1, -1, out)


def floods_are_contained(driver: Path, probe: Path, work: Path,
                         log: bool = True) -> int:
    """Every flood the schedule offers, applied on its own and compiled."""
    donor = CORPUS / "q2dm1.bsp"
    worst = 0
    for seed in (1, 2, 3):
        listing = subprocess.run(
            [str(driver), str(donor), "--seed", str(seed), "--list"],
            capture_output=True, text=True, timeout=3600).stdout
        for edit, amount in FLOOD_EDIT.findall(listing):
            job = work / f"seed{seed}_flood{edit}"
            if job.exists():
                shutil.rmtree(job)
            job.mkdir(parents=True)
            out = job / "flood.map"
            applied = subprocess.run(
                [str(driver), str(donor), "--seed", str(seed),
                 "--apply", edit, "--out", str(out)],
                capture_output=True, text=True, timeout=3600).stdout
            if "changed yes" not in applied:
                if log:
                    check(f"the flood at edit {edit} (seed {seed}) was"
                          f" declined rather than left standing", True,
                          f"dealt {amount}, declined")
                continue
            compile_map(out)
            bsp = out.with_suffix(".bsp")
            if not bsp.is_file():
                if log:
                    check(f"the flood at edit {edit} (seed {seed}) compiles",
                          False, "no bsp")
                continue
            faces, area, _ = exposed_faces(probe, bsp)
            worst = max(worst, faces)
            if log:
                check(f"the flood at edit {edit} (seed {seed}) leaves no water"
                      f" standing in the air", faces == 0,
                      f"dealt {amount}, {faces} vertical liquid faces,"
                      f" area {area}")
    return worst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    ap.add_argument("--skip-green", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    probe = build(REPO, a.work, "water_probe", PROBE_SRC)

    print("the donor, and what its basins allow")
    faces, area, text = exposed_faces(probe, CORPUS / "q2dm1.bsp")
    check("q2dm1 keeps all of its water in its basins", faces == 0,
          f"{faces} vertical liquid faces")
    for surface, depth, rim in POOL.findall(text):
        print(f"        pool surface {surface}, depth {depth}, rim {rim}")

    print("the maps that were handed over, which are the RED")
    for name, run, art, expect in (
            ("the f090s1 of 2026-09-07", "q2mg_f90s1b", "try_0432", 23),
            ("the f090s2 of 2026-09-07", "q2mg_f90s2", "try_0294", 4),
            ("the f090s3 of 2026-09-07", "q2mg_f90s3", "try_0281", 11)):
        stem = run[:-1] if run.endswith("b") else run
        bsp = BATCH5 / run / art / f"{stem}.bsp"
        if not bsp.is_file():
            #
            # GONE, and saying so is not the same as passing.
            #
            # The batch5 job directories were deleted on 2026-09-12 clearing
            # disk space, and with them the three maps this RED was read off.
            # A guard that FAILS because its own evidence was deleted reports a
            # defect that is not there, and one that silently PASSES reports a
            # proof it no longer has. So it is neither: the recorded count
            # stands in the ledger (memory/project_mapgen1_evidence_ledger.md)
            # and the behavioural RED below - the water rising as a plane - is
            # what keeps this contract honest. That RED is not optional.
            #
            print(f"  GONE  {name}: recorded at {expect} vertical liquid"
                  f" faces; the artifact is no longer on disk")
            continue
        faces, area, _ = exposed_faces(probe, bsp)
        check(f"{name} stands water in the air - the RED", faces == expect,
              f"{faces} vertical liquid faces, area {area}")

    if not a.skip_green:
        print("and what the flood does today")
        driver = build(REPO, a.work, "driver", DRIVER_SRC)
        floods_are_contained(driver, probe, a.work)

    failures = FAILED
    cases = CASES
    if not a.skip_red and not a.skip_green:
        print("controlled RED")
        cases += 1
        tree = a.work / "red_no_rim"
        if tree.exists():
            shutil.rmtree(tree)
        tree.mkdir(parents=True)
        for sub in ("inc", "src", "tools"):
            shutil.copytree(REPO / sub, tree / sub)
        p = tree / "src" / "mapgen" / "mapgen_geometry_edit.c"
        text = p.read_text(encoding="utf-8")
        #
        # WHAT the RED mutates, and why it moved.
        #
        # It used to displace the pool's top plane instead of emitting the
        # fill's boxes. That mutation is now DOWNSTREAM of the refusal the fill
        # itself makes: with the spill rule of 2026-09-12 the fill returns no
        # boxes at all, the operator declines, and the mutated emit never runs -
        # the RED reported «worst case 0 vertical liquid faces» and proved
        # nothing. A RED has to aim at the rule that holds the contract, so it
        # now removes that rule: the water is allowed to stop at the edge of its
        # own lattice, which is exactly what stood four faces of water in the
        # air on the plane x=1169 (evidence ledger row 77).
        #
        old = """            if (x == lo_x || x == hi_x - 1 || y == lo_y || y == hi_y - 1) {
                if (out_spilled)
                    *out_spilled = true;
                free(wet);
                free(queue);
                return 0;
            }"""
        new = """            /* RED: the clamp is a wall again - the water may stop
               in mid-air at the edge of its own lattice. */
            (void)out_spilled;"""
        if text.count(old) != 1:
            print("  FAIL  RED the clamp is a wall again: cannot mutate")
            failures += 1
        else:
            text = text.replace(old, new, 1)
            p.write_text(text, encoding="utf-8")
            red_driver = build(tree, tree, "driver_red", DRIVER_SRC)
            worst = floods_are_contained(red_driver, probe, tree, log=False)
            ok = worst > 0
            print(f"  {'PASS' if ok else 'FAIL'}  RED the clamp is a wall"
                  f" again: the water stands in the air"
                  f"  -- worst case {worst} vertical liquid faces")
            failures += 0 if ok else 1

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
