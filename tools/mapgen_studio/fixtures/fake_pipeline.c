/*
 * A stand-in for pipeline.exe (ledger row 410): what the Studio's window is driven against in
 * tools/check_mapgen_studio_ui.py - a run of a few seconds that writes what the real one writes, in its order and
 * format: the progress lines (start, baseline, baseline-faithful, plan, try before each attempt and the attempt's line
 * after it, judge, light, finish), the ledger, the base, an accepted try's own map, the lit map; and a --resume that
 * replays the ledger (pass=replay) and says «stage=resume replayed=N». The maps are copies of the donor - the window
 * reads them, nothing compiles. Each attempt takes FAKE_STEP_MS (300 by default).
 *
 *   fake_pipeline.exe COMPILER DONOR.bsp JOB_DIR NAME FIDELITY SEED [--resume] [--memory MB] [--checkpoints 0|1]
 *                     [--warp-size N] [anything else ignored]
 *
 * The PO, 11.10 (each stage drawn): with --warp-size other than 100 the base's frame is tried twice, each try's part
 * layout said («stage=warp-map»: the donor's plan in three parts an axis, stretched unequally) before its «stage=warp»
 * line; the light pass's portal file is the donor's own DONOR.prt, copied beside the lit map when there is one, and the
 * light goes through the visibility's two passes, the direct light and a bounce.
 *
 * Row 411: with --memory the base and each accepted try's map are also put in named sections, as the real engine
 * keeps them (Local\q2mem_<root>/baseline/q2mg.bsp ...), and the run says «stage=memory mode=memory root=...»; with
 * --checkpoints 0 they are ONLY there - nothing of a try or of the base on the disk. FAKE_MEMORY_NEED_MB set: the
 * share given is too small, the run says «stage=memory mode=files need_mb=... allowed_mb=...» and works in files.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <windows.h>
#include <direct.h>

static FILE *g_progress;
static time_t g_began;

static void line(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(g_progress, "PROGRESS ");
    vfprintf(g_progress, fmt, ap);
    fprintf(g_progress, " elapsed=%lld\n", (long long)(time(NULL) - g_began));
    fflush(g_progress);
    va_end(ap);
}

static int copy(const char *from, const char *to)
{
    return CopyFileA(from, to, FALSE) ? 0 : -1;
}

/* row 411: a section held for the run's length, as the engine holds its working files */
static char g_root[128];

static void put_section(const char *rel, const char *from)
{
    FILE *f = fopen(from, "rb");
    if (!f)
        return;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char name[512];
    snprintf(name, sizeof(name), "Local\\q2mem_%s/%s", g_root, rel);
    const unsigned long long total = 32ull + (unsigned long long)n;
    HANDLE h = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, (DWORD)(total >> 32),
                                  (DWORD)(total & 0xffffffffu), name);
    unsigned char *view = h ? MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, 0) : NULL;
    if (view) {
        memcpy(view, "Q2MEM1\0\0", 8);
        const unsigned long long room = (unsigned long long)n, size = (unsigned long long)n, present = 1;
        memcpy(view + 8, &room, 8);
        memcpy(view + 16, &size, 8);
        fread(view + 32, 1, (size_t)n, f);
        memcpy(view + 24, &present, 8);
    }
    fclose(f);
    /* never closed: the section lives as long as this run */
}

static const char *FAMILIES[] = { "dig", "window", "widen-connector", "flood", "span", "reshape-room" };

