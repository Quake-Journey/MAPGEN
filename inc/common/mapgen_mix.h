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

MAPGEN-1 - MapGenMix: several snapshots, one immutable model

Contract section 9.

--- A snapshot is pinned, not named ------------------------------------------

Each selection carries `revision_uuid + payload_sha256`, and both are checked
against the file that was opened. A snapshot that does not match the pin is
refused rather than substituted, because "the snapshot I trained on" and "a
snapshot with the same name" are different things and only one of them
reproduces a result.

--- Duplicates across snapshots ----------------------------------------------

Two snapshots trained on overlapping corpora share source hashes. By default a
source counts ONCE however many snapshots carry it: a map that appears in three
selected snapshots is not three times as normal. Contract 9 allows the user to
enable repeated influence explicitly, and that is a flag on the request rather
than a default, because the default should be the one that does not quietly
distort what the user asked for.

--- What mixing may not do --------------------------------------------------

It does not mutate a snapshot - it cannot; every input is `const` and this
module has no way to write a file. It does not invent a material: the allowlist
is the exact union of what the selected snapshots carry, per contract 15's
provenance rule. And it refuses outright when a selection's physics or schema
hash disagrees with the rest, because a model mixed across incompatible
physics is not a model of anything.

==============================================================================
*/

#pragma once

#include "common/mapgen_random.h"
#include "common/mapgen_snapshot.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_MIX_MIN_WEIGHT   1u
#define MAPGEN_MIX_MAX_WEIGHT   100u
#define MAPGEN_MIX_MAX_INPUTS   32u

typedef enum {
    MAPGEN_MIX_OK = 0,
    MAPGEN_MIX_ERR_ARGS,
    MAPGEN_MIX_ERR_MEMORY,
    MAPGEN_MIX_ERR_NO_INPUTS,
    MAPGEN_MIX_ERR_TOO_MANY_INPUTS,
    MAPGEN_MIX_ERR_BAD_WEIGHT,
    /* The opened snapshot is not the revision that was pinned. */
    MAPGEN_MIX_ERR_PIN_MISMATCH,
    /* Contract 9: incompatible physics/schema shows `Needs Rebuild`. */
    MAPGEN_MIX_ERR_NEEDS_REBUILD,
    MAPGEN_MIX_ERR_DUPLICATE_REVISION,
} mapgen_mix_result_t;

const char *MapGenMix_ResultName(mapgen_mix_result_t r);

/*
 * One selected revision. The pin is the caller's record of what it meant to
 * select; the snapshot is what was actually opened, and the two are compared.
 */
typedef struct {
    const mapgen_snapshot_t *snapshot;
    uint8_t  revision_uuid[MAPGEN_SNAPSHOT_UUID_BYTES];
    uint8_t  payload_sha256[MAPGEN_SHA256_BYTES];
    uint32_t weight;                    /* 1..100; equal weights by default */
} mapgen_mix_input_t;

typedef struct {
    /* Repeated influence for a source several snapshots share. Contract 9
       makes this an explicit Advanced setting, so it is a flag the caller must
       set rather than a default. */
    bool allow_repeated_influence;

    /*
     * The target manifest: every `<dir>/<name>` that really resolves as a
     * texture in the frozen target view.
     *
     * Contract 15 forbids emitting a material the target does not have, and
     * the pinned compiler only WARNS about one it cannot find - so a map can
     * compile cleanly and be textured with nothing at all. That is not
     * hypothetical: the first map this chain produced was 556 brushes of
     * textures under `rcdm17`, which the corpus taught and baseq2 cannot
     * resolve.
     *
     * A material outside this list is not in the allowlist. Leaving it NULL
     * builds a model that records having no manifest, and the brush stage
     * refuses to texture from one.
     */
    const char *const *available;
    uint32_t           num_available;
} mapgen_mix_options_t;

typedef struct mapgen_mix_s mapgen_mix_t;

/*
 * Build the mixed model. Every input is read and none is retained; the result
 * owns its own copy of everything it reports.
 */
mapgen_mix_result_t MapGenMix_Build(const mapgen_mix_input_t *inputs,
                                    uint32_t count,
                                    const mapgen_mix_options_t *options,
                                    mapgen_mix_t **out);
void MapGenMix_Free(mapgen_mix_t *mix);

