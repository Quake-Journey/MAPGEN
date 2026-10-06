/*
Copyright (C) 2026 Q2PRO-X

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
*/

/*
 * MAPGEN-1 - the Controller.
 *
 * Binds the job state machine to the worker process host and exposes the one
 * external Seam. It owns the decisions the worker is not allowed to make:
 * when a worker exists at all, what a staged result means, and which single
 * terminal event a job emits.
 *
 * Contract sections 5.1, 5.2 and 2.11.
 */

#include "common/mapgen.h"
#include "common/mapgen_publish.h"
#include "common/mapgen_process.h"

#ifdef _WIN32
#include <direct.h>
#else
#include <sys/stat.h>
#endif
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

/* How many frames one Tick may drain. The client frame loop calls this; it
   must return promptly whatever the worker is doing (contract 2.12). */
#define MAPGEN_TICK_MAX_FRAMES   16
/* How long a single Receive may wait inside a Tick. Zero would spin; a small
   bound keeps the frame cost predictable. */
#define MAPGEN_TICK_WAIT_MS      1
/* How long a child that just errored may take to finish dying before the
   Controller decides the error was not a death. */
#define MAPGEN_DEATH_SETTLE_MS   250

#define MAPGEN_PATH_MAX          512

struct mapgen_s {
    mapgen_jobs_t     *jobs;

    char               worker_exe[MAPGEN_PATH_MAX];
    char               work_dir[MAPGEN_PATH_MAX];
    char               build_id[MAPGEN_PROCESS_BUILD_ID_BYTES];
    uint32_t           handshake_timeout_ms;

    /* Where the things a request NAMES live, and the pinned compiler. Fixed
       at install; this is what lets a request carry names rather than paths. */
    char               maps_dir[MAPGEN_PATH_MAX];
    char               snapshots_dir[MAPGEN_PATH_MAX];
    char               moddir[MAPGEN_PATH_MAX];
    char               compiler[MAPGEN_PATH_MAX];

    /* NULL whenever no job needs a worker. This is the off-state promise made
       concrete: there is no idle worker and no lazy singleton. */
    mapgen_process_t  *worker;
    mapgen_job_id_t    worker_job;

    /* What a published map is called. The request names it, the worker only
       ever reports paths inside its own job directory, and the name has to
       outlive the request - which is deep-copied and gone by the time there is
       anything to publish. */
    char               publish_name[MAPGEN_REQUEST_NAME];

    /* This run's job directory and the identity that made it unique. Both are
       needed after the worker is gone: the artifacts are in the first, and the
       second is what a published Project is traced back by. */
    char               job_dir[MAPGEN_PATH_MAX];
    char               job_identity[MAPGEN_REQUEST_NAME];

    /* Set once the worker has staged a result. STAGED_RESULT is not success;
       the Controller decides. */
    bool               staged;
    /* What the worker said about what it staged, kept until the decision is
       made - a verdict read from a buffer that has moved on is a verdict about
       something else. */
    char               summary[MAPGEN_SUMMARY_MAX];
    /* Which job it is about. One buffer serves every job in turn, and a
       verdict handed out under the wrong id is a verdict about something
       else - the same reason it is kept until the decision is made. */
    mapgen_job_id_t    summary_job;
};

/* ------------------------------------------------------------------------ */

/* Below, where the paths it makes are explained. Declared here because the
   Controller makes its own work directory before anything else uses it. */
static void make_path(const char *path);

static void copy_bounded(char *dst, size_t dst_size, const char *src)
{
    if (!dst || !dst_size)
        return;
    dst[0] = '\0';
    if (!src)
        return;
    size_t n = strlen(src);
    if (n >= dst_size)
        n = dst_size - 1;
    memcpy(dst, src, n);
    dst[n] = '\0';
}

/* Random enough for a per-launch capability token: it only has to be
   unguessable by another local process within one launch. */
static void fill_random(uint8_t *out, size_t count)
{
#ifdef _WIN32
    static uint64_t counter;
    uint64_t seed = (uint64_t)GetTickCount64();
    seed ^= (uint64_t)GetCurrentProcessId() << 32;
    seed ^= ++counter * 0x9E3779B97F4A7C15ull;
    LARGE_INTEGER perf;
    if (QueryPerformanceCounter(&perf))
        seed ^= (uint64_t)perf.QuadPart;
    for (size_t i = 0; i < count; i++) {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        out[i] = (uint8_t)(seed >> ((i % 8) * 8));
    }
#else
    for (size_t i = 0; i < count; i++)
        out[i] = (uint8_t)(i * 31 + 7);
#endif
}

/* Does this request kind need the heavy worker at all?
   Discovery, both preflights, commit recovery and the snapshot library
   transactions are Controller-local jobs and never cross the IPC
   (contract section 24). */
static bool kind_needs_worker(mapgen_request_kind_t kind)
{
    switch (kind) {
    case MAPGEN_REQ_TRAIN:
    case MAPGEN_REQ_GENERATE:
    case MAPGEN_REQ_VALIDATE:
        return true;
    default:
        return false;
    }
}

