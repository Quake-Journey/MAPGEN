/*
 * The schedule a seed produces, in the order the transaction will spend it.
 *
 *     mapgen_schedule_dump DONOR.bsp SEED [--limit N]
 *
 * One line per planned edit: its position, its kind, what it acts on, and by
 * how much. The transaction takes this list in order and stops when it reaches
 * the fidelity it was asked for, so this list IS what a fidelity spends - and
 * whether two seeds build different maps is decided here, before a single
 * compile.
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_geometry_edit.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s DONOR.bsp SEED [--limit N]\n", argv[0]);
        return 2;
    }
    const uint64_t seed = strtoull(argv[2], NULL, 10);
    uint32_t limit = 0;
    for (int i = 3; i < argc; i++)
        if (!strcmp(argv[i], "--limit") && i + 1 < argc)
            limit = (uint32_t)strtoul(argv[++i], NULL, 10);

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", argv[1]);
        return 2;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = size > 0 ? malloc((size_t)size) : NULL;
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size) {
        free(data);
        fclose(f);
        return 2;
    }
    fclose(f);

    mapgen_bsp_t *bsp = NULL;
    if (MapGenBsp_Load(data, (size_t)size, &bsp) != MAPGEN_BSP_OK) {
        free(data);
        return 2;
    }
    free(data);

    mapgen_geometry_t *donor = NULL;
    if (MapGenGeometry_FromBsp(bsp, &donor) != MAPGEN_GEOMETRY_OK) {
        MapGenBsp_Free(bsp);
        return 2;
    }
    mapgen_geometry_edit_plan_t *plan = NULL;
    if (MapGenGeometryEdit_Plan(donor, bsp, seed, &plan)
        != MAPGEN_GEOMETRY_OK) {
        MapGenGeometry_Free(donor);
        MapGenBsp_Free(bsp);
        return 2;
    }

    const uint32_t offered = MapGenGeometryEdit_Count(plan);
    printf("seed %llu\n", (unsigned long long)seed);
    printf("edits %u\n", offered);
    for (uint32_t i = 0; i < offered && (!limit || i < limit); i++) {
        const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
        if (!e)
            break;
        printf("%4u %-20s target %u amount %d\n", i,
               MapGenGeometryEdit_KindName((mapgen_edit_kind_t)e->kind),
               e->target, e->amount);
    }

    MapGenGeometryEdit_Free(plan);
    MapGenGeometry_Free(donor);
    MapGenBsp_Free(bsp);
    return 0;
}
