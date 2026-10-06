/*
 * MAPGEN-1 job state machine - self-asserting test.
 *
 * Compiled and run by tools/check_mapgen_job_contract.py with a targeted
 * throwaway gcc invocation.
 *
 * The transition oracle below is written INDEPENDENTLY from contract section
 * 5.1, not derived from the implementation's tables. That duplication is the
 * whole point: two separate statements of the same contract must agree, and
 * checking a table against itself proves only that it is a table.
 *
 * Every case asserts and prints one PASS/FAIL line.
 */

#include "common/mapgen_job.h"

#include <stdio.h>
#include <string.h>

static int g_cases;
static int g_failed;

static void ck(const char *name, bool ok, const char *detail)
{
    g_cases++;
    if (ok) {
        printf("  PASS  %s\n", name);
    } else {
        printf("  FAIL  %s%s%s\n", name, detail && *detail ? "  -- " : "", detail ? detail : "");
        g_failed++;
    }
}

/* ------------------------------------------------------------------------ */
/* Independent oracle, transcribed from contract section 5.1                 */
/* ------------------------------------------------------------------------ */

typedef struct {
    mapgen_request_kind_t kind;
    mapgen_state_t from;
    mapgen_state_t to;
} triple_t;

static const triple_t oracle[] = {
    /* DISCOVER: QUEUED -> DISCOVERY -> SUCCEEDED */
    { MAPGEN_REQ_DISCOVER, MAPGEN_STATE_QUEUED,    MAPGEN_STATE_DISCOVERY },
    { MAPGEN_REQ_DISCOVER, MAPGEN_STATE_DISCOVERY, MAPGEN_STATE_SUCCEEDED },

    /* PREFLIGHT_TRAIN / PREFLIGHT_GENERATE: QUEUED -> PREFLIGHT -> SUCCEEDED */
    { MAPGEN_REQ_PREFLIGHT_TRAIN,    MAPGEN_STATE_QUEUED,    MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_REQ_PREFLIGHT_TRAIN,    MAPGEN_STATE_PREFLIGHT, MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_REQ_PREFLIGHT_GENERATE, MAPGEN_STATE_QUEUED,    MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_REQ_PREFLIGHT_GENERATE, MAPGEN_STATE_PREFLIGHT, MAPGEN_STATE_SUCCEEDED },

    /* TRAIN */
    { MAPGEN_REQ_TRAIN, MAPGEN_STATE_QUEUED,              MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_REQ_TRAIN, MAPGEN_STATE_PREFLIGHT,           MAPGEN_STATE_WARMUP },
    { MAPGEN_REQ_TRAIN, MAPGEN_STATE_WARMUP,              MAPGEN_STATE_ANALYSIS },
    { MAPGEN_REQ_TRAIN, MAPGEN_STATE_ANALYSIS,            MAPGEN_STATE_TRAINING },
    { MAPGEN_REQ_TRAIN, MAPGEN_STATE_TRAINING,            MAPGEN_STATE_COMMITTING_SNAPSHOT },
    { MAPGEN_REQ_TRAIN, MAPGEN_STATE_COMMITTING_SNAPSHOT, MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_REQ_TRAIN, MAPGEN_STATE_COMMITTING_SNAPSHOT, MAPGEN_STATE_RECOVERING },

    /* GENERATE */
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_QUEUED,             MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_PREFLIGHT,          MAPGEN_STATE_WARMUP },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_WARMUP,             MAPGEN_STATE_SYNTHESIS },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_SYNTHESIS,          MAPGEN_STATE_DRAFT_COMPILE },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_DRAFT_COMPILE,      MAPGEN_STATE_DRAFT_VALIDATION },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_DRAFT_VALIDATION,   MAPGEN_STATE_SYNTHESIS },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_DRAFT_VALIDATION,   MAPGEN_STATE_FINAL_COMPILE },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_FINAL_COMPILE,      MAPGEN_STATE_FINAL_VALIDATION },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_FINAL_VALIDATION,   MAPGEN_STATE_COMMITTING_PROJECT },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_COMMITTING_PROJECT, MAPGEN_STATE_PUBLISHING_MAP },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_PUBLISHING_MAP,     MAPGEN_STATE_FINALIZING_PROJECT },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_FINALIZING_PROJECT, MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_COMMITTING_PROJECT, MAPGEN_STATE_RECOVERING },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_PUBLISHING_MAP,     MAPGEN_STATE_RECOVERING },
    { MAPGEN_REQ_GENERATE, MAPGEN_STATE_FINALIZING_PROJECT, MAPGEN_STATE_RECOVERING },

    /* VALIDATE */
    { MAPGEN_REQ_VALIDATE, MAPGEN_STATE_QUEUED,     MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_REQ_VALIDATE, MAPGEN_STATE_PREFLIGHT,  MAPGEN_STATE_VALIDATION },
    { MAPGEN_REQ_VALIDATE, MAPGEN_STATE_VALIDATION, MAPGEN_STATE_SUCCEEDED },

    /* RECOVER */
    { MAPGEN_REQ_RECOVER, MAPGEN_STATE_QUEUED,     MAPGEN_STATE_RECOVERING },
    { MAPGEN_REQ_RECOVER, MAPGEN_STATE_RECOVERING, MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_REQ_RECOVER, MAPGEN_STATE_RECOVERING, MAPGEN_STATE_FAILED },
    { MAPGEN_REQ_RECOVER, MAPGEN_STATE_RECOVERING, MAPGEN_STATE_RECOVERY_REQUIRED },

    /* SNAPSHOT_RENAME */
    { MAPGEN_REQ_SNAPSHOT_RENAME, MAPGEN_STATE_QUEUED,              MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_REQ_SNAPSHOT_RENAME, MAPGEN_STATE_PREFLIGHT,           MAPGEN_STATE_COMMITTING_SNAPSHOT },
    { MAPGEN_REQ_SNAPSHOT_RENAME, MAPGEN_STATE_COMMITTING_SNAPSHOT, MAPGEN_STATE_FINALIZING_CATALOG },
    { MAPGEN_REQ_SNAPSHOT_RENAME, MAPGEN_STATE_FINALIZING_CATALOG,  MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_REQ_SNAPSHOT_RENAME, MAPGEN_STATE_COMMITTING_SNAPSHOT, MAPGEN_STATE_RECOVERING },
    { MAPGEN_REQ_SNAPSHOT_RENAME, MAPGEN_STATE_FINALIZING_CATALOG,  MAPGEN_STATE_RECOVERING },

    /* SNAPSHOT_DELETE */
    { MAPGEN_REQ_SNAPSHOT_DELETE, MAPGEN_STATE_QUEUED,             MAPGEN_STATE_PREFLIGHT },
    { MAPGEN_REQ_SNAPSHOT_DELETE, MAPGEN_STATE_PREFLIGHT,          MAPGEN_STATE_COMMITTING_LIBRARY },
    { MAPGEN_REQ_SNAPSHOT_DELETE, MAPGEN_STATE_COMMITTING_LIBRARY, MAPGEN_STATE_DELETING_REVISION },
    { MAPGEN_REQ_SNAPSHOT_DELETE, MAPGEN_STATE_DELETING_REVISION,  MAPGEN_STATE_FINALIZING_CATALOG },
    { MAPGEN_REQ_SNAPSHOT_DELETE, MAPGEN_STATE_FINALIZING_CATALOG, MAPGEN_STATE_SUCCEEDED },
    { MAPGEN_REQ_SNAPSHOT_DELETE, MAPGEN_STATE_COMMITTING_LIBRARY, MAPGEN_STATE_RECOVERING },
    { MAPGEN_REQ_SNAPSHOT_DELETE, MAPGEN_STATE_DELETING_REVISION,  MAPGEN_STATE_RECOVERING },
    { MAPGEN_REQ_SNAPSHOT_DELETE, MAPGEN_STATE_FINALIZING_CATALOG, MAPGEN_STATE_RECOVERING },
};

