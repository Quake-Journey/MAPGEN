/*
 * What the corpus has that could BE an arena.
 *
 *     mapgen_arena_stock MAP.bsp [MAP.bsp ...]
 *
 * The invented map of 2026-09-07 was a box on a grid with tubes between it,
 * and the PO said so in as many words. The material for a better one is
 * already in the reference maps: rooms that were BUILT - ledges, walkways,
 * buttresses, a bridge - and the survey can lift them out. This says which
 * ones are worth lifting, and what stands in the way of lifting the big ones.
 *
 * Per room:
 *
 *     room N  <box>  air A  brushes B  sockets S  sky F  <sealed> <movable>
 *              spread D  storeys T  planes P
 *
 * where `sky` counts the faces of the room's own brushes painted sky, and
 * `spread`, `storeys` and `planes` are the arena measures of
 * check_mapgen_arena_shape.py applied to this room alone: how far its floors
 * are spread, over how many levels, and how many different wall planes a
 * player inside it looks at.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_bundle.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_compose.h"
#include "common/mapgen_rooms.h"

#define SURF_SKY_BIT 0x4
#define MAX_PLACES   20000u
#define GRID         32.0f

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

/* How many of this room's own brushes carry a face painted sky. */
static uint32_t sky_faces(const mapgen_geometry_t *g, const mapgen_bundle_t *b)
{
    uint32_t n = 0;
    for (uint32_t i = 0; i < MapGenBundle_NumBrushes(b); i++) {
        const mapgen_bundle_brush_t *bb = MapGenBundle_Brush(b, i);
        if (!bb)
            continue;
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(g, bb->brush);
        if (!br)
            continue;
        for (uint32_t s = 0; s < br->num_sides; s++) {
            const mapgen_geometry_side_t *side =
                MapGenGeometry_Side(g, br->first_side + s);
            if (side && (side->flags & SURF_SKY_BIT))
                n++;
        }
    }
    return n;
}

/* The floors inside this room, and the walls a player in it can see. */
static void shape_of(const mapgen_bsp_t *bsp, const float lo[3],
                     const float hi[3], float *out_spread,
                     uint32_t *out_storeys, uint32_t *out_planes,
                     uint32_t *out_places)
{
    static float places[MAX_PLACES][3];
    const uint32_t found =
        MapGenBsp_PlacesIn(bsp, lo, hi, GRID, places, MAX_PLACES);
    const uint32_t n = found < MAX_PLACES ? found : MAX_PLACES;
    *out_places = n;
    *out_spread = 0.0f;
    *out_storeys = 0;
    *out_planes = 0;
    if (!n)
        return;

    float low = places[0][2], high = places[0][2];
    for (uint32_t i = 1; i < n; i++) {
        if (places[i][2] < low)
            low = places[i][2];
        if (places[i][2] > high)
            high = places[i][2];
    }
    *out_spread = high - low;

    /* A storey is a band 96 units deep holding at least a twentieth. */
    const uint32_t need = n / 20u;
    for (float z = low; z <= high; z += 96.0f) {
        uint32_t here = 0;
        for (uint32_t i = 0; i < n; i++)
            if (places[i][2] >= z && places[i][2] < z + 96.0f)
                here++;
        if (here > need)
            (*out_storeys)++;
    }

    /* The distinct planes of the faces inside this box. */
    float seen[512][4];
    uint32_t planes = 0;
    for (uint32_t f = 0; f < MapGenBsp_NumFaces(bsp) && planes < 512; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(bsp, f);
        if (!face || face->numedges < 3)
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(bsp, face->planenum);
        if (!pl || fabsf(pl->normal[2]) > 0.5f)
            continue;
        float mid[3] = { 0, 0, 0 };
        uint32_t got = 0;
        for (int32_t e = 0; e < face->numedges; e++) {
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
            for (int a = 0; a < 3; a++)
                mid[a] += v->point[a];
            got++;
        }
        if (got < 3)
            continue;
        for (int a = 0; a < 3; a++)
            mid[a] /= (float)got;
        if (mid[0] < lo[0] || mid[0] > hi[0] || mid[1] < lo[1]
            || mid[1] > hi[1] || mid[2] < lo[2] || mid[2] > hi[2])
            continue;
        bool known = false;
        for (uint32_t k = 0; k < planes && !known; k++)
            known = fabsf(seen[k][0] - pl->normal[0]) < 0.01f
                 && fabsf(seen[k][1] - pl->normal[1]) < 0.01f
                 && fabsf(seen[k][2] - pl->normal[2]) < 0.01f
                 && fabsf(seen[k][3] - pl->dist) < 1.0f;
        if (known)
            continue;
        seen[planes][0] = pl->normal[0];
        seen[planes][1] = pl->normal[1];
        seen[planes][2] = pl->normal[2];
        seen[planes][3] = pl->dist;
        planes++;
    }
    *out_planes = planes;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s MAP.bsp [MAP.bsp ...]\n", argv[0]);
        return 2;
    }
    for (int a = 1; a < argc; a++) {
        mapgen_bsp_t *bsp = load(argv[a]);
        mapgen_geometry_t *geo = NULL;
        mapgen_rooms_t *rooms = NULL;
        mapgen_bundle_set_t *set = NULL;
        if (!bsp || MapGenGeometry_FromBsp(bsp, &geo) != MAPGEN_GEOMETRY_OK
            || MapGenRooms_Find(bsp, 64.0f, MAPGEN_ROOMS_PERSISTENCE, &rooms)
               != MAPGEN_ROOMS_OK
            || MapGenBundle_Survey(bsp, geo, rooms, &set) != MAPGEN_BUNDLE_OK) {
            fprintf(stderr, "cannot survey %s\n", argv[a]);
            continue;
        }
        printf("%s\n", argv[a]);
        for (uint32_t r = 0; r < MapGenBundleSet_Count(set); r++) {
            const mapgen_bundle_t *b = MapGenBundleSet_At(set, r);
            if (!b)
                continue;
            const float *lo = MapGenBundle_Mins(b);
            const float *hi = MapGenBundle_Maxs(b);
            if (!lo || !hi)
                continue;
            float spread = 0.0f;
            uint32_t storeys = 0, planes = 0, places = 0;
            shape_of(bsp, lo, hi, &spread, &storeys, &planes, &places);
            printf("  room %3u  %.0f %.0f %.0f .. %.0f %.0f %.0f"
                   "  size %.0f x %.0f x %.0f"
                   "  air %5u brushes %4u sockets %2u sky %3u"
                   "  %s %s  places %4u spread %4.0f storeys %u planes %3u\n",
                   r, lo[0], lo[1], lo[2], hi[0], hi[1], hi[2],
                   hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2],
                   MapGenBundle_AirCells(b), MapGenBundle_NumBrushes(b),
                   MapGenBundle_NumSockets(b), sky_faces(geo, b),
                   MapGenBundle_Sealed(b) ? "sealed" : "OPEN  ",
                   !MapGenCompose_Carriable(geo, b) ? "machined"
                       : MapGenBundle_Movable(b) ? "movable" : "fixed   ",
                   places, spread, storeys, planes);
        }
        MapGenBundleSet_Free(set);
        MapGenRooms_Free(rooms);
        MapGenGeometry_Free(geo);
        MapGenBsp_Free(bsp);
    }
    return 0;
}
