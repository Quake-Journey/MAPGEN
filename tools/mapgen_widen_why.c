/*
 * Why every planned widen is refused, counted by reason.
 *
 *     mapgen_widen_why DONOR.bsp SEED
 *
 * `widen-connector` is the largest structural family on q2dm1 - 43 of the
 * candidates - and the ledger says it refuses 41 of them. That is where GF6C's
 * shortfall lives, and until now the refusal carried no reason: "there is not
 * enough rock behind this face" and "somebody else's brush is inside the cut"
 * were the same bare `false`.
 *
 * This asks each one, on the donor's own geometry, and tallies the answers. It
 * costs no compiler and no minutes.
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_geometry_edit.h"

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
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = size > 0 ? malloc((size_t)size) : NULL;
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
    if (argc < 3) {
        fprintf(stderr, "usage: %s DONOR.bsp SEED\n", argv[0]);
        return 2;
    }

    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp)
        return 1;
    mapgen_geometry_t *donor = NULL;
    if (MapGenGeometry_FromBsp(bsp, &donor) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot lift %s into geometry\n", argv[1]);
        return 1;
    }

    mapgen_geometry_edit_plan_t *plan = NULL;
    if (MapGenGeometryEdit_PlanWith(donor, bsp, strtoull(argv[2], NULL, 10),
                                    NULL, NULL, NULL, 0, &plan)
        != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot plan\n");
        return 1;
    }

    /*
     * On a CLONE, because the question is about the map as the transaction
     * would meet it and because nothing here is allowed to change the donor.
     */
    mapgen_geometry_t *candidate = NULL;
    if (MapGenGeometry_Clone(donor, &candidate) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot clone\n");
        return 1;
    }

    const uint32_t widens = MapGenGeometryEdit_CountOfKind(
        plan, MAPGEN_EDIT_WIDEN_CONNECTOR);
    uint32_t tally[MAPGEN_WIDEN_REASONS];
    memset(tally, 0, sizeof(tally));

    printf("donor %s seed %s, %u planned widens\n", argv[1], argv[2], widens);
    for (uint32_t i = 0; i < widens; i++) {
        const mapgen_widen_refusal_t why =
            MapGenGeometryEdit_WhyWidenRefused(plan, candidate, bsp, i);
        if ((unsigned)why < MAPGEN_WIDEN_REASONS)
            tally[why]++;
        printf("  widen %3u  %s\n", i,
               MapGenGeometryEdit_WidenRefusalName(why));
    }

    printf("\n");
    for (uint32_t r = 0; r < MAPGEN_WIDEN_REASONS; r++)
        if (tally[r])
            printf("  %4u  %s\n", tally[r],
                   MapGenGeometryEdit_WidenRefusalName(
                       (mapgen_widen_refusal_t)r));

    MapGenGeometry_Free(candidate);
    MapGenGeometryEdit_Free(plan);
    MapGenGeometry_Free(donor);
    MapGenBsp_Free(bsp);
    return 0;
}
