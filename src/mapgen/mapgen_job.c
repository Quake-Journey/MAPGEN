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
 * MAPGEN-1 - job state machine and event log.
 *
 * Pure: no OS, no engine, no allocation outside create/destroy. Contract
 * section 5.1.
 */

#include "common/mapgen_job.h"

#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------------ */

typedef struct {
    mapgen_job_id_t       id;          /* the slot's KEY; 0 means empty      */
    mapgen_request_kind_t kind;
    mapgen_state_t        state;
    bool                  cancel_requested;
    uint8_t               percent;

    uint64_t              next_sequence;
    uint32_t              event_count;
    uint32_t              event_head;   /* index of the oldest retained event */
    uint32_t              events_dropped;
    mapgen_job_event_t    events[MAPGEN_JOB_EVENT_SLOTS];
} mapgen_job_slot_t;

struct mapgen_jobs_s {
    mapgen_job_slot_t slots[MAPGEN_JOB_RING_SLOTS];
    uint32_t          next_slot;
    mapgen_job_id_t   next_id;
    mapgen_job_id_t   active;
};

/* ------------------------------------------------------------------------ */

bool MapGenState_IsTerminal(mapgen_state_t state)
{
    switch (state) {
    case MAPGEN_STATE_SUCCEEDED:
    case MAPGEN_STATE_FAILED:
    case MAPGEN_STATE_CANCELLED:
    case MAPGEN_STATE_CRASHED:
    case MAPGEN_STATE_RECOVERY_REQUIRED:
        return true;
    default:
        return false;
    }
}

bool MapGenState_IsCommitting(mapgen_state_t state)
{
    switch (state) {
    case MAPGEN_STATE_COMMITTING_SNAPSHOT:
    case MAPGEN_STATE_COMMITTING_PROJECT:
    case MAPGEN_STATE_PUBLISHING_MAP:
    case MAPGEN_STATE_FINALIZING_PROJECT:
    case MAPGEN_STATE_COMMITTING_LIBRARY:
    case MAPGEN_STATE_DELETING_REVISION:
    case MAPGEN_STATE_FINALIZING_CATALOG:
    /* RECOVER begins INSIDE the durable-commit boundary and is
       noncancellable for its whole life (contract section 5.1). */
    case MAPGEN_STATE_RECOVERING:
        return true;
    default:
        return false;
    }
}

/*
 * The canonical state machines, one row per request kind, exactly as contract
 * section 5.1 writes them. A transition not listed here is refused.
 *
 * They are spelled out as data rather than as branches so the whole machine
 * can be enumerated by a test: every kind, every state, every possible next
 * state.
 */
typedef struct {
    mapgen_state_t from;
    mapgen_state_t to;
} mapgen_edge_t;

static const mapgen_edge_t edges_discover[] = {
    { MAPGEN_STATE_QUEUED,    MAPGEN_STATE_DISCOVERY },
    { MAPGEN_STATE_DISCOVERY, MAPGEN_STATE_SUCCEEDED },
};

static const mapgen_edge_t edges_preflight[] = {
    { MAPGEN_STATE_QUEUED,    MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_STATE_PREFLIGHT, MAPGEN_STATE_SUCCEEDED },
};

static const mapgen_edge_t edges_train[] = {
    { MAPGEN_STATE_QUEUED,              MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_STATE_PREFLIGHT,           MAPGEN_STATE_WARMUP },
    { MAPGEN_STATE_WARMUP,              MAPGEN_STATE_ANALYSIS },
    { MAPGEN_STATE_ANALYSIS,            MAPGEN_STATE_TRAINING },
    { MAPGEN_STATE_TRAINING,            MAPGEN_STATE_COMMITTING_SNAPSHOT },
    { MAPGEN_STATE_COMMITTING_SNAPSHOT, MAPGEN_STATE_SUCCEEDED },
    /* An interrupted commit reconciles rather than guessing. */
    { MAPGEN_STATE_COMMITTING_SNAPSHOT, MAPGEN_STATE_RECOVERING },
};

