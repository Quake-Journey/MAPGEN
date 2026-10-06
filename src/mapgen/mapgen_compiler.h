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

MAPGEN-1 - MapCompilerAdapter contract

This header is the M0 CONTRACT ONLY.  It declares the Seam between MAPGEN's
worker and whatever external program turns an authoring `.map` into a compiled
BSP.  No implementation exists yet and no build target references this file:
contract phase M0 creates contracts, fixtures, fake adapters and the
qualification harness, and production implementation begins at M1 after M0Q
has qualified a real compiler.

The executable form of this contract - the one that actually runs today - is
`tools/mapgen_qualification.py`.  The two must agree; the M0 acceptance suite
`tools/check_mapgen_m0_contract.py` compares the result enumeration below with
the runner's own list and fails if they drift.

--- The one law -------------------------------------------------------------

A zero exit code is NEVER success.

That is not caution, it is a property of the pinned candidate.
`qbism/q2tools-220` calls exit(0) after printing "**** leaked ****" and before
writing the BSP (src/bsp.c:225-234), and it prints a WARNING and leaves surface
flags and contents at ZERO when a texture cannot be resolved
(src/textures.c:29-105).  Both produce a clean-looking run and a map that is
wrong or absent.  Therefore MAPCOMPILE_OK may be returned only after the
produced BSP has been reread by an independent parser and its semantic
expectations have been checked against the frozen Recipe.

--- What is private ---------------------------------------------------------

Compiler command lines, thread policy, the job-local read-only asset mirror and
the process host are implementation details of this Adapter.  The external Seam
of the whole feature remains MapGen_Submit / MapGen_Observe / MapGen_Cancel;
nothing here appears in a caller Interface.

Contract sections: 16 (pipeline), 17 (adapter and qualification), 18 (hard
validation profiles), 10 (determinism), 24 (process security).
==============================================================================
*/

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Keep in step with RESULTS in tools/mapgen_qualification.py. */
typedef enum {
    MAPCOMPILE_OK = 0,

    /* the request itself is not runnable */
    MAPCOMPILE_ERR_INVALID_REQUEST,
    /* the attempt directory was not freshly created and empty */
    MAPCOMPILE_ERR_DIRTY_JOB_DIR,

    /* the child process never ran, or did not finish normally */
    MAPCOMPILE_ERR_LAUNCH,
    MAPCOMPILE_ERR_TIMEOUT,
    MAPCOMPILE_ERR_CRASH,
    MAPCOMPILE_ERR_NONZERO_EXIT,

    /* the child exited zero and still failed */
    MAPCOMPILE_ERR_LEAKED,
    MAPCOMPILE_ERR_MISSING_ASSET,
    MAPCOMPILE_ERR_NO_OUTPUT,
    MAPCOMPILE_ERR_STALE_OUTPUT,
    MAPCOMPILE_ERR_OUTPUT_UNREADABLE,
    MAPCOMPILE_ERR_WRONG_FORMAT,
    MAPCOMPILE_ERR_SEMANTICS,

    /* containment and budgets */
    MAPCOMPILE_ERR_ESCAPED_JOB_ROOT,
    MAPCOMPILE_ERR_DISK_BUDGET,
    MAPCOMPILE_ERR_LOG_BUDGET,

    MAPCOMPILE_ERR_CANCELLED,
    /* the executable is not the qualified one (path, SHA-256 or build id) */
    MAPCOMPILE_ERR_IDENTITY,

    MAPCOMPILE_RESULT_COUNT
} mapcompile_result_t;

typedef enum {
    MAPCOMPILE_STAGE_BSP,
    MAPCOMPILE_STAGE_VIS_FAST,
    MAPCOMPILE_STAGE_VIS,
    MAPCOMPILE_STAGE_RAD,

    MAPCOMPILE_STAGE_COUNT
} mapcompile_stage_t;

typedef enum {
    /* geometry, collision, entities and every hard Recipe constraint, plus
       whatever fast VIS produced.  No final-light requirement. */
    MAPCOMPILE_PROFILE_DRAFT,
    /* every draft gate again on the accepted lineage, plus final VIS, LIGHT
       and the isolated runtime-load gate. */
    MAPCOMPILE_PROFILE_FINAL,

    MAPCOMPILE_PROFILE_COUNT
} mapcompile_profile_t;

