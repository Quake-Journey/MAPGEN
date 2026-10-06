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
 * MAPGEN-1 - mixing several snapshots into one immutable model.
 *
 * Everything is checked before anything is combined: the pin against the file,
 * the physics and schema hashes against each other, the weights against their
 * range. Only then is a model built, and it owns every byte it reports.
 */

#include "common/mapgen_mix.h"
#include "common/mapgen_wiring.h"

#include <stdlib.h>
#include <string.h>

#define MATERIAL_NAME_BYTES  33         /* the format's own texture name cap */
#define SOURCE_HEX_BYTES     65

typedef struct {
    char     name[MATERIAL_NAME_BYTES];
    /*
     * How often to draw this material.
     *
     * The corpus's own usage - total brush-side references - scaled by the
     * weight of the snapshot it came from. It used to be the snapshot weight
     * alone, which made every texture in the allowlist equally likely: a map
     * learned from q2dm1 drew its incidentals as often as the ochre it is
     * built out of, and came out grey.
     */
    uint64_t weight;
    uint32_t snapshots;
    /* What the corpus used it as, unioned across the snapshots that have it. */
    uint32_t roles;
    int32_t  surface_flags;
    int32_t  light_value;
    int32_t  contents;
} material_t;

/* An architecture donor: a source whose blueprint a Recipe may preserve. */
typedef struct {
    char     hex[SOURCE_HEX_BYTES];
    uint64_t weight;
    uint32_t snapshots;
    /* The donor's canonical blueprint text, owned here. This is the map's
       architecture; without it a donor is only a name. */
    char    *blueprint;
    uint64_t blueprint_digest;
} donor_t;

typedef struct {
    char     hex[SOURCE_HEX_BYTES];
    uint32_t snapshots;
} source_t;

/*
 * One learned map: the six statistics it was measured to have, and the summed
 * normalized weight of the selections that carry it.
 */
typedef struct {
    char     hex[SOURCE_HEX_BYTES];
    int64_t  values[MAPGEN_MIX_STAT_COUNT];
    uint64_t weight;
    uint32_t snapshots;
} sample_t;

struct mapgen_mix_s {
    uint32_t  num_inputs;
    uint32_t *weight_ppm;

    material_t *materials;
    uint32_t    num_materials;

    source_t *sources;
    uint32_t  num_sources;
    uint32_t  shared_sources;

    sample_t *samples;
    uint32_t  num_samples;
    /* The architecture donors, deduplicated by source hash. */
    donor_t  *donors;
    uint32_t  num_donors;
    uint64_t  sample_weight_total;

    /* One bit per MAPGEN_ROLE_*: set when any selected snapshot learned it. */
    uint32_t learned_roles;

    uint64_t material_weight_total;
    bool     repeated_influence;

    bool     has_manifest;
    /* Names the target cannot resolve, once each. */
    char   (*unavailable)[MATERIAL_NAME_BYTES];
    uint32_t unavailable_materials;
};

const char *MapGenMix_ResultName(mapgen_mix_result_t r)
{
    switch (r) {
    case MAPGEN_MIX_OK:                    return "OK";
    case MAPGEN_MIX_ERR_ARGS:              return "ERR_ARGS";
    case MAPGEN_MIX_ERR_MEMORY:            return "ERR_MEMORY";
    case MAPGEN_MIX_ERR_NO_INPUTS:         return "ERR_NO_INPUTS";
    case MAPGEN_MIX_ERR_TOO_MANY_INPUTS:   return "ERR_TOO_MANY_INPUTS";
    case MAPGEN_MIX_ERR_BAD_WEIGHT:        return "ERR_BAD_WEIGHT";
    case MAPGEN_MIX_ERR_PIN_MISMATCH:      return "ERR_PIN_MISMATCH";
    case MAPGEN_MIX_ERR_NEEDS_REBUILD:     return "ERR_NEEDS_REBUILD";
    case MAPGEN_MIX_ERR_DUPLICATE_REVISION: return "ERR_DUPLICATE_REVISION";
    }
    return "ERR_UNKNOWN";
}

/* ------------------------------------------------------------------------ */

/* Walk `prefix`-led lines of a chunk, handing each line's body to `visit`. */
static void for_each_row(const mapgen_snapshot_t *snap, uint32_t chunk,
                         const char *prefix,
                         void (*visit)(const uint8_t *body, size_t length, void *ctx),
                         void *ctx)
{
    size_t size = 0;
    const uint8_t *text = MapGenSnapshot_Chunk(snap, chunk, &size);
    if (!text)
        return;
    const size_t n = strlen(prefix);
    for (size_t i = 0; i + n <= size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (memcmp(text + i, prefix, n))
            continue;
        size_t end = i + n;
        while (end < size && text[end] != '\n')
            end++;
        visit(text + i + n, end - (i + n), ctx);
    }
}

