/*
 * MapGenGraft - what it would take to move this room, said before anything moves.
 *
 * Codex, 2026-09-06 section 5, point 1: "Describe the complete source bundle:
 * exact brushes/sides/render surfaces, boundary, shared-solid dependencies,
 * models/entities/targets, mover sweeps, anchors and typed sockets. Prove which
 * geometry is wholly owned, which must be split at a declared cut and which
 * cannot safely be extracted."
 *
 * The operator that exists today does none of that. It leaves the boundary
 * behind on BOTH sides - ours stays because it is what seals the map, theirs
 * does not come because it would arrive as a second shell inside ours - so
 * what changes hands is the furniture. That is why thirty-one of forty rooms
 * offered nothing: a room whose every brush is its own boundary has nothing
 * left once the boundary is excluded. Codex's ruling is that this is a
 * limitation of the operator and not the definition of GF7.
 *
 * The reason the boundary was excluded was not laziness. Two attempts at
 * carrying it both compiled to "**** leaked ****": once by grafting the whole
 * room, once by filling the difference between two shells on a lattice. What
 * was missing was not courage but a statement of who owns what. A wall between
 * two rooms belongs to both, and a brush cannot travel in two directions; the
 * answer is to CUT it on a declared plane, not to guess with an AABB and not
 * to leave the whole room's shell behind.
 *
 * So this module is the statement. It reads a bundle and answers, for every
 * brush the bundle owns:
 *
 *   TRAVELS   nothing else bounds its air on this brush; it goes as it is;
 *   CUT       another room bounds air on it too, and here is the exact plane
 *             that separates the two - the part on this room's side travels
 *             and the rest stays, so the neighbour's wall is never deleted;
 *   STAYS     it is in the closure but is not this room's to carry;
 *   BLOCKED   it cannot be extracted safely, and here is which of the five
 *             reasons it is.
 *
 * A plan is COMPLETE when nothing is BLOCKED. An operator may act on a
 * complete plan and may not act on any other - which makes the refusal a
 * property of the map that can be reported and diagnosed, rather than an
 * operator quietly doing less than it said.
 *
 * Nothing here modifies anything. It is the description Codex asked for, and
 * it is separated from the transport so that the description can be proved on
 * real donors before any geometry moves.
 */

#ifndef MAPGEN_GRAFT_H
#define MAPGEN_GRAFT_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_bundle.h"
#include "common/mapgen_geometry.h"

typedef enum {
    MAPGEN_GRAFT_OK = 0,
    MAPGEN_GRAFT_ERR_ARGS,
    MAPGEN_GRAFT_ERR_MEMORY,
    MAPGEN_GRAFT_ERR_NO_BUNDLE
} mapgen_graft_result_t;

const char *MapGenGraft_ResultName(mapgen_graft_result_t r);

typedef enum {
    MAPGEN_GRAFT_TRAVELS = 0,
    MAPGEN_GRAFT_CUT,
    MAPGEN_GRAFT_STAYS,
    MAPGEN_GRAFT_BLOCKED,
    MAPGEN_GRAFT_DISPOSITION_COUNT
} mapgen_graft_disposition_t;

const char *MapGenGraft_DispositionName(mapgen_graft_disposition_t d);

/*
 * Why a brush cannot be carried.
 *
 * Named rather than counted, because each is a different thing to do about it:
 * a shared wall with no separating plane is a map this operator cannot serve,
 * and a seal the bundle does not own is a room that was never movable in the
 * first place.
 */
