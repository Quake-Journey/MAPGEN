/*
 * The transaction's seam rule, asked of any compiled map (ledger row 382).
 *
 *     mapgen_seam_probe <map.bsp> <donor.bsp>
 *
 * Prints every witness the transaction keeps from the donor ("donor witness at
 * X Y Z on the edge ..."), then every world seam of the map ("seam at X Y Z ...
 * new" or "... inherited"), then "witnesses N, seams M, new K". The same
 * functions the transaction judges with (`MapGenTransaction_DonorSeams`,
 * `MapGenTransaction_NewSeam`), not a copy. The skin-gap discount (row 369) is
 * the judge's own and is not applied.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_transaction.h"

#define CAP 1024u

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    mapgen_bsp_t *bsp = NULL;
    if (raw && fread(raw, 1, (size_t)n, f) == (size_t)n)
        MapGenBsp_Load(raw, (size_t)n, &bsp);
    fclose(f);
    free(raw);
    return bsp;
}

static void said(const char *what, const mapgen_bsp_seam_t *s, const char *tail)
{
    printf("%s at %.1f %.1f %.1f on the edge %.2f %.2f %.2f -> %.2f %.2f %.2f%s\n", what,
           (double)s->split[0], (double)s->split[1], (double)s->split[2],
           (double)s->from[0], (double)s->from[1], (double)s->from[2],
           (double)s->to[0], (double)s->to[1], (double)s->to[2], tail);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s map.bsp donor.bsp\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *map = load(argv[1]), *donor = load(argv[2]);
    mapgen_bsp_seam_t *wit = malloc(sizeof(*wit) * CAP), *seam = malloc(sizeof(*seam) * CAP);
    if (!map || !donor || !wit || !seam) {
        fprintf(stderr, "cannot read the maps\n");
        return 2;
    }
    uint32_t num_wit = 0, num = 0, fresh = 0, world = 0;
    if (MapGenTransaction_DonorSeams(donor, wit, CAP, &num_wit) != MAPGEN_SEAMS_OK
        || MapGenBsp_Seams(map, seam, CAP, &num) != MAPGEN_SEAMS_OK) {
        printf("seams UNKNOWN\n");
        return 1;
    }
    for (uint32_t i = 0; i < num_wit; i++)
        said("donor witness", &wit[i], "");
    for (uint32_t i = 0; i < num; i++) {
        if ((!seam[i].opaque_edge && !seam[i].opaque_vertex)
            || seam[i].edge_model != seam[i].vertex_model)
            continue;
        world++;
        const bool is_new = MapGenTransaction_NewSeam(&seam[i], wit, num_wit);
        fresh += is_new ? 1u : 0u;
        said("seam", &seam[i], is_new ? " new" : " inherited");
    }
    printf("witnesses %u, seams %u, new %u\n", num_wit, world, fresh);
    MapGenBsp_Free(map);
    MapGenBsp_Free(donor);
    free(wit);
    free(seam);
    return 0;
}
