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
 * MAPGEN-1 - the recipe file.
 *
 * Everything a file claims about itself is checked against the bytes that are
 * actually there before any of it is believed, in this order: size, magic,
 * schema, header size, declared file size, the reserved bytes, the checksum,
 * and only then the table counts. A file that fails any of them is refused;
 * none of them is repaired.
 */

#include "common/mapgen_recipe.h"

#include <stdlib.h>
#include <string.h>

/* ---- the layout, written down once -------------------------------------- */

#define OFF_MAGIC            0
#define OFF_SCHEMA_MAJOR     8
#define OFF_SCHEMA_MINOR    10
#define OFF_HEADER_BYTES    12
#define OFF_RESERVED        14
#define OFF_FILE_BYTES      16
#define OFF_UUID            24
#define OFF_SEED            40
#define OFF_TYPE            48
#define OFF_GOAL            52
#define OFF_PLAYERS_MIN     56
#define OFF_PLAYERS_MAX     60
#define OFF_ATTEMPTS        64
#define OFF_QUALITY         68
#define OFF_GENERATOR       72
#define OFF_ENTITY_SCHEMA   76
#define OFF_PHYSICS_ID      80
#define OFF_SNAPSHOT_COUNT  84
#define OFF_CONTROL_COUNT   88
#define OFF_MATERIAL_HASH   92
#define OFF_COMPILER_HASH  124
#define OFF_ENTITY_HASH    156
#define OFF_PHYSICS_HASH   188
#define OFF_NAME           220
#define OFF_SLUG           284
/* Schema minor 1: the donor a fork was made from, and the digest of the BSP
   that was actually read. */
#define OFF_DONOR_NAME     316
#define OFF_DONOR_HASH     380
#define OFF_CRC            412

const char *MapGenRecipe_TypeName(mapgen_gen_type_t type)
{
    switch (type) {
    case MAPGEN_GEN_AUTO:        return "auto";
    case MAPGEN_GEN_FULL_RANDOM: return "full_random";
    }
    return "unknown";
}

const char *MapGenRecipe_GoalName(mapgen_goal_t goal)
{
    switch (goal) {
    case MAPGEN_GOAL_MIX:           return "mix";
    case MAPGEN_GOAL_DUEL:          return "duel";
    case MAPGEN_GOAL_TDM:           return "tdm";
    case MAPGEN_GOAL_FFA:           return "ffa";
    case MAPGEN_GOAL_SINGLE_PLAYER: return "single_player";
    }
    return "unknown";
}

const char *MapGenRecipe_ResultName(mapgen_recipe_result_t r)
{
    switch (r) {
    case MAPGEN_RECIPE_OK:                     return "OK";
    case MAPGEN_RECIPE_ERR_ARGS:               return "ERR_ARGS";
    case MAPGEN_RECIPE_ERR_MEMORY:             return "ERR_MEMORY";
    case MAPGEN_RECIPE_ERR_TOO_SMALL:          return "ERR_TOO_SMALL";
    case MAPGEN_RECIPE_ERR_BAD_MAGIC:          return "ERR_BAD_MAGIC";
    case MAPGEN_RECIPE_ERR_UNSUPPORTED_MAJOR:  return "ERR_UNSUPPORTED_MAJOR";
    case MAPGEN_RECIPE_ERR_BAD_HEADER_BYTES:   return "ERR_BAD_HEADER_BYTES";
    case MAPGEN_RECIPE_ERR_BAD_FILE_BYTES:     return "ERR_BAD_FILE_BYTES";
    case MAPGEN_RECIPE_ERR_FILE_TOO_LARGE:     return "ERR_FILE_TOO_LARGE";
    case MAPGEN_RECIPE_ERR_RESERVED_NOT_ZERO:  return "ERR_RESERVED_NOT_ZERO";
    case MAPGEN_RECIPE_ERR_BAD_CRC:            return "ERR_BAD_CRC";
    case MAPGEN_RECIPE_ERR_TOO_MANY_SNAPSHOTS: return "ERR_TOO_MANY_SNAPSHOTS";
    case MAPGEN_RECIPE_ERR_TOO_MANY_CONTROLS:  return "ERR_TOO_MANY_CONTROLS";
    case MAPGEN_RECIPE_ERR_TABLE_OUT_OF_BOUNDS: return "ERR_TABLE_OUT_OF_BOUNDS";
    case MAPGEN_RECIPE_ERR_NO_SNAPSHOTS:       return "ERR_NO_SNAPSHOTS";
    case MAPGEN_RECIPE_ERR_NO_SOURCE:          return "ERR_NO_SOURCE";
    case MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL:  return "ERR_DUPLICATE_CONTROL";
    case MAPGEN_RECIPE_ERR_DUPLICATE_SNAPSHOT: return "ERR_DUPLICATE_SNAPSHOT";
    case MAPGEN_RECIPE_ERR_BAD_WEIGHT:         return "ERR_BAD_WEIGHT";
    case MAPGEN_RECIPE_ERR_BAD_TYPE:           return "ERR_BAD_TYPE";
    case MAPGEN_RECIPE_ERR_BAD_GOAL:           return "ERR_BAD_GOAL";
    case MAPGEN_RECIPE_ERR_BAD_ENVELOPE:       return "ERR_BAD_ENVELOPE";
    case MAPGEN_RECIPE_ERR_BAD_ATTEMPTS:       return "ERR_BAD_ATTEMPTS";
    case MAPGEN_RECIPE_ERR_BAD_SLUG:           return "ERR_BAD_SLUG";
    case MAPGEN_RECIPE_ERR_BAD_NAME:           return "ERR_BAD_NAME";
    case MAPGEN_RECIPE_ERR_BAD_KEY:            return "ERR_BAD_KEY";
    case MAPGEN_RECIPE_ERR_UNRESOLVED:         return "ERR_UNRESOLVED";
    case MAPGEN_RECIPE_RESULT_COUNT:           break;
    }
    return "ERR_UNKNOWN";
}

