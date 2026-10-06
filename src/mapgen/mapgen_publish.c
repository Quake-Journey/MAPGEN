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
 * Publishing a Project. The contract is in inc/common/mapgen_publish.h.
 *
 * Two rules run through everything here: nothing existing is ever removed or
 * replaced, and nothing is visible until all of it is.
 */

/*
 * `fileno` and `fsync` are POSIX rather than ISO C, and a
 * -std=c17 build hides them unless this is asked for BEFORE
 * any header is read.
 */
#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L
#endif

#include "common/mapgen_publish.h"
#include "common/mapgen_digest.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <direct.h>
#else
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#endif

#define MANIFEST_SUFFIX  ".q2mgproj"
#define MANIFEST_MAGIC   "q2pro-x mapgen project 1"

bool MapGenPublish_IsProjectName(const char *name)
{
    return name && !strncmp(name, MAPGEN_PUBLISH_PREFIX,
                            strlen(MAPGEN_PUBLISH_PREFIX));
}

const char *MapGenPublish_ResultName(mapgen_publish_result_t r)
{
    switch (r) {
    case MAPGEN_PUBLISH_OK:                 return "OK";
    case MAPGEN_PUBLISH_ERR_ARGS:           return "ERR_ARGS";
    case MAPGEN_PUBLISH_ERR_SOURCE:         return "ERR_SOURCE";
    case MAPGEN_PUBLISH_ERR_HASH:           return "ERR_HASH";
    case MAPGEN_PUBLISH_ERR_COLLISION:      return "ERR_COLLISION";
    case MAPGEN_PUBLISH_ERR_STAGE:          return "ERR_STAGE";
    case MAPGEN_PUBLISH_ERR_COMMIT:         return "ERR_COMMIT";
    case MAPGEN_PUBLISH_ERR_NOT_A_PROJECT:  return "ERR_NOT_A_PROJECT";
    case MAPGEN_PUBLISH_ERR_MANIFEST:       return "ERR_MANIFEST";
    case MAPGEN_PUBLISH_ERR_NAME:           return "ERR_NAME";
    case MAPGEN_PUBLISH_ERR_RECEIPT:        return "ERR_RECEIPT";
    case MAPGEN_PUBLISH_ERR_ROLE:           return "ERR_ROLE";
    case MAPGEN_PUBLISH_ERR_NOT_THESE_BYTES: return "ERR_NOT_THESE_BYTES";
    case MAPGEN_PUBLISH_RESULT_COUNT:       break;
    }
    return "?";
}

void MapGenPublish_ManifestName(const char *name,
                                char out[MAPGEN_PUBLISH_NAME])
{
    if (out)
        snprintf(out, MAPGEN_PUBLISH_NAME, "%s%s", name ? name : "",
                 MANIFEST_SUFFIX);
}

/* ---- files --------------------------------------------------------------- */

static bool exists(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0;
}

static bool make_dir(const char *path)
{
#ifdef _WIN32
    if (_mkdir(path) == 0)
        return true;
#else
    if (mkdir(path, 0777) == 0)
        return true;
#endif
    return errno == EEXIST;
}

/*
 * Push this file's data to the device.
 *
 * On POSIX that is `fsync`, which is a real crash guarantee for the CONTENT.
 * On Windows it is `FlushFileBuffers`, which is the same promise for the same
 * thing. Neither says anything about the file's NAME; that is the directory's
 * business, below.
 */
static bool flush_file(FILE *f)
{
#ifdef _WIN32
    const HANDLE h = (HANDLE)_get_osfhandle(_fileno(f));
    return h != INVALID_HANDLE_VALUE && FlushFileBuffers(h);
#else
    return fsync(fileno(f)) == 0;
#endif
}

/*
 * Push a directory's ENTRIES to the device.
 *
 * On POSIX a file is not durably named until its directory is fsync'd, so this
 * is what makes a committed member survive a crash.
 *
 * On Windows there is no supported way to do it. NTFS orders metadata through
 * its own journal and a MoveFileEx that has returned is recorded there; what a
 * caller does NOT get is a barrier it can place itself. So this is a no-op on
 * Windows, and the guarantee is weaker than on POSIX - said here rather than
 * implied by a function that pretends to do something.
 */
static bool flush_directory(const char *path)
{
#ifdef _WIN32
    (void)path;
    return true;
#else
    const int fd = open(path, O_RDONLY);
    if (fd < 0)
        return false;
    const bool ok = fsync(fd) == 0;
    close(fd);
    return ok;
#endif
}

/*
 * Copy, flush to the device, close, then read the copy back and hash it.
 *
 * The read-back is the point. A copy that returned success and a file that is
 * on the disk are different claims, and the second one is the one a player
 * needs to be true.
 */
static bool copy_and_hash(const char *from, const char *to,
                          char out_hex[MAPGEN_PUBLISH_HEX])
{
    FILE *in = fopen(from, "rb");
    if (!in)
        return false;
    FILE *dest = fopen(to, "wb");
    if (!dest) {
        fclose(in);
        return false;
    }

    bool ok = true;
    static char buffer[64 * 1024];
    for (;;) {
        const size_t got = fread(buffer, 1, sizeof(buffer), in);
        if (!got)
            break;
        if (fwrite(buffer, 1, got, dest) != got) {
            ok = false;
            break;
        }
    }
    if (ferror(in))
        ok = false;
    if (ok && fflush(dest) != 0)
        ok = false;
    if (ok)
        ok = flush_file(dest);
    if (fclose(dest) != 0)
        ok = false;
    fclose(in);
    if (!ok) {
        remove(to);
        return false;
    }

    /* Read back what is actually there, not what was in the buffer. */
    FILE *check = fopen(to, "rb");
    if (!check)
        return false;
    mapgen_sha256_t ctx;
    MapGenDigest_Sha256Init(&ctx);
    for (;;) {
        const size_t got = fread(buffer, 1, sizeof(buffer), check);
        if (!got)
            break;
        MapGenDigest_Sha256Update(&ctx, buffer, got);
    }
    ok = !ferror(check);
    fclose(check);
    if (!ok)
        return false;

    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256Final(&ctx, digest);
    MapGenDigest_Sha256Hex(digest, out_hex);
    return true;
}

