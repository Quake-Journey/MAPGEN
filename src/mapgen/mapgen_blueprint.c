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
 * MAPGEN-1 - extracting a map's architecture from its compiled truth.
 *
 * The segmentation, stated once and implemented twice - here and in
 * `tools/mapgen_blueprint_oracle.py`, which shares no code with this file:
 *
 *   1. a stance's WALK degree tells open space from a passage. A corridor is
 *      thin; a hall is not;
 *   2. the hall class is dilated by one step, because a stance beside a wall
 *      loses half its neighbours and would otherwise ring every hall with
 *      "passage" stances - on q2dm1 that produced 459 slivers;
 *   3. a volume is a connected component of ONE class over walk and step
 *      edges, so a hall and the corridor leaving it stay two volumes;
 *   4. a passage component touching only one other volume is a dead end, not
 *      a corridor: it is the edge of what it hangs off, and is absorbed;
 *   5. an edge between two volumes is a PORTAL carrying its kind, its signed
 *      rise, its aperture and the tightest headroom through it;
 *   6. relations - above, XY overlap, containment - are read off the bounds.
 *
 * Nothing here is the stance graph's `region`. That is a connected component
 * over walk/step/swim edges; q2dm1 has 81 of them and not one is a room.
 */

#include "common/mapgen_blueprint.h"

#include <stdlib.h>
#include <string.h>

