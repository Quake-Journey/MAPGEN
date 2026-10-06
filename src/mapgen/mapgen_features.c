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
 * MAPGEN-1 - the deterministic per-map feature vector.
 *
 * Four passes over the candidate graph: shape, connectivity, visibility and
 * entity binding. Every number that leaves this file is an integer, and every
 * sample is chosen by index arithmetic rather than by a generator, so the same
 * map always produces the same vector.
 */

#include "common/mapgen_features.h"
#include "common/mapgen_trace.h"

#include <stdlib.h>
#include <string.h>

struct mapgen_features_s {
    mapgen_features_vector_t v;
    uint32_t *entity_node;
    uint32_t  num_entities;
};

const char *MapGenFeatures_ResultName(mapgen_features_result_t r)
{
    switch (r) {
    case MAPGEN_FEATURES_OK:         return "OK";
    case MAPGEN_FEATURES_ERR_ARGS:   return "ERR_ARGS";
    case MAPGEN_FEATURES_ERR_MEMORY: return "ERR_MEMORY";
    }
    return "ERR_UNKNOWN";
}

/* Integer square root, so a length never depends on a libm build. */
static uint32_t isqrt32(uint64_t v)
{
    if (v == 0)
        return 0;
    uint64_t x = v, y = (x + 1) / 2;
    while (y < x) {
        x = y;
        y = (x + v / x) / 2;
    }
    return (uint32_t)x;
}

static uint32_t distance_units(const float a[3], const float b[3])
{
    int64_t total = 0;
    for (int i = 0; i < 3; i++) {
        const int64_t d = (int64_t)(a[i] - b[i]);
        total += d * d;
    }
    return isqrt32((uint64_t)total);
}

/* C truncates towards zero, which would make the band straddling z = 0 twice
   as tall as every other band. Height bands must all be the same size or the
   count means nothing. */
static int32_t floor_div(int32_t value, int32_t divisor)
{
    const int32_t q = value / divisor;
    return (value % divisor != 0 && (value < 0) != (divisor < 0)) ? q - 1 : q;
}

