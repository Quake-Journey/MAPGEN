/*
 * MAPGEN-1 Controller - self-asserting test against a REAL worker.
 *
 * Compiled and run by tools/check_mapgen_controller_contract.py.
 *
 * usage: mapgen_controller_driver <worker-exe> <work-dir>
 *
 * The off-state cases run with no worker at all; the rest launch the real
 * helper, because "the Controller stops the worker when the job ends" is not
 * something an in-process seam can answer.
 */

#include "common/mapgen.h"
#include "common/mapgen_process.h"

#include <stdio.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

static int g_cases;
static int g_failed;

static void ck(const char *name, bool ok, const char *detail)
{
    g_cases++;
    if (ok)
        printf("  PASS  %s\n", name);
    else {
        printf("  FAIL  %s%s%s\n", name, detail && *detail ? "  -- " : "", detail ? detail : "");
        g_failed++;
    }
}

static const char *g_worker;
static const char *g_crash_worker;
static const char *g_summary_worker;
static const char *g_publish_worker;
static const char *g_thin_worker;
static const char *g_dir;

static mapgen_t *make_with(const char *worker)
{
    mapgen_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.worker_exe_path = worker;
    cfg.work_dir = g_dir;
    cfg.expected_build_id = "q2prox-mapgen-worker-1";
    cfg.handshake_timeout_ms = 4000;
    return MapGen_Create(&cfg);
}

static mapgen_t *make(void)
{
    mapgen_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.worker_exe_path = g_worker;
    cfg.work_dir = g_dir;
    cfg.expected_build_id = "q2prox-mapgen-worker-1";
    cfg.handshake_timeout_ms = 4000;
    return MapGen_Create(&cfg);
}

static bool pump_until_terminal(mapgen_t *m, mapgen_job_id_t id, int max_ticks,
                                mapgen_job_view_t *out)
{
    for (int i = 0; i < max_ticks; i++) {
        MapGen_Tick(m);
        mapgen_observation_t obs;
        if (!MapGen_Observe(m, id, 0, &obs))
            return false;
        if (obs.view.terminal) {
            if (out)
                *out = obs.view;
            return true;
        }
#ifdef _WIN32
        Sleep(5);
#endif
    }
    mapgen_observation_t obs;
    if (MapGen_Observe(m, id, 0, &obs) && out)
        *out = obs.view;
    return false;
}

/* ------------------------------------------------------------------------ */

static void test_off_state(void)
{
    printf("\n=== off-state costs nothing\n");
    mapgen_t *m = make();
    ck("the Controller is created", m != NULL, "");
    ck("creating it starts no worker", !MapGen_HasWorker(m), "");
    ck("it has no active job", MapGen_ActiveJob(m) == MAPGEN_JOB_ID_NONE, "");

    for (int i = 0; i < 100; i++)
        MapGen_Tick(m);
    ck("ticking an idle Controller starts nothing", !MapGen_HasWorker(m), "");
    ck("ticking an idle Controller creates no job", MapGen_ActiveJob(m) == MAPGEN_JOB_ID_NONE, "");

    mapgen_observation_t obs;
    ck("observing an unknown job fails", !MapGen_Observe(m, 12345, 0, &obs), "");
    ck("cancelling an unknown job says so",
       MapGen_Cancel(m, 12345) == MAPGEN_CANCEL_UNKNOWN_JOB, "");

    MapGen_Destroy(m);
    ck("destroying an idle Controller is safe", true, "");
}

static void test_controller_local_job(void)
{
    printf("\n=== a Controller-local job never launches a worker\n");
    mapgen_t *m = make();
    mapgen_request_t req;
    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;

    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_DISCOVER;
    ck("discovery is accepted", MapGen_Submit(m, &req, &id) == MAPGEN_SUBMIT_ACCEPTED, "");
    ck("discovery got a job id", id != MAPGEN_JOB_ID_NONE, "");
    ck("discovery launched no worker", !MapGen_HasWorker(m),
       "discovery, preflight, recovery and the snapshot library never cross the IPC");

    mapgen_observation_t obs;
    ck("the job is observable", MapGen_Observe(m, id, 0, &obs), "");
    ck("it starts QUEUED", obs.view.state == MAPGEN_STATE_QUEUED, MapGenState_Name(obs.view.state));

    MapGen_Destroy(m);
}

