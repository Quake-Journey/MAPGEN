"""A construction has to give the player something, or it is a pillar.

The PO walked three forks on 2026-09-08 and refused them all. What he saw was
square columns two hundred and forty units tall standing in the middles of
rooms - four of them the same in every seed, one in the courtyard rising above
the parapet into the sky, two side by side in one room - and he asked what such
artistry was for. Every gate in the tree passed those maps. Not one of them was
measuring what he was looking at: they ask whether an edit BROKE something, and
a column breaks nothing.

    python tools/check_mapgen_construction_worth.py [--work DIR] [--seeds N]
                                                    [--skip-red]

So this asks what an edit was WORTH, with the reach explorer's own answer - the
places a player can get to and get back from, in the spawns' own component:

    every block and recut the schedule offers, applied on its own, compiled,
    and explored. It has to leave MORE of them than the baseline had, and at
    least one of the new ones has to be ON the thing that was built.

MEASURED on the batch the PO refused: `mgtest_f095s2` shipped nine
constructions and 6157 standing places against its baseline's 6166 - NINE
FEWER. A plinth's top is two hundred and forty units up, nobody gets onto it,
and it takes away the floor it stands on.

The controlled RED withdraws the two rules that make a form climbable - the
cap on how far a top may be above the step under it, and the headroom over it -
and deals the plinth back into the form table. The blocks that come out are the
ones in the photographs, and the worth gate has to refuse them.
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260908"
                    r"\worth_gate")

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

WORTH_SRC = [
    "tools/mapgen_construction_worth.c", "src/mapgen/mapgen_reach.c",
    "src/mapgen/mapgen_digest.c",
    "src/mapgen/mapgen_pmove.c", "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c", "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_bsp.c",
    "src/common/q2prox_cpu_topology.c", "src/common/pmove/old.c",
    "src/common/pmove/common.c", "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

EDIT = re.compile(r"^  edit (\d+)  (block|recut)"
                  r" +(-?\d+) +(-?\d+) +(-?\d+) \.\. +(-?\d+) +(-?\d+) +(-?\d+)",
                  re.M)
COMPONENT = re.compile(r"^component (\d+)$", re.M)
ON_IT = re.compile(r"^on the construction (\d+)$", re.M)

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


def compile_map(path: Path) -> None:
    exe, threads = pinned()
    subprocess.run(
        [str(exe), "-bsp", "-threads", threads, "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)


def identity(driver: Path, work: Path) -> Path:
    """The donor read as brushes, written back and compiled, with nothing
    applied - the map a candidate's own compile would have produced."""
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


def worth(probe: Path, bsp: Path, box: list[str]) -> dict:
    run = subprocess.run([str(probe), str(bsp)] + box,
                         capture_output=True, text=True, timeout=7200)
    out = run.stdout + run.stderr
    def one(rx):
        m = rx.search(out)
        return int(m.group(1)) if m else -1
    return {"component": one(COMPONENT), "on_it": one(ON_IT), "text": out}


