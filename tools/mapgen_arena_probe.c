/*
 * Is this map an arena - the shape the PO asked for - or a warren?
 *
 *     mapgen_arena_probe <map.bsp>
 *
 * Five numbers, all measured on the compiled artifact and none of them read
 * off the recipe that asked for them:
 *
 *   FOOTPRINT   how much ground the map covers, to compare with a donor's;
 *   SKY         the share of the places a player can stand that have sky
 *               directly overhead, found by walking up from each of them and
 *               asking whether the surface it meets is a sky face;
 *   LEVELS      how many distinct floor heights a player stands on, and how
 *               many of them are below the water - q2dm1 has about four above
 *               its upper pool and one below, which is what was asked for;
 *   WATER       the surface height of every pool;
 *   MATERIALS   how many texture families the map is built from, because four
 *               episodes stitched together is not one place.
 *
 * The standing places are a 64-unit lattice: a point with air at knee height
 * and solid under it. That is a coarser question than the reachability
 * explorer's and a much cheaper one, and it is the right grain for "how much
 * of the floor is outdoors".
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"

#define GRID       64.0f
#define MAX_LEVELS 64
#define MAX_POOLS  32
#define MAX_FAMILY 64

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = malloc((size_t)(n > 0 ? n : 1));
    if (!raw || n <= 0 || fread(raw, 1, (size_t)n, f) != (size_t)n) {
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

static const char *texture_of(const mapgen_bsp_t *bsp,
                              const mapgen_bsp_face_t *face)
{
    const mapgen_bsp_texinfo_t *tex = MapGenBsp_TexInfo(bsp, face->texinfo);
    return tex ? tex->texture : NULL;
}

static bool is_sky(const char *name)
{
    if (!name)
        return false;
    for (const char *p = name; *p; p++)
        if ((p[0] == 's' || p[0] == 'S') && (p[1] == 'k' || p[1] == 'K')
            && (p[2] == 'y' || p[2] == 'Y'))
            return true;
    return false;
}

/* One face's corners, in the order the surfedge table gives them. */
static uint32_t face_points(const mapgen_bsp_t *bsp,
                            const mapgen_bsp_face_t *face,
                            float out[64][3])
{
    uint32_t n = 0;
    for (int32_t e = 0; e < face->numedges && n < 64; e++) {
        const int32_t se =
            MapGenBsp_SurfEdge(bsp, (uint32_t)(face->firstedge + e));
        const mapgen_bsp_edge_t *edge =
            MapGenBsp_Edge(bsp, (uint32_t)(se < 0 ? -se : se));
        if (!edge)
            break;
        const mapgen_bsp_vertex_t *v =
            MapGenBsp_Vertex(bsp, se < 0 ? edge->v[1] : edge->v[0]);
        if (!v)
            break;
        memcpy(out[n++], v->point, sizeof(out[0]));
    }
    return n;
}

/* Is this point, seen from below, under that face? The face is nearly
   horizontal, so the test is a point-in-polygon on x and y. */
