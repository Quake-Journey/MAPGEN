/*
 * The SHAPE of a map's open air - which is what "an arena" means and what
 * "how much sky" never measured.
 *
 *     mapgen_arena_shape <map.bsp>
 *
 * Three rounds of work went into the invented map and the PO said the same
 * thing after each: a box. The first measure asked whether there was sky
 * straight up, and a shaft with a lid passed it. The second asked how much of
 * the sky a player owns from where he stands, and a yard with low walls
 * passed that. Both are properties of the LID. What he is looking at is the
 * shape of the space under it, so that is what this measures:
 *
 *   VOLUMES    outdoor standing places grouped into open volumes - two places
 *              belong to one volume when a horizontal ray at eye height joins
 *              them, transitively. q2dm1 has two; a map of separate yards has
 *              one per yard however open each is.
 *   INSIDE     within the biggest volume, the spread of the floor heights and
 *              how many storeys hold a twentieth of it each. q2dm1's courtyard
 *              has ledges, walkways and a bridge standing IN the air: four
 *              storeys over 592 units. Three flat yards at different heights
 *              are not that, and this is the number that tells them apart.
 *   WALLS      how many distinct wall planes the horizontal rays from that
 *              volume's places meet. A brick box has four; q2dm1's courtyard
 *              has fifty-nine - the curve, the windows, the buttresses, the
 *              fronts of the ledges.
 *   LAMPS      light fittings, and how many share a ceiling plane with the
 *              sky - reported rather than judged, see the note on the
 *              function itself.
 *   FLATNESS   the share of the whole map's standing places on its single
 *              biggest storey.
 *
 * Every line is `key value`, so a guard can read it and a person can too.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_trace.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define GRID        64.0f
#define SURF_LIGHT  0x1
#define SURF_SKY    0x4
#define MAX_STANDS  60000
#define NUM_AZ      16
#define REACH       8192.0f
#define STOREY      96.0f
#define MAX_PLANES  8192
#define JOIN_REACH  2048.0f

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = malloc((size_t)(n > 0 ? n : 1));
    if (!raw || n <= 0 || fread(raw, 1, (size_t)n, f) != (size_t)n) {
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

/* 0 solid, 1 sky, 2 nothing. */
static int shoot(mapgen_trace_context_t *ctx, const float from[3],
                 const float dir[3], mapgen_trace_result_t *hit)
{
    const float to[3] = { from[0] + dir[0] * REACH, from[1] + dir[1] * REACH,
                          from[2] + dir[2] * REACH };
    const float zero[3] = { 0, 0, 0 };
    MapGenTrace_Box(ctx, from, to, zero, zero, MAPGEN_TRACE_SOLID, hit);
    if (hit->fraction >= 0.999f)
        return 2;
    return (hit->surface_flags & SURF_SKY) ? 1 : 0;
}

static float px[MAX_STANDS], py[MAX_STANDS], pz[MAX_STANDS];
static uint8_t is_outdoor[MAX_STANDS];
static int owner[MAX_STANDS];
static uint32_t stands;

static int find(int i)
{
    while (owner[i] != i)
        i = owner[i] = owner[owner[i]];
    return i;
}

/* One face's corners. */
static uint32_t face_points(const mapgen_bsp_t *bsp,
                            const mapgen_bsp_face_t *face, float out[64][3])
{
    uint32_t n = 0;
    for (int32_t e = 0; e < face->numedges && n < 64; e++) {
        const int32_t se =
            MapGenBsp_SurfEdge(bsp, (uint32_t)(face->firstedge + e));
        const mapgen_bsp_edge_t *edge =
            MapGenBsp_Edge(bsp, (uint32_t)(se < 0 ? -se : se));
        if (!edge)
            break;
        const mapgen_bsp_vertex_t *v =
            MapGenBsp_Vertex(bsp, se < 0 ? edge->v[1] : edge->v[0]);
        if (!v)
            break;
        memcpy(out[n++], v->point, sizeof(out[0]));
    }
    return n;
}

/*
 * Light fittings, and how many of them share a ceiling plane with the sky.
 *
 * REPORTED, not judged, and the reason is worth writing down. The PO
 * photographed lamps hanging in the blue in the invented map on 2026-09-07,
 * and the geometry behind that is exact: its outdoor ceilings carry sky faces
 * at z 528 and light faces at 544, so the recess is cut into the slab whose
 * underside was painted sky and you see the fitting through the sky.
 *
 * Every way of asking a compiled map "is this fitting in the sky" that was
 * tried here also fires on hand-built maps: q2dm2 and q2dm3 share planes
 * between sky and lights, and every map with an open room has lamps with sky
 * somewhere above them. A number that condemns the references is not a gate.
 * So the DEFECT is held at its source - a light recess is not cut into a
 * ceiling that is painted sky - and this line is the diagnostic that says how
 * near the two are to each other.
 */