def constructions_are_worth_it(driver: Path, probe: Path, work: Path,
                               seeds: int, log: bool = True) -> tuple[int, int]:
    """Returns (built, worthless): how many constructions stood, and how many
    of them nobody could use."""
    donor = identity(driver, work)
    base = worth(probe, donor, ["0", "0", "0", "0", "0", "0"])["component"]
    if log:
        print(f"the baseline's own component: {base} places")
    built = worthless = 0
    for seed in range(1, seeds + 1):
        # With the baseline as the ground, which is what the transaction hands
        # the operators - see check_mapgen_route_kept.py.
        listing = subprocess.run(
            [str(driver), str(CORPUS / "q2dm1.bsp"), "--seed", str(seed),
             "--ground", str(donor), "--list", "--recuts"],
            capture_output=True, text=True, timeout=3600).stdout
        for m in EDIT.finditer(listing):
            edit, kind = m.group(1), m.group(2)
            box = [m.group(i) for i in range(3, 9)]
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
                continue
            compile_map(out)
            bsp = out.with_suffix(".bsp")
            if not bsp.is_file():
                if log:
                    check(f"the {kind} at edit {edit} (seed {seed}) compiles",
                          False, "no bsp")
                continue
            built += 1
            got = worth(probe, bsp, box)
            bad = got["on_it"] < 1 or got["component"] <= base
            if bad:
                worthless += 1
                if log:
                    print(f"  note  the {kind} at edit {edit} (seed {seed}) is"
                          f" not worth building"
                          f"  -- {got['component']} places against {base},"
                          f" {got['on_it']} of them on it")
            elif log:
                check(f"the {kind} at edit {edit} (seed {seed}) is worth"
                      f" building", True,
                      f"{got['component']} places against {base},"
                      f" {got['on_it']} of them on it")
    return built, worthless


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    driver = build(REPO, a.work, "driver", DRIVER_SRC)
    probe = build(REPO, a.work, "worth", WORTH_SRC)

    print("every construction the schedule offers, applied on its own")
    built, worthless = constructions_are_worth_it(driver, probe, a.work,
                                                  a.seeds)
    check("the schedule offers constructions at all", built > 0,
          f"{built} built")
    #
    # And how many of them the worth gate refuses - bounded, not forbidden, and
    # the reason is measured.
    #
    # The planner proves a construction with geometry: one floor under it, a
    # player's width beside every face that meets air, no climb buried, and
    # since 2026-09-10 `block_keeps_the_way` - the standing places around it
    # with and without it, a piece more than before being a passage closed. What
    # it cannot do is run the REACHABILITY WALK, which is what the worth gate
    # uses and which has rules of its own about what a player can climb and drop.
    #
    # MEASURED on q2dm1 seed 1, the one construction that gets this far: the
    # block at 225 107 176 .. 368 284 312 takes exactly 20 standing places off
    # the map and puts 20 back on its own top - `MapGenBsp_Places` counts 4432
    # before and 4432 after - and the WALK then reaches 68 fewer, because the
    # thing stands where a route went. No plan-time proxy in this module sees
    # that, and widening `block_keeps_the_way` from a 192-unit reach to 384 did
    # not change it.
    #
    # So the division of labour stands: the planner refuses what geometry can
    # refuse, the gate refuses the rest at a compile each, and the NUMBER is
    # what this guard holds. One per run per donor is the measured cost; two
    # would mean a proxy stopped working.
    check("the worth gate refuses no more than one construction a seed",
          worthless <= a.seeds,
          f"{worthless} of {built} refused, over {a.seeds} seeds")

    failures, cases = FAILED, CASES
    if not a.skip_red:
        print("controlled RED: the plinth back, and nothing to climb it by")
        cases += 1
        tree = a.work / "red_plinth"
        if tree.exists():
            shutil.rmtree(tree)
        tree.mkdir(parents=True)
        for sub in ("inc", "src", "tools"):
            shutil.copytree(REPO / sub, tree / sub)
        p = tree / "src" / "mapgen" / "mapgen_geometry_edit.c"
        text = p.read_text(encoding="utf-8")
        cuts = [
            # a top no player can reach is allowed again
            ("""        const float top = stood.has_step ? stood.step[1][2] : floor_at;
        if (stood.maxs[2] - top > 64.0f)
            return block_no("nobody can climb onto it");
        if (stood.has_step && stood.step[1][2] - floor_at > 64.0f)
            return block_no("nobody can climb onto its step");
        if (stood.has_tier && stood.tier[1][2] - stood.maxs[2] > 64.0f)
            return block_no("nobody can climb onto its tier");""", ""),
            # and so is a top with the ceiling on it
            ("""        if (!clear_after(donor, head_lo, head_hi, empty_lo, empty_hi))
            return block_no("no headroom on top of it");
    }
    /* And with a player's width beside every side that faces air. */""",
             """    }
    /* And with a player's width beside every side that faces air. */"""),
            # and the plinth is back in the table
            ("""                    { 1.8f, 2.5f,  48.0f,  0.0f, false },  /* terrace  */""",
             """                    { 8.0f, 8.0f, 224.0f,  0.0f, false },  /* plinth   */"""),
            # and the family the plinth belongs to is dealt again.
            #
            # The room block is not dealt into any product schedule since
            # 2026-09-10 - the PO called the heap of platforms it builds
            # «просто мусорница» - so a mutant tree that puts the plinth back
            # in the table plans nothing at all, and this RED reported "0 of 3
            # constructions nobody can use" for the wrong reason entirely.
            # The mutant is a mutant: it gets the family back too.
            ("static bool g_deal_room_blocks = false;",
             "static bool g_deal_room_blocks = true;"),
        ]
        missing = [c for c, _ in cuts if text.count(c) != 1]
        if missing:
            print(f"  FAIL  RED a plinth may stand again: cannot mutate"
                  f" ({len(missing)} of {len(cuts)} sites not found)")
            failures += 1
        else:
            for old, new in cuts:
                text = text.replace(old, new, 1)
            p.write_text(text, encoding="utf-8")
            red_driver = build(tree, tree, "driver_red", DRIVER_SRC)
            red_built, red_worthless = constructions_are_worth_it(
                red_driver, probe, tree, 1, log=False)
            ok = red_worthless > 0
            print(f"  {'PASS' if ok else 'FAIL'}  RED a plinth may stand"
                  f" again: the gate refuses it"
                  f"  -- {red_worthless} of {red_built} constructions"
                  f" nobody can use")
            failures += 0 if ok else 1

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
