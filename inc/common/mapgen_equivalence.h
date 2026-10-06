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

MAPGEN-1 - is the baseline still the donor?

--- Why this exists -------------------------------------------------------

Divergence is measured between B, the donor's own geometry compiled by the
frozen toolchain with nothing applied, and C, the candidate. That is the right
reference: raw BSP bytes are not a semantic identity, and comparing a candidate
to the file id Software shipped in 1997 charges the generator for everything a
modern compiler normalizes.

But it buys the right reference at a price, and until now the price was not
paid. `MapGenTransaction_Begin` built B, loaded it, set the accepted divergence
to zero and never once asked whether B was still the donor. Every one of these
can compile without complaint and become an accepted zero baseline:

    a dropped brush; a moved solid/empty boundary; a lost liquid or hazard;
    a surface that stopped being drawn; a texture that slid; a brush model
    that became world; a door that lost its target; a trigger that vanished;
    an areaportal that closed; a spawn, item or light that disappeared;
    a route the player could walk that he now cannot.

An F100 of zero measured that way is zero by construction. It is circular
evidence: the pipeline is asked whether it agrees with itself.

So B is not usable until D and B are proved equivalent, by a comparison that
does NOT share a projection with the thing that produced B. The producer reads
the donor through `MapGenGeometry_FromBsp`, writes brushes and compiles them.
This oracle never touches that path. It reads both COMPILED artifacts through
`MapGenBsp`, samples space through the collision tree, measures drawn surfaces
off the face lump, reads movers through `MapGenMovers` and parses the entity
text itself. A defect in the geometry projection therefore shows up here as a
difference rather than being reproduced identically on both sides.

--- What is compared ------------------------------------------------------

    space          solid/empty/liquid/hazard on a lattice, with the
                   disagreements that sit ON a boundary separated from the
                   ones that sit in open space
    architecture   the canonical planes that carry drawn surfaces, and the
                   reconstructed convex volume of the brushwork by class
    surface        drawn area per (plane, material, flags, value), which is
                   invariant to how the compiler split or merged faces
    mapping        the texture axes, offsets and scales, weighted by area
    ownership      world versus brush model, model bounds, and which entity
                   binds which model - matched by binding, not by index
    entity         the normalized entity set: lights, items, spawns, targets,
                   movers, triggers, trains, path corners and areaportals
    mover          the compiled sweep - every stop of every machine, its
                   operators, teleporters, relays and push volumes
    traversal      the obligations: every spawn and pickup still stands where
                   a player can be, and the areas and areaportals agree

--- What the compiler is allowed to change --------------------------------

Listed, not inferred from a successful build. `MapGenEquivalence_AllowedDifference`
returns them one by one so a guard can assert the list rather than trust it.

==============================================================================
*/

#ifndef MAPGEN_EQUIVALENCE_H
#define MAPGEN_EQUIVALENCE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "common/mapgen_bsp.h"

typedef enum {
    MAPGEN_EQUIV_OK = 0,

    MAPGEN_EQUIV_ERR_ARGS,
    MAPGEN_EQUIV_ERR_MEMORY,
    MAPGEN_EQUIV_ERR_LIMIT,        /* more samples than the policy allows   */
    /* An entity string this cannot read exactly: a value that does not fit, a
       block that does not close, a key with no value, a duplicate key, or more
       pairs than a block may hold. Refused rather than approximated. */
    MAPGEN_EQUIV_ERR_ENTITIES,

    /* One axis per failure, because "the baseline is wrong" tells nobody
       where to look. */
    MAPGEN_EQUIV_DIFF_SPACE,
    MAPGEN_EQUIV_DIFF_ARCHITECTURE,
    MAPGEN_EQUIV_DIFF_SURFACE,
    MAPGEN_EQUIV_DIFF_MAPPING,
    MAPGEN_EQUIV_DIFF_OWNERSHIP,
    MAPGEN_EQUIV_DIFF_ENTITY,
    MAPGEN_EQUIV_DIFF_MOVER,
    MAPGEN_EQUIV_DIFF_TRAVERSAL,

    MAPGEN_EQUIV_RESULT_COUNT
} mapgen_equiv_result_t;

