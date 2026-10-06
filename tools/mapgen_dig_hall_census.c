/*
 * Which of a plan's tunnels could open into a HALL on the way?
 *
 *     mapgen_dig_hall_census <donor.bsp> <ground.bsp> <ambition> <seed> [width height margin]
 *
 * Ledger row 309: q2dm1's walls can hardly be moved, and its rock has room for new
 * space - a chamber census found 192 placements of a 192 by 192 by 128 room beside
 * a wall. A room with one mouth is a dead end and a construction without a purpose,
 * so the space is asked of the tunnels instead: a dig already joins two places, and
 * a long level stretch of it grown into a hall is new architecture on a route that
 * already has one.
 *
 * For every dig edit the plan deals (`MapGenGeometryEdit_DigBoxes`), every segment
 * whose box is longer than `width` along one level axis and no taller than a
 * tunnel is grown to `width` across that axis and to `height` over its own floor,
 * about its own middle; the grown box with `margin` all round, less the segment's
 * own box, is asked of the compiled ground - all rock, or where it meets air.
 * Nothing is carved.
 */

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_geometry_edit.h"

#define MAX_SEGS 32u

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

static bool rock_at(const mapgen_bsp_t *b, const float p[3])
{
    return (MapGenBsp_PointContents(b, p) & MAPGEN_CONTENTS_SOLID) != 0;
}

/* Air points of the grown box outside the segment's own box, and how many were asked. */
static uint32_t air_in(const mapgen_bsp_t *b, const float lo[3], const float hi[3],
                       const float slo[3], const float shi[3], uint32_t *asked,
                       float first[3])
{
    uint32_t air = 0;
    *asked = 0;
    for (float x = lo[0]; x <= hi[0] + 0.5f; x += 16.0f)
        for (float y = lo[1]; y <= hi[1] + 0.5f; y += 16.0f)
            for (float z = lo[2]; z <= hi[2] + 0.5f; z += 16.0f) {
                const float p[3] = { x > hi[0] ? hi[0] : x, y > hi[1] ? hi[1] : y,
                                     z > hi[2] ? hi[2] : z };
                if (p[0] > slo[0] && p[0] < shi[0] && p[1] > slo[1] && p[1] < shi[1]
                    && p[2] > slo[2] && p[2] < shi[2])
                    continue;
                (*asked)++;
                if (!rock_at(b, p)) {
                    if (!air)
                        memcpy(first, p, sizeof(p));
                    air++;
                }
            }
    return air;
}

int main(int argc, char **argv)
{
    if (argc < 5) {
        fprintf(stderr, "usage: %s donor.bsp ground.bsp ambition seed [width height margin]\n",
                argv[0]);
        return 2;
    }
    mapgen_bsp_t *donor_bsp = load(argv[1]);
    mapgen_bsp_t *ground = load(argv[2]);
    const int32_t ambition = atoi(argv[3]);
    const uint64_t seed = strtoull(argv[4], NULL, 10);
    const float width = argc > 5 ? strtof(argv[5], NULL) : 192.0f;
    const float height = argc > 6 ? strtof(argv[6], NULL) : 128.0f;
    const float margin = argc > 7 ? strtof(argv[7], NULL) : 16.0f;
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
    printf("plan: seed %llu, ambition %d, %u digs; hall %.0f wide and %.0f tall, %.0f of rock"
           " round it\n", (unsigned long long)seed, ambition,
           MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_DIG), (double)width, (double)height,
           (double)margin);

    uint32_t digs = 0, level_segs = 0, halls = 0, digs_with_hall = 0;
    const uint32_t edits = MapGenGeometryEdit_Count(plan);
    for (uint32_t i = 0; i < edits; i++) {
        const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
        if (!e || e->kind != MAPGEN_EDIT_DIG)
            continue;
        float boxes[6u * MAX_SEGS];
        const uint32_t segs = MapGenGeometryEdit_DigBoxes(plan, e->target, boxes, MAX_SEGS);
        mapgen_dig_report_t dig;
        const bool known = MapGenGeometryEdit_DigAt(plan, e->target, &dig);
        digs++;
        printf("dig %u (edit %u)", e->target, i);
        if (known)
            printf(" from %.0f %.0f %.0f to %.0f %.0f %.0f", (double)dig.from[0],
                   (double)dig.from[1], (double)dig.from[2], (double)dig.to[0],
                   (double)dig.to[1], (double)dig.to[2]);
        printf(", %u segments\n", segs);
        bool any = false;
        for (uint32_t s = 0; s < segs; s++) {
            const float *lo = &boxes[6u * s], *hi = &boxes[6u * s + 3u];
            const float len[3] = { hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2] };
            /* the router cuts a tunnel as a chain of 128-unit cells, so a hall
               is one cell grown on both level axes, not a long stretch */
            const bool level = len[2] <= 176.0f;
            printf("   segment %u: %.0f %.0f %.0f .. %.0f %.0f %.0f (%.0f x %.0f x %.0f)%s",
                   s, (double)lo[0], (double)lo[1], (double)lo[2], (double)hi[0], (double)hi[1],
                   (double)hi[2], (double)len[0], (double)len[1], (double)len[2],
                   level ? "" : " - too tall a cell for a hall\n");
            if (!level)
                continue;
            level_segs++;
            float glo[3], ghi[3];
            memcpy(glo, lo, 3 * sizeof(float));
            memcpy(ghi, hi, 3 * sizeof(float));
            for (int a = 0; a < 2; a++) {
                const float mid = 0.5f * (lo[a] + hi[a]);
                if (len[a] < width) {
                    glo[a] = mid - 0.5f * width;
                    ghi[a] = mid + 0.5f * width;
                }
            }
            if (len[2] < height)
                ghi[2] = lo[2] + height;
            for (int a = 0; a < 3; a++) {
                glo[a] -= margin;
                ghi[a] += margin;
            }
            uint32_t asked = 0;
            float first[3] = { 0 };
            const uint32_t air = air_in(ground, glo, ghi, lo, hi, &asked, first);
            if (!air) {
                halls++;
                any = true;
                printf(" - a hall fits: %.0f x %.0f x %.0f all rock round the tunnel\n",
                       (double)(ghi[0] - glo[0] - 2 * margin), (double)(ghi[1] - glo[1] - 2 * margin),
                       (double)(ghi[2] - glo[2] - 2 * margin));
            } else {
                printf(" - %u of %u points of the grown box are air, the first at %.0f %.0f %.0f\n",
                       air, asked, (double)first[0], (double)first[1], (double)first[2]);
            }
        }
        digs_with_hall += any ? 1u : 0u;
    }
    printf("== %u digs, %u long level segments, %u of them can grow into a hall; %u digs with at"
           " least one\n", digs, level_segs, halls, digs_with_hall);
    return 0;
}
