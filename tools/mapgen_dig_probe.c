/*
 * Can a player WALK a dig, and is it dark in there?
 *
 *     mapgen_dig_probe <map.bsp> --walk X0 Y0 Z0 X1 Y1 Z1 [--step 16]
 *     mapgen_dig_probe <map.bsp> --stand X Y Z
 *
 * `--walk` steps a player hull along the straight line between the two ends of a
 * dig and reports, at every step, the ground under it and the headroom over it.
 * That is what "every tread is at most 18 above the one before it, with 128 of
 * headroom" has to be PROVED with: the plan's own arithmetic is a plan, and
 * `MapGenTrace_Box` against the compiled file is the map.
 *
 * It does not pretend to be the reachability gate - that is `MapGenReach`, and it
 * judges the whole map. This answers one question about one passage, cheaply
 * enough to run on every delivered map.
 *
 * Exit 0 when every step is walkable, 1 when one is not.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_trace.h"

/*
 * How many T-junctions the COMPILED map has between two world faces.
 *
 * That is the number the transaction's seam gate is about, and it is the right
 * question to ask of a dig: a source-brush fault count is not, because the
 * compiler's own FixTjuncs pass stitches the world before anybody sees the map,
 * and a carve that replaces one rock brush with six pieces raises the source
 * count by design. MEASURED on the guard's rock fixture: 446 source faults
 * against the donor's 72, and zero world-against-world seams in the compiled
 * file either way.
 */
#define SEAM_CAP 65536u

/* The player, as the engine has him: 32 wide and 56 tall, standing. */
static const float PLAYER_MINS[3] = { -16.0f, -16.0f, -24.0f };
static const float PLAYER_MAXS[3] = { 16.0f, 16.0f, 32.0f };
/* What pmove will climb, and the headroom a dig promises. */
#define STEP_MAX   18.0f
#define HEADROOM  128.0f

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = malloc((size_t)(n > 0 ? n : 1));
    if (!raw || n <= 0 || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t rc = MapGenBsp_Load(raw, (size_t)n, &bsp);
    free(raw);
    return rc == MAPGEN_BSP_OK ? bsp : NULL;
}

/*
 * The ground under a point, as a player's own hull finds it: a sweep down from
 * a little above, so a tread the hull cannot actually rest on is not reported as
 * ground.
 */
/*
 * Where each brush model ACTUALLY is when the map spawns.
 *
 * Everything sits where it is drawn except an untargeted `func_plat`, which
 * `SP_func_plat` lowers by its own `height` before the first frame - `pos2 =
 * origin - height`, then `s.origin = pos2`. MEASURED consequence of ignoring it:
 * a lift shaft whose floor is 328 and whose deck is DRAWN at 384..400 leaves a
 * 56-unit gap, exactly a standing player's height, and the probe could not find a
 * place to stand anywhere in the shaft. At spawn the deck is 52 lower and he
 * stands on it.
 */
#define PROBE_MAX_MODELS 512u
static float g_model_drop[PROBE_MAX_MODELS];

static void learn_model_positions(const mapgen_bsp_t *bsp)
{
    memset(g_model_drop, 0, sizeof(g_model_drop));
    uint32_t length = 0;
    const char *text = MapGenBsp_Entities(bsp, &length);
    if (!text)
        return;
    const char *at = text;
    while ((at = strchr(at, '{')) != NULL) {
        const char *end = strchr(at, '}');
        if (!end)
            break;
        char block[2048];
        const size_t n = (size_t)(end - at) < sizeof(block) - 1
                       ? (size_t)(end - at) : sizeof(block) - 1;
        memcpy(block, at, n);
        block[n] = '\0';
        at = end + 1;
        if (!strstr(block, "\"classname\" \"func_plat\""))
            continue;
        if (strstr(block, "\"targetname\""))
            continue;           /* it waits at the top until something fires it */
        const char *mv = strstr(block, "\"model\"");
        if (!mv)
            continue;
        const char *q = strchr(mv + 7, '"');
        if (!q || q[1] != '*')
            continue;
        const uint32_t model = (uint32_t)atoi(q + 2);
        if (model == 0 || model >= PROBE_MAX_MODELS)
            continue;
        float height = 0.0f;
        const char *hv = strstr(block, "\"height\"");
        if (hv) {
            const char *hq = strchr(hv + 8, '"');
            if (hq)
                height = (float)atof(hq + 1);
        }
        if (height <= 0.0f) {
            /* no `height`: the travel is the model's own size less the lip */
            float lip = 8.0f;
            const char *lv = strstr(block, "\"lip\"");
            if (lv) {
                const char *lq = strchr(lv + 5, '"');
                if (lq)
                    lip = (float)atof(lq + 1);
            }
            const mapgen_bsp_model_t *m = MapGenBsp_Model(bsp, model);
            if (m)
                height = (m->maxs[2] - m->mins[2]) - lip;
        }
        if (height > 0.0f)
            g_model_drop[model] = -height;
    }
}

