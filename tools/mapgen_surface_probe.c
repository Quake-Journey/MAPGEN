/*
 * What a compiled map leaves that a compiler cannot build cleanly.
 *
 * The one thing this prints is the number the edit transaction holds every
 * attempt to: a candidate may not have more of these than the map it came
 * from. Reading it needs no compiler and no schedule, so a fixture pair can be
 * asked what the count MEANS before anything is asked to enforce it.
 *
 *      mapgen_surface_probe <map.bsp>
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

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
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp>\n", argv[0]);
        return 2;
    }

    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 1;
    }

    mapgen_geometry_t *geometry = NULL;
    if (MapGenGeometry_FromBsp(bsp, &geometry) != MAPGEN_GEOMETRY_OK
        || !geometry) {
        fprintf(stderr, "cannot rebuild the geometry of %s\n", argv[1]);
        MapGenBsp_Free(bsp);
        return 1;
    }

    printf("brushes: %u\n", MapGenGeometry_NumBrushes(geometry));
    printf("surface faults: %u\n", MapGenGeometry_SurfaceFaults(geometry, bsp));

    MapGenGeometry_Free(geometry);
    MapGenBsp_Free(bsp);
    return 0;
}
