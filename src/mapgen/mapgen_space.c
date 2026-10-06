/*
Copyright (C) 2026 Q2PRO-X

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
*/

/*
 * MAPGEN-1 - the candidate traversal graph.
 *
 * Two passes, both built entirely out of real hull traces:
 *
 *   1. every column of the quantized grid is dropped through from the top,
 *      collecting each place the standing hull comes to rest;
 *   2. every pair of neighbouring columns is joined by stepping up, moving
 *      across and dropping down - the same three motions the player makes -
 *      and an edge exists only when all three traces agree.
 *
 * Nothing is inferred from leaf bounds, PVS or the tree's shape. Contract 18.3
 * rules those out as proof, and they would be wrong anyway: a leaf's bounding
 * box contains solid, and a PVS cluster says nothing about whether a body fits.
 */

#include "common/mapgen_space.h"
#include "common/mapgen_trace.h"

#include <stdlib.h>
#include <string.h>

#define LIQUID_MASK (MAPGEN_TRACE_WATER | MAPGEN_TRACE_SLIME | MAPGEN_TRACE_LAVA)
#define HAZARD_MASK (MAPGEN_TRACE_SLIME | MAPGEN_TRACE_LAVA)

struct mapgen_space_s {
    int32_t  cell;
    int32_t  base[3];              /* quantization origin, on the cell grid  */
    int32_t  span[2];              /* columns in x and y                     */

    mapgen_space_node_t   *nodes;
    uint32_t               num_nodes;
    mapgen_space_edge_t   *edges;
    uint32_t               num_edges;
    mapgen_space_region_t *regions;
    uint32_t               num_regions;

    uint32_t kind_counts[MAPGEN_EDGE_KIND_COUNT];
};

