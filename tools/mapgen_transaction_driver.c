/*
 * A whole schedule, spent one edit at a time, with the ledger printed.
 *
 * Every line says what was attempted, what happened to it, and what it was
 * worth. The lines that matter are the refusals: an operator that declined
 * costs nothing and tells you the schedule is offering edits this map cannot
 * take, and an edit that compiles, stays playable and moves the divergence by
 * zero is the whole explanation for a fork that is the donor again.
 *
 *     mapgen_transaction_driver <compiler.exe> <donor.bsp> <job root>
 *                               <map name> <moddir> [seed] [max attempts]
 *
 * `job root` must exist; every attempt gets a fresh directory beneath it.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "common/mapgen_transaction.h"
#include "common/q2prox_cpu_topology.h"

static const char *stage_flags(mapcompile_stage_t stage)
{
    switch (stage) {
    case MAPCOMPILE_STAGE_BSP:      return "-bsp";
    case MAPCOMPILE_STAGE_VIS_FAST: return "-vis -fast";
    case MAPCOMPILE_STAGE_VIS:      return "-vis";
    /*
     * -rad, and the name matters: q2tool has no -light mode.
     *
     * It was -light here and in two drivers, and q2tool answers an unknown
     * mode by doing nothing and exiting ZERO - so the stage was scheduled,
     * reported as run, and produced no lightmap. Every map this generator has
     * ever published carries a lighting lump of 0 bytes against the donor's
     * 362745, which is why they render flat grey. mapgen_compile_driver.c had
     * it right all along.
     */
    /*
     * Row 404: the light lump may outgrow the original 2 MB. cor's own carries 3406620 bytes and its
     * copy needs 2332599, which the tool refuses by default (`lightdatasize > maxdata`) and the stage then
     * handed back an unlit map. Q2PRO-X takes a lump of any size; a map under 2 MB lights byte for byte
     * as it did (q2dm1, measured).
     */
    case MAPCOMPILE_STAGE_RAD:      return "-rad -maxdata 8388608";
    case MAPCOMPILE_STAGE_COUNT:    break;
    }
    return "-bsp";
}

/*
 * What the machine actually did, charged WHERE IT HAPPENS.
 *
 * The budget used to be counted from verdicts, which charges a compile for
 * refusals that never reached the compiler and charges nothing for the
 * baseline and the finishing pass (Codex's review, §D1). A stage is charged
 * here, in the one function that launches the compiler, so the number cannot
 * drift from the work.
 */
static uint32_t g_stages[MAPCOMPILE_STAGE_COUNT];
static uint32_t g_compiles;          /* candidates put through the compiler  */
static double   g_stage_seconds;
/* D18 (assignment 22): where the attempts' time went, summed over the run */
static uint64_t g_ms_apply, g_ms_compile, g_ms_load, g_ms_reach, g_ms_seams,
                g_ms_water, g_ms_pairs, g_ms_parent, g_ms_divergence,
                g_ms_accept, g_ms_total;
/* D20 (assignment 23): the walks' shape, summed over the run */
static uint64_t g_walk_levels, g_walk_wide, g_walk_rounds;
static uint32_t g_walked;
/* D28 (assignment 24): the attempts and their walks in CPU milliseconds */
static uint64_t g_cpu_total, g_cpu_reach;

