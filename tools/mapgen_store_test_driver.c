/*
 * MAPGEN-1 durable store test driver.
 *
 * Compiled and run by tools/check_mapgen_store_contract.py.
 *
 *   driver run <workdir>
 *
 * Every interrupted-commit state is CONSTRUCTED on disk rather than produced by
 * killing a process mid-write. That is deliberate on two counts: a test that
 * spawns and kills processes is the pattern that has already cost this project
 * a desktop reboot, and constructing the state directly is more precise - the
 * exact situation under test is the one that exists, with no timing to get
 * lucky with.
 */

#include "common/mapgen_store.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <windows.h>

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

/* ------------------------------------------------------------------------ */

static uint8_t *make_image(uint8_t revision_byte, size_t *out_size,
                           uint8_t out_payload[MAPGEN_SHA256_BYTES])
{
    mapgen_snapshot_builder_t *b = MapGenSnapshot_BuilderCreate();
    if (!b)
        return NULL;
    /*
     * Every chunk the schema requires, not the seven it required when this
     * driver was written. Schema 3 added SHAPES and GEOMETRY; a builder that
     * stops at QUALITY produces nothing, and the store then refuses an empty
     * image with ERR_ARGS - which reads like a broken store and is a stale
     * test.
     */
    for (uint32_t i = MAPGEN_CHUNK_META; i <= MAPGEN_CHUNK_GEOMETRY; i++) {
        char body[128];
        snprintf(body, sizeof(body), "chunk=%u revision=%u\n", i, revision_byte);
        if (MapGenSnapshot_AddChunk(b, i, body, strlen(body),
                                    MAPGEN_COMPRESSION_NONE) != MAPGEN_SNAPSHOT_OK) {
            MapGenSnapshot_BuilderFree(b);
            return NULL;
        }
    }
    uint8_t uuid[MAPGEN_SNAPSHOT_UUID_BYTES];
    memset(uuid, revision_byte, sizeof(uuid));
    MapGenSnapshot_SetIdentity(b, uuid, uuid, NULL);
    MapGenSnapshot_BuilderPayloadHash(b, out_payload);

    uint8_t *bytes = NULL;
    if (MapGenSnapshot_Finish(b, &bytes, out_size) != MAPGEN_SNAPSHOT_OK)
        bytes = NULL;
    MapGenSnapshot_BuilderFree(b);
    return bytes;
}

