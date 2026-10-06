/*
 * Where is the wall not there any more?
 *
 * `mapgen_wall_audit` asks the same question and answers it wrong, because it
 * asks it once per surface, at the surface's own middle. A seam is not in the
 * middle of anything. It is a strip a couple of units wide along the line where
 * two brushes were supposed to meet, and every face around it still has solid
 * behind its centre - which is why that audit reported 0 lost on the very map
 * the PO photographed a slit of sky in.
 *
 * Solid is also not the whole question. The defect that took two thirds of a
 * wall off q2dm1's mesh left every brush where it was and moved only the drawn
 * FACE; `mapgen_visible_holes` is what sees that, and this is its counterpart
 * for the cases where the solid really does move.
 *
 * So this one samples the whole polygon, and the band along its edges most
 * densely, because that is where a brush meets its neighbour. It probes at
 * several depths, because a seam that is a hair wide at the surface opens up
 * behind it, and at several offsets, because the compiler is allowed to move a
 * shared edge slightly and a probe exactly on the line would be answering about
 * rounding rather than about a hole.
 *
 * Defects are then clustered, because one slit produces thousands of points and
 * what a person needs is where it is and how big it is.
 *
 *     mapgen_seam_audit <donor.bsp> <candidate.bsp> [step] [--dump file]
 *
 * Exit 0 when the candidate keeps every wall the donor had, 1 when it does not.
 */

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_trace.h"

#define MAX_POLY     128
#define MAX_DEFECTS  400000
/* How far apart two lost points may be and still be one hole. Larger than the
   sampling step, so a strip stays a strip instead of a thousand specks. */
#define CLUSTER_REACH 24.0f

typedef struct {
    float mins[3];
    float maxs[3];
    uint32_t count;
} cluster_t;

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

/* ---- the probe ----------------------------------------------------------- */

static mapgen_trace_context_t g_donor, g_cand;
static float (*g_lost)[3];
static uint32_t g_num_lost;
static uint32_t g_checked;
static float (*g_extra)[3];
static uint32_t g_num_extra;
static uint32_t g_checked_air;

/*
 * One point on a surface: is the solid that used to be behind it still there?
 *
 * At three depths. A seam is a wedge - two planes that no longer meet part
 * company gradually - so one unit in can still be solid where four units in is
 * open sky, and it is the four that a player sees through.
 */
static void probe(const double p[3], const float into[3])
{
    static const float depths[3] = { 1.0f, 4.0f, 12.0f };
    for (int d = 0; d < 3; d++) {
        float at[3];
        for (int a = 0; a < 3; a++)
            at[a] = (float)p[a] + into[a] * depths[d];
        if (!(MapGenTrace_PointContents(&g_donor, at) & MAPGEN_TRACE_SOLID))
            continue;               /* the donor has no wall here to lose */
        g_checked++;
        if (MapGenTrace_PointContents(&g_cand, at) & MAPGEN_TRACE_SOLID)
            continue;
        if (g_num_lost < MAX_DEFECTS)
            memcpy(g_lost[g_num_lost], at, sizeof(g_lost[0]));
        g_num_lost++;
        return;                     /* one report per point, deepest wins */
    }
}

/*
 * And the other direction: has a brush GROWN into the air in front of a wall?
 *
 * Asking only "is the donor's solid still there" misses this entirely, and it
 * is not a harmless miss. A brush that comes back a few units too big buries
 * the wall beside it, the compiler stops drawing the buried strip, and the
 * player sees straight past the corner - which is one of the gaps left on
 * q2dm1 after the writer was fixed: the wall at 864 913 is drawn from 866 915
 * because its neighbour arrived three and a half units long.
 *
 * A stricter tolerance than the loss probe on purpose. The donor's own surface
 * sits at zero, so a sample must clear it before extra solid means anything.
 */