static const mapgen_edge_t edges_generate[] = {
    { MAPGEN_STATE_QUEUED,             MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_STATE_PREFLIGHT,          MAPGEN_STATE_WARMUP },
    { MAPGEN_STATE_WARMUP,             MAPGEN_STATE_SYNTHESIS },
    { MAPGEN_STATE_SYNTHESIS,          MAPGEN_STATE_DRAFT_COMPILE },
    { MAPGEN_STATE_DRAFT_COMPILE,      MAPGEN_STATE_DRAFT_VALIDATION },
    /* A repaired candidate invalidates every compiled artifact and starts a
       fresh attempt (contract section 16 step 14). */
    { MAPGEN_STATE_DRAFT_VALIDATION,   MAPGEN_STATE_SYNTHESIS },
    { MAPGEN_STATE_DRAFT_VALIDATION,   MAPGEN_STATE_FINAL_COMPILE },
    { MAPGEN_STATE_FINAL_COMPILE,      MAPGEN_STATE_FINAL_VALIDATION },
    { MAPGEN_STATE_FINAL_VALIDATION,   MAPGEN_STATE_COMMITTING_PROJECT },
    { MAPGEN_STATE_COMMITTING_PROJECT, MAPGEN_STATE_PUBLISHING_MAP },
    { MAPGEN_STATE_PUBLISHING_MAP,     MAPGEN_STATE_FINALIZING_PROJECT },
    { MAPGEN_STATE_FINALIZING_PROJECT, MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_STATE_COMMITTING_PROJECT, MAPGEN_STATE_RECOVERING },
    { MAPGEN_STATE_PUBLISHING_MAP,     MAPGEN_STATE_RECOVERING },
    { MAPGEN_STATE_FINALIZING_PROJECT, MAPGEN_STATE_RECOVERING },
};

static const mapgen_edge_t edges_validate[] = {
    { MAPGEN_STATE_QUEUED,     MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_STATE_PREFLIGHT,  MAPGEN_STATE_VALIDATION },
    { MAPGEN_STATE_VALIDATION, MAPGEN_STATE_SUCCEEDED },
};

static const mapgen_edge_t edges_recover[] = {
    { MAPGEN_STATE_QUEUED,     MAPGEN_STATE_RECOVERING },
    { MAPGEN_STATE_RECOVERING, MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_STATE_RECOVERING, MAPGEN_STATE_FAILED },
    { MAPGEN_STATE_RECOVERING, MAPGEN_STATE_RECOVERY_REQUIRED },
};

static const mapgen_edge_t edges_rename[] = {
    { MAPGEN_STATE_QUEUED,              MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_STATE_PREFLIGHT,           MAPGEN_STATE_COMMITTING_SNAPSHOT },
    { MAPGEN_STATE_COMMITTING_SNAPSHOT, MAPGEN_STATE_FINALIZING_CATALOG },
    { MAPGEN_STATE_FINALIZING_CATALOG,  MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_STATE_COMMITTING_SNAPSHOT, MAPGEN_STATE_RECOVERING },
    { MAPGEN_STATE_FINALIZING_CATALOG,  MAPGEN_STATE_RECOVERING },
};

static const mapgen_edge_t edges_delete[] = {
    { MAPGEN_STATE_QUEUED,             MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_STATE_PREFLIGHT,          MAPGEN_STATE_COMMITTING_LIBRARY },
    { MAPGEN_STATE_COMMITTING_LIBRARY, MAPGEN_STATE_DELETING_REVISION },
    { MAPGEN_STATE_DELETING_REVISION,  MAPGEN_STATE_FINALIZING_CATALOG },
    { MAPGEN_STATE_FINALIZING_CATALOG, MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_STATE_COMMITTING_LIBRARY, MAPGEN_STATE_RECOVERING },
    { MAPGEN_STATE_DELETING_REVISION,  MAPGEN_STATE_RECOVERING },
    { MAPGEN_STATE_FINALIZING_CATALOG, MAPGEN_STATE_RECOVERING },
};

typedef struct {
    const mapgen_edge_t *edges;
    size_t               count;
} mapgen_machine_t;

#define MACHINE(a) { a, sizeof(a) / sizeof((a)[0]) }

