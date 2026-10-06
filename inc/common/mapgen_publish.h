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

MAPGEN-1 - publishing a Project, all of it or none of it

--- What was wrong --------------------------------------------------------

The old publication copied the map into the maps directory, then tried the
certificates, then tried the recipe, ignored whether either worked, and
returned success. It called `remove()` on the destination first, so a second
job with the same name silently replaced the first. And nothing recorded that
a set of files belonged together, so the client decided what was playable by
looking at filename prefixes - which is why roughly twenty-five driver and
fixture artifacts in the Release tree were being offered to the player as
generated maps.

A map with no evidence beside it is not a Project. A map that replaced another
is a Project the player did not agree to lose. A map that is visible before its
certificates are durable is a map that can be played while the proof that it
can be walked does not exist.

--- What this is ----------------------------------------------------------

One transaction with one visibility point.

    stage      every member is copied into a staging directory of its own,
               flushed, closed, READ BACK and hashed; the hash is compared
               with what was written, and with what the verdict declared
    reserve    every final name is checked, and a name already taken refuses
               the whole publication: nothing is ever overwritten
    commit     members move into place with a no-replace move, and then the
               MANIFEST moves last

The manifest is the commit point. Until it lands nothing is a Project, so a
crash at any earlier moment leaves files nobody will list or play; after it
lands the whole set is there, verified, with every hash written down. On any
failure the set is withdrawn - only ever the files this publication itself
created, never a Project that was already there.

`MapGenPublish_Verify` is what list and Play must ask. A loose BSP whose name
happens to start with a familiar prefix is a test artifact, not a Project, and
it answers false.

==============================================================================
*/

#ifndef MAPGEN_PUBLISH_H
#define MAPGEN_PUBLISH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_PUBLISH_PATH     512
#define MAPGEN_PUBLISH_NAME     64
#define MAPGEN_PUBLISH_ROLE     32
#define MAPGEN_PUBLISH_MEMBERS  8
#define MAPGEN_PUBLISH_HEX      65

typedef enum {
    MAPGEN_PUBLISH_OK = 0,

    MAPGEN_PUBLISH_ERR_ARGS,
    /* A member the caller declared is missing or cannot be read. */
    MAPGEN_PUBLISH_ERR_SOURCE,
    /* What was read back is not what was written, or not what the verdict
       said it would be. */
    MAPGEN_PUBLISH_ERR_HASH,
    /* The name is taken. The answer is a new Project identity, never an
       overwrite. */
    MAPGEN_PUBLISH_ERR_COLLISION,
    MAPGEN_PUBLISH_ERR_STAGE,
    MAPGEN_PUBLISH_ERR_COMMIT,
    /* Asked about something that is not a published Project. */
    MAPGEN_PUBLISH_ERR_NOT_A_PROJECT,
    MAPGEN_PUBLISH_ERR_MANIFEST,
    /* A name, role or member file that could become path syntax. */
    MAPGEN_PUBLISH_ERR_NAME,
    /* The receipt is missing, malformed, or does not describe this map. */
    MAPGEN_PUBLISH_ERR_RECEIPT,
    /* A role a Project must have, or one it must not have twice. */
    MAPGEN_PUBLISH_ERR_ROLE,

    /*
     * The Project verifies, and the bytes in hand are not its map.
     *
     * Kept apart from ERR_HASH, which is a file on disk disagreeing with its
     * manifest: this is the loader holding one thing while the manifest
     * describes another, which is the case a check made before the read can
     * never see.
     */
    MAPGEN_PUBLISH_ERR_NOT_THESE_BYTES,
    MAPGEN_PUBLISH_RESULT_COUNT
} mapgen_publish_result_t;

const char *MapGenPublish_ResultName(mapgen_publish_result_t r);

/*
 * The name every published Project starts with.
 *
 * One definition: the client used to carry its own copy, and a loader that
 * spelled it out again would be a third. What wears this prefix must answer to
 * a manifest; what does not is an ordinary map.
 */
#define MAPGEN_PUBLISH_PREFIX  "q2mg_"

