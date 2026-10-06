/*
 * MapGenDivergence - how much of the donor's architecture a candidate changed.
 *
 * Contract 14.0.1. Every version of the specification before 2026-09-01 set a
 * maximum divergence and no minimum, so an untouched donor satisfied 90, 50 and
 * even 0 - which is the map the PO was handed three times running. The fault
 * was in the specification, and the fix is a TARGET:
 *
 *     target_divergence_permille = 10 * (100 - F)
 *
 * At fidelity 100 that is exactly zero. Below 100 it is not, so a candidate
 * that changed no architecture fails however faithful its texture axes are.
 *
 * --- measured on the compiled candidate, never counted from edits ----------
 *
 * A count of operators says what the generator TRIED. Two operators that undo
 * each other, an operator that landed on a wall nobody can see, and an operator
 * that ran twice on the same staircase all raise that count and change nothing.
 * So this reads two compiled BSPs and compares what is actually in them.
 *
 * --- what counts, and what deliberately does not --------------------------
 *
 * The unit is a thirty-two unit cell of the map that carries donor
 * architecture: solid, a visible surface, a floor, or a place a player goes.
 * The divergence is the fraction of those cells the candidate changed, counted
 * ONCE however many ways it changed them - that is what "deduplicated union"
 * means, and it is why an operator run twice on one staircase contributes what
 * one run of it does.
 *
 * A reskin, a relight and a texture swap contribute exactly zero, and not by a
 * rule that excludes them: material and lighting are not in any axis, so there
 * is nothing for them to move.
 *
 * Spawns and pickups contribute zero too, and that IS by a rule: TZ 14.0.1
 * gives "item and spawn swaps" no structural credit, and Codex ruled on
 * 2026-09-06 that the exclusion holds even where a room's use plainly changed.
 * The motif axis counted them until then, which meant emptying a room of its
 * items bought divergence without a plane moving - a near-copy passing the
 * target by the back door. A mover is not a pickup and still counts: a door is
 * architecture.
 */

#ifndef MAPGEN_DIVERGENCE_H
#define MAPGEN_DIVERGENCE_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_bsp.h"

/* The lattice. The same thirty-two units the reachability search calls one
   place and the demo corpus quantises onto, so the three can be talked about
   together. */
#define MAPGEN_DIVERGENCE_CELL   32.0f
#define MAPGEN_DIVERGENCE_MAX_CELLS 8388608u

/*
 * The schema of the numbers below.
 *
 * A divergence permille is only comparable to another one measured the same
 * way, and this instrument has been repaired twice in a week: the surface axis
 * stopped charging a whole cell for a corner sliver, and the motif axis
 * stopped broadcasting a room hash over every cell of its room. Both changed
 * every number the metric has ever printed. A receipt that records "42
 * permille" without recording WHICH instrument said so is not a receipt, so
 * every result carries this and every ledger writes it down.
 *
 * Bump it whenever what is measured changes. Never for a change that cannot
 * move a number.
 */
#define MAPGEN_DIVERGENCE_SCHEMA        3u
#define MAPGEN_DIVERGENCE_SCHEMA_ID     "14.0.1/3 exact-area-surfaces," \
                                        " construction-extent-motifs"

typedef enum {
    MAPGEN_DIVERGENCE_OK = 0,
    MAPGEN_DIVERGENCE_ERR_ARGS,
    MAPGEN_DIVERGENCE_ERR_MEMORY,
    MAPGEN_DIVERGENCE_ERR_TOO_LARGE,
    MAPGEN_DIVERGENCE_ERR_NO_DONOR_STRUCTURE
} mapgen_divergence_result_t;

const char *MapGenDivergence_ResultName(mapgen_divergence_result_t r);