const char *MapGenEquivalence_ResultName(mapgen_equiv_result_t r);

enum {
    MAPGEN_EQUIV_SOLID = 0,
    MAPGEN_EQUIV_EMPTY,
    MAPGEN_EQUIV_LIQUID,
    MAPGEN_EQUIV_HAZARD,
    MAPGEN_EQUIV_CLASSES
};

const char *MapGenEquivalence_ClassName(int cls);

typedef struct {
    /* Sample spacing. Coarser than the smallest architecture on purpose: the
       boundary refinement below is what resolves detail, and a lattice fine
       enough to see a 1-unit sliver everywhere would cost more than the
       compile it guards. */
    float    lattice;
    /* The frozen compiler epsilon. A disagreement within this distance of a
       boundary in EITHER map is a boundary sample, not a lost room. */
    float    epsilon;
    float    plane_epsilon;    /* distance tolerance matching two planes    */
    float    normal_epsilon;   /* and their normals                         */
    float    centroid_epsilon; /* how far a material's drawn area may move   */
    float    facing_epsilon;   /* how far its mean facing may turn           */
    float    offset_epsilon;   /* how far its mean plane may move            */
    float    axis_epsilon;     /* how far a texture axis may slide           */
    /* A face group smaller than this is a sliver, not a wall: the compilers
       disagree about whether such a thing exists at all. */
    float    sliver_area;
    /* How much a wall's coverage may differ, in parts per thousand. Bigger
       than the area tolerance on purpose: coverage is measured on a raster,
       and the raster's error lives here. */
    float    coverage_permille;
    /* How near two planes must be to count as one wall's neighbourhood: the
       compiler may put a face on either, and on a curve they are a fraction
       of a degree apart. */
    float    neighbour_distance;
    float    neighbour_normal;
    /*
     * A surface the baseline draws and the donor does not is bounded, not
     * forbidden. Whether a face coincident with another brush's face survives
     * is decided by the compiler's CSG culling, and the donor's compiler is
     * not the frozen one - so the two disagree about a handful of small
     * faces. Losing a surface is never allowed; gaining one is allowed up to
     * this share of the total drawn area.
     */
    float    added_area_permille;
    float    area_permille;    /* drawn-area drift allowed per material     */
    float    volume_permille;  /* brushwork volume drift allowed per class  */
    float    bounds_epsilon;   /* model bounds and entity origins           */
    float    value_epsilon;    /* numeric entity values                     */
    /* Refuse rather than allocate past this. The lattice is widened until the
       count fits, and the effective spacing is reported. */
    uint32_t max_samples;
    bool     compare_traversal;
} mapgen_equiv_policy_t;

void MapGenEquivalence_DefaultPolicy(mapgen_equiv_policy_t *out);

#define MAPGEN_EQUIV_DETAIL   256
#define MAPGEN_EQUIV_NAME     64

/*
 * Both sides of every count, always.
 *
 * A report that said only "they differ" would make the reader open both files
 * to learn anything, so index 0 is the donor and index 1 is the baseline
 * throughout, and the facts are recorded whether or not the axis failed.
 */
/* One bit per axis, so a controlled RED can prove the axis it aimed at was
   the one that fired even when another axis fails as well. */
#define MAPGEN_EQUIV_AXIS_BIT(result_code)  (1u << ((result_code) \
                                                    - MAPGEN_EQUIV_DIFF_SPACE))

