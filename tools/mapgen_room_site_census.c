/*
 * Where can a ROOM - the size of one of the map's own - be dug into the rock, reached from a room the map
 * already has by a short passage?
 *
 *     mapgen_room_site_census <map.bsp> [width depth height margin max_reach]
 *
 * Ledger row 314: the halls grown on mg_20h's tunnels are flights widened to 256, and the PO, 2026-09-15: «все эти
 * увеличения ширины это пока очень минорные изменения ... для меня, как игрока, и как PO это просто довольно
 * небольшие отличия архитектурно». Row 309's chamber census asked for a room right behind a wall and found only
 * small ones, because another room lies within a carve's depth behind most walls. This asks further back.
 *
 * For every place a player can stand - a 32-unit lattice over the world model's bounds, air over rock with 72
 * units of headroom - and each of the four ways, the first rock within 64 units at a player's middle height is the
 * wall. A room `width` across, `depth` deep and `height` tall stands `reach` behind that wall's face, its floor at
 * the standing floor, and a passage 128 wide and 128 tall runs from the face to the room. A site is counted at the
 * smallest `reach` (32 to `max_reach`, by 32) at which the room grown by `margin` - on its near side no closer than
 * the face - and the passage grown by 16 across, under and over it are both ROCK: every leaf of the world's tree
 * they reach, a quarter unit in from their faces, solid by the leaf's own contents (the exact question of
 * `dig_hall_in_rock`, ledger row 311). Outside the map's hull the compiler's fill is rock, as the dig's shell treats
 * it. Sites are de-duplicated on a 128-unit grid of the room's middle and its way.
 *
 * Nothing is carved: the answer is how many real rooms the rock could take, how far from the map, and where.
 */

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"

#define MAX_SITES   65536u
#define INSET       0.25f
#define PASSAGE     128.0f
#define HEADROOM    72.0f

typedef struct {
    int32_t key[4];
    float   lo[3], hi[3];
    float   stand[3];
    float   reach;
    int     way;
} site_t;

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t rc = MapGenBsp_Load(raw, (size_t)n, &bsp);
    free(raw);
    return rc == MAPGEN_BSP_OK ? bsp : NULL;
}

static bool rock_at(const mapgen_bsp_t *b, float x, float y, float z)
{
    const float p[3] = { x, y, z };
    return (MapGenBsp_PointContents(b, p) & MAPGEN_CONTENTS_SOLID) != 0;
}

/* Every leaf of the tree the box reaches: solid by its own contents? */
static bool box_rock_node(const mapgen_bsp_t *b, int32_t num, const float lo[3],
                          const float hi[3], int depth)
{
    while (num >= 0) {
        const mapgen_bsp_node_t *node = depth <= 1024
            ? MapGenBsp_Node(b, (uint32_t)num) : NULL;
        const mapgen_bsp_plane_t *plane = node
            ? MapGenBsp_Plane(b, node->planenum) : NULL;
        if (!plane)
            return false;
        float dmin = -plane->dist, dmax = -plane->dist;
        for (int a = 0; a < 3; a++) {
            const float n = plane->normal[a];
            dmin += n * (n < 0.0f ? hi[a] : lo[a]);
            dmax += n * (n < 0.0f ? lo[a] : hi[a]);
        }
        depth++;
        if (dmin >= 0.0f) {
            num = node->children[0];
        } else if (dmax < 0.0f) {
            num = node->children[1];
        } else {
            if (!box_rock_node(b, node->children[0], lo, hi, depth))
                return false;
            num = node->children[1];
        }
    }
    const mapgen_bsp_leaf_t *leaf = MapGenBsp_Leaf(b, (uint32_t)(-1 - num));
    return leaf && (leaf->contents & MAPGEN_CONTENTS_SOLID);
}

