/*
 * Will the generator read this map at all? (the PO, 09.10: «Генератор же должен быть универсален»; the donor survey
 * met maps the pipeline stopped on in its first second, ERR_GENERATE, without a word.) The compiled map read, then its
 * brushes rebuilt - each step's own result said, for every file given.
 *
 *     mapgen_bsp_load_probe MAP.bsp [MAP.bsp ...]
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    int bad = 0;
    for (int i = 1; i < argc; i++) {
        FILE *f = fopen(argv[i], "rb");
        if (!f) {
            printf("%s: cannot open\n", argv[i]);
            bad++;
            continue;
        }
        fseek(f, 0, SEEK_END);
        const long size = ftell(f);
        fseek(f, 0, SEEK_SET);
        unsigned char *data = size > 0 ? malloc((size_t)size) : NULL;
        const size_t got = data ? fread(data, 1, (size_t)size, f) : 0;
        fclose(f);
        if (!data || got != (size_t)size) {
            printf("%s: cannot read\n", argv[i]);
            free(data);
            bad++;
            continue;
        }
        mapgen_bsp_t *bsp = NULL;
        const mapgen_bsp_result_t rb = MapGenBsp_Load(data, (size_t)size, &bsp);
        free(data);
        if (rb != MAPGEN_BSP_OK) {
            printf("%s: the compiled map - %s\n", argv[i], MapGenBsp_ResultName(rb));
            bad++;
            continue;
        }
        mapgen_geometry_t *g = NULL;
        const mapgen_geometry_result_t rg = MapGenGeometry_FromBsp(bsp, &g);
        printf("%s: the compiled map read; its brushes - %s%s\n", argv[i], MapGenGeometry_ResultName(rg),
               rg == MAPGEN_GEOMETRY_OK ? "" : " (the generator cannot rebuild it)");
        bad += rg != MAPGEN_GEOMETRY_OK;
        MapGenGeometry_Free(g);
        MapGenBsp_Free(bsp);
    }
    return bad ? 1 : 0;
}