static uint16_t start_frame_for(mapgen_request_kind_t kind)
{
    switch (kind) {
    case MAPGEN_REQ_TRAIN:    return MAPGEN_IPC_START_TRAIN;
    case MAPGEN_REQ_GENERATE: return MAPGEN_IPC_START_GENERATE;
    default:                  return MAPGEN_IPC_START_VALIDATE;
    }
}

static void release_worker(mapgen_t *mapgen)
{
    if (!mapgen->worker)
        return;
    MapGenProcess_Close(mapgen->worker);
    mapgen->worker = NULL;
    mapgen->worker_job = MAPGEN_JOB_ID_NONE;
    mapgen->staged = false;
}

/*
 * Which terminal state does a process error mean?
 *
 * CHILD_GONE is obviously CRASHED, but so is a WRITE or PROTOCOL error to a
 * child that has already died - and that is a real race, not a hypothetical:
 * a worker can abort in the window between answering HELLO and receiving its
 * START, so the very same death is observed as either a failed read or a
 * failed write depending on timing. Reporting one as CRASHED and the other as
 * FAILED would make the user-visible result depend on a scheduler.
 */
static mapgen_state_t terminal_for(mapgen_t *mapgen, mapgen_process_result_t r)
{
    if (r == MAPGEN_PROC_ERR_CHILD_GONE)
        return MAPGEN_STATE_CRASHED;
    if (!mapgen->worker)
        return MAPGEN_STATE_FAILED;
    /* Give a dying child a bounded moment to finish dying. Asking "is it
       alive?" at the exact instant of the error answers about a process that
       is mid-abort, which is how the same crash came out CRASHED or FAILED
       depending on the scheduler. */
    if (!MapGenProcess_IsAlive(mapgen->worker) ||
        MapGenProcess_WaitExit(mapgen->worker, MAPGEN_DEATH_SETTLE_MS, NULL))
        return MAPGEN_STATE_CRASHED;
    return MAPGEN_STATE_FAILED;
}

/* Drive a job to a terminal state and drop the worker with it. Every path that
   ends a job goes through here, so "exactly one terminal event" is a property
   of one function rather than of remembering. */
static void terminate_job(mapgen_t *mapgen, mapgen_job_id_t id, mapgen_state_t terminal)
{
    mapgen_job_view_t view;
    if (MapGenJobs_Observe(mapgen->jobs, id, &view) && !view.terminal) {
        if (terminal == MAPGEN_STATE_CANCELLED && view.state != MAPGEN_STATE_CANCELLING)
            MapGenJobs_Advance(mapgen->jobs, id, MAPGEN_STATE_CANCELLING);
        MapGenJobs_Advance(mapgen->jobs, id, terminal);
    }
    /*
     * Why it ended, when nothing else said.
     *
     * A job that reached a terminal state without a staged result has only
     * the child's own exit status left to explain it, and dropping the worker
     * throws that away. It is recorded as a diagnostic - evidence, not a
     * decision: the terminal state is already chosen above and this cannot
     * change it.
     *
     * MAPGEN_DIAG_WORKER_EXIT marks it, so a reader can tell an exit status
     * apart from the protocol codes that share this channel.
     */
    if (mapgen->worker_job == id) {
        if (!mapgen->staged && mapgen->worker) {
            int32_t code = 0;
            if (MapGenProcess_WaitExit(mapgen->worker, MAPGEN_DEATH_SETTLE_MS,
                                       &code))
                MapGenJobs_Diagnostic(mapgen->jobs, id,
                                      MAPGEN_DIAG_WORKER_EXIT |
                                      (uint32_t)(code & 0xFFFF));
        }
        release_worker(mapgen);
    }
}

/* ------------------------------------------------------------------------ */

mapgen_t *MapGen_Create(const mapgen_config_t *config)
{
    if (!config || !config->worker_exe_path || !config->work_dir)
        return NULL;

    mapgen_t *mapgen = calloc(1, sizeof(*mapgen));
    if (!mapgen)
        return NULL;

    mapgen->jobs = MapGenJobs_Create();
    if (!mapgen->jobs) {
        free(mapgen);
        return NULL;
    }

    copy_bounded(mapgen->worker_exe, sizeof(mapgen->worker_exe), config->worker_exe_path);
    copy_bounded(mapgen->work_dir, sizeof(mapgen->work_dir), config->work_dir);
    /*
     * And it exists. The worker is launched WITH this as its working
     * directory, and a process cannot start in a directory that is not there,
     * so the launch would fail before the job directory - which is what would
     * otherwise have created it - was ever named.
     */
    if (mapgen->work_dir[0])
        make_path(mapgen->work_dir);
    copy_bounded(mapgen->build_id, sizeof(mapgen->build_id), config->expected_build_id);
    /* Where the things a request NAMES live. Copied like everything else the
       config carries: the Controller keeps no pointer into a caller's memory. */
    copy_bounded(mapgen->maps_dir, sizeof(mapgen->maps_dir), config->maps_dir);
    copy_bounded(mapgen->snapshots_dir, sizeof(mapgen->snapshots_dir),
                 config->snapshots_dir);
    copy_bounded(mapgen->moddir, sizeof(mapgen->moddir), config->moddir);
    copy_bounded(mapgen->compiler, sizeof(mapgen->compiler),
                 config->compiler_path);
    mapgen->handshake_timeout_ms = config->handshake_timeout_ms;
    mapgen->worker_job = MAPGEN_JOB_ID_NONE;

    /* Deliberately nothing else. No process, no handle, no thread, no probe of
       the filesystem: creating the Controller must cost nothing, because it is
       created whether or not the user ever opens the Map Generator. */
    return mapgen;
}

