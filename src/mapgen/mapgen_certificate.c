/*
 * A certificate is evidence, and evidence is checked against the thing it is
 * about.
 *
 * Two checks, in the order they cost. Identity is string comparison and
 * catches the certificate that belongs to the candidate before this one.
 * Replay explores the compiled map again and asks whether it still does what
 * the certificate says - which is the only check that survives an edit that
 * carved away the ledge somebody launched from, because the identity of an
 * entity does not change when the floor under it does.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "common/mapgen_certificate.h"
#include "common/mapgen_reach.h"

const char *MapGenCertificate_KindName(mapgen_traversal_kind_t kind)
{
    switch (kind) {
    case MAPGEN_TRAVERSAL_ROCKET_JUMP: return "rocket-jump";
    case MAPGEN_TRAVERSAL_NONE:        break;
    }
    return "none";
}

const char *MapGenCertificate_ResultName(mapgen_certificate_result_t r)
{
    switch (r) {
    case MAPGEN_CERT_OK:                  return "OK";
    case MAPGEN_CERT_ERR_ARGS:            return "ERR_ARGS";
    case MAPGEN_CERT_ERR_STALE:           return "ERR_STALE";
    case MAPGEN_CERT_ERR_NOT_REPRODUCED:  return "ERR_NOT_REPRODUCED";
    case MAPGEN_CERT_ERR_UNSUPPORTED:     return "ERR_UNSUPPORTED";
    case MAPGEN_CERT_ERR_MEMORY:          return "ERR_MEMORY";
    }
    return "ERR_UNKNOWN";
}

void MapGenCertificate_Stamp(mapgen_certificate_set_t *set,
                             const char *candidate_sha256,
                             const char *donor_sha256,
                             const char *physics_sha256)
{
    if (!set)
        return;
    for (uint32_t i = 0; i < set->count; i++) {
        mapgen_certificate_t *c = &set->entries[i];
        snprintf(c->candidate_sha256, sizeof(c->candidate_sha256), "%s",
                 candidate_sha256 ? candidate_sha256 : "");
        snprintf(c->donor_sha256, sizeof(c->donor_sha256), "%s",
                 donor_sha256 ? donor_sha256 : "");
        snprintf(c->physics_sha256, sizeof(c->physics_sha256), "%s",
                 physics_sha256 ? physics_sha256 : "");
    }
}

/* An empty hash matches nothing, including another empty one: a certificate
   about no particular map would otherwise be about every map. */
static bool same_hash(const char *a, const char *b)
{
    return a && b && *a && *b && !strcmp(a, b);
}

mapgen_certificate_result_t
MapGenCertificate_Verify(const mapgen_certificate_t *cert,
                         const char *candidate_sha256,
                         const char *donor_sha256,
                         const char *physics_sha256)
{
    if (!cert)
        return MAPGEN_CERT_ERR_ARGS;
    if (cert->kind != MAPGEN_TRAVERSAL_ROCKET_JUMP)
        return MAPGEN_CERT_ERR_UNSUPPORTED;
    if (!same_hash(cert->candidate_sha256, candidate_sha256)
        || !same_hash(cert->donor_sha256, donor_sha256)
        || !same_hash(cert->physics_sha256, physics_sha256))
        return MAPGEN_CERT_ERR_STALE;
    return MAPGEN_CERT_OK;
}

/*
 * Near enough to be the same place.
 *
 * A player's own body is thirty-two wide and fifty-six tall, and the states a
 * search settles on sample a floor rather than cover it, so two runs of the
 * same map can witness the same jump from adjacent stances. Tighter than this
 * would fail a certificate for being re-derived; looser would let a
 * certificate about the other side of a room match.
 */
static bool same_place(const float a[3], const float b[3])
{
    return fabsf(a[0] - b[0]) <= 64.0f
        && fabsf(a[1] - b[1]) <= 64.0f
        && fabsf(a[2] - b[2]) <= 40.0f;
}

mapgen_certificate_result_t
MapGenCertificate_Replay(mapgen_certificate_t *cert, const mapgen_bsp_t *bsp,
                         const char *candidate_sha256,
                         const char *donor_sha256,
                         const char *physics_sha256)
{
    if (!cert || !bsp)
        return MAPGEN_CERT_ERR_ARGS;
    cert->replayed = false;

    const mapgen_certificate_result_t identity =
        MapGenCertificate_Verify(cert, candidate_sha256, donor_sha256,
                                 physics_sha256);
    if (identity != MAPGEN_CERT_OK)
        return identity;

    /*
     * Re-derived rather than re-checked.
     *
     * The search is what decides a special traversal is a route, and asking it
     * again is the only way to be sure the answer comes from the same rules
     * the gate uses. A second implementation here would be a second opinion,
     * and the two would drift.
     */
    mapgen_reach_t *reach = NULL;
    if (MapGenReach_Explore(bsp, 40000u, &reach) != MAPGEN_REACH_OK || !reach) {
        MapGenReach_Free(reach);
        return MAPGEN_CERT_ERR_NOT_REPRODUCED;
    }

    const mapgen_certificate_set_t *found = MapGenReach_Certificates(reach);
    bool reproduced = false;
    for (uint32_t i = 0; found && i < found->count && !reproduced; i++) {
        const mapgen_certificate_t *c = &found->entries[i];
        reproduced = c->kind == cert->kind
                  && !strcmp(c->classname, cert->classname)
                  && same_place(c->entity_origin, cert->entity_origin)
                  && same_place(c->launch, cert->launch)
                  && same_place(c->touch, cert->touch)
                  && same_place(c->landing, cert->landing);
    }
    MapGenReach_Free(reach);

    if (!reproduced)
        return MAPGEN_CERT_ERR_NOT_REPRODUCED;
    cert->replayed = true;
    return MAPGEN_CERT_OK;
}

