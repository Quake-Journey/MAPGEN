/*
 * MAPGEN-1 Training aggregation test driver.
 *
 * Compiled and run by tools/check_mapgen_training_contract.py.
 *
 *   driver train  <out.q2mgdb> <map.bsp>...   analyse maps, write a snapshot
 *   driver chunks <map.bsp>...                the chunk payloads, on stdout
 *   driver order  <map.bsp>...                the canonical source order
 *   driver shuffle <map.bsp>...               train twice, in opposite orders
 *
 * `shuffle` is the one that matters: contract 8 requires the payload to be
 * independent of the order workers finish in, so the same maps offered
 * forwards and backwards must produce the same payload hash.
 */

#include "common/mapgen_demo.h"
#include "common/mapgen_training.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    mapgen_bsp_t     *bsp;
    mapgen_genome_t  *genome;
    mapgen_space_t   *space;
    mapgen_wiring_t  *wiring;
    mapgen_features_t *features;
    uint8_t           sha256[MAPGEN_SHA256_BYTES];
    uint64_t          bytes;
} analysis_t;

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    long size = ftell(f);
    if (size < 0) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) { fclose(f); return NULL; }
    size_t got = fread(data, 1, (size_t)size, f);
    fclose(f);
    *out_size = got;
    return data;
}

static void free_analysis(analysis_t *a)
{
    MapGenFeatures_Free(a->features);
    MapGenWiring_Free(a->wiring);
    MapGenSpace_Free(a->space);
    MapGenGenome_Free(a->genome);
    MapGenBsp_Free(a->bsp);
    memset(a, 0, sizeof(*a));
}

static bool analyse(const char *path, analysis_t *a)
{
    memset(a, 0, sizeof(*a));
    size_t size = 0;
    uint8_t *data = read_file(path, &size);
    if (!data)
        return false;
    a->bytes = size;
    MapGenDigest_Sha256(data, size, a->sha256);

    if (MapGenBsp_Load(data, size, &a->bsp) != MAPGEN_BSP_OK) {
        free(data);
        return false;
    }
    free(data);

    if (MapGenGenome_Extract(a->bsp, &a->genome) != MAPGEN_GENOME_OK)
        return false;
    mapgen_space_params_t p = MapGenSpace_DefaultParams();
    if (MapGenSpace_Build(a->bsp, &p, &a->space) != MAPGEN_SPACE_OK)
        return false;
    if (MapGenWiring_Build(a->genome, a->bsp, &a->wiring) != MAPGEN_WIRING_OK)
        return false;
    return MapGenFeatures_Build(a->bsp, a->genome, a->space, a->wiring, &a->features)
           == MAPGEN_FEATURES_OK;
}

/* The map's own filename, which is what a qpath looks like in practice. */
static const char *basename_of(const char *path)
{
    const char *slash = strrchr(path, '/');
    const char *back = strrchr(path, '\\');
    const char *last = slash > back ? slash : back;
    return last ? last + 1 : path;
}

static mapgen_training_t *train(int argc, char **argv, int first, bool reverse)
{
    mapgen_training_t *t = MapGenTraining_Create();
    if (!t)
        return NULL;
    const int count = argc - first;
    for (int i = 0; i < count; i++) {
        const char *path = argv[first + (reverse ? count - 1 - i : i)];
        analysis_t a;
        if (!analyse(path, &a)) {
            free_analysis(&a);
            MapGenTraining_RejectSource(t, basename_of(path), "baseq2", 0,
                                        (const uint8_t *)
                                        "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0"
                                        "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0");
            continue;
        }
        MapGenTraining_AddSource(t, basename_of(path), "baseq2", a.bytes,
                                 a.sha256, a.features, a.genome, a.wiring,
                                 NULL, NULL);
        free_analysis(&a);
    }
    return t;
}