static void test_worker_job(void)
{
    printf("\n=== a worker job launches, runs and releases\n");
    mapgen_t *m = make();
    mapgen_request_t req;
    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;

    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_VALIDATE;
    ck("validate is accepted", MapGen_Submit(m, &req, &id) == MAPGEN_SUBMIT_ACCEPTED, "");
    ck("a worker now exists", MapGen_HasWorker(m), "");

    mapgen_observation_t obs;
    MapGen_Observe(m, id, 0, &obs);
    ck("the job left QUEUED", obs.view.state != MAPGEN_STATE_QUEUED, MapGenState_Name(obs.view.state));

    /* Drain progress. The worker stages a result and stops; the Controller
       must NOT call that success. */
    bool saw_progress = false;
    for (int i = 0; i < 200; i++) {
        MapGen_Tick(m);
        if (MapGen_Observe(m, id, 0, &obs) && obs.view.percent > 0)
            saw_progress = true;
        if (obs.view.terminal)
            break;
#ifdef _WIN32
        Sleep(5);
#endif
    }
    ck("progress reached the Controller", saw_progress, "");
    ck("a staged result is NOT reported as success",
       !(obs.view.terminal && obs.view.state == MAPGEN_STATE_SUCCEEDED),
       "STAGED_RESULT is not success; the Controller commits (contract 5.1)");

    MapGen_Destroy(m);
    ck("destroy releases the worker", true, "");
}

static void test_busy(void)
{
    printf("\n=== one foreground job\n");
    mapgen_t *m = make();
    mapgen_request_t req;
    mapgen_job_id_t a = MAPGEN_JOB_ID_NONE, b = MAPGEN_JOB_ID_NONE;

    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_VALIDATE;
    ck("the first job is accepted", MapGen_Submit(m, &req, &a) == MAPGEN_SUBMIT_ACCEPTED, "");
    ck("the second is BUSY", MapGen_Submit(m, &req, &b) == MAPGEN_SUBMIT_BUSY, "");
    ck("the refused submit yields no id", b == MAPGEN_JOB_ID_NONE, "");
    ck("only one worker exists", MapGen_HasWorker(m), "");
    MapGen_Destroy(m);
}

static void test_cancel(void)
{
    printf("\n=== cancellation reaches the worker\n");
    mapgen_t *m = make();
    mapgen_request_t req;
    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;

    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_TRAIN;
    MapGen_Submit(m, &req, &id);

    /* Let it start reporting, then cancel. */
    for (int i = 0; i < 10; i++) {
        MapGen_Tick(m);
#ifdef _WIN32
        Sleep(5);
#endif
    }
    ck("cancel is accepted", MapGen_Cancel(m, id) == MAPGEN_CANCEL_ACCEPTED, "");
    ck("a second cancel says ALREADY_CANCELLING",
       MapGen_Cancel(m, id) == MAPGEN_CANCEL_ALREADY_CANCELLING, "");

    mapgen_job_view_t view;
    memset(&view, 0, sizeof(view));
    bool terminal = pump_until_terminal(m, id, 400, &view);
    ck("the job reaches a terminal state", terminal, MapGenState_Name(view.state));
    ck("that state is CANCELLED", view.state == MAPGEN_STATE_CANCELLED, MapGenState_Name(view.state));
    ck("the worker was released with the job", !MapGen_HasWorker(m), "");
    ck("the Controller is free again", MapGen_ActiveJob(m) == MAPGEN_JOB_ID_NONE, "");
    ck("cancel after terminal says ALREADY_TERMINAL",
       MapGen_Cancel(m, id) == MAPGEN_CANCEL_ALREADY_TERMINAL, "");

    /* And a new job can start. */
    mapgen_job_id_t next = MAPGEN_JOB_ID_NONE;
    ck("a new job is accepted after cancellation",
       MapGen_Submit(m, &req, &next) == MAPGEN_SUBMIT_ACCEPTED, "");
    ck("the new job has a different id", next != id, "");
    MapGen_Destroy(m);
}

