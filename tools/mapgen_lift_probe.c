/*
 * Is there room for the machine to move?
 *
 *     mapgen_lift_probe <map.bsp> [baseline.bsp]
 *
 * The PO watched a lift rise through a crate and a flight of steps on
 * 2026-09-07 and said what a lift is: part of a logical construction, bounded
 * by architecture free of other geometry. Every gate had passed it, because
 * the sweep check exempts a mover that starts inside solid - and the operator
 * that built these sank every deck twelve units into the floor, so all of them
 * were exempt by construction.
 *
 * So this asks the question directly, of the compiled artifact: for each mover
 * that carries a player, sample its own box at rest, at every stop, and along
 * the sweep between them, and report how much of that volume is WORLD solid.
 * A lift in a shaft reports zero.
 *
 *     mover *N kind at <box> stops S rest R travel T rider D permille
 *     movers N, obstructed M
 *
 * TRAVEL and RIDER are the contract and q2dm1 answers zero to both. REST is
 * reported and not judged: a lift flush in its own recess has solid against
 * its sides where it sits, and q2dm1's big lift reports five permille there.
 *
 * With a second file, the models of the FIRST are also compared with the
 * models of the second, index by index, and any that lost volume is reported:
 * that is the donor's own lift, cut to a fifteenth of itself by an edit that
 * addressed brushes by index into a geometry that had moved underneath it.
 *
 *     model *N was <box> now <box> LOST
 *
 * Exit 1 when any mover is obstructed or any model lost volume.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_movers.h"

#define CONTENTS_SOLID 0x00000001
#define STEP           4.0f
#define MAX_HITS       64

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

/*
 * How much of the MOVER, moved by `at`, is inside world solid.
 *
 * Of the mover and not of its bounding box: a lift is a slab in a tall shaft
 * and its box is mostly the shaft. Sampling the box asks whether the shaft is
 * empty, which is a different question and one q2dm1's own lifts fail - the
 * first version of this probe reported both of them obstructed, which is how
 * the measure was caught.
 *
 * The lattice is offset two units into the model, so a deck resting ON a floor
 * is not read as a deck inside it.
 */
static uint32_t occupancy(const mapgen_bsp_t *bsp,
                          const mapgen_bsp_model_t *model, const float at[3],
                          float from_z, uint32_t *out_total)
{
    uint32_t in = 0, total = 0;
    for (float x = model->mins[0] + 2.0f; x < model->maxs[0]; x += STEP) {
        for (float y = model->mins[1] + 2.0f; y < model->maxs[1]; y += STEP) {
            for (float z = from_z + 2.0f; z < model->maxs[2]; z += STEP) {
                const float here[3] = { x, y, z };
                if (!(MapGenBsp_PointContentsAt(bsp, model->headnode, here)
                      & CONTENTS_SOLID))
                    continue;           /* not part of the machine */
                const float there[3] = { x + at[0], y + at[1], z + at[2] };
                total++;
                if (MapGenBsp_PointContents(bsp, there) & CONTENTS_SOLID)
                    in++;
            }
        }
    }
    if (out_total)
        *out_total += total;
    return in;
}

/*
 * And the space the RIDER occupies: a player's height above the deck.
 *
 * This is the measure that matches what the PO watched. The machine's own body
 * may be buried - q2dm1 builds its big lift as a tall pillar that sinks into
 * the rock, which is the idiom and not a defect - but the place a player
 * stands has to be clear the whole way up, and on the maps of 2026-09-07 it
 * was full of crates and steps.
 */
