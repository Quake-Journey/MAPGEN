/*
 * MapGenPipeline - a candidate becomes a map, or it does not.
 *
 * Generate, compile, validate, measure - as ONE thing with one verdict, which
 * is what contract 17 means by a transaction. The pieces have all existed
 * separately for a while and that is precisely the problem: a caller that ran
 * them in order would have to decide for itself what counts as success, and
 * every caller would decide slightly differently. There is one place that
 * decides, and it is this.
 *
 * --- what "it worked" means -----------------------------------------------
 *
 * All four of these, and a failure at any point stops the rest:
 *
 *   the generator wrote a candidate;
 *   the compiler produced a map, judged from artifacts and not exit codes -
 *     no leak, no missing material, the right format, and something in it;
 *   the compiled map is PLAYABLE - every player start in one component, and
 *     nothing a player can reach and not leave that will not kill him;
 *   and it diverged from its donor by as much as the fidelity asked for.
 *
 * The last one is the reason a near-copy is a failure. A candidate that
 * compiles perfectly and is q2dm1 again is not a fork, and for three rounds
 * that is exactly what was handed over.
 *
 * --- retained or discarded ------------------------------------------------
 *
 * Nothing here publishes. A verdict and a job directory come back, and what to
 * do with them belongs to whoever asked - because "keep it" and "throw it
 * away" are decisions about a Project and a lineage, and this does not know
 * about either.
 */

#ifndef MAPGEN_PIPELINE_H
#define MAPGEN_PIPELINE_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_divergence.h"
#include "common/mapgen_certificate.h"
#include "common/mapgen_synthesis.h"
#include "common/mapgen_generate.h"
#include "common/mapgen_reach.h"
#include "common/mapgen_transaction.h"
#include "mapgen_compiler.h"

/*
 * Whether the caller still wants the answer.
 *
 * Asked wherever the pipeline is about to spend real time, and passed into the
 * authoritative walk, which is where nearly all of it goes.
 */
typedef bool (*mapgen_pipeline_cancelled_fn)(void *user);

typedef enum {
    MAPGEN_PIPELINE_OK = 0,
    /*
     * Everything a product run asks was asked and passed, except that this run
     * was told not to hold the candidate to its target band. The artifact is
     * not publishable and this is not OK; it is a measurement.
     */
    MAPGEN_PIPELINE_DIAGNOSTIC,
    MAPGEN_PIPELINE_ERR_ARGS,
    MAPGEN_PIPELINE_ERR_GENERATE,
    /*
     * The donor's own geometry could not be written, compiled and read back,
     * so there is no reference to measure anything against. The first compile
     * a run does is this one, which is why a compiler that leaks or writes
     * nothing arrives here rather than at an edit.
     */
    MAPGEN_PIPELINE_ERR_BASELINE,
    /* Not a failure: the caller asked it to stop. */
    MAPGEN_PIPELINE_CANCELLED,
    /*
     * A run that applied nothing produced a map that is not the donor.
     *
     * Fidelity 100 is the one case where the candidate must be the donor
     * itself, so this is the same refusal as ERR_BASELINE aimed at the other
     * end of the run.
     */
    MAPGEN_PIPELINE_ERR_CANDIDATE,
    /*
     * Fidelity zero, and the chain that invents a map produced none: no
     * snapshot to learn from, a manifest the target cannot resolve, or every
     * attempt the recipe allowed refused. The report says which.
     */
    MAPGEN_PIPELINE_ERR_SYNTHESIS,
    MAPGEN_PIPELINE_ERR_COMPILE,
    MAPGEN_PIPELINE_ERR_UNPLAYABLE,
    MAPGEN_PIPELINE_ERR_TOO_LIKE_THE_DONOR,
    MAPGEN_PIPELINE_ERR_CHANGED_TOO_MUCH,

    /*
     * Nobody measured it.
     *
     * The donor would not load, the oracle failed, or it ran with an axis
     * missing. A candidate that passes because nothing checked it is the exact
     * shape of the defect this whole path exists to prevent, so an unmeasured
     * candidate is refused rather than waved through.
     */
    MAPGEN_PIPELINE_ERR_NOT_MEASURED,

    /*
     * The schedule ran out and the target was still short.
     *
     * Codex's VARIATION_TARGET_UNREACHABLE. The alternative is handing over a
     * candidate that is the donor with paint on it, which a maximum with no
     * minimum permitted three times running and which the PO rejected three
     * times running. The report says how much was missing and what was tried,
     * so the answer to "why is this map not different enough" is a number and
     * a list rather than a shrug.
     */
    MAPGEN_PIPELINE_ERR_TARGET_UNREACHABLE,
    /*
     * A donor was selected and gave nothing.
     *
     * Codex, 2026-09-06 section 5: every explicitly selected Architecture
     * Donor must contribute a major intact bundle, "or return a named
     * donor/constraint conflict without publication". Naming the omission in
     * the report is not permission to succeed anyway - which is how it was
     * read before, and the reading Codex rejected. `donor_used` says which.
     */
    MAPGEN_PIPELINE_ERR_DONOR_OMITTED,
    MAPGEN_PIPELINE_ERR_MEMORY
} mapgen_pipeline_result_t;

