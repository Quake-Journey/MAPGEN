/*
 * MAPGEN-1 MapGenFeatures test driver.
 *
 * Compiled and run by tools/check_mapgen_features_contract.py.
 *
 *   driver text     <map.bsp>   the canonical feature vector
 *   driver digest   <map.bsp>   "OK <digest> <nodes> <loops> <cover>"
 *   driver bindings <map.bsp>   one line per positioned entity and its stance
 *   driver stable   <map.bsp>   build it twice, compare digests
 *   driver threads  <map.bsp> <n>   n threads compute it at once
 */

#include "common/mapgen_features.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <windows.h>

typedef struct {
    mapgen_bsp_t    *bsp;
    mapgen_genome_t *genome;
    mapgen_space_t  *space;
    mapgen_wiring_t *wiring;
} world_t;

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

static bool load_world(const char *path, world_t *w)
{
    memset(w, 0, sizeof(*w));
    size_t size = 0;
    uint8_t *data = read_file(path, &size);
    if (!data)
        return false;
    if (MapGenBsp_Load(data, size, &w->bsp) != MAPGEN_BSP_OK) {
        free(data);
        return false;
    }
    free(data);
    if (MapGenGenome_Extract(w->bsp, &w->genome) != MAPGEN_GENOME_OK)
        return false;
    mapgen_space_params_t p = MapGenSpace_DefaultParams();
    if (MapGenSpace_Build(w->bsp, &p, &w->space) != MAPGEN_SPACE_OK)
        return false;
    return MapGenWiring_Build(w->genome, w->bsp, &w->wiring) == MAPGEN_WIRING_OK;
}

static void free_world(world_t *w)
{
    MapGenWiring_Free(w->wiring);
    MapGenSpace_Free(w->space);
    MapGenGenome_Free(w->genome);
    MapGenBsp_Free(w->bsp);
}

typedef struct {
    const world_t *w;
    uint64_t       digest;
    int            ok;
} worker_arg_t;

static DWORD WINAPI worker_main(LPVOID param)
{
    worker_arg_t *arg = (worker_arg_t *)param;
    mapgen_features_t *f = NULL;
    if (MapGenFeatures_Build(arg->w->bsp, arg->w->genome, arg->w->space,
                             arg->w->wiring, &f) != MAPGEN_FEATURES_OK)
        return 1;
    arg->digest = MapGenFeatures_CanonicalDigest(f);
    arg->ok = 1;
    MapGenFeatures_Free(f);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        printf("usage\n");
        return 2;
    }
    const char *mode = argv[1];

    world_t w;
    if (!load_world(argv[2], &w)) {
        free_world(&w);
        printf("LOAD_FAILED\n");
        return 1;
    }

    if (!strcmp(mode, "threads")) {
        int threads = argc > 3 ? atoi(argv[3]) : 4;
        if (threads < 1) threads = 1;
        if (threads > 32) threads = 32;

        mapgen_features_t *base = NULL;
        if (MapGenFeatures_Build(w.bsp, w.genome, w.space, w.wiring, &base)
            != MAPGEN_FEATURES_OK) {
            printf("BUILD_FAILED\n");
            free_world(&w);
            return 1;
        }
        const uint64_t baseline = MapGenFeatures_CanonicalDigest(base);
        MapGenFeatures_Free(base);

        worker_arg_t *args = calloc((size_t)threads, sizeof(worker_arg_t));
        HANDLE *handles = calloc((size_t)threads, sizeof(HANDLE));
        for (int t = 0; t < threads; t++) {
            args[t].w = &w;
            handles[t] = CreateThread(NULL, 0, worker_main, &args[t], 0, NULL);
        }
        WaitForMultipleObjects((DWORD)threads, handles, TRUE, INFINITE);

        int diverged = 0, failed = 0;
        for (int t = 0; t < threads; t++) {
            if (handles[t])
                CloseHandle(handles[t]);
            if (!args[t].ok)
                failed++;
            else if (args[t].digest != baseline)
                diverged++;
        }
        printf("%s %d %d\n",
               failed ? "THREADS_FAILED" : (diverged ? "DIVERGED" : "IDENTICAL"),
               diverged, threads);
        free(handles);
        free(args);
        free_world(&w);
        return 0;
    }

    mapgen_features_t *f = NULL;
    const mapgen_features_result_t r =
        MapGenFeatures_Build(w.bsp, w.genome, w.space, w.wiring, &f);
    if (r != MAPGEN_FEATURES_OK) {
        printf("%s\n", MapGenFeatures_ResultName(r));
        free_world(&w);
        return 0;
    }
    const mapgen_features_vector_t *v = MapGenFeatures_Vector(f);

    if (!strcmp(mode, "text")) {
        size_t needed = MapGenFeatures_CanonicalText(f, NULL, 0);
        char *text = malloc(needed + 1);
        if (text) {
            MapGenFeatures_CanonicalText(f, text, needed + 1);
            fwrite(text, 1, needed, stdout);
            free(text);
        }
    } else if (!strcmp(mode, "digest")) {
        printf("OK %016llx nodes %u loops %u chokepoints %u bridges %u "
               "cover %u sight %u items %u unbound %u\n",
               (unsigned long long)MapGenFeatures_CanonicalDigest(f),
               v->nodes, v->loops, v->chokepoints, v->bridges,
               v->cover_permille, v->mean_sight_length,
               v->items_bound, v->unbound_entities);
    } else if (!strcmp(mode, "bindings")) {
        for (uint32_t i = 0; i < MapGenGenome_NumEntities(w.genome); i++) {
            const mapgen_entity_t *ent = MapGenGenome_Entity(w.genome, i);
            if (!ent->has_origin)
                continue;
            const uint32_t node = MapGenFeatures_EntityNode(f, i);
            printf("%s %d\n", ent->classname,
                   node == UINT32_MAX ? -1 : (int)node);
        }
    } else if (!strcmp(mode, "stable")) {
        const uint64_t first = MapGenFeatures_CanonicalDigest(f);
        mapgen_features_t *again = NULL;
        MapGenFeatures_Build(w.bsp, w.genome, w.space, w.wiring, &again);
        const uint64_t second = again ? MapGenFeatures_CanonicalDigest(again) : 0;
        printf("%s %016llx %016llx\n", first == second ? "STABLE" : "UNSTABLE",
               (unsigned long long)first, (unsigned long long)second);
        MapGenFeatures_Free(again);
    } else {
        printf("BAD_MODE\n");
    }

    MapGenFeatures_Free(f);
    free_world(&w);
    return 0;
}
