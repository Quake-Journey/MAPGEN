/*
 * The whole product path, from a donor to a verdict, with the REAL compiler.
 *
 * Generate, compile, validate, measure - one call, one answer. This is the
 * thing that did not exist: the pieces have all been runnable one at a time
 * from a shell for a while, and running them in order by hand is not the same
 * as a path the product has.
 *
 *     mapgen_pipeline_driver <compiler.exe> <donor.bsp> <job dir> <map name>
 *                            [fidelity] [seed] [--diagnostic] [--final]
 *                            [--moddir DIR] [--donor OTHER.bsp ...]
 *                            [--fake <python> <behaviour>]
 *
 * `job dir` must exist and be empty. It is also handed to the compiler as its
 * moddir and basedir, so a run reads the job-local mirror and never an ambient
 * game directory - which is contract 5.6 and is also the only way two runs can
 * be compared.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <windows.h>
#include <dbghelp.h>

#include "common/mapgen_digest.h"
#include "common/mapgen_divergence.h"
#include "common/mapgen_pipeline.h"
#include "common/mapgen_transaction.h"
#include "common/mapgen_geometry_edit.h"
#include "common/q2prox_cpu_topology.h"

/*
 * THE CRASH RECORD (ledger row 392, Fable's brief 3 G2).
 *
 * Twice a run died with 0xC0000005 right after an attempt's compile and Windows
 * kept nothing (rows 341, 348): no dump, no place, no stdout. So the driver
 * installs a top-level filter before the run starts. A fault writes, into the
 * job folder, `crash.txt` - the code, the faulting address as an offset into
 * this executable, the frames of the faulting thread as offsets too, and the
 * last PROGRESS line (which attempt, which family, which stage) - and a
 * minidump `crash_<attempt>.dmp`; then the process ends with the fault's own
 * code, as it did. The offsets are read against the linker map the build
 * writes beside the executable (`tools/mapgen_crash_symbolicate.py`) - never a
 * rebuild with symbols, which changes the code under the addresses.
 */
static char g_crash_dir[MAPCOMPILE_MAX_PATH];
static const bool g_crash_filter = true;       /* the RED's mutation point */
static uint32_t g_crash_at;                    /* test seam: `--crash-at N` */

static void crash_offset(FILE *f, const char *what, DWORD64 address)
{
    const HMODULE self = GetModuleHandleW(NULL);
    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)self;
    const IMAGE_NT_HEADERS *nt = (const IMAGE_NT_HEADERS *)((const char *)self + dos->e_lfanew);
    const DWORD64 base = (DWORD64)(uintptr_t)self;
    if (address >= base && address < base + nt->OptionalHeader.SizeOfImage)
        fprintf(f, "%s pipeline.exe+0x%llx\n", what, (unsigned long long)(address - base));
    else
        fprintf(f, "%s 0x%llx (outside pipeline.exe)\n", what, (unsigned long long)address);
}

