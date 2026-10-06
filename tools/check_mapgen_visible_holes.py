"""Can a player see through a rebuilt wall?

The PO photographed a strip of sky in the middle of a wall in a fidelity-100
fork of q2dm1 and reported it for five days. Three guards looked at that same
map and all three passed it:

    the wall audit probes one point per surface, at the surface's middle, and
    a seam is never in the middle of anything - 0 lost on the broken map;
    the surface-fault count is about brush windings, and the brushes were fine;
    the coverage oracle allows a candidate face two units off-plane and a whole
    sampling step of slack outside its edge, which is more slack than the whole
    defect - 0 uncovered of 1151333 points on the broken map.

Two of those three ask about SOLID, and solid was never wrong here: the wall's
brush stayed exactly where it was and only its drawn face moved, onto a
neighbouring plane half a unit in. A map can keep every cubic unit of its
collision hull and still be missing two thirds of a wall from its mesh.

So this one asks the question a player asks, with no slack to hide in: every
point the donor DRAWS must be drawn by the rebuild, on the same plane, within a
hair. It also says what shows through each gap, because that is what separates
a defect from a difference - a surface half a unit back wearing the same
texture is the compiler re-deriving a plane and nobody can see it; void is the
photograph.

    python tools/check_mapgen_visible_holes.py [--donor NAME ...] [--work DIR]
                                               [--skip-red]

Cases, per donor:
    the rebuild compiles;
    no gap a player can see through is larger than SEE_THROUGH_MAX;
    the total undrawn area stays under the budget measured for that donor;
    the solid behind the donor's surfaces is not lost in new places;
    and no brush GROWS into the air in front of a wall - the question nobody
    was asking, and the one that explains a wall buried by its neighbour.

Then two controlled REDs on the writer knob that caused it, because the fix has
two halves. With MAPGEN_BEVEL_OUTSET at zero - a redundant plane written exactly
where the donor had it, so the writer's own rounding can move it inward and cut
the wall - the see-through gap on q2dm1 must come back. And with it at 1/128,
BELOW the pinned compiler's DIST_EPSILON of 0.01, `PlaneEqual` merges the plane
straight back onto the face it was meant to stand clear of, so the outset must
be shown to buy nothing at all. Then the writer is restored and both must close
again.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260906\holes")

FORK_SRC = ["tools/mapgen_geometry_fork.c", "src/mapgen/mapgen_geometry.c",
            "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_bsp.c",
            "src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_rooms.c",
            "src/mapgen/mapgen_bundle.c", "src/mapgen/mapgen_closure.c"]
HOLES_SRC = ["tools/mapgen_visible_holes.c", "src/mapgen/mapgen_bsp.c"]
SEAM_SRC = ["tools/mapgen_seam_audit.c", "src/mapgen/mapgen_bsp.c",
            "src/mapgen/mapgen_trace.c"]

# What a player may see through, anywhere, in square units. The photographed
# gap was 13120 and every donor now measures 0. This is a ceiling to hold, not
# a target to grow into; it is not 0 only so that an equivalent re-split of one
# surface cannot fail the suite on its own.
SEE_THROUGH_MAX = 64

# Undrawn area, per donor. All four now rebuild every drawn point of their
# donor exactly, q2dm1 included - it stopped being the exception when local
# patch P12 stopped the compiler cutting every winding out of a quad 2^20 units
# wide in single precision. Zero is what they measure, so zero is the budget.
UNDRAWN_BUDGET = {"q2dm1": 0, "q2dm2": 0, "q2dm3": 0, "q2dm8": 0}

# Points where the donor has solid and the rebuild does not. Measured, per
# donor, with a little room: these are a separate defect from the one this
# guard is for, and the budget exists so that a change cannot trade the mesh
# for the hull without anyone noticing. MEASURED 2026-09-06 with P12 and
# integer plane points: 2, 3, 311, 583 - down from 48, 136, 341, 634.
SOLID_BUDGET = {"q2dm1": 10, "q2dm2": 10, "q2dm3": 330, "q2dm8": 620}

# And points where the donor has AIR and the rebuild has solid, which is the
# question nobody was asking. A brush that comes back proud buries the strip of
# wall beside it and the compiler stops drawing it. MEASURED 2026-09-06 with
# P12 and integer plane points: 11, 115, 47, 28 - q2dm1 down from 2458, which
# was the same winding precision showing on the other side.
GROWN_BUDGET = {"q2dm1": 30, "q2dm2": 140, "q2dm3": 70, "q2dm8": 50}

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def build(work: Path, name: str, sources, defines=()) -> Path:
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    exe = out / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I" + str(REPO / "inc")]
        + [f"-D{d}" for d in defines]
        + [str(REPO / f) for f in sources] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-1500:])
        raise SystemExit(f"cannot build {name}")
    return exe


def pinned_threads() -> str:
    """The compiler thread count the pin qualified, not a number of our own.

    MEASURED and recorded in the pin: the semantic digest does not depend on
    this, but the time does - the compiler waits a fixed second per parallel
    batch, so one thread is 0.3s where sixteen is 12.8s. Asking for a count the
    pin did not qualify is calling three configurations one pinned one.
    """
    pin = json.loads((REPO / "tools" / "mapgen_compiler_pin.json")
                     .read_text(encoding="utf-8"))
    return str(pin["thread_policy"]["value"])


def compile_map(path: Path) -> str | None:
    run = subprocess.run(
        [str(COMPILER), "-bsp", "-threads", pinned_threads(), "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)
    text = run.stdout + run.stderr
    if run.returncode != 0 or "ERROR" in text:
        return "refused"
    if "leaked" in text.lower():
        return "leaked"
    return None


HEAD = re.compile(r"(\d+) no longer drawn on their own plane, in (\d+) places")
ROW = re.compile(r"\s+(\d+) sq units .*?->\s+(.*?)(?:, ([\d.]+) behind)?$")


def read_holes(text: str) -> tuple[int, int, str]:
    """Undrawn area, the largest gap you can see through, and its line."""
    head = HEAD.search(text)
    total = int(head.group(1)) if head else -1
    worst, worst_line = 0, ""
    for line in text.splitlines():
        m = ROW.match(line.rstrip())
        if not m:
            continue
        area, how_far = int(m.group(1)), m.group(3)
        # Visible when what shows through is far enough back to read as
        # somewhere else, or is nothing at all.
        if (how_far is None or float(how_far) > 1.0) and area > worst:
            worst, worst_line = area, line.strip()
    return total, worst, worst_line


def rebuild(work: Path, donor: Path, fork: Path, tag: str) -> Path | None:
    out_map = work / f"{donor.stem}_{tag}.map"
    run = subprocess.run([str(fork), str(donor), str(out_map), "100", "1"],
                         capture_output=True, text=True)
    if run.returncode != 0:
        return None
    return None if compile_map(out_map) else out_map.with_suffix(".bsp")


def measure(holes: Path, seam: Path, donor: Path,
            bsp: Path) -> tuple[int, int, str, int, int]:
    h = subprocess.run([str(holes), str(donor), str(bsp), "1", "0.35"],
                       capture_output=True, text=True)
    s = subprocess.run([str(seam), str(donor), str(bsp), "4"],
                       capture_output=True, text=True)
    total, worst, line = read_holes(h.stdout)
    lost = re.search(r"lost the solid behind (\d+) of them", s.stdout)
    grown = re.search(r"grown solid in front of (\d+) of them", s.stdout)
    return (total, worst, line,
            int(lost.group(1)) if lost else -1,
            int(grown.group(1)) if grown else -1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--donor", action="append", default=None)
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    args = ap.parse_args()

    names = args.donor or ["q2dm1", "q2dm2", "q2dm3", "q2dm8"]
    if not COMPILER.exists():
        print(f"  the pinned compiler is not at {COMPILER}")
        return 2
    args.work.mkdir(parents=True, exist_ok=True)

    fork = build(args.work, "fork", FORK_SRC)
    holes = build(args.work, "holes", HOLES_SRC)
    seam = build(args.work, "seam", SEAM_SRC)

    for name in names:
        donor = CORPUS / f"{name}.bsp"
        if not donor.exists():
            check(f"{name}: the donor is in the corpus", False, str(donor))
            continue
        print(f"{name}:")
        bsp = rebuild(args.work, donor, fork, "green")
        if not check(f"{name}: the rebuild compiles", bsp is not None):
            continue
        total, worst, line, lost, grown = measure(holes, seam, donor, bsp)
        check(f"{name}: nothing a player can see through above"
              f" {SEE_THROUGH_MAX} square units",
              worst <= SEE_THROUGH_MAX, f"{worst} -- {line}")
        budget = UNDRAWN_BUDGET.get(name, 0)
        check(f"{name}: undrawn area within its budget of {budget}",
              0 <= total <= budget, str(total))
        solid = SOLID_BUDGET.get(name, 0)
        check(f"{name}: solid lost at no more than {solid} points",
              0 <= lost <= solid, str(lost))
        proud = GROWN_BUDGET.get(name, 0)
        check(f"{name}: solid grown at no more than {proud} points",
              0 <= grown <= proud, str(grown))

    if not args.skip_red:
        donor = CORPUS / "q2dm1.bsp"
        #
        # Two mutations, because the fix has two halves and each has to be
        # shown to matter on its own.
        #
        for label, define, why in (
                ("0",
                 "MAPGEN_BEVEL_OUTSET=0.0",
                 "a redundant plane written exactly where the donor had it, so"
                 " the writer's own rounding can move it inward"),
                ("under_epsilon",
                 "MAPGEN_BEVEL_OUTSET=0.0078125",
                 "outset by less than the compiler's DIST_EPSILON of 0.01, so"
                 " PlaneEqual merges it straight back onto the face")):
            print(f"controlled RED -- {why}:")
            red_fork = build(args.work, f"fork_red_{label}", FORK_SRC,
                             (define,))
            bsp = rebuild(args.work, donor, red_fork, f"red_{label}")
            if check("  the mutated writer still compiles", bsp is not None):
                undrawn, worst, line, _, _ = measure(holes, seam, donor, bsp)
                #
                # The undrawn budget, and deliberately not the see-through
                # ceiling. Since P12 these two mutations lose a wall to the
                # plane half a unit behind it rather than to a gap, so they no
                # longer open anything a player can see through - and a guard
                # must assert what its mutation actually does.
                #
                check("  and the undrawn area breaks its budget",
                      undrawn > UNDRAWN_BUDGET["q2dm1"], f"{undrawn} -- {line}")
        bsp = rebuild(args.work, donor, fork, "restored")
        if check("  the writer restored still compiles", bsp is not None):
            undrawn, worst, _, _, _ = measure(holes, seam, donor, bsp)
            check("  and nothing is see-through again", worst <= SEE_THROUGH_MAX,
                  str(worst))
            check("  and the undrawn area is back within budget",
                  undrawn <= UNDRAWN_BUDGET["q2dm1"], str(undrawn))

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    print("RESULT: " + ("PASS" if FAILED == 0 else "FAIL"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
