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
 * MAPGEN-1 - deriving the solid world from the empty space.
 *
 * Four passes:
 *
 *   1. mark every voxel the layout says is empty;
 *   2. mark the shell - every voxel within a wall's thickness of an empty one;
 *   3. prove the shell seals, by flooding from outside and checking that the
 *      flood never reaches empty space;
 *   4. merge the shell voxels into as few axis-aligned boxes as a greedy pass
 *      manages, and give each box's faces a material the corpus taught.
 *
 * The openings where a corridor meets a room are not built. They are what is
 * left where two empty volumes touch, which is why this construction has no
 * special case for them.
 */

#include "common/mapgen_brush.h"
#include "common/mapgen_random.h"
#include "common/mapgen_entities.h"  /* MAPGEN_PLACEMENT_FLOOR_OFFSET */
#include "common/mapgen_genome.h"

#include <stdlib.h>
#include <string.h>

const char *MapGenBrush_ResultName(mapgen_brush_result_t r)
{
    switch (r) {
    case MAPGEN_BRUSH_OK:                  return "OK";
    case MAPGEN_BRUSH_ERR_ARGS:            return "ERR_ARGS";
    case MAPGEN_BRUSH_ERR_MEMORY:          return "ERR_MEMORY";
    case MAPGEN_BRUSH_ERR_EMPTY_LAYOUT:    return "ERR_EMPTY_LAYOUT";
    case MAPGEN_BRUSH_ERR_GRID_TOO_LARGE:  return "ERR_GRID_TOO_LARGE";
    case MAPGEN_BRUSH_ERR_TOO_MANY_BRUSHES: return "ERR_TOO_MANY_BRUSHES";
    case MAPGEN_BRUSH_ERR_NO_MATERIAL:     return "ERR_NO_MATERIAL";
    case MAPGEN_BRUSH_ERR_NO_TARGET_MANIFEST: return "ERR_NO_TARGET_MANIFEST";
    case MAPGEN_BRUSH_ERR_LEAK:            return "ERR_LEAK";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenBrush_FaceName(mapgen_face_t face)
{
    switch (face) {
    case MAPGEN_FACE_EAST:   return "east";
    case MAPGEN_FACE_WEST:   return "west";
    case MAPGEN_FACE_NORTH:  return "north";
    case MAPGEN_FACE_SOUTH:  return "south";
    case MAPGEN_FACE_TOP:    return "top";
    case MAPGEN_FACE_BOTTOM: return "bottom";
    case MAPGEN_FACE_COUNT:  break;
    }
    return "unknown";
}

/* ---- the grid ------------------------------------------------------------ */

#define VOXEL_OUTSIDE  0u
#define VOXEL_EMPTY    1u
#define VOXEL_SHELL    2u
#define VOXEL_FLOODED  3u

typedef struct {
    uint8_t *cell;
    int32_t  origin[3];         /* world coordinate of voxel (0,0,0) */
    uint32_t size[3];
} grid_t;

static size_t grid_index(const grid_t *g, uint32_t x, uint32_t y, uint32_t z)
{
    return ((size_t)z * g->size[1] + y) * g->size[0] + x;
}

struct mapgen_brushwork_s {
    mapgen_brush_t     *brushes;
    uint32_t            num_brushes;
    uint64_t            empty_voxels;
    mapgen_layout_box_t bounds;
    mapgen_fixture_t    fixtures[MAPGEN_MAX_FIXTURES];
    uint32_t            num_fixtures;
    mapgen_fixture_t    markers[MAPGEN_MAX_FIXTURES];
    uint32_t            num_markers;
};

/* ---- fixtures ------------------------------------------------------------ */


/* To the layout's own grid, so a fitting's corners sit where every other
   corner in this file sits. */
static int32_t snap_to_grid(int32_t v)
{
    const int32_t g = MAPGEN_LAYOUT_GRID;
    return (v >= 0 ? (v + g / 2) / g : -((-v + g / 2) / g)) * g;
}
/*
 * Where a room's ceiling lights are, as boxes cut UPWARD into the rock.
 *
 * One function, used by the pass that carves them and by the pass that
 * textures them, because two copies of this arithmetic would eventually
 * disagree about where a fitting is and leave an unlit hole in the ceiling.
 *
 * Returns how many the room has; `index` selects one.
 */
static uint32_t ceiling_recesses(const mapgen_layout_box_t *space,
                                 uint32_t index, mapgen_layout_box_t *out)
{
    const int32_t width = space->maxs[0] - space->mins[0];
    const int32_t depth = space->maxs[1] - space->mins[1];

    int32_t across = width / MAPGEN_BRUSH_PANEL_SPACING;
    int32_t down = depth / MAPGEN_BRUSH_PANEL_SPACING;
    if (across < 1) across = 1;
    if (down < 1) down = 1;
    /* A hall gets a row of them, not a single lamp in the middle. */
    if (across > 4) across = 4;
    if (down > 4) down = 4;

    const uint32_t count = (uint32_t)(across * down);
    if (!out || index >= count)
        return count;

    const int32_t px = (int32_t)(index % (uint32_t)across);
    const int32_t py = (int32_t)(index / (uint32_t)across);
    const int32_t cx = space->mins[0] + width * (2 * px + 1) / (2 * across);
    const int32_t cy = space->mins[1] + depth * (2 * py + 1) / (2 * down);

    out->mins[0] = snap_to_grid(cx) - MAPGEN_BRUSH_PANEL_SIZE / 2;
    out->maxs[0] = out->mins[0] + MAPGEN_BRUSH_PANEL_SIZE;
    out->mins[1] = snap_to_grid(cy) - MAPGEN_BRUSH_PANEL_SIZE / 2;
    out->maxs[1] = out->mins[1] + MAPGEN_BRUSH_PANEL_SIZE;
    /* Upward into the rock: the ceiling plane is the bottom of the recess. */
    out->mins[2] = space->maxs[2];
    out->maxs[2] = space->maxs[2] + MAPGEN_BRUSH_RECESS_DEPTH;
    return count;
}

/*
 * Is this brush's downward face the top of a light recess?
 *
 * The same arithmetic that carved them, asked in reverse, so the pass that
 * makes a fitting and the pass that textures it cannot disagree about where
 * one is and leave an unlit hole in a ceiling.
 */
static bool lit_by_recess(const mapgen_layout_t *layout,
                          const mapgen_brush_t *b)
{
    for (uint32_t pass = 0; pass < 2; pass++) {
        const uint32_t outer = pass ? MapGenLayout_NumPassages(layout)
                                    : MapGenLayout_NumRooms(layout);
        for (uint32_t o = 0; o < outer; o++) {
            const mapgen_layout_passage_t *p =
                pass ? MapGenLayout_Passage(layout, o) : NULL;
            const uint32_t inner = pass ? p->num_segments : 1;
            for (uint32_t s = 0; s < inner; s++) {
                const mapgen_layout_box_t *space =
                    pass ? &p->segments[s]
                         : &MapGenLayout_Room(layout, o)->space;
                mapgen_layout_box_t recess;
                const uint32_t count = ceiling_recesses(space, 0, NULL);
                for (uint32_t i = 0; i < count; i++) {
                    if (ceiling_recesses(space, i, &recess) <= i)
                        continue;
                    if (b->mins[2] == recess.maxs[2]
                        && b->mins[0] < recess.maxs[0]
                        && b->maxs[0] > recess.mins[0]
                        && b->mins[1] < recess.maxs[1]
                        && b->maxs[1] > recess.mins[1])
                        return true;
                }
            }
        }
    }
    return false;
}


static void fixture_key(mapgen_fixture_t *f, const char *key, const char *value)
{
    if (f->num_keys >= MAPGEN_FIXTURE_MAX_KEYS)
        return;
    mapgen_fixture_key_t *k = &f->keys[f->num_keys++];
    size_t i = 0;
    for (; key[i] && i + 1 < sizeof(k->key); i++)
        k->key[i] = key[i];
    k->key[i] = '\0';
    for (i = 0; value[i] && i + 1 < sizeof(k->value); i++)
        k->value[i] = value[i];
    k->value[i] = '\0';
}

/* Locale-free, and the only integer-to-text this file does. */
static void fixture_int(char *out, size_t capacity, int32_t value)
{
    char digits[12];
    size_t n = 0, at = 0;
    uint32_t magnitude = value < 0 ? (uint32_t)(-(int64_t)value) : (uint32_t)value;

    do {
        digits[n++] = (char)('0' + magnitude % 10u);
        magnitude /= 10u;
    } while (magnitude && n < sizeof(digits));

    if (value < 0 && at + 1 < capacity)
        out[at++] = '-';
    while (n && at + 1 < capacity)
        out[at++] = digits[--n];
    out[at] = '\0';
}

static mapgen_fixture_t *new_fixture(mapgen_brushwork_t *work,
                                     const char *classname,
                                     const mapgen_layout_box_t *box,
                                     uint32_t material)
{
    if (work->num_fixtures >= MAPGEN_MAX_FIXTURES)
        return NULL;
    mapgen_fixture_t *f = &work->fixtures[work->num_fixtures++];
    memset(f, 0, sizeof(*f));
    size_t i = 0;
    for (; classname[i] && i + 1 < sizeof(f->classname); i++)
        f->classname[i] = classname[i];
    f->classname[i] = '\0';
    for (int axis = 0; axis < 3; axis++) {
        f->brush.mins[axis] = box->mins[axis];
        f->brush.maxs[axis] = box->maxs[axis];
    }
    for (uint32_t face = 0; face < MAPGEN_FACE_COUNT; face++)
        f->brush.material[face] = material;
    return f;
}

static mapgen_fixture_t *new_marker(mapgen_brushwork_t *work,
                                    const char *classname,
                                    const int32_t origin[3])
{
    if (work->num_markers >= MAPGEN_MAX_FIXTURES)
        return NULL;
    mapgen_fixture_t *m = &work->markers[work->num_markers++];
    memset(m, 0, sizeof(*m));
    size_t i = 0;
    for (; classname[i] && i + 1 < sizeof(m->classname); i++)
        m->classname[i] = classname[i];
    m->classname[i] = '\0';
    for (int axis = 0; axis < 3; axis++) {
        m->brush.mins[axis] = origin[axis];
        m->brush.maxs[axis] = origin[axis];
    }
    return m;
}

/* ---- materials ----------------------------------------------------------- */

/*
 * A face's material is chosen from the allowlist by what the corpus USED the
 * material as. `wanted` is the role that must be present and `forbidden` the
 * roles that rule it out - a sky or a liquid is not a wall, however often it
 * appeared.
 */
/*
 * The set a texture belongs to: the first component of its path.
 *
 * `e1u1/floor3_1` and `e1u1/box1_3` are the same place; `e3u3/metal15_2` is
 * another one. A map built from four of them at once is four places, and the
 * one this generator handed over on 2026-09-07 was exactly that.
 */
static void material_family(const mapgen_mix_t *model, uint32_t index,
                            char *out, size_t capacity)
{
    if (capacity)
        out[0] = '\0';
    const char *name = MapGenMix_MaterialName(model, index);
    if (!name || !capacity)
        return;
    size_t n = 0;
    for (; name[n] && name[n] != '/' && n + 1 < capacity; n++)
        out[n] = name[n];
    out[n] = '\0';
}

/*
 * One material, of a role, and - when a family has been settled on - of that
 * family.
 *
 * `family` is the set every wall and floor of this map should come from. It
 * is a preference rather than a rule: a corpus that learned its sky or its
 * water in another set would otherwise produce a map with no sky at all,
 * which is a worse answer than a sky from next door. So the family narrows
 * the choice when it can and is dropped when it would empty it.
 */
static uint32_t pick_material_of(const mapgen_mix_t *model,
                                 mapgen_random_t *rng, uint32_t wanted,
                                 uint32_t forbidden, const char *family)
{
    const uint32_t count = MapGenMix_NumMaterials(model);
    if (!count)
        return count;

    uint32_t *weights = calloc(count, sizeof(uint32_t));
    if (!weights)
        return count;

    uint32_t eligible = 0;
    for (uint32_t i = 0; i < count; i++) {
        const uint32_t roles = MapGenMix_MaterialRoles(model, i);
        if (wanted && !(roles & wanted))
            continue;
        if (roles & forbidden)
            continue;
        if (family && family[0]) {
            char mine[32];
            material_family(model, i, mine, sizeof(mine));
            if (strcmp(mine, family))
                continue;
        }
        /* Sampled in proportion to how much of the corpus used it. */
        weights[i] = MapGenMix_MaterialProbabilityPpm(model, i);
        if (!weights[i])
            weights[i] = 1;
        eligible++;
    }

    uint32_t chosen = count;
    if (eligible)
        chosen = MapGenRandom_Weighted(rng, weights, count);
    free(weights);
    /* Nothing of that role in that family: take the role and let the family
       go, rather than build a map with a hole where its sky should be. */
    if (!eligible && family && family[0])
        return pick_material_of(model, rng, wanted, forbidden, NULL);
    return chosen;
}

static uint32_t pick_material(const mapgen_mix_t *model, mapgen_random_t *rng,
                              uint32_t wanted, uint32_t forbidden)
{
    return pick_material_of(model, rng, wanted, forbidden, NULL);
}

/* ---- building ------------------------------------------------------------ */

static void mark_box(grid_t *g, const mapgen_layout_box_t *box, uint8_t value)
{
    const int32_t v = MAPGEN_BRUSH_VOXEL;
    for (int32_t z = box->mins[2]; z < box->maxs[2]; z += v) {
        for (int32_t y = box->mins[1]; y < box->maxs[1]; y += v) {
            for (int32_t x = box->mins[0]; x < box->maxs[0]; x += v) {
                const int64_t gx = (x - g->origin[0]) / v;
                const int64_t gy = (y - g->origin[1]) / v;
                const int64_t gz = (z - g->origin[2]) / v;
                if (gx < 0 || gy < 0 || gz < 0)
                    continue;
                if ((uint32_t)gx >= g->size[0] || (uint32_t)gy >= g->size[1]
                    || (uint32_t)gz >= g->size[2])
                    continue;
                g->cell[grid_index(g, (uint32_t)gx, (uint32_t)gy, (uint32_t)gz)] = value;
            }
        }
    }
}


/*
 * Flood from outside through everything that is not shell. Reaching an empty
 * voxel means the map leaks, which is the one failure a compiler cannot fix
 * and a player finds immediately.
 */
static bool shell_seals(grid_t *g)
{
    const size_t total = (size_t)g->size[0] * g->size[1] * g->size[2];
    uint32_t *stack = malloc(total * sizeof(uint32_t));
    if (!stack)
        return false;

    size_t top = 0;
    /* Every voxel on the boundary of the grid that is not shell. */
    for (uint32_t z = 0; z < g->size[2]; z++) {
        for (uint32_t y = 0; y < g->size[1]; y++) {
            for (uint32_t x = 0; x < g->size[0]; x++) {
                const bool on_edge = x == 0 || y == 0 || z == 0
                                   || x + 1 == g->size[0]
                                   || y + 1 == g->size[1]
                                   || z + 1 == g->size[2];
                if (!on_edge)
                    continue;
                const size_t at = grid_index(g, x, y, z);
                if (g->cell[at] != VOXEL_OUTSIDE)
                    continue;
                g->cell[at] = VOXEL_FLOODED;
                stack[top++] = (uint32_t)at;
            }
        }
    }

    bool leaked = false;
    while (top && !leaked) {
        const uint32_t at = stack[--top];
        const uint32_t x = (uint32_t)(at % g->size[0]);
        const uint32_t y = (uint32_t)((at / g->size[0]) % g->size[1]);
        const uint32_t z = (uint32_t)(at / ((size_t)g->size[0] * g->size[1]));

        static const int32_t STEP[6][3] = {
            { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 },
            { 0, -1, 0 }, { 0, 0, 1 }, { 0, 0, -1 },
        };
        for (int d = 0; d < 6; d++) {
            const int64_t nx = (int64_t)x + STEP[d][0];
            const int64_t ny = (int64_t)y + STEP[d][1];
            const int64_t nz = (int64_t)z + STEP[d][2];
            if (nx < 0 || ny < 0 || nz < 0)
                continue;
            if ((uint32_t)nx >= g->size[0] || (uint32_t)ny >= g->size[1]
                || (uint32_t)nz >= g->size[2])
                continue;
            const size_t next = grid_index(g, (uint32_t)nx, (uint32_t)ny,
                                           (uint32_t)nz);
            if (g->cell[next] == VOXEL_EMPTY) {
                leaked = true;
                break;
            }
            if (g->cell[next] != VOXEL_OUTSIDE)
                continue;
            g->cell[next] = VOXEL_FLOODED;
            stack[top++] = (uint32_t)next;
        }
    }

    free(stack);
    return !leaked;
}

/* ---- merging ------------------------------------------------------------- */

static bool all_shell(const grid_t *g, uint32_t x0, uint32_t x1,
                      uint32_t y0, uint32_t y1, uint32_t z0, uint32_t z1)
{
    for (uint32_t z = z0; z < z1; z++)
        for (uint32_t y = y0; y < y1; y++)
            for (uint32_t x = x0; x < x1; x++)
                if (g->cell[grid_index(g, x, y, z)] != VOXEL_SHELL)
                    return false;
    return true;
}

static void claim(grid_t *g, uint32_t x0, uint32_t x1, uint32_t y0,
                  uint32_t y1, uint32_t z0, uint32_t z1)
{
    for (uint32_t z = z0; z < z1; z++)
        for (uint32_t y = y0; y < y1; y++)
            for (uint32_t x = x0; x < x1; x++)
                g->cell[grid_index(g, x, y, z)] = VOXEL_OUTSIDE;
}

mapgen_brush_result_t MapGenBrush_Build(const mapgen_layout_t *layout,
                                        const mapgen_mix_t *model,
                                        const mapgen_recipe_t *recipe,
                                        uint32_t attempt,
                                        mapgen_brushwork_t **out)
{
    if (out)
        *out = NULL;
    if (!layout || !model || !recipe || !out)
        return MAPGEN_BRUSH_ERR_ARGS;
    if (!MapGenLayout_NumRooms(layout))
        return MAPGEN_BRUSH_ERR_EMPTY_LAYOUT;
    /* Contract 15: an allowlist that was never filtered against the target is
       an allowlist of things that may not exist there. */
    if (!MapGenMix_HasTargetManifest(model))
        return MAPGEN_BRUSH_ERR_NO_TARGET_MANIFEST;

    const mapgen_layout_box_t *bounds = MapGenLayout_Bounds(layout);
    const int32_t v = MAPGEN_BRUSH_VOXEL;
    /*
     * The rock envelope has to be thicker than anything carved INTO it. A
     * light recess is cut upward out of the ceiling, and with the old margin
     * the topmost room had exactly as much rock above it as the recess was
     * deep - so the recess punched through to the void and the map leaked.
     */
    const int32_t margin = (MAPGEN_BRUSH_WALL_VOXELS + 1) * v
                         + MAPGEN_BRUSH_RECESS_DEPTH;

    grid_t g;
    memset(&g, 0, sizeof(g));
    for (int axis = 0; axis < 3; axis++) {
        g.origin[axis] = bounds->mins[axis] - margin;
        const int64_t span = (int64_t)bounds->maxs[axis] + margin - g.origin[axis];
        g.size[axis] = (uint32_t)((span + v - 1) / v);
        if (!g.size[axis])
            g.size[axis] = 1;
    }

    const uint64_t voxels = (uint64_t)g.size[0] * g.size[1] * g.size[2];
    if (voxels > MAPGEN_BRUSH_MAX_VOXELS)
        return MAPGEN_BRUSH_ERR_GRID_TOO_LARGE;

    g.cell = calloc((size_t)voxels, 1);
    if (!g.cell)
        return MAPGEN_BRUSH_ERR_MEMORY;

    /* --- 1: the empty space ---------------------------------------------- */
    for (uint32_t i = 0; i < MapGenLayout_NumRooms(layout); i++)
        mark_box(&g, &MapGenLayout_Room(layout, i)->space, VOXEL_EMPTY);
    for (uint32_t p = 0; p < MapGenLayout_NumPassages(layout); p++) {
        const mapgen_layout_passage_t *pass = MapGenLayout_Passage(layout, p);
        for (uint32_t s = 0; s < pass->num_segments; s++)
            mark_box(&g, &pass->segments[s], VOXEL_EMPTY);
    }
    /*
     * A pool is a pit in the floor, and a pit is empty space: the player is IN
     * the water. Carving it here is what makes the solid derivation leave the
     * hole; the liquid brush that fills it is emitted further down, and does
     * not participate in the seal because a liquid does not seal anything.
     */
    for (uint32_t i = 0; i < MapGenLayout_NumPools(layout); i++)
        mark_box(&g, &MapGenLayout_Pool(layout, i)->space, VOXEL_EMPTY);
    /*
     * And the light recesses, cut UPWARD into the ceiling rock. Carving them
     * with the rest of the empty space is what makes the rock around them
     * their housing, so a fitting is part of the ceiling and cannot end up
     * hanging in the air the way a separate box could.
     */
    for (uint32_t r = 0; r < MapGenLayout_NumRooms(layout); r++) {
        const mapgen_layout_box_t *space = &MapGenLayout_Room(layout, r)->space;
        mapgen_layout_box_t recess;
        const uint32_t count = ceiling_recesses(space, 0, NULL);
        for (uint32_t i = 0; i < count; i++)
            if (ceiling_recesses(space, i, &recess) > i)
                mark_box(&g, &recess, VOXEL_EMPTY);
    }
    for (uint32_t p = 0; p < MapGenLayout_NumPassages(layout); p++) {
        const mapgen_layout_passage_t *pass = MapGenLayout_Passage(layout, p);
        for (uint32_t s = 0; s < pass->num_segments; s++) {
            mapgen_layout_box_t recess;
            const uint32_t count = ceiling_recesses(&pass->segments[s], 0, NULL);
            for (uint32_t i = 0; i < count; i++)
                if (ceiling_recesses(&pass->segments[s], i, &recess) > i)
                    mark_box(&g, &recess, VOXEL_EMPTY);
        }
    }

    uint64_t empty = 0;
    for (uint64_t i = 0; i < voxels; i++)
        if (g.cell[i] == VOXEL_EMPTY)
            empty++;
    if (!empty) {
        free(g.cell);
        return MAPGEN_BRUSH_ERR_EMPTY_LAYOUT;
    }

    /* --- 2: the rock -------------------------------------------------------
     *
     * Everything that is not empty space is SOLID, out to one voxel short of
     * the grid's edge.
     *
     * This was a shell MAPGEN_BRUSH_WALL_VOXELS thick, with nothing beyond it,
     * and that is what made the maps look the way the PO described: a flight
     * of stairs became 32-unit treads with a void underneath, a lift shaft
     * became a tube hanging in space, and from any tall room you could see the
     * outside of the next corridor. A map is cut OUT of rock; it is not
     * assembled from plates.
     *
     * The outermost ring stays outside, so the seal proof below still has
     * somewhere to flood from and still means what it meant.
     */
    for (uint32_t z = 0; z < g.size[2]; z++) {
        for (uint32_t y = 0; y < g.size[1]; y++) {
            for (uint32_t x = 0; x < g.size[0]; x++) {
                const size_t at = grid_index(&g, x, y, z);
                if (g.cell[at] == VOXEL_EMPTY)
                    continue;
                if (x == 0 || y == 0 || z == 0
                    || x + 1 == g.size[0] || y + 1 == g.size[1]
                    || z + 1 == g.size[2])
                    continue;               /* the ring the flood starts in */
                g.cell[at] = VOXEL_SHELL;
            }
        }
    }

    /* --- 3: it has to seal ------------------------------------------------ */
    if (!shell_seals(&g)) {
        free(g.cell);
        return MAPGEN_BRUSH_ERR_LEAK;
    }
    /* The flood marked its own path; put it back so the merge sees only
       shell and not-shell. */
    for (uint64_t i = 0; i < voxels; i++)
        if (g.cell[i] == VOXEL_FLOODED)
            g.cell[i] = VOXEL_OUTSIDE;

    /* --- 4: merge and texture --------------------------------------------- */
    mapgen_random_t rng;
    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,
                        MAPGEN_RANDOM_MATERIALS);

    /*
     * A texture set PER ROOM, not one for the whole map.
     *
     * Contract 7.7's style grammar is about a map looking like the corpus, and
     * the corpus does not build every room out of the same three textures - a
     * map that does reads as one corridor however large it is. Still one draw
     * per room rather than per brush, because forty different walls in one
     * room is the opposite mistake.
     */
    /*
     * MAPGEN_ROLE_LIGHT belongs on this list and was missing from it. A room
     * whose walls are a light-emitting texture is a lightbulb: everything it
     * sees clamps to white and everything else stays black, which is the
     * measured shape of every generated lightmap so far.
     */
    const uint32_t forbidden = MAPGEN_ROLE_SKY | MAPGEN_ROLE_WATER
                             | MAPGEN_ROLE_LAVA | MAPGEN_ROLE_SLIME
                             | MAPGEN_ROLE_NODRAW | MAPGEN_ROLE_CLIP
                             | MAPGEN_ROLE_TRANSLUCENT | MAPGEN_ROLE_LIGHT;
    const uint32_t materials = MapGenMix_NumMaterials(model);
    const uint32_t num_rooms = MapGenLayout_NumRooms(layout);

    /*
     * The sky, for the rooms the layout marked open to it. Drawn once: a map
     * with two different skies in it is a map with a seam in it.
     */
    const uint32_t sky = pick_material(model, &rng, MAPGEN_ROLE_SKY,
                                       MAPGEN_ROLE_WATER | MAPGEN_ROLE_LAVA
                                       | MAPGEN_ROLE_SLIME);

    uint32_t *floor_of = calloc(num_rooms, sizeof(uint32_t));
    uint32_t *wall_of = calloc(num_rooms, sizeof(uint32_t));
    uint32_t *ceiling_of = calloc(num_rooms, sizeof(uint32_t));
    if (!floor_of || !wall_of || !ceiling_of) {
        free(floor_of); free(wall_of); free(ceiling_of);
        free(g.cell);
        return MAPGEN_BRUSH_ERR_MEMORY;
    }
    /*
     * One place, or four.
     *
     * `arch_material_family` at 1 settles on the set the first solid pick
     * belongs to and asks for every wall, floor and ceiling from it. The map
     * this generator handed over on 2026-09-07 was built from e1u1, e2u3,
     * e3u2 and e3u3 at once - four episodes in one room-and-a-half - and the
     * PO's word for the result was that it did not look like a place.
     *
     * Off by default, because a corpus of many maps IS a mixture and a
     * caller may want what it learned.
     */
    char family[32] = "";
    if (MapGenRecipe_ResolvedValue(recipe, "arch_material_family", 0) > 0) {
        const uint32_t first =
            pick_material(model, &rng, MAPGEN_ROLE_SOLID, forbidden);
        if (first < materials)
            material_family(model, first, family, sizeof(family));
    }

    for (uint32_t r = 0; r < num_rooms; r++) {
        floor_of[r] = pick_material_of(model, &rng, MAPGEN_ROLE_SOLID,
                                       forbidden, family);
        wall_of[r] = pick_material_of(model, &rng, MAPGEN_ROLE_SOLID,
                                      forbidden, family);
        ceiling_of[r] = pick_material_of(model, &rng, MAPGEN_ROLE_SOLID,
                                         forbidden, family);
        if (floor_of[r] >= materials || wall_of[r] >= materials
            || ceiling_of[r] >= materials) {
            free(floor_of); free(wall_of); free(ceiling_of);
            free(g.cell);
            return MAPGEN_BRUSH_ERR_NO_MATERIAL;
        }
    }

    /*
     * The ceiling fittings, chosen before the rock is textured: a fitting
     * is a FACE of the shell now, not a box added afterwards.
     */
    /*
     * An emitter the corpus used AT a brightness. A material can carry
     * SURF_LIGHT and have only ever been used at value 0 - a sky is the
     * common case - and a panel wearing one of those is a fitting that
     * emits nothing.
     */
    uint32_t emitter = materials;
    for (uint32_t tries = 0; tries < 32 && emitter >= materials; tries++) {
        const uint32_t candidate =
            pick_material(model, &rng, MAPGEN_ROLE_LIGHT,
                          MAPGEN_ROLE_SKY | MAPGEN_ROLE_WATER
                          | MAPGEN_ROLE_LAVA | MAPGEN_ROLE_SLIME
                          | MAPGEN_ROLE_NODRAW);
        if (candidate < materials
            && MapGenMix_MaterialLightValue(model, candidate) > 0)
            emitter = candidate;
    }
    /*
     * And a fitting PER ROOM, drawn the same way, for the same reason the
     * wall texture is per room: one emitter for the whole map lights every
     * room in one colour, and the colour a surface light gives is the
     * colour of the texture it wears. MEASURED: with a single neutral
     * fitting only 2% of lightmap texels carried any colour at all, where
     * a real map runs 96 to 99%.
     */
    uint32_t *emitter_of = calloc(num_rooms ? num_rooms : 1,
                                  sizeof(uint32_t));
    if (!emitter_of) {
        /* Before the brushwork exists, so there is nothing else to release. */
        free(floor_of); free(wall_of); free(ceiling_of);
        free(g.cell);
        return MAPGEN_BRUSH_ERR_MEMORY;
    }
    /*
     * A CEILING fitting, which is a brighter thing than a wall trim.
     *
     * MEASURED: the corpus lights its ceilings at 10000 - q2dm1 ceil1_13,
     * q2dm2 ceil1_28, q2dm3 ceil1_4, q2duel1 ceil1_17, match1 ceil1_3 -
     * and its wall strips at 200 to 800. Drawing from all of them equally
     * hung 200-value trims from the ceiling and took the map back down to
     * a lightmap mean of 27 where a real map sits near 60. The threshold
     * is a quarter of the brightest the selection knows, so it follows the
     * corpus rather than a number of mine.
     */
    int32_t brightest = 0;
    for (uint32_t i = 0; i < materials; i++) {
        const int32_t value = MapGenMix_MaterialLightValue(model, i);
        if (value > brightest)
            brightest = value;
    }
    const int32_t ceiling_min = brightest / 4;

    for (uint32_t r = 0; r < num_rooms; r++) {
        emitter_of[r] = emitter;
        for (uint32_t tries = 0; tries < 16; tries++) {
            const uint32_t candidate =
                pick_material(model, &rng, MAPGEN_ROLE_LIGHT,
                              MAPGEN_ROLE_SKY | MAPGEN_ROLE_WATER
                              | MAPGEN_ROLE_LAVA | MAPGEN_ROLE_SLIME
                              | MAPGEN_ROLE_NODRAW);
            if (candidate < materials
                && MapGenMix_MaterialLightValue(model, candidate)
                   >= ceiling_min) {
                emitter_of[r] = candidate;
                break;
            }
        }
    }

    mapgen_brushwork_t *work = calloc(1, sizeof(*work));
    if (!work) {
        free(g.cell);
        return MAPGEN_BRUSH_ERR_MEMORY;
    }
    work->empty_voxels = empty;
    work->bounds = *bounds;

    for (uint32_t z = 0; z < g.size[2]; z++) {
        for (uint32_t y = 0; y < g.size[1]; y++) {
            for (uint32_t x = 0; x < g.size[0]; x++) {
                if (g.cell[grid_index(&g, x, y, z)] != VOXEL_SHELL)
                    continue;

                /* Greedy: as far as it goes in x, then y, then z. */
                uint32_t x1 = x + 1;
                while (x1 < g.size[0]
                       && g.cell[grid_index(&g, x1, y, z)] == VOXEL_SHELL)
                    x1++;
                uint32_t y1 = y + 1;
                while (y1 < g.size[1] && all_shell(&g, x, x1, y1, y1 + 1, z, z + 1))
                    y1++;
                uint32_t z1 = z + 1;
                while (z1 < g.size[2] && all_shell(&g, x, x1, y, y1, z1, z1 + 1))
                    z1++;

                claim(&g, x, x1, y, y1, z, z1);

                if (work->num_brushes >= MAPGEN_BRUSH_MAX_BRUSHES) {
                    free(g.cell);
                    MapGenBrush_Free(work);
                    return MAPGEN_BRUSH_ERR_TOO_MANY_BRUSHES;
                }
                void *grown = realloc(work->brushes,
                                      (size_t)(work->num_brushes + 1)
                                      * sizeof(*work->brushes));
                if (!grown) {
                    free(g.cell);
                    MapGenBrush_Free(work);
                    return MAPGEN_BRUSH_ERR_MEMORY;
                }
                work->brushes = grown;
                mapgen_brush_t *b = &work->brushes[work->num_brushes++];
                b->mins[0] = g.origin[0] + (int32_t)x * v;
                b->mins[1] = g.origin[1] + (int32_t)y * v;
                b->mins[2] = g.origin[2] + (int32_t)z * v;
                b->maxs[0] = g.origin[0] + (int32_t)x1 * v;
                b->maxs[1] = g.origin[1] + (int32_t)y1 * v;
                b->maxs[2] = g.origin[2] + (int32_t)z1 * v;

                /*
                 * Which room's shell this is - the nearest room centre. A wall
                 * between two rooms takes one side's texture rather than some
                 * third thing neither room has.
                 */
                uint32_t nearest = 0;
                int64_t nearest_distance = 0;
                for (uint32_t r = 0; r < num_rooms; r++) {
                    const mapgen_layout_box_t *space =
                        &MapGenLayout_Room(layout, r)->space;
                    int64_t d = 0;
                    for (int axis = 0; axis < 3; axis++) {
                        const int64_t centre =
                            (space->mins[axis] + space->maxs[axis]) / 2;
                        const int64_t mid = (b->mins[axis] + b->maxs[axis]) / 2;
                        const int64_t delta = mid - centre;
                        d += delta * delta;
                    }
                    if (!r || d < nearest_distance) {
                        nearest_distance = d;
                        nearest = r;
                    }
                }

                /* A solid's TOP face is the floor of whatever stands on it,
                   and its BOTTOM face is that room's ceiling - or the sky,
                   when the room it roofs is open to it. A ceiling face is one
                   that looks DOWN onto the room's own headroom. */
                b->material[MAPGEN_FACE_TOP] = floor_of[nearest];
                b->material[MAPGEN_FACE_BOTTOM] = ceiling_of[nearest];
                if (sky < materials
                    && MapGenLayout_Room(layout, nearest)->outdoor
                    && b->mins[2]
                       >= MapGenLayout_Room(layout, nearest)->space.maxs[2])
                    b->material[MAPGEN_FACE_BOTTOM] = sky;

                /*
                 * The face at the top of a light recess is the fitting. The
                 * rock around the recess was carved by the same arithmetic, so
                 * the two passes cannot disagree about where a light is.
                 */
                if (emitter_of && lit_by_recess(layout, b))
                    b->material[MAPGEN_FACE_BOTTOM] = emitter_of[nearest];
                b->material[MAPGEN_FACE_EAST] = wall_of[nearest];
                b->material[MAPGEN_FACE_WEST] = wall_of[nearest];
                b->material[MAPGEN_FACE_NORTH] = wall_of[nearest];
                b->material[MAPGEN_FACE_SOUTH] = wall_of[nearest];
            }
        }
    }

    /* --- the liquids ------------------------------------------------------
     *
     * A world brush of a learned water, lava or slime material. The contents
     * ride on the material: the compiler reads CONTENTS_WATER, _LAVA and
     * _SLIME out of the texture's own .wal header (textures.c:77), which is
     * why the writer omits the contents triple and lets each face inherit
     * what its material declares. Nothing here has to know the numbers.
     */
    for (uint32_t i = 0; i < MapGenLayout_NumPools(layout); i++) {
        const mapgen_layout_pool_t *pool = MapGenLayout_Pool(layout, i);
        const uint32_t liquid = pick_material(model, &rng, pool->role, 0);
        if (liquid >= materials)
            continue;                       /* learned, then not drawable */

        void *grown = realloc(work->brushes,
                              (size_t)(work->num_brushes + 1)
                              * sizeof(*work->brushes));
        if (!grown) {
            free(floor_of); free(wall_of); free(ceiling_of);
            free(g.cell);
            MapGenBrush_Free(work);
            return MAPGEN_BRUSH_ERR_MEMORY;
        }
        work->brushes = grown;
        mapgen_brush_t *b = &work->brushes[work->num_brushes++];
        for (int axis = 0; axis < 3; axis++) {
            b->mins[axis] = pool->liquid.mins[axis];
            b->maxs[axis] = pool->liquid.maxs[axis];
        }
        for (uint32_t face = 0; face < MAPGEN_FACE_COUNT; face++)
            b->material[face] = liquid;
    }

    /* --- the fixtures -----------------------------------------------------
     *
     * The topology chose between a walk, a door, a lift, a jump pad and a
     * teleporter for every route in the map, and until now the layout built
     * all five as the same corridor. Each kind that needs an entity gets one
     * here, sized to the passage it belongs to.
     */
    for (uint32_t i = 0; i < MapGenLayout_NumPassages(layout); i++) {
        const mapgen_layout_passage_t *pass = MapGenLayout_Passage(layout, i);
        if (!pass->num_segments)
            continue;

        /* The middle segment is the run between the two rooms; that is where
           a door belongs, and where a lift's shaft is. */
        const mapgen_layout_box_t *seg =
            &pass->segments[pass->num_segments / 2];
        const uint32_t skin = wall_of[pass->from_room < num_rooms
                                      ? pass->from_room : 0];
        char number[16];

        switch (pass->kind) {
        case MAPGEN_ROUTE_DOOR: {
            /*
             * A door fills the doorway and slides out of it. The thin axis is
             * whichever of x and y the passage is narrow in, so the door is a
             * panel across the corridor rather than a block along it.
             */
            mapgen_layout_box_t box = *seg;
            const int32_t width = seg->maxs[0] - seg->mins[0];
            const int32_t depth = seg->maxs[1] - seg->mins[1];
            const int32_t mid_x = (seg->mins[0] + seg->maxs[0]) / 2;
            const int32_t mid_y = (seg->mins[1] + seg->maxs[1]) / 2;
            if (width >= depth) {
                box.mins[0] = mid_x - 8;
                box.maxs[0] = mid_x + 8;
            } else {
                box.mins[1] = mid_y - 8;
                box.maxs[1] = mid_y + 8;
            }
            mapgen_fixture_t *f = new_fixture(work, "func_door", &box, skin);
            if (f) {
                fixture_key(f, "angle", "-1");      /* opens upward */
                fixture_key(f, "speed", "100");
                fixture_key(f, "wait", "3");
            }
            break;
        }

        case MAPGEN_ROUTE_LIFT: {
            /*
             * A plat carries a player up the shaft, and it is DRAWN where it
             * ends up.
             *
             * An untargeted func_plat rests at its lowered position, which the
             * game computes as the drawn brush minus its height. Drawing it on
             * the floor of the shaft therefore sank it the whole rise into the
             * floor slab, and a machine that cannot move is a route that does
             * not exist - the first fidelity-zero map the product path ever
             * gated lost four player starts and eleven pickups behind one.
             *
             * So the brush sits at the top with its face flush with the upper
             * floor, and the travel is what is left after the platform's own
             * thickness: at the bottom it stands ON the lower floor instead of
             * inside it.
             */
            enum { PLATFORM_THICKNESS = 16 };
            mapgen_layout_box_t box = *seg;
            const int32_t upper = seg->maxs[2] - MAPGEN_LAYOUT_CORRIDOR_HEIGHT;
            const int32_t rise = upper - seg->mins[2] - PLATFORM_THICKNESS;
            box.mins[0] += 8;
            box.maxs[0] -= 8;
            box.mins[1] += 8;
            box.maxs[1] -= 8;
            box.maxs[2] = upper;
            box.mins[2] = upper - PLATFORM_THICKNESS;
            if (rise <= 0 || box.maxs[0] <= box.mins[0]
                || box.maxs[1] <= box.mins[1])
                break;
            mapgen_fixture_t *f = new_fixture(work, "func_plat", &box, skin);
            if (f) {
                fixture_int(number, sizeof(number), rise);
                fixture_key(f, "height", number);
                fixture_key(f, "speed", "150");
            }
            break;
        }

        case MAPGEN_ROUTE_PUSH: {
            /*
             * A jump pad, and ONLY where there is somewhere to be thrown.
             *
             * The first version put one in the middle segment of any push
             * passage, firing straight up at a fixed 800 - and the middle
             * segment of an ordinary passage is a corridor one ceiling high.
             * A player who walked in was fired into that ceiling, could not
             * get past, and took the fall. The height above the pad is now
             * the condition, not an assumption.
             */
            const int32_t headroom = seg->maxs[2] - seg->mins[2];
            if (headroom < MAPGEN_BRUSH_MIN_PAD_HEADROOM)
                break;

            mapgen_layout_box_t box = *seg;
            box.mins[0] += 8;
            box.maxs[0] -= 8;
            box.mins[1] += 8;
            box.maxs[1] -= 8;
            box.maxs[2] = seg->mins[2] + 32;
            if (box.maxs[0] <= box.mins[0] || box.maxs[1] <= box.mins[1])
                break;

            mapgen_fixture_t *f = new_fixture(work, "trigger_push", &box, skin);
            if (f) {
                /*
                 * Sized to the shaft: enough to reach the top of it and no
                 * more. v = sqrt(2*g*h) at the engine's own gravity of 800,
                 * approximated with an integer square root so the writer stays
                 * free of floating point.
                 */
                int32_t speed = 0;
                int64_t target = 2 * 800 * (int64_t)(headroom - 64);
                while ((int64_t)(speed + 1) * (speed + 1) <= target)
                    speed++;
                if (speed < 200)
                    speed = 200;
                fixture_int(number, sizeof(number), speed);
                fixture_key(f, "angle", "-1");      /* straight up */
                fixture_key(f, "speed", number);
            }
            break;
        }

        case MAPGEN_ROUTE_TELEPORT: {
            /*
             * A trigger in the first room and a destination in the second. The
             * pair is named after the passage, so two teleporters in one map
             * cannot end up sharing a destination.
             */
            if (pass->from_room >= num_rooms || pass->to_room >= num_rooms)
                break;
            const mapgen_layout_box_t *dest =
                &MapGenLayout_Room(layout, pass->to_room)->space;

            mapgen_layout_box_t box = *seg;
            box.mins[0] += 8;
            box.maxs[0] -= 8;
            box.mins[1] += 8;
            box.maxs[1] -= 8;
            box.maxs[2] = seg->mins[2] + 64;
            if (box.maxs[0] <= box.mins[0] || box.maxs[1] <= box.mins[1])
                break;

            char name[MAPGEN_FIXTURE_VALUE_BYTES];
            fixture_int(number, sizeof(number), (int32_t)i);
            size_t at = 0;
            const char *prefix = "tp_";
            while (prefix[at] && at + 1 < sizeof(name)) {
                name[at] = prefix[at];
                at++;
            }
            for (size_t j = 0; number[j] && at + 1 < sizeof(name); j++)
                name[at++] = number[j];
            name[at] = '\0';

            mapgen_fixture_t *f =
                new_fixture(work, "trigger_teleport", &box, skin);
            if (f)
                fixture_key(f, "target", name);

            const int32_t origin[3] = {
                (dest->mins[0] + dest->maxs[0]) / 2,
                (dest->mins[1] + dest->maxs[1]) / 2,
                dest->mins[2] + MAPGEN_PLACEMENT_FLOOR_OFFSET,
            };
            mapgen_fixture_t *m =
                new_marker(work, "misc_teleporter_dest", origin);
            if (m)
                fixture_key(m, "targetname", name);
            break;
        }

        default:
            break;                          /* the rest are pure geometry */
        }
    }

    free(emitter_of);
    free(floor_of);
    free(wall_of);
    free(ceiling_of);
    free(g.cell);
    *out = work;
    return MAPGEN_BRUSH_OK;
}

void MapGenBrush_Free(mapgen_brushwork_t *work)
{
    if (!work)
        return;
    free(work->brushes);
    free(work);
}

/* ---- accessors ----------------------------------------------------------- */

uint32_t MapGenBrush_Count(const mapgen_brushwork_t *work)
{
    return work ? work->num_brushes : 0;
}

const mapgen_brush_t *MapGenBrush_At(const mapgen_brushwork_t *work,
                                     uint32_t index)
{
    return (work && index < work->num_brushes) ? &work->brushes[index] : NULL;
}

uint32_t MapGenBrush_NumFixtures(const mapgen_brushwork_t *work)
{
    return work ? work->num_fixtures : 0;
}

const mapgen_fixture_t *MapGenBrush_Fixture(const mapgen_brushwork_t *work,
                                            uint32_t index)
{
    return (work && index < work->num_fixtures) ? &work->fixtures[index] : NULL;
}

uint32_t MapGenBrush_NumMarkers(const mapgen_brushwork_t *work)
{
    return work ? work->num_markers : 0;
}

const mapgen_fixture_t *MapGenBrush_Marker(const mapgen_brushwork_t *work,
                                           uint32_t index)
{
    return (work && index < work->num_markers) ? &work->markers[index] : NULL;
}

uint64_t MapGenBrush_EmptyVoxels(const mapgen_brushwork_t *work)
{
    return work ? work->empty_voxels : 0;
}

const mapgen_layout_box_t *MapGenBrush_Bounds(const mapgen_brushwork_t *work)
{
    return work ? &work->bounds : NULL;
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

size_t MapGenBrush_CanonicalText(const mapgen_brushwork_t *work,
                                 const mapgen_mix_t *model,
                                 char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!work) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    put(&s, "brushes=");
    put_i32(&s, (int32_t)work->num_brushes);
    put(&s, "\n");
    for (uint32_t i = 0; i < work->num_brushes; i++) {
        const mapgen_brush_t *b = &work->brushes[i];
        put(&s, "b=");
        for (int axis = 0; axis < 3; axis++) {
            put_i32(&s, b->mins[axis]);
            put(&s, ",");
        }
        for (int axis = 0; axis < 3; axis++) {
            put_i32(&s, b->maxs[axis]);
            put(&s, ",");
        }
        for (uint32_t f = 0; f < MAPGEN_FACE_COUNT; f++) {
            const char *name = model
                ? MapGenMix_MaterialName(model, b->material[f]) : NULL;
            put(&s, name ? name : "?");
            if (f + 1 < MAPGEN_FACE_COUNT)
                put(&s, ",");
        }
        put(&s, "\n");
    }

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

uint64_t MapGenBrush_CanonicalDigest(const mapgen_brushwork_t *work,
                                     const mapgen_mix_t *model)
{
    const size_t needed = MapGenBrush_CanonicalText(work, model, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenBrush_CanonicalText(work, model, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
