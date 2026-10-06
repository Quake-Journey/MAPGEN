/*
Copyright (C) 2026 Q2PRO-X

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
*/

/*
 * MAPGEN-1 - the `.q2mgdb` container.
 *
 * The order of operations in `MapGenSnapshot_Open` is the whole design: every
 * number the file states about itself is checked against the actual size and
 * against a ceiling BEFORE it is used to allocate or to index. A file gets to
 * describe itself; it does not get to be believed.
 */

#include "common/mapgen_snapshot.h"

#include <stdlib.h>
#include <string.h>

#include <zlib.h>

/* Header field offsets, so the layout in the header comment and the code
   cannot drift apart silently. */
#define OFF_MAGIC          0
#define OFF_SCHEMA_MAJOR   8
#define OFF_SCHEMA_MINOR   10
#define OFF_HEADER_BYTES   12
#define OFF_FILE_BYTES     16
#define OFF_FLAGS          24
#define OFF_HEADER_CRC     28
#define OFF_TABLE_OFFSET   32
#define OFF_ENTRY_BYTES    40
#define OFF_LINEAGE        44
#define OFF_REVISION       60
#define OFF_PARENT_HASH    76
#define OFF_RECIPE_HASH    108
#define OFF_CREATED_MS     140
#define OFF_SOURCE_COUNT   148
#define OFF_CHUNK_COUNT    152
#define OFF_PHYSICS_HASH   156
#define OFF_PAYLOAD_HASH   188

#define ENT_TYPE     0
#define ENT_FLAGS    4
#define ENT_OFFSET   8
#define ENT_STORED   16
#define ENT_PLAIN    24
#define ENT_CRC      32
#define ENT_RESERVED 36

typedef struct {
    uint32_t type;
    uint8_t *data;
    size_t   size;
    mapgen_compression_t compression;
} chunk_t;

struct mapgen_snapshot_s {
    mapgen_snapshot_header_t header;
    chunk_t *chunks;
    uint32_t num_chunks;
};

struct mapgen_snapshot_builder_s {
    mapgen_snapshot_header_t header;
    chunk_t *chunks;
    uint32_t num_chunks;
    uint32_t capacity;
};

/* ------------------------------------------------------------------------ */

const char *MapGenSnapshot_ResultName(mapgen_snapshot_result_t r)
{
    switch (r) {
    case MAPGEN_SNAPSHOT_OK:                        return "OK";
    case MAPGEN_SNAPSHOT_ERR_ARGS:                  return "ERR_ARGS";
    case MAPGEN_SNAPSHOT_ERR_MEMORY:                return "ERR_MEMORY";
    case MAPGEN_SNAPSHOT_ERR_TOO_SMALL:             return "ERR_TOO_SMALL";
    case MAPGEN_SNAPSHOT_ERR_BAD_MAGIC:             return "ERR_BAD_MAGIC";
    case MAPGEN_SNAPSHOT_ERR_UNSUPPORTED_MAJOR:     return "ERR_UNSUPPORTED_MAJOR";
    case MAPGEN_SNAPSHOT_ERR_BAD_HEADER_BYTES:      return "ERR_BAD_HEADER_BYTES";
    case MAPGEN_SNAPSHOT_ERR_BAD_HEADER_CRC:        return "ERR_BAD_HEADER_CRC";
    case MAPGEN_SNAPSHOT_ERR_BAD_FILE_BYTES:        return "ERR_BAD_FILE_BYTES";
    case MAPGEN_SNAPSHOT_ERR_FILE_TOO_LARGE:        return "ERR_FILE_TOO_LARGE";
    case MAPGEN_SNAPSHOT_ERR_BAD_ENTRY_BYTES:       return "ERR_BAD_ENTRY_BYTES";
    case MAPGEN_SNAPSHOT_ERR_TOO_MANY_CHUNKS:       return "ERR_TOO_MANY_CHUNKS";
    case MAPGEN_SNAPSHOT_ERR_TOO_MANY_SOURCES:      return "ERR_TOO_MANY_SOURCES";
    case MAPGEN_SNAPSHOT_ERR_TABLE_OUT_OF_BOUNDS:   return "ERR_TABLE_OUT_OF_BOUNDS";
    case MAPGEN_SNAPSHOT_ERR_CHUNK_OUT_OF_BOUNDS:   return "ERR_CHUNK_OUT_OF_BOUNDS";
    case MAPGEN_SNAPSHOT_ERR_CHUNK_OVERLAP:         return "ERR_CHUNK_OVERLAP";
    case MAPGEN_SNAPSHOT_ERR_CHUNK_TOO_LARGE:       return "ERR_CHUNK_TOO_LARGE";
    case MAPGEN_SNAPSHOT_ERR_DUPLICATE_CHUNK:       return "ERR_DUPLICATE_CHUNK";
    case MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK:         return "ERR_MISSING_CHUNK";
    case MAPGEN_SNAPSHOT_ERR_UNKNOWN_REQUIRED_CHUNK: return "ERR_UNKNOWN_REQUIRED_CHUNK";
    case MAPGEN_SNAPSHOT_ERR_BAD_COMPRESSION:       return "ERR_BAD_COMPRESSION";
    case MAPGEN_SNAPSHOT_ERR_RATIO_TOO_HIGH:        return "ERR_RATIO_TOO_HIGH";
    case MAPGEN_SNAPSHOT_ERR_BAD_CHUNK_CRC:         return "ERR_BAD_CHUNK_CRC";
    case MAPGEN_SNAPSHOT_ERR_DECOMPRESS_FAILED:     return "ERR_DECOMPRESS_FAILED";
    case MAPGEN_SNAPSHOT_ERR_BAD_PAYLOAD_HASH:      return "ERR_BAD_PAYLOAD_HASH";
    case MAPGEN_SNAPSHOT_ERR_RESERVED_NOT_ZERO:     return "ERR_RESERVED_NOT_ZERO";
    case MAPGEN_SNAPSHOT_RESULT_COUNT:              break;
    }
    return "ERR_UNKNOWN";
}

