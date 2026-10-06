/*
 * The REJECTED_HIDDEN question asked from outside the transaction (ledger rows 297 and 299).
 *
 *     mapgen_visgate_oracle <parent.bsp> <candidate.bsp> x0 y0 z0 x1 y1 z1 [grow]
 *                           [--walk] [--eye x y z]...
 *
 * The transaction's eyes are the reachable places of a walk; a walk is minutes on
 * this machine, so by default the oracle stands its eyes on the candidate's floors
 * instead - air over solid, a player's height clear, a player's half-width off the
 * walls, on a 16-unit lattice inside the box grown by `grow` - at view height over
 * the origin. `--walk` takes the transaction's after-the-walk eyes: the candidate's
 * reach walk, its reachable places inside the grown box, 22 units over each origin.
 * `--eye` asks from exactly the eyes given - a witness a walk found, without the
 * walk. The question itself is `MapGenTransaction_HiddenInSight`, unchanged.
 *
 * Exit 0 when no pair is lost, 1 when one is, 2 when a map cannot be read.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_reach.h"
#include "common/mapgen_transaction.h"

#define MAX_GIVEN 64

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    if (MapGenBsp_Load(raw, (size_t)n, &bsp) != MAPGEN_BSP_OK)
        bsp = NULL;
    free(raw);
    return bsp;
}

static bool stops(const mapgen_bsp_t *b, float x, float y, float z)
{
    const float p[3] = { x, y, z };
    return (MapGenBsp_PointContents(b, p) & (MAPGEN_CONTENTS_SOLID | 0x10000)) != 0;
}

int main(int argc, char **argv)
{
    bool walk = false;
    float given[MAX_GIVEN][3];
    uint32_t num_given = 0;
    const char *pos[9] = { 0 };
    int npos = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--walk") == 0) {
            walk = true;
        } else if (strcmp(argv[i], "--eye") == 0 && i + 3 < argc
                   && num_given < MAX_GIVEN) {
            for (int a = 0; a < 3; a++)
                given[num_given][a] = strtof(argv[++i], NULL);
            num_given++;
        } else if (npos < 9) {
            pos[npos++] = argv[i];
        }
    }
    if (npos < 8) {
        fprintf(stderr, "usage: %s parent.bsp candidate.bsp x0 y0 z0 x1 y1 z1"
                        " [grow] [--walk] [--eye x y z]...\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *parent = load(pos[0]);
    mapgen_bsp_t *cand = load(pos[1]);
    if (!parent || !cand) {
        fprintf(stderr, "cannot read a map\n");
        return 2;
    }
    float lo[3], hi[3];
    for (int a = 0; a < 3; a++) {
        lo[a] = strtof(pos[2 + a], NULL);
        hi[a] = strtof(pos[5 + a], NULL);
    }
    const float grow = npos > 8 ? strtof(pos[8], NULL) : 256.0f;

    uint32_t cap = 1u << 16, num_eyes = 0;
    float (*eyes)[3] = malloc(sizeof(*eyes) * cap);
    for (uint32_t g = 0; eyes && g < num_given; g++) {
        memcpy(eyes[num_eyes], given[g], sizeof(given[g]));
        num_eyes++;
    }
    if (walk && eyes && !num_given) {
        /* the transaction's own eyes: the same walk, the same box, the same 22 */
        mapgen_reach_t *reach = NULL;
        if (MapGenReach_Explore(cand, 40000u, &reach) != MAPGEN_REACH_OK || !reach) {
            fprintf(stderr, "the candidate's walk did not run\n");
            return 2;
        }
        const uint32_t states = MapGenReach_NumStates(reach);
        for (uint32_t s = 0; s < states && num_eyes < cap; s++) {
            const mapgen_reach_state_t *st = MapGenReach_State(reach, s);
            if (!st || !st->reachable)
                continue;
            bool by_it = true;
            for (int a = 0; a < 3 && by_it; a++)
                by_it = st->origin[a] >= lo[a] - grow && st->origin[a] <= hi[a] + grow;
            if (!by_it)
                continue;
            eyes[num_eyes][0] = st->origin[0];
            eyes[num_eyes][1] = st->origin[1];
            eyes[num_eyes][2] = st->origin[2] + 22.0f;
            num_eyes++;
        }
        MapGenReach_Free(reach);
    }
    for (float x = lo[0] - grow; eyes && !walk && !num_given && x <= hi[0] + grow;
         x += 16.0f)
        for (float y = lo[1] - grow; y <= hi[1] + grow; y += 16.0f) {
            bool was_solid = true;
            for (float z = lo[2] - grow; z <= hi[2] + grow; z += 8.0f) {
                const bool now = stops(cand, x, y, z);
                const bool floor_here = was_solid && !now;
                was_solid = now;
                if (!floor_here || stops(cand, x, y, z + 56.0f))
                    continue;
                bool boxed = false;
                for (int w = 0; w < 4 && !boxed; w++)
                    boxed = stops(cand, x + (w == 0 ? 16.0f : w == 1 ? -16.0f : 0.0f),
                                  y + (w == 2 ? 16.0f : w == 3 ? -16.0f : 0.0f),
                                  z + 24.0f);
                if (boxed || num_eyes >= cap)
                    continue;
                /* an origin 24 over the floor, and the eye 22 over the origin */
                eyes[num_eyes][0] = x;
                eyes[num_eyes][1] = y;
                eyes[num_eyes][2] = z + 46.0f;
                num_eyes++;
            }
        }

    float witness[6];
    const uint32_t lost = MapGenTransaction_HiddenInSight(
        parent, cand, (const float (*)[3])eyes, num_eyes, lo, hi, grow, witness);
    printf("%u eyes, %u pairs LOST in plain sight", num_eyes, lost);
    if (lost)
        printf(" (first: eye %.0f %.0f %.0f -> %.0f %.0f %.0f)",
               (double)witness[0], (double)witness[1], (double)witness[2],
               (double)witness[3], (double)witness[4], (double)witness[5]);
    printf("\n");
    free(eyes);
    MapGenBsp_Free(parent);
    MapGenBsp_Free(cand);
    return lost ? 1 : 0;
}