typedef struct {
    /* The donor-bound cells each axis found, and how many of them changed.
       They overlap on purpose: a wall that moved changes its solid, its
       surface and the floor beside it, and the aggregate counts it once. */
    uint32_t solid_cells,    solid_changed;
    uint32_t surface_cells,  surface_changed;
    uint32_t vertical_cells, vertical_changed;
    uint32_t route_cells,    route_changed;
    uint32_t motif_cells,    motif_changed;

    uint32_t solid_permille;
    uint32_t surface_permille;
    uint32_t vertical_permille;
    uint32_t route_permille;
    uint32_t motif_permille;

    /* The deduplicated union over every axis that was measured. */
    uint32_t donor_cells;
    uint32_t changed_cells;
    uint32_t aggregate_permille;

    /*
     * Which axes actually ran.
     *
     * Routes cost a full reachability exploration of both maps and are asked
     * for. Motifs read the sealed bundles of both maps, which is the axis that
     * answers "is this the same architecture" - a room that grew by a tenth is
     * the same kind of room, and one that gained a way out is not.
     *
     * An axis that did not run is reported as NOT MEASURED and never as zero,
     * because zero is a claim.
     */
    bool     routes_measured;
    bool     motifs_measured;

    /*
     * And why an axis did not run, where the reason is that it ran out.
     *
     * A reachability search that hits its budget returns the states it opened,
     * which is a PREFIX of the map's routes. Marking those cells and calling
     * the axis measured is a resource failure wearing a result's clothes, and
     * the pipeline's final verdict used to rest on it. A face too large for
     * the surface rasteriser is the same thing on the other axis.
     *
     * Both leave their axis unmeasured and are reported here, so that a reader
     * is told the difference between "nothing changed" and "the measurement
     * stopped early".
     */
    bool     routes_truncated;
    uint32_t surfaces_skipped;

    uint32_t fidelity;
    uint32_t target_permille;
    bool     within_band;      /* within 50 permille of the target          */
    bool     complete;         /* every axis of 14.0.1 was measured         */
    uint32_t schema;           /* MAPGEN_DIVERGENCE_SCHEMA that produced it */
} mapgen_divergence_t;

/* What each cell of the lattice was found to be. The witness below reports
   them; the axes above count them. */
typedef enum {
    MAPGEN_DIVERGENCE_AXIS_SOLID    = 0x01u,
    MAPGEN_DIVERGENCE_AXIS_SURFACE  = 0x02u,
    MAPGEN_DIVERGENCE_AXIS_VERTICAL = 0x04u,
    MAPGEN_DIVERGENCE_AXIS_ROUTE    = 0x08u,
    MAPGEN_DIVERGENCE_AXIS_MOTIF    = 0x10u
} mapgen_divergence_axis_t;

/*
 * Every cell that differs, said out loud.
 *
 * A permille is a summary, and a summary cannot be argued with. Codex asked
 * on 2026-09-07 for "per-cell identities that explain each axis" - which cells
 * this instrument thinks changed, on which axis, and for the motif axis WHICH
 * construction identity stood there before and after. That is what makes a
 * disagreement about the metric checkable instead of a matter of opinion.
 *
 * `cell` is the lattice coordinate and `world` its centre in map units.
 */
typedef void (*mapgen_divergence_witness_fn)(
    void *user, const int32_t cell[3], const float world[3],
    uint32_t donor_axes, uint32_t candidate_axes,
    uint32_t donor_motif, uint32_t candidate_motif);

/*
 * Compare two compiled maps.
 *
 * `fidelity` is 0..100 and only sets the target the result is judged against;
 * it does not change what is measured. `measure_routes` runs the reachability
 * search over both maps, which is minutes rather than seconds.
 */
mapgen_divergence_result_t MapGenDivergence_Measure(
    const mapgen_bsp_t *donor, const mapgen_bsp_t *candidate,
    uint32_t fidelity, bool measure_routes, mapgen_divergence_t *out);

/* The same measurement, reporting each differing cell to `witness` as it is
   counted. The summary is identical; passing NULL is exactly Measure. */
mapgen_divergence_result_t MapGenDivergence_MeasureWitness(
    const mapgen_bsp_t *donor, const mapgen_bsp_t *candidate,
    uint32_t fidelity, bool measure_routes, mapgen_divergence_t *out,
    mapgen_divergence_witness_fn witness, void *user);

/*
 * The complete measurement, with the route axis marked from walks the caller
 * already has instead of two new walks of the two files (D19, assignment 23).
 *
 * Each walk must be a walk of that very file at the route axis's budget
 * (40000), and `*_whole` says it finished. A NULL walk leaves the axis
 * unmeasured and a walk that did not finish leaves it truncated - the same
 * answers a walk taken inside `MapGenDivergence_Measure` gives.
 */
struct mapgen_reach_s;
mapgen_divergence_result_t MapGenDivergence_MeasureWalked(
    const mapgen_bsp_t *donor, const struct mapgen_reach_s *donor_walk,
    bool donor_whole, const mapgen_bsp_t *candidate,
    const struct mapgen_reach_s *candidate_walk, bool candidate_whole,
    uint32_t fidelity, mapgen_divergence_t *out);

/* 10 * (100 - F), and nothing else is allowed to define it. */
uint32_t MapGenDivergence_Target(uint32_t fidelity);

#endif /* MAPGEN_DIVERGENCE_H */
