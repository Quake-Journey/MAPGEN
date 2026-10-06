/*
 * MapCompile_RunProfile - see src/mapgen/mapgen_compiler.h.
 *
 * The contract's own words are the design: `run_stage` reports what the process
 * DID, and this decides whether the attempt succeeded by reading artifacts. So
 * there is no path through this file where a zero exit code alone produces
 * MAPCOMPILE_OK. The compiler exits zero when it leaks, when a texture is
 * missing, and when it writes nothing at all; every one of those has its own
 * result code here and every one of them is reached by looking at what is on
 * disk afterwards rather than at what the child said.
 *
 * Launching belongs to the Adapter and not here. That is not tidiness: an
 * in-process seam has no concept of an exit code, a hung child or a flooded
 * pipe, so the qualification harness substitutes a REAL process that produces
 * each failure mode, and this file has to be the same code in both cases.
 */

#include "common/mapgen_fs.h"
#include "mapgen_compiler.h"

#include "common/mapgen_bsp.h"
#include "common/mapgen_digest.h"

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

const char *MapCompile_ResultName(mapcompile_result_t result)
{
    switch (result) {
    case MAPCOMPILE_OK:                     return "OK";
    case MAPCOMPILE_ERR_INVALID_REQUEST:    return "ERR_INVALID_REQUEST";
    case MAPCOMPILE_ERR_DIRTY_JOB_DIR:      return "ERR_DIRTY_JOB_DIR";
    case MAPCOMPILE_ERR_LAUNCH:             return "ERR_LAUNCH";
    case MAPCOMPILE_ERR_TIMEOUT:            return "ERR_TIMEOUT";
    case MAPCOMPILE_ERR_CRASH:              return "ERR_CRASH";
    case MAPCOMPILE_ERR_NONZERO_EXIT:       return "ERR_NONZERO_EXIT";
    case MAPCOMPILE_ERR_LEAKED:             return "ERR_LEAKED";
    case MAPCOMPILE_ERR_MISSING_ASSET:      return "ERR_MISSING_ASSET";
    case MAPCOMPILE_ERR_NO_OUTPUT:          return "ERR_NO_OUTPUT";
    case MAPCOMPILE_ERR_STALE_OUTPUT:       return "ERR_STALE_OUTPUT";
    case MAPCOMPILE_ERR_OUTPUT_UNREADABLE:  return "ERR_OUTPUT_UNREADABLE";
    case MAPCOMPILE_ERR_WRONG_FORMAT:       return "ERR_WRONG_FORMAT";
    case MAPCOMPILE_ERR_SEMANTICS:          return "ERR_SEMANTICS";
    case MAPCOMPILE_ERR_ESCAPED_JOB_ROOT:   return "ERR_ESCAPED_JOB_ROOT";
    case MAPCOMPILE_ERR_DISK_BUDGET:        return "ERR_DISK_BUDGET";
    case MAPCOMPILE_ERR_LOG_BUDGET:         return "ERR_LOG_BUDGET";
    case MAPCOMPILE_ERR_CANCELLED:          return "ERR_CANCELLED";
    case MAPCOMPILE_ERR_IDENTITY:           return "ERR_IDENTITY";
    case MAPCOMPILE_RESULT_COUNT:           break;
    }
    return "ERR_UNKNOWN";
}

/* ---- the stages a profile runs ----------------------------------------------- */

static int stages_of(mapcompile_profile_t profile, mapcompile_stage_t *out)
{
    switch (profile) {
    case MAPCOMPILE_PROFILE_DRAFT:
        out[0] = MAPCOMPILE_STAGE_BSP;
        out[1] = MAPCOMPILE_STAGE_VIS_FAST;
        return 2;
    case MAPCOMPILE_PROFILE_FINAL:
        out[0] = MAPCOMPILE_STAGE_BSP;
        out[1] = MAPCOMPILE_STAGE_VIS;
        out[2] = MAPCOMPILE_STAGE_RAD;
        return 3;
    case MAPCOMPILE_PROFILE_COUNT:
        break;
    }
    return 0;
}

/* ---- small file helpers ------------------------------------------------------ */

static bool path_join(char *out, size_t size, const char *dir,
                      const char *name, const char *suffix)
{
    const int n = snprintf(out, size, "%s/%s%s", dir, name, suffix);
    return n > 0 && (size_t)n < size;
}

