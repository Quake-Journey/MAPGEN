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
#include "common/mapgen_warp.h"
#include "common/mapgen_reach.h"

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

/*
 * Brief 18 D1 (Fable: «the patch size is not left to chance - the retry is the net, not the plan»): what the light
 * tool will make of a map, read from the map's faces BEFORE the first light pass.
 *
 * Patches: the tool halves a face along each axis until no side is longer than the patch size + 1; every face is at
 * least one patch. Counted the same way here - against the tool's own count on three maps of 12.10: 24551 for its
 * 23869 (q2dm3, 64), 12862 for 12839 (the same at 128), 47175 for 45787 (q2dm1 at 150 %, 64): 0..3 % over.
 * The lightmap: a sample every 16 units along the texture's two axes, 3 bytes each, on every face that is neither
 * sky nor warped - 19854822 for the 19839405 bytes q3t2 at 1000 % holds, 661683 for 661683 (q2dm3).
 *
 * `subdiv`: the smallest of 64, 128, 256, 512 that keeps the patches under 60000 (the tool holds 65535).
 * `maxdata`: 0 while the lightmap and a tenth over fit the tool's own 8 MB; else that, rounded up to 16 MB (the
 * client packs lightmaps into 128 blocks of 1024 x 1024 - 128 MB is the cap).
 */
#define LIGHT_PATCHES_WANTED 60000u
static bool g_light_plan = true;        /* RED: the first pass at the tool's defaults, the retries alone */
static mapgen_bsp_t *load_bsp(const char *path);

static bool g_light_again = true;       /* RED: one light pass, whatever the tool said */

void MapGenPipeline_SetLightPlan(bool plan)
{
    g_light_plan = plan;
}

void MapGenPipeline_SetLightAgain(bool again)
{
    g_light_again = again;
}

static void light_plan(const mapgen_bsp_t *bsp, int *subdiv, unsigned long long *maxdata, uint32_t patches_at[4],
                       unsigned long long *lightmap)
{
    static const float sizes[4] = { 64.0f, 128.0f, 256.0f, 512.0f };
    unsigned long long patches[4] = { 0, 0, 0, 0 }, bytes = 0;
    const uint32_t faces = MapGenBsp_NumFaces(bsp), surfedges = MapGenBsp_NumSurfEdges(bsp);
    for (uint32_t f = 0; f < faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        const mapgen_bsp_texinfo_t *tex = face && face->texinfo >= 0
                                        ? MapGenBsp_TexInfo(bsp, (uint32_t)face->texinfo) : NULL;
        if (!face || face->numedges < 3 || face->firstedge < 0
            || (uint32_t)face->firstedge + (uint32_t)face->numedges > surfedges)
            continue;
        float lo[3] = { 1e30f, 1e30f, 1e30f }, hi[3] = { -1e30f, -1e30f, -1e30f };
        float st_lo[2] = { 1e30f, 1e30f }, st_hi[2] = { -1e30f, -1e30f };
        for (int32_t k = 0; k < face->numedges; k++) {
            const int32_t se = MapGenBsp_SurfEdge(bsp, (uint32_t)(face->firstedge + k));
            const mapgen_bsp_edge_t *e = MapGenBsp_Edge(bsp, (uint32_t)(se >= 0 ? se : -se));
            const mapgen_bsp_vertex_t *v = e ? MapGenBsp_Vertex(bsp, e->v[se >= 0 ? 0 : 1]) : NULL;
            if (!v)
                continue;
            for (int a = 0; a < 3; a++) {
                lo[a] = fminf(lo[a], v->point[a]);
                hi[a] = fmaxf(hi[a], v->point[a]);
            }
            for (int a = 0; a < 2 && tex; a++) {
                const float s = v->point[0] * tex->axis[a][0] + v->point[1] * tex->axis[a][1]
                              + v->point[2] * tex->axis[a][2] + tex->axis[a][3];
                st_lo[a] = fminf(st_lo[a], s);
                st_hi[a] = fmaxf(st_hi[a], s);
            }
        }
        if (lo[0] > hi[0])
            continue;
        for (int s = 0; s < 4; s++) {
            unsigned long long n = 1;
            for (int a = 0; a < 3; a++)
                for (float side = hi[a] - lo[a]; side > sizes[s] + 1.0f; side *= 0.5f)
                    n *= 2u;
            patches[s] += n;
        }
        if (tex && !(tex->flags & (0x0004 | 0x0008)) /* neither sky nor warped */ && st_lo[0] <= st_hi[0])
            bytes += 3ull * (unsigned long long)((long long)ceilf(st_hi[0] / 16.0f) - (long long)floorf(st_lo[0] / 16.0f) + 1)
                          * (unsigned long long)((long long)ceilf(st_hi[1] / 16.0f) - (long long)floorf(st_lo[1] / 16.0f) + 1);
    }
    int pick = 3;
    for (int s = 3; s >= 0; s--)
        if (patches[s] <= LIGHT_PATCHES_WANTED)
            pick = s;
    *subdiv = (int)sizes[pick];
    const unsigned long long need = bytes + bytes / 10u;
    *maxdata = need > 8388608ull ? (need + (16ull << 20) - 1) / (16ull << 20) * (16ull << 20) : 0;
    if (*maxdata > 128ull << 20)
        *maxdata = 128ull << 20;
    for (int s = 0; s < 4; s++)
        patches_at[s] = patches[s] > 0xFFFFFFFFull ? 0xFFFFFFFFu : (uint32_t)patches[s];
    *lightmap = bytes;
}

bool MapGenPipeline_LightPlan(const char *bsp_path, int *subdiv, unsigned long long *maxdata, uint32_t patches_at[4],
                              unsigned long long *lightmap)
{
    mapgen_bsp_t *bsp = bsp_path ? load_bsp(bsp_path) : NULL;
    if (!bsp)
        return false;
    light_plan(bsp, subdiv, maxdata, patches_at, lightmap);
    MapGenBsp_Free(bsp);
    return true;
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

    /* brief 18 D1: the patch size and the lightmap's room chosen from the judged map's faces - the map this one is
       compiled from again, beside it under the same name */
    int subdiv = 64;
    unsigned long long maxdata = 0;      /* 0: the stage's own 8 MB */
    if (g_light_plan) {
        char judged[MAPCOMPILE_MAX_PATH];
        const size_t n = strlen(map_path);
        mapgen_bsp_t *faces = n > 4 && snprintf(judged, sizeof(judged), "%.*s.bsp", (int)(n - 4), map_path)
                                       < (int)sizeof(judged) ? load_bsp(judged) : NULL;
        if (faces) {
            uint32_t patches[4];
            unsigned long long lightmap = 0;
            light_plan(faces, &subdiv, &maxdata, patches, &lightmap);
            progress_line("stage=light-plan patches64=%u patches128=%u patches256=%u subdiv=%d lightmap=%llu "
                          "maxdata=%llu", (unsigned)patches[0], (unsigned)patches[1], (unsigned)patches[2], subdiv,
                          lightmap, maxdata ? maxdata : 8388608ull);
            if (subdiv > 64 || maxdata)
                snprintf(creq.rad_flags, sizeof(creq.rad_flags), "%s -subdiv %d -maxdata %llu", request->light_flags,
                         subdiv, maxdata ? maxdata : 8388608ull);
            MapGenBsp_Free(faces);
        }
    }

    mapcompile_report_t lit;
    memset(&lit, 0, sizeof(lit));
    MapCompile_SetTick(light_tick);
    mapcompile_result_t rc = MapCompile_RunProfile(adapter, &creq, &lit);
    /*
     * The PO, 11.10 (mg_10_6695, q3t2 at 1000 %: «снова карта монохромная - значит лайтмапы не отработали»): the
     * light tool stopped at «Exceeded MAX_PATCHES 65535» - a map that large has more light patches of the default
     * 64 across than it can hold - and the map went out unlit. The light pass alone again on the map the visibility
     * has already been worked out for (an hour and a half of it there), its patches twice as large each time (128,
     * 256, 512); what each try said is kept for the log.
     */
    char again_said[4096] = "";
    for (int tries = 0; g_light_again && rc != MAPCOMPILE_OK && tries < 6 && lit.num_stages > 0
                        && lit.stages[lit.num_stages - 1].stage == MAPCOMPILE_STAGE_RAD
                        && lit.stages[lit.num_stages - 1].stdout_captured; tries++) {
        const char *said = lit.stages[lit.num_stages - 1].stdout_captured;
        const char *over = strstr(said, "lightdatasize ");
        unsigned long long need = 0;
        if (strstr(said, "MAX_PATCHES") && subdiv < 512)
            subdiv *= 2;
        else if (over && sscanf(over, "lightdatasize %llu > maxdata", &need) == 1 && need > maxdata
                 && need <= 128ull << 20)
            /* the lightmap the map needs, rounded up to the next 16 MB; the client packs lightmaps into 128 blocks
               of 1024 x 1024 (LM_MAX_LIGHTMAPS), far past it */
            maxdata = (need + (16ull << 20) - 1) / (16ull << 20) * (16ull << 20);
        else
            break;
        snprintf(creq.rad_flags, sizeof(creq.rad_flags), "%s -subdiv %d -maxdata %llu", request->light_flags, subdiv,
                 maxdata ? maxdata : 8388608ull);
        mapcompile_stage_report_t *rad = &lit.stages[lit.num_stages - 1];
        const size_t used = strlen(again_said);
        snprintf(again_said + used, sizeof(again_said) - used, "light pass stopped (exit %d: %s); again with -subdiv %d "
                 "-maxdata %llu\n", (int)rad->exit_code, need ? "the lightmap over maxdata" : "out of patches", subdiv,
                 maxdata ? maxdata : 8388608ull);
        free(rad->stdout_captured);
        memset(rad, 0, sizeof(*rad));
        rad->stage = MAPCOMPILE_STAGE_RAD;
        const mapcompile_result_t rr = adapter->run_stage(adapter->ctx, &creq, MAPCOMPILE_STAGE_RAD, rad);
        if (rr == MAPCOMPILE_OK && rad->exit_code == 0 && !rad->timed_out && !rad->crashed
            && snprintf(lit.bsp_path, sizeof(lit.bsp_path), "%s/%s.bsp", creq.job_dir, creq.map_name)
                   < (int)sizeof(lit.bsp_path)) {
            rc = MAPCOMPILE_OK;
            progress_line("stage=light-again subdiv=%d maxdata=%llu", subdiv, maxdata ? maxdata : 8388608ull);
        }
    }
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
                fprintf(lf, "light compile: %s, %d threads, flags \"%s\"\n%s", MapCompile_ResultName(rc),
                        creq.threads, creq.rad_flags, again_said);
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
                                    ? request->reach_budget : MAPGEN_REACH_BUDGET, &walk,
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

/*
 * Brief 16 D6 (the PO's slider «Быстрее ↔ Точнее» becomes minutes): the edits stop when the run has spent its time
 * but for what the map still needs after them - its finishing swaps, its light and its checks - kept back: four
 * minutes and a thirtieth of the budget. Zero: no time budget, the builds alone bound the run, as before.
 */
static bool time_is_up(const mapgen_pipeline_request_t *request)
{
    if (!request->time_budget_s)
        return false;
    /* the finishing swaps (a minute), the light (a minute and a half on q2dm3) and the map's checks after the engine */
    const long long reserve = 240 + (long long)request->time_budget_s / 30;
    return (long long)(time(NULL) - g_progress_began) + reserve >= (long long)request->time_budget_s;
}
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
    if (step->walk_states && step->walk_changed != UINT32_MAX)      /* brief 16 D5 */
        fprintf(ledger, " inherited %u of the parent's walk, %u brushes changed", step->walk_inherited,
                step->walk_changed);
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
    /*
     * Brief 16: the DRY replay of a finished run (`--replay-dry`) - what the new plan would have done with each row:
     * by the ledger's verdict, the rows the proof refuses before a build, the rows whose site was refused before (the
     * redeal's repeats), and the edits that move no architecture. It stops at the ledger's end.
     */
    bool dry;
    uint32_t rows[MAPGEN_TXN_NUM_VERDICTS], proof_refused[MAPGEN_TXN_NUM_VERDICTS];
    uint32_t repeats[MAPGEN_TXN_NUM_VERDICTS], paint[MAPGEN_TXN_NUM_VERDICTS];
    uint64_t row_ms[MAPGEN_TXN_NUM_VERDICTS], saved_ms;
    uint64_t *refused_print;
    uint32_t num_refused_print, cap_refused_print;
    uint32_t last_divergence;          /* the ledger's divergence after its last accepted row */
} replay_t;

