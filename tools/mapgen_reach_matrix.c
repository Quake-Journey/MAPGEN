/*
 * One walk, told exactly how many threads to use, and what came out of it.
 *
 *     mapgen_reach_matrix MAP.bsp [--workers N] [--budget N]
 *                         [--cancel-after N] [--quiet] [--noreuse]
 *
 * The point is the digests. A sequential reference and a parallel run of the
 * same map must produce the same graph digest, the same certificate text and
 * the same report - not similar numbers, the same digest. Everything else it
 * prints is there so a difference can be looked into rather than only
 * detected.
 *
 * `--cancel-after N` answers the other half: a token that says stop after N
 * questions, so that cancellation can be shown to stop a walk rather than to
 * be checked and ignored.
 *
 * `--concurrent MAP2 [MAP3 ...]` answers a third: several walks running at the
 * same time in one process, each on its own thread and each with its own pool
 * of workers. The same digests as running them one at a time, or the walks are
 * treading on each other. Naming the same map twice is the sharpest form of
 * it - two walks over identical data, which is where a shared buffer shows
 * first.
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_reach.h"
#include "common/mapgen_certificate.h"
#include "common/mapgen_digest.h"
#include "common/q2prox_cpu_topology.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <process.h>
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* Enough for the guard's cases and small enough to keep on the stack. */
#define MAX_CONCURRENT 8

/*
 * The token is asked from the walk's worker threads as well as from the run
 * itself, so the counter it keeps is atomic. A plain increment here would be a
 * data race in the very test that exists to prove the walk has none.
 */
static volatile long s_asked;
static long s_stop_after = -1;

static bool cancel_asked(void *user)
{
    (void)user;
    const long seen = __atomic_add_fetch(&s_asked, 1, __ATOMIC_RELAXED);
    return s_stop_after >= 0 && seen > s_stop_after;
}

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

/*
 * What a finished walk IS, in two digests.
 *
 * Shared by the single walk and by the concurrent one so that the two print
 * the same facts - a concurrent run that agreed with a solo run because they
 * were described differently would prove nothing.
 */
static void describe(const mapgen_reach_t *reach, char *graph,
                     char *cert_hex, size_t *cert_bytes)
{
    MapGenReach_GraphDigest(reach, graph);
    const mapgen_certificate_set_t *set = MapGenReach_Certificates(reach);
    char *text = malloc(65536);
    if (!text) {
        cert_hex[0] = '\0';
        *cert_bytes = 0;
        return;
    }
    const size_t need = MapGenCertificate_Render(set, text, 65536);
    uint8_t cert_digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(text, need < 65536 ? need : 65535, cert_digest);
    MapGenDigest_Sha256Hex(cert_digest, cert_hex);
    *cert_bytes = need;
    free(text);
}

/*
 * One walk on its own thread, so several can be in flight at once.
 *
 * Everything it needs is in its own slot: its own file, its own BSP, its own
 * graph. Nothing is shared but the module under test, which is the point.
 */
typedef struct {
    const char            *path;
    mapgen_reach_options_t options;
    uint32_t               budget;
    mapgen_reach_result_t  rc;
    char                   graph[65];
    char                   cert_hex[MAPGEN_SHA256_HEX];
    size_t                 cert_bytes;
    uint32_t               states;
} slot_t;

static void run_slot(slot_t *s)
{
    mapgen_bsp_t *bsp = load(s->path);
    if (!bsp) {
        s->rc = MAPGEN_REACH_ERR_ARGS;
        return;
    }
    mapgen_reach_t *reach = NULL;
    s->rc = MapGenReach_ExploreWith(bsp, s->budget, &s->options, &reach);
    if (s->rc == MAPGEN_REACH_OK && reach) {
        describe(reach, s->graph, s->cert_hex, &s->cert_bytes);
        s->states = MapGenReach_NumStates(reach);
    }
    MapGenReach_Free(reach);
    MapGenBsp_Free(bsp);
}

#ifdef _WIN32
static unsigned __stdcall slot_thread(void *arg)
{
    run_slot((slot_t *)arg);
    return 0;
}
#endif

