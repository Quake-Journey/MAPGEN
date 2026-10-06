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

MAPGEN-1 - MapGenRecipe: one immutable request, and what it resolved to

Contract section 10.

--- Why a recipe and not three hundred cvars --------------------------------

The UI has more than a hundred item and architecture controls. Persisting them
as cvars would make "the settings that produced this map" mean "whatever the
settings happen to be now", and `Generate Again` would be a different request
wearing the same name. A recipe is built once, is immutable from then on, and
is stored beside the map it produced.

--- Requested and resolved are both kept ------------------------------------

Every control has an `Auto` that the generator resolves against the goal, the
player envelope, the map scale and the mixed snapshot model. Both halves are
stored: the requested value says what the user asked for, and the resolved
value is what actually ran. Contract 10 is explicit that `Generate Again` uses
the RESOLVED values - it "never silently recalculates an old Auto choice under
a newer engine", because that would produce a different map from the same
button and call it the same recipe.

An explicit `Custom 0` is not an absence. Contract 13 makes it a hard
constraint, so it is stored as the number zero and is never confused with
`Auto`, which is why `Auto` has a sentinel of its own rather than being spelled
"unset".

--- What a reuse must check first -------------------------------------------

A recipe pins the generator version, the compiler build hash, the entity schema
and the physics profile. Before an unchanged rerun those four are compared with
what is installed. A component that is MISSING makes the recipe unrunnable and
reports `UNAVAILABLE_VERSION`; a component that is present but different
reports `NEEDS_MIGRATION`. Neither runs anyway. Migration is explicit and
copy-on-write: it produces a NEW recipe with new provenance, and this module
has no way to edit one in place.

--- The file ----------------------------------------------------------------

`.q2mgrec` is versioned, length-bounded and checksummed, on the same rules the
snapshot container follows: every count is checked against the bytes that are
actually there before anything is allocated, and a file whose checksum does not
describe its own contents is refused rather than repaired.

==============================================================================
*/

#pragma once

#include "common/mapgen_digest.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_RECIPE_MAGIC          "Q2MGREC\0"
#define MAPGEN_RECIPE_MAGIC_BYTES    8
#define MAPGEN_RECIPE_SCHEMA_MAJOR   1
/* 1: the donor. A fork's record has to be able to name what it forked. */
#define MAPGEN_RECIPE_SCHEMA_MINOR   1
/* 320 + 64 for the donor's name + 32 for the digest of the BSP that was
   read. The reader demands this number exactly, so it changed exactly
   once - before the first recipe file in the world existed. */
#define MAPGEN_RECIPE_HEADER_BYTES   416
#define MAPGEN_RECIPE_SNAPSHOT_BYTES 52
#define MAPGEN_RECIPE_CONTROL_BYTES  48
#define MAPGEN_RECIPE_UUID_BYTES     16

/* Ceilings, all checked against the bytes present before anything is
   allocated on a file's word. */
#define MAPGEN_RECIPE_MAX_FILE_BYTES  (4u * 1024u * 1024u)
#define MAPGEN_RECIPE_MAX_SNAPSHOTS   32u
#define MAPGEN_RECIPE_MAX_CONTROLS    512u

#define MAPGEN_RECIPE_NAME_BYTES      64
#define MAPGEN_RECIPE_SLUG_BYTES      32
#define MAPGEN_RECIPE_KEY_BYTES       40

/* Contract 16's Advanced range for candidate attempts. */
#define MAPGEN_RECIPE_MIN_ATTEMPTS    1u
#define MAPGEN_RECIPE_MAX_ATTEMPTS    256u

/*
 * `Auto`: the user did not choose, and the generator will. It is a sentinel
 * rather than a flag because contract 13's `Custom 0` is a real value, and the
 * one mistake this type exists to prevent is treating "none" as "unset".
 */
#define MAPGEN_RECIPE_AUTO            INT32_MIN

typedef enum {
    MAPGEN_GEN_AUTO        = 1,
    MAPGEN_GEN_FULL_RANDOM = 2,
} mapgen_gen_type_t;

typedef enum {
    MAPGEN_GOAL_MIX           = 1,
    MAPGEN_GOAL_DUEL          = 2,
    MAPGEN_GOAL_TDM           = 3,
    MAPGEN_GOAL_FFA           = 4,
    MAPGEN_GOAL_SINGLE_PLAYER = 5,
} mapgen_goal_t;

const char *MapGenRecipe_TypeName(mapgen_gen_type_t type);
const char *MapGenRecipe_GoalName(mapgen_goal_t goal);

