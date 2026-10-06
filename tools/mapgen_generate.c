/*
 * MAPGEN-1 - generate one `.map` from a corpus, from the command line.
 *
 *   mapgen_generate <out.map> <manifest.txt> <seed> <scale> <goal> <map.bsp>...
 *
 *     scale  0 compact  1 medium  2 large  3 very large
 *     goal   1 mix  2 duel  3 tdm  4 ffa  5 single player
 *
 * This is the generator's body without a UI around it: the same chain the
 * worker will run, driven by arguments instead of by a menu. It exists so the
 * result can be compiled and LOOKED AT long before the menu is written -
 * which is the only way to find out what the maps are actually like.
 */

#include "common/mapgen_architecture.h"
#include "common/mapgen_blueprint.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_mapfile.h"
#include "common/mapgen_synthesis.h"
#include "common/mapgen_lineage.h"
#include "common/mapgen_features.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

static const char *basename_of(const char *path)
{
    const char *slash = strrchr(path, '/');
    const char *back = strrchr(path, '\\');
    const char *last = slash > back ? slash : back;
    return last ? last + 1 : path;
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
    mapgen_blueprint_t *blueprint = NULL;
    mapgen_geometry_t *geometry = NULL;
    mapgen_space_params_t p = MapGenSpace_DefaultParams();
    bool ok = false;

    if (MapGenBsp_Load(data, size, &bsp) == MAPGEN_BSP_OK &&
        MapGenGenome_Extract(bsp, &genome) == MAPGEN_GENOME_OK &&
        MapGenSpace_Build(bsp, &p, &space) == MAPGEN_SPACE_OK &&
        MapGenWiring_Build(genome, bsp, &wiring) == MAPGEN_WIRING_OK &&
        MapGenFeatures_Build(bsp, genome, space, wiring, &features)
            == MAPGEN_FEATURES_OK) {
        /*
         * The source's architecture, beside its statistics. A map whose
         * blueprint cannot be built is still learned from - its materials and
         * aggregates are as good as any - it simply cannot be an architecture
         * donor.
         */
        MapGenBlueprint_Build(bsp, genome, space, &blueprint);

        /*
         * And its GEOMETRY - the solids the blueprint is an annotation over.
         * A source without it can still be learned from for materials and
         * aggregates; it simply cannot be a donor above fidelity zero, which
         * is the whole of what a donor is for.
         */
        MapGenGeometry_FromBsp(bsp, &geometry);
        ok = MapGenTraining_AddSource(t, basename_of(path), "baseq2", size, sha,
                                      features, genome, wiring, blueprint,
                                      geometry)
             == MAPGEN_TRAINING_OK;
    }

    MapGenGeometry_Free(geometry);
    MapGenBlueprint_Free(blueprint);
    MapGenFeatures_Free(features);
    MapGenWiring_Free(wiring);
    MapGenSpace_Free(space);
    MapGenGenome_Free(genome);
    MapGenBsp_Free(bsp);
    free(data);
    return ok;
}

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
        void *grown = realloc(MANIFEST,
                              (size_t)(MANIFEST_COUNT + 1) * sizeof(char *));
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

int main(int argc, char **argv)
{
    if (argc < 7) {
        printf("usage: mapgen_generate <out.map> <manifest.txt> <seed> "
               "<scale 0-3> <goal 1-5> <map.bsp>...\n");
        return 2;
    }
    const char *out_path = argv[1];
    if (!load_manifest(argv[2])) {
        printf("cannot read the target manifest: %s\n", argv[2]);
        return 1;
    }
    const uint64_t seed = strtoull(argv[3], NULL, 0);
    const int32_t scale = (int32_t)strtol(argv[4], NULL, 10);
    const mapgen_goal_t goal = (mapgen_goal_t)strtol(argv[5], NULL, 10);

    /* --- learn ------------------------------------------------------------ */
    mapgen_training_t *t = MapGenTraining_Create();
    uint32_t learned = 0;
    for (int i = 6; i < argc; i++) {
        if (add_map(t, argv[i]))
            learned++;
        else
            printf("  could not learn from %s\n", argv[i]);
    }
    if (!learned) {
        printf("nothing to learn from\n");
        return 1;
    }

    uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES], revision[MAPGEN_SNAPSHOT_UUID_BYTES];
    memset(lineage, 0xA0, sizeof(lineage));
    memset(revision, 0xA0, sizeof(revision));
    uint8_t *image = NULL;
    size_t image_size = 0;
    if (MapGenLineage_New(t, lineage, revision, 1756600000000ull,
                          MAPGEN_COMPRESSION_DEFLATE, &image, &image_size)
        != MAPGEN_LINEAGE_OK) {
        printf("could not build a snapshot\n");
        return 1;
    }
    MapGenTraining_Free(t);

    mapgen_snapshot_t *snap = NULL;
    MapGenSnapshot_Open(image, image_size, &snap);

    /* --- mix, against what the target can resolve ------------------------- */
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
        printf("could not mix a model\n");
        return 1;
    }
    printf("learned from %u maps: %u materials the target has, %u it does not,"
           " %u architecture donor(s)\n",
           learned, MapGenMix_NumMaterials(mix),
           MapGenMix_NumUnavailableMaterials(mix),
           MapGenMix_NumDonors(mix));

    /* --- the recipe, and the candidate ------------------------------------
     *
     * Both belong to MapGenSynthesis now: the product path needed the same
     * chain, and a second copy of the loadout table here would have drifted
     * from the one that ships.
     */
    char slug[MAPGEN_RECIPE_SLUG_BYTES];
    snprintf(slug, sizeof(slug), "q2mg_%08x", (unsigned)(seed & 0xFFFFFFFFu));

    /*
     * Contract 14.0. At 100 the map is a fork of its donor, which this
     * generator cannot do - that is the transaction's path, through the
     * pipeline - and at 0 it is the statistics-driven synthesis below. Taken
     * from the environment so a sweep needs no rebuild.
     */
    const char *asked_fidelity = getenv("MAPGEN_FIDELITY");
    int32_t fidelity = asked_fidelity
                     ? (int32_t)strtol(asked_fidelity, NULL, 10) : 0;
    if (fidelity < 0) fidelity = 0;
    if (fidelity > 100) fidelity = 100;

    mapgen_recipe_t *recipe = NULL;
    mapgen_synthesis_result_t rc =
        MapGenSynthesis_Recipe(mix, seed, scale, goal, fidelity, slug,
                               &recipe);
    if (rc == MAPGEN_SYNTHESIS_ERR_NOT_ZERO) {
        printf("refused: fidelity %d is the donor's own geometry, which is the"
               " transaction's path and not this one (contract 14.0)\n",
               fidelity);
        return 1;
    }
    if (rc != MAPGEN_SYNTHESIS_OK) {
        printf("refused: %s\n", MapGenSynthesis_ResultName(rc));
        return 1;
    }

    mapgen_synthesis_report_t built;
    rc = MapGenSynthesis_Write(mix, recipe, goal, 0, out_path, &built);
    MapGenRecipe_Free(recipe);
    if (rc != MAPGEN_SYNTHESIS_OK) {
        printf("refused: %s (%s)\n", MapGenSynthesis_ResultName(rc),
               built.refusal);
        return 1;
    }

    printf("%s: attempt %u, %u rooms, %u passages, %u junctions, %u pools, "
           "%u fixtures, %u brushes, %u entities (%u spawns), %zu bytes\n",
           slug, built.attempt, built.rooms, built.passages, built.junctions,
           built.pools, built.fixtures, built.brushes, built.entities,
           built.spawns, built.map_bytes);
    return 0;
}