static int cmp_u32(const void *a, const void *b)
{
    const uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

/* ------------------------------------------------------------------------ */
/* The undirected walk graph, which is what chokepoints, bridges and loops    */
/* are all defined over.                                                     */

typedef struct {
    uint32_t *first;      /* CSR offsets, one per node plus a tail          */
    uint32_t *to;         /* neighbour                                      */
    uint32_t *edge_id;    /* which undirected edge this arc belongs to      */
    uint32_t  num_edges;  /* undirected edges, after deduplication          */
    uint32_t  num_arcs;
} undirected_t;

static void undirected_free(undirected_t *g)
{
    free(g->first);
    free(g->to);
    free(g->edge_id);
    memset(g, 0, sizeof(*g));
}

static bool joins(uint8_t kind)
{
    return kind == MAPGEN_EDGE_WALK || kind == MAPGEN_EDGE_STEP ||
           kind == MAPGEN_EDGE_SWIM;
}

/*
 * The space graph is directed and emits a symmetric motion from both ends, so
 * the same walkable connection arrives twice. Counting it twice would inflate
 * the cyclomatic number and hide every bridge, so each unordered pair becomes
 * exactly one undirected edge, keyed on the lower index.
 */
static bool build_undirected(const mapgen_space_t *space, undirected_t *g)
{
    const uint32_t n = MapGenSpace_NumNodes(space);
    const uint32_t m = MapGenSpace_NumEdges(space);
    memset(g, 0, sizeof(*g));
    if (!n)
        return true;

    g->first = calloc((size_t)n + 1, sizeof(uint32_t));
    if (!g->first)
        return false;

    /* Pass one: how many arcs leave each node, counting a pair once. */
    for (uint32_t i = 0; i < m; i++) {
        const mapgen_space_edge_t *e = MapGenSpace_Edge(space, i);
        if (!joins(e->kind) || e->from == e->to)
            continue;
        if (e->from > e->to)
            continue;                   /* the twin will be counted instead */
        g->first[e->from + 1]++;
        g->first[e->to + 1]++;
    }
    for (uint32_t i = 0; i < n; i++)
        g->first[i + 1] += g->first[i];
    g->num_arcs = g->first[n];

    g->to = g->num_arcs ? malloc((size_t)g->num_arcs * sizeof(uint32_t)) : NULL;
    g->edge_id = g->num_arcs ? malloc((size_t)g->num_arcs * sizeof(uint32_t)) : NULL;
    if (g->num_arcs && (!g->to || !g->edge_id))
        return false;

    uint32_t *fill = calloc(n, sizeof(uint32_t));
    if (!fill)
        return false;
    for (uint32_t i = 0; i < m; i++) {
        const mapgen_space_edge_t *e = MapGenSpace_Edge(space, i);
        if (!joins(e->kind) || e->from == e->to || e->from > e->to)
            continue;
        const uint32_t id = g->num_edges++;
        uint32_t slot = g->first[e->from] + fill[e->from]++;
        g->to[slot] = e->to;
        g->edge_id[slot] = id;
        slot = g->first[e->to] + fill[e->to]++;
        g->to[slot] = e->from;
        g->edge_id[slot] = id;
    }
    free(fill);
    return true;
}

/*
 * Articulation points and bridges, by depth-first lowpoint. Iterative: a
 * component with 25 000 stances is deeper than any stack wants.
 */
typedef struct {
    uint32_t nodes_seen;
    uint32_t components;
    uint32_t articulation;
    uint32_t bridges;
} connectivity_t;

static bool analyse_connectivity(const undirected_t *g, uint32_t n, connectivity_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!n)
        return true;

    uint32_t *disc = malloc((size_t)n * sizeof(uint32_t));
    uint32_t *low = malloc((size_t)n * sizeof(uint32_t));
    uint32_t *parent_edge = malloc((size_t)n * sizeof(uint32_t));
    uint32_t *stack = malloc((size_t)n * sizeof(uint32_t));
    uint32_t *cursor = malloc((size_t)n * sizeof(uint32_t));
    uint32_t *children = calloc(n, sizeof(uint32_t));
    uint8_t  *is_articulation = calloc(n, sizeof(uint8_t));
    if (!disc || !low || !parent_edge || !stack || !cursor || !children ||
        !is_articulation) {
        free(disc); free(low); free(parent_edge); free(stack); free(cursor);
        free(children); free(is_articulation);
        return false;
    }
    for (uint32_t i = 0; i < n; i++)
        disc[i] = UINT32_MAX;

    uint32_t timer = 0;

    for (uint32_t root = 0; root < n; root++) {
        if (disc[root] != UINT32_MAX)
            continue;
        out->components++;

        uint32_t top = 0;
        stack[0] = root;
        cursor[0] = g->first[root];
        parent_edge[root] = UINT32_MAX;
        disc[root] = low[root] = timer++;

        while (true) {
            const uint32_t v = stack[top];
            if (cursor[top] < g->first[v + 1]) {
                const uint32_t slot = cursor[top]++;
                const uint32_t w = g->to[slot];
                const uint32_t id = g->edge_id[slot];
                if (id == parent_edge[v])
                    continue;           /* the edge we arrived by, not a twin */
                if (disc[w] == UINT32_MAX) {
                    children[v]++;
                    parent_edge[w] = id;
                    disc[w] = low[w] = timer++;
                    stack[++top] = w;
                    cursor[top] = g->first[w];
                } else if (disc[w] < low[v]) {
                    low[v] = disc[w];
                }
                continue;
            }

            if (!top)
                break;
            const uint32_t child = v;
            top--;
            const uint32_t parent = stack[top];
            if (low[child] < low[parent])
                low[parent] = low[child];
            if (low[child] > disc[parent])
                out->bridges++;
            /* The root is an articulation point only if it has two or more
               children in the DFS tree; every other node if some child cannot
               reach above it. */
            if (parent != root && low[child] >= disc[parent])
                is_articulation[parent] = 1;
        }
        if (children[root] > 1)
            is_articulation[root] = 1;
    }

    for (uint32_t i = 0; i < n; i++) {
        out->nodes_seen++;
        if (is_articulation[i])
            out->articulation++;
    }

    free(disc); free(low); free(parent_edge); free(stack); free(cursor);
    free(children); free(is_articulation);
    return true;
}

