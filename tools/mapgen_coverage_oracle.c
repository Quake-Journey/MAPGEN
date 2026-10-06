/*
 * Is every bit of wall the donor draws still drawn by the candidate?
 *
 * The area comparison says a surface came back four per cent smaller. It
 * cannot say whether that four per cent is a strip of sky down the middle of a
 * wall or a rounding difference spread along its edge, and only one of those is
 * a defect. This asks the question a viewer asks, without a viewer: walk the
 * donor's own surfaces, and for each point ask whether the candidate still has
 * geometry there.
 *
 * Deliberately not a camera. A camera answers "is it visible from where I
 * stood", which makes acceptance a search; a surface either has geometry on it
 * or does not, everywhere, and that is decidable.
 *
 * Everything here works on TRIANGLES, both to generate the sample points and
 * to test them. A compiled winding is convex in principle and not always in
 * practice - one rebuilt wall came back as ...(1635,1024) (1634.8,1024)
 * (1635,1024)..., a hairline spike with a repeated vertex - and an edge-sign
 * test on that face calls every interior point of it outside. It reported
 * three thousand square units of missing wall on a wall that was there. A fan
 * about the first vertex does not care.
 *
 *     mapgen_coverage_oracle <donor.bsp> <candidate.bsp> [step] [tolerance]
 *
 * Exit code 0 when every sampled point is still covered, 1 when a run of them
 * is not - and it names the surface and where to stand to see it.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

/* Sky is drawn by the sky, and a candidate is not obliged to put a surface
   where the donor put nothing to look at. */
#define SURF_SKY_BIT     0x0004
#define SURF_NODRAW_BIT  0x0080
#define SURF_HINT_BIT    0x0100
#define SURF_SKIP_BIT    0x0200
#define SURF_IGNORED  (SURF_SKY_BIT | SURF_NODRAW_BIT | SURF_HINT_BIT \
                       | SURF_SKIP_BIT)

/* A hole smaller than this is an edge, not a slit. */
#define HOLE_MIN_AREA 64.0

static mapgen_geometry_t *load(const char *path)
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
    mapgen_geometry_t *g = NULL;
    if (MapGenBsp_Load(raw, (size_t)n, &bsp) == MAPGEN_BSP_OK)
        MapGenGeometry_FromBsp(bsp, &g);
    free(raw);
    MapGenBsp_Free(bsp);
    return g;
}

/*
 * Does this face have geometry at the point, allowing `margin` units of slack
 * outside its edges? Tested as a fan of triangles about the first vertex, in
 * barycentric coordinates, with the slack converted into each triangle's own
 * scale.
 */
