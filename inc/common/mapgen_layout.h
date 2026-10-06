/*
Copyright (C) 2026 Q2PRO-X

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
*/

/*
==============================================================================

MAPGEN-1 - MapGenLayout: where the graph actually is

Contract section 16, stage 6: a project-owned constructive grammar of convex
brushes. This module does the placing; turning the placed volumes into brushes
and then into a `.map` file is the stage after it.

--- Integers on a grid, and no floating point anywhere ----------------------

Every coordinate is a multiple of 16 and is stored as an int32. Contract 10
requires the same recipe to produce the same `source.map` regardless of
machine, and the surest way to keep that promise is to have no rounding to get
wrong. It also happens to be what Quake II mapping does anyway.

--- A crossing is a junction; a hole in a wall is not ------------------------

Corridors are routed along the lanes between cells, where no room can reach, so
a passage cannot cut through a room it does not connect. That is by
construction and the check that remains is its proof, not its enforcement.

Two corridors crossing each other is a different thing: it is a junction, which
real maps have everywhere, and it adds only WALK adjacency - never a route kind
the user turned off. So junctions are permitted and COUNTED rather than
forbidden. Forbidding them was tried and refused 394 embeddings out of 400 at
Very Large scale, for a rule that describes no real map.

What the layout therefore claims is narrower and true: every planned route is
realized, no passage breaches an unrelated room, and here is how many junctions
the result has. Contract 16 stage 12 reloads the compiled BSP and validates
THAT - the map is the truth and the graph was always the plan.

--- Everything a player has to fit through ----------------------------------

The minimum sizes here come from the engine's own hull: a standing player is
32 wide and 56 tall with the eye at 22, and `src/common/pmove/template.c:19`
sets STEPSIZE to 18. A corridor narrower than the hull is not a corridor, so
those are floors and not preferences.

==============================================================================
*/

#pragma once

#include "common/mapgen_blueprint.h"
#include "common/mapgen_blueprint.h"
#include "common/mapgen_topology.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Everything is a multiple of this. */
#define MAPGEN_LAYOUT_GRID            16

/* The player hull, from inc/shared/shared.h and the pmove template. */
#define MAPGEN_LAYOUT_HULL_WIDTH      32
#define MAPGEN_LAYOUT_HULL_HEIGHT     56

/*
 * A tall room, and a room open to the sky.
 *
 * MEASURED: q2dm1 spans 1408 units of height over a 2336-unit footprint. Rooms
 * 256 to 384 high, which is what these used to be, cannot add up to that
 * however many of them there are.
 */
#define MAPGEN_LAYOUT_TALL_ROOM_HEIGHT 768
/*
 * A room open to the sky is a YARD, and a yard has a parapet rather than a
 * shaft.
 *
 * MEASURED on the map the PO walked on 2026-09-07, whose outdoor rooms were
 * this tall: 411 permille of its floor had sky straight overhead and NOBODY
 * standing anywhere in it could see sky below thirty degrees of elevation -
 * the lid was a thousand units up behind twelve hundred units of wall, and he
 * said he was running in a box whose lid had been opened a crack. q2dm1, at
 * the same measure, has a hundred and thirty-four permille of its floor with
 * sky at or below thirty degrees and its top storey sees sky at zero.
 *
 * So the height of an outdoor room is now the height of a WALL a player can
 * see over from the floor beside it, and the number is chosen against that
 * measurement rather than against a ceiling: two hundred and eighty-eight
 * units over a courtyard eleven hundred and fifty-two wide puts the parapet
 * at twenty-three degrees from the middle of it.
 */
#define MAPGEN_LAYOUT_SKY_ROOM_HEIGHT  288

/*
 * A room has to hold a FIGHT, and a fight needs somewhere to move.
 *
 * The first version used 192 to 512, which is a corridor with delusions: two
 * players in a 192-unit box are already touching. These are the sizes the
 * corpus's own arenas run at.
 */
#define MAPGEN_LAYOUT_MIN_ROOM        384
#define MAPGEN_LAYOUT_MAX_ROOM        1152
#define MAPGEN_LAYOUT_MIN_ROOM_HEIGHT 256

/* Wide enough for two players to pass, tall enough to walk and jump. */
/*
 * The narrowest a connection may be, and the widest.
 *
 * Every passage used to be exactly MIN wide and MIN high, which made contract
 * 14's "corridors vs open arenas" row a setting with nothing behind it: ten
 * rooms joined by ten identical pipes reads as a corridor system whatever the
 * rooms are. A wide passage is an OPENING between two rooms, which is what
 * most connections in the corpus are.
 */
