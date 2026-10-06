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
 * MAPGEN-1 - MapGenome, layer 1.
 *
 * Pure: no OS, no engine, no globals. Contract sections 7 and 15.
 */

#include "common/mapgen_genome.h"

#include <stdlib.h>
#include <string.h>

struct mapgen_genome_s {
    uint32_t           num_materials;
    mapgen_material_t *materials;

    uint32_t           num_entities;
    mapgen_entity_t   *entities;

    float              world_mins[3];
    float              world_maxs[3];
};

/* ------------------------------------------------------------------------ */

static uint32_t roles_from(int32_t surface_flags, int32_t contents, bool animated)
{
    /*
     * Everything below reads FLAGS. Not one branch looks at the name.
     *
     * Contract section 7.7 is explicit about this, and the reason is concrete:
     * a texture called `water4` can be a dry wall and a texture called
     * `floor3_3` can be the top of a lava pit. The compiled flags are what the
     * engine itself acts on, so they are the only honest source.
     */
    uint32_t roles = 0;

    if (surface_flags & MAPGEN_SURF_SKY)      roles |= MAPGEN_ROLE_SKY;
    if (surface_flags & MAPGEN_SURF_LIGHT)    roles |= MAPGEN_ROLE_LIGHT;
    if (surface_flags & MAPGEN_SURF_FLOWING)  roles |= MAPGEN_ROLE_FLOWING;
    if (surface_flags & (MAPGEN_SURF_TRANS33 | MAPGEN_SURF_TRANS66))
        roles |= MAPGEN_ROLE_TRANSLUCENT;
    if (surface_flags & (MAPGEN_SURF_NODRAW | MAPGEN_SURF_HINT | MAPGEN_SURF_SKIP))
        roles |= MAPGEN_ROLE_NODRAW;

    if (contents & MAPGEN_CONTENTS_WATER)  roles |= MAPGEN_ROLE_WATER;
    if (contents & MAPGEN_CONTENTS_LAVA)   roles |= MAPGEN_ROLE_LAVA;
    if (contents & MAPGEN_CONTENTS_SLIME)  roles |= MAPGEN_ROLE_SLIME;
    if (contents & MAPGEN_CONTENTS_MIST)   roles |= MAPGEN_ROLE_MIST;
    if (contents & MAPGEN_CONTENTS_LADDER) roles |= MAPGEN_ROLE_LADDER;
    if (contents & (MAPGEN_CONTENTS_PLAYERCLIP | MAPGEN_CONTENTS_MONSTERCLIP))
        roles |= MAPGEN_ROLE_CLIP;
    if (contents & MAPGEN_CONTENTS_TRANSLUCENT)
        roles |= MAPGEN_ROLE_TRANSLUCENT;
    if (contents & MAPGEN_CONTENTS_SOLID)  roles |= MAPGEN_ROLE_SOLID;

    if (animated)
        roles |= MAPGEN_ROLE_ANIMATED;

    return roles;
}

static int material_find(const mapgen_genome_t *g, const char *name)
{
    for (uint32_t i = 0; i < g->num_materials; i++) {
        if (!strcmp(g->materials[i].name, name))
            return (int)i;
    }
    return -1;
}

/* ------------------------------------------------------------------------ */
/* Entity string parsing - strict, bounded, and unforgiving on purpose.      */
/* ------------------------------------------------------------------------ */

typedef struct {
    const char *text;
    size_t      length;
    size_t      pos;
} ent_parser_t;

static void ent_skip_space(ent_parser_t *p)
{
    while (p->pos < p->length) {
        char c = p->text[p->pos];
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n')
            p->pos++;
        else
            break;
    }
}

/* Read a quoted token into `out`. An overlong token is an ERROR rather than a
   silent truncation: a truncated targetname would silently rewire a map. */
static bool ent_quoted(ent_parser_t *p, char *out, size_t capacity, bool *too_long)
{
    *too_long = false;
    if (p->pos >= p->length || p->text[p->pos] != '"')
        return false;
    p->pos++;

    size_t n = 0;
    while (p->pos < p->length && p->text[p->pos] != '"') {
        char c = p->text[p->pos++];
        if (n + 1 >= capacity) {
            *too_long = true;
            return false;
        }
        /* Control bytes never belong in an entity value and would reach a log
           and a UI. */
        out[n++] = ((unsigned char)c < 0x20) ? '?' : c;
    }
    if (p->pos >= p->length)
        return false;                 /* unterminated quote */
    p->pos++;
    out[n] = '\0';
    return true;
}

