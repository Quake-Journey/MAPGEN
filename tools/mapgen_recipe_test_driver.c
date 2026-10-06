/*
 * MAPGEN-1 recipe test driver.
 *
 * Compiled and run by tools/check_mapgen_recipe_contract.py.
 *
 *   driver run
 *
 * Every case builds a real `.q2mgrec` image in memory and reads it back with
 * the real reader. Damaged files are CONSTRUCTED byte by byte - truncated at
 * every length, one bit flipped at every offset - rather than described.
 */

#include "common/mapgen_recipe.h"

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

/* -------------------------------------------------------------------------- */

/*
 * The checksum, recomputed here rather than asked of the module.
 *
 * It exists so the driver can build a file that is DAMAGED IN MEANING while
 * being perfectly well-formed: a valid checksum over a table that says
 * something the format forbids. Without it, every constructed defect would be
 * caught by the checksum and the reader's own rules would never be reached.
 * It doubles as a second statement of which bytes the checksum covers.
 */
/* The checksum sits at the end of the header, so it MOVES when the header
   grows - and it did, when the recipe learned about donors. Derived, because a
   copy of the number here is a second spelling of one fact. */
#define RECIPE_OFF_CRC   (MAPGEN_RECIPE_HEADER_BYTES - 4)

static void refresh_crc(uint8_t *image, size_t size)
{
    uint32_t state = MapGenDigest_Crc32Init();
    state = MapGenDigest_Crc32Update(state, image, RECIPE_OFF_CRC);
    state = MapGenDigest_Crc32Update(state, image + RECIPE_OFF_CRC + 4,
                                     size - (RECIPE_OFF_CRC + 4));
    state = MapGenDigest_Crc32Final(state);
    for (int i = 0; i < 4; i++)
        image[RECIPE_OFF_CRC + i] = (uint8_t)((state >> (8 * i)) & 0xFFu);
}

/* Where control `index` starts, in a file with `snapshots` snapshot rows. */
static size_t control_at(uint32_t snapshots, uint32_t index)
{
    return (size_t)MAPGEN_RECIPE_HEADER_BYTES
         + (size_t)snapshots * MAPGEN_RECIPE_SNAPSHOT_BYTES
         + (size_t)index * MAPGEN_RECIPE_CONTROL_BYTES;
}

static void fill(uint8_t *bytes, size_t count, uint8_t tag)
{
    for (size_t i = 0; i < count; i++)
        bytes[i] = (uint8_t)(tag + i);
}

static mapgen_recipe_toolchain_t sample_toolchain(uint8_t tag)
{
    mapgen_recipe_toolchain_t t;
    memset(&t, 0, sizeof(t));
    t.generator_version = 0x00010600u;
    t.entity_schema_version = 3;
    t.physics_profile_id = 1;
    fill(t.compiler_build_sha256, MAPGEN_SHA256_BYTES, (uint8_t)(0x10 + tag));
    fill(t.entity_schema_sha256, MAPGEN_SHA256_BYTES, (uint8_t)(0x40 + tag));
    fill(t.physics_profile_sha256, MAPGEN_SHA256_BYTES, (uint8_t)(0x70 + tag));
    return t;
}