static uint32_t rider(const mapgen_bsp_t *bsp,
                      const mapgen_bsp_model_t *model, const float at[3],
                      uint32_t *out_total)
{
    uint32_t in = 0, total = 0;
    for (float x = model->mins[0] + 4.0f; x < model->maxs[0] - 2.0f;
         x += STEP) {
        for (float y = model->mins[1] + 4.0f; y < model->maxs[1] - 2.0f;
             y += STEP) {
            /* Where the deck's top is under this column, if it is here. */
            float top = model->mins[2] - 1.0f;
            for (float z = model->maxs[2] - 1.0f; z > model->mins[2];
                 z -= STEP) {
                const float here[3] = { x, y, z };
                if (MapGenBsp_PointContentsAt(bsp, model->headnode, here)
                    & CONTENTS_SOLID) {
                    top = z;
                    break;
                }
            }
            if (top < model->mins[2])
                continue;               /* nothing to stand on in this column */
            for (float up = 8.0f; up <= 56.0f; up += 8.0f) {
                const float there[3] = { x + at[0], y + at[1],
                                         top + up + at[2] };
                total++;
                if (MapGenBsp_PointContents(bsp, there) & CONTENTS_SOLID)
                    in++;
            }
        }
    }
    if (out_total)
        *out_total += total;
    return in;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp> [baseline.bsp]\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }

    static mapgen_movers_t movers;
    if (!MapGenMovers_Read(bsp, &movers)) {
        fprintf(stderr, "cannot read the movers of %s\n", argv[1]);
        return 2;
    }

    uint32_t obstructed = 0;
    for (uint32_t i = 0; i < movers.num_movers; i++) {
        const mapgen_mover_t *mv = &movers.movers[i];
        if (!mv->carries)
            continue;

        const mapgen_bsp_model_t *model = MapGenBsp_Model(bsp, mv->model);
        if (!model)
            continue;

        /* The deck: the top sixteen units of the machine, which is the part
           a player sees and stands on. The rest of it may be a pillar. */
        const float deck_from = model->maxs[2] - 16.0f > model->mins[2]
                              ? model->maxs[2] - 16.0f : model->mins[2];

        /*
         * Three numbers, and only two of them are the contract.
         *
         * REST is where the machine sits with nothing done to it, and a lift
         * flush in its own recess has solid against its sides there: q2dm1's
         * big lift reports five permille at rest and is not a defect. So rest
         * is reported and not judged.
         *
         * TRAVEL is the deck anywhere else along its sweep - a deck that
         * passes through a crate or through the steps of its own staircase,
         * which is what the PO watched. q2dm1: zero.
         *
         * RIDER is the space a player standing on the deck passes through.
         * q2dm1: zero.
         */
        uint32_t rest_total = 0, rest_in = 0;
        uint32_t travel_total = 0, travel_in = 0;
        uint32_t ride_total = 0, ride_in = 0;
        for (uint32_t s = 0; s < mv->num_stops; s++) {
            const bool resting = (s == 0);
            occupancy(bsp, model, mv->stop[s], deck_from,
                      resting ? &rest_total : &travel_total);
            const uint32_t d = occupancy(bsp, model, mv->stop[s], deck_from,
                                         NULL);
            if (resting)
                rest_in += d;
            else
                travel_in += d;
            ride_in += rider(bsp, model, mv->stop[s], &ride_total);
        }
        for (uint32_t s = 0; s + 1 < mv->num_stops; s++) {
            float d[3];
            float span = 0.0f;
            for (int a = 0; a < 3; a++) {
                d[a] = mv->stop[s + 1][a] - mv->stop[s][a];
                span += fabsf(d[a]);
            }
            const uint32_t steps = (uint32_t)(span / STEP);
            for (uint32_t k = 1; k < steps; k++) {
                float at[3];
                for (int a = 0; a < 3; a++)
                    at[a] = mv->stop[s][a] + d[a] * (float)k / (float)steps;
                travel_in += occupancy(bsp, model, at, deck_from,
                                       &travel_total);
                ride_in += rider(bsp, model, at, &ride_total);
            }
        }

        if (travel_in || ride_in)
            obstructed++;

        printf("mover *%u %s at %6.0f %6.0f %6.0f .. %6.0f %6.0f %6.0f"
               "  stops %u  rest %u  travel %u  rider %u  permille\n",
               mv->model, MapGenMovers_KindName(mv->kind),
               mv->mins[0], mv->mins[1], mv->mins[2],
               mv->maxs[0], mv->maxs[1], mv->maxs[2], mv->num_stops,
               rest_total ? (uint32_t)((1000ull * rest_in) / rest_total) : 0u,
               travel_total ? (uint32_t)((1000ull * travel_in) / travel_total)
                            : 0u,
               ride_total ? (uint32_t)((1000ull * ride_in) / ride_total) : 0u);
    }
    printf("movers %u, obstructed %u\n", movers.num_movers, obstructed);

    /* --- and what happened to the models a baseline had ------------------ */
    uint32_t lost = 0;
    if (argc > 2) {
        mapgen_bsp_t *base = load(argv[2]);
        if (!base) {
            fprintf(stderr, "cannot read %s\n", argv[2]);
            return 2;
        }
        const uint32_t nb = MapGenBsp_NumModels(base);
        const uint32_t nc = MapGenBsp_NumModels(bsp);
        for (uint32_t m = 1; m < nb; m++) {
            const mapgen_bsp_model_t *was = MapGenBsp_Model(base, m);
            const mapgen_bsp_model_t *now = m < nc ? MapGenBsp_Model(bsp, m)
                                                  : NULL;
            if (!was)
                continue;
            const float wv = (was->maxs[0] - was->mins[0])
                           * (was->maxs[1] - was->mins[1])
                           * (was->maxs[2] - was->mins[2]);
            const float nv = now ? (now->maxs[0] - now->mins[0])
                                 * (now->maxs[1] - now->mins[1])
                                 * (now->maxs[2] - now->mins[2])
                                 : 0.0f;
            const bool shrank = !now || nv < wv * 0.999f;
            if (shrank)
                lost++;
            printf("model *%u was %.0fx%.0fx%.0f now %.0fx%.0fx%.0f %s\n", m,
                   was->maxs[0] - was->mins[0], was->maxs[1] - was->mins[1],
                   was->maxs[2] - was->mins[2],
                   now ? now->maxs[0] - now->mins[0] : 0.0f,
                   now ? now->maxs[1] - now->mins[1] : 0.0f,
                   now ? now->maxs[2] - now->mins[2] : 0.0f,
                   shrank ? "LOST" : "kept");
        }
        printf("models compared %u, lost %u\n", nb > 0 ? nb - 1 : 0, lost);
        MapGenBsp_Free(base);
    }

    MapGenBsp_Free(bsp);
    return (obstructed || lost) ? 1 : 0;
}
