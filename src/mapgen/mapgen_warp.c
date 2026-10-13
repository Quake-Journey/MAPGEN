/*
 * MAPGEN-1 - the warp: the donor's plan stretched and squeezed part by part (see mapgen_warp.h).
 */
#include "common/mapgen_trace.h"
#include "common/mapgen_warp.h"
#include "common/mapgen_bsp.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WARP_SURF_HINT   0x0100
#define WARP_SURF_SKIP   0x0200
/*
 * A cut crossing a brush by more than this splits it. Not more: a wall that ran 1 past a cut and went whole with its
 * middle's part ended 0.4 off its neighbour, which began exactly there and went with the other part - MEASURED, q2dm1
 * at 200 % and every spread from 7 to 60 leaked; the plane along an axis is now taken by the one continuous map.
 */
#define WARP_SPLIT_INSIDE 0.01f
/* a brush no wider than this keeps its texture stretched with it - a lamp, a button, a sign - not repeated */
#define WARP_SMALL_BRUSH 64.0f
/* the bands a cut keeps away from */
#define WARP_BAND_MARGIN 16.0f
#define WARP_TRAVEL_CAP  256.0f
#define WARP_CUT_STEP    8.0f
#define WARP_END_KEEP    128.0f
#define WARP_CUT_GAP     160.0f
#define WARP_PART_LEN    640.0f
/*
 * A cut placed within this of a wall's end leaves a sliver of it - a few units of wall in the next part. Leaning, a
 * sliver is a thin slanted wedge whose plane a rebuild states from points a few units apart; q2dm1 shifted 60 %: a
 * 5-unit wedge at x 946 came back off by a hundredth over its height and the rebuilt base leaked (10.10). The cut
 * goes where the fewest walls end that near it (a wall ending exactly on it is no sliver).
 */
#define WARP_SLIVER      24.0f
#define WARP_PI          3.14159265358979f

/* ---- the map of one axis ------------------------------------------------------------------------------------- */

void MapGenWarp_Identity(mapgen_warp_t *w)
{
    memset(w, 0, sizeof(*w));
    w->asked_size = 100;
    w->area_permille = 1000;
}

bool MapGenWarp_IsIdentity(const mapgen_warp_t *w)
{
    if (!w)
        return true;
    if (w->turns || w->mirror)
        return false;
    for (int a = 0; a < 2; a++)
        for (uint32_t i = 0; i <= w->num[a] && w->num[a]; i++)
            if (fabsf(w->lean[a][i]) > 0.01f)
                return false;
    for (int a = 0; a < 3; a++)
        for (uint32_t i = 0; i <= w->num[a] && w->num[a]; i++)
            if (fabsf(w->to[a][i] - w->at[a][i]) > 0.01f)
                return false;
    return true;
}

static void part_map(const mapgen_warp_t *w, int axis, float v, float *k, float *b)
{
    *k = 1.0f;
    *b = 0.0f;
    if (!w || axis < 0 || axis > 2 || !w->num[axis])
        return;
    uint32_t i = 0;
    while (i + 1 < w->num[axis] && v >= w->at[axis][i + 1])
        i++;
    const float span = w->at[axis][i + 1] - w->at[axis][i];
    if (span <= 0.0f)
        return;
    *k = (w->to[axis][i + 1] - w->to[axis][i]) / span;
    *b = w->to[axis][i] - *k * w->at[axis][i];
}

float MapGenWarp_Point(const mapgen_warp_t *w, int axis, float v)
{
    float k, b;
    part_map(w, axis, v, &k, &b);
    return k * v + b;
}

float MapGenWarp_Factor(const mapgen_warp_t *w, int axis, float v)
{
    float k, b;
    part_map(w, axis, v, &k, &b);
    return k;
}

/* ---- the plan ------------------------------------------------------------------------------------------------ */

static uint64_t warp_mix(uint64_t *s);

bool MapGenWarp_PlanHeight(mapgen_warp_t *w, float z_lo, float z0, float z_hi, uint32_t height_pct)
{
    if (!w || height_pct <= 100u || !(z_lo < z0 && z0 < z_hi))
        return false;
    if (height_pct > 300u)
        height_pct = 300u;
    /* brief 18 D2: over the proportional heights when the map grew tall - the ceilings' line where it lands */
    const float lo = MapGenWarp_Point(w, 2, z_lo), mid = MapGenWarp_Point(w, 2, z0), hi = MapGenWarp_Point(w, 2, z_hi);
    w->num[2] = 2;
    w->at[2][0] = z_lo;
    w->at[2][1] = z0;
    w->at[2][2] = z_hi;
    w->to[2][0] = lo;
    w->to[2][1] = mid;
    /* ... and no higher than the game's coordinates hold (as `MapGenWarp_PlanTall`): q3t2 at 1000 %, as tall as it
       grew wide (its top at 3232), asked for ceilings at 200 % - 5460, past the world; the compiler cut the sky off
       («leaked») and the ceilings were given back whole. They get what the world has left - 133 % there. */
    float top = roundf(mid + (hi - mid) * (float)height_pct / 100.0f);
    if (top > 3968.0f)
        top = 3968.0f;
    if (top < hi + 16.0f)
        return false;                   /* nothing left over the proportional height */
    w->to[2][2] = top;
    w->height_pct = (uint32_t)(100.0f * (top - mid) / (hi - mid) + 0.5f);
    return true;
}

static const bool g_warp_tall = true;   /* brief 18 D2: the RED's mutation point */

bool MapGenWarp_PlanTall(mapgen_warp_t *w, float z_lo, float z_hi, float max_k)
{
    if (!w || !g_warp_tall || w->area_permille <= 1000u || !(z_lo < z_hi))
        return false;
    /* about the world's middle, and no taller than the game's coordinates hold (+-4096: a position goes over the
       network in 16 bits of eighths) - q3t2 at 1000 %, grown from its bottom, rose to 5424 and the compiler cut the sky
       off: «leaked» on every try */
    const float mid = 0.5f * (z_lo + z_hi), half = 0.5f * (z_hi - z_lo);
    float k = sqrtf((float)w->area_permille / 1000.0f);
    if (k > max_k)
        k = max_k;                      /* a try the walk refused grows less tall the next time */
    if (half * k > 3968.0f - fabsf(mid))
        k = (3968.0f - fabsf(mid)) / half;
    if (k <= 1.01f)
        return false;
    w->num[2] = 1;
    w->at[2][0] = z_lo;
    w->at[2][1] = z_hi;
    w->to[2][0] = roundf(mid - half * k);
    w->to[2][1] = roundf(mid + half * k);
    w->tall = k;
    return true;
}

/* ---- the ramps a taller map needs (brief 18 D2) ------------------------------------------------------------------ */

#define RAMP_SLOPE_TAN 0.8391f          /* tan 40 degrees: walkable (Q2 stands on a normal's z of 0.7 and up) */
#define RAMP_RISE_MAX  48.0f            /* a riser up to a jump's height gets one */
#define RAMP_MAX       6000u

/*
 * What is AT a point, brush by brush - not what its leaf says.
 *
 * A leaf carries the contents of every detail brush that touches it, so `MapGenBsp_PointContents` says «player clip»
 * of a point 8 units outside the clip brush (q3t2: the clip along the trim beside the flight at -640 126 marks the
 * leaf over every tread). Read that way the treads were «not open», no step of that flight got its ramp, and at
 * x3.11 its 8-unit risers stood 25 high - over a step's 18, each one a jump. So: a solid leaf is solid, and beyond
 * that only the brushes the point is inside count.
 */
static bool g_ramp_exact = true;        /* RED: the leaf's own word, as before 13.10 */

void MapGenWarp_SetRampExact(bool exact)
{
    g_ramp_exact = exact;
}

static int32_t ramp_contents(const mapgen_bsp_t *bsp, float x, float y, float z)
{
    const float p[3] = { x, y, z };
    if (!g_ramp_exact)
        return MapGenBsp_PointContents(bsp, p);
    const mapgen_bsp_leaf_t *leaf = MapGenBsp_PointLeaf(bsp, p);
    if (!leaf)
        return 0;
    int32_t contents = leaf->contents & 0x1;
    for (uint32_t i = 0; i < leaf->numleafbrushes; i++) {
        const mapgen_bsp_brush_t *br = MapGenBsp_Brush(bsp, MapGenBsp_LeafBrush(bsp, leaf->firstleafbrush + i));
        bool inside = br != NULL;
        for (int32_t s = 0; inside && s < br->numsides; s++) {
            const mapgen_bsp_brushside_t *side = MapGenBsp_BrushSide(bsp, (uint32_t)(br->firstside + s));
            const mapgen_bsp_plane_t *pl = side ? MapGenBsp_Plane(bsp, side->planenum) : NULL;
            inside = pl && p[0] * pl->normal[0] + p[1] * pl->normal[1] + p[2] * pl->normal[2] - pl->dist <= 0.0f;
        }
        if (inside)
            contents |= br->contents;
    }
    return contents;
}

static bool ramp_open(const mapgen_bsp_t *bsp, float x, float y, float z)
{
    return !(ramp_contents(bsp, x, y, z) & (0x1 | 0x10000));          /* neither solid nor player clip */
}

static bool ramp_solid(const mapgen_bsp_t *bsp, float x, float y, float z)
{
    return (ramp_contents(bsp, x, y, z) & 0x1) != 0;
}

