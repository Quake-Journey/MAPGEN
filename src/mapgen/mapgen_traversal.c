/*
 * MapGenTraversal - see inc/common/mapgen_traversal.h.
 *
 * Two sweeps over the same directed graph, in opposite directions. What a
 * player can reach from a spawn, and what can reach a spawn. A stance in the
 * first set and not the second is somewhere you can go and not come back from,
 * which is the defect this Module exists to name.
 */

#include "common/mapgen_traversal.h"
#include "common/mapgen_space.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

const char *MapGenTraversal_ResultName(mapgen_traversal_result_t r)
{
    switch (r) {
    case MAPGEN_TRAVERSAL_OK:            return "OK";
    case MAPGEN_TRAVERSAL_ERR_ARGS:      return "ERR_ARGS";
    case MAPGEN_TRAVERSAL_ERR_MEMORY:    return "ERR_MEMORY";
    case MAPGEN_TRAVERSAL_ERR_NO_SPACE:  return "ERR_NO_SPACE";
    case MAPGEN_TRAVERSAL_ERR_NO_SPAWNS: return "ERR_NO_SPAWNS";
    }
    return "ERR_UNKNOWN";
}

bool MapGenTraversal_Passed(const mapgen_traversal_report_t *report)
{
    if (!report)
        return false;
    /*
     * A deliberately lethal drop is a design decision and is exempt. A
     * harmless pocket with no way out never is - that is precisely the map the
     * PO found himself standing in.
     */
    return report->spawns > 0
        && report->spawns_off_main == 0
        && report->trapped == report->trapped_lethal;
}

bool MapGenTraversal_NoWorseThan(const mapgen_traversal_report_t *donor,
                                 const mapgen_traversal_report_t *candidate,
                                 const char **out_reason)
{
    if (out_reason)
        *out_reason = NULL;
    if (!donor || !candidate) {
        if (out_reason)
            *out_reason = "no report";
        return false;
    }

    /* Absolute, whatever the donor does: a player who cannot reach the game
       is not playing it. */
    if (!candidate->spawns) {
        if (out_reason)
            *out_reason = "no player starts";
        return false;
    }
    if (candidate->spawns_off_main) {
        if (out_reason)
            *out_reason = "a player start cannot reach the others";
        return false;
    }

    /*
     * Reach, counted rather than shared.
     *
     * A share of the floor looks like the natural measure and is the wrong
     * one: thickening a wall puts new standable ledges on top of it, so the
     * denominator grows while the play space does not, and a candidate is
     * punished for adding geometry nobody needed to reach. What must not
     * shrink is how much a player can actually get to - which is what the
     * rejected F=66 map lost, at 22 reachable stances against its donor's
     * 2633.
     */
    if (candidate->reachable < (uint32_t)((uint64_t)donor->reachable * 9 / 10)) {
        if (out_reason)
            *out_reason = "much less of the map can be reached than in the donor";
        return false;
    }

    /*
     * Traps, also as a share, because the compiler's own subdivision moves the
     * absolute count by one or two either way on an unchanged map.
     */
    const uint32_t donor_traps = donor->trapped - donor->trapped_lethal;
    const uint32_t cand_traps = candidate->trapped - candidate->trapped_lethal;
    const double donor_share = donor->reachable
        ? (double)donor_traps / donor->reachable : 0.0;
    const double cand_share = candidate->reachable
        ? (double)cand_traps / candidate->reachable : 0.0;
    if (cand_share > donor_share * 1.10 + 0.002) {
        if (out_reason)
            *out_reason = "more of the map is a one-way pocket than in the donor";
        return false;
    }
    return true;
}

/* ---- spawns ---------------------------------------------------------------- */

/*
 * Player starts, read from the compiled entity lump rather than from the
 * candidate that claimed to place them. The compiled map is the only thing a
 * player actually loads.
 */
