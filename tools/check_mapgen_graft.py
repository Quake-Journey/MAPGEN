"""GF7 groundwork: carrying a room from one map into another.

Codex's operator order puts multi-donor bundle substitution and grafting at
GF7, after the single-donor bundle and transaction framework. Almost everything
it needs is already here and already proven inside one map:

    interchangeable()   asks whether one bundle can take another's place - the
                        same ways out, of the same kinds, pointing the same way
                        after one of eight turns, no obligation lost, and the
                        air fitting. It reads only bundle properties, so it
                        never cared which map a bundle came from.
    swap_bundles()      exchanges two of them, as two transforms
    TransformSubset()   moves brushes and entities with their texture axes,
                        their anchors and their angles

What a same-map swap never needed is geometry from a DIFFERENT map. This guard
covers that one primitive, `MapGenGeometry_Graft`, on its own and before any
operator uses it - because an operator built on an unproven primitive is an
operator whose failures are attributed to the wrong place.

What is asserted, and why each matters for GF7:

  the count           what crossed is what was asked for, and the destination
                      grew by exactly that
  the place           the turn and the offset were APPLIED, not merely
                      accepted - proved on a brush that is not square in plan,
                      because a square one is its own rotation
  the source          is unchanged, because a donor that changed while being
                      read from is a donor nothing can be measured against
  provenance          the graft says where its brushes landed, so a caller can
                      record which donor they came from. GF7 requires every
                      grafted bundle to be attributable.
  ownership           an entity whose brushes did not cross is REFUSED rather
                      than written as a door into nothing
  models              two maps both calling something `*1` is two rooms with
                      one name; each source model gets an index of its own

    python tools/check_mapgen_graft.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_geometry_fixtures as fixtures  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402
from mapgen_red_support import resolve_anchor  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260904\graft")

DRIVER = [
    "tools/mapgen_graft_driver.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_trace.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

# Two maps that are not each other, so "it came from the other one" is a fact
# about the result rather than a coincidence.
SOURCE = "open_pair"
DEST = "reshape_plain"

# `open_pair`'s dividing wall: 64 across and 704 along, so a quarter turn moves
# it somewhere a square brush would not go.
WALL = 6

CASES = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
        FAILURES.append(name)
    return bool(ok)


def build(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in DRIVER] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def compile_fixture(work: Path, name: str) -> Path | None:
    job = work / name
    bsp = job / f"{name}.bsp"
    if bsp.exists():
        return bsp
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    source = job / f"{name}.map"
    fixtures.FIXTURES[name](source)
    subprocess.run([str(COMPILER), "-bsp", "-threads", "4",
                    "-moddir", str(GAME), "-basedir", str(GAME),
                    "-gamedir", str(GAME), str(source)],
                   capture_output=True, text=True, timeout=1800)
    return bsp if bsp.exists() else None


def graft(exe: Path, src: Path, dst: Path, out: Path,
          *extra: str) -> dict:
    run = subprocess.run([str(exe), str(src), str(dst), str(out), *extra],
                         capture_output=True, text=True, timeout=600)
    got: dict = {"result": "?", "text": run.stdout + run.stderr}
    for line in run.stdout.splitlines():
        m = re.match(r"^result\s+(\S+)", line)
        if m:
            got["result"] = m.group(1)
        m = re.match(r"^crossed\s+(\d+) brushes, landed at (\d+)", line)
        if m:
            got["crossed"] = int(m.group(1))
            got["landed"] = int(m.group(2))
        m = re.match(r"^dest\s+(\d+) brushes, (\d+) entities", line)
        if m:
            got["dest"] = (int(m.group(1)), int(m.group(2)))
        m = re.match(r"^source\s+(\d+) brushes, (\d+) entities after", line)
        if m:
            got["source_after"] = (int(m.group(1)), int(m.group(2)))
        m = re.match(r"^source\s+(\d+) brushes, (\d+) entities$", line)
        if m:
            got["source"] = (int(m.group(1)), int(m.group(2)))
        m = re.match(r"^after\s+(\d+) brushes, (\d+) entities", line)
        if m:
            got["after"] = (int(m.group(1)), int(m.group(2)))
        m = re.match(r"^bounds\s+(-?\d+) (-?\d+) (-?\d+) \.\. "
                     r"(-?\d+) (-?\d+) (-?\d+)", line)
        if m:
            got["bounds"] = tuple(int(m.group(k)) for k in range(1, 7))
    return got


def static_contract() -> None:
    print("\n=== what the graft is, and what it refuses")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry.h").read_text(
        encoding="utf-8", errors="replace")

    check("it exists and is declared",
          "MapGenGeometry_Graft" in header
          and "mapgen_geometry_result_t MapGenGeometry_Graft" in impl)
    #
    # The transform is not written a second time. This file's own comment says
    # turning a plane about a pivot is the part that is easy to get subtly
    # wrong, and two spellings of it is how two operators come to disagree
    # about where a room ended up.
    #
    check("the transform is reused, not rewritten",
          "MapGenGeometry_TransformSubset(moved" in impl)
    check("the source is cloned rather than modified",
          "MapGenGeometry_Clone(src, &moved)" in impl)
    check("and why that matters is written down",
          "being read is a donor nothing can be measured against" in impl)
    check("every source model gets an index of its own",
          "remap[model] = next_model++;" in impl)
    check("an entity whose brushes did not cross is refused",
          "MAPGEN_GEOMETRY_ERR_OWNERSHIP" in impl
          and "a door into nothing" in impl)
    check("and it says where its brushes landed, for provenance",
          "out_first_brush" in header and "*out_first_brush = first;" in impl)


def behaviour(work: Path) -> dict:
    print("\n=== a room carried from one map into another")

    exe = work / "bin" / "graft.exe"
    err = build(REPO, exe)
    if not check("the driver compiles", not err, err):
        return {}
    src = compile_fixture(work, SOURCE)
    dst = compile_fixture(work, DEST)
    if not check("both fixtures compile", src is not None and dst is not None):
        return {}

    #
    # The wall alone, so the count is exact and the place is checkable.
    #
    plain = graft(exe, src, dst, work / "plain.map",
                  "--first", str(WALL), "--count", "1", "--models-only")
    if not check("the graft succeeds", plain.get("result") == "OK",
                 plain.get("text", "")[-400:]):
        return {}
    check("exactly what was asked for crossed", plain.get("crossed") == 1,
          str(plain.get("crossed")))
    check("and the destination grew by exactly that",
          plain.get("after", (0, 0))[0] == plain.get("dest", (0, 0))[0] + 1,
          f"{plain.get('dest')} -> {plain.get('after')}")
    check("the graft says where they landed",
          plain.get("landed") == plain.get("dest", (0, 0))[0],
          f"landed {plain.get('landed')}, dest had {plain.get('dest')}")
    #
    # The source is const. A donor that changed while being read from is a
    # donor nothing can be measured against afterwards.
    #
    check("and the source is unchanged",
          plain.get("source") == plain.get("source_after"),
          f"{plain.get('source')} -> {plain.get('source_after')}")

    print("\n=== and the turn and the offset were applied, not merely accepted")
    #
    # On a brush that is NOT square in plan, because a square one is its own
    # rotation and would pass this whether or not the turn happened.
    #
    here = plain.get("bounds")
    check("the wall is not square in plan",
          here is not None and abs((here[3] - here[0]) - (here[4] - here[1]))
          > 64, str(here))

    turned = graft(exe, src, dst, work / "turned.map",
                   "--first", str(WALL), "--count", "1", "--models-only",
                   "--quarter", "1")
    there = turned.get("bounds")
    check("a quarter turn swaps its two horizontal extents",
          here is not None and there is not None
          and (there[3] - there[0]) == (here[4] - here[1])
          and (there[4] - there[1]) == (here[3] - here[0]),
          f"{here} -> {there}")
    check("and leaves its height alone",
          here is not None and there is not None
          and (there[5] - there[2]) == (here[5] - here[2]),
          f"{here} -> {there}")

    moved_out = graft(exe, src, dst, work / "moved.map",
                      "--first", str(WALL), "--count", "1", "--models-only",
                      "--offset", "1000", "0", "0")
    away = moved_out.get("bounds")
    check("an offset moves it by exactly that much",
          here is not None and away is not None
          and away[0] == here[0] + 1000 and away[3] == here[3] + 1000,
          f"{here} -> {away}")

    print("\n=== and the entities cross with the brushes they belong to")
    whole = graft(exe, src, dst, work / "whole.map")
    check("every entity crossed",
          whole.get("after", (0, 0))[1]
          == whole.get("dest", (0, 0))[1] + whole.get("source", (0, 0))[1],
          f"{whole.get('dest')} + {whole.get('source')} "
          f"-> {whole.get('after')}")
    check("and the source is still unchanged",
          whole.get("source") == whole.get("source_after"),
          f"{whole.get('source')} -> {whole.get('source_after')}")
    return {"src": src, "dst": dst, "exe": exe, "here": here}


MUTATION = (
    b"""    mapgen_geometry_result_t rc = MapGenGeometry_Clone(src, &moved);""",
    b"""    mapgen_geometry_result_t rc = MapGenGeometry_Clone(src, &moved);
    (void)pivot;""",
)

NO_TRANSFORM = (
    b"""    rc = MapGenGeometry_TransformSubset(moved, brush_mask, entity_mask, pivot,
                                        quarter_turns, mirror_x, offset);""",
    b"""    rc = MAPGEN_GEOMETRY_OK;""",
)


def red(work: Path, got: dict) -> None:
    print("\n=== and the transform is what puts it in the right place")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "graft")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry.c"
        pristine = target.read_bytes()
        anchor, replacement, count = resolve_anchor(pristine, *NO_TRANSFORM)
        if not check("the transform call is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(pristine.replace(anchor, replacement, 1))
        red_exe = box.root / "red_graft.exe"
        err = build(box.root, red_exe)
        if not check("it still compiles without the transform", not err, err):
            target.write_bytes(pristine)
            return
        #
        # With the transform gone the graft still succeeds and still copies the
        # right number of brushes - it simply puts them where they already
        # were. That is exactly the failure a count-only check would miss, and
        # it is why the cases above measure the PLACE.
        #
        bad = graft(red_exe, got["src"], got["dst"], work / "red.map",
                    "--first", str(WALL), "--count", "1", "--models-only",
                    "--offset", "1000", "0", "0")
        check("without it the brush does not move",
              bad.get("result") == "OK"
              and bad.get("bounds") == got.get("here"),
              f"{bad.get('bounds')} against {got.get('here')}")
        target.write_bytes(pristine)
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing",
              hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--no-red", action="store_true")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    print("=== MAPGEN-1 GF7 groundwork: a room carried across from another map")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()
    got = behaviour(args.work)
    if got and not args.no_red:
        red(args.work, got)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("PASS" if not FAILURES else "FAIL"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