typedef struct {
    /* What this file is to the Project: "map", "certificates", "recipe",
       "receipt". Recorded in the manifest, so what is missing can be named. */
    char role[MAPGEN_PUBLISH_ROLE];
    char source[MAPGEN_PUBLISH_PATH];
    /* Appended to the Project's name to make the published file name. */
    char suffix[MAPGEN_PUBLISH_ROLE];
    /* A required member that is missing refuses the publication. An optional
       one that EXISTS is still copied, hashed and recorded: an artifact that
       exists and does not travel is evidence nobody has. */
    bool required;
    /* What the verdict says this file's SHA-256 is, or empty. When it is
       given, a read-back that disagrees refuses the publication. */
    char declared_sha256[MAPGEN_PUBLISH_HEX];
} mapgen_publish_member_t;

typedef struct {
    char     maps_dir[MAPGEN_PUBLISH_PATH];
    /*
     * Where this job's artifacts live. Every member source must be inside it:
     * the paths come from a worker's summary, and a worker naming a file
     * outside its own directory is either broken or hostile - either way its
     * word is not a reason to copy that file into the player's maps.
     */
    char     job_dir[MAPGEN_PUBLISH_PATH];
    char     name[MAPGEN_PUBLISH_NAME];
    /* The job this came out of, written into the manifest so a published
       Project can be traced back to the run that made it. Two runs must not
       share one: it is job id and uuid, not job id alone. */
    char     job_identity[MAPGEN_PUBLISH_NAME];
    char     recipe_sha256[MAPGEN_PUBLISH_HEX];
    mapgen_publish_member_t members[MAPGEN_PUBLISH_MEMBERS];
    uint32_t num_members;
} mapgen_publish_request_t;

typedef struct {
    char     name[MAPGEN_PUBLISH_NAME];
    char     job_identity[MAPGEN_PUBLISH_NAME];
    uint32_t num_members;
    char     role[MAPGEN_PUBLISH_MEMBERS][MAPGEN_PUBLISH_ROLE];
    char     file[MAPGEN_PUBLISH_MEMBERS][MAPGEN_PUBLISH_NAME];
    char     sha256[MAPGEN_PUBLISH_MEMBERS][MAPGEN_PUBLISH_HEX];
    char     manifest_sha256[MAPGEN_PUBLISH_HEX];
    char     detail[192];
} mapgen_publish_report_t;

/*
 * Publish, or publish nothing.
 *
 * Returns ERR_COLLISION when any final name is already there; the caller's
 * answer to that is a new identity, never a replacement. `out` may be NULL.
 */
mapgen_publish_result_t
MapGenPublish_Commit(const mapgen_publish_request_t *request,
                     mapgen_publish_report_t *out);

/*
 * Is this a published Project, and is it still what it said it was?
 *
 * Reads the manifest, checks the manifest's own hash, then hashes every member
 * on disk and compares. Tampering after publication, a missing sidecar and a
 * truncated map all answer no.
 */
mapgen_publish_result_t
MapGenPublish_Verify(const char *maps_dir, const char *name,
                     mapgen_publish_report_t *out);

/*
 * The Project verifies AND its map is exactly these bytes.
 *
 * `MapGenPublish_Verify` answers about files on disk, which is the right
 * question for a list and the wrong one for a load: between the answer and the
 * engine's own read, the file can change. This takes the bytes the loader is
 * already holding and requires them to be the ones the manifest recorded, so
 * that what was verified and what is used are one thing rather than two reads
 * of the same path.
 *
 * ERR_NOT_A_PROJECT for a name with no manifest, so a caller can tell "not
 * ours" from "ours, and wrong".
 */
mapgen_publish_result_t
MapGenPublish_BindBytes(const char *maps_dir, const char *name,
                        const void *bytes, size_t length,
                        mapgen_publish_report_t *out);

/*
 * Is this the name of something the generator publishes?
 *
 * The prefix is the generator's own, so a map wearing it must answer to a
 * manifest. Here rather than spelled out at each caller: a loader deciding for
 * itself what a Project is called would be a second opinion about it.
 */
bool MapGenPublish_IsProjectName(const char *name);

/*
 * Every published Project in a maps directory, newest manifest first.
 *
 * Only Projects: a loose BSP with a familiar-looking name is not one, however
 * it is spelled. Returns how many names were written.
 */
uint32_t MapGenPublish_List(const char *maps_dir,
                            char (*names)[MAPGEN_PUBLISH_NAME], uint32_t max);

/* The manifest's file name for a Project, e.g. "q2mg_0001.q2mgproj". */
void MapGenPublish_ManifestName(const char *name,
                                char out[MAPGEN_PUBLISH_NAME]);

#endif /* MAPGEN_PUBLISH_H */