const char *MapGenSnapshot_ChunkTypeName(uint32_t type)
{
    switch (type) {
    case MAPGEN_CHUNK_META:      return "META";
    case MAPGEN_CHUNK_SOURCES:   return "SOURCES";
    case MAPGEN_CHUNK_MATERIALS: return "MATERIALS";
    case MAPGEN_CHUNK_REGIONS:   return "REGIONS";
    case MAPGEN_CHUNK_ENTITIES:  return "ENTITIES";
    case MAPGEN_CHUNK_STATS:     return "STATS";
    case MAPGEN_CHUNK_QUALITY:   return "QUALITY";
    case MAPGEN_CHUNK_SHAPES:    return "SHAPES";
    case MAPGEN_CHUNK_GEOMETRY:  return "GEOMETRY";
    case MAPGEN_CHUNK_MOVEMENT:  return "MOVEMENT";
    default:                     return "OPTIONAL";
    }
}

bool MapGenSnapshot_ChunkTypeIsRequired(uint32_t type)
{
    return type >= MAPGEN_CHUNK_META && type <= MAPGEN_CHUNK_GEOMETRY;
}

/* --- little-endian readers, which never read past `size` ---------------- */

static uint16_t rd_u16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }

static uint32_t rd_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t rd_u64(const uint8_t *p)
{
    return (uint64_t)rd_u32(p) | ((uint64_t)rd_u32(p + 4) << 32);
}

static void wr_u16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }

static void wr_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static void wr_u64(uint8_t *p, uint64_t v)
{
    wr_u32(p, (uint32_t)v);
    wr_u32(p + 4, (uint32_t)(v >> 32));
}

/*
 * The header's CRC, computed with the CRC field itself taken as zero -
 * otherwise it would have to contain a hash of itself.
 *
 * It covers the CHUNK TABLE as well, and that is deliberate. Chunk CRCs cover
 * chunk bytes and this covers the header, which left the table itself
 * unprotected: flipping a spare bit in an entry's flags changed the file and
 * was accepted by both readers, because nothing validated the field and the
 * payload hash does not see the table at all. Extending this CRC closes that
 * without changing the layout, since the writer lays the table down before it
 * stamps the header.
 */
static uint32_t header_crc(const uint8_t *image, uint64_t table_offset,
                           uint64_t table_bytes)
{
    uint32_t state = MapGenDigest_Crc32Init();
    state = MapGenDigest_Crc32Update(state, image, OFF_HEADER_CRC);
    const uint8_t zero[4] = { 0, 0, 0, 0 };
    state = MapGenDigest_Crc32Update(state, zero, sizeof(zero));
    state = MapGenDigest_Crc32Update(state, image + OFF_HEADER_CRC + 4,
                                     MAPGEN_SNAPSHOT_HEADER_BYTES - OFF_HEADER_CRC - 4);
    state = MapGenDigest_Crc32Update(state, image + table_offset, (size_t)table_bytes);
    return MapGenDigest_Crc32Final(state);
}