typedef struct {
    mapgen_equiv_result_t result;   /* the first axis that failed          */
    uint32_t failed_axes;           /* ... and every axis that did         */
    char     detail[MAPGEN_EQUIV_DETAIL];
    char     axis[MAPGEN_EQUIV_NAME];
    /* What each axis said, indexed by result code. Recorded whether or not
       the axis failed, so "this axis ran and was satisfied" is evidence a
       guard can assert rather than infer from silence. */
    mapgen_equiv_result_t axis_result[MAPGEN_EQUIV_RESULT_COUNT];
    char     axis_detail[MAPGEN_EQUIV_RESULT_COUNT][MAPGEN_EQUIV_DETAIL];

    /* space */
    float    lattice_used;
    uint32_t samples;
    uint32_t class_count[2][MAPGEN_EQUIV_CLASSES];
    uint32_t space_diff;          /* every disagreement                     */
    uint32_t space_diff_boundary; /* ... that sits on a boundary            */
    uint32_t space_diff_interior; /* ... and the ones that do not: the gate */
    uint32_t space_solid_riders;  /* row 400: solid in both, other bits differ - not compared */
    uint32_t sealed_faces[2];     /* row 400: faces facing what the OTHER map's compiler sealed - not compared */
    /* Where the samples came from. The lattice covers open volume; the leaf
       probes give the comparison the resolution the architecture has, so a
       wall thinner than the lattice is still looked at. */
    uint32_t lattice_samples;
    uint32_t leaf_samples;
    /* Samples in space no brush of either map describes - outside the sealed
       hull, where how far the marking reaches is the compiler's decision.
       Reported because excluding samples is the kind of thing that grows. */
    uint32_t space_outside;
    /* The content bits that differed, ORed over every interior disagreement,
       so a report says WHAT changed and not only that something did. */
    int32_t  first_diff_contents[2];
    /* The content bits that ever differed, ORed over the interior
       disagreements: a report that says WHAT changed, not only that
       something did. */
    int32_t  diff_bits_donor;
    int32_t  diff_bits_baseline;
    /* How far apart two disagreeing places are, at the widest: a boundary
       that moved a unit is a different finding from a brush that is not
       there. */
    float    diff_span;
    float    first_diff[3];
    int      first_diff_class[2];

    /* architecture */
    uint32_t surface_planes[2];
    uint32_t planes_missing;      /* in the donor, absent from the baseline */
    uint32_t planes_added;
    /* Summed per brush: a fact about how the space was DESCRIBED, and not
       invariant to redecomposition, so reported rather than gated. */
    double   brush_volume[2][MAPGEN_EQUIV_CLASSES];
    /* Summed over the tree's disjoint convex leaves: a fact about the SPACE,
       invariant to splitting, merging and the compiler's choice of split
       planes. This is what the architecture axis gates on. */
    double   leaf_volume[2][MAPGEN_EQUIV_CLASSES];
    double   worst_volume_permille;
    int      worst_volume_class;

    /* surface and mapping */
    uint32_t materials[2];
    double   drawn_area[2];
    double   worst_area_permille;
    char     worst_area_material[MAPGEN_BSP_TEXNAME + 1];
    uint32_t surface_mismatch;
    double   worst_centroid_shift;
    /* Material-on-plane presence, above the sliver floor. */
    /* Coverage: the union area of the faces on each wall, which is what a
       player sees. Summed area counts a face laid on another twice. */
    double   coverage[2];
    double   worst_coverage_permille;
    char     worst_coverage_material[MAPGEN_BSP_TEXNAME + 1];
    float    worst_coverage_plane[4];
    uint32_t coverage_mismatch;
    float    coverage_step;
    uint32_t drawn_groups[2];
    uint32_t groups_missing;
    uint32_t groups_added;
    double   groups_missing_area;
    double   groups_added_area;
    char     worst_group[MAPGEN_BSP_TEXNAME + 1];
    uint32_t mapping_mismatch;
    /* Walls carrying more distinct mappings than the comparison holds:
       refused, not approximated, and counted apart from a drift. */
    uint32_t mapping_overflow;
    double   worst_axis_shift;
    char     worst_mapping_material[MAPGEN_BSP_TEXNAME + 1];
    /* Where it happened: the plane the worst-mapped group sits on, so a
       reader can go and look at one wall instead of a whole material. */
    float    worst_mapping_plane[4];

    /* ownership */
    uint32_t models[2];
    uint32_t bindings[2];
    uint32_t bindings_unmatched;

    /* entities */
    uint32_t entities[2];
    uint32_t entities_missing;
    uint32_t entities_added;
    char     worst_entity[MAPGEN_EQUIV_NAME];

    /* movers */
    uint32_t movers[2];
    uint32_t operators[2];
    uint32_t portals[2];
    uint32_t relays[2];
    uint32_t pushes[2];
    uint32_t mover_stops_differ;

    /* traversal */
    uint32_t spawns[2];
    uint32_t pickups[2];
    uint32_t areas[2];
    uint32_t areaportal_leafs[2];
    /* Areas whose shape has no counterpart in the other map, matched by what
       they hold rather than by the number the compiler gave them. */
    uint32_t areas_unmatched;
    uint32_t obligations_broken;

    /* Scratch: what the axis being evaluated said. Not part of the verdict. */
    char     pending[MAPGEN_EQUIV_DETAIL];
} mapgen_equiv_report_t;

