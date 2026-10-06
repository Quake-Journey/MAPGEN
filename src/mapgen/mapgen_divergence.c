/*
 * MapGenDivergence - see inc/common/mapgen_divergence.h.
 *
 * The whole file is one idea: rasterise both compiled maps onto the same
 * lattice, note what each cell carries, and count the cells that disagree.
 * Nothing here knows what an operator is or how many ran, which is the point -
 * two operators that undo each other and one that landed behind a wall all
 * raise an edit count and move nothing.
 */

#include "common/mapgen_divergence.h"
#include "common/mapgen_movers.h"
#include "common/mapgen_reach.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

const char *MapGenDivergence_ResultName(mapgen_divergence_result_t r)
{
    switch (r) {
    case MAPGEN_DIVERGENCE_OK:                    return "OK";
    case MAPGEN_DIVERGENCE_ERR_ARGS:              return "ERR_ARGS";
    case MAPGEN_DIVERGENCE_ERR_MEMORY:            return "ERR_MEMORY";
    case MAPGEN_DIVERGENCE_ERR_TOO_LARGE:         return "ERR_TOO_LARGE";
    case MAPGEN_DIVERGENCE_ERR_NO_DONOR_STRUCTURE:
        return "ERR_NO_DONOR_STRUCTURE";
    }
    return "ERR_UNKNOWN";
}

uint32_t MapGenDivergence_Target(uint32_t fidelity)
{
    if (fidelity > 100)
        fidelity = 100;
    return 10u * (100u - fidelity);
}

/* What a cell carries. One bit each, so a cell that changed in three ways is
   still one changed cell. */
#define CELL_SOLID     0x01u
#define CELL_SURFACE   0x02u
#define CELL_VERTICAL  0x04u
#define CELL_ROUTE     0x08u
#define CELL_MOTIF     0x10u

typedef struct {
    int32_t  mins[3];
    int32_t  size[3];
    uint32_t count;
    uint8_t *flags;

    /* What KIND of place each cell is part of, when it is part of one. Kept
       beside the flags rather than in them, because the motif axis is the one
       axis where "changed" means the value differs rather than the bit
       flipped. */
    uint32_t *motif;

    /* How much drawn surface, in square units, the faces put in each cell -
       and how much of that faced upward. Accumulated rather than flagged,
       because a bit that is set by TOUCHING a cell is a bit that depends on
       how the compiler cut the surface up. See rasterise_faces. */
    float *area;
    float *floor_area;
} lattice_t;

/*
 * How much of a cell a surface has to cover before the cell is one it is in.
 *
 * A cell's own cross-section is 32 x 32 = 1024 square units. A face that
 * clips a corner of a cell contributes a sliver, and whether a sliver lands
 * inside a cell at all depends on where the compiler happened to cut the
 * face - which is the thing this axis must not depend on. A twentieth of a
 * cell is comfortably above every sliver measured on the fixtures and far
 * below a wall crossing a cell, which contributes the whole 1024.
 */
#define CELL_AREA        (MAPGEN_DIVERGENCE_CELL * MAPGEN_DIVERGENCE_CELL)
#define AREA_THRESHOLD   (CELL_AREA * 0.05f)

static int32_t floor_div(float v)
{
    return (int32_t)floorf(v / MAPGEN_DIVERGENCE_CELL);
}

static bool lattice_init(lattice_t *l, const float mins[3], const float maxs[3])
{
    memset(l, 0, sizeof(*l));
    uint64_t total = 1;
    for (int i = 0; i < 3; i++) {
        l->mins[i] = floor_div(mins[i]) - 1;
        const int32_t hi = floor_div(maxs[i]) + 1;
        l->size[i] = hi - l->mins[i] + 1;
        if (l->size[i] <= 0)
            return false;
        total *= (uint64_t)l->size[i];
        if (total > MAPGEN_DIVERGENCE_MAX_CELLS)
            return false;
    }
    l->count = (uint32_t)total;
    l->flags = calloc(l->count, 1);
    l->motif = calloc(l->count, sizeof(uint32_t));
    l->area = calloc(l->count, sizeof(float));
    l->floor_area = calloc(l->count, sizeof(float));
    return l->flags != NULL && l->motif != NULL
        && l->area != NULL && l->floor_area != NULL;
}

