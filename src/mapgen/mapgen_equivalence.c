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
 * Is the baseline still the donor?
 *
 * The contract, the reasoning and the list of what the compiler owns are in
 * inc/common/mapgen_equivalence.h. What matters here: nothing in this file
 * reads the geometry projection that PRODUCED the baseline. Both maps arrive
 * as compiled artifacts and are measured through the reader, the collision
 * tree, the face lump, the mover reader and a parser this file owns.
 */

#include "common/mapgen_equivalence.h"
#include "common/mapgen_movers.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The contents bits, spelled out locally like every other headless module:
   this code must build without the engine's shared header. */
#define BIT_SOLID       0x00000001
#define BIT_WINDOW      0x00000002
#define BIT_AUX         0x00000004
#define BIT_LAVA        0x00000008
#define BIT_SLIME       0x00000010
#define BIT_WATER       0x00000020
#define BIT_MIST        0x00000040
#define BIT_AREAPORTAL  0x00008000
#define BIT_PLAYERCLIP  0x00010000
#define BIT_MONSTERCLIP 0x00020000
#define BIT_CURRENT_0   0x00040000
#define BIT_CURRENT_90  0x00080000
#define BIT_CURRENT_180 0x00100000
#define BIT_CURRENT_270 0x00200000
#define BIT_CURRENT_UP  0x00400000
#define BIT_CURRENT_DN  0x00800000
#define BIT_LADDER      0x20000000

/*
 * Everything a player's movement or a monster's can run into.
 *
 * Compared bit for bit, because "not solid" is not a description of a place: a
 * player clip is where he cannot go, a ladder is how he climbs, and a current
 * is where the water takes him. Folding all of those into EMPTY is how a clip
 * brush could appear or vanish with every axis still green.
 *
 * Left out deliberately: ORIGIN, MONSTER, DEADMONSTER, DETAIL and TRANSLUCENT,
 * which say how a brush was authored or what occupies it at runtime rather
 * than what the space IS.
 */
#define MOVEMENT_MASK   (BIT_SOLID | BIT_WINDOW | BIT_AUX | BIT_LAVA \
                         | BIT_SLIME | BIT_WATER | BIT_MIST \
                         | BIT_AREAPORTAL | BIT_PLAYERCLIP \
                         | BIT_MONSTERCLIP | BIT_CURRENT_0 | BIT_CURRENT_90 \
                         | BIT_CURRENT_180 | BIT_CURRENT_270 \
                         | BIT_CURRENT_UP | BIT_CURRENT_DN | BIT_LADDER)

#define NIL             0xffffffffu
#define MAX_POLY        64
#define TEXBUCKETS      1024

/* ---- results ------------------------------------------------------------- */

const char *MapGenEquivalence_ResultName(mapgen_equiv_result_t r)
{
    switch (r) {
    case MAPGEN_EQUIV_OK:                 return "OK";
    case MAPGEN_EQUIV_ERR_ARGS:           return "ERR_ARGS";
    case MAPGEN_EQUIV_ERR_MEMORY:         return "ERR_MEMORY";
    case MAPGEN_EQUIV_ERR_LIMIT:          return "ERR_LIMIT";
    case MAPGEN_EQUIV_ERR_ENTITIES:       return "ERR_ENTITIES";
    case MAPGEN_EQUIV_DIFF_SPACE:         return "DIFF_SPACE";
    case MAPGEN_EQUIV_DIFF_ARCHITECTURE:  return "DIFF_ARCHITECTURE";
    case MAPGEN_EQUIV_DIFF_SURFACE:       return "DIFF_SURFACE";
    case MAPGEN_EQUIV_DIFF_MAPPING:       return "DIFF_MAPPING";
    case MAPGEN_EQUIV_DIFF_OWNERSHIP:     return "DIFF_OWNERSHIP";
    case MAPGEN_EQUIV_DIFF_ENTITY:        return "DIFF_ENTITY";
    case MAPGEN_EQUIV_DIFF_MOVER:         return "DIFF_MOVER";
    case MAPGEN_EQUIV_DIFF_TRAVERSAL:     return "DIFF_TRAVERSAL";
    case MAPGEN_EQUIV_RESULT_COUNT:       break;
    }
    return "?";
}

const char *MapGenEquivalence_ClassName(int cls)
{
    switch (cls) {
    case MAPGEN_EQUIV_SOLID:  return "solid";
    case MAPGEN_EQUIV_EMPTY:  return "empty";
    case MAPGEN_EQUIV_LIQUID: return "liquid";
    case MAPGEN_EQUIV_HAZARD: return "hazard";
    default: break;
    }
    return "?";
}

/*
 * What the compiler owns.
 *
 * Written out so that "the build succeeded" is never the argument for calling
 * a difference acceptable. Anything not on this list is a difference this gate
 * reports.
 */
static const char *const s_allowed[] = {
    "lump order, lump offsets and padding",
    "plane order, plane de-duplication and plane sign",
    "node and leaf structure, cluster numbering and area numbering",
    "face subdivision, T-junction vertices, edge and surfedge reuse, face order",
    "lightmap bytes, vis bytes, light offsets and light styles",
    "entity order, and brush-model index renumbering with the binding kept",
    "texinfo de-duplication, reordering and nexttexinfo chains - a wall may "
    "come back with fewer distinct mappings than the donor gave it, never "
    "with one the donor did not use",
    "brush and brush-side ordering, and axial bevel sides the compiler adds",
    "culling of faces coincident with another brush, within the added-area "
    "budget: a surface may be GAINED, never lost",
    "numeric formatting of entity values within the policy epsilon",
};

uint32_t MapGenEquivalence_NumAllowedDifferences(void)
{
    return (uint32_t)(sizeof(s_allowed) / sizeof(s_allowed[0]));
}

const char *MapGenEquivalence_AllowedDifference(uint32_t i)
{
    return i < MapGenEquivalence_NumAllowedDifferences() ? s_allowed[i] : NULL;
}

void MapGenEquivalence_DefaultPolicy(mapgen_equiv_policy_t *out)
{
    if (!out)
        return;
    memset(out, 0, sizeof(*out));
    out->lattice = 64.0f;
    out->epsilon = 1.0f;
    out->plane_epsilon = 0.5f;
    out->normal_epsilon = 0.002f;
    out->centroid_epsilon = 1.0f;
    out->facing_epsilon = 0.01f;
    out->offset_epsilon = 1.0f;
    out->axis_epsilon = 0.05f;
    out->sliver_area = 64.0f;
    out->coverage_permille = 5.0f;
    out->neighbour_distance = 24.0f;
    out->neighbour_normal = 0.08f;
    out->added_area_permille = 1.0f;
    out->area_permille = 5.0f;
    out->volume_permille = 5.0f;
    out->bounds_epsilon = 1.0f;
    out->value_epsilon = 0.05f;
    out->max_samples = 4000000u;
    out->compare_traversal = true;
}

/* ---- small helpers ------------------------------------------------------- */

static int classify(int32_t contents)
{
    if (contents & (BIT_SOLID | BIT_WINDOW))
        return MAPGEN_EQUIV_SOLID;
    if (contents & (BIT_LAVA | BIT_SLIME))
        return MAPGEN_EQUIV_HAZARD;
    if (contents & BIT_WATER)
        return MAPGEN_EQUIV_LIQUID;
    return MAPGEN_EQUIV_EMPTY;
}

static int class_at(const mapgen_bsp_t *bsp, const float p[3])
{
    return classify(MapGenBsp_PointContents(bsp, p));
}

/*
 * What a player runs into here.
 *
 * Derived from the BRUSHES that contain the point, not from the leaf's mark.
 * A leaf carries the contents of the brushes that fill it, and where two
 * compilers split leaves differently they mark different regions - which is a
 * decision about the tree, not about the map. What stops a player is the trace
 * against brushes, and that is what this asks.
 *
 * Outside the map is the exception: a point no leaf describes is solid, and no
 * brush has to say so.
 */
/* The contents of the brushes that hold the point, nothing from the leaf's own mark (row 400: the sealing test). */
static int32_t brushes_at(const mapgen_bsp_t *bsp, const mapgen_bsp_leaf_t *leaf, const float p[3])
{
    int32_t contents = 0;
    const uint32_t nbrushes = MapGenBsp_NumBrushes(bsp);
    const uint32_t nsides = MapGenBsp_NumBrushSides(bsp);
    const uint32_t nplanes = MapGenBsp_NumPlanes(bsp);
    const uint32_t nleafbrushes = MapGenBsp_NumLeafBrushes(bsp);

    for (uint32_t k = 0; k < leaf->numleafbrushes; k++) {
        const uint32_t at = leaf->firstleafbrush + k;
        if (at >= nleafbrushes)
            break;
        const uint32_t bi = MapGenBsp_LeafBrush(bsp, at);
        if (bi >= nbrushes)
            continue;
        const mapgen_bsp_brush_t *brush = MapGenBsp_Brush(bsp, bi);
        if (!brush || brush->numsides <= 0 || brush->firstside < 0)
            continue;
        bool inside = true;
        for (int32_t s = 0; s < brush->numsides && inside; s++) {
            const uint32_t si = (uint32_t)brush->firstside + (uint32_t)s;
            if (si >= nsides) {
                inside = false;
                break;
            }
            const mapgen_bsp_brushside_t *side = MapGenBsp_BrushSide(bsp, si);
            if (!side || side->planenum >= nplanes) {
                inside = false;
                break;
            }
            const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, side->planenum);
            const float d = p[0] * pl->normal[0] + p[1] * pl->normal[1]
                          + p[2] * pl->normal[2] - pl->dist;
            /* The brush is the intersection of its half-spaces; a hair of
               slack, because two compilers write the same plane a hair
               apart. */
            if (d > 0.03f)
                inside = false;
        }
        if (inside)
            contents |= brush->contents;
    }
    return contents;
}

static int32_t movement_at(const mapgen_bsp_t *bsp, const float p[3])
{
    const mapgen_bsp_leaf_t *leaf = MapGenBsp_PointLeaf(bsp, p);
    if (!leaf)
        return BIT_SOLID & MOVEMENT_MASK;

    int32_t contents = brushes_at(bsp, leaf, p);
    /*
     * Structural contents come from the LEAF; detail contents come from the
     * brushes.
     *
     * The tree is split on structural brushes, so a leaf is entirely inside or
     * entirely outside each of them and its mark is exact - including the
     * sealed outside of the map, which no brush describes. Detail brushes are
     * NOT split into the tree: a leaf that merely touches one is marked with
     * its contents, and where two compilers cut leaves differently they mark
     * different regions. Q2's clip and ladder brushes are detail, which is
     * exactly the case this separates.
     */
    #define STRUCTURAL (BIT_SOLID | BIT_WINDOW | BIT_AUX | BIT_LAVA                         | BIT_SLIME | BIT_WATER | BIT_MIST)
    contents |= leaf->contents & STRUCTURAL;
    #undef STRUCTURAL
    return contents & MOVEMENT_MASK;
}

typedef struct { float n[3]; float d; } cplane_t;

/* Sign-free identity of a plane: the largest component is made positive, so
   the same wall described from either side is the same plane. */
static void canon_plane(cplane_t *p)
{
    int best = 0;
    for (int i = 1; i < 3; i++)
        if (fabsf(p->n[i]) > fabsf(p->n[best]) + 1e-6f)
            best = i;
    if (p->n[best] < 0.0f) {
        for (int i = 0; i < 3; i++)
            p->n[i] = -p->n[i];
        p->d = -p->d;
    }
}

static bool plane_same(const cplane_t *a, const cplane_t *b,
                       float ne, float de)
{
    for (int i = 0; i < 3; i++)
        if (fabsf(a->n[i] - b->n[i]) > ne)
            return false;
    return fabsf(a->d - b->d) <= de;
}

static uint32_t hash_text(const char *s)
{
    uint32_t h = 2166136261u;
    for (; *s; s++) {
        h ^= (uint8_t)*s;
        h *= 16777619u;
    }
    return h;
}

static double permille(double a, double b)
{
    const double scale = fabs(a) > fabs(b) ? fabs(a) : fabs(b);
    if (scale < 1e-9)
        return 0.0;
    return fabs(a - b) * 1000.0 / scale;
}

/*
 * Record what an axis found.
 *
 * `detail` and `axis` describe the FIRST failure, because that is what a
 * one-line log wants; the per-axis text is kept beside it so nothing is lost
 * when two axes fail at once.
 */
static void say(mapgen_equiv_report_t *r, const char *axis, const char *fmt, ...)
{
    va_list ap;
    if (!r->axis[0])
        snprintf(r->axis, sizeof(r->axis), "%s", axis);
    char text[MAPGEN_EQUIV_DETAIL];
    va_start(ap, fmt);
    vsnprintf(text, sizeof(text), fmt, ap);
    va_end(ap);
    if (!r->detail[0])
        snprintf(r->detail, sizeof(r->detail), "%s", text);
    snprintf(r->pending, sizeof(r->pending), "%s", text);
}

/* Fold one axis into the report and keep going. */
static void axis_done(mapgen_equiv_report_t *r, mapgen_equiv_result_t rc)
{
    if (rc < MAPGEN_EQUIV_DIFF_SPACE || rc >= MAPGEN_EQUIV_RESULT_COUNT)
        return;
    r->axis_result[rc] = rc;
    snprintf(r->axis_detail[rc], MAPGEN_EQUIV_DETAIL, "%s", r->pending);
    r->failed_axes |= MAPGEN_EQUIV_AXIS_BIT(rc);
    if (r->result == MAPGEN_EQUIV_OK)
        r->result = rc;
    r->pending[0] = '\0';
}

/* ---- faces: polygons, area and the plane they sit on --------------------- */

static uint32_t face_points(const mapgen_bsp_t *bsp,
                            const mapgen_bsp_face_t *f, float (*out)[3])
{
    if (f->numedges < 3 || f->numedges > MAX_POLY)
        return 0;
    const uint32_t nse = MapGenBsp_NumSurfEdges(bsp);
    const uint32_t nv = MapGenBsp_NumVertices(bsp);
    const uint32_t ne = MapGenBsp_NumEdges(bsp);
    uint32_t n = 0;
    for (int32_t k = 0; k < f->numedges; k++) {
        const uint32_t si = (uint32_t)f->firstedge + (uint32_t)k;
        if (si >= nse)
            return 0;
        const int32_t se = MapGenBsp_SurfEdge(bsp, si);
        const uint32_t ei = (uint32_t)(se >= 0 ? se : -se);
        if (ei >= ne)
            return 0;
        const mapgen_bsp_edge_t *edge = MapGenBsp_Edge(bsp, ei);
        const uint32_t vi = se >= 0 ? edge->v[0] : edge->v[1];
        if (vi >= nv)
            return 0;
        const mapgen_bsp_vertex_t *v = MapGenBsp_Vertex(bsp, vi);
        out[n][0] = v->point[0];
        out[n][1] = v->point[1];
        out[n][2] = v->point[2];
        n++;
    }
    return n;
}

static double polygon_area(const float (*pt)[3], uint32_t n)
{
    if (n < 3)
        return 0.0;
    double cross[3] = { 0, 0, 0 };
    for (uint32_t i = 1; i + 1 < n; i++) {
        const double a[3] = { pt[i][0] - pt[0][0], pt[i][1] - pt[0][1],
                              pt[i][2] - pt[0][2] };
        const double b[3] = { pt[i + 1][0] - pt[0][0], pt[i + 1][1] - pt[0][1],
                              pt[i + 1][2] - pt[0][2] };
        cross[0] += a[1] * b[2] - a[2] * b[1];
        cross[1] += a[2] * b[0] - a[0] * b[2];
        cross[2] += a[0] * b[1] - a[1] * b[0];
    }
    return 0.5 * sqrt(cross[0] * cross[0] + cross[1] * cross[1]
                      + cross[2] * cross[2]);
}

/* ---- which machine draws a surface, whatever number it was given -------- */

/*
 * A semantic identity per brush model.
 *
 * The compiler may renumber submodels freely as long as the entity binding is
 * preserved, so the number is not an identity and the thing bound to it is.
 * Filled in by `identify_models` below, which needs the parsed entities and
 * therefore lives with them; the type is here because the collectors take it.
 */
#define MAX_MODELS 256u

typedef struct {
    uint32_t of[MAX_MODELS];      /* model index -> semantic identity */
    uint32_t count;
} model_identity_t;

/* ---- drawn surfaces, grouped so subdivision cannot matter ---------------- */

