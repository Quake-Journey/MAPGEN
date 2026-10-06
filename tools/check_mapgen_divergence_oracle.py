"""What the divergence oracle counts, and what it must not.

Codex, 2026-09-06 section 3, on the instrument rather than on the anchors:

    Before calling an operator intrinsically ineffective, distinguish:
      - no compiled architectural change;
      - real change smaller than one rounded permille;
      - a change inside the same 32-unit cells;
      - changed spatial structure with the same aggregate score;
      - a route change omitted by the cheap per-edit measurement;
      - compiler subdivision/numeric noise changing a representation.

    Prove unchanged/reordered/subdivided-equivalent geometry stays zero and
    that small real geometric/route edits are distinguishable.
    Cosmetic/item/spawn-only changes remain zero.

So this builds one small two-room map, compiles a dozen variants of it with
the pinned compiler, and measures each against the base. Nothing here is
argued from the source: every number is the oracle's own output on real BSPs,
and every changed cell can be listed.

    python tools/check_mapgen_divergence_oracle.py [--work DIR] [--skip-red]

Codex, 2026-09-07, on the motif axis after it charged 322 permille of a whole
map to one staircase becoming a lift, ruled that the axis must bind to the
construction that actually stands somewhere, and listed what a repaired schema
has to be shown to do. Section 6, in his words:

    a localized mover edit cannot relabel untouched room support as changed,
    including a large room and an air-count bucket boundary; an equal-count
    spatial relocation and a real whole-bundle change are detected; real
    construction/route change without static-solid change remains observable;
    segmentation ID/split bookkeeping does not fabricate changes;
    repeated/overlapping edits and an exact undo have correct deduplication;
    resource truncation produces incomplete, never a complete zero/pass;
    per-cell identities explain each axis.

The fixture is one two-room map with a corridor and TWO doors in series - two
constructions, so that "which one is it" is a question the map can ask.

    self       the same file twice                      must be zero
    respell    the same brushes, reordered, and every
               plane written from a different three of
               its own points                           must be zero
    chop       the same .map compiled with -chop 64, so
               the compiler cuts every face into more
               pieces                                   must be zero
    texture    every surface repainted                  must be zero
    item       a pickup carried to the other room       must be zero
    spawn      a deathmatch start moved                 must be zero
    order      the same two doors, written to the .map
               in the other order                       must be zero
    nudge      one wall segment moved one cell          must NOT be zero
    swap       the two doors exchange travels, so each
               place holds a different construction and
               the map holds the same two               must NOT be zero
    travel     the near door's lip changed, so it stops
               short: the same brushes, a different
               swept extent                             must NOT be zero
    both       nudge and travel in one map               the union of the two,
                                                        counted once each
    locked     the near door given a targetname nothing
               triggers, so it never opens               a changed
                                                        construction with no
                                                        static change at all

`locked` is Codex's "real construction/route change without static-solid
change remains observable". Before the repair it was invisible without the
route axis; the cheap per-edit score reported a map identical to the one it
came from, and the map was not identical - a player could no longer get to
half of it. It is now visible on the motif axis while solid, surface and floor
all stay exactly zero, which is the shape of the claim.

The cheap score still may not conclude NO_EFFECT, and the reason is now
structural rather than anecdotal: with routes off the result says
`complete NO`, and an incomplete measurement authorises nothing.

Then the controlled REDs, because a green oracle proves nothing until the
check is shown to be able to go red:

    counting spawns and items as constructions again must break the item and
    spawn cases - that is the exclusion TZ 14.0.1 requires;

    marking faces by their EDGES instead of their interiors must break the
    subdivision case - the discriminating proof for rasterise_faces;

    marking a construction only where it is PARKED must break the swept
    extent, which is what makes a lift the shaft rather than the slab;

    folding the entity ordinal into a construction's identity must break the
    order case - an entity renumbered is not a map changed;

    marking a construction over its whole ROOM, which is what the axis used
    to do, must break the locality case - one door may not relabel the room
    it stands in.

And one controlled resource case: the route budget cut to a number the
fixture cannot fit, which must come back INCOMPLETE and never as a pass.
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260906"
                    r"\divergence_oracle")

GATE_SRC = [
    "tools/mapgen_divergence_gate.c",
    "src/mapgen/mapgen_divergence.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_reach.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
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
    if ok:
        print(f"  PASS  {name}" + (f"  -- {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    return ok


# ---- the fixture -----------------------------------------------------------
#
# Two rooms and a corridor with a door in it. Small on purpose: every variant
# is a real compile, and a guard nobody runs proves nothing.

AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"
WALL = "e2u3/blum12_1"
FLOOR = "e2u3/floor1_6"


def box(x0, y0, z0, x1, y1, z1, tex=WALL, rot=0):
    """One axial brush. `rot` writes each plane from a different three of its
    own points - the same plane, a different spelling of it."""
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
        # A rotation of the three points is the same plane with the same
        # winding - which is exactly the point of writing it this way.
        p = f[rot % 3:] + f[:rot % 3]
        out.append(" ".join(f"( {a[0]} {a[1]} {a[2]} )" for a in p) + " " + t)
    out.append("}")
    return "\n".join(out)


def shell(wall_tex: str, floor_tex: str, rot: int, nudged: bool) -> list[str]:
    """The rooms. `nudged` moves one segment of the middle wall by one cell,
    which is the smallest edit this lattice can see at all."""
    south_wall_y1 = 176 - 32 if nudged else 176
    b = [
        box(-32, -32, -32, 1184, 480, 0, floor_tex, rot),      # floor
        box(-32, -32, 192, 1184, 480, 224, wall_tex, rot),     # ceiling
        box(-32, -32, 0, 0, 480, 192, wall_tex, rot),          # west
        box(1152, -32, 0, 1184, 480, 192, wall_tex, rot),      # east
        box(-32, -32, 0, 1184, 0, 192, wall_tex, rot),         # south
        box(-32, 448, 0, 1184, 480, 192, wall_tex, rot),       # north
        # the wall between the rooms, with a doorway cut out of it
        box(448, -32, 0, 704, south_wall_y1, 192, wall_tex, rot),
        box(448, 272, 0, 704, 480, 192, wall_tex, rot),
        box(448, 176, 128, 704, 272, 192, wall_tex, rot),
    ]
    if nudged:
        # Put the removed slab back somewhere that is NOT where it was, so the
        # map stays sealed and the edit is a moved wall rather than a hole.
        b.append(box(448, 176, 0, 704, 176 + 32, 192, wall_tex, rot))
    return b


def entity(classname: str, **keys) -> str:
    out = ["{", f'"classname" "{classname}"']
    out += [f'"{k}" "{v}"' for k, v in keys.items()]
    out.append("}")
    return "\n".join(out)


# The two doors, in series across the one corridor. Both are 16 units thick
# and both fill the opening, so either one shut is a corridor a player cannot
# walk. They differ in TRAVEL - how far each rises before it stops - which is
# what makes them two constructions rather than one construction twice.
NEAR_DOOR_X = 536
FAR_DOOR_X = 600
NEAR_LIP = 8
FAR_LIP = 64
DOOR_TOP = 128


def door(x0: int, lip: int, locked: bool, rot: int, tex: str) -> str:
    keys = ['"classname" "func_door"', '"angle" "-1"', '"speed" "100"',
            f'"lip" "{lip}"']
    if locked:
        # Nothing in the map names this. A door that waits to be told is a
        # door that never opens, and the corridor behind it is not a way out.
        keys.append('"targetname" "sealed"')
    return "{\n" + "\n".join(keys) + "\n" \
        + box(x0, 176, 0, x0 + 16, 272, DOOR_TOP, tex, rot) + "\n}\n"


def write_map(path: Path, *, wall_tex=WALL, floor_tex=FLOOR, rot=0,
              nudged=False, locked=False, item_in_b=False,
              spawn_in_b=False, swapped=False, near_lip=NEAR_LIP,
              reorder=False) -> None:
    brushes = shell(wall_tex, floor_tex, rot, nudged)
    if rot:
        brushes = list(reversed(brushes))

    lips = (FAR_LIP, NEAR_LIP) if swapped else (near_lip, FAR_LIP)
    doors = [door(NEAR_DOOR_X, lips[0], locked, rot, wall_tex),
             door(FAR_DOOR_X, lips[1], False, rot, wall_tex)]
    if reorder:
        # The same two doors, written the other way round. Nothing about the
        # architecture changed; only the order the entity lump lists them in.
        doors.reverse()

    item = (900, 300, 24) if item_in_b else (300, 300, 24)
    dm = (900, 100, 24) if spawn_in_b else (224, 100, 24)

    text = ["// Game: Quake 2", "// Format: Valve",
            "{", '"classname" "worldspawn"', '"mapversion" "220"',
            "\n".join(brushes), "}",
            entity("info_player_start", origin="224 224 24"),
            entity("info_player_deathmatch", origin=f"{dm[0]} {dm[1]} {dm[2]}"),
            entity("info_player_deathmatch", origin="900 224 24"),
            entity("item_health", origin=f"{item[0]} {item[1]} {item[2]}"),
            entity("light", origin="224 224 150", light="300"),
            entity("light", origin="900 224 150", light="300")] + doors
    path.write_text("\n".join(text) + "\n", encoding="ascii")


VARIANTS = {
    "base":    {},
    "respell": {"rot": 1},
    "texture": {"wall_tex": FLOOR, "floor_tex": WALL},
    "item":    {"item_in_b": True},
    "spawn":   {"spawn_in_b": True},
    "order":   {"reorder": True},
    "nudge":   {"nudged": True},
    "swap":    {"swapped": True},
    "travel":  {"near_lip": FAR_LIP},
    "both":    {"nudged": True, "near_lip": FAR_LIP},
    "locked":  {"locked": True},
}


# ---- running things --------------------------------------------------------

def pinned_threads() -> str:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    return str(pin["thread_policy"]["value"])


def pinned_compiler() -> Path:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler as resolve
    return resolve()[0]


def compile_map(compiler: Path, path: Path, chop: int | None = None) -> str | None:
    argv = [str(compiler), "-bsp", "-threads", pinned_threads()]
    if chop:
        argv += ["-chop", str(chop)]
    argv += ["-moddir", str(GAME), "-basedir", str(GAME), "-gamedir", str(GAME),
             str(path)]
    run = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
    text = run.stdout + run.stderr
    if run.returncode != 0 or "ERROR" in text:
        return "refused: " + text[-300:]
    if "leaked" in text.lower():
        return "leaked"
    return None


def build_gate(tree: Path, out: Path) -> Path:
    exe = out / "divergence_gate.exe"
    if exe.exists():
        exe.unlink()
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"),
         "-I" + str(tree / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(tree / f) for f in GATE_SRC] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the divergence gate")
    return exe


TOGETHER = re.compile(r"together\s+(\d+) permille\s+\((\d+) of (\d+) cells")
AXIS = re.compile(r"^\s+(solid|surface|floors|routes|motifs)\s+(\d+) permille"
                  r"\s+\((\d+) of (\d+)(?: cells)?\)", re.M)
COMPLETE = re.compile(r"complete\s+(yes|NO)\s+\(routes truncated (yes|YES|no),"
                      r" faces skipped (\d+)\)")
CELL = re.compile(r"^cell (-?\d+) (-?\d+) (-?\d+)\s+at \S+ \S+ \S+\s+(\S+)"
                  r"\s+donor (\w+)/(\w+)\s+candidate (\w+)/(\w+)", re.M)

# The axis names the gate prints, mapped to the names used here.
AXIS_NAME = {"solid": "solid", "surface": "surface", "floors": "vertical",
             "routes": "route", "motifs": "motif"}


def measure(gate: Path, a: Path, b: Path, routes: bool,
            cells: Path | None = None) -> dict:
    """One measurement, everything it said, and optionally every cell it
    counted as changed."""
    argv = [str(gate), str(a), str(b), "100"] + (["--routes"] if routes else [])
    if cells:
        argv += ["--cells", str(cells)]
    run = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
    text = run.stdout + run.stderr
    m = TOGETHER.search(text)
    if not m:
        return {"error": text[-400:]}
    got = {"permille": int(m.group(1)), "changed": int(m.group(2)),
           "cells": int(m.group(3)),
           "routes_measured": "routes    NOT MEASURED" not in text}
    for axis in AXIS.finditer(text):
        name = AXIS_NAME[axis.group(1)]
        got[name + "_permille"] = int(axis.group(2))
        got[name + "_changed"] = int(axis.group(3))
        got[name + "_cells"] = int(axis.group(4))
    c = COMPLETE.search(text)
    if c:
        got["complete"] = c.group(1) == "yes"
        got["truncated"] = c.group(2).lower() == "yes"
        got["skipped"] = int(c.group(3))
    if cells and cells.exists():
        got["cell_set"] = cell_set(cells)
    return got


def cell_set(dump: Path) -> dict[tuple[int, int, int], str]:
    """The witness file, as {cell: the axes that moved there}."""
    out = {}
    for m in CELL.finditer(dump.read_text(encoding="utf-8", errors="replace")):
        out[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = m.group(4)
    return out


# ---- the run ---------------------------------------------------------------

def build_fixtures(work: Path, compiler: Path) -> dict[str, Path] | None:
    maps = work / "maps"
    maps.mkdir(parents=True, exist_ok=True)
    bsps: dict[str, Path] = {}
    for name, opts in VARIANTS.items():
        m = maps / f"{name}.map"
        write_map(m, **opts)
        why = compile_map(compiler, m)
        if why:
            check(f"the {name} fixture compiles", False, why)
            return None
        bsps[name] = m.with_suffix(".bsp")

    # The subdivision variant is the SAME .map through a different chop, so
    # nothing about the geometry can differ - only how the compiler cut it up.
    chop = maps / "chop.map"
    shutil.copy2(maps / "base.map", chop)
    why = compile_map(compiler, chop, chop=64)
    if why:
        check("the chop fixture compiles", False, why)
        return None
    bsps["chop"] = chop.with_suffix(".bsp")
    check("every fixture compiled and sealed", True,
          f"{len(bsps)} variants")
    return bsps


def faces_in(bsp: Path) -> int:
    import struct
    raw = bsp.read_bytes()
    off, ln = struct.unpack_from("<ii", raw, 8 + 6 * 8)
    return ln // 20


def run_cases(gate: Path, bsps: dict[str, Path], work: Path,
              log: bool = True) -> dict:
    """Every case. Returns the raw measurements so a RED can read them."""
    base = bsps["base"]
    got: dict[str, dict] = {}
    dumps = work / "cells"
    dumps.mkdir(parents=True, exist_ok=True)

    got["self"] = measure(gate, base, base, routes=True)
    if log:
        check("the same map against itself is zero",
              got["self"].get("changed") == 0, str(got["self"]))

    for name, why in (("respell", "reordered brushes and re-spelled planes"),
                      ("chop", "a different face subdivision"),
                      ("texture", "every surface repainted"),
                      ("item", "a pickup carried to the other room"),
                      ("spawn", "a deathmatch start moved"),
                      ("order", "the same two doors written in the other"
                                " order")):
        got[name] = measure(gate, base, bsps[name], routes=True)
        if log:
            check(f"{why} is zero",
                  got[name].get("changed") == 0, str(got[name]))

    got["nudge"] = measure(gate, base, bsps["nudge"], routes=True,
                           cells=dumps / "nudge.txt")
    if log:
        check("one wall moved by one cell is NOT zero",
              (got["nudge"].get("changed") or 0) > 0, str(got["nudge"]))
        # The old axis hashed a room's air count to the nearest doubling, so a
        # wall that moved could flip a whole room's motif by arithmetic. A
        # wall is not a construction and may not touch this axis at all.
        check("a wall moved changes solid and floors and NOT the motif axis"
              " - an air count is not architecture",
              got["nudge"].get("motif_changed") == 0
              and (got["nudge"].get("solid_changed") or 0) > 0,
              f"solid {got['nudge'].get('solid_changed')},"
              f" motif {got['nudge'].get('motif_changed')}")

    # Two constructions exchanging travels: the same two doors, the same two
    # places, a different construction standing in each.
    got["swap"] = measure(gate, base, bsps["swap"], routes=True)
    if log:
        check("two doors that exchange travels are NOT zero - a construction"
              " is identified by what it is, and each place now holds the"
              " other one",
              (got["swap"].get("motif_changed") or 0) > 0, str(got["swap"]))

    # A construction whose swept extent changed, with every brush where it was.
    got["travel"] = measure(gate, base, bsps["travel"], routes=True,
                            cells=dumps / "travel.txt")
    if log:
        check("a door that stops short is NOT zero - the extent it governs is"
              " part of what it is",
              (got["travel"].get("motif_changed") or 0) > 0,
              str(got["travel"]))
        # Marking it where it is PARKED would find the same closed box in both
        # maps. What differs is above the closed door, in the shaft it used to
        # sweep and now does not.
        above = [c for c in (got["travel"].get("cell_set") or {})
                 if c[2] * 32 > DOOR_TOP]
        check("and what changed is ABOVE the closed door - the swept extent,"
              " not the slab",
              len(above) > 0, f"{len(above)} cells above z={DOOR_TOP}")

    got["locked_routes"] = measure(gate, base, bsps["locked"], routes=True)
    got["locked_cheap"] = measure(gate, base, bsps["locked"], routes=False,
                                  cells=dumps / "locked.txt")
    if log:
        check("a door that never opens is NOT zero when routes are measured",
              (got["locked_routes"].get("route_changed") or 0) > 0,
              str(got["locked_routes"]))
        # Codex 2026-09-07 section 6: "real construction/route change without
        # static-solid change remains observable". Not one plane moved.
        static = sum(got["locked_cheap"].get(a + "_changed") or 0
                     for a in ("solid", "surface", "vertical"))
        check("and the cheap route-free score sees it too, with solid,"
              " surface and floors all untouched",
              (got["locked_cheap"].get("motif_changed") or 0) > 0
              and static == 0,
              f"motif {got['locked_cheap'].get('motif_changed')},"
              f" static {static}")
        # And what it may still not do is conclude anything final, because
        # with routes off the measurement says so itself.
        check("the cheap score is INCOMPLETE by its own account - which is"
              " why it may not conclude NO_EFFECT",
              got["locked_cheap"].get("complete") is False
              and got["locked_routes"].get("complete") is True,
              f"cheap complete={got['locked_cheap'].get('complete')},"
              f" full complete={got['locked_routes'].get('complete')}")
        # One door, one room: the cells it changed are its own. The axis this
        # replaced would have relabelled every cell of the room it stands in.
        locality_case(got["locked_cheap"], got["self"])

    # Two edits at once, one of which overlaps the other's cells.
    got["both"] = measure(gate, base, bsps["both"], routes=True,
                          cells=dumps / "both.txt")
    got["undo"] = measure(gate, bsps["nudge"], base, routes=True,
                          cells=dumps / "undo.txt")
    if log:
        union_case(got)
        # An edit and its exact undo touch the same architecture. The score
        # need not be identical - the solid axis is bound to the DONOR, and
        # the two runs have different donors - but the cells must be.
        there = set(got["nudge"].get("cell_set") or {})
        back = set(got["undo"].get("cell_set") or {})
        check("an edit and its exact undo report the same cells",
              bool(there) and there == back,
              f"{len(there)} out, {len(back)} back,"
              f" {len(there ^ back)} disagree")
    return got


def locality_case(locked: dict, whole: dict) -> None:
    """One door changed - so the door's own neighbourhood changed.

    The axis this replaced wrote one room hash into every cell of its room, so
    a door gaining a targetname turned 45% of q2dm1 into changed architecture.
    The bound here is the door's own swept box grown by a cell: the near door
    is 16 units of x, 96 of y, and rises 120, which is at most 3 x 5 x 9 cells
    with the growth. Anything outside that is a cell the edit did not touch.
    """
    cells = locked.get("cell_set") or {}
    lo = (NEAR_DOOR_X // 32 - 1, 176 // 32 - 1, -1)
    hi = ((NEAR_DOOR_X + 16) // 32 + 1, 272 // 32 + 1,
          (DOOR_TOP + DOOR_TOP - NEAR_LIP) // 32 + 1)
    outside = [c for c in cells
               if not all(lo[i] <= c[i] <= hi[i] for i in range(3))]
    check("one door relabels its own extent and nothing else - not the room"
          " it stands in",
          bool(cells) and not outside,
          f"{len(cells)} changed cells, {len(outside)} outside the door's own"
          f" box, room holds {whole.get('cells')} cells")


def union_case(got: dict) -> None:
    """Two edits in one map are their union, counted once each.

    Codex asked for "repeated/overlapping edits and an exact undo have correct
    deduplication". These two overlap: the wall segment the nudge moves runs
    through the cells the near door's shaft occupies. If the metric summed
    instead of unioning, the overlap would be counted twice and the total
    would exceed the union.
    """
    a = set((got["nudge"].get("cell_set") or {}))
    b = set((got["travel"].get("cell_set") or {}))
    c = set((got["both"].get("cell_set") or {}))
    if not a or not b or not c:
        check("two edits at once are the union of the two", False,
              "no cell dump")
        return
    missing = (a | b) - c
    extra = c - (a | b)
    check("two edits at once are exactly the union of the two, counted once"
          " each",
          not missing and not extra,
          f"{len(a)} + {len(b)} -> {len(c)}, overlap {len(a & b)},"
          f" missing {len(missing)}, unexplained {len(extra)}")


def rounding_case(got: dict) -> None:
    """A real change smaller than one rounded permille.

    Not a fixture: arithmetic on the fixture's own cell count. One changed
    cell in this map is 1000/N permille, and the aggregate is rounded to an
    integer before anything compares it, so below 2000 changed cells per
    permille a real edit is invisible to the score and visible in the count.
    """
    cells = got["self"].get("cells") or 0
    one_cell_permille = (1000 * 1 + cells // 2) // cells if cells else 0
    check("one changed cell of this map rounds to zero permille - so the raw"
          " count is the only thing that can see it",
          cells > 0 and one_cell_permille == 0,
          f"{cells} cells, one of them is {1000 / cells:.4f} permille"
          if cells else "no cells")


# ---- controlled RED --------------------------------------------------------

DIVERGENCE_C = "src/mapgen/mapgen_divergence.c"

# Where every construction-axis mutation goes in: the end of the ladder pass,
# just before rasterise_motifs returns.
MOTIF_TAIL = """            l->flags[at] |= CELL_MOTIF;
            l->motif[at] += 0x9E3779B9u;
        }

    return true;
}"""

MOTIF_INCLUDES = '#include "common/mapgen_movers.h"'
BUNDLE_INCLUDES = ('#include "common/mapgen_bundle.h"\n'
                   '#include "common/mapgen_movers.h"\n'
                   '#include "common/mapgen_rooms.h"')


def changed(key: str):
    """The commonest RED expectation: this case stops being zero."""
    return lambda g: (g[key].get("changed") or 0) > 0


def unchanged(key: str):
    """The other one: this case stops being able to see its edit."""
    return lambda g: (g[key].get("motif_changed") or 0) == 0


REDS = [
    ("spawns and items are constructions again",
     DIVERGENCE_C,
     MOTIF_TAIL,
     """            l->flags[at] |= CELL_MOTIF;
            l->motif[at] += 0x9E3779B9u;
        }

    /* RED: a pickup and a spawn point marked where they stand, which is what
       TZ 14.0.1 forbids and what the old signature did by counting them. */
    {
        mapgen_geometry_t *geometry = NULL;
        mapgen_rooms_t *rooms = NULL;
        mapgen_bundle_set_t *set = NULL;
        if (MapGenGeometry_FromBsp(bsp, &geometry) == MAPGEN_GEOMETRY_OK
            && MapGenRooms_Find(bsp, 64.0f, MAPGEN_ROOMS_PERSISTENCE, &rooms)
               == MAPGEN_ROOMS_OK
            && MapGenBundle_Survey(bsp, geometry, rooms, &set)
               == MAPGEN_BUNDLE_OK) {
            for (uint32_t r = 0; r < MapGenBundleSet_Count(set); r++) {
                const mapgen_bundle_t *bu = MapGenBundleSet_At(set, r);
                for (uint32_t i = 0; i < MapGenBundle_NumAnchors(bu); i++) {
                    const mapgen_bundle_anchor_t *an =
                        MapGenBundle_Anchor(bu, i);
                    if (an->kind != MAPGEN_ANCHOR_ITEM
                        && an->kind != MAPGEN_ANCHOR_SPAWN)
                        continue;
                    const int32_t c[3] = { floor_div(an->origin[0]),
                                           floor_div(an->origin[1]),
                                           floor_div(an->origin[2]) };
                    const int64_t at2 = lattice_index(l, c);
                    if (at2 < 0)
                        continue;
                    l->flags[at2] |= CELL_MOTIF;
                    l->motif[at2] += 0x5BF03635u + (uint32_t)an->kind;
                }
            }
        }
        MapGenBundleSet_Free(set);
        MapGenRooms_Free(rooms);
        MapGenGeometry_Free(geometry);
    }

    return true;
}""",
     (("item", changed("item")), ("spawn", changed("spawn"))),
     MOTIF_INCLUDES, BUNDLE_INCLUDES),

    ("a construction is marked where it is parked, not over its travel",
     DIVERGENCE_C,
     "        for (uint32_t s = 0; s < mv->num_stops"
     " && s < MAPGEN_MOVER_STOPS; s++) {",
     "        for (uint32_t s = 0; s < 1u; s++) {",
     # The travel case can still see the identity change; what it loses is
     # the shaft. Nothing may then differ above the closed door.
     (("travel above the closed door",
       lambda g: not [c for c in (g["travel"].get("cell_set") or {})
                      if c[2] * 32 > DOOR_TOP]),),
     None, None),

    ("a construction's identity includes its entity ordinal",
     DIVERGENCE_C,
     "        const uint32_t value = construction_value(mv);",
     "        const uint32_t value = construction_value(mv)"
     " + i * 2654435761u;",
     (("order", changed("order")),),
     None, None),

    ("a construction is marked over its whole room, as the old axis did",
     DIVERGENCE_C,
     """        for (uint32_t s = 0; s < mv->num_stops && s < MAPGEN_MOVER_STOPS; s++) {
            float lo[3], hi[3];
            for (int a = 0; a < 3; a++) {
                lo[a] = mv->mins[a] + mv->stop[s][a];
                hi[a] = mv->maxs[a] + mv->stop[s][a];
            }
            mark_box(l, lo, hi, value);
        }""",
     """        /* RED: the room it stands in, which is what turned one lift
           into 322 permille of q2dm1. */
        {
            float lo[3], hi[3];
            for (int a = 0; a < 3; a++) {
                lo[a] = (float)l->mins[a] * MAPGEN_DIVERGENCE_CELL;
                hi[a] = (float)(l->mins[a] + l->size[a] - 1)
                      * MAPGEN_DIVERGENCE_CELL;
            }
            mark_box(l, lo, hi, value);
        }""",
     # The bound the locality case holds the axis to is the door's own box;
     # a whole-map mark cannot stay inside it.
     (("locality",
       lambda g: bool([c for c in (g["locked_cheap"].get("cell_set") or {})
                       if not (NEAR_DOOR_X // 32 - 1 <= c[0]
                               <= (NEAR_DOOR_X + 16) // 32 + 1)])),),
     None, None),

    # The face axis, back to what it did before this session: sample the
    # triangle fan and mark every cell a sample landed in. That is the
    # implementation whose invariance the comment CLAIMED, and the chop
    # fixture is what disproved it - 25 permille on the surface axis for a
    # map with identical geometry. Restoring it must reopen exactly that.
    ("faces are marked by being touched instead of by area",
     "src/mapgen/mapgen_divergence.c",
     """        for (int32_t cz = lo[2]; cz <= hi[2]; cz++) {
          for (int32_t cy = lo[1]; cy <= hi[1]; cy++) {
            for (int32_t cx = lo[0]; cx <= hi[0]; cx++) {
                const int32_t c[3] = { cx, cy, cz };
                if (lattice_index(l, c) < 0)
                    continue;
                const float area = clipped_area(points, n, c);
                if (area > 0.0f)
                    add_area(l, c, area, (bit & CELL_VERTICAL) != 0);
            }
          }
        }""",
     """        (void)lo; (void)hi;
        for (uint32_t k = 1; k + 1 < n; k++) {
            float e1[3], e2[3];
            float len1 = 0.0f, len2 = 0.0f;
            for (int i = 0; i < 3; i++) {
                e1[i] = points[k][i] - points[0][i];
                e2[i] = points[k + 1][i] - points[0][i];
                len1 += e1[i] * e1[i];
                len2 += e2[i] * e2[i];
            }
            const float longest = sqrtf(len1 > len2 ? len1 : len2);
            int steps = (int)(longest / (MAPGEN_DIVERGENCE_CELL * 0.4f)) + 1;
            if (steps > 512)
                steps = 512;
            for (int a = 0; a <= steps; a++) {
                for (int b = 0; a + b <= steps; b++) {
                    const float u = (float)a / (float)steps;
                    const float v = (float)b / (float)steps;
                    const float p[3] = {
                        points[0][0] + e1[0] * u + e2[0] * v,
                        points[0][1] + e1[1] * u + e2[1] * v,
                        points[0][2] + e1[2] * u + e2[2] * v,
                    };
                    const int32_t c[3] = { floor_div(p[0]), floor_div(p[1]),
                                           floor_div(p[2]) };
                    add_area(l, c, CELL_AREA, (bit & CELL_VERTICAL) != 0);
                }
            }
        }""",
     (("chop", changed("chop")), ("respell", changed("respell"))),
     None, None),
]


def mutated_tree(work: Path, name: str, edits: list[tuple[str, str, str]]
                 ) -> Path | None:
    """A copy of the tree with exact text substitutions applied to it.

    Every substitution must match exactly once. A mutation that no longer
    finds its target is a mutation that proves nothing, and it is reported as
    a failure rather than skipped - that is how the last one went stale.
    """
    tree = work / "red" / re.sub(r"\W+", "_", name)
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True)
    for sub in ("inc", "src", "tools"):
        shutil.copytree(REPO / sub, tree / sub)
    for rel, old, new in edits:
        p = tree / rel
        t = p.read_text(encoding="utf-8")
        if t.count(old) != 1:
            print(f"  FAIL  {name}: cannot mutate {rel}"
                  f" ({t.count(old)} matches)")
            return None
        p.write_text(t.replace(old, new, 1), encoding="utf-8")
    return tree


def red(work: Path, bsps: dict[str, Path]) -> int:
    failures = 0
    for name, rel, old, new, breaks, old2, new2 in REDS:
        edits = [(rel, old, new)]
        if old2:
            edits.append((rel, old2, new2))
        tree = mutated_tree(work, name, edits)
        if not tree:
            failures += len(breaks)
            continue

        gate = build_gate(tree, tree)
        got = run_cases(gate, bsps, tree, log=False)
        for label, defect_visible in breaks:
            ok = defect_visible(got)
            print(f"  {'PASS' if ok else 'FAIL'}  RED {name}: the {label} case"
                  f" goes red")
            failures += 0 if ok else 1
    return failures


def truncation_case(work: Path, bsps: dict[str, Path]) -> int:
    """A route search that ran out must not come back as a measurement.

    Codex, 2026-09-07 section 5: "an exhausted/failed required axis must remain
    incomplete and cannot authorize a final target, NO_EFFECT, or publication
    verdict". This is that, with the budget cut to a number the fixture cannot
    fit - a controlled resource limit, not a mock. The measurement still runs;
    what it may not do is call itself complete.
    """
    tree = mutated_tree(work, "route budget of 64", [(
        DIVERGENCE_C,
        "        const bool ok = rasterise_routes(donor, &a, 40000, &truncated)"
        "\n                     && rasterise_routes(candidate, &b, 40000,"
        " &truncated);",
        "        const bool ok = rasterise_routes(donor, &a, 64, &truncated)"
        "\n                     && rasterise_routes(candidate, &b, 64,"
        " &truncated);")])
    if not tree:
        check("a route search that ran out of budget leaves the result"
              " INCOMPLETE", False, "the budget could not be cut")
        return
    gate = build_gate(tree, tree)
    starved = measure(gate, bsps["base"], bsps["locked"], routes=True)
    check("a route search that ran out of budget leaves the result INCOMPLETE",
          starved.get("truncated") is True
          and starved.get("complete") is False
          and starved.get("routes_measured") is False,
          str({k: starved.get(k) for k in
               ("truncated", "complete", "routes_measured", "permille")}))
    # And the trap it must not fall into: a truncated search that marked no
    # route cells looks exactly like a map nobody changed.
    check("and it is not reported as a clean zero",
          starved.get("complete") is not True,
          f"aggregate {starved.get('permille')} permille,"
          f" complete {starved.get('complete')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    compiler = pinned_compiler()
    if not compiler.exists():
        print(f"  the pinned compiler is not at {compiler}")
        return 2

    print("fixtures")
    bsps = build_fixtures(a.work, compiler)
    if not bsps:
        print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
        return 1
    # The subdivision case is only a case if the subdivision actually happened.
    check("the -chop build really did cut the faces differently",
          faces_in(bsps["chop"]) != faces_in(bsps["base"]),
          f"{faces_in(bsps['base'])} faces vs {faces_in(bsps['chop'])}")

    print("the oracle")
    gate = build_gate(REPO, a.work)
    got = run_cases(gate, bsps, a.work)
    rounding_case(got)

    reds = 0
    extra = 0
    if not a.skip_red:
        print("controlled RED")
        reds = red(a.work, bsps)
        extra = sum(len(e[4]) for e in REDS)
        print("controlled resource limit")
        # Counts itself: every assertion in here goes through check().
        truncation_case(a.work, bsps)

    cases = CASES + extra
    failures = FAILED + reds

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
