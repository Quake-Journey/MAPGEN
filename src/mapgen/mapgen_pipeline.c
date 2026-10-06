/*
 * MapGenPipeline - see inc/common/mapgen_pipeline.h.
 *
 * Composition, and one verdict. Every step here already existed and every one
 * of them already knows how to refuse; what this adds is the decision that a
 * candidate which passed some of them has not passed.
 */

#include "common/mapgen_fs.h"
#include "common/mapgen_pipeline.h"

#include "common/mapgen_transaction.h"

#include "common/mapgen_bsp.h"
#include "common/mapgen_digest.h"
#include "common/q2prox_cpu_topology.h"

#ifdef _WIN32
#include <direct.h>
#include <process.h>
#include <io.h>
#else
#include <sys/stat.h>
#endif
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

const char *MapGenPipeline_ResultName(mapgen_pipeline_result_t r)
{
    switch (r) {
    case MAPGEN_PIPELINE_DIAGNOSTIC:            return "DIAGNOSTIC";
    case MAPGEN_PIPELINE_OK:                    return "OK";
    case MAPGEN_PIPELINE_ERR_ARGS:              return "ERR_ARGS";
    case MAPGEN_PIPELINE_ERR_BASELINE:          return "ERR_BASELINE";
    case MAPGEN_PIPELINE_CANCELLED:             return "CANCELLED";
    case MAPGEN_PIPELINE_ERR_CANDIDATE:         return "ERR_CANDIDATE";
    case MAPGEN_PIPELINE_ERR_SYNTHESIS:         return "ERR_SYNTHESIS";
    case MAPGEN_PIPELINE_ERR_GENERATE:          return "ERR_GENERATE";
    case MAPGEN_PIPELINE_ERR_COMPILE:           return "ERR_COMPILE";
    case MAPGEN_PIPELINE_ERR_UNPLAYABLE:        return "ERR_UNPLAYABLE";
    case MAPGEN_PIPELINE_ERR_TOO_LIKE_THE_DONOR:
        return "ERR_TOO_LIKE_THE_DONOR";
    case MAPGEN_PIPELINE_ERR_CHANGED_TOO_MUCH:  return "ERR_CHANGED_TOO_MUCH";
    case MAPGEN_PIPELINE_ERR_NOT_MEASURED:       return "ERR_NOT_MEASURED";
    case MAPGEN_PIPELINE_ERR_TARGET_UNREACHABLE:
        return "ERR_TARGET_UNREACHABLE";
    case MAPGEN_PIPELINE_ERR_DONOR_OMITTED:     return "ERR_DONOR_OMITTED";
    case MAPGEN_PIPELINE_ERR_MEMORY:            return "ERR_MEMORY";
    }
    return "ERR_UNKNOWN";
}

/*
 * The certificates, beside the map they are about.
 *
 * Named for the map rather than for the run, because the pair is what somebody
 * will pick up: a .bsp and the account of why it passed. A failure to write
 * them is not a failure of the run - the verdict already stands on what the
 * exploration found - but the file is the only copy that outlives the process.
 */
static void write_certificates(mapgen_pipeline_report_t *report)
{
    if (!report->certificates.count || !report->bsp_path[0])
        return;
    char path[MAPCOMPILE_MAX_PATH];
    const size_t n = strlen(report->bsp_path);
    if (snprintf(path, sizeof(path), "%.*s.certificates.txt",
                 (int)(n > 4 ? n - 4 : n), report->bsp_path)
        >= (int)sizeof(path))
        return;

    char *text = malloc(65536);
    if (!text)
        return;
    MapGenCertificate_Render(&report->certificates, text, 65536);
    FILE *f = fopen(path, "wb");
    if (f) {
        fputs(text, f);
        fclose(f);
    }
    free(text);
}

/*
 * The identity of a file on disk.
 *
 * The artifact that was judged is the one a certificate has to name, and the
 * only thing that knows it for certain is the file itself. Reading it again
 * costs one pass over a few hundred kilobytes and removes any question about
 * which of several attempts the hash belongs to.
 */
static uint64_t hash_artifact(const char *path, char out[MAPCOMPILE_SHA256_HEX])
{
    out[0] = '\0';
    uint8_t *data = NULL;       /* row 411: a file or a section */
    size_t bytes = 0;
    if (!MapGenFs_Read(path, &data, &bytes))
        return 0;
    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(data, bytes, digest);
    MapGenDigest_Sha256Hex(digest, out);
    free(data);
    return bytes;
}

/*
 * The finished map, with its lighting.
 *
 * Attempts compile DRAFT - bsp and a fast vis - because a run throws away
 * dozens of them and a full vis is twenty-five seconds each. The one that
 * survives is worth the full profile: on q2dm1 the rad stage costs 0.6
 * seconds and turns a lighting lump of 0 bytes into 363444, which is the
 * difference between a map that renders flat grey and one that looks like
 * the game it belongs to.
 *
 * Into a directory of its own, because the compiler refuses a job directory
 * that already holds an output and that rule is worth keeping. On any
 * failure the draft artifact stands: a run is not spoiled by the attempt to
 * light it.
 */
/* One file over another, whole or not at all. */
static bool copy_file(const char *from, const char *to)
{
    uint8_t *data = NULL;       /* row 411: either side a file or a section */
    size_t size = 0;
    const bool ok = MapGenFs_Read(from, &data, &size) && MapGenFs_Write(to, data, size);
    free(data);
    return ok;
}

/*
 * The donor's sun, for the light compile only (row 405).
 *
 * cor and q3t2 were lit by their author's tool with worldspawn "_sun_angle" "yaw pitch" (cor "-20 -90", q3t2
 * "-95 -60") beside "_sun_light", "_sun_ambient" and "_sun_diffuse". The pinned q2tools reads those three but
 * lights by the sun only when worldspawn names a "_sun" target, and takes its direction from a light entity that
 * targets it (lightmap.c: sun_pos = the light's origin minus its target's); without it the sky is an ordinary
 * surface and the sun and its ambient are off. MEASURED: the mean of the light lump, cor 87.0, mg_cor 8.8; q3t2 43.8,
 * mg_q3t2 19.8 - the PO: «на ней нет вообще лайтмапов или почти нет».
 *
 * So the copy the light compile reads gets "_sun" and the two points that give the direction - the target at a
 * start (inside the map: an entity in the void is a leak) and the light 8 units from it towards the sun - and the
 * lit file then takes back the judged file's own entity lump, so the map handed over carries exactly the entities
 * it was judged with. Nothing is done for a map without "_sun_angle" or that names its own "_sun" (q2dm1: neither).
 */
static char *read_text_file(const char *path, size_t *size)
{
    if (MapGenFs_IsMem(path)) {     /* row 411 */
        uint8_t *data = NULL;
        return MapGenFs_Read(path, &data, size) ? (char *)data : NULL;
    }
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *text = n >= 0 ? malloc((size_t)n + 1) : NULL;
    if (text && fread(text, 1, (size_t)n, f) != (size_t)n) {
        free(text);
        text = NULL;
    }
    fclose(f);
    if (text) {
        text[n] = '\0';
        *size = (size_t)n;
    }
    return text;
}

/* The value of `key` in the entity block starting at `block` (up to its first brush or its end), or NULL. */
static const char *block_value(const char *block, const char *key, char *out, size_t cap)
{
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *stop = block + 1;
    while (*stop && *stop != '{' && *stop != '}')
        stop++;
    for (const char *at = strstr(block, pattern); at && at < stop; at = strstr(at + 1, pattern)) {
        const char *q = strchr(at + strlen(pattern), '"');
        if (!q || q >= stop)
            return NULL;
        const char *e = strchr(q + 1, '"');
        if (!e || e >= stop)
            return NULL;
        snprintf(out, cap, "%.*s", (int)(e - q - 1), q + 1);
        return out;
    }
    return NULL;
}

/*
 * Row 410: worldspawn keys `key=value;key=value` into a .map's first block - a key the block has is replaced, one it
 * lacks is added after its brace. Rewrites the file; false when it could not.
 */
static bool set_world_keys(const char *map_path, const char *keys)
{
    if (!keys || !keys[0])
        return true;
    size_t size = 0;
    char *text = read_text_file(map_path, &size);
    if (!text)
        return false;
    const char *world = strchr(text, '{');
    if (!world) {
        free(text);
        return false;
    }
    const char *stop = world + 1;
    while (*stop && *stop != '{' && *stop != '}')
        stop++;
    /* the block's own lines, those not named in `keys` kept */
    char *out = malloc(size + strlen(keys) * 2u + 64u);
    if (!out) {
        free(text);
        return false;
    }
    size_t n = 0;
    const size_t head = (size_t)(world - text) + 1;
    memcpy(out, text, head);
    n = head;
    for (const char *k = keys; *k;) {
        const char *eq = strchr(k, '=');
        const char *end = strchr(k, ';');
        if (!end)
            end = k + strlen(k);
        if (eq && eq < end)
            n += (size_t)sprintf(out + n, "\n\"%.*s\" \"%.*s\"", (int)(eq - k), k, (int)(end - eq - 1), eq + 1);
        k = *end ? end + 1 : end;
    }
    for (const char *line = world + 1; line < stop;) {
        const char *nl = memchr(line, '\n', (size_t)(stop - line));
        const char *eol = nl ? nl + 1 : stop;
        bool named = false;
        if (*line == '"' || (line + 1 < eol && line[0] == '\r')) {
            const char *q = strchr(line, '"');
            const char *qe = q ? strchr(q + 1, '"') : NULL;
            if (q && qe && qe < eol)
                for (const char *k = keys; *k && !named;) {
                    const char *eq = strchr(k, '=');
                    const char *end = strchr(k, ';');
                    if (!end)
                        end = k + strlen(k);
                    named = eq && eq < end && (size_t)(eq - k) == (size_t)(qe - q - 1) && !strncmp(k, q + 1, (size_t)(eq - k));
                    k = *end ? end + 1 : end;
                }
        }
        if (!named) {
            memcpy(out + n, line, (size_t)(eol - line));
            n += (size_t)(eol - line);
        }
        line = eol;
    }
    memcpy(out + n, stop, size - (size_t)(stop - text));
    n += size - (size_t)(stop - text);
    const bool ok = MapGenFs_Write(map_path, out, n);       /* row 411: a file or a section */
    free(out);
    free(text);
    return ok;
}

static bool add_sun_for_light(const char *map_path)
{
    size_t size = 0;
    char *text = read_text_file(map_path, &size);
    if (!text)
        return false;
    bool added = false;
    char angle[64], own[64];
    const char *world = strchr(text, '{');
    if (world && block_value(world, "_sun_angle", angle, sizeof(angle))
        && !block_value(world, "_sun", own, sizeof(own))) {
        double yaw = 0.0, pitch = -90.0;
        sscanf(angle, "%lf %lf", &yaw, &pitch);
        /* a start's origin: inside the map */
        double at[3] = { 0, 0, 0 };
        bool found = false;
        for (const char *b = strchr(world + 1, '{'); b && !found; b = strchr(b + 1, '{')) {
            char cls[64], origin[96];
            if (block_value(b, "classname", cls, sizeof(cls)) && !strncmp(cls, "info_player_", 12)
                && block_value(b, "origin", origin, sizeof(origin))
                && sscanf(origin, "%lf %lf %lf", &at[0], &at[1], &at[2]) == 3)
                found = true;
        }
        FILE *f = found ? MapGenFs_OpenWrite(map_path, "wb") : NULL;      /* row 411 */
        if (f) {
            const double r = 3.14159265358979323846 / 180.0;
            /* the direction the light travels is (yaw, pitch); towards the sun is the other way */
            const double to[3] = { -cos(pitch * r) * cos(yaw * r), -cos(pitch * r) * sin(yaw * r), -sin(pitch * r) };
            const size_t head = (size_t)(world - text) + 1;
            fwrite(text, 1, head, f);
            fputs("\n\"_sun\" \"mapgen_sun\"", f);
            fwrite(text + head, 1, size - head, f);
            fprintf(f, "{\n\"classname\" \"light\"\n\"target\" \"mapgen_sun\"\n\"origin\" \"%.1f %.1f %.1f\"\n}\n",
                    at[0] + to[0] * 8.0, at[1] + to[1] * 8.0, at[2] + to[2] * 8.0);
            fprintf(f, "{\n\"classname\" \"info_null\"\n\"targetname\" \"mapgen_sun\"\n\"origin\" \"%.1f %.1f %.1f\"\n}\n",
                    at[0], at[1], at[2]);
            added = MapGenFs_Close(f) == 0;
        }
    }
    free(text);
    return added;
}