static void replay_free(replay_t *r)
{
    for (uint32_t i = 0; i < r->n; i++)
        free(r->e[i].line);
    free(r->e);
    free(r->refused_print);
    memset(r, 0, sizeof(*r));
}

/*
 * Brief 16 D3: an edit's SITE, as a print - its family, a dig's shape, and its box to eight units (an edit with no box:
 * its target and amount in the family's own list). The same print on a later round is the same edit at the same
 * place, and a verdict already given there is not asked again.
 */
static uint64_t edit_print(const mapgen_geometry_edit_plan_t *plan, uint32_t i, const mapgen_geometry_edit_t *planned)
{
    uint64_t h = 1469598103934665603ull;
#define PRINT_MIX(v) do { const int64_t mix_ = (int64_t)(v); \
        for (int b_ = 0; b_ < 8; b_++) h = (h ^ (uint8_t)(mix_ >> (8 * b_))) * 1099511628211ull; } while (0)
    PRINT_MIX(planned->kind);
    float lo[3], hi[3];
    if (MapGenGeometryEdit_BoxOf(plan, NULL, NULL, i, lo, hi)) {
        for (int a = 0; a < 3; a++) {
            PRINT_MIX(lroundf(lo[a] / 8.0f));
            PRINT_MIX(lroundf(hi[a] / 8.0f));
        }
    } else {
        PRINT_MIX(planned->target);
        PRINT_MIX(planned->amount);
    }
    if (planned->kind == MAPGEN_EDIT_DIG) {
        mapgen_dig_report_t dig;
        if (MapGenGeometryEdit_DigAt(plan, planned->target, &dig))
            for (const char *c = dig.shape; *c; c++)
                PRINT_MIX(*c);
    }
#undef PRINT_MIX
    return h;
}

/*
 * Brief 16 D2: a family that adds nothing the metric counts - the paint, and the liquids swapped (mg_10_6695: 16
 * accepted, 0 permille). Not built while the band is unmet; the finishing pass has them.
 */
static bool zero_gain(mapgen_edit_kind_t kind)
{
    return !MapGenGeometryEdit_MovesArchitecture(kind) || kind == MAPGEN_EDIT_RELIQUID;
}

static bool print_held(const uint64_t *set, uint32_t n, uint64_t print)
{
    for (uint32_t k = 0; k < n; k++)
        if (set[k] == print)
            return true;
    return false;
}

static void print_keep(uint64_t **set, uint32_t *n, uint32_t *cap, uint64_t print)
{
    if (print_held(*set, *n, print))
        return;
    if (*n == *cap) {
        const uint32_t want = *cap ? *cap * 2u : 256u;
        uint64_t *grown = realloc(*set, want * sizeof(*grown));
        if (!grown)
            return;
        *set = grown;
        *cap = want;
    }
    (*set)[(*n)++] = print;
}


/*
 * Brief 16 D2 (the PO, 10.10: «оценка того, что можно изменить на карте не качественная»): the plan's WORD, before its
 * first build, and the order its edits are built in.
 *
 * Every edit of the plan as dealt is applied to a clone of the accepted map and proved; a proved one is worth the
 * lattice cells it changes (`MapGenTransaction_ProvePlan`). The edits are then built most valuable first - a dig is
 * worth fifty windows - and the plan says what it can give at most with the builds left: the best of its proved,
 * untried edits, one build each, on top of what is already accepted. A dry replay keeps the ledger's own order.
 */
typedef struct {
    uint32_t value;            /* tenths of a permille */
    uint32_t index;
    uint32_t place;            /* the value its turn is taken by: `value`, or a failed trial build's own estimate */
} ranked_t;

static int ranked_order(const void *a, const void *b)
{
    const ranked_t *x = a, *y = b;
    if (x->value != y->value)
        return x->value > y->value ? -1 : 1;
    return x->index < y->index ? -1 : x->index > y->index ? 1 : 0;
}

static int ranked_place(const void *a, const void *b)
{
    const ranked_t *x = a, *y = b;
    if (x->place != y->place)
        return x->place > y->place ? -1 : 1;
    return x->index < y->index ? -1 : x->index > y->index ? 1 : 0;
}

static int key_order(const void *a, const void *b)
{
    const uint64_t x = *(const uint64_t *)a & ~(1ull << 63), y = *(const uint64_t *)b & ~(1ull << 63);
    return x < y ? -1 : x > y ? 1 : 0;
}

/*
 * Brief 17 D5: the cells a set of edits changes, each counted once - two digs under one sky lift, a window in a wall a
 * reshape moves, change many of the same cells, and the sum said 89 % on warped q2dm1 where the run reached far less.
 * `changed` gets the distinct cells, `added` those of them new to the metric's count (by any of the edits).
 */
static void plan_union(const mapgen_plan_value_t *v, const ranked_t *ranked, uint32_t chosen, uint32_t *changed,
                       uint32_t *added)
{
    *changed = *added = 0;
    uint32_t total = 0;
    for (uint32_t k = 0; k < chosen; k++)
        total += v->key_count[ranked[k].index];
    if (!total || !v->keys)
        return;
    uint64_t *all = malloc((size_t)total * sizeof(*all));
    if (!all)
        return;
    uint32_t m = 0;
    for (uint32_t k = 0; k < chosen; k++) {
        const uint32_t i = ranked[k].index;
        memcpy(all + m, v->keys + v->key_first[i], (size_t)v->key_count[i] * sizeof(*all));
        m += v->key_count[i];
    }
    qsort(all, m, sizeof(*all), key_order);
    for (uint32_t i = 0; i < m;) {
        uint32_t j = i;
        bool joins = false;
        while (j < m && key_order(&all[i], &all[j]) == 0) {
            if (all[j] >> 63)
                joins = true;
            j++;
        }
        (*changed)++;
        if (joins)
            (*added)++;
        i = j;
    }
    free(all);
}

static const bool g_plan_word_union = true;     /* brief 17 D5: the RED's mutation point */
static const bool g_plan_word_measured = true;  /* brief 18: the word held to its trial builds' count; a RED's too */
/* brief 17 D5: a dig worth this much (tenths of a permille) is built dry before the word counts it */
#define PLAN_DRY_BUILD_TENTHS 100u
#define PLAN_DRY_SAY_TENTHS 3000u       /* ... and one worth more than a third of this is said with its re-measure */
static const bool g_plan_dry_build = true;      /* the RED's mutation point */

/* Brief 16 D3: a proved, untried edit worth at least half a permille - what a new deal has to offer to go on. */
#define PLAN_WORTH_TENTHS 5u

