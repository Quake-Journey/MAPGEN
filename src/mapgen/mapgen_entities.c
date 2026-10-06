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
 * MAPGEN-1 - placing what a player finds in the map.
 *
 * Spawn points first and spread across the graph, then items, then a light in
 * every room. Every placement is checked against the room it is going into and
 * against everything already placed; an exact count that cannot be met is a
 * refusal, because contract 13 makes it a hard constraint and not a target.
 */

#include "common/mapgen_entities.h"
#include "common/mapgen_features.h"   /* MAPGEN_FEATURES_LIGHT_COLOURS */
#include "common/mapgen_random.h"

#include <stdlib.h>
#include <string.h>

const char *MapGenEntities_ResultName(mapgen_entities_result_t r)
{
    switch (r) {
    case MAPGEN_ENTITIES_OK:                return "OK";
    case MAPGEN_ENTITIES_ERR_ARGS:          return "ERR_ARGS";
    case MAPGEN_ENTITIES_ERR_MEMORY:        return "ERR_MEMORY";
    case MAPGEN_ENTITIES_ERR_NO_ROOMS:      return "ERR_NO_ROOMS";
    case MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE: return "ERR_NO_SAFE_PLACE";
    case MAPGEN_ENTITIES_ERR_TOO_MANY:      return "ERR_TOO_MANY";
    }
    return "ERR_UNKNOWN";
}

/* ---- the item table ------------------------------------------------------ */

/*
 * Contract 13's rows, each with the recipe control that carries its resolved
 * count and the stock classname it becomes. One table, so a control cannot
 * exist without a classname or a classname without a control.
 */
typedef struct {
    const char *control;
    const char *classname;
} item_rule_t;

static const item_rule_t ITEM_RULES[] = {
    { "item_armor_jacket",     "item_armor_jacket" },
    { "item_armor_combat",     "item_armor_combat" },
    { "item_armor_body",       "item_armor_body" },
    { "item_health_mega",      "item_health_mega" },
    { "item_quad",             "item_quad" },
    { "item_invulnerability",  "item_invulnerability" },
    { "item_adrenaline",       "item_adrenaline" },
    { "item_bandolier",        "item_bandolier" },
    { "item_pack",             "item_pack" },
    { "weapon_shotgun",        "weapon_shotgun" },
    { "weapon_supershotgun",   "weapon_supershotgun" },
    { "weapon_machinegun",     "weapon_machinegun" },
    { "weapon_chaingun",       "weapon_chaingun" },
    { "weapon_grenadelauncher", "weapon_grenadelauncher" },
    { "weapon_rocketlauncher", "weapon_rocketlauncher" },
    { "weapon_hyperblaster",   "weapon_hyperblaster" },
    { "weapon_railgun",        "weapon_railgun" },
    { "item_armor_shard",      "item_armor_shard" },
    { "item_health",           "item_health" },
    { "item_health_small",     "item_health_small" },
    { "item_health_large",     "item_health_large" },
    { "ammo_shells",           "ammo_shells" },
    { "ammo_bullets",          "ammo_bullets" },
    { "ammo_cells",            "ammo_cells" },
    { "ammo_rockets",          "ammo_rockets" },
    { "ammo_slugs",            "ammo_slugs" },
    { "ammo_grenades",         "ammo_grenades" },
};

#define ITEM_RULE_COUNT (sizeof(ITEM_RULES) / sizeof(ITEM_RULES[0]))

uint32_t MapGenEntities_NumItemKinds(void)
{
    return (uint32_t)ITEM_RULE_COUNT;
}

const char *MapGenEntities_ItemControl(uint32_t index)
{
    return index < ITEM_RULE_COUNT ? ITEM_RULES[index].control : NULL;
}

const char *MapGenEntities_ItemClassname(uint32_t index)
{
    return index < ITEM_RULE_COUNT ? ITEM_RULES[index].classname : NULL;
}

/* ---- the model ----------------------------------------------------------- */

struct mapgen_entities_s {
    mapgen_placement_t *items;
    uint32_t         count;
};

/*
 * A placement has to leave room for what stands there. Everything placed is
 * kept at least this far from anything else, so two pickups never share a
 * spot and a spawning player never materializes inside one.
 */
