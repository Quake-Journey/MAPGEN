/*
 * An invented map composed of rooms that were built. See mapgen_compose.h.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_compose.h"
#include "common/mapgen_bsp.h"
#include "common/mapgen_bundle.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_graft.h"
#include "common/mapgen_rooms.h"
#include "common/mapgen_trace.h"

#define CONTENTS_SOLID_BIT 0x00000001
#define SURF_SKY_BIT       0x00000004

#define CELL         16.0f
#define GAP         192.0f   /* rock between the arena and a pocket        */
#define WAY_WIDE    128.0f   /* a way in, a player and a half wide         */
#define WAY_TALL    160.0f
#define WAY_REACH   1024u    /* how far in a way may look for open space   */
#define MARGIN      128.0f   /* rock around everything                     */
#define CLIP_SLOP    64.0f   /* how much of a carried wall comes with it   */
#define CLIP_REACH 32768.0f

/*
 * What an ARENA is, and it is the contract of check_mapgen_arena_shape.py
 * asked of the material before it is carried rather than of the map after.
 *
 * MEASURED over the whole corpus, room by room: not one room in it answers
 * to the contract. q2dm8's yard is 1216 by 896 and indoors; q2dm2's hall is
 * 832 wide; q2dm1's courtyard is 1184 by 1696 and IS an arena, but it is
 * q2dm1's own and a map made of it is q2dm1. What does answer, in every
 * reference map, is the set of rooms that are open to the SKY taken
 * together: q2dm2's outdoors is 1504 by 1600 over five storeys with a
 * hundred and ninety-five wall planes, q2dm3's is 1824 by 1568. That is the
 * unit this composes with - a donor's outdoors, carried whole, with its own
 * sky on its own brushes.
 *
 * The sky is a condition and not a nicety: a room that was INDOORS stays
 * indoors when its roof is cut off, because its ledges were built with a
 * storey over them and nothing under them can see out.
 */
#define ARENA_MIN_X  1024.0f
#define ARENA_MIN_Y  1024.0f
#define ARENA_STOREYS     3u
#define ARENA_PLANES     40u
#define ARENA_SPREAD 384.0f
#define ROOM_SKY          8u    /* faces of sky that make a room outdoor   */

#define POCKET_MIN_AIR  400u
#define POCKET_MAX_AIR 3200u

#define WANT_X      2496.0f  /* q2dm1's own footprint, which is the target */
#define WANT_Y      2272.0f
#define WANT_SLACK     0.25f

#define MAX_CELLS  8000000u
#define MAX_SHELL     8000u
#define PLACE_CAP    20000u
#define GRID          32.0f
#define MAX_GROUP        24u

#define WANT_SPAWNS      8u

const char *MapGenCompose_ResultName(mapgen_compose_result_t r)
{
    switch (r) {
    case MAPGEN_COMPOSE_OK:          return "ok";
    case MAPGEN_COMPOSE_ERR_ARGS:    return "args";
    case MAPGEN_COMPOSE_ERR_MEMORY:  return "memory";
    case MAPGEN_COMPOSE_ERR_DONOR:   return "donor";
    case MAPGEN_COMPOSE_ERR_STOCK:   return "stock";
    case MAPGEN_COMPOSE_ERR_BUILD:   return "build";
    default:                         return "?";
    }
}

/* The same mixer the edit schedule deals from, so a composition is a
   property of its seed and of nothing else. */
static uint64_t mix(uint64_t *state)
{
    uint64_t x = (*state += 0x9E3779B97F4A7C15ull);
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ull;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBull;
    return x ^ (x >> 31);
}

/* ------------------------------------------------------------------ donors */

typedef struct {
    char                  name[MAPGEN_COMPOSE_NAME];
    mapgen_bsp_t         *bsp;
    mapgen_geometry_t    *geo;
    mapgen_rooms_t       *rooms;
    mapgen_bundle_set_t  *set;
} donor_t;

static mapgen_bsp_t *load_bsp(const char *path)
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

static void donor_free(donor_t *d)
{
    MapGenBundleSet_Free(d->set);
    MapGenRooms_Free(d->rooms);
    MapGenGeometry_Free(d->geo);
    MapGenBsp_Free(d->bsp);
    memset(d, 0, sizeof(*d));
}

static const char *base_name(const char *path)
{
    const char *slash = path;
    for (const char *p = path; *p; p++)
        if (*p == '/' || *p == '\\')
            slash = p + 1;
    return slash;
}

/* ------------------------------------------------------------- measuring */

typedef struct {
    uint32_t places;
    uint32_t storeys;
    uint32_t planes;
    float    spread;
    float    floor_z;
    float    air_top;
} shape_t;

/*
 * Is this somewhere a player would call OUTDOORS?
 *
 * The arena probe's own question, asked at four elevations: at one of them,
 * half the compass has to end in sky. MEASURED, and this is why the cheaper
 * question will not do: q2dm3's outdoor rooms measure 1824 by 1568 over four
 * storeys with eighty-eight wall planes when every standing place in the box
 * is counted, and the map they compose into has an open volume sixteen units
 * deep, because almost none of those places can see out. An arena has to be
 * judged by the places that are IN it.
 */
#define SKY_AZ    16
#define SKY_REACH 8192.0f

static bool outdoors(mapgen_trace_context_t *ctx, const float place[3])
{
    static const float EL[4] = { 0.0f, 15.0f, 30.0f, 45.0f };
    const float eye[3] = { place[0], place[1], place[2] + 40.0f };
    for (int e = 0; e < 4; e++) {
        const float el = EL[e] * 3.14159265358979323846f / 180.0f;
        int sky = 0;
        for (int a = 0; a < SKY_AZ; a++) {
            const float az = (float)a * 2.0f * 3.14159265358979323846f
                           / (float)SKY_AZ;
            const float to[3] = {
                eye[0] + cosf(az) * cosf(el) * SKY_REACH,
                eye[1] + sinf(az) * cosf(el) * SKY_REACH,
                eye[2] + sinf(el) * SKY_REACH,
            };
            const float zero[3] = { 0, 0, 0 };
            mapgen_trace_result_t hit;
            MapGenTrace_Box(ctx, eye, to, zero, zero, MAPGEN_TRACE_SOLID, &hit);
            if (hit.fraction < 0.999f && (hit.surface_flags & SURF_SKY_BIT))
                sky++;
        }
        if (sky * 2 >= SKY_AZ)
            return true;
    }
    return false;
}

/*
 * The floors inside a box and the walls a player in it looks at: the arena
 * measures of check_mapgen_arena_shape.py asked of a piece of a map, over the
 * places that are outdoors in it.
 */
static void shape_of(const mapgen_bsp_t *bsp, const float lo[3],
                     const float hi[3], shape_t *out)
{
    memset(out, 0, sizeof(*out));
    out->air_top = lo[2];
    for (float z = hi[2] - 8.0f; z > lo[2]; z -= 8.0f) {
        bool any = false;
        for (float x = lo[0] + 32.0f; x < hi[0] && !any; x += 64.0f)
          for (float y = lo[1] + 32.0f; y < hi[1] && !any; y += 64.0f) {
            const float p[3] = { x, y, z };
            any = !(MapGenBsp_PointContents(bsp, p) & CONTENTS_SOLID_BIT);
          }
        if (any) {
            out->air_top = z;
            break;
        }
    }

    float (*places)[3] = malloc(sizeof(*places) * PLACE_CAP);
    if (!places)
        return;
    const uint32_t found =
        MapGenBsp_PlacesIn(bsp, lo, hi, GRID, places, PLACE_CAP);
    uint32_t n = found < PLACE_CAP ? found : PLACE_CAP;

    mapgen_trace_context_t ctx;
    memset(&ctx, 0, sizeof(ctx));
    if (MapGenTrace_Bind(&ctx, bsp)) {
        uint32_t kept = 0;
        for (uint32_t i = 0; i < n; i++)
            if (outdoors(&ctx, places[i]))
                memcpy(places[kept++], places[i], sizeof(places[0]));
        n = kept;
        MapGenTrace_Release(&ctx);
    }

    out->places = n;
    if (n) {
        float low = places[0][2], high = places[0][2];
        for (uint32_t i = 1; i < n; i++) {
            if (places[i][2] < low)
                low = places[i][2];
            if (places[i][2] > high)
                high = places[i][2];
        }
        out->spread = high - low;
        out->floor_z = low;
        const uint32_t need = n / 20u;
        for (float z = low; z <= high; z += 96.0f) {
            uint32_t here = 0;
            for (uint32_t i = 0; i < n; i++)
                if (places[i][2] >= z && places[i][2] < z + 96.0f)
                    here++;
            if (here > need)
                out->storeys++;
        }
    }
    free(places);

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
    out->planes = planes;
}