static bool parse_origin(const char *value, float out[3])
{
    int found = 0;
    const char *s = value;
    while (*s && found < 3) {
        while (*s == ' ' || *s == '\t')
            s++;
        if (!*s)
            break;
        char *end = NULL;
        double v = strtod(s, &end);
        if (end == s)
            return false;
        out[found++] = (float)v;
        s = end;
    }
    return found == 3;
}

/* ------------------------------------------------------------------------ */

mapgen_genome_result_t MapGenGenome_Extract(const mapgen_bsp_t *bsp, mapgen_genome_t **out)
{
    if (!bsp || !out)
        return MAPGEN_GENOME_ERR_ARGUMENT;
    *out = NULL;

    mapgen_genome_t *g = calloc(1, sizeof(*g));
    if (!g)
        return MAPGEN_GENOME_ERR_OUT_OF_MEMORY;

    uint32_t tex_count = MapGenBsp_NumTexInfo(bsp);
    uint32_t cap_materials = tex_count < MAPGEN_GENOME_MAX_MATERIALS
        ? tex_count : MAPGEN_GENOME_MAX_MATERIALS;
    if (cap_materials) {
        g->materials = calloc(cap_materials, sizeof(*g->materials));
        if (!g->materials) {
            MapGenGenome_Free(g);
            return MAPGEN_GENOME_ERR_OUT_OF_MEMORY;
        }
    }

    /* Pass 1: one material per distinct texture name, with the union of every
       surface flag any texinfo gave it. */
    for (uint32_t i = 0; i < tex_count; i++) {
        const mapgen_bsp_texinfo_t *ti = MapGenBsp_TexInfo(bsp, i);
        if (!ti)
            continue;
        int index = material_find(g, ti->texture);
        if (index < 0) {
            if (g->num_materials == cap_materials) {
                MapGenGenome_Free(g);
                return MAPGEN_GENOME_ERR_TOO_MANY_MATERIALS;
            }
            index = (int)g->num_materials++;
            mapgen_material_t *m = &g->materials[index];
            memcpy(m->name, ti->texture, sizeof(m->name) - 1);
            m->name[sizeof(m->name) - 1] = '\0';
        }
        mapgen_material_t *m = &g->materials[index];
        m->surface_flags |= ti->flags;
        if ((ti->flags & MAPGEN_SURF_LIGHT) && ti->value > m->light_value)
            m->light_value = ti->value;
        m->texinfo_refs++;
        /* A texinfo in an animation chain marks its material animated. */
        if (ti->nexttexinfo >= 0)
            m->roles |= MAPGEN_ROLE_ANIMATED;
    }

    /* Pass 2: contents come from the BRUSHES, because a texture is only water
       when a water brush uses it. */
    uint32_t brush_count = MapGenBsp_NumBrushes(bsp);
    for (uint32_t b = 0; b < brush_count; b++) {
        const mapgen_bsp_brush_t *brush = MapGenBsp_Brush(bsp, b);
        if (!brush)
            continue;
        for (int32_t s = 0; s < brush->numsides; s++) {
            const mapgen_bsp_brushside_t *side =
                MapGenBsp_BrushSide(bsp, (uint32_t)(brush->firstside + s));
            if (!side || side->texinfo < 0)
                continue;
            const mapgen_bsp_texinfo_t *ti = MapGenBsp_TexInfo(bsp, (uint32_t)side->texinfo);
            if (!ti)
                continue;
            int index = material_find(g, ti->texture);
            if (index < 0)
                continue;
            g->materials[index].contents |= brush->contents;
            g->materials[index].brushside_refs++;
        }
    }

    /* Pass 3: how often each material is actually drawn. */
    uint32_t face_count = MapGenBsp_NumFaces(bsp);
    for (uint32_t f = 0; f < face_count; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        if (!face || face->texinfo < 0)
            continue;
        const mapgen_bsp_texinfo_t *ti = MapGenBsp_TexInfo(bsp, (uint32_t)face->texinfo);
        if (!ti)
            continue;
        int index = material_find(g, ti->texture);
        if (index >= 0)
            g->materials[index].face_refs++;
    }

    for (uint32_t i = 0; i < g->num_materials; i++) {
        mapgen_material_t *m = &g->materials[i];
        bool animated = (m->roles & MAPGEN_ROLE_ANIMATED) != 0;
        m->roles = roles_from(m->surface_flags, m->contents, animated);
    }

    /* Entities. */
    uint32_t ent_len = 0;
    const char *ent_text = MapGenBsp_Entities(bsp, &ent_len);
    if (ent_text) {
        ent_parser_t p = { ent_text, ent_len, 0 };

        g->entities = calloc(MAPGEN_GENOME_MAX_ENTITIES, sizeof(*g->entities));
        if (!g->entities) {
            MapGenGenome_Free(g);
            return MAPGEN_GENOME_ERR_OUT_OF_MEMORY;
        }

        for (;;) {
            ent_skip_space(&p);
            if (p.pos >= p.length)
                break;
            if (p.text[p.pos] != '{') {
                MapGenGenome_Free(g);
                return MAPGEN_GENOME_ERR_ENTITY_SYNTAX;
            }
            p.pos++;

            if (g->num_entities == MAPGEN_GENOME_MAX_ENTITIES) {
                MapGenGenome_Free(g);
                return MAPGEN_GENOME_ERR_TOO_MANY_ENTITIES;
            }
            mapgen_entity_t *ent = &g->entities[g->num_entities];
            memset(ent, 0, sizeof(*ent));

            bool closed = false;
            for (;;) {
                ent_skip_space(&p);
                if (p.pos >= p.length)
                    break;
                if (p.text[p.pos] == '}') {
                    p.pos++;
                    closed = true;
                    break;
                }
                char key[MAPGEN_GENOME_KEY_BYTES];
                char value[MAPGEN_GENOME_VALUE_BYTES];
                bool too_long = false;
                if (!ent_quoted(&p, key, sizeof(key), &too_long)) {
                    MapGenGenome_Free(g);
                    return too_long ? MAPGEN_GENOME_ERR_ENTITY_TOO_LONG
                                    : MAPGEN_GENOME_ERR_ENTITY_SYNTAX;
                }
                ent_skip_space(&p);
                if (!ent_quoted(&p, value, sizeof(value), &too_long)) {
                    MapGenGenome_Free(g);
                    return too_long ? MAPGEN_GENOME_ERR_ENTITY_TOO_LONG
                                    : MAPGEN_GENOME_ERR_ENTITY_SYNTAX;
                }

                if (!strcmp(key, "classname")) {
                    memcpy(ent->classname, value, sizeof(ent->classname) - 1);
                    ent->classname[sizeof(ent->classname) - 1] = '\0';
                } else if (!strcmp(key, "origin")) {
                    ent->has_origin = parse_origin(value, ent->origin);
                }

                if (ent->num_keys < MAPGEN_GENOME_MAX_KEYS) {
                    mapgen_kv_t *kv = &ent->keys[ent->num_keys++];
                    memcpy(kv->key, key, sizeof(kv->key) - 1);
                    kv->key[sizeof(kv->key) - 1] = '\0';
                    memcpy(kv->value, value, sizeof(kv->value) - 1);
                    kv->value[sizeof(kv->value) - 1] = '\0';
                }
            }
            if (!closed) {
                MapGenGenome_Free(g);
                return MAPGEN_GENOME_ERR_ENTITY_SYNTAX;
            }
            g->num_entities++;
        }
    }

    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    if (world) {
        for (int k = 0; k < 3; k++) {
            g->world_mins[k] = world->mins[k];
            g->world_maxs[k] = world->maxs[k];
        }
    }

    *out = g;
    return MAPGEN_GENOME_OK;
}