uint32_t MapGenWarp_AddRamps(mapgen_geometry_t *g, const mapgen_bsp_t *ground, const mapgen_warp_t *w)
{
    if (!g || !ground || !w || w->tall <= 1.01f)
        return 0;
    uint32_t added = 0;
    const uint32_t n0 = MapGenGeometry_NumBrushes(g);
    /* the map's own player clip, to bridge the gaps a player could not fall through (below) */
    mapgen_geometry_side_t clip;
    int32_t clip_contents = 0;
    for (uint32_t c = 0; c < n0 && !clip_contents; c++) {
        const mapgen_geometry_brush_t *cb = MapGenGeometry_Brush(g, c);
        if (cb && !cb->model && (cb->contents & 0x10000) && !(cb->contents & 0x1) && cb->num_sides) {
            const mapgen_geometry_side_t *cs = MapGenGeometry_Side(g, cb->first_side);
            if (cs) {
                clip = *cs;
                clip_contents = cb->contents;
            }
        }
    }
    for (uint32_t b = 0; b < n0 && added < RAMP_MAX; b++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(g, b);
        if (!br || br->model || !(br->contents & 0x1) || br->num_sides < 5)
            continue;
        /* a flat top, standable, and no sky on it */
        const mapgen_geometry_side_t *top = NULL;
        bool sky = false;
        for (uint32_t s = 0; s < br->num_sides; s++) {
            const mapgen_geometry_side_t *sd = MapGenGeometry_Side(g, br->first_side + s);
            if (!sd)
                continue;
            if (sd->flags & 0x4)
                sky = true;
            if (sd->normal[2] > 0.999f && fabsf(sd->dist - br->maxs[2]) < 0.5f && !sd->bevel)
                top = sd;
        }
        /* a diagnostic: MAPGEN_RAMP_WHY="x y z" says what this pass does with the brush that holds the point */
        bool say = false;
        {
            const char *at = getenv("MAPGEN_RAMP_WHY");
            float q[3];
            say = at && sscanf(at, "%f %f %f", &q[0], &q[1], &q[2]) == 3 && q[0] >= br->mins[0] && q[0] <= br->maxs[0]
               && q[1] >= br->mins[1] && q[1] <= br->maxs[1] && q[2] >= br->mins[2] && q[2] <= br->maxs[2];
        }
        if (say)
            fprintf(stderr, "RAMP brush %u: %.0f %.0f %.0f .. %.0f %.0f %.0f, top %d, sky %d\n", (unsigned)b,
                    (double)br->mins[0], (double)br->mins[1], (double)br->mins[2], (double)br->maxs[0],
                    (double)br->maxs[1], (double)br->maxs[2], top ? 1 : 0, sky ? 1 : 0);
        if (!top || sky)
            continue;
        const mapgen_geometry_side_t top_side = *top;       /* the side table may move as wedges go in */
        const float zt = br->maxs[2];
        for (uint32_t s = 0; s < br->num_sides && added < RAMP_MAX; s++) {
            const mapgen_geometry_side_t *sd = MapGenGeometry_Side(g, br->first_side + s);
            if (!sd || sd->bevel)
                continue;
            int a = -1;
            if (fabsf(sd->normal[0]) > 0.999f)
                a = 0;
            else if (fabsf(sd->normal[1]) > 0.999f)
                a = 1;
            if (a < 0)
                continue;
            const int o = 1 - a;
            const float sg = sd->normal[a] > 0.0f ? 1.0f : -1.0f;
            const float face = sg > 0.0f ? br->maxs[a] : br->mins[a];
            if (fabsf(sg * sd->dist - face) > 0.5f)
                continue;
            const float lo = br->mins[o], hi = br->maxs[o];
            if (hi - lo < 16.0f)
                continue;
            /* three places along the edge: standable on top, air in front, a floor below within a jump's height */
            float zl = 0.0f;
            bool ok = true;
            for (int k = 0; k < 3 && ok; k++) {
                const float t = k == 0 ? 0.2f : k == 1 ? 0.5f : 0.8f, along = lo + (hi - lo) * t;
                float in[3], out[3];
                in[a] = face - sg * 4.0f;
                in[o] = along;
                out[a] = face + sg * 4.0f;
                out[o] = along;
                ok = ramp_open(ground, in[0], in[1], zt + 8.0f) && ramp_open(ground, in[0], in[1], zt + 40.0f)
                  && ramp_open(ground, out[0], out[1], zt + 8.0f);
                float found = -1e9f;
                for (float z = zt - 1.0f; ok && z >= zt - RAMP_RISE_MAX - 1.0f; z -= 1.0f)
                    if (ramp_solid(ground, out[0], out[1], z)) {
                        found = z + 1.0f;
                        break;
                    }
                if (say)
                    fprintf(stderr, "RAMP   sample %d at %.0f %.0f: on top open %d, head open %d, front open %d, floor "
                            "in front %.0f\n", k, (double)in[0], (double)in[1],
                            ramp_open(ground, in[0], in[1], zt + 8.0f) ? 1 : 0,
                            ramp_open(ground, in[0], in[1], zt + 40.0f) ? 1 : 0,
                            ramp_open(ground, out[0], out[1], zt + 8.0f) ? 1 : 0, (double)found);
                if (found < -1e8f && k == 0 && clip_contents) {
                    /*
                     * No floor within a jump below, and the next floor's top level with this one closer than a player
                     * is wide: a gap a player walks over in the donor (q3t2's grating at its middle). Grown, it would
                     * be wider than a player over a pocket grown deeper than a jump - bridged with the map's own clip
                     * at the floor's level, the grating still seen.
                     */
                    float gap = -1.0f;
                    for (float d = 2.0f; d <= 30.0f && gap < 0.0f; d += 1.0f) {
                        bool across = true;
                        for (int q = 0; q < 3 && across; q++) {
                            const float tq = q == 0 ? 0.2f : q == 1 ? 0.5f : 0.8f, aq = lo + (hi - lo) * tq;
                            float pq[3];
                            pq[a] = face + sg * d;
                            pq[o] = aq;
                            across = ramp_solid(ground, pq[0], pq[1], zt - 1.0f) && ramp_open(ground, pq[0], pq[1], zt + 8.0f);
                        }
                        if (across)
                            gap = d;
                    }
                    if (gap > 0.0f) {
                        mapgen_geometry_side_t cs[6];
                        for (int i = 0; i < 6; i++) {
                            cs[i] = clip;
                            cs[i].bevel = false;
                            cs[i].has_anchor = false;
                            cs[i].num_samples = 0;
                            memset(cs[i].normal, 0, sizeof(cs[i].normal));
                        }
                        cs[0].normal[2] = -1.0f;
                        cs[0].dist = -(zt - 4.0f);
                        cs[1].normal[2] = 1.0f;
                        cs[1].dist = zt;
                        cs[2].normal[a] = -sg;
                        cs[2].dist = -sg * face;
                        cs[3].normal[a] = sg;
                        cs[3].dist = sg * (face + sg * gap);
                        cs[4].normal[o] = -1.0f;
                        cs[4].dist = -lo;
                        cs[5].normal[o] = 1.0f;
                        cs[5].dist = hi;
                        for (int i = 0; i < 6; i++)
                            MapGenGeometry_AxesForNormal(cs[i].axis, cs[i].normal);
                        if (MapGenGeometry_AddBrush(g, cs, 6, clip_contents, 0) == MAPGEN_GEOMETRY_OK)
                            added++;
                        br = MapGenGeometry_Brush(g, b);
                    }
                    ok = false;
                } else if (found < -1e8f || zt - found < 2.0f)
                    ok = false;
                else if (k == 0)
                    zl = found;
                else if (fabsf(found - zl) > 2.0f)
                    ok = false;
            }
            if (!br)
                break;
            if (say)
                fprintf(stderr, "RAMP  side %u axis %d sign %.0f face %.0f along %.0f..%.0f: ok %d, lower floor %.0f\n",
                        (unsigned)s, a, (double)sg, (double)face, (double)lo, (double)hi, ok ? 1 : 0, (double)zl);
            if (!ok)
                continue;
            const float rise = zt - zl;
            const float kz = MapGenWarp_Factor(w, 2, zt), ka = MapGenWarp_Factor(w, a, face);
            if (rise * kz <= 18.0f || ka <= 0.0f)
                continue;
            /* the run on the lower floor, in donor units, that makes 40 degrees once warped */
            const float run = fmaxf(4.0f, rise * kz / (RAMP_SLOPE_TAN * ka));
            /* how far the lower floor reaches in front, up to that run */
            float room = 0.0f;
            for (float d = 4.0f; d <= run + 0.5f; d += 2.0f) {
                bool floor = true;
                for (int k = 0; k < 3 && floor; k++) {
                    const float t = k == 0 ? 0.2f : k == 1 ? 0.5f : 0.8f, along = lo + (hi - lo) * t;
                    float p[3];
                    p[a] = face + sg * (d - 1.0f);
                    p[o] = along;
                    floor = ramp_solid(ground, p[0], p[1], zl - 2.0f) && ramp_open(ground, p[0], p[1], zl + 8.0f);
                }
                if (!floor)
                    break;
                room = d;
            }
            if (say)
                fprintf(stderr, "RAMP  rise %.1f (x%.2f), run %.1f, room %.1f\n", (double)rise, (double)kz, (double)run,
                        (double)room);
            if (room < 4.0f)
                continue;
            mapgen_geometry_side_t sides[6];
            if (room < run - 0.5f) {
                /*
                 * No room for the slope (q3t2's pit at the middle: 27 deep, jumped out of, 83 once grown and too narrow
                 * for a ramp): a flight of steps instead, each rise 16 or less once warped, on the floor there is -
                 * a player steps up a riser of 18 whatever the tread.
                 */
                const int steps = (int)ceilf(rise * kz / 16.0f);
                const float each_rise = rise / (float)steps, each_run = room / (float)steps;
                if (each_run * ka < 2.0f)
                    continue;
                for (int st = 0; st < steps - 0 && added < RAMP_MAX; st++) {
                    /* step st: from the riser out to (steps - st) treads, up to (st + 1) rises - a box each */
                    const float out = each_run * (float)(steps - st), ztop = zl + each_rise * (float)(st + 1);
                    if (st == steps - 1)
                        break;                                  /* the last rise is the riser's own top */
                    for (int i = 0; i < 6; i++) {
                        sides[i] = top_side;
                        sides[i].bevel = false;
                        sides[i].has_anchor = false;
                        sides[i].num_samples = 0;
                        memset(sides[i].normal, 0, sizeof(sides[i].normal));
                    }
                    sides[0].normal[2] = -1.0f;
                    sides[0].dist = -(zl - 1.0f);
                    sides[1].normal[2] = 1.0f;
                    sides[1].dist = ztop;
                    sides[2].normal[a] = -sg;
                    sides[2].dist = -sg * face;
                    sides[3].normal[a] = sg;
                    sides[3].dist = sg * (face + sg * out);
                    sides[4].normal[o] = -1.0f;
                    sides[4].dist = -lo;
                    sides[5].normal[o] = 1.0f;
                    sides[5].dist = hi;
                    for (int i = 0; i < 6; i++)
                        MapGenGeometry_AxesForNormal(sides[i].axis, sides[i].normal);
                    if (MapGenGeometry_AddBrush(g, sides, 6, br->contents, 0) == MAPGEN_GEOMETRY_OK)
                        added++;
                }
                br = MapGenGeometry_Brush(g, b);
                if (!br)
                    break;
                continue;
            }
            for (int i = 0; i < 6; i++) {
                sides[i] = top_side;
                sides[i].bevel = false;
                sides[i].has_anchor = false;
                sides[i].num_samples = 0;
                memset(sides[i].normal, 0, sizeof(sides[i].normal));
            }
            sides[0].normal[2] = -1.0f;                         /* the bottom, into the floor */
            sides[0].dist = -(zl - 1.0f);
            sides[1].normal[a] = -sg;                           /* against the riser */
            sides[1].dist = -sg * face;
            sides[2].normal[a] = sg;                            /* the foot */
            sides[2].dist = sg * (face + sg * run);
            sides[3].normal[o] = -1.0f;
            sides[3].dist = -lo;
            sides[4].normal[o] = 1.0f;
            sides[4].dist = hi;
            {                                                   /* the slope: through (face, zt) and (face + run, zl) */
                const float len = sqrtf(rise * rise + run * run);
                sides[5].normal[a] = sg * rise / len;
                sides[5].normal[2] = run / len;
                sides[5].dist = (sg * rise * face + run * zt) / len;
            }
            for (int i = 0; i < 6; i++)
                MapGenGeometry_AxesForNormal(sides[i].axis, sides[i].normal);
            if (MapGenGeometry_AddBrush(g, sides, 6, br->contents, 0) == MAPGEN_GEOMETRY_OK)
                added++;
            br = MapGenGeometry_Brush(g, b);                    /* the table may have moved */
            if (!br)
                break;
        }
    }
    return added;
}