static uint32_t collect_spawns(const mapgen_bsp_t *bsp, float (**out)[3])
{
    uint32_t length = 0;
    const char *at = MapGenBsp_Entities(bsp, &length);
    if (!at)
        return 0;

    uint32_t capacity = 32, count = 0;
    float (*spawns)[3] = calloc(capacity, sizeof(*spawns));
    if (!spawns)
        return 0;

    const char *block = at;
    while ((block = strchr(block, '{')) != NULL) {
        const char *end = strchr(block, '}');
        if (!end)
            break;

        bool is_spawn = false;
        for (const char *p = block; p < end; p++) {
            if (p[0] != 'i')
                continue;
            if (!strncmp(p, "info_player_deathmatch", 22)
                || !strncmp(p, "info_player_start", 17)
                || !strncmp(p, "info_player_coop", 16)) {
                is_spawn = true;
                break;
            }
        }
        if (is_spawn) {
            const char *o = strstr(block, "\"origin\"");
            if (o && o < end) {
                o = strchr(o + 8, '"');
                if (o && o < end) {
                    if (count == capacity) {
                        float (*grown)[3] =
                            realloc(spawns, (size_t)capacity * 2 * sizeof(*grown));
                        if (!grown)
                            break;
                        spawns = grown;
                        capacity *= 2;
                    }
                    char buf[128];
                    const char *close = strchr(o + 1, '"');
                    size_t n = close ? (size_t)(close - o - 1) : 0;
                    if (n >= sizeof(buf))
                        n = sizeof(buf) - 1;
                    memcpy(buf, o + 1, n);
                    buf[n] = '\0';
                    char *cursor = buf;
                    for (int a = 0; a < 3; a++)
                        spawns[count][a] = strtof(cursor, &cursor);
                    count++;
                }
            }
        }
        block = end + 1;
    }

    if (!count) {
        free(spawns);
        return 0;
    }
    *out = spawns;
    return count;
}

/* The stance a spawn point stands on: the nearest one, which is what the
   engine's own drop-to-floor amounts to here. */
static uint32_t nearest_node(const mapgen_space_t *space, const float at[3])
{
    const uint32_t count = MapGenSpace_NumNodes(space);
    uint32_t best = UINT32_MAX;
    double best_d2 = 0.0;
    for (uint32_t i = 0; i < count; i++) {
        const mapgen_space_node_t *node = MapGenSpace_Node(space, i);
        double d2 = 0.0;
        for (int a = 0; a < 3; a++) {
            const double d = (double)node->origin[a] - at[a];
            d2 += d * d;
        }
        if (best == UINT32_MAX || d2 < best_d2) {
            best_d2 = d2;
            best = i;
        }
    }
    /* Further away than a room, and it is not this spawn's floor. */
    return best != UINT32_MAX && best_d2 <= 256.0 * 256.0 ? best : UINT32_MAX;
}

/* ---- the two sweeps -------------------------------------------------------- */

typedef struct {
    uint32_t *head;
    uint32_t *next;
    uint32_t *dest;
} adjacency_t;

static bool build_adjacency(const mapgen_space_t *space, adjacency_t *fwd,
                            adjacency_t *rev)
{
    const uint32_t nodes = MapGenSpace_NumNodes(space);
    const uint32_t edges = MapGenSpace_NumEdges(space);

    adjacency_t *both[2] = { fwd, rev };
    for (int i = 0; i < 2; i++) {
        both[i]->head = malloc((size_t)nodes * sizeof(*both[i]->head));
        both[i]->next = malloc(((size_t)edges + 1) * sizeof(*both[i]->next));
        both[i]->dest = malloc(((size_t)edges + 1) * sizeof(*both[i]->dest));
        if (!both[i]->head || !both[i]->next || !both[i]->dest)
            return false;
        for (uint32_t n = 0; n < nodes; n++)
            both[i]->head[n] = UINT32_MAX;
    }

    for (uint32_t e = 0; e < edges; e++) {
        const mapgen_space_edge_t *edge = MapGenSpace_Edge(space, e);
        if (edge->from >= nodes || edge->to >= nodes)
            continue;
        fwd->dest[e] = edge->to;
        fwd->next[e] = fwd->head[edge->from];
        fwd->head[edge->from] = e;

        rev->dest[e] = edge->from;
        rev->next[e] = rev->head[edge->to];
        rev->head[edge->to] = e;
    }
    return true;
}