/* A builder with everything a valid recipe needs. */
static mapgen_recipe_builder_t *sample_builder(void)
{
    mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
    if (!b)
        return NULL;

    uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
    fill(uuid, sizeof(uuid), 0xA1);
    MapGenRecipe_SetIdentity(b, uuid, 0x0123456789ABCDEFull);
    MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA, 2, 16, 32, 1);
    MapGenRecipe_SetOutput(b, "Test Map", "test_map");

    uint8_t materials[MAPGEN_SHA256_BYTES];
    fill(materials, sizeof(materials), 0xC0);
    MapGenRecipe_SetMaterialTable(b, materials);

    const mapgen_recipe_toolchain_t t = sample_toolchain(0);
    MapGenRecipe_SetToolchain(b, &t);

    mapgen_recipe_snapshot_t snap;
    memset(&snap, 0, sizeof(snap));
    fill(snap.revision_uuid, sizeof(snap.revision_uuid), 0x01);
    fill(snap.payload_sha256, sizeof(snap.payload_sha256), 0x02);
    snap.weight = 50;
    MapGenRecipe_AddSnapshot(b, &snap);

    fill(snap.revision_uuid, sizeof(snap.revision_uuid), 0x03);
    fill(snap.payload_sha256, sizeof(snap.payload_sha256), 0x04);
    snap.weight = 50;
    MapGenRecipe_AddSnapshot(b, &snap);

    MapGenRecipe_AddControl(b, "item_quad", MAPGEN_RECIPE_AUTO, 1);
    MapGenRecipe_AddControl(b, "item_health", 12, 12);
    MapGenRecipe_AddControl(b, "arch_water", MAPGEN_RECIPE_AUTO, 2);
    MapGenRecipe_AddControl(b, "weapon_bfg", 0, 0);
    return b;
}

static bool sample_image(uint8_t **bytes, size_t *size)
{
    mapgen_recipe_builder_t *b = sample_builder();
    if (!b)
        return false;
    const mapgen_recipe_result_t r = MapGenRecipe_Finish(b, bytes, size);
    MapGenRecipe_BuilderFree(b);
    return r == MAPGEN_RECIPE_OK;
}

/* -------------------------------------------------------------------------- */