/* ------------------------------------------------------------------------ */

static void measure_shape(const mapgen_space_t *space, mapgen_features_vector_t *v,
                          uint32_t *clearances)
{
    const uint32_t n = MapGenSpace_NumNodes(space);
    v->nodes = n;
    v->regions = MapGenSpace_NumRegions(space);
    v->edges = MapGenSpace_NumEdges(space);
    for (uint32_t k = 0; k < MAPGEN_EDGE_KIND_COUNT; k++)
        v->edges_of_kind[k] = MapGenSpace_NumEdgesOfKind(space, (mapgen_edge_kind_t)k);

    const uint32_t largest = MapGenSpace_LargestRegion(space);
    const mapgen_space_region_t *rg = MapGenSpace_Region(space, largest);
    v->largest_region_nodes = rg ? rg->nodes : 0;
    v->largest_region_permille = n ? (uint32_t)((uint64_t)v->largest_region_nodes * 1000u / n) : 0;

    if (!n)
        return;

    int32_t lo[3] = { INT32_MAX, INT32_MAX, INT32_MAX };
    int32_t hi[3] = { INT32_MIN, INT32_MIN, INT32_MIN };
    int32_t band_lo = INT32_MAX, band_hi = INT32_MIN;

    for (uint32_t i = 0; i < n; i++) {
        const mapgen_space_node_t *nd = MapGenSpace_Node(space, i);
        clearances[i] = nd->clearance;
        for (int k = 0; k < 3; k++) {
            const int32_t x = (int32_t)(nd->origin[k] < 0 ? nd->origin[k] - 0.5f
                                                          : nd->origin[k] + 0.5f);
            if (x < lo[k]) lo[k] = x;
            if (x > hi[k]) hi[k] = x;
        }
        if (nd->flags & MAPGEN_SPACE_NODE_LIQUID)
            v->liquid_nodes++;
        if (nd->flags & MAPGEN_SPACE_NODE_HAZARD)
            v->hazard_nodes++;
    }
    for (int k = 0; k < 3; k++)
        v->extent[k] = hi[k] - lo[k];
    v->vertical_span = (uint32_t)v->extent[2];
    v->hazard_permille = (uint32_t)((uint64_t)v->hazard_nodes * 1000u / n);

    /* Height bands: how many 64-unit slices contain a stance. A flat arena and
       a tower with the same vertical span are not the same map. */
    band_lo = floor_div(lo[2], MAPGEN_FEATURES_HEIGHT_BAND);
    band_hi = floor_div(hi[2], MAPGEN_FEATURES_HEIGHT_BAND);
    if (band_hi >= band_lo) {
        const uint32_t span = (uint32_t)(band_hi - band_lo) + 1u;
        uint8_t *bands = calloc(span, sizeof(uint8_t));
        if (bands) {
            for (uint32_t i = 0; i < n; i++) {
                const mapgen_space_node_t *nd = MapGenSpace_Node(space, i);
                const int32_t z = (int32_t)(nd->origin[2] < 0 ? nd->origin[2] - 0.5f
                                                              : nd->origin[2] + 0.5f);
                const int32_t band = floor_div(z, MAPGEN_FEATURES_HEIGHT_BAND);
                if (band >= band_lo && band <= band_hi)
                    bands[band - band_lo] = 1;
            }
            for (uint32_t i = 0; i < span; i++)
                v->height_bands += bands[i];
            free(bands);
        }
    }

    qsort(clearances, n, sizeof(uint32_t), cmp_u32);
    v->median_clearance = clearances[n / 2];

    /* The probe is exactly 512 long, so a clearance of 512 means "nothing was
       hit" rather than "the ceiling is 512 up". */
    uint32_t capped = 0;
    for (uint32_t i = 0; i < n; i++)
        if (clearances[i] >= 512)
            capped++;
    v->open_permille = (uint32_t)((uint64_t)capped * 1000u / n);
}