void MapGen_Destroy(mapgen_t *mapgen)
{
    if (!mapgen)
        return;
    release_worker(mapgen);
    MapGenJobs_Destroy(mapgen->jobs);
    free(mapgen);
}

/*
 * The job, as the worker reads it.
 *
 * `key value` a line at a time, which is what the worker parses, and every
 * path in it is built here from a name the caller gave and a directory this
 * Controller was configured with. A request that names nothing usable is
 * refused before a worker is launched, because a worker started to be told it
 * has nothing to do is a process nobody needed.
 *
 * Returns the length written, or zero when the request cannot be a job.
 */
/*
 * Make a directory and everything above it.
 *
 * The work directory of a fresh install has never existed, and neither has the
 * job directory inside it - the pipeline's first act is to create a compile
 * directory in there, which cannot work if nothing above it is there either.
 */
static void make_path(const char *path)
{
    char work[MAPGEN_PATH_MAX];
    snprintf(work, sizeof(work), "%s", path);
    for (char *at = work + 1; *at; at++) {
        if (*at != '/' && *at != '\\')
            continue;
        const char was = *at;
        *at = '\0';
#ifdef _WIN32
        _mkdir(work);
#else
        mkdir(work, 0777);
#endif
        *at = was;
    }
#ifdef _WIN32
    _mkdir(work);
#else
    mkdir(work, 0777);
#endif
}

/* Is it there? The Controller opens no map; it only decides which path to
   name, and a path to a file that is not there names nothing. */
static bool file_exists(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return false;
    fclose(f);
    return true;
}

static uint32_t render_generate(const mapgen_t *mapgen,
                                const mapgen_generate_request_t *g,
                                mapgen_job_id_t id,
                                const uint8_t uuid[MAPGEN_IPC_UUID_BYTES],
                                char *out, size_t size)
{
    if (!g->donor_map[0] || !g->map_name[0] || !mapgen->maps_dir[0]
        || !mapgen->compiler[0])
        return 0;
    if (g->fidelity < 0 || g->fidelity > 100)
        return 0;
    /*
     * Fidelity zero invents a map out of a snapshot. Without one there is
     * nothing to invent from, and forking the donor instead would answer a
     * question nobody asked - which is exactly what the anchor sweep did
     * until it was told the difference.
     */
    if (g->fidelity == 0 && (!g->snapshot[0] || !mapgen->snapshots_dir[0]))
        return 0;

    /*
     * Where the donor actually is.
     *
     * The maps directory first, and then the work directory's own `donors`,
     * because the stock maps live inside a pak and somebody has to lay one out
     * before a separate process can read it. Whoever did that put it there.
     */
    char donor[MAPGEN_PATH_MAX];
    snprintf(donor, sizeof(donor), "%s/%s", mapgen->maps_dir, g->donor_map);
    if (!file_exists(donor))
        snprintf(donor, sizeof(donor), "%s/donors/%s", mapgen->work_dir,
                 g->donor_map);

    /*
     * Every job gets a directory of its own, and it is MADE here, because this
     * is where the name is decided.
     *
     * Named by the JobId AND the job's uuid. The JobId alone is not this job's
     * name: it starts at 1 in every session, so the second session's first
     * generate was handed the first session's directory - baseline, attempts
     * and all - and died at once with ERR_BASELINE. Build a map, quit, build
     * another: broken every time. The uuid is made from the tick count, the
     * process id and a performance counter, which is what makes it this run's.
     */
    /*
     * The directory this job was given when it was submitted, which is also
     * the worker's own working directory. Recomputing it here from the uuid
     * would be a second source of truth for the same thing.
     */
    char job_dir[MAPGEN_PATH_MAX];
    snprintf(job_dir, sizeof(job_dir), "%s", mapgen->job_dir);
    make_path(job_dir);
    /* The identity is the job's, decided at submit; these are here so the
       signature still says what a request is rendered from. */
    (void)id;
    (void)uuid;

    const int n = snprintf(out, size,
                           "compiler %s\n"
                           "donor %s\n"
                           "jobdir %s\n"
                           "mapname %s\n"
                           "moddir %s\n"
                           "fidelity %d\n"
                           "seed %llu\n"
                           "scale %d\n"
                           "goal %d\n"
                           "profile %s\n",
                           mapgen->compiler,
                           donor,
                           job_dir,
                           g->map_name,
                           mapgen->moddir[0] ? mapgen->moddir : mapgen->work_dir,
                           g->fidelity,
                           (unsigned long long)g->seed,
                           g->scale, g->goal,
                           g->final_profile ? "final" : "draft");
    if (n <= 0 || (size_t)n >= size)
        return 0;

    uint32_t used = (uint32_t)n;
    if (g->fidelity == 0) {
        const int m = snprintf(out + used, size - used,
                               "snapshot %s/%s\n"
                               "manifest %s/target_manifest.txt\n",
                               mapgen->snapshots_dir, g->snapshot,
                               mapgen->work_dir);
        if (m <= 0 || (size_t)(used + m) >= size)
            return 0;
        used += (uint32_t)m;
    }
    if (g->max_attempts) {
        const int m = snprintf(out + used, size - used, "maxattempts %u\n",
                               g->max_attempts);
        if (m <= 0 || (size_t)(used + m) >= size)
            return 0;
        used += (uint32_t)m;
    }
    return used + 1;            /* the worker reads a NUL-terminated request */
}

