#!/usr/bin/env python3
"""MAPGEN-1 M4 - the `source.map` a compiler can read.

Contract section 16 stage 10: a deterministic Quake II Valve 220 `.map`.

Two halves:

  * STATIC - determinism by construction. Every number is printed by hand, so
    a comma-decimal locale cannot change the file; there is no floating point
    to round differently on another machine; and the line endings are chosen
    rather than inherited;

  * PARSING - the file is read back HERE, in Python, and checked against what
    the writer said it wrote. The part that matters most cannot be checked by
    reading the text at all: every face's plane normal is recomputed with
    qbsp3's own arithmetic, `(p0 - p1) x (p2 - p1)`, and compared against the
    face it is supposed to be. A wrong winding produces a map that compiles
    into an inside-out room, and nothing about the text would look wrong.

Run: python tools/check_mapgen_mapfile_contract.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_build_target as build_target  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

HEADER = REPO / "inc" / "common" / "mapgen_mapfile.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_mapfile.c"
DRIVER = REPO / "tools" / "mapgen_mapfile_test_driver.c"
PARTS = [
    REPO / "src" / "mapgen" / "mapgen_entities.c",
    REPO / "src" / "mapgen" / "mapgen_brush.c",
    REPO / "src" / "mapgen" / "mapgen_layout.c",
    REPO / "src" / "mapgen" / "mapgen_topology.c",
    REPO / "src" / "mapgen" / "mapgen_recipe.c",
    REPO / "src" / "mapgen" / "mapgen_mix.c",
    REPO / "src" / "mapgen" / "mapgen_random.c",
    REPO / "src" / "mapgen" / "mapgen_lineage.c",
    REPO / "src" / "mapgen" / "mapgen_training.c",
    REPO / "src" / "mapgen" / "mapgen_snapshot.c",
    REPO / "src" / "mapgen" / "mapgen_digest.c",
    REPO / "src" / "mapgen" / "mapgen_features.c",
    REPO / "src" / "mapgen" / "mapgen_wiring.c",
    REPO / "src" / "mapgen" / "mapgen_space.c",
    REPO / "src" / "mapgen" / "mapgen_trace.c",
    REPO / "src" / "mapgen" / "mapgen_genome.c",
    REPO / "src" / "mapgen" / "mapgen_bsp.c",
    REPO / "src" / "mapgen" / "mapgen_geometry.c",
    REPO / "src" / "mapgen" / "mapgen_blueprint.c",
]

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
]
MAPS = ["2box4.bsp", "rcdm17.bsp", "lbrdm1.bsp"]

CASES = 0
FAILED = 0

FACE_RE = re.compile(
    r"^\(\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\)\s*"
    r"\(\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\)\s*"
    r"\(\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\)\s+"
    r"(\S+)\s+"
    r"\[\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\]\s+"
    r"\[\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\]\s+"
    r"(-?\d+)\s+(-?\d+)\s+(-?\d+)"
    # The optional contents/flags/value triple. Present only on faces
    # whose material the corpus used as a light, because a .wal almost
    # always carries value 0 and the map says how bright this fitting is.
    r"(?:\s+(-?\d+)\s+(-?\d+)\s+(-?\d+))?\s*$"
)


def check(name: str, condition: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if condition:
        print(f"  PASS  {name}")
        return True
    print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    FAILED += 1
    return False


def head(text: str) -> None:
    print(f"\n=== {text}")


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


# --------------------------------------------------------------------------


def test_static() -> None:
    head("static: nothing here can be rounded or localized")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr_prose = HEADER.read_text(encoding="utf-8")

    check(
        "there is no floating point in the writer",
        not re.search(r"\b(float|double)\b", src),
        "a coordinate that went through a float would round differently on "
        "another machine",
    )
    check(
        "and no printf at all",
        "printf" not in src,
        "%f follows the locale, and a comma-decimal machine would write a "
        "file no compiler can read",
    )
    check(
        "every number is printed by hand",
        "static void emit_i32" in src,
        "",
    )
    check(
        "the line endings are chosen, not inherited",
        '\\r' not in src and src.count('\\n') > 5,
        "LF, written explicitly",
    )
    check(
        "the winding is derived from the face, not written out six times",
        "static void face_axis" in src
        and "const int u = (axis + 1) % 3;" in src,
        "a remembered convention is a convention nobody can check",
    )
    check(
        "the header says which formula it is arranged for",
        "(p0 - p1) x (p2 - p1)" in hdr_prose,
        "qbsp3's own, so the test can recompute it",
    )
    check(
        "the display name is deliberately kept out of the file",
        "MapGenRecipe_Slug(recipe)" in src
        and "MapGenRecipe_DisplayName" not in src,
        "it may be Russian and the compiler's UTF-8 behaviour is not "
        "qualified yet",
    )
    check(
        "and the header says why",
        "What is deliberately not in the file" in hdr_prose,
        "",
    )
    check(
        "every input is const to it",
        "mapgen_brushwork_t *work" not in
        src.replace("const mapgen_brushwork_t *work", "")
        and "mapgen_entities_t *entities" not in
            src.replace("const mapgen_entities_t *entities", ""),
        "",
    )
    # Scoped to the writer: the first MAPGEN_MAPFILE_ERR_ARGS in the file is
    # the one in ResultName's switch, which sits above everything.
    write = src[src.find("mapgen_mapfile_result_t MapGenMapFile_Write"):]
    cleared_at = write.find("*out_text = NULL")
    refused_at = write.find("return MAPGEN_MAPFILE_ERR_ARGS")
    check(
        "the out-parameters are cleared before anything can fail",
        cleared_at >= 0 and refused_at >= 0 and cleared_at < refused_at,
        "a refused write must not leave a stale pointer in the caller's hands",
    )
    # The rule protects the PO's binary, not the generator: a module
    # the packaged helper runs has to be linked somewhere, and
    # mapgen_src is the somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_mapfile.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build_exe(cc: str, out: Path) -> Path | None:
    exe = out / ("mapfile.exe" if os.name == "nt" else "mapfile")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), *[str(x) for x in PARTS], "-o", str(exe), "-lz"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def find_map(name: str) -> Path | None:
    for root in MAP_ROOTS:
        if (root / name).exists():
            return root / name
    return None

GAMEDIR = Path(r"O:\Claude2\q2pro-release\baseq2")


def write_manifest(path: Path) -> int:
    """The names that really resolve as textures in the target view.

    Produced here, by the same reader the compiler uses, rather than assumed:
    a texture the target lacks is only a WARNING inside the compiler, so a map
    can be textured with nothing at all and still compile cleanly.
    """
    sys.path.insert(0, str(REPO / "tools"))
    from mapgen_target_manifest import resolvable_textures

    names = sorted(resolvable_textures(GAMEDIR))
    path.write_text("\n".join(names) + "\n", encoding="ascii")
    return len(names)



def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def parse_map(text: str):
    """Blocks of the file, as (keys, brushes)."""
    entities = []
    lines = [ln.strip() for ln in text.split("\n")]
    i = 0
    while i < len(lines):
        if lines[i] != "{":
            i += 1
            continue
        i += 1
        keys, brushes = {}, []
        while i < len(lines) and lines[i] != "}":
            if lines[i] == "{":
                i += 1
                faces = []
                while i < len(lines) and lines[i] != "}":
                    faces.append(lines[i])
                    i += 1
                i += 1
                brushes.append(faces)
                continue
            m = re.match(r'^"([^"]*)"\s+"([^"]*)"$', lines[i])
            if m:
                keys[m.group(1)] = m.group(2)
            i += 1
        i += 1
        entities.append((keys, brushes))
    return entities


def test_file(exe: Path, out_map: Path) -> None:
    head("parsing: the bytes, and the planes a compiler will build from them")
    paths = [find_map(n) for n in MAPS]
    paths = [p for p in paths if p]
    if not check("the maps are available", len(paths) == len(MAPS),
                 f"{len(paths)} of {len(MAPS)}"):
        return

    manifest = out_map.parent / "target_manifest.txt"
    count = write_manifest(manifest)
    if not check("the target's own texture list could be read", count > 100,
                 f"{count} names"):
        return

    try:
        p = subprocess.run([str(exe), "run", str(out_map), str(manifest),
                            *[str(x) for x in paths]],
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        check("the writer produced a file", False, "timed out")
        return
    if not check("the writer produced a file",
                 p.returncode == 0 and out_map.exists(),
                 (p.stdout + p.stderr)[-400:]):
        return

    said = {}
    materials = set()
    for line in p.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        if parts[0] == "MATERIAL":
            materials.add(parts[1].strip())
        elif parts[1].strip().isdigit():
            said[parts[0]] = int(parts[1].strip())

    check("and wrote the same bytes when asked twice",
          said.get("IDENTICAL") == 1,
          "the writer is a function of its inputs and nothing else")

    raw = out_map.read_bytes()
    check("the file has no carriage returns", b"\r" not in raw,
          "LF, chosen rather than inherited from the platform")
    text = raw.decode("ascii", errors="replace")
    check("and is plain ASCII", "\ufffd" not in text, "")

    body = "\n".join(ln for ln in text.split("\n") if not ln.startswith("//"))
    check("no coordinate is a decimal", "." not in body.replace("\n", ""),
          "everything is an integer, so nothing rounds")

    blocks = parse_map(text)
    check("the file parses as entity blocks", len(blocks) > 0, "")

    worlds = [b for b in blocks if b[0].get("classname") == "worldspawn"]
    check("there is exactly one worldspawn", len(worlds) == 1, "")
    if not worlds:
        return
    world_keys, world_brushes = worlds[0]

    check("the worldspawn holds every brush",
          len(world_brushes) == said.get("BRUSHES"),
          f"{len(world_brushes)} in the file, {said.get('BRUSHES')} claimed")
    check("and the message is the slug",
          world_keys.get("message") == "q2mg_demo",
          "the display name stays in the recipe")

    BRUSH_ENTITIES = {"func_door", "func_plat", "trigger_push",
                      "trigger_teleport"}

    others = [b for b in blocks if b[0].get("classname") != "worldspawn"]
    # By what the block SAYS it is, not by what it happens to contain. Splitting
    # on "has brushes" made the next check unfalsifiable: a door written
    # without its brush simply stopped being counted as a door.
    fixtures = [b for b in others if b[0].get("classname") in BRUSH_ENTITIES]
    points = [b for b in others if b[0].get("classname") not in BRUSH_ENTITIES]

    check("every block other than the world is a brush entity or a point one",
          len(fixtures) + len(points) == len(others),
          "there is no third shape a block can have")
    check("and no point entity smuggled a brush in",
          all(not b[1] for b in points),
          "a brush on something that is not a door, a plat, a push or a "
          "teleport is geometry nobody can account for")
    check("and there are as many point entities as were placed",
          len(points) == said.get("ENTITIES") + said.get("MARKERS"),
          f"{len(points)} in the file, {said.get('ENTITIES')} placements plus "
          f"{said.get('MARKERS')} markers claimed")
    check("and as many brush entities as were built",
          len(fixtures) == said.get("FIXTURES"),
          f"{len(fixtures)} in the file, {said.get('FIXTURES')} claimed")
    check("every brush entity has a classname and exactly one brush",
          all(b[0].get("classname") and len(b[1]) == 1 for b in fixtures),
          "a door with no brush is a key nobody can see, and a door with two "
          "is two doors sharing one set of keys")
    check("and every brush entity is one the corpus taught",
          all(b[0].get("classname") in BRUSH_ENTITIES for b in fixtures),
          "contract 15: the writer emits no motif the generator did not build")
    check("a teleport trigger names a destination that exists",
          all(b[0].get("target") in
              {p[0].get("targetname") for p in points if p[0].get("targetname")}
              for b in fixtures
              if b[0].get("classname") == "trigger_teleport"),
          "a teleporter with no destination drops the player nowhere, and the "
          "compiler will not say so")
    check("the railgun that was asked for is in the file",
          sum(1 for b in points
              if b[0].get("classname") == "weapon_railgun") == said.get("RAILGUNS"),
          "")
    check("and the four health",
          sum(1 for b in points
              if b[0].get("classname") == "item_health") == said.get("HEALTH"),
          "")
    check("every point entity has an origin",
          all("origin" in b[0] for b in points), "")
    check("and every origin is three integers",
          all(re.fullmatch(r"-?\d+ -?\d+ -?\d+", b[0]["origin"])
              for b in points if "origin" in b[0]), "")

    # --- the faces ---------------------------------------------------------
    emitting_triples: list[tuple] = []
    plain_textures: set[str] = set()
    bad_syntax = 0
    bad_texture = 0
    bad_faces = 0
    wrong_normals = 0
    off_plane = 0
    inside_out = 0
    bad_axes = 0
    for faces in world_brushes:
        if len(faces) != 6:
            bad_faces += 1
            continue
        normals = []
        planes = {}
        for line in faces:
            m = FACE_RE.match(line)
            if not m:
                bad_syntax += 1
                continue
            # The last three are absent on any face that does not emit.
            g = [int(x) if x is not None and x.lstrip("-").isdigit() else x
                 for x in m.groups()]
            if g[-1] is not None:
                emitting_triples.append((g[9], g[-3], g[-2], g[-1]))
            else:
                plain_textures.add(g[9])
            p0 = (g[0], g[1], g[2])
            p1 = (g[3], g[4], g[5])
            p2 = (g[6], g[7], g[8])
            texture = m.group(10)
            if texture not in materials:
                bad_texture += 1

            # Coplanarity FIRST, and on its own terms.
            #
            # It used to sit after the normal test, behind its `continue`, so a
            # face whose points are not coplanar failed the normal test and
            # this never ran. A check that cannot be reached independently
            # proves nothing by itself.
            flat = any(p0[a] == p1[a] == p2[a] for a in range(3))
            if not flat:
                off_plane += 1

            # qbsp3's own: normal = (p0 - p1) x (p2 - p1).
            t1 = tuple(p0[i] - p1[i] for i in range(3))
            t2 = tuple(p2[i] - p1[i] for i in range(3))
            n = cross(t1, t2)
            nonzero = [i for i in range(3) if n[i]]
            if len(nonzero) != 1:
                wrong_normals += 1
                continue
            axis = nonzero[0]
            sign = 1 if n[axis] > 0 else -1
            normals.append((axis, sign))
            planes[(axis, sign)] = p0[axis]

            # Valve 220's texture axes: both non-zero, and neither parallel to
            # the face - a parallel one divides by zero in the compiler while
            # the text looks perfectly ordinary.
            u_axis = (g[10], g[11], g[12])
            v_axis = (g[14], g[15], g[16])
            if not any(u_axis) or not any(v_axis):
                bad_axes += 1
            elif u_axis[axis] or v_axis[axis]:
                bad_axes += 1

        if len(normals) == 6 and len(set(normals)) != 6:
            wrong_normals += 1

        # Six correct directions at six wrong distances is a brush with no
        # inside. The +face has to sit above the -face on every axis.
        for a in range(3):
            hi = planes.get((a, 1))
            lo = planes.get((a, -1))
            if hi is None or lo is None or hi <= lo:
                inside_out += 1

    check("a face carries the contents/flags/value triple only when it emits",
          all(flags & 0x1 for _, _, flags, _ in emitting_triples),
          "the triple OVERRIDES what the texture declares, and the reason the "
          "writer normally omits it is that a material the corpus used as a "
          "light has to keep behaving like one")
    check("and never claims to be a light worth nothing",
          all(value > 0 for _, _, _, value in emitting_triples),
          "a face that says it emits and then says zero is the defect this "
          "was added to fix, wearing the fix as a disguise")
    check("and no texture both emits and does not",
          not ({t for t, _, _, _ in emitting_triples} & plain_textures),
          "the same material written two ways in one file is two different "
          "surfaces as far as the compiler is concerned")
    check("every face line is Valve 220 syntax", bad_syntax == 0,
          f"{bad_syntax} lines did not parse")
    check("every brush has exactly six faces", bad_faces == 0, "")
    check("every texture is one the model allowed", bad_texture == 0,
          "contract 15: nothing is textured with something the corpus never "
          "had")
    check("every plane's normal is axis-aligned, and a brush has all six",
          wrong_normals == 0,
          "recomputed with qbsp3's own (p0 - p1) x (p2 - p1); a wrong winding "
          "compiles into an inside-out room and the text looks fine")
    check("and every face's three points lie on it", off_plane == 0, "")
    check("every brush has an inside",
          inside_out == 0,
          "six correct directions at six wrong distances is a brush a "
          "compiler turns into nothing")
    check("and every texture axis is usable",
          bad_axes == 0,
          "an axis parallel to the face divides by zero in the compiler and "
          "looks perfectly ordinary in the text")


def main() -> int:
    print("=== MAPGEN-1 M4 map-file contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_mapfile_") as td:
        head("building")
        exe = build_exe(cc, Path(td))
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_file(exe, Path(td) / "generated.map")

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