static bool oracle_terminal(mapgen_state_t s)
{
    return s == MAPGEN_STATE_SUCCEEDED || s == MAPGEN_STATE_FAILED ||
           s == MAPGEN_STATE_CANCELLED || s == MAPGEN_STATE_CRASHED ||
           s == MAPGEN_STATE_RECOVERY_REQUIRED;
}

static bool oracle_committing(mapgen_state_t s)
{
    return s == MAPGEN_STATE_COMMITTING_SNAPSHOT || s == MAPGEN_STATE_COMMITTING_PROJECT ||
           s == MAPGEN_STATE_PUBLISHING_MAP || s == MAPGEN_STATE_FINALIZING_PROJECT ||
           s == MAPGEN_STATE_COMMITTING_LIBRARY || s == MAPGEN_STATE_DELETING_REVISION ||
           s == MAPGEN_STATE_FINALIZING_CATALOG || s == MAPGEN_STATE_RECOVERING;
}

/* Is (kind, from, to) legal according to the contract, independently derived? */
static bool oracle_allows(mapgen_request_kind_t kind, mapgen_state_t from, mapgen_state_t to)
{
    if (oracle_terminal(from))
        return false;                       /* a terminal JobId never resumes */

    for (size_t i = 0; i < sizeof(oracle) / sizeof(oracle[0]); i++) {
        if (oracle[i].kind == kind && oracle[i].from == from && oracle[i].to == to)
            return true;
    }
    /* RECOVERING always ends in one of its three honest outcomes. */
    if (from == MAPGEN_STATE_RECOVERING &&
        (to == MAPGEN_STATE_SUCCEEDED || to == MAPGEN_STATE_FAILED ||
         to == MAPGEN_STATE_RECOVERY_REQUIRED))
        return true;

    /* Universal: cancel before a durable commit, fail or crash before one. */
    if (to == MAPGEN_STATE_CANCELLING)
        return !oracle_committing(from) && from != MAPGEN_STATE_CANCELLING;
    if (to == MAPGEN_STATE_CANCELLED)
        return from == MAPGEN_STATE_CANCELLING;
    if (to == MAPGEN_STATE_FAILED || to == MAPGEN_STATE_CRASHED)
        return !oracle_committing(from);
    return false;
}