static void test_missing_worker(void)
{
    printf("\n=== a worker that cannot be launched still ends its job\n");
    mapgen_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.worker_exe_path = "O:\\Claude2\\_agent_temp\\claude\\definitely-not-here.exe";
    cfg.work_dir = g_dir;
    cfg.expected_build_id = "q2prox-mapgen-worker-1";
    cfg.handshake_timeout_ms = 1000;

    mapgen_t *m = MapGen_Create(&cfg);
    ck("the Controller is created even with a bad worker path", m != NULL,
       "creating it must not touch the filesystem");
    ck("still no worker", !MapGen_HasWorker(m), "");

    mapgen_request_t req;
    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_TRAIN;
    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    ck("the submit is still accepted", MapGen_Submit(m, &req, &id) == MAPGEN_SUBMIT_ACCEPTED,
       "the job must exist so it can emit its one terminal event");

    mapgen_observation_t obs;
    ck("the job is observable", MapGen_Observe(m, id, 0, &obs), "");
    ck("it terminated", obs.view.terminal, MapGenState_Name(obs.view.state));
    ck("it terminated as FAILED", obs.view.state == MAPGEN_STATE_FAILED,
       MapGenState_Name(obs.view.state));
    ck("no worker was left behind", !MapGen_HasWorker(m), "");
    ck("the Controller is free", MapGen_ActiveJob(m) == MAPGEN_JOB_ID_NONE, "");

    /* Exactly one terminal event, even on this path. */
    int terminal_events = 0;
    for (uint32_t i = 0; i < obs.event_count; i++) {
        if (obs.events[i].kind == MAPGEN_EVENT_STATE &&
            MapGenState_IsTerminal(obs.events[i].state))
            terminal_events++;
    }
    ck("exactly one terminal event", terminal_events == 1, "");

    MapGen_Destroy(m);
}

static void test_observe_cursor(void)
{
    printf("\n=== Observe is a cursor\n");
    mapgen_t *m = make();
    mapgen_request_t req;
    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_VALIDATE;
    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    MapGen_Submit(m, &req, &id);

    for (int i = 0; i < 40; i++) {
        MapGen_Tick(m);
#ifdef _WIN32
        Sleep(2);
#endif
    }

    mapgen_observation_t first;
    ck("observe from zero returns events", MapGen_Observe(m, id, 0, &first) && first.event_count > 0, "");

    uint64_t cursor = first.events[first.event_count - 1].sequence;
    mapgen_observation_t second;
    MapGen_Observe(m, id, cursor, &second);
    bool all_after = true;
    for (uint32_t i = 0; i < second.event_count; i++) {
        if (second.events[i].sequence <= cursor)
            all_after = false;
    }
    ck("a cursor returns only later events", all_after, "");
    ck("the view is carried with the events", second.view.id == id, "");

    MapGen_Destroy(m);
}

static void test_worker_crash(void)
{
    printf("\n=== a worker that dies mid-job\n");
    if (!g_crash_worker) {
        ck("a crashing worker binary was supplied", false, "third argument missing");
        return;
    }
    mapgen_t *m = make_with(g_crash_worker);
    mapgen_request_t req;
    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_VALIDATE;
    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    ck("the job is accepted", MapGen_Submit(m, &req, &id) == MAPGEN_SUBMIT_ACCEPTED, "");

    mapgen_job_view_t view;
    memset(&view, 0, sizeof(view));
    bool terminal = pump_until_terminal(m, id, 400, &view);
    ck("the job reaches a terminal state", terminal, MapGenState_Name(view.state));
    ck("a vanished worker is CRASHED, not merely FAILED",
       view.state == MAPGEN_STATE_CRASHED, MapGenState_Name(view.state));
    ck("no worker is left behind", !MapGen_HasWorker(m), "");
    ck("the Controller is free again", MapGen_ActiveJob(m) == MAPGEN_JOB_ID_NONE, "");
    MapGen_Destroy(m);
}

