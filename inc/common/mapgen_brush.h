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

MAPGEN-1 - MapGenBrush: the solid world around the empty space

Contract section 16, stages 6 and 7: a project-owned constructive grammar of
convex brushes, with exact allowed material roles on every face.

--- Why the solid is derived and not assembled ------------------------------

The obvious construction is to wrap each room in six slabs. It is also wrong:
the slab where a corridor meets a room seals the corridor, and unsealing it
means splitting slabs around openings, which is a special case for every shape
a passage can arrive in.

So the solid is DERIVED. The empty space is marked on a voxel grid, the shell
is every solid voxel within a wall's thickness of it, and the openings appear
by themselves wherever two empty volumes meet - because they were never
anything but empty. A corridor joining a room needs no code at all.

The price is a voxel grid and a merge pass. The gain is that "the map is
sealed" is a property of the construction, checkable by flood fill, instead of
a list of cases somebody has to keep complete.

--- Materials come from the corpus, by role ---------------------------------

Contract 15: a face's texture is chosen from the mixed model's allowlist, by
what the corpus USED that material as - floor, wall, ceiling - and never from
its filename. A face whose role the corpus never taught cannot be textured, and
that is a refusal rather than a guess.

==============================================================================
*/

#pragma once

#include "common/mapgen_layout.h"
#include "common/mapgen_mix.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* One voxel is one grid step, so every layout coordinate lands exactly. */
#define MAPGEN_BRUSH_VOXEL        MAPGEN_LAYOUT_GRID

/* A wall is two voxels thick: thin enough not to waste the world, thick
   enough that a compiler never treats it as a crack. */
#define MAPGEN_BRUSH_WALL_VOXELS  2

/* A grid bigger than this is refused rather than allocated. */
#define MAPGEN_BRUSH_MAX_VOXELS   (64u * 1024u * 1024u)
#define MAPGEN_BRUSH_MAX_BRUSHES  65536u

typedef enum {
    MAPGEN_BRUSH_OK = 0,
    MAPGEN_BRUSH_ERR_ARGS,
    MAPGEN_BRUSH_ERR_MEMORY,
    MAPGEN_BRUSH_ERR_EMPTY_LAYOUT,
    MAPGEN_BRUSH_ERR_GRID_TOO_LARGE,
    MAPGEN_BRUSH_ERR_TOO_MANY_BRUSHES,
    /* The corpus taught no material for a role the map needs. Contract 15
       makes that a refusal: there is nothing legitimate to put there. */
    MAPGEN_BRUSH_ERR_NO_MATERIAL,
    /*
     * The model was mixed without a target manifest, so its allowlist is what
     * the CORPUS had rather than what the TARGET has. Texturing from one
     * produced a map of 556 brushes carrying a texture baseq2 cannot resolve,
     * and the compiler only warned. Refused rather than made reachable by
     * forgetting an argument.
     */
    MAPGEN_BRUSH_ERR_NO_TARGET_MANIFEST,
    /* The shell did not seal - a flood from outside reached empty space. */
    MAPGEN_BRUSH_ERR_LEAK,
} mapgen_brush_result_t;

const char *MapGenBrush_ResultName(mapgen_brush_result_t r);

/* Which way a face looks, and therefore what it is. */
typedef enum {
    MAPGEN_FACE_EAST = 0,       /* +x */
    MAPGEN_FACE_WEST,           /* -x */
    MAPGEN_FACE_NORTH,          /* +y */
    MAPGEN_FACE_SOUTH,          /* -y */
    MAPGEN_FACE_TOP,            /* +z - a floor, seen from the room above  */
    MAPGEN_FACE_BOTTOM,         /* -z - a ceiling, seen from the room below */

    MAPGEN_FACE_COUNT
} mapgen_face_t;

const char *MapGenBrush_FaceName(mapgen_face_t face);

typedef struct {
    int32_t mins[3];
    int32_t maxs[3];
    /* One material index into the mixed model's allowlist, per face. */
    uint32_t material[MAPGEN_FACE_COUNT];
} mapgen_brush_t;

