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
 * MAPGEN-1 - aggregating analysed maps into a snapshot's chunks.
 *
 * Every source's own numbers are kept. The aggregate is derived from them at
 * serialization time, in canonical order, which is what makes the result
 * independent of the order eight workers happened to finish in.
 */

#include "common/mapgen_training.h"

#include <stdlib.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    char     name[MAPGEN_BSP_TEXNAME + 1];
    uint32_t roles;
    int32_t  surface_flags;
    int32_t  contents;
    /* The brightest a map in the corpus used it as a light, or 0. */
    int32_t  light_value;
    uint32_t sources;          /* how many maps used it                     */
    uint32_t uses;             /* total brushside references across them    */
} material_t;

typedef struct {
    mapgen_training_source_t identity;
    mapgen_features_vector_t features;
    bool                     has_features;
    /* The canonical blueprint text, owned here, or NULL when the source had
       no analysable space. */
    char                    *blueprint;
    uint64_t                 blueprint_digest;
    /* The canonical geometry text, owned here, or NULL when the caller had
       none to give. */
    char                    *geometry;
    uint64_t                 geometry_digest;
    uint32_t                 entity_roles[32];
    uint32_t                 materials;
} source_t;

/*
 * What one demo of one source saw.
 *
 * Held by the source's own SHA-256 rather than by its index, because sources
 * are sorted for rendering and an index would move under it.
 */
typedef struct {
    uint8_t  source_sha256[MAPGEN_SHA256_BYTES];
    char     physics_sha256[65];
    mapgen_demo_provenance_t provenance;
    uint32_t cells, jumps, drops, rides, swims;
} movement_t;

#define MAPGEN_TRAINING_MAX_MOVEMENT 4096u

struct mapgen_training_s {
    source_t  *sources;
    uint32_t   num_sources;
    uint32_t   capacity;

    movement_t *movement;
    uint32_t    num_movement;
    uint32_t    movement_capacity;

    material_t *materials;
    uint32_t    num_materials;
    uint32_t    material_capacity;

};

/* Is this a source this corpus actually has? */
static bool source_known(const mapgen_training_t *t,
                         const uint8_t sha256[MAPGEN_SHA256_BYTES])
{
    for (uint32_t i = 0; i < t->num_sources; i++)
        if (!memcmp(t->sources[i].identity.sha256, sha256,
                    MAPGEN_SHA256_BYTES))
            return true;
    return false;
}

mapgen_training_result_t MapGenTraining_AddMovement(
    mapgen_training_t *t,
    const uint8_t source_sha256[MAPGEN_SHA256_BYTES],
    const char *physics_sha256,
    const mapgen_demo_provenance_t *provenance,
    uint32_t cells, uint32_t jumps, uint32_t drops, uint32_t rides,
    uint32_t swims)
{
    if (!t || !source_sha256 || !provenance || !physics_sha256
        || !*physics_sha256)
        return MAPGEN_TRAINING_ERR_ARGS;
    /*
     * Evidence for a map this corpus does not have is refused.
     *
     * Filing it under nothing is how a corpus comes to contain movement that
     * belongs to a map it has never seen, and the whole point of the identity
     * is that somebody can check the two against each other later.
     */
    if (!source_known(t, source_sha256))
        return MAPGEN_TRAINING_ERR_ARGS;
    if (t->num_movement >= MAPGEN_TRAINING_MAX_MOVEMENT)
        return MAPGEN_TRAINING_ERR_TOO_MANY_SOURCES;

    if (t->num_movement == t->movement_capacity) {
        const uint32_t want = t->movement_capacity ? t->movement_capacity * 2
                                                   : 16u;
        movement_t *grown = realloc(t->movement, want * sizeof(*grown));
        if (!grown)
            return MAPGEN_TRAINING_ERR_MEMORY;
        t->movement = grown;
        t->movement_capacity = want;
    }

    movement_t *m = &t->movement[t->num_movement++];
    memset(m, 0, sizeof(*m));
    memcpy(m->source_sha256, source_sha256, MAPGEN_SHA256_BYTES);
    snprintf(m->physics_sha256, sizeof(m->physics_sha256), "%s",
             physics_sha256);
    m->provenance = *provenance;
    m->cells = cells;
    m->jumps = jumps;
    m->drops = drops;
    m->rides = rides;
    m->swims = swims;
    return MAPGEN_TRAINING_OK;
}

uint32_t MapGenTraining_NumMovement(const mapgen_training_t *t)
{
    return t ? t->num_movement : 0;
}