/* ------------------------------------------------------------------------ */

/*
 * Visibility. Sampled by fixed stride, never randomly: the same map must
 * always choose the same pairs, or two Training runs would disagree about a
 * map neither of them changed.
 */
static void measure_sight(const mapgen_bsp_t *bsp, const mapgen_space_t *space,
                          mapgen_features_vector_t *v)
{
    const uint32_t n = MapGenSpace_NumNodes(space);
    if (n < 2)
        return;

    mapgen_trace_context_t ctx = { 0 };
    if (!MapGenTrace_Bind(&ctx, bsp))
        return;

    const uint32_t observers = n < MAPGEN_FEATURES_MAX_OBSERVERS
                             ? n : MAPGEN_FEATURES_MAX_OBSERVERS;
    const uint32_t observer_stride = n / observers;
    const uint32_t partner_stride = n / MAPGEN_FEATURES_PARTNERS
                                  ? n / MAPGEN_FEATURES_PARTNERS : 1;

    uint64_t open_length_total = 0;

    for (uint32_t o = 0; o < observers; o++) {
        const uint32_t i = o * observer_stride;
        const mapgen_space_node_t *a = MapGenSpace_Node(space, i);
        if (!a)
            continue;
        const float eye_a[3] = {
            a->origin[0], a->origin[1],
            a->origin[2] + (float)MAPGEN_FEATURES_VIEWHEIGHT,
        };

        for (uint32_t p = 0; p < MAPGEN_FEATURES_PARTNERS; p++) {
            const uint32_t j = (i + (p + 1) * partner_stride) % n;
            if (j == i)
                continue;
            const mapgen_space_node_t *b = MapGenSpace_Node(space, j);
            if (!b)
                continue;
            const float eye_b[3] = {
                b->origin[0], b->origin[1],
                b->origin[2] + (float)MAPGEN_FEATURES_VIEWHEIGHT,
            };

            static const float zero[3] = { 0.0f, 0.0f, 0.0f };
            mapgen_trace_result_t tr;
            MapGenTrace_Box(&ctx, eye_a, eye_b, zero, zero,
                            MAPGEN_TRACE_SOLID | MAPGEN_TRACE_WINDOW, &tr);

            v->sight_pairs++;
            if (tr.fraction >= 1.0f) {
                const uint32_t d = distance_units(eye_a, eye_b);
                v->sight_open++;
                open_length_total += d;
                if (d > v->max_sight_length)
                    v->max_sight_length = d;
            }
        }
    }

    MapGenTrace_Release(&ctx);

    if (v->sight_pairs)
        v->cover_permille = 1000u -
            (uint32_t)((uint64_t)v->sight_open * 1000u / v->sight_pairs);
    if (v->sight_open)
        v->mean_sight_length = (uint32_t)(open_length_total / v->sight_open);
}

/* ------------------------------------------------------------------------ */

/*
 * The corpus's lighting, per contract 7.7.
 *
 * The intensity is the `light` key, then `_light`, then the compiler's own
 * default of 300 (`lightmap.c:1548-1552`) - which is what an entity carrying
 * neither key will actually be given, so it is what the corpus really has.
 *
 * A median rather than a mean: the corpus is full of outliers - one of these
 * maps ranges from -500 to 1200 - and one 1200 should not drag the number a
 * generator samples.
 */
/*
 * One `_color` value, packed 0xRRGGBB.
 *
 * The corpus writes these in BOTH conventions - "255 222 173" and
 * "0.3 0.3 0.3" - so the reader accepts both and tells them apart the only way
 * available: a value with a decimal point, or every component at most 1, is
 * the 0..1 form. That is not a guess about intent, it is what the two formats
 * look like.
 */
