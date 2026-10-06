/*
 * MapGenGeometry - see inc/common/mapgen_geometry.h for why this exists.
 *
 * Three jobs live here and nowhere else: deriving a brush's real shape from
 * the half-spaces a compiler left behind, proving which model owns it, and
 * writing the result back out as a `.map` the pinned compiler will rebuild
 * into the same map. Callers see brushes, sides and entities; they never see a
 * winding, a plane index or an entity string.
 */

#include "common/mapgen_fs.h"
#include "common/mapgen_geometry.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char *MapGenGeometry_ResultName(mapgen_geometry_result_t r)
{
    switch (r) {
    case MAPGEN_GEOMETRY_OK:              return "OK";
    case MAPGEN_GEOMETRY_ERR_ARGS:        return "ERR_ARGS";
    case MAPGEN_GEOMETRY_ERR_MEMORY:      return "ERR_MEMORY";
    case MAPGEN_GEOMETRY_ERR_LIMIT:       return "ERR_LIMIT";
    case MAPGEN_GEOMETRY_ERR_DEGENERATE:  return "ERR_DEGENERATE";
    case MAPGEN_GEOMETRY_ERR_NON_FINITE:  return "ERR_NON_FINITE";
    case MAPGEN_GEOMETRY_ERR_OWNERSHIP:   return "ERR_OWNERSHIP";
    case MAPGEN_GEOMETRY_ERR_UNSUPPORTED: return "DONOR_GEOMETRY_UNSUPPORTED";
    case MAPGEN_GEOMETRY_ERR_AREAPORTAL:  return "ERR_AREAPORTAL";
    }
    return "ERR_UNKNOWN";
}

struct mapgen_geometry_s {
    mapgen_geometry_brush_t  *brushes;
    uint32_t                  num_brushes;
    mapgen_geometry_side_t   *sides;
    uint32_t                  num_sides;
    mapgen_geometry_entity_t *entities;
    uint32_t                  num_entities;

    /* Key/value bytes, NUL-separated; `pair_at[2i]` and `[2i+1]` are the
       offsets of the i-th key and its value. One block so a clone is one
       memcpy and a bound is one number. */
    char                     *text;
    size_t                    text_len;
    size_t                    text_cap;
    uint32_t                 *pair_at;
    uint32_t                  num_pairs;
    uint32_t                  pair_cap;

    /* The visible mesh, independent of the brushes above. */
    mapgen_geometry_face_t   *faces;
    uint32_t                  num_faces;
    float                    *points;      /* three floats per point */
    uint32_t                  num_points;

    uint32_t                  num_models;
    uint32_t                  orphan_brushes;

    /* Capacity, so a candidate can grow. The donor's own extraction sizes
       these exactly and they only move when an edit adds something. */
    uint32_t                  brush_cap;
    uint32_t                  side_cap;
    uint32_t                  entity_cap;
    uint32_t dressed_sides;     /* row 400: textureless sides of drawn brushes given the map's texture */
    uint32_t faithful_sides;    /* row 400: overlapped sides given the face the donor draws over them */
    uint32_t respanned_sides;   /* row 404: sides whose mapping did not span their own wall */
};

/* ---- windings ------------------------------------------------------------- */

/*
 * A brush arrives as a pile of half-spaces with no shape of its own. Its
 * shape is what is left of each plane after every other plane has taken its
 * bite - so that is how it is derived, by clipping a plane-sized square down
 * against all of the brush's other planes.
 *
 * A side left with nothing is not an error and not something to discard: it is
 * a compiler bevel, redundant against its neighbours, and it is kept because
 * proving one redundant is a separate question from noticing it has no face.
 */

#ifndef MAPGEN_BASE_WINDING_EXTENT
#define MAPGEN_BASE_WINDING_EXTENT 65536.0f
#endif

#define WINDING_MAX_POINTS 256
#define WINDING_EPSILON    0.01f

/*
 * Double, deliberately. The square a winding starts as is 65536 units across,
 * where a float has 0.008 of slack per coordinate, and four clips later that
 * decides whether a hairline side has a face or is a bevel - which in turn
 * decides whether the writer may drop its plane. The independent oracle, which
 * works in double, disagreed with this file about exactly one such side.
 */
typedef struct {
    uint32_t count;
    double   p[WINDING_MAX_POINTS][3];
} winding_t;

static bool finite3(const float v[3])
{
    return isfinite(v[0]) && isfinite(v[1]) && isfinite(v[2]);
}

static void base_winding(const float normal[3], float dist, winding_t *w)
{
    const double n[3] = { normal[0], normal[1], normal[2] };
    const double d = (double)dist;
    /* Any tangent will do; the one built from the smallest component is the
       one furthest from parallel, which is the one that stays well
       conditioned. */
    int minor = 0;
    for (int i = 1; i < 3; i++) {
        if (fabs(n[i]) < fabs(n[minor]))
            minor = i;
    }

    double t[3] = { 0, 0, 0 };
    t[minor] = 1.0;

    double u[3], v[3];
    const double dot = t[0] * n[0] + t[1] * n[1] + t[2] * n[2];
    for (int i = 0; i < 3; i++)
        u[i] = t[i] - n[i] * dot;
    const double ulen = sqrt(u[0] * u[0] + u[1] * u[1] + u[2] * u[2]);
    for (int i = 0; i < 3; i++)
        u[i] /= ulen;

    /* v = n x u, so that u x v is n and the winding runs counter-clockwise
       seen from the front - the order the compiler reads a face in. */
    v[0] = n[1] * u[2] - n[2] * u[1];
    v[1] = n[2] * u[0] - n[0] * u[2];
    v[2] = n[0] * u[1] - n[1] * u[0];

    /*
     * How far the plane-sized square starts out.
     *
     * A variable of the seam diagnosis, because it is also a precision
     * decision: at 65536 a float32 coordinate is spaced 0.0078 apart, so a
     * corner that survives four clips can land a hundredth of a unit from
     * where it belongs - and the plane stated through that corner is then a
     * hundredth out, which is exactly the tolerance the compiler uses to
     * decide whether two planes are the same one.
     */
    const double R = MAPGEN_BASE_WINDING_EXTENT;
    double c[3];
    for (int i = 0; i < 3; i++)
        c[i] = n[i] * d;

    const double su[4] = { -1, +1, +1, -1 };
    const double sv[4] = { -1, -1, +1, +1 };
    w->count = 4;
    for (int k = 0; k < 4; k++) {
        for (int i = 0; i < 3; i++)
            w->p[k][i] = c[i] + u[i] * (su[k] * R) + v[i] * (sv[k] * R);
    }
}

/* Keep the half that is BEHIND the plane - inside the solid. */
static void clip_winding(winding_t *w, const float normal[3], float dist)
{
    double   dists[WINDING_MAX_POINTS + 1];
    int      sides[WINDING_MAX_POINTS + 1];
    uint32_t counts[3] = { 0, 0, 0 };

    for (uint32_t i = 0; i < w->count; i++) {
        const double d = w->p[i][0] * (double)normal[0]
                       + w->p[i][1] * (double)normal[1]
                       + w->p[i][2] * (double)normal[2] - (double)dist;
        dists[i] = d;
        sides[i] = d > WINDING_EPSILON ? 0 : (d < -WINDING_EPSILON ? 1 : 2);
        counts[sides[i]]++;
    }
    if (!counts[0]) {
        return;                  /* nothing in front; the whole side survives */
    }
    if (!counts[1]) {
        w->count = 0;            /* nothing behind; this plane cuts it away */
        return;
    }
    dists[w->count] = dists[0];
    sides[w->count] = sides[0];

    winding_t out;
    out.count = 0;
    for (uint32_t i = 0; i < w->count; i++) {
        if (sides[i] != 0 && out.count < WINDING_MAX_POINTS)
            memcpy(out.p[out.count++], w->p[i], sizeof(out.p[0]));
        if (sides[i] == 2 || sides[i + 1] == 2 || sides[i + 1] == sides[i])
            continue;

        const uint32_t next = (i + 1) % w->count;
        const double f = dists[i] / (dists[i] - dists[i + 1]);
        if (out.count >= WINDING_MAX_POINTS)
            continue;
        for (int a = 0; a < 3; a++) {
            /* Snapping a crossing that lands on an axis keeps a plane that
               was axis-aligned in the donor axis-aligned here. */
            const double mid = w->p[i][a] + f * (w->p[next][a] - w->p[i][a]);
            out.p[out.count][a] = normal[a] == 1.0f  ? (double)dist
                                : normal[a] == -1.0f ? -(double)dist
                                : mid;
        }
        out.count++;
    }
    *w = out;
}

/*
 * Give a set of planes their shape: each side's winding, and from it the
 * brush's bounds and the side's centroid, area and samples.
 *
 * Returns how many sides ended up with a face of their own. Zero means the
 * planes enclose nothing.
 */
static uint32_t shape_brush(mapgen_geometry_side_t *sides, uint32_t count,
                            float mins[3], float maxs[3])
{
    winding_t *windings = malloc((size_t)count * sizeof(*windings));
    if (!windings)
        return 0;

    for (int a = 0; a < 3; a++) {
        mins[a] = MAPGEN_GEOMETRY_WORLD_EXTENT;
        maxs[a] = -MAPGEN_GEOMETRY_WORLD_EXTENT;
    }

    uint32_t shaped = 0;
    for (uint32_t s = 0; s < count; s++) {
        base_winding(sides[s].normal, sides[s].dist, &windings[s]);
        for (uint32_t o = 0; o < count && windings[s].count; o++) {
            if (o == s)
                continue;
            clip_winding(&windings[s], sides[o].normal, sides[o].dist);
        }

        sides[s].bevel = windings[s].count < 3;
        sides[s].area = 0.0f;
        sides[s].num_samples = 0;
        if (sides[s].bevel)
            continue;
        shaped++;

        double area2 = 0.0, cx = 0.0, cy = 0.0, cz = 0.0;
        for (uint32_t p = 1; p + 1 < windings[s].count; p++) {
            double e1[3], e2[3], cross[3];
            for (int a = 0; a < 3; a++) {
                e1[a] = windings[s].p[p][a] - windings[s].p[0][a];
                e2[a] = windings[s].p[p + 1][a] - windings[s].p[0][a];
            }
            cross[0] = e1[1] * e2[2] - e1[2] * e2[1];
            cross[1] = e1[2] * e2[0] - e1[0] * e2[2];
            cross[2] = e1[0] * e2[1] - e1[1] * e2[0];
            const double tri = sqrt(cross[0] * cross[0] + cross[1] * cross[1]
                                  + cross[2] * cross[2]);
            area2 += tri;
            cx += tri * (windings[s].p[0][0] + windings[s].p[p][0]
                         + windings[s].p[p + 1][0]) / 3.0;
            cy += tri * (windings[s].p[0][1] + windings[s].p[p][1]
                         + windings[s].p[p + 1][1]) / 3.0;
            cz += tri * (windings[s].p[0][2] + windings[s].p[p][2]
                         + windings[s].p[p + 1][2]) / 3.0;
        }
        sides[s].area = (float)(area2 * 0.5);
        if (area2 > 0.0) {
            sides[s].center[0] = (float)(cx / area2);
            sides[s].center[1] = (float)(cy / area2);
            sides[s].center[2] = (float)(cz / area2);
        }

        sides[s].num_samples = 1;
        memcpy(sides[s].sample[0], sides[s].center, sizeof(sides[s].center));
        const uint32_t step = windings[s].count
                            / (MAPGEN_GEOMETRY_FACE_SAMPLES - 1) + 1;
        for (uint32_t p = 0; p < windings[s].count
             && sides[s].num_samples < MAPGEN_GEOMETRY_FACE_SAMPLES; p += step) {
            for (int a = 0; a < 3; a++) {
                sides[s].sample[sides[s].num_samples][a] =
                    0.5f * (sides[s].center[a] + windings[s].p[p][a]);
            }
            sides[s].num_samples++;
        }

        for (uint32_t p = 0; p < windings[s].count; p++) {
            for (int a = 0; a < 3; a++) {
                if (windings[s].p[p][a] < mins[a])
                    mins[a] = windings[s].p[p][a];
                if (windings[s].p[p][a] > maxs[a])
                    maxs[a] = windings[s].p[p][a];
            }
        }
    }

    free(windings);
    return shaped;
}

/* ---- ownership ------------------------------------------------------------ */

/*
 * Which model a brush belongs to is decided by which model's collision tree
 * reaches it, never by where it happens to be. A door's solids are the door's
 * because the door's tree owns the leaf they sit in; two doors standing in the
 * same doorway would defeat any answer based on proximity.
 */
static mapgen_geometry_result_t mark_owner(const mapgen_bsp_t *bsp,
                                           int32_t root, uint32_t model,
                                           uint32_t *owner, uint8_t *claimed)
{
    const uint32_t num_nodes = MapGenBsp_NumNodes(bsp);
    const uint32_t num_leafs = MapGenBsp_NumLeafs(bsp);
    const uint32_t num_brushes = MapGenBsp_NumBrushes(bsp);

    int32_t *stack = malloc((size_t)(num_nodes + 1) * sizeof(*stack));
    uint8_t *seen = calloc(num_nodes ? num_nodes : 1, sizeof(*seen));
    if (!stack || !seen) {
        free(stack);
        free(seen);
        return MAPGEN_GEOMETRY_ERR_MEMORY;
    }

    size_t top = 0;
    stack[top++] = root;
    mapgen_geometry_result_t result = MAPGEN_GEOMETRY_OK;

    while (top) {
        const int32_t at = stack[--top];
        if (at < 0) {
            const uint32_t leaf = (uint32_t)(-1 - at);
            if (leaf >= num_leafs)
                continue;
            const mapgen_bsp_leaf_t *l = MapGenBsp_Leaf(bsp, leaf);
            for (uint32_t i = 0; i < (uint32_t)l->numleafbrushes; i++) {
                const uint32_t b = MapGenBsp_LeafBrush(bsp, l->firstleafbrush + i);
                if (b >= num_brushes)
                    continue;
                if (claimed[b] && owner[b] != model) {
                    result = MAPGEN_GEOMETRY_ERR_OWNERSHIP;
                    top = 0;
                    break;
                }
                owner[b] = model;
                claimed[b] = 1;
            }
            continue;
        }
        if ((uint32_t)at >= num_nodes || seen[at])
            continue;
        seen[at] = 1;
        const mapgen_bsp_node_t *n = MapGenBsp_Node(bsp, (uint32_t)at);
        if (top + 2 > (size_t)num_nodes + 1)
            continue;
        stack[top++] = n->children[0];
        stack[top++] = n->children[1];
    }

    free(stack);
    free(seen);
    return result;
}

/* ---- text storage --------------------------------------------------------- */

static bool reserve_text(mapgen_geometry_t *g, size_t extra)
{
    if (g->text_len + extra <= g->text_cap)
        return true;
    size_t want = g->text_cap ? g->text_cap : 4096;
    while (want < g->text_len + extra)
        want *= 2;
    if (want > MAPGEN_GEOMETRY_MAX_KEYVALUES)
        return false;
#ifdef MAPGEN_GEOMETRY_TEXT_ALWAYS_MOVES
    /* the entity-text guard's build: every growth moves the block and spoils the old one, so a pointer still
       aimed at it reads spoiled bytes every time instead of whenever the allocator happens to move it */
    char *grown = malloc(want);
    if (!grown)
        return false;
    if (g->text) {
        memcpy(grown, g->text, g->text_len);
        memset(g->text, 0xEE, g->text_cap);
        free(g->text);
    }
#else
    char *grown = realloc(g->text, want);
    if (!grown)
        return false;
#endif
    g->text = grown;
    g->text_cap = want;
    return true;
}

/*
 * Where in the block a key or a value lies, or -1 when it is not in it (row 403).
 *
 * Callers hand over strings read from this same block - a swap of two pickups writes one's classname over the
 * other's, read with MapGenGeometry_EntityValue - and growing the block can move it. The Studio guard's resumed
 * q2dm1 run wrote spoiled bytes as an ammo_grenades' class and then crashed: the swap's second name was copied from the block
 * the growth had just freed. A string from the block is re-found at its offset after the growth.
 */
static ptrdiff_t text_offset(const mapgen_geometry_t *g, const char *p)
{
    const uintptr_t at = (uintptr_t)p, lo = (uintptr_t)g->text;
    return g->text && at >= lo && at < lo + g->text_cap ? (ptrdiff_t)(at - lo) : -1;
}

static bool add_pair(mapgen_geometry_t *g, const char *key, size_t klen,
                     const char *value, size_t vlen)
{
    const ptrdiff_t key_at = text_offset(g, key), value_at = text_offset(g, value);
    if (g->num_pairs == g->pair_cap) {
        const uint32_t want = g->pair_cap ? g->pair_cap * 2 : 64;
        uint32_t *grown = realloc(g->pair_at, (size_t)want * 2 * sizeof(*grown));
        if (!grown)
            return false;
        g->pair_at = grown;
        g->pair_cap = want;
    }
    if (!reserve_text(g, klen + vlen + 2))
        return false;
    if (key_at >= 0)
        key = g->text + key_at;
    if (value_at >= 0)
        value = g->text + value_at;

    g->pair_at[g->num_pairs * 2] = (uint32_t)g->text_len;
    memcpy(g->text + g->text_len, key, klen);
    g->text_len += klen;
    g->text[g->text_len++] = '\0';

    g->pair_at[g->num_pairs * 2 + 1] = (uint32_t)g->text_len;
    memcpy(g->text + g->text_len, value, vlen);
    g->text_len += vlen;
    g->text[g->text_len++] = '\0';

    g->num_pairs++;
    return true;
}

/* ---- entities -------------------------------------------------------------- */

static const char *skip_space(const char *p)
{
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')
        p++;
    return p;
}

static mapgen_geometry_result_t parse_entities(mapgen_geometry_t *g,
                                               const mapgen_bsp_t *bsp)
{
    uint32_t length = 0;
    const char *at = MapGenBsp_Entities(bsp, &length);
    if (!at)
        return MAPGEN_GEOMETRY_OK;

    uint32_t capacity = 64;
    g->entities = calloc(capacity, sizeof(*g->entities));
    if (!g->entities)
        return MAPGEN_GEOMETRY_ERR_MEMORY;
    g->entity_cap = capacity;

    while (*at) {
        at = skip_space(at);
        if (*at != '{')
            break;
        at++;

        if (g->num_entities == capacity) {
            if (capacity * 2 > MAPGEN_GEOMETRY_MAX_ENTITIES)
                return MAPGEN_GEOMETRY_ERR_LIMIT;
            mapgen_geometry_entity_t *grown =
                realloc(g->entities, (size_t)capacity * 2 * sizeof(*grown));
            if (!grown)
                return MAPGEN_GEOMETRY_ERR_MEMORY;
            memset(grown + capacity, 0, (size_t)capacity * sizeof(*grown));
            g->entities = grown;
            capacity *= 2;
            g->entity_cap = capacity;
        }

        mapgen_geometry_entity_t *e = &g->entities[g->num_entities];
        e->first_pair = g->num_pairs;

        for (;;) {
            at = skip_space(at);
            if (*at == '}') {
                at++;
                break;
            }
            if (*at != '"')
                return MAPGEN_GEOMETRY_ERR_UNSUPPORTED;
            const char *key = ++at;
            while (*at && *at != '"')
                at++;
            if (*at != '"')
                return MAPGEN_GEOMETRY_ERR_UNSUPPORTED;
            const size_t klen = (size_t)(at - key);
            at = skip_space(at + 1);
            if (*at != '"')
                return MAPGEN_GEOMETRY_ERR_UNSUPPORTED;
            const char *value = ++at;
            while (*at && *at != '"')
                at++;
            if (*at != '"')
                return MAPGEN_GEOMETRY_ERR_UNSUPPORTED;
            const size_t vlen = (size_t)(at - value);
            at++;

            if (!add_pair(g, key, klen, value, vlen))
                return MAPGEN_GEOMETRY_ERR_LIMIT;

            /*
             * The two keys that bind an entity to geometry are read as they
             * arrive. `model "*n"` is the ONLY thing that makes a brush model
             * a door - the compiler will renumber it on the way out, so the
             * binding is what has to survive, not the ordinal.
             */
            if (klen == 5 && !memcmp(key, "model", 5) && vlen > 1
                && value[0] == '*') {
                e->model = (uint32_t)strtoul(value + 1, NULL, 10);
            } else if (klen == 6 && !memcmp(key, "origin", 6)) {
                char buf[128];
                const size_t n = vlen < sizeof(buf) - 1 ? vlen : sizeof(buf) - 1;
                memcpy(buf, value, n);
                buf[n] = '\0';
                char *cursor = buf;
                for (int i = 0; i < 3; i++)
                    e->origin[i] = strtof(cursor, &cursor);
                e->has_origin = true;
            }
        }

        e->num_pairs = g->num_pairs - e->first_pair;
        g->num_entities++;
    }
    return MAPGEN_GEOMETRY_OK;
}