/* The lit file takes the judged file's entity lump: appended, its header pointed at it, the old bytes left unused. */
static bool restore_entities(const char *lit_path, const char *judged_path)
{
    size_t lit_size = 0, judged_size = 0;
    char *lit = read_text_file(lit_path, &lit_size);
    char *judged = read_text_file(judged_path, &judged_size);
    bool ok = false;
    if (lit && judged && lit_size >= 160 && judged_size >= 160) {
        int32_t offset = 0, length = 0;
        memcpy(&offset, judged + 8, 4);
        memcpy(&length, judged + 12, 4);
        if (offset >= 0 && length >= 0 && (size_t)offset + (size_t)length <= judged_size) {
            const size_t at = (lit_size + 3u) & ~(size_t)3u;
            /* row 411: built in one buffer, written whole - to a file or a section */
            uint8_t *whole = calloc(1, at + (size_t)length);
            if (whole) {
                const int32_t new_offset = (int32_t)at;
                memcpy(lit + 8, &new_offset, 4);
                memcpy(lit + 12, &length, 4);
                memcpy(whole, lit, lit_size);
                memcpy(whole + at, judged + offset, (size_t)length);
                ok = MapGenFs_Write(lit_path, whole, at + (size_t)length);
                free(whole);
            }
        }
    }
    free(lit);
    free(judged);
    return ok;
}

/* Row 411: the run's working root - the job folder, or "mem:<run>" when the run works in memory. */
static char g_work_root[MAPCOMPILE_MAX_PATH];

static void progress_line(const char *fmt, ...);

/* Row 411: the light compile's passes, a progress line a tenth (the Studio shows them on the stage and the plan). */
static void light_tick(const char *stage, int pass, int tenths)
{
    static char last_stage[8];
    static int last_pass = -1, last_tenths = -1;
    if (!strcmp(stage, last_stage) && pass == last_pass && tenths == last_tenths)
        return;
    snprintf(last_stage, sizeof(last_stage), "%s", stage);
    last_pass = pass;
    last_tenths = tenths;
    progress_line("stage=light-step step=%s pass=%d tenths=%d", stage, pass, tenths);
}

static bool light_the_artifact(const mapcompile_adapter_t *adapter,
                               const mapgen_pipeline_request_t *request,
                               const char *job_dir, const char *map_path,
                               char *bsp_out, size_t bsp_size, bool *sun_added)
{
    if (!adapter || !map_path || !map_path[0] || !bsp_out)
        return false;

    /* row 411: the light compile in the run's working root; its log in the job folder either way */
    char dir[MAPCOMPILE_MAX_PATH], log_dir[MAPCOMPILE_MAX_PATH];
    if (snprintf(dir, sizeof(dir), "%s/lit", g_work_root[0] ? g_work_root : job_dir) >= (int)sizeof(dir)
        || snprintf(log_dir, sizeof(log_dir), "%s/lit", job_dir) >= (int)sizeof(log_dir))
        return false;
#ifdef _WIN32
    _mkdir(log_dir);
#else
    mkdir(log_dir, 0777);
#endif

    /* The name the artifact already has, so nothing downstream has to learn
       a new one. */
    const char *base = strrchr(map_path, 0x2F);
    const char *back = strrchr(map_path, 0x5C);
    if (back > base)
        base = back;
    base = base ? base + 1 : map_path;
    char name[64];
    if (snprintf(name, sizeof(name), "%s", base) >= (int)sizeof(name))
        return false;
    char *dot = strrchr(name, 0x2E);
    if (dot)
        *dot = 0;
    if (!name[0])
        return false;

    char copy[MAPCOMPILE_MAX_PATH];
    if (snprintf(copy, sizeof(copy), "%s/%s.map", dir, name)
        >= (int)sizeof(copy))
        return false;
    if (MapGenFs_IsMem(dir)) {
        MapGenFs_ReleaseDir(dir);       /* a light pass of its own: the compiler refuses a folder that holds a map */
        if (!MapGenFs_MakeDir(dir, name))
            return false;
    }
    if (!copy_file(map_path, copy))
        return false;
    /* row 410: the donor's sun as this tool must be told it, before the sun is added from it */
    if (!set_world_keys(copy, request->light_keys))
        return false;
    if (sun_added)
        *sun_added = add_sun_for_light(copy);

    mapcompile_request_t creq;
    memset(&creq, 0, sizeof(creq));
    snprintf(creq.job_dir, sizeof(creq.job_dir), "%s", dir);
    snprintf(creq.map_name, sizeof(creq.map_name), "%s", name);
    snprintf(creq.moddir, sizeof(creq.moddir), "%s",
             request->moddir[0] ? request->moddir : job_dir);
    snprintf(creq.basedir, sizeof(creq.basedir), "%s", creq.moddir);
    creq.profile = MAPCOMPILE_PROFILE_FINAL;
    creq.format = MAPCOMPILE_FORMAT_IBSP;
    /* row 404: every P-core thread of the machine, a count fixed per machine (`light_threads`) */
    creq.threads = MAPCOMPILE_LIGHT_THREADS(request->light_threads);
    snprintf(creq.rad_flags, sizeof(creq.rad_flags), "%s", request->light_flags);  /* row 405 */
    creq.stage_timeout_ms = request->stage_timeout_ms;
    creq.max_log_bytes = request->max_log_bytes;
    creq.disk_budget_bytes = request->disk_budget_bytes;

    mapcompile_report_t lit;
    memset(&lit, 0, sizeof(lit));
    MapCompile_SetTick(light_tick);
    const mapcompile_result_t rc = MapCompile_RunProfile(adapter, &creq, &lit);
    MapCompile_SetTick(NULL);
    /*
     * Row 405 (Fable's brief 5 L5): the light tool's own words are kept beside the lit map - «Sun activated», the
     * bounces, every texture it could not find (its reflectivity then falls to the default) - not thrown away with
     * the report. Every stage of the light compile, in order, as the compiler adapter captured it.
     */
    {
        char log_path[MAPCOMPILE_MAX_PATH];
        if (snprintf(log_path, sizeof(log_path), "%s/rad.log", log_dir) < (int)sizeof(log_path)) {
            FILE *lf = fopen(log_path, "wb");
            if (lf) {
                fprintf(lf, "light compile: %s, %d threads, flags \"%s\"\n", MapCompile_ResultName(rc),
                        creq.threads, creq.rad_flags);
                for (int i = 0; i < lit.num_stages; i++)
                    fprintf(lf, "==== stage %d: exit %d%s, %u ms, %llu bytes%s\n%s\n", (int)lit.stages[i].stage,
                            (int)lit.stages[i].exit_code, lit.stages[i].timed_out ? " TIMED OUT" : "",
                            (unsigned)lit.stages[i].duration_ms,
                            (unsigned long long)lit.stages[i].stdout_total_bytes,
                            lit.stages[i].stdout_truncated ? " (the start kept)" : "",
                            lit.stages[i].stdout_captured ? lit.stages[i].stdout_captured : "");
                fclose(lf);
            }
        }
    }
    for (int i = 0; i < lit.num_stages; i++)
        free(lit.stages[i].stdout_captured);
    if (rc != MAPCOMPILE_OK || !lit.bsp_path[0])
        return false;

    snprintf(bsp_out, bsp_size, "%s", lit.bsp_path);
    return true;
}

static mapgen_bsp_t *load_bsp(const char *path)
{
    uint8_t *raw = NULL;        /* row 411: a file or a section */
    size_t n = 0;
    if (!MapGenFs_Read(path, &raw, &n) || !n) {
        free(raw);
        return NULL;
    }

    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t rc = MapGenBsp_Load(raw, (size_t)n, &bsp);
    free(raw);
    return rc == MAPGEN_BSP_OK ? bsp : NULL;
}

/*
 * The target's own material list, as the frozen manifest states it.
 *
 * A map that names a material the target cannot resolve is a map nobody can
 * load, so the mix is built against this and never against what the corpus
 * happened to contain.
 */
static char **read_manifest(const char *path, uint32_t *out_count)
{
    *out_count = 0;
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    char **list = NULL;
    uint32_t count = 0;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = '\0';
        if (!n)
            continue;
        char **grown = realloc(list, (size_t)(count + 1) * sizeof(*grown));
        if (!grown)
            break;
        list = grown;
        list[count] = malloc(n + 1);
        if (!list[count])
            break;
        memcpy(list[count], line, n + 1);
        count++;
    }
    fclose(f);
    *out_count = count;
    return list;
}

static void free_manifest(char **list, uint32_t count)
{
    for (uint32_t i = 0; i < count; i++)
        free(list[i]);
    free(list);
}

/*
 * Fidelity zero: build a map out of what was learned, and compile it.
 *
 * Fills in exactly what the transaction fills in for every other fidelity -
 * where the map and the BSP are, what the compile said, and the baseline the
 * divergence will be measured against - so that everything after the branch is
 * the same code asking the same questions.
 */