static bool hash_file(const char *path, char out_hex[MAPGEN_PUBLISH_HEX])
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return false;
    mapgen_sha256_t ctx;
    MapGenDigest_Sha256Init(&ctx);
    static char buffer[64 * 1024];
    for (;;) {
        const size_t got = fread(buffer, 1, sizeof(buffer), f);
        if (!got)
            break;
        MapGenDigest_Sha256Update(&ctx, buffer, got);
    }
    const bool ok = !ferror(f);
    fclose(f);
    if (!ok)
        return false;
    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256Final(&ctx, digest);
    MapGenDigest_Sha256Hex(digest, out_hex);
    return true;
}

/*
 * Move into place, refusing to replace.
 *
 * On Windows that is one call with no REPLACE_EXISTING flag. Elsewhere it is
 * `link` then `unlink`, because `rename` REPLACES on POSIX and would do
 * silently the one thing this whole module exists to prevent.
 */
static bool move_no_replace(const char *from, const char *to)
{
#ifdef _WIN32
    /* MoveFileExA, and no MOVEFILE_REPLACE_EXISTING: the whole point is that
       an existing destination makes this fail. */
    return MoveFileExA(from, to, 0) != 0;
#else
    if (link(from, to) != 0)
        return false;
    unlink(from);
    return true;
#endif
}

/* ---- what a Project is allowed to be called ----------------------------- */

/*
 * A name is a basename and nothing else.
 *
 * Every one of these becomes a path component. A separator, a dot component, a
 * drive letter or a reserved device name in any of them is a way out of the
 * maps directory, and the caller of this module is the Controller acting on a
 * worker's word - which is not a reason to trust it.
 */
static bool safe_component(const char *s, size_t max)
{
    if (!s || !*s)
        return false;
    size_t n = 0;
    for (const char *at = s; *at; at++, n++) {
        if (n >= max)
            return false;
        const char c = *at;
        const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                     || (c >= '0' && c <= '9') || c == '_' || c == '-'
                     || c == '.';
        if (!ok)
            return false;
    }
    /* "." and ".." are components with meaning, and a name that starts with a
       dot is one the shell and the loader disagree about. */
    if (s[0] == '.')
        return false;
    /* No stream or device syntax can survive, and no path can be rebuilt. */
    if (strchr(s, ':') || strchr(s, '/') || strchr(s, '\\'))
        return false;
    static const char *const reserved[] = {
        "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5",
        "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4",
        "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
    };
    char lower[MAPGEN_PUBLISH_NAME];
    size_t k = 0;
    for (const char *at = s; *at && k + 1 < sizeof(lower); at++, k++)
        lower[k] = (*at >= 'A' && *at <= 'Z') ? (char)(*at - 'A' + 'a') : *at;
    lower[k] = '\0';
    char *dot = strchr(lower, '.');
    if (dot)
        *dot = '\0';
    for (size_t i = 0; i < sizeof(reserved) / sizeof(reserved[0]); i++)
        if (!strcmp(lower, reserved[i]))
            return false;
    return true;
}

static bool is_sha256_hex(const char *s)
{
    if (!s)
        return false;
    size_t n = 0;
    for (; s[n]; n++) {
        const char c = s[n];
        const bool hex = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
        if (!hex)
            return false;
    }
    return n == 64;
}

/* ---- the roles a Project has ------------------------------------------- */

typedef struct {
    const char *role;
    const char *suffix;
    bool        always;      /* every Project has one, or it is not one */
} role_rule_t;

/*
 * The whole set, and nothing outside it. A role is an identity with a fixed
 * file suffix, not a string the caller invents - which is what let a manifest
 * list a receipt and call itself complete.
 */
static const role_rule_t s_roles[] = {
    { "map",          ".bsp",              true  },
    { "receipt",      ".q2mgreceipt",      true  },
    { "certificates", ".certificates.txt", false },
    { "recipe",       ".q2mgrec",          false },
};

#define NUM_ROLES  (sizeof(s_roles) / sizeof(s_roles[0]))

static const role_rule_t *role_of(const char *name)
{
    for (size_t i = 0; i < NUM_ROLES; i++)
        if (name && !strcmp(name, s_roles[i].role))
            return &s_roles[i];
    return NULL;
}

/* ---- the receipt, parsed strictly --------------------------------------- */

/*
 * What the verdict said, read as a contract rather than as a log.
 *
 * The receipt is the worker's own summary, and publication has to know three
 * things from it: what the map hashed to, how many certificates the verdict
 * rests on, and whether a recipe was written. Missing, duplicated or malformed
 * fields are refusals - a receipt whose certificate count could not be read is
 * not a receipt that declares zero.
 */
typedef struct {
    char     bsp_sha256[MAPGEN_PUBLISH_HEX];
    uint32_t certificates;
    bool     has_recipe;
    bool     publishable;
} receipt_t;

static bool receipt_field(const char *text, const char *key, char *out,
                          size_t capacity, bool *duplicated)
{
    const size_t klen = strlen(key);
    bool found = false;
    *duplicated = false;
    for (const char *at = text; at && *at;) {
        const char *end = strchr(at, '\n');
        const size_t len = end ? (size_t)(end - at) : strlen(at);
        if (len > klen && !strncmp(at, key, klen) && at[klen] == ' ') {
            if (found) {
                *duplicated = true;
                return false;
            }
            size_t n = len - klen - 1;
            if (n >= capacity)
                return false;
            memcpy(out, at + klen + 1, n);
            out[n] = '\0';
            found = true;
        }
        at = end ? end + 1 : NULL;
    }
    return found;
}

