/*
 * The strip of sky in the middle of a wall, found without a camera.
 *
 * Three oracles looked at the map the PO photographed that strip in and all
 * three said it was fine. They were each asking a question the defect does not
 * answer to:
 *
 *   the wall audit probes one point per surface, at its middle, and a strip is
 *   never in the middle of anything;
 *   the seam audit asks whether the SOLID is still there, and it is - the sky
 *   you see through the gap is a sky brush, which is solid, so the map does not
 *   leak and the collision hull is intact;
 *   the coverage oracle allows a candidate face two units off-plane and a full
 *   sampling step of slack outside its edge, which is more slack than the whole
 *   defect: the wall came back drawn half a unit further in, and every point of
 *   it was "covered" by the face that had moved.
 *
 * So this one asks the question a player asks. Every point the donor DRAWS must
 * be drawn by the candidate, on the same plane, within a hair - not on a
 * neighbouring plane, not with a step's worth of grace. Where it is not, the
 * ray that would have stopped at that wall carries on, and what it reaches
 * instead is reported: a sky surface behind the gap is exactly the bright blue
 * strip in the photograph.
 *
 *     mapgen_visible_holes <donor.bsp> <candidate.bsp> [step] [margin]
 *
 * Exit 0 when every drawn point survives, 1 when a run of them does not.
 */

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"

#define MAX_POLY      64
#define MAX_HOLES     200000
#define CLUSTER_REACH 16.0

/* Surfaces the donor does not really draw, or draws as background. */
#define SURF_SKY_BIT    0x0004
#define SURF_WARP_BIT   0x0008
#define SURF_NODRAW_BIT 0x0080
#define SURF_HINT_BIT   0x0100
#define SURF_SKIP_BIT   0x0200
#define SURF_TRANS33    0x0010
#define SURF_TRANS66    0x0020

/* How nearly two planes must agree to be the same wall. A face half a unit
   behind the one it replaced is the defect, not a match for it. */
#define PLANE_SAME_DIST  0.06
#define PLANE_SAME_DOT   0.9999

typedef struct {
    double p[MAX_POLY][3];
    int n;
    float normal[3];
    float dist;
    uint32_t flags;
    const char *texture;
} poly_t;

typedef struct {
    double mins[3], maxs[3];
    uint32_t count;
    const char *texture;
    const char *behind;
    /* What a player would actually see instead, and how far away it is: a
       surface a fifth of a unit back with the same texture on it is a plane
       the compiler re-derived, not a hole, and only the distance tells the
       two apart. */
    double behind_at;
    float normal[3];
    float dist;
} hole_t;

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
    if (MapGenBsp_Load(raw, (size_t)n, &bsp) != MAPGEN_BSP_OK)
        bsp = NULL;
    free(raw);
    return bsp;
}

/* One face as a polygon on an outward-facing plane. */
static bool face_poly(const mapgen_bsp_t *b, uint32_t i, poly_t *out)
{
    const mapgen_bsp_face_t *face = MapGenBsp_Face(b, i);
    if (face->numedges < 3 || face->numedges > MAX_POLY)
        return false;
    const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(b, face->planenum);
    const float s = face->side ? -1.0f : 1.0f;
    for (int a = 0; a < 3; a++)
        out->normal[a] = pl->normal[a] * s;
    out->dist = pl->dist * s;
    out->n = face->numedges;
    for (int32_t e = 0; e < face->numedges; e++) {
        const int32_t se = MapGenBsp_SurfEdge(b, (uint32_t)(face->firstedge + e));
        const mapgen_bsp_edge_t *ed =
            MapGenBsp_Edge(b, (uint32_t)(se < 0 ? -se : se));
        const mapgen_bsp_vertex_t *v =
            MapGenBsp_Vertex(b, se < 0 ? ed->v[1] : ed->v[0]);
        for (int a = 0; a < 3; a++)
            out->p[e][a] = v->point[a];
    }
    const mapgen_bsp_texinfo_t *ti =
        MapGenBsp_TexInfo(b, (uint32_t)face->texinfo);
    out->flags = ti ? ti->flags : 0;
    out->texture = ti ? ti->texture : "?";
    return true;
}