static void lattice_free(lattice_t *l)
{
    free(l->flags);
    free(l->motif);
    free(l->area);
    free(l->floor_area);
    l->flags = NULL;
    l->motif = NULL;
    l->area = NULL;
    l->floor_area = NULL;
}

static int64_t lattice_index(const lattice_t *l, const int32_t c[3])
{
    for (int i = 0; i < 3; i++) {
        const int32_t at = c[i] - l->mins[i];
        if (at < 0 || at >= l->size[i])
            return -1;
    }
    return (int64_t)(c[0] - l->mins[0])
         + (int64_t)(c[1] - l->mins[1]) * l->size[0]
         + (int64_t)(c[2] - l->mins[2]) * l->size[0] * l->size[1];
}

static void mark(lattice_t *l, const int32_t c[3], uint8_t bit)
{
    const int64_t at = lattice_index(l, c);
    if (at >= 0)
        l->flags[at] |= bit;
}

static void mark_point(lattice_t *l, const float p[3], uint8_t bit)
{
    const int32_t c[3] = { floor_div(p[0]), floor_div(p[1]), floor_div(p[2]) };
    mark(l, c, bit);
}

/* Put a face's square units into the cell they are in. */
static void add_area(lattice_t *l, const int32_t c[3], float area, bool upward)
{
    const int64_t at = lattice_index(l, c);
    if (at < 0)
        return;
    l->area[at] += area;
    if (upward)
        l->floor_area[at] += area;
}

/* ---- what each map puts in each cell ----------------------------------------- */

/*
 * Solid, sampled at the cell's own centre - and then reduced to its SHELL.
 *
 * A Quake II map is a hollow shape inside an infinite solid: everything
 * outside the walls is solid too, and there is a great deal of it. Counting
 * all of it made q2dm1 three hundred and seventy-eight thousand solid cells
 * against eleven thousand surface cells, so the aggregate became "how much of
 * the void changed" and every real edit rounded to nothing.
 *
 * The architecture is the boundary: a solid cell with a non-solid neighbour.
 * The inside of a rock is not architecture and neither is the sky beyond the
 * ceiling. A wall three cells thick that is removed still counts, because the
 * shell cells on both of its faces change.
 *
 * A cell is not "part solid" either: at thirty-two units the question is
 * whether the architecture is there, and the surface axis is what notices a
 * wall that moved by less than a cell.
 */