/*
 * A staged verdict of contract size arrives whole.
 *
 * The synthetic job stages an EMPTY result, so every test of this path proved
 * a delivery that carried nothing - and the Controller read frames into 256
 * bytes while the contract allows 2048. Every real summary was refused as
 * PAYLOAD_TOO_LARGE and every generate in the shipped game failed for a reason
 * that had nothing to do with the map it built.
 */
static void test_staged_summary(void)
{
    printf("\n=== a staged verdict of contract size arrives whole\n");
    if (!g_summary_worker) {
        ck("a max-summary worker binary was supplied", false,
           "fourth argument missing");
        return;
    }
    mapgen_t *m = make_with(g_summary_worker);
    mapgen_request_t req;
    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_VALIDATE;
    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    ck("the job is accepted", MapGen_Submit(m, &req, &id) == MAPGEN_SUBMIT_ACCEPTED, "");

    mapgen_job_view_t view;
    memset(&view, 0, sizeof(view));
    const bool terminal = pump_until_terminal(m, id, 400, &view);
    ck("the job reaches a terminal state", terminal, MapGenState_Name(view.state));

    /* PAYLOAD_TOO_LARGE is what a receiver too small to hold the contract
       records, and it is recorded as a diagnostic before the job dies. */
    mapgen_observation_t obs;
    bool too_large = false;
    if (MapGen_Observe(m, id, 0, &obs)) {
        for (uint32_t i = 0; i < obs.event_count; i++)
            if (obs.events[i].kind == MAPGEN_EVENT_DIAGNOSTIC &&
                obs.events[i].code == (uint32_t)MAPGEN_PROC_ERR_PAYLOAD_TOO_LARGE)
                too_large = true;
    }
    ck("the frame was not refused as too large", !too_large,
       "the Controller's receive buffer is smaller than a summary may be");

    char summary[MAPGEN_SUMMARY_MAX];
    const bool got = MapGen_Summary(m, id, summary, sizeof(summary));
    ck("the verdict can be read back", got, "");
    ck("it is the verdict the worker staged",
       got && !strncmp(summary, "result SELFTEST", 15), got ? summary : "");
    ck("all of it arrived, not a truncated prefix",
       got && strlen(summary) == MAPGEN_SUMMARY_MAX - 1, "");

    MapGen_Destroy(m);
}

/*
 * A published map is one the game can load.
 *
 * PUBLISHING_MAP was a state that did nothing: a generate that succeeded left
 * its artifact in the job directory, which the engine does not search, so the
 * player had no map. This drives a worker that stages a publishable verdict
 * naming a file it wrote, and asserts the bytes reach the maps directory under
 * the requested name.
 */
/*
 * A verdict that accounts for nothing is not walked past.
 *
 * The Controller advances a generate through the states the contract defines,
 * and it does that on the strength of what the worker reported doing. A
 * summary that says only "publish me" reports no compile, no validation and no
 * measurement, and the job fails rather than being carried to success by a
 * transition nobody earned.
 */
static void test_thin_verdict(void)
{
    printf("\n=== a verdict that accounts for nothing is refused\n");
    if (!g_thin_worker) {
        ck("a thin-verdict worker binary was supplied", false,
           "sixth argument missing");
        return;
    }

    char maps[1024];
    snprintf(maps, sizeof(maps), "%s/thin_maps", g_dir);

    mapgen_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.worker_exe_path = g_thin_worker;
    cfg.work_dir = g_dir;
    cfg.expected_build_id = "q2prox-mapgen-worker-1";
    cfg.handshake_timeout_ms = 4000;
    cfg.maps_dir = maps;
    cfg.moddir = g_dir;
    cfg.compiler_path = "compiler-not-run-by-this-test";
    mapgen_t *m = MapGen_Create(&cfg);

    mapgen_request_t req;
    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_GENERATE;
    snprintf(req.generate.donor_map, sizeof(req.generate.donor_map), "donor.bsp");
    snprintf(req.generate.map_name, sizeof(req.generate.map_name), "q2mg_thin");
    req.generate.fidelity = 100;
    req.generate.seed = 1;

    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    ck("the generate is accepted",
       MapGen_Submit(m, &req, &id) == MAPGEN_SUBMIT_ACCEPTED, "");

    mapgen_job_view_t view;
    memset(&view, 0, sizeof(view));
    const bool terminal = pump_until_terminal(m, id, 400, &view);
    ck("the job reaches a terminal state", terminal, MapGenState_Name(view.state));
    ck("it does not succeed", view.state != MAPGEN_STATE_SUCCEEDED,
       MapGenState_Name(view.state));

    mapgen_observation_t obs;
    bool said_why = false;
    if (MapGen_Observe(m, id, 0, &obs))
        for (uint32_t i = 0; i < obs.event_count; i++)
            if (obs.events[i].kind == MAPGEN_EVENT_DIAGNOSTIC &&
                obs.events[i].code == MAPGEN_DIAG_VERDICT_INCOMPLETE)
                said_why = true;
    ck("and it says the verdict did not account for what it did", said_why, "");

    char published[1200];
    snprintf(published, sizeof(published), "%s/q2mg_thin.bsp", maps);
    FILE *f = fopen(published, "rb");
    ck("nothing was published", f == NULL, published);
    if (f)
        fclose(f);

    MapGen_Destroy(m);
}

