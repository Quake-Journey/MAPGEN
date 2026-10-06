/*
 * What moves in this map, where it moves to, and who can move it.
 *
 * Reading a door's travel out of `angle`, `lip` and the model's own size is
 * arithmetic with two reserved values and an off-by-a-lip, and a lift that
 * rests at the top instead of the bottom puts a solid floor across the room it
 * serves. So it is printed, against maps whose lifts and doors are known, and
 * not taken on trust.
 *
 *     mapgen_movers_dump <map.bsp>
 */

#include <stdio.h>
#include <stdlib.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_movers.h"

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp>\n", argv[0]);
        return 2;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    fclose(f);

    mapgen_bsp_t *bsp = NULL;
    if (MapGenBsp_Load(raw, (size_t)n, &bsp) != MAPGEN_BSP_OK) {
        free(raw);
        fprintf(stderr, "not a map this can read\n");
        return 2;
    }
    free(raw);

    mapgen_movers_t m;
    if (!MapGenMovers_Read(bsp, &m)) {
        MapGenBsp_Free(bsp);
        fprintf(stderr, "could not read the entities\n");
        return 2;
    }

    printf("%s: %u movers, %u operators, %u teleporters%s\n", argv[1],
           m.num_movers, m.num_operators, m.num_portals,
           m.overflowed ? "  (MORE THAN THIS CAN HOLD)" : "");

    for (uint32_t i = 0; i < m.num_movers; i++) {
        const mapgen_mover_t *mv = &m.movers[i];
        printf("  %2u %-8s model *%-3u  %s%s%s\n", i,
               MapGenMovers_KindName(mv->kind), mv->model,
               mv->player_operated ? "a player working it is enough"
                                   : "needs firing",
               mv->carries ? ", carries a rider" : "",
               mv->inoperable ? ", NOTHING CAN FIRE IT" : "");
        printf("        drawn %.0f %.0f %.0f .. %.0f %.0f %.0f\n",
               (double)mv->mins[0], (double)mv->mins[1], (double)mv->mins[2],
               (double)mv->maxs[0], (double)mv->maxs[1], (double)mv->maxs[2]);
        if (mv->targetname[0])
            printf("        named \"%s\"\n", mv->targetname);
        if (mv->target[0])
            printf("        fires \"%s\"\n", mv->target);
        for (uint32_t s = 0; s < mv->num_stops; s++)
            printf("        stop %u  %+8.1f %+8.1f %+8.1f\n", s,
                   (double)mv->stop[s][0], (double)mv->stop[s][1],
                   (double)mv->stop[s][2]);
    }

    for (uint32_t i = 0; i < m.num_operators; i++) {
        const mapgen_mover_operator_t *op = &m.operators[i];
        printf("  operator -> \"%s\"  at %.0f %.0f %.0f .. %.0f %.0f %.0f%s\n",
               op->target, (double)op->mins[0], (double)op->mins[1],
               (double)op->mins[2], (double)op->maxs[0], (double)op->maxs[1],
               (double)op->maxs[2], op->shootable ? "  (must be shot)" : "");
    }

    for (uint32_t i = 0; i < m.num_portals; i++) {
        const mapgen_mover_portal_t *p = &m.portals[i];
        if (p->has_destination)
            printf("  teleporter at %.0f %.0f %.0f .. %.0f %.0f %.0f"
                   " -> %.0f %.0f %.0f\n",
                   (double)p->mins[0], (double)p->mins[1], (double)p->mins[2],
                   (double)p->maxs[0], (double)p->maxs[1], (double)p->maxs[2],
                   (double)p->destination[0], (double)p->destination[1],
                   (double)p->destination[2]);
        else
            printf("  teleporter at %.0f %.0f %.0f .. %.0f %.0f %.0f"
                   " -> \"%s\" WHICH IS NOT IN THIS MAP\n",
                   (double)p->mins[0], (double)p->mins[1], (double)p->mins[2],
                   (double)p->maxs[0], (double)p->maxs[1], (double)p->maxs[2],
                   p->target);
    }

    MapGenBsp_Free(bsp);
    return 0;
}
