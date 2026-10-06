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

MAPGEN-1 - MapGenEntities: who spawns where, and what is lying around

Contract section 16 stage 8, contract 13's item controls and contract 18.2's
spawn and item safety.

--- An explicit count is a promise, not a preference ------------------------

Contract 13 is unambiguous: `Custom 0` means none and is a hard constraint, and
an exact count is exact. So the resolved count in the recipe is what gets
placed - not approximately, and never quietly reduced because placing them was
awkward. When there is nowhere safe to put the last one, that is a REFUSAL with
the item named, which contract 14 calls a preflight conflict and which the
attempt loop answers by trying a different candidate.

--- Standing on the floor, not in it ----------------------------------------

An entity's origin sits where the engine expects it: a player spawn is placed
so the hull's feet rest on the floor, which is 24 units up, because
`inc/shared/shared.h` puts the player's mins at -24. An item is placed on the
same rule. Getting this wrong produces a map that looks right in an editor and
telefrags on the first spawn.

--- Spread comes from the graph, not from geometry --------------------------

Spawn points are pushed apart by ROOM, not by distance in units: two spawns
ten units apart through a wall are further apart in play than two spawns
across the same room. The topology graph is what knows that, so it is what
decides.

==============================================================================
*/

#pragma once

#include "common/mapgen_layout.h"
#include "common/mapgen_mix.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_PLACEMENT_CLASSNAME_BYTES 40
#define MAPGEN_ENTITIES_MAX           4096

/* The player's feet, from inc/shared/shared.h: mins z is -24. */
#define MAPGEN_PLACEMENT_FLOOR_OFFSET    24
/* Item pickups are smaller; 16 up clears the floor without floating. */
#define MAPGEN_PLACEMENT_ITEM_OFFSET     16

/*
 * A light dimmer than this is not worth the entity: the compiler's own
 * falloff puts it below one lightmap unit within a few dozen units, and
 * the corpus's dimmest light is 30.
 */
#define MAPGEN_LIGHT_MIN_INTENSITY       30

/* A placement that is in a passage rather than in any room. */
#define MAPGEN_PLACEMENT_NO_ROOM         UINT32_MAX

typedef enum {
    MAPGEN_ENTITIES_OK = 0,
    MAPGEN_ENTITIES_ERR_ARGS,
    MAPGEN_ENTITIES_ERR_MEMORY,
    MAPGEN_ENTITIES_ERR_NO_ROOMS,
    /* Contract 13: an exact count that cannot be placed safely is refused
       with the control named, never quietly reduced. */
    MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE,
    MAPGEN_ENTITIES_ERR_TOO_MANY,
} mapgen_entities_result_t;

const char *MapGenEntities_ResultName(mapgen_entities_result_t r);

/*
 * One PLACEMENT, not an entity: `mapgen_genome.h` owns `mapgen_entity_t` for
 * an entity parsed out of a real map, and a thing this module decides to put
 * somewhere is the opposite direction of travel. Two concepts under one name
 * is how a reader ends up comparing a measured entity with a planned one.
 */
typedef struct {
    char    classname[MAPGEN_PLACEMENT_CLASSNAME_BYTES];
    int32_t origin[3];
    int32_t angle;              /* degrees, 0..359 */
    /*
     * The room it stands in, or MAPGEN_PLACEMENT_NO_ROOM when it stands in a
     * passage instead. Naming a room a thing is nowhere near is a small
     * untruth every later stage would inherit.
     */
    uint32_t room;
    /*
     * For a light, the intensity it was given - learned from the corpus, not
     * left to the compiler's default. Zero on everything else.
     *
     * Leaving it out is not choosing 300; it is declining to choose, and the
     * maps that came of that averaged 2.3 of 255 on their own lightmaps.
     */
    int32_t light;
    /*
     * And the colour it was given, packed 0xRRGGBB, or 0 for the engine's
     * plain white.
     *
     * Without this every light in every map was white, so every lightmap texel
     * came out with r == g == b - which renders exactly as though coloured
     * lightmaps were switched off, and is what the PO reported seeing.
     */
    uint32_t light_colour;
} mapgen_placement_t;

typedef struct mapgen_entities_s mapgen_entities_t;

/*
 * Place them. `conflict` receives the control that could not be satisfied when
 * the result is ERR_NO_SAFE_PLACE, because contract 14 wants the exact
 * conflict named rather than the fact that one exists.
 */
mapgen_entities_result_t MapGenEntities_Build(const mapgen_layout_t *layout,
                                              const mapgen_topology_t *topology,
                                              const mapgen_mix_t *model,
                                              const mapgen_recipe_t *recipe,
                                              uint32_t attempt,
                                              const char **conflict,
                                              mapgen_entities_t **out);
void MapGenEntities_Free(mapgen_entities_t *entities);

uint32_t MapGenEntities_Count(const mapgen_entities_t *e);
const mapgen_placement_t *MapGenEntities_At(const mapgen_entities_t *e,
                                         uint32_t index);
uint32_t MapGenEntities_CountOf(const mapgen_entities_t *e,
                                const char *classname);

/*
 * The item controls this module places, in the order it places them. The names
 * are the recipe control keys, and the classnames are the stock ones from the
 * baseq2 entity schema.
 */
uint32_t MapGenEntities_NumItemKinds(void);
const char *MapGenEntities_ItemControl(uint32_t index);
const char *MapGenEntities_ItemClassname(uint32_t index);

size_t   MapGenEntities_CanonicalText(const mapgen_entities_t *e, char *out,
                                      size_t capacity);
uint64_t MapGenEntities_CanonicalDigest(const mapgen_entities_t *e);
