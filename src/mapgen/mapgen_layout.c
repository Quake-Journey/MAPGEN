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
 * MAPGEN-1 - placing the graph in space.
 *
 * The skeleton of the topology graph is a tree, and a tree can be embedded on
 * a grid with no crossings at all: each room is placed in a cell next to its
 * parent's. The loop routes added on top are the ones that can cross
 * something, so they are the ones that get checked - and a candidate whose
 * corridors would cut through a room they do not connect is refused rather
 * than shipped with a connectivity nobody planned.
 */

#include "common/mapgen_layout.h"
#include "common/mapgen_genome.h"   /* MAPGEN_ROLE_WATER and its two siblings */
#include "common/mapgen_random.h"

#include <stdlib.h>
#include <string.h>

const char *MapGenLayout_ResultName(mapgen_layout_result_t r)
{
    switch (r) {
    case MAPGEN_LAYOUT_OK:                  return "OK";
    case MAPGEN_LAYOUT_ERR_ARGS:            return "ERR_ARGS";
    case MAPGEN_LAYOUT_ERR_MEMORY:          return "ERR_MEMORY";
    case MAPGEN_LAYOUT_ERR_NO_NODES:        return "ERR_NO_NODES";
    case MAPGEN_LAYOUT_ERR_NO_ROOM_TO_PLACE: return "ERR_NO_ROOM_TO_PLACE";
    case MAPGEN_LAYOUT_ERR_INTERSECTION:    return "ERR_INTERSECTION";
    case MAPGEN_LAYOUT_ERR_TOO_STEEP:       return "ERR_TOO_STEEP";
    case MAPGEN_LAYOUT_ERR_OUT_OF_WORLD:    return "ERR_OUT_OF_WORLD";
    }
    return "ERR_UNKNOWN";
}

struct mapgen_layout_s {
    mapgen_layout_room_t    *rooms;
    uint32_t                 num_rooms;
    mapgen_layout_passage_t *passages;
    uint32_t                 num_passages;
    mapgen_layout_pool_t     pools[MAPGEN_LAYOUT_MAX_POOLS];
    uint32_t                 num_pools;
    uint32_t                 num_junctions;
    mapgen_layout_box_t      bounds;
};

/* ---- boxes --------------------------------------------------------------- */

/* Overlap of interiors. Two boxes that merely touch do not overlap: a corridor
   ending flush against a room's wall is how it connects, not a fault. */
static bool boxes_overlap(const mapgen_layout_box_t *a,
                          const mapgen_layout_box_t *b)
{
    for (int axis = 0; axis < 3; axis++)
        if (a->maxs[axis] <= b->mins[axis] || a->mins[axis] >= b->maxs[axis])
            return false;
    return true;
}

static void box_grow(mapgen_layout_box_t *bounds, const mapgen_layout_box_t *b)
{
    for (int axis = 0; axis < 3; axis++) {
        if (b->mins[axis] < bounds->mins[axis])
            bounds->mins[axis] = b->mins[axis];
        if (b->maxs[axis] > bounds->maxs[axis])
            bounds->maxs[axis] = b->maxs[axis];
    }
}

static int32_t snap(int32_t v)
{
    /* Toward negative infinity, so a negative coordinate snaps the same way a
       positive one does and the grid stays uniform across the origin. */
    const int32_t g = MAPGEN_LAYOUT_GRID;
    return (v >= 0 ? (v / g) : ((v - g + 1) / g)) * g;
}

static bool inside_world(const mapgen_layout_box_t *b)
{
    for (int axis = 0; axis < 3; axis++)
        if (b->mins[axis] < -MAPGEN_LAYOUT_WORLD_LIMIT
            || b->maxs[axis] > MAPGEN_LAYOUT_WORLD_LIMIT)
            return false;
    return true;
}

/* ---- placing ------------------------------------------------------------- */

typedef struct {
    int32_t cell[2];
    bool    placed;
} slot_t;

/* A cell whose room and its lanes still fit inside Quake II's world. */
static bool cell_in_world(int32_t cx, int32_t cy)
{
    /* Half a cell for the room, and a corridor for the lane beside it. A
       whole cell each side left three cells in the entire world. */
    const int32_t reach = MAPGEN_LAYOUT_CELL / 2 + MAPGEN_LAYOUT_CORRIDOR_WIDTH;
    const int64_t x = (int64_t)cx * MAPGEN_LAYOUT_CELL;
    const int64_t y = (int64_t)cy * MAPGEN_LAYOUT_CELL;
    return x - reach >= -MAPGEN_LAYOUT_WORLD_LIMIT
        && x + reach <= MAPGEN_LAYOUT_WORLD_LIMIT
        && y - reach >= -MAPGEN_LAYOUT_WORLD_LIMIT
        && y + reach <= MAPGEN_LAYOUT_WORLD_LIMIT;
}

static bool cell_taken(const slot_t *slots, uint32_t count,
                       int32_t cx, int32_t cy)
{
    for (uint32_t i = 0; i < count; i++)
        if (slots[i].placed && slots[i].cell[0] == cx && slots[i].cell[1] == cy)
            return true;
    return false;
}

/* Is `route` the one connecting these two rooms? */
static bool connects(const mapgen_topology_t *topology, uint32_t route,
                     uint32_t a, uint32_t b)
{
    const mapgen_topology_route_t *r = MapGenTopology_Route(topology, route);
    if (!r)
        return false;
    return (r->from == a && r->to == b) || (r->from == b && r->to == a);
}