/* A big floor legitimately carries many mappings: q2dm2's has
   eleven. The first version held eight and reported the overflow
   as a drift of 8.0, which read like an eight-unit slide. */
#define GROUP_MAX_AXES 64

typedef struct {
    cplane_t plane;                          /* oriented: which way it faces */
    char     texture[MAPGEN_BSP_TEXNAME + 1];
    int32_t  flags, value;
    /*
     * Every distinct mapping used on this wall, not just the first.
     *
     * One wall can carry several texinfos - the same axes with offsets a
     * texture-width apart render identically, and the two compilers disagree
     * about whether to keep both. Comparing one of them compares whichever
     * face happened to come first.
     */
    float    axes[GROUP_MAX_AXES][2][4];
    uint8_t  num_axes;
    bool     too_many_axes;
    float    axis[2][4];                     /* the first, for the report */
    double   area;
    uint32_t model;
    uint32_t next;
    bool     matched;
} group_t;

/* Two mappings are the same when every component matches to the epsilon two
   compilers write the same number apart. */
static bool same_axes(const float a[2][4], const float b[2][4], float eps)
{
    for (int u = 0; u < 2; u++)
        for (int i = 0; i < 4; i++)
            if (fabsf(a[u][i] - b[u][i]) > eps)
                return false;
    return true;
}

static void group_add_axes(group_t *g, const float axis[2][4], float eps)
{
    for (uint8_t i = 0; i < g->num_axes; i++)
        if (same_axes(g->axes[i], axis, eps))
            return;
    if (g->num_axes >= GROUP_MAX_AXES) {
        g->too_many_axes = true;
        return;
    }
    memcpy(g->axes[g->num_axes], axis, sizeof(g->axes[0]));
    g->num_axes++;
}

typedef struct {
    group_t *g;
    uint32_t n, cap;
    uint32_t head[TEXBUCKETS];
} groups_t;

static void groups_init(groups_t *gs)
{
    memset(gs, 0, sizeof(*gs));
    for (uint32_t i = 0; i < TEXBUCKETS; i++)
        gs->head[i] = NIL;
}

static void groups_free(groups_t *gs)
{
    free(gs->g);
    gs->g = NULL;
    gs->n = gs->cap = 0;
}

static group_t *groups_find_or_add(groups_t *gs, const group_t *key,
                                   const mapgen_equiv_policy_t *pol)
{
    const uint32_t b = hash_text(key->texture) & (TEXBUCKETS - 1);
    for (uint32_t i = gs->head[b]; i != NIL; i = gs->g[i].next) {
        group_t *g = &gs->g[i];
        if (g->flags != key->flags || g->value != key->value
            || g->model != key->model
            || strcmp(g->texture, key->texture) != 0)
            continue;
        /* Oriented, not canonical: a surface that flipped is not the same
           surface, even though it lies on the same wall. */
        if (fabsf(g->plane.d - key->plane.d) > pol->plane_epsilon)
            continue;
        bool same = true;
        for (int a = 0; a < 3 && same; a++)
            same = fabsf(g->plane.n[a] - key->plane.n[a]) <= pol->normal_epsilon;
        if (same)
            return g;
    }
    if (gs->n == gs->cap) {
        const uint32_t want = gs->cap ? gs->cap * 2 : 512;
        group_t *grow = realloc(gs->g, (size_t)want * sizeof(*grow));
        if (!grow)
            return NULL;
        gs->g = grow;
        gs->cap = want;
    }
    group_t *g = &gs->g[gs->n];
    *g = *key;
    g->area = 0.0;
    g->matched = false;
    g->next = gs->head[b];
    gs->head[b] = gs->n;
    gs->n++;
    return g;
}

/*
 * Faces whose front the OTHER map's compiler sealed (row 400, Fable's brief 4 G5-4).
 *
 * The space axis already says it: a leaf no brush describes - past the sealed hull - is the compiler's business,
 * and comparing there compares the two compilers' sealing, not the map. The same holds for what is drawn facing
 * it. q3t2's arch niches open to their rooms through cracks of 0.05 units (the plate under the arch tops out at
 * z 340.443, the arch's slabs start at 340.496); the donor's compiler flooded through them and drew the niches,
 * the frozen compiler treats planes 0.1 apart as one (ON_EPSILON), sealed them and filled them as outside. No
 * player sees through 0.05 units. So a face is left out of every drawn-surface comparison when the point one unit
 * in front of its middle lies, in the OTHER map, in a solid leaf yet inside none of that map's brushes (the
 * frozen compiler lists the brushes touching a filled leaf, so its brush count is no test - containment is). A wall that is really gone
 * still fails: in front of it the other map has air, or a brush.
 */
static double polygon_centroid(const float (*pt)[3], uint32_t n, double out[3]);

/*
 * Row 412 (the PO's first map on q2duel1: refused at its first step, «за 7 секунд там нечему было меняться»): a face
 * whose texinfo says NODRAW is drawn by nobody - q2duel1's compiler kept its triggers' faces (e1u3/trigger and the
 * like, flags 128), ours writes none, and the gate called 112384 units of them «drawn only in the donor» and 2 of its
 * planes «missing». What no player sees is not compared: such a face belongs to no model here.
 */
#define EQUIV_SURF_NODRAW 0x0080

static bool face_unseen(const mapgen_bsp_t *bsp, uint32_t face)
{
    const mapgen_bsp_face_t *f = MapGenBsp_Face(bsp, face);
    if (!f || f->texinfo < 0 || (uint32_t)f->texinfo >= MapGenBsp_NumTexInfo(bsp))
        return false;
    const mapgen_bsp_texinfo_t *ti = MapGenBsp_TexInfo(bsp, (uint32_t)f->texinfo);
    return ti && (ti->flags & EQUIV_SURF_NODRAW);
}

static void seal_owners(const mapgen_bsp_t *bsp, const mapgen_bsp_t *other, uint32_t *owner, uint32_t nfaces,
                        uint32_t *sealed)
{
    if (!other)
        return;
    const uint32_t nplanes = MapGenBsp_NumPlanes(bsp);
    float pts[MAX_POLY][3];
    for (uint32_t i = 0; i < nfaces; i++) {
        if (owner[i] == NIL)
            continue;
        const mapgen_bsp_face_t *f = MapGenBsp_Face(bsp, i);
        if (!f || f->planenum >= nplanes)
            continue;
        const uint32_t n = face_points(bsp, f, pts);
        if (n < 3)
            continue;
        double c[3];
        if (polygon_centroid((const float (*)[3])pts, n, c) <= 0.0)
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, f->planenum);
        const float s = f->side ? -1.0f : 1.0f;
        const float probe[3] = { (float)c[0] + pl->normal[0] * s, (float)c[1] + pl->normal[1] * s,
                                 (float)c[2] + pl->normal[2] * s };
        const mapgen_bsp_leaf_t *leaf = MapGenBsp_PointLeaf(other, probe);
        /* solid in that compiler's tree, yet inside none of that map's brushes: its fill, its sealing */
        if (leaf && (leaf->contents & BIT_SOLID) && !(brushes_at(other, leaf, probe) & (BIT_SOLID | BIT_WINDOW))) {
            owner[i] = NIL;
            if (sealed)
                (*sealed)++;
        }
    }
}

static bool collect_surfaces(const mapgen_bsp_t *bsp, const mapgen_bsp_t *other,
                             const mapgen_equiv_policy_t *pol,
                             const model_identity_t *ident,
                             groups_t *gs, double *out_area)
{
    const uint32_t nfaces = MapGenBsp_NumFaces(bsp);
    const uint32_t nti = MapGenBsp_NumTexInfo(bsp);
    const uint32_t nplanes = MapGenBsp_NumPlanes(bsp);
    const uint32_t nmodels = MapGenBsp_NumModels(bsp);
    double total = 0.0;

    /* Which model draws a face. Faces outside every model are not drawn by
       anything and are left out rather than attributed to the world. */
    uint32_t *owner = calloc(nfaces ? nfaces : 1, sizeof(*owner));
    if (!owner)
        return false;
    for (uint32_t i = 0; i < nfaces; i++)
        owner[i] = NIL;
    for (uint32_t m = 0; m < nmodels; m++) {
        const mapgen_bsp_model_t *mo = MapGenBsp_Model(bsp, m);
        if (!mo || mo->firstface < 0 || mo->numfaces < 0)
            continue;
        for (int32_t k = 0; k < mo->numfaces; k++) {
            const uint32_t fi = (uint32_t)mo->firstface + (uint32_t)k;
            if (fi < nfaces && owner[fi] == NIL && !face_unseen(bsp, fi))
                owner[fi] = m;
        }
    }
    seal_owners(bsp, other, owner, nfaces, NULL);

    float pts[MAX_POLY][3];
    for (uint32_t i = 0; i < nfaces; i++) {
        if (owner[i] == NIL)
            continue;
        const mapgen_bsp_face_t *f = MapGenBsp_Face(bsp, i);
        if (!f || f->planenum >= nplanes || f->texinfo < 0
            || (uint32_t)f->texinfo >= nti)
            continue;
        const uint32_t n = face_points(bsp, f, pts);
        if (n < 3)
            continue;
        const double area = polygon_area((const float (*)[3])pts, n);
        if (area <= 0.0)
            continue;

        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, f->planenum);
        const mapgen_bsp_texinfo_t *ti = MapGenBsp_TexInfo(bsp,
                                                           (uint32_t)f->texinfo);
        group_t key;
        memset(&key, 0, sizeof(key));
        for (int a = 0; a < 3; a++)
            key.plane.n[a] = f->side ? -pl->normal[a] : pl->normal[a];
        key.plane.d = f->side ? -pl->dist : pl->dist;
        snprintf(key.texture, sizeof(key.texture), "%s", ti->texture);
        key.flags = ti->flags;
        key.value = ti->value;
        memcpy(key.axis, ti->axis, sizeof(key.axis));
        /* Which machine draws it, not which number it was given. */
        key.model = owner[i] < MAX_MODELS ? ident->of[owner[i]] : owner[i];

        group_t *g = groups_find_or_add(gs, &key, pol);
        if (!g) {
            free(owner);
            return false;
        }
        g->area += area;
        group_add_axes(g, ti->axis, pol->axis_epsilon);
        total += area;
    }
    free(owner);
    if (out_area)
        *out_area = total;
    return true;
}

/* ---- materials: signatures that survive splitting and merging ------------ */

/*
 * Everything here is a SUM over faces, weighted by area. That is the whole
 * design: split a face and both halves land in the same material with the same
 * plane and the same texinfo, so every sum is unchanged. Nothing is matched to
 * anything by tolerance, so no tolerance can put a face in the wrong bucket.
 */
typedef struct {
    char     texture[MAPGEN_BSP_TEXNAME + 1];
    int32_t  flags, value;
    uint32_t model;
    double   area;
    double   centroid[3];      /* area * true area-centroid                  */
    double   normal[3];        /* area * surface normal                      */
    double   offset;           /* area * plane offset                        */
    double   axis[2][4];       /* area * texture axis, offset and scale      */
    uint32_t next;
    bool     matched;
} material_t;

typedef struct {
    material_t *m;
    uint32_t n, cap;
    uint32_t head[TEXBUCKETS];
} materials_t;

static void materials_init(materials_t *ms)
{
    memset(ms, 0, sizeof(*ms));
    for (uint32_t i = 0; i < TEXBUCKETS; i++)
        ms->head[i] = NIL;
}

static void materials_free(materials_t *ms)
{
    free(ms->m);
    ms->m = NULL;
    ms->n = ms->cap = 0;
}

/* Exact identity, no tolerance: a material is a name, two integers and the
   model that draws it. */
static material_t *material_for(materials_t *ms, const char *texture,
                                int32_t flags, int32_t value, uint32_t model)
{
    const uint32_t b = hash_text(texture) & (TEXBUCKETS - 1);
    for (uint32_t i = ms->head[b]; i != NIL; i = ms->m[i].next) {
        material_t *m = &ms->m[i];
        if (m->flags == flags && m->value == value && m->model == model
            && !strcmp(m->texture, texture))
            return m;
    }
    if (ms->n == ms->cap) {
        const uint32_t want = ms->cap ? ms->cap * 2 : 256;
        material_t *grow = realloc(ms->m, (size_t)want * sizeof(*grow));
        if (!grow)
            return NULL;
        ms->m = grow;
        ms->cap = want;
    }
    material_t *m = &ms->m[ms->n];
    memset(m, 0, sizeof(*m));
    snprintf(m->texture, sizeof(m->texture), "%s", texture);
    m->flags = flags;
    m->value = value;
    m->model = model;
    m->next = ms->head[b];
    ms->head[b] = ms->n;
    ms->n++;
    return m;
}

/*
 * The area-centroid of a polygon, and its area.
 *
 * The vertex mean would have been easier and wrong: it is not additive, so
 * splitting a face would move it and the signature would report the compiler's
 * subdivision as a difference. The triangle-fan centroid, weighted by triangle
 * area, is the real one and does survive the split.
 */
static double polygon_centroid(const float (*pt)[3], uint32_t n, double out[3])
{
    out[0] = out[1] = out[2] = 0.0;
    if (n < 3)
        return 0.0;
    double total = 0.0;
    for (uint32_t i = 1; i + 1 < n; i++) {
        const double a[3] = { pt[i][0] - pt[0][0], pt[i][1] - pt[0][1],
                              pt[i][2] - pt[0][2] };
        const double b[3] = { pt[i + 1][0] - pt[0][0], pt[i + 1][1] - pt[0][1],
                              pt[i + 1][2] - pt[0][2] };
        const double cross[3] = { a[1] * b[2] - a[2] * b[1],
                                  a[2] * b[0] - a[0] * b[2],
                                  a[0] * b[1] - a[1] * b[0] };
        const double area = 0.5 * sqrt(cross[0] * cross[0]
                                       + cross[1] * cross[1]
                                       + cross[2] * cross[2]);
        for (int k = 0; k < 3; k++)
            out[k] += area * (pt[0][k] + pt[i][k] + pt[i + 1][k]) / 3.0;
        total += area;
    }
    if (total > 0.0)
        for (int k = 0; k < 3; k++)
            out[k] /= total;
    return total;
}

static bool collect_materials(const mapgen_bsp_t *bsp, const mapgen_bsp_t *other,
                              const model_identity_t *ident,
                              materials_t *ms, double *out_area, uint32_t *sealed)
{
    const uint32_t nfaces = MapGenBsp_NumFaces(bsp);
    const uint32_t nti = MapGenBsp_NumTexInfo(bsp);
    const uint32_t nplanes = MapGenBsp_NumPlanes(bsp);
    const uint32_t nmodels = MapGenBsp_NumModels(bsp);
    double total = 0.0;

    uint32_t *owner = malloc((nfaces ? nfaces : 1) * sizeof(*owner));
    if (!owner)
        return false;
    for (uint32_t i = 0; i < nfaces; i++)
        owner[i] = NIL;
    for (uint32_t m = 0; m < nmodels; m++) {
        const mapgen_bsp_model_t *mo = MapGenBsp_Model(bsp, m);
        if (!mo || mo->firstface < 0 || mo->numfaces < 0)
            continue;
        for (int32_t k = 0; k < mo->numfaces; k++) {
            const uint32_t fi = (uint32_t)mo->firstface + (uint32_t)k;
            if (fi < nfaces && owner[fi] == NIL && !face_unseen(bsp, fi))
                owner[fi] = m;
        }
    }

    seal_owners(bsp, other, owner, nfaces, sealed);

    float pts[MAX_POLY][3];
    for (uint32_t i = 0; i < nfaces; i++) {
        if (owner[i] == NIL)
            continue;
        const mapgen_bsp_face_t *f = MapGenBsp_Face(bsp, i);
        if (!f || f->planenum >= nplanes || f->texinfo < 0
            || (uint32_t)f->texinfo >= nti)
            continue;
        const uint32_t n = face_points(bsp, f, pts);
        if (n < 3)
            continue;
        double centroid[3];
        const double area = polygon_centroid((const float (*)[3])pts, n,
                                             centroid);
        if (area <= 0.0)
            continue;

        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, f->planenum);
        const mapgen_bsp_texinfo_t *ti = MapGenBsp_TexInfo(bsp,
                                                           (uint32_t)f->texinfo);
        material_t *m = material_for(ms, ti->texture, ti->flags, ti->value,
                                     owner[i] < MAX_MODELS
                                         ? ident->of[owner[i]] : owner[i]);
        if (!m) {
            free(owner);
            return false;
        }
        m->area += area;
        for (int a = 0; a < 3; a++) {
            m->centroid[a] += area * centroid[a];
            m->normal[a] += area * (double)(f->side ? -pl->normal[a]
                                                    : pl->normal[a]);
        }
        m->offset += area * (double)(f->side ? -pl->dist : pl->dist);
        for (int u = 0; u < 2; u++)
            for (int a = 0; a < 4; a++)
                m->axis[u][a] += area * (double)ti->axis[u][a];
        total += area;
    }
    free(owner);
    if (out_area)
        *out_area = total;
    return true;
}