/*
 * Brief 18 D2: a pickup keeps its height over the floor under it.
 *
 * The game drops a pickup to the floor when it spawns, through 128 units and no further; one that starts higher hangs
 * where the drop ends. Grown tall with the map, a pickup 16 over its floor stood 50 over it and still landed - and
 * q3t2's three shotguns at -944 16, one on the floor and two more 96 and 128 over it (they all land in the donor),
 * stood 298 and 398 over it at x3.11: the top one hung 220 over the floor, out of any player's reach, and the walk
 * refused the map its proportional height for that one pickup.
 *
 * So, in the donor before the warp: each pickup with a floor within the game's drop under it is put where the warp
 * will leave it as high over that floor as it was. Returns how many moved.
 *
 * And a player's START alike (mg_b18_q3t2 on 3.32, 13.10): q3t2's stand 15 over their floors, 46.6 at x3.11 - the
 * game puts a player nine over a start and he falls 31, harmless, but a start is asked a floor within 32 of his
 * feet and 12 of 13 were «over no floor». Asked from nine over it, as the game puts the player down (at its own
 * height the pickup's box lies IN the floor it stands 15 over).
 */
static bool g_warp_keep_drops = true;   /* RED: pickups grow away from their floors with the map */
static bool g_warp_keep_starts = true;  /* RED: ... and the starts with them */

void MapGenWarp_SetKeepStarts(bool keep)
{
    g_warp_keep_starts = keep;
}

void MapGenWarp_SetKeepDrops(bool keep)
{
    g_warp_keep_drops = keep;
}

uint32_t MapGenWarp_KeepDrops(mapgen_geometry_t *g, const mapgen_bsp_t *ground, const mapgen_warp_t *w)
{
    if (!g || !ground || !w || w->tall <= 1.01f || !g_warp_keep_drops)
        return 0;
    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (!MapGenTrace_Bind(&ctx, ground))
        return 0;
    /* the game's own drop: the pickup's box, 128 down, against what is solid - the world and every machine at rest */
    static const float mins[3] = { -15.0f, -15.0f, -15.0f }, maxs[3] = { 15.0f, 15.0f, 15.0f };
    static const float still[3] = { 0.0f, 0.0f, 0.0f };
    uint32_t moved = 0;
    const uint32_t n = MapGenGeometry_NumEntities(g);
    for (uint32_t e = 0; e < n; e++) {
        const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(g, e);
        const char *cls = ent && ent->has_origin && !ent->model ? MapGenGeometry_EntityValue(g, e, "classname") : NULL;
        const bool start = cls && !strncmp(cls, "info_player_", 12);
        if (!cls || (!(start && g_warp_keep_starts) && strncmp(cls, "weapon_", 7) && strncmp(cls, "item_", 5)
                     && strncmp(cls, "ammo_", 5) && strncmp(cls, "key_", 4)))
            continue;
        const float lift = start ? 9.0f : 0.0f;
        const float from[3] = { ent->origin[0], ent->origin[1], ent->origin[2] + lift };
        const float down[3] = { from[0], from[1], ent->origin[2] - 128.0f };
        mapgen_trace_result_t hit;
        MapGenTrace_Box(&ctx, from, down, mins, maxs, MAPGEN_TRACE_SOLID | MAPGEN_TRACE_WINDOW, &hit);
        for (uint32_t m = 0; m < n; m++) {
            const mapgen_geometry_entity_t *me = MapGenGeometry_Entity(g, m);
            const char *mc = me && me->model ? MapGenGeometry_EntityValue(g, m, "classname") : NULL;
            if (mc && !strncmp(mc, "func_", 5))
                MapGenTrace_BoxModel(&ctx, me->model, still, from, down, mins, maxs,
                                     MAPGEN_TRACE_SOLID | MAPGEN_TRACE_WINDOW, &hit);
        }
        if (hit.startsolid || hit.allsolid || hit.fraction >= 1.0f)
            continue;                   /* in a solid (the game frees it) or with nothing under its drop: as it was */
        const float floor = hit.endpos[2] - 15.0f, kz = MapGenWarp_Factor(w, 2, floor);
        if (kz <= 1.01f || ent->origin[2] <= floor)
            continue;
        const float to[3] = { from[0], from[1], floor + (ent->origin[2] - floor) / kz };
        if (fabsf(to[2] - ent->origin[2]) > 0.25f && MapGenGeometry_MoveEntity(g, e, to) == MAPGEN_GEOMETRY_OK)
            moved++;
    }
    MapGenTrace_Release(&ctx);
    return moved;
}

void MapGenWarp_PlanTurn(mapgen_warp_t *w, uint64_t seed, int32_t turn)
{
    if (!w)
        return;
    if (turn == 8) {
        uint64_t s = seed ^ 0x7D1B5A3C9E4F2601ull;
        turn = 1 + (int32_t)(warp_mix(&s) % 7u);
    }
    if (turn < 0 || turn > 7)
        turn = 0;
    w->turns = (uint32_t)turn & 3u;
    w->mirror = (turn & 4) != 0;
}

