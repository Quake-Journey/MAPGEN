"""The recut operator: what it may empty, and what it may never reach.

A recut takes the middle out of a room and stands new blocks in it. The one
thing it must never do is reach the VOID - the gap between two rooms' shells,
where the compiler's tree says solid because there is nothing there. A region
that took a shell away and was emptied would leave the map open, and the
compiler answers that with "**** leaked ****" and no lighting and no vis.

So the fixture is built to contain exactly that trap: two sealed boxes with
two hundred and fifty-six units of nothing between them, joined by a corridor.
A grown region that stops at the shell is correct; one that walks through it
is the defect, and the controlled RED below produces it on purpose and watches
the compiler find the hole.

    python tools/check_mapgen_recut.py [--work DIR] [--skip-red]

The cases:

    the fixture itself compiles sealed                      no leak
    a box inside the big room's air is sound                yes
    a box spanning the gap between the two shells is NOT    no
    the region grown from the room's middle stays inside
    its own shell                                           bounded
    the planner offers a ladder rather than one size        >= 2 sizes
    the recut applied compiles sealed                       no leak
    what was in the region is gone and blocks stand there   measured on
                                                            the compiled BSP
    HollowWorld leaves a door's own brushes standing and
    Hollow does not                                         differential

    RED  the void is indistinguishable from a wall: the grown region walks
         through the shell and the compiled map leaks.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
from mapgen_load_guard import game_dir  # noqa: E402  (brief 13 W1: the game folder of this run)
GAME = Path(game_dir())
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\recut_gate")

SOURCES = [
    "tools/mapgen_recut_driver.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_reach.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_digest.c",
    "src/common/q2prox_cpu_topology.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

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


# ---- the fixture -----------------------------------------------------------

AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"
WALL = "e2u3/blum12_1"
FLOOR = "e2u3/floor1_6"
T = 32          # every shell is one thirty-two unit slab thick

# Room A, the big one, and room B beside it. The x gap between A and B is the
# void this guard exists for: nothing is built there, so the compiled tree calls
# it solid and no brush provides it.
#
# A is 1536 across and was 1024, and the reason is a decision rather than a
# preference. The room block is planned BEFORE the recut since assignment 8 -
# measured, because giving the room to the recut instead cost F90 two thirds of
# its divergence - and the block family fills a 1024-unit room on every seed
# tried, so the recut had nothing left to be tested with. A room with corners
# for the blocks AND a middle they do not reach is what lets this guard go on
# asking what it was written to ask. The gap, the pillar and the corridor are
# unchanged in shape; only A's far wall and B's position moved with it.
A = (0, 0, 0, 1536, 1536, 320)
B = (1792, 0, 0, 2304, 512, 320)
# The corridor between them, and the opening it needs in each shell. The
# opening has to lie inside BOTH rooms - room B is only 512 deep - or the
# corridor meets the smaller room's wall from outside and the map leaks.
HOLE_Y = (320, 416)
HOLE_Z = (32, 160)


def box(x0, y0, z0, x1, y1, z1, tex=WALL):
    t = f"{tex} {AXES}"
    faces = [
        [(x0, 0, 0), (x0, 1, 0), (x0, 0, 1)],
        [(x1, 0, 0), (x1, 0, 1), (x1, 1, 0)],
        [(0, y0, 0), (0, y0, 1), (1, y0, 0)],
        [(0, y1, 0), (1, y1, 0), (0, y1, 1)],
        [(0, 0, z0), (1, 0, z0), (0, 1, z0)],
        [(0, 0, z1), (0, 1, z1), (1, 0, z1)],
    ]
    out = ["{"]
    for f in faces:
        out.append(" ".join(f"( {p[0]} {p[1]} {p[2]} )" for p in f) + " " + t)
    out.append("}")
    return "\n".join(out)


def shell(b, holes=()):
    """Six slabs around a box, with rectangular openings cut out of the named
    faces. A hole is (face, y0, y1, z0, z1) and only the two x faces are ever
    asked for here, which is all the fixture needs."""
    x0, y0, z0, x1, y1, z1 = b
    out = [
        box(x0, y0, z0, x1, y1, z0 + T, FLOOR),          # floor
        box(x0, y0, z1 - T, x1, y1, z1),                 # ceiling
        box(x0, y0, z0, x1, y0 + T, z1),                 # -y
        box(x0, y1 - T, z0, x1, y1, z1),                 # +y
    ]
    for face, wx0, wx1 in (("-x", x0, x0 + T), ("+x", x1 - T, x1)):
        cut = [h for h in holes if h[0] == face]
        if not cut:
            out.append(box(wx0, y0, z0, wx1, y1, z1))
            continue
        _, hy0, hy1, hz0, hz1 = cut[0]
        out += [
            box(wx0, y0, z0, wx1, hy0, z1),
            box(wx0, hy1, z0, wx1, y1, z1),
            box(wx0, hy0, z0, wx1, hy1, hz0),
            box(wx0, hy0, hz1, wx1, hy1, z1),
        ]
    return out


def entity(classname, **keys):
    out = ["{", f'"classname" "{classname}"']
    out += [f'"{k}" "{v}"' for k, v in keys.items()]
    out.append("}")
    return "\n".join(out)


def write_fixture(path: Path) -> None:
    brushes = shell(A, holes=[("+x", HOLE_Y[0], HOLE_Y[1], HOLE_Z[0], HOLE_Z[1])])
    brushes += shell(B, holes=[("-x", HOLE_Y[0], HOLE_Y[1], HOLE_Z[0], HOLE_Z[1])])
    # The corridor across the gap: a tube whose ends meet the two openings.
    brushes += [
        box(A[3] - T, HOLE_Y[0], HOLE_Z[0] - T, B[0] + T, HOLE_Y[1], HOLE_Z[0]),
        box(A[3] - T, HOLE_Y[0], HOLE_Z[1], B[0] + T, HOLE_Y[1], HOLE_Z[1] + T),
        box(A[3] - T, HOLE_Y[0] - T, HOLE_Z[0] - T, B[0] + T, HOLE_Y[0],
            HOLE_Z[1] + T),
        box(A[3] - T, HOLE_Y[1], HOLE_Z[0] - T, B[0] + T, HOLE_Y[1] + T,
            HOLE_Z[1] + T),
    ]
    # Something in the middle of room A for the recut to take away - and
    # something a construction can be a STEP TO.
    #
    # It was 224 tall, and since 2026-09-10 a construction is only offered if
    # its top is within a jump of a standing surface the map already had: 270
    # units of jump against 800 of gravity is 45.6 of apex, plus an 18-unit
    # step, so 64. A block 32 to 64 tall in the middle of this room had its
    # top at 96 and the pillar's at 224, which is 128 above it and out of
    # reach - so the family considered four rungs and offered none, and the
    # guard reported "no recut on this fixture at all". That was the rule
    # working on a fixture that had nowhere to climb to.
    #
    # 144 is a pillar a block is a step onto, which is the situation this
    # family exists for and therefore the one its fixture has to contain.
    brushes.append(box(704, 704, T, 832, 832, 144))

    text = ["// Game: Quake 2", "// Format: Valve",
            "{", '"classname" "worldspawn"', '"mapversion" "220"',
            "\n".join(brushes), "}",
            entity("info_player_start", origin="160 160 64"),
            entity("info_player_deathmatch", origin="160 800 64"),
            entity("info_player_deathmatch", origin="1500 200 64"),
            entity("light", origin="768 768 250", light="400"),
            entity("light", origin="2020 250 250", light="300"),
            # A machine inside the region, so that what HollowWorld leaves
            # standing can be counted.
            "{", '"classname" "func_door"', '"angle" "-1"', '"speed" "100"',
            box(956, 448, T, 972, 576, 160), "}"]
    path.write_text("\n".join(text) + "\n", encoding="ascii")


# ---- running things --------------------------------------------------------

def pinned() -> tuple[Path, str]:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler()


def compile_map(path: Path) -> str:
    exe, threads = pinned()
    run = load_guard.run(
        [str(exe), "-bsp", "-threads", threads, "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


def build_driver(tree: Path, out: Path) -> Path:
    exe = out / "recut_driver.exe"
    if exe.exists():
        exe.unlink()
    run = load_guard.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"),
         "-I" + str(tree / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(tree / s) for s in SOURCES] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the recut driver")
    return exe


def drive(exe: Path, bsp: Path, *args: str) -> str:
    #
    # `--recuts` on every run, because the family is no longer DEALT into any
    # product schedule: the PO refused what it builds and what it empties on
    # his fourth round of screenshots (2026-09-10), and
    # `MapGenGeometryEdit_DealRecuts` is off by default. The operator is still
    # here and still has to be correct, which is what this guard is for, so it
    # asks for it.
    #
    run = load_guard.run([str(exe), str(bsp), *args, "--recuts"],
                         capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


GROWN = re.compile(r"grown (-?\d+) (-?\d+) (-?\d+)\s+(-?\d+) (-?\d+) (-?\d+)")
BRUSHES = re.compile(r"(\d+) brushes")


def brushes_in_door(map_text: str) -> int:
    """How many brushes the func_door block still owns."""
    at = map_text.find('"classname" "func_door"')
    if at < 0:
        return 0
    depth = 0
    count = 0
    for ch in map_text[at:]:
        if ch == "{":
            depth += 1
            if depth == 1:
                count += 1
        elif ch == "}":
            if depth == 0:
                break
            depth -= 1
    return count


def line_of(text: str, word: str) -> str:
    """The line that answers the question, not the last line printed. The
    driver prints a surface-fault tally after everything else, and a detail
    that quoted it made two cases look as though they had measured it."""
    for line in text.splitlines():
        if word in line:
            return line.strip()
    return text.strip().splitlines()[-1] if text.strip() else ""


def leaked(log: str) -> bool:
    return "leaked" in log.lower()


# ---- the run ---------------------------------------------------------------

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

    print("fixture")
    fixture = a.work / "recut_fixture.map"
    write_fixture(fixture)
    log = compile_map(fixture)
    if not check("the fixture compiles sealed", not leaked(log) and
                 (a.work / "recut_fixture.bsp").exists(),
                 log.strip().splitlines()[-1] if log.strip() else ""):
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1
    donor = a.work / "recut_fixture.bsp"

    driver = build_driver(REPO, a.work)

    print("what may be emptied")
    inside = drive(driver, donor, "--sound", "200", "200", "64",
                   "800", "800", "250")
    check("a box inside the room's air may be emptied", "sound yes" in inside,
          line_of(inside, "sound"))

    # From inside room A, across the gap, into room B. Every unit of the gap
    # is solid to the tree and no brush provides any of it.
    across = drive(driver, donor, "--sound", "1312", "200", "64",
                   "1912", "400", "250")
    check("a box that spans the gap between two shells may NOT",
          "sound no" in across, line_of(across, "sound"))

    # Room A's interior is 960 units across. A region that grew to the shell
    # and stopped there is the whole of what this operator may do; one that
    # stopped at a tenth of the room is a grower that does not work, and one
    # that passed x=1024 has walked into the gap.
    grown = drive(driver, donor, "--grow", "768", "768", "160")
    m = GROWN.search(grown)
    span = (int(m.group(4)) - int(m.group(1))) if m else 0
    check("a region grown from the room's middle fills it and stops at its"
          " own shell",
          bool(m) and int(m.group(4)) <= A[3] and int(m.group(1)) >= A[0]
          and span >= 512,
          f"{m.group(0) if m else grown.strip()}: {span} units across, the"
          f" room's air is {A[3] - A[0] - 2 * T} and its shell ends at"
          f" x={A[3]}")

    print("the operator")
    listing = drive(driver, donor, "--list")
    # `--list` prints a recut as the box it will BUILD plus the region's own
    # width as `amount`; it used to print "recut <amount> region <box>" and
    # this guard went on matching that after the driver stopped saying it, so
    # it reported "the planner offers no recut at all" on a listing with two
    # in it.
    #
    # The ladder is read off the OFFERS again.
    #
    # It was moved onto the rungs the planner merely considered in assignment
    # 8, because the room block was planned first and filled this fixture, so
    # what survived to be offered was whatever one rung the blocks had left
    # alone. The block is no longer dealt at all (2026-09-10, the PO's verdict
    # on the heap of platforms), the family has the fixture to itself, and the
    # design shows where it should: seven candidates at seven different sizes.
    # The rungs considered are still counted and printed, because a ladder
    # that stops being offered should say whether it stopped being CONSIDERED
    # or stopped surviving.
    rungs = set(re.findall(r"recut room (\d+) rung (\d+)", listing))
    per_room: dict[str, set] = {}
    for room, rung in rungs:
        per_room.setdefault(room, set()).add(rung)
    widest = max((len(v) for v in per_room.values()), default=0)
    spans = [int(x) for x in re.findall(r"recut\s+.*?amount\s+(-?\d+)",
                                        listing)]
    check("the planner offers a ladder of sizes rather than one",
          len(spans) >= 2 and len(set(spans)) >= 2,
          f"{len(spans)} offered at {len(set(spans))} sizes: {spans};"
          f" {widest} rungs considered for one room")

    # The largest one, because the case below asks whether what stood in the
    # middle of the big room is gone and only the largest region covers it.
    offered = [(int(s), i) for i, s in
               re.findall(r"edit (\d+)\s+recut\s+.*?amount\s+(-?\d+)",
                          listing)]
    if not offered:
        check("the planner offers a recut on this fixture at all", False,
              listing.strip()[-200:])
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1
    which = str(max(offered)[1])

    cut = a.work / "recut_applied.map"
    applied = drive(driver, donor, "--apply", which, "--out", str(cut))
    check("the recut applies", "changed yes" in applied,
          line_of(applied, "apply"))
    log = compile_map(cut)
    check("and the map it produced compiles SEALED",
          not leaked(log) and cut.with_suffix(".bsp").exists(),
          "leaked" if leaked(log) else "no leak")

    # What the region held is gone, and something new stands in it. Asked of
    # the COMPILED candidate at a point, because the question is what a player
    # would walk into - not what the plan intended.
    after_bsp = cut.with_suffix(".bsp")
    if after_bsp.exists():
        # The pillar is the box at 704..832 on both axes, so its middle -
        # which is the middle of room A, where the region grows from.
        was = drive(driver, donor, "--contents", "768", "768", "128")
        now = drive(driver, after_bsp, "--contents", "768", "768", "128")
        check("the pillar that stood in the middle is gone from the compiled"
              " map",
              "contents solid" in was and "contents empty" in now,
              f"before: {line_of(was, 'contents')};"
              f" after: {line_of(now, 'contents')}")

        # And something new stands somewhere in the region. The blocks are
        # dealt from the seed, so the guard looks for solid where the donor
        # had air rather than at one predicted place.
        grid = [(x, y) for x in range(320, 1220, 64)
                for y in range(320, 1220, 64)]
        new_solid = 0
        for x, y in grid:
            d = drive(driver, donor, "--contents", str(x), str(y), "64")
            c = drive(driver, after_bsp, "--contents", str(x), str(y), "64")
            if "contents empty" in d and "contents solid" in c:
                new_solid += 1
        check("and new blocks stand where the donor had air", new_solid > 0,
              f"{new_solid} of {len(grid)} probed places are now solid")
    else:
        check("the pillar that stood in the middle is gone from the compiled"
              " map", False, "no compiled candidate")
        check("and new blocks stand where the donor had air", False,
              "no compiled candidate")

    print("the machines")
    world = a.work / "hollow_world.map"
    both = a.work / "hollow_both.map"
    region = ["--hollow", "856", "400", "0", "1056", "600", "300"]
    drive(driver, donor, *region, "--out", str(world))
    drive(driver, donor, *region, "--models", "--out", str(both))
    kept = brushes_in_door(world.read_text(encoding="ascii", errors="replace"))
    lost = brushes_in_door(both.read_text(encoding="ascii", errors="replace"))
    check("HollowWorld leaves the door's own brushes standing", kept >= 1,
          f"{kept} brushes in the func_door")
    check("and Hollow, which the graft uses, takes them", lost != kept,
          f"{lost} brushes after the model-aware hollow")

    failures = FAILED
    cases = CASES
    if not a.skip_red:
        print("controlled RED")
        cases += 1
        failures += red(a.work, fixture)

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


def red(work: Path, fixture: Path) -> int:
    """The void made indistinguishable from a wall.

    real_solid answers "is this point somewhere the map actually is" and the
    whole safety of the operator is in it. Drop the brush half of the question
    and every point the tree calls solid looks like a wall, so the region grows
    through the shell and out into nothing. The compiler is what says so.
    """
    tree = work / "red_void"
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True)
    for sub in ("inc", "src", "tools"):
        shutil.copytree(REPO / sub, tree / sub)

    p = tree / "src" / "mapgen" / "mapgen_graft.c"
    t = p.read_text(encoding="utf-8")
    old = """    if (!(MapGenBsp_PointContents(bsp, p) & MAPGEN_CONTENTS_SOLID))
        return true;   /* not solid at all: somewhere inside the map */"""
    if t.count(old) != 1:
        print("  FAIL  RED the void looks like a wall: cannot mutate")
        return 1
    p.write_text(t.replace(old, old + "\n    return true;", 1),
                 encoding="utf-8")

    driver = build_driver(tree, tree)
    donor = fixture.with_suffix(".bsp")
    listing = drive(driver, donor, "--list")
    first = re.search(r"edit (\d+)\s+recut", listing)
    if not first:
        print("  FAIL  RED the void looks like a wall: no recut offered")
        return 1
    cut = tree / "red.map"
    drive(driver, donor, "--apply", first.group(1), "--out", str(cut))
    log = compile_map(cut)
    ok = leaked(log)
    print(("  PASS  " if ok else "  FAIL  ")
          + "RED the void looks like a wall: the compiled map LEAKS"
          + f"  -- {'leaked' if ok else 'no leak, which the guard cannot see'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