static mapgen_pipeline_result_t
synthesise(const char *donor_bsp, const char *job_dir, const char *map_name,
           const mapcompile_adapter_t *adapter,
           const mapgen_pipeline_request_t *request,
           mapgen_pipeline_report_t *report,
           char baseline[MAPCOMPILE_MAX_PATH])
{
    if (!request->snapshot[0] || !request->manifest[0])
        return MAPGEN_PIPELINE_ERR_SYNTHESIS;

    /*
     * Fidelity zero measures against a reference too, so it proves it like
     * every other fidelity. It used to call the unchecked builder, which is
     * how the one path that INVENTS a map ended up with the one baseline
     * nobody had compared to the donor.
     */
    char sha[MAPCOMPILE_SHA256_HEX];
    mapgen_equiv_report_t why;
    if (!MapGenTransaction_BuildBaselineChecked(
            donor_bsp, job_dir, map_name,
            request->moddir[0] ? request->moddir : job_dir, adapter, &why,
            baseline, sha)) {
        /* The reason is kept where a Project can store it; the progress
           voice belongs to the caller further down, which has the request. */
        if (why.axis[0] && report)
            snprintf(report->baseline_bsp, sizeof(report->baseline_bsp),
                     "%s", why.axis);
        return MAPGEN_PIPELINE_ERR_BASELINE;
    }
    snprintf(report->baseline_bsp, sizeof(report->baseline_bsp), "%s", sha);

    size_t image_size = 0;
    uint8_t *image = NULL;
    FILE *f = fopen(request->snapshot, "rb");
    if (f) {
        fseek(f, 0, SEEK_END);
        const long n = ftell(f);
        fseek(f, 0, SEEK_SET);
        image = n > 0 ? malloc((size_t)n) : NULL;
        if (image && fread(image, 1, (size_t)n, f) == (size_t)n)
            image_size = (size_t)n;
        else {
            free(image);
            image = NULL;
        }
        fclose(f);
    }
    if (!image)
        return MAPGEN_PIPELINE_ERR_SYNTHESIS;

    mapgen_snapshot_t *snap = NULL;
    const mapgen_snapshot_result_t sr =
        MapGenSnapshot_Open(image, image_size, &snap);
    free(image);
    if (sr != MAPGEN_SNAPSHOT_OK || !snap) {
        MapGenSnapshot_Free(snap);
        return MAPGEN_PIPELINE_ERR_SYNTHESIS;
    }

    uint32_t available = 0;
    char **manifest = read_manifest(request->manifest, &available);
    if (!manifest || !available) {
        free_manifest(manifest, available);
        MapGenSnapshot_Free(snap);
        return MAPGEN_PIPELINE_ERR_SYNTHESIS;
    }

    mapgen_mix_input_t in;
    memset(&in, 0, sizeof(in));
    in.snapshot = snap;
    memcpy(in.revision_uuid, MapGenSnapshot_Header(snap)->revision_uuid,
           MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(in.payload_sha256, MapGenSnapshot_Header(snap)->payload_sha256,
           MAPGEN_SHA256_BYTES);
    in.weight = 100;

    mapgen_mix_options_t options;
    memset(&options, 0, sizeof(options));
    options.available = (const char *const *)manifest;
    options.num_available = available;

    mapgen_mix_t *mix = NULL;
    const mapgen_mix_result_t mr = MapGenMix_Build(&in, 1, &options, &mix);
    if (mr != MAPGEN_MIX_OK || !mix) {
        MapGenMix_Free(mix);
        free_manifest(manifest, available);
        MapGenSnapshot_Free(snap);
        return MAPGEN_PIPELINE_ERR_SYNTHESIS;
    }

    mapgen_recipe_t *recipe = NULL;
    mapgen_synthesis_result_t rc =
        MapGenSynthesis_Recipe(mix, request->generate.seed, request->scale,
                               (mapgen_goal_t)request->goal, 0, map_name,
                               &recipe);
    if (rc != MAPGEN_SYNTHESIS_OK) {
        MapGenRecipe_Free(recipe);
        MapGenMix_Free(mix);
        free_manifest(manifest, available);
        MapGenSnapshot_Free(snap);
        return MAPGEN_PIPELINE_ERR_SYNTHESIS;
    }

    /*
     * Attempts, the way every other fidelity spends edits.
     *
     * Each one is a different map from the same recipe. The first invented map
     * the product path ever gated was refused - a region of it could not be
     * reached - and the run stopped there, because the branch took attempt
     * zero and handed it over whatever it turned out to be. A transaction gets
     * to try again; so does this.
     *
     * The reachability check here decides whether to try again, and the shared
     * section below produces the verdict. That costs one exploration on the
     * map that wins, and it buys the retry without a second copy of the
     * oracle.
     */
    char dir[MAPCOMPILE_MAX_PATH];
    snprintf(dir, sizeof(dir), "%s/synth", job_dir);
    const uint32_t budget = request->max_attempts ? request->max_attempts : 8u;
    mapgen_pipeline_result_t last = MAPGEN_PIPELINE_ERR_SYNTHESIS;
    bool playable = false;

    for (uint32_t attempt = 0; attempt < budget && !playable; ) {
        char here[MAPCOMPILE_MAX_PATH];
        snprintf(here, sizeof(here), "%s/try_%04u", dir, attempt);
#ifdef _WIN32
        _mkdir(dir);
        _mkdir(here);
#else
        mkdir(dir, 0777);
        mkdir(here, 0777);
#endif
        snprintf(report->map_path, sizeof(report->map_path), "%s/%s.map", here,
                 map_name);
        rc = MapGenSynthesis_Write(mix, recipe, (mapgen_goal_t)request->goal,
                                   attempt, report->map_path,
                                   &report->synthesis);
        if (rc != MAPGEN_SYNTHESIS_OK) {
            last = MAPGEN_PIPELINE_ERR_SYNTHESIS;
            break;
        }
        attempt = report->synthesis.attempt + 1;
        report->synthesised = true;
        report->wrote_candidate = true;

        mapcompile_request_t creq;
        memset(&creq, 0, sizeof(creq));
        snprintf(creq.job_dir, sizeof(creq.job_dir), "%s", here);
        snprintf(creq.map_name, sizeof(creq.map_name), "%s", map_name);
        snprintf(creq.moddir, sizeof(creq.moddir), "%s",
                 request->moddir[0] ? request->moddir : job_dir);
        snprintf(creq.basedir, sizeof(creq.basedir), "%s", creq.moddir);
        creq.profile = request->profile;
        creq.format = MAPCOMPILE_FORMAT_IBSP;
        creq.threads = request->threads ? request->threads
                                    : MAPCOMPILE_PINNED_THREADS;
        creq.stage_timeout_ms = request->stage_timeout_ms;
        creq.max_log_bytes = request->max_log_bytes;
        creq.disk_budget_bytes = request->disk_budget_bytes;

        memset(&report->compiled, 0, sizeof(report->compiled));
        const mapcompile_result_t crc =
            MapCompile_RunProfile(adapter, &creq, &report->compiled);
        for (int i = 0; i < report->compiled.num_stages; i++) {
            free(report->compiled.stages[i].stdout_captured);
            report->compiled.stages[i].stdout_captured = NULL;
        }
        if (crc != MAPCOMPILE_OK) {
            last = MAPGEN_PIPELINE_ERR_COMPILE;
            continue;
        }
        snprintf(report->bsp_path, sizeof(report->bsp_path), "%s",
                 report->compiled.bsp_path);
        report->compiled_a_map = true;

        mapgen_bsp_t *built = load_bsp(report->bsp_path);
        if (!built) {
            last = MAPGEN_PIPELINE_ERR_COMPILE;
            continue;
        }
        mapgen_reach_t *reach = NULL;
        mapgen_reach_options_t walk;
        memset(&walk, 0, sizeof(walk));
        walk.cancel.asked = request->cancelled;
        walk.cancel.user = request->cancelled_user;
        if (MapGenReach_ExploreWith(built, request->reach_budget
                                    ? request->reach_budget : 40000u, &walk,
                                    &reach)
            == MAPGEN_REACH_OK && reach)
            playable = MapGenReach_Passed(MapGenReach_Report(reach));
        MapGenReach_Free(reach);
        MapGenBsp_Free(built);
        last = playable ? MAPGEN_PIPELINE_OK : MAPGEN_PIPELINE_ERR_UNPLAYABLE;
    }

    MapGenRecipe_Free(recipe);
    MapGenMix_Free(mix);
    free_manifest(manifest, available);
    MapGenSnapshot_Free(snap);
    return last;
}

/*
 * THE PROGRESS STREAM (ledger row 391, Fable's brief 3 G1).
 *
 * `progress.txt` beside the ledger: one line per step of the run as it ends,
 * written and flushed at once - `PROGRESS stage=<start|baseline|plan|redeal|
 * attempt|judge|light|finish> ... elapsed=S` - so whoever drives the
 * generator (MAPGEN Studio) can say what is being done, what is done and what
 * is next while the run is alive. The ledger is the record of the attempts;
 * this is the account of the run, every stage of it, in the order it went.
 * One run at a time per process, as the pipeline itself.
 */
static FILE *g_progress;
static time_t g_progress_began;
static const bool g_progress_written = true;   /* the RED's mutation point */
/* row 392: the last line, kept for a crash record whether or not a file is
   open, and how many attempt lines were written */
static char g_progress_last[512];
static uint32_t g_progress_attempts;

const char *MapGenPipeline_LastProgress(void)
{
    return g_progress_last;
}

uint32_t MapGenPipeline_AttemptsSoFar(void)
{
    return g_progress_attempts;
}

/*
 * Flushed per line. MEASURED (row 391): without the flush the lines still
 * appear while the run is alive, because the C runtime flushes every stream
 * before it spawns the compiler - but a line written after the last compile
 * of a stretch (the judge, the light, the finish) would wait for the next
 * spawn or the end, so the flush stays.
 */
static void progress_line(const char *fmt, ...)
{
    if (!g_progress_written)
        return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_progress_last, sizeof(g_progress_last), fmt, ap);
    va_end(ap);
    if (!strncmp(g_progress_last, "stage=attempt", 13))
        g_progress_attempts++;
    if (!g_progress)
        return;
    fprintf(g_progress, "PROGRESS %s elapsed=%lld\n", g_progress_last,
            (long long)(time(NULL) - g_progress_began));
    fflush(g_progress);
}

/* An attempt's line: which pass, the edit, its family and verdict, and where
   the run stands - accepted, compiles spent of the budget, how far from the
   donor against the target. */
static void progress_attempt(const char *pass, uint32_t i,
                             const mapgen_geometry_edit_t *planned,
                             mapgen_transaction_verdict_t verdict,
                             const mapgen_transaction_step_t *step,
                             mapgen_transaction_t *txn, uint32_t compiles,
                             uint32_t budget, uint32_t target)
{
    /* row 411: a dig says its shape - a new passage, an annex, a two-storey room, a hall (the PO's options) */
    const char *shape = "-";
    mapgen_dig_report_t dr;
    if (planned->kind == MAPGEN_EDIT_DIG && MapGenTransaction_Plan(txn)
        && MapGenGeometryEdit_DigAt(MapGenTransaction_Plan(txn), planned->target, &dr) && dr.shape[0])
        shape = dr.shape;
    /* brief 9: the second map a dig owes to (a room of it, or its skin) */
    const char *from = planned->kind == MAPGEN_EDIT_DIG && MapGenTransaction_Plan(txn)
                     ? MapGenGeometryEdit_DigFrom(MapGenTransaction_Plan(txn), planned->target) : NULL;
    progress_line("stage=attempt pass=%s edit=%u family=%s shape=%s from=\"%s\" verdict=%s accepted=%u"
                  " compiles=%u budget=%u divergence=%u target=%u ms=%u", pass,
                  (unsigned)i, MapGenGeometryEdit_KindName(planned->kind), shape, from ? from : "",
                  MapGenTransaction_VerdictName(verdict),
                  (unsigned)MapGenTransaction_Accepted(txn), (unsigned)compiles,
                  (unsigned)budget, (unsigned)MapGenTransaction_Divergence(txn),
                  (unsigned)target, (unsigned)step->total_ms);
}

/* Row 394: a family the caller asked the run not to try. */
static bool family_skipped(const mapgen_pipeline_request_t *request, mapgen_edit_kind_t kind)
{
    const char *name = MapGenGeometryEdit_KindName(kind);
    for (uint32_t k = 0; k < request->num_excluded_families
                         && k < sizeof(request->excluded_families) / sizeof(request->excluded_families[0]); k++)
        if (name && !strcmp(request->excluded_families[k], name))
            return true;
    return false;
}

/*
 * One attempt, written down: its line in the job's ledger and its phase times
 * in the run's sums.
 *
 * For EVERY attempt the run makes. The finishing pass and the graft pass ran
 * after the ledger had been closed, so what they tried was in neither the
 * ledger nor the sums: MEASURED on round 27 (ledger row 272), 6 of the 604
 * attempts the run reported - 3 NO_EFFECT, 2 NOT_APPLIED and an UNPLAYABLE
 * whose witness nobody could read.
 */
static void write_attempt(FILE *ledger, uint64_t phase_ms[8],
                          uint64_t walk_sum[2],
                          const mapgen_geometry_edit_plan_t *plan, uint32_t i,
                          const mapgen_geometry_edit_t *planned,
                          mapgen_transaction_verdict_t verdict,
                          const mapgen_transaction_step_t *step)
{
    /* D18 (assignment 22): total, compile, reach, flood and mouth pairs, the
       parent's walk, divergence */
    phase_ms[0] += step->total_ms;
    phase_ms[1] += step->compile_ms;
    phase_ms[2] += step->reach_ms;
    phase_ms[3] += step->pairs_ms;
    phase_ms[4] += step->parent_ms;
    phase_ms[5] += step->divergence_ms;
    /* D28 (assignment 24): the attempt and its walk in CPU */
    phase_ms[6] += step->total_cpu_ms;
    phase_ms[7] += step->reach_cpu_ms;
    walk_sum[0] += step->walk_levels;
    walk_sum[1] += step->walk_rounds;
    if (!ledger)
        return;
    float lo[3] = { 0.0f, 0.0f, 0.0f }, hi[3] = { 0.0f, 0.0f, 0.0f };
    /* NULL for the two donor handles: the families that need one
       to place themselves are the block (not dealt) and a lift's
       full flight, and `StairBounds` answers that without it. */
    const bool placed = MapGenGeometryEdit_BoxOf(plan, NULL, NULL, i, lo, hi);
    fprintf(ledger, "%5u %-16s %-24s %4u", (unsigned)i,
            MapGenGeometryEdit_KindName(planned->kind),
            MapGenTransaction_VerdictName(verdict),
            (unsigned)step->divergence_after);
    if (placed)
        fprintf(ledger, "  %.0f %.0f %.0f  %.0f %.0f %.0f",
                (double)lo[0], (double)lo[1], (double)lo[2],
                (double)hi[0], (double)hi[1], (double)hi[2]);
    /*
     * A dig also says WHERE IT GOES, after its box.
     *
     * The box is what a delivered map can be read against; the two
     * spots are what a reader walks to and what the static guard needs
     * to ask whether the passage opens at both of them. Appended, so
     * everything that already reads this line by position still does.
     */
    if (planned->kind == MAPGEN_EDIT_DIG) {
        mapgen_dig_report_t dig;
        if (MapGenGeometryEdit_DigAt(plan, planned->target, &dig))
            fprintf(ledger, "  from %.0f %.0f %.0f to %.0f %.0f %.0f"
                            " shape %s%s",    /* row 334: the gates read it; row 405: and «air» */
                    (double)dig.from[0], (double)dig.from[1],
                    (double)dig.from[2], (double)dig.to[0],
                    (double)dig.to[1], (double)dig.to[2],
                    dig.shape[0] ? dig.shape : "-", dig.air ? " air" : "");
    }
    if (step->declined[0])
        fprintf(ledger, "  %s", step->declined);
    if (step->total_ms)
        fprintf(ledger, "  ms %u (compile %u reach %u pairs %u parent"
                        " %u divergence %u)", step->total_ms,
                step->compile_ms, step->reach_ms, step->pairs_ms,
                step->parent_ms, step->divergence_ms);
    if (step->total_ms)
        fprintf(ledger, "  cpu %u (reach %u)", step->total_cpu_ms,
                step->reach_cpu_ms);
    /* D20 and D21 (assignment 23): the walk's shape, and how much of the
       parent's walk the edit could touch */
    if (step->walk_states)
        fprintf(ledger, "  walk %u states %u levels (%u wide) %u rounds",
                step->walk_states, step->walk_levels, step->walk_levels_wide,
                step->walk_rounds);
    if (step->walk_states)          /* row 331 */
        fprintf(ledger, " (simulated %u reused %u)", step->walk_simulated,
                step->walk_reused);
    if (step->parent_states)
        fprintf(ledger, "  parent %u near %u/%u", step->parent_states,
                step->parent_near_512, step->parent_near_1024);
    fprintf(ledger, "\n");
    fflush(ledger);
}

