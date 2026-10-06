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

MAPGEN-1 - MapGenStore: the durable snapshot commit

Contract section 8's commit transaction and section 20's `RECOVERING` /
`RECOVERY_REQUIRED` contract.

--- The commit point is one filesystem operation ------------------------------

Write `<final>.tmp`, flush it to the disk, close it, read it back, verify it is
byte-for-byte what was meant AND that its payload hash still describes it, and
only then create the final path with NO-REPLACE semantics. That last step is
atomic and is the commit point: before it nothing has happened, after it the
revision exists. `COMMITTING_SNAPSHOT` is noncancellable because there is
nothing in the middle to cancel.

No-replace is not an optimisation. An existing revision is immutable and is
never overwritten, never replaced and never automatically deleted - contract 8
says so three times in different words, and section 20 adds that snapshots are
user data.

--- Binary mode is part of the contract, not a detail -------------------------

Everything here is byte-exact: the payload hash, the read-back comparison, the
journal's own hash. A file opened in text mode on Windows turns every 0x0A it
writes into 0x0D 0x0A, which silently destroys all three.

This is Hard Rule #51 in this project's own history: a transaction with a
byte-identity read-back once passed six failure stages and fifteen controlled
REDs and still never saved a single time, because production opened the file
in text mode. A seam proves the algorithm; it cannot prove the call. So the
guard checks the open flags STATICALLY, at the call site, with its own RED.

--- What recovery may and may not conclude ------------------------------------

  journal + final revision present, identity and payload hash match
      -> SUCCEEDED, finish the catalog pointer by compare-and-swap
  journal + no final revision
      -> FAILED, and no snapshot exists. Nothing to clean up but the temp file
  journal + final revision present with a DIFFERENT identity
      -> RECOVERY_REQUIRED. Someone else's file is at that path and it is not
         ours to touch
  catalog moved under us (its hash is not the one the journal recorded)
      -> RECOVERY_REQUIRED

Recovery never deletes or overwrites a committed revision, and never resolves
a conflict by guessing.

==============================================================================
*/

#pragma once

#include "common/mapgen_snapshot.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_STORE_PATH_BYTES  1024

typedef enum {
    MAPGEN_STORE_OK = 0,
    MAPGEN_STORE_ERR_ARGS,
    MAPGEN_STORE_ERR_MEMORY,
    MAPGEN_STORE_ERR_PATH_TOO_LONG,
    /* The final path already exists. Never an overwrite. */
    MAPGEN_STORE_ERR_ALREADY_EXISTS,
    MAPGEN_STORE_ERR_WRITE_FAILED,
    MAPGEN_STORE_ERR_FLUSH_FAILED,
    /* What came back off the disk is not what was written. */
    MAPGEN_STORE_ERR_READBACK_MISMATCH,
    /* It came back intact but no longer describes itself. */
    MAPGEN_STORE_ERR_PAYLOAD_MISMATCH,
    MAPGEN_STORE_ERR_JOURNAL_FAILED,
    MAPGEN_STORE_ERR_COMMIT_FAILED,
    /* The catalog is not the one the journal recorded. */
    MAPGEN_STORE_ERR_CATALOG_MOVED,
    /* Deletion, which is the only thing here that destroys user data. */
    MAPGEN_STORE_ERR_NOT_CONFIRMED,
    MAPGEN_STORE_ERR_STILL_REFERENCED,
    MAPGEN_STORE_ERR_IDENTITY_CHANGED,
    MAPGEN_STORE_ERR_NOT_FOUND,
    MAPGEN_STORE_ERR_DELETE_FAILED,

    MAPGEN_STORE_RESULT_COUNT
} mapgen_store_result_t;

const char *MapGenStore_ResultName(mapgen_store_result_t r);

/*
 * What a journal describes. Delete is a different transaction from Commit -
 * contract 8 makes it "distinct" and "explicit user-authorized" - and recovery
 * has to know which one it is looking at before it does anything.
 */
typedef enum {
    MAPGEN_JOURNAL_COMMIT = 1,
    MAPGEN_JOURNAL_DELETE_PENDING = 2,
} mapgen_journal_kind_t;