const char *MapGenRecipe_ReuseName(mapgen_recipe_reuse_t r)
{
    switch (r) {
    case MAPGEN_REUSE_OK:                  return "OK";
    case MAPGEN_REUSE_NEEDS_MIGRATION:     return "NEEDS_MIGRATION";
    case MAPGEN_REUSE_UNAVAILABLE_VERSION: return "UNAVAILABLE_VERSION";
    }
    return "UNKNOWN";
}

/* ---- little-endian accessors -------------------------------------------- */

static void wr_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
}

static void wr_u32(uint8_t *p, uint32_t v)
{
    for (int i = 0; i < 4; i++)
        p[i] = (uint8_t)((v >> (8 * i)) & 0xFFu);
}

static void wr_u64(uint8_t *p, uint64_t v)
{
    for (int i = 0; i < 8; i++)
        p[i] = (uint8_t)((v >> (8 * i)) & 0xFFu);
}

static uint16_t rd_u16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd_u32(const uint8_t *p)
{
    uint32_t v = 0;
    for (int i = 0; i < 4; i++)
        v |= (uint32_t)p[i] << (8 * i);
    return v;
}

static uint64_t rd_u64(const uint8_t *p)
{
    uint64_t v = 0;
    for (int i = 0; i < 8; i++)
        v |= (uint64_t)p[i] << (8 * i);
    return v;
}

/*
 * The checksum covers everything except its own four bytes - the header AND
 * both tables. A checksum that covered only the header would leave every
 * control and every snapshot pin unprotected, which is the exact gap the
 * snapshot container shipped with until a test found it.
 */
static uint32_t image_crc(const uint8_t *image, size_t size)
{
    uint32_t state = MapGenDigest_Crc32Init();
    state = MapGenDigest_Crc32Update(state, image, OFF_CRC);
    if (size > OFF_CRC + 4)
        state = MapGenDigest_Crc32Update(state, image + OFF_CRC + 4,
                                         size - (OFF_CRC + 4));
    return MapGenDigest_Crc32Final(state);
}

/* ---- names, keys and slugs ---------------------------------------------- */

/* A display name may be anything printable, including Russian; it is never a
   path. Control bytes are refused because they would break every report. */
static bool name_is_clean(const char *name, size_t cap)
{
    if (!name)
        return false;
    const size_t n = strnlen(name, cap);
    if (!n || n >= cap)
        return false;
    for (size_t i = 0; i < n; i++) {
        const unsigned char c = (unsigned char)name[i];
        if (c < 0x20 || c == 0x7F)
            return false;
    }
    return true;
}

/*
 * A slug becomes part of a filename, so contract 22's rules apply here and not
 * only at publication: lower-case ascii, digits, underscore. No separator, no
 * drive syntax, no dot at all - which also settles "..".
 */
static bool slug_is_safe(const char *slug)
{
    if (!slug)
        return false;
    const size_t n = strnlen(slug, MAPGEN_RECIPE_SLUG_BYTES);
    if (!n || n >= MAPGEN_RECIPE_SLUG_BYTES)
        return false;
    for (size_t i = 0; i < n; i++) {
        const char c = slug[i];
        const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
        if (!ok)
            return false;
    }
    return true;
}

/* A control key is an identifier, on the same rules, so it can be printed in a
   report and compared byte for byte. */
static bool key_is_clean(const char *key)
{
    if (!key)
        return false;
    const size_t n = strnlen(key, MAPGEN_RECIPE_KEY_BYTES);
    if (!n || n >= MAPGEN_RECIPE_KEY_BYTES)
        return false;
    for (size_t i = 0; i < n; i++) {
        const char c = key[i];
        const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
        if (!ok)
            return false;
    }
    return true;
}

/* ---- the builder -------------------------------------------------------- */

struct mapgen_recipe_builder_s {
    uint8_t  uuid[MAPGEN_RECIPE_UUID_BYTES];
    uint64_t seed;
    uint32_t type;
    uint32_t goal;
    uint32_t players_min;
    uint32_t players_max;
    uint32_t attempts;
    uint32_t quality;
    char     name[MAPGEN_RECIPE_NAME_BYTES];
    char     slug[MAPGEN_RECIPE_SLUG_BYTES];
    char     donor[MAPGEN_RECIPE_NAME_BYTES];
    uint8_t  donor_hash[MAPGEN_SHA256_BYTES];
    uint8_t  material_hash[MAPGEN_SHA256_BYTES];
    mapgen_recipe_toolchain_t toolchain;

    mapgen_recipe_snapshot_t *snapshots;
    uint32_t num_snapshots;
    mapgen_recipe_control_t  *controls;
    uint32_t num_controls;

    bool request_set;
    bool output_set;
};

mapgen_recipe_builder_t *MapGenRecipe_BuilderCreate(void)
{
    return calloc(1, sizeof(mapgen_recipe_builder_t));
}

void MapGenRecipe_BuilderFree(mapgen_recipe_builder_t *b)
{
    if (!b)
        return;
    free(b->snapshots);
    free(b->controls);
    free(b);
}

void MapGenRecipe_SetIdentity(mapgen_recipe_builder_t *b,
                              const uint8_t recipe_uuid[MAPGEN_RECIPE_UUID_BYTES],
                              uint64_t seed)
{
    if (!b)
        return;
    if (recipe_uuid)
        memcpy(b->uuid, recipe_uuid, MAPGEN_RECIPE_UUID_BYTES);
    b->seed = seed;
}

