/*
 * Where does the walk go wrong? (ledger row 400)
 *
 *     mapgen_reach_path <map.bsp> [count] [--solid-places] [--no-spawn-lift] [--pushes] [--drops H]
 *
 * `--pushes` (brief 18 D2): for every push volume of the map, the highest place the walk lands a player thrown by
 * it - one line each, «push N at x y z: up H to x y z», or «throws nobody» - so a guard can hold a map grown tall
 * to the heights its donor's pads reach. `--drops H`: how many of the walk's moves fall more than H (the fall that
 * begins to hurt), and to how many places.
 *
 * Explores the map as the product does and, for the first COUNT places a player can reach and not leave without
 * dying (and for every stranded start), prints the shortest chain of moves from a start to it - one origin per
 * line - so a reader sees where the walk leaves the map it should stay in.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_reach.h"
#include "common/mapgen_movers.h"

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *data = malloc((size_t)size);
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size) {
        fclose(f);
        free(data);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    MapGenBsp_Load(data, (size_t)size, &bsp);
    free(data);
    return bsp;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp> [count] [--solid-places]\n", argv[0]);
        return 2;
    }
    int want = 3;
    bool pushes = false;
    float drop = 0.0f;
    for (int a = 2; a < argc; a++) {
        if (!strcmp(argv[a], "--solid-places"))
            MapGenReach_SetSolidPlaces(true);       /* brief 18 D2 RED: a body settled inside a solid is a place */
        else if (!strcmp(argv[a], "--short-flight"))
            MapGenReach_SetPushFlight(false);       /* brief 18 D2 RED: a push followed for 180 frames only */
        else if (!strcmp(argv[a], "--no-spawn-lift"))
            MapGenReach_SetSpawnLift(false);        /* brief 18 D2 RED: a start settled at its origin alone */
        else if (!strcmp(argv[a], "--pushes"))
            pushes = true;
        else if (!strcmp(argv[a], "--drops") && a + 1 < argc)
            drop = strtof(argv[++a], NULL);
        else
            want = atoi(argv[a]);
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot load %s\n", argv[1]);
        return 2;
    }
    mapgen_reach_t *reach = NULL;
    if (MapGenReach_Explore(bsp, 40000u, &reach) != MAPGEN_REACH_OK || !reach) {
        fprintf(stderr, "the walk did not run\n");
        return 2;
    }
    const uint32_t n = MapGenReach_NumStates(reach), m = MapGenReach_NumEdges(reach);
    uint32_t *prev = malloc(n * sizeof(*prev));
    uint32_t *queue = malloc(n * sizeof(*queue));
    uint32_t *first = calloc(n + 1, sizeof(*first));
    uint32_t *adj = malloc((m ? m : 1) * sizeof(*adj));
    for (uint32_t e = 0; e < m; e++) {
        uint32_t a, b;
        MapGenReach_Edge(reach, e, &a, &b);
        first[a + 1]++;
    }
    for (uint32_t i = 0; i < n; i++)
        first[i + 1] += first[i];
    uint32_t *fill = calloc(n, sizeof(*fill));
    for (uint32_t e = 0; e < m; e++) {
        uint32_t a, b;
        MapGenReach_Edge(reach, e, &a, &b);
        adj[first[a] + fill[a]++] = b;
    }
    uint32_t head = 0, tail = 0;
    for (uint32_t i = 0; i < n; i++) {
        prev[i] = UINT32_MAX;
        if (MapGenReach_State(reach, i)->from_spawn) {
            prev[i] = i;
            queue[tail++] = i;
        }
    }
    while (head < tail) {
        const uint32_t s = queue[head++];
        for (uint32_t k = first[s]; k < first[s + 1]; k++)
            if (prev[adj[k]] == UINT32_MAX) {
                prev[adj[k]] = s;
                queue[tail++] = adj[k];
            }
    }
    int shown = 0;
    for (uint32_t i = 0; i < n && shown < want; i++) {
        const mapgen_reach_state_t *st = MapGenReach_State(reach, i);
        if (!st->reachable || st->can_return || st->hazard)
            continue;
        printf("trapped %.1f %.1f %.1f, from a start:\n", st->origin[0], st->origin[1], st->origin[2]);
        uint32_t chain[512], len = 0;
        for (uint32_t c = i; len < 512; c = prev[c]) {
            chain[len++] = c;
            if (prev[c] == c || prev[c] == UINT32_MAX)
                break;
        }
        for (uint32_t k = len; k-- > 0;) {
            const mapgen_reach_state_t *c = MapGenReach_State(reach, chain[k]);
            printf("   %8.1f %8.1f %8.1f%s%s\n", c->origin[0], c->origin[1], c->origin[2],
                   c->from_spawn ? "  start" : "", c->hazard ? "  lethal" : "");
        }
        shown++;
    }
    for (uint32_t i = 0; i < n; i++) {
        const mapgen_reach_state_t *st = MapGenReach_State(reach, i);
        if (st->from_spawn && !(st->reachable && st->can_return))
            printf("stranded start %.1f %.1f %.1f: reachable %d, can return %d, in %u out %u\n", st->origin[0],
                   st->origin[1], st->origin[2], st->reachable, st->can_return, st->in_degree, st->out_degree);
    }
    if (pushes) {
        mapgen_movers_t *movers = calloc(1, sizeof(*movers));
        if (movers && MapGenMovers_Read(bsp, movers)) {
            for (uint32_t i = 0; i < movers->num_pushes; i++) {
                const mapgen_mover_push_t *pv = &movers->pushes[i];
                float best = -1e9f, to[3] = { 0, 0, 0 };
                for (uint32_t e = 0; e < m; e++) {
                    uint32_t from, dest;
                    MapGenReach_Edge(reach, e, &from, &dest);
                    const mapgen_reach_state_t *s = MapGenReach_State(reach, from), *t = MapGenReach_State(reach, dest);
                    /* the player's box against the volume, both a unit larger - as the walk touches a push */
                    const bool in = s->origin[0] - 18.0f <= pv->maxs[0] && s->origin[0] + 18.0f >= pv->mins[0]
                                 && s->origin[1] - 18.0f <= pv->maxs[1] && s->origin[1] + 18.0f >= pv->mins[1]
                                 && s->origin[2] - 26.0f <= pv->maxs[2] && s->origin[2] + 34.0f >= pv->mins[2];
                    if (in && s->reachable && t->origin[2] - s->origin[2] > best) {
                        best = t->origin[2] - s->origin[2];
                        memcpy(to, t->origin, sizeof(to));
                    }
                }
                if (best > -1e8f)
                    printf("push %u at %.0f %.0f %.0f: up %.0f to %.0f %.0f %.0f\n", (unsigned)i,
                           0.5 * (double)(pv->mins[0] + pv->maxs[0]), 0.5 * (double)(pv->mins[1] + pv->maxs[1]),
                           0.5 * (double)(pv->mins[2] + pv->maxs[2]), (double)best, (double)to[0], (double)to[1],
                           (double)to[2]);
                else
                    printf("push %u at %.0f %.0f %.0f: throws nobody\n", (unsigned)i,
                           0.5 * (double)(pv->mins[0] + pv->maxs[0]), 0.5 * (double)(pv->mins[1] + pv->maxs[1]),
                           0.5 * (double)(pv->mins[2] + pv->maxs[2]));
            }
        }
        free(movers);
    }
    if (drop > 0.0f) {
        uint32_t moves = 0, places = 0;
        uint8_t *hit = calloc(n ? n : 1, 1);
        for (uint32_t e = 0; hit && e < m; e++) {
            uint32_t from, dest;
            MapGenReach_Edge(reach, e, &from, &dest);
            const mapgen_reach_state_t *s = MapGenReach_State(reach, from), *t = MapGenReach_State(reach, dest);
            if (s->reachable && !t->hazard && s->origin[2] - t->origin[2] > drop) {
                moves++;
                if (!hit[dest]) {
                    hit[dest] = 1;
                    places++;
                }
            }
        }
        free(hit);
        printf("drops over %.0f: %u moves onto %u places that do not kill\n", (double)drop, (unsigned)moves,
               (unsigned)places);
    }
    {
        /* the walk's own account, for a guard to read */
        const mapgen_reach_report_t *r = MapGenReach_Report(reach);
        printf("walk: places %u, no way back %u, of them lethal %u, pickups out of reach %u of %u, starts stranded %u "
               "of %u, passes %d\n", (unsigned)r->reachable, (unsigned)r->trapped, (unsigned)r->trapped_lethal,
               (unsigned)r->items_unreachable, (unsigned)r->items, (unsigned)r->spawns_stranded, (unsigned)r->spawns,
               MapGenReach_Passed(r) ? 1 : 0);
        if (r->items_unreachable)
            printf("pickup out of reach at %.0f %.0f %.0f\n", (double)r->worst_item[0], (double)r->worst_item[1],
                   (double)r->worst_item[2]);
        if (r->landmarks_unreachable)
            printf("landmarks out of reach %u, the worst at %.0f %.0f %.0f\n", (unsigned)r->landmarks_unreachable,
                   (double)r->worst_landmark[0], (double)r->worst_landmark[1], (double)r->worst_landmark[2]);
    }
    MapGenReach_Free(reach);
    MapGenBsp_Free(bsp);
    return 0;
}
