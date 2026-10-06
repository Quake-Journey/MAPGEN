/*
 * MAPGEN-1 BspDocument test driver.
 *
 * Compiled and run by tools/check_mapgen_bsp_document.py.
 *
 *   driver digest <file.bsp>      -> "OK <16-hex digest> <counts...>" | "<ERROR>"
 *   driver text   <file.bsp>      -> the canonical text on stdout
 *   driver point  <file.bsp> x y z -> "<contents-int>"
 *
 * It exists so the C document can be compared against the Python oracle on the
 * same real maps. Two independent readers agreeing on a canonical digest is
 * the only evidence either of them is right about a format neither of us
 * wrote.
 */

#include "common/mapgen_bsp.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return NULL;
    }
    long size = ftell(f);
    if (size < 0) {
        fclose(f);
        return NULL;
    }
    rewind(f);
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) {
        fclose(f);
        return NULL;
    }
    size_t got = fread(data, 1, (size_t)size, f);
    fclose(f);
    *out_size = got;
    return data;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        printf("usage\n");
        return 2;
    }
    const char *mode = argv[1];
    size_t size = 0;
    uint8_t *data = read_file(argv[2], &size);
    if (!data) {
        printf("READ_FAILED\n");
        return 1;
    }

    mapgen_bsp_t *bsp = NULL;
    mapgen_bsp_result_t r = MapGenBsp_Load(data, size, &bsp);
    free(data);
    if (r != MAPGEN_BSP_OK) {
        printf("%s\n", MapGenBsp_ResultName(r));
        return 0;
    }

    if (!strcmp(mode, "digest")) {
        printf("OK %016llx %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u\n",
               (unsigned long long)MapGenBsp_CanonicalDigest(bsp),
               MapGenBsp_NumPlanes(bsp), MapGenBsp_NumNodes(bsp),
               MapGenBsp_NumLeafs(bsp), MapGenBsp_NumLeafBrushes(bsp),
               MapGenBsp_NumLeafFaces(bsp), MapGenBsp_NumBrushes(bsp),
               MapGenBsp_NumBrushSides(bsp), MapGenBsp_NumTexInfo(bsp),
               MapGenBsp_NumModels(bsp), MapGenBsp_NumVertices(bsp),
               MapGenBsp_NumEdges(bsp), MapGenBsp_NumSurfEdges(bsp),
               MapGenBsp_NumFaces(bsp), MapGenBsp_NumAreas(bsp),
               MapGenBsp_NumAreaPortals(bsp), MapGenBsp_VisibilityBytes(bsp),
               MapGenBsp_LightingBytes(bsp));
    } else if (!strcmp(mode, "text")) {
        size_t needed = MapGenBsp_CanonicalText(bsp, NULL, 0);
        char *text = malloc(needed + 1);
        if (text) {
            MapGenBsp_CanonicalText(bsp, text, needed + 1);
            fwrite(text, 1, needed, stdout);
            free(text);
        }
    } else if (!strcmp(mode, "point") && argc >= 6) {
        float p[3] = { (float)atof(argv[3]), (float)atof(argv[4]), (float)atof(argv[5]) };
        printf("%d\n", MapGenBsp_PointContents(bsp, p));
    } else {
        printf("BAD_MODE\n");
    }

    MapGenBsp_Free(bsp);
    return 0;
}