/*
 * What the worker staged, and whether anybody may have it.
 *
 * The summary is `key value` lines and the two that decide are `result` and
 * `publishable`. Both must say so: a diagnostic run reports every gate it ran
 * and is explicitly not publishable, and a verdict that travelled through here
 * without being read would turn one into a product answer.
 */
/*
 * One `key value` line of a staged summary.
 *
 * The summary is the worker's own account and this reads it rather than
 * re-deriving anything: the artifact's path is the worker's to report, since
 * it is the one that built it.
 */
static bool summary_value(const char *summary, const char *key,
                          char *out, size_t out_bytes)
{
    if (!out || !out_bytes)
        return false;
    out[0] = '\0';
    if (!summary || !key)
        return false;

    const size_t klen = strlen(key);
    for (const char *at = summary; *at; ) {
        const char *end = strchr(at, '\n');
        const size_t len = end ? (size_t)(end - at) : strlen(at);
        if (len > klen + 1 && !strncmp(at, key, klen) && at[klen] == ' ') {
            const size_t vlen = len - klen - 1;
            if (vlen >= out_bytes)
                return false;
            memcpy(out, at + klen + 1, vlen);
            out[vlen] = '\0';
            return true;
        }
        if (!end)
            break;
        at = end + 1;
    }
    return false;
}

/*
 * Write the verdict down beside the map.
 *
 * A published map that carries only its own bytes says nothing about what was
 * claimed for it - which fidelity was asked for, what divergence came out,
 * whether it was in band, what the artifact hashed to. The receipt is the
 * worker's own summary, stored unchanged, and it is a required member of the
 * Project: evidence that only exists in a log is evidence the player does not
 * have.
 */
static bool write_receipt(const mapgen_t *mapgen, char *out, size_t size)
{
    if (!mapgen->job_dir[0])
        return false;
    if ((size_t)snprintf(out, size, "%s/receipt.txt", mapgen->job_dir) >= size)
        return false;
    FILE *f = fopen(out, "wb");
    if (!f)
        return false;
    const size_t length = strlen(mapgen->summary);
    const bool ok = fwrite(mapgen->summary, 1, length, f) == length;
    return fclose(f) == 0 && ok;
}

/*
 * Publish the Project, all of it or none of it.
 *
 * What this used to be: copy the map, try the certificates, try the recipe,
 * ignore whether either worked, return true. It called remove() on the
 * destination first, so a second job with the same name replaced the first
 * without asking. Nothing recorded that the files belonged together, so the
 * client decided what was playable by looking at name prefixes - and about
 * twenty-five driver artifacts in the Release tree were offered to the player
 * as generated maps.
 *
 * Now it is one transaction with one visibility point, and the members it
 * requires are the ones the verdict declared: the map with the hash the worker
 * said it had, a certificate file when the verdict rests on certificates, the
 * recipe when one was written, and the receipt always.
 *
 * A name already taken is not overwritten. The Project takes the next free
 * identity instead, because rebuilding into a new identity is the only
 * replacement the player has agreed to.
 */
/*
 * Publish, and say what happened.
 *
 * Returns MAPGEN_PUBLISH_OK or the reason it did not. A caller that
 * only learns "false" can only report "could not be published", which
 * is what a player and a log both got: the report has a result code and
 * a sentence of detail, and both were being dropped here.
 */
