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
 * MAPGEN-1 - the topology graph.
 *
 * Built in three passes, in this order and for this reason:
 *
 *   1. a spanning skeleton of TWO-WAY routes, so the map is connected and stays
 *      connected whatever else happens;
 *   2. loop routes, until the graph has the redundancy the goal asks for;
 *   3. one-way routes as extras only, because a drop or a teleporter added to
 *      an already strongly connected graph cannot strand anybody.
 *
 * Doing it the other way round - routes first, connectivity repaired afterwards
 * - is how a generator ends up with a repair loop that sometimes fails.
 */

#include "common/mapgen_topology.h"
#include "common/mapgen_wiring.h"

#include <stdlib.h>
#include <string.h>

/* ---- the one table ------------------------------------------------------- */

/*
 * Every route kind, the learned role it needs, the control that gates it, and
 * the band change it can make. Contract 14's "None is absolute" and contract
 * 15's "never emit an unlearned motif" are the same lookup here, so they
 * cannot drift apart.
 */
typedef struct {
    const char *name;
    const char *control;        /* NULL: not gated - see `walk` below        */
    uint32_t    role;           /* 0: pure geometry, nothing to learn        */
    int32_t     min_delta;
    int32_t     max_delta;
    bool        one_way;
} route_rule_t;

static const route_rule_t ROUTE_RULES[MAPGEN_ROUTE_KIND_COUNT] = {
    /* WALK is the fallback and has no control: with every other kind set to
       None a map still has to be connected, and a corridor is what is left. */
    [MAPGEN_ROUTE_WALK]     = { "walk",     NULL,                  0,
                               0, 0, false },
    [MAPGEN_ROUTE_RAMP]     = { "ramp",     "arch_stairs_ramps",   0,
                               1, 1, false },
    [MAPGEN_ROUTE_JUMP]     = { "jump",     "arch_jumps_drops",    0,
                               1, 1, false },
    /* A drop is one-way: you can fall down it and not climb back. */
    [MAPGEN_ROUTE_DROP]     = { "drop",     "arch_jumps_drops",    0,
                               -3, -1, true },
    [MAPGEN_ROUTE_SWIM]     = { "swim",     "arch_water",          0,
                               -1, 1, false },
    [MAPGEN_ROUTE_DOOR]     = { "door",     "arch_doors_buttons",  MAPGEN_ENTROLE_DOOR,
                               0, 0, false },
    [MAPGEN_ROUTE_LIFT]     = { "lift",     "arch_lifts",          MAPGEN_ENTROLE_PLAT,
                               1, 3, false },
    [MAPGEN_ROUTE_TRAIN]    = { "train",    "arch_trains",         MAPGEN_ENTROLE_TRAIN,
                               1, 3, false },
    /* A teleporter has a destination and no return leg unless one is placed. */
    [MAPGEN_ROUTE_TELEPORT] = { "teleport", "arch_teleporters",    MAPGEN_ENTROLE_TELEPORTER,
                               -7, 7, true },
    [MAPGEN_ROUTE_PUSH]     = { "push",     "arch_jump_pads",      MAPGEN_ENTROLE_PUSH,
                               1, 2, false },
};

const char *MapGenTopology_RouteName(mapgen_route_kind_t kind)
{
    return kind < MAPGEN_ROUTE_KIND_COUNT ? ROUTE_RULES[kind].name : "unknown";
}

uint32_t MapGenTopology_RouteRole(mapgen_route_kind_t kind)
{
    return kind < MAPGEN_ROUTE_KIND_COUNT ? ROUTE_RULES[kind].role : 0;
}

const char *MapGenTopology_RouteControl(mapgen_route_kind_t kind)
{
    return kind < MAPGEN_ROUTE_KIND_COUNT ? ROUTE_RULES[kind].control : NULL;
}

bool MapGenTopology_RouteMovesThePlayer(mapgen_route_kind_t kind)
{
    /*
     * A pad throws you, a train carries you where it is going, a teleporter
     * takes you somewhere you did not walk to. A lift and a door move, but
     * they move at your request and leave you standing where you were.
     */
    return kind == MAPGEN_ROUTE_PUSH || kind == MAPGEN_ROUTE_TRAIN;
}

