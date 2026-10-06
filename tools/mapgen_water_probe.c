/*
 * Does the water lie IN something, or stand on the floor?
 *
 *     mapgen_water_probe <map.bsp>
 *
 * The PO walked a fork of q2dm1 on 2026-09-07 and said: water cannot lie like
 * that, as if it were part of the architecture - it would run off at once. The
 * flood operator had raised a pool a hundred and ninety-five units above a
 * basin whose rim is eight, and what he was looking at was the SIDE of a block
 * of water standing in the air.
 *
 * That has an exact spelling in a compiled map. The compiler does not draw a
 * face between water and solid - a pool in a basin has no vertical faces at
 * all - so every drawn face with liquid on one side and open air on the other
 * is water meeting air, which water does not do. This counts them and their
 * area, and it decides "liquid" and "air" by the CONTENTS either side of the
 * face rather than by a texture name, because that is what the engine will do
 * when a player swims into it.
 *
 *     vertical liquid faces N area A       the contract
 *     face ...                             one line each, biggest first
 *     pool <box> surface Z rim R           what the basin would have allowed
 *     flooded N drained M                  with a baseline: how much of the
 *                                          map the water took and gave back
 *
 * With a second file - the baseline the candidate was made from - every
 * standing place of the baseline is asked how deep it is in each, and the
 * ones that went under (or came out from under) by more than a player's
 * knees are counted. That is the size of a relevel: the flood the PO liked
 * put a thousand of them under water, and the twelve-unit rise the basin
 * rule allowed after it put none.
 *
 * The rim is the diagnosis rather than the contract: for each vertical side of
 * a liquid brush, how far above the surface the solid beside it goes before it
 * gives way to air. A pool may rise by the smallest of them and no further.
 *
 * Exit 1 when the map has any vertical liquid face, so a guard can use the
 * status and a reader can use the lines.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"

#define CONTENTS_SOLID  0x00000001
#define CONTENTS_LAVA   0x00000008
#define CONTENTS_SLIME  0x00000010
#define CONTENTS_WATER  0x00000020
#define LIQUID          (CONTENTS_LAVA | CONTENTS_SLIME | CONTENTS_WATER)

#define VERTICAL_COS    0.5f    /* within 30 degrees of vertical */
#define RIM_PROBE       8.0f    /* how far outside a side to look */
#define RIM_STEP        4.0f
#define RIM_REACH       512.0f

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

static uint32_t face_points(const mapgen_bsp_t *bsp,
                            const mapgen_bsp_face_t *face, float out[64][3])
{
    uint32_t n = 0;
    for (int32_t e = 0; e < face->numedges && n < 64; e++) {
        const int32_t se =
            MapGenBsp_SurfEdge(bsp, (uint32_t)(face->firstedge + e));
        const mapgen_bsp_edge_t *edge =
            MapGenBsp_Edge(bsp, (uint32_t)(se < 0 ? -se : se));
        if (!edge)
            break;
        const mapgen_bsp_vertex_t *v =
            MapGenBsp_Vertex(bsp, se < 0 ? edge->v[1] : edge->v[0]);
        if (!v)
            break;
        memcpy(out[n++], v->point, sizeof(out[0]));
    }
    return n;
}

static float polygon_area(const float p[64][3], uint32_t n)
{
    if (n < 3)
        return 0.0f;
    float sum[3] = { 0, 0, 0 };
    for (uint32_t i = 1; i + 1 < n; i++) {
        const float a[3] = { p[i][0] - p[0][0], p[i][1] - p[0][1],
                             p[i][2] - p[0][2] };
        const float b[3] = { p[i + 1][0] - p[0][0], p[i + 1][1] - p[0][1],
                             p[i + 1][2] - p[0][2] };
        sum[0] += a[1] * b[2] - a[2] * b[1];
        sum[1] += a[2] * b[0] - a[0] * b[2];
        sum[2] += a[0] * b[1] - a[1] * b[0];
    }
    return 0.5f * sqrtf(sum[0] * sum[0] + sum[1] * sum[1] + sum[2] * sum[2]);
}