typedef enum {
    MAPCOMPILE_FORMAT_IBSP,   /* standard v38, preferred while limits permit */
    MAPCOMPILE_FORMAT_QBSP    /* extended v38, only when needed and supported */
} mapcompile_format_t;

#define MAPCOMPILE_MAX_PATH         512
#define MAPCOMPILE_MAX_ARGV         64
#define MAPCOMPILE_SHA256_HEX       65

/*
 * The compiler thread count the pin qualified - not a number chosen here.
 *
 * tools/mapgen_compiler_pin.json thread_policy.value is 1, and it records why:
 * the semantic digest is independent of the count (MEASURED at 1, 2 and 16),
 * but q2tools' RunThreadsOn waits a fixed second per parallel batch, so one
 * thread is 0.3s where sixteen is 12.8s on the same fixture.
 *
 * Every request that asked for 4 was a configuration nobody qualified while
 * calling itself the pinned one. tools/check_mapgen_thread_policy.py holds
 * this constant and the pin to the same value and fails on a fresh literal.
 */
#define MAPCOMPILE_PINNED_THREADS   1

/*
 * Row 404: the one compile that is not an attempt's - the final light compile (bsp, full vis, rad), once per map -
 * runs on every performance-class logical CPU of the machine (`Q2PROX_Cpu_PerformanceCount`: the PO's 16 P-core
 * threads, his E-cores never counted), or on what the request names. On one thread it took 17 minutes for cor and
 * over an hour for q3t2 while the PO watched his processor at 3 %; RunThreadsOn's fixed second per batch, the reason
 * an attempt's small compile stays on one, is nothing against that. MEASURED on q2dm1: bsp and rad byte for byte
 * the same on 1, 8 and 16 threads; full vis on several threads is NOT the same from run to run - two runs on 16
 * differed in the visibility lump and in nothing else. q2tools' flow takes a portal another thread has finished
 * through its final vis and one it has not through its looser flood bound, so the PVS is conservative either way:
 * it can say a leaf is seen that is not, never the reverse. The finished map's bytes therefore vary in that one lump
 * between two runs of one request; what is judged - every attempt and the finished map's verdict - is the draft
 * compile, which stays on the pinned one thread, and the lit file replaces it only once proved equivalent on all
 * eight axes. `tools/check_mapgen_thread_policy.py` allows this spelling at this one site.
 */
#define MAPCOMPILE_LIGHT_THREADS(requested) ((requested) > 0 ? (requested) : Q2PROX_Cpu_PerformanceCount())

/*
 * One attempt.  Every path is absolute and job-local; no caller ever supplies
 * a raw OS path and no field is a shell string.  `job_dir` must have been
 * created empty for THIS attempt: a repaired candidate invalidates the whole
 * compiled lineage and starts a fresh directory (contract section 17).
 */
typedef struct {
    char                 job_dir[MAPCOMPILE_MAX_PATH];
    char                 map_name[64];          /* without extension */

    /* the job-local read-only mirror derived from the frozen target manifest;
       never a live or ambient baseq2 lookup (contract section 5.6) */
    char                 moddir[MAPCOMPILE_MAX_PATH];
    char                 basedir[MAPCOMPILE_MAX_PATH];

    mapcompile_profile_t profile;
    mapcompile_format_t  format;

    /* Always explicit.  The candidate's default is the machine's core count,
       and a result that depends on the worker count violates section 10.
       Use MAPCOMPILE_PINNED_THREADS unless something qualified another
       value - see the note on that macro. */
    int                  threads;

    uint32_t             stage_timeout_ms;
    uint32_t             max_log_bytes;
    uint64_t             disk_budget_bytes;

    /* Row 405: words added to the light pass alone ("-sunradscale 4.0 -scale 1.15"), the donor's calibration;
       empty for every compile but the finished map's light. */
    char                 rad_flags[128];
} mapcompile_request_t;

/*
 * Per-stage evidence.  The rolling hash and total byte count describe the WHOLE
 * stream even when the retained text was truncated, so output flooding cannot
 * destroy the evidence or the disk budget.
 */