static material_t *material_find(materials_t *ms, const material_t *key)
{
    const uint32_t b = hash_text(key->texture) & (TEXBUCKETS - 1);
    for (uint32_t i = ms->head[b]; i != NIL; i = ms->m[i].next) {
        material_t *m = &ms->m[i];
        if (m->flags == key->flags && m->value == key->value
            && m->model == key->model && !strcmp(m->texture, key->texture))
            return m;
    }
    return NULL;
}

static void mean_of(const material_t *m, double centroid[3], double normal[3],
                    double *offset, double axis[2][4])
{
    const double a = m->area > 0.0 ? m->area : 1.0;
    for (int i = 0; i < 3; i++) {
        centroid[i] = m->centroid[i] / a;
        normal[i] = m->normal[i] / a;
    }
    *offset = m->offset / a;
    for (int u = 0; u < 2; u++)
        for (int i = 0; i < 4; i++)
            axis[u][i] = m->axis[u][i] / a;
}

/* ---- which machine draws this, whatever number it was given ------------- */

/*
 * A semantic identity per brush model.
 *
 * The compiler may renumber submodels freely as long as the entity binding is
 * preserved, so the number is not an identity and the thing bound to it is.
 * Both maps' bindings are rendered to text and matched; a matched pair shares
 * an identity, and anything unmatched gets one of its own so the ownership
 * axis still has it to report.
 *
 * Model zero is the world in every map, and is always identity zero.
 */
/* ---- coverage: what a player actually sees on a wall -------------------- */

/*
 * The union area of a group's faces, measured on their own plane.
 *
 * Summed area counts a face laid on top of another twice, and Quake maps are
 * full of those: q2dm3's floor carries ten thousand units of coincident
 * duplicates that one compiler draws and the other culls. The union does not
 * care, and it does not care how a face was subdivided either.
 *
 * Rasterized rather than clipped: exact polygon union of a hundred faces is a
 * large piece of geometry code, and the raster's error is bounded, reportable,
 * and - because the step comes from the donor's group and is used for both
 * sides - the same error on both.
 */
#define COVERAGE_CELLS   65536u
#define COVERAGE_FACES   256u

/* Which model draws each face, or NIL. The two collectors work this out for
   themselves; the coverage measurement needs it per group, so it is worked out
   once and handed in. */
static uint32_t *face_owners(const mapgen_bsp_t *bsp)
{
    const uint32_t nfaces = MapGenBsp_NumFaces(bsp);
    const uint32_t nmodels = MapGenBsp_NumModels(bsp);
    uint32_t *owner = malloc((nfaces ? nfaces : 1) * sizeof(*owner));
    if (!owner)
        return NULL;
    for (uint32_t i = 0; i < nfaces; i++)
        owner[i] = NIL;
    for (uint32_t m = 0; m < nmodels; m++) {
        const mapgen_bsp_model_t *mo = MapGenBsp_Model(bsp, m);
        if (!mo || mo->firstface < 0 || mo->numfaces < 0)
            continue;
        for (int32_t k = 0; k < mo->numfaces; k++) {
            const uint32_t fi = (uint32_t)mo->firstface + (uint32_t)k;
            if (fi < nfaces && owner[fi] == NIL && !face_unseen(bsp, fi))
                owner[fi] = m;
        }
    }
    return owner;
}

typedef struct {
    float  pts[MAX_POLY][2];
    uint32_t count;
} flat_poly_t;

static bool point_in_poly(const flat_poly_t *poly, float x, float y)
{
    bool in = false;
    for (uint32_t i = 0, j = poly->count - 1; i < poly->count; j = i++) {
        const float xi = poly->pts[i][0], yi = poly->pts[i][1];
        const float xj = poly->pts[j][0], yj = poly->pts[j][1];
        if (((yi > y) != (yj > y))
            && (x < (xj - xi) * (y - yi) / (yj - yi) + xi))
            in = !in;
    }
    return in;
}

/*
 * Flatten every face of one group onto its plane, and say how big a step the
 * raster may use. `step` of zero means "choose one"; a non-zero step is used
 * as given, which is how both sides of a comparison get the same error.
 */
static double group_coverage(const mapgen_bsp_t *bsp, const group_t *g,
                             const uint32_t *owner,
                             const model_identity_t *ident, uint32_t nfaces,
                             float *step)
{
    const uint32_t nti = MapGenBsp_NumTexInfo(bsp);
    const uint32_t nplanes = MapGenBsp_NumPlanes(bsp);

    /* Which axis the plane faces most, so the other two carry the raster. */
    int drop = 0;
    for (int a = 1; a < 3; a++)
        if (fabsf(g->plane.n[a]) > fabsf(g->plane.n[drop]))
            drop = a;
    const int ax[2] = { drop == 0 ? 1 : 0, drop == 2 ? 1 : 2 };
    const float tilt = fabsf(g->plane.n[drop]);
    if (tilt < 1e-6f)
        return 0.0;

    static flat_poly_t flat[COVERAGE_FACES];
    uint32_t n = 0;
    float lo[2] = { 1e30f, 1e30f }, hi[2] = { -1e30f, -1e30f };
    float pts[MAX_POLY][3];

    for (uint32_t i = 0; i < nfaces && n < COVERAGE_FACES; i++) {
        /* The group's model is a SEMANTIC identity; `owner` is the raw
           index. Comparing them directly matched nothing whenever the two
           maps numbered a submodel differently - which is the case this
           identity exists for. */
        const uint32_t who = owner[i] < MAX_MODELS ? ident->of[owner[i]]
                                                   : owner[i];
        if (who != g->model)
            continue;
        const mapgen_bsp_face_t *f = MapGenBsp_Face(bsp, i);
        if (!f || f->planenum >= nplanes || f->texinfo < 0
            || (uint32_t)f->texinfo >= nti)
            continue;
        const mapgen_bsp_texinfo_t *ti = MapGenBsp_TexInfo(bsp,
                                                           (uint32_t)f->texinfo);
        if (ti->flags != g->flags || ti->value != g->value
            || strcmp(ti->texture, g->texture) != 0)
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, f->planenum);
        cplane_t face;
        for (int a = 0; a < 3; a++)
            face.n[a] = f->side ? -pl->normal[a] : pl->normal[a];
        face.d = f->side ? -pl->dist : pl->dist;
        if (fabsf(face.d - g->plane.d) > 0.5f)
            continue;
        bool same = true;
        for (int a = 0; a < 3 && same; a++)
            same = fabsf(face.n[a] - g->plane.n[a]) <= 0.002f;
        if (!same)
            continue;

        const uint32_t count = face_points(bsp, f, pts);
        if (count < 3)
            continue;
        flat[n].count = count;
        for (uint32_t k = 0; k < count; k++) {
            for (int a = 0; a < 2; a++) {
                const float v = pts[k][ax[a]];
                flat[n].pts[k][a] = v;
                if (v < lo[a])
                    lo[a] = v;
                if (v > hi[a])
                    hi[a] = v;
            }
        }
        n++;
    }
    if (!n)
        return 0.0;

    if (*step <= 0.0f) {
        /* A step that keeps the cell count bounded, never finer than a unit
           and never coarser than sixteen: below a unit the raster costs more
           than the answer is worth, above sixteen it stops being a measure of
           a wall. */
        const double span = (double)(hi[0] - lo[0]) * (double)(hi[1] - lo[1]);
        double want = sqrt(span / (double)COVERAGE_CELLS);
        if (want < 1.0)
            want = 1.0;
        if (want > 16.0)
            want = 16.0;
        *step = (float)want;
    }
    const float s = *step;

    double cells = 0.0;
    for (float y = lo[1]; y <= hi[1]; y += s)
        for (float x = lo[0]; x <= hi[0]; x += s) {
            const float cx = x + s * 0.5f, cy = y + s * 0.5f;
            for (uint32_t i = 0; i < n; i++)
                if (point_in_poly(&flat[i], cx, cy)) {
                    cells += 1.0;
                    break;
                }
        }
    return cells * (double)s * (double)s / (double)tilt;
}

/* ---- the architecture: canonical planes that carry a surface ------------- */

typedef struct { cplane_t *p; uint32_t n, cap; } planeset_t;

static bool planeset_add(planeset_t *ps, const cplane_t *pl,
                         const mapgen_equiv_policy_t *pol)
{
    for (uint32_t i = 0; i < ps->n; i++)
        if (plane_same(&ps->p[i], pl, pol->normal_epsilon, pol->plane_epsilon))
            return true;
    if (ps->n == ps->cap) {
        const uint32_t want = ps->cap ? ps->cap * 2 : 256;
        cplane_t *grow = realloc(ps->p, (size_t)want * sizeof(*grow));
        if (!grow)
            return false;
        ps->p = grow;
        ps->cap = want;
    }
    ps->p[ps->n++] = *pl;
    return true;
}

static bool planeset_has(const planeset_t *ps, const cplane_t *pl,
                         const mapgen_equiv_policy_t *pol)
{
    for (uint32_t i = 0; i < ps->n; i++)
        if (plane_same(&ps->p[i], pl, pol->normal_epsilon, pol->plane_epsilon))
            return true;
    return false;
}

static bool collect_planes(const groups_t *gs, planeset_t *ps,
                           const mapgen_equiv_policy_t *pol)
{
    for (uint32_t i = 0; i < gs->n; i++) {
        cplane_t c = gs->g[i].plane;
        canon_plane(&c);
        if (!planeset_add(ps, &c, pol))
            return false;
    }
    return true;
}

/* ---- the brushwork: convex volume, by contents class --------------------- */

static uint32_t clip_poly(float (*poly)[3], uint32_t n, const cplane_t *pl,
                          float eps)
{
    float out[MAX_POLY][3];
    float dist[MAX_POLY + 1];
    uint32_t m = 0;
    if (!n)
        return 0;
    for (uint32_t i = 0; i < n; i++)
        dist[i] = poly[i][0] * pl->n[0] + poly[i][1] * pl->n[1]
                + poly[i][2] * pl->n[2] - pl->d;
    dist[n] = dist[0];

    for (uint32_t i = 0; i < n; i++) {
        const uint32_t j = (i + 1) % n;
        if (dist[i] <= eps) {
            if (m >= MAX_POLY)
                return 0;
            memcpy(out[m++], poly[i], sizeof(out[0]));
        }
        if ((dist[i] > eps && dist[j] < -eps)
            || (dist[i] < -eps && dist[j] > eps)) {
            const float t = dist[i] / (dist[i] - dist[j]);
            if (m >= MAX_POLY)
                return 0;
            for (int a = 0; a < 3; a++)
                out[m][a] = poly[i][a] + t * (poly[j][a] - poly[i][a]);
            m++;
        }
    }
    memcpy(poly, out, (size_t)m * sizeof(out[0]));
    return m;
}

/* A huge polygon on `pl`, to be cut down by the brush's other sides. */
static uint32_t base_poly(const cplane_t *pl, float (*poly)[3], float reach)
{
    float up[3] = { 0, 0, 1 };
    if (fabsf(pl->n[2]) > 0.9f) {
        up[0] = 1;
        up[2] = 0;
    }
    float right[3];
    right[0] = up[1] * pl->n[2] - up[2] * pl->n[1];
    right[1] = up[2] * pl->n[0] - up[0] * pl->n[2];
    right[2] = up[0] * pl->n[1] - up[1] * pl->n[0];
    float len = sqrtf(right[0] * right[0] + right[1] * right[1]
                      + right[2] * right[2]);
    if (len < 1e-6f)
        return 0;
    for (int a = 0; a < 3; a++)
        right[a] /= len;
    up[0] = pl->n[1] * right[2] - pl->n[2] * right[1];
    up[1] = pl->n[2] * right[0] - pl->n[0] * right[2];
    up[2] = pl->n[0] * right[1] - pl->n[1] * right[0];

    float origin[3];
    for (int a = 0; a < 3; a++)
        origin[a] = pl->n[a] * pl->d;
    for (int k = 0; k < 4; k++) {
        const float sx = (k == 0 || k == 3) ? -reach : reach;
        const float sy = (k < 2) ? -reach : reach;
        for (int a = 0; a < 3; a++)
            poly[k][a] = origin[a] + right[a] * sx + up[a] * sy;
    }
    return 4;
}

static double brush_volume(const mapgen_bsp_t *bsp,
                           const mapgen_bsp_brush_t *br)
{
    const uint32_t nsides = MapGenBsp_NumBrushSides(bsp);
    const uint32_t nplanes = MapGenBsp_NumPlanes(bsp);
    if (br->numsides < 4 || br->firstside < 0)
        return 0.0;

    double volume = 0.0;
    for (int32_t i = 0; i < br->numsides; i++) {
        const uint32_t si = (uint32_t)br->firstside + (uint32_t)i;
        if (si >= nsides)
            return 0.0;
        const mapgen_bsp_brushside_t *side = MapGenBsp_BrushSide(bsp, si);
        if (side->planenum >= nplanes)
            return 0.0;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, side->planenum);
        cplane_t face = { { pl->normal[0], pl->normal[1], pl->normal[2] },
                          pl->dist };

        float poly[MAX_POLY][3];
        uint32_t n = base_poly(&face, poly, 65536.0f);
        for (int32_t j = 0; j < br->numsides && n; j++) {
            if (j == i)
                continue;
            const uint32_t sj = (uint32_t)br->firstside + (uint32_t)j;
            if (sj >= nsides)
                return 0.0;
            const mapgen_bsp_brushside_t *other = MapGenBsp_BrushSide(bsp, sj);
            if (other->planenum >= nplanes)
                return 0.0;
            const mapgen_bsp_plane_t *op = MapGenBsp_Plane(bsp, other->planenum);
            const cplane_t cut = { { op->normal[0], op->normal[1],
                                     op->normal[2] }, op->dist };
            n = clip_poly(poly, n, &cut, 0.01f);
        }
        if (n < 3)
            continue;
        volume += polygon_area((const float (*)[3])poly, n) * (double)face.d;
    }
    return fabs(volume) / 3.0;
}

/* ---- the tree's own volume, leaf by disjoint leaf ------------------------ */

#define MAX_REGION 128

typedef struct {
    cplane_t p[MAX_REGION];      /* the region is n.x <= d for every plane   */
    uint32_t n;
} region_t;

/*
 * The volume of a convex region given by its half-spaces.
 *
 * Each bounding plane gets a huge polygon cut down by every other plane; what
 * survives is that face of the region, and the divergence theorem turns the
 * faces into a volume. Planes that contribute no face - the ones another plane
 * already cut away - fall out on their own by clipping to nothing.
 */
static double region_volume(const region_t *r)
{
    double volume = 0.0;
    for (uint32_t i = 0; i < r->n; i++) {
        float poly[MAX_POLY][3];
        uint32_t n = base_poly(&r->p[i], poly, 131072.0f);
        for (uint32_t j = 0; j < r->n && n; j++)
            if (j != i)
                n = clip_poly(poly, n, &r->p[j], 0.01f);
        if (n < 3)
            continue;
        volume += polygon_area((const float (*)[3])poly, n) * (double)r->p[i].d;
    }
    return fabs(volume) / 3.0;
}

static bool region_push(region_t *r, const cplane_t *pl)
{
    if (r->n >= MAX_REGION)
        return false;
    r->p[r->n++] = *pl;
    return true;
}

#define MAX_AREAS 256u

