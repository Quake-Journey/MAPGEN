/*
 * Carrying a room from one map into another, and saying exactly what crossed.
 *
 *     mapgen_graft_driver SRC.bsp DST.bsp OUT.map
 *                         [--quarter N] [--mirror]
 *                         [--offset X Y Z] [--pivot X Y Z]
 *                         [--models-only] [--first N] [--count N]
 *
 * GF7 is bundle substitution across donors, and the one thing a same-map swap
 * never needed is geometry from a DIFFERENT map. This drives that primitive on
 * its own, before any operator uses it, so what it does can be measured rather
 * than inferred from what an operator produced.
 *
 * `--first`/`--count` choose which of the source's brushes cross, so a test can
 * name a subset without the driver having to know what a bundle is. Entities
 * cross when the brushes they own do; a point entity crosses when `--models-
 * only` is absent.
 *
 * What it prints is what the caller can check: how many brushes and entities
 * the destination had, how many crossed, where the first grafted brush landed,
 * and the bounds of the grafted set - which is what says the turn and the
 * offset were applied rather than merely accepted.
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

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
    long size = ftell(f);
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

static mapgen_geometry_t *geometry_of(const char *path)
{
    mapgen_bsp_t *bsp = load(path);
    if (!bsp)
        return NULL;
    mapgen_geometry_t *g = NULL;
    const mapgen_geometry_result_t rc = MapGenGeometry_FromBsp(bsp, &g);
    MapGenBsp_Free(bsp);
    if (rc != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "%s: %s\n", path, MapGenGeometry_ResultName(rc));
        return NULL;
    }
    return g;
}

int main(int argc, char **argv)
{
    if (argc < 4) {
        fprintf(stderr, "usage: %s SRC.bsp DST.bsp OUT.map [--quarter N]"
                        " [--mirror] [--offset X Y Z] [--pivot X Y Z]"
                        " [--first N] [--count N] [--models-only]\n", argv[0]);
        return 2;
    }
    const char *src_path = argv[1];
    const char *dst_path = argv[2];
    const char *out_path = argv[3];

    uint32_t quarter = 0;
    bool mirror = false;
    bool models_only = false;
    float offset[3] = { 0, 0, 0 };
    float pivot[3] = { 0, 0, 0 };
    uint32_t first = 0, count = 0;

    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i], "--quarter") && i + 1 < argc)
            quarter = (uint32_t)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--mirror"))
            mirror = true;
        else if (!strcmp(argv[i], "--models-only"))
            models_only = true;
        else if (!strcmp(argv[i], "--offset") && i + 3 < argc) {
            for (int a = 0; a < 3; a++)
                offset[a] = strtof(argv[++i], NULL);
        } else if (!strcmp(argv[i], "--pivot") && i + 3 < argc) {
            for (int a = 0; a < 3; a++)
                pivot[a] = strtof(argv[++i], NULL);
        } else if (!strcmp(argv[i], "--first") && i + 1 < argc)
            first = (uint32_t)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--count") && i + 1 < argc)
            count = (uint32_t)strtoul(argv[++i], NULL, 10);
    }

    mapgen_geometry_t *src = geometry_of(src_path);
    mapgen_geometry_t *dst = geometry_of(dst_path);
    if (!src || !dst) {
        MapGenGeometry_Free(src);
        MapGenGeometry_Free(dst);
        return 2;
    }

    const uint32_t src_brushes = MapGenGeometry_NumBrushes(src);
    const uint32_t src_entities = MapGenGeometry_NumEntities(src);
    if (!count || first + count > src_brushes)
        count = src_brushes > first ? src_brushes - first : 0;

    uint8_t *brush_mask = calloc(src_brushes ? src_brushes : 1, 1);
    uint8_t *entity_mask = calloc(src_entities ? src_entities : 1, 1);
    if (!brush_mask || !entity_mask) {
        free(brush_mask);
        free(entity_mask);
        MapGenGeometry_Free(src);
        MapGenGeometry_Free(dst);
        return 2;
    }
    for (uint32_t b = first; b < first + count && b < src_brushes; b++)
        brush_mask[b] = 1;

    /*
     * An entity crosses when its brushes do. A point entity has no brushes at
     * all, so it crosses unless the caller asked for models only - which is
     * how a test looks at the geometry without the entity string moving too.
     */
    for (uint32_t e = 0; e < src_entities; e++) {
        const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(src, e);
        if (!ent)
            continue;
        if (!ent->model) {
            entity_mask[e] = models_only ? 0 : 1;
            continue;
        }
        bool owns_one = false;
        for (uint32_t b = 0; b < src_brushes && !owns_one; b++) {
            const mapgen_geometry_brush_t *brush = MapGenGeometry_Brush(src, b);
            if (brush && brush_mask[b] && brush->model == ent->model)
                owns_one = true;
        }
        entity_mask[e] = owns_one ? 1 : 0;
    }

    printf("source   %u brushes, %u entities\n", src_brushes, src_entities);
    printf("dest     %u brushes, %u entities\n",
           MapGenGeometry_NumBrushes(dst), MapGenGeometry_NumEntities(dst));
    printf("asked    %u brushes from %u\n", count, first);

    uint32_t landed = 0, crossed = 0;
    const mapgen_geometry_result_t rc =
        MapGenGeometry_Graft(dst, src, brush_mask, entity_mask, pivot, quarter,
                             mirror, offset, &landed, &crossed);
    printf("result   %s\n", MapGenGeometry_ResultName(rc));
    free(brush_mask);
    free(entity_mask);

    if (rc == MAPGEN_GEOMETRY_OK) {
        printf("crossed  %u brushes, landed at %u\n", crossed, landed);
        printf("after    %u brushes, %u entities\n",
               MapGenGeometry_NumBrushes(dst), MapGenGeometry_NumEntities(dst));
        /* Where the grafted set actually is, which is what says the turn and
           the offset were applied rather than merely accepted. */
        float lo[3] = { 1e30f, 1e30f, 1e30f };
        float hi[3] = { -1e30f, -1e30f, -1e30f };
        for (uint32_t b = landed; b < landed + crossed; b++) {
            const mapgen_geometry_brush_t *brush = MapGenGeometry_Brush(dst, b);
            if (!brush)
                continue;
            for (int a = 0; a < 3; a++) {
                if (brush->mins[a] < lo[a]) lo[a] = brush->mins[a];
                if (brush->maxs[a] > hi[a]) hi[a] = brush->maxs[a];
            }
        }
        printf("bounds   %.0f %.0f %.0f .. %.0f %.0f %.0f\n",
               (double)lo[0], (double)lo[1], (double)lo[2],
               (double)hi[0], (double)hi[1], (double)hi[2]);
        /* And the source is untouched - a donor that changed while being read
           from is a donor nothing can be measured against afterwards. */
        printf("source   %u brushes, %u entities after\n",
               MapGenGeometry_NumBrushes(src),
               MapGenGeometry_NumEntities(src));
        const mapgen_geometry_result_t wr =
            MapGenGeometry_WriteValve220(dst, out_path);
        printf("wrote    %s\n", MapGenGeometry_ResultName(wr));
    }

    MapGenGeometry_Free(src);
    MapGenGeometry_Free(dst);
    return rc == MAPGEN_GEOMETRY_OK ? 0 : 1;
}