/*
 * The most recently made `job_*` directory under a work directory.
 *
 * The Controller names it and does not report it, so a test that wants to know
 * which directory a session used has to look.
 */
static void newest_job_dir(const char *work, char *out, size_t out_size)
{
    out[0] = '\0';
#ifdef _WIN32
    char pattern[512];
    snprintf(pattern, sizeof(pattern), "%s/job_*", work);
    WIN32_FIND_DATAA found;
    HANDLE h = FindFirstFileA(pattern, &found);
    if (h == INVALID_HANDLE_VALUE)
        return;
    FILETIME newest;
    memset(&newest, 0, sizeof(newest));
    do {
        if (!(found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY))
            continue;
        if (CompareFileTime(&found.ftLastWriteTime, &newest) >= 0
            || !out[0]) {
            newest = found.ftLastWriteTime;
            snprintf(out, out_size, "%s", found.cFileName);
        }
    } while (FindNextFileA(h, &found));
    FindClose(h);
#else
    (void)work; (void)out_size;
#endif
}

/*
 * Two sessions cannot share a job directory.
 *
 * JobIds start at 1 in every session, so the second session's first generate
 * used to be handed the first session's directory - baseline, attempts and all
 * - and died at once with ERR_BASELINE. Build a map, quit, build another:
 * broken every time.
 *
 * Two Controllers one after the other is that situation, and this asserts what
 * makes it safe: the same JobId, different directories.
 */
static void test_job_directory_is_this_jobs(void)
{
    printf("\n=== two sessions, the same JobId, different directories\n");
    if (!g_publish_worker) {
        ck("a publishing worker binary was supplied", false,
           "fifth argument missing");
        return;
    }

    char seen[2][512];
    mapgen_job_id_t ids[2] = { MAPGEN_JOB_ID_NONE, MAPGEN_JOB_ID_NONE };

    for (int session = 0; session < 2; session++) {
        char work[512];
        snprintf(work, sizeof(work), "%s/two_sessions", g_dir);

        mapgen_config_t cfg;
        memset(&cfg, 0, sizeof(cfg));
        cfg.worker_exe_path = g_publish_worker;
        cfg.work_dir = work;
        cfg.expected_build_id = "q2prox-mapgen-worker-1";
        cfg.handshake_timeout_ms = 4000;
        cfg.maps_dir = work;
        cfg.moddir = work;
        cfg.compiler_path = "compiler-not-run-by-this-test";
        mapgen_t *m = MapGen_Create(&cfg);

        mapgen_request_t req;
        memset(&req, 0, sizeof(req));
        req.kind = MAPGEN_REQ_GENERATE;
        snprintf(req.generate.donor_map, sizeof(req.generate.donor_map),
                 "donor.bsp");
        snprintf(req.generate.map_name, sizeof(req.generate.map_name),
                 "q2mg_sessions");
        req.generate.fidelity = 100;
        req.generate.seed = 1;
        MapGen_Submit(m, &req, &ids[session]);

        mapgen_job_view_t view;
        memset(&view, 0, sizeof(view));
        pump_until_terminal(m, ids[session], 400, &view);

        /* Whichever directory this session made under the work directory is
           the one it was given. */
        seen[session][0] = '\0';
        newest_job_dir(work, seen[session], sizeof(seen[session]));
        MapGen_Destroy(m);
    }

    ck("both sessions got the same JobId", ids[0] == ids[1],
       "if they did not, this test is not about what it says it is");
    ck("each session named a job directory",
       seen[0][0] && seen[1][0], "");
    ck("and they are not the same directory",
       strcmp(seen[0], seen[1]) != 0,
       "the second session would inherit the first's baseline and attempts");
}