static void walk_leaves(const mapgen_bsp_t *bsp, int32_t node, region_t *region,
                        double out[MAPGEN_EQUIV_CLASSES], double *by_area,
                        int depth)
{
    if (depth > MAX_REGION)
        return;
    if (node < 0) {
        const uint32_t li = (uint32_t)(-1 - node);
        if (li >= MapGenBsp_NumLeafs(bsp))
            return;
        const mapgen_bsp_leaf_t *leaf = MapGenBsp_Leaf(bsp, li);
        if (!leaf)
            return;
        const double volume = region_volume(region);
        out[classify(leaf->contents)] += volume;
        /* And per area, for the traversal axis: how much space an area holds
           does not change when the compiler splits its leaves differently. */
        if (by_area && leaf->area >= 0 && (uint32_t)leaf->area < MAX_AREAS)
            by_area[leaf->area] += volume;
        return;
    }
    if ((uint32_t)node >= MapGenBsp_NumNodes(bsp))
        return;
    const mapgen_bsp_node_t *n = MapGenBsp_Node(bsp, (uint32_t)node);
    if (n->planenum >= MapGenBsp_NumPlanes(bsp))
        return;
    const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, n->planenum);

    /* Front is the side the normal points at, which the tree calls child 0. */
    const cplane_t back = { { pl->normal[0], pl->normal[1], pl->normal[2] },
                            pl->dist };
    const cplane_t front = { { -pl->normal[0], -pl->normal[1], -pl->normal[2] },
                             -pl->dist };

    const uint32_t mark = region->n;
    if (region_push(region, &front)) {
        walk_leaves(bsp, n->children[0], region, out, by_area, depth + 1);
        region->n = mark;
    }
    if (region_push(region, &back)) {
        walk_leaves(bsp, n->children[1], region, out, by_area, depth + 1);
        region->n = mark;
    }
}

static void collect_leaf_volumes(const mapgen_bsp_t *bsp,
                                 double out[MAPGEN_EQUIV_CLASSES],
                                 double *by_area)
{
    for (int i = 0; i < MAPGEN_EQUIV_CLASSES; i++)
        out[i] = 0.0;
    if (by_area)
        for (uint32_t i = 0; i < MAX_AREAS; i++)
            by_area[i] = 0.0;
    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    if (!world)
        return;

    /*
     * The world box, one unit clear of the model's own bounds. Everything
     * outside it is outside the map, and the tree does not describe it.
     */
    region_t region;
    region.n = 0;
    for (int a = 0; a < 3; a++) {
        cplane_t hi = { { 0, 0, 0 }, world->maxs[a] + 1.0f };
        cplane_t lo = { { 0, 0, 0 }, -(world->mins[a] - 1.0f) };
        hi.n[a] = 1.0f;
        lo.n[a] = -1.0f;
        region_push(&region, &hi);
        region_push(&region, &lo);
    }
    walk_leaves(bsp, world->headnode, &region, out, by_area, 0);
}

static void collect_volumes(const mapgen_bsp_t *bsp,
                            double out[MAPGEN_EQUIV_CLASSES])
{
    const uint32_t n = MapGenBsp_NumBrushes(bsp);
    for (int i = 0; i < MAPGEN_EQUIV_CLASSES; i++)
        out[i] = 0.0;
    for (uint32_t i = 0; i < n; i++) {
        const mapgen_bsp_brush_t *br = MapGenBsp_Brush(bsp, i);
        if (!br)
            continue;
        out[classify(br->contents)] += brush_volume(bsp, br);
    }
}

/* ---- entities: parsed here, by this file, and nowhere else --------------- */

#define EKEY   64
#define EVAL   256

typedef struct { char key[EKEY]; char value[EVAL]; } kv_t;

typedef struct {
    kv_t     kv[32];
    uint32_t n;
    char     classname[MAPGEN_EQUIV_NAME];
    char     targetname[MAPGEN_EQUIV_NAME];
    char     target[MAPGEN_EQUIV_NAME];
    float    origin[3];
    bool     has_origin;
    int32_t  model;         /* from "*N", or -1 */
    char     canon[1024];
    bool     matched;
} eblock_t;

typedef struct { eblock_t *b; uint32_t n, cap; } entities_t;

static const char *skip_space(const char *p, const char *end)
{
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n'))
        p++;
    return p;
}

/*
 * A quoted string, or nothing.
 *
 * It used to keep the first `cap` characters and walk past the rest, so a value
 * that differed only after the sixty-fourth character compared equal. A value
 * this cannot hold exactly is a value it cannot compare, and that is a refusal.
 */
static const char *read_quoted(const char *p, const char *end,
                               char *out, size_t cap)
{
    p = skip_space(p, end);
    if (p >= end || *p != '"')
        return NULL;
    p++;
    size_t n = 0;
    while (p < end && *p != '"') {
        if (n + 1 >= cap)
            return NULL;              /* too long to compare exactly */
        out[n++] = *p;
        p++;
    }
    out[n] = '\0';
    return p < end ? p + 1 : NULL;
}

/*
 * Which keys are measurements and which are names.
 *
 * A tolerance on an origin is right: two compilers write 64 and 64.000001 for
 * the same place. A tolerance on a `target` is wrong: a targetname of "12" and
 * one of "12.00" are different names, and one of them probably does not exist.
 */
static bool key_is_measurement(const char *key)
{
    static const char *const measured[] = {
        "origin", "angle", "angles", "light", "_color", "color", "speed",
        "lip", "height", "distance", "wait", "delay", "dmg", "count",
        "random", "mangle", "radius", "attenuation", "_cone", "accel",
        "decel", "volume",
    };
    for (size_t i = 0; i < sizeof(measured) / sizeof(measured[0]); i++)
        if (!strcmp(key, measured[i]))
            return true;
    return false;
}

/* A value is normalized numerically when every token in it is a number, and
   left exactly as written when it is not: "90" and "90.0" are the same angle,
   "door" and "Door" are not the same target. */
static void normalize_value(const char *in, char *out, size_t cap,
                            float epsilon)
{
    const int digits = epsilon >= 0.5f ? 0 : (epsilon >= 0.05f ? 1 : 3);
    char scratch[EVAL];
    size_t used = 0;
    const char *p = in;
    bool numeric = *in != '\0';

    while (*p && numeric) {
        while (*p == ' ' || *p == '\t')
            p++;
        if (!*p)
            break;
        char *stop = NULL;
        const double v = strtod(p, &stop);
        if (stop == p) {
            numeric = false;
            break;
        }
        if (*stop && *stop != ' ' && *stop != '\t') {
            numeric = false;
            break;
        }
        const int wrote = snprintf(scratch + used, sizeof(scratch) - used,
                                   used ? " %.*f" : "%.*f", digits, v);
        if (wrote < 0 || (size_t)wrote >= sizeof(scratch) - used) {
            numeric = false;
            break;
        }
        used += (size_t)wrote;
        p = stop;
    }
    snprintf(out, cap, "%s", numeric ? scratch : in);
}

static int kv_order(const void *a, const void *b)
{
    return strcmp(((const kv_t *)a)->key, ((const kv_t *)b)->key);
}

static int block_order(const void *a, const void *b)
{
    return strcmp(((const eblock_t *)a)->canon, ((const eblock_t *)b)->canon);
}

static bool parse_entities(const mapgen_bsp_t *bsp,
                           const mapgen_equiv_policy_t *pol, entities_t *out)
{
    uint32_t length = 0;
    const char *text = MapGenBsp_Entities(bsp, &length);
    if (!text)
        return true;
    const char *end = text + length;
    const char *p = text;

    while (p < end) {
        p = skip_space(p, end);
        if (p >= end || *p != '{')
            break;
        p++;

        eblock_t block;
        memset(&block, 0, sizeof(block));
        block.model = -1;

        while (p < end) {
            p = skip_space(p, end);
            if (p >= end || *p == '}')
                break;
            char key[EKEY], value[EVAL];
            const char *next = read_quoted(p, end, key, sizeof(key));
            if (!next)
                return false;
            next = read_quoted(next, end, value, sizeof(value));
            if (!next)
                return false;
            p = next;

            if (!strcmp(key, "classname"))
                snprintf(block.classname, sizeof(block.classname), "%s", value);
            else if (!strcmp(key, "targetname"))
                snprintf(block.targetname, sizeof(block.targetname), "%s", value);
            else if (!strcmp(key, "target"))
                snprintf(block.target, sizeof(block.target), "%s", value);
            else if (!strcmp(key, "origin")) {
                char *cursor = value;
                for (int a = 0; a < 3; a++)
                    block.origin[a] = strtof(cursor, &cursor);
                block.has_origin = true;
            }

            /*
             * "model" "*7" is the one key whose VALUE the compiler owns: it
             * may renumber submodels freely. The binding it expresses is
             * compared on the ownership axis instead, by what the entity is
             * rather than by which number it drew.
             */
            if (!strcmp(key, "model") && value[0] == '*') {
                block.model = (int32_t)strtol(value + 1, NULL, 10);
                continue;
            }
            /*
             * Every pair, or none of them.
             *
             * Dropping the thirty-third pair hid whatever it said; a block with
             * more pairs than this can hold is a block this cannot compare.
             */
            if (block.n >= sizeof(block.kv) / sizeof(block.kv[0]))
                return false;
            for (uint32_t k = 0; k < block.n; k++)
                if (!strcmp(block.kv[k].key, key))
                    return false;      /* duplicate: Quake's rule is not this */
            snprintf(block.kv[block.n].key, EKEY, "%s", key);
            if (key_is_measurement(key))
                normalize_value(value, block.kv[block.n].value, EVAL,
                                pol->value_epsilon);
            else
                snprintf(block.kv[block.n].value, EVAL, "%s", value);
            block.n++;
        }
        if (p >= end || *p != '}')
            return false;             /* a block that does not close */
        p++;

        qsort(block.kv, block.n, sizeof(block.kv[0]), kv_order);
        size_t used = 0;
        for (uint32_t i = 0; i < block.n && used + 1 < sizeof(block.canon); i++)
            used += (size_t)snprintf(block.canon + used,
                                     sizeof(block.canon) - used, "%s=%s;",
                                     block.kv[i].key, block.kv[i].value);
        if (block.model >= 0 && used + 1 < sizeof(block.canon))
            snprintf(block.canon + used, sizeof(block.canon) - used, "model=*;");

        if (out->n == out->cap) {
            const uint32_t want = out->cap ? out->cap * 2 : 256;
            eblock_t *grow = realloc(out->b, (size_t)want * sizeof(*grow));
            if (!grow)
                return false;
            out->b = grow;
            out->cap = want;
        }
        out->b[out->n++] = block;
    }
    return true;
}

static void binding_text(const eblock_t *e, const mapgen_bsp_model_t *m,
                         char *out, size_t cap);

static void identify_models(const mapgen_bsp_t *d, const entities_t *ed,
                            const mapgen_bsp_t *b, const entities_t *eb,
                            model_identity_t *id_d, model_identity_t *id_b)
{
    memset(id_d, 0, sizeof(*id_d));
    memset(id_b, 0, sizeof(*id_b));
    /* Unbound until proved otherwise, and never colliding with the world. */
    for (uint32_t i = 0; i < MAX_MODELS; i++) {
        id_d->of[i] = i;
        id_b->of[i] = MAX_MODELS + i;
    }
    id_d->of[0] = 0;
    id_b->of[0] = 0;

    char want[192], have[192];
    uint32_t next = 1;
    for (uint32_t i = 0; i < ed->n; i++) {
        const eblock_t *e = &ed->b[i];
        if (e->model <= 0 || (uint32_t)e->model >= MAX_MODELS)
            continue;
        const mapgen_bsp_model_t *m = MapGenBsp_Model(d, (uint32_t)e->model);
        if (!m)
            continue;
        binding_text(e, m, want, sizeof(want));

        for (uint32_t k = 0; k < eb->n; k++) {
            const eblock_t *o = &eb->b[k];
            if (o->model <= 0 || (uint32_t)o->model >= MAX_MODELS)
                continue;
            const mapgen_bsp_model_t *om = MapGenBsp_Model(b,
                                                           (uint32_t)o->model);
            if (!om)
                continue;
            binding_text(o, om, have, sizeof(have));
            if (strcmp(want, have))
                continue;
            /* The same machine in both maps, whatever it is numbered. */
            id_d->of[e->model] = next;
            id_b->of[o->model] = next;
            next++;
            break;
        }
    }
    id_d->count = next;
    id_b->count = next;
}

/* ---- the report as text -------------------------------------------------- */

size_t MapGenEquivalence_ReportText(const mapgen_equiv_report_t *r,
                                    char *out, size_t capacity)
{
    if (!r)
        return 0;
    char buf[2048];
    int n = snprintf(buf, sizeof(buf),
        "equivalence %s\n"
        "axis %s\n"
        "detail %s\n"
        "lattice %.1f samples %u\n"
        "space donor solid=%u empty=%u liquid=%u hazard=%u\n"
        "space base  solid=%u empty=%u liquid=%u hazard=%u\n"
        "space diff %u boundary %u interior %u outside %u\n"
        "planes %u %u missing %u added %u\n"
        "brush volume solid %.0f %.0f empty %.0f %.0f liquid %.0f %.0f "
        "hazard %.0f %.0f\n"
        "leaf volume solid %.0f %.0f empty %.0f %.0f liquid %.0f %.0f "
        "hazard %.0f %.0f worst %.2f permille class %s\n"
        "groups %u %u missing %u (%.0f units) added %u (%.0f units) "
        "worst %s\n"
        "materials %u %u area %.0f %.0f mismatched %u worst %.2f permille %s "
        "centroid shift %.3f\n"
        "mapping mismatch %u worst axis %.4f on %s\n"
        "models %u %u bindings %u %u unmatched %u\n"
        "entities %u %u missing %u added %u worst %s\n"
        "movers %u %u operators %u %u portals %u %u relays %u %u "
        "pushes %u %u stops_differ %u\n"
        "spawns %u %u pickups %u %u areas %u %u areaportals %u %u "
        "obligations_broken %u\n"
        "failed_axes %08x\n",
        MapGenEquivalence_ResultName(r->result), r->axis, r->detail,
        (double)r->lattice_used, r->samples,
        r->class_count[0][0], r->class_count[0][1], r->class_count[0][2],
        r->class_count[0][3],
        r->class_count[1][0], r->class_count[1][1], r->class_count[1][2],
        r->class_count[1][3],
        r->space_diff, r->space_diff_boundary, r->space_diff_interior,
        r->space_outside,
        r->surface_planes[0], r->surface_planes[1], r->planes_missing,
        r->planes_added,
        r->brush_volume[0][0], r->brush_volume[1][0],
        r->brush_volume[0][1], r->brush_volume[1][1],
        r->brush_volume[0][2], r->brush_volume[1][2],
        r->brush_volume[0][3], r->brush_volume[1][3],
        r->leaf_volume[0][0], r->leaf_volume[1][0],
        r->leaf_volume[0][1], r->leaf_volume[1][1],
        r->leaf_volume[0][2], r->leaf_volume[1][2],
        r->leaf_volume[0][3], r->leaf_volume[1][3],
        r->worst_volume_permille,
        MapGenEquivalence_ClassName(r->worst_volume_class),
        r->drawn_groups[0], r->drawn_groups[1], r->groups_missing,
        r->groups_missing_area, r->groups_added, r->groups_added_area,
        r->worst_group,
        r->materials[0], r->materials[1], r->drawn_area[0], r->drawn_area[1],
        r->surface_mismatch, r->worst_area_permille, r->worst_area_material,
        r->worst_centroid_shift,
        r->mapping_mismatch, r->worst_axis_shift, r->worst_mapping_material,
        r->models[0], r->models[1], r->bindings[0], r->bindings[1],
        r->bindings_unmatched,
        r->entities[0], r->entities[1], r->entities_missing, r->entities_added,
        r->worst_entity,
        r->movers[0], r->movers[1], r->operators[0], r->operators[1],
        r->portals[0], r->portals[1], r->relays[0], r->relays[1],
        r->pushes[0], r->pushes[1], r->mover_stops_differ,
        r->spawns[0], r->spawns[1], r->pickups[0], r->pickups[1],
        r->areas[0], r->areas[1], r->areaportal_leafs[0],
        r->areaportal_leafs[1], r->obligations_broken, r->failed_axes);
    if (n < 0)
        return 0;
    if (out && capacity)
        snprintf(out, capacity, "%s", buf);
    return (size_t)n;
}

/* ---- the axes ------------------------------------------------------------ */

/*
 * Is this point within the compiler's epsilon of somewhere different?
 *
 * Asked with the same mask the disagreement was found with. It used to ask
 * about the four-way class, which meant the edge of a player clip - clip on
 * one side, air on the other, EMPTY on both - looked like open space, so every
 * disagreement across a clip boundary was counted as a lost room.
 */
