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

MAPGEN-1 - MapGenTraining: aggregating maps into a snapshot's chunks

Contract sections 7 (what Training learns) and 8 (the chunks it fills).

--- Per-source contributions are kept, not just the total -------------------

Contract 7 requires per-source contributions alongside the aggregate, so that
Extend and Rebuild remain possible and so a source can be deduplicated. That
means this is not a running sum: every source's own numbers survive into the
snapshot, and the aggregate is derived from them rather than the other way
round.

It also means a snapshot can answer "which map taught you that?", which is the
difference between a model you can audit and one you cannot.

--- Order is canonical, never arrival order ---------------------------------

Contract 8: sources are aggregated and serialized in
`(SHA-256, provider identity, qpath)` order, independent of worker completion.
Eight workers finishing in eight different orders must produce one byte-identical
payload, so nothing here may depend on when a map arrived.

--- Duplicates ---------------------------------------------------------------

Two qpaths with the same SHA-256 are the same map. The second is recorded as a
DUPLICATE and contributes nothing, because counting one map twice would teach
the generator that whatever it happens to contain is twice as normal. Five such
pairs exist in the shipped corpus - `aerowalk`/`q2duel1` among them - so this
is not a hypothetical.

==============================================================================
*/

#pragma once

#include "common/mapgen_blueprint.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_demo.h"
#include "common/mapgen_features.h"
#include "common/mapgen_snapshot.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_TRAINING_QPATH_BYTES     128
#define MAPGEN_TRAINING_PROVIDER_BYTES  64
#define MAPGEN_TRAINING_MAX_SOURCES     MAPGEN_SNAPSHOT_MAX_SOURCES
/* Beyond this a single snapshot's material allowlist stops being a list and
   starts being a liability; contract 15 wants it exact and auditable. */
#define MAPGEN_TRAINING_MAX_MATERIALS   65536u

/* A snapshot built from fewer than this many distinct sources gets a visible
   low-diversity warning. Contract 7: "a one-map snapshot is legal but receives
   a visible low-diversity warning". */
#define MAPGEN_TRAINING_LOW_DIVERSITY   4u

typedef enum {
    MAPGEN_SOURCE_ACCEPTED = 0,
    MAPGEN_SOURCE_DUPLICATE,      /* same SHA-256 as one already accepted */
    MAPGEN_SOURCE_REJECTED,       /* the caller could not analyse it       */
} mapgen_source_status_t;

const char *MapGenTraining_SourceStatusName(mapgen_source_status_t s);

typedef enum {
    MAPGEN_TRAINING_OK = 0,
    MAPGEN_TRAINING_ERR_ARGS,
    MAPGEN_TRAINING_ERR_MEMORY,
    MAPGEN_TRAINING_ERR_TOO_MANY_SOURCES,
    MAPGEN_TRAINING_ERR_TOO_MANY_MATERIALS,
    MAPGEN_TRAINING_ERR_NO_SOURCES,
} mapgen_training_result_t;

const char *MapGenTraining_ResultName(mapgen_training_result_t r);

typedef struct {
    char     qpath[MAPGEN_TRAINING_QPATH_BYTES];
    char     provider[MAPGEN_TRAINING_PROVIDER_BYTES];
    uint64_t bytes;
    uint8_t  sha256[MAPGEN_SHA256_BYTES];
    uint32_t status;
} mapgen_training_source_t;

typedef struct mapgen_training_s mapgen_training_t;

mapgen_training_t *MapGenTraining_Create(void);
void MapGenTraining_Free(mapgen_training_t *t);

/*
 * Contribute one analysed map.
 *
 * `features`, `genome` and `wiring` are read and copied from; none is retained.
 * A source whose SHA-256 matches one already accepted is recorded as a
 * DUPLICATE and contributes nothing to the aggregate - and that is reported
 * rather than silently done.
 */
/*
 * The donor's canonical geometry, handed in beside the blueprint.
 *
 * A caller that has none may pass NULL and the source is recorded without one,
 * but a snapshot built from such sources cannot serve any fidelity above zero:
 * the geometry is what a candidate begins as, and there is nothing to begin
 * from. Training does not invent it and does not pretend otherwise.
 */