int main(int argc, char **argv)
{
    if (argc < 7)
        return 2;
    const char *donor = argv[2], *job = argv[3];
    int resume = 0, memory = 0, checkpoints = 1, warp = 100;
    const char *second = NULL;          /* brief 9: the second map (`--donor`) */
    for (int a = 7; a < argc; a++) {
        if (!strcmp(argv[a], "--resume"))
            resume = 1;
        else if (!strcmp(argv[a], "--memory") && a + 1 < argc)
            memory = atoi(argv[++a]);
        else if (!strcmp(argv[a], "--checkpoints") && a + 1 < argc)
            checkpoints = atoi(argv[++a]);
        else if (!strcmp(argv[a], "--donor") && a + 1 < argc)
            second = argv[++a];
        else if (!strcmp(argv[a], "--warp-size") && a + 1 < argc)
            warp = atoi(argv[++a]);
    }
    const char *need = getenv("FAKE_MEMORY_NEED_MB");
    const int given = memory;
    if (need && memory > 0 && atoi(need) > memory)
        memory = -atoi(need);           /* too small a share: in files, said so below */
    const char *step_env = getenv("FAKE_STEP_MS");
    const int step = step_env ? atoi(step_env) : 300;
    char path[1024], path2[1024];
    _mkdir(job);
    snprintf(path, sizeof(path), "%s/progress.txt", job);
    if (resume) {
        snprintf(path2, sizeof(path2), "%s/progress_before_resume.txt", job);
        MoveFileExA(path, path2, MOVEFILE_REPLACE_EXISTING);
    }
    g_progress = fopen(path, "wb");
    if (!g_progress)
        return 3;
    g_began = time(NULL);
    const int budget = 6, total = 10, target = 800;
    line("stage=start map=q2mg fidelity=%s seed=%s target=%d", argv[5], argv[6], target);
    /* what the ledger already holds, when resuming */
    int done = 0;
    char rows[64][256];
    snprintf(path, sizeof(path), "%s/ledger.txt", job);
    if (resume) {
        FILE *l = fopen(path, "rb");
        char buf[256];
        while (l && fgets(buf, sizeof(buf), l))
            if (buf[0] != '#' && done < 64)
                snprintf(rows[done++], sizeof(rows[0]), "%s", buf);
        if (l)
            fclose(l);
        line("stage=resume ledger=%d", done);
    }
    FILE *ledger = fopen(path, "wb");
    fprintf(ledger, "# q2mg fidelity %s seed %s\n# index family verdict divergence box-lo box-hi\n", argv[5], argv[6]);
    fflush(ledger);
    if (memory > 0) {
        snprintf(g_root, sizeof(g_root), "q2mg_fake_%lu_%lld", (unsigned long)GetCurrentProcessId(), (long long)g_began);
        line("stage=memory mode=memory root=%s room_mb=32 need_mb=800 allowed_mb=%d checkpoints=%d", g_root, memory,
             checkpoints);
    } else if (memory < 0)
        line("stage=memory mode=files need_mb=%d allowed_mb=%d why=\"not enough free memory\"", -memory, given);
    else
        line("stage=memory mode=files why=\"not asked\"");
    const int disk = memory <= 0 || checkpoints;
    if (warp != 100 && !resume) {
        /* the donor's plan from its vertices (lump 2), cut in three parts an axis */
        float lo[2] = { 1e9f, 1e9f }, hi[2] = { -1e9f, -1e9f };
        FILE *d = fopen(donor, "rb");
        if (d) {
            int head[2 + 19 * 2];
            if (fread(head, sizeof(int), 2 + 19 * 2, d) == 2 + 19 * 2) {
                const int off = head[2 + 2 * 2], len = head[2 + 2 * 2 + 1];
                float v[3];
                fseek(d, off, SEEK_SET);
                for (int i = 0; i < len / 12 && fread(v, sizeof(float), 3, d) == 3; i++)
                    for (int a = 0; a < 2; a++) {
                        if (v[a] < lo[a]) lo[a] = v[a];
                        if (v[a] > hi[a]) hi[a] = v[a];
                    }
            }
            fclose(d);
        }
        static const float K[2][2][3] = { { { 1.6f, 1.0f, 1.4f }, { 1.2f, 1.7f, 1.0f } },
                                          { { 1.3f, 1.5f, 1.2f }, { 1.5f, 1.1f, 1.4f } } };
        for (int t = 0; t < 2 && lo[0] < hi[0]; t++) {
            char ax[2][160];
            for (int a = 0; a < 2; a++) {
                const float span = (hi[a] - lo[a]) / 3.0f, mid = 0.5f * (lo[a] + hi[a]);
                float at[4], to[4], total = 0;
                for (int i = 0; i < 3; i++)
                    total += span * K[t][a][i];
                to[0] = mid - total / 2;
                for (int i = 0; i < 4; i++) {
                    at[i] = lo[a] + span * (float)i;
                    if (i)
                        to[i] = to[i - 1] + span * K[t][a][i - 1];
                }
                snprintf(ax[a], sizeof(ax[a]), "%.0f:%.0f,%.0f:%.0f,%.0f:%.0f,%.0f:%.0f", at[0], to[0], at[1], to[1],
                         at[2], to[2], at[3], to[3]);
            }
            line("stage=warp-map try=%d x=\"%s\" y=\"%s\" z=\"\" lean_x=\"\" lean_y=\"\" turns=0 mirror=0", t, ax[0], ax[1]);
            Sleep(step * 3);
            line("stage=warp try=%d size=%d shape=50 area=%d parts=\"x=%.2f,%.2f,%.2f y=%.2f,%.2f,%.2f area=%d turn=0 mirror=0 "
                 "height=100 shift=0\" built=1 playable=%d places=9000 pickups=83 pickups_out=0 starts=10 stranded=0 "
                 "build_ms=900 walk_ms=20000 why=\"\"", t, warp, warp * 10, K[t][0][0], K[t][0][1], K[t][0][2], K[t][1][0],
                 K[t][1][1], K[t][1][2], warp, t == 1);
        }
        line("stage=warp-done area=%d parts=\"x=%.2f,%.2f,%.2f y=%.2f,%.2f,%.2f area=%d turn=0 mirror=0 height=100 shift=0\" "
             "asked_size=%d asked_shape=50 asked_turn=0 asked_height=100 ms=1000", warp * 10, K[1][0][0], K[1][0][1],
             K[1][0][2], K[1][1][0], K[1][1][1], K[1][1][2], warp, warp);
    }
    line("stage=baseline");
    if (memory > 0)
        put_section("baseline/q2mg.bsp", donor);
    if (memory <= 0) {
        snprintf(path, sizeof(path), "%s/baseline", job);
        _mkdir(path);
        snprintf(path, sizeof(path), "%s/baseline/q2mg.bsp", job);
        copy(donor, path);
    }
    Sleep(step);
    line("stage=baseline-faithful planes_missing=0 planes_added=0 residue_area=0 drawn=1 mapping=0");
    line("stage=plan offered=%d budget=%d target=%d digs=2 annexes=1 storeys=0 spans=1 floods=1 windows=2 reliquids=1", total, budget,
         target);
    /* row 411: the plan written whole (the Studio draws the edits still to come), digs with their shapes */
    snprintf(path, sizeof(path), "%s/plan.txt", job);
    FILE *planf = fopen(path, "wb");
    if (planf) {
        fprintf(planf, "# round 0 - index family shape box-lo box-hi\n");
        for (int i = 0; i < total; i++)
            fprintf(planf, "%d %s %s %d 200 0 %d 456 160\n", i, FAMILIES[i % 6], i % 6 == 0 ? (i ? "annex" : "ell") : "-",
                    100 + 150 * i, 228 + 150 * i);
        fclose(planf);
    }
    /* brief 9: what the second map gave the plan - a room of it (edit 6) and a room in its skin (edit 0) */
    const char *second_name = second ? (strrchr(second, '\\') ? strrchr(second, '\\') + 1 : second) : NULL;
    if (second_name)
        line("stage=second-map name=\"%s\" rooms=1 skins=1 tried=5 size=1 empty=1 nosite=2 nopickup=0 exchanges=0",
             second_name);
    int accepted = 0, compiles = 0, divergence = 0;
    for (int i = 0; i < total; i++) {
        const char *family = FAMILIES[i % 6];
        const int replay = i < done;
        const int ok = (i % 3) != 1;
        if (!replay) {
            line("stage=try edit=%d family=%s box=%d,%d,%d,%d,%d,%d", i, family, 100 + 150 * i, 200, 0,
                 228 + 150 * i, 456, 160);
            Sleep(step);
        }
        compiles++;
        if (ok) {
            accepted++;
            divergence += 70;
            if (memory > 0) {
                snprintf(path, sizeof(path), "try_%04d/q2mg.bsp", i);
                put_section(path, donor);
            }
            if (disk) {
                snprintf(path, sizeof(path), "%s/try_%04d", job, i);
                _mkdir(path);
                snprintf(path, sizeof(path), "%s/try_%04d/q2mg.bsp", job, i);
                copy(donor, path);
            }
        }
        if (replay)
            fputs(rows[i], ledger);
        else
            fprintf(ledger, "%5d %-16s %-24s %4d  %d 200 0  %d 456 160\n", i, family,
                    ok ? "ACCEPTED" : "REJECTED_UNPLAYABLE", divergence, 100 + 150 * i, 228 + 150 * i);
        fflush(ledger);
        line("stage=attempt pass=%s edit=%d family=%s shape=%s from=\"%s\" verdict=%s accepted=%d compiles=%d budget=%d"
             " divergence=%d target=%d ms=%d", replay ? "replay" : "edits", i, family,
             i % 6 == 0 ? (i ? "room-of" : "ell") : "-", second_name && i % 6 == 0 ? second_name : "",
             ok ? "ACCEPTED" : "REJECTED_UNPLAYABLE",
             accepted, compiles, budget + 4, divergence, target, replay ? 0 : step);
        if (resume && i + 1 == done)
            line("stage=resume replayed=%d", done);
    }
    fclose(ledger);
    line("stage=judge");
    Sleep(step);
    line("stage=light");
    snprintf(path, sizeof(path), "%s/lit", job);
    _mkdir(path);
    snprintf(path, sizeof(path), "%s/lit/q2mg.bsp", job);
    copy(donor, path);
    /* the PO, 11.10: the donor's portal file beside the lit map, for the visibility's picture */
    {
        char prt[1024], to[1024];
        snprintf(prt, sizeof(prt), "%s", donor);
        char *dot = strrchr(prt, '.');
        if (dot && strlen(dot) == 4) {
            strcpy(dot, ".prt");
            snprintf(to, sizeof(to), "%s/lit/q2mg.prt", job);
            copy(prt, to);
        }
    }
    /* row 411: the light compile's passes, a tenth at a time, as the real one says them: the visibility's base and
       full passes, the direct light, a bounce */
    static const char *const STEP[4] = { "vis", "vis", "rad", "rad" };
    static const int PASS[4] = { 0, 1, 0, 1 };
    for (int k = 0; k < 4; k++)
        for (int tenths = 1; tenths <= 10; tenths++) {
            line("stage=light-step step=%s pass=%d tenths=%d", STEP[k], PASS[k], tenths);
            Sleep(step / 2);
        }
    line("stage=finish result=OK accepted=%d attempted=%d divergence=%d target=%d ended_by=- compiles=%d budget=%d"
         " rounds=1 bsp=\"%s\"", accepted, total, divergence, target, compiles, budget + 4, path);
    fclose(g_progress);
    return 0;
}