static uint32_t lamps_sharing_sky_plane(const mapgen_bsp_t *bsp,
                                        uint32_t *out_total)
{
    const uint32_t faces = MapGenBsp_NumFaces(bsp);
    uint32_t total = 0, shared = 0;

    float sky_z[512];
    uint32_t num_sky = 0;
    for (uint32_t f = 0; f < faces && num_sky < 512; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        if (!face || face->numedges < 3)
            continue;
        const mapgen_bsp_texinfo_t *tex =
            MapGenBsp_TexInfo(bsp, (uint32_t)face->texinfo);
        if (!tex || !(tex->flags & SURF_SKY))
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, face->planenum);
        if (!pl || fabsf(pl->normal[2]) < 0.7f)
            continue;
        float p[64][3];
        if (face_points(bsp, face, p) < 3)
            continue;
        bool seen = false;
        for (uint32_t k = 0; k < num_sky && !seen; k++)
            seen = fabsf(sky_z[k] - p[0][2]) <= 24.0f;
        if (!seen)
            sky_z[num_sky++] = p[0][2];
    }

    for (uint32_t f = 0; f < faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        if (!face || face->numedges < 3)
            continue;
        const mapgen_bsp_texinfo_t *tex =
            MapGenBsp_TexInfo(bsp, (uint32_t)face->texinfo);
        if (!tex || !(tex->flags & SURF_LIGHT) || tex->value <= 0)
            continue;
        if (tex->flags & SURF_SKY)
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, face->planenum);
        if (!pl || fabsf(pl->normal[2]) < 0.7f)
            continue;
        float p[64][3];
        if (face_points(bsp, face, p) < 3)
            continue;
        total++;
        for (uint32_t k = 0; k < num_sky; k++)
            if (fabsf(sky_z[k] - p[0][2]) <= 24.0f) {
                shared++;
                break;
            }
    }
    if (out_total)
        *out_total = total;
    return shared;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp>\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (!MapGenTrace_Bind(&ctx, bsp))
        return 2;

    printf("footprint %.0f %.0f %.0f\n", world->maxs[0] - world->mins[0],
           world->maxs[1] - world->mins[1], world->maxs[2] - world->mins[2]);

    /* --- standing places, and which of them are outdoors ---------------- */
    static const float EL[4] = { 0, 15, 30, 45 };
    for (float x = world->mins[0] + GRID * 0.5f; x < world->maxs[0]; x += GRID) {
      for (float y = world->mins[1] + GRID * 0.5f; y < world->maxs[1]; y += GRID) {
        for (float z = world->mins[2] + 8.0f; z < world->maxs[2]; z += 8.0f) {
            const float here[3] = { x, y, z };
            const float below[3] = { x, y, z - 8.0f };
            const float head[3] = { x, y, z + 48.0f };
            if (MapGenBsp_PointContents(bsp, here) & 1)
                continue;
            if (!(MapGenBsp_PointContents(bsp, below) & 1))
                continue;
            if (MapGenBsp_PointContents(bsp, head) & 1)
                continue;
            if (stands >= MAX_STANDS)
                break;
            const float eye[3] = { x, y, z + 40.0f };
            bool out = false;
            for (int e = 0; e < 4 && !out; e++) {
                const float el = EL[e] * (float)M_PI / 180.0f;
                int sky = 0;
                for (int a = 0; a < NUM_AZ; a++) {
                    const float az = (float)a * 2.0f * (float)M_PI / NUM_AZ;
                    const float dir[3] = { cosf(az) * cosf(el),
                                           sinf(az) * cosf(el), sinf(el) };
                    mapgen_trace_result_t hit;
                    if (shoot(&ctx, eye, dir, &hit) == 1)
                        sky++;
                }
                if (sky * 2 >= NUM_AZ)
                    out = true;
            }
            px[stands] = x;
            py[stands] = y;
            pz[stands] = z;
            is_outdoor[stands] = out;
            owner[stands] = (int)stands;
            stands++;
            z += GRID;
        }
      }
    }
    printf("standing places %u\n", stands);

    /* --- the flattest thing about the whole map ------------------------- */
    {
        float levels[128];
        uint32_t count[128], num = 0, biggest = 0;
        for (uint32_t i = 0; i < stands; i++) {
            bool placed = false;
            for (uint32_t l = 0; l < num && !placed; l++)
                if (fabsf(levels[l] - pz[i]) <= STOREY) {
                    count[l]++;
                    placed = true;
                }
            if (!placed && num < 128) {
                levels[num] = pz[i];
                count[num] = 1;
                num++;
            }
        }
        for (uint32_t l = 0; l < num; l++)
            if (count[l] > biggest)
                biggest = count[l];
        printf("biggest storey %llu permille\n",
               stands ? (unsigned long long)(1000ull * biggest / stands) : 0ull);
    }

    /* --- outdoor places joined into volumes ----------------------------- */
    for (uint32_t i = 0; i < stands; i++) {
        if (!is_outdoor[i])
            continue;
        const float eye[3] = { px[i], py[i], pz[i] + 40.0f };
        for (uint32_t j = i + 1; j < stands; j++) {
            if (!is_outdoor[j] || find((int)i) == find((int)j))
                continue;
            const float d[3] = { px[j] - px[i], py[j] - py[i],
                                 (pz[j] + 40.0f) - eye[2] };
            if (sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) > JOIN_REACH)
                continue;
            const float to[3] = { px[j], py[j], pz[j] + 40.0f };
            const float zero[3] = { 0, 0, 0 };
            mapgen_trace_result_t hit;
            MapGenTrace_Box(&ctx, eye, to, zero, zero, MAPGEN_TRACE_SOLID, &hit);
            if (hit.fraction >= 0.999f)
                owner[find((int)i)] = find((int)j);
        }
    }

    /* --- and what each volume is --------------------------------------- */
    static float pn[MAX_PLANES][3];
    uint32_t volumes = 0, best_places = 0;
    float best_w = 0, best_d = 0, best_spread = 0;
    uint32_t best_storeys = 0, best_planes = 0;
    for (uint32_t r = 0; r < stands; r++) {
        if (!is_outdoor[r] || find((int)r) != (int)r)
            continue;
        uint32_t n = 0, np = 0;
        float lo = 1e9f, hi = -1e9f;
        float minx = 1e9f, maxx = -1e9f, miny = 1e9f, maxy = -1e9f;
        float levels[64];
        uint32_t count[64], num = 0;
        for (uint32_t i = 0; i < stands; i++) {
            if (!is_outdoor[i] || find((int)i) != (int)r)
                continue;
            n++;
            if (pz[i] < lo) lo = pz[i];
            if (pz[i] > hi) hi = pz[i];
            if (px[i] < minx) minx = px[i];
            if (px[i] > maxx) maxx = px[i];
            if (py[i] < miny) miny = py[i];
            if (py[i] > maxy) maxy = py[i];
            bool placed = false;
            for (uint32_t l = 0; l < num && !placed; l++)
                if (fabsf(levels[l] - pz[i]) <= STOREY) {
                    count[l]++;
                    placed = true;
                }
            if (!placed && num < 64) {
                levels[num] = pz[i];
                count[num] = 1;
                num++;
            }
            const float eye[3] = { px[i], py[i], pz[i] + 40.0f };
            for (int a = 0; a < NUM_AZ; a++) {
                const float az = (float)a * 2.0f * (float)M_PI / NUM_AZ;
                const float dir[3] = { cosf(az), sinf(az), 0.0f };
                mapgen_trace_result_t hit;
                if (shoot(&ctx, eye, dir, &hit) != 0 || !hit.hit_plane)
                    continue;
                if (fabsf(hit.plane_normal[2]) > 0.5f)
                    continue;
                const float q0 = roundf(hit.plane_normal[0] * 64.0f) / 64.0f;
                const float q1 = roundf(hit.plane_normal[1] * 64.0f) / 64.0f;
                const float qd = roundf(hit.plane_dist / 4.0f) * 4.0f;
                bool seen = false;
                for (uint32_t k = 0; k < np && !seen; k++)
                    seen = pn[k][0] == q0 && pn[k][1] == q1 && pn[k][2] == qd;
                if (!seen && np < MAX_PLANES) {
                    pn[np][0] = q0;
                    pn[np][1] = q1;
                    pn[np][2] = qd;
                    np++;
                }
            }
        }
        if (n < 20)
            continue;
        volumes++;
        uint32_t storeys = 0;
        for (uint32_t l = 0; l < num; l++)
            if (count[l] * 20u >= n)
                storeys++;
        printf("volume places %u size %.0f %.0f floors %.0f %.0f spread %.0f"
               " storeys %u planes %u\n", n, maxx - minx + GRID,
               maxy - miny + GRID, lo, hi, hi - lo, storeys, np);
        if (n > best_places) {
            best_places = n;
            best_w = maxx - minx + GRID;
            best_d = maxy - miny + GRID;
            best_spread = hi - lo;
            best_storeys = storeys;
            best_planes = np;
        }
    }
    printf("volumes %u\n", volumes);
    printf("main places %u size %.0f %.0f spread %.0f storeys %u planes %u\n",
           best_places, best_w, best_d, best_spread, best_storeys, best_planes);

    uint32_t total = 0;
    const uint32_t shared = lamps_sharing_sky_plane(bsp, &total);
    printf("lamps %u sharing a sky plane %u\n", total, shared);

    MapGenTrace_Release(&ctx);
    MapGenBsp_Free(bsp);
    return 0;
}