int main(int argc, char **argv)
{
    if (argc < 2 || strcmp(argv[1], "run")) {
        printf("usage: driver run\n");
        return 2;
    }

    uint8_t *image = NULL;
    size_t size = 0;
    check("a complete recipe serializes", sample_image(&image, &size), "");
    if (!image)
        return 1;

    check("and its size is exactly header plus both tables",
          size == (size_t)MAPGEN_RECIPE_HEADER_BYTES
                + 2u * MAPGEN_RECIPE_SNAPSHOT_BYTES
                + 4u * MAPGEN_RECIPE_CONTROL_BYTES, "");

    mapgen_recipe_t *r = NULL;
    mapgen_recipe_result_t rc = MapGenRecipe_Open(image, size, &r);
    check("it reads back", rc == MAPGEN_RECIPE_OK, MapGenRecipe_ResultName(rc));
    if (!r)
        return 1;

    /* --- everything survived the round trip ------------------------------- */
    check("the seed survives exactly",
          MapGenRecipe_Seed(r) == 0x0123456789ABCDEFull, "");
    check("so do the type and the goal",
          MapGenRecipe_Type(r) == MAPGEN_GEN_AUTO
          && MapGenRecipe_Goal(r) == MAPGEN_GOAL_FFA, "");
    check("and the resolved envelope",
          MapGenRecipe_PlayersMin(r) == 2 && MapGenRecipe_PlayersMax(r) == 16, "");
    check("and the attempt limit",
          MapGenRecipe_AttemptLimit(r) == 32, "");
    check("and the display name, which may be anything printable",
          MapGenRecipe_DisplayName(r)
          && !strcmp(MapGenRecipe_DisplayName(r), "Test Map"), "");
    check("and the slug",
          MapGenRecipe_Slug(r) && !strcmp(MapGenRecipe_Slug(r), "test_map"), "");
    check("both snapshot pins are there",
          MapGenRecipe_NumSnapshots(r) == 2, "");
    check("and all four controls",
          MapGenRecipe_NumControls(r) == 4, "");

    /* --- requested and resolved are different things ---------------------- */
    {
        const mapgen_recipe_control_t *quad = MapGenRecipe_Control(r, "item_quad");
        check("an Auto request is stored as Auto",
              quad && quad->requested == MAPGEN_RECIPE_AUTO, "");
        check("and its resolved value is a real number",
              quad && quad->resolved == 1, "");

        const mapgen_recipe_control_t *bfg = MapGenRecipe_Control(r, "weapon_bfg");
        check("an explicit Custom 0 survives as zero, not as Auto",
              bfg && bfg->requested == 0 && bfg->resolved == 0,
              "contract 13: Custom 0 means none and is a hard constraint");
        check("and zero is not the same value as Auto",
              MAPGEN_RECIPE_AUTO != 0,
              "the one confusion this type exists to prevent");

        check("the generator is handed the resolved value",
              MapGenRecipe_ResolvedValue(r, "item_quad", -1) == 1, "");
        check("and a fallback for a control the recipe never had",
              MapGenRecipe_ResolvedValue(r, "item_nonexistent", -7) == -7, "");
    }

    /* --- canonical order -------------------------------------------------- */
    {
        bool sorted = true;
        for (uint32_t i = 1; i < MapGenRecipe_NumControls(r); i++)
            if (strcmp(MapGenRecipe_ControlAt(r, i - 1)->key,
                       MapGenRecipe_ControlAt(r, i)->key) >= 0)
                sorted = false;
        check("controls come back in canonical order", sorted, "");

        /* The same content, added in a different order. */
        mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
        uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
        fill(uuid, sizeof(uuid), 0xA1);
        MapGenRecipe_SetIdentity(b, uuid, 0x0123456789ABCDEFull);
        MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA, 2, 16, 32, 1);
        MapGenRecipe_SetOutput(b, "Test Map", "test_map");
        uint8_t materials[MAPGEN_SHA256_BYTES];
        fill(materials, sizeof(materials), 0xC0);
        MapGenRecipe_SetMaterialTable(b, materials);
        const mapgen_recipe_toolchain_t t = sample_toolchain(0);
        MapGenRecipe_SetToolchain(b, &t);

        mapgen_recipe_snapshot_t snap;
        memset(&snap, 0, sizeof(snap));
        fill(snap.revision_uuid, sizeof(snap.revision_uuid), 0x03);
        fill(snap.payload_sha256, sizeof(snap.payload_sha256), 0x04);
        snap.weight = 50;
        MapGenRecipe_AddSnapshot(b, &snap);
        fill(snap.revision_uuid, sizeof(snap.revision_uuid), 0x01);
        fill(snap.payload_sha256, sizeof(snap.payload_sha256), 0x02);
        snap.weight = 50;
        MapGenRecipe_AddSnapshot(b, &snap);

        MapGenRecipe_AddControl(b, "weapon_bfg", 0, 0);
        MapGenRecipe_AddControl(b, "arch_water", MAPGEN_RECIPE_AUTO, 2);
        MapGenRecipe_AddControl(b, "item_health", 12, 12);
        MapGenRecipe_AddControl(b, "item_quad", MAPGEN_RECIPE_AUTO, 1);

        uint8_t *other_image = NULL;
        size_t other_size = 0;
        const mapgen_recipe_result_t fr =
            MapGenRecipe_Finish(b, &other_image, &other_size);
        MapGenRecipe_BuilderFree(b);
        check("the same content in a different order serializes",
              fr == MAPGEN_RECIPE_OK, MapGenRecipe_ResultName(fr));
        check("to the very same bytes",
              other_image && other_size == size
              && !memcmp(other_image, image, size),
              "the order the user clicked in is not part of the recipe");
        free(other_image);
    }

    /* --- what the builder refuses ----------------------------------------- */
    {
        mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
        uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
        fill(uuid, sizeof(uuid), 0xB2);
        MapGenRecipe_SetIdentity(b, uuid, 1);

        check("a duel that did not resolve to exactly two is refused",
              MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_DUEL,
                                      2, 8, 32, 0)
              == MAPGEN_RECIPE_ERR_BAD_ENVELOPE,
              "contract 12: 1v1 resolves to exactly 2");
        check("and single player that did not resolve to one",
              MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_SINGLE_PLAYER,
                                      1, 4, 32, 0)
              == MAPGEN_RECIPE_ERR_BAD_ENVELOPE, "");
        check("and a team game with an odd envelope",
              MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_TDM,
                                      5, 16, 32, 0)
              == MAPGEN_RECIPE_ERR_BAD_ENVELOPE,
              "contract 12: TDM resolves an even envelope within 4..32");
        check("an envelope past the engine's own limit",
              MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA,
                                      2, 64, 32, 0)
              == MAPGEN_RECIPE_ERR_BAD_ENVELOPE, "");
        check("an attempt limit outside 1..256",
              MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA,
                                      2, 16, 0, 0)
              == MAPGEN_RECIPE_ERR_BAD_ATTEMPTS
              && MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA,
                                         2, 16, 257, 0)
                 == MAPGEN_RECIPE_ERR_BAD_ATTEMPTS,
              "contract 16's Advanced 1..256");
        check("and both ends of that range are accepted",
              MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA,
                                      2, 16, 1, 0) == MAPGEN_RECIPE_OK
              && MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA,
                                         2, 16, 256, 0) == MAPGEN_RECIPE_OK, "");

        static const char *unsafe[] = {
            "maps/evil", "..", "../evil", "c:evil", "evil.bsp", "evil;map",
            "evil\"map", "EvilMap", "evil map", "",
        };
        bool all_refused = true;
        for (size_t i = 0; i < sizeof(unsafe) / sizeof(unsafe[0]); i++)
            if (MapGenRecipe_SetOutput(b, "Name", unsafe[i]) != MAPGEN_RECIPE_ERR_BAD_SLUG)
                all_refused = false;
        check("every unsafe slug is refused, including `..` and drive syntax",
              all_refused, "contract 22's rules, applied where the slug is set");
        check("a safe slug is accepted",
              MapGenRecipe_SetOutput(b, "Name", "q2mg_test_1") == MAPGEN_RECIPE_OK, "");
        check("a display name with a control byte is refused",
              MapGenRecipe_SetOutput(b, "Bad\nName", "ok_slug")
              == MAPGEN_RECIPE_ERR_BAD_NAME, "");
        check("a Russian display name is accepted",
              MapGenRecipe_SetOutput(b, "\xD0\x9A\xD0\xB0\xD1\x80\xD1\x82\xD0\xB0",
                                     "ok_slug") == MAPGEN_RECIPE_OK,
              "the name is a label, not a path");

        mapgen_recipe_snapshot_t snap;
        memset(&snap, 0, sizeof(snap));
        fill(snap.revision_uuid, sizeof(snap.revision_uuid), 0x01);
        snap.weight = 0;
        check("a zero weight is refused",
              MapGenRecipe_AddSnapshot(b, &snap) == MAPGEN_RECIPE_ERR_BAD_WEIGHT, "");
        snap.weight = 101;
        check("and one past a hundred",
              MapGenRecipe_AddSnapshot(b, &snap) == MAPGEN_RECIPE_ERR_BAD_WEIGHT, "");
        snap.weight = 50;
        check("a first snapshot is accepted",
              MapGenRecipe_AddSnapshot(b, &snap) == MAPGEN_RECIPE_OK, "");
        check("the same revision twice is refused",
              MapGenRecipe_AddSnapshot(b, &snap)
              == MAPGEN_RECIPE_ERR_DUPLICATE_SNAPSHOT, "");

        check("a control with an unresolved value is refused",
              MapGenRecipe_AddControl(b, "item_quad", MAPGEN_RECIPE_AUTO,
                                      MAPGEN_RECIPE_AUTO)
              == MAPGEN_RECIPE_ERR_UNRESOLVED,
              "a recipe that has run has no Auto left in it");
        check("a first control is accepted",
              MapGenRecipe_AddControl(b, "item_quad", MAPGEN_RECIPE_AUTO, 1)
              == MAPGEN_RECIPE_OK, "");
        check("the same key twice is refused, not overwritten",
              MapGenRecipe_AddControl(b, "item_quad", 3, 3)
              == MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL,
              "a control that can be overwritten depends on call order");
        check("and an unprintable key",
              MapGenRecipe_AddControl(b, "Item Quad", 1, 1)
              == MAPGEN_RECIPE_ERR_BAD_KEY, "");

        MapGenRecipe_BuilderFree(b);
    }

    /* --- a recipe with no snapshot is not a recipe ------------------------- */
    {
        mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
        uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
        fill(uuid, sizeof(uuid), 0xC3);
        MapGenRecipe_SetIdentity(b, uuid, 1);
        MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_MIX, 2, 8, 8, 0);
        MapGenRecipe_SetOutput(b, "No Snapshots", "no_snapshots");
        uint8_t *bytes = NULL;
        size_t bytes_size = 0;
        check("a recipe with no source at all is refused",
              MapGenRecipe_Finish(b, &bytes, &bytes_size)
              == MAPGEN_RECIPE_ERR_NO_SOURCE,
              "a snapshot, a donor, or both - a recipe with neither describes "
              "no input");
        check("and nothing was allocated for it", bytes == NULL, "");
        MapGenRecipe_BuilderFree(b);
    }

    /* A fork has no snapshots at all: the donor IS its input, and a record
       that could not describe one would be a record of the generation this
       product does not ship. */
    {
        mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
        uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
        uint8_t donor_hash[MAPGEN_SHA256_BYTES];
        fill(uuid, sizeof(uuid), 0xD0);
        fill(donor_hash, sizeof(donor_hash), 0xD1);
        MapGenRecipe_SetIdentity(b, uuid, 75);
        MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA, 2, 8, 8, 0);
        MapGenRecipe_SetOutput(b, "A Fork", "a_fork");
        check("a donor is accepted",
              MapGenRecipe_SetDonor(b, "q2dm1.bsp", donor_hash)
              == MAPGEN_RECIPE_OK, "");
        check("an empty donor name is not",
              MapGenRecipe_SetDonor(b, "", donor_hash)
              == MAPGEN_RECIPE_ERR_BAD_NAME, "");

        uint8_t *bytes = NULL;
        size_t bytes_size = 0;
        check("a fork with no snapshots is a complete recipe",
              MapGenRecipe_Finish(b, &bytes, &bytes_size) == MAPGEN_RECIPE_OK,
              "");
        mapgen_recipe_t *back = NULL;
        if (bytes && MapGenRecipe_Open(bytes, bytes_size, &back)
            == MAPGEN_RECIPE_OK) {
            check("and it names the map it forked",
                  !strcmp(MapGenRecipe_Donor(back), "q2dm1.bsp"),
                  MapGenRecipe_Donor(back));
            check("with the digest of the file that was read",
                  MapGenRecipe_DonorHash(back)
                  && !memcmp(MapGenRecipe_DonorHash(back), donor_hash,
                             MAPGEN_SHA256_BYTES),
                  "a map that changed under the same name is a different "
                  "input");
            check("and the seed that produced it",
                  MapGenRecipe_Seed(back) == 75, "");
            MapGenRecipe_Free(back);
        } else {
            check("a fork recipe reads back", false, "");
        }
        free(bytes);
        MapGenRecipe_BuilderFree(b);
    }

    /* --- damaged files ---------------------------------------------------- */
    {
        /* Truncated at every length. */
        bool all_refused = true;
        size_t accepted_at = 0;
        for (size_t n = 0; n < size; n++) {
            mapgen_recipe_t *bad = NULL;
            if (MapGenRecipe_Open(image, n, &bad) == MAPGEN_RECIPE_OK) {
                all_refused = false;
                accepted_at = n;
                MapGenRecipe_Free(bad);
                break;
            }
        }
        char detail[64];
        snprintf(detail, sizeof(detail), "accepted a %zu-byte prefix", accepted_at);
        check("no truncation of the file is accepted", all_refused, detail);

        /* One bit flipped at every offset. */
        uint8_t *copy = malloc(size);
        bool every_flip_refused = true;
        size_t survived_at = 0;
        if (copy) {
            for (size_t i = 0; i < size; i++) {
                memcpy(copy, image, size);
                copy[i] ^= 0x01;
                mapgen_recipe_t *bad = NULL;
                if (MapGenRecipe_Open(copy, size, &bad) == MAPGEN_RECIPE_OK) {
                    every_flip_refused = false;
                    survived_at = i;
                    MapGenRecipe_Free(bad);
                    break;
                }
            }
            free(copy);
        }
        snprintf(detail, sizeof(detail), "a flip at offset %zu was accepted",
                 survived_at);
        check("one flipped bit anywhere in the file is refused",
              every_flip_refused, detail);
    }

    /* --- specific refusals, so the reason is right too -------------------- */
    {
        uint8_t *copy = malloc(size);
        mapgen_recipe_t *bad = NULL;
        if (copy) {
            memcpy(copy, image, size);
            copy[0] = 'X';
            check("a file with the wrong magic says so",
                  MapGenRecipe_Open(copy, size, &bad)
                  == MAPGEN_RECIPE_ERR_BAD_MAGIC, "");

            memcpy(copy, image, size);
            copy[8] = 9;
            check("a future schema major is refused as unsupported",
                  MapGenRecipe_Open(copy, size, &bad)
                  == MAPGEN_RECIPE_ERR_UNSUPPORTED_MAJOR, "");

            memcpy(copy, image, size);
            copy[14] = 1;
            check("a reserved byte that is not zero is refused",
                  MapGenRecipe_Open(copy, size, &bad)
                  == MAPGEN_RECIPE_ERR_RESERVED_NOT_ZERO,
                  "it is how a later version will be told apart");

            memcpy(copy, image, size);
            copy[316] ^= 0xFF;
            check("a checksum that does not describe the file is refused",
                  MapGenRecipe_Open(copy, size, &bad)
                  == MAPGEN_RECIPE_ERR_BAD_CRC, "");

            /* The tables ARE covered: change a control's resolved value and
               fix nothing else. */
            memcpy(copy, image, size);
            copy[size - 1] ^= 0x40;
            check("and so is a change to a control the header never mentions",
                  MapGenRecipe_Open(copy, size, &bad) == MAPGEN_RECIPE_ERR_BAD_CRC,
                  "the checksum covers both tables, not just the header");

            check("nothing is handed back by any of them", bad == NULL, "");
            free(copy);
        }
    }

    /* --- well-formed files that say forbidden things ---------------------- */
    {
        uint8_t *copy = malloc(size);
        mapgen_recipe_t *bad = NULL;
        if (copy) {
            /* Two controls with the same key, and a checksum that agrees. */
            memcpy(copy, image, size);
            memcpy(copy + control_at(2, 1), copy + control_at(2, 0),
                   MAPGEN_RECIPE_KEY_BYTES);
            refresh_crc(copy, size);
            check("a file carrying one control twice is refused",
                  MapGenRecipe_Open(copy, size, &bad)
                  == MAPGEN_RECIPE_ERR_DUPLICATE_CONTROL,
                  "the checksum is valid; it is the content that is not");

            /* A control that was never resolved, and a checksum that agrees. */
            memcpy(copy, image, size);
            const size_t resolved_at = control_at(2, 0) + 44;
            copy[resolved_at + 0] = 0x00;
            copy[resolved_at + 1] = 0x00;
            copy[resolved_at + 2] = 0x00;
            copy[resolved_at + 3] = 0x80;
            refresh_crc(copy, size);
            check("and one whose control was never resolved",
                  MapGenRecipe_Open(copy, size, &bad)
                  == MAPGEN_RECIPE_ERR_UNRESOLVED,
                  "the file came from a disk, not from this process");

            /* A snapshot weight outside 1..100, checksum agreeing. */
            memcpy(copy, image, size);
            const size_t weight_at = (size_t)MAPGEN_RECIPE_HEADER_BYTES + 48;
            memset(copy + weight_at, 0, 4);
            refresh_crc(copy, size);
            check("and one whose snapshot weight is out of range",
                  MapGenRecipe_Open(copy, size, &bad)
                  == MAPGEN_RECIPE_ERR_BAD_WEIGHT, "");

            check("none of them handed anything back", bad == NULL, "");
            free(copy);
        }

        /* Bytes appended after the tables: the file is no longer the size it
           says it is, and that is its own answer, not a checksum failure. */
        uint8_t *longer = malloc(size + 16);
        if (longer) {
            memcpy(longer, image, size);
            memset(longer + size, 0, 16);
            check("a file with slack after its tables says its size is wrong",
                  MapGenRecipe_Open(longer, size + 16, &bad)
                  == MAPGEN_RECIPE_ERR_BAD_FILE_BYTES, "");
            free(longer);
        }
    }

    /* --- reuse ------------------------------------------------------------ */
    {
        const mapgen_recipe_toolchain_t same = sample_toolchain(0);
        const char *which = "unset";
        check("an unchanged toolchain may rerun",
              MapGenRecipe_CheckReuse(r, &same, &which) == MAPGEN_REUSE_OK
              && which == NULL, "");

        struct { const char *name; int part; } parts[] = {
            { "generator", 0 }, { "compiler", 1 },
            { "entity_schema", 2 }, { "physics_profile", 3 },
        };
        bool all_migrate = true, all_named = true;
        for (size_t i = 0; i < 4; i++) {
            mapgen_recipe_toolchain_t changed = sample_toolchain(0);
            switch (parts[i].part) {
            case 0: changed.generator_version++; break;
            case 1: changed.compiler_build_sha256[7] ^= 0xFF; break;
            case 2: changed.entity_schema_sha256[7] ^= 0xFF; break;
            case 3: changed.physics_profile_sha256[7] ^= 0xFF; break;
            }
            which = NULL;
            if (MapGenRecipe_CheckReuse(r, &changed, &which)
                != MAPGEN_REUSE_NEEDS_MIGRATION)
                all_migrate = false;
            if (!which || strcmp(which, parts[i].name))
                all_named = false;
        }
        check("each of the four pinned components blocks a rerun when it changes",
              all_migrate, "five of six agreeing proves nothing");
        check("and the report says which one", all_named, "");

        bool all_unavailable = true;
        for (size_t i = 0; i < 4; i++) {
            mapgen_recipe_toolchain_t missing = sample_toolchain(0);
            switch (parts[i].part) {
            case 0: missing.generator_version = 0; break;
            case 1: memset(missing.compiler_build_sha256, 0, MAPGEN_SHA256_BYTES); break;
            case 2: memset(missing.entity_schema_sha256, 0, MAPGEN_SHA256_BYTES); break;
            case 3: memset(missing.physics_profile_sha256, 0, MAPGEN_SHA256_BYTES); break;
            }
            if (MapGenRecipe_CheckReuse(r, &missing, NULL)
                != MAPGEN_REUSE_UNAVAILABLE_VERSION)
                all_unavailable = false;
        }
        check("a component that could not be read is UNAVAILABLE, not a match",
              all_unavailable,
              "an all-zero hash is what a failed read looks like");

        check("and no toolchain at all is UNAVAILABLE too",
              MapGenRecipe_CheckReuse(r, NULL, NULL)
              == MAPGEN_REUSE_UNAVAILABLE_VERSION, "");
    }

    /* --- the canonical digest --------------------------------------------- */
    {
        const uint64_t digest = MapGenRecipe_CanonicalDigest(r);
        mapgen_recipe_t *again = NULL;
        MapGenRecipe_Open(image, size, &again);
        check("the same file gives the same digest",
              again && MapGenRecipe_CanonicalDigest(again) == digest, "");
        MapGenRecipe_Free(again);

        size_t n = MapGenRecipe_CanonicalText(r, NULL, 0);
        char *text = malloc(n + 1);
        if (text) {
            MapGenRecipe_CanonicalText(r, text, n + 1);
            check("the canonical text names the seed and the goal",
                  strstr(text, "seed=81985529216486895") != NULL
                  && strstr(text, "goal=ffa") != NULL, "");
            check("and renders an Auto request as Auto, not as a number",
                  strstr(text, "c=item_quad,auto,1") != NULL, "");
            check("and an explicit zero as zero",
                  strstr(text, "c=weapon_bfg,0,0") != NULL, "");
            free(text);
        }
    }

    MapGenRecipe_Free(r);
    free(image);

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}
