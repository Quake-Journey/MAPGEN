/*
 * Why the big operators refuse on a donor - the evidence for the PO's next stage.
 *
 *     mapgen_refusal_census <donor.bsp> <ground.bsp> <ambition> <seed>
 *
 * Round 35's button tried 629 edits and 584 never built: widen-connector 208,
 * reshape-room 195, turn-bundle 95, stairs-to-lift 64 (ledger row 305). The PO,
 * 2026-09-14: «странно, что ты работаешь целый день делая минимальные изменения
 * на выходе», and then «приступай к следующему этапу». Before an operator is
 * changed, this says which question refuses each of its edits and - for a widen,
 * whose refusals name a neighbouring face without saying which - what that face
 * is: its brush, contents, texture, size, how far from the face being moved, and
 * whether its brush even touches the moving one.
 *
 * And for every widen, what CARVING the doorway would cut instead of sliding one
 * face, measured on the compiled ground at the face's middle: in front of the face
 * the opening's floor and ceiling; behind it the wall's rock across its thickness
 * at mid-height; the box that rock makes, taken `depth` back - how much of it is
 * rock, and whether rock stays behind it, over it and under it.
 *
 * It plans exactly as the pipeline does (`MapGenGeometryEdit_PlanOn`, the ground
 * being the run's baseline) and asks every widen-connector, reshape-room,
 * turn-bundle and stairs-to-lift edit on a fresh copy of the donor's geometry.
 * Nothing is compiled and nothing is written.
 */

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_geometry_edit.h"

#define MAX_TALLY 256
#define CARVE_STEP 8.0f
#define CARVE_KEEP 16.0f
#define CARVE_REACH 512.0f

typedef struct {
    char     key[160];
    uint32_t n;
} tally_t;

static tally_t   g_reasons[MAX_TALLY];
static uint32_t  g_num_reasons;
static tally_t   g_faces[MAX_TALLY];
static uint32_t  g_num_faces;
static tally_t   g_carves[MAX_TALLY];
static uint32_t  g_num_carves;

static void count(tally_t *t, uint32_t *n, const char *key)
{
    for (uint32_t i = 0; i < *n; i++)
        if (!strcmp(t[i].key, key)) {
            t[i].n++;
            return;
        }
    if (*n < MAX_TALLY) {
        snprintf(t[*n].key, sizeof(t[*n].key), "%s", key);
        t[*n].n = 1;
        (*n)++;
    }
}

/* A reason with its numbers taken out, so that one question is one line. */
static void shape_of(const char *why, char *out, size_t size)
{
    size_t o = 0;
    for (const char *s = why; *s && o + 2 < size; s++) {
        const bool digit = (*s >= '0' && *s <= '9')
                        || ((*s == '-' || *s == '.') && s[1] >= '0' && s[1] <= '9');
        if (digit) {
            while (s[1] && ((s[1] >= '0' && s[1] <= '9') || s[1] == '.'))
                s++;
            out[o++] = 'N';
        } else {
            out[o++] = *s;
        }
    }
    out[o] = '\0';
}

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t rc = MapGenBsp_Load(raw, (size_t)n, &bsp);
    free(raw);
    return rc == MAPGEN_BSP_OK ? bsp : NULL;
}

static uint32_t brush_of_side(const mapgen_geometry_t *g, uint32_t s)
{
    const uint32_t brushes = MapGenGeometry_NumBrushes(g);
    for (uint32_t b = 0; b < brushes; b++) {
        const mapgen_geometry_brush_t *brush = MapGenGeometry_Brush(g, b);
        if (brush && s >= brush->first_side
            && s < brush->first_side + brush->num_sides)
            return b;
    }
    return UINT32_MAX;
}

/* Do two brushes' boxes meet, a unit of slack either way? */
static bool brushes_touch(const mapgen_geometry_brush_t *a,
                          const mapgen_geometry_brush_t *b)
{
    if (!a || !b)
        return true;
    for (int k = 0; k < 3; k++)
        if (a->mins[k] > b->maxs[k] + 1.0f || b->mins[k] > a->maxs[k] + 1.0f)
            return false;
    return true;
}

