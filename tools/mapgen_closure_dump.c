/*
 * What one closure is made of, and the two questions asked of it.
 *
 *     mapgen_closure_dump <map.bsp> <seed brush> [depth] [--at x y z]
 *
 * With no `--at`, the point asked about is the middle of the seed brush: the
 * question "is there other solid inside my own wall", whose answer has to be
 * no however many pieces the wall was built from.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>

#include "common/mapgen_closure.h"

/*
 * The brush at a place.
 *
 * A guard that named brushes by index would break the day the compiler ordered
 * them differently; a place is where the fixture put it and stays there.
 */
static uint32_t brush_at(const mapgen_geometry_t *g, const float p[3])
{
    const uint32_t n = MapGenGeometry_NumBrushes(g);
    for (uint32_t b = 0; b < n; b++) {
        const mapgen_geometry_brush_t *brush = MapGenGeometry_Brush(g, b);
        if (!brush)
            continue;
        bool in = true;
        for (int a = 0; a < 3 && in; a++)
            if (p[a] < brush->mins[a] - 0.5f || p[a] > brush->maxs[a] + 0.5f)
                in = false;
        for (uint32_t s = 0; s < brush->num_sides && in; s++) {
            const mapgen_geometry_side_t *side =
                MapGenGeometry_Side(g, brush->first_side + s);
            if (!side || side->bevel)
                continue;
            if (side->normal[0] * p[0] + side->normal[1] * p[1]
                + side->normal[2] * p[2] - side->dist > 0.03125f)
                in = false;
        }
        if (in)
            return b;
    }
    return UINT32_MAX;
}

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

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <map.bsp> <seed brush | @x,y,z> [depth]"
                        " [--at x y z]\n", argv[0]);
        return 2;
    }
    const uint32_t depth = argc > 3 && argv[3][0] != '-'
                         ? (uint32_t)strtoul(argv[3], NULL, 10) : 1;
    float seed_point[3] = { 0, 0, 0 };
    const bool seed_by_place = argv[2][0] == '@';
    if (seed_by_place)
        sscanf(argv[2] + 1, "%f,%f,%f", &seed_point[0], &seed_point[1],
               &seed_point[2]);

    float at[3];
    bool have_at = false;
    for (int a = 1; a + 3 < argc; a++)
        if (!strcmp(argv[a], "--at")) {
            for (int k = 0; k < 3; k++)
                at[k] = strtof(argv[a + 1 + k], NULL);
            have_at = true;
        }

    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    mapgen_geometry_t *geometry = NULL;
    if (MapGenGeometry_FromBsp(bsp, &geometry) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot read its brushes\n");
        return 2;
    }
    printf("%u brushes, %u entities\n", MapGenGeometry_NumBrushes(geometry),
           MapGenGeometry_NumEntities(geometry));

    const uint32_t seed = seed_by_place
                        ? brush_at(geometry, seed_point)
                        : (uint32_t)strtoul(argv[2], NULL, 10);
    if (seed == UINT32_MAX) {
        printf("ERR_NO_SEED\n");
        return 2;
    }

    mapgen_closure_t *closure = NULL;
    const mapgen_closure_result_t rc =
        MapGenClosure_Build(geometry, seed, depth, &closure);
    if (rc != MAPGEN_CLOSURE_OK) {
        printf("%s\n", MapGenClosure_ResultName(rc));
        return 2;
    }

    printf("closure of brush %u at depth %u: %u brushes\n", seed, depth,
           MapGenClosure_NumBrushes(closure));
    for (uint32_t i = 0; i < MapGenClosure_NumBrushes(closure); i++) {
        const uint32_t b = MapGenClosure_Brush(closure, i);
        printf("  brush %4u %s\n", b,
               MapGenClosure_ReasonName(MapGenClosure_Reason(closure, b)));
    }
    printf("entities: %u\n", MapGenClosure_NumEntities(closure));
    for (uint32_t i = 0; i < MapGenClosure_NumEntities(closure); i++) {
        const uint32_t e = MapGenClosure_Entity(closure, i);
        const char *name = MapGenGeometry_EntityValue(geometry, e, "classname");
        printf("  entity %4u %s\n", e, name ? name : "?");
    }

    const float *mins = MapGenClosure_Mins(closure);
    const float *maxs = MapGenClosure_Maxs(closure);
    printf("bounds %.0f %.0f %.0f .. %.0f %.0f %.0f\n",
           (double)mins[0], (double)mins[1], (double)mins[2],
           (double)maxs[0], (double)maxs[1], (double)maxs[2]);

    if (!have_at) {
        const mapgen_geometry_brush_t *b = MapGenGeometry_Brush(geometry, seed);
        for (int k = 0; k < 3; k++)
            at[k] = (b->mins[k] + b->maxs[k]) * 0.5f;
    }
    printf("other solid at %.0f %.0f %.0f: %s\n", (double)at[0], (double)at[1],
           (double)at[2],
           MapGenClosure_SolidWithout(closure, geometry, at) ? "yes" : "no");
    printf("seals: %s\n",
           MapGenClosure_Seals(closure, geometry, bsp) ? "yes" : "no");

    MapGenClosure_Free(closure);
    MapGenGeometry_Free(geometry);
    MapGenBsp_Free(bsp);
    return 0;
}