/* The axis-aligned box a brush's axial planes bound. */
static bool brush_box(const mapgen_bsp_t *bsp, const mapgen_bsp_brush_t *br,
                      float mins[3], float maxs[3])
{
    for (int a = 0; a < 3; a++) {
        mins[a] = -1e9f;
        maxs[a] = 1e9f;
    }
    for (int32_t s = 0; s < br->numsides; s++) {
        const mapgen_bsp_brushside_t *side =
            MapGenBsp_BrushSide(bsp, (uint32_t)(br->firstside + s));
        if (!side)
            return false;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, side->planenum);
        if (!pl)
            return false;
        for (int a = 0; a < 3; a++) {
            if (pl->normal[a] > 0.999f && pl->dist < maxs[a])
                maxs[a] = pl->dist;
            if (pl->normal[a] < -0.999f && -pl->dist > mins[a])
                mins[a] = -pl->dist;
        }
    }
    for (int a = 0; a < 3; a++)
        if (mins[a] < -1e8f || maxs[a] > 1e8f || maxs[a] <= mins[a])
            return false;
    return true;
}

/*
 * How far this pool could rise before it spills.
 *
 * Along every vertical side, eight units out, climb from the surface until the
 * map is no longer solid there: that column's rim. The pool's rim is the
 * lowest of them, because water finds the low side.
 */
static float rim_of(const mapgen_bsp_t *bsp, const float mins[3],
                    const float maxs[3])
{
    float rim = RIM_REACH;
    for (int axis = 0; axis < 2; axis++) {
        const int across = axis ^ 1;
        for (int dir = 0; dir < 2; dir++) {
            const float at = dir ? maxs[axis] + RIM_PROBE
                                 : mins[axis] - RIM_PROBE;
            for (float t = mins[across] + 4.0f; t < maxs[across]; t += 16.0f) {
                float p[3];
                p[axis] = at;
                p[across] = t;
                float here = RIM_REACH;
                for (float z = maxs[2]; z <= maxs[2] + RIM_REACH;
                     z += RIM_STEP) {
                    p[2] = z;
                    if (!(MapGenBsp_PointContents(bsp, p) & CONTENTS_SOLID)) {
                        here = z - maxs[2];
                        break;
                    }
                }
                if (here < rim)
                    rim = here;
            }
        }
    }
    return rim;
}

/* Air here, solid just under, room over: a place a player's feet can rest. */
static bool stands(const mapgen_bsp_t *bsp, float x, float y, float z)
{
    const float here[3] = { x, y, z };
    const float below[3] = { x, y, z - 8.0f };
    const float head[3] = { x, y, z + 48.0f };
    return !(MapGenBsp_PointContents(bsp, here) & CONTENTS_SOLID)
        && (MapGenBsp_PointContents(bsp, below) & CONTENTS_SOLID)
        && !(MapGenBsp_PointContents(bsp, head) & CONTENTS_SOLID);
}