bool MapGenTopology_RouteIsOneWay(mapgen_route_kind_t kind)
{
    return kind < MAPGEN_ROUTE_KIND_COUNT && ROUTE_RULES[kind].one_way;
}

const char *MapGenTopology_ResultName(mapgen_topology_result_t r)
{
    switch (r) {
    case MAPGEN_TOPOLOGY_OK:                  return "OK";
    case MAPGEN_TOPOLOGY_ERR_ARGS:            return "ERR_ARGS";
    case MAPGEN_TOPOLOGY_ERR_MEMORY:          return "ERR_MEMORY";
    case MAPGEN_TOPOLOGY_ERR_NO_SAMPLES:      return "ERR_NO_SAMPLES";
    case MAPGEN_TOPOLOGY_ERR_UNLEARNED_MOTIF: return "ERR_UNLEARNED_MOTIF";
    case MAPGEN_TOPOLOGY_ERR_TOO_MANY_NODES:  return "ERR_TOO_MANY_NODES";
    case MAPGEN_TOPOLOGY_ERR_TOO_MANY_ROUTES:  return "ERR_TOO_MANY_LINKS";
    }
    return "ERR_UNKNOWN";
}

/* ---- the model ----------------------------------------------------------- */

struct mapgen_topology_s {
    mapgen_topology_node_t *nodes;
    uint32_t                num_nodes;
    mapgen_topology_route_t *routes;
    uint32_t                num_routes;
    uint32_t                bands;
    char                    sample[65];
};

/*
 * How often a kind is chosen, by the level its control resolved to. `None` is
 * absent from this table on purpose: it is not a small weight, it is a
 * prohibition, and it is handled before any drawing happens.
 */
static uint32_t level_weight(int32_t level)
{
    switch (level) {
    case 1: return 1;                       /* Low       */
    case 2: return 3;                       /* Balanced  */
    case 3: return 8;                       /* High      */
    default: return 0;
    }
}


static uint32_t clamp_u32(int64_t v, uint32_t lo, uint32_t hi)
{
    if (v < (int64_t)lo)
        return lo;
    if (v > (int64_t)hi)
        return hi;
    return (uint32_t)v;
}

static bool route_exists(const mapgen_topology_t *t, uint32_t a, uint32_t b)
{
    for (uint32_t i = 0; i < t->num_routes; i++) {
        const mapgen_topology_route_t *e = &t->routes[i];
        if ((e->from == a && e->to == b) || (e->from == b && e->to == a))
            return true;
    }
    return false;
}

static bool push_route(mapgen_topology_t *t, uint32_t from, uint32_t to,
                      uint32_t kind)
{
    if (t->num_routes >= MAPGEN_TOPOLOGY_MAX_ROUTES)
        return false;
    void *grown = realloc(t->routes,
                          (size_t)(t->num_routes + 1) * sizeof(*t->routes));
    if (!grown)
        return false;
    t->routes = grown;
    t->routes[t->num_routes].from = from;
    t->routes[t->num_routes].to = to;
    t->routes[t->num_routes].kind = kind;
    t->num_routes++;
    return true;
}

/* ---- building ------------------------------------------------------------ */

typedef struct {
    /*
     * How often a kind may be chosen. Zero is the prohibition and there is no
     * second flag beside it: `MapGenRandom_Weighted` never returns an index
     * whose weight is zero, which its own guard proves, so contract 14's
     * absolute None and "weight zero" are the same fact. Two names for one
     * state is how the two drift apart.
     */
    uint32_t weight[MAPGEN_ROUTE_KIND_COUNT];
} palette_t;

/*
 * What may be emitted at all, decided once, before anything is drawn.
 *
 * Two reasons a kind can be unavailable, and they are not the same: the user
 * said None, or the corpus never contained one. The second is reported as a
 * conflict only when the user actually asked for it - a corpus without
 * teleporters and a user who did not want any is not a conflict.
 */