/*
 * The three liquids, each with the role that has to have been learned and the
 * control that gates it. One table, so contract 14's "None is absolute" and
 * contract 15's "never emit an unlearned motif" stay the same lookup.
 */
typedef struct {
    uint32_t    role;
    const char *control;
} liquid_rule_t;

static const liquid_rule_t LIQUID_RULES[] = {
    { MAPGEN_ROLE_WATER, "arch_water" },
    { MAPGEN_ROLE_LAVA,  "arch_lava"  },
    { MAPGEN_ROLE_SLIME, "arch_slime" },
};

/*
 * Sink pools into the floors of some rooms.
 *
 * How many is the sum of what the three controls ask for, capped by how many
 * rooms are big enough to hold one and still leave a lip to stand on. A room
 * gets at most one.
 */
static void place_pools(mapgen_layout_t *l, const mapgen_mix_t *model,
                        const mapgen_recipe_t *recipe, mapgen_random_t *rng)
{
    uint32_t available[3];
    uint32_t num_available = 0;
    uint32_t wanted = 0;

    for (uint32_t i = 0; i < 3; i++) {
        const int32_t level =
            MapGenRecipe_ResolvedValue(recipe, LIQUID_RULES[i].control, 2);
        if (level <= 0)
            continue;                       /* None is absolute */
        if (!model || !MapGenMix_MaterialRoleIsLearned(model, LIQUID_RULES[i].role))
            continue;                       /* never learned, so never emitted */
        available[num_available++] = i;
        wanted += (uint32_t)level;          /* Low 1, Balanced 2, High 3 */
    }
    if (!num_available)
        return;

    /* A pool needs a room wide enough to keep a lip on all four sides. */
    const int32_t needed = 2 * MAPGEN_LAYOUT_POOL_INSET + 2 * MAPGEN_LAYOUT_CORRIDOR_WIDTH;

    for (uint32_t r = 0; r < l->num_rooms && l->num_pools < MAPGEN_LAYOUT_MAX_POOLS
                         && l->num_pools < wanted; r++) {
        const mapgen_layout_box_t *space = &l->rooms[r].space;
        const int32_t width = space->maxs[0] - space->mins[0];
        const int32_t depth = space->maxs[1] - space->mins[1];
        if (width < needed || depth < needed)
            continue;
        /* Not every big room: a map where every floor is a pool reads as a
           swimming pool rather than as a map with water in it. */
        if (MapGenRandom_Below(rng, 2) == 0)
            continue;

        mapgen_layout_pool_t *pool = &l->pools[l->num_pools++];
        /*
         * A pit in a floor is WATER where the corpus learned one.
         *
         * A pool here is ninety-six units below a floor a player fights on,
         * and the only way out of one is to swim up and step over the lip.
         * That works in water and it is death in slime or lava: MEASURED on
         * the invented map of 2026-09-07 evening, whose one pool came out
         * slime - the reachability explorer found a hundred and fifty-one
         * one-way transitions, every one of them lethal, where there had been
         * none. Lava and slime are hazards a map builds AROUND; until this
         * generator builds a ledge and a way out, it does not put one in the
         * floor of a room.
         */
        uint32_t pick = available[MapGenRandom_Below(rng, num_available)];
        for (uint32_t k = 0; k < num_available; k++)
            if (LIQUID_RULES[available[k]].role == MAPGEN_ROLE_WATER)
                pick = available[k];
        pool->role = LIQUID_RULES[pick].role;
        pool->room = r;

        pool->space.mins[0] = space->mins[0] + MAPGEN_LAYOUT_POOL_INSET;
        pool->space.maxs[0] = space->maxs[0] - MAPGEN_LAYOUT_POOL_INSET;
        pool->space.mins[1] = space->mins[1] + MAPGEN_LAYOUT_POOL_INSET;
        pool->space.maxs[1] = space->maxs[1] - MAPGEN_LAYOUT_POOL_INSET;
        pool->space.mins[2] = space->mins[2] - MAPGEN_LAYOUT_POOL_DEPTH;
        pool->space.maxs[2] = space->mins[2];

        /*
         * The liquid stops short of the rim, so the surface is visible from
         * the floor around it rather than flush with it.
         */
        pool->liquid = pool->space;
        pool->liquid.maxs[2] = pool->space.maxs[2] - 16;

        /* The pit hangs below the room, so the world got taller. */
        box_grow(&l->bounds, &pool->space);
    }
}