mapgen_recipe_result_t MapGenRecipe_SetRequest(mapgen_recipe_builder_t *b,
                                               mapgen_gen_type_t type,
                                               mapgen_goal_t goal,
                                               uint32_t players_min,
                                               uint32_t players_max,
                                               uint32_t attempt_limit,
                                               uint32_t quality_policy)
{
    if (!b)
        return MAPGEN_RECIPE_ERR_ARGS;
    if (type != MAPGEN_GEN_AUTO && type != MAPGEN_GEN_FULL_RANDOM)
        return MAPGEN_RECIPE_ERR_BAD_TYPE;
    if (goal < MAPGEN_GOAL_MIX || goal > MAPGEN_GOAL_SINGLE_PLAYER)
        return MAPGEN_RECIPE_ERR_BAD_GOAL;

    /*
     * The envelope is RESOLVED by the time a recipe exists, so contract 12's
     * per-goal policy is checkable here rather than trusted: a duel recipe
     * that says 2..8 did not resolve a duel.
     */
    if (!players_min || players_min > players_max || players_max > 32u)
        return MAPGEN_RECIPE_ERR_BAD_ENVELOPE;
    if (goal == MAPGEN_GOAL_DUEL && (players_min != 2u || players_max != 2u))
        return MAPGEN_RECIPE_ERR_BAD_ENVELOPE;
    if (goal == MAPGEN_GOAL_SINGLE_PLAYER && (players_min != 1u || players_max != 1u))
        return MAPGEN_RECIPE_ERR_BAD_ENVELOPE;
    if (goal == MAPGEN_GOAL_TDM &&
        (players_min < 4u || (players_min & 1u) || (players_max & 1u)))
        return MAPGEN_RECIPE_ERR_BAD_ENVELOPE;

    if (attempt_limit < MAPGEN_RECIPE_MIN_ATTEMPTS ||
        attempt_limit > MAPGEN_RECIPE_MAX_ATTEMPTS)
        return MAPGEN_RECIPE_ERR_BAD_ATTEMPTS;

    b->type = (uint32_t)type;
    b->goal = (uint32_t)goal;
    b->players_min = players_min;
    b->players_max = players_max;
    b->attempts = attempt_limit;
    b->quality = quality_policy;
    b->request_set = true;
    return MAPGEN_RECIPE_OK;
}

mapgen_recipe_result_t MapGenRecipe_SetOutput(mapgen_recipe_builder_t *b,
                                              const char *display_name,
                                              const char *slug)
{
    if (!b)
        return MAPGEN_RECIPE_ERR_ARGS;
    if (!name_is_clean(display_name, MAPGEN_RECIPE_NAME_BYTES))
        return MAPGEN_RECIPE_ERR_BAD_NAME;
    if (!slug_is_safe(slug))
        return MAPGEN_RECIPE_ERR_BAD_SLUG;

    memset(b->name, 0, sizeof(b->name));
    memset(b->slug, 0, sizeof(b->slug));
    memcpy(b->name, display_name, strlen(display_name));
    memcpy(b->slug, slug, strlen(slug));
    b->output_set = true;
    return MAPGEN_RECIPE_OK;
}

void MapGenRecipe_SetMaterialTable(mapgen_recipe_builder_t *b,
                                   const uint8_t sha256[MAPGEN_SHA256_BYTES])
{
    if (b && sha256)
        memcpy(b->material_hash, sha256, MAPGEN_SHA256_BYTES);
}

void MapGenRecipe_SetToolchain(mapgen_recipe_builder_t *b,
                               const mapgen_recipe_toolchain_t *toolchain)
{
    if (b && toolchain)
        b->toolchain = *toolchain;
}

mapgen_recipe_result_t MapGenRecipe_AddSnapshot(mapgen_recipe_builder_t *b,
                                                const mapgen_recipe_snapshot_t *snapshot)
{
    if (!b || !snapshot)
        return MAPGEN_RECIPE_ERR_ARGS;
    if (b->num_snapshots >= MAPGEN_RECIPE_MAX_SNAPSHOTS)
        return MAPGEN_RECIPE_ERR_TOO_MANY_SNAPSHOTS;
    if (snapshot->weight < 1u || snapshot->weight > 100u)
        return MAPGEN_RECIPE_ERR_BAD_WEIGHT;

    for (uint32_t i = 0; i < b->num_snapshots; i++)
        if (!memcmp(b->snapshots[i].revision_uuid, snapshot->revision_uuid,
                    MAPGEN_RECIPE_UUID_BYTES))
            return MAPGEN_RECIPE_ERR_DUPLICATE_SNAPSHOT;

    void *grown = realloc(b->snapshots,
                          (size_t)(b->num_snapshots + 1) * sizeof(*b->snapshots));
    if (!grown)
        return MAPGEN_RECIPE_ERR_MEMORY;
    b->snapshots = grown;
    b->snapshots[b->num_snapshots++] = *snapshot;
    return MAPGEN_RECIPE_OK;
}

mapgen_recipe_result_t MapGenRecipe_AddControl(mapgen_recipe_builder_t *b,
                                               const char *key,
                                               int32_t requested,
                                               int32_t resolved)
{
    if (!b)
        return MAPGEN_RECIPE_ERR_ARGS;
    if (!key_is_clean(key))
        return MAPGEN_RECIPE_ERR_BAD_KEY;
    if (b->num_controls >= MAPGEN_RECIPE_MAX_CONTROLS)
        return MAPGEN_RECIPE_ERR_TOO_MANY_CONTROLS;

    /* A recipe that has run has no Auto left in it. Storing one would let
       `Generate Again` re-resolve it under a newer engine, which is the one
       thing contract 10 says must never happen. */
    if (resolved == MAPGEN_RECIPE_AUTO)
        return MAPGEN_RECIPE_ERR_UNRESOLVED;

    for (uint32_t i = 0; i < b->num_controls; i++)
        if (!strcmp(b->controls[i].key, key))
            return MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL;

    void *grown = realloc(b->controls,
                          (size_t)(b->num_controls + 1) * sizeof(*b->controls));
    if (!grown)
        return MAPGEN_RECIPE_ERR_MEMORY;
    b->controls = grown;
    mapgen_recipe_control_t *slot = &b->controls[b->num_controls++];
    memset(slot, 0, sizeof(*slot));
    memcpy(slot->key, key, strlen(key));
    slot->requested = requested;
    slot->resolved = resolved;
    return MAPGEN_RECIPE_OK;
}