static void test_publish(void)
{
    printf("\n=== a successful job publishes a map the game can load\n");
    if (!g_publish_worker) {
        ck("a publishing worker binary was supplied", false,
           "fifth argument missing");
        return;
    }

    char maps[1024];
    snprintf(maps, sizeof(maps), "%s/published_maps", g_dir);

    mapgen_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.worker_exe_path = g_publish_worker;
    cfg.work_dir = g_dir;
    cfg.expected_build_id = "q2prox-mapgen-worker-1";
    cfg.handshake_timeout_ms = 4000;
    cfg.maps_dir = maps;
    cfg.moddir = g_dir;
    cfg.compiler_path = "compiler-not-run-by-this-test";
    mapgen_t *m = MapGen_Create(&cfg);
    ck("the Controller is created", m != NULL, "");

    mapgen_request_t req;
    memset(&req, 0, sizeof(req));
    req.kind = MAPGEN_REQ_GENERATE;
    snprintf(req.generate.donor_map, sizeof(req.generate.donor_map), "donor.bsp");
    snprintf(req.generate.map_name, sizeof(req.generate.map_name), "q2mg_published");
    req.generate.fidelity = 100;
    req.generate.seed = 1;

    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    ck("the generate is accepted",
       MapGen_Submit(m, &req, &id) == MAPGEN_SUBMIT_ACCEPTED, "");

    mapgen_job_view_t view;
    memset(&view, 0, sizeof(view));
    const bool terminal = pump_until_terminal(m, id, 400, &view);
    ck("the job reaches a terminal state", terminal, MapGenState_Name(view.state));
    ck("a publishable verdict SUCCEEDS",
       view.state == MAPGEN_STATE_SUCCEEDED, MapGenState_Name(view.state));

    char published[1200];
    snprintf(published, sizeof(published), "%s/q2mg_published.bsp", maps);
    FILE *f = fopen(published, "rb");
    ck("the map is in the maps directory, under the requested name",
       f != NULL, published);
    if (f) {
        char got[64];
        const size_t n = fread(got, 1, sizeof(got) - 1, f);
        fclose(f);
        got[n] = '\0';
        ck("it is the artifact the worker staged, whole",
           n == 22 && !memcmp(got, "IBSP-selftest-artifact", 22), got);
    }

    char part[1300];
    snprintf(part, sizeof(part), "%s.part", published);
    f = fopen(part, "rb");
    ck("no half-written copy is left behind", f == NULL, part);
    if (f)
        fclose(f);

    MapGen_Destroy(m);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        printf("usage: driver <worker-exe> <work-dir> [crash-worker-exe]\n");
        return 2;
    }
    g_worker = argv[1];
    g_dir = argv[2];
    g_crash_worker = argc > 3 ? argv[3] : NULL;
    g_summary_worker = argc > 4 ? argv[4] : NULL;
    g_publish_worker = argc > 5 ? argv[5] : NULL;
    g_thin_worker = argc > 6 ? argv[6] : NULL;

    printf("=== MAPGEN-1 Controller\n");
    test_off_state();
    test_controller_local_job();
    test_worker_job();
    test_busy();
    test_cancel();
    test_missing_worker();
    test_observe_cursor();
    test_worker_crash();
    test_staged_summary();
    test_publish();
    test_thin_verdict();
    test_job_directory_is_this_jobs();

    printf("\n=== %d cases asserted, %d failures\n", g_cases, g_failed);
    printf("%s\n", g_failed ? "RESULT: FAIL" : "RESULT: PASS");
    return g_failed ? 1 : 0;
}
