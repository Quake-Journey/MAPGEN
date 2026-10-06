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
 * MAPGEN-1 - New, Extend, Rebuild and Rename.
 *
 * The parent is opened, read and never written. Every operation builds a fresh
 * image; nothing in this file can modify a snapshot that already exists,
 * which is the whole of contract 7's copy-on-write rule made structural rather
 * than remembered.
 */

#include "common/mapgen_lineage.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char *MapGenLineage_ResultName(mapgen_lineage_result_t r)
{
    switch (r) {
    case MAPGEN_LINEAGE_OK:                 return "OK";
    case MAPGEN_LINEAGE_ERR_ARGS:           return "ERR_ARGS";
    case MAPGEN_LINEAGE_ERR_MEMORY:         return "ERR_MEMORY";
    case MAPGEN_LINEAGE_ERR_PARENT_INVALID: return "ERR_PARENT_INVALID";
    case MAPGEN_LINEAGE_ERR_SAME_REVISION:  return "ERR_SAME_REVISION";
    case MAPGEN_LINEAGE_ERR_NO_SOURCES:     return "ERR_NO_SOURCES";
    case MAPGEN_LINEAGE_ERR_TITLE_INVALID:  return "ERR_TITLE_INVALID";
    }
    return "ERR_UNKNOWN";
}

/* ------------------------------------------------------------------------ */

bool MapGenLineage_Title(const mapgen_snapshot_t *snap,
                         char out[MAPGEN_LINEAGE_TITLE_BYTES])
{
    if (!out)
        return false;
    out[0] = '\0';
    size_t size = 0;
    const uint8_t *meta = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_META, &size);
    if (!meta || !size)
        return false;

    /* `title=` at the start of a line, to the end of that line. */
    for (size_t i = 0; i + 6 <= size; i++) {
        if (i && meta[i - 1] != '\n')
            continue;
        if (memcmp(meta + i, "title=", 6))
            continue;
        size_t n = 0;
        for (size_t k = i + 6; k < size && meta[k] != '\n'; k++) {
            if (n + 1 >= MAPGEN_LINEAGE_TITLE_BYTES)
                break;
            out[n++] = (char)meta[k];
        }
        out[n] = '\0';
        return n > 0;
    }
    return false;
}

/*
 * A slug is ASCII, lowercase, and contains only what every filesystem this
 * ships on accepts. A Cyrillic title therefore does not become a filename in
 * some codepage - it becomes a transliteration-free run of underscores plus
 * whatever ASCII it contained, and the DISPLAY title keeps the real text.
 */
