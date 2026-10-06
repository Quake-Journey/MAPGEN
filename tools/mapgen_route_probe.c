/*
 * Did the edits bury a way through the map?
 *
 *     mapgen_route_probe <baseline.bsp> <candidate.bsp>
 *
 * The PO walked a fork on 2026-09-07 evening and found a stairwell filled
 * wall to wall: three blocks, 160 x 128 x 344 and two more, with four units
 * of daylight beside them. Every gate passed it, because the reachability
 * gate asks whether each pickup can be reached from each spawn and q2dm1 has
 * another way up.
 *
 * So this asks about the WAY rather than the destination, using the module's
 * own definitions - `MapGenBsp_Places`, `MapGenBsp_Climbs`, so that what this
 * prints and what the transaction refuses are one implementation:
 *
 *   CLIMB places   a standing place of the BASELINE with three or more floor
 *                  heights within sixty-four units of it: a step, a stair, a
 *                  ledge to hop;
 *   LOST           of those, the ones that are not standing places in the
 *                  candidate any more;
 *   NARROWED       places that survive but whose free run in the four compass
 *                  directions has fallen below a player's own width.
 *
 * Exit 1 when any climb place is lost.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"

#define GRID       32.0f
#define PLAYER     32.0f
#define MAX_PLACES 400000

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

/* The free run from a place in the four compass directions, at knee height. */
static float widest_run(const mapgen_bsp_t *bsp, const float p[3])
{
    float best = 1e9f;
    for (int axis = 0; axis < 2; axis++) {
        for (int dir = -1; dir <= 1; dir += 2) {
            float run = 0.0f;
            while (run < PLAYER) {
                float q[3] = { p[0], p[1], p[2] + 24.0f };
                q[axis] += (float)dir * (run + 4.0f);
                if (MapGenBsp_PointContents(bsp, q) & 1)
                    break;
                run += 4.0f;
            }
            if (run < best)
                best = run;
        }
    }
    return best;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <baseline.bsp> <candidate.bsp>"
                        " [x0 y0 z0 x1 y1 z1]\n", argv[0]);
        return 2;
    }
    /*
     * And, when the caller knows one, the box a MACHINE replaced.
     *
     * A lift is a staircase taken away and a func_plat put where it was: the
     * standing places on the steps are gone and the way through the map is
     * not. The only honest way to tell that apart from a stairwell somebody
     * filled in is WHERE the lost places are, so a caller who is asking about
     * one lift passes the box the lift stands in and reads `climb lost
     * outside`, which is the number that has to be zero.
     */
    float box[2][3];
    const bool has_box = argc >= 9;
    if (has_box)
        for (int a = 0; a < 3; a++) {
            box[0][a] = strtof(argv[3 + a], NULL);
            box[1][a] = strtof(argv[6 + a], NULL);
        }
    else
        memset(box, 0, sizeof(box));
    mapgen_bsp_t *base = load(argv[1]), *cand = load(argv[2]);
    if (!base || !cand) {
        fprintf(stderr, "cannot read the pair\n");
        return 2;
    }

    static float places[MAX_PLACES][3];
    static uint8_t climb[MAX_PLACES];
    const uint32_t found = MapGenBsp_Places(base, GRID, places, MAX_PLACES);
    const uint32_t n = found < MAX_PLACES ? found : MAX_PLACES;
    const uint32_t climbs = MapGenBsp_Climbs(places, n, climb);

    uint32_t gone = 0, lost = 0, narrowed = 0, shown = 0, outside = 0;
    for (uint32_t i = 0; i < n; i++) {
        if (!MapGenBsp_Stands(cand, places[i])) {
            gone++;
            if (climb[i]) {
                const bool in_box = has_box
                    && places[i][0] >= box[0][0] && places[i][0] <= box[1][0]
                    && places[i][1] >= box[0][1] && places[i][1] <= box[1][1]
                    && places[i][2] >= box[0][2] && places[i][2] <= box[1][2];
                if (!in_box) {
                    if (shown++ < 24)
                        printf("lost climb %.0f %.0f %.0f\n", places[i][0],
                               places[i][1], places[i][2]);
                    outside++;
                }
                lost++;
            }
            continue;
        }
        const float now = widest_run(cand, places[i]);
        if (now < 16.0f && now < widest_run(base, places[i]))
            narrowed++;
    }

    printf("baseline places %u\n", n);
    printf("climb places %u\n", climbs);
    printf("places lost %u\n", gone);
    printf("climb lost %u\n", lost);
    printf("climb lost outside %u\n", outside);
    printf("narrowed %u\n", narrowed);
    MapGenBsp_Free(base);
    MapGenBsp_Free(cand);
    return lost ? 1 : 0;
}