static bool box_rock(const mapgen_bsp_t *b, int32_t head, const float lo[3], const float hi[3])
{
    const float l[3] = { lo[0] + INSET, lo[1] + INSET, lo[2] + INSET };
    const float h[3] = { hi[0] - INSET, hi[1] - INSET, hi[2] - INSET };
    return box_rock_node(b, head, l, h, 0);
}

/* A box along way `w` from the standing point: `u0..u1` along it, `across` wide about the point, `z0..z1`. */
static void way_box(int w, float x, float y, float u0, float u1, float across, float z0, float z1,
                    float lo[3], float hi[3])
{
    static const int dx[4] = { 1, -1, 0, 0 }, dy[4] = { 0, 0, 1, -1 };
    if (dx[w]) {
        lo[0] = dx[w] > 0 ? x + u0 : x - u1;
        hi[0] = dx[w] > 0 ? x + u1 : x - u0;
        lo[1] = y - 0.5f * across;
        hi[1] = y + 0.5f * across;
    } else {
        lo[1] = dy[w] > 0 ? y + u0 : y - u1;
        hi[1] = dy[w] > 0 ? y + u1 : y - u0;
        lo[0] = x - 0.5f * across;
        hi[0] = x + 0.5f * across;
    }
    lo[2] = z0;
    hi[2] = z1;
}