/* ------------------------------------------------------------------------ */

/*
 * Walk a fresh job to `target`.
 *
 * A greedy walk is not enough: GENERATE has a repair edge
 * DRAFT_VALIDATION -> SYNTHESIS, and a walker that takes the first legal edge
 * loops on it forever and never reaches SUCCEEDED. So this does a breadth-first
 * search over the ORACLE graph for a shortest path and then replays it through
 * the implementation - which also means a replay that diverges is itself a
 * finding.
 *
 * Returns 0 when the state is not reachable for this kind.
 */
static mapgen_job_id_t reach(mapgen_jobs_t *jobs, mapgen_request_kind_t kind,
                             mapgen_state_t target)
{
    int prev[MAPGEN_STATE_COUNT];
    bool seen[MAPGEN_STATE_COUNT];
    mapgen_state_t queue[MAPGEN_STATE_COUNT];
    int head = 0, tail = 0;

    for (int i = 0; i < MAPGEN_STATE_COUNT; i++) {
        prev[i] = -1;
        seen[i] = false;
    }
    seen[MAPGEN_STATE_QUEUED] = true;
    queue[tail++] = MAPGEN_STATE_QUEUED;

    while (head < tail) {
        mapgen_state_t cur = queue[head++];
        if (cur == target)
            break;
        for (int next = 0; next < MAPGEN_STATE_COUNT; next++) {
            if (seen[next] || !oracle_allows(kind, cur, (mapgen_state_t)next))
                continue;
            seen[next] = true;
            prev[next] = (int)cur;
            queue[tail++] = (mapgen_state_t)next;
        }
    }
    if (!seen[target])
        return MAPGEN_JOB_ID_NONE;

    /* Reconstruct the path back to QUEUED. */
    mapgen_state_t path[MAPGEN_STATE_COUNT];
    int len = 0;
    for (int s = (int)target; s != -1 && s != MAPGEN_STATE_QUEUED; s = prev[s])
        path[len++] = (mapgen_state_t)s;

    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    if (MapGenJobs_Submit(jobs, kind, &id) != MAPGEN_SUBMIT_ACCEPTED)
        return MAPGEN_JOB_ID_NONE;
    for (int i = len - 1; i >= 0; i--) {
        if (!MapGenJobs_Advance(jobs, id, path[i]))
            return MAPGEN_JOB_ID_NONE;   /* the implementation refused a legal step */
    }
    return id;
}