static bool parse_receipt(const char *text, receipt_t *out, char *why,
                          size_t why_size)
{
    memset(out, 0, sizeof(*out));
    char value[MAPGEN_PUBLISH_PATH];
    bool duplicated = false;

    if (!receipt_field(text, "bspsha", out->bsp_sha256,
                       sizeof(out->bsp_sha256), &duplicated)) {
        snprintf(why, why_size, duplicated ? "the receipt declares two map "
                 "hashes" : "the receipt declares no map hash");
        return false;
    }
    if (!is_sha256_hex(out->bsp_sha256)) {
        snprintf(why, why_size, "the receipt's map hash is not a hash");
        return false;
    }
    if (!receipt_field(text, "certificates", value, sizeof(value),
                       &duplicated)) {
        snprintf(why, why_size, duplicated
                 ? "the receipt declares two certificate counts"
                 : "the receipt declares no certificate count");
        return false;
    }
    char *stop = NULL;
    const unsigned long count = strtoul(value, &stop, 10);
    if (!value[0] || !stop || *stop || count > 4096u) {
        snprintf(why, why_size, "the certificate count is not a count: %s",
                 value);
        return false;
    }
    out->certificates = (uint32_t)count;

    if (!receipt_field(text, "recipe", value, sizeof(value), &duplicated)) {
        snprintf(why, why_size, duplicated
                 ? "the receipt names two recipes"
                 : "the receipt does not say whether a recipe was written");
        return false;
    }
    out->has_recipe = value[0] && strcmp(value, "-") != 0;

    if (!receipt_field(text, "publishable", value, sizeof(value),
                       &duplicated)) {
        snprintf(why, why_size, "the receipt does not say it is publishable");
        return false;
    }
    out->publishable = !strcmp(value, "1");
    if (!out->publishable) {
        snprintf(why, why_size, "the receipt says this is not publishable");
        return false;
    }
    return true;
}

/*
 * The certificates, read rather than weighed.
 *
 * A traversal certificate says: this candidate, under this physics, can be
 * walked to this pickup. Publication cannot replay one - that is the reach
 * layer's work and it does not belong in the client - but it can insist that
 * the file contains as many records as the verdict declared and that every one
 * of them is about the map being published. An empty file, a truncated file
 * and a file belonging to another Project all fail here.
 */
static bool validate_certificates(const char *text, uint32_t declared,
                                  const char *map_sha256, char *why,
                                  size_t why_size)
{
    uint32_t records = 0, about_this_map = 0, with_physics = 0;
    for (const char *at = text; at && *at;) {
        const char *end = strchr(at, '\n');
        const size_t len = end ? (size_t)(end - at) : strlen(at);
        if (len > 12 && !strncmp(at, "certificate ", 12))
            records++;
        else if (len > 12 && !strncmp(at, "  candidate ", 12)) {
            char sha[MAPGEN_PUBLISH_HEX];
            const size_t n = len - 12;
            if (n < sizeof(sha)) {
                memcpy(sha, at + 12, n);
                sha[n] = '\0';
                if (!strcmp(sha, map_sha256))
                    about_this_map++;
            }
        } else if (len > 10 && !strncmp(at, "  physics ", 10)) {
            with_physics++;
        }
        at = end ? end + 1 : NULL;
    }

    if (records != declared) {
        snprintf(why, why_size,
                 "the receipt rests on %u certificates and the file holds %u",
                 declared, records);
        return false;
    }
    if (about_this_map != records) {
        snprintf(why, why_size,
                 "%u of %u certificates are about another map",
                 records - about_this_map, records);
        return false;
    }
    if (with_physics != records) {
        snprintf(why, why_size,
                 "%u of %u certificates carry no physics identity",
                 records - with_physics, records);
        return false;
    }
    return true;
}

/* ---- the manifest -------------------------------------------------------- */

/*
 * The manifest is the Project.
 *
 * It names every member with the hash it had when it was published, and ends
 * with a hash of everything above it, so a manifest edited to describe a
 * tampered map fails on its own line before any member is even opened.
 */
static size_t manifest_body(const mapgen_publish_report_t *r, char *out,
                            size_t capacity)
{
    size_t used = 0;
    used += (size_t)snprintf(out + used, capacity - used,
                             "%s\nname %s\njob %s\nmembers %u\n",
                             MANIFEST_MAGIC, r->name, r->job_identity,
                             r->num_members);
    for (uint32_t i = 0; i < r->num_members && used + 1 < capacity; i++)
        used += (size_t)snprintf(out + used, capacity - used,
                                 "member %s %s %s\n", r->role[i], r->file[i],
                                 r->sha256[i]);
    return used;
}

static void manifest_hash(const char *body, size_t length,
                          char out[MAPGEN_PUBLISH_HEX])
{
    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(body, length, digest);
    MapGenDigest_Sha256Hex(digest, out);
}

/*
 * Is this path inside that directory?
 *
 * Textual, deliberately strict, and refusing anything it cannot decide: a
 * relative component, a dot component, a mismatched prefix or a path that
 * merely starts with the same letters as a sibling directory all answer no.
 * A worker's summary is untrusted input and this is the boundary it crosses.
 */
static bool inside_directory(const char *path, const char *dir)
{
    if (!path || !dir || !*path || !*dir)
        return false;
    for (const char *at = path; *at; at++) {
        if (at[0] != '.' || at[1] != '.')
            continue;
        const char before = at == path ? '/' : at[-1];
        const char after = at[2];
        if ((before == '/' || before == '\\')
            && (after == '/' || after == '\\' || after == '\0'))
            return false;
    }
    size_t n = strlen(dir);
    while (n && (dir[n - 1] == '/' || dir[n - 1] == '\\'))
        n--;
    if (strlen(path) <= n + 1)
        return false;
    for (size_t i = 0; i < n; i++) {
        char a = path[i], b = dir[i];
        if (a == '\\')
            a = '/';
        if (b == '\\')
            b = '/';
        if (a >= 'A' && a <= 'Z')
            a = (char)(a - 'A' + 'a');
        if (b >= 'A' && b <= 'Z')
            b = (char)(b - 'A' + 'a');
        if (a != b)
            return false;
    }
    return path[n] == '/' || path[n] == '\\';
}

/* ---- publishing ---------------------------------------------------------- */

static void remove_dir(const char *path)
{
#ifdef _WIN32
    _rmdir(path);
#else
    rmdir(path);
#endif
}

