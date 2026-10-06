/*
 * GF4 - take a donor BSP apart into canonical geometry and write it back out
 * as a `.map`, so the pinned compiler can rebuild it.
 *
 * This is the whole fidelity-100 claim in one program: if what comes out the
 * far end is the donor, then the representation carries an architecture, and
 * if it is not, the numbers below say exactly which part went missing. The
 * previous path could not have been asked this question at all - it never held
 * a donor plane to begin with.
 *
 *     mapgen_geometry_fork <donor.bsp> <out.map> [fidelity 0..100] [seed]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_geometry_edit.h"

static uint8_t *slurp(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0) {
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

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <donor.bsp> <out.map> [fidelity] [seed]\n",
                argv[0]);
        return 2;
    }
    const int32_t fidelity = argc > 3 ? (int32_t)strtol(argv[3], NULL, 10) : 100;
    const uint64_t seed = argc > 4 ? strtoull(argv[4], NULL, 10) : 1;

    /*
     * Two knobs the qualification pass uses. MAPGEN_QUALIFY_STAIR builds a
     * candidate carrying nothing but that one staircase replacement, so the
     * compiler can give it a verdict on its own; MAPGEN_STAIR_MASK then tells
     * a real run which staircases earned one.
     */
    const char *qualify = getenv("MAPGEN_QUALIFY_STAIR");
    const char *mask_text = getenv("MAPGEN_STAIR_MASK");
    const uint64_t stair_mask = mask_text ? strtoull(mask_text, NULL, 0)
                                          : UINT64_MAX;
    if (fidelity < 0 || fidelity > 100) {
        fprintf(stderr, "fidelity is 0..100\n");
        return 2;
    }

    size_t size = 0;
    uint8_t *raw = slurp(argv[1], &size);
    if (!raw) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 1;
    }

    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t br = MapGenBsp_Load(raw, size, &bsp);
    free(raw);
    if (br != MAPGEN_BSP_OK) {
        fprintf(stderr, "bsp refused it: %d\n", (int)br);
        return 1;
    }

    mapgen_geometry_t *g = NULL;
    const mapgen_geometry_result_t gr = MapGenGeometry_FromBsp(bsp, &g);
    if (gr != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "geometry refused it: %s\n",
                MapGenGeometry_ResultName(gr));
        MapGenBsp_Free(bsp);
        return 1;
    }

    /*
     * What was carried, counted against what the donor had. The two numbers
     * that mattered in the failure - oblique planes and sides per brush - are
     * reported first, because they are what a box shell cannot have.
     */
    const uint32_t brushes = MapGenGeometry_NumBrushes(g);
    const uint32_t sides = MapGenGeometry_NumSides(g);
    uint32_t oblique = 0, bevels = 0, textured = 0, oblique_bevel = 0;
    for (uint32_t s = 0; s < sides; s++) {
        const mapgen_geometry_side_t *side = MapGenGeometry_Side(g, s);
        const bool axial = (side->normal[0] == 1.0f || side->normal[0] == -1.0f)
                        || (side->normal[1] == 1.0f || side->normal[1] == -1.0f)
                        || (side->normal[2] == 1.0f || side->normal[2] == -1.0f);
        if (!axial)
            oblique++;
        if (side->bevel) {
            bevels++;
            if (!axial)
                oblique_bevel++;
        }
        if (side->texture[0])
            textured++;
    }

    /* Every brush must land inside some entity, or geometry is lost in the
       writing rather than in the reading, which is harder to see. */
    uint32_t placed = 0;
    for (uint32_t b = 0; b < brushes; b++) {
        const mapgen_geometry_brush_t *brush = MapGenGeometry_Brush(g, b);
        for (uint32_t e = 0; e < MapGenGeometry_NumEntities(g); e++) {
            const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(g, e);
            if (ent->model == brush->model && (brush->model != 0 || e == 0)) {
                placed++;
                break;
            }
        }
    }

    printf("donor %s\n", argv[1]);
    printf("  brushes %u, sides %u (%.2f per brush), oblique %u, bevels %u,"
           " textured %u\n",
           brushes, sides, brushes ? (double)sides / brushes : 0.0,
           oblique, bevels, textured);
    printf("  of the oblique sides, %u have no winding of their own\n",
           oblique_bevel);
    printf("  models %u, entities %u, brushes placed in an entity %u/%u\n",
           MapGenGeometry_NumModels(g), MapGenGeometry_NumEntities(g),
           placed, brushes);
    printf("  canonical digest %016llx\n",
           (unsigned long long)MapGenGeometry_CanonicalDigest(g));

    if (placed != brushes) {
        fprintf(stderr, "REFUSED: %u brushes belong to no entity\n",
                brushes - placed);
        MapGenGeometry_Free(g);
        MapGenBsp_Free(bsp);
        return 1;
    }

    /*
     * Below 100 the candidate is a clone that the schedule then diverges. The
     * donor itself is never edited: the plan is measured against the donor's
     * compiled truth, and an operator that had already changed it would be
     * asking its questions of a map that no longer exists.
     */
    mapgen_geometry_t *candidate = g;
    mapgen_geometry_edit_plan_t *plan = NULL;
    uint32_t spent = 0;

    if (fidelity < 100) {
        if (MapGenGeometry_Clone(g, &candidate) != MAPGEN_GEOMETRY_OK) {
            fprintf(stderr, "out of memory cloning the donor\n");
            MapGenGeometry_Free(g);
            MapGenBsp_Free(bsp);
            return 1;
        }
        const mapgen_geometry_result_t pr =
            MapGenGeometryEdit_Plan(g, bsp, seed, &plan);
        if (pr != MAPGEN_GEOMETRY_OK) {
            fprintf(stderr, "planning refused it: %s\n",
                    MapGenGeometry_ResultName(pr));
            MapGenGeometry_Free(candidate);
            MapGenGeometry_Free(g);
            MapGenBsp_Free(bsp);
            return 1;
        }
        MapGenGeometryEdit_SetStairMask(plan, stair_mask);
        if (qualify) {
            const uint32_t which = (uint32_t)strtoul(qualify, NULL, 10);
            printf("  qualifying staircase %u of %u\n", which,
                   MapGenGeometryEdit_NumStairs(plan));
            if (which >= MapGenGeometryEdit_NumStairs(plan)) {
                fprintf(stderr, "no such staircase\n");
                return 1;
            }
            float smins[3], smaxs[3];
            if (MapGenGeometryEdit_StairBounds(plan, which, smins, smaxs)) {
                printf("  stair bounds %.0f %.0f %.0f %.0f %.0f %.0f\n",
                       (double)smins[0], (double)smins[1], (double)smins[2],
                       (double)smaxs[0], (double)smaxs[1], (double)smaxs[2]);
            }
            MapGenGeometryEdit_ApplyOneStair(plan, candidate, g, which);
            spent = 1;
        } else {
            MapGenGeometryEdit_Apply(plan, candidate, g, fidelity, &spent);
        }

        printf("  fidelity %d: %u of %u scheduled edits spent"
               "\n",
               fidelity, spent, MapGenGeometryEdit_Count(plan));
        /* What was actually spent, kind by kind: "the map has this many
           lifts in it" is the thing worth reading, not how many the schedule
           could have offered. */
        printf("    spent:");
        for (uint32_t k = 0; k < MAPGEN_EDIT_KINDS; k++) {
            const uint32_t of_kind =
                MapGenGeometryEdit_SpentOfKind(plan, fidelity,
                                               (mapgen_edit_kind_t)k);
            if (of_kind)
                printf(" %u %s,", of_kind,
                       MapGenGeometryEdit_KindName((mapgen_edit_kind_t)k));
        }
        printf("\n");
        printf("  candidate brushes %u, sides %u, digest %016llx\n",
               MapGenGeometry_NumBrushes(candidate),
               MapGenGeometry_NumSides(candidate),
               (unsigned long long)MapGenGeometry_CanonicalDigest(candidate));
    } else {
        printf("  fidelity 100: the candidate is the donor's own geometry\n");
    }

    const mapgen_geometry_result_t wr =
        MapGenGeometry_WriteValve220(candidate, argv[2]);
    if (wr != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "write refused it: %s\n", MapGenGeometry_ResultName(wr));
        MapGenGeometry_Free(g);
        MapGenBsp_Free(bsp);
        return 1;
    }
    printf("  wrote %s\n", argv[2]);

    if (candidate != g)
        MapGenGeometry_Free(candidate);
    MapGenGeometryEdit_Free(plan);
    MapGenGeometry_Free(g);
    MapGenBsp_Free(bsp);
    return 0;
}