/* Canonical order, so two builders that were given the same content in
   different orders serialize to the same bytes. */
static int compare_controls(const void *a, const void *b)
{
    return strcmp(((const mapgen_recipe_control_t *)a)->key,
                  ((const mapgen_recipe_control_t *)b)->key);
}

/*
 * The map this recipe forked, and the digest of the BSP that was read.
 *
 * The digest is of the file, not of the name: a map that changed under the
 * same name is a different input, and a rerun that ignored that would produce
 * a different map and call it the same recipe.
 */
mapgen_recipe_result_t MapGenRecipe_SetDonor(mapgen_recipe_builder_t *b,
                                             const char *map_name,
                                             const uint8_t sha256[MAPGEN_SHA256_BYTES])
{
    if (!b || !map_name || !sha256)
        return MAPGEN_RECIPE_ERR_ARGS;
    const size_t len = strlen(map_name);
    if (!len || len >= MAPGEN_RECIPE_NAME_BYTES)
        return MAPGEN_RECIPE_ERR_BAD_NAME;
    memset(b->donor, 0, sizeof(b->donor));
    memcpy(b->donor, map_name, len);
    memcpy(b->donor_hash, sha256, MAPGEN_SHA256_BYTES);
    return MAPGEN_RECIPE_OK;
}

static int compare_snapshots(const void *a, const void *b)
{
    return memcmp(((const mapgen_recipe_snapshot_t *)a)->revision_uuid,
                  ((const mapgen_recipe_snapshot_t *)b)->revision_uuid,
                  MAPGEN_RECIPE_UUID_BYTES);
}

mapgen_recipe_result_t MapGenRecipe_Finish(mapgen_recipe_builder_t *b,
                                           uint8_t **out_bytes, size_t *out_size)
{
    if (!b || !out_bytes || !out_size)
        return MAPGEN_RECIPE_ERR_ARGS;
    *out_bytes = NULL;
    *out_size = 0;
    if (!b->request_set)
        return MAPGEN_RECIPE_ERR_BAD_TYPE;
    if (!b->output_set)
        return MAPGEN_RECIPE_ERR_BAD_SLUG;
    /* At least one source. A snapshot, a donor, or both - a recipe with
       neither describes no input at all. */
    if (!b->num_snapshots && !b->donor[0])
        return MAPGEN_RECIPE_ERR_NO_SOURCE;

    const size_t size = (size_t)MAPGEN_RECIPE_HEADER_BYTES
                      + (size_t)b->num_snapshots * MAPGEN_RECIPE_SNAPSHOT_BYTES
                      + (size_t)b->num_controls * MAPGEN_RECIPE_CONTROL_BYTES;
    if (size > MAPGEN_RECIPE_MAX_FILE_BYTES)
        return MAPGEN_RECIPE_ERR_FILE_TOO_LARGE;

    uint8_t *image = calloc(1, size);
    if (!image)
        return MAPGEN_RECIPE_ERR_MEMORY;

    qsort(b->snapshots, b->num_snapshots, sizeof(*b->snapshots), compare_snapshots);
    if (b->num_controls)
        qsort(b->controls, b->num_controls, sizeof(*b->controls), compare_controls);

    memcpy(image + OFF_MAGIC, MAPGEN_RECIPE_MAGIC, MAPGEN_RECIPE_MAGIC_BYTES);
    wr_u16(image + OFF_SCHEMA_MAJOR, MAPGEN_RECIPE_SCHEMA_MAJOR);
    wr_u16(image + OFF_SCHEMA_MINOR, MAPGEN_RECIPE_SCHEMA_MINOR);
    wr_u16(image + OFF_HEADER_BYTES, MAPGEN_RECIPE_HEADER_BYTES);
    wr_u16(image + OFF_RESERVED, 0);
    wr_u64(image + OFF_FILE_BYTES, (uint64_t)size);
    memcpy(image + OFF_UUID, b->uuid, MAPGEN_RECIPE_UUID_BYTES);
    wr_u64(image + OFF_SEED, b->seed);
    wr_u32(image + OFF_TYPE, b->type);
    wr_u32(image + OFF_GOAL, b->goal);
    wr_u32(image + OFF_PLAYERS_MIN, b->players_min);
    wr_u32(image + OFF_PLAYERS_MAX, b->players_max);
    wr_u32(image + OFF_ATTEMPTS, b->attempts);
    wr_u32(image + OFF_QUALITY, b->quality);
    wr_u32(image + OFF_GENERATOR, b->toolchain.generator_version);
    wr_u32(image + OFF_ENTITY_SCHEMA, b->toolchain.entity_schema_version);
    wr_u32(image + OFF_PHYSICS_ID, b->toolchain.physics_profile_id);
    wr_u32(image + OFF_SNAPSHOT_COUNT, b->num_snapshots);
    wr_u32(image + OFF_CONTROL_COUNT, b->num_controls);
    memcpy(image + OFF_MATERIAL_HASH, b->material_hash, MAPGEN_SHA256_BYTES);
    memcpy(image + OFF_COMPILER_HASH, b->toolchain.compiler_build_sha256,
           MAPGEN_SHA256_BYTES);
    memcpy(image + OFF_ENTITY_HASH, b->toolchain.entity_schema_sha256,
           MAPGEN_SHA256_BYTES);
    memcpy(image + OFF_PHYSICS_HASH, b->toolchain.physics_profile_sha256,
           MAPGEN_SHA256_BYTES);
    memcpy(image + OFF_NAME, b->name, MAPGEN_RECIPE_NAME_BYTES);
    memcpy(image + OFF_SLUG, b->slug, MAPGEN_RECIPE_SLUG_BYTES);
    memcpy(image + OFF_DONOR_NAME, b->donor, MAPGEN_RECIPE_NAME_BYTES);
    memcpy(image + OFF_DONOR_HASH, b->donor_hash, MAPGEN_SHA256_BYTES);

    size_t at = MAPGEN_RECIPE_HEADER_BYTES;
    for (uint32_t i = 0; i < b->num_snapshots; i++) {
        memcpy(image + at, b->snapshots[i].revision_uuid, MAPGEN_RECIPE_UUID_BYTES);
        memcpy(image + at + 16, b->snapshots[i].payload_sha256, MAPGEN_SHA256_BYTES);
        wr_u32(image + at + 48, b->snapshots[i].weight);
        at += MAPGEN_RECIPE_SNAPSHOT_BYTES;
    }
    for (uint32_t i = 0; i < b->num_controls; i++) {
        memcpy(image + at, b->controls[i].key, MAPGEN_RECIPE_KEY_BYTES);
        wr_u32(image + at + 40, (uint32_t)b->controls[i].requested);
        wr_u32(image + at + 44, (uint32_t)b->controls[i].resolved);
        at += MAPGEN_RECIPE_CONTROL_BYTES;
    }

    wr_u32(image + OFF_CRC, image_crc(image, size));

    *out_bytes = image;
    *out_size = size;
    return MAPGEN_RECIPE_OK;
}