const char *MapGenPipeline_ResultName(mapgen_pipeline_result_t r);

/* Enough for a corpus. A run wanting more than this wants a different design,
   not a bigger array. */
/*
 * How many times a run may deal itself a new hand before it gives up.
 *
 * Each round replans over the geometry the accepted edits have left, so the
 * rounds are not repetitions: the second sees rooms the first changed. Four
 * is what it took on q2dm1 for three seeds at fidelity 90 to land in a band
 * one of them used to miss.
 */
#define MAPGEN_PIPELINE_MAX_ROUNDS 4u

/*
 * How many attempts a run spends on being a fork rather than on being the
 * right distance from one.
 *
 * Item swaps and moved spawns take no architectural credit, so they cannot
 * move the band and are not competing with it - but each is a compile, and a
 * run that spent forty of them on q2dm1's forty-one pedestals would double
 * its cost to say the same thing.
 */
#define MAPGEN_PIPELINE_FINISHING 6u

#define MAPGEN_PIPELINE_MAX_DONORS 8

typedef struct {
    mapgen_generate_request_t generate;

    /*
     * Where the compiler looks for materials.
     *
     * The job-local read-only mirror derived from the frozen target manifest,
     * never a live or ambient baseq2 lookup - contract 5.6, and also the only
     * way two runs of one request can be compared at all. The pipeline does
     * not choose it: a caller that has not frozen a manifest has not got one,
     * and should not be handed a default that quietly works.
     */
    char                      moddir[MAPCOMPILE_MAX_PATH];
    char                      basedir[MAPCOMPILE_MAX_PATH];

    mapcompile_profile_t      profile;
    mapcompile_format_t       format;
    int                       threads;
    /*
     * Row 404: the threads of the final light compile (bsp, full vis, rad) - 0 is every performance-class logical
     * CPU of the machine (`Q2PROX_Cpu_PerformanceCount`: 16 of the PO's 32, his E-cores never counted). That one
     * compile ran on one thread: 17 minutes for cor, over an hour for q3t2, while the PO waited and watched his
     * processor at 3 %. Measured on q2dm1: bsp and rad are byte for byte the same on 1, 8 and 16 threads; full vis
     * on several threads varies from run to run in the visibility lump alone, conservatively (see
     * MAPCOMPILE_LIGHT_THREADS).
     */
    int                       light_threads;
    uint32_t                  stage_timeout_ms;
    uint32_t                  max_log_bytes;
    uint64_t                  disk_budget_bytes;

    /* How many places the reachability search may open before it gives up and
       says the answer is about part of the map. */
    uint32_t                  reach_budget;
    /*
     * A qualification run that wants the NUMBER rather than a verdict.
     *
     * The divergence band is otherwise mandatory, like the compile, the
     * reachability, the items, the landmarks and the movers, and there is
     * deliberately no field for turning any of those off. This one is stated
     * the way round it is because a zeroed request must be the fully gated
     * one: it used to be `require_band`, so a caller who never heard of the
     * band got a product OK for a candidate nobody had measured against its
     * target. A gate a caller can forget is a gate that gets forgotten.
     *
     * A run that sets it does not produce a publishable artifact and does not
     * say OK. It says MAPGEN_PIPELINE_DIAGNOSTIC, which is a different word.
     */
    bool                      diagnostic_no_band;

    /*
     * How many edits the transaction may attempt.
     *
     * Every attempt is a real compile, so this is the wall-clock budget in the
     * only unit that means anything. Zero asks for the schedule's own length,
     * which on a map the size of q2dm1 is a couple of hundred compiles - an
     * honest number rather than a comfortable one.
     */
    uint32_t                  max_attempts;

    /*
     * Fidelity ZERO only: what was learned, and what the target can resolve.
     *
     * There is no donor geometry to fork at zero, so the candidate is built
     * out of a snapshot - and out of the frozen target manifest, because a map
     * that names a material the target does not have is a map nobody can load.
     * Above zero these are ignored: the donor's own geometry is the input and
     * a statistics-driven room would be the rejected delivery again.
     */
    char                      snapshot[MAPCOMPILE_MAX_PATH];
    char                      manifest[MAPCOMPILE_MAX_PATH];
    int32_t                   scale;      /* 0 compact .. 3 very large */
    int32_t                   goal;       /* mapgen_goal_t             */

    /*
     * Whether the caller still wants the answer.
     *
     * Part of the request rather than a setting on the module: two runs must
     * be able to be cancelled independently, and a process-global token is the
     * kind of shared mutable state this project has already been bitten by.
     * Called from the walk's worker threads as well as from the run itself, so
     * it must be safe to call concurrently.
     */
    mapgen_pipeline_cancelled_fn cancelled;
    void                        *cancelled_user;

    /*
     * The other donors a room may be brought in from - GF7.
     *
     * By PATH, because the request is what a worker receives across a process
     * boundary and a pointer would not survive it. Empty means one donor,
     * which is what every run before this one meant.
     *
     * They are OFFERED, not required: a donor that has no room interchangeable
     * with one of ours contributes nothing, and the report says so by name
     * rather than leaving it to be noticed.
     */
    char                      other_donors[MAPGEN_PIPELINE_MAX_DONORS]
                                          [MAPCOMPILE_MAX_PATH];
    uint32_t                  num_other_donors;

    /*
     * Families the run must not try (ledger row 394, MAPGEN Studio's «what may
     * change»): edit kinds by their `MapGenGeometryEdit_KindName`, skipped in
     * every pass as if the plan had not dealt them. Empty: every family.
     */
    /* row 410: room for every kind there is - at 16 a longer list was cut short in silence */
    char                      excluded_families[40][32];
    uint32_t                  num_excluded_families;

    /*
     * Resume the run this job folder holds (ledger row 395): its ledger is
     * replayed attempt by attempt (`MapGenTransaction_Replay`) and the run goes
     * on from the first attempt it does not name. The baseline is rebuilt.
     */
    bool                      resume;

    /*
     * Hold the finished map to its DONOR's own walk rather than to the five absolutes (row 400): for a donor
     * whose own walk fails them - cor's ledge start that its straight-up pad cannot reach, its balcony a player
     * can jump off past the kill curtains - the map is delivered when it is no worse than the donor
     * (`MapGenReach_NoWorseThan`), and the finish line says it was. The candidates of a run are held to the donor
     * always; the finished map only when this asks. Off: a map nobody can play is refused, whatever its donor.
     */
    bool                      hold_to_donor;
    /*
     * Row 405 (Fable's brief 5 section 7 L3): the donor's light calibration, added to the finished map's light pass -
     * the settings under which the donor's own faces come out as bright as the donor draws them (wall, floor and
     * ceiling ratios within 0.8..1.25, `tools/mapgen_light_calibrate.py`): cor "-sunradscale 4.0 -scale 1.15"
     * (its diffuse sky, `_sun_diffuse 80`, is a term q2tools does not have), q3t2 "-scale 0.68". Empty: the tool's own.
     */
    char                      light_flags[128];
    /*
     * Row 410 (Fable's brief 7): the donor's sun as q2tools-220 must be told it, `key=value;key=value` written into
     * the lit copy's worldspawn before its sun is added (replacing the donor's own). MEASURED on cor: without
     * `_sun_color` the tool paints the sun in the sky texture's colour (cor's old faces B/R 0.27 of cor's), and the
     * donor's `_sun_angle` is not read the way its own compiler read it. From tools/mapgen_donor_light.json.
     */
    char                      light_keys[256];
    /*
     * Row 411 (Fable's brief 8): the working files of the run - each try's .map, .bsp, .prt, .pts, the base's, the
     * light pass's - in memory, named sections the pinned compiler opens (patch P13), when this is the most memory
     * the run may take (bytes; the caller's share of what is free). 0: in files, as before. A run whose sections
     * would not fit under it works in files and says so (`stage=memory mode=files`).
     */
    uint64_t                  memory_bytes;
    /*
     * Row 411: with the run in memory, the accepted tries are NOT written to the job folder as checkpoints - the run
     * then writes nothing of its tries to the disk, and cannot be resumed. Off (the default): each accepted try's
     * .map and .bsp are written once, where a run in files keeps them, and a stopped run resumes from them.
     */
    bool                      no_checkpoints;
} mapgen_pipeline_request_t;

