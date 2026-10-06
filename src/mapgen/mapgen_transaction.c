/*
 * MapGenTransaction - see inc/common/mapgen_transaction.h.
 *
 * The shape of every attempt is the same six steps, and the reason they are in
 * one place is that the batch applier had them in none: it mutated a candidate
 * repeatedly and compiled at the end, so no edit had a cost, no edit could be
 * discarded, and the schedule spent most of its budget on edits that move
 * nothing because nothing measured what an edit moved.
 */

#include "common/mapgen_fs.h"
#include "common/mapgen_transaction.h"
#include "mapgen_flood_rules.h"
#include "common/mapgen_equivalence.h"

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_geometry_edit.h"
#include "common/mapgen_movers.h"
#include "common/mapgen_trace.h"
#include "common/q2prox_cpu_topology.h"

#include <stdio.h>
#include <stdlib.h>
#include <math.h>

/* row 369: a crack in a skinned dig's gap is not refused (the RED's mutation point) */
static const bool g_txn_skin_gap_spared = true;
/* row 371: a skinned dig is asked the sky (the RED's mutation point) */
static const bool g_txn_sky_check = true;
/* whether the attempt being judged dressed a dig in a sky skin */
static bool s_attempt_skinned;
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <time.h>

#ifdef _WIN32
#include <direct.h>
#include <io.h>
#endif
#include "common/mapgen_digest.h"