/*
 * RESUME (ledger row 395, Fable's brief 3 G3): the ledger of the run being resumed, read before it is rewritten.
 * One entry per attempt line, in order: the schedule index, the family, the verdict, the divergence after it and the
 * line itself, written again verbatim so the resumed ledger reads as the uninterrupted one.
 */
typedef struct {
    uint32_t index;
    char family[32];
    char verdict[40];
    uint32_t divergence;
    char *line;
} replay_entry_t;

typedef struct {
    replay_entry_t *e;
    uint32_t n, at;
    bool done;                 /* ReplayDone called */
    bool diverged;
    char why[256];
} replay_t;

static void replay_free(replay_t *r)
{
    for (uint32_t i = 0; i < r->n; i++)
        free(r->e[i].line);
    free(r->e);
    memset(r, 0, sizeof(*r));
}

static bool replay_read(replay_t *r, const char *ledger_path)
{
    memset(r, 0, sizeof(*r));
    FILE *f = fopen(ledger_path, "r");
    if (!f)
        return false;
    char line[4096];
    uint32_t cap = 0;
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#')
            continue;
        replay_entry_t e;
        memset(&e, 0, sizeof(e));
        if (sscanf(line, "%u %31s %39s %u", &e.index, e.family, e.verdict, &e.divergence) != 4)
            continue;
        if (r->n == cap) {
            cap = cap ? cap * 2 : 64;
            replay_entry_t *grown = realloc(r->e, cap * sizeof(*grown));
            if (!grown)
                break;
            r->e = grown;
        }
        const size_t len = strlen(line);
        e.line = malloc(len + 1);
        if (!e.line)
            break;
        memcpy(e.line, line, len + 1);
        r->e[r->n++] = e;
    }
    fclose(f);
    return true;
}

/*
 * One attempt, through the replay while it lasts and through the transaction after. A replayed attempt's ledger line
 * is written here verbatim, so the resumed ledger reads as the uninterrupted one; a real one's by the caller. False when the resume has
 * DIVERGED; `r->why` then says where, and the run stops.
 */
static bool attempt_or_replay(replay_t *r, mapgen_transaction_t *txn, FILE *ledger, uint32_t i,
                              const mapgen_geometry_edit_t *planned, const mapgen_typed_edit_t *edit,
                              mapgen_transaction_verdict_t *verdict, mapgen_transaction_step_t *step,
                              bool *replayed)
{
    *replayed = false;
    if (r && r->at < r->n) {
        const replay_entry_t *e = &r->e[r->at];
        const mapgen_transaction_verdict_t was = MapGenTransaction_VerdictFromName(e->verdict);
        if (e->index != i || strcmp(e->family, MapGenGeometryEdit_KindName(planned->kind))
            || was >= MAPGEN_TXN_NUM_VERDICTS) {
            r->diverged = true;
            snprintf(r->why, sizeof(r->why), "the ledger's attempt %u is %u %s, the schedule offers %u %s",
                     (unsigned)r->at, (unsigned)e->index, e->family, (unsigned)i,
                     MapGenGeometryEdit_KindName(planned->kind));
            return false;
        }
        *verdict = MapGenTransaction_Replay(txn, edit, was, e->divergence, step, r->why, sizeof(r->why));
        if (r->why[0] || *verdict != was) {
            r->diverged = true;
            if (!r->why[0])
                snprintf(r->why, sizeof(r->why), "attempt %u: the ledger says %s, the replay %s", (unsigned)r->at,
                         e->verdict, MapGenTransaction_VerdictName(*verdict));
            return false;
        }
        if (ledger) {
            fputs(e->line, ledger);
            fflush(ledger);
        }
        r->at++;
        *replayed = true;
        return true;
    }
    if (r && r->n && !r->done) {
        r->done = true;
        progress_line("stage=resume replayed=%u", (unsigned)r->n);
        MapGenTransaction_ReplayDone(txn);
    }
    /*
     * Row 410 (the PO 05.10, the Studio's plan of the build): what is about to be tried and where, BEFORE it is -
     * the attempt's own line comes only with its verdict, a minute or two later. The box is the ledger's.
     */
    {
        float lo[3] = { 0.0f, 0.0f, 0.0f }, hi[3] = { 0.0f, 0.0f, 0.0f };
        const mapgen_geometry_edit_plan_t *plan = MapGenTransaction_Plan(txn);
        if (plan && MapGenGeometryEdit_BoxOf(plan, NULL, NULL, i, lo, hi))
            progress_line("stage=try edit=%u family=%s box=%.0f,%.0f,%.0f,%.0f,%.0f,%.0f", (unsigned)i,
                          MapGenGeometryEdit_KindName(planned->kind), (double)lo[0], (double)lo[1], (double)lo[2],
                          (double)hi[0], (double)hi[1], (double)hi[2]);
        else
            progress_line("stage=try edit=%u family=%s", (unsigned)i, MapGenGeometryEdit_KindName(planned->kind));
    }
    *verdict = MapGenTransaction_Try(txn, edit, step);
    return true;
}
/*
 * Row 411 (the PO, 05.10: «у нас есть куча доп параметров - это как то учитывается тоже в прогрессе параметров и на
 * схеме?»): the whole plan of this round, an edit a line - its index, family, the dig's shape, its box - beside the
 * ledger, for the Studio to draw the edits still to come. A few hundred short lines, written once a round.
 */
static void write_plan(const char *job_dir, const mapgen_geometry_edit_plan_t *plan, uint32_t round)
{
    if (!job_dir || !plan)
        return;
    char path[MAPCOMPILE_MAX_PATH];
    snprintf(path, sizeof(path), "%s/plan.txt", job_dir);
    FILE *f = fopen(path, "w");
    if (!f)
        return;
    fprintf(f, "# round %u - index family shape box-lo box-hi\n", (unsigned)round);
    for (uint32_t i = 0; i < MapGenGeometryEdit_Count(plan); i++) {
        const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
        if (!e)
            continue;
        const char *shape = "-";
        mapgen_dig_report_t dr;
        if (e->kind == MAPGEN_EDIT_DIG && MapGenGeometryEdit_DigAt(plan, e->target, &dr) && dr.shape[0])
            shape = dr.shape;
        float lo[3], hi[3];
        if (MapGenGeometryEdit_BoxOf(plan, NULL, NULL, i, lo, hi))
            fprintf(f, "%u %s %s %.0f %.0f %.0f %.0f %.0f %.0f\n", (unsigned)i, MapGenGeometryEdit_KindName(e->kind), shape,
                    (double)lo[0], (double)lo[1], (double)lo[2], (double)hi[0], (double)hi[1], (double)hi[2]);
        else
            fprintf(f, "%u %s %s\n", (unsigned)i, MapGenGeometryEdit_KindName(e->kind), shape);
    }
    fclose(f);
}

/* Every file directly in a folder removed - not the folder, nothing below it (row 395). */
static void clear_files(const char *dir)
{
#ifdef _WIN32
    char pattern[MAPCOMPILE_MAX_PATH + 4];
    snprintf(pattern, sizeof(pattern), "%s/*", dir);
    struct _finddata_t fd;
    intptr_t h = _findfirst(pattern, &fd);
    if (h == -1)
        return;
    do {
        if (fd.attrib & _A_SUBDIR)
            continue;
        char path[MAPCOMPILE_MAX_PATH + 300];
        snprintf(path, sizeof(path), "%s/%s", dir, fd.name);
        remove(path);
    } while (_findnext(h, &fd) == 0);
    _findclose(h);
#else
    (void)dir;
#endif
}
/*
 * Row 411 (Fable's brief 8 decision 5): whether the run works in memory. Each section is given room for the biggest
 * file it can hold - four times the biggest donor, 32 MB at least, 256 MB at most (cor's .bsp is 5 MB, its lit one
 * under 10) - and a run holds at most the base's, the accepted try's, the current try's, the replay's and the light
 * pass's: five directories of five sections. If that is more than the caller allows (its share of what is free), the
 * run works in files and says so; the line is what the Studio reads it from.
 */
/*
 * Row 411: the map the run made, from its sections to the job folder - where a run in files keeps it
 * (<job>/try_NNNN/<name>.map and .bsp) - each file written only when the disk does not already hold those bytes (the
 * checkpoint of the accepted try is its .map, and its .bsp until the light pass). Nothing for a map in files.
 */
/*
 * Brief 9 D5 (Fable, 05.10): the base's .map and .bsp to <job>/baseline as well, once, when the run worked in memory -
 * the delivery checks read the base from there («no map in ...job/baseline» failed three checks of the PO's first map
 * from the Studio). Nothing for a run in files: it is there already.
 */
static void materialize_base(const char *job_dir, const char *map_name)
{
    if (!g_work_root[0] || !job_dir || !map_name || !map_name[0])
        return;
    char dir[MAPCOMPILE_MAX_PATH];
    snprintf(dir, sizeof(dir), "%s/baseline", job_dir);
#ifdef _WIN32
    _mkdir(dir);
#else
    mkdir(dir, 0777);
#endif
    for (int i = 0; i < 2; i++) {
        char from[MAPCOMPILE_MAX_PATH], to[MAPCOMPILE_MAX_PATH];
        snprintf(from, sizeof(from), "%s/baseline/%s%s", g_work_root, map_name, i ? ".bsp" : ".map");
        snprintf(to, sizeof(to), "%s/%s%s", dir, map_name, i ? ".bsp" : ".map");
        uint64_t have = 0;
        if (MapGenFs_Exists(to, &have))
            continue;
        uint8_t *data = NULL;
        size_t size = 0;
        if (MapGenFs_Read(from, &data, &size))
            MapGenFs_Write(to, data, size);
        free(data);
    }
}

static void materialize_artifact(mapgen_pipeline_report_t *report, const char *job_dir)
{
    if (!MapGenFs_IsMem(report->bsp_path) || !g_work_root[0])
        return;
    const size_t root = strlen(g_work_root), m = strlen(report->bsp_path);
    if (m < root + 4 || strncmp(report->bsp_path, g_work_root, root))
        return;
    char disk[MAPCOMPILE_MAX_PATH], dir[MAPCOMPILE_MAX_PATH];
    if (snprintf(disk, sizeof(disk), "%s%s", job_dir, report->bsp_path + root) >= (int)sizeof(disk))
        return;
    snprintf(dir, sizeof(dir), "%s", disk);
    char *slash = strrchr(dir, '/');
    if (slash)
        *slash = 0;
#ifdef _WIN32
    _mkdir(dir);
#else
    mkdir(dir, 0777);
#endif
    const size_t n = strlen(disk);
    bool whole = true;
    for (int i = 0; i < 2; i++) {
        char from[MAPCOMPILE_MAX_PATH], to[MAPCOMPILE_MAX_PATH];
        snprintf(from, sizeof(from), "%.*s%s", (int)(m - 4), report->bsp_path, i ? ".bsp" : ".map");
        snprintf(to, sizeof(to), "%.*s%s", (int)(n - 4), disk, i ? ".bsp" : ".map");
        uint8_t *a = NULL, *b = NULL;
        size_t na = 0, nb = 0;
        if (MapGenFs_Read(from, &a, &na)) {
            const bool same = MapGenFs_Read(to, &b, &nb) && na == nb && !memcmp(a, b, na);
            if (!same && !MapGenFs_Write(to, a, na))
                whole = false;
        } else
            whole = false;
        free(a);
        free(b);
    }
    if (!whole)
        return;
    snprintf(report->bsp_path, sizeof(report->bsp_path), "%s", disk);
    snprintf(report->map_path, sizeof(report->map_path), "%.*s.map", (int)(n - 4), disk);
}

