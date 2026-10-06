/*
 * MAPGEN-1 `.q2mgdb` container test driver.
 *
 * Compiled and run by tools/check_mapgen_snapshot_contract.py.
 *
 *   driver build   <out.q2mgdb> [deflate|store]   write a valid snapshot
 *   driver open    <file.q2mgdb>                  validate and describe
 *   driver hash    <file.q2mgdb>                  the payload hash it carries
 *   driver roundtrip <tmpdir>                     build/open both compressions
 *   driver selftest                               builder-side refusals
 *
 * `open` prints the result code and nothing else when a file is refused, so
 * the guard can assert on the exact reason rather than on "it failed".
 */

#include "common/mapgen_snapshot.h"

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
    long size = ftell(f);
    if (size < 0) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) { fclose(f); return NULL; }
    size_t got = fread(data, 1, (size_t)size, f);
    fclose(f);
    *out_size = got;
    return data;
}

static bool write_file(const char *path, const uint8_t *data, size_t size)
{
    FILE *f = fopen(path, "wb");
    if (!f)
        return false;
    const size_t wrote = fwrite(data, 1, size, f);
    fclose(f);
    return wrote == size;
}

/* A snapshot with all seven required chunks, filled with content that is
   deterministic and compressible enough to exercise deflate. */
static mapgen_snapshot_builder_t *make_builder(mapgen_compression_t how)
{
    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
    if (!b)
        return NULL;

    static const struct { uint32_t type; const char *body; } BODIES[] = {
        { MAPGEN_CHUNK_META,      "title=Test Snapshot\nslug=test_snapshot\n" },
        { MAPGEN_CHUNK_SOURCES,   "count=2\naerowalk.bsp\nq2rdm8.bsp\n" },
        { MAPGEN_CHUNK_MATERIALS, "e1u1/floor3_3 roles=floor\ne1u1/sky1 roles=sky\n" },
        { MAPGEN_CHUNK_REGIONS,   "regions=63 largest=1059\n" },
        { MAPGEN_CHUNK_ENTITIES,  "spawn_dm=9 item=55 teleporter=2\n" },
        { MAPGEN_CHUNK_STATS,     "cover_permille=863 loops=1875\n" },
        { MAPGEN_CHUNK_QUALITY,   "sources=2 warning=low_diversity\n" },
        { MAPGEN_CHUNK_SHAPES,    "max_volumes=1024 basis=16\n" },
        { MAPGEN_CHUNK_GEOMETRY,  "max_donors=256 max_brushes=262144\n" },
    };

    uint8_t lineage[16], revision[16], parent[32], recipe[32], physics[32];
    for (int i = 0; i < 16; i++) { lineage[i] = (uint8_t)(0x10 + i); revision[i] = (uint8_t)(0x20 + i); }
    for (int i = 0; i < 32; i++) { parent[i] = (uint8_t)i; recipe[i] = (uint8_t)(0x40 + i); physics[i] = (uint8_t)(0x80 + i); }
    MapGenSnapshot_SetIdentity(b, lineage, revision, parent);
    MapGenSnapshot_SetProvenance(b, recipe, physics, 1756600000000ull, 2);

    for (size_t i = 0; i < sizeof(BODIES) / sizeof(BODIES[0]); i++) {
        /* Repeat the body so deflate has something to work with. */
        char buffer[4096];
        size_t n = 0;
        while (n + strlen(BODIES[i].body) < sizeof(buffer) - 1) {
            memcpy(buffer + n, BODIES[i].body, strlen(BODIES[i].body));
            n += strlen(BODIES[i].body);
        }
        buffer[n] = '\0';
        if (MapGenSnapshot_AddChunk(b, BODIES[i].type, buffer, n, how)
            != MAPGEN_SNAPSHOT_OK) {
            MapGenSnapshot_BuilderFree(b);
            return NULL;
        }
    }
    return b;
}

static int cmd_build(const char *path, mapgen_compression_t how)
{
    mapgen_snapshot_builder_t *b = make_builder(how);
    if (!b) {
        printf("BUILDER_FAILED\n");
        return 1;
    }
    uint8_t *bytes = NULL;
    size_t size = 0;
    const mapgen_snapshot_result_t r = MapGenSnapshot_Finish(b, &bytes, &size);
    MapGenSnapshot_BuilderFree(b);
    if (r != MAPGEN_SNAPSHOT_OK) {
        printf("%s\n", MapGenSnapshot_ResultName(r));
        return 1;
    }
    const bool ok = write_file(path, bytes, size);
    free(bytes);
    printf(ok ? "OK %zu\n" : "WRITE_FAILED %zu\n", size);
    return ok ? 0 : 1;
}

