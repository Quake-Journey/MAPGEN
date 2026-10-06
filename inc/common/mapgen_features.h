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

MAPGEN-1 - MapGenFeatures: the deterministic per-map feature vector

Contract section 27's closing item for M2 ("deterministic per-map features"),
serving sections 7.1-7.4 (spatial, traversal, combat and item grammars) and
5.4's "line-of-sight, cover, chokepoint, loop, verticality and route
redundancy descriptors".

--- Every number is an integer -----------------------------------------------

Contract section 7 requires stable integer/fixed-point bins for learned
decisions, so there is not one float in this interface. Ratios are thousandths,
lengths are whole engine units. A feature that drifted in its last bits would
make two Training runs over the same map disagree for no reason.

--- Sampling is arithmetic, never random -------------------------------------

The visibility features sample pairs of stances, because testing all of them is
quadratic in a graph with 25 000 nodes. The sample is chosen by fixed strides
over the node array - no RNG, no seed, no clock - so the same map always yields
the same sample and therefore the same features. The counts that describe the
sample are reported alongside the ratios, so a reader can see what the number
is a ratio OF.

--- What is measured, exactly ------------------------------------------------

  chokepoints   articulation nodes of the undirected walk graph: stances whose
                removal splits their own region
  bridges       walk edges whose removal splits their region - a corridor with
                no alternative
  loops         the cyclomatic number E - V + C: independent cycles, which is
                what "route redundancy" means when it is made precise
  cover         the fraction of sampled stance pairs that CANNOT see each other
  verticality   distinct 64-unit height bands that contain a stance

==============================================================================
*/

#pragma once

#include "common/mapgen_space.h"
#include "common/mapgen_wiring.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* The engine's standing view height, `src/common/pmove/template.c:760`. A
   sight line drawn from anywhere else is not the line the player has. */
#define MAPGEN_FEATURES_VIEWHEIGHT   22

/* Bounds on the visibility sample. Both are part of the feature definition -
   changing either changes what the numbers mean, so they are in the header
   where that is visible rather than buried in the implementation. */
#define MAPGEN_FEATURES_MAX_OBSERVERS 512
#define MAPGEN_FEATURES_PARTNERS      32

/* An entity binds to a stance only if one is this close. Beyond that it is
   unbound, which is a fact about the map worth reporting rather than a
   nearest-node answer that means nothing. */
#define MAPGEN_FEATURES_BIND_RADIUS_XY 64
#define MAPGEN_FEATURES_BIND_RADIUS_Z  96

#define MAPGEN_FEATURES_HEIGHT_BAND   64

typedef enum {
    MAPGEN_FEATURES_OK = 0,
    MAPGEN_FEATURES_ERR_ARGS,
    MAPGEN_FEATURES_ERR_MEMORY,
} mapgen_features_result_t;

const char *MapGenFeatures_ResultName(mapgen_features_result_t r);

/*
 * The vector itself. Deliberately a plain struct of named integers rather than
 * an array: a feature that can only be read by index is a feature nobody can
 * check.
 */
/* How many distinct light colours are kept from one map. */
#define MAPGEN_FEATURES_LIGHT_COLOURS 4