/* ------------------------------------------------------------------------ */

static int compare_chunks(const void *a, const void *b)
{
    const uint32_t x = ((const chunk_t *)a)->type;
    const uint32_t y = ((const chunk_t *)b)->type;
    return (x > y) - (x < y);
}

/*
 * The canonical payload hash: chunk type order, uncompressed bytes, and
 * nothing about how or where they were stored. Two builds that learned the
 * same thing hash the same even when their files differ byte for byte.
 */
static void payload_hash(const chunk_t *chunks, uint32_t count,
                         uint8_t out[MAPGEN_SHA256_BYTES])
{
    chunk_t *sorted = count ? malloc((size_t)count * sizeof(chunk_t)) : NULL;
    if (count && !sorted) {
        memset(out, 0, MAPGEN_SHA256_BYTES);
        return;
    }
    if (count) {
        memcpy(sorted, chunks, (size_t)count * sizeof(chunk_t));
        qsort(sorted, count, sizeof(chunk_t), compare_chunks);
    }

    mapgen_sha256_t ctx;
    MapGenDigest_Sha256Init(&ctx);

    uint8_t scratch[8];
    wr_u32(scratch, count);
    MapGenDigest_Sha256Update(&ctx, scratch, 4);

    for (uint32_t i = 0; i < count; i++) {
        wr_u32(scratch, sorted[i].type);
        MapGenDigest_Sha256Update(&ctx, scratch, 4);
        wr_u64(scratch, (uint64_t)sorted[i].size);
        MapGenDigest_Sha256Update(&ctx, scratch, 8);
        MapGenDigest_Sha256Update(&ctx, sorted[i].data, sorted[i].size);
    }

    MapGenDigest_Sha256Final(&ctx, out);
    free(sorted);
}

/* ------------------------------------------------------------------------ */

static void free_chunks(chunk_t *chunks, uint32_t count)
{
    if (!chunks)
        return;
    for (uint32_t i = 0; i < count; i++)
        free(chunks[i].data);
    free(chunks);
}