/*
 * Sweep the world AND every brush model, at the position each is really in.
 *
 * A lift's deck is a submodel, and `MapGenTrace_Box` sweeps model zero only - so
 * the one surface a player stands on in a lift shaft was invisible to this probe
 * and it reported «NO GROUND» over a shaft that is plainly in the file. A
 * `func_plat` is drawn in its RAISED position by the stock game's own convention,
 * which is where the brushes are, so a zero displacement is the right frame.
 */
static void sweep_all(mapgen_trace_context_t *ctx, const mapgen_bsp_t *bsp,
                      const float start[3], const float end[3],
                      mapgen_trace_result_t *out)
{
    MapGenTrace_Box(ctx, start, end, PLAYER_MINS, PLAYER_MAXS,
                    MAPGEN_MASK_PLAYERSOLID, out);
    for (uint32_t m = 1; m < MapGenBsp_NumModels(bsp); m++) {
        const float where[3] = { 0.0f, 0.0f,
                                 m < PROBE_MAX_MODELS ? g_model_drop[m] : 0.0f };
        MapGenTrace_BoxModel(ctx, m, where, start, end, PLAYER_MINS,
                             PLAYER_MAXS, MAPGEN_MASK_PLAYERSOLID, out);
    }
}

static bool ground_under(mapgen_trace_context_t *ctx,
                         const mapgen_bsp_t *bsp, const float at[3],
                         float reach, float *out)
{
    /*
     * The sweep has to START in free space, and inside a TUNNEL neither "at the
     * point" nor "a long way above it" is reliable.
     *
     * MEASURED on the ell dig: the passage is there in the compiled file - a
     * stepped tunnel with 128 of headroom - and this reported «31 of 38 samples
     * NO GROUND», because the caller lifted the start 96 units and this lifted
     * it further, so every attempt began in the rock OVER the tunnel.
     *
     * So the search walks OUTWARD from the point: zero, eight up, eight down,
     * sixteen up, sixteen down, and so on. A passage is bounded above as well as
     * below and the free space is NEAR the sample, in either direction.
     */
    for (float away = 0.0f; away <= 72.0f; away += 8.0f) {
        for (int sign = 0; sign < 2; sign++) {
            if (!away && sign)
                continue;
            const float from_z = at[2] + (sign ? -away : away);
            float start[3] = { at[0], at[1], from_z };
            float end[3] = { at[0], at[1], from_z - reach };
            mapgen_trace_result_t tr;
            sweep_all(ctx, bsp, start, end, &tr);
            if (tr.startsolid || tr.allsolid)
                continue;
            if (tr.fraction >= 1.0f)
                continue;
            *out = tr.endpos[2] - 24.0f;  /* the surface the hull rests on */
            return true;
        }
    }
    return false;
}

