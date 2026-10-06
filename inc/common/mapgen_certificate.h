/*
 * MapGenCertificate - why an item nobody can walk to is still reachable.
 *
 * Codex's ruling of 2026-09-02 on q2dm1 widened "reachable" to include the
 * traversals Quake II actually has, and then asked the harder question: what
 * makes such a claim CHECKABLE later. A number in a report - "two pickups
 * reached by rocket jump" - is not evidence. It says nothing about which
 * pickups, from where, at what cost, under which physics, or whether the map
 * it was true of is the map somebody is holding.
 *
 * So a special traversal that lets a candidate pass writes down what it
 * actually did:
 *
 *   the map it is about, by hash, and the donor that map came from;
 *   the entity it is about, by classname and where it stands;
 *   the traversal, by kind, and the physics the arithmetic came from;
 *   the three states - where he launched, where he touched it, where he came
 *   down - because those are what a replay reproduces;
 *   what he had to have: the launcher, the rockets, the damage he took and
 *   the height he gained, which is the access envelope;
 *   and where the movement evidence came from, when it came from a demo.
 *
 * The one thing a certificate is NOT is an input. Nothing in the reachability
 * gate reads one: every run re-derives its own witnesses against the compiled
 * candidate in front of it, and a certificate that disagrees with what this
 * map does is the certificate that is wrong. That is the whole difference
 * between evidence and a cached permission, and it is the reason a stale
 * certificate can be refused rather than believed.
 */

#ifndef MAPGEN_CERTIFICATE_H
#define MAPGEN_CERTIFICATE_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_bsp.h"

#define MAPGEN_CERT_MAX       64u
#define MAPGEN_CERT_NAME      64u
#define MAPGEN_CERT_SHA_HEX   65u

typedef enum {
    MAPGEN_TRAVERSAL_NONE = 0,
    /* Stock Quake II: he fires at his own feet and rides the blast. The
       arithmetic and its sources are in mapgen_reach.c. */
    MAPGEN_TRAVERSAL_ROCKET_JUMP
} mapgen_traversal_kind_t;

const char *MapGenCertificate_KindName(mapgen_traversal_kind_t kind);

typedef struct {
    /* --- what map, and what it came from ------------------------------- */
    char     candidate_sha256[MAPGEN_CERT_SHA_HEX];
    char     donor_sha256[MAPGEN_CERT_SHA_HEX];

    /* --- what in it ---------------------------------------------------- */
    char     classname[MAPGEN_CERT_NAME];
    float    entity_origin[3];
    uint32_t entity_index;              /* the gate's own ordinal          */

    /* --- how ----------------------------------------------------------- */
    mapgen_traversal_kind_t kind;
    char     physics_sha256[MAPGEN_CERT_SHA_HEX];

    /* --- the three states a replay reproduces -------------------------- */
    float    launch[3];
    float    touch[3];
    float    landing[3];

    /* --- the access envelope ------------------------------------------- */
    bool     needed_launcher;
    bool     needed_rockets;
    float    damage_taken;              /* what the blast costs him        */
    float    height_gained;

    /* --- where the movement evidence came from, if a demo -------------- */
    char     demo_digest[MAPGEN_CERT_SHA_HEX];
    char     demo_source[MAPGEN_CERT_NAME];

    /* Set by a replay against a compiled map, never by the writer. */
    bool     replayed;
} mapgen_certificate_t;

typedef struct {
    mapgen_certificate_t entries[MAPGEN_CERT_MAX];
    uint32_t             count;
    /* The map had more special traversals than this can hold. A caller that
       went on would be publishing a partial account of why its map passed. */
    bool                 overflowed;
} mapgen_certificate_set_t;

typedef enum {
    MAPGEN_CERT_OK = 0,
    MAPGEN_CERT_ERR_ARGS,
    /* It is about a different map, a different donor, or different physics. */
    MAPGEN_CERT_ERR_STALE,
    /* It is about this map and this map does not do it. */
    MAPGEN_CERT_ERR_NOT_REPRODUCED,
    /* It claims a traversal nothing here knows how to check. */
    MAPGEN_CERT_ERR_UNSUPPORTED,
    MAPGEN_CERT_ERR_MEMORY
} mapgen_certificate_result_t;

const char *MapGenCertificate_ResultName(mapgen_certificate_result_t r);

/*
 * Write the identity onto every certificate in a set.
 *
 * The search that produces them knows the geometry and nothing about hashes;
 * whoever compiled the candidate knows the hashes and nothing about the
 * geometry. Stamping is where the two meet, and a set that was never stamped
 * carries empty hashes - which Verify refuses, because a certificate about no
 * particular map is about every map.
 */
void MapGenCertificate_Stamp(mapgen_certificate_set_t *set,
                             const char *candidate_sha256,
                             const char *donor_sha256,
                             const char *physics_sha256);

/*
 * Is this certificate about the map in front of us?
 *
 * Identity only - the hashes and a traversal this build knows. It is the cheap
 * half, and it is the half that catches a certificate carried over from the
 * candidate before this one.
 */
mapgen_certificate_result_t
MapGenCertificate_Verify(const mapgen_certificate_t *cert,
                         const char *candidate_sha256,
                         const char *donor_sha256,
                         const char *physics_sha256);

/*
 * And does the map actually do it?
 *
 * The expensive half: the compiled candidate is explored again and the
 * certificate has to appear in what THIS map produces - same entity, same
 * launch, same touch, same landing, to within a player's own width. A
 * certificate whose launch ledge an edit has since carved away does not
 * survive this, which is exactly what it is for.
 *
 * `bsp` must be the map the certificate names; Verify is called first and its
 * failure is returned unchanged.
 */
mapgen_certificate_result_t
MapGenCertificate_Replay(mapgen_certificate_t *cert, const mapgen_bsp_t *bsp,
                         const char *candidate_sha256,
                         const char *donor_sha256,
                         const char *physics_sha256);

/*
 * The set as text, one certificate per block, in the order they were found.
 *
 * Ordered and locale-free so two runs of one candidate produce the same bytes,
 * which is what lets a snapshot carry them and a report quote them.
 */
size_t MapGenCertificate_Render(const mapgen_certificate_set_t *set, char *out,
                                size_t size);

/* And back, for reading what a snapshot carried. Returns how many were read. */
uint32_t MapGenCertificate_Parse(const char *text,
                                 mapgen_certificate_set_t *out);

#endif /* MAPGEN_CERTIFICATE_H */