static bool choose_memory(const char *donor_bsp, const mapgen_pipeline_request_t *request, const char *map_name)
{
    g_work_root[0] = '\0';
    if (!request->memory_bytes) {
        progress_line("stage=memory mode=files why=\"not asked\"");
        return false;
    }
    uint64_t biggest = 0, size = 0;
    if (MapGenFs_Exists(donor_bsp, &size))
        biggest = size;
    for (uint32_t i = 0; i < request->num_other_donors && i < MAPGEN_PIPELINE_MAX_DONORS; i++)
        if (request->other_donors[i][0] && MapGenFs_Exists(request->other_donors[i], &size) && size > biggest)
            biggest = size;
    uint64_t room = biggest * 4u;
    if (room < (32ull << 20))
        room = 32ull << 20;
    if (room > (256ull << 20))
        room = 256ull << 20;
    const uint64_t need = room * 25u;
    if (need > request->memory_bytes) {
        progress_line("stage=memory mode=files need_mb=%llu allowed_mb=%llu why=\"not enough free memory\"",
                      (unsigned long long)(need >> 20), (unsigned long long)(request->memory_bytes >> 20));
        return false;
    }
#ifdef _WIN32
    snprintf(g_work_root, sizeof(g_work_root), "mem:q2mg_%lu_%llx", (unsigned long)_getpid(),
             (unsigned long long)time(NULL));
#else
    (void)map_name;
    progress_line("stage=memory mode=files why=\"no memory files here\"");
    return false;
#endif
    MapGenFs_SetRoom(room);
    progress_line("stage=memory mode=memory root=%s room_mb=%llu need_mb=%llu allowed_mb=%llu checkpoints=%d",
                  g_work_root + 4, (unsigned long long)(room >> 20), (unsigned long long)(need >> 20),
                  (unsigned long long)(request->memory_bytes >> 20), request->no_checkpoints ? 0 : 1);
    (void)map_name;
    return true;
}