typedef struct {
    mapgen_generate_report_t  generated;
    mapcompile_report_t       compiled;
    mapgen_reach_report_t     reach;
    mapgen_divergence_t       divergence;

    /* How far each stage got, so a failure says where rather than only that. */
    bool                      wrote_candidate;
    bool                      compiled_a_map;
    bool                      measured_reach;
    bool                      measured_divergence;
    /* D19 (assignment 23): the complete oracle's route axis was marked from
       the final gate's walk and the transaction's baseline walk rather than
       from two new walks */
    bool                      oracle_from_walks;

    /*
     * What the finished candidate looks like against the DONOR, rather than
     * against the baseline everything else is measured from. At fidelity 100
     * an empty mask is required; below that it is evidence, so that a loss
     * already tolerated in the baseline cannot be repeated invisibly.
     */
    uint32_t                  candidate_axes;
    char                      candidate_detail[192];

    char                      map_path[MAPCOMPILE_MAX_PATH];
    char                      bsp_path[MAPCOMPILE_MAX_PATH];

    /*
     * The SHA-256 of the baseline every divergence was measured against: the
     * donor's own geometry through this compiler with nothing applied. A run's
     * numbers cannot be checked without knowing what they were measured
     * against, and it is not the donor's own file.
     */
    char                      baseline_bsp[MAPCOMPILE_SHA256_HEX];

    /*
     * Why each pickup ordinary movement could not reach is still reachable.
     *
     * Stamped with the identity of the artifact that was actually judged, so a
     * reader can tell whether the account in front of them is about the map in
     * front of them. Written beside the map as well, because a report that
     * outlives the process is the point.
     */
    mapgen_certificate_set_t  certificates;

    /* What the fidelity-zero chain built, when that is the path taken. */
    mapgen_synthesis_report_t synthesis;
    bool                      synthesised;

    /*
     * Where the budget went.
     *
     * One line per verdict rather than a count of successes, because the
     * question this path exists to answer is why a fork came back looking like
     * its donor, and the answer is always in the refusals: the operators that
     * declined, and the edits that compiled, stayed playable and moved
     * nothing at all.
     */
    uint32_t                  attempted;
    uint32_t                  accepted;

    /*
     * What the other donors actually gave - GF7's contribution floor.
     *
     * `grafts_accepted` counts rooms that are IN the finished map, not rooms
     * that were offered or tried: a floor met by an edit that was thrown away
     * is not a floor. `donors_offered` is how many were named, so a donor that
     * gave nothing is visible as the difference rather than by its absence.
     */
    uint32_t                  donors_offered;
    uint32_t                  donors_contributed;
    uint32_t                  grafts_accepted;
    char                      donor_name[MAPGEN_PIPELINE_MAX_DONORS][64];
    bool                      donor_used[MAPGEN_PIPELINE_MAX_DONORS];
    /* One slot per verdict, from the transaction's own count rather than a
       number copied here - a tally that stops at eight silently loses the
       ninth, which is how REJECTED_UNMEASURED would have gone unreported. */
    uint32_t                  by_verdict[MAPGEN_TXN_NUM_VERDICTS];
    uint32_t                  reached_permille;
    uint32_t                  missing_permille;
    /*
     * What ended the edits (ledger row 397, Fable's brief 3 G4): "target"
     * (reached), "budget" (the compiles allowed were spent) or "schedule" (every
     * round dealt ran to its end) - so a run short of its target says why rather
     * than calling itself a failure.
     */
    char                      ended_by[16];
    uint32_t                  rounds;
    uint32_t                  compiles;
    uint32_t                  budget;
} mapgen_pipeline_report_t;

