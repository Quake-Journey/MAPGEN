/*
 * What one recording says about how people move on a map.
 *
 * Reads a .dm2 through the engine's own offline decoder and prints the bounded
 * derived trace: provenance, occupancy, the moves that were observed, and the
 * events. A rejected stream prints WHY, with its provenance, because a corpus
 * that silently drops what it cannot read reports agreement it has not earned.
 *
 *     mapgen_demo_ingest <demo.dm2> [--map NAME] [--source NAME] [--cells]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_demo.h"

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <demo.dm2> [--map NAME] [--source NAME]"
                        " [--cells] [--evidence FILE]\n", argv[0]);
        return 2;
    }

    const char *path = argv[1];
    const char *expect = NULL;
    const char *source = NULL;
    bool list_cells = false;
    /* Where to write the machine-readable record, for whatever holds the
       evidence afterwards. */
    const char *evidence = NULL;
    for (int a = 2; a < argc; a++) {
        if (!strcmp(argv[a], "--map") && a + 1 < argc)
            expect = argv[++a];
        else if (!strcmp(argv[a], "--source") && a + 1 < argc)
            source = argv[++a];
        else if (!strcmp(argv[a], "--cells"))
            list_cells = true;
        else if (!strcmp(argv[a], "--evidence") && a + 1 < argc)
            evidence = argv[++a];
    }

    mapgen_demo_t *demo = NULL;
    const mapgen_demo_result_t rc = MapGenDemo_Read(path, expect, source,
                                                    &demo);
    const mapgen_demo_provenance_t *p = MapGenDemo_Provenance(demo);

    if (!p) {
        printf("%s: %s\n", path, MapGenDemo_ResultName(rc));
        MapGenDemo_Free(demo);
        return 1;
    }

    if (evidence) {
        /*
         * One line per field, in a fixed order.
         *
         * Everything the provenance carries plus the counts derived from the
         * trace - which is what movement evidence IS, and all of it, because a
         * record that dropped a field would be a record somebody has to go
         * back to the demo to complete.
         */
        FILE *f = fopen(evidence, "wb");
        if (f) {
            fprintf(f, "map %s\n", p->map);
            fprintf(f, "gamedir %s\n", p->gamedir[0] ? p->gamedir : "-");
            fprintf(f, "source %s\n", p->source[0] ? p->source : path);
            fprintf(f, "digest %s\n", p->digest);
            fprintf(f, "protocol %d\n", p->protocol);
            fprintf(f, "pov %d\n", p->pov_slot);
            fprintf(f, "quality %u\n", p->quality);
            fprintf(f, "duration_ms %d\n", p->duration_ms);
            fprintf(f, "samples %u\n", p->samples);
            fprintf(f, "cells %u\n", MapGenDemo_NumCells(demo));
            fprintf(f, "jumps %u\n",
                    MapGenDemo_EventCount(demo, MAPGEN_DEMO_JUMP));
            fprintf(f, "drops %u\n",
                    MapGenDemo_EventCount(demo, MAPGEN_DEMO_DROP));
            fprintf(f, "rides %u\n",
                    MapGenDemo_EventCount(demo, MAPGEN_DEMO_RIDE));
            fclose(f);
        }
    }

    printf("%s\n", p->source[0] ? p->source : path);
    printf("  sha256 %s\n", p->digest);
    printf("  map \"%s\"  gamedir \"%s\"  protocol %d  pov %d  quality %u\n",
           p->map, p->gamedir, p->protocol, p->pov_slot, p->quality);

    if (rc != MAPGEN_DEMO_OK) {
        printf("  REJECTED: %s\n", MapGenDemo_ResultName(rc));
        MapGenDemo_Free(demo);
        return 1;
    }

    printf("  %u playerstates over %.1f s\n", p->samples,
           p->duration_ms / 1000.0);
    printf("  %u places occupied, %u moves between them\n",
           MapGenDemo_NumCells(demo), MapGenDemo_NumMoves(demo));
    printf("  ");
    for (uint32_t k = 0; k < MAPGEN_DEMO_EVENT_KINDS; k++)
        printf("%s %u  ", MapGenDemo_EventName((mapgen_demo_event_kind_t)k),
               MapGenDemo_EventCount(demo, (mapgen_demo_event_kind_t)k));
    printf("\n  trace digest %016llx\n",
           (unsigned long long)MapGenDemo_Digest(demo));

    if (list_cells) {
        const uint32_t n = MapGenDemo_NumCells(demo);
        for (uint32_t i = 0; i < n; i++) {
            const mapgen_demo_cell_t *c = MapGenDemo_Cell(demo, i);
            printf("    cell %5d %5d %5d  frames %4u  contacts %4u\n",
                   c->cell[0], c->cell[1], c->cell[2], c->frames, c->contacts);
        }
    }

    MapGenDemo_Free(demo);
    return 0;
}
