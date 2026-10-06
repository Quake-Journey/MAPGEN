/*
 * MapGenGenerate - see inc/common/mapgen_generate.h.
 *
 * The pipeline is the one the fork tool has been running all along: load,
 * extract, plan, spend, write. It is written here once so the tool, the worker
 * and the Recipe path are all asking the same thing rather than three
 * copies of it drifting apart.
 */

#include "common/mapgen_generate.h"

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char *MapGenGenerate_ResultName(mapgen_generate_result_t r)
{
    switch (r) {
    case MAPGEN_GENERATE_OK:                 return "OK";
    case MAPGEN_GENERATE_ERR_ARGS:           return "ERR_ARGS";
    case MAPGEN_GENERATE_ERR_MEMORY:         return "ERR_MEMORY";
    case MAPGEN_GENERATE_ERR_DONOR_UNREADABLE: return "ERR_DONOR_UNREADABLE";
    case MAPGEN_GENERATE_ERR_DONOR_REFUSED:  return "ERR_DONOR_REFUSED";
    case MAPGEN_GENERATE_ERR_GEOMETRY:       return "ERR_GEOMETRY";
    case MAPGEN_GENERATE_ERR_PLAN:           return "ERR_PLAN";
    case MAPGEN_GENERATE_ERR_WRITE:          return "ERR_WRITE";
    }
    return "ERR_UNKNOWN";
}

static uint8_t *slurp(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return NULL;
    }
    const long n = ftell(f);
    if (n <= 0 || fseek(f, 0, SEEK_SET) != 0) {
        fclose(f);
        return NULL;
    }
    uint8_t *data = malloc((size_t)n);
    if (data && fread(data, 1, (size_t)n, f) != (size_t)n) {
        free(data);
        data = NULL;
    }
    fclose(f);
    if (data)
        *size = (size_t)n;
    return data;
}

mapgen_generate_result_t MapGenGenerate_Fork(const char *donor_bsp,
                                             const char *out_map,
                                             const mapgen_generate_request_t *request,
                                             mapgen_generate_report_t *report)
{
    if (report)
        memset(report, 0, sizeof(*report));
    if (!donor_bsp || !out_map || !request)
        return MAPGEN_GENERATE_ERR_ARGS;
    if (request->fidelity < 0 || request->fidelity > 100)
        return MAPGEN_GENERATE_ERR_ARGS;

    size_t size = 0;
    uint8_t *raw = slurp(donor_bsp, &size);
    if (!raw)
        return MAPGEN_GENERATE_ERR_DONOR_UNREADABLE;

    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t br = MapGenBsp_Load(raw, size, &bsp);
    free(raw);
    if (br != MAPGEN_BSP_OK)
        return MAPGEN_GENERATE_ERR_DONOR_REFUSED;

    mapgen_geometry_t *donor = NULL;
    if (MapGenGeometry_FromBsp(bsp, &donor) != MAPGEN_GEOMETRY_OK) {
        MapGenBsp_Free(bsp);
        return MAPGEN_GENERATE_ERR_GEOMETRY;
    }

    if (report) {
        report->donor_brushes = MapGenGeometry_NumBrushes(donor);
        report->donor_sides = MapGenGeometry_NumSides(donor);
        report->donor_digest = MapGenGeometry_CanonicalDigest(donor);
    }

    /*
     * At fidelity 100 the candidate IS the donor's geometry - not a copy of it
     * with nothing done, but the same object, so there is no clone to differ
     * from the original in any way at all.
     */
    mapgen_geometry_t *candidate = donor;
    mapgen_geometry_edit_plan_t *plan = NULL;
    mapgen_generate_result_t rc = MAPGEN_GENERATE_OK;

    if (request->fidelity < 100) {
        if (MapGenGeometry_Clone(donor, &candidate) != MAPGEN_GEOMETRY_OK) {
            candidate = donor;
            rc = MAPGEN_GENERATE_ERR_MEMORY;
        } else if (MapGenGeometryEdit_Plan(donor, bsp, request->seed, &plan)
                   != MAPGEN_GEOMETRY_OK) {
            rc = MAPGEN_GENERATE_ERR_PLAN;
        } else {
            MapGenGeometryEdit_SetStairMask(plan, request->stair_mask);
            uint32_t spent = 0;
            MapGenGeometryEdit_Apply(plan, candidate, donor, request->fidelity,
                                     &spent);
            if (report) {
                report->edits_offered = MapGenGeometryEdit_Count(plan);
                report->edits_spent = spent;
                for (uint32_t k = 0; k < MAPGEN_EDIT_KINDS; k++)
                    report->spent_of_kind[k] =
                        MapGenGeometryEdit_SpentOfKind(plan, request->fidelity,
                                                       (mapgen_edit_kind_t)k);
            }
        }
    }

    if (rc == MAPGEN_GENERATE_OK) {
        if (report) {
            report->candidate_brushes = MapGenGeometry_NumBrushes(candidate);
            report->candidate_sides = MapGenGeometry_NumSides(candidate);
            report->candidate_digest = MapGenGeometry_CanonicalDigest(candidate);
        }
        if (MapGenGeometry_WriteValve220(candidate, out_map)
            != MAPGEN_GEOMETRY_OK)
            rc = MAPGEN_GENERATE_ERR_WRITE;
    }

    MapGenGeometryEdit_Free(plan);
    if (candidate != donor)
        MapGenGeometry_Free(candidate);
    MapGenGeometry_Free(donor);
    MapGenBsp_Free(bsp);
    return rc;
}
