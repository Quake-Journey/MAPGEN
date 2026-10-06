/*
 * MAPGEN-1 MapGenSpace test driver.
 *
 * Compiled and run by tools/check_mapgen_space_contract.py.
 *
 *   driver summary  <map.bsp> [cell]   one line of counts plus the digest
 *   driver text     <map.bsp> [cell]   the canonical text
 *   driver regions  <map.bsp> [cell]   one line per region
 *   driver stable   <map.bsp> [cell]   build it twice, compare digests
 *   driver threads  <map.bsp> <n>      n threads build it at once
 *   driver cells    <map.bsp>          every legal and illegal cell size
 *
 * `threads` is the claim MapGenTraceContext was written for: the whole graph,
 * built concurrently, must come out byte-identical.
 */

#include "common/mapgen_space.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <windows.h>

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

static mapgen_bsp_t *load_bsp(const char *path)
{
    size_t size = 0;
    uint8_t *data = read_file(path, &size);
    if (!data)
        return NULL;
    mapgen_bsp_t *bsp = NULL;
    mapgen_bsp_result_t r = MapGenBsp_Load(data, size, &bsp);
    free(data);
    return (r == MAPGEN_BSP_OK) ? bsp : NULL;
}

static mapgen_space_params_t params_for(int argc, char **argv, int index)
{
    mapgen_space_params_t p = MapGenSpace_DefaultParams();
    if (argc > index)
        p.cell = atoi(argv[index]);
    return p;
}

typedef struct {
    const mapgen_bsp_t   *bsp;
    mapgen_space_params_t params;
    uint64_t              digest;
    uint32_t              nodes;
    uint32_t              edges;
    int                   ok;
} worker_arg_t;

static DWORD WINAPI worker_main(LPVOID param)
{
    worker_arg_t *arg = (worker_arg_t *)param;
    mapgen_space_t *sp = NULL;
    if (MapGenSpace_Build(arg->bsp, &arg->params, &sp) != MAPGEN_SPACE_OK)
        return 1;
    arg->digest = MapGenSpace_CanonicalDigest(sp);
    arg->nodes = MapGenSpace_NumNodes(sp);
    arg->edges = MapGenSpace_NumEdges(sp);
    arg->ok = 1;
    MapGenSpace_Free(sp);
    return 0;
}