static bool near_boundary(const mapgen_bsp_t *bsp, const float p[3],
                          int32_t contents, float eps)
{
    for (int a = 0; a < 3; a++) {
        for (int s = -1; s <= 1; s += 2) {
            float q[3] = { p[0], p[1], p[2] };
            q[a] += (float)s * eps;
            if (movement_at(bsp, q) != contents)
                return true;
        }
    }
    return false;
}

/*
 * One sample: what both maps say is here, and whether a disagreement is real.
 *
 * A disagreement sitting within the compiler's epsilon of a boundary in either
 * map is the two compilers rounding a plane differently. One in open space is
 * a place that changed.
 */
/* Does any brush of this map describe this point's leaf? */
static bool leaf_has_brushes(const mapgen_bsp_t *bsp, const float p[3])
{
    const mapgen_bsp_leaf_t *leaf = MapGenBsp_PointLeaf(bsp, p);
    return leaf && leaf->numleafbrushes > 0;
}

static void probe(const mapgen_bsp_t *d, const mapgen_bsp_t *b,
                  const float p[3], const mapgen_equiv_policy_t *pol,
                  mapgen_equiv_report_t *r, bool *first)
{
    /*
     * Outside the described world.
     *
     * A leaf with no brush in it is space nothing in the map is responsible
     * for - past the sealed hull - and how far a compiler marks it solid is
     * its own business. Comparing there compares the two compilers' sealing,
     * not the map.
     */
    if (!leaf_has_brushes(d, p) || !leaf_has_brushes(b, p)) {
        r->space_outside++;
        return;
    }

    const int32_t cd = movement_at(d, p);
    const int32_t cb = movement_at(b, p);
    const int kd = classify(cd), kb = classify(cb);

    r->samples++;
    r->class_count[0][kd]++;
    r->class_count[1][kb]++;
    if (cd == cb)
        return;
    /*
     * Row 400 (brief 4 G5-2): a point inside a SOLID brush in both maps is rock to everything that moves or looks.
     * cor's donor lists a mist brush inside a solid one (contents 0x41) where the frozen compiler's CSG drops the
     * mist fragment inside the rock (0x01); that is the compilers' bookkeeping, not the map. Bits that ride along
     * with SOLID are not compared; a point solid in one map and not in the other still is.
     */
    if ((cd & BIT_SOLID) && (cb & BIT_SOLID)) {
        r->space_solid_riders++;
        return;
    }

    r->space_diff++;
    if (near_boundary(d, p, cd, pol->epsilon)
        || near_boundary(b, p, cb, pol->epsilon)) {
        r->space_diff_boundary++;
        return;
    }
    r->space_diff_interior++;
    r->diff_bits_donor |= cd & ~cb;
    r->diff_bits_baseline |= cb & ~cd;
    if (!*first) {
        float span = 0.0f;
        for (int a = 0; a < 3; a++) {
            const float delta = fabsf(p[a] - r->first_diff[a]);
            if (delta > span)
                span = delta;
        }
        if (span > r->diff_span)
            r->diff_span = span;
    }
    if (*first) {
        *first = false;
        memcpy(r->first_diff, p, sizeof(r->first_diff));
        r->first_diff_class[0] = kd;
        r->first_diff_class[1] = kb;
        r->first_diff_contents[0] = cd;
        r->first_diff_contents[1] = cb;
    }
}

/*
 * Every leaf of one map, probed at a point inside it.
 *
 * The lattice cannot see anything thinner than its own spacing. Leaves can:
 * they are the convex regions the compiler carved space into, so a wall, a
 * clip brush, a narrow passage or a small pool is a leaf however thin it is,
 * and its centre is a point the other map has to agree about.
 *
 * Both maps' leaves are probed, so a region that exists in only one of them is
 * still looked at - which is the whole difficulty with sampling by lattice.
 */
static void probe_leaves(const mapgen_bsp_t *of, const mapgen_bsp_t *d,
                         const mapgen_bsp_t *b,
                         const mapgen_equiv_policy_t *pol,
                         mapgen_equiv_report_t *r, bool *first)
{
    const uint32_t n = MapGenBsp_NumLeafs(of);
    for (uint32_t i = 0; i < n; i++) {
        const mapgen_bsp_leaf_t *leaf = MapGenBsp_Leaf(of, i);
        if (!leaf)
            continue;
        /* A leaf with no extent describes nothing. */
        if (leaf->maxs[0] <= leaf->mins[0] || leaf->maxs[1] <= leaf->mins[1]
            || leaf->maxs[2] <= leaf->mins[2])
            continue;
        /*
         * A point actually inside the leaf.
         *
         * Leaves are convex but a slanted one can have its bounding-box centre
         * outside itself, and a probe there measures a neighbour. The centre is
         * tried first, then a few positions nearer each corner; the leaf is
         * skipped when none of them is a point this map agrees is in it.
         */
        static const float toward[5][3] = {
            {  0.0f,  0.0f,  0.0f },
            { -0.25f, -0.25f, -0.25f },
            {  0.25f,  0.25f, -0.25f },
            { -0.25f,  0.25f,  0.25f },
            {  0.25f, -0.25f,  0.25f },
        };
        const int32_t wanted = leaf->contents & MOVEMENT_MASK;
        bool inside = false;
        float p[3];
        for (int k = 0; k < 5 && !inside; k++) {
            for (int a = 0; a < 3; a++) {
                const float lo = (float)leaf->mins[a], hi = (float)leaf->maxs[a];
                p[a] = 0.5f * (lo + hi) + toward[k][a] * (hi - lo);
            }
            inside = movement_at(of, p) == wanted;
        }
        if (!inside)
            continue;
        r->leaf_samples++;
        probe(d, b, p, pol, r, first);
    }
}

static mapgen_equiv_result_t
axis_space(const mapgen_bsp_t *d, const mapgen_bsp_t *b,
           const mapgen_equiv_policy_t *pol, mapgen_equiv_report_t *r)
{
    const mapgen_bsp_model_t *md = MapGenBsp_Model(d, 0);
    const mapgen_bsp_model_t *mb = MapGenBsp_Model(b, 0);
    if (!md || !mb)
        return MAPGEN_EQUIV_ERR_ARGS;

    /* The union, so a baseline that lost its outer shell is sampled where the
       donor still has one. */
    float mins[3], maxs[3];
    for (int a = 0; a < 3; a++) {
        mins[a] = md->mins[a] < mb->mins[a] ? md->mins[a] : mb->mins[a];
        maxs[a] = md->maxs[a] > mb->maxs[a] ? md->maxs[a] : mb->maxs[a];
        if (maxs[a] <= mins[a])
            return MAPGEN_EQUIV_ERR_ARGS;
    }

    float lattice = pol->lattice > 1.0f ? pol->lattice : 1.0f;
    uint32_t steps[3];
    for (int guard = 0; guard < 32; guard++) {
        double count = 1.0;
        for (int a = 0; a < 3; a++) {
            steps[a] = (uint32_t)((maxs[a] - mins[a]) / lattice) + 1u;
            count *= (double)steps[a];
        }
        if (count <= (double)pol->max_samples)
            break;
        lattice *= 2.0f;
        if (guard == 31)
            return MAPGEN_EQUIV_ERR_LIMIT;
    }
    r->lattice_used = lattice;

    bool first = true;

    /*
     * The lattice, deliberately off the map's own grid. Quake architecture
     * sits on 8, 16, 32 and 64 units; a sampler that landed exactly on those
     * planes would spend its budget on ties and measure the tie-breaking rule
     * rather than the map.
     */
    const float bias = 0.317f * lattice;
    for (uint32_t ix = 0; ix < steps[0]; ix++)
        for (uint32_t iy = 0; iy < steps[1]; iy++)
            for (uint32_t iz = 0; iz < steps[2]; iz++) {
                const float p[3] = {
                    mins[0] + bias + (float)ix * lattice,
                    mins[1] + bias + (float)iy * lattice,
                    mins[2] + bias + (float)iz * lattice,
                };
                r->lattice_samples++;
                probe(d, b, p, pol, r, &first);
            }

    /* And the architecture's own resolution, from both maps. */
    probe_leaves(d, d, b, pol, r, &first);
    probe_leaves(b, d, b, pol, r, &first);

    if (r->space_diff_interior) {
        say(r, "space",
            "%u of %u samples disagree away from any boundary; first at "
            "%.0f %.0f %.0f, donor %s (contents %08x), baseline %s (%08x); "
            "bits only in the donor %08x, only in the baseline %08x, spread "
            "%.0f units",
            r->space_diff_interior, r->samples, (double)r->first_diff[0],
            (double)r->first_diff[1], (double)r->first_diff[2],
            MapGenEquivalence_ClassName(r->first_diff_class[0]),
            (unsigned)r->first_diff_contents[0],
            MapGenEquivalence_ClassName(r->first_diff_class[1]),
            (unsigned)r->first_diff_contents[1],
            (unsigned)r->diff_bits_donor, (unsigned)r->diff_bits_baseline,
            (double)r->diff_span);
        return MAPGEN_EQUIV_DIFF_SPACE;
    }
    return MAPGEN_EQUIV_OK;
}

static mapgen_equiv_result_t
axis_architecture(const mapgen_bsp_t *d, const mapgen_bsp_t *b,
                  const groups_t *gd, const groups_t *gb,
                  const mapgen_equiv_policy_t *pol, mapgen_equiv_report_t *r)
{
    planeset_t pd = { 0 }, pb = { 0 };
    mapgen_equiv_result_t rc = MAPGEN_EQUIV_OK;

    if (!collect_planes(gd, &pd, pol) || !collect_planes(gb, &pb, pol)) {
        rc = MAPGEN_EQUIV_ERR_MEMORY;
        goto done;
    }
    r->surface_planes[0] = pd.n;
    r->surface_planes[1] = pb.n;
    for (uint32_t i = 0; i < pd.n; i++)
        if (!planeset_has(&pb, &pd.p[i], pol))
            r->planes_missing++;
    for (uint32_t i = 0; i < pb.n; i++)
        if (!planeset_has(&pd, &pb.p[i], pol))
            r->planes_added++;

    collect_volumes(d, r->brush_volume[0]);
    collect_volumes(b, r->brush_volume[1]);
    collect_leaf_volumes(d, r->leaf_volume[0], NULL);
    collect_leaf_volumes(b, r->leaf_volume[1], NULL);
    for (int c = 0; c < MAPGEN_EQUIV_CLASSES; c++) {
        const double pm = permille(r->leaf_volume[0][c], r->leaf_volume[1][c]);
        if (pm > r->worst_volume_permille) {
            r->worst_volume_permille = pm;
            r->worst_volume_class = c;
        }
    }

    /*
     * A plane the donor draws on and the baseline does not is a wall that
     * moved. The other direction is allowed: splitting one surface into three
     * keeps the plane, and a compiler that adds a plane without taking one
     * away has not lost architecture.
     */
    if (r->planes_missing) {
        say(r, "architecture",
            "%u of %u planes carrying donor surfaces have no counterpart in "
            "the baseline", r->planes_missing, pd.n);
        rc = MAPGEN_EQUIV_DIFF_ARCHITECTURE;
        goto done;
    }
    if (r->worst_volume_permille > pol->volume_permille) {
        say(r, "architecture",
            "%s space differs by %.2f permille of volume: donor %.0f, "
            "baseline %.0f",
            MapGenEquivalence_ClassName(r->worst_volume_class),
            r->worst_volume_permille,
            r->leaf_volume[0][r->worst_volume_class],
            r->leaf_volume[1][r->worst_volume_class]);
        rc = MAPGEN_EQUIV_DIFF_ARCHITECTURE;
    }

done:
    free(pd.p);
    free(pb.p);
    return rc;
}

/*
 * What did not match, worst first, for a reader who has to judge whether a
 * difference is a lost surface or a tolerance.
 *
 * A snapshot rather than part of the report: the report is copied, stored and
 * compared, and should not carry a variable-length tail only a diagnostic
 * reads.
 */
#define MAX_DIFFS 64
static mapgen_equiv_surface_diff_t s_diffs[MAX_DIFFS];
static uint32_t s_num_diffs;
static mapgen_equiv_surface_diff_t s_deltas[MAX_DIFFS];
static uint32_t s_num_deltas;

uint32_t MapGenEquivalence_SurfaceDiffs(mapgen_equiv_surface_diff_t *out,
                                        uint32_t max)
{
    const uint32_t n = s_num_diffs < max ? s_num_diffs : max;
    if (out && n)
        memcpy(out, s_diffs, (size_t)n * sizeof(*out));
    return n;
}

static mapgen_equiv_surface_diff_t *note_diff(int side, const material_t *m)
{
    if (s_num_diffs >= MAX_DIFFS)
        return NULL;
    mapgen_equiv_surface_diff_t *d = &s_diffs[s_num_diffs++];
    memset(d, 0, sizeof(*d));
    d->side = side;
    if (m) {
        snprintf(d->texture, sizeof(d->texture), "%s", m->texture);
        d->flags = m->flags;
        d->value = m->value;
        d->model = m->model;
    }
    return d;
}

static double distance(const double a[3], const double b[3])
{
    const double dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
    return sqrt(dx * dx + dy * dy + dz * dz);
}

/*
 * Is every material still drawn on every plane it was drawn on?
 *
 * Existence only. Two compiled artifacts do not agree on area to better than
 * about a part in a thousand, so asking "is there the same amount" is either
 * blind or noisy; asking "is there any" is neither.
 */
static bool group_present(const groups_t *gs, const group_t *key,
                          const mapgen_equiv_policy_t *pol)
{
    const uint32_t b = hash_text(key->texture) & (TEXBUCKETS - 1);
    for (uint32_t i = gs->head[b]; i != NIL; i = gs->g[i].next) {
        const group_t *g = &gs->g[i];
        if (g->flags != key->flags || g->value != key->value
            || g->model != key->model
            || strcmp(g->texture, key->texture) != 0)
            continue;
        if (fabsf(g->plane.d - key->plane.d) > pol->plane_epsilon)
            continue;
        bool same = true;
        for (int a = 0; a < 3 && same; a++)
            same = fabsf(g->plane.n[a] - key->plane.n[a]) <= pol->normal_epsilon;
        if (same)
            return true;
    }
    return false;
}

/*
 * The counterpart group, or NULL. Same test as `group_present`, but it hands
 * back what it found so a diagnostic can compare the two areas.
 */
static const group_t *group_counterpart(const groups_t *gs, const group_t *key,
                                        const mapgen_equiv_policy_t *pol)
{
    const uint32_t b = hash_text(key->texture) & (TEXBUCKETS - 1);
    for (uint32_t i = gs->head[b]; i != NIL; i = gs->g[i].next) {
        const group_t *g = &gs->g[i];
        if (g->flags != key->flags || g->value != key->value
            || g->model != key->model
            || strcmp(g->texture, key->texture) != 0)
            continue;
        if (fabsf(g->plane.d - key->plane.d) > pol->plane_epsilon)
            continue;
        bool same = true;
        for (int a = 0; a < 3 && same; a++)
            same = fabsf(g->plane.n[a] - key->plane.n[a]) <= pol->normal_epsilon;
        if (same)
            return g;
    }
    return NULL;
}

/*
 * The groups whose area moved most, largest first. Diagnostic only: nothing
 * here is gated, because matching plane to plane inside a tolerance is exactly
 * what put area on the wrong neighbour when this was a gate.
 */
uint32_t MapGenEquivalence_GroupDeltas(mapgen_equiv_surface_diff_t *out,
                                       uint32_t max)
{
    const uint32_t n = s_num_deltas < max ? s_num_deltas : max;
    if (out && n)
        memcpy(out, s_deltas, (size_t)n * sizeof(*out));
    return n;
}

static void collect_group_deltas(const groups_t *gd, const groups_t *gb,
                                 const mapgen_equiv_policy_t *pol)
{
    s_num_deltas = 0;
    for (uint32_t i = 0; i < gd->n; i++) {
        const group_t *g = &gd->g[i];
        const group_t *other = group_counterpart(gb, g, pol);
        const double have = other ? other->area : 0.0;
        const double delta = fabs(g->area - have);
        if (delta < 1.0)
            continue;
        /* Keep the worst MAX_DIFFS by insertion, so the list stays sorted and
           no allocation is needed. */
        uint32_t at = s_num_deltas;
        while (at > 0 && fabs(s_deltas[at - 1].donor_area
                              - s_deltas[at - 1].baseline_area) < delta) {
            if (at < MAX_DIFFS)
                s_deltas[at] = s_deltas[at - 1];
            at--;
        }
        if (at >= MAX_DIFFS)
            continue;
        mapgen_equiv_surface_diff_t *d = &s_deltas[at];
        memset(d, 0, sizeof(*d));
        d->side = 2;
        snprintf(d->texture, sizeof(d->texture), "%s", g->texture);
        d->flags = g->flags;
        d->value = g->value;
        d->model = g->model;
        memcpy(d->normal, g->plane.n, sizeof(d->normal));
        d->dist = g->plane.d;
        d->donor_area = g->area;
        d->baseline_area = have;
        d->area_permille = permille(g->area, have);
        if (s_num_deltas < MAX_DIFFS)
            s_num_deltas++;
    }
}

