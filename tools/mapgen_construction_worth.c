/*
 * What can a player DO here, and how much of it is on the thing that was
 * built?
 *
 *     mapgen_construction_worth <map.bsp> [x0 y0 z0 x1 y1 z1]
 *
 * Every gate in this tree asks whether an edit BROKE something - a way
 * through, a surface, a spawn, a pool's rim. None of them asks whether it was
 * worth making, and on 2026-09-08 the PO walked three forks that passed all
 * of them and were pointless: square columns two hundred and forty units tall
 * in the middles of rooms, one map with nine of them and NINE FEWER standing
 * places than the donor it forked.
 *
 * So this prints the reach explorer's own answer:
 *
 *   component   the places a player can get to and get back from, in the
 *               component his spawns are in - which is what a map IS to play;
 *   on the      of those, the ones standing on the construction whose box was
 *   construction given: inside its footprint and higher than the ground it
 *               stands on, which is what tells a place on the platform from a
 *               place on the floor beside it.
 *
 * The box is the operator's own, printed by `mapgen_recut_driver --list`.
 * With no box the second number is zero and the first is the map's own, which
 * is how a baseline is measured.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_reach.h"

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

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp> [x0 y0 z0 x1 y1 z1]\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }

    float lo[3] = { 0, 0, 0 }, hi[3] = { 0, 0, 0 };
    bool has_box = false;
    if (argc >= 8) {
        for (int a = 0; a < 3; a++) {
            lo[a] = strtof(argv[2 + a], NULL);
            hi[a] = strtof(argv[5 + a], NULL);
        }
        has_box = hi[0] > lo[0] || hi[1] > lo[1] || hi[2] > lo[2];
    }

    mapgen_reach_t *reach = NULL;
    if (MapGenReach_Explore(bsp, 40000u, &reach) != MAPGEN_REACH_OK || !reach) {
        printf("component 0\n");
        printf("on the construction 0\n");
        printf("explored no\n");
        MapGenBsp_Free(bsp);
        return 2;
    }
    const mapgen_reach_report_t *report = MapGenReach_Report(reach);

    uint32_t on_it = 0;
    const uint32_t states = MapGenReach_NumStates(reach);
    for (uint32_t s = 0; s < states; s++) {
        const mapgen_reach_state_t *st = MapGenReach_State(reach, s);
        if (!st || !st->reachable || !st->can_return || st->hazard)
            continue;
        if (!has_box)
            continue;
        /* Standing ON it: inside the footprint and higher than the ground the
           construction was dropped onto. Its foot is buried sixteen units
           below that ground, so twenty-four above the foot is a place on the
           thing rather than on the floor beside it. */
        if (st->origin[0] >= lo[0] && st->origin[0] <= hi[0]
            && st->origin[1] >= lo[1] && st->origin[1] <= hi[1]
            && st->origin[2] >= lo[2] + 24.0f)
            on_it++;
    }

    printf("component %u\n", report->component);
    printf("on the construction %u\n", on_it);
    printf("reachable %u\n", report->reachable);
    printf("trapped %u\n", report->trapped);
    printf("items unreachable %u\n", report->items_unreachable);
    printf("spawns stranded %u\n", report->spawns_stranded);
    printf("explored yes\n");

    MapGenReach_Free(reach);
    MapGenBsp_Free(bsp);
    return 0;
}