size_t MapGenLineage_Slug(const char *title, char *out, size_t capacity)
{
    size_t n = 0;
    bool last_was_break = true;
    if (!title)
        title = "";

    for (const unsigned char *p = (const unsigned char *)title; *p; p++) {
        char c = 0;
        if (*p >= 'A' && *p <= 'Z')
            c = (char)(*p - 'A' + 'a');
        else if ((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9'))
            c = (char)*p;

        if (!c) {
            /* Anything else - space, punctuation, a byte of a UTF-8 sequence -
               collapses to a single separator. Runs never repeat. */
            if (last_was_break)
                continue;
            c = '_';
            last_was_break = true;
        } else {
            last_was_break = false;
        }
        if (out && n + 1 < capacity)
            out[n] = c;
        n++;
    }
    /* Never end on a separator, and never produce nothing at all. */
    while (n && out && n - 1 < capacity && out[n - 1] == '_')
        n--;
    if (!n) {
        const char *fallback = "snapshot";
        for (const char *p = fallback; *p; p++) {
            if (out && n + 1 < capacity)
                out[n] = *p;
            n++;
        }
    }
    if (out && capacity)
        out[n < capacity ? n : capacity - 1] = '\0';
    return n;
}

/* ------------------------------------------------------------------------ */

static mapgen_lineage_result_t finish(mapgen_snapshot_builder_t *b,
                                      uint8_t **out_bytes, size_t *out_size)
{
    const mapgen_snapshot_result_t r = MapGenSnapshot_Finish(b, out_bytes, out_size);
    MapGenSnapshot_BuilderFree(b);
    return r == MAPGEN_SNAPSHOT_OK ? MAPGEN_LINEAGE_OK : MAPGEN_LINEAGE_ERR_MEMORY;
}

mapgen_lineage_result_t MapGenLineage_New(
    const mapgen_training_t *training,
    const uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES],
    const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
    uint64_t created_utc_ms,
    mapgen_compression_t compression,
    uint8_t **out_bytes, size_t *out_size)
{
    if (!training || !lineage || !revision || !out_bytes || !out_size)
        return MAPGEN_LINEAGE_ERR_ARGS;
    *out_bytes = NULL;
    *out_size = 0;
    if (!MapGenTraining_NumAccepted(training))
        return MAPGEN_LINEAGE_ERR_NO_SOURCES;

    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
    if (!b)
        return MAPGEN_LINEAGE_ERR_MEMORY;
    if (MapGenTraining_FillSnapshot(training, b, compression) != MAPGEN_TRAINING_OK) {
        MapGenSnapshot_BuilderFree(b);
        return MAPGEN_LINEAGE_ERR_MEMORY;
    }
    /* No parent, so the parent payload hash stays all zeros - which is what
       "this lineage starts here" looks like on disk. */
    MapGenSnapshot_SetIdentity(b, lineage, revision, NULL);
    MapGenSnapshot_SetProvenance(b, NULL, NULL, created_utc_ms,
                                 MapGenTraining_NumSources(training));
    return finish(b, out_bytes, out_size);
}

/*
 * Extend and Rebuild differ in where the payload comes from, and in nothing
 * else: both keep the lineage, both record the parent's payload hash, both
 * refuse to reuse the parent's revision identity.
 */
static mapgen_lineage_result_t derive(const mapgen_snapshot_t *parent,
                                      const mapgen_training_t *training,
                                      const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
                                      uint64_t created_utc_ms,
                                      mapgen_compression_t compression,
                                      uint8_t **out_bytes, size_t *out_size)
{
    const mapgen_snapshot_header_t *h = MapGenSnapshot_Header(parent);
    if (!h)
        return MAPGEN_LINEAGE_ERR_PARENT_INVALID;
    if (!memcmp(h->revision_uuid, revision, MAPGEN_SNAPSHOT_UUID_BYTES))
        return MAPGEN_LINEAGE_ERR_SAME_REVISION;

    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
    if (!b)
        return MAPGEN_LINEAGE_ERR_MEMORY;
    if (MapGenTraining_FillSnapshot(training, b, compression) != MAPGEN_TRAINING_OK) {
        MapGenSnapshot_BuilderFree(b);
        return MAPGEN_LINEAGE_ERR_MEMORY;
    }
    MapGenSnapshot_SetIdentity(b, h->lineage_uuid, revision, h->payload_sha256);
    MapGenSnapshot_SetProvenance(b, NULL, NULL, created_utc_ms,
                                 MapGenTraining_NumSources(training));
    return finish(b, out_bytes, out_size);
}

mapgen_lineage_result_t MapGenLineage_Extend(
    const mapgen_snapshot_t *parent,
    const mapgen_training_t *training,
    const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
    uint64_t created_utc_ms,
    mapgen_compression_t compression,
    uint8_t **out_bytes, size_t *out_size,
    uint32_t *out_added, uint32_t *out_skipped)
{
    if (!parent || !training || !revision || !out_bytes || !out_size)
        return MAPGEN_LINEAGE_ERR_ARGS;
    *out_bytes = NULL;
    *out_size = 0;
    if (out_added)
        *out_added = 0;
    if (out_skipped)
        *out_skipped = 0;
    if (!MapGenTraining_NumAccepted(training))
        return MAPGEN_LINEAGE_ERR_NO_SOURCES;

    /*
     * How many of the offered sources the parent already knew. The caller
     * needs this to tell "you added nothing new" from "nothing happened",
     * which are very different things to report.
     */
    size_t parent_sources = 0;
    const uint8_t *parent_text =
        MapGenSnapshot_Chunk(parent, MAPGEN_CHUNK_SOURCES, &parent_sources);
    uint32_t added = 0, skipped = 0;
    for (uint32_t i = 0; i < MapGenTraining_NumSources(training); i++) {
        mapgen_training_source_t src;
        if (!MapGenTraining_SourceAt(training, i, &src))
            continue;
        if (src.status != MAPGEN_SOURCE_ACCEPTED)
            continue;
        char hex[MAPGEN_SHA256_HEX];
        MapGenDigest_Sha256Hex(src.sha256, hex);
        bool known = false;
        if (parent_text && parent_sources >= 64) {
            for (size_t k = 0; k + 64 <= parent_sources && !known; k++)
                known = !memcmp(parent_text + k, hex, 64);
        }
        if (known)
            skipped++;
        else
            added++;
    }
    if (out_added)
        *out_added = added;
    if (out_skipped)
        *out_skipped = skipped;

    return derive(parent, training, revision, created_utc_ms, compression,
                  out_bytes, out_size);
}

mapgen_lineage_result_t MapGenLineage_Rebuild(
    const mapgen_snapshot_t *parent,
    const mapgen_training_t *rebuilt,
    const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
    uint64_t created_utc_ms,
    mapgen_compression_t compression,
    uint8_t **out_bytes, size_t *out_size)
{
    if (!parent || !rebuilt || !revision || !out_bytes || !out_size)
        return MAPGEN_LINEAGE_ERR_ARGS;
    *out_bytes = NULL;
    *out_size = 0;
    if (!MapGenTraining_NumAccepted(rebuilt))
        return MAPGEN_LINEAGE_ERR_NO_SOURCES;
    return derive(parent, rebuilt, revision, created_utc_ms, compression,
                  out_bytes, out_size);
}

/* ------------------------------------------------------------------------ */

mapgen_lineage_result_t MapGenLineage_Rename(
    const mapgen_snapshot_t *parent,
    const char *title,
    const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
    uint64_t created_utc_ms,
    mapgen_compression_t compression,
    uint8_t **out_bytes, size_t *out_size)
{
    if (!parent || !title || !revision || !out_bytes || !out_size)
        return MAPGEN_LINEAGE_ERR_ARGS;
    *out_bytes = NULL;
    *out_size = 0;

    const size_t length = strlen(title);
    if (!length || length >= MAPGEN_LINEAGE_TITLE_BYTES)
        return MAPGEN_LINEAGE_ERR_TITLE_INVALID;
    for (const unsigned char *p = (const unsigned char *)title; *p; p++)
        if (*p < 0x20 || *p == 0x7F)
            return MAPGEN_LINEAGE_ERR_TITLE_INVALID;

    const mapgen_snapshot_header_t *h = MapGenSnapshot_Header(parent);
    if (!h)
        return MAPGEN_LINEAGE_ERR_PARENT_INVALID;
    if (!memcmp(h->revision_uuid, revision, MAPGEN_SNAPSHOT_UUID_BYTES))
        return MAPGEN_LINEAGE_ERR_SAME_REVISION;

    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
    if (!b)
        return MAPGEN_LINEAGE_ERR_MEMORY;

    for (uint32_t type = MAPGEN_CHUNK_META; type <= MAPGEN_CHUNK_GEOMETRY; type++) {
        size_t size = 0;
        const uint8_t *data = MapGenSnapshot_Chunk(parent, type, &size);
        if (!data) {
            MapGenSnapshot_BuilderFree(b);
            return MAPGEN_LINEAGE_ERR_PARENT_INVALID;
        }

        if (type != MAPGEN_CHUNK_META) {
            /* Copied through untouched. A rename must not be able to change
               what was learned, and the guard compares these chunk by chunk. */
            if (MapGenSnapshot_AddChunk(b, type, data, size, compression)
                != MAPGEN_SNAPSHOT_OK) {
                MapGenSnapshot_BuilderFree(b);
                return MAPGEN_LINEAGE_ERR_MEMORY;
            }
            continue;
        }

        /* META keeps every line it had except the title, which is replaced.
           A slug line is left alone: contract 8 says the creation slug stays
           a filesystem label and need not follow a later display title. */
        char *rebuilt = malloc(size + MAPGEN_LINEAGE_TITLE_BYTES + 16);
        if (!rebuilt) {
            MapGenSnapshot_BuilderFree(b);
            return MAPGEN_LINEAGE_ERR_MEMORY;
        }
        size_t out = 0;
        size_t line = 0;
        while (line < size) {
            size_t end = line;
            while (end < size && data[end] != '\n')
                end++;
            const bool is_title = (end - line) >= 6 && !memcmp(data + line, "title=", 6);
            if (!is_title) {
                memcpy(rebuilt + out, data + line, end - line + (end < size ? 1 : 0));
                out += end - line + (end < size ? 1 : 0);
            }
            line = end + 1;
        }
        out += (size_t)snprintf(rebuilt + out, MAPGEN_LINEAGE_TITLE_BYTES + 8,
                                "title=%s\n", title);

        const mapgen_snapshot_result_t ar =
            MapGenSnapshot_AddChunk(b, type, rebuilt, out, compression);
        free(rebuilt);
        if (ar != MAPGEN_SNAPSHOT_OK) {
            MapGenSnapshot_BuilderFree(b);
            return MAPGEN_LINEAGE_ERR_MEMORY;
        }
    }

    MapGenSnapshot_SetIdentity(b, h->lineage_uuid, revision, h->payload_sha256);
    MapGenSnapshot_SetProvenance(b, NULL, NULL, created_utc_ms, h->source_count);
    return finish(b, out_bytes, out_size);
}
