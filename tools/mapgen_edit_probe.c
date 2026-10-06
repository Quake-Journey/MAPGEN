/*
 * What the schedule offers, and what one operator does when asked - without
 * compiling anything.
 *
 *     mapgen_edit_probe <donor.bsp> [seed] [--only <kind>] [--apply N]
 *
 * A compile costs six seconds on a fixture and a minute on a real map, and
 * most questions about an operator are not questions about the compiler: did
 * it decline, how many did the schedule offer, and did applying it change the
 * candidate at all. Those are answered here. Whether what it produced can be
 * built and played is the transaction's question and is asked there.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_geometry_edit.h"

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
        fprintf(stderr, "usage: %s <donor.bsp> [seed] [--only <kind>]"
                        " [--apply N]\n", argv[0]);
        return 2;
    }
    const uint64_t seed = argc > 2 && argv[2][0] != '-'
                        ? strtoull(argv[2], NULL, 10) : 1;
    const char *only = NULL;
    uint32_t apply = 0;
    for (int a = 2; a + 1 < argc; a++) {
        if (!strcmp(argv[a], "--only"))
            only = argv[a + 1];
        else if (!strcmp(argv[a], "--apply"))
            apply = (uint32_t)strtoul(argv[a + 1], NULL, 10);
    }

    mapgen_bsp_t *bsp = load(argv[1]);
    mapgen_geometry_t *donor = NULL;
    if (!bsp || MapGenGeometry_FromBsp(bsp, &donor) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    mapgen_geometry_edit_plan_t *plan = NULL;
    if (MapGenGeometryEdit_Plan(donor, bsp, seed, &plan)
        != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot plan\n");
        return 2;
    }

    const uint32_t offered = MapGenGeometryEdit_Count(plan);
    printf("%u edits\n", offered);
    for (int k = 0; k < MAPGEN_EDIT_KINDS; k++)
        printf("  %-18s %u\n",
               MapGenGeometryEdit_KindName((mapgen_edit_kind_t)k),
               MapGenGeometryEdit_CountOfKind(plan, (mapgen_edit_kind_t)k));

    /* Which room each planned turn is for, so a fixture with five rooms and
       one with four can be compared on the room they are both about. */
    for (uint32_t i = 0; i < offered; i++) {
        const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
        uint32_t room = 0, quarter = 0;
        bool mirror = false;
        if (e && e->kind == MAPGEN_EDIT_TURN_BUNDLE
            && MapGenGeometryEdit_TurnAt(plan, e->target, &room, &quarter,
                                         &mirror))
            printf("turn %u room %u quarter %u%s\n", i, room, quarter,
                   mirror ? " mirrored" : "");
    }

    if (only) {
        mapgen_geometry_t *candidate = NULL;
        if (MapGenGeometry_Clone(donor, &candidate) != MAPGEN_GEOMETRY_OK)
            return 2;
        const uint64_t before = MapGenGeometry_CanonicalDigest(candidate);

        uint32_t seen = 0, applied = 0, declined = 0;
        for (uint32_t i = 0; i < offered; i++) {
            const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
            if (!e || strcmp(MapGenGeometryEdit_KindName(e->kind), only))
                continue;
            if (seen++ < apply)
                continue;
            bool changed = false;
            MapGenGeometryEdit_ApplyOne(plan, candidate, donor, i, &changed);
            /* A reshape holds its target in its own table; reading the
               widen's with a reshape's index prints an unrelated edit. */
            float normal[3], centre[3], dist;
            if (e->kind == MAPGEN_EDIT_WIDEN_CONNECTOR
                && MapGenGeometryEdit_WidenAt(plan, e->target, normal, &dist,
                                              centre))
                printf("edit %u %s at %.0f %.0f %.0f facing %.0f %.0f %.0f:"
                       " %s\n", i, only,
                       (double)centre[0], (double)centre[1], (double)centre[2],
                       (double)normal[0], (double)normal[1], (double)normal[2],
                       changed ? "applied" : "declined");
            else
                printf("edit %u %s: %s\n", i, only,
                       changed ? "applied" : "declined");
            if (changed)
                applied++;
            else
                declined++;
            if (applied + declined >= 1 && apply != UINT32_MAX)
                break;
        }
        const uint64_t after = MapGenGeometry_CanonicalDigest(candidate);
        printf("applied %u, declined %u\n", applied, declined);
        printf("candidate %s\n", before == after ? "unchanged" : "changed");
        MapGenGeometry_Free(candidate);
    }

    MapGenGeometryEdit_Free(plan);
    MapGenGeometry_Free(donor);
    MapGenBsp_Free(bsp);
    return 0;
}
