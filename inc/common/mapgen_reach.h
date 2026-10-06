/*
 * MapGenReach - where a player can actually get, and get back from.
 *
 * The question contract 18.3 asks is not "is this place reachable". A player
 * can always reach the bottom of a pit. It is "having reached it, is there a
 * way back to where everyone else is", and that is a question about a DIRECTED
 * graph over states a real player can occupy.
 *
 * So the states come from the engine's own movement: each one is a place a
 * simulated player came to rest, and each edge is a burst of input that was
 * actually run and actually arrived. Nothing here decides that a rise of
 * eighteen is a step or that a gap of ninety is a jump - the engine decides,
 * by moving.
 *
 * Movers are explicit rather than physical. A door or a lift is a state the
 * world can be in, and a route through one exists when the player can reach
 * the thing that operates it and the swept volume clears; that is a separate
 * layer over this one, and it is why an edge carries what it depended on.
 */

#ifndef MAPGEN_REACH_H
#define MAPGEN_REACH_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_certificate.h"

typedef enum {
    MAPGEN_REACH_OK = 0,
    MAPGEN_REACH_ERR_ARGS,
    MAPGEN_REACH_ERR_MEMORY,
    MAPGEN_REACH_ERR_NO_SPAWNS,
    MAPGEN_REACH_ERR_BOUND,
    MAPGEN_REACH_ERR_TOO_LARGE,
    /* Not a failure: the caller asked it to stop, and it did. A report from a
       cancelled walk describes part of a map and must not be read as though
       it described the map. */
    MAPGEN_REACH_CANCELLED
} mapgen_reach_result_t;

/*
 * Whether the caller still wants the answer.
 *
 * Asked before every state a worker simulates and before every level, from
 * every thread the walk is using at once, so `asked` must be safe to call
 * concurrently - reading one flag another thread sets is the intended shape.
 * A NULL token, or a NULL `asked`, means the walk runs to the end.
 */
typedef struct {
    bool (*asked)(void *user);
    void  *user;
} mapgen_reach_cancel_t;

const char *MapGenReach_ResultName(mapgen_reach_result_t r);

/*
 * Bounds, so an exploration of a hostile map cannot decide how long it runs or
 * how much it allocates.
 */
#define MAPGEN_REACH_MAX_STATES     262144u
#define MAPGEN_REACH_MAX_EDGES      2097152u
#define MAPGEN_REACH_MAX_SPAWNS     1024u
/* How far apart two resting places have to be to be different places. Below
   this they are the same spot reached by two routes, and merging them is what
   keeps the graph from growing without bound along a corridor. */
#define MAPGEN_REACH_CELL           32.0f

typedef struct {
    float    origin[3];
    bool     from_spawn;      /* a player starts here                        */
    bool     hazard;          /* standing here is lethal - a terminal state  */
    bool     liquid;
    /*
     * The verdict, per place, so a failure can be walked to rather than
     * counted. A caller that only learns "one thousand one hundred and
     * ninety-six" has to go looking; one that can print the first few with
     * their degrees can see in a line whether they are a real pocket in the
     * map or a place the exploration could not leave for reasons of its own.
     */
    bool     reachable;       /* a player can get here from a start          */
    bool     can_return;      /* ... and get back to one                     */
    uint32_t out_degree;      /* moves that leave here                       */
    uint32_t in_degree;       /* moves that arrive                           */
} mapgen_reach_state_t;

typedef struct mapgen_reach_s mapgen_reach_t;