mapgen_training_result_t MapGenTraining_AddSource(
    mapgen_training_t *t,
    const char *qpath, const char *provider, uint64_t bytes,
    const uint8_t sha256[MAPGEN_SHA256_BYTES],
    const mapgen_features_t *features,
    const mapgen_genome_t *genome,
    const mapgen_wiring_t *wiring,
    /*
     * The source's ARCHITECTURE. Without it a snapshot carries counts and
     * shares and no shape, and no fidelity control can preserve what was never
     * learned. May be NULL only for a source whose space could not be built;
     * such a source can never be an architecture donor.
     */
    const mapgen_blueprint_t *blueprint,
    /*
     * And the donor's own GEOMETRY - its convex solids, their mapping, its
     * submodels and the entities bound to them. The blueprint above says where
     * the rooms are; this is what they are built from, and it is what a
     * candidate above fidelity zero begins as. NULL is permitted and means the
     * source can never be an architecture donor at any fidelity above zero.
     */
    const mapgen_geometry_t *geometry);

/*
 * What a demo of one of those sources saw.
 *
 * `source_sha256` is the map the demo was recorded on, by the same identity
 * the source was added under - evidence for a source nobody added is refused,
 * because filing it under nothing is how a corpus comes to contain movement
 * that belongs to a map it does not have.
 *
 * `physics_sha256` is the movement rules it was read under. A trace of where a
 * player could go is a statement about those rules, and two builds that
 * disagree about them disagree about the trace.
 */
mapgen_training_result_t MapGenTraining_AddMovement(
    mapgen_training_t *t,
    const uint8_t source_sha256[MAPGEN_SHA256_BYTES],
    const char *physics_sha256,
    const mapgen_demo_provenance_t *provenance,
    uint32_t cells, uint32_t jumps, uint32_t drops, uint32_t rides,
    uint32_t swims);

uint32_t MapGenTraining_NumMovement(const mapgen_training_t *t);

/* A source the caller could not analyse. It is still recorded, because "this
   map was offered and could not be used" is part of the provenance. */
mapgen_training_result_t MapGenTraining_RejectSource(
    mapgen_training_t *t,
    const char *qpath, const char *provider, uint64_t bytes,
    const uint8_t sha256[MAPGEN_SHA256_BYTES]);

uint32_t MapGenTraining_NumSources(const mapgen_training_t *t);
uint32_t MapGenTraining_NumAccepted(const mapgen_training_t *t);
uint32_t MapGenTraining_NumDuplicates(const mapgen_training_t *t);
uint32_t MapGenTraining_NumRejected(const mapgen_training_t *t);
uint32_t MapGenTraining_NumMaterials(const mapgen_training_t *t);
bool     MapGenTraining_LowDiversity(const mapgen_training_t *t);

/*
 * One source, in canonical order - which is the order it will be serialized
 * in, not the order it arrived.
 *
 * The result is written into caller-owned storage rather than returned as a
 * pointer, because the only ways to return a pointer here are to keep a
 * mutable cache or a per-thread scratch buffer, and this module is not allowed
 * either. Walking every source is O(n^2 log n); for a corpus of a few hundred
 * maps that is nothing, and Training is not an inner loop.
 */
bool MapGenTraining_SourceAt(const mapgen_training_t *t, uint32_t index,
                             mapgen_training_source_t *out);

/*
 * Render one chunk's canonical payload. Same convention as everywhere else in
 * MAPGEN: pass NULL to measure, then a buffer to fill.
 */
size_t MapGenTraining_ChunkText(const mapgen_training_t *t, uint32_t chunk_type,
                                char *out, size_t capacity);

/*
 * Fill every required chunk of a snapshot builder.
 *
 * Fails on an empty corpus: a snapshot that learned from nothing is not a
 * snapshot, and writing one would only move the failure somewhere later and
 * less obvious.
 */
mapgen_training_result_t MapGenTraining_FillSnapshot(const mapgen_training_t *t,
                                                     mapgen_snapshot_builder_t *b,
                                                     mapgen_compression_t compression);