/*
 * Compare the donor with the baseline.
 *
 * Both must be COMPILED artifacts, already loaded. Returns MAPGEN_EQUIV_OK
 * when B may be used as the reference, and the axis that failed otherwise.
 * `out` is filled in either way: the facts are the point of the exercise, and
 * a caller that only wanted a boolean would have learned nothing from a run
 * that took a second.
 */
mapgen_equiv_result_t
MapGenEquivalence_Compare(const mapgen_bsp_t *donor,
                          const mapgen_bsp_t *baseline,
                          const mapgen_equiv_policy_t *policy,
                          mapgen_equiv_report_t *out);

/* What the compiler owns, and may therefore change without being wrong. */
uint32_t    MapGenEquivalence_NumAllowedDifferences(void);
const char *MapGenEquivalence_AllowedDifference(uint32_t i);

/*
 * The surface groups that did not match, worst area first.
 *
 * `side` is 0 for a group the donor draws and the baseline does not, 1 for the
 * reverse, and 2 for a group both draw with different area. Returns how many
 * were written. Valid only for the report of the most recent comparison.
 */
typedef struct {
    int      side;              /* 0 donor only, 1 baseline only, 2 both     */
    char     texture[MAPGEN_BSP_TEXNAME + 1];
    int32_t  flags, value;
    uint32_t model;
    /* Set for a presence difference, so the reader can go and look at the
       plane; zero for a whole-material difference. */
    float    normal[3];
    float    dist;
    double   donor_area;
    double   baseline_area;
    double   area_permille;
    double   centroid_shift;    /* units the drawn area's centre moved       */
    double   normal_shift;      /* how far the mean facing turned            */
    double   offset_shift;      /* units the mean plane moved                */
    double   axis_shift;        /* the worst texture axis component          */
} mapgen_equiv_surface_diff_t;

uint32_t MapGenEquivalence_SurfaceDiffs(mapgen_equiv_surface_diff_t *out,
                                        uint32_t max);

/*
 * The material-on-plane groups whose drawn area moved most, largest first.
 * Diagnostic only - nothing in the verdict rests on it, because matching one
 * plane to another inside a tolerance is unreliable where a curve is built
 * from many nearly parallel planes.
 */
uint32_t MapGenEquivalence_GroupDeltas(mapgen_equiv_surface_diff_t *out,
                                       uint32_t max);

/* The report as text, for the evidence a Project stores. Returns the length
   the full text would need, like snprintf. */
size_t MapGenEquivalence_ReportText(const mapgen_equiv_report_t *report,
                                    char *out, size_t capacity);

#endif /* MAPGEN_EQUIVALENCE_H */
