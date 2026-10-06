/*
 * MAPGEN-1 MapGenTraceContext test driver.
 *
 * Compiled and run by tools/check_mapgen_trace_contract.py.
 *
 *   driver trace       <map.bsp> <rays.txt>            one result line per ray
 *   driver concurrent  <map.bsp> <rays.txt> <threads>  same rays, N threads
 *   driver interleave  <mapA.bsp> <mapB.bsp> <rays.txt>
 *   driver rebind      <mapA.bsp> <mapB.bsp> <rays.txt>
 *
 * Rays come from a FILE rather than from an RNG in here, so the C and the
 * Python reference get bit-identical inputs and a disagreement can only mean a
 * disagreement about the algorithm.
 *
 * `concurrent` is the case the engine's own tracer could not pass: the same
 * work, on many threads, must produce exactly what one thread produced.
 */

#include "common/mapgen_trace.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <windows.h>

typedef struct {
    float   start[3];
    float   end[3];
    float   mins[3];
    float   maxs[3];
    int32_t mask;
} ray_t;

typedef struct {
    float   fraction;
    int     allsolid;
    int     startsolid;
    int32_t contents;
    int32_t surface_flags;
    float   endpos[3];
} answer_t;

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

static ray_t *read_rays(const char *path, size_t *out_count)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    size_t cap = 256, n = 0;
    ray_t *rays = malloc(cap * sizeof(ray_t));
    if (!rays) { fclose(f); return NULL; }
    char line[512];
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r')
            continue;
        ray_t r;
        int got = sscanf(line, "%f %f %f %f %f %f %f %f %f %f %f %f %d",
                         &r.start[0], &r.start[1], &r.start[2],
                         &r.end[0], &r.end[1], &r.end[2],
                         &r.mins[0], &r.mins[1], &r.mins[2],
                         &r.maxs[0], &r.maxs[1], &r.maxs[2],
                         &r.mask);
        if (got != 13)
            continue;
        if (n == cap) {
            cap *= 2;
            ray_t *grown = realloc(rays, cap * sizeof(ray_t));
            if (!grown) { free(rays); fclose(f); return NULL; }
            rays = grown;
        }
        rays[n++] = r;
    }
    fclose(f);
    *out_count = n;
    return rays;
}

static void run_one(mapgen_trace_context_t *ctx, const ray_t *r, answer_t *a)
{
    mapgen_trace_result_t out;
    MapGenTrace_Box(ctx, r->start, r->end, r->mins, r->maxs, r->mask, &out);
    a->fraction = out.fraction;
    a->allsolid = out.allsolid;
    a->startsolid = out.startsolid;
    a->contents = out.contents;
    a->surface_flags = out.surface_flags;
    memcpy(a->endpos, out.endpos, sizeof(a->endpos));
}

static void run_all(const mapgen_bsp_t *bsp, const ray_t *rays, size_t n, answer_t *out)
{
    mapgen_trace_context_t ctx = { 0 };
    if (!MapGenTrace_Bind(&ctx, bsp)) {
        memset(out, 0, n * sizeof(answer_t));
        return;
    }
    for (size_t i = 0; i < n; i++)
        run_one(&ctx, &rays[i], &out[i]);
    MapGenTrace_Release(&ctx);
}

/* ------------------------------------------------------------------ */

typedef struct {
    const mapgen_bsp_t *bsp;
    const ray_t        *rays;
    size_t              count;
    answer_t           *out;
    int                 ok;
} worker_arg_t;

static DWORD WINAPI worker_main(LPVOID param)
{
    worker_arg_t *arg = (worker_arg_t *)param;
    /* Each thread owns its context; that is the entire claim under test. */
    mapgen_trace_context_t ctx = { 0 };
    if (!MapGenTrace_Bind(&ctx, arg->bsp))
        return 1;
    for (size_t pass = 0; pass < 3; pass++)
        for (size_t i = 0; i < arg->count; i++)
            run_one(&ctx, &arg->rays[i], &arg->out[i]);
    MapGenTrace_Release(&ctx);
    arg->ok = 1;
    return 0;
}

static int answers_equal(const answer_t *a, const answer_t *b)
{
    return memcmp(a, b, sizeof(answer_t)) == 0;
}

