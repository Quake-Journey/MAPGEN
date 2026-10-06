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

MAPGEN-1 - MapGenLineage: New, Extend, Rebuild and Rename

Contract section 7's Training modes and section 8's copy-on-write rule.

--- Nothing here ever modifies an existing snapshot ---------------------------

Every operation produces a NEW image. The parent's bytes are read and never
written, which the guard checks by hashing the parent file before and after.
Contract 7 says it plainly - "Extend/Rebuild never mutates or overwrites an
existing payload" - and contract 8 adds that a display-title Rename is
copy-on-write too, so the old `.q2mgdb` stays byte-identical.

  New       a fresh lineage and a fresh revision. No parent
  Extend    the same lineage, sources added, exact duplicates skipped
  Rebuild   the same lineage, the recorded sources re-analysed
  Rename    the same lineage, the same payload, a new title

Every one of them records the parent's payload hash, so a revision can always
say what it came from.

--- Identity is supplied, not invented ----------------------------------------

The caller passes the new revision UUID. This module has no clock, no RNG and
no global state, which is what makes an Extend of the same parent with the same
sources reproducible - and testable at all. Generating identity here would make
every result unrepeatable by construction, and the one thing a snapshot must be
able to do is prove it is the same as another.

==============================================================================
*/

#pragma once

#include "common/mapgen_training.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_LINEAGE_TITLE_BYTES  256

typedef enum {
    MAPGEN_LINEAGE_OK = 0,
    MAPGEN_LINEAGE_ERR_ARGS,
    MAPGEN_LINEAGE_ERR_MEMORY,
    MAPGEN_LINEAGE_ERR_PARENT_INVALID,
    /* The new revision must not claim the identity it descends from. */
    MAPGEN_LINEAGE_ERR_SAME_REVISION,
    MAPGEN_LINEAGE_ERR_NO_SOURCES,
    MAPGEN_LINEAGE_ERR_TITLE_INVALID,
} mapgen_lineage_result_t;

const char *MapGenLineage_ResultName(mapgen_lineage_result_t r);

/*
 * A fresh lineage. `lineage` and `revision` are the caller's; they must differ
 * from each other only in the sense that both are freshly minted.
 */
mapgen_lineage_result_t MapGenLineage_New(
    const mapgen_training_t *training,
    const uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES],
    const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
    uint64_t created_utc_ms,
    mapgen_compression_t compression,
    uint8_t **out_bytes, size_t *out_size);

/*
 * A new revision of an existing lineage, carrying the parent's sources plus
 * whatever `training` adds. A source already present by SHA-256 is skipped,
 * and how many were skipped is reported through `out_added` so the caller can
 * tell "nothing new" from "nothing happened".
 */
mapgen_lineage_result_t MapGenLineage_Extend(
    const mapgen_snapshot_t *parent,
    const mapgen_training_t *training,
    const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
    uint64_t created_utc_ms,
    mapgen_compression_t compression,
    uint8_t **out_bytes, size_t *out_size,
    uint32_t *out_added, uint32_t *out_skipped);

/*
 * A new revision built from a re-analysis of the parent's recorded sources.
 * The caller does the re-analysis - this module has no BSP reader - and passes
 * the result; what is enforced here is that the lineage, the parent link and
 * the immutability of the parent are all correct.
 */
mapgen_lineage_result_t MapGenLineage_Rebuild(
    const mapgen_snapshot_t *parent,
    const mapgen_training_t *rebuilt,
    const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
    uint64_t created_utc_ms,
    mapgen_compression_t compression,
    uint8_t **out_bytes, size_t *out_size);

/*
 * A metadata-only new revision: the same learned payload under a new display
 * title. Everything except META is copied through unchanged, which the guard
 * verifies chunk by chunk.
 */
mapgen_lineage_result_t MapGenLineage_Rename(
    const mapgen_snapshot_t *parent,
    const char *title,
    const uint8_t revision[MAPGEN_SNAPSHOT_UUID_BYTES],
    uint64_t created_utc_ms,
    mapgen_compression_t compression,
    uint8_t **out_bytes, size_t *out_size);

/*
 * The display title a snapshot carries, read out of its META chunk. False when
 * there is none. The buffer is always NUL-terminated.
 */
bool MapGenLineage_Title(const mapgen_snapshot_t *snap,
                         char out[MAPGEN_LINEAGE_TITLE_BYTES]);

/*
 * A filesystem-safe slug for a title. Contract 8: "Russian names never become
 * unsafe filesystem syntax", and the creation slug stays a filesystem label
 * that need not change when a later revision gets a new display title.
 */
size_t MapGenLineage_Slug(const char *title, char *out, size_t capacity);