static mapcompile_result_t run_stage(void *ctx,
                                     const mapcompile_request_t *request,
                                     mapcompile_stage_t stage,
                                     mapcompile_stage_report_t *out)
{
    const char *compiler = (const char *)ctx;
    /*
     * WALL time, not `clock()`.
     *
     * MEASURED 2026-09-13: the first version used `clock()` and reported «1 s in
     * the compiler» for two compiles that took most of forty seconds. `clock()`
     * is this process's own CPU time and the compiler is a CHILD, so its work is
     * never in it - the instrument read zero by construction, which is the same
     * class of defect as a counter nobody can see.
     */
    const time_t started = time(NULL);
    if ((unsigned)stage < MAPCOMPILE_STAGE_COUNT)
        g_stages[stage]++;
    if (stage == MAPCOMPILE_STAGE_BSP)
        g_compiles++;                /* one per candidate: bsp leads every set */

    char command[4096];
    const int n = snprintf(command, sizeof(command),
                           "\"\"%s\" %s -threads %d -moddir \"%s\""
                           " -basedir \"%s\" -gamedir \"%s\" \"%s/%s.map\"\""
                           " 2>&1",
                           compiler, stage_flags(stage), request->threads,
                           request->moddir, request->basedir, request->basedir,
                           request->job_dir, request->map_name);
    if (n <= 0 || (size_t)n >= sizeof(command))
        return MAPCOMPILE_ERR_INVALID_REQUEST;

    FILE *pipe = popen(command, "r");
    if (!pipe)
        return MAPCOMPILE_ERR_LAUNCH;

    const size_t cap = request->max_log_bytes < 262144u
                     ? request->max_log_bytes : 262144u;
    char *kept = malloc(cap + 1);
    size_t held = 0;
    uint64_t total = 0;
    int c;
    while ((c = fgetc(pipe)) != EOF) {
        total++;
        if (kept && held < cap)
            kept[held++] = (char)((c >= 32 || c == '\n') ? c : ' ');
    }
    if (kept)
        kept[held] = '\0';

    out->exit_code = pclose(pipe);
    out->stdout_total_bytes = total;
    out->stdout_captured = kept;
    out->stdout_captured_bytes = held;
    out->stdout_truncated = total > held;
    /*
     * MEASURED AGAIN, 2026-09-13: `difftime(time(NULL), started)` ALSO reported
     * «1 s» for a forty-second run. The stage is timed correctly here - the
     * seconds are simply spent before this line, inside `fgetc` draining the
     * pipe, and the two bsp/vis-fast stages of a DRAFT compile really are about
     * half a second each; the forty seconds of the run are the baseline's own
     * full compile plus the reach walk, which are not stages of this adapter.
     * So the number is right and its LABEL was the lie: it is the time inside
     * the stages this adapter ran, not the time the run took.
     */
    g_stage_seconds += difftime(time(NULL), started);
    return MAPCOMPILE_OK;
}

/*
 * `--only` names one family or several, comma-separated - «dig,window,flood»
 * for the PO's showcase map (ledger rows 247-248), which carries three families
 * on one candidate.
 */
/* `--skip` names schedule indices to leave out, comma-separated: edits a run
   already refused for reasons the next run does not touch (ledger row 254) */
static bool index_in_list(const char *list, uint32_t index)
{
    for (const char *p = list; p && *p;) {
        char *end = NULL;
        const unsigned long v = strtoul(p, &end, 10);
        if (end != p && v == index)
            return true;
        p = end && *end == ',' ? end + 1 : NULL;
    }
    return false;
}

static bool kind_in_list(const char *list, const char *name)
{
    const size_t n = strlen(name);
    for (const char *p = list; p && *p;) {
        const char *end = strchr(p, ',');
        const size_t len = end ? (size_t)(end - p) : strlen(p);
        if (len == n && !strncmp(p, name, n))
            return true;
        p = end ? end + 1 : NULL;
    }
    return false;
}

