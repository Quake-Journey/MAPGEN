/*
 * MapGenTraversal - can a player who gets there get back?
 *
 * This exists because of one screenshot. A candidate shipped with a narrow
 * trench a player could drop into and never leave; the generator had checked
 * connectivity and found it fine, because it had asked the question of an
 * abstract portal graph where an edge is an edge. On the compiled map that
 * edge was a ledge too high to climb.
 *
 * So the question is asked here of the COMPILED map, with a real player hull
 * and the engine's own step, jump and fall behaviour, and it is asked in the
 * direction that matters. "Is this place reachable" is the wrong question: a
 * player can always reach the bottom of a pit. "Having reached it, is there a
 * way back to where everyone else is" is the right one, and it is the one a
 * directed graph answers and an undirected one cannot.
 *
 * Contract 18.3. Absolute at every fidelity, including 0 - a score of 66 does
 * not buy 34 per cent of a map you can get stuck in.
 */

#ifndef MAPGEN_TRAVERSAL_H
#define MAPGEN_TRAVERSAL_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_bsp.h"

typedef enum {
    MAPGEN_TRAVERSAL_OK = 0,
    MAPGEN_TRAVERSAL_ERR_ARGS,
    MAPGEN_TRAVERSAL_ERR_MEMORY,
    MAPGEN_TRAVERSAL_ERR_NO_SPACE,     /* the map has no standable space     */
    MAPGEN_TRAVERSAL_ERR_NO_SPAWNS     /* nowhere for a player to start      */
} mapgen_traversal_result_t;

const char *MapGenTraversal_ResultName(mapgen_traversal_result_t r);

typedef struct {
    uint32_t stances;             /* standable positions on the compiled map */
    uint32_t spawns;              /* player starts found in the entity lump  */
    uint32_t spawns_off_main;     /* starts outside the main component       */
    uint32_t main_component;      /* stances in the main component           */
    uint32_t reachable;           /* stances a player can get to from a start*/
    uint32_t trapped;             /* ... and cannot get back from            */
    uint32_t trapped_lethal;      /* of those, ones that kill - not a trap   */
    float    worst_trap[3];       /* where to look, when there is one        */
} mapgen_traversal_report_t;

/*
 * Run the gate over a compiled BSP.
 *
 * Returns OK when the report was produced; the report is what passes or fails,
 * and `trapped - trapped_lethal` above zero is a rejection, not a warning.
 */
mapgen_traversal_result_t MapGenTraversal_Check(const mapgen_bsp_t *bsp,
                                                mapgen_traversal_report_t *out);

/* Whether that report is a pass on its own terms: someone can start, and
   everyone who starts can reach everyone else. */
bool MapGenTraversal_Passed(const mapgen_traversal_report_t *report);

/*
 * The gate a CANDIDATE has to pass, which is a comparison and not a constant.
 *
 * The absolute form of contract 18.3 - every reachable stance has a way back -
 * cannot be applied to a stance graph that has no edges for doors, plats or
 * teleporters: retail q2dm1 itself reports 196 one-way stances and only a
 * third of its floor reachable from a spawn, because everything behind a door
 * is invisible to the graph. A threshold that rejects q2dm1 is a broken
 * threshold, not a strict one.
 *
 * So the donor is the baseline. A candidate may not strand more of its floor
 * than its donor does, and may not lose the reach its donor had. That catches
 * both defects the PO found - the map that fell into 22 reachable stances, and
 * the pocket with no way out - without pretending to an absolute answer the
 * graph cannot yet give. Closing that gap needs mover and teleporter edges and
 * is tracked as its own work.
 */
bool MapGenTraversal_NoWorseThan(const mapgen_traversal_report_t *donor,
                                 const mapgen_traversal_report_t *candidate,
                                 const char **out_reason);

#endif /* MAPGEN_TRAVERSAL_H */