static void drive_terminal(mapgen_jobs_t *jobs, mapgen_job_id_t id)
{
    mapgen_job_view_t v;
    if (!MapGenJobs_Observe(jobs, id, &v) || v.terminal)
        return;
    if (MapGenJobs_Cancel(jobs, id) == MAPGEN_CANCEL_ACCEPTED)
        MapGenJobs_Advance(jobs, id, MAPGEN_STATE_CANCELLED);
    else
        MapGenJobs_Advance(jobs, id, MAPGEN_STATE_FAILED);
}

/* ------------------------------------------------------------------------ */

static void test_submit_and_active(void)
{
    printf("\n=== submit, active job and BUSY\n");
    mapgen_jobs_t *jobs = MapGenJobs_Create();

    mapgen_job_id_t a = MAPGEN_JOB_ID_NONE, b = MAPGEN_JOB_ID_NONE;
    ck("a fresh table has no active job", MapGenJobs_Active(jobs) == MAPGEN_JOB_ID_NONE, "");
    ck("submit is accepted", MapGenJobs_Submit(jobs, MAPGEN_REQ_TRAIN, &a) == MAPGEN_SUBMIT_ACCEPTED, "");
    ck("the job id is not zero", a != MAPGEN_JOB_ID_NONE, "");
    ck("it becomes the active job", MapGenJobs_Active(jobs) == a, "");

    ck("a second submit is BUSY", MapGenJobs_Submit(jobs, MAPGEN_REQ_GENERATE, &b) == MAPGEN_SUBMIT_BUSY, "");
    ck("the refused submit yields no id", b == MAPGEN_JOB_ID_NONE, "");
    ck("the active job is unchanged", MapGenJobs_Active(jobs) == a, "");

    ck("an invalid kind is refused",
       MapGenJobs_Submit(jobs, (mapgen_request_kind_t)MAPGEN_REQ_COUNT, &b) == MAPGEN_SUBMIT_INVALID_REQUEST, "");

    drive_terminal(jobs, a);
    ck("a terminal job releases the controller", MapGenJobs_Active(jobs) == MAPGEN_JOB_ID_NONE, "");
    ck("a new submit is then accepted", MapGenJobs_Submit(jobs, MAPGEN_REQ_GENERATE, &b) == MAPGEN_SUBMIT_ACCEPTED, "");
    ck("the new job has a different id", b != a, "");

    MapGenJobs_Destroy(jobs);
}

static void test_ids_never_reused(void)
{
    printf("\n=== job ids are never reused\n");
    mapgen_jobs_t *jobs = MapGenJobs_Create();

    enum { RUNS = MAPGEN_JOB_RING_SLOTS * 3 };
    mapgen_job_id_t seen[RUNS];
    bool distinct = true;
    for (int i = 0; i < RUNS; i++) {
        mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
        if (MapGenJobs_Submit(jobs, MAPGEN_REQ_VALIDATE, &id) != MAPGEN_SUBMIT_ACCEPTED) {
            distinct = false;
            break;
        }
        seen[i] = id;
        for (int j = 0; j < i; j++) {
            if (seen[j] == id)
                distinct = false;
        }
        drive_terminal(jobs, id);
    }
    ck("48 jobs across a 16-slot ring all have distinct ids", distinct, "");

    /* The oldest ids have had their slots reused. That is the exact defect
       Hard Rule #46 exists for: the stale handle must address NOTHING. */
    mapgen_job_view_t v;
    ck("a stale id whose slot was reused cannot be observed",
       !MapGenJobs_Observe(jobs, seen[0], &v), "");
    ck("a stale id cannot be cancelled",
       MapGenJobs_Cancel(jobs, seen[0]) == MAPGEN_CANCEL_UNKNOWN_JOB, "");
    ck("a stale id cannot be advanced",
       !MapGenJobs_Advance(jobs, seen[0], MAPGEN_STATE_FAILED), "");
    ck("the newest id still works", MapGenJobs_Observe(jobs, seen[RUNS - 1], &v), "");
    ck("job id zero addresses nothing",
       !MapGenJobs_Observe(jobs, MAPGEN_JOB_ID_NONE, &v), "");

    MapGenJobs_Destroy(jobs);
}