void MapGenGenome_Free(mapgen_genome_t *g)
{
    if (!g)
        return;
    free(g->materials);
    free(g->entities);
    free(g);
}

/* ------------------------------------------------------------------------ */

uint32_t MapGenGenome_NumMaterials(const mapgen_genome_t *g) { return g ? g->num_materials : 0; }
uint32_t MapGenGenome_NumEntities(const mapgen_genome_t *g) { return g ? g->num_entities : 0; }

const mapgen_material_t *MapGenGenome_Material(const mapgen_genome_t *g, uint32_t i)
{
    return (g && i < g->num_materials) ? &g->materials[i] : NULL;
}

const mapgen_entity_t *MapGenGenome_Entity(const mapgen_genome_t *g, uint32_t i)
{
    return (g && i < g->num_entities) ? &g->entities[i] : NULL;
}

const mapgen_material_t *MapGenGenome_FindMaterial(const mapgen_genome_t *g, const char *name)
{
    if (!g || !name)
        return NULL;
    int index = material_find(g, name);
    return index < 0 ? NULL : &g->materials[index];
}

uint32_t MapGenGenome_CountClassname(const mapgen_genome_t *g, const char *classname)
{
    if (!g || !classname)
        return 0;
    uint32_t n = 0;
    for (uint32_t i = 0; i < g->num_entities; i++) {
        if (!strcmp(g->entities[i].classname, classname))
            n++;
    }
    return n;
}

