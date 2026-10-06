/*
 * Sample two maps for a gap in the solid, finely, where one is suspected.
 *
 * The ray probe casts from a player's eye and misses a hairline; the edge
 * count says a rebuild has more loose ends than its donor but not whether any
 * of them is a hole. This asks the only question that settles it: is there a
 * place the donor calls solid and the candidate calls empty, and how wide is
 * it.
 *
 *     mapgen_gap_probe <donor.bsp> <candidate.bsp> <x> <y> <z> [radius] [step]
 */

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
    if (argc < 6) {
        fprintf(stderr,
                "usage: %s <donor.bsp> <candidate.bsp> <x> <y> <z> "
                "[radius] [step]\n", argv[0]);
        return 2;
    }
    const float cx = strtof(argv[3], NULL);
    const float cy = strtof(argv[4], NULL);
    const float cz = strtof(argv[5], NULL);
    const float radius = argc > 6 ? strtof(argv[6], NULL) : 48.0f;
    const float step = argc > 7 ? strtof(argv[7], NULL) : 0.5f;

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

    uint32_t solid_only_donor = 0, solid_only_cand = 0, samples = 0;
    float first[3] = { 0, 0, 0 };

    for (float x = cx - radius; x <= cx + radius; x += step) {
        for (float y = cy - radius; y <= cy + radius; y += step) {
            for (float z = cz - radius; z <= cz + radius; z += step) {
                const float p[3] = { x, y, z };
                const int32_t d = MapGenTrace_PointContents(&dctx, p);
                const int32_t c = MapGenTrace_PointContents(&cctx, p);
                samples++;
                if ((d & MAPGEN_TRACE_SOLID) && !(c & MAPGEN_TRACE_SOLID)) {
                    if (!solid_only_donor)
                        memcpy(first, p, sizeof(first));
                    solid_only_donor++;
                } else if (!(d & MAPGEN_TRACE_SOLID) && (c & MAPGEN_TRACE_SOLID)) {
                    solid_only_cand++;
                }
            }
        }
    }

    printf("around (%.0f %.0f %.0f) +-%.0f at %.2f: %u samples,"
           " %u solid only in the donor, %u solid only in the candidate\n",
           (double)cx, (double)cy, (double)cz, (double)radius, (double)step,
           samples, solid_only_donor, solid_only_cand);
    if (solid_only_donor)
        printf("  the candidate first loses solid at %.2f %.2f %.2f\n",
               (double)first[0], (double)first[1], (double)first[2]);

    MapGenTrace_Release(&dctx);
    MapGenTrace_Release(&cctx);
    MapGenBsp_Free(donor);
    MapGenBsp_Free(cand);
    return solid_only_donor ? 1 : 0;
}