#define MAPGEN_LAYOUT_CORRIDOR_WIDTH  128
#define MAPGEN_LAYOUT_CORRIDOR_HEIGHT 128
#define MAPGEN_LAYOUT_OPENING_WIDTH   384
#define MAPGEN_LAYOUT_OPENING_HEIGHT  256

/*
 * One height band to the next: one flight of stairs.
 *
 * 128 is eight 16-unit steps, and 16 is inside STEPSIZE 18
 * (src/common/pmove/template.c:19) so a player walks up it without jumping.
 * At 512 nothing could climb between bands at all, and every floor above the
 * ground was somewhere you could only fall into.
 */
#define MAPGEN_LAYOUT_BAND_HEIGHT     128

/* One step of that flight. */
#define MAPGEN_LAYOUT_STEP_RISE       16
#define MAPGEN_LAYOUT_STEP_RUN        64

/*
 * The cell a room is placed in. It is wider than the largest room by more
 * than a corridor, which is what makes the lane down the middle of the gap
 * between two cells clear of every room by construction.
 */
#define MAPGEN_LAYOUT_CELL            1536

/*
 * At most this many axis-aligned segments make up one passage: four for the
 * route itself and room for the flight of stairs when it changes band.
 */
/*
 * Enough for a real flight of stairs.
 *
 * Four segments of a passage are its approach and its exit; the rest are the
 * climb, one box per sixteen-unit step. At sixteen that capped a climb at a
 * hundred and ninety-two units and rooms a level apart silently became shafts
 * nobody could get out of. Forty-eight is seven hundred units of climb, and a
 * passage that needs more than that is refused rather than built as a hole.
 */
#define MAPGEN_LAYOUT_MAX_SEGMENTS    48

/* Quake II's own world limit is +/-4096; staying well inside it is what keeps
   a compiled map from being clipped. */
#define MAPGEN_LAYOUT_WORLD_LIMIT     4096

/* At most this many pools of liquid in one map. */
#define MAPGEN_LAYOUT_MAX_POOLS       16

/* A pool is this deep, and inset this far from the walls of its room. */
#define MAPGEN_LAYOUT_POOL_DEPTH      96
#define MAPGEN_LAYOUT_POOL_INSET      96

typedef enum {
    MAPGEN_LAYOUT_OK = 0,
    MAPGEN_LAYOUT_ERR_ARGS,
    MAPGEN_LAYOUT_ERR_MEMORY,
    MAPGEN_LAYOUT_ERR_NO_NODES,
    /* No free cell next to the parent - the graph is denser than the grid. */
    MAPGEN_LAYOUT_ERR_NO_ROOM_TO_PLACE,
    /* A corridor would breach a room it does not connect. */
    MAPGEN_LAYOUT_ERR_INTERSECTION,
    /* The placement wandered outside the world. */
    MAPGEN_LAYOUT_ERR_OUT_OF_WORLD,
    /*
     * Two rooms are further apart in height than a flight of stairs can
     * cover, and the route between them is not a lift. One box from the lower
     * floor to the upper one is a hole a player falls into and cannot leave,
     * so the layout is refused and the next attempt is a different map.
     */
    MAPGEN_LAYOUT_ERR_TOO_STEEP,
} mapgen_layout_result_t;

const char *MapGenLayout_ResultName(mapgen_layout_result_t r);

/* An axis-aligned box of EMPTY space: what a player can stand in. */
typedef struct {
    int32_t mins[3];
    int32_t maxs[3];
} mapgen_layout_box_t;

typedef struct {
    mapgen_layout_box_t space;
    uint32_t            node;       /* the topology node it realizes */
    int32_t             cell[2];    /* which grid cell it was placed in */
    /*
     * Whether this room is open to the sky.
     *
     * An outdoor room's ceiling is the learned sky material, and it is built
     * tall: a courtyard 256 units high is a well. How many rooms are outdoor
     * follows the learned sky share - q2dm1 states 23 parts per thousand of
     * its surface, and every generated map before this stated 0.
     */
    bool                outdoor;
} mapgen_layout_room_t;

/*
 * A passage is a chain of axis-aligned segments: a stub out of the first room
 * into the lane, a run along the lane, and a stub into the second room. One
 * box could not do it without cutting through whatever stood between.
 */