/*
 * Can this room be carried at all?
 *
 * A brush model is a machine - a lift, a door - and the entity that owns it
 * refers to it by NUMBER, so a room whose own GEOMETRY is a machine cannot be
 * carried into a map whose models are numbered differently without carrying
 * the numbering too.
 *
 * MEASURED on the corpus: refusing a room that merely MENTIONS a machine - an
 * anchor of a lift or a trigger, which a bundle collects through the target
 * closure and which can belong three rooms away - leaves nothing at all.
 * q2dm1's courtyard, q2dm2's hall, q2dm8's yard and every other room worth
 * composing with mentions one. What the composer does instead is leave the
 * machines behind: an entity that owns a brush model is not carried, and
 * neither is the model, so what arrives is the room's own architecture.
 */
bool MapGenCompose_Carriable(const mapgen_geometry_t *g,
                             const mapgen_bundle_t *b)
{
    uint32_t world = 0;
    for (uint32_t i = 0; i < MapGenBundle_NumBrushes(b); i++) {
        const mapgen_bundle_brush_t *bb = MapGenBundle_Brush(b, i);
        if (!bb)
            return false;
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(g, bb->brush);
        if (!br)
            return false;
        if (!br->model)
            world++;
    }
    /* Something has to arrive, and it has to be the room rather than the
       fittings that were standing in it. */
    return world >= 8;
}

/* ------------------------------------------------------------ the lattice */

typedef struct {
    int32_t lo[3];
    int32_t n[3];
    uint8_t *bit;
} grid_t;

static bool grid_make(grid_t *g, const float lo[3], const float hi[3])
{
    for (int a = 0; a < 3; a++) {
        g->lo[a] = (int32_t)floorf(lo[a] / CELL);
        g->n[a] = (int32_t)ceilf(hi[a] / CELL) - g->lo[a];
        if (g->n[a] <= 0)
            return false;
    }
    if ((uint64_t)g->n[0] * g->n[1] * g->n[2] > MAX_CELLS)
        return false;
    g->bit = calloc((size_t)g->n[0] * g->n[1] * g->n[2], 1);
    return g->bit != NULL;
}

static size_t grid_at(const grid_t *g, int32_t x, int32_t y, int32_t z)
{
    return (((size_t)(z - g->lo[2]) * g->n[1]) + (y - g->lo[1])) * g->n[0]
           + (x - g->lo[0]);
}

static bool grid_in(const grid_t *g, int32_t x, int32_t y, int32_t z)
{
    return x >= g->lo[0] && x < g->lo[0] + g->n[0]
        && y >= g->lo[1] && y < g->lo[1] + g->n[1]
        && z >= g->lo[2] && z < g->lo[2] + g->n[2];
}

static void grid_box(grid_t *g, const float lo[3], const float hi[3],
                     uint8_t value)
{
    for (int32_t z = (int32_t)floorf(lo[2] / CELL);
         z < (int32_t)ceilf(hi[2] / CELL); z++)
      for (int32_t y = (int32_t)floorf(lo[1] / CELL);
           y < (int32_t)ceilf(hi[1] / CELL); y++)
        for (int32_t x = (int32_t)floorf(lo[0] / CELL);
             x < (int32_t)ceilf(hi[0] / CELL); x++)
            if (grid_in(g, x, y, z))
                g->bit[grid_at(g, x, y, z)] = value;
}

/*
 * Which cells the composed geometry fills, asked BRUSH by brush.
 *
 * Cell by cell it would be a million points against a thousand brushes; brush
 * by brush it is the volume of the map, once.
 */
static void mark_solid(grid_t *g, const mapgen_geometry_t *geo)
{
    for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(geo); b++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(geo, b);
        if (!br || br->model != 0 || !(br->contents & CONTENTS_SOLID_BIT))
            continue;
        for (int32_t z = (int32_t)floorf(br->mins[2] / CELL);
             z < (int32_t)ceilf(br->maxs[2] / CELL); z++)
          for (int32_t y = (int32_t)floorf(br->mins[1] / CELL);
               y < (int32_t)ceilf(br->maxs[1] / CELL); y++)
            for (int32_t x = (int32_t)floorf(br->mins[0] / CELL);
                 x < (int32_t)ceilf(br->maxs[0] / CELL); x++) {
                if (!grid_in(g, x, y, z) || g->bit[grid_at(g, x, y, z)])
                    continue;
                const float p[3] = { ((float)x + 0.5f) * CELL,
                                     ((float)y + 0.5f) * CELL,
                                     ((float)z + 0.5f) * CELL };
                bool inside = true;
                for (uint32_t s = 0; s < br->num_sides && inside; s++) {
                    const mapgen_geometry_side_t *side =
                        MapGenGeometry_Side(geo, br->first_side + s);
                    if (!side || side->bevel)
                        continue;
                    inside = side->normal[0] * p[0] + side->normal[1] * p[1]
                           + side->normal[2] * p[2] - side->dist <= 0.0f;
                }
                if (inside)
                    g->bit[grid_at(g, x, y, z)] = 1;
            }
    }
}

/* --------------------------------------------------------------- brushes */

static void plane_of(mapgen_geometry_side_t *side,
                     const mapgen_geometry_side_t *skin,
                     float nx, float ny, float nz, float dist)
{
    memset(side, 0, sizeof(*side));
    side->normal[0] = nx;
    side->normal[1] = ny;
    side->normal[2] = nz;
    side->dist = dist;
    memcpy(side->texture, skin->texture, sizeof(side->texture));
    side->flags = skin->flags;
    side->value = skin->value;
    MapGenGeometry_AxesForNormal(side->axis, side->normal);
}

static bool add_box(mapgen_geometry_t *g, const mapgen_geometry_side_t *skin,
                    const float mins[3], const float maxs[3])
{
    mapgen_geometry_side_t sides[6];
    plane_of(&sides[0], skin, 0, 0, -1.0f, -mins[2]);
    plane_of(&sides[1], skin, 0, 0, 1.0f, maxs[2]);
    plane_of(&sides[2], skin, -1.0f, 0, 0, -mins[0]);
    plane_of(&sides[3], skin, 1.0f, 0, 0, maxs[0]);
    plane_of(&sides[4], skin, 0, -1.0f, 0, -mins[1]);
    plane_of(&sides[5], skin, 0, 1.0f, 0, maxs[1]);
    return MapGenGeometry_AddBrush(g, sides, 6, CONTENTS_SOLID_BIT, 0)
           == MAPGEN_GEOMETRY_OK;
}

/* A wall to build with, taken from the references rather than invented: the
   corpus is what the map is made of. */
static bool borrow(const mapgen_geometry_t *g, mapgen_geometry_side_t *out)
{
    const mapgen_geometry_side_t *best = NULL;
    for (uint32_t s = 0; s < MapGenGeometry_NumSides(g); s++) {
        const mapgen_geometry_side_t *side = MapGenGeometry_Side(g, s);
        if (!side || side->bevel || !side->texture[0] || side->flags)
            continue;
        if (!best || side->area > best->area)
            best = side;
    }
    if (!best)
        return false;
    *out = *best;
    return true;
}

/* ------------------------------------------------------------------ parts */