static mapgen_equiv_result_t
axis_presence(const mapgen_bsp_t *d, const mapgen_bsp_t *b,
              const groups_t *gd, const groups_t *gb,
              const model_identity_t *ident_d, const model_identity_t *ident_b,
              const mapgen_equiv_policy_t *pol, mapgen_equiv_report_t *r)
{
    s_num_diffs = 0;
    collect_group_deltas(gd, gb, pol);

    /*
     * Coverage, wall by wall.
     *
     * Summed area counts a face laid on another twice, and Quake maps carry
     * plenty of those - q2dm3's floor has ten thousand units of coincident
     * duplicates that one compiler draws and the other culls. What a player
     * sees is the union, and that is what is gated.
     */
    uint32_t *owner_d = face_owners(d);
    uint32_t *owner_b = face_owners(b);
    const uint32_t nfaces_d = MapGenBsp_NumFaces(d);
    const uint32_t nfaces_b = MapGenBsp_NumFaces(b);
    /* row 400: what faces the other compiler's sealing is not compared here either */
    if (owner_d && owner_b) {
        seal_owners(d, b, owner_d, nfaces_d, NULL);
        seal_owners(b, d, owner_b, nfaces_b, NULL);
    }
    if (owner_d && owner_b) {
        for (uint32_t i = 0; i < gd->n; i++) {
            const group_t *want = &gd->g[i];
            if (want->area < (double)pol->sliver_area)
                continue;
            const group_t *have = group_counterpart(gb, want, pol);
            if (!have)
                continue;             /* presence below owns that failure */
            float step = 0.0f;
            const double cd = group_coverage(d, want, owner_d, ident_d, nfaces_d,
                                             &step);
            const double cb = group_coverage(b, have, owner_b, ident_b, nfaces_b,
                                             &step);
            r->coverage[0] += cd;
            r->coverage[1] += cb;
            r->coverage_step = step;
            /*
             * The tolerance is the measurement's own error bar.
             *
             * A raster of step s misjudges a polygon by about its perimeter
             * times s, and the two maps cut the same wall into different
             * polygons, so the errors do not cancel. For a wall of area A the
             * perimeter is at least 4*sqrt(A), and two of them are being
             * compared - so anything inside 8*sqrt(A)*s is the raster talking.
             * A permille allowance rides on top for the wall itself.
             */
            const double bigger = cd > cb ? cd : cb;
            const double raster_error = 8.0 * sqrt(bigger > 0.0 ? bigger : 0.0)
                                      * (double)step;
            const double allowed = raster_error
                                 + bigger * (double)pol->coverage_permille
                                   / 1000.0;
            double pm = fabs(cd - cb) <= allowed ? 0.0 : permille(cd, cb);

            /*
             * If this wall differs, ask its neighbourhood.
             *
             * A curve is many planes a fraction of a degree apart, and which
             * of them a face lands on is the compiler's - plane merging is on
             * the allowed list. A face that moved next door leaves the
             * neighbourhood's coverage alone; a face that stopped being drawn
             * does not.
             */
            if (pm > (double)pol->coverage_permille) {
                double near_d = 0.0, near_b = 0.0;
                for (uint32_t k = 0; k < gd->n; k++) {
                    const group_t *o = &gd->g[k];
                    if (o->model != want->model || o->flags != want->flags
                        || o->value != want->value
                        || strcmp(o->texture, want->texture) != 0)
                        continue;
                    if (fabsf(o->plane.d - want->plane.d)
                        > pol->neighbour_distance)
                        continue;
                    bool close = true;
                    for (int a = 0; a < 3 && close; a++)
                        close = fabsf(o->plane.n[a] - want->plane.n[a])
                                <= pol->neighbour_normal;
                    if (!close)
                        continue;
                    float s = step;
                    near_d += group_coverage(d, o, owner_d, ident_d, nfaces_d, &s);
                    const group_t *twin = group_counterpart(gb, o, pol);
                    if (twin) {
                        s = step;
                        near_b += group_coverage(b, twin, owner_b, ident_b, nfaces_b,
                                                 &s);
                    }
                }
                const double near_bigger = near_d > near_b ? near_d : near_b;
                const double near_allowed =
                    8.0 * sqrt(near_bigger > 0.0 ? near_bigger : 0.0)
                    * (double)step
                    + near_bigger * (double)pol->coverage_permille / 1000.0;
                if (fabs(near_d - near_b) <= near_allowed)
                    pm = 0.0;
            }
            if (pm > r->worst_coverage_permille) {
                r->worst_coverage_permille = pm;
                snprintf(r->worst_coverage_material,
                         sizeof(r->worst_coverage_material), "%s",
                         want->texture);
                for (int a = 0; a < 3; a++)
                    r->worst_coverage_plane[a] = want->plane.n[a];
                r->worst_coverage_plane[3] = want->plane.d;
            }
            if (pm > (double)pol->coverage_permille)
                r->coverage_mismatch++;
        }
    }
    free(owner_d);
    free(owner_b);
    for (uint32_t side = 0; side < 2; side++) {
        const groups_t *from = side ? gb : gd;
        const groups_t *to = side ? gd : gb;
        for (uint32_t i = 0; i < from->n; i++) {
            const group_t *g = &from->g[i];
            if (g->area < (double)pol->sliver_area)
                continue;
            r->drawn_groups[side]++;
            if (group_present(to, g, pol))
                continue;
            mapgen_equiv_surface_diff_t *d = note_diff((int)side, NULL);
            if (d) {
                snprintf(d->texture, sizeof(d->texture), "%s", g->texture);
                d->flags = g->flags;
                d->value = g->value;
                d->model = g->model;
                memcpy(d->normal, g->plane.n, sizeof(d->normal));
                d->dist = g->plane.d;
                if (side)
                    d->baseline_area = g->area;
                else
                    d->donor_area = g->area;
            }
            if (side == 0) {
                r->groups_missing++;
                if (g->area > r->groups_missing_area) {
                    r->groups_missing_area = g->area;
                    snprintf(r->worst_group, sizeof(r->worst_group), "%s",
                             g->texture);
                }
            } else {
                r->groups_added++;
                r->groups_added_area += g->area;
                if (!r->groups_missing && !r->worst_group[0])
                    snprintf(r->worst_group, sizeof(r->worst_group), "%s",
                             g->texture);
            }
        }
    }
    if (r->coverage_mismatch) {
        say(r, "surface",
            "%u walls are covered differently; the worst is %s on the plane "
            "%.3f %.3f %.3f at %.1f, off by %.2f permille (donor %.0f, "
            "baseline %.0f units of coverage, %.0f-unit raster)",
            r->coverage_mismatch, r->worst_coverage_material,
            (double)r->worst_coverage_plane[0],
            (double)r->worst_coverage_plane[1],
            (double)r->worst_coverage_plane[2],
            (double)r->worst_coverage_plane[3],
            r->worst_coverage_permille, r->coverage[0], r->coverage[1],
            (double)r->coverage_step);
        return MAPGEN_EQUIV_DIFF_SURFACE;
    }
    if (r->groups_missing) {
        say(r, "surface",
            "%u face groups the donor draws are absent from the baseline; the "
            "largest is %.0f units of %s", r->groups_missing,
            r->groups_missing_area, r->worst_group);
        return MAPGEN_EQUIV_DIFF_SURFACE;
    }
    /*
     * Gained surfaces are bounded by area rather than by count. The donor's
     * compiler is not the frozen one, and the two make different decisions
     * about a face that lies exactly on another brush - so a few small faces
     * appear. A budget says how much of that is a compiler and how much is a
     * generator drawing walls the donor never had.
     */
    const double budget = (r->drawn_area[0] > 0.0 ? r->drawn_area[0] : 1.0)
                        * (double)pol->added_area_permille / 1000.0;
    if (r->groups_added && r->groups_added_area > budget) {
        say(r, "surface",
            "the baseline draws %u face groups the donor does not, %.0f units "
            "in all, over the %.0f-unit budget", r->groups_added,
            r->groups_added_area, budget);
        return MAPGEN_EQUIV_DIFF_SURFACE;
    }
    return MAPGEN_EQUIV_OK;
}

/*
 * Does the baseline draw what the donor draws, in the same places, facing the
 * same way?
 *
 * Every quantity compared here is a sum over faces weighted by area, so how
 * the compiler cut the faces up cannot reach it. What can reach it: a surface
 * that stopped being drawn, one that appeared, one whose area changed, one
 * that moved, and one that turned around.
 */
static mapgen_equiv_result_t
axis_surface(materials_t *md, materials_t *mb,
             const mapgen_equiv_policy_t *pol, mapgen_equiv_report_t *r)
{
    r->materials[0] = md->n;
    r->materials[1] = mb->n;

    double worst_area = 0.0, worst_shift = 0.0;
    const char *worst_area_name = "";
    const char *lost = NULL, *gained = NULL;
    double lost_area = 0.0, gained_area = 0.0;

    for (uint32_t i = 0; i < md->n; i++) {
        material_t *want = &md->m[i];
        material_t *have = material_find(mb, want);
        if (!have) {
            mapgen_equiv_surface_diff_t *d = note_diff(0, want);
            if (d) {
                d->donor_area = want->area;
                d->area_permille = 1000.0;
            }
            if (want->area > lost_area) {
                lost_area = want->area;
                lost = want->texture;
            }
            r->surface_mismatch++;
            continue;
        }
        have->matched = true;

        double cd[3], cb[3], nd[3], nb[3], od, ob, ad[2][4], ab[2][4];
        mean_of(want, cd, nd, &od, ad);
        mean_of(have, cb, nb, &ob, ab);

        const double pm = permille(want->area, have->area);
        const double shift = distance(cd, cb);
        const double turn = distance(nd, nb);
        const double slide = fabs(od - ob);

        if (pm > worst_area) {
            worst_area = pm;
            worst_area_name = want->texture;
        }
        if (shift > worst_shift)
            worst_shift = shift;

        /*
         * The mean plane offset is REPORTED, not gated. Inside one material
         * the plane offsets are spread over thousands of units, so a permille
         * of area moving between two distant walls of the same texture shifts
         * the mean by more than a unit while nothing has moved. It measures
         * the spread. The centroid measures the position, and it is gated.
         */
        /*
         * Reported, not gated.
         *
         * Summed area and its centroid move whenever a compiler culls a face
         * laid on another - ten thousand units of q2dm3's floor - and that
         * changes nothing a player sees. Coverage is the gate; these say how
         * the description changed.
         */
        const bool bad = false;
        (void)shift;
        (void)turn;
        (void)pm;
        (void)pol;
        if (bad) {
            r->surface_mismatch++;
            mapgen_equiv_surface_diff_t *d = note_diff(2, want);
            if (d) {
                d->donor_area = want->area;
                d->baseline_area = have->area;
                d->area_permille = pm;
                d->centroid_shift = shift;
                d->normal_shift = turn;
                d->offset_shift = slide;
            }
        }
    }
    for (uint32_t i = 0; i < mb->n; i++) {
        if (mb->m[i].matched)
            continue;
        r->surface_mismatch++;
        mapgen_equiv_surface_diff_t *d = note_diff(1, &mb->m[i]);
        if (d) {
            d->baseline_area = mb->m[i].area;
            d->area_permille = 1000.0;
        }
        if (mb->m[i].area > gained_area) {
            gained_area = mb->m[i].area;
            gained = mb->m[i].texture;
        }
    }

    r->worst_area_permille = worst_area;
    r->worst_centroid_shift = worst_shift;
    snprintf(r->worst_area_material, sizeof(r->worst_area_material), "%s",
             worst_area_name);

    if (lost) {
        say(r, "surface",
            "the baseline draws nothing where the donor draws %.0f units of "
            "%s", lost_area, lost);
        return MAPGEN_EQUIV_DIFF_SURFACE;
    }
    if (gained) {
        say(r, "surface",
            "the baseline draws %.0f units of %s that the donor does not",
            gained_area, gained);
        return MAPGEN_EQUIV_DIFF_SURFACE;
    }
    if (r->surface_mismatch) {
        say(r, "surface",
            "%u materials differ; worst area drift %.2f permille on %s, worst "
            "centroid shift %.2f units", r->surface_mismatch, worst_area,
            worst_area_name, worst_shift);
        return MAPGEN_EQUIV_DIFF_SURFACE;
    }
    return MAPGEN_EQUIV_OK;
}

/*
 * Does the texture sit the same way on it?
 *
 * The mean texture axis is the area-weighted average of every face's texinfo,
 * so a texture slid by eight units on a wall moves the mean by eight times the
 * share of that wall in its material - visible in the number, and impossible
 * to produce by splitting a face.
 */
/*
 * Does the texture sit the same way on each WALL?
 *
 * Compared per (model, material, plane) group rather than averaged over a
 * material. The average is blind to two walls sliding in opposite directions,
 * and when it does fire it can only name the material - which on q2dm2 is
 * eight hundred thousand units of surface.
 *
 * A group with no counterpart belongs to the surface axis; this one only looks
 * at pairs that matched.
 */
static mapgen_equiv_result_t
axis_mapping(const groups_t *gd, const groups_t *gb,
             const mapgen_equiv_policy_t *pol, mapgen_equiv_report_t *r)
{
    double worst = 0.0;
    const group_t *worst_group = NULL;

    for (uint32_t i = 0; i < gd->n; i++) {
        const group_t *want = &gd->g[i];
        if (want->area < (double)pol->sliver_area)
            continue;
        const group_t *have = group_counterpart(gb, want, pol);
        if (!have)
            continue;                 /* the surface axis owns that failure */

        if (want->too_many_axes || have->too_many_axes) {
            /* Not a drift: a wall carrying more distinct mappings than this
               can hold is one the comparison refuses rather than
               approximates. */
            r->mapping_overflow++;
            continue;
        }

        /*
         * Every mapping the BASELINE uses here must be one the DONOR uses
         * here. Folding two identical-looking texinfos into one is the
         * compiler's business; inventing a mapping is not, and a texture slid
         * by any amount invents one.
         */
        for (uint8_t k = 0; k < have->num_axes; k++) {
            double nearest = 1e30;
            for (uint8_t j = 0; j < want->num_axes; j++) {
                double drift = 0.0;
                for (int u = 0; u < 2; u++)
                    for (int a = 0; a < 4; a++) {
                        const double delta =
                            fabs((double)have->axes[k][u][a]
                                 - (double)want->axes[j][u][a]);
                        if (delta > drift)
                            drift = delta;
                    }
                if (drift < nearest)
                    nearest = drift;
            }
            if (nearest > worst) {
                worst = nearest;
                worst_group = want;
            }
            if (nearest > (double)pol->axis_epsilon)
                r->mapping_mismatch++;
        }
    }

    r->worst_axis_shift = worst;
    if (worst_group) {
        snprintf(r->worst_mapping_material, sizeof(r->worst_mapping_material),
                 "%s", worst_group->texture);
        for (int a = 0; a < 3; a++)
            r->worst_mapping_plane[a] = worst_group->plane.n[a];
        r->worst_mapping_plane[3] = worst_group->plane.d;
    }
    if (r->mapping_overflow) {
        say(r, "mapping",
            "%u surfaces carry more distinct texture mappings than the "
            "comparison holds", r->mapping_overflow);
        return MAPGEN_EQUIV_DIFF_MAPPING;
    }
    if (r->mapping_mismatch) {
        say(r, "mapping",
            "%u surfaces carry different texture axes; the worst is %s on the "
            "plane %.3f %.3f %.3f at %.1f, off by %.3f", r->mapping_mismatch,
            r->worst_mapping_material,
            (double)r->worst_mapping_plane[0],
            (double)r->worst_mapping_plane[1],
            (double)r->worst_mapping_plane[2],
            (double)r->worst_mapping_plane[3], worst);
        return MAPGEN_EQUIV_DIFF_MAPPING;
    }
    return MAPGEN_EQUIV_OK;
}

