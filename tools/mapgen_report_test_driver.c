/*
 * MAPGEN-1 Training report test driver.
 *
 * Compiled and run by tools/check_mapgen_report_contract.py.
 *
 *   driver render <map.bsp>...   train, then print the Training result page
 *
 * The guard reads the rendered text and checks what it says - and, more to the
 * point, what it refuses to say.
 */

#include "common/mapgen_report.h"
#include "common/mapgen_lineage.h"
#include "common/mapgen_features.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    const long size = ftell(f);
    if (size < 0) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) { fclose(f); return NULL; }
    const size_t got = fread(data, 1, (size_t)size, f);
    fclose(f);
    *out_size = got;
    return data;
}

static const char *basename_of(const char *path)
{
    const char *slash = strrchr(path, '/');
    const char *back = strrchr(path, '\\');
    const char *last = slash > back ? slash : back;
    return last ? last + 1 : path;
}

int main(int argc, char **argv)
{
    if (argc < 3 || strcmp(argv[1], "render")) {
        printf("usage\n");
        return 2;
    }

    mapgen_training_t *t = MapGenTraining_Create();
    if (!t)
        return 1;

    for (int i = 2; i < argc; i++) {
        size_t size = 0;
        uint8_t *data = read_file(argv[i], &size);
        if (!data)
            continue;
        uint8_t sha[MAPGEN_SHA256_BYTES];
        MapGenDigest_Sha256(data, size, sha);

        mapgen_bsp_t *bsp = NULL;
        mapgen_genome_t *genome = NULL;
        mapgen_space_t *space = NULL;
        mapgen_wiring_t *wiring = NULL;
        mapgen_features_t *features = NULL;
        mapgen_space_params_t p = MapGenSpace_DefaultParams();

        if (MapGenBsp_Load(data, size, &bsp) == MAPGEN_BSP_OK &&
            MapGenGenome_Extract(bsp, &genome) == MAPGEN_GENOME_OK &&
            MapGenSpace_Build(bsp, &p, &space) == MAPGEN_SPACE_OK &&
            MapGenWiring_Build(genome, bsp, &wiring) == MAPGEN_WIRING_OK &&
            MapGenFeatures_Build(bsp, genome, space, wiring, &features)
                == MAPGEN_FEATURES_OK) {
            MapGenTraining_AddSource(t, basename_of(argv[i]), "baseq2", size,
                                     sha, features, genome, wiring,
                                      /* this driver learns statistics, not architecture:
                                         neither a shape nor a solid */
                                      NULL, NULL);
        }
        MapGenFeatures_Free(features);
        MapGenWiring_Free(wiring);
        MapGenSpace_Free(space);
        MapGenGenome_Free(genome);
        MapGenBsp_Free(bsp);
        free(data);
    }

    uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES], revision[MAPGEN_SNAPSHOT_UUID_BYTES];
    memset(lineage, 0xC1, sizeof(lineage));
    memset(revision, 0xC2, sizeof(revision));

    uint8_t *bytes = NULL;
    size_t size = 0;
    if (MapGenLineage_New(t, lineage, revision, 1756600000000ull,
                          MAPGEN_COMPRESSION_DEFLATE, &bytes, &size)
        != MAPGEN_LINEAGE_OK) {
        printf("TRAIN_FAILED\n");
        MapGenTraining_Free(t);
        return 1;
    }
    MapGenTraining_Free(t);

    mapgen_snapshot_t *snap = NULL;
    if (MapGenSnapshot_Open(bytes, size, &snap) != MAPGEN_SNAPSHOT_OK) {
        printf("OPEN_FAILED\n");
        free(bytes);
        return 1;
    }

    const size_t needed = MapGenReport_Training(snap, "snapshots/example.q2mgdb",
                                                NULL, 0);
    char *text = malloc(needed + 1);
    if (text) {
        MapGenReport_Training(snap, "snapshots/example.q2mgdb", text, needed + 1);
        fwrite(text, 1, needed, stdout);
        free(text);
    }

    MapGenSnapshot_Free(snap);
    free(bytes);
    return 0;
}