static mapgen_topology_result_t build_palette(const mapgen_mix_t *model,
                                              const mapgen_recipe_t *recipe,
                                              palette_t *p,
                                              const char **conflict)
{
    memset(p, 0, sizeof(*p));

    for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
        const route_rule_t *rule = &ROUTE_RULES[k];
        if (!rule->control) {
            p->weight[k] = 4;               /* WALK, the fallback */
            continue;
        }

        const int32_t level = MapGenRecipe_ResolvedValue(recipe, rule->control, 2);
        if (level <= 0) {
            p->weight[k] = 0;               /* None is absolute */
            continue;
        }

        if (rule->role && !MapGenMix_RoleIsLearned(model, rule->role)) {
            /* Asked for, never learned. Contract 14 wants the exact conflict
               named, not the fact that one exists. */
            if (conflict)
                *conflict = rule->control;
            return MAPGEN_TOPOLOGY_ERR_UNLEARNED_MOTIF;
        }

        p->weight[k] = level_weight(level);
    }
    return MAPGEN_TOPOLOGY_OK;
}

/* The kinds that can join two nodes whose bands differ by `delta`. */
static uint32_t kinds_for_delta(const palette_t *p, int32_t delta,
                                bool two_way_only,
                                uint32_t *weights)
{
    uint32_t total = 0;
    for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
        const route_rule_t *rule = &ROUTE_RULES[k];
        weights[k] = 0;
        if (!p->weight[k])
            continue;
        if (two_way_only && rule->one_way)
            continue;
        if (delta < rule->min_delta || delta > rule->max_delta)
            continue;
        weights[k] = p->weight[k];
        total += weights[k];
    }
    return total;
}

/* How many independent loops the goal wants. */
static uint32_t loop_target(mapgen_goal_t goal, uint32_t nodes)
{
    switch (goal) {
    case MAPGEN_GOAL_SINGLE_PLAYER:
        return 1;                           /* one optional branch at least  */
    case MAPGEN_GOAL_DUEL:
        return nodes / 3u + 1u;             /* duel control loops            */
    case MAPGEN_GOAL_TDM:
    case MAPGEN_GOAL_FFA:
    case MAPGEN_GOAL_MIX:
    default:
        return nodes / 4u + 1u;
    }
}