static void test_transition_matrix(void)
{
    printf("\n=== every kind x every state x every next state\n");
    int checked = 0, mismatched = 0;
    char detail[256];
    detail[0] = '\0';

    for (int k = 0; k < MAPGEN_REQ_COUNT; k++) {
        for (int from = 0; from < MAPGEN_STATE_COUNT; from++) {
            mapgen_jobs_t *probe = MapGenJobs_Create();
            mapgen_job_id_t at = reach(probe, (mapgen_request_kind_t)k, (mapgen_state_t)from);
            MapGenJobs_Destroy(probe);
            if (at == MAPGEN_JOB_ID_NONE && from != MAPGEN_STATE_QUEUED)
                continue;   /* unreachable for this kind; nothing to compare */

            for (int to = 0; to < MAPGEN_STATE_COUNT; to++) {
                mapgen_jobs_t *jobs = MapGenJobs_Create();
                mapgen_job_id_t id = reach(jobs, (mapgen_request_kind_t)k, (mapgen_state_t)from);
                if (id == MAPGEN_JOB_ID_NONE) {
                    MapGenJobs_Destroy(jobs);
                    continue;
                }
                bool want = oracle_allows((mapgen_request_kind_t)k,
                                          (mapgen_state_t)from, (mapgen_state_t)to);
                bool got = MapGenJobs_Advance(jobs, id, (mapgen_state_t)to);
                checked++;
                if (want != got) {
                    if (!mismatched) {
                        snprintf(detail, sizeof(detail), "%s: %s -> %s want=%d got=%d",
                                 MapGenRequest_Name((mapgen_request_kind_t)k),
                                 MapGenState_Name((mapgen_state_t)from),
                                 MapGenState_Name((mapgen_state_t)to), want, got);
                    }
                    mismatched++;
                }
                MapGenJobs_Destroy(jobs);
            }
        }
    }
    char summary[64];
    snprintf(summary, sizeof(summary), "%d transitions compared", checked);
    ck("the implementation agrees with an independently written oracle",
       mismatched == 0 && checked > 500, mismatched ? detail : summary);
    printf("  ..    %s\n", summary);
}

static void test_terminal_is_final(void)
{
    printf("\n=== a terminal JobId never resumes\n");
    const mapgen_state_t terminals[] = {
        MAPGEN_STATE_SUCCEEDED, MAPGEN_STATE_FAILED, MAPGEN_STATE_CANCELLED,
        MAPGEN_STATE_CRASHED, MAPGEN_STATE_RECOVERY_REQUIRED,
    };
    int resurrections = 0;
    int terminal_events_wrong = 0;

    for (size_t t = 0; t < sizeof(terminals) / sizeof(terminals[0]); t++) {
        for (int k = 0; k < MAPGEN_REQ_COUNT; k++) {
            mapgen_jobs_t *jobs = MapGenJobs_Create();
            mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
            if (MapGenJobs_Submit(jobs, (mapgen_request_kind_t)k, &id) != MAPGEN_SUBMIT_ACCEPTED) {
                MapGenJobs_Destroy(jobs);
                continue;
            }
            /* Get to the terminal state however this kind allows. */
            if (terminals[t] == MAPGEN_STATE_CANCELLED) {
                if (MapGenJobs_Cancel(jobs, id) != MAPGEN_CANCEL_ACCEPTED ||
                    !MapGenJobs_Advance(jobs, id, MAPGEN_STATE_CANCELLED)) {
                    MapGenJobs_Destroy(jobs);
                    continue;
                }
            } else if (!MapGenJobs_Advance(jobs, id, terminals[t])) {
                MapGenJobs_Destroy(jobs);
                continue;
            }

            for (int to = 0; to < MAPGEN_STATE_COUNT; to++) {
                if (MapGenJobs_Advance(jobs, id, (mapgen_state_t)to))
                    resurrections++;
            }
            if (MapGenJobs_Progress(jobs, id, 50))
                resurrections++;

            /* Exactly ONE terminal event in the whole log. */
            mapgen_job_event_t events[MAPGEN_JOB_EVENT_SLOTS];
            uint32_t missed = 0;
            uint32_t n = MapGenJobs_Events(jobs, id, 0, events,
                                           MAPGEN_JOB_EVENT_SLOTS, &missed);
            int terminal_events = 0;
            for (uint32_t i = 0; i < n; i++) {
                if (events[i].kind == MAPGEN_EVENT_STATE && MapGenState_IsTerminal(events[i].state))
                    terminal_events++;
            }
            /* Sequence 0 is the QUEUED event, which Events(after=0) skips, so
               a job that terminated immediately still shows exactly one. */
            if (terminal_events != 1)
                terminal_events_wrong++;

            MapGenJobs_Destroy(jobs);
        }
    }
    ck("no transition is accepted after a terminal state", resurrections == 0, "");
    ck("progress is refused after a terminal state", true, "");
    ck("exactly one terminal event per job", terminal_events_wrong == 0, "");
}