static void print_summary(const mapgen_space_t *sp)
{
    const uint32_t largest = MapGenSpace_LargestRegion(sp);
    const mapgen_space_region_t *rg = MapGenSpace_Region(sp, largest);
    printf("OK %016llx cell %d nodes %u edges %u regions %u "
           "walk %u step %u jump %u fall %u swim %u largest %u\n",
           (unsigned long long)MapGenSpace_CanonicalDigest(sp),
           MapGenSpace_CellSize(sp),
           MapGenSpace_NumNodes(sp), MapGenSpace_NumEdges(sp),
           MapGenSpace_NumRegions(sp),
           MapGenSpace_NumEdgesOfKind(sp, MAPGEN_EDGE_WALK),
           MapGenSpace_NumEdgesOfKind(sp, MAPGEN_EDGE_STEP),
           MapGenSpace_NumEdgesOfKind(sp, MAPGEN_EDGE_JUMP),
           MapGenSpace_NumEdgesOfKind(sp, MAPGEN_EDGE_FALL),
           MapGenSpace_NumEdgesOfKind(sp, MAPGEN_EDGE_SWIM),
           rg ? rg->nodes : 0);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        printf("usage\n");
        return 2;
    }
    const char *mode = argv[1];
    mapgen_bsp_t *bsp = load_bsp(argv[2]);
    if (!bsp) {
        printf("LOAD_FAILED\n");
        return 1;
    }

    int rc = 0;

    if (!strcmp(mode, "cells")) {
        /* Every cell size the header allows, and the two that bracket it. */
        static const int sizes[] = { 0, 8, 15, 16, 32, 64, 256, 257, 1024, -32 };
        for (size_t i = 0; i < sizeof(sizes) / sizeof(sizes[0]); i++) {
            mapgen_space_params_t p = MapGenSpace_DefaultParams();
            p.cell = sizes[i];
            mapgen_space_t *sp = NULL;
            mapgen_space_result_t r = MapGenSpace_Build(bsp, &p, &sp);
            printf("cell %d -> %s nodes %u\n", sizes[i],
                   MapGenSpace_ResultName(r), sp ? MapGenSpace_NumNodes(sp) : 0u);
            MapGenSpace_Free(sp);
        }
        MapGenBsp_Free(bsp);
        return 0;
    }

    if (!strcmp(mode, "threads")) {
        int threads = argc > 3 ? atoi(argv[3]) : 4;
        if (threads < 1) threads = 1;
        if (threads > 32) threads = 32;

        mapgen_space_t *sp = NULL;
        mapgen_space_params_t p = MapGenSpace_DefaultParams();
        if (MapGenSpace_Build(bsp, &p, &sp) != MAPGEN_SPACE_OK) {
            printf("BUILD_FAILED\n");
            MapGenBsp_Free(bsp);
            return 1;
        }
        const uint64_t baseline = MapGenSpace_CanonicalDigest(sp);
        const uint32_t nodes = MapGenSpace_NumNodes(sp);
        MapGenSpace_Free(sp);

        worker_arg_t *args = calloc((size_t)threads, sizeof(worker_arg_t));
        HANDLE *handles = calloc((size_t)threads, sizeof(HANDLE));
        for (int t = 0; t < threads; t++) {
            args[t].bsp = bsp;
            args[t].params = p;
            handles[t] = CreateThread(NULL, 0, worker_main, &args[t], 0, NULL);
        }
        WaitForMultipleObjects((DWORD)threads, handles, TRUE, INFINITE);

        int diverged = 0, failed = 0;
        for (int t = 0; t < threads; t++) {
            if (handles[t])
                CloseHandle(handles[t]);
            if (!args[t].ok)
                failed++;
            else if (args[t].digest != baseline || args[t].nodes != nodes)
                diverged++;
        }
        if (failed)
            printf("THREADS_FAILED %d\n", failed);
        else
            printf("%s %d %d nodes %u\n", diverged ? "DIVERGED" : "IDENTICAL",
                   diverged, threads, nodes);
        free(handles);
        free(args);
        MapGenBsp_Free(bsp);
        return 0;
    }

    mapgen_space_params_t p = params_for(argc, argv, 3);
    mapgen_space_t *sp = NULL;
    mapgen_space_result_t r = MapGenSpace_Build(bsp, &p, &sp);
    if (r != MAPGEN_SPACE_OK) {
        printf("%s\n", MapGenSpace_ResultName(r));
        MapGenBsp_Free(bsp);
        return 0;
    }

    if (!strcmp(mode, "summary")) {
        print_summary(sp);
    } else if (!strcmp(mode, "text")) {
        size_t needed = MapGenSpace_CanonicalText(sp, NULL, 0);
        char *text = malloc(needed + 1);
        if (text) {
            MapGenSpace_CanonicalText(sp, text, needed + 1);
            fwrite(text, 1, needed, stdout);
            free(text);
        }
    } else if (!strcmp(mode, "regions")) {
        for (uint32_t i = 0; i < MapGenSpace_NumRegions(sp); i++) {
            const mapgen_space_region_t *rg = MapGenSpace_Region(sp, i);
            printf("region %u nodes %u box %d,%d,%d..%d,%d,%d liquid %u hazard %u thin %u\n",
                   i, rg->nodes, rg->mins[0], rg->mins[1], rg->mins[2],
                   rg->maxs[0], rg->maxs[1], rg->maxs[2],
                   rg->liquid_nodes, rg->hazard_nodes, rg->thin_nodes);
        }
    } else if (!strcmp(mode, "stable")) {
        const uint64_t first = MapGenSpace_CanonicalDigest(sp);
        mapgen_space_t *again = NULL;
        MapGenSpace_Build(bsp, &p, &again);
        const uint64_t second = again ? MapGenSpace_CanonicalDigest(again) : 0;
        printf("%s %016llx %016llx\n", first == second ? "STABLE" : "UNSTABLE",
               (unsigned long long)first, (unsigned long long)second);
        MapGenSpace_Free(again);
    } else {
        printf("BAD_MODE\n");
        rc = 2;
    }

    MapGenSpace_Free(sp);
    MapGenBsp_Free(bsp);
    return rc;
}