/* --- materials ------------------------------------------------------------ */

typedef struct {
    mapgen_mix_t *mix;
    uint64_t      weight;
    bool          failed;
    /* Contract 15's target manifest, or NULL when the caller supplied none. */
    const char *const *available;
    uint32_t           num_available;
} material_ctx_t;

/* One `,`-separated signed integer field. */
static bool material_field(const uint8_t *body, size_t length, size_t *at,
                           int64_t *out)
{
    if (*at >= length)
        return false;
    bool negative = false;
    if (body[*at] == '-') {
        negative = true;
        (*at)++;
    }
    size_t digits = 0;
    int64_t value = 0;
    while (*at < length && body[*at] >= '0' && body[*at] <= '9') {
        value = value * 10 + (body[*at] - '0');
        digits++;
        (*at)++;
    }
    if (!digits)
        return false;
    if (*at < length && body[*at] == ',')
        (*at)++;
    *out = negative ? -value : value;
    return true;
}

static void collect_material(const uint8_t *body, size_t length, void *ctx)
{
    material_ctx_t *m = ctx;
    if (m->failed)
        return;

    /* `name,roles,flags,contents,sources,uses`: the name is up to the comma. */
    size_t n = 0;
    while (n < length && body[n] != ',')
        n++;
    if (!n || n >= MATERIAL_NAME_BYTES)
        return;

    char name[MATERIAL_NAME_BYTES];
    memcpy(name, body, n);
    name[n] = '\0';

    /*
     * Contract 15: a material the target cannot resolve is not in the
     * allowlist. The compiler would only WARN about it, and a map textured
     * with something that does not exist compiles perfectly cleanly.
     */
    if (m->available) {
        bool resolves = false;
        for (uint32_t i = 0; i < m->num_available && !resolves; i++)
            resolves = m->available[i] && !strcmp(m->available[i], name);
        if (!resolves) {
            /* Once each: a texture both snapshots use is one texture the
               target is missing, not two. */
            for (uint32_t i = 0; i < m->mix->unavailable_materials; i++)
                if (!strcmp(m->mix->unavailable[i], name))
                    return;
            void *grown = realloc(m->mix->unavailable,
                                  (size_t)(m->mix->unavailable_materials + 1)
                                  * MATERIAL_NAME_BYTES);
            if (!grown) {
                m->failed = true;
                return;
            }
            m->mix->unavailable = grown;
            memcpy(m->mix->unavailable[m->mix->unavailable_materials++],
                   name, n + 1);
            return;
        }
    }

    /* What it was used AS. A row without them is not this format. */
    int64_t roles = 0, flags = 0, contents = 0, light_value = 0;
    int64_t sources = 0, uses = 0;
    size_t at = n + 1;
    if (!material_field(body, length, &at, &roles)
        || !material_field(body, length, &at, &flags)
        || !material_field(body, length, &at, &contents)
        || !material_field(body, length, &at, &light_value)
        || !material_field(body, length, &at, &sources)
        || !material_field(body, length, &at, &uses))
        return;

    /*
     * How much of the corpus wears this material, weighted by the selection it
     * came from. A material a snapshot recorded but never used still gets one,
     * so a legitimate allowlist entry is never unreachable.
     */
    const uint64_t draw = (uint64_t)(uses > 0 ? uses : 1) * m->weight;

    for (uint32_t i = 0; i < m->mix->num_materials; i++) {
        if (strcmp(m->mix->materials[i].name, name))
            continue;
        /* Already in the union. The allowlist stays exact; the sampling
           weight grows and the roles union - a texture used as a light in one
           map and as wall in another is both. */
        m->mix->materials[i].weight += draw;
        m->mix->materials[i].snapshots++;
        m->mix->materials[i].roles |= (uint32_t)roles;
        m->mix->materials[i].surface_flags |= (int32_t)flags;
        m->mix->materials[i].contents |= (int32_t)contents;
        /* The brightest, not the union: these are watts, not flags. */
        if ((int32_t)light_value > m->mix->materials[i].light_value)
            m->mix->materials[i].light_value = (int32_t)light_value;
        return;
    }

    void *grown = realloc(m->mix->materials,
                          (size_t)(m->mix->num_materials + 1) * sizeof(material_t));
    if (!grown) {
        m->failed = true;
        return;
    }
    m->mix->materials = grown;
    material_t *slot = &m->mix->materials[m->mix->num_materials++];
    memset(slot, 0, sizeof(*slot));
    memcpy(slot->name, name, n + 1);
    slot->weight = draw;
    slot->snapshots = 1;
    slot->roles = (uint32_t)roles;
    slot->surface_flags = (int32_t)flags;
    slot->light_value = (int32_t)light_value;
    slot->contents = (int32_t)contents;
}