const char *MapGenSpace_ResultName(mapgen_space_result_t r)
{
    switch (r) {
    case MAPGEN_SPACE_OK:            return "OK";
    case MAPGEN_SPACE_ERR_ARGS:      return "ERR_ARGS";
    case MAPGEN_SPACE_ERR_NO_WORLD:  return "ERR_NO_WORLD";
    case MAPGEN_SPACE_ERR_CELL_SIZE: return "ERR_CELL_SIZE";
    case MAPGEN_SPACE_ERR_TOO_LARGE: return "ERR_TOO_LARGE";
    case MAPGEN_SPACE_ERR_MEMORY:    return "ERR_MEMORY";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenSpace_EdgeKindName(mapgen_edge_kind_t k)
{
    switch (k) {
    case MAPGEN_EDGE_WALK: return "walk";
    case MAPGEN_EDGE_STEP: return "step";
    case MAPGEN_EDGE_JUMP: return "jump";
    case MAPGEN_EDGE_FALL: return "fall";
    case MAPGEN_EDGE_SWIM: return "swim";
    case MAPGEN_EDGE_KIND_COUNT: break;
    }
    return "?";
}

mapgen_space_params_t MapGenSpace_DefaultParams(void)
{
    mapgen_space_params_t p;
    p.cell = 32;
    p.include_liquids = true;
    return p;
}

/* ------------------------------------------------------------------------ */

typedef struct {
    mapgen_trace_context_t  trace;
    mapgen_space_t         *space;

    float    mins[3];
    float    maxs[3];
    float    duck_maxs[3];
    float    world_top;
    float    world_bottom;

    uint32_t node_capacity;
    uint32_t edge_capacity;

    /* Where each column's nodes start, so pass 2 can find a neighbour's
       stances without searching. One extra slot holds the end. */
    uint32_t *col_first;
    uint32_t  num_columns;

    uint32_t *parent;              /* union-find over walk/step/swim edges   */
    uint32_t *walk_degree;
    bool      overflowed;
    /* A failed realloc must not read as a small map. Kept apart from the
       ceiling flag so the caller can tell "too big" from "out of memory". */
    bool      out_of_memory;
} build_t;

static bool push_node(build_t *b, const mapgen_space_node_t *node)
{
    mapgen_space_t *sp = b->space;
    if (sp->num_nodes >= MAPGEN_SPACE_MAX_NODES) {
        b->overflowed = true;
        return false;
    }
    if (sp->num_nodes == b->node_capacity) {
        uint32_t want = b->node_capacity ? b->node_capacity * 2u : 1024u;
        if (want > MAPGEN_SPACE_MAX_NODES)
            want = MAPGEN_SPACE_MAX_NODES;
        void *grown = realloc(sp->nodes, (size_t)want * sizeof(*sp->nodes));
        if (!grown) {
            b->out_of_memory = true;
            return false;
        }
        sp->nodes = grown;
        b->node_capacity = want;
    }
    sp->nodes[sp->num_nodes++] = *node;
    return true;
}

static bool push_edge(build_t *b, const mapgen_space_edge_t *edge)
{
    mapgen_space_t *sp = b->space;
    if (sp->num_edges >= MAPGEN_SPACE_MAX_EDGES) {
        b->overflowed = true;
        return false;
    }
    if (sp->num_edges == b->edge_capacity) {
        uint32_t want = b->edge_capacity ? b->edge_capacity * 2u : 4096u;
        if (want > MAPGEN_SPACE_MAX_EDGES)
            want = MAPGEN_SPACE_MAX_EDGES;
        void *grown = realloc(sp->edges, (size_t)want * sizeof(*sp->edges));
        if (!grown) {
            b->out_of_memory = true;
            return false;
        }
        sp->edges = grown;
        b->edge_capacity = want;
    }
    sp->edges[sp->num_edges++] = *edge;
    return true;
}

/* ------------------------------------------------------------------------ */

static bool is_ground(const mapgen_trace_result_t *tr)
{
    /* PM_CategorizePosition's rule, in whole thousandths, so this is the same
       comparison the engine makes rather than a looser one. */
    if (!tr->hit_plane)
        return false;
    return (int32_t)(tr->plane_normal[2] * 1000.0f) >= MAPGEN_SPACE_GROUND_NORMAL_Z_MILLI;
}

static bool hull_fits(build_t *b, const float origin[3], const float *maxs)
{
    mapgen_trace_result_t tr;
    MapGenTrace_Box(&b->trace, origin, origin, b->mins, maxs,
                    MAPGEN_MASK_PLAYERSOLID, &tr);
    return !tr.allsolid && !tr.startsolid;
}

/* Room above a stance, capped so an open sky column does not produce an
   outlier that swamps every average built on it. */
static uint16_t clearance_above(build_t *b, const float origin[3])
{
    float up[3] = { origin[0], origin[1], origin[2] + 512.0f };
    mapgen_trace_result_t tr;
    MapGenTrace_Box(&b->trace, origin, up, b->mins, b->maxs,
                    MAPGEN_MASK_PLAYERSOLID, &tr);
    /* The trace itself is 512 long, so the result cannot exceed it; the only
       clamp that can ever fire is the one against a negative. */
    float d = tr.endpos[2] - origin[2];
    if (d < 0.0f)
        d = 0.0f;
    return (uint16_t)d;
}

/* --- pass 1: drop through one column ------------------------------------ */

static void scan_column(build_t *b, int32_t ix, int32_t iy, bool include_liquids)
{
    mapgen_space_t *sp = b->space;
    const float half = (float)sp->cell * 0.5f;
    const float x = (float)(sp->base[0] + ix * sp->cell) + half;
    const float y = (float)(sp->base[1] + iy * sp->cell) + half;

    float z = b->world_top;
    uint32_t floors = 0;

    while (z > b->world_bottom && floors < MAPGEN_SPACE_MAX_FLOORS_PER_COLUMN) {
        const float start[3] = { x, y, z };
        const float end[3]   = { x, y, b->world_bottom };

        mapgen_trace_result_t tr;
        MapGenTrace_Box(&b->trace, start, end, b->mins, b->maxs,
                        MAPGEN_MASK_PLAYERSOLID, &tr);

        if (tr.startsolid) {
            /* Inside geometry: sink past it a cell at a time. Bounded by the
               column height, so a solid column terminates rather than spins. */
            z -= (float)sp->cell;
            continue;
        }
        if (tr.fraction >= 1.0f)
            break;                      /* nothing below: out of the world   */

        const float stance[3] = { tr.endpos[0], tr.endpos[1], tr.endpos[2] };
        bool ground = is_ground(&tr);
        bool ducked = false;

        if (ground && !hull_fits(b, stance, b->maxs)) {
            /* Standing does not fit, but Quake II lets a player crouch
               through; the stance is kept and marked rather than lost. */
            ducked = hull_fits(b, stance, b->duck_maxs);
            ground = ducked;
        }

        if (ground) {
            const int32_t contents = MapGenTrace_PointContents(&b->trace, stance);
            const bool liquid = (contents & LIQUID_MASK) != 0;
            if (!liquid || include_liquids) {
                mapgen_space_node_t node;
                memset(&node, 0, sizeof(node));
                node.cell[0] = ix;
                node.cell[1] = iy;
                node.cell[2] = (int32_t)((stance[2] - (float)sp->base[2]) /
                                         (float)sp->cell);
                node.origin[0] = stance[0];
                node.origin[1] = stance[1];
                node.origin[2] = stance[2];
                node.contents = contents;
                node.clearance = clearance_above(b, stance);
                node.region = UINT32_MAX;
                if (liquid)
                    node.flags |= MAPGEN_SPACE_NODE_LIQUID;
                if (contents & HAZARD_MASK)
                    node.flags |= MAPGEN_SPACE_NODE_HAZARD;
                if (ducked)
                    node.flags |= MAPGEN_SPACE_NODE_DUCKED;
                if (!push_node(b, &node))
                    return;
            }
        }

        z = stance[2] - (float)sp->cell;
        floors++;
    }
}

/* --- pass 2: join neighbouring columns ---------------------------------- */

static const int NEIGHBOUR_DX[4] = { 1, -1, 0, 0 };
static const int NEIGHBOUR_DY[4] = { 0, 0, 1, -1 };

/* Step up, move across, drop down. An edge exists only when all three say so.
   The lift is the height the player must gain before moving: a step for
   anything within STEPSIZE, the full rise for a jump. */
static bool motion_is_clear(build_t *b, const mapgen_space_node_t *from,
                            const mapgen_space_node_t *to, float lift)
{
    mapgen_trace_result_t tr;

    const float a[3] = { from->origin[0], from->origin[1], from->origin[2] };
    const float raised[3] = { a[0], a[1], a[2] + lift };
    MapGenTrace_Box(&b->trace, a, raised, b->mins, b->maxs,
                    MAPGEN_MASK_PLAYERSOLID, &tr);
    if (tr.fraction < 1.0f)
        return false;

    const float across[3] = { to->origin[0], to->origin[1], raised[2] };
    MapGenTrace_Box(&b->trace, raised, across, b->mins, b->maxs,
                    MAPGEN_MASK_PLAYERSOLID, &tr);
    if (tr.fraction < 1.0f)
        return false;

    /* And the landing must be the stance we claimed to reach, not some ledge
       on the way down. */
    const float below[3] = { across[0], across[1], to->origin[2] - 1.0f };
    MapGenTrace_Box(&b->trace, across, below, b->mins, b->maxs,
                    MAPGEN_MASK_PLAYERSOLID, &tr);
    if (tr.fraction >= 1.0f || !is_ground(&tr))
        return false;

    const float landed = tr.endpos[2] - to->origin[2];
    return landed > -1.0f && landed < 1.0f;
}

static uint8_t classify(const mapgen_space_node_t *from,
                        const mapgen_space_node_t *to, int32_t rise)
{
    if ((from->flags & MAPGEN_SPACE_NODE_LIQUID) &&
        (to->flags & MAPGEN_SPACE_NODE_LIQUID))
        return MAPGEN_EDGE_SWIM;
    if (rise > MAPGEN_SPACE_STEPSIZE)
        return MAPGEN_EDGE_JUMP;
    if (rise < -MAPGEN_SPACE_STEPSIZE)
        return MAPGEN_EDGE_FALL;
    if (rise != 0)
        return MAPGEN_EDGE_STEP;
    return MAPGEN_EDGE_WALK;
}

static void link_column(build_t *b, uint32_t from_index)
{
    mapgen_space_t *sp = b->space;
    const mapgen_space_node_t from = sp->nodes[from_index];

    for (int n = 0; n < 4; n++) {
        const int32_t nx = from.cell[0] + NEIGHBOUR_DX[n];
        const int32_t ny = from.cell[1] + NEIGHBOUR_DY[n];
        if (nx < 0 || ny < 0 || nx >= sp->span[0] || ny >= sp->span[1])
            continue;

        const uint32_t col = (uint32_t)nx * (uint32_t)sp->span[1] + (uint32_t)ny;
        for (uint32_t j = b->col_first[col]; j < b->col_first[col + 1]; j++) {
            const mapgen_space_node_t *to = &sp->nodes[j];
            const float frise = to->origin[2] - from.origin[2];
            const int32_t rise = (int32_t)(frise < 0 ? frise - 0.5f : frise + 0.5f);

            if (rise > MAPGEN_SPACE_JUMP_RISE)
                continue;
            if (rise < -MAPGEN_SPACE_MAX_FALL)
                continue;

            const float lift = rise > MAPGEN_SPACE_STEPSIZE
                             ? (float)rise + 1.0f
                             : (float)MAPGEN_SPACE_STEPSIZE;
            if (!motion_is_clear(b, &from, to, lift))
                continue;

            mapgen_space_edge_t edge;
            edge.from = from_index;
            edge.to = j;
            edge.rise = rise;
            edge.kind = classify(&from, to, rise);
            if (!push_edge(b, &edge))
                return;
        }
    }
}

/* --- regions ------------------------------------------------------------ */

static uint32_t uf_find(uint32_t *parent, uint32_t i)
{
    while (parent[i] != i) {
        parent[i] = parent[parent[i]];
        i = parent[i];
    }
    return i;
}

static void uf_union(uint32_t *parent, uint32_t a, uint32_t b)
{
    a = uf_find(parent, a);
    b = uf_find(parent, b);
    if (a != b)
        parent[a > b ? a : b] = a < b ? a : b;
}

static bool joins_a_region(uint8_t kind)
{
    /* Only the symmetric motions. A jump up and the fall back down are not the
       same relation, and treating them as one would merge a ledge you can
       leave with a ledge you can return to. */
    return kind == MAPGEN_EDGE_WALK || kind == MAPGEN_EDGE_STEP ||
           kind == MAPGEN_EDGE_SWIM;
}

static bool build_regions(build_t *b)
{
    mapgen_space_t *sp = b->space;
    if (!sp->num_nodes)
        return true;

    b->parent = malloc((size_t)sp->num_nodes * sizeof(uint32_t));
    b->walk_degree = calloc(sp->num_nodes, sizeof(uint32_t));
    if (!b->parent || !b->walk_degree)
        return false;
    for (uint32_t i = 0; i < sp->num_nodes; i++)
        b->parent[i] = i;

    for (uint32_t i = 0; i < sp->num_edges; i++) {
        if (!joins_a_region(sp->edges[i].kind))
            continue;
        uf_union(b->parent, sp->edges[i].from, sp->edges[i].to);
        b->walk_degree[sp->edges[i].from]++;
    }

    /* Relabel by first appearance, so a region id depends on the node order
       and not on how the union-find happened to root its trees. */
    uint32_t *label = malloc((size_t)sp->num_nodes * sizeof(uint32_t));
    if (!label)
        return false;
    for (uint32_t i = 0; i < sp->num_nodes; i++)
        label[i] = UINT32_MAX;

    uint32_t next = 0;
    for (uint32_t i = 0; i < sp->num_nodes; i++) {
        const uint32_t root = uf_find(b->parent, i);
        if (label[root] == UINT32_MAX)
            label[root] = next++;
        sp->nodes[i].region = label[root];
    }
    free(label);

    sp->regions = calloc(next ? next : 1, sizeof(*sp->regions));
    if (!sp->regions)
        return false;
    sp->num_regions = next;

    for (uint32_t r = 0; r < next; r++) {
        sp->regions[r].mins[0] = INT32_MAX;
        sp->regions[r].mins[1] = INT32_MAX;
        sp->regions[r].mins[2] = INT32_MAX;
        sp->regions[r].maxs[0] = INT32_MIN;
        sp->regions[r].maxs[1] = INT32_MIN;
        sp->regions[r].maxs[2] = INT32_MIN;
    }

    for (uint32_t i = 0; i < sp->num_nodes; i++) {
        const mapgen_space_node_t *nd = &sp->nodes[i];
        mapgen_space_region_t *rg = &sp->regions[nd->region];
        rg->nodes++;
        for (int k = 0; k < 3; k++) {
            const int32_t v = (int32_t)(nd->origin[k] < 0 ? nd->origin[k] - 0.5f
                                                          : nd->origin[k] + 0.5f);
            if (v < rg->mins[k]) rg->mins[k] = v;
            if (v > rg->maxs[k]) rg->maxs[k] = v;
        }
        if (nd->flags & MAPGEN_SPACE_NODE_LIQUID)
            rg->liquid_nodes++;
        if (nd->flags & MAPGEN_SPACE_NODE_HAZARD)
            rg->hazard_nodes++;
        if (b->walk_degree[i] <= 2)
            rg->thin_nodes++;
    }
    return true;
}

/* ------------------------------------------------------------------------ */

/*
 * Where the world actually is.
 *
 * The model's own mins/maxs are NOT usable: `2box4.bsp`, `airport2.bsp` and
 * `aqnitro.bsp` all ship with a world model of +-99999 on every axis, which is
 * a compiler's "bounds not computed" sentinel and would ask for 39 million
 * columns. The BSP tree's root node carries the real extents in int16, so it
 * is both trustworthy and inherently bounded; the model's box is used only to
 * tighten it, never to widen it.
 */
static bool world_bounds(const mapgen_bsp_t *bsp, const mapgen_bsp_model_t *world,
                         int32_t lo[3], int32_t hi[3])
{
    if (world->headnode < 0) {
        const uint32_t leafnum = (uint32_t)(-1 - world->headnode);
        const mapgen_bsp_leaf_t *leaf = MapGenBsp_Leaf(bsp, leafnum);
        if (!leaf)
            return false;
        for (int i = 0; i < 3; i++) {
            lo[i] = leaf->mins[i];
            hi[i] = leaf->maxs[i];
        }
    } else {
        const mapgen_bsp_node_t *node = MapGenBsp_Node(bsp, (uint32_t)world->headnode);
        if (!node)
            return false;
        for (int i = 0; i < 3; i++) {
            lo[i] = node->mins[i];
            hi[i] = node->maxs[i];
        }
    }

    for (int i = 0; i < 3; i++) {
        if (world->mins[i] > (float)lo[i] && world->mins[i] < (float)hi[i])
            lo[i] = (int32_t)world->mins[i];
        if (world->maxs[i] < (float)hi[i] && world->maxs[i] > (float)lo[i])
            hi[i] = (int32_t)world->maxs[i];
        if (hi[i] <= lo[i])
            return false;
    }
    return true;
}

static void free_build(build_t *b)
{
    MapGenTrace_Release(&b->trace);
    free(b->col_first);
    free(b->parent);
    free(b->walk_degree);
}

mapgen_space_result_t MapGenSpace_Build(const mapgen_bsp_t *bsp,
                                        const mapgen_space_params_t *params,
                                        mapgen_space_t **out)
{
    if (!bsp || !out)
        return MAPGEN_SPACE_ERR_ARGS;
    *out = NULL;

    mapgen_space_params_t p = params ? *params : MapGenSpace_DefaultParams();
    if (!p.cell)
        p.cell = 32;
    if (p.cell < MAPGEN_SPACE_MIN_CELL || p.cell > MAPGEN_SPACE_MAX_CELL)
        return MAPGEN_SPACE_ERR_CELL_SIZE;

    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    if (!world)
        return MAPGEN_SPACE_ERR_NO_WORLD;

    int32_t lo[3], hi[3];
    if (!world_bounds(bsp, world, lo, hi))
        return MAPGEN_SPACE_ERR_NO_WORLD;

    /* Ceilings are checked against the world's own size BEFORE anything is
       allocated, the same rule the document layer follows. */
    int32_t base[3], span[2];
    for (int i = 0; i < 3; i++)
        base[i] = (lo[i] >= 0 ? lo[i] / p.cell
                              : -((-lo[i] + p.cell - 1) / p.cell)) * p.cell;
    for (int i = 0; i < 2; i++) {
        const int64_t width = (int64_t)hi[i] - base[i];
        if (width <= 0)
            return MAPGEN_SPACE_ERR_NO_WORLD;
        const int64_t cols = (width + p.cell - 1) / p.cell;
        if (cols <= 0 || cols > (int64_t)MAPGEN_SPACE_MAX_COLUMNS)
            return MAPGEN_SPACE_ERR_TOO_LARGE;
        span[i] = (int32_t)cols;
    }
    if ((int64_t)span[0] * span[1] > (int64_t)MAPGEN_SPACE_MAX_COLUMNS)
        return MAPGEN_SPACE_ERR_TOO_LARGE;

    mapgen_space_t *sp = calloc(1, sizeof(*sp));
    if (!sp)
        return MAPGEN_SPACE_ERR_MEMORY;
    sp->cell = p.cell;
    memcpy(sp->base, base, sizeof(base));
    memcpy(sp->span, span, sizeof(span));

    build_t b;
    memset(&b, 0, sizeof(b));
    b.space = sp;
    b.mins[0] = b.mins[1] = -(float)MAPGEN_SPACE_HULL_WIDTH;
    b.mins[2] = (float)MAPGEN_SPACE_HULL_BOTTOM;
    b.maxs[0] = b.maxs[1] = (float)MAPGEN_SPACE_HULL_WIDTH;
    b.maxs[2] = (float)MAPGEN_SPACE_HULL_TOP;
    b.duck_maxs[0] = b.maxs[0];
    b.duck_maxs[1] = b.maxs[1];
    b.duck_maxs[2] = (float)MAPGEN_SPACE_DUCK_TOP;
    b.world_top = (float)hi[2] - 1.0f;
    b.world_bottom = (float)lo[2] + 1.0f;
    b.num_columns = (uint32_t)span[0] * (uint32_t)span[1];

    if (!MapGenTrace_Bind(&b.trace, bsp)) {
        MapGenSpace_Free(sp);
        return MAPGEN_SPACE_ERR_MEMORY;
    }

    b.col_first = calloc((size_t)b.num_columns + 1, sizeof(uint32_t));
    if (!b.col_first) {
        free_build(&b);
        MapGenSpace_Free(sp);
        return MAPGEN_SPACE_ERR_MEMORY;
    }

    for (int32_t ix = 0; ix < span[0]; ix++) {
        for (int32_t iy = 0; iy < span[1]; iy++) {
            const uint32_t col = (uint32_t)ix * (uint32_t)span[1] + (uint32_t)iy;
            b.col_first[col] = sp->num_nodes;
            scan_column(&b, ix, iy, p.include_liquids);
            /* The column was walked top down; the canonical order is bottom
               up, and pass 2 relies on it being stable. */
            const uint32_t lo = b.col_first[col], hi = sp->num_nodes;
            for (uint32_t a = lo, z = hi; a + 1 < z; a++, z--) {
                const mapgen_space_node_t tmp = sp->nodes[a];
                sp->nodes[a] = sp->nodes[z - 1];
                sp->nodes[z - 1] = tmp;
            }
        }
    }
    b.col_first[b.num_columns] = sp->num_nodes;

    for (uint32_t i = 0; i < sp->num_nodes; i++)
        link_column(&b, i);

    for (uint32_t i = 0; i < sp->num_edges; i++)
        sp->kind_counts[sp->edges[i].kind]++;

    if (!build_regions(&b)) {
        free_build(&b);
        MapGenSpace_Free(sp);
        return MAPGEN_SPACE_ERR_MEMORY;
    }

    const bool overflowed = b.overflowed;
    const bool exhausted = b.out_of_memory;
    free_build(&b);
    if (exhausted) {
        MapGenSpace_Free(sp);
        return MAPGEN_SPACE_ERR_MEMORY;
    }
    if (overflowed) {
        MapGenSpace_Free(sp);
        return MAPGEN_SPACE_ERR_TOO_LARGE;
    }

    *out = sp;
    return MAPGEN_SPACE_OK;
}

void MapGenSpace_Free(mapgen_space_t *space)
{
    if (!space)
        return;
    free(space->nodes);
    free(space->edges);
    free(space->regions);
    free(space);
}

/* ------------------------------------------------------------------------ */

uint32_t MapGenSpace_NumNodes(const mapgen_space_t *s)   { return s ? s->num_nodes : 0; }
uint32_t MapGenSpace_NumEdges(const mapgen_space_t *s)   { return s ? s->num_edges : 0; }
uint32_t MapGenSpace_NumRegions(const mapgen_space_t *s) { return s ? s->num_regions : 0; }
int32_t  MapGenSpace_CellSize(const mapgen_space_t *s)   { return s ? s->cell : 0; }

uint32_t MapGenSpace_NumEdgesOfKind(const mapgen_space_t *s, mapgen_edge_kind_t k)
{
    if (!s || (unsigned)k >= MAPGEN_EDGE_KIND_COUNT)
        return 0;
    return s->kind_counts[k];
}

const mapgen_space_node_t *MapGenSpace_Node(const mapgen_space_t *s, uint32_t i)
{
    return (s && i < s->num_nodes) ? &s->nodes[i] : NULL;
}

const mapgen_space_edge_t *MapGenSpace_Edge(const mapgen_space_t *s, uint32_t i)
{
    return (s && i < s->num_edges) ? &s->edges[i] : NULL;
}

const mapgen_space_region_t *MapGenSpace_Region(const mapgen_space_t *s, uint32_t i)
{
    return (s && i < s->num_regions) ? &s->regions[i] : NULL;
}

uint32_t MapGenSpace_LargestRegion(const mapgen_space_t *s)
{
    if (!s || !s->num_regions)
        return UINT32_MAX;
    uint32_t best = 0;
    for (uint32_t i = 1; i < s->num_regions; i++) {
        /* Ties go to the lower index, so the answer does not depend on the
           iteration order. */
        if (s->regions[i].nodes > s->regions[best].nodes)
            best = i;
    }
    return best;
}

/* ------------------------------------------------------------------------ */

typedef struct {
    char  *out;
    size_t capacity;
    size_t needed;
} sink_t;

static void sink_str(sink_t *s, const char *text)
{
    const size_t n = strlen(text);
    if (s->out && s->needed < s->capacity) {
        const size_t room = s->capacity - 1 - s->needed;
        memcpy(s->out + s->needed, text, n < room ? n : room);
    }
    s->needed += n;
}

static void sink_i64(sink_t *s, int64_t v)
{
    char buf[24];
    size_t n = 0;
    uint64_t m;
    if (v < 0) {
        buf[n++] = '-';
        m = (uint64_t)(-(v + 1)) + 1u;
    } else {
        m = (uint64_t)v;
    }
    char tmp[24];
    size_t t = 0;
    if (!m) {
        tmp[t++] = '0';
    } else {
        while (m) {
            tmp[t++] = (char)('0' + (m % 10u));
            m /= 10u;
        }
    }
    while (t)
        buf[n++] = tmp[--t];
    buf[n] = '\0';
    sink_str(s, buf);
}

/* Positions are quantized to whole units before they are rendered. A stance is
   the result of a trace, so its last bits carry no meaning worth digesting -
   and a digest that changed with them would be useless for comparing two
   runs. */
static void sink_unit(sink_t *s, float v)
{
    sink_i64(s, (int64_t)(v < 0 ? v - 0.5f : v + 0.5f));
}

size_t MapGenSpace_CanonicalText(const mapgen_space_t *sp, char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!sp) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    sink_str(&s, "cell="); sink_i64(&s, sp->cell); sink_str(&s, "\n");
    sink_str(&s, "base=");
    sink_i64(&s, sp->base[0]); sink_str(&s, ",");
    sink_i64(&s, sp->base[1]); sink_str(&s, ",");
    sink_i64(&s, sp->base[2]); sink_str(&s, "\n");
    sink_str(&s, "span=");
    sink_i64(&s, sp->span[0]); sink_str(&s, ",");
    sink_i64(&s, sp->span[1]); sink_str(&s, "\n");

    sink_str(&s, "nodes="); sink_i64(&s, sp->num_nodes); sink_str(&s, "\n");
    for (uint32_t i = 0; i < sp->num_nodes; i++) {
        const mapgen_space_node_t *n = &sp->nodes[i];
        sink_str(&s, "n=");
        sink_unit(&s, n->origin[0]); sink_str(&s, ",");
        sink_unit(&s, n->origin[1]); sink_str(&s, ",");
        sink_unit(&s, n->origin[2]); sink_str(&s, ",");
        sink_i64(&s, n->contents); sink_str(&s, ",");
        sink_i64(&s, n->clearance); sink_str(&s, ",");
        sink_i64(&s, n->flags); sink_str(&s, ",");
        sink_i64(&s, n->region); sink_str(&s, "\n");
    }

    sink_str(&s, "edges="); sink_i64(&s, sp->num_edges); sink_str(&s, "\n");
    for (uint32_t i = 0; i < sp->num_edges; i++) {
        const mapgen_space_edge_t *e = &sp->edges[i];
        sink_str(&s, "e=");
        sink_i64(&s, e->from); sink_str(&s, ",");
        sink_i64(&s, e->to); sink_str(&s, ",");
        sink_i64(&s, e->rise); sink_str(&s, ",");
        sink_str(&s, MapGenSpace_EdgeKindName((mapgen_edge_kind_t)e->kind));
        sink_str(&s, "\n");
    }

    sink_str(&s, "regions="); sink_i64(&s, sp->num_regions); sink_str(&s, "\n");
    for (uint32_t i = 0; i < sp->num_regions; i++) {
        const mapgen_space_region_t *r = &sp->regions[i];
        sink_str(&s, "r=");
        sink_i64(&s, r->nodes); sink_str(&s, ",");
        sink_i64(&s, r->mins[0]); sink_str(&s, ",");
        sink_i64(&s, r->mins[1]); sink_str(&s, ",");
        sink_i64(&s, r->mins[2]); sink_str(&s, ",");
        sink_i64(&s, r->maxs[0]); sink_str(&s, ",");
        sink_i64(&s, r->maxs[1]); sink_str(&s, ",");
        sink_i64(&s, r->maxs[2]); sink_str(&s, ",");
        sink_i64(&s, r->liquid_nodes); sink_str(&s, ",");
        sink_i64(&s, r->hazard_nodes); sink_str(&s, ",");
        sink_i64(&s, r->thin_nodes); sink_str(&s, "\n");
    }

    for (int k = 0; k < MAPGEN_EDGE_KIND_COUNT; k++) {
        sink_str(&s, "kind=");
        sink_str(&s, MapGenSpace_EdgeKindName((mapgen_edge_kind_t)k));
        sink_str(&s, ",");
        sink_i64(&s, sp->kind_counts[k]);
        sink_str(&s, "\n");
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenSpace_CanonicalDigest(const mapgen_space_t *sp)
{
    const size_t needed = MapGenSpace_CanonicalText(sp, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenSpace_CanonicalText(sp, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;      /* FNV-1a 64 offset basis   */
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