int main(int argc, char **argv)
{
    if (argc < 6) {
        fprintf(stderr, "usage: %s <compiler.exe> <donor.bsp> <job root>"
                        " <map name> <moddir> [seed] [max attempts]\n",
                argv[0]);
        return 2;
    }
    /* D28: the run's wall clock and this process's CPU, from here */
    const clock_t run_began = clock();
    const uint64_t run_cpu_began = Q2PROX_Cpu_ProcessMs();
    const uint64_t seed = argc > 6 ? strtoull(argv[6], NULL, 10) : 1;
    /* Not const: `--flood-at` narrows it to the one attempt it selected. */
    uint32_t limit = argc > 7 ? (uint32_t)strtoul(argv[7], NULL, 10)
                              : 64u;
    /* Ask about one operator without paying for the two hundred edits that
       come before it in the schedule. */
    const char *only = NULL;
    const char *skip = NULL;
    /*
     * And at WHAT DISTANCE from the donor the schedule is dealt.
     *
     * MEASURED 2026-09-13: without this the driver dealt at ambition zero and
     * q2dm1 offers exactly ONE flood there - the arena, `944 304 384 .. 1744
     * 1008 448`. Room 4's flood (`496 944 678 .. 1072 1680 768`) is dealt only
     * from about ambition 80, and room 4 is the only case that reaches the
     * repaired buried-route branch. So the one test assignment 18 asks for was
     * not expressible by this tool: it could compile a flood and never the
     * flood in question. The pipeline has always set this (`SetAmbition(100 -
     * fidelity)`); the driver that exists to ask about one operator could not.
     */
    int32_t ambition = 0;
    /*
     * D7: WHICH ROOM, by a point inside it - never by an index.
     *
     * MEASURED 2026-09-13 (ledger rows 173-175): a flood index read from
     * `recut_driver --list` was passed to this driver as «the second flood»,
     * and the run flooded a different room - `BeginWith` redeals against the
     * compiled baseline and `SetAmbition` redeals again, so the two plans are
     * different objects and an index means nothing across them. Every
     * conclusion drawn from that run named the wrong room. A point is a fact
     * about the map; an index is a fact about one deal.
     */
    bool flood_at = false;
    float flood_point[2] = { 0.0f, 0.0f };
    for (int a = 8; a + 1 < argc; a++) {
        if (!strcmp(argv[a], "--only"))
            only = argv[a + 1];
        if (!strcmp(argv[a], "--skip"))
            skip = argv[a + 1];
        /* a showcase count for the tunnel deal; 0 keeps the ambition's */
        if (!strcmp(argv[a], "--digs"))
            MapGenGeometryEdit_WantDigs(
                (uint32_t)strtoul(argv[a + 1], NULL, 10));
        if (!strcmp(argv[a], "--ambition"))
            ambition = (int32_t)strtol(argv[a + 1], NULL, 10);
        if (!strcmp(argv[a], "--flood-at") && a + 2 < argc) {
            flood_at = true;
            flood_point[0] = strtof(argv[a + 1], NULL);
            flood_point[1] = strtof(argv[a + 2], NULL);
        }
    }
    /*
     * The room block is not dealt into any product schedule - see
     * `MapGenGeometryEdit_DealRoomBlocks` - and this is the only caller that
     * asks for it back. The carving guard needs an operator that builds real
     * brushwork on a bare fixture to drive the transaction's fault, leak and
     * playability gates with; without one it would ask its questions of an
     * empty schedule and pass for the wrong reason.
     *
     * A flag with no value of its own, so it is read over the whole tail
     * rather than in pairs.
     */
    for (int a = 8; a < argc; a++) {
        if (!strcmp(argv[a], "--crates"))
            MapGenGeometryEdit_DealRoomBlocks(true);
        /* The recut, likewise: undealt in every product schedule since the
           PO's fourth round, and asked back here for the guards. */
        if (!strcmp(argv[a], "--recuts"))
            MapGenGeometryEdit_DealRecuts(true);
        /* The breakable pane, likewise: the stock game frees a
           func_explosive at spawn in deathmatch, so no product schedule
           deals one, and this is what regenerates the launch guard's red
           map. */
        if (!strcmp(argv[a], "--breakable"))
            MapGenGeometryEdit_DealBreakableGlass(true);
        /* The 128 x 128 pit, likewise: refused by the PO three times over
           rounds seven and eight, undealt in every product schedule since, and
           asked back here so its own guards keep their operator. */
        if (!strcmp(argv[a], "--pits"))
            MapGenGeometryEdit_DealPits(true);
        /* the PO's own watched routes among the tunnel candidates, the same
           three landmarks `mapgen_recut_driver.c --powatch` reads out of his
           demo of 2026-09-11 */
        if (!strcmp(argv[a], "--powatch")) {
            const float a_from[3] = { 1430.0f, 870.0f, 448.0f };
            const float a_to[3]   = { 1465.0f, 850.0f, 328.0f };
            const float b_from[3] = { 1330.0f, 300.0f, 640.0f };
            const float b_to[3]   = { 1440.0f, 290.0f, 510.0f };
            const float c_from[3] = { 1150.0f, -40.0f, 896.0f };
            const float c_to[3]   = { 300.0f, -400.0f, 444.0f };
            MapGenGeometryEdit_WatchDig(a_from, a_to, "a arena->corridor");
            MapGenGeometryEdit_WatchDig(b_from, b_to, "b ledge->room below");
            MapGenGeometryEdit_WatchDig(c_from, c_to, "c rocket->railgun");
        }
        if (!strcmp(argv[a], "--showcase-glass"))
            MapGenGeometryEdit_ShowcaseGlass(true);
        /* row 408: the finished map's light pass words, as the pipeline's --light-flags */
        if (!strcmp(argv[a], "--light-flags") && a + 1 < argc)
            MapGenGeometryEdit_SetLightFlags(argv[a + 1]);
        /* row 405 (W5): spans asked for on a map that is no arena - the span fixture */
        if (!strcmp(argv[a], "--spans") && a + 1 < argc)
            MapGenGeometryEdit_DigSpans((uint32_t)strtoul(argv[a + 1], NULL, 10));
    }

    const mapcompile_adapter_t adapter = { "q2tool", (void *)argv[1],
                                           run_stage, NULL };

    mapgen_transaction_t *txn = NULL;
    mapgen_equiv_report_t why;
    memset(&why, 0, sizeof(why));
    const mapgen_transaction_result_t rc =
        MapGenTransaction_BeginWith(argv[2], argv[3], argv[4], argv[5],
                                    &adapter, seed, &why, &txn);
    if (rc != MAPGEN_TXN_OK) {
        printf("%s\n", MapGenTransaction_ResultName(rc));
        /*
         * Why, when the reason is the baseline. The transaction that knew it
         * is destroyed before a caller can ask, so the report comes out
         * alongside the code.
         */
        if (why.axis[0])
            printf("baseline %s: %s\n", why.axis, why.detail);
        return 2;
    }

    if (ambition)
        MapGenTransaction_SetAmbition(txn, ambition);
    const mapgen_geometry_edit_plan_t *plan = MapGenTransaction_Plan(txn);
    const uint32_t offered = MapGenGeometryEdit_Count(plan);
    printf("the schedule offers %u edits at ambition %d; attempting up to"
           " %u%s%s\n", offered, ambition, limit, only ? " of kind " : "",
           only ? only : "");

    /*
     * The identity of what is about to be attempted, printed BEFORE it is,
     * and refused when it is not exactly one thing.
     */
    bool have_target = false;
    uint32_t target = 0;
    if (flood_at) {
        uint32_t matches = 0;
        float mlo[3], mhi[3];
        for (uint32_t i = 0; i < offered; i++) {
            const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
            float lo[3], hi[3];
            if (!e || e->kind != MAPGEN_EDIT_FLOOD)
                continue;
            /* NULL donor handles: a flood's box is its own family record and
               needs neither the ground nor the geometry (`BoxOf`'s contract). */
            if (!MapGenGeometryEdit_BoxOf(plan, NULL, NULL, i, lo, hi))
                continue;
            if (flood_point[0] < lo[0] || flood_point[0] > hi[0]
                || flood_point[1] < lo[1] || flood_point[1] > hi[1])
                continue;
            matches++;
            target = i;
            memcpy(mlo, lo, sizeof(mlo));
            memcpy(mhi, hi, sizeof(mhi));
            printf("  flood %u at %.0f %.0f %.0f .. %.0f %.0f %.0f\n", i,
                   (double)lo[0], (double)lo[1], (double)lo[2],
                   (double)hi[0], (double)hi[1], (double)hi[2]);
        }
        if (matches != 1) {
            printf("REFUSED: %u floods of this plan contain %.0f %.0f -"
                   " an attempt must name exactly one room\n", matches,
                   (double)flood_point[0], (double)flood_point[1]);
            MapGenTransaction_Free(txn);
            return 2;
        }
        have_target = true;
        limit = 1;
        only = NULL;
        printf("  SELECTED flood %u, footprint %.0f %.0f %.0f .. %.0f %.0f"
               " %.0f\n", target, (double)mlo[0], (double)mlo[1],
               (double)mlo[2], (double)mhi[0], (double)mhi[1], (double)mhi[2]);
        printf("  donor      %s\n", argv[2]);
        printf("  baseline   %s\n", MapGenTransaction_BaselineBsp(txn));
        printf("  baseline   sha256 %.16s\n",
               MapGenTransaction_BaselineSha256(txn));
        printf("  accepted   digest %016llx\n",
               (unsigned long long)MapGenTransaction_AcceptedDigest(txn));
        printf("  seed %llu, ambition %d\n", (unsigned long long)seed,
               ambition);
        fflush(stdout);
    }

    uint32_t spent = 0;
    for (uint32_t i = 0; i < offered && spent < limit; i++) {
        const mapgen_geometry_edit_t *planned = MapGenGeometryEdit_At(plan, i);
        if (!planned)
            break;
        if (only && !kind_in_list(only,
                                  MapGenGeometryEdit_KindName(planned->kind)))
            continue;
        if (have_target && i != target)
            continue;
        if (skip && index_in_list(skip, i))
            continue;
        spent++;

        const mapgen_typed_edit_t edit = { planned->kind, i, planned->amount };
        mapgen_transaction_step_t step;
        MapGenTransaction_Try(txn, &edit, &step);

        printf("  %4u %-14s %-22s", i,
               MapGenGeometryEdit_KindName(planned->kind),
               MapGenTransaction_VerdictName(step.verdict));
        if (step.verdict == MAPGEN_TXN_ACCEPTED)
            printf("  divergence %4u (%+d), %u brushes, %u ms",
                   step.divergence_after, step.divergence_delta,
                   step.brushes_after, step.compile_ms);
        else if (step.compile_result != MAPCOMPILE_OK)
            printf("  %s", MapCompile_ResultName(step.compile_result));
        /*
         * WHATEVER the refusal, say what it said.
         *
         * This printed `declined` for `REJECTED_NOT_APPLIED` alone, so every
         * reason a GATE wrote - the buried climb place and which question it
         * failed, the machine that lost room, the blocking mover - was computed
         * and thrown away. That is the same defect twice over: the gate knows
         * and the report does not say. Ledger rows 126, 144, 153.
         */
        if (step.declined[0])
            printf("  %s", step.declined);
        if (step.verdict == MAPGEN_TXN_ACCEPTED
            || step.verdict == MAPGEN_TXN_REJECTED_SURFACE)
            printf("  source seams %u, compiled %u (%u liquid)",
                   step.faults_after, step.tjunctions_after,
                   step.tjunctions_liquid);
        if ((step.verdict == MAPGEN_TXN_ACCEPTED
             || step.verdict == MAPGEN_TXN_REJECTED_SURFACE)
            && step.tjunctions_cross_model)
            printf(", %u cross-model", step.tjunctions_cross_model);
        if ((step.verdict == MAPGEN_TXN_ACCEPTED
             || step.verdict == MAPGEN_TXN_REJECTED_SURFACE)
            && step.tjunctions_skin)
            printf(", %u in a skin's gap", step.tjunctions_skin);
        if (step.verdict == MAPGEN_TXN_REJECTED_SURFACE
            && (step.new_seam[0] || step.new_seam[1] || step.new_seam[2]))
            printf("  new seam at %.1f %.1f %.1f", (double)step.new_seam[0],
                   (double)step.new_seam[1], (double)step.new_seam[2]);
        /*
         * A flood's own trace: how many ways it took away inside its footprint
         * and how many it proved a replacement for. Assignment 18's S1
         * measurement asks for exactly this pair beside the verdict, because
         * «accepted» and «replaced every one of eleven» are different facts and
         * a reader cannot derive either from the other.
         */
        if (planned->kind == MAPGEN_EDIT_FLOOD)
            printf("  flood places %u, replaced %u, entrances %u, pairs proved"
                   " %u, excused %u", step.flood_places, step.flood_replaced,
                   step.flood_entrances, step.flood_pairs_proved,
                   step.flood_pairs_excused);
        /* D16: a tunnel's mouth, proved like a flood's box */
        if (planned->kind == MAPGEN_EDIT_DIG)
            printf("  mouth entrances %u, pairs proved %u, excused %u, lost %u",
                   step.dig_entrances, step.dig_pairs_proved,
                   step.dig_pairs_excused, step.dig_pairs_lost);
        if (step.dig_pairs_lost)
            printf(" (first %.0f %.0f %.0f - %.0f %.0f %.0f)",
                   (double)step.dig_lost_from[0], (double)step.dig_lost_from[1],
                   (double)step.dig_lost_from[2], (double)step.dig_lost_to[0],
                   (double)step.dig_lost_to[1], (double)step.dig_lost_to[2]);
        /* D18: where this attempt's time went */
        if (step.total_ms)
            printf("  ms %u: apply %u compile %u load %u reach %u seams %u"
                   " water %u pairs %u parent %u divergence %u accept %u",
                   step.total_ms, step.apply_ms, step.compile_ms, step.load_ms,
                   step.reach_ms, step.seams_ms, step.water_ms, step.pairs_ms,
                   step.parent_ms, step.divergence_ms, step.accept_ms);
        /* D28: and in CPU */
        if (step.total_ms)
            printf("  cpu %u (reach %u)", step.total_cpu_ms,
                   step.reach_cpu_ms);
        g_cpu_total += step.total_cpu_ms;
        g_cpu_reach += step.reach_cpu_ms;
        g_ms_apply += step.apply_ms;
        g_ms_compile += step.compile_ms;
        g_ms_load += step.load_ms;
        g_ms_reach += step.reach_ms;
        g_ms_seams += step.seams_ms;
        g_ms_water += step.water_ms;
        g_ms_pairs += step.pairs_ms;
        g_ms_parent += step.parent_ms;
        g_ms_divergence += step.divergence_ms;
        g_ms_accept += step.accept_ms;
        g_ms_total += step.total_ms;
        /* D20 and D21 (assignment 23): the walk's shape, and how much of the
           parent's walk this edit could touch */
        if (step.walk_states)
            printf("  walk %u states %u edges %u levels (%u wide) %u rounds"
                   " %u movers", step.walk_states, step.walk_edges,
                   step.walk_levels, step.walk_levels_wide, step.walk_rounds,
                   step.walk_movers);
        if (step.parent_states)
            printf("  parent %u near %u/%u", step.parent_states,
                   step.parent_near_512, step.parent_near_1024);
        if (step.walk_states) {
            g_walk_levels += step.walk_levels;
            g_walk_wide += step.walk_levels_wide;
            g_walk_rounds += step.walk_rounds;
            g_walked++;
        }
        /* What a construction turned out to be worth: how many places a
           player can get to ON it. Zero is the whole of REJECTED_WORTHLESS. */
        if (planned->kind == MAPGEN_EDIT_ROOM_BLOCK
            || planned->kind == MAPGEN_EDIT_RECUT_ROOM)
            printf("  on it %u", step.places_on_construction);
        /* The raw structural count, whenever the scalar score could not
           decide and the authoritative measurement was taken. Printed
           separately from the score because they are different quantities:
           an edit can change cells and buy no permille. */
        if (step.structural_measured)
            printf("  structural %u cells%s", step.structural_cells,
                   step.structural_routes ? "" : " (no routes)");
        else if (step.verdict == MAPGEN_TXN_REJECTED_UNMEASURED)
            printf("  structural NOT MEASURED");
        printf("\n");
        fflush(stdout);

        /*
         * And one line per attempt to a file, flushed, so a run that is killed
         * leaves every attempt it finished.
         *
         * `_IONBF` on stdout was not enough: the parent buffers a child's pipe
         * until it exits, and a killed run left nothing at all (ledger row
         * 132). This is owned by the job, not by whoever is reading stdout.
         */
        {
            char log_path[1024];
            if (snprintf(log_path, sizeof(log_path), "%s/attempts.log",
                         argv[3]) < (int)sizeof(log_path)) {
                FILE *log = fopen(log_path, "a");
                if (log) {
                    float lo[3] = { 0, 0, 0 }, hi[3] = { 0, 0, 0 };
                    const bool placed =
                        MapGenGeometryEdit_BoxOf(plan, NULL, NULL, i, lo, hi);
                    fprintf(log,
                            "attempt=%u edit=%u family=%s verdict=%s"
                            " divergence=%u parent=%016llx candidate=%.16s"
                            " box=%s", spent, i,
                            MapGenGeometryEdit_KindName(planned->kind),
                            MapGenTransaction_VerdictName(step.verdict),
                            step.divergence_after,
                            (unsigned long long)
                                MapGenTransaction_AcceptedDigest(txn),
                            step.bsp_sha256[0] ? step.bsp_sha256 : "-",
                            placed ? "" : "none");
                    if (placed)
                        fprintf(log, "%.0f %.0f %.0f..%.0f %.0f %.0f",
                                (double)lo[0], (double)lo[1], (double)lo[2],
                                (double)hi[0], (double)hi[1], (double)hi[2]);
                    if (planned->kind == MAPGEN_EDIT_FLOOD)
                        fprintf(log, " flood_places=%u flood_replaced=%u"
                                     " flood_entrances=%u"
                                     " flood_pairs_proved=%u"
                                     " flood_pairs_excused=%u",
                                step.flood_places, step.flood_replaced,
                                step.flood_entrances,
                                step.flood_pairs_proved,
                                step.flood_pairs_excused);
                    if (planned->kind == MAPGEN_EDIT_DIG) {
                        fprintf(log, " dig_entrances=%u dig_pairs_proved=%u"
                                     " dig_pairs_excused=%u dig_pairs_lost=%u",
                                step.dig_entrances, step.dig_pairs_proved,
                                step.dig_pairs_excused, step.dig_pairs_lost);
                        /* row 408: its two ends and its shape, so a light measure can find its doors */
                        mapgen_dig_report_t dr;
                        if (MapGenGeometryEdit_DigAt(plan, planned->target, &dr))
                            fprintf(log, " dig_from=%.0f,%.0f,%.0f dig_to=%.0f,%.0f,%.0f dig_shape=%s",
                                    (double)dr.from[0], (double)dr.from[1], (double)dr.from[2],
                                    (double)dr.to[0], (double)dr.to[1], (double)dr.to[2],
                                    dr.shape[0] ? dr.shape : "-");
                    }
                    fprintf(log, " ms_total=%u ms_compile=%u ms_reach=%u"
                                 " ms_pairs=%u ms_parent=%u ms_divergence=%u",
                            step.total_ms, step.compile_ms, step.reach_ms,
                            step.pairs_ms, step.parent_ms,
                            step.divergence_ms);
                    fprintf(log, " ms_total_cpu=%u ms_reach_cpu=%u",
                            step.total_cpu_ms, step.reach_cpu_ms);
                    fprintf(log, " walk_states=%u walk_edges=%u walk_levels=%u"
                                 " walk_wide=%u walk_rounds=%u walk_movers=%u"
                                 " parent_states=%u parent_near_512=%u"
                                 " parent_near_1024=%u",
                            step.walk_states, step.walk_edges,
                            step.walk_levels, step.walk_levels_wide,
                            step.walk_rounds, step.walk_movers,
                            step.parent_states, step.parent_near_512,
                            step.parent_near_1024);
                    if (step.declined[0])
                        fprintf(log, " why=\"%s\"", step.declined);
                    fprintf(log, "\n");
                    fclose(log);
                }
            }
        }
    }

    /* What the machine did, apart from what the schedule offered: a compile is
       charged where the adapter starts one, never inferred from a verdict. */
    /* «compiles», not «candidate compiles»: the BASELINE goes through the same
       adapter and is real work that used to be charged to nobody. */
    printf("machine: %u compiles (the baseline among them), stages bsp %u /"
           " vis-fast %u / vis %u / rad %u, %.0f s inside those stages\n",
           g_compiles,
           g_stages[MAPCOMPILE_STAGE_BSP], g_stages[MAPCOMPILE_STAGE_VIS_FAST],
           g_stages[MAPCOMPILE_STAGE_VIS], g_stages[MAPCOMPILE_STAGE_RAD],
           g_stage_seconds);
    {
        const uint64_t named = g_ms_apply + g_ms_compile + g_ms_load
            + g_ms_reach + g_ms_seams + g_ms_water + g_ms_pairs + g_ms_parent
            + g_ms_divergence + g_ms_accept;
        printf("time in attempts: %.0f s - apply %.0f, compile %.0f, load %.0f,"
               " reach %.0f, seams %.0f, water %.0f, pairs %.0f, parent %.0f,"
               " divergence %.0f, accept %.0f, the rest %.0f\n",
               (double)g_ms_total / 1000.0, (double)g_ms_apply / 1000.0,
               (double)g_ms_compile / 1000.0, (double)g_ms_load / 1000.0,
               (double)g_ms_reach / 1000.0, (double)g_ms_seams / 1000.0,
               (double)g_ms_water / 1000.0, (double)g_ms_pairs / 1000.0,
               (double)g_ms_parent / 1000.0, (double)g_ms_divergence / 1000.0,
               (double)g_ms_accept / 1000.0,
               g_ms_total > named ? (double)(g_ms_total - named) / 1000.0
                                  : 0.0);
    }
    /* D28 (assignment 24): CPU beside wall, and what the walk had to run on */
    printf("cpu in attempts: %.0f s, the walks %.0f s; the run %.0f s wall and"
           " %.0f s cpu in this process; %d logical CPUs in the affinity"
           " mask, the walk takes %d workers\n",
           (double)g_cpu_total / 1000.0, (double)g_cpu_reach / 1000.0,
           (double)(clock() - run_began) / CLOCKS_PER_SEC,
           (double)(Q2PROX_Cpu_ProcessMs() - run_cpu_began) / 1000.0,
           Q2PROX_Cpu_AffinityCount(), Q2PROX_Cpu_PerformanceCount());
    printf("walks: %u candidates walked, %llu levels (%llu wide), %llu rounds\n",
           g_walked, (unsigned long long)g_walk_levels,
           (unsigned long long)g_walk_wide, (unsigned long long)g_walk_rounds);
    printf("donor faults: %u\n", MapGenTransaction_DonorFaults(txn));
    printf("\n%u attempted, %u accepted; divergence %u permille\n",
           MapGenTransaction_Attempted(txn), MapGenTransaction_Accepted(txn),
           MapGenTransaction_Divergence(txn));
    printf("accepted candidate: %s\n", MapGenTransaction_AcceptedBsp(txn));
    printf("accepted digest: %016llx\n",
           (unsigned long long)MapGenTransaction_AcceptedDigest(txn));
    printf("immutability violations: %u\n",
           MapGenTransaction_Violations(txn));

    /*
     * Where the budget went, which is the number the batch could never give.
     *
     * There are EIGHT verdicts. The loop below counted into an array of eight
     * and printed seven, so REJECTED_SURFACE was tallied and never shown - a
     * ledger that silently omitted a whole outcome. It went unnoticed until a
     * seeded schedule produced one within the first twelve attempts.
     */
    #define NUM_VERDICTS MAPGEN_TXN_NUM_VERDICTS
    uint32_t by_verdict[NUM_VERDICTS];
    memset(by_verdict, 0, sizeof(by_verdict));
    const uint32_t steps = MapGenTransaction_Steps(txn);
    for (uint32_t i = 0; i < steps; i++) {
        const mapgen_transaction_step_t *s = MapGenTransaction_Step(txn, i);
        if ((unsigned)s->verdict < NUM_VERDICTS)
            by_verdict[s->verdict]++;
    }
    printf("ledger:");
    for (uint32_t v = 0; v < NUM_VERDICTS; v++) {
        if (by_verdict[v])
            printf(" %s=%u",
                   MapGenTransaction_VerdictName((mapgen_transaction_verdict_t)v),
                   by_verdict[v]);
    }
    printf("\n");

    MapGenTransaction_Free(txn);
    return 0;
}