/* ---- the visible mesh -------------------------------------------------------- */

/*
 * Which model a face belongs to, from the model's own face range. Faces are
 * contiguous per model in a compiled BSP, which is the one place ownership can
 * be read directly rather than proven.
 */
static uint32_t face_model(const mapgen_bsp_t *bsp, uint32_t face)
{
    for (uint32_t m = 0; m < MapGenBsp_NumModels(bsp); m++) {
        const mapgen_bsp_model_t *model = MapGenBsp_Model(bsp, m);
        if (model->firstface >= 0 && face >= (uint32_t)model->firstface
            && face < (uint32_t)(model->firstface + model->numfaces))
            return m;
    }
    return 0;
}

static mapgen_geometry_result_t extract_faces(mapgen_geometry_t *g,
                                              const mapgen_bsp_t *bsp)
{
    const uint32_t count = MapGenBsp_NumFaces(bsp);
    const uint32_t num_texinfo = MapGenBsp_NumTexInfo(bsp);
    const uint32_t num_planes = MapGenBsp_NumPlanes(bsp);
    const uint32_t num_verts = MapGenBsp_NumVertices(bsp);
    const uint32_t num_edges = MapGenBsp_NumEdges(bsp);
    const uint32_t num_surfedges = MapGenBsp_NumSurfEdges(bsp);

    if (count > MAPGEN_GEOMETRY_MAX_FACES
        || num_surfedges > MAPGEN_GEOMETRY_MAX_POINTS)
        return MAPGEN_GEOMETRY_ERR_LIMIT;
    if (!count)
        return MAPGEN_GEOMETRY_OK;

    g->faces = calloc(count, sizeof(*g->faces));
    g->points = calloc((size_t)num_surfedges * 3 + 3, sizeof(*g->points));
    if (!g->faces || !g->points)
        return MAPGEN_GEOMETRY_ERR_MEMORY;

    for (uint32_t f = 0; f < count; f++) {
        const mapgen_bsp_face_t *src = MapGenBsp_Face(bsp, f);
        if (src->numedges < 3 || src->firstedge < 0
            || (uint32_t)(src->firstedge + src->numedges) > num_surfedges)
            continue;
        if (src->planenum >= num_planes)
            return MAPGEN_GEOMETRY_ERR_LIMIT;

        mapgen_geometry_face_t *dst = &g->faces[g->num_faces];
        const mapgen_bsp_plane_t *plane = MapGenBsp_Plane(bsp, src->planenum);
        const float sign = src->side ? -1.0f : 1.0f;
        for (int a = 0; a < 3; a++)
            dst->normal[a] = plane->normal[a] * sign;
        dst->dist = plane->dist * sign;
        dst->model = face_model(bsp, f);
        dst->first_point = g->num_points;
        dst->num_points = (uint32_t)src->numedges;

        if (src->texinfo >= 0 && (uint32_t)src->texinfo < num_texinfo) {
            const mapgen_bsp_texinfo_t *ti =
                MapGenBsp_TexInfo(bsp, (uint32_t)src->texinfo);
            dst->flags = ti->flags;
            dst->value = ti->value;
            memcpy(dst->texture, ti->texture, sizeof(dst->texture));
        }

        for (int32_t e = 0; e < src->numedges; e++) {
            const int32_t se =
                MapGenBsp_SurfEdge(bsp, (uint32_t)(src->firstedge + e));
            const uint32_t index = (uint32_t)(se < 0 ? -se : se);
            if (index >= num_edges)
                return MAPGEN_GEOMETRY_ERR_LIMIT;
            const mapgen_bsp_edge_t *edge = MapGenBsp_Edge(bsp, index);
            const uint32_t v = se < 0 ? edge->v[1] : edge->v[0];
            if (v >= num_verts)
                return MAPGEN_GEOMETRY_ERR_LIMIT;
            const mapgen_bsp_vertex_t *point = MapGenBsp_Vertex(bsp, v);
            memcpy(&g->points[g->num_points * 3], point->point,
                   3 * sizeof(float));
            g->num_points++;
        }

        /* The fan sum about the first point, exact for the convex polygons a
           BSP face always is. */
        double area2 = 0.0;
        const float *p0 = &g->points[dst->first_point * 3];
        for (uint32_t p = 1; p + 1 < dst->num_points; p++) {
            const float *pa = &g->points[(dst->first_point + p) * 3];
            const float *pb = &g->points[(dst->first_point + p + 1) * 3];
            double e1[3], e2[3], cross[3];
            for (int a = 0; a < 3; a++) {
                e1[a] = pa[a] - p0[a];
                e2[a] = pb[a] - p0[a];
            }
            cross[0] = e1[1] * e2[2] - e1[2] * e2[1];
            cross[1] = e1[2] * e2[0] - e1[0] * e2[2];
            cross[2] = e1[0] * e2[1] - e1[1] * e2[0];
            area2 += sqrt(cross[0] * cross[0] + cross[1] * cross[1]
                          + cross[2] * cross[2]);
        }
        dst->area = (float)(area2 * 0.5);
        g->num_faces++;
    }
    return MAPGEN_GEOMETRY_OK;
}

/* ---- extraction ------------------------------------------------------------ */

/*
 * A side of a DRAWN brush that the donor left without a texture (ledger row 400, Fable's brief 4 G5-1).
 *
 * The donor's compiler never used such a side for a face: cor - a Quake III layout made for Quake II and compiled
 * without the outside fill - has 342 of them on 23 solid brushes. The writer spelled one `e1u1/clip`, and the
 * frozen compiler DRAWS it: where it faces the void past the hull (746619 units of clip in cor's copy), and where
 * it lies on the plane of another brush's textured side, because the compiler gives a portal the first side it
 * finds on that plane (q2tools portals.c FindPortalSide) - the copy then shows this side where the donor shows
 * its neighbour's wall.
 *
 * The PO's rule (2026-10-03): «пусть ставит генератор в таких случаях существующую текстуру». So such a side wears
 * a texture the map already has, and is drawn the way the donor drew that place:
 *  - where the donor DRAWS a face on this very plane over the side (any of its sample points inside a coplanar
 *    donor face), the side takes that face - texture, flags, value and mapping - so whichever of the two sides the
 *    compiler picks, the wall looks as it did;
 *  - where the donor draws nothing there, it takes the texture most of the brush's own textured sides wear (a
 *    brush with none: the nearest drawn face on a parallel plane facing the same way) and SURF_NODRAW - nothing
 *    drawn, as in the donor; should an edit ever need a skin from it, `plane()` drops the flag.
 *
 * Clip, trigger and ladder brushes are not drawn and keep their bare sides: q2dm1's 199 bare sides all sit on clip
 * brushes (0x8030000), so its rebuilt copy is byte-for-byte what it was.
 */
#define MAPGEN_SURF_NODRAW 0x80

/* Is `p` inside BSP face `f` (on its plane, within its convex polygon)? */
static bool bsp_face_holds(const mapgen_bsp_t *bsp, const mapgen_bsp_face_t *f, const float n[3], const float p[3])
{
    const uint32_t num_surfedges = MapGenBsp_NumSurfEdges(bsp), num_edges = MapGenBsp_NumEdges(bsp);
    const uint32_t num_verts = MapGenBsp_NumVertices(bsp);
    float prev[3], first[3];
    bool pos = false, neg = false;
    for (int32_t e = 0; e <= f->numedges; e++) {
        const int32_t k = e % f->numedges;
        if ((uint32_t)(f->firstedge + k) >= num_surfedges)
            return false;
        const int32_t se = MapGenBsp_SurfEdge(bsp, (uint32_t)(f->firstedge + k));
        const uint32_t index = (uint32_t)(se < 0 ? -se : se);
        if (index >= num_edges)
            return false;
        const mapgen_bsp_edge_t *edge = MapGenBsp_Edge(bsp, index);
        const uint32_t vi = se < 0 ? edge->v[1] : edge->v[0];
        if (vi >= num_verts)
            return false;
        const float *v = MapGenBsp_Vertex(bsp, vi)->point;
        if (e == 0) {
            memcpy(first, v, sizeof(first));
        } else {
            const float *cur = e == f->numedges ? first : v;
            const float ex = cur[0] - prev[0], ey = cur[1] - prev[1], ez = cur[2] - prev[2];
            const float wx = p[0] - prev[0], wy = p[1] - prev[1], wz = p[2] - prev[2];
            /* inside a convex polygon: (edge x to-point) . normal keeps one sign all the way round */
            const float c = (ey * wz - ez * wy) * n[0] + (ez * wx - ex * wz) * n[1] + (ex * wy - ey * wx) * n[2];
            if (c > 0.05f)
                pos = true;
            else if (c < -0.05f)
                neg = true;
            if (pos && neg)
                return false;
        }
        memcpy(prev, v, sizeof(prev));
    }
    return true;
}

static void dress_untextured(mapgen_geometry_t *g, const mapgen_bsp_t *bsp)
{
    const uint32_t num_faces = MapGenBsp_NumFaces(bsp), num_planes = MapGenBsp_NumPlanes(bsp);
    const uint32_t num_texinfo = MapGenBsp_NumTexInfo(bsp);
    for (uint32_t b = 0; b < g->num_brushes; b++) {
        const mapgen_geometry_brush_t *brush = &g->brushes[b];
        if (!(brush->contents & (0x00000001 | 0x00000002)))
            continue;
        mapgen_geometry_side_t *sides = &g->sides[brush->first_side];

        /* the brush's own material: the texture most of its textured sides wear */
        const mapgen_geometry_side_t *own = NULL;
        uint32_t own_count = 0;
        bool bare = false;
        for (uint32_t i = 0; i < brush->num_sides; i++) {
            if (!sides[i].bevel && !sides[i].texture[0])
                bare = true;
            if (sides[i].bevel || !MapGenGeometry_TextureIsMaterial(sides[i].texture))
                continue;
            uint32_t n = 0;
            for (uint32_t j = 0; j < brush->num_sides; j++)
                if (!sides[j].bevel && !strcmp(sides[j].texture, sides[i].texture))
                    n++;
            if (n > own_count) {
                own = &sides[i];
                own_count = n;
            }
        }
        if (!bare)
            continue;

        for (uint32_t i = 0; i < brush->num_sides; i++) {
            mapgen_geometry_side_t *side = &sides[i];
            if (side->bevel || side->texture[0])
                continue;

            /* the face the donor draws on this very plane, over this side */
            const mapgen_bsp_texinfo_t *drawn = NULL;
            for (uint32_t f = 0; f < num_faces && !drawn; f++) {
                const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
                if (face->numedges < 3 || face->planenum >= num_planes || face->texinfo < 0
                    || (uint32_t)face->texinfo >= num_texinfo)
                    continue;
                const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, face->planenum);
                const float sign = face->side ? -1.0f : 1.0f;
                const float n[3] = { pl->normal[0] * sign, pl->normal[1] * sign, pl->normal[2] * sign };
                if (n[0] * side->normal[0] + n[1] * side->normal[1] + n[2] * side->normal[2] < 0.9999f
                    || fabsf(pl->dist * sign - side->dist) > 0.1f)
                    continue;
                for (uint32_t k = 0; k < side->num_samples; k++) {
                    if (bsp_face_holds(bsp, face, n, side->sample[k])) {
                        drawn = MapGenBsp_TexInfo(bsp, (uint32_t)face->texinfo);
                        break;
                    }
                }
            }
            if (drawn) {
                memcpy(side->axis, drawn->axis, sizeof(side->axis));
                memcpy(side->texture, drawn->texture, sizeof(side->texture));
                side->flags = drawn->flags;
                side->value = drawn->value;
                g->dressed_sides++;
                continue;
            }

            const char *texture = own ? own->texture : NULL;
            int32_t flags = own ? own->flags : 0, value = own ? own->value : 0;
            if (!texture) {
                /* no textured side of its own: the nearest drawn face on a parallel plane, facing the same way */
                double best = 1e30;
                for (uint32_t f = 0; f < g->num_faces; f++) {
                    const mapgen_geometry_face_t *face = &g->faces[f];
                    if (!face->num_points || !MapGenGeometry_TextureIsMaterial(face->texture)
                        || face->normal[0] * side->normal[0] + face->normal[1] * side->normal[1]
                           + face->normal[2] * side->normal[2] < 0.99f)
                        continue;
                    const float *q = &g->points[face->first_point * 3];
                    const double dx = q[0] - side->center[0], dy = q[1] - side->center[1],
                                 dz = q[2] - side->center[2];
                    const double d2 = dx * dx + dy * dy + dz * dz;
                    if (d2 < best) {
                        best = d2;
                        texture = face->texture;
                        flags = face->flags;
                        value = face->value;
                    }
                }
            }
            if (!texture)
                continue;
            snprintf(side->texture, sizeof(side->texture), "%s", texture);
            side->value = value;
            /* the donor draws nothing here: neither does the copy */
            side->flags = flags | MAPGEN_SURF_NODRAW;
            g->dressed_sides++;
        }
    }
}

/*
 * Faithful skins (row 400, Fable's brief 4 G5-3): a textured side of a drawn brush that lies under a face the donor
 * draws on its own plane, and wears anything else there - another texture, another mapping (one that does not even
 * lie on its plane: an axis along the plane's normal), other flags - takes that face: texture, flags, value, mapping.
 *
 * Quake III layouts made for Quake II carry such sides by the hundred (cor 98, q3t2 189): brushes that overlap on a
 * plane, the hidden one wearing a texture of its own or one projected for a wall at right angles. The donor's
 * compiler drew the visible one; the frozen compiler gives a portal the FIRST side it finds on its plane
 * (q2tools portals.c FindPortalSide) and drew the hidden one - corrupted/rail1 smeared across a floor, wall1 where
 * the donor shows wall4. Dressed this way, whichever side the compiler picks, the wall is the donor's.
 *
 * Only on a donor whose plain rebuild the oracle refused for what is drawn (the transaction asks for it): q2dm1 has
 * 35 such sides of its own and its plain rebuild already draws the right ones, so it is never dressed.
 */
static void dress_overlapped(mapgen_geometry_t *g, const mapgen_bsp_t *bsp)
{
    const uint32_t num_faces = MapGenBsp_NumFaces(bsp), num_planes = MapGenBsp_NumPlanes(bsp);
    const uint32_t num_texinfo = MapGenBsp_NumTexInfo(bsp);
    for (uint32_t b = 0; b < g->num_brushes; b++) {
        const mapgen_geometry_brush_t *brush = &g->brushes[b];
        if (!(brush->contents & (0x00000001 | 0x00000002)))
            continue;
        for (uint32_t i = 0; i < brush->num_sides; i++) {
            mapgen_geometry_side_t *side = &g->sides[brush->first_side + i];
            if (side->bevel || !side->texture[0] || !side->num_samples)
                continue;
            /* does its own mapping lie on its plane? */
            const float *u = side->axis[0], *v = side->axis[1];
            const float c[3] = { u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0] };
            const float lc = sqrtf(c[0] * c[0] + c[1] * c[1] + c[2] * c[2]);
            const bool lies = lc > 0.0f
                && fabsf(c[0] * side->normal[0] + c[1] * side->normal[1] + c[2] * side->normal[2]) / lc >= 0.2f;

            /* the face the donor draws over most of this side's sample points */
            int32_t hit[MAPGEN_GEOMETRY_FACE_SAMPLES];
            for (uint32_t k = 0; k < side->num_samples; k++)
                hit[k] = -1;
            for (uint32_t f = 0; f < num_faces; f++) {
                const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
                if (face->numedges < 3 || face->planenum >= num_planes || face->texinfo < 0
                    || (uint32_t)face->texinfo >= num_texinfo)
                    continue;
                const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, face->planenum);
                const float sign = face->side ? -1.0f : 1.0f;
                const float n[3] = { pl->normal[0] * sign, pl->normal[1] * sign, pl->normal[2] * sign };
                if (n[0] * side->normal[0] + n[1] * side->normal[1] + n[2] * side->normal[2] < 0.9999f
                    || fabsf(pl->dist * sign - side->dist) > 0.1f)
                    continue;
                for (uint32_t k = 0; k < side->num_samples; k++)
                    if (hit[k] < 0 && bsp_face_holds(bsp, face, n, side->sample[k]))
                        hit[k] = face->texinfo;
            }
            int32_t best = -1;
            uint32_t best_count = 0;
            for (uint32_t k = 0; k < side->num_samples; k++) {
                if (hit[k] < 0)
                    continue;
                uint32_t c = 0;
                for (uint32_t j = 0; j < side->num_samples; j++)
                    if (hit[j] >= 0 && !strcmp(MapGenBsp_TexInfo(bsp, (uint32_t)hit[j])->texture,
                                               MapGenBsp_TexInfo(bsp, (uint32_t)hit[k])->texture))
                        c++;
                if (c > best_count) {
                    best_count = c;
                    best = hit[k];
                }
            }
            const mapgen_bsp_texinfo_t *drawn = best >= 0 ? MapGenBsp_TexInfo(bsp, (uint32_t)best) : NULL;
            if (!drawn || (lies && !strcmp(drawn->texture, side->texture)))
                continue;
            memcpy(side->axis, drawn->axis, sizeof(side->axis));
            memcpy(side->texture, drawn->texture, sizeof(side->texture));
            side->flags = drawn->flags;
            side->value = drawn->value;
            g->faithful_sides++;
        }
    }
}

/*
 * A side whose mapping does not span its own wall (row 404).
 *
 * span = |n . (u x v)| / |u x v|: 1 when the texture lies flat on the wall, 0 when one of its axes runs along the
 * wall's normal and the texture is drawn as one smeared line (the axes gate fails a drawn face under 0.5). q2dm1's
 * two are stacked rock ceilings no face of the donor lies on. A Quake III layout made for Quake II has them on sides its
 * own compiler never drew - cor at x -125 y -550.4: corrupted/wall4 with [ 0 1 0 ] [ 0 0 -1 ] on a wall facing y,
 * one of fourteen brushes stacked on that plane, the other thirteen wearing [ 1 0 0 ] [ 0 0 -1 ] - and the frozen
 * compiler may draw exactly that one (FindPortalSide gives a portal the first side on its plane).
 *
 * Such a side, where the donor draws a face on its wall or is open in front of it, takes in order: the face the donor draws on its plane over
 * it; else the mapping most of the sides of the same texture on the same plane, facing the same way, wear; else the
 * editor's projection (the axis plane nearest the wall, the side's own scale, no offset). Its texture is kept but
 * for the first case. cor: 2 sides of its faithful copy (38 of its plain one), q3t2: 101 (146); q2dm1: none.
 */
