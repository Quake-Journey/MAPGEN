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
 * MAPGEN-1 - the target/targetname graph.
 *
 * One pass to classify and index, one pass to link. Everything a real map does
 * is representable: a name shared by several entities fires all of them, a
 * target that names nothing is kept as a dangling link, and a ring of
 * path_corners is a cycle rather than an error.
 */

#include "common/mapgen_wiring.h"

#include <stdlib.h>
#include <string.h>

struct mapgen_wiring_s {
    mapgen_wiring_entity_t   *entities;
    uint32_t                  num_entities;
    mapgen_wiring_link_t     *links;
    uint32_t                  num_links;
    mapgen_wiring_dangling_t *dangling;
    uint32_t                  num_dangling;

    uint32_t num_teams;
    uint32_t num_shared_names;
    uint32_t num_on_cycle;
    uint32_t num_bad_submodels;
};

const char *MapGenWiring_ResultName(mapgen_wiring_result_t r)
{
    switch (r) {
    case MAPGEN_WIRING_OK:                 return "OK";
    case MAPGEN_WIRING_ERR_ARGS:           return "ERR_ARGS";
    case MAPGEN_WIRING_ERR_MEMORY:         return "ERR_MEMORY";
    case MAPGEN_WIRING_ERR_TOO_MANY_LINKS: return "ERR_TOO_MANY_LINKS";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenWiring_LinkKindName(mapgen_link_kind_t kind)
{
    switch (kind) {
    case MAPGEN_LINK_TARGET:     return "target";
    case MAPGEN_LINK_KILLTARGET: return "killtarget";
    case MAPGEN_LINK_PATHTARGET: return "pathtarget";
    case MAPGEN_LINK_KIND_COUNT: break;
    }
    return "?";
}

const char *MapGenWiring_LinkKindKey(mapgen_link_kind_t kind)
{
    /* The key really is the name here; kept as its own function so a caller
       cannot come to depend on that staying true. */
    return MapGenWiring_LinkKindName(kind);
}

/* ------------------------------------------------------------------------ */

typedef struct {
    const char *name;
    uint32_t    roles;
} class_role_t;

/*
 * The exact table comes first and decides on its own. Every classname the
 * corpus contains is here; the prefix rules below exist for the ones it does
 * not, which is most of Quake II's monster list.
 */
static const class_role_t EXACT_ROLES[] = {
    { "worldspawn",               MAPGEN_ENTROLE_WORLDSPAWN },

    { "info_player_deathmatch",   MAPGEN_ENTROLE_SPAWN_DM },
    { "info_player_start",        MAPGEN_ENTROLE_SPAWN_SP },
    { "info_player_coop",         MAPGEN_ENTROLE_SPAWN_COOP },
    { "info_player_intermission", MAPGEN_ENTROLE_INTERMISSION },
    { "info_intermission",        MAPGEN_ENTROLE_INTERMISSION },
    { "info_null",                MAPGEN_ENTROLE_MARKER },
    { "info_notnull",             MAPGEN_ENTROLE_MARKER },

    { "func_door",                MAPGEN_ENTROLE_DOOR | MAPGEN_ENTROLE_MOVER },
    { "func_door_rotating",       MAPGEN_ENTROLE_DOOR | MAPGEN_ENTROLE_MOVER | MAPGEN_ENTROLE_ROTATING },
    { "func_door_secret",         MAPGEN_ENTROLE_DOOR | MAPGEN_ENTROLE_MOVER },
    { "func_plat",                MAPGEN_ENTROLE_PLAT | MAPGEN_ENTROLE_MOVER },
    { "func_plat2",               MAPGEN_ENTROLE_PLAT | MAPGEN_ENTROLE_MOVER },
    { "func_train",               MAPGEN_ENTROLE_TRAIN | MAPGEN_ENTROLE_MOVER },
    { "func_button",              MAPGEN_ENTROLE_BUTTON | MAPGEN_ENTROLE_MOVER },
    { "func_rotating",            MAPGEN_ENTROLE_ROTATING | MAPGEN_ENTROLE_MOVER },
    { "func_water",               MAPGEN_ENTROLE_MOVER },
    { "func_timer",               MAPGEN_ENTROLE_TIMER },
    { "func_wall",                MAPGEN_ENTROLE_DECOR },
    { "func_areaportal",          MAPGEN_ENTROLE_AREAPORTAL },
    { "func_group",               MAPGEN_ENTROLE_EDITOR_LEFTOVER },
    { "func_object",              MAPGEN_ENTROLE_DECOR },
    { "func_explosive",           MAPGEN_ENTROLE_DECOR },
    { "func_killbox",             MAPGEN_ENTROLE_HAZARD },
    { "func_conveyor",            MAPGEN_ENTROLE_MOVER },

    { "misc_teleporter",          MAPGEN_ENTROLE_TELEPORTER },
    { "trigger_teleport",         MAPGEN_ENTROLE_TELEPORTER | MAPGEN_ENTROLE_TRIGGER },
    { "misc_teleporter_dest",     MAPGEN_ENTROLE_TELEPORT_DEST },
    { "info_teleport_destination", MAPGEN_ENTROLE_TELEPORT_DEST },

    { "trigger_push",             MAPGEN_ENTROLE_PUSH | MAPGEN_ENTROLE_TRIGGER },
    { "trigger_hurt",             MAPGEN_ENTROLE_HAZARD | MAPGEN_ENTROLE_TRIGGER },
    { "trigger_gravity",          MAPGEN_ENTROLE_TRIGGER },
    { "trigger_multiple",         MAPGEN_ENTROLE_TRIGGER },
    { "trigger_once",             MAPGEN_ENTROLE_TRIGGER },
    { "trigger_relay",            MAPGEN_ENTROLE_TRIGGER },
    { "trigger_always",           MAPGEN_ENTROLE_TRIGGER },
    { "trigger_counter",          MAPGEN_ENTROLE_TRIGGER },
    { "trigger_key",              MAPGEN_ENTROLE_TRIGGER },

    { "path_corner",              MAPGEN_ENTROLE_PATH },
    { "target_position",          MAPGEN_ENTROLE_PATH },
    { "target_speaker",           MAPGEN_ENTROLE_SOUND },
    { "target_splash",            MAPGEN_ENTROLE_DECOR },
    { "target_explosion",         MAPGEN_ENTROLE_HAZARD },
    { "target_laser",             MAPGEN_ENTROLE_HAZARD },
    { "target_changelevel",       MAPGEN_ENTROLE_CHANGELEVEL },
    { "target_spawner",           MAPGEN_ENTROLE_MARKER },

    { "misc_banner",              MAPGEN_ENTROLE_DECOR },
    { "misc_model",               MAPGEN_ENTROLE_DECOR },

    { "item_health",              MAPGEN_ENTROLE_HEALTH | MAPGEN_ENTROLE_ITEM },
    { "item_health_small",        MAPGEN_ENTROLE_HEALTH | MAPGEN_ENTROLE_ITEM },
    { "item_health_large",        MAPGEN_ENTROLE_HEALTH | MAPGEN_ENTROLE_ITEM },
    { "item_health_mega",         MAPGEN_ENTROLE_HEALTH | MAPGEN_ENTROLE_POWERUP | MAPGEN_ENTROLE_ITEM },
    { "item_armor_body",          MAPGEN_ENTROLE_ARMOR | MAPGEN_ENTROLE_ITEM },
    { "item_armor_combat",        MAPGEN_ENTROLE_ARMOR | MAPGEN_ENTROLE_ITEM },
    { "item_armor_jacket",        MAPGEN_ENTROLE_ARMOR | MAPGEN_ENTROLE_ITEM },
    { "item_armor_shard",         MAPGEN_ENTROLE_ARMOR | MAPGEN_ENTROLE_ITEM },
    { "item_power_screen",        MAPGEN_ENTROLE_ARMOR | MAPGEN_ENTROLE_ITEM },
    { "item_power_shield",        MAPGEN_ENTROLE_ARMOR | MAPGEN_ENTROLE_ITEM },
    { "item_quad",                MAPGEN_ENTROLE_POWERUP | MAPGEN_ENTROLE_ITEM },
    { "item_invulnerability",     MAPGEN_ENTROLE_POWERUP | MAPGEN_ENTROLE_ITEM },
    { "item_double",              MAPGEN_ENTROLE_POWERUP | MAPGEN_ENTROLE_ITEM },
    { "item_adrenaline",          MAPGEN_ENTROLE_POWERUP | MAPGEN_ENTROLE_ITEM },
    { "item_pack",                MAPGEN_ENTROLE_AMMO | MAPGEN_ENTROLE_ITEM },
    { "item_bandolier",           MAPGEN_ENTROLE_AMMO | MAPGEN_ENTROLE_ITEM },

    /* The one classname in the corpus that no prefix reaches: the Tag token
       from the mission packs, carried by two entities in one map. */
    { "dm_tag_token",             MAPGEN_ENTROLE_POWERUP | MAPGEN_ENTROLE_ITEM },
};

/*
 * Family prefixes, for the classnames the corpus does not contain. Applied
 * only when the exact table has nothing, so a name in the table can never be
 * overruled by a prefix that happens to match it.
 */
static const class_role_t PREFIX_ROLES[] = {
    { "monster_",  MAPGEN_ENTROLE_MONSTER },
    { "weapon_",   MAPGEN_ENTROLE_WEAPON | MAPGEN_ENTROLE_ITEM },
    { "ammo_",     MAPGEN_ENTROLE_AMMO | MAPGEN_ENTROLE_ITEM },
    { "key_",      MAPGEN_ENTROLE_ITEM },
    { "item_",     MAPGEN_ENTROLE_ITEM },
    { "light",     MAPGEN_ENTROLE_LIGHT },
    { "trigger_",  MAPGEN_ENTROLE_TRIGGER },
    { "func_",     MAPGEN_ENTROLE_MOVER },
    { "target_",   MAPGEN_ENTROLE_MARKER },
    { "misc_",     MAPGEN_ENTROLE_DECOR },
    { "info_",     MAPGEN_ENTROLE_MARKER },
};

uint32_t MapGenWiring_RolesForClassname(const char *classname)
{
    if (!classname || !*classname)
        return 0;

    for (size_t i = 0; i < sizeof(EXACT_ROLES) / sizeof(EXACT_ROLES[0]); i++)
        if (!strcmp(EXACT_ROLES[i].name, classname))
            return EXACT_ROLES[i].roles;

    for (size_t i = 0; i < sizeof(PREFIX_ROLES) / sizeof(PREFIX_ROLES[0]); i++) {
        const size_t n = strlen(PREFIX_ROLES[i].name);
        if (!strncmp(PREFIX_ROLES[i].name, classname, n))
            return PREFIX_ROLES[i].roles;
    }
    return 0;
}

static const struct { uint32_t bit; const char *name; } ROLE_NAMES[] = {
    { MAPGEN_ENTROLE_SPAWN_DM,        "spawn_dm" },
    { MAPGEN_ENTROLE_SPAWN_SP,        "spawn_sp" },
    { MAPGEN_ENTROLE_SPAWN_COOP,      "spawn_coop" },
    { MAPGEN_ENTROLE_INTERMISSION,    "intermission" },
    { MAPGEN_ENTROLE_WEAPON,          "weapon" },
    { MAPGEN_ENTROLE_AMMO,            "ammo" },
    { MAPGEN_ENTROLE_ARMOR,           "armor" },
    { MAPGEN_ENTROLE_HEALTH,          "health" },
    { MAPGEN_ENTROLE_POWERUP,         "powerup" },
    { MAPGEN_ENTROLE_ITEM,            "item" },
    { MAPGEN_ENTROLE_MONSTER,         "monster" },
    { MAPGEN_ENTROLE_DOOR,            "door" },
    { MAPGEN_ENTROLE_PLAT,            "plat" },
    { MAPGEN_ENTROLE_TRAIN,           "train" },
    { MAPGEN_ENTROLE_BUTTON,          "button" },
    { MAPGEN_ENTROLE_ROTATING,        "rotating" },
    { MAPGEN_ENTROLE_MOVER,           "mover" },
    { MAPGEN_ENTROLE_TELEPORTER,      "teleporter" },
    { MAPGEN_ENTROLE_TELEPORT_DEST,   "teleport_dest" },
    { MAPGEN_ENTROLE_PUSH,            "push" },
    { MAPGEN_ENTROLE_TRIGGER,         "trigger" },
    { MAPGEN_ENTROLE_HAZARD,          "hazard" },
    { MAPGEN_ENTROLE_PATH,            "path" },
    { MAPGEN_ENTROLE_TIMER,           "timer" },
    { MAPGEN_ENTROLE_MARKER,          "marker" },
    { MAPGEN_ENTROLE_LIGHT,           "light" },
    { MAPGEN_ENTROLE_SOUND,           "sound" },
    { MAPGEN_ENTROLE_DECOR,           "decor" },
    { MAPGEN_ENTROLE_WORLDSPAWN,      "worldspawn" },
    { MAPGEN_ENTROLE_AREAPORTAL,      "areaportal" },
    { MAPGEN_ENTROLE_CHANGELEVEL,     "changelevel" },
    { MAPGEN_ENTROLE_EDITOR_LEFTOVER, "editor_leftover" },
};

uint32_t MapGenWiring_RoleNames(uint32_t roles, const char **out, uint32_t capacity)
{
    uint32_t n = 0;
    for (size_t i = 0; i < sizeof(ROLE_NAMES) / sizeof(ROLE_NAMES[0]); i++) {
        if (!(roles & ROLE_NAMES[i].bit))
            continue;
        if (out && n < capacity)
            out[n] = ROLE_NAMES[i].name;
        n++;
    }
    return n;
}

/* ------------------------------------------------------------------------ */

/* "*12" -> 12; anything else -> -1. Deliberately strict: the value comes out
   of a file we did not write, and a partly numeric name is not a submodel. */
static int32_t parse_submodel(const char *model)
{
    if (!model || model[0] != '*' || !model[1])
        return -1;
    int64_t v = 0;
    for (const char *p = model + 1; *p; p++) {
        if (*p < '0' || *p > '9')
            return -1;
        v = v * 10 + (*p - '0');
        if (v > 0x7fffffff)
            return -1;
    }
    return (int32_t)v;
}

static const char *value_of(const mapgen_entity_t *ent, const char *key)
{
    return MapGenGenome_EntityValue(ent, key);
}

static bool push_link(mapgen_wiring_t *w, uint32_t *capacity,
                      uint32_t from, uint32_t to, uint8_t kind)
{
    if (w->num_links >= MAPGEN_WIRING_MAX_LINKS)
        return false;
    if (w->num_links == *capacity) {
        uint32_t want = *capacity ? *capacity * 2u : 256u;
        if (want > MAPGEN_WIRING_MAX_LINKS)
            want = MAPGEN_WIRING_MAX_LINKS;
        void *grown = realloc(w->links, (size_t)want * sizeof(*w->links));
        if (!grown)
            return false;
        w->links = grown;
        *capacity = want;
    }
    w->links[w->num_links].from = from;
    w->links[w->num_links].to = to;
    w->links[w->num_links].kind = kind;
    w->num_links++;
    return true;
}

static bool push_dangling(mapgen_wiring_t *w, uint32_t *capacity,
                          uint32_t from, uint8_t kind, const char *name)
{
    if (w->num_dangling >= MAPGEN_WIRING_MAX_DANGLING)
        return true;            /* a cap on reporting is not a build failure */
    if (w->num_dangling == *capacity) {
        uint32_t want = *capacity ? *capacity * 2u : 32u;
        if (want > MAPGEN_WIRING_MAX_DANGLING)
            want = MAPGEN_WIRING_MAX_DANGLING;
        void *grown = realloc(w->dangling, (size_t)want * sizeof(*w->dangling));
        if (!grown)
            return false;
        w->dangling = grown;
        *capacity = want;
    }
    mapgen_wiring_dangling_t *d = &w->dangling[w->num_dangling++];
    d->from = from;
    d->kind = kind;
    memset(d->name, 0, sizeof(d->name));
    if (name) {
        size_t n = strlen(name);
        if (n >= sizeof(d->name))
            n = sizeof(d->name) - 1;
        memcpy(d->name, name, n);
    }
    return true;
}

/* --- cycles -------------------------------------------------------------- */

/*
 * "On a cycle" means one thing precisely: the entity is in a strongly
 * connected component of more than one entity, or it targets itself. That is
 * Tarjan's definition, and it is what is computed here.
 *
 * The obvious cheaper answer - unwind the DFS stack whenever a back edge is
 * found - is NOT the same thing, and gets it wrong in both directions. It was
 * the first implementation, and the independent Python build disagreed with it
 * on four shipped maps.
 *
 * Iterative, with explicit stacks: a link graph comes out of a file, and a
 * deep chain must not become a stack overflow. A ring of path_corners is a
 * cycle by design, so this counts and never refuses.
 */

#define TARJAN_UNSET  UINT32_MAX

typedef struct {
    uint32_t *first;       /* CSR offsets into `sorted`                     */
    uint32_t *sorted;      /* link indices grouped by their `from`          */
    uint32_t *index;
    uint32_t *lowlink;
    uint32_t *component;   /* the SCC stack                                 */
    uint8_t  *on_component;
    uint32_t *frame_node;
    uint32_t *frame_cursor;
} tarjan_t;

static void tarjan_free(tarjan_t *t)
{
    free(t->first); free(t->sorted); free(t->index); free(t->lowlink);
    free(t->component); free(t->on_component);
    free(t->frame_node); free(t->frame_cursor);
    memset(t, 0, sizeof(*t));
}

static bool build_adjacency(const mapgen_wiring_t *w, tarjan_t *t)
{
    const uint32_t n = w->num_entities;
    t->first = calloc((size_t)n + 1, sizeof(uint32_t));
    t->sorted = w->num_links ? malloc((size_t)w->num_links * sizeof(uint32_t)) : NULL;
    if (!t->first || (w->num_links && !t->sorted))
        return false;

    for (uint32_t i = 0; i < w->num_links; i++)
        t->first[w->links[i].from + 1]++;
    for (uint32_t i = 0; i < n; i++)
        t->first[i + 1] += t->first[i];

    uint32_t *fill = calloc(n ? n : 1, sizeof(uint32_t));
    if (!fill)
        return false;
    for (uint32_t i = 0; i < w->num_links; i++) {
        const uint32_t f = w->links[i].from;
        t->sorted[t->first[f] + fill[f]++] = i;
    }
    free(fill);
    return true;
}

static void close_component(mapgen_wiring_t *w, tarjan_t *t, uint32_t root,
                            uint32_t *component_top)
{
    /* Pop one strongly connected component. */
    uint32_t size = 0;
    uint32_t member;
    const uint32_t base = *component_top;
    do {
        member = t->component[--(*component_top)];
        t->on_component[member] = 0;
        size++;
    } while (member != root);

    bool cyclic = size > 1;
    if (!cyclic) {
        /* A single entity is on a cycle only if it targets itself. */
        for (uint32_t k = t->first[root]; k < t->first[root + 1]; k++)
            if (w->links[t->sorted[k]].to == root) {
                cyclic = true;
                break;
            }
    }
    if (!cyclic)
        return;
    for (uint32_t s = *component_top; s < base; s++) {
        if (!w->entities[t->component[s]].on_cycle) {
            w->entities[t->component[s]].on_cycle = true;
            w->num_on_cycle++;
        }
    }
}

static bool mark_cycles(mapgen_wiring_t *w)
{
    const uint32_t n = w->num_entities;
    if (!n)
        return true;

    tarjan_t t;
    memset(&t, 0, sizeof(t));
    if (!build_adjacency(w, &t)) {
        tarjan_free(&t);
        return false;
    }
    t.index = malloc((size_t)n * sizeof(uint32_t));
    t.lowlink = malloc((size_t)n * sizeof(uint32_t));
    t.component = malloc((size_t)n * sizeof(uint32_t));
    t.on_component = calloc(n, sizeof(uint8_t));
    t.frame_node = malloc((size_t)n * sizeof(uint32_t));
    t.frame_cursor = malloc((size_t)n * sizeof(uint32_t));
    if (!t.index || !t.lowlink || !t.component || !t.on_component ||
        !t.frame_node || !t.frame_cursor) {
        tarjan_free(&t);
        return false;
    }
    for (uint32_t i = 0; i < n; i++)
        t.index[i] = TARJAN_UNSET;

    uint32_t counter = 0;
    uint32_t component_top = 0;

    for (uint32_t root = 0; root < n; root++) {
        if (t.index[root] != TARJAN_UNSET)
            continue;

        uint32_t frames = 0;
        t.index[root] = t.lowlink[root] = counter++;
        t.component[component_top++] = root;
        t.on_component[root] = 1;
        t.frame_node[frames] = root;
        t.frame_cursor[frames] = t.first[root];
        frames++;

        while (frames) {
            const uint32_t v = t.frame_node[frames - 1];
            if (t.frame_cursor[frames - 1] < t.first[v + 1]) {
                const uint32_t link = t.sorted[t.frame_cursor[frames - 1]++];
                const uint32_t next = w->links[link].to;
                if (t.index[next] == TARJAN_UNSET) {
                    t.index[next] = t.lowlink[next] = counter++;
                    t.component[component_top++] = next;
                    t.on_component[next] = 1;
                    t.frame_node[frames] = next;
                    t.frame_cursor[frames] = t.first[next];
                    frames++;
                } else if (t.on_component[next] &&
                           t.index[next] < t.lowlink[v]) {
                    t.lowlink[v] = t.index[next];
                }
                continue;
            }

            frames--;
            if (t.lowlink[v] == t.index[v])
                close_component(w, &t, v, &component_top);
            if (frames) {
                const uint32_t parent = t.frame_node[frames - 1];
                if (t.lowlink[v] < t.lowlink[parent])
                    t.lowlink[parent] = t.lowlink[v];
            }
        }
    }

    tarjan_free(&t);
    return true;
}

/* ------------------------------------------------------------------------ */

mapgen_wiring_result_t MapGenWiring_Build(const mapgen_genome_t *genome,
                                          const mapgen_bsp_t *bsp,
                                          mapgen_wiring_t **out)
{
    if (!genome || !out)
        return MAPGEN_WIRING_ERR_ARGS;
    *out = NULL;

    const uint32_t count = MapGenGenome_NumEntities(genome);

    mapgen_wiring_t *w = calloc(1, sizeof(*w));
    if (!w)
        return MAPGEN_WIRING_ERR_MEMORY;
    w->num_entities = count;
    if (count) {
        w->entities = calloc(count, sizeof(*w->entities));
        if (!w->entities) {
            MapGenWiring_Free(w);
            return MAPGEN_WIRING_ERR_MEMORY;
        }
    }

    const uint32_t models = bsp ? MapGenBsp_NumModels(bsp) : 0;

    for (uint32_t i = 0; i < count; i++) {
        const mapgen_entity_t *ent = MapGenGenome_Entity(genome, i);
        mapgen_wiring_entity_t *e = &w->entities[i];
        e->roles = MapGenWiring_RolesForClassname(ent->classname);
        e->team = UINT32_MAX;
        e->submodel = parse_submodel(value_of(ent, "model"));
        if (e->submodel >= 0 && bsp && (uint32_t)e->submodel >= models) {
            w->num_bad_submodels++;
            e->submodel = -1;
        }
    }

    /* --- teams. Small and quadratic on purpose: 71 team values in the whole
       corpus, and a hash table would be more machinery than the data. */
    for (uint32_t i = 0; i < count; i++) {
        const char *team = value_of(MapGenGenome_Entity(genome, i), "team");
        if (!team || !*team || w->entities[i].team != UINT32_MAX)
            continue;
        const uint32_t id = w->num_teams++;
        for (uint32_t j = i; j < count; j++) {
            const char *other = value_of(MapGenGenome_Entity(genome, j), "team");
            if (other && !strcmp(other, team))
                w->entities[j].team = id;
        }
    }

    /* --- links. One-to-many: a name shared by several entities fires all. */
    uint32_t link_cap = 0, dangle_cap = 0;
    static const char *LINK_KEYS[MAPGEN_LINK_KIND_COUNT] = {
        "target", "killtarget", "pathtarget",
    };

    for (uint32_t i = 0; i < count; i++) {
        const mapgen_entity_t *ent = MapGenGenome_Entity(genome, i);
        for (uint32_t k = 0; k < MAPGEN_LINK_KIND_COUNT; k++) {
            const char *want = value_of(ent, LINK_KEYS[k]);
            if (!want || !*want)
                continue;
            uint32_t matched = 0;
            for (uint32_t j = 0; j < count; j++) {
                const char *name = value_of(MapGenGenome_Entity(genome, j), "targetname");
                if (!name || strcmp(name, want))
                    continue;
                if (!push_link(w, &link_cap, i, j, (uint8_t)k)) {
                    MapGenWiring_Free(w);
                    return MAPGEN_WIRING_ERR_TOO_MANY_LINKS;
                }
                w->entities[i].out_links++;
                w->entities[j].in_links++;
                matched++;
            }
            if (!matched && !push_dangling(w, &dangle_cap, i, (uint8_t)k, want)) {
                MapGenWiring_Free(w);
                return MAPGEN_WIRING_ERR_MEMORY;
            }
        }
    }

    /* --- names carried by more than one entity. */
    for (uint32_t i = 0; i < count; i++) {
        const char *name = value_of(MapGenGenome_Entity(genome, i), "targetname");
        if (!name || !*name)
            continue;
        bool first_of_its_name = true;
        uint32_t sharing = 0;
        for (uint32_t j = 0; j < count; j++) {
            const char *other = value_of(MapGenGenome_Entity(genome, j), "targetname");
            if (!other || strcmp(other, name))
                continue;
            if (j < i) {
                first_of_its_name = false;
                break;
            }
            sharing++;
        }
        if (first_of_its_name && sharing > 1)
            w->num_shared_names++;
    }

    if (!mark_cycles(w)) {
        MapGenWiring_Free(w);
        return MAPGEN_WIRING_ERR_MEMORY;
    }

    *out = w;
    return MAPGEN_WIRING_OK;
}

void MapGenWiring_Free(mapgen_wiring_t *w)
{
    if (!w)
        return;
    free(w->entities);
    free(w->links);
    free(w->dangling);
    free(w);
}

/* ------------------------------------------------------------------------ */

uint32_t MapGenWiring_NumEntities(const mapgen_wiring_t *w)     { return w ? w->num_entities : 0; }
uint32_t MapGenWiring_NumLinks(const mapgen_wiring_t *w)        { return w ? w->num_links : 0; }
uint32_t MapGenWiring_NumDangling(const mapgen_wiring_t *w)     { return w ? w->num_dangling : 0; }
uint32_t MapGenWiring_NumTeams(const mapgen_wiring_t *w)        { return w ? w->num_teams : 0; }
uint32_t MapGenWiring_NumSharedNames(const mapgen_wiring_t *w)  { return w ? w->num_shared_names : 0; }
uint32_t MapGenWiring_NumOnCycle(const mapgen_wiring_t *w)      { return w ? w->num_on_cycle : 0; }
uint32_t MapGenWiring_NumBadSubmodels(const mapgen_wiring_t *w) { return w ? w->num_bad_submodels : 0; }

const mapgen_wiring_entity_t *MapGenWiring_Entity(const mapgen_wiring_t *w, uint32_t i)
{
    return (w && i < w->num_entities) ? &w->entities[i] : NULL;
}

const mapgen_wiring_link_t *MapGenWiring_Link(const mapgen_wiring_t *w, uint32_t i)
{
    return (w && i < w->num_links) ? &w->links[i] : NULL;
}

const mapgen_wiring_dangling_t *MapGenWiring_Dangling(const mapgen_wiring_t *w, uint32_t i)
{
    return (w && i < w->num_dangling) ? &w->dangling[i] : NULL;
}

uint32_t MapGenWiring_CountRole(const mapgen_wiring_t *w, uint32_t roles)
{
    if (!w || !roles)
        return 0;
    uint32_t n = 0;
    for (uint32_t i = 0; i < w->num_entities; i++)
        if ((w->entities[i].roles & roles) == roles)
            n++;
    return n;
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
    size_t t = 0;
    if (!m) {
        tmp[t++] = '0';
    } else {
        while (m) {
            tmp[t++] = (char)('0' + (m % 10u));
            m /= 10u;
        }
    }
    while (t)
        buf[n++] = tmp[--t];
    buf[n] = '\0';
    sink_str(s, buf);
}

size_t MapGenWiring_CanonicalText(const mapgen_wiring_t *w, char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!w) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    sink_str(&s, "entities="); sink_i64(&s, w->num_entities); sink_str(&s, "\n");
    for (uint32_t i = 0; i < w->num_entities; i++) {
        const mapgen_wiring_entity_t *e = &w->entities[i];
        sink_str(&s, "w=");
        sink_i64(&s, e->roles); sink_str(&s, ",");
        sink_i64(&s, e->submodel); sink_str(&s, ",");
        sink_i64(&s, e->out_links); sink_str(&s, ",");
        sink_i64(&s, e->in_links); sink_str(&s, ",");
        sink_i64(&s, e->team == UINT32_MAX ? -1 : (int64_t)e->team); sink_str(&s, ",");
        sink_i64(&s, e->on_cycle ? 1 : 0); sink_str(&s, "\n");
    }

    sink_str(&s, "links="); sink_i64(&s, w->num_links); sink_str(&s, "\n");
    for (uint32_t i = 0; i < w->num_links; i++) {
        sink_str(&s, "l=");
        sink_i64(&s, w->links[i].from); sink_str(&s, ",");
        sink_i64(&s, w->links[i].to); sink_str(&s, ",");
        sink_str(&s, MapGenWiring_LinkKindName((mapgen_link_kind_t)w->links[i].kind));
        sink_str(&s, "\n");
    }

    sink_str(&s, "dangling="); sink_i64(&s, w->num_dangling); sink_str(&s, "\n");
    for (uint32_t i = 0; i < w->num_dangling; i++) {
        sink_str(&s, "d=");
        sink_i64(&s, w->dangling[i].from); sink_str(&s, ",");
        sink_str(&s, MapGenWiring_LinkKindName((mapgen_link_kind_t)w->dangling[i].kind));
        sink_str(&s, ",");
        sink_str(&s, w->dangling[i].name);
        sink_str(&s, "\n");
    }

    sink_str(&s, "teams="); sink_i64(&s, w->num_teams); sink_str(&s, "\n");
    sink_str(&s, "shared_names="); sink_i64(&s, w->num_shared_names); sink_str(&s, "\n");
    sink_str(&s, "on_cycle="); sink_i64(&s, w->num_on_cycle); sink_str(&s, "\n");
    sink_str(&s, "bad_submodels="); sink_i64(&s, w->num_bad_submodels); sink_str(&s, "\n");

    for (size_t i = 0; i < sizeof(ROLE_NAMES) / sizeof(ROLE_NAMES[0]); i++) {
        sink_str(&s, "role=");
        sink_str(&s, ROLE_NAMES[i].name);
        sink_str(&s, ",");
        sink_i64(&s, MapGenWiring_CountRole(w, ROLE_NAMES[i].bit));
        sink_str(&s, "\n");
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenWiring_CanonicalDigest(const mapgen_wiring_t *w)
{
    const size_t needed = MapGenWiring_CanonicalText(w, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenWiring_CanonicalText(w, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;      /* FNV-1a 64 offset basis   */
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