typedef enum {
    MAPGEN_GRAFT_CLEAR = 0,
    MAPGEN_GRAFT_BLOCKED_UNSEALED,      /* the bundle has a hole in it       */
    MAPGEN_GRAFT_BLOCKED_UNOWNED_SEAL,  /* part of the seal is no brush      */
    MAPGEN_GRAFT_BLOCKED_NO_CUT,        /* shared, and no plane separates it */
    MAPGEN_GRAFT_BLOCKED_MOVER,         /* a brush model reaching outside    */
    MAPGEN_GRAFT_BLOCKED_MISSING,       /* the brush is not in the geometry  */
    /*
     * Something the room depends on is not in the room.
     *
     * The bundle's entity closure follows target and targetname BOTH ways, so
     * a door in this room brings the button outside it that opens it - half a
     * mechanism is a map where the button does nothing. Carrying that button
     * means putting it where the room went, which is somewhere it has no
     * business being: MEASURED, an arriving entity landed outside q2dm1
     * altogether and the compile came back "**** leaked ****", because an
     * entity outside the sealed map is exactly what a leak is.
     */
    MAPGEN_GRAFT_BLOCKED_OUTSIDE,
    MAPGEN_GRAFT_REASON_COUNT
} mapgen_graft_reason_t;

const char *MapGenGraft_ReasonName(mapgen_graft_reason_t r);

typedef struct {
    uint32_t                   brush;
    mapgen_bundle_role_t       role;
    mapgen_graft_disposition_t disposition;
    mapgen_graft_reason_t      reason;

    /*
     * For a CUT: the plane the brush is split on, pointing INTO this room.
     *
     * Declared rather than derived at transport time, so the same plan cuts
     * the same wall in the same place however often it is applied, and so a
     * reader can check the cut without running the operator.
     */
    float    cut_normal[3];
    float    cut_dist;
    /* The room on the other side of that plane - the one whose half stays. */
    uint32_t shared_with;
} mapgen_graft_brush_t;

typedef struct mapgen_graft_plan_s mapgen_graft_plan_t;

/*
 * Describe what moving one room would take.
 *
 * `set` and `geometry` must be the survey and the brushes of the SAME map;
 * they are two views of one thing and the description needs both - the survey
 * knows which room a piece of solid bounds, and the geometry knows where the
 * brush actually is.
 */
mapgen_graft_result_t MapGenGraft_Describe(const mapgen_bundle_set_t *set,
                                           const mapgen_geometry_t *geometry,
                                           uint32_t room,
                                           mapgen_graft_plan_t **out);

void MapGenGraft_Free(mapgen_graft_plan_t *plan);

uint32_t MapGenGraft_Room(const mapgen_graft_plan_t *p);
uint32_t MapGenGraft_NumBrushes(const mapgen_graft_plan_t *p);
const mapgen_graft_brush_t *MapGenGraft_Brush(const mapgen_graft_plan_t *p,
                                              uint32_t i);
uint32_t MapGenGraft_Count(const mapgen_graft_plan_t *p,
                           mapgen_graft_disposition_t d);

/*
 * Nothing is BLOCKED, so every brush of the seal has somewhere to go.
 *
 * The one question an operator is allowed to ask before acting. It is not
 * "mostly complete": a single wall nobody can cut is a wall that would be
 * deleted or duplicated, and both of those are the leak this exists to
 * prevent.
 */
bool MapGenGraft_Complete(const mapgen_graft_plan_t *p);

/* The first reason it is not, for a refusal that can be diagnosed instead of
   retried. CLEAR when it is complete. */
mapgen_graft_reason_t MapGenGraft_Why(const mapgen_graft_plan_t *p);

/* ---- carrying it -------------------------------------------------------- */

