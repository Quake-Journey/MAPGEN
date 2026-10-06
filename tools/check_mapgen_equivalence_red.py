"""Can the baseline gate see the damage it exists to see?

Codex's ruling of 2026-09-03, section 4.3, lists the damage that must each be
refused for its own reason: world solid, reachable empty space, liquid and
hazard contents, a visible surface, a texture mapping, model ownership, a mover
target, a trigger, an areaportal, a spawn, item or light, and a traversal
obligation. It also requires the opposite: a change that only splits or merges,
with the same meaning, must stay GREEN.

Every case below starts from a pair the gate calls equivalent - q2dm1 and its
own no-edit round trip through the frozen compiler - damages ONE thing, and
asserts the axis that fired. A case that fires the wrong axis fails here, so a
gate that returned "something is wrong" for everything would not pass.

    python tools/check_mapgen_equivalence_red.py [--work DIR] [--keep]
"""
from __future__ import annotations

import argparse
import struct
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_bsp_edit as E                                    # noqa: E402

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260903"
                    r"\equivgate\red")

AXIS = {
    "space": 1 << 0,
    "architecture": 1 << 1,
    "surface": 1 << 2,
    "mapping": 1 << 3,
    "ownership": 1 << 4,
    "entity": 1 << 5,
    "mover": 1 << 6,
    "traversal": 1 << 7,
}

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILED += 1
    return ok


def build_driver(work: Path) -> Path:
    exe = work / "equiv.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I" + str(REPO / "inc"),
         str(REPO / "tools/mapgen_equivalence_driver.c"),
         str(REPO / "src/mapgen/mapgen_equivalence.c"),
         str(REPO / "src/mapgen/mapgen_bsp.c"),
         str(REPO / "src/mapgen/mapgen_movers.c"),
         str(REPO / "src/mapgen/mapgen_trace.c"),
         "-o", str(exe), "-lm"], capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the equivalence driver")
    return exe


def build_fork(work: Path) -> Path:
    exe = work / "fork.exe"
    files = ["tools/mapgen_geometry_fork.c", "src/mapgen/mapgen_geometry.c",
             "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_bsp.c",
             "src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_rooms.c",
             "src/mapgen/mapgen_bundle.c", "src/mapgen/mapgen_closure.c"]
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc")]
        + [str(REPO / f) for f in files] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the fork tool")
    return exe


FIXTURE = "everything"