mapgen_layout_result_t MapGenLayout_Build(const mapgen_topology_t *topology,
                                          const mapgen_mix_t *model,
                                          const mapgen_recipe_t *recipe,
                                          uint32_t attempt,
                                          mapgen_layout_t **out)
{
    /* Cleared first: a refused build must not leave a stale layout in the
       caller's hands, and returning before this is how that happens. */
    if (out)
        *out = NULL;
    if (!topology || !recipe || !out)
        return MAPGEN_LAYOUT_ERR_ARGS;

    const uint32_t nodes = MapGenTopology_NumNodes(topology);
    if (!nodes)
        return MAPGEN_LAYOUT_ERR_NO_NODES;

    mapgen_random_t rng;
    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,
                        MAPGEN_RANDOM_BRUSHES);

    /*
     * How much of this map is open to the sky, and whether the corpus taught a
     * sky material at all. A selection without one cannot produce a courtyard,
     * and contract 15 says so.
     */
    const bool sky_material_learned =
        model && MapGenMix_MaterialRoleIsLearned(model, MAPGEN_ROLE_SKY);
    int64_t sky_rooms_permille = 0;
    if (sky_material_learned) {
        for (uint32_t s = 0; s < MapGenMix_NumSamples(model); s++) {
            const int64_t share = MapGenMix_SampleValue(
                model, s, MAPGEN_MIX_STAT_SKY_PERMILLE);
            if (share > sky_rooms_permille)
                sky_rooms_permille = share;
        }
        /*
         * The learned figure is a share of SURFACE and this is a share of
         * ROOMS. A courtyard's sky is one face of six, so a map whose surface
         * is 23 parts per thousand sky has rather more than 23 parts per
         * thousand of its rooms outdoors. Six faces to a room is the
         * conversion; it is stated here rather than tuned until it looked
         * right.
         */
        sky_rooms_permille *= 6;
        if (sky_rooms_permille > 500)
            sky_rooms_permille = 500;
    }

    /*
     * And what the RECIPE asks for, which overrides what the corpus happened
     * to teach.
     *
     * The learned figure is a description of the maps in the snapshot; it is
     * not a design. MEASURED on the invented map of 2026-09-07: thirty-nine
     * sky sides out of four thousand six hundred and thirty-two, which is a
     * map with a lid on it, and the PO asked for one with sky over it. So
     * `arch_open_sky` says how much of the map is outdoors, from none to most
     * of it, and a selection that never learned a sky material still cannot
     * produce one - that part is contract 15 and stays.
     */
    if (sky_material_learned) {
        static const int64_t OPEN_SKY[5] = { 0, 150, 300, 450, 650 };
        const int32_t asked =
            MapGenRecipe_ResolvedValue(recipe, "arch_open_sky", -1);
        if (asked >= 0 && asked < 5)
            sky_rooms_permille = OPEN_SKY[asked];
    }

    slot_t *slots = calloc(nodes, sizeof(*slots));
    mapgen_layout_t *l = calloc(1, sizeof(*l));
    if (!slots || !l) {
        free(slots);
        MapGenLayout_Free(l);
        return MAPGEN_LAYOUT_ERR_MEMORY;
    }
    l->rooms = calloc(nodes, sizeof(*l->rooms));
    if (!l->rooms) {
        free(slots);
        MapGenLayout_Free(l);
        return MAPGEN_LAYOUT_ERR_MEMORY;
    }
    l->num_rooms = nodes;

    /*
     * Cells first, from a walk of the skeleton.
     *
     * The walk is over the graph as given, in index order, which is the order
     * the skeleton built it: node i was attached to some earlier node, so
     * every node has a placed parent by the time it is reached. That is a
     * property of how the topology is built, and the guard checks it rather
     * than assuming it.
     */
    slots[0].cell[0] = 0;
    slots[0].cell[1] = 0;
    slots[0].placed = true;

    for (uint32_t i = 1; i < nodes; i++) {
        /* The earlier node this one is joined to. */
        uint32_t parent = UINT32_MAX;
        for (uint32_t r = 0; r < MapGenTopology_NumRoutes(topology)
                             && parent == UINT32_MAX; r++) {
            const mapgen_topology_route_t *route = MapGenTopology_Route(topology, r);
            if (route->to == i && route->from < i)
                parent = route->from;
            else if (route->from == i && route->to < i)
                parent = route->to;
        }
        if (parent == UINT32_MAX || !slots[parent].placed) {
            free(slots);
            MapGenLayout_Free(l);
            return MAPGEN_LAYOUT_ERR_NO_ROOM_TO_PLACE;
        }

        /*
         * A free cell touching the parent's, preferring the one nearest the
         * origin. Walking outward from the parent instead sends a chain of
         * rooms off in one direction and straight out of the world.
         */
        uint32_t order[4] = { 0, 1, 2, 3 };
        MapGenRandom_Shuffle(&rng, order, 4, sizeof(order[0]));

        bool placed = false;
        int32_t best_x = 0, best_y = 0;
        int64_t best_distance = INT64_MAX;
        /*
         * Touching the parent when there is room, and a ring or two further
         * out when there is not: a node with four children and a parent has
         * no free neighbour at all, and refusing the whole embedding for that
         * threw away more than half of every attempt.
         */
        for (int32_t ring = 1; ring <= 3 && !placed; ring++) {
            for (int32_t dy = -ring; dy <= ring; dy++) {
                for (int32_t dx = -ring; dx <= ring; dx++) {
                    if ((dx > -ring && dx < ring) && (dy > -ring && dy < ring))
                        continue;               /* already tried, inner ring */
                    const int32_t cx = slots[parent].cell[0] + dx;
                    const int32_t cy = slots[parent].cell[1] + dy;
                    if (cell_taken(slots, nodes, cx, cy))
                        continue;
                    if (!cell_in_world(cx, cy))
                        continue;
                    /* Nearest the origin, with the drawn order breaking ties
                       so the shape is not always the same corner. */
                    const int64_t distance = (int64_t)cx * cx + (int64_t)cy * cy
                                           + (int64_t)order[((uint32_t)(dx + dy)) & 3u];
                    if (distance < best_distance) {
                        best_distance = distance;
                        best_x = cx;
                        best_y = cy;
                        placed = true;
                    }
                }
            }
        }
        if (placed) {
            slots[i].cell[0] = best_x;
            slots[i].cell[1] = best_y;
            slots[i].placed = true;
        }
        if (!placed) {
            free(slots);
            MapGenLayout_Free(l);
            return MAPGEN_LAYOUT_ERR_NO_ROOM_TO_PLACE;
        }
    }

    /* --- rooms ------------------------------------------------------------ */
    l->bounds.mins[0] = l->bounds.mins[1] = l->bounds.mins[2] = INT32_MAX;
    l->bounds.maxs[0] = l->bounds.maxs[1] = l->bounds.maxs[2] = INT32_MIN;

    for (uint32_t i = 0; i < nodes; i++) {
        const mapgen_topology_node_t *n = MapGenTopology_Node(topology, i);

        /*
         * The room's footprint follows the share of the map the learned
         * sample gave this region, between the floor and the ceiling of what
         * fits in a cell.
         */
        /*
         * Outdoors first, because a courtyard is a SIZE as well as a ceiling.
         *
         * MEASURED on the invented map the PO walked: raising the share of
         * rooms that are open from 80 to 650 permille moved the share of the
         * FLOOR under sky from 80 permille to 99, because six rooms and eight
         * corridors means the corridors hold most of the floor and a corridor
         * is never outdoors. An outdoor room that is also the biggest room in
         * the map is what "много неба над головой" actually means.
         */
        const bool outdoor = sky_material_learned
                           && (int64_t)MapGenRandom_Below(&rng, 1000)
                              < sky_rooms_permille;

        const int32_t span = MAPGEN_LAYOUT_MAX_ROOM - MAPGEN_LAYOUT_MIN_ROOM;
        int32_t size = MAPGEN_LAYOUT_MIN_ROOM
                     + (int32_t)((int64_t)span * n->size_permille / 1000);
        if (outdoor)
            size = MAPGEN_LAYOUT_MAX_ROOM;
        size = snap(size);
        if (size < MAPGEN_LAYOUT_MIN_ROOM)
            size = MAPGEN_LAYOUT_MIN_ROOM;
        if (size > MAPGEN_LAYOUT_MAX_ROOM)
            size = MAPGEN_LAYOUT_MAX_ROOM;

        /* A little variation in the other axis, so rooms are not all square.
           A courtyard keeps its size on both. */
        int32_t depth = outdoor ? size
                                : snap(size + MapGenRandom_Range(&rng, -128, 128));
        if (depth < MAPGEN_LAYOUT_MIN_ROOM)
            depth = MAPGEN_LAYOUT_MIN_ROOM;
        if (depth > MAPGEN_LAYOUT_MAX_ROOM)
            depth = MAPGEN_LAYOUT_MAX_ROOM;

        /*
         * Height, and whether the room is open to the sky.
         *
         * A third of the rooms are halls rather than chambers, because a map
         * built to one ceiling height reads as a corridor system whatever its
         * floor plan says. The outdoor ones follow the learned sky share.
         */
        const bool tall = outdoor || MapGenRandom_Below(&rng, 3) == 0;

        int32_t height;
        if (outdoor)
            /* A parapet, and a little variety in it, but never so high that
               the yard becomes a shaft again: see the header. */
            height = snap(MAPGEN_LAYOUT_SKY_ROOM_HEIGHT
                          + MapGenRandom_Range(&rng, -32, 96));
        else if (tall)
            height = snap(MAPGEN_LAYOUT_TALL_ROOM_HEIGHT
                          + MapGenRandom_Range(&rng, -128, 256));
        else
            height = snap(MAPGEN_LAYOUT_MIN_ROOM_HEIGHT
                          + MapGenRandom_Range(&rng, 0, 256));
        if (height < MAPGEN_LAYOUT_MIN_ROOM_HEIGHT)
            height = MAPGEN_LAYOUT_MIN_ROOM_HEIGHT;

        const int32_t centre_x = slots[i].cell[0] * MAPGEN_LAYOUT_CELL;
        const int32_t centre_y = slots[i].cell[1] * MAPGEN_LAYOUT_CELL;
        const int32_t floor_z = (int32_t)n->band * MAPGEN_LAYOUT_BAND_HEIGHT;

        mapgen_layout_room_t *room = &l->rooms[i];
        room->node = i;
        room->cell[0] = slots[i].cell[0];
        room->cell[1] = slots[i].cell[1];
        room->space.mins[0] = snap(centre_x - size / 2);
        room->space.maxs[0] = room->space.mins[0] + size;
        room->space.mins[1] = snap(centre_y - depth / 2);
        room->space.maxs[1] = room->space.mins[1] + depth;
        room->space.mins[2] = floor_z;
        room->space.maxs[2] = floor_z + height;
        room->outdoor = outdoor;

        if (!inside_world(&room->space)) {
            free(slots);
            MapGenLayout_Free(l);
            return MAPGEN_LAYOUT_ERR_OUT_OF_WORLD;
        }
        box_grow(&l->bounds, &room->space);
    }
    free(slots);

    /* Two rooms sharing a cell would be a placement bug, not a map. */
    for (uint32_t i = 0; i < nodes; i++) {
        for (uint32_t j = 0; j < i; j++) {
            if (boxes_overlap(&l->rooms[i].space, &l->rooms[j].space)) {
                MapGenLayout_Free(l);
                return MAPGEN_LAYOUT_ERR_INTERSECTION;
            }
        }
    }

    /* --- passages --------------------------------------------------------- */
    const uint32_t routes = MapGenTopology_NumRoutes(topology);
    if (routes) {
        l->passages = calloc(routes, sizeof(*l->passages));
        if (!l->passages) {
            MapGenLayout_Free(l);
            return MAPGEN_LAYOUT_ERR_MEMORY;
        }
    }

    for (uint32_t r = 0; r < routes; r++) {
        const mapgen_topology_route_t *route = MapGenTopology_Route(topology, r);
        const mapgen_layout_room_t *from = &l->rooms[route->from];
        const mapgen_layout_room_t *to = &l->rooms[route->to];

        /*
         * Four segments, and never a step off a lane:
         *
         *   1. out of the first room to its own cell's boundary,
         *   2. along that boundary, in x,
         *   3. along the second room's column boundary, in y,
         *   4. off that boundary into the second room.
         *
         * Legs 2 and 3 run where no room can reach: a room is at most
         * MAPGEN_LAYOUT_MAX_ROOM wide inside a MAPGEN_LAYOUT_CELL-wide cell,
         * so the boundary is clear of every room by more than half a corridor.
         * Legs 1 and 4 never leave their own room's cell. A passage therefore
         * cannot cross a room it does not connect - by construction, not by
         * luck, which is what the three-segment version was relying on.
         */
        const int32_t from_x = (from->space.mins[0] + from->space.maxs[0]) / 2;
        const int32_t from_y = (from->space.mins[1] + from->space.maxs[1]) / 2;
        const int32_t to_x = (to->space.mins[0] + to->space.maxs[0]) / 2;
        const int32_t to_y = (to->space.mins[1] + to->space.maxs[1]) / 2;

        /* The boundary of the first room's cell, on the side facing the
           second - or simply the near side when they share a row. */
        const int32_t lane_y = from->cell[1] * MAPGEN_LAYOUT_CELL
            + ((to->cell[1] >= from->cell[1]) ? MAPGEN_LAYOUT_CELL / 2
                                              : -MAPGEN_LAYOUT_CELL / 2);
        const int32_t lane_x = to->cell[0] * MAPGEN_LAYOUT_CELL
            + ((from->cell[0] >= to->cell[0]) ? MAPGEN_LAYOUT_CELL / 2
                                              : -MAPGEN_LAYOUT_CELL / 2);

        const int32_t low_floor = from->space.mins[2] < to->space.mins[2]
                                ? from->space.mins[2] : to->space.mins[2];
        const int32_t high_floor = from->space.mins[2] > to->space.mins[2]
                                 ? from->space.mins[2] : to->space.mins[2];
        /*
         * How wide this connection is. A narrow one is a corridor; a wide one
         * is an opening between two rooms. `arch_corridors_vs_arenas` says how
         * often each: at None every connection is a tube, at High most of them
         * are openings.
         */
        static const uint32_t OPENING_CHANCE[5] = { 0, 200, 450, 650, 850 };
        const int32_t openness =
            MapGenRecipe_ResolvedValue(recipe, "arch_corridors_vs_arenas", 2);
        const uint32_t chance =
            OPENING_CHANCE[openness >= 0 && openness < 5 ? openness : 2];
        const bool opening = MapGenRandom_Below(&rng, 1000) < chance;

        const int32_t corridor_width = opening ? MAPGEN_LAYOUT_OPENING_WIDTH
                                               : MAPGEN_LAYOUT_CORRIDOR_WIDTH;
        const int32_t corridor_height = opening ? MAPGEN_LAYOUT_OPENING_HEIGHT
                                                : MAPGEN_LAYOUT_CORRIDOR_HEIGHT;
        const int32_t half = corridor_width / 2;

        mapgen_layout_passage_t *p = &l->passages[l->num_passages++];
        p->route = r;
        p->kind = route->kind;
        p->from_room = route->from;
        p->to_room = route->to;

        /* 1: out of the first room, in y, to its cell boundary. */
        {
            mapgen_layout_box_t seg;
            seg.mins[0] = snap(from_x - half);
            seg.maxs[0] = seg.mins[0] + corridor_width;
            seg.mins[1] = snap(lane_y < from_y ? lane_y - half : from_y - half);
            seg.maxs[1] = snap(lane_y < from_y ? from_y + half : lane_y + half);
            seg.mins[2] = from->space.mins[2];
            seg.maxs[2] = from->space.mins[2] + corridor_height;
            p->segments[p->num_segments++] = seg;
        }

        /* 2: along that boundary, in x, to the second room's column lane. */
        {
            mapgen_layout_box_t seg;
            seg.mins[0] = snap((from_x < lane_x ? from_x : lane_x) - half);
            seg.maxs[0] = snap((from_x < lane_x ? lane_x : from_x) + half);
            seg.mins[1] = snap(lane_y - half);
            seg.maxs[1] = seg.mins[1] + corridor_width;
            seg.mins[2] = from->space.mins[2];
            seg.maxs[2] = from->space.mins[2] + corridor_height;
            p->segments[p->num_segments++] = seg;
        }

        /*
         * 3: along the column lane, in y - and the leg that CLIMBS.
         *
         * A single box from the lower floor to the upper one is a shaft, and
         * the first version built exactly that: the plan said lift or ramp and
         * the geometry said hole. Nobody could climb it, so every band above
         * the ground was somewhere a player could only fall into and never
         * leave. This builds the flight instead - one box per step, each
         * MAPGEN_LAYOUT_STEP_RISE up and MAPGEN_LAYOUT_STEP_RUN along, which
         * is inside the engine's own STEPSIZE and so is walked rather than
         * jumped.
         */
        {
            const int32_t lo = snap((lane_y < to_y ? lane_y : to_y) - half);
            const int32_t hi = snap((lane_y < to_y ? to_y : lane_y) + half);
            const int32_t rise = high_floor - low_floor;
            const int32_t steps = rise > 0 ? rise / MAPGEN_LAYOUT_STEP_RISE : 0;

            /*
             * A climb that will not fit is a REFUSAL, not a shaft.
             *
             * Only a lift may be a shaft, because a lift has something in it
             * that climbs. For anything else, one box from the lower floor to
             * the upper one is a hole a player falls into and cannot leave -
             * which is what reached the product path and cost an invented map
             * four of its player starts.
             */
            if (steps > MAPGEN_LAYOUT_MAX_SEGMENTS - 4
                && p->kind != MAPGEN_ROUTE_LIFT) {
                MapGenLayout_Free(l);
                return MAPGEN_LAYOUT_ERR_TOO_STEEP;
            }
            if (steps <= 0 || steps > MAPGEN_LAYOUT_MAX_SEGMENTS - 4) {
                /* Flat, or a lift's shaft, which is one box by design. */
                mapgen_layout_box_t seg;
                seg.mins[0] = snap(lane_x - half);
                seg.maxs[0] = seg.mins[0] + corridor_width;
                seg.mins[1] = lo;
                seg.maxs[1] = hi;
                seg.mins[2] = low_floor;
                seg.maxs[2] = high_floor + corridor_height;
                p->segments[p->num_segments++] = seg;
            } else {
                /* The flight runs from whichever end is lower. */
                const bool up_in_y = from->space.mins[2] < to->space.mins[2]
                                   ? (lane_y < to_y) : (to_y < lane_y);
                const int32_t run = MAPGEN_LAYOUT_STEP_RUN;
                for (int32_t s = 0; s < steps; s++) {
                    mapgen_layout_box_t seg;
                    seg.mins[0] = snap(lane_x - half);
                    seg.maxs[0] = seg.mins[0] + corridor_width;
                    if (up_in_y) {
                        seg.mins[1] = lo + s * run;
                        seg.maxs[1] = (s + 1 == steps) ? hi : lo + (s + 1) * run;
                    } else {
                        seg.maxs[1] = hi - s * run;
                        seg.mins[1] = (s + 1 == steps) ? lo : hi - (s + 1) * run;
                    }
                    if (seg.maxs[1] <= seg.mins[1]) {
                        seg.mins[1] = lo;
                        seg.maxs[1] = hi;
                    }
                    /* Each tread stands one rise higher and is tall enough to
                       walk through with headroom. */
                    seg.mins[2] = low_floor + s * MAPGEN_LAYOUT_STEP_RISE;
                    seg.maxs[2] = seg.mins[2] + corridor_height
                                + MAPGEN_LAYOUT_STEP_RISE;
                    p->segments[p->num_segments++] = seg;
                }
            }
        }

        /* 4: off the lane, in x, into the second room. */
        {
            mapgen_layout_box_t seg;
            seg.mins[0] = snap((lane_x < to_x ? lane_x : to_x) - half);
            seg.maxs[0] = snap((lane_x < to_x ? to_x : lane_x) + half);
            seg.mins[1] = snap(to_y - half);
            seg.maxs[1] = seg.mins[1] + corridor_width;
            seg.mins[2] = to->space.mins[2];
            seg.maxs[2] = to->space.mins[2] + corridor_height;
            p->segments[p->num_segments++] = seg;
        }

        for (uint32_t s = 0; s < p->num_segments; s++) {
            if (!inside_world(&p->segments[s])) {
                MapGenLayout_Free(l);
                return MAPGEN_LAYOUT_ERR_OUT_OF_WORLD;
            }
            box_grow(&l->bounds, &p->segments[s]);
        }
    }

    /*
     * A passage may enter the two rooms it connects and no other. Lane routing
     * makes that true by construction; this is the proof, kept because a
     * construction argument nobody checks is an assumption.
     *
     * Two passages crossing each other is counted instead of refused: that is
     * a junction, it adds only walk adjacency, and forbidding it described no
     * real map while refusing almost every large one.
     */
    for (uint32_t p = 0; p < l->num_passages; p++) {
        for (uint32_t s = 0; s < l->passages[p].num_segments; s++) {
            for (uint32_t i = 0; i < l->num_rooms; i++) {
                if (i == l->passages[p].from_room || i == l->passages[p].to_room)
                    continue;
                if (boxes_overlap(&l->passages[p].segments[s], &l->rooms[i].space)) {
                    MapGenLayout_Free(l);
                    return MAPGEN_LAYOUT_ERR_INTERSECTION;
                }
            }
            for (uint32_t q = 0; q < p; q++) {
                /* Passages that share a room meet inside it by design; the
                   rest meeting anywhere is a junction, and counted. */
                const bool share_room =
                    l->passages[p].from_room == l->passages[q].from_room
                    || l->passages[p].from_room == l->passages[q].to_room
                    || l->passages[p].to_room == l->passages[q].from_room
                    || l->passages[p].to_room == l->passages[q].to_room;
                if (share_room)
                    continue;
                for (uint32_t t = 0; t < l->passages[q].num_segments; t++)
                    if (boxes_overlap(&l->passages[p].segments[s],
                                      &l->passages[q].segments[t]))
                        l->num_junctions++;
            }
        }
        /* And it has to actually reach both ends. */
        if (!connects(topology, l->passages[p].route,
                      l->passages[p].from_room, l->passages[p].to_room)) {
            MapGenLayout_Free(l);
            return MAPGEN_LAYOUT_ERR_INTERSECTION;
        }
    }

    /* The rooms are final now, so the pools can be sunk into them. */
    place_pools(l, model, recipe, &rng);

    *out = l;
    return MAPGEN_LAYOUT_OK;
}

