/*
 * Where can a new room be dug into a map's rock beside a room it already has?
 *
 *     mapgen_chamber_census <map.bsp> [width depth height margin]
 *
 * Ledger row 309: q2dm1's walls can hardly be moved - behind most of them another
 * space lies within a carve's depth - so the PO's next stage looks for NEW space
 * instead, the way the tunnels already cut it. This counts where such space is.
 *
 * For every place a player can stand - a 32-unit lattice over the world model's
 * bounds, air over rock with `height` of headroom - and for each of the four ways,
 * the first rock within 64 units at a player's middle height: behind a 16-unit
 * wall there, a chamber `width` across, `depth` deep and `height` tall with its
 * floor at the standing floor, counted when the chamber grown by `margin` all round
 * is rock in the compiled map. The compiler's outside fill is rock here, as the
 * dig's shell treats it. Placements are de-duplicated on a 64-unit grid of the
 * chamber's middle and its way.
 *
 * Nothing is carved; the answer is how many new rooms the rock could take, and
 * where the first of them are.
 */

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"

#define MAX_PLACES 65536u

typedef struct {
    int32_t key[4];
    float   mid[3];
    float   floor_z;
    int     way;
} place_t;

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

/* Every 16 units inside the box, and the box's own corners: all rock? */
static bool box_is_rock(const mapgen_bsp_t *b, const float lo[3], const float hi[3])
{
    for (float x = lo[0]; x <= hi[0] + 0.5f; x += 16.0f)
        for (float y = lo[1]; y <= hi[1] + 0.5f; y += 16.0f)
            for (float z = lo[2]; z <= hi[2] + 0.5f; z += 16.0f)
                if (!rock_at(b, x > hi[0] ? hi[0] : x, y > hi[1] ? hi[1] : y,
                             z > hi[2] ? hi[2] : z))
                    return false;
    return true;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s map.bsp [width depth height margin]\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    const float width = argc > 2 ? strtof(argv[2], NULL) : 192.0f;
    const float depth = argc > 3 ? strtof(argv[3], NULL) : 192.0f;
    const float height = argc > 4 ? strtof(argv[4], NULL) : 128.0f;
    const float margin = argc > 5 ? strtof(argv[5], NULL) : 16.0f;
    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    if (!world) {
        fprintf(stderr, "no world model\n");
        return 2;
    }

    place_t *places = calloc(MAX_PLACES, sizeof(*places));
    uint32_t num_places = 0, standing = 0, standing_with = 0, walls = 0, tried = 0;
    uint32_t per_way[4] = { 0 };
    const int dx[4] = { 1, -1, 0, 0 }, dy[4] = { 0, 0, 1, -1 };
    const char *way_name[4] = { "+x", "-x", "+y", "-y" };

    for (float x = world->mins[0] + 16.0f; places && x < world->maxs[0]; x += 32.0f)
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
                for (float h = 8.0f; h <= height && clear; h += 16.0f)
                    clear = !rock_at(bsp, x, y, floor_z + h);
                if (!clear)
                    continue;
                standing++;
                bool any = false;
                for (int w = 0; w < 4; w++) {
                    /* the first rock within 64 at a player's middle height */
                    float face = -1.0f;
                    for (float s = 4.0f; s <= 64.0f; s += 4.0f)
                        if (rock_at(bsp, x + dx[w] * s, y + dy[w] * s, floor_z + 32.0f)) {
                            face = s;
                            break;
                        }
                    if (face < 0.0f)
                        continue;
                    walls++;
                    const float near = face + 16.0f, far = face + 16.0f + depth;
                    float lo[3], hi[3];
                    if (dx[w]) {
                        lo[0] = dx[w] > 0 ? x + near : x - far;
                        hi[0] = dx[w] > 0 ? x + far : x - near;
                        lo[1] = y - 0.5f * width;
                        hi[1] = y + 0.5f * width;
                    } else {
                        lo[1] = dy[w] > 0 ? y + near : y - far;
                        hi[1] = dy[w] > 0 ? y + far : y - near;
                        lo[0] = x - 0.5f * width;
                        hi[0] = x + 0.5f * width;
                    }
                    lo[2] = floor_z;
                    hi[2] = floor_z + height;
                    const float glo[3] = { lo[0] - margin, lo[1] - margin, lo[2] - margin };
                    const float ghi[3] = { hi[0] + margin, hi[1] + margin, hi[2] + margin };
                    tried++;
                    if (!box_is_rock(bsp, glo, ghi))
                        continue;
                    any = true;
                    const float mid[3] = { 0.5f * (lo[0] + hi[0]), 0.5f * (lo[1] + hi[1]),
                                           0.5f * (lo[2] + hi[2]) };
                    const int32_t key[4] = { (int32_t)floorf(mid[0] / 64.0f),
                                             (int32_t)floorf(mid[1] / 64.0f),
                                             (int32_t)floorf(mid[2] / 64.0f), w };
                    bool seen = false;
                    for (uint32_t i = 0; i < num_places && !seen; i++)
                        seen = !memcmp(places[i].key, key, sizeof(key));
                    if (seen || num_places >= MAX_PLACES)
                        continue;
                    memcpy(places[num_places].key, key, sizeof(key));
                    memcpy(places[num_places].mid, mid, sizeof(mid));
                    places[num_places].floor_z = floor_z;
                    places[num_places].way = w;
                    num_places++;
                    per_way[w]++;
                }
                standing_with += any ? 1u : 0u;
            }
        }

    printf("%s: chamber %.0f wide, %.0f deep, %.0f tall, %.0f of rock all round\n", argv[1],
           (double)width, (double)depth, (double)height, (double)margin);
    printf("%u standing places, %u of them beside a wall with room for one; %u walls, %u chambers"
           " tried\n", standing, standing_with, walls, tried);
    printf("%u distinct chambers: +x %u, -x %u, +y %u, -y %u\n", num_places, per_way[0],
           per_way[1], per_way[2], per_way[3]);
    for (uint32_t i = 0; places && i < num_places && i < 40u; i++)
        printf("  chamber at %.0f %.0f %.0f, floor %.0f, dug %s\n", (double)places[i].mid[0],
               (double)places[i].mid[1], (double)places[i].mid[2], (double)places[i].floor_z,
               way_name[places[i].way]);
    free(places);
    MapGenBsp_Free(bsp);
    return 0;
}
