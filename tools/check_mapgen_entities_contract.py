#!/usr/bin/env python3
"""MAPGEN-1 M4 - who spawns where, and what is lying around.

Contract section 16 stage 8, contract 13's item controls, contract 18.2's
spawn and item safety.

Two halves:

  * STATIC - what has to hold by construction. One table pairs every item
    control with its classname, so neither can exist without the other; the
    placement search is a LATTICE rather than a series of draws, because a
    draw that keeps missing turns "there is nowhere safe" into "we were
    unlucky" and contract 13 needs those two to be different; and an exact
    count that cannot be met is refused with the control named, never reduced;

  * BEHAVIOUR - the compiled module against a real layout. Every placement is
    re-measured against the room it claims to be in, the counts are compared
    against what the recipe asked for, and a request the map cannot hold is
    checked to be refused by name.

Run: python tools/check_mapgen_entities_contract.py
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

HEADER = REPO / "inc" / "common" / "mapgen_entities.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_entities.c"
DRIVER = REPO / "tools" / "mapgen_entities_test_driver.c"
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
    head("static: an exact count is a promise")
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
        "one table pairs every control with its classname",
        "static const item_rule_t ITEM_RULES[]" in src
        and "const char *control;" in src and "const char *classname;" in src,
        "so a control cannot exist without a classname or the other way round",
    )
    check(
        "contract 13's rows are actually in it",
        all(f'"{name}"' in src for name in
            ("item_quad", "item_invulnerability", "weapon_railgun",
             "item_armor_body", "ammo_grenades", "item_health_small")),
        "",
    )

    # --- contract 13's hard constraint --------------------------------------
    build = src[src.find("mapgen_entities_result_t MapGenEntities_Build"):]
    check(
        "a resolved count of zero places nothing",
        "if (wanted <= 0)\n            continue;" in build,
        "contract 13: None is absolute",
    )
    check(
        "and a count that cannot be placed is refused",
        "MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE" in build
        and "*conflict = ITEM_RULES[k].control;" in build,
        "never quietly reduced, and named so preflight can say which",
    )
    check(
        "the search is a lattice, not a series of draws",
        "for (int32_t i = 0; i < cells; i++)" in src
        and "(first + i) % cells" in src,
        "a draw that keeps missing turns 'nowhere safe' into 'unlucky', and "
        "contract 13 needs those two to be different",
    )
    check(
        "the header says why that distinction matters",
        "An explicit count is a promise, not a preference" in hdr_prose,
        "",
    )

    # --- safety --------------------------------------------------------------
    check(
        "nothing is placed on top of anything already placed",
        "too_close(e, out)" in src and "PLACEMENT_CLEARANCE" in src,
        "contract 18.2: a spawn inside a pickup is a telefrag waiting",
    )
    check(
        "the feet offset is the engine's own hull",
        "#define MAPGEN_PLACEMENT_FLOOR_OFFSET    24" in hdr,
        "inc/shared/shared.h puts the player's mins at -24",
    )
    check(
        "a room too small for a standing player is skipped",
        "MAPGEN_LAYOUT_HULL_HEIGHT" in src and "MAPGEN_LAYOUT_HULL_WIDTH" in src,
        "",
    )
    check(
        "a multiplayer map never gets fewer than two spawns",
        "else if (spawns < 2)\n        spawns = 2;" in build,
        "one spawn means the second player telefrags the first",
    )
    check(
        "and single player gets exactly one start",
        'goal == MAPGEN_GOAL_SINGLE_PLAYER\n                            ? "info_player_start"' in build,
        "",
    )

    # --- determinism ---------------------------------------------------------
    check(
        "the placement stream is the item stream",
        "MAPGEN_RANDOM_ITEMS" in build and src.count("MapGenRandom_Stream") == 1,
        "another stage's draws must not move an item",
    )
    check(
        "it reads only the resolved half of a control",
        "MapGenRecipe_ResolvedValue" in src and "MapGenRecipe_Control(" not in src,
        "contract 10: Generate Again must not re-resolve an old Auto",
    )
    check(
        "the out-parameter is cleared before anything can fail",
        build.find("*out = NULL") >= 0
        and build.find("*out = NULL") < build.find("MAPGEN_ENTITIES_ERR_ARGS"),
        "",
    )
    check(
        "every input is const to it",
        "mapgen_layout_t *layout" not in
        src.replace("const mapgen_layout_t *layout", "")
        and "mapgen_recipe_t *recipe" not in
            src.replace("const mapgen_recipe_t *recipe", ""),
        "",
    )
    check(
        "a placement is not called an entity",
        "mapgen_entity_t" not in src and "mapgen_placement_t" in src,
        "mapgen_genome.h owns that name for an entity parsed out of a real "
        "map, which is the opposite direction of travel",
    )
    # The rule protects the PO's binary, not the generator: a module
    # the packaged helper runs has to be linked somewhere, and
    # mapgen_src is the somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_entities.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build_exe(cc: str, out: Path) -> Path | None:
    exe = out / ("entities.exe" if os.name == "nt" else "entities")
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


def test_behaviour(exe: Path) -> None:
    head("behaviour: every placement re-measured against its room")
    paths = [find_map(n) for n in MAPS]
    paths = [p for p in paths if p]
    if not check("the maps are available", len(paths) == len(MAPS),
                 f"{len(paths)} of {len(MAPS)}"):
        return

    try:
        p = subprocess.run([str(exe), "run", *[str(x) for x in paths]],
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
    print("=== MAPGEN-1 M4 entity placement contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_entities_") as td:
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