/*
 * How the arriving room is turned and where it lands, and whether the map
 * still closes when it does.
 *
 * Codex, section 5 points 2 and 3: a bounded receiving region, exact cut
 * planes, outside geometry preserved, and the bundle transported coherently
 * with the permitted rigid transform - quarter turns about the vertical and
 * an optional mirror, nothing else.
 *
 * The region is what makes this operator different from the two attempts that
 * compiled to "**** leaked ****". Both of them removed solid whose job was to
 * seal the map and then tried to put something equivalent back, and nothing
 * equivalent is good enough: a seal is not a quantity. Here the replacement is
 * bounded and nothing outside the bound is touched - a brush that crosses it
 * is split on the region's own planes and its outside part is kept as the same
 * brush with one more side. The map's seal lives outside the region, so a leak
 * is impossible by construction rather than unlikely by inspection.
 *
 * What the region cannot guarantee is that the ways out still lead anywhere,
 * so that is what `sockets_aligned` counts, and `fits` says whether the
 * arriving room lies inside the space being cleared for it. Both are necessary
 * conditions checked before a compile is spent; the compile, the reachability
 * gate and the hole oracle are what finally say the map is sound.
 */
typedef struct {
    uint32_t quarter_turns;
    bool     mirror_x;
    float    pivot[3];          /* the donor room's middle, in donor space  */
    float    offset[3];         /* from there to the recipient room's       */

    /* The bounded receiving region, in our coordinates. Nothing outside it
       is touched by the graft, which is what makes a leak impossible rather
       than unlikely. */
    float    region_lo[3];
    float    region_hi[3];

    bool     fits;              /* their room lies inside that region       */
    /*
     * And everything the arriving room brings with it lands inside it too.
     *
     * A bundle's entity closure follows target and targetname both ways, so it
     * can reach a switch three rooms away; carried, that switch lands wherever
     * the offset puts it. MEASURED: an ammo_rockets of q2dm3 room 17 arrived
     * at (-344 -160 208) in q2dm1, outside the map, and the compile flooded
     * straight out from it - "**** leaked ****" with the leak file naming that
     * entity. An entity outside the sealed map IS a leak.
     */
    bool     brings_nothing_outside;
    /*
     * And the region itself holds no VOID.
     *
     * `grow_region` stops a face that would reach the world outside the map,
     * and that is not the whole question: it says nothing about what is in the
     * MIDDLE of the box it started from. Inside a sealed Quake map the space
     * between two rooms' shells is the world outside, and a region that
     * contains air and a piece of that gap joins them the moment it is
     * emptied. The recut learned this on 2026-09-07 - its largest region
     * passed a boundary proof and compiled to "**** leaked ****" - and asks
     * `MapGenGraft_RegionIsSound`, which sweeps the interior as well as the
     * boundary. The graft did not, and carried the same hole.
     *
     * MEASURED on 2026-09-09: q2dm1's room 6 receiving q2dm3's room 5, region
     * 800 -160 896 .. 1312 160 1216, compiled to a leak whose pointfile left
     * through that region's own +y face at (892 158 896).
     */
    bool     region_is_sound;
    uint32_t sockets_aligned;   /* ways out that still lead somewhere       */
    uint32_t sockets_wanted;    /* ways out the room has                    */
} mapgen_graft_fit_t;

/*
 * Try all eight permitted orientations and keep the one that seals.
 *
 * Both plans must be COMPLETE - a room with a wall nobody can cut has no fit
 * to look for - and both must have been described from the geometry passed
 * here, because the dispositions are per-brush and a plan read against a
 * different map is a plan about different brushes.
 */
mapgen_graft_result_t MapGenGraft_Fit(const mapgen_bsp_t *recipient_bsp,
                                      const mapgen_geometry_t *recipient,
                                      const mapgen_graft_plan_t *mine,
                                      const mapgen_bundle_t *my_bundle,
                                      const mapgen_geometry_t *donor,
                                      const mapgen_graft_plan_t *theirs,
                                      const mapgen_bundle_t *their_bundle,
                                      mapgen_graft_fit_t *out);

/*
 * Carry it: our room out, theirs in, the shared walls cut rather than moved.
 *
 * Atomic in the sense the transaction needs - it either does all of it or
 * leaves `candidate` untouched - and it refuses a fit that does not seal
 * rather than producing a map for the compiler to find the hole in.
 */
