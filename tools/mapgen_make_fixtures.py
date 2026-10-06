#!/usr/bin/env python3
"""Generate the MAPGEN-1 M0 compiler fixtures and their independent expectations.

Emits, deterministically, into tools/mapgen_fixtures/:

    maps/<name>.map           Valve 220 authoring source
    textures/<dir>/<n>.wal    minimal synthetic textures the fixtures reference
    expected/<name>.json      what a CORRECT compile of that map must produce,
                              derived from the authoring source alone

The expectations are the point. They are written from the geometry we emitted,
never from a compiler's output, because contract section 17 forbids letting an
unqualified compiler be its own golden oracle. A fixture whose expectation was
copied out of a compile log proves only that the compiler is self-consistent.

Both the fixtures and this generator are committed, and `--check` proves
regeneration is byte-identical - the same discipline the repository already
applies to tools/gen_mp_menu.py.

Usage:
    python tools/mapgen_make_fixtures.py            # write
    python tools/mapgen_make_fixtures.py --check    # verify byte-identical
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapgen_fixture_lib import (  # noqa: E402
    CONTENTS_LAVA,
    CONTENTS_SOLID,
    CONTENTS_WATER,
    SURF_SKY,
    SURF_WARP,
    Box,
    Entity,
    FaceOverride,
    MapFixture,
    hollow_room,
    write_pcx_palette,
    write_wal,
)

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "tools" / "mapgen_fixtures"

WALL_TEX = "q2mgfx/wall"
FLOOR_TEX = "q2mgfx/floor"
SKY_TEX = "q2mgfx/sky"
WATER_TEX = "q2mgfx/water"
LAVA_TEX = "q2mgfx/lava"
ABSENT_TEX = "q2mgfx/absent"

# name -> (flags, contents) written into the synthetic .wal header.
WAL_TABLE = {
    WALL_TEX: (0, 0),
    FLOOR_TEX: (0, 0),
    SKY_TEX: (SURF_SKY, 0),
    WATER_TEX: (SURF_WARP, CONTENTS_WATER),
    LAVA_TEX: (SURF_WARP, CONTENTS_LAVA),
}


def player_start(origin=(0, 0, 24), angle=0) -> Entity:
    return Entity(
        "info_player_start",
        keys=[("origin", f"{origin[0]} {origin[1]} {origin[2]}"), ("angle", str(angle))],
    )


def light(origin, intensity=300) -> Entity:
    return Entity(
        "light",
        keys=[
            ("origin", f"{origin[0]} {origin[1]} {origin[2]}"),
            ("light", str(intensity)),
        ],
    )


def build_fixtures() -> dict[str, tuple[MapFixture, dict]]:
    fixtures: dict[str, tuple[MapFixture, dict]] = {}

    # ---------------------------------------------------------------- sealed
    sealed = MapFixture(
        name="sealed_room",
        description="One sealed 256x256x128 room with a start and a light. The baseline every other case is a delta from.",
        world_brushes=hollow_room((-128, -128, 0), (128, 128, 128), texture=WALL_TEX, floor_texture=FLOOR_TEX),
        entities=[player_start(), light((0, 0, 96))],
    )
    fixtures["sealed_room"] = (
        sealed,
        {
            "must_compile": True,
            "must_leak": False,
            "entity_classnames": {"worldspawn": 1, "info_player_start": 1, "light": 1},
            "textures_allowed": sorted(sealed.textures()),
            "world_bounds_contains": [[-144, -144, -16], [144, 144, 144]],
            "interior_points_empty": [[0, 0, 24], [100, 100, 64], [-100, -100, 100]],
            "solid_points": [[0, 0, -8], [136, 0, 64]],
            "min_models": 1,
            "forbidden_contents": ["CONTENTS_WATER", "CONTENTS_LAVA", "CONTENTS_SLIME"],
        },
    )

    # ------------------------------------------------------------- two rooms
    # One sealed outer envelope with an internal dividing wall that has a
    # doorway. Building it as "envelope minus doorway" instead of "two shells
    # glued together" is deliberate: sealing is then a property of one brush
    # set that is trivially correct, so a leak in this fixture can only come
    # from the compiler, never from fixture arithmetic.
    corridor = MapFixture(
        name="two_rooms_corridor",
        description="One sealed envelope split by a wall with a doorway: the smallest map with a real traversal graph.",
        world_brushes=(
            hollow_room((-320, -128, 0), (320, 128, 128), texture=WALL_TEX, floor_texture=FLOOR_TEX)
            + [
                Box((-16, -128, 0), (16, -32, 128), texture=WALL_TEX),
                Box((-16, 32, 0), (16, 128, 128), texture=WALL_TEX),
                Box((-16, -32, 96), (16, 32, 128), texture=WALL_TEX),
            ]
        ),
        entities=[
            player_start((-192, 0, 24)),
            Entity("info_player_deathmatch", keys=[("origin", "192 0 24"), ("angle", "180")]),
            light((-192, 0, 96)),
            light((192, 0, 96)),
        ],
    )
    fixtures["two_rooms_corridor"] = (
        corridor,
        {
            "must_compile": True,
            "must_leak": False,
            "entity_classnames": {
                "worldspawn": 1,
                "info_player_start": 1,
                "info_player_deathmatch": 1,
                "light": 2,
            },
            "textures_allowed": sorted(corridor.textures()),
            "interior_points_empty": [[-192, 0, 24], [192, 0, 24], [0, 0, 24]],
            "solid_points": [[0, 0, -8], [-192, 0, -8], [0, 96, 64], [0, 0, 112]],
            "world_bounds_contains": [[-336, -144, -16], [336, 144, 144]],
            "connected_point_pairs": [[[-192, 0, 24], [192, 0, 24]]],
            "min_models": 1,
            "forbidden_contents": ["CONTENTS_WATER", "CONTENTS_LAVA", "CONTENTS_SLIME"],
        },
    )

    # ------------------------------------------------------------ leaked map
    leaking = MapFixture(
        name="leaking_room",
        description="The sealed room minus its north wall. Must LEAK - and this compiler reports a leak with exit code ZERO.",
        world_brushes=hollow_room(
            (-128, -128, 0), (128, 128, 128), texture=WALL_TEX, floor_texture=FLOOR_TEX, omit="north"
        ),
        entities=[player_start(), light((0, 0, 96))],
    )
    fixtures["leaking_room"] = (
        leaking,
        {
            "must_compile": False,
            "must_leak": True,
            "expected_failure": "MAPCOMPILE_ERR_LEAKED",
            "note": "q2tools-220 src/bsp.c:225-234 calls exit(0) on a leak, so a zero exit code here is a FAILURE.",
            "textures_allowed": sorted(leaking.textures()),
        },
    )

    # ------------------------------------------------------------ water room
    water = MapFixture(
        name="water_room",
        description="Sealed room with a water volume and a lava pit: liquid contents must survive to the compiled leafs.",
        world_brushes=hollow_room((-192, -192, 0), (192, 192, 192), texture=WALL_TEX, floor_texture=FLOOR_TEX)
        + [
            Box(
                (-160, -160, 0),
                (0, 160, 64),
                texture=WATER_TEX,
                contents=CONTENTS_WATER,
                flags=SURF_WARP,
            ),
            Box(
                (64, -64, 0),
                (160, 64, 32),
                texture=LAVA_TEX,
                contents=CONTENTS_LAVA,
                flags=SURF_WARP,
            ),
        ],
        entities=[player_start((32, 0, 24)), light((0, 0, 160))],
    )
    fixtures["water_room"] = (
        water,
        {
            "must_compile": True,
            "must_leak": False,
            "entity_classnames": {"worldspawn": 1, "info_player_start": 1, "light": 1},
            "textures_allowed": sorted(water.textures()),
            "interior_points_empty": [[32, 0, 24], [0, 0, 160]],
            "water_points": [[-80, 0, 32], [-140, -140, 16]],
            "lava_points": [[112, 0, 16]],
            "solid_points": [[0, 0, -8]],
            "required_contents": ["CONTENTS_WATER", "CONTENTS_LAVA"],
            "min_models": 1,
        },
    )

    # -------------------------------------------------------------- sky room
    sky = MapFixture(
        name="sky_room",
        description="Sealed room whose ceiling is sky: SURF_SKY must reach the compiled texinfo.",
        world_brushes=hollow_room((-128, -128, 0), (128, 128, 192), texture=WALL_TEX, floor_texture=FLOOR_TEX)[:1]
        + [
            Box(
                (-144, -144, 192),
                (144, 144, 208),
                texture=SKY_TEX,
                contents=CONTENTS_SOLID,
                flags=SURF_SKY,
                overrides={"down": FaceOverride(texture=SKY_TEX, flags=SURF_SKY)},
            )
        ]
        + hollow_room((-128, -128, 0), (128, 128, 192), texture=WALL_TEX, floor_texture=FLOOR_TEX)[2:],
        worldspawn_keys=[("sky", "unit1_")],
        entities=[player_start(), light((0, 0, 160))],
    )
    fixtures["sky_room"] = (
        sky,
        {
            "must_compile": True,
            "must_leak": False,
            "entity_classnames": {"worldspawn": 1, "info_player_start": 1, "light": 1},
            "textures_allowed": sorted(sky.textures()),
            "required_surface_flags": ["SURF_SKY"],
            "interior_points_empty": [[0, 0, 24], [0, 0, 160]],
            "solid_points": [[0, 0, -8], [0, 0, 200]],
            "min_models": 1,
        },
    )

    # ------------------------------------------------------- missing texture
    missing = MapFixture(
        name="missing_texture_room",
        description="Sealed room referencing a texture that does not exist in the target view. The compiler only WARNS - the adapter must fail the attempt.",
        world_brushes=hollow_room((-128, -128, 0), (128, 128, 128), texture=WALL_TEX, floor_texture=FLOOR_TEX)[:1]
        + [Box((-144, -144, 128), (144, 144, 144), texture=ABSENT_TEX)]
        + hollow_room((-128, -128, 0), (128, 128, 128), texture=WALL_TEX, floor_texture=FLOOR_TEX)[2:],
        entities=[player_start(), light((0, 0, 96))],
    )
    fixtures["missing_texture_room"] = (
        missing,
        {
            "must_compile": False,
            "must_leak": False,
            "expected_failure": "MAPCOMPILE_ERR_MISSING_ASSET",
            "missing_texture": ABSENT_TEX,
            "note": "q2tools-220 src/textures.c:29-105 prints a WARNING and leaves flags/contents at zero, then exits 0.",
            "textures_allowed": sorted(missing.textures() - {ABSENT_TEX}),
        },
    )

    # ---------------------------------------------------- malformed: braces
    fixtures["malformed_unclosed_brace"] = (
        None,
        {
            "must_compile": False,
            "expected_failure": "MAPCOMPILE_ERR_NONZERO_EXIT",
            "raw_map": "{\n"
            '"classname" "worldspawn"\n'
            '"mapversion" "220"\n'
            "{\n"
            "( 0 0 16 ) ( 0 1 16 ) ( 1 1 16 ) " + WALL_TEX + " [ 1 0 0 0 ] [ 0 -1 0 0 ] 0 1 1 1 0 0\n"
            "( 0 1 0 ) ( 0 0 0 ) ( 1 0 0 ) " + WALL_TEX + " [ 1 0 0 0 ] [ 0 -1 0 0 ] 0 1 1 1 0 0\n",
            "note": "Truncated mid-brush: the parser must reject it, never silently produce a partial BSP.",
        },
    )

    # ------------------------------------------------ malformed: no worldspawn
    fixtures["malformed_no_worldspawn"] = (
        None,
        {
            "must_compile": False,
            "expected_failure": "MAPCOMPILE_ERR_NONZERO_EXIT",
            "raw_map": "{\n"
            '"classname" "info_player_start"\n'
            '"origin" "0 0 24"\n'
            "}\n",
            "note": "A map whose first entity is not worldspawn has no world geometry at all.",
        },
    )

    # ------------------------------------------------ malformed: empty world
    fixtures["malformed_empty_world"] = (
        None,
        {
            "must_compile": False,
            "expected_failure": "MAPCOMPILE_ERR_NONZERO_EXIT",
            "raw_map": "{\n" '"classname" "worldspawn"\n' '"mapversion" "220"\n' "}\n",
            "note": (
                "Worldspawn with zero brushes. MEASURED on q2tools-220 07d8d893: the BSP pass "
                "exits ZERO and writes a degenerate map with 0 nodes, 0 faces and 1 leaf; only "
                "the VIS pass refuses it, with 'Empty map' and exit 1. A profile that ran BSP "
                "alone would therefore have accepted an empty world, which is why the runner "
                "also carries an unconditional degenerate-output floor."
            ),
        },
    )

    return fixtures


def write_all(check_only: bool) -> int:
    fixtures = build_fixtures()
    files: dict[Path, bytes] = {}

    for name, (fixture, expected) in fixtures.items():
        if fixture is not None:
            text = fixture.emit()
            expected = dict(expected)
            expected["description"] = fixture.description
        else:
            text = expected["raw_map"]
            expected = {k: v for k, v in expected.items() if k != "raw_map"}
        expected["fixture"] = name
        files[OUT / "maps" / f"{name}.map"] = text.encode("ascii")
        files[OUT / "expected" / f"{name}.json"] = (
            json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("ascii")

    # The LIGHT pass hard-fails without the game palette, so it belongs to the
    # fixture set exactly like the textures do.
    files[OUT / "pics" / "colormap.pcx"] = write_pcx_palette(None)

    for tex, (flags, contents) in sorted(WAL_TABLE.items()):
        rel = Path(*tex.split("/"))
        files[OUT / "textures" / rel.with_suffix(".wal")] = write_wal(
            None, name=tex, flags=flags, contents=contents
        )

    index = {
        "generator": "tools/mapgen_make_fixtures.py",
        "format": "Quake II Valve 220 authoring source",
        "oracle_rule": "expectations are derived from the authoring source, never from compiler output",
        "fixtures": sorted(fixtures),
        "textures": sorted(WAL_TABLE),
        "absent_texture": ABSENT_TEX,
        "palette": "pics/colormap.pcx",
    }
    files[OUT / "index.json"] = (
        json.dumps(index, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("ascii")

    drift = []
    for path, data in sorted(files.items()):
        if check_only:
            if not path.is_file() or path.read_bytes() != data:
                drift.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    if check_only:
        if drift:
            for path in drift:
                print(f"  FAIL  drifted or missing: {path.relative_to(REPO)}")
            print(f"\n=== {len(files)} fixture files, {len(drift)} drifted")
            print("RESULT: FAIL")
            return 1
        print(f"=== {len(files)} fixture files, byte-identical regeneration")
        print("RESULT: PASS")
        return 0

    for path in sorted(files):
        print(f"  wrote {path.relative_to(REPO)}")
    print(f"=== {len(files)} fixture files written")
    return 0


if __name__ == "__main__":
    sys.exit(write_all("--check" in sys.argv))
