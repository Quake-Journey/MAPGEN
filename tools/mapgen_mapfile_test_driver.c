/*
 * MAPGEN-1 map-file test driver.
 *
 * Compiled and run by tools/check_mapgen_mapfile_contract.py.
 *
 *   driver run <out.map> <map.bsp> <map.bsp> <map.bsp>
 *
 * Writes one `.map` through the whole chain and prints what it believes it
 * wrote. The guard then parses the file in Python and checks that belief
 * against the bytes - including recomputing every plane the way qbsp3 will.
 */

#include "common/mapgen_mapfile.h"
#include "common/mapgen_lineage.h"
#include "common/mapgen_features.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>


/* --------------------------------------------------------------------------
 * The target manifest, read from the file the guard generated with
 * tools/mapgen_target_manifest.py - the names that really resolve as textures
 * in the frozen target view. Contract 15: an allowlist that was not filtered
 * against this is a list of things that may not exist where the map is going.
 */

static char **MANIFEST;
static uint32_t MANIFEST_COUNT;

static bool load_manifest(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return false;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = '\0';
        if (!n)
            continue;
        void *grown = realloc(MANIFEST, (size_t)(MANIFEST_COUNT + 1) * sizeof(char *));
        if (!grown) {
            fclose(f);
            return false;
        }
        MANIFEST = grown;
        MANIFEST[MANIFEST_COUNT] = malloc(n + 1);
        if (!MANIFEST[MANIFEST_COUNT]) {
            fclose(f);
            return false;
        }
        memcpy(MANIFEST[MANIFEST_COUNT], line, n + 1);
        MANIFEST_COUNT++;
    }
    fclose(f);
    return MANIFEST_COUNT > 0;
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
    const size_t got = fread(data, 1, (size_t)size, f);
    fclose(f);
    *out_size = got;
    return data;
}

