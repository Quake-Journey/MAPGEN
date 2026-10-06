/*
 * Ask the equivalence oracle about two compiled maps, and print what it saw.
 *
 *     mapgen_equivalence_driver DONOR.bsp BASELINE.bsp [--lattice N]
 *                               [--no-traversal] [--allowed]
 *
 * Exit code 0 when the baseline may be used as the reference, 1 when it may
 * not, 2 when the run itself failed. Everything it measured is printed either
 * way: a gate that only said yes or no would make the reader open both files.
 */
#include "common/mapgen_equivalence.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size <= 0) {
        fclose(f);
        fprintf(stderr, "empty %s\n", path);
        return NULL;
    }
    uint8_t *data = malloc((size_t)size);
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size) {
        free(data);
        fclose(f);
        fprintf(stderr, "cannot read %s\n", path);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t rc = MapGenBsp_Load(data, (size_t)size, &bsp);
    free(data);
    if (rc != MAPGEN_BSP_OK) {
        fprintf(stderr, "%s: %s\n", path, MapGenBsp_ResultName(rc));
        return NULL;
    }
    return bsp;
}

int main(int argc, char **argv)
{
    mapgen_equiv_policy_t policy;
    MapGenEquivalence_DefaultPolicy(&policy);

    const char *donor_path = NULL, *base_path = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--allowed")) {
            const uint32_t n = MapGenEquivalence_NumAllowedDifferences();
            for (uint32_t k = 0; k < n; k++)
                printf("allowed %s\n", MapGenEquivalence_AllowedDifference(k));
            if (argc == 2)
                return 0;
        } else if (!strcmp(argv[i], "--lattice") && i + 1 < argc) {
            policy.lattice = (float)atof(argv[++i]);
        } else if (!strcmp(argv[i], "--no-traversal")) {
            policy.compare_traversal = false;
        } else if (!donor_path) {
            donor_path = argv[i];
        } else if (!base_path) {
            base_path = argv[i];
        }
    }
    if (!donor_path || !base_path) {
        fprintf(stderr, "usage: %s DONOR.bsp BASELINE.bsp\n", argv[0]);
        return 2;
    }

    mapgen_bsp_t *donor = load(donor_path);
    mapgen_bsp_t *base = donor ? load(base_path) : NULL;
    if (!donor || !base) {
        MapGenBsp_Free(donor);
        MapGenBsp_Free(base);
        return 2;
    }

    mapgen_equiv_report_t report;
    const mapgen_equiv_result_t rc =
        MapGenEquivalence_Compare(donor, base, &policy, &report);

    char text[4096];
    MapGenEquivalence_ReportText(&report, text, sizeof(text));
    fputs(text, stdout);
    mapgen_equiv_surface_diff_t diffs[64];
    const uint32_t nd = MapGenEquivalence_SurfaceDiffs(diffs, 64);
    for (uint32_t i = 0; i < nd; i++)
        printf("surfdiff %-13s %-24s flags %d value %d model %u "
               "normal %.4f %.4f %.4f dist %.2f donor %.1f baseline %.1f area %.2f permille centroid %.3f "
               "facing %.4f offset %.3f axis %.4f\n",
               diffs[i].side == 0 ? "donor-only" :
               diffs[i].side == 1 ? "baseline-only" : "both",
               diffs[i].texture, diffs[i].flags, diffs[i].value, diffs[i].model,
               (double)diffs[i].normal[0], (double)diffs[i].normal[1],
               (double)diffs[i].normal[2], (double)diffs[i].dist,
               diffs[i].donor_area, diffs[i].baseline_area,
               diffs[i].area_permille, diffs[i].centroid_shift,
               diffs[i].normal_shift, diffs[i].offset_shift,
               diffs[i].axis_shift);

    const uint32_t ng = MapGenEquivalence_GroupDeltas(diffs, 64);
    for (uint32_t i = 0; i < ng && i < 12; i++)
        printf("groupdelta %-24s model %u normal %.4f %.4f %.4f dist %.2f "
               "donor %.1f baseline %.1f %.1f permille\n",
               diffs[i].texture, diffs[i].model, (double)diffs[i].normal[0],
               (double)diffs[i].normal[1], (double)diffs[i].normal[2],
               (double)diffs[i].dist, diffs[i].donor_area,
               diffs[i].baseline_area, diffs[i].area_permille);

    for (int a = MAPGEN_EQUIV_DIFF_SPACE; a < MAPGEN_EQUIV_RESULT_COUNT; a++)
        printf("axis %-18s %s%s%s\n",
               MapGenEquivalence_ResultName((mapgen_equiv_result_t)a),
               report.axis_result[a] ? "FAILED" : "ok",
               report.axis_detail[a][0] ? " -- " : "",
               report.axis_detail[a]);

    MapGenBsp_Free(donor);
    MapGenBsp_Free(base);
    if (rc == MAPGEN_EQUIV_OK)
        return 0;
    if (rc == MAPGEN_EQUIV_ERR_ARGS || rc == MAPGEN_EQUIV_ERR_MEMORY
        || rc == MAPGEN_EQUIV_ERR_LIMIT)
        return 2;
    return 1;
}