static uint64_t warp_mix(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

static float warp_unit(uint64_t *s)          /* -1 .. 1 */
{
    return (float)((double)(warp_mix(s) >> 11) / (double)(1ull << 53)) * 2.0f - 1.0f;
}

typedef struct {
    float lo, hi;
} band_t;

typedef struct {
    band_t  *band[2];
    uint32_t num[2], cap[2];
} bands_t;

static void band_add(bands_t *bs, int axis, float lo, float hi)
{
    if (bs->num[axis] == bs->cap[axis]) {
        const uint32_t want = bs->cap[axis] ? bs->cap[axis] * 2u : 64u;
        band_t *grown = realloc(bs->band[axis], (size_t)want * sizeof(*grown));
        if (!grown)
            return;
        bs->band[axis] = grown;
        bs->cap[axis] = want;
    }
    bs->band[axis][bs->num[axis]].lo = lo - WARP_BAND_MARGIN;
    bs->band[axis][bs->num[axis]].hi = hi + WARP_BAND_MARGIN;
    bs->num[axis]++;
}

static bool band_free(const bands_t *bs, int axis, float v)
{
    for (uint32_t i = 0; i < bs->num[axis]; i++)
        if (v >= bs->band[axis][i].lo && v <= bs->band[axis][i].hi)
            return false;
    return true;
}

static bool entity_class(const mapgen_geometry_t *g, uint32_t e, const char *cls)
{
    const char *c = MapGenGeometry_EntityValue(g, e, "classname");
    return c && !strcmp(c, cls);
}

static bool entity_point(const mapgen_geometry_t *g, uint32_t e, float p[3])
{
    const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(g, e);
    if (!ent || !ent->has_origin)
        return false;
    memcpy(p, ent->origin, sizeof(float) * 3);
    return true;
}

static uint32_t entity_named(const mapgen_geometry_t *g, const char *name)
{
    for (uint32_t e = 0; name && *name && e < MapGenGeometry_NumEntities(g); e++) {
        const char *t = MapGenGeometry_EntityValue(g, e, "targetname");
        if (t && !strcmp(t, name))
            return e;
    }
    return UINT32_MAX;
}

/* every model's bounds, over its own brushes */
static bool model_bounds(const mapgen_geometry_t *g, float (**lo)[3], float (**hi)[3], uint8_t **has)
{
    const uint32_t nm = MapGenGeometry_NumModels(g) + 1u;
    *lo = calloc(nm, sizeof(**lo));
    *hi = calloc(nm, sizeof(**hi));
    *has = calloc(nm, 1);
    if (!*lo || !*hi || !*has)
        return false;
    for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(g); b++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(g, b);
        if (!br || br->model >= nm)
            continue;
        for (int a = 0; a < 3; a++) {
            if (!(*has)[br->model] || br->mins[a] < (*lo)[br->model][a])
                (*lo)[br->model][a] = br->mins[a];
            if (!(*has)[br->model] || br->maxs[a] > (*hi)[br->model][a])
                (*hi)[br->model][a] = br->maxs[a];
        }
        (*has)[br->model] = 1;
    }
    return true;
}

bool MapGenWarp_Plan(const mapgen_geometry_t *g, uint64_t seed, uint32_t size_pct, uint32_t shape_pct,
                     uint32_t shift_pct, mapgen_warp_t *out)
{
    if (!out)
        return false;
    MapGenWarp_Identity(out);
    out->asked_size = size_pct;
    out->asked_shape = shape_pct;
    if (shift_pct > 100u)
        shift_pct = 100u;
    if (!g || (size_pct == 100u && shape_pct == 0u && shift_pct == 0u))
        return g != NULL;
    if (size_pct < 10u)
        size_pct = 10u;
    if (size_pct > 1000u)
        size_pct = 1000u;
    if (shape_pct > 100u)
        shape_pct = 100u;

    /* the world's extent */
    float lo[2] = { 1e30f, 1e30f }, hi[2] = { -1e30f, -1e30f };
    for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(g); b++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(g, b);
        if (!br || br->model)
            continue;
        for (int a = 0; a < 2; a++) {
            lo[a] = fminf(lo[a], br->mins[a]);
            hi[a] = fmaxf(hi[a], br->maxs[a]);
        }
    }
    if (lo[0] >= hi[0] || lo[1] >= hi[1])
        return false;

    /*
     * The bands no cut may cross. A machine is moved whole with its part, so a cut through it, or through the room it
     * travels in, would leave it a different size from its slot: every brush model (doors, lifts, trains, buttons,
     * triggers, pushes) with its own extent again on each side for its travel (to WARP_TRAVEL_CAP); a train's path from
     * corner to corner; every areaportal (the compiler wants exactly one brush for each).
     */
    bands_t bs;
    memset(&bs, 0, sizeof(bs));
    float (*mlo)[3] = NULL, (*mhi)[3] = NULL;
    uint8_t *mhas = NULL;
    if (!model_bounds(g, &mlo, &mhi, &mhas)) {
        free(mlo);
        free(mhi);
        free(mhas);
        return false;
    }
    for (uint32_t m = 1; m <= MapGenGeometry_NumModels(g); m++) {
        if (!mhas[m])
            continue;
        for (int a = 0; a < 2; a++) {
            const float travel = fminf(mhi[m][a] - mlo[m][a], WARP_TRAVEL_CAP);
            band_add(&bs, a, mlo[m][a] - travel, mhi[m][a] + travel);
        }
    }
    for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(g); b++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(g, b);
        if (br && !br->model && (br->contents & MAPGEN_CONTENTS_AREAPORTAL))
            for (int a = 0; a < 2; a++)
                band_add(&bs, a, br->mins[a], br->maxs[a]);
    }
    for (uint32_t e = 0; e < MapGenGeometry_NumEntities(g); e++) {
        if (!entity_class(g, e, "func_train"))
            continue;
        uint32_t at = entity_named(g, MapGenGeometry_EntityValue(g, e, "target"));
        float prev[3];
        bool has_prev = false;
        for (uint32_t step = 0; at != UINT32_MAX && step < 64u; step++) {
            float p[3];
            if (!entity_point(g, at, p))
                break;
            if (has_prev)
                for (int a = 0; a < 2; a++)
                    band_add(&bs, a, fminf(prev[a], p[a]) - 64.0f, fmaxf(prev[a], p[a]) + 64.0f);
            memcpy(prev, p, sizeof(prev));
            has_prev = true;
            const uint32_t next = entity_named(g, MapGenGeometry_EntityValue(g, at, "target"));
            if (next == at)
                break;
            at = next;
        }
    }
    free(mlo);
    free(mhi);
    free(mhas);

    uint64_t stream = seed ^ 0x57A2F1D3C0B4E599ull;
    const float area = (float)size_pct / 100.0f;
    const float sigma = (float)shape_pct / 100.0f * logf(2.2f);
    for (int a = 0; a < 2; a++) {
        const float len = hi[a] - lo[a];
        /* the size asked, as the game's coordinates allow */
        float mean = sqrtf(area);
        if (mean * len > 2.0f * MAPGEN_WARP_WORLD_HALF)
            mean = 2.0f * MAPGEN_WARP_WORLD_HALF / len;
        if (mean < MAPGEN_WARP_MIN_FACTOR)
            mean = MAPGEN_WARP_MIN_FACTOR;
        /* the cuts: evenly meant, jittered by the seed, moved to the nearest place no band holds */
        uint32_t want = 1;
        if (shape_pct || shift_pct) {
            want = (uint32_t)lroundf(len / WARP_PART_LEN);
            want = want < 2u ? 2u : want > MAPGEN_WARP_MAX_PARTS ? MAPGEN_WARP_MAX_PARTS : want;
        }
        float edge[MAPGEN_WARP_MAX_PARTS + 1];
        uint32_t n = 0;
        edge[n++] = lo[a];
        for (uint32_t j = 1; j < want; j++) {
            const float ideal = lo[a] + len * (float)j / (float)want + warp_unit(&stream) * len / (5.0f * (float)want);
            const float reach = len / (2.5f * (float)want);
            float best = 0.0f, best_d = 1e30f;
            uint32_t best_slivers = UINT32_MAX;
            for (float c = lo[a] + WARP_END_KEEP; c <= hi[a] - WARP_END_KEEP; c += WARP_CUT_STEP) {
                const float d = fabsf(c - ideal);
                if (d > reach || c < edge[n - 1] + WARP_CUT_GAP || !band_free(&bs, a, c))
                    continue;
                /* only a leaning part makes a sliver slanted; straight, it rebuilds exactly and the cut stays where
                   it always went */
                uint32_t slivers = 0;
                for (uint32_t b = 0; shift_pct && b < MapGenGeometry_NumBrushes(g) && slivers <= best_slivers; b++) {
                    const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(g, b);
                    if (!br || br->model || br->mins[a] >= c || br->maxs[a] <= c)
                        continue;                   /* a brush the cut does not cross */
                    if (c - br->mins[a] < WARP_SLIVER || br->maxs[a] - c < WARP_SLIVER)
                        slivers++;
                }
                if (slivers > best_slivers || (slivers == best_slivers && d >= best_d))
                    continue;
                best = c;
                best_d = d;
                best_slivers = slivers;
            }
            if (best_d < 1e29f)
                edge[n++] = best;
            else
                out->cuts_refused++;
        }
        if (n > 1 && hi[a] - edge[n - 1] < WARP_CUT_GAP)
            n--;                                    /* the last part too short: its cut goes */
        edge[n++] = hi[a];
        const uint32_t parts = n - 1;

        /* the factors: drawn, then held to the mean over the whole length and to what a part can take */
        float f[MAPGEN_WARP_MAX_PARTS], raw[MAPGEN_WARP_MAX_PARTS];
        bool pinned[MAPGEN_WARP_MAX_PARTS];
        for (uint32_t i = 0; i < parts; i++) {
            raw[i] = expf(sigma * warp_unit(&stream));
            pinned[i] = false;
        }
        for (int iter = 0; iter < 8; iter++) {
            float free_raw = 0.0f, pinned_len = 0.0f;
            for (uint32_t i = 0; i < parts; i++) {
                const float l = edge[i + 1] - edge[i];
                if (pinned[i])
                    pinned_len += f[i] * l;
                else
                    free_raw += raw[i] * l;
            }
            const float rest = mean * len - pinned_len;
            bool moved = false;
            for (uint32_t i = 0; i < parts; i++) {
                if (pinned[i])
                    continue;
                f[i] = free_raw > 0.0f ? raw[i] * rest / free_raw : mean;
                if (f[i] < MAPGEN_WARP_MIN_FACTOR || f[i] > MAPGEN_WARP_MAX_FACTOR) {
                    f[i] = f[i] < MAPGEN_WARP_MIN_FACTOR ? MAPGEN_WARP_MIN_FACTOR : MAPGEN_WARP_MAX_FACTOR;
                    pinned[i] = true;
                    moved = true;
                }
            }
            if (!moved)
                break;
        }
        /* where the edges land: the map's middle stays, the whole kept inside the game's coordinates */
        float total = 0.0f;
        for (uint32_t i = 0; i < parts; i++)
            total += f[i] * (edge[i + 1] - edge[i]);
        if (total > 2.0f * MAPGEN_WARP_WORLD_HALF) {
            const float s = 2.0f * MAPGEN_WARP_WORLD_HALF / total;
            for (uint32_t i = 0; i < parts; i++)
                f[i] *= s;
            total *= s;
        }
        float start = 0.5f * (lo[a] + hi[a]) - 0.5f * total;
        if (start < -MAPGEN_WARP_WORLD_HALF)
            start = -MAPGEN_WARP_WORLD_HALF;
        if (start + total > MAPGEN_WARP_WORLD_HALF)
            start = MAPGEN_WARP_WORLD_HALF - total;
        out->num[a] = parts;
        float at_to = roundf(start);
        for (uint32_t i = 0; i <= parts; i++) {
            out->at[a][i] = edge[i];
            out->to[a][i] = at_to;
            if (i < parts)
                at_to = roundf(at_to + f[i] * (edge[i + 1] - edge[i]));
        }
    }
    /*
     * The leans: along each axis, every part slides the other way by its own slope (up to 0.45 at 100 %, ~24 degrees),
     * a part a machine's band touches by none - it moves over whole; the offsets centred, and held so the map stays
     * inside the game's coordinates.
     */
    if (shift_pct) {
        const float most = 0.45f * (float)shift_pct / 100.0f;
        for (int a = 0; a < 2; a++) {
            const int other = 1 - a;
            float low = 0.0f, high = 0.0f;
            out->lean[a][0] = 0.0f;
            for (uint32_t i = 0; i < out->num[a]; i++) {
                bool rigid = false;
                for (uint32_t k = 0; k < bs.num[a] && !rigid; k++)
                    rigid = bs.band[a][k].hi > out->at[a][i] && bs.band[a][k].lo < out->at[a][i + 1];
                const float slope = rigid ? 0.0f : most * warp_unit(&stream);
                out->lean[a][i + 1] = out->lean[a][i] + slope * (out->at[a][i + 1] - out->at[a][i]);
                low = fminf(low, out->lean[a][i + 1]);
                high = fmaxf(high, out->lean[a][i + 1]);
            }
            const float mid = 0.5f * (low + high);
            const float extent = out->to[other][out->num[other]] - out->to[other][0];
            float scale = 1.0f;
            if (extent + (high - low) > 2.0f * MAPGEN_WARP_WORLD_HALF)
                scale = fmaxf(0.0f, (2.0f * MAPGEN_WARP_WORLD_HALF - extent) / (high - low));
            for (uint32_t i = 0; i <= out->num[a]; i++)
                out->lean[a][i] = roundf((out->lean[a][i] - mid) * scale);
        }
        out->shift_pct = shift_pct;
    }
    free(bs.band[0]);
    free(bs.band[1]);
    const float was = (hi[0] - lo[0]) * (hi[1] - lo[1]);
    const float now = (out->to[0][out->num[0]] - out->to[0][0]) * (out->to[1][out->num[1]] - out->to[1][0]);
    out->area_permille = was > 0.0f ? (uint32_t)lroundf(1000.0f * now / was) : 1000u;
    return true;
}