/* --- sources -------------------------------------------------------------- */

typedef struct {
    mapgen_mix_t *mix;
    bool          failed;
} source_ctx_t;

static void collect_source(const uint8_t *body, size_t length, void *ctx)
{
    source_ctx_t *s = ctx;
    if (s->failed || length < 64)
        return;

    /* `sha256hex,provider,qpath,bytes,status` - only accepted sources teach
       anything, and only the hash identifies them. */
    const uint8_t *status = body + length;
    while (status > body && status[-1] != ',')
        status--;
    if ((size_t)(body + length - status) != 8 || memcmp(status, "accepted", 8))
        return;

    char hex[SOURCE_HEX_BYTES];
    memcpy(hex, body, 64);
    hex[64] = '\0';

    for (uint32_t i = 0; i < s->mix->num_sources; i++) {
        if (strcmp(s->mix->sources[i].hex, hex))
            continue;
        s->mix->sources[i].snapshots++;
        if (s->mix->sources[i].snapshots == 2)
            s->mix->shared_sources++;
        return;
    }

    void *grown = realloc(s->mix->sources,
                          (size_t)(s->mix->num_sources + 1) * sizeof(source_t));
    if (!grown) {
        s->failed = true;
        return;
    }
    s->mix->sources = grown;
    source_t *slot = &s->mix->sources[s->mix->num_sources++];
    memcpy(slot->hex, hex, SOURCE_HEX_BYTES);
    slot->snapshots = 1;
}

/* --- learned entity roles ------------------------------------------------- */

typedef struct {
    mapgen_mix_t *mix;
} role_ctx_t;

static void collect_role(const uint8_t *body, size_t length, void *ctx)
{
    role_ctx_t *c = ctx;

    /* `name,total` - the name is the role, and any total above zero means the
       selection has actually seen one. */
    size_t n = 0;
    while (n < length && body[n] != ',')
        n++;
    if (!n || n + 1 >= length)
        return;

    bool any = false;
    for (size_t i = n + 1; i < length; i++) {
        if (body[i] < '0' || body[i] > '9')
            return;
        if (body[i] != '0')
            any = true;
    }
    if (!any)
        return;

    char name[64];
    if (n >= sizeof(name))
        return;
    memcpy(name, body, n);
    name[n] = '\0';

    /* Matched back to the bit through the wiring layer's own table, so the
       two cannot drift apart. */
    for (uint32_t bit = 0; bit < 32; bit++) {
        const char *names[MAPGEN_WIRING_MAX_ROLE_NAMES];
        const uint32_t count = MapGenWiring_RoleNames(1u << bit, names,
                                                      MAPGEN_WIRING_MAX_ROLE_NAMES);
        if (count && !strcmp(names[0], name)) {
            c->mix->learned_roles |= 1u << bit;
            return;
        }
    }
}

/* --- learned statistics --------------------------------------------------- */

const char *MapGenMix_StatName(mapgen_mix_stat_t stat)
{
    switch (stat) {
    case MAPGEN_MIX_STAT_NODES:                    return "nodes";
    case MAPGEN_MIX_STAT_REGIONS:                  return "regions";
    case MAPGEN_MIX_STAT_LARGEST_REGION_PERMILLE:  return "largest_region_permille";
    case MAPGEN_MIX_STAT_HEIGHT_BANDS:             return "height_bands";
    case MAPGEN_MIX_STAT_VERTICAL_SPAN:            return "vertical_span";
    case MAPGEN_MIX_STAT_OPEN_PERMILLE:            return "open_permille";
    case MAPGEN_MIX_STAT_LIGHTS:                   return "lights";
    case MAPGEN_MIX_STAT_LIGHT_MEDIAN:             return "light_median";
    case MAPGEN_MIX_STAT_LIGHT_LOWER:              return "light_lower";
    case MAPGEN_MIX_STAT_LIGHT_UPPER:              return "light_upper";
    case MAPGEN_MIX_STAT_LIGHT_COLOUR_0:           return "light_colour_0";
    case MAPGEN_MIX_STAT_LIGHT_COLOUR_1:           return "light_colour_1";
    case MAPGEN_MIX_STAT_LIGHT_COLOUR_2:           return "light_colour_2";
    case MAPGEN_MIX_STAT_LIGHT_COLOUR_3:           return "light_colour_3";
    case MAPGEN_MIX_STAT_SKY_PERMILLE:             return "sky_permille";
    case MAPGEN_MIX_STAT_COUNT:                    break;
    }
    return "unknown";
}