#define PLACEMENT_CLEARANCE 64

static bool too_close(const mapgen_entities_t *e, const int32_t origin[3])
{
    for (uint32_t i = 0; i < e->count; i++) {
        int32_t d = 0;
        for (int axis = 0; axis < 3; axis++) {
            const int32_t delta = e->items[i].origin[axis] - origin[axis];
            d += delta < 0 ? -delta : delta;
        }
        if (d < PLACEMENT_CLEARANCE)
            return true;
    }
    return false;
}

static bool push(mapgen_entities_t *e, const char *classname,
                 const int32_t origin[3], int32_t angle, uint32_t room)
{
    if (e->count >= MAPGEN_ENTITIES_MAX)
        return false;
    void *grown = realloc(e->items, (size_t)(e->count + 1) * sizeof(*e->items));
    if (!grown)
        return false;
    e->items = grown;
    mapgen_placement_t *slot = &e->items[e->count++];
    memset(slot, 0, sizeof(*slot));
    const size_t n = strlen(classname);
    memcpy(slot->classname, classname,
           n < MAPGEN_PLACEMENT_CLASSNAME_BYTES - 1
           ? n : MAPGEN_PLACEMENT_CLASSNAME_BYTES - 1);
    memcpy(slot->origin, origin, sizeof(slot->origin));
    slot->angle = angle;
    slot->room = room;
    slot->light = 0;
    return true;
}

/*
 * Somewhere inside this room that nothing else has taken.
 *
 * The search is a fixed lattice rather than a series of draws: a draw that
 * keeps missing turns "there is no room" into "we were unlucky", and contract
 * 13 needs the difference between those two to be exact.
 */
static bool find_spot(const mapgen_entities_t *e,
                      const mapgen_layout_box_t *room,
                      int32_t offset, mapgen_random_t *rng,
                      int32_t out[3])
{
    const int32_t margin = MAPGEN_LAYOUT_HULL_WIDTH;
    const int32_t x0 = room->mins[0] + margin;
    const int32_t x1 = room->maxs[0] - margin;
    const int32_t y0 = room->mins[1] + margin;
    const int32_t y1 = room->maxs[1] - margin;
    if (x1 <= x0 || y1 <= y0)
        return false;
    if (room->maxs[2] - room->mins[2] < MAPGEN_LAYOUT_HULL_HEIGHT)
        return false;

    const int32_t step = PLACEMENT_CLEARANCE;
    const int32_t columns = (x1 - x0) / step + 1;
    const int32_t rows = (y1 - y0) / step + 1;
    const int32_t cells = columns * rows;
    if (cells <= 0)
        return false;

    /* Every cell is tried, starting from a drawn one so two rooms of the same
       size do not fill in the same pattern. */
    const int32_t first = MapGenRandom_Below(rng, (uint32_t)cells);
    for (int32_t i = 0; i < cells; i++) {
        const int32_t cell = (first + i) % cells;
        out[0] = x0 + (cell % columns) * step;
        out[1] = y0 + (cell / columns) * step;
        out[2] = room->mins[2] + offset;
        if (out[0] > x1 || out[1] > y1)
            continue;
        if (!too_close(e, out))
            return true;
    }
    return false;
}

/* ---- building ------------------------------------------------------------ */

/*
 * How many lights an area of this size earns out of the learned total.
 *
 * Rounded rather than truncated, so a hundred small areas each earning 0.6 of
 * a light do not all silently round to zero - and `floor_one` is what keeps a
 * room lit even when the arithmetic says it earned none.
 */
static int64_t lights_for_area(int64_t wanted, int64_t area, int64_t total,
                               int64_t floor_one)
{
    if (total <= 0 || wanted <= 0)
        return floor_one;
    const int64_t share = (wanted * area + total / 2) / total;
    return share > floor_one ? share : floor_one;
}

/*
 * One light's intensity.
 *
 * Drawn between the learned quartiles rather than stamped from the median,
 * because a map lit by ninety-seven identical sources clamps to white wherever
 * two of them overlap and sits at black between - and both of those are grey,
 * which is how a colored lightmap ends up looking like no lightmap at all.
 *
 * Then scaled to what this one has to cover. The corpus puts its 300s in halls
 * and its 60s in doorways; a source sized for a hall, placed in a corridor a
 * quarter as wide, is the same blow-out by another route.
 */