mapgen_topology_result_t MapGenTopology_Build(const mapgen_mix_t *model,
                                              const mapgen_recipe_t *recipe,
                                              uint32_t attempt,
                                              const char **conflict,
                                              mapgen_topology_t **out)
{
    if (conflict)
        *conflict = NULL;
    if (!model || !recipe || !out)
        return MAPGEN_TOPOLOGY_ERR_ARGS;
    *out = NULL;
    if (!MapGenMix_NumSamples(model))
        return MAPGEN_TOPOLOGY_ERR_NO_SAMPLES;

    palette_t palette;
    const mapgen_topology_result_t gated =
        build_palette(model, recipe, &palette, conflict);
    if (gated != MAPGEN_TOPOLOGY_OK)
        return gated;

    mapgen_random_t rng;
    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,
                        MAPGEN_RANDOM_TOPOLOGY);

    /* --- sized from a map the corpus actually contained -------------------- */
    const uint32_t sample = MapGenMix_DrawSample(model, &rng);
    if (sample >= MapGenMix_NumSamples(model))
        return MAPGEN_TOPOLOGY_ERR_NO_SAMPLES;

    const int64_t learned_bands =
        MapGenMix_SampleValue(model, sample, MAPGEN_MIX_STAT_HEIGHT_BANDS);
    const int64_t learned_largest =
        MapGenMix_SampleValue(model, sample, MAPGEN_MIX_STAT_LARGEST_REGION_PERMILLE);

    /*
     * How many AREAS the map has, from the map-scale control.
     *
     * This used to be the learned `regions` figure scaled by the control, and
     * that was a misreading of my own statistic: `regions` counts connected
     * components of the stance graph - aerowalk has 63 - not rooms. Taking it
     * for a room count built forty small boxes where the corpus has a dozen
     * places, which is most of what "narrow corridors instead of arenas"
     * meant. Contract 14 puts the count under Map scale; the learned sample
     * still decides how BIG each one is.
     */
    const int32_t scale = MapGenRecipe_ResolvedValue(recipe, "map_scale", 1);
    /*
     * The world is +/-4096 and a cell is 1536, which leaves five cells on each
     * axis - twenty-five places a room can stand. Asking for twenty-two of
     * them made Very Large fail its first embedding and find one only on a
     * later attempt; these counts fit the grid they have to be placed in.
     */
    static const uint32_t AREAS[4] = { 6, 10, 14, 18 };
    const uint32_t nodes = clamp_u32(AREAS[scale >= 0 && scale < 4 ? scale : 1],
                                     MAPGEN_TOPOLOGY_MIN_NODES,
                                     MAPGEN_TOPOLOGY_MAX_NODES);
    /* The learned region count is no longer the room count, but it is still
       what the map is SIZED from, so it stays in the record. */

    const int32_t verticality = MapGenRecipe_ResolvedValue(recipe, "arch_verticality", 2);
    uint32_t bands = clamp_u32(learned_bands, 1, MAPGEN_TOPOLOGY_MAX_BANDS);
    if (verticality <= 0)
        bands = 1;
    else if (verticality == 1)
        bands = bands < 2 ? bands : 2;
    else if (verticality >= 3)
        bands = clamp_u32((int64_t)bands + 2, 1, MAPGEN_TOPOLOGY_MAX_BANDS);

    mapgen_topology_t *t = calloc(1, sizeof(*t));
    if (!t)
        return MAPGEN_TOPOLOGY_ERR_MEMORY;
    t->bands = bands;
    t->nodes = calloc(nodes, sizeof(*t->nodes));
    if (!t->nodes) {
        MapGenTopology_Free(t);
        return MAPGEN_TOPOLOGY_ERR_MEMORY;
    }
    t->num_nodes = nodes;

    const char *source = MapGenMix_SampleSource(model, sample);
    if (source)
        memcpy(t->sample, source, sizeof(t->sample) - 1);

    /* The largest region is the learned number; the rest share what is left.
       Stated that way in the report, too: one of these is measured and the
       others are a consequence of it. */
    t->nodes[0].band = 0;
    t->nodes[0].size_permille = clamp_u32(learned_largest, 1, 1000);
    const uint32_t remainder = 1000u - t->nodes[0].size_permille;
    for (uint32_t i = 1; i < nodes; i++)
        t->nodes[i].size_permille = nodes > 1 ? remainder / (nodes - 1) : 0;

    /* --- pass 1: a two-way spanning skeleton ------------------------------- */
    uint32_t weights[MAPGEN_ROUTE_KIND_COUNT];
    for (uint32_t i = 1; i < nodes; i++) {
        const uint32_t j = MapGenRandom_Below(&rng, i);

        /*
         * The partner is chosen FIRST and the new node's band follows from the
         * kind that was drawn. Choosing the band first and then hunting for a
         * kind that fits is what produces the case where nothing fits and the
         * builder has to give up or repair.
         */
        uint32_t candidates[MAPGEN_ROUTE_KIND_COUNT];
        uint32_t total = 0;
        for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
            candidates[k] = 0;
            if (!palette.weight[k] || ROUTE_RULES[k].one_way)
                continue;
            /* Reachable band for this kind from j, inside the band count. */
            const int64_t lo = (int64_t)t->nodes[j].band + ROUTE_RULES[k].min_delta;
            const int64_t hi = (int64_t)t->nodes[j].band + ROUTE_RULES[k].max_delta;
            if (hi < 0 || lo > (int64_t)bands - 1)
                continue;
            candidates[k] = palette.weight[k];
            total += candidates[k];
        }
        if (!total) {
            /* Only WALK can always apply, and WALK is never forbidden. */
            candidates[MAPGEN_ROUTE_WALK] = 1;
            total = 1;
        }

        const uint32_t kind = MapGenRandom_Weighted(&rng, candidates,
                                                    MAPGEN_ROUTE_KIND_COUNT);
        const route_rule_t *rule = &ROUTE_RULES[kind];
        int64_t lo = (int64_t)t->nodes[j].band + rule->min_delta;
        int64_t hi = (int64_t)t->nodes[j].band + rule->max_delta;
        if (lo < 0)
            lo = 0;
        if (hi > (int64_t)bands - 1)
            hi = (int64_t)bands - 1;
        if (hi < lo)
            hi = lo;
        t->nodes[i].band = (uint32_t)MapGenRandom_Range(&rng, (int32_t)lo,
                                                        (int32_t)hi);

        if (!push_route(t, j, i, kind)) {
            MapGenTopology_Free(t);
            return MAPGEN_TOPOLOGY_ERR_MEMORY;
        }
    }

    /* --- pass 2: loops, so a route has an alternative ---------------------- */
    const uint32_t loops = loop_target(MapGenRecipe_Goal(recipe), nodes);
    uint32_t added = 0;
    for (uint32_t tries = 0; added < loops && tries < loops * 64u + 256u; tries++) {
        const uint32_t a = MapGenRandom_Below(&rng, nodes);
        const uint32_t b = MapGenRandom_Below(&rng, nodes);
        if (a == b || route_exists(t, a, b))
            continue;
        const int32_t delta = (int32_t)t->nodes[b].band - (int32_t)t->nodes[a].band;
        if (!kinds_for_delta(&palette, delta, true, weights))
            continue;
        const uint32_t kind = MapGenRandom_Weighted(&rng, weights,
                                                    MAPGEN_ROUTE_KIND_COUNT);
        if (kind >= MAPGEN_ROUTE_KIND_COUNT)
            continue;
        if (!push_route(t, a, b, kind)) {
            MapGenTopology_Free(t);
            return MAPGEN_TOPOLOGY_ERR_MEMORY;
        }
        added++;
    }

    /* --- pass 3: one-way shortcuts, as extras only ------------------------- */
    uint32_t one_way_weight = 0;
    for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++)
        if (ROUTE_RULES[k].one_way)
            one_way_weight += palette.weight[k];
    if (one_way_weight) {
        const uint32_t want = nodes / 6u;
        uint32_t placed = 0;
        for (uint32_t tries = 0; placed < want && tries < want * 64u + 128u; tries++) {
            const uint32_t a = MapGenRandom_Below(&rng, nodes);
            const uint32_t b = MapGenRandom_Below(&rng, nodes);
            if (a == b || route_exists(t, a, b))
                continue;
            const int32_t delta = (int32_t)t->nodes[b].band - (int32_t)t->nodes[a].band;
            uint32_t only_one_way[MAPGEN_ROUTE_KIND_COUNT];
            uint32_t total = 0;
            for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
                only_one_way[k] = 0;
                if (!ROUTE_RULES[k].one_way || !palette.weight[k])
                    continue;
                if (delta < ROUTE_RULES[k].min_delta || delta > ROUTE_RULES[k].max_delta)
                    continue;
                only_one_way[k] = palette.weight[k];
                total += only_one_way[k];
            }
            if (!total)
                continue;
            const uint32_t kind = MapGenRandom_Weighted(&rng, only_one_way,
                                                        MAPGEN_ROUTE_KIND_COUNT);
            if (kind >= MAPGEN_ROUTE_KIND_COUNT)
                continue;
            if (!push_route(t, a, b, kind)) {
                MapGenTopology_Free(t);
                return MAPGEN_TOPOLOGY_ERR_MEMORY;
            }
            placed++;
        }
    }

    *out = t;
    return MAPGEN_TOPOLOGY_OK;
}

