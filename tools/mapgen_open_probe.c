/*
 * How open does a map FEEL from where a player stands?
 *
 *     mapgen_open_probe <map.bsp>
 *
 * `mapgen_arena_probe` asks whether there is sky straight up. A shaft with a
 * sky lid passes that, and the map the PO walked on 2026-09-07 did: 411
 * permille of its floor has sky overhead and he called it "running in a box
 * whose lid was opened a crack". So this asks the question he was actually
 * asking, from the same standing places the arena probe uses:
 *
 *   HORIZON     for each standing place, the lowest elevation at which at
 *               least half the compass reaches sky. That is the angle of the
 *               lid as seen from where you stand: zero means the parapet is
 *               at eye level and you are OUTSIDE; seventy-five means you are
 *               at the bottom of a well. On q2dm1's top storey it is zero.
 *   ELEVATIONS  the share of all (place, azimuth) rays that reach sky at each
 *               elevation, so "how much sky do I own" is a curve rather than
 *               one number.
 *   HEIGHT      where the sky IS straight up, how far above the eye - a lid a
 *               thousand units up is a different place from a parapet two
 *               hundred up, and both are "under sky".
 *   STOREYS     how many distinct floor heights have places that are outdoors
 *               by the horizon test, because one outdoor floor at the bottom
 *               of a courtyard is a pit and four of them is an arena.
 *   SIGHTLINE   how far a ray at eye height travels before it hits solid.
 *               Reported and NOT judged: the invented map's sightlines are
 *               longer than q2dm1's and it still reads as a box. Space is not
 *               distance to the next wall.
 *
 * Written for the assignment of 2026-09-07 evening, whose prototype this is
 * lifted from, and the numbers it prints for q2dm1 are the reference the
 * openness guard holds an invented map to.
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
#define SURF_SKY    0x4
#define MAX_STANDS  200000
#define NUM_AZ      16
#define NUM_EL      7
#define REACH       16384.0f
#define STOREY      96.0f

static const float EL[NUM_EL] = { 0, 10, 20, 30, 45, 60, 75 };

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

static int cmpf(const void *a, const void *b)
{
    const float x = *(const float *)a, y = *(const float *)b;
    return x < y ? -1 : x > y;
}

/* 0 = solid, 1 = sky, 2 = nothing at all (a leak, counted and reported). */
static int shoot(mapgen_trace_context_t *ctx, const float from[3],
                 const float dir[3], float *dist)
{
    const float to[3] = { from[0] + dir[0] * REACH, from[1] + dir[1] * REACH,
                          from[2] + dir[2] * REACH };
    const float zero[3] = { 0, 0, 0 };
    mapgen_trace_result_t hit;
    MapGenTrace_Box(ctx, from, to, zero, zero, MAPGEN_TRACE_SOLID, &hit);
    *dist = hit.fraction * REACH;
    if (hit.fraction >= 0.999f)
        return 2;
    return (hit.surface_flags & SURF_SKY) ? 1 : 0;
}