static int32_t draw_intensity(mapgen_random_t *rng, int32_t lower,
                              int32_t median, int32_t upper,
                              int32_t width, int32_t depth, int32_t height)
{
    /*
     * Half the draws fall between the lower quartile and the median and half
     * between the median and the upper one, which is what those three numbers
     * mean. Drawing uniformly across the whole range instead would put as much
     * weight on the extremes as on the middle, and the corpus does not.
     */
    int32_t from = lower, to = median;
    if (MapGenRandom_Below(rng, 2)) {
        from = median;
        to = upper;
    }
    const uint32_t span = (uint32_t)(to - from) + 1u;
    int64_t value = from + (int32_t)MapGenRandom_Below(rng, span);

    /*
     * And that is the whole of it. There WAS a step here that scaled the
     * learned value by how much space the light had to cover, and it was an
     * invention with a learned-looking wrapper - exactly what contract 19
     * forbids. MEASURED: it took a corpus median of 100 to 170 down to 30 to
     * 66, and a map lit by 119 sources at 30 has a lightmap mean of 0.1.
     *
     * It existed to stop corridors blowing out, and corridors were blowing out
     * because whole rooms were being built from light-emitting textures. That
     * is fixed where it belongs, so the learned intensity stands as learned.
     */
    (void)width;
    (void)depth;
    (void)height;

    if (value < MAPGEN_LIGHT_MIN_INTENSITY)
        value = MAPGEN_LIGHT_MIN_INTENSITY;
    return (int32_t)value;
}