/* The two in-plane directions this polygon is measured in. */
static void basis(const float normal[3], double u[3], double v[3])
{
    int minor = 0;
    for (int a = 1; a < 3; a++)
        if (fabsf(normal[a]) < fabsf(normal[minor]))
            minor = a;
    double t[3] = { 0, 0, 0 };
    t[minor] = 1.0;
    double d = 0.0;
    for (int a = 0; a < 3; a++)
        d += t[a] * normal[a];
    double len = 0.0;
    for (int a = 0; a < 3; a++) {
        u[a] = t[a] - normal[a] * d;
        len += u[a] * u[a];
    }
    len = sqrt(len);
    for (int a = 0; a < 3; a++)
        u[a] /= len;
    v[0] = normal[1] * u[2] - normal[2] * u[1];
    v[1] = normal[2] * u[0] - normal[0] * u[2];
    v[2] = normal[0] * u[1] - normal[1] * u[0];
}

/*
 * Is the point inside this polygon by more than `margin`?
 *
 * Inside-ness and the distance to the nearest edge together, so that a point a
 * hair outside a face that merely got re-split does not read as a hole while a
 * point well clear of every face does.
 */
static bool covers(const poly_t *poly, const double u[3], const double v[3],
                   double a, double b, double margin)
{
    double su[MAX_POLY], sv[MAX_POLY];
    for (int e = 0; e < poly->n; e++) {
        su[e] = sv[e] = 0.0;
        for (int k = 0; k < 3; k++) {
            su[e] += poly->p[e][k] * u[k];
            sv[e] += poly->p[e][k] * v[k];
        }
    }
    bool in = false;
    for (int e = 0, j = poly->n - 1; e < poly->n; j = e++)
        if ((sv[e] > b) != (sv[j] > b)
            && a < (su[j] - su[e]) * (b - sv[e]) / (sv[j] - sv[e]) + su[e])
            in = !in;
    if (in)
        return true;
    if (margin <= 0.0)
        return false;
    /* Just outside is still covered, if it is only just. */
    for (int e = 0, j = poly->n - 1; e < poly->n; j = e++) {
        const double ex = su[e] - su[j], ey = sv[e] - sv[j];
        const double len2 = ex * ex + ey * ey;
        double t = len2 > 0 ? ((a - su[j]) * ex + (b - sv[j]) * ey) / len2 : 0.0;
        t = t < 0 ? 0 : (t > 1 ? 1 : t);
        const double dx = a - (su[j] + ex * t), dy = b - (sv[j] + ey * t);
        if (dx * dx + dy * dy <= margin * margin)
            return true;
    }
    return false;
}

/* What the eye reaches instead, once the wall is not there: the first face
   behind the gap, along the direction the missing wall faced. */