const char *MapGenBlueprint_ResultName(mapgen_blueprint_result_t r)
{
    switch (r) {
    case MAPGEN_BLUEPRINT_OK:                     return "OK";
    case MAPGEN_BLUEPRINT_ERR_ARGS:               return "ERR_ARGS";
    case MAPGEN_BLUEPRINT_ERR_MEMORY:             return "ERR_MEMORY";
    case MAPGEN_BLUEPRINT_ERR_NO_SPACE:           return "ERR_NO_SPACE";
    case MAPGEN_BLUEPRINT_ERR_TOO_MANY_VOLUMES:   return "ERR_TOO_MANY_VOLUMES";
    case MAPGEN_BLUEPRINT_ERR_TOO_MANY_PORTALS:   return "ERR_TOO_MANY_PORTALS";
    case MAPGEN_BLUEPRINT_ERR_TOO_MANY_RELATIONS: return "ERR_TOO_MANY_RELATIONS";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenBlueprint_ClassName(mapgen_volume_class_t c)
{
    switch (c) {
    case MAPGEN_VOLUME_HALL:        return "hall";
    case MAPGEN_VOLUME_PASSAGE:     return "passage";
    case MAPGEN_VOLUME_CLASS_COUNT: break;
    }
    return "unknown";
}

const char *MapGenBlueprint_RelationName(mapgen_relation_kind_t r)
{
    switch (r) {
    case MAPGEN_RELATION_ABOVE:      return "above";
    case MAPGEN_RELATION_OVERLAP_XY: return "overlap_xy";
    case MAPGEN_RELATION_CONTAINS:   return "contains";
    case MAPGEN_RELATION_ADJACENT:   return "adjacent";
    case MAPGEN_RELATION_COUNT:      break;
    }
    return "unknown";
}

struct mapgen_blueprint_s {
    mapgen_blueprint_volume_t   *volumes;
    uint32_t                     num_volumes;
    mapgen_blueprint_portal_t   *portals;
    uint32_t                     num_portals;
    mapgen_blueprint_relation_t *relations;
    uint32_t                     num_relations;
};

/* ---- the basis ----------------------------------------------------------- */

static int32_t snap_down(int32_t v)
{
    const int32_t b = MAPGEN_BLUEPRINT_BASIS;
    return v >= 0 ? (v / b) * b : -(((-v) + b - 1) / b) * b;
}

/* ---- segmentation -------------------------------------------------------- */

static bool joins(uint8_t kind)
{
    /* What makes one continuous piece of floor. A jump or a drop reaches
       another volume; it does not merge two into one. */
    return kind == MAPGEN_EDGE_WALK || kind == MAPGEN_EDGE_STEP;
}

static bool one_way_kind(uint8_t kind)
{
    return kind == MAPGEN_EDGE_JUMP || kind == MAPGEN_EDGE_FALL;
}

/*
 * Fold single-neighbour passage components into what they hang off.
 *
 * A corridor connects two volumes; a component touching one is the edge of
 * that one. Lowest id first and one absorption per sweep, so the outcome
 * cannot depend on iteration order.
 */
static void absorb_dead_ends(const mapgen_space_t *space,
                             const uint8_t *volume_class,
                             uint32_t *owner, uint32_t nodes, uint32_t count)
{
    uint32_t *first_touch = malloc((size_t)count * sizeof(uint32_t));
    uint32_t *touches = malloc((size_t)count * sizeof(uint32_t));
    uint8_t  *is_passage = calloc(count, 1);
    if (!first_touch || !touches || !is_passage) {
        free(first_touch);
        free(touches);
        free(is_passage);
        return;
    }

    for (bool changed = true; changed; ) {
        changed = false;
        for (uint32_t v = 0; v < count; v++) {
            first_touch[v] = UINT32_MAX;
            touches[v] = 0;
            is_passage[v] = 0;
        }
        /*
         * The class belongs to the VOLUME, not to its stances: after an
         * absorption a volume's stances no longer share one, and asking them
         * makes the answer depend on which stance is asked.
         */
        for (uint32_t i = 0; i < nodes; i++)
            if (volume_class[owner[i]] == MAPGEN_VOLUME_PASSAGE)
                is_passage[owner[i]] = 1;

        for (uint32_t e = 0; e < MapGenSpace_NumEdges(space); e++) {
            const mapgen_space_edge_t *edge = MapGenSpace_Edge(space, e);
            const uint32_t a = owner[edge->from], b = owner[edge->to];
            if (a == b)
                continue;
            /* Only the first distinct neighbour is remembered; a second
               distinct one is all this needs to know. */
            if (first_touch[a] == UINT32_MAX) {
                first_touch[a] = b;
                touches[a] = 1;
            } else if (first_touch[a] != b && touches[a] < 2) {
                touches[a] = 2;
            }
            if (first_touch[b] == UINT32_MAX) {
                first_touch[b] = a;
                touches[b] = 1;
            } else if (first_touch[b] != a && touches[b] < 2) {
                touches[b] = 2;
            }
        }

        for (uint32_t v = 0; v < count && !changed; v++) {
            if (!is_passage[v] || touches[v] != 1)
                continue;
            const uint32_t into = first_touch[v];
            for (uint32_t i = 0; i < nodes; i++)
                if (owner[i] == v)
                    owner[i] = into;
            changed = true;
        }
    }

    free(first_touch);
    free(touches);
    free(is_passage);
}

mapgen_blueprint_result_t MapGenBlueprint_Build(const mapgen_bsp_t *bsp,
                                                const mapgen_genome_t *genome,
                                                const mapgen_space_t *space,
                                                mapgen_blueprint_t **out)
{
    if (out)
        *out = NULL;
    if (!bsp || !genome || !space || !out)
        return MAPGEN_BLUEPRINT_ERR_ARGS;

    const uint32_t nodes = MapGenSpace_NumNodes(space);
    const uint32_t edges = MapGenSpace_NumEdges(space);
    if (!nodes)
        return MAPGEN_BLUEPRINT_ERR_NO_SPACE;

    uint32_t *degree = calloc(nodes, sizeof(uint32_t));
    uint8_t  *klass = calloc(nodes, 1);
    uint8_t  *grown = calloc(nodes, 1);
    uint32_t *owner = malloc((size_t)nodes * sizeof(uint32_t));
    uint32_t *stack = malloc((size_t)nodes * sizeof(uint32_t));
    if (!degree || !klass || !grown || !owner || !stack) {
        free(degree); free(klass); free(grown); free(owner); free(stack);
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    }

    for (uint32_t e = 0; e < edges; e++) {
        const mapgen_space_edge_t *edge = MapGenSpace_Edge(space, e);
        if (edge->kind == MAPGEN_EDGE_WALK) {
            degree[edge->from]++;
            degree[edge->to]++;
        }
    }
    for (uint32_t i = 0; i < nodes; i++)
        klass[i] = degree[i] <= MAPGEN_BLUEPRINT_THIN_DEGREE
                 ? MAPGEN_VOLUME_PASSAGE : MAPGEN_VOLUME_HALL;

    /* Dilate the hall class by one walk step: a stance beside a wall is not a
       corridor, it is the edge of the room. */
    memcpy(grown, klass, nodes);
    for (uint32_t e = 0; e < edges; e++) {
        const mapgen_space_edge_t *edge = MapGenSpace_Edge(space, e);
        if (edge->kind != MAPGEN_EDGE_WALK)
            continue;
        if (klass[edge->from] == MAPGEN_VOLUME_HALL)
            grown[edge->to] = MAPGEN_VOLUME_HALL;
        if (klass[edge->to] == MAPGEN_VOLUME_HALL)
            grown[edge->from] = MAPGEN_VOLUME_HALL;
    }
    memcpy(klass, grown, nodes);

    /* Components within one class, seeded in node order. */
    for (uint32_t i = 0; i < nodes; i++)
        owner[i] = UINT32_MAX;
    uint32_t count = 0;
    for (uint32_t start = 0; start < nodes; start++) {
        if (owner[start] != UINT32_MAX)
            continue;
        size_t top = 0;
        owner[start] = count;
        stack[top++] = start;
        while (top) {
            const uint32_t at = stack[--top];
            for (uint32_t e = 0; e < edges; e++) {
                const mapgen_space_edge_t *edge = MapGenSpace_Edge(space, e);
                if (!joins(edge->kind))
                    continue;
                uint32_t next = UINT32_MAX;
                if (edge->from == at)
                    next = edge->to;
                else if (edge->to == at)
                    next = edge->from;
                if (next == UINT32_MAX || owner[next] != UINT32_MAX)
                    continue;
                if (klass[next] != klass[at])
                    continue;
                owner[next] = count;
                stack[top++] = next;
            }
        }
        count++;
    }

    /* One class per volume, taken when the component was formed. */
    uint8_t *volume_class = malloc(count ? count : 1);
    if (!volume_class) {
        free(degree); free(klass); free(grown); free(owner); free(stack);
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    }
    memset(volume_class, 0xFF, count ? count : 1);
    for (uint32_t i = 0; i < nodes; i++)
        if (volume_class[owner[i]] == 0xFF)
            volume_class[owner[i]] = klass[i];

    absorb_dead_ends(space, volume_class, owner, nodes, count);

    /* Renumber to a dense, deterministic id space. */
    uint32_t *remap = malloc((size_t)count * sizeof(uint32_t));
    if (!remap) {
        free(degree); free(klass); free(grown); free(owner); free(stack);
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    }
    for (uint32_t v = 0; v < count; v++)
        remap[v] = UINT32_MAX;
    uint32_t dense = 0;
    for (uint32_t i = 0; i < nodes; i++)
        if (remap[owner[i]] == UINT32_MAX)
            remap[owner[i]] = dense++;
    uint8_t *dense_class = malloc(dense ? dense : 1);
    if (!dense_class) {
        free(remap); free(volume_class);
        free(degree); free(klass); free(grown); free(owner); free(stack);
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    }
    for (uint32_t v = 0; v < count; v++)
        if (remap[v] != UINT32_MAX)
            dense_class[remap[v]] = volume_class[v];
    for (uint32_t i = 0; i < nodes; i++)
        owner[i] = remap[owner[i]];
    free(remap);
    free(volume_class);
    volume_class = dense_class;
    count = dense;

    if (count > MAPGEN_BLUEPRINT_MAX_VOLUMES) {
        free(degree); free(klass); free(grown); free(owner); free(stack);
        return MAPGEN_BLUEPRINT_ERR_TOO_MANY_VOLUMES;
    }

    mapgen_blueprint_t *bp = calloc(1, sizeof(*bp));
    if (!bp) {
        free(degree); free(klass); free(grown); free(owner); free(stack);
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    }
    bp->volumes = calloc(count ? count : 1, sizeof(*bp->volumes));
    if (!bp->volumes) {
        free(degree); free(klass); free(grown); free(owner); free(stack);
        MapGenBlueprint_Free(bp);
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    }
    bp->num_volumes = count;

    /* --- the volumes ------------------------------------------------------ */
    uint16_t *clearances = malloc((size_t)nodes * sizeof(uint16_t));
    if (!clearances) {
        free(degree); free(klass); free(grown); free(owner); free(stack);
        MapGenBlueprint_Free(bp);
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    }

    for (uint32_t v = 0; v < count; v++) {
        mapgen_blueprint_volume_t *vol = &bp->volumes[v];
        vol->id = v;
        vol->mins[0] = vol->mins[1] = vol->mins[2] = INT32_MAX;
        vol->maxs[0] = vol->maxs[1] = vol->maxs[2] = INT32_MIN;

        uint32_t members = 0, ducked = 0, samples = 0;
        for (uint32_t i = 0; i < nodes; i++) {
            if (owner[i] != v)
                continue;
            const mapgen_space_node_t *n = MapGenSpace_Node(space, i);
            if (!members)
                vol->klass = volume_class[v];
            members++;
            for (int axis = 0; axis < 3; axis++) {
                const int32_t at = (int32_t)n->origin[axis];
                if (at < vol->mins[axis]) vol->mins[axis] = at;
                if (at > vol->maxs[axis]) vol->maxs[axis] = at;
            }
            if (n->flags & MAPGEN_SPACE_NODE_LIQUID) vol->flags |= MAPGEN_VOLUME_LIQUID;
            if (n->flags & MAPGEN_SPACE_NODE_HAZARD) vol->flags |= MAPGEN_VOLUME_HAZARD;
            if (n->flags & MAPGEN_SPACE_NODE_DUCKED) ducked++;
            clearances[samples++] = n->clearance;
        }
        if (!members)
            continue;

        for (int axis = 0; axis < 3; axis++) {
            vol->mins[axis] = snap_down(vol->mins[axis]);
            vol->maxs[axis] = snap_down(vol->maxs[axis]) + MAPGEN_BLUEPRINT_BASIS;
        }
        if (ducked == members)
            vol->flags |= MAPGEN_VOLUME_DUCKED;

        /* Insertion sort: one volume's stances, and the median is what a
           mean cannot give on a distribution with a hard cap in it. */
        for (uint32_t i = 1; i < samples; i++) {
            const uint16_t c = clearances[i];
            uint32_t j = i;
            while (j && clearances[j - 1] > c) {
                clearances[j] = clearances[j - 1];
                j--;
            }
            clearances[j] = c;
        }
        const uint16_t median = clearances[samples / 2];
        vol->floor = vol->mins[2];
        vol->ceiling = vol->mins[2] + median;
        if (median >= 512)
            vol->flags |= MAPGEN_VOLUME_SKY;

        vol->stances = members;
        const int64_t footprint =
            (int64_t)((vol->maxs[0] - vol->mins[0]) / MAPGEN_BLUEPRINT_BASIS)
            * ((vol->maxs[1] - vol->mins[1]) / MAPGEN_BLUEPRINT_BASIS);
        int64_t occupancy = footprint ? (int64_t)members * 1000 / footprint : 0;
        if (occupancy > 1000)
            occupancy = 1000;
        vol->occupancy_permille = (uint32_t)occupancy;
        vol->landmark_weight = (uint32_t)((int64_t)members * occupancy / 1000);
    }
    free(clearances);

    /* --- the portals ------------------------------------------------------ */
    for (uint32_t e = 0; e < edges; e++) {
        const mapgen_space_edge_t *edge = MapGenSpace_Edge(space, e);
        const uint32_t a = owner[edge->from], b = owner[edge->to];
        if (a == b)
            continue;
        const mapgen_space_node_t *na = MapGenSpace_Node(space, edge->from);
        const mapgen_space_node_t *nb = MapGenSpace_Node(space, edge->to);
        const uint16_t clearance = na->clearance < nb->clearance
                                 ? na->clearance : nb->clearance;

        mapgen_blueprint_portal_t *found = NULL;
        for (uint32_t p = 0; p < bp->num_portals; p++) {
            if (bp->portals[p].from == a && bp->portals[p].to == b
                && bp->portals[p].kind == edge->kind) {
                found = &bp->portals[p];
                break;
            }
        }
        if (found) {
            found->aperture++;
            if (clearance < found->clearance)
                found->clearance = clearance;
            continue;
        }
        if (bp->num_portals >= MAPGEN_BLUEPRINT_MAX_PORTALS) {
            free(degree); free(klass); free(grown); free(owner); free(stack);
            MapGenBlueprint_Free(bp);
            return MAPGEN_BLUEPRINT_ERR_TOO_MANY_PORTALS;
        }
        void *bigger = realloc(bp->portals,
                               (size_t)(bp->num_portals + 1) * sizeof(*bp->portals));
        if (!bigger) {
            free(degree); free(klass); free(grown); free(owner); free(stack);
            MapGenBlueprint_Free(bp);
            return MAPGEN_BLUEPRINT_ERR_MEMORY;
        }
        bp->portals = bigger;
        mapgen_blueprint_portal_t *portal = &bp->portals[bp->num_portals++];
        portal->from = a;
        portal->to = b;
        portal->kind = edge->kind;
        portal->one_way = one_way_kind(edge->kind);
        portal->rise = edge->rise;
        portal->aperture = 1;
        portal->clearance = clearance;
    }

    /*
     * Sorted by (from, to, kind), so the canonical form does not depend on the
     * order the stance graph happened to hand out its edges. Insertion sort:
     * a map has portals in the thousands, and this runs once.
     */
    for (uint32_t i = 1; i < bp->num_portals; i++) {
        const mapgen_blueprint_portal_t key = bp->portals[i];
        uint32_t j = i;
        while (j) {
            const mapgen_blueprint_portal_t *prev = &bp->portals[j - 1];
            const bool after = prev->from > key.from
                            || (prev->from == key.from && prev->to > key.to)
                            || (prev->from == key.from && prev->to == key.to
                                && prev->kind > key.kind);
            if (!after)
                break;
            bp->portals[j] = bp->portals[j - 1];
            j--;
        }
        bp->portals[j] = key;
    }

    /* --- the relations ---------------------------------------------------- */
    for (uint32_t i = 0; i < count; i++) {
        for (uint32_t j = i + 1; j < count; j++) {
            const mapgen_blueprint_volume_t *va = &bp->volumes[i];
            const mapgen_blueprint_volume_t *vb = &bp->volumes[j];
            const bool overlap_xy =
                va->mins[0] < vb->maxs[0] && va->maxs[0] > vb->mins[0]
                && va->mins[1] < vb->maxs[1] && va->maxs[1] > vb->mins[1];
            bool contains = true;
            for (int axis = 0; axis < 3; axis++)
                if (va->mins[axis] > vb->mins[axis] || va->maxs[axis] < vb->maxs[axis])
                    contains = false;

            const struct { bool on; uint32_t a, b; uint8_t kind; } wanted[] = {
                { overlap_xy, va->id, vb->id, MAPGEN_RELATION_OVERLAP_XY },
                { overlap_xy && va->mins[2] >= vb->maxs[2], va->id, vb->id,
                  MAPGEN_RELATION_ABOVE },
                { overlap_xy && vb->mins[2] >= va->maxs[2], vb->id, va->id,
                  MAPGEN_RELATION_ABOVE },
                { contains, va->id, vb->id, MAPGEN_RELATION_CONTAINS },
            };
            for (size_t w = 0; w < sizeof(wanted) / sizeof(wanted[0]); w++) {
                if (!wanted[w].on)
                    continue;
                if (bp->num_relations >= MAPGEN_BLUEPRINT_MAX_RELATIONS) {
                    free(degree); free(klass); free(grown); free(owner); free(stack);
                    MapGenBlueprint_Free(bp);
                    return MAPGEN_BLUEPRINT_ERR_TOO_MANY_RELATIONS;
                }
                void *bigger = realloc(bp->relations,
                                       (size_t)(bp->num_relations + 1)
                                       * sizeof(*bp->relations));
                if (!bigger) {
                    free(degree); free(klass); free(grown); free(owner); free(stack);
                    MapGenBlueprint_Free(bp);
                    return MAPGEN_BLUEPRINT_ERR_MEMORY;
                }
                bp->relations = bigger;
                mapgen_blueprint_relation_t *rel = &bp->relations[bp->num_relations++];
                rel->a = wanted[w].a;
                rel->b = wanted[w].b;
                rel->kind = wanted[w].kind;
            }
        }
    }

    /* Sorted by (kind, a, b), for the same reason the portals are: a
       canonical form must not depend on the order things were discovered in. */
    for (uint32_t i = 1; i < bp->num_relations; i++) {
        const mapgen_blueprint_relation_t key = bp->relations[i];
        uint32_t j = i;
        while (j) {
            const mapgen_blueprint_relation_t *prev = &bp->relations[j - 1];
            const bool after = prev->kind > key.kind
                            || (prev->kind == key.kind && prev->a > key.a)
                            || (prev->kind == key.kind && prev->a == key.a
                                && prev->b > key.b);
            if (!after)
                break;
            bp->relations[j] = bp->relations[j - 1];
            j--;
        }
        bp->relations[j] = key;
    }

    free(volume_class);
    free(degree);
    free(klass);
    free(grown);
    free(owner);
    free(stack);
    *out = bp;
    return MAPGEN_BLUEPRINT_OK;
}

mapgen_blueprint_result_t MapGenBlueprint_CreateEmpty(mapgen_blueprint_t **out)
{
    if (!out)
        return MAPGEN_BLUEPRINT_ERR_ARGS;
    *out = calloc(1, sizeof(**out));
    return *out ? MAPGEN_BLUEPRINT_OK : MAPGEN_BLUEPRINT_ERR_MEMORY;
}

mapgen_blueprint_result_t MapGenBlueprint_AddVolume(mapgen_blueprint_t *bp,
                                                    const mapgen_blueprint_volume_t *v)
{
    if (!bp || !v)
        return MAPGEN_BLUEPRINT_ERR_ARGS;
    if (bp->num_volumes >= MAPGEN_BLUEPRINT_MAX_VOLUMES)
        return MAPGEN_BLUEPRINT_ERR_TOO_MANY_VOLUMES;
    void *grown = realloc(bp->volumes,
                          (size_t)(bp->num_volumes + 1) * sizeof(*bp->volumes));
    if (!grown)
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    bp->volumes = grown;
    bp->volumes[bp->num_volumes] = *v;
    /* Dense ids, whatever the caller thought: an id that is not its own index
       is an id every later reference has to be careful about. */
    bp->volumes[bp->num_volumes].id = bp->num_volumes;
    bp->num_volumes++;
    return MAPGEN_BLUEPRINT_OK;
}

mapgen_blueprint_result_t MapGenBlueprint_AddPortal(mapgen_blueprint_t *bp,
                                                    const mapgen_blueprint_portal_t *p)
{
    if (!bp || !p)
        return MAPGEN_BLUEPRINT_ERR_ARGS;
    if (p->from >= bp->num_volumes || p->to >= bp->num_volumes
        || p->from == p->to)
        return MAPGEN_BLUEPRINT_ERR_ARGS;
    if (bp->num_portals >= MAPGEN_BLUEPRINT_MAX_PORTALS)
        return MAPGEN_BLUEPRINT_ERR_TOO_MANY_PORTALS;
    void *grown = realloc(bp->portals,
                          (size_t)(bp->num_portals + 1) * sizeof(*bp->portals));
    if (!grown)
        return MAPGEN_BLUEPRINT_ERR_MEMORY;
    bp->portals = grown;
    bp->portals[bp->num_portals++] = *p;
    return MAPGEN_BLUEPRINT_OK;
}

mapgen_blueprint_result_t MapGenBlueprint_DropPortal(mapgen_blueprint_t *bp,
                                                     uint32_t index)
{
    if (!bp || index >= bp->num_portals)
        return MAPGEN_BLUEPRINT_ERR_ARGS;
    memmove(&bp->portals[index], &bp->portals[index + 1],
            (size_t)(bp->num_portals - index - 1) * sizeof(*bp->portals));
    bp->num_portals--;
    return MAPGEN_BLUEPRINT_OK;
}

mapgen_blueprint_result_t MapGenBlueprint_ReshapeVolume(mapgen_blueprint_t *bp,
                                                        uint32_t index,
                                                        uint32_t shrink_permille)
{
    if (!bp || index >= bp->num_volumes || shrink_permille >= 1000)
        return MAPGEN_BLUEPRINT_ERR_ARGS;

    mapgen_blueprint_volume_t *vol = &bp->volumes[index];
    int32_t mins[2], maxs[2];

    for (int axis = 0; axis < 2; axis++) {
        const int32_t span = vol->maxs[axis] - vol->mins[axis];
        const int32_t trim = (int32_t)((int64_t)span * shrink_permille / 2000);
        mins[axis] = vol->mins[axis] + trim;
        maxs[axis] = vol->maxs[axis] - trim;
        if (maxs[axis] - mins[axis] < MAPGEN_BLUEPRINT_MIN_FOOTPRINT)
            return MAPGEN_BLUEPRINT_ERR_ARGS;
    }

    /* The stances go with the floor they were standing on. */
    const int64_t was = (int64_t)(vol->maxs[0] - vol->mins[0])
                      * (vol->maxs[1] - vol->mins[1]);
    const int64_t now = (int64_t)(maxs[0] - mins[0]) * (maxs[1] - mins[1]);
    if (was > 0)
        vol->stances = (uint32_t)((int64_t)vol->stances * now / was);

    for (int axis = 0; axis < 2; axis++) {
        vol->mins[axis] = mins[axis];
        vol->maxs[axis] = maxs[axis];
    }
    return MAPGEN_BLUEPRINT_OK;
}

mapgen_blueprint_result_t MapGenBlueprint_DropVolume(mapgen_blueprint_t *bp,
                                                     uint32_t index)
{
    if (!bp || index >= bp->num_volumes)
        return MAPGEN_BLUEPRINT_ERR_ARGS;

    /* Its portals go with it. Walked backwards so removing one does not move
       the next one out from under the loop. */
    for (uint32_t p = bp->num_portals; p--; ) {
        if (bp->portals[p].from == index || bp->portals[p].to == index)
            MapGenBlueprint_DropPortal(bp, p);
    }

    memmove(&bp->volumes[index], &bp->volumes[index + 1],
            (size_t)(bp->num_volumes - index - 1) * sizeof(*bp->volumes));
    bp->num_volumes--;

    /* Ids stay dense and every reference follows them down. */
    for (uint32_t v = index; v < bp->num_volumes; v++)
        bp->volumes[v].id = v;
    for (uint32_t p = 0; p < bp->num_portals; p++) {
        if (bp->portals[p].from > index)
            bp->portals[p].from--;
        if (bp->portals[p].to > index)
            bp->portals[p].to--;
    }
    for (uint32_t r = bp->num_relations; r--; ) {
        if (bp->relations[r].a == index || bp->relations[r].b == index) {
            memmove(&bp->relations[r], &bp->relations[r + 1],
                    (size_t)(bp->num_relations - r - 1) * sizeof(*bp->relations));
            bp->num_relations--;
            continue;
        }
        if (bp->relations[r].a > index)
            bp->relations[r].a--;
        if (bp->relations[r].b > index)
            bp->relations[r].b--;
    }
    return MAPGEN_BLUEPRINT_OK;
}

void MapGenBlueprint_Transform(const int32_t mins[3], const int32_t maxs[3],
                               uint32_t quarter_turns, bool mirror,
                               int32_t out_mins[3], int32_t out_maxs[3])
{
    if (!mins || !maxs || !out_mins || !out_maxs)
        return;

    /* Both corners go through the same map, then the box is re-ordered: a
       rotation swaps which corner is the minimum. */
    int32_t corner[2][3];
    for (int c = 0; c < 2; c++) {
        int32_t x = c ? maxs[0] : mins[0];
        int32_t y = c ? maxs[1] : mins[1];
        for (uint32_t turn = 0; turn < (quarter_turns & 3u); turn++) {
            const int32_t rotated_x = -y;
            y = x;
            x = rotated_x;
        }
        if (mirror)
            x = -x;
        corner[c][0] = x;
        corner[c][1] = y;
        corner[c][2] = c ? maxs[2] : mins[2];
    }

    for (int axis = 0; axis < 3; axis++) {
        out_mins[axis] = corner[0][axis] < corner[1][axis]
                       ? corner[0][axis] : corner[1][axis];
        out_maxs[axis] = corner[0][axis] < corner[1][axis]
                       ? corner[1][axis] : corner[0][axis];
    }
}

void MapGenBlueprint_Free(mapgen_blueprint_t *bp)
{
    if (!bp)
        return;
    free(bp->volumes);
    free(bp->portals);
    free(bp->relations);
    free(bp);
}

uint32_t MapGenBlueprint_NumVolumes(const mapgen_blueprint_t *bp)
{
    return bp ? bp->num_volumes : 0;
}

const mapgen_blueprint_volume_t *MapGenBlueprint_Volume(const mapgen_blueprint_t *bp,
                                                        uint32_t index)
{
    return (bp && index < bp->num_volumes) ? &bp->volumes[index] : NULL;
}

uint32_t MapGenBlueprint_NumPortals(const mapgen_blueprint_t *bp)
{
    return bp ? bp->num_portals : 0;
}

const mapgen_blueprint_portal_t *MapGenBlueprint_Portal(const mapgen_blueprint_t *bp,
                                                        uint32_t index)
{
    return (bp && index < bp->num_portals) ? &bp->portals[index] : NULL;
}

uint32_t MapGenBlueprint_NumRelations(const mapgen_blueprint_t *bp)
{
    return bp ? bp->num_relations : 0;
}

const mapgen_blueprint_relation_t *MapGenBlueprint_Relation(const mapgen_blueprint_t *bp,
                                                            uint32_t index)
{
    return (bp && index < bp->num_relations) ? &bp->relations[index] : NULL;
}

uint32_t MapGenBlueprint_VolumeAt(const mapgen_blueprint_t *bp,
                                  const int32_t point[3])
{
    if (!bp || !point)
        return MAPGEN_BLUEPRINT_NO_VOLUME;
    for (uint32_t v = 0; v < bp->num_volumes; v++) {
        const mapgen_blueprint_volume_t *vol = &bp->volumes[v];
        bool inside = true;
        for (int axis = 0; axis < 3; axis++)
            if (point[axis] < vol->mins[axis] || point[axis] >= vol->maxs[axis])
                inside = false;
        if (inside)
            return v;
    }
    return MAPGEN_BLUEPRINT_NO_VOLUME;
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
    if (s->out && s->needed + n < s->capacity)
        memcpy(s->out + s->needed, text, n);
    s->needed += n;
}

static void put_i32(sink_t *s, int32_t value)
{
    char digits[12];
    size_t n = 0;
    uint32_t magnitude = value < 0 ? (uint32_t)(-(int64_t)value) : (uint32_t)value;
    do {
        digits[n++] = (char)('0' + magnitude % 10u);
        magnitude /= 10u;
    } while (magnitude && n < sizeof(digits));

    char text[16];
    size_t at = 0;
    if (value < 0)
        text[at++] = '-';
    while (n)
        text[at++] = digits[--n];
    text[at] = '\0';
    put(s, text);
}

static void put_row(sink_t *s, const int32_t *values, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++) {
        put_i32(s, values[i]);
        put(s, i + 1 < n ? "," : "\n");
    }
}

size_t MapGenBlueprint_CanonicalText(const mapgen_blueprint_t *bp, char *out,
                                     size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!bp) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    put(&s, "volumes=");
    put_i32(&s, (int32_t)bp->num_volumes);
    put(&s, "\n");
    for (uint32_t v = 0; v < bp->num_volumes; v++) {
        const mapgen_blueprint_volume_t *vol = &bp->volumes[v];
        const int32_t row[] = {
            (int32_t)vol->id, (int32_t)vol->klass, (int32_t)vol->flags,
            vol->mins[0], vol->mins[1], vol->mins[2],
            vol->maxs[0], vol->maxs[1], vol->maxs[2],
            vol->floor, vol->ceiling, (int32_t)vol->stances,
            (int32_t)vol->occupancy_permille, (int32_t)vol->landmark_weight,
        };
        put(&s, "v=");
        put_row(&s, row, sizeof(row) / sizeof(row[0]));
    }

    put(&s, "portals=");
    put_i32(&s, (int32_t)bp->num_portals);
    put(&s, "\n");
    for (uint32_t p = 0; p < bp->num_portals; p++) {
        const mapgen_blueprint_portal_t *portal = &bp->portals[p];
        const int32_t row[] = {
            (int32_t)portal->from, (int32_t)portal->to, (int32_t)portal->kind,
            portal->one_way ? 1 : 0, portal->rise, (int32_t)portal->aperture,
            (int32_t)portal->clearance,
        };
        put(&s, "p=");
        put_row(&s, row, sizeof(row) / sizeof(row[0]));
    }

    put(&s, "relations=");
    put_i32(&s, (int32_t)bp->num_relations);
    put(&s, "\n");
    for (uint32_t r = 0; r < bp->num_relations; r++) {
        const mapgen_blueprint_relation_t *rel = &bp->relations[r];
        const int32_t row[] = { (int32_t)rel->a, (int32_t)rel->b,
                                (int32_t)rel->kind };
        put(&s, "r=");
        put_row(&s, row, sizeof(row) / sizeof(row[0]));
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenBlueprint_CanonicalDigest(const mapgen_blueprint_t *bp)
{
    const size_t needed = MapGenBlueprint_CanonicalText(bp, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenBlueprint_CanonicalText(bp, text, needed + 1);

    /* FNV-1a 64, the same hash every other canonical form in this tree uses. */
    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