/*
 * Run the whole thing in `job_dir`, which must exist and must be empty.
 *
 * `adapter` launches the compiler; production hands it the real one and the
 * qualification harness a fake process. `report` is always written when it is
 * given, including on failure.
 */
/*
 * Told where the run has got to, as it gets there.
 *
 * `percent` is of the whole run and `what` is a short phrase in the product's
 * own words - "compiling the donor", "checking the map" - because the caller
 * that shows it to a player has no vocabulary of its own for the inside of a
 * pipeline.
 *
 * Optional: a caller that passes NULL gets exactly the behaviour every caller
 * had before this existed. It is never called from another thread.
 */
typedef void (*mapgen_pipeline_progress_fn)(void *user, uint32_t percent,
                                            const char *what);

/*
 * Whether the caller still wants the answer.
 *
 * Asked wherever the pipeline is about to spend real time - and passed down
 * into the authoritative walk, which is where nearly all of it goes. Returning
 * true makes the run end as CANCELLED: nothing is written, nothing is staged,
 * and no verdict is reported about a map that was never finished.
 */

/*
 * The run's account (ledger rows 391-392): the last PROGRESS line written -
 * `stage=...` without the prefix and the time - and how many attempt lines the
 * run has written so far. For a crash record written from a fault handler,
 * which has nothing else to say where the run was.
 */
const char *MapGenPipeline_LastProgress(void);
uint32_t MapGenPipeline_AttemptsSoFar(void);

mapgen_pipeline_result_t MapGenPipeline_Run(const char *donor_bsp,
                                            const char *job_dir,
                                            const char *map_name,
                                            const mapcompile_adapter_t *adapter,
                                            const mapgen_pipeline_request_t *request,
                                            mapgen_pipeline_report_t *report,
                                            mapgen_pipeline_progress_fn progress,
                                            void *progress_user);

#endif /* MAPGEN_PIPELINE_H */
