/*
 * MAPGEN-1 lineage test driver.
 *
 * Compiled and run by tools/check_mapgen_lineage_contract.py.
 *
 *   driver run <map.bsp> <map.bsp> ...
 *
 * Trains on the maps given, then exercises New / Extend / Rebuild / Rename and
 * checks the properties contract 7 and 8 require of each - above all that the
 * parent's bytes are never touched.
 */

#include "common/mapgen_lineage.h"
#include "common/mapgen_features.h"

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

/* ------------------------------------------------------------------------ */

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

/* Train on a slice of the argv map list. */
static mapgen_training_t *train(int argc, char **argv, int first, int count)
{
    mapgen_training_t *t = MapGenTraining_Create();
    if (!t)
        return NULL;
    for (int i = first; i < argc && i < first + count; i++) {
        size_t size = 0;
        uint8_t *data = read_file(argv[i], &size);
        if (!data)
            continue;
        uint8_t sha[MAPGEN_SHA256_BYTES];
        MapGenDigest_Sha256(data, size, sha);

        mapgen_bsp_t *bsp = NULL;
        mapgen_genome_t *genome = NULL;
        mapgen_space_t *space = NULL;
        mapgen_wiring_t *wiring = NULL;
        mapgen_features_t *features = NULL;
        mapgen_space_params_t p = MapGenSpace_DefaultParams();

        if (MapGenBsp_Load(data, size, &bsp) == MAPGEN_BSP_OK &&
            MapGenGenome_Extract(bsp, &genome) == MAPGEN_GENOME_OK &&
            MapGenSpace_Build(bsp, &p, &space) == MAPGEN_SPACE_OK &&
            MapGenWiring_Build(genome, bsp, &wiring) == MAPGEN_WIRING_OK &&
            MapGenFeatures_Build(bsp, genome, space, wiring, &features)
                == MAPGEN_FEATURES_OK) {
            MapGenTraining_AddSource(t, basename_of(argv[i]), "baseq2", size,
                                     sha, features, genome, wiring,
                                      /* this driver learns statistics, not architecture:
                                         neither a shape nor a solid */
                                      NULL, NULL);
        }
        MapGenFeatures_Free(features);
        MapGenWiring_Free(wiring);
        MapGenSpace_Free(space);
        MapGenGenome_Free(genome);
        MapGenBsp_Free(bsp);
        free(data);
    }
    return t;
}

static void fill_uuid(uint8_t *out, uint8_t value)
{
    memset(out, value, MAPGEN_SNAPSHOT_UUID_BYTES);
}