typedef enum {
    MAPGEN_RECIPE_OK = 0,
    MAPGEN_RECIPE_ERR_ARGS,
    MAPGEN_RECIPE_ERR_MEMORY,
    MAPGEN_RECIPE_ERR_TOO_SMALL,
    MAPGEN_RECIPE_ERR_BAD_MAGIC,
    MAPGEN_RECIPE_ERR_UNSUPPORTED_MAJOR,
    MAPGEN_RECIPE_ERR_BAD_HEADER_BYTES,
    MAPGEN_RECIPE_ERR_BAD_FILE_BYTES,
    MAPGEN_RECIPE_ERR_FILE_TOO_LARGE,
    MAPGEN_RECIPE_ERR_RESERVED_NOT_ZERO,
    MAPGEN_RECIPE_ERR_BAD_CRC,
    MAPGEN_RECIPE_ERR_TOO_MANY_SNAPSHOTS,
    MAPGEN_RECIPE_ERR_TOO_MANY_CONTROLS,
    MAPGEN_RECIPE_ERR_TABLE_OUT_OF_BOUNDS,
    MAPGEN_RECIPE_ERR_NO_SNAPSHOTS,
    MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL,
    MAPGEN_RECIPE_ERR_DUPLICATE_SNAPSHOT,
    MAPGEN_RECIPE_ERR_BAD_WEIGHT,
    MAPGEN_RECIPE_ERR_BAD_TYPE,
    MAPGEN_RECIPE_ERR_BAD_GOAL,
    MAPGEN_RECIPE_ERR_BAD_ENVELOPE,
    MAPGEN_RECIPE_ERR_BAD_ATTEMPTS,
    MAPGEN_RECIPE_ERR_BAD_SLUG,
    MAPGEN_RECIPE_ERR_BAD_NAME,
    MAPGEN_RECIPE_ERR_BAD_KEY,
    MAPGEN_RECIPE_ERR_UNRESOLVED,
    /* Neither a snapshot nor a donor: a recipe that describes no input. */
    MAPGEN_RECIPE_ERR_NO_SOURCE,

    MAPGEN_RECIPE_RESULT_COUNT
} mapgen_recipe_result_t;

const char *MapGenRecipe_ResultName(mapgen_recipe_result_t r);

/* One selected snapshot revision and its weight, as contract 9 pins it. */
typedef struct {
    uint8_t  revision_uuid[MAPGEN_RECIPE_UUID_BYTES];
    uint8_t  payload_sha256[MAPGEN_SHA256_BYTES];
    uint32_t weight;
} mapgen_recipe_snapshot_t;

/*
 * One control, in both halves. `requested` is MAPGEN_RECIPE_AUTO or the exact
 * number the user typed; `resolved` is always an exact number, because a
 * recipe that has run has no Auto left in it.
 */
typedef struct {
    char    key[MAPGEN_RECIPE_KEY_BYTES];
    int32_t requested;
    int32_t resolved;
} mapgen_recipe_control_t;

/*
 * The toolchain a recipe was produced by, and the one that would rerun it.
 * All six parts, because five of them agreeing proves nothing.
 */
typedef struct {
    uint32_t generator_version;         /* packed semantic version */
    uint8_t  compiler_build_sha256[MAPGEN_SHA256_BYTES];
    uint32_t entity_schema_version;
    uint8_t  entity_schema_sha256[MAPGEN_SHA256_BYTES];
    uint32_t physics_profile_id;
    uint8_t  physics_profile_sha256[MAPGEN_SHA256_BYTES];
} mapgen_recipe_toolchain_t;

typedef struct mapgen_recipe_s mapgen_recipe_t;

/* --- building ------------------------------------------------------------ */

typedef struct mapgen_recipe_builder_s mapgen_recipe_builder_t;

mapgen_recipe_builder_t *MapGenRecipe_BuilderCreate(void);
void MapGenRecipe_BuilderFree(mapgen_recipe_builder_t *b);

/* Identity is supplied, never invented: this module has no clock and no RNG. */
void MapGenRecipe_SetIdentity(mapgen_recipe_builder_t *b,
                              const uint8_t recipe_uuid[MAPGEN_RECIPE_UUID_BYTES],
                              uint64_t seed);
mapgen_recipe_result_t MapGenRecipe_SetRequest(mapgen_recipe_builder_t *b,
                                               mapgen_gen_type_t type,
                                               mapgen_goal_t goal,
                                               uint32_t players_min,
                                               uint32_t players_max,
                                               uint32_t attempt_limit,
                                               uint32_t quality_policy);
mapgen_recipe_result_t MapGenRecipe_SetOutput(mapgen_recipe_builder_t *b,
                                              const char *display_name,
                                              const char *slug);
void MapGenRecipe_SetMaterialTable(mapgen_recipe_builder_t *b,
                                   const uint8_t sha256[MAPGEN_SHA256_BYTES]);
void MapGenRecipe_SetToolchain(mapgen_recipe_builder_t *b,
                               const mapgen_recipe_toolchain_t *toolchain);

/*
 * The map this one was forked from, and the digest of the BSP that was read.
 *
 * A recipe with a donor and no snapshots is a fork; one with snapshots and no
 * donor is invented from what a corpus taught; one with both is a fork guided
 * by a corpus. One with NEITHER describes no input at all and is refused.
 *
 * The digest is of the donor as it was READ, not of the name: a map file that
 * changed under the same name is a different input, and `Generate Again`
 * would otherwise produce a different map and call it the same recipe.
 */
