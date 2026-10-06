/*
 * MAPGEN-1 snapshot mixing test driver.
 *
 * Compiled and run by tools/check_mapgen_mix_contract.py.
 *
 *   driver run <map.bsp> <map.bsp> <map.bsp> <map.bsp>
 *
 * Trains two snapshots from OVERLAPPING halves of the maps given - maps 0,1,2
 * and maps 1,2,3 - so the shared-source rule has real shared sources to act on
 * rather than a constructed pair, and then exercises what contract 9 requires
 * of a mix.
 *
 * The material union is recomputed here from the snapshots' own chunks, so the
 * allowlist is compared against an independent answer instead of against the
 * module's own bookkeeping.
 */

#include "common/mapgen_mix.h"
#include "common/mapgen_lineage.h"
#include "common/mapgen_features.h"
#include "common/mapgen_random.h"
#include "common/mapgen_wiring.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int CASES;
static int FAILED;

static void check(const char *name, bool ok, const char *detail)
{
    CASES++;
    if (ok) {
        printf("  PASS  %s\n", name);
        return;
    }
    FAILED++;
    printf("  FAIL  %s%s%s\n", name, detail && *detail ? "  -- " : "",
           detail ? detail : "");
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
    mapgen_space_params_t p = MapGenSpace_DefaultParams();
    bool ok = false;

    if (MapGenBsp_Load(data, size, &bsp) == MAPGEN_BSP_OK &&
        MapGenGenome_Extract(bsp, &genome) == MAPGEN_GENOME_OK &&
        MapGenSpace_Build(bsp, &p, &space) == MAPGEN_SPACE_OK &&
        MapGenWiring_Build(genome, bsp, &wiring) == MAPGEN_WIRING_OK &&
        MapGenFeatures_Build(bsp, genome, space, wiring, &features)
            == MAPGEN_FEATURES_OK) {
        ok = MapGenTraining_AddSource(t, basename_of(path), "baseq2", size, sha,
                                      features, genome, wiring,
                                      /* this driver learns statistics, not architecture:
                                         neither a shape nor a solid */
                                      NULL, NULL)
             == MAPGEN_TRAINING_OK;
    }
    MapGenFeatures_Free(features);
    MapGenWiring_Free(wiring);
    MapGenSpace_Free(space);
    MapGenGenome_Free(genome);
    MapGenBsp_Free(bsp);
    free(data);
    return ok;
}

/* Build one snapshot from the map paths listed. */
static mapgen_snapshot_t *make_snapshot(char **paths, int count, uint8_t tag,
                                        uint8_t **owned, size_t *owned_size)
{
    mapgen_training_t *t = MapGenTraining_Create();
    if (!t)
        return NULL;
    for (int i = 0; i < count; i++) {
        if (!add_map(t, paths[i])) {
            MapGenTraining_Free(t);
            return NULL;
        }
    }

    uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES], revision[MAPGEN_SNAPSHOT_UUID_BYTES];
    memset(lineage, tag, sizeof(lineage));
    memset(revision, tag, sizeof(revision));

    size_t size = 0;
    *owned_size = 0;
    const mapgen_lineage_result_t r =
        MapGenLineage_New(t, lineage, revision, 1756600000000ull,
                          MAPGEN_COMPRESSION_DEFLATE, owned, &size);
    MapGenTraining_Free(t);
    if (r != MAPGEN_LINEAGE_OK)
        return NULL;
    *owned_size = size;

    mapgen_snapshot_t *snap = NULL;
    if (MapGenSnapshot_Open(*owned, size, &snap) != MAPGEN_SNAPSHOT_OK)
        return NULL;
    return snap;
}

static void pin(mapgen_mix_input_t *input, const mapgen_snapshot_t *snap,
                uint32_t weight)
{
    const mapgen_snapshot_header_t *h = MapGenSnapshot_Header(snap);
    memset(input, 0, sizeof(*input));
    input->snapshot = snap;
    memcpy(input->revision_uuid, h->revision_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(input->payload_sha256, h->payload_sha256, MAPGEN_SHA256_BYTES);
    input->weight = weight;
}

/* --------------------------------------------------------------------------
 * The union, computed here rather than asked of the module under test.
 */

#define NAME_BYTES 33

static char (*UNION_NAMES)[NAME_BYTES];
static uint32_t *UNION_ROLES;
static uint32_t UNION_COUNT;

static bool union_has(const char *name)
{
    for (uint32_t i = 0; i < UNION_COUNT; i++)
        if (name && !strcmp(UNION_NAMES[i], name))
            return true;
    return false;
}

static void union_scan(const mapgen_snapshot_t *snap)
{
    size_t size = 0;
    const uint8_t *text = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_MATERIALS, &size);
    if (!text)
        return;
    for (size_t i = 0; i + 2 <= size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (memcmp(text + i, "m=", 2))
            continue;
        const uint8_t *body = text + i + 2;
        size_t n = 0;
        while (i + 2 + n < size && body[n] != ',' && body[n] != '\n')
            n++;
        if (!n || n >= NAME_BYTES)
            continue;
        char name[NAME_BYTES];
        memcpy(name, body, n);
        name[n] = '\0';
        /* `name,roles,flags,contents,...` - the roles are the next field. */
        uint32_t roles = 0;
        {
            size_t at = n + 1;
            while (i + 2 + at < size && body[at] >= '0' && body[at] <= '9') {
                roles = roles * 10u + (uint32_t)(body[at] - '0');
                at++;
            }
        }

        for (uint32_t k = 0; k < UNION_COUNT; k++) {
            if (!strcmp(UNION_NAMES[k], name)) {
                UNION_ROLES[k] |= roles;    /* the union, as the model does */
                break;
            }
        }
        if (union_has(name))
            continue;

        void *grown = realloc(UNION_NAMES, (size_t)(UNION_COUNT + 1) * NAME_BYTES);
        if (!grown)
            return;
        UNION_NAMES = grown;
        void *grown_roles = realloc(UNION_ROLES,
                                    (size_t)(UNION_COUNT + 1) * sizeof(uint32_t));
        if (!grown_roles)
            return;
        UNION_ROLES = grown_roles;
        UNION_ROLES[UNION_COUNT] = roles;
        memcpy(UNION_NAMES[UNION_COUNT++], name, n + 1);
    }
}