typedef struct {
    mapgen_mix_t *mix;
    uint64_t      weight;
    bool          repeats;
    bool          failed;
} sample_ctx_t;

/*
 * Canonical sample order: by the map's hash, then by weight so that two
 * samples of one map under repeated influence still order the same way. The
 * samples arrive in whatever order the user selected the snapshots in, and
 * that order must leave no trace in the model.
 */
static int compare_samples(const void *a, const void *b)
{
    const sample_t *x = a, *y = b;
    const int by_hash = strcmp(x->hex, y->hex);
    if (by_hash)
        return by_hash;
    if (x->weight != y->weight)
        return x->weight < y->weight ? -1 : 1;
    return 0;
}

/* One `,`-separated integer field, or false when the row is malformed. */
static bool field_i64(const uint8_t *body, size_t length, size_t *at, int64_t *out)
{
    if (*at >= length)
        return false;
    bool negative = false;
    if (body[*at] == '-') {
        negative = true;
        (*at)++;
    }
    size_t digits = 0;
    int64_t value = 0;
    while (*at < length && body[*at] >= '0' && body[*at] <= '9') {
        value = value * 10 + (body[*at] - '0');
        digits++;
        (*at)++;
    }
    if (!digits)
        return false;
    if (*at < length && body[*at] == ',')
        (*at)++;
    *out = negative ? -value : value;
    return true;
}

/*
 * The architecture donors in one snapshot.
 *
 * A blueprint is a BLOCK of rows, not one row: the `b=` line names the donor
 * and the digest of what follows, and the volumes, portals and relations run
 * until the next `b=`. The text is kept verbatim - parsing it into volumes is
 * the architecture Module's business. The model's job is to say which donors
 * exist, how much weight each carries, and that the architecture attached to
 * one really is that donor's.
 *
 * Deduplicated by exact hash: one map that two selected snapshots both learned
 * from is ONE donor whose influence is the sum, never two that look alike.
 */
static void collect_donors(const mapgen_snapshot_t *snap, sample_ctx_t *c)
{
    size_t size = 0;
    const uint8_t *text = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_REGIONS, &size);
    if (!text || !c || !c->mix)
        return;

    for (size_t i = 0; i + 2 <= size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (text[i] != 'b' || text[i + 1] != '=')
            continue;

        const size_t head = i + 2;
        size_t line_end = head;
        while (line_end < size && text[line_end] != '\n')
            line_end++;
        if (line_end - head < SOURCE_HEX_BYTES - 1)
            continue;

        char hex[SOURCE_HEX_BYTES];
        memcpy(hex, text + head, SOURCE_HEX_BYTES - 1);
        hex[SOURCE_HEX_BYTES - 1] = '\0';
        bool valid = true;
        for (size_t k = 0; k < SOURCE_HEX_BYTES - 1; k++) {
            const char ch = hex[k];
            if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')))
                valid = false;
        }
        if (!valid)
            continue;

        /* The blueprint runs to the next `b=` or to the end of the chunk. */
        size_t body = line_end + 1;
        size_t body_end = body;
        while (body_end < size) {
            if (body_end + 2 <= size && text[body_end - 1] == '\n'
                && text[body_end] == 'b' && text[body_end + 1] == '=')
                break;
            body_end++;
        }

        /* Already known: sum the influence and keep the first blueprint. */
        bool known = false;
        for (uint32_t d = 0; d < c->mix->num_donors; d++) {
            if (strcmp(c->mix->donors[d].hex, hex))
                continue;
            c->mix->donors[d].weight += c->weight;
            c->mix->donors[d].snapshots++;
            known = true;
            break;
        }
        if (known)
            continue;

        void *grown = realloc(c->mix->donors,
                              (size_t)(c->mix->num_donors + 1) * sizeof(donor_t));
        if (!grown) {
            c->failed = true;
            return;
        }
        c->mix->donors = grown;
        donor_t *slot = &c->mix->donors[c->mix->num_donors++];
        memset(slot, 0, sizeof(*slot));
        memcpy(slot->hex, hex, sizeof(slot->hex));
        slot->weight = c->weight;
        slot->snapshots = 1;
        slot->blueprint = malloc(body_end - body + 1);
        if (!slot->blueprint) {
            c->failed = true;
            return;
        }
        memcpy(slot->blueprint, text + body, body_end - body);
        slot->blueprint[body_end - body] = '\0';
    }
}