static mapcompile_tick_fn g_tick;

void MapCompile_SetTick(mapcompile_tick_fn tick)
{
    g_tick = tick;
}

void MapCompile_Tick(const char *stage, int pass, int tenths)
{
    if (g_tick)
        g_tick(stage, pass, tenths);
}

static bool file_stat(const char *path, struct stat *st)
{
    if (MapGenFs_IsMem(path)) {     /* row 411: a section of the caller's - present, and its size */
        uint64_t size = 0;
        if (!MapGenFs_Exists(path, &size))
            return false;
        memset(st, 0, sizeof(*st));
        st->st_mode = S_IFREG;
        st->st_size = (off_t)size;
        st->st_mtime = time(NULL);
        return true;
    }
    return stat(path, st) == 0;
}

/* Row 411: what a compile's sections hold - the files a folder of it would. */
static uint64_t memory_dir_bytes(const char *dir, const char *name)
{
    static const char *const exts[] = { ".map", ".bsp", ".prt", ".pts", ".replay.map" };
    uint64_t total = 0;
    for (size_t i = 0; i < sizeof(exts) / sizeof(exts[0]); i++) {
        char path[MAPCOMPILE_MAX_PATH];
        uint64_t size = 0;
        if (snprintf(path, sizeof(path), "%s/%s%s", dir, name, exts[i]) < (int)sizeof(path)
            && MapGenFs_Exists(path, &size))
            total += size;
    }
    return total;
}

/*
 * Everything under the job directory, counted.
 *
 * One level deep, because the compiler writes beside its input and does not
 * make subdirectories; a directory that turns up here is counted as present
 * and not descended, which keeps a hostile tree from turning a size check into
 * an unbounded walk.
 */
static uint64_t directory_bytes(const char *dir)
{
    DIR *d = opendir(dir);
    if (!d)
        return 0;
    uint64_t total = 0;
    const struct dirent *entry;
    while ((entry = readdir(d)) != NULL) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
            continue;
        char path[MAPCOMPILE_MAX_PATH * 2];
        if (snprintf(path, sizeof(path), "%s/%s", dir, entry->d_name)
            >= (int)sizeof(path))
            continue;
        struct stat st;
        if (file_stat(path, &st) && S_ISREG(st.st_mode))
            total += (uint64_t)st.st_size;
    }
    closedir(d);
    return total;
}

/*
 * The names in a directory, joined into one string, in the order the system
 * hands them over.
 *
 * Used to answer one question and no other: did anything appear beside the job
 * directory while the compile was running. Real containment is the process
 * Adapter's - job objects and restricted tokens - and this cannot replace it;
 * what it can do is notice, which is worth having because a compiler that
 * writes outside its job root has already broken the lineage whether or not it
 * was stopped.
 */
static char *directory_listing(const char *dir)
{
    DIR *d = opendir(dir);
    if (!d)
        return NULL;
    size_t held = 0, cap = 1024;
    char *names = malloc(cap);
    if (names)
        names[0] = '\0';
    const struct dirent *entry;
    while (names && (entry = readdir(d)) != NULL) {
        const size_t n = strlen(entry->d_name);
        if (held + n + 2 > cap) {
            cap = (held + n + 2) * 2;
            char *grown = realloc(names, cap);
            if (!grown)
                break;
            names = grown;
        }
        memcpy(names + held, entry->d_name, n);
        held += n;
        names[held++] = '\n';
        names[held] = '\0';
    }
    closedir(d);
    return names;
}

/* The directory one level up from `dir`, or NULL when there is none. */
static bool parent_of(const char *dir, char *out, size_t size)
{
    const size_t n = strlen(dir);
    if (!n || n >= size)
        return false;
    memcpy(out, dir, n + 1);
    /* Trailing separators first, then the last component. */
    size_t at = n;
    while (at && (out[at - 1] == '/' || out[at - 1] == '\\'))
        at--;
    while (at && out[at - 1] != '/' && out[at - 1] != '\\')
        at--;
    if (!at)
        return false;
    out[at - 1] = '\0';
    return out[0] != '\0';
}