mapgen_publish_result_t
MapGenPublish_Commit(const mapgen_publish_request_t *request,
                     mapgen_publish_report_t *out)
{
    mapgen_publish_report_t scratch;
    if (!out)
        out = &scratch;
    memset(out, 0, sizeof(*out));

    if (!request || !request->maps_dir[0] || !request->name[0]
        || !request->num_members
        || request->num_members > MAPGEN_PUBLISH_MEMBERS)
        return MAPGEN_PUBLISH_ERR_ARGS;

    /*
     * The same rules Verify will apply, applied here - so a Project can never
     * be committed in a shape that would then fail to verify.
     */
    if (!safe_component(request->name, MAPGEN_PUBLISH_NAME - 16)
        || !safe_component(request->job_identity, MAPGEN_PUBLISH_NAME - 1)) {
        snprintf(out->detail, sizeof(out->detail),
                 "the name or job identity is not one a Project may have");
        return MAPGEN_PUBLISH_ERR_NAME;
    }
    {
        bool declared_role[NUM_ROLES] = { false };
        for (uint32_t i = 0; i < request->num_members; i++) {
            const mapgen_publish_member_t *m = &request->members[i];
            const role_rule_t *rule = role_of(m->role);
            if (!rule) {
                snprintf(out->detail, sizeof(out->detail),
                         "%s is not a role a Project has", m->role);
                return MAPGEN_PUBLISH_ERR_ROLE;
            }
            if (strcmp(m->suffix, rule->suffix)) {
                snprintf(out->detail, sizeof(out->detail),
                         "a %s is called %s, not %s", m->role, rule->suffix,
                         m->suffix);
                return MAPGEN_PUBLISH_ERR_ROLE;
            }
            const size_t which = (size_t)(rule - s_roles);
            if (declared_role[which]) {
                snprintf(out->detail, sizeof(out->detail),
                         "two members claim to be the %s", m->role);
                return MAPGEN_PUBLISH_ERR_ROLE;
            }
            declared_role[which] = true;
            if (request->job_dir[0] && m->source[0]
                && !inside_directory(m->source, request->job_dir)) {
                snprintf(out->detail, sizeof(out->detail),
                         "the %s is outside the job directory: %s", m->role,
                         m->source);
                return MAPGEN_PUBLISH_ERR_NAME;
            }
        }
        for (size_t i = 0; i < NUM_ROLES; i++)
            if (s_roles[i].always && !declared_role[i]) {
                snprintf(out->detail, sizeof(out->detail),
                         "a Project has a %s and this one declares none",
                         s_roles[i].role);
                return MAPGEN_PUBLISH_ERR_ROLE;
            }
    }

    snprintf(out->name, sizeof(out->name), "%s", request->name);
    snprintf(out->job_identity, sizeof(out->job_identity), "%s",
             request->job_identity);

    char stage[MAPGEN_PUBLISH_PATH];
    if ((size_t)snprintf(stage, sizeof(stage), "%s/.q2mgstage_%s_%s",
                         request->maps_dir, request->name,
                         request->job_identity[0] ? request->job_identity
                                                  : "0") >= sizeof(stage))
        return MAPGEN_PUBLISH_ERR_ARGS;
    /*
     * The staging directory is created EXCLUSIVELY.
     *
     * `make_dir` treated an existing one as success, so two runs sharing an
     * identity could stage into the same place and each see the other's files.
     * A stage that is already there is a run that did not finish, or another
     * one in flight; either way this publication does not get to use it.
     */
    if (!make_dir(request->maps_dir))
        return MAPGEN_PUBLISH_ERR_STAGE;
    if (exists(stage)) {
        snprintf(out->detail, sizeof(out->detail),
                 "a staging directory for this identity is already there: %s",
                 stage);
        return MAPGEN_PUBLISH_ERR_STAGE;
    }
    if (!make_dir(stage))
        return MAPGEN_PUBLISH_ERR_STAGE;

    char staged[MAPGEN_PUBLISH_MEMBERS][MAPGEN_PUBLISH_PATH];
    char final[MAPGEN_PUBLISH_MEMBERS][MAPGEN_PUBLISH_PATH];
    uint32_t staged_count = 0;
    mapgen_publish_result_t rc = MAPGEN_PUBLISH_OK;

    for (uint32_t i = 0; i < request->num_members && rc == MAPGEN_PUBLISH_OK;
         i++) {
        const mapgen_publish_member_t *m = &request->members[i];
        if (!m->source[0] || !exists(m->source)) {
            if (m->required) {
                snprintf(out->detail, sizeof(out->detail),
                         "the %s is not there: %s", m->role, m->source);
                rc = MAPGEN_PUBLISH_ERR_SOURCE;
            }
            continue;               /* an optional member simply is not one */
        }

        char file[MAPGEN_PUBLISH_NAME];
        if ((size_t)snprintf(file, sizeof(file), "%s%s", request->name,
                             m->suffix) >= sizeof(file)) {
            rc = MAPGEN_PUBLISH_ERR_ARGS;
            break;
        }
        if ((size_t)snprintf(staged[staged_count], MAPGEN_PUBLISH_PATH,
                             "%s/%s", stage, file) >= MAPGEN_PUBLISH_PATH
            || (size_t)snprintf(final[staged_count], MAPGEN_PUBLISH_PATH,
                                "%s/%s", request->maps_dir, file)
               >= MAPGEN_PUBLISH_PATH) {
            rc = MAPGEN_PUBLISH_ERR_ARGS;
            break;
        }

        char hex[MAPGEN_PUBLISH_HEX];
        if (!copy_and_hash(m->source, staged[staged_count], hex)) {
            snprintf(out->detail, sizeof(out->detail),
                     "the %s could not be staged", m->role);
            rc = MAPGEN_PUBLISH_ERR_SOURCE;
            break;
        }
        if (m->declared_sha256[0]
            && strcmp(m->declared_sha256, hex) != 0) {
            snprintf(out->detail, sizeof(out->detail),
                     "the %s hashes %s, the verdict declared %s", m->role,
                     hex, m->declared_sha256);
            rc = MAPGEN_PUBLISH_ERR_HASH;
            break;
        }
        snprintf(out->role[staged_count], MAPGEN_PUBLISH_ROLE, "%s", m->role);
        snprintf(out->file[staged_count], MAPGEN_PUBLISH_NAME, "%s", file);
        snprintf(out->sha256[staged_count], MAPGEN_PUBLISH_HEX, "%s", hex);
        staged_count++;
    }
    out->num_members = staged_count;

    /*
     * What the receipt declares, applied here as well as in Verify.
     *
     * A Project committed without the evidence its own verdict rests on could
     * never verify, so refusing it on the way out only would leave a set of
     * files nothing would ever list - and no explanation of why.
     */
    if (rc == MAPGEN_PUBLISH_OK) {
        char receipt_path[MAPGEN_PUBLISH_PATH] = "";
        char map_sha[MAPGEN_PUBLISH_HEX] = "";
        char certs_path[MAPGEN_PUBLISH_PATH] = "";
        bool has_certificates = false, has_recipe = false;
        for (uint32_t i = 0; i < staged_count; i++) {
            if (!strcmp(out->role[i], "receipt"))
                snprintf(receipt_path, sizeof(receipt_path), "%s",
                         staged[i]);
            else if (!strcmp(out->role[i], "map"))
                snprintf(map_sha, sizeof(map_sha), "%s", out->sha256[i]);
            else if (!strcmp(out->role[i], "certificates")) {
                has_certificates = true;
                snprintf(certs_path, sizeof(certs_path), "%s", staged[i]);
            } else if (!strcmp(out->role[i], "recipe"))
                has_recipe = true;
        }

        char receipt_text[8192] = "";
        FILE *r = receipt_path[0] ? fopen(receipt_path, "rb") : NULL;
        if (r) {
            const size_t n = fread(receipt_text, 1, sizeof(receipt_text) - 1,
                                   r);
            receipt_text[n] = '\0';
            fclose(r);
        }
        receipt_t receipt;
        char why[128];
        if (!parse_receipt(receipt_text, &receipt, why, sizeof(why))) {
            snprintf(out->detail, sizeof(out->detail), "%s", why);
            rc = MAPGEN_PUBLISH_ERR_RECEIPT;
        } else if (strcmp(receipt.bsp_sha256, map_sha)) {
            snprintf(out->detail, sizeof(out->detail),
                     "the receipt declares the map hashes %s and it hashes %s",
                     receipt.bsp_sha256, map_sha);
            rc = MAPGEN_PUBLISH_ERR_RECEIPT;
        } else if (receipt.certificates && !has_certificates) {
            snprintf(out->detail, sizeof(out->detail),
                     "the receipt rests on %u certificates and none were "
                     "staged", receipt.certificates);
            rc = MAPGEN_PUBLISH_ERR_ROLE;
        } else if (receipt.has_recipe && !has_recipe) {
            snprintf(out->detail, sizeof(out->detail),
                     "the receipt names a recipe and none was staged");
            rc = MAPGEN_PUBLISH_ERR_ROLE;
        } else if (has_certificates) {
            char text[65536] = "";
            FILE *c = fopen(certs_path, "rb");
            if (c) {
                const size_t n = fread(text, 1, sizeof(text) - 1, c);
                text[n] = '\0';
                fclose(c);
            }
            if (!validate_certificates(text, receipt.certificates, map_sha,
                                       why, sizeof(why))) {
                snprintf(out->detail, sizeof(out->detail), "%s", why);
                rc = MAPGEN_PUBLISH_ERR_RECEIPT;
            }
        }
    }

    /* Reserve: a name already taken refuses everything, before anything has
       moved. The no-replace move below is what makes it safe against a race;
       this is what makes the message useful. */
    char manifest_name[MAPGEN_PUBLISH_NAME];
    char manifest_final[MAPGEN_PUBLISH_PATH];
    char manifest_staged[MAPGEN_PUBLISH_PATH];
    MapGenPublish_ManifestName(request->name, manifest_name);
    if (rc == MAPGEN_PUBLISH_OK) {
        if ((size_t)snprintf(manifest_final, sizeof(manifest_final), "%s/%s",
                             request->maps_dir, manifest_name)
                >= sizeof(manifest_final)
            || (size_t)snprintf(manifest_staged, sizeof(manifest_staged),
                                "%s/%s", stage, manifest_name)
               >= sizeof(manifest_staged))
            rc = MAPGEN_PUBLISH_ERR_ARGS;
    }
    if (rc == MAPGEN_PUBLISH_OK) {
        if (exists(manifest_final)) {
            snprintf(out->detail, sizeof(out->detail),
                     "%s is already a published Project", request->name);
            rc = MAPGEN_PUBLISH_ERR_COLLISION;
        }
        for (uint32_t i = 0; i < staged_count && rc == MAPGEN_PUBLISH_OK; i++)
            if (exists(final[i])) {
                snprintf(out->detail, sizeof(out->detail),
                         "%s is already there", out->file[i]);
                rc = MAPGEN_PUBLISH_ERR_COLLISION;
            }
    }

    /* The manifest, written and hashed while still out of sight. */
    if (rc == MAPGEN_PUBLISH_OK) {
        char body[4096];
        const size_t length = manifest_body(out, body, sizeof(body));
        manifest_hash(body, length, out->manifest_sha256);
        FILE *f = fopen(manifest_staged, "wb");
        bool ok = f != NULL;
        if (ok)
            ok = fwrite(body, 1, length, f) == length;
        if (ok)
            ok = fprintf(f, "manifest-sha256 %s\n", out->manifest_sha256) > 0;
        if (ok && fflush(f) != 0)
            ok = false;
        if (ok && f)
            ok = flush_file(f);
        if (f && fclose(f) != 0)
            ok = false;
        if (!ok) {
            snprintf(out->detail, sizeof(out->detail),
                     "the manifest could not be written");
            rc = MAPGEN_PUBLISH_ERR_MANIFEST;
        }
    }

    /*
     * Commit. Members first, manifest last: until the manifest lands there is
     * no Project, so a crash in the middle leaves files that nothing lists and
     * nothing plays.
     */
    /*
     * The staged files' names are durable before anything moves: on POSIX a
     * file that has been fsync'd is still nameless until its directory is.
     */
    if (rc == MAPGEN_PUBLISH_OK)
        flush_directory(stage);

    uint32_t moved = 0;
    if (rc == MAPGEN_PUBLISH_OK) {
        for (; moved < staged_count; moved++)
            if (!move_no_replace(staged[moved], final[moved])) {
                snprintf(out->detail, sizeof(out->detail),
                         "%s could not be committed", out->file[moved]);
                rc = MAPGEN_PUBLISH_ERR_COMMIT;
                break;
            }
    }
    /* Every member is named durably before the manifest makes them a
       Project. */
    if (rc == MAPGEN_PUBLISH_OK)
        flush_directory(request->maps_dir);

    if (rc == MAPGEN_PUBLISH_OK
        && !move_no_replace(manifest_staged, manifest_final)) {
        snprintf(out->detail, sizeof(out->detail),
                 "the manifest could not be committed");
        rc = MAPGEN_PUBLISH_ERR_COMMIT;
    }

    if (rc != MAPGEN_PUBLISH_OK) {
        /*
         * Withdraw. Only ever this publication's own files: every one of these
         * names was proved absent a moment ago, so nothing here can belong to
         * a Project that was already published.
         */
        for (uint32_t i = 0; i < moved; i++)
            remove(final[i]);
        for (uint32_t i = 0; i < staged_count; i++)
            remove(staged[i]);
        remove(manifest_staged);
        remove_dir(stage);
        return rc;
    }

    /* And the manifest itself, which is the moment the Project exists. */
    flush_directory(request->maps_dir);

    remove_dir(stage);
    snprintf(out->detail, sizeof(out->detail),
             "%u members committed under one manifest", out->num_members);
    return MAPGEN_PUBLISH_OK;
}