static void collect_sample(const uint8_t *body, size_t length, void *ctx)
{
    sample_ctx_t *c = ctx;
    if (c->failed || length < SOURCE_HEX_BYTES)
        return;

    /* `sha256hex,nodes,regions,largest,bands,span,open` - the hash first, so
       the statistic and the map it came from travel together. */
    char hex[SOURCE_HEX_BYTES];
    memcpy(hex, body, 64);
    hex[64] = '\0';
    for (size_t i = 0; i < 64; i++) {
        const char ch = hex[i];
        const bool ok = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
        if (!ok)
            return;
    }
    if (body[64] != ',')
        return;

    int64_t values[MAPGEN_MIX_STAT_COUNT];
    size_t at = 65;
    for (uint32_t i = 0; i < MAPGEN_MIX_STAT_COUNT; i++)
        if (!field_i64(body, length, &at, &values[i]))
            return;

    for (uint32_t i = 0; i < c->mix->num_samples; i++) {
        if (strcmp(c->mix->samples[i].hex, hex))
            continue;
        /*
         * The same map, learned by another selected snapshot. By default it
         * stays ONE sample and only its weight grows, which is the same rule
         * the material table follows; with repeated influence it becomes a
         * second sample, so the setting reaches the numbers the generator
         * samples and not just the source list.
         */
        if (!c->repeats) {
            c->mix->samples[i].snapshots++;
            c->mix->samples[i].weight += c->weight;
            return;
        }
        break;                              /* a second sample, added below */
    }

    void *grown = realloc(c->mix->samples,
                          (size_t)(c->mix->num_samples + 1) * sizeof(sample_t));
    if (!grown) {
        c->failed = true;
        return;
    }
    c->mix->samples = grown;
    sample_t *slot = &c->mix->samples[c->mix->num_samples++];
    memset(slot, 0, sizeof(*slot));
    memcpy(slot->hex, hex, SOURCE_HEX_BYTES);
    memcpy(slot->values, values, sizeof(values));
    slot->weight = c->weight;
    slot->snapshots = 1;
}

/* ------------------------------------------------------------------------ */