/* How much room there is over a point before the hull hits something. */
static float headroom_over(mapgen_trace_context_t *ctx,
                           const mapgen_bsp_t *bsp, const float at[3])
{
    float start[3] = { at[0], at[1], at[2] + 25.0f };
    float end[3] = { at[0], at[1], at[2] + 25.0f + 512.0f };
    mapgen_trace_result_t tr;
    sweep_all(ctx, bsp, start, end, &tr);
    if (tr.startsolid || tr.allsolid)
        return 0.0f;
    return 57.0f + tr.fraction * 512.0f;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <map.bsp> --walk X0 Y0 Z0 X1 Y1 Z1"
                        " [--step N] | --stand X Y Z\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    learn_model_positions(bsp);
    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (!MapGenTrace_Bind(&ctx, bsp)) {
        fprintf(stderr, "cannot bind a trace context\n");
        return 2;
    }

    float from[3] = { 0, 0, 0 }, to[3] = { 0, 0, 0 }, stand[3] = { 0, 0, 0 };
    bool do_walk = false, do_stand = false, do_seams = false;
    float step = 16.0f;
    for (int a = 2; a < argc; a++) {
        if (!strcmp(argv[a], "--seams")) {
            do_seams = true;
        } else if (!strcmp(argv[a], "--walk") && a + 6 < argc) {
            for (int i = 0; i < 3; i++)
                from[i] = strtof(argv[++a], NULL);
            for (int i = 0; i < 3; i++)
                to[i] = strtof(argv[++a], NULL);
            do_walk = true;
        } else if (!strcmp(argv[a], "--stand") && a + 3 < argc) {
            for (int i = 0; i < 3; i++)
                stand[i] = strtof(argv[++a], NULL);
            do_stand = true;
        } else if (!strcmp(argv[a], "--step") && a + 1 < argc) {
            step = strtof(argv[++a], NULL);
        }
    }

    int bad = 0;

    if (do_seams) {
        mapgen_bsp_seam_t *seam = malloc(sizeof(*seam) * SEAM_CAP);
        uint32_t count = 0, world = 0, cross = 0, liquid = 0;
        const mapgen_bsp_seams_result_t rc = seam
            ? MapGenBsp_Seams(bsp, seam, SEAM_CAP, &count)
            : MAPGEN_SEAMS_ERR_MEMORY;
        for (uint32_t i = 0; i < count && i < SEAM_CAP; i++) {
            if (!seam[i].opaque_edge && !seam[i].opaque_vertex)
                liquid++;
            else if (seam[i].edge_model != seam[i].vertex_model)
                cross++;
            else {
                world++;
                /* row 344: where, so a guard can ask whether it is a dig's */
                printf("world seam at %.1f %.1f %.1f\n", (double)seam[i].split[0],
                       (double)seam[i].split[1], (double)seam[i].split[2]);
                /* row 382: and the edge it splits, for a crack far from the edit */
                printf("  on the edge %.2f %.2f %.2f -> %.2f %.2f %.2f\n",
                       (double)seam[i].from[0], (double)seam[i].from[1], (double)seam[i].from[2],
                       (double)seam[i].to[0], (double)seam[i].to[1], (double)seam[i].to[2]);
            }
        }
        printf("seams %s: %u total, %u world-vs-world, %u cross-model,"
               " %u liquid\n", MapGenBsp_SeamsResultName(rc), count, world,
               cross, liquid);
        free(seam);
        if (rc != MAPGEN_SEAMS_OK)
            bad = 1;
    }

    if (do_stand) {
        float g = 0.0f;
        const bool got = ground_under(&ctx, bsp, stand, 768.0f, &g);
        const float head = headroom_over(&ctx, bsp, stand);
        printf("stand %.0f %.0f %.0f: ground %s%.0f, headroom %.0f\n",
               (double)stand[0], (double)stand[1], (double)stand[2],
               got ? "" : "none ", (double)g, (double)head);
        if (!got || head < 57.0f)
            bad = 1;
    }

    if (do_walk) {
        float d[3];
        float span = 0.0f;
        for (int a = 0; a < 3; a++) {
            d[a] = to[a] - from[a];
            span += d[a] * d[a];
        }
        span = sqrtf(span);
        const uint32_t n = (uint32_t)(span / step) + 1u;
        float last = 0.0f;
        bool have_last = false;
        uint32_t walkable = 0, tall = 0, steep = 0, missing = 0;
        float worst_step = 0.0f, worst_head = 1e9f;
        for (uint32_t i = 0; i <= n; i++) {
            const float f = (float)i / (float)n;
            float at[3];
            for (int a = 0; a < 3; a++)
                at[a] = from[a] + d[a] * f;
            /* the ground under the sample itself, not under a point a
               storey above it: a tunnel has a ceiling */
            /*
             * The whole storey, not 320 units: a lift shaft is as deep as the
             * drop it replaces, and one of mg_tunnels' own is 608.
             */
            float g = 0.0f;
            const bool got = ground_under(&ctx, bsp, at, 768.0f, &g);
            if (!got) {
                missing++;
                printf("  %4u  %7.0f %7.0f %7.0f  NO GROUND within a storey\n",
                       i, (double)at[0], (double)at[1], (double)at[2]);
                have_last = false;
                continue;
            }
            float on[3] = { at[0], at[1], g + 1.0f };
            const float head = headroom_over(&ctx, bsp, on);
            if (head < worst_head)
                worst_head = head;
            float rise = 0.0f;
            if (have_last) {
                rise = g - last;
                if (fabsf(rise) > worst_step)
                    worst_step = fabsf(rise);
                if (rise > STEP_MAX)
                    steep++;
            }
            if (head >= HEADROOM)
                tall++;
            walkable++;
            printf("  %4u  %7.0f %7.0f %7.0f  ground %6.0f  rise %+5.0f"
                   "  headroom %5.0f%s%s\n", i, (double)at[0], (double)at[1],
                   (double)at[2], (double)g, (double)rise, (double)head,
                   rise > STEP_MAX ? "  TOO STEEP" : "",
                   head < 57.0f ? "  CANNOT STAND" : "");
            last = g;
            have_last = true;
        }
        printf("walk %u samples: %u with ground, %u missing, %u too steep,"
               " %u with %0.f of headroom; worst rise %.0f, worst headroom"
               " %.0f\n", n + 1u, walkable, missing, steep, tall,
               (double)HEADROOM, (double)worst_step, (double)worst_head);
        if (missing || steep || worst_head < 57.0f)
            bad = 1;
    }

    MapGenTrace_Release(&ctx);
    MapGenBsp_Free(bsp);
    return bad;
}