static bool add_map(mapgen_training_t *t, const char *path)
{
    size_t size = 0;
    uint8_t *data = read_file(path, &size);
    if (!data)
        return false;
    uint8_t sha[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(data, size, sha);

    mapgen_bsp_t *bsp = NULL;
    mapgen_genome_t *genome = NULL;
    mapgen_space_t *space = NULL;
    mapgen_wiring_t *wiring = NULL;
    mapgen_features_t *features = NULL;
    mapgen_space_params_t p = MapGenSpace_DefaultParams();
    bool ok = false;

    if (MapGenBsp_Load(data, size, &bsp) == MAPGEN_BSP_OK &&
        MapGenGenome_Extract(bsp, &genome) == MAPGEN_GENOME_OK &&
        MapGenSpace_Build(bsp, &p, &space) == MAPGEN_SPACE_OK &&
        MapGenWiring_Build(genome, bsp, &wiring) == MAPGEN_WIRING_OK &&
        MapGenFeatures_Build(bsp, genome, space, wiring, &features)
            == MAPGEN_FEATURES_OK)
        ok = MapGenTraining_AddSource(t, path, "baseq2", size, sha,
                                      features, genome, wiring,
                                      /* this driver learns statistics, not architecture:
                                         neither a shape nor a solid */
                                      NULL, NULL)
             == MAPGEN_TRAINING_OK;

    MapGenFeatures_Free(features);
    MapGenWiring_Free(wiring);
    MapGenSpace_Free(space);
    MapGenGenome_Free(genome);
    MapGenBsp_Free(bsp);
    free(data);
    return ok;
}

int main(int argc, char **argv)
{
    if (argc < 7 || strcmp(argv[1], "run")) {
        printf("usage: driver run <out.map> <manifest.txt> <3 map paths>\n");
        return 2;
    }
    const char *out_path = argv[2];

    if (!load_manifest(argv[3])) {
        printf("MANIFEST_FAILED\n");
        return 1;
    }

    mapgen_training_t *t = MapGenTraining_Create();
    for (int i = 4; i < argc; i++) {
        if (!add_map(t, argv[i])) {
            printf("TRAIN_FAILED\n");
            return 1;
        }
    }
    uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES], revision[MAPGEN_SNAPSHOT_UUID_BYTES];
    memset(lineage, 0xA0, sizeof(lineage));
    memset(revision, 0xA0, sizeof(revision));
    uint8_t *image = NULL;
    size_t image_size = 0;
    if (MapGenLineage_New(t, lineage, revision, 1756600000000ull,
                          MAPGEN_COMPRESSION_DEFLATE, &image, &image_size)
        != MAPGEN_LINEAGE_OK) {
        printf("LINEAGE_FAILED\n");
        return 1;
    }
    MapGenTraining_Free(t);

    mapgen_snapshot_t *snap = NULL;
    MapGenSnapshot_Open(image, image_size, &snap);
    mapgen_mix_input_t in;
    memset(&in, 0, sizeof(in));
    in.snapshot = snap;
    memcpy(in.revision_uuid, MapGenSnapshot_Header(snap)->revision_uuid,
           MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(in.payload_sha256, MapGenSnapshot_Header(snap)->payload_sha256,
           MAPGEN_SHA256_BYTES);
    in.weight = 100;
    mapgen_mix_options_t options;
    memset(&options, 0, sizeof(options));
    options.available = (const char *const *)MANIFEST;
    options.num_available = MANIFEST_COUNT;
    mapgen_mix_t *mix = NULL;
    if (MapGenMix_Build(&in, 1, &options, &mix) != MAPGEN_MIX_OK) {
        printf("MIX_FAILED\n");
        return 1;
    }

    mapgen_recipe_builder_t *rb = MapGenRecipe_BuilderCreate();
    uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
    memset(uuid, 0x77, sizeof(uuid));
    MapGenRecipe_SetIdentity(rb, uuid, 0x1D1D1D1D1D1D1D1Dull);
    MapGenRecipe_SetRequest(rb, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA, 2, 8, 32, 0);
    MapGenRecipe_SetOutput(rb, "Generated", "q2mg_demo");
    mapgen_recipe_snapshot_t rs;
    memset(&rs, 0, sizeof(rs));
    memset(rs.revision_uuid, 0x11, sizeof(rs.revision_uuid));
    rs.weight = 50;
    MapGenRecipe_AddSnapshot(rb, &rs);
    MapGenRecipe_AddControl(rb, "map_scale", 1, 1);
    MapGenRecipe_AddControl(rb, "arch_verticality", 2, 2);
    for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
        const char *c = MapGenTopology_RouteControl((mapgen_route_kind_t)k);
        if (!c)
            continue;
        const uint32_t role = MapGenTopology_RouteRole((mapgen_route_kind_t)k);
        const int32_t level = (!role || MapGenMix_RoleIsLearned(mix, role)) ? 2 : 0;
        MapGenRecipe_AddControl(rb, c, level, level);
    }
    MapGenRecipe_AddControl(rb, "weapon_railgun", 1, 1);
    MapGenRecipe_AddControl(rb, "item_health", 4, 4);

    uint8_t *rbytes = NULL;
    size_t rsize = 0;
    if (MapGenRecipe_Finish(rb, &rbytes, &rsize) != MAPGEN_RECIPE_OK) {
        printf("RECIPE_FAILED\n");
        return 1;
    }
    MapGenRecipe_BuilderFree(rb);
    mapgen_recipe_t *recipe = NULL;
    MapGenRecipe_Open(rbytes, rsize, &recipe);
    free(rbytes);

    for (uint32_t attempt = 0; attempt < 32; attempt++) {
        mapgen_topology_t *topology = NULL;
        if (MapGenTopology_Build(mix, recipe, attempt, NULL, &topology)
            != MAPGEN_TOPOLOGY_OK)
            continue;
        mapgen_layout_t *layout = NULL;
        if (MapGenLayout_Build(topology, mix, recipe, attempt, &layout)
            != MAPGEN_LAYOUT_OK) {
            MapGenTopology_Free(topology);
            continue;
        }
        mapgen_brushwork_t *work = NULL;
        if (MapGenBrush_Build(layout, mix, recipe, attempt, &work)
            != MAPGEN_BRUSH_OK) {
            MapGenLayout_Free(layout);
            MapGenTopology_Free(topology);
            continue;
        }
        mapgen_entities_t *entities = NULL;
        if (MapGenEntities_Build(layout, topology, mix, recipe, attempt, NULL,
                                 &entities) != MAPGEN_ENTITIES_OK) {
            MapGenBrush_Free(work);
            MapGenLayout_Free(layout);
            MapGenTopology_Free(topology);
            continue;
        }

        char *text = NULL;
        size_t size = 0;
        const mapgen_mapfile_result_t r =
            MapGenMapFile_Write(work, entities, mix, recipe, &text, &size);
        if (r != MAPGEN_MAPFILE_OK) {
            printf("WRITE_FAILED %s\n", MapGenMapFile_ResultName(r));
            return 1;
        }

        /* Twice, to prove the writer is a function of its inputs. */
        char *again = NULL;
        size_t again_size = 0;
        MapGenMapFile_Write(work, entities, mix, recipe, &again, &again_size);
        const bool identical = again && again_size == size
                             && !memcmp(again, text, size);
        free(again);

        FILE *f = fopen(out_path, "wb");
        if (!f) {
            printf("CANNOT_WRITE\n");
            return 1;
        }
        fwrite(text, 1, size, f);
        fclose(f);

        /* What the writer believes it wrote. The guard checks the bytes. */
        printf("BRUSHES %u\n", MapGenBrush_Count(work));
        printf("ENTITIES %u\n", MapGenEntities_Count(entities));
        printf("FIXTURES %u\n", MapGenBrush_NumFixtures(work));
        printf("MARKERS %u\n", MapGenBrush_NumMarkers(work));
        printf("BYTES %zu\n", size);
        printf("IDENTICAL %d\n", identical ? 1 : 0);
        printf("RAILGUNS %u\n",
               MapGenEntities_CountOf(entities, "weapon_railgun"));
        printf("HEALTH %u\n", MapGenEntities_CountOf(entities, "item_health"));
        printf("SPAWNS %u\n",
               MapGenEntities_CountOf(entities, "info_player_deathmatch"));
        for (uint32_t i = 0; i < MapGenMix_NumMaterials(mix); i++)
            printf("MATERIAL %s\n", MapGenMix_MaterialName(mix, i));

        free(text);
        MapGenEntities_Free(entities);
        MapGenBrush_Free(work);
        MapGenLayout_Free(layout);
        MapGenTopology_Free(topology);
        MapGenRecipe_Free(recipe);
        MapGenMix_Free(mix);
        MapGenSnapshot_Free(snap);
        free(image);
        return 0;
    }

    printf("NO_CANDIDATE\n");
    return 1;
}