/* ---- verifying ----------------------------------------------------------- */

/*
 * The manifest, read as a grammar.
 *
 * Every line is expected in order and nothing else is allowed anywhere:
 *
 *     q2pro-x mapgen project 1
 *     name <name>
 *     job <identity>
 *     members <n>
 *     member <role> <file> <64 hex>        exactly n of these
 *     manifest-sha256 <64 hex>             and nothing after it
 *
 * The previous version searched for substrings, which is why a manifest that
 * listed one receipt and nothing else verified happily beside a loose BSP that
 * nothing had ever hashed.
 */
static const char *next_line(const char *at, char *out, size_t capacity)
{
    if (!at || !*at)
        return NULL;
    const char *end = strchr(at, '\n');
    const size_t len = end ? (size_t)(end - at) : strlen(at);
    if (len + 1 > capacity)
        return NULL;
    memcpy(out, at, len);
    out[len] = '\0';
    return end ? end + 1 : at + len;
}

static bool starts_with(const char *s, const char *prefix, const char **rest)
{
    const size_t n = strlen(prefix);
    if (strncmp(s, prefix, n))
        return false;
    *rest = s + n;
    return true;
}

mapgen_publish_result_t
MapGenPublish_Verify(const char *maps_dir, const char *name,
                     mapgen_publish_report_t *out)
{
    mapgen_publish_report_t scratch;
    if (!out)
        out = &scratch;
    memset(out, 0, sizeof(*out));
    if (!maps_dir || !name)
        return MAPGEN_PUBLISH_ERR_ARGS;
    if (!safe_component(name, MAPGEN_PUBLISH_NAME - 16)) {
        snprintf(out->detail, sizeof(out->detail),
                 "%s is not a name a Project may have", name);
        return MAPGEN_PUBLISH_ERR_NAME;
    }

    char manifest_name[MAPGEN_PUBLISH_NAME];
    char path[MAPGEN_PUBLISH_PATH];
    MapGenPublish_ManifestName(name, manifest_name);
    if ((size_t)snprintf(path, sizeof(path), "%s/%s", maps_dir,
                         manifest_name) >= sizeof(path))
        return MAPGEN_PUBLISH_ERR_ARGS;

    FILE *f = fopen(path, "rb");
    if (!f) {
        snprintf(out->detail, sizeof(out->detail),
                 "%s has no manifest, so it is not a Project", name);
        return MAPGEN_PUBLISH_ERR_NOT_A_PROJECT;
    }
    char text[8192];
    const size_t length = fread(text, 1, sizeof(text) - 1, f);
    const bool truncated = !feof(f);
    fclose(f);
    text[length] = '\0';
    if (truncated) {
        snprintf(out->detail, sizeof(out->detail), "the manifest is too large");
        return MAPGEN_PUBLISH_ERR_MANIFEST;
    }
    if (memchr(text, '\0', length)) {
        snprintf(out->detail, sizeof(out->detail),
                 "the manifest carries a NUL");
        return MAPGEN_PUBLISH_ERR_MANIFEST;
    }

    char line[1024];
    const char *at = text;
    const char *rest = NULL;

#define REFUSE(...) do { snprintf(out->detail, sizeof(out->detail), \
                                  __VA_ARGS__); \
                         return MAPGEN_PUBLISH_ERR_MANIFEST; } while (0)

    at = next_line(at, line, sizeof(line));
    if (!at || strcmp(line, MANIFEST_MAGIC))
        REFUSE("the manifest does not say what it is");

    at = next_line(at, line, sizeof(line));
    if (!at || !starts_with(line, "name ", &rest))
        REFUSE("the manifest names nothing");
    if (strcmp(rest, name))
        REFUSE("the manifest is called %s and was asked about as %s", rest,
               name);
    snprintf(out->name, sizeof(out->name), "%s", rest);

    at = next_line(at, line, sizeof(line));
    if (!at || !starts_with(line, "job ", &rest))
        REFUSE("the manifest records no job");
    if (!safe_component(rest, MAPGEN_PUBLISH_NAME - 1))
        REFUSE("the job identity is not one: %s", rest);
    snprintf(out->job_identity, sizeof(out->job_identity), "%s", rest);

    at = next_line(at, line, sizeof(line));
    if (!at || !starts_with(line, "members ", &rest))
        REFUSE("the manifest does not say how many members it has");
    char *stop = NULL;
    const unsigned long declared = strtoul(rest, &stop, 10);
    if (!*rest || !stop || *stop || declared == 0
        || declared > MAPGEN_PUBLISH_MEMBERS)
        REFUSE("the member count is not a count: %s", rest);

    /*
     * The members. Each role at most once, each file a basename, each hash a
     * hash - and exactly as many as the count above promised.
     */
    bool seen_role[NUM_ROLES] = { false };
    for (unsigned long i = 0; i < declared; i++) {
        at = next_line(at, line, sizeof(line));
        if (!at || !starts_with(line, "member ", &rest))
            REFUSE("member %lu of %lu is missing", i + 1, declared);
        char role[MAPGEN_PUBLISH_ROLE], file[MAPGEN_PUBLISH_NAME];
        char hex[MAPGEN_PUBLISH_HEX], extra[8];
        const int fields = sscanf(rest, "%31s %63s %64s %7s", role, file, hex,
                                  extra);
        if (fields != 3)
            REFUSE("member %lu is not a member line", i + 1);
        const role_rule_t *rule = role_of(role);
        if (!rule)
            REFUSE("%s is not a role a Project has", role);
        const size_t which = (size_t)(rule - s_roles);
        if (seen_role[which])
            REFUSE("the manifest lists %s twice", role);
        seen_role[which] = true;
        if (!safe_component(file, MAPGEN_PUBLISH_NAME - 1))
            REFUSE("%s is not a file name a Project may have", file);
        char wanted[MAPGEN_PUBLISH_NAME];
        snprintf(wanted, sizeof(wanted), "%s%s", name, rule->suffix);
        if (strcmp(file, wanted))
            REFUSE("the %s must be %s and is %s", role, wanted, file);
        if (!is_sha256_hex(hex))
            REFUSE("the %s hash is not a hash", role);
        snprintf(out->role[i], MAPGEN_PUBLISH_ROLE, "%s", role);
        snprintf(out->file[i], MAPGEN_PUBLISH_NAME, "%s", file);
        snprintf(out->sha256[i], MAPGEN_PUBLISH_HEX, "%s", hex);
        out->num_members++;
    }

    /* Every role a Project must have. Nothing about the caller's list can
       excuse a missing map or a missing receipt. */
    for (size_t i = 0; i < NUM_ROLES; i++)
        if (s_roles[i].always && !seen_role[i]) {
            snprintf(out->detail, sizeof(out->detail),
                     "a Project has a %s and this one does not",
                     s_roles[i].role);
            return MAPGEN_PUBLISH_ERR_ROLE;
        }

    const char *tail = at;
    at = next_line(at, line, sizeof(line));
    if (!at || !starts_with(line, "manifest-sha256 ", &rest))
        REFUSE("the manifest carries no hash of itself");
    if (!is_sha256_hex(rest))
        REFUSE("the manifest hash is not a hash");
    snprintf(out->manifest_sha256, sizeof(out->manifest_sha256), "%s", rest);

    /* Nothing after it. A manifest with a second self-hash, or anything
       appended, is not this format. */
    while (at && *at) {
        char trailing[1024];
        at = next_line(at, trailing, sizeof(trailing));
        if (at && trailing[0])
            REFUSE("the manifest has content after its hash: %s", trailing);
        if (!at)
            break;
    }

    char computed[MAPGEN_PUBLISH_HEX];
    manifest_hash(text, (size_t)(tail - text), computed);
    if (strcmp(computed, out->manifest_sha256))
        REFUSE("the manifest has been edited: it hashes %s and says %s",
               computed, out->manifest_sha256);

    /* Every member, hashed as it is on the disk. */
    char member_path[MAPGEN_PUBLISH_PATH];
    char receipt_text[8192] = "";
    for (uint32_t i = 0; i < out->num_members; i++) {
        char hex[MAPGEN_PUBLISH_HEX];
        if ((size_t)snprintf(member_path, sizeof(member_path), "%s/%s",
                             maps_dir, out->file[i]) >= sizeof(member_path))
            return MAPGEN_PUBLISH_ERR_ARGS;
        if (!hash_file(member_path, hex)) {
            snprintf(out->detail, sizeof(out->detail), "the %s is gone: %s",
                     out->role[i], out->file[i]);
            return MAPGEN_PUBLISH_ERR_SOURCE;
        }
        if (strcmp(hex, out->sha256[i])) {
            snprintf(out->detail, sizeof(out->detail),
                     "the %s is not what was published: %s", out->role[i],
                     out->file[i]);
            return MAPGEN_PUBLISH_ERR_HASH;
        }
        if (!strcmp(out->role[i], "receipt")) {
            FILE *r = fopen(member_path, "rb");
            if (r) {
                const size_t n = fread(receipt_text, 1,
                                       sizeof(receipt_text) - 1, r);
                receipt_text[n] = '\0';
                fclose(r);
            }
        }
    }

    /*
     * And the receipt decides what else the Project must have.
     *
     * This is what stops evidence being dropped by simply not mentioning it:
     * the verdict says how many certificates it rests on and whether a recipe
     * was written, and a manifest that omits either is refused here rather
     * than believed.
     */
    receipt_t receipt;
    char why[128];
    if (!parse_receipt(receipt_text, &receipt, why, sizeof(why))) {
        snprintf(out->detail, sizeof(out->detail), "%s", why);
        return MAPGEN_PUBLISH_ERR_RECEIPT;
    }
    for (uint32_t i = 0; i < out->num_members; i++)
        if (!strcmp(out->role[i], "map")
            && strcmp(out->sha256[i], receipt.bsp_sha256)) {
            snprintf(out->detail, sizeof(out->detail),
                     "the receipt declares the map hashes %s and it hashes %s",
                     receipt.bsp_sha256, out->sha256[i]);
            return MAPGEN_PUBLISH_ERR_RECEIPT;
        }
    if (receipt.certificates && seen_role[2]) {
        char certs[MAPGEN_PUBLISH_PATH];
        char text[65536] = "";
        for (uint32_t i = 0; i < out->num_members; i++)
            if (!strcmp(out->role[i], "certificates")
                && (size_t)snprintf(certs, sizeof(certs), "%s/%s", maps_dir,
                                    out->file[i]) < sizeof(certs)) {
                FILE *c = fopen(certs, "rb");
                if (c) {
                    const size_t n = fread(text, 1, sizeof(text) - 1, c);
                    text[n] = '\0';
                    fclose(c);
                }
            }
        char cwhy[128];
        if (!validate_certificates(text, receipt.certificates,
                                   receipt.bsp_sha256, cwhy, sizeof(cwhy))) {
            snprintf(out->detail, sizeof(out->detail), "%s", cwhy);
            return MAPGEN_PUBLISH_ERR_RECEIPT;
        }
    }
    if (receipt.certificates && !seen_role[2]) {
        snprintf(out->detail, sizeof(out->detail),
                 "the receipt rests on %u certificates and none were published",
                 receipt.certificates);
        return MAPGEN_PUBLISH_ERR_ROLE;
    }
    if (receipt.has_recipe && !seen_role[3]) {
        snprintf(out->detail, sizeof(out->detail),
                 "the receipt names a recipe and none was published");
        return MAPGEN_PUBLISH_ERR_ROLE;
    }