mapgen_entities_result_t MapGenEntities_Build(const mapgen_layout_t *layout,
                                              const mapgen_topology_t *topology,
                                              const mapgen_mix_t *model,
                                              const mapgen_recipe_t *recipe,
                                              uint32_t attempt,
                                              const char **conflict,
                                              mapgen_entities_t **out)
{
    if (conflict)
        *conflict = NULL;
    if (out)
        *out = NULL;
    if (!layout || !topology || !model || !recipe || !out)
        return MAPGEN_ENTITIES_ERR_ARGS;

    const uint32_t rooms = MapGenLayout_NumRooms(layout);
    if (!rooms)
        return MAPGEN_ENTITIES_ERR_NO_ROOMS;

    mapgen_random_t rng;
    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,
                        MAPGEN_RANDOM_ITEMS);

    mapgen_entities_t *e = calloc(1, sizeof(*e));
    if (!e)
        return MAPGEN_ENTITIES_ERR_MEMORY;

    /* --- spawn points ------------------------------------------------------ */
    const mapgen_goal_t goal = MapGenRecipe_Goal(recipe);
    const char *spawn_class = goal == MAPGEN_GOAL_SINGLE_PLAYER
                            ? "info_player_start" : "info_player_deathmatch";

    /*
     * One per player the envelope resolved to, and never fewer than two for a
     * multiplayer map - a deathmatch map with one spawn is a map where the
     * second player telefrags the first.
     */
    uint32_t spawns = MapGenRecipe_PlayersMax(recipe);
    if (goal == MAPGEN_GOAL_SINGLE_PLAYER)
        spawns = 1;
    else if (spawns < 2)
        spawns = 2;

    /* Spread by ROOM: the room list is walked with a stride so consecutive
       spawns land as far apart in the graph as the room count allows. */
    const uint32_t stride = rooms > 2 ? (rooms / 2) | 1u : 1u;
    uint32_t room_at = MapGenRandom_Below(&rng, rooms);
    for (uint32_t i = 0; i < spawns; i++) {
        bool placed = false;
        for (uint32_t tries = 0; tries < rooms && !placed; tries++) {
            const uint32_t room = (room_at + tries * stride) % rooms;
            int32_t origin[3];
            if (!find_spot(e, &MapGenLayout_Room(layout, room)->space,
                           MAPGEN_PLACEMENT_FLOOR_OFFSET, &rng, origin))
                continue;
            if (!push(e, spawn_class, origin,
                      (int32_t)MapGenRandom_Below(&rng, 8) * 45, room)) {
                MapGenEntities_Free(e);
                return MAPGEN_ENTITIES_ERR_MEMORY;
            }
            placed = true;
        }
        if (!placed) {
            if (conflict)
                *conflict = "players_max";
            MapGenEntities_Free(e);
            return MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE;
        }
        room_at = (room_at + stride) % rooms;
    }

    /* --- items ------------------------------------------------------------- */
    for (uint32_t k = 0; k < ITEM_RULE_COUNT; k++) {
        const int32_t wanted =
            MapGenRecipe_ResolvedValue(recipe, ITEM_RULES[k].control, 0);
        if (wanted <= 0)
            continue;                       /* None is absolute */

        for (int32_t n = 0; n < wanted; n++) {
            bool placed = false;
            for (uint32_t tries = 0; tries < rooms && !placed; tries++) {
                const uint32_t room = (room_at + tries) % rooms;
                int32_t origin[3];
                if (!find_spot(e, &MapGenLayout_Room(layout, room)->space,
                               MAPGEN_PLACEMENT_ITEM_OFFSET, &rng, origin))
                    continue;
                if (!push(e, ITEM_RULES[k].classname, origin, 0, room)) {
                    MapGenEntities_Free(e);
                    return MAPGEN_ENTITIES_ERR_MEMORY;
                }
                placed = true;
            }
            if (!placed) {
                /* Contract 13: an exact count is a hard constraint. It is
                   refused with the control named, never quietly reduced. */
                if (conflict)
                    *conflict = ITEM_RULES[k].control;
                MapGenEntities_Free(e);
                return MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE;
            }
            room_at = (room_at + 1) % rooms;
        }
    }

    /* --- lights, by area and at the learned intensity ---------------------- */
    {
        /*
         * Both numbers come from a map the corpus actually contained, drawn
         * from the same weighted samples the topology was sized from. A
         * generator that invents a brightness is inventing what the maps it
         * learned from look like.
         */
        int32_t median = 0, lower = 0, upper = 0;
        int64_t wanted_lights = 0;
        const uint32_t sample = MapGenMix_DrawSample(model, &rng);
        if (sample < MapGenMix_NumSamples(model)) {
            median = (int32_t)MapGenMix_SampleValue(model, sample,
                                                    MAPGEN_MIX_STAT_LIGHT_MEDIAN);
            lower = (int32_t)MapGenMix_SampleValue(model, sample,
                                                   MAPGEN_MIX_STAT_LIGHT_LOWER);
            upper = (int32_t)MapGenMix_SampleValue(model, sample,
                                                   MAPGEN_MIX_STAT_LIGHT_UPPER);
            wanted_lights = MapGenMix_SampleValue(model, sample,
                                                  MAPGEN_MIX_STAT_LIGHTS);
        }
        if (median <= 0)
            median = 300;                   /* what the compiler would use */
        if (lower <= 0 || lower > median)
            lower = median;
        if (upper < median)
            upper = median;

        /*
         * The colours come from the whole SELECTION, not from the one sample
         * the map was sized from.
         *
         * A corpus is a union for materials and for roles, and a colour is the
         * same kind of fact: "these maps are lit like this". Reading only the
         * drawn sample meant a selection of ten maps produced a white map
         * whenever the draw landed on one of the several that carry no _color
         * at all - which is most of them, and which is why the first run after
         * this was learned still had none.
         */
        uint32_t colours[MAPGEN_FEATURES_LIGHT_COLOURS * 8] = { 0 };
        uint32_t num_colours = 0;
        for (uint32_t s = 0; s < MapGenMix_NumSamples(model)
                             && num_colours < sizeof(colours) / sizeof(colours[0]);
             s++) {
            for (uint32_t c = 0; c < MAPGEN_FEATURES_LIGHT_COLOURS; c++) {
                const int64_t packed = MapGenMix_SampleValue(
                    model, s,
                    (mapgen_mix_stat_t)(MAPGEN_MIX_STAT_LIGHT_COLOUR_0 + c));
                if (packed <= 0)
                    continue;
                bool already = false;
                for (uint32_t k = 0; k < num_colours; k++)
                    if (colours[k] == (uint32_t)packed)
                        already = true;
                if (!already
                    && num_colours < sizeof(colours) / sizeof(colours[0]))
                    colours[num_colours++] = (uint32_t)packed;
            }
        }
        if (wanted_lights <= 0)
            wanted_lights = (int64_t)rooms * 2;

        /*
         * Spread that many over the map in proportion to floor area, so an
         * arena gets more of them than a corridor. The spacing this replaces
         * was a fixed grid, and it put five to ten times as many lights in a
         * map as the corpus it was supposedly learning from.
         */
        int64_t total_area = 0;
        for (uint32_t room = 0; room < rooms; room++) {
            const mapgen_layout_box_t *box =
                &MapGenLayout_Room(layout, room)->space;
            total_area += (int64_t)(box->maxs[0] - box->mins[0])
                        * (box->maxs[1] - box->mins[1]);
        }
        for (uint32_t pass = 0; pass < MapGenLayout_NumPassages(layout); pass++) {
            const mapgen_layout_passage_t *p = MapGenLayout_Passage(layout, pass);
            for (uint32_t s = 0; s < p->num_segments; s++)
                total_area += (int64_t)(p->segments[s].maxs[0] - p->segments[s].mins[0])
                            * (p->segments[s].maxs[1] - p->segments[s].mins[1]);
        }
        if (total_area <= 0)
            total_area = 1;

        for (uint32_t room = 0; room < rooms; room++) {
            const mapgen_layout_box_t *box =
                &MapGenLayout_Room(layout, room)->space;
            int32_t z = box->maxs[2] - MAPGEN_LAYOUT_GRID * 2;
            if (z <= box->mins[2])
                z = box->mins[2] + MAPGEN_LAYOUT_GRID;

            /*
             * This area's share of the learned count, as a grid across it. A
             * room always earns at least one: a room nobody can see is not a
             * room.
             */
            const int32_t width = box->maxs[0] - box->mins[0];
            const int32_t depth = box->maxs[1] - box->mins[1];
            const int64_t share = lights_for_area(wanted_lights,
                                                  (int64_t)width * depth,
                                                  total_area, 1);
            int32_t across = 1, down = 1;
            while ((int64_t)(across + 1) * down <= share && across < 8)
                across++;
            while ((int64_t)across * (down + 1) <= share && down < 8)
                down++;

            for (int32_t cy = 0; cy < down; cy++) {
                for (int32_t cx = 0; cx < across; cx++) {
                    int32_t origin[3];
                    origin[0] = box->mins[0] + width * (2 * cx + 1) / (2 * across);
                    origin[1] = box->mins[1] + depth * (2 * cy + 1) / (2 * down);
                    origin[2] = z;
                    if (!push(e, "light", origin, 0, room)) {
                        MapGenEntities_Free(e);
                        return MAPGEN_ENTITIES_ERR_MEMORY;
                    }
                    e->items[e->count - 1].light =
                        draw_intensity(&rng, lower, median, upper,
                                       width / across, depth / down,
                                       box->maxs[2] - box->mins[2]);
                    e->items[e->count - 1].light_colour =
                        num_colours ? colours[MapGenRandom_Below(&rng,
                                                                 num_colours)]
                                    : 0;
                }
            }
        }

        /*
         * And the passages, which is most of the surface in these maps.
         *
         * Lighting only the rooms left the majority of every map lit by
         * nothing, and that - not the brightness - was why raising the
         * intensity barely moved the lightmap: 600 in the rooms did worse
         * than 170, because the number was never the thing that was wrong.
         */
        for (uint32_t pass = 0; pass < MapGenLayout_NumPassages(layout); pass++) {
            const mapgen_layout_passage_t *p = MapGenLayout_Passage(layout, pass);
            for (uint32_t s = 0; s < p->num_segments; s++) {
                const mapgen_layout_box_t *seg = &p->segments[s];
                const int32_t width = seg->maxs[0] - seg->mins[0];
                const int32_t depth = seg->maxs[1] - seg->mins[1];
                /*
                 * A stub earns a source only when its share says so. Giving
                 * every segment one regardless is what put sixty sources in
                 * the corridors of a map whose corpus asked for thirty in the
                 * whole thing.
                 */
                const int64_t share = lights_for_area(wanted_lights,
                                                      (int64_t)width * depth,
                                                      total_area, 0);
                if (share <= 0)
                    continue;
                int32_t across = 1, down = 1;
                while ((int64_t)(across + 1) * down <= share && across < 4)
                    across++;
                while ((int64_t)across * (down + 1) <= share && down < 4)
                    down++;

                int32_t z = seg->maxs[2] - MAPGEN_LAYOUT_GRID;
                if (z <= seg->mins[2])
                    z = seg->mins[2] + MAPGEN_LAYOUT_GRID;

                for (int32_t cy = 0; cy < down; cy++) {
                    for (int32_t cx = 0; cx < across; cx++) {
                        int32_t origin[3];
                        origin[0] = seg->mins[0]
                                  + width * (2 * cx + 1) / (2 * across);
                        origin[1] = seg->mins[1]
                                  + depth * (2 * cy + 1) / (2 * down);
                        origin[2] = z;
                        if (!push(e, "light", origin, 0,
                                  MAPGEN_PLACEMENT_NO_ROOM)) {
                            MapGenEntities_Free(e);
                            return MAPGEN_ENTITIES_ERR_MEMORY;
                        }
                        e->items[e->count - 1].light =
                            draw_intensity(&rng, lower, median, upper,
                                           width / across, depth / down,
                                           seg->maxs[2] - seg->mins[2]);
                        e->items[e->count - 1].light_colour =
                            num_colours ? colours[MapGenRandom_Below(
                                              &rng, num_colours)]
                                        : 0;
                    }
                }
            }
        }
    }

    (void)topology;

    *out = e;
    return MAPGEN_ENTITIES_OK;
}