void MapGenTopology_Free(mapgen_topology_t *t)
{
    if (!t)
        return;
    free(t->nodes);
    free(t->routes);
    free(t);
}

/* ---- accessors ----------------------------------------------------------- */

uint32_t MapGenTopology_NumNodes(const mapgen_topology_t *t)
{
    return t ? t->num_nodes : 0;
}

uint32_t MapGenTopology_NumRoutes(const mapgen_topology_t *t)
{
    return t ? t->num_routes : 0;
}

const mapgen_topology_node_t *MapGenTopology_Node(const mapgen_topology_t *t,
                                                  uint32_t index)
{
    return (t && index < t->num_nodes) ? &t->nodes[index] : NULL;
}

const mapgen_topology_route_t *MapGenTopology_Route(const mapgen_topology_t *t,
                                                  uint32_t index)
{
    return (t && index < t->num_routes) ? &t->routes[index] : NULL;
}

const char *MapGenTopology_SampleSource(const mapgen_topology_t *t)
{
    return t ? t->sample : NULL;
}

uint32_t MapGenTopology_NumRoutesOfKind(const mapgen_topology_t *t,
                                       mapgen_route_kind_t kind)
{
    if (!t)
        return 0;
    uint32_t n = 0;
    for (uint32_t i = 0; i < t->num_routes; i++)
        if (t->routes[i].kind == (uint32_t)kind)
            n++;
    return n;
}