static const mapgen_machine_t machines[MAPGEN_REQ_COUNT] = {
    [MAPGEN_REQ_DISCOVER]           = MACHINE(edges_discover),
    [MAPGEN_REQ_PREFLIGHT_TRAIN]    = MACHINE(edges_preflight),
    [MAPGEN_REQ_PREFLIGHT_GENERATE] = MACHINE(edges_preflight),
    [MAPGEN_REQ_TRAIN]              = MACHINE(edges_train),
    [MAPGEN_REQ_GENERATE]           = MACHINE(edges_generate),
    [MAPGEN_REQ_VALIDATE]           = MACHINE(edges_validate),
    [MAPGEN_REQ_RECOVER]            = MACHINE(edges_recover),
    [MAPGEN_REQ_SNAPSHOT_RENAME]    = MACHINE(edges_rename),
    [MAPGEN_REQ_SNAPSHOT_DELETE]    = MACHINE(edges_delete),
};

/*
 * Universal edges, legal for every kind:
 *
 *   any cancellable state -> CANCELLING -> CANCELLED
 *   any pre-commit state  -> FAILED / CRASHED
 *
 * A durable commit may NOT jump to FAILED: once the commit began, the outcome
 * is decided by reconciliation, not by giving up (contract section 5.1). It
 * goes through RECOVERING, whose terminal outcomes each mean something exact.
 */
static bool universal_edge(const mapgen_job_slot_t *slot, mapgen_state_t next)
{
    /* No terminal check here on purpose. `edge_allowed` already refuses every
       transition out of a terminal state, and a second copy of that rule would
       mean neither copy could be proven: a controlled RED that deletes one
       leaves the other still refusing, and the guard looks green while the
       promise has lost half its enforcement. One rule, one place. */

    if (next == MAPGEN_STATE_CANCELLING)
        return !MapGenState_IsCommitting(slot->state) && slot->state != MAPGEN_STATE_CANCELLING;

    if (next == MAPGEN_STATE_CANCELLED)
        return slot->state == MAPGEN_STATE_CANCELLING;

    if (next == MAPGEN_STATE_FAILED || next == MAPGEN_STATE_CRASHED)
        return !MapGenState_IsCommitting(slot->state);

    /* RECOVERING's own terminal outcomes are declared per kind, because what
       they MEAN differs: for Generate, FAILED means nothing was published. */
    return false;
}

static bool edge_allowed(const mapgen_job_slot_t *slot, mapgen_state_t next)
{
    if (slot->kind >= MAPGEN_REQ_COUNT)
        return false;
    if (next >= MAPGEN_STATE_COUNT)
        return false;
    if (MapGenState_IsTerminal(slot->state))
        return false;   /* a terminal JobId never resumes */

    const mapgen_machine_t *m = &machines[slot->kind];
    for (size_t i = 0; i < m->count; i++) {
        if (m->edges[i].from == slot->state && m->edges[i].to == next)
            return true;
    }
    /* RECOVERING can end for any kind that can enter it. */
    if (slot->state == MAPGEN_STATE_RECOVERING &&
        (next == MAPGEN_STATE_SUCCEEDED || next == MAPGEN_STATE_FAILED ||
         next == MAPGEN_STATE_RECOVERY_REQUIRED))
        return true;

    return universal_edge(slot, next);
}

/* ------------------------------------------------------------------------ */

static mapgen_job_slot_t *find_slot(mapgen_jobs_t *jobs, mapgen_job_id_t id)
{
    if (!jobs || id == MAPGEN_JOB_ID_NONE)
        return NULL;
    for (uint32_t i = 0; i < MAPGEN_JOB_RING_SLOTS; i++) {
        /* The slot carries its own key and it is checked on EVERY read. A
           ring indexed by a wrapping counter without this is the reused-slot
           defect from Hard Rule #46. */
        if (jobs->slots[i].id == id)
            return &jobs->slots[i];
    }
    return NULL;
}

static const mapgen_job_slot_t *find_slot_const(const mapgen_jobs_t *jobs, mapgen_job_id_t id)
{
    return find_slot((mapgen_jobs_t *)jobs, id);
}

