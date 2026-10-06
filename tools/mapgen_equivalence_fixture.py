"""One small map with one of everything the equivalence gate compares.

The gate's controlled REDs need a pair the projection round-trips, and they
need that pair to CONTAIN the things they mutate. `open_room` round-trips and
has no items, no lights, no trigger and no mover, so four of the mandatory
mutations had nothing to damage and were skipped - and Codex's ruling of
2026-09-03 says a mandatory skip is a failure, not a pass.

So this builds a map that has:

    two player starts           the traversal obligations
    an item and a light         the entity axis, and the placements
    a door with a targetname    the mover axis: stops, and a machine that is
    and a trigger that fires it fired by something a player can reach
    a pool of water             a liquid class, and a surface the compiler
                                treats differently from a wall
    a player-clip brush         content a player runs into and cannot see
    a ladder brush              content that changes how he moves
    a second material           so a material can be changed without changing
                                every surface in the map

It is deliberately small. A fixture that reproduces a defect in twenty brushes
is a fixture somebody can debug; q2dm1 is not.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapgen_fixture_lib import (  # noqa: E402
    Box,
    CONTENTS_MONSTERCLIP,
    CONTENTS_PLAYERCLIP,
    CONTENTS_SOLID,
    CONTENTS_WATER,
    Entity,
    MapFixture,
    hollow_room,
)

WALL = "e1u1/c_met5_2"
FLOOR = "e1u1/c_met5_1"
TRIM = "e1u1/c_met1_1"
WATER = "e1u1/c_met5_1"
CLIP = "e1u1/clip"

# Q2's ladder is a content flag; the fixture states it explicitly rather than
# relying on a texture name the compiler might read differently.
CONTENTS_LADDER = 0x20000000


def everything(path: Path) -> None:
    """A sealed room with one of each thing the gate compares."""
    fx = MapFixture("equivalence_everything",
                    "one of everything the equivalence gate looks at")

    fx.world_brushes = list(hollow_room((-448, -384, 0), (448, 384, 320),
                                        texture=WALL, floor_texture=FLOOR))

    # A step, in a second material, so a material can change without touching
    # every surface in the map.
    fx.world_brushes.append(Box((-160, 160, 0), (160, 320, 64),
                                texture=TRIM, contents=CONTENTS_SOLID))

    # A pool: a liquid class, and a surface the compiler handles its own way.
    fx.world_brushes.append(Box((-384, -320, 0), (-192, -128, 48),
                                texture=WATER, contents=CONTENTS_WATER))

    # Content a player runs into and cannot see.
    fx.world_brushes.append(Box((192, -320, 0), (256, -128, 192),
                                texture=CLIP,
                                contents=CONTENTS_PLAYERCLIP
                                       | CONTENTS_MONSTERCLIP))

    # Content that changes how he moves.
    fx.world_brushes.append(Box((320, 96, 0), (384, 224, 256),
                                texture=CLIP,
                                contents=CONTENTS_LADDER
                                       | CONTENTS_PLAYERCLIP
                                       | CONTENTS_MONSTERCLIP))

    # Two pillars with an eight-unit gap between them.
    #
    # The gap is a real piece of architecture - a slot too narrow to walk
    # through - and it is also the case Codex's section 1.7 asks for: a
    # region thinner than the sampling lattice. A 64-unit grid steps straight
    # over it, so anything that changes in there is invisible to a lattice and
    # visible to a probe of every leaf.
    fx.world_brushes.append(Box((-320, 224, 0), (-260, 320, 256),
                                texture=WALL, contents=CONTENTS_SOLID))
    fx.world_brushes.append(Box((-252, 224, 0), (-192, 320, 256),
                                texture=WALL, contents=CONTENTS_SOLID))

    # And an eight-unit clip brush filling that slot.
    #
    # A player-clip obstruction thinner than the sampling lattice: the case
    # Codex's section 1.7 asks for. Nothing draws it, a 64-unit grid steps over
    # it, and it is the difference between a slot a player can squeeze into and
    # one he cannot.
    fx.world_brushes.append(Box((-260, 224, 0), (-252, 320, 256),
                                texture=CLIP,
                                contents=CONTENTS_PLAYERCLIP
                                       | CONTENTS_MONSTERCLIP))

    # A machine, and something a player can reach that fires it.
    door = Box((-64, -32, 0), (64, 32, 160), texture=TRIM,
               contents=CONTENTS_SOLID)
    trigger = Box((-128, 64, 0), (128, 160, 128), texture=CLIP,
                  contents=CONTENTS_PLAYERCLIP | CONTENTS_MONSTERCLIP)

    fx.entities = [
        Entity("info_player_deathmatch",
               [("origin", "-320 -32 32"), ("angle", "0")]),
        Entity("info_player_deathmatch",
               [("origin", "320 -32 32"), ("angle", "180")]),
        Entity("item_health", [("origin", "0 224 96")]),
        Entity("light", [("origin", "0 0 256"), ("light", "300")]),
        Entity("func_door",
               [("targetname", "the_door"), ("angle", "-1"),
                ("speed", "100"), ("wait", "3")], brushes=[door]),
        Entity("trigger_multiple",
               [("target", "the_door"), ("wait", "2")], brushes=[trigger]),
    ]
    path.write_text(fx.emit(), encoding="ascii", newline="\n")


# Q2's areaportal is a content flag on a brush inside a func_areaportal.
CONTENTS_AREAPORTAL = 0x8000


def sealed_areas(path: Path) -> None:
    """Three rooms, two doorways, and a real areaportal in each doorway.

    The equivalence gate compares which areas each portal joins. None of the
    four donors has a func_areaportal at all, so that comparison has nothing to
    look at on the corpus and cannot be trusted by running it there.

    The three rooms have three different volumes and the middle one has two
    portals where the outer two have one each. That is what makes a rewired
    portal visible as a different graph instead of the same graph renumbered:
    both ends of a portal are described by (how many portals that area has, how
    much space it holds), and here no two areas share a description.
    """
    fx = MapFixture("equivalence_sealed_areas",
                    "three rooms of three sizes, joined by two areaportals")

    # One shell, divided by two walls. The outer walls are 16 thick.
    fx.world_brushes = list(hollow_room((-1024, -256, 0), (768, 256, 256),
                                        texture=WALL, floor_texture=FLOOR))

    # Two dividing walls, each with a doorway 128 wide and 128 high.
    #
    # The rooms they cut out are 656, 640 and 400 units across, so no two areas
    # hold the same amount of space.
    for x0, x1 in ((-352, -320), (320, 352)):
        # left of the doorway, right of it, and the lintel above it
        fx.world_brushes.append(Box((x0, -256, 0), (x1, -64, 256),
                                    texture=WALL, contents=CONTENTS_SOLID))
        fx.world_brushes.append(Box((x0, 64, 0), (x1, 256, 256),
                                    texture=WALL, contents=CONTENTS_SOLID))
        fx.world_brushes.append(Box((x0, -64, 128), (x1, 64, 256),
                                    texture=WALL, contents=CONTENTS_SOLID))

    # The doorway fillers, and a door in each doorway that opens them.
    portal_a = Box((-352, -64, 0), (-320, 64, 128),
                   texture=CLIP, contents=CONTENTS_AREAPORTAL)
    portal_b = Box((320, -64, 0), (352, 64, 128),
                   texture=CLIP, contents=CONTENTS_AREAPORTAL)
    door_a = Box((-348, -64, 0), (-324, 64, 128), texture=TRIM,
                 contents=CONTENTS_SOLID)
    door_b = Box((324, -64, 0), (348, 64, 128), texture=TRIM,
                 contents=CONTENTS_SOLID)

    fx.entities = [
        Entity("info_player_deathmatch",
               [("origin", "-700 0 32"), ("angle", "0")]),
        Entity("info_player_deathmatch",
               [("origin", "560 0 32"), ("angle", "180")]),
        Entity("light", [("origin", "-700 0 200"), ("light", "300")]),
        Entity("light", [("origin", "0 0 200"), ("light", "300")]),
        Entity("light", [("origin", "560 0 200"), ("light", "300")]),
        Entity("func_door", [("targetname", "door_a"), ("angle", "-1"),
                             ("speed", "100"), ("wait", "3")],
               brushes=[door_a]),
        Entity("func_door", [("targetname", "door_b"), ("angle", "-1"),
                             ("speed", "100"), ("wait", "3")],
               brushes=[door_b]),
        Entity("func_areaportal", [("style", "1")], brushes=[portal_a]),
        Entity("func_areaportal", [("style", "2")], brushes=[portal_b]),
    ]
    path.write_text(fx.emit(), encoding="ascii", newline="\n")


FIXTURES = {"everything": everything,
            "sealed_areas": sealed_areas}


if __name__ == "__main__":
    which = sys.argv[2] if len(sys.argv) > 2 else "everything"
    out = Path(sys.argv[1] if len(sys.argv) > 1 else f"{which}.map")
    FIXTURES[which](out)
    print(f"wrote {out}")
