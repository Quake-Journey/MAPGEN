/*
 * The seeded schedule, one line per edit.
 *
 *     mapgen_deal_dump DONOR.bsp SEED [OTHER.bsp ...]
 *
 * It exists to answer one question that nothing else could: does offering a
 * donor ADD to the schedule, or does it re-deal it?
 *
 * GF7 measured that offering a second donor made the result worse - F75
 * reached 290 of 250 without one and 79 of 250 with one, same seed, same
 * worker. A graft is a single edit, so a schedule that is disturbed by one
 * edit is the suspect, and a schedule is cheap to compare: no compiler, no
 * candidate, no minutes. This prints the plan and the comparison is done on
 * the text.
 *
 * The line is `ORDINAL KIND TARGET`. Grafts are printed too and are expected
 * to differ - they are what the extra donor adds. Every OTHER kind's edits
 * must appear in the same relative order in both runs, and that is the whole
 * claim.
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_geometry_edit.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_OTHERS 8

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = size > 0 ? malloc((size_t)size) : NULL;
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size) {
        free(data);
        fclose(f);
        fprintf(stderr, "cannot read %s\n", path);
        return NULL;
    }
    fclose(f);

    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t rc = MapGenBsp_Load(data, (size_t)size, &bsp);
    free(data);
    if (rc != MAPGEN_BSP_OK) {
        fprintf(stderr, "%s: %s\n", path, MapGenBsp_ResultName(rc));
        return NULL;
    }
    return bsp;
}

static const char *name_of(const char *path)
{
    const char *slash = strrchr(path, '\\');
    const char *fwd = strrchr(path, '/');
    if (fwd > slash)
        slash = fwd;
    return slash ? slash + 1 : path;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s DONOR.bsp SEED [OTHER.bsp ...]\n", argv[0]);
        return 2;
    }

    mapgen_bsp_t *donor_bsp = load(argv[1]);
    if (!donor_bsp)
        return 1;
    mapgen_geometry_t *donor = NULL;
    if (MapGenGeometry_FromBsp(donor_bsp, &donor) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot lift %s into geometry\n", argv[1]);
        MapGenBsp_Free(donor_bsp);
        return 1;
    }

    const uint64_t seed = strtoull(argv[2], NULL, 10);

    mapgen_bsp_t *other_bsps[MAX_OTHERS] = { 0 };
    mapgen_geometry_t *others[MAX_OTHERS] = { 0 };
    const char *names[MAX_OTHERS] = { 0 };
    uint32_t num_others = 0;
    for (int a = 3; a < argc && num_others < MAX_OTHERS; a++) {
        other_bsps[num_others] = load(argv[a]);
        if (!other_bsps[num_others])
            return 1;
        if (MapGenGeometry_FromBsp(other_bsps[num_others],
                                   &others[num_others]) != MAPGEN_GEOMETRY_OK) {
            fprintf(stderr, "cannot lift %s into geometry\n", argv[a]);
            return 1;
        }
        names[num_others] = name_of(argv[a]);
        num_others++;
    }

    mapgen_geometry_edit_plan_t *plan = NULL;
    const mapgen_geometry_result_t rc = MapGenGeometryEdit_PlanWith(
        donor, donor_bsp, seed,
        num_others ? (const mapgen_geometry_t *const *)others : NULL,
        num_others ? (const mapgen_bsp_t *const *)other_bsps : NULL,
        num_others ? names : NULL, num_others, &plan);
    if (rc != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "plan: %s\n", MapGenGeometry_ResultName(rc));
        return 1;
    }

    const uint32_t edits = MapGenGeometryEdit_Count(plan);
    printf("donor %s seed %llu others %u edits %u\n", name_of(argv[1]),
           (unsigned long long)seed, num_others, edits);
    for (uint32_t i = 0; i < edits; i++) {
        const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
        printf("%u %s %u\n", e->schedule,
               MapGenGeometryEdit_KindName((mapgen_edit_kind_t)e->kind),
               e->target);
    }

    MapGenGeometryEdit_Free(plan);
    for (uint32_t i = 0; i < num_others; i++) {
        MapGenGeometry_Free(others[i]);
        MapGenBsp_Free(other_bsps[i]);
    }
    MapGenGeometry_Free(donor);
    MapGenBsp_Free(donor_bsp);
    return 0;
}