/* ---- reading ------------------------------------------------------------ */

struct mapgen_recipe_s {
    uint8_t  uuid[MAPGEN_RECIPE_UUID_BYTES];
    uint64_t seed;
    uint32_t type;
    uint32_t goal;
    uint32_t players_min;
    uint32_t players_max;
    uint32_t attempts;
    uint32_t quality;
    char     name[MAPGEN_RECIPE_NAME_BYTES];
    char     slug[MAPGEN_RECIPE_SLUG_BYTES];
    char     donor[MAPGEN_RECIPE_NAME_BYTES];
    uint8_t  donor_hash[MAPGEN_SHA256_BYTES];
    uint8_t  material_hash[MAPGEN_SHA256_BYTES];
    mapgen_recipe_toolchain_t toolchain;

    mapgen_recipe_snapshot_t *snapshots;
    uint32_t num_snapshots;
    mapgen_recipe_control_t  *controls;
    uint32_t num_controls;
};

mapgen_recipe_result_t MapGenRecipe_Open(const uint8_t *bytes, size_t size,
                                         mapgen_recipe_t **out)
{
    if (!bytes || !out)
        return MAPGEN_RECIPE_ERR_ARGS;
    *out = NULL;

    if (size < MAPGEN_RECIPE_HEADER_BYTES)
        return MAPGEN_RECIPE_ERR_TOO_SMALL;
    if (memcmp(bytes + OFF_MAGIC, MAPGEN_RECIPE_MAGIC, MAPGEN_RECIPE_MAGIC_BYTES))
        return MAPGEN_RECIPE_ERR_BAD_MAGIC;
    if (rd_u16(bytes + OFF_SCHEMA_MAJOR) != MAPGEN_RECIPE_SCHEMA_MAJOR)
        return MAPGEN_RECIPE_ERR_UNSUPPORTED_MAJOR;
    if (rd_u16(bytes + OFF_HEADER_BYTES) != MAPGEN_RECIPE_HEADER_BYTES)
        return MAPGEN_RECIPE_ERR_BAD_HEADER_BYTES;
    if (rd_u16(bytes + OFF_RESERVED) != 0)
        return MAPGEN_RECIPE_ERR_RESERVED_NOT_ZERO;

    const uint64_t declared = rd_u64(bytes + OFF_FILE_BYTES);
    if (declared > MAPGEN_RECIPE_MAX_FILE_BYTES)
        return MAPGEN_RECIPE_ERR_FILE_TOO_LARGE;
    if (declared != (uint64_t)size)
        return MAPGEN_RECIPE_ERR_BAD_FILE_BYTES;

    /* The checksum before the counts: a corrupted count field is exactly what
       a checksum is for, and believing it first is how a reader is made to
       allocate on a damaged number. */
    if (image_crc(bytes, size) != rd_u32(bytes + OFF_CRC))
        return MAPGEN_RECIPE_ERR_BAD_CRC;

    const uint32_t snapshot_count = rd_u32(bytes + OFF_SNAPSHOT_COUNT);
    const uint32_t control_count = rd_u32(bytes + OFF_CONTROL_COUNT);
    /* At least one source: a snapshot, a donor, or both. A fork has no
       snapshots at all, and refusing it would refuse the generation this
       product actually ships. */
    if (!snapshot_count && !bytes[OFF_DONOR_NAME])
        return MAPGEN_RECIPE_ERR_NO_SOURCE;
    if (snapshot_count > MAPGEN_RECIPE_MAX_SNAPSHOTS)
        return MAPGEN_RECIPE_ERR_TOO_MANY_SNAPSHOTS;
    if (control_count > MAPGEN_RECIPE_MAX_CONTROLS)
        return MAPGEN_RECIPE_ERR_TOO_MANY_CONTROLS;

    const size_t needed = (size_t)MAPGEN_RECIPE_HEADER_BYTES
                        + (size_t)snapshot_count * MAPGEN_RECIPE_SNAPSHOT_BYTES
                        + (size_t)control_count * MAPGEN_RECIPE_CONTROL_BYTES;
    if (needed != size)
        return MAPGEN_RECIPE_ERR_TABLE_OUT_OF_BOUNDS;

    const uint32_t type = rd_u32(bytes + OFF_TYPE);
    const uint32_t goal = rd_u32(bytes + OFF_GOAL);
    if (type != MAPGEN_GEN_AUTO && type != MAPGEN_GEN_FULL_RANDOM)
        return MAPGEN_RECIPE_ERR_BAD_TYPE;
    if (goal < MAPGEN_GOAL_MIX || goal > MAPGEN_GOAL_SINGLE_PLAYER)
        return MAPGEN_RECIPE_ERR_BAD_GOAL;

    mapgen_recipe_t *r = calloc(1, sizeof(*r));
    if (!r)
        return MAPGEN_RECIPE_ERR_MEMORY;

    memcpy(r->uuid, bytes + OFF_UUID, MAPGEN_RECIPE_UUID_BYTES);
    r->seed = rd_u64(bytes + OFF_SEED);
    r->type = type;
    r->goal = goal;
    r->players_min = rd_u32(bytes + OFF_PLAYERS_MIN);
    r->players_max = rd_u32(bytes + OFF_PLAYERS_MAX);
    r->attempts = rd_u32(bytes + OFF_ATTEMPTS);
    r->quality = rd_u32(bytes + OFF_QUALITY);
    r->toolchain.generator_version = rd_u32(bytes + OFF_GENERATOR);
    r->toolchain.entity_schema_version = rd_u32(bytes + OFF_ENTITY_SCHEMA);
    r->toolchain.physics_profile_id = rd_u32(bytes + OFF_PHYSICS_ID);
    memcpy(r->material_hash, bytes + OFF_MATERIAL_HASH, MAPGEN_SHA256_BYTES);
    memcpy(r->toolchain.compiler_build_sha256, bytes + OFF_COMPILER_HASH,
           MAPGEN_SHA256_BYTES);
    memcpy(r->toolchain.entity_schema_sha256, bytes + OFF_ENTITY_HASH,
           MAPGEN_SHA256_BYTES);
    memcpy(r->toolchain.physics_profile_sha256, bytes + OFF_PHYSICS_HASH,
           MAPGEN_SHA256_BYTES);

    /* Terminated by construction: the fields are fixed-width and the last byte
       of each is never written by the builder. Enforced anyway, because the
       bytes came from a file. */
    memcpy(r->name, bytes + OFF_NAME, MAPGEN_RECIPE_NAME_BYTES);
    r->name[MAPGEN_RECIPE_NAME_BYTES - 1] = '\0';
    memcpy(r->slug, bytes + OFF_SLUG, MAPGEN_RECIPE_SLUG_BYTES);
    r->slug[MAPGEN_RECIPE_SLUG_BYTES - 1] = '\0';
    /* The donor, when there is one. Terminated and checked like every other
       name that came out of a file. */
    memcpy(r->donor, bytes + OFF_DONOR_NAME, MAPGEN_RECIPE_NAME_BYTES);
    r->donor[MAPGEN_RECIPE_NAME_BYTES - 1] = '\0';
    memcpy(r->donor_hash, bytes + OFF_DONOR_HASH, MAPGEN_SHA256_BYTES);

    if (!name_is_clean(r->name, MAPGEN_RECIPE_NAME_BYTES)) {
        MapGenRecipe_Free(r);
        return MAPGEN_RECIPE_ERR_BAD_NAME;
    }
    if (r->donor[0] && !name_is_clean(r->donor, MAPGEN_RECIPE_NAME_BYTES)) {
        MapGenRecipe_Free(r);
        return MAPGEN_RECIPE_ERR_BAD_NAME;
    }
    if (!slug_is_safe(r->slug)) {
        MapGenRecipe_Free(r);
        return MAPGEN_RECIPE_ERR_BAD_SLUG;
    }

    r->snapshots = calloc(snapshot_count, sizeof(*r->snapshots));
    if (!r->snapshots) {
        MapGenRecipe_Free(r);
        return MAPGEN_RECIPE_ERR_MEMORY;
    }
    if (control_count) {
        r->controls = calloc(control_count, sizeof(*r->controls));
        if (!r->controls) {
            MapGenRecipe_Free(r);
            return MAPGEN_RECIPE_ERR_MEMORY;
        }
    }

    size_t at = MAPGEN_RECIPE_HEADER_BYTES;
    for (uint32_t i = 0; i < snapshot_count; i++) {
        memcpy(r->snapshots[i].revision_uuid, bytes + at, MAPGEN_RECIPE_UUID_BYTES);
        memcpy(r->snapshots[i].payload_sha256, bytes + at + 16, MAPGEN_SHA256_BYTES);
        r->snapshots[i].weight = rd_u32(bytes + at + 48);
        if (r->snapshots[i].weight < 1u || r->snapshots[i].weight > 100u) {
            MapGenRecipe_Free(r);
            return MAPGEN_RECIPE_ERR_BAD_WEIGHT;
        }
        for (uint32_t j = 0; j < i; j++) {
            if (!memcmp(r->snapshots[j].revision_uuid,
                        r->snapshots[i].revision_uuid, MAPGEN_RECIPE_UUID_BYTES)) {
                MapGenRecipe_Free(r);
                return MAPGEN_RECIPE_ERR_DUPLICATE_SNAPSHOT;
            }
        }
        at += MAPGEN_RECIPE_SNAPSHOT_BYTES;
    }
    r->num_snapshots = snapshot_count;

    for (uint32_t i = 0; i < control_count; i++) {
        memcpy(r->controls[i].key, bytes + at, MAPGEN_RECIPE_KEY_BYTES);
        r->controls[i].key[MAPGEN_RECIPE_KEY_BYTES - 1] = '\0';
        r->controls[i].requested = (int32_t)rd_u32(bytes + at + 40);
        r->controls[i].resolved = (int32_t)rd_u32(bytes + at + 44);
        if (!key_is_clean(r->controls[i].key)) {
            MapGenRecipe_Free(r);
            return MAPGEN_RECIPE_ERR_BAD_KEY;
        }
        if (r->controls[i].resolved == MAPGEN_RECIPE_AUTO) {
            MapGenRecipe_Free(r);
            return MAPGEN_RECIPE_ERR_UNRESOLVED;
        }
        for (uint32_t j = 0; j < i; j++) {
            if (!strcmp(r->controls[j].key, r->controls[i].key)) {
                MapGenRecipe_Free(r);
                return MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL;
            }
        }
        at += MAPGEN_RECIPE_CONTROL_BYTES;
    }
    r->num_controls = control_count;

    *out = r;
    return MAPGEN_RECIPE_OK;
}