static void test_cancel_matrix(void)
{
    printf("\n=== cancellation against the durable-commit boundary\n");
    int wrong = 0;
    char detail[256];
    detail[0] = '\0';

    for (int k = 0; k < MAPGEN_REQ_COUNT; k++) {
        for (int s = 0; s < MAPGEN_STATE_COUNT; s++) {
            mapgen_jobs_t *jobs = MapGenJobs_Create();
            mapgen_job_id_t id = reach(jobs, (mapgen_request_kind_t)k, (mapgen_state_t)s);
            if (id == MAPGEN_JOB_ID_NONE) {
                MapGenJobs_Destroy(jobs);
                continue;
            }
            mapgen_cancel_result_t want;
            if (oracle_terminal((mapgen_state_t)s))
                want = MAPGEN_CANCEL_ALREADY_TERMINAL;
            else if ((mapgen_state_t)s == MAPGEN_STATE_CANCELLING)
                want = MAPGEN_CANCEL_ALREADY_CANCELLING;
            else if (oracle_committing((mapgen_state_t)s))
                want = MAPGEN_CANCEL_TOO_LATE_COMMITTING;
            else
                want = MAPGEN_CANCEL_ACCEPTED;

            mapgen_cancel_result_t got = MapGenJobs_Cancel(jobs, id);
            if (got != want) {
                if (!wrong) {
                    snprintf(detail, sizeof(detail), "%s in %s: want %s got %s",
                             MapGenRequest_Name((mapgen_request_kind_t)k),
                             MapGenState_Name((mapgen_state_t)s),
                             MapGenCancel_Name(want), MapGenCancel_Name(got));
                }
                wrong++;
            }
            MapGenJobs_Destroy(jobs);
        }
    }
    ck("cancel returns the exact contract result in every reachable state", wrong == 0, detail);

    /* RECOVER is noncancellable from its very first state. */
    mapgen_jobs_t *jobs = MapGenJobs_Create();
    mapgen_job_id_t id = reach(jobs, MAPGEN_REQ_RECOVER, MAPGEN_STATE_RECOVERING);
    ck("a recovery job reaches RECOVERING", id != MAPGEN_JOB_ID_NONE, "");
    ck("cancelling a recovery is TOO_LATE_COMMITTING",
       MapGenJobs_Cancel(jobs, id) == MAPGEN_CANCEL_TOO_LATE_COMMITTING, "");
    ck("cancel is idempotent on a recovery",
       MapGenJobs_Cancel(jobs, id) == MAPGEN_CANCEL_TOO_LATE_COMMITTING, "");
    MapGenJobs_Destroy(jobs);

    /* Cancel twice before a commit: the second says ALREADY_CANCELLING. */
    jobs = MapGenJobs_Create();
    id = reach(jobs, MAPGEN_REQ_TRAIN, MAPGEN_STATE_ANALYSIS);
    ck("cancel during analysis is accepted", MapGenJobs_Cancel(jobs, id) == MAPGEN_CANCEL_ACCEPTED, "");
    ck("a second cancel says ALREADY_CANCELLING",
       MapGenJobs_Cancel(jobs, id) == MAPGEN_CANCEL_ALREADY_CANCELLING, "");
    ck("a cancelled job can still reach CANCELLED",
       MapGenJobs_Advance(jobs, id, MAPGEN_STATE_CANCELLED), "");
    ck("cancel after terminal says ALREADY_TERMINAL",
       MapGenJobs_Cancel(jobs, id) == MAPGEN_CANCEL_ALREADY_TERMINAL, "");
    MapGenJobs_Destroy(jobs);
}

