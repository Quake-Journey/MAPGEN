/*
 * Row 403 - a key or value written from the entity text block itself survives the block growing.
 *
 * Built with MAPGEN_GEOMETRY_TEXT_ALWAYS_MOVES, so every growth of the block moves it and spoils the old bytes:
 * a writer that copies from a pointer into the old block then copies spoiled bytes every time, not only when the
 * allocator happens to move the block (the Studio guard's resumed q2dm1 run, whose swap of two pickups wrote
 * spoiled bytes as an ammo_grenades' class and then crashed).
 *
 *     mapgen_entity_text_probe <donor.bsp>
 *
 * Swaps the classnames of two pickups of different classes back and forth, the way the swap edit does - the
 * second name read with MapGenGeometry_EntityValue and written straight from the block - until the block has
 * grown at least twice, and checks both names after every write. Prints PASS or FAIL lines; exits 1 on a FAIL.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

static uint8_t *slurp(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = n > 0 ? malloc((size_t)n) : NULL;
    if (data && fread(data, 1, (size_t)n, f) != (size_t)n) {
        free(data);
        data = NULL;
    }
    fclose(f);
    if (data)
        *size = (size_t)n;
    return data;
}

static bool is_pickup(const char *c)
{
    return c && (!strncmp(c, "ammo_", 5) || !strncmp(c, "weapon_", 7) || !strncmp(c, "item_", 5));
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s <donor.bsp>\n", argv[0]);
        return 2;
    }
    size_t size = 0;
    uint8_t *raw = slurp(argv[1], &size);
    mapgen_bsp_t *bsp = NULL;
    if (!raw || MapGenBsp_Load(raw, size, &bsp) != MAPGEN_BSP_OK) {
        fprintf(stderr, "cannot load %s\n", argv[1]);
        return 2;
    }
    free(raw);
    mapgen_geometry_t *g = NULL;
    if (MapGenGeometry_FromBsp(bsp, &g) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot take %s apart\n", argv[1]);
        return 2;
    }

    /* two pickups of different classes */
    uint32_t a = UINT32_MAX, b = UINT32_MAX;
    for (uint32_t e = 0; e < MapGenGeometry_NumEntities(g) && b == UINT32_MAX; e++) {
        const char *c = MapGenGeometry_EntityValue(g, e, "classname");
        if (!is_pickup(c))
            continue;
        if (a == UINT32_MAX)
            a = e;
        else if (strcmp(c, MapGenGeometry_EntityValue(g, a, "classname")))
            b = e;
    }
    if (b == UINT32_MAX) {
        printf("FAIL the map has two pickups of different classes\n");
        return 1;
    }
    char want_a[64], want_b[64];
    snprintf(want_a, sizeof(want_a), "%s", MapGenGeometry_EntityValue(g, a, "classname"));
    snprintf(want_b, sizeof(want_b), "%s", MapGenGeometry_EntityValue(g, b, "classname"));

    uint32_t moved = 0, bad = 0, swaps = 0;
    const char *was = MapGenGeometry_EntityValue(g, a, "classname");
    for (; swaps < 200000 && moved < 2 && !bad; swaps++) {
        /* the swap edit: the first name kept aside, the second written straight from the block */
        char keep[64];
        snprintf(keep, sizeof(keep), "%s", MapGenGeometry_EntityValue(g, a, "classname"));
        const char *theirs = MapGenGeometry_EntityValue(g, b, "classname");
        if (MapGenGeometry_SetEntityValue(g, a, "classname", theirs) != MAPGEN_GEOMETRY_OK
            || MapGenGeometry_SetEntityValue(g, b, "classname", keep) != MAPGEN_GEOMETRY_OK) {
            bad++;
            break;
        }
        const char *now_a = MapGenGeometry_EntityValue(g, a, "classname");
        const char *now_b = MapGenGeometry_EntityValue(g, b, "classname");
        const bool even = (swaps % 2) == 1;
        if (strcmp(now_a, even ? want_a : want_b) || strcmp(now_b, even ? want_b : want_a)) {
            printf("        after swap %u: \"%.20s\" and \"%.20s\"\n", swaps + 1, now_a, now_b);
            bad++;
        }
        /* the block moved when a fresh read of the same pair is somewhere else than it can be by appending */
        const char *here = MapGenGeometry_EntityValue(g, a, "classname");
        if (here < was || here > was + 1024 * 1024)
            moved++;
        was = here;
    }
    printf("%s every swap kept both names while the block moved %u times (%u swaps, %s <-> %s)\n",
           bad ? "FAIL" : (moved >= 2 ? "PASS" : "FAIL"), moved, swaps, want_a, want_b);
    MapGenGeometry_Free(g);
    MapGenBsp_Free(bsp);
    return bad || moved < 2 ? 1 : 0;
}