void MapGenRecipe_Free(mapgen_recipe_t *recipe)
{
    if (!recipe)
        return;
    free(recipe->snapshots);
    free(recipe->controls);
    free(recipe);
}

/* ---- accessors ---------------------------------------------------------- */

const uint8_t *MapGenRecipe_Uuid(const mapgen_recipe_t *r) { return r ? r->uuid : NULL; }
uint64_t MapGenRecipe_Seed(const mapgen_recipe_t *r) { return r ? r->seed : 0; }
mapgen_gen_type_t MapGenRecipe_Type(const mapgen_recipe_t *r)
{
    return r ? (mapgen_gen_type_t)r->type : MAPGEN_GEN_AUTO;
}
mapgen_goal_t MapGenRecipe_Goal(const mapgen_recipe_t *r)
{
    return r ? (mapgen_goal_t)r->goal : MAPGEN_GOAL_MIX;
}
uint32_t MapGenRecipe_PlayersMin(const mapgen_recipe_t *r) { return r ? r->players_min : 0; }
uint32_t MapGenRecipe_PlayersMax(const mapgen_recipe_t *r) { return r ? r->players_max : 0; }
uint32_t MapGenRecipe_AttemptLimit(const mapgen_recipe_t *r) { return r ? r->attempts : 0; }
uint32_t MapGenRecipe_QualityPolicy(const mapgen_recipe_t *r) { return r ? r->quality : 0; }
const char *MapGenRecipe_DisplayName(const mapgen_recipe_t *r) { return r ? r->name : NULL; }
const char *MapGenRecipe_Slug(const mapgen_recipe_t *r) { return r ? r->slug : NULL; }
/* Empty when this recipe forked nothing. */
const char *MapGenRecipe_Donor(const mapgen_recipe_t *r) { return r ? r->donor : ""; }
const uint8_t *MapGenRecipe_DonorHash(const mapgen_recipe_t *r) { return r ? r->donor_hash : NULL; }
const uint8_t *MapGenRecipe_MaterialTableHash(const mapgen_recipe_t *r)
{
    return r ? r->material_hash : NULL;
}
const mapgen_recipe_toolchain_t *MapGenRecipe_Toolchain(const mapgen_recipe_t *r)
{
    return r ? &r->toolchain : NULL;
}
uint32_t MapGenRecipe_NumSnapshots(const mapgen_recipe_t *r)
{
    return r ? r->num_snapshots : 0;
}
const mapgen_recipe_snapshot_t *MapGenRecipe_SnapshotAt(const mapgen_recipe_t *r,
                                                        uint32_t index)
{
    return (r && index < r->num_snapshots) ? &r->snapshots[index] : NULL;
}
uint32_t MapGenRecipe_NumControls(const mapgen_recipe_t *r)
{
    return r ? r->num_controls : 0;
}
const mapgen_recipe_control_t *MapGenRecipe_ControlAt(const mapgen_recipe_t *r,
                                                      uint32_t index)
{
    return (r && index < r->num_controls) ? &r->controls[index] : NULL;
}
const mapgen_recipe_control_t *MapGenRecipe_Control(const mapgen_recipe_t *r,
                                                    const char *key)
{
    if (!r || !key)
        return NULL;
    for (uint32_t i = 0; i < r->num_controls; i++)
        if (!strcmp(r->controls[i].key, key))
            return &r->controls[i];
    return NULL;
}

