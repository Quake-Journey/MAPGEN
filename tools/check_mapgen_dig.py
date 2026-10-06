"""A DIG: a passage through the rock between two floors the donor already has,
with stairs or a lift in it.

The PO asked for this family with a verb on 2026-09-11 - «Туннель под ареной - что
мешает прорыть с арены в туннель лестницу или лифт? Прорыть по стенке от верхнего
рокета вниз к рейлгану крутой тоннель, расставить там лестницы/лифты» - and an
hour later said what the three examples are FOR: «это просто самые очевидные
примеры... реально есть на много порядков больше вариантов, что и где можно делать
с картой, это же форк!». So the three places he named are the first three
CANDIDATES of a general enumeration, and this guard's first case is that they are
in the list with their ratios.

    python tools/check_mapgen_dig.py [--work DIR] [--quick]

Five cases and a controlled RED, every one on a real artifact:

  1 FIXTURE, rock between.  Two rooms, floors 256 apart, solid rock between them.
                            One dig is offered, applied, compiles SEALED, adds no
                            surface fault the donor did not have, and a PLAYER
                            HULL walks it end to end - every tread at most 18
                            above the one before, headroom all the way.
  2 FIXTURE, void between.  The same two rooms with NOTHING between them but the
                            space outside both. The dig's SHELL is the only thing
                            that can close that, and the map must still compile
                            sealed. This is the case that says what the shell is
                            for.
  3 FIXTURE, a third room.  A room in the way. The dig is refused AT THE PLAN with
                            the coordinates of the break, and no compile is spent.
  4 q2dm1, the PO's three.  Each of his three examples is followed through every
                            stage of the plan by name, and the ledger says which
                            stage accepted or refused it - with coordinates. At
                            least the first is accepted and applied through the
                            real transaction path at one seed. Every passage
                            dealt at seed 1 is a WAY on the map its deal
                            compiles, and on that map the game frees no pickup
                            at spawn and no lift runs into a spawn point - asked
                            of the transaction's own oracle (ledger row 311).
  5 The lift is ALIVE.      A `func_plat` in a delivered map is an edict the stock
                            game keeps in deathmatch, proved the way the glass is:
                            a hidden dedicated server, its own MVD gamestate, and
                            no window on the PO's screen ever.

  6 q2dm1, halls.           At seed 1020 the long tunnels get HALLS - a cell grown
                            into a room where the rock round it is proved (ledger
                            row 310) - and every hall's box with the shell round
                            it is rock in the donor's own BSP - its tree walked
                            with the box here (row 311), not taken from the
                            plan; at 384 wide the proof refuses cells that would
                            break into space; and no hall reaches into another
                            segment of its passage (row 318).

  RED  Take the SHELL pass away (`--digpass`, the module's own test seam) and case
       2 must stop sealing. A shell that is not what seals the void is not a shell,
       and a guard that cannot show that is a guard that asserts a constant.
  7 q2dm1, annexes.         At seed 1020 the plan deals ANNEX rooms - a room of
                            the map's own size behind a wall of a room q2dm1
                            has, entered by a doorway cut through that wall and
                            holding a pickup moved in from that room (ledger row
                            315) - and every room with its shell and every
                            doorway is rock in the donor's own tree, the place
                            each opens off is standing air, each moved pickup is
                            the donor's own and stands inside its room, and no
                            annex meets another or a passage; and at seed 42
                            WINGS join two rooms by a link (row 324) - each link
                            touches both its rooms and is rock, and no segment
                            of a wing meets another of its own. Rows 377-379:
                            every annex holds a pickup worth the walk by the
                            generator's own table; one annex applied alone,
                            with a swap of its pickup for a lesser one staged,
                            compiles to a room with a dais of two tiers and
                            trim bands on every wall, and still holds its
                            pickup - the swap declined.

  RED  Take the hall's proof out, in a disposable sandbox, and at 384 wide a
       hall's box meets air.
  RED  Take the annex's proof out, in a disposable sandbox, and at 1024 by 1024
       by 320 an annex's room meets air.
  RED  Put a wing's link 64 into its near room, in a disposable sandbox, and a
       link no longer touches both its rooms and meets a segment of its own
       wing (row 325: on q2dm1 the link's rock proof never refuses a link).
  RED  Take the annex's worth rule out, in a disposable sandbox, and an annex
       holds a pickup worth less than the walk (row 379).
  RED  Take the room's pattern and the swap's refusal out, in one disposable
       sandbox - two independent questions of one staged map - and the room
       has no dais and no bands, and holds the lesser pickup (row 379).
  8 q2dm1, storeys.         At seed 1020 the plan deals a room of two STOREYS
                            (ledger row 327) - a hall entered from a place
                            below, a terrace along the wall of a place above and
                            a flight up to it along a side wall, both inside the
                            room - its dig of five segments found; the room with
                            16 round it is rock in the donor's tree; each
                            doorway touches the room's wall from outside on its
                            floor; the terrace runs along the upper doorway's
                            wall and the flight from the room's floor to the
                            terrace's edge, treads no higher than 18 and no
                            shallower than 24; the lower doorway, 64 into the
                            room, meets neither; no two segments meet but the
                            room and what it holds. On the map case 4 compiles
                            the terrace is solid down to the room's floor and no
                            rock hangs over the flight.
  RED  Take out the storey dealt before the halls of 768 (row 332), in a
       disposable sandbox, and at seed 1020 no storey is dealt.
  RED  Lay the flight on the low side wall without asking the lower doorway, in
       a disposable sandbox, and the doorway opens into the flight (row 328: on
       q2dm1 the rule that each doorway ends on the room's wall never changes a
       plan).
  RED  Revert the two FILL rules of an inner segment, in a disposable sandbox,
       and the storey compiled alone has a terrace that is a slab and rock over
       its flight.
  RED  Put row 310's proof back - voxel centres only, no walk of the tree - and
       at 384 wide a hall kept beside a corridor meets air.
  RED  Grow a landing hall along its run again, in a disposable sandbox, and a
       hall reaches into the next segment of its passage.
  RED  Take the plan's lift refusal out, in a disposable sandbox, and the map
       its deal compiles frees a pickup at spawn or blocks a spawn point.
  RED  Take the treads' rule out (row 333), in a disposable sandbox, and at
       seed 1 the map its deal compiles loses a pickup under a flight.

Nothing here opens a window. `check_mapgen_glass_alive.py` owns the hidden
dedicated launch and this guard calls it.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260917\dig_gate")
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")

sys.path.insert(0, str(REPO / "tools"))
from check_mapgen_recut import build_driver          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"
SKY_AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 4 0"
WALL = "e2u3/blum12_1"
ROCK = "e2u3/rocks19_1"
FLOOR = "e2u3/floor1_6"
SKY = "e2u3/sky1"
T = 32

# The three digs the PO named, as the driver watches them.
#
# Where he actually stood and looked, out of his own demo of the test
# (2026-09-11-00.08-mg_20.dm2) - see the `--powatch` block of the driver.
#
PO_EXAMPLES = {
    "a arena->corridor": ((1430, 870, 448), (1465, 850, 328)),
    "b ledge->room below": ((1330, 300, 640), (1440, 290, 510)),
    "c rocket->railgun": ((1150, -40, 896), (300, -400, 444)),
}

DIG_EDIT = re.compile(r"^  edit (\d+)  dig  (\d+)  (-?\d+) (-?\d+) (-?\d+) ->"
                      r" (-?\d+) (-?\d+) (-?\d+)  (\S+)  (\d+) steps"
                      r"  (\d+) landings  (\d+) lights  ratio (\d+)(.*)$", re.M)
CHAIN = re.compile(r"^  chain (\d+) (\d+)((?: -?\d+){3,})", re.M)
WATCH = re.compile(r"^  WATCHED dig (.+?): (.*)$", re.M)
CAND = re.compile(r"^  dig candidate (\d+): (.*)$", re.M)
TALLY = re.compile(r"^  digs: (.*)$", re.M)
FAULTS = re.compile(r"^surface faults (\d+)$", re.M)
APPLY = re.compile(r"^apply (\d+): (\S+), changed (\S+), (\d+) brushes$", re.M)
HALL = re.compile(r"^  dig hall: segment (\d+) (-?\d+) (-?\d+) (-?\d+) \.\."
                  r" (-?\d+) (-?\d+) (-?\d+)$", re.M)
HALLS = re.compile(r"^  dig halls: (\d+) grown, (\d+) refused, of a passage of"
                   r" (\d+) segments", re.M)

CASES = 0
FAILED = 0


def bsp_tree(path: Path):
    """The world tree of a compiled map: its planes, nodes and leafs lumps and
    model 0's head node."""
    data = path.read_bytes()

    def lump(i: int) -> bytes:
        o, n = struct.unpack_from("<ii", data, 8 + i * 8)
        return data[o:o + n]
    head = struct.unpack_from("<i", lump(13), 36)[0]
    return lump(1), lump(4), lump(8), head


def tree_solid(tree, p) -> bool:
    """Is a point in a SOLID leaf of the world's tree?"""
    planes, nodes, leafs, head = tree
    n = head
    while n >= 0:
        pl, c0, c1 = struct.unpack_from("<iii", nodes, n * 28)
        nx, ny, nz, dist = struct.unpack_from("<ffff", planes, pl * 20)
        n = c0 if nx * p[0] + ny * p[1] + nz * p[2] - dist >= 0 else c1
    return bool(struct.unpack_from("<i", leafs, (-1 - n) * 28)[0] & 1)


def box_in_rock(tree, box: tuple, margin: float = 16.0,
                inset: float = 0.25) -> bool:
    """Is every leaf of the world's tree that the box reaches - grown by
    `margin`, then `inset` in from its faces - SOLID by its own contents?

    Walked, not sampled (ledger row 311): the plan's voxels left half a voxel
    of a hall's shell unasked, and a guard that samples leaves gaps of its own.
    Where a plane cuts the box both sides are walked."""
    planes, nodes, leafs, head = tree
    lo = [box[a] - margin + inset for a in range(3)]
    hi = [box[3 + a] + margin - inset for a in range(3)]
    stack = [head]
    while stack:
        n = stack.pop()
        if n < 0:
            if not struct.unpack_from("<i", leafs, (-1 - n) * 28)[0] & 1:
                return False
            continue
        pl, c0, c1 = struct.unpack_from("<iii", nodes, n * 28)
        nx, ny, nz, dist = struct.unpack_from("<ffff", planes, pl * 20)
        dmin, dmax = -dist, -dist
        for a, v in enumerate((nx, ny, nz)):
            dmin += v * (hi[a] if v < 0 else lo[a])
            dmax += v * (lo[a] if v < 0 else hi[a])
        if dmin >= 0:
            stack.append(c0)
        elif dmax < 0:
            stack.append(c1)
        else:
            stack += [c0, c1]
    return True


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def box(x0, y0, z0, x1, y1, z1, tex, axes=AXES) -> str:
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
        out.append(" ".join(f"( {p[0]} {p[1]} {p[2]} )" for p in f)
                   + f" {tex} {axes}")
    out.append("}")
    return "\n".join(out)


def entity(classname: str, **kv) -> str:
    out = ["{", f'"classname" "{classname}"']
    for k, v in kv.items():
        out.append(f'"{k}" "{v}"')
    out.append("}")
    return "\n".join(out)


# ---- the fixtures ----------------------------------------------------------
#
# Two rooms, one over the other and offset along x, with a closed corridor
# joining them THE LONG WAY ROUND so both are reachable and a dig between them is
# a shortcut rather than the only route. What sits between them is the variable:
#
#   rock   a solid block - the ordinary case, and what q2dm1 mostly is not;
#   void   nothing at all, so the two rooms are separate boxes and the only thing
#          that can seal a passage between them is the dig's own shell;
#   third  a room in the way, which must be refused at the plan.
#
# The long way round is a stair the fixture builds itself, because a dig needs an
# EXISTING route to be a shortcut on and the ratio is measured against it.

UPPER = (0, 0, 512, 640, 512, 768)        # the room you start in
LOWER = (0, 0, 0, 640, 512, 256)          # the room you are going to


def room_shell(room, doorway_z, tex_wall, tex_floor, tex_lid,
               door_lo=160.0, door_hi=256.0, door_tall=128.0):
    """One sealed room with ONE doorway cut in its east wall.

    The doorway is a real GAP - the east wall is built as four pieces around it -
    because a box laid on top of a solid wall is not a hole, and the first version
    of this fixture had two rooms that could not see each other at all.
    """
    x0, y0, z0, x1, y1, z1 = room
    T = 32
    dz0 = doorway_z
    dz1 = doorway_z + door_tall
    return [
        box(x0 - T, y0 - T, z0 - T, x1 + T, y1 + T, z0, tex_floor),
        box(x0 - T, y0 - T, z1, x1 + T, y1 + T, z1 + T, tex_lid),
        box(x0 - T, y0 - T, z0, x0, y1 + T, z1, tex_wall),
        box(x0 - T, y0 - T, z0, x1 + T, y0, z1, tex_wall),
        box(x0 - T, y1, z0, x1 + T, y1 + T, z1, tex_wall),
        # the east wall, in four pieces round the doorway
        box(x1, y0 - T, z0, x1 + T, door_lo, z1, tex_wall),
        box(x1, door_hi, z0, x1 + T, y1 + T, z1, tex_wall),
        box(x1, door_lo, dz1, x1 + T, door_hi, z1, tex_wall),
    ] + ([box(x1, door_lo, z0, x1 + T, door_hi, dz0, tex_wall)]
         if dz0 > z0 else [])


def write_fixture(path: Path, between: str) -> None:
    """Two rooms, one over the other, joined the LONG WAY ROUND by a stair in a
    shaft east of both - so a dig between them is a shortcut on an existing route
    rather than the only route there is, which is what the ratio is measured
    against.

    What lies BETWEEN them is the variable, and it is the whole point of the
    fixture:

      rock   a solid block, the ordinary case;
      void   nothing at all - the two rooms are separate boxes with the outside
             between them, and only the dig's own shell can close a passage
             through that;
      third  a sealed chamber in the way, which must be refused at the plan.
    """
    ux0, uy0, uz0, ux1, uy1, uz1 = UPPER
    lx0, ly0, lz0, lx1, ly1, lz1 = LOWER
    b = room_shell(UPPER, uz0, WALL, FLOOR, ROCK)
    b += room_shell(LOWER, lz0, WALL, FLOOR, ROCK)

    # the long way round: a shaft east of both rooms with a staircase in it
    cx0 = ux1 + T
    cx1 = cx0 + 640
    b += [
        box(cx0, uy0 - T, lz0 - T, cx1 + T, uy1 + T, lz0, FLOOR),
        box(cx0, uy0 - T, uz1, cx1 + T, uy1 + T, uz1 + T, ROCK),
        box(cx0, uy0 - T, lz0, cx1 + T, uy0, uz1, WALL),
        box(cx0, uy1, lz0, cx1 + T, uy1 + T, uz1, WALL),
        box(cx1, uy0 - T, lz0, cx1 + T, uy1 + T, uz1, WALL),
        # and the slab that closes its west side between the two rooms
        box(ux1, uy0 - T, lz1, ux1 + T, uy1 + T, uz0, WALL),
    ]
    # its steps, sixteen at a time from the lower floor to the upper one
    z = lz0
    x = cx0
    while z < uz0 and x + 32 <= cx1:
        b.append(box(x, 160, lz0 - T, x + 32, 256, z + 16, FLOOR))
        z += 16
        x += 32

    if between in ("rock", "third"):
        if between == "rock":
            b.append(box(lx0 - T, ly0 - T, lz1, lx1, ly1 + T, uz0, ROCK))
        else:
            # the same block with a sealed chamber inside it: six slabs round a
            # hole, so the chamber is a real room the dig must not break into
            cz0, cz1 = 320, 448
            hx0, hx1, hy0, hy1 = 192, 448, 160, 352
            b += [
                box(lx0 - T, ly0 - T, lz1, lx1, ly1 + T, cz0, ROCK),
                box(lx0 - T, ly0 - T, cz1, lx1, ly1 + T, uz0, ROCK),
                box(lx0 - T, ly0 - T, cz0, hx0, ly1 + T, cz1, ROCK),
                box(hx1, ly0 - T, cz0, lx1, ly1 + T, cz1, ROCK),
                box(hx0, ly0 - T, cz0, hx1, hy0, cz1, ROCK),
                box(hx0, hy1, cz0, hx1, ly1 + T, cz1, ROCK),
            ]

    text = ["// Game: Quake 2", "// Format: Valve",
            "{", '"classname" "worldspawn"', '"mapversion" "220"',
            "\n".join(b), "}",
            entity("info_player_start", origin="320 256 536"),
            entity("info_player_deathmatch", origin="96 96 536"),
            entity("info_player_deathmatch", origin="320 256 24"),
            entity("info_player_deathmatch", origin="96 96 24"),
            entity("weapon_railgun", origin="544 416 24"),
            entity("weapon_rocketlauncher", origin="544 416 536"),
            entity("item_health", origin="96 416 536"),
            entity("item_health", origin="96 416 24"),
            entity("light", origin="320 256 700", light="500"),
            entity("light", origin="320 256 200", light="500"),
            entity("light", origin="900 208 400", light="400")]
    if between == "third":
        text.append(entity("light", origin="320 256 400", light="300"))
    path.write_text("\n".join(text) + "\n", encoding="ascii")