static uint32_t *plan_order(mapgen_transaction_t *txn, const mapgen_pipeline_request_t *request, uint32_t round,
                            uint32_t target, uint32_t builds_left, const uint64_t *tried, uint32_t num_tried,
                            bool dry, uint32_t *worthy)
{
    *worthy = 0;
    const mapgen_geometry_edit_plan_t *plan = MapGenTransaction_Plan(txn);
    const uint32_t n = MapGenGeometryEdit_Count(plan);
    uint32_t *order = malloc((n ? n : 1u) * sizeof(*order));
    ranked_t *ranked = calloc(n ? n : 1u, sizeof(*ranked));
    if (!order || !ranked) {
        free(order);
        free(ranked);
        return NULL;
    }
    for (uint32_t i = 0; i < n; i++)
        order[i] = i;
    mapgen_plan_value_t v;
    if (!MapGenTransaction_ProvePlan(txn, &v)) {
        free(ranked);
        return order;
    }
    uint32_t builds = 0, tenths = 0, worth = 0, large = 0;
    uint64_t tried_est = 0, tried_true = 0;     /* the trial builds that built: their cells estimated, and measured */
    for (uint32_t i = 0; i < n; i++) {
        const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
        /* brief 16 D4: the large families - a room dug or built, a passage, a storey, a bridge - proved before a build */
        if (e && v.state[i] == MAPGEN_PLAN_EDIT_PROVED && (e->kind == MAPGEN_EDIT_DIG || e->kind == MAPGEN_EDIT_SPAN))
            large++;
        bool counts = e && v.state[i] == MAPGEN_PLAN_EDIT_PROVED && !family_skipped(request, e->kind)
                   && !(target > 0 && zero_gain(e->kind))
                   && !print_held(tried, num_tried, edit_print(plan, i, e));
        /*
         * Brief 17 D5: the estimate counts only an edit the run would build - a large dig is built dry first and asked
         * what its compile alone answers. On warped q2dm1 6675 the annex from 1424 1968 768, worth 5.4 points of
         * the word, opened high into the old map on every build (REJECTED_OPEN_HIGH) and the word said 75 % where
         * the run reached 65 %. Refused here, it is worth nothing to the word and built last.
         *
         * Brief 18: but a dig whose trial build FAILED keeps its turn by its value - the failure is of this map alone
         * (MapGenTransaction_DryFailedAgain), and its site is whole now: mg_b18_q2dm3's tunnel and lift, second of
         * the plan by value, was accepted right after the storey room on 12.10; put last, it would wait for 27
         * smaller edits to build about its site.
         */
        bool again = false;
        if (counts && g_plan_dry_build && e->kind == MAPGEN_EDIT_DIG && v.value[i] >= PLAN_DRY_BUILD_TENTHS) {
            char why[200];
            uint32_t true_cells = 0;
            const bool builds_dry = MapGenTransaction_PlanDryBuild(txn, i, why, sizeof(why), &true_cells);
            /* the estimate re-measured (`true_cells`) is said, not used: the metric's own count of one compiled edit
               is not the share it adds to the others' union - scaled by it, warped q2dm1's word rose to 74.7 % where
               the run reached 66.4 */
            if (builds_dry && true_cells && v.cells[i]) {
                tried_est += v.cells[i];
                tried_true += true_cells;
            }
            if (builds_dry && true_cells && v.cells[i] && 3u * v.value[i] > PLAN_DRY_SAY_TENTHS)
                progress_line("stage=plan-dry edit=%u family=%s value=%.1f cells=%u true=%u", (unsigned)i,
                              MapGenGeometryEdit_KindName(e->kind), (double)v.value[i] / 10.0, (unsigned)v.cells[i],
                              (unsigned)true_cells);
            if (!builds_dry) {
                counts = false;
                again = MapGenTransaction_DryFailedAgain(txn, i);
                progress_line("stage=plan-dry edit=%u family=%s value=%.1f why=\"%s\"", (unsigned)i,
                              MapGenGeometryEdit_KindName(e->kind), (double)v.value[i] / 10.0, why);
            }
        }
        ranked[i].index = i;
        ranked[i].value = counts ? v.value[i] : 0u;
        ranked[i].place = counts || again ? v.value[i] : 0u;
        if (counts)
            worth++;
        if (counts && v.value[i] >= PLAN_WORTH_TENTHS) {
            (*worthy)++;
            /* a later deal's new worthy edits, by name - what keeps the edits going */
            if (round || dry)
                progress_line("stage=plan-worthy round=%u edit=%u family=%s value=%.1f", (unsigned)round, (unsigned)i,
                              MapGenGeometryEdit_KindName(e->kind), (double)v.value[i] / 10.0);
        }
    }
    qsort(ranked, n, sizeof(*ranked), ranked_order);
    uint64_t sum_cells = v.base_changed, sum_all = v.base_cells;
    for (uint32_t k = 0; k < n; k++) {
        if (k < worth && builds < builds_left) {
            builds++;
            tenths += ranked[k].value;
            sum_cells += v.cells[ranked[k].index];
            sum_all += v.added[ranked[k].index];
        }
    }
    /* brief 17 D5: each cell once */
    uint32_t sum_cells_summed = (uint32_t)sum_cells, union_changed = 0, union_added = 0;
    plan_union(&v, ranked, builds, &union_changed, &union_added);
    /*
     * Brief 18 (mg_b18_q2dm1 on 3.31: the word 64.6 %, the run 57.4 - and 94 % of the word's worth was ACCEPTED): the
     * estimate itself counts more cells than the metric does. Its two digs built on trial measured 34116 cells for
     * 39294 estimated and 5739 for 6434 - 0.87 - and the run's whole count came to 0.82 of the plan's. So the word
     * says no more than its own trial builds measured: the union's cells in the measure of theirs, when that is
     * less (q2dm3 at 150 %: 0.92; its reference: 1.03, left as estimated - two builds are no ground to promise more).
     */
    if (g_plan_word_measured && tried_est && tried_true < tried_est) {
        union_changed = (uint32_t)((uint64_t)union_changed * tried_true / tried_est);
        union_added = (uint32_t)((uint64_t)union_added * tried_true / tried_est);
        if (!(g_plan_word_union && v.keys)) {
            sum_cells = (uint64_t)v.base_changed + (sum_cells - v.base_changed) * tried_true / tried_est;
            sum_all = (uint64_t)v.base_cells + (sum_all - v.base_cells) * tried_true / tried_est;
        }
    }
    if (g_plan_word_union && v.keys) {
        sum_cells = (uint64_t)v.base_changed + union_changed;
        sum_all = (uint64_t)v.base_cells + union_added;
    }
    /* as the metric counts: the cells changed of the cells it counts, new architecture joining both */
    const uint32_t have = MapGenTransaction_Divergence(txn);
    uint32_t can = sum_all ? (uint32_t)((1000ull * sum_cells + sum_all / 2u) / sum_all) : have + (tenths + 5u) / 10u;
    if (can < have)
        can = have;
    if (can > 1000u)
        can = 1000u;
    progress_line("stage=plan-value round=%u proved=%u worthy=%u declined=%u refused=%u builds=%u can=%u have=%u"
                  " target=%u large=%u ms=%u cells=%u summed=%u tried=%llu/%llu", (unsigned)round, (unsigned)worth,
                  (unsigned)*worthy, (unsigned)v.declined, (unsigned)v.refused, (unsigned)builds, (unsigned)can,
                  (unsigned)have, (unsigned)target, (unsigned)large, (unsigned)v.ms, (unsigned)union_changed,
                  (unsigned)sum_cells_summed, (unsigned long long)tried_true, (unsigned long long)tried_est);
    /* the turns, by place - after the word, which is said of the counted edits alone; the first of them said */
    qsort(ranked, n, sizeof(*ranked), ranked_place);
    {
        char first[96] = "";
        size_t at = 0;
        for (uint32_t k = 0; k < n && k < 8u && at + 12u < sizeof(first); k++)
            at += (size_t)snprintf(first + at, sizeof(first) - at, k ? ",%u" : "%u", (unsigned)ranked[k].index);
        progress_line("stage=plan-turns round=%u first=%s", (unsigned)round, first);
    }
    if (!dry)                           /* a dry replay keeps the ledger's order; the word is said all the same */
        for (uint32_t k = 0; k < n; k++)
            order[k] = ranked[k].index;
    MapGenTransaction_PlanValueFree(&v);
    free(ranked);
    return order;
}

/*
 * Brief 16 D0: the LADDER, counted - where each edit was answered, cheapest first: the operator declining (no build),
 * its proof refusing it (no build), a site tried before (not offered again), a family the metric does not count
 * (kept for the finishing pass); and what was built - walked whole, or from its parent's walk. The ledger and the
 * Studio say it, so the PO sees where the time went.
 */
typedef struct {
    uint32_t not_applied, proved, tried, paint, builds, whole, taken;
} ladder_t;

static void ladder_count(ladder_t *l, mapgen_transaction_verdict_t verdict, const mapgen_transaction_step_t *step)
{
    if (verdict == MAPGEN_TXN_REJECTED_NOT_APPLIED)
        l->not_applied++;
    else if (step->proved_refusal)
        l->proved++;
    else
        l->builds++;
    if (step->walk_states && step->walk_changed == UINT32_MAX)
        l->whole++;
    else if (step->walk_states)
        l->taken++;
}

/* Brief 16: the dry replay's account of one row, and of the whole ledger at its end */
static void dry_row(replay_t *r, const mapgen_geometry_edit_plan_t *plan, uint32_t i,
                    const mapgen_geometry_edit_t *planned, mapgen_transaction_verdict_t was,
                    const mapgen_transaction_step_t *step, const char *line, uint32_t divergence)
{
    /* the worth the run measured for an accepted row, beside the worth estimated before its build (D2) */
    const int32_t delta = was == MAPGEN_TXN_ACCEPTED ? (int32_t)divergence - (int32_t)r->last_divergence : 0;
    if (was == MAPGEN_TXN_ACCEPTED)
        r->last_divergence = divergence;
    if ((unsigned)was >= MAPGEN_TXN_NUM_VERDICTS)
        return;
    uint32_t ms = 0;
    const char *m = strstr(line, "  ms ");
    if (m)
        ms = (uint32_t)strtoul(m + 5, NULL, 10);
    r->rows[was]++;
    r->row_ms[was] += ms;
    const uint64_t print = edit_print(plan, i, planned);
    const bool repeat = was != MAPGEN_TXN_ACCEPTED && print_held(r->refused_print, r->num_refused_print, print);
    const bool paint = zero_gain(planned->kind);
    const bool refused = step->observed && step->observed_verdict != MAPGEN_TXN_ACCEPTED;
    if (repeat)
        r->repeats[was]++;
    if (paint)
        r->paint[was]++;
    if (refused)
        r->proof_refused[was]++;
    if (was != MAPGEN_TXN_ACCEPTED && was != MAPGEN_TXN_REJECTED_NOT_APPLIED && (repeat || paint || refused))
        r->saved_ms += ms;
    if (was != MAPGEN_TXN_ACCEPTED)
        print_keep(&r->refused_print, &r->num_refused_print, &r->cap_refused_print, print);
    if (was == MAPGEN_TXN_ACCEPTED)
        progress_line("stage=dry-cells edit=%u family=%s est=%u true=%u solid=%u surface=%u vertical=%u motif=%u",
                      (unsigned)i, MapGenGeometryEdit_KindName(planned->kind), (unsigned)step->observed_cells,
                      (unsigned)step->observed_true[0], (unsigned)step->observed_true[1],
                      (unsigned)step->observed_true[2], (unsigned)step->observed_true[3],
                      (unsigned)step->observed_true[4]);
    progress_line("stage=dry-row edit=%u family=%s was=%s proof=%s repeat=%d paint=%d ms=%u value=%.1f delta=%d"
                  " why=\"%s\"",
                  (unsigned)i, MapGenGeometryEdit_KindName(planned->kind), MapGenTransaction_VerdictName(was),
                  !step->observed ? "-" : refused ? MapGenTransaction_VerdictName((mapgen_transaction_verdict_t)
                                                                                  step->observed_verdict)
                                              : "passed",
                  repeat ? 1 : 0, paint ? 1 : 0, (unsigned)ms, (double)step->observed_value / 10.0, (int)delta,
                  refused ? step->observed_why : "");
}