mapgen_recipe_result_t MapGenRecipe_SetDonor(mapgen_recipe_builder_t *b,
                                             const char *map_name,
                                             const uint8_t sha256[MAPGEN_SHA256_BYTES]);

/* Adding the same revision twice is an error, not a heavier weight. */
mapgen_recipe_result_t MapGenRecipe_AddSnapshot(mapgen_recipe_builder_t *b,
                                                const mapgen_recipe_snapshot_t *snapshot);
/* Adding the same key twice is an error, not a replacement: a control that can
   be silently overwritten is a control whose value depends on call order. */
mapgen_recipe_result_t MapGenRecipe_AddControl(mapgen_recipe_builder_t *b,
                                               const char *key,
                                               int32_t requested,
                                               int32_t resolved);

/* Serialize. The caller owns `*out_bytes` and frees it with `free`. */
mapgen_recipe_result_t MapGenRecipe_Finish(mapgen_recipe_builder_t *b,
                                           uint8_t **out_bytes, size_t *out_size);

/* --- reading ------------------------------------------------------------- */

mapgen_recipe_result_t MapGenRecipe_Open(const uint8_t *bytes, size_t size,
                                         mapgen_recipe_t **out);
void MapGenRecipe_Free(mapgen_recipe_t *recipe);

const uint8_t *MapGenRecipe_Uuid(const mapgen_recipe_t *recipe);
uint64_t       MapGenRecipe_Seed(const mapgen_recipe_t *recipe);
mapgen_gen_type_t MapGenRecipe_Type(const mapgen_recipe_t *recipe);
mapgen_goal_t     MapGenRecipe_Goal(const mapgen_recipe_t *recipe);
uint32_t MapGenRecipe_PlayersMin(const mapgen_recipe_t *recipe);
uint32_t MapGenRecipe_PlayersMax(const mapgen_recipe_t *recipe);
uint32_t MapGenRecipe_AttemptLimit(const mapgen_recipe_t *recipe);
uint32_t MapGenRecipe_QualityPolicy(const mapgen_recipe_t *recipe);
const char *MapGenRecipe_DisplayName(const mapgen_recipe_t *recipe);
const char *MapGenRecipe_Slug(const mapgen_recipe_t *recipe);
/* Empty when this recipe forked nothing. */
const char *MapGenRecipe_Donor(const mapgen_recipe_t *recipe);
const uint8_t *MapGenRecipe_DonorHash(const mapgen_recipe_t *recipe);
const uint8_t *MapGenRecipe_MaterialTableHash(const mapgen_recipe_t *recipe);
const mapgen_recipe_toolchain_t *MapGenRecipe_Toolchain(const mapgen_recipe_t *recipe);

uint32_t MapGenRecipe_NumSnapshots(const mapgen_recipe_t *recipe);
const mapgen_recipe_snapshot_t *MapGenRecipe_SnapshotAt(const mapgen_recipe_t *recipe,
                                                        uint32_t index);
uint32_t MapGenRecipe_NumControls(const mapgen_recipe_t *recipe);
const mapgen_recipe_control_t *MapGenRecipe_ControlAt(const mapgen_recipe_t *recipe,
                                                      uint32_t index);
const mapgen_recipe_control_t *MapGenRecipe_Control(const mapgen_recipe_t *recipe,
                                                    const char *key);

/*
 * What the generator reads. It gets the RESOLVED value and nothing else: a
 * generator that could see `requested` could re-resolve an old Auto, which is
 * exactly what contract 10 forbids. `fallback` is returned when the recipe has
 * no such control at all.
 */
int32_t MapGenRecipe_ResolvedValue(const mapgen_recipe_t *recipe,
                                   const char *key, int32_t fallback);

/* --- reuse --------------------------------------------------------------- */

typedef enum {
    MAPGEN_REUSE_OK = 0,
    /* Present, but not the same: an explicit migration can carry it forward. */
    MAPGEN_REUSE_NEEDS_MIGRATION,
    /* Absent: there is nothing to run it with. */
    MAPGEN_REUSE_UNAVAILABLE_VERSION,
} mapgen_recipe_reuse_t;

const char *MapGenRecipe_ReuseName(mapgen_recipe_reuse_t r);

/*
 * Compare the recipe's pinned toolchain with what is installed. `installed`
 * being NULL is `UNAVAILABLE_VERSION`, and so is any component that is present
 * but empty - an all-zero hash is what "we could not read it" looks like, and
 * treating that as a match would be the whole check quietly disarmed.
 *
 * `which` receives the name of the first disagreeing component, so the UI can
 * say what stopped it rather than that something did.
 */
mapgen_recipe_reuse_t MapGenRecipe_CheckReuse(const mapgen_recipe_t *recipe,
                                              const mapgen_recipe_toolchain_t *installed,
                                              const char **which);

/* --- canonical form ------------------------------------------------------ */

size_t   MapGenRecipe_CanonicalText(const mapgen_recipe_t *recipe, char *out,
                                    size_t capacity);
uint64_t MapGenRecipe_CanonicalDigest(const mapgen_recipe_t *recipe);