void MapGenEntities_Free(mapgen_entities_t *e)
{
    if (!e)
        return;
    free(e->items);
    free(e);
}

/* ---- accessors ----------------------------------------------------------- */

uint32_t MapGenEntities_Count(const mapgen_entities_t *e)
{
    return e ? e->count : 0;
}

const mapgen_placement_t *MapGenEntities_At(const mapgen_entities_t *e,
                                         uint32_t index)
{
    return (e && index < e->count) ? &e->items[index] : NULL;
}

uint32_t MapGenEntities_CountOf(const mapgen_entities_t *e,
                                const char *classname)
{
    if (!e || !classname)
        return 0;
    uint32_t n = 0;
    for (uint32_t i = 0; i < e->count; i++)
        if (!strcmp(e->items[i].classname, classname))
            n++;
    return n;
}

/* ---- canonical form ------------------------------------------------------ */

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

static void put_i32(sink_t *s, int32_t value)
{
    char buf[16], tmp[16];
    size_t n = 0, t = 0;
    uint32_t u = value < 0 ? (uint32_t)(-(int64_t)value) : (uint32_t)value;
    if (value < 0)
        buf[n++] = '-';
    if (!u) {
        tmp[t++] = '0';
    } else {
        while (u) {
            tmp[t++] = (char)('0' + (u % 10u));
            u /= 10u;
        }
    }
    while (t)
        buf[n++] = tmp[--t];
    buf[n] = '\0';
    put(s, buf);
}

size_t MapGenEntities_CanonicalText(const mapgen_entities_t *e, char *out,
                                    size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!e) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    put(&s, "entities=");
    put_i32(&s, (int32_t)e->count);
    put(&s, "\n");
    for (uint32_t i = 0; i < e->count; i++) {
        put(&s, "e=");
        put(&s, e->items[i].classname);
        for (int axis = 0; axis < 3; axis++) {
            put(&s, ",");
            put_i32(&s, e->items[i].origin[axis]);
        }
        put(&s, ",");
        put_i32(&s, e->items[i].angle);
        put(&s, "\n");
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenEntities_CanonicalDigest(const mapgen_entities_t *e)
{
    const size_t needed = MapGenEntities_CanonicalText(e, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenEntities_CanonicalText(e, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