static uint32_t parse_colour(const char *text)
{
    int32_t whole[3] = { 0, 0, 0 };
    uint32_t frac[3] = { 0, 0, 0 };
    uint32_t frac_digits[3] = { 0, 0, 0 };
    const char *p = text;

    for (int axis = 0; axis < 3; axis++) {
        while (*p == ' ')
            p++;
        bool any = false;
        while (*p >= '0' && *p <= '9') {
            whole[axis] = whole[axis] * 10 + (*p - '0');
            any = true;
            p++;
        }
        if (*p == '.') {
            p++;
            while (*p >= '0' && *p <= '9') {
                if (frac_digits[axis] < 6) {
                    frac[axis] = frac[axis] * 10u + (uint32_t)(*p - '0');
                    frac_digits[axis]++;
                }
                any = true;
                p++;
            }
        }
        if (!any)
            return 0;
        while (*p && *p != ' ')
            p++;
    }

    const bool unit_scale = whole[0] <= 1 && whole[1] <= 1 && whole[2] <= 1;
    uint32_t packed = 0;
    for (int axis = 0; axis < 3; axis++) {
        int64_t value;
        if (unit_scale) {
            /* whole + frac/10^digits, times 255, in integers throughout. */
            uint32_t scale = 1;
            for (uint32_t d = 0; d < frac_digits[axis]; d++)
                scale *= 10u;
            value = (int64_t)whole[axis] * 255
                  + (scale ? (int64_t)frac[axis] * 255 / scale : 0);
        } else {
            value = whole[axis];
        }
        if (value < 0)
            value = 0;
        if (value > 255)
            value = 255;
        packed = (packed << 8) | (uint32_t)value;
    }
    return packed;
}

/* The four commonest colours the map's lights carry, most common first. */
static void learn_light_colours(const mapgen_genome_t *genome,
                                uint32_t *out)
{
    uint32_t seen[32] = { 0 };
    uint32_t hits[32] = { 0 };
    uint32_t distinct = 0;

    for (uint32_t i = 0; i < MapGenGenome_NumEntities(genome); i++) {
        const mapgen_entity_t *ent = MapGenGenome_Entity(genome, i);
        const char *classname = MapGenGenome_EntityValue(ent, "classname");
        if (!classname || strncmp(classname, "light", 5))
            continue;
        const char *text = MapGenGenome_EntityValue(ent, "_color");
        if (!text)
            text = MapGenGenome_EntityValue(ent, "color");
        if (!text)
            continue;
        const uint32_t packed = parse_colour(text);
        if (!packed)
            continue;

        bool found = false;
        for (uint32_t k = 0; k < distinct; k++) {
            if (seen[k] == packed) {
                hits[k]++;
                found = true;
                break;
            }
        }
        if (!found && distinct < 32) {
            seen[distinct] = packed;
            hits[distinct] = 1;
            distinct++;
        }
    }

    for (uint32_t slot = 0; slot < MAPGEN_FEATURES_LIGHT_COLOURS; slot++) {
        uint32_t best = 0, at = distinct;
        for (uint32_t k = 0; k < distinct; k++) {
            if (hits[k] > best) {
                best = hits[k];
                at = k;
            }
        }
        if (at >= distinct)
            break;
        out[slot] = seen[at];
        hits[at] = 0;
    }
}

