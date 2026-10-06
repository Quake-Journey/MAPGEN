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

MAPGEN-1 - MapGenBlueprint: what a map's ARCHITECTURE is

Contract section 5.4.1, added by the Codex directive of 2026-09-01.

--- Why this exists ----------------------------------------------------------

Training used to extract only aggregates from a source map - how many regions,
how many height bands, what share is sky, which materials and how often. Where
the volumes are, how big they are, what connects to what and what sits above
what was discarded at the learning stage, and synthesis then invented a fresh
grid of boxes from those numbers.

That is why the PO's request - a 0..100 control that at 100 yields a
recognizable fork of the source - could not be built at any setting: nothing
in the pipeline held the source's form for a control to interpolate towards.
This module holds it.

--- A volume is not a region -------------------------------------------------

`MapGenSpace`'s `region` is a connected component over walk/step/swim edges.
aerowalk has 63 of them; q2dm1 has 81. It is not a room, and renaming it to one
would be the same mistake in new words. Segmentation here is deliberate:

  * a stance's WALK degree says whether it is in the open or in a passage - a
    corridor is thin, a hall is not, and the space layer already counts this;
  * volumes are the connected components of each class separately, so a hall
    and the corridor leaving it are two volumes rather than one blob;
  * an edge whose ends are in different volumes is a PORTAL, and it carries the
    traversal kind, the signed height change and whether it is one-way.

--- What the fidelity control will measure -----------------------------------

Four independent axes, per contract 18.0, and this module supplies the source
side of all four: the volume/portal graph, the normalized occupancy of each
volume, the vertical and overlap relations between them, and which volumes are
landmarks. Nothing here averages anything: a blueprint is one map's own shape.

--- What must never be in here -----------------------------------------------

Raw source BSP bytes, original brush arrays and authoring CSG are forbidden
payloads (contract 15). A blueprint is the project's own semantic description
of playable space, derived from the compiled map and rebuildable from it.

==============================================================================
*/

#pragma once

#include "common/mapgen_bsp.h"
#include "common/mapgen_genome.h"
#include "common/mapgen_space.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/*
 * The coordinate basis every blueprint is quantized to.
 *
 * Fixed at 16 units because that is the layout grid the generator builds on,
 * so a preserved volume lands on the grid it will be rebuilt on rather than
 * one quantization step away from it.
 */
#define MAPGEN_BLUEPRINT_BASIS        16

#define MAPGEN_BLUEPRINT_MAX_VOLUMES  1024u
#define MAPGEN_BLUEPRINT_MAX_PORTALS  4096u
#define MAPGEN_BLUEPRINT_MAX_RELATIONS 8192u

/* A stance with this many walk neighbours or fewer is in a passage, not in a
   room. The space layer counts these already; the threshold is stated once. */
#define MAPGEN_BLUEPRINT_THIN_DEGREE  2

typedef enum {
    MAPGEN_BLUEPRINT_OK = 0,
    MAPGEN_BLUEPRINT_ERR_ARGS,
    MAPGEN_BLUEPRINT_ERR_MEMORY,
    MAPGEN_BLUEPRINT_ERR_NO_SPACE,
    MAPGEN_BLUEPRINT_ERR_TOO_MANY_VOLUMES,
    MAPGEN_BLUEPRINT_ERR_TOO_MANY_PORTALS,
    MAPGEN_BLUEPRINT_ERR_TOO_MANY_RELATIONS,
} mapgen_blueprint_result_t;

const char *MapGenBlueprint_ResultName(mapgen_blueprint_result_t r);

/* What a volume IS, as opposed to how big it is. */
typedef enum {
    MAPGEN_VOLUME_HALL = 0,     /* open space: a fight happens here          */
    MAPGEN_VOLUME_PASSAGE,      /* thin space: you travel through it         */

    MAPGEN_VOLUME_CLASS_COUNT
} mapgen_volume_class_t;

const char *MapGenBlueprint_ClassName(mapgen_volume_class_t c);

/* Volume flags: what the space contains, not what it is shaped like. */
#define MAPGEN_VOLUME_LIQUID   0x0001
#define MAPGEN_VOLUME_HAZARD   0x0002
#define MAPGEN_VOLUME_SKY      0x0004   /* open to the sky above             */
#define MAPGEN_VOLUME_DUCKED   0x0008   /* only a ducked hull fits           */

typedef struct {
    uint32_t id;                /* stable within one blueprint               */
    uint8_t  klass;             /* mapgen_volume_class_t                     */
    uint16_t flags;
    int32_t  mins[3];           /* on the 16-unit basis                      */
    int32_t  maxs[3];
    int32_t  floor;             /* the level a player stands on              */
    int32_t  ceiling;           /* floor + the median clearance above it     */
    uint32_t stances;           /* how much walkable surface it holds        */
    /*
     * How much of this volume's own footprint is walkable, per thousand.
     *
     * The shape payload contract 8 requires, in the one number that survives
     * being rebuilt on a different grid: a long thin volume and a square one
     * of the same area are different maps.
     */
    uint32_t occupancy_permille;
    /* Deterministic landmark weight: stances scaled by openness. The biggest
       spaces are what a player remembers a map by. */
    uint32_t landmark_weight;
} mapgen_blueprint_volume_t;

typedef struct {
    uint32_t from;              /* volume id                                 */
    uint32_t to;
    uint8_t  kind;              /* mapgen_edge_kind_t                        */
    bool     one_way;
    int32_t  rise;              /* signed, `from` to `to`                    */
    uint32_t aperture;          /* how many stance edges cross here          */
    uint16_t clearance;         /* the tightest headroom on the way through  */
} mapgen_blueprint_portal_t;