int32_t MapGenRecipe_ResolvedValue(const mapgen_recipe_t *r, const char *key,
                                   int32_t fallback)
{
    const mapgen_recipe_control_t *c = MapGenRecipe_Control(r, key);
    return c ? c->resolved : fallback;
}

/* ---- reuse -------------------------------------------------------------- */

static bool hash_is_present(const uint8_t hash[MAPGEN_SHA256_BYTES])
{
    for (size_t i = 0; i < MAPGEN_SHA256_BYTES; i++)
        if (hash[i])
            return true;
    return false;
}

mapgen_recipe_reuse_t MapGenRecipe_CheckReuse(const mapgen_recipe_t *recipe,
                                              const mapgen_recipe_toolchain_t *installed,
                                              const char **which)
{
    if (which)
        *which = NULL;
    if (!recipe || !installed) {
        if (which)
            *which = "toolchain";
        return MAPGEN_REUSE_UNAVAILABLE_VERSION;
    }

    const mapgen_recipe_toolchain_t *pinned = &recipe->toolchain;

    /*
     * Absent beats different. A zero version or an all-zero hash is what "we
     * could not read it" looks like, and calling that a match would disarm the
     * whole check on exactly the machine where it matters most.
     */
    if (!installed->generator_version) {
        if (which) *which = "generator";
        return MAPGEN_REUSE_UNAVAILABLE_VERSION;
    }
    if (!hash_is_present(installed->compiler_build_sha256)) {
        if (which) *which = "compiler";
        return MAPGEN_REUSE_UNAVAILABLE_VERSION;
    }
    if (!installed->entity_schema_version ||
        !hash_is_present(installed->entity_schema_sha256)) {
        if (which) *which = "entity_schema";
        return MAPGEN_REUSE_UNAVAILABLE_VERSION;
    }
    if (!installed->physics_profile_id ||
        !hash_is_present(installed->physics_profile_sha256)) {
        if (which) *which = "physics_profile";
        return MAPGEN_REUSE_UNAVAILABLE_VERSION;
    }

    if (pinned->generator_version != installed->generator_version) {
        if (which) *which = "generator";
        return MAPGEN_REUSE_NEEDS_MIGRATION;
    }
    if (memcmp(pinned->compiler_build_sha256, installed->compiler_build_sha256,
               MAPGEN_SHA256_BYTES)) {
        if (which) *which = "compiler";
        return MAPGEN_REUSE_NEEDS_MIGRATION;
    }
    if (pinned->entity_schema_version != installed->entity_schema_version ||
        memcmp(pinned->entity_schema_sha256, installed->entity_schema_sha256,
               MAPGEN_SHA256_BYTES)) {
        if (which) *which = "entity_schema";
        return MAPGEN_REUSE_NEEDS_MIGRATION;
    }
    if (pinned->physics_profile_id != installed->physics_profile_id ||
        memcmp(pinned->physics_profile_sha256, installed->physics_profile_sha256,
               MAPGEN_SHA256_BYTES)) {
        if (which) *which = "physics_profile";
        return MAPGEN_REUSE_NEEDS_MIGRATION;
    }

    return MAPGEN_REUSE_OK;
}