static void learn_lighting(const mapgen_genome_t *genome, uint32_t *count,
                           uint32_t *median, uint32_t *lower, uint32_t *upper)
{
    *count = 0;
    *median = 0;
    *lower = 0;
    *upper = 0;

    const uint32_t entities = MapGenGenome_NumEntities(genome);
    int32_t *values = entities ? calloc(entities, sizeof(int32_t)) : NULL;
    if (!values)
        return;

    uint32_t n = 0;
    for (uint32_t i = 0; i < entities; i++) {
        const mapgen_entity_t *ent = MapGenGenome_Entity(genome, i);
        const char *classname = MapGenGenome_EntityValue(ent, "classname");
        if (!classname || strncmp(classname, "light", 5))
            continue;

        const char *text = MapGenGenome_EntityValue(ent, "light");
        if (!text)
            text = MapGenGenome_EntityValue(ent, "_light");

        int32_t intensity = 300;            /* the compiler's own default */
        if (text) {
            const char *p = text;
            bool negative = false;
            if (*p == '-') {
                negative = true;
                p++;
            }
            int32_t v = 0;
            bool digits = false;
            while (*p >= '0' && *p <= '9') {
                v = v * 10 + (*p - '0');
                digits = true;
                p++;
            }
            if (digits)
                intensity = negative ? -v : v;
        }
        values[n++] = intensity;
    }

    if (n) {
        /* Insertion sort: n is one map's light count, in the hundreds. */
        for (uint32_t i = 1; i < n; i++) {
            const int32_t v = values[i];
            uint32_t j = i;
            while (j && values[j - 1] > v) {
                values[j] = values[j - 1];
                j--;
            }
            values[j] = v;
        }
        const int32_t middle = values[n / 2];
        const int32_t low = values[n / 4];
        const int32_t high = values[(3 * n) / 4];
        *count = n;
        *median = middle > 0 ? (uint32_t)middle : 0;
        /*
         * The quartiles, so a generator can draw a SPREAD rather than stamp
         * one number on every light it places. Clamped at zero because the
         * corpus contains negative lights - campgrounds has a -500 - and a
         * negative intensity is a subtractive light, which is a motif of its
         * own and not something to sample an ordinary light from.
         */
        *lower = low > 0 ? (uint32_t)low : 0;
        *upper = high > 0 ? (uint32_t)high : *median;
    }
    free(values);
}

static void measure_entities(const mapgen_genome_t *genome,
                             const mapgen_space_t *space,
                             const mapgen_wiring_t *wiring,
                             mapgen_features_t *f)
{
    mapgen_features_vector_t *v = &f->v;
    const uint32_t count = MapGenGenome_NumEntities(genome);
    const uint32_t n = MapGenSpace_NumNodes(space);

    uint32_t item_count = 0;
    float (*item_origins)[3] = count ? malloc((size_t)count * sizeof(*item_origins)) : NULL;

    for (uint32_t i = 0; i < count; i++) {
        f->entity_node[i] = UINT32_MAX;
        const mapgen_entity_t *ent = MapGenGenome_Entity(genome, i);
        const mapgen_wiring_entity_t *we = MapGenWiring_Entity(wiring, i);
        if (!ent || !ent->has_origin)
            continue;
        v->positioned_entities++;

        /* The nearest stance, but only if one is genuinely near. A "nearest"
           node 900 units away would be an answer that means nothing. */
        uint32_t best = UINT32_MAX;
        uint32_t best_d = UINT32_MAX;
        for (uint32_t k = 0; k < n; k++) {
            const mapgen_space_node_t *nd = MapGenSpace_Node(space, k);
            const int32_t dx = (int32_t)(nd->origin[0] - ent->origin[0]);
            const int32_t dy = (int32_t)(nd->origin[1] - ent->origin[1]);
            const int32_t dz = (int32_t)(nd->origin[2] - ent->origin[2]);
            if (dx > MAPGEN_FEATURES_BIND_RADIUS_XY || dx < -MAPGEN_FEATURES_BIND_RADIUS_XY ||
                dy > MAPGEN_FEATURES_BIND_RADIUS_XY || dy < -MAPGEN_FEATURES_BIND_RADIUS_XY ||
                dz > MAPGEN_FEATURES_BIND_RADIUS_Z  || dz < -MAPGEN_FEATURES_BIND_RADIUS_Z)
                continue;
            const uint32_t d = isqrt32((uint64_t)((int64_t)dx * dx +
                                                  (int64_t)dy * dy +
                                                  (int64_t)dz * dz));
            /* Ties go to the lower index, so the answer does not depend on
               the order the stances happen to be in. */
            if (d < best_d) {
                best_d = d;
                best = k;
            }
        }
        f->entity_node[i] = best;

        const bool bound = best != UINT32_MAX;
        if (bound)
            v->bound_entities++;
        else
            v->unbound_entities++;

        const uint32_t roles = we ? we->roles : 0;
        if (roles & MAPGEN_ENTROLE_ITEM) {
            if (bound)
                v->items_bound++;
            else
                v->items_unbound++;
            if (item_origins) {
                memcpy(item_origins[item_count], ent->origin, sizeof(ent->origin));
                item_count++;
            }
        }
        if (roles & (MAPGEN_ENTROLE_SPAWN_DM | MAPGEN_ENTROLE_SPAWN_SP | MAPGEN_ENTROLE_SPAWN_COOP)) {
            if (bound)
                v->spawns_bound++;
            else
                v->spawns_unbound++;
        }
    }

    /* How far an item is from the next one: an arena where every pickup is in
       one corner is a different map from one where they are spread out. */
    if (item_origins && item_count > 1) {
        uint64_t total = 0;
        for (uint32_t i = 0; i < item_count; i++) {
            uint32_t nearest = UINT32_MAX;
            for (uint32_t j = 0; j < item_count; j++) {
                if (j == i)
                    continue;
                const uint32_t d = distance_units(item_origins[i], item_origins[j]);
                if (d < nearest)
                    nearest = d;
            }
            total += nearest;
        }
        v->mean_item_separation = (uint32_t)(total / item_count);
    }
    free(item_origins);

    learn_lighting(genome, &v->lights, &v->light_median,
                   &v->light_lower, &v->light_upper);
    learn_light_colours(genome, v->light_colours);

    /*
     * And how much of the map is open to the sky. Counted over brush SIDES
     * rather than faces, because that is what the genome records and because a
     * side is there whether or not the compiler drew it.
     */
    {
        uint64_t sky = 0, sides = 0;
        for (uint32_t i = 0; i < MapGenGenome_NumMaterials(genome); i++) {
            const mapgen_material_t *m = MapGenGenome_Material(genome, i);
            sides += m->brushside_refs;
            if (m->surface_flags & MAPGEN_SURF_SKY)
                sky += m->brushside_refs;
        }
        v->sky_permille = sides ? (uint32_t)(sky * 1000u / sides) : 0;
    }
}