int main(int argc, char **argv)
{
    if (argc < 4 || strcmp(argv[1], "run")) {
        printf("usage\n");
        return 2;
    }

    const int maps = argc - 2;
    mapgen_training_t *first_half = train(argc, argv, 2, maps / 2);
    mapgen_training_t *everything = train(argc, argv, 2, maps);
    if (!first_half || !everything) {
        printf("TRAIN_FAILED\n");
        return 1;
    }

    uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES], rev1[MAPGEN_SNAPSHOT_UUID_BYTES];
    uint8_t rev2[MAPGEN_SNAPSHOT_UUID_BYTES], rev3[MAPGEN_SNAPSHOT_UUID_BYTES];
    fill_uuid(lineage, 0xA1);
    fill_uuid(rev1, 0xB1);
    fill_uuid(rev2, 0xB2);
    fill_uuid(rev3, 0xB3);

    /* --- New -------------------------------------------------------------- */
    uint8_t *first_bytes = NULL;
    size_t first_size = 0;
    mapgen_lineage_result_t r = MapGenLineage_New(
        first_half, lineage, rev1, 1756600000000ull,
        MAPGEN_COMPRESSION_DEFLATE, &first_bytes, &first_size);
    check("New produces a snapshot", r == MAPGEN_LINEAGE_OK,
          MapGenLineage_ResultName(r));
    if (r != MAPGEN_LINEAGE_OK)
        return 1;

    mapgen_snapshot_t *parent = NULL;
    check("and it opens", MapGenSnapshot_Open(first_bytes, first_size, &parent)
          == MAPGEN_SNAPSHOT_OK, "");
    if (!parent)
        return 1;

    const mapgen_snapshot_header_t *ph = MapGenSnapshot_Header(parent);
    uint8_t zero[MAPGEN_SHA256_BYTES] = { 0 };
    check("a new lineage has no parent payload",
          !memcmp(ph->parent_payload_sha256, zero, MAPGEN_SHA256_BYTES), "");
    check("it carries the lineage it was given",
          !memcmp(ph->lineage_uuid, lineage, MAPGEN_SNAPSHOT_UUID_BYTES), "");

    /* Keep an untouched copy to prove the parent is never modified. */
    uint8_t parent_digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(first_bytes, first_size, parent_digest);

    /* --- Extend ----------------------------------------------------------- */
    uint8_t *extended = NULL;
    size_t extended_size = 0;
    uint32_t added = 0, skipped = 0;
    r = MapGenLineage_Extend(parent, everything, rev2, 1756600001000ull,
                             MAPGEN_COMPRESSION_DEFLATE, &extended,
                             &extended_size, &added, &skipped);
    check("Extend produces a snapshot", r == MAPGEN_LINEAGE_OK,
          MapGenLineage_ResultName(r));

    uint8_t after_digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(first_bytes, first_size, after_digest);
    check("the parent's bytes are untouched by Extend",
          !memcmp(parent_digest, after_digest, MAPGEN_SHA256_BYTES), "");

    mapgen_snapshot_t *child = NULL;
    if (extended)
        MapGenSnapshot_Open(extended, extended_size, &child);
    check("the extension opens", child != NULL, "");
    if (child) {
        const mapgen_snapshot_header_t *ch = MapGenSnapshot_Header(child);
        check("the extension keeps the lineage",
              !memcmp(ch->lineage_uuid, ph->lineage_uuid, MAPGEN_SNAPSHOT_UUID_BYTES), "");
        check("and takes a new revision identity",
              memcmp(ch->revision_uuid, ph->revision_uuid, MAPGEN_SNAPSHOT_UUID_BYTES), "");
        check("and records the parent's payload hash",
              !memcmp(ch->parent_payload_sha256, ph->payload_sha256,
                      MAPGEN_SHA256_BYTES), "");
        check("and has a payload of its own",
              memcmp(ch->payload_sha256, ph->payload_sha256, MAPGEN_SHA256_BYTES), "");
        check("Extend reports what it added and what it already knew",
              added + skipped > 0 && skipped > 0,
              "the second half of the corpus shares maps with the first");
    }

    /* Extending with the parent's own revision id is refused. */
    uint8_t *rejected = NULL;
    size_t rejected_size = 0;
    r = MapGenLineage_Extend(parent, everything, ph->revision_uuid, 0,
                             MAPGEN_COMPRESSION_NONE, &rejected, &rejected_size,
                             NULL, NULL);
    check("a new revision may not reuse its parent's identity",
          r == MAPGEN_LINEAGE_ERR_SAME_REVISION, MapGenLineage_ResultName(r));

    /* --- Rebuild ---------------------------------------------------------- */
    uint8_t *rebuilt = NULL;
    size_t rebuilt_size = 0;
    r = MapGenLineage_Rebuild(parent, first_half, rev3, 1756600002000ull,
                              MAPGEN_COMPRESSION_DEFLATE, &rebuilt, &rebuilt_size);
    check("Rebuild produces a snapshot", r == MAPGEN_LINEAGE_OK,
          MapGenLineage_ResultName(r));
    if (rebuilt) {
        mapgen_snapshot_t *rebuilt_snap = NULL;
        MapGenSnapshot_Open(rebuilt, rebuilt_size, &rebuilt_snap);
        check("the rebuild opens", rebuilt_snap != NULL, "");
        if (rebuilt_snap) {
            const mapgen_snapshot_header_t *rh = MapGenSnapshot_Header(rebuilt_snap);
            check("a rebuild of the same sources reproduces the same payload",
                  !memcmp(rh->payload_sha256, ph->payload_sha256,
                          MAPGEN_SHA256_BYTES),
                  "same sources, same schema, same learned content");
            check("but it is a new revision",
                  memcmp(rh->revision_uuid, ph->revision_uuid,
                         MAPGEN_SNAPSHOT_UUID_BYTES), "");
            check("in the same lineage",
                  !memcmp(rh->lineage_uuid, ph->lineage_uuid,
                          MAPGEN_SNAPSHOT_UUID_BYTES), "");
            MapGenSnapshot_Free(rebuilt_snap);
        }
        free(rebuilt);
    }

    /* --- Rename ----------------------------------------------------------- */
    {
        uint8_t *renamed = NULL;
        size_t renamed_size = 0;
        const char *title = "Карта для дуэлей";       /* UTF-8, deliberately */
        uint8_t rev4[MAPGEN_SNAPSHOT_UUID_BYTES];
        fill_uuid(rev4, 0xB4);
        r = MapGenLineage_Rename(parent, title, rev4, 1756600003000ull,
                                 MAPGEN_COMPRESSION_DEFLATE, &renamed, &renamed_size);
        check("Rename produces a snapshot", r == MAPGEN_LINEAGE_OK,
              MapGenLineage_ResultName(r));

        MapGenDigest_Sha256(first_bytes, first_size, after_digest);
        check("the parent's bytes are untouched by Rename",
              !memcmp(parent_digest, after_digest, MAPGEN_SHA256_BYTES), "");

        if (renamed) {
            mapgen_snapshot_t *renamed_snap = NULL;
            MapGenSnapshot_Open(renamed, renamed_size, &renamed_snap);
            check("the rename opens", renamed_snap != NULL, "");
            if (renamed_snap) {
                char read_title[MAPGEN_LINEAGE_TITLE_BYTES];
                check("the new title is there",
                      MapGenLineage_Title(renamed_snap, read_title)
                      && !strcmp(read_title, title), read_title);

                /* Every chunk except META must be byte-identical. A rename
                   cannot be allowed to change what was learned. */
                bool identical = true;
                for (uint32_t type = MAPGEN_CHUNK_SOURCES;
                     type <= MAPGEN_CHUNK_QUALITY; type++) {
                    size_t a = 0, b = 0;
                    const uint8_t *pa = MapGenSnapshot_Chunk(parent, type, &a);
                    const uint8_t *pb = MapGenSnapshot_Chunk(renamed_snap, type, &b);
                    if (!pa || !pb || a != b || memcmp(pa, pb, a))
                        identical = false;
                }
                check("every learned chunk survives a rename untouched", identical,
                      "");

                const mapgen_snapshot_header_t *nh = MapGenSnapshot_Header(renamed_snap);
                check("the rename keeps the lineage",
                      !memcmp(nh->lineage_uuid, ph->lineage_uuid,
                              MAPGEN_SNAPSHOT_UUID_BYTES), "");
                check("and takes a new revision identity",
                      memcmp(nh->revision_uuid, ph->revision_uuid,
                             MAPGEN_SNAPSHOT_UUID_BYTES), "");
                check("and records the parent it renamed",
                      !memcmp(nh->parent_payload_sha256, ph->payload_sha256,
                              MAPGEN_SHA256_BYTES), "");
                /* Rename it AGAIN. The first rename put a title where there
                   had been none; only a second one proves the old line is
                   REPLACED rather than accumulated. Without this the whole
                   title-rewriting branch was never executed. */
                uint8_t rev5[MAPGEN_SNAPSHOT_UUID_BYTES];
                fill_uuid(rev5, 0xB5);
                uint8_t *twice = NULL;
                size_t twice_size = 0;
                const char *second = "Renamed Again";
                const mapgen_lineage_result_t r2 = MapGenLineage_Rename(
                    renamed_snap, second, rev5, 1756600004000ull,
                    MAPGEN_COMPRESSION_DEFLATE, &twice, &twice_size);
                check("a snapshot can be renamed a second time",
                      r2 == MAPGEN_LINEAGE_OK, MapGenLineage_ResultName(r2));
                if (twice) {
                    mapgen_snapshot_t *twice_snap = NULL;
                    MapGenSnapshot_Open(twice, twice_size, &twice_snap);
                    if (twice_snap) {
                        char t2[MAPGEN_LINEAGE_TITLE_BYTES];
                        check("the second title replaces the first",
                              MapGenLineage_Title(twice_snap, t2)
                              && !strcmp(t2, second), t2);

                        size_t meta_size = 0;
                        const uint8_t *meta = MapGenSnapshot_Chunk(
                            twice_snap, MAPGEN_CHUNK_META, &meta_size);
                        uint32_t titles = 0;
                        for (size_t i = 0; meta && i + 6 <= meta_size; i++)
                            if ((i == 0 || meta[i - 1] == '\n')
                                && !memcmp(meta + i, "title=", 6))
                                titles++;
                        check("and the old title line is gone, not kept",
                              titles == 1, "");
                        MapGenSnapshot_Free(twice_snap);
                    }
                    free(twice);
                }

                MapGenSnapshot_Free(renamed_snap);
            }
            free(renamed);
        }

        /* A title with a control byte in it is refused outright. */
        uint8_t *bad = NULL;
        size_t bad_size = 0;
        r = MapGenLineage_Rename(parent, "line\nbreak", rev4, 0,
                                 MAPGEN_COMPRESSION_NONE, &bad, &bad_size);
        check("a title containing a control byte is refused",
              r == MAPGEN_LINEAGE_ERR_TITLE_INVALID, MapGenLineage_ResultName(r));
        r = MapGenLineage_Rename(parent, "", rev4, 0,
                                 MAPGEN_COMPRESSION_NONE, &bad, &bad_size);
        check("an empty title is refused",
              r == MAPGEN_LINEAGE_ERR_TITLE_INVALID, MapGenLineage_ResultName(r));
    }

    /* --- slugs ------------------------------------------------------------ */
    {
        char slug[128];
        MapGenLineage_Slug("Карта для дуэлей", slug, sizeof(slug));
        check("a Cyrillic title still yields a safe slug",
              slug[0] && strlen(slug) < sizeof(slug), slug);
        bool safe = true;
        for (const char *p = slug; *p; p++)
            if (!((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9') || *p == '_'))
                safe = false;
        check("and it contains nothing a filesystem could object to", safe, slug);

        MapGenLineage_Slug("  Duel Arena!!  v2  ", slug, sizeof(slug));
        check("separators collapse and never trail",
              !strcmp(slug, "duel_arena_v2"), slug);

        MapGenLineage_Slug("///", slug, sizeof(slug));
        check("a title with no usable characters still yields something",
              !strcmp(slug, "snapshot"), slug);
    }

    MapGenSnapshot_Free(child);
    MapGenSnapshot_Free(parent);
    free(extended);
    free(first_bytes);
    MapGenTraining_Free(first_half);
    MapGenTraining_Free(everything);

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}