# ---- running things --------------------------------------------------------

def pinned() -> tuple[Path, str]:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler()


def compile_map(path: Path, full: bool = False) -> str:
    exe, threads = pinned()
    out = ""
    # `-rad` is this compiler's lighting stage; `-light` makes it print its
    # usage and exit, which is how a map reached the lighting assertion with an
    # empty lighting lump.
    for stage in ([["-bsp"], ["-vis"], ["-rad"]] if full else [["-bsp"]]):
        run = load_guard.run(
            [str(exe)] + stage + ["-threads", threads, "-moddir", str(GAME),
                                  "-basedir", str(GAME), "-gamedir", str(GAME),
                                  str(path)],
            capture_output=True, text=True, timeout=7200)
        out += run.stdout + run.stderr
    return out


def drive(exe: Path, bsp: Path, *args: str) -> str:
    # row 412: the generator's own box rooms (annexes, two-storey halls) are dealt only when asked - the PO, 05.10:
    # «скучно, в оригинальных картах такого нет». The cases about them ask for them as the old default at ambition 80
    # did: six annexes, two storeys.
    args = tuple(args)
    # row 412: and on the footprints they had before the cap, which the staged cases stand on - unless the caller
    # asks for the capped ones (the annex-rooms guard)
    if "--annex-capped" in args:
        args = tuple(x for x in args if x != "--annex-capped")
    elif "--annex-uncapped" not in args:
        args += ("--annex-uncapped",)
    if "--annex" not in args:
        args += ("--annex", "6", "0", "0", "0")
    if "--storeys" not in args:
        args += ("--storeys", "2")
    run = load_guard.run([str(exe), str(bsp), *args],
                         capture_output=True, text=True, timeout=7200)
    return run.stdout + run.stderr


def probe(exe: Path, bsp: Path, *args: str) -> tuple[int, str]:
    run = load_guard.run([str(exe), str(bsp), *args],
                         capture_output=True, text=True, timeout=1200)
    return run.returncode, run.stdout + run.stderr


def build_probe(out: Path) -> Path:
    exe = out / "dig_probe.exe"
    run = load_guard.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-I" + str(REPO / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0",
         str(REPO / "tools" / "mapgen_dig_probe.c"),
         str(REPO / "src" / "mapgen" / "mapgen_bsp.c"),
         str(REPO / "src" / "mapgen" / "mapgen_trace.c"),
         str(REPO / "src" / "shared" / "shared.c"),
         str(REPO / "tools" / "mapgen_host_stubs.c"),
         "-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the dig probe")
    return exe


def walk_chain(probe_exe: Path, bsp: Path, listing: str,
               edit: int) -> tuple[int, list[str]]:
    """Sweep a player hull through the chain of ONE dig. Returns the number of
    legs a player cannot walk and the lines that say why."""
    bad = 0
    why: list[str] = []
    for m in CHAIN.finditer(listing):
        if int(m.group(1)) != edit:
            continue
        nums = [float(x) for x in m.group(3).split()]
        pts = [nums[i:i + 3] for i in range(0, len(nums), 3)]
        for a, b in zip(pts, pts[1:]):
            rc, out = probe(probe_exe, bsp, "--walk",
                            *[f"{v:.0f}" for v in a],
                            *[f"{v:.0f}" for v in b], "--step", "16")
            if rc:
                bad += 1
                for line in out.splitlines():
                    if ("TOO STEEP" in line or "NO GROUND" in line
                            or "CANNOT STAND" in line):
                        why.append(line.strip())
    return bad, why


def lump(d: bytes, n: int) -> bytes:
    o, l = struct.unpack_from("<ii", d, 8 + 8 * n)
    return d[o:o + l]


def count_plats(bsp: Path) -> int:
    text = lump(bsp.read_bytes(), 0).split(b"\0")[0].decode("latin-1")
    return text.count('"classname" "func_plat"')