static mapgen_publish_result_t publish_artifact(mapgen_t *mapgen)
{
    if (!mapgen->maps_dir[0] || !mapgen->publish_name[0])
        return MAPGEN_PUBLISH_ERR_ARGS;

    char bsp[MAPGEN_PATH_MAX];
    if (!summary_value(mapgen->summary, "bsp", bsp, sizeof(bsp)) || !bsp[0])
        return MAPGEN_PUBLISH_ERR_SOURCE;

    mapgen_publish_request_t request;
    memset(&request, 0, sizeof(request));
    snprintf(request.maps_dir, sizeof(request.maps_dir), "%s",
             mapgen->maps_dir);
    snprintf(request.job_identity, sizeof(request.job_identity), "%s",
             mapgen->job_identity);
    /* Every artifact the worker named must be inside this, or it does not
       travel: the paths come from the worker's own summary. */
    snprintf(request.job_dir, sizeof(request.job_dir), "%s",
             mapgen->job_dir);

    const char *dot = strrchr(bsp, '.');
    const int stem = dot ? (int)(dot - bsp) : (int)strlen(bsp);

    /* the map, with the hash the verdict declared for it */
    mapgen_publish_member_t *m = &request.members[request.num_members++];
    snprintf(m->role, sizeof(m->role), "map");
    snprintf(m->suffix, sizeof(m->suffix), ".bsp");
    snprintf(m->source, sizeof(m->source), "%s", bsp);
    m->required = true;
    summary_value(mapgen->summary, "bspsha", m->declared_sha256,
                  sizeof(m->declared_sha256));

    /* the certificates, required exactly when the verdict rests on any */
    char declared[64];
    const bool has_count = summary_value(mapgen->summary, "certificates",
                                         declared, sizeof(declared));
    const unsigned certificates = has_count ? (unsigned)strtoul(declared, NULL,
                                                                10) : 0u;
    char certs[MAPGEN_PATH_MAX];
    if ((size_t)snprintf(certs, sizeof(certs), "%.*s.certificates.txt", stem,
                         bsp) < sizeof(certs)
        && (certificates || file_exists(certs))) {
        m = &request.members[request.num_members++];
        snprintf(m->role, sizeof(m->role), "certificates");
        snprintf(m->suffix, sizeof(m->suffix), ".certificates.txt");
        snprintf(m->source, sizeof(m->source), "%s", certs);
        m->required = certificates > 0;
    }

    /* the recipe, required when the worker says it wrote one */
    char recipe[MAPGEN_PATH_MAX];
    if (summary_value(mapgen->summary, "recipe", recipe, sizeof(recipe))
        && recipe[0] && strcmp(recipe, "-") != 0) {
        m = &request.members[request.num_members++];
        snprintf(m->role, sizeof(m->role), "recipe");
        snprintf(m->suffix, sizeof(m->suffix), ".q2mgrec");
        snprintf(m->source, sizeof(m->source), "%s", recipe);
        m->required = true;
    }

    /* the receipt, always */
    char receipt[MAPGEN_PATH_MAX];
    if (!write_receipt(mapgen, receipt, sizeof(receipt)))
        return MAPGEN_PUBLISH_ERR_RECEIPT;
    m = &request.members[request.num_members++];
    snprintf(m->role, sizeof(m->role), "receipt");
    snprintf(m->suffix, sizeof(m->suffix), ".q2mgreceipt");
    snprintf(m->source, sizeof(m->source), "%s", receipt);
    m->required = true;

    /*
     * The name, and the next one if it is taken.
     *
     * Sixty-four tries, then it gives up rather than looping: a maps directory
     * with sixty-four Projects of the same name is telling us something other
     * than "try sixty-five".
     */
    mapgen_publish_report_t report;
    for (unsigned attempt = 0; attempt < 64; attempt++) {
        if (!attempt)
            snprintf(request.name, sizeof(request.name), "%s",
                     mapgen->publish_name);
        else
            snprintf(request.name, sizeof(request.name), "%s_%u",
                     mapgen->publish_name, attempt + 1);

        const mapgen_publish_result_t rc =
            MapGenPublish_Commit(&request, &report);
        if (rc == MAPGEN_PUBLISH_OK) {
            /* What it ended up being called, so the client offers the Project
               that exists rather than the name that was asked for. */
            snprintf(mapgen->publish_name, sizeof(mapgen->publish_name), "%s",
                     request.name);
            return MAPGEN_PUBLISH_OK;
        }
        if (rc != MAPGEN_PUBLISH_ERR_COLLISION)
            return rc;
    }
    return MAPGEN_PUBLISH_ERR_COLLISION;
}

/*
 * The route a generate takes, in the order the state machine allows.
 *
 * The same order as `edges_generate` in the job store, which is the authority;
 * this is how the Controller WALKS it. A job cannot be moved to a state that
 * is not one edge away, so a Controller that jumped to the publish state moved
 * nothing at all and left the job to be failed by the helper's goodbye.
 */
static const mapgen_state_t generate_route[] = {
    MAPGEN_STATE_QUEUED,
    MAPGEN_STATE_PREFLIGHT,
    MAPGEN_STATE_WARMUP,
    MAPGEN_STATE_SYNTHESIS,
    MAPGEN_STATE_DRAFT_COMPILE,
    MAPGEN_STATE_DRAFT_VALIDATION,
    MAPGEN_STATE_FINAL_COMPILE,
    MAPGEN_STATE_FINAL_VALIDATION,
    MAPGEN_STATE_COMMITTING_PROJECT,
    MAPGEN_STATE_PUBLISHING_MAP,
    MAPGEN_STATE_FINALIZING_PROJECT,
    MAPGEN_STATE_SUCCEEDED,
};