static bool face_covers(const mapgen_geometry_t *g,
                        const mapgen_geometry_face_t *face,
                        const float p[3], float margin)
{
    const float *p0 = MapGenGeometry_FacePoint(g, face->first_point);
    if (!p0)
        return false;

    for (uint32_t i = 1; i + 1 < face->num_points; i++) {
        const float *a = MapGenGeometry_FacePoint(g, face->first_point + i);
        const float *b = MapGenGeometry_FacePoint(g, face->first_point + i + 1);
        float u[3], v[3], w[3];
        for (int k = 0; k < 3; k++) {
            u[k] = a[k] - p0[k];
            v[k] = b[k] - p0[k];
            w[k] = p[k] - p0[k];
        }
        const float uu = u[0] * u[0] + u[1] * u[1] + u[2] * u[2];
        const float uv = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
        const float vv = v[0] * v[0] + v[1] * v[1] + v[2] * v[2];
        const float det = uu * vv - uv * uv;
        if (det <= 1e-6f)
            continue;               /* a degenerate sliver covers nothing */

        const float wu = w[0] * u[0] + w[1] * u[1] + w[2] * u[2];
        const float wv = w[0] * v[0] + w[1] * v[1] + w[2] * v[2];
        const float s = (wu * vv - wv * uv) / det;
        const float t = (wv * uu - wu * uv) / det;

        /* The slack, expressed in this triangle's own barycentric scale. */
        const float su = margin / (sqrtf(uu) + 1e-6f);
        const float sv = margin / (sqrtf(vv) + 1e-6f);
        if (s >= -su && t >= -sv && s + t <= 1.0f + su + sv)
            return true;
    }
    return false;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <donor.bsp> <candidate.bsp>"
                        " [step] [tolerance]\n", argv[0]);
        return 2;
    }
    const float step = argc > 3 ? strtof(argv[3], NULL) : 8.0f;
    const float tolerance = argc > 4 ? strtof(argv[4], NULL) : 2.0f;

    mapgen_geometry_t *donor = load(argv[1]);
    mapgen_geometry_t *cand = load(argv[2]);
    if (!donor || !cand) {
        fprintf(stderr, "cannot read one of them\n");
        return 2;
    }

    const uint32_t dfaces = MapGenGeometry_NumFaces(donor);
    const uint32_t cfaces = MapGenGeometry_NumFaces(cand);
    uint64_t sampled = 0, uncovered = 0;
    double worst_hole = 0.0;
    float worst_at[3] = { 0, 0, 0 };
    char worst_texture[MAPGEN_BSP_TEXNAME + 1] = "";
    mapgen_geometry_face_t worst_face;
    memset(&worst_face, 0, sizeof(worst_face));

    for (uint32_t f = 0; f < dfaces; f++) {
        const mapgen_geometry_face_t *face = MapGenGeometry_Face(donor, f);
        if ((face->flags & SURF_IGNORED) || face->num_points < 3)
            continue;

        const float *p0 = MapGenGeometry_FacePoint(donor, face->first_point);
        uint64_t face_missing = 0;

        /*
         * The samples come from the donor's own triangles rather than from a
         * grid over its bounding box, so every one of them is inside the face
         * by construction and no edge test is needed to keep them there.
         */
        for (uint32_t i = 1; i + 1 < face->num_points; i++) {
            const float *a = MapGenGeometry_FacePoint(donor,
                                                      face->first_point + i);
            const float *b = MapGenGeometry_FacePoint(donor,
                                                      face->first_point + i + 1);
            float u[3], v[3];
            for (int k = 0; k < 3; k++) {
                u[k] = a[k] - p0[k];
                v[k] = b[k] - p0[k];
            }
            const float ulen = sqrtf(u[0] * u[0] + u[1] * u[1] + u[2] * u[2]);
            const float vlen = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
            if (ulen < step || vlen < step)
                continue;

            const uint32_t nu = (uint32_t)(ulen / step) + 1;
            const uint32_t nv = (uint32_t)(vlen / step) + 1;
            for (uint32_t iu = 0; iu <= nu; iu++) {
                for (uint32_t iv = 0; iv <= nv; iv++) {
                    const float s = (float)iu / nu;
                    const float t = (float)iv / nv;
                    if (s + t > 1.0f)
                        continue;
                    float p[3];
                    for (int k = 0; k < 3; k++)
                        p[k] = p0[k] + u[k] * s + v[k] * t;
                    sampled++;

                    bool covered = false;
                    for (uint32_t c = 0; c < cfaces && !covered; c++) {
                        const mapgen_geometry_face_t *other =
                            MapGenGeometry_Face(cand, c);
                        if (other->flags & SURF_NODRAW_BIT)
                            continue;
                        if (other->normal[0] * face->normal[0]
                            + other->normal[1] * face->normal[1]
                            + other->normal[2] * face->normal[2] < 0.98f)
                            continue;
                        const float off = other->normal[0] * p[0]
                                        + other->normal[1] * p[1]
                                        + other->normal[2] * p[2] - other->dist;
                        if (fabsf(off) > tolerance)
                            continue;
                        covered = face_covers(cand, other, p, step);
                    }
                    if (covered)
                        continue;

                    uncovered++;
                    face_missing++;
                    if (getenv("MAPGEN_COVERAGE_DUMP") && uncovered < 24) {
                        printf("    uncovered %8.2f %8.2f %8.2f on %s\n",
                               (double)p[0], (double)p[1], (double)p[2],
                               face->texture);
                    }
                    if ((double)face_missing * step * step > worst_hole) {
                        worst_hole = (double)face_missing * step * step;
                        memcpy(worst_at, p, sizeof(worst_at));
                        memcpy(worst_texture, face->texture,
                               sizeof(worst_texture));
                        worst_face = *face;
                    }
                }
            }
        }
    }

    printf("%s vs %s: %llu points sampled on the donor's surfaces at %.0f"
           " units, %llu no longer covered\n",
           argv[1], argv[2], (unsigned long long)sampled, (double)step,
           (unsigned long long)uncovered);
    if (uncovered) {
        printf("  largest hole about %.0f square units on %s, near %.0f %.0f"
               " %.0f\n", worst_hole, worst_texture, (double)worst_at[0],
               (double)worst_at[1], (double)worst_at[2]);
        printf("  that surface: normal %.4f %.4f %.4f dist %.3f, area %.0f\n",
               (double)worst_face.normal[0], (double)worst_face.normal[1],
               (double)worst_face.normal[2], (double)worst_face.dist,
               (double)worst_face.area);
    }

    MapGenGeometry_Free(donor);
    MapGenGeometry_Free(cand);
    return worst_hole >= HOLE_MIN_AREA ? 1 : 0;
}