uint32_t MapGenTopology_CyclomaticNumber(const mapgen_topology_t *t)
{
    if (!t || !t->num_nodes)
        return 0;

    /*
     * Counted over the TWO-WAY subgraph only.
     *
     * A drop you cannot climb back up is a shortcut, not an alternative route,
     * and counting it here would let a graph with no loops at all report
     * redundancy. The two-way subgraph is also the one the loop pass builds
     * and the one the skeleton spans, so E - V + 1 is well defined on it.
     */
    uint32_t two_way = 0;
    for (uint32_t i = 0; i < t->num_routes; i++)
        if (!ROUTE_RULES[t->routes[i].kind].one_way)
            two_way++;

    return two_way + 1u > t->num_nodes ? two_way + 1u - t->num_nodes : 0u;
}

/* ---- canonical form ------------------------------------------------------ */

typedef struct {
    char  *out;
    size_t capacity;
    size_t needed;
} sink_t;

static void put(sink_t *s, const char *text)
{
    const size_t n = strlen(text);
    if (s->out && s->needed < s->capacity) {
        const size_t room = s->capacity - 1 - s->needed;
        memcpy(s->out + s->needed, text, n < room ? n : room);
    }
    s->needed += n;
}

static void put_u64(sink_t *s, uint64_t v)
{
    char buf[24], tmp[24];
    size_t n = 0, t = 0;
    if (!v) {
        tmp[t++] = '0';
    } else {
        while (v) {
            tmp[t++] = (char)('0' + (v % 10u));
            v /= 10u;
        }
    }
    while (t)
        buf[n++] = tmp[--t];
    buf[n] = '\0';
    put(s, buf);
}

size_t MapGenTopology_CanonicalText(const mapgen_topology_t *t, char *out,
                                    size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!t) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    put(&s, "sample=");
    put(&s, t->sample);
    put(&s, "\nbands=");
    put_u64(&s, t->bands);
    put(&s, "\nnodes=");
    put_u64(&s, t->num_nodes);
    put(&s, "\n");
    for (uint32_t i = 0; i < t->num_nodes; i++) {
        put(&s, "n=");
        put_u64(&s, t->nodes[i].band);
        put(&s, ",");
        put_u64(&s, t->nodes[i].size_permille);
        put(&s, "\n");
    }
    put(&s, "routes=");
    put_u64(&s, t->num_routes);
    put(&s, "\n");
    for (uint32_t i = 0; i < t->num_routes; i++) {
        put(&s, "e=");
        put_u64(&s, t->routes[i].from);
        put(&s, ",");
        put_u64(&s, t->routes[i].to);
        put(&s, ",");
        put(&s, MapGenTopology_RouteName((mapgen_route_kind_t)t->routes[i].kind));
        put(&s, "\n");
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenTopology_CanonicalDigest(const mapgen_topology_t *t)
{
    const size_t needed = MapGenTopology_CanonicalText(t, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenTopology_CanonicalText(t, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