static int cmd_open(const char *path, bool print_hash)
{
    size_t size = 0;
    uint8_t *bytes = read_file(path, &size);
    if (!bytes) {
        printf("READ_FAILED\n");
        return 1;
    }
    mapgen_snapshot_t *snap = NULL;
    const mapgen_snapshot_result_t r = MapGenSnapshot_Open(bytes, size, &snap);
    free(bytes);
    if (r != MAPGEN_SNAPSHOT_OK) {
        printf("%s\n", MapGenSnapshot_ResultName(r));
        return 0;
    }

    const mapgen_snapshot_header_t *h = MapGenSnapshot_Header(snap);
    if (print_hash) {
        char hex[MAPGEN_SHA256_HEX];
        MapGenDigest_Sha256Hex(h->payload_sha256, hex);
        printf("OK %s\n", hex);
    } else {
        printf("OK schema %u.%u chunks %u sources %u created %llu bytes %llu\n",
               h->schema_major, h->schema_minor, h->chunk_count, h->source_count,
               (unsigned long long)h->created_utc_ms,
               (unsigned long long)h->file_bytes);
        for (uint32_t i = 0; i < MapGenSnapshot_NumChunks(snap); i++) {
            const uint32_t type = MapGenSnapshot_ChunkTypeAt(snap, i);
            size_t chunk_size = 0;
            MapGenSnapshot_Chunk(snap, type, &chunk_size);
            printf("chunk %u %s %zu\n", type,
                   MapGenSnapshot_ChunkTypeName(type), chunk_size);
        }
    }
    MapGenSnapshot_Free(snap);
    return 0;
}

static int cmd_roundtrip(const char *dir)
{
    char path[1024];
    for (int pass = 0; pass < 2; pass++) {
        const mapgen_compression_t how = pass ? MAPGEN_COMPRESSION_DEFLATE
                                              : MAPGEN_COMPRESSION_NONE;
        const char *label = pass ? "deflate" : "store";

        mapgen_snapshot_builder_t *b = make_builder(how);
        uint8_t *bytes = NULL;
        size_t size = 0;
        check("the builder accepted every required chunk", b != NULL, label);
        if (!b)
            continue;

        uint8_t expect[MAPGEN_SHA256_BYTES];
        MapGenSnapshot_BuilderPayloadHash(b, expect);

        const mapgen_snapshot_result_t r = MapGenSnapshot_Finish(b, &bytes, &size);
        MapGenSnapshot_BuilderFree(b);
        check("it serialized", r == MAPGEN_SNAPSHOT_OK, MapGenSnapshot_ResultName(r));
        if (r != MAPGEN_SNAPSHOT_OK)
            continue;

        snprintf(path, sizeof(path), "%s/roundtrip_%s.q2mgdb", dir, label);
        check("it reached the disk", write_file(path, bytes, size), path);

        mapgen_snapshot_t *snap = NULL;
        const mapgen_snapshot_result_t o = MapGenSnapshot_Open(bytes, size, &snap);
        check(pass ? "a deflated snapshot reopens" : "a stored snapshot reopens",
              o == MAPGEN_SNAPSHOT_OK, MapGenSnapshot_ResultName(o));
        if (o != MAPGEN_SNAPSHOT_OK) {
            free(bytes);
            continue;
        }

        check("the payload hash survives the round trip",
              !memcmp(MapGenSnapshot_Header(snap)->payload_sha256, expect,
                      MAPGEN_SHA256_BYTES), "");
        check("every required chunk came back",
              MapGenSnapshot_NumChunks(snap) == MAPGEN_SNAPSHOT_REQUIRED_CHUNKS, "");

        size_t meta_size = 0;
        const uint8_t *meta = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_META, &meta_size);
        check("a chunk's bytes come back unchanged",
              meta && meta_size > 16 && !memcmp(meta, "title=Test Snapshot", 19), "");
        size_t missing = 123;
        check("asking for a chunk that is not there yields nothing",
              MapGenSnapshot_Chunk(snap, 4242, &missing) == NULL && missing == 0, "");

        MapGenSnapshot_Free(snap);
        free(bytes);
    }

    /* The same content compressed two different ways must hash the same: the
       payload hash is about what was learned, not about how it was stored. */
    uint8_t stored_hash[MAPGEN_SHA256_BYTES], deflated_hash[MAPGEN_SHA256_BYTES];
    size_t stored_size = 0, deflated_size = 0;
    for (int pass = 0; pass < 2; pass++) {
        mapgen_snapshot_builder_t *b = make_builder(pass ? MAPGEN_COMPRESSION_DEFLATE
                                                         : MAPGEN_COMPRESSION_NONE);
        uint8_t *bytes = NULL;
        size_t size = 0;
        if (!b || MapGenSnapshot_Finish(b, &bytes, &size) != MAPGEN_SNAPSHOT_OK) {
            MapGenSnapshot_BuilderFree(b);
            continue;
        }
        MapGenSnapshot_BuilderFree(b);
        mapgen_snapshot_t *snap = NULL;
        if (MapGenSnapshot_Open(bytes, size, &snap) == MAPGEN_SNAPSHOT_OK) {
            memcpy(pass ? deflated_hash : stored_hash,
                   MapGenSnapshot_Header(snap)->payload_sha256, MAPGEN_SHA256_BYTES);
            if (pass)
                deflated_size = size;
            else
                stored_size = size;
            MapGenSnapshot_Free(snap);
        }
        free(bytes);
    }
    check("the payload hash does not depend on the compressor",
          !memcmp(stored_hash, deflated_hash, MAPGEN_SHA256_BYTES), "");
    check("deflate actually made the file smaller",
          deflated_size && stored_size && deflated_size < stored_size, "");

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}