static float side_span(const float normal[3], const float axis[2][4])
{
    const float *u = axis[0], *v = axis[1];
    const float c[3] = { u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0] };
    const float lc = sqrtf(c[0] * c[0] + c[1] * c[1] + c[2] * c[2]);
    return lc > 0.0f ? fabsf(c[0] * normal[0] + c[1] * normal[1] + c[2] * normal[2]) / lc : 0.0f;
}

static bool same_wall(const mapgen_geometry_side_t *a, const mapgen_geometry_side_t *b)
{
    return a->normal[0] * b->normal[0] + a->normal[1] * b->normal[1] + a->normal[2] * b->normal[2] >= 0.9999f
        && fabsf(a->dist - b->dist) <= 0.1f;
}

/* Does the donor draw anything on this side's wall, where the side is? A side only part of which is seen is still
   seen: cor's brush 424 at y -550.4 has rock in front of all five of its sample points, and the donor draws its wall
   just past them at x -126 - the frozen compiler drew the side there, smeared. The side's extent is its samples'
   box grown by 16 (they are set in from its corners). q2dm1's two stacked rocks19_1 ceilings at z 256, [ 0 1 0 ]
   [ 0 0 -1 ] on a face looking down, have no face of the donor on their plane and stay as they are. */
static bool side_on_drawn_wall(const mapgen_bsp_t *bsp, const mapgen_geometry_side_t *side)
{
    if (!side->num_samples)
        return false;
    float lo[3], hi[3];
    for (int a = 0; a < 3; a++) {
        lo[a] = hi[a] = side->sample[0][a];
        for (uint32_t k = 1; k < side->num_samples; k++) {
            lo[a] = fminf(lo[a], side->sample[k][a]);
            hi[a] = fmaxf(hi[a], side->sample[k][a]);
        }
        lo[a] -= 16.0f;
        hi[a] += 16.0f;
    }
    const uint32_t num_faces = MapGenBsp_NumFaces(bsp), num_planes = MapGenBsp_NumPlanes(bsp);
    const uint32_t num_surfedges = MapGenBsp_NumSurfEdges(bsp), num_edges = MapGenBsp_NumEdges(bsp);
    const uint32_t num_verts = MapGenBsp_NumVertices(bsp);
    for (uint32_t f = 0; f < num_faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        if (face->numedges < 3 || face->planenum >= num_planes || face->texinfo < 0)
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, face->planenum);
        const float sign = face->side ? -1.0f : 1.0f;
        if (pl->normal[0] * sign * side->normal[0] + pl->normal[1] * sign * side->normal[1]
                + pl->normal[2] * sign * side->normal[2] < 0.9999f
            || fabsf(pl->dist * sign - side->dist) > 0.5f)
            continue;
        float flo[3] = { 1e30f, 1e30f, 1e30f }, fhi[3] = { -1e30f, -1e30f, -1e30f };
        for (int32_t e = 0; e < face->numedges; e++) {
            if ((uint32_t)(face->firstedge + e) >= num_surfedges)
                break;
            const int32_t se = MapGenBsp_SurfEdge(bsp, (uint32_t)(face->firstedge + e));
            const uint32_t index = (uint32_t)(se < 0 ? -se : se);
            if (index >= num_edges)
                break;
            const mapgen_bsp_edge_t *edge = MapGenBsp_Edge(bsp, index);
            const uint32_t vi = se < 0 ? edge->v[1] : edge->v[0];
            if (vi >= num_verts)
                break;
            const float *v = MapGenBsp_Vertex(bsp, vi)->point;
            for (int a = 0; a < 3; a++) {
                flo[a] = fminf(flo[a], v[a]);
                fhi[a] = fmaxf(fhi[a], v[a]);
            }
        }
        bool meets = true;
        for (int a = 0; a < 3 && meets; a++)
            meets = flo[a] <= hi[a] && fhi[a] >= lo[a];
        if (meets)
            return true;
    }
    return false;
}

/* Or does it face open space in the donor - air, water, glass two units out from any of its sample points? q3t2's
   mist brushes (contents 0x40) at x 807 y -43 wear q3t2/c_met5_2 at a span of 0.42 on a wall no face of the donor
   lies on, and the frozen compiler draws them. */
static bool side_faces_open(const mapgen_bsp_t *bsp, const mapgen_geometry_side_t *side)
{
    for (uint32_t k = 0; k < side->num_samples; k++) {
        const float p[3] = { side->sample[k][0] + side->normal[0] * 2.0f, side->sample[k][1] + side->normal[1] * 2.0f,
                             side->sample[k][2] + side->normal[2] * 2.0f };
        if (!(MapGenBsp_PointContents(bsp, p) & 0x00000001))
            return true;
    }
    return false;
}

static void respan_sides(mapgen_geometry_t *g, const mapgen_bsp_t *bsp)
{
    const uint32_t num_faces = MapGenBsp_NumFaces(bsp), num_planes = MapGenBsp_NumPlanes(bsp);
    const uint32_t num_texinfo = MapGenBsp_NumTexInfo(bsp);
    for (uint32_t s = 0; s < g->num_sides; s++) {
        mapgen_geometry_side_t *side = &g->sides[s];
        if (side->bevel || !side->texture[0] || side_span(side->normal, side->axis) >= 0.5f
            || !(side_on_drawn_wall(bsp, side) || side_faces_open(bsp, side)))
            continue;

        /* the face the donor draws on this plane over the side */
        const mapgen_bsp_texinfo_t *drawn = NULL;
        for (uint32_t f = 0; f < num_faces && !drawn; f++) {
            const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
            if (face->numedges < 3 || face->planenum >= num_planes || face->texinfo < 0
                || (uint32_t)face->texinfo >= num_texinfo)
                continue;
            const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, face->planenum);
            const float sign = face->side ? -1.0f : 1.0f;
            const float n[3] = { pl->normal[0] * sign, pl->normal[1] * sign, pl->normal[2] * sign };
            if (n[0] * side->normal[0] + n[1] * side->normal[1] + n[2] * side->normal[2] < 0.9999f
                || fabsf(pl->dist * sign - side->dist) > 0.1f)
                continue;
            const mapgen_bsp_texinfo_t *ti = MapGenBsp_TexInfo(bsp, (uint32_t)face->texinfo);
            if (side_span(side->normal, ti->axis) < 0.5f)
                continue;
            for (uint32_t k = 0; k < side->num_samples; k++)
                if (bsp_face_holds(bsp, face, n, side->sample[k])) {
                    drawn = ti;
                    break;
                }
        }
        if (drawn) {
            memcpy(side->axis, drawn->axis, sizeof(side->axis));
            memcpy(side->texture, drawn->texture, sizeof(side->texture));
            side->flags = drawn->flags;
            side->value = drawn->value;
            g->respanned_sides++;
            continue;
        }

        /* the mapping most of its texture's sides on this plane wear */
        const mapgen_geometry_side_t *best = NULL;
        uint32_t best_count = 0;
        for (uint32_t t = 0; t < g->num_sides; t++) {
            const mapgen_geometry_side_t *o = &g->sides[t];
            if (t == s || o->bevel || strcmp(o->texture, side->texture) || !same_wall(o, side)
                || side_span(o->normal, o->axis) < 0.5f)
                continue;
            uint32_t c = 0;
            for (uint32_t r = 0; r < g->num_sides; r++) {
                const mapgen_geometry_side_t *q = &g->sides[r];
                if (r != s && !q->bevel && !strcmp(q->texture, side->texture) && same_wall(q, side)
                    && !memcmp(q->axis, o->axis, sizeof(q->axis)))
                    c++;
            }
            if (c > best_count) {
                best_count = c;
                best = o;
            }
        }
        if (best) {
            memcpy(side->axis, best->axis, sizeof(side->axis));
            g->respanned_sides++;
            continue;
        }

        /* the editor's projection: the axis plane nearest the wall, the side's own scale */
        static const float base[6][3][3] = {
            { { 0, 0, 1 }, { 1, 0, 0 }, { 0, -1, 0 } }, { { 0, 0, -1 }, { 1, 0, 0 }, { 0, -1, 0 } },
            { { 1, 0, 0 }, { 0, 1, 0 }, { 0, 0, -1 } }, { { -1, 0, 0 }, { 0, 1, 0 }, { 0, 0, -1 } },
            { { 0, 1, 0 }, { 1, 0, 0 }, { 0, 0, -1 } }, { { 0, -1, 0 }, { 1, 0, 0 }, { 0, 0, -1 } },
        };
        int pick = 0;
        float most = -2.0f;
        for (int k = 0; k < 6; k++) {
            const float d = side->normal[0] * base[k][0][0] + side->normal[1] * base[k][0][1]
                          + side->normal[2] * base[k][0][2];
            if (d > most) {
                most = d;
                pick = k;
            }
        }
        for (int a = 0; a < 2; a++) {
            const float *w = side->axis[a];
            float len = sqrtf(w[0] * w[0] + w[1] * w[1] + w[2] * w[2]);
            if (len <= 0.0f)
                len = 1.0f;
            for (int c = 0; c < 3; c++)
                side->axis[a][c] = base[pick][a + 1][c] * len;
            side->axis[a][3] = 0.0f;
        }
        g->respanned_sides++;
    }
}

mapgen_geometry_result_t MapGenGeometry_FromBsp(const mapgen_bsp_t *bsp,
                                                mapgen_geometry_t **out)
{
    return MapGenGeometry_FromBspWith(bsp, 0, out);
}

mapgen_geometry_result_t MapGenGeometry_FromBspWith(const mapgen_bsp_t *bsp, uint32_t flags,
                                                    mapgen_geometry_t **out)
{
    if (out)
        *out = NULL;
    if (!bsp || !out)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    const uint32_t num_brushes = MapGenBsp_NumBrushes(bsp);
    const uint32_t num_sides = MapGenBsp_NumBrushSides(bsp);
    const uint32_t num_models = MapGenBsp_NumModels(bsp);
    const uint32_t num_planes = MapGenBsp_NumPlanes(bsp);
    const uint32_t num_texinfo = MapGenBsp_NumTexInfo(bsp);

    /* Sized before it is trusted. */
    if (num_brushes > MAPGEN_GEOMETRY_MAX_BRUSHES
        || num_sides > MAPGEN_GEOMETRY_MAX_SIDES
        || num_models > MAPGEN_GEOMETRY_MAX_MODELS)
        return MAPGEN_GEOMETRY_ERR_LIMIT;
    if (!num_brushes || !num_models)
        return MAPGEN_GEOMETRY_ERR_UNSUPPORTED;

    mapgen_geometry_t *g = calloc(1, sizeof(*g));
    if (!g)
        return MAPGEN_GEOMETRY_ERR_MEMORY;
    g->num_models = num_models;

    uint32_t *owner = calloc(num_brushes, sizeof(*owner));
    uint8_t *claimed = calloc(num_brushes, sizeof(*claimed));
    g->brushes = calloc(num_brushes, sizeof(*g->brushes));
    g->sides = calloc(num_sides ? num_sides : 1, sizeof(*g->sides));
    g->brush_cap = num_brushes;
    g->side_cap = num_sides;
    if (!owner || !claimed || !g->brushes || !g->sides) {
        free(owner);
        free(claimed);
        MapGenGeometry_Free(g);
        return MAPGEN_GEOMETRY_ERR_MEMORY;
    }

    mapgen_geometry_result_t rc = MAPGEN_GEOMETRY_OK;
    for (uint32_t m = 0; m < num_models && rc == MAPGEN_GEOMETRY_OK; m++) {
        const mapgen_bsp_model_t *model = MapGenBsp_Model(bsp, m);
        rc = mark_owner(bsp, model->headnode, m, owner, claimed);
    }
    if (rc != MAPGEN_GEOMETRY_OK) {
        free(owner);
        free(claimed);
        MapGenGeometry_Free(g);
        return rc;
    }

    winding_t *windings = malloc(MAPGEN_GEOMETRY_MAX_SIDES_PER_BRUSH
                                 * sizeof(*windings));
    if (!windings) {
        free(owner);
        free(claimed);
        MapGenGeometry_Free(g);
        return MAPGEN_GEOMETRY_ERR_MEMORY;
    }

    for (uint32_t b = 0; b < num_brushes; b++) {
        const mapgen_bsp_brush_t *src = MapGenBsp_Brush(bsp, b);
        if (src->numsides <= 0
            || (uint32_t)src->numsides > MAPGEN_GEOMETRY_MAX_SIDES_PER_BRUSH) {
            rc = MAPGEN_GEOMETRY_ERR_LIMIT;
            break;
        }
        const uint32_t count = (uint32_t)src->numsides;
        const uint32_t first = (uint32_t)src->firstside;
        if (first > num_sides || first + count > num_sides) {
            rc = MAPGEN_GEOMETRY_ERR_LIMIT;
            break;
        }

        /* Each side's face is its plane, minus every bite the others take. */
        for (uint32_t s = 0; s < count; s++) {
            const mapgen_bsp_brushside_t *bs = MapGenBsp_BrushSide(bsp, first + s);
            if (bs->planenum >= num_planes) {
                rc = MAPGEN_GEOMETRY_ERR_LIMIT;
                break;
            }
            const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, bs->planenum);
            if (!finite3(pl->normal) || !isfinite(pl->dist)) {
                rc = MAPGEN_GEOMETRY_ERR_NON_FINITE;
                break;
            }
            base_winding(pl->normal, pl->dist, &windings[s]);
            for (uint32_t o = 0; o < count && windings[s].count; o++) {
                if (o == s)
                    continue;
                const mapgen_bsp_brushside_t *ob =
                    MapGenBsp_BrushSide(bsp, first + o);
                if (ob->planenum >= num_planes || ob->planenum == bs->planenum)
                    continue;
                const mapgen_bsp_plane_t *op = MapGenBsp_Plane(bsp, ob->planenum);
                clip_winding(&windings[s], op->normal, op->dist);
            }
        }
        if (rc != MAPGEN_GEOMETRY_OK)
            break;

        mapgen_geometry_brush_t *dst = &g->brushes[g->num_brushes];
        dst->first_side = g->num_sides;
        dst->num_sides = count;
        dst->contents = src->contents;
        dst->model = claimed[b] ? owner[b] : 0;
        if (!claimed[b])
            g->orphan_brushes++;
        for (int a = 0; a < 3; a++) {
            dst->mins[a] = MAPGEN_GEOMETRY_WORLD_EXTENT;
            dst->maxs[a] = -MAPGEN_GEOMETRY_WORLD_EXTENT;
        }

        uint32_t shaped = 0;
        for (uint32_t s = 0; s < count; s++) {
            const mapgen_bsp_brushside_t *bs = MapGenBsp_BrushSide(bsp, first + s);
            const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, bs->planenum);
            mapgen_geometry_side_t *side = &g->sides[g->num_sides + s];

            memcpy(side->normal, pl->normal, sizeof(side->normal));
            side->dist = pl->dist;
            side->bevel = windings[s].count < 3;
            if (!side->bevel)
                shaped++;

            if (bs->texinfo >= 0 && (uint32_t)bs->texinfo < num_texinfo) {
                const mapgen_bsp_texinfo_t *ti =
                    MapGenBsp_TexInfo(bsp, (uint32_t)bs->texinfo);
                memcpy(side->axis, ti->axis, sizeof(side->axis));
                side->flags = ti->flags;
                side->value = ti->value;
                memcpy(side->texture, ti->texture, sizeof(side->texture));
            } else {
                /* A side the compiler added for collision and never textured.
                   It still bounds the solid, so it is kept and given a mapping
                   that cannot stretch: derived from its own plane, never
                   inherited. */
                MapGenGeometry_AxesForNormal(side->axis, side->normal);
                side->texture[0] = '\0';
            }

            for (uint32_t p = 0; p < windings[s].count; p++) {
                for (int a = 0; a < 3; a++) {
                    if (windings[s].p[p][a] < dst->mins[a])
                        dst->mins[a] = windings[s].p[p][a];
                    if (windings[s].p[p][a] > dst->maxs[a])
                        dst->maxs[a] = windings[s].p[p][a];
                }
            }

            /*
             * The face's centroid and area, kept rather than discarded with
             * the winding: an operator asking "is there room beyond this
             * surface" needs somewhere to ask from, and an area-weighted
             * coverage axis needs the area. Both are the fan sum about the
             * first point, which is exact for a convex polygon.
             */
            if (windings[s].count >= 3) {
                double area2 = 0.0;
                double cx = 0.0, cy = 0.0, cz = 0.0;
                for (uint32_t p = 1; p + 1 < windings[s].count; p++) {
                    double e1[3], e2[3], cross[3];
                    for (int a = 0; a < 3; a++) {
                        e1[a] = windings[s].p[p][a] - windings[s].p[0][a];
                        e2[a] = windings[s].p[p + 1][a] - windings[s].p[0][a];
                    }
                    cross[0] = e1[1] * e2[2] - e1[2] * e2[1];
                    cross[1] = e1[2] * e2[0] - e1[0] * e2[2];
                    cross[2] = e1[0] * e2[1] - e1[1] * e2[0];
                    const double tri = sqrt(cross[0] * cross[0]
                                          + cross[1] * cross[1]
                                          + cross[2] * cross[2]);
                    area2 += tri;
                    cx += tri * (windings[s].p[0][0] + windings[s].p[p][0]
                                 + windings[s].p[p + 1][0]) / 3.0;
                    cy += tri * (windings[s].p[0][1] + windings[s].p[p][1]
                                 + windings[s].p[p + 1][1]) / 3.0;
                    cz += tri * (windings[s].p[0][2] + windings[s].p[p][2]
                                 + windings[s].p[p + 1][2]) / 3.0;
                }
                side->area = (float)(area2 * 0.5);
                if (area2 > 0.0) {
                    side->center[0] = (float)(cx / area2);
                    side->center[1] = (float)(cy / area2);
                    side->center[2] = (float)(cz / area2);
                }

                /* The centroid, then halfway out to each corner: inside the
                   face by construction, and spread across all of it. */
                /*
                 * Three widely separated winding points: the first, and the two
                 * furthest from it and from each other. Widely separated
                 * because the compiler derives the plane from a cross product,
                 * and three points huddled together derive it badly.
                 */
                if (windings[s].count >= 3) {
                    uint32_t b = 1, c = 2;
                    double best = -1.0;
                    for (uint32_t i = 1; i < windings[s].count; i++) {
                        for (uint32_t j = i + 1; j < windings[s].count; j++) {
                            double area = 0.0;
                            double e1[3], e2[3], cross[3];
                            for (int a = 0; a < 3; a++) {
                                e1[a] = windings[s].p[i][a] - windings[s].p[0][a];
                                e2[a] = windings[s].p[j][a] - windings[s].p[0][a];
                            }
                            cross[0] = e1[1] * e2[2] - e1[2] * e2[1];
                            cross[1] = e1[2] * e2[0] - e1[0] * e2[2];
                            cross[2] = e1[0] * e2[1] - e1[1] * e2[0];
                            area = cross[0] * cross[0] + cross[1] * cross[1]
                                 + cross[2] * cross[2];
                            if (area > best) {
                                best = area;
                                b = i;
                                c = j;
                            }
                        }
                    }
                    if (best > 0.0) {
                        memcpy(side->anchor[0], windings[s].p[0], 3 * sizeof(float));
                        memcpy(side->anchor[1], windings[s].p[b], 3 * sizeof(float));
                        memcpy(side->anchor[2], windings[s].p[c], 3 * sizeof(float));
                        side->has_anchor = true;
                    }
                }

                side->num_samples = 1;
                memcpy(side->sample[0], side->center, sizeof(side->center));
                const uint32_t step = windings[s].count
                                    / (MAPGEN_GEOMETRY_FACE_SAMPLES - 1) + 1;
                for (uint32_t p = 0; p < windings[s].count
                     && side->num_samples < MAPGEN_GEOMETRY_FACE_SAMPLES;
                     p += step) {
                    for (int a = 0; a < 3; a++) {
                        side->sample[side->num_samples][a] =
                            0.5f * (side->center[a] + windings[s].p[p][a]);
                    }
                    side->num_samples++;
                }
            }
        }

        /* A pile of half-spaces enclosing nothing is not a brush, and writing
           one out would hand the compiler a solid it cannot build. */
        if (!shaped) {
            rc = MAPGEN_GEOMETRY_ERR_DEGENERATE;
            break;
        }

        g->num_sides += count;
        g->num_brushes++;
    }

    free(windings);
    free(owner);
    free(claimed);
    if (rc != MAPGEN_GEOMETRY_OK) {
        MapGenGeometry_Free(g);
        return rc;
    }

    rc = extract_faces(g, bsp);
    if (rc != MAPGEN_GEOMETRY_OK) {
        MapGenGeometry_Free(g);
        return rc;
    }

    dress_untextured(g, bsp);
    if (flags & MAPGEN_GEOMETRY_FAITHFUL_SKINS)
        dress_overlapped(g, bsp);
    respan_sides(g, bsp);

    rc = parse_entities(g, bsp);
    if (rc != MAPGEN_GEOMETRY_OK) {
        MapGenGeometry_Free(g);
        return rc;
    }

    /*
     * Row 410: a brush model with an "origin" (an origin brush in its source - koldduel1's func_rotating at
     * -832 832 496) is stored by the compiler AROUND that origin, its brushes at -56..56; the .map has them where
     * they stand in the world, and the compiler takes the origin off again. Read as stored, the rebuild put the fan
     * at 776..888 -888..-776 -504..-488 and the donor was refused (DIFF_OWNERSHIP, DIFF_ARCHITECTURE). Moved to the
     * world here, the texture with it.
     */
    for (uint32_t e = 0; e < g->num_entities; e++) {
        const mapgen_geometry_entity_t *ent = &g->entities[e];
        if (!ent->model || !ent->has_origin
            || (ent->origin[0] == 0.0f && ent->origin[1] == 0.0f && ent->origin[2] == 0.0f))
            continue;
        uint8_t *mask = calloc(g->num_brushes ? g->num_brushes : 1u, 1);
        uint8_t *none = calloc(g->num_entities, 1);
        if (!mask || !none) {
            free(mask);
            free(none);
            MapGenGeometry_Free(g);
            return MAPGEN_GEOMETRY_ERR_LIMIT;
        }
        bool any = false;
        for (uint32_t b = 0; b < g->num_brushes; b++)
            if (g->brushes[b].model == ent->model)
                mask[b] = 1, any = true;
        const float pivot[3] = { 0.0f, 0.0f, 0.0f };
        if (any)
            MapGenGeometry_TransformSubset(g, mask, none, pivot, 0u, false, ent->origin);
        for (uint32_t b = 0; any && b < g->num_brushes; b++) {
            if (!mask[b])
                continue;
            for (uint32_t s = 0; s < g->brushes[b].num_sides; s++) {
                mapgen_geometry_side_t *side = &g->sides[g->brushes[b].first_side + s];
                for (int a = 0; a < 2; a++)
                    side->axis[a][3] -= side->axis[a][0] * ent->origin[0] + side->axis[a][1] * ent->origin[1]
                                      + side->axis[a][2] * ent->origin[2];
            }
        }
        free(mask);
        free(none);
    }

    *out = g;
    return MAPGEN_GEOMETRY_OK;
}