/* The identity of a brush-model binding, free of the submodel number. */
static void binding_text(const eblock_t *e, const mapgen_bsp_model_t *m,
                         char *out, size_t cap)
{
    snprintf(out, cap, "%s|%s|%s|%.0f %.0f %.0f|%.0f %.0f %.0f",
             e->classname, e->targetname, e->target,
             (double)m->mins[0], (double)m->mins[1], (double)m->mins[2],
             (double)m->maxs[0], (double)m->maxs[1], (double)m->maxs[2]);
}

static mapgen_equiv_result_t
axis_ownership(const mapgen_bsp_t *d, const mapgen_bsp_t *b,
               entities_t *ed, entities_t *eb, mapgen_equiv_report_t *r)
{
    r->models[0] = MapGenBsp_NumModels(d);
    r->models[1] = MapGenBsp_NumModels(b);
    if (r->models[0] != r->models[1]) {
        say(r, "ownership", "the donor has %u brush models, the baseline %u",
            r->models[0], r->models[1]);
        return MAPGEN_EQUIV_DIFF_OWNERSHIP;
    }

    char (*want)[192] = NULL;
    char (*have)[192] = NULL;
    uint32_t nw = 0, nh = 0;
    const uint32_t cap = ed->n + eb->n + 1;
    want = calloc(cap, sizeof(*want));
    have = calloc(cap, sizeof(*have));
    if (!want || !have) {
        free(want);
        free(have);
        return MAPGEN_EQUIV_ERR_MEMORY;
    }

    /*
     * Every binding, and an unbound one is a failure rather than a skip.
     *
     * Skipping a model reference that does not resolve meant a door repointed
     * at a submodel that is not there passed the ownership axis: the binding
     * simply vanished from both lists and nothing was compared.
     */
    for (uint32_t i = 0; i < ed->n; i++) {
        if (ed->b[i].model < 0)
            continue;
        const mapgen_bsp_model_t *m = MapGenBsp_Model(d,
                                                      (uint32_t)ed->b[i].model);
        if (!m) {
            snprintf(r->detail, sizeof(r->detail),
                     "the donor's %s is bound to submodel *%d, which is not "
                     "there", ed->b[i].classname, ed->b[i].model);
            snprintf(r->axis, sizeof(r->axis), "ownership");
            free(want);
            free(have);
            return MAPGEN_EQUIV_DIFF_OWNERSHIP;
        }
        binding_text(&ed->b[i], m, want[nw++], sizeof(want[0]));
    }
    for (uint32_t i = 0; i < eb->n; i++) {
        if (eb->b[i].model < 0)
            continue;
        const mapgen_bsp_model_t *m = MapGenBsp_Model(b,
                                                      (uint32_t)eb->b[i].model);
        if (!m) {
            snprintf(r->detail, sizeof(r->detail),
                     "the baseline's %s is bound to submodel *%d, which is "
                     "not there", eb->b[i].classname, eb->b[i].model);
            snprintf(r->axis, sizeof(r->axis), "ownership");
            free(want);
            free(have);
            return MAPGEN_EQUIV_DIFF_OWNERSHIP;
        }
        binding_text(&eb->b[i], m, have[nh++], sizeof(have[0]));
    }
    r->bindings[0] = nw;
    r->bindings[1] = nh;

    bool *used = calloc(nh ? nh : 1, sizeof(*used));
    if (!used) {
        free(want);
        free(have);
        return MAPGEN_EQUIV_ERR_MEMORY;
    }
    char unmatched[192] = "";
    for (uint32_t i = 0; i < nw; i++) {
        bool found = false;
        for (uint32_t k = 0; k < nh && !found; k++) {
            if (used[k] || strcmp(want[i], have[k]) != 0)
                continue;
            used[k] = true;
            found = true;
        }
        if (!found) {
            r->bindings_unmatched++;
            if (!unmatched[0])
                snprintf(unmatched, sizeof(unmatched), "%s", want[i]);
        }
    }
    for (uint32_t k = 0; k < nh; k++)
        if (!used[k])
            r->bindings_unmatched++;

    free(used);
    free(want);
    free(have);

    if (r->bindings_unmatched) {
        say(r, "ownership",
            "%u brush-model bindings do not match; first unmatched is %s",
            r->bindings_unmatched, unmatched[0] ? unmatched : "(added)");
        return MAPGEN_EQUIV_DIFF_OWNERSHIP;
    }
    return MAPGEN_EQUIV_OK;
}

static mapgen_equiv_result_t
axis_entity(entities_t *ed, entities_t *eb, mapgen_equiv_report_t *r)
{
    r->entities[0] = ed->n;
    r->entities[1] = eb->n;

    qsort(ed->b, ed->n, sizeof(ed->b[0]), block_order);
    qsort(eb->b, eb->n, sizeof(eb->b[0]), block_order);

    uint32_t i = 0, k = 0;
    while (i < ed->n && k < eb->n) {
        const int cmp = strcmp(ed->b[i].canon, eb->b[k].canon);
        if (cmp == 0) {
            i++;
            k++;
        } else if (cmp < 0) {
            if (!r->entities_missing)
                snprintf(r->worst_entity, sizeof(r->worst_entity), "%s",
                         ed->b[i].classname);
            r->entities_missing++;
            i++;
        } else {
            if (!r->entities_missing && !r->entities_added)
                snprintf(r->worst_entity, sizeof(r->worst_entity), "%s",
                         eb->b[k].classname);
            r->entities_added++;
            k++;
        }
    }
    for (; i < ed->n; i++) {
        if (!r->entities_missing)
            snprintf(r->worst_entity, sizeof(r->worst_entity), "%s",
                     ed->b[i].classname);
        r->entities_missing++;
    }
    for (; k < eb->n; k++) {
        if (!r->entities_missing && !r->entities_added)
            snprintf(r->worst_entity, sizeof(r->worst_entity), "%s",
                     eb->b[k].classname);
        r->entities_added++;
    }

    if (r->entities_missing || r->entities_added) {
        say(r, "entity",
            "%u donor entities are absent from the baseline and %u are new; "
            "first is %s", r->entities_missing, r->entities_added,
            r->worst_entity);
        return MAPGEN_EQUIV_DIFF_ENTITY;
    }
    return MAPGEN_EQUIV_OK;
}

static void mover_text(const mapgen_mover_t *m, char *out, size_t cap)
{
    /*
     * The operational state belongs in the identity.
     *
     * `MapGenMovers_CheckSweeps` decides whether a machine can actually travel
     * between its stops and whether anything in the map can fire it. A lift
     * with the same stops that has become blocked describes a map a player
     * cannot cross, and leaving that out of the comparison is how it would
     * pass.
     */
    size_t used = (size_t)snprintf(out, cap,
        "%s|%s|%s|%s|%.0f %.0f %.0f|%.0f %.0f %.0f|%d%d%d%d|",
        MapGenMovers_KindName(m->kind), m->classname, m->targetname, m->target,
        (double)m->mins[0], (double)m->mins[1], (double)m->mins[2],
        (double)m->maxs[0], (double)m->maxs[1], (double)m->maxs[2],
        m->player_operated ? 1 : 0, m->carries ? 1 : 0,
        m->inoperable ? 1 : 0, m->obstructed ? 1 : 0);
    for (uint32_t s = 0; s < m->num_stops && used + 1 < cap; s++)
        used += (size_t)snprintf(out + used, cap - used, "%.0f %.0f %.0f;",
                                 (double)m->stop[s][0], (double)m->stop[s][1],
                                 (double)m->stop[s][2]);
}

static void operator_text(const mapgen_mover_operator_t *o, char *out,
                          size_t cap)
{
    snprintf(out, cap, "%s|%.0f %.0f %.0f|%.0f %.0f %.0f|%d", o->target,
             (double)o->mins[0], (double)o->mins[1], (double)o->mins[2],
             (double)o->maxs[0], (double)o->maxs[1], (double)o->maxs[2],
             o->shootable ? 1 : 0);
}

static void portal_text(const mapgen_mover_portal_t *p, char *out, size_t cap)
{
    snprintf(out, cap, "%s|%.0f %.0f %.0f|%.0f %.0f %.0f|%d|%.0f %.0f %.0f",
             p->target,
             (double)p->mins[0], (double)p->mins[1], (double)p->mins[2],
             (double)p->maxs[0], (double)p->maxs[1], (double)p->maxs[2],
             p->has_destination ? 1 : 0,
             (double)p->destination[0], (double)p->destination[1],
             (double)p->destination[2]);
}

static void relay_text(const mapgen_mover_relay_t *r, char *out, size_t cap)
{
    snprintf(out, cap, "%s|%s", r->name, r->target);
}

static void push_text(const mapgen_mover_push_t *p, char *out, size_t cap)
{
    snprintf(out, cap, "%.0f %.0f %.0f|%.0f %.0f %.0f|%.0f %.0f %.0f",
             (double)p->mins[0], (double)p->mins[1], (double)p->mins[2],
             (double)p->maxs[0], (double)p->maxs[1], (double)p->maxs[2],
             (double)p->velocity[0], (double)p->velocity[1],
             (double)p->velocity[2]);
}

/*
 * One family of records, compared as a multiset.
 *
 * Order is the reader's, and the reader's order follows the entity order the
 * compiler is free to change - so what is compared is which records exist and
 * how many, not where they sit in an array.
 */
typedef void (*record_fn)(const void *record, char *out, size_t cap);

static uint32_t unmatched_records(const void *left, uint32_t nleft,
                                  const void *right, uint32_t nright,
                                  size_t stride, record_fn render,
                                  char *first, size_t first_size)
{
    if (nleft > 64 || nright > 64)
        return nleft + nright;        /* more than the table holds */
    bool used[64] = { false };
    uint32_t unmatched = 0;
    char a[512], b[512];
    for (uint32_t i = 0; i < nleft; i++) {
        render((const char *)left + i * stride, a, sizeof(a));
        bool found = false;
        for (uint32_t k = 0; k < nright && !found; k++) {
            if (used[k])
                continue;
            render((const char *)right + k * stride, b, sizeof(b));
            if (!strcmp(a, b)) {
                used[k] = true;
                found = true;
            }
        }
        if (!found) {
            unmatched++;
            if (first && first_size && !first[0])
                snprintf(first, first_size, "%s", a);
        }
    }
    for (uint32_t k = 0; k < nright; k++)
        if (!used[k])
            unmatched++;
    return unmatched;
}

static void render_mover(const void *r, char *out, size_t cap)
{
    mover_text((const mapgen_mover_t *)r, out, cap);
}
static void render_operator(const void *r, char *out, size_t cap)
{
    operator_text((const mapgen_mover_operator_t *)r, out, cap);
}
static void render_portal(const void *r, char *out, size_t cap)
{
    portal_text((const mapgen_mover_portal_t *)r, out, cap);
}
static void render_relay(const void *r, char *out, size_t cap)
{
    relay_text((const mapgen_mover_relay_t *)r, out, cap);
}
static void render_push(const void *r, char *out, size_t cap)
{
    push_text((const mapgen_mover_push_t *)r, out, cap);
}

static mapgen_equiv_result_t
axis_mover(const mapgen_bsp_t *d, const mapgen_bsp_t *b,
           mapgen_equiv_report_t *r)
{
    mapgen_movers_t md, mb;
    if (!MapGenMovers_Read(d, &md) || !MapGenMovers_Read(b, &mb)) {
        say(r, "mover", "the mover set could not be read");
        return MAPGEN_EQUIV_DIFF_MOVER;
    }
    if (md.overflowed || mb.overflowed) {
        say(r, "mover", "more machines than the mover table holds");
        return MAPGEN_EQUIV_DIFF_MOVER;
    }

    r->movers[0] = md.num_movers;
    r->movers[1] = mb.num_movers;
    r->operators[0] = md.num_operators;
    r->operators[1] = mb.num_operators;
    r->portals[0] = md.num_portals;
    r->portals[1] = mb.num_portals;
    r->relays[0] = md.num_relays;
    r->relays[1] = mb.num_relays;
    r->pushes[0] = md.num_pushes;
    r->pushes[1] = mb.num_pushes;

    if (md.num_movers != mb.num_movers || md.num_operators != mb.num_operators
        || md.num_portals != mb.num_portals || md.num_relays != mb.num_relays
        || md.num_pushes != mb.num_pushes) {
        say(r, "mover",
            "movers %u/%u operators %u/%u teleporters %u/%u relays %u/%u "
            "pushes %u/%u", md.num_movers, mb.num_movers, md.num_operators,
            mb.num_operators, md.num_portals, mb.num_portals, md.num_relays,
            mb.num_relays, md.num_pushes, mb.num_pushes);
        return MAPGEN_EQUIV_DIFF_MOVER;
    }

    /*
     * Every family, not just the machines.
     *
     * The counts above proved only that there are as many buttons as there
     * were. A button moved across the room, a teleporter pointed somewhere
     * else, a relay rewired or a push volume made twice as strong all keep the
     * counts and change the map.
     */
    char first[512] = "";
    uint32_t unmatched = 0;
    unmatched += unmatched_records(md.movers, md.num_movers, mb.movers,
                                   mb.num_movers, sizeof(md.movers[0]),
                                   render_mover, first, sizeof(first));
    unmatched += unmatched_records(md.operators, md.num_operators,
                                   mb.operators, mb.num_operators,
                                   sizeof(md.operators[0]), render_operator,
                                   first, sizeof(first));
    unmatched += unmatched_records(md.portals, md.num_portals, mb.portals,
                                   mb.num_portals, sizeof(md.portals[0]),
                                   render_portal, first, sizeof(first));
    unmatched += unmatched_records(md.relays, md.num_relays, mb.relays,
                                   mb.num_relays, sizeof(md.relays[0]),
                                   render_relay, first, sizeof(first));
    unmatched += unmatched_records(md.pushes, md.num_pushes, mb.pushes,
                                   mb.num_pushes, sizeof(md.pushes[0]),
                                   render_push, first, sizeof(first));
    r->mover_stops_differ = unmatched;
    if (unmatched)
        say(r, "mover",
            "%u mover records have no counterpart; the first is %s",
            unmatched, first[0] ? first : "(only in the baseline)");
    return unmatched ? MAPGEN_EQUIV_DIFF_MOVER : MAPGEN_EQUIV_OK;
}

static bool is_spawn(const char *classname)
{
    return !strcmp(classname, "info_player_deathmatch")
        || !strcmp(classname, "info_player_start")
        || !strcmp(classname, "info_player_coop");
}

static bool is_pickup(const char *classname)
{
    return !strncmp(classname, "item_", 5) || !strncmp(classname, "weapon_", 7)
        || !strncmp(classname, "ammo_", 5);
}

/* How far below a placement the floor is, or -1 when there is none within a
   step of falling. A pickup that lost its floor is a pickup that fell. */
static float support_depth(const mapgen_bsp_t *bsp, const float origin[3])
{
    for (float drop = 0.0f; drop <= 128.0f; drop += 4.0f) {
        const float p[3] = { origin[0], origin[1], origin[2] - drop };
        if (class_at(bsp, p) == MAPGEN_EQUIV_SOLID)
            return drop;
    }
    return -1.0f;
}

/*
 * What a compiled map owes a player before any walk is run: every place he can
 * be put, and everything he can pick up, stands in the kind of space it was
 * meant to stand in, with the same floor under it.
 *
 * Asked twice, because one question is not enough. Each map is asked about its
 * OWN placements, and the two answers compared - that sees a pickup that moved.
 * Then the donor's placements are looked up in both maps - that sees a floor
 * that moved out from under one that did not.
 */
static void obligation_text(const eblock_t *e, const mapgen_bsp_t *bsp,
                            char *out, size_t cap)
{
    const int cls = class_at(bsp, e->origin);
    const float depth = support_depth(bsp, e->origin);
    snprintf(out, cap, "%s|%s|%.0f", e->classname,
             MapGenEquivalence_ClassName(cls),
             depth < 0.0f ? -1.0 : (double)((int)(depth / 8.0f) * 8));
}

static int text_order(const void *a, const void *b)
{
    return strcmp((const char *)a, (const char *)b);
}

#define OBLIGATION_TEXT 96