static float horizon_of[MAX_STANDS];
static float stand_z[MAX_STANDS];
static float sight[MAX_STANDS * NUM_AZ];
static float up_height[MAX_STANDS];
static float scratch[MAX_STANDS];

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
    if (!world)
        return 2;

    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (!MapGenTrace_Bind(&ctx, bsp))
        return 2;

    uint32_t stands = 0, sights = 0, ups = 0;
    uint64_t rays = 0, sky_rays = 0, none_rays = 0;
    uint64_t outside = 0;       /* horizon <= 30: standing OUT of doors */
    uint64_t any45 = 0;
    uint64_t el_sky[NUM_EL] = { 0 };

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

            float hz = 999.0f;
            bool saw45 = false;
            for (int e = 0; e < NUM_EL; e++) {
                const float el = EL[e] * (float)M_PI / 180.0f;
                int here_sky = 0;
                for (int a = 0; a < NUM_AZ; a++) {
                    const float az = (float)a * 2.0f * (float)M_PI / NUM_AZ;
                    const float dir[3] = { cosf(az) * cosf(el),
                                           sinf(az) * cosf(el), sinf(el) };
                    float d;
                    const int what = shoot(&ctx, eye, dir, &d);
                    rays++;
                    if (what == 1) {
                        sky_rays++;
                        here_sky++;
                        if (EL[e] <= 45.0f)
                            saw45 = true;
                    } else if (what == 2) {
                        none_rays++;
                    }
                    if (e == 0 && sights < MAX_STANDS * NUM_AZ)
                        sight[sights++] = d;
                }
                el_sky[e] += (uint64_t)here_sky;
                if (here_sky * 2 >= NUM_AZ && hz > 900.0f)
                    hz = EL[e];
            }
            {
                const float up[3] = { 0, 0, 1 };
                float d;
                if (shoot(&ctx, eye, up, &d) == 1) {
                    up_height[ups++] = d;
                    if (hz > 900.0f)
                        hz = 90.0f;     /* sky only straight overhead */
                }
            }
            horizon_of[stands] = hz;
            stand_z[stands] = z;
            stands++;
            if (hz <= 30.0f)
                outside++;
            if (saw45)
                any45++;
            z += GRID;      /* one standing place per column */
        }
      }
    }

    printf("standing places %u\n", stands);
    printf("rays %llu, sky %llu (%llu permille), nowhere %llu\n",
           (unsigned long long)rays, (unsigned long long)sky_rays,
           rays ? (unsigned long long)(1000ull * sky_rays / rays) : 0ull,
           (unsigned long long)none_rays);
    for (int e = 0; e < NUM_EL; e++)
        printf("elevation %.0f sky %llu permille\n", EL[e],
               stands ? (unsigned long long)(1000ull * el_sky[e]
                                             / ((uint64_t)stands * NUM_AZ))
                      : 0ull);
    printf("straight up sky %llu permille\n",
           stands ? (unsigned long long)(1000ull * ups / stands) : 0ull);
    printf("outside %llu permille\n",
           stands ? (unsigned long long)(1000ull * outside / stands) : 0ull);
    printf("any sky below 45 %llu permille\n",
           stands ? (unsigned long long)(1000ull * any45 / stands) : 0ull);

    uint32_t nh = 0;
    for (uint32_t i = 0; i < stands; i++)
        if (horizon_of[i] < 900.0f)
            scratch[nh++] = horizon_of[i];
    qsort(scratch, nh, sizeof(float), cmpf);
    printf("horizon places %u median %.0f quartiles %.0f %.0f\n", nh,
           nh ? scratch[nh / 2] : 0.0f, nh ? scratch[nh / 4] : 0.0f,
           nh ? scratch[(3 * nh) / 4] : 0.0f);

    qsort(up_height, ups, sizeof(float), cmpf);
    printf("sky height median %.0f quartiles %.0f %.0f\n",
           ups ? up_height[ups / 2] : 0.0f, ups ? up_height[ups / 4] : 0.0f,
           ups ? up_height[(3 * ups) / 4] : 0.0f);

    qsort(sight, sights, sizeof(float), cmpf);
    double mean = 0;
    for (uint32_t i = 0; i < sights; i++)
        mean += sight[i];
    printf("sightline mean %.0f median %.0f p90 %.0f\n",
           sights ? mean / sights : 0.0,
           sights ? sight[sights / 2] : 0.0f,
           sights ? sight[(9 * sights) / 10] : 0.0f);

    /* The storeys of the OUTDOORS: floor heights that hold places whose
       horizon is 45 or less, each holding a twentieth of them. */
    float levels[64];
    uint32_t level_count[64], num_levels = 0, outdoors = 0;
    for (uint32_t i = 0; i < stands; i++) {
        if (horizon_of[i] > 45.0f)
            continue;
        outdoors++;
        bool placed = false;
        for (uint32_t l = 0; l < num_levels && !placed; l++)
            if (fabsf(levels[l] - stand_z[i]) <= STOREY) {
                level_count[l]++;
                placed = true;
            }
        if (!placed && num_levels < 64) {
            levels[num_levels] = stand_z[i];
            level_count[num_levels] = 1;
            num_levels++;
        }
    }
    uint32_t real = 0;
    for (uint32_t l = 0; l < num_levels; l++)
        if (outdoors && level_count[l] * 20u >= outdoors)
            real++;
    printf("outdoor storeys %u of %u clusters over %u places\n", real,
           num_levels, outdoors);
    for (uint32_t l = 0; l < num_levels; l++)
        if (outdoors && level_count[l] * 20u >= outdoors)
            printf("  storey z %.0f places %u\n", levels[l], level_count[l]);

    MapGenTrace_Release(&ctx);
    MapGenBsp_Free(bsp);
    return 0;
}