#undef REFUSE

    snprintf(out->detail, sizeof(out->detail),
             "%u members, all present and unchanged", out->num_members);
    return MAPGEN_PUBLISH_OK;
}

/* ---- listing ------------------------------------------------------------- */

/*
 * The Project verifies, and the map it names is exactly the bytes in hand.
 *
 * Verification alone answers about a path: it opens the files, hashes them and
 * compares. That is the right question for a list and the wrong one for a
 * load, because the engine then opens the same path AGAIN and nothing says the
 * second read saw what the first did. This is handed the bytes the loader is
 * holding, so the thing verified and the thing used are one thing.
 *
 * The Project is still verified in full first. A map whose own bytes match
 * while its receipt has been replaced is not a Project that may be played, and
 * checking only the hash in hand would be exactly that mistake.
 */
mapgen_publish_result_t
MapGenPublish_BindBytes(const char *maps_dir, const char *name,
                        const void *bytes, size_t length,
                        mapgen_publish_report_t *out)
{
    mapgen_publish_report_t scratch;
    if (!out)
        out = &scratch;
    memset(out, 0, sizeof(*out));

    if (!maps_dir || !name || !bytes)
        return MAPGEN_PUBLISH_ERR_ARGS;

    /* Everything the list is held to, before anything about these bytes. */
    const mapgen_publish_result_t rc = MapGenPublish_Verify(maps_dir, name,
                                                            out);
    if (rc != MAPGEN_PUBLISH_OK)
        return rc;

    const char *declared = NULL;
    for (uint32_t i = 0; i < out->num_members; i++)
        if (!strcmp(out->role[i], "map"))
            declared = out->sha256[i];
    if (!declared) {
        /* Verify already refuses a Project with no map, so reaching here means
           the two disagree about what a Project is - which is a defect, not a
           tampered file, and it is not going to be answered with a load. */
        snprintf(out->detail, sizeof(out->detail),
                 "the manifest verified and names no map");
        return MAPGEN_PUBLISH_ERR_ROLE;
    }

    uint8_t digest[MAPGEN_SHA256_BYTES];
    char hex[MAPGEN_SHA256_HEX];
    MapGenDigest_Sha256(bytes, length, digest);
    MapGenDigest_Sha256Hex(digest, hex);
    if (strcmp(hex, declared)) {
        snprintf(out->detail, sizeof(out->detail),
                 "the manifest records %.16s and these %zu bytes are %.16s",
                 declared, length, hex);
        return MAPGEN_PUBLISH_ERR_NOT_THESE_BYTES;
    }
    return MAPGEN_PUBLISH_OK;
}