/* --------------------------------------------------------------------------
 * A rebuild of an opened snapshot with one header field changed.
 *
 * Contract 9's `Needs Rebuild` fires on a physics or schema disagreement, and
 * nothing in the real corpus disagrees - every map is compiled against the one
 * physics. So the incompatible snapshot is CONSTRUCTED: the same chunks, the
 * same sources, a fresh revision, and a different physics hash. Patching the
 * bytes would have been faster and would have produced a file the reader
 * rejects; this produces one it accepts, which is the case that matters.
 */
static mapgen_snapshot_t *rebuild_with_physics(const mapgen_snapshot_t *src,
                                               uint8_t revision_tag,
                                               uint8_t physics_byte,
                                               uint8_t **owned, size_t *owned_size)
{
    const mapgen_snapshot_header_t *h = MapGenSnapshot_Header(src);
    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
    if (!b)
        return NULL;

    uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES];
    memset(revision, revision_tag, sizeof(revision));
    MapGenSnapshot_SetIdentity(b, h->lineage_uuid, revision, h->parent_payload_sha256);

    uint8_t physics[MAPGEN_SHA256_BYTES];
    memcpy(physics, h->physics_schema_hash, MAPGEN_SHA256_BYTES);
    physics[0] = physics_byte;
    MapGenSnapshot_SetProvenance(b, h->training_recipe_hash, physics,
                                 h->created_utc_ms, h->source_count);

    bool ok = true;
    for (uint32_t i = 0; i < MapGenSnapshot_NumChunks(src) && ok; i++) {
        const uint32_t type = MapGenSnapshot_ChunkTypeAt(src, i);
        size_t size = 0;
        const uint8_t *data = MapGenSnapshot_Chunk(src, type, &size);
        ok = MapGenSnapshot_AddChunk(b, type, data, size,
                                     MAPGEN_COMPRESSION_DEFLATE)
             == MAPGEN_SNAPSHOT_OK;
    }

    *owned = NULL;
    *owned_size = 0;
    mapgen_snapshot_t *out = NULL;
    if (ok && MapGenSnapshot_Finish(b, owned, owned_size) == MAPGEN_SNAPSHOT_OK)
        MapGenSnapshot_Open(*owned, *owned_size, &out);
    MapGenSnapshot_BuilderFree(b);
    return out;
}

/* --------------------------------------------------------------------------
 * The learned statistics, read here straight out of the snapshot's own chunk
 * so the model is compared against the file rather than against itself.
 */

#define STAT_COUNT 6

typedef struct {
    char    hex[65];
    int64_t values[STAT_COUNT];
} learned_t;

static learned_t *LEARNED;
static uint32_t LEARNED_COUNT;

static void learned_scan(const mapgen_snapshot_t *snap)
{
    size_t size = 0;
    /* The aggregate rows live in STATS since schema 2 gave REGIONS the
       architecture; scanning REGIONS for them found nothing and reported a
       corpus that had taught no statistics at all. */
    const uint8_t *text = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_STATS, &size);
    if (!text)
        return;
    for (size_t i = 0; i + 2 <= size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (memcmp(text + i, "r=", 2))
            continue;
        const uint8_t *body = text + i + 2;
        size_t remaining = size - (i + 2);
        if (remaining < 65 || body[64] != ',')
            continue;

        learned_t row;
        memset(&row, 0, sizeof(row));
        memcpy(row.hex, body, 64);
        row.hex[64] = '\0';

        size_t at = 65;
        bool ok = true;
        for (uint32_t k = 0; k < STAT_COUNT && ok; k++) {
            int64_t value = 0;
            size_t digits = 0;
            bool negative = false;
            if (at < remaining && body[at] == '-') { negative = true; at++; }
            while (at < remaining && body[at] >= '0' && body[at] <= '9') {
                value = value * 10 + (body[at] - '0');
                digits++;
                at++;
            }
            if (!digits)
                ok = false;
            if (at < remaining && body[at] == ',')
                at++;
            row.values[k] = negative ? -value : value;
        }
        if (!ok)
            continue;

        bool seen = false;
        for (uint32_t k = 0; k < LEARNED_COUNT && !seen; k++)
            seen = !strcmp(LEARNED[k].hex, row.hex);
        if (seen)
            continue;

        void *grown = realloc(LEARNED, (size_t)(LEARNED_COUNT + 1) * sizeof(learned_t));
        if (!grown)
            return;
        LEARNED = grown;
        LEARNED[LEARNED_COUNT++] = row;
    }
}

