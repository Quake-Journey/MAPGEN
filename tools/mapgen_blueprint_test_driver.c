/*
 * MAPGEN-1 R3 - does the blueprint say what a map's architecture actually is?
 *
 *   mapgen_blueprint_test_driver <map.bsp>
 *
 * Prints the canonical blueprint on stdout for the guard to compare against
 * the independent Python oracle, and asserts the properties that must hold of
 * any blueprint whatever map it came from.
 */

#include "common/mapgen_blueprint.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int FAILED;

static void check(const char *name, bool ok, const char *detail)
{
    printf("CASE %s|%s|%s\n", ok ? "PASS" : "FAIL", name, detail ? detail : "");
    if (!ok)
        FAILED++;
}

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    const long size = ftell(f);
    if (size < 0) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) { fclose(f); return NULL; }
    *out_size = fread(data, 1, (size_t)size, f);
    fclose(f);
    return data;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        printf("usage: mapgen_blueprint_test_driver <map.bsp>\n");
        return 2;
    }

    size_t size = 0;
    uint8_t *data = read_file(argv[1], &size);
    if (!data) {
        printf("cannot read %s\n", argv[1]);
        return 2;
    }

    mapgen_bsp_t *bsp = NULL;
    mapgen_genome_t *genome = NULL;
    mapgen_space_t *space = NULL;
    mapgen_blueprint_t *bp = NULL;
    mapgen_space_params_t params = MapGenSpace_DefaultParams();

    if (MapGenBsp_Load(data, size, &bsp) != MAPGEN_BSP_OK
        || MapGenGenome_Extract(bsp, &genome) != MAPGEN_GENOME_OK
        || MapGenSpace_Build(bsp, &params, &space) != MAPGEN_SPACE_OK) {
        printf("cannot analyse %s\n", argv[1]);
        return 2;
    }

    const mapgen_blueprint_result_t rc =
        MapGenBlueprint_Build(bsp, genome, space, &bp);
    check("the blueprint builds", rc == MAPGEN_BLUEPRINT_OK,
          MapGenBlueprint_ResultName(rc));
    if (rc != MAPGEN_BLUEPRINT_OK)
        return 1;

    const uint32_t volumes = MapGenBlueprint_NumVolumes(bp);
    const uint32_t portals = MapGenBlueprint_NumPortals(bp);
    char detail[128];

    /* --- what must hold of any blueprint ---------------------------------- */
    check("a map has volumes in it", volumes > 0, "");

    bool ids_dense = true, bounds_ordered = true, on_basis = true;
    bool weight_bounded = true;
    for (uint32_t v = 0; v < volumes; v++) {
        const mapgen_blueprint_volume_t *vol = MapGenBlueprint_Volume(bp, v);
        if (vol->id != v)
            ids_dense = false;
        for (int axis = 0; axis < 3; axis++) {
            if (vol->maxs[axis] <= vol->mins[axis])
                bounds_ordered = false;
            if (vol->mins[axis] % MAPGEN_BLUEPRINT_BASIS
                || vol->maxs[axis] % MAPGEN_BLUEPRINT_BASIS)
                on_basis = false;
        }
        if (vol->occupancy_permille > 1000 || vol->landmark_weight > vol->stances)
            weight_bounded = false;
    }
    check("volume ids are dense and in order", ids_dense, "");
    check("every volume has a positive extent", bounds_ordered, "");
    check("and sits on the 16-unit basis", on_basis,
          "a volume off the basis is a volume that cannot be rebuilt on the "
          "grid the generator builds on");
    check("occupancy and landmark weight are bounded", weight_bounded, "");

    bool portals_valid = true, portals_distinct = true;
    for (uint32_t p = 0; p < portals; p++) {
        const mapgen_blueprint_portal_t *a = MapGenBlueprint_Portal(bp, p);
        if (a->from >= volumes || a->to >= volumes || a->from == a->to
            || !a->aperture)
            portals_valid = false;
        for (uint32_t q = p + 1; q < portals; q++) {
            const mapgen_blueprint_portal_t *b = MapGenBlueprint_Portal(bp, q);
            if (a->from == b->from && a->to == b->to && a->kind == b->kind)
                portals_distinct = false;
        }
    }
    check("every portal joins two different volumes that exist", portals_valid, "");
    check("and no two portals are the same edge twice", portals_distinct,
          "one crossing counted twice is one connection the fidelity ledger "
          "would think it had preserved");

    /* A one-way portal must be a one-way KIND, and the reverse. */
    bool one_way_consistent = true;
    for (uint32_t p = 0; p < portals; p++) {
        const mapgen_blueprint_portal_t *portal = MapGenBlueprint_Portal(bp, p);
        const bool kind_is_one_way = portal->kind == MAPGEN_EDGE_JUMP
                                  || portal->kind == MAPGEN_EDGE_FALL;
        if (portal->one_way != kind_is_one_way)
            one_way_consistent = false;
    }
    check("a portal is one-way exactly when its kind is", one_way_consistent,
          "a drop you can walk back up is a route the plan does not have");

    /* --- determinism ------------------------------------------------------ */
    mapgen_blueprint_t *again = NULL;
    MapGenBlueprint_Build(bsp, genome, space, &again);
    check("the same map gives the same blueprint",
          again && MapGenBlueprint_CanonicalDigest(again)
                   == MapGenBlueprint_CanonicalDigest(bp), "");
    MapGenBlueprint_Free(again);

    /* --- refusals --------------------------------------------------------- */
    mapgen_blueprint_t *refused = (mapgen_blueprint_t *)(uintptr_t)1;
    check("a missing space is refused rather than dereferenced",
          MapGenBlueprint_Build(bsp, genome, NULL, &refused)
              == MAPGEN_BLUEPRINT_ERR_ARGS && refused == NULL,
          "and the out-parameter is cleared before anything can fail");

    snprintf(detail, sizeof(detail), "%u volumes, %u portals, %u relations",
             volumes, portals, MapGenBlueprint_NumRelations(bp));
    check("summary", true, detail);

    /* --- the canonical text, for the oracle to disagree with -------------- */
    const size_t needed = MapGenBlueprint_CanonicalText(bp, NULL, 0);
    char *text = malloc(needed + 1);
    if (text) {
        MapGenBlueprint_CanonicalText(bp, text, needed + 1);
        printf("BLUEPRINT-BEGIN\n%sBLUEPRINT-END\n", text);
        free(text);
    }

    MapGenBlueprint_Free(bp);
    MapGenSpace_Free(space);
    MapGenGenome_Free(genome);
    MapGenBsp_Free(bsp);
    free(data);
    return FAILED ? 1 : 0;
}