static mapgen_pipeline_result_t run_pipeline(const char *donor_bsp,
                                             const char *job_dir,
                                             const char *map_name,
                                             const mapcompile_adapter_t *adapter,
                                             const mapgen_pipeline_request_t *request,
                                             mapgen_pipeline_report_t *report,
                                             mapgen_pipeline_progress_fn progress,
                                             void *progress_user)
{
    mapgen_pipeline_report_t local;
    if (!report)
        report = &local;
    memset(report, 0, sizeof(*report));
    /* row 395: the ledger of the run being resumed, when this one resumes */
    static replay_t replay;
    replay_free(&replay);

    /* Said once here so the rest of the function can just say where it is. */
#define SAY(percent, what) \
    do { if (progress) progress(progress_user, (percent), (what)); } while (0)

    if (!donor_bsp || !job_dir || !map_name || !adapter || !request)
        return MAPGEN_PIPELINE_ERR_ARGS;
    if (snprintf(report->map_path, sizeof(report->map_path), "%s/%s.map",
                 job_dir, map_name) >= (int)sizeof(report->map_path))
        return MAPGEN_PIPELINE_ERR_ARGS;

    /* --- 1: the candidate, one edit at a time ----------------------------- */

    /*
     * The transaction, not a batch.
     *
     * Codex's ruling of 2026-09-02: a schedule applied wholesale to one
     * candidate and compiled once at the end has no per-edit cost, nothing to
     * discard when one edit of two hundred broke the map, and no way to say
     * where the budget went. Every attempt below is a real compile and that is
     * the price of being able to answer those.
     */
    SAY(6, "reading the donor");

    const uint32_t target =
        MapGenDivergence_Target((uint32_t)request->generate.fidelity);

    char baseline[MAPCOMPILE_MAX_PATH];
    /* D19 (assignment 23): the transaction's walk of the baseline, taken over
       for the oracle when the run took one */
    mapgen_reach_t *baseline_walk = NULL;
    baseline[0] = '\0';

    if (request->generate.fidelity == 0) {
        /*
         * Nothing to fork.
         *
         * A donor is still named, and still compiled, because divergence needs
         * a reference and the reference is the donor through this compiler -
         * at zero the candidate is measured to be a thousand permille away
         * from it rather than a few.
         */
        const mapgen_pipeline_result_t sr =
            synthesise(donor_bsp, job_dir, map_name, adapter, request, report,
                       baseline);
        if (sr != MAPGEN_PIPELINE_OK)
            return sr;
        goto judge;
    }

    /* The baseline is a full compile of the donor's own geometry, and on a
       real map it is a minute of the run rather than an instant. */
    SAY(8, "compiling the donor as it is");
    /*
     * RESUME (row 395): the run this job folder holds is read back before
     * anything of it is written again - its ledger, to replay - and its
     * baseline is built again from nothing (the compiler refuses a folder that
     * already holds an output; the build is deterministic, so it is the same).
     */
    if (request->resume) {
        char path[MAPCOMPILE_MAX_PATH];
        snprintf(path, sizeof(path), "%s/ledger.txt", job_dir);
        if (!replay_read(&replay, path)) {
            progress_line("stage=resume-failed why=\"no ledger to resume from\"");
            return MAPGEN_PIPELINE_ERR_ARGS;
        }
        snprintf(path, sizeof(path), "%s/baseline", job_dir);
        clear_files(path);
        progress_line("stage=resume ledger=%u", (unsigned)replay.n);
    }
    progress_line("stage=baseline");

    /*
     * The other donors, passed through rather than dropped.
     *
     * A request that names them and a transaction that never hears about them
     * is the same failure as an operator nothing can reach: the feature exists
     * in the layer below and the product cannot use it.
     */
    const char *others[MAPGEN_PIPELINE_MAX_DONORS];
    uint32_t num_others = 0;
    for (uint32_t i = 0; i < request->num_other_donors
                         && i < MAPGEN_PIPELINE_MAX_DONORS; i++)
        if (request->other_donors[i][0])
            others[num_others++] = request->other_donors[i];

    mapgen_transaction_t *txn = NULL;
    /* row 408: a dig values its downlights for the finished map's light pass */
    MapGenGeometryEdit_SetLightFlags(request->light_flags);
    /* row 411: the tries in memory when the run may take it, the accepted ones checkpointed to the job folder */
    const bool in_memory = choose_memory(donor_bsp, request, map_name);
    MapGenTransaction_SetCheckpoints(job_dir, !request->no_checkpoints);
    const mapgen_transaction_result_t opened =
        MapGenTransaction_BeginWithDonors(
            donor_bsp, in_memory ? g_work_root : job_dir, map_name,
            request->moddir[0] ? request->moddir : job_dir,
            adapter, request->generate.seed,
            num_others ? others : NULL, num_others, &txn);
    if (opened == MAPGEN_TXN_ERR_BASELINE) {
        /* row 412: which parts of the copy differ from the original, and how - the Studio says it */
        mapgen_equiv_report_t why;
        if (MapGenTransaction_LastBaselineWhy(&why)) {
            char axes[256] = "";
            for (int r = MAPGEN_EQUIV_DIFF_SPACE; r < MAPGEN_EQUIV_RESULT_COUNT; r++)
                if (why.failed_axes & MAPGEN_EQUIV_AXIS_BIT(r)) {
                    const size_t used = strlen(axes);
                    snprintf(axes + used, sizeof(axes) - used, "%s%s", used ? "," : "",
                             MapGenEquivalence_ResultName((mapgen_equiv_result_t)r));
                }
            /* every part's own words, not only the first's */
            char said[4 * MAPGEN_EQUIV_DETAIL] = "";
            for (int r = MAPGEN_EQUIV_DIFF_SPACE; r < MAPGEN_EQUIV_RESULT_COUNT; r++)
                if ((why.failed_axes & MAPGEN_EQUIV_AXIS_BIT(r)) && why.axis_detail[r][0]) {
                    const size_t used = strlen(said);
                    snprintf(said + used, sizeof(said) - used, "%s%s", used ? "; " : "", why.axis_detail[r]);
                }
            if (!said[0])
                snprintf(said, sizeof(said), "%s", why.detail);
            for (char *c = said; *c; c++)
                if (*c == '"' || *c == '\n' || *c == '\r')
                    *c = '\'';
            progress_line("stage=baseline-refused axes=%s what=\"%s\"", axes[0] ? axes : "none", said);
            fprintf(stderr, "baseline refused: %s - %s\n", axes[0] ? axes : "none", said);
        }
        return MAPGEN_PIPELINE_ERR_BASELINE;
    }
    if (opened != MAPGEN_TXN_OK)
        return MAPGEN_PIPELINE_ERR_GENERATE;
    /* row 400: a donor rebuilt with faithful skins, and what it still draws differently */
    if (MapGenTransaction_FaithfulSkins(txn)) {
        mapgen_equiv_report_t eq;
        if (MapGenTransaction_Equivalence(txn, &eq))
            progress_line("stage=baseline-faithful planes_missing=%u planes_added=%u residue_area=%.0f drawn=%.0f "
                          "mapping=%u", (unsigned)eq.planes_missing, (unsigned)eq.planes_added,
                          eq.groups_missing_area + eq.groups_added_area, eq.drawn_area[0],
                          (unsigned)eq.mapping_mismatch);
    }

    /* Aim at the band, so an edit that would jump past it is refused while
       there are still edits left to try. */
    if (!request->diagnostic_no_band)
        MapGenTransaction_SetBand(txn, target, 50);

    /*
     * And how far each edit may reach, which is the other side of the same
     * number: a fork at ninety per cent of q2dm1 moves a water level by a
     * stride, one at fifty by half a storey, one at nothing by a storey.
     *
     * "Я был бы не против прочих вариаций когда процент от донора q2dm1
     * понижается" - the PO, 2026-09-08. Without this every fidelity dealt the
     * same small amounts and the low ones reached their band by doing the
     * same small thing more times.
     */
    MapGenTransaction_SetAmbition(txn, 100 - (int32_t)request->generate.fidelity);

    const mapgen_geometry_edit_plan_t *plan = MapGenTransaction_Plan(txn);
    uint32_t offered = MapGenGeometryEdit_Count(plan);
    /*
     * The budget is ATTEMPTS, and the rounds share it.
     *
     * One deal of q2dm1's catalogue spends about a hundred and sixteen of
     * them - the rest of the schedule is paint, which is skipped while the
     * band is unmet - so a budget the size of the catalogue is about two and
     * a half deals, and a run costs what it used to.
     */
    /*
     * And the default budget is a NUMBER OF COMPILES, not the size of the
     * schedule.
     *
     * Once `REJECTED_NOT_APPLIED` stopped spending the budget, a run walked its
     * whole schedule and compiled everything that applied: MEASURED 2026-09-13
     * on q2dm1 at fidelity 20, 49 compiles in 75 minutes - about a minute and a
     * quarter each - with the divergence target (800 permille) unreachable on
     * this donor, so the run would have spent all 334 of its offered edits and
     * taken seven hours. Six maps that way is a night. Forty-five compiles is
     * fifty minutes a map, which is what a batch of six costs in one evening,
     * and a caller who wants more says so in `max_attempts`.
     */
    const uint32_t budget = request->max_attempts ? request->max_attempts
                          : (offered < 45u ? offered : 45u);
    /*
     * Row 410: and what the plan holds, by kind and by the dig's shape - the PO's creative options («Новые проходы»,
     * «Пристройки», «Комнаты в два этажа», «Мосты») change these and nothing else, and a plan line that said only
     * how many edits in all could not show it (q2dm1 with and without them: offered=339 both).
     */
    uint32_t tunnels = 0, annexes = 0, storeys = 0;
    for (uint32_t d = 0; plan && d < MapGenGeometryEdit_NumDigs(plan); d++) {
        mapgen_dig_report_t dr;
        if (!MapGenGeometryEdit_DigAt(plan, d, &dr))
            continue;
        if (!strcmp(dr.shape, "annex"))
            annexes++;
        else if (!strcmp(dr.shape, "storeys"))
            storeys++;
        else
            tunnels++;
    }
    write_plan(job_dir, plan, 0);
    /* brief 9 D4: what the second map gave the plan, and why not more - the Studio says it in words */
    if (num_others) {
        uint32_t tally[8];
        MapGenGeometryEdit_SecondTally(plan, tally);
        progress_line("stage=second-map name=\"%s\" rooms=%u skins=%u tried=%u size=%u empty=%u nosite=%u nopickup=%u"
                      " exchanges=%u", others[0], (unsigned)tally[0], (unsigned)tally[1], (unsigned)tally[2],
                      (unsigned)tally[3], (unsigned)tally[4], (unsigned)tally[5], (unsigned)tally[6],
                      (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_GRAFT_BUNDLE) : 0u));
    }
    progress_line("stage=plan offered=%u budget=%u target=%u digs=%u annexes=%u storeys=%u spans=%u floods=%u"
                  " windows=%u reliquids=%u", (unsigned)offered, (unsigned)budget, (unsigned)target, (unsigned)tunnels,
                  (unsigned)annexes, (unsigned)storeys,
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_SPAN) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_FLOOD) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_WINDOW) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_RELIQUID) : 0u));
    {   /* row 412: the real rooms of the base itself the plan dealt (rooms of the second map are said above) */
        uint32_t tally[8];
        MapGenGeometryEdit_SecondTally(plan, tally);
        progress_line("stage=plan-rooms copies=%u", (unsigned)tally[7]);
    }

    /*
     * Attempts are the middle of the bar.
     *
     * Each one is a real compile, the budget is known, and how many of them
     * will actually be spent is not - a run that reaches the band early stops
     * there. So the bar advances with the attempts that happen and simply
     * stops climbing when they do, which is honest about both.
     */
    const uint32_t spend_from = 12, spend_to = 55;

    /*
     * Rounds, because running out of ideas is not the same as arriving.
     *
     * The schedule is dealt once from the donor, and when the last edit in it
     * has been tried the run used to stop wherever it happened to be.
     * MEASURED on schema 3: every fidelity below a hundred returned the SAME
     * file at 24 permille, because the stopping point is a property of the
     * catalogue and not of the target - and the three seeds that were handed
     * to the PO landed at 30, 56 and 75 against a band of 50 to 150, so
     * whether a seed reached its band was luck.
     *
     * So a run that is still short deals again, from a seed of its own, over
     * the geometry the accepted edits have left. Each round is a different
     * hand over a different map. The budget is the count of ATTEMPTS, which
     * is what a compile costs, and it is spent across the rounds rather than
     * per round: a run that cannot reach its band inside it is a refusal, and
     * ERR_TARGET_UNREACHABLE still says so.
     */
    /*
     * The LEDGER: one line per attempt, with the family and the box.
     *
     * The PO photographs something he does not like and asks what it is, and
     * on 2026-09-10 answering that cost two rounds of screenshots because
     * nothing a run wrote down said WHERE anything went. Every family already
     * knows its own box; `MapGenGeometryEdit_BoxOf` asks whichever one owns
     * the edit, and this writes it beside the verdict.
     *
     * Written as it goes rather than at the end, so a run that is killed or
     * that dies still leaves what it had done.
     */
    char ledger_path[MAPCOMPILE_MAX_PATH];
    snprintf(ledger_path, sizeof(ledger_path), "%s/ledger.txt", job_dir);
    FILE *ledger = fopen(ledger_path, "w");
    if (ledger) {
        fprintf(ledger, "# %s fidelity %u seed %llu\n", map_name,
                (unsigned)request->generate.fidelity,
                (unsigned long long)request->generate.seed);
        fprintf(ledger, "# index family verdict divergence"
                        " box-lo box-hi\n");
    }
    uint32_t spent_to = 0;
    uint32_t attempts = 0;
    /* D18 (assignment 22): where the run's attempts spent their time, in ms:
       total, compile, reach, flood and mouth pairs, the parent's walk,
       divergence - and D28's (assignment 24) CPU, the attempts' and their
       walks' */
    uint64_t phase_ms[8] = { 0, 0, 0, 0, 0, 0, 0, 0 };
    /* D20 (assignment 23): the candidates' walks, levels and rounds summed */
    uint64_t walk_sum[2] = { 0, 0 };
    uint32_t rounds_dealt = 0;          /* row 397 */
    for (uint32_t round = 0; round < MAPGEN_PIPELINE_MAX_ROUNDS; round++) {
      rounds_dealt = round + 1u;
      if (round) {
          if (MapGenTransaction_Divergence(txn) >= target || attempts >= budget)
              break;
          if (MapGenTransaction_Redeal(txn, request->generate.seed
                                            + 0x9E3779B9ull * (round + 1))
              != MAPGEN_TXN_OK)
              break;
          plan = MapGenTransaction_Plan(txn);
          offered = MapGenGeometryEdit_Count(plan);
          SAY(50, "dealing again");
          write_plan(job_dir, plan, round);
          progress_line("stage=redeal round=%u offered=%u", (unsigned)round,
                        (unsigned)offered);
      }
      for (uint32_t i = 0; i < offered && attempts < budget; i++) {
        spent_to = i;
        if (MapGenTransaction_Divergence(txn) >= target)
            break;                       /* far enough; stop spending */
        {
            const uint32_t span = spend_to - spend_from;
            const uint32_t at = budget ? spend_from + (span * i) / budget
                                       : spend_from;
            char what[96];
            snprintf(what, sizeof(what), "building a candidate (%u of %u)",
                     (unsigned)(i + 1), (unsigned)budget);
            SAY(at, what);
        }
        const mapgen_geometry_edit_t *planned = MapGenGeometryEdit_At(plan, i);
        if (!planned)
            break;
        if (family_skipped(request, planned->kind))
            continue;                    /* row 394: the caller said not this family */
        /*
         * Never fill the budget with paint - section 4.1, in as many words.
         *
         * While a structural band is unmet, a family that contributes zero to
         * the architecture metric cannot bring the run any closer to it, and
         * attempting one costs a compile to measure a zero that the contract
         * already fixed. On q2dm1 that was 173 compiles per anchor.
         *
         * Skipped rather than refused: the edit was never tried, so nothing
         * about it is reported as a rejection.
         */
        if (target > 0 && !MapGenGeometryEdit_MovesArchitecture(planned->kind))
            continue;
        const mapgen_typed_edit_t edit = { planned->kind, i, planned->amount };
        mapgen_transaction_step_t step;
        mapgen_transaction_verdict_t verdict;
        bool replayed = false;
        if (!attempt_or_replay(&replay, txn, ledger, i, planned, &edit, &verdict, &step, &replayed))
            break;                       /* row 395: the resume diverged - said below */
        /*
         * The budget counts COMPILES, not tries.
         *
         * `REJECTED_NOT_APPLIED` is the operator declining, and the transaction
         * says what that costs in as many words: «no compile, no directory, and
         * the accepted candidate has not moved». Counting it spent the whole
         * run on operators that never apply to this donor: MEASURED on the
         * delivery of 2026-09-12, mg_20 spent 306 of its 336 attempts that way
         * - widen-connector 113, reshape-room 112, turn-bundle 50 - and stopped
         * after three rounds at 107 permille of the 800 its fidelity asked for,
         * which is exactly the PO's «эта карта менее разнообразная, чем даже
         * две предыдущие». mg_60 305 of 331 and mg_50 306 of 332 are the same
         * run.
         */
        if (verdict != MAPGEN_TXN_REJECTED_NOT_APPLIED)
            attempts++;
        if ((unsigned)verdict < MAPGEN_TXN_NUM_VERDICTS)
            report->by_verdict[verdict]++;
        if (!replayed)
            write_attempt(ledger, phase_ms, walk_sum, plan, i, planned, verdict,
                          &step);
        progress_attempt(replayed ? "replay" : "edits", i, planned, verdict, &step, txn,
                         attempts, budget, target);
      }
      if (replay.diverged || MapGenTransaction_Divergence(txn) >= target || attempts >= budget)
          break;
    }

    /*
     * The finishing pass: what makes it a FORK rather than a rebuild.
     *
     * "A fork is not only architecture - it is also variations of weapons and
     * spawn points" (PO, 2026-09-07). The families that do that have been in
     * the schedule all along and have never run below fidelity 100: a family
     * that cannot move the architecture metric is skipped while a structural
     * band is unmet, and the band is unmet until the last structural edit is
     * spent. So the three forks he walked had q2dm1's weapons on q2dm1's
     * pedestals and q2dm1's spawns, to the unit.
     *
     * They run here, after the band is settled, and they cannot disturb it:
     * TZ 14.0.1 gives an item swap and a spawn no architectural credit, so
     * neither can carry the run out of its band. What they can still do is
     * put a pickup somewhere nobody can reach or a start inside a wall, and
     * the transaction's own gates - reachability, the drowned rule - answer
     * that, which is why each one is a real attempt.
     *
     * Bounded, because each is a compile.
     */
    /*
     * Not at fidelity 100. There the candidate must BE the donor - the
     * contract's one exact number - and a fork's variations are the opposite
     * of that.
     */
    if (!request->diagnostic_no_band && target > 0) {
        uint32_t finished = 0;
        for (uint32_t i = 0; i < offered
                             && finished < MAPGEN_PIPELINE_FINISHING; i++) {
            const mapgen_geometry_edit_t *planned =
                MapGenGeometryEdit_At(plan, i);
            if (!planned)
                break;
            if (planned->kind != MAPGEN_EDIT_SWAP_ITEM
                && planned->kind != MAPGEN_EDIT_MOVE_SPAWN)
                continue;
            if (family_skipped(request, planned->kind))
                continue;                /* row 394 */
            const mapgen_typed_edit_t edit = { planned->kind, i,
                                               planned->amount };
            mapgen_transaction_step_t step;
            mapgen_transaction_verdict_t verdict;
            bool replayed = false;
            if (replay.diverged
                || !attempt_or_replay(&replay, txn, ledger, i, planned, &edit, &verdict, &step, &replayed))
                break;
            if ((unsigned)verdict < MAPGEN_TXN_NUM_VERDICTS)
                report->by_verdict[verdict]++;
            if (!replayed)
                write_attempt(ledger, phase_ms, walk_sum, plan, i, planned,
                              verdict, &step);
            progress_attempt(replayed ? "replay" : "finishing", i, planned, verdict, &step, txn,
                             attempts, budget, target);
            finished++;
        }
    }

    /*
     * A donor's contribution is an OBLIGATION, not a line in the budget.
     *
     * GF7 requires a major intact contribution from every active donor and
     * forbids silent omission, and the loop above cannot deliver that. It
     * stops at the target, and a graft dealt to its own fair place in the
     * schedule usually sits past that point: measured on q2dm1 at fidelity 90,
     * two donors offered, ZERO grafts kept and zero donors credited. The donor
     * was offered, planned, attributed - and never reached. That is exactly
     * the silent omission the phase forbids.
     *
     * Ranking grafts first was tried and is far worse: every anchor collapsed
     * to 79 permille and F90 through F25 returned the same file, because an
     * early graft costs the whole rest of the schedule. So the graft is
     * attempted LAST instead - after the budget has done its work, where
     * nothing downstream can be disturbed by it.
     *
     * It is not privileged, only reached. Every gate still applies: surface
     * faults, the compiler, and the band - a graft that would carry the run
     * outside its tolerance is refused like any other edit.
     *
     * At target 0 it is skipped only when there is nobody else to graft FROM.
     * "The answer is the donor" is the single-donor rule, and Codex's ruling
     * of 2026-09-06 (section 5) is that it cannot stand in for multi-donor
     * composition: a run that named a second donor and then declined to try
     * any of it because the target was zero has dropped that donor, which is
     * the omission the phase forbids.
     */
    if (target > 0 || MapGenTransaction_NumOtherDonors(txn) > 0) {
        for (uint32_t i = spent_to; i < offered; i++) {
            const mapgen_geometry_edit_t *planned =
                MapGenGeometryEdit_At(plan, i);
            if (!planned || planned->kind != MAPGEN_EDIT_GRAFT_BUNDLE
                || family_skipped(request, planned->kind))
                continue;
            const mapgen_typed_edit_t edit = { planned->kind, i,
                                               planned->amount };
            mapgen_transaction_step_t step;
            mapgen_transaction_verdict_t verdict;
            bool replayed = false;
            if (replay.diverged
                || !attempt_or_replay(&replay, txn, ledger, i, planned, &edit, &verdict, &step, &replayed))
                break;
            if ((unsigned)verdict < MAPGEN_TXN_NUM_VERDICTS)
                report->by_verdict[verdict]++;
            if (!replayed)
                write_attempt(ledger, phase_ms, walk_sum, plan, i, planned,
                              verdict, &step);
            progress_attempt(replayed ? "replay" : "graft", i, planned, verdict, &step, txn,
                             attempts, budget, target);
        }
    }

    /* row 395: a resume that diverged stops here and says where */
    if (replay.diverged) {
        progress_line("stage=resume-diverged why=\"%s\"", replay.why);
        if (ledger) {
            fprintf(ledger, "# resume diverged: %s\n", replay.why);
            fclose(ledger);
            ledger = NULL;
        }
        MapGenTransaction_Free(txn);
        replay_free(&replay);
        return MAPGEN_PIPELINE_ERR_GENERATE;
    }
    if (replay.n && !replay.done) {
        replay.done = true;
        MapGenTransaction_ReplayDone(txn);
    }
    replay_free(&replay);
    /* row 397 (Fable's brief 3 G4): what ended the edits, for a run short of its target to say */
    snprintf(report->ended_by, sizeof(report->ended_by), "%s",
             MapGenTransaction_Divergence(txn) >= target ? "target" : attempts >= budget ? "budget" : "schedule");
    report->compiles = attempts;
    report->budget = budget;
    report->rounds = rounds_dealt;

    /* The run's sums close the ledger after its LAST attempt (row 272). */    if (ledger) {
        {
            const uint64_t named = phase_ms[1] + phase_ms[2] + phase_ms[3]
                                 + phase_ms[4] + phase_ms[5];
            fprintf(ledger, "# time in attempts %.0f s: compile %.0f, reach"
                            " %.0f, pairs %.0f, parent %.0f, divergence %.0f,"
                            " the rest %.0f\n", (double)phase_ms[0] / 1000.0,
                    (double)phase_ms[1] / 1000.0,
                    (double)phase_ms[2] / 1000.0,
                    (double)phase_ms[3] / 1000.0,
                    (double)phase_ms[4] / 1000.0,
                    (double)phase_ms[5] / 1000.0,
                    phase_ms[0] > named
                        ? (double)(phase_ms[0] - named) / 1000.0 : 0.0);
        }
        /* D28 (assignment 24): the same attempts in CPU, and what the walk had
           to run on */
        fprintf(ledger, "# cpu in attempts %.0f s, of it the walks %.0f s;"
                        " %d logical CPUs in the affinity mask, the walk"
                        " takes %d workers\n", (double)phase_ms[6] / 1000.0,
                (double)phase_ms[7] / 1000.0, Q2PROX_Cpu_AffinityCount(),
                Q2PROX_Cpu_PerformanceCount());
        fprintf(ledger, "# walks: %llu levels, %llu rounds\n",
                (unsigned long long)walk_sum[0],
                (unsigned long long)walk_sum[1]);
        fprintf(ledger, "# %u attempted, divergence %u of target %u\n",
                (unsigned)attempts,
                (unsigned)MapGenTransaction_Divergence(txn),
                (unsigned)target);
        fclose(ledger);
        ledger = NULL;
    }

    /*
     * If nothing was spent there is still a map to make.
     *
     * Fidelity 100 spends none by design, and a run that handed back the
     * donor's own file would be handing back the map it was given rather than
     * one it built - and every gate below would then be judging the donor.
     */
    if (MapGenTransaction_Accepted(txn) == 0)
        MapGenTransaction_Materialise(txn, NULL);

    report->attempted = MapGenTransaction_Attempted(txn);
    report->accepted = MapGenTransaction_Accepted(txn);
    /* Which donors are in the map, which is the only sense in which one
       contributed. Asked of the transaction, which is what retained them. */
    report->grafts_accepted = MapGenTransaction_GraftsAccepted(txn);
    report->donors_offered = MapGenTransaction_NumOtherDonors(txn);
    for (uint32_t i = 0; i < report->donors_offered
                         && i < MAPGEN_PIPELINE_MAX_DONORS; i++) {
        const char *name = MapGenTransaction_OtherDonor(txn, i);
        snprintf(report->donor_name[i], sizeof(report->donor_name[i]), "%s",
                 name ? name : "");
        report->donor_used[i] = MapGenTransaction_DonorContributed(txn, i);
        if (report->donor_used[i])
            report->donors_contributed++;
    }
    report->reached_permille = MapGenTransaction_Divergence(txn);
    report->missing_permille = report->reached_permille < target
                             ? target - report->reached_permille : 0;
    /* Refined below from the COMPLETE measurement, which is the one the
       verdict comes from; this is what the transaction thought at the time. */
    report->wrote_candidate = report->accepted > 0;
    report->compiled_a_map = report->accepted > 0;
    snprintf(report->bsp_path, sizeof(report->bsp_path), "%s",
             MapGenTransaction_AcceptedBsp(txn));
    if (report->accepted > 0) {
        /* The candidate is the one that was judged: its own directory, not the
           job root, because every attempt got a directory of its own. */
        const size_t n = strlen(report->bsp_path);
        snprintf(report->map_path, sizeof(report->map_path), "%.*s.map",
                 (int)(n > 4 ? n - 4 : n), report->bsp_path);
    }
    if (report->reach.spawns == 0 && MapGenTransaction_Reach(txn)) {
        report->reach = *MapGenTransaction_Reach(txn);
        report->measured_reach = report->accepted > 0;
    }
    /*
     * Taken by value before the transaction goes.
     *
     * The complete oracle at the end of this function measures against the
     * baseline, and the baseline belongs to the transaction - which is freed
     * here, a hundred lines earlier than it is read.
     */
    snprintf(baseline, sizeof(baseline), "%s",
             MapGenTransaction_BaselineBsp(txn));
    snprintf(report->baseline_bsp, sizeof(report->baseline_bsp), "%s",
             MapGenTransaction_BaselineSha256(txn));
    baseline_walk = MapGenTransaction_TakeBaselineWalk(txn);
    MapGenTransaction_Free(txn);
    /*
     * Row 411: the map the run made stays in memory through the judge and the light pass over it, and is written to
     * the job folder ONCE, lit, where a run in files keeps it (materialize_artifact) - before the certificates beside
     * it, or at the finish line whatever way the run ended.
     */

    /*
     * Nothing survived, or not enough did.
     *
     * Handing over the donor with paint on it is what a maximum with no
     * minimum permitted three times running, and it is the thing this refusal
     * exists to stop.
     */
    if (report->accepted == 0 && target > 0) {
        /*
         * Nothing survived, and two of the reasons are not about the band at
         * all: a compiler that could not build anything, and a map nothing
         * could play. Those say the schedule was never the problem, and
         * telling a caller its fidelity was too ambitious sends them to fix
         * the wrong thing.
         *
         * Anything else waits for the measurement below, because whether a
         * run that accepted nothing came out too like its donor or nothing
         * like it is not a question the ledger can answer.
         */
        if (report->by_verdict[MAPGEN_TXN_REJECTED_COMPILE]) {
            MapGenReach_Free(baseline_walk);
            return MAPGEN_PIPELINE_ERR_COMPILE;
        }
        if (report->by_verdict[MAPGEN_TXN_REJECTED_UNPLAYABLE]) {
            MapGenReach_Free(baseline_walk);
            return MAPGEN_PIPELINE_ERR_UNPLAYABLE;
        }
    }

    /*
     * What was actually produced, by identity.
     *
     * The transaction knows each attempt's hash and the pipeline had only the
     * path, so the compile report - and every certificate stamped from it -
     * carried an empty one. A certificate about no particular map is about
     * every map, and the checker that refuses stale ones would have refused
     * all of them.
     */
    /* --- 3: can it be played ---------------------------------------------- */