mapgen_mix_result_t MapGenMix_Build(const mapgen_mix_input_t *inputs,
                                    uint32_t count,
                                    const mapgen_mix_options_t *options,
                                    mapgen_mix_t **out)
{
    if (!inputs || !out)
        return MAPGEN_MIX_ERR_ARGS;
    *out = NULL;
    if (!count)
        return MAPGEN_MIX_ERR_NO_INPUTS;
    if (count > MAPGEN_MIX_MAX_INPUTS)
        return MAPGEN_MIX_ERR_TOO_MANY_INPUTS;

    const mapgen_mix_options_t defaults = { false, NULL, 0 };
    const mapgen_mix_options_t *opts = options ? options : &defaults;

    /*
     * Everything is validated before anything is combined. A half-built model
     * from a selection that turns out to be incompatible is worse than none.
     */
    uint64_t weight_total = 0;
    for (uint32_t i = 0; i < count; i++) {
        if (!inputs[i].snapshot)
            return MAPGEN_MIX_ERR_ARGS;
        if (inputs[i].weight < MAPGEN_MIX_MIN_WEIGHT ||
            inputs[i].weight > MAPGEN_MIX_MAX_WEIGHT)
            return MAPGEN_MIX_ERR_BAD_WEIGHT;

        const mapgen_snapshot_header_t *h = MapGenSnapshot_Header(inputs[i].snapshot);
        if (!h)
            return MAPGEN_MIX_ERR_ARGS;

        /* The pin is what the caller meant to select; the header is what was
           actually opened. A mismatch is refused, never substituted. */
        if (memcmp(h->revision_uuid, inputs[i].revision_uuid,
                   MAPGEN_SNAPSHOT_UUID_BYTES) ||
            memcmp(h->payload_sha256, inputs[i].payload_sha256, MAPGEN_SHA256_BYTES))
            return MAPGEN_MIX_ERR_PIN_MISMATCH;

        for (uint32_t j = 0; j < i; j++) {
            const mapgen_snapshot_header_t *other =
                MapGenSnapshot_Header(inputs[j].snapshot);
            if (!memcmp(other->revision_uuid, h->revision_uuid,
                        MAPGEN_SNAPSHOT_UUID_BYTES))
                return MAPGEN_MIX_ERR_DUPLICATE_REVISION;
            /* Contract 9: incompatible physics or schema cannot run. Mixing
               across them would produce a model of no particular game. */
            if (memcmp(other->physics_schema_hash, h->physics_schema_hash,
                       MAPGEN_SHA256_BYTES) ||
                other->schema_major != h->schema_major)
                return MAPGEN_MIX_ERR_NEEDS_REBUILD;
        }
        weight_total += inputs[i].weight;
    }

    mapgen_mix_t *mix = calloc(1, sizeof(*mix));
    if (!mix)
        return MAPGEN_MIX_ERR_MEMORY;
    mix->num_inputs = count;
    mix->weight_ppm = calloc(count, sizeof(uint32_t));
    if (!mix->weight_ppm) {
        MapGenMix_Free(mix);
        return MAPGEN_MIX_ERR_MEMORY;
    }

    for (uint32_t i = 0; i < count; i++)
        mix->weight_ppm[i] = (uint32_t)(((uint64_t)inputs[i].weight * 1000000u)
                                        / weight_total);

    for (uint32_t i = 0; i < count; i++) {
        material_ctx_t mctx = { mix, mix->weight_ppm[i], false,
                                opts->available, opts->num_available };
        for_each_row(inputs[i].snapshot, MAPGEN_CHUNK_MATERIALS, "m=",
                     collect_material, &mctx);
        if (mctx.failed) {
            MapGenMix_Free(mix);
            return MAPGEN_MIX_ERR_MEMORY;
        }

        source_ctx_t sctx = { mix, false };
        for_each_row(inputs[i].snapshot, MAPGEN_CHUNK_SOURCES, "s=",
                     collect_source, &sctx);
        if (sctx.failed) {
            MapGenMix_Free(mix);
            return MAPGEN_MIX_ERR_MEMORY;
        }

        role_ctx_t rctx = { mix };
        for_each_row(inputs[i].snapshot, MAPGEN_CHUNK_ENTITIES, "e=",
                     collect_role, &rctx);

        sample_ctx_t pctx = { mix, mix->weight_ppm[i],
                              opts->allow_repeated_influence, false };
        /*
         * The aggregate samples live in STATS from schema 2 onward; REGIONS
         * carries the architecture instead.
         */
        for_each_row(inputs[i].snapshot, MAPGEN_CHUNK_STATS, "r=",
                     collect_sample, &pctx);
        collect_donors(inputs[i].snapshot, &pctx);
        if (pctx.failed) {
            MapGenMix_Free(mix);
            return MAPGEN_MIX_ERR_MEMORY;
        }
    }

    /*
     * The per-source appearance counts are kept as measured, whatever the
     * setting: how many snapshots carry a source is a fact about the
     * selection, and a caller may want to see it. The SETTING decides how many
     * contributions the model is built on, which is what
     * MapGenMix_EffectiveSourceCount reports.
     */
    mix->repeated_influence = opts->allow_repeated_influence;
    mix->has_manifest = opts->available != NULL;

    for (uint32_t i = 0; i < mix->num_materials; i++)
        mix->material_weight_total += mix->materials[i].weight;
    if (mix->num_samples)
        qsort(mix->samples, mix->num_samples, sizeof(sample_t), compare_samples);
    for (uint32_t i = 0; i < mix->num_samples; i++)
        mix->sample_weight_total += mix->samples[i].weight;

    *out = mix;
    return MAPGEN_MIX_OK;
}

uint32_t MapGenMix_NumDonors(const mapgen_mix_t *m)
{
    return m ? m->num_donors : 0;
}

const char *MapGenMix_DonorHex(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->num_donors) ? m->donors[index].hex : NULL;
}

const char *MapGenMix_DonorBlueprint(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->num_donors) ? m->donors[index].blueprint : NULL;
}

uint32_t MapGenMix_DonorWeightPpm(const mapgen_mix_t *m, uint32_t index)
{
    if (!m || index >= m->num_donors)
        return 0;
    uint64_t total = 0;
    for (uint32_t i = 0; i < m->num_donors; i++)
        total += m->donors[i].weight;
    return total ? (uint32_t)(m->donors[index].weight * 1000000u / total) : 0;
}