void MapGenWarp_Describe(const mapgen_warp_t *w, char *out, size_t cap)
{
    if (!out || !cap)
        return;
    out[0] = '\0';
    if (!w)
        return;
    size_t used = 0;
    /* a shift said only when some part did lean: a part a machine touches only moves over */
    bool leaned = false;
    for (int a = 0; a < 2; a++)
        for (uint32_t i = 0; w->num[a] && i < w->num[a] && !leaned; i++)
            leaned = fabsf((w->lean[a][i + 1] - w->lean[a][i]) / (w->at[a][i + 1] - w->at[a][i])) > 0.01f;
    for (int a = 0; a < 2; a++) {
        used += (size_t)snprintf(out + used, used < cap ? cap - used : 0, "%s%c=", a ? " " : "", a ? 'y' : 'x');
        for (uint32_t i = 0; i < (w->num[a] ? w->num[a] : 1u); i++) {
            const float k = w->num[a] ? (w->to[a][i + 1] - w->to[a][i]) / (w->at[a][i + 1] - w->at[a][i]) : 1.0f;
            used += (size_t)snprintf(out + used, used < cap ? cap - used : 0, "%s%.2f", i ? "," : "", (double)k);
        }
    }
    snprintf(out + (used < cap ? used : cap - 1), used < cap ? cap - used : 1,
             " area=%u turn=%u mirror=%d height=%u shift=%u", (unsigned)((w->area_permille + 5u) / 10u),
             (unsigned)(w->turns * 90u), w->mirror ? 1 : 0, (unsigned)(w->height_pct ? w->height_pct : 100u),
             (unsigned)(leaned ? w->shift_pct : 0u));
}

/* ---- the warp itself ----------------------------------------------------------------------------------------- */

/*
 * One cell's straight map: x' = kx x + cxy y + bx, y' = cyx x + ky y + by, z' = kz z + bz. `cxy` the lean of the
 * Y-part (an X offset growing along Y), `cyx` the X-part's; `lx`, `ly` the cell's constant X and Y offsets when its
 * lean is none (an axis plane then goes by the one continuous map plus that offset, exactly).
 */
typedef struct {
    float k[3], b[3];
    float cxy, cyx, lx, ly;
} affine_t;

/* the lean of the part holding `v` on `axis`: its slope and its offset at v = 0 */
static void lean_of(const mapgen_warp_t *w, int axis, float v, float *slope, float *offset)
{
    *slope = 0.0f;
    *offset = 0.0f;
    if (!w || axis < 0 || axis > 1 || !w->num[axis])
        return;
    uint32_t i = 0;
    while (i + 1 < w->num[axis] && v >= w->at[axis][i + 1])
        i++;
    const float span = w->at[axis][i + 1] - w->at[axis][i];
    *slope = span > 0.0f ? (w->lean[axis][i + 1] - w->lean[axis][i]) / span : 0.0f;
    *offset = w->lean[axis][i] - *slope * w->at[axis][i];
}

static affine_t affine_at(const mapgen_warp_t *w, const float p[3])
{
    affine_t m;
    for (int a = 0; a < 3; a++)
        part_map(w, a, p[a], &m.k[a], &m.b[a]);
    float sx, ox, sy, oy;
    lean_of(w, 0, p[0], &sx, &ox);          /* the X-part: a Y offset growing along X */
    lean_of(w, 1, p[1], &sy, &oy);          /* the Y-part: an X offset growing along Y */
    m.cyx = sx;
    m.b[1] += ox;
    m.cxy = sy;
    m.b[0] += oy;
    m.lx = sy == 0.0f ? oy : 0.0f;
    m.ly = sx == 0.0f ? ox : 0.0f;
    return m;
}

static void affine_apply(const affine_t *m, const float p[3], float out[3])
{
    const float x = p[0], y = p[1], z = p[2];
    out[0] = m->k[0] * x + m->cxy * y + m->b[0];
    out[1] = m->cyx * x + m->k[1] * y + m->b[1];
    out[2] = m->k[2] * z + m->b[2];
}

/* a covector through the map's inverse transpose (a plane's normal, a texture axis) */
static void affine_covector(const affine_t *m, const double v[3], double out[3])
{
    const double det = (double)m->k[0] * m->k[1] - (double)m->cxy * m->cyx;
    out[0] = ((double)m->k[1] * v[0] - (double)m->cyx * v[1]) / det;
    out[1] = (-(double)m->cxy * v[0] + (double)m->k[0] * v[1]) / det;
    out[2] = v[2] / m->k[2];
}

static void warp_point(const mapgen_warp_t *w, const float p[3], float out[3])
{
    const affine_t m = affine_at(w, p);
    affine_apply(&m, p, out);
}

static affine_t affine_parts(const mapgen_warp_t *w, float x, float y, float z)
{
    const float p[3] = { x, y, z };
    return affine_at(w, p);
}

static float snap8(float v)
{
    return roundf(v * 8.0f) / 8.0f;
}

/*
 * One side through a part's straight map p' = (kx x + bx, ky y + by, z): the plane by the inverse transpose, the
 * anchors as points. The texture: `lock` - stretched with the brush (its axes through the same map); otherwise its
 * size kept on the wall and its offset moved with the brush (`shift`, where the brush's middle went).
 */