static int by_reach(const void *a, const void *b)
{
    const site_t *x = a, *y = b;
    return x->reach < y->reach ? -1 : x->reach > y->reach ? 1 : 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s map.bsp [width depth height margin max_reach]\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    const float width = argc > 2 ? strtof(argv[2], NULL) : 384.0f;
    const float depth = argc > 3 ? strtof(argv[3], NULL) : 384.0f;
    const float height = argc > 4 ? strtof(argv[4], NULL) : 256.0f;
    const float margin = argc > 5 ? strtof(argv[5], NULL) : 32.0f;
    const float max_reach = argc > 6 ? strtof(argv[6], NULL) : 512.0f;
    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    if (!world) {
        fprintf(stderr, "no world model\n");
        return 2;
    }
    const int32_t head = world->headnode;
    static const int dx[4] = { 1, -1, 0, 0 }, dy[4] = { 0, 0, 1, -1 };
    static const char *way_name[4] = { "+x", "-x", "+y", "-y" };

    site_t *sites = calloc(MAX_SITES, sizeof(*sites));
    uint32_t num_sites = 0, standing = 0, walls = 0, standing_with = 0;
    uint32_t bucket[4] = { 0 };                 /* reach <= 32, <= 128, <= 256, more */
    for (float x = world->mins[0] + 16.0f; sites && x < world->maxs[0]; x += 32.0f)
        for (float y = world->mins[1] + 16.0f; y < world->maxs[1]; y += 32.0f) {
            bool below_rock = true;
            for (float z = world->mins[2] + 4.0f; z < world->maxs[2]; z += 8.0f) {
                const bool now = rock_at(bsp, x, y, z);
                const bool floor_here = below_rock && !now;
                below_rock = now;
                if (!floor_here)
                    continue;
                const float floor_z = z - 4.0f;
                bool clear = true;
                for (float h = 8.0f; h <= HEADROOM && clear; h += 16.0f)
                    clear = !rock_at(bsp, x, y, floor_z + h);
                if (!clear)
                    continue;
                standing++;
                bool any = false;
                for (int w = 0; w < 4; w++) {
                    float face = -1.0f;
                    for (float s = 4.0f; s <= 64.0f; s += 4.0f)
                        if (rock_at(bsp, x + dx[w] * s, y + dy[w] * s, floor_z + 32.0f)) {
                            face = s;
                            break;
                        }
                    if (face < 0.0f)
                        continue;
                    walls++;
                    const float first = margin > 32.0f ? ceilf(margin / 32.0f) * 32.0f : 32.0f;
                    for (float reach = first; reach <= max_reach; reach += 32.0f) {
                        float plo[3], phi[3], rlo[3], rhi[3];
                        way_box(w, x, y, face, face + reach, PASSAGE + 32.0f, floor_z - 16.0f,
                                floor_z + PASSAGE + 16.0f, plo, phi);
                        if (!box_rock(bsp, head, plo, phi))
                            break;                  /* a longer passage meets the same air */
                        way_box(w, x, y, face + reach - margin, face + reach + depth + margin,
                                width + 2.0f * margin, floor_z - margin, floor_z + height + margin,
                                rlo, rhi);
                        if (!box_rock(bsp, head, rlo, rhi))
                            continue;
                        any = true;
                        float lo[3], hi[3];
                        way_box(w, x, y, face + reach, face + reach + depth, width, floor_z,
                                floor_z + height, lo, hi);
                        const float mid[3] = { 0.5f * (lo[0] + hi[0]), 0.5f * (lo[1] + hi[1]),
                                               0.5f * (lo[2] + hi[2]) };
                        const int32_t key[4] = { (int32_t)floorf(mid[0] / 128.0f),
                                                 (int32_t)floorf(mid[1] / 128.0f),
                                                 (int32_t)floorf(mid[2] / 128.0f), w };
                        int32_t seen = -1;
                        for (uint32_t i = 0; i < num_sites && seen < 0; i++)
                            if (!memcmp(sites[i].key, key, sizeof(key)))
                                seen = (int32_t)i;
                        if (seen >= 0) {
                            if (reach < sites[seen].reach) {
                                sites[seen].reach = reach;
                                memcpy(sites[seen].lo, lo, sizeof(lo));
                                memcpy(sites[seen].hi, hi, sizeof(hi));
                                sites[seen].stand[0] = x;
                                sites[seen].stand[1] = y;
                                sites[seen].stand[2] = floor_z;
                            }
                            break;
                        }
                        if (num_sites >= MAX_SITES)
                            break;
                        site_t *s = &sites[num_sites++];
                        memcpy(s->key, key, sizeof(key));
                        memcpy(s->lo, lo, sizeof(lo));
                        memcpy(s->hi, hi, sizeof(hi));
                        s->stand[0] = x;
                        s->stand[1] = y;
                        s->stand[2] = floor_z;
                        s->reach = reach;
                        s->way = w;
                        break;
                    }
                }
                standing_with += any ? 1u : 0u;
            }
        }

    for (uint32_t i = 0; i < num_sites; i++)
        bucket[sites[i].reach <= 32.0f ? 0 : sites[i].reach <= 128.0f ? 1
               : sites[i].reach <= 256.0f ? 2 : 3]++;
    printf("%s: a room %.0f wide, %.0f deep, %.0f tall, %.0f of rock round it, reached by a passage of up"
           " to %.0f\n", argv[1], (double)width, (double)depth, (double)height, (double)margin,
           (double)max_reach);
    printf("%u standing places, %u beside a wall, %u with a room behind; %u distinct rooms - reach 32: %u,"
           " up to 128: %u, up to 256: %u, further: %u\n", standing, walls, standing_with, num_sites,
           bucket[0], bucket[1], bucket[2], bucket[3]);
    if (sites)
        qsort(sites, num_sites, sizeof(*sites), by_reach);
    for (uint32_t i = 0; sites && i < num_sites; i++)
        printf("  room %.0f %.0f %.0f .. %.0f %.0f %.0f  reach %.0f %s from the place %.0f %.0f %.0f\n",
               (double)sites[i].lo[0], (double)sites[i].lo[1], (double)sites[i].lo[2],
               (double)sites[i].hi[0], (double)sites[i].hi[1], (double)sites[i].hi[2],
               (double)sites[i].reach, way_name[sites[i].way], (double)sites[i].stand[0],
               (double)sites[i].stand[1], (double)sites[i].stand[2]);
    free(sites);
    MapGenBsp_Free(bsp);
    return 0;
}