static LONG WINAPI crash_filter(EXCEPTION_POINTERS *ep)
{
    char path[MAPCOMPILE_MAX_PATH + 64];
    const uint32_t attempt = MapGenPipeline_AttemptsSoFar();
    snprintf(path, sizeof(path), "%s/crash.txt", g_crash_dir);
    FILE *f = fopen(path, "w");
    if (f) {
        const HMODULE self = GetModuleHandleW(NULL);
        fprintf(f, "crash code 0x%08lx after %u attempts\n",
                (unsigned long)ep->ExceptionRecord->ExceptionCode, (unsigned)attempt);
        fprintf(f, "last %s\n", MapGenPipeline_LastProgress());
        fprintf(f, "base 0x%llx\n", (unsigned long long)(uintptr_t)self);
        crash_offset(f, "at", (DWORD64)(uintptr_t)ep->ExceptionRecord->ExceptionAddress);
        /* the faulting thread's frames, unwound from its own context */
        CONTEXT ctx = *ep->ContextRecord;
        for (int k = 0; k < 32 && ctx.Rip; k++) {
            crash_offset(f, "frame", ctx.Rip);
            DWORD64 image = 0;
            RUNTIME_FUNCTION *fn = RtlLookupFunctionEntry(ctx.Rip, &image, NULL);
            if (!fn) {
                ctx.Rip = *(DWORD64 *)(uintptr_t)ctx.Rsp;   /* a leaf: its return address */
                ctx.Rsp += 8;
                continue;
            }
            void *handler_data = NULL;
            DWORD64 frame = 0;
            RtlVirtualUnwind(UNW_FLAG_NHANDLER, image, ctx.Rip, fn, &ctx, &handler_data, &frame, NULL);
        }
        fclose(f);
    }
    /* dbghelp loaded here, at the crash, so nothing that links this driver
       needs another library */
    typedef BOOL (WINAPI *dump_fn)(HANDLE, DWORD, HANDLE, MINIDUMP_TYPE,
                                   PMINIDUMP_EXCEPTION_INFORMATION,
                                   PMINIDUMP_USER_STREAM_INFORMATION,
                                   PMINIDUMP_CALLBACK_INFORMATION);
    HMODULE dbghelp = LoadLibraryA("dbghelp.dll");
    dump_fn write_dump = dbghelp ? (dump_fn)(void (*)(void))GetProcAddress(dbghelp, "MiniDumpWriteDump") : NULL;
    snprintf(path, sizeof(path), "%s/crash_%u.dmp", g_crash_dir, (unsigned)attempt);
    HANDLE dump = write_dump ? CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL)
                             : INVALID_HANDLE_VALUE;
    if (dump != INVALID_HANDLE_VALUE) {
        MINIDUMP_EXCEPTION_INFORMATION info;
        info.ThreadId = GetCurrentThreadId();
        info.ExceptionPointers = ep;
        info.ClientPointers = FALSE;
        write_dump(GetCurrentProcess(), GetCurrentProcessId(), dump, MiniDumpNormal, &info, NULL, NULL);
        CloseHandle(dump);
    }
    return EXCEPTION_EXECUTE_HANDLER;      /* the process ends with the fault's code */
}

/* The test seam: fault at the Nth candidate the run builds. Only `--crash-at`
   sets it; no product path does. */
static void crash_seam(void *user, uint32_t percent, const char *what)
{
    (void)user;
    (void)percent;
    unsigned n = 0, of = 0;
    if (g_crash_at && sscanf(what, "building a candidate (%u of %u)", &n, &of) == 2 && n == g_crash_at)
        *(volatile int *)(uintptr_t)8 = 1;
}

/* The two lumps a caller has to be able to see from outside: an artifact with
   no lighting is a DRAFT, whatever else is true of it. */
#define LUMP_VISIBILITY 3
#define LUMP_LIGHTING   7

/* One lump's size, straight out of the header. Zero when the file is not
   there or is too short to have one, which reads the same as "empty" and is
   the right answer either way. */
static uint32_t lump_bytes(const char *path, int lump)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return 0;
    uint8_t head[8 + 19 * 8];
    const size_t got = fread(head, 1, sizeof(head), f);
    fclose(f);
    if (got < sizeof(head))
        return 0;
    uint32_t length = 0;
    memcpy(&length, head + 8 + (size_t)lump * 8 + 4, 4);
    return length;
}

/* The bytes on disk, hashed, and how many there are. Not the hash the
   compiler reported: the question is what is in the file NOW. */
static uint64_t artifact_identity(const char *path, char out[MAPGEN_SHA256_HEX])
{
    out[0] = '\0';
    FILE *f = fopen(path, "rb");
    if (!f)
        return 0;
    mapgen_sha256_t ctx;
    MapGenDigest_Sha256Init(&ctx);
    uint8_t buffer[65536];
    size_t got;
    uint64_t bytes = 0;
    while ((got = fread(buffer, 1, sizeof(buffer), f)) > 0) {
        MapGenDigest_Sha256Update(&ctx, buffer, got);
        bytes += got;
    }
    fclose(f);
    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256Final(&ctx, digest);
    MapGenDigest_Sha256Hex(digest, out);
    return bytes;
}

typedef struct {
    const char *compiler;
    /* When set, the compiler is the qualification harness's fake one, run
       through this interpreter with this behaviour. It is still a REAL child
       process: what changes is which program it is. */
    const char *python;
    const char *behavior;
} real_t;

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
 * Launch the pinned compiler and report what it did - nothing more. Whether
 * the attempt succeeded is read off the artifacts afterwards, by the runner,
 * which is the entire point of the split.
 */