static void warp_side(mapgen_geometry_side_t *s, const mapgen_warp_t *w, const affine_t *m, const float shift[3],
                      bool lock)
{
    const float was_normal[3] = { s->normal[0], s->normal[1], s->normal[2] }, was_dist = s->dist;
    const double nv[3] = { s->normal[0], s->normal[1], s->normal[2] };
    double n[3];
    affine_covector(m, nv, n);
    const double d = (double)s->dist + n[0] * m->b[0] + n[1] * m->b[1] + n[2] * m->b[2];
    const double len = sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
    int axis = -1;
    for (int a = 0; a < 3; a++) {
        n[a] /= len;
        if (fabs(n[a]) < 1e-7)
            n[a] = 0.0;
        if (fabs(n[a]) > 1.0 - 1e-7)
            axis = a;
    }
    if (axis >= 0) {
        /* a plane along an axis stays exactly that, where the one continuous map puts it (the brush beside it, in the
           next part, takes the same plane to the same place). Not rounded: a slanted rock face meeting it at an edge
           goes by the map exactly, and a wall rounded to the eighth stood off it by a hair - the compiler's fill ran
           through into a pocket the donor seals and the rebuilt base disagreed with it (q2dm1, 484 samples, 10.10) */
        const float sign = was_normal[axis] > 0.0f ? 1.0f : -1.0f;
        for (int a = 0; a < 3; a++)
            s->normal[a] = a == axis ? sign : 0.0f;
        const float lean = axis == 0 ? m->lx : axis == 1 ? m->ly : 0.0f;
        s->dist = sign * (MapGenWarp_Point(w, axis, sign * was_dist) + lean);
        s->has_anchor = false;
    } else {
        for (int a = 0; a < 3; a++)
            s->normal[a] = (float)n[a];
        s->dist = (float)(d / len);
        for (int p = 0; p < 3 && s->has_anchor; p++) {
            float moved[3];
            affine_apply(m, s->anchor[p], moved);
            memcpy(s->anchor[p], moved, sizeof(moved));
        }
    }
    /* a slanted face's texture goes with it, stretched, its axes laid into the face's own plane: kept as they were,
       or only stretched, they stood off a face the warp had turned, and the rebuilt base respanned 22 of them (q2dm1
       at 300 %, DIFF_MAPPING, 10.10). What an axis has along the normal is a constant over the face - the face's
       distance times it - and goes into the offset, so the texture on the face is the same. */
    const bool stretch = lock || axis < 0;
    float was_len[2];
    for (int t = 0; t < 2; t++)
        was_len[t] = sqrtf(s->axis[t][0] * s->axis[t][0] + s->axis[t][1] * s->axis[t][1] + s->axis[t][2] * s->axis[t][2]);
    for (int t = 0; t < 2; t++) {
        if (stretch) {
            const double u[3] = { s->axis[t][0], s->axis[t][1], s->axis[t][2] };
            double uu[3];
            affine_covector(m, u, uu);
            for (int a = 0; a < 3; a++)
                s->axis[t][a] = (float)uu[a];
            s->axis[t][3] -= s->axis[t][0] * m->b[0] + s->axis[t][1] * m->b[1] + s->axis[t][2] * m->b[2];
            if (axis < 0) {
                const float c = s->axis[t][0] * s->normal[0] + s->axis[t][1] * s->normal[1]
                              + s->axis[t][2] * s->normal[2];
                for (int a = 0; a < 3; a++)
                    s->axis[t][a] -= c * s->normal[a];
                s->axis[t][3] += c * s->dist;
            }
        } else {
            s->axis[t][3] -= s->axis[t][0] * shift[0] + s->axis[t][1] * shift[1] + s->axis[t][2] * shift[2];
        }
    }
    /* an axis nearly along the face's new normal leaves nothing in the plane: the texture spans no width there (q2dm3
       at 150 %, flat1_1 at -112 540 64, span 0 - the axes gate). Such a face takes the plane's own axes, at the
       density it had */
    {
        /* (any side: one the donor never drew may carry axes along its own normal - q2dm3's sides at y 540, drawn once
           stretched) the measure the axes gate takes: |n . (u x v)| / |u x v| */
        const float *u = s->axis[0], *v = s->axis[1];
        const float cx = u[1] * v[2] - u[2] * v[1], cy = u[2] * v[0] - u[0] * v[2], cz = u[0] * v[1] - u[1] * v[0];
        const float area = sqrtf(cx * cx + cy * cy + cz * cz);
        const float span = area > 1e-9f ? fabsf(s->normal[0] * cx + s->normal[1] * cy + s->normal[2] * cz) / area : 0.0f;
        if (span < 0.5f) {
            MapGenGeometry_AxesForNormal(s->axis, s->normal);
            for (int t = 0; t < 2; t++) {
                const float l = sqrtf(s->axis[t][0] * s->axis[t][0] + s->axis[t][1] * s->axis[t][1]
                                      + s->axis[t][2] * s->axis[t][2]);
                for (int a = 0; a < 3 && l > 0.0f; a++)
                    s->axis[t][a] *= was_len[t] / l;
                s->axis[t][3] = 0.0f;
            }
        }
    }
}

/*
 * The cut face of a piece: a side nothing draws (it lies against the brush's other piece), of the brush's own kind.
 * A hint brush's cut face is a SKIP: a side with neither flag is solid to the compiler, and a brush takes its
 * contents from its first side - MEASURED, q2dm1 at 200 %: the rebuilt base read a hint piece whose first side was
 * its cut face as rock, and a courtyard with a start in it was filled (774 samples, DIFF_SPACE, 10.10).
 */
static void cut_side(mapgen_geometry_side_t *s, const mapgen_geometry_side_t *like, int axis, float sign, float dist)
{
    memset(s, 0, sizeof(*s));
    s->normal[axis] = sign;
    s->dist = sign * dist;
    MapGenGeometry_AxesForNormal(s->axis, s->normal);
    if (like) {
        memcpy(s->texture, like->texture, sizeof(s->texture));
        s->flags = like->flags;
        s->value = like->value;
    }
}

/* The side a cut face is made like: a hint brush's skip side (or its hint side, made a skip), else the first side
   with a face of its own. */
static mapgen_geometry_side_t cut_like(const mapgen_geometry_t *g, const mapgen_geometry_brush_t *br, bool *found)
{
    mapgen_geometry_side_t like;
    memset(&like, 0, sizeof(like));
    const mapgen_geometry_side_t *skip = NULL, *hint = NULL, *face = NULL;
    for (uint32_t s = 0; s < br->num_sides; s++) {
        const mapgen_geometry_side_t *side = MapGenGeometry_Side(g, br->first_side + s);
        if (!side)
            continue;
        if (!skip && (side->flags & WARP_SURF_SKIP))
            skip = side;
        if (!hint && (side->flags & WARP_SURF_HINT))
            hint = side;
        if (!face && !side->bevel)
            face = side;
    }
    *found = skip || hint || face;
    if (skip)
        like = *skip;
    else if (hint) {
        like = *hint;
        like.flags = (like.flags & ~WARP_SURF_HINT) | WARP_SURF_SKIP;
    } else if (face) {
        like = *face;
        like.flags &= ~(WARP_SURF_HINT | WARP_SURF_SKIP);
    }
    return like;
}

static float push_speed_default(const char *v)
{
    return v && *v ? (float)atof(v) : 1000.0f;
}

/* Q2's facing keys to a direction, and back (G_SetMovedir, vectoangles) */
static void facing_dir(float pitch, float yaw, float dir[3])
{
    const float p = pitch * WARP_PI / 180.0f, y = yaw * WARP_PI / 180.0f;
    dir[0] = cosf(p) * cosf(y);
    dir[1] = cosf(p) * sinf(y);
    dir[2] = -sinf(p);
}

static void dir_facing(const float dir[3], float *pitch, float *yaw)
{
    const float flat = sqrtf(dir[0] * dir[0] + dir[1] * dir[1]);
    *yaw = (dir[0] || dir[1]) ? atan2f(dir[1], dir[0]) * 180.0f / WARP_PI : 0.0f;
    if (*yaw < 0.0f)
        *yaw += 360.0f;
    *pitch = -atan2f(dir[2], flat) * 180.0f / WARP_PI;
}

static float turned_yaw(float yaw, const affine_t *m)
{
    const float y = yaw * WARP_PI / 180.0f, cx = cosf(y), sy = sinf(y);
    float d = atan2f(m->cyx * cx + m->k[1] * sy, m->k[0] * cx + m->cxy * sy) * 180.0f / WARP_PI;
    if (d < 0.0f)
        d += 360.0f;
    return roundf(d);
}