uint32_t MapGenMix_NumInputs(const mapgen_mix_t *mix);
uint32_t MapGenMix_NumMaterials(const mapgen_mix_t *mix);
/* Distinct source hashes across the whole selection. */
uint32_t MapGenMix_NumSources(const mapgen_mix_t *mix);
/* Sources that more than one selected snapshot carries. */
uint32_t MapGenMix_NumSharedSources(const mapgen_mix_t *mix);

/* Whether the model was built against a target manifest at all. */
bool MapGenMix_HasTargetManifest(const mapgen_mix_t *mix);
/*
 * Materials the corpus taught that the target cannot resolve - counted once
 * each, and nameable. A report that says "seven of your textures are not in
 * baseq2" is worth something only if seven means seven textures, and it is
 * worth much more if it can say which.
 */
uint32_t MapGenMix_NumUnavailableMaterials(const mapgen_mix_t *mix);
const char *MapGenMix_UnavailableMaterial(const mapgen_mix_t *mix,
                                          uint32_t index);

/*
 * How many source contributions the model is built on.
 *
 * This is where `allow_repeated_influence` actually lands. By default a source
 * several snapshots share contributes ONCE, so this equals the distinct count;
 * with repeated influence enabled it counts once per snapshot carrying it, and
 * the two differ by exactly the shared appearances. A flag that changed only a
 * displayed number would not be the setting contract 9 describes.
 */
uint32_t MapGenMix_EffectiveSourceCount(const mapgen_mix_t *mix);

/* Whether repeated influence was enabled for this model. */
bool MapGenMix_RepeatedInfluence(const mapgen_mix_t *mix);

/*
 * A material's sampling probability, in parts per million of the whole
 * allowlist. Weight-normalized across the snapshots that carry it, so a
 * material in a heavily weighted snapshot is sampled more often without ever
 * leaving the exact union.
 */
uint32_t MapGenMix_MaterialProbabilityPpm(const mapgen_mix_t *mix, uint32_t index);
const char *MapGenMix_MaterialName(const mapgen_mix_t *mix, uint32_t index);

/*
 * What the corpus used this material AS - the MAPGEN_ROLE_* bits from
 * mapgen_genome.h - and the Quake II contents flags it carried.
 *
 * The union across every snapshot that has it, because a texture used as a
 * light in one map and as plain wall in another is both, and keeping only one
 * would drop a fact the corpus contains. Picking a floor texture rather than
 * a sky one is a question about this and about nothing else: contract 15
 * forbids classifying a material from its filename.
 */
uint32_t MapGenMix_MaterialRoles(const mapgen_mix_t *mix, uint32_t index);
int32_t  MapGenMix_MaterialContents(const mapgen_mix_t *mix, uint32_t index);
int32_t  MapGenMix_MaterialSurfaceFlags(const mapgen_mix_t *mix, uint32_t index);
/*
 * How bright the corpus used this material as a light, or 0 if it never did.
 *
 * The brightest across every snapshot that has it, for the same reason the
 * roles are a union: a fitting used at 10000 in one map is a fitting capable
 * of 10000.
 */
int32_t  MapGenMix_MaterialLightValue(const mapgen_mix_t *mix, uint32_t index);

/*
 * --- architecture donors ----------------------------------------------------
 *
 * A donor is a source whose BLUEPRINT the selection carries, so a Recipe can
 * ask for its architecture to be preserved. Deduplicated by exact source hash,
 * never by title: one map two selected snapshots both learned from is ONE
 * donor whose influence is the sum of theirs.
 *
 * A source whose space could not be analysed has no blueprint and is therefore
 * not a donor, however much of its material the selection uses. Contributing a
 * texture is not contributing an architecture.
 */
uint32_t    MapGenMix_NumDonors(const mapgen_mix_t *mix);
const char *MapGenMix_DonorHex(const mapgen_mix_t *mix, uint32_t index);
uint32_t    MapGenMix_DonorWeightPpm(const mapgen_mix_t *mix, uint32_t index);
/* The donor's canonical blueprint text - its architecture, verbatim. */
const char *MapGenMix_DonorBlueprint(const mapgen_mix_t *mix, uint32_t index);

/* The normalized weight of one input, in parts per million. */
uint32_t MapGenMix_WeightPpm(const mapgen_mix_t *mix, uint32_t input);