static void dry_summary(const replay_t *r)
{
    for (int v = 0; v < (int)MAPGEN_TXN_NUM_VERDICTS; v++)
        if (r->rows[v])
            progress_line("stage=dry-verdict verdict=%s rows=%u seconds=%.0f proof_refused=%u repeats=%u paint=%u",
                          MapGenTransaction_VerdictName((mapgen_transaction_verdict_t)v), (unsigned)r->rows[v],
                          (double)r->row_ms[v] / 1000.0, (unsigned)r->proof_refused[v], (unsigned)r->repeats[v],
                          (unsigned)r->paint[v]);
    const mapgen_transaction_verdict_t costly[3] = { MAPGEN_TXN_REJECTED_NO_EFFECT, MAPGEN_TXN_REJECTED_UNPLAYABLE,
                                                     MAPGEN_TXN_REJECTED_BURIED_ROUTE };
    uint32_t total = 0;
    for (int k = 0; k < 3; k++)
        total += r->rows[costly[k]];
    progress_line("stage=dry-summary rows=%u costly=%u accepted=%u accepted_refused_by_proof=%u saved_seconds=%.0f",
                  (unsigned)r->n, (unsigned)total, (unsigned)r->rows[MAPGEN_TXN_ACCEPTED],
                  (unsigned)r->proof_refused[MAPGEN_TXN_ACCEPTED], (double)r->saved_ms / 1000.0);
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
        /* brief 16 D1: a refusal its proof gave cost no build then, and costs none now */
        step->proved_refusal = strstr(e->line, "(proved before the build)") != NULL;
        if (r->dry)
            dry_row(r, MapGenTransaction_Plan(txn), i, planned, was, step, e->line, e->divergence);
        if (r->dry && step->judged)
            progress_line("stage=dry-judged edit=%u family=%s verdict=%s ms=%u compile=%u reach=%u simulated=%u"
                          " reused=%u inherited=%u changed=%u refused=%u divergence=%u ledger=%u", (unsigned)i,
                          MapGenGeometryEdit_KindName(planned->kind), MapGenTransaction_VerdictName(*verdict),
                          (unsigned)step->total_ms, (unsigned)step->compile_ms, (unsigned)step->reach_ms,
                          (unsigned)step->walk_simulated, (unsigned)step->walk_reused, (unsigned)step->walk_inherited,
                          (unsigned)step->walk_changed, (unsigned)step->walk_refused, (unsigned)step->divergence_after,
                          (unsigned)e->divergence);
        /* brief 17 D5: a dry replay measures; a row the plan now deals otherwise (a window whose kind was the draw's
           in an older run and is the plan's now) is said and gone past, not the end of the measurement */
        if (r->dry && *verdict != was && was != MAPGEN_TXN_ACCEPTED) {
            progress_line("stage=dry-skip edit=%u family=%s was=%s now=%s why=\"%s\"", (unsigned)i,
                          MapGenGeometryEdit_KindName(planned->kind), e->verdict, MapGenTransaction_VerdictName(*verdict),
                          r->why);
            r->why[0] = '\0';
            *verdict = was;
        }
        if (r->dry && *verdict != was && was == MAPGEN_TXN_ACCEPTED
            && (*verdict == MAPGEN_TXN_REJECTED_NOT_APPLIED
                || (*verdict == MAPGEN_TXN_REJECTED_WRITE && strstr(r->why, "the operator declined")))) {
            progress_line("stage=dry-skip edit=%u family=%s was=%s now=%s why=\"%s\"", (unsigned)i,
                          MapGenGeometryEdit_KindName(planned->kind), e->verdict, MapGenTransaction_VerdictName(*verdict),
                          r->why);
            r->why[0] = '\0';
            r->at++;
            *replayed = true;
            if (r->at == r->n) {
                dry_summary(r);
                r->diverged = true;
                snprintf(r->why, sizeof(r->why), "the dry replay is over: %u rows measured", (unsigned)r->n);
            }
            return true;
        }
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
        if (r->dry && r->at == r->n) {
            /* brief 16: the dry replay ends with the ledger's last row, and says what it measured */
            dry_summary(r);
            r->diverged = true;
            snprintf(r->why, sizeof(r->why), "the dry replay is over: %u rows measured", (unsigned)r->n);
        }
        return true;
    }
    if (r && r->dry && r->n) {
        /* brief 16: the dry replay ends with the ledger, and says what it measured */
        dry_summary(r);
        r->diverged = true;
        snprintf(r->why, sizeof(r->why), "the dry replay is over: %u rows measured", (unsigned)r->n);
        return false;
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
    /* brief 11 step 1: where each carried room came from, every round's (plan.txt is the last round's alone): the
       light gate and the room light judge a copy against its original */
    snprintf(path, sizeof(path), "%s/sources.txt", job_dir);
    FILE *s = fopen(path, round ? "a" : "w");
    if (!s)
        return;
    for (uint32_t i = 0; i < MapGenGeometryEdit_NumRefusals(plan); i++) {
        const char *line = MapGenGeometryEdit_Refusal(plan, i);
        if (line && !strncmp(line, "dig room-of source:", 19))
            fprintf(s, "  %s\n", line);
    }
    fclose(s);
    /* brief 13 W7: which liquid each flood was dealt with, and the kinds' account - the map's description names them
       (the PO on mg_1_6662: lava and slime asked, water seen) */
    snprintf(path, sizeof(path), "%s/liquids.txt", job_dir);
    FILE *q = fopen(path, round ? "a" : "w");
    if (!q)
        return;
    for (uint32_t i = 0; i < MapGenGeometryEdit_NumRefusals(plan); i++) {
        const char *line = MapGenGeometryEdit_Refusal(plan, i);
        if (line && (!strncmp(line, "flood offered:", 14) || !strncmp(line, "floods by kind:", 15)))
            fprintf(q, "  %s\n", line);
    }
    fclose(q);
    /* brief 15 D3: what each family was asked and dealt, and why not more - the map's description says it in words */
    snprintf(path, sizeof(path), "%s/plan_said.txt", job_dir);
    FILE *w = fopen(path, round ? "a" : "w");
    if (!w)
        return;
    fprintf(w, "# round %u\n", (unsigned)round);
    static const char *const KEEP[] = { "dig annexes:", "dig storeys dealt:", "dig storeys pairs refused:", "spans:",
                                        "spans refused:", "stairways:", "remodels:", "remodels refused:", "blocks:",
                                        "blocks refused:", "floor-shifts:", "floor-shifts refused:", "stair-reshapes:",
                                        "reshaping families dropped", "floods by kind:" };
    for (uint32_t i = 0; i < MapGenGeometryEdit_NumRefusals(plan); i++) {
        const char *line = MapGenGeometryEdit_Refusal(plan, i);
        for (size_t k = 0; line && k < sizeof(KEEP) / sizeof(KEEP[0]); k++)
            if (!strncmp(line, KEEP[k], strlen(KEEP[k]))) {
                fprintf(w, "%s\n", line);
                break;
            }
    }
    fclose(w);
    /* brief 18 (mg_b18_q2dm3): every round's dealt digs as the plan listing prints them - the delivery gates re-deal
       the first round alone, and an annex, a storey or a stairway a later round dealt and the ledger accepted was
       never asked (two of its three annexes; a first-round stairway matched to a later one's box) */
    snprintf(path, sizeof(path), "%s/plan_rounds.txt", job_dir);
    FILE *pr = fopen(path, round ? "a" : "w");
    if (!pr)
        return;
    fprintf(pr, "# round %u\n", (unsigned)round);
    static const char *const DEALT[] = { "dig offered:", "dig hall:", "dig annex", "dig storeys", "stairway " };
    for (uint32_t i = 0; i < MapGenGeometryEdit_NumRefusals(plan); i++) {
        const char *line = MapGenGeometryEdit_Refusal(plan, i);
        for (size_t k = 0; line && k < sizeof(DEALT) / sizeof(DEALT[0]); k++)
            if (!strncmp(line, DEALT[k], strlen(DEALT[k]))) {
                fprintf(pr, "  %s\n", line);
                break;
            }
    }
    /* and each flood's footprint, its shore and slab with it - they stand outside its box (the ledger's), and the
       digwalls gate laid a flood's shore over q3t2's pit to the dig whose box held it */
    for (uint32_t i = 0; i < MapGenGeometryEdit_Count(plan); i++) {
        float blo[3], bhi[3], flo[3], fhi[3];
        if (MapGenGeometryEdit_BoxOf(plan, NULL, NULL, i, blo, bhi)
            && MapGenGeometryEdit_FloodFootprint(plan, i, flo, fhi))
            fprintf(pr, "  flood footprint: %.0f %.0f %.0f %.0f %.0f %.0f -> %.0f %.0f %.0f %.0f %.0f %.0f\n",
                    (double)blo[0], (double)blo[1], (double)blo[2], (double)bhi[0], (double)bhi[1], (double)bhi[2],
                    (double)flo[0], (double)flo[1], (double)flo[2], (double)fhi[0], (double)fhi[1], (double)fhi[2]);
    }
    fclose(pr);
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
    /* brief 18 D1: a frame grown 10 times its area grows the map and its lightmap with it (the PO's q3t2 at 1000 %:
       the lit file 7 MB of map and 17.7 MB of light) - the room grows with the size asked */
    if (request->warp_size > 100u)
        room = room * request->warp_size / 100u;
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

/*
 * THE WARP, before the first edit (the PO, 10.10: «нужно чтобы генератор делал анализ до начала работ и не тратил время
 * на бесконечные тесты»): the donor's plan stretched part by part (mapgen_warp.h), built once and walked once. A map
 * the walk refuses - a corridor squeezed shut, a jump stretched past a player's reach - is planned again with half
 * the spread, then with half the size's change, at most four times; when none walks, the donor goes as it is and the
 * run says so. The warped base is then the base: everything after measures from it.
 */
/* One warped map: built into `dir`, walked once, held to the absolutes or - a donor that fails them itself - to its
   own walk (`*donor_walk`, walked the first time it is needed). Says the try; the walk is kept in `*kept` when the map
   is playable (the ceilings' line is read from it). */
/* Brief 18 D2: what the walk of a try says FIRST, with its numbers and its place - «the donor passes on its own»
   named no cause, and q3t2's taller tries (x3.11, x2.48) stayed untraced through four runs. */
static void walk_says(const mapgen_reach_report_t *r, char *why, size_t cap)
{
    switch (MapGenReach_FirstFailure(r)) {
    case MAPGEN_REACH_FAILS_SPAWNS:
        snprintf(why, cap, "no start in the map");
        break;
    case MAPGEN_REACH_FAILS_STRANDED:
        snprintf(why, cap, "%u of %u starts cannot reach the others", (unsigned)r->spawns_stranded,
                 (unsigned)r->spawns);
        break;
    case MAPGEN_REACH_FAILS_TRAPPED:
        snprintf(why, cap, "%u places with no way back (and %u that kill), the worst at %.0f %.0f %.0f",
                 (unsigned)(r->trapped - r->trapped_lethal), (unsigned)r->trapped_lethal, (double)r->worst_trap[0],
                 (double)r->worst_trap[1], (double)r->worst_trap[2]);
        break;
    case MAPGEN_REACH_FAILS_ITEMS:
        snprintf(why, cap, "%u pickups out of reach, the worst at %.0f %.0f %.0f", (unsigned)r->items_unreachable,
                 (double)r->worst_item[0], (double)r->worst_item[1], (double)r->worst_item[2]);
        break;
    case MAPGEN_REACH_FAILS_LANDMARKS:
        snprintf(why, cap, "%u landmarks out of reach, the worst at %.0f %.0f %.0f",
                 (unsigned)r->landmarks_unreachable, (double)r->worst_landmark[0], (double)r->worst_landmark[1],
                 (double)r->worst_landmark[2]);
        break;
    case MAPGEN_REACH_FAILS_MOVERS:
        snprintf(why, cap, "%u machines nothing in the map can operate", (unsigned)r->movers_inoperable);
        break;
    default:
        break;
    }
}

static bool warp_try(const mapgen_geometry_t *geometry, const mapgen_bsp_t *donor, mapgen_reach_t **donor_walk,
                     const mapgen_warp_t *w, const char *dir, const char *map_name, const char *moddir,
                     const mapcompile_adapter_t *adapter, const mapgen_pipeline_request_t *request, uint32_t attempt,
                     uint32_t size, uint32_t shape, char path[MAPCOMPILE_MAX_PATH], mapgen_reach_t **kept)
{
    *kept = NULL;
    char said[256];
    MapGenWarp_Describe(w, said, sizeof(said));
    /* brief 18 D2: a map grown tall gets its ramps - in a copy of the donor, before the warp */
    mapgen_geometry_t *ramped = NULL;
    uint32_t ramps = 0;
    if (w->tall > 1.01f && MapGenGeometry_Clone(geometry, &ramped) == MAPGEN_GEOMETRY_OK) {
        ramps = MapGenWarp_AddRamps(ramped, donor, w);
        const uint32_t drops = MapGenWarp_KeepDrops(ramped, donor, w);
        progress_line("stage=warp-ramps try=%u tall=%.2f ramps=%u drops=%u", (unsigned)attempt, (double)w->tall,
                      (unsigned)ramps, (unsigned)drops);
    }
    /*
     * The Studio's picture of the frame (the PO, 11.10: «когда деформация тоже отображать как то наглядно, карта то
     * 3D»): each part's edges in the donor and where they land, the leans and the turn - the Studio draws the donor
     * stretching into this try's frame while it is built and walked.
     */
    {
        char axes[5][192];
        for (int a = 0; a < 5; a++) {
            size_t used = 0;
            axes[a][0] = '\0';
            const int ax = a < 3 ? a : a - 3;
            const uint32_t n = w->num[ax];
            for (uint32_t i = 0; n && i <= n && used + 28 < sizeof(axes[a]); i++)
                used += (size_t)snprintf(axes[a] + used, sizeof(axes[a]) - used, "%s%.0f:%.0f", i ? "," : "",
                                         (double)w->at[ax][i], (double)(a < 3 ? w->to[ax][i] : w->lean[ax][i]));
        }
        progress_line("stage=warp-map try=%u x=\"%s\" y=\"%s\" z=\"%s\" lean_x=\"%s\" lean_y=\"%s\" turns=%u mirror=%d",
                      (unsigned)attempt, axes[0], axes[1], axes[2], axes[3], axes[4], (unsigned)w->turns,
                      w->mirror ? 1 : 0);
    }
    mapgen_geometry_t *warped = NULL;
    path[0] = '\0';
    MapGenFs_EmptyDir(dir);
    const clock_t built_at = clock();
    const bool built = MapGenWarp_Apply(ramped ? ramped : geometry, w, &warped) == MAPGEN_GEOMETRY_OK
                    && MapGenTransaction_CompileGeometry(warped, dir, map_name, moddir, adapter, path);
    const uint32_t build_ms = (uint32_t)((clock() - built_at) * 1000 / CLOCKS_PER_SEC);
    MapGenGeometry_Free(warped);
    MapGenGeometry_Free(ramped);
    mapgen_bsp_t *bsp = built ? load_bsp(path) : NULL;
    {
        /* brief 18, a diagnostic: MAPGEN_WARP_KEEP=<folder> keeps every try's compiled map (try_<n>_tall<x100>.bsp) -
           q3t2's one trapped place at x3.11 was read from these */
        const char *keep = getenv("MAPGEN_WARP_KEEP");
        uint8_t *raw = NULL;
        size_t n = 0;
        char to[MAPCOMPILE_MAX_PATH];
        FILE *f = NULL;
        if (keep && keep[0] && built && MapGenFs_Read(path, &raw, &n) && n
            && snprintf(to, sizeof(to), "%s/try_%u_tall%u_h%u.bsp", keep, (unsigned)attempt,
                        (unsigned)(w->tall * 100.0f + 0.5f), (unsigned)w->height_pct) < (int)sizeof(to)
            && (f = fopen(to, "wb")) != NULL) {
            fwrite(raw, 1, n, f);
            fclose(f);
        }
        free(raw);
    }
    mapgen_reach_t *walk = NULL;
    char why[200] = "";
    bool playable = false;
    uint32_t places = 0, items = 0, items_out = 0, spawns = 0, stranded = 0;
    const clock_t walked_at = clock();
    if (bsp) {
        mapgen_reach_options_t o;
        memset(&o, 0, sizeof(o));
        o.cancel.asked = request->cancelled;
        o.cancel.user = request->cancelled_user;
        const mapgen_reach_result_t rr = MapGenReach_ExploreWith(bsp, MAPGEN_REACH_BUDGET, &o, &walk);
        if (rr == MAPGEN_REACH_OK && walk) {
            const mapgen_reach_report_t *r = MapGenReach_Report(walk);
            playable = MapGenReach_Passed(r);
            places = r->reachable;
            items = r->items;
            items_out = r->items_unreachable;
            spawns = r->spawns;
            stranded = r->spawns_stranded;
            if (!playable) {
                if (!*donor_walk) {
                    mapgen_reach_options_t d;
                    memset(&d, 0, sizeof(d));
                    MapGenReach_ExploreWith(donor, MAPGEN_REACH_BUDGET, &d, donor_walk);
                }
                playable = *donor_walk && MapGenReach_NoWorseThanWhy(r, MapGenReach_Report(*donor_walk), why,
                                                                     sizeof(why));
                if (!playable && *donor_walk && MapGenReach_Passed(MapGenReach_Report(*donor_walk)))
                    walk_says(r, why, sizeof(why));     /* the donor passes: this try's own first failure */
            }
        } else {
            snprintf(why, sizeof(why), "the walk did not finish: %s, %u places", MapGenReach_ResultName(rr),
                     walk ? (unsigned)MapGenReach_NumStates(walk) : 0u);
        }
    } else {
        snprintf(why, sizeof(why), "%s", built ? "the build could not be read"
                                               : MapGenTransaction_LastBaselineCompileWhy());
    }
    const uint32_t walk_ms = (uint32_t)((clock() - walked_at) * 1000 / CLOCKS_PER_SEC);
    for (char *c = why; *c; c++)
        if (*c == '"' || *c == '\n' || *c == '\r')
            *c = '\'';
    progress_line("stage=warp try=%u size=%u shape=%u area=%u parts=\"%s\" built=%d playable=%d places=%u "
                  "pickups=%u pickups_out=%u starts=%u stranded=%u build_ms=%u walk_ms=%u why=\"%s\"",
                  (unsigned)attempt, (unsigned)size, (unsigned)shape, (unsigned)w->area_permille, said, built ? 1 : 0,
                  playable ? 1 : 0, (unsigned)places, (unsigned)items, (unsigned)items_out, (unsigned)spawns,
                  (unsigned)stranded, (unsigned)build_ms, (unsigned)walk_ms, why);
    MapGenBsp_Free(bsp);
    if (playable)
        *kept = walk;
    else
        MapGenReach_Free(walk);
    return playable;
}

/*
 * The ceilings' line of a warped map: above the highest place its walk stands on and the highest pickup or start
 * of the donor (one a rocket jump reaches stands on no walked place), with a player's height and a margin over it.
 */
static float ceilings_line(const mapgen_reach_t *walk, const mapgen_geometry_t *donor)
{
    float top = -1e30f;
    for (uint32_t s = 0; walk && s < MapGenReach_NumStates(walk); s++) {
        const mapgen_reach_state_t *st = MapGenReach_State(walk, s);
        if (st && st->origin[2] > top)
            top = st->origin[2];
    }
    for (uint32_t e = 0; donor && e < MapGenGeometry_NumEntities(donor); e++) {
        const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(donor, e);
        const char *cls = MapGenGeometry_EntityValue(donor, e, "classname");
        if (!ent || !ent->has_origin || !cls)
            continue;
        if (!strncmp(cls, "weapon_", 7) || !strncmp(cls, "item_", 5) || !strncmp(cls, "ammo_", 5)
            || !strncmp(cls, "info_player_", 12) || !strcmp(cls, "misc_teleporter_dest"))
            if (ent->origin[2] > top)
                top = ent->origin[2];
    }
    return top + 96.0f;                 /* an origin is 24 over the feet; a player stands 56; and a jump's height */
}

/*
 * THE WARP, before the first edit (the PO, 10.10: «нужно чтобы генератор делал анализ до начала работ и не тратил время
 * на бесконечные тесты»): the donor's plan stretched part by part (mapgen_warp.h) and turned as asked, built once and
 * walked once. A map the walk refuses - a corridor squeezed shut, a jump stretched past a player's reach - is planned
 * again with half the spread, then with half the size's change, at most four times; when none walks, the donor goes
 * as it is and the run says so. Then the ceilings, when asked: everything above the highest place a player stands
 * lifted, built and walked once more - a map that does not walk keeps its ceilings. The warped base is the base:
 * everything after measures from it.
 */
static bool warp_donor(const char *donor_bsp, const char *root, const char *map_name, const char *moddir,
                       const mapcompile_adapter_t *adapter, const mapgen_pipeline_request_t *request,
                       char out[MAPCOMPILE_MAX_PATH], uint32_t *area_permille)
{
    uint32_t size = request->warp_size ? request->warp_size : 100u, shape = request->warp_shape;
    uint32_t shift = request->warp_shift;
    const uint32_t height = request->warp_height > 100u ? request->warp_height : 100u;
    if (size == 100u && !shape && !shift && !request->warp_turn && height == 100u)
        return false;
    const clock_t began = clock();
    mapgen_bsp_t *donor = load_bsp(donor_bsp);
    mapgen_geometry_t *geometry = NULL;
    if (!donor || MapGenGeometry_FromBsp(donor, &geometry) != MAPGEN_GEOMETRY_OK) {
        progress_line("stage=warp-refused why=\"the donor could not be read\"");
        MapGenBsp_Free(donor);
        return false;
    }
    float zlo = 1e30f, zhi = -1e30f;
    for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(geometry); b++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(geometry, b);
        if (br && !br->model) {
            zlo = fminf(zlo, br->mins[2]);
            zhi = fmaxf(zhi, br->maxs[2]);
        }
    }
    mapgen_reach_t *donor_walk = NULL;          /* walked only when a warped map fails the absolutes */
    bool done = false;
    int32_t turn = request->warp_turn;
    /* brief 18 D2: what a frame grown tall cannot keep walkable (q3t2 at 1000 %: a grating's gaps grown wider than a
       player over a pocket grown three times as deep) is taken back first by growing less tall - 30 % of the growth
       a try - before the turn, the shift, the spread and the size */
    float tall_cap = 1e9f;
    for (uint32_t attempt = 0; attempt < (request->warp_tries ? request->warp_tries : 8u) && !done; attempt++) {
        mapgen_warp_t w;
        if (!MapGenWarp_Plan(geometry, request->generate.seed, size, shape, shift, &w))
            break;
        MapGenWarp_PlanTurn(&w, request->generate.seed, turn);
        /* brief 18 D2 (the PO, 11.10: «не сохраняя пропорции»): as tall as it grew wide */
        MapGenWarp_PlanTall(&w, zlo, zhi, tall_cap);
        const bool plane_moves = !MapGenWarp_IsIdentity(&w);
        char dir[MAPCOMPILE_MAX_PATH], path[MAPCOMPILE_MAX_PATH] = "";
        mapgen_reach_t *walk = NULL;
        bool playable = false;
        if (plane_moves) {
            snprintf(dir, sizeof(dir), "%s/warp_%u", root, (unsigned)attempt);
            playable = warp_try(geometry, donor, &donor_walk, &w, dir, map_name, moddir, adapter, request, attempt,
                                size, shape, path, &walk);
        } else if (height > 100u) {
            /* only the ceilings asked: the donor's own walk gives their line */
            mapgen_reach_options_t d;
            memset(&d, 0, sizeof(d));
            if (!donor_walk)
                MapGenReach_ExploreWith(donor, MAPGEN_REACH_BUDGET, &d, &donor_walk);
            playable = true;
        } else {
            break;
        }
        if (playable && height > 100u) {
            float z0 = ceilings_line(walk ? walk : donor_walk, geometry);
            if (walk && w.tall > 1.01f)
                z0 = 0.5f * (zlo + zhi) + (z0 - 0.5f * (zlo + zhi)) / w.tall;       /* the warped walk's line, back in the donor's heights */
            mapgen_warp_t tall = w;
            char tall_dir[MAPCOMPILE_MAX_PATH], tall_path[MAPCOMPILE_MAX_PATH] = "";
            mapgen_reach_t *tall_walk = NULL;
            snprintf(tall_dir, sizeof(tall_dir), "%s/warp_%u_tall", root, (unsigned)attempt);
            if (MapGenWarp_PlanHeight(&tall, zlo, z0, zhi, height)
                && warp_try(geometry, donor, &donor_walk, &tall, tall_dir, map_name, moddir, adapter, request,
                            attempt, size, shape, tall_path, &tall_walk)) {
                w = tall;
                snprintf(path, sizeof(path), "%s", tall_path);
            } else {
                progress_line("stage=warp-ceilings-kept line=%.0f why=\"the taller map did not walk\"", (double)z0);
            }
            MapGenReach_Free(tall_walk);
        }
        MapGenReach_Free(walk);
        if (playable && path[0]) {
            char said[256];
            MapGenWarp_Describe(&w, said, sizeof(said));
            snprintf(out, MAPCOMPILE_MAX_PATH, "%s", path);
            *area_permille = w.area_permille;
            progress_line("stage=warp-done area=%u parts=\"%s\" asked_size=%u asked_shape=%u asked_turn=%d "
                          "asked_height=%u ms=%u", (unsigned)w.area_permille, said,
                          (unsigned)(request->warp_size ? request->warp_size : 100u), (unsigned)request->warp_shape,
                          (int)request->warp_turn, (unsigned)height,
                          (unsigned)((clock() - began) * 1000 / CLOCKS_PER_SEC));
            done = true;
            break;
        }
        if (playable)
            break;                      /* nothing to build: only the ceilings were asked, and they did not walk */
        /* what the map could not take, taken back: the turn first - a turned map plays the same moves mirrored, and
           a rocket jump onto q2dm1's pedestals, a hair from failing, failed mirrored (2 pickups, 10.10) - then the
           spread by half, then the size's change by half */
        if (w.tall > 1.15f)
            tall_cap = 1.0f + (w.tall - 1.0f) * 0.7f;
        else if (turn)
            turn = 0;
        else if (shift >= 10u)
            shift /= 2u;
        else if (shift)
            shift = 0u;
        else if (shape >= 10u)
            shape /= 2u;
        else {
            shape = 0u;
            size = (uint32_t)(100 + ((int32_t)size - 100) / 2);
        }
        if (size >= 95u && size <= 105u && !shape && !turn && !shift)
            break;
    }
    if (!done)
        progress_line("stage=warp-kept why=\"no warped map walked; the donor goes as it is\"");
    MapGenReach_Free(donor_walk);
    MapGenGeometry_Free(geometry);
    MapGenBsp_Free(donor);
    return done;
}