def make_fixture_donor(work: Path, which: str = FIXTURE) -> Path | None:
    """A small map with one of everything the gate compares.

    Compiled by the pinned compiler, so the donor and the baseline come from
    the same toolchain and any difference between them belongs to the round
    trip. It carries a clip brush, a ladder, water, a door, a trigger that
    fires it, an item and a light, so no mandatory mutation has nothing to
    damage - a skipped mandatory RED is a failure, not a pass.
    """
    import sys as _sys
    _sys.path.insert(0, str(REPO / "tools"))
    import mapgen_equivalence_fixture as fixtures

    source = work / f"{which}.map"
    bsp = source.with_suffix(".bsp")
    if bsp.is_file():
        return bsp
    fixtures.FIXTURES[which](source)
    run = subprocess.run(
        [str(COMPILER), "-bsp", "-threads", "8", "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(source)],
        capture_output=True, text=True, timeout=3600)
    if not bsp.is_file():
        print((run.stdout + run.stderr)[-800:])
        return None
    return bsp


def make_baseline(fork: Path, donor: Path, work: Path) -> Path:
    """The donor's own geometry, nothing applied, through the frozen
    compiler. This is B, and the gate exists to decide whether it is D."""
    out = work / f"{donor.stem}_base.map"
    bsp = out.with_suffix(".bsp")
    if bsp.is_file():
        return bsp
    run = subprocess.run([str(fork), str(donor), str(out), "100"],
                         capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stdout[-1500:], run.stderr[-1500:])
        raise SystemExit("the fork refused the donor")
    run = subprocess.run(
        [str(COMPILER), "-bsp", "-threads", "8", "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(out)],
        capture_output=True, text=True, timeout=3600)
    if run.returncode != 0 or not bsp.is_file():
        print((run.stdout + run.stderr)[-1500:])
        raise SystemExit("the compiler refused the baseline")
    return bsp


def gate(exe: Path, donor: Path, baseline: Path) -> tuple[int, str]:
    run = subprocess.run([str(exe), str(donor), str(baseline)],
                         capture_output=True, text=True, timeout=600)
    mask = 0
    for line in run.stdout.splitlines():
        if line.startswith("failed_axes "):
            mask = int(line.split()[1], 16)
    detail = ""
    for line in run.stdout.splitlines():
        if line.startswith("detail "):
            detail = line[7:]
    if run.returncode == 2:
        raise SystemExit(f"the gate could not run: {run.stdout}{run.stderr}")
    return mask, detail


# ---- the mutations -------------------------------------------------------
#
# Each takes the loaded baseline and damages exactly one thing. Returning
# False means this map has nothing of that kind to damage, and the case is
# reported as skipped rather than passed.

def m_world_solid_removed(b: E.BspFile) -> bool:
    leaf = E.leaf_of_class(b, "solid")
    if leaf is None:
        return False
    for brush in b.leaf_brushes(leaf):
        b.set_brush_contents(brush, 0)
    b.set_leaf_contents(leaf, 0)
    return True


def m_empty_space_filled(b: E.BspFile) -> bool:
    leaf = E.leaf_of_class(b, "empty", min_brushes=0)
    if leaf is None:
        return False
    b.set_leaf_contents(leaf, E.CONTENTS_SOLID)
    return True


def m_liquid_lost(b: E.BspFile) -> bool:
    leaf = E.leaf_of_class(b, "liquid", min_brushes=0)
    if leaf is None:
        return False
    for brush in b.leaf_brushes(leaf):
        b.set_brush_contents(brush, 0)
    b.set_leaf_contents(leaf, 0)
    return True


def m_liquid_becomes_hazard(b: E.BspFile) -> bool:
    leaf = E.leaf_of_class(b, "liquid", min_brushes=0)
    if leaf is None:
        return False
    for brush in b.leaf_brushes(leaf):
        b.set_brush_contents(brush, E.CONTENTS_LAVA)
    b.set_leaf_contents(leaf, E.CONTENTS_LAVA)
    return True


def _busiest_texinfo(b: E.BspFile) -> int:
    used: dict[int, int] = {}
    for i in range(b.count(E.L_FACES, E.SZ_FACE)):
        ti = b.face(i)[4]
        if ti >= 0:
            used[ti] = used.get(ti, 0) + 1
    return max(used, key=lambda k: used[k])


def m_surface_material_changed(b: E.BspFile) -> bool:
    ti = _busiest_texinfo(b)
    b.set_texinfo_name(ti, "e2u3/notarealtexture")
    return True


def m_texture_slid(b: E.BspFile) -> bool:
    ti = _busiest_texinfo(b)
    axis = list(b.texinfo_axis(ti))
    axis[3] += 16.0                     # the u offset, by half a texture
    b.set_texinfo_axis(ti, axis)
    return True


def m_model_bounds_changed(b: E.BspFile) -> bool:
    if b.count(E.L_MODELS, E.SZ_MODEL) < 2:
        return False
    m = b.model(1)
    mins, maxs = list(m[0:3]), list(m[3:6])
    maxs[2] += 32.0
    b.set_model_bounds(1, mins, maxs)
    return True


def m_mover_target_lost(b: E.BspFile) -> bool:
    blocks = E.entity_blocks(b.entities)
    at = E.find_block_prefix(blocks, "func_")
    if at is None:
        return False
    blocks[at] = E.set_block_value(blocks[at], "targetname", "nothing_fires_me")
    b.entities = E.blocks_to_text(blocks)
    return True


def m_areaportal_opened(b: E.BspFile) -> bool:
    leaf = E.leaf_of_class(b, "empty", min_brushes=0)
    if leaf is None:
        return False
    b.set_leaf_contents(leaf, E.CONTENTS_AREAPORTAL)
    return True


def m_item_removed(b: E.BspFile) -> bool:
    blocks = E.entity_blocks(b.entities)
    at = E.find_block_prefix(blocks, "item_")
    if at is None:
        at = E.find_block_prefix(blocks, "weapon_")
    if at is None:
        return False
    del blocks[at]
    b.entities = E.blocks_to_text(blocks)
    return True


def m_light_removed(b: E.BspFile) -> bool:
    blocks = E.entity_blocks(b.entities)
    at = E.find_block(blocks, "light")
    if at is None:
        return False
    del blocks[at]
    b.entities = E.blocks_to_text(blocks)
    return True


def m_item_floats(b: E.BspFile) -> bool:
    """The obligation, not the entity: the pickup keeps its name and its place
    in the list, and stops having a floor under it."""
    blocks = E.entity_blocks(b.entities)
    at = E.find_block_prefix(blocks, "item_")
    if at is None:
        return False
    origin = E.block_value(blocks[at], "origin")
    if not origin:
        return False
    x, y, z = (float(v) for v in origin.split())
    blocks[at] = E.set_block_value(blocks[at], "origin",
                                   f"{x:.0f} {y:.0f} {z + 240:.0f}")
    b.entities = E.blocks_to_text(blocks)
    return True


def m_spawn_moved_into_solid(b: E.BspFile) -> bool:
    blocks = E.entity_blocks(b.entities)
    # A real spawn, not the intermission camera: a camera owes the player no
    # floor, so moving it proves nothing about a traversal obligation.
    at = E.find_block(blocks, "info_player_deathmatch")
    if at is None:
        at = E.find_block(blocks, "info_player_start")
    if at is None:
        return False
    origin = E.block_value(blocks[at], "origin")
    if not origin:
        return False
    x, y, z = (float(v) for v in origin.split())
    blocks[at] = E.set_block_value(blocks[at], "origin",
                                   f"{x:.0f} {y:.0f} {z - 64:.0f}")
    b.entities = E.blocks_to_text(blocks)
    return True


# ---- mutations of the DONOR, for what the baseline has none of -----------

def d_trigger_added(d: E.BspFile) -> bool:
    """q2dm1 has no trigger to take away, so the donor gains one: the gate
    must notice that the baseline has no counterpart."""
    if d.count(E.L_MODELS, E.SZ_MODEL) < 2:
        return False
    blocks = E.entity_blocks(d.entities)
    blocks.append('{\n"classname" "trigger_multiple"\n"model" "*1"\n'
                  '"target" "a_target_that_matters"\n}')
    d.entities = E.blocks_to_text(blocks)
    return True


# ---- the changes that must NOT be refused --------------------------------

def g_face_split(b: E.BspFile) -> bool:
    """One quad becomes two triangles covering exactly the same surface.

    This is the compiler's own freedom, and the case Codex names: it changes
    the face count, the edges, the surfedges and every index after it, and it
    must change no verdict.
    """
    faces = b.count(E.L_FACES, E.SZ_FACE)
    world = b.model(0)
    target = None
    for i in range(world[10], world[10] + world[11]):
        if i < faces and b.face(i)[3] == 4:
            target = i
            break
    if target is None:
        return False

    planenum, side, first, _, texinfo = b.face(target)[:5]
    styles_lightofs = b.lumps[E.L_FACES][target * E.SZ_FACE + 12:
                                         target * E.SZ_FACE + 20]
    se = [struct.unpack_from("<i", b.lumps[E.L_SURFEDGES], (first + k) * 4)[0]
          for k in range(4)]

    def vertex_of(surfedge: int, end: int) -> int:
        a, c = struct.unpack_from("<2H", b.lumps[E.L_EDGES],
                                  abs(surfedge) * E.SZ_EDGE)
        pair = (a, c) if surfedge >= 0 else (c, a)
        return pair[end]

    v0, v2 = vertex_of(se[0], 0), vertex_of(se[2], 0)

    new_edge = b.count(E.L_EDGES, E.SZ_EDGE)
    b.lumps[E.L_EDGES] += struct.pack("<2H", v0, v2)

    base = b.count(E.L_SURFEDGES, 4)
    for value in (se[0], se[1], -new_edge, new_edge, se[2], se[3]):
        b.lumps[E.L_SURFEDGES] += struct.pack("<i", value)

    a = struct.pack("<Hhihh", planenum, side, base, 3, texinfo) + styles_lightofs
    c = struct.pack("<Hhihh", planenum, side, base + 3, 3, texinfo) \
        + styles_lightofs
    at = target * E.SZ_FACE
    b.lumps[E.L_FACES][at:at + E.SZ_FACE] = a
    b.lumps[E.L_FACES][at + E.SZ_FACE:at + E.SZ_FACE] = c

    # Everything that names a face by index moves with it.
    for i in range(b.count(E.L_LEAFFACES, 2)):
        value = struct.unpack_from("<H", b.lumps[E.L_LEAFFACES], i * 2)[0]
        if value > target:
            struct.pack_into("<H", b.lumps[E.L_LEAFFACES], i * 2, value + 1)
    for i in range(b.count(E.L_MODELS, E.SZ_MODEL)):
        m = b.model(i)
        firstface, numfaces = m[10], m[11]
        if firstface > target:
            firstface += 1
        elif firstface <= target < firstface + numfaces:
            numfaces += 1
        struct.pack_into("<2i", b.lumps[E.L_MODELS], i * E.SZ_MODEL + 40,
                         firstface, numfaces)
    return True


def g_plane_duplicated(b: E.BspFile) -> bool:
    """A plane the compiler could equally have de-duplicated or not."""
    faces = b.count(E.L_FACES, E.SZ_FACE)
    if not faces:
        return False
    planenum = b.face(0)[0]
    copy = b.count(E.L_PLANES, E.SZ_PLANE)
    at = planenum * E.SZ_PLANE
    b.lumps[E.L_PLANES] += b.lumps[E.L_PLANES][at:at + E.SZ_PLANE]
    for i in range(faces):
        if b.face(i)[0] == planenum:
            struct.pack_into("<H", b.lumps[E.L_FACES], i * E.SZ_FACE, copy)
    return True


def g_texinfo_duplicated(b: E.BspFile) -> bool:
    """The same material described twice, which texinfo de-duplication is free
    to do either way."""
    ti = _busiest_texinfo(b)
    copy = b.count(E.L_TEXINFO, E.SZ_TEXINFO)
    at = ti * E.SZ_TEXINFO
    b.lumps[E.L_TEXINFO] += b.lumps[E.L_TEXINFO][at:at + E.SZ_TEXINFO]
    seen = 0
    for i in range(b.count(E.L_FACES, E.SZ_FACE)):
        if b.face(i)[4] == ti:
            seen += 1
            if seen % 2 == 0:
                b.set_face_texinfo(i, copy)
    return True


def g_entities_rewritten(b: E.BspFile) -> bool:
    """Reordered, re-keyed and re-formatted, meaning untouched: the order of
    entities and the spelling of their numbers are the compiler's."""
    blocks = E.entity_blocks(b.entities)
    out = []
    for block in blocks:
        rewritten = block
        for key in ("origin", "angle", "light"):
            value = E.block_value(block, key)
            if value is None:
                continue
            try:
                numbers = [float(v) for v in value.split()]
            except ValueError:
                continue
            rewritten = E.set_block_value(
                rewritten, key, " ".join(f"{n:.4f}" for n in numbers))
        out.append(rewritten)
    b.entities = E.blocks_to_text(list(reversed(out)))
    return True



def _leaf_by_class(b: E.BspFile, wanted: str, skip: int = 0):
    """The nth leaf of a class, so two cases can pick different ones."""
    seen = 0
    for i in range(b.count(E.L_LEAFS, E.SZ_LEAF)):
        leaf = b.leaf(i)
        contents = leaf[0]
        if contents & (E.CONTENTS_SOLID | E.CONTENTS_WINDOW):
            cls = "solid"
        elif contents & (E.CONTENTS_LAVA | E.CONTENTS_SLIME):
            cls = "hazard"
        elif contents & E.CONTENTS_WATER:
            cls = "liquid"
        else:
            cls = "empty"
        if cls != wanted:
            continue
        if seen == skip:
            return i
        seen += 1
    return None


def m_thin_clip_added(b: E.BspFile) -> bool:
    """The thinnest clip brush stops being one.

    A player-clip obstruction eight units thick, in a slot a 64-unit lattice
    steps straight over. Marked on the BRUSH, because that is what a player
    runs into and what the comparison reads - the first version of this case
    set a LEAF's contents, which the compiler owns.
    """
    import struct as _struct
    thinnest, thinnest_span = None, None
    for i in range(b.count(E.L_BRUSHES, E.SZ_BRUSH)):
        first, num, contents = _struct.unpack_from(
            "<3i", b.lumps[E.L_BRUSHES], i * E.SZ_BRUSH)
        if not contents & (E.CONTENTS_PLAYERCLIP | E.CONTENTS_MONSTERCLIP):
            continue
        lo = [-1e9] * 3
        hi = [1e9] * 3
        for s in range(num):
            pn, _ = _struct.unpack_from("<Hh", b.lumps[E.L_BRUSHSIDES],
                                        (first + s) * E.SZ_BRUSHSIDE)
            nx, ny, nz, d = _struct.unpack_from("<4f", b.lumps[E.L_PLANES],
                                                pn * E.SZ_PLANE)
            for a, n in enumerate((nx, ny, nz)):
                if n > 0.99:
                    hi[a] = min(hi[a], d)
                elif n < -0.99:
                    lo[a] = max(lo[a], -d)
        span = min(hi[a] - lo[a] for a in range(3))
        if span > 0 and (thinnest_span is None or span < thinnest_span):
            thinnest, thinnest_span = i, span
    if thinnest is None or thinnest_span is None or thinnest_span > 16:
        return False
    keep = b.brush_contents(thinnest) & ~(E.CONTENTS_PLAYERCLIP
                                          | E.CONTENTS_MONSTERCLIP)
    b.set_brush_contents(thinnest, keep)
    return True


def m_ladder_removed(b: E.BspFile) -> bool:
    """A ladder that stops being one: the same space, a different way to move
    through it."""
    LADDER = 0x20000000
    for i in range(b.count(E.L_LEAFS, E.SZ_LEAF)):
        leaf = b.leaf(i)
        if leaf[0] & LADDER:
            b.set_leaf_contents(i, leaf[0] & ~LADDER)
            for brush in b.leaf_brushes(i):
                b.set_brush_contents(brush, b.brush_contents(brush) & ~LADDER)
            return True
    return False


def m_solid_relocated(b: E.BspFile) -> bool:
    """Solid taken from one place and given to another of the same size.

    Every total is unchanged - the same number of solid leaves, near enough the
    same volume - so a gate resting on aggregates would see nothing. Two places
    changed, and that is what has to be caught.
    """
    take = _leaf_by_class(b, "solid", 0)
    give = _leaf_by_class(b, "empty", 1)
    if take is None or give is None:
        return False
    taken = b.leaf(take)
    for brush in b.leaf_brushes(take):
        b.set_brush_contents(brush, 0)
    b.set_leaf_contents(take, 0)
    b.set_leaf_contents(give, taken[0])
    return True



def m_thirty_third_pair(b: E.BspFile) -> bool:
    """A block with more pairs than the comparison can hold.

    The parser used to keep thirty-two and walk past the rest, so whatever the
    thirty-third said was invisible. It must refuse instead.
    """
    blocks = E.entity_blocks(b.entities)
    at = E.find_block(blocks, "worldspawn")
    if at is None:
        at = 0
    block = blocks[at]
    extra = "".join(f'"pad{i}" "{i}"\n' for i in range(40))
    blocks[at] = block[:-1].rstrip() + "\n" + extra + "}"
    b.entities = E.blocks_to_text(blocks)
    return True


def m_overlength_value(b: E.BspFile) -> bool:
    """A value longer than the comparison can hold exactly."""
    blocks = E.entity_blocks(b.entities)
    at = E.find_block(blocks, "worldspawn")
    if at is None:
        at = 0
    blocks[at] = E.set_block_value(blocks[at], "message", "x" * 400)
    b.entities = E.blocks_to_text(blocks)
    return True


def m_duplicate_key(b: E.BspFile) -> bool:
    """The same key twice: Quake takes the last, a sorted canonical form takes
    whichever sorts first, and the two cannot both be right."""
    blocks = E.entity_blocks(b.entities)
    at = E.find_block_prefix(blocks, "info_player_")
    if at is None:
        return False
    blocks[at] = blocks[at][:-1].rstrip() + '\n"angle" "90"\n"angle" "270"\n}'
    b.entities = E.blocks_to_text(blocks)
    return True


def m_malformed_block(b: E.BspFile) -> bool:
    """A block that never closes."""
    text = b.entities
    at = text.rfind("}")
    if at < 0:
        return False
    b.entities = text[:at] + text[at + 1:]
    return True


def m_invalid_model_reference(b: E.BspFile) -> bool:
    """A machine bound to a submodel that is not there.

    The ownership axis used to skip a reference it could not resolve, so the
    binding vanished from both lists and nothing was compared.
    """
    blocks = E.entity_blocks(b.entities)
    at = E.find_block_prefix(blocks, "func_")
    if at is None:
        return False
    blocks[at] = E.set_block_value(blocks[at], "model", "*99")
    b.entities = E.blocks_to_text(blocks)
    return True


def m_identifier_reformatted(b: E.BspFile) -> bool:
    """A name that is a number, written differently.

    `sounds "1"` and `sounds "1.0"` are the same measurement and different
    identifiers. Keys that name things are compared as written; keys that
    measure things are compared with a tolerance. This proves the first half.
    """
    blocks = E.entity_blocks(b.entities)
    at = E.find_block_prefix(blocks, "func_")
    if at is None:
        return False
    blocks[at] = E.set_block_value(blocks[at], "sounds", "1.0")
    b.entities = E.blocks_to_text(blocks)
    return True


def g_measurement_reformatted(b: E.BspFile) -> bool:
    """And the second half: a measurement written differently is the same
    measurement."""
    blocks = E.entity_blocks(b.entities)
    at = E.find_block_prefix(blocks, "func_")
    if at is None:
        return False
    blocks[at] = E.set_block_value(blocks[at], "speed", "100.000")
    b.entities = E.blocks_to_text(blocks)
    return True



def m_operator_moved(b: E.BspFile) -> bool:
    """The trigger volume moves across the room and still fires the same thing.

    Every count is unchanged and every target is unchanged; only the place a
    player has to be is somewhere else. The axis used to compare only
    `movers[]`, so this passed.
    """
    blocks = E.entity_blocks(b.entities)
    at = E.find_block(blocks, "trigger_multiple")
    if at is None:
        return False
    model = E.block_value(blocks[at], "model")
    if not model or not model.startswith("*"):
        return False
    index = int(model[1:])
    if index <= 0 or index >= b.count(E.L_MODELS, E.SZ_MODEL):
        return False
    m = b.model(index)
    mins = [m[0] + 256.0, m[1], m[2]]
    maxs = [m[3] + 256.0, m[4], m[5]]
    b.set_model_bounds(index, mins, maxs)
    return True


def m_operator_target_rewired(b: E.BspFile) -> bool:
    """The trigger fires something else. Every count is the same."""
    blocks = E.entity_blocks(b.entities)
    at = E.find_block(blocks, "trigger_multiple")
    if at is None:
        return False
    blocks[at] = E.set_block_value(blocks[at], "target", "a_door_that_is_not")
    b.entities = E.blocks_to_text(blocks)
    return True



def m_wall_undrawn(b: E.BspFile) -> bool:
    """One wall stops being drawn.

    Its faces are repointed at a texinfo the donor never uses on that plane, so
    the surface a player sees is gone while the solid behind it stays. Coverage
    is what must catch this: the summed area of the material barely moves.
    """
    import struct as _struct
    ti = _busiest_texinfo(b)
    copy = b.count(E.L_TEXINFO, E.SZ_TEXINFO)
    at = ti * E.SZ_TEXINFO
    b.lumps[E.L_TEXINFO] += b.lumps[E.L_TEXINFO][at:at + E.SZ_TEXINFO]
    b.set_texinfo_name(copy, "e1u1/nothinghere")

    # Every face on the busiest single plane of that texinfo.
    counts = {}
    for i in range(b.count(E.L_FACES, E.SZ_FACE)):
        planenum, side, first, count, face_ti = b.face(i)[:5]
        if face_ti == ti and count >= 3:
            counts[planenum] = counts.get(planenum, 0) + 1
    if not counts:
        return False
    plane = max(counts, key=lambda k: counts[k])
    for i in range(b.count(E.L_FACES, E.SZ_FACE)):
        planenum, side, first, count, face_ti = b.face(i)[:5]
        if face_ti == ti and planenum == plane:
            b.set_face_texinfo(i, copy)
    return True



def g_submodels_renumbered(b: E.BspFile) -> bool:
    """The same machines, numbered the other way round.

    Codex's section 1.3 asks for this GREEN: the compiler may renumber
    submodels as long as the binding is kept, and the surface and mapping axes
    used to key on the raw number. Two submodels swap places - their records,
    their faces' ownership and the entity references that name them - and
    nothing about the map has changed.
    """
    import struct as _struct
    n = b.count(E.L_MODELS, E.SZ_MODEL)
    if n < 3:
        return False
    a, c = 1, 2
    at, ct = a * E.SZ_MODEL, c * E.SZ_MODEL
    first = bytes(b.lumps[E.L_MODELS][at:at + E.SZ_MODEL])
    second = bytes(b.lumps[E.L_MODELS][ct:ct + E.SZ_MODEL])
    b.lumps[E.L_MODELS][at:at + E.SZ_MODEL] = second
    b.lumps[E.L_MODELS][ct:ct + E.SZ_MODEL] = first

    blocks = E.entity_blocks(b.entities)
    for i, block in enumerate(blocks):
        model = E.block_value(block, "model")
        if model == f"*{a}":
            blocks[i] = E.set_block_value(block, "model", f"*{c}")
        elif model == f"*{c}":
            blocks[i] = E.set_block_value(block, "model", f"*{a}")
    b.entities = E.blocks_to_text(blocks)
    return True


RED = [
    ("world solid removed", "space", m_world_solid_removed, "baseline"),
    ("reachable empty space filled", "space", m_empty_space_filled, "baseline"),
    ("liquid contents lost", "space", m_liquid_lost, "baseline"),
    ("liquid became a hazard", "space", m_liquid_becomes_hazard, "baseline"),
    ("visible surface material changed", "surface",
     m_surface_material_changed, "baseline"),
    ("texture mapping slid", "mapping", m_texture_slid, "baseline"),
    ("brush model ownership changed", "ownership", m_model_bounds_changed,
     "baseline"),
    ("mover target lost", "mover", m_mover_target_lost, "baseline"),
    ("trigger without a counterpart", "mover", d_trigger_added, "donor"),
    ("areaportal opened", "traversal", m_areaportal_opened, "baseline"),
    ("item removed", "entity", m_item_removed, "baseline"),
    ("light removed", "entity", m_light_removed, "baseline"),
    ("pickup left without a floor", "traversal", m_item_floats, "baseline"),
    ("spawn pushed into the floor", "traversal", m_spawn_moved_into_solid,
     "baseline"),
    # Codex 2026-09-03 section 1.7, the ones the current code can answer.
    ("a clip brush thinner than the lattice", "space", m_thin_clip_added,
     "baseline"),
    ("a ladder that stopped being one", "space", m_ladder_removed,
     "baseline"),
    ("solid relocated, every total unchanged", "space", m_solid_relocated,
     "baseline"),
    ("a machine bound to a submodel that is not there", "ownership",
     m_invalid_model_reference, "baseline"),
    ("an identifier written differently", "entity", m_identifier_reformatted,
     "baseline"),
    ("a trigger volume moved, every count unchanged", "mover",
     m_operator_moved, "baseline"),
    ("a trigger rewired to fire something else", "mover",
     m_operator_target_rewired, "baseline"),
    ("a whole wall stops being drawn", "surface", m_wall_undrawn, "baseline"),
]

# Entity strings this cannot read exactly. Not an axis: a refusal, because
# comparing them approximately is how a changed value goes unnoticed.
# ---- the portal graph, on a fixture that has one -------------------------
#
# Each of these rewires the AREAS/AREAPORTALS lumps directly. That is what a
# compiler bug or a bad edit would look like: the geometry is untouched and
# only the sealing changes, which is precisely the case the area COUNT and the
# area VOLUMES cannot see.


def _middle_area(b: E.BspFile) -> int | None:
    """The area with the most portals - the one in the middle of the chain."""
    graph = b.area_graph()
    best, best_n = None, 0
    for a, portals in enumerate(graph):
        if len(portals) > best_n:
            best, best_n = a, len(portals)
    return best if best_n >= 2 else None


def _leaf_area(b: E.BspFile, i: int) -> int:
    return b.leaf(i)[2]


def p_portal_rewired(b: E.BspFile) -> bool:
    """A portal that led to one area now leads to another.

    Nothing about the space changes: the same rooms, the same volumes, the
    same number of areas and the same number of portals. Only which two the
    portal joins - which is the entire job of an areaportal.
    """
    mid = _middle_area(b)
    if mid is None:
        return False
    # An outer area: one portal, and it leads to the middle.
    for a, portals in enumerate(b.area_graph()):
        if a == mid or len(portals) != 1:
            continue
        num, first = b.area(a)
        portalnum, other = b.areaportal(first)
        # Point it at some area that is neither itself nor its real neighbour.
        for cand in range(1, b.count(E.L_AREAS, E.SZ_AREA)):
            if cand not in (a, other):
                b.set_areaportal(first, portalnum, cand)
                return True
    return False


def p_area_loses_a_portal(b: E.BspFile) -> bool:
    """The middle area declares one portal where it has two.

    The lump still holds every record; the area simply stops walking to one of
    them, and the engine floods as if that doorway were not there.
    """
    mid = _middle_area(b)
    if mid is None:
        return False
    num, first = b.area(mid)
    b.set_area(mid, num - 1, first)
    return True


def p_portals_collapsed(b: E.BspFile) -> bool:
    """Both of the middle area's portals lead to the same neighbour.

    The degree of every area is unchanged and so is the count of records; one
    end of one portal moves, and the far room is sealed off.
    """
    mid = _middle_area(b)
    if mid is None:
        return False
    num, first = b.area(mid)
    a0 = b.areaportal(first)
    a1 = b.areaportal(first + 1)
    if a0[1] == a1[1]:
        return False
    b.set_areaportal(first + 1, a1[0], a0[1])
    return True


def p_areas_renumbered(b: E.BspFile) -> bool:
    """Every area gets a different number, and the graph is the same graph.

    The compiler numbers areas in whatever order its flood happens to reach
    them, so a comparison that depended on the numbers would fail a baseline
    for a choice its own toolchain made. This is the case that proves it does
    not: two areas swap identities everywhere they appear - in the leaves, in
    the order of the AREAS records, and in every otherarea that names them.
    """
    n = b.count(E.L_AREAS, E.SZ_AREA)
    graph = b.area_graph()
    outer = [a for a in range(1, n) if len(graph[a]) == 1]
    if len(outer) < 2:
        return False
    x, y = outer[0], outer[1]

    rec_x, rec_y = b.area(x), b.area(y)
    b.set_area(x, *rec_y)
    b.set_area(y, *rec_x)

    for i in range(b.count(E.L_AREAPORTALS, E.SZ_AREAPORTAL)):
        portalnum, other = b.areaportal(i)
        if other == x:
            b.set_areaportal(i, portalnum, y)
        elif other == y:
            b.set_areaportal(i, portalnum, x)

    for i in range(b.count(E.L_LEAFS, E.SZ_LEAF)):
        area = _leaf_area(b, i)
        if area in (x, y):
            struct.pack_into("<h", b.lumps[E.L_LEAFS], i * E.SZ_LEAF + 6,
                             y if area == x else x)
    return True


PORTAL_RED = [
    ("an areaportal rewired to a different area", "traversal",
     p_portal_rewired),
    ("an area that stops declaring one of its portals", "traversal",
     p_area_loses_a_portal),
    ("two portals collapsed onto one neighbour", "traversal",
     p_portals_collapsed),
]

PORTAL_GREEN = [
    ("every area renumbered", p_areas_renumbered),
]


REFUSED = [
    ("a thirty-third key/value pair", m_thirty_third_pair),
    ("a value too long to compare exactly", m_overlength_value),
    ("the same key twice", m_duplicate_key),
    ("a block that never closes", m_malformed_block),
]

GREEN = [
    ("two submodels renumbered", g_submodels_renumbered),
    ("a measurement written differently", g_measurement_reformatted),
    ("one face split into two", g_face_split),
    ("a plane duplicated", g_plane_duplicated),
    ("a texinfo duplicated", g_texinfo_duplicated),
    ("entities reordered and reformatted", g_entities_rewritten),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--donor", type=Path, default=None,
                    help="a donor the projection round-trips; the default is "
                         "a fixture, because the corpus donors do not yet")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    exe = build_driver(args.work)
    fork = build_fork(args.work)
    donor = args.donor or make_fixture_donor(args.work)
    if donor is None:
        print("the fixture donor could not be compiled")
        return 1
    args.donor = donor
    baseline = make_baseline(fork, args.donor, args.work)

    print(f"donor    {args.donor}")
    print(f"baseline {baseline}")

    print("\nthe pair the whole matrix rests on")
    mask, detail = gate(exe, args.donor, baseline)
    if not check("the unmutated pair is equivalent", mask == 0, detail):
        print("\nEVERY red case below would be meaningless: fix this first.")
        return 1

    print("\ncontrolled RED - each must fire its own axis")
    for name, axis, mutate, target in RED:
        source = args.donor if target == "donor" else baseline
        bsp = E.BspFile(source)
        if not mutate(bsp):
            # Codex, 2026-09-03: a mandatory mutation that finds nothing to
            # damage has not been run, and a matrix that reports it as a skip
            # is reporting coverage it does not have.
            check(f"{name} -> {axis}", False,
                  "this map has nothing of that kind to damage")
            continue
        safe = "".join(c if c.isalnum() else "_" for c in name)
        out = args.work / f"{safe}.bsp"
        bsp.write(out)
        if target == "donor":
            mask, detail = gate(exe, out, baseline)
        else:
            mask, detail = gate(exe, args.donor, out)
        want = AXIS[axis]
        check(f"{name} -> {axis}", (mask & want) != 0,
              f"axes {mask:08x}, wanted {want:08x}: {detail}")

    print("\nentity strings that cannot be compared exactly - each must be "
          "REFUSED")
    for name, mutate in REFUSED:
        bsp = E.BspFile(baseline)
        if not mutate(bsp):
            check(name, False, "this map has nothing of that kind to damage")
            continue
        safe = "".join(c if c.isalnum() else "_" for c in name)
        out = args.work / f"refuse_{safe}.bsp"
        bsp.write(out)
        run = subprocess.run([str(exe), str(args.donor), str(out)],
                             capture_output=True, text=True, timeout=600)
        result = "?"
        for line in run.stdout.splitlines():
            if line.startswith("equivalence "):
                result = line.split()[1]
        check(f"{name} -> ERR_ENTITIES", result == "ERR_ENTITIES", result)

    print("\nequivalence preserved - each must stay GREEN")
    for name, mutate in GREEN:
        bsp = E.BspFile(baseline)
        if not mutate(bsp):
            print(f"  SKIP  {name}")
            continue
        safe = "".join(c if c.isalnum() else "_" for c in name)
        out = args.work / f"green_{safe}.bsp"
        bsp.write(out)
        mask, detail = gate(exe, args.donor, out)
        check(f"{name} stays equivalent", mask == 0, f"{mask:08x}: {detail}")

    # ---- the portal graph, on the only fixture that has one -------------
    #
    # Kept separate because it needs a different map. None of the corpus
    # donors and not the `everything` fixture has a func_areaportal, so the
    # comparison of WHICH areas a portal joins would otherwise be asserted on
    # an empty graph - coverage on paper and none in fact.
    print("\nthe portal graph - three rooms, two areaportals")
    sealed = make_fixture_donor(args.work, "sealed_areas")
    if sealed is None:
        check("the sealed fixture compiles", False,
              "the fixture donor could not be compiled")
    else:
        sealed_base = make_baseline(fork, sealed, args.work)
        mask, detail = gate(exe, sealed, sealed_base)
        if not check("the sealed pair is equivalent", mask == 0, detail):
            print("  the portal cases below would be meaningless")
        else:
            graph = E.BspFile(sealed).area_graph()
            degrees = sorted(len(p) for p in graph)
            check("the fixture really has a portal graph",
                  sum(degrees) >= 4 and max(degrees) >= 2,
                  f"degrees {degrees}")
            for name, axis, mutate in PORTAL_RED:
                bsp = E.BspFile(sealed_base)
                if not mutate(bsp):
                    check(f"{name} -> {axis}", False,
                          "this map has nothing of that kind to damage")
                    continue
                safe = "".join(c if c.isalnum() else "_" for c in name)
                out = args.work / f"portal_{safe}.bsp"
                bsp.write(out)
                mask, detail = gate(exe, sealed, out)
                want = AXIS[axis]
                check(f"{name} -> {axis}", (mask & want) != 0,
                      f"axes {mask:08x}, wanted {want:08x}: {detail}")
            for name, mutate in PORTAL_GREEN:
                bsp = E.BspFile(sealed_base)
                if not mutate(bsp):
                    check(f"{name} stays equivalent", False,
                          "this map has nothing of that kind to renumber")
                    continue
                safe = "".join(c if c.isalnum() else "_" for c in name)
                out = args.work / f"portal_green_{safe}.bsp"
                bsp.write(out)
                mask, detail = gate(exe, sealed, out)
                check(f"{name} stays equivalent", mask == 0,
                      f"{mask:08x}: {detail}")

    print(f"\n{CASES} cases, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