/* How two volumes sit relative to one another. */
typedef enum {
    MAPGEN_RELATION_ABOVE = 0,  /* `a` is entirely above `b`                 */
    MAPGEN_RELATION_OVERLAP_XY, /* their footprints intersect                */
    MAPGEN_RELATION_CONTAINS,   /* `a`'s bounds contain `b`'s                */
    MAPGEN_RELATION_ADJACENT,   /* they touch without a portal               */

    MAPGEN_RELATION_COUNT
} mapgen_relation_kind_t;

const char *MapGenBlueprint_RelationName(mapgen_relation_kind_t r);

typedef struct {
    uint32_t a;
    uint32_t b;
    uint8_t  kind;              /* mapgen_relation_kind_t                    */
} mapgen_blueprint_relation_t;

typedef struct mapgen_blueprint_s mapgen_blueprint_t;

/*
 * Extract one map's architecture.
 *
 * `space` supplies the stances and their typed edges, `genome` the materials
 * and entities, `bsp` the world bounds. All three are required: a blueprint
 * built from part of the picture silently means something else.
 */
mapgen_blueprint_result_t MapGenBlueprint_Build(const mapgen_bsp_t *bsp,
                                                const mapgen_genome_t *genome,
                                                const mapgen_space_t *space,
                                                mapgen_blueprint_t **out);
void MapGenBlueprint_Free(mapgen_blueprint_t *bp);

/*
 * --- constructing one -------------------------------------------------------
 *
 * A candidate is a blueprint the generator WRITES rather than reads, so that it
 * can be compared with a donor's by exactly the same rules. Volumes must be
 * added in id order; a portal must name volumes that already exist.
 */
mapgen_blueprint_result_t MapGenBlueprint_CreateEmpty(mapgen_blueprint_t **out);
mapgen_blueprint_result_t MapGenBlueprint_AddVolume(mapgen_blueprint_t *bp,
                                                    const mapgen_blueprint_volume_t *v);
mapgen_blueprint_result_t MapGenBlueprint_AddPortal(mapgen_blueprint_t *bp,
                                                    const mapgen_blueprint_portal_t *p);

/*
 * What a fidelity edit spends its budget on.
 *
 * Dropping a volume takes its portals with it and renumbers everything above
 * it: a candidate whose portals point at volumes that are gone is not a map
 * with one room fewer, it is a broken graph.
 */
mapgen_blueprint_result_t MapGenBlueprint_DropPortal(mapgen_blueprint_t *bp,
                                                     uint32_t index);
mapgen_blueprint_result_t MapGenBlueprint_DropVolume(mapgen_blueprint_t *bp,
                                                     uint32_t index);

/*
 * Contract the volume's FOOTPRINT toward its own centre, in permille.
 *
 * Horizontal only: the floor and the ceiling are what the portals' rise and
 * clearance were measured against, and a volume whose floor moved under a
 * stair that still expects the old height is where a flight of steps ends in
 * mid air. Refused if the result would be too small to stand and fight in, so
 * a caller can spend down a budget without checking the arithmetic itself.
 */
#define MAPGEN_BLUEPRINT_MIN_FOOTPRINT 128

mapgen_blueprint_result_t MapGenBlueprint_ReshapeVolume(mapgen_blueprint_t *bp,
                                                        uint32_t index,
                                                        uint32_t shrink_permille);

/*
 * The global transform fidelity 100 permits: a translation and an
 * axis-preserving 90-degree rotation, optionally mirrored.
 *
 * Applied to a box, in one place, because every volume and every relation has
 * to receive the SAME transform - a map half-rotated is not the donor seen
 * from another side, it is a different map.
 */
void MapGenBlueprint_Transform(const int32_t mins[3], const int32_t maxs[3],
                               uint32_t quarter_turns, bool mirror,
                               int32_t out_mins[3], int32_t out_maxs[3]);

uint32_t MapGenBlueprint_NumVolumes(const mapgen_blueprint_t *bp);
const mapgen_blueprint_volume_t *MapGenBlueprint_Volume(const mapgen_blueprint_t *bp,
                                                        uint32_t index);
uint32_t MapGenBlueprint_NumPortals(const mapgen_blueprint_t *bp);
const mapgen_blueprint_portal_t *MapGenBlueprint_Portal(const mapgen_blueprint_t *bp,
                                                        uint32_t index);
uint32_t MapGenBlueprint_NumRelations(const mapgen_blueprint_t *bp);
const mapgen_blueprint_relation_t *MapGenBlueprint_Relation(const mapgen_blueprint_t *bp,
                                                            uint32_t index);

/* The volume a point is in, or MAPGEN_BLUEPRINT_NO_VOLUME. */
#define MAPGEN_BLUEPRINT_NO_VOLUME UINT32_MAX
uint32_t MapGenBlueprint_VolumeAt(const mapgen_blueprint_t *bp,
                                  const int32_t point[3]);

/*
 * The canonical form, and its digest.
 *
 * Same map, same bytes, on any machine and in any locale: volumes are emitted
 * in id order and ids are assigned from a deterministic scan, so a blueprint
 * cannot depend on the order the stance graph happened to be built in.
 */
size_t   MapGenBlueprint_CanonicalText(const mapgen_blueprint_t *bp, char *out,
                                       size_t capacity);
uint64_t MapGenBlueprint_CanonicalDigest(const mapgen_blueprint_t *bp);