typedef struct {
    uint32_t states;
    uint32_t edges;
    uint32_t spawns;
    uint32_t spawns_stranded;   /* a start that cannot reach the others      */
    uint32_t component;         /* states in the spawns' own component       */
    uint32_t reachable;         /* states a player can get to from a start   */
    uint32_t trapped;           /* ... and cannot get back from              */
    uint32_t trapped_lethal;    /* of those, the ones that kill              */
    float    worst_trap[3];
    uint32_t movers;            /* doors, lifts, trains and buttons           */
    uint32_t movers_open;       /* ... that a player can get open             */
    uint32_t movers_inoperable; /* ... that nothing in the map can ever fire  */
    uint32_t rounds;            /* explorations run: one per world that a
                                   button made different from the last        */
    /*
     * How wide the search actually got.
     *
     * `levels` is how many frontiers it worked through; `levels_wide` is how
     * many of those held at least eight states, which is the width at which a
     * level is handed to every core. So `levels_wide` is how many times the
     * parallel path was the one taken - and a fixture claiming to exercise it
     * can be required to prove so rather than argued about from its shape.
     *
     * Both describe the SEARCH and not the scheduling. A one-worker run and an
     * all-cores run must produce identical numbers here, exactly as they must
     * for every other field: the width of a level is a property of the map.
     */
    uint32_t levels;
    uint32_t levels_wide;
    uint32_t items;             /* weapons, armour, ammo and health           */
    uint32_t items_unreachable; /* ... that no player can pick up             */
    /*
     * Of the items, the ones ordinary locomotion cannot touch and an
     * authoritative special traversal can - each with a replayed witness
     * against THIS compiled map.
     *
     * Codex, 2026-09-02: reachability stays absolute and "reachable" means
     * through an accepted Quake II mechanism rather than through walking.
     * An item that is neither ordinarily reachable nor witnessed counts in
     * `items_unreachable` and fails the map.
     */
    uint32_t items_special;
    float    worst_item[3];

    /*
     * Landmarks: the places the map is built around.
     *
     * A room holding a player start, a pickup, or the deck of a machine that
     * carries one. Not an annotation - those are derived from the compiled map
     * the same way everything else here is, so the gate works on a donor
     * nobody has described.
     */
    uint32_t landmarks;
    uint32_t landmarks_unreachable;
    float    worst_landmark[3];

    /*
     * Row 331: places simulated, and places a later round took from an earlier
     * one's simulation of the same exact origin because no mover that changed
     * between the two could have touched it. Over all rounds.
     */
    uint32_t simulated;
    uint32_t reused;

    /*
     * Row 404 (Fable's brief 4 G5-6): the teleporters with a destination and the push volumes, and how many of each
     * a player who can get back to the starts steps into - Quake III layouts made for Quake II carry both (cor 16
     * misc_teleporter, 12 of them leading somewhere, and 4 pads; q3t2 6 and 3), and a map whose pads nobody reaches
     * is a different map.
     */
    uint32_t portals;
    uint32_t portals_crossed;
    uint32_t pushes;
    uint32_t pushes_crossed;
} mapgen_reach_report_t;

/*
 * Explore a compiled map with the engine's movement and report what a player
 * can do in it.
 *
 * `budget` bounds the work: the exploration stops opening new states once it
 * has that many, and says so by returning ERR_TOO_LARGE rather than by
 * quietly reporting a smaller map than there is.
 */
mapgen_reach_result_t MapGenReach_Explore(const mapgen_bsp_t *bsp,
                                          uint32_t budget,
                                          mapgen_reach_t **out);

typedef struct {
    /*
     * How many threads simulate a level at once.
     *
     * Zero means as many as there are performance-class logical CPUs. It is an
     * argument rather than a setting because a walk with a different worker
     * count must produce the same graph, and proving that needs two walks of
     * the same map in one process with different counts.
     */
    int                   workers;
    mapgen_reach_cancel_t cancel;
    /* TEST SEAM (row 331): every round simulates every place again, as before
       the reuse. The reuse guard's reference walk is the only caller. */
    bool                  no_round_reuse;
} mapgen_reach_options_t;

/*
 * The same walk, with a worker count and a cancellation token.
 *
 * `MapGenReach_Explore` is this with neither. Nothing else differs: the same
 * states, the same ids, the same edges and the same certificates come out
 * whatever the worker count, and out of a walk that was never asked to stop.
 */
mapgen_reach_result_t
MapGenReach_ExploreWith(const mapgen_bsp_t *bsp, uint32_t budget,
                        const mapgen_reach_options_t *options,
                        mapgen_reach_t **out);

/*
 * SHA-256 over the graph itself: every state in id order with its origin,
 * flags and degrees, then every edge in the order the walk recorded it.
 *
 * This is what "the same graph" means when two walks are compared. A count of
 * states would not be: two different maps can have the same number.
 */
void MapGenReach_GraphDigest(const mapgen_reach_t *reach,
                             char out[65]);

void MapGenReach_Free(mapgen_reach_t *reach);

const mapgen_reach_report_t *MapGenReach_Report(const mapgen_reach_t *reach);