void MapGenMix_Free(mapgen_mix_t *mix)
{
    if (!mix)
        return;
    free(mix->weight_ppm);
    free(mix->materials);
    free(mix->sources);
    for (uint32_t i = 0; i < mix->num_donors; i++)
        free(mix->donors[i].blueprint);
    free(mix->donors);
    free(mix->samples);
    free(mix->unavailable);
    free(mix);
}

/* ------------------------------------------------------------------------ */

uint32_t MapGenMix_NumInputs(const mapgen_mix_t *m)    { return m ? m->num_inputs : 0; }
uint32_t MapGenMix_NumMaterials(const mapgen_mix_t *m) { return m ? m->num_materials : 0; }
uint32_t MapGenMix_NumSources(const mapgen_mix_t *m)   { return m ? m->num_sources : 0; }

uint32_t MapGenMix_NumSharedSources(const mapgen_mix_t *m)
{
    return m ? m->shared_sources : 0;
}

bool MapGenMix_RepeatedInfluence(const mapgen_mix_t *m)
{
    return m && m->repeated_influence;
}

bool MapGenMix_HasTargetManifest(const mapgen_mix_t *m)
{
    return m && m->has_manifest;
}

uint32_t MapGenMix_NumUnavailableMaterials(const mapgen_mix_t *m)
{
    return m ? m->unavailable_materials : 0;
}

const char *MapGenMix_UnavailableMaterial(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->unavailable_materials) ? m->unavailable[index] : NULL;
}

uint32_t MapGenMix_EffectiveSourceCount(const mapgen_mix_t *m)
{
    if (!m)
        return 0;
    if (!m->repeated_influence)
        return m->num_sources;          /* each distinct source teaches once */

    uint32_t total = 0;
    for (uint32_t i = 0; i < m->num_sources; i++)
        total += m->sources[i].snapshots;
    return total;
}

bool MapGenMix_RoleIsLearned(const mapgen_mix_t *m, uint32_t role_bit)
{
    return m && role_bit && (m->learned_roles & role_bit) == role_bit;
}

bool MapGenMix_MaterialRoleIsLearned(const mapgen_mix_t *m, uint32_t role_bit)
{
    if (!m || !role_bit)
        return false;
    for (uint32_t i = 0; i < m->num_materials; i++)
        if ((m->materials[i].roles & role_bit) == role_bit)
            return true;
    return false;
}

uint32_t MapGenMix_NumSamples(const mapgen_mix_t *m)
{
    return m ? m->num_samples : 0;
}

int64_t MapGenMix_SampleValue(const mapgen_mix_t *m, uint32_t index,
                              mapgen_mix_stat_t stat)
{
    if (!m || index >= m->num_samples || stat >= MAPGEN_MIX_STAT_COUNT)
        return 0;
    return m->samples[index].values[stat];
}

uint32_t MapGenMix_SampleWeightPpm(const mapgen_mix_t *m, uint32_t index)
{
    if (!m || index >= m->num_samples || !m->sample_weight_total)
        return 0;
    return (uint32_t)((m->samples[index].weight * 1000000u)
                      / m->sample_weight_total);
}

const char *MapGenMix_SampleSource(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->num_samples) ? m->samples[index].hex : NULL;
}

uint32_t MapGenMix_DrawSample(const mapgen_mix_t *m, mapgen_random_t *r)
{
    if (!m || !r || !m->num_samples)
        return m ? m->num_samples : 0;

    /* The draw walks the weights rather than picking an index and correcting
       it, so a heavier snapshot's maps really do come up more often instead of
       merely being recorded with a bigger number. */
    uint64_t total = 0;
    for (uint32_t i = 0; i < m->num_samples; i++)
        total += m->samples[i].weight;
    if (!total)
        return MapGenRandom_Below(r, m->num_samples);

    uint64_t pick;
    if (total <= 0xFFFFFFFFull) {
        pick = MapGenRandom_Below(r, (uint32_t)total);
    } else {
        const uint64_t limit = 0xFFFFFFFFFFFFFFFFull
                             - (0xFFFFFFFFFFFFFFFFull % total);
        do {
            pick = MapGenRandom_Next(r);
        } while (pick >= limit);
        pick %= total;
    }

    uint64_t seen = 0;
    for (uint32_t i = 0; i < m->num_samples; i++) {
        seen += m->samples[i].weight;
        if (pick < seen)
            return i;
    }
    return m->num_samples - 1;
}

uint32_t MapGenMix_WeightPpm(const mapgen_mix_t *m, uint32_t input)
{
    return (m && m->weight_ppm && input < m->num_inputs) ? m->weight_ppm[input] : 0;
}

