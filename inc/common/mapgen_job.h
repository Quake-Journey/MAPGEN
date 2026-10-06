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

MAPGEN-1 - job state machine and event log

The part of the Controller that has no operating system in it: which states a
request kind may pass through, when cancellation is still possible, and the
promise that every accepted JobId emits exactly one terminal event and never
resumes.

Keeping it pure is deliberate. This is where the contract's hardest guarantees
live (section 5.1), and they must be provable exhaustively rather than through
a running game, a worker process or a compiler.

--- The four promises ------------------------------------------------------

  1. ONE terminal event per accepted JobId, ever.
  2. A terminal JobId never resumes. Retry and `Generate Again` are a NEW
     JobId, a new preflight and a new execution receipt.
  3. Event sequences are monotonic and gapless per job, so `Observe(after)` is
     a cursor and not a guess.
  4. Cancellation is honest about the durable-commit boundary: before it,
     cancel means nothing was published; after it, cancel cannot promise
     rollback and says so.

--- Why a ring that stores its own key -------------------------------------

Job records live in a bounded ring, and each slot stores the JobId it holds.
Every lookup validates that id before returning the slot.

That is not defensive habit, it is Hard Rule #46 written into the data
structure. The Ping-adaptation review found a 128-slot ring indexed by
`sequence & CMD_MASK` that stored no sequence, so a delayed datagram stamped a
slot already reused by `sequence + 128`. A ring indexed by a wrapping counter
without its key is the same bug every time; the fix is always to store the key
and check it on every read.

==============================================================================
*/

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* 0 is never a valid job. A caller holding a zeroed struct addresses nothing
   rather than accidentally addressing job number one. */
typedef uint64_t mapgen_job_id_t;
#define MAPGEN_JOB_ID_NONE  ((mapgen_job_id_t)0)

/* How many finished jobs stay observable. Jobs & Results shows retained
   reports (contract section 21), and a UI that closed and reopened must still
   find the job it was watching. */
#define MAPGEN_JOB_RING_SLOTS   16

/* Bounded per-job event log. Progress is coalesced into the newest event
   rather than growing without limit, so a long job cannot consume memory
   through its own reporting. */
#define MAPGEN_JOB_EVENT_SLOTS  64

typedef enum {
    MAPGEN_REQ_DISCOVER,
    MAPGEN_REQ_PREFLIGHT_TRAIN,
    MAPGEN_REQ_PREFLIGHT_GENERATE,
    MAPGEN_REQ_TRAIN,
    MAPGEN_REQ_GENERATE,
    MAPGEN_REQ_VALIDATE,
    MAPGEN_REQ_RECOVER,
    MAPGEN_REQ_SNAPSHOT_RENAME,
    MAPGEN_REQ_SNAPSHOT_DELETE,

    MAPGEN_REQ_COUNT
} mapgen_request_kind_t;

typedef enum {
    MAPGEN_STATE_QUEUED,
    MAPGEN_STATE_DISCOVERY,
    MAPGEN_STATE_PREFLIGHT,
    MAPGEN_STATE_WARMUP,
    MAPGEN_STATE_ANALYSIS,
    MAPGEN_STATE_TRAINING,
    MAPGEN_STATE_SYNTHESIS,
    MAPGEN_STATE_DRAFT_COMPILE,
    MAPGEN_STATE_DRAFT_VALIDATION,
    MAPGEN_STATE_FINAL_COMPILE,
    MAPGEN_STATE_FINAL_VALIDATION,
    MAPGEN_STATE_VALIDATION,
    MAPGEN_STATE_RECOVERING,

    /* Durable-commit states. Cancellation cannot promise rollback here. */
    MAPGEN_STATE_COMMITTING_SNAPSHOT,
    MAPGEN_STATE_COMMITTING_PROJECT,
    MAPGEN_STATE_PUBLISHING_MAP,
    MAPGEN_STATE_FINALIZING_PROJECT,
    MAPGEN_STATE_COMMITTING_LIBRARY,
    MAPGEN_STATE_DELETING_REVISION,
    MAPGEN_STATE_FINALIZING_CATALOG,

    MAPGEN_STATE_CANCELLING,

    /* Terminal. Exactly one of these is ever emitted per JobId. */
    MAPGEN_STATE_SUCCEEDED,
    MAPGEN_STATE_FAILED,
    MAPGEN_STATE_CANCELLED,
    MAPGEN_STATE_CRASHED,
    MAPGEN_STATE_RECOVERY_REQUIRED,

    MAPGEN_STATE_COUNT
} mapgen_state_t;