static void sweep(const adjacency_t *adj, uint32_t nodes, const uint8_t *seeds,
                  uint8_t *reached, uint32_t *queue)
{
    uint32_t tail = 0, cursor = 0;
    for (uint32_t n = 0; n < nodes; n++) {
        if (seeds[n]) {
            reached[n] = 1;
            queue[tail++] = n;
        }
    }
    while (cursor < tail) {
        const uint32_t at = queue[cursor++];
        for (uint32_t e = adj->head[at]; e != UINT32_MAX; e = adj->next[e]) {
            if (!reached[adj->dest[e]]) {
                reached[adj->dest[e]] = 1;
                queue[tail++] = adj->dest[e];
            }
        }
    }
}

static void free_adjacency(adjacency_t *a)
{
    free(a->head);
    free(a->next);
    free(a->dest);
}

mapgen_traversal_result_t MapGenTraversal_Check(const mapgen_bsp_t *bsp,
                                                mapgen_traversal_report_t *out)
{
    if (!bsp || !out)
        return MAPGEN_TRAVERSAL_ERR_ARGS;
    memset(out, 0, sizeof(*out));

    mapgen_space_t *space = NULL;
    mapgen_space_params_t params = MapGenSpace_DefaultParams();
    if (MapGenSpace_Build(bsp, &params, &space) != MAPGEN_SPACE_OK || !space)
        return MAPGEN_TRAVERSAL_ERR_NO_SPACE;

    const uint32_t nodes = MapGenSpace_NumNodes(space);
    out->stances = nodes;
    if (!nodes) {
        MapGenSpace_Free(space);
        return MAPGEN_TRAVERSAL_ERR_NO_SPACE;
    }

    float (*spawns)[3] = NULL;
    const uint32_t num_spawns = collect_spawns(bsp, &spawns);
    out->spawns = num_spawns;
    if (!num_spawns) {
        MapGenSpace_Free(space);
        return MAPGEN_TRAVERSAL_ERR_NO_SPAWNS;
    }

    adjacency_t fwd, rev;
    memset(&fwd, 0, sizeof(fwd));
    memset(&rev, 0, sizeof(rev));
    uint8_t *seeds = calloc(nodes, sizeof(*seeds));
    uint8_t *forward = calloc(nodes, sizeof(*forward));
    uint8_t *backward = calloc(nodes, sizeof(*backward));
    uint32_t *queue = malloc((size_t)nodes * sizeof(*queue));

    if (!seeds || !forward || !backward || !queue
        || !build_adjacency(space, &fwd, &rev)) {
        free(spawns);
        free(seeds);
        free(forward);
        free(backward);
        free(queue);
        free_adjacency(&fwd);
        free_adjacency(&rev);
        MapGenSpace_Free(space);
        return MAPGEN_TRAVERSAL_ERR_MEMORY;
    }

    /*
     * The main component is what the spawns share. Taking it from the spawns
     * rather than from the largest region matters: a candidate whose players
     * all start in a sealed annex is broken even if the annex is small and the
     * rest of the map is large and healthy.
     */
    for (uint32_t s = 0; s < num_spawns; s++) {
        const uint32_t node = nearest_node(space, spawns[s]);
        if (node != UINT32_MAX)
            seeds[node] = 1;
        else
            out->spawns_off_main++;
    }

    sweep(&fwd, nodes, seeds, forward, queue);
    sweep(&rev, nodes, seeds, backward, queue);

    /* A spawn that cannot walk to the others is off the main component even
       when it did find a floor to stand on. */
    for (uint32_t s = 0; s < num_spawns; s++) {
        const uint32_t node = nearest_node(space, spawns[s]);
        if (node != UINT32_MAX && !backward[node])
            out->spawns_off_main++;
    }

    for (uint32_t n = 0; n < nodes; n++) {
        if (forward[n] && backward[n])
            out->main_component++;
        if (!forward[n])
            continue;
        out->reachable++;
        if (backward[n])
            continue;

        out->trapped++;
        const mapgen_space_node_t *node = MapGenSpace_Node(space, n);
        if (node->flags & MAPGEN_SPACE_NODE_HAZARD) {
            out->trapped_lethal++;
        } else if (out->trapped - out->trapped_lethal == 1) {
            memcpy(out->worst_trap, node->origin, sizeof(out->worst_trap));
        }
    }

    free(spawns);
    free(seeds);
    free(forward);
    free(backward);
    free(queue);
    free_adjacency(&fwd);
    free_adjacency(&rev);
    MapGenSpace_Free(space);
    return MAPGEN_TRAVERSAL_OK;
}
