/*
 * MapGenClosure - see inc/common/mapgen_closure.h.
 *
 * Two rules do the work, and both are about what the compiled map says rather
 * than what anybody meant by it.
 *
 * COPLANAR takes the rest of a surface the compiler cut up. It is bounded to
 * the SEED's own planes and to brushes that actually abut a member and carry
 * at least two of those planes - because a rule that grew its own plane list
 * is transitive, and a transitive rule over a map whose solid is one connected
 * mass returned 923 of q2dm1's 960 brushes.
 *
 * TOUCHING takes what is stuck to it: its clip, its trim, and what holds it
 * up. Bounded by the caller's depth, because the floor holds up the post and
 * the world holds up the floor.
 */

#include "common/mapgen_closure.h"

#include "common/mapgen_genome.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

const char *MapGenClosure_ResultName(mapgen_closure_result_t r)
{
    switch (r) {
    case MAPGEN_CLOSURE_OK:            return "OK";
    case MAPGEN_CLOSURE_ERR_ARGS:      return "ERR_ARGS";
    case MAPGEN_CLOSURE_ERR_MEMORY:    return "ERR_MEMORY";
    case MAPGEN_CLOSURE_ERR_NO_SEED:   return "ERR_NO_SEED";
    case MAPGEN_CLOSURE_ERR_TOO_LARGE: return "ERR_TOO_LARGE";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenClosure_ReasonName(mapgen_closure_reason_t reason)
{
    switch (reason) {
    case MAPGEN_CLOSURE_SEED:         return "seed";
    case MAPGEN_CLOSURE_COPLANAR:     return "coplanar";
    case MAPGEN_CLOSURE_TOUCHING:     return "touching";
    case MAPGEN_CLOSURE_MODEL:        return "model";
    case MAPGEN_CLOSURE_REASON_COUNT: break;
    }
    return "unknown";
}

/* How near two planes have to be to be the same plane. The compiler's own
   NORMAL_EPSILON is 0.00001 and its distance epsilon 0.01; these are one
   quantum looser, because a brush that was split and rebuilt is not bit-exact
   with the one it was split from. */
#define PLANE_NORMAL_EPSILON 0.001f
#define PLANE_DIST_EPSILON   0.05f

/* How far apart two brushes may be and still be touching. A quarter of a unit:
   the compiler's own snapping moves a plane by less than that, and a gap wider
   than it is a gap. */
#define TOUCH_EPSILON 0.25f

/* How far a piece attached to a member may stick out past it before it stops
   being a piece of it and becomes the map. One player width. */
#define ATTACHED_REACH 32.0f

struct mapgen_closure_s {
    uint32_t *brushes;
    uint8_t  *reason;        /* per donor brush, reason + 1, 0 for absent */
    uint32_t  num_brushes;
    uint32_t  num_donor_brushes;

    uint32_t *entities;
    uint8_t  *owned_entity;
    uint32_t  num_entities;

    float mins[3], maxs[3];
};

/* ---- membership ---------------------------------------------------------------- */

static void add(mapgen_closure_t *c, const mapgen_geometry_t *g,
                uint32_t brush, mapgen_closure_reason_t reason)
{
    if (brush >= MapGenGeometry_NumBrushes(g) || c->reason[brush]
        || c->num_brushes >= MAPGEN_CLOSURE_MAX_BRUSHES)
        return;
    c->reason[brush] = (uint8_t)(reason + 1);
    c->brushes[c->num_brushes++] = brush;

    const mapgen_geometry_brush_t *b = MapGenGeometry_Brush(g, brush);
    if (!b)
        return;
    for (int a = 0; a < 3; a++) {
        if (b->mins[a] < c->mins[a]) c->mins[a] = b->mins[a];
        if (b->maxs[a] > c->maxs[a]) c->maxs[a] = b->maxs[a];
    }
}

static bool same_plane(const mapgen_geometry_side_t *x,
                       const mapgen_geometry_side_t *y)
{
    for (int a = 0; a < 3; a++)
        if (fabsf(x->normal[a] - y->normal[a]) > PLANE_NORMAL_EPSILON)
            return false;
    return fabsf(x->dist - y->dist) <= PLANE_DIST_EPSILON;
}

static bool boxes_touch(const mapgen_geometry_brush_t *x,
                        const mapgen_geometry_brush_t *y, float slack)
{
    for (int a = 0; a < 3; a++)
        if (x->mins[a] > y->maxs[a] + slack || x->maxs[a] < y->mins[a] - slack)
            return false;
    return true;
}

/*
 * How many of these planes the candidate carries.
 *
 * One is not enough and that is the whole finding: every brush standing on the
 * floor of a room carries the floor's plane, so a rule that merged on one
 * plane merged the pillar with the wedge across the room from it. The three
 * pieces of a wall share its front, its back, its top and its bottom.
 */
static uint32_t planes_shared(const mapgen_geometry_t *g,
                              const mapgen_geometry_side_t *const *planes,
                              uint32_t num_planes,
                              const mapgen_geometry_brush_t *cand)
{
    uint32_t shared = 0;
    for (uint32_t i = 0; i < num_planes; i++)
        for (uint32_t j = 0; j < cand->num_sides; j++) {
            const mapgen_geometry_side_t *b =
                MapGenGeometry_Side(g, cand->first_side + j);
            if (b && !b->bevel && same_plane(planes[i], b)) {
                shared++;
                break;
            }
        }
    return shared;
}

/*
 * Do these two actually abut?
 *
 * One's face plane is the other's, facing the other way - which is what "they
 * meet here" means to a compiler. Bounding boxes are no help: two walls a
 * hundred units apart share the floor plane and overlap in two axes out of
 * three, and they are two walls.
 */
static bool contact(const mapgen_geometry_t *g,
                    const mapgen_geometry_brush_t *x,
                    const mapgen_geometry_brush_t *y,
                    float normal_out[3])
{
    if (!boxes_touch(x, y, TOUCH_EPSILON))
        return false;
    for (uint32_t i = 0; i < x->num_sides; i++) {
        const mapgen_geometry_side_t *a =
            MapGenGeometry_Side(g, x->first_side + i);
        if (!a || a->bevel)
            continue;
        for (uint32_t j = 0; j < y->num_sides; j++) {
            const mapgen_geometry_side_t *b =
                MapGenGeometry_Side(g, y->first_side + j);
            if (!b || b->bevel)
                continue;
            bool opposed = fabsf(a->dist + b->dist) <= PLANE_DIST_EPSILON;
            for (int k = 0; k < 3 && opposed; k++)
                if (fabsf(a->normal[k] + b->normal[k]) > PLANE_NORMAL_EPSILON)
                    opposed = false;
            if (opposed) {
                if (normal_out)
                    memcpy(normal_out, a->normal, sizeof(float) * 3);
                return true;
            }
        }
    }
    return false;
}

/*
 * Does one of these hold the other up?
 *
 * A vertical contact where one footprint sits inside the other's, which is
 * what holding up means when all you have is geometry. The post under a ledge
 * qualifies; the wall a pillar leans against does not, because that contact is
 * a wall's, standing on end.
 */
static bool supports(const mapgen_geometry_brush_t *x,
                     const mapgen_geometry_brush_t *y,
                     const float normal[3])
{
    if (fabsf(normal[2]) < 0.9f)
        return false;
    bool x_in_y = true, y_in_x = true;
    for (int a = 0; a < 2; a++) {
        if (x->mins[a] < y->mins[a] - TOUCH_EPSILON
            || x->maxs[a] > y->maxs[a] + TOUCH_EPSILON)
            x_in_y = false;
        if (y->mins[a] < x->mins[a] - TOUCH_EPSILON
            || y->maxs[a] > x->maxs[a] + TOUCH_EPSILON)
            y_in_x = false;
    }
    return x_in_y || y_in_x;
}

/* Something small stuck to a member: a step, a trim, the clip brush over a
   ledge. Bounded by how far it sticks out, because a wall that runs the length
   of the map also touches the member and is not part of it. */
static bool attached_to(const mapgen_geometry_brush_t *member,
                        const mapgen_geometry_brush_t *cand)
{
    if (!boxes_touch(member, cand, TOUCH_EPSILON))
        return false;
    for (int a = 0; a < 3; a++)
        if (cand->mins[a] < member->mins[a] - ATTACHED_REACH
            || cand->maxs[a] > member->maxs[a] + ATTACHED_REACH)
            return false;
    return true;
}

static bool invisible(const mapgen_geometry_t *g,
                      const mapgen_geometry_brush_t *b)
{
    for (uint32_t s = 0; s < b->num_sides; s++) {
        const mapgen_geometry_side_t *side =
            MapGenGeometry_Side(g, b->first_side + s);
        if (!side || side->bevel)
            continue;
        if (!(side->flags & (MAPGEN_SURF_NODRAW | MAPGEN_SURF_HINT
                             | MAPGEN_SURF_SKIP)))
            return false;
    }
    return true;
}

/* ---- entities ------------------------------------------------------------------ */

static void own_entity(mapgen_closure_t *c, uint32_t entity)
{
    if (c->owned_entity[entity]
        || c->num_entities >= MAPGEN_CLOSURE_MAX_ENTITIES)
        return;
    c->owned_entity[entity] = 1;
    c->entities[c->num_entities++] = entity;
}

static bool named(const char *a, const char *b)
{
    return a && b && *a && !strcmp(a, b);
}

static void close_over_targets(mapgen_closure_t *c, const mapgen_geometry_t *g)
{
    const uint32_t n = MapGenGeometry_NumEntities(g);
    bool grew = true;
    while (grew) {
        grew = false;
        for (uint32_t owned = 0; owned < c->num_entities; owned++) {
            const uint32_t e = c->entities[owned];
            const char *target = MapGenGeometry_EntityValue(g, e, "target");
            const char *kill = MapGenGeometry_EntityValue(g, e, "killtarget");
            const char *name = MapGenGeometry_EntityValue(g, e, "targetname");
            for (uint32_t other = 0; other < n; other++) {
                if (c->owned_entity[other])
                    continue;
                const char *on = MapGenGeometry_EntityValue(g, other,
                                                            "targetname");
                const char *ot = MapGenGeometry_EntityValue(g, other, "target");
                const char *ok = MapGenGeometry_EntityValue(g, other,
                                                            "killtarget");
                if (named(target, on) || named(kill, on) || named(ot, name)
                    || named(ok, name)) {
                    own_entity(c, other);
                    grew = true;
                }
            }
        }
    }
}

/* ---- building ------------------------------------------------------------------- */

mapgen_closure_result_t MapGenClosure_Build(const mapgen_geometry_t *geometry,
                                            uint32_t seed_brush,
                                            uint32_t depth,
                                            mapgen_closure_t **out)
{
    if (out)
        *out = NULL;
    if (!geometry || !out)
        return MAPGEN_CLOSURE_ERR_ARGS;
    const uint32_t n = MapGenGeometry_NumBrushes(geometry);
    const mapgen_geometry_brush_t *seed =
        MapGenGeometry_Brush(geometry, seed_brush);
    if (!seed)
        return MAPGEN_CLOSURE_ERR_NO_SEED;

    mapgen_closure_t *c = calloc(1, sizeof(*c));
    if (!c)
        return MAPGEN_CLOSURE_ERR_MEMORY;
    c->brushes = calloc(MAPGEN_CLOSURE_MAX_BRUSHES, sizeof(uint32_t));
    c->reason = calloc(n ? n : 1, 1);
    c->entities = calloc(MAPGEN_CLOSURE_MAX_ENTITIES, sizeof(uint32_t));
    c->owned_entity = calloc(MapGenGeometry_NumEntities(geometry) + 1, 1);
    if (!c->brushes || !c->reason || !c->entities || !c->owned_entity) {
        MapGenClosure_Free(c);
        return MAPGEN_CLOSURE_ERR_MEMORY;
    }
    c->num_donor_brushes = n;
    for (int a = 0; a < 3; a++) {
        c->mins[a] = 1e30f;
        c->maxs[a] = -1e30f;
    }

    add(c, geometry, seed_brush, MAPGEN_CLOSURE_SEED);

    /* Half a door is not a door. */
    if (seed->model != 0)
        for (uint32_t b = 0; b < n; b++) {
            const mapgen_geometry_brush_t *cand =
                MapGenGeometry_Brush(geometry, b);
            if (cand && cand->model == seed->model)
                add(c, geometry, b, MAPGEN_CLOSURE_MODEL);
        }

    /*
     * The surface, all of it - and no further.
     *
     * The planes are the SEED's, fixed here and never added to. Letting each
     * new member contribute its own planes makes the rule transitive, and a
     * transitive rule over a map whose solid is one connected mass returns the
     * map: the first version of this came back with 923 of q2dm1's 960
     * brushes.
     */
    const mapgen_geometry_side_t *planes[64];
    uint32_t num_planes = 0;
    for (uint32_t s = 0; s < seed->num_sides && num_planes < 64; s++) {
        const mapgen_geometry_side_t *side =
            MapGenGeometry_Side(geometry, seed->first_side + s);
        if (side && !side->bevel)
            planes[num_planes++] = side;
    }

    bool grew = true;
    while (grew) {
        grew = false;
        const uint32_t held = c->num_brushes;
        for (uint32_t i = 0; i < held; i++) {
            const mapgen_geometry_brush_t *member =
                MapGenGeometry_Brush(geometry, c->brushes[i]);
            if (!member)
                continue;
            for (uint32_t b = 0; b < n; b++) {
                if (c->reason[b])
                    continue;
                const mapgen_geometry_brush_t *cand =
                    MapGenGeometry_Brush(geometry, b);
                if (!cand || cand->model != member->model)
                    continue;
                if (!contact(geometry, member, cand, NULL))
                    continue;
                if (planes_shared(geometry, planes, num_planes, cand) >= 2) {
                    add(c, geometry, b, MAPGEN_CLOSURE_COPLANAR);
                    grew = true;
                }
            }
        }
        if (c->num_brushes >= MAPGEN_CLOSURE_MAX_BRUSHES) {
            MapGenClosure_Free(c);
            return MAPGEN_CLOSURE_ERR_TOO_LARGE;
        }
    }

    /* What is stuck to it, as far out as it was asked to look. */
    for (uint32_t round = 0; round < depth; round++) {
        const uint32_t held = c->num_brushes;
        for (uint32_t i = 0; i < held; i++) {
            const mapgen_geometry_brush_t *member =
                MapGenGeometry_Brush(geometry, c->brushes[i]);
            if (!member)
                continue;
            for (uint32_t b = 0; b < n; b++) {
                if (c->reason[b])
                    continue;
                const mapgen_geometry_brush_t *cand =
                    MapGenGeometry_Brush(geometry, b);
                float where[3];
                if (!cand || !contact(geometry, member, cand, where))
                    continue;
                /*
                 * Three ways something that abuts a member belongs to it: it
                 * is that member's clip, it is a small piece stuck to it, or
                 * it holds it up. A long wall a pillar leans on is none of
                 * those, and taking it would make this closure the map.
                 */
                if (invisible(geometry, cand)
                    || attached_to(member, cand)
                    || supports(member, cand, where))
                    add(c, geometry, b, MAPGEN_CLOSURE_TOUCHING);
            }
        }
        if (c->num_brushes == held)
            break;
    }

    /* The entities standing on it, and the mechanisms they belong to. */
    const uint32_t entities = MapGenGeometry_NumEntities(geometry);
    for (uint32_t e = 0; e < entities; e++) {
        const mapgen_geometry_entity_t *ent =
            MapGenGeometry_Entity(geometry, e);
        if (!ent)
            continue;
        if (ent->model) {
            for (uint32_t i = 0; i < c->num_brushes; i++) {
                const mapgen_geometry_brush_t *member =
                    MapGenGeometry_Brush(geometry, c->brushes[i]);
                if (member && member->model == ent->model) {
                    own_entity(c, e);
                    break;
                }
            }
            continue;
        }
        if (!ent->has_origin)
            continue;
        /* Standing on it: inside the closure's box, within a step of the top
           of it. Not "near", which would take in the room. */
        bool on_it = true;
        for (int a = 0; a < 2 && on_it; a++)
            if (ent->origin[a] < c->mins[a] || ent->origin[a] > c->maxs[a])
                on_it = false;
        if (on_it && ent->origin[2] >= c->maxs[2] - 1.0f
            && ent->origin[2] <= c->maxs[2] + 64.0f)
            own_entity(c, e);
    }
    close_over_targets(c, geometry);

    /*
     * A rule that is right can still be handed a map that defeats it.
     *
     * A closure past a third of the map is not one logical structure whatever
     * the rules concluded, and returning it would let an operator carve half
     * the level believing it had chosen a wall. Refused, and the refusal is
     * the answer.
     */
    if (n > 8 && c->num_brushes * 3 > n * 2) {
        MapGenClosure_Free(c);
        return MAPGEN_CLOSURE_ERR_TOO_LARGE;
    }

    *out = c;
    return MAPGEN_CLOSURE_OK;
}

void MapGenClosure_Free(mapgen_closure_t *c)
{
    if (!c)
        return;
    free(c->brushes);
    free(c->reason);
    free(c->entities);
    free(c->owned_entity);
    free(c);
}

/* ---- what it knows -------------------------------------------------------------- */

uint32_t MapGenClosure_NumBrushes(const mapgen_closure_t *c)
{
    return c ? c->num_brushes : 0;
}

uint32_t MapGenClosure_Brush(const mapgen_closure_t *c, uint32_t i)
{
    return c && i < c->num_brushes ? c->brushes[i] : UINT32_MAX;
}

mapgen_closure_reason_t MapGenClosure_Reason(const mapgen_closure_t *c,
                                             uint32_t brush)
{
    if (!c || brush >= c->num_donor_brushes || !c->reason[brush])
        return MAPGEN_CLOSURE_REASON_COUNT;
    return (mapgen_closure_reason_t)(c->reason[brush] - 1);
}

bool MapGenClosure_Contains(const mapgen_closure_t *c, uint32_t brush)
{
    return c && brush < c->num_donor_brushes && c->reason[brush] != 0;
}

uint32_t MapGenClosure_NumEntities(const mapgen_closure_t *c)
{
    return c ? c->num_entities : 0;
}

uint32_t MapGenClosure_Entity(const mapgen_closure_t *c, uint32_t i)
{
    return c && i < c->num_entities ? c->entities[i] : UINT32_MAX;
}

const float *MapGenClosure_Mins(const mapgen_closure_t *c)
{
    return c ? c->mins : NULL;
}

const float *MapGenClosure_Maxs(const mapgen_closure_t *c)
{
    return c ? c->maxs : NULL;
}

/* ---- the two questions ---------------------------------------------------------- */

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
        if (side->normal[0] * p[0] + side->normal[1] * p[1]
            + side->normal[2] * p[2] - side->dist > 0.03125f)
            return false;
    }
    return true;
}

