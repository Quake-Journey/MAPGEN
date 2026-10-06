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
==============================================================================

MAPGEN-1 - the `.q2mgdb` snapshot container

Contract section 8. A small project-owned, little-endian, chunked binary
format; explicitly NOT SQLite.

--- This module handles BYTES, never files ----------------------------------

Reading, validating and building a snapshot image are all pure: they take and
return memory. The atomic no-replace commit, the durable journal and the
catalog compare-and-swap are a separate platform concern, because they are
about a filesystem and this is not.

That split matters for testing. A format that can only be exercised by writing
files can only be tested by writing files, and the hostile-input cases below
are the ones that matter most.

--- Everything a file says about itself is suspect ---------------------------

A `.q2mgdb` is data we did not write - it can arrive from another machine, an
older build or a corrupted disk. Every count, offset and size in it is checked
before a single byte is allocated on its word, and each refusal has its own
result code so a failure says WHAT was wrong rather than "invalid file".

--- Layout ------------------------------------------------------------------

Header, 220 bytes, little-endian throughout:

```text
  0  magic[8]                "Q2MGDB\0" plus one zero byte of padding
  8  schema_major   uint16
 10  schema_minor   uint16
 12  header_bytes   uint32   always MAPGEN_SNAPSHOT_HEADER_BYTES
 16  file_bytes     uint64   the whole image, and it must match exactly
 24  flags          uint32
 28  header_crc32   uint32   over the header with these 4 bytes taken as zero
 32  chunk_table_offset uint64
 40  chunk_entry_bytes  uint32
 44  lineage_uuid[16]
 60  revision_uuid[16]
 76  parent_payload_sha256[32]
108  training_recipe_hash[32]
140  created_utc_ms uint64
148  source_count   uint32
152  chunk_count    uint32
156  physics_schema_hash[32]
188  payload_sha256[32]
220  -- end
```

Chunk table entry, 40 bytes:

```text
  0  type         uint32
  4  flags        uint32   bit 0 required, bits 8..15 compression method
  8  offset       uint64   from the start of the file
 16  stored_bytes uint64   as it sits in the file
 24  plain_bytes  uint64   after decompression
 32  crc32        uint32   over the STORED bytes
 36  reserved     uint32   zero
```

`payload_sha256` is over the canonical uncompressed form in fixed chunk-type
order, so it is unchanged by which compressor produced the file, by where the
chunks physically sit, and by any padding. Two builds that learned the same
thing produce the same payload hash even if their bytes differ.

==============================================================================
*/

#pragma once

#include "common/mapgen_digest.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_SNAPSHOT_MAGIC          "Q2MGDB\0\0"
#define MAPGEN_SNAPSHOT_MAGIC_BYTES    8
/*
 * Schema 3.
 *
 * Schema 1 held aggregates - counts, shares, material lists. Schema 2 added a
 * semantic blueprint: where the rooms are, how big, what connects to what.
 * Neither holds a single plane of a donor, and a fidelity control built on
 * what they store reproduces a volume graph and calls it a fork. That is the
 * failure this schema exists to correct, and it is why schema 2 is refused for
 * exactly the reason schema 1 is: geometry cannot be migrated out of rows that
 * never described a solid.
 *
 * A schema-1 or schema-2 file opens as needing a rebuild, and rebuilding
 * re-reads the recorded source BSPs into a NEW immutable revision. Never
 * synthesize missing structure, never read an old row width as a new one,
 * never overwrite the old revision, and never widen a reader to tolerate both
 * shapes.
 */
#define MAPGEN_SNAPSHOT_SCHEMA_MAJOR   3
#define MAPGEN_SNAPSHOT_SCHEMA_MINOR   0
#define MAPGEN_SNAPSHOT_HEADER_BYTES   220
#define MAPGEN_SNAPSHOT_ENTRY_BYTES    40
#define MAPGEN_SNAPSHOT_UUID_BYTES     16

/* Ceilings, all checked before anything is allocated on a file's word. */
#define MAPGEN_SNAPSHOT_MAX_FILE_BYTES   (256u * 1024u * 1024u)
#define MAPGEN_SNAPSHOT_MAX_CHUNKS       64u
#define MAPGEN_SNAPSHOT_MAX_CHUNK_BYTES  (64u * 1024u * 1024u)
#define MAPGEN_SNAPSHOT_MAX_SOURCES      100000u
/* A chunk claiming to expand more than this is a decompression bomb, not a
   well-compressed chunk. */
#define MAPGEN_SNAPSHOT_MAX_RATIO        1024u

/* Chunk flags. */
#define MAPGEN_CHUNK_FLAG_REQUIRED     0x00000001u
#define MAPGEN_CHUNK_COMPRESSION_SHIFT 8
#define MAPGEN_CHUNK_COMPRESSION_MASK  0x0000FF00u