const char *MapGenTraining_ResultName(mapgen_training_result_t r)
{
    switch (r) {
    case MAPGEN_TRAINING_OK:                     return "OK";
    case MAPGEN_TRAINING_ERR_ARGS:               return "ERR_ARGS";
    case MAPGEN_TRAINING_ERR_MEMORY:             return "ERR_MEMORY";
    case MAPGEN_TRAINING_ERR_TOO_MANY_SOURCES:   return "ERR_TOO_MANY_SOURCES";
    case MAPGEN_TRAINING_ERR_TOO_MANY_MATERIALS: return "ERR_TOO_MANY_MATERIALS";
    case MAPGEN_TRAINING_ERR_NO_SOURCES:         return "ERR_NO_SOURCES";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenTraining_SourceStatusName(mapgen_source_status_t s)
{
    switch (s) {
    case MAPGEN_SOURCE_ACCEPTED:  return "accepted";
    case MAPGEN_SOURCE_DUPLICATE: return "duplicate";
    case MAPGEN_SOURCE_REJECTED:  return "rejected";
    }
    return "?";
}

/* ------------------------------------------------------------------------ */

mapgen_training_t *MapGenTraining_Create(void)
{
    return calloc(1, sizeof(mapgen_training_t));
}

void MapGenTraining_Free(mapgen_training_t *t)
{
    if (!t)
        return;
    for (uint32_t i = 0; i < t->num_sources; i++) {
        free(t->sources[i].blueprint);
        free(t->sources[i].geometry);
    }
    free(t->sources);
    free(t->materials);
    free(t->movement);
    free(t);
}

static void copy_bounded(char *dst, size_t cap, const char *src)
{
    memset(dst, 0, cap);
    if (!src)
        return;
    size_t n = strlen(src);
    if (n >= cap)
        n = cap - 1;
    /* The qpath comes from a file listing, so a control byte in it would
       reach a report and a UI. It is sanitized here, once. */
    for (size_t i = 0; i < n; i++)
        dst[i] = ((unsigned char)src[i] < 0x20 || src[i] == '\n') ? '?' : src[i];
}

static source_t *push_source(mapgen_training_t *t)
{
    if (t->num_sources >= MAPGEN_TRAINING_MAX_SOURCES)
        return NULL;
    if (t->num_sources == t->capacity) {
        uint32_t want = t->capacity ? t->capacity * 2u : 64u;
        if (want > MAPGEN_TRAINING_MAX_SOURCES)
            want = MAPGEN_TRAINING_MAX_SOURCES;
        void *grown = realloc(t->sources, (size_t)want * sizeof(source_t));
        if (!grown)
            return NULL;
        t->sources = grown;
        t->capacity = want;
    }
    source_t *s = &t->sources[t->num_sources++];
    memset(s, 0, sizeof(*s));
    return s;
}


static material_t *find_or_add_material(mapgen_training_t *t, const char *name)
{
    for (uint32_t i = 0; i < t->num_materials; i++)
        if (!strcmp(t->materials[i].name, name))
            return &t->materials[i];

    if (t->num_materials >= MAPGEN_TRAINING_MAX_MATERIALS)
        return NULL;
    if (t->num_materials == t->material_capacity) {
        uint32_t want = t->material_capacity ? t->material_capacity * 2u : 256u;
        if (want > MAPGEN_TRAINING_MAX_MATERIALS)
            want = MAPGEN_TRAINING_MAX_MATERIALS;
        void *grown = realloc(t->materials, (size_t)want * sizeof(material_t));
        if (!grown)
            return NULL;
        t->materials = grown;
        t->material_capacity = want;
    }
    material_t *m = &t->materials[t->num_materials++];
    memset(m, 0, sizeof(*m));
    copy_bounded(m->name, sizeof(m->name), name);
    return m;
}

mapgen_training_result_t MapGenTraining_AddSource(
    mapgen_training_t *t,
    const char *qpath, const char *provider, uint64_t bytes,
    const uint8_t sha256[MAPGEN_SHA256_BYTES],
    const mapgen_features_t *features,
    const mapgen_genome_t *genome,
    const mapgen_wiring_t *wiring,
    const mapgen_blueprint_t *blueprint,
    const mapgen_geometry_t *geometry)
{
    if (!t || !qpath || !sha256 || !features || !genome || !wiring)
        return MAPGEN_TRAINING_ERR_ARGS;

    source_t *s = push_source(t);
    if (!s)
        return MAPGEN_TRAINING_ERR_TOO_MANY_SOURCES;

    copy_bounded(s->identity.qpath, sizeof(s->identity.qpath), qpath);
    copy_bounded(s->identity.provider, sizeof(s->identity.provider), provider);
    s->identity.bytes = bytes;
    memcpy(s->identity.sha256, sha256, MAPGEN_SHA256_BYTES);

    /*
     * The architecture, copied here: the caller owns its blueprint and a
     * snapshot outlives the analysis that produced it. A source without one is
     * recorded as usual and simply cannot be an architecture donor.
     */
    if (blueprint) {
        const size_t needed = MapGenBlueprint_CanonicalText(blueprint, NULL, 0);
        s->blueprint = malloc(needed + 1);
        if (!s->blueprint)
            return MAPGEN_TRAINING_ERR_MEMORY;
        MapGenBlueprint_CanonicalText(blueprint, s->blueprint, needed + 1);
        s->blueprint_digest = MapGenBlueprint_CanonicalDigest(blueprint);
    }

    /*
     * The geometry, copied for the same reason: the caller owns it and a
     * snapshot outlives the analysis. This is the one a fidelity above zero
     * cannot do without - a source recorded with a blueprint and no geometry
     * knows where the donor's rooms were and nothing about what they were made
     * of, which is precisely the state the rejected delivery was built from.
     */
    if (geometry) {
        const size_t needed = MapGenGeometry_CanonicalText(geometry, NULL, 0);
        s->geometry = malloc(needed + 1);
        if (!s->geometry)
            return MAPGEN_TRAINING_ERR_MEMORY;
        MapGenGeometry_CanonicalText(geometry, s->geometry, needed + 1);
        s->geometry_digest = MapGenGeometry_CanonicalDigest(geometry);
    }

    /*
     * Whether this source is the ACCEPTED member of its SHA-256 group or a
     * DUPLICATE is NOT decided here, and that is the point. Deciding it on
     * arrival makes the answer depend on which worker finished first: offering
     * `aerowalk.bsp` and `q2duel1.bsp` - byte-identical files under different
     * names - in one order or the other produced two different payloads, which
     * contract 8 forbids outright. The decision is made in canonical order at
     * serialization time instead.
     */
    s->identity.status = MAPGEN_SOURCE_ACCEPTED;
    s->features = *MapGenFeatures_Vector(features);
    s->has_features = true;

    const uint32_t material_count = MapGenGenome_NumMaterials(genome);
    s->materials = material_count;
    for (uint32_t i = 0; i < material_count; i++) {
        const mapgen_material_t *src = MapGenGenome_Material(genome, i);
        material_t *m = find_or_add_material(t, src->name);
        if (!m)
            return MAPGEN_TRAINING_ERR_TOO_MANY_MATERIALS;
        m->roles |= src->roles;
        m->surface_flags |= src->surface_flags;
        m->contents |= src->contents;
        /* The brightest, not a union: these are watts, not flags. */
        if (src->light_value > m->light_value)
            m->light_value = src->light_value;
        m->sources++;
        m->uses += src->brushside_refs;
    }

    for (uint32_t i = 0; i < MapGenWiring_NumEntities(wiring); i++) {
        const mapgen_wiring_entity_t *e = MapGenWiring_Entity(wiring, i);
        for (uint32_t bit = 0; bit < 32; bit++)
            if (e->roles & (1u << bit))
                s->entity_roles[bit]++;
    }

    return MAPGEN_TRAINING_OK;
}

mapgen_training_result_t MapGenTraining_RejectSource(
    mapgen_training_t *t,
    const char *qpath, const char *provider, uint64_t bytes,
    const uint8_t sha256[MAPGEN_SHA256_BYTES])
{
    if (!t || !qpath || !sha256)
        return MAPGEN_TRAINING_ERR_ARGS;
    source_t *s = push_source(t);
    if (!s)
        return MAPGEN_TRAINING_ERR_TOO_MANY_SOURCES;
    copy_bounded(s->identity.qpath, sizeof(s->identity.qpath), qpath);
    copy_bounded(s->identity.provider, sizeof(s->identity.provider), provider);
    s->identity.bytes = bytes;
    memcpy(s->identity.sha256, sha256, MAPGEN_SHA256_BYTES);
    s->identity.status = MAPGEN_SOURCE_REJECTED;
    return MAPGEN_TRAINING_OK;
}


/* ------------------------------------------------------------------------ */
/* Canonical order: (SHA-256, provider, qpath). Never arrival order.         */

static int compare_sources(const void *a, const void *b)
{
    const source_t *x = a, *y = b;
    int c = memcmp(x->identity.sha256, y->identity.sha256, MAPGEN_SHA256_BYTES);
    if (c)
        return c;
    c = strcmp(x->identity.provider, y->identity.provider);
    if (c)
        return c;
    return strcmp(x->identity.qpath, y->identity.qpath);
}

static int compare_materials(const void *a, const void *b)
{
    return strcmp(((const material_t *)a)->name, ((const material_t *)b)->name);
}

/*
 * Sort canonically, then decide the duplicates.
 *
 * Within one SHA-256 group the FIRST source in canonical order is the accepted
 * one and the rest are duplicates. Because the order is canonical, so is the
 * decision - the same maps offered in any order produce the same answer, which
 * is what contract 8 means by "independent of worker completion".
 */
static source_t *sorted_sources(const mapgen_training_t *t)
{
    if (!t->num_sources)
        return NULL;
    source_t *copy = malloc((size_t)t->num_sources * sizeof(source_t));
    if (!copy)
        return NULL;
    memcpy(copy, t->sources, (size_t)t->num_sources * sizeof(source_t));
    qsort(copy, t->num_sources, sizeof(source_t), compare_sources);

    for (uint32_t i = 0; i < t->num_sources; i++) {
        if (copy[i].identity.status == MAPGEN_SOURCE_REJECTED)
            continue;               /* a rejection is not a duplicate */
        copy[i].identity.status = MAPGEN_SOURCE_ACCEPTED;
        for (uint32_t j = 0; j < i; j++) {
            if (copy[j].identity.status == MAPGEN_SOURCE_ACCEPTED &&
                !memcmp(copy[j].identity.sha256, copy[i].identity.sha256,
                        MAPGEN_SHA256_BYTES)) {
                copy[i].identity.status = MAPGEN_SOURCE_DUPLICATE;
                break;
            }
        }
    }
    return copy;
}

/* The counts are derived from that resolution rather than incremented on
   arrival, for exactly the same reason. */
static void tally(const mapgen_training_t *t, uint32_t *accepted,
                  uint32_t *duplicates, uint32_t *rejected)
{
    *accepted = *duplicates = *rejected = 0;
    source_t *sorted = sorted_sources(t);
    if (!sorted)
        return;
    for (uint32_t i = 0; i < t->num_sources; i++) {
        switch (sorted[i].identity.status) {
        case MAPGEN_SOURCE_ACCEPTED:  (*accepted)++; break;
        case MAPGEN_SOURCE_DUPLICATE: (*duplicates)++; break;
        case MAPGEN_SOURCE_REJECTED:  (*rejected)++; break;
        default: break;
        }
    }
    free(sorted);
}

uint32_t MapGenTraining_NumSources(const mapgen_training_t *t)
{
    return t ? t->num_sources : 0;
}

uint32_t MapGenTraining_NumAccepted(const mapgen_training_t *t)
{
    if (!t)
        return 0;
    uint32_t a, d, r;
    tally(t, &a, &d, &r);
    return a;
}

uint32_t MapGenTraining_NumDuplicates(const mapgen_training_t *t)
{
    if (!t)
        return 0;
    uint32_t a, d, r;
    tally(t, &a, &d, &r);
    return d;
}

uint32_t MapGenTraining_NumRejected(const mapgen_training_t *t)
{
    if (!t)
        return 0;
    uint32_t a, d, r;
    tally(t, &a, &d, &r);
    return r;
}

uint32_t MapGenTraining_NumMaterials(const mapgen_training_t *t)
{
    return t ? t->num_materials : 0;
}

bool MapGenTraining_LowDiversity(const mapgen_training_t *t)
{
    return MapGenTraining_NumAccepted(t) < MAPGEN_TRAINING_LOW_DIVERSITY;
}

bool MapGenTraining_SourceAt(const mapgen_training_t *t, uint32_t index,
                             mapgen_training_source_t *out)
{
    /* The public order is the canonical one, so a caller that walks sources
       sees what the snapshot will contain rather than what arrived first. */
    if (!t || !out || index >= t->num_sources)
        return false;
    source_t *sorted = sorted_sources(t);
    if (!sorted)
        return false;
    *out = sorted[index].identity;
    free(sorted);
    return true;
}

/* ------------------------------------------------------------------------ */

typedef struct {
    char  *out;
    size_t capacity;
    size_t needed;
} sink_t;

static void sink_str(sink_t *s, const char *text)
{
    const size_t n = strlen(text);
    if (s->out && s->needed < s->capacity) {
        const size_t room = s->capacity - 1 - s->needed;
        memcpy(s->out + s->needed, text, n < room ? n : room);
    }
    s->needed += n;
}

static void sink_i64(sink_t *s, int64_t v)
{
    char buf[24];
    size_t n = 0;
    uint64_t m;
    if (v < 0) {
        buf[n++] = '-';
        m = (uint64_t)(-(v + 1)) + 1u;
    } else {
        m = (uint64_t)v;
    }
    char tmp[24];
    size_t k = 0;
    if (!m) {
        tmp[k++] = '0';
    } else {
        while (m) {
            tmp[k++] = (char)('0' + (m % 10u));
            m /= 10u;
        }
    }
    while (k)
        buf[n++] = tmp[--k];
    buf[n] = '\0';
    sink_str(s, buf);
}

static void sink_hex(sink_t *s, const uint8_t *bytes, size_t count)
{
    char hex[3] = { 0, 0, 0 };
    static const char DIGITS[] = "0123456789abcdef";
    for (size_t i = 0; i < count; i++) {
        hex[0] = DIGITS[(bytes[i] >> 4) & 0xFu];
        hex[1] = DIGITS[bytes[i] & 0xFu];
        sink_str(s, hex);
    }
}

static void row_i64(sink_t *s, const char *name, int64_t value)
{
    sink_str(s, name);
    sink_str(s, "=");
    sink_i64(s, value);
    sink_str(s, "\n");
}

/* Aggregates over the ACCEPTED sources only, one feature at a time. */
typedef struct {
    uint64_t total;
    uint32_t min;
    uint32_t max;
    uint32_t median;
} aggregate_t;

static int compare_u32(const void *a, const void *b)
{
    const uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

static aggregate_t aggregate_of(const source_t *sorted, uint32_t count,
                                size_t offset, uint32_t *scratch)
{
    aggregate_t agg = { 0, UINT32_MAX, 0, 0 };
    uint32_t n = 0;
    for (uint32_t i = 0; i < count; i++) {
        if (sorted[i].identity.status != MAPGEN_SOURCE_ACCEPTED || !sorted[i].has_features)
            continue;
        const uint32_t v = *(const uint32_t *)((const uint8_t *)&sorted[i].features + offset);
        scratch[n++] = v;
        agg.total += v;
        if (v < agg.min) agg.min = v;
        if (v > agg.max) agg.max = v;
    }
    if (!n) {
        agg.min = 0;
        return agg;
    }
    qsort(scratch, n, sizeof(uint32_t), compare_u32);
    agg.median = scratch[n / 2];
    return agg;
}

#define FEATURE(name) { #name, offsetof(mapgen_features_vector_t, name) }

static const struct { const char *name; size_t offset; } FEATURES[] = {
    FEATURE(nodes), FEATURE(regions), FEATURE(largest_region_permille),
    FEATURE(median_clearance), FEATURE(open_permille), FEATURE(vertical_span),
    FEATURE(height_bands), FEATURE(edges), FEATURE(mean_walk_degree_milli),
    FEATURE(chokepoints), FEATURE(bridges), FEATURE(loops),
    FEATURE(bridge_permille), FEATURE(cover_permille),
    FEATURE(mean_sight_length), FEATURE(max_sight_length),
    FEATURE(hazard_permille), FEATURE(positioned_entities),
    FEATURE(items_bound), FEATURE(spawns_bound), FEATURE(mean_item_separation),
};

#undef FEATURE

size_t MapGenTraining_ChunkText(const mapgen_training_t *t, uint32_t chunk_type,
                                char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!t) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    source_t *sorted = sorted_sources(t);
    uint32_t accepted = 0, duplicates = 0, rejected = 0;
    tally(t, &accepted, &duplicates, &rejected);

    switch (chunk_type) {
    case MAPGEN_CHUNK_META:
        sink_str(&s, "schema=1.0\n");
        sink_str(&s, "producer=q2prox-mapgen\n");
        row_i64(&s, "sources", t->num_sources);
        row_i64(&s, "accepted", accepted);
        break;

    case MAPGEN_CHUNK_SOURCES:
        row_i64(&s, "count", t->num_sources);
        for (uint32_t i = 0; i < t->num_sources && sorted; i++) {
            const mapgen_training_source_t *id = &sorted[i].identity;
            sink_str(&s, "s=");
            sink_hex(&s, id->sha256, MAPGEN_SHA256_BYTES);
            sink_str(&s, ",");
            sink_str(&s, id->provider);
            sink_str(&s, ",");
            sink_str(&s, id->qpath);
            sink_str(&s, ",");
            sink_i64(&s, (int64_t)id->bytes);
            sink_str(&s, ",");
            sink_str(&s, MapGenTraining_SourceStatusName(
                         (mapgen_source_status_t)id->status));
            sink_str(&s, "\n");
        }
        break;

    case MAPGEN_CHUNK_MATERIALS: {
        material_t *materials = NULL;
        if (t->num_materials) {
            materials = malloc((size_t)t->num_materials * sizeof(material_t));
            if (materials) {
                memcpy(materials, t->materials,
                       (size_t)t->num_materials * sizeof(material_t));
                qsort(materials, t->num_materials, sizeof(material_t),
                      compare_materials);
            }
        }
        row_i64(&s, "count", t->num_materials);
        for (uint32_t i = 0; i < t->num_materials && materials; i++) {
            const material_t *m = &materials[i];
            sink_str(&s, "m=");
            sink_str(&s, m->name);
            sink_str(&s, ",");
            sink_i64(&s, m->roles); sink_str(&s, ",");
            sink_i64(&s, m->surface_flags); sink_str(&s, ",");
            sink_i64(&s, m->contents); sink_str(&s, ",");
            sink_i64(&s, m->light_value); sink_str(&s, ",");
            sink_i64(&s, m->sources); sink_str(&s, ",");
            sink_i64(&s, m->uses); sink_str(&s, "\n");
        }
        free(materials);
        break;
    }

    case MAPGEN_CHUNK_REGIONS:
        /*
         * The spatial motifs, per source.
         *
         * Each row names the source it came from. Without that, pairing a
         * statistic with its source would depend on this chunk's row order
         * matching the accepted-source order in SOURCES - an implicit coupling
         * between two chunks - and mixing needs IDENTITY, not position: a map
         * two snapshots both learned from has to be recognised as one map in
         * both, which is a question about its hash and not about where it
         * happens to sit in a list.
         */
        row_i64(&s, "count", accepted);
        for (uint32_t i = 0; i < t->num_sources && sorted; i++) {
            if (sorted[i].identity.status != MAPGEN_SOURCE_ACCEPTED)
                continue;
            /*
             * The source's ARCHITECTURE, under its own hash.
             *
             * Every volume and portal in it carries provenance back to this
             * map, which is what lets a donor be recognised in a hybrid and
             * what a fidelity ledger measures against. A source whose space
             * could not be analysed contributes no rows and can never be a
             * donor.
             */
            if (!sorted[i].blueprint)
                continue;
            sink_str(&s, "b=");
            sink_hex(&s, sorted[i].identity.sha256, MAPGEN_SHA256_BYTES);
            sink_str(&s, ",");
            sink_i64(&s, (int64_t)sorted[i].blueprint_digest);
            sink_str(&s, "\n");
            sink_str(&s, sorted[i].blueprint);
        }
        break;

    case MAPGEN_CHUNK_ENTITIES: {
        uint32_t totals[32] = { 0 };
        for (uint32_t i = 0; i < t->num_sources && sorted; i++) {
            if (sorted[i].identity.status != MAPGEN_SOURCE_ACCEPTED)
                continue;
            for (uint32_t bit = 0; bit < 32; bit++)
                totals[bit] += sorted[i].entity_roles[bit];
        }
        row_i64(&s, "roles", 32);
        for (uint32_t bit = 0; bit < 32; bit++) {
            const char *names[MAPGEN_WIRING_MAX_ROLE_NAMES];
            const uint32_t n = MapGenWiring_RoleNames(1u << bit, names,
                                                      MAPGEN_WIRING_MAX_ROLE_NAMES);
            sink_str(&s, "e=");
            sink_str(&s, n ? names[0] : "reserved");
            sink_str(&s, ",");
            sink_i64(&s, totals[bit]);
            sink_str(&s, "\n");
        }
        break;
    }

    case MAPGEN_CHUNK_STATS: {
        /*
         * The aggregates. They used to live in REGIONS, which now carries the
         * architecture instead - a row of counts and shares describes nothing
         * about where anything is.
         */
        for (uint32_t i = 0; i < t->num_sources && sorted; i++) {
            if (sorted[i].identity.status != MAPGEN_SOURCE_ACCEPTED)
                continue;
            const mapgen_features_vector_t *v = &sorted[i].features;
            sink_str(&s, "r=");
            sink_hex(&s, sorted[i].identity.sha256, MAPGEN_SHA256_BYTES);
            sink_str(&s, ",");
            sink_i64(&s, v->nodes); sink_str(&s, ",");
            sink_i64(&s, v->regions); sink_str(&s, ",");
            sink_i64(&s, v->largest_region_permille); sink_str(&s, ",");
            sink_i64(&s, v->height_bands); sink_str(&s, ",");
            sink_i64(&s, v->vertical_span); sink_str(&s, ",");
            sink_i64(&s, v->open_permille); sink_str(&s, ",");
            sink_i64(&s, v->lights); sink_str(&s, ",");
            sink_i64(&s, v->light_median); sink_str(&s, ",");
            sink_i64(&s, v->light_lower); sink_str(&s, ",");
            sink_i64(&s, v->light_upper); sink_str(&s, ",");
            for (uint32_t c = 0; c < MAPGEN_FEATURES_LIGHT_COLOURS; c++) {
                sink_i64(&s, v->light_colours[c]);
                sink_str(&s, ",");
            }
            sink_i64(&s, v->sky_permille); sink_str(&s, "\n");
        }
        uint32_t *scratch = t->num_sources
                          ? malloc((size_t)t->num_sources * sizeof(uint32_t)) : NULL;
        row_i64(&s, "features", (int64_t)(sizeof(FEATURES) / sizeof(FEATURES[0])));
        row_i64(&s, "population", accepted);
        for (size_t f = 0; f < sizeof(FEATURES) / sizeof(FEATURES[0]); f++) {
            aggregate_t agg = { 0, 0, 0, 0 };
            if (sorted && scratch)
                agg = aggregate_of(sorted, t->num_sources, FEATURES[f].offset, scratch);
            sink_str(&s, "f=");
            sink_str(&s, FEATURES[f].name);
            sink_str(&s, ",");
            sink_i64(&s, agg.min); sink_str(&s, ",");
            sink_i64(&s, agg.median); sink_str(&s, ",");
            sink_i64(&s, agg.max); sink_str(&s, ",");
            /* The mean is integer division of a 64-bit total, so it cannot
               drift with the order the sources were summed in. */
            sink_i64(&s, accepted ? (int64_t)(agg.total / accepted) : 0);
            sink_str(&s, "\n");
        }
        free(scratch);
        break;
    }

    case MAPGEN_CHUNK_SHAPES:
        /*
         * The bounds a reader checks BEFORE it allocates. A payload sized by
         * whatever the file claims is a payload that chooses how much memory
         * the reader spends.
         */
        row_i64(&s, "max_volumes", MAPGEN_BLUEPRINT_MAX_VOLUMES);
        row_i64(&s, "max_portals", MAPGEN_BLUEPRINT_MAX_PORTALS);
        row_i64(&s, "basis", MAPGEN_BLUEPRINT_BASIS);
        row_i64(&s, "occupancy_scale", 1000);
        for (uint32_t i = 0; i < t->num_sources && sorted; i++) {
            if (sorted[i].identity.status != MAPGEN_SOURCE_ACCEPTED
                || !sorted[i].blueprint)
                continue;
            /*
             * One row per donor: its hash and the digest of the blueprint the
             * occupancy belongs to, so a shape can never be read against a
             * different architecture than the one it was measured from.
             */
            sink_str(&s, "s=");
            sink_hex(&s, sorted[i].identity.sha256, MAPGEN_SHA256_BYTES);
            sink_str(&s, ",");
            sink_i64(&s, (int64_t)sorted[i].blueprint_digest);
            sink_str(&s, "\n");
        }
        break;

    case MAPGEN_CHUNK_GEOMETRY:
        /*
         * The bounds first, as everywhere else: a payload sized by whatever
         * the file claims is a payload that decides how much memory the
         * reader spends.
         */
        row_i64(&s, "max_donors", MAPGEN_SNAPSHOT_MAX_GEOM_DONORS);
        row_i64(&s, "max_brushes", MAPGEN_SNAPSHOT_MAX_GEOM_BRUSHES);
        row_i64(&s, "max_sides", MAPGEN_SNAPSHOT_MAX_GEOM_SIDES);
        row_i64(&s, "max_faces", MAPGEN_SNAPSHOT_MAX_GEOM_FACES);
        row_i64(&s, "max_points", MAPGEN_SNAPSHOT_MAX_GEOM_POINTS);
        row_i64(&s, "max_entities", MAPGEN_SNAPSHOT_MAX_GEOM_ENTITIES);
        row_i64(&s, "max_text_bytes", MAPGEN_SNAPSHOT_MAX_GEOM_TEXT);
        for (uint32_t i = 0; i < t->num_sources && sorted; i++) {
            if (sorted[i].identity.status != MAPGEN_SOURCE_ACCEPTED
                || !sorted[i].geometry)
                continue;
            /*
             * The donor's hash, the digest of the geometry, and then the
             * geometry itself. The hash and the digest travel together so a
             * candidate can never be built from one donor's solids while
             * claiming another donor's provenance.
             */
            sink_str(&s, "g=");
            sink_hex(&s, sorted[i].identity.sha256, MAPGEN_SHA256_BYTES);
            sink_str(&s, ",");
            sink_i64(&s, (int64_t)sorted[i].geometry_digest);
            sink_str(&s, "\n");
            sink_str(&s, sorted[i].geometry);
        }
        break;

    case MAPGEN_CHUNK_QUALITY:
        row_i64(&s, "sources", t->num_sources);
        row_i64(&s, "accepted", accepted);
        row_i64(&s, "duplicates", duplicates);
        row_i64(&s, "rejected", rejected);
        row_i64(&s, "materials", t->num_materials);
        row_i64(&s, "low_diversity", MapGenTraining_LowDiversity(t) ? 1 : 0);
        sink_str(&s, "warning=");
        sink_str(&s, MapGenTraining_LowDiversity(t)
                 ? "few_sources_low_confidence" : "none");
        sink_str(&s, "\n");
        break;

    case MAPGEN_CHUNK_MOVEMENT:
        /*
         * One row per demo, in the order they were contributed. Not sorted:
         * the order a corpus was walked in is itself provenance, and two runs
         * over the same corpus walk it the same way.
         */
        row_i64(&s, "count", t->num_movement);
        for (uint32_t i = 0; i < t->num_movement; i++) {
            const movement_t *m = &t->movement[i];
            const mapgen_demo_provenance_t *p = &m->provenance;
            sink_str(&s, "m=");
            sink_hex(&s, m->source_sha256, MAPGEN_SHA256_BYTES);
            sink_str(&s, ",");
            sink_str(&s, m->physics_sha256);
            sink_str(&s, ",");
            sink_str(&s, p->map);
            sink_str(&s, ",");
            sink_str(&s, p->gamedir);
            sink_str(&s, ",");
            sink_str(&s, p->source);
            sink_str(&s, ",");
            sink_str(&s, p->digest);
            sink_str(&s, ",");
            sink_i64(&s, p->protocol); sink_str(&s, ",");
            sink_i64(&s, p->pov_slot); sink_str(&s, ",");
            sink_i64(&s, (int64_t)p->quality); sink_str(&s, ",");
            sink_i64(&s, p->duration_ms); sink_str(&s, ",");
            sink_i64(&s, (int64_t)p->samples); sink_str(&s, ",");
            sink_i64(&s, (int64_t)m->cells); sink_str(&s, ",");
            sink_i64(&s, (int64_t)m->jumps); sink_str(&s, ",");
            sink_i64(&s, (int64_t)m->drops); sink_str(&s, ",");
            sink_i64(&s, (int64_t)m->rides); sink_str(&s, ",");
            sink_i64(&s, (int64_t)m->swims); sink_str(&s, "\n");
        }
        break;

    default:
        break;
    }

    free(sorted);
    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

mapgen_training_result_t MapGenTraining_FillSnapshot(const mapgen_training_t *t,
                                                     mapgen_snapshot_builder_t *b,
                                                     mapgen_compression_t compression)
{
    if (!t || !b)
        return MAPGEN_TRAINING_ERR_ARGS;
    if (!MapGenTraining_NumAccepted(t))
        return MAPGEN_TRAINING_ERR_NO_SOURCES;

    /*
     * The required chunks, and then movement if there is any.
     *
     * Movement is not in the required range on purpose: a corpus nobody has
     * demos for has not been played, which is not the same as broken, and a
     * snapshot that carried an empty movement chunk would say the opposite.
     */
    for (uint32_t type = MAPGEN_CHUNK_META;
         type <= (t->num_movement ? MAPGEN_CHUNK_MOVEMENT
                                  : MAPGEN_CHUNK_GEOMETRY);
         type++) {
        if (type == MAPGEN_CHUNK_MOVEMENT && !t->num_movement)
            continue;
        const size_t needed = MapGenTraining_ChunkText(t, type, NULL, 0);
        char *text = malloc(needed + 1);
        if (!text)
            return MAPGEN_TRAINING_ERR_MEMORY;
        MapGenTraining_ChunkText(t, type, text, needed + 1);
        const mapgen_snapshot_result_t r =
            MapGenSnapshot_AddChunk(b, type, text, needed, compression);
        free(text);
        if (r != MAPGEN_SNAPSHOT_OK)
            return MAPGEN_TRAINING_ERR_MEMORY;
    }
    return MAPGEN_TRAINING_OK;
}