mapgen_geometry_result_t MapGenWarp_Apply(const mapgen_geometry_t *g, const mapgen_warp_t *w,
                                          mapgen_geometry_t **out)
{
    if (out)
        *out = NULL;
    if (!g || !w || !out)
        return MAPGEN_GEOMETRY_ERR_ARGS;
    mapgen_geometry_t *o = NULL;
    mapgen_geometry_result_t rc = MapGenGeometry_Empty(&o);
    if (rc != MAPGEN_GEOMETRY_OK)
        return rc;
    float (*mlo)[3] = NULL, (*mhi)[3] = NULL;
    uint8_t *mhas = NULL;
    mapgen_geometry_side_t *sides = malloc((MAPGEN_GEOMETRY_MAX_SIDES_PER_BRUSH + 4u) * sizeof(*sides));
    if (!sides || !model_bounds(g, &mlo, &mhi, &mhas)) {
        rc = MAPGEN_GEOMETRY_ERR_MEMORY;
        goto done;
    }

    /* the entities first, so every model a brush names is there */
    for (uint32_t e = 0; e < MapGenGeometry_NumEntities(g); e++) {
        const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(g, e);
        uint32_t at = 0;
        rc = MapGenGeometry_AddEntity(o, ent->model, &at);
        if (rc != MAPGEN_GEOMETRY_OK)
            goto done;
        float where[3] = { 0.0f, 0.0f, 0.0f };
        const bool model = ent->model && ent->model <= MapGenGeometry_NumModels(g) && mhas[ent->model];
        if (model)
            for (int a = 0; a < 3; a++)
                where[a] = 0.5f * (mlo[ent->model][a] + mhi[ent->model][a]);
        else if (ent->has_origin)
            memcpy(where, ent->origin, sizeof(where));
        const affine_t m = affine_at(w, where);
        const char *cls = MapGenGeometry_EntityValue(g, e, "classname");
        const bool push = cls && !strcmp(cls, "trigger_push");
        const bool light = cls && !strncmp(cls, "light", 5);
        bool had_speed = false, had_light = false;
        float push_speed = 0.0f, push_angles[2] = { 0.0f, 0.0f };
        bool push_moves = false;
        if (push) {
            /* the flight a push gives, stretched with its part: what it threw over a gap it throws over the gap now */
            const char *as = MapGenGeometry_EntityValue(g, e, "angles");
            const char *a1 = MapGenGeometry_EntityValue(g, e, "angle");
            float pitch = 0.0f, yaw = 0.0f, roll = 0.0f;
            if (as && *as)
                sscanf(as, "%f %f %f", &pitch, &yaw, &roll);
            else if (a1 && *a1)
                yaw = (float)atof(a1);
            const bool straight = (!as || !*as) && a1 && (yaw == -1.0f || yaw == -2.0f);
            if (!straight) {
                float dir[3];
                facing_dir(pitch, yaw, dir);
                const float speed = push_speed_default(MapGenGeometry_EntityValue(g, e, "speed"));
                /* brief 18 D2: a height grown kz needs the rise's speed sqrt(kz) (height goes with v^2), and the flight
                   then lasts sqrt(kz) longer - the reach's speed is the plan's factor over it */
                const float up = sqrtf(fmaxf(1.0f, m.k[2]));
                float v[3] = { speed * (m.k[0] * dir[0] + m.cxy * dir[1]) / up,
                               speed * (m.cyx * dir[0] + m.k[1] * dir[1]) / up, dir[2] * speed * up };
                push_speed = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
                if (push_speed > 0.0f) {
                    for (int a = 0; a < 3; a++)
                        v[a] /= push_speed;
                    dir_facing(v, &push_angles[0], &push_angles[1]);
                    push_moves = fabsf(push_speed - speed) > 0.5f;
                }
            }
        }
        for (uint32_t p = 0; p < ent->num_pairs; p++) {
            const char *key = NULL, *value = NULL;
            MapGenGeometry_Pair(g, ent->first_pair + p, &key, &value);
            if (!key || !value)
                continue;
            char text[96];
            const char *put = value;
            if (!strcmp(key, "origin") && ent->has_origin) {
                const affine_t om = model ? m : affine_at(w, ent->origin);
                float o3[3];
                affine_apply(&om, ent->origin, o3);
                snprintf(text, sizeof(text), "%g %g %g", (double)snap8(o3[0]), (double)snap8(o3[1]),
                         (double)snap8(o3[2]));
                put = text;
            } else if (push && push_speed > 0.0f && !strcmp(key, "speed")) {
                snprintf(text, sizeof(text), "%.0f", (double)push_speed);
                put = text;
                had_speed = true;
            } else if (push && push_speed > 0.0f && !strcmp(key, "angles")) {
                snprintf(text, sizeof(text), "%.0f %.0f 0", (double)push_angles[0], (double)push_angles[1]);
                put = text;
            } else if (push && push_speed > 0.0f && !strcmp(key, "angle")) {
                snprintf(text, sizeof(text), "%.0f", (double)push_angles[1]);
                put = text;
            } else if (!push && !strcmp(key, "angle")
                       && (fabsf(m.k[0] - m.k[1]) > 0.001f || m.cxy != 0.0f || m.cyx != 0.0f)) {
                const float yaw = (float)atof(value);
                if (yaw >= 0.0f) {
                    snprintf(text, sizeof(text), "%.0f", (double)turned_yaw(yaw, &m));
                    put = text;
                }
            } else if (!push && !strcmp(key, "angles")
                       && (fabsf(m.k[0] - m.k[1]) > 0.001f || m.cxy != 0.0f || m.cyx != 0.0f)) {
                float pitch = 0.0f, yaw = 0.0f, roll = 0.0f;
                if (sscanf(value, "%f %f %f", &pitch, &yaw, &roll) == 3) {
                    snprintf(text, sizeof(text), "%g %.0f %g", (double)pitch, (double)turned_yaw(yaw, &m),
                             (double)roll);
                    put = text;
                }
            } else if (cls && m.k[2] > 1.01f && !strcmp(key, "speed")
                       && (!strcmp(cls, "func_plat") || !strcmp(cls, "func_door") || !strcmp(cls, "func_train"))) {
                /* brief 18 D2: a lift or a door in a taller map travels kz further - in the time it took */
                snprintf(text, sizeof(text), "%.0f", (double)(atof(value) * m.k[2]));
                put = text;
            } else if (cls && m.k[2] > 1.01f && !strcmp(cls, "func_plat") && !strcmp(key, "height")) {
                snprintf(text, sizeof(text), "%.0f", (double)(atof(value) * m.k[2]));
                put = text;
            } else if (light && !strcmp(key, "light")) {
                /* the reach of a lamp, for the room round it grown or shrunk: 150 of its reach at a mean distance */
                const float was = (float)atof(value), k = sqrtf(m.k[0] * m.k[1]);
                float now = was + (k - 1.0f) * 150.0f;
                now = fmaxf(was * 0.6f, fminf(now, was * 2.5f));
                snprintf(text, sizeof(text), "%.0f", (double)now);
                put = text;
                had_light = true;
            }
            rc = MapGenGeometry_AddEntityPair(o, at, key, put);
            if (rc != MAPGEN_GEOMETRY_OK)
                goto done;
        }
        if (push && push_moves && !had_speed) {
            char text[32];
            snprintf(text, sizeof(text), "%.0f", (double)push_speed);
            if ((rc = MapGenGeometry_AddEntityPair(o, at, "speed", text)) != MAPGEN_GEOMETRY_OK)
                goto done;
        }
        if (light && !had_light && fabsf(sqrtf(m.k[0] * m.k[1]) - 1.0f) > 0.01f) {
            char text[32];
            const float k = sqrtf(m.k[0] * m.k[1]);
            snprintf(text, sizeof(text), "%.0f", (double)fmaxf(180.0f, fminf(300.0f + (k - 1.0f) * 150.0f, 750.0f)));
            if ((rc = MapGenGeometry_AddEntityPair(o, at, "light", text)) != MAPGEN_GEOMETRY_OK)
                goto done;
        }
        /* a machine or a start that faces the game's default way says so, so the turn turns it: a door with no
           «angle» slides along X, and on q2dm3 turned by 90 degrees three doors slid into their walls («3 machines
           nothing can operate against the donor's 1», 10.10) */
        if ((w->turns || w->mirror) && e && (model || (cls && (!strncmp(cls, "info_player_", 12)
                                                              || !strcmp(cls, "misc_teleporter_dest"))))
            && !MapGenGeometry_EntityValue(g, e, "angle") && !MapGenGeometry_EntityValue(g, e, "angles")
            && (rc = MapGenGeometry_AddEntityPair(o, at, "angle", "0")) != MAPGEN_GEOMETRY_OK)
            goto done;
        if (ent->has_origin) {
            const affine_t om = model ? m : affine_at(w, ent->origin);
            float moved[3];
            affine_apply(&om, ent->origin, moved);
            for (int a = 0; a < 3; a++)
                moved[a] = snap8(moved[a]);
            MapGenGeometry_MoveEntity(o, at, moved);
        }
    }

    /* the brushes: a machine whole with its part, a world brush in pieces where cuts cross it */
    for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(g); b++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(g, b);
        if (!br || br->num_sides < 4u || br->num_sides > MAPGEN_GEOMETRY_MAX_SIDES_PER_BRUSH)
            continue;
        bool has_like = false;
        const mapgen_geometry_side_t like_side = cut_like(g, br, &has_like);
        const mapgen_geometry_side_t *like = has_like ? &like_side : NULL;
        float mid[3];
        for (int a = 0; a < 3; a++)
            mid[a] = 0.5f * (br->mins[a] + br->maxs[a]);
        const bool small = br->maxs[0] - br->mins[0] <= WARP_SMALL_BRUSH && br->maxs[1] - br->mins[1] <= WARP_SMALL_BRUSH;
        const bool whole = br->model || (br->contents & MAPGEN_CONTENTS_AREAPORTAL);
        const bool lock = br->model || small;
        float pin[3];
        memcpy(pin, mid, sizeof(pin));
        if (br->model && br->model <= MapGenGeometry_NumModels(g) && mhas[br->model])
            for (int a = 0; a < 3; a++)
                pin[a] = 0.5f * (mlo[br->model][a] + mhi[br->model][a]);
        float went[3];
        warp_point(w, mid, went);
        const float shift[3] = { went[0] - mid[0], went[1] - mid[1], went[2] - mid[2] };
        /* the cuts that cross it, each axis */
        float cx[MAPGEN_WARP_MAX_PARTS + 2], cy[MAPGEN_WARP_MAX_PARTS + 2], cz[MAPGEN_WARP_MAX_PARTS + 2];
        uint32_t nx = 0, ny = 0, nz = 0;
        cx[nx++] = br->mins[0];
        cy[ny++] = br->mins[1];
        cz[nz++] = br->mins[2];
        for (uint32_t i = 1; !whole && i < w->num[0]; i++)
            if (w->at[0][i] > br->mins[0] + WARP_SPLIT_INSIDE && w->at[0][i] < br->maxs[0] - WARP_SPLIT_INSIDE)
                cx[nx++] = w->at[0][i];
        for (uint32_t i = 1; !whole && i < w->num[1]; i++)
            if (w->at[1][i] > br->mins[1] + WARP_SPLIT_INSIDE && w->at[1][i] < br->maxs[1] - WARP_SPLIT_INSIDE)
                cy[ny++] = w->at[1][i];
        for (uint32_t i = 1; !whole && i < w->num[2]; i++)
            if (w->at[2][i] > br->mins[2] + WARP_SPLIT_INSIDE && w->at[2][i] < br->maxs[2] - WARP_SPLIT_INSIDE)
                cz[nz++] = w->at[2][i];
        cx[nx++] = br->maxs[0];
        cy[ny++] = br->maxs[1];
        cz[nz++] = br->maxs[2];
        for (uint32_t ix = 0; ix + 1 < nx; ix++)
            for (uint32_t iy = 0; iy + 1 < ny; iy++)
            for (uint32_t iz = 0; iz + 1 < nz; iz++) {
                const bool cut = nx > 2 || ny > 2 || nz > 2;
                const affine_t m = whole || !cut ? affine_at(w, pin)
                                 : affine_parts(w, 0.5f * (cx[ix] + cx[ix + 1]), 0.5f * (cy[iy] + cy[iy + 1]),
                                                0.5f * (cz[iz] + cz[iz + 1]));
                uint32_t n = 0;
                for (uint32_t s = 0; s < br->num_sides; s++) {
                    const mapgen_geometry_side_t *side = MapGenGeometry_Side(g, br->first_side + s);
                    if (!side)
                        continue;
                    sides[n++] = *side;
                }
                /* the piece's own cut faces, planes of the donor, sent through the same map as every other side:
                   along an axis with no lean they land exactly where the next piece's land; leaning, they lean */
                if (ix > 0)
                    cut_side(&sides[n++], like, 0, -1.0f, cx[ix]);
                if (ix + 2 < nx)
                    cut_side(&sides[n++], like, 0, 1.0f, cx[ix + 1]);
                if (iy > 0)
                    cut_side(&sides[n++], like, 1, -1.0f, cy[iy]);
                if (iy + 2 < ny)
                    cut_side(&sides[n++], like, 1, 1.0f, cy[iy + 1]);
                if (iz > 0)
                    cut_side(&sides[n++], like, 2, -1.0f, cz[iz]);
                if (iz + 2 < nz)
                    cut_side(&sides[n++], like, 2, 1.0f, cz[iz + 1]);
                for (uint32_t s = 0; s < n; s++)
                    warp_side(&sides[s], w, &m, shift, lock || s >= br->num_sides);
                rc = MapGenGeometry_AddBrush(o, sides, n, br->contents, br->model);
                if (rc == MAPGEN_GEOMETRY_ERR_DEGENERATE)
                    rc = MAPGEN_GEOMETRY_OK;        /* a piece the cuts left empty */
                if (rc != MAPGEN_GEOMETRY_OK)
                    goto done;
            }
    }
    if (w->turns || w->mirror) {
        float lo[3] = { 1e30f, 1e30f, 1e30f }, hi[3] = { -1e30f, -1e30f, -1e30f };
        for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(o); b++) {
            const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(o, b);
            for (int a = 0; br && !br->model && a < 3; a++) {
                lo[a] = fminf(lo[a], br->mins[a]);
                hi[a] = fmaxf(hi[a], br->maxs[a]);
            }
        }
        const float pivot[3] = { roundf(0.5f * (lo[0] + hi[0])), roundf(0.5f * (lo[1] + hi[1])), 0.0f };
        const float none[3] = { 0.0f, 0.0f, 0.0f };
        /* each train's model mins before the turn: the game stands a train's MINS on its path's corners, and the
           turned box's mins is another of its corners */
        const uint32_t ne = MapGenGeometry_NumEntities(o);
        float (*train_lo)[3] = calloc(ne ? ne : 1u, sizeof(*train_lo));
        uint8_t *is_train = calloc(ne ? ne : 1u, 1);
        if (!train_lo || !is_train) {
            free(train_lo);
            free(is_train);
            rc = MAPGEN_GEOMETRY_ERR_MEMORY;
            goto done;
        }
        for (uint32_t e = 0; e < ne; e++) {
            const char *cls = MapGenGeometry_EntityValue(o, e, "classname");
            const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(o, e);
            if (!cls || strcmp(cls, "func_train") || !ent || !ent->model)
                continue;
            bool any = false;
            for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(o); b++) {
                const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(o, b);
                if (!br || br->model != ent->model)
                    continue;
                for (int a = 0; a < 3; a++)
                    train_lo[e][a] = any ? fminf(train_lo[e][a], br->mins[a]) : br->mins[a];
                any = true;
            }
            is_train[e] = any;
        }
        rc = MapGenGeometry_TransformSubset(o, NULL, NULL, pivot, w->turns, w->mirror, none);
        if (rc != MAPGEN_GEOMETRY_OK) {
            free(train_lo);
            free(is_train);
            goto done;
        }
        /*
         * And its path moved by what the turn did to its mins: where the old mins went (turned about the pivot) and
         * where the turned box's mins is now differ by the box's own turned extent. MEASURED, q2dm3 turned 90 degrees:
         * its three trains ran their old corners a width off and swept into the walls («3 machines nothing can operate
         * against the donor's 1», 10.10).
         */
        for (uint32_t e = 0; e < ne; e++) {
            if (!is_train[e])
                continue;
            const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(o, e);
            float now_lo[3] = { 1e30f, 1e30f, 1e30f };
            for (uint32_t b = 0; ent && b < MapGenGeometry_NumBrushes(o); b++) {
                const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(o, b);
                if (br && br->model == ent->model)
                    for (int a = 0; a < 3; a++)
                        now_lo[a] = fminf(now_lo[a], br->mins[a]);
            }
            float was[2] = { train_lo[e][0] - pivot[0], train_lo[e][1] - pivot[1] };
            for (uint32_t q = 0; q < w->turns; q++) {
                const float x = was[0];
                was[0] = -was[1];
                was[1] = x;
            }
            if (w->mirror)
                was[0] = -was[0];
            const float shift_by[2] = { now_lo[0] - (was[0] + pivot[0]), now_lo[1] - (was[1] + pivot[1]) };
            if (fabsf(shift_by[0]) < 0.01f && fabsf(shift_by[1]) < 0.01f)
                continue;
            /* the corners of its path, followed from its target - each moved once */
            const char *name = MapGenGeometry_EntityValue(o, e, "target");
            for (uint32_t step = 0; name && *name && step < 64u; step++) {
                uint32_t at = UINT32_MAX;
                for (uint32_t c = 0; c < ne && at == UINT32_MAX; c++) {
                    const char *tn = MapGenGeometry_EntityValue(o, c, "targetname");
                    if (tn && !strcmp(tn, name))
                        at = c;
                }
                const mapgen_geometry_entity_t *corner = at != UINT32_MAX ? MapGenGeometry_Entity(o, at) : NULL;
                if (!corner || !corner->has_origin || is_train[at] == 2u)
                    break;
                const float moved[3] = { corner->origin[0] + shift_by[0], corner->origin[1] + shift_by[1],
                                         corner->origin[2] };
                MapGenGeometry_MoveEntity(o, at, moved);
                is_train[at] = 2u;                      /* moved: a loop of corners ends here */
                name = MapGenGeometry_EntityValue(o, at, "target");
            }
        }
        free(train_lo);
        free(is_train);
    }
    {
        /* a turned plan of unequal sides, or leaning parts, may reach past the game's coordinates: moved back in */
        float tlo[2] = { 1e30f, 1e30f }, thi[2] = { -1e30f, -1e30f };
        for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(o); b++) {
            const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(o, b);
            for (int a = 0; br && !br->model && a < 2; a++) {
                tlo[a] = fminf(tlo[a], br->mins[a]);
                thi[a] = fmaxf(thi[a], br->maxs[a]);
            }
        }
        float back[3] = { 0.0f, 0.0f, 0.0f };
        for (int a = 0; a < 2; a++) {
            if (tlo[a] < -MAPGEN_WARP_WORLD_HALF)
                back[a] = roundf(-MAPGEN_WARP_WORLD_HALF - tlo[a]);
            else if (thi[a] > MAPGEN_WARP_WORLD_HALF)
                back[a] = roundf(MAPGEN_WARP_WORLD_HALF - thi[a]);
        }
        if (back[0] != 0.0f || back[1] != 0.0f)
            rc = MapGenGeometry_Transform(o, 0u, false, back);
    }
done:
    free(sides);
    free(mlo);
    free(mhi);
    free(mhas);
    if (rc != MAPGEN_GEOMETRY_OK) {
        MapGenGeometry_Free(o);
        return rc;
    }
    *out = o;
    return MAPGEN_GEOMETRY_OK;
}
