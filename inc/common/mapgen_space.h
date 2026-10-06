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

MAPGEN-1 - MapGenSpace: standable space and the candidate traversal graph

Contract sections 5.4 (occupancy and segmentation, a typed traversal graph
with walk / step / jump / fall / swim edges) and 18.3 ("build a candidate nav
graph for speed, but final authority is a reentrant player-hull trace plus
shared pmove").

--- What this is, and what it is not ----------------------------------------

This is the CANDIDATE graph. Every node and every edge here is asserted by a
real player-hull trace through `MapGenTraceContext`, never by a static
adjacency, a PVS lookup or a leaf bounding box - the contract rules all three
out as proof. But a traced edge is still only a candidate: doors, lifts,
triggers, keys, mover timing and unavoidable death are invisible at this
layer, and the final proof is the bounded state graph of section 18.3 with
pmove as its authority.

So nothing here may ever be reported as "reachable". It answers a narrower
question - could a player hull stand here, and is there an unobstructed hull
path from here to there - and the validator built on it answers the rest.

--- The constants are the engine's ------------------------------------------

Every movement number below is read from the game, not chosen:

  step height 18          `src/common/pmove/template.c:19`  (STEPSIZE)
  hull        +-16, -24..32  `src/common/pmove/template.c:835-870`
  ducked maxs 4           `src/common/pmove/template.c:868`
  jump speed  270         `src/common/pmove/template.c:690`
  gravity     800         `src/game/g_main.c:132`  (sv_gravity default)
  ground when normal.z >= 0.7  `src/common/pmove/template.c` PM_CategorizePosition

A candidate graph built on invented constants would describe a game nobody is
playing.

==============================================================================
*/

#pragma once

#include "common/mapgen_bsp.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* --- the engine's movement constants ------------------------------------ */

#define MAPGEN_SPACE_STEPSIZE       18
#define MAPGEN_SPACE_HULL_WIDTH     16      /* +-x, +-y                      */
#define MAPGEN_SPACE_HULL_BOTTOM    (-24)
#define MAPGEN_SPACE_HULL_TOP       32
#define MAPGEN_SPACE_DUCK_TOP       4
#define MAPGEN_SPACE_JUMP_SPEED     270
#define MAPGEN_SPACE_GRAVITY        800

/* 270*270 / (2*800) = 45.5625, so 45 whole units of rise are reachable from a
   standing jump. Derived, not picked. */
#define MAPGEN_SPACE_JUMP_RISE      45

/* A surface flatter than this is not ground, exactly as PM_CategorizePosition
   decides it. Stored as thousandths so the header carries no float. */
#define MAPGEN_SPACE_GROUND_NORMAL_Z_MILLI  700

/* A fall is bounded, not because the player cannot fall further, but because
   beyond this a drop is a different question - survivability - that belongs to
   the validator with the health budget, not to a candidate edge. */
#define MAPGEN_SPACE_MAX_FALL       1024

/* --- limits, checked before anything is allocated ----------------------- */

#define MAPGEN_SPACE_MIN_CELL        16
#define MAPGEN_SPACE_MAX_CELL        256
#define MAPGEN_SPACE_MAX_COLUMNS     (1u << 20)
#define MAPGEN_SPACE_MAX_NODES       (1u << 21)
#define MAPGEN_SPACE_MAX_EDGES       (1u << 23)
#define MAPGEN_SPACE_MAX_FLOORS_PER_COLUMN  64

typedef enum {
    MAPGEN_SPACE_OK = 0,
    MAPGEN_SPACE_ERR_ARGS,
    MAPGEN_SPACE_ERR_NO_WORLD,
    MAPGEN_SPACE_ERR_CELL_SIZE,
    MAPGEN_SPACE_ERR_TOO_LARGE,
    MAPGEN_SPACE_ERR_MEMORY,
} mapgen_space_result_t;

const char *MapGenSpace_ResultName(mapgen_space_result_t r);

/* Edge kinds. Walk and step are symmetric and are the only ones that join a
   region; jump and fall are one-way by construction, and a swim edge is only
   emitted where at least one end is in a liquid. */
typedef enum {
    MAPGEN_EDGE_WALK = 0,
    MAPGEN_EDGE_STEP,
    MAPGEN_EDGE_JUMP,
    MAPGEN_EDGE_FALL,
    MAPGEN_EDGE_SWIM,
    MAPGEN_EDGE_KIND_COUNT,
} mapgen_edge_kind_t;

const char *MapGenSpace_EdgeKindName(mapgen_edge_kind_t k);

/* Node flags. */
#define MAPGEN_SPACE_NODE_LIQUID     0x0001  /* the stance is in a liquid     */
#define MAPGEN_SPACE_NODE_HAZARD     0x0002  /* it stands in lava or slime    */
#define MAPGEN_SPACE_NODE_DUCKED     0x0004  /* only a ducked hull fits       */

typedef struct {
    int32_t  cell[3];        /* quantized position on the shared basis      */
    float    origin[3];      /* where the hull actually rests               */
    uint32_t region;         /* connected component over walk/step edges    */
    int32_t  contents;       /* contents at the stance                      */
    uint16_t clearance;      /* free height above the stance, capped        */
    uint16_t flags;
} mapgen_space_node_t;

typedef struct {
    uint32_t from;
    uint32_t to;
    int32_t  rise;           /* signed height change, in units              */
    uint8_t  kind;
} mapgen_space_edge_t;

typedef struct {
    uint32_t nodes;
    int32_t  mins[3];
    int32_t  maxs[3];
    uint32_t liquid_nodes;
    uint32_t hazard_nodes;
    /* Nodes with two or fewer walk neighbours: a corridor is thin, a room is
       not. Reported as a count, so the caller decides the threshold. */
    uint32_t thin_nodes;
} mapgen_space_region_t;

typedef struct mapgen_space_s mapgen_space_t;

typedef struct {
    int32_t cell;            /* quantization, engine units; 0 = default 32  */
    bool    include_liquids; /* sample standable ground under water too     */
} mapgen_space_params_t;

mapgen_space_params_t MapGenSpace_DefaultParams(void);

/*
 * Build the candidate graph for a document's world model.
 *
 * Reentrant with respect to the document: two threads may build two spaces
 * from the same `bsp` at once, because everything mutable lives in the
 * returned object and in a trace context this call owns.
 */
mapgen_space_result_t MapGenSpace_Build(const mapgen_bsp_t *bsp,
                                        const mapgen_space_params_t *params,
                                        mapgen_space_t **out);
void MapGenSpace_Free(mapgen_space_t *space);

uint32_t MapGenSpace_NumNodes(const mapgen_space_t *space);
uint32_t MapGenSpace_NumEdges(const mapgen_space_t *space);
uint32_t MapGenSpace_NumRegions(const mapgen_space_t *space);
uint32_t MapGenSpace_NumEdgesOfKind(const mapgen_space_t *space, mapgen_edge_kind_t kind);
int32_t  MapGenSpace_CellSize(const mapgen_space_t *space);

const mapgen_space_node_t   *MapGenSpace_Node(const mapgen_space_t *space, uint32_t i);
const mapgen_space_edge_t   *MapGenSpace_Edge(const mapgen_space_t *space, uint32_t i);
const mapgen_space_region_t *MapGenSpace_Region(const mapgen_space_t *space, uint32_t i);

/* The largest region by node count, which is the playable body of almost every
   map. Returns UINT32_MAX when there are no regions at all. */
uint32_t MapGenSpace_LargestRegion(const mapgen_space_t *space);

/* Canonical rendering and its digest, on the same rules as the document and
   the genome: locale-free, order-independent, byte-stable. */
size_t   MapGenSpace_CanonicalText(const mapgen_space_t *space, char *buf, size_t size);
uint64_t MapGenSpace_CanonicalDigest(const mapgen_space_t *space);