int main(int argc, char **argv)
{
    const char *path = NULL;
    mapgen_reach_options_t options;
    memset(&options, 0, sizeof(options));
    uint32_t budget = 200000;
    bool quiet = false;
    const char *extra_paths[MAX_CONCURRENT];
    int concurrent = 0;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--workers") && i + 1 < argc)
            options.workers = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--budget") && i + 1 < argc)
            budget = (uint32_t)strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--cancel-after") && i + 1 < argc)
            s_stop_after = strtol(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--concurrent")) {
            /* Everything after it that is not another flag is one more map to
               walk beside the first. */
            while (i + 1 < argc && argv[i + 1][0] != '-'
                   && concurrent < MAX_CONCURRENT)
                extra_paths[concurrent++] = argv[++i];
        }
        else if (!strcmp(argv[i], "--quiet"))
            quiet = true;
        else if (!strcmp(argv[i], "--noreuse"))
            options.no_round_reuse = true;     /* row 331: the reference walk */
        else if (!path)
            path = argv[i];
    }
    if (!path) {
        fprintf(stderr, "usage: %s MAP.bsp [--workers N] [--budget N]"
                        " [--cancel-after N]\n", argv[0]);
        return 2;
    }
    if (s_stop_after >= 0) {
        options.cancel.asked = cancel_asked;
        options.cancel.user = NULL;
    }

    /*
     * Several walks at once, or one.
     *
     * The concurrent path returns before the single one begins: the two answer
     * different questions and mixing their output would only make both harder
     * to read.
     */
    if (concurrent) {
        slot_t slots[MAX_CONCURRENT + 1];
        memset(slots, 0, sizeof(slots));
        const int total = concurrent + 1;
        for (int i = 0; i < total; i++) {
            slots[i].path = i ? extra_paths[i - 1] : path;
            slots[i].options = options;
            slots[i].budget = budget;
            slots[i].rc = MAPGEN_REACH_ERR_ARGS;
        }
#ifdef _WIN32
        HANDLE threads[MAX_CONCURRENT + 1];
        int started_count = 0;
        for (int i = 0; i < total; i++) {
            threads[i] = (HANDLE)_beginthreadex(NULL, 8u * 1024u * 1024u,
                                                slot_thread, &slots[i], 0,
                                                NULL);
            if (!threads[i]) {
                /* Fail rather than quietly walk this one in line with the
                   others: a serialized run is not the thing being tested. */
                fprintf(stderr, "cannot start walk %d\n", i);
                for (int k = 0; k < started_count; k++) {
                    WaitForSingleObject(threads[k], INFINITE);
                    CloseHandle(threads[k]);
                }
                return 2;
            }
            started_count++;
        }
        for (int i = 0; i < total; i++) {
            WaitForSingleObject(threads[i], INFINITE);
            CloseHandle(threads[i]);
        }
#else
        for (int i = 0; i < total; i++)
            run_slot(&slots[i]);
#endif
        int bad = 0;
        for (int i = 0; i < total; i++) {
            printf("concurrent %d map %s\n", i, slots[i].path);
            printf("concurrent %d result %s\n", i,
                   MapGenReach_ResultName(slots[i].rc));
            printf("concurrent %d graph %s\n", i, slots[i].graph);
            printf("concurrent %d states %u\n", i, slots[i].states);
            printf("concurrent %d certificates %zu bytes %s\n", i,
                   slots[i].cert_bytes, slots[i].cert_hex);
            if (slots[i].rc != MAPGEN_REACH_OK)
                bad++;
        }
        printf("concurrent walks %d\n", total);
        return bad ? 1 : 0;
    }

    mapgen_bsp_t *bsp = load(path);
    if (!bsp)
        return 2;

    const clock_t started = clock();
    mapgen_reach_t *reach = NULL;
    const mapgen_reach_result_t rc =
        MapGenReach_ExploreWith(bsp, budget, &options, &reach);
    const double ms = 1000.0 * (double)(clock() - started) / CLOCKS_PER_SEC;

    printf("map %s\n", path);
    printf("workers asked %d, performance-class logical cpus %d\n",
           options.workers, Q2PROX_Cpu_PerformanceCount());
    printf("result %s\n", MapGenReach_ResultName(rc));
    printf("cancel asked %ld times\n", s_asked);
    printf("elapsed %.0f ms\n", ms);

    if (rc == MAPGEN_REACH_OK && reach) {
        char digest[65];
        char cert_hex_single[MAPGEN_SHA256_HEX];
        size_t cert_bytes_single = 0;
        describe(reach, digest, cert_hex_single, &cert_bytes_single);
        const mapgen_reach_report_t *r = MapGenReach_Report(reach);
        printf("graph %s\n", digest);
        printf("states %u edges-implied-by %u\n", MapGenReach_NumStates(reach),
               r->edges);
        printf("report spawns %u stranded %u component %u reachable %u "
               "trapped %u lethal %u\n", r->spawns, r->spawns_stranded,
               r->component, r->reachable, r->trapped, r->trapped_lethal);
        printf("report movers %u open %u inoperable %u rounds %u\n",
               r->movers, r->movers_open, r->movers_inoperable, r->rounds);
        /* How wide the search got: the fixture's claim to exercise the
           parallel path, stated as a number rather than argued. */
        printf("report levels %u wide %u\n", r->levels, r->levels_wide);
        printf("report simulated %u reused %u\n", r->simulated, r->reused);
        printf("report items %u unreachable %u special %u\n", r->items,
               r->items_unreachable, r->items_special);
        printf("report landmarks %u unreachable %u\n", r->landmarks,
               r->landmarks_unreachable);

        /*
         * By their BYTES, not by how many. A byte count is not an identity:
         * two different witnesses can render to the same length. Computed by
         * describe(), which is what the concurrent walks use too.
         */
        printf("certificates %zu bytes %s\n", cert_bytes_single,
               cert_hex_single);

        /* And the three report fields the printout used to leave out, which a
           difference could have hidden in. */
        printf("report worst_trap %.6f %.6f %.6f\n", (double)r->worst_trap[0],
               (double)r->worst_trap[1], (double)r->worst_trap[2]);
        printf("report worst_item %.6f %.6f %.6f\n", (double)r->worst_item[0],
               (double)r->worst_item[1], (double)r->worst_item[2]);
        printf("report worst_landmark %.6f %.6f %.6f\n",
               (double)r->worst_landmark[0], (double)r->worst_landmark[1],
               (double)r->worst_landmark[2]);
        if (!quiet && cert_bytes_single) {
            const mapgen_certificate_set_t *set =
                MapGenReach_Certificates(reach);
            char *text = malloc(65536);
            if (text) {
                const size_t need = MapGenCertificate_Render(set, text, 65536);
                if (need && need < 65536)
                    fputs(text, stdout);
                free(text);
            }
        }
    }

    MapGenReach_Free(reach);
    MapGenBsp_Free(bsp);
    if (rc == MAPGEN_REACH_OK)
        return 0;
    return rc == MAPGEN_REACH_CANCELLED ? 3 : 1;
}