#define APPEND(...)                                                          \
    do {                                                                     \
        const int n = snprintf(out + used, used < size ? size - used : 0,     \
                               __VA_ARGS__);                                 \
        if (n > 0)                                                           \
            used += (size_t)n;                                               \
    } while (0)

size_t MapGenCertificate_Render(const mapgen_certificate_set_t *set, char *out,
                                size_t size)
{
    if (!set)
        return 0;
    size_t used = 0;
    if (out && size)
        out[0] = '\0';

    for (uint32_t i = 0; i < set->count; i++) {
        const mapgen_certificate_t *c = &set->entries[i];
        APPEND("certificate %u\n", i);
        APPEND("  kind %s\n", MapGenCertificate_KindName(c->kind));
        APPEND("  candidate %s\n", c->candidate_sha256);
        APPEND("  donor %s\n", c->donor_sha256);
        APPEND("  physics %s\n", c->physics_sha256);
        APPEND("  entity %u %s\n", c->entity_index, c->classname);
        APPEND("  at %.1f %.1f %.1f\n", c->entity_origin[0],
               c->entity_origin[1], c->entity_origin[2]);
        APPEND("  launch %.1f %.1f %.1f\n", c->launch[0], c->launch[1],
               c->launch[2]);
        APPEND("  touch %.1f %.1f %.1f\n", c->touch[0], c->touch[1],
               c->touch[2]);
        APPEND("  landing %.1f %.1f %.1f\n", c->landing[0], c->landing[1],
               c->landing[2]);
        APPEND("  needs %s%s\n", c->needed_launcher ? "launcher " : "",
               c->needed_rockets ? "rockets" : "");
        APPEND("  cost %.1f damage, %.1f up\n", c->damage_taken,
               c->height_gained);
        APPEND("  demo %s %s\n", c->demo_digest[0] ? c->demo_digest : "-",
               c->demo_source[0] ? c->demo_source : "-");
        APPEND("  replayed %d\n", c->replayed ? 1 : 0);
    }
    if (set->overflowed)
        APPEND("overflowed 1\n");
    return used;
}

#undef APPEND

uint32_t MapGenCertificate_Parse(const char *text,
                                 mapgen_certificate_set_t *out)
{
    if (!text || !out)
        return 0;
    memset(out, 0, sizeof(*out));

    const char *at = text;
    mapgen_certificate_t *c = NULL;
    while (*at) {
        const char *line_end = strchr(at, '\n');
        const size_t n = line_end ? (size_t)(line_end - at) : strlen(at);
        char line[512];
        const size_t take = n < sizeof(line) - 1 ? n : sizeof(line) - 1;
        memcpy(line, at, take);
        line[take] = '\0';

        unsigned index = 0, replayed = 0;
        char word[128];
        if (sscanf(line, "certificate %u", &index) == 1) {
            if (out->count >= MAPGEN_CERT_MAX) {
                out->overflowed = true;
                c = NULL;
            } else {
                c = &out->entries[out->count++];
                memset(c, 0, sizeof(*c));
            }
        } else if (c && sscanf(line, " kind %127s", word) == 1) {
            c->kind = !strcmp(word, "rocket-jump")
                    ? MAPGEN_TRAVERSAL_ROCKET_JUMP : MAPGEN_TRAVERSAL_NONE;
        } else if (c && sscanf(line, " candidate %64s", word) == 1) {
            snprintf(c->candidate_sha256, sizeof(c->candidate_sha256), "%s",
                     word);
        } else if (c && sscanf(line, " donor %64s", word) == 1) {
            snprintf(c->donor_sha256, sizeof(c->donor_sha256), "%s", word);
        } else if (c && sscanf(line, " physics %64s", word) == 1) {
            snprintf(c->physics_sha256, sizeof(c->physics_sha256), "%s", word);
        } else if (c && sscanf(line, " entity %u %63s", &index, word) == 2) {
            c->entity_index = index;
            snprintf(c->classname, sizeof(c->classname), "%s", word);
        } else if (c && sscanf(line, " at %f %f %f", &c->entity_origin[0],
                               &c->entity_origin[1], &c->entity_origin[2])
                   == 3) {
            /* filled by the scan */
        } else if (c && sscanf(line, " launch %f %f %f", &c->launch[0],
                               &c->launch[1], &c->launch[2]) == 3) {
        } else if (c && sscanf(line, " touch %f %f %f", &c->touch[0],
                               &c->touch[1], &c->touch[2]) == 3) {
        } else if (c && sscanf(line, " landing %f %f %f", &c->landing[0],
                               &c->landing[1], &c->landing[2]) == 3) {
        } else if (c && sscanf(line, " cost %f damage, %f up",
                               &c->damage_taken, &c->height_gained) == 2) {
        } else if (c && sscanf(line, " replayed %u", &replayed) == 1) {
            /*
             * Read, and deliberately not trusted.
             *
             * Whether a map does what a certificate says is decided by
             * replaying it against that map, never by what the file it came in
             * says about itself.
             */
            c->replayed = false;
        } else if (c && strstr(line, "  needs ")) {
            c->needed_launcher = strstr(line, "launcher") != NULL;
            c->needed_rockets = strstr(line, "rockets") != NULL;
        } else if (c && sscanf(line, " demo %64s %63s",
                               c->demo_digest, c->demo_source) >= 1) {
            if (!strcmp(c->demo_digest, "-"))
                c->demo_digest[0] = '\0';
            if (!strcmp(c->demo_source, "-"))
                c->demo_source[0] = '\0';
        }

        if (!line_end)
            break;
        at = line_end + 1;
    }
    return out->count;
}