/* The face a widen names: on its plane, within 64 of its middle - `side_on_plane`. */
static uint32_t find_face(const mapgen_geometry_t *g, const float normal[3],
                          float dist, const float center[3])
{
    const uint32_t sides = MapGenGeometry_NumSides(g);
    for (uint32_t s = 0; s < sides; s++) {
        const mapgen_geometry_side_t *side = MapGenGeometry_Side(g, s);
        if (!side || side->bevel || fabsf(side->dist - dist) > 0.05f)
            continue;
        bool same = true;
        float apart = 0.0f;
        for (int a = 0; a < 3; a++) {
            same = same && fabsf(side->normal[a] - normal[a]) <= 0.001f;
            apart += (side->center[a] - center[a]) * (side->center[a] - center[a]);
        }
        if (same && apart <= 64.0f * 64.0f)
            return s;
    }
    return UINT32_MAX;
}

/*
 * The first neighbour that refuses a widen, found the way `widen_is_safe_why`
 * finds it: any other face on that plane (FLUSH) or on it facing the other way
 * (BACKFACE) within 256 - and of those, how many belong to a brush that even
 * touches the one being moved.
 */
static void name_neighbour(const mapgen_geometry_t *g, uint32_t mine)
{
    const uint32_t sides = MapGenGeometry_NumSides(g);
    const mapgen_geometry_side_t *face = MapGenGeometry_Side(g, mine);
    const uint32_t owner = brush_of_side(g, mine);
    const mapgen_geometry_brush_t *own = MapGenGeometry_Brush(g, owner);
    uint32_t found = 0, touching = 0;
    for (uint32_t s = 0; s < sides; s++) {
        if (s == mine)
            continue;
        const mapgen_geometry_side_t *other = MapGenGeometry_Side(g, s);
        if (!other || other->bevel)
            continue;
        bool same = fabsf(other->dist - face->dist) <= 0.5f;
        bool opposed = fabsf(other->dist + face->dist) <= 0.5f;
        for (int a = 0; a < 3; a++) {
            if (fabsf(other->normal[a] - face->normal[a]) > 0.01f)
                same = false;
            if (fabsf(other->normal[a] + face->normal[a]) > 0.01f)
                opposed = false;
        }
        if (!same && !opposed)
            continue;
        float apart = 0.0f;
        for (int a = 0; a < 3; a++)
            apart += (other->center[a] - face->center[a]) * (other->center[a] - face->center[a]);
        if (apart > 256.0f * 256.0f)
            continue;
        const uint32_t b = brush_of_side(g, s);
        const mapgen_geometry_brush_t *brush = MapGenGeometry_Brush(g, b);
        const bool meets = brushes_touch(own, brush);
        touching += meets ? 1u : 0u;
        if (found++ == 0) {
            printf(" - face %u of brush %u (%s): brush %u contents %#x, %s,"
                   " '%s' area %.0f at %.0f %.0f %.0f, %.0f apart",
                   mine, owner, same ? "on the same plane" : "facing it", b,
                   brush ? (unsigned)brush->contents : 0u,
                   meets ? "touching the moving brush" : "detached from it",
                   other->texture, (double)other->area, (double)other->center[0],
                   (double)other->center[1], (double)other->center[2], sqrt((double)apart));
        }
    }
    printf(" (%u such faces, %u on brushes touching the moving one)", found, touching);
    count(g_faces, &g_num_faces, touching ? "a refusing face is on a brush touching the moving one"
                                          : "refused only by faces of detached brushes");
}

static bool rock(const mapgen_bsp_t *ground, const float p[3])
{
    return (MapGenBsp_PointContents(ground, p) & MAPGEN_CONTENTS_SOLID) != 0;
}

/* The share of a box's grid points in rock, in percent; 100 for an empty box. */
static uint32_t rock_share(const mapgen_bsp_t *ground, const float lo[3], const float hi[3])
{
    uint32_t n = 0, in = 0;
    for (float x = lo[0] + 1.0f; x < hi[0]; x += CARVE_STEP)
        for (float y = lo[1] + 1.0f; y < hi[1]; y += CARVE_STEP)
            for (float z = lo[2] + 1.0f; z < hi[2]; z += CARVE_STEP) {
                const float p[3] = { x, y, z };
                n++;
                in += rock(ground, p) ? 1u : 0u;
            }
    return n ? in * 100u / n : 100u;
}

/*
 * What carving the doorway would cut, measured at the face's middle on the
 * compiled ground.
 */