const char *MapGenStore_JournalKindName(mapgen_journal_kind_t kind);

typedef enum {
    MAPGEN_RECOVERY_SUCCEEDED = 0,
    MAPGEN_RECOVERY_FAILED,
    MAPGEN_RECOVERY_REQUIRED,
    MAPGEN_RECOVERY_NOTHING_TO_DO,
} mapgen_recovery_t;

const char *MapGenStore_RecoveryName(mapgen_recovery_t r);

/*
 * What the journal records before the commit point, and what recovery reads
 * back afterwards. Contract 8 names every field: the final revision path, the
 * revision UUID, the payload hash and the previous catalog hash it validated.
 */
typedef struct {
    char     final_path[MAPGEN_STORE_PATH_BYTES];
    char     catalog_path[MAPGEN_STORE_PATH_BYTES];
    uint8_t  revision_uuid[MAPGEN_SNAPSHOT_UUID_BYTES];
    uint8_t  payload_sha256[MAPGEN_SHA256_BYTES];
    uint8_t  previous_catalog_sha256[MAPGEN_SHA256_BYTES];
    uint64_t image_bytes;
    uint32_t kind;                /* mapgen_journal_kind_t */
    /* How many Projects pin this revision. A deletion with any is refused:
       contract 20 makes snapshots user data, and a Project that pins one is
       the user saying they still want it. */
    uint32_t project_references;
} mapgen_store_plan_t;

/*
 * Commit one snapshot image.
 *
 * `journal_path` is written durably BEFORE the commit point, so a crash at any
 * moment leaves a record of what was being attempted. On success the journal is
 * removed, because a completed transaction has nothing left to recover.
 */
mapgen_store_result_t MapGenStore_Commit(const mapgen_store_plan_t *plan,
                                         const char *journal_path,
                                         const uint8_t *image, size_t size);

/*
 * Write a journal record durably.
 *
 * Public because the commit is not the only thing that needs it: recovery has
 * to be testable against journals describing states no successful commit ever
 * produces - a revision that was never written, a path now holding somebody
 * else's file, a catalog that moved. Constructing those states directly is
 * both safer and more precise than killing a process mid-write and hoping it
 * stopped in the right place.
 */
mapgen_store_result_t MapGenStore_WriteJournal(const char *journal_path,
                                               const mapgen_store_plan_t *plan);

/* Read a journal back. False when there is none, or it is unreadable. */
bool MapGenStore_ReadJournal(const char *journal_path, mapgen_store_plan_t *out);

/*
 * Decide what an interrupted transaction became, and finish it if it can be
 * finished. Never deletes or overwrites a committed revision.
 */
mapgen_recovery_t MapGenStore_Recover(const char *journal_path);

/* The catalog is a list of committed revision paths, one per line. It is
   replaced only by compare-and-swap against the hash the caller last read. */
mapgen_store_result_t MapGenStore_CatalogHash(const char *catalog_path,
                                              uint8_t out[MAPGEN_SHA256_BYTES]);

/* --- deletion ----------------------------------------------------------- */

/*
 * Pin exactly what is about to be deleted.
 *
 * Opens the revision and reads its identity out of the file itself rather than
 * taking the caller's word for it, so the confirmation the user gives is about
 * the file that is actually there. `project_references` is what the caller
 * knows about Projects pinning this revision; the deletion refuses on any.
 */
mapgen_store_result_t MapGenStore_PreflightDelete(const char *final_path,
                                                  const char *catalog_path,
                                                  uint32_t project_references,
                                                  mapgen_store_plan_t *out);

/*
 * Delete one pinned revision.
 *
 * `confirmed` is the user's second confirmation and is not a formality: the
 * call refuses without it. The commit point is the DeletePending journal
 * record, after which the transaction is noncancellable; before it, nothing
 * has happened.
 *
 * The file is re-opened and its identity re-checked against the pin
 * immediately before removal, so a revision that was replaced between the
 * preflight and the confirmation is never the one that gets deleted.
 */
mapgen_store_result_t MapGenStore_Delete(const mapgen_store_plan_t *plan,
                                         const char *journal_path,
                                         bool confirmed);