static int cmd_selftest(void)
{
    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
    uint8_t *bytes = NULL;
    size_t size = 0;

    check("a builder with no chunks refuses to finish",
          MapGenSnapshot_Finish(b, &bytes, &size) == MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK, "");

    MapGenSnapshot_AddChunk(b, MAPGEN_CHUNK_META, "x", 1, MAPGEN_COMPRESSION_NONE);
    check("adding the same chunk type twice is an error, not a replacement",
          MapGenSnapshot_AddChunk(b, MAPGEN_CHUNK_META, "y", 1, MAPGEN_COMPRESSION_NONE)
          == MAPGEN_SNAPSHOT_ERR_DUPLICATE_CHUNK, "");
    check("an unknown compression method is refused",
          MapGenSnapshot_AddChunk(b, MAPGEN_CHUNK_STATS, "y", 1, (mapgen_compression_t)7)
          == MAPGEN_SNAPSHOT_ERR_BAD_COMPRESSION, "");
    check("a snapshot missing one required chunk refuses to finish",
          MapGenSnapshot_Finish(b, &bytes, &size) == MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK, "");
    MapGenSnapshot_BuilderFree(b);

    mapgen_snapshot_t *snap = NULL;
    check("opening a NULL buffer is an argument error",
          MapGenSnapshot_Open(NULL, 0, &snap) == MAPGEN_SNAPSHOT_ERR_ARGS, "");
    check("opening without somewhere to put the result is an argument error",
          MapGenSnapshot_Open((const uint8_t *)"x", 1, NULL)
          == MAPGEN_SNAPSHOT_ERR_ARGS, "");

    const uint8_t tiny[4] = { 'Q', '2', 'M', 'G' };
    check("a four-byte file is TOO_SMALL",
          MapGenSnapshot_Open(tiny, sizeof(tiny), &snap) == MAPGEN_SNAPSHOT_ERR_TOO_SMALL, "");

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}

/*
 * Deterministic buffers, so the Python side can generate the identical bytes
 * and check the digests against hashlib and zlib rather than against us.
 */
static uint64_t lcg_next(uint64_t *state)
{
    *state = *state * 6364136223846793005ull + 1442695040888963407ull;
    return *state;
}

static int cmd_digests(unsigned count, uint64_t seed)
{
    uint8_t *buffer = malloc(65536);
    if (!buffer)
        return 1;
    uint64_t state = seed;
    for (unsigned i = 0; i < count; i++) {
        const size_t len = (size_t)(lcg_next(&state) % 4096u);
        for (size_t k = 0; k < len; k++)
            buffer[k] = (uint8_t)((lcg_next(&state) >> 33) & 0xFFu);

        uint8_t digest[MAPGEN_SHA256_BYTES];
        char hex[MAPGEN_SHA256_HEX];
        MapGenDigest_Sha256(buffer, len, digest);
        MapGenDigest_Sha256Hex(digest, hex);

        /* The same bytes through the incremental interface, split at an
           awkward place, must give the same answer as the one-shot. */
        mapgen_sha256_t ctx;
        MapGenDigest_Sha256Init(&ctx);
        const size_t split = len / 3;
        MapGenDigest_Sha256Update(&ctx, buffer, split);
        MapGenDigest_Sha256Update(&ctx, buffer + split, len - split);
        uint8_t streamed[MAPGEN_SHA256_BYTES];
        MapGenDigest_Sha256Final(&ctx, streamed);

        printf("%zu %s %08x %d\n", len, hex,
               MapGenDigest_Crc32(buffer, len),
               memcmp(digest, streamed, MAPGEN_SHA256_BYTES) == 0 ? 1 : 0);
    }
    free(buffer);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        printf("usage\n");
        return 2;
    }
    const char *mode = argv[1];

    if (!strcmp(mode, "digests") && argc >= 4)
        return cmd_digests((unsigned)strtoul(argv[2], NULL, 10),
                           strtoull(argv[3], NULL, 10));
    if (!strcmp(mode, "selftest"))
        return cmd_selftest();
    if (!strcmp(mode, "roundtrip") && argc >= 3)
        return cmd_roundtrip(argv[2]);
    if (!strcmp(mode, "build") && argc >= 3)
        return cmd_build(argv[2],
                         (argc >= 4 && !strcmp(argv[3], "deflate"))
                         ? MAPGEN_COMPRESSION_DEFLATE : MAPGEN_COMPRESSION_NONE);
    if (!strcmp(mode, "open") && argc >= 3)
        return cmd_open(argv[2], false);
    if (!strcmp(mode, "hash") && argc >= 3)
        return cmd_open(argv[2], true);

    printf("BAD_MODE\n");
    return 2;
}