static void push_event(mapgen_job_slot_t *slot, mapgen_event_kind_t kind,
                       mapgen_state_t state, uint8_t percent, uint32_t code)
{
    if (slot->event_count == MAPGEN_JOB_EVENT_SLOTS) {
        /* Drop the OLDEST and say so. A cursor that silently skips is worse
           than one that admits the gap. */
        slot->event_head = (slot->event_head + 1) % MAPGEN_JOB_EVENT_SLOTS;
        slot->event_count--;
        slot->events_dropped++;
    }
    uint32_t index = (slot->event_head + slot->event_count) % MAPGEN_JOB_EVENT_SLOTS;
    mapgen_job_event_t *e = &slot->events[index];
    e->sequence = slot->next_sequence++;
    e->kind = kind;
    e->state = state;
    e->percent = percent;
    e->code = code;
    slot->event_count++;
}

/* ------------------------------------------------------------------------ */

mapgen_jobs_t *MapGenJobs_Create(void)
{
    mapgen_jobs_t *jobs = calloc(1, sizeof(*jobs));
    if (!jobs)
        return NULL;
    jobs->next_id = 1;
    jobs->active = MAPGEN_JOB_ID_NONE;
    return jobs;
}

void MapGenJobs_Destroy(mapgen_jobs_t *jobs)
{
    free(jobs);
}

mapgen_submit_result_t MapGenJobs_Submit(mapgen_jobs_t *jobs,
                                         mapgen_request_kind_t kind,
                                         mapgen_job_id_t *out_id)
{
    if (out_id)
        *out_id = MAPGEN_JOB_ID_NONE;
    if (!jobs || kind >= MAPGEN_REQ_COUNT)
        return MAPGEN_SUBMIT_INVALID_REQUEST;

    /* One foreground job, so an argument-less menu action or console command
       always addresses an unambiguous job (contract section 5.1). */
    if (jobs->active != MAPGEN_JOB_ID_NONE) {
        const mapgen_job_slot_t *slot = find_slot_const(jobs, jobs->active);
        if (slot && !MapGenState_IsTerminal(slot->state))
            return MAPGEN_SUBMIT_BUSY;
    }

    mapgen_job_slot_t *slot = &jobs->slots[jobs->next_slot];
    jobs->next_slot = (jobs->next_slot + 1) % MAPGEN_JOB_RING_SLOTS;

    memset(slot, 0, sizeof(*slot));
    slot->id = jobs->next_id++;      /* never reused */
    slot->kind = kind;
    slot->state = MAPGEN_STATE_QUEUED;

    push_event(slot, MAPGEN_EVENT_STATE, MAPGEN_STATE_QUEUED, 0, 0);

    jobs->active = slot->id;
    if (out_id)
        *out_id = slot->id;
    return MAPGEN_SUBMIT_ACCEPTED;
}

bool MapGenJobs_Advance(mapgen_jobs_t *jobs, mapgen_job_id_t id, mapgen_state_t next)
{
    mapgen_job_slot_t *slot = find_slot(jobs, id);
    if (!slot)
        return false;
    if (!edge_allowed(slot, next))
        return false;

    slot->state = next;
    if (next == MAPGEN_STATE_CANCELLING)
        slot->cancel_requested = true;
    push_event(slot, MAPGEN_EVENT_STATE, next, slot->percent, 0);

    if (MapGenState_IsTerminal(next) && jobs->active == id)
        jobs->active = MAPGEN_JOB_ID_NONE;
    return true;
}

bool MapGenJobs_Progress(mapgen_jobs_t *jobs, mapgen_job_id_t id, uint8_t percent)
{
    mapgen_job_slot_t *slot = find_slot(jobs, id);
    if (!slot || MapGenState_IsTerminal(slot->state))
        return false;
    if (percent > 100)
        percent = 100;
    slot->percent = percent;
    push_event(slot, MAPGEN_EVENT_PROGRESS, slot->state, percent, 0);
    return true;
}

