/*
 * Has a wall gone missing?
 *
 * The slit of sky the PO photographed is a wall that stopped being there. It
 * does not leak, because the brush that vanished was detail or was replaced by
 * something that does not fill the same volume, and the compiler's flood fill
 * only ever asks whether a point entity can escape.
 *
 * So the question is asked of the walls themselves. Every surface the donor
 * draws has solid immediately behind it - that is what makes it a surface. Step
 * one unit back along its own normal, and ask both maps what is there. Where
 * the donor says solid and the candidate says air, the candidate has lost a
 * wall, and the coordinates say which one.
 *
 *     mapgen_wall_audit <donor.bsp> <candidate.bsp> [mins xyz maxs xyz]
 *
 * The optional box is the region a deliberate edit owns - a lift shaft, say -
 * where losing solid is the point rather than the defect.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_trace.h"

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

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <donor.bsp> <candidate.bsp>"
                        " [minx miny minz maxx maxy maxz]\n", argv[0]);
        return 2;
    }

    bool have_box = argc >= 9;
    float bmins[3] = { 0, 0, 0 }, bmaxs[3] = { 0, 0, 0 };
    if (have_box) {
        for (int a = 0; a < 3; a++) {
            bmins[a] = strtof(argv[3 + a], NULL) - 8.0f;
            bmaxs[a] = strtof(argv[6 + a], NULL) + 8.0f;
        }
    }

    mapgen_bsp_t *donor = load(argv[1]);
    mapgen_bsp_t *cand = load(argv[2]);
    if (!donor || !cand) {
        fprintf(stderr, "cannot read one of them\n");
        return 2;
    }

    mapgen_trace_context_t dctx, cctx;
    memset(&dctx, 0, sizeof(dctx));
    memset(&cctx, 0, sizeof(cctx));
    MapGenTrace_Bind(&dctx, donor);
    MapGenTrace_Bind(&cctx, cand);

    const uint32_t faces = MapGenBsp_NumFaces(donor);
    uint32_t checked = 0, lost = 0, lost_outside = 0;
    float first[3] = { 0, 0, 0 };

    for (uint32_t f = 0; f < faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(donor, f);
        if (face->numedges < 3)
            continue;
        const mapgen_bsp_plane_t *plane =
            MapGenBsp_Plane(donor, face->planenum);

        /* The face's own middle, and the direction that points into the solid
           it belongs to. */
        double c[3] = { 0, 0, 0 };
        for (int32_t e = 0; e < face->numedges; e++) {
            const int32_t se = MapGenBsp_SurfEdge(donor, (uint32_t)(face->firstedge + e));
            const mapgen_bsp_edge_t *edge =
                MapGenBsp_Edge(donor, (uint32_t)(se < 0 ? -se : se));
            const mapgen_bsp_vertex_t *v =
                MapGenBsp_Vertex(donor, se < 0 ? edge->v[1] : edge->v[0]);
            for (int a = 0; a < 3; a++)
                c[a] += v->point[a];
        }
        for (int a = 0; a < 3; a++)
            c[a] /= face->numedges;

        float behind[3];
        const float sign = face->side ? 1.0f : -1.0f;
        for (int a = 0; a < 3; a++)
            behind[a] = (float)c[a] + plane->normal[a] * sign * 1.0f;

        const int32_t d = MapGenTrace_PointContents(&dctx, behind);
        if (!(d & MAPGEN_TRACE_SOLID))
            continue;                  /* not a wall we can reason about */
        checked++;

        const int32_t k = MapGenTrace_PointContents(&cctx, behind);
        if (k & MAPGEN_TRACE_SOLID)
            continue;

        lost++;
        bool inside_box = have_box;
        for (int a = 0; a < 3 && inside_box; a++)
            inside_box = behind[a] >= bmins[a] && behind[a] <= bmaxs[a];
        if (inside_box)
            continue;

        if (!lost_outside)
            memcpy(first, behind, sizeof(first));
        lost_outside++;
    }

    printf("%u of the donor's surfaces have solid behind them; the candidate"
           " has lost %u", checked, lost);
    if (have_box)
        printf(", %u of them outside the edit's own box", lost_outside);
    printf("\n");
    if (lost_outside)
        printf("  first at %.0f %.0f %.0f\n", (double)first[0],
               (double)first[1], (double)first[2]);

    MapGenTrace_Release(&dctx);
    MapGenTrace_Release(&cctx);
    MapGenBsp_Free(donor);
    MapGenBsp_Free(cand);
    return (have_box ? lost_outside : lost) ? 1 : 0;
}
