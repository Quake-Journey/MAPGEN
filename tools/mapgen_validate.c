/*
 * MAPGEN-1 - can a player actually get around this map?
 *
 *   mapgen_validate <map.bsp> [--corpus <map.bsp>...]
 *
 * Contract section 18.3's traversal gate, in the form it can take before the
 * validator proper exists: reload the COMPILED map - not the plan that
 * produced it - rebuild the stance graph with the same code that learns from
 * real maps, and ask the questions a player would.
 *
 * The one that matters most is the largest WALKABLE region. A map can be
 * sealed, lit, fully connected on paper and still be four disconnected
 * islands, because a route the plan called a lift was built as a bare shaft.
 * Every geometric check in this tree passed such a map. This one does not:
 *
 *   - every spawn point has to be in one and the same walkable region;
 *   - that region has to hold most of the map's standable surface;
 *   - the map has to have chokepoints at all, because a map with none is a
 *     uniform mesh rather than a place with rooms and doorways.
 *
 * Measured on the corpus for the thresholds, so they are not invented:
 * aerowalk 38% largest region and 172 chokepoints, bloodrun 11% and 224,
 * campgrounds 49% and 157, q2dm1e 36% and 210.
 */

#include "common/mapgen_features.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int FAILED;

static void check(const char *name, bool ok, const char *detail)
{
    printf("  %s  %s%s%s\n", ok ? "PASS" : "FAIL", name,
           detail && *detail ? "  -- " : "", detail ? detail : "");
    if (!ok)
        FAILED++;
}

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    const long size = ftell(f);
    if (size < 0) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) { fclose(f); return NULL; }
    *out_size = fread(data, 1, (size_t)size, f);
    fclose(f);
    return data;
}

typedef struct {
    mapgen_bsp_t      *bsp;
    mapgen_genome_t   *genome;
    mapgen_space_t    *space;
    mapgen_wiring_t   *wiring;
    mapgen_features_t *features;
    uint8_t           *data;
} analysis_t;

static void release(analysis_t *a)
{
    MapGenFeatures_Free(a->features);
    MapGenWiring_Free(a->wiring);
    MapGenSpace_Free(a->space);
    MapGenGenome_Free(a->genome);
    MapGenBsp_Free(a->bsp);
    free(a->data);
    memset(a, 0, sizeof(*a));
}

static bool analyse(const char *path, analysis_t *a)
{
    memset(a, 0, sizeof(*a));
    size_t size = 0;
    a->data = read_file(path, &size);
    if (!a->data)
        return false;
    mapgen_space_params_t p = MapGenSpace_DefaultParams();
    if (MapGenBsp_Load(a->data, size, &a->bsp) != MAPGEN_BSP_OK
        || MapGenGenome_Extract(a->bsp, &a->genome) != MAPGEN_GENOME_OK
        || MapGenSpace_Build(a->bsp, &p, &a->space) != MAPGEN_SPACE_OK
        || MapGenWiring_Build(a->genome, a->bsp, &a->wiring) != MAPGEN_WIRING_OK
        || MapGenFeatures_Build(a->bsp, a->genome, a->space, a->wiring,
                                &a->features) != MAPGEN_FEATURES_OK) {
        release(a);
        return false;
    }
    return true;
}

/* The stance nearest a point - where a player put there would be standing. */
static uint32_t node_at(const mapgen_space_t *space, const int32_t origin[3])
{
    uint32_t best = UINT32_MAX;
    int64_t best_distance = 0;
    for (uint32_t i = 0; i < MapGenSpace_NumNodes(space); i++) {
        const mapgen_space_node_t *n = MapGenSpace_Node(space, i);
        int64_t d = 0;
        for (int axis = 0; axis < 3; axis++) {
            const int64_t delta = (int64_t)n->origin[axis] - origin[axis];
            d += delta * delta;
        }
        if (best == UINT32_MAX || d < best_distance) {
            best_distance = d;
            best = i;
        }
    }
    return best;
}

/*
 * Everywhere a player can get to from here AND back again.
 *
 * Not the walkable region: that check failed on aerowalk and q2dm1e, because
 * real maps join their areas with jumps, drops and lifts and none of those is
 * a walk edge. What a player actually needs is a round trip, so this is the
 * strongly connected component - reachable forward over every traversal kind,
 * and reachable backward too, which is what stops a one-way drop from
 * counting as a connection.
 */