typedef struct {
    uint32_t donor;
    uint32_t room[MAX_GROUP];
    uint32_t rooms;
    float    box_lo[3];      /* the rooms' own box, in donor coordinates */
    float    box_hi[3];
    bool     clip;           /* trim what it brings to that box           */
    bool     machines;       /* and bring its lifts and doors with it      */
    bool     by_box;         /* everything of the donor's inside its box   */
    shape_t  shape;
    uint32_t sky;
    uint32_t air;
    bool     movable;

    uint32_t quarter_turns;
    bool     mirror_x;
    float    size[3];        /* after the turn */
    float    at[3];          /* where its box's low corner goes */
    int      side;           /* 0 +x, 1 -x, 2 +y, 3 -y; -1 for the arena */
    float    way_z;          /* the floor the way into it runs at         */
} part_t;

static void turned_size(const part_t *p, uint32_t turns, float out[3])
{
    const float sx = p->box_hi[0] - p->box_lo[0];
    const float sy = p->box_hi[1] - p->box_lo[1];
    out[0] = (turns & 1u) ? sy : sx;
    out[1] = (turns & 1u) ? sx : sy;
    out[2] = p->box_hi[2] - p->box_lo[2];
}

/*
 * Everything outside a box goes.
 *
 * MEASURED on the first composition: a room's own shell brushes are the MAP's
 * walls where they touch it, and q2dm1's are slabs two thousand units long.
 * Carried whole they put the composed map's footprint at 3312 by 2864 where
 * q2dm1's is 2496 by 2272, and they were nowhere near anything the map was
 * going to use. So a piece arrives clipped to its own box with a wall's
 * thickness to spare, and what seals it beyond that is the shell.
 */
static void clip_to_box(mapgen_geometry_t *g, const float lo[3],
                        const float hi[3])
{
    for (int axis = 0; axis < 3; axis++)
      for (int dir = 0; dir < 2; dir++) {
        float rlo[3], rhi[3];
        for (int a = 0; a < 3; a++) {
            rlo[a] = lo[a] - CLIP_REACH;
            rhi[a] = hi[a] + CLIP_REACH;
        }
        if (dir)
            rlo[axis] = hi[axis];
        else
            rhi[axis] = lo[axis];
        MapGenGraft_Hollow(g, rlo, rhi);
      }
}

/*
 * Which brushes and entities a piece carries.
 *
 * The ARENA brings everything of its own, machines included. MEASURED on the
 * first composition that passed the shape gate: leaving q2dm1's lifts and
 * doors behind left five and a half thousand places a player could get into
 * and not out of, and four pickups nobody could reach - because a lift is
 * not a fitting standing in a room, it is the way up out of it.
 *
 * A brush model is referred to by NUMBER, so only one piece may bring
 * machines: the arena, which is carried first into an empty map where every
 * number is still free. A pocket brings its architecture and leaves its
 * machinery, and an entity of a pocket that talks to something left behind
 * is not carried at all.
 */
static bool piece_mask(const donor_t *d, const part_t *p, uint8_t *bm,
                       uint8_t *em)
{
    const uint32_t nb = MapGenGeometry_NumBrushes(d->geo);
    const uint32_t ne = MapGenGeometry_NumEntities(d->geo);
    if (p->by_box) {
        /*
         * Everything of the donor's that is in that box, room or no room.
         *
         * MEASURED: carrying the arena's ROOMS and opening the donor's air
         * left three hundred and sixty-eight places a player could drop into
         * and not climb out of, because a room whose box straddles the
         * arena's edge was not carried and its FLOOR went with it - the space
         * stayed open and the ground under it did not come. A yard is
         * everything that is in it.
         */
        for (uint32_t i = 0; i < nb; i++) {
            const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(d->geo, i);
            if (!br)
                continue;
            bool touches = true;
            for (int a = 0; a < 3 && touches; a++)
                touches = br->maxs[a] > p->box_lo[a]
                       && br->mins[a] < p->box_hi[a];
            if (touches)
                bm[i] = 1;
        }
        for (uint32_t i = 0; i < ne; i++) {
            const mapgen_geometry_entity_t *e =
                MapGenGeometry_Entity(d->geo, i);
            if (!e)
                continue;
            if (e->model) {
                em[i] = 1;      /* it goes with the brushes it owns */
                continue;
            }
            if (!e->has_origin)
                continue;
            bool inside = true;
            for (int a = 0; a < 3 && inside; a++)
                inside = e->origin[a] >= p->box_lo[a]
                      && e->origin[a] <= p->box_hi[a];
            if (inside)
                em[i] = 1;
        }
        return true;
    }
    for (uint32_t r = 0; r < p->rooms; r++) {
        const mapgen_bundle_t *b = MapGenBundleSet_At(d->set, p->room[r]);
        if (!b)
            continue;
        for (uint32_t i = 0; i < nb; i++) {
            const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(d->geo, i);
            if (!br || !MapGenBundle_OwnsBrush(b, i))
                continue;
            if (br->model && !p->machines)
                continue;
            bm[i] = 1;
        }
        for (uint32_t i = 0; i < ne; i++) {
            const mapgen_geometry_entity_t *e =
                MapGenGeometry_Entity(d->geo, i);
            if (!e || !MapGenBundle_OwnsEntity(b, i))
                continue;
            if (e->model && !p->machines)
                continue;
            if (!p->machines
                && (MapGenGeometry_EntityValue(d->geo, i, "target")
                    || MapGenGeometry_EntityValue(d->geo, i, "targetname")))
                continue;
            em[i] = 1;
        }
    }
    return true;
}

/*
 * And how much SPACE that comes to, which is not the rooms' box.
 *
 * MEASURED on q2dm1: the eight rooms of its outdoors fit in 2208 by 1920,
 * and the brushes those rooms own reach 2496 by 2272 - the map's own
 * footprint - because the outermost of them are the map's outer wall and its
 * sky. Trimming the arena to the rooms' box takes its sky with it: thirteen
 * rays in a thousand found any, where q2dm1 answers two hundred and five.
 * So an arena is carried whole and it is the POCKETS that get trimmed.
 */
static void piece_extent(const donor_t *d, const part_t *p, float lo[3],
                         float hi[3])
{
    const uint32_t nb = MapGenGeometry_NumBrushes(d->geo);
    uint8_t *bm = calloc(nb ? nb : 1, 1);
    uint8_t *em = calloc(MapGenGeometry_NumEntities(d->geo) + 1, 1);
    bool any = false;
    if (bm && em) {
        piece_mask(d, p, bm, em);
        for (uint32_t i = 0; i < nb; i++) {
            if (!bm[i])
                continue;
            const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(d->geo, i);
            if (!br)
                continue;
            for (int a = 0; a < 3; a++) {
                if (!any || br->mins[a] < lo[a])
                    lo[a] = br->mins[a];
                if (!any || br->maxs[a] > hi[a])
                    hi[a] = br->maxs[a];
            }
            any = true;
        }
    }
    free(bm);
    free(em);
    if (!any) {
        memcpy(lo, p->box_lo, sizeof(float) * 3);
        memcpy(hi, p->box_hi, sizeof(float) * 3);
    }
}

/* Carry one piece in - one room or a whole outdoors - turned and put down
   where the plan says. */
