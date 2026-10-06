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
==============================================================================

MAPGEN-1 - the external Interface

This is the ONLY Seam the rest of Q2PRO-X may use. The menus, the console
commands and the integration tests all go through these three calls and none
of them knows that a worker process, a pipe, a compiler, a SnapshotStore or a
GPU exists (contract section 5.1).

    MapGen_Submit    validate, deep-copy, accept or refuse
    MapGen_Observe   nonblocking; an immutable view plus ordered events
    MapGen_Cancel    idempotent, and honest about the durable-commit boundary

Everything else in the feature is an implementation detail behind them.

--- Two semantics that break a naive implementation ------------------------

`SUCCEEDED` for Training means the new snapshot revision is ALREADY atomically
committed. `SUCCEEDED` for Generation means the BSP has ALREADY been rechecked
by the Controller and published. There is no externally visible state that
means "succeeded but not yet published".

A terminal JobId never resumes. Retry and `Generate Again` are a new JobId, a
new preflight and a new one-time execution receipt.

--- Off-state costs nothing ------------------------------------------------

Contract section 2.11: no background scan, worker, GPU context or compiler
process exists until the user starts a Map Generator operation. Creating the
Controller starts nothing. Ticking an idle Controller does nothing. This is a
promise the tests measure, not a habit.

==============================================================================
*/

#pragma once

#include "common/mapgen_job.h"
/* For MAPGEN_IPC_SUMMARY_MAX: the staged verdict is a frame, and its bound
   belongs to the protocol that carries it. */
#include "common/mapgen_protocol.h"

#include <stdbool.h>
#include <stdint.h>

#define MAPGEN_MAX_EVENTS_PER_OBSERVE   32

typedef struct {
    /* Absolute path of the packaged worker helper. */
    const char *worker_exe_path;
    /* Directory the worker runs in; must exist. */
    const char *work_dir;
    /* The build id this Controller accepts from a worker. */
    const char *expected_build_id;
    /* Milliseconds a worker gets to answer HELLO. 0 uses the default. */
    uint32_t    handshake_timeout_ms;
    /*
     * Where the things a request NAMES actually live, and the pinned compiler
     * the worker must use. These are the product's own, fixed at install and
     * never typed by a user - which is what lets a request carry names.
     */
    const char *maps_dir;
    const char *snapshots_dir;
    const char *moddir;
    const char *compiler_path;
} mapgen_config_t;

/*
 * An immutable request. `Submit` deep-copies everything it needs; no caller
 * supplies an OS path and nothing here is a shell fragment (contract 5.1).
 *
 * At M1 the payloads are still empty: the request KINDS and their lifecycle
 * are what this milestone owns. Snapshot selections, recipes and receipts
 * arrive with the milestones that can honour them, so that an unfinished field
 * never sits in a shipped struct pretending to work.
 */
#define MAPGEN_REQUEST_NAME   64

/*
 * How long a rendered job may be, and how much of a worker's answer is kept.
 *
 * The worker holds 8192 bytes of a START payload and refuses anything larger,
 * so a Controller that could render more would be building requests nobody can
 * accept. The summary is the worker's own bound.
 */
/*
 * A diagnostic code that is a worker exit status, not a protocol code.
 *
 * They share one channel because they answer the same question - what ended
 * this job - and a reader that could not tell them apart would read an exit
 * code of 3 as the protocol's third error.
 */
#define MAPGEN_DIAG_WORKER_EXIT  0x00010000u

/* The verdict said publish and the artifact did not reach the maps directory.
   The job fails: a publish that did not publish is not a success. */
#define MAPGEN_DIAG_PUBLISH_FAILED  0x00020000u

/* The verdict said publish, and did not account for the stages a generate
   passes through on the way there. The Controller does not walk a job past a
   stage nobody can show happened. */
#define MAPGEN_DIAG_VERDICT_INCOMPLETE  0x00040000u