/* row 412: which parts of the rebuilt base differ from the original, and how - every part's own words, quotes and line
   breaks made safe for a progress line. False when the transaction kept no account. */
static bool baseline_refusal(char *axes, size_t axes_cap, char *said, size_t said_cap)
{
    mapgen_equiv_report_t why;
    axes[0] = said[0] = '\0';
    if (!MapGenTransaction_LastBaselineWhy(&why))
        return false;
    for (int r = MAPGEN_EQUIV_DIFF_SPACE; r < MAPGEN_EQUIV_RESULT_COUNT; r++)
        if (why.failed_axes & MAPGEN_EQUIV_AXIS_BIT(r)) {
            const size_t used = strlen(axes);
            snprintf(axes + used, axes_cap - used, "%s%s", used ? "," : "",
                     MapGenEquivalence_ResultName((mapgen_equiv_result_t)r));
        }
    for (int r = MAPGEN_EQUIV_DIFF_SPACE; r < MAPGEN_EQUIV_RESULT_COUNT; r++)
        if ((why.failed_axes & MAPGEN_EQUIV_AXIS_BIT(r)) && why.axis_detail[r][0]) {
            const size_t used = strlen(said);
            snprintf(said + used, said_cap - used, "%s%s", used ? "; " : "", why.axis_detail[r]);
        }
    if (!said[0])
        snprintf(said, said_cap, "%s", why.detail);
    if (!axes[0] && MapGenTransaction_LastBaselineCompileWhy()[0])
        snprintf(said, said_cap, "%s", MapGenTransaction_LastBaselineCompileWhy());
    if (!axes[0])
        snprintf(axes, axes_cap, "none");
    for (char *c = said; *c; c++)
        if (*c == '"' || *c == '\n' || *c == '\r')
            *c = '\'';
    return true;
}