static bool carry(mapgen_geometry_t *dst, const donor_t *d, const part_t *p,
                  uint32_t *out_brushes)
{
    const uint32_t nb = MapGenGeometry_NumBrushes(d->geo);
    const uint32_t ne = MapGenGeometry_NumEntities(d->geo);
    uint8_t *bm = calloc(nb ? nb : 1, 1);
    uint8_t *em = calloc(ne ? ne : 1, 1);
    if (!bm || !em) {
        free(bm);
        free(em);
        return false;
    }
    piece_mask(d, p, bm, em);
    (void)ne;

    const float pivot[3] = { 0.5f * (p->box_lo[0] + p->box_hi[0]),
                             0.5f * (p->box_lo[1] + p->box_hi[1]),
                             0.5f * (p->box_lo[2] + p->box_hi[2]) };
    /* The turn keeps the middle where it is, so the offset is from the box's
       middle to where the plan wants the box's middle. */
    const float want[3] = { p->at[0] + p->size[0] * 0.5f,
                            p->at[1] + p->size[1] * 0.5f,
                            p->at[2] + p->size[2] * 0.5f };
    const float offset[3] = { want[0] - pivot[0], want[1] - pivot[1],
                              want[2] - pivot[2] };

    /* Into a map of its own first, so it can be clipped without the pieces
       already standing being clipped with it. */
    mapgen_geometry_t *one = NULL;
    if (MapGenGeometry_Empty(&one) != MAPGEN_GEOMETRY_OK) {
        free(bm);
        free(em);
        return false;
    }
    uint32_t first = 0, count = 0;
    mapgen_geometry_result_t rc =
        MapGenGeometry_Graft(one, d->geo, bm, em, pivot, p->quarter_turns,
                             p->mirror_x, offset, &first, &count);
    free(bm);
    free(em);
    if (rc != MAPGEN_GEOMETRY_OK) {
        MapGenGeometry_Free(one);
        return false;
    }

    if (p->clip) {
        const float clo[3] = { p->at[0] - CLIP_SLOP, p->at[1] - CLIP_SLOP,
                               p->at[2] - CLIP_SLOP };
        const float chi[3] = { p->at[0] + p->size[0] + CLIP_SLOP,
                               p->at[1] + p->size[1] + CLIP_SLOP,
                               p->at[2] + p->size[2] + CLIP_SLOP };
        clip_to_box(one, clo, chi);
    }

    const uint32_t ob = MapGenGeometry_NumBrushes(one);
    const uint32_t oe = MapGenGeometry_NumEntities(one);
    uint8_t *ab = malloc(ob ? ob : 1);
    uint8_t *ae = malloc(oe ? oe : 1);
    if (!ab || !ae) {
        free(ab);
        free(ae);
        MapGenGeometry_Free(one);
        return false;
    }
    memset(ab, 1, ob ? ob : 1);
    memset(ae, 1, oe ? oe : 1);
    const float here[3] = { 0.0f, 0.0f, 0.0f };
    rc = MapGenGeometry_Graft(dst, one, ab, ae, here, 0, false, here,
                              &first, &count);
    free(ab);
    free(ae);
    MapGenGeometry_Free(one);
    if (out_brushes)
        *out_brushes = count;
    return rc == MAPGEN_GEOMETRY_OK;
}

/*
 * A box of the donor's, where the plan puts it.
 *
 * The turn is about the piece's own middle and the mirror comes after it,
 * which is what MapGenGeometry_Graft does to the brushes; a box follows its
 * corners.
 */
static void map_box(const part_t *p, const float dlo[3], const float dhi[3],
                    float lo[3], float hi[3])
{
    const float pivot[2] = { 0.5f * (p->box_lo[0] + p->box_hi[0]),
                             0.5f * (p->box_lo[1] + p->box_hi[1]) };
    const float want[2] = { p->at[0] + p->size[0] * 0.5f,
                            p->at[1] + p->size[1] * 0.5f };
    bool any = false;
    for (int c = 0; c < 4; c++) {
        const float x = (c & 1) ? dhi[0] : dlo[0];
        const float y = (c & 2) ? dhi[1] : dlo[1];
        const float dx = x - pivot[0], dy = y - pivot[1];
        float rx = dx, ry = dy;
        switch (p->quarter_turns & 3u) {
        case 1: rx = -dy; ry = dx; break;
        case 2: rx = -dx; ry = -dy; break;
        case 3: rx = dy; ry = -dx; break;
        default: break;
        }
        if (p->mirror_x)
            rx = -rx;
        const float px = want[0] + rx, py = want[1] + ry;
        if (!any || px < lo[0]) lo[0] = px;
        if (!any || px > hi[0]) hi[0] = px;
        if (!any || py < lo[1]) lo[1] = py;
        if (!any || py > hi[1]) hi[1] = py;
        any = true;
    }
    lo[2] = p->at[2] + (dlo[2] - p->box_lo[2]);
    hi[2] = p->at[2] + (dhi[2] - p->box_lo[2]);
}

/*
 * Where a side of the arena has somewhere to open into.
 *
 * MEASURED on the first composition with a pocket: the way was cut at the
 * middle of the pocket's face and ran a thousand and twenty-four units into
 * the arena without meeting anything, because at that height and that
 * distance along the wall there is nothing but the donor's rock. The pocket,
 * its start and its pickups were a map of their own. So the wall is READ
 * first: for every place along it and every height, how deep the rock goes
 * before there is floor to stand on, and the way is cut at the shallowest.
 */
#define DOOR_STEP     64.0f
#define DOOR_RISE     32.0f
#define DOOR_DEPTH   512.0f
#define DOOR_FLOOR    64.0f

static void donor_point(const part_t *p, const float here[3], float out[3]);

static bool best_door(const mapgen_bsp_t *bsp, const part_t *yard, int side,
                      const float yard_lo[2], const float yard_hi[2],
                      float *out_across, float *out_z)
{
    const int axis = side < 2 ? 0 : 1;
    const int across = axis ^ 1;
    const bool from_hi = (side == 0 || side == 2);
    float depth_best = DOOR_DEPTH + 1.0f;
    bool found = false;
    for (float a = yard_lo[across] + 128.0f; a <= yard_hi[across] - 128.0f;
         a += DOOR_STEP)
      for (float z = DOOR_RISE; z < yard->size[2] - 96.0f; z += DOOR_RISE)
        for (float depth = 0.0f; depth <= DOOR_DEPTH; depth += 16.0f) {
            float here[3];
            here[axis] = from_hi ? yard_hi[axis] - depth
                                 : yard_lo[axis] + depth;
            here[across] = a;
            here[2] = z;
            float there[3];
            donor_point(yard, here, there);
            if (MapGenBsp_PointContents(bsp, there) & CONTENTS_SOLID_BIT)
                continue;
            /* Air, and it has to have a floor under it and headroom over. */
            bool floor = false;
            for (float dz = 8.0f; dz <= DOOR_FLOOR && !floor; dz += 8.0f) {
                float below[3] = { here[0], here[1], here[2] - dz };
                float bthere[3];
                donor_point(yard, below, bthere);
                floor = (MapGenBsp_PointContents(bsp, bthere)
                         & CONTENTS_SOLID_BIT) != 0;
            }
            float head[3] = { here[0], here[1], here[2] + 56.0f };
            float hthere[3];
            donor_point(yard, head, hthere);
            const bool room = !(MapGenBsp_PointContents(bsp, hthere)
                                & CONTENTS_SOLID_BIT);
            if (floor && room && depth < depth_best) {
                depth_best = depth;
                *out_across = a;
                *out_z = z;
                found = true;
            }
            break;
        }
    return found;
}

/* The donor point a composed point came from: map_box run backwards. */
static void donor_point(const part_t *p, const float here[3], float out[3])
{
    const float pivot[2] = { 0.5f * (p->box_lo[0] + p->box_hi[0]),
                             0.5f * (p->box_lo[1] + p->box_hi[1]) };
    const float want[2] = { p->at[0] + p->size[0] * 0.5f,
                            p->at[1] + p->size[1] * 0.5f };
    float rx = here[0] - want[0], ry = here[1] - want[1];
    if (p->mirror_x)
        rx = -rx;
    float dx = rx, dy = ry;
    switch (p->quarter_turns & 3u) {
    case 1: dx = ry; dy = -rx; break;
    case 2: dx = -rx; dy = -ry; break;
    case 3: dx = -ry; dy = rx; break;
    default: break;
    }
    out[0] = pivot[0] + dx;
    out[1] = pivot[1] + dy;
    out[2] = here[2] - p->at[2] + p->box_lo[2];
}

/* Where the way into a pocket runs, which the hollow and the lattice have to
   agree about exactly. */
static void way_to(const part_t *p, const float yard_lo[2],
                   const float yard_hi[2], float lo[3], float hi[3])
{
    const int axis = p->side < 2 ? 0 : 1;
    const int across = axis ^ 1;
    const float mid = p->at[across] + p->size[across] * 0.5f;
    lo[across] = mid - WAY_WIDE * 0.5f;
    hi[across] = mid + WAY_WIDE * 0.5f;
    if (p->side == 0 || p->side == 2) {
        lo[axis] = yard_hi[axis] - 64.0f;
        hi[axis] = p->at[axis] + 64.0f;
    } else {
        lo[axis] = p->at[axis] + p->size[axis] - 64.0f;
        hi[axis] = yard_lo[axis] + 64.0f;
    }
    lo[2] = p->way_z;
    hi[2] = p->way_z + WAY_TALL;
}

