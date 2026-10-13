/*
 * Each machine's room, as the generator's judge measures it, in two compiled maps - the donor and a map made from it
 * (the PO, 09.10, mg_10_6695: «платформа ездит сквозь колонну»). For every carrying mover of the second map: its kind,
 * box, the permille of its travel inside world solid, and the same mover's in the first map (same kind, box within two
 * units), or "new". A machine whose travel grew past its own by more than 2 permille is what the blocked-machine gate
 * refuses now.
 *
 *     mapgen_mover_clearance_probe DONOR.bsp MAP.bsp
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_movers.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *data = size > 0 ? malloc((size_t)size) : NULL;
    const size_t got = data ? fread(data, 1, (size_t)size, f) : 0;
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    if (!data || got != (size_t)size || MapGenBsp_Load(data, (size_t)size, &bsp) != MAPGEN_BSP_OK)
        bsp = NULL;
    free(data);
    return bsp;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s DONOR.bsp MAP.bsp\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *a = load(argv[1]), *b = load(argv[2]);
    if (!a || !b) {
        fprintf(stderr, "cannot read the maps\n");
        return 2;
    }
    mapgen_movers_t *ma = calloc(1, sizeof(*ma)), *mb = calloc(1, sizeof(*mb));
    if (!ma || !mb || !MapGenMovers_Read(a, ma) || !MapGenMovers_Read(b, mb)) {
        fprintf(stderr, "cannot read the movers\n");
        return 2;
    }
    MapGenMovers_MeasureClearance(ma, a);
    MapGenMovers_MeasureClearance(mb, b);
    int blocked = 0;
    for (uint32_t i = 0; i < mb->num_movers; i++) {
        const mapgen_mover_t *m = &mb->movers[i];
        if (!m->carries)
            continue;
        int was = -1;
        for (uint32_t k = 0; k < ma->num_movers && was < 0; k++) {
            const mapgen_mover_t *o = &ma->movers[k];
            bool same = o->carries && o->kind == m->kind;
            for (int x = 0; x < 3 && same; x++)
                same = fabsf(o->mins[x] - m->mins[x]) <= 2.0f && fabsf(o->maxs[x] - m->maxs[x]) <= 2.0f;
            if (same)
                was = o->body_permille;
        }
        const bool bad = (int)m->body_permille > (was < 0 ? 0 : was) + 2;
        blocked += bad;
        printf("%-8s %6.0f %6.0f %6.0f .. %6.0f %6.0f %6.0f  body in solid %4u permille, in the donor %s%d%s\n",
               MapGenMovers_KindName(m->kind), (double)m->mins[0], (double)m->mins[1], (double)m->mins[2],
               (double)m->maxs[0], (double)m->maxs[1], (double)m->maxs[2], (unsigned)m->body_permille,
               was < 0 ? "new " : "", was < 0 ? 0 : was, bad ? "   <- BLOCKED" : "");
    }
    printf("%d machine(s) blocked against their own room in the donor\n", blocked);
    return blocked ? 1 : 0;
}