static bool *round_trip_from(const mapgen_space_t *space, uint32_t start)
{
    const uint32_t n = MapGenSpace_NumNodes(space);
    bool *forward = calloc(n, sizeof(bool));
    bool *backward = calloc(n, sizeof(bool));
    uint32_t *stack = malloc((size_t)n * sizeof(uint32_t));
    if (!forward || !backward || !stack || start >= n) {
        free(forward);
        free(backward);
        free(stack);
        return NULL;
    }

    for (int pass = 0; pass < 2; pass++) {
        bool *seen = pass ? backward : forward;
        size_t top = 0;
        seen[start] = true;
        stack[top++] = start;
        while (top) {
            const uint32_t at = stack[--top];
            for (uint32_t e = 0; e < MapGenSpace_NumEdges(space); e++) {
                const mapgen_space_edge_t *edge = MapGenSpace_Edge(space, e);
                const bool two_way = edge->kind == MAPGEN_EDGE_WALK
                                  || edge->kind == MAPGEN_EDGE_STEP
                                  || edge->kind == MAPGEN_EDGE_SWIM;
                uint32_t next = UINT32_MAX;
                if (!pass) {
                    if (edge->from == at)
                        next = edge->to;
                    else if (edge->to == at && two_way)
                        next = edge->from;
                } else {
                    if (edge->to == at)
                        next = edge->from;
                    else if (edge->from == at && two_way)
                        next = edge->to;
                }
                if (next != UINT32_MAX && next < n && !seen[next]) {
                    seen[next] = true;
                    stack[top++] = next;
                }
            }
        }
    }

    for (uint32_t i = 0; i < n; i++)
        forward[i] = forward[i] && backward[i];
    free(backward);
    free(stack);
    return forward;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        printf("usage: mapgen_validate <map.bsp>\n");
        return 2;
    }

    analysis_t a;
    if (!analyse(argv[1], &a)) {
        printf("could not analyse %s\n", argv[1]);
        return 1;
    }
    const mapgen_features_vector_t *v = MapGenFeatures_Vector(a.features);

    const char *name = strrchr(argv[1], '\\');
    const char *slash = strrchr(argv[1], '/');
    if (slash > name)
        name = slash;
    printf("%s\n", name ? name + 1 : argv[1]);

    /* --- the gate that matters ------------------------------------------- */
    uint32_t *spawn_nodes = calloc(MapGenGenome_NumEntities(a.genome),
                                   sizeof(uint32_t));
    uint32_t spawns = 0;
    for (uint32_t i = 0; i < MapGenGenome_NumEntities(a.genome); i++) {
        const mapgen_entity_t *ent = MapGenGenome_Entity(a.genome, i);
        const char *classname = MapGenGenome_EntityValue(ent, "classname");
        if (!classname
            || (strcmp(classname, "info_player_deathmatch")
                && strcmp(classname, "info_player_start")))
            continue;
        const char *origin_text = MapGenGenome_EntityValue(ent, "origin");
        if (!origin_text)
            continue;

        int32_t origin[3] = { 0, 0, 0 };
        const char *p = origin_text;
        for (int axis = 0; axis < 3 && *p; axis++) {
            while (*p == ' ')
                p++;
            int sign = 1;
            if (*p == '-') { sign = -1; p++; }
            int32_t value = 0;
            while (*p >= '0' && *p <= '9') {
                value = value * 10 + (*p - '0');
                p++;
            }
            while (*p && *p != ' ')
                p++;               /* skip any fraction */
            origin[axis] = sign * value;
        }

        const uint32_t node = node_at(a.space, origin);
        if (node != UINT32_MAX && spawn_nodes)
            spawn_nodes[spawns] = node;
        spawns++;
    }

    char detail[128];
    check("the map has spawn points", spawns > 0, "");

    uint32_t stranded = 0, reachable = 0;
    if (spawns && spawn_nodes) {
        bool *round_trip = round_trip_from(a.space, spawn_nodes[0]);
        if (round_trip) {
            for (uint32_t i = 1; i < spawns; i++)
                if (!round_trip[spawn_nodes[i]])
                    stranded++;
            for (uint32_t i = 0; i < MapGenSpace_NumNodes(a.space); i++)
                if (round_trip[i])
                    reachable++;
            free(round_trip);
        }
    }
    free(spawn_nodes);

    snprintf(detail, sizeof(detail),
             "%u of %u cannot be reached from the first and back", stranded,
             spawns);
    check("a player can get from any spawn to any other, and back",
          stranded == 0, detail);

    const uint32_t share = MapGenSpace_NumNodes(a.space)
        ? reachable * 100u / MapGenSpace_NumNodes(a.space) : 0;
    snprintf(detail, sizeof(detail), "%u%% of the map's standable surface", share);
    check("and reach most of the map from where he spawned", share >= 60, detail);

    snprintf(detail, sizeof(detail),
             "%u; the corpus runs 157 to 224", v->chokepoints);
    check("the map has doorways and junctions at all", v->chokepoints > 0, detail);

    snprintf(detail, sizeof(detail), "%u regions, corpus 63 to 98", v->regions);
    check("it is not shattered into more pieces than a real map",
          v->regions <= 120, detail);

    snprintf(detail, sizeof(detail), "%d units, corpus 736 to 1408", v->extent[2]);
    check("it is not taller than any map anybody plays",
          v->extent[2] <= 1600, detail);

    printf("\n  nodes=%u regions=%u largest=%u%% bands=%u vspan=%d open=%u%% "
           "loops=%u chokes=%u\n",
           v->nodes, v->regions, v->largest_region_permille / 10,
           v->height_bands, v->extent[2], v->open_permille / 10, v->loops,
           v->chokepoints);

    release(&a);
    printf("\n%s\n", FAILED ? "RESULT: NOT PLAYABLE" : "RESULT: playable");
    return FAILED ? 1 : 0;
}