static void rasterise_solid(const mapgen_bsp_t *bsp, lattice_t *l)
{
    uint8_t *solid = calloc(l->count, 1);
    if (!solid)
        return;

    for (int32_t z = 0; z < l->size[2]; z++) {
      for (int32_t y = 0; y < l->size[1]; y++) {
        for (int32_t x = 0; x < l->size[0]; x++) {
            const int32_t c[3] = { l->mins[0] + x, l->mins[1] + y,
                                   l->mins[2] + z };
            const float p[3] = {
                (c[0] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
                (c[1] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
                (c[2] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
            };
            if (MapGenBsp_PointContents(bsp, p) & 1) {
                const int64_t at = lattice_index(l, c);
                if (at >= 0)
                    solid[at] = 1;
            }
        }
      }
    }

    static const int32_t SIDES[6][3] = {
        { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 },
        { 0, -1, 0 }, { 0, 0, 1 }, { 0, 0, -1 },
    };
    for (int32_t z = 0; z < l->size[2]; z++) {
      for (int32_t y = 0; y < l->size[1]; y++) {
        for (int32_t x = 0; x < l->size[0]; x++) {
            const int32_t c[3] = { l->mins[0] + x, l->mins[1] + y,
                                   l->mins[2] + z };
            const int64_t at = lattice_index(l, c);
            if (at < 0 || !solid[at])
                continue;
            for (int s = 0; s < 6; s++) {
                const int32_t n[3] = { c[0] + SIDES[s][0], c[1] + SIDES[s][1],
                                       c[2] + SIDES[s][2] };
                const int64_t next = lattice_index(l, n);
                if (next >= 0 && !solid[next]) {
                    mark(l, c, CELL_SOLID);
                    break;
                }
            }
        }
      }
    }
    free(solid);
}

/*
 * How much of a polygon lies inside one cell.
 *
 * Sutherland-Hodgman against the cell's six planes, then the area of what is
 * left. The bound on the working polygon is the input's vertices plus one per
 * clipping plane, and the caller's input is capped at sixty-four.
 */
#define CLIP_MAX 96

static float clipped_area(const float points[][3], uint32_t n,
                          const int32_t cell[3])
{
    float buf[2][CLIP_MAX][3];
    uint32_t count = n < CLIP_MAX ? n : CLIP_MAX;
    memcpy(buf[0], points, count * sizeof(buf[0][0]));
    int cur = 0;

    for (int axis = 0; axis < 3; axis++) {
        for (int side = 0; side < 2; side++) {
            /*
             * A cell is half-open: [lo, hi). Keep p >= lo and p < hi.
             *
             * Half-open because the cells have to PARTITION space. A wall
             * lying exactly on a cell boundary - which in a Quake map is
             * most of them, the grid being 32 units and the cell being 32
             * units - would otherwise be wholly inside the cell on each
             * side of it and get counted twice.
             */
            const float bound = (float)(cell[axis] + side)
                              * MAPGEN_DIVERGENCE_CELL;
            const float sign = side ? -1.0f : 1.0f;
            const uint32_t in = count;
            uint32_t out = 0;
            if (!in)
                return 0.0f;
            for (uint32_t i = 0; i < in && out + 1 < CLIP_MAX; i++) {
                const float *a = buf[cur][i];
                const float *b = buf[cur][(i + 1) % in];
                const float da = sign * (a[axis] - bound);
                const float db = sign * (b[axis] - bound);
                const bool a_in = side ? (da > 0.0f) : (da >= 0.0f);
                const bool b_in = side ? (db > 0.0f) : (db >= 0.0f);
                if (a_in)
                    memcpy(buf[!cur][out++], a, sizeof(buf[0][0]));
                if (a_in != b_in) {
                    const float t = da / (da - db);
                    for (int k = 0; k < 3; k++)
                        buf[!cur][out][k] = a[k] + (b[k] - a[k]) * t;
                    out++;
                }
            }
            cur = !cur;
            count = out;
            if (count < 3)
                return 0.0f;
        }
    }

    /* Twice the area is the length of the summed cross products. */
    float sum[3] = { 0.0f, 0.0f, 0.0f };
    for (uint32_t i = 0; i < count; i++) {
        const float *a = buf[cur][i];
        const float *b = buf[cur][(i + 1) % count];
        sum[0] += a[1] * b[2] - a[2] * b[1];
        sum[1] += a[2] * b[0] - a[0] * b[2];
        sum[2] += a[0] * b[1] - a[1] * b[0];
    }
    return 0.5f * sqrtf(sum[0] * sum[0] + sum[1] * sum[1] + sum[2] * sum[2]);
}

/*
 * Where the map is visible, and where its floors are.
 *
 * Both come from the drawn faces, because a face is the compiler's own
 * statement of what a player can see and stand on. A face whose normal points
 * up is a floor.
 *
 * The face's INTERIOR is what marks cells, not its edges. Walking the edges
 * looks equivalent and is not: the compiler is free to split one surface into
 * three, and a split adds interior edges whose cells then get marked in one
 * map and not the other. Recompiling q2dm1 unchanged came out fifty-three
 * permille different from itself, and every bit of that was the compiler
 * choosing different splits.
 *
 * --- and sampling the interior is not enough either ------------------------
 *
 * That was the claim this code carried, and Codex asked for it to be proved
 * (2026-09-06 section 3). It is not true, and the fixture says so: the same
 * .map compiled with -chop 64 instead of 240 - identical geometry, 270 faces
 * where there were 42 - came out TWENTY-FIVE permille different on this axis,
 * and merely writing the same brushes in a different order came out six.
 *
 * The reason is that a cell was marked by being TOUCHED. A face that clips the
 * corner of a cell marks it exactly as hard as a wall crossing it, so whether
 * the cell is marked at all comes down to whether a sample point of whatever
 * triangulation the compiler chose happened to land in that corner - which is
 * the compiler's business and not the map's.
 *
 * So the axis counts AREA. Each triangle spreads its own square units over the
 * cells its samples land in, and a cell is part of the surface when it holds
 * more than a twentieth of a cell's worth. Cutting a face into pieces
 * partitions its area exactly, so the total each cell receives does not depend
 * on how the cutting went; the sampling density is fixed in world units for
 * the same reason, so a bigger triangle gets proportionally more samples
 * rather than the same number spread thinner. Same reason the render
 * canonicalisation aggregates per plane and not per face.
 */
static uint32_t rasterise_faces(const mapgen_bsp_t *bsp, lattice_t *l)
{
    uint32_t skipped = 0;
    const uint32_t num_faces = MapGenBsp_NumFaces(bsp);
    float points[64][3];

    for (uint32_t f = 0; f < num_faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        if (!face || face->numedges < 3)
            continue;
        const mapgen_bsp_plane_t *plane = MapGenBsp_Plane(bsp, face->planenum);
        if (!plane)
            continue;

        const float up = face->side ? -plane->normal[2] : plane->normal[2];
        const uint8_t bit = CELL_SURFACE | (up > 0.7f ? CELL_VERTICAL : 0u);

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
            memcpy(points[n++], v->point, sizeof(points[0]));
        }
        if (n < 3)
            continue;

        /*
         * How much of this polygon is in each cell - exactly, by clipping it
         * to the cell, not by counting samples that landed there.
         *
         * Exactly is what makes the axis invariant: area is additive, so
         * however the compiler cut this surface up, the pieces' areas inside
         * a given cell sum to the whole surface's area inside that cell.
         */
        int32_t lo[3], hi[3];
        for (int i = 0; i < 3; i++) {
            float a = points[0][i], b = points[0][i];
            for (uint32_t k = 1; k < n; k++) {
                if (points[k][i] < a) a = points[k][i];
                if (points[k][i] > b) b = points[k][i];
            }
            lo[i] = floor_div(a);
            hi[i] = floor_div(b);
        }
        /*
         * A face spanning more cells than a map has is a face this axis
         * cannot afford to walk; there are none in a sane BSP, and refusing
         * is better than a minute per face.
         *
         * It is COUNTED rather than passed over quietly. A skipped face is a
         * piece of the surface axis that was not measured, and a result with
         * one in it is not a full measurement however small the number looks
         * (Codex, 2026-09-07 section 5).
         */
        double span = 1.0;
        for (int i = 0; i < 3; i++)
            span *= (double)(hi[i] - lo[i] + 1);
        if (span > 262144.0) {
            skipped++;
            continue;
        }

        for (int32_t cz = lo[2]; cz <= hi[2]; cz++) {
          for (int32_t cy = lo[1]; cy <= hi[1]; cy++) {
            for (int32_t cx = lo[0]; cx <= hi[0]; cx++) {
                const int32_t c[3] = { cx, cy, cz };
                if (lattice_index(l, c) < 0)
                    continue;
                const float area = clipped_area(points, n, c);
                if (area > 0.0f)
                    add_area(l, c, area, (bit & CELL_VERTICAL) != 0);
            }
          }
        }
    }

    /*
     * And now the flags, from the areas.
     *
     * One pass at the end rather than a bit set as each face arrives, because
     * the question is how much surface a cell holds ALTOGETHER - three faces
     * each clipping a corner of it are a cell with surface in it, and one of
     * them alone is not.
     */
    for (uint32_t i = 0; i < l->count; i++) {
        if (l->area[i] >= AREA_THRESHOLD)
            l->flags[i] |= CELL_SURFACE;
        if (l->floor_area[i] >= AREA_THRESHOLD)
            l->flags[i] |= CELL_VERTICAL;
    }
    return skipped;
}

/*
 * What a map is BUILT of, marked where each thing actually is.
 *
 * Codex, 2026-09-07: "one mover changing a categorical room signature must not
 * automatically turn every cell in that room into changed architectural
 * extent... Bind motif observations to concrete compiled bundle construction:
 * defining surfaces/solids, mover/submodel geometry and swept extent, typed
 * sockets, and the construction/connection relations they implement. Recognize
 * their spatial placement."
 *
 * What was here before did the opposite. It hashed a room into one number -
 * air to the nearest doubling, socket kinds, a capped mover count, ladders,
 * whether the bundle was carriable - and wrote that number into EVERY cell the
 * segmentation gave the room. So one lift arriving in q2dm1's biggest room
 * moved that room from one mover bucket to the next and 22,105 cells of 49,314
 * changed at once: 448 permille on this axis, 322 on the aggregate, for one
 * staircase. The rungs of the whole metric became 1 permille and 300, and the
 * F90 and F50 bands fall in the gap between them.
 *
 * It also made the axis depend on the segmentation, on a room's identity, and
 * on where an air count fell against a power of two - three kinds of
 * bookkeeping that are not architecture.
 *
 * So the axis marks CONSTRUCTIONS at their own support:
 *
 *   every brush model - a door, a lift, a rotating thing, a button, a trigger
 *   - over the cells its brushes occupy AT EVERY STOP IT HAS, which is its
 *   swept extent and is the space it governs;
 *   every ladder, over the cells its brushes occupy.
 *
 * The value at a cell is the SUM of what stands there, so it does not depend
 * on the order the entity lump happens to list things in, and a cell that
 * gains or loses one of two constructions changes either way.
 *
 * A construction is identified by what it IS and what it DOES - its classname,
 * whether it carries a player, whether he can work it himself, how many stops
 * it has and how far it travels - and never by its model number, its entity
 * index or the room it is in. Two lifts that swap places therefore change
 * both places; a lift that is merely re-numbered changes nothing.
 *
 * Reskins, relights, items and spawns have no construction and so contribute
 * nothing, which is what TZ 14.0.1 requires of them.
 */
static uint32_t construction_value(const mapgen_mover_t *mv)
{
    /* FNV-1a over the things that make it that construction rather than
       another one. Not its ordinal: an entity renumbered is not a map
       changed. */
    uint64_t h = 14695981039346656037ull;
    for (const char *p = mv->classname; *p; p++) {
        h ^= (unsigned char)*p;
        h *= 1099511628211ull;
    }
    const uint32_t bits = (mv->player_operated ? 1u : 0u)
                        | (mv->carries ? 2u : 0u)
                        | (mv->inoperable ? 4u : 0u)
                        | (mv->num_stops << 3);
    h ^= bits;
    h *= 1099511628211ull;
    /* How far it goes, to the unit: a lift whose travel changed is a lift
       that changed, and a unit is under the compiler's own noise floor. */
    for (uint32_t s = 0; s < mv->num_stops && s < MAPGEN_MOVER_STOPS; s++)
        for (int a = 0; a < 3; a++) {
            h ^= (uint64_t)(int64_t)(mv->stop[s][a] < 0.0f
                                     ? mv->stop[s][a] - 0.5f
                                     : mv->stop[s][a] + 0.5f);
            h *= 1099511628211ull;
        }
    /* Never zero: zero is what an unmarked cell carries. */
    return (uint32_t)(h >> 32) | 1u;
}

/* Every cell an axis-aligned box covers, marked and given its share. */
static void mark_box(lattice_t *l, const float lo[3], const float hi[3],
                     uint32_t value)
{
    int32_t a[3], b[3];
    for (int i = 0; i < 3; i++) {
        a[i] = floor_div(lo[i]);
        b[i] = floor_div(hi[i]);
    }
    double span = 1.0;
    for (int i = 0; i < 3; i++)
        span *= (double)(b[i] - a[i] + 1);
    /* A construction bigger than a map is not a construction. */
    if (span > 262144.0)
        return;
    for (int32_t z = a[2]; z <= b[2]; z++)
      for (int32_t y = a[1]; y <= b[1]; y++)
        for (int32_t x = a[0]; x <= b[0]; x++) {
            const int32_t c[3] = { x, y, z };
            const int64_t at = lattice_index(l, c);
            if (at < 0)
                continue;
            l->flags[at] |= CELL_MOTIF;
            l->motif[at] += value;
        }
}

static bool rasterise_motifs(const mapgen_bsp_t *bsp, lattice_t *l)
{
    mapgen_movers_t *movers = calloc(1, sizeof(*movers));
    if (!movers)
        return false;
    /* A map with nothing that moves is a map with no movers, not a failure. */
    (void)MapGenMovers_Read(bsp, movers);

    for (uint32_t i = 0; i < movers->num_movers; i++) {
        const mapgen_mover_t *mv = &movers->movers[i];
        const uint32_t value = construction_value(mv);
        /*
         * At every stop, which is the swept extent: a lift is the shaft it
         * runs in, not the slab where it happens to be parked, and a door is
         * the doorway it closes.
         */
        for (uint32_t s = 0; s < mv->num_stops && s < MAPGEN_MOVER_STOPS; s++) {
            float lo[3], hi[3];
            for (int a = 0; a < 3; a++) {
                lo[a] = mv->mins[a] + mv->stop[s][a];
                hi[a] = mv->maxs[a] + mv->stop[s][a];
            }
            mark_box(l, lo, hi, value);
        }
    }
    free(movers);

    /*
     * And the ladders, which are a construction a player uses and which no
     * brush model owns: solid he can climb.
     */
    for (int32_t z = 0; z < l->size[2]; z++)
      for (int32_t y = 0; y < l->size[1]; y++)
        for (int32_t x = 0; x < l->size[0]; x++) {
            const int32_t c[3] = { l->mins[0] + x, l->mins[1] + y,
                                   l->mins[2] + z };
            const float p[3] = {
                (c[0] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
                (c[1] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
                (c[2] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
            };
            if (!(MapGenBsp_PointContents(bsp, p) & MAPGEN_CONTENTS_LADDER))
                continue;
            const int64_t at = lattice_index(l, c);
            if (at < 0)
                continue;
            l->flags[at] |= CELL_MOTIF;
            l->motif[at] += 0x9E3779B9u;
        }

    return true;
}

/*
 * Where a player can get to - and whether the search finished.
 *
 * This used to accept MAPGEN_REACH_ERR_TOO_LARGE alongside OK, rasterise
 * whatever states had been opened, and return true. TOO_LARGE means the
 * exploration stopped opening states at its budget: the cells it marked are a
 * PREFIX of the map's routes, not the map's routes. `routes_measured` was then
 * true, `complete` was true, and the pipeline's final verdict rested on a
 * measurement that had been cut short. Codex, 2026-09-07 section 5: "an
 * exhausted/failed required axis must remain incomplete and cannot authorize a
 * final target, NO_EFFECT, or publication verdict."
 *
 * So the cells are still marked - a partial route map is a useful diagnostic
 * and throwing it away would tell a reader less - and the truncation is
 * reported, so that nothing downstream can call the result whole.
 */
/*
 * The route cells of one walk: every place a player can get to.
 *
 * One function for a walk taken here and for a walk a caller already has
 * (D19, assignment 23), so a measurement from a handed walk marks exactly the
 * cells one that walked the map itself would.
 */
static void rasterise_walk(const mapgen_reach_t *reach, lattice_t *l)
{
    const uint32_t states = MapGenReach_NumStates(reach);
    for (uint32_t s = 0; s < states; s++) {
        const mapgen_reach_state_t *st = MapGenReach_State(reach, s);
        if (st && st->reachable)
            mark_point(l, st->origin, CELL_ROUTE);
    }
}

static bool rasterise_routes(const mapgen_bsp_t *bsp, lattice_t *l,
                             uint32_t budget, bool *out_truncated)
{
    mapgen_reach_t *reach = NULL;
    const mapgen_reach_result_t rc = MapGenReach_Explore(bsp, budget, &reach);
    if (rc != MAPGEN_REACH_OK && rc != MAPGEN_REACH_ERR_TOO_LARGE) {
        MapGenReach_Free(reach);
        return false;
    }
    if (rc == MAPGEN_REACH_ERR_TOO_LARGE && out_truncated)
        *out_truncated = true;
    rasterise_walk(reach, l);
    MapGenReach_Free(reach);
    return true;
}

/* Walks a caller already took, for the route axis (D19). */
typedef struct {
    const mapgen_reach_t *donor, *candidate;
    bool                  donor_whole, candidate_whole;
} given_walks_t;

/* ---- the comparison ---------------------------------------------------------- */

static void bounds_of(const mapgen_bsp_t *bsp, float mins[3], float maxs[3])
{
    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    if (!world) {
        for (int i = 0; i < 3; i++) {
            mins[i] = -1.0f;
            maxs[i] = 1.0f;
        }
        return;
    }
    memcpy(mins, world->mins, sizeof(float) * 3);
    memcpy(maxs, world->maxs, sizeof(float) * 3);
}

static uint32_t permille(uint32_t part, uint32_t whole)
{
    if (!whole)
        return 0;
    return (uint32_t)((1000ull * part + whole / 2) / whole);
}

mapgen_divergence_result_t MapGenDivergence_Measure(
    const mapgen_bsp_t *donor, const mapgen_bsp_t *candidate,
    uint32_t fidelity, bool measure_routes, mapgen_divergence_t *out)
{
    return MapGenDivergence_MeasureWitness(donor, candidate, fidelity,
                                           measure_routes, out, NULL, NULL);
}

static mapgen_divergence_result_t measure(
    const mapgen_bsp_t *donor, const mapgen_bsp_t *candidate,
    uint32_t fidelity, bool measure_routes, const given_walks_t *walks,
    mapgen_divergence_t *out, mapgen_divergence_witness_fn witness,
    void *user)
{
    if (!donor || !candidate || !out)
        return MAPGEN_DIVERGENCE_ERR_ARGS;
    memset(out, 0, sizeof(*out));
    out->schema = MAPGEN_DIVERGENCE_SCHEMA;
    out->fidelity = fidelity > 100 ? 100 : fidelity;
    out->target_permille = MapGenDivergence_Target(out->fidelity);

    /* One lattice for both, spanning both, so a cell means the same place in
       each and a candidate that grew the map is measured over the growth. */
    float mins[3], maxs[3], other_mins[3], other_maxs[3];
    bounds_of(donor, mins, maxs);
    bounds_of(candidate, other_mins, other_maxs);
    for (int i = 0; i < 3; i++) {
        if (other_mins[i] < mins[i])
            mins[i] = other_mins[i];
        if (other_maxs[i] > maxs[i])
            maxs[i] = other_maxs[i];
    }

    lattice_t a, b;
    if (!lattice_init(&a, mins, maxs))
        return MAPGEN_DIVERGENCE_ERR_TOO_LARGE;
    if (!lattice_init(&b, mins, maxs)) {
        lattice_free(&a);
        return MAPGEN_DIVERGENCE_ERR_TOO_LARGE;
    }

    rasterise_solid(donor, &a);
    out->surfaces_skipped = rasterise_faces(donor, &a);
    rasterise_solid(candidate, &b);
    out->surfaces_skipped += rasterise_faces(candidate, &b);

    if (!rasterise_motifs(donor, &a) || !rasterise_motifs(candidate, &b)) {
        lattice_free(&a);
        lattice_free(&b);
        return MAPGEN_DIVERGENCE_ERR_MEMORY;
    }
    out->motifs_measured = true;

    if (measure_routes && walks) {
        /*
         * D19: the walks the caller already took, marked as a walk taken here
         * would be. A walk that is missing did not measure the axis, and one
         * that did not finish sampled it - the same two answers a walk taken
         * below gives.
         */
        if (walks->donor)
            rasterise_walk(walks->donor, &a);
        if (walks->candidate)
            rasterise_walk(walks->candidate, &b);
        const bool truncated = (walks->donor && !walks->donor_whole)
                            || (walks->candidate && !walks->candidate_whole);
        out->routes_truncated = truncated;
        out->routes_measured = walks->donor && walks->candidate && !truncated;
    } else if (measure_routes) {
        bool truncated = false;
        const bool ok = rasterise_routes(donor, &a, 40000, &truncated)
                     && rasterise_routes(candidate, &b, 40000, &truncated);
        out->routes_truncated = truncated;
        /* A search that ran out of budget did not measure the axis; it
           sampled it. The cells are marked for the diagnostic and the axis
           does not count as run. */
        out->routes_measured = ok && !truncated;
    }

    for (uint32_t i = 0; i < a.count; i++) {
        const uint8_t x = a.flags[i];
        const uint8_t y = b.flags[i];
        const uint8_t differ = (uint8_t)(x ^ y);

        if (x & CELL_SOLID) {
            out->solid_cells++;
            if (differ & CELL_SOLID)
                out->solid_changed++;
        } else if (differ & CELL_SOLID) {
            /* Solid where the donor had none is a change to the donor's
               architecture too - the cell is bound to the donor by being
               inside its bounds, and filling it in is exactly the kind of
               edit that has to count. */
            out->solid_cells++;
            out->solid_changed++;
        }

        if ((x | y) & CELL_SURFACE) {
            out->surface_cells++;
            if (differ & CELL_SURFACE)
                out->surface_changed++;
        }
        if ((x | y) & CELL_VERTICAL) {
            out->vertical_cells++;
            if (differ & CELL_VERTICAL)
                out->vertical_changed++;
        }
        if (out->routes_measured && ((x | y) & CELL_ROUTE)) {
            out->route_cells++;
            if (differ & CELL_ROUTE)
                out->route_changed++;
        }
        /*
         * The one axis where "changed" is not a bit flipping. A cell that is
         * part of a place in both maps has changed when it is part of a
         * DIFFERENT KIND of place, and that is a comparison of two values
         * rather than of two flags.
         */
        if ((x | y) & CELL_MOTIF) {
            out->motif_cells++;
            if (a.motif[i] != b.motif[i])
                out->motif_changed++;
        }

        uint8_t measured = CELL_SOLID | CELL_SURFACE | CELL_VERTICAL
                         | CELL_MOTIF;
        if (out->routes_measured)
            measured |= CELL_ROUTE;
        if ((x | y) & measured) {
            out->donor_cells++;
            const bool moved = (differ & measured)
                            || (((x | y) & CELL_MOTIF)
                                && a.motif[i] != b.motif[i]);
            if (moved)
                out->changed_cells++;
            /* Say WHICH cell and WHY, for anyone who wants to check the
               summary rather than believe it. */
            if (moved && witness) {
                const int32_t c[3] = {
                    a.mins[0] + (int32_t)(i % (uint32_t)a.size[0]),
                    a.mins[1] + (int32_t)((i / (uint32_t)a.size[0])
                                          % (uint32_t)a.size[1]),
                    a.mins[2] + (int32_t)(i / (uint32_t)(a.size[0]
                                                         * a.size[1])),
                };
                const float w[3] = {
                    (c[0] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
                    (c[1] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
                    (c[2] + 0.5f) * MAPGEN_DIVERGENCE_CELL,
                };
                witness(user, c, w, x & measured, y & measured,
                        a.motif[i], b.motif[i]);
            }
        }
    }

    lattice_free(&a);
    lattice_free(&b);

    if (!out->donor_cells)
        return MAPGEN_DIVERGENCE_ERR_NO_DONOR_STRUCTURE;

    out->solid_permille    = permille(out->solid_changed, out->solid_cells);
    out->surface_permille  = permille(out->surface_changed, out->surface_cells);
    out->vertical_permille = permille(out->vertical_changed,
                                      out->vertical_cells);
    out->route_permille    = permille(out->route_changed, out->route_cells);
    out->motif_permille    = permille(out->motif_changed, out->motif_cells);
    out->aggregate_permille = permille(out->changed_cells, out->donor_cells);

    const int32_t off = (int32_t)out->aggregate_permille
                      - (int32_t)out->target_permille;
    out->within_band = (off >= -50 && off <= 50);
    /* Every axis of 14.0.1 measured, and none of them cut short. A face this
       axis could not walk leaves the surface axis short of the map. */
    out->complete = out->routes_measured && out->motifs_measured
                 && !out->routes_truncated && out->surfaces_skipped == 0;
    return MAPGEN_DIVERGENCE_OK;
}

mapgen_divergence_result_t MapGenDivergence_MeasureWitness(
    const mapgen_bsp_t *donor, const mapgen_bsp_t *candidate,
    uint32_t fidelity, bool measure_routes, mapgen_divergence_t *out,
    mapgen_divergence_witness_fn witness, void *user)
{
    return measure(donor, candidate, fidelity, measure_routes, NULL, out,
                   witness, user);
}

mapgen_divergence_result_t MapGenDivergence_MeasureWalked(
    const mapgen_bsp_t *donor, const struct mapgen_reach_s *donor_walk,
    bool donor_whole, const mapgen_bsp_t *candidate,
    const struct mapgen_reach_s *candidate_walk, bool candidate_whole,
    uint32_t fidelity, mapgen_divergence_t *out)
{
    const given_walks_t walks = { donor_walk, candidate_walk, donor_whole,
                                  candidate_whole };
    return measure(donor, candidate, fidelity, true, &walks, out, NULL, NULL);
}