/*
 * Why each pickup that ordinary movement missed is still reachable.
 *
 * One certificate per special traversal the search witnessed, in the order it
 * found them, with the geometry filled in and the identity left empty - the
 * search knows where things are and nothing about hashes. Whoever compiled the
 * candidate stamps them.
 *
 * `items_special` is how many there are; this is what they were.
 */
const mapgen_certificate_set_t *
MapGenReach_Certificates(const mapgen_reach_t *reach);

/*
 * The physics those certificates were written under, as a hash.
 *
 * The constants the special traversal is computed from, in a fixed order:
 * change one and every certificate written before the change stops matching,
 * which is what makes a stale certificate detectable rather than plausible.
 * Not the source text, which changes when a comment does, and not a version
 * number somebody has to remember to bump.
 */
void MapGenReach_PhysicsSha256(char out[65]);
uint32_t MapGenReach_NumStates(const mapgen_reach_t *reach);
const mapgen_reach_state_t *MapGenReach_State(const mapgen_reach_t *reach,
                                              uint32_t index);

/*
 * THE PRODUCT VERDICT. Every absolute condition, and none of them optional.
 *
 * Every player start shares one component; every place a player can get to
 * that will not kill him has a way back; every pickup can be walked onto;
 * every landmark is in the safe component; and nothing in the map is a machine
 * that nothing can operate.
 *
 * There is deliberately no way to ask for a subset. A gate a caller can forget
 * is a gate that gets forgotten, and the one thing this must never do is
 * return a publishable success for a map that failed a check nobody ran.
 */
bool MapGenReach_Passed(const mapgen_reach_report_t *report);

/* Row 400: the moves the walk found, one per edge (from state, to state), for a probe that walks a failure back. */
uint32_t MapGenReach_NumEdges(const mapgen_reach_t *reach);
bool MapGenReach_Edge(const mapgen_reach_t *reach, uint32_t index, uint32_t *from, uint32_t *to);

/*
 * WHICH absolute a report fails first, in the order the verdict above asks
 * them - the one function the verdict and a refusal's witness both read.
 *
 * The witness used to ask its own questions: «N places have no way back»
 * whenever `trapped` was not zero, while the verdict excuses a place that
 * kills. MEASURED on round 27 (ledger row 272): a stairs-to-lift was refused
 * «77 places have no way back (77 lethal)» on a map that passed with the same
 * 77, so the condition that did refuse it was never written down.
 *
 * The define exists only for the fixture's RED
 * (`tools/mapgen_reach_failure_test.c`), which counts a lethal place again.
 */
#ifndef MAPGEN_REACH_LETHAL_IS_NO_TRAP
#define MAPGEN_REACH_LETHAL_IS_NO_TRAP 1
#endif

typedef enum {
    MAPGEN_REACH_PASSES = 0,
    MAPGEN_REACH_FAILS_SPAWNS,      /* no start at all, or no report          */
    MAPGEN_REACH_FAILS_STRANDED,    /* a start cannot reach the others        */
    MAPGEN_REACH_FAILS_TRAPPED,     /* a place that does not kill, no way back */
    MAPGEN_REACH_FAILS_ITEMS,       /* a pickup nobody can reach              */
    MAPGEN_REACH_FAILS_LANDMARKS,   /* a landmark outside the safe component  */
    MAPGEN_REACH_FAILS_MOVERS       /* a machine nothing can operate          */
} mapgen_reach_failure_t;

static inline mapgen_reach_failure_t
MapGenReach_FirstFailure(const mapgen_reach_report_t *report)
{
    if (!report || report->spawns == 0)
        return MAPGEN_REACH_FAILS_SPAWNS;
    if (report->spawns_stranded)
        return MAPGEN_REACH_FAILS_STRANDED;
    if (MAPGEN_REACH_LETHAL_IS_NO_TRAP
            ? report->trapped != report->trapped_lethal
            : report->trapped != 0)
        return MAPGEN_REACH_FAILS_TRAPPED;
    if (report->items_unreachable)
        return MAPGEN_REACH_FAILS_ITEMS;
    if (report->landmarks_unreachable)
        return MAPGEN_REACH_FAILS_LANDMARKS;
    if (report->movers_inoperable)
        return MAPGEN_REACH_FAILS_MOVERS;
    return MAPGEN_REACH_PASSES;
}