static void carve_report(const mapgen_geometry_t *g, const mapgen_bsp_t *ground,
                         uint32_t mine, float depth)
{
    const mapgen_geometry_side_t *face = MapGenGeometry_Side(g, mine);
    int axis = -1;
    for (int a = 0; a < 2; a++)
        if (fabsf(face->normal[a]) > 0.999f)
            axis = a;
    if (axis < 0) {
        printf(" | carve: not an upright face on an axis");
        count(g_carves, &g_num_carves, "not an upright face on an axis");
        return;
    }
    const int across = axis ^ 1;
    const float sgn = face->normal[axis] > 0.0f ? 1.0f : -1.0f;
    const float at = sgn > 0.0f ? face->dist : -face->dist;

    /* the opening in front of the face: its floor and ceiling */
    float p[3] = { face->center[0], face->center[1], face->center[2] };
    p[axis] = at + sgn * 2.0f;
    if (rock(ground, p)) {
        printf(" | carve: rock in front of the face");
        count(g_carves, &g_num_carves, "rock in front of the face");
        return;
    }
    float floor_z = p[2], ceil_z = p[2];
    for (float z = p[2]; z > p[2] - CARVE_REACH; z -= 2.0f) {
        const float q[3] = { p[0], p[1], z };
        if (rock(ground, q))
            break;
        floor_z = z;
    }
    for (float z = p[2]; z < p[2] + CARVE_REACH; z += 2.0f) {
        const float q[3] = { p[0], p[1], z };
        if (rock(ground, q))
            break;
        ceil_z = z;
    }
    const float mid = 0.5f * (floor_z + ceil_z);

    /* the wall behind the face: its rock across the thickness at mid-height */
    float r[3] = { face->center[0], face->center[1], mid };
    r[axis] = at - sgn * 2.0f;
    if (!rock(ground, r)) {
        printf(" | carve: doorway %.0f..%.0f, no rock behind the face at mid-height",
               (double)floor_z, (double)ceil_z);
        count(g_carves, &g_num_carves, "no rock behind the face at mid-height");
        return;
    }
    float t_lo = r[across], t_hi = r[across];
    for (float t = r[across]; t > r[across] - CARVE_REACH; t -= 2.0f) {
        float q[3] = { r[0], r[1], r[2] };
        q[across] = t;
        if (!rock(ground, q))
            break;
        t_lo = t;
    }
    for (float t = r[across]; t < r[across] + CARVE_REACH; t += 2.0f) {
        float q[3] = { r[0], r[1], r[2] };
        q[across] = t;
        if (!rock(ground, q))
            break;
        t_hi = t;
    }

    float lo[3], hi[3], back_lo[3], back_hi[3], over_lo[3], over_hi[3], under_lo[3], under_hi[3];
    lo[across] = t_lo;
    hi[across] = t_hi;
    lo[2] = floor_z;
    hi[2] = ceil_z;
    lo[axis] = sgn > 0.0f ? at - depth : at;
    hi[axis] = sgn > 0.0f ? at : at + depth;
    memcpy(back_lo, lo, sizeof(lo));
    memcpy(back_hi, hi, sizeof(hi));
    back_lo[axis] = sgn > 0.0f ? at - depth - CARVE_KEEP : at + depth;
    back_hi[axis] = sgn > 0.0f ? at - depth : at + depth + CARVE_KEEP;
    memcpy(over_lo, lo, sizeof(lo));
    memcpy(over_hi, hi, sizeof(hi));
    over_lo[2] = ceil_z;
    over_hi[2] = ceil_z + CARVE_KEEP;
    memcpy(under_lo, lo, sizeof(lo));
    memcpy(under_hi, hi, sizeof(hi));
    under_lo[2] = floor_z - CARVE_KEEP;
    under_hi[2] = floor_z;

    const uint32_t box = rock_share(ground, lo, hi);
    const uint32_t back = rock_share(ground, back_lo, back_hi);
    const uint32_t over = rock_share(ground, over_lo, over_hi);
    const uint32_t under = rock_share(ground, under_lo, under_hi);
    printf(" | doorway %.0f tall, wall %.0f thick; carve %.0f..%.0f x %.0f..%.0f x %.0f..%.0f:"
           " %u%% rock, behind %u%%, over %u%%, under %u%%", (double)(ceil_z - floor_z),
           (double)(t_hi - t_lo), (double)lo[0], (double)hi[0], (double)lo[1], (double)hi[1],
           (double)lo[2], (double)hi[2], box, back, over, under);
    count(g_carves, &g_num_carves,
          box == 100u && back >= 95u && over >= 95u && under >= 95u
              ? "carvable: all rock, sealed behind, over and under"
          : box < 100u ? (box >= 90u ? "the box is 90-99% rock" : "the box meets air")
          : back < 95u ? "all rock, but it would open behind"
                       : "all rock, but open over or under");
}

