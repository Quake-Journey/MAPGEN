/*
 * Where does the walk go wrong? (ledger row 400)
 *
 *     mapgen_reach_path <map.bsp> [count]
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
        fprintf(stderr, "usage: %s <map.bsp> [count]\n", argv[0]);
        return 2;
    }
    const int want = argc > 2 ? atoi(argv[2]) : 3;
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
    MapGenReach_Free(reach);
    MapGenBsp_Free(bsp);
    return 0;
}