bool MapGenClosure_SolidWithout(const mapgen_closure_t *c,
                                const mapgen_geometry_t *geometry,
                                const float point[3])
{
    if (!c || !geometry || !point)
        return false;
    const uint32_t n = MapGenGeometry_NumBrushes(geometry);
    for (uint32_t b = 0; b < n; b++) {
        if (b < c->num_donor_brushes && c->reason[b])
            continue;                    /* it is us; that is the whole point */
        const mapgen_geometry_brush_t *brush =
            MapGenGeometry_Brush(geometry, b);
        if (!brush || !(brush->contents & MAPGEN_CONTENTS_SOLID))
            continue;
        if (inside(geometry, brush, point))
            return true;
    }
    return false;
}

/*
 * Would taking this away open the map?
 *
 * Asked across each member brush rather than around it: step just outside one
 * face, step just outside the face opposite, and if both of those are open
 * space and nothing but this closure fills the line between them, then this
 * closure is the only thing keeping those two places apart. Removing it joins
 * them, and joining two places that were not joined is either a new route or a
 * hole, and an operator may not decide which by itself.
 */
bool MapGenClosure_Seals(const mapgen_closure_t *c,
                         const mapgen_geometry_t *geometry,
                         const mapgen_bsp_t *bsp)
{
    if (!c || !geometry || !bsp)
        return true;                     /* refuse when it cannot be asked */

    for (uint32_t i = 0; i < c->num_brushes; i++) {
        const mapgen_geometry_brush_t *brush =
            MapGenGeometry_Brush(geometry, c->brushes[i]);
        if (!brush || !(brush->contents & MAPGEN_CONTENTS_SOLID))
            continue;

        for (uint32_t s = 0; s < brush->num_sides; s++) {
            const mapgen_geometry_side_t *side =
                MapGenGeometry_Side(geometry, brush->first_side + s);
            if (!side || side->bevel || side->area <= 0.0f)
                continue;

            /* Just outside this face, and just outside the far side of the
               brush along the same line. */
            float here[3], there[3];
            for (int a = 0; a < 3; a++)
                here[a] = side->center[a] + side->normal[a] * 1.0f;

            float thickness = 0;
            for (int a = 0; a < 3; a++)
                thickness += (brush->maxs[a] - brush->mins[a])
                           * fabsf(side->normal[a]);
            for (int a = 0; a < 3; a++)
                there[a] = side->center[a]
                         - side->normal[a] * (thickness + 1.0f);

            if ((MapGenBsp_PointContents(bsp, here) & MAPGEN_CONTENTS_SOLID)
                || (MapGenBsp_PointContents(bsp, there)
                    & MAPGEN_CONTENTS_SOLID))
                continue;                /* one end is rock; nothing to open */

            /* Nothing but us between them? */
            bool only_us = true;
            const int steps = (int)(thickness / 4.0f) + 2;
            for (int k = 1; k < steps && only_us; k++) {
                float p[3];
                const float t = (float)k / (float)steps;
                for (int a = 0; a < 3; a++)
                    p[a] = here[a] + (there[a] - here[a]) * t;
                if (MapGenClosure_SolidWithout(c, geometry, p))
                    only_us = false;
            }
            if (only_us)
                return true;
        }
    }
    return false;
}