uint32_t MapGenPublish_List(const char *maps_dir,
                            char (*names)[MAPGEN_PUBLISH_NAME], uint32_t max)
{
    if (!maps_dir || !names || !max)
        return 0;
    uint32_t found = 0;

#ifdef _WIN32
    char pattern[MAPGEN_PUBLISH_PATH];
    if ((size_t)snprintf(pattern, sizeof(pattern), "%s/*%s", maps_dir,
                         MANIFEST_SUFFIX) >= sizeof(pattern))
        return 0;
    WIN32_FIND_DATAA data;
    const HANDLE h = FindFirstFileA(pattern, &data);
    if (h == INVALID_HANDLE_VALUE)
        return 0;
    do {
        if (found >= max)
            break;
        char name[MAPGEN_PUBLISH_NAME];
        snprintf(name, sizeof(name), "%s", data.cFileName);
        char *dot = strstr(name, MANIFEST_SUFFIX);
        if (!dot)
            continue;
        *dot = '\0';
        /* Listed only if it verifies: a manifest that does not describe what
           is on the disk is not a Project the player may play. */
        if (MapGenPublish_Verify(maps_dir, name, NULL) != MAPGEN_PUBLISH_OK)
            continue;
        snprintf(names[found++], MAPGEN_PUBLISH_NAME, "%s", name);
    } while (FindNextFileA(h, &data));
    FindClose(h);
#else
    DIR *dir = opendir(maps_dir);
    if (!dir)
        return 0;
    const struct dirent *entry;
    while ((entry = readdir(dir)) != NULL && found < max) {
        char name[MAPGEN_PUBLISH_NAME];
        snprintf(name, sizeof(name), "%s", entry->d_name);
        char *dot = strstr(name, MANIFEST_SUFFIX);
        if (!dot || dot[strlen(MANIFEST_SUFFIX)] != '\0')
            continue;
        *dot = '\0';
        if (MapGenPublish_Verify(maps_dir, name, NULL) != MAPGEN_PUBLISH_OK)
            continue;
        snprintf(names[found++], MAPGEN_PUBLISH_NAME, "%s", name);
    }
    closedir(dir);
#endif
    return found;
}