/* Case-insensitive substring, because compiler output is not a stable case. */
static bool says(const char *haystack, const char *needle)
{
    if (!haystack || !needle)
        return false;
    const size_t n = strlen(needle);
    for (const char *at = haystack; *at; at++) {
        size_t i = 0;
        while (i < n) {
            char a = at[i], b = needle[i];
            if (a >= 'A' && a <= 'Z') a = (char)(a - 'A' + 'a');
            if (b >= 'A' && b <= 'Z') b = (char)(b - 'A' + 'a');
            if (a != b)
                break;
            i++;
        }
        if (i == n)
            return true;
    }
    return false;
}

static void hex_of(const uint8_t digest[MAPGEN_SHA256_BYTES], char *out)
{
    MapGenDigest_Sha256Hex(digest, out);
}

/* ---- the runner --------------------------------------------------------------- */

static bool request_is_runnable(const mapcompile_request_t *r)
{
    if (!r->job_dir[0] || !r->map_name[0] || !r->moddir[0] || !r->basedir[0])
        return false;
    if (r->profile >= MAPCOMPILE_PROFILE_COUNT)
        return false;
    if (r->threads <= 0)
        return false;
    if (!r->stage_timeout_ms || !r->max_log_bytes || !r->disk_budget_bytes)
        return false;
    /* A map name is a name, not a path: anything that could climb out of the
       job directory is refused before a child ever sees it. */
    if (strchr(r->map_name, '/') || strchr(r->map_name, '\\')
        || strstr(r->map_name, ".."))
        return false;
    return true;
}