mapgen_layout_result_t MapGenLayout_FromBlueprint(const mapgen_blueprint_t *bp,
                                                  const mapgen_recipe_t *recipe,
                                                  mapgen_layout_t **out)
{
    if (out)
        *out = NULL;
    if (!bp || !recipe || !out)
        return MAPGEN_LAYOUT_ERR_ARGS;

    const uint32_t volumes = MapGenBlueprint_NumVolumes(bp);
    if (!volumes)
        return MAPGEN_LAYOUT_ERR_NO_NODES;

    mapgen_layout_t *l = calloc(1, sizeof(*l));
    if (!l)
        return MAPGEN_LAYOUT_ERR_MEMORY;
    l->rooms = calloc(volumes, sizeof(*l->rooms));
    l->passages = calloc(MapGenBlueprint_NumPortals(bp) + 1,
                         sizeof(*l->passages));
    if (!l->rooms || !l->passages) {
        MapGenLayout_Free(l);
        return MAPGEN_LAYOUT_ERR_MEMORY;
    }

    l->bounds.mins[0] = l->bounds.mins[1] = l->bounds.mins[2] = INT32_MAX;
    l->bounds.maxs[0] = l->bounds.maxs[1] = l->bounds.maxs[2] = INT32_MIN;

    /*
     * The rooms are the volumes, at their own coordinates. Two of them may
     * overlap in XY at different heights, which the grid path cannot express
     * and which is exactly how a real map is compact.
     */
    for (uint32_t v = 0; v < volumes; v++) {
        const mapgen_blueprint_volume_t *vol = MapGenBlueprint_Volume(bp, v);
        mapgen_layout_room_t *room = &l->rooms[l->num_rooms++];
        room->node = v;
        room->space.mins[0] = vol->mins[0];
        room->space.mins[1] = vol->mins[1];
        room->space.mins[2] = vol->mins[2];
        room->space.maxs[0] = vol->maxs[0];
        room->space.maxs[1] = vol->maxs[1];
        /*
         * Headroom comes from the volume's own measured ceiling, floored at
         * what a player needs to stand: a donor volume one basis cell tall is
         * a ledge in the source and has to be a place you can stand here.
         */
        int32_t top = vol->ceiling > vol->mins[2] + MAPGEN_LAYOUT_CORRIDOR_HEIGHT
                    ? vol->ceiling
                    : vol->mins[2] + MAPGEN_LAYOUT_CORRIDOR_HEIGHT;
        if (top > vol->maxs[2])
            room->space.maxs[2] = top;
        else
            room->space.maxs[2] = vol->maxs[2];
        room->outdoor = (vol->flags & MAPGEN_VOLUME_SKY) != 0;
        if (!inside_world(&room->space)) {
            MapGenLayout_Free(l);
            return MAPGEN_LAYOUT_ERR_OUT_OF_WORLD;
        }
        box_grow(&l->bounds, &room->space);
    }

    /*
     * The passages are the portals: one connector joining the two volumes the
     * portal joins, at the height it says. A portal whose volumes already
     * touch needs no geometry - the opening is what is left where two empty
     * volumes meet - so it contributes a zero-segment passage and stays in the
     * record as the connection it is.
     */
    for (uint32_t p = 0; p < MapGenBlueprint_NumPortals(bp); p++) {
        const mapgen_blueprint_portal_t *portal = MapGenBlueprint_Portal(bp, p);
        if (portal->from >= l->num_rooms || portal->to >= l->num_rooms)
            continue;
        const mapgen_layout_box_t *a = &l->rooms[portal->from].space;
        const mapgen_layout_box_t *b = &l->rooms[portal->to].space;

        mapgen_layout_passage_t *pass = &l->passages[l->num_passages++];
        pass->route = p;
        pass->kind = portal->kind;
        pass->from_room = portal->from;
        pass->to_room = portal->to;

        const bool touching =
            a->mins[0] < b->maxs[0] && a->maxs[0] > b->mins[0]
            && a->mins[1] < b->maxs[1] && a->maxs[1] > b->mins[1];
        if (touching)
            continue;               /* the opening already exists */

        mapgen_layout_box_t seg;
        for (int axis = 0; axis < 2; axis++) {
            const int32_t lo = a->mins[axis] < b->mins[axis]
                             ? a->maxs[axis] : b->maxs[axis];
            const int32_t hi = a->mins[axis] < b->mins[axis]
                             ? b->mins[axis] : a->mins[axis];
            if (lo < hi) {
                seg.mins[axis] = lo;
                seg.maxs[axis] = hi;
            } else {
                const int32_t centre =
                    ((a->mins[axis] + a->maxs[axis])
                     + (b->mins[axis] + b->maxs[axis])) / 4;
                seg.mins[axis] = centre - MAPGEN_LAYOUT_CORRIDOR_WIDTH / 2;
                seg.maxs[axis] = centre + MAPGEN_LAYOUT_CORRIDOR_WIDTH / 2;
            }
        }
        const int32_t floor = a->mins[2] < b->mins[2] ? a->mins[2] : b->mins[2];
        const int32_t rise = a->mins[2] < b->mins[2]
                           ? b->mins[2] - a->mins[2] : a->mins[2] - b->mins[2];
        seg.mins[2] = floor;
        seg.maxs[2] = floor + rise + MAPGEN_LAYOUT_CORRIDOR_HEIGHT;
        pass->segments[pass->num_segments++] = seg;
        box_grow(&l->bounds, &seg);
    }

    place_pools(l, NULL, recipe, NULL);
    *out = l;
    return MAPGEN_LAYOUT_OK;
}