judge:
    progress_line("stage=judge");

    /* After the label, because fidelity zero jumps here and its artifact needs
       naming just as much. */
    report->compiled.bsp_bytes =
        hash_artifact(report->bsp_path, report->compiled.bsp_sha256);
    if (report->compiled.bsp_bytes)
        report->compiled.result = MAPCOMPILE_OK;

    mapgen_bsp_t *candidate = load_bsp(report->bsp_path);
    if (!candidate) {
        MapGenReach_Free(baseline_walk);
        return MAPGEN_PIPELINE_ERR_COMPILE;
    }
    report->compiled_a_map = true;

    /*
     * The candidate against the DONOR, not only against the baseline.
     *
     * Divergence is measured from B, so anything already lost in D-to-B is the
     * zero everything else is measured from - and could be lost again without
     * the number moving. This asks the other question directly.
     *
     * At fidelity 100 nothing was applied, so the candidate must BE the donor
     * and a difference is a refusal. Below that the edits are meant to change
     * the map, so what fired is recorded rather than judged.
     */
    {
        mapgen_bsp_t *donor_for_check = load_bsp(donor_bsp);
        if (donor_for_check) {
            mapgen_equiv_policy_t policy;
            mapgen_equiv_report_t against_donor;
            MapGenEquivalence_DefaultPolicy(&policy);
            const mapgen_equiv_result_t dc =
                MapGenEquivalence_Compare(donor_for_check, candidate, &policy,
                                          &against_donor);
            report->candidate_axes = against_donor.failed_axes;
            snprintf(report->candidate_detail,
                     sizeof(report->candidate_detail), "%s",
                     dc == MAPGEN_EQUIV_OK ? "the candidate is the donor"
                                           : against_donor.detail);
            MapGenBsp_Free(donor_for_check);
            if (request->generate.fidelity >= 100
                && dc != MAPGEN_EQUIV_OK) {
                MapGenBsp_Free(candidate);
                MapGenReach_Free(baseline_walk);
                return MAPGEN_PIPELINE_ERR_CANDIDATE;
            }
        }
    }

    mapgen_reach_t *reach = NULL;
    /* The final walk answers to the same token as the first: a cancel that
       arrives here has to be honoured before the verdict is formed. */
    mapgen_reach_options_t walk;
    memset(&walk, 0, sizeof(walk));
    walk.cancel.asked = request->cancelled;
    walk.cancel.user = request->cancelled_user;
    const mapgen_reach_result_t rr =
        MapGenReach_ExploreWith(candidate, request->reach_budget
                                ? request->reach_budget : 40000u, &walk,
                                &reach);
    if (rr == MAPGEN_REACH_CANCELLED) {
        MapGenReach_Free(reach);
        MapGenReach_Free(baseline_walk);
        return MAPGEN_PIPELINE_CANCELLED;
    }
    if (rr == MAPGEN_REACH_OK && reach) {
        report->reach = *MapGenReach_Report(reach);
        report->measured_reach = true;
    }
    /*
     * And the account of any special traversal it leaned on, stamped with the
     * identity of the artifact that was actually judged. The exploration that
     * writes them is the one whose verdict is used, so the certificates and
     * the verdict cannot describe different runs.
     */
    if (reach) {
        const mapgen_certificate_set_t *found =
            MapGenReach_Certificates(reach);
        if (found)
            report->certificates = *found;
        char physics[65];
        MapGenReach_PhysicsSha256(physics);
        MapGenCertificate_Stamp(&report->certificates,
                                report->compiled.bsp_sha256,
                                report->baseline_bsp, physics);
        /*
         * Now that the map has been judged, give it its light.
         *
         * After, not before: the judgement compares the candidate with the
         * donor, and at fidelity 100 they must be the same map. Compiling
         * the candidate with a different profile than the baseline makes
         * them differ for reasons that have nothing to do with what was
         * built - the pipeline gate caught exactly that.
         *
         * The lit file is then held to the same eight axes against the file
         * that WAS judged. Lighting must change the light and nothing else;
         * if it changes anything structural the lit copy is dropped and the
         * run keeps the map it proved. So nothing is published that was not
         * judged, and nothing judged is quietly replaced.
         */
        if (report->bsp_path[0]) {
            char judged[MAPCOMPILE_MAX_PATH];
            snprintf(judged, sizeof(judged), "%s", report->bsp_path);
            const size_t n = strlen(judged);
            char source[MAPCOMPILE_MAX_PATH];
            snprintf(source, sizeof(source), "%.*s.map",
                     (int)(n > 4 ? n - 4 : n), judged);
            char lit_path[MAPCOMPILE_MAX_PATH];
            snprintf(lit_path, sizeof(lit_path), "%s", judged);
            progress_line("stage=light");
            /* row 404: said either way - an unlit map handed back in silence is how mg_cor reached its gates */
            const char *unlit = "the light compile failed";
            bool sun = false;
            if (light_the_artifact(adapter, request, job_dir, source,
                                   lit_path, sizeof(lit_path), &sun)
                && (!sun || restore_entities(lit_path, judged))) {
                unlit = "the lit compile is not the judged map";
                mapgen_bsp_t *was = load_bsp(judged);
                mapgen_bsp_t *now = load_bsp(lit_path);
                bool same = false;
                if (was && now) {
                    mapgen_equiv_policy_t policy;
                    mapgen_equiv_report_t why2;
                    MapGenEquivalence_DefaultPolicy(&policy);
                    same = MapGenEquivalence_Compare(was, now, &policy,
                                                     &why2)
                           == MAPGEN_EQUIV_OK;
                }
                MapGenBsp_Free(now);
                MapGenBsp_Free(was);
                /*
                 * Over the judged artifact, not beside it.
                 *
                 * Pointing the report at the lit directory made publication
                 * hang at 100%: the receipt, the recipe, the certificates and
                 * every Project member are derived from the artifact's own
                 * path, and moving it somewhere nothing downstream knew about
                 * is a change none of them agreed to. The map keeps its place
                 * and gains its light.
                 */
                if (same && copy_file(lit_path, judged)) {
                    report->compiled.bsp_bytes =
                        hash_artifact(report->bsp_path,
                                      report->compiled.bsp_sha256);
                    /*
                     * The certificates name the map they are about, and the
                     * map now has different bytes. Publication checks that
                     * every record belongs to the file being published and
                     * refused the lot - rightly, since they described a file
                     * that no longer existed.
                     *
                     * Re-named rather than re-earned: the lit file was just
                     * proved equivalent on all eight axes, so what each
                     * certificate claims is as true of it as of the file it
                     * was measured on. Nothing here would be defensible
                     * without that check immediately above.
                     */
                    for (uint32_t c = 0; c < report->certificates.count;
                         c++)
                        snprintf(report->certificates.entries[c].candidate_sha256,
                                 MAPGEN_CERT_SHA_HEX, "%s",
                                 report->compiled.bsp_sha256);
                    unlit = NULL;
                }
            }
            if (unlit)
                progress_line("stage=light lit=0 why=\"%s\"", unlit);
            else
                progress_line("stage=light lit=1 sun=%d", sun ? 1 : 0);
        }
        materialize_base(job_dir, map_name);
        materialize_artifact(report, job_dir);
        write_certificates(report);
    }

    /* The product verdict, always. There is no subset to ask for. */
    bool playable = report->measured_reach
                 && MapGenReach_Passed(&report->reach);
    /* row 400: asked to, on a donor whose own walk fails the absolutes, no worse than the donor */
    if (report->measured_reach && !playable && request->hold_to_donor) {
        /* the donor's walk: the run's own when it has one, else one taken here and let go here */
        const mapgen_reach_t *donor_walk = baseline_walk;
        mapgen_reach_t *own = NULL;
        mapgen_bsp_t *base = NULL;
        if (!donor_walk && baseline[0] && (base = load_bsp(baseline)) != NULL
            && MapGenReach_Explore(base, request->reach_budget ? request->reach_budget : 40000u, &own)
               == MAPGEN_REACH_OK)
            donor_walk = own;
        if (donor_walk && MapGenReach_NoWorseThan(&report->reach, MapGenReach_Report(donor_walk))) {
            playable = true;
            const mapgen_reach_report_t *dr = MapGenReach_Report(donor_walk);
            progress_line("stage=judge held_to_donor=1 stranded=%u donor_stranded=%u stuck=%u donor_stuck=%u",
                          (unsigned)report->reach.spawns_stranded, (unsigned)dr->spawns_stranded,
                          (unsigned)(report->reach.trapped - report->reach.trapped_lethal),
                          (unsigned)(dr->trapped - dr->trapped_lethal));
        }
        MapGenReach_Free(own);
        MapGenBsp_Free(base);
    }
    /* `reach` is kept: the oracle below measures routes from it (D19) */

    if (!report->measured_reach) {
        /*
         * The exploration did not finish - it hit its budget, or the map was
         * larger than the search can hold. That is not the same as a map
         * nobody can play, and telling a caller their candidate is unplayable
         * sends them to the wrong end of it.
         */
        MapGenBsp_Free(candidate);
        MapGenReach_Free(reach);
        MapGenReach_Free(baseline_walk);
        return MAPGEN_PIPELINE_ERR_NOT_MEASURED;
    }
    if (!playable) {
        MapGenBsp_Free(candidate);
        MapGenReach_Free(reach);
        MapGenReach_Free(baseline_walk);
        return MAPGEN_PIPELINE_ERR_UNPLAYABLE;
    }

    /* --- 4: is it a fork ---------------------------------------------------
     *
     * Last, because it is the only gate a candidate can fail by being TOO
     * GOOD a copy, and because measuring it on a map that does not compile or
     * cannot be played would be measuring nothing.
     */
    /*
     * The BASELINE, which is the donor's own geometry through this compiler
     * with nothing applied to it - not the file the donor arrived in.
     *
     * The transaction built it when it opened and every per-edit cost was
     * measured against it; measuring the verdict against something else would
     * be two references for one question. It is also the only way fidelity 100
     * can be exactly zero: a candidate that applied nothing IS this file, and
     * no two compilers agree on how to split a surface or where to put a leaf
     * boundary, so against the donor's own 1997 build a run that changed
     * nothing measured fifty-six permille of q2dm1.
     */
    mapgen_bsp_t *donor = load_bsp(baseline);
    if (!donor) {
        MapGenBsp_Free(candidate);
        MapGenReach_Free(reach);
        MapGenReach_Free(baseline_walk);
        return MAPGEN_PIPELINE_ERR_NOT_MEASURED;
    }

    /*
     * The COMPLETE oracle, routes and all.
     *
     * Expensive - about five minutes on a map the size of q2dm1 - and this is
     * the place to spend it: once per candidate, on the measurement that
     * decides whether anyone is handed the map. The four cheap axes are what
     * the transaction uses per edit, and that is a cost signal rather than a
     * verdict.
     */
    /*
     * D19 (assignment 23): from the walks this run already took, when it took
     * both - the final gate's walk of this very candidate, when it finished at
     * the route axis's own budget, and the baseline's walk the transaction
     * handed over. Otherwise the oracle walks the two files itself, as it
     * always did.
     */
    const uint32_t gate_budget = request->reach_budget ? request->reach_budget
                                                       : 40000u;
    const bool walks_fit = reach && rr == MAPGEN_REACH_OK
                        && gate_budget == 40000u && baseline_walk;
    const mapgen_divergence_result_t measured =
        walks_fit
        ? MapGenDivergence_MeasureWalked(donor, baseline_walk, true, candidate,
                                         reach, true,
                                         (uint32_t)request->generate.fidelity,
                                         &report->divergence)
        : MapGenDivergence_Measure(donor, candidate,
                                   (uint32_t)request->generate.fidelity,
                                   true, &report->divergence);
    report->oracle_from_walks = walks_fit;
    MapGenReach_Free(reach);
    MapGenReach_Free(baseline_walk);
    MapGenBsp_Free(donor);
    MapGenBsp_Free(candidate);

    if (measured != MAPGEN_DIVERGENCE_OK || !report->divergence.complete)
        return MAPGEN_PIPELINE_ERR_NOT_MEASURED;
    report->measured_divergence = true;
    report->reached_permille = report->divergence.aggregate_permille;
    report->missing_permille =
        report->reached_permille < report->divergence.target_permille
        ? report->divergence.target_permille - report->reached_permille : 0;

    /*
     * Out of the band is two failures on opposite sides.
     *
     * Below it, the schedule could not find the difference that was asked for
     * and the report says how much was missing - Codex's
     * VARIATION_TARGET_UNREACHABLE. Above it, the candidate is not a fork of
     * anything. Calling the second one "unreachable", which is what an
     * earlier version did, sends a reader to the wrong end of the problem.
     */
    /*
     * A donor that was asked for and gave nothing.
     *
     * Before the band, because it is an obligation rather than a target:
     * Codex's section 5 requires every selected donor to contribute a major
     * intact bundle "or return a named donor/constraint conflict without
     * publication", and a run that says `q2dm2.bsp gave nothing` and then
     * reports OK has published exactly the omission the phase forbids.
     *
     * `donor_used` already names which, so the caller has the conflict and
     * not merely the refusal.
     */
    for (uint32_t i = 0; i < report->donors_offered
                         && i < MAPGEN_PIPELINE_MAX_DONORS; i++)
        if (!report->donor_used[i])
            return MAPGEN_PIPELINE_ERR_DONOR_OMITTED;

    if (request->diagnostic_no_band)
        return MAPGEN_PIPELINE_DIAGNOSTIC;
    if (!report->divergence.within_band) {
        if (report->divergence.aggregate_permille
            < report->divergence.target_permille)
            return MAPGEN_PIPELINE_ERR_TARGET_UNREACHABLE;
        return MAPGEN_PIPELINE_ERR_CHANGED_TOO_MUCH;
    }
    return MAPGEN_PIPELINE_OK;
}