#define MAPGEN_JOB_REQUEST_MAX   8192
/* The protocol's bound, because this is a bound on a frame the protocol
   carries and two spellings of one number is what let them disagree. */
#define MAPGEN_SUMMARY_MAX       MAPGEN_IPC_SUMMARY_MAX

/*
 * What a generation actually is.
 *
 * Names, not paths. The caller says which map to fork and which snapshot to
 * learn from; the Controller resolves both under the directories it was
 * configured with. Contract 5.1: no caller supplies an OS path, and nothing
 * here is a shell fragment.
 *
 * `fidelity` 100 is the donor exactly and 0 invents a map out of what a corpus
 * taught - which needs `snapshot` and can use neither donor geometry nor an
 * empty one, so a zero request without a snapshot is refused rather than
 * quietly forked.
 */
typedef struct {
    char     donor_map[MAPGEN_REQUEST_NAME];
    char     snapshot[MAPGEN_REQUEST_NAME];
    char     map_name[MAPGEN_REQUEST_NAME];
    int32_t  fidelity;
    uint64_t seed;
    int32_t  scale;          /* 0 compact .. 3 very large, fidelity zero    */
    int32_t  goal;           /* mapgen_goal_t, fidelity zero                */
    uint32_t max_attempts;   /* 0 is the schedule's own length              */
    bool     final_profile;  /* vis and light as well as bsp                */
} mapgen_generate_request_t;

typedef struct {
    mapgen_request_kind_t kind;
    /* Generation only; ignored by every other kind. */
    mapgen_generate_request_t generate;
} mapgen_request_t;

typedef struct {
    mapgen_job_view_t  view;
    mapgen_job_event_t events[MAPGEN_MAX_EVENTS_PER_OBSERVE];
    uint32_t           event_count;
    /* Events trimmed before the caller asked for them. A cursor that silently
       skips is worse than one that admits the gap. */
    uint32_t           events_missed;
} mapgen_observation_t;

typedef struct mapgen_s mapgen_t;

/* Create the Controller. Starts NO process and opens NO handle. */
mapgen_t *MapGen_Create(const mapgen_config_t *config);

/* Destroy it, stopping any worker it owns. After this call nothing it started
   is running. */
void MapGen_Destroy(mapgen_t *mapgen);

mapgen_submit_result_t MapGen_Submit(mapgen_t *mapgen,
                                     const mapgen_request_t *request,
                                     mapgen_job_id_t *out_id);

bool MapGen_Observe(mapgen_t *mapgen, mapgen_job_id_t id,
                    uint64_t after_sequence, mapgen_observation_t *out);

mapgen_cancel_result_t MapGen_Cancel(mapgen_t *mapgen, mapgen_job_id_t id);

/*
 * Pump the worker. Nonblocking by contract: it drains at most a bounded number
 * of frames and returns, so it can be called from the client frame loop
 * without ever holding it (contract section 2.12).
 *
 * On an idle Controller this does nothing at all.
 */
void MapGen_Tick(mapgen_t *mapgen);

/* The single foreground job, or MAPGEN_JOB_ID_NONE. */
mapgen_job_id_t MapGen_ActiveJob(const mapgen_t *mapgen);

/*
 * The worker's own account of what it staged, for the job it describes.
 *
 * `key value` lines: the verdict, the artifact it built, the divergence it
 * measured against the band it was aiming at, and the counts every gate
 * produced. It is evidence, not a decision - the Controller has already
 * decided by the time anyone can read this, and reading it cannot change the
 * terminal state.
 *
 * False when there is nothing to say: a job that never staged a result, or an
 * id other than the one the kept summary belongs to.
 */
bool MapGen_Summary(const mapgen_t *mapgen, mapgen_job_id_t id,
                    char *out, size_t out_bytes);

/* True while this Controller owns a live worker process. The off-state promise
   is that this is false until a job needs one, and false again afterwards. */
bool MapGen_HasWorker(const mapgen_t *mapgen);
