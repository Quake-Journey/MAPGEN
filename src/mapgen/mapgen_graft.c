/*
 * MapGenGraft - see inc/common/mapgen_graft.h.
 *
 * One idea: before a room can be carried, every brush that seals it has to
 * have somewhere to go, and saying so is a different job from doing it.
 */

#include "common/mapgen_graft.h"

#include <math.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

const char *MapGenGraft_ResultName(mapgen_graft_result_t r)
{
    switch (r) {
    case MAPGEN_GRAFT_OK:            return "OK";
    case MAPGEN_GRAFT_ERR_ARGS:      return "ERR_ARGS";
    case MAPGEN_GRAFT_ERR_MEMORY:    return "ERR_MEMORY";
    case MAPGEN_GRAFT_ERR_NO_BUNDLE: return "ERR_NO_BUNDLE";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenGraft_DispositionName(mapgen_graft_disposition_t d)
{
    switch (d) {
    case MAPGEN_GRAFT_TRAVELS: return "TRAVELS";
    case MAPGEN_GRAFT_CUT:     return "CUT";
    case MAPGEN_GRAFT_STAYS:   return "STAYS";
    case MAPGEN_GRAFT_BLOCKED: return "BLOCKED";
    case MAPGEN_GRAFT_DISPOSITION_COUNT: break;
    }
    return "UNKNOWN";
}

const char *MapGenGraft_ReasonName(mapgen_graft_reason_t r)
{
    switch (r) {
    case MAPGEN_GRAFT_CLEAR:              return "CLEAR";
    case MAPGEN_GRAFT_BLOCKED_UNSEALED:   return "UNSEALED";
    case MAPGEN_GRAFT_BLOCKED_UNOWNED_SEAL: return "UNOWNED_SEAL";
    case MAPGEN_GRAFT_BLOCKED_NO_CUT:     return "NO_CUT";
    case MAPGEN_GRAFT_BLOCKED_MOVER:      return "MOVER";
    case MAPGEN_GRAFT_BLOCKED_MISSING:    return "MISSING";
    case MAPGEN_GRAFT_BLOCKED_OUTSIDE:    return "OUTSIDE";
    case MAPGEN_GRAFT_REASON_COUNT:       break;
    }
    return "UNKNOWN";
}

struct mapgen_graft_plan_s {
    uint32_t              room;
    uint32_t              num_brushes;
    mapgen_graft_brush_t *brushes;
    uint32_t              counts[MAPGEN_GRAFT_DISPOSITION_COUNT];
    mapgen_graft_reason_t why;
};

uint32_t MapGenGraft_Room(const mapgen_graft_plan_t *p)
{
    return p ? p->room : 0;
}

uint32_t MapGenGraft_NumBrushes(const mapgen_graft_plan_t *p)
{
    return p ? p->num_brushes : 0;
}

const mapgen_graft_brush_t *MapGenGraft_Brush(const mapgen_graft_plan_t *p,
                                              uint32_t i)
{
    return (p && i < p->num_brushes) ? &p->brushes[i] : NULL;
}

uint32_t MapGenGraft_Count(const mapgen_graft_plan_t *p,
                           mapgen_graft_disposition_t d)
{
    if (!p || (unsigned)d >= MAPGEN_GRAFT_DISPOSITION_COUNT)
        return 0;
    return p->counts[d];
}

bool MapGenGraft_Complete(const mapgen_graft_plan_t *p)
{
    return p && p->why == MAPGEN_GRAFT_CLEAR
        && p->counts[MAPGEN_GRAFT_BLOCKED] == 0;
}

mapgen_graft_reason_t MapGenGraft_Why(const mapgen_graft_plan_t *p)
{
    return p ? p->why : MAPGEN_GRAFT_BLOCKED_MISSING;
}

void MapGenGraft_Free(mapgen_graft_plan_t *plan)
{
    if (!plan)
        return;
    free(plan->brushes);
    free(plan);
}

/* ---- the cut ---------------------------------------------------------------- */

/*
 * Where to split a wall that two rooms both bound air on.
 *
 * Axial, through the wall's own middle, and declared - so a reader can check
 * the cut without running the operator, and so the same wall is cut in the
 * same place however often the plan is applied. Which axis comes from the way
 * out towards that neighbour where there is one, and from the wall's own
 * shape where there is not.
 *
 * A wall for which no single plane does it is reported as NO_CUT and the room
 * is refused. That is not a failure to try harder: it is a wall that winds
 * around a corner between the two rooms, splitting it needs more than one
 * plane, and the alternatives - deleting a wall the neighbour needs, or
 * carrying a second copy of it - are both the leak this module exists to
 * prevent.
 */

/* The plane through the middle of `brush` on `axis`, pointing whichever way
   `sign` says is into our room, on the eighth of a unit the writer spells
   plane points on so the cut survives being written and read back. */
static void cut_on(const mapgen_geometry_brush_t *brush, int axis, float sign,
                   float normal[3], float *dist)
{
    const float at = 0.5f * (brush->mins[axis] + brush->maxs[axis]);
    normal[0] = normal[1] = normal[2] = 0.0f;
    normal[axis] = sign;
    *dist = sign * ((float)((int32_t)(at * 8.0f + (at < 0.0f ? -0.5f : 0.5f)))
                    / 8.0f);
}

/*
 * The way out towards one neighbour tells us which way the wall between us
 * lies, and it does so LOCALLY - which is the whole reason to prefer it.
 *
 * A room's middle is a fact about the whole room, and a neighbour that wraps
 * around us has its middle on the same side of the wall we do. The socket is
 * where the two rooms actually meet, so the axis it points along is the axis
 * the wall separates on whatever shape either room is.
 */
static bool socket_axis(const mapgen_bundle_t *mine, uint32_t neighbour,
                        const mapgen_geometry_brush_t *brush,
                        int *axis, float *sign)
{
    const float centre[3] = {
        0.5f * (brush->mins[0] + brush->maxs[0]),
        0.5f * (brush->mins[1] + brush->maxs[1]),
        0.5f * (brush->mins[2] + brush->maxs[2]),
    };
    const mapgen_socket_t *best = NULL;
    float best_d2 = 0.0f;
    for (uint32_t i = 0; i < MapGenBundle_NumSockets(mine); i++) {
        const mapgen_socket_t *s = MapGenBundle_Socket(mine, i);
        if (!s || s->peer != neighbour)
            continue;
        float d2 = 0.0f;
        for (int a = 0; a < 3; a++) {
            const float d = s->at[a] - centre[a];
            d2 += d * d;
        }
        if (!best || d2 < best_d2) {
            best = s;
            best_d2 = d2;
        }
    }
    if (!best)
        return false;

    int dominant = 0;
    for (int a = 1; a < 3; a++)
        if (fabsf(best->normal[a]) > fabsf(best->normal[dominant]))
            dominant = a;
    if (fabsf(best->normal[dominant]) < 0.5f)
        return false;
    if (brush->maxs[dominant] - brush->mins[dominant] <= 0.0f)
        return false;

    *axis = dominant;
    /* The socket points OUT of our room, so into it is the other way. */
    *sign = best->normal[dominant] > 0.0f ? -1.0f : 1.0f;
    return true;
}

static bool separating_plane(const float *a_mins, const float *a_maxs,
                             const float *b_mins, const float *b_maxs,
                             const mapgen_geometry_brush_t *brush,
                             float normal[3], float *dist)
{
    /*
     * The two rooms' own middles, which is what the plane has to come between.
     *
     * NOT their bounding boxes: a bundle's box includes the wall it shares, so
     * two rooms either side of one wall overlap on every axis by the thickness
     * of that wall, and a rule looking for daylight between the boxes finds
     * none. MEASURED on q2dm1: all six movable rooms were refused for it.
     */
    float a_mid[3], b_mid[3];
    for (int i = 0; i < 3; i++) {
        a_mid[i] = 0.5f * (a_mins[i] + a_maxs[i]);
        b_mid[i] = 0.5f * (b_mins[i] + b_maxs[i]);
    }

    int best = -1;
    float best_thickness = 0.0f;
    float best_at = 0.0f;
    float best_sign = 1.0f;

    for (int axis = 0; axis < 3; axis++) {
        /* Halfway through the wall, on this axis. The plane passes through
           the brush by construction, so it always splits it. */
        const float at = 0.5f * (brush->mins[axis] + brush->maxs[axis]);
        const float thickness = brush->maxs[axis] - brush->mins[axis];
        if (thickness <= 0.0f)
            continue;
        /* And it has to come BETWEEN the rooms: ours on one side, theirs on
           the other, or it is not separating anything. */
        const float sign = a_mid[axis] < at ? -1.0f : 1.0f;
        if ((a_mid[axis] < at) == (b_mid[axis] < at))
            continue;
        /*
         * The thinnest axis of the wall, of those that separate.
         *
         * A wall between two rooms is thin along the axis that separates
         * them; cutting it across its thickness gives each room the face it
         * bounds air on and takes nothing from the other.
         */
        if (best < 0 || thickness < best_thickness) {
            best = axis;
            best_thickness = thickness;
            best_at = at;
            best_sign = sign;
        }
    }

    if (best < 0)
        return false;

    (void)best_at;
    cut_on(brush, best, best_sign, normal, dist);
    return true;
}

/*
 * One brush cannot be carried, and the plan remembers the FIRST reason.
 *
 * The plan's own reason and the brush's are recorded together, in one place,
 * because they went out of step when they were not: a room blocked by a mover
 * reported CLEAR as its reason while refusing, which is a refusal nobody can
 * diagnose.
 */
static void block(mapgen_graft_plan_t *plan, mapgen_graft_brush_t *e,
                  mapgen_graft_reason_t why)
{
    e->disposition = MAPGEN_GRAFT_BLOCKED;
    e->reason = why;
    plan->counts[MAPGEN_GRAFT_BLOCKED]++;
    if (plan->why == MAPGEN_GRAFT_CLEAR)
        plan->why = why;
}

/* ---- describing ------------------------------------------------------------- */

mapgen_graft_result_t MapGenGraft_Describe(const mapgen_bundle_set_t *set,
                                           const mapgen_geometry_t *geometry,
                                           uint32_t room,
                                           mapgen_graft_plan_t **out)
{
    if (!set || !geometry || !out)
        return MAPGEN_GRAFT_ERR_ARGS;
    *out = NULL;

    const mapgen_bundle_t *mine = MapGenBundleSet_At(set, room);
    if (!mine)
        return MAPGEN_GRAFT_ERR_NO_BUNDLE;

    mapgen_graft_plan_t *plan = calloc(1, sizeof(*plan));
    if (!plan)
        return MAPGEN_GRAFT_ERR_MEMORY;
    plan->room = room;
    plan->num_brushes = MapGenBundle_NumBrushes(mine);
    plan->brushes = calloc(plan->num_brushes ? plan->num_brushes : 1,
                           sizeof(*plan->brushes));
    if (!plan->brushes) {
        free(plan);
        return MAPGEN_GRAFT_ERR_MEMORY;
    }

    /*
     * Two properties of the whole bundle come first, because either of them
     * makes every brush's disposition moot.
     *
     * A bundle that is not SEALED has a hole nothing accounts for, and moving
     * it would take the hole along. A bundle that is sealed but not MOVABLE is
     * closed partly by solid the tree asserts and no brush provides - it can
     * be reshaped where it stands and it cannot be carried, and that is the
     * distinction MapGenBundle_Movable exists to make.
     */
    if (!MapGenBundle_Sealed(mine))
        plan->why = MAPGEN_GRAFT_BLOCKED_UNSEALED;
    else if (!MapGenBundle_Movable(mine))
        plan->why = MAPGEN_GRAFT_BLOCKED_UNOWNED_SEAL;

    /*
     * And the third: a mechanism whose geometry we cannot carry.
     *
     * The bundle's entity closure reaches BOTH ways along target and
     * targetname - a door in this room that a button outside it opens brings
     * the button, because half a mechanism is a map where the button does
     * nothing. When the thing it reaches is itself a brush model whose brushes
     * are not this bundle's, there is no half to carry: the entity would
     * arrive naming a submodel that did not come with it. MEASURED: this is
     * what q2dm1 room 5 did to the first transport, ERR_OWNERSHIP out of the
     * graft, and it is a property of the room rather than a bug in the move.
     */
    if (plan->why == MAPGEN_GRAFT_CLEAR) {
        const uint32_t all = MapGenGeometry_NumBrushes(geometry);
        for (uint32_t i = 0; i < MapGenBundle_NumEntities(mine)
                             && plan->why == MAPGEN_GRAFT_CLEAR; i++) {
            const mapgen_geometry_entity_t *ent =
                MapGenGeometry_Entity(geometry, MapGenBundle_Entity(mine, i));
            if (!ent)
                continue;
            /*
             * And an entity that is not in the room at all.
             *
             * Carrying it means putting it where the room went. An arriving
             * entity that landed outside q2dm1 is what made the first
             * transport compile to "**** leaked ****" - an entity outside the
             * sealed map IS a leak, and the compiler flooded straight out
             * from it. Two cells of slack, because the closure legitimately
             * reaches a light or a trigger sitting in the doorway.
             */
            if (ent->has_origin) {
                const float *air_lo = MapGenBundle_Mins(mine);
                const float *air_hi = MapGenBundle_Maxs(mine);
                for (int a = 0; a < 3; a++)
                    if (ent->origin[a] < air_lo[a] - MAPGEN_BUNDLE_CELL * 2.0f
                        || ent->origin[a] > air_hi[a]
                                            + MAPGEN_BUNDLE_CELL * 2.0f) {
                        plan->why = MAPGEN_GRAFT_BLOCKED_OUTSIDE;
                        break;
                    }
                if (plan->why != MAPGEN_GRAFT_CLEAR)
                    break;
            }
            if (!ent->model)
                continue;
            for (uint32_t b = 0; b < all; b++) {
                const mapgen_geometry_brush_t *gb =
                    MapGenGeometry_Brush(geometry, b);
                if (gb && gb->model == ent->model
                    && !MapGenBundle_OwnsBrush(mine, b)) {
                    plan->why = MAPGEN_GRAFT_BLOCKED_MOVER;
                    break;
                }
            }
        }
    }

    const uint32_t rooms = MapGenBundleSet_Count(set);
    const uint32_t num_brushes = MapGenGeometry_NumBrushes(geometry);

    for (uint32_t i = 0; i < plan->num_brushes; i++) {
        const mapgen_bundle_brush_t *bb = MapGenBundle_Brush(mine, i);
        mapgen_graft_brush_t *e = &plan->brushes[i];
        e->brush = bb ? bb->brush : 0;
        e->role = bb ? bb->role : MAPGEN_BUNDLE_ROLE_SUPPORT;
        e->shared_with = UINT32_MAX;

        if (plan->why != MAPGEN_GRAFT_CLEAR) {
            block(plan, e, plan->why);
            continue;
        }

        const mapgen_geometry_brush_t *gb =
            e->brush < num_brushes ? MapGenGeometry_Brush(geometry, e->brush)
                                   : NULL;
        if (!gb) {
            block(plan, e, MAPGEN_GRAFT_BLOCKED_MISSING);
            continue;
        }

        /*
         * A mover is a brush model, and a brush model is all or nothing: half
         * a door is not a door. It travels when the whole model is this
         * bundle's, and blocks the graft when the model reaches outside it.
         */
        if (e->role == MAPGEN_BUNDLE_ROLE_MOVER) {
            bool whole = true;
            for (uint32_t k = 0; k < num_brushes && whole; k++) {
                const mapgen_geometry_brush_t *other =
                    MapGenGeometry_Brush(geometry, k);
                if (!other || other->model != gb->model)
                    continue;
                whole = MapGenBundle_OwnsBrush(mine, k);
            }
            if (!whole) {
                block(plan, e, MAPGEN_GRAFT_BLOCKED_MOVER);
                continue;
            }
            e->disposition = MAPGEN_GRAFT_TRAVELS;
            plan->counts[MAPGEN_GRAFT_TRAVELS]++;
            continue;
        }

        /*
         * Does anybody else bound air on this brush?
         *
         * Only the BOUNDARY role counts as a claim on it. A brush that merely
         * holds up somebody else's floor is not a wall two rooms share, and
         * treating it as one would cut a pillar in half for no reason.
         */
        uint32_t neighbour = UINT32_MAX;
        for (uint32_t r = 0; r < rooms && neighbour == UINT32_MAX; r++) {
            if (r == room)
                continue;
            const mapgen_bundle_t *theirs = MapGenBundleSet_At(set, r);
            if (!theirs || !MapGenBundle_OwnsBrush(theirs, e->brush))
                continue;
            for (uint32_t k = 0; k < MapGenBundle_NumBrushes(theirs); k++) {
                const mapgen_bundle_brush_t *tb =
                    MapGenBundle_Brush(theirs, k);
                if (tb && tb->brush == e->brush
                    && tb->role == MAPGEN_BUNDLE_ROLE_BOUNDARY) {
                    neighbour = r;
                    break;
                }
            }
        }

        if (neighbour == UINT32_MAX) {
            /* Nobody else's. It goes as it is - boundary included, which is
               the whole point of this module. */
            e->disposition = MAPGEN_GRAFT_TRAVELS;
            plan->counts[MAPGEN_GRAFT_TRAVELS]++;
            continue;
        }

        if (e->role != MAPGEN_BUNDLE_ROLE_BOUNDARY) {
            /* Shared, and not part of OUR seal. The neighbour keeps it. */
            e->disposition = MAPGEN_GRAFT_STAYS;
            e->shared_with = neighbour;
            plan->counts[MAPGEN_GRAFT_STAYS]++;
            continue;
        }

        const mapgen_bundle_t *theirs = MapGenBundleSet_At(set, neighbour);
        int axis = 0;
        float sign = 1.0f;
        bool cut = socket_axis(mine, neighbour, gb, &axis, &sign);
        if (cut)
            cut_on(gb, axis, sign, e->cut_normal, &e->cut_dist);
        else if (theirs)
            cut = separating_plane(MapGenBundle_Mins(mine),
                                   MapGenBundle_Maxs(mine),
                                   MapGenBundle_Mins(theirs),
                                   MapGenBundle_Maxs(theirs),
                                   gb, e->cut_normal, &e->cut_dist);
        if (cut) {
            e->disposition = MAPGEN_GRAFT_CUT;
            e->shared_with = neighbour;
            plan->counts[MAPGEN_GRAFT_CUT]++;
            continue;
        }

        e->shared_with = neighbour;
        block(plan, e, MAPGEN_GRAFT_BLOCKED_NO_CUT);
    }

    *out = plan;
    return MAPGEN_GRAFT_OK;
}

/* ---- carrying it ------------------------------------------------------------- */

/*
 * The permitted rigid transform, and its inverse.
 *
 * The same one MapGenGeometry_TransformSubset applies - quarter turns about
 * the vertical, then an optional mirror in x, about a pivot, then an offset.
 * Written out here because the fit has to ask where a point of OUR map lands
 * in theirs, which is that transform run backwards.
 */
static void turn_xy(float v[3], uint32_t quarter_turns, bool mirror_x)
{
    for (uint32_t t = 0; t < quarter_turns; t++) {
        const float x = v[0], y = v[1];
        v[0] = -y;
        v[1] = x;
    }
    if (mirror_x)
        v[0] = -v[0];
}

static void unturn_xy(float v[3], uint32_t quarter_turns, bool mirror_x)
{
    /* Mirror is its own inverse and comes off first; then the turns come off
       by turning the rest of the way round. */
    if (mirror_x)
        v[0] = -v[0];
    for (uint32_t t = 0; t < (4u - quarter_turns) % 4u; t++) {
        const float x = v[0], y = v[1];
        v[0] = -y;
        v[1] = x;
    }
}

/* Where a point of the donor's map ends up in ours, and where a point of ours
   came from in theirs. */
static void forward(const mapgen_graft_fit_t *f, const float p[3], float out[3])
{
    float v[3];
    for (int a = 0; a < 3; a++)
        v[a] = p[a] - f->pivot[a];
    turn_xy(v, f->quarter_turns, f->mirror_x);
    for (int a = 0; a < 3; a++)
        out[a] = v[a] + f->pivot[a] + f->offset[a];
}

static void backward(const mapgen_graft_fit_t *f, const float p[3],
                     float out[3])
{
    float v[3];
    for (int a = 0; a < 3; a++)
        v[a] = p[a] - f->pivot[a] - f->offset[a];
    unturn_xy(v, f->quarter_turns, f->mirror_x);
    for (int a = 0; a < 3; a++)
        out[a] = v[a] + f->pivot[a];
}

/*
 * Is this point inside this brush?
 *
 * The same slack the bundle survey uses, and for the same reason: a plane
 * reconstructed from a compiled map is a plane to within a thirty-second of a
 * unit, and a test with no slack decides that the surface of a wall is not
 * the wall.
 */
static bool inside(const mapgen_geometry_t *g,
                   const mapgen_geometry_brush_t *brush, const float p[3])
{
    for (int a = 0; a < 3; a++)
        if (p[a] < brush->mins[a] - 1.0f || p[a] > brush->maxs[a] + 1.0f)
            return false;
    for (uint32_t s = 0; s < brush->num_sides; s++) {
        const mapgen_geometry_side_t *side =
            MapGenGeometry_Side(g, brush->first_side + s);
        if (!side || side->bevel)
            continue;
        const float d = side->normal[0] * p[0] + side->normal[1] * p[1]
                      + side->normal[2] * p[2] - side->dist;
        if (d > 0.03125f)
            return false;
    }
    return true;
}

/* ---- the receiving region ----------------------------------------------------- */

/*
 * A box, and why the whole operator turns on it being one.
 *
 * The two attempts before this both compiled to "**** leaked ****", and both
 * of them removed solid whose job was to seal the map and then tried to put
 * something equivalent back. Nothing equivalent is good enough: a seal is not
 * a quantity.
 *
 * So the replacement region is bounded, and NOTHING OUTSIDE IT IS TOUCHED.
 * Every brush that crosses the boundary is split on the region's own planes
 * and its outside part is kept exactly - not re-derived, not approximated, the
 * same brush with one more side. The map's seal lives outside the region and
 * therefore cannot be broken by anything that happens inside it. A leak is not
 * unlikely here; it is impossible, and that is a property of the construction
 * rather than a result to be checked afterwards.
 *
 * The region is the room's own air, grown by one cell so that it takes in the
 * inside face of the room's walls and stops there.
 */
static void region_of(const mapgen_bundle_t *b, float lo[3], float hi[3])
{
    const float *mins = MapGenBundle_Mins(b);
    const float *maxs = MapGenBundle_Maxs(b);
    const float cell = MAPGEN_BUNDLE_CELL;
    for (int a = 0; a < 3; a++) {
        /* The bundle states its air as cell CENTRES, so the air itself
           reaches half a cell further in each direction. */
        lo[a] = mins[a] - cell * 0.5f;
        hi[a] = maxs[a] + cell * 0.5f;
    }
}

/*
 * Is this piece of solid a WALL, or is it the world outside the map?
 *
 * Both read as solid, and the difference is the whole of the leak. Outside a
 * Quake map the tree says solid and there are no brushes, because there is
 * nothing there; a wall is solid a brush provides. A region that reached past
 * the map's outer shell would take that shell away and leave the room open to
 * the void - which is exactly what the first version of this did, and it
 * compiled to "**** leaked ****" on the first pair it tried.
 */
/*
 * Does this brush SEAL - is it a piece of the map's structural shell?
 *
 * Only the world model does: a submodel is a door or a lift, and the compiler
 * seals the map without it - a region bounded by a mover is a region that
 * opens when the mover moves. Only SOLID contents do: water, slime, lava,
 * fog, a player clip, a trigger and a window are all things the compiler's
 * outside-fill passes straight through. And detail never does: a detail brush
 * is left out of the structural tree, drawn and collided with, and the fill
 * goes through it - so solid that only a detail brush provides is, for the
 * purpose of not opening the map, the void with something standing in it.
 *
 * MEASURED, and it is the whole of the leak nobody could explain. Codex's
 * witness on the donor, reproduced here: at (114.4, 384, 276.8) the tree says
 * SOLID and PointContents is 33 - solid AND water - and the ONLY source brush
 * covering that point is brush 446, model 0, contents 32: water. The point is
 * on the outside slab of the recut region (118.4,128,236.8)..(490,512,339.2),
 * so the proof said "bounded by things the map is made of", the region was
 * emptied, and the compiler said "**** leaked ****". Three of the slab's
 * sample points are like it. The air flood added later could not see it
 * either: it skips cells the tree calls SOLID, and these are exactly that.
 */
static bool seals(const mapgen_geometry_brush_t *gb)
{
    return gb
        && gb->model == 0
        && (gb->contents & MAPGEN_CONTENTS_SOLID)
        && !(gb->contents & MAPGEN_CONTENTS_DETAIL);
}

/*
 * Is this piece of solid a WALL, or is it the world outside the map?
 *
 * `out_why` and `out_brush`, when given, come back describing the FIRST
 * covering brush that was not a seal - which is what a caller prints when it
 * refuses a region, so that the next reader is not left with "sound no".
 */
static bool real_solid_why(const mapgen_bsp_t *bsp, const mapgen_geometry_t *g,
                           const float p[3], const char **out_why,
                           uint32_t *out_brush)
{
    if (out_why)
        *out_why = "";
    if (out_brush)
        *out_brush = UINT32_MAX;
    if (!(MapGenBsp_PointContents(bsp, p) & MAPGEN_CONTENTS_SOLID))
        return true;   /* not solid at all: somewhere inside the map */

    bool covered_by_something = false;
    for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(g); b++) {
        const mapgen_geometry_brush_t *gb = MapGenGeometry_Brush(g, b);
        if (!gb)
            continue;
        /* The box first, and only then the planes. A brush is rejected by
           six comparisons instead of by intersecting every side of it, which
           is what makes asking this question of a whole region affordable:
           the recut operator asks it of thousands of points. */
        if (p[0] < gb->mins[0] || p[0] > gb->maxs[0]
            || p[1] < gb->mins[1] || p[1] > gb->maxs[1]
            || p[2] < gb->mins[2] || p[2] > gb->maxs[2])
            continue;
        if (!inside(g, gb, p))
            continue;
        if (seals(gb))
            return true;
        /* Covered, but by something that does not hold the map shut. Kept for
           the reason rather than returned at once: a wall behind the water
           still counts, and it may be the next brush in the array. */
        if (!covered_by_something) {
            covered_by_something = true;
            if (out_brush)
                *out_brush = b;
            if (out_why)
                *out_why = gb->model != 0
                    ? "filled void covered only by a brush model"
                    : (gb->contents & MAPGEN_CONTENTS_DETAIL)
                      ? "filled void covered only by a detail brush"
                      : "filled void covered only by a non-sealing brush";
        }
    }
    if (!covered_by_something && out_why)
        *out_why = "filled void with no brush at all";
    return false;
}

static bool real_solid(const mapgen_bsp_t *bsp, const mapgen_geometry_t *g,
                       const float p[3])
{
    return real_solid_why(bsp, g, p, NULL, NULL);
}

/*
 * The first sample that failed, kept for whoever refuses the region.
 *
 * One slot, written on the way out of the proof and read by its caller before
 * the next one runs - the same shape as the operators' decline register, and
 * for the same reason: the alternative is threading an out-parameter through
 * four nested sampling loops to carry something only a diagnostic reads.
 */
static mapgen_graft_refusal_t s_refusal;

const mapgen_graft_refusal_t *MapGenGraft_LastRefusal(void)
{
    return &s_refusal;
}

/* Record a failed sample and answer false, so a caller reads
   `if (!sealed_at(...)) return false;` and the witness is kept for it. */
static bool sealed_at(const mapgen_bsp_t *bsp, const mapgen_geometry_t *g,
                      const float p[3])
{
    const char *why = "";
    uint32_t brush = UINT32_MAX;
    if (real_solid_why(bsp, g, p, &why, &brush))
        return true;
    memcpy(s_refusal.point, p, sizeof(s_refusal.point));
    s_refusal.brush = brush;
    s_refusal.leaf_contents = MapGenBsp_PointContents(bsp, p);
    snprintf(s_refusal.why, sizeof(s_refusal.why), "%s", why);
    return false;
}

/*
 * Grow each face of the region as far as it can go and still have real solid
 * beyond it.
 *
 * Face by face rather than all together, because a room can be against the
 * map's outer shell on one side and have three more rooms' worth of rock on
 * another, and one number for all six would be the smallest of them.
 *
 * The layer just OUTSIDE the region is what has to be sound: everything there
 * is kept, and it is what the emptied region will be bounded by. Air there is
 * fine - it is another room, and a room is inside the map. Solid there is fine
 * when a brush provides it. Solid no brush provides is the void, and a face
 * that would reach it does not grow.
 */
static void grow_region(const mapgen_bsp_t *bsp, const mapgen_geometry_t *g,
                        float lo[3], float hi[3])
{
    const float cell = MAPGEN_BUNDLE_CELL;
    for (int axis = 0; axis < 3; axis++) {
      for (int side = 0; side < 2; side++) {
        for (int step = 0; step < 2; step++) {
            const float was = side ? hi[axis] : lo[axis];
            const float now = side ? was + cell : was - cell;
            /* Sample the layer just beyond where the face would be. */
            bool sound = true;
            const float at = side ? now + cell * 0.5f : now - cell * 0.5f;
            for (float u = lo[(axis + 1) % 3] - cell;
                 u <= hi[(axis + 1) % 3] + cell && sound; u += cell) {
              for (float v = lo[(axis + 2) % 3] - cell;
                   v <= hi[(axis + 2) % 3] + cell && sound; v += cell) {
                float p[3];
                p[axis] = at;
                p[(axis + 1) % 3] = u;
                p[(axis + 2) % 3] = v;
                sound = real_solid(bsp, g, p);
              }
            }
            if (!sound)
                break;
            if (side)
                hi[axis] = now;
            else
                lo[axis] = now;
        }
      }
    }
}

static bool in_region(const float lo[3], const float hi[3], const float p[3])
{
    for (int a = 0; a < 3; a++)
        if (p[a] < lo[a] || p[a] > hi[a])
            return false;
    return true;
}

/*
 * Do the ways out still lead anywhere?
 *
 * The only thing the region cannot guarantee. A socket is a place where air
 * crosses the region's boundary; after the swap the arriving room has to have
 * air there too, or a corridor that went somewhere now stops at a wall. That
 * is not a leak - it is a map a player cannot get around, which the
 * reachability gate would refuse a compile later and which is cheaper to see
 * here.
 */
static void ways_out(const mapgen_bundle_t *my_bundle, const float lo[3],
                     const float hi[3], const mapgen_geometry_t *donor,
                     const mapgen_graft_plan_t *theirs,
                     const mapgen_bundle_t *their_bundle,
                     mapgen_graft_fit_t *fit)
{
    fit->sockets_wanted = 0;
    fit->sockets_aligned = 0;
    float their_lo[3], their_hi[3];
    region_of(their_bundle, their_lo, their_hi);

    for (uint32_t i = 0; i < MapGenBundle_NumSockets(my_bundle); i++) {
        const mapgen_socket_t *s = MapGenBundle_Socket(my_bundle, i);
        if (!s)
            continue;
        fit->sockets_wanted++;

        /*
         * Just inside the region, at the socket, pointing back in. If the
         * arriving room has air there, the way out still leads somewhere.
         */
        float p[3];
        for (int a = 0; a < 3; a++)
            p[a] = s->at[a] - s->normal[a] * MAPGEN_BUNDLE_CELL;
        if (!in_region(lo, hi, p))
            continue;

        float q[3];
        backward(fit, p, q);
        /* Air in the donor is air inside their room's region that no brush of
           their bundle fills. */
        if (!in_region(their_lo, their_hi, q))
            continue;
        bool solid = false;
        for (uint32_t k = 0;
             k < MapGenGraft_NumBrushes(theirs) && !solid; k++) {
            const mapgen_graft_brush_t *e = MapGenGraft_Brush(theirs, k);
            const mapgen_geometry_brush_t *gb =
                MapGenGeometry_Brush(donor, e->brush);
            if (gb && inside(donor, gb, q))
                solid = true;
        }
        if (!solid)
            fit->sockets_aligned++;
    }
}

mapgen_graft_result_t MapGenGraft_Fit(const mapgen_bsp_t *recipient_bsp,
                                      const mapgen_geometry_t *recipient,
                                      const mapgen_graft_plan_t *mine,
                                      const mapgen_bundle_t *my_bundle,
                                      const mapgen_geometry_t *donor,
                                      const mapgen_graft_plan_t *theirs,
                                      const mapgen_bundle_t *their_bundle,
                                      mapgen_graft_fit_t *out)
{
    if (!recipient_bsp || !recipient || !mine || !my_bundle || !donor
        || !theirs || !their_bundle || !out)
        return MAPGEN_GRAFT_ERR_ARGS;
    memset(out, 0, sizeof(*out));
    if (!MapGenGraft_Complete(mine) || !MapGenGraft_Complete(theirs))
        return MAPGEN_GRAFT_ERR_NO_BUNDLE;

    float lo[3], hi[3], their_lo[3], their_hi[3];
    region_of(my_bundle, lo, hi);
    grow_region(recipient_bsp, recipient, lo, hi);
    region_of(their_bundle, their_lo, their_hi);
    for (int a = 0; a < 3; a++) {
        out->region_lo[a] = lo[a];
        out->region_hi[a] = hi[a];
    }
    /* And the region holds no void, boundary AND interior - see
       `region_is_sound`. Asked once, because the region does not depend on
       which way the arriving room is turned. */
    const bool sound = MapGenGraft_RegionIsSound(recipient_bsp, recipient,
                                                 lo, hi);

    mapgen_graft_fit_t best;
    memset(&best, 0, sizeof(best));
    bool have = false;

    for (uint32_t turns = 0; turns < 4; turns++) {
      for (int m = 0; m < 2; m++) {
        mapgen_graft_fit_t f;
        memset(&f, 0, sizeof(f));
        f.quarter_turns = turns;
        f.mirror_x = m != 0;
        for (int a = 0; a < 3; a++) {
            f.region_lo[a] = lo[a];
            f.region_hi[a] = hi[a];
            f.pivot[a] = 0.5f * (their_lo[a] + their_hi[a]);
            f.offset[a] = 0.5f * (lo[a] + hi[a]) - f.pivot[a];
        }

        /*
         * Does the arriving room fit in the space being cleared for it?
         *
         * Its own region, turned and moved, has to lie inside ours. A room
         * that pokes out would have its air cut off at the region planes, and
         * an arriving room with a wall through the middle of it is not the
         * room anybody selected.
         */
        f.fits = true;
        for (int c = 0; c < 8 && f.fits; c++) {
            const float corner[3] = {
                (c & 1) ? their_hi[0] : their_lo[0],
                (c & 2) ? their_hi[1] : their_lo[1],
                (c & 4) ? their_hi[2] : their_lo[2],
            };
            float there[3];
            forward(&f, corner, there);
            if (!in_region(lo, hi, there))
                f.fits = false;
        }

        /* And nothing it brings lands outside the region either. */
        f.brings_nothing_outside = true;
        for (uint32_t i = 0;
             i < MapGenBundle_NumEntities(their_bundle)
             && f.brings_nothing_outside; i++) {
            const mapgen_geometry_entity_t *ent =
                MapGenGeometry_Entity(donor,
                                      MapGenBundle_Entity(their_bundle, i));
            if (!ent || !ent->has_origin)
                continue;
            float there[3];
            forward(&f, ent->origin, there);
            if (!in_region(lo, hi, there))
                f.brings_nothing_outside = false;
        }

        ways_out(my_bundle, lo, hi, donor, theirs, their_bundle, &f);

        f.region_is_sound = sound;

        /* Fitting first, then the ways out: a room that lines its doors up
           and does not fit is not a candidate at all. */
        const bool usable = f.fits && f.brings_nothing_outside
                         && f.region_is_sound;
        const bool best_usable = best.fits && best.brings_nothing_outside
                              && best.region_is_sound;
        if (!have
            || (usable && !best_usable)
            || (usable == best_usable
                && f.sockets_aligned > best.sockets_aligned)) {
            best = f;
            have = true;
        }
      }
    }

    *out = best;
    return MAPGEN_GRAFT_OK;
}

/* ---- applying ---------------------------------------------------------------- */

/*
 * A cut is one more side.
 *
 * A convex solid intersected with a half-space is a convex solid, so splitting
 * a wall needs no clipping code: the piece that stays is the same brush with
 * one plane added to it. Exact, and it keeps every texture axis the brush
 * already had - which is why this operator can carry a boundary where filling
 * the difference between two shells on a lattice could not.
 */
static mapgen_graft_result_t add_clipped(mapgen_geometry_t *dst,
                                         const mapgen_geometry_t *src,
                                         uint32_t brush,
                                         const float normals[][3],
                                         const float *dists, uint32_t planes)
{
    const mapgen_geometry_brush_t *b = MapGenGeometry_Brush(src, brush);
    if (!b)
        return MAPGEN_GRAFT_ERR_ARGS;
    const uint32_t n = b->num_sides;
    mapgen_geometry_side_t *sides = calloc(n + planes + 1, sizeof(*sides));
    if (!sides)
        return MAPGEN_GRAFT_ERR_MEMORY;
    uint32_t out = 0;
    for (uint32_t s = 0; s < n; s++) {
        const mapgen_geometry_side_t *side =
            MapGenGeometry_Side(src, b->first_side + s);
        if (!side) {
            free(sides);
            return MAPGEN_GRAFT_ERR_ARGS;
        }
        sides[out++] = *side;
    }
    for (uint32_t p = 0; p < planes; p++) {
        /*
         * A plane the brush does not reach is not a cut.
         *
         * Adding it anyway makes a side coincident with one the brush already
         * has, which the compiler reports as a mirrored plane and which is a
         * face with no area for it to build. The brush's own bounds answer it
         * exactly for an axial plane, which is the only kind here.
         */
        float far = -1e30f, near = 1e30f;
        for (int c = 0; c < 8; c++) {
            const float corner[3] = {
                (c & 1) ? b->maxs[0] : b->mins[0],
                (c & 2) ? b->maxs[1] : b->mins[1],
                (c & 4) ? b->maxs[2] : b->mins[2],
            };
            const float d = normals[p][0] * corner[0] + normals[p][1] * corner[1]
                          + normals[p][2] * corner[2] - dists[p];
            if (d > far) far = d;
            if (d < near) near = d;
        }
        if (far <= 0.0f)
            continue;              /* wholly on the side that is kept */
        if (near >= 0.0f) {
            free(sides);
            return MAPGEN_GRAFT_OK;  /* wholly on the side that is cut away */
        }
        /*
         * The new face wears a material of the wall it is part of - one the
         * map DRAWS, not merely the first side in the list.
         *
         * It was `sides[0]`, on the reasoning that the face is inside solid
         * wherever the region does its job and a face nobody sees still has
         * to be spelled. Both halves were wrong. When the region is emptied
         * the face is the new wall of the space, and side zero of a brush the
         * compiler built has no texture about as often as not - which the
         * writer spells `e1u1/clip`, and the compiler draws.
         */
        uint32_t skin = 0;
        for (uint32_t k = 0; k < b->num_sides; k++) {
            const mapgen_geometry_side_t *cand =
                MapGenGeometry_Side(src, b->first_side + k);
            if (cand && !cand->bevel
                && MapGenGeometry_TextureIsMaterial(cand->texture)) {
                skin = k;
                break;
            }
        }
        sides[out] = sides[skin < out ? skin : 0];
        sides[out].bevel = false;
        sides[out].has_anchor = false;
        for (int a = 0; a < 3; a++)
            sides[out].normal[a] = normals[p][a];
        sides[out].dist = dists[p];
        /*
         * The skin's TEXTURE, never the skin's axes.
         *
         * A cut face points somewhere the wall it was cut from does not, and
         * the wall's S/T axes carried onto it are edge-on to it: one texel
         * column smeared across the face, which is what the PO photographed
         * on every map with a hollow in it. MEASURED on the donor with one
         * `--hollow 1504 1152 1048 1536 1258 1152`: five sides added, all
         * five with the wall's mapping, four of them drawn as streaks by the
         * compiler. The mapping comes from the new plane instead.
         */
        MapGenGeometry_AxesForNormal(sides[out].axis, sides[out].normal);
        out++;
    }
    mapgen_geometry_result_t rc =
        MapGenGeometry_AddBrush(dst, sides, out, b->contents, b->model);

    /*
     * And then again, without the planes that turned out not to be faces.
     *
     * Clipping a brush leaves some of its original sides entirely outside the
     * half-space that was kept. They are still planes of a convex solid and
     * the shape is right, but each of them is a side with no winding, and
     * MapGenGeometry_SurfaceFaults counts exactly that as a fault - "a face
     * cut away to nothing". MEASURED: all twenty-four carve attempts at
     * fidelity 90 were REJECTED_SURFACE for it, every one of them a brush
     * whose shape was perfectly sound.
     *
     * So the areas the add already computed are read back, and a brush that
     * came out carrying dead planes is replaced by the same brush without
     * them. A bevel is kept: a bevel is a plane that is meant to have no face.
     */
    if (rc == MAPGEN_GEOMETRY_OK) {
        const uint32_t at = MapGenGeometry_NumBrushes(dst) - 1;
        const mapgen_geometry_brush_t *added = MapGenGeometry_Brush(dst, at);
        uint32_t alive = 0;
        for (uint32_t s = 0; added && s < added->num_sides; s++) {
            const mapgen_geometry_side_t *side =
                MapGenGeometry_Side(dst, added->first_side + s);
            if (side && (side->bevel || side->area > 0.0f))
                sides[alive++] = *side;
        }
        if (added && alive >= 4 && alive < added->num_sides) {
            const int32_t contents = added->contents;
            const uint32_t model = added->model;
            if (MapGenGeometry_DropBrush(dst, at) == MAPGEN_GEOMETRY_OK)
                rc = MapGenGeometry_AddBrush(dst, sides, alive, contents,
                                             model);
        }
    }

    free(sides);
    /* An empty intersection is not a failure: it is a brush that turned out
       not to reach into this half-space at all, and there is nothing to add. */
    return (rc == MAPGEN_GEOMETRY_OK || rc == MAPGEN_GEOMETRY_ERR_DEGENERATE)
           ? MAPGEN_GRAFT_OK : MAPGEN_GRAFT_ERR_ARGS;
}

/* The region's six planes, oriented to KEEP the inside. */
static void region_planes(const float lo[3], const float hi[3],
                          float normals[6][3], float dists[6])
{
    for (int a = 0; a < 3; a++) {
        for (int k = 0; k < 3; k++) {
            normals[a * 2][k] = 0.0f;
            normals[a * 2 + 1][k] = 0.0f;
        }
        normals[a * 2][a] = 1.0f;
        dists[a * 2] = hi[a];
        normals[a * 2 + 1][a] = -1.0f;
        dists[a * 2 + 1] = -lo[a];
    }
}

/*
 * Empty a box, and touch nothing outside it.
 *
 * Every brush that crosses the boundary becomes up to six pieces, one per
 * face, each the same brush with that face's plane added the other way round.
 * They overlap where a brush wraps a corner of the box, which is allowed and
 * is not an approximation: their union is exactly the brush MINUS the box, and
 * the union is what the compiler sees.
 *
 * This is the whole of why a graft cannot leak, and it is the same reason a
 * carve cannot: the map's seal lives outside the box and nothing here can
 * reach it.
 */
static mapgen_graft_result_t hollow(mapgen_geometry_t *candidate,
                                    const float lo[3], const float hi[3],
                                    bool world_only)
{
    if (!candidate || !lo || !hi)
        return MAPGEN_GRAFT_ERR_ARGS;
    for (int a = 0; a < 3; a++)
        if (!(hi[a] > lo[a]))
            return MAPGEN_GRAFT_ERR_ARGS;

    float normals[6][3], dists[6];
    region_planes(lo, hi, normals, dists);

    const uint32_t before = MapGenGeometry_NumBrushes(candidate);
    uint32_t *going = malloc((before + 1) * sizeof(uint32_t));
    if (!going)
        return MAPGEN_GRAFT_ERR_MEMORY;
    uint32_t num_going = 0;

    for (uint32_t b = 0; b < before; b++) {
        const mapgen_geometry_brush_t *gb = MapGenGeometry_Brush(candidate, b);
        if (!gb)
            continue;
        /* A mechanism's own geometry, left where it is: see HollowWorld. */
        if (world_only && gb->model)
            continue;
        /*
         * And a brush the player can neither see nor touch is not this
         * operator's business either.
         *
         * A hint or a skip brush carries NO contents at all - q2dm1 has them
         * as `B 0 0 6`, six sides and nothing in them - because the compiler
         * uses them to decide where to split and nothing else. Clipping one
         * against the region leaves six pieces of invisible nothing behind,
         * and those pieces are not solid in the baseline, so everything
         * downstream reads them as things the edit BUILT: q2dm1 seed 3 came
         * back with a 424 by 1488 by 8 "construction" wearing
         * `e2u3/hint,e2u3/skip`, which is how this was found.
         *
         * Anything with contents is kept and clipped, clip brushes included -
         * an invisible wall left standing in an emptied room is a room a
         * player cannot walk into.
         */
        if (!gb->contents)
            continue;
        bool touches = true;
        for (int a = 0; a < 3 && touches; a++)
            if (gb->maxs[a] <= lo[a] || gb->mins[a] >= hi[a])
                touches = false;
        if (!touches)
            continue;

        going[num_going++] = b;
        /*
         * Six pieces, one per face of the box, each the brush clipped to the
         * OUTSIDE of that face. They overlap where a brush wraps a corner,
         * and their union is exactly the brush minus the box.
         *
         * The overlap is not free: two pieces that share a corner present
         * coplanar faces that cross, which MapGenGeometry_SurfaceFaults
         * counts as T-junctions - measured on q2dm1, one hollow adds between
         * nine and seventy of them, and that is what refuses a graft or a
         * recut as REJECTED_SURFACE.
         *
         * A DISJOINT partition - piece i being the brush outside face i and
         * inside every face before it - is the right answer to that and is
         * not what is here, because the first attempt at it compiled to
         * "**** leaked ****" on q2dm1: the pieces tile the remainder on
         * paper and something in the clipping does not deliver it. A map that
         * seals with some T-junctions in it beats a map with a hole, so this
         * stays until the partition can be shown to seal.
         */
        for (int p = 0; p < 6; p++) {
            /*
             * Piece p is the brush OUTSIDE face p and INSIDE every face
             * before it. Each point of the brush outside the box fails at
             * least one face and lands in the piece of the first face it
             * fails, so the pieces tile the remainder exactly once and share
             * only their boundaries. Overlapping pieces share FACES, and two
             * coplanar faces that cross are the T-junction that gets every
             * region edit refused.
             */
            float planes[6][3];
            float ds[6];
            for (int q = 0; q < p; q++) {
                for (int a = 0; a < 3; a++)
                    planes[q][a] = normals[q][a];
                ds[q] = dists[q];
            }
            for (int a = 0; a < 3; a++)
                planes[p][a] = -normals[p][a];
            ds[p] = -dists[p];
            if (add_clipped(candidate, candidate, b, planes, ds,
                            (uint32_t)(p + 1)) != MAPGEN_GRAFT_OK) {
                free(going);
                return MAPGEN_GRAFT_ERR_ARGS;
            }
        }
    }

    /* Highest index first: every drop moves what follows it down by one. */
    for (uint32_t i = 1; i < num_going; i++) {
        const uint32_t key = going[i];
        uint32_t j = i;
        while (j && going[j - 1] < key) {
            going[j] = going[j - 1];
            j--;
        }
        going[j] = key;
    }
    for (uint32_t i = 0; i < num_going; i++)
        if (MapGenGeometry_DropBrush(candidate, going[i])
            != MAPGEN_GEOMETRY_OK) {
            free(going);
            return MAPGEN_GRAFT_ERR_ARGS;
        }
    free(going);
    return MAPGEN_GRAFT_OK;
}

mapgen_graft_result_t MapGenGraft_Hollow(mapgen_geometry_t *candidate,
                                         const float lo[3], const float hi[3])
{
    return hollow(candidate, lo, hi, false);
}

mapgen_graft_result_t MapGenGraft_HollowWorld(mapgen_geometry_t *candidate,
                                              const float lo[3],
                                              const float hi[3])
{
    return hollow(candidate, lo, hi, true);
}

/* One face of a region, pushed out by one cell if the layer beyond it holds
   no void. The layer sampled overhangs the region by a cell on each side, so
   the corners a later face will inherit are checked here. */
static bool push_face(const mapgen_bsp_t *bsp, const mapgen_geometry_t *g,
                      float lo[3], float hi[3], int axis, int side)
{
    const float cell = MAPGEN_BUNDLE_CELL;
    const float was = side ? hi[axis] : lo[axis];
    const float now = side ? was + cell : was - cell;
    const float at = side ? now + cell * 0.5f : now - cell * 0.5f;
    /*
     * Half a cell in, so no sample ever lands exactly on a plane.
     *
     * A point on a brush's own face is inside it or outside it depending on
     * which way the arithmetic rounded, and a region growing along a room's
     * ceiling puts its corner samples on exactly that plane: the layer beyond
     * the far wall was sampled at the very top of the ceiling slab, came back
     * "not a brush", and the region stopped 288 units wide in a room 960
     * units across. Cell centres cannot land on a plane the map is built on.
     */
    for (float u = lo[(axis + 1) % 3] - cell * 0.5f;
         u <= hi[(axis + 1) % 3] + cell * 0.5f; u += cell) {
        for (float v = lo[(axis + 2) % 3] - cell * 0.5f;
             v <= hi[(axis + 2) % 3] + cell * 0.5f; v += cell) {
            float p[3];
            p[axis] = at;
            p[(axis + 1) % 3] = u;
            p[(axis + 2) % 3] = v;
            if (!sealed_at(bsp, g, p))
                return false;
        }
    }
    if (side)
        hi[axis] = now;
    else
        lo[axis] = now;
    return true;
}

bool MapGenGraft_GrowSoundRegion(const mapgen_bsp_t *bsp,
                                 const mapgen_geometry_t *g,
                                 const float around[3], uint32_t max_steps,
                                 float lo[3], float hi[3])
{
    if (!bsp || !g || !around || !lo || !hi)
        return false;
    const float cell = MAPGEN_BUNDLE_CELL;
    for (int a = 0; a < 3; a++) {
        lo[a] = around[a] - cell * 0.5f;
        hi[a] = around[a] + cell * 0.5f;
    }
    if (!MapGenGraft_RegionIsSound(bsp, g, lo, hi))
        return false;

    /* Round robin rather than one face at a time to exhaustion: a face grown
       to its limit first makes the region long before it is wide, and the
       layer a later face then has to clear is longer for it. */
    bool alive[3][2] = { { true, true }, { true, true }, { true, true } };
    for (uint32_t step = 0; step < max_steps; step++) {
        bool moved = false;
        for (int axis = 0; axis < 3; axis++)
            for (int side = 0; side < 2; side++) {
                if (!alive[axis][side])
                    continue;
                if (push_face(bsp, g, lo, hi, axis, side))
                    moved = true;
                else
                    alive[axis][side] = false;
            }
        if (!moved)
            break;
    }
    return true;
}

/*
 * Is this box safe to empty?
 *
 * Nothing outside it is touched, so the only question is what BOUNDS it. Air
 * beyond a face is somewhere else in the map and emptying up to it opens a way
 * through, which is a structural edit rather than a defect. Solid a brush
 * provides is a wall and stays a wall. Solid the tree asserts that no brush
 * provides is the world OUTSIDE the map, and emptying up to that is the leak -
 * the same distinction grow_region makes, for the same reason.
 */
bool MapGenGraft_RegionIsSound(const mapgen_bsp_t *bsp,
                               const mapgen_geometry_t *g,
                               const float lo[3], const float hi[3])
{
    if (!bsp || !g || !lo || !hi)
        return false;
    const float cell = MAPGEN_BUNDLE_CELL;
    /*
     * The layer is sampled at HALF a cell, and the reason is a leak.
     *
     * A thirty-two unit grid over a face 634 units across is twenty samples,
     * and q2dm1's walls are eight and sixteen units thick. A column of void
     * narrower than the grid slips between two samples: the region is
     * declared bounded by things the map is made of, it is emptied, and the
     * hole it opens is exactly the width of what nobody looked at. MEASURED:
     * the recut of region (-2,-285,224)..(610,349,372) passed at a
     * thirty-two unit layer and compiled to "**** leaked ****", with the
     * pointfile leaving through the region's own -x face.
     */
    const float layer = cell * 0.125f;
    for (int axis = 0; axis < 3; axis++) {
      for (int side = 0; side < 2; side++) {
        /*
         * A SLAB, not one plane.
         *
         * This used to sample a single sheet of points half a cell beyond the
         * face, and the sixteen units between the face and that sheet were
         * never looked at. A column of void in that gap is a hole the proof
         * cannot see: MEASURED on q2dm1, the recut of
         * (-2,-285,224)..(610,349,372) passed at every sampling density tried
         * - thirty-two, sixteen and four units across the sheet - and the
         * compiler's own pointfile then left the map through that region's -x
         * face at x = -2.24, which is one and three quarter units outside it
         * and fourteen short of where anybody had looked.
         *
         * The layer is two-dimensional, so covering its depth as well costs
         * four sheets instead of one and is still nothing next to the sweep
         * of the interior below.
         */
        for (float depth = layer; depth <= cell * 0.5f; depth += layer * 1.0f) {
            const float at = side ? hi[axis] + depth : lo[axis] - depth;
            for (float u = lo[(axis + 1) % 3] - cell;
                 u <= hi[(axis + 1) % 3] + cell; u += layer) {
              for (float v = lo[(axis + 2) % 3] - cell;
                   v <= hi[(axis + 2) % 3] + cell; v += layer) {
                float p[3];
                p[axis] = at;
                p[(axis + 1) % 3] = u;
                p[(axis + 2) % 3] = v;
                if (!sealed_at(bsp, g, p))
                    return false;
              }
            }
        }
      }
    }

    /*
     * And nothing INSIDE it may be the void either.
     *
     * The boundary proof above says the region is bounded by things the map
     * is made of. It says nothing about what is in the middle, and inside a
     * sealed Quake map the space between two rooms' shells is the world
     * OUTSIDE - the tree calls it solid and no brush provides it. A region
     * that contains air AND a piece of that gap joins them when it is
     * emptied, and the map is then open through its own middle.
     *
     * MEASURED on q2dm1: the largest recut this planner offers, region 612
     * units across, passed the boundary proof and compiled to
     * "**** leaked ****".
     *
     * Neither this nor the boundary proof can see AIR THAT IS NOT THE MAP'S:
     * both accept air, on the ground that air is another room and a room is
     * inside the map. A pocket sealed off from the map and bounded in part by
     * the void is not another room, and emptying a region that touches both
     * joins the map to it through a place where nothing was solid and nothing
     * was lost. That proof is written and is the caller's: `air_build` in
     * mapgen_geometry_edit.c floods the donor's empty space from its
     * deathmatch starts and `air_is_the_maps` refuses a region holding air
     * the flood never reached. The recut asks it for every region it offers.
     */
    /* Half a cell. Eight units was tried and refused nothing more on q2dm1,
       and it costs eight times the samples. */
    const float step = cell * 0.5f;
    for (float x = lo[0] + step * 0.5f; x <= hi[0]; x += step)
      for (float y = lo[1] + step * 0.5f; y <= hi[1]; y += step)
        for (float z = lo[2] + step * 0.5f; z <= hi[2]; z += step) {
            const float p[3] = { x, y, z };
            if (!sealed_at(bsp, g, p))
                return false;
        }
    return true;
}

mapgen_graft_result_t MapGenGraft_Apply(mapgen_geometry_t *candidate,
                                        const mapgen_graft_plan_t *mine,
                                        const mapgen_geometry_t *donor,
                                        const mapgen_graft_plan_t *theirs,
                                        const uint8_t *their_entities,
                                        uint32_t num_their_entities,
                                        const mapgen_graft_fit_t *fit)
{
    if (!candidate || !mine || !donor || !theirs || !fit)
        return MAPGEN_GRAFT_ERR_ARGS;
    if (!MapGenGraft_Complete(mine) || !MapGenGraft_Complete(theirs))
        return MAPGEN_GRAFT_ERR_NO_BUNDLE;
    /* A room that does not fit the space cleared for it would arrive with a
       wall through the middle of it. */
    if (!fit->fits || !fit->brings_nothing_outside
        || !fit->region_is_sound)
        return MAPGEN_GRAFT_ERR_NO_BUNDLE;

    float normals[6][3], dists[6];
    region_planes(fit->region_lo, fit->region_hi, normals, dists);

    const mapgen_graft_result_t emptied =
        MapGenGraft_Hollow(candidate, fit->region_lo, fit->region_hi);
    if (emptied != MAPGEN_GRAFT_OK)
        return emptied;

    /*
     * And theirs in, clipped to the same region.
     *
     * Grafted whole first - which is what carries the texture axes, the
     * entities and the angles through the turn - and then trimmed to the
     * region, because the trim is a plane in OUR coordinates and the brushes
     * are not in ours until they have arrived.
     */
    const uint32_t donor_brushes = MapGenGeometry_NumBrushes(donor);
    uint8_t *mask = calloc(donor_brushes ? donor_brushes : 1, 1);
    const uint32_t donor_entities = MapGenGeometry_NumEntities(donor);
    uint8_t *entities = donor_entities ? calloc(donor_entities, 1) : NULL;
    if (!mask || (donor_entities && !entities)) {
        free(mask);
        free(entities);
        return MAPGEN_GRAFT_ERR_MEMORY;
    }
    for (uint32_t i = 0; i < MapGenGraft_NumBrushes(theirs); i++) {
        const mapgen_graft_brush_t *e = MapGenGraft_Brush(theirs, i);
        if (e->disposition != MAPGEN_GRAFT_STAYS && e->brush < donor_brushes)
            mask[e->brush] = 1;
    }
    for (uint32_t i = 0; i < num_their_entities && their_entities; i++)
        if (their_entities[i] && i < donor_entities)
            entities[i] = 1;

    uint32_t first = 0, arrived = 0;
    const mapgen_geometry_result_t rc =
        MapGenGeometry_Graft(candidate, donor, mask, entities, fit->pivot,
                             fit->quarter_turns, fit->mirror_x, fit->offset,
                             &first, &arrived);
    free(mask);
    free(entities);
    if (rc != MAPGEN_GEOMETRY_OK)
        return MAPGEN_GRAFT_ERR_ARGS;

    /* Trim each arrival to the region: one convex piece, six planes added. */
    for (uint32_t i = 0; i < arrived; i++)
        if (add_clipped(candidate, candidate, first + i, normals, dists, 6)
            != MAPGEN_GRAFT_OK)
            return MAPGEN_GRAFT_ERR_ARGS;
    for (uint32_t i = arrived; i > 0; i--)
        if (MapGenGeometry_DropBrush(candidate, first + i - 1)
            != MAPGEN_GEOMETRY_OK)
            return MAPGEN_GRAFT_ERR_ARGS;

    return MAPGEN_GRAFT_OK;
}