void MapGenLayout_Free(mapgen_layout_t *l)
{
    if (!l)
        return;
    free(l->rooms);
    free(l->passages);
    free(l);
}

/* ---- accessors ----------------------------------------------------------- */

uint32_t MapGenLayout_NumRooms(const mapgen_layout_t *l)
{
    return l ? l->num_rooms : 0;
}

uint32_t MapGenLayout_NumPassages(const mapgen_layout_t *l)
{
    return l ? l->num_passages : 0;
}

const mapgen_layout_room_t *MapGenLayout_Room(const mapgen_layout_t *l,
                                              uint32_t index)
{
    return (l && index < l->num_rooms) ? &l->rooms[index] : NULL;
}

const mapgen_layout_passage_t *MapGenLayout_Passage(const mapgen_layout_t *l,
                                                    uint32_t index)
{
    return (l && index < l->num_passages) ? &l->passages[index] : NULL;
}

const mapgen_layout_box_t *MapGenLayout_Bounds(const mapgen_layout_t *l)
{
    return l ? &l->bounds : NULL;
}

uint32_t MapGenLayout_NumPools(const mapgen_layout_t *l)
{
    return l ? l->num_pools : 0;
}

const mapgen_layout_pool_t *MapGenLayout_Pool(const mapgen_layout_t *l,
                                              uint32_t index)
{
    return (l && index < l->num_pools) ? &l->pools[index] : NULL;
}