/* ------------------------------------------------------------------------ */

mapgen_features_result_t MapGenFeatures_Build(const mapgen_bsp_t *bsp,
                                              const mapgen_genome_t *genome,
                                              const mapgen_space_t *space,
                                              const mapgen_wiring_t *wiring,
                                              mapgen_features_t **out)
{
    if (!bsp || !genome || !space || !wiring || !out)
        return MAPGEN_FEATURES_ERR_ARGS;
    *out = NULL;

    mapgen_features_t *f = calloc(1, sizeof(*f));
    if (!f)
        return MAPGEN_FEATURES_ERR_MEMORY;
    f->num_entities = MapGenGenome_NumEntities(genome);
    if (f->num_entities) {
        f->entity_node = malloc((size_t)f->num_entities * sizeof(uint32_t));
        if (!f->entity_node) {
            MapGenFeatures_Free(f);
            return MAPGEN_FEATURES_ERR_MEMORY;
        }
    }

    const uint32_t n = MapGenSpace_NumNodes(space);
    uint32_t *clearances = n ? malloc((size_t)n * sizeof(uint32_t)) : NULL;
    if (n && !clearances) {
        MapGenFeatures_Free(f);
        return MAPGEN_FEATURES_ERR_MEMORY;
    }
    measure_shape(space, &f->v, clearances);
    free(clearances);

    undirected_t g;
    if (!build_undirected(space, &g)) {
        undirected_free(&g);
        MapGenFeatures_Free(f);
        return MAPGEN_FEATURES_ERR_MEMORY;
    }
    connectivity_t conn;
    if (!analyse_connectivity(&g, n, &conn)) {
        undirected_free(&g);
        MapGenFeatures_Free(f);
        return MAPGEN_FEATURES_ERR_MEMORY;
    }
    f->v.chokepoints = conn.articulation;
    f->v.bridges = conn.bridges;
    /* The cyclomatic number: independent cycles in the walkable graph, which
       is "route redundancy" once it is made precise. */
    f->v.loops = g.num_edges + conn.components >= n
               ? g.num_edges + conn.components - n : 0;
    f->v.bridge_permille = g.num_edges
                         ? (uint32_t)((uint64_t)conn.bridges * 1000u / g.num_edges) : 0;
    f->v.mean_walk_degree_milli = n
                                   ? (uint32_t)((uint64_t)g.num_arcs * 1000u / n) : 0;
    undirected_free(&g);

    measure_sight(bsp, space, &f->v);
    measure_entities(genome, space, wiring, f);

    *out = f;
    return MAPGEN_FEATURES_OK;
}