const char *MapGenGenome_EntityValue(const mapgen_entity_t *ent, const char *key)
{
    if (!ent || !key)
        return NULL;
    for (uint32_t i = 0; i < ent->num_keys; i++) {
        if (!strcmp(ent->keys[i].key, key))
            return ent->keys[i].value;
    }
    return NULL;
}

void MapGenGenome_WorldBounds(const mapgen_genome_t *g, float mins[3], float maxs[3])
{
    for (int k = 0; k < 3; k++) {
        if (mins)
            mins[k] = g ? g->world_mins[k] : 0.0f;
        if (maxs)
            maxs[k] = g ? g->world_maxs[k] : 0.0f;
    }
}

/* ------------------------------------------------------------------------ */

static const char *ROLE_NAMES[] = {
    "SOLID", "SKY", "WATER", "LAVA", "SLIME", "MIST", "CLIP",
    "TRANSLUCENT", "NODRAW", "LIGHT", "FLOWING", "ANIMATED", "LADDER"
};

uint32_t MapGenGenome_RoleNames(uint32_t roles, const char **out, uint32_t capacity)
{
    uint32_t n = 0;
    for (uint32_t bit = 0; bit < sizeof(ROLE_NAMES) / sizeof(ROLE_NAMES[0]); bit++) {
        if ((roles & (1u << bit)) && out && n < capacity)
            out[n++] = ROLE_NAMES[bit];
        else if (roles & (1u << bit))
            n++;
    }
    return n;
}

/* ------------------------------------------------------------------------ */

typedef struct {
    char  *out;
    size_t capacity;
    size_t needed;
} sink_t;

static void put(sink_t *s, const char *text)
{
    size_t n = strlen(text);
    if (s->out && s->needed < s->capacity) {
        size_t room = s->capacity - 1 - s->needed;
        size_t copy = n < room ? n : room;
        memcpy(s->out + s->needed, text, copy);
    }
    s->needed += n;
}

static void put_i(sink_t *s, int64_t v)
{
    char buf[24];
    size_t n = 0;
    bool neg = v < 0;
    uint64_t u = neg ? (uint64_t)(-(v + 1)) + 1u : (uint64_t)v;
    char tmp[24];
    size_t t = 0;
    if (!u)
        tmp[t++] = '0';
    while (u) {
        tmp[t++] = (char)('0' + (u % 10u));
        u /= 10u;
    }
    if (neg)
        buf[n++] = '-';
    while (t)
        buf[n++] = tmp[--t];
    buf[n] = '\0';
    put(s, buf);
}

/* Same locale-free rendering as the document's, for the same reason. */
static void put_f(sink_t *s, float value)
{
    double v = (double)value;
    bool negative = v < 0.0;
    if (negative)
        v = -v;
    double scaled = v * 1000000.0 + 0.5;
    if (!(scaled < 9.0e18))
        scaled = 0.0;
    uint64_t units = (uint64_t)scaled;
    uint64_t whole = units / 1000000u;
    uint64_t frac = units % 1000000u;
    if (whole == 0 && frac == 0)
        negative = false;
    if (negative)
        put(s, "-");
    put_i(s, (int64_t)whole);
    put(s, ".");
    char digits[7];
    for (int i = 5; i >= 0; i--) {
        digits[i] = (char)('0' + (frac % 10u));
        frac /= 10u;
    }
    digits[6] = '\0';
    put(s, digits);
}