typedef enum {
    MAPGEN_COMPRESSION_NONE = 0,
    MAPGEN_COMPRESSION_DEFLATE = 1,
} mapgen_compression_t;

/*
 * Chunk types. The seven required ones are contract section 8's list; the
 * numbering is fixed forever, because it is the canonical hash order.
 */
typedef enum {
    MAPGEN_CHUNK_META      = 1,
    MAPGEN_CHUNK_SOURCES   = 2,
    MAPGEN_CHUNK_MATERIALS = 3,
    /*
     * Schema 2: the per-source volume/portal GRAPH, not one flat statistic
     * row. The aggregates it used to hold live in STATS, where fidelity 0 and
     * the fitness scores read them.
     */
    MAPGEN_CHUNK_REGIONS   = 4,
    MAPGEN_CHUNK_ENTITIES  = 5,
    MAPGEN_CHUNK_STATS     = 6,
    MAPGEN_CHUNK_QUALITY   = 7,
    /* Schema 2: bounded per-volume occupancy, with explicit limits. */
    MAPGEN_CHUNK_SHAPES    = 8,
    /*
     * The donor's own geometry: canonical convex plane brushes with their
     * contents, per-side texture reference with the real S/T axes, visible
     * face windings, world and submodel ownership, and the architectural
     * entity records bound to them. Everything above is an annotation over
     * this; this is what a candidate at any fidelity above zero begins as.
     */
    MAPGEN_CHUNK_GEOMETRY  = 9,
    /*
     * Where players actually went, from demos of the sources.
     *
     * Optional, and deliberately outside the required set: a corpus nobody has
     * demos for has not been played, which is not the same as broken. What it
     * is not optional about is identity - every row names the source it is
     * about and the physics it was read under.
     */
    MAPGEN_CHUNK_MOVEMENT  = 10,
} mapgen_chunk_type_t;

#define MAPGEN_SNAPSHOT_REQUIRED_CHUNKS 9

/*
 * Bounds on the geometry chunk, checked BEFORE anything is allocated on a
 * file's word. A snapshot is data from outside this program and is sized
 * before it is trusted.
 */
#define MAPGEN_SNAPSHOT_MAX_GEOM_DONORS   256u
#define MAPGEN_SNAPSHOT_MAX_GEOM_BRUSHES  262144u
#define MAPGEN_SNAPSHOT_MAX_GEOM_SIDES    1048576u
#define MAPGEN_SNAPSHOT_MAX_GEOM_FACES    1048576u
#define MAPGEN_SNAPSHOT_MAX_GEOM_POINTS   8388608u
#define MAPGEN_SNAPSHOT_MAX_GEOM_ENTITIES 32768u
#define MAPGEN_SNAPSHOT_MAX_GEOM_TEXT     (8u * 1024u * 1024u)

const char *MapGenSnapshot_ChunkTypeName(uint32_t type);
bool        MapGenSnapshot_ChunkTypeIsRequired(uint32_t type);

typedef enum {
    MAPGEN_SNAPSHOT_OK = 0,
    MAPGEN_SNAPSHOT_ERR_ARGS,
    MAPGEN_SNAPSHOT_ERR_MEMORY,
    MAPGEN_SNAPSHOT_ERR_TOO_SMALL,
    MAPGEN_SNAPSHOT_ERR_BAD_MAGIC,
    MAPGEN_SNAPSHOT_ERR_UNSUPPORTED_MAJOR,
    MAPGEN_SNAPSHOT_ERR_BAD_HEADER_BYTES,
    MAPGEN_SNAPSHOT_ERR_BAD_HEADER_CRC,
    MAPGEN_SNAPSHOT_ERR_BAD_FILE_BYTES,
    MAPGEN_SNAPSHOT_ERR_FILE_TOO_LARGE,
    MAPGEN_SNAPSHOT_ERR_BAD_ENTRY_BYTES,
    MAPGEN_SNAPSHOT_ERR_TOO_MANY_CHUNKS,
    MAPGEN_SNAPSHOT_ERR_TOO_MANY_SOURCES,
    MAPGEN_SNAPSHOT_ERR_TABLE_OUT_OF_BOUNDS,
    MAPGEN_SNAPSHOT_ERR_CHUNK_OUT_OF_BOUNDS,
    MAPGEN_SNAPSHOT_ERR_CHUNK_OVERLAP,
    MAPGEN_SNAPSHOT_ERR_CHUNK_TOO_LARGE,
    MAPGEN_SNAPSHOT_ERR_DUPLICATE_CHUNK,
    MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK,
    MAPGEN_SNAPSHOT_ERR_UNKNOWN_REQUIRED_CHUNK,
    MAPGEN_SNAPSHOT_ERR_BAD_COMPRESSION,
    MAPGEN_SNAPSHOT_ERR_RATIO_TOO_HIGH,
    MAPGEN_SNAPSHOT_ERR_BAD_CHUNK_CRC,
    MAPGEN_SNAPSHOT_ERR_DECOMPRESS_FAILED,
    MAPGEN_SNAPSHOT_ERR_BAD_PAYLOAD_HASH,
    MAPGEN_SNAPSHOT_ERR_RESERVED_NOT_ZERO,

    MAPGEN_SNAPSHOT_RESULT_COUNT
} mapgen_snapshot_result_t;