void MapGenFeatures_Free(mapgen_features_t *f)
{
    if (!f)
        return;
    free(f->entity_node);
    free(f);
}

const mapgen_features_vector_t *MapGenFeatures_Vector(const mapgen_features_t *f)
{
    return f ? &f->v : NULL;
}

uint32_t MapGenFeatures_EntityNode(const mapgen_features_t *f, uint32_t entity)
{
    return (f && f->entity_node && entity < f->num_entities)
         ? f->entity_node[entity] : UINT32_MAX;
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

static void row(sink_t *s, const char *name, int64_t value)
{
    sink_str(s, name);
    sink_str(s, "=");
    sink_i64(s, value);
    sink_str(s, "\n");
}

size_t MapGenFeatures_CanonicalText(const mapgen_features_t *f, char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!f) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }
    const mapgen_features_vector_t *v = &f->v;

    row(&s, "nodes", v->nodes);
    row(&s, "regions", v->regions);
    row(&s, "largest_region_nodes", v->largest_region_nodes);
    row(&s, "largest_region_permille", v->largest_region_permille);
    row(&s, "extent_x", v->extent[0]);
    row(&s, "extent_y", v->extent[1]);
    row(&s, "extent_z", v->extent[2]);
    row(&s, "median_clearance", v->median_clearance);
    row(&s, "open_permille", v->open_permille);
    row(&s, "vertical_span", v->vertical_span);
    row(&s, "height_bands", v->height_bands);

    row(&s, "edges", v->edges);
    for (uint32_t k = 0; k < MAPGEN_EDGE_KIND_COUNT; k++) {
        sink_str(&s, "edges_");
        sink_str(&s, MapGenSpace_EdgeKindName((mapgen_edge_kind_t)k));
        sink_str(&s, "=");
        sink_i64(&s, v->edges_of_kind[k]);
        sink_str(&s, "\n");
    }
    row(&s, "mean_walk_degree_milli", v->mean_walk_degree_milli);
    row(&s, "chokepoints", v->chokepoints);
    row(&s, "bridges", v->bridges);
    row(&s, "loops", v->loops);
    row(&s, "bridge_permille", v->bridge_permille);

    row(&s, "sight_pairs", v->sight_pairs);
    row(&s, "sight_open", v->sight_open);
    row(&s, "cover_permille", v->cover_permille);
    row(&s, "mean_sight_length", v->mean_sight_length);
    row(&s, "max_sight_length", v->max_sight_length);

    row(&s, "liquid_nodes", v->liquid_nodes);
    row(&s, "hazard_nodes", v->hazard_nodes);
    row(&s, "hazard_permille", v->hazard_permille);

    row(&s, "positioned_entities", v->positioned_entities);
    row(&s, "bound_entities", v->bound_entities);
    row(&s, "unbound_entities", v->unbound_entities);
    row(&s, "items_bound", v->items_bound);
    row(&s, "items_unbound", v->items_unbound);
    row(&s, "spawns_bound", v->spawns_bound);
    row(&s, "spawns_unbound", v->spawns_unbound);
    row(&s, "mean_item_separation", v->mean_item_separation);
    row(&s, "lights", v->lights);
    row(&s, "light_median", v->light_median);
    row(&s, "light_lower", v->light_lower);
    row(&s, "light_upper", v->light_upper);
    for (uint32_t i = 0; i < MAPGEN_FEATURES_LIGHT_COLOURS; i++) {
        char key[24] = "light_colour_0";
        key[13] = (char)('0' + i);
        row(&s, key, v->light_colours[i]);
    }
    row(&s, "sky_permille", v->sky_permille);

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenFeatures_CanonicalDigest(const mapgen_features_t *f)
{
    const size_t needed = MapGenFeatures_CanonicalText(f, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenFeatures_CanonicalText(f, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