size_t MapGenGenome_CanonicalText(const mapgen_genome_t *g, char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!g) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    /*
     * Materials are emitted in sorted NAME order, not in the order the texinfo
     * lump happened to mention them. Contract section 10 requires the digest to
     * be independent of thread completion and iteration order, and a lump's
     * order is exactly the kind of incidental sequence that would leak in.
     */
    uint32_t *order = malloc(g->num_materials ? g->num_materials * sizeof(uint32_t) : 1);
    if (!order)
        return 0;
    for (uint32_t i = 0; i < g->num_materials; i++)
        order[i] = i;
    for (uint32_t i = 1; i < g->num_materials; i++) {
        uint32_t key = order[i];
        uint32_t j = i;
        while (j > 0 && strcmp(g->materials[order[j - 1]].name, g->materials[key].name) > 0) {
            order[j] = order[j - 1];
            j--;
        }
        order[j] = key;
    }

    put(&s, "materials="); put_i(&s, g->num_materials); put(&s, "\n");
    for (uint32_t i = 0; i < g->num_materials; i++) {
        const mapgen_material_t *m = &g->materials[order[i]];
        put(&s, "mat=");
        put(&s, m->name); put(&s, ",");
        put_i(&s, m->surface_flags); put(&s, ",");
        put_i(&s, m->contents); put(&s, ",");
        put_i(&s, m->roles); put(&s, ",");
        put_i(&s, m->texinfo_refs); put(&s, ",");
        put_i(&s, m->brushside_refs); put(&s, ",");
        put_i(&s, m->face_refs); put(&s, "\n");
    }
    free(order);

    put(&s, "entities="); put_i(&s, g->num_entities); put(&s, "\n");
    for (uint32_t i = 0; i < g->num_entities; i++) {
        const mapgen_entity_t *e = &g->entities[i];
        put(&s, "ent=");
        put(&s, e->classname[0] ? e->classname : "<none>");
        put(&s, ",");
        put_i(&s, e->num_keys);
        put(&s, ",");
        put_i(&s, e->has_origin ? 1 : 0);
        if (e->has_origin) {
            put(&s, ",");
            put_f(&s, e->origin[0]); put(&s, ",");
            put_f(&s, e->origin[1]); put(&s, ",");
            put_f(&s, e->origin[2]);
        }
        put(&s, "\n");
    }

    put(&s, "world=");
    for (int k = 0; k < 3; k++) {
        put_f(&s, g->world_mins[k]);
        put(&s, ",");
    }
    for (int k = 0; k < 3; k++) {
        put_f(&s, g->world_maxs[k]);
        if (k < 2)
            put(&s, ",");
    }
    put(&s, "\n");

    if (out && capacity) {
        size_t end = s.needed < capacity - 1 ? s.needed : capacity - 1;
        out[end] = '\0';
    }
    return s.needed;
}

uint64_t MapGenGenome_Digest(const mapgen_genome_t *g)
{
    size_t needed = MapGenGenome_CanonicalText(g, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenGenome_CanonicalText(g, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}

const char *MapGenGenome_ResultName(mapgen_genome_result_t r)
{
    switch (r) {
    case MAPGEN_GENOME_OK:                       return "OK";
    case MAPGEN_GENOME_ERR_ARGUMENT:             return "ARGUMENT";
    case MAPGEN_GENOME_ERR_OUT_OF_MEMORY:        return "OUT_OF_MEMORY";
    case MAPGEN_GENOME_ERR_TOO_MANY_MATERIALS:   return "TOO_MANY_MATERIALS";
    case MAPGEN_GENOME_ERR_TOO_MANY_ENTITIES:    return "TOO_MANY_ENTITIES";
    case MAPGEN_GENOME_ERR_ENTITY_SYNTAX:        return "ENTITY_SYNTAX";
    case MAPGEN_GENOME_ERR_ENTITY_TOO_LONG:      return "ENTITY_TOO_LONG";
    default:                                     return "UNKNOWN";
    }
}