/* What a refused rebuild draws differently, in the numbers `faithful_residue_small` holds it to - said beside every
   «not held», so the bound that refused is read and not guessed (brief 18 D2). */
static void baseline_residue_say(void)
{
    mapgen_equiv_report_t why;
    if (!MapGenTransaction_LastBaselineWhy(&why))
        return;
    progress_line("stage=baseline-residue drawn=%.0f rebuilt=%.0f groups_missing=%.0f groups_added=%.0f "
                  "planes_missing=%u planes_added=%u planes=%u mapping=%u groups=%u overflow=%d",
                  why.drawn_area[0], why.drawn_area[1], why.groups_missing_area, why.groups_added_area,
                  (unsigned)why.planes_missing, (unsigned)why.planes_added, (unsigned)why.surface_planes[0],
                  (unsigned)why.mapping_mismatch, (unsigned)why.drawn_groups[0], why.mapping_overflow ? 1 : 0);
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
        replay.dry = request->replay_dry;
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
    /* the warp: the base itself changed first, planned on the donor, built and walked once (see `warp_donor`) */
    char warped[MAPCOMPILE_MAX_PATH] = "";
    const char *const unwarped = donor_bsp;
    uint32_t warp_area = 1000u;                 /* the warped plan's area against the donor's, permille */
    if (request->warp_shape || (request->warp_size && request->warp_size != 100u) || request->warp_turn
        || request->warp_height > 100u || request->warp_shift) {
        if (warp_donor(donor_bsp, in_memory ? g_work_root : job_dir, map_name,
                       request->moddir[0] ? request->moddir : job_dir, adapter, request, warped, &warp_area))
            donor_bsp = warped;
        if (request->warp_only) {
            /* the frame alone: the base it gave kept beside the job, as a whole run keeps it */
            uint8_t *raw = NULL;
            size_t n = 0;
            char kept[MAPCOMPILE_MAX_PATH];
            snprintf(kept, sizeof(kept), "%s/warped_base.bsp", job_dir);
            FILE *f = NULL;
            if (donor_bsp != unwarped && MapGenFs_Read(donor_bsp, &raw, &n) && n && (f = fopen(kept, "wb")) != NULL) {
                const bool whole = fwrite(raw, 1, n, f) == n;
                fclose(f);
                if (whole)
                    progress_line("stage=warp-base path=\"%s\"", kept);
            }
            free(raw);
        }
        progress_line("stage=baseline");            /* and now the base, warped or not, is built as the base */
    }
    /* a tunnel may run as much further as the plan grew (`MapGenGeometryEdit_SetSpanScale`) */
    MapGenGeometryEdit_SetSpanScale(donor_bsp != unwarped && warp_area > 1000u ? sqrtf((float)warp_area / 1000.0f)
                                                                                : 1.0f);
    mapgen_transaction_result_t opened =
        MapGenTransaction_BeginWithDonors(
            donor_bsp, in_memory ? g_work_root : job_dir, map_name,
            request->moddir[0] ? request->moddir : job_dir,
            adapter, request->generate.seed,
            num_others ? others : NULL, num_others, &txn);
    if (request->warp_only) {
        /*
         * The frame alone ends here - AFTER its base was built as the run's base. Brief 18 D2: the seam's first cut
         * stopped at the walk, the guard on it was green, and the run itself (mg_b18_q3t2 on 3.31) then said «the
         * warped base was not held by its rebuild» and went on the donor as it was - a map at 100 % of its size
         * delivered for the PO's 1000 %. A frame is kept when the walk passes AND the rebuild holds it.
         */
        if (opened == MAPGEN_TXN_ERR_BASELINE && donor_bsp != unwarped) {
            char axes[256] = "none", said[4 * MAPGEN_EQUIV_DETAIL] = "the rebuilt base differs";
            baseline_refusal(axes, sizeof(axes), said, sizeof(said));
            progress_line("stage=warp-kept why=\"the warped base was not held by its rebuild: %s - %s\"", axes, said);
            baseline_residue_say();
        } else if (opened == MAPGEN_TXN_OK && donor_bsp != unwarped) {
            progress_line("stage=warp-held");
        }
        progress_line("stage=warp-only");
        MapGenTransaction_Free(txn);
        return MAPGEN_PIPELINE_ERR_GENERATE;
    }
    if (opened == MAPGEN_TXN_ERR_BASELINE && donor_bsp != unwarped) {
        /* a warped base its own rebuild does not hold to: the run goes on the donor as it is, and says so - a frame
           that cannot be held is no reason to lose the generation */
        char axes[256] = "none", said[4 * MAPGEN_EQUIV_DETAIL] = "the rebuilt base differs";
        baseline_refusal(axes, sizeof(axes), said, sizeof(said));
        progress_line("stage=warp-kept why=\"the warped base was not held by its rebuild: %s - %s\"", axes, said);
        baseline_residue_say();
        char base_dir[MAPCOMPILE_MAX_PATH];
        snprintf(base_dir, sizeof(base_dir), "%s/baseline", in_memory ? g_work_root : job_dir);
        if (in_memory)
            MapGenFs_EmptyDir(base_dir);
        else
            clear_files(base_dir);
        donor_bsp = unwarped;
        MapGenGeometryEdit_SetSpanScale(1.0f);
        progress_line("stage=baseline");
        opened = MapGenTransaction_BeginWithDonors(
            donor_bsp, in_memory ? g_work_root : job_dir, map_name,
            request->moddir[0] ? request->moddir : job_dir,
            adapter, request->generate.seed,
            num_others ? others : NULL, num_others, &txn);
    }
    if (opened == MAPGEN_TXN_ERR_BASELINE) {
        /* row 412: which parts of the copy differ from the original, and how - the Studio says it */
        char axes[256], said[4 * MAPGEN_EQUIV_DETAIL];
        if (baseline_refusal(axes, sizeof(axes), said, sizeof(said))) {
            progress_line("stage=baseline-refused axes=%s what=\"%s\"", axes, said);
            fprintf(stderr, "baseline refused: %s - %s\n", axes, said);
        }
        return MAPGEN_PIPELINE_ERR_BASELINE;
    }
    if (opened != MAPGEN_TXN_OK) {
        /* said, not only returned (the donor survey, 09.10: 2box4 stopped in its first second without a word) */
        progress_line("stage=donor-refused why=%s", MapGenTransaction_ResultName(opened));
        fprintf(stderr, "the donor was not opened: %s\n", MapGenTransaction_ResultName(opened));
        return MAPGEN_PIPELINE_ERR_GENERATE;
    }
    /* the warped base kept beside the job on the disk, whatever the run works in: the map's checks after the run hold
       it to the base it was built on, not to the donor's old places */
    if (donor_bsp != unwarped) {
        uint8_t *raw = NULL;
        size_t n = 0;
        char kept[MAPCOMPILE_MAX_PATH];
        snprintf(kept, sizeof(kept), "%s/warped_base.bsp", job_dir);
        FILE *f = NULL;
        if (MapGenFs_Read(donor_bsp, &raw, &n) && n && (f = fopen(kept, "wb")) != NULL) {
            const bool whole = fwrite(raw, 1, n, f) == n;
            fclose(f);
            if (whole)
                progress_line("stage=warp-base path=\"%s\"", kept);
        }
        free(raw);
    }
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
                  " windows=%u reliquids=%u stairways=%u remodels=%u blocks=%u floor_shifts=%u stair_reshapes=%u", (unsigned)offered, (unsigned)budget, (unsigned)target,
                  (unsigned)tunnels, (unsigned)annexes, (unsigned)storeys,
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_SPAN) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_FLOOD) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_WINDOW) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_RELIQUID) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_STAIRWAY) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_REMODEL) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_BLOCK) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_FLOOR_SHIFT) : 0u),
                  (unsigned)(plan ? MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_STAIR_RESHAPE) : 0u));
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
        /* brief 11: the options that change the plan, so the gates re-deal the plan this run dealt - and, on a warped
           base, how much longer its tunnels may run (MapGenGeometryEdit_SetSpanScale) */
        const float span = donor_bsp != unwarped && warp_area > 1000u ? sqrtf((float)warp_area / 1000.0f) : 1.0f;
        if (request->plan_options[0] || span > 1.0f) {
            char span_text[48] = "";
            if (span > 1.0f)
                snprintf(span_text, sizeof(span_text), "%s--span-scale %.4f", request->plan_options[0] ? " " : "",
                         (double)span);
            fprintf(ledger, "# plan-options %s%s\n", request->plan_options, span_text);
        }
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
    uint32_t accepted_before_round = 0;
    /*
     * Brief 16 D3 (the PO, 10.10: mg_10_6695 tried one shaft and lift in SEVEN rounds, refused alike each time, 587
     * seconds): every site the run has tried, by its print - a redeal deals it again, the run does not ask again. A
     * redeal with nothing new to try ends the edits: «план исчерпан». Not in a dry replay of an older run's ledger,
     * which tried its sites as often as it did; the replay counts them instead.
     */
    uint64_t *tried = NULL;
    uint32_t num_tried = 0, cap_tried = 0, skipped_tried = 0;
    ladder_t ladder;
    memset(&ladder, 0, sizeof(ladder));
    bool plan_exhausted = false, out_of_time = false;
    uint32_t *order = NULL;
    for (uint32_t round = 0; round < MAPGEN_PIPELINE_MORE_ROUNDS; round++) {
      rounds_dealt = round + 1u;
      if (round) {
          if (MapGenTransaction_Divergence(txn) >= target || attempts >= budget)
              break;
          /* brief 15 D4: past the first four, only while the round before accepted something */
          if (round >= MAPGEN_PIPELINE_MAX_ROUNDS && MapGenTransaction_Accepted(txn) == accepted_before_round)
              break;
          accepted_before_round = MapGenTransaction_Accepted(txn);
          if (MapGenTransaction_Redeal(txn, request->generate.seed
                                            + 0x9E3779B9ull * (round + 1))
              != MAPGEN_TXN_OK)
              break;
          plan = MapGenTransaction_Plan(txn);
          offered = MapGenGeometryEdit_Count(plan);
          SAY(50, "dealing again");
          write_plan(job_dir, plan, round);
          uint32_t fresh = 0;
          for (uint32_t i = 0; i < offered; i++) {
              const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
              if (e && !family_skipped(request, e->kind)
                  && (target == 0 || !zero_gain(e->kind))
                  && !print_held(tried, num_tried, edit_print(plan, i, e)))
                  fresh++;
          }
          progress_line("stage=redeal round=%u offered=%u fresh=%u", (unsigned)round,
                        (unsigned)offered, (unsigned)fresh);
      }
      /* brief 16 D2: the round's edits proved and valued, built most valuable first; the plan says what it can give */
      free(order);
      uint32_t worthy = 0;
      order = plan_order(txn, request, round, target, budget > attempts ? budget - attempts : 0u, tried, num_tried,
                         replay.dry, &worthy);
      /* brief 17 D5: a replay offers the ledger's next rows in the ledger's own order - a run since brief 16 builds
         its most valuable edits first, so a stretched run's ledger is no schedule order */
      /* brief 18 D4: a row is this round's when its edit is - the same index AND the same family (the reference's row
         37, «12 dig», is round 1's; round 0's edit 12 was a reliquid, and the replay offered it); the rows past it are
         the next round's, and the replay deals that round when this one's rows are spent */
      uint32_t round_end = replay.n;
      for (uint32_t j = replay.at, put = 0; order && j < replay.n && put < offered; j++) {
          uint32_t k = put;
          while (k < offered && (order[k] != replay.e[j].index
                                 || !MapGenGeometryEdit_At(plan, order[k])
                                 || strcmp(replay.e[j].family,
                                           MapGenGeometryEdit_KindName(MapGenGeometryEdit_At(plan, order[k])->kind))))
              k++;
          if (k == offered) {
              round_end = j;
              break;                                  /* the next round's */
          }
          const uint32_t want = order[k];
          memmove(&order[put + 1], &order[put], (size_t)(k - put) * sizeof(*order));
          order[put++] = want;
      }
      /* brief 16 D3: a new deal with no new proved edit worth building ends the edits - «план исчерпан». A dry replay
         ends them too when its ledger says so (brief 18 D4): its next row is none of this deal's, or the finishing
         pass's (a liquid, a swapped pickup, a moved start) - an older ledger's next row is this deal's own */
      const char *next_family = replay.at < replay.n ? replay.e[replay.at].family : "";
      const bool ledger_ends_round = replay.dry && replay.at < replay.n
          && (round_end == replay.at || !strcmp(next_family, "reliquid") || !strcmp(next_family, "swap-item")
              || !strcmp(next_family, "move-spawn"));
      if (round && !worthy && (!replay.dry || ledger_ends_round)) {
          plan_exhausted = true;
          progress_line("stage=plan-exhausted round=%u tried=%u", (unsigned)round, (unsigned)num_tried);
          break;
      }
      if (request->plan_only && request->plan_check) {
          /* brief 16 D2: and each edit of it worth building, compiled alone on the base - its estimate checked */
          uint64_t se = 0, st = 0, sa = 0, sta = 0;
          for (uint32_t k = 0; order && k < offered && k < request->plan_check; k++) {
              const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, order[k]);
              uint32_t c = 0, a2 = 0, tc = 0, ta = 0;
              if (!e || zero_gain(e->kind) || !MapGenTransaction_PlanCheck(txn, order[k], &c, &a2, &tc, &ta))
                  continue;
              se += c; st += tc; sa += a2; sta += ta;
              progress_line("stage=plan-check edit=%u family=%s est=%u true=%u added=%u true_added=%u", (unsigned)order[k],
                            MapGenGeometryEdit_KindName(e->kind), (unsigned)c, (unsigned)tc, (unsigned)a2, (unsigned)ta);
          }
          progress_line("stage=plan-check-sum est=%llu true=%llu added=%llu true_added=%llu", (unsigned long long)se,
                        (unsigned long long)st, (unsigned long long)sa, (unsigned long long)sta);
      }
      if (request->plan_only) {
          /* brief 16 D2: the plan and its word, and nothing built - how a ledger made by an older engine is measured */
          replay.diverged = true;
          snprintf(replay.why, sizeof(replay.why), "the plan only: its word is said, nothing is built");
          break;
      }
      for (uint32_t k = 0; k < offered && attempts < budget; k++) {
        const uint32_t i = order ? order[k] : k;
        if (replay.dry && replay.at < replay.n && replay.at >= round_end)
            break;                       /* brief 18 D4: this round's rows are spent - the ledger's next is a new deal's */
        spent_to = k;
        /* brief 16 D6: the run's minutes, not only its builds (a replayed row costs none) */
        if (replay.at >= replay.n && time_is_up(request)) {
            out_of_time = true;
            break;
        }
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
        if (target > 0 && zero_gain(planned->kind) && !replay.dry) {
            ladder.paint++;
            continue;                    /* brief 16 D2: the liquids too, until the finishing pass */
        }
        const uint64_t print = edit_print(plan, i, planned);
        if (!replay.dry && print_held(tried, num_tried, print)) {
            skipped_tried++;
            continue;                    /* brief 16 D3: tried before, on this run */
        }
        print_keep(&tried, &num_tried, &cap_tried, print);
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
        if (verdict != MAPGEN_TXN_REJECTED_NOT_APPLIED && !step.proved_refusal)
            attempts++;                  /* brief 16 D1: an edit refused by its proof was never built */
        ladder_count(&ladder, verdict, &step);
        if ((unsigned)verdict < MAPGEN_TXN_NUM_VERDICTS)
            report->by_verdict[verdict]++;
        if (!replayed)
            write_attempt(ledger, phase_ms, walk_sum, plan, i, planned, verdict,
                          &step);
        progress_attempt(replayed ? "replay" : "edits", i, planned, verdict, &step, txn,
                         attempts, budget, target);
      }
      if (replay.diverged || MapGenTransaction_Divergence(txn) >= target || attempts >= budget || out_of_time)
          break;
    }
    free(order);
    order = NULL;
    if (skipped_tried)
        progress_line("stage=tried-before skipped=%u", (unsigned)skipped_tried);

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
        /* brief 16 D2: the liquids swapped here - 48 attempts and an hour of mg_10_6695 for nothing the metric sees,
           while its band was unmet - with a share of their own, then the swaps and the starts (a dry replay of an
           older ledger: as that run did) */
        /* brief 18 D4: a dry replay passes the liquids too when its ledger's next row is one (a ledger of this
           engine; an older one swapped them in its rounds) */
        const bool ledger_liquids = replay.at < replay.n && !strcmp(replay.e[replay.at].family, "reliquid");
        for (int fpass = replay.dry && !ledger_liquids ? 1 : 0; fpass < 2; fpass++) {
        uint32_t finished = 0;
        for (uint32_t i = 0; i < offered
                             && finished < MAPGEN_PIPELINE_FINISHING; i++) {
            const mapgen_geometry_edit_t *planned =
                MapGenGeometryEdit_At(plan, i);
            if (!planned)
                break;
            if (fpass == 0 ? planned->kind != MAPGEN_EDIT_RELIQUID
                           : planned->kind != MAPGEN_EDIT_SWAP_ITEM && planned->kind != MAPGEN_EDIT_MOVE_SPAWN)
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
            ladder_count(&ladder, verdict, &step);
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
        /* brief 16 D2: the edits are built by worth, so a graft is past the last one tried when it was never tried */
        for (uint32_t i = replay.dry ? spent_to : 0u; i < offered; i++) {
            const mapgen_geometry_edit_t *planned =
                MapGenGeometryEdit_At(plan, i);
            if (!planned || planned->kind != MAPGEN_EDIT_GRAFT_BUNDLE
                || family_skipped(request, planned->kind))
                continue;
            if (!replay.dry && print_held(tried, num_tried, edit_print(plan, i, planned)))
                continue;
            const mapgen_typed_edit_t edit = { planned->kind, i,
                                               planned->amount };
            mapgen_transaction_step_t step;
            mapgen_transaction_verdict_t verdict;
            bool replayed = false;
            if (replay.diverged
                || !attempt_or_replay(&replay, txn, ledger, i, planned, &edit, &verdict, &step, &replayed))
                break;
            ladder_count(&ladder, verdict, &step);
            if ((unsigned)verdict < MAPGEN_TXN_NUM_VERDICTS)
                report->by_verdict[verdict]++;
            if (!replayed)
                write_attempt(ledger, phase_ms, walk_sum, plan, i, planned,
                              verdict, &step);
            progress_attempt(replayed ? "replay" : "graft", i, planned, verdict, &step, txn,
                             attempts, budget, target);
        }
    }

    free(tried);
    tried = NULL;
    progress_line("stage=ladder not_applied=%u proved=%u tried=%u paint=%u builds=%u whole=%u taken=%u",
                  (unsigned)ladder.not_applied, (unsigned)ladder.proved, (unsigned)skipped_tried,
                  (unsigned)ladder.paint, (unsigned)ladder.builds, (unsigned)ladder.whole, (unsigned)ladder.taken);

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
             MapGenTransaction_Divergence(txn) >= target ? "target" : out_of_time ? "time"
             : attempts >= budget ? "budget" : plan_exhausted ? "plan" : "schedule");
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
        /* brief 16 D0: the ladder */
        fprintf(ledger, "# ladder: %u declined by the operator and %u refused by the proof, no build; %u tried"
                        " before, not offered again; %u worth nothing the metric counts, kept for the finishing"
                        " pass; %u built - %u walked whole, %u from the parent's walk\n",
                (unsigned)ladder.not_applied, (unsigned)ladder.proved, (unsigned)skipped_tried,
                (unsigned)ladder.paint, (unsigned)ladder.builds, (unsigned)ladder.whole, (unsigned)ladder.taken);
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
                                ? request->reach_budget : MAPGEN_REACH_BUDGET, &walk,
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
            && MapGenReach_Explore(base, request->reach_budget ? request->reach_budget : MAPGEN_REACH_BUDGET, &own)
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
                                                       : MAPGEN_REACH_BUDGET;
    const bool walks_fit = reach && rr == MAPGEN_REACH_OK
                        && gate_budget == MAPGEN_REACH_BUDGET && baseline_walk;
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
        /* brief 14 F5: whether this run resumes, said at its first line - the PO's mg_1_6662 «resumed» from scratch
           (no `stage=resume` at all), and nothing in its records said so */
        progress_line("stage=start map=%s fidelity=%d seed=%llu target=%u resume=%d",
                      map_name ? map_name : "-", (int)request->generate.fidelity,
                      (unsigned long long)request->generate.seed,
                      (unsigned)MapGenDivergence_Target((uint32_t)request->generate.fidelity), request->resume ? 1 : 0);
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