mapgen_graft_result_t MapGenGraft_Apply(mapgen_geometry_t *candidate,
                                        const mapgen_graft_plan_t *mine,
                                        const mapgen_geometry_t *donor,
                                        const mapgen_graft_plan_t *theirs,
                                        const uint8_t *their_entities,
                                        uint32_t num_their_entities,
                                        const mapgen_graft_fit_t *fit);

/* ---- emptying a bounded box ---------------------------------------------- */

/*
 * The primitive underneath the graft, on its own, because a second operator
 * needs it.
 *
 * Emptying a BOX and touching nothing outside it is what makes the graft
 * unable to leak, and it is the answer to the thing the wall operators kept
 * refusing for: they will not move a wall into rock they cannot prove is
 * there, and a hundred and two of a hundred and twenty-three structural
 * candidates on q2dm1 are declined for exactly that. A box whose outside layer
 * is real solid IS that proof, and it is checkable.
 */
/*
 * Why the last region was refused, and where.
 *
 * A proof that answers only "sound no" cannot be acted on: the leak of
 * 2026-09-08 took a day to find because nothing recorded WHICH point of the
 * boundary failed or what covered it. Valid immediately after a
 * MapGenGraft_RegionIsSound that came back false; `point` is the first sample
 * that failed and `brush` the first non-sealing brush covering it, or
 * UINT32_MAX when nothing covered it at all.
 */
typedef struct {
    float    point[3];
    uint32_t brush;
    int32_t  leaf_contents;
    char     why[96];
} mapgen_graft_refusal_t;

const mapgen_graft_refusal_t *MapGenGraft_LastRefusal(void);

bool MapGenGraft_RegionIsSound(const mapgen_bsp_t *bsp,
                               const mapgen_geometry_t *g,
                               const float lo[3], const float hi[3]);

mapgen_graft_result_t MapGenGraft_Hollow(mapgen_geometry_t *candidate,
                                         const float lo[3], const float hi[3]);

/*
 * The same box emptied of the WORLD only, leaving the machines standing.
 *
 * A brush model is a door, a lift, a rotating thing: geometry an entity owns
 * and refers to by number. Clipping one is not emptying a region, it is
 * dismantling a mechanism and leaving the entity naming the pieces - so the
 * graft refuses a room that holds one at all (BLOCKED_MOVER) and never needs
 * this.
 *
 * An operator that RECUTS a room does need it: the point is to take out what
 * the room is built of and put something else there, and the lift in the
 * corner is not what the room is built of. It keeps its shaft's air, because
 * the air around it is what was emptied.
 */
mapgen_graft_result_t MapGenGraft_HollowWorld(mapgen_geometry_t *candidate,
                                              const float lo[3],
                                              const float hi[3]);

/*
 * The largest box around a point that can be emptied without opening the map.
 *
 * Grown one cell at a time, face by face, stopping each face where the layer
 * beyond it stops being real solid or real air. Face by face and not all
 * together, because a room can be against another room's shell on one side
 * and have a hall's worth of space on another.
 *
 * What stops a face is nearly always the same thing: the GAP between two
 * rooms' shells. Inside a sealed map that gap is the world outside - the tree
 * says solid and no brush provides it - so a region that reached into it and
 * was emptied would take the shell away and leave the map open. It is also
 * why growing a box outward from a room's bounding-box centre finds nothing
 * on q2dm1: the centre of the box around an L-shaped hall is in the rock
 * between two of its arms.
 *
 * `around` must be somewhere the map actually is - air a player could stand
 * in is the case this was written for. False when even one cell around it
 * cannot be emptied, which is the honest answer for a point in the void.
 */
bool MapGenGraft_GrowSoundRegion(const mapgen_bsp_t *bsp,
                                 const mapgen_geometry_t *g,
                                 const float around[3], uint32_t max_steps,
                                 float lo[3], float hi[3]);

#endif /* MAPGEN_GRAFT_H */
