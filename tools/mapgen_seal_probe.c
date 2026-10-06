/*
 * Find the holes, by asking the same question of two maps.
 *
 * A crack in a rebuilt map is a sliver of void between two solids that used to
 * meet. It does not leak - the compiler's own flood fill runs on leaves and a
 * zero-width sliver is not a leaf a point entity can escape through - so
 * nothing in the build complains, and the first anyone knows of it is a
 * hairline of sky down a wall.
 *
 * So it is found the way a player finds it: by looking. From every standable
 * position in the DONOR, rays go out in a fixed spread of directions. Where
 * the donor's ray stops against a wall and the candidate's ray flies out of
 * the world, the two maps disagree about whether there is a wall there, and
 * the candidate is the one that is wrong.
 *
 *     mapgen_seal_probe <donor.bsp> <candidate.bsp> [rays]
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_space.h"
#include "common/mapgen_trace.h"

#define RAY_LENGTH 8192.0f

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

/* An even spread over the sphere, so no direction is favoured and the same
   set is used on both maps. */
static void spread(uint32_t i, uint32_t count, float out[3])
{
    const double golden = 3.14159265358979 * (3.0 - sqrt(5.0));
    const double z = 1.0 - 2.0 * ((double)i + 0.5) / count;
    const double r = sqrt(1.0 - z * z);
    const double theta = golden * i;
    out[0] = (float)(cos(theta) * r);
    out[1] = (float)(sin(theta) * r);
    out[2] = (float)z;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <donor.bsp> <candidate.bsp> [rays]\n",
                argv[0]);
        return 2;
    }
    const uint32_t rays = argc > 3 ? (uint32_t)strtoul(argv[3], NULL, 10) : 64;

    mapgen_bsp_t *donor = load(argv[1]);
    mapgen_bsp_t *cand = load(argv[2]);
    if (!donor || !cand) {
        fprintf(stderr, "cannot read one of them\n");
        return 2;
    }

    mapgen_space_t *space = NULL;
    mapgen_space_params_t params = MapGenSpace_DefaultParams();
    if (MapGenSpace_Build(donor, &params, &space) != MAPGEN_SPACE_OK) {
        fprintf(stderr, "the donor has no standable space\n");
        return 2;
    }

    mapgen_trace_context_t dctx, cctx;
    memset(&dctx, 0, sizeof(dctx));
    memset(&cctx, 0, sizeof(cctx));
    if (!MapGenTrace_Bind(&dctx, donor) || !MapGenTrace_Bind(&cctx, cand)) {
        fprintf(stderr, "out of memory\n");
        return 2;
    }

    const uint32_t nodes = MapGenSpace_NumNodes(space);
    uint32_t holes = 0, tested = 0;
    float worst[3] = { 0, 0, 0 }, worst_dir[3] = { 0, 0, 0 };

    for (uint32_t n = 0; n < nodes; n++) {
        const mapgen_space_node_t *node = MapGenSpace_Node(space, n);
        float eye[3];
        for (int a = 0; a < 3; a++)
            eye[a] = node->origin[a];
        eye[2] += 28.0f;              /* about where a player's eyes are */

        for (uint32_t r = 0; r < rays; r++) {
            float dir[3], end[3];
            spread(r, rays, dir);
            for (int a = 0; a < 3; a++)
                end[a] = eye[a] + dir[a] * RAY_LENGTH;

            const float zero[3] = { 0, 0, 0 };
            mapgen_trace_result_t dt, ct;
            MapGenTrace_Box(&dctx, eye, end, zero, zero, MAPGEN_TRACE_SOLID, &dt);
            if (dt.startsolid)
                continue;
            tested++;
            if (dt.fraction >= 1.0f)
                continue;             /* the donor sees out here too */

            MapGenTrace_Box(&cctx, eye, end, zero, zero, MAPGEN_TRACE_SOLID, &ct);
            if (ct.startsolid || ct.fraction < 1.0f)
                continue;

            /* The donor has a wall here and the candidate does not. */
            if (!holes) {
                memcpy(worst, eye, sizeof(worst));
                memcpy(worst_dir, dir, sizeof(worst_dir));
            }
            holes++;
        }
    }

    printf("%s vs %s: %u rays cast from %u stances, %u found a hole\n",
           argv[1], argv[2], tested, nodes, holes);
    if (holes) {
        printf("  first at %.0f %.0f %.0f looking %.3f %.3f %.3f\n",
               (double)worst[0], (double)worst[1], (double)worst[2],
               (double)worst_dir[0], (double)worst_dir[1], (double)worst_dir[2]);
    }

    MapGenTrace_Release(&dctx);
    MapGenTrace_Release(&cctx);
    MapGenSpace_Free(space);
    MapGenBsp_Free(donor);
    MapGenBsp_Free(cand);
    return holes ? 1 : 0;
}