uint32_t MapGenLayout_NumJunctions(const mapgen_layout_t *l)
{
    return l ? l->num_junctions : 0;
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

static void put_i32(sink_t *s, int32_t v)
{
    char buf[16], tmp[16];
    size_t n = 0, t = 0;
    uint32_t u = v < 0 ? (uint32_t)(-(int64_t)v) : (uint32_t)v;
    if (v < 0)
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

static void put_box(sink_t *s, const mapgen_layout_box_t *b)
{
    for (int axis = 0; axis < 3; axis++) {
        put_i32(s, b->mins[axis]);
        put(s, ",");
    }
    for (int axis = 0; axis < 3; axis++) {
        put_i32(s, b->maxs[axis]);
        if (axis < 2)
            put(s, ",");
    }
}

size_t MapGenLayout_CanonicalText(const mapgen_layout_t *l, char *out,
                                  size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!l) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    put(&s, "bounds=");
    put_box(&s, &l->bounds);
    put(&s, "\nrooms=");
    put_i32(&s, (int32_t)l->num_rooms);
    put(&s, "\n");
    for (uint32_t i = 0; i < l->num_rooms; i++) {
        put(&s, "r=");
        put_box(&s, &l->rooms[i].space);
        put(&s, "\n");
    }
    put(&s, "junctions=");
    put_i32(&s, (int32_t)l->num_junctions);
    put(&s, "\npassages=");
    put_i32(&s, (int32_t)l->num_passages);
    put(&s, "\n");
    for (uint32_t i = 0; i < l->num_passages; i++) {
        for (uint32_t s2 = 0; s2 < l->passages[i].num_segments; s2++) {
            put(&s, "p=");
            put_i32(&s, (int32_t)l->passages[i].from_room);
            put(&s, ",");
            put_i32(&s, (int32_t)l->passages[i].to_room);
            put(&s, ",");
            put(&s, MapGenTopology_RouteName(l->passages[i].kind));
            put(&s, ",");
            put_box(&s, &l->passages[i].segments[s2]);
            put(&s, "\n");
        }
    }

    put(&s, "pools=");
    put_i32(&s, (int32_t)l->num_pools);
    put(&s, "\n");
    for (uint32_t i = 0; i < l->num_pools; i++) {
        put(&s, "l=");
        put_i32(&s, (int32_t)l->pools[i].room);
        put(&s, ",");
        put_i32(&s, (int32_t)l->pools[i].role);
        put(&s, ",");
        put_box(&s, &l->pools[i].liquid);
        put(&s, "\n");
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenLayout_CanonicalDigest(const mapgen_layout_t *l)
{
    const size_t needed = MapGenLayout_CanonicalText(l, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenLayout_CanonicalText(l, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
