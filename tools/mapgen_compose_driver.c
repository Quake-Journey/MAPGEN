/*
 * Compose an invented map out of rooms the references were built with.
 *
 *     mapgen_compose_driver --seed N --out FILE.map DONOR.bsp [DONOR.bsp ...]
 *
 * Prints what it chose and where it put it, so the choice can be read without
 * opening the map.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_compose.h"

int main(int argc, char **argv)
{
    uint64_t seed = 1;
    const char *out = NULL;
    const char *donor[MAPGEN_COMPOSE_MAX_DONORS];
    uint32_t num = 0;

    for (int a = 1; a < argc; a++) {
        if (!strcmp(argv[a], "--seed") && a + 1 < argc)
            seed = strtoull(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--out") && a + 1 < argc)
            out = argv[++a];
        else if (num < MAPGEN_COMPOSE_MAX_DONORS)
            donor[num++] = argv[a];
    }
    if (!num) {
        fprintf(stderr, "usage: %s [--seed N] [--out FILE.map]"
                        " DONOR.bsp [DONOR.bsp ...]\n", argv[0]);
        return 2;
    }

    mapgen_geometry_t *g = NULL;
    mapgen_compose_report_t report;
    const mapgen_compose_result_t rc =
        MapGenCompose_Build(donor, num, seed, &g, &report);
    if (rc != MAPGEN_COMPOSE_OK) {
        printf("compose %s\n", MapGenCompose_ResultName(rc));
        return 1;
    }

    printf("parts %u, connectors %u, shell %u brushes (%u sky), spawns %u\n",
           report.num_parts, report.connectors, report.shell_brushes,
           report.sky_brushes, report.spawns);
    printf("footprint %.0f x %.0f, sky at %.0f\n", report.footprint[0],
           report.footprint[1], report.sky_z);
    for (uint32_t i = 0; i < report.num_parts; i++) {
        const mapgen_compose_part_t *p = &report.part[i];
        printf("  %-10s room %3u  turn %u%s  %.0f %.0f %.0f .. %.0f %.0f %.0f"
               "  %u brushes%s\n", p->donor, p->room, p->quarter_turns,
               p->mirror_x ? " mirrored" : "         ",
               p->mins[0], p->mins[1], p->mins[2],
               p->maxs[0], p->maxs[1], p->maxs[2], p->brushes,
               p->main ? "  MAIN" : "");
    }
    printf("brushes %u, entities %u\n", MapGenGeometry_NumBrushes(g),
           MapGenGeometry_NumEntities(g));

    if (out) {
        const mapgen_geometry_result_t wr = MapGenGeometry_WriteValve220(g, out);
        printf("wrote %s: %s\n", out, MapGenGeometry_ResultName(wr));
        if (wr != MAPGEN_GEOMETRY_OK) {
            MapGenGeometry_Free(g);
            return 1;
        }
    }
    MapGenGeometry_Free(g);
    return 0;
}
