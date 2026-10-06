/*
 * The REJECTED_LOST_PICKUP and REJECTED_BLOCKED_SPAWN questions asked of one
 * compiled map (ledger rows 302 and 307).
 *
 *     mapgen_lost_pickup_oracle <map.bsp>
 *
 * Prints every pickup the game frees at spawn - its class, its origin and what
 * its box starts inside - as `MapGenTransaction_PickupsLostAtSpawn` answers it,
 * then every spawn point a carrying mover runs into - its class, its origin and
 * the mover - as `MapGenTransaction_SpawnsInMoverColumns` answers it.
 *
 * Exit 0 when there is neither, 1 when there is one, 2 when the map cannot be
 * read.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_transaction.h"

#define MAX_LOST 1024u

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

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s map.bsp\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    mapgen_lost_pickup_t *lost = calloc(MAX_LOST, sizeof(*lost));
    const uint32_t n =
        lost ? MapGenTransaction_PickupsLostAtSpawn(bsp, lost, MAX_LOST) : 0u;
    printf("%u pickups lost at spawn\n", n);
    for (uint32_t i = 0; lost && i < n && i < MAX_LOST; i++)
        printf("  %s at %.0f %.0f %.0f inside %s\n", lost[i].classname,
               (double)lost[i].origin[0], (double)lost[i].origin[1],
               (double)lost[i].origin[2], lost[i].inside);
    free(lost);

    mapgen_blocked_spawn_t *blocked = calloc(MAX_LOST, sizeof(*blocked));
    const uint32_t b = blocked
        ? MapGenTransaction_SpawnsInMoverColumns(bsp, blocked, MAX_LOST) : 0u;
    printf("%u spawns blocked by movers\n", b);
    for (uint32_t i = 0; blocked && i < b && i < MAX_LOST; i++)
        printf("  %s at %.0f %.0f %.0f in the column of %s\n",
               blocked[i].classname, (double)blocked[i].origin[0],
               (double)blocked[i].origin[1], (double)blocked[i].origin[2],
               blocked[i].mover);
    free(blocked);
    MapGenBsp_Free(bsp);
    return n || b ? 1 : 0;
}