const char *MapGenSnapshot_ResultName(mapgen_snapshot_result_t r);

typedef struct {
    uint16_t schema_major;
    uint16_t schema_minor;
    uint32_t flags;
    uint64_t file_bytes;
    uint8_t  lineage_uuid[MAPGEN_SNAPSHOT_UUID_BYTES];
    uint8_t  revision_uuid[MAPGEN_SNAPSHOT_UUID_BYTES];
    uint8_t  parent_payload_sha256[MAPGEN_SHA256_BYTES];
    uint8_t  training_recipe_hash[MAPGEN_SHA256_BYTES];
    uint64_t created_utc_ms;
    uint32_t source_count;
    uint32_t chunk_count;
    uint8_t  physics_schema_hash[MAPGEN_SHA256_BYTES];
    uint8_t  payload_sha256[MAPGEN_SHA256_BYTES];
} mapgen_snapshot_header_t;

typedef struct mapgen_snapshot_s mapgen_snapshot_t;

/*
 * Open an image. Validates everything before trusting anything, decompresses
 * every chunk, and recomputes `payload_sha256` - a file whose hash does not
 * describe its own contents is refused, not repaired.
 *
 * The snapshot owns its own copy; `bytes` need not outlive the call.
 */
mapgen_snapshot_result_t MapGenSnapshot_Open(const uint8_t *bytes, size_t size,
                                             mapgen_snapshot_t **out);
void MapGenSnapshot_Free(mapgen_snapshot_t *snap);

const mapgen_snapshot_header_t *MapGenSnapshot_Header(const mapgen_snapshot_t *snap);

/* The uncompressed bytes of one chunk, or NULL when the file has no chunk of
   that type. `*size` is set either way. */
const uint8_t *MapGenSnapshot_Chunk(const mapgen_snapshot_t *snap, uint32_t type,
                                    size_t *size);
uint32_t MapGenSnapshot_NumChunks(const mapgen_snapshot_t *snap);
uint32_t MapGenSnapshot_ChunkTypeAt(const mapgen_snapshot_t *snap, uint32_t index);

/* --- building ----------------------------------------------------------- */

typedef struct mapgen_snapshot_builder_s mapgen_snapshot_builder_t;

mapgen_snapshot_builder_t *MapGenSnapshot_BuilderCreate(void);
void MapGenSnapshot_BuilderFree(mapgen_snapshot_builder_t *b);

/* Identity the caller supplies. A builder with no identity still produces a
   valid file - all-zero UUIDs are legal bytes - so the Training layer above is
   what must refuse to commit one. */
void MapGenSnapshot_SetIdentity(mapgen_snapshot_builder_t *b,
                                const uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES],
                                const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
                                const uint8_t parent_payload[MAPGEN_SHA256_BYTES]);
void MapGenSnapshot_SetProvenance(mapgen_snapshot_builder_t *b,
                                  const uint8_t recipe_hash[MAPGEN_SHA256_BYTES],
                                  const uint8_t physics_hash[MAPGEN_SHA256_BYTES],
                                  uint64_t created_utc_ms, uint32_t source_count);

/* Add one chunk. Adding the same type twice is an error, not a replacement. */
mapgen_snapshot_result_t MapGenSnapshot_AddChunk(mapgen_snapshot_builder_t *b,
                                                 uint32_t type,
                                                 const void *data, size_t size,
                                                 mapgen_compression_t compression);

/*
 * Serialize. Fails unless every required chunk is present, because a file that
 * is missing one cannot be read back by this module and writing it would only
 * move the failure somewhere less convenient.
 *
 * The caller owns `*out_bytes` and frees it with `free`.
 */
mapgen_snapshot_result_t MapGenSnapshot_Finish(mapgen_snapshot_builder_t *b,
                                               uint8_t **out_bytes, size_t *out_size);

/* The canonical payload hash of what a builder currently holds, without
   serializing. Same value the reader recomputes. */
mapgen_snapshot_result_t MapGenSnapshot_BuilderPayloadHash(
    const mapgen_snapshot_builder_t *b, uint8_t out[MAPGEN_SHA256_BYTES]);