typedef struct {
    mapcompile_stage_t   stage;
    int32_t              exit_code;
    bool                 timed_out;
    bool                 crashed;
    uint32_t             duration_ms;

    uint64_t             stdout_total_bytes;
    char                 stdout_rolling_sha256[MAPCOMPILE_SHA256_HEX];
    bool                 stdout_truncated;

    /* bounded, control-characters sanitized, safe for UI/console display */
    char                *stdout_captured;
    size_t               stdout_captured_bytes;
} mapcompile_stage_report_t;

/*
 * The whole attempt.  `reread_performed` and `semantics_checked` are not
 * diagnostics: MAPCOMPILE_OK is invalid unless both are true, and the
 * implementation must assert that rather than trusting a caller to check.
 */
typedef struct {
    mapcompile_result_t       result;

    bool                      reread_performed;
    bool                      semantics_checked;

    char                      bsp_path[MAPCOMPILE_MAX_PATH];
    uint64_t                  bsp_bytes;
    char                      bsp_sha256[MAPCOMPILE_SHA256_HEX];
    /* canonical digest of MEANING, excluding lightmap bytes, vis bytes,
       padding and lump offsets (contract section 10) */
    char                      semantic_digest[MAPCOMPILE_SHA256_HEX];

    /* identity of the executable that produced this, verified before launch
       and again at HELLO (contract section 24) */
    char                      compiler_path[MAPCOMPILE_MAX_PATH];
    char                      compiler_sha256[MAPCOMPILE_SHA256_HEX];
    char                      compiler_build_id[64];

    mapcompile_stage_report_t stages[MAPCOMPILE_STAGE_COUNT];
    int                       num_stages;

    uint64_t                  job_dir_bytes;
    bool                      escaped_job_root;
} mapcompile_report_t;

/*
 * The Adapter.  Production launches a real process; the qualification harness
 * substitutes a fake one that produces each failure mode as a REAL process,
 * because an in-process seam has no concept of an exit code, a hung child or a
 * flooded pipe (Hard Rule #51).
 *
 * `run_stage` reports what the process DID.  It never decides whether the
 * attempt succeeded - that judgement belongs to the runner below, which reads
 * artifacts.
 */
typedef struct mapcompile_adapter_s {
    const char *name;
    void       *ctx;

    mapcompile_result_t (*run_stage)(void                       *ctx,
                                     const mapcompile_request_t *request,
                                     mapcompile_stage_t          stage,
                                     mapcompile_stage_report_t  *out);

    void (*cancel)(void *ctx);
} mapcompile_adapter_t;

/*
 * Run every stage of `request->profile` through `adapter`, then decide the
 * result from artifacts alone.  Returns `report->result`.
 *
 * Post-conditions the implementation must guarantee:
 *   - MAPCOMPILE_OK implies report->reread_performed && report->semantics_checked;
 *   - a leaked or missing-asset run reports its own code, never OK, whatever
 *     the exit code was;
 *   - a pre-existing output file in the job directory is DIRTY_JOB_DIR, not a
 *     result;
 *   - nothing was written outside job_dir;
 *   - no child or grandchild process outlives the call.
 */
mapcompile_result_t MapCompile_RunProfile(const mapcompile_adapter_t *adapter,
                                          const mapcompile_request_t *request,
                                          mapcompile_report_t        *report);

/* Stable, translatable identifier for a result code. */
const char *MapCompile_ResultName(mapcompile_result_t result);

/*
 * The compiler's own progress (ledger row 411; the PO, 05.10: «освещение - разве не должно было это показываться как
 * идет процесс»): q2tool prints a bar of tenths, «0...1...2...9... (n)», for each pass of a stage - the adapter calls
 * the tick with the stage («bsp», «vis», «rad»), the pass within it (0, 1, ...) and the tenths done (1..10). Nothing
 * when no tick is set.
 */
typedef void (*mapcompile_tick_fn)(const char *stage, int pass, int tenths);
void MapCompile_SetTick(mapcompile_tick_fn tick);
void MapCompile_Tick(const char *stage, int pass, int tenths);