/* The roles one snapshot's MATERIALS chunk records for a named material. */
static uint32_t chunk_material_roles(const mapgen_snapshot_t *snap,
                                     const char *material)
{
    size_t size = 0;
    const uint8_t *text = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_MATERIALS, &size);
    if (!text || !material)
        return 0;
    const size_t n = strlen(material);
    for (size_t i = 0; i + 2 <= size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (memcmp(text + i, "m=", 2))
            continue;
        const uint8_t *body = text + i + 2;
        const size_t remaining = size - (i + 2);
        if (remaining < n + 2 || memcmp(body, material, n) || body[n] != ',')
            continue;
        uint32_t roles = 0;
        for (size_t k = n + 1; k < remaining && body[k] >= '0' && body[k] <= '9'; k++)
            roles = roles * 10u + (uint32_t)(body[k] - '0');
        return roles;
    }
    return 0;
}

/*
 * Whether either snapshot's ENTITIES chunk records a nonzero total for a role,
 * read here rather than asked of the model.
 */
static bool chunk_has_role(const mapgen_snapshot_t *snap, const char *role)
{
    size_t size = 0;
    const uint8_t *text = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_ENTITIES, &size);
    if (!text || !role)
        return false;
    const size_t n = strlen(role);
    for (size_t i = 0; i + 2 <= size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (memcmp(text + i, "e=", 2))
            continue;
        const uint8_t *body = text + i + 2;
        size_t remaining = size - (i + 2);
        if (remaining < n + 2 || memcmp(body, role, n) || body[n] != ',')
            continue;
        for (size_t k = n + 1; k < remaining && body[k] != '\n'; k++)
            if (body[k] >= '1' && body[k] <= '9')
                return true;
        return false;
    }
    return false;
}

/* Whether one snapshot's SOURCES chunk carries this hash as accepted. */
static bool snapshot_has_source(const mapgen_snapshot_t *snap, const char *hex)
{
    size_t size = 0;
    const uint8_t *text = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_SOURCES, &size);
    if (!text || !hex)
        return false;
    for (size_t i = 0; i + 2 <= size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (memcmp(text + i, "s=", 2))
            continue;
        if (size - (i + 2) >= 64 && !memcmp(text + i + 2, hex, 64))
            return true;
    }
    return false;
}

static const learned_t *learned_find(const char *hex)
{
    for (uint32_t i = 0; i < LEARNED_COUNT; i++)
        if (hex && !strcmp(LEARNED[i].hex, hex))
            return &LEARNED[i];
    return NULL;
}

/* -------------------------------------------------------------------------- */

static char *render(const mapgen_mix_t *mix)
{
    const size_t n = MapGenMix_CanonicalText(mix, NULL, 0);
    char *text = malloc(n + 1);
    if (text)
        MapGenMix_CanonicalText(mix, text, n + 1);
    return text;
}