/*
 * CONNECTIVITY ONLY, and NOT a product verdict.
 *
 * Named, so it cannot be mistaken for the one above. It asks whether players
 * can reach each other and get back, and nothing else - which is the question
 * to ask of a DONOR, because maps people play do not satisfy the rest: all
 * three of ours put a few pickups where ordinary movement cannot reach them,
 * q2dm1 having two on a pedestal a hundred and four units up, which is the
 * height a rocket jump gets you. Rocket jumping is a weapon and not movement.
 *
 * Anything this accepts is a survey result. It is not publishable and no
 * product path may use it.
 */
bool MapGenReach_ConnectivityOnly(const mapgen_reach_report_t *report);

/*
 * NO WORSE THAN THE DONOR (row 400, Fable's brief 4 G5-6).
 *
 * The five absolutes above hold on q2dm1, whose own walk passes them. A Quake III layout made for Quake II does
 * not: cor was compiled without the outside fill and the walk drops into the void past its kill curtains (2860
 * places «reached and not left»), and one of its starts stands on a ledge its straight-up pad cannot reach in Quake
 * II's air control. Every candidate of such a donor fails the absolutes for the donor's own reasons, so none was
 * ever accepted. The candidate is then held to the donor instead: no more stranded starts, no more places a player
 * is stuck in without dying (a fiftieth more, at least eight, for a walk that wanders the same void a few states
 * differently), no more pickups, landmarks or machines out of reach. Asked ONLY when the donor's own walk fails the
 * absolutes: on a donor that passes them they stay the rule, unchanged.
 */
bool MapGenReach_NoWorseThan(const mapgen_reach_report_t *report, const mapgen_reach_report_t *donor);
/* Row 405: the same, and the axis that decided with both numbers into `why` (one-way places as a share, +20
   permille of the donor's; the other axes counts). */
bool MapGenReach_NoWorseThanWhy(const mapgen_reach_report_t *report, const mapgen_reach_report_t *donor, char *why,
                                size_t cap);

/*
 * Row 409: the places of `map` a player reaches and cannot leave, not dying there, that the donor's walk has no such
 * place within `radius` of - NEW traps, by place and not by count. Held to the donor by count, mg_cor kept a pool
 * reached through a shot pane and left by nothing: 2760 such places against cor's own 2860 (its void past the kill
 * curtains). `first` gets the first one. Returns how many.
 */
uint32_t MapGenReach_NewTraps(const mapgen_reach_t *map, const mapgen_reach_t *donor, float radius, float first[3]);
#define MAPGEN_REACH_NEW_TRAP_RADIUS 64.0f
#define MAPGEN_REACH_NEW_TRAP_SLACK  8u     /* a walk that wanders the same pocket a few places differently */

/*
 * Is a PASSAGE a way, on the map as it was built?
 *
 * `boxes` is the passage itself, segment by segment (six floats each, the first
 * at its upper end and the last at its lower one) rather than one box round the
 * lot: the bounding box of a passage that bends holds rooms that are not in it,
 * and a walk through THOSE is not a walk through the passage.
 *
 * The walk starts at the state nearest `from` (a point on the upper floor) and
 * has to arrive at the state nearest `to` in this order and nothing else: the
 * upper end's neighbourhood (`radius` round it), the first segment, the
 * segments, the last segment, the lower end's neighbourhood. A passage closed
 * at either end fails, because the only way between its ends is then the long
 * way round and that leaves the neighbourhoods at once.
 *
 * `start`/`goal` are those two states, UINT32_MAX when nobody can stand within
 * 96 units of an end; `entered` says whether the walk got into the passage at
 * all, which is what tells a closed top from a closed bottom.
 */
typedef struct {
    uint32_t start;
    uint32_t goal;
    bool     entered;
    bool     through;
    /* where the walk first stood inside the box, and the place inside it that
       it got nearest the lower end from - what a refusal points at */
    float    entry[3];
    float    stuck[3];
    uint32_t box_states;       /* standing places inside the box              */
    uint32_t box_reached;      /* ... that the walk from the upper end got to  */
} mapgen_reach_way_t;

bool MapGenReach_WayThrough(const mapgen_reach_t *reach, const float from[3],
                            const float to[3], const float *boxes,
                            uint32_t num_boxes, float radius,
                            mapgen_reach_way_t *out);

#define MAPGEN_REACH_MAX_ITEMS 512u

#endif /* MAPGEN_REACH_H */