int main(int argc, char **argv)
{
    if (argc < 5) {
        fprintf(stderr, "usage: %s donor.bsp ground.bsp ambition seed\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *donor_bsp = load(argv[1]);
    mapgen_bsp_t *ground = load(argv[2]);
    const int32_t ambition = atoi(argv[3]);
    const uint64_t seed = strtoull(argv[4], NULL, 10);
    mapgen_geometry_t *donor = NULL;
    if (!donor_bsp || !ground || MapGenGeometry_FromBsp(donor_bsp, &donor) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot read the maps\n");
        return 2;
    }
    mapgen_geometry_edit_plan_t *plan = NULL;
    if (MapGenGeometryEdit_PlanOn(donor, donor_bsp, ground, ambition, seed, NULL, NULL, NULL, 0,
                                  &plan) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot plan\n");
        return 2;
    }
    const uint32_t edits = MapGenGeometryEdit_Count(plan);
    printf("plan: seed %llu, ambition %d, %u edits; widen-connector %u, reshape-room %u,"
           " turn-bundle %u, stairs-to-lift %u\n", (unsigned long long)seed, ambition, edits,
           MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_WIDEN_CONNECTOR),
           MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_RESHAPE_ROOM),
           MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_TURN_BUNDLE),
           MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_STAIRS_LIFT));

    for (uint32_t i = 0; i < edits; i++) {
        const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
        if (!e)
            continue;
        const bool widen = e->kind == MAPGEN_EDIT_WIDEN_CONNECTOR;
        if (!widen && e->kind != MAPGEN_EDIT_RESHAPE_ROOM && e->kind != MAPGEN_EDIT_TURN_BUNDLE
            && e->kind != MAPGEN_EDIT_STAIRS_LIFT)
            continue;
        mapgen_geometry_t *candidate = NULL;
        if (MapGenGeometry_Clone(donor, &candidate) != MAPGEN_GEOMETRY_OK)
            continue;
        const char *kind = MapGenGeometryEdit_KindName(e->kind);
        char reason[200];
        if (widen) {
            const mapgen_widen_refusal_t why =
                MapGenGeometryEdit_WhyWidenRefused(plan, candidate, ground, e->target);
            float normal[3] = { 0 }, center[3] = { 0 }, dist = 0.0f;
            MapGenGeometryEdit_WidenAt(plan, e->target, normal, &dist, center);
            printf("%s %u (edit %u) at %.0f %.0f %.0f facing %.2f %.2f %.2f, %d deep: %s", kind,
                   e->target, i, (double)center[0], (double)center[1], (double)center[2],
                   (double)normal[0], (double)normal[1], (double)normal[2], e->amount,
                   MapGenGeometryEdit_WidenRefusalName(why));
            const uint32_t mine = find_face(candidate, normal, dist, center);
            if (mine == UINT32_MAX) {
                printf(" - its face is not found");
            } else {
                if (why == MAPGEN_WIDEN_FLUSH || why == MAPGEN_WIDEN_BACKFACE)
                    name_neighbour(candidate, mine);
                carve_report(candidate, ground, mine, (float)e->amount);
            }
            printf("\n");
            snprintf(reason, sizeof(reason), "%s: %s", kind, MapGenGeometryEdit_WidenRefusalName(why));
        } else {
            bool changed = false;
            MapGenGeometryEdit_ApplyOne(plan, candidate, donor, i, &changed);
            const char *why = changed ? "APPLIES" : MapGenGeometryEdit_WhyDeclined();
            printf("%s %u (edit %u): %s\n", kind, e->target, i, why);
            char shape[160];
            shape_of(why, shape, sizeof(shape));
            snprintf(reason, sizeof(reason), "%s: %s", kind, shape);
        }
        count(g_reasons, &g_num_reasons, reason);
        MapGenGeometry_Free(candidate);
    }

    printf("\n== refusals by question\n");
    for (uint32_t i = 0; i < g_num_reasons; i++)
        printf("  %4u  %s\n", g_reasons[i].n, g_reasons[i].key);
    printf("== the widen's refusing neighbour\n");
    for (uint32_t i = 0; i < g_num_faces; i++)
        printf("  %4u  %s\n", g_faces[i].n, g_faces[i].key);
    printf("== what carving each widen's doorway would cut\n");
    for (uint32_t i = 0; i < g_num_carves; i++)
        printf("  %4u  %s\n", g_carves[i].n, g_carves[i].key);
    return 0;
}