mapgen_snapshot_result_t MapGenSnapshot_Open(const uint8_t *bytes, size_t size,
                                             mapgen_snapshot_t **out)
{
    if (!bytes || !out)
        return MAPGEN_SNAPSHOT_ERR_ARGS;
    *out = NULL;

    if (size < MAPGEN_SNAPSHOT_HEADER_BYTES)
        return MAPGEN_SNAPSHOT_ERR_TOO_SMALL;
    if (size > MAPGEN_SNAPSHOT_MAX_FILE_BYTES)
        return MAPGEN_SNAPSHOT_ERR_FILE_TOO_LARGE;

    if (memcmp(bytes + OFF_MAGIC, MAPGEN_SNAPSHOT_MAGIC, MAPGEN_SNAPSHOT_MAGIC_BYTES))
        return MAPGEN_SNAPSHOT_ERR_BAD_MAGIC;

    const uint16_t major = rd_u16(bytes + OFF_SCHEMA_MAJOR);
    if (major != MAPGEN_SNAPSHOT_SCHEMA_MAJOR)
        return MAPGEN_SNAPSHOT_ERR_UNSUPPORTED_MAJOR;

    if (rd_u32(bytes + OFF_HEADER_BYTES) != MAPGEN_SNAPSHOT_HEADER_BYTES)
        return MAPGEN_SNAPSHOT_ERR_BAD_HEADER_BYTES;
    if (rd_u64(bytes + OFF_FILE_BYTES) != (uint64_t)size)
        return MAPGEN_SNAPSHOT_ERR_BAD_FILE_BYTES;
    if (rd_u32(bytes + OFF_ENTRY_BYTES) != MAPGEN_SNAPSHOT_ENTRY_BYTES)
        return MAPGEN_SNAPSHOT_ERR_BAD_ENTRY_BYTES;

    const uint32_t chunk_count = rd_u32(bytes + OFF_CHUNK_COUNT);
    if (chunk_count > MAPGEN_SNAPSHOT_MAX_CHUNKS)
        return MAPGEN_SNAPSHOT_ERR_TOO_MANY_CHUNKS;
    if (rd_u32(bytes + OFF_SOURCE_COUNT) > MAPGEN_SNAPSHOT_MAX_SOURCES)
        return MAPGEN_SNAPSHOT_ERR_TOO_MANY_SOURCES;

    const uint64_t table_offset = rd_u64(bytes + OFF_TABLE_OFFSET);
    const uint64_t table_bytes = (uint64_t)chunk_count * MAPGEN_SNAPSHOT_ENTRY_BYTES;
    if (table_offset < MAPGEN_SNAPSHOT_HEADER_BYTES ||
        table_offset > (uint64_t)size ||
        table_bytes > (uint64_t)size - table_offset)
        return MAPGEN_SNAPSHOT_ERR_TABLE_OUT_OF_BOUNDS;

    /* Only now, with the table's bounds known to be inside the buffer we
       actually hold, can the CRC that covers it be computed at all. */
    if (header_crc(bytes, table_offset, table_bytes) != rd_u32(bytes + OFF_HEADER_CRC))
        return MAPGEN_SNAPSHOT_ERR_BAD_HEADER_CRC;

    /* Nothing is allocated until every entry has been checked against the
       real size of the buffer we actually hold. */
    for (uint32_t i = 0; i < chunk_count; i++) {
        const uint8_t *e = bytes + table_offset + (uint64_t)i * MAPGEN_SNAPSHOT_ENTRY_BYTES;
        const uint64_t offset = rd_u64(e + ENT_OFFSET);
        const uint64_t stored = rd_u64(e + ENT_STORED);
        const uint64_t plain = rd_u64(e + ENT_PLAIN);
        const uint32_t flags = rd_u32(e + ENT_FLAGS);

        if (rd_u32(e + ENT_RESERVED) != 0)
            return MAPGEN_SNAPSHOT_ERR_RESERVED_NOT_ZERO;
        if (offset < MAPGEN_SNAPSHOT_HEADER_BYTES || offset > (uint64_t)size ||
            stored > (uint64_t)size - offset)
            return MAPGEN_SNAPSHOT_ERR_CHUNK_OUT_OF_BOUNDS;
        if (plain > MAPGEN_SNAPSHOT_MAX_CHUNK_BYTES ||
            stored > MAPGEN_SNAPSHOT_MAX_CHUNK_BYTES)
            return MAPGEN_SNAPSHOT_ERR_CHUNK_TOO_LARGE;

        const uint32_t method = (flags & MAPGEN_CHUNK_COMPRESSION_MASK)
                              >> MAPGEN_CHUNK_COMPRESSION_SHIFT;
        if (method != MAPGEN_COMPRESSION_NONE && method != MAPGEN_COMPRESSION_DEFLATE)
            return MAPGEN_SNAPSHOT_ERR_BAD_COMPRESSION;
        if (method == MAPGEN_COMPRESSION_NONE && plain != stored)
            return MAPGEN_SNAPSHOT_ERR_BAD_COMPRESSION;
        /* A chunk that claims to expand a thousandfold is a bomb, and it is
           refused BEFORE the buffer it asks for is allocated. */
        if (stored && plain / (stored ? stored : 1) > MAPGEN_SNAPSHOT_MAX_RATIO)
            return MAPGEN_SNAPSHOT_ERR_RATIO_TOO_HIGH;
        if (!stored && plain)
            return MAPGEN_SNAPSHOT_ERR_RATIO_TOO_HIGH;

        const uint32_t type = rd_u32(e + ENT_TYPE);
        for (uint32_t j = 0; j < i; j++) {
            const uint8_t *o = bytes + table_offset + (uint64_t)j * MAPGEN_SNAPSHOT_ENTRY_BYTES;
            if (rd_u32(o + ENT_TYPE) == type)
                return MAPGEN_SNAPSHOT_ERR_DUPLICATE_CHUNK;
            const uint64_t other_off = rd_u64(o + ENT_OFFSET);
            const uint64_t other_end = other_off + rd_u64(o + ENT_STORED);
            if (offset < other_end && other_off < offset + stored)
                return MAPGEN_SNAPSHOT_ERR_CHUNK_OVERLAP;
        }
        /* A chunk may not sit on top of the header or the table either. */
        if (offset < table_offset + table_bytes && table_offset < offset + stored)
            return MAPGEN_SNAPSHOT_ERR_CHUNK_OVERLAP;
    }

    /* Every required chunk must be present, and an unknown type may not claim
       to be required - we would not know what to do with it. */
    bool present[MAPGEN_SNAPSHOT_REQUIRED_CHUNKS + 1] = { false };
    for (uint32_t i = 0; i < chunk_count; i++) {
        const uint8_t *e = bytes + table_offset + (uint64_t)i * MAPGEN_SNAPSHOT_ENTRY_BYTES;
        const uint32_t type = rd_u32(e + ENT_TYPE);
        const uint32_t flags = rd_u32(e + ENT_FLAGS);
        if (MapGenSnapshot_ChunkTypeIsRequired(type))
            present[type] = true;
        else if (flags & MAPGEN_CHUNK_FLAG_REQUIRED)
            return MAPGEN_SNAPSHOT_ERR_UNKNOWN_REQUIRED_CHUNK;
    }
    for (uint32_t t = MAPGEN_CHUNK_META; t <= MAPGEN_CHUNK_GEOMETRY; t++)
        if (!present[t])
            return MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK;

    mapgen_snapshot_t *snap = calloc(1, sizeof(*snap));
    if (!snap)
        return MAPGEN_SNAPSHOT_ERR_MEMORY;
    if (chunk_count) {
        snap->chunks = calloc(chunk_count, sizeof(chunk_t));
        if (!snap->chunks) {
            free(snap);
            return MAPGEN_SNAPSHOT_ERR_MEMORY;
        }
    }

    for (uint32_t i = 0; i < chunk_count; i++) {
        const uint8_t *e = bytes + table_offset + (uint64_t)i * MAPGEN_SNAPSHOT_ENTRY_BYTES;
        const uint64_t offset = rd_u64(e + ENT_OFFSET);
        const uint64_t stored = rd_u64(e + ENT_STORED);
        const uint64_t plain = rd_u64(e + ENT_PLAIN);
        const uint32_t flags = rd_u32(e + ENT_FLAGS);
        const uint32_t method = (flags & MAPGEN_CHUNK_COMPRESSION_MASK)
                              >> MAPGEN_CHUNK_COMPRESSION_SHIFT;
        const uint8_t *stored_bytes = bytes + offset;

        if (MapGenDigest_Crc32(stored_bytes, (size_t)stored) != rd_u32(e + ENT_CRC)) {
            free_chunks(snap->chunks, snap->num_chunks);
            free(snap);
            return MAPGEN_SNAPSHOT_ERR_BAD_CHUNK_CRC;
        }

        chunk_t *c = &snap->chunks[snap->num_chunks];
        c->type = rd_u32(e + ENT_TYPE);
        c->size = (size_t)plain;
        c->compression = (mapgen_compression_t)method;
        c->data = malloc(plain ? (size_t)plain : 1);
        if (!c->data) {
            free_chunks(snap->chunks, snap->num_chunks);
            free(snap);
            return MAPGEN_SNAPSHOT_ERR_MEMORY;
        }
        snap->num_chunks++;

        if (method == MAPGEN_COMPRESSION_NONE) {
            memcpy(c->data, stored_bytes, (size_t)plain);
        } else {
            uLongf produced = (uLongf)plain;
            const int rc = uncompress(c->data, &produced, stored_bytes, (uLong)stored);
            if (rc != Z_OK || produced != (uLongf)plain) {
                free_chunks(snap->chunks, snap->num_chunks);
                free(snap);
                return MAPGEN_SNAPSHOT_ERR_DECOMPRESS_FAILED;
            }
        }
    }

    uint8_t computed[MAPGEN_SHA256_BYTES];
    payload_hash(snap->chunks, snap->num_chunks, computed);
    if (memcmp(computed, bytes + OFF_PAYLOAD_HASH, MAPGEN_SHA256_BYTES)) {
        free_chunks(snap->chunks, snap->num_chunks);
        free(snap);
        return MAPGEN_SNAPSHOT_ERR_BAD_PAYLOAD_HASH;
    }

    mapgen_snapshot_header_t *h = &snap->header;
    h->schema_major = major;
    h->schema_minor = rd_u16(bytes + OFF_SCHEMA_MINOR);
    h->flags = rd_u32(bytes + OFF_FLAGS);
    h->file_bytes = rd_u64(bytes + OFF_FILE_BYTES);
    memcpy(h->lineage_uuid, bytes + OFF_LINEAGE, MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(h->revision_uuid, bytes + OFF_REVISION, MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(h->parent_payload_sha256, bytes + OFF_PARENT_HASH, MAPGEN_SHA256_BYTES);
    memcpy(h->training_recipe_hash, bytes + OFF_RECIPE_HASH, MAPGEN_SHA256_BYTES);
    h->created_utc_ms = rd_u64(bytes + OFF_CREATED_MS);
    h->source_count = rd_u32(bytes + OFF_SOURCE_COUNT);
    h->chunk_count = chunk_count;
    memcpy(h->physics_schema_hash, bytes + OFF_PHYSICS_HASH, MAPGEN_SHA256_BYTES);
    memcpy(h->payload_sha256, bytes + OFF_PAYLOAD_HASH, MAPGEN_SHA256_BYTES);

    *out = snap;
    return MAPGEN_SNAPSHOT_OK;
}

void MapGenSnapshot_Free(mapgen_snapshot_t *snap)
{
    if (!snap)
        return;
    free_chunks(snap->chunks, snap->num_chunks);
    free(snap);
}

const mapgen_snapshot_header_t *MapGenSnapshot_Header(const mapgen_snapshot_t *snap)
{
    return snap ? &snap->header : NULL;
}

const uint8_t *MapGenSnapshot_Chunk(const mapgen_snapshot_t *snap, uint32_t type,
                                    size_t *size)
{
    if (size)
        *size = 0;
    if (!snap)
        return NULL;
    for (uint32_t i = 0; i < snap->num_chunks; i++) {
        if (snap->chunks[i].type != type)
            continue;
        if (size)
            *size = snap->chunks[i].size;
        return snap->chunks[i].data;
    }
    return NULL;
}

uint32_t MapGenSnapshot_NumChunks(const mapgen_snapshot_t *snap)
{
    return snap ? snap->num_chunks : 0;
}

uint32_t MapGenSnapshot_ChunkTypeAt(const mapgen_snapshot_t *snap, uint32_t index)
{
    return (snap && index < snap->num_chunks) ? snap->chunks[index].type : 0;
}

/* ------------------------------------------------------------------------ */

mapgen_snapshot_builder_t *MapGenSnapshot_BuilderCreate(void)
{
    mapgen_snapshot_builder_t *b = calloc(1, sizeof(*b));
    if (!b)
        return NULL;
    b->header.schema_major = MAPGEN_SNAPSHOT_SCHEMA_MAJOR;
    b->header.schema_minor = MAPGEN_SNAPSHOT_SCHEMA_MINOR;
    return b;
}

void MapGenSnapshot_BuilderFree(mapgen_snapshot_builder_t *b)
{
    if (!b)
        return;
    free_chunks(b->chunks, b->num_chunks);
    free(b);
}

void MapGenSnapshot_SetIdentity(mapgen_snapshot_builder_t *b,
                                const uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES],
                                const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
                                const uint8_t parent_payload[MAPGEN_SHA256_BYTES])
{
    if (!b)
        return;
    if (lineage)
        memcpy(b->header.lineage_uuid, lineage, MAPGEN_SNAPSHOT_UUID_BYTES);
    if (revision)
        memcpy(b->header.revision_uuid, revision, MAPGEN_SNAPSHOT_UUID_BYTES);
    if (parent_payload)
        memcpy(b->header.parent_payload_sha256, parent_payload, MAPGEN_SHA256_BYTES);
}

void MapGenSnapshot_SetProvenance(mapgen_snapshot_builder_t *b,
                                  const uint8_t recipe_hash[MAPGEN_SHA256_BYTES],
                                  const uint8_t physics_hash[MAPGEN_SHA256_BYTES],
                                  uint64_t created_utc_ms, uint32_t source_count)
{
    if (!b)
        return;
    if (recipe_hash)
        memcpy(b->header.training_recipe_hash, recipe_hash, MAPGEN_SHA256_BYTES);
    if (physics_hash)
        memcpy(b->header.physics_schema_hash, physics_hash, MAPGEN_SHA256_BYTES);
    b->header.created_utc_ms = created_utc_ms;
    b->header.source_count = source_count;
}

mapgen_snapshot_result_t MapGenSnapshot_AddChunk(mapgen_snapshot_builder_t *b,
                                                 uint32_t type,
                                                 const void *data, size_t size,
                                                 mapgen_compression_t compression)
{
    if (!b || (!data && size))
        return MAPGEN_SNAPSHOT_ERR_ARGS;
    if (size > MAPGEN_SNAPSHOT_MAX_CHUNK_BYTES)
        return MAPGEN_SNAPSHOT_ERR_CHUNK_TOO_LARGE;
    if (compression != MAPGEN_COMPRESSION_NONE && compression != MAPGEN_COMPRESSION_DEFLATE)
        return MAPGEN_SNAPSHOT_ERR_BAD_COMPRESSION;
    if (b->num_chunks >= MAPGEN_SNAPSHOT_MAX_CHUNKS)
        return MAPGEN_SNAPSHOT_ERR_TOO_MANY_CHUNKS;

    for (uint32_t i = 0; i < b->num_chunks; i++)
        if (b->chunks[i].type == type)
            return MAPGEN_SNAPSHOT_ERR_DUPLICATE_CHUNK;

    if (b->num_chunks == b->capacity) {
        const uint32_t want = b->capacity ? b->capacity * 2u : 8u;
        void *grown = realloc(b->chunks, (size_t)want * sizeof(chunk_t));
        if (!grown)
            return MAPGEN_SNAPSHOT_ERR_MEMORY;
        b->chunks = grown;
        b->capacity = want;
    }

    chunk_t *c = &b->chunks[b->num_chunks];
    memset(c, 0, sizeof(*c));
    c->type = type;
    c->size = size;
    c->compression = compression;
    c->data = malloc(size ? size : 1);
    if (!c->data)
        return MAPGEN_SNAPSHOT_ERR_MEMORY;
    if (size)
        memcpy(c->data, data, size);
    b->num_chunks++;
    return MAPGEN_SNAPSHOT_OK;
}

mapgen_snapshot_result_t MapGenSnapshot_BuilderPayloadHash(
    const mapgen_snapshot_builder_t *b, uint8_t out[MAPGEN_SHA256_BYTES])
{
    if (!b || !out)
        return MAPGEN_SNAPSHOT_ERR_ARGS;
    payload_hash(b->chunks, b->num_chunks, out);
    return MAPGEN_SNAPSHOT_OK;
}

mapgen_snapshot_result_t MapGenSnapshot_Finish(mapgen_snapshot_builder_t *b,
                                               uint8_t **out_bytes, size_t *out_size)
{
    if (!b || !out_bytes || !out_size)
        return MAPGEN_SNAPSHOT_ERR_ARGS;
    *out_bytes = NULL;
    *out_size = 0;

    for (uint32_t t = MAPGEN_CHUNK_META; t <= MAPGEN_CHUNK_GEOMETRY; t++) {
        bool found = false;
        for (uint32_t i = 0; i < b->num_chunks && !found; i++)
            found = b->chunks[i].type == t;
        if (!found)
            return MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK;
    }

    /* Compress first, so the layout is decided against real stored sizes
       rather than against a guess that would need patching afterwards. */
    uint8_t **stored = calloc(b->num_chunks ? b->num_chunks : 1, sizeof(uint8_t *));
    size_t *stored_size = calloc(b->num_chunks ? b->num_chunks : 1, sizeof(size_t));
    if (!stored || !stored_size) {
        free(stored);
        free(stored_size);
        return MAPGEN_SNAPSHOT_ERR_MEMORY;
    }

    mapgen_snapshot_result_t rc = MAPGEN_SNAPSHOT_OK;
    for (uint32_t i = 0; i < b->num_chunks && rc == MAPGEN_SNAPSHOT_OK; i++) {
        const chunk_t *c = &b->chunks[i];
        if (c->compression == MAPGEN_COMPRESSION_NONE) {
            stored_size[i] = c->size;
            stored[i] = malloc(c->size ? c->size : 1);
            if (!stored[i]) {
                rc = MAPGEN_SNAPSHOT_ERR_MEMORY;
                break;
            }
            memcpy(stored[i], c->data, c->size);
            continue;
        }
        uLongf bound = compressBound((uLong)c->size);
        stored[i] = malloc(bound ? bound : 1);
        if (!stored[i]) {
            rc = MAPGEN_SNAPSHOT_ERR_MEMORY;
            break;
        }
        if (compress2(stored[i], &bound, c->data, (uLong)c->size, 9) != Z_OK) {
            rc = MAPGEN_SNAPSHOT_ERR_DECOMPRESS_FAILED;
            break;
        }
        stored_size[i] = (size_t)bound;
        /* Refuse to WRITE what the reader would refuse to read. */
        if (c->size && stored_size[i] &&
            c->size / stored_size[i] > MAPGEN_SNAPSHOT_MAX_RATIO)
            rc = MAPGEN_SNAPSHOT_ERR_RATIO_TOO_HIGH;
    }

    if (rc != MAPGEN_SNAPSHOT_OK) {
        for (uint32_t i = 0; i < b->num_chunks; i++)
            free(stored[i]);
        free(stored);
        free(stored_size);
        return rc;
    }

    uint64_t total = MAPGEN_SNAPSHOT_HEADER_BYTES;
    for (uint32_t i = 0; i < b->num_chunks; i++)
        total += stored_size[i];
    const uint64_t table_offset = total;
    total += (uint64_t)b->num_chunks * MAPGEN_SNAPSHOT_ENTRY_BYTES;

    if (total > MAPGEN_SNAPSHOT_MAX_FILE_BYTES) {
        for (uint32_t i = 0; i < b->num_chunks; i++)
            free(stored[i]);
        free(stored);
        free(stored_size);
        return MAPGEN_SNAPSHOT_ERR_FILE_TOO_LARGE;
    }

    uint8_t *image = calloc((size_t)total, 1);
    if (!image) {
        for (uint32_t i = 0; i < b->num_chunks; i++)
            free(stored[i]);
        free(stored);
        free(stored_size);
        return MAPGEN_SNAPSHOT_ERR_MEMORY;
    }

    uint64_t cursor = MAPGEN_SNAPSHOT_HEADER_BYTES;
    for (uint32_t i = 0; i < b->num_chunks; i++) {
        const chunk_t *c = &b->chunks[i];
        memcpy(image + cursor, stored[i], stored_size[i]);

        uint8_t *e = image + table_offset + (uint64_t)i * MAPGEN_SNAPSHOT_ENTRY_BYTES;
        wr_u32(e + ENT_TYPE, c->type);
        wr_u32(e + ENT_FLAGS,
               (MapGenSnapshot_ChunkTypeIsRequired(c->type) ? MAPGEN_CHUNK_FLAG_REQUIRED : 0u) |
               ((uint32_t)c->compression << MAPGEN_CHUNK_COMPRESSION_SHIFT));
        wr_u64(e + ENT_OFFSET, cursor);
        wr_u64(e + ENT_STORED, stored_size[i]);
        wr_u64(e + ENT_PLAIN, c->size);
        wr_u32(e + ENT_CRC, MapGenDigest_Crc32(stored[i], stored_size[i]));
        wr_u32(e + ENT_RESERVED, 0);

        cursor += stored_size[i];
        free(stored[i]);
    }
    free(stored);
    free(stored_size);

    memcpy(image + OFF_MAGIC, MAPGEN_SNAPSHOT_MAGIC, MAPGEN_SNAPSHOT_MAGIC_BYTES);
    wr_u16(image + OFF_SCHEMA_MAJOR, b->header.schema_major);
    wr_u16(image + OFF_SCHEMA_MINOR, b->header.schema_minor);
    wr_u32(image + OFF_HEADER_BYTES, MAPGEN_SNAPSHOT_HEADER_BYTES);
    wr_u64(image + OFF_FILE_BYTES, total);
    wr_u32(image + OFF_FLAGS, b->header.flags);
    wr_u64(image + OFF_TABLE_OFFSET, table_offset);
    wr_u32(image + OFF_ENTRY_BYTES, MAPGEN_SNAPSHOT_ENTRY_BYTES);
    memcpy(image + OFF_LINEAGE, b->header.lineage_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(image + OFF_REVISION, b->header.revision_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(image + OFF_PARENT_HASH, b->header.parent_payload_sha256, MAPGEN_SHA256_BYTES);
    memcpy(image + OFF_RECIPE_HASH, b->header.training_recipe_hash, MAPGEN_SHA256_BYTES);
    wr_u64(image + OFF_CREATED_MS, b->header.created_utc_ms);
    wr_u32(image + OFF_SOURCE_COUNT, b->header.source_count);
    wr_u32(image + OFF_CHUNK_COUNT, b->num_chunks);
    memcpy(image + OFF_PHYSICS_HASH, b->header.physics_schema_hash, MAPGEN_SHA256_BYTES);

    uint8_t hash[MAPGEN_SHA256_BYTES];
    payload_hash(b->chunks, b->num_chunks, hash);
    memcpy(image + OFF_PAYLOAD_HASH, hash, MAPGEN_SHA256_BYTES);

    wr_u32(image + OFF_HEADER_CRC, 0);
    wr_u32(image + OFF_HEADER_CRC,
           header_crc(image, table_offset,
                      (uint64_t)b->num_chunks * MAPGEN_SNAPSHOT_ENTRY_BYTES));

    *out_bytes = image;
    *out_size = (size_t)total;
    return MAPGEN_SNAPSHOT_OK;
}