typedef struct {
    mapgen_layout_box_t segments[MAPGEN_LAYOUT_MAX_SEGMENTS];
    uint32_t            num_segments;
    uint32_t            route;      /* the topology route it realizes */
    /*
     * And what KIND of route that is - mapgen_route_kind_t.
     *
     * The topology has chosen between a walk, a lift, a door, a teleporter and
     * a jump pad since it was written, and the layout used to build all ten
     * kinds as the same corridor. A plan that says lift and geometry that says
     * corridor is not a lift; carrying the kind here is what lets the brush
     * stage build the thing that was planned.
     */
    uint32_t            kind;
    uint32_t            from_room;
    uint32_t            to_room;
} mapgen_layout_passage_t;

/*
 * A pool of liquid sunk into a room's floor.
 *
 * The space is EMPTY - a player swims in water and burns in lava, but is in
 * both - so the brush stage carves it like a room and then fills it with a
 * brush whose material carries the contents. Which liquid it is comes from the
 * learned role, so a corpus that never had lava cannot produce one.
 */
typedef struct {
    mapgen_layout_box_t space;      /* the pit, empty                         */
    mapgen_layout_box_t liquid;     /* the part of it the liquid fills        */
    uint32_t            role;       /* MAPGEN_ROLE_WATER, _LAVA or _SLIME     */
    uint32_t            room;       /* the room it is sunk into               */
} mapgen_layout_pool_t;

typedef struct mapgen_layout_s mapgen_layout_t;

/*
 * Place the graph. `attempt` selects the seed stream, and a failed embedding
 * is an ordinary outcome for one attempt - the caller tries the next.
 */
mapgen_layout_result_t MapGenLayout_Build(const mapgen_topology_t *topology,
                                          const mapgen_mix_t *model,
                                          const mapgen_recipe_t *recipe,
                                          uint32_t attempt,
                                          mapgen_layout_t **out);
void MapGenLayout_Free(mapgen_layout_t *layout);

/*
 * Lower a candidate blueprint into rooms and passages.
 *
 * The other Build INVENTS a plan: one XY cell per node, floors from band
 * indices, which cannot express two volumes stacked over one another. This one
 * decides nothing - the rooms are the candidate's volumes at its own
 * coordinates and the passages are its portals - so a map built this way is as
 * compact and as stacked as the architecture it came from.
 */
mapgen_layout_result_t MapGenLayout_FromBlueprint(const mapgen_blueprint_t *bp,
                                                  const mapgen_recipe_t *recipe,
                                                  mapgen_layout_t **out);

/*
 * Lower a candidate blueprint into rooms and passages.
 *
 * The other Build INVENTS a plan: one XY cell per node, floors from band
 * indices, which cannot express two volumes stacked over one another. This one
 * decides nothing - the rooms are the candidate's volumes at its own
 * coordinates and the passages are its portals - so a map built this way is as
 * compact and as stacked as the architecture it came from.
 */
mapgen_layout_result_t MapGenLayout_FromBlueprint(const mapgen_blueprint_t *bp,
                                                  const mapgen_recipe_t *recipe,
                                                  mapgen_layout_t **out);

uint32_t MapGenLayout_NumRooms(const mapgen_layout_t *l);
uint32_t MapGenLayout_NumPassages(const mapgen_layout_t *l);
const mapgen_layout_room_t *MapGenLayout_Room(const mapgen_layout_t *l,
                                              uint32_t index);
const mapgen_layout_passage_t *MapGenLayout_Passage(const mapgen_layout_t *l,
                                                    uint32_t index);
uint32_t MapGenLayout_NumPools(const mapgen_layout_t *l);
const mapgen_layout_pool_t *MapGenLayout_Pool(const mapgen_layout_t *l,
                                              uint32_t index);
/* The box every room and passage fits inside. */
const mapgen_layout_box_t *MapGenLayout_Bounds(const mapgen_layout_t *l);

/*
 * How many places two unrelated passages meet. Not a fault - a junction - but
 * a number the report states rather than leaves implied, because it is
 * connectivity the topology graph did not plan.
 */
uint32_t MapGenLayout_NumJunctions(const mapgen_layout_t *l);

size_t   MapGenLayout_CanonicalText(const mapgen_layout_t *l, char *out,
                                    size_t capacity);
uint64_t MapGenLayout_CanonicalDigest(const mapgen_layout_t *l);