/* The run, with its progress stream opened before it and its last line - how
   it ended, whatever the path - written after (row 391). */
mapgen_pipeline_result_t MapGenPipeline_Run(const char *donor_bsp,
                                            const char *job_dir,
                                            const char *map_name,
                                            const mapcompile_adapter_t *adapter,
                                            const mapgen_pipeline_request_t *request,
                                            mapgen_pipeline_report_t *report,
                                            mapgen_pipeline_progress_fn progress,
                                            void *progress_user)
{
    mapgen_pipeline_report_t local;
    if (!report)
        report = &local;
    g_progress = NULL;
    g_progress_began = time(NULL);
    g_progress_last[0] = '\0';
    g_progress_attempts = 0;
    if (job_dir && request) {
        char path[MAPCOMPILE_MAX_PATH];
        snprintf(path, sizeof(path), "%s/progress.txt", job_dir);
        g_progress = fopen(path, "w");
        progress_line("stage=start map=%s fidelity=%d seed=%llu target=%u",
                      map_name ? map_name : "-", (int)request->generate.fidelity,
                      (unsigned long long)request->generate.seed,
                      (unsigned)MapGenDivergence_Target((uint32_t)request->generate.fidelity));
    }
    const mapgen_pipeline_result_t rc =
        run_pipeline(donor_bsp, job_dir, map_name, adapter, request, report,
                     progress, progress_user);
    if (job_dir) {
        materialize_base(job_dir, map_name);
        materialize_artifact(report, job_dir);
    }
    /* row 411: what went from program to program in memory, and the most the sections held */
    progress_line("stage=memory-used pipes_mb=%.2f peak_mb=%llu self_written_mb=%.2f",
                  (double)MapGenFs_PipeBytes() / 1048576.0, (unsigned long long)(MapGenFs_PeakBytes() >> 20),
                  (double)MapGenFs_SelfWritten() / 1048576.0);
    /* the map made, last and quoted (a path may hold spaces): MAPGEN Studio
       reads the run's outcome from this line alone */
    progress_line("stage=finish result=%s accepted=%u attempted=%u divergence=%u"
                  " target=%u ended_by=%s compiles=%u budget=%u rounds=%u bsp=\"%s\"", MapGenPipeline_ResultName(rc),
                  (unsigned)report->accepted, (unsigned)report->attempted,
                  (unsigned)report->reached_permille,
                  request ? (unsigned)MapGenDivergence_Target((uint32_t)request->generate.fidelity) : 0u,
                  report->ended_by[0] ? report->ended_by : "-", (unsigned)report->compiles,
                  (unsigned)report->budget, (unsigned)report->rounds,
                  report->compiled_a_map ? report->bsp_path : "");
    if (g_progress) {
        fclose(g_progress);
        g_progress = NULL;
    }
    return rc;
}