def tread_light(bsp: Path) -> tuple[int, int]:
    """The darkest and the mean lightmap byte over the whole file, as a cheap
    "is it black in there" number. A dig whose treads are unlit reads as the
    lighting lump being empty, which the delivery guard refuses outright."""
    raw = lump(bsp.read_bytes(), 7)
    if not raw:
        return 0, 0
    return min(raw), sum(raw) // len(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(WORK))
    ap.add_argument("--quick", action="store_true",
                    help="skip the q2dm1 apply and the alive launch")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)

    exe = build_driver(REPO, work)
    probe_exe = build_probe(work)
    print(f"driver {exe}\nprobe  {probe_exe}")

    watches = []
    for name, (f, t) in PO_EXAMPLES.items():
        watches.append(name)

    # ---- cases 1 and 2: the two fixtures that must SEAL -------------------
    for which, between in (("rock", "rock"), ("void", "void")):
        src = work / f"dig_{which}.map"
        write_fixture(src, between)
        log = compile_map(src)
        base = src.with_suffix(".bsp")
        if not check(f"the {which} fixture itself compiles",
                     base.is_file() and "leaked" not in log,
                     "leaked" if "leaked" in log else ""):
            continue
        listing = drive(exe, base, "--seed", "1", "--ambition", "80", "--list")
        offers = list(DIG_EDIT.finditer(listing))
        tally = TALLY.search(listing)
        if not check(f"{which}: the family offers a dig", bool(offers),
                     tally.group(1)[:150] if tally else "no tally"):
            continue
        edit = int(offers[0].group(1))
        shape = offers[0].group(9)
        cand = work / f"dig_{which}_applied.map"
        out = drive(exe, base, "--seed", "1", "--ambition", "80",
                    "--apply", str(edit), "--out", str(cand))
        ap_m = APPLY.search(out)
        check(f"{which}: it applies", bool(ap_m) and ap_m.group(3) == "yes",
              (ap_m.group(0) if ap_m else "")
              + (" " + [l for l in out.splitlines()
                        if l.startswith("declined")][0]
                 if "declined" in out else ""))
        clog = compile_map(cand)
        dug = cand.with_suffix(".bsp")
        sealed = "leaked" not in clog and dug.is_file()
        check(f"{which}: the dug map is SEALED ({shape})", sealed,
              "leaked" if "leaked" in clog
              else ("" if dug.is_file() else "no bsp written"))
        if sealed:
            #
            # The LIFT, in the quick path too.
            #
            # It used to be asserted only on q2dm1, in the slow path, so a
            # mutation that built `func_wall` instead of `func_plat` left the
            # quick run green - a guard that cannot go red on the thing it is
            # about.
            #
            if "lift" in shape:
                text_map = cand.read_text(encoding="latin-1")
                check(f"{which}: the dig's lift is a func_plat in the map the"
                      f" operator wrote",
                      '"classname" "func_plat"' in text_map,
                      "func_plat" if '"classname" "func_plat"' in text_map
                      else "no func_plat at all")
            bad, why = walk_chain(probe_exe, dug, listing, edit)
            check(f"{which}: a player hull walks it end to end", bad == 0,
                  "; ".join(why[:3]) if why else "")
            #
            # The seam contract, asked of the COMPILED file.
            #
            # NOT the source-brush fault count: the transaction stopped gating on
            # that in September because the compiler's own FixTjuncs pass stitches
            # the world before anybody sees the map, and a carve that replaces one
            # rock brush with six pieces raises it by design - MEASURED, 72 to 446
            # on this fixture. What the gate reads is the compiled
            # world-against-world count, and that is what is asserted.
            #
            _, before = probe(probe_exe, base, "--seams")
            _, after = probe(probe_exe, dug, "--seams")
            bw = re.search(r"(\d+) world-vs-world", before)
            aw = re.search(r"(\d+) world-vs-world", after)
            check(f"{which}: the dig adds no T-junction between two world faces"
                  f" in the COMPILED map",
                  bool(bw) and bool(aw)
                  and int(aw.group(1)) <= int(bw.group(1)),
                  f"{aw.group(1) if aw else '?'} after,"
                  f" {bw.group(1) if bw else '?'} before")

    # ---- the controlled RED: no shell, and the void fixture must open -----
    src = work / "dig_void.map"
    base = src.with_suffix(".bsp")
    if base.is_file():
        listing = drive(exe, base, "--seed", "1", "--ambition", "80", "--list")
        offers = list(DIG_EDIT.finditer(listing))
        if offers:
            edit = int(offers[0].group(1))
            red = work / "dig_void_noshell.map"
            drive(exe, base, "--seed", "1", "--ambition", "80",
                  "--digpass", "14",          # carve + fill + fit, NO shell
                  "--apply", str(edit), "--out", str(red))
            rlog = compile_map(red)
            check("RED: with the SHELL pass removed the void fixture LEAKS",
                  "leaked" in rlog,
                  "it still sealed - the shell is not what seals it"
                  if "leaked" not in rlog else "**** leaked ****")

    # ---- case 3: a third room in the way is refused at the plan -----------
    src = work / "dig_third.map"
    write_fixture(src, "third")
    log = compile_map(src)
    base = src.with_suffix(".bsp")
    if check("the third-room fixture itself compiles",
             base.is_file() and "leaked" not in log):
        # row 333: one annex of 256, so four halls of 768 round the block do not
        # take the rock this case's router needs - its question is the router
        # row 412: no real room on this small fixture - the case is the router's, and the rooms took its sites
        PINNED = ("--annex", "1", "256", "256", "192", "--real-rooms", "0")
        listing = drive(exe, base, "--seed", "1", "--ambition", "80", *PINNED, "--list")
        tally = TALLY.search(listing)
        broke = re.search(r"(\d+) would break into a third room", listing)
        check("third room: the plan refuses passages that break into it",
              bool(broke) and int(broke.group(1)) > 0,
              tally.group(1)[:200] if tally else "no tally")
        first = re.search(r"opened it first at (-?\d+ -?\d+ -?\d+)",
                          listing)
        check("third room: and the refusal names the coordinates of the break",
              bool(first), first.group(1) if first else "no coordinates")
        # every dig it DOES offer must still seal
        offers = list(DIG_EDIT.finditer(listing))
        if offers:
            edit = int(offers[0].group(1))
            cand = work / "dig_third_applied.map"
            drive(exe, base, "--seed", "1", "--ambition", "80", *PINNED,
                  "--apply", str(edit), "--out", str(cand))
            clog = compile_map(cand)
            check("third room: what it does offer still compiles sealed",
                  "leaked" not in clog,
                  "leaked" if "leaked" in clog else "")
        #
        # The ROUTER goes ROUND the chamber the straight shapes break into.
        #
        # This is what «по стенке» asked for on q2dm1: the courtyard in the way
        # of every straight line from the rocket ledge to the railgun is this
        # fixture's chamber. A passage that goes round it through the rock, with
        # a lift where the block is too thin for the whole drop, is the answer -
        # and it has to seal, and a player has to be able to walk it.
        #
        routes = re.search(r"dig routes: (\d+) pairs routed, (\d+) laid"
                           r" through the rock", listing)
        routed = [m for m in offers
                  if m.group(9) in ("tunnel", "tunnel+lift", "corridor")]
        check("third room: the ROUTER lays a passage round the chamber through"
              " the rock", bool(routes) and int(routes.group(2)) > 0
              and bool(routed),
              (routes.group(0) if routes else "no routes line")
              + f"; {len(routed)} routed digs dealt")
        if routed:
            edit = int(routed[0].group(1))
            cand = work / "dig_third_routed.map"
            drive(exe, base, "--seed", "1", "--ambition", "80", *PINNED,
                  "--apply", str(edit), "--out", str(cand))
            clog = compile_map(cand)
            dug = cand.with_suffix(".bsp")
            sealed = "leaked" not in clog and dug.is_file()
            check(f"third room: the routed passage ({routed[0].group(9)})"
                  f" compiles SEALED", sealed,
                  "leaked" if "leaked" in clog else "")
            if sealed:
                bad, why = walk_chain(probe_exe, dug, listing, edit)
                check("third room: a player hull walks the routed passage end"
                      " to end", bad == 0, "; ".join(why[:3]))
        #
        # And the controlled RED: the same fixture with the router OFF (the
        # module's own test seam, `--norouter`) has no way round at all. A
        # routed candidate that appears without the router is not the router's.
        #
        red_listing = drive(exe, base, "--seed", "1", "--ambition", "80", *PINNED,
                            "--list", "--norouter")
        red_routed = [m for m in DIG_EDIT.finditer(red_listing)
                      if m.group(9) in ("tunnel", "tunnel+lift", "corridor")]
        red_routes = re.search(r"dig routes: (\d+) pairs routed, (\d+) laid",
                               red_listing)
        check("RED: with the router off the chamber has no way round",
              not red_routed and bool(red_routes)
              and int(red_routes.group(2)) == 0,
              f"{len(red_routed)} routed digs;"
              f" {red_routes.group(0) if red_routes else 'no routes line'}")

    # ---- case 4: q2dm1 and the PO's own three examples --------------------
    if DONOR.is_file():
        listing = drive(exe, DONOR, "--seed", "1", "--ambition", "80",
                        "--powatch", "--list")
        (work / "q2dm1_list.txt").write_text(listing, encoding="utf-8")

        #
        # 6 MOUTHS. Every passage this donor deals is a WAY on the file that
        # was built - and with the mouths off, at least one of them is not.
        #
        # The PO walked into one on 2026-09-11 and had to walk back out: «есть
        # моменты когда вырытый тоннель упирается в непроходимое препятствие».
        # It had compiled, it had sealed, every pickup was reachable and the
        # hull probe had walked its inside end to end, because nothing asked
        # whether a player can get INTO it. This does, through the passage's own
        # segments rather than through the box round them - the bounding box of
        # a passage that bends holds rooms that are not in it.
        #
        if not a.quick:
            def dig_ways(tag: str, extra: list) -> list:
                text = (listing if not extra
                        else drive(exe, DONOR, "--seed", "1", "--ambition",
                                   "80", "--powatch", "--list", *extra))
                (work / f"q2dm1_{tag}_list.txt").write_text(text,
                                                            encoding="utf-8")
                digs = list(DIG_EDIT.finditer(text))
                segs = {}
                for m in re.finditer(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$",
                                     text, re.M):
                    segs.setdefault(int(m.group(1)), []).append(
                        m.group(3).split())
                if not digs:
                    return []
                args = ["--seed", "1", "--ambition", "80", "--powatch", *extra]
                for m in digs:
                    args += ["--apply", m.group(1)]
                cand = work / f"q2dm1_{tag}.map"
                drive(exe, DONOR, *args, "--out", str(cand))
                cand.with_suffix(".bsp").unlink(missing_ok=True)
                clog = compile_map(cand)
                built = cand.with_suffix(".bsp")
                if "leaked" in clog or not built.is_file():
                    return []
                cmd = [str(gate_exe), str(built), "40000"]
                names = []
                for m in digs:
                    e = int(m.group(1))
                    boxes = segs.get(e) or []
                    if not boxes:
                        continue
                    cmd += ["--way"] + [m.group(i) for i in (3, 4, 5)]
                    cmd += [m.group(i) for i in (6, 7, 8)]
                    cmd += [str(len(boxes))] + [v for b in boxes for v in b]
                    names.append(f"{m.group(3)} {m.group(4)} {m.group(5)}")
                got = load_guard.run(cmd, capture_output=True, text=True,
                                     timeout=3600)
                (work / f"q2dm1_{tag}_ways.txt").write_text(
                    got.stdout + got.stderr, encoding="utf-8")
                out = []
                for line in (got.stdout + got.stderr).splitlines():
                    if line.strip().startswith("WAY"):
                        out.append((names[len(out)] if len(out) < len(names)
                                    else "?", True))
                    elif line.strip().startswith("DEAD END"):
                        out.append((names[len(out)] if len(out) < len(names)
                                    else "?", False))
                return out

            from check_mapgen_reach_gate import build_gate     # noqa: E402
            gate_exe = build_gate(work)
            green = dig_ways("mouths", [])
            check("q2dm1: every passage dealt is a WAY on the compiled map",
                  bool(green) and all(w for _, w in green),
                  "; ".join(f"{k}: {'WAY' if v else 'DEAD END'}"
                            for k, v in green) or "no passage reached the gate")
            red = dig_ways("nomouth", ["--nomouth"])
            check("RED: with the mouths off (`--nomouth`) at least one passage"
                  " is a DEAD END",
                  bool(red) and not all(w for _, w in red),
                  "; ".join(f"{k}: {'WAY' if v else 'DEAD END'}"
                            for k, v in red) or "no passage reached the gate")

            #
            # And on the map the deal compiles, the game frees no pickup at
            # spawn and no lift runs into a spawn point (ledger row 311). This
            # case was red on the committed source for exactly that - lifts
            # dealt onto a chaingun, two boxes of bullets, slugs and a spawn,
            # which the transaction refuses only after a compile - so it is
            # asked of the transaction's own oracle, not of the plan.
            #
            from check_mapgen_lost_pickup import build as build_oracle, ask
            oracle = work / "lost_pickup_oracle.exe"
            oracle.unlink(missing_ok=True)
            err = build_oracle(REPO, oracle)
            mouths = work / "q2dm1_mouths.bsp"

            def asked(bsp: Path) -> tuple:
                if err or not bsp.is_file():
                    return -1, {}, -1, {}
                n_lost, lost, n_blocked, blocked, _ = ask(oracle, bsp)
                return n_lost, lost, n_blocked, blocked

            def said(n_lost, lost, n_blocked, blocked) -> str:
                return (f"{n_lost} lost, {n_blocked} blocked: "
                        + "; ".join(f"{c} at {o} {i}" for (c, o), i in
                                    list(lost.items())[:3]
                                    + list(blocked.items())[:2])
                        + (f" oracle build: {err[:160]}" if err else ""))
            got = asked(mouths)
            check("q2dm1: on that map no pickup is lost at spawn and no lift"
                  " runs into a spawn point",
                  got[0] == 0 and got[2] == 0, said(*got))
            # row 343: and every passage of that deal is DUG - nothing open high to
            # the old map, nothing it built standing in the old air
            from check_mapgen_dig_walls import open_high, solid_in_air, said as walls_said

            def seg_boxes(text: str) -> list:
                ends = {int(m.group(1)): ([float(m.group(i)) for i in (3, 4, 5)],
                                          [float(m.group(i)) for i in (6, 7, 8)])
                        for m in DIG_EDIT.finditer(text)}
                out = []
                for m in re.finditer(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$", text, re.M):
                    e = ends.get(int(m.group(1)))
                    out.append({"box": [float(v) for v in m.group(3).split()],
                                "from": e[0] if e else None, "to": e[1] if e else None})
                return out
            segs4 = seg_boxes(listing)
            walls = (open_high(mouths, segs4, DONOR) + solid_in_air(mouths, segs4, DONOR)
                     if mouths.is_file() else [None])
            check("q2dm1: every passage of that deal is dug - nothing open high to the old"
                  " map, nothing standing in its air", not walls,
                  f"{len(segs4)} segments, {len(walls)} points"
                  + (f": {walls_said(walls)}" if walls and walls[0] else ""))
            before_dug = hash_tree(REPO)
            dbox = Sandbox(REPO, "digdug")
            try:
                target = dbox.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
                data = target.read_bytes()
                rules = (b"if (have_vox && dig_air_beyond_mouths(&vox, &d, walled_at)) {",
                         b"if (dig_air_beyond_mouths(&vox, &d, walled_at)) {")
                if check("RED: the plan's dug rule is where the mutation says",
                         all(data.count(r) == 1 for r in rules),
                         ", ".join(str(data.count(r)) for r in rules)):
                    for r in rules:
                        data = data.replace(r, r.replace(b"if (", b"if (false && ", 1), 1)
                    target.write_bytes(data)
                    dug_dir = work / "red_dug"
                    dug_dir.mkdir(parents=True, exist_ok=True)
                    dug_exe = build_driver(dbox.root, dug_dir)
                    dtext = drive(dug_exe, DONOR, "--seed", "1", "--ambition", "80",
                                  "--powatch", "--list")
                    dargs = ["--seed", "1", "--ambition", "80", "--powatch"]
                    for m in DIG_EDIT.finditer(dtext):
                        dargs += ["--apply", m.group(1)]
                    dug_map = work / "q2dm1_reddug.map"
                    drive(dug_exe, DONOR, *dargs, "--out", str(dug_map))
                    dug_map.with_suffix(".bsp").unlink(missing_ok=True)
                    compile_map(dug_map)
                    dsegs = seg_boxes(dtext)
                    red_walls = (open_high(dug_map.with_suffix(".bsp"), dsegs, DONOR)
                                 + solid_in_air(dug_map.with_suffix(".bsp"), dsegs, DONOR)
                                 if dug_map.with_suffix(".bsp").is_file() else [])
                    check("RED: with the dug rule taken out, the deal opens high to the old"
                          " map or stands in its air - the case above goes red",
                          bool(red_walls), f"{len(red_walls)} points: {walls_said(red_walls)}")
            finally:
                dbox.dispose()
                check("the shared worktree was never opened for writing",
                      hash_tree(REPO) == before_dug)
            # row 337: and no player-clip brush left in space the deal opened -
            # the north hall's doorway is cut through q2dm1's two clip beams
            from check_mapgen_clips import exposed as clips_exposed, said as clips_said
            clip_bad = clips_exposed(mouths, DONOR) if mouths.is_file() else [None]
            check("q2dm1: on that map no player-clip brush stands beside space the"
                  " deal opened", not clip_bad,
                  f"{len(clip_bad)} found" + (f": {clips_said(clip_bad)}"
                                              if clip_bad and clip_bad[0] else ""))
            before_clip = hash_tree(REPO)
            cbox = Sandbox(REPO, "digclip")
            try:
                target = cbox.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
                data = target.read_bytes()
                anchor = (b"|| !(brush->contents & (CONTENTS_SOLID_BIT"
                          b" | CONTENTS_PLAYERCLIP_BIT)))")
                if check("RED: the carve's clip rule is where the mutation says",
                         data.count(anchor) == 1, f"{data.count(anchor)} occurrences"):
                    target.write_bytes(data.replace(
                        anchor, b"|| !(brush->contents & CONTENTS_SOLID_BIT))", 1))
                    clip_dir = work / "red_clip"
                    clip_dir.mkdir(parents=True, exist_ok=True)
                    clip_exe = build_driver(cbox.root, clip_dir)
                    ctext = drive(clip_exe, DONOR, "--seed", "1", "--ambition", "80",
                                  "--powatch", "--list")
                    cargs = ["--seed", "1", "--ambition", "80", "--powatch"]
                    for m in DIG_EDIT.finditer(ctext):
                        cargs += ["--apply", m.group(1)]
                    clip_map = work / "q2dm1_redclip.map"
                    drive(clip_exe, DONOR, *cargs, "--out", str(clip_map))
                    clip_map.with_suffix(".bsp").unlink(missing_ok=True)
                    compile_map(clip_map)
                    red_bad = (clips_exposed(clip_map.with_suffix(".bsp"), DONOR)
                               if clip_map.with_suffix(".bsp").is_file() else [])
                    check("RED: with the carve cutting solid brushes only, the deal"
                          " leaves clip brushes in space it opened - the case above"
                          " goes red", bool(red_bad),
                          f"{len(red_bad)} found: {clips_said(red_bad)}")
            finally:
                cbox.dispose()
                check("the shared worktree was never opened for writing",
                      hash_tree(REPO) == before_clip)

            before_lift = hash_tree(REPO)
            lbox = Sandbox(REPO, "diglift")
            try:
                target = lbox.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
                data = target.read_bytes()
                anchor = b"if (dig_lift_on_someone(ground, &cand[k], lift_what,"
                if check("RED: the plan's lift refusal is where the mutation"
                         " says", data.count(anchor) == 1,
                         f"{data.count(anchor)} occurrences"):
                    target.write_bytes(data.replace(
                        anchor, b"if (false && dig_lift_on_someone(ground,"
                                b" &cand[k], lift_what,", 1))
                    lift_dir = work / "red_lift"
                    lift_dir.mkdir(parents=True, exist_ok=True)
                    lift_exe = build_driver(lbox.root, lift_dir)
                    text = drive(lift_exe, DONOR, "--seed", "1", "--ambition",
                                 "80", "--powatch", "--list")
                    (work / "q2dm1_redlift_list.txt").write_text(
                        text, encoding="utf-8")
                    args = ["--seed", "1", "--ambition", "80", "--powatch"]
                    for m in DIG_EDIT.finditer(text):
                        args += ["--apply", m.group(1)]
                    red_map = work / "q2dm1_redlift.map"
                    drive(lift_exe, DONOR, *args, "--out", str(red_map))
                    red_map.with_suffix(".bsp").unlink(missing_ok=True)
                    compile_map(red_map)
                    got = asked(red_map.with_suffix(".bsp"))
                    check("RED: with the plan's lift refusal taken out the map"
                          " its deal compiles frees a pickup or blocks a spawn",
                          got[0] > 0 or got[2] > 0, said(*got))
            finally:
                lbox.dispose()
                check("the shared worktree was never opened for writing",
                      hash_tree(REPO) == before_lift)

            # RED (row 333): the treads' rule taken out - at seed 1 the PO's
            # example c is laid with its last flight in the slugs' box
            before_treads = hash_tree(REPO)
            tbox = Sandbox(REPO, "digtreads")
            try:
                target = tbox.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
                data = target.read_bytes()
                anchor = (b"if (dig_treads_bury_someone(ground, &d, walled_at))"
                          b" {   /* row 333 */")
                # row 344: with the dug rule, which at seed 1 refuses the same
                # tunnel - the two together are what this RED shows
                dug_rules = (b"if (have_vox && dig_air_beyond_mouths(&vox, &d, walled_at)) {",
                             b"if (dig_air_beyond_mouths(&vox, &d, walled_at)) {")
                if check("RED: the treads' rule is where the mutation says",
                         data.count(anchor) == 2
                         and all(data.count(r) == 1 for r in dug_rules),
                         f"{data.count(anchor)} occurrences"):
                    data = data.replace(
                        anchor, b"if (false && dig_treads_bury_someone(ground, &d,"
                                b" walled_at)) {")
                    for r in dug_rules:
                        data = data.replace(r, r.replace(b"if (", b"if (false && ", 1), 1)
                    target.write_bytes(data)
                    treads_dir = work / "red_treads"
                    treads_dir.mkdir(parents=True, exist_ok=True)
                    treads_exe = build_driver(tbox.root, treads_dir)
                    text = drive(treads_exe, DONOR, "--seed", "1", "--ambition",
                                 "80", "--powatch", "--list")
                    (work / "q2dm1_redtreads_list.txt").write_text(
                        text, encoding="utf-8")
                    args = ["--seed", "1", "--ambition", "80", "--powatch"]
                    for m in DIG_EDIT.finditer(text):
                        args += ["--apply", m.group(1)]
                    red_map = work / "q2dm1_redtreads.map"
                    drive(treads_exe, DONOR, *args, "--out", str(red_map))
                    red_map.with_suffix(".bsp").unlink(missing_ok=True)
                    compile_map(red_map)
                    got = asked(red_map.with_suffix(".bsp"))
                    check("RED: with the treads' rule taken out the map its deal"
                          " compiles loses a pickup - the case above goes red",
                          got[0] > 0, said(*got))
            finally:
                tbox.dispose()
                check("the shared worktree was never opened for writing",
                      hash_tree(REPO) == before_treads)
        seen = {}
        for m in WATCH.finditer(listing):
            name, said = m.group(1), m.group(2)
            if "ACCEPTED" in said:
                seen[name] = "accepted: " + said
            elif name not in seen:
                seen[name] = "refused: " + said
        for name in PO_EXAMPLES:
            verdict = seen.get(name, "never reached the planner at all")
            check(f"q2dm1: the PO's example «{name}» has a verdict with"
                  f" coordinates", name in seen, verdict[:170])
        accepted = [n for n, v in seen.items() if v.startswith("accepted")]
        check("q2dm1: at least one of the PO's three examples is a candidate",
              len(accepted) >= 1, ", ".join(accepted) or "none")
        cands = CAND.findall(listing)
        check("q2dm1: the whole candidate list is in the ledger with ratios",
              len(cands) >= 3, f"{len(cands)} candidates listed")
        watched_dealt = [c for c in cands if "WATCHED" in c[1]
                         and "DEALT" in c[1]]
        check("q2dm1: a named example is dealt FIRST, not buried under the"
              " biggest shortcuts", len(watched_dealt) >= 1,
              watched_dealt[0][1][:140] if watched_dealt else "none dealt")
        offers = list(DIG_EDIT.finditer(listing))
        #
        # 1 + ambition * 9 / 100: eight at fidelity 20. «Чем ниже процент
        # форка, тем больше подобного нужно делать» - and the PO had said it
        # more than once before 2026-09-11. Six is the floor this asserts,
        # because two candidates may cross and one of them then gives way.
        #
        check("q2dm1: the ambition deals at least six digs at fidelity 20",
              len(offers) >= 6, f"{len(offers)} dealt")
        routed = [m for m in offers
                  if m.group(9) in ("tunnel", "tunnel+lift", "corridor")]
        check("q2dm1: and some of them are ROUTED through the rock, which no"
              " straight shape could lay", len(routed) >= 1,
              ", ".join(f"{m.group(3)} {m.group(4)} {m.group(5)} -> {m.group(6)}"
                        f" {m.group(7)} {m.group(8)} {m.group(9)}"
                        for m in routed[:3]))
        shapes = sorted({m.group(9) for m in offers})
        check("q2dm1: and they are not all the same shape", len(shapes) >= 2,
              ", ".join(shapes))
        # and the count rises with the ambition
        counts = {}
        for amb in (10, 25, 40, 50, 80):
            one = drive(exe, DONOR, "--seed", "1", "--ambition", str(amb),
                        "--powatch", "--list")
            counts[amb] = len(list(DIG_EDIT.finditer(one)))
        check("q2dm1: fewer digs at a high fidelity than at a low one",
              counts[10] <= counts[50] and counts[10] < counts[80],
              ", ".join(f"F{100 - k}={v}" for k, v in counts.items()))

        if not a.quick and offers:
            #
            # A dig WITH A LIFT, deliberately.
            #
            # The first offered dig is whichever has the lowest schedule index,
            # and on this donor that is often a plain flight. Applying it and then
            # asserting «a func_plat edict is alive» passed on the DONOR's own two
            # plats - the feature owns neither of them. The guard picks a dig whose
            # own listing line says `lift`.
            #
            with_lift = [m for m in offers if "lift" in m.group(14)] or offers
            edit = int(with_lift[0].group(1))
            cand = work / "q2dm1_dug.map"
            out = drive(exe, DONOR, "--seed", "1", "--ambition", "80",
                        "--powatch", "--apply", str(edit), "--out", str(cand))
            ap_m = APPLY.search(out)
            check("q2dm1: the dig applies to the real donor",
                  bool(ap_m) and ap_m.group(3) == "yes",
                  ap_m.group(0) if ap_m else out[-160:])
            clog = compile_map(cand, full=True)
            bsp = cand.with_suffix(".bsp")
            check("q2dm1: the dug donor is SEALED",
                  "leaked" not in clog and bsp.is_file(),
                  "leaked" if "leaked" in clog else "")
            if bsp.is_file():
                _, before = probe(probe_exe, DONOR, "--seams")
                _, after = probe(probe_exe, bsp, "--seams")
                bw = re.search(r"(\d+) world-vs-world", before)
                aw = re.search(r"(\d+) world-vs-world", after)
                # row 344: those within 64 of this dig's own segments - the
                # compiler's re-partition can split an unchanged floor far away
                own = [[float(v) for v in m.group(1).split()] for m in re.finditer(
                    rf"^  digseg {edit} \d+((?: -?\d+){{6}})$", listing, re.M)]
                near = [s for s in re.findall(r"^world seam at (\S+) (\S+) (\S+)$", after, re.M)
                        if any(all(b[i] - 64.0 <= float(s[i]) <= b[3 + i] + 64.0 for i in range(3))
                               for b in own)]
                check("q2dm1: and it adds no T-junction between two world faces near the"
                      " dig", bool(bw) and bool(aw) and bool(own) and not near,
                      f"{len(near)} near its {len(own)} segments; {aw.group(1) if aw else '?'}"
                      f" in the map, {bw.group(1) if bw else '?'} in the donor")
            if bsp.is_file():
                bad, why = walk_chain(probe_exe, bsp, listing, edit)
                check("q2dm1: a player hull walks the dig end to end",
                      bad == 0, "; ".join(why[:3]))
                dark, mean = tread_light(bsp)
                check("q2dm1: the dig is LIT - the map has a lighting lump"
                      " with light in it", mean > 0,
                      f"darkest byte {dark}, mean {mean}")
                plats = count_plats(bsp)
                donor_plats = count_plats(DONOR)
                wants_lift = "lift" in with_lift[0].group(14)
                check("q2dm1: the dig's OWN lift is in the file, not just the"
                      " donor's two",
                      plats >= donor_plats + (1 if wants_lift else 0),
                      f"{plats} func_plat against the donor's {donor_plats},"
                      f" and this dig {'has' if wants_lift else 'has no'} lift")
                # ---- case 5: and it is ALIVE after spawn in deathmatch ----
                if not a.quick:
                    maps = GAME / "maps"
                    name = "mgdigtest"
                    shutil.copyfile(bsp, maps / f"{name}.bsp")
                    run = load_guard.run(
                        [sys.executable,
                         str(REPO / "tools" / "check_mapgen_glass_alive.py"),
                         name, "--lifts",
                         str(count_plats(DONOR) + (1 if wants_lift else 0)),
                         "--json", str(work / "alive.json")],
                        capture_output=True, text=True, timeout=3600)
                    print(run.stdout.rstrip()[-1200:])
                    alive = {}
                    if (work / "alive.json").is_file():
                        alive = json.loads(
                            (work / "alive.json").read_text(encoding="utf-8"))
                    check("q2dm1: the dug map spawns on a hidden dedicated"
                          " server with no window of ours on screen",
                          run.returncode == 0 or bool(alive),
                          run.stdout.strip().splitlines()[-1]
                          if run.stdout.strip() else "")
                    try:
                        (maps / f"{name}.bsp").unlink()
                    except OSError:
                        pass

    # ---- case 6: HALLS on the long tunnels (ledger row 310) -----------------
    #
    # q2dm1's walls can hardly be moved - behind most of them another room lies
    # within a carve's depth (row 309) - but the passages the router lays run
    # through its outer rock, and a cell of one grown into a room is new
    # architecture on a way that already has a purpose. The plan's listing says
    # where each hall is; this guard walks the donor's own tree with every one
    # of them, the shell round it included (row 311), instead of taking the
    # plan's word.
    #
    if DONOR.is_file():
        tree = bsp_tree(DONOR)

        def halls_of(text: str) -> list:
            return [tuple(float(v) for v in m.groups()[1:])
                    for m in HALL.finditer(text)]

        def show(halls: list) -> str:
            return "; ".join(f"{h[0]:.0f} {h[1]:.0f} {h[2]:.0f} .. {h[3]:.0f}"
                             f" {h[4]:.0f} {h[5]:.0f}" for h in halls[:4]) or "none"

        def hall_overlaps(text: str) -> list:
            """Row 318: (edit, hall segment, other segment) for every hall box
            that meets another segment box of its own passage by more than a
            unit on every axis."""
            hall_boxes = [tuple(float(v) for v in m.groups()[1:])
                          for m in HALL.finditer(text)]
            segs = {}
            for m in re.finditer(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$",
                                 text, re.M):
                segs.setdefault(int(m.group(1)), []).append(
                    tuple(float(v) for v in m.group(3).split()))
            bad = []
            for e, boxes in segs.items():
                for i, b in enumerate(boxes):
                    if not any(all(abs(b[k] - h[k]) < 0.5 for k in range(6))
                               for h in hall_boxes):
                        continue
                    for j, o in enumerate(boxes):
                        if j != i and all(min(b[3 + k], o[3 + k])
                                          - max(b[k], o[k]) > 1.0
                                          for k in range(3)):
                            bad.append((e, i, j))
            return bad

        # row 358: seed 2 - with dealt digs 80 apart (row 357) only 2 and 10 deal halls
        hall_list = drive(exe, DONOR, "--seed", "2", "--ambition", "80",
                          "--list")
        (work / "q2dm1_halls_list.txt").write_text(hall_list, encoding="utf-8")
        halls = halls_of(hall_list)
        told = list(HALLS.finditer(hall_list))
        check("halls: q2dm1 at seed 2 deals at least two halls",
              len(halls) >= 2, f"{len(halls)} halls: {show(halls)}")
        check("halls: every one on a passage of six segments or more",
              bool(told) and all(int(m.group(3)) >= 6 for m in told
                                 if int(m.group(1)) > 0),
              "; ".join(m.group(0)[:90] for m in told[:4]) or "no halls line")
        check("halls: every hall stands in rock, the shell round it included",
              bool(halls) and all(box_in_rock(tree, h) for h in halls),
              show(halls))
        overlaps = hall_overlaps(hall_list)
        check("halls: no hall reaches into another segment of its passage",
              bool(halls) and not overlaps,
              f"{len(overlaps)} overlaps {overlaps[:4]}")

        # row 345: the rock proof is asked of a driver with the dug rule taken
        # out - with it no passage on q2dm1 grows a hall the proof refuses
        DUG_RULES = (b"if (have_vox && dig_air_beyond_mouths(&vox, &d, walled_at)) {",
                     b"if (dig_air_beyond_mouths(&vox, &d, walled_at)) {")

        def dug_off(data: bytes) -> bytes:
            for r in DUG_RULES:
                data = data.replace(r, r.replace(b"if (", b"if (false && ", 1), 1)
            return data

        before = hash_tree(REPO)
        box = Sandbox(REPO, "dighallsdugoff")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            check("the dug rule is where the dug-off driver takes it out",
                  all(data.count(r) == 1 for r in DUG_RULES))
            target.write_bytes(dug_off(data))
            off_dir = work / "dugoff"
            off_dir.mkdir(parents=True, exist_ok=True)
            off_exe = build_driver(box.root, off_dir)
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

        wide_args = ("--seed", "1020", "--ambition", "80", "--halls", "32",
                     "384", "192", "--list")
        wide_list = drive(off_exe, DONOR, *wide_args)
        (work / "q2dm1_halls384_list.txt").write_text(wide_list,
                                                       encoding="utf-8")
        wide = halls_of(wide_list)
        refused = sum(int(m.group(2)) for m in HALLS.finditer(wide_list))
        check("halls: at 384 wide the proof refuses a cell that would break"
              " into space", refused >= 1,
              f"{refused} refused, {len(wide)} kept")
        check("halls: and every hall it keeps at 384 wide is still rock",
              all(box_in_rock(tree, h) for h in wide), show(wide))

        before = hash_tree(REPO)
        box = Sandbox(REPO, "dighalls")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            anchor = b"if (!dig_hall_in_rock(r, glo, ghi, bad))"
            if check("RED: the hall's proof is where the mutation says",
                     data.count(anchor) == 1,
                     f"{data.count(anchor)} occurrences"):
                target.write_bytes(dug_off(data.replace(
                    anchor, b"if (false && !dig_hall_in_rock(r, glo, ghi, bad))",
                    1)))
                red_dir = work / "red_halls"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(box.root, red_dir)
                red = halls_of(drive(red_exe, DONOR, *wide_args))
                check("RED: with the proof taken out a hall at 384 wide meets"
                      " air - the case above goes red",
                      bool(red) and not all(box_in_rock(tree, h) for h in red),
                      f"{len(red)} halls: {show(red)}")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

        # RED: row 310's proof put back - the voxels whose centres lie in the
        # box, and no walk of the tree - keeps a hall beside a corridor
        before = hash_tree(REPO)
        box = Sandbox(REPO, "dighalls310")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            grow = b"const float grow = 0.5f * ROUTE_VOX - 0.5f;"
            exact = (b"if (!dig_box_rock_node(r->ground, world->headnode, tlo,"
                     b" thi, bad, 0))")
            if check("RED: row 310's proof is where the mutation says",
                     data.count(grow) == 1 and data.count(exact) == 1,
                     f"{data.count(grow)} and {data.count(exact)} occurrences"):
                target.write_bytes(dug_off(
                    data.replace(grow, b"const float grow = 0.0f;", 1)
                        .replace(exact, b"if (false && !dig_box_rock_node("
                                        b"r->ground, world->headnode, tlo,"
                                        b" thi, bad, 0))", 1)))
                red_dir = work / "red_halls310"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(box.root, red_dir)
                red = halls_of(drive(red_exe, DONOR, *wide_args))
                check("RED: with row 310's proof back a hall kept at 384 wide"
                      " meets air - the case above goes red",
                      bool(red) and not all(box_in_rock(tree, h) for h in red),
                      f"{len(red)} halls: {show(red)}")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

        # row 333: the passages dealt at seed 1020 moved when the storey came to
        # be dealt first, and the turn these REDs need is dealt at seed 1
        seed1_bad = hall_overlaps(drive(exe, DONOR, "--seed", "10", "--ambition", "80",
                                        "--list"))
        check("halls: at seed 10 either, no hall reaches into another segment of its"
              " passage", not seed1_bad, f"{len(seed1_bad)} overlaps {seed1_bad[:4]}")

        # RED (row 318): a landing hall grown along its run again reaches into
        # the flights before and after it
        before = hash_tree(REPO)
        box = Sandbox(REPO, "dighallrun")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            anchor = (b"if (a == (int)s->axis)             /* row 318: never"
                      b" along its run */")
            meet = b"if (meets) {             /* row 319: never into its own passage */"
            if check("RED: the hall's run rule and its passage rule are where the"
                     " mutation says",
                     data.count(anchor) == 1 and data.count(meet) == 1,
                     f"{data.count(anchor)} and {data.count(meet)} occurrences"):
                target.write_bytes(data.replace(
                    anchor, b"if (s->kind == DIG_SEG_STAIR && a == (int)s->axis)",
                    1).replace(meet, b"if (false && meets) {", 1))
                red_dir = work / "red_hall_run"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(box.root, red_dir)
                red_bad = hall_overlaps(drive(red_exe, DONOR, "--seed", "2",
                                              "--ambition", "80", "--list"))
                check("RED: with row 310's growth back - along its run, into its"
                      " passage - a hall reaches into its passage's next segment",
                      bool(red_bad), f"{len(red_bad)} overlaps {red_bad[:4]}")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

        # RED (row 319): the passage rule taken out alone - at a turn a hall
        # grown across its landing's run reaches into the next segment
        before = hash_tree(REPO)
        box = Sandbox(REPO, "dighallmeet")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            meet = b"if (meets) {             /* row 319: never into its own passage */"
            if check("RED: the hall's passage rule is where the mutation says",
                     data.count(meet) == 1, f"{data.count(meet)} occurrences"):
                target.write_bytes(data.replace(meet, b"if (false && meets) {", 1))
                red_dir = work / "red_hall_meet"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(box.root, red_dir)
                red_bad = hall_overlaps(drive(red_exe, DONOR, "--seed", "10",
                                              "--ambition", "80", "--list"))
                check("RED: with the passage rule taken out a hall at a turn"
                      " reaches into its passage's next segment - the case above"
                      " goes red", bool(red_bad),
                      f"{len(red_bad)} overlaps {red_bad[:4]}")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

    # ---- case 7: ANNEX rooms (ledger row 315) --------------------------------
    #
    # The PO called mg_20h's widened flights minor: «для меня, как игрока, и как
    # PO это просто довольно небольшие отличия архитектурно». Rooms of the map's
    # own size fit behind q2dm1's walls, nearly all beyond its hull (row 315's
    # census). The plan's listing says where each room, doorway and moved pickup
    # is; this guard asks the donor's own tree and entity lump, not the plan.
    #
    if DONOR.is_file():
        tree = bsp_tree(DONOR)
        data = DONOR.read_bytes()
        eo, en = struct.unpack_from("<ii", data, 8)
        donor_ents = [dict(re.findall(r'"([^"]*)"\s*"([^"]*)"', b))
                      for b in re.findall(r"\{([^}]*)\}",
                                          data[eo:eo + en].decode("latin1"))]
        num = r"(-?\d+)"
        ANNEX = re.compile(r"^  dig annex: room " + " ".join([num] * 3) + r" \.\. "
                           + " ".join([num] * 3) + " off " + " ".join([num] * 3)
                           + r" through (\d+) of wall$", re.M)
        DOOR = re.compile(r"^  dig annex doorway: " + " ".join([num] * 3)
                          + r" \.\. " + " ".join([num] * 3) + "$", re.M)
        MOVE = re.compile(r"^  dig annex moves: (\S+) from " + " ".join([num] * 3)
                          + " to " + " ".join([num] * 3) + "$", re.M)
        TALLY7 = re.compile(r"^  dig annexes: (\d+) dealt of (\d+) wanted; (\d+)"
                            r" sites proved", re.M)

        def annexes_of(text: str) -> list:
            rooms = [[float(v) for v in m.groups()] for m in ANNEX.finditer(text)]
            doors = [[float(v) for v in m.groups()] for m in DOOR.finditer(text)]
            moves = [(m.group(1), [float(v) for v in m.groups()[1:]])
                     for m in MOVE.finditer(text)]
            if not (len(rooms) == len(doors) == len(moves)):
                return []
            return [{"room": r[:6], "host": r[6:9], "reach": r[9], "door": d,
                     "cls": mv[0], "from": mv[1][:3], "to": mv[1][3:]}
                    for r, d, mv in zip(rooms, doors, moves)]

        def shown(an: list) -> str:
            return "; ".join(f"{a['room'][0]:.0f} {a['room'][1]:.0f} {a['room'][2]:.0f}"
                             f" .. {a['room'][3]:.0f} {a['room'][4]:.0f} {a['room'][5]:.0f}"
                             f" holds {a['cls']}" for a in an[:4]) or "none"

        def door_rock(a: dict) -> bool:
            """The doorway from 4 past the wall's face to its room, 16 across,
            under and over: rock."""
            d, host = a["door"], a["host"]
            ax = 0 if d[3] - d[0] < d[4] - d[1] else 1
            lo, hi = list(d[:3]), list(d[3:])
            if host[ax] < 0.5 * (d[ax] + d[3 + ax]):
                lo[ax] += 16.0 + 4.0          # the host is on the low side
            else:
                hi[ax] -= 16.0 + 4.0
            cr = 1 - ax
            lo[cr] -= 16.0
            hi[cr] += 16.0
            lo[2] -= 16.0
            hi[2] += 16.0
            return box_in_rock(tree, tuple(lo + hi), margin=0.0)

        def pickup_is_donors(a: dict) -> bool:
            for e in donor_ents:
                o = e.get("origin", "").split()
                if e.get("classname") == a["cls"] and len(o) == 3 and all(
                        abs(float(o[i]) - a["from"][i]) <= 1.0 for i in range(3)):
                    return True
            return False

        def inside(p, box) -> bool:
            return all(box[i] <= p[i] <= box[3 + i] for i in range(3))

        annex_list = drive(exe, DONOR, "--seed", "1020", "--ambition", "80",
                           "--list")
        (work / "q2dm1_annex_list.txt").write_text(annex_list, encoding="utf-8")
        annexes = annexes_of(annex_list)
        tally = TALLY7.search(annex_list)
        check("annexes: q2dm1 at seed 1020 deals at least two",
              len(annexes) >= 2, f"{len(annexes)}: {shown(annexes)}; "
              + (tally.group(0).strip() if tally else "no tally"))
        check("annexes: every room, its shell round it, is rock in the donor",
              bool(annexes) and all(box_in_rock(tree, tuple(a["room"]))
                                    for a in annexes), shown(annexes))
        check("annexes: every doorway is cut through rock from the wall's face"
              " to its room", bool(annexes) and all(door_rock(a) for a in annexes),
              "; ".join(f"{a['door']}" for a in annexes[:3]))
        def stands(h) -> bool:
            """Row 316: floor within 2 under each corner of a 24 by 24 square
            round the place, air 8 and 48 over each corner."""
            return all(tree_solid(tree, (h[0] + cx, h[1] + cy, h[2] - 2.0))
                       and not tree_solid(tree, (h[0] + cx, h[1] + cy, h[2] + 8.0))
                       and not tree_solid(tree, (h[0] + cx, h[1] + cy, h[2] + 48.0))
                       for cx in (-12.0, 12.0) for cy in (-12.0, 12.0))
        check("annexes: the place each opens off is a place a player stands",
              bool(annexes) and all(stands(a["host"]) for a in annexes),
              "; ".join(f"{a['host']}" for a in annexes[:4]))
        check("annexes: each moved pickup is the donor's own, and its new place is"
              " inside its room", bool(annexes) and all(
                  pickup_is_donors(a) and inside(a["to"], a["room"]) for a in annexes),
              "; ".join(f"{a['cls']} {a['from']} -> {a['to']}" for a in annexes[:4]))
        segs = {}
        for m in re.finditer(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$", annex_list, re.M):
            segs.setdefault(int(m.group(1)), []).append([float(v) for v in m.group(3).split()])
        shapes = {int(m.group(1)): m.group(9) for m in DIG_EDIT.finditer(annex_list)}
        passage_boxes = [b for e, bs in segs.items() if shapes.get(e) != "annex" for b in bs]

        def meets(a, b, gap=16.0) -> bool:
            return all(a[3 + i] + gap > b[i] and b[3 + i] + gap > a[i] for i in range(3))
        crossings = [(i, j) for i in range(len(annexes)) for j in range(i + 1, len(annexes))
                     if meets(annexes[i]["room"], annexes[j]["room"])]
        crossings += [(i, "passage") for i, a in enumerate(annexes)
                      if any(meets(a["room"], b) for b in passage_boxes)]
        check("annexes: no annex meets another annex or a passage",
              bool(annexes) and not crossings and bool(passage_boxes),
              f"{len(passage_boxes)} passage segments; crossings {crossings[:4]}")

        big_args = ("--seed", "1020", "--ambition", "80", "--annex", "4", "1024",
                    "1024", "320", "--list")
        big_list = drive(exe, DONOR, *big_args)
        (work / "q2dm1_annex1024_list.txt").write_text(big_list, encoding="utf-8")
        big = annexes_of(big_list)
        big_tally = TALLY7.search(big_list)
        check("annexes: at 1024 by 1024 by 320 the proof keeps fewer sites than at"
              " 512, and every room it keeps is rock",
              bool(big_tally) and bool(tally)
              and int(big_tally.group(3)) < int(tally.group(3))
              and all(box_in_rock(tree, tuple(a["room"])) for a in big),
              f"{big_tally.group(0).strip() if big_tally else 'no tally'};"
              f" kept {shown(big)}")

        # ---- row 324: WINGS - two annex rooms joined by a link ----------------
        WING = re.compile(r"^  dig annex wing: from " + " ".join([num] * 3) + " to "
                          + " ".join([num] * 3) + ", link " + " ".join([num] * 3)
                          + r" \.\. " + " ".join([num] * 3)
                          + r", (level|steps) (\d+)$", re.M)

        def wings_of(text: str) -> list:
            """Each wing line, with the segment boxes of its own dig."""
            ends = {}
            for m in DIG_EDIT.finditer(text):
                ends[tuple(round(float(m.group(i))) for i in (3, 4, 5, 6, 7, 8))] = \
                    int(m.group(1))
            segs = {}
            for m in re.finditer(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$", text,
                                 re.M):
                segs.setdefault(int(m.group(1)), []).append(
                    tuple(float(v) for v in m.group(3).split()))
            out = []
            for m in WING.finditer(text):
                v = [float(x) for x in m.groups()[:12]]
                e = ends.get(tuple(round(x) for x in v[:6]))
                out.append({"from": v[0:3], "to": v[3:6], "link": v[6:12],
                            "kind": m.group(13),
                            "segs": segs.get(e, []) if e is not None else []})
            return out

        def link_axis(w: dict):
            """The level axis along which the link touches room A (segment 1) and
            room B (segment 3), or None."""
            L, s = w["link"], w["segs"]
            if len(s) != 5:
                return None
            for ax in (0, 1):
                a = abs(s[1][3 + ax] - L[ax]) < 1.0 or abs(s[1][ax] - L[3 + ax]) < 1.0
                b = abs(s[3][3 + ax] - L[ax]) < 1.0 or abs(s[3][ax] - L[3 + ax]) < 1.0
                if a and b:
                    return ax
            return None

        def link_rock(w: dict) -> bool:
            ax = link_axis(w)
            if ax is None:
                return False
            lo, hi = list(w["link"][:3]), list(w["link"][3:])
            lo[1 - ax] -= 16.0
            hi[1 - ax] += 16.0
            lo[2] -= 16.0
            hi[2] += 16.0
            return box_in_rock(tree, tuple(lo + hi), margin=0.0)

        def wing_meets_itself(w: dict) -> list:
            s = w["segs"]
            return [(i, j) for i in range(len(s)) for j in range(i + 1, len(s))
                    if all(min(s[i][3 + k], s[j][3 + k]) - max(s[i][k], s[j][k])
                           > 1.0 for k in range(3))]

        wing_list = drive(exe, DONOR, "--seed", "42", "--ambition", "80", "--list")
        (work / "q2dm1_wings_list.txt").write_text(wing_list, encoding="utf-8")
        wings = wings_of(wing_list)
        said = "; ".join(f"{w['from']} -> {w['to']} {w['kind']}"
                         for w in wings[:4]) or "none"
        check("wings: q2dm1 at seed 42 joins at least one wing, its dig of five"
              " segments found", bool(wings)
              and all(len(w["segs"]) == 5 for w in wings), said)
        check("wings: every link touches both its rooms",
              bool(wings) and all(link_axis(w) is not None for w in wings), said)
        check("wings: every link, 16 round it across, under and over, is rock in"
              " the donor", bool(wings) and all(link_rock(w) for w in wings), said)
        check("wings: no segment of a wing meets another of its own",
              bool(wings) and not any(wing_meets_itself(w) for w in wings),
              "; ".join(str(wing_meets_itself(w)) for w in wings) or "none")

        # RED (row 325): a link put 64 into its near room - the contact and the
        # self-overlap questions above must both catch it
        before = hash_tree(REPO)
        box = Sandbox(REPO, "digwingred")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            anchor = b"                    jn->lo[ax] = near->hi[ax];"
            if check("RED: the wing link's placement is where the mutation says",
                     data.count(anchor) == 1, f"{data.count(anchor)} occurrences"):
                target.write_bytes(data.replace(
                    anchor, b"                    jn->lo[ax] = near->hi[ax] - 64.0f;", 1))
                red_dir = work / "red_wing"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(box.root, red_dir)
                red = wings_of(drive(red_exe, DONOR, "--seed", "42", "--ambition", "80",
                                     "--list"))
                check("RED: with a link 64 into its room, a link no longer touches both"
                      " its rooms and meets a segment of its own wing - the cases above"
                      " go red", bool(red)
                      and any(link_axis(w) is None for w in red)
                      and any(wing_meets_itself(w) for w in red),
                      "; ".join(f"{w['from']} -> {w['to']}: axis {link_axis(w)},"
                                f" meets {wing_meets_itself(w)}" for w in red[:3])
                      or "no wing")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

        before = hash_tree(REPO)
        box = Sandbox(REPO, "digannex")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            anchor = b"if (!dig_hall_in_rock(rc, glo, ghi, bad))"
            if check("RED: the annex's proof is where the mutation says",
                     data.count(anchor) == 1, f"{data.count(anchor)} occurrences"):
                target.write_bytes(data.replace(
                    anchor, b"if (false && !dig_hall_in_rock(rc, glo, ghi, bad))", 1))
                red_dir = work / "red_annex"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(box.root, red_dir)
                red = annexes_of(drive(red_exe, DONOR, *big_args))
                check("RED: with the annex's proof taken out a room at 1024 meets air"
                      " - the case above goes red",
                      bool(red) and not all(box_in_rock(tree, tuple(a["room"]))
                                            for a in red),
                      f"{len(red)} annexes: {shown(red)}")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

        # ---- rows 377-379: what an annex holds, what its room is built of, and
        # that no swap trades its pickup away ------------------------------------
        #
        # The PO on mg_20r (quake163, quake164): «комната хороша, когда в ней
        # есть интересная архитектура и объекты, а не просто куб в стенке ... у
        # игроков должна быть цель заходить в неё». The listing says what each
        # annex holds; one annex applied alone with a swap staged against its
        # pickup says what its room is built of (the compiled tree) and what it
        # holds (the .map's entities).
        #
        from mapgen_delivery_gates import PICKUP_WORTH, ANNEX_WORTH_MIN
        src = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
            encoding="utf-8", errors="replace")
        body = src[src.find("static int pickup_worth("):]
        body = body[:body.find("return 0;")]
        src_worth = {c: int(w) for c, w in re.findall(r'\{ "([a-z_]+)", (\d+) \}', body)}
        check("annexes: the guard's worth table is the generator's own",
              bool(src_worth) and src_worth == PICKUP_WORTH,
              f"{len(src_worth)} classes in the source, {len(PICKUP_WORTH)} here")

        def worth_said(an: list) -> str:
            return "; ".join(f"{a['cls']} {PICKUP_WORTH.get(a['cls'], 0)}" for a in an) or "none"
        check("annexes: each holds a pickup worth the walk (5 or more)",
              bool(annexes) and all(PICKUP_WORTH.get(a["cls"], 0) >= ANNEX_WORTH_MIN
                                    for a in annexes), worth_said(annexes))
        before = hash_tree(REPO)
        box = Sandbox(REPO, "digworth")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            anchor = b"best_at, best_class, true);"
            if check("RED: the annex's worth rule is where the mutation says",
                     data.count(anchor) == 1, f"{data.count(anchor)} occurrences"):
                target.write_bytes(data.replace(anchor, b"best_at, best_class, false);", 1))
                red_dir = work / "red_worth"
                red_dir.mkdir(parents=True, exist_ok=True)
                red = annexes_of(drive(build_driver(box.root, red_dir), DONOR, "--seed", "1020",
                                       "--ambition", "80", "--list"))
                check("RED: with the worth rule taken out an annex holds less - the case above goes red",
                      bool(red) and any(PICKUP_WORTH.get(a["cls"], 0) < ANNEX_WORTH_MIN for a in red),
                      worth_said(red))
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)

        SWAP = re.compile(r"^  edit (\d+)  swap-item  (\d+) (\S+) <-> (\d+) (\S+)$", re.M)
        POINT = re.compile(r'^\{\n((?:"[^"\n]*" "[^"\n]*"\n)+)\}$', re.M)

        def donor_at(i: int, cls: str, at: list) -> bool:
            if i >= len(donor_ents):
                return False
            o = donor_ents[i].get("origin", "").split()
            return (donor_ents[i].get("classname") == cls and len(o) == 3
                    and all(abs(float(o[k]) - at[k]) <= 1.0 for k in range(3)))

        def staged_room(drv: Path, tag: str) -> dict:
            """A standalone annex at seed 1020 and a swap of its pickup for one
            worth less, applied together; the .map's pickup at the annex's place,
            the driver's declines, and the compiled map's tree."""
            text = drive(drv, DONOR, "--seed", "1020", "--ambition", "80", "--list")
            got = {"staged": None, "held": None, "declined": [], "tree": None}
            for an in annexes_of(text):
                mid = [0.5 * (an["room"][0] + an["room"][3]),
                       0.5 * (an["room"][1] + an["room"][4]), an["host"][2]]
                edit = next((m.group(1) for m in DIG_EDIT.finditer(text) if m.group(9) == "annex"
                             and [float(m.group(k)) for k in range(3, 9)] == an["host"] + mid), None)
                if edit is None:
                    continue
                for m in SWAP.finditer(text):
                    i, ci, j, cj = int(m.group(2)), m.group(3), int(m.group(4)), m.group(5)
                    lesser = (cj if donor_at(i, ci, an["from"]) else
                              ci if donor_at(j, cj, an["from"]) else None)
                    if lesser and PICKUP_WORTH.get(lesser, 0) < ANNEX_WORTH_MIN:
                        got["staged"] = (an, edit, m.group(1), lesser)
                        break
                if got["staged"]:
                    break
            if not got["staged"]:
                return got
            an, edit, sw, _ = got["staged"]
            mp = work / f"q2dm1_room_{tag}.map"
            out = drive(drv, DONOR, "--seed", "1020", "--ambition", "80", "--apply", edit,
                        "--apply", sw, "--out", str(mp))
            got["declined"] = [ln.strip() for ln in out.splitlines() if "declined:" in ln]
            for m in POINT.finditer(mp.read_text(encoding="latin1") if mp.is_file() else ""):
                kv = dict(re.findall(r'"([^"]*)" "([^"]*)"', m.group(1)))
                o = kv.get("origin", "").split()
                if (kv.get("classname", "").startswith(("weapon_", "item_", "ammo_")) and len(o) == 3
                        and all(abs(float(o[k]) - an["to"][k]) <= 1.0 for k in range(3))):
                    got["held"] = kv["classname"]
            if not a.quick:
                mp.with_suffix(".bsp").unlink(missing_ok=True)
                log = compile_map(mp)
                if "leaked" not in log and mp.with_suffix(".bsp").is_file():
                    got["tree"] = bsp_tree(mp.with_suffix(".bsp"))
            return got

        def pattern_of(tree, an: dict) -> dict:
            """The dais 8 and 24 over the floor at the room's middle with air 40
            over it, solid under the pickup's place 2 under the dais' top, and on
            each wall a knee band (4 in, 36 over the floor) and a lintel band (20
            under the ceiling) at one of three places along it, air 16 past it."""
            r, f, c = an["room"], an["room"][2], an["room"][5]
            mx, my = 0.5 * (r[0] + r[3]), 0.5 * (r[1] + r[4])
            out = {"dais": tree_solid(tree, (mx, my, f + 8.0)) and tree_solid(tree, (mx, my, f + 24.0))
                   and not tree_solid(tree, (mx, my, f + 40.0)),
                   "under": tree_solid(tree, (an["to"][0], an["to"][1], f + 30.0)),
                   "knee": 0, "lintel": 0}
            for wall in range(4):
                ax, al = wall // 2, 1 - wall // 2
                face = r[3 + ax] - 4.0 if wall & 1 else r[ax] + 4.0
                knee = lintel = False
                for frac in (0.25, 0.5, 0.75):
                    q = [0.0, 0.0]
                    q[ax], q[al] = face, r[al] + frac * (r[3 + al] - r[al])
                    knee = knee or (tree_solid(tree, (q[0], q[1], f + 36.0))
                                    and not tree_solid(tree, (q[0], q[1], f + 52.0)))
                    lintel = lintel or (tree_solid(tree, (q[0], q[1], c - 20.0))
                                        and not tree_solid(tree, (q[0], q[1], c - 36.0)))
                out["knee"] += 1 if knee else 0
                out["lintel"] += 1 if lintel else 0
            return out

        def room_said(got: dict, pat: dict | None) -> str:
            if not got["staged"]:
                return "no standalone annex with a lesser swap found"
            an, edit, sw, lesser = got["staged"]
            return (f"annex edit {edit} holding {an['cls']}, swap edit {sw} for {lesser}: holds {got['held']};"
                    f" {'; '.join(got['declined'][:2]) or 'nothing declined'}"
                    + (f"; dais {pat['dais']}, pickup on it {pat['under']}, knee bands on {pat['knee']} walls,"
                       f" lintel bands on {pat['lintel']}" if pat else ""))

        room = staged_room(exe, "green")
        pat = pattern_of(room["tree"], room["staged"][0]) if room["tree"] and room["staged"] else None
        # brief 9 D3 (row 412): the room's parts are drawn per room - the room is held to what the plan declared for it
        from check_mapgen_annex_rooms import annexes as declared_annexes, matches as declared_wrong, parts as declared_parts

        def declared(drv: Path, got: dict) -> tuple[dict | None, list]:
            if not got["staged"] or not got["tree"]:
                return None, ["no compiled room"]
            text = drive(drv, DONOR, "--seed", "1020", "--ambition", "80", "--list")
            an = got["staged"][0]
            dec = next((x for x in declared_annexes(text) if x["room"] == an["room"]), None)
            if dec is None:
                return None, ["no pattern declared for it"]
            return dec, declared_wrong(dec, declared_parts(got["tree"], dec))
        check("annexes: an annex's pickup is not swapped for one worth less - the swap declined, saying why",
              bool(room["staged"]) and room["held"] == room["staged"][0]["cls"]
              and any("dug room's pickup worth the walk" in d for d in room["declined"]),
              room_said(room, pat))
        if not a.quick:
            dec, wrong = declared(exe, room)
            check("annexes: its room, compiled, is the room its plan drew (its floor, its pickup's stand, its columns)",
                  dec is not None and not wrong,
                  (f"{dec['floor']}, pickup {dec['pickup']}, columns {dec['columns']}: " if dec else "")
                  + (", ".join(wrong) or "as declared"))
        before = hash_tree(REPO)
        box = Sandbox(REPO, "digroom")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            pattern_line = b"static const bool g_annex_pattern = true;"
            swap_line = b"static const bool g_swap_keeps_dug = true;"
            if check("RED: the room's pattern and the swap's refusal are where the mutation says",
                     data.count(pattern_line) == 1 and data.count(swap_line) == 1,
                     f"{data.count(pattern_line)}, {data.count(swap_line)}"):
                data = data.replace(pattern_line, b"static const bool g_annex_pattern = false;", 1)
                target.write_bytes(data.replace(swap_line, b"static const bool g_swap_keeps_dug = false;", 1))
                red_dir = work / "red_room"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_room = staged_room(build_driver(box.root, red_dir), "red")
                red_pat = (pattern_of(red_room["tree"], red_room["staged"][0])
                           if red_room["tree"] and red_room["staged"] else None)
                check("RED: with the swap's refusal taken out the room holds the lesser pickup - the case"
                      " above goes red", bool(red_room["staged"])
                      and red_room["held"] == red_room["staged"][3], room_said(red_room, red_pat))
                if not a.quick:
                    red_dec, red_wrong = declared(build_driver(box.root, red_dir), red_room)
                    check("RED: with the pattern taken out the room is not the room its plan drew - the case above"
                          " goes red", red_dec is not None and bool(red_wrong), ", ".join(red_wrong))
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)

        # ---- case 8: STOREYS - one room of two storeys (ledger rows 327-328) --
        #
        # A hall entered from a place below, a terrace along the wall of a place
        # above, a flight up to it along a side wall: the terrace and the flight
        # are INNER segments of the room. The plan's listing says where; this
        # asks the donor's tree, and the map case 4 compiled.
        #
        T3 = " ".join([num] * 3)
        STOREY = re.compile(r"^  dig storeys: room " + T3 + r" \.\. " + T3 + " from "
                            + T3 + " below, " + T3 + " above$", re.M)
        STOREY_DOORS = re.compile(r"^  dig storeys doorways: " + T3 + r" \.\. " + T3
                                  + " and " + T3 + r" \.\. " + T3 + "$", re.M)
        STOREY_PARTS = re.compile(r"^  dig storeys terrace: " + T3 + r" \.\. " + T3
                                  + "; flight " + T3 + r" \.\. " + T3
                                  + r", (\d+) treads$", re.M)

        def storeys_of(text: str) -> list:
            """Each storey's lines, with the edit and the segment boxes of its dig."""
            rooms = [[float(v) for v in m.groups()] for m in STOREY.finditer(text)]
            doors = [[float(v) for v in m.groups()]
                     for m in STOREY_DOORS.finditer(text)]
            parts = [[float(v) for v in m.groups()]
                     for m in STOREY_PARTS.finditer(text)]
            if not (len(rooms) == len(doors) == len(parts)):
                return []
            ends = {}
            for m in DIG_EDIT.finditer(text):
                ends[tuple(round(float(m.group(i))) for i in (3, 4, 5, 6, 7, 8))] = \
                    int(m.group(1))
            segs = {}
            for m in re.finditer(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$", text,
                                 re.M):
                segs.setdefault(int(m.group(1)), []).append(
                    tuple(float(v) for v in m.group(3).split()))
            out = []
            for r, d, p in zip(rooms, doors, parts):
                e = ends.get(tuple(round(x) for x in r[6:12]))
                out.append({"room": r[:6], "below": r[6:9], "above": r[9:12],
                            "door_a": d[:6], "door_b": d[6:12], "terrace": p[:6],
                            "flight": p[6:12], "treads": int(p[12]), "edit": e,
                            "segs": segs.get(e, []) if e is not None else []})
            return out

        def wall_axis(door, room):
            """The level axis on which a doorway's face lies on one of the room's
            walls, within that wall's span; None when it lies on none."""
            for ax in (0, 1):
                cr = 1 - ax
                on = (abs(door[3 + ax] - room[ax]) < 1.0
                      or abs(door[ax] - room[3 + ax]) < 1.0)
                if (on and door[cr] >= room[cr] - 1.0
                        and door[3 + cr] <= room[3 + cr] + 1.0):
                    return ax
            return None

        def boxes_meet(p, q, axes=(0, 1, 2)) -> bool:
            return all(min(p[3 + k], q[3 + k]) - max(p[k], q[k]) > 1.0 for k in axes)

        def storey_wrong(s: dict) -> list:
            """What is wrong with one storey's layout, in words; empty if nothing."""
            room, ter, fl = s["room"], s["terrace"], s["flight"]
            a_door, b_door, n = s["door_a"], s["door_b"], max(1, s["treads"])
            wrong = []
            if len(s["segs"]) != 5:
                wrong.append(f"{len(s['segs'])} segments")
            for door, floor, name in ((a_door, room[2], "lower"),
                                      (b_door, ter[2], "upper")):
                if (boxes_meet(door, room) or wall_axis(door, room) is None
                        or abs(door[2] - floor) > 1.0):
                    wrong.append(f"the {name} doorway does not touch the room's"
                                 f" wall from outside on its floor")
            if not all(room[k] - 1.0 <= box[k] and box[3 + k] <= room[3 + k] + 1.0
                       for box in (ter, fl) for k in range(3)):
                wrong.append("the terrace or the flight is outside the room")
            bax = wall_axis(b_door, room)
            if bax is not None:
                low = abs(b_door[3 + bax] - room[bax]) < 1.0
                along = (abs(ter[bax] - room[bax]) < 1.0 if low
                         else abs(ter[3 + bax] - room[3 + bax]) < 1.0)
                if not along:
                    wrong.append("the terrace is not along the upper doorway's wall")
                edge = ter[3 + bax] if low else ter[bax]
                high = fl[bax] if low else fl[3 + bax]
                if abs(high - edge) > 1.0:
                    wrong.append("the flight's high end is not on the terrace's edge")
                rise = (ter[2] - room[2]) / n
                depth = (fl[3 + bax] - fl[bax]) / n
                if abs(fl[2] - room[2]) > 1.0 or rise > 18.0 or depth < 24.0:
                    wrong.append(f"a flight from {fl[2]:.0f} of treads {rise:.1f}"
                                 f" high and {depth:.1f} deep")
            aax = wall_axis(a_door, room)
            if aax is not None:
                patch = list(a_door)
                if abs(a_door[3 + aax] - room[aax]) < 1.0:
                    patch[aax], patch[3 + aax] = room[aax], room[aax] + 64.0
                else:
                    patch[aax], patch[3 + aax] = room[3 + aax] - 64.0, room[3 + aax]
                if boxes_meet(patch, ter, (0, 1)) or boxes_meet(patch, fl, (0, 1)):
                    wrong.append("the lower doorway opens into the terrace or the"
                                 " flight")
            segs = s["segs"]
            meets = {(i, j) for i in range(len(segs)) for j in range(i + 1, len(segs))
                     if boxes_meet(segs[i], segs[j])}
            if meets - {(1, 2), (1, 3)}:
                wrong.append(f"segments meet: {sorted(meets - {(1, 2), (1, 3)})}")
            return wrong

        def storey_said(st: list) -> str:
            return "; ".join(f"{s['room'][0]:.0f} {s['room'][1]:.0f} {s['room'][2]:.0f}"
                             f" .. {s['room'][3]:.0f} {s['room'][4]:.0f}"
                             f" {s['room'][5]:.0f} from {s['below']} below,"
                             f" {s['above']} above" for s in st[:2]) or "none"

        storeys = storeys_of(annex_list)
        # row 332: halls of 768 at ambition 80, the storey dealt before them
        # row 412: a hall of 768 or more along one side - each annex now takes a footprint of its own (brief 9 D3),
        # and at 1020 the square 768 fell to none: 960 x 576 stands for it
        check("annexes: at seed 1020 halls of 768 are dealt, and a storey with them",
              any(max(a["room"][3] - a["room"][0], a["room"][4] - a["room"][1]) >= 767.0 for a in annexes)
              and bool(storeys),
              f"{shown(annexes)}; storeys {len(storeys)}")
        before = hash_tree(REPO)
        box = Sandbox(REPO, "digstoreyfirst")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            eol = b"\r\n" if b"\r\n" in data else b"\n"
            anchor = (b"    if (want_storeys) {" + eol
                      + b"        const uint32_t sz = num_sizes == 3u ? 1u : 0u;")
            if check("RED: the storey dealt first is where the mutation says",
                     data.count(anchor) == 1, f"{data.count(anchor)} occurrences"):
                target.write_bytes(data.replace(
                    anchor, anchor.replace(b"if (want_storeys)",
                                           b"if (false && want_storeys)"), 1))
                first_dir = work / "red_storey_first"
                first_dir.mkdir(parents=True, exist_ok=True)
                first_exe = build_driver(box.root, first_dir)
                red_first = storeys_of(drive(first_exe, DONOR, "--seed", "1020",
                                             "--ambition", "80", "--list"))
                check("RED: with the storey no longer dealt first, seed 1020 deals"
                      " none - the case above goes red", not red_first,
                      f"{len(red_first)} storeys")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)
        check("storeys: q2dm1 at seed 1020 deals at least one, its dig of five"
              " segments found", bool(storeys)
              and all(len(s["segs"]) == 5 for s in storeys), storey_said(storeys))
        check("storeys: every room, 16 round it, is rock in the donor",
              bool(storeys) and all(box_in_rock(tree, tuple(s["room"]))
                                    for s in storeys), storey_said(storeys))
        check("storeys: each doorway touches its room's wall from outside on its"
              " floor; the terrace runs along the upper doorway's wall and the"
              " flight from the room's floor to the terrace's edge inside the room,"
              " treads no higher than 18 and no shallower than 24; the lower"
              " doorway, 64 into the room, meets neither; no two segments meet but"
              " the room and what it holds",
              bool(storeys) and not any(storey_wrong(s) for s in storeys),
              "; ".join(f"{s['below']}: {storey_wrong(s) or 'as laid'}"
                        for s in storeys[:2]) or "none")

        # RED (row 328): the flight laid on the low side wall without asking the
        # lower doorway - the layout question above must catch it
        before = hash_tree(REPO)
        box = Sandbox(REPO, "digstoreyred")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            anchor = b"            clear = !plan_meets(dlo, dhi, flo, fhi);"
            if check("RED: the flight's side rule is where the mutation says",
                     data.count(anchor) == 2, f"{data.count(anchor)} occurrences"):
                # brief 5 W6: the storey with one door asks the same rule - both taken out
                target.write_bytes(data.replace(anchor, b"            clear = true;"))
                red_dir = work / "red_storey"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(box.root, red_dir)
                red = storeys_of(drive(red_exe, DONOR, "--seed", "1020",
                                       "--ambition", "80", "--list"))
                check("RED: with the flight laid on the low side wall without asking"
                      " the lower doorway, the doorway opens into the flight - the"
                      " case above goes red", bool(red) and any(
                          "the lower doorway opens into the terrace or the flight"
                          in storey_wrong(s) for s in red),
                      "; ".join(f"{s['below']}: {storey_wrong(s)}" for s in red[:2])
                      or "no storey")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

        def storey_fill_wrong(bsp: Path, s: dict) -> list:
            """On a compiled map: the terrace solid 8 and 64 under its top and half
            way down, air 32 over it; the flight's middle tread solid 8 under its
            top and no rock over it from 32 up to 32 under the ceiling. The flight
            touches the terrace on one level axis, and that face is its high end."""
            built = bsp_tree(bsp)
            room, ter, fl, n = s["room"], s["terrace"], s["flight"], max(1, s["treads"])
            z0, zt, ceil = room[2], ter[2], room[5]
            tx, ty = (ter[0] + ter[3]) / 2.0, (ter[1] + ter[4]) / 2.0
            wrong = []
            if (not all(tree_solid(built, (tx, ty, z))
                        for z in (zt - 8.0, zt - 64.0, (z0 + zt) / 2.0))
                    or tree_solid(built, (tx, ty, zt + 32.0))):
                wrong.append("the terrace is not solid down to the room's floor")
            bax = next((k for k in (0, 1) if abs(fl[k] - ter[3 + k]) < 1.0
                        or abs(fl[3 + k] - ter[k]) < 1.0), None)
            if bax is None:
                return wrong + ["the flight does not touch the terrace"]
            high, step = ((fl[bax], 1.0) if abs(fl[bax] - ter[3 + bax]) < 1.0
                          else (fl[3 + bax], -1.0))
            k = n // 2
            p = [(fl[0] + fl[3]) / 2.0, (fl[1] + fl[4]) / 2.0, 0.0]
            p[bax] = high + step * (k + 0.5) * (fl[3 + bax] - fl[bax]) / n
            top = zt - (k + 1) * (zt - z0) / n
            if not tree_solid(built, (p[0], p[1], top - 8.0)):
                wrong.append(f"tread {k} is not solid under its top {top:.0f}")
            rock = [z for z in range(int(top + 32.0), int(ceil - 32.0) + 1, 16)
                    if tree_solid(built, (p[0], p[1], float(z)))]
            if rock:
                wrong.append(f"rock over the flight at {rock[:4]}")
            return wrong

        if not a.quick:
            mouths_map = work / "q2dm1_mouths.bsp"
            seed1 = work / "q2dm1_list.txt"
            st1 = storeys_of(seed1.read_text(encoding="utf-8")) if seed1.is_file() else []
            got8 = ([storey_fill_wrong(mouths_map, s) for s in st1]
                    if mouths_map.is_file() else [])
            check("storeys: on the map case 4 compiled at seed 1 the terrace is solid"
                  " down to the room's floor and no rock hangs over the flight",
                  bool(got8) and not any(got8),
                  "; ".join(f"{s['below']}: {w or 'as built'}"
                            for s, w in zip(st1, got8))
                  or f"{len(st1)} storeys, map there: {mouths_map.is_file()}")

            before = hash_tree(REPO)
            box = Sandbox(REPO, "digstoreyfill")
            try:
                target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
                data = target.read_bytes()
                swaps = ((b"            tlo[2] = (s->inner ? s->base : lo[2]) - DIG_SHELL;",
                          b"            tlo[2] = lo[2] - DIG_SHELL;"),
                         (b"            if (!s->inner && bhi[2] > blo[2] + 0.5f) {",
                          b"            if (bhi[2] > blo[2] + 0.5f) {"))
                if check("RED: the two FILL rules of an inner segment are where the"
                         " mutation says", all(data.count(o) == 1 for o, _ in swaps),
                         ", ".join(str(data.count(o)) for o, _ in swaps)):
                    for old, new in swaps:
                        data = data.replace(old, new, 1)
                    target.write_bytes(data)
                    fill_dir = work / "red_storey_fill"
                    fill_dir.mkdir(parents=True, exist_ok=True)
                    fill_exe = build_driver(box.root, fill_dir)
                    red_st = storeys_of(drive(fill_exe, DONOR, "--seed", "1",
                                              "--ambition", "80", "--powatch",
                                              "--list"))
                    red_map = work / "q2dm1_redstorey.map"
                    red_bsp = red_map.with_suffix(".bsp")
                    red_bsp.unlink(missing_ok=True)
                    if red_st and red_st[0]["edit"] is not None:
                        drive(fill_exe, DONOR, "--seed", "1", "--ambition", "80",
                              "--powatch", "--apply", str(red_st[0]["edit"]),
                              "--out", str(red_map))
                        red_bsp.unlink(missing_ok=True)
                        compile_map(red_map)
                    got = (storey_fill_wrong(red_bsp, red_st[0])
                           if red_st and red_bsp.is_file() else [])
                    check("RED: with the FILL rules of an inner segment reverted, the"
                          " storey compiled alone has a terrace that is a slab and"
                          " rock over its flight - the case above goes red",
                          any("terrace" in w for w in got)
                          and any("rock over the flight" in w for w in got),
                          "; ".join(got)
                          or f"{len(red_st)} storeys, map there: {red_bsp.is_file()}")
            finally:
                box.dispose()
                check("the shared worktree was never opened for writing",
                      hash_tree(REPO) == before)

    # ---- case 8: the SKY SKIN (ledger rows 351-354) ----------------------------
    #
    # The PO on mg_20q: «у тебя в них как будто небо вместо стенок/потолка снаружи
    # лежит» - a room dug past a courtyard's sky stood in the void, and from the
    # courtyard its far inner walls showed where the sky should be. A dig whose
    # roof rises past a sky near it wears a sky skin: a detail shell inside an
    # enclosure of sky, its outer faces drawn. The annex of seed 42 on q2dm1
    # `1840 112 897 -> 1872 880 1025` rises past the courtyard's sky: applied
    # alone it must be skinned once, compile sealed with its visibility, and leave
    # no new space the sky gate sees through the sky; with the skin's decision
    # taken out, the gate must see it.
    #
    if DONOR.is_file() and not a.quick:
        from check_mapgen_sky_portal import seen_through_sky, said as sky_said
        # row 412: the same wing of the two annexes off the courtyard, its far end now 1840 944 (the rooms' drawn
        # patterns, brief 9 D3, moved it from 1872 880)
        sky_dig = ("1840", "112", "897", "1840", "944", "1025")

        def compile_vis(path: Path) -> str:
            exe_c, threads = pinned()
            out = ""
            for stage in (["-bsp"], ["-vis"]):
                run = load_guard.run(
                    [str(exe_c)] + stage + ["-threads", threads, "-moddir", str(GAME),
                                            "-basedir", str(GAME), "-gamedir", str(GAME),
                                            str(path)],
                    capture_output=True, text=True, timeout=7200)
                out += run.stdout + run.stderr
            return out

        from check_mapgen_lift_pvs import measure as lift_pvs

        def sky_case(drv: Path, tag: str, *extra: str) -> dict:
            text = drive(drv, DONOR, "--seed", "42", "--ambition", "80", "--list")
            edit = next((m.group(1) for m in DIG_EDIT.finditer(text)
                         if tuple(m.group(i) for i in range(3, 9)) == sky_dig), None)
            got = {"edit": edit, "lifts": None, "leak": None, "found": None, "box": None,
                   "sky_lifts": None, "floor": None, "said": "", "pvs": None, "vis_s": None}
            if edit is None:
                return got
            segs = [[float(v) for v in m.group(1).split()] for m in re.finditer(
                rf"^  digseg {edit} \d+((?: -?\d+){{6}})$", text, re.M)]
            if not segs:
                return got
            got["box"] = ([min(s[i] for s in segs) for i in range(3)]
                          + [max(s[3 + i] for s in segs) for i in range(3)])
            mp = work / f"q2dm1_{tag}.map"
            said_apply = drive(drv, DONOR, "--seed", "42", "--ambition", "80",
                               "--apply", edit, *extra, "--out", str(mp))
            lifts = re.search(r"^sky skins (\d+)", said_apply, re.M)
            got["lifts"] = int(lifts.group(1)) if lifts else None
            # row 384: and the courtyard's sky lifted over it
            sl = re.search(r"^sky lifts (\d+), floor brushes (\d+)", said_apply, re.M)
            if sl:
                got["sky_lifts"], got["floor"] = int(sl.group(1)), int(sl.group(2))
            sd = re.search(r"^sky lift: (.*)$", said_apply, re.M)
            got["said"] = sd.group(1) if sd else ""
            bsp = mp.with_suffix(".bsp")
            bsp.unlink(missing_ok=True)
            t_vis = time.time()
            log = compile_vis(mp)
            got["vis_s"] = time.time() - t_vis
            got["leak"] = "leaked" in log or not bsp.is_file()
            if bsp.is_file():
                got["found"] = seen_through_sky(bsp, [{"box": got["box"]}])
                got["pvs"] = lift_pvs(bsp, DONOR, segs, 700.0)
            return got

        sky = sky_case(exe, "sky")
        check("q2dm1: seed 42 deals the annex that rises past the courtyard's sky",
              sky["edit"] is not None and sky["box"] is not None,
              f"edit {sky['edit']}, box {sky['box']}")
        check("q2dm1: applied alone it wears a sky skin - once, observed",
              sky["lifts"] == 1, f"sky skins {sky['lifts']}")
        check("q2dm1: and the map compiles sealed, with its visibility",
              sky["leak"] is False, f"leaked or no map: {sky['leak']}")
        f = sky["found"]
        check("q2dm1: and nothing new is seen through the sky",
              f is not None and not f[0],
              f"{f[1]} viewers, {f[2]} new points, {len(f[0])} seen: {sky_said(f[0])}"
              if f else "no map")

        # ---- case 8, row 384: the courtyard's sky LIFTED over it --------------
        #
        # Row 375: the skin gave the building outer faces but no portal to the
        # courtyard, so the visibility listed it from some courtyard places and
        # not from others - the flicker the PO filmed on mg_20r. Applied alone,
        # the annex lifts the courtyard's sky once, its floor a few dozen brushes
        # from the map's own solid leaves; compiled with its visibility, every
        # courtyard place within 700 that sees a point of the new air round the
        # building has that point's cluster in its PVS. RED with the lift
        # switched off (`--nolift`): the same annex in its skin alone is seen from
        # the courtyard where its PVS does not list it.
        #
        def pvs_said(r) -> str:
            if not r:
                return "no map"
            full = sum(1 for s, t in r["per_position"] if s == t)
            return (f"{r['positions']} positions, {r['targets']} points in {r['clusters']} clusters,"
                    f" {len(r['per_position'])} see some, {full} see all they should;"
                    f" {r['misses']} misses from {r['miss_positions']} positions")

        check("q2dm1: it lifts the courtyard's sky - once, observed, its floor under 200 brushes",
              sky["sky_lifts"] == 1 and sky["floor"] is not None and 0 < sky["floor"] < 200,
              f"sky lifts {sky['sky_lifts']}, floor {sky['floor']}: {sky['said']};"
              f" bsp+vis {sky['vis_s'] or 0:.0f} s")
        check("q2dm1: and from the courtyard the building is in the visibility wherever it is in sight",
              sky["pvs"] is not None and sky["pvs"]["misses"] == 0 and sky["pvs"]["targets"] > 0,
              pvs_said(sky["pvs"]))
        nolift = sky_case(exe, "nolift", "--nolift")
        check("RED: with the lift switched off the same annex is seen from the courtyard where its"
              " PVS does not list it - the case above goes red",
              nolift["sky_lifts"] == 0 and nolift["pvs"] is not None and nolift["pvs"]["misses"] > 0,
              f"sky lifts {nolift['sky_lifts']}; {pvs_said(nolift['pvs'])}")

        # ---- case 8, row 390: the lift's clip is the very shape of the sky ---
        #
        # Fable's brief 3, W1: the player's world is unchanged only if the clip
        # the lift lays stands where the sky (or rock) stood and nowhere else.
        # On a lattice through every clip brush of the lifted map inside the
        # lift's record: no point where the donor was open air. RED with the
        # clip piece taken as the carve box alone, it stands in the courtyard.
        #
        from check_mapgen_lift_pvs import clip_overreach

        def over_said(r) -> str:
            n, o, s = r
            return f"{n} points sampled, {o} in the donor's open air" + (
                ": " + "; ".join(" ".join(f"{v:.0f}" for v in p) for p in s) if s else "")

        sky_bsp = work / "q2dm1_sky.bsp"
        if check("case 8: the lifted map is there", sky_bsp.is_file(), str(sky_bsp)):
            over = clip_overreach(sky_bsp, DONOR)
            check("q2dm1: the lift's clip stands only where sky or rock stood - never in open air",
                  over[0] > 0 and over[1] == 0, over_said(over))
            before_clip = hash_tree(REPO)
            cbox = Sandbox(REPO, "digliftclip")
            try:
                target = cbox.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
                data = target.read_bytes()
                flag = b"static const bool g_lift_clip_shaped = true;"
                if check("RED: the clip's shape rule is where the mutation says", data.count(flag) == 1,
                         f"{data.count(flag)} occurrences"):
                    target.write_bytes(data.replace(flag, b"static const bool g_lift_clip_shaped = false;", 1))
                    red_dir = work / "red_liftclip"
                    red_dir.mkdir(parents=True, exist_ok=True)
                    red_exe = build_driver(cbox.root, red_dir)
                    text_c = drive(red_exe, DONOR, "--seed", "42", "--ambition", "80", "--list")
                    ed_c = next((m.group(1) for m in DIG_EDIT.finditer(text_c)
                                 if tuple(m.group(i) for i in range(3, 9)) == sky_dig), None)
                    red_over = (0, 0, [])
                    if ed_c is not None:
                        mp_c = work / "q2dm1_redliftclip.map"
                        drive(red_exe, DONOR, "--seed", "42", "--ambition", "80", "--apply", ed_c,
                              "--out", str(mp_c))
                        mp_c.with_suffix(".bsp").unlink(missing_ok=True)
                        exe_c, threads = pinned()
                        load_guard.run([str(exe_c), "-bsp", "-threads", threads, "-moddir", str(GAME),
                                        "-basedir", str(GAME), "-gamedir", str(GAME), str(mp_c)],
                                       capture_output=True, text=True, timeout=1800)
                        if mp_c.with_suffix(".bsp").is_file():
                            red_over = clip_overreach(mp_c.with_suffix(".bsp"), DONOR)
                    check("RED: with the clip taken as the carve box alone it stands in the donor's open air -"
                          " the case above goes red", red_over[1] > 0, over_said(red_over))
            finally:
                cbox.dispose()
                check("the shared worktree was never opened for writing", hash_tree(REPO) == before_clip)
        before_sky = hash_tree(REPO)
        sbox = Sandbox(REPO, "digsky")
        try:
            target = sbox.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            call = b"(g_dig_passes & DIG_PASS_SHELL) && dig_needs_skin(g, d);"
            if check("RED: the skin's decision is where the mutation says",
                     data.count(call) == 1, f"{data.count(call)} occurrences"):
                target.write_bytes(data.replace(
                    call, b"(g_dig_passes & DIG_PASS_SHELL) && false && dig_needs_skin(g, d);", 1))
                red_dir = work / "red_sky"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(sbox.root, red_dir)
                red = sky_case(red_exe, "redsky")
                rf_ = red["found"]
                check("RED: with the skin's decision taken out, the same annex wears none and"
                      " the gate sees its new space through the sky - the case above goes red",
                      red["lifts"] == 0 and rf_ is not None and bool(rf_[0]),
                      f"sky skins {red['lifts']}; "
                      + (f"{len(rf_[0])} seen: {sky_said(rf_[0])}" if rf_ else "no map"))
        finally:
            sbox.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before_sky)

    # ---- case 9: dealt digs keep both skins' room (ledger row 361) ------------
    #
    # Fable's brief C2: a skinned dig owns a band of shell 16 + gap 16 + voxel 8
    # round its segments; the digs one plan deals keep both bands between them -
    # 80 between interiors - in all four deals (tunnels, annexes, storeys, wing
    # links). Two annexes 32 apart opened the second into the first's gap (rows
    # 357, 359). Every pair of segments of two different dealt digs, six seeds.
    #
    if DONOR.is_file():
        clear = 80.0
        seg_re = re.compile(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$", re.M)

        def closest_pair(text: str):
            segs = [(int(m.group(1)), [float(v) for v in m.group(3).split()])
                    for m in seg_re.finditer(text)]
            best = None
            for i in range(len(segs)):
                for j in range(i + 1, len(segs)):
                    if segs[i][0] == segs[j][0]:
                        continue
                    a, b = segs[i][1], segs[j][1]
                    sep = max(max(b[k] - a[3 + k], a[k] - b[3 + k]) for k in range(3))
                    if best is None or sep < best[0]:
                        best = (sep, segs[i][0], segs[j][0])
            return best

        def deal_counts(text: str) -> str:
            got = []
            for label, rx in (("annexes", r"dig annexes: (\d+) dealt"),
                              ("storeys", r"dig storeys dealt: (\d+)"),
                              ("wings", r"dig annex wings: (\d+) joined")):
                m = re.search(rx, text)
                got.append(f"{label} {m.group(1) if m else '?'}")
            got.append(f"halls {len(list(HALL.finditer(text)))}")
            got.append(f"digs {len(list(DIG_EDIT.finditer(text)))}")
            return ", ".join(got)

        seeds = ("1", "2", "3", "7", "42", "1020")
        worst, said9 = None, []
        for s in seeds:
            text = drive(exe, DONOR, "--seed", s, "--ambition", "80", "--list")
            c = closest_pair(text)
            said9.append(f"seed {s}: closest {c[0]:.0f} ({deal_counts(text)})" if c
                         else f"seed {s}: one dig or none")
            if c and (worst is None or c[0] < worst[0]):
                worst = (c[0], s)
        check("q2dm1: the digs one plan deals keep 80 between them - both skins' room",
              worst is None or worst[0] >= clear - 0.01, "; ".join(said9))
        before9 = hash_tree(REPO)
        box9 = Sandbox(REPO, "digclear")
        try:
            target = box9.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            line = b"#define DIG_DEALT_CLEAR  (2.0f * (DIG_SHELL + SKY_SKIN_GAP + SKY_SKIN_VOXEL))"
            if check("RED: the dealt clearance is where the mutation says",
                     data.count(line) == 1, f"{data.count(line)} occurrences"):
                target.write_bytes(data.replace(
                    line, b"#define DIG_DEALT_CLEAR  (2.0f * DIG_SHELL)", 1))
                red_dir = work / "red_clear"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_exe = build_driver(box9.root, red_dir)
                red_worst = None
                for s in seeds:
                    c = closest_pair(drive(red_exe, DONOR, "--seed", s, "--ambition", "80",
                                           "--list"))
                    if c and (red_worst is None or c[0] < red_worst[0]):
                        red_worst = (c[0], s)
                check("RED: with two shells' clearance back, digs are dealt closer than 80 -"
                      " the case above goes red", red_worst is not None and red_worst[0] < clear,
                      f"closest {red_worst[0]:.0f} at seed {red_worst[1]}" if red_worst else "none")
        finally:
            box9.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before9)

    # ---- case 10: no edit changes another dig's band (ledger row 362) --------
    #
    # Fable's brief C2 for every family: each dig records its band (its shell,
    # its whole skin when it wears one) and `ApplyOne` declines an edit that
    # changes what stands in another dig's band. Staged with the dealt clearance
    # back to two shells (so the plan deals two digs too close), on a driver
    # built in a sandbox: the closer pair at seed 1, applied in both orders - the
    # second must be declined each time; RED with the comparison taken out, it
    # is applied.
    #
    if DONOR.is_file():
        clear_line = b"#define DIG_DEALT_CLEAR  (2.0f * (DIG_SHELL + SKY_SKIN_GAP + SKY_SKIN_VOXEL))"
        check_line = b"static const bool g_skin_band_check = true;"
        band_exes = {}
        before10 = hash_tree(REPO)
        for tag, keep_check in (("bandon", True), ("bandoff", False)):
            box10 = Sandbox(REPO, "dig" + tag)
            try:
                target = box10.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
                data = target.read_bytes()
                if not check(f"{tag}: the clearance and the band check are where the staging says",
                             data.count(clear_line) == 1 and data.count(check_line) == 1,
                             f"{data.count(clear_line)}, {data.count(check_line)}"):
                    continue
                data = data.replace(clear_line, b"#define DIG_DEALT_CLEAR  (2.0f * DIG_SHELL)", 1)
                if not keep_check:
                    data = data.replace(check_line, b"static const bool g_skin_band_check = false;", 1)
                target.write_bytes(data)
                d10 = work / tag
                d10.mkdir(parents=True, exist_ok=True)
                band_exes[tag] = build_driver(box10.root, d10)
            finally:
                box10.dispose()
        check("the shared worktree was never opened for writing", hash_tree(REPO) == before10)
        if len(band_exes) == 2:
            seg10 = re.compile(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$", re.M)
            text = drive(band_exes["bandon"], DONOR, "--seed", "1", "--ambition", "80", "--list")
            segs = [(int(m.group(1)), [float(v) for v in m.group(3).split()])
                    for m in seg10.finditer(text)]
            near = {}
            for i in range(len(segs)):
                for j in range(i + 1, len(segs)):
                    if segs[i][0] == segs[j][0]:
                        continue
                    a, b = segs[i][1], segs[j][1]
                    sep = max(max(b[k] - a[3 + k], a[k] - b[3 + k]) for k in range(3))
                    key = (min(segs[i][0], segs[j][0]), max(segs[i][0], segs[j][0]))
                    near[key] = min(sep, near.get(key, sep))
            pairs10 = sorted((sep, e1, e2) for (e1, e2), sep in near.items())
            pair = pairs10[0] if pairs10 else None
            check("staging: with two shells' clearance the plan at seed 1 deals two digs"
                  " within 40 of each other", pair is not None and pair[0] < 41.0,
                  f"closest {pair[0]:.0f}, edits {pair[1]} and {pair[2]}" if pair else "none")
            if pair is not None:
                def second(exe10: Path, first: int, then: int) -> str:
                    out = drive(exe10, DONOR, "--seed", "1", "--ambition", "80",
                                "--apply", str(first), "--apply", str(then),
                                "--out", str(work / f"q2dm1_band_{first}_{then}.map"))
                    return next((l for l in out.splitlines() if "declined:" in l), "")
                # row 412: of the pairs within 40 (up to four, closest first) the first on which the band rule
                # itself refuses - the closest one may be refused both ways by the skin's rock rule alone (seed 1
                # after brief 9's room patterns: edits 83 and 98)
                for cand10 in [p for p in pairs10 if p[0] < 41.0][:4]:
                    pair = cand10
                    on = [second(band_exes["bandon"], pair[1], pair[2]),
                          second(band_exes["bandon"], pair[2], pair[1])]
                    if any("shell or sky skin" in s for s in on):
                        break
                # row 373: in one order the skin's own rock rule may decline the
                # second first - the first dig's shell is rock against the sky
                # in the second's band; either refusal names the first dig
                check("q2dm1: an edit that would change another dig's shell or skin is"
                      " declined - in both orders",
                      all("shell or sky skin" in s or "rock it cannot clear" in s for s in on)
                      and any("shell or sky skin" in s for s in on),
                      " | ".join(on) or "none declined")
                off = [second(band_exes["bandoff"], pair[1], pair[2]),
                       second(band_exes["bandoff"], pair[2], pair[1])]
                check("RED: with the band comparison taken out, the order the band rule refused is"
                      " applied - the case above goes red",
                      all(not o for s, o in zip(on, off) if "shell or sky skin" in s),
                      " | ".join(off) or "applied")

    # ---- case 11: old air is the original donor's too (ledger row 364) -------
    #
    # Fable's brief C3. Rounds 44-45: an annex applied after another of the
    # same plan found the first's skin gap as air in the accepted map and left
    # its shell out on that side, as at a doorway. Round45's job baseline at
    # seed 42 deals the two annexes 32 apart when the dealt clearance is staged
    # back to two shells; the first is applied and compiled, the second applied
    # alone over it (`--ground-after`, as the transaction does) and compiled -
    # sealed with the rule, leaked with it taken out.
    #
    base11 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round45\s3_42\job\baseline\q2mg_f20.bsp")
    if check("case 11: round45's job baseline is there", base11.is_file(), str(base11)):
        clear_line = b"#define DIG_DEALT_CLEAR  (2.0f * (DIG_SHELL + SKY_SKIN_GAP + SKY_SKIN_VOXEL))"
        rule_line = (b"    return donor_air(ground, x, y, z) && (!g_dig_original || donor_air(g_dig_original,"
                     b" x, y, z));")
        exes11 = {}
        before11 = hash_tree(REPO)
        for tag, keep in (("oldair", True), ("noold", False)):
            box11 = Sandbox(REPO, "dig" + tag)
            try:
                target = box11.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
                data = target.read_bytes()
                if not check(f"{tag}: the clearance and the old-air rule are where the staging says",
                             data.count(clear_line) == 1 and data.count(rule_line) == 1,
                             f"{data.count(clear_line)}, {data.count(rule_line)}"):
                    continue
                data = data.replace(clear_line, b"#define DIG_DEALT_CLEAR  (2.0f * DIG_SHELL)", 1)
                if not keep:
                    data = data.replace(rule_line, b"    return donor_air(ground, x, y, z);", 1)
                target.write_bytes(data)
                d11 = work / tag
                d11.mkdir(parents=True, exist_ok=True)
                exes11[tag] = build_driver(box11.root, d11)
            finally:
                box11.dispose()
        check("the shared worktree was never opened for writing", hash_tree(REPO) == before11)

        def compile_bsp11(mp: Path) -> str:
            exe_c, threads = pinned()
            mp.with_suffix(".bsp").unlink(missing_ok=True)
            run = load_guard.run([str(exe_c), "-bsp", "-threads", threads, "-moddir", str(GAME),
                                  "-basedir", str(GAME), "-gamedir", str(GAME), str(mp)],
                                 capture_output=True, text=True, timeout=1800)
            return run.stdout + run.stderr

        # row 412: seed 16, the wings not joined (--annexgap 1) - at 42 brief 9's room patterns join the two annexes
        # off the courtyard into one wing; at 16 the first is the same, the second 32 from it
        # (`tools/mapgen_find_close_annexes.py`, seeds 1..60: 11, 13, 16, 31, 32, 39, 41, 50, 59 deal such a pair)
        SEED11 = "16"
        if len(exes11) == 2:
            text = drive(exes11["oldair"], base11, "--seed", SEED11, "--ambition", "80", "--annexgap", "1", "--list")
            ids = {tuple(m.group(i) for i in range(3, 9)): m.group(1) for m in DIG_EDIT.finditer(text)}
            a11 = ids.get(("1840", "112", "896", "2336", "112", "896"))
            b11 = ids.get(("1872", "848", "1024", "2144", "848", "1024"))
            if check("staging: the two annexes are dealt", a11 is not None and b11 is not None,
                     f"{a11}, {b11}"):
                # Row 387: with the sky lift switched off (`--nolift`). This case asks the skin's old-air rule,
                # and `--ground-after` applies the second annex to the BASE geometry over the first's compiled
                # map - a pair the transaction never builds (its candidate is the accepted geometry itself); a
                # lift there floors against air the first lift made that the base does not have, and leaks. The
                # lift over two digs is case 4's (every dig of a plan on one map) and case 8's.
                first = work / "q2dm1_oldair_first.map"
                drive(exes11["oldair"], base11, "--seed", SEED11, "--ambition", "80", "--annexgap", "1", "--nolift", "--apply", a11,
                      "--out", str(first))
                log = compile_bsp11(first)
                check("staging: the first annex compiles sealed", "leaked" not in log
                      and first.with_suffix(".bsp").is_file())
                got = {}
                for tag, exe11 in exes11.items():
                    mp = work / f"q2dm1_oldair_second_{tag}.map"
                    drive(exe11, base11, "--seed", SEED11, "--ambition", "80", "--annexgap", "1", "--nolift", "--ground-after",
                          str(first.with_suffix(".bsp")), "--apply", b11, "--out", str(mp))
                    log = compile_bsp11(mp)
                    got[tag] = "leaked" in log or not mp.with_suffix(".bsp").is_file()
                check("q2dm1: the second annex, applied over the first, closes its shell and skin"
                      " toward the first's gap - sealed", got.get("oldair") is False,
                      f"leaked: {got.get('oldair')}")
                check("RED: with old air taken as the accepted map's alone, it leaves them out and"
                      " leaks - the case above goes red", got.get("noold") is True,
                      f"leaked: {got.get('noold')}")

    # ---- case 12: skins stay dealt; rock against the sky counted (row 367) ---
    #
    # Fable's brief C4, narrowed: rock the band carve could not clear refuses
    # the dig only where it lies against a sky brush - taken literally (any rock
    # left in the band) it refused every skinned dig on q2dm1, a feature lost.
    # Every dig the plan deals at seeds 42 and 1020, applied alone: the skins
    # built and the rock refusals, printed; at least one skin at each seed.
    #
    if DONOR.is_file():
        said12 = []
        alive = True
        for s in ("42", "1020"):
            text = drive(exe, DONOR, "--seed", s, "--ambition", "80", "--list")
            skins = refusals = 0
            for m in DIG_EDIT.finditer(text):
                out = drive(exe, DONOR, "--seed", s, "--ambition", "80", "--apply", m.group(1),
                            "--out", str(work / "q2dm1_case12.map"))
                for line in out.splitlines():
                    if line.startswith("sky skins "):
                        skins += int(line.split()[2])
                    if line.startswith("skin rock refusals "):
                        refusals += int(line.split()[3])
            said12.append(f"seed {s}: {len(list(DIG_EDIT.finditer(text)))} digs, {skins} skinned,"
                          f" {refusals} refused for rock against the sky")
            alive = alive and skins >= 1
        check("q2dm1: the digs that need a sky skin are dealt and wear it - none lost to the"
              " rock rule", alive, "; ".join(said12))

    # ---- case 13: a crack inside a skin's gap is no crack in the world (369) --
    #
    # Round45's storey `1424 1584 768 -> 1840 1200 1024` was refused for a new
    # seam at 1568 1280 926: the skin's band carve exposed an old block's face
    # INTO the sealed gap. The transaction spares a seam that
    # `MapGenGeometryEdit_InSkinGap` places in a skinned dig's gap; asked of the
    # storey alone on round45's baseline - the crack yes, a far floor seam
    # (615 102 440, row 344's re-partition) and a point in the room no; RED
    # with the function made to answer no.
    #
    base13 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round45\s3_42\job\baseline\q2mg_f20.bsp")
    if check("case 13: round45's job baseline is there", base13.is_file(), str(base13)):
        pts = (("1568", "1280", "926", 1), ("615", "102", "440", 0), ("1700", "1500", "1000", 0))

        def gap_answers(exe13: Path) -> dict:
            text = drive(exe13, base13, "--seed", "42", "--ambition", "80", "--list")
            edit = next((m.group(1) for m in DIG_EDIT.finditer(text)
                         if tuple(m.group(i) for i in range(3, 9))
                         == ("1424", "1584", "768", "1840", "1200", "1024")), None)
            if edit is None:
                return {}
            args = ["--seed", "42", "--ambition", "80", "--apply", edit]
            for x, y, z, _ in pts:
                args += ["--gapat", x, y, z]
            out = drive(exe13, base13, *args, "--out", str(work / "q2dm1_gap13.map"))
            return {m.group(1): int(m.group(2))
                    for m in re.finditer(r"^in skin gap (-?\d+ -?\d+ -?\d+): (\d)", out, re.M)}

        got = gap_answers(exe)
        check("q2dm1: the storey's crack lies in its skin gap; a far floor and its room do not",
              all(got.get(f"{x} {y} {z}") == want for x, y, z, want in pts), str(got) or "storey not dealt")
        impl = (REPO / "src" / "mapgen" / "mapgen_transaction.c").read_text(encoding="utf-8", errors="replace")
        check("the transaction asks it of every new seam, behind its own switch",
              "&& MapGenGeometryEdit_InSkinGap(candidate, seam[s].split)" in impl
              and "static const bool g_txn_skin_gap_spared = true;" in impl)
        before13 = hash_tree(REPO)
        box13 = Sandbox(REPO, "diggap")
        try:
            target = box13.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
            data = target.read_bytes()
            head = b"bool MapGenGeometryEdit_InSkinGap(const mapgen_geometry_t *g, const float p[3])\n{\n"
            if b"\r\n" in data:
                head = head.replace(b"\n", b"\r\n")
            if check("RED: the gap question is where the mutation says", data.count(head) == 1,
                     f"{data.count(head)} occurrences"):
                target.write_bytes(data.replace(head, head + b"    if (g) return false;\n", 1))
                red_dir = work / "red_gap"
                red_dir.mkdir(parents=True, exist_ok=True)
                red_got = gap_answers(build_driver(box13.root, red_dir))
                check("RED: with the gap question answering no, the storey's crack is not spared -"
                      " the case above goes red", red_got.get("1568 1280 926") == 0, str(red_got))
        finally:
            box13.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before13)

    # ---- case 14: the transaction refuses a dig seen through the sky (372) -----
    #
    # Fable's brief C6: `REJECTED_SKY`, the rule of `check_mapgen_sky_portal.py`
    # on every skinned dig's own compile (no PVS there). `mapgen_sky_probe` is
    # that very function: asked of case 8's maps - the donor annex in its skin
    # (pass) and without it (refuse) - and of mg_20q, the map the PO refused.
    #
    sky8 = work / "q2dm1_sky.bsp"
    red8 = work / "q2dm1_redsky.bsp"
    mg20q = GAME / "maps" / "mg_20q.bsp"
    if check("case 14: case 8's two maps and mg_20q are there",
             sky8.is_file() and red8.is_file() and mg20q.is_file(),
             f"{sky8.is_file()}, {red8.is_file()}, {mg20q.is_file()}"):
        import subprocess as _sp
        sys.path.insert(0, str(REPO / "tools"))
        from check_mapgen_transaction import SOURCES as TXN_SOURCES
        probe14 = work / "sky_probe.exe"
        probe14.unlink(missing_ok=True)
        srcs = [s for s in TXN_SOURCES if s != "tools/mapgen_transaction_driver.c"] + ["tools/mapgen_sky_probe.c"]
        built14 = load_guard.run(
            ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"), "-I" + str(REPO / "src" / "mapgen"),
             "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
            + [str(REPO / s) for s in srcs] + ["-o", str(probe14), "-lm"],
            capture_output=True, text=True)
        if check("the sky probe builds from the transaction's own source", probe14.is_file(),
                 built14.stderr[-400:]):
            box8 = [str(v) for v in (1824, 96, 897, 2176, 960, 1281)]
            text8 = drive(exe, DONOR, "--seed", "42", "--ambition", "80", "--list")
            ed8 = next((m.group(1) for m in DIG_EDIT.finditer(text8)
                        if tuple(m.group(i) for i in range(3, 9))
                        == ("1840", "112", "897", "1872", "880", "1025")), None)
            if ed8 is not None:
                s8 = [[float(v) for v in m.group(1).split()] for m in re.finditer(
                    rf"^  digseg {ed8} \d+((?: -?\d+){{6}})$", text8, re.M)]
                if s8:
                    box8 = [f"{min(s[i] for s in s8):.0f}" for i in range(3)] + \
                           [f"{max(s[3 + i] for s in s8):.0f}" for i in range(3)]

            def ask14(bsp: Path, donor: Path, box: list) -> str:
                return load_guard.run([str(probe14), str(bsp), str(donor), *box],
                                      capture_output=True, text=True, timeout=600).stdout.strip()

            green = ask14(sky8, DONOR, box8)
            check("q2dm1: the transaction's sky rule passes the annex in its skin", green == "seen 0", green)
            red = ask14(red8, DONOR, box8)
            check("RED: and refuses the same annex without its skin - the case above goes red",
                  red.startswith("seen 1"), red)
            q = ask14(mg20q, DONOR, ["1904", "528", "1024", "2464", "1040", "1312"])
            check("q2dm1: and refuses mg_20q's annex, the PO's quake162", q.startswith("seen 1"), q)
        impl14 = (REPO / "src" / "mapgen" / "mapgen_transaction.c").read_text(encoding="utf-8", errors="replace")
        check("the transaction asks it of every skinned dig and refuses as REJECTED_SKY",
              "if (s_attempt_skinned && g_txn_sky_check) {" in impl14
              and "MapGenTransaction_SeenThroughSky(built, txn->donor_bsp, slo, shi, witness)" in impl14
              and "return step->verdict = MAPGEN_TXN_REJECTED_SKY;" in impl14
              and "static const bool g_txn_sky_check = true;" in impl14)

    # ---- case 15: the donor's own near-line corner is no new crack (row 382) ---
    #
    # Round48's one map stopped after its fifth accepted edit: every attempt,
    # anywhere, was refused for «a new crack in the world at 1526 512 560» -
    # q2dm1's own sliver of floor at a diagonal wall, 0.517 off the wall's edge
    # in the donor (outside the rule's 0.5, so no witness) and 0.481 in the
    # later compiles. The transaction takes the donor's witnesses at twice the
    # reach. `mapgen_seam_probe` asks the transaction's own functions: round48's
    # try_0022 against the donor 0 new; RED with the reach back at 0.5 in a
    # sandbox, 1 new there; control: round45's try_0115 keeps its real crack at
    # 1568 1280 926 new; the donor's witnesses a handful, that corner among them.
    #
    try22 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round48\s3_42\job\try_0022\q2mg_f20.bsp")
    try115 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round45\s3_42\job\try_0115\q2mg_f20.bsp")
    if check("case 15: round48's try_0022, round45's try_0115 and the donor are there",
             try22.is_file() and try115.is_file() and DONOR.is_file(),
             f"{try22.is_file()}, {try115.is_file()}, {DONOR.is_file()}"):
        import ast as _ast
        txn_src = (REPO / "tools" / "check_mapgen_transaction.py").read_text(encoding="utf-8")
        sources15 = _ast.literal_eval(re.search(r"^SOURCES = (\[.*?\])", txn_src, re.M | re.S).group(1))

        def seam_probe(tree: Path, exe15: Path) -> Path:
            exe15.unlink(missing_ok=True)
            srcs = [s for s in sources15 if s != "tools/mapgen_transaction_driver.c"] + ["tools/mapgen_seam_probe.c"]
            built15 = load_guard.run(
                ["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"), "-I" + str(tree / "src" / "mapgen"),
                 "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                + [str(tree / s) for s in srcs] + ["-o", str(exe15), "-lm"],
                capture_output=True, text=True)
            if not exe15.is_file():
                print(built15.stderr[-1500:])
            return exe15

        def ask15(exe15: Path, bsp: Path) -> tuple:
            out15 = load_guard.run([str(exe15), str(bsp), str(DONOR)], capture_output=True, text=True,
                                   timeout=600).stdout
            tally = re.search(r"^witnesses (\d+), seams (\d+), new (\d+)$", out15, re.M)
            new = re.findall(r"^seam at (\S+ \S+ \S+) on the edge .* new$", out15, re.M)
            wit = re.findall(r"^donor witness at (\S+ \S+ \S+) ", out15, re.M)
            return (tuple(int(v) for v in tally.groups()) if tally else None), new, wit

        exe15 = seam_probe(REPO, work / "seam_probe.exe")
        if check("the seam probe builds from the transaction's own source", exe15.is_file()):
            t22, new22, wit = ask15(exe15, try22)
            check("q2dm1: the donor's witnesses are a handful (16 or fewer) and name its floor sliver at"
                  " 1525.6 512 560", bool(t22) and t22[0] <= 16 and "1525.6 512.0 560.0" in wit,
                  f"{t22[0] if t22 else '?'} witnesses: {'; '.join(wit[:8])}")
            check("q2dm1: round48's try_0022 has the sliver as its one world seam, and no new one",
                  bool(t22) and t22[1] >= 1 and t22[2] == 0, f"{t22}; new {new22}")
            t115, new115, _ = ask15(exe15, try115)
            check("control: round45's try_0115 keeps its real crack at 1568 1280 926 new",
                  bool(t115) and any(n.startswith("1568.0 1280.0 92") for n in new115), f"{t115}; new {new115}")
        impl15 = (REPO / "src" / "mapgen" / "mapgen_transaction.c").read_text(encoding="utf-8", errors="replace")
        check("the transaction judges with the same two functions",
              "MapGenTransaction_DonorSeams(txn->donor_bsp, txn->donor_seam," in impl15
              and "if (MapGenTransaction_NewSeam(&seam[s], txn->donor_seam," in impl15)
        before15 = hash_tree(REPO)
        box15 = Sandbox(REPO, "digseamreach")
        try:
            target = box15.root / "src" / "mapgen" / "mapgen_transaction.c"
            data = target.read_bytes()
            reach = b"static const float g_txn_donor_seam_reach = 1.0f;"
            if check("RED: the donor's reach is where the mutation says", data.count(reach) == 1,
                     f"{data.count(reach)} occurrences"):
                target.write_bytes(data.replace(reach, b"static const float g_txn_donor_seam_reach = 0.5f;", 1))
                red15 = seam_probe(box15.root, work / "seam_probe_red.exe")
                rt, rnew, _ = ask15(red15, try22) if red15.is_file() else (None, [], [])
                check("RED: with the donor's witnesses at the candidate's 0.5 the sliver is a new crack - the case"
                      " above goes red", bool(rt) and rt[2] == 1 and rnew and rnew[0].startswith("1525.6 512.0"),
                      f"{rt}; new {rnew}")
        finally:
            box15.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before15)

    print(f"\n{CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
