/*
 * What a map's rooms are made of, by role.
 *
 *     mapgen_bundle_census MAP.bsp
 *
 * A graft moves what a room CONTAINS and leaves the boundary that seals the
 * map where the room is - "theirs would arrive as a second shell inside it".
 * So a room whose every brush is its own boundary has nothing to give, and the
 * planner skips it.
 *
 * An invented map is built room by room and every one of its rooms is movable,
 * which made it look like a much better donor than a hand-built map. Then the
 * planner found no graft in it at all. This says whether "all shell, nothing
 * inside" is the reason.
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_rooms.h"
#include "common/mapgen_bundle.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s MAP.bsp\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp)
        return 1;
    mapgen_geometry_t *geo = NULL;
    if (MapGenGeometry_FromBsp(bsp, &geo) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot lift %s into geometry\n", argv[1]);
        return 1;
    }

    mapgen_rooms_t *rooms = NULL;
    mapgen_bundle_set_t *set = NULL;
    if (MapGenRooms_Find(bsp, 64.0f, MAPGEN_ROOMS_PERSISTENCE, &rooms)
            != MAPGEN_ROOMS_OK
        || MapGenBundle_Survey(bsp, geo, rooms, &set) != MAPGEN_BUNDLE_OK) {
        fprintf(stderr, "cannot survey the rooms\n");
        return 1;
    }

    const uint32_t n = MapGenBundleSet_Count(set);
    uint32_t all_shell = 0, has_inside = 0;
    printf("%s: %u rooms\n", argv[1], n);
    for (uint32_t i = 0; i < n; i++) {
        const mapgen_bundle_t *b = MapGenBundleSet_At(set, i);
        const uint32_t brushes = MapGenBundle_NumBrushes(b);
        uint32_t boundary = 0;
        for (uint32_t k = 0; k < brushes; k++) {
            const mapgen_bundle_brush_t *bb = MapGenBundle_Brush(b, k);
            if (bb && bb->role == MAPGEN_BUNDLE_ROLE_BOUNDARY)
                boundary++;
        }
        const uint32_t inside = brushes - boundary;
        if (!inside)
            all_shell++;
        else
            has_inside++;
        if (i < 8 || !inside)
            printf("  room %2u  %4u brushes  %4u boundary  %4u inside%s\n",
                   i, brushes, boundary, inside,
                   inside ? "" : "   <- nothing to give");
    }
    printf("\n  %u rooms have something inside, %u are all shell\n",
           has_inside, all_shell);

    MapGenBundleSet_Free(set);
    MapGenRooms_Free(rooms);
    MapGenGeometry_Free(geo);
    MapGenBsp_Free(bsp);
    return 0;
}
