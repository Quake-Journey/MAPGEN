/*
 * The compile runner, driven against a REAL child process.
 *
 * The Adapter here launches the qualification harness's fake compiler as an
 * actual process and reports what it did; the runner then decides the verdict
 * by reading artifacts. That split is the contract's, and it is the reason this
 * driver exists at all: an in-process seam has no concept of an exit code or a
 * flooded pipe, so a guard that proved the runner against a function pointer
 * returning canned values would prove nothing about the case where a compiler
 * exits ZERO and has leaked.
 *
 * What this driver's adapter does NOT do is time out or detect a crash. Those
 * belong to the process Adapter in src/windows, which owns job objects, wait
 * handles and exit-status decoding and is qualified separately; `popen` can
 * report neither. The runner's own handling of both is exercised by the two
 * `--simulate` modes, which set the flags the process Adapter would set.
 *
 *     mapgen_compile_driver <python> <fake.py> <behavior> <job dir> <map name>
 *                           [draft|final] [--simulate timeout|crash|launch]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mapgen_compiler.h"

typedef struct {
    const char *python;
    const char *script;
    const char *behavior;
    const char *simulate;
} fake_t;

static const char *stage_flag(mapcompile_stage_t stage)
{
    switch (stage) {
    case MAPCOMPILE_STAGE_BSP:      return "-bsp";
    case MAPCOMPILE_STAGE_VIS_FAST: return "-vis -fast";
    case MAPCOMPILE_STAGE_VIS:      return "-vis";
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

static mapcompile_result_t run_stage(void *ctx,
                                     const mapcompile_request_t *request,
                                     mapcompile_stage_t stage,
                                     mapcompile_stage_report_t *out)
{
    fake_t *fake = (fake_t *)ctx;

    if (fake->simulate) {
        /* The flags the process Adapter would set, so the runner's handling of
           each is exercised without pretending popen can see them. */
        if (!strcmp(fake->simulate, "timeout")) {
            out->timed_out = true;
            return MAPCOMPILE_OK;
        }
        if (!strcmp(fake->simulate, "crash")) {
            out->crashed = true;
            return MAPCOMPILE_OK;
        }
        if (!strcmp(fake->simulate, "launch"))
            return MAPCOMPILE_ERR_LAUNCH;
    }

    char command[4096];
    const int n = snprintf(command, sizeof(command),
                           "\"\"%s\" \"%s\" --behavior %s %s -threads %d"
                           " -moddir \"%s\" -basedir \"%s\" \"%s/%s.map\"\" 2>&1",
                           fake->python, fake->script, fake->behavior,
                           stage_flag(stage), request->threads,
                           request->moddir, request->basedir,
                           request->job_dir, request->map_name);
    if (n <= 0 || (size_t)n >= sizeof(command))
        return MAPCOMPILE_ERR_INVALID_REQUEST;

    FILE *pipe = popen(command, "r");
    if (!pipe)
        return MAPCOMPILE_ERR_LAUNCH;

    /*
     * Bounded on the way in, and the WHOLE stream still counted. A compiler
     * that floods its output must not be able to destroy the evidence of what
     * it said before it started flooding, nor the disk budget.
     */
    const size_t cap = request->max_log_bytes < 65536u
                     ? request->max_log_bytes : 65536u;
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

    const int status = pclose(pipe);
    out->exit_code = status;
    out->stdout_total_bytes = total;
    out->stdout_captured = kept;
    out->stdout_captured_bytes = held;
    out->stdout_truncated = total > held;
    return MAPCOMPILE_OK;
}

int main(int argc, char **argv)
{
    if (argc < 6) {
        fprintf(stderr, "usage: %s <python> <fake.py> <behavior> <job dir>"
                        " <map name> [draft|final] [--simulate WHAT]\n",
                argv[0]);
        return 2;
    }

    fake_t fake = { argv[1], argv[2], argv[3], NULL };
    mapcompile_request_t request;
    memset(&request, 0, sizeof(request));
    snprintf(request.job_dir, sizeof(request.job_dir), "%s", argv[4]);
    snprintf(request.map_name, sizeof(request.map_name), "%s", argv[5]);
    snprintf(request.moddir, sizeof(request.moddir), "%s", argv[4]);
    snprintf(request.basedir, sizeof(request.basedir), "%s", argv[4]);
    request.profile = MAPCOMPILE_PROFILE_DRAFT;
    request.format = MAPCOMPILE_FORMAT_IBSP;
    request.threads = MAPCOMPILE_PINNED_THREADS;
    request.stage_timeout_ms = 600000;
    request.max_log_bytes = 65536;
    request.disk_budget_bytes = 256u * 1024u * 1024u;

    for (int a = 6; a < argc; a++) {
        if (!strcmp(argv[a], "final"))
            request.profile = MAPCOMPILE_PROFILE_FINAL;
        else if (!strcmp(argv[a], "--simulate") && a + 1 < argc)
            fake.simulate = argv[++a];
        else if (!strcmp(argv[a], "--tiny-disk"))
            request.disk_budget_bytes = 1;
        else if (!strcmp(argv[a], "--tiny-log"))
            request.max_log_bytes = 8;
    }

    const mapcompile_adapter_t adapter = { "fake", &fake, run_stage, NULL };
    mapcompile_report_t report;
    const mapcompile_result_t rc =
        MapCompile_RunProfile(&adapter, &request, &report);

    printf("%s\n", MapCompile_ResultName(rc));
    printf("  stages %d  reread %d  semantics %d\n", report.num_stages,
           (int)report.reread_performed, (int)report.semantics_checked);
    if (report.bsp_sha256[0])
        printf("  bsp %llu bytes, sha256 %.16s\n",
               (unsigned long long)report.bsp_bytes, report.bsp_sha256);
    if (report.semantic_digest[0])
        printf("  semantic %.16s\n", report.semantic_digest);
    printf("  job dir %llu bytes\n", (unsigned long long)report.job_dir_bytes);

    for (int i = 0; i < report.num_stages; i++)
        free(report.stages[i].stdout_captured);
    return rc == MAPCOMPILE_OK ? 0 : 1;
}