static void probe_extra(const double p[3], const float out_dir[3])
{
    static const float heights[3] = { 2.0f, 6.0f, 16.0f };
    for (int d = 0; d < 3; d++) {
        float at[3];
        for (int a = 0; a < 3; a++)
            at[a] = (float)p[a] + out_dir[a] * heights[d];
        if (MapGenTrace_PointContents(&g_donor, at) & MAPGEN_TRACE_SOLID)
            continue;               /* the donor is solid here too - not new */
        g_checked_air++;
        if (!(MapGenTrace_PointContents(&g_cand, at) & MAPGEN_TRACE_SOLID))
            continue;
        if (g_num_extra < MAX_DEFECTS)
            memcpy(g_extra[g_num_extra], at, sizeof(g_extra[0]));
        g_num_extra++;
        return;
    }
}

/* ---- clustering ---------------------------------------------------------- */

static int by_size(const void *a, const void *b)
{
    const cluster_t *x = a, *y = b;
    if (x->count != y->count)
        return x->count > y->count ? -1 : 1;
    return 0;
}

static bool near_cluster(const cluster_t *c, const float p[3])
{
    for (int a = 0; a < 3; a++)
        if (p[a] < c->mins[a] - CLUSTER_REACH || p[a] > c->maxs[a] + CLUSTER_REACH)
            return false;
    return true;
}

/*
 * A set of defect points, clustered and named.
 *
 * One slit produces thousands of samples and what a person needs is where it
 * is and how big it is, so they are merged by proximity and the largest are
 * printed. Shared by both directions - solid the rebuild lost, and solid it
 * grew where the donor had air - because a defect is a defect either way and
 * only asking one of the two questions is how the wall at 864 913 stayed
 * buried while every audit reported the map intact.
 */