static int route_index(mapgen_state_t state)
{
    for (int i = 0; i < (int)(sizeof(generate_route) / sizeof(generate_route[0])); i++)
        if (generate_route[i] == state)
            return i;
    return -1;
}

/*
 * Walk a generate forward to `target`, one edge at a time.
 *
 * Every state it passes through is emitted, because a caller watching the job
 * is entitled to see what it went through rather than a jump. It refuses to go
 * backwards and stops at the first advance the store will not make.
 */
static bool walk_to(mapgen_t *mapgen, mapgen_job_id_t id, mapgen_state_t target)
{
    mapgen_job_view_t view;
    if (!MapGenJobs_Observe(mapgen->jobs, id, &view))
        return false;

    const int from = route_index(view.state);
    const int to = route_index(target);
    if (from < 0 || to < 0 || to < from)
        return false;

    for (int i = from + 1; i <= to; i++)
        if (!MapGenJobs_Advance(mapgen->jobs, id, generate_route[i]))
            return false;
    return true;
}

/*
 * Does the staged verdict account for the stages it is about to be walked
 * past?
 *
 * The summary names the artifact and its digest (the compiles), the counts the
 * reachability oracle produced (the validations) and the divergence measured
 * against the band (the measurement). Anything missing means a stage nobody
 * can show happened, and the Controller does not advance a job on nothing.
 */
static bool summary_accounts_for_route(const char *summary)
{
    static const char *const needed[] = {
        "bsp", "bspsha", "places", "spawns", "divergence", "target", NULL
    };
    char value[MAPGEN_PATH_MAX];
    for (const char *const *key = needed; *key; key++)
        if (!summary_value(summary, *key, value, sizeof(value)) || !value[0])
            return false;
    return true;
}

static bool staged_is_publishable(const char *summary)
{
    if (!summary || !*summary)
        return false;
    bool result_ok = false, publishable = false;
    const char *at = summary;
    while (*at) {
        if (!strncmp(at, "result ", 7))
            result_ok = !strncmp(at + 7, "OK", 2)
                     && (at[9] == '\n' || at[9] == '\0' || at[9] == '\r');
        else if (!strncmp(at, "publishable ", 12))
            publishable = at[12] == '1';
        const char *eol = strchr(at, '\n');
        if (!eol)
            break;
        at = eol + 1;
    }
    return result_ok && publishable;
}

mapgen_submit_result_t MapGen_Submit(mapgen_t *mapgen,
                                     const mapgen_request_t *request,
                                     mapgen_job_id_t *out_id)
{
    if (out_id)
        *out_id = MAPGEN_JOB_ID_NONE;
    if (!mapgen || !request)
        return MAPGEN_SUBMIT_INVALID_REQUEST;
    if (request->kind >= MAPGEN_REQ_COUNT)
        return MAPGEN_SUBMIT_INVALID_REQUEST;

    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    mapgen_submit_result_t r = MapGenJobs_Submit(mapgen->jobs, request->kind, &id);
    if (r != MAPGEN_SUBMIT_ACCEPTED)
        return r;

    if (!kind_needs_worker(request->kind)) {
        /* Controller-local work. It still gets a JobId, a state machine and one
           terminal event; it simply never touches the worker. */
        if (out_id)
            *out_id = id;
        return MAPGEN_SUBMIT_ACCEPTED;
    }

    uint8_t token[MAPGEN_IPC_TOKEN_BYTES];
    uint8_t uuid[MAPGEN_IPC_UUID_BYTES];
    fill_random(token, sizeof(token));
    fill_random(uuid, sizeof(uuid));

    /*
     * This job's identity and its directory, decided before the worker exists.
     *
     * JobIds restart at one every session, so the identity carries the uuid as
     * well - two sessions' first jobs must not share a directory. The worker
     * starts IN it, so anything it writes without being told where lands in
     * its own job's directory and nowhere else.
     */
    snprintf(mapgen->job_identity, sizeof(mapgen->job_identity),
             "%08x_%02x%02x%02x%02x", (unsigned)id, uuid[0], uuid[1], uuid[2],
             uuid[3]);
    snprintf(mapgen->job_dir, sizeof(mapgen->job_dir), "%s/job_%s",
             mapgen->work_dir, mapgen->job_identity);
    make_path(mapgen->job_dir);

    mapgen_process_desc_t desc;
    memset(&desc, 0, sizeof(desc));
    desc.exe_path = mapgen->worker_exe;
    desc.work_dir = mapgen->job_dir;
    desc.token = token;
    desc.job_uuid = uuid;
    desc.handshake_timeout_ms = mapgen->handshake_timeout_ms;
    memcpy(desc.expected_build_id, mapgen->build_id, sizeof(desc.expected_build_id));

    mapgen_process_t *worker = NULL;
    mapgen_process_result_t pr = MapGenProcess_Launch(&desc, &worker);
    if (pr != MAPGEN_PROC_OK) {
        /* The job exists and must still emit exactly one terminal event, so
           the failure is reported through the state machine rather than by
           pretending the submit never happened. */
        MapGenJobs_Diagnostic(mapgen->jobs, id, (uint32_t)pr);
        terminate_job(mapgen, id, MAPGEN_STATE_FAILED);
        if (out_id)
            *out_id = id;
        return MAPGEN_SUBMIT_ACCEPTED;
    }

    mapgen->worker = worker;
    mapgen->worker_job = id;
    mapgen->staged = false;
    /* Kept, because the request is deep-copied and gone long before there is
       anything to publish under the name it asked for. */
    mapgen->publish_name[0] = '\0';
    if (request->kind == MAPGEN_REQ_GENERATE)
        copy_bounded(mapgen->publish_name, sizeof(mapgen->publish_name),
                     request->generate.map_name);

    /*
     * The job goes with the START.
     *
     * It used to be sent with nothing at all, and the worker - which parses a
     * job out of exactly this payload - could only ever answer ERR_REQUEST.
     * A generate whose request cannot be rendered never gets here: it is
     * refused above rather than launched to be told it has nothing to do.
     */
    char job[MAPGEN_JOB_REQUEST_MAX];
    uint32_t job_len = 0;
    if (request->kind == MAPGEN_REQ_GENERATE) {
        job_len = render_generate(mapgen, &request->generate, id, uuid, job,
                                  sizeof(job));
    }

    mapgen_process_result_t sr =
        MapGenProcess_Send(worker, start_frame_for(request->kind),
                           job_len ? (const uint8_t *)job : NULL, job_len);
    if (sr != MAPGEN_PROC_OK) {
        MapGenJobs_Diagnostic(mapgen->jobs, id, (uint32_t)sr);
        terminate_job(mapgen, id, terminal_for(mapgen, sr));
        if (out_id)
            *out_id = id;
        return MAPGEN_SUBMIT_ACCEPTED;
    }

    MapGenJobs_Advance(mapgen->jobs, id, MAPGEN_STATE_PREFLIGHT);
    if (out_id)
        *out_id = id;
    return MAPGEN_SUBMIT_ACCEPTED;
}

