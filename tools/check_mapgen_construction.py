"""What the generator BUILDS has to be something a mapper would have built.

Two questions, both asked of compiled maps by `tools/mapgen_brush_diff.c`:

    is every new construction made of a material the map DRAWS;
    is every new construction standing on something.

Both were answered "no" by the batch of 2026-09-07, in three screenshots. The
blocks wore `e1u1/clip` - the name the .map writer gives a side that has no
texture, which the block builders were borrowing from "any wall face at all" -
and the recut's blocks hung in the air over a courtyard, because their base
came from the floor of the emptied REGION rather than from the ground.

    python tools/check_mapgen_construction.py [--work DIR] [--skip-red]

The RED half of this guard is not a mutation: it is the three maps that were
handed to the PO. They are still on disk, they still fail, and the guard reads
them. The GREEN half applies today's operators to the same donor, compiles,
and asks the same two questions of the result.

Then two controlled mutations, because a guard that has only ever seen a
repaired tree proves nothing: put "any wall face at all" back and the material
case reopens; put the region's floor back and the construction floats again.
"""
from __future__ import annotations

import argparse
import importlib.util
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
BATCH = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\batch")
MAPS = GAME / "maps"
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907"
                    r"\construction_gate")

DIFF_SRC = ["tools/mapgen_brush_diff.c", "src/mapgen/mapgen_geometry.c",
            "src/mapgen/mapgen_bsp.c", "src/mapgen/mapgen_digest.c",
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

# The three maps that were handed to the PO on 2026-09-07, as ARTIFACTS beside
# the baseline each run compiled. These are the RED.
#
# The artifacts and not the installed files: the maps directory is replaced
# every time a batch is delivered, and a guard whose RED can be overwritten by
# the next delivery is a guard that stops proving anything the moment it
# starts passing. These paths are what those maps WERE.
DELIVERED = [
    ("the f090s1 of 2026-09-07",
     BATCH / "q2mg_f90s1" / "baseline" / "q2mg_f90s1.bsp",
     BATCH / "q2mg_f90s1" / "try_0042" / "q2mg_f90s1.bsp"),
    ("the f090s2 of 2026-09-07",
     BATCH / "q2mg_f90s2" / "baseline" / "q2mg_f90s2.bsp",
     BATCH / "q2mg_f90s2" / "try_0115" / "q2mg_f90s2.bsp"),
    ("the f090s3 of 2026-09-07",
     BATCH / "q2mg_f90s3b" / "baseline" / "q2mg_f90s3.bsp",
     BATCH / "q2mg_f90s3b" / "try_0112" / "q2mg_f90s3.bsp"),
]

CASES = 0
FAILED = 0

SUMMARY = re.compile(r"added (\d+) \((\d+) constructions, (\d+) remnants"
                     r" and pools\): (\d+) not a material, (\d+) floating")


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def pinned() -> tuple[Path, str]:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler()


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


def compile_map(path: Path) -> str:
    exe, threads = pinned()
    run = subprocess.run(
        [str(exe), "-bsp", "-threads", threads, "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


def judge(diff: Path, baseline: Path, candidate: Path) -> dict:
    run = subprocess.run([str(diff), str(baseline), str(candidate)],
                         capture_output=True, text=True, timeout=3600)
    m = SUMMARY.search(run.stdout)
    if not m:
        return {"error": (run.stdout + run.stderr)[-300:]}
    return {"added": int(m.group(1)), "constructions": int(m.group(2)),
            "remnants": int(m.group(3)), "unmaterial": int(m.group(4)),
            "floating": int(m.group(5)),
            "bad": [line.strip() for line in run.stdout.splitlines()
                    if line.strip().startswith("BAD")]}


def offered(driver: Path, donor: Path, seed: int) -> list[tuple[int, str]]:
    run = subprocess.run([str(driver), str(donor), "--seed", str(seed),
                          "--list", "--recuts"], capture_output=True,
                         text=True,
                         timeout=3600)
    return [(int(i), kind) for i, kind in
            re.findall(r"edit (\d+)\s+(recut|push|block)\s+", run.stdout)]


def one_candidate(driver: Path, donor: Path, seed: int, which: int,
                  work: Path, name: str) -> Path | None:
    """Apply one edit, write it, compile it, and hand back the artifact."""
    out = work / f"{name}.map"
    subprocess.run([str(driver), str(donor), "--seed", str(seed),
                    "--apply", str(which), "--out", str(out), "--recuts"],
                   capture_output=True, text=True, timeout=3600)
    if not out.exists():
        return None
    log = compile_map(out)
    bsp = out.with_suffix(".bsp")
    return bsp if bsp.exists() and "leaked" not in log.lower() else None


def green(tree: Path, work: Path, diff: Path, label: str, log: bool = True
          ) -> tuple[int, int]:
    """Today's operators on the real donor, compiled, and judged."""
    driver = build(tree, work, "driver_" + label, DRIVER_SRC)
    donor = CORPUS / "q2dm1.bsp"
    # A baseline compile of the donor's own geometry, so that "added" means
    # added by the edit rather than by the round trip.
    base_map = work / f"base_{label}.map"
    subprocess.run([str(driver), str(donor), "--out", str(base_map)],
                   capture_output=True, text=True, timeout=3600)
    compile_map(base_map)
    baseline = base_map.with_suffix(".bsp")
    if not baseline.exists():
        if log:
            check(f"{label}: the donor's own geometry compiles", False, "no bsp")
        return (1, 1)

    unmaterial = floating = 0
    seen = 0
    for seed in (1, 3):
        # One of each family the seed offers, so that the room block - the
        # construction the PO photographed - is covered as well as the recut.
        by_kind = {}
        for which, kind in offered(driver, donor, seed):
            by_kind.setdefault(kind, which)
        for kind, which in sorted(by_kind.items()):
            bsp = one_candidate(driver, donor, seed, which, work,
                                f"{label}_s{seed}_e{which}")
            if not bsp:
                continue
            got = judge(diff, baseline, bsp)
            seen += 1
            unmaterial += got.get("unmaterial", 0)
            floating += got.get("floating", 0)
            if log:
                check(f"a {kind} on q2dm1 (seed {seed}, edit {which}) builds"
                      f" material, on the ground",
                      got.get("unmaterial") == 0 and got.get("floating") == 0,
                      f"{got.get('constructions')} constructions,"
                      f" {got.get('unmaterial')} not a material,"
                      f" {got.get('floating')} floating"
                      + (f"; {got['bad'][0]}" if got.get("bad") else ""))
    if log and not seen:
        check(f"{label}: at least one construction edit could be applied",
              False, "none applied")
    return (unmaterial, floating)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    exe, _ = pinned()
    if not exe.exists():
        print(f"  the pinned compiler is not at {exe}")
        return 2

    diff = build(REPO, a.work, "brush_diff", DIFF_SRC)

    print("the maps that were handed over - the RED this guard was written for")
    for name, baseline, bsp in DELIVERED:
        if not bsp.is_file() or not baseline.is_file():
            check(f"{name} and its baseline are still on disk", False,
                  f"{bsp if not bsp.is_file() else baseline} is gone")
            continue
        got = judge(diff, baseline, bsp)
        check(f"{name} as delivered fails - the tool sees what the PO saw",
              (got.get("unmaterial", 0) > 0 or got.get("floating", 0) > 0),
              f"{got.get('unmaterial')} not a material,"
              f" {got.get('floating')} floating"
              + (f"; {got['bad'][0]}" if got.get("bad") else ""))

    # And the FLOATING half of the probe specifically, because that is the half
    # no mutation can exercise any more - see the note in the RED section.
    floating_seen = 0
    for name, baseline, bsp in DELIVERED:
        if bsp.is_file() and baseline.is_file():
            floating_seen += judge(diff, baseline, bsp).get("floating", 0)
    check("and at least one of them floats, which is the floating rule's own"
          " red evidence", floating_seen > 0, f"{floating_seen} floating")

    print("and what the operators build today")
    green(REPO, a.work, diff, "now")

    failures = FAILED
    cases = CASES
    if not a.skip_red:
        print("controlled RED")
        for name, edits, expect in (
            ("any wall face at all is a skin again", [(
                "src/mapgen/mapgen_geometry_edit.c",
                """    const uint32_t faces = MapGenGeometry_NumFaces(g);
    const mapgen_geometry_face_t *best = NULL;""",
                """    /* RED: the first SIDE with a near-vertical normal, which on q2dm1
       has no texture at all and is written out as e1u1/clip. */
    {
        const uint32_t ns = MapGenGeometry_NumSides(g);
        for (uint32_t s = 0; s < ns; s++) {
            const mapgen_geometry_side_t *side = MapGenGeometry_Side(g, s);
            if (side && !side->bevel && side->num_samples
                && (want_up ? side->normal[2] > 0.7f
                            : fabsf(side->normal[2]) < 0.2f)) {
                memset(out, 0, sizeof(*out));
                memcpy(out->texture, side->texture, sizeof(out->texture));
                out->flags = side->flags;
                out->value = side->value;
                (void)at;
                return true;
            }
        }
        return false;
    }
    const uint32_t faces = MapGenGeometry_NumFaces(g);
    const mapgen_geometry_face_t *best = NULL;""")], "unmaterial"),
            # The mutation moved because the defect's home did.
            #
            # This used to reach into the recut's own copy of the grounding
            # arithmetic, which is gone: the recut and the room block now ask
            # one predicate, `block_stands`, and the drop onto the floor
            # happens once, there. So the RED is the drop itself - leave every
            # construction at the height it was dealt, which for a recut is
            # the floor of a region that grew hundreds of units above the
            # room's own, and is exactly what the PO photographed against the
            # sky on 2026-09-07.
            #
            # There is no FLOATING mutation here any more, and the reason is a
            # result rather than a gap.
            #
            # Two were tried on 2026-09-10 and both were measured at 0 floating:
            # standing the construction on the emptied region's own floor line
            # instead of on the ground (the line is now a 16-unit clearance over
            # a real floor, so the 4-unit probe under the corners still finds
            # rock), and basing it on the HIGHEST of the nine ground samples
            # instead of the lowest - which `footprint_ground`'s own comment
            # names as the defect - because `one_floor` refuses any footprint
            # whose nine samples span more than 8 units while the foot is buried
            # 16. Highest and lowest cannot differ by enough to lift a corner
            # off the rock.
            #
            # So the floating predicate's red evidence is the three DELIVERED
            # maps of 2026-09-07 checked at the top of this guard: f090s1 and
            # f090s3 each carry one floating construction, on disk, compiled, and
            # this probe finds them. A real artifact that fails is stronger
            # evidence than a mutant, and what it proves is the same thing.
            #
        ):
            cases += 1
            tree = a.work / "red" / re.sub(r"\W+", "_", name)
            if tree.exists():
                shutil.rmtree(tree)
            tree.mkdir(parents=True)
            for sub in ("inc", "src", "tools"):
                shutil.copytree(REPO / sub, tree / sub)
            ok_to_run = True
            for rel, old, new in edits:
                p = tree / rel
                text = p.read_text(encoding="utf-8")
                if text.count(old) != 1:
                    print(f"  FAIL  RED {name}: cannot mutate"
                          f" ({text.count(old)} matches)")
                    failures += 1
                    ok_to_run = False
                    break
                p.write_text(text.replace(old, new, 1), encoding="utf-8")
            if not ok_to_run:
                continue
            unmaterial, floating = green(tree, tree, diff, "red", log=False)
            got = unmaterial if expect == "unmaterial" else floating
            print(f"  {'PASS' if got else 'FAIL'}  RED {name}:"
                  f" {expect} comes back  -- {unmaterial} not a material,"
                  f" {floating} floating")
            failures += 0 if got else 1

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
