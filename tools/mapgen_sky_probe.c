/*
 * The transaction's sky rule, asked of any compiled map (ledger row 371).
 *
 *     mapgen_sky_probe <map.bsp> <donor.bsp> lox loy loz hix hiy hiz
 *
 * Prints "seen 1: new space at X Y Z from X Y Z" when the rule the transaction
 * applies to a skinned dig's attempt (`REJECTED_SKY`) finds new space in the
 * box seen through the sky, and "seen 0" when it does not. The same function,
 * not a copy, so a guard can show the rule refusing a map the PO refused and
 * passing a skinned one.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_transaction.h"

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

int main(int argc, char **argv)
{
    if (argc < 9) {
        fprintf(stderr, "usage: %s map.bsp donor.bsp lox loy loz hix hiy hiz\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *map = load(argv[1]), *donor = load(argv[2]);
    if (!map || !donor) {
        fprintf(stderr, "cannot read the maps\n");
        return 2;
    }
    float lo[3], hi[3], witness[6];
    for (int a = 0; a < 3; a++) {
        lo[a] = strtof(argv[3 + a], NULL);
        hi[a] = strtof(argv[6 + a], NULL);
    }
    if (MapGenTransaction_SeenThroughSky(map, donor, lo, hi, witness))
        printf("seen 1: new space at %.0f %.0f %.0f from %.0f %.0f %.0f\n",
               (double)witness[0], (double)witness[1], (double)witness[2],
               (double)witness[3], (double)witness[4], (double)witness[5]);
    else
        printf("seen 0\n");
    MapGenBsp_Free(map);
    MapGenBsp_Free(donor);
    return 0;
}