/* ---- canonical form ----------------------------------------------------- */

typedef struct {
    char  *out;
    size_t capacity;
    size_t needed;
} sink_t;

static void put(sink_t *s, const char *text)
{
    const size_t n = strlen(text);
    if (s->out && s->needed < s->capacity) {
        const size_t room = s->capacity - 1 - s->needed;
        memcpy(s->out + s->needed, text, n < room ? n : room);
    }
    s->needed += n;
}

static void put_u64(sink_t *s, uint64_t v)
{
    char buf[24], tmp[24];
    size_t n = 0, t = 0;
    if (!v) {
        tmp[t++] = '0';
    } else {
        while (v) {
            tmp[t++] = (char)('0' + (v % 10u));
            v /= 10u;
        }
    }
    while (t)
        buf[n++] = tmp[--t];
    buf[n] = '\0';
    put(s, buf);
}

static void put_i32(sink_t *s, int32_t v)
{
    if (v == MAPGEN_RECIPE_AUTO) {
        put(s, "auto");
        return;
    }
    if (v < 0) {
        put(s, "-");
        put_u64(s, (uint64_t)(-(int64_t)v));
        return;
    }
    put_u64(s, (uint64_t)v);
}

static void put_hex(sink_t *s, const uint8_t *bytes, size_t count)
{
    static const char digits[] = "0123456789abcdef";
    char buf[3] = { 0, 0, 0 };
    for (size_t i = 0; i < count; i++) {
        buf[0] = digits[bytes[i] >> 4];
        buf[1] = digits[bytes[i] & 0x0Fu];
        put(s, buf);
    }
}

size_t MapGenRecipe_CanonicalText(const mapgen_recipe_t *r, char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!r) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    put(&s, "recipe=");
    put_hex(&s, r->uuid, MAPGEN_RECIPE_UUID_BYTES);
    put(&s, "\nseed=");
    put_u64(&s, r->seed);
    put(&s, "\ntype=");
    put(&s, MapGenRecipe_TypeName((mapgen_gen_type_t)r->type));
    put(&s, "\ngoal=");
    put(&s, MapGenRecipe_GoalName((mapgen_goal_t)r->goal));
    put(&s, "\nplayers=");
    put_u64(&s, r->players_min);
    put(&s, "..");
    put_u64(&s, r->players_max);
    put(&s, "\nattempts=");
    put_u64(&s, r->attempts);
    put(&s, "\nquality=");
    put_u64(&s, r->quality);
    put(&s, "\nslug=");
    put(&s, r->slug);
    put(&s, "\nname=");
    put(&s, r->name);
    put(&s, "\nmaterials=");
    put_hex(&s, r->material_hash, MAPGEN_SHA256_BYTES);
    put(&s, "\ngenerator=");
    put_u64(&s, r->toolchain.generator_version);
    put(&s, "\ncompiler=");
    put_hex(&s, r->toolchain.compiler_build_sha256, MAPGEN_SHA256_BYTES);
    put(&s, "\nentity_schema=");
    put_u64(&s, r->toolchain.entity_schema_version);
    put(&s, ",");
    put_hex(&s, r->toolchain.entity_schema_sha256, MAPGEN_SHA256_BYTES);
    put(&s, "\nphysics=");
    put_u64(&s, r->toolchain.physics_profile_id);
    put(&s, ",");
    put_hex(&s, r->toolchain.physics_profile_sha256, MAPGEN_SHA256_BYTES);
    put(&s, "\nsnapshots=");
    put_u64(&s, r->num_snapshots);
    put(&s, "\n");
    for (uint32_t i = 0; i < r->num_snapshots; i++) {
        put(&s, "s=");
        put_hex(&s, r->snapshots[i].revision_uuid, MAPGEN_RECIPE_UUID_BYTES);
        put(&s, ",");
        put_hex(&s, r->snapshots[i].payload_sha256, MAPGEN_SHA256_BYTES);
        put(&s, ",");
        put_u64(&s, r->snapshots[i].weight);
        put(&s, "\n");
    }
    put(&s, "controls=");
    put_u64(&s, r->num_controls);
    put(&s, "\n");
    for (uint32_t i = 0; i < r->num_controls; i++) {
        put(&s, "c=");
        put(&s, r->controls[i].key);
        put(&s, ",");
        put_i32(&s, r->controls[i].requested);
        put(&s, ",");
        put_i32(&s, r->controls[i].resolved);
        put(&s, "\n");
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenRecipe_CanonicalDigest(const mapgen_recipe_t *r)
{
    const size_t needed = MapGenRecipe_CanonicalText(r, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenRecipe_CanonicalText(r, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