bool MapGenJobs_Diagnostic(mapgen_jobs_t *jobs, mapgen_job_id_t id, uint32_t code)
{
    mapgen_job_slot_t *slot = find_slot(jobs, id);
    if (!slot)
        return false;
    push_event(slot, MAPGEN_EVENT_DIAGNOSTIC, slot->state, slot->percent, code);
    return true;
}

mapgen_cancel_result_t MapGenJobs_Cancel(mapgen_jobs_t *jobs, mapgen_job_id_t id)
{
    mapgen_job_slot_t *slot = find_slot(jobs, id);
    if (!slot)
        return MAPGEN_CANCEL_UNKNOWN_JOB;
    if (MapGenState_IsTerminal(slot->state))
        return MAPGEN_CANCEL_ALREADY_TERMINAL;
    if (slot->state == MAPGEN_STATE_CANCELLING)
        return MAPGEN_CANCEL_ALREADY_CANCELLING;
    if (MapGenState_IsCommitting(slot->state))
        return MAPGEN_CANCEL_TOO_LATE_COMMITTING;

    slot->state = MAPGEN_STATE_CANCELLING;
    slot->cancel_requested = true;
    push_event(slot, MAPGEN_EVENT_STATE, MAPGEN_STATE_CANCELLING, slot->percent, 0);
    return MAPGEN_CANCEL_ACCEPTED;
}

bool MapGenJobs_Observe(const mapgen_jobs_t *jobs, mapgen_job_id_t id,
                        mapgen_job_view_t *out_view)
{
    const mapgen_job_slot_t *slot = find_slot_const(jobs, id);
    if (!slot || !out_view)
        return false;

    memset(out_view, 0, sizeof(*out_view));
    out_view->id = slot->id;
    out_view->kind = slot->kind;
    out_view->state = slot->state;
    out_view->terminal = MapGenState_IsTerminal(slot->state);
    out_view->cancel_requested = slot->cancel_requested;
    out_view->percent = slot->percent;
    out_view->last_sequence = slot->next_sequence ? slot->next_sequence - 1 : 0;
    out_view->event_count = slot->event_count;
    out_view->events_dropped = slot->events_dropped;
    return true;
}

uint32_t MapGenJobs_Events(const mapgen_jobs_t *jobs, mapgen_job_id_t id,
                           uint64_t after_sequence,
                           mapgen_job_event_t *out, uint32_t out_capacity,
                           uint32_t *out_missed)
{
    if (out_missed)
        *out_missed = 0;
    const mapgen_job_slot_t *slot = find_slot_const(jobs, id);
    if (!slot || !out || !out_capacity)
        return 0;

    uint32_t written = 0;
    uint32_t missed = 0;
    for (uint32_t i = 0; i < slot->event_count; i++) {
        const mapgen_job_event_t *e =
            &slot->events[(slot->event_head + i) % MAPGEN_JOB_EVENT_SLOTS];
        if (e->sequence <= after_sequence)
            continue;
        if (written == out_capacity)
            break;
        out[written++] = *e;
    }

    /* Everything the caller asked for that has already been trimmed. */
    uint64_t oldest_retained = slot->event_count
        ? slot->events[slot->event_head].sequence
        : slot->next_sequence;
    if (oldest_retained > after_sequence + 1)
        missed = (uint32_t)(oldest_retained - (after_sequence + 1));
    if (out_missed)
        *out_missed = missed;
    return written;
}

mapgen_job_id_t MapGenJobs_Active(const mapgen_jobs_t *jobs)
{
    return jobs ? jobs->active : MAPGEN_JOB_ID_NONE;
}

/* ------------------------------------------------------------------------ */