static void report(const char *what, float (*points)[3], uint32_t count,
                   const char *dump_path)
{
    const uint32_t kept = count < MAX_DEFECTS ? count : MAX_DEFECTS;
    cluster_t *clusters = calloc(kept ? kept : 1, sizeof(*clusters));
    if (!clusters)
        return;
    uint32_t num_clusters = 0;
    for (uint32_t i = 0; i < kept; i++) {
        uint32_t at = num_clusters;
        for (uint32_t c = 0; c < num_clusters; c++)
            if (near_cluster(&clusters[c], points[i])) {
                at = c;
                break;
            }
        if (at == num_clusters) {
            for (int a = 0; a < 3; a++)
                clusters[at].mins[a] = clusters[at].maxs[a] = points[i][a];
            clusters[at].count = 0;
            num_clusters++;
        }
        for (int a = 0; a < 3; a++) {
            if (points[i][a] < clusters[at].mins[a])
                clusters[at].mins[a] = points[i][a];
            if (points[i][a] > clusters[at].maxs[a])
                clusters[at].maxs[a] = points[i][a];
        }
        clusters[at].count++;
    }
    qsort(clusters, num_clusters, sizeof(*clusters), by_size);

    printf("the candidate has %s %u of them, in %u places\n",
           what, count, num_clusters);
    const uint32_t show = num_clusters < 20 ? num_clusters : 20;
    for (uint32_t c = 0; c < show; c++) {
        const cluster_t *k = &clusters[c];
        printf("  %6u points  %8.0f %8.0f %8.0f .. %8.0f %8.0f %8.0f"
               "   (%.0f x %.0f x %.0f)\n", k->count,
               (double)k->mins[0], (double)k->mins[1], (double)k->mins[2],
               (double)k->maxs[0], (double)k->maxs[1], (double)k->maxs[2],
               (double)(k->maxs[0] - k->mins[0]),
               (double)(k->maxs[1] - k->mins[1]),
               (double)(k->maxs[2] - k->mins[2]));
    }
    if (num_clusters > show)
        printf("  ... and %u more\n", num_clusters - show);

    if (dump_path) {
        FILE *d = fopen(dump_path, "wb");
        if (d) {
            for (uint32_t i = 0; i < kept; i++)
                fprintf(d, "%.2f %.2f %.2f\n", (double)points[i][0],
                        (double)points[i][1], (double)points[i][2]);
            fclose(d);
        }
    }
    free(clusters);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <donor.bsp> <candidate.bsp> [step]"
                        " [--dump file]\n", argv[0]);
        return 2;
    }
    const double step = argc > 3 && argv[3][0] != '-' ? strtod(argv[3], NULL)
                                                      : 4.0;
    const char *dump_path = NULL;
    for (int i = 3; i + 1 < argc; i++)
        if (!strcmp(argv[i], "--dump"))
            dump_path = argv[i + 1];

    mapgen_bsp_t *donor = load(argv[1]);
    mapgen_bsp_t *cand = load(argv[2]);
    if (!donor || !cand) {
        fprintf(stderr, "cannot read one of them\n");
        return 2;
    }
    g_lost = calloc(MAX_DEFECTS, sizeof(*g_lost));
    g_extra = calloc(MAX_DEFECTS, sizeof(*g_extra));
    if (!g_lost || !g_extra)
        return 2;

    memset(&g_donor, 0, sizeof(g_donor));
    memset(&g_cand, 0, sizeof(g_cand));
    MapGenTrace_Bind(&g_donor, donor);
    MapGenTrace_Bind(&g_cand, cand);

    const uint32_t faces = MapGenBsp_NumFaces(donor);
    uint32_t sampled_faces = 0;

    for (uint32_t f = 0; f < faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(donor, f);
        if (face->numedges < 3 || face->numedges > MAX_POLY)
            continue;
        const mapgen_bsp_plane_t *plane = MapGenBsp_Plane(donor, face->planenum);
        const float sign = face->side ? 1.0f : -1.0f;
        /*
         * `normal` is the face's own outward-facing plane normal and is what
         * the sampling basis and the plane's origin are built from; `into`
         * points at the solid behind the face and `out_dir` at the air in
         * front. Deriving the basis from a negated normal mirrors every body
         * sample through the origin, which is a silent way to sample nothing.
         */
        float into[3], normal[3], out_dir[3];
        for (int a = 0; a < 3; a++) {
            normal[a] = plane->normal[a] * sign;
            into[a] = normal[a];
            out_dir[a] = -normal[a];
        }

        double poly[MAX_POLY][3];
        const int n = face->numedges;
        for (int e = 0; e < n; e++) {
            const int32_t se =
                MapGenBsp_SurfEdge(donor, (uint32_t)(face->firstedge + e));
            const mapgen_bsp_edge_t *edge =
                MapGenBsp_Edge(donor, (uint32_t)(se < 0 ? -se : se));
            const mapgen_bsp_vertex_t *v =
                MapGenBsp_Vertex(donor, se < 0 ? edge->v[1] : edge->v[0]);
            for (int a = 0; a < 3; a++)
                poly[e][a] = v->point[a];
        }
        sampled_faces++;

        double centre[3] = { 0, 0, 0 };
        for (int e = 0; e < n; e++)
            for (int a = 0; a < 3; a++)
                centre[a] += poly[e][a] / n;

        /*
         * The band along the edges, first and finest.
         *
         * This is where one brush hands the surface over to the next, so this
         * is where a seam is. The samples are pulled INWARD from the edge by a
         * few different amounts: a point exactly on the line answers about
         * where the compiler put a shared edge, which it is allowed to move,
         * and the question here is whether there is a hole behind it.
         */
        static const double insets[3] = { 0.5, 2.0, 6.0 };
        for (int e = 0; e < n; e++) {
            const double *a0 = poly[e];
            const double *a1 = poly[(e + 1) % n];
            double along[3], len = 0.0;
            for (int a = 0; a < 3; a++) {
                along[a] = a1[a] - a0[a];
                len += along[a] * along[a];
            }
            len = sqrt(len);
            if (len < 1.0)
                continue;
            const int steps = (int)(len / 2.0) + 1;
            for (int s = 0; s <= steps; s++) {
                const double t = (double)s / steps;
                double on[3];
                for (int a = 0; a < 3; a++)
                    on[a] = a0[a] + along[a] * t;
                for (int i = 0; i < 3; i++) {
                    /* toward the middle of the face, so the sample stays on it */
                    double in[3];
                    double d = 0.0;
                    for (int a = 0; a < 3; a++)
                        d += (centre[a] - on[a]) * (centre[a] - on[a]);
                    d = sqrt(d);
                    if (d < insets[i] * 1.5)
                        continue;
                    for (int a = 0; a < 3; a++)
                        in[a] = on[a] + (centre[a] - on[a]) / d * insets[i];
                    probe(in, into);
                    probe_extra(in, out_dir);
                }
            }
        }

        /* And the body of the face, coarsely, so nothing large is missed. */
        {
            int minor = 0;
            for (int a = 1; a < 3; a++)
                if (fabsf(normal[a]) < fabsf(normal[minor]))
                    minor = a;
            double t[3] = { 0, 0, 0 };
            t[minor] = 1.0;
            double u[3], v[3], d = 0.0;
            for (int a = 0; a < 3; a++)
                d += t[a] * normal[a];
            double ulen = 0.0;
            for (int a = 0; a < 3; a++) {
                u[a] = t[a] - normal[a] * d;
                ulen += u[a] * u[a];
            }
            ulen = sqrt(ulen);
            for (int a = 0; a < 3; a++)
                u[a] /= ulen;
            v[0] = normal[1] * u[2] - normal[2] * u[1];
            v[1] = normal[2] * u[0] - normal[0] * u[2];
            v[2] = normal[0] * u[1] - normal[1] * u[0];

            double su[MAX_POLY], sv[MAX_POLY];
            double lo_u = 1e30, hi_u = -1e30, lo_v = 1e30, hi_v = -1e30;
            for (int e = 0; e < n; e++) {
                su[e] = sv[e] = 0.0;
                for (int a = 0; a < 3; a++) {
                    su[e] += poly[e][a] * u[a];
                    sv[e] += poly[e][a] * v[a];
                }
                if (su[e] < lo_u) lo_u = su[e];
                if (su[e] > hi_u) hi_u = su[e];
                if (sv[e] < lo_v) lo_v = sv[e];
                if (sv[e] > hi_v) hi_v = sv[e];
            }
            const double origin[3] = { normal[0] * plane->dist * sign,
                                       normal[1] * plane->dist * sign,
                                       normal[2] * plane->dist * sign };
            for (double a = lo_u + step * 0.5; a < hi_u; a += step) {
                for (double b = lo_v + step * 0.5; b < hi_v; b += step) {
                    /* crossing number, on the projection */
                    bool in = false;
                    for (int e = 0, j = n - 1; e < n; j = e++)
                        if ((sv[e] > b) != (sv[j] > b)
                            && a < (su[j] - su[e]) * (b - sv[e])
                                       / (sv[j] - sv[e]) + su[e])
                            in = !in;
                    if (!in)
                        continue;
                    double p[3];
                    for (int c = 0; c < 3; c++)
                        p[c] = origin[c] + u[c] * a + v[c] * b;
                    probe(p, into);
                    probe_extra(p, out_dir);
                }
            }
        }
    }

    /* ---- what was found -------------------------------------------------- */

    printf("probed %u points behind and %u in front of %u of the donor's"
           " surfaces\n", g_checked, g_checked_air, sampled_faces);
    report("lost the solid behind", g_lost, g_num_lost, dump_path);
    report("grown solid in front of", g_extra, g_num_extra, NULL);

    free(g_extra);
    free(g_lost);
    MapGenTrace_Release(&g_donor);
    MapGenTrace_Release(&g_cand);
    MapGenBsp_Free(donor);
    MapGenBsp_Free(cand);
    return (g_num_lost || g_num_extra) ? 1 : 0;
}