/*
 * --- what the generator is actually going to sample ------------------------
 *
 * A learned map, with the weight of the selection it came from. The model
 * keeps the SAMPLES and not a summary, because contract 19 says the report
 * may state measured evidence and nothing more: a mean of two corpora is a
 * number no map in either corpus ever had, and a generator that sized itself
 * from one would be inventing a target and calling it learned.
 *
 * A source several snapshots share is ONE sample carrying the sum of their
 * weights, on exactly the rule the material table already follows. With
 * repeated influence it is one sample per snapshot instead - otherwise the
 * setting would be honoured for the source list and quietly ignored for the
 * numbers that decide what the map looks like.
 */
typedef enum {
    MAPGEN_MIX_STAT_NODES = 0,
    MAPGEN_MIX_STAT_REGIONS,
    MAPGEN_MIX_STAT_LARGEST_REGION_PERMILLE,
    MAPGEN_MIX_STAT_HEIGHT_BANDS,
    MAPGEN_MIX_STAT_VERTICAL_SPAN,
    MAPGEN_MIX_STAT_OPEN_PERMILLE,
    /* Contract 7.7's lighting evidence: how many lights the map had, and the
       intensity they ran at. */
    MAPGEN_MIX_STAT_LIGHTS,
    MAPGEN_MIX_STAT_LIGHT_MEDIAN,
    /* And the spread they were drawn across, as quartiles. */
    MAPGEN_MIX_STAT_LIGHT_LOWER,
    MAPGEN_MIX_STAT_LIGHT_UPPER,
    /*
     * The four commonest colours those lights were given, packed 0xRRGGBB and
     * 0 where the map had no fourth. A map lit in one tint everywhere is the
     * same mistake as a map lit at one intensity everywhere.
     */
    MAPGEN_MIX_STAT_LIGHT_COLOUR_0,
    MAPGEN_MIX_STAT_LIGHT_COLOUR_1,
    MAPGEN_MIX_STAT_LIGHT_COLOUR_2,
    MAPGEN_MIX_STAT_LIGHT_COLOUR_3,
    /* How much of the map's surface is open sky, per thousand sides. */
    MAPGEN_MIX_STAT_SKY_PERMILLE,

    MAPGEN_MIX_STAT_COUNT
} mapgen_mix_stat_t;

const char *MapGenMix_StatName(mapgen_mix_stat_t stat);

uint32_t MapGenMix_NumSamples(const mapgen_mix_t *mix);
int64_t  MapGenMix_SampleValue(const mapgen_mix_t *mix, uint32_t index,
                               mapgen_mix_stat_t stat);
uint32_t MapGenMix_SampleWeightPpm(const mapgen_mix_t *mix, uint32_t index);
/* The source hash the sample came from, as 64 lower-case hex characters. */
const char *MapGenMix_SampleSource(const mapgen_mix_t *mix, uint32_t index);

/*
 * Whether the selection learned a given entity role at all - the role bits are
 * MAPGEN_ROLE_* from mapgen_wiring.h.
 *
 * PRESENCE, and deliberately not a count. The snapshots aggregate their entity
 * totals before writing them, so a map two selected snapshots share is counted
 * twice with no way to subtract it back out, and a count that is wrong in a
 * way nobody can correct is worse than no count. Presence is exact whatever
 * the duplication, and presence is the question contract 15 actually asks:
 * "Teleporters High but no compatible teleporter motif" is about existence.
 *
 * A count could be had later by making the ENTITIES chunk per-source the way
 * REGIONS is; nothing needs one yet.
 */
bool MapGenMix_RoleIsLearned(const mapgen_mix_t *mix, uint32_t role_bit);

/*
 * Whether any material in the ALLOWLIST carries a material role - the
 * MAPGEN_ROLE_ bits of mapgen_genome.h, not the entity roles above.
 *
 * Answered from the allowlist rather than from a summary bit, because a
 * corpus that had lava and a game directory that resolves none of its lava
 * textures are the same thing to every later stage: nothing to draw.
 */
bool MapGenMix_MaterialRoleIsLearned(const mapgen_mix_t *m, uint32_t role_bit);

/*
 * Draw one learned map in proportion to weight. Returns NumSamples() when
 * there is nothing to draw from - a value the caller cannot mistake for
 * sample zero.
 */
uint32_t MapGenMix_DrawSample(const mapgen_mix_t *mix, mapgen_random_t *r);

/* Canonical rendering and digest, on the same rules as everything else. */
size_t   MapGenMix_CanonicalText(const mapgen_mix_t *mix, char *out, size_t capacity);
uint64_t MapGenMix_CanonicalDigest(const mapgen_mix_t *mix);