const char *MapGenMix_MaterialName(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->num_materials) ? m->materials[index].name : NULL;
}

uint32_t MapGenMix_MaterialRoles(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->num_materials) ? m->materials[index].roles : 0;
}

int32_t MapGenMix_MaterialContents(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->num_materials) ? m->materials[index].contents : 0;
}

int32_t MapGenMix_MaterialSurfaceFlags(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->num_materials) ? m->materials[index].surface_flags : 0;
}

int32_t MapGenMix_MaterialLightValue(const mapgen_mix_t *m, uint32_t index)
{
    return (m && index < m->num_materials) ? m->materials[index].light_value : 0;
}

uint32_t MapGenMix_MaterialProbabilityPpm(const mapgen_mix_t *m, uint32_t index)
{
    if (!m || index >= m->num_materials || !m->material_weight_total)
        return 0;
    return (uint32_t)((m->materials[index].weight * 1000000u)
                      / m->material_weight_total);
}

/* ------------------------------------------------------------------------ */

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

static int compare_materials(const void *a, const void *b)
{
    return strcmp(((const material_t *)a)->name, ((const material_t *)b)->name);
}

size_t MapGenMix_CanonicalText(const mapgen_mix_t *mix, char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!mix) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    put(&s, "inputs=");
    put_u64(&s, mix->num_inputs);
    put(&s, "\n");
    for (uint32_t i = 0; i < mix->num_inputs; i++) {
        put(&s, "w=");
        put_u64(&s, mix->weight_ppm[i]);
        put(&s, "\n");
    }

    /* Sorted, so the model does not depend on the order the user happened to
       select the snapshots in. */
    material_t *sorted = mix->num_materials
                       ? malloc((size_t)mix->num_materials * sizeof(material_t))
                       : NULL;
    if (sorted) {
        memcpy(sorted, mix->materials, (size_t)mix->num_materials * sizeof(material_t));
        qsort(sorted, mix->num_materials, sizeof(material_t), compare_materials);
    }
    put(&s, "materials=");
    put_u64(&s, mix->num_materials);
    put(&s, "\n");
    for (uint32_t i = 0; i < mix->num_materials && sorted; i++) {
        put(&s, "m=");
        put(&s, sorted[i].name);
        put(&s, ",");
        put_u64(&s, mix->material_weight_total
                ? (sorted[i].weight * 1000000u) / mix->material_weight_total : 0);
        put(&s, ",");
        put_u64(&s, sorted[i].snapshots);
        put(&s, ",");
        put_u64(&s, sorted[i].roles);
        put(&s, "\n");
    }
    free(sorted);

    put(&s, "sources=");
    put_u64(&s, mix->num_sources);
    put(&s, "\n");
    put(&s, "shared_sources=");
    put_u64(&s, mix->shared_sources);
    put(&s, "\n");
    put(&s, "effective_sources=");
    put_u64(&s, MapGenMix_EffectiveSourceCount(mix));
    put(&s, "\n");
    put(&s, "repeated_influence=");
    put_u64(&s, mix->repeated_influence ? 1u : 0u);
    put(&s, "\n");

    /* The learned maps, in canonical order - sorted when the model was built,
       so nothing here depends on the order the user selected in. */
    put(&s, "target_manifest=");
    put_u64(&s, mix->has_manifest ? 1u : 0u);
    put(&s, "\nunavailable_materials=");
    put_u64(&s, mix->unavailable_materials);
    put(&s, "\n");

    put(&s, "learned_roles=");
    put_u64(&s, mix->learned_roles);
    put(&s, "\n");

    put(&s, "samples=");
    put_u64(&s, mix->num_samples);
    put(&s, "\n");
    for (uint32_t i = 0; i < mix->num_samples; i++) {
        put(&s, "p=");
        put(&s, mix->samples[i].hex);
        for (uint32_t k = 0; k < MAPGEN_MIX_STAT_COUNT; k++) {
            put(&s, ",");
            const int64_t v = mix->samples[i].values[k];
            if (v < 0) {
                put(&s, "-");
                put_u64(&s, (uint64_t)(-v));
            } else {
                put_u64(&s, (uint64_t)v);
            }
        }
        put(&s, ",");
        put_u64(&s, MapGenMix_SampleWeightPpm(mix, i));
        put(&s, "\n");
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenMix_CanonicalDigest(const mapgen_mix_t *mix)
{
    const size_t needed = MapGenMix_CanonicalText(mix, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenMix_CanonicalText(mix, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