bool MapGen_Observe(mapgen_t *mapgen, mapgen_job_id_t id,
                    uint64_t after_sequence, mapgen_observation_t *out)
{
    if (!mapgen || !out)
        return false;
    memset(out, 0, sizeof(*out));
    if (!MapGenJobs_Observe(mapgen->jobs, id, &out->view))
        return false;
    out->event_count = MapGenJobs_Events(mapgen->jobs, id, after_sequence,
                                         out->events, MAPGEN_MAX_EVENTS_PER_OBSERVE,
                                         &out->events_missed);
    return true;
}

mapgen_cancel_result_t MapGen_Cancel(mapgen_t *mapgen, mapgen_job_id_t id)
{
    if (!mapgen)
        return MAPGEN_CANCEL_UNKNOWN_JOB;

    mapgen_cancel_result_t r = MapGenJobs_Cancel(mapgen->jobs, id);
    if (r != MAPGEN_CANCEL_ACCEPTED)
        return r;

    /* Ask the worker to stop at its next checkpoint. It is not killed here:
       a job that is mid-write reaches a checkpoint and stops there, and the
       Controller decides what the result means. */
    if (mapgen->worker && mapgen->worker_job == id)
        MapGenProcess_RequestCancel(mapgen->worker);
    return r;
}

void MapGen_Tick(mapgen_t *mapgen)
{
    /* An idle Controller does nothing here - no syscall, no allocation, no
       poll. That is the off-state promise (contract 2.11), and it is the
       reason this early-out is the first statement. */
    if (!mapgen || !mapgen->worker)
        return;

    mapgen_job_id_t id = mapgen->worker_job;

    for (int i = 0; i < MAPGEN_TICK_MAX_FRAMES; i++) {
        mapgen_ipc_header_t header;
        /*
         * Sized by the contract, not by a round number.
         *
         * The receiver refuses a frame that does not fit the buffer it was
         * given, and MAPGEN_SUMMARY_MAX is how much verdict a worker is
         * allowed to stage. At 256 bytes every real summary - eighteen lines,
         * two digests, two paths - was refused as PAYLOAD_TOO_LARGE, and the
         * job it belonged to failed for a reason that had nothing to do with
         * the map.
         */
        uint8_t payload[MAPGEN_SUMMARY_MAX];
        uint32_t payload_len = 0;

        mapgen_process_result_t r = MapGenProcess_Receive(
            mapgen->worker, MAPGEN_TICK_WAIT_MS, &header,
            payload, (uint32_t)sizeof(payload), &payload_len);

        if (r == MAPGEN_PROC_ERR_TIMEOUT)
            return;                       /* nothing pending; not a failure */

        if (r != MAPGEN_PROC_OK) {
            /* The worker vanished, or failed in a way a dead child explains.
               If it had staged a result the Controller would still have to
               revalidate and commit before calling that success. */
            MapGenJobs_Diagnostic(mapgen->jobs, id, (uint32_t)r);
            terminate_job(mapgen, id, terminal_for(mapgen, r));
            return;
        }

        switch (header.type) {
        case MAPGEN_IPC_READY:
            break;

        case MAPGEN_IPC_PROGRESS:
            if (payload_len >= 1)
                MapGenJobs_Progress(mapgen->jobs, id, payload[0]);
            break;

        case MAPGEN_IPC_LOG_SUMMARY:
            break;

        case MAPGEN_IPC_CANCELLED:
            terminate_job(mapgen, id, MAPGEN_STATE_CANCELLED);
            return;

        case MAPGEN_IPC_STAGED_RESULT:
            /*
             * NOT success. The worker can only stage; the Controller decides
             * and emits the one terminal event (contract 5.1).
             *
             * What it decides is narrow on purpose. The pipeline's summary
             * says both what the verdict was and whether the artifact may be
             * published, and BOTH have to say yes: a diagnostic run reports
             * every gate it ran and is explicitly not publishable, and a
             * verdict that travelled through here unread would turn one into
             * a product answer.
             */
            mapgen->staged = true;
            copy_bounded(mapgen->summary, sizeof(mapgen->summary),
                         (const char *)payload);
            mapgen->summary_job = id;
            MapGenJobs_Diagnostic(mapgen->jobs, id, MAPGEN_IPC_STAGED_RESULT);
            if (staged_is_publishable(mapgen->summary)) {
                /* The durable-commit boundary the state machine promises: a
                   caller watching it sees the publish, not a job that jumps
                   from running to done. */
/*
                 * Walked, not jumped, and only as far as the verdict accounts
                 * for. PUBLISHING_MAP is not one edge from wherever a job
                 * happens to be, so an advance straight to it moved nothing
                 * and no generate could ever reach SUCCEEDED.
                 */
                if (!summary_accounts_for_route(mapgen->summary)) {
                    MapGenJobs_Diagnostic(mapgen->jobs, id,
                                          MAPGEN_DIAG_VERDICT_INCOMPLETE);
                    terminate_job(mapgen, id, MAPGEN_STATE_FAILED);
                    break;
                }
                if (!walk_to(mapgen, id, MAPGEN_STATE_PUBLISHING_MAP)) {
                    MapGenJobs_Diagnostic(mapgen->jobs, id,
                                          MAPGEN_DIAG_PUBLISH_FAILED);
                    terminate_job(mapgen, id, MAPGEN_STATE_FAILED);
                    break;
                }
                /*
                 * And it publishes. The state used to be the whole of it: the
                 * artifact stayed in the job directory, which the engine does
                 * not search, so a successful generate produced a map nobody
                 * could load.
                 */
                const mapgen_publish_result_t prc =
                    publish_artifact(mapgen);
                if (prc == MAPGEN_PUBLISH_OK &&
                    walk_to(mapgen, id, MAPGEN_STATE_FINALIZING_PROJECT)) {
                    terminate_job(mapgen, id, MAPGEN_STATE_SUCCEEDED);
                } else {
                    /* The reason travels in the low bits, the way the
                       worker exit code already does. */
                    MapGenJobs_Diagnostic(mapgen->jobs, id,
                                          MAPGEN_DIAG_PUBLISH_FAILED
                                          | ((uint32_t)prc & 0xFFFFu));
                    terminate_job(mapgen, id, MAPGEN_STATE_FAILED);
                }
            } else {
                terminate_job(mapgen, id, MAPGEN_STATE_FAILED);
            }
            break;

        case MAPGEN_IPC_ERROR:
            MapGenJobs_Diagnostic(mapgen->jobs, id,
                                  payload_len >= 4 ? (uint32_t)payload[0] : 0);
            terminate_job(mapgen, id, MAPGEN_STATE_FAILED);
            return;

        case MAPGEN_IPC_BYE:
            terminate_job(mapgen, id, MAPGEN_STATE_FAILED);
            return;

        default:
            break;
        }
    }
}

/*
 * What the worker said about what it staged.
 *
 * The verdict, the divergence it measured and the gates it ran are all in
 * here, and without a way to read it the whole of that reached a player as the
 * single word "failed". It answers for the job the summary was written for and
 * no other: one buffer serves every job in turn.
 *
 * False when there is nothing to say - a job that never staged a result, or a
 * job that is not the one this summary describes.
 */
bool MapGen_Summary(const mapgen_t *mapgen, mapgen_job_id_t id,
                    char *out, size_t out_bytes)
{
    if (!out || !out_bytes)
        return false;
    out[0] = '\0';
    if (!mapgen || id == MAPGEN_JOB_ID_NONE || mapgen->summary_job != id)
        return false;
    if (!mapgen->summary[0])
        return false;
    copy_bounded(out, out_bytes, mapgen->summary);
    return true;
}

mapgen_job_id_t MapGen_ActiveJob(const mapgen_t *mapgen)
{
    return mapgen ? MapGenJobs_Active(mapgen->jobs) : MAPGEN_JOB_ID_NONE;
}

bool MapGen_HasWorker(const mapgen_t *mapgen)
{
    return mapgen && mapgen->worker != NULL;
}