const char *MapGenTransaction_ResultName(mapgen_transaction_result_t r)
{
    switch (r) {
    case MAPGEN_TXN_OK:           return "OK";
    case MAPGEN_TXN_ERR_ARGS:     return "ERR_ARGS";
    case MAPGEN_TXN_ERR_MEMORY:   return "ERR_MEMORY";
    case MAPGEN_TXN_ERR_DONOR:    return "ERR_DONOR";
    case MAPGEN_TXN_ERR_BASELINE:  return "ERR_BASELINE";
    case MAPGEN_TXN_ERR_JOB_ROOT: return "ERR_JOB_ROOT";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenTransaction_VerdictName(mapgen_transaction_verdict_t v)
{
    switch (v) {
    case MAPGEN_TXN_ACCEPTED:             return "ACCEPTED";
    case MAPGEN_TXN_REJECTED_NOT_APPLIED: return "REJECTED_NOT_APPLIED";
    case MAPGEN_TXN_REJECTED_WRITE:       return "REJECTED_WRITE";
    case MAPGEN_TXN_REJECTED_COMPILE:     return "REJECTED_COMPILE";
    case MAPGEN_TXN_REJECTED_UNPLAYABLE:  return "REJECTED_UNPLAYABLE";
    case MAPGEN_TXN_REJECTED_SURFACE:     return "REJECTED_SURFACE";
    case MAPGEN_TXN_REJECTED_NO_EFFECT:   return "REJECTED_NO_EFFECT";
    case MAPGEN_TXN_REJECTED_OVERSHOT:    return "REJECTED_OVERSHOT";
    case MAPGEN_TXN_REJECTED_UNMEASURED:  return "REJECTED_UNMEASURED";
    case MAPGEN_TXN_REJECTED_ORPHANED_MODEL:
        return "REJECTED_ORPHANED_MODEL";
    case MAPGEN_TXN_REJECTED_DROWNED:     return "REJECTED_DROWNED";
    case MAPGEN_TXN_REJECTED_STANDING_WATER:
        return "REJECTED_STANDING_WATER";
    case MAPGEN_TXN_REJECTED_MUTILATED_MODEL:
        return "REJECTED_MUTILATED_MODEL";
    case MAPGEN_TXN_REJECTED_BLOCKED_MACHINE:
        return "REJECTED_BLOCKED_MACHINE";
    case MAPGEN_TXN_REJECTED_BURIED_ROUTE:
        return "REJECTED_BURIED_ROUTE";
    case MAPGEN_TXN_REJECTED_WORTHLESS:
        return "REJECTED_WORTHLESS";
    case MAPGEN_TXN_REJECTED_DEAD_END:
        return "REJECTED_DEAD_END";
    case MAPGEN_TXN_REJECTED_HIDDEN:
        return "REJECTED_HIDDEN";
    case MAPGEN_TXN_REJECTED_LOST_PICKUP:
        return "REJECTED_LOST_PICKUP";
    case MAPGEN_TXN_REJECTED_BLOCKED_SPAWN:
        return "REJECTED_BLOCKED_SPAWN";
    case MAPGEN_TXN_REJECTED_SKY:
        return "REJECTED_SKY";
    case MAPGEN_TXN_REJECTED_OPEN_HIGH:
        return "REJECTED_OPEN_HIGH";
    }
    return "UNKNOWN";
}


/*
 * NOTHING NEW SEEN THROUGH THE SKY (ledger row 371, Fable's brief C6).
 *
 * The rule of `tools/check_mapgen_sky_portal.py`, asked on the attempt's own
 * compile, which has no visibility data yet - so every cluster counts as seen,
 * which is stricter. On the gate's own lattices - 32 units - since a coarser
 * one missed a storey the gate saw (row 372). TARGETS: points of the dig's box that are air in the
 * candidate, rock in the donor and under a roof (straight up the first solid is
 * not sky - a skin's gap is under its enclosure's sky). VIEWERS: per column
 * within TXN_SKY_REACH of the box, the highest air that is air in the donor too
 * and has sky over it, at a player's eye - TXN_SKY_EYE over the floor at most.
 * A line from a viewer up to a target that passes a sky brush and meets no
 * drawn face - air into a solid that is not sky - before it is a witness.
 */
#define TXN_SKY_REACH   2048.0f
#define TXN_SKY_EYE       96.0f
#define TXN_SKY_COLUMN    32.0f
#define TXN_SKY_TARGETS 8192u
#define TXN_SKY_VIEWERS 32768u
#define TXN_SURF_SKY    0x00000004
#define TXN_SOLID       0x00000001

static bool txn_air(const mapgen_bsp_t *b, const float p[3])
{
    return !(MapGenBsp_PointContents(b, p) & TXN_SOLID);
}

/*
 * Row 412: the digwalls gate's rule (`tools/check_mapgen_dig_walls.py open_high`) on an attempt's compile. Every 16
 * units in the dig's box, a point of new space (air in `built`, rock in `before`) under a roof, whose neighbour 16
 * across is old air (air in both, the half-way point air in `built`) more than 176 over the old floor and out of the
 * doorway band of the dig's two ends (32 under to 160 over an end, within 256 of it). The first such pair into
 * `said`; how many there are.
 */
#define TXN_OPEN_STEP     16.0f
#define TXN_OPEN_DOORWAY 176.0f

static uint32_t dig_opens_high(const mapgen_bsp_t *built, const mapgen_bsp_t *before, const float lo[3],
                               const float hi[3], const float from[3], const float to[3], float said[6])
{
    if (!built || !before)
        return 0;
    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (!MapGenTrace_Bind(&ctx, built))
        return 0;
    const float zero[3] = { 0.0f, 0.0f, 0.0f };
    uint32_t found = 0;
    for (float x = lo[0] + 0.5f * TXN_OPEN_STEP; x < hi[0]; x += TXN_OPEN_STEP)
        for (float y = lo[1] + 0.5f * TXN_OPEN_STEP; y < hi[1]; y += TXN_OPEN_STEP)
            for (float z = lo[2] + 0.5f * TXN_OPEN_STEP; z < hi[2]; z += TXN_OPEN_STEP) {
                const float p[3] = { x, y, z };
                if (!txn_air(built, p) || txn_air(before, p))
                    continue;
                const float up[3] = { x, y, z + 4096.0f };
                mapgen_trace_result_t roof;
                memset(&roof, 0, sizeof(roof));
                MapGenTrace_Box(&ctx, p, up, zero, zero, TXN_SOLID, &roof);
                if (roof.fraction >= 1.0f || (roof.surface_flags & TXN_SURF_SKY))
                    continue;                   /* under the sky: a sky skin's gap, the dig's outside seen */
                static const float d4[4][2] = { { TXN_OPEN_STEP, 0 }, { -TXN_OPEN_STEP, 0 }, { 0, TXN_OPEN_STEP },
                                                { 0, -TXN_OPEN_STEP } };
                for (int k = 0; k < 4; k++) {
                    const float q[3] = { x + d4[k][0], y + d4[k][1], z };
                    const float mid[3] = { x + 0.5f * d4[k][0], y + 0.5f * d4[k][1], z };
                    if (!txn_air(built, q) || !txn_air(before, q) || !txn_air(built, mid))
                        continue;
                    float floor_z = q[2] - 1024.0f;
                    for (float fz = q[2]; fz > q[2] - 1024.0f; fz -= 4.0f) {
                        const float f[3] = { q[0], q[1], fz };
                        if (!txn_air(before, f)) {
                            floor_z = fz;
                            break;
                        }
                    }
                    if (q[2] - floor_z <= TXN_OPEN_DOORWAY)
                        break;
                    bool doorway = false;
                    const float *ends[2] = { from, to };
                    for (int e = 0; e < 2 && !doorway; e++) {
                        const float dz = q[2] - ends[e][2];
                        const float dx = q[0] - ends[e][0], dy = q[1] - ends[e][1];
                        doorway = dz >= -32.0f && dz <= 160.0f && dx * dx + dy * dy <= 256.0f * 256.0f;
                    }
                    if (!doorway) {
                        if (!found && said) {
                            memcpy(said, p, sizeof(p));
                            memcpy(said + 3, q, sizeof(q));
                        }
                        found++;
                    }
                    break;
                }
            }
    MapGenTrace_Release(&ctx);
    return found;
}

static bool txn_sky_line(mapgen_trace_context_t *ctx, const mapgen_bsp_t *b,
                         const mapgen_bsp_t *donor, const float from[3],
                         const float to[3])
{
    static const float zero[3] = { 0.0f, 0.0f, 0.0f };
    float p[3] = { from[0], from[1], from[2] };
    bool sky = false;
    for (int hop = 0; hop < 32; hop++) {
        mapgen_trace_result_t hit;
        memset(&hit, 0, sizeof(hit));
        MapGenTrace_Box(ctx, p, to, zero, zero, TXN_SOLID, &hit);
        if (hit.startsolid)
            return false;
        if (hit.fraction >= 1.0f)
            return sky;                     /* reached it in the air */
        if (!(hit.surface_flags & TXN_SURF_SKY))
            return false;                   /* a drawn face hides it */
        sky = true;
        /* through what it entered - sky, then maybe rock or the void, none of
           which draws a face against another solid - to the next air */
        float d[3], len = 0.0f;
        for (int a = 0; a < 3; a++) {
            d[a] = to[a] - hit.endpos[a];
            len += d[a] * d[a];
        }
        len = sqrtf(len);
        if (len < 1.0f)
            return false;
        float q[3] = { hit.endpos[0], hit.endpos[1], hit.endpos[2] };
        bool out = false;
        for (float s = 2.0f; s < len; s += 2.0f) {
            for (int a = 0; a < 3; a++)
                q[a] = hit.endpos[a] + d[a] * (s / len);
            if (txn_air(b, q)) {
                out = true;
                break;
            }
        }
        if (!out)
            return false;
        /*
         * Out into the OLD map's air: from here on it is a view from that room,
         * which the map's own visibility decides - a doorway seen from the room
         * beyond, not anything seen through the sky (row 372: without the
         * compile's PVS, a courtyard line through the sky and the void into the
         * room past the storey read its upper doorway as a witness).
         */
        if (txn_air(donor, q))
            sky = false;
        memcpy(p, q, sizeof(p));
    }
    return false;
}

bool MapGenTransaction_SeenThroughSky(const mapgen_bsp_t *built,
                                     const mapgen_bsp_t *donor, const float lo[3],
                                     const float hi[3], float witness[6])
{
    if (!built || !donor)
        return false;
    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (!MapGenTrace_Bind(&ctx, built))
        return false;
    static const float zero[3] = { 0.0f, 0.0f, 0.0f };
    static float target[TXN_SKY_TARGETS][3];
    static float viewer[TXN_SKY_VIEWERS][3];
    uint32_t nt = 0, nv = 0;
    /* the lattice coarse enough that a room gives at most the cap */
    float vol = 1.0f;
    for (int a = 0; a < 3; a++)
        vol *= (hi[a] - lo[a]) > 1.0f ? (hi[a] - lo[a]) : 1.0f;
    float step = cbrtf(vol / (float)TXN_SKY_TARGETS);
    if (step < 32.0f)
        step = 32.0f;
    /* off every grid the map is built on, by fractions too: a line from one
       integer lattice to another ran exactly down a room's corner edge, where
       two shells meet and nothing can be seen (row 372) */
    for (float z = lo[2] + 0.5f * step + 1.13f; z < hi[2] && nt < TXN_SKY_TARGETS; z += step)
        for (float y = lo[1] + 0.5f * step + 3.71f; y < hi[1] && nt < TXN_SKY_TARGETS; y += step)
            for (float x = lo[0] + 0.5f * step + 5.37f; x < hi[0] && nt < TXN_SKY_TARGETS; x += step) {
                const float p[3] = { x, y, z };
                if (!txn_air(built, p) || txn_air(donor, p))
                    continue;
                const float up[3] = { x, y, z + 4096.0f };
                mapgen_trace_result_t roof;
                memset(&roof, 0, sizeof(roof));
                MapGenTrace_Box(&ctx, p, up, zero, zero, TXN_SOLID, &roof);
                if (roof.fraction >= 1.0f || (roof.surface_flags & TXN_SURF_SKY))
                    continue;               /* no roof, or under the sky */
                memcpy(target[nt++], p, sizeof(p));
            }
    const float ztop = hi[2] + 1024.0f, zbot = lo[2] - 1024.0f;
    for (float x = lo[0] - TXN_SKY_REACH + 7.29f; x < hi[0] + TXN_SKY_REACH && nv < TXN_SKY_VIEWERS;
         x += TXN_SKY_COLUMN)
        for (float y = lo[1] - TXN_SKY_REACH + 11.53f; y < hi[1] + TXN_SKY_REACH && nv < TXN_SKY_VIEWERS;
             y += TXN_SKY_COLUMN) {
            float z = ztop;
            float p[3] = { x, y, z };
            while (z > zbot) {
                p[2] = z;
                if (txn_air(built, p) && txn_air(donor, p))
                    break;
                z -= 16.0f;
            }
            if (z <= zbot)
                continue;
            const float up[3] = { x, y, z + 8192.0f };
            mapgen_trace_result_t lid;
            memset(&lid, 0, sizeof(lid));
            MapGenTrace_Box(&ctx, p, up, zero, zero, TXN_SOLID, &lid);
            if (lid.fraction >= 1.0f || !(lid.surface_flags & TXN_SURF_SKY))
                continue;
            const float down[3] = { x, y, z - 4096.0f };
            mapgen_trace_result_t floor_hit;
            memset(&floor_hit, 0, sizeof(floor_hit));
            MapGenTrace_Box(&ctx, p, down, zero, zero, TXN_SOLID, &floor_hit);
            float eye = lid.endpos[2] - 4.0f;
            if (floor_hit.fraction < 1.0f && floor_hit.endpos[2] + TXN_SKY_EYE < eye)
                eye = floor_hit.endpos[2] + TXN_SKY_EYE;
            const float v[3] = { x, y, eye };
            if (!txn_air(built, v) || !txn_air(donor, v))
                continue;
            memcpy(viewer[nv++], v, sizeof(v));
        }
    bool seen = false;
    for (uint32_t t = 0; t < nt && !seen; t++)
        for (uint32_t v = 0; v < nv && !seen; v++) {
            if (viewer[v][2] >= target[t][2])
                continue;
            const float dx = viewer[v][0] - target[t][0], dy = viewer[v][1] - target[t][1];
            if (dx * dx + dy * dy > TXN_SKY_REACH * TXN_SKY_REACH)
                continue;
            /*
             * Seen along the line AND along two lines a unit or so beside it:
             * a line that grazes a room's corner edge - where two shells meet
             * and nothing can be seen - slips through the trace's epsilon once
             * and is caught by its neighbours (row 372); a wall with no outer
             * face is seen along all three.
             */
            static const float jitter[2][3] = { { 1.3f, -0.9f, 1.1f }, { -1.1f, 1.4f, -0.8f } };
            float t1[3], t2[3];
            for (int a = 0; a < 3; a++) {
                t1[a] = target[t][a] + jitter[0][a];
                t2[a] = target[t][a] + jitter[1][a];
            }
            if (txn_sky_line(&ctx, built, donor, viewer[v], target[t])
                && txn_air(built, t1) && txn_sky_line(&ctx, built, donor, viewer[v], t1)
                && txn_air(built, t2) && txn_sky_line(&ctx, built, donor, viewer[v], t2)) {
                seen = true;
                memcpy(witness, target[t], 3 * sizeof(float));
                memcpy(witness + 3, viewer[v], 3 * sizeof(float));
            }
        }
    MapGenTrace_Release(&ctx);
    return seen;
}


#define MAX_STEPS 4096
/* How far round each end of a dig its own neighbourhood reaches, for the
   dead-end gate: a routed passage's mouth is at most an anchor (128) and half a
   cell (64) from its spot, plus a player's width. And how many segments of one
   passage the gate walks. */
#define MAPGEN_TXN_WAY_REACH 256.0f
/* Row 297: how far round an edit's box the hidden-surface gate looks, and how
   high a standing player's eye is over his origin. */
#define MAPGEN_TXN_HIDDEN_GROW 256.0f
#define MAPGEN_TXN_VIEW_HEIGHT 22.0f
/* Row 299: what a sightline stops at - every content the compiler's own
   visibility can stop at (solid, window, aux, lava, slime, water, mist), so a
   line through glass or any liquid is not asked - and how near one it may
   pass: a line that grazes an edge within a unit is not plain sight. Round 33
   refused five edits that were no holes for want of both. */
#define MAPGEN_TXN_HIDDEN_STOPS 0x7F
#define MAPGEN_TXN_HIDDEN_HALF  1.0f
/* Row 302: the game's MASK_SOLID (shared.h:852), what `droptofloor` sweeps
   a pickup's box against. */
#define MAPGEN_TXN_MASK_SOLID (MAPGEN_CONTENTS_SOLID | MAPGEN_CONTENTS_WINDOW)
/* Row 307: the room a rider takes over a lift's deck - a player's height, 56. */
#define MAPGEN_TXN_RIDER_HEIGHT 56.0f
#define MAPGEN_TXN_MAX_DIG_SEGS 32u
/*
 * How near a replacement has to be to be a lost climb place's replacement.
 *
 * 96 is the project's own figure for «nobody can stand within 96 units of an
 * end» (`MapGenReach_WayThrough`, `inc/common/mapgen_reach.h`), and the places
 * it is compared against are sampled on a 32-unit lattice - so 96 is three
 * cells: near enough to be the same spot in the room, far enough that the
 * water's own surface counts for the floor it replaced. Used by `judge` and by
 * `route_replaced`, which is why it is declared up here with the other bounds
 * and not beside the function (that cost one compile).
 */
#define MAPGEN_TXN_FLOOD_REACH 96.0f
/* How many staircases one run may turn into machines. q2dm1 has four. */
/* 256, not 32: a showcase map leaves forgiveness for four floods and a dozen
   tunnels of several segments each (ledger row 254) */
#define MAPGEN_TXN_MAX_FORGIVEN 256u
/* How many seams a map may carry before this stops being a diagnosis and
   starts being a fixture. q2dm1 has fourteen; a hundred is room to spare and
   a candidate that exceeds it is refused as UNMEASURED rather than trusted. */
/* row 400: 128 held q2dm1's 14; a Quake III layout made for Quake II carries hundreds, and a list that overflowed
   left every candidate's cracks unmeasured (REJECTED_UNMEASURED on every swap of cor and q3t2) */
#define MAPGEN_TXN_MAX_SEAMS 4096u
/* Row 382: the donor's witnesses are taken this far off an edge's line - twice
   the candidate's 0.5 - so a donor corner near the line is named on both sides
   of it. */
static const float g_txn_donor_seam_reach = 1.0f;   /* the RED's mutation point */

struct mapgen_transaction_s {
    char     job_root[MAPCOMPILE_MAX_PATH];
    char     map_name[64];
    char     moddir[MAPCOMPILE_MAX_PATH];
    char     donor_path[MAPCOMPILE_MAX_PATH];
    const mapcompile_adapter_t *adapter;

    mapgen_bsp_t      *donor_bsp;
    mapgen_geometry_t *donor;

    /*
     * The other donors a room may be brought in from.
     *
     * Kept for the transaction's whole life, because the plan holds borrowed
     * pointers into these geometries and reads them when a graft is applied.
     * Freeing them early would be a plan reading freed memory, which is a
     * crash that would look like a compiler fault.
     */
    mapgen_bsp_t      *other_bsp[MAPGEN_TXN_MAX_OTHER_DONORS];
    mapgen_geometry_t *other[MAPGEN_TXN_MAX_OTHER_DONORS];
    char               other_name[MAPGEN_TXN_MAX_OTHER_DONORS][64];
    uint32_t           num_others;
    /* Which of them are in the ACCEPTED candidate, which is the only sense in
       which a donor contributed anything. */
    bool               other_used[MAPGEN_TXN_MAX_OTHER_DONORS];
    uint32_t           grafts_accepted;

    /*
     * The donor's own geometry through this compiler, with nothing applied.
     *
     * Every divergence is measured against this rather than against
     * `donor_bsp`, because the file a donor arrives in was built by a
     * different compiler and the difference between the two is not something
     * any edit did.
     */
    mapgen_bsp_t      *baseline_bsp;

    /* How many of the DONOR's own spawns and pickups are already in a liquid.
       An edit may not add to it; see MAPGEN_TXN_REJECTED_DROWNED. */
    uint32_t           donor_drowned;
    /* Vertical liquid faces the donor draws, and how much of its own
       machines' travel is inside the world: the floors an edit is held to. */
    uint32_t           donor_standing_water;
    uint32_t           donor_mover_travel;
    /* And the seams the compiler left in the donor's own file, by place: the
       set an edit's own compile is held to. A candidate may keep any of them
       and may remove any of them; it may not add one that is not here. */
    mapgen_bsp_seam_t  donor_seam[MAPGEN_TXN_MAX_SEAMS];
    uint32_t           num_donor_seams;
    bool               donor_seams_known;

    /*
     * The ways through the baseline, taken once.
     *
     * A climb is a standing place with three floor heights within reach of
     * it, and every candidate is held to keeping all of them. Measured on the
     * BASELINE - the donor through this compiler - because that is the map
     * the fork is a fork of.
     */
    float            (*climb)[3];
    uint32_t           num_climbs;

    /*
     * And the flights an accepted lift REPLACED.
     *
     * A staircase that became a func_plat is not a way lost - it is the same
     * two heights served by a machine, which is what a mapper does when he
     * wants a room to read differently. Its steps are gone all the same, so
     * the climb places on them fail the rule above from the moment the lift is
     * accepted and would fail it for every later edit of the run.
     *
     * So the box is remembered, and the places inside it are forgiven for
     * exactly as long as a machine stands there and serves the heights. It is
     * re-proved on every attempt rather than trusted from when it was
     * accepted: an edit that took the lift away would otherwise inherit the
     * forgiveness for the stairs it no longer has.
     */
    /*
     * And a FLOOD's box is forgiven the other way: not by a machine serving
     * the heights, but because the place is now under water the edit put there.
     *
     * MEASURED 2026-09-12 on the delivery the PO refused: the flood family was
     * tried ten times across the five fidelity maps and accepted zero times -
     * nine `REJECTED_BURIED_ROUTE` and one `UNPLAYABLE` - on the very rooms
     * that seal and walk when applied alone (`mg_water` carries one). A flooded
     * floor's climb places are in liquid, nothing «serves» them, and the only
     * water the PO could then see on those maps was the 128-unit pit he has now
     * refused three times. A place under our own water is not a way taken away:
     * the reach explorer swims, and the component is checked separately.
     */
    struct {
        float lo[3];
        float hi[3];
        float rise;
        bool  liquid;
    }                  forgiven[MAPGEN_TXN_MAX_FORGIVEN];
    uint32_t           num_forgiven;

    /* How many places a player could get to, and get back from, in the last
       accepted candidate - the floor a construction has to beat. */
    uint32_t           accepted_component;

    /*
     * The PARENT's walk - the map this attempt is applied to - for D9's and
     * D16's excuse (D15) and for D21's count.
     *
     * D19 (assignment 23): the walk an accepted candidate was judged on is
     * handed over here on acceptance, because it IS the walk of the map that
     * acceptance loads - the same compiled file, the same budget. Before the
     * first acceptance the parent is the baseline, whose walk is
     * `baseline_reach`. Explored lazily only when an acceptance had no walk
     * to hand over.
     */
    mapgen_reach_t    *parent_reach;
    bool               parent_reach_tried;
    bool               parent_is_baseline;
    /* row 400: the donor's plain rebuild was refused for what it draws, the faithful one accepted */
    bool               faithful_skins;
    /* ... and accepted with a bounded residue of what it draws differently (`faithful_residue_small`) */
    bool               faithful_residue;
    /* The BASELINE walked once per run, lazily: the parent before the first
       acceptance, the floor the WORTHLESS gate compares with and - taken over
       by the pipeline - the oracle's walk of the donor side. */
    mapgen_reach_t    *baseline_reach;
    bool               baseline_reach_tried;

    /* The accepted map, kept open so the operators can measure against what
       they are actually editing rather than against the donor. */
    mapgen_bsp_t      *accepted_map;

    /* How far from the donor this run may go, kept because a redeal deals a
       new plan and the fidelity did not change with it. */
    int32_t            ambition;
    /* The seed the schedule was dealt from. Kept because the ambition and the
       baseline both arrive after the first deal and both are planning inputs,
       so the plan has to be dealt again - with the same seed, or it would be a
       different schedule and not the same one asked a better question. */
    uint64_t seed;
    /* Why the reference was accepted, or refused: kept so a Project can store
       the evidence rather than the verdict alone. */
    mapgen_equiv_report_t equivalence;
    char               baseline_path[MAPCOMPILE_MAX_PATH];
    char               baseline_sha256[MAPCOMPILE_SHA256_HEX];
    mapgen_geometry_edit_plan_t *plan;

    /* The last ACCEPTED candidate. Immutable between attempts: an attempt
       clones it and never writes to it. */
    mapgen_geometry_t *accepted;
    char               accepted_bsp[MAPCOMPILE_MAX_PATH];
    /* And its hash. Two compiles that produced the same bytes produced the
       same map - the one bound on "did this edit do anything" that costs a
       string compare instead of a reachability exploration. */
    char               accepted_sha256[MAPCOMPILE_SHA256_HEX];
    uint32_t           accepted_divergence;
    /* And how many surfaces of it a compiler cannot build cleanly. The donor's
       own count is the floor every later candidate is held to. */
    uint32_t           accepted_faults;
    /* And what that count was when nothing had been done yet, kept so a run
       can be read against the map it started from. */
    uint32_t           donor_faults;
    mapgen_reach_report_t accepted_reach;

    uint32_t attempted;
    uint32_t accepted_count;
    uint32_t violations;

    /* What the run is aiming at, when anybody said. */
    uint32_t band_target;
    uint32_t band_tolerance;
    bool     has_band;

    mapgen_transaction_step_t steps[MAX_STEPS];
    uint32_t                  num_steps;
};

/* ---- small helpers ----------------------------------------------------------- */

static mapgen_bsp_t *load_bsp(const char *path)
{
    uint8_t *raw = NULL;       /* row 411: a file or a section */
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
 * A directory created empty for THIS attempt.
 *
 * Not reused and not cleaned: the compiler refuses a directory that already
 * holds an output, and an attempt that reused one would be judged partly on
 * what the last attempt left behind. They are numbered so the ledger and the
 * filesystem tell the same story afterwards.
 */
static bool attempt_dir(const mapgen_transaction_t *txn, uint32_t n,
                        char *out, size_t size)
{
    const int written = snprintf(out, size, "%s/try_%04u", txn->job_root, n);
    if (written <= 0 || (size_t)written >= size)
        return false;
    if (MapGenFs_IsMem(txn->job_root)) {
        /*
         * Row 411 (Fable's brief 8): a try in memory - the tries before it give theirs back first, but the map
         * that stands (the accepted one, or the base) keeps its own: the next try is measured against it.
         */
        char keep[MAPCOMPILE_MAX_PATH];
        snprintf(keep, sizeof(keep), "%s", txn->accepted_bsp);
        char *slash = strrchr(keep, '/');
        if (slash)
            *slash = 0;
        MapGenFs_ReleaseTries(txn->job_root, keep);
        return MapGenFs_MakeDir(out, txn->map_name);
    }
#ifdef _WIN32
    const int made = _mkdir(out);
#else
    const int made = mkdir(out, 0777);
#endif
    return made == 0 || errno == EEXIST;
}

/*
 * Row 411 (Fable's brief 8 decision 4): the run's tries in memory, and the accepted ones written once to the disk
 * as CHECKPOINTS - their .map and .bsp under `disk_root/try_NNNN`, what a resume replays against - when the caller
 * asks for it. Without them nothing of a try ever reaches the disk, and a stopped run cannot be resumed.
 */
static char g_txn_disk_root[MAPCOMPILE_MAX_PATH];
static bool g_txn_checkpoints = true;

void MapGenTransaction_SetCheckpoints(const char *disk_root, bool on)
{
    snprintf(g_txn_disk_root, sizeof(g_txn_disk_root), "%s", disk_root ? disk_root : "");
    g_txn_checkpoints = on;
}

static void checkpoint(const mapgen_transaction_t *txn, uint32_t attempt, const char *bsp_path)
{
    if (!MapGenFs_IsMem(bsp_path) || !g_txn_checkpoints || !g_txn_disk_root[0])
        return;
    char dir[MAPCOMPILE_MAX_PATH], to[MAPCOMPILE_MAX_PATH], from[MAPCOMPILE_MAX_PATH];
    snprintf(dir, sizeof(dir), "%s/try_%04u", g_txn_disk_root, (unsigned)attempt);
    if (!MapGenFs_MakeDir(dir, txn->map_name))
        return;
    const char *exts[2] = { ".map", ".bsp" };
    for (int i = 0; i < 2; i++) {
        snprintf(from, sizeof(from), "%.*s%s", (int)(strlen(bsp_path) - 4), bsp_path, exts[i]);
        snprintf(to, sizeof(to), "%s/%s%s", dir, txn->map_name, exts[i]);
        uint8_t *data = NULL;
        size_t size = 0;
        if (MapGenFs_Read(from, &data, &size))
            MapGenFs_Write(to, data, size);
        free(data);
    }
}

/*
 * The donor, through this compiler, with nothing done to it.
 *
 * One compile, once, when the transaction opens. It is the same work an
 * attempt does - write the geometry, run the profile, read what came out - and
 * it is deliberately not shared with `judge`, because judge measures a
 * candidate against this and something has to exist before it can be measured
 * against.
 */
/*
 * The same work, for a caller that has geometry rather than a transaction.
 *
 * Fidelity zero invents its map instead of forking one and still has to
 * measure against the donor through this compiler, so the reference is built
 * the same way by the same code.
 */
static bool baseline_from(const mapgen_geometry_t *geometry,
                          const char *job_root, const char *map_name,
                          const char *moddir,
                          const mapcompile_adapter_t *adapter,
                          char out_path[MAPCOMPILE_MAX_PATH],
                          char out_sha256[MAPCOMPILE_SHA256_HEX]);

/*
 * Build the reference and prove it is the donor.
 *
 * Every fidelity comes through here - the fork path below and the synthesis
 * path in the pipeline - because a baseline nobody checked is a baseline that
 * makes divergence mean nothing, and fidelity zero used to have one.
 */
bool MapGenTransaction_BuildBaselineChecked(const char *donor_bsp,
                                            const char *job_root,
                                            const char *map_name,
                                            const char *moddir,
                                            const mapcompile_adapter_t *adapter,
                                            mapgen_equiv_report_t *why,
                                            char out_path[MAPCOMPILE_MAX_PATH],
                                            char out_sha256[MAPCOMPILE_SHA256_HEX])
{
    if (why)
        memset(why, 0, sizeof(*why));
    if (!donor_bsp || !job_root || !map_name || !adapter)
        return false;
    mapgen_bsp_t *bsp = load_bsp(donor_bsp);
    if (!bsp)
        return false;
    mapgen_geometry_t *geometry = NULL;
    if (MapGenGeometry_FromBsp(bsp, &geometry) != MAPGEN_GEOMETRY_OK) {
        MapGenBsp_Free(bsp);
        return false;
    }
    bool ok = baseline_from(geometry, job_root, map_name, moddir, adapter,
                            out_path, out_sha256);
    MapGenGeometry_Free(geometry);

    if (ok) {
        mapgen_bsp_t *baseline = load_bsp(out_path);
        if (!baseline) {
            ok = false;
        } else {
            mapgen_equiv_policy_t policy;
            mapgen_equiv_report_t scratch;
            MapGenEquivalence_DefaultPolicy(&policy);
            ok = MapGenEquivalence_Compare(bsp, baseline, &policy,
                                           why ? why : &scratch)
                 == MAPGEN_EQUIV_OK;
            MapGenBsp_Free(baseline);
        }
    }
    MapGenBsp_Free(bsp);
    return ok;
}

bool MapGenTransaction_FaithfulSkins(const mapgen_transaction_t *txn)
{
    return txn && txn->faithful_skins;
}

bool MapGenTransaction_BuildBaseline(const char *donor_bsp,
                                     const char *job_root,
                                     const char *map_name, const char *moddir,
                                     const mapcompile_adapter_t *adapter,
                                     char out_path[MAPCOMPILE_MAX_PATH],
                                     char out_sha256[MAPCOMPILE_SHA256_HEX])
{
    return MapGenTransaction_BuildBaselineChecked(donor_bsp, job_root,
                                                  map_name, moddir, adapter,
                                                  NULL, out_path, out_sha256);
}

/*
 * Build the reference, and then prove it is the donor.
 *
 * The proof is not optional and it is not the compiler's exit code. A dropped
 * brush, a moved solid boundary, a lost liquid, a surface that stopped being
 * drawn, a texture that slid, a model that became world, a door that lost its
 * target, a trigger or areaportal that vanished, a spawn or item that
 * disappeared, a floor that moved out from under a pickup: every one of those
 * compiles without complaint, and every one of them would silently become an
 * accepted zero baseline.
 *
 * The comparison shares no projection with the code above it: it reads both
 * COMPILED artifacts, samples space through the collision tree, measures drawn
 * surfaces off the face lump and parses the entities itself.
 */
static void clear_dir_files(const char *dir);

/*
 * What a FAITHFUL rebuild may still draw differently (row 400, Fable's brief 4 G5-3/G5-4).
 *
 * Faithful skins give every overlapped side the face the donor draws over most of it. A side the donor drew with
 * two textures - two overlapping brushes, each visible over part of it (cor's wall at x -281.6: wall1 over 39813
 * units, floor2 over the rest) - can wear only one; matching that exactly takes cutting the donor's brushes apart.
 * So a faithful rebuild is the reference when everything but what is drawn is the donor's - space, models,
 * entities, movers, the way through, all passed - and what is drawn differently is the map's own textures on at
 * most two thousandths of its surface, one plane in fifty and one mapping in a hundred. Not a tolerance for a lost
 * wall: a wall that is gone changes the space axis, which must pass. The residue is said on the progress stream.
 */
static bool faithful_residue_small(const mapgen_equiv_report_t *r)
{
    const uint32_t drawn_only = MAPGEN_EQUIV_AXIS_BIT(MAPGEN_EQUIV_DIFF_ARCHITECTURE)
                              | MAPGEN_EQUIV_AXIS_BIT(MAPGEN_EQUIV_DIFF_SURFACE)
                              | MAPGEN_EQUIV_AXIS_BIT(MAPGEN_EQUIV_DIFF_MAPPING);
    if (!r->failed_axes || (r->failed_axes & ~drawn_only) || r->mapping_overflow)
        return false;
    const double drawn = r->drawn_area[0];
    if (drawn <= 0.0 || fabs(r->drawn_area[1] - drawn) > 0.002 * drawn)
        return false;
    if (r->groups_missing_area + r->groups_added_area > 0.002 * drawn)
        return false;
    if (r->planes_missing * 50u > r->surface_planes[0] || r->planes_added * 50u > r->surface_planes[0])
        return false;
    return r->mapping_mismatch * 100u <= r->drawn_groups[0];
}

static bool build_baseline(mapgen_transaction_t *txn)
{
    if (!baseline_from(txn->donor, txn->job_root, txn->map_name, txn->moddir,
                       txn->adapter, txn->baseline_path, txn->baseline_sha256))
        return false;
    if ((txn->baseline_bsp = load_bsp(txn->baseline_path)) == NULL)
        return false;

    mapgen_equiv_policy_t policy;
    MapGenEquivalence_DefaultPolicy(&policy);
    const mapgen_equiv_result_t rc =
        MapGenEquivalence_Compare(txn->donor_bsp, txn->baseline_bsp, &policy,
                                  &txn->equivalence);
    if (rc == MAPGEN_EQUIV_OK)
        return true;

    /* Freed by the caller's ERR_BASELINE path along with everything else. */
    return false;
}

static bool baseline_from(const mapgen_geometry_t *geometry,
                          const char *job_root, const char *map_name,
                          const char *moddir,
                          const mapcompile_adapter_t *adapter,
                          char out_path[MAPCOMPILE_MAX_PATH],
                          char out_sha256[MAPCOMPILE_SHA256_HEX])
{
    char dir[MAPCOMPILE_MAX_PATH];
    char map_path[MAPCOMPILE_MAX_PATH];
    if (snprintf(dir, sizeof(dir), "%s/baseline", job_root)
            >= (int)sizeof(dir)
        || snprintf(map_path, sizeof(map_path), "%s/%s.map", dir,
                    map_name) >= (int)sizeof(map_path))
        return false;
    if (!MapGenFs_MakeDir(dir, map_name))       /* row 411: a folder, or the base's sections in memory */
        return false;

    if (MapGenGeometry_WriteValve220(geometry, map_path)
        != MAPGEN_GEOMETRY_OK)
        return false;

    mapcompile_request_t request;
    memset(&request, 0, sizeof(request));
    snprintf(request.job_dir, sizeof(request.job_dir), "%s", dir);
    snprintf(request.map_name, sizeof(request.map_name), "%s", map_name);
    snprintf(request.moddir, sizeof(request.moddir), "%s", moddir);
    snprintf(request.basedir, sizeof(request.basedir), "%s", moddir);
    request.profile = MAPCOMPILE_PROFILE_DRAFT;
    request.format = MAPCOMPILE_FORMAT_IBSP;
    request.threads = MAPCOMPILE_PINNED_THREADS;
    request.stage_timeout_ms = 1800000;
    request.max_log_bytes = 262144;
    request.disk_budget_bytes = 512ull * 1024ull * 1024ull;

    mapcompile_report_t compiled;
    memset(&compiled, 0, sizeof(compiled));
    const mapcompile_result_t rc =
        MapCompile_RunProfile(adapter, &request, &compiled);
    for (int i = 0; i < compiled.num_stages; i++)
        free(compiled.stages[i].stdout_captured);
    if (rc != MAPCOMPILE_OK)
        return false;

    snprintf(out_path, MAPCOMPILE_MAX_PATH, "%s", compiled.bsp_path);
    snprintf(out_sha256, MAPCOMPILE_SHA256_HEX, "%s", compiled.bsp_sha256);
    return true;
}

/* ---- opening and closing ------------------------------------------------------ */

/* Deal the schedule again from what the transaction knows NOW. Defined with the
   other plan handling below; declared here because the opening re-deals as soon
   as the baseline exists, which is a planning input the first deal lacked. */
static mapgen_transaction_result_t redeal(mapgen_transaction_t *txn,
                                         bool from_accepted);

/* The one implementation the three entry points share; defined below. */
static mapgen_transaction_result_t
begin_impl(const char *donor_bsp, const char *job_root, const char *map_name,
           const char *moddir, const mapcompile_adapter_t *adapter,
           uint64_t seed, mapgen_equiv_report_t *why,
           const char *const *other_donors, uint32_t num_others,
           mapgen_transaction_t **out);

mapgen_transaction_result_t
MapGenTransaction_Begin(const char *donor_bsp, const char *job_root,
                        const char *map_name, const char *moddir,
                        const mapcompile_adapter_t *adapter,
                        uint64_t seed, mapgen_transaction_t **out)
{
    return MapGenTransaction_BeginWithDonors(donor_bsp, job_root, map_name,
                                             moddir, adapter, seed, NULL, 0,
                                             out);
}

uint32_t MapGenTransaction_NumOtherDonors(const mapgen_transaction_t *txn)
{
    return txn ? txn->num_others : 0;
}

uint32_t MapGenTransaction_GraftsAccepted(const mapgen_transaction_t *txn)
{
    return txn ? txn->grafts_accepted : 0;
}

bool MapGenTransaction_DonorContributed(const mapgen_transaction_t *txn,
                                        uint32_t i)
{
    return txn && i < txn->num_others && txn->other_used[i];
}

const char *MapGenTransaction_OtherDonor(const mapgen_transaction_t *txn,
                                         uint32_t i)
{
    return (txn && i < txn->num_others) ? txn->other_name[i] : NULL;
}

/*
 * Row 412 (the PO, on q2duel1 refused at its first step: «почему не пишет? нужен лог», «пусть пишет точные
 * причины»): why the last base was refused - the copy compared with the original, axis by axis - kept for a caller
 * that began without asking (the pipeline), so it can say it.
 */
static mapgen_equiv_report_t g_last_baseline_why;
static bool g_have_baseline_why;

bool MapGenTransaction_LastBaselineWhy(mapgen_equiv_report_t *out)
{
    if (out && g_have_baseline_why)
        *out = g_last_baseline_why;
    return g_have_baseline_why;
}

mapgen_transaction_result_t
MapGenTransaction_BeginWithDonors(const char *donor_bsp, const char *job_root,
                                  const char *map_name, const char *moddir,
                                  const mapcompile_adapter_t *adapter,
                                  uint64_t seed,
                                  const char *const *other_donors,
                                  uint32_t num_others,
                                  mapgen_transaction_t **out)
{
    return begin_impl(donor_bsp, job_root, map_name, moddir, adapter, seed,
                      NULL, other_donors, num_others, out);
}

mapgen_transaction_result_t
MapGenTransaction_BeginWith(const char *donor_bsp, const char *job_root,
                            const char *map_name, const char *moddir,
                            const mapcompile_adapter_t *adapter,
                            uint64_t seed, mapgen_equiv_report_t *why,
                            mapgen_transaction_t **out)
{
    return begin_impl(donor_bsp, job_root, map_name, moddir, adapter, seed,
                      why, NULL, 0, out);
}

mapgen_bsp_seams_result_t MapGenTransaction_DonorSeams(const mapgen_bsp_t *donor,
                                                       mapgen_bsp_seam_t *out,
                                                       uint32_t cap,
                                                       uint32_t *out_count)
{
    uint32_t found = 0, kept = 0;
    const mapgen_bsp_seams_result_t rc =
        MapGenBsp_SeamsWithin(donor, g_txn_donor_seam_reach, out, cap, &found);
    /* The same two discounts the candidate gets, applied here: like is
       compared with like or the comparison means nothing. */
    for (uint32_t s = 0; s < found && s < cap; s++) {
        if (!out[s].opaque_edge && !out[s].opaque_vertex)
            continue;
        if (out[s].edge_model != out[s].vertex_model)
            continue;
        out[kept++] = out[s];
    }
    if (out_count)
        *out_count = kept;
    return rc;
}

bool MapGenTransaction_NewSeam(const mapgen_bsp_seam_t *seam,
                               const mapgen_bsp_seam_t *donor, uint32_t num_donor)
{
    if (!seam->opaque_edge && !seam->opaque_vertex)
        return false;
    if (seam->edge_model != seam->vertex_model)
        return false;
    for (uint32_t d = 0; d < num_donor; d++)
        if (MapGenBsp_SameSeam(seam, &donor[d]))
            return false;
    return true;
}

/*
 * The one implementation, behind all three names.
 *
 * There were two ways to open a transaction before the other donors existed,
 * and adding a third made one of them forward to another that had no parameter
 * for them - so the donors reached the transaction and never reached the plan.
 * One function that takes everything is how that cannot happen again.
 */
static mapgen_transaction_result_t
begin_impl(const char *donor_bsp, const char *job_root,
           const char *map_name, const char *moddir,
           const mapcompile_adapter_t *adapter, uint64_t seed,
           mapgen_equiv_report_t *why,
           const char *const *other_donors, uint32_t num_others,
           mapgen_transaction_t **out)
{
    if (why)
        memset(why, 0, sizeof(*why));
    if (out)
        *out = NULL;
    if (!donor_bsp || !job_root || !map_name || !adapter || !out)
        return MAPGEN_TXN_ERR_ARGS;

    mapgen_transaction_t *txn = calloc(1, sizeof(*txn));
    if (!txn)
        return MAPGEN_TXN_ERR_MEMORY;

    if (snprintf(txn->job_root, sizeof(txn->job_root), "%s", job_root)
            >= (int)sizeof(txn->job_root)
        || snprintf(txn->map_name, sizeof(txn->map_name), "%s", map_name)
            >= (int)sizeof(txn->map_name)
        || snprintf(txn->donor_path, sizeof(txn->donor_path), "%s", donor_bsp)
            >= (int)sizeof(txn->donor_path)
        || snprintf(txn->moddir, sizeof(txn->moddir), "%s",
                    moddir ? moddir : job_root) >= (int)sizeof(txn->moddir)) {
        free(txn);
        return MAPGEN_TXN_ERR_ARGS;
    }
    txn->adapter = adapter;
    /* row 408: where a dig reads the colour its panels emit in */
    MapGenGeometryEdit_SetGameDir(txn->moddir);

    txn->donor_bsp = load_bsp(donor_bsp);
    if (!txn->donor_bsp) {
        free(txn);
        return MAPGEN_TXN_ERR_DONOR;
    }
    /* What the donor itself already keeps in the water, so an edit is held
       to not ADDING to it - the same shape of rule as surface faults. */
    if (MapGenGeometry_FromBsp(txn->donor_bsp, &txn->donor)
        != MAPGEN_GEOMETRY_OK) {
        MapGenBsp_Free(txn->donor_bsp);
        free(txn);
        return MAPGEN_TXN_ERR_DONOR;
    }
    txn->donor_drowned =
        MapGenGeometry_DrownedEntities(txn->donor, false, NULL, 0);
    /* And what it already stands in the air, and how much room its own
       machines have. Both are floors an edit may not sink below. */
    txn->donor_standing_water = MapGenBsp_StandingWater(txn->donor_bsp, NULL);
    {
        mapgen_movers_t *movers = calloc(1, sizeof(*movers));
        if (movers && MapGenMovers_Read(txn->donor_bsp, movers)) {
            MapGenMovers_MeasureClearance(movers, txn->donor_bsp);
            MapGenMovers_WorstClearance(movers, &txn->donor_mover_travel,
                                        NULL);
        }
        free(movers);
    }
    /*
     * The other donors, loaded before the plan because the plan reads them.
     *
     * One that cannot be loaded is skipped rather than fatal: a run asked for
     * three donors and given two working ones should make a map out of the two
     * and say which it used, not refuse. Which it used IS said - every graft
     * records the donor's name - so nothing is silently omitted.
     */
    for (uint32_t i = 0; i < num_others && other_donors
                         && txn->num_others < MAPGEN_TXN_MAX_OTHER_DONORS;
         i++) {
        if (!other_donors[i] || !other_donors[i][0])
            continue;
        mapgen_bsp_t *bsp = load_bsp(other_donors[i]);
        if (!bsp)
            continue;
        mapgen_geometry_t *g = NULL;
        if (MapGenGeometry_FromBsp(bsp, &g) != MAPGEN_GEOMETRY_OK) {
            MapGenBsp_Free(bsp);
            continue;
        }
        const uint32_t at = txn->num_others++;
        txn->other_bsp[at] = bsp;
        txn->other[at] = g;
        /* The map's NAME, which is what provenance is recorded as. */
        const char *slash = strrchr(other_donors[i], '/');
        const char *back = strrchr(other_donors[i], '\\');
        if (back > slash)
            slash = back;
        snprintf(txn->other_name[at], sizeof(txn->other_name[at]), "%s",
                 slash ? slash + 1 : other_donors[i]);
    }

    const mapgen_geometry_t *others[MAPGEN_TXN_MAX_OTHER_DONORS];
    const mapgen_bsp_t *other_bsps[MAPGEN_TXN_MAX_OTHER_DONORS];
    const char *names[MAPGEN_TXN_MAX_OTHER_DONORS];
    for (uint32_t i = 0; i < txn->num_others; i++) {
        others[i] = txn->other[i];
        other_bsps[i] = txn->other_bsp[i];
        names[i] = txn->other_name[i];
    }

    if (MapGenGeometryEdit_PlanWith(txn->donor, txn->donor_bsp, seed,
                                    txn->num_others ? others : NULL,
                                    txn->num_others ? other_bsps : NULL,
                                    txn->num_others ? names : NULL,
                                    txn->num_others, &txn->plan)
        != MAPGEN_GEOMETRY_OK) {
        for (uint32_t i = 0; i < txn->num_others; i++) {
            MapGenGeometry_Free(txn->other[i]);
            MapGenBsp_Free(txn->other_bsp[i]);
        }
        MapGenGeometry_Free(txn->donor);
        MapGenBsp_Free(txn->donor_bsp);
        free(txn);
        return MAPGEN_TXN_ERR_DONOR;
    }

    /*
     * The accepted candidate starts as the donor's own geometry, cloned.
     *
     * Cloned rather than shared, because the donor stays the thing every
     * divergence is measured against and an attempt must not be able to touch
     * it even by accident.
     */
    if (MapGenGeometry_Clone(txn->donor, &txn->accepted)
        != MAPGEN_GEOMETRY_OK) {
        MapGenGeometryEdit_Free(txn->plan);
        MapGenGeometry_Free(txn->donor);
        MapGenBsp_Free(txn->donor_bsp);
        free(txn);
        return MAPGEN_TXN_ERR_MEMORY;
    }
    /* Nothing has been done to it, so its divergence from the donor is zero by
       construction rather than by tolerance. */
    txn->accepted_divergence = 0;
    txn->accepted_faults = MapGenGeometry_SurfaceFaults(txn->accepted,
                                                        txn->donor_bsp);
    txn->donor_faults = txn->accepted_faults;
    /*
     * And the seams the compiler leaves in the donor's own file, as WITNESSES.
     *
     * Taken from the DONOR rather than the baseline for the same reason the
     * fault count is: it is the map the fork is a fork of, and the round trip
     * does not change it - both measure fourteen on q2dm1.
     *
     * Kept as places rather than as a number, because a count cannot tell a
     * candidate that removed one crack and made another from a candidate that
     * changed nothing. An inherited seam is one this list already names; any
     * other is new, and new is what the rule is about. The same policy is
     * applied to both sides: nothing is discounted here that is not
     * discounted there.
     */
    {
        /* Row 382: taken twice as far off the line as a candidate is judged
           (`MapGenTransaction_DonorSeams`), the two discounts applied. */
        uint32_t found = 0;
        const mapgen_bsp_seams_result_t rc =
            MapGenTransaction_DonorSeams(txn->donor_bsp, txn->donor_seam,
                                         MAPGEN_TXN_MAX_SEAMS, &found);
        txn->donor_seams_known = rc == MAPGEN_SEAMS_OK;
        txn->num_donor_seams = found;
    }

    /*
     * And the reference every divergence is measured against.
     *
     * A donor that cannot be written, compiled and read back is refused here:
     * nothing downstream could tell that failure apart from an edit's, and a
     * run that measured against a missing baseline would be measuring nothing.
     */
    bool built = build_baseline(txn);
    /*
     * Row 400 (Fable's brief 4, G5-3): a plain rebuild refused ONLY for what it draws - planes, surfaces, mappings,
     * nothing about space, entities, models or movers - is built once more with faithful skins (every overlapped
     * side wears the face the donor draws over it), the plan dealt again on that geometry. q2dm1's plain rebuild is
     * accepted and never comes here; a donor the second build does not satisfy is refused as before, with the second
     * build's account.
     */
    {
        const uint32_t drawn_only = MAPGEN_EQUIV_AXIS_BIT(MAPGEN_EQUIV_DIFF_ARCHITECTURE)
                                  | MAPGEN_EQUIV_AXIS_BIT(MAPGEN_EQUIV_DIFF_SURFACE)
                                  | MAPGEN_EQUIV_AXIS_BIT(MAPGEN_EQUIV_DIFF_MAPPING);
        const uint32_t failed = txn->equivalence.failed_axes;
        mapgen_geometry_t *faithful = NULL;
        mapgen_geometry_edit_plan_t *plan = NULL;
        mapgen_geometry_t *accepted = NULL;
        if (!built && failed && !(failed & ~drawn_only)
            && MapGenGeometry_FromBspWith(txn->donor_bsp, MAPGEN_GEOMETRY_FAITHFUL_SKINS, &faithful)
               == MAPGEN_GEOMETRY_OK
            && MapGenGeometryEdit_PlanWith(faithful, txn->donor_bsp, seed,
                                           txn->num_others ? others : NULL,
                                           txn->num_others ? other_bsps : NULL,
                                           txn->num_others ? names : NULL,
                                           txn->num_others, &plan) == MAPGEN_GEOMETRY_OK
            && MapGenGeometry_Clone(faithful, &accepted) == MAPGEN_GEOMETRY_OK) {
            MapGenBsp_Free(txn->baseline_bsp);
            txn->baseline_bsp = NULL;
            MapGenGeometry_Free(txn->accepted);
            MapGenGeometryEdit_Free(txn->plan);
            MapGenGeometry_Free(txn->donor);
            txn->donor = faithful;
            txn->plan = plan;
            txn->accepted = accepted;
            faithful = NULL;
            plan = NULL;
            accepted = NULL;
            txn->donor_drowned = MapGenGeometry_DrownedEntities(txn->donor, false, NULL, 0);
            txn->accepted_faults = MapGenGeometry_SurfaceFaults(txn->accepted, txn->donor_bsp);
            txn->donor_faults = txn->accepted_faults;
            txn->faithful_skins = true;
            /* the plain build's files go: the compiler refuses a job folder that already holds a map */
            char dir[MAPCOMPILE_MAX_PATH];
            if (snprintf(dir, sizeof(dir), "%s/baseline", txn->job_root) < (int)sizeof(dir))
                clear_dir_files(dir);
            built = build_baseline(txn);
            if (!built && txn->baseline_bsp && faithful_residue_small(&txn->equivalence)) {
                txn->faithful_residue = true;
                built = true;
            }
        }
        MapGenGeometry_Free(accepted);
        MapGenGeometryEdit_Free(plan);
        MapGenGeometry_Free(faithful);
    }
    if (!built) {
        /*
         * Why, before the transaction that knows it is destroyed - and the
         * baseline it loaded, which this path used to walk away from.
         */
        if (why)
            *why = txn->equivalence;
        g_last_baseline_why = txn->equivalence;       /* row 412: and for the pipeline to say */
        g_have_baseline_why = true;
        MapGenBsp_Free(txn->baseline_bsp);
        txn->baseline_bsp = NULL;
        /* Not ERR_DONOR: the donor loaded, parsed and planned. What failed is
           the reference, and a caller told the donor was bad would go looking
           at the wrong file. */
        MapGenGeometry_Free(txn->accepted);
        MapGenGeometryEdit_Free(txn->plan);
        MapGenGeometry_Free(txn->donor);
        MapGenBsp_Free(txn->donor_bsp);
        free(txn);
        return MAPGEN_TXN_ERR_BASELINE;
    }
    snprintf(txn->accepted_bsp, sizeof(txn->accepted_bsp), "%s",
             txn->baseline_path);
    snprintf(txn->accepted_sha256, sizeof(txn->accepted_sha256), "%s",
             txn->baseline_sha256);

    /*
     * Row 400: and the BASELINE's own seams, as witnesses too.
     *
     * The donor's seams are its compiler's; on q2dm1 the frozen compiler leaves the same fourteen in the baseline,
     * so the donor's list was the baseline's. A donor built by another compiler is not: cor's and q3t2's baselines
     * carry T-junctions their donors never had, every candidate inherits them from the baseline, and every swap of
     * a weapon was refused «a new crack in the world». A seam the baseline already has is one no edit made. On
     * q2dm1 every baseline seam is a donor seam already and the list does not change.
     */
    if (txn->donor_seams_known && txn->baseline_bsp) {
        mapgen_bsp_seam_t *extra = calloc(MAPGEN_TXN_MAX_SEAMS, sizeof(*extra));
        uint32_t found = 0;
        if (extra && MapGenTransaction_DonorSeams(txn->baseline_bsp, extra, MAPGEN_TXN_MAX_SEAMS, &found)
                     == MAPGEN_SEAMS_OK) {
            for (uint32_t i = 0; i < found && txn->num_donor_seams < MAPGEN_TXN_MAX_SEAMS; i++)
                if (MapGenTransaction_NewSeam(&extra[i], txn->donor_seam, txn->num_donor_seams))
                    txn->donor_seam[txn->num_donor_seams++] = extra[i];
        }
        free(extra);
    }

    /*
     * And the operators measure against the BASELINE from the first edit.
     *
     * Until now the ground was set only when something was accepted, so every
     * edit before the first acceptance asked the DONOR'S OWN FILE whether
     * there was a way through where it meant to build - while the route gate
     * below judged it against the baseline, which is the donor written back
     * out and compiled again. Those are two different maps: the round trip
     * moves places about, and it is the reason a gate was found charging the
     * operators for the compiler twice in two days.
     *
     * MEASURED: seed 1's block at edit 8 stands at 153 102 176 .. 368 284 240
     * and asked the donor's file whether 176 128 192 was a climb. It said no.
     * In the baseline it is one, and the edit was refused after its compile
     * for burying it. Three of the six constructions the route guard checks
     * fail this way and no other.
     *
     * A second handle on the same file rather than the baseline's own,
     * because the two have different lifetimes: this one is replaced by every
     * accepted candidate.
     */
    txn->accepted_map = load_bsp(txn->baseline_path);
    /* D19: until an acceptance hands a walk over, the parent is the baseline */
    txn->parent_is_baseline = true;

    /*
     * And the schedule is DEALT AGAIN, now that the baseline exists.
     *
     * Handing the ground over after the plan was dealt fixed the apply and
     * left the planner where it was: it had already asked the donor's own file
     * whether there was a way through where it meant to build, and thrown
     * away every place that file said no to. So the schedule was a schedule
     * for one map and the gates were about another.
     *
     * MEASURED on q2dm1 seed 1 with the baseline as the ground: the block at
     * edit 6 declined with "it stands on a way through" and the recut at edit
     * 44 with "there is a way through the region on the map as it is now" -
     * two of that seed's five constructions, a compile each, and neither of
     * them offered a second place to try.
     *
     * The seed is the same, so this is the same schedule; what changes is that
     * every question was put to the map the answer will be judged against. A
     * re-deal that fails leaves the first plan in place rather than leaving
     * the transaction with none.
     */
    txn->seed = seed;
    if (txn->accepted_map)
        (void)redeal(txn, false);
    MapGenGeometryEdit_SetGround(txn->plan, txn->accepted_map);

    /*
     * And the ways through the baseline, taken once.
     *
     * Every candidate is held to keeping them: a place with three floor
     * heights within reach is a stair, a step or a ledge to hop, and burying
     * one takes a way through the map away whatever the pickups say.
     */
    {
        const uint32_t found =
            MapGenBsp_Places(txn->baseline_bsp, 32.0f, NULL, 0);
        float (*places)[3] = found ? calloc(found, sizeof(*places)) : NULL;
        uint8_t *climb = found ? calloc(found, 1) : NULL;
        if (places && climb) {
            MapGenBsp_Places(txn->baseline_bsp, 32.0f, places, found);
            const uint32_t climbs = MapGenBsp_Climbs(places, found, climb);
            txn->climb = climbs ? calloc(climbs, sizeof(*txn->climb)) : NULL;
            if (txn->climb) {
                for (uint32_t i = 0; i < found; i++)
                    if (climb[i] && txn->num_climbs < climbs)
                        memcpy(txn->climb[txn->num_climbs++], places[i],
                               sizeof(places[i]));
            }
        }
        free(places);
        free(climb);
    }

    *out = txn;
    return MAPGEN_TXN_OK;
}

void MapGenTransaction_SetBand(mapgen_transaction_t *txn, uint32_t target,
                               uint32_t tolerance)
{
    if (!txn)
        return;
    txn->band_target = target;
    txn->band_tolerance = tolerance;
    txn->has_band = true;
}

void MapGenTransaction_Free(mapgen_transaction_t *txn)
{
    if (!txn)
        return;
    MapGenBsp_Free(txn->accepted_map);
    free(txn->climb);
    MapGenReach_Free(txn->parent_reach);
    MapGenReach_Free(txn->baseline_reach);
    MapGenBsp_Free(txn->baseline_bsp);
    MapGenGeometry_Free(txn->accepted);
    /* The plan first: it holds borrowed pointers into the other donors and
       freeing them before it would leave it pointing at nothing. */
    MapGenGeometryEdit_Free(txn->plan);
    for (uint32_t i = 0; i < txn->num_others; i++) {
        MapGenGeometry_Free(txn->other[i]);
        MapGenBsp_Free(txn->other_bsp[i]);
    }
    MapGenGeometry_Free(txn->donor);
    MapGenBsp_Free(txn->donor_bsp);
    free(txn);
}

/* ---- did this edit do anything? ------------------------------------------------ */

/*
 * Three answers, because there are three, and the code used to have two.
 *
 * The per-edit score is a difference of two aggregates that were measured with
 * routes OFF and rounded to integer permille before they were subtracted. A
 * zero in it means one of six things (Codex, 2026-09-06 section 3):
 *
 *     nothing changed;
 *     a real change smaller than one rounded permille;
 *     a change inside the same thirty-two unit cells;
 *     different structure with the same aggregate score;
 *     a route change the cheap measurement never looked at;
 *     compiler subdivision noise changing a representation.
 *
 * Only the first is NO_EFFECT. Rejecting on the zero itself discards the other
 * five - including, exactly, a mover or connector edit that changes where a
 * player can go without changing one solid cell, which is the kind of edit the
 * structural operators exist to make.
 */
typedef enum {
    EDIT_MOVED,        /* it changed the compiled map                       */
    EDIT_NOTHING,      /* MEASURED: it did not                              */
    EDIT_UNMEASURED    /* nobody could say - not the same as EDIT_NOTHING   */
} edit_effect_t;

/*
 * Two things can answer where the cheap score cannot.
 *
 * The bytes, first: a compile that produced the accepted map's own hash cannot
 * have moved a wall, a route or a mover, and that is a sound bound costing a
 * string compare. It is also the common case, because an operator that
 * declined to change the geometry writes the same .map.
 *
 * Otherwise the authoritative measurement, and against the ACCEPTED map rather
 * than against the baseline. That is the question being asked: not "how far is
 * this candidate from the reference" - two changes that cancel in that
 * aggregate are not nothing - but "did THIS edit change the map". Routes on,
 * and the result must actually be complete: an incomplete measurement is never
 * accepted as a complete one.
 */
static mapgen_reach_t *parent_walk(mapgen_transaction_t *txn,
                                   mapgen_transaction_step_t *step);

/* D25: does one entity read differently in two geometries - any key, any
   value, or where it stands? */
static bool entity_differs(const mapgen_geometry_t *a,
                           const mapgen_geometry_t *b, uint32_t e)
{
    const mapgen_geometry_entity_t *ea = MapGenGeometry_Entity(a, e);
    const mapgen_geometry_entity_t *eb = MapGenGeometry_Entity(b, e);
    if (!ea || !eb)
        return ea != eb;
    if (ea->num_pairs != eb->num_pairs || ea->has_origin != eb->has_origin)
        return true;
    if (ea->has_origin
        && memcmp(ea->origin, eb->origin, sizeof(ea->origin)) != 0)
        return true;
    for (uint32_t i = 0; i < ea->num_pairs; i++) {
        const char *ka = NULL, *va = NULL, *kb = NULL, *vb = NULL;
        MapGenGeometry_Pair(a, ea->first_pair + i, &ka, &va);
        MapGenGeometry_Pair(b, eb->first_pair + i, &kb, &vb);
        if (!ka || !va || !kb || !vb || strcmp(ka, kb) || strcmp(va, vb))
            return true;
    }
    return false;
}

static edit_effect_t
edit_effect(mapgen_transaction_t *txn, const mapgen_geometry_t *candidate,
            const mapgen_bsp_t *built, const mapgen_reach_t *walk,
            const char *bsp_sha256, mapgen_transaction_step_t *step)
{
    if (bsp_sha256 && bsp_sha256[0] && txn->accepted_sha256[0]
        && !strcmp(bsp_sha256, txn->accepted_sha256)) {
        /* Identical bytes. Measured, in the strongest sense available. */
        step->structural_measured = true;
        step->structural_routes = true;
        step->structural_cells = 0;
        return EDIT_NOTHING;
    }

    /*
     * D25 (assignment 24, ledger row 286): a family that moves no architecture
     * is judged by what it DOES move.
     *
     * A swap changes two classnames and a spawn move one origin, and neither
     * moves a cell, so the cell measure below answered EDIT_NOTHING for every
     * one of them: three swaps a run refused NO_EFFECT on rounds 27 and 30,
     * each after a compile and a walk, and the fork never swapped a weapon
     * (Fable, row 284). The entities the edit names are compared with the
     * parent's, and no route is measured for it. Everything else the attempt
     * judges - the walk, the drowned rule, the band - has already run.
     */
    uint32_t named[2];
    const uint32_t num_named =
        MapGenGeometryEdit_NamedEntities(txn->plan, step->edit.target, named,
                                         2u);
    if (num_named) {
        bool moved = false;
        for (uint32_t k = 0; k < num_named && !moved; k++)
            moved = entity_differs(txn->accepted, candidate, named[k]);
        step->structural_measured = true;
        step->structural_routes = false;
        step->structural_cells = 0;
        return moved ? EDIT_MOVED : EDIT_NOTHING;
    }

    mapgen_bsp_t *before = load_bsp(txn->accepted_bsp);
    if (!before)
        return EDIT_UNMEASURED;

    /*
     * D19 (assignment 23): routes from the walks this attempt already has - the
     * parent's and the candidate's own - instead of walking both files again.
     * Each is a walk of exactly the file measured here at the route axis's
     * budget; a missing one leaves the axis unmeasured, which is refused below
     * as a walk that gave up always was.
     */
    const mapgen_reach_t *parent = parent_walk(txn, step);
    mapgen_divergence_t d;
    memset(&d, 0, sizeof(d));
    const bool ok = MapGenDivergence_MeasureWalked(before, parent,
                                                   parent != NULL, built,
                                                   walk, walk != NULL, 100,
                                                   &d)
                    == MAPGEN_DIVERGENCE_OK;
    MapGenBsp_Free(before);
    if (!ok)
        return EDIT_UNMEASURED;

    step->structural_cells = d.changed_cells;
    step->structural_routes = d.routes_measured;
    /* `complete` is the measurement's own statement that every axis it needs
       ran. A route exploration that gave up is not a route axis of zero. */
    step->structural_measured = d.complete;
    if (!d.complete)
        return EDIT_UNMEASURED;

    return d.changed_cells ? EDIT_MOVED : EDIT_NOTHING;
}

/* ---- one attempt --------------------------------------------------------------- */

/*
 * Steps three to six on a candidate somebody else prepared.
 *
 * Shared by an attempt and by materialising, because they are the same six
 * steps and the only difference is whether an edit was applied first. Two
 * copies of this would be two chances for the gates to drift apart.
 */
static mapgen_transaction_verdict_t
judge(mapgen_transaction_t *txn, mapgen_geometry_t *candidate,
      uint32_t attempt, bool require_movement,
      mapgen_transaction_step_t *step);

static bool machine_serves(const mapgen_movers_t *movers, const float lo[3],
                           const float hi[3], float rise);
static bool point_in(const float p[3], const float lo[3], const float hi[3]);
static bool route_replaced(const mapgen_reach_t *reach, const float p[3]);

/* D18: wall milliseconds on the clock `compile_ms` has always used */
#define TXN_MS_SINCE(t) ((uint32_t)((clock() - (t)) * 1000 / CLOCKS_PER_SEC))
/* D28 (assignment 24): CPU milliseconds of this process since `t` */
#define TXN_CPU_SINCE(t) ((uint32_t)(Q2PROX_Cpu_ProcessMs() - (t)))

/*
 * D15 (assignment 22, ledger row 265): the reference a pair proof is excused
 * against is the PARENT - the map this attempt was applied to - not the donor.
 *
 * H6 walked `baseline_bsp` and cached it for the run, so after an accepted
 * tunnel a way the tunnel CREATED could be walled up by a flood and excused
 * because the donor never had it (Fable, 2026-09-13). The walk is taken
 * lazily, the first time a pair fails, and dropped whenever an acceptance
 * replaces the parent. Its time is charged to `parent_ms`, apart from the
 * pairs it answers.
 */
static mapgen_reach_t *baseline_walk(mapgen_transaction_t *txn,
                                     mapgen_transaction_step_t *step)
{
    if (!txn->baseline_reach_tried) {
        txn->baseline_reach_tried = true;
        const clock_t began = clock();
        if (!txn->baseline_bsp
            || MapGenReach_Explore(txn->baseline_bsp, 40000u,
                                   &txn->baseline_reach)
               != MAPGEN_REACH_OK) {
            MapGenReach_Free(txn->baseline_reach);
            txn->baseline_reach = NULL;
        }
        if (step)
            step->parent_ms += TXN_MS_SINCE(began);
    }
    return txn->baseline_reach;
}

static mapgen_reach_t *parent_walk(mapgen_transaction_t *txn,
                                   mapgen_transaction_step_t *step)
{
    /* D19: before the first acceptance the parent IS the baseline */
    if (txn->parent_is_baseline)
        return baseline_walk(txn, step);
    if (!txn->parent_reach_tried) {
        txn->parent_reach_tried = true;
        const clock_t began = clock();
        if (!txn->accepted_map
            || MapGenReach_Explore(txn->accepted_map, 40000u,
                                   &txn->parent_reach)
               != MAPGEN_REACH_OK) {
            MapGenReach_Free(txn->parent_reach);
            txn->parent_reach = NULL;
        }
        if (step)
            step->parent_ms += TXN_MS_SINCE(began);
    }
    return txn->parent_reach;
}

/*
 * D21 (assignment 23): how much of the PARENT's walk an edit of this size can
 * touch - its states, and those whose origin lies within 512 and within 1024
 * units (straight-line, to the nearest point of the edit's box). What an
 * incremental walk would save is the rest; this counts it before one is built.
 */
static void count_parent_near(const mapgen_reach_t *parent, const float lo[3],
                              const float hi[3],
                              mapgen_transaction_step_t *step)
{
    const uint32_t states = MapGenReach_NumStates(parent);
    step->parent_states = states;
    for (uint32_t s = 0; s < states; s++) {
        const mapgen_reach_state_t *st = MapGenReach_State(parent, s);
        if (!st)
            continue;
        float d2 = 0.0f;
        for (int a = 0; a < 3; a++) {
            const float o = st->origin[a];
            const float gap = o < lo[a] ? lo[a] - o
                            : o > hi[a] ? o - hi[a] : 0.0f;
            d2 += gap * gap;
        }
        if (d2 <= 512.0f * 512.0f)
            step->parent_near_512++;
        if (d2 <= 1024.0f * 1024.0f)
            step->parent_near_1024++;
    }
}

/*
 * Ledger row 297: which surfaces a player can see near an edit does the
 * candidate's own visibility hide, that the parent's did not?
 */
uint32_t MapGenTransaction_HiddenInSight(const mapgen_bsp_t *parent,
                                         const mapgen_bsp_t *candidate,
                                         const float (*eyes)[3],
                                         uint32_t num_eyes, const float lo[3],
                                         const float hi[3], float grow,
                                         float witness[6])
{
    if (witness)
        memset(witness, 0, 6 * sizeof(float));
    if (!parent || !candidate || !eyes || !num_eyes || !lo || !hi
        || !MapGenBsp_VisibilityBytes(parent)
        || !MapGenBsp_VisibilityBytes(candidate))
        return 0;

    typedef struct {
        float   p[3], n[3];
        int32_t mine, theirs;
    } sample_t;
    const uint32_t nf = MapGenBsp_NumFaces(candidate);
    sample_t *samples = malloc(sizeof(*samples) * ((size_t)nf * 7u + 1u));
    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (!samples || !MapGenTrace_Bind(&ctx, candidate)) {
        free(samples);
        return 0;
    }
    uint32_t ns = 0;
    for (uint32_t i = 0; i < nf; i++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(candidate, i);
        const mapgen_bsp_texinfo_t *ti =
            MapGenBsp_TexInfo(candidate, (uint32_t)face->texinfo);
        /* sky, nodraw, hint and skip are not surfaces a hole shows through */
        if (!ti || (ti->flags & (0x4 | 0x80 | 0x100 | 0x200))
            || face->numedges < 3 || face->numedges > 32)
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(candidate, face->planenum);
        const float s = face->side ? -1.0f : 1.0f;
        const float n[3] = { pl->normal[0] * s, pl->normal[1] * s,
                             pl->normal[2] * s };
        float corner[32][3], mid[3] = { 0.0f, 0.0f, 0.0f };
        for (int32_t e = 0; e < face->numedges; e++) {
            const int32_t se =
                MapGenBsp_SurfEdge(candidate, (uint32_t)(face->firstedge + e));
            const mapgen_bsp_edge_t *ed =
                MapGenBsp_Edge(candidate, (uint32_t)(se < 0 ? -se : se));
            const mapgen_bsp_vertex_t *v =
                MapGenBsp_Vertex(candidate, se < 0 ? ed->v[1] : ed->v[0]);
            for (int a = 0; a < 3; a++) {
                corner[e][a] = v->point[a];
                mid[a] += v->point[a] / (float)face->numedges;
            }
        }
        bool near = true;
        for (int a = 0; a < 3 && near; a++)
            near = mid[a] >= lo[a] - grow && mid[a] <= hi[a] + grow;
        if (!near)
            continue;
        for (int32_t k = -1; k < face->numedges && k < 6; k++) {
            sample_t *sm = &samples[ns];
            for (int a = 0; a < 3; a++) {
                sm->p[a] = (k < 0 ? mid[a] : 0.5f * (mid[a] + corner[k][a]))
                         + n[a] * 1.5f;
                sm->n[a] = n[a];
            }
            if (MapGenBsp_PointContents(candidate, sm->p) & MAPGEN_CONTENTS_SOLID)
                continue;
            const mapgen_bsp_leaf_t *mine = MapGenBsp_PointLeaf(candidate, sm->p);
            const mapgen_bsp_leaf_t *theirs = MapGenBsp_PointLeaf(parent, sm->p);
            sm->mine = mine ? mine->cluster : -1;
            sm->theirs = theirs ? theirs->cluster : -1;
            ns++;
        }
    }

    const float bmin[3] = { -MAPGEN_TXN_HIDDEN_HALF, -MAPGEN_TXN_HIDDEN_HALF,
                            -MAPGEN_TXN_HIDDEN_HALF };
    const float bmax[3] = { MAPGEN_TXN_HIDDEN_HALF, MAPGEN_TXN_HIDDEN_HALF,
                            MAPGEN_TXN_HIDDEN_HALF };
    uint32_t lost = 0;
    uint64_t traced = 0;
    for (uint32_t e = 0; e < num_eyes && traced < 8000000u; e++) {
        const mapgen_bsp_leaf_t *em = MapGenBsp_PointLeaf(candidate, eyes[e]);
        const mapgen_bsp_leaf_t *ep = MapGenBsp_PointLeaf(parent, eyes[e]);
        if (!em || em->cluster < 0 || !ep)
            continue;
        for (uint32_t k = 0; k < ns; k++) {
            const sample_t *sm = &samples[k];
            const float to_eye = (eyes[e][0] - sm->p[0]) * sm->n[0]
                               + (eyes[e][1] - sm->p[1]) * sm->n[1]
                               + (eyes[e][2] - sm->p[2]) * sm->n[2];
            if (to_eye <= 0.0f)
                continue;                   /* behind it: culled anyway */
            if (MapGenBsp_ClusterSees(candidate, em->cluster, sm->mine))
                continue;
            if (!MapGenBsp_ClusterSees(parent, ep->cluster, sm->theirs))
                continue;                   /* the parent hid it too */
            mapgen_trace_result_t tr;
            MapGenTrace_Box(&ctx, eyes[e], sm->p, bmin, bmax,
                            MAPGEN_TXN_HIDDEN_STOPS, &tr);
            traced++;
            if (tr.startsolid || tr.fraction < 1.0f)
                continue;
            if (!lost && witness) {
                memcpy(witness, eyes[e], 3 * sizeof(float));
                memcpy(witness + 3, sm->p, 3 * sizeof(float));
            }
            lost++;
        }
    }
    MapGenTrace_Release(&ctx);
    free(samples);
    return lost;
}

/*
 * Row 299: the hidden-surface question asked from one walk's places - its
 * reachable states inside the edit's box grown by MAPGEN_TXN_HIDDEN_GROW, at
 * view height over each origin. Returns the pairs lost; `witness` the first.
 */
static uint32_t
hidden_from_walk(const mapgen_bsp_t *parent, const mapgen_bsp_t *candidate,
                 const mapgen_reach_t *walk, const float lo[3],
                 const float hi[3], float witness[6])
{
    memset(witness, 0, 6 * sizeof(float));
    const uint32_t states = walk ? MapGenReach_NumStates(walk) : 0u;
    float (*eyes)[3] = malloc(sizeof(*eyes) * (states ? states : 1u));
    uint32_t num_eyes = 0;
    for (uint32_t s = 0; eyes && s < states; s++) {
        const mapgen_reach_state_t *st = MapGenReach_State(walk, s);
        if (!st || !st->reachable)
            continue;
        bool by_it = true;
        for (int a = 0; a < 3 && by_it; a++)
            by_it = st->origin[a] >= lo[a] - MAPGEN_TXN_HIDDEN_GROW
                 && st->origin[a] <= hi[a] + MAPGEN_TXN_HIDDEN_GROW;
        if (!by_it)
            continue;
        eyes[num_eyes][0] = st->origin[0];
        eyes[num_eyes][1] = st->origin[1];
        eyes[num_eyes][2] = st->origin[2] + MAPGEN_TXN_VIEW_HEIGHT;
        num_eyes++;
    }
    const uint32_t lost = eyes && num_eyes
        ? MapGenTransaction_HiddenInSight(parent, candidate,
                                          (const float (*)[3])eyes, num_eyes,
                                          lo, hi, MAPGEN_TXN_HIDDEN_GROW,
                                          witness)
        : 0u;
    free(eyes);
    return lost;
}

/*
 * Row 302: the pickups the game frees at spawn - see the header.
 */
static bool pickup_classname(const char *c)
{
    return !strncmp(c, "weapon_", 7) || !strncmp(c, "item_", 5)
        || !strncmp(c, "ammo_", 5);
}

/* Brush models the game makes solid and leaves where they were drawn; doors,
   lifts, trains and buttons are read as movers instead. */
static bool drawn_solid_classname(const char *c)
{
    return !strcmp(c, "func_wall") || !strcmp(c, "func_object")
        || !strcmp(c, "func_explosive") || !strcmp(c, "func_rotating")
        || !strcmp(c, "func_conveyor");
}

/* One entity of the entity text: its classname, origin and "*N" model. Returns
   where the next one starts, or NULL at the end or at text it cannot read. */
static const char *entity_keys(const char *s, const char *end,
                               char classname[64], float origin[3],
                               bool *has_origin, int32_t *model)
{
    classname[0] = '\0';
    *has_origin = false;
    *model = -1;
    while (s < end && *s != '{')
        s++;
    if (s >= end)
        return NULL;
    s++;
    for (;;) {
        while (s < end && (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n'))
            s++;
        if (s >= end || *s != '"')
            return s < end && *s == '}' ? s + 1 : NULL;
        const char *key = ++s;
        while (s < end && *s != '"')
            s++;
        if (s >= end)
            return NULL;
        const size_t key_len = (size_t)(s - key);
        s++;
        while (s < end && *s != '"')
            s++;
        if (s >= end)
            return NULL;
        const char *value = ++s;
        while (s < end && *s != '"')
            s++;
        if (s >= end)
            return NULL;
        size_t value_len = (size_t)(s - value);
        s++;
        char buf[64];
        if (value_len > sizeof(buf) - 1)
            value_len = sizeof(buf) - 1;
        memcpy(buf, value, value_len);
        buf[value_len] = '\0';
        if (key_len == 9 && !strncmp(key, "classname", 9))
            memcpy(classname, buf, value_len + 1);
        else if (key_len == 6 && !strncmp(key, "origin", 6))
            *has_origin = sscanf(buf, "%f %f %f", &origin[0], &origin[1],
                                 &origin[2]) == 3;
        else if (key_len == 5 && !strncmp(key, "model", 5) && buf[0] == '*')
            *model = atoi(buf + 1);
    }
}

uint32_t MapGenTransaction_PickupsLostAtSpawn(const mapgen_bsp_t *bsp,
                                              mapgen_lost_pickup_t *out,
                                              uint32_t max_out)
{
    uint32_t length = 0;
    const char *text = bsp ? MapGenBsp_Entities(bsp, &length) : NULL;
    if (!text || !length)
        return 0;
    const char *const end = text + length;

    mapgen_movers_t *movers = calloc(1, sizeof(*movers));
    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (!movers || !MapGenTrace_Bind(&ctx, bsp)) {
        free(movers);
        return 0;
    }
    if (!MapGenMovers_Read(bsp, movers))
        movers->num_movers = 0;

    char classname[64];
    float origin[3] = { 0.0f, 0.0f, 0.0f };
    bool has_origin = false;
    int32_t model = -1;
    int32_t drawn[256];
    uint32_t num_drawn = 0;
    for (const char *s = text;
         (s = entity_keys(s, end, classname, origin, &has_origin, &model));) {
        if (model > 0 && drawn_solid_classname(classname) && num_drawn < 256u)
            drawn[num_drawn++] = model;
    }

    const float mins[3] = { -15.0f, -15.0f, -15.0f };
    const float maxs[3] = { 15.0f, 15.0f, 15.0f };
    uint32_t lost = 0;
    for (const char *s = text;
         (s = entity_keys(s, end, classname, origin, &has_origin, &model));) {
        if (!has_origin || !pickup_classname(classname))
            continue;
        const float down[3] = { origin[0], origin[1], origin[2] - 128.0f };
        char inside[112] = "";
        mapgen_trace_result_t tr;
        MapGenTrace_Box(&ctx, origin, down, mins, maxs, MAPGEN_TXN_MASK_SOLID,
                        &tr);
        if (tr.startsolid)
            snprintf(inside, sizeof(inside), "the world");
        for (uint32_t m = 0; !inside[0] && m < movers->num_movers; m++) {
            mapgen_trace_result_t mt;
            memset(&mt, 0, sizeof(mt));
            mt.fraction = 1.0f;
            MapGenTrace_BoxModel(&ctx, movers->movers[m].model,
                                 MapGenMovers_Displacement(movers, m, 0),
                                 origin, down, mins, maxs,
                                 MAPGEN_TXN_MASK_SOLID, &mt);
            if (mt.startsolid)
                snprintf(inside, sizeof(inside), "%s *%u where it rests",
                         movers->movers[m].classname, movers->movers[m].model);
        }
        for (uint32_t m = 0; !inside[0] && m < num_drawn; m++) {
            mapgen_trace_result_t mt;
            memset(&mt, 0, sizeof(mt));
            mt.fraction = 1.0f;
            MapGenTrace_BoxModel(&ctx, (uint32_t)drawn[m], NULL, origin, down,
                                 mins, maxs, MAPGEN_TXN_MASK_SOLID, &mt);
            if (mt.startsolid)
                snprintf(inside, sizeof(inside), "brush model *%d as drawn",
                         drawn[m]);
        }
        if (!inside[0])
            continue;
        if (out && lost < max_out) {
            memcpy(out[lost].classname, classname, sizeof(classname));
            memcpy(out[lost].origin, origin, sizeof(origin));
            memcpy(out[lost].inside, inside, sizeof(inside));
        }
        lost++;
    }
    MapGenTrace_Release(&ctx);
    free(movers);
    return lost;
}

static bool boxes_overlap(const float alo[3], const float ahi[3],
                          const float blo[3], const float bhi[3])
{
    for (int a = 0; a < 3; a++) {
        const float lo = alo[a] > blo[a] ? alo[a] : blo[a];
        const float hi = ahi[a] < bhi[a] ? ahi[a] : bhi[a];
        if (hi - lo <= 0.0f)
            return false;
    }
    return true;
}

/*
 * Row 307: the spawn points a carrying mover runs into - see the header.
 */
uint32_t MapGenTransaction_SpawnsInMoverColumns(const mapgen_bsp_t *bsp,
                                                mapgen_blocked_spawn_t *out,
                                                uint32_t max_out)
{
    uint32_t length = 0;
    const char *text = bsp ? MapGenBsp_Entities(bsp, &length) : NULL;
    if (!text || !length)
        return 0;
    const char *const end = text + length;
    mapgen_movers_t *movers = calloc(1, sizeof(*movers));
    if (!movers)
        return 0;
    if (!MapGenMovers_Read(bsp, movers))
        movers->num_movers = 0;

    char classname[64];
    float origin[3] = { 0.0f, 0.0f, 0.0f };
    bool has_origin = false;
    int32_t model = -1;
    uint32_t blocked = 0;
    for (const char *s = text;
         (s = entity_keys(s, end, classname, origin, &has_origin, &model));) {
        if (!has_origin || strncmp(classname, "info_player_", 12))
            continue;
        const float pad_lo[3] = { origin[0] - 32.0f, origin[1] - 32.0f,
                                  origin[2] - 24.0f };
        const float pad_hi[3] = { origin[0] + 32.0f, origin[1] + 32.0f,
                                  origin[2] - 16.0f };
        const float body_lo[3] = { origin[0] - 16.0f, origin[1] - 16.0f,
                                   origin[2] - 24.0f };
        const float body_hi[3] = { origin[0] + 16.0f, origin[1] + 16.0f,
                                   origin[2] + 32.0f };
        const mapgen_mover_t *hit = NULL;
        for (uint32_t m = 0; !hit && m < movers->num_movers; m++) {
            const mapgen_mover_t *mv = &movers->movers[m];
            if (!mv->carries || !mv->num_stops)
                continue;
            float lo[3], hi[3];
            for (int a = 0; a < 3; a++) {
                float low = mv->stop[0][a], high = mv->stop[0][a];
                for (uint32_t k = 1; k < mv->num_stops; k++) {
                    low = mv->stop[k][a] < low ? mv->stop[k][a] : low;
                    high = mv->stop[k][a] > high ? mv->stop[k][a] : high;
                }
                lo[a] = mv->mins[a] + low;
                hi[a] = mv->maxs[a] + high;
            }
            lo[0] -= 16.0f;
            lo[1] -= 16.0f;
            hi[0] += 16.0f;
            hi[1] += 16.0f;
            hi[2] += MAPGEN_TXN_RIDER_HEIGHT;
            if (boxes_overlap(lo, hi, pad_lo, pad_hi)
                || boxes_overlap(lo, hi, body_lo, body_hi))
                hit = mv;
        }
        if (!hit)
            continue;
        if (out && blocked < max_out) {
            memcpy(out[blocked].classname, classname, sizeof(classname));
            memcpy(out[blocked].origin, origin, sizeof(origin));
            snprintf(out[blocked].mover, sizeof(out[blocked].mover), "%s *%u",
                     hit->classname, hit->model);
        }
        blocked++;
    }
    free(movers);
    return blocked;
}

static mapgen_transaction_verdict_t
try_one(mapgen_transaction_t *txn, const mapgen_typed_edit_t *edit,
        mapgen_transaction_step_t *step)
{
    step->edit = *edit;
    const uint32_t attempt = txn->attempted++;

    const clock_t attempt_began = clock();
    /* --- 1: a clone of the last accepted candidate ---------------------- */

    mapgen_geometry_t *candidate = NULL;
    if (MapGenGeometry_Clone(txn->accepted, &candidate) != MAPGEN_GEOMETRY_OK)
        return step->verdict = MAPGEN_TXN_REJECTED_WRITE;

    /* --- 2: exactly one edit -------------------------------------------- */

    bool changed = false;
    const uint32_t skins_before = MapGenGeometryEdit_SkySkins();
    MapGenGeometryEdit_ApplyOne(txn->plan, candidate, txn->donor,
                                edit->target, &changed);
    /* row 371: did this edit dress a dig in a sky skin? */
    s_attempt_skinned = MapGenGeometryEdit_SkySkins() > skins_before;
    if (!changed) {
        /* The operator declined. That is a fact about the operator and the
           map, not a failure, and it costs nothing: no compile, no directory,
           and the accepted candidate has not moved. It says WHY, which is the
           difference between a ledger that counts refusals and one that can
           be acted on. */
        snprintf(step->declined, sizeof(step->declined), "%s",
                 MapGenGeometryEdit_WhyDeclined());
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_NOT_APPLIED;
    }
    /*
     * What it left has to be buildable.
     *
     * The compiler does not refuse a T-junction; it builds the crack and ships
     * it, so nothing downstream of here would ever see this. The donor's own
     * count is the floor - q2dm1's brushes come out of a compiled tree that
     * split them - and an edit is held only to not adding to it.
     */
    /*
     * An entity that owns a model has to own brushes.
     *
     * Asked here rather than after the compile because it is a property of
     * the geometry and costs a scan, and because the compile cannot see it:
     * a brush entity with nothing in it produces a valid BSP with one model
     * fewer than the entity lump refers to, and only the game notices.
     */
    for (uint32_t e = 0; e < MapGenGeometry_NumEntities(candidate); e++) {
        const mapgen_geometry_entity_t *ent =
            MapGenGeometry_Entity(candidate, e);
        if (!ent || !ent->model)
            continue;
        bool owned = false;
        for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(candidate)
                             && !owned; b++) {
            const mapgen_geometry_brush_t *gb =
                MapGenGeometry_Brush(candidate, b);
            owned = gb && gb->model == ent->model;
        }
        if (!owned) {
            MapGenGeometry_Free(candidate);
            return step->verdict = MAPGEN_TXN_REJECTED_ORPHANED_MODEL;
        }
    }

    /*
     * And nobody is standing in the water.
     *
     * The donor's own count is the floor, exactly as it is for surface
     * faults: a map whose designer put a weapon in a pool may be forked, and
     * an edit is held only to not drowning anything that was dry. A SPAWN is
     * absolute - there is no donor in this corpus that spawns a player
     * swimming, and if one appears its own baseline count will say so.
     */
    {
        char who[128] = "";
        const uint32_t wet =
            MapGenGeometry_DrownedEntities(candidate, false, who, sizeof(who));
        if (wet > txn->donor_drowned) {
            MapGenGeometry_Free(candidate);
            return step->verdict = MAPGEN_TXN_REJECTED_DROWNED;
        }
    }

    /*
     * And nothing has taken a piece out of a machine.
     *
     * Asked of the GEOMETRY, before a compile is spent on it: every model the
     * donor has must still own brushes with the same bounds. An edit that
     * addressed its brushes by an index the accepted geometry had renumbered
     * is how q2dm1's own lift became a fragment, and neither the compiler nor
     * the orphan gate above can see it.
     */
    if (!MapGenGeometry_ModelsIntact(txn->donor, candidate)) {
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_MUTILATED_MODEL;
    }

    /*
     * The source count is RECORDED, and it is no longer a gate.
     *
     * It counts a vertex of one face in the middle of a coplanar neighbour's
     * edge, in the BRUSHES - and the compiler's own FixTjuncs pass, on by
     * default over the world and every submodel, stitches exactly that before
     * anybody sees the map. MEASURED on the candidates it refused: a pushed
     * wall at +18 in the source, a recut at +4, a lift at +5, and all three
     * compile to precisely the fourteen T-junctions q2dm1's own file has.
     * Those fourteen are its big lift's edges against world faces, which
     * FixTjuncs does not stitch across models - so the rule was refusing
     * cracks that do not exist and passing the ones that do.
     *
     * It cost the push-wall every one of its six candidates, the
     * open-connector its only one, a third of the lifts and every recut, and
     * with them the whole of the F75 band. The question is asked of the
     * COMPILED file below, where the answer is about the map a player loads.
     */
    step->faults_after = MapGenGeometry_SurfaceFaults(candidate, txn->donor_bsp);

    /* D18: the clone and the edit's own apply, before the gates take over */
    step->apply_ms = TXN_MS_SINCE(attempt_began);
    const mapgen_transaction_verdict_t verdict =
        judge(txn, candidate, attempt, true, step);
    s_attempt_skinned = false;

    /*
     * A graft that is RETAINED is a donor that contributed.
     *
     * Recorded where the edit is known AND the verdict is in, which is
     * neither where it was planned nor where it was applied: a contribution
     * floor met by a room that was tried and thrown away is not a floor.
     */
    if (verdict == MAPGEN_TXN_ACCEPTED) {
        /*
         * `edit->target` is the position in the SCHEDULE, which is what
         * ApplyOne takes; the graft's own index is the schedule entry's
         * target. Asking GraftedFrom with the schedule position was the first
         * version of this, and the report caught it by saying something that
         * cannot be true - one graft kept and no donor having contributed.
         */
        const mapgen_geometry_edit_t *planned =
            MapGenGeometryEdit_At(txn->plan, edit->target);
        if (planned && planned->kind == MAPGEN_EDIT_GRAFT_BUNDLE) {
            txn->grafts_accepted++;
            const char *from =
                MapGenGeometryEdit_GraftedFrom(txn->plan, planned->target);
            for (uint32_t i = 0; i < txn->num_others; i++)
                if (from && !strcmp(from, txn->other_name[i]))
                    txn->other_used[i] = true;
        }
        /* brief 9: a room of the second map, or one in its skin, is that map's contribution too */
        if (planned && planned->kind == MAPGEN_EDIT_DIG) {
            const char *from = MapGenGeometryEdit_DigFrom(txn->plan, planned->target);
            for (uint32_t i = 0; i < txn->num_others; i++)
                if (from && !strcmp(from, txn->other_name[i]))
                    txn->other_used[i] = true;
        }
    }
    return verdict;
}

mapgen_transaction_verdict_t
MapGenTransaction_Materialise(mapgen_transaction_t *txn,
                              mapgen_transaction_step_t *step)
{
    mapgen_transaction_step_t local;
    if (!step)
        step = &local;
    memset(step, 0, sizeof(*step));
    if (!txn)
        return step->verdict = MAPGEN_TXN_REJECTED_WRITE;

    mapgen_geometry_t *candidate = NULL;
    if (MapGenGeometry_Clone(txn->accepted, &candidate) != MAPGEN_GEOMETRY_OK)
        return step->verdict = MAPGEN_TXN_REJECTED_WRITE;
    /* Nothing was applied, so the surfaces are the accepted ones and nothing
       is required to have moved. */
    step->faults_after = txn->accepted_faults;
    s_attempt_skinned = false;
    const mapgen_transaction_verdict_t verdict =
        judge(txn, candidate, txn->attempted++, false, step);
    if (txn->num_steps < MAX_STEPS)
        txn->steps[txn->num_steps++] = *step;
    return verdict;
}

static mapgen_transaction_verdict_t
judge(mapgen_transaction_t *txn, mapgen_geometry_t *candidate,
      uint32_t attempt, bool require_movement,
      mapgen_transaction_step_t *step)
{

    /* --- 3: written and compiled in a directory of its own -------------- */

    char dir[MAPCOMPILE_MAX_PATH];
    char map_path[MAPCOMPILE_MAX_PATH];
    if (!attempt_dir(txn, attempt, dir, sizeof(dir))
        || snprintf(map_path, sizeof(map_path), "%s/%s.map", dir,
                    txn->map_name) >= (int)sizeof(map_path)) {
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_WRITE;
    }
    if (MapGenGeometry_WriteValve220(candidate, map_path)
        != MAPGEN_GEOMETRY_OK) {
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_WRITE;
    }

    mapcompile_request_t request;
    memset(&request, 0, sizeof(request));
    snprintf(request.job_dir, sizeof(request.job_dir), "%s", dir);
    snprintf(request.map_name, sizeof(request.map_name), "%s", txn->map_name);
    snprintf(request.moddir, sizeof(request.moddir), "%s", txn->moddir);
    snprintf(request.basedir, sizeof(request.basedir), "%s", txn->moddir);
    request.profile = MAPCOMPILE_PROFILE_DRAFT;
    request.format = MAPCOMPILE_FORMAT_IBSP;
    request.threads = MAPCOMPILE_PINNED_THREADS;
    request.stage_timeout_ms = 1800000;
    request.max_log_bytes = 262144;
    request.disk_budget_bytes = 512ull * 1024ull * 1024ull;

    /*
     * Zeroed before the call, not after it.
     *
     * The stage logs are freed from this report whatever the compile did, and
     * a compiler that refuses before the runner fills anything in leaves it
     * holding whatever was on the stack. Every attempt in this session used a
     * compiler that succeeded, so it took the product path - where the first
     * fake compiler that fails on purpose segfaulted immediately - to find it.
     */
    mapcompile_report_t compiled;
    memset(&compiled, 0, sizeof(compiled));
    const clock_t began = clock();
    const mapcompile_result_t crc =
        MapCompile_RunProfile(txn->adapter, &request, &compiled);
    step->compile_ms =
        (uint32_t)((clock() - began) * 1000 / CLOCKS_PER_SEC);
    step->compile_result = crc;
    snprintf(step->bsp_sha256, sizeof(step->bsp_sha256), "%s",
             compiled.bsp_sha256);
    for (int i = 0; i < compiled.num_stages; i++)
        free(compiled.stages[i].stdout_captured);

    if (crc != MAPCOMPILE_OK) {
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_COMPILE;
    }

    /* --- 4: every hard gate, on what actually came out ------------------ */

    const clock_t load_began = clock();
    mapgen_bsp_t *built = load_bsp(compiled.bsp_path);
    step->load_ms = TXN_MS_SINCE(load_began);
    if (!built) {
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_COMPILE;
    }

    /*
     * Row 302: and no pickup the parent kept is FREED by the game at spawn.
     *
     * The PO, 2026-09-14, on mg_20e: «Не нашел где теперь лежит chaingun». The
     * file had it; its own server freed it, and the jacket armour, a box of
     * bullets and three shards with it, each inside the resting deck of a dig's
     * lift - on every map this pipeline had made. Asked before any walk: the
     * compiled map and a few hundred sweeps. A pickup the parent already lost
     * is not this attempt's to answer for.
     */
    if (require_movement && txn->accepted_map) {
        mapgen_lost_pickup_t *mine = calloc(256, sizeof(*mine));
        const uint32_t n_mine =
            mine ? MapGenTransaction_PickupsLostAtSpawn(built, mine, 256) : 0u;
        mapgen_lost_pickup_t *theirs =
            n_mine ? calloc(256, sizeof(*theirs)) : NULL;
        const uint32_t n_theirs =
            theirs ? MapGenTransaction_PickupsLostAtSpawn(txn->accepted_map,
                                                          theirs, 256)
                   : 0u;
        uint32_t new_losses = 0, first = UINT32_MAX;
        for (uint32_t i = 0; i < n_mine && i < 256u; i++) {
            bool parent_lost_it = false;
            for (uint32_t j = 0; j < n_theirs && j < 256u && !parent_lost_it;
                 j++) {
                bool same = !strcmp(mine[i].classname, theirs[j].classname);
                for (int a = 0; a < 3 && same; a++) {
                    const float d = mine[i].origin[a] - theirs[j].origin[a];
                    same = d > -0.5f && d < 0.5f;
                }
                parent_lost_it = same;
            }
            if (parent_lost_it)
                continue;
            if (first == UINT32_MAX)
                first = i;
            new_losses++;
        }
        if (new_losses) {
            snprintf(step->declined, sizeof(step->declined),
                     "lost pickup: the game frees %s at %.0f %.0f %.0f at spawn"
                     " - its box starts inside %s (%u the parent kept)",
                     mine[first].classname, (double)mine[first].origin[0],
                     (double)mine[first].origin[1],
                     (double)mine[first].origin[2], mine[first].inside,
                     new_losses);
            free(mine);
            free(theirs);
            MapGenBsp_Free(built);
            MapGenGeometry_Free(candidate);
            return step->verdict = MAPGEN_TXN_REJECTED_LOST_PICKUP;
        }
        free(mine);
        free(theirs);
    }

    /*
     * Row 307: and no spawn its parent kept clear stands in the column a lift
     * or a train carries its rider through.
     *
     * The PO, 2026-09-14, on mg_20f: «лифт ... упирается в место респавна и не
     * поднимается из за этого выше». A dig dealt to q2dm1's spawn spot had dug
     * the floor from under that spawn; at the top of its travel the lift's rider
     * met the spawn's pad and the plat went back down. Asked before any walk.
     */
    if (require_movement && txn->accepted_map) {
        mapgen_blocked_spawn_t *mine = calloc(64, sizeof(*mine));
        const uint32_t n_mine =
            mine ? MapGenTransaction_SpawnsInMoverColumns(built, mine, 64)
                 : 0u;
        mapgen_blocked_spawn_t *theirs =
            n_mine ? calloc(64, sizeof(*theirs)) : NULL;
        const uint32_t n_theirs =
            theirs ? MapGenTransaction_SpawnsInMoverColumns(txn->accepted_map,
                                                            theirs, 64)
                   : 0u;
        uint32_t new_blocks = 0, first = UINT32_MAX;
        for (uint32_t i = 0; i < n_mine && i < 64u; i++) {
            bool parent_had_it = false;
            for (uint32_t j = 0; j < n_theirs && j < 64u && !parent_had_it;
                 j++) {
                bool same = !strcmp(mine[i].classname, theirs[j].classname);
                for (int a = 0; a < 3 && same; a++) {
                    const float d = mine[i].origin[a] - theirs[j].origin[a];
                    same = d > -0.5f && d < 0.5f;
                }
                parent_had_it = same;
            }
            if (parent_had_it)
                continue;
            if (first == UINT32_MAX)
                first = i;
            new_blocks++;
        }
        if (new_blocks) {
            snprintf(step->declined, sizeof(step->declined),
                     "blocked spawn: %s at %.0f %.0f %.0f stands in the column"
                     " %s carries its rider through (%u the parent kept clear)",
                     mine[first].classname, (double)mine[first].origin[0],
                     (double)mine[first].origin[1],
                     (double)mine[first].origin[2], mine[first].mover,
                     new_blocks);
            free(mine);
            free(theirs);
            MapGenBsp_Free(built);
            MapGenGeometry_Free(candidate);
            return step->verdict = MAPGEN_TXN_REJECTED_BLOCKED_SPAWN;
        }
        free(mine);
        free(theirs);
    }

    /*
     * Row 299: the hidden-surface gate asked FIRST from the parent's own
     * places, before this attempt walks. Round 33 refused thirteen attempts
     * after walking each of them - 1719 s of walks, a third of a run that
     * then ran out of time - so a surface the candidate hides from a place a
     * player already stood costs the compile and not a walk. The parent's
     * walk is the one D21 reads for every attempt anyway. The places this
     * attempt makes are asked after its walk, below.
     */
    if (require_movement && txn->accepted_map) {
        float vlo[3], vhi[3], witness[6];
        const mapgen_reach_t *before = NULL;
        if (MapGenGeometryEdit_BoxOf(txn->plan, NULL, NULL, step->edit.target,
                                     vlo, vhi)
            && (before = parent_walk(txn, step)) != NULL) {
            const uint32_t lost = hidden_from_walk(txn->accepted_map, built,
                                                   before, vlo, vhi, witness);
            if (lost) {
                snprintf(step->declined, sizeof(step->declined),
                         "hidden: from %.0f %.0f %.0f, where the parent's walk"
                         " stood, the drawn face at %.0f %.0f %.0f is in plain"
                         " sight and the map's own visibility no longer shows"
                         " it (%u pairs)",
                         (double)witness[0], (double)witness[1],
                         (double)witness[2], (double)witness[3],
                         (double)witness[4], (double)witness[5], lost);
                MapGenBsp_Free(built);
                MapGenGeometry_Free(candidate);
                return step->verdict = MAPGEN_TXN_REJECTED_HIDDEN;
            }
        }
    }

    /*
     * Explored ONCE, and kept until everything that reads it has read it.
     *
     * The worth gate below asks which of these places stand on the thing that
     * was built, and asking it of a second exploration of the same file is a
     * minute of walking spent to learn what is already in memory.
     */
    mapgen_reach_t *reach = NULL;
    mapgen_reach_report_t reach_report;
    memset(&reach_report, 0, sizeof(reach_report));
    bool playable = false;
    bool held = false;            /* row 405: refused by the donor comparison */
    char held_why[200] = "";
    const clock_t reach_began = clock();
    const uint64_t reach_cpu_began = Q2PROX_Cpu_ProcessMs();
    const bool explored =
        MapGenReach_Explore(built, 40000u, &reach) == MAPGEN_REACH_OK;
    step->reach_ms = TXN_MS_SINCE(reach_began);
    step->reach_cpu_ms = TXN_CPU_SINCE(reach_cpu_began);
    if (explored && reach) {
        reach_report = *MapGenReach_Report(reach);
        playable = MapGenReach_Passed(&reach_report);
        /* row 400: on a donor whose own walk fails the absolutes, no worse than the donor */
        if (!playable) {
            const mapgen_reach_t *base = baseline_walk(txn, step);
            /* row 409: and no trap of its own - a place reached and not left that the donor has none of near it.
               By count alone mg_cor kept a pool reached through a shot pane: 74 such places, the first at
               -660 -1356 -82, inside cor's own 2860 */
            float trap_at[3] = { 0, 0, 0 };
            const uint32_t fresh = base ? MapGenReach_NewTraps(reach, base, MAPGEN_REACH_NEW_TRAP_RADIUS, trap_at)
                                        : 0u;
            if (fresh > MAPGEN_REACH_NEW_TRAP_SLACK) {
                snprintf(held_why, sizeof(held_why), "%u new places a player reaches and cannot leave, the first at"
                         " %.0f %.0f %.0f", fresh, (double)trap_at[0], (double)trap_at[1], (double)trap_at[2]);
                held = true;
            } else if (base && MapGenReach_NoWorseThanWhy(&reach_report, MapGenReach_Report(base), held_why,
                                                          sizeof(held_why)))
                playable = true;
            /* row 405: the donor failing too is what the judge asked; say which of its axes refused */
            else if (base && !MapGenReach_Passed(MapGenReach_Report(base)))
                held = true;
        }
        /* D20 (assignment 23): the walk's shape, on every line */
        step->walk_states = reach_report.states;
        step->walk_edges = reach_report.edges;
        step->walk_levels = reach_report.levels;
        step->walk_levels_wide = reach_report.levels_wide;
        step->walk_rounds = reach_report.rounds;
        step->walk_movers = reach_report.movers;
        step->walk_simulated = reach_report.simulated;
        step->walk_reused = reach_report.reused;
    }
    /* D21: the parent's walk near this edit's box, for every attempt that
       compiled. Materialising applied nothing and has no box. */
    if (require_movement) {
        float elo[3], ehi[3];
        if (MapGenGeometryEdit_BoxOf(txn->plan, NULL, NULL, step->edit.target,
                                     elo, ehi)) {
            const mapgen_reach_t *parent = parent_walk(txn, step);
            if (parent)
                count_parent_near(parent, elo, ehi, step);
        }
    }

    if (!playable) {
        /*
         * And WHICH of the five absolutes failed, and where.
         *
         * `MapGenReach_Passed` answers one bool over five conditions and this
         * returned the verdict with `declined` EMPTY, so a refusal named
         * nothing: MEASURED 2026-09-13, the arena's flood came back
         * `REJECTED_UNPLAYABLE` with no reason at all, exactly as round9's third
         * room did (ledger rows 145, 163-164). Everything a reader needs was
         * already in the report and never reached the ledger - the same defect
         * as the pit in a lift's deck, the buried route and the blocking
         * machine, found in the third gate.
         *
         * Named in the order a reader can act on, and a walk that did not run is
         * its own case: a report of zeroes from an exploration that never
         * happened must not read as «nothing was wrong».
         */
        /*
         * Asked of `MapGenReach_FirstFailure`, the function the verdict itself
         * reads (ledger row 273). This chain used to ask its own questions and
         * named «N places have no way back» whenever `trapped` was not zero: on
         * round 27 a stairs-to-lift was refused naming the 77 lethal places of
         * a map that passed with them, and what refused it went unwritten
         * (row 272).
         */
        if (!reach) {
            snprintf(step->declined, sizeof(step->declined),
                     "unplayable: the reach walk did not run");
        } else if (held) {
            snprintf(step->declined, sizeof(step->declined), "unplayable, no worse than the donor failed: %s",
                     held_why);
        } else {
            switch (MapGenReach_FirstFailure(&reach_report)) {
            case MAPGEN_REACH_FAILS_STRANDED:
                snprintf(step->declined, sizeof(step->declined),
                         "unplayable: %u of %u starts cannot reach the others",
                         reach_report.spawns_stranded, reach_report.spawns);
                break;
            case MAPGEN_REACH_FAILS_TRAPPED:
                snprintf(step->declined, sizeof(step->declined),
                         "unplayable: %u places have no way back (%u lethal),"
                         " worst at %.0f %.0f %.0f", reach_report.trapped,
                         reach_report.trapped_lethal,
                         (double)reach_report.worst_trap[0],
                         (double)reach_report.worst_trap[1],
                         (double)reach_report.worst_trap[2]);
                break;
            case MAPGEN_REACH_FAILS_ITEMS:
                snprintf(step->declined, sizeof(step->declined),
                         "unplayable: %u of %u pickups out of reach, worst at"
                         " %.0f %.0f %.0f", reach_report.items_unreachable,
                         reach_report.items,
                         (double)reach_report.worst_item[0],
                         (double)reach_report.worst_item[1],
                         (double)reach_report.worst_item[2]);
                break;
            case MAPGEN_REACH_FAILS_LANDMARKS:
                snprintf(step->declined, sizeof(step->declined),
                         "unplayable: %u of %u landmarks out of reach, worst"
                         " at %.0f %.0f %.0f",
                         reach_report.landmarks_unreachable,
                         reach_report.landmarks,
                         (double)reach_report.worst_landmark[0],
                         (double)reach_report.worst_landmark[1],
                         (double)reach_report.worst_landmark[2]);
                break;
            case MAPGEN_REACH_FAILS_MOVERS:
                snprintf(step->declined, sizeof(step->declined),
                         "unplayable: %u machines nothing in the map can"
                         " operate", reach_report.movers_inoperable);
                break;
            default:
                snprintf(step->declined, sizeof(step->declined),
                         "unplayable: %u states, %u in the spawns' component",
                         reach_report.states, reach_report.component);
                break;
            }
        }
        MapGenReach_Free(reach);
        MapGenBsp_Free(built);
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_UNPLAYABLE;
    }

    /* H10 (ledger row 254): the attempted tunnel's own SEGMENT boxes, kept for
       the climb-place gate below and for the forgiveness an accepted tunnel
       leaves - never its union box, which spans rooms an L never enters */
    float dig_boxes[6u * MAPGEN_TXN_MAX_DIG_SEGS];
    uint32_t dig_segs = 0;
    if (step->edit.kind == MAPGEN_EDIT_DIG) {
        const mapgen_geometry_edit_t *de =
            MapGenGeometryEdit_At(txn->plan, step->edit.target);
        if (de)
            dig_segs = MapGenGeometryEdit_DigBoxes(txn->plan, de->target,
                                                   dig_boxes,
                                                   MAPGEN_TXN_MAX_DIG_SEGS);
    }

    /*
     * And a dig is a WAY on the file that was built: from its upper end through
     * its own box to its lower end, using nothing but the box and the ends'
     * neighbourhoods. See MAPGEN_TXN_REJECTED_DEAD_END for the tunnel the PO
     * walked into and had to walk back out of.
     */
    if (step->edit.kind == MAPGEN_EDIT_DIG) {
        const mapgen_geometry_edit_t *e =
            MapGenGeometryEdit_At(txn->plan, step->edit.target);
        mapgen_dig_report_t dig;
        float boxes[6u * MAPGEN_TXN_MAX_DIG_SEGS];
        mapgen_reach_way_t way;
        const uint32_t segs = e ? MapGenGeometryEdit_DigBoxes(
                                      txn->plan, e->target, boxes,
                                      MAPGEN_TXN_MAX_DIG_SEGS) : 0u;
        if (e && segs && MapGenGeometryEdit_DigAt(txn->plan, e->target, &dig)
            && !MapGenReach_WayThrough(reach, dig.from, dig.to, boxes, segs,
                                       MAPGEN_TXN_WAY_REACH, &way)) {
            snprintf(step->declined, sizeof(step->declined), "dead end: %s",
                     way.start == UINT32_MAX
                         ? "nobody can stand at its upper end"
                     : way.goal == UINT32_MAX
                         ? "nobody can stand at its lower end"
                     : !way.entered
                         ? "no way from the upper end into the passage"
                         : "no way from inside the passage to the lower end");
            MapGenReach_Free(reach);
            MapGenBsp_Free(built);
            MapGenGeometry_Free(candidate);
            return step->verdict = MAPGEN_TXN_REJECTED_DEAD_END;
        }
        /* row 412: and no hole in a wall high into the old map - the digwalls gate's rule, on this compile */
        if (e && segs && MapGenGeometryEdit_DigAt(txn->plan, e->target, &dig)) {
            float blo[3] = { 1e30f, 1e30f, 1e30f }, bhi[3] = { -1e30f, -1e30f, -1e30f };
            for (uint32_t s = 0; s < segs; s++)
                for (int a = 0; a < 3; a++) {
                    blo[a] = fminf(blo[a], boxes[6u * s + (uint32_t)a]);
                    bhi[a] = fmaxf(bhi[a], boxes[6u * s + 3u + (uint32_t)a]);
                }
            float said[6] = { 0, 0, 0, 0, 0, 0 };
            const uint32_t open = dig_opens_high(built, txn->accepted_map ? txn->accepted_map : txn->baseline_bsp,
                                                 blo, bhi, dig.from, dig.to, said);
            if (open) {
                snprintf(step->declined, sizeof(step->declined),
                         "open high: %u points, new %.0f %.0f %.0f open to old %.0f %.0f %.0f", (unsigned)open,
                         (double)said[0], (double)said[1], (double)said[2], (double)said[3], (double)said[4],
                         (double)said[5]);
                MapGenReach_Free(reach);
                MapGenBsp_Free(built);
                MapGenGeometry_Free(candidate);
                return step->verdict = MAPGEN_TXN_REJECTED_OPEN_HIGH;
            }
        }
    }

    /*
     * And nothing in plain sight that the compiled map's own visibility hides.
     *
     * MEASURED 2026-09-14 (ledger row 297): corridor 12's flood sealed its
     * geometry and drew every face, and the compiler's visibility then no longer
     * joined the curved stair under it to the step a player stands over; the
     * step was not drawn and the PO saw a hole out of the level on mg_20b, mg_20c
     * and mg_20d. The draft that added the flood already lost 722 such pairs,
     * and neither the parent nor an unrelated dig lost any. Eyes are this walk's
     * own reachable places near the edit, at view height; the parent's PVS says
     * what a loss is. The parent's own places were asked before the walk (row
     * 299); these are the places this attempt kept or made.
     */
    if (require_movement && txn->accepted_map && reach) {
        float vlo[3], vhi[3];
        if (MapGenGeometryEdit_BoxOf(txn->plan, NULL, NULL, step->edit.target,
                                     vlo, vhi)) {
            float witness[6];
            const uint32_t lost = hidden_from_walk(txn->accepted_map, built,
                                                   reach, vlo, vhi, witness);
            if (lost) {
                snprintf(step->declined, sizeof(step->declined),
                         "hidden: from %.0f %.0f %.0f, where this attempt's"
                         " walk stood, the drawn face at %.0f %.0f %.0f is in"
                         " plain sight and the map's own visibility no longer"
                         " shows it (%u pairs)",
                         (double)witness[0], (double)witness[1],
                         (double)witness[2], (double)witness[3],
                         (double)witness[4], (double)witness[5], lost);
                MapGenReach_Free(reach);
                MapGenBsp_Free(built);
                MapGenGeometry_Free(candidate);
                return step->verdict = MAPGEN_TXN_REJECTED_HIDDEN;
            }
        }
    }

    /*
     * And no crack the compiler left unstitched.
     *
     * The seam rule, asked of the artifact: a vertex of one drawn face lying
     * strictly inside another's edge. The donor's own compiled count is the
     * floor - q2dm1 has fourteen and they are its own lift's - and a pair
     * where the split edge is drawn only by LIQUID faces is not counted,
     * because two water surfaces are translucent and coincident and a vertex
     * in the middle of one changes nothing anybody can see.
     */
    {
        /* row 400: on the heap - four thousand of them do not belong on a stack */
        mapgen_bsp_seam_t *seam = calloc(MAPGEN_TXN_MAX_SEAMS, sizeof(*seam));
        uint32_t seams = 0;
        const clock_t seams_began = clock();
        const mapgen_bsp_seams_result_t rc =
            seam ? MapGenBsp_Seams(built, seam, MAPGEN_TXN_MAX_SEAMS, &seams) : MAPGEN_SEAMS_ERR_MEMORY;
        step->seams_ms = TXN_MS_SINCE(seams_began);
        step->tjunctions_after = seams;
        step->tjunctions_liquid = 0;
        step->tjunctions_cross_model = 0;
        step->tjunctions_skin = 0;

        /*
         * A measurement that could not run is not a map without cracks.
         *
         * The first version of this returned zero on an allocation failure
         * and the gate read that as a perfect candidate. An unmeasured
         * candidate is refused under its own name, exactly as an unmeasured
         * divergence is.
         */
        bool inherited_only = rc == MAPGEN_SEAMS_OK && txn->donor_seams_known;
        for (uint32_t s = 0; s < seams && s < MAPGEN_TXN_MAX_SEAMS
                             && inherited_only; s++) {
            /*
             * Liquid against liquid is not a crack anybody sees - two water
             * surfaces are drawn translucent and coincident - and it takes
             * BOTH sides to make that true. An opaque vertex splitting a
             * water edge is a vertex in a wall's neighbour and it counts.
             */
            if (!seam[s].opaque_edge && !seam[s].opaque_vertex) {
                step->tjunctions_liquid++;
                continue;
            }
            /*
             * And a seam BETWEEN TWO MODELS is not a crack the compiler could
             * have closed. FixTjuncs runs over the world and over each
             * submodel separately, on purpose: a door or a lift moves, and a
             * vertex welded across that boundary would tear the moment it
             * did. What holds such a contact honest is the mover's own gates
             * - travel, clearance, the rider's column - not this one.
             *
             * MEASURED: ALL FOURTEEN of q2dm1's own seams are of this kind,
             * its world faces against its two func_plats, and so are all
             * fourteen of every candidate measured so far. The world has none
             * against itself, and that is the number this gate is about.
             * Counting them cost the push-wall, both lifts and the
             * open-connector their acceptances an hour after the compiled
             * rule gave them back, on a seam that moved twelve units up one
             * of the lift's own edges because the tree was cut differently.
             */
            if (seam[s].edge_model != seam[s].vertex_model) {
                step->tjunctions_cross_model++;
                continue;
            }
            /*
             * Row 369: nor one inside a skinned dig's gap. The skin's band
             * carve exposes old faces there that face into the sealed gap;
             * round45's storey was refused for such a crack at 1568 1280 926,
             * where no player can stand or look.
             */
            if (g_txn_skin_gap_spared
                && MapGenGeometryEdit_InSkinGap(candidate, seam[s].split)) {
                step->tjunctions_skin++;
                continue;
            }
            /* row 382: the one question the seam probe asks too */
            if (MapGenTransaction_NewSeam(&seam[s], txn->donor_seam,
                                          txn->num_donor_seams)) {
                /* A NEW crack in something that is not going to move. The
                   candidate does not get to spend a seam it removed
                   somewhere else. */
                inherited_only = false;
                memcpy(step->new_seam, seam[s].split, sizeof(step->new_seam));
                /*
                 * And WHERE, for the same reason the buried place and the
                 * blocking machine say where.
                 *
                 * MEASURED 2026-09-13: the arena flood - the room the PO named,
                 * «главная арена например» - is refused `REJECTED_SURFACE` on
                 * four attempts across two fidelities, and the ledger line
                 * carries nothing but the verdict and the flood's own box, so
                 * nothing in a run says which crack it opened. The gate has
                 * known the split point all along and kept it to itself.
                 *
                 * Diagnostic only: it writes a string and changes no verdict.
                 */
                snprintf(step->declined, sizeof(step->declined),
                         "a new crack in the world at %.0f %.0f %.0f"
                         " (model %d, opaque edge %d, opaque vertex %d)",
                         (double)seam[s].split[0], (double)seam[s].split[1],
                         (double)seam[s].split[2], (int)seam[s].edge_model,
                         seam[s].opaque_edge ? 1 : 0,
                         seam[s].opaque_vertex ? 1 : 0);
            }
        }
        free(seam);
        if (!inherited_only) {
            MapGenReach_Free(reach);
            MapGenBsp_Free(built);
            MapGenGeometry_Free(candidate);
            return step->verdict = rc == MAPGEN_SEAMS_OK
                                 && txn->donor_seams_known
                                 ? MAPGEN_TXN_REJECTED_SURFACE
                                 : MAPGEN_TXN_REJECTED_UNMEASURED;
        }
    }

    /*
     * And nothing new seen through the sky (row 371, Fable's brief C6): asked
     * of every dig that wore a sky skin, so that no accepted map can show a
     * room's inside where the sky should be, whatever any edit did.
     */
    if (s_attempt_skinned && g_txn_sky_check) {
        float slo[3], shi[3], witness[6];
        if (MapGenGeometryEdit_BoxOf(txn->plan, NULL, NULL, step->edit.target, slo, shi)
            && MapGenTransaction_SeenThroughSky(built, txn->donor_bsp, slo, shi, witness)) {
            snprintf(step->declined, sizeof(step->declined),
                     "new space at %.0f %.0f %.0f seen through the sky from %.0f %.0f %.0f",
                     (double)witness[0], (double)witness[1], (double)witness[2],
                     (double)witness[3], (double)witness[4], (double)witness[5]);
            MapGenReach_Free(reach);
            MapGenBsp_Free(built);
            MapGenGeometry_Free(candidate);
            return step->verdict = MAPGEN_TXN_REJECTED_SKY;
        }
    }

    /*
     * Water lies in a basin, and a machine travels through air.
     *
     * Both are read off what the COMPILER produced rather than off the
     * geometry that asked for it, because both are properties of the faces
     * and the models it built. The donor's own numbers are the floor: a map
     * whose designer left a waterfall or a lift that grazes its shaft may be
     * forked, and an edit is held only to not adding to it.
     */
    const clock_t water_began = clock();
    const bool water_stands =
        MapGenBsp_StandingWater(built, NULL) > txn->donor_standing_water;
    step->water_ms = TXN_MS_SINCE(water_began);
    if (water_stands) {
        MapGenReach_Free(reach);
        MapGenBsp_Free(built);
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_STANDING_WATER;
    }
    /* Read once: the clearance gate below wants them, and so does the route
       gate, which has to know whether a staircase's replacement is there. */
    mapgen_movers_t *movers = calloc(1, sizeof(*movers));
    if (movers && !MapGenMovers_Read(built, movers)) {
        free(movers);
        movers = NULL;
    }
    {
        uint32_t travel = 0;
        if (movers) {
            MapGenMovers_MeasureClearance(movers, built);
            MapGenMovers_WorstClearance(movers, &travel, NULL);
        }
        if (travel > txn->donor_mover_travel) {
            /*
             * And WHICH machine, and by how much - the same duty the buried
             * route now carries.
             *
             * MEASURED 2026-09-13: the arena's flood was refused this way three
             * runs in a row, and «REJECTED_BLOCKED_MACHINE» plus a box was all
             * there was to go on. I read it as «the water is in a machine's
             * swept volume», added a rule to the flood family to keep its cells
             * out of one, watched the mask shrink from 55 cells to 50 - and the
             * verdict did not move, because this gate is not about overlap at
             * all: it compares the WORST clearance of every carrying machine
             * against the donor's worst. A day of that is what an unnamed
             * verdict costs.
             */
            uint32_t worst = 0;
            const mapgen_mover_t *blame = NULL;
            if (movers)
                for (uint32_t m = 0; m < movers->num_movers; m++) {
                    const mapgen_mover_t *mv = &movers->movers[m];
                    if (!mv->carries)
                        continue;
                    const uint32_t t = mv->travel_permille;
                    if (t >= worst) {
                        worst = t;
                        blame = mv;
                    }
                }
            if (blame)
                snprintf(step->declined, sizeof(step->declined),
                         "machine %s at %.0f %.0f %.0f loses room: travel"
                         " %u permille against the donor's worst %u",
                         MapGenMovers_KindName(blame->kind),
                         (double)(0.5f * (blame->mins[0] + blame->maxs[0])),
                         (double)(0.5f * (blame->mins[1] + blame->maxs[1])),
                         (double)(0.5f * (blame->mins[2] + blame->maxs[2])),
                         travel, txn->donor_mover_travel);
            else
                snprintf(step->declined, sizeof(step->declined),
                         "a machine loses room: travel %u permille against the"
                         " donor's worst %u", travel,
                         txn->donor_mover_travel);
            free(movers);
            MapGenReach_Free(reach);
            MapGenBsp_Free(built);
            MapGenGeometry_Free(candidate);
            return step->verdict = MAPGEN_TXN_REJECTED_BLOCKED_MACHINE;
        }
    }

    /*
     * And every way through the map is still a way.
     *
     * The reachability gate above asks whether the pickups can be reached,
     * and a map with two ways up passes it with one of them filled in - which
     * is how a stairwell with three blocks in it was handed to the PO.
     */
    /*
     * ... and a way REPLACED is not a way lost.
     *
     * The flight this edit turns into a machine, if it is one, plus every
     * flight an earlier accepted edit already did. Forgiveness is granted
     * inside those boxes and nowhere else, and only while the machine that
     * bought it is standing in the compiled candidate serving the heights the
     * steps served: this loop can then still refuse a block dropped on a
     * stair, which is the rule it was written for.
     */
    float pending_lo[3], pending_hi[3], pending_rise = 0.0f;
    const bool pending = require_movement
        && MapGenGeometryEdit_ReplacedFlight(txn->plan, txn->donor,
                                             step->edit.target, pending_lo,
                                             pending_hi, &pending_rise)
        && machine_serves(movers, pending_lo, pending_hi, pending_rise);

    /*
     * The flood being applied right now, and its own box.
     *
     * ASKED OF `BoxOf`, AND THE PREVIOUS VERSION OF THIS COMMENT WAS WRONG.
     *
     * It said `ConstructionOf` returns «what an edit BUILDS, which for a flood
     * is the hollow it filled - the same box the ledger prints». It does not.
     * Read to the end (`mapgen_geometry_edit.c:4376`), `ConstructionOf` answers
     * `RECUT_ROOM` and `ROOM_BLOCK` and returns FALSE for every other kind - so
     * for a flood `flooding` was always false, the whole branch below never ran,
     * and a climb place was never once compared with the water the flood had
     * just put under it.
     *
     * MEASURED 2026-09-13 on the delivery batch (ledger rows 136, 140, 141):
     * the room at `496 944 696 .. 1072 1680 768` was refused
     * `REJECTED_BURIED_ROUTE` «buried a climb place at 656 1152 768» on two
     * rounds, and both refused candidates were kept and probed at exactly that
     * x/y over exactly the window `under_our_liquid` samples: SOLID at z
     * 672..688, **WATER at z 696..752**, empty above. First liquid at dz -72,
     * well inside -96..+32. The answer was there and nobody asked.
     *
     * It is also why widening that window last round changed nothing, which I
     * recorded as a fix on the strength of probing the GEOMETRY by hand instead
     * of probing the GATE.
     *
     * `BoxOf` is the one function that answers «where is this edit» for every
     * family, and its flood case is the flood's own box - the same box the
     * ledger prints, which is the point: one box asked by both, the lesson the
     * pit family already paid for. NOT a flood case added to `ConstructionOf`,
     * because that same function gates `REJECTED_WORTHLESS` - «a place has to be
     * ON the thing that was built» - and places on filled water are not standing
     * places, so that would trade one refusal for another.
     */
    float flood_lo[3] = { 0.0f, 0.0f, 0.0f };
    float flood_hi[3] = { 0.0f, 0.0f, 0.0f };
    const bool flooding = require_movement
        && step->edit.kind == MAPGEN_EDIT_FLOOD
        && MapGenGeometryEdit_BoxOf(txn->plan,
                                    txn->accepted_map ? txn->accepted_map
                                                      : txn->donor_bsp,
                                    txn->donor, step->edit.target, flood_lo,
                                    flood_hi);
    /*
     * H8 (ledger rows 242-243): the flood's WHOLE footprint - its water and
     * its shell - answers «is this buried place one our flood answers for»,
     * here and in the forgiveness it leaves behind. D9's entrances keep the
     * water's box. MEASURED: the arena's lake answered 48 of 48 places under
     * its water and was refused for 1776 768 432, under its own ring.
     */
    float foot_lo[3] = { 0.0f, 0.0f, 0.0f };
    float foot_hi[3] = { 0.0f, 0.0f, 0.0f };
    if (flooding
        && !MapGenGeometryEdit_FloodFootprint(txn->plan, step->edit.target,
                                              foot_lo, foot_hi)) {
        memcpy(foot_lo, flood_lo, sizeof(foot_lo));
        memcpy(foot_hi, flood_hi, sizeof(foot_hi));
    }

    /*
     * The FIRST failure, recorded rather than returned.
     *
     * This loop used to return the moment it found an unreplaced place, so the
     * counters it fills described only the part of the map it had walked:
     * «flood places 11, replaced 11» meant «eleven of the eleven I reached»,
     * not «every obligation was replaced». Codex's second review of 2026-09-13
     * named it and it is ledger row 177. The walk is complete now; the message
     * belongs to the first failure; the verdict is formed after the loop.
     */
    int32_t first_fail = -1;

    /*
     * D9: WHAT A FLOOD PROVES BEFORE IT MAY RETIRE A WAY.
     *
     * `route_replaced` asks whether a reachable, returnable, non-lethal place
     * lies within 96 units of the lost one. That proves a nearby usable state
     * EXISTS; it does not prove a route across the water. Codex's second review
     * gave the counterexample: one safe point 32 units away behind a wall
     * satisfies it while the passage through the flooded room is walled
     * (ledger row 177).
     *
     * So the flood proves the thing itself. Its ENTRANCES are the baseline's
     * standing places inside the grown box that STILL stand in the compiled
     * candidate - a way into the room that survived the water, which needs no
     * new accessor to find: the water is where the places went. Every entrance
     * must reach the first one and come back, asked of the engine's own
     * movement through the flood's own box (`MapGenReach_WayThrough`, whose
     * `through` is set only on arriving PAST the box and which skips every
     * hazard state). Fewer than two entrances is a vacuous obligation and the
     * counters say so.
     *
     * And a HAZARD forgives nothing. Measured off the candidate rather than
     * read from the plan's intent: if the liquid at the box's own centre is
     * slime or lava, every baseline place must still stand or lie outside the
     * footprint. «Чтобы не сгореть» is about crates staying standing places.
     */
    bool flood_crossed = false;
    bool flood_hazard = false;
    float grown_box[6] = { 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f };
    const clock_t pairs_began = clock();
    const uint32_t parent_before_flood = step->parent_ms;
    if (flooding) {
        for (int a = 0; a < 3; a++) {
            grown_box[a] = flood_lo[a] - 24.0f;
            grown_box[3 + a] = flood_hi[a] + 24.0f;
        }
        const float mid[3] = {
            0.5f * (flood_lo[0] + flood_hi[0]),
            0.5f * (flood_lo[1] + flood_hi[1]),
            flood_hi[2] - 16.0f,
        };
        flood_hazard = (MapGenBsp_PointContents(built, mid)
                        & (MAPGEN_CONTENTS_LAVA | MAPGEN_CONTENTS_SLIME)) != 0;

        float ents[64][3];
        const uint32_t offered_ents =
            MapGenBsp_PlacesIn(txn->baseline_bsp, grown_box, grown_box + 3,
                               96.0f, ents, 64u);
        uint32_t kept = 0;
        for (uint32_t e = 0; e < offered_ents && e < 64u; e++)
            if (MapGenBsp_Stands(built, ents[e]))
                memcpy(ents[kept++], ents[e], sizeof(ents[0]));
        step->flood_entrances = kept;
        if (kept >= 2u) {
            uint32_t proved = 0, excused = 0;
            for (uint32_t e = 1; e < kept; e++) {
                mapgen_reach_way_t there, back;
                const bool c_there =
                    MapGenReach_WayThrough(reach, ents[e], ents[0], grown_box,
                                           1u, 96.0f, &there);
                const bool c_back =
                    MapGenReach_WayThrough(reach, ents[0], ents[e], grown_box,
                                           1u, 96.0f, &back);
                if (c_there && c_back) {
                    proved++;
                    continue;
                }
                /*
                 * H6 (ledger row 239), corrected by D15 (row 265): a direction
                 * the candidate lost is charged to the flood only if the
                 * PARENT walked it inside the same box. MEASURED on the arena:
                 * 23 of 62 pairs failed because a raised block crosses its
                 * box, water or not. With no parent walk the direction is
                 * charged, as before.
                 */
                const mapgen_reach_t *parent = parent_walk(txn, step);
                bool b_there = true, b_back = true;
                if (parent) {
                    mapgen_reach_way_t was_there, was_back;
                    b_there = MapGenReach_WayThrough(parent, ents[e], ents[0],
                                                     grown_box, 1u, 96.0f,
                                                     &was_there);
                    b_back = MapGenReach_WayThrough(parent, ents[0], ents[e],
                                                    grown_box, 1u, 96.0f,
                                                    &was_back);
                }
                if (mapgen_flood_pair_answered(c_there, b_there)
                    && mapgen_flood_pair_answered(c_back, b_back))
                    excused++;
            }
            step->flood_pairs_proved = proved;
            step->flood_pairs_excused = excused;
            flood_crossed = proved + excused + 1u == kept;
        } else {
            /* one way in, or none: nothing to cross, and the reach gate above
               has already judged the room as a whole */
            flood_crossed = true;
        }
        if (flood_hazard)
            flood_crossed = false;
    }

    /*
     * D16 (assignment 22, ledger row 265): a tunnel's MOUTH is proved like a
     * flood's box. H10 retired a place its mouth buried by `route_replaced`
     * alone - the test Codex refuted for floods (row 177): a corridor cut in
     * two by a mouth still passes the reach gate the long way round. So each
     * segment box of the attempted tunnel, grown by 24, gets D9's own proof:
     * the baseline's standing places inside it that still stand are entrances,
     * every pair walks both ways inside the box, and a direction the parent
     * does not walk either is excused. Measured first as counters on the
     * showcase's ten tunnels (assignment 22 S1, ledger row 269), then made the
     * refusal below - a gate that has never fired is not thereby wrong.
     */
    for (uint32_t s = 0; s < dig_segs; s++) {
        float gbox[6];
        for (int a = 0; a < 3; a++) {
            gbox[a] = dig_boxes[6u * s + (uint32_t)a] - 24.0f;
            gbox[3 + a] = dig_boxes[6u * s + 3u + (uint32_t)a] + 24.0f;
        }
        float mouth[64][3];
        const uint32_t offered_mouth =
            MapGenBsp_PlacesIn(txn->baseline_bsp, gbox, gbox + 3, 96.0f,
                               mouth, 64u);
        uint32_t held = 0;
        for (uint32_t e = 0; e < offered_mouth && e < 64u; e++)
            if (MapGenBsp_Stands(built, mouth[e]))
                memcpy(mouth[held++], mouth[e], sizeof(mouth[0]));
        step->dig_entrances += held;
        for (uint32_t e = 1; e < held; e++) {
            mapgen_reach_way_t there, back;
            const bool c_there = MapGenReach_WayThrough(
                reach, mouth[e], mouth[0], gbox, 1u, 96.0f, &there);
            const bool c_back = MapGenReach_WayThrough(
                reach, mouth[0], mouth[e], gbox, 1u, 96.0f, &back);
            if (c_there && c_back) {
                step->dig_pairs_proved++;
                continue;
            }
            const mapgen_reach_t *parent = parent_walk(txn, step);
            bool b_there = true, b_back = true;
            if (parent) {
                mapgen_reach_way_t was_there, was_back;
                b_there = MapGenReach_WayThrough(parent, mouth[e], mouth[0],
                                                 gbox, 1u, 96.0f, &was_there);
                b_back = MapGenReach_WayThrough(parent, mouth[0], mouth[e],
                                                gbox, 1u, 96.0f, &was_back);
            }
            if (mapgen_flood_pair_answered(c_there, b_there)
                && mapgen_flood_pair_answered(c_back, b_back)) {
                step->dig_pairs_excused++;
                continue;
            }
            if (!step->dig_pairs_lost) {
                memcpy(step->dig_lost_from, mouth[e], sizeof(mouth[0]));
                memcpy(step->dig_lost_to, mouth[0], sizeof(mouth[0]));
            }
            step->dig_pairs_lost++;
        }
    }
    step->pairs_ms += TXN_MS_SINCE(pairs_began)
                    - (step->parent_ms - parent_before_flood);

    /*
     * D16, the refusal: a pair of a mouth's entrances that the parent joined
     * inside the segment's box and the candidate does not is a way the mouth
     * cut. No nearby place answers for it - that was H10's mistake - so the
     * tunnel is refused, naming the two places.
     */
    if (step->dig_pairs_lost) {
        snprintf(step->declined, sizeof(step->declined),
                 "the tunnel's mouth separates %.0f %.0f %.0f from %.0f %.0f"
                 " %.0f (%u pairs lost)",
                 (double)step->dig_lost_from[0], (double)step->dig_lost_from[1],
                 (double)step->dig_lost_from[2], (double)step->dig_lost_to[0],
                 (double)step->dig_lost_to[1], (double)step->dig_lost_to[2],
                 step->dig_pairs_lost);
        free(movers);
        MapGenReach_Free(reach);
        MapGenBsp_Free(built);
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_BURIED_ROUTE;
    }

    for (uint32_t c = 0; c < txn->num_climbs; c++) {
        if (MapGenBsp_Stands(built, txn->climb[c]))
            continue;
        bool replaced = pending && point_in(txn->climb[c], pending_lo,
                                            pending_hi);
        /* whether this place is one OUR flood is answerable for, so a refusal
           can say which question failed rather than only that one did */
        bool in_our_flood = false;
        /*
         * The box is grown by a step before the place is tested against it.
         *
         * A climb place is recorded on the floor the hollow REPLACED, so it
         * sits exactly on the box's top: room 4's place at 656 1152 768 against
         * a box of `496 944 696 .. 1072 1680 768`. `point_in` is an inclusive
         * compare on floats and a place on the boundary is one rounding away
         * from being outside, so a step of tolerance is what the geometry
         * means.
         *
         * That tolerance is NOT why the room was refused, and the previous
         * version of this comment said it was. The refusal survived it because
         * `flooding` above was false for every flood there has ever been; see
         * the note there. Keeping the tolerance because the boundary case is
         * real, not because it was the bug.
         */
        if (!replaced && flooding) {
            float grown_lo[3], grown_hi[3];
            for (int a = 0; a < 3; a++) {
                grown_lo[a] = foot_lo[a] - 24.0f;
                grown_hi[a] = foot_hi[a] + 24.0f;
            }
            if (point_in(txn->climb[c], grown_lo, grown_hi)) {
                in_our_flood = true;
                step->flood_places++;
                /*
                 * The proof is the room's, not the place's: the way across was
                 * established once, above, and a place inside the footprint is
                 * retired by it. `route_replaced` is kept as the attachment
                 * question - is there anything usable near this place at all -
                 * because a place with the room crossed and nothing whatever
                 * beside it is worth refusing.
                 */
                replaced = flood_crossed
                        && route_replaced(reach, txn->climb[c]);
                if (replaced)
                    step->flood_replaced++;
            }
        }
        /*
         * H10 (ledger rows 253-254): a place inside the attempted tunnel's own
         * segment boxes, grown by 24, is the tunnel's to answer. Its way is
         * already proved - an attempt whose tunnel is not a way ended at
         * DEAD_END above - and the place is retired when one a player can reach
         * and return from lies within 96 units: the question a flood asks.
         * MEASURED: six of the showcase's seven refused tunnels buried a place
         * inside their own box, where their own mouth cut the floor.
         */
        for (uint32_t s = 0; s < dig_segs && !replaced; s++) {
            float glo[3], ghi[3];
            for (int a = 0; a < 3; a++) {
                glo[a] = dig_boxes[6u * s + (uint32_t)a] - 24.0f;
                ghi[a] = dig_boxes[6u * s + 3u + (uint32_t)a] + 24.0f;
            }
            if (point_in(txn->climb[c], glo, ghi))
                replaced = route_replaced(reach, txn->climb[c]);
        }
        for (uint32_t f = 0; f < txn->num_forgiven && !replaced; f++) {
            if (!point_in(txn->climb[c], txn->forgiven[f].lo,
                          txn->forgiven[f].hi))
                continue;
            /*
             * Re-proved on every attempt, and by its own kind: a machine's box
             * needs a machine still standing there, a flood's box needs the
             * water still there. An edit that took either away would otherwise
             * inherit the forgiveness for something it no longer has.
             */
            if (txn->forgiven[f].liquid)
                in_our_flood = true;
            replaced = txn->forgiven[f].liquid
                ? route_replaced(reach, txn->climb[c])
                : machine_serves(movers, txn->forgiven[f].lo,
                                 txn->forgiven[f].hi,
                                 txn->forgiven[f].rise);
        }
        if (replaced)
            continue;
        /* The counters keep walking; only the FIRST failure gets the message
           and the recorded index (see `first_fail` above). */
        if (first_fail >= 0)
            continue;
        /*
         * And WHERE, because a verdict that names no place cannot be acted on.
         *
         * MEASURED twice in two days at my own cost: the pit that stood in a
         * lift's deck took a full diagnosis to locate because the gate said
         * only «lift deck sunk into the floor», and the flood of room 4 was
         * refused «buried route» three times in a row with nothing but its box
         * to go on. The ledger already carries `declined` for the operator's
         * own reasons; a gate that refuses has the same duty.
         */
        /*
         * And WHICH QUESTION failed, not only where.
         *
         * A place inside our own flood's footprint and a place nowhere near it
         * are two different refusals with two different fixes, and the line they
         * used to share said nothing about which one this was. Assignment 18's
         * S1 measurement asks for exactly this: «for each the compiled
         * traversal proof or its named absence».
         */
        if (in_our_flood)
            snprintf(step->declined, sizeof(step->declined),
                     "buried a climb place at %.0f %.0f %.0f: inside our"
                     " flood, and no place a player can reach AND return from"
                     " within %.0f units of it",
                     (double)txn->climb[c][0], (double)txn->climb[c][1],
                     (double)txn->climb[c][2],
                     (double)MAPGEN_TXN_FLOOD_REACH);
        else
            snprintf(step->declined, sizeof(step->declined),
                     "buried a climb place at %.0f %.0f %.0f",
                     (double)txn->climb[c][0], (double)txn->climb[c][1],
                     (double)txn->climb[c][2]);
        first_fail = (int32_t)c;
    }

    if (first_fail >= 0) {
        free(movers);
        MapGenReach_Free(reach);
        MapGenBsp_Free(built);
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_BURIED_ROUTE;
    }
    free(movers);
    movers = NULL;

    /*
     * And a construction is worth building.
     *
     * Asked of the two families that add architecture, on the compiled
     * candidate, from the explorer that decides what a player can do: the
     * component the spawns are in has to be BIGGER than it was, and at least
     * one of the places in it has to be on the thing that was built. See
     * MAPGEN_TXN_REJECTED_WORTHLESS for what the PO walked when nothing asked.
     */
    if (require_movement) {
        float clo[3], chi[3];
        if (MapGenGeometryEdit_ConstructionOf(txn->plan,
                                              txn->accepted_map
                                                  ? txn->accepted_map
                                                  : txn->donor_bsp,
                                              step->edit.target, clo, chi)) {
            /*
             * What the map the fork STARTED from was worth, taken once.
             *
             * `accepted_component` is filled in when something is accepted,
             * and the schedule is structural-first: a construction attempted
             * before anything has been accepted would be compared against
             * zero, which every map beats. That is precisely the first
             * construction of every run - and one construction that adds
             * places on itself and takes more away from the room around it is
             * the whole of what the PO refused.
             *
             * Explored lazily rather than at open, so a run that never offers
             * a construction never pays for it.
             */
            if (!txn->accepted_component && txn->baseline_bsp) {
                /* D19: the baseline's one walk of the run */
                const mapgen_reach_t *was = baseline_walk(txn, step);
                if (was)
                    txn->accepted_component =
                        MapGenReach_Report(was)->component;
            }

            uint32_t on_it = 0;
            const uint32_t states = MapGenReach_NumStates(reach);
            for (uint32_t s = 0; s < states; s++) {
                const mapgen_reach_state_t *st = MapGenReach_State(reach, s);
                /* Standing ON it: inside its footprint and higher than the
                   ground it stands on, which is what tells a place on the
                   platform from a place on the floor beside it. */
                if (st && st->reachable && st->can_return && !st->hazard
                    && st->origin[0] >= clo[0] && st->origin[0] <= chi[0]
                    && st->origin[1] >= clo[1] && st->origin[1] <= chi[1]
                    && st->origin[2] >= clo[2] + 24.0f)
                    on_it++;
            }
            step->places_on_construction = on_it;
            if (!on_it || reach_report.component <= txn->accepted_component) {
                MapGenReach_Free(reach);
                MapGenBsp_Free(built);
                MapGenGeometry_Free(candidate);
                return step->verdict = MAPGEN_TXN_REJECTED_WORTHLESS;
            }
        }
    }

    /* --- 5: what it cost, and what it was worth ------------------------- */

    mapgen_divergence_t divergence;
    memset(&divergence, 0, sizeof(divergence));
    /* Against the baseline, not against the file the donor arrived in: what
       this number answers is how much the EDITS changed.

       Routes off: this is the SCALAR PROGRESS the schedule steers by, taken
       once per attempt, and a reachability exploration of both maps every time
       would price the schedule out. What it may not do is decide, on its own,
       that an edit did nothing - that is edit_effect() below. */
    const clock_t divergence_began = clock();
    const bool measured =
        MapGenDivergence_Measure(txn->baseline_bsp, built, 100, false,
                                 &divergence) == MAPGEN_DIVERGENCE_OK;
    step->divergence_ms = TXN_MS_SINCE(divergence_began);
    step->brushes_after = MapGenGeometry_NumBrushes(candidate);

    if (!measured) {
        /* An unmeasured edit is an edit nobody can price. It is refused
           rather than kept on the assumption that it was harmless - and
           refused under its own name, because "nobody measured it" is not
           the finding "it changed nothing". */
        MapGenReach_Free(reach);
        MapGenBsp_Free(built);
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_UNMEASURED;
    }

    step->divergence_after = divergence.aggregate_permille;
    step->divergence_delta = (int32_t)divergence.aggregate_permille
                           - (int32_t)txn->accepted_divergence;

    /*
     * Past what it was aiming at.
     *
     * Discarded like any other refusal, so the schedule can try the next edit
     * instead of arriving at the end one permille outside the band with every
     * compile already spent.
     */
    if (require_movement && txn->has_band
        && divergence.aggregate_permille
           > txn->band_target + txn->band_tolerance) {
        MapGenReach_Free(reach);
        MapGenBsp_Free(built);
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_OVERSHOT;
    }

    if (require_movement && step->divergence_delta == 0) {
        /*
         * The score did not move. That is a question, not an answer.
         *
         * It compiled and it is playable, and the cheap route-free aggregate
         * came out where it already was - which is true of an edit that did
         * nothing AND of five other things, one of them a route change this
         * measurement never looked at. So the verdict comes from evidence
         * that can tell them apart, and an edit that really did move the map
         * is kept even though it bought no scalar progress.
         */
        const clock_t effect_began = clock();
        const uint32_t parent_before_effect = step->parent_ms;
        const edit_effect_t effect =
            edit_effect(txn, candidate, built, reach, compiled.bsp_sha256,
                        step);
        step->divergence_ms += TXN_MS_SINCE(effect_began)
                             - (step->parent_ms - parent_before_effect);
        if (effect != EDIT_MOVED) {
            MapGenReach_Free(reach);
            MapGenBsp_Free(built);
            MapGenGeometry_Free(candidate);
            return step->verdict = effect == EDIT_NOTHING
                                 ? MAPGEN_TXN_REJECTED_NO_EFFECT
                                 : MAPGEN_TXN_REJECTED_UNMEASURED;
        }
    }

    MapGenBsp_Free(built);
    /* `reach` is kept: on acceptance it becomes the parent's walk (D19) */

    /* --- 6: retained, atomically ---------------------------------------- */

    MapGenGeometry_Free(txn->accepted);
    txn->accepted = candidate;
    txn->accepted_divergence = divergence.aggregate_permille;
    /* Not recomputed: this is the count taken of this very geometry on the way
       in, and an accepted candidate is exactly what was judged. */
    txn->accepted_faults = step->faults_after;
    txn->accepted_reach = reach_report;
    txn->accepted_component = reach_report.component;
    if (pending && txn->num_forgiven < MAPGEN_TXN_MAX_FORGIVEN) {
        memcpy(txn->forgiven[txn->num_forgiven].lo, pending_lo,
               sizeof(pending_lo));
        memcpy(txn->forgiven[txn->num_forgiven].hi, pending_hi,
               sizeof(pending_hi));
        txn->forgiven[txn->num_forgiven].liquid = false;
        txn->forgiven[txn->num_forgiven++].rise = pending_rise;
    }
    /*
     * and an accepted FLOOD's box - THE SAME BOX THE IMMEDIATE TEST USED.
     *
     * It used to record the ungrown box while the test above grew it by 24, so a
     * place up to 24 units outside the flood's own boundary was forgiven on the
     * attempt that created the flood and refused on the next unrelated edit,
     * with the water unchanged. Codex §C2 found it in the control flow; ledger
     * row 152. One footprint, asked twice.
     */
    if (flooding && txn->num_forgiven < MAPGEN_TXN_MAX_FORGIVEN) {
        for (int a = 0; a < 3; a++) {
            txn->forgiven[txn->num_forgiven].lo[a] = foot_lo[a] - 24.0f;
            txn->forgiven[txn->num_forgiven].hi[a] = foot_hi[a] + 24.0f;
        }
        txn->forgiven[txn->num_forgiven].rise = 0.0f;
        txn->forgiven[txn->num_forgiven++].liquid = true;
    }
    /* H10: an accepted tunnel leaves its segment boxes, re-proved on every
       later attempt by the same `route_replaced` question - which is what
       `liquid` selects in the re-proof, a flood's question and a tunnel's */
    for (uint32_t s = 0;
         s < dig_segs && txn->num_forgiven < MAPGEN_TXN_MAX_FORGIVEN; s++) {
        for (int a = 0; a < 3; a++) {
            txn->forgiven[txn->num_forgiven].lo[a] =
                dig_boxes[6u * s + (uint32_t)a] - 24.0f;
            txn->forgiven[txn->num_forgiven].hi[a] =
                dig_boxes[6u * s + 3u + (uint32_t)a] + 24.0f;
        }
        txn->forgiven[txn->num_forgiven].rise = 0.0f;
        txn->forgiven[txn->num_forgiven++].liquid = true;
    }
    snprintf(txn->accepted_bsp, sizeof(txn->accepted_bsp), "%s",
             compiled.bsp_path);
    checkpoint(txn, attempt, compiled.bsp_path);      /* row 411: once, to the disk, when the caller wants it */
    /*
     * And the operators measure against it from here on.
     *
     * A plan is dealt once and applied many times; until 2026-09-08 every
     * check an operator made read the DONOR's map, so the second round's
     * block saw the same empty stairwell the first one had filled.
     */
    {
        const clock_t accept_began = clock();
        mapgen_bsp_t *fresh = load_bsp(compiled.bsp_path);
        if (fresh) {
            MapGenBsp_Free(txn->accepted_map);
            txn->accepted_map = fresh;
            MapGenGeometryEdit_SetGround(txn->plan, txn->accepted_map);
            /*
             * D19 (assignment 23): the parent changed, and the walk this
             * candidate was judged on IS the walk of the map just loaded -
             * the same compiled file at the same budget - so it is handed over
             * instead of being taken again by the next attempt.
             */
            MapGenReach_Free(txn->parent_reach);
            txn->parent_reach = reach;
            txn->parent_reach_tried = true;
            txn->parent_is_baseline = false;
            reach = NULL;
        }
        step->accept_ms = TXN_MS_SINCE(accept_began);
    }
    MapGenReach_Free(reach);
    /* Its hash travels with its path: the next edit's identity bound is only
       sound if it is the hash of the map that edit was applied to. */
    snprintf(txn->accepted_sha256, sizeof(txn->accepted_sha256), "%s",
             compiled.bsp_sha256);
    /* Materialising is not an acceptance: nothing was applied, so nothing was
       accepted, and a caller counting accepted edits must not see one. */
    if (require_movement)
        txn->accepted_count++;

    return step->verdict = MAPGEN_TXN_ACCEPTED;
}

/*
 * Is there a machine standing here that serves these two heights?
 *
 * What makes a lift a REPLACEMENT rather than a demolition. Read from the
 * compiled candidate, because a way through a map is a property of the map
 * and not of the plan that asked for it: the deck has to be inside the box
 * the steps occupied, it has to carry whoever stands on it, something in the
 * map has to be able to work it, and its stops have to be at least as far
 * apart as the flight was tall, less one step - a machine that rises half way
 * up a staircase leaves the top of it as unreachable as a wall would.
 */
static bool machine_serves(const mapgen_movers_t *movers, const float lo[3],
                           const float hi[3], float rise)
{
    if (!movers)
        return false;
    for (uint32_t m = 0; m < movers->num_movers; m++) {
        const mapgen_mover_t *mv = &movers->movers[m];
        if (!mv->carries || mv->inoperable || mv->obstructed)
            continue;
        const float mid[3] = { 0.5f * (mv->mins[0] + mv->maxs[0]),
                               0.5f * (mv->mins[1] + mv->maxs[1]),
                               0.5f * (mv->mins[2] + mv->maxs[2]) };
        if (mid[0] < lo[0] || mid[0] > hi[0]
            || mid[1] < lo[1] || mid[1] > hi[1]
            || mid[2] < lo[2] || mid[2] > hi[2])
            continue;
        float low = 0.0f, high = 0.0f;
        for (uint32_t s = 0; s < mv->num_stops; s++) {
            if (mv->stop[s][2] < low)
                low = mv->stop[s][2];
            if (mv->stop[s][2] > high)
                high = mv->stop[s][2];
        }
        if (high - low + 32.0f >= rise)
            return true;
    }
    return false;
}

/*
 * Is this place under a liquid now, on the map that was built?
 *
 * Asked of the COMPILED candidate, like every other question here: a place is
 * forgiven because the player can swim where he used to walk, and that is a
 * property of the file rather than of the plan that asked for it. The column is
 * sampled from sixteen below the place to thirty-two above it, because the
 * liquid's surface stands `SUNK_LINE_DROP` under the floor it replaced and a
 * standing place is where the feet are.
 */
/*
 * Is there a way here in the COMPILED candidate - not a liquid sample?
 *
 * What this replaced, and why, ledger row 152. `under_our_liquid` asked one
 * question on one vertical line: does any of water, slime or lava appear
 * between 96 below the place and 32 above it. That proves a liquid exists at a
 * sampled point. It does not prove a route: not that a player can get there,
 * not that he can get back, not that the liquid is survivable, not that it is
 * ours. Codex's review of 2026-09-13 (§C2) names the same weakness, and Fable's
 * assignment 18 decision D4 settles what to ask instead: «inside the footprint
 * an old standing place may be retired only by compiled traversal evidence of
 * the intended way across».
 *
 * That evidence is already computed in `judge` before this is called: the reach
 * walk is the engine's own movement over the compiled candidate, and every
 * resting place it found carries whether a player can GET there, whether he can
 * get BACK, and whether standing there kills him. So a lost climb place is
 * replaced when one of those places is within reach of it and is none of those
 * three things a trap.
 *
 * Hazards therefore cannot forgive anything, which is D4's rule without a
 * second predicate: a lava or slime rest is `hazard` and disqualified here. And
 * a retained ledge, crate or platform inside the flood qualifies exactly as
 * swimming does, because the walk does not care which one it stood on - which is
 * the PO's "нужно пробираться по имеющимся ящикам" in the form of a gate.
 */
static bool route_replaced(const mapgen_reach_t *reach, const float p[3])
{
    if (!reach)
        return false;
    const uint32_t n = MapGenReach_NumStates(reach);
    for (uint32_t i = 0; i < n; i++) {
        const mapgen_reach_state_t *s = MapGenReach_State(reach, i);
        if (!s || !s->reachable || !s->can_return || s->hazard)
            continue;
        const float dx = s->origin[0] - p[0];
        const float dy = s->origin[1] - p[1];
        const float dz = s->origin[2] - p[2];
        if (dx * dx + dy * dy + dz * dz
            <= MAPGEN_TXN_FLOOD_REACH * MAPGEN_TXN_FLOOD_REACH)
            return true;
    }
    return false;
}

/* Is this place inside a box? */
static bool point_in(const float p[3], const float lo[3], const float hi[3])
{
    return p[0] >= lo[0] && p[0] <= hi[0]
        && p[1] >= lo[1] && p[1] <= hi[1]
        && p[2] >= lo[2] && p[2] <= hi[2];
}

/*
 * Attempt one edit and WRITE IT DOWN, whatever happened.
 *
 * A ledger of successes cannot answer the question this mechanism exists for -
 * where did the budget go - because the interesting lines are the refusals:
 * the operator that declined, the edit that compiled and moved nothing, the one
 * that opened the map.
 */
mapgen_transaction_verdict_t
MapGenTransaction_Try(mapgen_transaction_t *txn, const mapgen_typed_edit_t *edit,
                      mapgen_transaction_step_t *step)
{
    mapgen_transaction_step_t local;
    if (!step)
        step = &local;
    memset(step, 0, sizeof(*step));
    if (!txn || !edit)
        return step->verdict = MAPGEN_TXN_REJECTED_NOT_APPLIED;

    step->divergence_after = txn->accepted_divergence;

    /* What the header promises, checked rather than trusted. */
    const uint64_t before = MapGenGeometry_CanonicalDigest(txn->accepted);
    const clock_t total_began = clock();
    const uint64_t total_cpu_began = Q2PROX_Cpu_ProcessMs();
    const mapgen_transaction_verdict_t verdict = try_one(txn, edit, step);
    step->total_ms = TXN_MS_SINCE(total_began);
    step->total_cpu_ms = TXN_CPU_SINCE(total_cpu_began);
    if (verdict != MAPGEN_TXN_ACCEPTED
        && MapGenGeometry_CanonicalDigest(txn->accepted) != before)
        txn->violations++;

    if (txn->num_steps < MAX_STEPS)
        txn->steps[txn->num_steps++] = *step;
    return verdict;
}

/* ---- what it knows ------------------------------------------------------------- */

/*
 * Deal the schedule again, from what the transaction knows NOW.
 *
 * Three things the planner needs arrive after the first deal: the baseline it
 * will be judged against, the ambition that says how wide to search, and - on
 * a second pass - the accepted geometry. Each of them used to be handed to the
 * finished plan, which is too late: a planner that has already thrown away
 * every place the donor's own file refused cannot be told to reconsider.
 *
 * `from_accepted` is the difference between the two callers. A re-deal caused
 * by a planning input plans the DONOR again with better information; a re-deal
 * asked for by `Redeal` plans the ACCEPTED map, because what changed is the
 * map itself and the operators are being asked a different question.
 */
static mapgen_transaction_result_t redeal(mapgen_transaction_t *txn,
                                          bool from_accepted)
{
    if (!txn)
        return MAPGEN_TXN_ERR_ARGS;
    const mapgen_geometry_t *others[MAPGEN_TXN_MAX_OTHER_DONORS];
    const mapgen_bsp_t *other_bsps[MAPGEN_TXN_MAX_OTHER_DONORS];
    const char *names[MAPGEN_TXN_MAX_OTHER_DONORS];
    for (uint32_t i = 0; i < txn->num_others; i++) {
        others[i] = txn->other[i];
        other_bsps[i] = txn->other_bsp[i];
        names[i] = txn->other_name[i];
    }
    mapgen_geometry_edit_plan_t *fresh = NULL;
    /*
     * D27 (assignment 24, ledger row 286): a re-deal of the ACCEPTED map is
     * the same run asked again, and the pools the plan it replaces offered -
     * and the plans before that one - are not offered twice. A re-deal of the
     * DONOR comes before any attempt and is the first deal done better, so it
     * starts fresh.
     */
    if (MapGenGeometryEdit_PlanAfter(from_accepted ? txn->plan : NULL,
                                     from_accepted ? txn->accepted : txn->donor,
                                     txn->donor_bsp, txn->accepted_map,
                                     txn->ambition, txn->seed,
                                     txn->num_others ? others : NULL,
                                     txn->num_others ? other_bsps : NULL,
                                     txn->num_others ? names : NULL,
                                     txn->num_others, &fresh)
        != MAPGEN_GEOMETRY_OK)
        return MAPGEN_TXN_ERR_MEMORY;
    MapGenGeometryEdit_Free(txn->plan);
    txn->plan = fresh;
    MapGenGeometryEdit_SetGround(txn->plan, txn->accepted_map);
    MapGenGeometryEdit_SetAmbition(txn->plan, txn->ambition);
    return MAPGEN_TXN_OK;
}

mapgen_transaction_result_t MapGenTransaction_Redeal(mapgen_transaction_t *txn,
                                                     uint64_t seed)
{
    if (!txn)
        return MAPGEN_TXN_ERR_ARGS;
    txn->seed = seed;
    /*
     * Planned against the ACCEPTED geometry, not against the donor.
     *
     * A second pass over the donor's own rooms would offer the same edits and
     * they would be refused for the same reasons. What has changed is the
     * map: a wall that moved has rock behind it now, a room that was recut
     * has a different middle, and the operators that declined the first time
     * are being asked a different question.
     */
    return redeal(txn, true);
}

void MapGenTransaction_SetAmbition(mapgen_transaction_t *txn, int32_t ambition)
{
    if (!txn)
        return;
    if (txn->ambition == ambition) {
        MapGenGeometryEdit_SetAmbition(txn->plan, ambition);
        return;
    }
    txn->ambition = ambition;
    /*
     * And the schedule is DEALT AGAIN, because this is a planning input.
     *
     * The pipeline calls this after `Begin` has returned, so until now the
     * planners read an ambition of zero and every fidelity searched as narrowly
     * as ninety. MEASURED 2026-09-09: F90 and F75 reached the same divergence
     * on two seeds of three and F75 reached less on the third. A re-deal that
     * fails leaves the plan that exists rather than leaving none.
     */
    (void)redeal(txn, false);
}

const mapgen_geometry_edit_plan_t *
MapGenTransaction_Plan(const mapgen_transaction_t *txn)
{
    return txn ? txn->plan : NULL;
}

uint32_t MapGenTransaction_Divergence(const mapgen_transaction_t *txn)
{
    return txn ? txn->accepted_divergence : 0;
}

uint32_t MapGenTransaction_Accepted(const mapgen_transaction_t *txn)
{
    return txn ? txn->accepted_count : 0;
}

const char *MapGenTransaction_BaselineBsp(const mapgen_transaction_t *txn)
{
    return txn ? txn->baseline_path : "";
}

const char *MapGenTransaction_BaselineSha256(const mapgen_transaction_t *txn)
{
    return txn ? txn->baseline_sha256 : "";
}

uint32_t MapGenTransaction_DonorFaults(const mapgen_transaction_t *txn)
{
    return txn ? txn->donor_faults : 0;
}

uint32_t MapGenTransaction_Attempted(const mapgen_transaction_t *txn)
{
    return txn ? txn->attempted : 0;
}

const char *MapGenTransaction_AcceptedBsp(const mapgen_transaction_t *txn)
{
    return txn ? txn->accepted_bsp : NULL;
}

const mapgen_reach_report_t *
MapGenTransaction_Reach(const mapgen_transaction_t *txn)
{
    return txn ? &txn->accepted_reach : NULL;
}

mapgen_reach_t *MapGenTransaction_TakeBaselineWalk(mapgen_transaction_t *txn)
{
    if (!txn)
        return NULL;
    mapgen_reach_t *walk = txn->baseline_reach;
    txn->baseline_reach = NULL;
    return walk;
}

uint64_t MapGenTransaction_AcceptedDigest(const mapgen_transaction_t *txn)
{
    return txn ? MapGenGeometry_CanonicalDigest(txn->accepted) : 0;
}

uint32_t MapGenTransaction_Violations(const mapgen_transaction_t *txn)
{
    return txn ? txn->violations : 0;
}

uint32_t MapGenTransaction_Steps(const mapgen_transaction_t *txn)
{
    return txn ? txn->num_steps : 0;
}

const mapgen_transaction_step_t *
MapGenTransaction_Step(const mapgen_transaction_t *txn, uint32_t i)
{
    return txn && i < txn->num_steps ? &txn->steps[i] : NULL;
}

bool MapGenTransaction_Equivalence(const mapgen_transaction_t *txn,
                                   mapgen_equiv_report_t *out)
{
    if (!txn || !out)
        return false;
    *out = txn->equivalence;
    return true;
}

/* ---- resume helpers (row 395) ------------------------------------------------------------------------------------ */

/*
 * Row 410: the guards' replays of jobs made before brief 6 (row 408) lit a dig's rooms otherwise - only the point
 * lights' entities differ, every brush the same (mg_20u's attempt 12: 75 lines, all of light entities). Set by the
 * pipeline driver's `--replay-any-lights`, which only the donors guard passes; a real resume stays byte for byte.
 */
static bool g_replay_any_lights;

void MapGenTransaction_SetReplayAnyLights(bool any)
{
    g_replay_any_lights = any;
}

/* The file without its top-level point-light entities (a "light" with no brush), NUL-terminated; NULL on failure. */
static char *map_without_lights(const char *path, size_t *len)
{
    uint8_t *raw = NULL;
    size_t size = 0;
    if (!MapGenFs_Read(path, &raw, &size))      /* row 411: a file or a section */
        return NULL;
    char *in = (char *)raw;
    const long n = (long)size;
    char *out = malloc(size + 1);
    if (!out) {
        free(in);
        return NULL;
    }
    in[n] = '\0';
    size_t o = 0;
    long i = 0;
    while (i < n) {
        if (in[i] != '{') {
            out[o++] = in[i++];
            continue;
        }
        /* one entity: to its closing brace at depth 0, quoted text skipped */
        long j = i, depth = 0;
        bool brush = false, quoted = false;
        for (; j < n; j++) {
            if (in[j] == '"')
                quoted = !quoted;
            else if (!quoted && in[j] == '{') {
                if (++depth > 1)
                    brush = true;
            } else if (!quoted && in[j] == '}' && --depth == 0)
                break;
        }
        const long end = j < n ? j + 1 : n;
        const char saved = in[end - 1];
        in[end - 1] = '\0';
        const bool light = !brush && strstr(in + i, "\"classname\" \"light\"") != NULL;
        in[end - 1] = saved;
        if (!light) {
            memcpy(out + o, in + i, (size_t)(end - i));
            o += (size_t)(end - i);
        }
        i = light && end < n && in[end] == '\n' ? end + 1 : end;
    }
    out[o] = '\0';
    free(in);
    *len = o;
    return out;
}

static bool maps_equal_but_lights(const char *a, const char *b)
{
    size_t na = 0, nb = 0;
    char *ta = map_without_lights(a, &na), *tb = map_without_lights(b, &nb);
    const bool same = ta && tb && na == nb && !memcmp(ta, tb, na);
    free(ta);
    free(tb);
    return same;
}

static bool files_equal(const char *a, const char *b)
{
    uint8_t *da = NULL, *db = NULL;      /* row 411: files or sections, either side */
    size_t na = 0, nb = 0;
    const bool same = MapGenFs_Read(a, &da, &na) && MapGenFs_Read(b, &db, &nb) && na == nb && !memcmp(da, db, na);
    free(da);
    free(db);
    return same;
}

/* The file's SHA-256 as lowercase hex, what the compile adapter reports for an artifact; "" when unreadable. */
static void file_sha256_hex(const char *path, char out[MAPCOMPILE_SHA256_HEX])
{
    out[0] = '\0';
    uint8_t *data = NULL;       /* row 411: a file or a section */
    size_t size = 0;
    if (!MapGenFs_Read(path, &data, &size))
        return;
    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(data, size, digest);
    MapGenDigest_Sha256Hex(digest, out);
    free(data);
}

/* Every file directly in `dir` removed (not the directory itself, nothing below it). */
static void clear_dir_files(const char *dir)
{
    if (MapGenFs_IsMem(dir)) {          /* row 411 */
        MapGenFs_EmptyDir(dir);
        return;
    }
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
/* ---- RESUME (ledger row 395, Fable's brief 3 G3) ---------------------------------------------------------------- */

/*
 * One attempt of an earlier run, REPLAYED from its ledger instead of being tried again.
 *
 * A run stopped part way (a crash, the Studio closed) left on disk its ledger - every attempt's verdict and the
 * divergence after it - and a directory per compiled attempt holding the very .map and .bsp that were judged. A
 * resumed run deals the same plan from the same seed and walks the same schedule; for every attempt the ledger
 * names, this restores what that attempt left in the transaction without compiling or walking again:
 *
 *   NOT_APPLIED  - tried for real: the operator's own refusal, no compile, cheap and exact;
 *   any other refusal after a compile - counted, nothing kept, exactly as the try left it;
 *   ACCEPTED     - the edit applied to the accepted geometry again; the .map that writes must be byte for byte the
 *                  attempt's own .map (the writer is deterministic) - else the resume has DIVERGED and says where;
 *                  then the attempt's .bsp becomes the accepted map, the ledger's divergence the accepted divergence,
 *                  and what the try left for later attempts (the forgiven boxes of a lift, a flood or a dig) is
 *                  taken again from the same plan, the same accepted map and the same compiled file.
 *
 * The walk of the last replayed map is taken once, by `MapGenTransaction_ReplayDone`, before the first real attempt.
 */
mapgen_transaction_verdict_t
MapGenTransaction_Replay(mapgen_transaction_t *txn, const mapgen_typed_edit_t *edit,
                         mapgen_transaction_verdict_t was, uint32_t divergence_after,
                         mapgen_transaction_step_t *step, char *why, size_t why_size)
{
    mapgen_transaction_step_t local;
    if (!step)
        step = &local;
    if (why && why_size)
        why[0] = '\0';
    if (!txn || !edit) {
        if (why) snprintf(why, why_size, "no transaction to replay into");
        return MAPGEN_TXN_REJECTED_WRITE;
    }
    if (was == MAPGEN_TXN_REJECTED_NOT_APPLIED) {
        const mapgen_transaction_verdict_t v = MapGenTransaction_Try(txn, edit, step);
        if (v != MAPGEN_TXN_REJECTED_NOT_APPLIED && why)
            snprintf(why, why_size, "attempt %u: the ledger says NOT_APPLIED, the operator applied",
                     (unsigned)(txn->attempted - 1u));
        return v;
    }
    memset(step, 0, sizeof(*step));
    step->edit = *edit;
    step->divergence_after = txn->accepted_divergence;
    const uint32_t attempt = txn->attempted++;
    if (was != MAPGEN_TXN_ACCEPTED) {
        step->verdict = was;
        if (txn->num_steps < MAX_STEPS)
            txn->steps[txn->num_steps++] = *step;
        return was;
    }
    char dir[MAPCOMPILE_MAX_PATH], map_path[MAPCOMPILE_MAX_PATH], bsp_path[MAPCOMPILE_MAX_PATH],
         check_path[MAPCOMPILE_MAX_PATH];
    /* row 411: in memory, what was built is the checkpoint on the disk; the replay's own map is written to memory */
    const bool in_memory = MapGenFs_IsMem(txn->job_root) && g_txn_disk_root[0];
    snprintf(dir, sizeof(dir), "%s/try_%04u", in_memory ? g_txn_disk_root : txn->job_root, (unsigned)attempt);
    snprintf(map_path, sizeof(map_path), "%s/%s.map", dir, txn->map_name);
    snprintf(bsp_path, sizeof(bsp_path), "%s/%s.bsp", dir, txn->map_name);
    if (in_memory) {
        char replay_dir[MAPCOMPILE_MAX_PATH];
        snprintf(replay_dir, sizeof(replay_dir), "%s/replay", txn->job_root);
        MapGenFs_MakeDir(replay_dir, txn->map_name);
        snprintf(check_path, sizeof(check_path), "%s/%s.replay.map", replay_dir, txn->map_name);
    } else
        snprintf(check_path, sizeof(check_path), "%s/%s.replay.map", dir, txn->map_name);
    mapgen_geometry_t *candidate = NULL;
    if (MapGenGeometry_Clone(txn->accepted, &candidate) != MAPGEN_GEOMETRY_OK) {
        if (why) snprintf(why, why_size, "attempt %u: cannot clone the accepted map", (unsigned)attempt);
        return step->verdict = MAPGEN_TXN_REJECTED_WRITE;
    }
    bool changed = false;
    MapGenGeometryEdit_ApplyOne(txn->plan, candidate, txn->donor, edit->target, &changed);
    bool same = false;
    if (changed && MapGenGeometry_WriteValve220(candidate, check_path) == MAPGEN_GEOMETRY_OK) {
        same = files_equal(check_path, map_path)
               || (g_replay_any_lights && maps_equal_but_lights(check_path, map_path));
        /* row 402: kept when it differs, so the divergence can be read line by line */
        if (same)
            MapGenFs_Remove(check_path);
    }
    mapgen_bsp_t *built = same ? load_bsp(bsp_path) : NULL;
    if (!built) {
        if (why)
            snprintf(why, why_size, "attempt %u: %s", (unsigned)attempt,
                     !changed ? "the ledger says ACCEPTED, the operator declined"
                     : !same ? "the edit replayed is not the map that was built (its .map differs)"
                             : "the attempt's .bsp cannot be read");
        MapGenGeometry_Free(candidate);
        return step->verdict = MAPGEN_TXN_REJECTED_WRITE;
    }
    step->faults_after = MapGenGeometry_SurfaceFaults(candidate, txn->donor_bsp);

    /* what the try left for later attempts: the same three questions `judge` asks, on the same inputs */
    mapgen_movers_t *movers = calloc(1, sizeof(*movers));
    if (movers && !MapGenMovers_Read(built, movers)) {
        free(movers);
        movers = NULL;
    }
    if (movers)
        MapGenMovers_MeasureClearance(movers, built);   /* as `judge` reads them */
    float pending_lo[3], pending_hi[3], pending_rise = 0.0f;
    const bool pending = MapGenGeometryEdit_ReplacedFlight(txn->plan, txn->donor, edit->target, pending_lo,
                                                           pending_hi, &pending_rise)
                      && machine_serves(movers, pending_lo, pending_hi, pending_rise);
    free(movers);
    float flood_lo[3] = { 0, 0, 0 }, flood_hi[3] = { 0, 0, 0 };
    const bool flooding = edit->kind == MAPGEN_EDIT_FLOOD
        && MapGenGeometryEdit_BoxOf(txn->plan, txn->accepted_map ? txn->accepted_map : txn->donor_bsp,
                                    txn->donor, edit->target, flood_lo, flood_hi);
    float foot_lo[3] = { 0, 0, 0 }, foot_hi[3] = { 0, 0, 0 };
    if (flooding && !MapGenGeometryEdit_FloodFootprint(txn->plan, edit->target, foot_lo, foot_hi)) {
        memcpy(foot_lo, flood_lo, sizeof(foot_lo));
        memcpy(foot_hi, flood_hi, sizeof(foot_hi));
    }
    float dig_boxes[6u * MAPGEN_TXN_MAX_DIG_SEGS];
    uint32_t dig_segs = 0;
    if (edit->kind == MAPGEN_EDIT_DIG) {
        const mapgen_geometry_edit_t *de = MapGenGeometryEdit_At(txn->plan, edit->target);
        if (de)
            dig_segs = MapGenGeometryEdit_DigBoxes(txn->plan, de->target, dig_boxes, MAPGEN_TXN_MAX_DIG_SEGS);
    }
    if (pending && txn->num_forgiven < MAPGEN_TXN_MAX_FORGIVEN) {
        memcpy(txn->forgiven[txn->num_forgiven].lo, pending_lo, sizeof(pending_lo));
        memcpy(txn->forgiven[txn->num_forgiven].hi, pending_hi, sizeof(pending_hi));
        txn->forgiven[txn->num_forgiven].liquid = false;
        txn->forgiven[txn->num_forgiven++].rise = pending_rise;
    }
    if (flooding && txn->num_forgiven < MAPGEN_TXN_MAX_FORGIVEN) {
        for (int a = 0; a < 3; a++) {
            txn->forgiven[txn->num_forgiven].lo[a] = foot_lo[a] - 24.0f;
            txn->forgiven[txn->num_forgiven].hi[a] = foot_hi[a] + 24.0f;
        }
        txn->forgiven[txn->num_forgiven].rise = 0.0f;
        txn->forgiven[txn->num_forgiven++].liquid = true;
    }
    for (uint32_t s = 0; s < dig_segs && txn->num_forgiven < MAPGEN_TXN_MAX_FORGIVEN; s++) {
        for (int a = 0; a < 3; a++) {
            txn->forgiven[txn->num_forgiven].lo[a] = dig_boxes[6u * s + (uint32_t)a] - 24.0f;
            txn->forgiven[txn->num_forgiven].hi[a] = dig_boxes[6u * s + 3u + (uint32_t)a] + 24.0f;
        }
        txn->forgiven[txn->num_forgiven].rise = 0.0f;
        txn->forgiven[txn->num_forgiven++].liquid = true;
    }

    /* retained, as `judge` retains - the walk is taken once the replay ends */
    MapGenGeometry_Free(txn->accepted);
    txn->accepted = candidate;
    txn->accepted_divergence = divergence_after;
    txn->accepted_faults = step->faults_after;
    snprintf(txn->accepted_bsp, sizeof(txn->accepted_bsp), "%s", bsp_path);
    MapGenBsp_Free(txn->accepted_map);
    txn->accepted_map = built;
    MapGenGeometryEdit_SetGround(txn->plan, txn->accepted_map);
    MapGenReach_Free(txn->parent_reach);
    txn->parent_reach = NULL;
    txn->parent_reach_tried = false;
    txn->parent_is_baseline = false;
    file_sha256_hex(bsp_path, txn->accepted_sha256);
    snprintf(step->bsp_sha256, sizeof(step->bsp_sha256), "%s", txn->accepted_sha256);
    txn->accepted_count++;
    const mapgen_geometry_edit_t *planned = MapGenGeometryEdit_At(txn->plan, edit->target);
    if (planned && planned->kind == MAPGEN_EDIT_GRAFT_BUNDLE) {
        txn->grafts_accepted++;
        const char *from = MapGenGeometryEdit_GraftedFrom(txn->plan, planned->target);
        for (uint32_t i = 0; i < txn->num_others; i++)
            if (from && !strcmp(from, txn->other_name[i]))
                txn->other_used[i] = true;
    }
    if (planned && planned->kind == MAPGEN_EDIT_DIG) {        /* brief 9 */
        const char *from = MapGenGeometryEdit_DigFrom(txn->plan, planned->target);
        for (uint32_t i = 0; i < txn->num_others; i++)
            if (from && !strcmp(from, txn->other_name[i]))
                txn->other_used[i] = true;
    }
    step->divergence_after = divergence_after;
    step->verdict = MAPGEN_TXN_ACCEPTED;
    if (txn->num_steps < MAX_STEPS)
        txn->steps[txn->num_steps++] = *step;
    return MAPGEN_TXN_ACCEPTED;
}

/*
 * The replay is over: the walk of the accepted map, as `judge` would have handed it over, and the first real
 * attempt's directory cleared of whatever the interrupted run left in it (the compiler refuses a directory that
 * already holds an output).
 */
bool MapGenTransaction_ReplayDone(mapgen_transaction_t *txn)
{
    if (!txn)
        return false;
    if (!txn->parent_reach_tried && txn->accepted_map) {
        mapgen_reach_t *reach = NULL;
        if (MapGenReach_Explore(txn->accepted_map, 40000u, &reach) == MAPGEN_REACH_OK && reach) {
            txn->accepted_reach = *MapGenReach_Report(reach);
            txn->accepted_component = txn->accepted_reach.component;
            txn->parent_reach = reach;
        }
        txn->parent_reach_tried = true;
    }
    char dir[MAPCOMPILE_MAX_PATH];
    snprintf(dir, sizeof(dir), "%s/try_%04u", txn->job_root, (unsigned)txn->attempted);
    clear_dir_files(dir);
    return true;
}

mapgen_transaction_verdict_t MapGenTransaction_VerdictFromName(const char *name)
{
    for (int v = 0; v < (int)MAPGEN_TXN_NUM_VERDICTS; v++)
        if (name && !strcmp(name, MapGenTransaction_VerdictName((mapgen_transaction_verdict_t)v)))
            return (mapgen_transaction_verdict_t)v;
    return MAPGEN_TXN_NUM_VERDICTS;
}
