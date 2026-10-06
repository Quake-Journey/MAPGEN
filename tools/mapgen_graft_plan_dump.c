/*
 * What a schedule offers when it is given more than one donor.
 *
 *     mapgen_graft_plan_dump DONOR.bsp SEED [OTHER.bsp ...]
 *
 * GF7 requires a major intact contribution from every active donor and forbids
 * silent omission, so both halves have to be answerable BEFORE anything is
 * compiled: which donors can contribute a room at all, and how many.
 *
 * One line per graft the plan found - which of our rooms it replaces, which
 * donor the replacement comes from, and the turn that lines its ways out up -
 * and then a tally per donor, which is what a contribution floor is checked
 * against. A donor with no line is a donor that offered nothing, and this says
 * so by name rather than leaving it to be noticed.
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_geometry_edit.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_OTHERS 8

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
    uint8_t *data = size > 0 ? malloc((size_t)size) : NULL;
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size) {
        free(data);
        fclose(f);
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

/* The map's name, which is what provenance is recorded as. */
static const char *name_of(const char *path)
{
    const char *slash = strrchr(path, '/');
    const char *back = strrchr(path, '\\');
    if (back > slash)
        slash = back;
    return slash ? slash + 1 : path;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s DONOR.bsp SEED [OTHER.bsp ...]\n", argv[0]);
        return 2;
    }
    const uint64_t seed = strtoull(argv[2], NULL, 10);
    /* Where to write the map the first graft produces, if asked. */
    const char *out_map = NULL;
    for (int i = 3; i + 1 < argc; i++)
        if (!strcmp(argv[i], "--out"))
            out_map = argv[i + 1];

    mapgen_bsp_t *donor_bsp = load(argv[1]);
    if (!donor_bsp)
        return 2;
    mapgen_geometry_t *donor = NULL;
    if (MapGenGeometry_FromBsp(donor_bsp, &donor) != MAPGEN_GEOMETRY_OK) {
        MapGenBsp_Free(donor_bsp);
        return 2;
    }

    const mapgen_bsp_t *other_bsps[MAX_OTHERS];
    const mapgen_geometry_t *others[MAX_OTHERS];
    const char *names[MAX_OTHERS];
    mapgen_bsp_t *own_bsp[MAX_OTHERS];
    mapgen_geometry_t *own[MAX_OTHERS];
    uint32_t num_others = 0;

    for (int i = 3; i < argc && num_others < MAX_OTHERS; i++) {
        if (!strcmp(argv[i], "--out")) {
            i++;
            continue;
        }
        mapgen_bsp_t *bsp = load(argv[i]);
        if (!bsp)
            continue;
        mapgen_geometry_t *g = NULL;
        if (MapGenGeometry_FromBsp(bsp, &g) != MAPGEN_GEOMETRY_OK) {
            MapGenBsp_Free(bsp);
            continue;
        }
        own_bsp[num_others] = bsp;
        own[num_others] = g;
        other_bsps[num_others] = bsp;
        others[num_others] = g;
        names[num_others] = name_of(argv[i]);
        num_others++;
    }

    printf("donor %s, seed %llu, %u other donor(s)\n", name_of(argv[1]),
           (unsigned long long)seed, num_others);

    mapgen_geometry_edit_plan_t *plan = NULL;
    const mapgen_geometry_result_t rc =
        MapGenGeometryEdit_PlanWith(donor, donor_bsp, seed, others, other_bsps,
                                    names, num_others, &plan);
    printf("plan %s\n", MapGenGeometry_ResultName(rc));

    if (rc == MAPGEN_GEOMETRY_OK) {
        const uint32_t edits = MapGenGeometryEdit_Count(plan);
        const uint32_t grafts = MapGenGeometryEdit_NumGrafts(plan);
        printf("edits %u, grafts %u\n", edits, grafts);
        /* And the pairs that were compared and refused, which is the
           half of a graft plan a count of zero hides. */
        if (MapGenGeometryEdit_RefusalsSeen(plan)) {
            printf("refused %u (showing %u):\n",
                   MapGenGeometryEdit_RefusalsSeen(plan),
                   MapGenGeometryEdit_NumRefusals(plan));
            for (uint32_t i = 0;
                 i < MapGenGeometryEdit_NumRefusals(plan); i++)
                printf("  %s\n",
                       MapGenGeometryEdit_Refusal(plan, i));
        }
        for (uint32_t i = 0; i < grafts; i++) {
            const char *from = MapGenGeometryEdit_GraftedFrom(plan, i);
            printf("graft %u from %s\n", i, from ? from : "(unnamed)");
        }
        /*
         * And the tally a contribution floor is checked against. A donor that
         * offered nothing is named here rather than being noticed by its
         * absence from the list above.
         */
        for (uint32_t d = 0; d < num_others; d++) {
            uint32_t mine = 0;
            for (uint32_t i = 0; i < grafts; i++) {
                const char *from = MapGenGeometryEdit_GraftedFrom(plan, i);
                if (from && !strcmp(from, names[d]))
                    mine++;
            }
            printf("donor %s offers %u\n", names[d], mine);
        }
        /*
         * And it is applied, because a plan nobody applied is a plan nobody
         * has measured. The candidate is the donor's own geometry cloned - the
         * transaction's own starting point - and what comes out is written so
         * the compiler can be asked whether it is a map.
         */
        if (grafts && out_map) {
            mapgen_geometry_t *candidate = NULL;
            if (MapGenGeometry_Clone(donor, &candidate)
                == MAPGEN_GEOMETRY_OK) {
                const uint32_t before = MapGenGeometry_NumBrushes(candidate);
                bool changed = false;
                uint32_t at = 0;
                for (uint32_t i = 0; i < edits; i++) {
                    const mapgen_geometry_edit_t *e =
                        MapGenGeometryEdit_At(plan, i);
                    if (e && e->kind == MAPGEN_EDIT_GRAFT_BUNDLE) {
                        at = i;
                        break;
                    }
                }
                const mapgen_geometry_result_t ar =
                    MapGenGeometryEdit_ApplyOne(plan, candidate, donor, at,
                                                &changed);
                printf("applied %s, changed %s\n",
                       MapGenGeometry_ResultName(ar), changed ? "yes" : "no");
                printf("brushes %u -> %u\n", before,
                       MapGenGeometry_NumBrushes(candidate));
                const mapgen_geometry_result_t wr =
                    MapGenGeometry_WriteValve220(candidate, out_map);
                printf("wrote %s\n", MapGenGeometry_ResultName(wr));
            }
            MapGenGeometry_Free(candidate);
        }
        MapGenGeometryEdit_Free(plan);
    }

    MapGenGeometry_Free(donor);
    MapGenBsp_Free(donor_bsp);
    for (uint32_t i = 0; i < num_others; i++) {
        MapGenGeometry_Free(own[i]);
        MapGenBsp_Free(own_bsp[i]);
    }
    return rc == MAPGEN_GEOMETRY_OK ? 0 : 1;
}