const char *MapGenState_Name(mapgen_state_t state)
{
    switch (state) {
    case MAPGEN_STATE_QUEUED:              return "QUEUED";
    case MAPGEN_STATE_DISCOVERY:           return "DISCOVERY";
    case MAPGEN_STATE_PREFLIGHT:           return "PREFLIGHT";
    case MAPGEN_STATE_WARMUP:              return "WARMUP";
    case MAPGEN_STATE_ANALYSIS:            return "ANALYSIS";
    case MAPGEN_STATE_TRAINING:            return "TRAINING";
    case MAPGEN_STATE_SYNTHESIS:           return "SYNTHESIS";
    case MAPGEN_STATE_DRAFT_COMPILE:       return "DRAFT_COMPILE";
    case MAPGEN_STATE_DRAFT_VALIDATION:    return "DRAFT_VALIDATION";
    case MAPGEN_STATE_FINAL_COMPILE:       return "FINAL_COMPILE";
    case MAPGEN_STATE_FINAL_VALIDATION:    return "FINAL_VALIDATION";
    case MAPGEN_STATE_VALIDATION:          return "VALIDATION";
    case MAPGEN_STATE_RECOVERING:          return "RECOVERING";
    case MAPGEN_STATE_COMMITTING_SNAPSHOT: return "COMMITTING_SNAPSHOT";
    case MAPGEN_STATE_COMMITTING_PROJECT:  return "COMMITTING_PROJECT";
    case MAPGEN_STATE_PUBLISHING_MAP:      return "PUBLISHING_MAP";
    case MAPGEN_STATE_FINALIZING_PROJECT:  return "FINALIZING_PROJECT";
    case MAPGEN_STATE_COMMITTING_LIBRARY:  return "COMMITTING_LIBRARY";
    case MAPGEN_STATE_DELETING_REVISION:   return "DELETING_REVISION";
    case MAPGEN_STATE_FINALIZING_CATALOG:  return "FINALIZING_CATALOG";
    case MAPGEN_STATE_CANCELLING:          return "CANCELLING";
    case MAPGEN_STATE_SUCCEEDED:           return "SUCCEEDED";
    case MAPGEN_STATE_FAILED:              return "FAILED";
    case MAPGEN_STATE_CANCELLED:           return "CANCELLED";
    case MAPGEN_STATE_CRASHED:             return "CRASHED";
    case MAPGEN_STATE_RECOVERY_REQUIRED:   return "RECOVERY_REQUIRED";
    default:                               return "UNKNOWN";
    }
}

const char *MapGenRequest_Name(mapgen_request_kind_t kind)
{
    switch (kind) {
    case MAPGEN_REQ_DISCOVER:           return "DISCOVER";
    case MAPGEN_REQ_PREFLIGHT_TRAIN:    return "PREFLIGHT_TRAIN";
    case MAPGEN_REQ_PREFLIGHT_GENERATE: return "PREFLIGHT_GENERATE";
    case MAPGEN_REQ_TRAIN:              return "TRAIN";
    case MAPGEN_REQ_GENERATE:           return "GENERATE";
    case MAPGEN_REQ_VALIDATE:           return "VALIDATE";
    case MAPGEN_REQ_RECOVER:            return "RECOVER";
    case MAPGEN_REQ_SNAPSHOT_RENAME:    return "SNAPSHOT_RENAME";
    case MAPGEN_REQ_SNAPSHOT_DELETE:    return "SNAPSHOT_DELETE";
    default:                            return "UNKNOWN";
    }
}

const char *MapGenSubmit_Name(mapgen_submit_result_t result)
{
    switch (result) {
    case MAPGEN_SUBMIT_ACCEPTED:        return "ACCEPTED";
    case MAPGEN_SUBMIT_BUSY:            return "BUSY";
    case MAPGEN_SUBMIT_INVALID_REQUEST: return "INVALID_REQUEST";
    case MAPGEN_SUBMIT_STALE_INPUT:     return "STALE_INPUT";
    default:                            return "UNKNOWN";
    }
}

const char *MapGenCancel_Name(mapgen_cancel_result_t result)
{
    switch (result) {
    case MAPGEN_CANCEL_ACCEPTED:            return "ACCEPTED";
    case MAPGEN_CANCEL_ALREADY_CANCELLING:  return "ALREADY_CANCELLING";
    case MAPGEN_CANCEL_ALREADY_TERMINAL:    return "ALREADY_TERMINAL";
    case MAPGEN_CANCEL_TOO_LATE_COMMITTING: return "TOO_LATE_COMMITTING";
    case MAPGEN_CANCEL_UNKNOWN_JOB:         return "UNKNOWN_JOB";
    default:                                return "UNKNOWN";
    }
}