static const char *behind(const poly_t *cand, uint32_t count,
                          const double at[3], const float dir[3],
                          double *out_distance)
{
    double best = 1e30;
    const char *what = NULL;
    for (uint32_t c = 0; c < count; c++) {
        const poly_t *q = &cand[c];
        double nd = 0.0, np = 0.0;
        for (int a = 0; a < 3; a++) {
            nd += q->normal[a] * dir[a];
            np += q->normal[a] * at[a];
        }
        if (fabs(nd) < 1e-6)
            continue;
        const double t = (q->dist - np) / nd;
        if (t <= 0.05 || t >= best)
            continue;
        double hit[3], u[3], v[3], a2 = 0.0, b2 = 0.0;
        for (int a = 0; a < 3; a++)
            hit[a] = at[a] + dir[a] * t;
        basis(q->normal, u, v);
        for (int a = 0; a < 3; a++) {
            a2 += hit[a] * u[a];
            b2 += hit[a] * v[a];
        }
        if (!covers(q, u, v, a2, b2, 0.0))
            continue;
        best = t;
        what = (q->flags & SURF_SKY_BIT) ? "the sky" : q->texture;
    }
    if (out_distance)
        *out_distance = what ? best : -1.0;
    return what ? what : "nothing (the void)";
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <donor.bsp> <candidate.bsp> [step]"
                        " [margin]\n", argv[0]);
        return 2;
    }
    const double step = argc > 3 ? strtod(argv[3], NULL) : 1.0;
    const double margin = argc > 4 ? strtod(argv[4], NULL) : 0.35;

    mapgen_bsp_t *donor = load(argv[1]);
    mapgen_bsp_t *cand = load(argv[2]);
    if (!donor || !cand) {
        fprintf(stderr, "cannot read one of them\n");
        return 2;
    }

    const uint32_t nc = MapGenBsp_NumFaces(cand);
    poly_t *cpoly = calloc(nc ? nc : 1, sizeof(*cpoly));
    uint32_t ncp = 0;
    for (uint32_t i = 0; i < nc; i++)
        if (face_poly(cand, i, &cpoly[ncp]))
            ncp++;

    hole_t *holes = calloc(4096, sizeof(*holes));
    uint32_t num_holes = 0;
    uint64_t sampled = 0, missing = 0;

    const uint32_t nd = MapGenBsp_NumFaces(donor);
    uint32_t *match = calloc(ncp ? ncp : 1, sizeof(*match));

    for (uint32_t i = 0; i < nd; i++) {
        poly_t d;
        if (!face_poly(donor, i, &d))
            continue;
        if (d.flags & (SURF_SKY_BIT | SURF_NODRAW_BIT | SURF_HINT_BIT
                       | SURF_SKIP_BIT))
            continue;

        /* Every candidate face that could be this wall. */
        uint32_t nm = 0;
        for (uint32_t c = 0; c < ncp; c++) {
            double dot = 0.0;
            for (int a = 0; a < 3; a++)
                dot += cpoly[c].normal[a] * d.normal[a];
            if (dot < PLANE_SAME_DOT)
                continue;
            if (fabs((double)cpoly[c].dist - d.dist) > PLANE_SAME_DIST)
                continue;
            if (cpoly[c].flags & SURF_NODRAW_BIT)
                continue;
            match[nm++] = c;
        }

        double u[3], v[3];
        basis(d.normal, u, v);
        double su[MAX_POLY], sv[MAX_POLY];
        double lo_u = 1e30, hi_u = -1e30, lo_v = 1e30, hi_v = -1e30;
        for (int e = 0; e < d.n; e++) {
            su[e] = sv[e] = 0.0;
            for (int a = 0; a < 3; a++) {
                su[e] += d.p[e][a] * u[a];
                sv[e] += d.p[e][a] * v[a];
            }
            if (su[e] < lo_u) lo_u = su[e];
            if (su[e] > hi_u) hi_u = su[e];
            if (sv[e] < lo_v) lo_v = sv[e];
            if (sv[e] > hi_v) hi_v = sv[e];
        }

        for (double a = lo_u + step * 0.5; a < hi_u; a += step) {
            for (double b = lo_v + step * 0.5; b < hi_v; b += step) {
                /*
                 * Inside the donor's own face, and clear of its rim.
                 *
                 * A compiler may re-split one surface into equivalent pieces,
                 * which moves shared edges by a hair; a sample sitting on such
                 * an edge answers about that and not about a hole.
                 */
                if (!covers(&d, u, v, a, b, -1.0))
                    continue;
                bool rim = false;
                for (int e = 0, j = d.n - 1; e < d.n && !rim; j = e++) {
                    const double ex = su[e] - su[j], ey = sv[e] - sv[j];
                    const double l2 = ex * ex + ey * ey;
                    double t = l2 > 0 ? ((a - su[j]) * ex
                                         + (b - sv[j]) * ey) / l2 : 0.0;
                    t = t < 0 ? 0 : (t > 1 ? 1 : t);
                    const double dx = a - (su[j] + ex * t);
                    const double dy = b - (sv[j] + ey * t);
                    rim = dx * dx + dy * dy < margin * margin;
                }
                if (rim)
                    continue;
                sampled++;

                bool covered = false;
                for (uint32_t m = 0; m < nm && !covered; m++)
                    covered = covers(&cpoly[match[m]], u, v, a, b, margin);
                if (covered)
                    continue;
                missing++;

                double at[3];
                for (int k = 0; k < 3; k++)
                    at[k] = d.normal[k] * d.dist + u[k] * a + v[k] * b;

                uint32_t h = num_holes;
                for (uint32_t k = 0; k < num_holes; k++) {
                    bool near = true;
                    for (int x = 0; x < 3 && near; x++)
                        near = at[x] >= holes[k].mins[x] - CLUSTER_REACH
                            && at[x] <= holes[k].maxs[x] + CLUSTER_REACH;
                    if (near && holes[k].texture == d.texture) {
                        h = k;
                        break;
                    }
                }
                if (h == num_holes) {
                    if (num_holes >= 4096)
                        continue;
                    for (int x = 0; x < 3; x++)
                        holes[h].mins[x] = holes[h].maxs[x] = at[x];
                    holes[h].texture = d.texture;
                    float into[3];
                    for (int x = 0; x < 3; x++)
                        into[x] = -d.normal[x];
                    /* a step off the missing wall, looking the way it faced */
                    double from[3];
                    for (int x = 0; x < 3; x++)
                        from[x] = at[x] + d.normal[x] * 0.5;
                    holes[h].behind = behind(cpoly, ncp, from, into,
                                             &holes[h].behind_at);
                    memcpy(holes[h].normal, d.normal, sizeof(holes[h].normal));
                    holes[h].dist = d.dist;
                    holes[h].count = 0;
                    num_holes++;
                }
                for (int x = 0; x < 3; x++) {
                    if (at[x] < holes[h].mins[x]) holes[h].mins[x] = at[x];
                    if (at[x] > holes[h].maxs[x]) holes[h].maxs[x] = at[x];
                }
                holes[h].count++;
            }
        }
    }

    printf("%llu drawn points sampled at %.2f units, %llu no longer drawn"
           " on their own plane, in %u places\n",
           (unsigned long long)sampled, step, (unsigned long long)missing,
           num_holes);

    /* biggest first */
    for (uint32_t i = 0; i < num_holes; i++)
        for (uint32_t j = i + 1; j < num_holes; j++)
            if (holes[j].count > holes[i].count) {
                hole_t t = holes[i];
                holes[i] = holes[j];
                holes[j] = t;
            }
    uint32_t worst = 0;
    const uint32_t show = num_holes < 16 ? num_holes : 16;
    for (uint32_t i = 0; i < show; i++) {
        const hole_t *h = &holes[i];
        const double area = h->count * step * step;
        if (i == 0)
            worst = (uint32_t)area;
        /*
         * How far back the replacement is decides whether this matters.
         *
         * A surface a fifth of a unit behind the one it replaced, wearing the
         * same texture, is the compiler re-deriving a plane from text and no
         * player can see it. Void or sky behind the gap is the defect that was
         * photographed. The distance is printed so the two are never confused
         * for each other again.
         */
        char how_far[32];
        if (h->behind_at < 0.0)
            how_far[0] = '\0';
        else
            snprintf(how_far, sizeof(how_far), ", %.2f behind", h->behind_at);
        printf("  %8.0f sq units  %7.0f %7.0f %7.0f .. %7.0f %7.0f %7.0f"
               "  %-16s plane %6.3f %6.3f %6.3f %10.4f  ->  %s%s\n", area,
               h->mins[0], h->mins[1], h->mins[2],
               h->maxs[0], h->maxs[1], h->maxs[2],
               h->texture, (double)h->normal[0], (double)h->normal[1],
               (double)h->normal[2], (double)h->dist, h->behind, how_far);
    }
    if (num_holes > show)
        printf("  ... and %u more\n", num_holes - show);

    free(match);
    free(holes);
    free(cpoly);
    MapGenBsp_Free(donor);
    MapGenBsp_Free(cand);
    return worst >= 16 ? 1 : 0;
}