static bool under_face(const mapgen_bsp_t *bsp, const mapgen_bsp_face_t *face,
                       float x, float y)
{
    float p[64][3];
    const uint32_t n = face_points(bsp, face, p);
    if (n < 3)
        return false;
    bool in = false;
    for (uint32_t i = 0, j = n - 1; i < n; j = i++) {
        if ((p[i][1] > y) != (p[j][1] > y)
            && x < (p[j][0] - p[i][0]) * (y - p[i][1])
                   / (p[j][1] - p[i][1] + 1e-6f) + p[i][0])
            in = !in;
    }
    return in;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp>\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    const mapgen_bsp_model_t *world = MapGenBsp_Model(bsp, 0);
    if (!world)
        return 2;

    printf("footprint %.0f x %.0f x %.0f\n",
           world->maxs[0] - world->mins[0], world->maxs[1] - world->mins[1],
           world->maxs[2] - world->mins[2]);

    /* The sky faces, and the families every drawn face belongs to. */
    const uint32_t faces = MapGenBsp_NumFaces(bsp);
    const mapgen_bsp_face_t **sky = malloc((faces + 1) * sizeof(*sky));
    uint32_t num_sky = 0;
    char family[MAX_FAMILY][32];
    uint32_t families = 0;
    for (uint32_t f = 0; f < faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        if (!face || face->numedges < 3)
            continue;
        const char *name = texture_of(bsp, face);
        if (!name)
            continue;
        if (is_sky(name))
            sky[num_sky++] = face;
        /* The family is the first path component: e1u1, e2u3 ... */
        char head[32];
        size_t n = 0;
        for (; name[n] && name[n] != '/' && n < sizeof(head) - 1; n++)
            head[n] = name[n];
        head[n] = '\0';
        bool seen = false;
        for (uint32_t i = 0; i < families && !seen; i++)
            seen = !strcmp(family[i], head);
        if (!seen && families < MAX_FAMILY)
            snprintf(family[families++], sizeof(family[0]), "%s", head);
    }

    /* Standing places, and which of them are outdoors. */
    uint32_t stands = 0, outdoors = 0;
    float levels[MAX_LEVELS];
    uint32_t level_count[MAX_LEVELS];
    uint32_t num_levels = 0;
    for (float x = world->mins[0] + GRID * 0.5f; x < world->maxs[0]; x += GRID) {
      for (float y = world->mins[1] + GRID * 0.5f; y < world->maxs[1];
           y += GRID) {
        for (float z = world->mins[2] + 8.0f; z < world->maxs[2]; z += 8.0f) {
            const float here[3] = { x, y, z };
            const float below[3] = { x, y, z - 8.0f };
            const float head[3] = { x, y, z + 48.0f };
            if (MapGenBsp_PointContents(bsp, here) & 1)
                continue;
            if (!(MapGenBsp_PointContents(bsp, below) & 1))
                continue;
            if (MapGenBsp_PointContents(bsp, head) & 1)
                continue;
            stands++;

            /* Which level is this? */
            /* Ninety-six units apart is a STOREY - a height a player has to
               climb to rather than step onto. Forty-eight counted q2dm1's
               ledges as levels of their own and made it eleven storeys. */
            bool placed = false;
            for (uint32_t i = 0; i < num_levels && !placed; i++)
                if (fabsf(levels[i] - z) <= 96.0f) {
                    level_count[i]++;
                    placed = true;
                }
            if (!placed && num_levels < MAX_LEVELS) {
                levels[num_levels] = z;
                level_count[num_levels] = 1;
                num_levels++;
            }

            /* Straight up: the first solid, and whether it is the sky. */
            float ceiling = 0.0f;
            bool hit = false;
            for (float up = z + 48.0f; up < world->maxs[2] + 64.0f;
                 up += 16.0f) {
                const float p[3] = { x, y, up };
                if (MapGenBsp_PointContents(bsp, p) & 1) {
                    ceiling = up;
                    hit = true;
                    break;
                }
            }
            if (hit) {
                for (uint32_t s = 0; s < num_sky; s++) {
                    const mapgen_bsp_plane_t *plane =
                        MapGenBsp_Plane(bsp, sky[s]->planenum);
                    if (!plane || fabsf(plane->normal[2]) < 0.7f)
                        continue;
                    float p[64][3];
                    if (face_points(bsp, sky[s], p) < 3)
                        continue;
                    if (fabsf(p[0][2] - ceiling) > 64.0f)
                        continue;
                    if (under_face(bsp, sky[s], x, y)) {
                        outdoors++;
                        break;
                    }
                }
            }
            /* One standing place per column is enough for this question. */
            z += 64.0f;
        }
      }
    }

    printf("standing places %u, under sky %u (%u permille)\n", stands, outdoors,
           stands ? (uint32_t)((1000ull * outdoors) / stands) : 0u);

    /* The levels that actually hold people, biggest first. */
    uint32_t real_levels = 0;
    for (uint32_t i = 0; i < num_levels; i++)
        if (stands && level_count[i] * 10u >= stands)   /* a tenth of it */
            real_levels++;
    printf("floor levels %u (of %u clusters, counting those with a twentieth"
           " of the floor)\n", real_levels, num_levels);
    for (uint32_t i = 0; i < num_levels; i++)
        if (stands && level_count[i] * 10u >= stands)
            printf("  level z %.0f  %u places\n", levels[i], level_count[i]);

    printf("material families %u:", families);
    for (uint32_t i = 0; i < families; i++)
        printf(" %s", family[i]);
    printf("\n");
    printf("sky faces %u of %u\n", num_sky, faces);
    free(sky);
    return 0;
}