/* How deep the liquid is over this place, up to a player's height. */
static float depth_at(const mapgen_bsp_t *bsp, float x, float y, float z)
{
    float depth = 0.0f;
    for (float d = 4.0f; d <= 56.0f; d += 4.0f) {
        const float p[3] = { x, y, z + d };
        if (MapGenBsp_PointContents(bsp, p) & LIQUID)
            depth = d;
        else if (d <= 8.0f)
            return 0.0f;
    }
    return depth;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp> [baseline.bsp]\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }

    /*
     * The contract itself comes from the module, so that what this prints and
     * what the transaction refuses are one implementation. The lines below it
     * are this tool's own: which faces, and where.
     */
    double area = 0.0;
    const uint32_t exposed = MapGenBsp_StandingWater(bsp, &area);

    const uint32_t faces = MapGenBsp_NumFaces(bsp);
    for (uint32_t f = 0; f < faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        if (!face || face->numedges < 3)
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, face->planenum);
        if (!pl || fabsf(pl->normal[2]) > VERTICAL_COS)
            continue;

        float p[64][3];
        const uint32_t n = face_points(bsp, face, p);
        if (n < 3)
            continue;
        float centre[3] = { 0, 0, 0 };
        for (uint32_t i = 0; i < n; i++)
            for (int a = 0; a < 3; a++)
                centre[a] += p[i][a] / (float)n;

        float front[3], back[3];
        for (int a = 0; a < 3; a++) {
            front[a] = centre[a] + pl->normal[a] * 2.0f;
            back[a] = centre[a] - pl->normal[a] * 2.0f;
        }
        const int32_t cf = MapGenBsp_PointContents(bsp, front);
        const int32_t cb = MapGenBsp_PointContents(bsp, back);
        const bool water_air = ((cf & LIQUID) && !(cb & (LIQUID | CONTENTS_SOLID)))
                            || ((cb & LIQUID) && !(cf & (LIQUID | CONTENTS_SOLID)));
        if (!water_air)
            continue;

        const mapgen_bsp_texinfo_t *tex =
            MapGenBsp_TexInfo(bsp, (uint32_t)face->texinfo);
        float lo[3], hi[3];
        memcpy(lo, p[0], sizeof(lo));
        memcpy(hi, p[0], sizeof(hi));
        for (uint32_t i = 1; i < n; i++)
            for (int k = 0; k < 3; k++) {
                if (p[i][k] < lo[k]) lo[k] = p[i][k];
                if (p[i][k] > hi[k]) hi[k] = p[i][k];
            }
        printf("face %8.0f %-22s %6.0f %6.0f %6.0f .. %6.0f %6.0f %6.0f\n",
               polygon_area(p, n), tex ? tex->texture : "(none)",
               lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]);
    }
    printf("vertical liquid faces %u area %.0f\n", exposed, area);

    /* --- the diagnosis: every pool, and how far its basin would let it rise */
    const uint32_t brushes = MapGenBsp_NumBrushes(bsp);
    for (uint32_t b = 0; b < brushes; b++) {
        const mapgen_bsp_brush_t *br = MapGenBsp_Brush(bsp, b);
        if (!br || !(br->contents & LIQUID))
            continue;
        float mins[3], maxs[3];
        if (!brush_box(bsp, br, mins, maxs))
            continue;
        printf("pool %6.0f %6.0f %6.0f .. %6.0f %6.0f %6.0f  surface %.0f"
               "  depth %.0f  rim %.0f\n",
               mins[0], mins[1], mins[2], maxs[0], maxs[1], maxs[2], maxs[2],
               maxs[2] - mins[2], rim_of(bsp, mins, maxs));
    }

    /* --- and, against a baseline, the size of the level change ---------- */
    if (argc > 2) {
        mapgen_bsp_t *base = load(argv[2]);
        if (!base) {
            fprintf(stderr, "cannot read %s\n", argv[2]);
            return 2;
        }
        const mapgen_bsp_model_t *world = MapGenBsp_Model(base, 0);
        uint32_t flooded = 0, drained = 0, places = 0;
        for (float x = world->mins[0] + 16.0f; x < world->maxs[0]; x += 32.0f)
          for (float y = world->mins[1] + 16.0f; y < world->maxs[1]; y += 32.0f)
            for (float z = world->mins[2] + 8.0f; z < world->maxs[2]; z += 8.0f) {
                if (!stands(base, x, y, z))
                    continue;
                places++;
                const float was = depth_at(base, x, y, z);
                const float now = depth_at(bsp, x, y, z);
                if (now >= 24.0f && was < 24.0f)
                    flooded++;
                else if (was >= 24.0f && now < 24.0f)
                    drained++;
                z += 40.0f;
            }
        printf("baseline places %u\n", places);
        printf("flooded %u drained %u\n", flooded, drained);
        MapGenBsp_Free(base);
    }

    MapGenBsp_Free(bsp);
    return exposed ? 1 : 0;
}
