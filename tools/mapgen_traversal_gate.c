/*
 * GF5 - run the safe-return gate over a compiled candidate and say whether it
 * is fit to hand anybody.
 *
 *     mapgen_traversal_gate <donor.bsp> <candidate.bsp>
 *     mapgen_traversal_gate <map.bsp>              (report only, no verdict)
 *
 * Exit code 0 passes, 1 fails. A failure says what is wrong and where to stand
 * to see it, because "there is a trap somewhere" is not a bug report.
 */

#include <stdio.h>
#include <stdlib.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_traversal.h"

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

static bool measure(const char *path, mapgen_traversal_report_t *report)
{
    mapgen_bsp_t *bsp = load(path);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", path);
        return false;
    }
    const mapgen_traversal_result_t rc = MapGenTraversal_Check(bsp, report);
    MapGenBsp_Free(bsp);
    if (rc != MAPGEN_TRAVERSAL_OK) {
        printf("%s: %s\n", path, MapGenTraversal_ResultName(rc));
        return false;
    }
    printf("%s: %u stances, %u spawns, reachable %u (%.0f%%), one-way %u"
           " (%u lethal)\n",
           path, report->stances, report->spawns, report->reachable,
           report->stances ? 100.0 * report->reachable / report->stances : 0.0,
           report->trapped, report->trapped_lethal);
    return true;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <donor.bsp> <candidate.bsp>\n", argv[0]);
        return 2;
    }

    mapgen_traversal_report_t first;
    if (!measure(argv[1], &first))
        return 1;
    if (argc < 3)
        return 0;

    mapgen_traversal_report_t second;
    if (!measure(argv[2], &second))
        return 1;

    const char *reason = NULL;
    if (!MapGenTraversal_NoWorseThan(&first, &second, &reason)) {
        printf("  FAIL: %s\n", reason ? reason : "unknown");
        const uint32_t traps = second.trapped - second.trapped_lethal;
        if (traps)
            printf("  nearest one-way stance at %.0f %.0f %.0f\n",
                   (double)second.worst_trap[0], (double)second.worst_trap[1],
                   (double)second.worst_trap[2]);
        return 1;
    }
    printf("  PASS: no worse than the donor\n");
    return 0;
}
