#!/usr/bin/env python3
"""MAPGEN-1 M4 - the solid world around the empty space.

Contract section 16, stages 6 and 7: convex brushes, and exact allowed
material roles on every face.

Two halves:

  * STATIC - the construction. The solid is DERIVED from the empty space on a
    voxel grid rather than assembled from slabs around each room, which is why
    the opening where a corridor meets a room needs no code; the shell is
    proven to seal by a flood fill before any brush is emitted; and a face's
    material is chosen by what the corpus USED it as, never by its filename;

  * BEHAVIOUR - the compiled module against a real layout. The seal is checked
    AGAINST THE BRUSHES: the driver re-voxelizes the boxes that came out,
    paints the empty space the layout asked for, and floods from outside. That
    is a different computation from the module's own, so agreeing means
    something.

Run: python tools/check_mapgen_brush_contract.py
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

HEADER = REPO / "inc" / "common" / "mapgen_brush.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_brush.c"
DRIVER = REPO / "tools" / "mapgen_brush_test_driver.c"
PARTS = [
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
    head("static: derived, sealed, and textured from the corpus")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))
    hdr_prose = HEADER.read_text(encoding="utf-8")

    check(
        "no floating point anywhere in it",
        not re.search(r"\b(float|double)\b", src),
        "",
    )
    check(
        "and no clock and no libc generator",
        not re.search(r"\b(time|clock|rand|srand)\s*\(", src),
        "",
    )
    check(
        "one voxel is exactly one layout grid step",
        "#define MAPGEN_BRUSH_VOXEL        MAPGEN_LAYOUT_GRID" in hdr,
        "so every coordinate the layout produced lands on a voxel exactly",
    )

    # --- derived, not assembled --------------------------------------------
    build = src[src.find("mapgen_brush_result_t MapGenBrush_Build"):]
    check(
        "the empty space is marked before anything solid exists",
        build.find("VOXEL_EMPTY") >= 0
        and build.find("VOXEL_EMPTY") < build.find("VOXEL_SHELL"),
        "",
    )
    check(
        "the solid is every voxel that is not empty space",
        "g.cell[at] = VOXEL_SHELL;" in build
        and "if (g.cell[at] == VOXEL_EMPTY)" in build
        and "x + 1 == g.size[0] || y + 1 == g.size[1]" in build,
        "the openings are what is left where two empty volumes meet, which "
        "is why they need no code",
    )
    check(
        "the header says why the solid is derived rather than assembled",
        "Why the solid is derived and not assembled" in hdr_prose,
        "",
    )

    # --- the seal -----------------------------------------------------------
    seal_at = build.find("shell_seals(&g)")
    merge_at = build.find("MAPGEN_BRUSH_MAX_BRUSHES")
    check(
        "the seal is proven before a single brush is emitted",
        seal_at >= 0 and merge_at >= 0 and seal_at < merge_at
        and "if (!shell_seals(&g)) {" in build,
        "the exact refusal, not just the call: `shell_seals(&g) && false` "
        "would leave a looser check standing",
    )
    check(
        "and a leak is a refusal, not a warning",
        "return MAPGEN_BRUSH_ERR_LEAK;" in build,
        "it is the one failure a compiler cannot fix",
    )
    flood = src[src.find("static bool shell_seals"):]
    check(
        "the flood starts from every edge of the grid",
        "if (!on_edge)\n                    continue;" in flood
        and "VOXEL_FLOODED" in flood,
        "checked in its exact form: with an intact shell nothing leaks, so no "
        "run can tell a misdirected flood from a correct one",
    )
    check(
        "and reports a leak the moment it touches empty space",
        "leaked = true;" in flood,
        "",
    )

    # --- provenance ---------------------------------------------------------
    pick = src[src.find("static uint32_t pick_material"):]
    check(
        "a material is chosen by the role the corpus used it in",
        "MapGenMix_MaterialRoles(model, i)" in pick,
        "contract 15 forbids classifying a material from its filename",
    )
    check(
        "a role the material must have, and roles that rule it out",
        "if (wanted && !(roles & wanted))\n            continue;" in pick
        and "if (roles & forbidden)\n            continue;" in pick,
        "in their exact form: whether an unsuitable material is then DRAWN "
        "depends on the weights, so no run reliably notices a weakened test",
    )
    check(
        "and the wall is at least one voxel thick",
        int(re.search(r"MAPGEN_BRUSH_WALL_VOXELS\s+(\d+)", hdr).group(1)) >= 1,
        "the shell is a cube neighbourhood, so one voxel already seals a "
        "corner - zero is the absence of a wall",
    )
    check(
        "the sky and the liquids are excluded from every solid surface",
        "const uint32_t forbidden = MAPGEN_ROLE_SKY | MAPGEN_ROLE_WATER\n"
        "                             | MAPGEN_ROLE_LAVA | MAPGEN_ROLE_SLIME\n"
        "                             | MAPGEN_ROLE_NODRAW | MAPGEN_ROLE_CLIP\n"
        "                             | MAPGEN_ROLE_TRANSLUCENT | MAPGEN_ROLE_LIGHT;"
        in build
        and build.count("MAPGEN_ROLE_SOLID, forbidden") == 3,
        "named once and used for the floor, the wall and the ceiling: three "
        "separate copies of the list could disagree, and one of them silently "
        "letting lava onto a wall is exactly the kind of drift this prevents",
    )
    check(
        "and a role the corpus never taught is a refusal, not a guess",
        "if (floor_of[r] >= materials || wall_of[r] >= materials\n"
        "            || ceiling_of[r] >= materials) {" in build
        and "return MAPGEN_BRUSH_ERR_NO_MATERIAL;" in build,
        "all three roles, in the exact form, for every room: every snapshot "
        "in this corpus has solid materials, so no run can reach the refusal",
    )
    check(
        "the material stream is the material stream",
        "MAPGEN_RANDOM_MATERIALS" in build and src.count("MapGenRandom_Stream") == 1,
        "another stage's draws must not change the textures",
    )
    check(
        "a texture set per room, drawn once per room and not once per brush",
        "for (uint32_t r = 0; r < num_rooms; r++) {\n"
        "        floor_of[r] = pick_material(model, &rng, MAPGEN_ROLE_SOLID, forbidden);"
        in build
        and build.count("pick_material(model, &rng, MAPGEN_ROLE_SOLID, forbidden)") == 3,
        "three draws inside the per-room loop and nowhere else: a draw per "
        "BRUSH would make one room out of forty different walls, and a single "
        "draw for the whole map makes every room the same room",
    )
    check(
        "and a brush takes the set of the room it is nearest",
        "uint32_t nearest = 0;" in build
        and "nearest_distance" in build
        and "b->material[MAPGEN_FACE_TOP] = floor_of[nearest];" in build,
        "a wall between two rooms takes one side's texture rather than some "
        "third thing neither room has",
    )
    check(
        "a pool is filled with a material of the pool's own role",
        "pick_material(model, &rng, pool->role, 0)" in build
        and "if (liquid >= materials)\n            continue;" in build,
        "the role it was placed with, in its exact form - filling a lava pit "
        "with whatever was drawn last is how a map gets water that burns",
    )
    check(
        "and a fixture's brush is textured on every face like any other",
        "for (uint32_t face = 0; face < MAPGEN_FACE_COUNT; face++)\n"
        "        f->brush.material[face] = material;" in src,
        "a face with no material is a face the writer cannot name, and the "
        "whole file is refused for it",
    )

    # --- refusals -----------------------------------------------------------
    check(
        "the out-parameter is cleared before anything can fail",
        build.find("*out = NULL") >= 0
        and build.find("*out = NULL") < build.find("MAPGEN_BRUSH_ERR_ARGS"),
        "",
    )
    check(
        "a grid too large to allocate is refused rather than attempted",
        "MAPGEN_BRUSH_ERR_GRID_TOO_LARGE" in build,
        "",
    )
    check(
        "the layout is const to it",
        "mapgen_layout_t *layout" not in
        src.replace("const mapgen_layout_t *layout", ""),
        "",
    )
    check(
        "and so are the model and the recipe",
        "mapgen_mix_t *model" not in src.replace("const mapgen_mix_t *model", "")
        and "mapgen_recipe_t *recipe" not in
            src.replace("const mapgen_recipe_t *recipe", ""),
        "",
    )
    # The rule protects the PO's binary, not the generator: a module
    # the packaged helper runs has to be linked somewhere, and
    # mapgen_src is the somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_brush.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build_exe(cc: str, out: Path) -> Path | None:
    exe = out / ("brush.exe" if os.name == "nt" else "brush")
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



def test_behaviour(exe: Path) -> None:
    head("behaviour: the seal checked against the brushes, not the grid")
    paths = [find_map(n) for n in MAPS]
    paths = [p for p in paths if p]
    if not check("the maps are available", len(paths) == len(MAPS),
                 f"{len(paths)} of {len(MAPS)}"):
        return

    manifest = exe.parent / "target_manifest.txt"
    count = write_manifest(manifest)
    if not check("the target's own texture list could be read", count > 100,
                 f"{count} names"):
        return

    try:
        p = subprocess.run([str(exe), "run", str(manifest),
                            *[str(x) for x in paths]],
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        check("the behavioural suite reported a result", False, "timed out")
        return
    for line in p.stdout.splitlines():
        if line.startswith(("  PASS", "  FAIL")):
            print(line)
    m = re.search(r"=== (\d+) cases asserted, (\d+) failures", p.stdout)
    if not check("the behavioural suite reported a result", m is not None,
                 (p.stdout + p.stderr)[-600:]):
        return
    assert m is not None
    global CASES, FAILED
    CASES += int(m.group(1))
    FAILED += int(m.group(2))


def main() -> int:
    print("=== MAPGEN-1 M4 brush contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_brush_") as td:
        head("building")
        exe = build_exe(cc, Path(td))
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_behaviour(exe)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
