/*
 * The destruction driver (Fable's brief 11 D2, ledger row 412l).
 *
 *   mapgen_destroy_driver FINISHED.bsp OUT.map --destruction D --seed S --pack PACK.txt --needs NEEDS.txt
 *                         [--game BASEQ2] [--skip MASK]
 *
 * Reads a finished map, puts D percent of it in ruins (`MapGenGeometryEdit_Destroy`) and writes the .map the
 * compiler takes; the cracked copies of the map's own textures it now wears go to NEEDS for
 * `tools/mapgen_textures.py crack`. Prints one line `destroyed: ...` the destroy tool and the Studio read.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_geometry_edit.h"

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
        fprintf(stderr, "usage: %s FINISHED.bsp OUT.map --destruction D --seed S --pack PACK.txt --needs NEEDS.txt"
                        " [--game BASEQ2] [--skip MASK]\n", argv[0]);
        return 2;
    }
    uint32_t percent = 0, skip = 0;
    unsigned long long seed = 1;
    const char *pack = NULL, *needs = NULL, *masks = NULL, *into = NULL;
    for (int a = 3; a < argc; a++) {
        if (!strcmp(argv[a], "--destruction") && a + 1 < argc)
            percent = (uint32_t)strtoul(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--seed") && a + 1 < argc)
            seed = strtoull(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--pack") && a + 1 < argc)
            pack = argv[++a];
        else if (!strcmp(argv[a], "--needs") && a + 1 < argc)
            needs = argv[++a];
        else if (!strcmp(argv[a], "--game") && a + 1 < argc)
            MapGenGeometryEdit_SetGameDir(argv[++a]);
        else if (!strcmp(argv[a], "--masks") && a + 1 < argc)
            masks = argv[++a];
        else if (!strcmp(argv[a], "--into") && a + 1 < argc)
            into = argv[++a];
        else if (!strcmp(argv[a], "--skip") && a + 1 < argc)
            skip = (uint32_t)strtoul(argv[++a], NULL, 10);
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    mapgen_geometry_t *g = NULL;
    if (!bsp || MapGenGeometry_FromBsp(bsp, &g) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    MapGenGeometryEdit_DestroySkip(skip);
    mapgen_destroy_report_t r;
    const mapgen_geometry_result_t rc = MapGenGeometryEdit_Destroy(g, bsp, percent, seed, pack, needs, &r);
    if (rc != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "destruction failed: %s\n", MapGenGeometry_ResultName(rc));
        return 2;
    }
    printf("destroyed: percent %u cracks %u rubble %u craters %u breaches %u gouges %u broken %u collapses %u"
           " ruins %u refused %u rooms %u pack %u needs %u nearest %.0f wanted %u %u %u %u %u %u\n", percent, r.cracks,
           r.rubble, r.craters, r.breaches, r.gouges, r.broken, r.collapses, r.ruins, r.refused, r.rooms, r.pack, r.needs,
           (double)r.start_nearest,
           r.wanted[0], r.wanted[1], r.wanted[2], r.wanted[3], r.wanted[4], r.wanted[5]);
    if (masks && into && needs) {
        uint32_t missing = 0;
        const uint32_t drawn = MapGenGeometryEdit_DrawCracks(needs, masks, into, &missing);
        printf("cracks drawn: %u, %u without an original or a mask\n", drawn, missing);
    }
    if (MapGenGeometry_WriteValve220(g, argv[2]) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot write %s\n", argv[2]);
        return 2;
    }
    MapGenGeometry_Free(g);
    MapGenBsp_Free(bsp);
    return 0;
}
