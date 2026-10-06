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

MAPGEN-1 - MapGenTopology: the shape of a map, before it has any geometry

Contract section 16, stages 3 to 5: a typed topology graph sized for the goal
and the player envelope, learned region motifs connected through compatible
sockets, and traversal routes of the kinds the corpus actually contained.

--- Sized from a learned map, not from a formula -----------------------------

The node count is DRAWN from the mixed model's samples and then adjusted by the
recipe's map scale. It is not computed from the player count by some curve of
mine: contract 19 allows the report to state measured evidence and nothing
more, and "this map has as many regions as one the corpus actually contained"
is measured, while "this map has 4 + players/2 regions" is an invention with a
learned-looking wrapper.

--- One table decides what may be emitted ------------------------------------

Every route kind names the learned role it requires and the recipe control that
gates it, in a single table. Contract 14's "None is absolute" and contract 15's
"never emit an unlearned motif" are then the same lookup, rather than two lists
that agree today and drift apart in six months. An route kind whose role the
selection never learned cannot be emitted at `High` either - the setting asks
for more of something, and there is no something.

--- Connected, or it is not a map -------------------------------------------

A graph a player cannot walk around is not a candidate, so connectivity is not
a fitness score to be traded off - it is built in and then checked. One-way
kinds (a drop, a teleporter with no return) are directed, and every
multiplayer goal additionally requires the DIRECTED graph to be strongly
connected: a route you can fall down but not climb back out of is a trap, not
a route.

==============================================================================
*/

#pragma once

#include "common/mapgen_mix.h"
#include "common/mapgen_recipe.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_TOPOLOGY_MIN_NODES   4u
#define MAPGEN_TOPOLOGY_MAX_NODES   256u
#define MAPGEN_TOPOLOGY_MAX_ROUTES   2048u
#define MAPGEN_TOPOLOGY_MAX_BANDS   8u

typedef enum {
    MAPGEN_ROUTE_WALK = 0,
    MAPGEN_ROUTE_RAMP,
    MAPGEN_ROUTE_JUMP,
    MAPGEN_ROUTE_DROP,
    MAPGEN_ROUTE_SWIM,
    MAPGEN_ROUTE_DOOR,
    MAPGEN_ROUTE_LIFT,
    MAPGEN_ROUTE_TRAIN,
    MAPGEN_ROUTE_TELEPORT,
    MAPGEN_ROUTE_PUSH,

    MAPGEN_ROUTE_KIND_COUNT
} mapgen_route_kind_t;

const char *MapGenTopology_RouteName(mapgen_route_kind_t kind);
/* The MAPGEN_ROLE_* bit an route kind needs the corpus to have learned, or 0
   for the kinds that are pure geometry and need no entity at all. */
uint32_t    MapGenTopology_RouteRole(mapgen_route_kind_t kind);
/* The recipe control that gates it, e.g. "arch_teleporters". */
const char *MapGenTopology_RouteControl(mapgen_route_kind_t kind);
/* Whether traversal is one-way. */
bool        MapGenTopology_RouteIsOneWay(mapgen_route_kind_t kind);
/*
 * Whether the kind MOVES the player rather than letting them move.
 *
 * PO rule, 2026-08-31: these are forbidden by default and emitted only when a
 * control explicitly asks for them. A jump pad in a corridor fires the player
 * into the ceiling - they cannot get past it and they die in it - and that is
 * not something a multiplayer map does by accident.
 */
bool        MapGenTopology_RouteMovesThePlayer(mapgen_route_kind_t kind);

typedef enum {
    MAPGEN_TOPOLOGY_OK = 0,
    MAPGEN_TOPOLOGY_ERR_ARGS,
    MAPGEN_TOPOLOGY_ERR_MEMORY,
    MAPGEN_TOPOLOGY_ERR_NO_SAMPLES,
    /* Contract 14: a control asked for something the corpus never contained. */
    MAPGEN_TOPOLOGY_ERR_UNLEARNED_MOTIF,
    MAPGEN_TOPOLOGY_ERR_TOO_MANY_NODES,
    MAPGEN_TOPOLOGY_ERR_TOO_MANY_ROUTES,
} mapgen_topology_result_t;

const char *MapGenTopology_ResultName(mapgen_topology_result_t r);

typedef struct {
    uint32_t band;              /* height band, 0 is the lowest              */
    uint32_t size_permille;     /* share of the map's area, learned          */
} mapgen_topology_node_t;

typedef struct {
    uint32_t from;
    uint32_t to;
    uint32_t kind;              /* mapgen_route_kind_t                        */
} mapgen_topology_route_t;

typedef struct mapgen_topology_s mapgen_topology_t;

/*
 * Build the graph. `attempt` is the candidate index, and it selects the seed
 * stream, so attempt N is the same graph however many attempts ran beside it.
 *
 * `conflict` receives the name of the control that could not be satisfied when
 * the result is ERR_UNLEARNED_MOTIF, because contract 14 requires preflight to
 * name the exact conflict rather than report that one exists.
 */
mapgen_topology_result_t MapGenTopology_Build(const mapgen_mix_t *model,
                                              const mapgen_recipe_t *recipe,
                                              uint32_t attempt,
                                              const char **conflict,
                                              mapgen_topology_t **out);
void MapGenTopology_Free(mapgen_topology_t *topology);

uint32_t MapGenTopology_NumNodes(const mapgen_topology_t *t);
uint32_t MapGenTopology_NumRoutes(const mapgen_topology_t *t);
const mapgen_topology_node_t *MapGenTopology_Node(const mapgen_topology_t *t,
                                                  uint32_t index);
const mapgen_topology_route_t *MapGenTopology_Route(const mapgen_topology_t *t,
                                                  uint32_t index);
/* Which learned map the size was drawn from, as 64 hex characters. */
const char *MapGenTopology_SampleSource(const mapgen_topology_t *t);
uint32_t MapGenTopology_NumRoutesOfKind(const mapgen_topology_t *t,
                                       mapgen_route_kind_t kind);
/* E - V + 1: how many independent loops the graph has. Contract 12 wants
   route redundancy for every multiplayer goal, and this is what that means. */
uint32_t MapGenTopology_CyclomaticNumber(const mapgen_topology_t *t);

size_t   MapGenTopology_CanonicalText(const mapgen_topology_t *t, char *out,
                                      size_t capacity);
uint64_t MapGenTopology_CanonicalDigest(const mapgen_topology_t *t);