/*
 * A map with nothing in it yet.
 *
 * The composer needs somewhere to graft the first room INTO, and every other
 * way of getting a geometry starts from a map that already exists. An empty
 * one is not a degenerate case of those: it is what a map that is being made
 * out of pieces begins as.
 */
mapgen_geometry_result_t MapGenGeometry_Empty(mapgen_geometry_t **out)
{
    if (!out)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    *out = calloc(1, sizeof(**out));
    if (!*out)
        return MAPGEN_GEOMETRY_ERR_MEMORY;
    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_Clone(const mapgen_geometry_t *src,
                                              mapgen_geometry_t **out)
{
    if (out)
        *out = NULL;
    if (!src || !out)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    mapgen_geometry_t *g = calloc(1, sizeof(*g));
    if (!g)
        return MAPGEN_GEOMETRY_ERR_MEMORY;

    g->num_brushes = src->num_brushes;
    g->num_sides = src->num_sides;
    g->num_entities = src->num_entities;
    g->num_pairs = src->num_pairs;
    g->pair_cap = src->num_pairs;
    g->text_len = g->text_cap = src->text_len;
    g->num_models = src->num_models;
    g->orphan_brushes = src->orphan_brushes;

    g->brushes = malloc((src->num_brushes ? src->num_brushes : 1) * sizeof(*g->brushes));
    g->sides = malloc((src->num_sides ? src->num_sides : 1) * sizeof(*g->sides));
    g->entities = malloc((src->num_entities ? src->num_entities : 1) * sizeof(*g->entities));
    g->pair_at = malloc((src->num_pairs ? src->num_pairs : 1) * 2 * sizeof(*g->pair_at));
    g->text = malloc(src->text_len ? src->text_len : 1);
    if (!g->brushes || !g->sides || !g->entities || !g->pair_at || !g->text) {
        MapGenGeometry_Free(g);
        return MAPGEN_GEOMETRY_ERR_MEMORY;
    }

    memcpy(g->brushes, src->brushes, src->num_brushes * sizeof(*g->brushes));
    memcpy(g->sides, src->sides, src->num_sides * sizeof(*g->sides));
    memcpy(g->entities, src->entities, src->num_entities * sizeof(*g->entities));
    memcpy(g->pair_at, src->pair_at, (size_t)src->num_pairs * 2 * sizeof(*g->pair_at));
    memcpy(g->text, src->text, src->text_len);

    /*
     * The mesh comes across as the DONOR's, and a candidate that edits its
     * geometry must not be believed about it afterwards: a face table copied
     * from before an edit describes a map that no longer exists. It is carried
     * so that an unedited clone can still be compared, and every consumer is
     * required to re-extract from the compiled candidate instead of trusting
     * this - which is what "compiled truth is the final authority" means.
     */
    g->num_faces = src->num_faces;
    g->num_points = src->num_points;
    if (src->num_faces) {
        g->faces = malloc((size_t)src->num_faces * sizeof(*g->faces));
        g->points = malloc((size_t)src->num_points * 3 * sizeof(*g->points) + 3);
        if (!g->faces || !g->points) {
            MapGenGeometry_Free(g);
            return MAPGEN_GEOMETRY_ERR_MEMORY;
        }
        memcpy(g->faces, src->faces, (size_t)src->num_faces * sizeof(*g->faces));
        memcpy(g->points, src->points,
               (size_t)src->num_points * 3 * sizeof(*g->points));
    }
    g->brush_cap = src->num_brushes;
    g->side_cap = src->num_sides;
    g->entity_cap = src->num_entities;

    *out = g;
    return MAPGEN_GEOMETRY_OK;
}

void MapGenGeometry_Free(mapgen_geometry_t *g)
{
    if (!g)
        return;
    free(g->brushes);
    free(g->sides);
    free(g->entities);
    free(g->pair_at);
    free(g->text);
    free(g->faces);
    free(g->points);
    free(g);
}

uint32_t MapGenGeometry_NumBrushes(const mapgen_geometry_t *g)
{
    return g ? g->num_brushes : 0;
}

uint32_t MapGenGeometry_NumSides(const mapgen_geometry_t *g)
{
    return g ? g->num_sides : 0;
}

uint32_t MapGenGeometry_NumModels(const mapgen_geometry_t *g)
{
    return g ? g->num_models : 0;
}

uint32_t MapGenGeometry_NumEntities(const mapgen_geometry_t *g)
{
    return g ? g->num_entities : 0;
}

uint32_t MapGenGeometry_NumFaces(const mapgen_geometry_t *g)
{
    return g ? g->num_faces : 0;
}

/* ---- surfaces a compiler cannot build ------------------------------------- */

/*
 * Two faces are on the same plane when they face the same way from the same
 * distance. The tolerances are the writer's: a .map states a plane as three
 * integer points, so anything finer than this cannot survive the round trip
 * and anything coarser would call two different walls one wall.
 */
#define SAME_NORMAL   0.001f
#define SAME_DIST     0.05f
#define ON_EDGE       0.10f
#define OFF_CORNER    0.50f
#define FACE_MIN_AREA 0.10f

typedef struct {
    uint32_t brush;
    uint32_t first, count;      /* into the shared point pool */
    float    normal[3];
    float    dist;
} flat_face_t;

static bool same_plane(const flat_face_t *a, const flat_face_t *b)
{
    return fabsf(a->normal[0] - b->normal[0]) <= SAME_NORMAL
        && fabsf(a->normal[1] - b->normal[1]) <= SAME_NORMAL
        && fabsf(a->normal[2] - b->normal[2]) <= SAME_NORMAL
        && fabsf(a->dist - b->dist) <= SAME_DIST;
}

/*
 * Does this point sit in the middle of that edge?
 *
 * Not at either end - a shared corner is how two faces are SUPPOSED to meet -
 * and near enough to the line that the compiler will put a vertex of one face
 * where the other face has none. That is the T.
 */
static bool splits_edge(const double p[3], const double a[3], const double b[3])
{
    double ab[3], ap[3];
    for (int i = 0; i < 3; i++) {
        ab[i] = b[i] - a[i];
        ap[i] = p[i] - a[i];
    }
    const double len2 = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2];
    if (len2 <= 0.0)
        return false;
    const double t = (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / len2;
    const double len = sqrt(len2);
    if (t * len <= OFF_CORNER || (1.0 - t) * len <= OFF_CORNER)
        return false;

    double off = 0.0;
    for (int i = 0; i < 3; i++) {
        const double d = ap[i] - t * ab[i];
        off += d * d;
    }
    return sqrt(off) <= ON_EDGE;
}

/*
 * Could anybody stand in front of this face?
 *
 * A step off the plane along its own normal, asked of the compiled map: inside
 * a wall reads solid, and so does the void outside the hull, which is the
 * answer that matters here - the outside of a sealed box is not a place.
 */
/* The same bit the collision hull uses; a leaf outside the map has it too. */
#define CONTENTS_SOLID_BIT  0x00000001

/*
 * Is this brush one a player swims in?
 *
 * The three liquid contents of Quake II. MIST is not among them: it is drawn
 * like a liquid and it is not one, and a brush of fog with a T-junction in it
 * shows the same hairline any other translucent surface would.
 */
#define LIQUID_CONTENTS (MAPGEN_CONTENTS_LAVA | MAPGEN_CONTENTS_SLIME | MAPGEN_CONTENTS_WATER)

static bool liquid_brush(const mapgen_geometry_t *g, uint32_t brush)
{
    return brush < g->num_brushes
        && (g->brushes[brush].contents & LIQUID_CONTENTS) != 0
        && !(g->brushes[brush].contents & CONTENTS_SOLID_BIT);
}

static bool anyone_can_see(const mapgen_bsp_t *space, const double at[3],
                           const float normal[3])
{
    if (!space)
        return true;
    const float off[3] = { (float)at[0] + normal[0] * 2.0f,
                           (float)at[1] + normal[1] * 2.0f,
                           (float)at[2] + normal[2] * 2.0f };
    return !(MapGenBsp_PointContents(space, off) & CONTENTS_SOLID_BIT);
}

/*
 * The texture axes a face gets when nobody measured them on it.
 *
 * A Quake II surface maps texture coordinates as s = p.u + su, t = p.v + sv:
 * a projection of the face along (u x v). The two axes therefore have to
 * SPAN the face - if either of them is parallel to the face's own normal the
 * projection is edge-on, one texel column is smeared across the whole
 * surface, and what the map draws is the streak the PO photographed on
 * 2026-09-10 and called "как будто ножом разрезали".
 *
 * That is exactly what inheriting a neighbour's axes does. `add_clipped`
 * gave a cut face the SKIN side's mapping and swapped only the normal, so on
 * q2dm1 - where the skin a wall offers is x-facing - every +-y and +-z face
 * of every hollow came out with u = (0,1,0), v = (0,0,-1) and drew as
 * streaks: 88, 86 and 62 such faces in the three F90 forks of 2026-09-10 and
 * 50 in the 93-permille map, against 0 in the donor and 0 in the accepted
 * set.
 *
 * The rule is the one a level editor uses for a new face: the dominant axis
 * of the normal decides which two world axes span it. Unit length, no shift
 * - the face is new, so there is no alignment to preserve. It was written
 * three times in three modules before this (the writer of replacements, the
 * composer, and the loader's fallback for a side the compiler never
 * textured); this is that rule, once, so that a fourth caller cannot get it
 * wrong by not knowing it existed.
 */
void MapGenGeometry_AxesForNormal(float axis[2][4], const float normal[3])
{
    if (!axis || !normal)
        return;
    for (int a = 0; a < 2; a++)
        for (int k = 0; k < 4; k++)
            axis[a][k] = 0.0f;
    const float ax = fabsf(normal[0]);
    const float ay = fabsf(normal[1]);
    const float az = fabsf(normal[2]);
    if (az >= ax && az >= ay) {
        /* floor or ceiling: x across, y down the texture */
        axis[0][0] = 1.0f;
        axis[1][1] = -1.0f;
    } else if (ax >= ay) {
        /* a wall facing along x: y across, z down */
        axis[0][1] = 1.0f;
        axis[1][2] = -1.0f;
    } else {
        /* a wall facing along y: x across, z down */
        axis[0][0] = 1.0f;
        axis[1][2] = -1.0f;
    }
}

bool MapGenGeometry_TextureIsMaterial(const char *texture)
{
    if (!texture || !texture[0])
        return false;
    static const char *const FORBIDDEN[] = {
        "clip", "hint", "skip", "nodraw", "trigger", "origin", "sky",
        "wter", "water", "lava", "slime", "fog", "caulk"
    };
    char lower[MAPGEN_BSP_TEXNAME + 1];
    size_t n = 0;
    for (; texture[n] && n < sizeof(lower) - 1; n++)
        lower[n] = (char)((texture[n] >= 'A' && texture[n] <= 'Z')
                          ? texture[n] - 'A' + 'a' : texture[n]);
    lower[n] = '\0';
    if (lower[0] == '*' || lower[0] == '!')
        return false;
    for (size_t i = 0; i < sizeof(FORBIDDEN) / sizeof(FORBIDDEN[0]); i++)
        if (strstr(lower, FORBIDDEN[i]))
            return false;
    return true;
}

/* Is this point inside a liquid brush of this geometry? */
static bool in_liquid(const mapgen_geometry_t *g, const float p[3])
{
    for (uint32_t b = 0; b < g->num_brushes; b++) {
        const mapgen_geometry_brush_t *br = &g->brushes[b];
        if (!(br->contents & (MAPGEN_CONTENTS_WATER | MAPGEN_CONTENTS_LAVA
                              | MAPGEN_CONTENTS_SLIME)))
            continue;
        if (p[0] < br->mins[0] || p[0] > br->maxs[0]
            || p[1] < br->mins[1] || p[1] > br->maxs[1]
            || p[2] < br->mins[2] || p[2] > br->maxs[2])
            continue;
        bool inside = true;
        for (uint32_t s = 0; s < br->num_sides && inside; s++) {
            const mapgen_geometry_side_t *side = &g->sides[br->first_side + s];
            if (side->bevel)
                continue;
            const float d = side->normal[0] * p[0] + side->normal[1] * p[1]
                          + side->normal[2] * p[2] - side->dist;
            if (d > 0.03125f)
                inside = false;
        }
        if (inside)
            return true;
    }
    return false;
}

uint32_t MapGenGeometry_DrownedEntities(const mapgen_geometry_t *g,
                                        bool spawns_only,
                                        char *out_first, size_t capacity)
{
    if (out_first && capacity)
        out_first[0] = '\0';
    if (!g)
        return 0;
    uint32_t drowned = 0;
    for (uint32_t e = 0; e < g->num_entities; e++) {
        const mapgen_geometry_entity_t *ent = &g->entities[e];
        if (!ent->has_origin)
            continue;
        const char *cls = MapGenGeometry_EntityValue(g, e, "classname");
        if (!cls)
            continue;
        const bool spawn = !strncmp(cls, "info_player", 11);
        const bool pickup = !strncmp(cls, "item_", 5)
                         || !strncmp(cls, "weapon_", 7)
                         || !strncmp(cls, "ammo_", 5);
        if (!spawn && !(pickup && !spawns_only))
            continue;
        /* His feet, and where his eyes would be. */
        const float feet[3] = { ent->origin[0], ent->origin[1],
                                ent->origin[2] + 1.0f };
        const float eye[3] = { ent->origin[0], ent->origin[1],
                               ent->origin[2] + 40.0f };
        if (!in_liquid(g, feet) && !in_liquid(g, eye))
            continue;
        if (out_first && capacity && !out_first[0])
            snprintf(out_first, capacity, "%s at %.0f %.0f %.0f", cls,
                     ent->origin[0], ent->origin[1], ent->origin[2]);
        drowned++;
    }
    return drowned;
}

uint32_t MapGenGeometry_SurfaceFaults(const mapgen_geometry_t *g,
                                      const mapgen_bsp_t *space)
{
    if (!g || !g->num_brushes)
        return 0;

    flat_face_t *faces = calloc(g->num_sides ? g->num_sides : 1, sizeof(*faces));
    double *pool = calloc((size_t)(g->num_sides ? g->num_sides : 1)
                          * WINDING_MAX_POINTS * 3, sizeof(*pool));
    winding_t *w = malloc(sizeof(*w));
    if (!faces || !pool || !w) {
        free(faces);
        free(pool);
        free(w);
        return 0;
    }

    uint32_t faults = 0, num_faces = 0, used = 0;

    for (uint32_t b = 0; b < g->num_brushes; b++) {
        const mapgen_geometry_brush_t *brush = &g->brushes[b];
        const mapgen_geometry_side_t *sides = &g->sides[brush->first_side];
        uint32_t shaped = 0;

        for (uint32_t s = 0; s < brush->num_sides; s++) {
            base_winding(sides[s].normal, sides[s].dist, w);
            for (uint32_t o = 0; o < brush->num_sides && w->count; o++) {
                if (o == s)
                    continue;
                clip_winding(w, sides[o].normal, sides[o].dist);
            }
            if (w->count < 3) {
                /*
                 * A side with nothing left of it is a bevel, which is normal
                 * and kept; only a side the donor itself called a face and
                 * which an edit has since cut away is a fault.
                 */
                if (!sides[s].bevel)
                    faults++;
                continue;
            }

            double area2 = 0.0;
            for (uint32_t p = 1; p + 1 < w->count; p++) {
                double e1[3], e2[3], cross[3];
                for (int a = 0; a < 3; a++) {
                    e1[a] = w->p[p][a] - w->p[0][a];
                    e2[a] = w->p[p + 1][a] - w->p[0][a];
                }
                cross[0] = e1[1] * e2[2] - e1[2] * e2[1];
                cross[1] = e1[2] * e2[0] - e1[0] * e2[2];
                cross[2] = e1[0] * e2[1] - e1[1] * e2[0];
                area2 += sqrt(cross[0] * cross[0] + cross[1] * cross[1]
                              + cross[2] * cross[2]);
            }
            if (area2 * 0.5 < FACE_MIN_AREA) {
                faults++;
                continue;
            }
            shaped++;

            if (num_faces >= g->num_sides)
                continue;
            flat_face_t *f = &faces[num_faces++];
            f->brush = b;
            f->count = w->count;
            f->first = used;
            memcpy(f->normal, sides[s].normal, sizeof(f->normal));
            f->dist = sides[s].dist;
            for (uint32_t p = 0; p < w->count; p++)
                for (int a = 0; a < 3; a++)
                    pool[(size_t)(used + p) * 3 + a] = w->p[p][a];
            used += w->count;
        }

        /* Planes that enclose nothing are not a brush at all. */
        if (!shaped && brush->num_sides)
            faults++;
    }

    /*
     * And the seams between them.
     *
     * Only faces of DIFFERENT brushes on the same plane can leave one: within
     * one convex solid every side meets its neighbours at a shared edge by
     * construction.
     */
    for (uint32_t i = 0; i < num_faces; i++) {
        for (uint32_t j = i + 1; j < num_faces; j++) {
            if (faces[i].brush == faces[j].brush || !same_plane(&faces[i],
                                                                &faces[j]))
                continue;
            /*
             * Between two LIQUIDS there is no seam to see.
             *
             * What this rule is about is a hairline: the compiler puts a
             * vertex on one side of a shared plane and none on the other, the
             * two faces disagree about where their surfaces are by a fraction
             * of a unit, and the crack between them sparkles. That is an
             * argument about OPAQUE faces, which are drawn once, in front of
             * whatever is behind them.
             *
             * A water surface is drawn translucent over the room it stands
             * in, and where two of them are coplanar they are the same
             * surface at the same height with the same texture: a vertex in
             * the middle of the neighbour's edge changes nothing anybody can
             * see, because there is nothing behind it to show through.
             *
             * MEASURED, and this is why the rule is here: a pool raised by
             * the relevel emits a TILING of the flooded region - fifty-nine
             * boxes over one room of q2dm1 - and a tiling of an irregular
             * room is made of nothing but corners in the middles of edges.
             * 103 of them, against a donor's own 892, so every flood ever
             * planned was refused and the PO's forks came out with no water
             * moved at all. The liquid contract is
             * `check_mapgen_standing_water.py`, which asks the question that
             * can actually be seen - is there a VERTICAL face of liquid, is
             * there liquid standing in the air - and it is exact.
             *
             * Opaque against opaque, and opaque against liquid, still count.
             */
            if (liquid_brush(g, faces[i].brush)
                && liquid_brush(g, faces[j].brush))
                continue;
            bool split = false;
            for (int way = 0; way < 2 && !split; way++) {
                const flat_face_t *pt = way ? &faces[j] : &faces[i];
                const flat_face_t *ed = way ? &faces[i] : &faces[j];
                for (uint32_t p = 0; p < pt->count && !split; p++) {
                    const double *v = &pool[(size_t)(pt->first + p) * 3];
                    for (uint32_t e = 0; e < ed->count && !split; e++) {
                        const double *a = &pool[(size_t)(ed->first + e) * 3];
                        const double *b2 =
                            &pool[(size_t)(ed->first + (e + 1) % ed->count) * 3];
                        /* Both faces are on one plane facing one way, so where
                           the vertex splits the edge is where the crack is and
                           one look off it answers for both. */
                        split = splits_edge(v, a, b2)
                             && anyone_can_see(space, v, pt->normal);
                    }
                }
            }
            if (split)
                faults++;
        }
    }

    free(faces);
    free(pool);
    free(w);
    return faults;
}

const mapgen_geometry_face_t *MapGenGeometry_Face(const mapgen_geometry_t *g,
                                                  uint32_t i)
{
    return g && i < g->num_faces ? &g->faces[i] : NULL;
}

uint32_t MapGenGeometry_DressedSides(const mapgen_geometry_t *g)
{
    return g ? g->dressed_sides : 0;
}

uint32_t MapGenGeometry_FaithfulSides(const mapgen_geometry_t *g)
{
    return g ? g->faithful_sides : 0;
}

uint32_t MapGenGeometry_RespannedSides(const mapgen_geometry_t *g)
{
    return g ? g->respanned_sides : 0;
}

const float *MapGenGeometry_FacePoint(const mapgen_geometry_t *g, uint32_t i)
{
    return g && i < g->num_points ? &g->points[i * 3] : NULL;
}

const mapgen_geometry_brush_t *MapGenGeometry_Brush(const mapgen_geometry_t *g,
                                                    uint32_t i)
{
    return g && i < g->num_brushes ? &g->brushes[i] : NULL;
}

const mapgen_geometry_side_t *MapGenGeometry_Side(const mapgen_geometry_t *g,
                                                  uint32_t i)
{
    return g && i < g->num_sides ? &g->sides[i] : NULL;
}

const mapgen_geometry_entity_t *MapGenGeometry_Entity(const mapgen_geometry_t *g,
                                                      uint32_t i)
{
    return g && i < g->num_entities ? &g->entities[i] : NULL;
}

void MapGenGeometry_Pair(const mapgen_geometry_t *g, uint32_t pair,
                         const char **key, const char **value)
{
    if (key)
        *key = NULL;
    if (value)
        *value = NULL;
    if (!g || pair >= g->num_pairs)
        return;
    if (key)
        *key = g->text + g->pair_at[pair * 2];
    if (value)
        *value = g->text + g->pair_at[pair * 2 + 1];
}

const char *MapGenGeometry_EntityValue(const mapgen_geometry_t *g,
                                       uint32_t entity, const char *key)
{
    const mapgen_geometry_entity_t *e = MapGenGeometry_Entity(g, entity);
    if (!e || !key)
        return NULL;
    for (uint32_t i = 0; i < e->num_pairs; i++) {
        const char *k, *v;
        MapGenGeometry_Pair(g, e->first_pair + i, &k, &v);
        if (k && !strcmp(k, key))
            return v;
    }
    return NULL;
}

/* ---- the rigid transform --------------------------------------------------- */

/* Row 412: a turned and moved brush keeps its texture where it lay (TransformSubset); the room-cut guard's RED
   takes it out. */
static const bool g_texture_lock = true;

static void rotate_xy(float v[3], uint32_t quarter_turns, bool mirror_x)
{
    for (uint32_t t = 0; t < quarter_turns; t++) {
        const float x = v[0], y = v[1];
        v[0] = -y;
        v[1] = x;
    }
    if (mirror_x)
        v[0] = -v[0];
}

/*
 * An angle in degrees, turned by the same quarter turns and mirror.
 *
 * Quake II writes a facing as one number, and two of its values are not
 * facings at all: -1 means up and -2 means down, and turning those is how a
 * door that rises becomes a door that opens sideways.
 */
static float turn_angle(float degrees, uint32_t quarter_turns, bool mirror_x)
{
    if (degrees == -1.0f || degrees == -2.0f)
        return degrees;
    float turned = degrees + 90.0f * (float)quarter_turns;
    if (mirror_x)
        turned = 180.0f - turned;
    while (turned < 0.0f)
        turned += 360.0f;
    while (turned >= 360.0f)
        turned -= 360.0f;
    return turned;
}

/*
 * An entity that moved has to SAY it moved.
 *
 * The writer emits an entity's key/values verbatim, so moving the parsed
 * `origin` and leaving the "origin" pair alone produces a map in which the
 * entity has not moved at all. MEASURED: an ammo_rockets carried from q2dm3
 * room 17 into q2dm1 arrived at its old q2dm3 coordinates, outside q2dm1
 * altogether, and the compile came back "**** leaked ****" naming that entity
 * in the leak file - an entity outside the sealed map IS a leak.
 *
 * The facing keys were already written back this way; the position was not,
 * which meant every operator that moved a room - swap, recompose and graft
 * alike - moved its walls and left its items where they were.
 */
static void write_origin(mapgen_geometry_t *g, uint32_t entity)
{
    char text[96];
    const float *o = g->entities[entity].origin;
    snprintf(text, sizeof(text), "%g %g %g", (double)o[0], (double)o[1],
             (double)o[2]);
    MapGenGeometry_SetEntityValue(g, entity, "origin", text);
}

bool MapGenGeometry_PointInLiquid(const mapgen_geometry_t *g,
                                  const float point[3])
{
    return g && point && in_liquid(g, point);
}

bool MapGenGeometry_ModelsIntact(const mapgen_geometry_t *donor,
                                 const mapgen_geometry_t *candidate)
{
    if (!donor || !candidate)
        return false;

    for (uint32_t m = 1; m < donor->num_models; m++) {
        uint32_t had = 0, has = 0;
        float was_lo[3] = { 0, 0, 0 }, was_hi[3] = { 0, 0, 0 };
        float now_lo[3] = { 0, 0, 0 }, now_hi[3] = { 0, 0, 0 };

        for (uint32_t b = 0; b < donor->num_brushes; b++) {
            const mapgen_geometry_brush_t *br = &donor->brushes[b];
            if (br->model != m)
                continue;
            for (int a = 0; a < 3; a++) {
                if (!had || br->mins[a] < was_lo[a])
                    was_lo[a] = br->mins[a];
                if (!had || br->maxs[a] > was_hi[a])
                    was_hi[a] = br->maxs[a];
            }
            had++;
        }
        if (!had)
            continue;               /* nothing to keep */

        for (uint32_t b = 0; b < candidate->num_brushes; b++) {
            const mapgen_geometry_brush_t *br = &candidate->brushes[b];
            if (br->model != m)
                continue;
            for (int a = 0; a < 3; a++) {
                if (!has || br->mins[a] < now_lo[a])
                    now_lo[a] = br->mins[a];
                if (!has || br->maxs[a] > now_hi[a])
                    now_hi[a] = br->maxs[a];
            }
            has++;
        }

        if (has < had)
            return false;
        for (int a = 0; a < 3; a++)
            if (now_lo[a] > was_lo[a] + 0.1f || now_hi[a] < was_hi[a] - 0.1f)
                return false;
    }
    return true;
}

mapgen_geometry_result_t MapGenGeometry_MoveEntity(mapgen_geometry_t *g,
                                                   uint32_t entity,
                                                   const float origin[3])
{
    if (!g || entity >= g->num_entities || !origin)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    memcpy(g->entities[entity].origin, origin, sizeof(float) * 3);
    g->entities[entity].has_origin = true;
    write_origin(g, entity);
    return MAPGEN_GEOMETRY_OK;
}

/* The keys that carry a facing, and how many numbers each of them holds. */
static void turn_entity_angles(mapgen_geometry_t *g, uint32_t entity,
                               uint32_t quarter_turns, bool mirror_x)
{
    const char *one = MapGenGeometry_EntityValue(g, entity, "angle");
    if (one && *one) {
        char text[32];
        snprintf(text, sizeof(text), "%g",
                 (double)turn_angle((float)atof(one), quarter_turns,
                                    mirror_x));
        MapGenGeometry_SetEntityValue(g, entity, "angle", text);
    }

    const char *three = MapGenGeometry_EntityValue(g, entity, "angles");
    if (three && *three) {
        float pitch = 0, yaw = 0, roll = 0;
        if (sscanf(three, "%f %f %f", &pitch, &yaw, &roll) == 3) {
            char text[96];
            snprintf(text, sizeof(text), "%g %g %g", (double)pitch,
                     (double)turn_angle(yaw, quarter_turns, mirror_x),
                     (double)roll);
            MapGenGeometry_SetEntityValue(g, entity, "angles", text);
        }
    }
}

mapgen_geometry_result_t MapGenGeometry_TransformSubset(
    mapgen_geometry_t *g, const uint8_t *brush_mask,
    const uint8_t *entity_mask, const float pivot[3],
    uint32_t quarter_turns, bool mirror_x, const float offset[3])
{
    if (!g || !offset || !pivot || quarter_turns > 3)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    if (!finite3(offset) || !finite3(pivot))
        return MAPGEN_GEOMETRY_ERR_NON_FINITE;

    for (uint32_t b = 0; b < g->num_brushes; b++) {
        if (brush_mask && !brush_mask[b])
            continue;
        mapgen_geometry_brush_t *brush = &g->brushes[b];

        for (uint32_t s = 0; s < brush->num_sides; s++) {
            mapgen_geometry_side_t *side = &g->sides[brush->first_side + s];
            /*
             * A plane turned about a pivot: turn its normal, then put the
             * distance back where the pivot says it belongs. Doing it as
             * "translate to the origin, turn, translate back" on the distance
             * alone is the same arithmetic written twice, and it is the part
             * that is easy to get subtly wrong.
             */
            float on_plane[3];
            for (int a = 0; a < 3; a++)
                on_plane[a] = side->normal[a] * side->dist - pivot[a];
            rotate_xy(side->normal, quarter_turns, mirror_x);
            rotate_xy(on_plane, quarter_turns, mirror_x);
            side->dist = side->normal[0] * (on_plane[0] + pivot[0] + offset[0])
                       + side->normal[1] * (on_plane[1] + pivot[1] + offset[1])
                       + side->normal[2] * (on_plane[2] + pivot[2] + offset[2]);

            for (int a = 0; a < 2; a++) {
                const float was[3] = { side->axis[a][0], side->axis[a][1],
                                       side->axis[a][2] };
                float axis[3] = { was[0], was[1], was[2] };
                rotate_xy(axis, quarter_turns, mirror_x);
                side->axis[a][0] = axis[0];
                side->axis[a][1] = axis[1];
                side->axis[a][2] = axis[2];
                /*
                 * Row 412 (the PO on mg_10_45e, «ты сломал фонарь»): the texture stays where it lay on the brush.
                 * A point's texture coordinate is p . v + off; the point moves to R(p - pivot) + pivot + offset and v
                 * turns to R v, so off becomes off + pivot . v - (pivot + offset) . R v. Without it a copy kept the
                 * source's offset - a tiling wall hides that, a picture does not: q3t2's torch flame, one image across
                 * its two crossed brushes, showed scraps of the image at its edges in a tunnel of mg_10_45e.
                 */
                if (g_texture_lock)
                    side->axis[a][3] += was[0] * pivot[0] + was[1] * pivot[1] + was[2] * pivot[2]
                                      - axis[0] * (pivot[0] + offset[0]) - axis[1] * (pivot[1] + offset[1])
                                      - axis[2] * (pivot[2] + offset[2]);
            }

            float centre[3];
            for (int a = 0; a < 3; a++)
                centre[a] = side->center[a] - pivot[a];
            rotate_xy(centre, quarter_turns, mirror_x);
            for (int a = 0; a < 3; a++)
                side->center[a] = centre[a] + pivot[a] + offset[a];

            for (uint8_t k = 0; k < side->num_samples; k++) {
                float sample[3];
                for (int a = 0; a < 3; a++)
                    sample[a] = side->sample[k][a] - pivot[a];
                rotate_xy(sample, quarter_turns, mirror_x);
                for (int a = 0; a < 3; a++)
                    side->sample[k][a] = sample[a] + pivot[a] + offset[a];
            }
            if (side->has_anchor)
                for (int k = 0; k < 3; k++) {
                    float anchor[3];
                    for (int a = 0; a < 3; a++)
                        anchor[a] = side->anchor[k][a] - pivot[a];
                    rotate_xy(anchor, quarter_turns, mirror_x);
                    for (int a = 0; a < 3; a++)
                        side->anchor[k][a] = anchor[a] + pivot[a] + offset[a];
                }
        }

        float lo[3], hi[3];
        for (int a = 0; a < 3; a++) {
            lo[a] = brush->mins[a] - pivot[a];
            hi[a] = brush->maxs[a] - pivot[a];
        }
        rotate_xy(lo, quarter_turns, mirror_x);
        rotate_xy(hi, quarter_turns, mirror_x);
        for (int a = 0; a < 3; a++) {
            const float x = lo[a] < hi[a] ? lo[a] : hi[a];
            const float y = lo[a] > hi[a] ? lo[a] : hi[a];
            brush->mins[a] = x + pivot[a] + offset[a];
            brush->maxs[a] = y + pivot[a] + offset[a];
        }
    }

    for (uint32_t e = 0; e < g->num_entities; e++) {
        if (entity_mask && !entity_mask[e])
            continue;
        if (g->entities[e].has_origin) {
            float origin[3];
            for (int a = 0; a < 3; a++)
                origin[a] = g->entities[e].origin[a] - pivot[a];
            rotate_xy(origin, quarter_turns, mirror_x);
            for (int a = 0; a < 3; a++)
                g->entities[e].origin[a] = origin[a] + pivot[a] + offset[a];
            write_origin(g, e);
        }
        /* And what it is FACING, which the whole-map transform never carried:
           a rotated map whose doors keep their old angle is a map whose doors
           open into the wall. */
        turn_entity_angles(g, e, quarter_turns, mirror_x);
    }

    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_Transform(mapgen_geometry_t *g,
                                                  uint32_t quarter_turns,
                                                  bool mirror_x,
                                                  const float offset[3])
{
    if (!g || !offset || quarter_turns > 3)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    if (!finite3(offset))
        return MAPGEN_GEOMETRY_ERR_NON_FINITE;

    for (uint32_t s = 0; s < g->num_sides; s++) {
        mapgen_geometry_side_t *side = &g->sides[s];
        rotate_xy(side->normal, quarter_turns, mirror_x);
        side->dist += side->normal[0] * offset[0] + side->normal[1] * offset[1]
                    + side->normal[2] * offset[2];

        /*
         * The texture goes with the surface. Rotate the axes and then pull the
         * offset back by what the translation added, or the map turns and the
         * texture on it does not.
         */
        for (int a = 0; a < 2; a++) {
            rotate_xy(side->axis[a], quarter_turns, mirror_x);
            side->axis[a][3] -= side->axis[a][0] * offset[0]
                              + side->axis[a][1] * offset[1]
                              + side->axis[a][2] * offset[2];
        }
    }

    for (uint32_t b = 0; b < g->num_brushes; b++) {
        mapgen_geometry_brush_t *brush = &g->brushes[b];
        float lo[3], hi[3];
        memcpy(lo, brush->mins, sizeof(lo));
        memcpy(hi, brush->maxs, sizeof(hi));
        rotate_xy(lo, quarter_turns, mirror_x);
        rotate_xy(hi, quarter_turns, mirror_x);
        for (int a = 0; a < 3; a++) {
            brush->mins[a] = (lo[a] < hi[a] ? lo[a] : hi[a]) + offset[a];
            brush->maxs[a] = (lo[a] > hi[a] ? lo[a] : hi[a]) + offset[a];
        }
    }

    for (uint32_t e = 0; e < g->num_entities; e++) {
        if (!g->entities[e].has_origin)
            continue;
        rotate_xy(g->entities[e].origin, quarter_turns, mirror_x);
        for (int a = 0; a < 3; a++)
            g->entities[e].origin[a] += offset[a];
        write_origin(g, e);
    }

    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_AddBrush(mapgen_geometry_t *g,
                                                 const mapgen_geometry_side_t *sides,
                                                 uint32_t num_sides,
                                                 int32_t contents,
                                                 uint32_t model)
{
    if (!g || !sides || num_sides < 4
        || num_sides > MAPGEN_GEOMETRY_MAX_SIDES_PER_BRUSH)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    mapgen_geometry_side_t *shaped =
        malloc((size_t)num_sides * sizeof(*shaped));
    if (!shaped)
        return MAPGEN_GEOMETRY_ERR_MEMORY;
    memcpy(shaped, sides, (size_t)num_sides * sizeof(*shaped));

    float mins[3], maxs[3];
    if (!shape_brush(shaped, num_sides, mins, maxs)) {
        free(shaped);
        return MAPGEN_GEOMETRY_ERR_DEGENERATE;
    }

    if (g->num_brushes == g->brush_cap) {
        const uint32_t want = g->brush_cap ? g->brush_cap * 2 : 64;
        mapgen_geometry_brush_t *grown =
            realloc(g->brushes, (size_t)want * sizeof(*grown));
        if (!grown) {
            free(shaped);
            return MAPGEN_GEOMETRY_ERR_MEMORY;
        }
        g->brushes = grown;
        g->brush_cap = want;
    }
    if (g->num_sides + num_sides > g->side_cap) {
        uint32_t want = g->side_cap ? g->side_cap : 64;
        while (want < g->num_sides + num_sides)
            want *= 2;
        mapgen_geometry_side_t *grown =
            realloc(g->sides, (size_t)want * sizeof(*grown));
        if (!grown) {
            free(shaped);
            return MAPGEN_GEOMETRY_ERR_MEMORY;
        }
        g->sides = grown;
        g->side_cap = want;
    }

    mapgen_geometry_brush_t *brush = &g->brushes[g->num_brushes++];
    brush->first_side = g->num_sides;
    brush->num_sides = num_sides;
    brush->contents = contents;
    brush->model = model;
    memcpy(brush->mins, mins, sizeof(brush->mins));
    memcpy(brush->maxs, maxs, sizeof(brush->maxs));

    memcpy(&g->sides[g->num_sides], shaped,
           (size_t)num_sides * sizeof(*g->sides));
    g->num_sides += num_sides;

    free(shaped);
    return MAPGEN_GEOMETRY_OK;
}

/*
 * Bring a subset of another map's geometry into this one.
 *
 * The transform is not written again here: the source is cloned, the clone is
 * put through `MapGenGeometry_TransformSubset` - which is where turning a plane
 * about a pivot, carrying its texture axes and moving its samples already lives
 * and is already proven - and then the masked brushes and entities are copied
 * across. A second spelling of that arithmetic is how two operators come to
 * disagree about where a room ended up.
 */
mapgen_geometry_result_t MapGenGeometry_Graft(
    mapgen_geometry_t *dst, const mapgen_geometry_t *src,
    const uint8_t *brush_mask, const uint8_t *entity_mask,
    const float pivot[3], uint32_t quarter_turns, bool mirror_x,
    const float offset[3], uint32_t *out_first_brush,
    uint32_t *out_num_brushes)
{
    if (out_first_brush)
        *out_first_brush = 0;
    if (out_num_brushes)
        *out_num_brushes = 0;
    if (!dst || !src || !pivot || !offset || quarter_turns > 3)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    /* The source is read from and never touched: a donor that changed while
       being read is a donor nothing can be measured against afterwards. */
    mapgen_geometry_t *moved = NULL;
    mapgen_geometry_result_t rc = MapGenGeometry_Clone(src, &moved);
    if (rc != MAPGEN_GEOMETRY_OK)
        return rc;
    rc = MapGenGeometry_TransformSubset(moved, brush_mask, entity_mask, pivot,
                                        quarter_turns, mirror_x, offset);
    if (rc != MAPGEN_GEOMETRY_OK) {
        MapGenGeometry_Free(moved);
        return rc;
    }

    /*
     * A brush entity keeps its brushes.
     *
     * Two maps both calling something `*1` is two different rooms with one
     * name, so every source model in the masked set is given an index of its
     * own here. The writer puts brushes inside their entity's braces and the
     * compiler assigns the real ordinals, so all that is required is that the
     * index is distinct per entity.
     */
    uint32_t next_model = 1;
    for (uint32_t b = 0; b < dst->num_brushes; b++)
        if (dst->brushes[b].model >= next_model)
            next_model = dst->brushes[b].model + 1;

    uint32_t remap[MAPGEN_GEOMETRY_MAX_MODELS];
    bool remapped[MAPGEN_GEOMETRY_MAX_MODELS];
    memset(remapped, 0, sizeof(remapped));

    const uint32_t first = dst->num_brushes;
    uint32_t crossed = 0;
    for (uint32_t b = 0; b < moved->num_brushes; b++) {
        if (brush_mask && !brush_mask[b])
            continue;
        const mapgen_geometry_brush_t *brush = &moved->brushes[b];
        uint32_t model = brush->model;
        if (model) {
            if (model >= MAPGEN_GEOMETRY_MAX_MODELS) {
                MapGenGeometry_Free(moved);
                return MAPGEN_GEOMETRY_ERR_LIMIT;
            }
            if (!remapped[model]) {
                remap[model] = next_model++;
                remapped[model] = true;
            }
            model = remap[model];
        }
        rc = MapGenGeometry_AddBrush(dst, &moved->sides[brush->first_side],
                                     brush->num_sides, brush->contents, model);
        if (rc != MAPGEN_GEOMETRY_OK) {
            MapGenGeometry_Free(moved);
            return rc;
        }
        crossed++;
    }

    for (uint32_t e = 0; e < moved->num_entities; e++) {
        if (entity_mask && !entity_mask[e])
            continue;
        const mapgen_geometry_entity_t *ent = &moved->entities[e];
        uint32_t model = ent->model;
        if (model) {
            /* An entity whose brushes did not cross would name a submodel
               that is not there, which is a map with a door into nothing. */
            if (model >= MAPGEN_GEOMETRY_MAX_MODELS || !remapped[model]) {
                MapGenGeometry_Free(moved);
                return MAPGEN_GEOMETRY_ERR_OWNERSHIP;
            }
            model = remap[model];
        }
        uint32_t at = 0;
        rc = MapGenGeometry_AddEntity(dst, model, &at);
        if (rc != MAPGEN_GEOMETRY_OK) {
            MapGenGeometry_Free(moved);
            return rc;
        }
        for (uint32_t p = 0; p < ent->num_pairs; p++) {
            const char *key = NULL, *value = NULL;
            MapGenGeometry_Pair(moved, ent->first_pair + p, &key, &value);
            if (!key || !value)
                continue;
            rc = MapGenGeometry_AddEntityPair(dst, at, key, value);
            if (rc != MAPGEN_GEOMETRY_OK) {
                MapGenGeometry_Free(moved);
                return rc;
            }
        }
    }

    MapGenGeometry_Free(moved);
    if (!crossed)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    if (out_first_brush)
        *out_first_brush = first;
    if (out_num_brushes)
        *out_num_brushes = crossed;
    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_AddEntity(mapgen_geometry_t *g,
                                                  uint32_t model,
                                                  uint32_t *out_entity)
{
    if (out_entity)
        *out_entity = 0;
    if (!g)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    if (g->num_entities == g->entity_cap) {
        const uint32_t want = g->entity_cap ? g->entity_cap * 2 : 64;
        if (want > MAPGEN_GEOMETRY_MAX_ENTITIES)
            return MAPGEN_GEOMETRY_ERR_LIMIT;
        mapgen_geometry_entity_t *grown =
            realloc(g->entities, (size_t)want * sizeof(*grown));
        if (!grown)
            return MAPGEN_GEOMETRY_ERR_MEMORY;
        g->entities = grown;
        g->entity_cap = want;
    }

    mapgen_geometry_entity_t *e = &g->entities[g->num_entities];
    memset(e, 0, sizeof(*e));
    e->first_pair = g->num_pairs;
    e->model = model;

    /*
     * And the count moves up with it.
     *
     * Without this, a caller asking for "the next model number" got the same
     * answer twice: the second lift on a map claimed the first one's model,
     * the writer put both platforms inside both entities, and neither of them
     * moved. One lift worked and two did not, which is why it looked like the
     * lift was broken rather than the numbering.
     */
    if (model >= g->num_models)
        g->num_models = model + 1;
    if (out_entity)
        *out_entity = g->num_entities;
    g->num_entities++;
    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_AddEntityPair(mapgen_geometry_t *g,
                                                      uint32_t entity,
                                                      const char *key,
                                                      const char *value)
{
    if (!g || entity >= g->num_entities || !key || !value)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    /* Only the entity written last can still take pairs: they live in one
       shared block in order, and inserting into the middle would renumber
       every entity after it. */
    if (entity != g->num_entities - 1)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    if (!add_pair(g, key, strlen(key), value, strlen(value)))
        return MAPGEN_GEOMETRY_ERR_LIMIT;
    g->entities[entity].num_pairs++;
    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_SetEntityValue(mapgen_geometry_t *g,
                                                       uint32_t entity,
                                                       const char *key,
                                                       const char *value)
{
    if (!g || entity >= g->num_entities || !key || !value)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    const mapgen_geometry_entity_t *e = &g->entities[entity];
    for (uint32_t i = 0; i < e->num_pairs; i++) {
        const uint32_t pair = e->first_pair + i;
        if (strcmp(g->text + g->pair_at[pair * 2], key))
            continue;

        /* The new bytes go on the end and the pair is repointed at them. The
           old ones stay where they are, unreferenced: the block is written out
           by walking the pairs, never by walking the bytes. */
        const size_t len = strlen(value);
        const ptrdiff_t value_at = text_offset(g, value);
        if (!reserve_text(g, len + 1))
            return MAPGEN_GEOMETRY_ERR_LIMIT;
        if (value_at >= 0)
            value = g->text + value_at;
        g->pair_at[pair * 2 + 1] = (uint32_t)g->text_len;
        memcpy(g->text + g->text_len, value, len);
        g->text_len += len;
        g->text[g->text_len++] = '\0';
        return MAPGEN_GEOMETRY_OK;
    }
    return MAPGEN_GEOMETRY_ERR_ARGS;
}

/* ---- the edit operators ---------------------------------------------------- */

/*
 * Move one plane along its own outward normal.
 *
 * A positive delta grows the solid. That direction is the safe one and it is
 * worth saying why: growing a brush only ever ADDS solid, so a map that was
 * sealed before is still sealed after - no displacement of this kind can open
 * a hole to the void. Shrinking can, by pulling a face back from the neighbour
 * it used to meet, so a caller that shrinks owes a compiled leak check.
 *
 * Convexity survives either way: a convex solid is the intersection of its
 * half-spaces, and sliding one half-space along its own normal leaves an
 * intersection of half-spaces.
 */
mapgen_geometry_result_t MapGenGeometry_DisplaceSide(mapgen_geometry_t *g,
                                                     uint32_t side, float delta)
{
    if (!g || side >= g->num_sides || !isfinite(delta))
        return MAPGEN_GEOMETRY_ERR_ARGS;
    g->sides[side].dist += delta;
    for (int a = 0; a < 3; a++)
        g->sides[side].center[a] += g->sides[side].normal[a] * delta;

    /*
     * And the brush this side belongs to is a different shape now.
     *
     * A brush carries its own box, and every reader of this module trusts it:
     * the hollow decides what a region touches by it, the divergence lattice
     * bounds itself by it, and the liquid test asks it whether a point is in
     * a pool. Moving a plane and leaving the box where it was makes all three
     * answer about a shape that is no longer there.
     *
     * MEASURED: the flood raised q2dm1's upper pool from 440 to 529 and the
     * box still said 440, so a deathmatch start at 482 - a foot and a half
     * under the new surface - was reported dry, by the very check written to
     * catch it. The PO had already spawned in that water.
     */
    for (uint32_t b = 0; b < g->num_brushes; b++) {
        mapgen_geometry_brush_t *brush = &g->brushes[b];
        if (side < brush->first_side
            || side >= brush->first_side + brush->num_sides)
            continue;
        float mins[3], maxs[3];
        if (shape_brush(&g->sides[brush->first_side], brush->num_sides,
                        mins, maxs) >= 4) {
            memcpy(brush->mins, mins, sizeof(brush->mins));
            memcpy(brush->maxs, maxs, sizeof(brush->maxs));
        }
        break;
    }
    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_RetextureSide(mapgen_geometry_t *g,
                                                      uint32_t side,
                                                      const char *texture,
                                                      int32_t flags,
                                                      int32_t value)
{
    if (!g || side >= g->num_sides || !texture)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    if (strlen(texture) > MAPGEN_BSP_TEXNAME)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    memset(g->sides[side].texture, 0, sizeof(g->sides[side].texture));
    memcpy(g->sides[side].texture, texture, strlen(texture));
    g->sides[side].flags = flags;
    g->sides[side].value = value;
    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_SetLiquid(mapgen_geometry_t *g, uint32_t brush, int32_t liquid)
{
    const int32_t mask = MAPGEN_CONTENTS_WATER | MAPGEN_CONTENTS_SLIME | MAPGEN_CONTENTS_LAVA;
    if (!g || brush >= g->num_brushes || !(g->brushes[brush].contents & mask)
        || (liquid != MAPGEN_CONTENTS_WATER && liquid != MAPGEN_CONTENTS_SLIME && liquid != MAPGEN_CONTENTS_LAVA))
        return MAPGEN_GEOMETRY_ERR_ARGS;
    g->brushes[brush].contents = (g->brushes[brush].contents & ~mask) | liquid;
    return MAPGEN_GEOMETRY_OK;
}

mapgen_geometry_result_t MapGenGeometry_DropBrush(mapgen_geometry_t *g,
                                                  uint32_t brush)
{
    if (!g || brush >= g->num_brushes)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    const mapgen_geometry_brush_t *gone = &g->brushes[brush];
    const uint32_t first = gone->first_side;
    const uint32_t count = gone->num_sides;

    memmove(&g->sides[first], &g->sides[first + count],
            (size_t)(g->num_sides - first - count) * sizeof(*g->sides));
    g->num_sides -= count;

    memmove(&g->brushes[brush], &g->brushes[brush + 1],
            (size_t)(g->num_brushes - brush - 1) * sizeof(*g->brushes));
    g->num_brushes--;

    /* Every brush after it owned sides further along the array, and now does
       not. A brush whose first_side still points past the hole would be
       wearing another brush's faces. */
    for (uint32_t b = brush; b < g->num_brushes; b++)
        g->brushes[b].first_side -= count;

    return MAPGEN_GEOMETRY_OK;
}

/* ---- canonical text -------------------------------------------------------- */

/*
 * Integers only, so the answer cannot depend on a locale, a libc's rounding of
 * the seventeenth digit or a second implementation's choice of format. Values
 * are carried at ten-thousandths, which is finer than any coordinate a Quake
 * II compiler will keep.
 */
#define CANON_SCALE 10000.0

typedef struct {
    char  *out;
    size_t capacity;
    size_t needed;
} canon_t;

static void canon_raw(canon_t *c, const char *s, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        if (c->needed + 1 < c->capacity && c->out)
            c->out[c->needed] = s[i];
        c->needed++;
    }
}

static void canon_str(canon_t *c, const char *s)
{
    canon_raw(c, s, strlen(s));
}

static void canon_i64(canon_t *c, int64_t v)
{
    char digits[24];
    size_t n = 0;
    uint64_t u = v < 0 ? (uint64_t)(-(v + 1)) + 1u : (uint64_t)v;
    if (v < 0)
        canon_raw(c, "-", 1);
    do {
        digits[n++] = (char)('0' + (u % 10));
        u /= 10;
    } while (u);
    while (n--)
        canon_raw(c, &digits[n], 1);
}

static void canon_f(canon_t *c, float v)
{
    const double scaled = (double)v * CANON_SCALE;
    canon_i64(c, (int64_t)(scaled >= 0 ? scaled + 0.5 : scaled - 0.5));
}

size_t MapGenGeometry_CanonicalText(const mapgen_geometry_t *g, char *out,
                                    size_t capacity)
{
    canon_t c = { out, capacity, 0 };
    if (!g) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    canon_str(&c, "geometry 1\nb=");
    canon_i64(&c, g->num_brushes);
    canon_str(&c, " s=");
    canon_i64(&c, g->num_sides);
    canon_str(&c, " m=");
    canon_i64(&c, g->num_models);
    canon_str(&c, " e=");
    canon_i64(&c, g->num_entities);
    canon_str(&c, " orphan=");
    canon_i64(&c, g->orphan_brushes);
    canon_str(&c, "\n");

    for (uint32_t b = 0; b < g->num_brushes; b++) {
        const mapgen_geometry_brush_t *brush = &g->brushes[b];
        canon_str(&c, "B ");
        canon_i64(&c, brush->contents);
        canon_str(&c, " ");
        canon_i64(&c, brush->model);
        canon_str(&c, " ");
        canon_i64(&c, brush->num_sides);
        canon_str(&c, "\n");
        for (uint32_t s = 0; s < brush->num_sides; s++) {
            const mapgen_geometry_side_t *side = &g->sides[brush->first_side + s];
            canon_str(&c, "S ");
            for (int a = 0; a < 3; a++) {
                canon_f(&c, side->normal[a]);
                canon_str(&c, " ");
            }
            canon_f(&c, side->dist);
            canon_str(&c, " ");
            canon_i64(&c, side->flags);
            canon_str(&c, " ");
            canon_i64(&c, side->value);
            canon_str(&c, " ");
            canon_i64(&c, side->bevel ? 1 : 0);
            for (int a = 0; a < 2; a++) {
                for (int k = 0; k < 4; k++) {
                    canon_str(&c, " ");
                    canon_f(&c, side->axis[a][k]);
                }
            }
            canon_str(&c, " ");
            canon_str(&c, side->texture);
            canon_str(&c, "\n");
        }
    }

    for (uint32_t e = 0; e < g->num_entities; e++) {
        const mapgen_geometry_entity_t *ent = &g->entities[e];
        canon_str(&c, "E ");
        canon_i64(&c, ent->model);
        canon_str(&c, " ");
        canon_i64(&c, ent->num_pairs);
        canon_str(&c, "\n");
        for (uint32_t p = 0; p < ent->num_pairs; p++) {
            const char *k, *v;
            MapGenGeometry_Pair(g, ent->first_pair + p, &k, &v);
            canon_str(&c, "K ");
            canon_str(&c, k ? k : "");
            canon_str(&c, "=");
            canon_str(&c, v ? v : "");
            canon_str(&c, "\n");
        }
    }

    if (out && capacity)
        out[c.needed < capacity ? c.needed : capacity - 1] = '\0';
    return c.needed + 1;
}

/*
 * One row per distinct plane and material: area, extent and how the surface is
 * flagged. Sorted, so the order faces arrived in cannot change the answer.
 */
typedef struct {
    float    normal[3];
    float    dist;
    int32_t  flags;
    int32_t  value;
    uint32_t model;
    char     texture[MAPGEN_BSP_TEXNAME + 1];
    double   area;
    float    mins[3];
    float    maxs[3];
} surface_row_t;

/*
 * Rounded, not truncated, and one quantum coarser than the compiler's own
 * NORMAL_EPSILON.
 *
 * Truncating at a hundred-thousandth turns 0.2095000 and 0.2094999 into
 * different surfaces, and the difference is in the seventh decimal of a value
 * the compiler considers identical. Keyed that way the audit reported 288 of
 * the donor's surfaces vanished from a rebuild whose planes are all reproduced
 * to better than a millionth - the tool was measuring its own arithmetic.
 */
static int64_t quantize(float v, double quantum)
{
    const double scaled = (double)v * quantum;
    return (int64_t)(scaled >= 0 ? scaled + 0.5 : scaled - 0.5);
}

#define SURFACE_NORMAL_QUANTUM 10000.0
#define SURFACE_DIST_QUANTUM   100.0

static int surface_order(const void *a, const void *b)
{
    const surface_row_t *x = a, *y = b;
    for (int i = 0; i < 3; i++) {
        const int64_t xn = quantize(x->normal[i], SURFACE_NORMAL_QUANTUM);
        const int64_t yn = quantize(y->normal[i], SURFACE_NORMAL_QUANTUM);
        if (xn != yn)
            return xn < yn ? -1 : 1;
    }
    const int64_t xd = quantize(x->dist, SURFACE_DIST_QUANTUM);
    const int64_t yd = quantize(y->dist, SURFACE_DIST_QUANTUM);
    if (xd != yd)
        return xd < yd ? -1 : 1;
    if (x->model != y->model)
        return x->model < y->model ? -1 : 1;
    return strcmp(x->texture, y->texture);
}

static bool same_surface(const surface_row_t *r, const mapgen_geometry_face_t *f)
{
    for (int i = 0; i < 3; i++) {
        if (quantize(r->normal[i], SURFACE_NORMAL_QUANTUM)
            != quantize(f->normal[i], SURFACE_NORMAL_QUANTUM))
            return false;
    }
    return quantize(r->dist, SURFACE_DIST_QUANTUM)
        == quantize(f->dist, SURFACE_DIST_QUANTUM)
        && r->model == f->model && r->flags == f->flags && r->value == f->value
        && !strcmp(r->texture, f->texture);
}

size_t MapGenGeometry_RenderCanonicalText(const mapgen_geometry_t *g,
                                          char *out, size_t capacity)
{
    canon_t c = { out, capacity, 0 };
    if (!g) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    surface_row_t *rows = calloc(g->num_faces ? g->num_faces : 1, sizeof(*rows));
    if (!rows) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }
    uint32_t num_rows = 0;

    for (uint32_t f = 0; f < g->num_faces; f++) {
        const mapgen_geometry_face_t *face = &g->faces[f];
        uint32_t at = num_rows;
        for (uint32_t r = 0; r < num_rows; r++) {
            if (same_surface(&rows[r], face)) {
                at = r;
                break;
            }
        }
        if (at == num_rows) {
            surface_row_t *row = &rows[num_rows++];
            memcpy(row->normal, face->normal, sizeof(row->normal));
            row->dist = face->dist;
            row->flags = face->flags;
            row->value = face->value;
            row->model = face->model;
            memcpy(row->texture, face->texture, sizeof(row->texture));
            for (int a = 0; a < 3; a++) {
                row->mins[a] = MAPGEN_GEOMETRY_WORLD_EXTENT;
                row->maxs[a] = -MAPGEN_GEOMETRY_WORLD_EXTENT;
            }
        }
        rows[at].area += face->area;
        for (uint32_t p = 0; p < face->num_points; p++) {
            const float *point = &g->points[(face->first_point + p) * 3];
            for (int a = 0; a < 3; a++) {
                if (point[a] < rows[at].mins[a])
                    rows[at].mins[a] = point[a];
                if (point[a] > rows[at].maxs[a])
                    rows[at].maxs[a] = point[a];
            }
        }
    }

    qsort(rows, num_rows, sizeof(*rows), surface_order);

    canon_str(&c, "render 1\nsurfaces=");
    canon_i64(&c, num_rows);
    canon_str(&c, "\n");
    for (uint32_t r = 0; r < num_rows; r++) {
        canon_str(&c, "R ");
        for (int a = 0; a < 3; a++) {
            canon_f(&c, rows[r].normal[a]);
            canon_str(&c, " ");
        }
        canon_f(&c, rows[r].dist);
        canon_str(&c, " ");
        canon_i64(&c, rows[r].flags);
        canon_str(&c, " ");
        canon_i64(&c, rows[r].value);
        canon_str(&c, " ");
        canon_i64(&c, rows[r].model);
        canon_str(&c, " ");
        /* Area to the nearest whole unit: the compiler's own arithmetic moves
           the last fraction, and a digest that noticed would be noise. */
        canon_i64(&c, (int64_t)(rows[r].area + 0.5));
        for (int a = 0; a < 3; a++) {
            canon_str(&c, " ");
            canon_f(&c, rows[r].mins[a]);
        }
        for (int a = 0; a < 3; a++) {
            canon_str(&c, " ");
            canon_f(&c, rows[r].maxs[a]);
        }
        canon_str(&c, " ");
        canon_str(&c, rows[r].texture);
        canon_str(&c, "\n");
    }

    free(rows);
    if (out && capacity)
        out[c.needed < capacity ? c.needed : capacity - 1] = '\0';
    return c.needed + 1;
}

uint64_t MapGenGeometry_RenderDigest(const mapgen_geometry_t *g)
{
    const size_t needed = MapGenGeometry_RenderCanonicalText(g, NULL, 0);
    char *text = malloc(needed ? needed : 1);
    if (!text)
        return 0;
    MapGenGeometry_RenderCanonicalText(g, text, needed);

    uint64_t hash = 14695981039346656037ull;
    for (const char *p = text; *p; p++) {
        hash ^= (uint8_t)*p;
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}

uint64_t MapGenGeometry_CanonicalDigest(const mapgen_geometry_t *g)
{
    const size_t needed = MapGenGeometry_CanonicalText(g, NULL, 0);
    char *text = malloc(needed ? needed : 1);
    if (!text)
        return 0;
    MapGenGeometry_CanonicalText(g, text, needed);

    uint64_t hash = 14695981039346656037ull;
    for (const char *p = text; *p; p++) {
        hash ^= (uint8_t)*p;
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}

/* ---- the Valve 220 writer ---------------------------------------------------- */

/* One variable of the seam diagnosis, overridable at build time so a
   controlled experiment changes exactly this and nothing else. */
/* The second variable of the seam diagnosis: whether the sides that clip
   nothing off the solid are handed to the compiler or left for it to derive
   again. */
#ifndef MAPGEN_REVERSE_BRUSH_ORDER
#define MAPGEN_REVERSE_BRUSH_ORDER 0
#endif

#ifndef MAPGEN_WRITE_BEVELS
/*
 * On, and measured rather than assumed.
 *
 * These sides clip nothing off their own brush, so dropping them looked free
 * and an aggregate count of loose edges moved from 407 to 401, which proved
 * nothing. Held against the faceted-arc fixture one variable at a time, the
 * worst plane the rebuild reproduces goes from being 0.0625 units out of place
 * to 0.000092 - seven hundred times closer - and the surfaces that come back
 * on the wrong plane drop from fourteen to six. A plane that clips nothing off
 * a convex body still tells the compiler where that body ends.
 */
#define MAPGEN_WRITE_BEVELS 1
#endif

/*
 * How far a redundant plane is pushed out of the way before it is written.
 *
 * A bevel clips nothing off the brush it belongs to - that is what makes it a
 * bevel - so it can be restated at any distance at or beyond where the donor
 * put it and the solid is unchanged. It CANNOT be restated a hair short of it:
 * the writer rounds three points to PLANE_POINT_DECIMALS, the compiler
 * re-derives a plane from them, and when that lands even slightly inside, the
 * redundant plane stops being redundant and starts cutting the wall. MEASURED
 * on q2dm1, the map the PO photographed a strip of sky in: handed back exactly
 * as they are, the bevels cost one angled wall 13159 of its 19698 square units.
 *
 * The SIZE is not a taste. The pinned compiler has two rules about plane
 * distances, both in its `map.c`, and this value has to sit between them:
 *
 *   `PlaneEqual` (map.c:92-96) calls two planes the same plane when their
 *   distances are within DIST_EPSILON = 0.01. An outset smaller than that is
 *   merged straight back onto the face it was meant to stand clear of and
 *   buys nothing - MEASURED, 1/128 of a unit leaves q2dm1 exactly where it
 *   was, at 21761 square units of undrawn wall.
 *
 *   `SnapPlane` (map.c:193-197) then rounds any distance within the same
 *   0.01 to the nearest integer, so a plane that is moved further is not
 *   moved by the amount asked for, and which way it finally lands stops
 *   being a property of this decision.
 *
 * So: the smallest step that clears DIST_EPSILON, and no larger, because every
 * extra unit of movement is another chance to disturb something - and it does.
 * MEASURED on q2dm1, undrawn area against the outset:
 *
 *     1/128   21761   (merged back; no effect at all)
 *     1/64     4294   <- this
 *     1/48     4294
 *     1/32     8889
 *     1/16     8889
 *
 * A sixty-fourth of a unit is a hundred and fifty times the writer's own
 * rounding and half again the compiler's epsilon, and it is far less than
 * anything a player can stand in.
 */
#ifndef MAPGEN_BEVEL_OUTSET
#define MAPGEN_BEVEL_OUTSET 0.015625
#endif

#ifndef PLANE_POINT_DECIMALS
#define PLANE_POINT_DECIMALS 4
#endif

/*
 * Decimals rendered from integers, for the same reason the canonical text is:
 * `printf("%f")` answers to the C locale and would write a comma on a machine
 * set to one, and a `.map` with commas in its coordinates is not a map.
 */
static void write_f(FILE *f, double v, int decimals)
{
    double scale = 1.0;
    for (int i = 0; i < decimals; i++)
        scale *= 10.0;

    double scaled = v * scale;
    if (!isfinite(scaled))
        scaled = 0.0;
    int64_t fixed = (int64_t)(scaled >= 0 ? scaled + 0.5 : scaled - 0.5);
    if (fixed < 0) {
        fputc('-', f);
        fixed = -fixed;
    }

    const int64_t whole = fixed / (int64_t)scale;
    int64_t frac = fixed % (int64_t)scale;

    char digits[24];
    size_t n = 0;
    int64_t u = whole;
    do {
        digits[n++] = (char)('0' + (u % 10));
        u /= 10;
    } while (u);
    while (n--)
        fputc(digits[n], f);

    /* Trailing zeroes carry no information and make a diff unreadable. */
    if (!frac)
        return;

    char tail[24];
    size_t t = 0;
    for (int i = 0; i < decimals; i++) {
        tail[t++] = (char)('0' + (frac % 10));
        frac /= 10;
    }
    while (t > 1 && tail[0] == '0') {
        memmove(tail, tail + 1, --t);
    }
    fputc('.', f);
    while (t--)
        fputc(tail[t], f);
}

/*
 * Three points on the plane, in the order the compiler derives a normal from:
 * it computes (p0 - p1) x (p2 - p1), so p1 is the corner and p0, p2 run along
 * two tangents whose cross product is the outward normal. Get the order wrong
 * and every solid in the map is inside out.
 */
#ifndef MAPGEN_PLANE_POINTS_FROM_WINDING
#define MAPGEN_PLANE_POINTS_FROM_WINDING 1
#endif

/* Three points on a plane, built from its normal and distance alone. */
static void plane_points_synthetic(const mapgen_geometry_side_t *side,
                                   double p[3][3]);

#ifndef MAPGEN_CANONICAL_PLANE_POINTS
#define MAPGEN_CANONICAL_PLANE_POINTS 1
#endif

/*
 * Is this side's normal the canonical orientation of its plane, or the
 * opposite one? First non-zero component positive, with the components tested
 * in a fixed order so that two sides sharing a plane always agree on which of
 * them is canonical.
 */
static bool plane_is_canonical(const float normal[3])
{
    for (int a = 0; a < 3; a++) {
        if (normal[a] > 0.0f)
            return true;
        if (normal[a] < 0.0f)
            return false;
    }
    return true;
}

/*
 * Write planes as the integers they were authored as.
 *
 * A Quake map is drawn on an integer grid, so every plane in it has an integer
 * normal (a b c) and an integer constant D; the BSP stores the NORMALISED
 * form, and normalising is what puts the irrational numbers in. Recovering the
 * integer form and writing three integer points on it means the compiler
 * derives exactly the plane the map was built with, with no rounding anywhere
 * in the path. On q2dm1 it recovers 2288 of 2408 planes and moves the worst by
 * 0.00035 units; the 120 it declines are genuinely off the grid (terrain, and
 * bevels the donor's own compiler generated) and fall through to the float
 * path below.
 *
 * This was OFF until 2026-09-06, on a measurement that looked like a trade:
 * exact planes reproduced the collision hull far better - q2dm1 48 -> 2 lost
 * sample points, q2dm2 136 -> 3 - and cost q2dm1 its mesh, 8889 -> 50098
 * square units of wall that nothing drew. The trade was not real. The mesh
 * damage was the pinned compiler cutting every winding out of a quad 2^20
 * units wide in single precision (local patch P12), which puts 0.06 units of
 * error in every winding; exact planes only changed which way that error fell
 * at q2dm1's 1.1-degree crease, where it is multiplied by fifty-two.
 *
 * MEASURED with P12, fidelity 100, float points against integer points -
 * undrawn drawn-surface area, then points where the donor has solid and the
 * rebuild does not, then points where the donor has air and the rebuild has
 * solid:
 *
 *     q2dm1   0 / 0     48 -> 24      76 -> 11
 *     q2dm2   0 / 0    136 ->  3      30 -> 115
 *     q2dm3   0 / 0    341 -> 311    189 -> 47
 *     q2dm8   0 / 0    634 -> 396    259 -> 22
 *
 * Every map draws every point of its donor either way; the hull is better on
 * all four and the grown solid on three of four. So it is on.
 */
#ifndef MAPGEN_INTEGER_PLANE_POINTS
#define MAPGEN_INTEGER_PLANE_POINTS 1
#endif

#if MAPGEN_INTEGER_PLANE_POINTS

/* ---- the plane the map was authored on ------------------------------------
 *
 * See the note on MAPGEN_INTEGER_PLANE_POINTS below: a BSP plane is the
 * NORMALISED form of an integer plane, and normalising it is what puts the
 * irrational numbers in. These recover the integer form.
 */

static long plane_gcd(long a, long b)
{
    a = a < 0 ? -a : a;
    b = b < 0 ? -b : b;
    while (b) {
        const long t = a % b;
        a = b;
        b = t;
    }
    return a;
}

/* Bezout: returns gcd(a,b) and the u, v with a*u + b*v = gcd(a,b). */
static long plane_bezout(long a, long b, long *u, long *v)
{
    long old_r = a, r = b, old_s = 1, s = 0, old_t = 0, t = 1;
    while (r) {
        const long q = old_r / r;
        long tmp = old_r - q * r; old_r = r; r = tmp;
        tmp = old_s - q * s; old_s = s; s = tmp;
        tmp = old_t - q * t; old_t = t; t = tmp;
    }
    if (old_r < 0) {
        old_r = -old_r;
        old_s = -old_s;
        old_t = -old_t;
    }
    *u = old_s;
    *v = old_t;
    return old_r;
}

/*
 * The integer plane behind a normalised one, if there is one.
 *
 * Found by scaling the normal until every component lands on an integer: the
 * scale that does it is |(a b c)|, so the search runs over the largest
 * component and takes the first scale that reproduces the direction AND the
 * distance. The bound is generous - id's own normals sit well inside it - and
 * a plane that does not answer is left to the float path below.
 */
static bool integer_plane(const float normal[3], float dist,
                          long m[3], long *out_d)
{
    int major = 0;
    for (int a = 1; a < 3; a++)
        if (fabs((double)normal[a]) > fabs((double)normal[major]))
            major = a;
    const double big = fabs((double)normal[major]);
    if (big < 1e-6)
        return false;

    for (long k = 1; k <= 1024; k++) {
        const double scale = (double)k / big;
        long r[3];
        bool integral = true;
        for (int a = 0; a < 3; a++) {
            const double v = (double)normal[a] * scale;
            r[a] = lround(v);
            if (fabs(v - (double)r[a]) > 2e-3)
                integral = false;
        }
        if (!integral)
            continue;

        const double len = sqrt((double)(r[0] * r[0] + r[1] * r[1]
                                         + r[2] * r[2]));
        if (len < 0.5)
            continue;
        /* It has to be THIS plane's direction, not merely one nearby. */
        bool same = true;
        for (int a = 0; a < 3; a++)
            if (fabs((double)r[a] / len - (double)normal[a]) > 2e-5)
                same = false;
        if (!same)
            continue;

        /*
         * And the distance has to be integral at the same scale. The slack is
         * the stored float's own error at this magnitude, and no more: a plane
         * that is genuinely off the grid must fall through rather than be
         * snapped onto it.
         */
        const double scaled = (double)dist * len;
        const long D = lround(scaled);
        /*
         * The slack is the stored float's own error at this magnitude, and no
         * more. MEASURED with a flat 0.02 in the scaled units instead: the
         * worst plane in q2dm1 came back 0.012 units from where the donor had
         * it, which is larger than the compiler's own idea of two planes being
         * the same one, and a plane that is genuinely off the grid must fall
         * through to the float path rather than be snapped onto it.
         */
        const double slack = fabs((double)dist) * 2e-6;
        if (fabs(scaled - (double)D) > len * (slack > 1e-4 ? slack : 1e-4))
            continue;

        const long g = plane_gcd(plane_gcd(r[0], r[1]), r[2]);
        if (g > 1) {
            if (D % g)
                continue;          /* then no integer point lies on it */
            for (int a = 0; a < 3; a++)
                r[a] /= g;
            *out_d = D / g;
        } else {
            *out_d = D;
        }
        m[0] = r[0];
        m[1] = r[1];
        m[2] = r[2];
        return true;
    }
    return false;
}

/*
 * Three integer points on an integer plane, in the compiler's own order.
 *
 * The lattice point they are built around is the one nearest the plane's
 * closest approach to the origin - a property of the PLANE and of nothing
 * else - so two brushes that share a plane write the same three points and
 * still meet exactly after the round trip.
 */
static bool integer_plane_points(const long m[3], long D, double p[3][3])
{
    long u, v;
    const long g1 = plane_bezout(m[0], m[1], &u, &v);
    long pc, q;
    const long g = plane_bezout(g1, m[2], &pc, &q);
    if (!g || (D % g))
        return false;
    const long t = D / g;
    long base[3] = { u * pc * t, v * pc * t, q * t };

    /* Two integer directions along the plane. */
    long e1[3], e2[3];
    if (m[0]) {
        e1[0] = m[1]; e1[1] = -m[0]; e1[2] = 0;
        e2[0] = m[2]; e2[1] = 0;     e2[2] = -m[0];
    } else if (m[1]) {
        e1[0] = 1;    e1[1] = 0;     e1[2] = 0;
        e2[0] = 0;    e2[1] = m[2];  e2[2] = -m[1];
    } else {
        e1[0] = 1; e1[1] = 0; e1[2] = 0;
        e2[0] = 0; e2[1] = 1; e2[2] = 0;
    }

    /* Walk the point back to the plane's own foot, so the coordinates stay
       small and - the reason this matters - depend on the plane alone. */
    const double len2 = (double)(m[0] * m[0] + m[1] * m[1] + m[2] * m[2]);
    double foot[3];
    for (int a = 0; a < 3; a++)
        foot[a] = (double)m[a] * (double)D / len2;
    const double g11 = (double)(e1[0]*e1[0] + e1[1]*e1[1] + e1[2]*e1[2]);
    const double g22 = (double)(e2[0]*e2[0] + e2[1]*e2[1] + e2[2]*e2[2]);
    const double g12 = (double)(e1[0]*e2[0] + e1[1]*e2[1] + e1[2]*e2[2]);
    const double det = g11 * g22 - g12 * g12;
    if (det > 1e-9) {
        for (int pass = 0; pass < 2; pass++) {
            double w[3];
            for (int a = 0; a < 3; a++)
                w[a] = foot[a] - (double)base[a];
            const double b1 = e1[0]*w[0] + e1[1]*w[1] + e1[2]*w[2];
            const double b2 = e2[0]*w[0] + e2[1]*w[1] + e2[2]*w[2];
            const long s1 = lround((b1 * g22 - b2 * g12) / det);
            const long s2 = lround((b2 * g11 - b1 * g12) / det);
            if (!s1 && !s2)
                break;
            for (int a = 0; a < 3; a++)
                base[a] += e1[a] * s1 + e2[a] * s2;
        }
    }

    /* Far enough apart that the compiler's own cross product is accurate. */
    long k1 = lround(512.0 / sqrt(g11 > 0.0 ? g11 : 1.0));
    long k2 = lround(512.0 / sqrt(g22 > 0.0 ? g22 : 1.0));
    if (k1 < 1) k1 = 1;
    if (k2 < 1) k2 = 1;

    double A[3], B[3];
    for (int a = 0; a < 3; a++) {
        A[a] = (double)(e1[a] * k1);
        B[a] = (double)(e2[a] * k2);
    }
    /* (p0 - p1) x (p2 - p1) has to come out along the integer normal. */
    const double cx = A[1]*B[2] - A[2]*B[1];
    const double cy = A[2]*B[0] - A[0]*B[2];
    const double cz = A[0]*B[1] - A[1]*B[0];
    if (cx * (double)m[0] + cy * (double)m[1] + cz * (double)m[2] < 0.0) {
        double swap[3];
        memcpy(swap, A, sizeof(swap));
        memcpy(A, B, sizeof(A));
        memcpy(B, swap, sizeof(B));
    }
    for (int a = 0; a < 3; a++) {
        p[1][a] = (double)base[a];
        p[0][a] = (double)base[a] + A[a];
        p[2][a] = (double)base[a] + B[a];
    }
    return true;
}


#endif  /* MAPGEN_INTEGER_PLANE_POINTS */

static void plane_points(const mapgen_geometry_side_t *side, double p[3][3])
{
#if MAPGEN_CANONICAL_PLANE_POINTS
    /*
     * Derive for the canonical orientation and flip the order for the other
     * one. The winding anchors cannot be used here: they belong to this side's
     * own brush, and the neighbour's anchors are different points on the same
     * plane, which is the whole problem.
     */
    /*
     * ALWAYS, not only for the flipped side.
     *
     * Deriving the canonical side from its own winding corners and the opposite
     * side from the negated plane still gives the two of them different
     * coordinates, because the corners belong to one brush and the negation to
     * the other. Both have to come from the same arithmetic or they do not meet.
     */
    {
        mapgen_geometry_side_t canon = *side;
        canon.has_anchor = false;
        const bool flip = !plane_is_canonical(side->normal);
        if (flip) {
            for (int a = 0; a < 3; a++)
                canon.normal[a] = -side->normal[a];
            canon.dist = -side->dist;
        }

        double q[3][3];
#if MAPGEN_INTEGER_PLANE_POINTS
        /*
         * The integer plane first, when the plane has one.
         *
         * Derived from the canonical orientation like everything else here, so
         * the two sides of a shared plane still write the same three points -
         * the same points, now, as the map was authored with.
         */
        long m[3], D;
        if (!integer_plane(canon.normal, canon.dist, m, &D)
            || !integer_plane_points(m, D, q))
            plane_points_synthetic(&canon, q);
#else
        plane_points_synthetic(&canon, q);
#endif
        for (int i = 0; i < 3; i++) {
            const int from = flip ? 2 - i : i;
            for (int a = 0; a < 3; a++)
                p[i][a] = q[from][a];
        }
        return;
    }
#endif

#if MAPGEN_PLANE_POINTS_FROM_WINDING
    /*
     * The side's own corners, when it has them, in the order the compiler
     * derives a normal from: it computes (p0 - p1) x (p2 - p1), so the middle
     * point is the corner and the other two run along two edges. The winding
     * is wound so that this comes out along the outward normal already; if the
     * chosen pair happens to give the other sign, they are swapped.
     */
    if (side->has_anchor) {
        double t1[3], t2[3], n[3];
        for (int a = 0; a < 3; a++) {
            t1[a] = side->anchor[1][a] - side->anchor[0][a];
            t2[a] = side->anchor[2][a] - side->anchor[0][a];
        }
        n[0] = t1[1] * t2[2] - t1[2] * t2[1];
        n[1] = t1[2] * t2[0] - t1[0] * t2[2];
        n[2] = t1[0] * t2[1] - t1[1] * t2[0];
        const double facing = n[0] * side->normal[0] + n[1] * side->normal[1]
                            + n[2] * side->normal[2];
        const int first = facing >= 0.0 ? 1 : 2;
        const int last = facing >= 0.0 ? 2 : 1;
        for (int a = 0; a < 3; a++) {
            p[0][a] = side->anchor[first][a];
            p[1][a] = side->anchor[0][a];
            p[2][a] = side->anchor[last][a];
        }
        return;
    }
#endif

    plane_points_synthetic(side, p);
}

/*
 * Three points on the plane, in the order the compiler derives a normal from:
 * it computes (p0 - p1) x (p2 - p1), so p1 is the corner and p0, p2 run along
 * two tangents whose cross product is the outward normal.
 */
static void plane_points_synthetic(const mapgen_geometry_side_t *side,
                                   double p[3][3])
{
    int minor = 0;
    for (int i = 1; i < 3; i++) {
        if (fabsf(side->normal[i]) < fabsf(side->normal[minor]))
            minor = i;
    }
    float t[3] = { 0, 0, 0 };
    t[minor] = 1.0f;

    float u[3], v[3];
    const float d = t[0] * side->normal[0] + t[1] * side->normal[1]
                  + t[2] * side->normal[2];
    for (int i = 0; i < 3; i++)
        u[i] = t[i] - side->normal[i] * d;
    const float ulen = sqrtf(u[0] * u[0] + u[1] * u[1] + u[2] * u[2]);
    for (int i = 0; i < 3; i++)
        u[i] /= ulen;
    v[0] = side->normal[1] * u[2] - side->normal[2] * u[1];
    v[1] = side->normal[2] * u[0] - side->normal[0] * u[2];
    v[2] = side->normal[0] * u[1] - side->normal[1] * u[0];

    /* Far enough apart that the compiler's own normal comes back accurate. */
    const double S = 512.0;
    for (int i = 0; i < 3; i++) {
        const double c = (double)side->normal[i] * side->dist;
        p[0][i] = c + u[i] * S;
        p[1][i] = c;
        p[2][i] = c + v[i] * S;
    }
}

/* Whether an entity carries this classname. Its pairs are held verbatim, so
   the answer is read from them rather than cached anywhere. */
static bool entity_is(const mapgen_geometry_t *g,
                      const mapgen_geometry_entity_t *ent, const char *want)
{
    for (uint32_t p = 0; p < ent->num_pairs; p++) {
        const char *k, *v;
        MapGenGeometry_Pair(g, ent->first_pair + p, &k, &v);
        if (k && v && !strcmp(k, "classname"))
            return !strcmp(v, want);
    }
    return false;
}

mapgen_geometry_result_t MapGenGeometry_WriteValve220(const mapgen_geometry_t *g,
                                                      const char *path)
{
    if (!g || !path)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    FILE *f = MapGenFs_OpenWrite(path, "wb");     /* row 411: a file, or a section of this process */
    if (!f)
        return MAPGEN_GEOMETRY_ERR_ARGS;

    fputs("// Game: Quake 2\n// Format: Valve\n"
          "// Generated by Q2PRO-X MAPGEN-1 (donor geometry)\n", f);

    /*
     * The areaportals, bound before anything is written.
     *
     * A compiled BSP keeps an areaportal brush in the world with
     * CONTENTS_AREAPORTAL and leaves its func_areaportal holding nothing but a
     * `style`; which brush belongs to which entity is not recorded anywhere in
     * the file. A .map may not say it that way - the compiler refuses a
     * func_areaportal that does not hold exactly one brush - so the binding is
     * restated here.
     *
     * Any one-to-one assignment is correct: the compiler numbers the portals
     * itself as it writes them, and which two areas a portal joins is decided
     * by where its brush is. A mismatched count is not correct, and fails here
     * rather than in the compiler.
     */
    uint32_t num_portal_brushes = 0;
    for (uint32_t k = 0; k < g->num_brushes; k++)
        if (g->brushes[k].model == 0
            && (g->brushes[k].contents & MAPGEN_CONTENTS_AREAPORTAL))
            num_portal_brushes++;
    uint32_t num_portal_entities = 0;
    for (uint32_t e = 0; e < g->num_entities; e++)
        if (entity_is(g, &g->entities[e], "func_areaportal"))
            num_portal_entities++;
    if (num_portal_brushes != num_portal_entities) {
        MapGenFs_Close(f);
        MapGenFs_Remove(path);
        return MAPGEN_GEOMETRY_ERR_AREAPORTAL;
    }
    uint32_t portal_taken = 0;

    for (uint32_t e = 0; e < g->num_entities; e++) {
        const mapgen_geometry_entity_t *ent = &g->entities[e];
        fputs("{\n", f);
        for (uint32_t p = 0; p < ent->num_pairs; p++) {
            const char *k, *v;
            MapGenGeometry_Pair(g, ent->first_pair + p, &k, &v);
            if (!k || !v)
                continue;
            /*
             * The compiler assigns its own `*n` as it writes the submodels,
             * so the donor's ordinal is dropped and the binding is expressed
             * by which brushes sit inside this entity's braces instead.
             */
            if (!strcmp(k, "model") && v[0] == '*')
                continue;
            if (!strcmp(k, "mapversion"))
                continue;          /* written once, below, and only as 220 */
            fputc('"', f);
            fputs(k, f);
            fputs("\" \"", f);
            fputs(v, f);
            fputs("\"\n", f);
        }

        /*
         * The dialect declaration, and it is not optional.
         *
         * The compiler decides how to read a face from this key alone: without
         * it the parser expects `shift shift rotate scale scale` and reads the
         * `[` of a Valve 220 texture axis as a number, then desynchronizes and
         * dies on the next brush. A donor BSP carries no mapversion of its
         * own, so it is emitted here as output metadata rather than inherited.
         */
        if (e == 0)
            fputs("\"mapversion\" \"220\"\n", f);

        /*
         * The brushes this entity owns, written inside it.
         *
         * Order is a variable of the seam diagnosis, not a detail: the
         * compiler resolves overlapping solids by CSG in the order it reads
         * them, so which of two brushes keeps the shared surface depends on
         * which came first. The donor's own .map order is gone - what survives
         * in the BSP is the order AFTER it was processed - so this is a
         * deliberate choice rather than a restoration.
         */
        /*
         * This entity's own areaportal brush, if it is one.
         *
         * Taken in file order, one each. The world loop below skips every
         * areaportal brush, so each is written exactly once and here.
         */
        const bool is_portal = entity_is(g, ent, "func_areaportal");
        uint32_t portal_brush = g->num_brushes;
        if (is_portal) {
            uint32_t seen = 0;
            for (uint32_t k = 0; k < g->num_brushes; k++) {
                if (g->brushes[k].model != 0
                    || !(g->brushes[k].contents & MAPGEN_CONTENTS_AREAPORTAL))
                    continue;
                if (seen++ == portal_taken) {
                    portal_brush = k;
                    break;
                }
            }
            portal_taken++;
        }

        for (uint32_t k = 0; k < g->num_brushes; k++) {
            const uint32_t b = MAPGEN_REVERSE_BRUSH_ORDER
                             ? g->num_brushes - 1 - k : k;
            const mapgen_geometry_brush_t *brush = &g->brushes[b];
            if (is_portal) {
                if (b != portal_brush)
                    continue;
            } else {
                if (brush->model != ent->model)
                    continue;
                if (ent->model == 0 && e != 0)
                    continue;      /* only worldspawn carries the world */
                /* An areaportal brush is written inside its own entity, and
                   the world must not claim it as well. */
                if (brush->model == 0
                    && (brush->contents & MAPGEN_CONTENTS_AREAPORTAL))
                    continue;
            }

            fputs("{\n", f);

            /*
             * Real faces first, then the sides with no winding of their own -
             * so that when one of those turns out to restate a face's plane,
             * it is the bevel that goes and never the wall.
             */
            /*
             * Does anything draw this brush?
             *
             * A clip brush, a ladder or a trigger volume has no face on any
             * side, so every side is flagged a bevel and the donor's compiler
             * has already added its own. Handing all of them back makes the
             * frozen compiler bevel a brush that is already bevelled, and the
             * extra plane clips it smaller - measured on q2dm1: five of
             * twenty-seven clip brushes come back with one more side, and the
             * player is stopped in sixteen places where the baseline lets him
             * through.
             *
             * A brush that IS drawn keeps its bevels: there the flag is
             * unreliable, the plane is often a real bounding one, and handing
             * it back is what puts the worst reproduced plane 700 times closer.
             */
            /*
             * "Drawn" is about textures, not about the bevel flag.
             *
             * The flag means "clips nothing off this brush", and a clip
             * brush's real sides clip plenty - so testing the flag classified
             * every clip brush as drawn and the rule did nothing. What makes a
             * brush collision-only is that no side of it has a texture: that
             * is why the writer has to invent one.
             */
            /*
             * Collision-only means CONTENTS, not textures.
             *
             * Testing for a textured side still let a clip brush through when
             * one of its sides happened to carry one - on q2dm3 that brush
             * came back with four extra planes. What decides it is what the
             * brush IS: a volume whose only contents are player clip, monster
             * clip or ladder is never drawn, so bevel precision buys nothing
             * there and handing the donor's bevels back only makes the frozen
             * compiler bevel a brush that is already bevelled.
             */
            #define VISIBLE_CONTENTS  (0x00000001 | 0x00000002 | 0x00000008                                        | 0x00000010 | 0x00000020 | 0x00000040)
            #define COLLISION_ONLY    (0x00010000 | 0x00020000 | 0x20000000)
            const bool drawn = (brush->contents & VISIBLE_CONTENTS) != 0
                            || (brush->contents & COLLISION_ONLY) == 0;
            #undef VISIBLE_CONTENTS
            #undef COLLISION_ONLY

            uint32_t order[MAPGEN_GEOMETRY_MAX_SIDES_PER_BRUSH];
            uint32_t ordered = 0;
            if (brush->num_sides <= MAPGEN_GEOMETRY_MAX_SIDES_PER_BRUSH) {
                for (int pass = 0; pass < 2; pass++) {
                    for (uint32_t s = 0; s < brush->num_sides; s++) {
                        if (g->sides[brush->first_side + s].bevel != (pass == 1))
                            continue;
                        order[ordered++] = s;
                    }
                }
            }

            for (uint32_t k = 0; k < ordered; k++) {
                const uint32_t s = order[k];
                const mapgen_geometry_side_t *side =
                    &g->sides[brush->first_side + s];
#if !MAPGEN_WRITE_BEVELS
                if (side->bevel)
                    continue;
#else
                /*
                 * Collision-only brushes hand back only what bounds them.
                 *
                 * A volume test - "does removing this plane make the brush
                 * bigger" - was tried here instead and reverted: it did not
                 * fix the second-generation leak it was written for, and it
                 * cost q2dm2 its mapping axis. The measurement is kept below
                 * for the diagnosis it belongs to.
                 */
                if (side->bevel && !drawn)
                    continue;
#endif

                /*
                 * A plane this brush has already stated.
                 *
                 * The compiler treats two planes as one within a hundredth of a
                 * unit, and it generates its own bevels for the collision hull
                 * that come back as near-duplicates of real faces - one arc
                 * segment carried its inner plane at d=-317.2622 and, three
                 * rows later, a bevel at -317.2637. Handing back both re-clips
                 * the brush by that hair, and the tighter copy takes the face
                 * off the map: that segment's whole inner wall vanished.
                 *
                 * So a brush states each of its planes once. Rounding that was
                 * allowed to become geometry is not geometry.
                 */
                bool duplicate = false;
                for (uint32_t p = 0; p < k && !duplicate; p++) {
                    const mapgen_geometry_side_t *earlier =
                        &g->sides[brush->first_side + order[p]];
                    const float dot = earlier->normal[0] * side->normal[0]
                                    + earlier->normal[1] * side->normal[1]
                                    + earlier->normal[2] * side->normal[2];
                    duplicate = dot > 0.9999f
                             && fabsf(earlier->dist - side->dist) < 0.05f;
                }
                if (duplicate)
                    continue;

                /*
                 * A bevel is restated where it cannot cut.
                 *
                 * See MAPGEN_BEVEL_OUTSET: the plane is redundant by
                 * construction, so moving it outward changes no solid, while
                 * leaving it exactly where it was lets the writer's own
                 * rounding move it INWARD and take a wall with it.
                 */
                mapgen_geometry_side_t written = *side;
                if (written.bevel)
                    written.dist += (float)MAPGEN_BEVEL_OUTSET;

                double pts[3][3];
                plane_points(&written, pts);

                for (int k = 0; k < 3; k++) {
                    fputs("( ", f);
                    for (int a = 0; a < 3; a++) {
                        write_f(f, pts[k][a], PLANE_POINT_DECIMALS);
                        fputc(' ', f);
                    }
                    fputs(") ", f);
                }

                fputs(side->texture[0] ? side->texture : "e1u1/clip", f);

                /*
                 * Valve 220 keeps the axis and the scale apart, while the BSP
                 * folds the scale into the axis. Split them back out - a unit
                 * axis and the reciprocal of its old length - and the mapping
                 * survives the round trip exactly.
                 */
                for (int a = 0; a < 2; a++) {
                    const double len = sqrt((double)side->axis[a][0] * side->axis[a][0]
                                          + (double)side->axis[a][1] * side->axis[a][1]
                                          + (double)side->axis[a][2] * side->axis[a][2]);
                    fputs(" [ ", f);
                    for (int i = 0; i < 3; i++) {
                        write_f(f, len > 0 ? side->axis[a][i] / len : (i == a ? 1 : 0), 6);
                        fputc(' ', f);
                    }
                    write_f(f, side->axis[a][3], 4);
                    fputs(" ]", f);
                }
                fputs(" 0", f);
                for (int a = 0; a < 2; a++) {
                    const double len = sqrt((double)side->axis[a][0] * side->axis[a][0]
                                          + (double)side->axis[a][1] * side->axis[a][1]
                                          + (double)side->axis[a][2] * side->axis[a][2]);
                    fputc(' ', f);
                    write_f(f, len > 0 ? 1.0 / len : 1.0, 6);
                }

                /*
                 * Contents, flags and value, on every side.
                 *
                 * Without them the compiler re-derives what a surface IS from
                 * its texture name, and a donor's water, lava, sky, detail and
                 * light surfaces all become ordinary walls that happen to look
                 * wet. The donor already answered this question; the answer is
                 * carried, not asked again.
                 */
                fputc(' ', f);
                write_f(f, brush->contents, 0);
                fputc(' ', f);
                write_f(f, side->flags, 0);
                fputc(' ', f);
                write_f(f, side->value, 0);
                fputc('\n', f);
            }
            fputs("}\n", f);
        }
        fputs("}\n", f);
    }

    const bool ok = ferror(f) == 0;
    const bool stored = MapGenFs_Close(f) == 0;
    return ok && stored ? MAPGEN_GEOMETRY_OK : MAPGEN_GEOMETRY_ERR_ARGS;
}