typedef enum {
    MAPGEN_SUBMIT_ACCEPTED = 0,
    /* Another mutation job already owns this Controller. Typed, so the UI can
       say which job rather than "try again". */
    MAPGEN_SUBMIT_BUSY,
    MAPGEN_SUBMIT_INVALID_REQUEST,
    MAPGEN_SUBMIT_STALE_INPUT,

    MAPGEN_SUBMIT_RESULT_COUNT
} mapgen_submit_result_t;

typedef enum {
    MAPGEN_CANCEL_ACCEPTED = 0,
    MAPGEN_CANCEL_ALREADY_CANCELLING,
    MAPGEN_CANCEL_ALREADY_TERMINAL,
    /* A durable commit has begun. Cancellation cannot promise rollback, so it
       refuses instead of pretending (contract section 5.1). */
    MAPGEN_CANCEL_TOO_LATE_COMMITTING,
    MAPGEN_CANCEL_UNKNOWN_JOB,

    MAPGEN_CANCEL_RESULT_COUNT
} mapgen_cancel_result_t;

typedef enum {
    MAPGEN_EVENT_STATE = 0,
    MAPGEN_EVENT_PROGRESS,
    MAPGEN_EVENT_DIAGNOSTIC,

    MAPGEN_EVENT_KIND_COUNT
} mapgen_event_kind_t;

typedef struct {
    uint64_t            sequence;     /* monotonic and gapless within a job */
    mapgen_event_kind_t kind;
    mapgen_state_t      state;
    uint8_t             percent;      /* 0..100, meaningful for PROGRESS     */
    uint32_t            code;         /* stable error/diagnostic code        */
} mapgen_job_event_t;

typedef struct {
    mapgen_job_id_t       id;
    mapgen_request_kind_t kind;
    mapgen_state_t        state;
    bool                  terminal;
    bool                  cancel_requested;
    uint8_t               percent;
    uint64_t              last_sequence;
    uint32_t              event_count;   /* events still retained            */
    uint32_t              events_dropped;/* trimmed from the front, honestly */
} mapgen_job_view_t;

typedef struct mapgen_jobs_s mapgen_jobs_t;

/* Create/destroy the job table. Nothing allocates until a job is submitted. */
mapgen_jobs_t *MapGenJobs_Create(void);
void           MapGenJobs_Destroy(mapgen_jobs_t *jobs);

/* Submit a request. On acceptance `out_id` receives a JobId that is never
   reused for the lifetime of this table. */
mapgen_submit_result_t MapGenJobs_Submit(mapgen_jobs_t *jobs,
                                         mapgen_request_kind_t kind,
                                         mapgen_job_id_t *out_id);

/*
 * Drive a job to `next`.
 *
 * Returns false and changes nothing when the transition is not legal for this
 * request kind, when the job is already terminal, or when the id does not
 * address a live slot. A refused transition is a caller bug, not a state.
 */
bool MapGenJobs_Advance(mapgen_jobs_t *jobs, mapgen_job_id_t id, mapgen_state_t next);

/* Report progress inside the current state. Coalesced into one event. */
bool MapGenJobs_Progress(mapgen_jobs_t *jobs, mapgen_job_id_t id, uint8_t percent);

/* Record a diagnostic without changing state. */
bool MapGenJobs_Diagnostic(mapgen_jobs_t *jobs, mapgen_job_id_t id, uint32_t code);

mapgen_cancel_result_t MapGenJobs_Cancel(mapgen_jobs_t *jobs, mapgen_job_id_t id);

/* Immutable view. Returns false for an id this table does not hold - including
   one whose slot has since been reused by a newer job. */
bool MapGenJobs_Observe(const mapgen_jobs_t *jobs, mapgen_job_id_t id,
                        mapgen_job_view_t *out_view);

/*
 * Copy events strictly after `after_sequence`, oldest first.
 *
 * Returns the number written. `out_missed` reports how many events the caller
 * can never see because they were trimmed before it asked - a cursor that
 * silently skips is worse than one that admits the gap.
 */
uint32_t MapGenJobs_Events(const mapgen_jobs_t *jobs, mapgen_job_id_t id,
                           uint64_t after_sequence,
                           mapgen_job_event_t *out, uint32_t out_capacity,
                           uint32_t *out_missed);

/* The single foreground job, or MAPGEN_JOB_ID_NONE. Argument-less menu
   actions, `mapgen_status` and `mapgen_cancel` address this one. */
mapgen_job_id_t MapGenJobs_Active(const mapgen_jobs_t *jobs);

bool MapGenState_IsTerminal(mapgen_state_t state);
/* True while a durable commit is in progress: cancellation cannot promise
   rollback from here. */
bool MapGenState_IsCommitting(mapgen_state_t state);

const char *MapGenState_Name(mapgen_state_t state);
const char *MapGenRequest_Name(mapgen_request_kind_t kind);
const char *MapGenSubmit_Name(mapgen_submit_result_t result);
const char *MapGenCancel_Name(mapgen_cancel_result_t result);