static void print_answer(size_t i, const answer_t *a)
{
    printf("%zu %.9g %d %d %d %d %.9g %.9g %.9g\n",
           i, (double)a->fraction, a->allsolid, a->startsolid,
           a->contents, a->surface_flags,
           (double)a->endpos[0], (double)a->endpos[1], (double)a->endpos[2]);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        printf("usage\n");
        return 2;
    }
    const char *mode = argv[1];

    if (!strcmp(mode, "trace") && argc >= 4) {
        mapgen_bsp_t *bsp = load_bsp(argv[2]);
        if (!bsp) { printf("LOAD_FAILED\n"); return 1; }
        size_t n = 0;
        ray_t *rays = read_rays(argv[3], &n);
        if (!rays) { printf("RAYS_FAILED\n"); MapGenBsp_Free(bsp); return 1; }
        answer_t *ans = calloc(n ? n : 1, sizeof(answer_t));
        run_all(bsp, rays, n, ans);
        for (size_t i = 0; i < n; i++)
            print_answer(i, &ans[i]);
        free(ans); free(rays); MapGenBsp_Free(bsp);
        return 0;
    }

    if (!strcmp(mode, "concurrent") && argc >= 5) {
        mapgen_bsp_t *bsp = load_bsp(argv[2]);
        if (!bsp) { printf("LOAD_FAILED\n"); return 1; }
        size_t n = 0;
        ray_t *rays = read_rays(argv[3], &n);
        if (!rays) { printf("RAYS_FAILED\n"); MapGenBsp_Free(bsp); return 1; }
        int threads = atoi(argv[4]);
        if (threads < 1) threads = 1;
        if (threads > 64) threads = 64;

        answer_t *baseline = calloc(n ? n : 1, sizeof(answer_t));
        run_all(bsp, rays, n, baseline);

        worker_arg_t *args = calloc((size_t)threads, sizeof(worker_arg_t));
        HANDLE *handles = calloc((size_t)threads, sizeof(HANDLE));
        for (int t = 0; t < threads; t++) {
            args[t].bsp = bsp;
            args[t].rays = rays;
            args[t].count = n;
            args[t].out = calloc(n ? n : 1, sizeof(answer_t));
            handles[t] = CreateThread(NULL, 0, worker_main, &args[t], 0, NULL);
        }
        WaitForMultipleObjects((DWORD)threads, handles, TRUE, INFINITE);

        size_t diverged = 0;
        int spawn_failed = 0;
        for (int t = 0; t < threads; t++) {
            if (!handles[t] || !args[t].ok) { spawn_failed = 1; continue; }
            CloseHandle(handles[t]);
            for (size_t i = 0; i < n; i++)
                if (!answers_equal(&baseline[i], &args[t].out[i]))
                    diverged++;
            free(args[t].out);
        }
        if (spawn_failed)
            printf("THREADS_FAILED\n");
        else
            printf("%s %zu %zu %d\n", diverged ? "DIVERGED" : "IDENTICAL",
                   diverged, n, threads);
        free(handles); free(args); free(baseline); free(rays);
        MapGenBsp_Free(bsp);
        return 0;
    }

    /* Two contexts on two different documents, alternating ray by ray. If any
       state leaked out of the contexts, the answers would not match the two
       maps traced separately. */
    if (!strcmp(mode, "interleave") && argc >= 5) {
        mapgen_bsp_t *a = load_bsp(argv[2]);
        mapgen_bsp_t *b = load_bsp(argv[3]);
        if (!a || !b) { printf("LOAD_FAILED\n"); return 1; }
        size_t n = 0;
        ray_t *rays = read_rays(argv[4], &n);
        if (!rays) { printf("RAYS_FAILED\n"); return 1; }

        answer_t *sa = calloc(n ? n : 1, sizeof(answer_t));
        answer_t *sb = calloc(n ? n : 1, sizeof(answer_t));
        run_all(a, rays, n, sa);
        run_all(b, rays, n, sb);

        mapgen_trace_context_t ca = { 0 }, cb = { 0 };
        MapGenTrace_Bind(&ca, a);
        MapGenTrace_Bind(&cb, b);
        size_t diverged = 0;
        for (size_t i = 0; i < n; i++) {
            answer_t ia, ib;
            run_one(&ca, &rays[i], &ia);
            run_one(&cb, &rays[i], &ib);
            if (!answers_equal(&ia, &sa[i])) diverged++;
            if (!answers_equal(&ib, &sb[i])) diverged++;
        }
        MapGenTrace_Release(&ca);
        MapGenTrace_Release(&cb);
        printf("%s %zu %zu\n", diverged ? "DIVERGED" : "IDENTICAL", diverged, n);
        free(sa); free(sb); free(rays);
        MapGenBsp_Free(a); MapGenBsp_Free(b);
        return 0;
    }

    /* One context, rebound from a big map to a small one and back. A stamp
       array sized for the big map must not let the small map read past its
       own brushes, and a stale generation must not hide brushes. */
    if (!strcmp(mode, "rebind") && argc >= 5) {
        mapgen_bsp_t *a = load_bsp(argv[2]);
        mapgen_bsp_t *b = load_bsp(argv[3]);
        if (!a || !b) { printf("LOAD_FAILED\n"); return 1; }
        size_t n = 0;
        ray_t *rays = read_rays(argv[4], &n);
        if (!rays) { printf("RAYS_FAILED\n"); return 1; }

        answer_t *sa = calloc(n ? n : 1, sizeof(answer_t));
        answer_t *sb = calloc(n ? n : 1, sizeof(answer_t));
        run_all(a, rays, n, sa);
        run_all(b, rays, n, sb);

        mapgen_trace_context_t ctx = { 0 };
        size_t diverged = 0;
        for (int round = 0; round < 3; round++) {
            MapGenTrace_Bind(&ctx, a);
            for (size_t i = 0; i < n; i++) {
                answer_t got;
                run_one(&ctx, &rays[i], &got);
                if (!answers_equal(&got, &sa[i])) diverged++;
            }
            MapGenTrace_Bind(&ctx, b);
            for (size_t i = 0; i < n; i++) {
                answer_t got;
                run_one(&ctx, &rays[i], &got);
                if (!answers_equal(&got, &sb[i])) diverged++;
            }
        }
        MapGenTrace_Release(&ctx);
        printf("%s %zu %zu\n", diverged ? "DIVERGED" : "IDENTICAL", diverged, n);
        free(sa); free(sb); free(rays);
        MapGenBsp_Free(a); MapGenBsp_Free(b);
        return 0;
    }

    printf("BAD_MODE\n");
    return 2;
}