static void plan_for(mapgen_store_plan_t *plan, const char *dir, const char *name,
                     uint8_t revision_byte,
                     const uint8_t payload[MAPGEN_SHA256_BYTES], size_t size)
{
    memset(plan, 0, sizeof(*plan));
    snprintf(plan->final_path, sizeof(plan->final_path), "%s/%s", dir, name);
    snprintf(plan->catalog_path, sizeof(plan->catalog_path), "%s/catalog.txt", dir);
    memset(plan->revision_uuid, revision_byte, MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(plan->payload_sha256, payload, MAPGEN_SHA256_BYTES);
    MapGenStore_CatalogHash(plan->catalog_path, plan->previous_catalog_sha256);
    plan->image_bytes = size;
}

static bool exists(const char *path)
{
    return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES;
}

static char *slurp(const char *path, size_t *out_size)
{
    *out_size = 0;
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    rewind(f);
    char *data = malloc((size_t)(n > 0 ? n : 0) + 1);
    if (!data) { fclose(f); return NULL; }
    const size_t got = fread(data, 1, (size_t)(n > 0 ? n : 0), f);
    fclose(f);
    data[got] = '\0';
    *out_size = got;
    return data;
}

static void spill(const char *path, const void *data, size_t size)
{
    FILE *f = fopen(path, "wb");
    if (!f)
        return;
    if (size)
        fwrite(data, 1, size, f);
    fclose(f);
}

static bool catalog_names(const char *catalog, const char *needle)
{
    size_t size = 0;
    char *text = slurp(catalog, &size);
    const bool found = text && strstr(text, needle) != NULL;
    free(text);
    return found;
}

/* ------------------------------------------------------------------------ */

int main(int argc, char **argv)
{
    if (argc < 3 || strcmp(argv[1], "run")) {
        printf("usage\n");
        return 2;
    }
    const char *dir = argv[2];

    char journal[1024], catalog[1024];
    snprintf(journal, sizeof(journal), "%s/commit.journal", dir);
    snprintf(catalog, sizeof(catalog), "%s/catalog.txt", dir);

    /* --- the happy path -------------------------------------------------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0x11, &size, payload);
        mapgen_store_plan_t plan;
        plan_for(&plan, dir, "rev1.q2mgdb", 0x11, payload, size);

        const mapgen_store_result_t r = MapGenStore_Commit(&plan, journal, image, size);
        check("a first commit succeeds", r == MAPGEN_STORE_OK,
              MapGenStore_ResultName(r));
        check("the revision exists at its final path", exists(plan.final_path), "");

        char temp[1100];
        snprintf(temp, sizeof(temp), "%s.tmp", plan.final_path);
        check("no temporary file is left behind", !exists(temp), "");
        check("the journal is gone once the transaction completes",
              !exists(journal), "");
        check("the catalog names the new revision",
              catalog_names(catalog, "rev1.q2mgdb"), "");

        /* Committing the same path again must not touch what is there. */
        size_t before = 0;
        char *snapshot_before = slurp(plan.final_path, &before);
        const mapgen_store_result_t again = MapGenStore_Commit(&plan, journal, image, size);
        check("committing over an existing revision is refused",
              again == MAPGEN_STORE_ERR_ALREADY_EXISTS,
              MapGenStore_ResultName(again));
        size_t after = 0;
        char *snapshot_after = slurp(plan.final_path, &after);
        check("and the committed revision is byte-for-byte untouched",
              before && before == after && snapshot_before && snapshot_after &&
              !memcmp(snapshot_before, snapshot_after, before), "");
        check("a refused commit leaves no journal behind", !exists(journal), "");
        free(snapshot_before);
        free(snapshot_after);
        free(image);
    }

    /* --- a plan that lies about its payload ------------------------------ */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0x22, &size, payload);
        mapgen_store_plan_t plan;
        plan_for(&plan, dir, "liar.q2mgdb", 0x22, payload, size);
        plan.payload_sha256[0] ^= 0xFF;

        const mapgen_store_result_t r = MapGenStore_Commit(&plan, journal, image, size);
        check("a commit whose payload hash does not match is refused",
              r == MAPGEN_STORE_ERR_PAYLOAD_MISMATCH, MapGenStore_ResultName(r));
        check("nothing was published", !exists(plan.final_path), "");
        check("and no journal was left", !exists(journal), "");
        free(image);
    }

    /* --- crashed BEFORE the commit point --------------------------------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0x33, &size, payload);
        mapgen_store_plan_t plan;
        plan_for(&plan, dir, "never.q2mgdb", 0x33, payload, size);

        MapGenStore_WriteJournal(journal, &plan);
        check("the journal reads back", exists(journal), "");

        const mapgen_recovery_t rec = MapGenStore_Recover(journal);
        check("a journal with no revision recovers as FAILED",
              rec == MAPGEN_RECOVERY_FAILED, MapGenStore_RecoveryName(rec));
        check("no snapshot appeared", !exists(plan.final_path), "");
        check("and the journal is cleared, since nothing was published",
              !exists(journal), "");
        free(image);
    }

    /* --- crashed AFTER the commit point, before the catalog --------------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0x44, &size, payload);
        mapgen_store_plan_t plan;
        plan_for(&plan, dir, "orphan.q2mgdb", 0x44, payload, size);

        /* The revision exists; the catalog does not know about it yet. */
        spill(plan.final_path, image, size);
        MapGenStore_CatalogHash(catalog, plan.previous_catalog_sha256);
        MapGenStore_WriteJournal(journal, &plan);

        const mapgen_recovery_t rec = MapGenStore_Recover(journal);
        check("a committed revision with an unfinished catalog recovers as SUCCEEDED",
              rec == MAPGEN_RECOVERY_SUCCEEDED, MapGenStore_RecoveryName(rec));
        check("recovery finishes the catalog pointer",
              catalog_names(catalog, "orphan.q2mgdb"), "");
        check("the revision is still there", exists(plan.final_path), "");
        check("and the journal is cleared", !exists(journal), "");
        free(image);
    }

    /* --- somebody else's file is at that path ---------------------------- */
    {
        size_t mine_size = 0, theirs_size = 0;
        uint8_t mine_payload[MAPGEN_SHA256_BYTES], theirs_payload[MAPGEN_SHA256_BYTES];
        uint8_t *mine = make_image(0x55, &mine_size, mine_payload);
        uint8_t *theirs = make_image(0x66, &theirs_size, theirs_payload);

        mapgen_store_plan_t plan;
        plan_for(&plan, dir, "contested.q2mgdb", 0x55, mine_payload, mine_size);
        spill(plan.final_path, theirs, theirs_size);
        MapGenStore_CatalogHash(catalog, plan.previous_catalog_sha256);
        MapGenStore_WriteJournal(journal, &plan);

        size_t before = 0;
        char *before_bytes = slurp(plan.final_path, &before);

        const mapgen_recovery_t rec = MapGenStore_Recover(journal);
        check("a path holding another revision recovers as RECOVERY_REQUIRED",
              rec == MAPGEN_RECOVERY_REQUIRED, MapGenStore_RecoveryName(rec));

        size_t after = 0;
        char *after_bytes = slurp(plan.final_path, &after);
        check("the other revision is not touched",
              before && before == after && before_bytes && after_bytes &&
              !memcmp(before_bytes, after_bytes, before), "");
        check("the journal is kept, because the situation is unresolved",
              exists(journal), "");
        check("the catalog does not name it",
              !catalog_names(catalog, "contested.q2mgdb"), "");

        free(before_bytes);
        free(after_bytes);
        free(mine);
        free(theirs);
        DeleteFileA(journal);
    }

    /* --- the catalog moved under us --------------------------------------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0x77, &size, payload);
        mapgen_store_plan_t plan;
        plan_for(&plan, dir, "raced.q2mgdb", 0x77, payload, size);
        spill(plan.final_path, image, size);
        /* A stale previous-catalog hash: somebody else committed in between. */
        memset(plan.previous_catalog_sha256, 0xAB, MAPGEN_SHA256_BYTES);
        MapGenStore_WriteJournal(journal, &plan);

        const mapgen_recovery_t rec = MapGenStore_Recover(journal);
        check("a catalog that moved recovers as RECOVERY_REQUIRED",
              rec == MAPGEN_RECOVERY_REQUIRED, MapGenStore_RecoveryName(rec));
        check("the revision is left committed", exists(plan.final_path), "");
        check("and nothing was guessed into the catalog",
              !catalog_names(catalog, "raced.q2mgdb"), "");
        free(image);
        DeleteFileA(journal);
    }

    /* --- a torn journal --------------------------------------------------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0x88, &size, payload);
        mapgen_store_plan_t plan;
        plan_for(&plan, dir, "torn.q2mgdb", 0x88, payload, size);
        MapGenStore_WriteJournal(journal, &plan);

        size_t js = 0;
        char *journal_bytes = slurp(journal, &js);
        check("the journal was written", journal_bytes != NULL && js > 64, "");
        if (journal_bytes) {
            spill(journal, journal_bytes, js - 8);     /* truncated */
            mapgen_store_plan_t read_back;
            check("a truncated journal is refused, not half-believed",
                  !MapGenStore_ReadJournal(journal, &read_back), "");
            check("and recovery has nothing to do with it",
                  MapGenStore_Recover(journal) == MAPGEN_RECOVERY_NOTHING_TO_DO, "");

            /* One flipped bit anywhere in the record must be caught too. */
            journal_bytes[40] ^= 0x01;
            spill(journal, journal_bytes, js);
            check("a journal with one flipped bit is refused",
                  !MapGenStore_ReadJournal(journal, &read_back), "");
            journal_bytes[40] ^= 0x01;

            /* And one with the right prefix but trailing rubbish. A size test
               that only rejected SHORT records would decode this one and read
               its own fields from wherever the extra bytes put them. */
            char *longer = malloc(js + 16);
            if (longer) {
                memcpy(longer, journal_bytes, js);
                memset(longer + js, 0x5A, 16);
                spill(journal, longer, js + 16);
                check("a journal with trailing bytes is refused",
                      !MapGenStore_ReadJournal(journal, &read_back), "");
                free(longer);
            }
        }
        free(journal_bytes);
        free(image);
        DeleteFileA(journal);
    }

    /* --- no journal at all ------------------------------------------------ */
    {
        DeleteFileA(journal);
        check("with no journal there is nothing to recover",
              MapGenStore_Recover(journal) == MAPGEN_RECOVERY_NOTHING_TO_DO, "");
    }

    /* --- the journal round-trips exactly ---------------------------------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0x99, &size, payload);
        mapgen_store_plan_t plan, read_back;
        plan_for(&plan, dir, "roundtrip.q2mgdb", 0x99, payload, size);
        MapGenStore_WriteJournal(journal, &plan);
        const bool ok = MapGenStore_ReadJournal(journal, &read_back);
        check("a journal reads back", ok, "");
        check("with every field intact",
              ok && !strcmp(plan.final_path, read_back.final_path)
              && !strcmp(plan.catalog_path, read_back.catalog_path)
              && !memcmp(plan.revision_uuid, read_back.revision_uuid,
                         MAPGEN_SNAPSHOT_UUID_BYTES)
              && !memcmp(plan.payload_sha256, read_back.payload_sha256,
                         MAPGEN_SHA256_BYTES)
              && !memcmp(plan.previous_catalog_sha256,
                         read_back.previous_catalog_sha256, MAPGEN_SHA256_BYTES)
              && plan.image_bytes == read_back.image_bytes, "");
        free(image);
        DeleteFileA(journal);
    }

    /* --- deletion: the only thing here that destroys user data ----------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0xAA, &size, payload);
        mapgen_store_plan_t commit;
        plan_for(&commit, dir, "doomed.q2mgdb", 0xAA, payload, size);
        MapGenStore_Commit(&commit, journal, image, size);
        check("a revision to delete exists", exists(commit.final_path), "");

        mapgen_store_plan_t plan;
        mapgen_store_result_t r = MapGenStore_PreflightDelete(
            commit.final_path, catalog, 0, &plan);
        check("the preflight pins the revision", r == MAPGEN_STORE_OK,
              MapGenStore_ResultName(r));
        check("and reads its identity out of the file itself",
              !memcmp(plan.payload_sha256, payload, MAPGEN_SHA256_BYTES)
              && plan.revision_uuid[0] == 0xAA, "");
        check("and marks the transaction as a deletion",
              plan.kind == MAPGEN_JOURNAL_DELETE_PENDING,
              MapGenStore_JournalKindName((mapgen_journal_kind_t)plan.kind));

        /* Without the second confirmation, nothing happens at all. */
        r = MapGenStore_Delete(&plan, journal, false);
        check("deleting without confirmation is refused",
              r == MAPGEN_STORE_ERR_NOT_CONFIRMED, MapGenStore_ResultName(r));
        check("and the revision is still there", exists(commit.final_path), "");
        check("and no journal was written", !exists(journal), "");

        /* A Project pinning it is the user saying they still want it. */
        mapgen_store_plan_t referenced = plan;
        referenced.project_references = 1;
        r = MapGenStore_Delete(&referenced, journal, true);
        check("deleting a revision a Project pins is refused",
              r == MAPGEN_STORE_ERR_STILL_REFERENCED, MapGenStore_ResultName(r));
        check("and it is still there", exists(commit.final_path), "");

        /* Replaced between the confirmation and the deletion. */
        size_t other_size = 0;
        uint8_t other_payload[MAPGEN_SHA256_BYTES];
        uint8_t *other = make_image(0xBB, &other_size, other_payload);
        size_t kept = 0;
        char *kept_bytes = slurp(commit.final_path, &kept);
        spill(commit.final_path, other, other_size);
        r = MapGenStore_Delete(&plan, journal, true);
        check("a revision replaced since the preflight is not the one deleted",
              r == MAPGEN_STORE_ERR_IDENTITY_CHANGED, MapGenStore_ResultName(r));
        check("and the replacement survives", exists(commit.final_path), "");
        spill(commit.final_path, kept_bytes, kept);   /* put ours back */
        free(kept_bytes);
        free(other);

        /* And now, properly authorised. */
        MapGenStore_CatalogHash(catalog, plan.previous_catalog_sha256);
        r = MapGenStore_Delete(&plan, journal, true);
        check("a confirmed deletion of the pinned revision succeeds",
              r == MAPGEN_STORE_OK, MapGenStore_ResultName(r));
        check("the revision is gone", !exists(commit.final_path), "");
        check("the catalog no longer names it",
              !catalog_names(catalog, "doomed.q2mgdb"), "");
        check("and the journal is cleared", !exists(journal), "");
        check("other revisions are untouched by the deletion",
              catalog_names(catalog, "rev1.q2mgdb"), "");
        free(image);
    }

    /* --- an interrupted deletion ----------------------------------------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0xCC, &size, payload);
        mapgen_store_plan_t commit;
        plan_for(&commit, dir, "halfgone.q2mgdb", 0xCC, payload, size);
        MapGenStore_Commit(&commit, journal, image, size);

        mapgen_store_plan_t plan;
        MapGenStore_PreflightDelete(commit.final_path, catalog, 0, &plan);
        MapGenStore_WriteJournal(journal, &plan);

        /* Crashed after the journal, before the file was removed. */
        const mapgen_recovery_t rec = MapGenStore_Recover(journal);
        check("an interrupted deletion is completed by recovery",
              rec == MAPGEN_RECOVERY_SUCCEEDED, MapGenStore_RecoveryName(rec));
        check("the revision is gone", !exists(commit.final_path), "");
        check("the catalog no longer names it",
              !catalog_names(catalog, "halfgone.q2mgdb"), "");
        check("and the journal is cleared", !exists(journal), "");
        free(image);
    }

    /* --- an interrupted deletion whose file was already removed ---------- */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0xDD, &size, payload);
        mapgen_store_plan_t commit;
        plan_for(&commit, dir, "vanished.q2mgdb", 0xDD, payload, size);
        MapGenStore_Commit(&commit, journal, image, size);

        mapgen_store_plan_t plan;
        MapGenStore_PreflightDelete(commit.final_path, catalog, 0, &plan);
        MapGenStore_WriteJournal(journal, &plan);
        DeleteFileA(commit.final_path);

        const mapgen_recovery_t rec = MapGenStore_Recover(journal);
        check("an already-absent pending deletion counts as done",
              rec == MAPGEN_RECOVERY_SUCCEEDED, MapGenStore_RecoveryName(rec));
        check("and its tombstone is finished",
              !catalog_names(catalog, "vanished.q2mgdb"), "");
        free(image);
    }

    /* --- an interrupted deletion whose file was REPLACED ------------------ */
    {
        size_t size = 0;
        uint8_t payload[MAPGEN_SHA256_BYTES];
        uint8_t *image = make_image(0xEE, &size, payload);
        mapgen_store_plan_t commit;
        plan_for(&commit, dir, "swapped.q2mgdb", 0xEE, payload, size);
        MapGenStore_Commit(&commit, journal, image, size);

        mapgen_store_plan_t plan;
        MapGenStore_PreflightDelete(commit.final_path, catalog, 0, &plan);
        MapGenStore_WriteJournal(journal, &plan);

        size_t other_size = 0;
        uint8_t other_payload[MAPGEN_SHA256_BYTES];
        uint8_t *other = make_image(0xEF, &other_size, other_payload);
        spill(commit.final_path, other, other_size);

        const mapgen_recovery_t rec = MapGenStore_Recover(journal);
        check("a pending deletion whose file was replaced is RECOVERY_REQUIRED",
              rec == MAPGEN_RECOVERY_REQUIRED, MapGenStore_RecoveryName(rec));
        check("and the replacement is NOT deleted", exists(commit.final_path), "");
        check("the journal is kept for a human to resolve", exists(journal), "");
        free(other);
        free(image);
        DeleteFileA(journal);
    }

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}