static mapcompile_result_t run_stage(void *ctx,
                                     const mapcompile_request_t *request,
                                     mapcompile_stage_t stage,
                                     mapcompile_stage_report_t *out)
{
    const real_t *real = (const real_t *)ctx;

    char command[4096];
    /*
     * Row 410: the BSP stage of the finished map's compile on the pinned one thread, vis and rad on the request's.
     * MEASURED (the Studio guard's resume case, q2dm1, 16 threads): two runs of one .map differed in the planes and
     * the nodes - the bsp stage itself, not only the visibility lump row 404 allowed for; on the PO's machine at the
     * night share, two bsp+vis runs on 4 threads differed, two on bsp 1 + vis 4 did not. The bsp stage is seconds.
     */
    const int threads = stage == MAPCOMPILE_STAGE_BSP ? MAPCOMPILE_PINNED_THREADS : request->threads;
    const int n = real->python
        ? snprintf(command, sizeof(command),
                   "\"\"%s\" \"%s\" --behavior %s %s -threads %d"
                   " -moddir \"%s\" -basedir \"%s\" \"%s/%s.map\"\" 2>&1",
                   real->python, real->compiler, real->behavior,
                   stage_flags(stage), request->threads, request->moddir,
                   request->basedir, request->job_dir, request->map_name)
        : snprintf(command, sizeof(command),
                   "\"\"%s\" %s%s%s -threads %d -moddir \"%s\""
                   " -basedir \"%s\" -gamedir \"%s\" \"%s/%s.map\"\""
                   " 2>&1",
                   real->compiler, stage_flags(stage),
                   stage == MAPCOMPILE_STAGE_RAD && request->rad_flags[0] ? " " : "",
                   stage == MAPCOMPILE_STAGE_RAD ? request->rad_flags : "", threads,
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
    /* row 411: the compiler's bars of tenths, passed on as they come - «BEGIN rad», then «0...1...9... (n)» a pass */
    char line[160];
    size_t at = 0;
    char stage_now[8] = "";
    int pass = 0, prev2 = 0, prev1 = 0;
    while ((c = fgetc(pipe)) != EOF) {
        total++;
        if (kept && held < cap)
            kept[held++] = (char)((c >= 32 || c == '\n') ? c : ' ');
        if (c == '\n') {
            line[at] = 0;
            const char *begin = strstr(line, "BEGIN ");
            if (begin && sscanf(begin + 6, "%7[a-z]", stage_now) == 1)
                pass = 0;
            at = 0;
        } else if (at + 1 < sizeof(line))
            line[at++] = (char)c;
        if (c == '.' && prev1 == '.' && prev2 >= '0' && prev2 <= '9' && stage_now[0])
            MapCompile_Tick(stage_now, pass, prev2 - '0' + 1);
        if (c == '(' && prev1 == ' ' && prev2 == '.' && stage_now[0])
            pass++;                     /* a bar's «(n)»: the pass is over */
        prev2 = prev1;
        prev1 = c;
    }
    if (kept)
        kept[held] = '\0';

    out->exit_code = pclose(pipe);
    out->stdout_total_bytes = total;
    out->stdout_captured = kept;
    out->stdout_captured_bytes = held;
    out->stdout_truncated = total > held;
    return MAPCOMPILE_OK;
}

/* Brief 11: an option that changes the plan, recorded as given - the ledger's head carries them for the gates. */
static void plan_option(mapgen_pipeline_request_t *r, const char *name, const char *value)
{
    const size_t used = strlen(r->plan_options);
    snprintf(r->plan_options + used, sizeof(r->plan_options) - used, "%s%s %s", used ? " " : "", name, value);
}

int main(int argc, char **argv)
{
    /*
     * UNBUFFERED STDOUT, before anything can print a word.
     *
     * MEASURED 2026-09-13 (ledger row 132): a run of this driver was stopped
     * after three hours and nineteen compiles and its redirected stdout held
     * ZERO bytes - every `SAY` and the whole report sat in one buffer waiting
     * for `exit`. So a run that dies takes its own diagnosis with it, which is
     * how two fidelity-20 runs came back as «the run printed nothing» with
     * nothing able to say why (rows 125, 131), and why the ledger had to be
     * written with an `fflush` per line to be worth anything at all.
     *
     * `_IONBF` and not `_IOLBF`: the Windows C runtime documents line buffering
     * as the same thing as full buffering, so the line mode does not exist
     * here. A run prints on the order of a kilobyte plus its progress lines,
     * next to a minute of compiler per attempt - the cost is not measurable.
     */
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 5) {
        fprintf(stderr, "usage: %s <compiler.exe> <donor.bsp> <job dir>"
                        " <map name> [fidelity] [seed] [--diagnostic]"
                        " [--final]\n", argv[0]);
        return 2;
    }

    mapgen_pipeline_request_t request;
    memset(&request, 0, sizeof(request));
    request.generate.fidelity = argc > 5 ? (int32_t)strtol(argv[5], NULL, 10)
                                         : 100;
    request.generate.seed = argc > 6 ? strtoull(argv[6], NULL, 10) : 1;
    request.generate.stair_mask = UINT64_MAX;
    request.profile = MAPCOMPILE_PROFILE_DRAFT;
    request.format = MAPCOMPILE_FORMAT_IBSP;
    /* The pin's qualified thread policy, not a number chosen here - see
       MAPCOMPILE_PINNED_THREADS. A driver that asks for 4 is a configuration
       nobody qualified calling itself the pinned one. */
    request.threads = MAPCOMPILE_PINNED_THREADS;
    request.stage_timeout_ms = 1800000;
    request.max_log_bytes = 262144;
    request.disk_budget_bytes = 512ull * 1024ull * 1024ull;
    request.reach_budget = 40000;

    for (int a = 5; a < argc; a++) {
        if (!strcmp(argv[a], "--diagnostic"))
            request.diagnostic_no_band = true;
        /* Fidelity zero: what was learned, and what the target can resolve. */
        else if (!strcmp(argv[a], "--donor") && a + 1 < argc) {
            /* Another donor a room may be brought in from - GF7. Repeatable,
               because a run may be offered several and the report says which
               of them actually gave one. */
            if (request.num_other_donors < MAPGEN_PIPELINE_MAX_DONORS)
                snprintf(request.other_donors[request.num_other_donors++],
                         MAPCOMPILE_MAX_PATH, "%s", argv[++a]);
            else
                a++;
        }
        else if (!strcmp(argv[a], "--snapshot") && a + 1 < argc)
            snprintf(request.snapshot, sizeof(request.snapshot), "%s",
                     argv[++a]);
        else if (!strcmp(argv[a], "--manifest") && a + 1 < argc)
            snprintf(request.manifest, sizeof(request.manifest), "%s",
                     argv[++a]);
        else if (!strcmp(argv[a], "--scale") && a + 1 < argc)
            request.scale = (int32_t)strtol(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--goal") && a + 1 < argc)
            request.goal = (int32_t)strtol(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--final"))
            request.profile = MAPCOMPILE_PROFILE_FINAL;
        else if (!strcmp(argv[a], "--fake") && a + 2 < argc)
            a += 2;                 /* read above, into the adapter */
        else if (!strcmp(argv[a], "--max-attempts") && a + 1 < argc)
            request.max_attempts = (uint32_t)strtoul(argv[a + 1], NULL, 10);
        /* row 392: the crash record's test seam - fault at the Nth candidate */
        else if (!strcmp(argv[a], "--crash-at") && a + 1 < argc)
            g_crash_at = (uint32_t)strtoul(argv[++a], NULL, 10);
        /* row 395: resume the run this job folder holds, from its ledger */
        /* row 400: the finished map held to its donor's own walk */
        else if (!strcmp(argv[a], "--hold-to-donor"))
            request.hold_to_donor = true;
        /* row 405: the donor's light calibration, for the finished map's light pass */
        else if (!strcmp(argv[a], "--light-flags") && a + 1 < argc)
            snprintf(request.light_flags, sizeof(request.light_flags), "%s", argv[++a]);
        /* row 410: the donor's sun keys for the light pass */
        else if (!strcmp(argv[a], "--light-keys") && a + 1 < argc)
            snprintf(request.light_keys, sizeof(request.light_keys), "%s", argv[++a]);
        else if (!strcmp(argv[a], "--resume"))
            request.resume = true;
        /* row 411: the most memory the run's working files may take, in MB (the Studio's share of what is free) */
        else if (!strcmp(argv[a], "--memory") && a + 1 < argc)
            request.memory_bytes = strtoull(argv[++a], NULL, 10) << 20;
        /* row 411: 0 - with the run in memory, its accepted tries are not written to the disk (no resume) */
        else if (!strcmp(argv[a], "--checkpoints") && a + 1 < argc)
            request.no_checkpoints = strtol(argv[++a], NULL, 10) == 0;
        /* row 410: the donors guard's replays of jobs older than row 408 - the point lights may differ */
        else if (!strcmp(argv[a], "--replay-any-lights")) {
            MapGenTransaction_SetReplayAnyLights(true);
            fprintf(stderr, "replay: a .map that differs from the one built in its point lights alone is the same\n");
        }
        /*
         * Row 410 (the PO 05.10: «какие еще параметры добавить в генератор ... чтобы получать больше вариаций
         * творчества»): the plan's own counts and sizes, until now only the guards' - how many new passages, annex
         * rooms (and how big), two-storey rooms, bridges over an arena, halls on a long passage. 0 or absent: the
         * likeness decides, as before. Same seed, same counts: the same map.
         */
        else if (!strcmp(argv[a], "--digs") && a + 1 < argc)
            MapGenGeometryEdit_WantDigs((uint32_t)strtoul(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--annexes") && a + 4 < argc) {
            const uint32_t n = (uint32_t)strtoul(argv[a + 1], NULL, 10);
            MapGenGeometryEdit_DigAnnexes(n, strtof(argv[a + 2], NULL), strtof(argv[a + 3], NULL),
                                          strtof(argv[a + 4], NULL));
            a += 4;
        }
        else if (!strcmp(argv[a], "--storeys") && a + 1 < argc)
            MapGenGeometryEdit_DigStoreys((uint32_t)strtoul(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--spans") && a + 1 < argc)
            MapGenGeometryEdit_DigSpans((uint32_t)strtoul(argv[++a], NULL, 10));
        /* brief 11 D1: stairways up the rooms' walls, 0..10 */
        else if (!strcmp(argv[a], "--stairways") && a + 1 < argc) {
            plan_option(&request, argv[a], argv[a + 1]);
            MapGenGeometryEdit_DigStairways((uint32_t)strtoul(argv[++a], NULL, 10));
        }
        /* row 410: the map's own pools made another liquid - look and harm («water-lava», «mix» ...) */
        else if (!strcmp(argv[a], "--liquids") && a + 1 < argc)
            MapGenGeometryEdit_SetLiquids(argv[++a]);
        /* row 412: how much new water, slime and lava the floods lay, percent of the rooms they may take */
        else if (!strcmp(argv[a], "--new-water") && a + 1 < argc) {
            plan_option(&request, argv[a], argv[a + 1]);
            MapGenGeometryEdit_SetNewLiquid(0u, (int32_t)strtol(argv[++a], NULL, 10));
        } else if (!strcmp(argv[a], "--new-slime") && a + 1 < argc) {
            plan_option(&request, argv[a], argv[a + 1]);
            MapGenGeometryEdit_SetNewLiquid(1u, (int32_t)strtol(argv[++a], NULL, 10));
        } else if (!strcmp(argv[a], "--new-lava") && a + 1 < argc) {
            plan_option(&request, argv[a], argv[a + 1]);
            MapGenGeometryEdit_SetNewLiquid(2u, (int32_t)strtol(argv[++a], NULL, 10));
        }
        /* row 412: how many of the base's wall pieces the digs hang, percent of the rule's */
        else if (!strcmp(argv[a], "--decor") && a + 1 < argc)
            MapGenGeometryEdit_SetWallDecor((uint32_t)strtoul(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--halls") && a + 1 < argc)
            MapGenGeometryEdit_DigHalls((uint32_t)strtoul(argv[++a], NULL, 10), 0.0f, 0.0f);
        /* row 394: a family the run must not try, by its name; repeatable */
        else if (!strcmp(argv[a], "--skip-family") && a + 1 < argc) {
            /* row 410: refused aloud past the room there is - 16 cut a longer list short in silence */
            if (request.num_excluded_families
                >= sizeof(request.excluded_families) / sizeof(request.excluded_families[0])) {
                fprintf(stderr, "too many --skip-family (%u at most)\n",
                        (unsigned)(sizeof(request.excluded_families) / sizeof(request.excluded_families[0])));
                return 2;
            }
            snprintf(request.excluded_families[request.num_excluded_families++],
                     sizeof(request.excluded_families[0]), "%s", argv[a + 1]);
            a++;
        }
        else if (!strcmp(argv[a], "--moddir") && a + 1 < argc) {
            snprintf(request.moddir, sizeof(request.moddir), "%s", argv[a + 1]);
            snprintf(request.basedir, sizeof(request.basedir), "%s", argv[a + 1]);
            a++;
        }
    }

    real_t real;
    memset(&real, 0, sizeof(real));
    real.compiler = argv[1];
    for (int a = 5; a < argc; a++) {
        if (!strcmp(argv[a], "--fake") && a + 2 < argc) {
            real.python = argv[a + 1];
            real.behavior = argv[a + 2];
            a += 2;
        }
    }
    const mapcompile_adapter_t adapter = { "q2tool", (void *)&real, run_stage,
                                           NULL };

    mapgen_pipeline_report_t report;
    /* row 392: the crash record goes into the job folder */
    snprintf(g_crash_dir, sizeof(g_crash_dir), "%s", argv[3]);
    /* row 395: a resumed run keeps the crash record it resumes from, under another name */
    if (request.resume) {
        char was[MAPCOMPILE_MAX_PATH + 32], kept[MAPCOMPILE_MAX_PATH + 32];
        snprintf(was, sizeof(was), "%s/crash.txt", argv[3]);
        snprintf(kept, sizeof(kept), "%s/crash_resumed_from.txt", argv[3]);
        remove(kept);
        rename(was, kept);
    }
    /* and no system crash window on the user's screen, ever - the record is
       the file; inherited by the compiler it spawns */
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (g_crash_filter)
        SetUnhandledExceptionFilter(crash_filter);
    /* D28 (assignment 24): the run's wall clock and this process's CPU */
    const clock_t run_began = clock();
    const uint64_t run_cpu_began = Q2PROX_Cpu_ProcessMs();
    const mapgen_pipeline_result_t rc =
        MapGenPipeline_Run(argv[2], argv[3], argv[4], &adapter, &request,
                           &report, g_crash_at ? crash_seam : NULL, NULL);

    printf("%s\n", MapGenPipeline_ResultName(rc));
    printf("  clock      %.0f s wall, %.0f s cpu in this process (the compiler"
           " is another); %d logical CPUs in the affinity mask, the walk"
           " takes %d workers\n",
           (double)(clock() - run_began) / CLOCKS_PER_SEC,
           (double)(Q2PROX_Cpu_ProcessMs() - run_cpu_began) / 1000.0,
           Q2PROX_Cpu_AffinityCount(), Q2PROX_Cpu_PerformanceCount());
    printf("  spent      %u attempted, %u accepted, %u permille reached,"
           " %u missing\n", report.attempted, report.accepted,
           report.reached_permille, report.missing_permille);
    /* What each donor offered gave, which is what a contribution floor is
       checked against - and a donor that gave nothing is named. */
    if (report.donors_offered) {
        printf("  donors     %u offered, %u contributed, %u grafts kept\n",
               report.donors_offered, report.donors_contributed,
               report.grafts_accepted);
        for (uint32_t d = 0; d < report.donors_offered
                             && d < MAPGEN_PIPELINE_MAX_DONORS; d++)
            printf("  donor      %s %s\n", report.donor_name[d],
                   report.donor_used[d] ? "contributed" : "gave nothing");
    }
    printf("  ledger    ");
    /* Every verdict there is, from the enum rather than from a number written
       here: a loop that stopped at seven hid REJECTED_SURFACE and
       REJECTED_UNMEASURED, and a run of 121 attempts printed a ledger that
       added up to 97. */
    for (unsigned v = 0; v < MAPGEN_TXN_NUM_VERDICTS; v++)
        if (report.by_verdict[v])
            printf(" %s=%u",
                   MapGenTransaction_VerdictName(
                       (mapgen_transaction_verdict_t)v),
                   report.by_verdict[v]);
    printf("\n");
    printf("  generated  %s  %u brushes -> %u, %u of %u edits spent\n",
           report.wrote_candidate ? "yes" : "no",
           report.generated.donor_brushes, report.generated.candidate_brushes,
           report.generated.edits_spent, report.generated.edits_offered);
    if (report.compiled_a_map)
        printf("  compiled   %s  %llu bytes, sha256 %.16s\n",
               MapCompile_ResultName(report.compiled.result),
               (unsigned long long)report.compiled.bsp_bytes,
               report.compiled.bsp_sha256);
    else
        printf("  compiled   %s\n",
               MapCompile_ResultName(report.compiled.result));
    /*
     * WHICH FILE all of that is about.
     *
     * A caller that had to work it out from the job directory got it wrong:
     * the anchor sweep took the last attempt by name order, which for two of
     * six anchors was a REJECTED attempt's draft - no lighting - while the
     * accepted, lit artifact sat in the next directory along. Two of the maps
     * handed to the PO on 2026-09-07 were that draft.
     *
     * So the run says the path, the hash of the bytes on disk, and how much
     * lighting is in them. Nothing downstream has to infer any of it.
     */
    if (report.bsp_path[0]) {
        char sha[MAPGEN_SHA256_HEX];
        const uint64_t bytes = artifact_identity(report.bsp_path, sha);
        printf("  artifact   %s\n", report.bsp_path);
        printf("             %llu bytes, sha256 %.16s, lighting %u bytes,"
               " vis %u bytes\n", (unsigned long long)bytes, sha,
               lump_bytes(report.bsp_path, LUMP_LIGHTING),
               lump_bytes(report.bsp_path, LUMP_VISIBILITY));
    }
    /* What every number below was measured against: the donor through this
       compiler with nothing applied, not the file the donor arrived in. */
    printf("  baseline   sha256 %.16s\n", report.baseline_bsp);
    if (report.synthesised)
        printf("  invented   attempt %u, %u rooms, %u passages, %u brushes,"
               " %u entities (%u spawns)\n",
               report.synthesis.attempt, report.synthesis.rooms,
               report.synthesis.passages, report.synthesis.brushes,
               report.synthesis.entities, report.synthesis.spawns);
    if (report.measured_reach)
        printf("  playable   %u places, %u spawns, component %u,"
               " %u one-way (%u lethal), %u of %u pickups out of reach\n",
               report.reach.states, report.reach.spawns, report.reach.component,
               report.reach.trapped, report.reach.trapped_lethal,
               report.reach.items_unreachable, report.reach.items);
    if (report.measured_divergence) {
        /*
         * Row 397 (Fable's brief 3 G4): asked and reached, and what ended the
         * edits when the run fell short - the compiles allowed, or every round
         * the schedule dealt - rather than «OUT OF BAND» on a map then shipped.
         */
        const bool short_of = report.divergence.aggregate_permille < report.divergence.target_permille;
        char why[160] = "";
        if (!report.divergence.within_band && short_of)
            snprintf(why, sizeof(why), "short of the target: %s",
                     !strcmp(report.ended_by, "budget") ? "the edits ended at the compiles allowed"
                     : "the edits ended with every round the schedule dealt");
        printf("  divergence %u permille, target %u, %s\n",
               report.divergence.aggregate_permille,
               report.divergence.target_permille,
               report.divergence.within_band ? "in band"
               : short_of ? why : "OVER THE TARGET");
        printf("  edits      ended by the %s: %u compiles of %u, %u round(s)\n",
               report.ended_by[0] ? report.ended_by : "-", report.compiles, report.budget, report.rounds);
        /* Which instrument said so. A permille from a repaired metric is not
           comparable to one from the metric before the repair, and this run's
           number will be read next to numbers measured last week. */
        printf("  metric     schema %u (%s)%s\n",
               report.divergence.schema, MAPGEN_DIVERGENCE_SCHEMA_ID,
               report.divergence.complete ? "" : ", INCOMPLETE");
        /* D19 (assignment 23): where the oracle's route axis came from */
        printf("  oracle     routes %s\n",
               report.oracle_from_walks ? "from the run's own walks"
                                        : "walked again");
    }

    for (int i = 0; i < report.compiled.num_stages; i++)
        free(report.compiled.stages[i].stdout_captured);
    /* row 397: a playable map short of its target is what this donor gave within the budget - a success that says
       so above, not a failure; every other refusal still exits 1 */
    return rc == MAPGEN_PIPELINE_OK || (rc == MAPGEN_PIPELINE_ERR_TARGET_UNREACHABLE && report.compiled_a_map)
           ? 0 : 1;
}