int main(int argc, char **argv)
{
    if (argc < 6 || strcmp(argv[1], "run")) {
        printf("usage: driver run <4 map paths>\n");
        return 2;
    }

    uint8_t *bytes_a = NULL, *bytes_b = NULL;
    size_t image_a = 0, image_b = 0;
    mapgen_snapshot_t *a = make_snapshot(&argv[2], 3, 0xA0, &bytes_a, &image_a);
    mapgen_snapshot_t *b = make_snapshot(&argv[3], 3, 0xB0, &bytes_b, &image_b);
    if (!a || !b) {
        printf("TRAIN_FAILED\n");
        return 1;
    }

    union_scan(a);
    union_scan(b);
    learned_scan(a);
    learned_scan(b);

    /* The snapshot bytes themselves, so "mixing does not mutate a snapshot" is
       checked against the whole image and not just a header field. */
    uint8_t before_a[MAPGEN_SHA256_BYTES], before_b[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(bytes_a, image_a, before_a);
    MapGenDigest_Sha256(bytes_b, image_b, before_b);

    mapgen_mix_input_t inputs[2];
    pin(&inputs[0], a, 50);
    pin(&inputs[1], b, 50);

    mapgen_mix_t *mix = NULL;
    mapgen_mix_result_t r = MapGenMix_Build(inputs, 2, NULL, &mix);
    check("two snapshots mix", r == MAPGEN_MIX_OK, MapGenMix_ResultName(r));
    if (r != MAPGEN_MIX_OK)
        return 1;

    check("equal weights normalize equally",
          MapGenMix_WeightPpm(mix, 0) == MapGenMix_WeightPpm(mix, 1)
          && MapGenMix_WeightPpm(mix, 0) == 500000u, "");

    /* --- the allowlist is the exact union, contract 15 -------------------- */
    check("the union computed independently is not empty",
          UNION_COUNT > 0, "the snapshots carry materials");
    check("the allowlist has exactly as many materials as the union",
          MapGenMix_NumMaterials(mix) == UNION_COUNT, "");

    bool all_in_union = true, all_of_union = true;
    for (uint32_t i = 0; i < MapGenMix_NumMaterials(mix); i++)
        if (!union_has(MapGenMix_MaterialName(mix, i)))
            all_in_union = false;
    for (uint32_t i = 0; i < UNION_COUNT; i++) {
        bool found = false;
        for (uint32_t j = 0; j < MapGenMix_NumMaterials(mix) && !found; j++) {
            const char *name = MapGenMix_MaterialName(mix, j);
            found = name && !strcmp(name, UNION_NAMES[i]);
        }
        if (!found)
            all_of_union = false;
    }
    check("mixing invents no material - every one came from a snapshot",
          all_in_union, "");

    /*
     * And what each one IS, not just that it exists. Contract 15 forbids
     * classifying a material from its filename, so the roles have to survive
     * the mix or the next stage would have nothing left but the name.
     */
    {
        uint32_t wrong = 0;
        const char *first = NULL;
        for (uint32_t i = 0; i < MapGenMix_NumMaterials(mix); i++) {
            const char *name = MapGenMix_MaterialName(mix, i);
            for (uint32_t k = 0; k < UNION_COUNT; k++) {
                if (!name || strcmp(UNION_NAMES[k], name))
                    continue;
                if (MapGenMix_MaterialRoles(mix, i) != UNION_ROLES[k]) {
                    wrong++;
                    if (!first)
                        first = name;
                }
                break;
            }
        }
        check("and every material carries the roles the corpus used it in",
              wrong == 0, first ? first : "");

        uint32_t with_roles = 0;
        for (uint32_t i = 0; i < MapGenMix_NumMaterials(mix); i++)
            if (MapGenMix_MaterialRoles(mix, i))
                with_roles++;
        check("with most of the allowlist actually carrying some",
              with_roles * 2 > MapGenMix_NumMaterials(mix),
              "all-zero roles would make the comparison above vacuous");

        /*
         * Whether the union rule is testable at all on this corpus.
         *
         * The model ORs a material's roles across every snapshot that has it.
         * If no material was used differently in the two snapshots, that OR
         * has nothing to do, and a case claiming to test it would be proving
         * nothing. So the number is measured and stated rather than assumed.
         */
        uint32_t disagreeing = 0;
        for (uint32_t k = 0; k < UNION_COUNT; k++) {
            const uint32_t in_a = chunk_material_roles(a, UNION_NAMES[k]);
            const uint32_t in_b = chunk_material_roles(b, UNION_NAMES[k]);
            if (in_a && in_b && in_a != in_b)
                disagreeing++;
        }
        printf("  NOTE  materials the two snapshots read differently: %u\n",
               disagreeing);
        check("every material's roles are at least what one snapshot alone says",
              wrong == 0,
              "with no material read differently, the union has nothing to do "
              "and this says only that neither reading was lost");
    }
    check("and drops none - the allowlist is the whole union", all_of_union, "");

    uint64_t probability_total = 0;
    uint32_t zero_probability = 0;
    for (uint32_t i = 0; i < MapGenMix_NumMaterials(mix); i++) {
        const uint32_t ppm = MapGenMix_MaterialProbabilityPpm(mix, i);
        probability_total += ppm;
        if (!ppm)
            zero_probability++;
    }
    check("the sampling probabilities sum to one",
          probability_total > 990000u && probability_total <= 1000000u,
          "integer truncation loses a little; it must not lose much");
    check("no material in the allowlist is unreachable",
          zero_probability == 0,
          "a material that can never be sampled is not in the allowlist");

    /* --- shared sources --------------------------------------------------- */
    check("the selection has shared sources to act on",
          MapGenMix_NumSharedSources(mix) > 0,
          "the two snapshots were trained on two maps in common");
    check("a shared source contributes once by default",
          MapGenMix_EffectiveSourceCount(mix) == MapGenMix_NumSources(mix)
          && !MapGenMix_RepeatedInfluence(mix), "");
    check("the distinct count is smaller than the appearances",
          MapGenMix_NumSources(mix) < 6u,
          "six maps were added across the two snapshots, four of them distinct");

    const uint64_t balanced_digest = MapGenMix_CanonicalDigest(mix);
    const uint32_t balanced_materials = MapGenMix_NumMaterials(mix);
    const uint32_t balanced_sources = MapGenMix_NumSources(mix);
    char *balanced_text = render(mix);

    /* --- contract 15: the allowlist is what the TARGET has ---------------- */
    {
        check("a model mixed without a manifest says so",
              !MapGenMix_HasTargetManifest(mix)
              && MapGenMix_NumUnavailableMaterials(mix) == 0,
              "an unfiltered allowlist is a list of things that may not exist "
              "where the map is going");

        /* Half the union, chosen by position so the choice is not a draw. */
        const uint32_t half = UNION_COUNT / 2;
        const char **allowed = malloc(half * sizeof(char *));
        if (allowed) {
            for (uint32_t i = 0; i < half; i++)
                allowed[i] = UNION_NAMES[i];

            mapgen_mix_options_t manifest;
            memset(&manifest, 0, sizeof(manifest));
            manifest.available = allowed;
            manifest.num_available = half;

            mapgen_mix_t *filtered = NULL;
            const mapgen_mix_result_t fr =
                MapGenMix_Build(inputs, 2, &manifest, &filtered);
            check("a model mixed against a manifest builds",
                  fr == MAPGEN_MIX_OK && filtered != NULL,
                  MapGenMix_ResultName(fr));
            if (filtered) {
                check("and says it has one",
                      MapGenMix_HasTargetManifest(filtered), "");
                check("the allowlist is exactly what the manifest allowed",
                      MapGenMix_NumMaterials(filtered) == half,
                      "not a subset of the corpus - the intersection");
                check("and the rest are counted as unavailable",
                      MapGenMix_NumUnavailableMaterials(filtered) > 0,
                      "a number the report can state rather than a silence");

                bool all_allowed = true;
                for (uint32_t i = 0; i < MapGenMix_NumMaterials(filtered); i++) {
                    const char *name = MapGenMix_MaterialName(filtered, i);
                    bool listed = false;
                    for (uint32_t k = 0; k < half && !listed; k++)
                        listed = name && !strcmp(allowed[k], name);
                    if (!listed)
                        all_allowed = false;
                }
                check("every material in it is one the target can resolve",
                      all_allowed,
                      "contract 15: the compiler only WARNS about a texture it "
                      "cannot find, so this is the only place it is caught");

                MapGenMix_Free(filtered);
            }

            /* A manifest nothing matches leaves nothing to texture with. */
            const char *nothing[] = { "no_such_dir/no_such_texture" };
            manifest.available = nothing;
            manifest.num_available = 1;
            mapgen_mix_t *empty = NULL;
            if (MapGenMix_Build(inputs, 2, &manifest, &empty) == MAPGEN_MIX_OK
                && empty) {
                check("a manifest the corpus shares nothing with empties the "
                      "allowlist",
                      MapGenMix_NumMaterials(empty) == 0
                      && MapGenMix_NumUnavailableMaterials(empty) == UNION_COUNT,
                      "which the brush stage then refuses, rather than "
                      "texturing with nothing");

                bool nameable = true;
                for (uint32_t i = 0;
                     i < MapGenMix_NumUnavailableMaterials(empty); i++)
                    if (!union_has(MapGenMix_UnavailableMaterial(empty, i)))
                        nameable = false;
                check("and every one of them can be named",
                      nameable,
                      "a number a user cannot act on is worth less than a "
                      "list they can");
                MapGenMix_Free(empty);
            }
            free(allowed);
        }
    }

    /* --- what the corpus actually contained ------------------------------- */
    {
        /*
         * Presence is the gate contract 15 describes, so it is checked against
         * the snapshots' own chunks for EVERY role rather than for a
         * convenient one. A model that reported a role nobody learned would
         * let the generator emit a motif with no provenance.
         */
        uint32_t wrong = 0, learned = 0;
        const char *first_wrong = NULL;
        for (uint32_t bit = 0; bit < 32; bit++) {
            const char *names[MAPGEN_WIRING_MAX_ROLE_NAMES];
            if (!MapGenWiring_RoleNames(1u << bit, names,
                                        MAPGEN_WIRING_MAX_ROLE_NAMES))
                continue;
            const bool want = chunk_has_role(a, names[0]) || chunk_has_role(b, names[0]);
            const bool got = MapGenMix_RoleIsLearned(mix, 1u << bit);
            if (want != got) {
                wrong++;
                if (!first_wrong)
                    first_wrong = names[0];
            }
            if (want)
                learned++;
        }
        check("the corpus taught at least a few entity roles", learned >= 4, "");
        check("and the model reports exactly the roles it taught, all 32 checked",
              wrong == 0, first_wrong ? first_wrong : "");

        check("a role bit of zero is never learned",
              !MapGenMix_RoleIsLearned(mix, 0), "");
        check("and a role nothing could have set is not either",
              !MapGenMix_RoleIsLearned(mix, 0x80000000u)
              || chunk_has_role(a, "editor_leftover")
              || chunk_has_role(b, "editor_leftover"), "");
    }

    /* --- the learned statistics the generator will sample ----------------- */
    {
        check("the snapshots carry learned statistics at all",
              LEARNED_COUNT > 0, "");
        check("the model keeps one sample per distinct learned map",
              MapGenMix_NumSamples(mix) == MapGenMix_NumSources(mix)
              && MapGenMix_NumSamples(mix) == LEARNED_COUNT,
              "a source two snapshots share is one map, not two");

        bool values_match = true, sources_known = true;
        const char *wrong = NULL;
        for (uint32_t i = 0; i < MapGenMix_NumSamples(mix); i++) {
            const char *hex = MapGenMix_SampleSource(mix, i);
            const learned_t *want = learned_find(hex);
            if (!want) {
                sources_known = false;
                continue;
            }
            for (uint32_t k = 0; k < STAT_COUNT; k++) {
                if (MapGenMix_SampleValue(mix, i, (mapgen_mix_stat_t)k)
                    != want->values[k]) {
                    values_match = false;
                    wrong = MapGenMix_StatName((mapgen_mix_stat_t)k);
                }
            }
        }
        check("every sample names a map one of the snapshots learned from",
              sources_known,
              "a statistic attributed to a map nobody learned from would be "
              "worse than no statistic");
        check("and carries exactly the numbers that snapshot recorded",
              values_match, wrong ? wrong : "");

        uint64_t sample_ppm = 0;
        uint32_t zero_weight = 0;
        for (uint32_t i = 0; i < MapGenMix_NumSamples(mix); i++) {
            const uint32_t ppm = MapGenMix_SampleWeightPpm(mix, i);
            sample_ppm += ppm;
            if (!ppm)
                zero_weight++;
        }
        check("the sample weights sum to one",
              sample_ppm > 990000u && sample_ppm <= 1000000u, "");
        check("and no learned map is unreachable", zero_weight == 0, "");

        check("a value outside the six statistics reads as nothing",
              MapGenMix_SampleValue(mix, 0, MAPGEN_MIX_STAT_COUNT) == 0, "");

        /* Drawing. */
        mapgen_random_t rng;
        MapGenRandom_Stream(&rng, 20260831ull, 0, MAPGEN_RANDOM_TOPOLOGY);
        uint32_t *hits = calloc(MapGenMix_NumSamples(mix), sizeof(uint32_t));
        bool in_range = true;
        const int draws = 100000;
        for (int i = 0; i < draws && hits; i++) {
            const uint32_t s = MapGenMix_DrawSample(mix, &rng);
            if (s >= MapGenMix_NumSamples(mix)) {
                in_range = false;
                break;
            }
            hits[s]++;
        }
        check("every draw lands on a real sample", in_range, "");

        bool every_reached = true;
        for (uint32_t i = 0; i < MapGenMix_NumSamples(mix) && hits; i++)
            if (!hits[i])
                every_reached = false;
        check("and over a hundred thousand draws every learned map comes up",
              every_reached && hits != NULL,
              "a map in the corpus that can never be drawn is not in the model");
        free(hits);

        /* The draw is a pure function of the stream. */
        mapgen_random_t one, two;
        MapGenRandom_Stream(&one, 7, 1, MAPGEN_RANDOM_TOPOLOGY);
        MapGenRandom_Stream(&two, 7, 1, MAPGEN_RANDOM_TOPOLOGY);
        bool same = true;
        for (int i = 0; i < 256; i++)
            same = same && MapGenMix_DrawSample(mix, &one)
                        == MapGenMix_DrawSample(mix, &two);
        check("the same stream draws the same maps", same, "");

        check("drawing from nothing gives a value that is not an index",
              MapGenMix_DrawSample(NULL, &one) == 0, "");
    }

    /* --- repeated influence, explicitly enabled --------------------------- */
    {
        const mapgen_mix_options_t repeats = { true, NULL, 0 };
        mapgen_mix_t *repeated = NULL;
        r = MapGenMix_Build(inputs, 2, &repeats, &repeated);
        check("repeated influence is accepted when asked for",
              r == MAPGEN_MIX_OK, MapGenMix_ResultName(r));
        if (repeated) {
            check("and then a shared source contributes more than once",
                  MapGenMix_EffectiveSourceCount(repeated)
                  == MapGenMix_NumSources(repeated)
                     + MapGenMix_NumSharedSources(repeated), "");
            check("which is a different model, not a different label",
                  MapGenMix_CanonicalDigest(repeated) != balanced_digest, "");
            check("the allowlist is unaffected by it",
                  MapGenMix_NumMaterials(repeated) == balanced_materials,
                  "repeated influence weights sources, it does not add materials");
            check("the setting reaches the samples, not just the source count",
                  MapGenMix_NumSamples(repeated)
                  == MapGenMix_EffectiveSourceCount(repeated)
                  && MapGenMix_NumSamples(repeated) > MapGenMix_NumSamples(mix),
                  "a shared map contributes once per snapshot when asked to");

            /* The model says which setting produced it, so a result can be
               read back years later without the request beside it. */
            char *text = render(repeated);
            check("the model records that repeated influence was on",
                  text && strstr(text, "repeated_influence=1\n") != NULL,
                  "the canonical text carries the setting, not just its effect");
            check("and the balanced model records that it was off",
                  balanced_text
                  && strstr(balanced_text, "repeated_influence=0\n") != NULL, "");
            free(text);
            MapGenMix_Free(repeated);
        }
    }

    /* --- weights actually change the model -------------------------------- */
    {
        mapgen_mix_input_t skewed[2];
        pin(&skewed[0], a, 100);
        pin(&skewed[1], b, 1);
        mapgen_mix_t *heavy = NULL;
        r = MapGenMix_Build(skewed, 2, NULL, &heavy);
        check("an uneven selection mixes", r == MAPGEN_MIX_OK,
              MapGenMix_ResultName(r));
        if (heavy) {
            check("the heavier snapshot carries more weight",
                  MapGenMix_WeightPpm(heavy, 0)
                  > MapGenMix_WeightPpm(heavy, 1) * 50u, "");
            check("and the model differs from the balanced one",
                  MapGenMix_CanonicalDigest(heavy) != balanced_digest, "");
            check("while the allowlist is unchanged - a union, not a sample",
                  MapGenMix_NumMaterials(heavy) == balanced_materials,
                  "weighting changes how often, never whether");

            /* The map only snapshot A knows must now be drawn far more often
               than the map only snapshot B knows. */
            uint32_t only_a = UINT32_MAX, only_b = UINT32_MAX;
            for (uint32_t i = 0; i < MapGenMix_NumSamples(heavy); i++) {
                const char *hex = MapGenMix_SampleSource(heavy, i);
                const bool in_a = snapshot_has_source(a, hex);
                const bool in_b = snapshot_has_source(b, hex);
                if (in_a && !in_b && only_a == UINT32_MAX) only_a = i;
                if (in_b && !in_a && only_b == UINT32_MAX) only_b = i;
            }
            check("the selection really does have a map from each side alone",
                  only_a != UINT32_MAX && only_b != UINT32_MAX, "");
            if (only_a != UINT32_MAX && only_b != UINT32_MAX) {
                check("and the heavier snapshot's own map records a far bigger weight",
                      MapGenMix_SampleWeightPpm(heavy, only_a)
                      > MapGenMix_SampleWeightPpm(heavy, only_b) * 50u, "");

                /*
                 * The number above is only a number. What the generator
                 * depends on is the DRAW, so it is drawn and counted: a model
                 * that records the weight and samples uniformly would pass
                 * every check up to this one.
                 */
                mapgen_random_t rng;
                MapGenRandom_Stream(&rng, 4242, 0, MAPGEN_RANDOM_TOPOLOGY);
                uint32_t hit_a = 0, hit_b = 0;
                for (int i = 0; i < 100000; i++) {
                    const uint32_t s = MapGenMix_DrawSample(heavy, &rng);
                    if (s == only_a) hit_a++;
                    if (s == only_b) hit_b++;
                }
                check("and is actually drawn far more often",
                      hit_a > hit_b * 50u && hit_b * 50u > 0u,
                      "weighting has to move the draw, not just a number");
            }
            MapGenMix_Free(heavy);
        }
    }

    /* --- what mixing refuses ---------------------------------------------- */
    {
        mapgen_mix_input_t bad[2];
        mapgen_mix_t *nope = (mapgen_mix_t *)1;

        pin(&bad[0], a, 50);
        pin(&bad[1], b, 50);
        bad[1].payload_sha256[0] ^= 0xFF;
        r = MapGenMix_Build(bad, 2, NULL, &nope);
        check("a snapshot whose payload does not match its pin is refused",
              r == MAPGEN_MIX_ERR_PIN_MISMATCH, MapGenMix_ResultName(r));
        check("and nothing is handed back when it is",
              nope == NULL, "a refused build must not leave a model behind");

        pin(&bad[1], b, 50);
        bad[1].revision_uuid[0] ^= 0xFF;
        r = MapGenMix_Build(bad, 2, NULL, &nope);
        check("so is one whose revision identity does not match",
              r == MAPGEN_MIX_ERR_PIN_MISMATCH, MapGenMix_ResultName(r));

        pin(&bad[1], b, 0);
        r = MapGenMix_Build(bad, 2, NULL, &nope);
        check("a weight below the range is refused",
              r == MAPGEN_MIX_ERR_BAD_WEIGHT, MapGenMix_ResultName(r));
        pin(&bad[1], b, MAPGEN_MIX_MAX_WEIGHT + 1u);
        r = MapGenMix_Build(bad, 2, NULL, &nope);
        check("and one above it",
              r == MAPGEN_MIX_ERR_BAD_WEIGHT, MapGenMix_ResultName(r));

        pin(&bad[1], b, MAPGEN_MIX_MAX_WEIGHT);
        r = MapGenMix_Build(bad, 2, NULL, &nope);
        check("the top of the range is accepted",
              r == MAPGEN_MIX_OK, MapGenMix_ResultName(r));
        MapGenMix_Free(nope);
        nope = NULL;

        pin(&bad[0], a, 50);
        pin(&bad[1], a, 50);
        r = MapGenMix_Build(bad, 2, NULL, &nope);
        check("selecting the same revision twice is refused",
              r == MAPGEN_MIX_ERR_DUPLICATE_REVISION, MapGenMix_ResultName(r));

        r = MapGenMix_Build(inputs, 0, NULL, &nope);
        check("an empty selection is refused",
              r == MAPGEN_MIX_ERR_NO_INPUTS, MapGenMix_ResultName(r));

        r = MapGenMix_Build(inputs, MAPGEN_MIX_MAX_INPUTS + 1u, NULL, &nope);
        check("and one past the input cap",
              r == MAPGEN_MIX_ERR_TOO_MANY_INPUTS, MapGenMix_ResultName(r));

        pin(&bad[0], a, 50);
        bad[0].snapshot = NULL;
        r = MapGenMix_Build(bad, 2, NULL, &nope);
        check("a missing snapshot is refused rather than dereferenced",
              r == MAPGEN_MIX_ERR_ARGS, MapGenMix_ResultName(r));
    }

    /* --- one snapshot is a legal selection -------------------------------- */
    {
        mapgen_mix_input_t single;
        pin(&single, a, 100);
        mapgen_mix_t *alone = NULL;
        r = MapGenMix_Build(&single, 1, NULL, &alone);
        check("a single snapshot mixes to itself", r == MAPGEN_MIX_OK,
              MapGenMix_ResultName(r));
        if (alone) {
            check("its whole weight is its own",
                  MapGenMix_WeightPpm(alone, 0) == 1000000u, "");
            check("it shares nothing with itself",
                  MapGenMix_NumSharedSources(alone) == 0, "");
            check("and its allowlist is no larger than the union of two",
                  MapGenMix_NumMaterials(alone) <= balanced_materials, "");
            MapGenMix_Free(alone);
        }
    }

    /* --- the inputs are untouched ----------------------------------------- */
    {
        uint8_t after_a[MAPGEN_SHA256_BYTES], after_b[MAPGEN_SHA256_BYTES];
        MapGenDigest_Sha256(bytes_a, image_a, after_a);
        MapGenDigest_Sha256(bytes_b, image_b, after_b);
        check("mixing does not disturb one byte of the snapshots it read",
              !memcmp(before_a, after_a, MAPGEN_SHA256_BYTES)
              && !memcmp(before_b, after_b, MAPGEN_SHA256_BYTES),
              "the whole image is hashed, not just the header");
    }

    /* --- selection order does not matter ---------------------------------- */
    {
        mapgen_mix_input_t reversed[2];
        pin(&reversed[0], b, 50);
        pin(&reversed[1], a, 50);
        mapgen_mix_t *other = NULL;
        r = MapGenMix_Build(reversed, 2, NULL, &other);
        check("the reversed selection mixes", r == MAPGEN_MIX_OK,
              MapGenMix_ResultName(r));
        if (other && balanced_text) {
            char *text = render(other);
            /* Equal weights, so even the per-input rows match: at equal
               weights the selection ORDER must leave no trace at all. */
            check("selection order leaves no trace in the model",
                  text && !strcmp(text, balanced_text),
                  "the material table is sorted and the counts are set-based");
            check("nor in its digest",
                  MapGenMix_CanonicalDigest(other) == balanced_digest, "");
            check("and the same snapshots give the same source count",
                  MapGenMix_NumSources(other) == balanced_sources, "");
            free(text);
        }
        MapGenMix_Free(other);
    }

    /* --- incompatible physics shows Needs Rebuild ------------------------- */
    {
        uint8_t *bytes_c = NULL;
        size_t image_c = 0;
        mapgen_snapshot_t *c = rebuild_with_physics(b, 0xC0, 0x5A,
                                                    &bytes_c, &image_c);
        check("a snapshot with different physics can be constructed",
              c != NULL, "same chunks, fresh revision, one physics byte changed");
        if (c) {
            check("and it is a valid snapshot in its own right",
                  memcmp(MapGenSnapshot_Header(c)->physics_schema_hash,
                         MapGenSnapshot_Header(b)->physics_schema_hash,
                         MAPGEN_SHA256_BYTES) != 0,
                  "the reader accepted it; only the physics differs");

            mapgen_mix_input_t cross[2];
            mapgen_mix_t *refused = (mapgen_mix_t *)1;
            pin(&cross[0], a, 50);
            pin(&cross[1], c, 50);
            r = MapGenMix_Build(cross, 2, NULL, &refused);
            check("mixing across incompatible physics shows Needs Rebuild",
                  r == MAPGEN_MIX_ERR_NEEDS_REBUILD, MapGenMix_ResultName(r));
            check("and builds nothing",
                  refused == NULL, "a model of no particular game is not built");

            /* The same snapshot alone is fine: it is the DISAGREEMENT that is
               refused, not the snapshot. */
            mapgen_mix_t *alone = NULL;
            r = MapGenMix_Build(&cross[1], 1, NULL, &alone);
            check("but that snapshot on its own still mixes",
                  r == MAPGEN_MIX_OK, MapGenMix_ResultName(r));
            MapGenMix_Free(alone);

            MapGenSnapshot_Free(c);
            free(bytes_c);
        }
    }

    /* --- the same selection twice is the same model ----------------------- */
    {
        mapgen_mix_t *again = NULL;
        if (MapGenMix_Build(inputs, 2, NULL, &again) == MAPGEN_MIX_OK && again) {
            check("mixing the same selection twice gives the same model",
                  MapGenMix_CanonicalDigest(again) == balanced_digest,
                  "there is no clock and no RNG in the module");
            MapGenMix_Free(again);
        }
    }

    free(balanced_text);
    MapGenMix_Free(mix);
    MapGenSnapshot_Free(a);
    MapGenSnapshot_Free(b);
    free(bytes_a);
    free(bytes_b);
    free(UNION_NAMES);
    free(UNION_ROLES);
    free(LEARNED);

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}
