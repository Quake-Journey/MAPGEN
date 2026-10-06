/*
 * The product's generator entry point, driven from a command line.
 *
 * Deliberately thin: it parses arguments and prints the report, and every
 * decision belongs to MapGenGenerate_Fork. That is what makes it usable as
 * evidence - a guard can run this and the older tool over the same donor,
 * fidelity and seed and require the two `.map` files to be identical byte for
 * byte, which is the only way to show that moving the pipeline behind an
 * interface did not change it.
 *
 *     mapgen_generate_driver <donor.bsp> <out.map> [fidelity] [seed] [mask]
 */

#include <stdio.h>
#include <stdlib.h>

#include "common/mapgen_generate.h"

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <donor.bsp> <out.map> [fidelity] [seed]"
                        " [stair mask]\n", argv[0]);
        return 2;
    }

    mapgen_generate_request_t request;
    request.fidelity = argc > 3 ? (int32_t)strtol(argv[3], NULL, 10) : 100;
    request.seed = argc > 4 ? strtoull(argv[4], NULL, 10) : 1;
    request.stair_mask = argc > 5 ? strtoull(argv[5], NULL, 0) : UINT64_MAX;

    mapgen_generate_report_t report;
    const mapgen_generate_result_t rc =
        MapGenGenerate_Fork(argv[1], argv[2], &request, &report);

    printf("%s\n", MapGenGenerate_ResultName(rc));
    printf("  donor      %u brushes, %u sides, digest %016llx\n",
           report.donor_brushes, report.donor_sides,
           (unsigned long long)report.donor_digest);
    printf("  candidate  %u brushes, %u sides, digest %016llx\n",
           report.candidate_brushes, report.candidate_sides,
           (unsigned long long)report.candidate_digest);
    printf("  fidelity %d: %u of %u scheduled edits spent\n", request.fidelity,
           report.edits_spent, report.edits_offered);
    printf("    spent:");
    for (uint32_t k = 0; k < MAPGEN_EDIT_KINDS; k++) {
        if (report.spent_of_kind[k])
            printf(" %u %s,", report.spent_of_kind[k],
                   MapGenGeometryEdit_KindName((mapgen_edit_kind_t)k));
    }
    printf("\n");
    return rc == MAPGEN_GENERATE_OK ? 0 : 1;
}