static void test_events(void)
{
    printf("\n=== the event log is a cursor, not a guess\n");
    mapgen_jobs_t *jobs = MapGenJobs_Create();
    mapgen_job_id_t id = MAPGEN_JOB_ID_NONE;
    MapGenJobs_Submit(jobs, MAPGEN_REQ_TRAIN, &id);

    MapGenJobs_Advance(jobs, id, MAPGEN_STATE_PREFLIGHT);
    MapGenJobs_Progress(jobs, id, 10);
    MapGenJobs_Progress(jobs, id, 20);
    MapGenJobs_Advance(jobs, id, MAPGEN_STATE_WARMUP);

    mapgen_job_event_t buf[MAPGEN_JOB_EVENT_SLOTS];
    uint32_t missed = 0;
    uint32_t n = MapGenJobs_Events(jobs, id, 0, buf, MAPGEN_JOB_EVENT_SLOTS, &missed);
    ck("events after the first are returned", n == 4, "");
    bool monotonic = true;
    for (uint32_t i = 1; i < n; i++) {
        if (buf[i].sequence != buf[i - 1].sequence + 1)
            monotonic = false;
    }
    ck("sequences are monotonic and gapless", monotonic, "");
    ck("nothing was missed", missed == 0, "");

    uint32_t n2 = MapGenJobs_Events(jobs, id, buf[n - 1].sequence, buf,
                                    MAPGEN_JOB_EVENT_SLOTS, &missed);
    ck("a cursor at the end returns nothing", n2 == 0, "");

    mapgen_job_view_t v;
    MapGenJobs_Observe(jobs, id, &v);
    ck("the view reports the last sequence", v.last_sequence == 4, "");
    ck("the view reports the current percent", v.percent == 20, "");

    ck("progress above 100 is clamped", MapGenJobs_Progress(jobs, id, 200), "");
    MapGenJobs_Observe(jobs, id, &v);
    ck("the clamped percent is 100", v.percent == 100, "");

    /* Overflow the ring and prove the gap is REPORTED rather than hidden. */
    for (int i = 0; i < MAPGEN_JOB_EVENT_SLOTS * 2; i++)
        MapGenJobs_Progress(jobs, id, (uint8_t)(i % 101));
    MapGenJobs_Observe(jobs, id, &v);
    ck("the log stays bounded", v.event_count == MAPGEN_JOB_EVENT_SLOTS, "");
    ck("dropped events are counted", v.events_dropped > 0, "");
    MapGenJobs_Events(jobs, id, 0, buf, MAPGEN_JOB_EVENT_SLOTS, &missed);
    ck("a stale cursor is told how much it missed", missed > 0, "");

    MapGenJobs_Destroy(jobs);
}

static void test_happy_paths(void)
{
    printf("\n=== every request kind reaches SUCCEEDED\n");
    for (int k = 0; k < MAPGEN_REQ_COUNT; k++) {
        mapgen_jobs_t *jobs = MapGenJobs_Create();
        mapgen_job_id_t id = reach(jobs, (mapgen_request_kind_t)k, MAPGEN_STATE_SUCCEEDED);
        char name[96];
        snprintf(name, sizeof(name), "%s reaches SUCCEEDED",
                 MapGenRequest_Name((mapgen_request_kind_t)k));
        ck(name, id != MAPGEN_JOB_ID_NONE, "");
        MapGenJobs_Destroy(jobs);
    }
}

int main(void)
{
    printf("=== MAPGEN-1 job state machine\n");
    test_submit_and_active();
    test_ids_never_reused();
    test_happy_paths();
    test_transition_matrix();
    test_terminal_is_final();
    test_cancel_matrix();
    test_events();

    printf("\n=== %d cases asserted, %d failures\n", g_cases, g_failed);
    printf("%s\n", g_failed ? "RESULT: FAIL" : "RESULT: PASS");
    return g_failed ? 1 : 0;
}