/*
 * A jump pad needs this much room above it before one is built at all.
 *
 * Two corridor heights plus the player: less than that and the pad throws
 * whoever steps on it into the ceiling, which is a place you cannot get past
 * rather than a route.
 */
#define MAPGEN_BRUSH_MIN_PAD_HEADROOM 320

/*
 * A light panel: how big one is, how deep, and how much floor each one lights.
 *
 * Sized from what the corpus does rather than from taste - its emitting
 * surfaces run from 36 to 963 sides across maps of this size, which is a
 * fitting every few hundred units rather than one bulb per room.
 */
#define MAPGEN_BRUSH_PANEL_SIZE    64
#define MAPGEN_BRUSH_PANEL_DEPTH    16

/*
 * How deep a light recess is cut UP into the ceiling rock.
 *
 * A recess cannot hang in the air the way the box it replaces could: the rock
 * around it is its housing. 195 of about 200 hung fittings were floating.
 */
#define MAPGEN_BRUSH_RECESS_DEPTH   32
#define MAPGEN_BRUSH_PANEL_SPACING 144

#define MAPGEN_FIXTURE_CLASSNAME_BYTES 32
#define MAPGEN_FIXTURE_KEY_BYTES       24
#define MAPGEN_FIXTURE_VALUE_BYTES     40
#define MAPGEN_FIXTURE_MAX_KEYS         6
#define MAPGEN_MAX_FIXTURES           256

typedef struct {
    char key[MAPGEN_FIXTURE_KEY_BYTES];
    char value[MAPGEN_FIXTURE_VALUE_BYTES];
} mapgen_fixture_key_t;

/*
 * One brush entity: a door, a lift, a push trigger, a teleport trigger.
 *
 * The brush is a box like any other and carries a material per face, so a
 * door is textured out of the same learned allowlist as the wall it sits in.
 */
typedef struct {
    char                 classname[MAPGEN_FIXTURE_CLASSNAME_BYTES];
    mapgen_brush_t       brush;
    mapgen_fixture_key_t keys[MAPGEN_FIXTURE_MAX_KEYS];
    uint32_t             num_keys;
} mapgen_fixture_t;

typedef struct mapgen_brushwork_s mapgen_brushwork_t;

mapgen_brush_result_t MapGenBrush_Build(const mapgen_layout_t *layout,
                                        const mapgen_mix_t *model,
                                        const mapgen_recipe_t *recipe,
                                        uint32_t attempt,
                                        mapgen_brushwork_t **out);
void MapGenBrush_Free(mapgen_brushwork_t *work);

uint32_t MapGenBrush_Count(const mapgen_brushwork_t *work);
const mapgen_brush_t *MapGenBrush_At(const mapgen_brushwork_t *work,
                                     uint32_t index);
uint32_t MapGenBrush_NumFixtures(const mapgen_brushwork_t *work);
const mapgen_fixture_t *MapGenBrush_Fixture(const mapgen_brushwork_t *work,
                                            uint32_t index);
/*
 * A point entity a fixture needs to work - a teleporter's destination, a jump
 * pad's target. It has no brush, so it rides with the fixtures rather than
 * with the item placements, which are chosen by a different stage for
 * different reasons.
 */
uint32_t MapGenBrush_NumMarkers(const mapgen_brushwork_t *work);
const mapgen_fixture_t *MapGenBrush_Marker(const mapgen_brushwork_t *work,
                                           uint32_t index);
/* How many voxels the empty space occupies - the volume a player can be in. */
uint64_t MapGenBrush_EmptyVoxels(const mapgen_brushwork_t *work);
const mapgen_layout_box_t *MapGenBrush_Bounds(const mapgen_brushwork_t *work);

size_t   MapGenBrush_CanonicalText(const mapgen_brushwork_t *work,
                                   const mapgen_mix_t *model,
                                   char *out, size_t capacity);
uint64_t MapGenBrush_CanonicalDigest(const mapgen_brushwork_t *work,
                                     const mapgen_mix_t *model);