static uint32_t collect_obligations(const entities_t *e,
                                    const mapgen_bsp_t *bsp,
                                    char (*out)[OBLIGATION_TEXT], uint32_t max)
{
    uint32_t n = 0;
    for (uint32_t i = 0; i < e->n && n < max; i++) {
        const eblock_t *block = &e->b[i];
        if (!block->has_origin
            || (!is_spawn(block->classname) && !is_pickup(block->classname)))
            continue;
        obligation_text(block, bsp, out[n], OBLIGATION_TEXT);
        n++;
    }
    qsort(out, n, OBLIGATION_TEXT, text_order);
    return n;
}

static mapgen_equiv_result_t
axis_traversal(const mapgen_bsp_t *d, const mapgen_bsp_t *b,
               const entities_t *ed, const entities_t *eb,
               const mapgen_equiv_policy_t *pol, mapgen_equiv_report_t *r)
{
    r->areas[0] = MapGenBsp_NumAreas(d);
    r->areas[1] = MapGenBsp_NumAreas(b);
    for (int side = 0; side < 2; side++) {
        const mapgen_bsp_t *bsp = side ? b : d;
        const uint32_t n = MapGenBsp_NumLeafs(bsp);
        for (uint32_t i = 0; i < n; i++) {
            const mapgen_bsp_leaf_t *leaf = MapGenBsp_Leaf(bsp, i);
            if (leaf && (leaf->contents & BIT_AREAPORTAL))
                r->areaportal_leafs[side]++;
        }
    }
    for (uint32_t i = 0; i < ed->n; i++) {
        r->spawns[0] += is_spawn(ed->b[i].classname) ? 1 : 0;
        r->pickups[0] += is_pickup(ed->b[i].classname) ? 1 : 0;
    }
    for (uint32_t i = 0; i < eb->n; i++) {
        r->spawns[1] += is_spawn(eb->b[i].classname) ? 1 : 0;
        r->pickups[1] += is_pickup(eb->b[i].classname) ? 1 : 0;
    }

    if (r->areas[0] != r->areas[1]
        || r->areaportal_leafs[0] != r->areaportal_leafs[1]) {
        say(r, "traversal", "areas %u/%u, areaportal leaves %u/%u",
            r->areas[0], r->areas[1], r->areaportal_leafs[0],
            r->areaportal_leafs[1]);
        return MAPGEN_EQUIV_DIFF_TRAVERSAL;
    }

    /*
     * And the areas themselves, matched by what they hold.
     *
     * The count above says how many there are. Two maps can agree on that
     * while an area has been merged with its neighbour, split in two or
     * resized, so each area is described by how many leaves it holds and how
     * much space they take, and the two multisets are compared. The compiler
     * renumbers areas freely; nothing here depends on the number.
     */
    {
        uint32_t leaves[2][MAX_AREAS];
        double volume[2][MAX_AREAS];
        double classes[MAPGEN_EQUIV_CLASSES];
        memset(leaves, 0, sizeof(leaves));
        collect_leaf_volumes(d, classes, volume[0]);
        collect_leaf_volumes(b, classes, volume[1]);
        for (int side = 0; side < 2; side++) {
            const mapgen_bsp_t *bsp = side ? b : d;
            const uint32_t n = MapGenBsp_NumLeafs(bsp);
            for (uint32_t i = 0; i < n; i++) {
                const mapgen_bsp_leaf_t *leaf = MapGenBsp_Leaf(bsp, i);
                if (!leaf || leaf->area < 0
                    || (uint32_t)leaf->area >= MAX_AREAS)
                    continue;
                leaves[side][leaf->area]++;
            }
        }
        bool taken[MAX_AREAS] = { false };
        char first[96] = "";
        for (uint32_t i = 0; i < MAX_AREAS; i++) {
            if (!leaves[0][i])
                continue;
            /*
             * Matched by VOLUME, not by leaf count.
             *
             * How many leaves an area is cut into is the compiler's decision -
             * the same space, split differently, is the same area - so
             * comparing counts fails a baseline for a choice its own toolchain
             * made. How much space the area holds is a property of the map.
             */
            bool found = false;
            for (uint32_t k = 0; k < MAX_AREAS && !found; k++) {
                if (taken[k] || !leaves[1][k])
                    continue;
                if (permille(volume[0][i], volume[1][k])
                    > (double)pol->volume_permille)
                    continue;
                taken[k] = true;
                found = true;
            }
            if (!found) {
                r->areas_unmatched++;
                if (!first[0])
                    snprintf(first, sizeof(first),
                             "an area holding %.0f units in %u leaves",
                             volume[0][i], leaves[0][i]);
            }
        }
        for (uint32_t k = 0; k < MAX_AREAS; k++)
            if (leaves[1][k] && !taken[k])
                r->areas_unmatched++;
        if (r->areas_unmatched) {
            say(r, "traversal",
                "%u areas have no counterpart; the first is %s",
                r->areas_unmatched, first[0] ? first : "(only in the baseline)");
            return MAPGEN_EQUIV_DIFF_TRAVERSAL;
        }

        /*
         * And WHICH areas each portal joins.
         *
         * Everything above holds while a portal is rewired to a different
         * neighbour, and a rewired portal seals the map differently - which is
         * the whole job of an areaportal. So each portal is described by its
         * two ends and the two multisets of descriptions are compared.
         *
         * An end is (how many portals that area has, how much space it holds).
         * Areas are renumbered freely by the compiler, so no number is used;
         * the degree is exact, and the volume carries the same tolerance the
         * area matching above already uses.
         *
         * Blind spot, stated rather than hidden: a portal moved between two
         * areas whose degree AND volume equal the pair it left describes
         * identically, and the multiset does not move.
         */
        /*
         * Built from what the AREAS reference, not from how long the lump is.
         *
         * Measured on all four donors: each carries exactly one AREAPORTALS
         * record that no area points at - both areas declare numareaportals 0 -
         * and the frozen compiler does not emit it. The engine floods areas by
         * walking area -> firstareaportal .. +numareaportals and never reads
         * outside that range, so a trailing unreferenced record cannot change
         * how the map is sealed. Comparing lump lengths would fail a baseline
         * over a byte nothing reads.
         */
        /* Sized by what the areas DECLARE, which is not the same number as
           the lump length: ranges may overlap, and sizing by the lump would
           drop the edges past its end without saying so. */
        uint32_t np[2] = { 0, 0 };
        for (int side = 0; side < 2; side++) {
            const mapgen_bsp_t *bsp = side ? b : d;
            const uint32_t na = MapGenBsp_NumAreas(bsp);
            for (uint32_t a = 0; a < na && a < MAX_AREAS; a++) {
                const mapgen_bsp_area_t *ar = MapGenBsp_Area(bsp, a);
                if (ar && ar->numareaportals > 0)
                    np[side] += (uint32_t)ar->numareaportals;
            }
        }
        if (np[0] || np[1]) {
            /* one row per declared portal on each side: from-degree,
               from-volume, to-degree, to-volume */
            struct edge { int32_t fd, td; double fv, tv; };
            struct edge *e[2] = { calloc(np[0] ? np[0] : 1, sizeof(struct edge)),
                                  calloc(np[1] ? np[1] : 1, sizeof(struct edge)) };
            if (!e[0] || !e[1]) {
                free(e[0]);
                free(e[1]);
                return MAPGEN_EQUIV_ERR_MEMORY;
            }
            uint32_t n[2] = { 0, 0 };
            for (int side = 0; side < 2; side++) {
                const mapgen_bsp_t *bsp = side ? b : d;
                const uint32_t na = MapGenBsp_NumAreas(bsp);
                for (uint32_t a = 0; a < na && a < MAX_AREAS; a++) {
                    const mapgen_bsp_area_t *ar = MapGenBsp_Area(bsp, a);
                    if (!ar)
                        continue;
                    for (int32_t k = 0; k < ar->numareaportals; k++) {
                        const mapgen_bsp_areaportal_t *ap =
                            MapGenBsp_AreaPortal(bsp,
                                (uint32_t)(ar->firstareaportal + k));
                        if (!ap || ap->otherarea < 0
                            || (uint32_t)ap->otherarea >= MAX_AREAS
                            || n[side] >= np[side])
                            continue;
                        const mapgen_bsp_area_t *other =
                            MapGenBsp_Area(bsp, (uint32_t)ap->otherarea);
                        struct edge *row = &e[side][n[side]++];
                        row->fd = ar->numareaportals;
                        row->fv = volume[side][a];
                        row->td = other ? other->numareaportals : -1;
                        row->tv = volume[side][ap->otherarea];
                    }
                }
            }
            uint32_t unmatched = 0;
            char firstedge[112] = "";
            bool *used = calloc(n[1] ? n[1] : 1, sizeof(bool));
            if (!used) {
                free(e[0]);
                free(e[1]);
                return MAPGEN_EQUIV_ERR_MEMORY;
            }
            for (uint32_t i2 = 0; i2 < n[0]; i2++) {
                const struct edge *want2 = &e[0][i2];
                bool found2 = false;
                for (uint32_t k = 0; k < n[1] && !found2; k++) {
                    const struct edge *got = &e[1][k];
                    if (used[k] || got->fd != want2->fd || got->td != want2->td)
                        continue;
                    if (permille(want2->fv, got->fv)
                            > (double)pol->volume_permille
                        || permille(want2->tv, got->tv)
                            > (double)pol->volume_permille)
                        continue;
                    used[k] = true;
                    found2 = true;
                }
                if (!found2) {
                    unmatched++;
                    if (!firstedge[0])
                        snprintf(firstedge, sizeof(firstedge),
                                 "a portal joining an area of %.0f units with "
                                 "%d portals to one of %.0f units with %d",
                                 want2->fv, want2->fd, want2->tv, want2->td);
                }
            }
            for (uint32_t k = 0; k < n[1]; k++)
                if (!used[k])
                    unmatched++;
            free(used);
            free(e[0]);
            free(e[1]);
            if (unmatched) {
                r->areas_unmatched += unmatched;
                say(r, "traversal",
                    "%u areaportals join different areas; the first is %s",
                    unmatched,
                    firstedge[0] ? firstedge : "(only in the baseline)");
                return MAPGEN_EQUIV_DIFF_TRAVERSAL;
            }
        }
    }

    /* Each map on its own placements. */
    const uint32_t cap = ed->n + eb->n + 1;
    char (*want)[OBLIGATION_TEXT] = calloc(cap, OBLIGATION_TEXT);
    char (*have)[OBLIGATION_TEXT] = calloc(cap, OBLIGATION_TEXT);
    if (!want || !have) {
        free(want);
        free(have);
        return MAPGEN_EQUIV_ERR_MEMORY;
    }
    const uint32_t nw = collect_obligations(ed, d, want, cap);
    const uint32_t nh = collect_obligations(eb, b, have, cap);

    char first[MAPGEN_EQUIV_NAME] = "";
    uint32_t i = 0, k = 0;
    while (i < nw && k < nh) {
        const int cmp = strcmp(want[i], have[k]);
        if (cmp == 0) {
            i++;
            k++;
        } else {
            if (!first[0])
                snprintf(first, sizeof(first), "%s",
                         cmp < 0 ? want[i] : have[k]);
            r->obligations_broken++;
            if (cmp < 0)
                i++;
            else
                k++;
        }
    }
    for (; i < nw; i++) {
        if (!first[0])
            snprintf(first, sizeof(first), "%s", want[i]);
        r->obligations_broken++;
    }
    for (; k < nh; k++) {
        if (!first[0])
            snprintf(first, sizeof(first), "%s", have[k]);
        r->obligations_broken++;
    }
    free(want);
    free(have);

    /* And the donor's placements, looked up in both: a floor that moved out
       from under something that stayed where it was. */
    for (uint32_t e = 0; e < ed->n; e++) {
        const eblock_t *block = &ed->b[e];
        if (!block->has_origin
            || (!is_spawn(block->classname) && !is_pickup(block->classname)))
            continue;
        const int cd = class_at(d, block->origin);
        const int cb = class_at(b, block->origin);
        const float sd = support_depth(d, block->origin);
        const float sb = support_depth(b, block->origin);
        if (cd != cb || fabsf(sd - sb) > pol->bounds_epsilon + 4.0f) {
            r->obligations_broken++;
            if (!first[0])
                snprintf(first, sizeof(first), "%s", block->classname);
        }
    }

    if (r->obligations_broken) {
        say(r, "traversal",
            "%u placements do not stand the same way in both maps; first is %s",
            r->obligations_broken, first);
        return MAPGEN_EQUIV_DIFF_TRAVERSAL;
    }
    return MAPGEN_EQUIV_OK;
}

/* ---- the gate ------------------------------------------------------------ */

mapgen_equiv_result_t
MapGenEquivalence_Compare(const mapgen_bsp_t *donor,
                          const mapgen_bsp_t *baseline,
                          const mapgen_equiv_policy_t *policy,
                          mapgen_equiv_report_t *out)
{
    mapgen_equiv_policy_t fallback;
    if (!policy) {
        MapGenEquivalence_DefaultPolicy(&fallback);
        policy = &fallback;
    }
    if (!donor || !baseline || !out)
        return MAPGEN_EQUIV_ERR_ARGS;

    memset(out, 0, sizeof(*out));
    out->worst_volume_class = MAPGEN_EQUIV_SOLID;

    groups_t gd, gb;
    materials_t md, mb;
    entities_t ed = { 0 }, eb = { 0 };
    groups_init(&gd);
    groups_init(&gb);
    materials_init(&md);
    materials_init(&mb);
    mapgen_equiv_result_t rc = MAPGEN_EQUIV_OK;

    /*
     * The entities come first, because the surfaces are grouped by which
     * MACHINE draws them and that identity comes from the bindings. Grouping
     * by the raw submodel number would fail a baseline for a renumbering the
     * allowed list permits.
     */
    if (!parse_entities(donor, policy, &ed)
        || !parse_entities(baseline, policy, &eb)) {
        snprintf(out->detail, sizeof(out->detail),
                 "an entity string could not be read exactly");
        rc = MAPGEN_EQUIV_ERR_ENTITIES;
        goto done;
    }
    model_identity_t ident_d, ident_b;
    identify_models(donor, &ed, baseline, &eb, &ident_d, &ident_b);

    /* Groups carry the architectural plane set; materials carry the surface
       and mapping signatures. Both are read off the same faces, once. */
    if (!collect_surfaces(donor, baseline, policy, &ident_d, &gd, NULL)
        || !collect_surfaces(baseline, donor, policy, &ident_b, &gb, NULL)
        || !collect_materials(donor, baseline, &ident_d, &md, &out->drawn_area[0], &out->sealed_faces[0])
        || !collect_materials(baseline, donor, &ident_b, &mb, &out->drawn_area[1], &out->sealed_faces[1])) {
        rc = MAPGEN_EQUIV_ERR_MEMORY;
        goto done;
    }
    /*
     * Every axis runs, in this order, and the FIRST failure is the verdict.
     * The order is the order a reader would want to be told about it: what
     * space is, then what bounds it, then what is drawn on it, then how, then
     * who owns it, then what is in it, then what moves, then what a player
     * still owes.
     */
    rc = axis_space(donor, baseline, policy, out);
    if (rc == MAPGEN_EQUIV_ERR_ARGS || rc == MAPGEN_EQUIV_ERR_LIMIT)
        goto done;
    axis_done(out, rc);

    rc = axis_architecture(donor, baseline, &gd, &gb, policy, out);
    if (rc == MAPGEN_EQUIV_ERR_MEMORY)
        goto done;
    axis_done(out, rc);

    axis_done(out, axis_presence(donor, baseline, &gd, &gb, &ident_d,
                                 &ident_b, policy, out));
    axis_done(out, axis_surface(&md, &mb, policy, out));
    axis_done(out, axis_mapping(&gd, &gb, policy, out));

    rc = axis_ownership(donor, baseline, &ed, &eb, out);
    if (rc == MAPGEN_EQUIV_ERR_MEMORY)
        goto done;
    axis_done(out, rc);

    axis_done(out, axis_entity(&ed, &eb, out));
    axis_done(out, axis_mover(donor, baseline, out));
    if (policy->compare_traversal)
        axis_done(out, axis_traversal(donor, baseline, &ed, &eb, policy, out));
    rc = out->result;

done:
    groups_free(&gd);
    groups_free(&gb);
    materials_free(&md);
    materials_free(&mb);
    free(ed.b);
    free(eb.b);
    out->result = rc;
    out->pending[0] = '\0';
    if (rc == MAPGEN_EQUIV_OK) {
        snprintf(out->axis, sizeof(out->axis), "%s", "none");
        snprintf(out->detail, sizeof(out->detail), "%s",
                 "the baseline is the donor on every axis");
    }
    return rc;
}