static mapcompile_result_t judge_artifacts(const mapcompile_request_t *request,
                                           mapcompile_report_t *report,
                                           time_t started)
{
    if (!path_join(report->bsp_path, sizeof(report->bsp_path),
                   request->job_dir, request->map_name, ".bsp"))
        return MAPCOMPILE_ERR_INVALID_REQUEST;

    struct stat st;
    if (!file_stat(report->bsp_path, &st))
        return MAPCOMPILE_ERR_NO_OUTPUT;
    /*
     * Row 411: a section has no time of its own - but it was found empty before the compile (the dirty check), so
     * what is in it now is this attempt's; the time a file carries is what proves that for a folder.
     */
    if (MapGenFs_IsMem(report->bsp_path))
        st.st_mtime = started;
    /*
     * Older than the attempt is not this attempt's output. A job directory is
     * created empty for every attempt, so this can only happen if something
     * else put it there - and reporting somebody else's map as a success is
     * the worst failure this whole file exists to prevent.
     */
    if (st.st_mtime < started)
        return MAPCOMPILE_ERR_STALE_OUTPUT;
    report->bsp_bytes = (uint64_t)st.st_size;

    uint8_t *raw = NULL;        /* row 411: a file or a section */
    size_t got = 0;
    if (!MapGenFs_Read(report->bsp_path, &raw, &got) || !got
        || got != (size_t)report->bsp_bytes) {
        free(raw);
        return MAPCOMPILE_ERR_OUTPUT_UNREADABLE;
    }

    uint8_t sha[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(raw, (size_t)report->bsp_bytes, sha);
    hex_of(sha, report->bsp_sha256);

    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t br = MapGenBsp_Load(raw, (size_t)report->bsp_bytes,
                                                  &bsp);
    free(raw);
    report->reread_performed = true;
    if (br == MAPGEN_BSP_ERR_BAD_IDENT || br == MAPGEN_BSP_ERR_BAD_VERSION)
        return MAPCOMPILE_ERR_WRONG_FORMAT;
    if (br != MAPGEN_BSP_OK)
        return MAPCOMPILE_ERR_OUTPUT_UNREADABLE;

    /*
     * The format that was asked for is the format that must come back.
     *
     * A compiler that ignores the switch and writes the other one produces a
     * perfectly readable map that the target engine may refuse to load, and the
     * only moment anyone can notice is now, with the file in hand.
     */
    {
        const bool extended = MapGenBsp_IsExtended(bsp);
        const bool wanted = request->format == MAPCOMPILE_FORMAT_QBSP;
        if (extended != wanted) {
            MapGenBsp_Free(bsp);
            report->reread_performed = true;
            return MAPCOMPILE_ERR_WRONG_FORMAT;
        }
    }

    /*
     * A map that parses and means nothing is still a failure. The compiler
     * writes a structurally valid BSP for a map with no solid in it, and a
     * caller that trusted the parse would publish an empty room.
     */
    uint32_t entity_length = 0;
    const char *entities = MapGenBsp_Entities(bsp, &entity_length);
    const bool sane = MapGenBsp_NumModels(bsp) > 0
                   && MapGenBsp_NumBrushes(bsp) > 0
                   && MapGenBsp_NumFaces(bsp) > 0
                   && MapGenBsp_NumPlanes(bsp) > 0
                   && entities && entity_length
                   && strstr(entities, "worldspawn") != NULL
                   /*
                    * And somewhere for a player to be. A map with no start
                    * parses, loads and cannot be played; the compiler exits
                    * zero for it, so nothing but this notices.
                    */
                   && (strstr(entities, "info_player_deathmatch") != NULL
                       || strstr(entities, "info_player_start") != NULL);

    if (sane) {
        /*
         * The digest of MEANING: the canonical text carries geometry, brushes,
         * materials and entities, and carries no lightmap bytes, no vis bytes,
         * no padding and no lump offsets - so two compiles of one candidate
         * agree on it even when their files differ.
         */
        const uint32_t needed = (uint32_t)MapGenBsp_CanonicalText(bsp, NULL, 0);
        char *text = malloc((size_t)needed + 1);
        if (text) {
            MapGenBsp_CanonicalText(bsp, text, needed + 1);
            uint8_t semantic[MAPGEN_SHA256_BYTES];
            MapGenDigest_Sha256(text, strlen(text), semantic);
            hex_of(semantic, report->semantic_digest);
            free(text);
        }
    }
    MapGenBsp_Free(bsp);
    report->semantics_checked = true;
    return sane ? MAPCOMPILE_OK : MAPCOMPILE_ERR_SEMANTICS;
}

mapcompile_result_t MapCompile_RunProfile(const mapcompile_adapter_t *adapter,
                                          const mapcompile_request_t *request,
                                          mapcompile_report_t *report)
{
    if (!report)
        return MAPCOMPILE_ERR_INVALID_REQUEST;
    memset(report, 0, sizeof(*report));
    if (!adapter || !adapter->run_stage || !request
        || !request_is_runnable(request)) {
        report->result = MAPCOMPILE_ERR_INVALID_REQUEST;
        return report->result;
    }

    /*
     * The directory must have been created empty for THIS attempt. A repaired
     * candidate invalidates the whole compiled lineage and starts a fresh one,
     * so an output already sitting here is not a result to be reported - it is
     * a caller that reused a directory.
     */
    char probe[MAPCOMPILE_MAX_PATH];
    if (!path_join(probe, sizeof(probe), request->job_dir, request->map_name,
                   ".bsp")) {
        report->result = MAPCOMPILE_ERR_INVALID_REQUEST;
        return report->result;
    }
    struct stat st;
    if (file_stat(probe, &st)) {
        report->result = MAPCOMPILE_ERR_DIRTY_JOB_DIR;
        return report->result;
    }

    const time_t started = time(NULL);

    char parent[MAPCOMPILE_MAX_PATH];
    /* row 411: a job in memory has no folder beside which anything could appear - its writes are its sections */
    char *before = !MapGenFs_IsMem(request->job_dir)
                   && parent_of(request->job_dir, parent, sizeof(parent))
                 ? directory_listing(parent) : NULL;

    mapcompile_stage_t order[MAPCOMPILE_STAGE_COUNT];
    const int count = stages_of(request->profile, order);

    mapcompile_result_t verdict = MAPCOMPILE_OK;
    bool leaked = false, missing_asset = false;

    for (int i = 0; i < count; i++) {
        mapcompile_stage_report_t *stage = &report->stages[report->num_stages++];
        memset(stage, 0, sizeof(*stage));
        stage->stage = order[i];

        const mapcompile_result_t rc =
            adapter->run_stage(adapter->ctx, request, order[i], stage);

        if (rc != MAPCOMPILE_OK) {
            verdict = rc;
            break;
        }
        /*
         * Row 411: what went through pipes - what the compiler printed (in files as in memory), and in memory its
         * portal file written by the bsp stage and fed to vis, and its point file: Windows counts each as written.
         */
        MapGenFs_NotePipe(stage->stdout_total_bytes);
        if (MapGenFs_IsMem(request->job_dir)) {
            char part[MAPCOMPILE_MAX_PATH];
            uint64_t size = 0;
            if (path_join(part, sizeof(part), request->job_dir, request->map_name, ".prt")
                && MapGenFs_Exists(part, &size)
                && (order[i] == MAPCOMPILE_STAGE_BSP || order[i] == MAPCOMPILE_STAGE_VIS
                    || order[i] == MAPCOMPILE_STAGE_VIS_FAST))
                MapGenFs_NotePipe(size);
            if (order[i] == MAPCOMPILE_STAGE_BSP
                && path_join(part, sizeof(part), request->job_dir, request->map_name, ".pts")
                && MapGenFs_Exists(part, &size))
                MapGenFs_NotePipe(size);
        }
        if (stage->timed_out) {
            verdict = MAPCOMPILE_ERR_TIMEOUT;
            break;
        }
        if (stage->crashed) {
            verdict = MAPCOMPILE_ERR_CRASH;
            break;
        }
        if (stage->exit_code != 0) {
            verdict = MAPCOMPILE_ERR_NONZERO_EXIT;
            break;
        }
        if (stage->stdout_captured_bytes > request->max_log_bytes) {
            verdict = MAPCOMPILE_ERR_LOG_BUDGET;
            break;
        }
        /*
         * Read while it is here, judged after every stage has run. The
         * compiler says "leaked" and exits ZERO, which is the whole reason
         * this file reads artifacts instead of exit codes.
         */
        if (says(stage->stdout_captured, "leaked"))
            leaked = true;
        /*
         * The compiler's own wording, taken from the pinned tool rather than
         * guessed: it says "WARNING: couldn't locate texture" and exits zero.
         * A map that compiled without its materials is not a map, and nothing
         * but the log says so.
         */
        if (says(stage->stdout_captured, "couldn't locate")
            || says(stage->stdout_captured, "could not locate")
            || says(stage->stdout_captured, "could not find")
            || says(stage->stdout_captured, "couldn't find"))
            missing_asset = true;
    }

    report->job_dir_bytes = MapGenFs_IsMem(request->job_dir)
                          ? memory_dir_bytes(request->job_dir, request->map_name)
                          : directory_bytes(request->job_dir);

    if (before) {
        char *after = directory_listing(parent);
        if (after && strcmp(before, after))
            report->escaped_job_root = true;
        free(after);
        free(before);
    }

    /*
     * And the point file, which is the leak said in the other language.
     *
     * The compiler announces a leak in its log AND drops a .pts beside the
     * map, and it does not always do both: a quiet build with a point file
     * next to it is a leaked map whose log said nothing. Reading only the log
     * accepted exactly that case.
     */
    char points[MAPCOMPILE_MAX_PATH];
    struct stat leak_st;
    if (path_join(points, sizeof(points), request->job_dir, request->map_name,
                  ".pts") && file_stat(points, &leak_st))
        leaked = true;
    if (path_join(points, sizeof(points), request->job_dir, request->map_name,
                  ".lin") && file_stat(points, &leak_st))
        leaked = true;

    if (verdict == MAPCOMPILE_OK && report->escaped_job_root)
        verdict = MAPCOMPILE_ERR_ESCAPED_JOB_ROOT;
    if (verdict == MAPCOMPILE_OK && leaked)
        verdict = MAPCOMPILE_ERR_LEAKED;
    if (verdict == MAPCOMPILE_OK && missing_asset)
        verdict = MAPCOMPILE_ERR_MISSING_ASSET;
    if (verdict == MAPCOMPILE_OK
        && report->job_dir_bytes > request->disk_budget_bytes)
        verdict = MAPCOMPILE_ERR_DISK_BUDGET;

    if (verdict == MAPCOMPILE_OK)
        verdict = judge_artifacts(request, report, started);

    /*
     * The post-condition, asserted here rather than trusted to a caller: OK is
     * not a thing this can return without having reread the output and looked
     * at what it means.
     */
    if (verdict == MAPCOMPILE_OK
        && !(report->reread_performed && report->semantics_checked))
        verdict = MAPCOMPILE_ERR_NO_OUTPUT;

    report->result = verdict;
    return verdict;
}