typedef struct {
    /* --- spatial ------------------------------------------------------- */
    uint32_t nodes;
    uint32_t regions;
    uint32_t largest_region_nodes;
    uint32_t largest_region_permille;   /* of all stances                   */
    int32_t  extent[3];                 /* whole units                      */
    uint32_t median_clearance;
    /* The clearance probe is 512 units long, so a stance under open sky and
       one under a tall ceiling both report 512. On 67 of the 132 shipped maps
       the MEDIAN is exactly that, which makes the median uninterpretable on
       its own - so the share of stances at the cap is reported beside it.
       It is also the most direct measure of how open a map is. */
    uint32_t open_permille;
    uint32_t vertical_span;
    uint32_t height_bands;              /* 64-unit bands containing a stance */

    /* --- traversal ------------------------------------------------------ */
    uint32_t edges;
    uint32_t edges_of_kind[MAPGEN_EDGE_KIND_COUNT];
    uint32_t mean_walk_degree_milli;
    uint32_t chokepoints;
    uint32_t bridges;
    uint32_t loops;                     /* cyclomatic number E - V + C      */
    uint32_t bridge_permille;           /* of undirected walk edges         */

    /* --- combat --------------------------------------------------------- */
    uint32_t sight_pairs;               /* how many pairs were sampled      */
    uint32_t sight_open;                /* how many could see each other    */
    uint32_t cover_permille;            /* 1000 - 1000*open/pairs           */
    uint32_t mean_sight_length;         /* units, over the OPEN pairs       */
    uint32_t max_sight_length;

    /* --- hazards and liquid --------------------------------------------- */
    uint32_t liquid_nodes;
    uint32_t hazard_nodes;
    uint32_t hazard_permille;

    /* --- items and spawns ------------------------------------------------ */
    uint32_t positioned_entities;
    uint32_t bound_entities;
    uint32_t unbound_entities;
    uint32_t items_bound;
    uint32_t items_unbound;
    uint32_t spawns_bound;
    uint32_t spawns_unbound;
    uint32_t mean_item_separation;      /* nearest other item, whole units  */

    /*
     * Contract 7.7's lighting evidence.
     *
     * `lights` is how many light entities the map has; `light_median` is the
     * intensity they run at, the median of the `light`/`_light` keys with the
     * engine's own default of 300 standing in where the key is absent.
     *
     * A median rather than a mean because the corpus is full of outliers - one
     * map here ranges from -500 to 1200 - and one 1200 should not drag the
     * number a generator samples.
     */
    uint32_t lights;
    uint32_t light_median;
    /*
     * And the spread, as the lower and upper quartile.
     *
     * The median alone made every light in a generated map identical, which
     * is not what any map in the corpus does and is what drove the lightmap
     * into clipping at both ends. Quartiles rather than min and max for the
     * same reason the median is a median: one -500 or one 1200 outlier should
     * not become the range a generator samples from.
     */
    uint32_t light_lower;
    uint32_t light_upper;
    /*
     * The four commonest light colours, packed 0xRRGGBB, most common first,
     * and 0 where the map had fewer than four.
     *
     * Packed rather than stored as triples because these ride in the same flat
     * row of integers every other learned statistic does, and a colour is one
     * fact rather than three.
     */
    uint32_t light_colours[MAPGEN_FEATURES_LIGHT_COLOURS];
    /*
     * How much of the map's surface is open sky, in parts per thousand of all
     * textured brush sides.
     *
     * MEASURED: q2dm1 23, q2dm2 18, q2duel1 4, match1 1 - and every generated
     * map 0, which is the whole of "the references are open levels with sky
     * over your head and yours are closed boxes".
     */
    uint32_t sky_permille;
} mapgen_features_vector_t;

typedef struct mapgen_features_s mapgen_features_t;

/*
 * Compute the vector.
 *
 * `bsp` supplies the collision geometry for the sight lines, `space` the
 * stances and edges, `wiring` the entity roles and `genome` their positions.
 * All four are required: a feature vector built from part of the picture would
 * silently mean something else.
 */
mapgen_features_result_t MapGenFeatures_Build(const mapgen_bsp_t *bsp,
                                              const mapgen_genome_t *genome,
                                              const mapgen_space_t *space,
                                              const mapgen_wiring_t *wiring,
                                              mapgen_features_t **out);
void MapGenFeatures_Free(mapgen_features_t *f);

const mapgen_features_vector_t *MapGenFeatures_Vector(const mapgen_features_t *f);

/* Which stance an entity stands on, or UINT32_MAX when nothing is near
   enough. Indexed the same as the genome's entity list. */
uint32_t MapGenFeatures_EntityNode(const mapgen_features_t *f, uint32_t entity);

size_t   MapGenFeatures_CanonicalText(const mapgen_features_t *f, char *out, size_t capacity);
uint64_t MapGenFeatures_CanonicalDigest(const mapgen_features_t *f);