static void bail(donor_t *d, uint32_t n, void *a, void *b,
                 mapgen_geometry_t *g)
{
    MapGenGeometry_Free(g);
    free(a);
    free(b);
    for (uint32_t i = 0; i < n; i++)
        donor_free(&d[i]);
}

mapgen_compose_result_t MapGenCompose_Build(const char *const *donors,
                                            uint32_t num_donors,
                                            uint64_t seed,
                                            mapgen_geometry_t **out,
                                            mapgen_compose_report_t *report)
{
    if (out)
        *out = NULL;
    if (report)
        memset(report, 0, sizeof(*report));
    if (!donors || !num_donors || num_donors > MAPGEN_COMPOSE_MAX_DONORS
        || !out)
        return MAPGEN_COMPOSE_ERR_ARGS;

    donor_t d[MAPGEN_COMPOSE_MAX_DONORS];
    memset(d, 0, sizeof(d));
    for (uint32_t i = 0; i < num_donors; i++) {
        snprintf(d[i].name, sizeof(d[i].name), "%s", base_name(donors[i]));
        d[i].bsp = load_bsp(donors[i]);
        if (!d[i].bsp
            || MapGenGeometry_FromBsp(d[i].bsp, &d[i].geo) != MAPGEN_GEOMETRY_OK
            || MapGenRooms_Find(d[i].bsp, 64.0f, MAPGEN_ROOMS_PERSISTENCE,
                                &d[i].rooms) != MAPGEN_ROOMS_OK
            || MapGenBundle_Survey(d[i].bsp, d[i].geo, d[i].rooms, &d[i].set)
               != MAPGEN_BUNDLE_OK) {
            bail(d, i + 1, NULL, NULL, NULL);
            return MAPGEN_COMPOSE_ERR_DONOR;
        }
    }

    /* ---- the arenas: one donor's outdoors each ------------------------ */
    part_t arena[MAPGEN_COMPOSE_MAX_DONORS];
    memset(arena, 0, sizeof(arena));
    uint32_t arenas = 0;
    for (uint32_t i = 0; i < num_donors; i++) {
        part_t a;
        memset(&a, 0, sizeof(a));
        a.donor = i;
        a.side = -1;
        for (uint32_t r = 0; r < MapGenBundleSet_Count(d[i].set)
                             && a.rooms < MAX_GROUP; r++) {
            const mapgen_bundle_t *b = MapGenBundleSet_At(d[i].set, r);
            if (!b || !MapGenBundle_Sealed(b))
                continue;
            if (!MapGenCompose_Carriable(d[i].geo, b))
                continue;
            uint32_t sky = 0;
            for (uint32_t k = 0; k < MapGenBundle_NumBrushes(b); k++) {
                const mapgen_bundle_brush_t *bb = MapGenBundle_Brush(b, k);
                const mapgen_geometry_brush_t *br =
                    bb ? MapGenGeometry_Brush(d[i].geo, bb->brush) : NULL;
                if (!br)
                    continue;
                for (uint32_t q = 0; q < br->num_sides; q++) {
                    const mapgen_geometry_side_t *side =
                        MapGenGeometry_Side(d[i].geo, br->first_side + q);
                    if (side && (side->flags & SURF_SKY_BIT))
                        sky++;
                }
            }
            if (sky < ROOM_SKY)
                continue;
            const float *lo = MapGenBundle_Mins(b);
            const float *hi = MapGenBundle_Maxs(b);
            if (!lo || !hi)
                continue;
            for (int x = 0; x < 3; x++) {
                if (!a.rooms || lo[x] < a.box_lo[x])
                    a.box_lo[x] = lo[x];
                if (!a.rooms || hi[x] > a.box_hi[x])
                    a.box_hi[x] = hi[x];
            }
            a.room[a.rooms++] = r;
            a.sky += sky;
            a.air += MapGenBundle_AirCells(b);
        }
        if (a.rooms < 2)
            continue;

        /*
         * And everything that stands INSIDE the outdoors comes with it.
         *
         * MEASURED on q2dm1: its eight sky rooms are joined through the
         * indoor ones - the lift lobby, the corridor behind the railgun -
         * and carrying only the rooms with sky left three hundred and
         * thirty-six places a player could drop into and not leave. A room
         * whose box lies inside the yard's box is part of the yard.
         */
        for (uint32_t r2 = 0; r2 < MapGenBundleSet_Count(d[i].set)
                              && a.rooms < MAX_GROUP; r2++) {
            bool inside = false;
            for (uint32_t k = 0; k < a.rooms && !inside; k++)
                inside = a.room[k] == r2;
            if (inside)
                continue;
            const mapgen_bundle_t *b2 = MapGenBundleSet_At(d[i].set, r2);
            if (!b2 || !MapGenBundle_Sealed(b2)
                || !MapGenCompose_Carriable(d[i].geo, b2))
                continue;
            const float *rlo = MapGenBundle_Mins(b2);
            const float *rhi = MapGenBundle_Maxs(b2);
            if (!rlo || !rhi)
                continue;
            bool within = true;
            for (int x = 0; x < 3 && within; x++)
                within = rlo[x] >= a.box_lo[x] - 32.0f
                      && rhi[x] <= a.box_hi[x] + 32.0f;
            if (!within)
                continue;
            a.room[a.rooms++] = r2;
            a.air += MapGenBundle_AirCells(b2);
        }

        /*
         * And the rooms of it have to reach each other WITHIN it.
         *
         * MEASURED on q2dm1: its outdoors is eight rooms and they are joined
         * through the indoor ones - the lift lobby, the corridor behind the
         * railgun - so carrying the sky rooms alone left three hundred and
         * thirty-five places a player could get into and not out of and four
         * pickups nobody could reach. Whatever lies BETWEEN two pieces of the
         * outdoors is part of the arena whether it has sky or not.
         */
        for (uint32_t pass = 0; pass < MAX_GROUP && a.rooms < MAX_GROUP;
             pass++) {
            uint32_t comp[MAX_GROUP];
            for (uint32_t k = 0; k < a.rooms; k++)
                comp[k] = k;
            bool moved = true;
            while (moved) {
                moved = false;
                for (uint32_t k = 0; k < a.rooms; k++) {
                    const mapgen_bundle_t *b =
                        MapGenBundleSet_At(d[i].set, a.room[k]);
                    for (uint32_t s = 0; b && s < MapGenBundle_NumSockets(b);
                         s++) {
                        const mapgen_socket_t *so = MapGenBundle_Socket(b, s);
                        if (!so)
                            continue;
                        for (uint32_t m = 0; m < a.rooms; m++) {
                            if (a.room[m] != so->peer)
                                continue;
                            const uint32_t lo_c = comp[k] < comp[m] ? comp[k]
                                                                    : comp[m];
                            if (comp[k] != lo_c || comp[m] != lo_c) {
                                comp[k] = comp[m] = lo_c;
                                moved = true;
                            }
                        }
                    }
                }
            }
            uint32_t groups = 0;
            for (uint32_t k = 0; k < a.rooms; k++)
                if (comp[k] == k)
                    groups++;
            if (groups <= 1)
                break;

            /* The room outside that touches the most of the pieces. */
            int32_t bridge = -1;
            uint32_t best = 1;
            for (uint32_t r2 = 0; r2 < MapGenBundleSet_Count(d[i].set); r2++) {
                bool inside = false;
                for (uint32_t k = 0; k < a.rooms && !inside; k++)
                    inside = a.room[k] == r2;
                if (inside)
                    continue;
                const mapgen_bundle_t *b2 = MapGenBundleSet_At(d[i].set, r2);
                if (!b2 || !MapGenBundle_Sealed(b2)
                    || !MapGenCompose_Carriable(d[i].geo, b2))
                    continue;
                uint32_t touched[MAX_GROUP], n = 0;
                for (uint32_t s = 0; s < MapGenBundle_NumSockets(b2); s++) {
                    const mapgen_socket_t *so = MapGenBundle_Socket(b2, s);
                    if (!so)
                        continue;
                    for (uint32_t k = 0; k < a.rooms; k++) {
                        if (a.room[k] != so->peer)
                            continue;
                        bool seen2 = false;
                        for (uint32_t q = 0; q < n && !seen2; q++)
                            seen2 = touched[q] == comp[k];
                        if (!seen2 && n < MAX_GROUP)
                            touched[n++] = comp[k];
                    }
                }
                if (n > best) {
                    best = n;
                    bridge = (int32_t)r2;
                }
            }
            if (bridge < 0)
                break;
            const mapgen_bundle_t *nb = MapGenBundleSet_At(d[i].set,
                                                          (uint32_t)bridge);
            const float *nlo = MapGenBundle_Mins(nb);
            const float *nhi = MapGenBundle_Maxs(nb);
            if (!nlo || !nhi)
                break;
            for (int x = 0; x < 3; x++) {
                if (nlo[x] < a.box_lo[x])
                    a.box_lo[x] = nlo[x];
                if (nhi[x] > a.box_hi[x])
                    a.box_hi[x] = nhi[x];
            }
            a.room[a.rooms++] = (uint32_t)bridge;
            a.air += MapGenBundle_AirCells(nb);
        }

        shape_of(d[i].bsp, a.box_lo, a.box_hi, &a.shape);
        if (a.box_hi[0] - a.box_lo[0] < ARENA_MIN_X)
            continue;
        if (a.box_hi[1] - a.box_lo[1] < ARENA_MIN_Y)
            continue;
        if (a.shape.storeys < ARENA_STOREYS
            || a.shape.planes < ARENA_PLANES
            || a.shape.spread < ARENA_SPREAD)
            continue;
        arena[arenas++] = a;
    }
    if (!arenas) {
        bail(d, num_donors, NULL, NULL, NULL);
        return MAPGEN_COMPOSE_ERR_STOCK;
    }

    uint64_t stream = seed ^ 0x4152454E41ull;   /* "ARENA" */
    part_t part[MAPGEN_COMPOSE_MAX_PARTS];
    memset(part, 0, sizeof(part));
    part[0] = arena[mix(&stream) % arenas];
    part[0].quarter_turns = (uint32_t)(mix(&stream) & 3u);
    part[0].mirror_x = (mix(&stream) & 1u) != 0;
    part[0].clip = false;
    part[0].machines = true;
    part[0].by_box = true;
    /* Placed by everything it brings, walls and sky included. */
    piece_extent(&d[part[0].donor], &part[0], part[0].box_lo, part[0].box_hi);
    turned_size(&part[0], part[0].quarter_turns, part[0].size);
    uint32_t parts = 1;

    const float yard_lo[2] = { 0.0f, 0.0f };
    const float yard_hi[2] = { part[0].size[0], part[0].size[1] };

    /*
     * ---- the pockets ---------------------------------------------------
     *
     * One at a time, on whichever side of the arena there is still room for
     * one inside q2dm1's own footprint. The budget is the point: three
     * rounds of invented maps came out two and three times too big because
     * nothing was counting, and the footprint is not a control to be tuned -
     * it is what is left when a yard of this size has rooms of that size
     * around it.
     */
    static const int SIDE[4][2] = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } };
    float budget[2] = {
        WANT_X * (1.0f + WANT_SLACK) - part[0].size[0] - 2.0f * MARGIN,
        WANT_Y * (1.0f + WANT_SLACK) - part[0].size[1] - 2.0f * MARGIN,
    };
    for (int s = 0; s < 4 && parts < MAPGEN_COMPOSE_MAX_PARTS; s++) {
        const int axis = SIDE[s][0] ? 0 : 1;
        const int across = axis ^ 1;
        const float room = budget[axis] - GAP;
        if (room < 320.0f)
            continue;
        part_t pick;
        memset(&pick, 0, sizeof(pick));
        uint32_t seen = 0;
        for (uint32_t i = 0; i < num_donors; i++) {
            if (i == part[0].donor)
                continue;
            for (uint32_t r = 0; r < MapGenBundleSet_Count(d[i].set); r++) {
                const mapgen_bundle_t *b = MapGenBundleSet_At(d[i].set, r);
                if (!b || !MapGenBundle_Sealed(b) || !MapGenBundle_Movable(b))
                    continue;
                if (!MapGenCompose_Carriable(d[i].geo, b))
                    continue;
                const uint32_t air = MapGenBundle_AirCells(b);
                if (air < POCKET_MIN_AIR || air > POCKET_MAX_AIR)
                    continue;
                if (MapGenBundle_NumSockets(b) < 2)
                    continue;
                const float *lo = MapGenBundle_Mins(b);
                const float *hi = MapGenBundle_Maxs(b);
                if (!lo || !hi)
                    continue;
                if (hi[axis] - lo[axis] > room)
                    continue;
                if (hi[across] - lo[across] > part[0].size[across])
                    continue;
                if (hi[2] - lo[2] > part[0].size[2])
                    continue;
                bool taken = false;
                for (uint32_t k = 1; k < parts && !taken; k++)
                    taken = part[k].donor == i && part[k].room[0] == r;
                if (taken)
                    continue;
                /* Reservoir choice, so every candidate has the same chance
                   and the pick is the seed's alone. */
                seen++;
                if (mix(&stream) % seen)
                    continue;
                memset(&pick, 0, sizeof(pick));
                pick.donor = i;
                pick.room[0] = r;
                pick.rooms = 1;
                pick.air = air;
                memcpy(pick.box_lo, lo, sizeof(pick.box_lo));
                memcpy(pick.box_hi, hi, sizeof(pick.box_hi));
            }
        }
        if (!pick.rooms)
            continue;
        part_t *p = &part[parts];
        *p = pick;
        p->side = s;
        p->clip = true;
        p->quarter_turns = 0;
        p->mirror_x = (mix(&stream) & 1u) != 0;
        turned_size(p, p->quarter_turns, p->size);
        float door_a = yard_lo[across]
                     + (yard_hi[across] - yard_lo[across]) * 0.5f;
        float door_z = 8.0f;
        if (!best_door(d[part[0].donor].bsp, &part[0], s, yard_lo, yard_hi,
                       &door_a, &door_z))
            continue;
        p->at[across] = door_a - p->size[across] * 0.5f;
        if (SIDE[s][axis] > 0)
            p->at[axis] = yard_hi[axis] + GAP;
        else
            p->at[axis] = yard_lo[axis] - GAP - p->size[axis];
        /* And its own floor level with the way, which is level with the
           arena's floor at the place the way opens into. */
        {
            const mapgen_bundle_t *pb = MapGenBundleSet_At(d[pick.donor].set,
                                                           pick.room[0]);
            float rise = 0.0f;
            if (pb) {
                for (float z = pick.box_lo[2] + 8.0f; z < pick.box_hi[2];
                     z += 8.0f) {
                    const float q[3] = {
                        0.5f * (pick.box_lo[0] + pick.box_hi[0]),
                        0.5f * (pick.box_lo[1] + pick.box_hi[1]), z };
                    const float u[3] = { q[0], q[1], z - 8.0f };
                    if (!(MapGenBsp_PointContents(d[pick.donor].bsp, q)
                          & CONTENTS_SOLID_BIT)
                        && (MapGenBsp_PointContents(d[pick.donor].bsp, u)
                            & CONTENTS_SOLID_BIT)) {
                        rise = z - pick.box_lo[2];
                        break;
                    }
                }
            }
            p->at[2] = door_z - rise;
        }
        p->way_z = door_z;
        budget[axis] -= GAP + p->size[axis];
        parts++;
    }

    /* ---- carry them in ------------------------------------------------ */
    mapgen_geometry_t *g = NULL;
    if (MapGenGeometry_Empty(&g) != MAPGEN_GEOMETRY_OK) {
        bail(d, num_donors, NULL, NULL, NULL);
        return MAPGEN_COMPOSE_ERR_MEMORY;
    }
    uint32_t world = 0;
    if (MapGenGeometry_AddEntity(g, 0, &world) != MAPGEN_GEOMETRY_OK
        || MapGenGeometry_AddEntityPair(g, world, "classname", "worldspawn")
           != MAPGEN_GEOMETRY_OK) {
        bail(d, num_donors, NULL, NULL, g);
        return MAPGEN_COMPOSE_ERR_BUILD;
    }

    for (uint32_t i = 0; i < parts; i++) {
        uint32_t got = 0;
        if (!carry(g, &d[part[i].donor], &part[i], &got)) {
            bail(d, num_donors, NULL, NULL, g);
            return MAPGEN_COMPOSE_ERR_BUILD;
        }
        if (report && report->num_parts < MAPGEN_COMPOSE_MAX_PARTS) {
            mapgen_compose_part_t *rp = &report->part[report->num_parts++];
            snprintf(rp->donor, sizeof(rp->donor), "%s",
                     d[part[i].donor].name);
            rp->room = part[i].rooms == 1 ? part[i].room[0] : part[i].rooms;
            rp->quarter_turns = part[i].quarter_turns;
            rp->mirror_x = part[i].mirror_x;
            for (int a = 0; a < 3; a++) {
                rp->mins[a] = part[i].at[a];
                rp->maxs[a] = part[i].at[a] + part[i].size[a];
            }
            rp->brushes = got;
            rp->main = i == 0;
        }
    }

    /* ---- the shell ---------------------------------------------------- */
    float lo[3] = { 0, 0, 0 }, hi[3] = { 0, 0, 0 };
    for (uint32_t i = 0; i < parts; i++)
      for (int a = 0; a < 3; a++) {
        if (!i || part[i].at[a] < lo[a])
            lo[a] = part[i].at[a];
        if (!i || part[i].at[a] + part[i].size[a] > hi[a])
            hi[a] = part[i].at[a] + part[i].size[a];
      }
    const float glo[3] = { lo[0] - MARGIN, lo[1] - MARGIN, lo[2] - MARGIN };
    const float ghi[3] = { hi[0] + MARGIN, hi[1] + MARGIN, hi[2] + MARGIN };

    grid_t air, rock;
    memset(&air, 0, sizeof(air));
    memset(&rock, 0, sizeof(rock));
    if (!grid_make(&air, glo, ghi) || !grid_make(&rock, glo, ghi)) {
        bail(d, num_donors, air.bit, rock.bit, g);
        return MAPGEN_COMPOSE_ERR_MEMORY;
    }

    /*
     * Where the map is ALLOWED to be open: inside a ROOM it carried, and
     * along a way between them. Everything else becomes rock, so the map is
     * sealed by construction.
     *
     * And "open" is asked of the DONOR, cell by cell, rather than of the
     * rooms' boxes. Two measurements decided it. Letting a piece's whole box
     * be open gave nine thousand standing places where q2dm1 has a thousand,
     * three player starts in voids of their own and five and a half thousand
     * places a player could get into and not out of, because the rock inside
     * that box belongs to rooms the arena did not carry. Letting only the
     * rooms' boxes be open filled the courtyard's own air with a thousand
     * brushes of shell and the arena went back to being a corridor: an open
     * volume 1280 by 704 with its floors spread thirty-two units. The space
     * a piece brings is the space its donor HAS there, and nothing else is
     * exactly it.
     */
    for (uint32_t i = 0; i < parts; i++) {
        const mapgen_bsp_t *src = d[part[i].donor].bsp;
        for (int32_t z = (int32_t)floorf(part[i].at[2] / CELL);
             z < (int32_t)ceilf((part[i].at[2] + part[i].size[2]) / CELL); z++)
          for (int32_t y = (int32_t)floorf(part[i].at[1] / CELL);
               y < (int32_t)ceilf((part[i].at[1] + part[i].size[1]) / CELL);
               y++)
            for (int32_t x = (int32_t)floorf(part[i].at[0] / CELL);
                 x < (int32_t)ceilf((part[i].at[0] + part[i].size[0]) / CELL);
                 x++) {
                if (!grid_in(&air, x, y, z))
                    continue;
                const float here[3] = { ((float)x + 0.5f) * CELL,
                                        ((float)y + 0.5f) * CELL,
                                        ((float)z + 0.5f) * CELL };
                float there[3];
                donor_point(&part[i], here, there);
                if (!(MapGenBsp_PointContents(src, there)
                      & CONTENTS_SOLID_BIT))
                    air.bit[grid_at(&air, x, y, z)] = 1;
            }
    }
    /*
     * ---- a way into each pocket ----------------------------------------
     *
     * Cut from the pocket towards the arena and NOT stopped at the arena's
     * edge: what is at that edge is its outer wall, and behind the wall can
     * be another hundred units of the donor's own rock before the first
     * thing a player could stand in. MEASURED on the composition that
     * stopped there: the pocket, its three spawns and its pickups were a
     * map of their own that nothing reached.
     */
    uint32_t connectors = 0;
    for (uint32_t i = 1; i < parts; i++) {
        float wlo[3], whi[3];
        way_to(&part[i], yard_lo, yard_hi, wlo, whi);
        const int axis = part[i].side < 2 ? 0 : 1;
        const bool inward = part[i].side == 0 || part[i].side == 2;
        const int32_t mid_a = (int32_t)floorf(
            (0.5f * (wlo[axis ^ 1] + whi[axis ^ 1])) / CELL);
        const int32_t mid_z = (int32_t)floorf(
            ((wlo[2] + whi[2]) * 0.5f) / CELL);
        for (uint32_t step = 0; step < WAY_REACH / (uint32_t)CELL; step++) {
            (void)step;
            const float edge = inward ? wlo[axis] : whi[axis];
            const int32_t cell = (int32_t)floorf(edge / CELL)
                               + (inward ? -1 : 0);
            const int32_t cx = axis ? mid_a : cell;
            const int32_t cy = axis ? cell : mid_a;
            if (!grid_in(&air, cx, cy, mid_z))
                break;
            if (air.bit[grid_at(&air, cx, cy, mid_z)])
                break;
            if (inward)
                wlo[axis] -= CELL;
            else
                whi[axis] += CELL;
        }
        grid_box(&air, wlo, whi, 1);
        if (MapGenGraft_Hollow(g, wlo, whi) == MAPGEN_GRAFT_OK)
            connectors++;
    }

    mark_solid(&rock, g);

    /*
     * ---- and the map is ONE body of air --------------------------------
     *
     * Whatever the donor's space brings that this map cannot reach is filled
     * in. MEASURED on q2dm1's outdoors carried whole: three hundred and
     * thirty-six of its four thousand standing places were pockets a player
     * could drop into and not leave, and three of the starts were in them -
     * because the outdoors of that map is joined THROUGH its indoor rooms
     * and those did not come. A room nobody can reach is not a room; it is
     * rock that has not been filled in yet.
     */
    {
        const size_t cells = (size_t)air.n[0] * air.n[1] * air.n[2];
        uint8_t *seen = calloc(cells, 1);
        int32_t *queue = malloc(sizeof(*queue) * cells);
        if (seen && queue) {
            static const int32_t STEP6[6][3] = {
                { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 },
                { 0, -1, 0 }, { 0, 0, 1 }, { 0, 0, -1 },
            };
            size_t best_at = 0, best_size = 0;
            uint8_t *keep = calloc(cells, 1);
            for (int32_t z0 = air.lo[2]; z0 < air.lo[2] + air.n[2]; z0++)
              for (int32_t y0 = air.lo[1]; y0 < air.lo[1] + air.n[1]; y0++)
                for (int32_t x0 = air.lo[0]; x0 < air.lo[0] + air.n[0]; x0++) {
                    const size_t at0 = grid_at(&air, x0, y0, z0);
                    if (!air.bit[at0] || rock.bit[at0] || seen[at0])
                        continue;
                    size_t head = 0, tail = 0, size = 0;
                    seen[at0] = 1;
                    queue[tail++] = (int32_t)at0;
                    while (head < tail) {
                        const int32_t at = queue[head++];
                        size++;
                        const int32_t z = air.lo[2]
                            + (int32_t)(at / (air.n[0] * air.n[1]));
                        const int32_t y = air.lo[1]
                            + (int32_t)((at / air.n[0]) % air.n[1]);
                        const int32_t x = air.lo[0] + (int32_t)(at % air.n[0]);
                        for (int s = 0; s < 6; s++) {
                            const int32_t nx = x + STEP6[s][0];
                            const int32_t ny = y + STEP6[s][1];
                            const int32_t nz = z + STEP6[s][2];
                            if (!grid_in(&air, nx, ny, nz))
                                continue;
                            const size_t n2 = grid_at(&air, nx, ny, nz);
                            if (seen[n2] || !air.bit[n2] || rock.bit[n2])
                                continue;
                            seen[n2] = 1;
                            queue[tail++] = (int32_t)n2;
                        }
                    }
                    if (size > best_size) {
                        best_size = size;
                        best_at = at0;
                    }
                }
            /* and again, keeping only the biggest */
            memset(seen, 0, cells);
            size_t head = 0, tail = 0;
            if (best_size && keep) {
                seen[best_at] = 1;
                keep[best_at] = 1;
                queue[tail++] = (int32_t)best_at;
                while (head < tail) {
                    const int32_t at = queue[head++];
                    const int32_t z = air.lo[2]
                        + (int32_t)(at / (air.n[0] * air.n[1]));
                    const int32_t y = air.lo[1]
                        + (int32_t)((at / air.n[0]) % air.n[1]);
                    const int32_t x = air.lo[0] + (int32_t)(at % air.n[0]);
                    for (int s = 0; s < 6; s++) {
                        const int32_t nx = x + STEP6[s][0];
                        const int32_t ny = y + STEP6[s][1];
                        const int32_t nz = z + STEP6[s][2];
                        if (!grid_in(&air, nx, ny, nz))
                            continue;
                        const size_t n2 = grid_at(&air, nx, ny, nz);
                        if (seen[n2] || !air.bit[n2] || rock.bit[n2])
                            continue;
                        seen[n2] = 1;
                        keep[n2] = 1;
                        queue[tail++] = (int32_t)n2;
                    }
                }
                for (size_t i = 0; i < cells; i++)
                    if (air.bit[i] && !keep[i])
                        air.bit[i] = 0;
            }
            free(keep);
        }
        free(seen);
        free(queue);
    }

    mapgen_geometry_side_t wall;
    bool has_wall = false;
    for (uint32_t i = 0; i < num_donors && !has_wall; i++)
        has_wall = borrow(d[i].geo, &wall);
    if (!has_wall) {
        bail(d, num_donors, air.bit, rock.bit, g);
        return MAPGEN_COMPOSE_ERR_BUILD;
    }

    uint32_t shell = 0;
    for (int32_t z = air.lo[2]; z < air.lo[2] + air.n[2] && shell < MAX_SHELL;
         z++)
      for (int32_t y = air.lo[1]; y < air.lo[1] + air.n[1] && shell < MAX_SHELL;
           y++)
        for (int32_t x = air.lo[0];
             x < air.lo[0] + air.n[0] && shell < MAX_SHELL; x++) {
            const size_t at = grid_at(&air, x, y, z);
            if (air.bit[at] || rock.bit[at])
                continue;
            int32_t run = 0;
            while (x + run < air.lo[0] + air.n[0]
                   && !air.bit[grid_at(&air, x + run, y, z)]
                   && !rock.bit[grid_at(&air, x + run, y, z)])
                run++;
            int32_t deep = 1;
            while (y + deep < air.lo[1] + air.n[1]) {
                bool whole = true;
                for (int32_t k = 0; k < run && whole; k++)
                    whole = !air.bit[grid_at(&air, x + k, y + deep, z)]
                         && !rock.bit[grid_at(&air, x + k, y + deep, z)];
                if (!whole)
                    break;
                deep++;
            }
            int32_t tall = 1;
            while (z + tall < air.lo[2] + air.n[2]) {
                bool whole = true;
                for (int32_t j = 0; j < deep && whole; j++)
                    for (int32_t k = 0; k < run && whole; k++)
                        whole = !air.bit[grid_at(&air, x + k, y + j, z + tall)]
                             && !rock.bit[grid_at(&air, x + k, y + j,
                                                  z + tall)];
                if (!whole)
                    break;
                tall++;
            }
            for (int32_t j = 0; j < deep; j++)
                for (int32_t k = 0; k < run; k++)
                    for (int32_t i = 0; i < tall; i++)
                        rock.bit[grid_at(&rock, x + k, y + j, z + i)] = 1;

            const float blo[3] = { (float)x * CELL, (float)y * CELL,
                                   (float)z * CELL };
            const float bhi[3] = { (float)(x + run) * CELL,
                                   (float)(y + deep) * CELL,
                                   (float)(z + tall) * CELL };
            if (add_box(g, &wall, blo, bhi))
                shell++;
        }

    /* ---- somewhere to start ------------------------------------------- */
    uint32_t spawns = 0;
    for (uint32_t e = 0; e < MapGenGeometry_NumEntities(g); e++) {
        const char *cls = MapGenGeometry_EntityValue(g, e, "classname");
        if (cls && !strcmp(cls, "info_player_deathmatch"))
            spawns++;
    }
    /*
     * And only if the arena did not bring enough of its own.
     *
     * MEASURED: a start put down on the first floor cell the lattice offers
     * is a start in whatever pocket of the donor's space happens to lie
     * lowest, and three of them landed where nothing else in the map could
     * reach. What a carried arena brings are the starts a designer chose.
     */
    const uint32_t carried_spawns = spawns;
    for (int32_t z = air.lo[2]; z < air.lo[2] + air.n[2]
                                && carried_spawns < 4u
                                && spawns < WANT_SPAWNS; z++)
      for (int32_t y = air.lo[1]; y < air.lo[1] + air.n[1]
                                  && spawns < WANT_SPAWNS; y += 5)
        for (int32_t x = air.lo[0]; x < air.lo[0] + air.n[0]
                                    && spawns < WANT_SPAWNS; x += 5) {
            if (!air.bit[grid_at(&air, x, y, z)]
                || rock.bit[grid_at(&air, x, y, z)])
                continue;
            if (!grid_in(&air, x, y, z - 1)
                || !rock.bit[grid_at(&rock, x, y, z - 1)])
                continue;
            if (!grid_in(&air, x, y, z + 2)
                || rock.bit[grid_at(&rock, x, y, z + 1)]
                || rock.bit[grid_at(&rock, x, y, z + 2)])
                continue;
            uint32_t ent = 0;
            char buf[64];
            snprintf(buf, sizeof(buf), "%.0f %.0f %.0f",
                     ((double)x + 0.5) * CELL, ((double)y + 0.5) * CELL,
                     (double)z * CELL + 25.0);
            if (MapGenGeometry_AddEntity(g, 0, &ent) != MAPGEN_GEOMETRY_OK)
                continue;
            MapGenGeometry_AddEntityPair(g, ent, "classname",
                                         "info_player_deathmatch");
            MapGenGeometry_AddEntityPair(g, ent, "origin", buf);
            spawns++;
        }

    if (report) {
        report->connectors = connectors;
        report->shell_brushes = shell;
        report->sky_brushes = part[0].sky;
        report->spawns = spawns;
        report->footprint[0] = hi[0] - lo[0];
        report->footprint[1] = hi[1] - lo[1];
        report->sky_z = part[0].at[2] + part[0].size[2];
    }

    free(air.bit);
    free(rock.bit);
    for (uint32_t i = 0; i < num_donors; i++)
        donor_free(&d[i]);

    if (shell >= MAX_SHELL) {
        MapGenGeometry_Free(g);
        return MAPGEN_COMPOSE_ERR_BUILD;
    }
    *out = g;
    return MAPGEN_COMPOSE_OK;
}