static uint64_t payload_of(mapgen_training_t *t, uint8_t out[MAPGEN_SHA256_BYTES])
{
    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
    if (!b)
        return 0;
    if (MapGenTraining_FillSnapshot(t, b, MAPGEN_COMPRESSION_DEFLATE)
        != MAPGEN_TRAINING_OK) {
        MapGenSnapshot_BuilderFree(b);
        return 0;
    }
    MapGenSnapshot_BuilderPayloadHash(b, out);
    uint8_t *bytes = NULL;
    size_t size = 0;
    MapGenSnapshot_Finish(b, &bytes, &size);
    MapGenSnapshot_BuilderFree(b);
    free(bytes);
    return size;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        printf("usage\n");
        return 2;
    }
    const char *mode = argv[1];

    if (!strcmp(mode, "shuffle")) {
        uint8_t forward[MAPGEN_SHA256_BYTES], backward[MAPGEN_SHA256_BYTES];
        mapgen_training_t *a = train(argc, argv, 2, false);
        mapgen_training_t *b = train(argc, argv, 2, true);
        if (!a || !b) {
            printf("TRAIN_FAILED\n");
            return 1;
        }
        payload_of(a, forward);
        payload_of(b, backward);
        char hex[MAPGEN_SHA256_HEX];
        MapGenDigest_Sha256Hex(forward, hex);
        printf("%s %s accepted %u duplicates %u\n",
               memcmp(forward, backward, MAPGEN_SHA256_BYTES) ? "DIVERGED" : "IDENTICAL",
               hex, MapGenTraining_NumAccepted(a), MapGenTraining_NumDuplicates(a));
        MapGenTraining_Free(a);
        MapGenTraining_Free(b);
        return 0;
    }

    /* `train` takes the snapshot path, `movement` takes it and a demo. */
    const int first_map = 2 + (!strcmp(mode, "train") ? 1 : 0)
                            + (!strcmp(mode, "movement") ? 3 : 0);
    mapgen_training_t *t = train(argc, argv, first_map, false);
    if (!t) {
        printf("TRAIN_FAILED\n");
        return 1;
    }

    if (!strcmp(mode, "train")) {
        mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
        const mapgen_training_result_t r =
            MapGenTraining_FillSnapshot(t, b, MAPGEN_COMPRESSION_DEFLATE);
        if (r != MAPGEN_TRAINING_OK) {
            printf("%s\n", MapGenTraining_ResultName(r));
            MapGenSnapshot_BuilderFree(b);
            MapGenTraining_Free(t);
            return 0;
        }
        uint8_t identity[MAPGEN_SNAPSHOT_UUID_BYTES];
        for (int i = 0; i < MAPGEN_SNAPSHOT_UUID_BYTES; i++)
            identity[i] = (uint8_t)(0xA0 + i);
        MapGenSnapshot_SetIdentity(b, identity, identity, NULL);
        MapGenSnapshot_SetProvenance(b, NULL, NULL, 1756600000000ull,
                                     MapGenTraining_NumSources(t));

        uint8_t *bytes = NULL;
        size_t size = 0;
        const mapgen_snapshot_result_t sr = MapGenSnapshot_Finish(b, &bytes, &size);
        MapGenSnapshot_BuilderFree(b);
        if (sr != MAPGEN_SNAPSHOT_OK) {
            printf("%s\n", MapGenSnapshot_ResultName(sr));
            MapGenTraining_Free(t);
            return 0;
        }
        FILE *f = fopen(argv[2], "wb");
        const bool ok = f && fwrite(bytes, 1, size, f) == size;
        if (f)
            fclose(f);
        free(bytes);
        printf("%s %zu sources %u accepted %u duplicates %u rejected %u "
               "materials %u lowdiv %d\n",
               ok ? "OK" : "WRITE_FAILED", size,
               MapGenTraining_NumSources(t), MapGenTraining_NumAccepted(t),
               MapGenTraining_NumDuplicates(t), MapGenTraining_NumRejected(t),
               MapGenTraining_NumMaterials(t),
               MapGenTraining_LowDiversity(t) ? 1 : 0);
    } else if (!strcmp(mode, "movement")) {
        /*
         * argv[2] is where the snapshot goes, argv[3] is the record the demo
         * ingester wrote, argv[4] is the physics it was read under, and the
         * maps came after that.
         */
        mapgen_demo_provenance_t prov;
        memset(&prov, 0, sizeof(prov));
        uint32_t cells = 0, jumps = 0, drops = 0, rides = 0;
        FILE *f = fopen(argv[3], "rb");
        if (!f) {
            printf("evidence UNREADABLE\n");
            MapGenTraining_Free(t);
            return 1;
        }
        char line[512];
        while (fgets(line, sizeof(line), f)) {
            char key[64], value[256];
            if (sscanf(line, "%63s %255[^\r\n]", key, value) != 2)
                continue;
            if (!strcmp(key, "map"))
                snprintf(prov.map, sizeof(prov.map), "%s", value);
            else if (!strcmp(key, "gamedir"))
                snprintf(prov.gamedir, sizeof(prov.gamedir), "%s", value);
            else if (!strcmp(key, "source"))
                snprintf(prov.source, sizeof(prov.source), "%s", value);
            else if (!strcmp(key, "digest"))
                snprintf(prov.digest, sizeof(prov.digest), "%s", value);
            else if (!strcmp(key, "protocol"))
                prov.protocol = atoi(value);
            else if (!strcmp(key, "pov"))
                prov.pov_slot = atoi(value);
            else if (!strcmp(key, "quality"))
                prov.quality = (uint32_t)strtoul(value, NULL, 10);
            else if (!strcmp(key, "duration_ms"))
                prov.duration_ms = atoi(value);
            else if (!strcmp(key, "samples"))
                prov.samples = (uint32_t)strtoul(value, NULL, 10);
            else if (!strcmp(key, "cells"))
                cells = (uint32_t)strtoul(value, NULL, 10);
            else if (!strcmp(key, "jumps"))
                jumps = (uint32_t)strtoul(value, NULL, 10);
            else if (!strcmp(key, "drops"))
                drops = (uint32_t)strtoul(value, NULL, 10);
            else if (!strcmp(key, "rides"))
                rides = (uint32_t)strtoul(value, NULL, 10);
        }
        fclose(f);
        printf("provenance %s %s protocol %d pov %d samples %u\n",
               prov.map, prov.gamedir, prov.protocol, prov.pov_slot,
               prov.samples);

        /*
         * Which source it is about.
         *
         * A demo carries the map's NAME and the corpus is held by the map's
         * HASH, so the two are joined by the source whose path ends in that
         * name. A demo of a map this corpus does not have finds nothing, and
         * the refusal below is the point of the exercise.
         */
        uint8_t sha[MAPGEN_SHA256_BYTES];
        memset(sha, 0, sizeof(sha));
        bool matched = false;
        for (uint32_t i = 0; i < MapGenTraining_NumSources(t) && !matched;
             i++) {
            mapgen_training_source_t src;
            if (!MapGenTraining_SourceAt(t, i, &src))
                continue;
            if (prov.map[0] && strstr(src.qpath, prov.map)) {
                memcpy(sha, src.sha256, MAPGEN_SHA256_BYTES);
                matched = true;
            }
        }
        printf("source %s\n", matched ? "found" : "unknown");

        const mapgen_training_result_t mr =
            MapGenTraining_AddMovement(t, sha, argv[4], &prov, cells, jumps,
                                       drops, rides, 0u);
        printf("movement %s, held %u\n", MapGenTraining_ResultName(mr),
               MapGenTraining_NumMovement(t));

        const size_t needed = MapGenTraining_ChunkText(t,
                                                       MAPGEN_CHUNK_MOVEMENT,
                                                       NULL, 0);
        char *text = malloc(needed + 1);
        if (text) {
            MapGenTraining_ChunkText(t, MAPGEN_CHUNK_MOVEMENT, text,
                                     needed + 1);
            printf("--- MOVEMENT\n");
            fwrite(text, 1, needed, stdout);
            free(text);
        }

        /* And into a snapshot, which is the only place it has to survive. */
        mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
        if (MapGenTraining_FillSnapshot(t, b, MAPGEN_COMPRESSION_DEFLATE)
            == MAPGEN_TRAINING_OK) {
            uint8_t identity[MAPGEN_SNAPSHOT_UUID_BYTES];
            for (int i = 0; i < MAPGEN_SNAPSHOT_UUID_BYTES; i++)
                identity[i] = (uint8_t)(0xA0 + i);
            MapGenSnapshot_SetIdentity(b, identity, identity, NULL);
            MapGenSnapshot_SetProvenance(b, NULL, NULL, 1756600000000ull,
                                         MapGenTraining_NumSources(t));
            uint8_t *bytes = NULL;
            size_t size = 0;
            if (MapGenSnapshot_Finish(b, &bytes, &size)
                == MAPGEN_SNAPSHOT_OK) {
                FILE *out = fopen(argv[2], "wb");
                if (out) {
                    fwrite(bytes, 1, size, out);
                    fclose(out);
                }
                mapgen_snapshot_t *snap = NULL;
                const mapgen_snapshot_result_t sr =
                    MapGenSnapshot_Open(bytes, size, &snap);
                printf("snapshot %s\n", MapGenSnapshot_ResultName(sr));
                if (sr == MAPGEN_SNAPSHOT_OK) {
                    size_t chunk_size = 0;
                    const uint8_t *chunk =
                        MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_MOVEMENT,
                                             &chunk_size);
                    printf("carried %zu bytes of movement\n",
                           chunk ? chunk_size : (size_t)0);
                }
                MapGenSnapshot_Free(snap);
            }
            free(bytes);
        }
        MapGenSnapshot_BuilderFree(b);
    } else if (!strcmp(mode, "chunks")) {
        for (uint32_t type = MAPGEN_CHUNK_META; type <= MAPGEN_CHUNK_QUALITY; type++) {
            printf("--- %s\n", MapGenSnapshot_ChunkTypeName(type));
            const size_t needed = MapGenTraining_ChunkText(t, type, NULL, 0);
            char *text = malloc(needed + 1);
            if (text) {
                MapGenTraining_ChunkText(t, type, text, needed + 1);
                fwrite(text, 1, needed, stdout);
                free(text);
            }
        }
    } else if (!strcmp(mode, "order")) {
        for (uint32_t i = 0; i < MapGenTraining_NumSources(t); i++) {
            mapgen_training_source_t src;
            if (!MapGenTraining_SourceAt(t, i, &src))
                continue;
            char hex[MAPGEN_SHA256_HEX];
            MapGenDigest_Sha256Hex(src.sha256, hex);
            printf("%s %s %s %s\n", hex, src.provider, src.qpath,
                   MapGenTraining_SourceStatusName(
                       (mapgen_source_status_t)src.status));
        }
    } else {
        printf("BAD_MODE\n");
    }

    MapGenTraining_Free(t);
    return 0;
}
