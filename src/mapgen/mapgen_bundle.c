/*
 * MapGenBundle - see inc/common/mapgen_bundle.h.
 *
 * Everything here is derived from the compiled donor. Nothing is taken from a
 * recipe, a blueprint or a name: a bundle that trusted an annotation would be
 * exactly as wrong as the annotation, and the maps this has to work on were
 * built by people who never heard of it.
 *
 * --- why the whole map is surveyed at once ---------------------------------
 *
 * The first version extracted one room at a time from a box drawn around it,
 * and it produced an answer that cannot be true: rooms 6 and 7 of q2dm1 each
 * declared a way out to room 0, and room 0 declared no way to either of them.
 * A way out is a way out from both ends, and it came out asymmetric because
 * each extraction was looking at a different piece of the map and reaching a
 * different conclusion about the same tight passage.
 *
 * So the lattice, the pockets of space no room owns, and the rooms each pocket
 * joins are computed ONCE for the map, and every bundle reads the same
 * answers. Symmetry is then not a property to be checked and repaired - it is
 * the shape of the data.
 */

#include "common/mapgen_bundle.h"

#include "common/mapgen_genome.h"   /* the Quake II content and surface bits */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char *MapGenBundle_ResultName(mapgen_bundle_result_t r)
{
    switch (r) {
    case MAPGEN_BUNDLE_OK:            return "OK";
    case MAPGEN_BUNDLE_ERR_ARGS:      return "ERR_ARGS";
    case MAPGEN_BUNDLE_ERR_MEMORY:    return "ERR_MEMORY";
    case MAPGEN_BUNDLE_ERR_NO_ROOM:   return "ERR_NO_ROOM";
    case MAPGEN_BUNDLE_ERR_TOO_LARGE: return "ERR_TOO_LARGE";
    }
    return "ERR_UNKNOWN";
}

const char *MapGenBundle_RoleName(mapgen_bundle_role_t role)
{
    switch (role) {
    case MAPGEN_BUNDLE_ROLE_MOVER:    return "mover";
    case MAPGEN_BUNDLE_ROLE_CLIP:     return "clip";
    case MAPGEN_BUNDLE_ROLE_BOUNDARY: return "boundary";
    case MAPGEN_BUNDLE_ROLE_SUPPORT:  return "support";
    case MAPGEN_BUNDLE_ROLE_COUNT:    break;
    }
    return "unknown";
}

const char *MapGenBundle_SocketName(mapgen_socket_kind_t kind)
{
    switch (kind) {
    case MAPGEN_SOCKET_CRAWL:   return "crawl";
    case MAPGEN_SOCKET_DOORWAY: return "doorway";
    case MAPGEN_SOCKET_HALL:    return "hall";
    case MAPGEN_SOCKET_SHAFT:   return "shaft";
    case MAPGEN_SOCKET_COUNT:   break;
    }
    return "unknown";
}

const char *MapGenBundle_AnchorName(mapgen_anchor_kind_t kind)
{
    switch (kind) {
    case MAPGEN_ANCHOR_SPAWN:   return "spawn";
    case MAPGEN_ANCHOR_ITEM:    return "item";
    case MAPGEN_ANCHOR_LIGHT:   return "light";
    case MAPGEN_ANCHOR_MOVER:   return "mover";
    case MAPGEN_ANCHOR_TRIGGER: return "trigger";
    case MAPGEN_ANCHOR_OTHER:   return "other";
    case MAPGEN_ANCHOR_COUNT:   break;
    }
    return "unknown";
}

/*
 * A standing Quake II player is 32 units across and 56 tall, and the socket
 * thresholds are his rather than round numbers that looked tidy.
 */
#define PLAYER_WIDTH   32.0f
#define DOORWAY_WIDTH  96.0f

/* How far past the map the lattice reaches. Two cells, which is enough that
   the outermost solid of the map has a cell of its own to sit in. */
#define MARGIN (MAPGEN_BUNDLE_CELL * 2.0f)

#define NO_CELL UINT32_MAX

struct mapgen_bundle_s {
    uint32_t room;
    float    mins[3], maxs[3];
    uint32_t air_cells, shell_cells, unaccounted, unowned_solid;
    /* Of the unowned, the ones the crossing walked into solid for and found no
       brush in - the world outside the map - against the ones it never reached
       solid in at all. And how much of the boundary a MOVER closes. */
    uint32_t unowned_exterior, unowned_corner, unowned_unreached;
    uint32_t seal_by_mover;
    mapgen_bundle_witness_t unowned_witness[MAPGEN_BUNDLE_WITNESSES];
    uint32_t num_unowned_witness;
    uint32_t undeclared, nook_cells, blind_cells;
    bool     sealed;

    mapgen_bundle_brush_t *brushes;
    uint32_t num_brushes;
    uint8_t *owned_brush;          /* one byte per donor brush, role + 1     */

    uint32_t *entities;
    uint32_t  num_entities;
    uint8_t  *owned_entity;

    mapgen_socket_t sockets[MAPGEN_BUNDLE_MAX_SOCKETS];
    uint32_t num_sockets;

    mapgen_bundle_anchor_t *anchors;
    uint32_t num_anchors;

    mapgen_bundle_surface_t *surfaces;
    uint32_t num_surfaces;
};

/*
 * The map, once.
 *
 * The lattice and the pocket table belong here rather than to any bundle,
 * because they are facts about the map, and two bundles that disagreed about
 * one of them would be describing two different maps.
 */
struct mapgen_bundle_set_s {
    const mapgen_bsp_t      *bsp;
    const mapgen_geometry_t *geometry;
    const mapgen_rooms_t    *rooms;

    float    lo[3];
    uint32_t dim[3];
    size_t   cells;

    uint32_t *cell_room;    /* which room's air, or UINT32_MAX              */
    uint8_t  *cell_solid;   /* solid anywhere in the cell                   */
    uint32_t *pocket;       /* which pocket of unowned space, or NO_CELL    */

    /*
     * Per pocket: one bit per room it joins.
     *
     * A bit rather than a short list, because a list has a length and a length
     * is a cap: with four slots, a pocket joining five rooms dropped one, and
     * the room that fell off the end declared no way to the others while they
     * declared ways to it. The table grows as pockets are found - there are
     * dozens on a map, not one per cell.
     */
    uint8_t  *pocket_bits;
    uint32_t  pocket_capacity;
    uint32_t  num_pockets;

    mapgen_bundle_t **bundles;
    uint32_t          num_bundles;
};

/* ---- the lattice ------------------------------------------------------------- */

static void cell_centre(const mapgen_bundle_set_t *set,
                        uint32_t x, uint32_t y, uint32_t z, float out[3])
{
    out[0] = set->lo[0] + (float)x * MAPGEN_BUNDLE_CELL
           + MAPGEN_BUNDLE_CELL * 0.5f;
    out[1] = set->lo[1] + (float)y * MAPGEN_BUNDLE_CELL
           + MAPGEN_BUNDLE_CELL * 0.5f;
    out[2] = set->lo[2] + (float)z * MAPGEN_BUNDLE_CELL
           + MAPGEN_BUNDLE_CELL * 0.5f;
}

/* The centre of a cell and its eight corners, pulled in far enough that a
   sample on a shared face belongs to this cell and not to its neighbour. */
static void sample_of(const float centre[3], int s, float out[3])
{
    for (int a = 0; a < 3; a++) {
        const int bit = ((s - 1) >> a) & 1;
        out[a] = s == 0 ? centre[a]
               : centre[a] + (bit ? 1 : -1) * MAPGEN_BUNDLE_CELL * 0.45f;
    }
}

static size_t index_of(const mapgen_bundle_set_t *set,
                       uint32_t x, uint32_t y, uint32_t z)
{
    return (size_t)(z * set->dim[1] + y) * set->dim[0] + x;
}

/* One bit per room, so a pocket can join as many as the segmentation allows. */
#define PEER_BYTES (MAPGEN_ROOMS_MAX / 8u)

static bool joins(const mapgen_bundle_set_t *set, uint32_t pocket,
                  uint32_t room)
{
    if (pocket >= set->num_pockets || room >= MAPGEN_ROOMS_MAX)
        return false;
    return (set->pocket_bits[(size_t)pocket * PEER_BYTES + room / 8u]
            >> (room % 8u)) & 1u;
}

static void join(mapgen_bundle_set_t *set, uint32_t pocket, uint32_t room)
{
    if (pocket >= set->pocket_capacity || room >= MAPGEN_ROOMS_MAX)
        return;
    set->pocket_bits[(size_t)pocket * PEER_BYTES + room / 8u]
        |= (uint8_t)(1u << (room % 8u));
}

static const int NEIGHBOUR[6][3] = {
    { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 },
    { 0, -1, 0 }, { 0, 0, 1 }, { 0, 0, -1 }
};

static bool step(const mapgen_bundle_set_t *set, uint32_t x, uint32_t y,
                 uint32_t z, int n, size_t *out)
{
    const int64_t nx = (int64_t)x + NEIGHBOUR[n][0];
    const int64_t ny = (int64_t)y + NEIGHBOUR[n][1];
    const int64_t nz = (int64_t)z + NEIGHBOUR[n][2];
    if (nx < 0 || ny < 0 || nz < 0 || nx >= (int64_t)set->dim[0]
        || ny >= (int64_t)set->dim[1] || nz >= (int64_t)set->dim[2])
        return false;
    *out = index_of(set, (uint32_t)nx, (uint32_t)ny, (uint32_t)nz);
    return true;
}

static bool point_in_brush(const mapgen_geometry_t *g,
                           const mapgen_geometry_brush_t *brush,
                           const float p[3])
{
    for (int a = 0; a < 3; a++)
        if (p[a] < brush->mins[a] - 1.0f || p[a] > brush->maxs[a] + 1.0f)
            return false;
    for (uint32_t s = 0; s < brush->num_sides; s++) {
        const mapgen_geometry_side_t *side =
            MapGenGeometry_Side(g, brush->first_side + s);
        if (!side || side->bevel)
            continue;
        const float d = side->normal[0] * p[0] + side->normal[1] * p[1]
                      + side->normal[2] * p[2] - side->dist;
        if (d > 0.03125f)
            return false;
    }
    return true;
}

/*
 * Which brush occupies a point, or UINT32_MAX.
 *
 * The world first, then the movers. A closed door fills a doorway with solid
 * that belongs to a brush model, and a shell cell it fills is the door's
 * rather than nobody's - but where a mover overlaps the world, the world is
 * what holds the map shut.
 */
static uint32_t brush_at(const mapgen_geometry_t *g, const float p[3])
{
    const uint32_t n = MapGenGeometry_NumBrushes(g);
    for (int pass = 0; pass < 2; pass++)
        for (uint32_t b = 0; b < n; b++) {
            const mapgen_geometry_brush_t *brush = MapGenGeometry_Brush(g, b);
            if (!brush || (pass == 0) != (brush->model == 0))
                continue;
            if (!(brush->contents & (MAPGEN_CONTENTS_SOLID
                                     | MAPGEN_CONTENTS_PLAYERCLIP
                                     | MAPGEN_CONTENTS_MONSTERCLIP
                                     | MAPGEN_CONTENTS_WINDOW)))
                continue;
            if (point_in_brush(g, brush, p))
                return b;
        }
    return UINT32_MAX;
}

/*
 * Who provides the solid between this air cell and that one?
 *
 * Asked by CROSSING the boundary, not by sampling the far cell's volume.
 *
 * The lattice is thirty-two units and q2dm1's walls are eight and sixteen, so
 * the cell beyond a wall is mostly on the far SIDE of it: nine samples spread
 * through that cell's middle can every one of them land in the void outside
 * the map while the wall they crossed is a brush. The room is then reported as
 * closed by solid nobody owns and refused for a seal it has. MEASURED on
 * q2dm1: eleven of seventeen rooms came out `fixed` this way, room 14 on a
 * SINGLE unowned cell of two hundred and seventy, and the whole F75 band rests
 * on rooms that can be carried.
 *
 * So: walk from the air cell's own centre towards the solid one in two-unit
 * steps, and the owner is the brush of the FIRST solid point on the way - the
 * piece of wall a player would walk into. A walk that finds solid no brush
 * provides is the real thing this check is for: the world outside the map.
 *
 * `out_first` is where solid began, for a witness; `out_entered` says whether
 * any solid was met at all.
 */
#define CROSS_STEP 2.0f
static uint32_t owner_across(const mapgen_bsp_t *bsp,
                             const mapgen_geometry_t *g,
                             const float from[3], const float to[3],
                             float out_first[3], bool *out_entered)
{
    float dir[3];
    float len = 0.0f;
    for (int a = 0; a < 3; a++) {
        dir[a] = to[a] - from[a];
        len += dir[a] * dir[a];
    }
    len = sqrtf(len);
    if (out_entered)
        *out_entered = false;
    if (len <= 0.0f)
        return UINT32_MAX;
    for (int a = 0; a < 3; a++)
        dir[a] /= len;
    /* A little past the far centre, because a wall may sit just beyond it:
       the cell is solid, so the solid is somewhere on this line. */
    const float reach = len + MAPGEN_BUNDLE_CELL * 0.5f;
    bool entered = false;
    uint32_t owner = UINT32_MAX;
    for (float d = CROSS_STEP; d <= reach && owner == UINT32_MAX;
         d += CROSS_STEP) {
        float q[3];
        for (int a = 0; a < 3; a++)
            q[a] = from[a] + dir[a] * d;
        if (!(MapGenBsp_PointContents(bsp, q) & MAPGEN_CONTENTS_SOLID))
            continue;
        if (!entered) {
            entered = true;
            if (out_first)
                memcpy(out_first, q, sizeof(float) * 3);
        }
        owner = brush_at(g, q);
    }
    if (out_entered)
        *out_entered = entered;
    return owner;
}

/* ---- ownership --------------------------------------------------------------- */

static void own_brush(mapgen_bundle_t *b, const mapgen_geometry_t *g,
                      uint32_t brush, mapgen_bundle_role_t role)
{
    if (brush >= MapGenGeometry_NumBrushes(g))
        return;
    if (b->owned_brush[brush]) {
        /* The strongest claim wins, and the roles are declared in that order. */
        const mapgen_bundle_role_t held =
            (mapgen_bundle_role_t)(b->owned_brush[brush] - 1);
        if (role < held) {
            b->owned_brush[brush] = (uint8_t)(role + 1);
            for (uint32_t i = 0; i < b->num_brushes; i++)
                if (b->brushes[i].brush == brush)
                    b->brushes[i].role = role;
        }
        return;
    }
    if (b->num_brushes >= MAPGEN_BUNDLE_MAX_BRUSHES)
        return;
    b->owned_brush[brush] = (uint8_t)(role + 1);
    mapgen_bundle_brush_t *entry = &b->brushes[b->num_brushes++];
    memset(entry, 0, sizeof(*entry));
    entry->brush = brush;
    entry->role = role;
}

static void count_boundary_cell(mapgen_bundle_t *b, uint32_t brush)
{
    for (uint32_t i = 0; i < b->num_brushes; i++)
        if (b->brushes[i].brush == brush) {
            b->brushes[i].boundary_cells++;
            return;
        }
}

/*
 * How many surfaces the compiler actually drew for a brush.
 *
 * Asked of the sides rather than of the face table, because a face carries no
 * brush index: the compiler cut the brushes into faces and did not write down
 * which brush each came from. A side flagged NODRAW, HINT or SKIP was never
 * going to be drawn, and a brush with none left is one the player can only
 * bump into.
 */
static uint32_t drawn_sides(const mapgen_geometry_t *g,
                            const mapgen_geometry_brush_t *brush)
{
    uint32_t drawn = 0;
    for (uint32_t s = 0; s < brush->num_sides; s++) {
        const mapgen_geometry_side_t *side =
            MapGenGeometry_Side(g, brush->first_side + s);
        if (!side || side->bevel)
            continue;
        if (side->flags & (MAPGEN_SURF_NODRAW | MAPGEN_SURF_HINT
                           | MAPGEN_SURF_SKIP))
            continue;
        drawn++;
    }
    return drawn;
}

static mapgen_bundle_role_t role_of(const mapgen_geometry_t *g, uint32_t brush)
{
    const mapgen_geometry_brush_t *b = MapGenGeometry_Brush(g, brush);
    if (!b)
        return MAPGEN_BUNDLE_ROLE_BOUNDARY;
    if (b->model != 0)
        return MAPGEN_BUNDLE_ROLE_MOVER;
    if (drawn_sides(g, b) == 0)
        return MAPGEN_BUNDLE_ROLE_CLIP;
    return MAPGEN_BUNDLE_ROLE_BOUNDARY;
}

/* ---- entities ----------------------------------------------------------------- */

static mapgen_anchor_kind_t anchor_kind(const char *classname)
{
    if (!classname)
        return MAPGEN_ANCHOR_OTHER;
    if (!strncmp(classname, "info_player", 11))
        return MAPGEN_ANCHOR_SPAWN;
    if (!strncmp(classname, "item_", 5) || !strncmp(classname, "weapon_", 7)
        || !strncmp(classname, "ammo_", 5))
        return MAPGEN_ANCHOR_ITEM;
    if (!strncmp(classname, "light", 5))
        return MAPGEN_ANCHOR_LIGHT;
    if (!strncmp(classname, "func_", 5))
        return MAPGEN_ANCHOR_MOVER;
    if (!strncmp(classname, "trigger_", 8))
        return MAPGEN_ANCHOR_TRIGGER;
    return MAPGEN_ANCHOR_OTHER;
}

/*
 * Where an entity is.
 *
 * A point entity says so itself. A brush entity often does not - a func_door
 * without an origin brush has no "origin" key at all - and its position is the
 * middle of the model it owns. Guessing from proximity would tie a door to
 * whichever room happened to be nearest its first brush, which is how a
 * mechanism gets cut in half.
 */
static bool entity_origin(const mapgen_geometry_t *g, uint32_t index,
                          float out[3])
{
    const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(g, index);
    if (!ent)
        return false;
    if (ent->has_origin) {
        memcpy(out, ent->origin, sizeof(float) * 3);
        return true;
    }
    if (!ent->model)
        return false;

    float mins[3] = { 1e30f, 1e30f, 1e30f };
    float maxs[3] = { -1e30f, -1e30f, -1e30f };
    bool any = false;
    const uint32_t n = MapGenGeometry_NumBrushes(g);
    for (uint32_t b = 0; b < n; b++) {
        const mapgen_geometry_brush_t *brush = MapGenGeometry_Brush(g, b);
        if (!brush || brush->model != ent->model)
            continue;
        for (int a = 0; a < 3; a++) {
            if (brush->mins[a] < mins[a]) mins[a] = brush->mins[a];
            if (brush->maxs[a] > maxs[a]) maxs[a] = brush->maxs[a];
        }
        any = true;
    }
    if (!any)
        return false;
    for (int a = 0; a < 3; a++)
        out[a] = (mins[a] + maxs[a]) * 0.5f;
    return true;
}

static void own_entity(mapgen_bundle_t *b, uint32_t entity)
{
    if (b->owned_entity[entity] || b->num_entities >= MAPGEN_BUNDLE_MAX_ENTITIES)
        return;
    b->owned_entity[entity] = 1;
    b->entities[b->num_entities++] = entity;
}

static bool same_name(const char *a, const char *b)
{
    return a && b && *a && !strcmp(a, b);
}

/*
 * The closure over target, targetname and killtarget, in BOTH directions.
 *
 * A door inside the room that a button outside opens is half a mechanism.
 * Moving either half alone leaves a map where the button does nothing, so the
 * bundle takes the whole mechanism or the operator is refused.
 */
static void close_over_targets(mapgen_bundle_t *b, const mapgen_geometry_t *g)
{
    const uint32_t n = MapGenGeometry_NumEntities(g);
    bool grew = true;
    while (grew) {
        grew = false;
        for (uint32_t owned = 0; owned < b->num_entities; owned++) {
            const uint32_t e = b->entities[owned];
            const char *target = MapGenGeometry_EntityValue(g, e, "target");
            const char *kill = MapGenGeometry_EntityValue(g, e, "killtarget");
            const char *name = MapGenGeometry_EntityValue(g, e, "targetname");

            for (uint32_t other = 0; other < n; other++) {
                if (b->owned_entity[other])
                    continue;
                const char *other_name =
                    MapGenGeometry_EntityValue(g, other, "targetname");
                const char *other_target =
                    MapGenGeometry_EntityValue(g, other, "target");
                const char *other_kill =
                    MapGenGeometry_EntityValue(g, other, "killtarget");

                if (same_name(target, other_name)
                    || same_name(kill, other_name)
                    || same_name(other_target, name)
                    || same_name(other_kill, name)) {
                    own_entity(b, other);
                    grew = true;
                }
            }
        }
    }
}

/* ---- sockets ------------------------------------------------------------------ */

static mapgen_socket_kind_t socket_kind(float width, const float normal[3])
{
    if (fabsf(normal[2]) > 0.7f)
        return MAPGEN_SOCKET_SHAFT;
    if (width < PLAYER_WIDTH * 1.5f)
        return MAPGEN_SOCKET_CRAWL;
    if (width < DOORWAY_WIDTH)
        return MAPGEN_SOCKET_DOORWAY;
    return MAPGEN_SOCKET_HALL;
}

static mapgen_socket_t *socket_to(mapgen_bundle_t *b, uint32_t peer)
{
    for (uint32_t i = 0; i < b->num_sockets; i++)
        if (b->sockets[i].peer == peer)
            return &b->sockets[i];
    return NULL;
}

/*
 * A way out the segmentation never wrote down.
 *
 * The link table records the saddles between basins the watershed flooded, and
 * two rooms can be joined through space too tight for it to have flooded at
 * all. That connection exists whatever the table says, and the bundle is the
 * thing standing there looking at it.
 *
 * Its width is left unstated rather than invented. Nothing measured a width
 * there, and a plausible number is the kind that gets believed later; what it
 * carries instead is its size in cells, which is measured.
 */
static mapgen_socket_t *derive_socket(mapgen_bundle_t *b, uint32_t peer,
                                      const float at[3])
{
    if (b->num_sockets >= MAPGEN_BUNDLE_MAX_SOCKETS)
        return NULL;
    mapgen_socket_t *socket = &b->sockets[b->num_sockets++];
    memset(socket, 0, sizeof(*socket));
    socket->link = UINT32_MAX;
    socket->peer = peer;
    socket->kind = MAPGEN_SOCKET_CRAWL;
    socket->derived = true;
    memcpy(socket->at, at, sizeof(float) * 3);
    return socket;
}

/*
 * Can `from` still reach `to` with this room taken out of the graph?
 *
 * This is the whole content of an obligation: a way out whose removal would
 * strand the room behind it is not a stylistic choice, and an operator that
 * narrows or closes it has broken the map whatever it did to the divergence.
 */
static bool connected_without(const mapgen_rooms_t *rooms, uint32_t without,
                              uint32_t from, uint32_t to)
{
    const uint32_t count = MapGenRooms_Count(rooms);
    if (from >= count || to >= count)
        return false;
    if (from == to)
        return true;

    uint8_t *seen = calloc(count, 1);
    uint32_t *queue = malloc(sizeof(uint32_t) * count);
    if (!seen || !queue) {
        free(seen);
        free(queue);
        return false;
    }
    uint32_t head = 0, tail = 0;
    seen[from] = 1;
    queue[tail++] = from;
    bool found = false;
    const uint32_t links = MapGenRooms_NumLinks(rooms);
    while (head < tail && !found) {
        const uint32_t at = queue[head++];
        for (uint32_t i = 0; i < links; i++) {
            const mapgen_room_link_t *link = MapGenRooms_Link(rooms, i);
            uint32_t next = UINT32_MAX;
            if (link->a == at)      next = link->b;
            else if (link->b == at) next = link->a;
            if (next == UINT32_MAX || next == without || next >= count
                || seen[next])
                continue;
            if (next == to) {
                found = true;
                break;
            }
            seen[next] = 1;
            queue[tail++] = next;
        }
    }
    free(seen);
    free(queue);
    return found;
}

static void find_sockets(mapgen_bundle_t *b, const mapgen_rooms_t *rooms)
{
    const uint32_t links = MapGenRooms_NumLinks(rooms);
    for (uint32_t i = 0; i < links && b->num_sockets < MAPGEN_BUNDLE_MAX_SOCKETS;
         i++) {
        const mapgen_room_link_t *link = MapGenRooms_Link(rooms, i);
        if (link->a != b->room && link->b != b->room)
            continue;

        mapgen_socket_t *socket = &b->sockets[b->num_sockets++];
        memset(socket, 0, sizeof(*socket));
        socket->link = i;
        socket->peer = link->a == b->room ? link->b : link->a;
        socket->width = link->width;
        memcpy(socket->at, link->at, sizeof(float) * 3);
        for (int a = 0; a < 3; a++)
            socket->normal[a] = link->a == b->room ? link->normal[a]
                                                   : -link->normal[a];
        socket->kind = socket_kind(link->width, socket->normal);
    }
}

/*
 * An obligation is a pair of ways out the rest of the map cannot join without
 * coming through this room.
 *
 * Settled last, because a derived socket is a way out like any other and a
 * pair that looked like a cut through this bundle may turn out to have a
 * second route the link table never recorded.
 */
static void find_obligations(mapgen_bundle_t *b, const mapgen_rooms_t *rooms)
{
    for (uint32_t i = 0; i < b->num_sockets; i++)
        for (uint32_t j = i + 1; j < b->num_sockets; j++)
            if (!connected_without(rooms, b->room, b->sockets[i].peer,
                                   b->sockets[j].peer)) {
                b->sockets[i].obligation = true;
                b->sockets[j].obligation = true;
            }
}

/* ---- the map, once ------------------------------------------------------------ */

static mapgen_bundle_result_t build_lattice(mapgen_bundle_set_t *set)
{
    const mapgen_bsp_model_t *world = MapGenBsp_Model(set->bsp, 0);
    if (!world)
        return MAPGEN_BUNDLE_ERR_ARGS;

    uint64_t cells = 1;
    for (int a = 0; a < 3; a++) {
        const float lo = floorf((world->mins[a] - MARGIN)
                                / MAPGEN_BUNDLE_CELL) * MAPGEN_BUNDLE_CELL;
        const float hi = ceilf((world->maxs[a] + MARGIN)
                               / MAPGEN_BUNDLE_CELL) * MAPGEN_BUNDLE_CELL;
        set->lo[a] = lo;
        set->dim[a] = (uint32_t)((hi - lo) / MAPGEN_BUNDLE_CELL) + 1;
        cells *= set->dim[a];
    }
    if (cells > MAPGEN_BUNDLE_MAX_CELLS)
        return MAPGEN_BUNDLE_ERR_TOO_LARGE;
    set->cells = (size_t)cells;

    set->cell_room = malloc(set->cells * sizeof(uint32_t));
    set->cell_solid = calloc(set->cells, 1);
    set->pocket = malloc(set->cells * sizeof(uint32_t));
    if (!set->cell_room || !set->cell_solid || !set->pocket)
        return MAPGEN_BUNDLE_ERR_MEMORY;

    for (uint32_t z = 0; z < set->dim[2]; z++)
        for (uint32_t y = 0; y < set->dim[1]; y++)
            for (uint32_t x = 0; x < set->dim[0]; x++) {
                const size_t at = index_of(set, x, y, z);
                float p[3];
                cell_centre(set, x, y, z, p);
                set->cell_room[at] = MapGenRooms_At(set->rooms, p);
                set->pocket[at] = NO_CELL;
                /* Solid ANYWHERE in the cell: a wall thinner than a cell has
                   its skin in the cell and its middle nowhere near the
                   centre. */
                for (int s = 0; s < 9 && !set->cell_solid[at]; s++) {
                    float q[3];
                    sample_of(p, s, q);
                    if (MapGenBsp_PointContents(set->bsp, q)
                        & MAPGEN_CONTENTS_SOLID)
                        set->cell_solid[at] = 1;
                }
            }
    return MAPGEN_BUNDLE_OK;
}

/*
 * The pockets of open space no room owns, and the rooms each one joins.
 *
 * The watershed floods what it can flood and leaves the tight places - the
 * skin along a wall, the gap under a step, the corner behind a pillar -
 * belonging to no basin. Those are not holes and they are not nothing: they
 * are how a great deal of a Quake II map is actually connected, and this
 * establishes what each of them joins instead of guessing.
 */
static mapgen_bundle_result_t label_pockets(mapgen_bundle_set_t *set)
{
    uint32_t *queue = malloc(set->cells * sizeof(uint32_t));
    set->pocket_capacity = 256;
    set->pocket_bits = calloc((size_t)set->pocket_capacity * PEER_BYTES, 1);
    if (!queue || !set->pocket_bits) {
        free(queue);
        return MAPGEN_BUNDLE_ERR_MEMORY;
    }

    for (uint32_t z = 0; z < set->dim[2]; z++)
      for (uint32_t y = 0; y < set->dim[1]; y++)
        for (uint32_t x = 0; x < set->dim[0]; x++) {
            const size_t seed = index_of(set, x, y, z);
            if (set->cell_solid[seed] || set->cell_room[seed] != UINT32_MAX
                || set->pocket[seed] != NO_CELL)
                continue;

            const uint32_t id = set->num_pockets++;
            if (id >= set->pocket_capacity) {
                const uint32_t grown = set->pocket_capacity * 2;
                uint8_t *bigger = realloc(set->pocket_bits,
                                          (size_t)grown * PEER_BYTES);
                if (!bigger) {
                    free(queue);
                    return MAPGEN_BUNDLE_ERR_MEMORY;
                }
                memset(bigger + (size_t)set->pocket_capacity * PEER_BYTES, 0,
                       (size_t)(grown - set->pocket_capacity) * PEER_BYTES);
                set->pocket_bits = bigger;
                set->pocket_capacity = grown;
            }
            uint32_t head = 0, tail = 0;
            set->pocket[seed] = id;
            queue[tail++] = (uint32_t)seed;

            while (head < tail) {
                const uint32_t at = queue[head++];
                const uint32_t cx = at % set->dim[0];
                const uint32_t cy = (at / set->dim[0]) % set->dim[1];
                const uint32_t cz = at / (set->dim[0] * set->dim[1]);
                for (int n = 0; n < 6; n++) {
                    size_t next;
                    if (!step(set, cx, cy, cz, n, &next))
                        continue;
                    if (set->cell_solid[next])
                        continue;
                    if (set->cell_room[next] != UINT32_MAX) {
                        join(set, id, set->cell_room[next]);
                        continue;
                    }
                    if (set->pocket[next] != NO_CELL)
                        continue;
                    set->pocket[next] = id;
                    queue[tail++] = (uint32_t)next;
                }
            }
        }

    free(queue);
    return MAPGEN_BUNDLE_OK;
}

/* ---- one bundle ---------------------------------------------------------------- */

static mapgen_bundle_result_t extract_one(mapgen_bundle_set_t *set,
                                          uint32_t room,
                                          mapgen_bundle_t **out)
{
    const mapgen_geometry_t *geometry = set->geometry;
    const uint32_t num_brushes = MapGenGeometry_NumBrushes(geometry);
    const uint32_t num_entities = MapGenGeometry_NumEntities(geometry);

    mapgen_bundle_t *b = calloc(1, sizeof(*b));
    if (!b)
        return MAPGEN_BUNDLE_ERR_MEMORY;
    b->room = room;
    for (int a = 0; a < 3; a++) {
        b->mins[a] = 1e30f;
        b->maxs[a] = -1e30f;
    }

    b->owned_brush = calloc(num_brushes ? num_brushes : 1, 1);
    b->owned_entity = calloc(num_entities ? num_entities : 1, 1);
    b->brushes = calloc(MAPGEN_BUNDLE_MAX_BRUSHES, sizeof(*b->brushes));
    b->entities = calloc(MAPGEN_BUNDLE_MAX_ENTITIES, sizeof(*b->entities));
    b->anchors = calloc(MAPGEN_BUNDLE_MAX_ANCHORS, sizeof(*b->anchors));
    b->surfaces = calloc(MAPGEN_BUNDLE_MAX_SURFACES, sizeof(*b->surfaces));
    if (!b->owned_brush || !b->owned_entity || !b->brushes || !b->entities
        || !b->anchors || !b->surfaces) {
        MapGenBundle_Free(b);
        return MAPGEN_BUNDLE_ERR_MEMORY;
    }

    find_sockets(b, set->rooms);

    /* --- the air, and what bounds it ------------------------------------ */

    for (uint32_t z = 0; z < set->dim[2]; z++)
      for (uint32_t y = 0; y < set->dim[1]; y++)
        for (uint32_t x = 0; x < set->dim[0]; x++) {
            const size_t at = index_of(set, x, y, z);
            if (set->cell_room[at] != room)
                continue;
            b->air_cells++;
            float here[3];
            cell_centre(set, x, y, z, here);
            for (int a = 0; a < 3; a++) {
                if (here[a] < b->mins[a]) b->mins[a] = here[a];
                if (here[a] > b->maxs[a]) b->maxs[a] = here[a];
            }

            for (int n = 0; n < 6; n++) {
                size_t next;
                if (!step(set, x, y, z, n, &next)) {
                    /* The lattice covers the map with two cells to spare, so
                       air at its edge is air outside the map: a hole, and the
                       only thing that can unseal a bundle. */
                    b->shell_cells++;
                    b->unaccounted++;
                    continue;
                }
                if (set->cell_room[next] == room)
                    continue;
                b->shell_cells++;

                float p[3];
                cell_centre(set, (uint32_t)(next % set->dim[0]),
                            (uint32_t)((next / set->dim[0]) % set->dim[1]),
                            (uint32_t)(next / (set->dim[0] * set->dim[1])), p);

                /* Another room's air: the watershed put the split there and
                   the two rooms genuinely open into each other. */
                if (set->cell_room[next] != UINT32_MAX) {
                    mapgen_socket_t *socket =
                        socket_to(b, set->cell_room[next]);
                    if (!socket) {
                        socket = derive_socket(b, set->cell_room[next], p);
                        b->undeclared++;
                    }
                    if (socket)
                        socket->cells++;
                    else
                        b->unaccounted++;
                    continue;
                }

                if (set->cell_solid[next]) {
                    /*
                     * The piece of wall BETWEEN the two cells, found by
                     * crossing it. See owner_across: sampling the far cell's
                     * own volume misses every wall thinner than the lattice,
                     * which on q2dm1 is every wall.
                     */
                    /*
                     * Two searches, and the reason each exists.
                     *
                     * A cell is SOLID here if any of nine samples of its
                     * volume is solid - see the segmentation above, which is
                     * deliberately generous so that a wall thinner than a cell
                     * is not missed. Ownership is asked at the same nine
                     * points, because those are the points that made the cell
                     * solid and asking anywhere else answers a different
                     * question.
                     *
                     * And before them, the CROSSING: the straight walk from
                     * this air cell's centre into that one. The lattice is
                     * thirty-two units and q2dm1's walls are eight and sixteen,
                     * so a wall can lie entirely between the two centres and
                     * have none of its body in either cell's nine samples. That
                     * is the case the nine alone cannot see, and it is the case
                     * q2dm1 is built out of: eleven of seventeen rooms were
                     * refused for a seal they have, room 14 on a SINGLE cell of
                     * two hundred and seventy.
                     *
                     * A third arrangement was tried and is worse: nine
                     * crossings spread over the shared face. Offset lines walk
                     * down the air beside a wall and meet no solid at all, so
                     * cells that are solid came back unreached - 9 rooms
                     * movable against 14. MEASURED, and this is why the pair
                     * below is the pair.
                     */
                    float first[3] = { 0.0f, 0.0f, 0.0f };
                    bool crossed = false, sampled = false;
                    uint32_t owner = owner_across(set->bsp, geometry, here, p,
                                                  first, &crossed);
                    if (owner == UINT32_MAX)
                        for (int s = 0; s < 9 && owner == UINT32_MAX; s++) {
                            float q[3];
                            sample_of(p, s, q);
                            if (!(MapGenBsp_PointContents(set->bsp, q)
                                  & MAPGEN_CONTENTS_SOLID))
                                continue;
                            if (!sampled) {
                                sampled = true;
                                if (!crossed)
                                    memcpy(first, q, sizeof(first));
                            }
                            owner = brush_at(geometry, q);
                        }
                    const bool entered = crossed || sampled;
                    if (owner != UINT32_MAX) {
                        const mapgen_geometry_brush_t *ob =
                            MapGenGeometry_Brush(geometry, owner);
                        /* A door or a lift closing the boundary is owned, and
                           it is worth knowing: what arrives with the room is a
                           mechanism, and the mover's own gates decide whether
                           it may travel. */
                        if (ob && ob->model)
                            b->seal_by_mover++;
                        own_brush(b, geometry, owner, role_of(geometry, owner));
                        count_boundary_cell(b, owner);
                        continue;
                    }
                    /*
                     * Solid with no brush behind it.
                     *
                     * Usually not a defect at all: outside the map the tree
                     * says solid and there are no brushes, because there is
                     * nothing there. The boundary is closed, so the room is
                     * SEALED - what the bundle cannot do is carry this piece
                     * of it, which is what `movable` answers.
                     *
                     * The two kinds are kept apart, because they are different
                     * facts about the map: solid the walk ENTERED and found no
                     * brush in is the world outside, and a boundary cell the
                     * walk never reached solid in at all is a hole in this
                     * measurement rather than in the map.
                     */
                    b->unowned_solid++;
                    /*
                     * And WHICH kind, because they are different facts.
                     *
                     * `exterior`: the walk between the two centres entered
                     * solid and found no brush in any of it. That is the world
                     * outside the map lying directly against this room, and
                     * the room genuinely cannot carry its own seal.
                     *
                     * `corner`: only the far cell's own samples found solid,
                     * so what is unowned is not between the two centres at all
                     * - it is up to forty-six units away at a corner of a cell
                     * the room merely touches. The cell is counted because the
                     * segmentation calls it solid, and saying so is better
                     * than pretending the two cases are one.
                     */
                    if (crossed)
                        b->unowned_exterior++;
                    else if (sampled)
                        b->unowned_corner++;
                    else
                        b->unowned_unreached++;
                    if (b->num_unowned_witness < MAPGEN_BUNDLE_WITNESSES) {
                        mapgen_bundle_witness_t *w =
                            &b->unowned_witness[b->num_unowned_witness++];
                        memcpy(w->air, here, sizeof(w->air));
                        memcpy(w->solid, entered ? first : p,
                               sizeof(w->solid));
                        w->entered = entered;
                    }
                    continue;
                }

                /*
                 * A pocket. One pocket has several mouths, and the cell is
                 * counted against each of them: it is the same cell seen from
                 * different ends, and attributing it to whichever end was
                 * reached first is what made rooms 6 and 7 of q2dm1 open onto
                 * room 0 while room 0 opened onto neither.
                 */
                const uint32_t id = set->pocket[next];
                if (id == NO_CELL) {
                    b->blind_cells++;
                    b->unaccounted++;
                    continue;
                }
                bool placed = false;
                const uint32_t named = MapGenRooms_Count(set->rooms);
                for (uint32_t peer = 0; peer < named; peer++) {
                    if (peer == room || !joins(set, id, peer))
                        continue;
                    mapgen_socket_t *socket = socket_to(b, peer);
                    if (!socket) {
                        socket = derive_socket(b, peer, p);
                        b->undeclared++;
                    }
                    if (socket) {
                        socket->cells++;
                        placed = true;
                    }
                }
                if (!placed) {
                    /* It comes back to this room and goes nowhere else: a nook
                       of this room the watershed was too coarse to name. */
                    b->nook_cells++;
                }
            }
        }

    find_obligations(b, set->rooms);
    b->sealed = b->unaccounted == 0 && b->air_cells > 0;

    /* --- the movers that reach into it ---------------------------------- */

    for (uint32_t br = 0; br < num_brushes; br++) {
        const mapgen_geometry_brush_t *brush =
            MapGenGeometry_Brush(geometry, br);
        if (!brush || brush->model == 0)
            continue;
        bool reaches = true;
        for (int a = 0; a < 3 && reaches; a++)
            if (brush->mins[a] > b->maxs[a] + MAPGEN_BUNDLE_CELL
                || brush->maxs[a] < b->mins[a] - MAPGEN_BUNDLE_CELL)
                reaches = false;
        if (reaches)
            own_brush(b, geometry, br, MAPGEN_BUNDLE_ROLE_MOVER);
    }

    /* --- the support closure -------------------------------------------- */

    const uint32_t bounding = b->num_brushes;
    for (uint32_t i = 0; i < bounding; i++) {
        if (b->brushes[i].role != MAPGEN_BUNDLE_ROLE_BOUNDARY)
            continue;
        const mapgen_geometry_brush_t *owned =
            MapGenGeometry_Brush(geometry, b->brushes[i].brush);
        if (!owned)
            continue;
        for (uint32_t other = 0; other < num_brushes; other++) {
            if (b->owned_brush[other])
                continue;
            const mapgen_geometry_brush_t *cand =
                MapGenGeometry_Brush(geometry, other);
            if (!cand || cand->model != 0)
                continue;
            bool touching = true;
            for (int a = 0; a < 3 && touching; a++)
                if (cand->mins[a] > owned->maxs[a] + 1.0f
                    || cand->maxs[a] < owned->mins[a] - 1.0f)
                    touching = false;
            /* Only what sits within the bundle's own extent: a wall that runs
               the length of the map touches this room and belongs to six
               others, and claiming it would make every bundle the whole map. */
            for (int a = 0; a < 3 && touching; a++)
                if (cand->mins[a] < b->mins[a] - MAPGEN_BUNDLE_CELL * 2.0f
                    || cand->maxs[a] > b->maxs[a] + MAPGEN_BUNDLE_CELL * 2.0f)
                    touching = false;
            if (touching)
                own_brush(b, geometry, other, MAPGEN_BUNDLE_ROLE_SUPPORT);
        }
    }

    /* --- movement-critical surfaces ------------------------------------- */

    for (uint32_t i = 0; i < b->num_brushes
                         && b->num_surfaces < MAPGEN_BUNDLE_MAX_SURFACES; i++) {
        const mapgen_geometry_brush_t *brush =
            MapGenGeometry_Brush(geometry, b->brushes[i].brush);
        if (!brush)
            continue;
        const bool ladder = (brush->contents & MAPGEN_CONTENTS_LADDER) != 0;
        for (uint32_t s = 0; s < brush->num_sides
                             && b->num_surfaces < MAPGEN_BUNDLE_MAX_SURFACES;
             s++) {
            const mapgen_geometry_side_t *side =
                MapGenGeometry_Side(geometry, brush->first_side + s);
            if (!side || side->bevel || side->area <= 0.0f)
                continue;
            /* A floor he stands on, or a wall he climbs. A ceiling is not a
               surface anyone was standing on when the demo said this route
               worked. */
            const bool floor = side->normal[2] > 0.7f;
            if (!floor && !ladder)
                continue;
            float above[3] = { side->center[0], side->center[1],
                               side->center[2] + MAPGEN_BUNDLE_CELL * 0.5f };
            if (floor && MapGenRooms_At(set->rooms, above) != room)
                continue;

            mapgen_bundle_surface_t *surface = &b->surfaces[b->num_surfaces++];
            surface->side = brush->first_side + s;
            memcpy(surface->center, side->center, sizeof(float) * 3);
            surface->area = side->area;
            surface->ladder = ladder;
        }
    }

    /* --- anchors, and the mechanisms they belong to ---------------------- */

    for (uint32_t e = 0; e < num_entities; e++) {
        float origin[3];
        if (!entity_origin(geometry, e, origin))
            continue;
        if (MapGenRooms_At(set->rooms, origin) != room)
            continue;
        own_entity(b, e);
    }
    /* A mover whose model reaches into the room belongs to it even when the
       middle of that model is somewhere else - a door standing in a doorway
       has half of itself in each room. */
    for (uint32_t e = 0; e < num_entities; e++) {
        const mapgen_geometry_entity_t *ent = MapGenGeometry_Entity(geometry, e);
        if (!ent || !ent->model || b->owned_entity[e])
            continue;
        for (uint32_t i = 0; i < b->num_brushes; i++) {
            const mapgen_geometry_brush_t *brush =
                MapGenGeometry_Brush(geometry, b->brushes[i].brush);
            if (brush && brush->model == ent->model) {
                own_entity(b, e);
                break;
            }
        }
    }
    close_over_targets(b, geometry);

    for (uint32_t i = 0; i < b->num_entities
                         && b->num_anchors < MAPGEN_BUNDLE_MAX_ANCHORS; i++) {
        const uint32_t e = b->entities[i];
        float origin[3] = { 0, 0, 0 };
        const bool placed = entity_origin(geometry, e, origin);
        mapgen_bundle_anchor_t *anchor = &b->anchors[b->num_anchors++];
        anchor->kind = anchor_kind(
            MapGenGeometry_EntityValue(geometry, e, "classname"));
        anchor->entity = e;
        memcpy(anchor->origin, origin, sizeof(float) * 3);
        anchor->inside = placed && MapGenRooms_At(set->rooms, origin) == room;
    }

    *out = b;
    return MAPGEN_BUNDLE_OK;
}

/* ---- the entry point ----------------------------------------------------------- */

mapgen_bundle_result_t MapGenBundle_Survey(const mapgen_bsp_t *bsp,
                                           const mapgen_geometry_t *geometry,
                                           const mapgen_rooms_t *rooms,
                                           mapgen_bundle_set_t **out)
{
    if (out)
        *out = NULL;
    if (!bsp || !geometry || !rooms || !out)
        return MAPGEN_BUNDLE_ERR_ARGS;

    mapgen_bundle_set_t *set = calloc(1, sizeof(*set));
    if (!set)
        return MAPGEN_BUNDLE_ERR_MEMORY;
    set->bsp = bsp;
    set->geometry = geometry;
    set->rooms = rooms;

    mapgen_bundle_result_t rc = build_lattice(set);
    if (rc == MAPGEN_BUNDLE_OK)
        rc = label_pockets(set);
    if (rc != MAPGEN_BUNDLE_OK) {
        MapGenBundleSet_Free(set);
        return rc;
    }

    const uint32_t count = MapGenRooms_Count(rooms);
    set->bundles = calloc(count ? count : 1, sizeof(*set->bundles));
    if (!set->bundles) {
        MapGenBundleSet_Free(set);
        return MAPGEN_BUNDLE_ERR_MEMORY;
    }
    for (uint32_t r = 0; r < count; r++) {
        rc = extract_one(set, r, &set->bundles[set->num_bundles]);
        if (rc != MAPGEN_BUNDLE_OK) {
            MapGenBundleSet_Free(set);
            return rc;
        }
        set->num_bundles++;
    }

    *out = set;
    return MAPGEN_BUNDLE_OK;
}

void MapGenBundleSet_Free(mapgen_bundle_set_t *set)
{
    if (!set)
        return;
    for (uint32_t i = 0; i < set->num_bundles; i++)
        MapGenBundle_Free(set->bundles[i]);
    free(set->bundles);
    free(set->cell_room);
    free(set->cell_solid);
    free(set->pocket);
    free(set->pocket_bits);
    free(set);
}

uint32_t MapGenBundleSet_Count(const mapgen_bundle_set_t *set)
{
    return set ? set->num_bundles : 0;
}

const mapgen_bundle_t *MapGenBundleSet_At(const mapgen_bundle_set_t *set,
                                          uint32_t room)
{
    return set && room < set->num_bundles ? set->bundles[room] : NULL;
}

uint32_t MapGenBundleSet_Pockets(const mapgen_bundle_set_t *set)
{
    return set ? set->num_pockets : 0;
}

void MapGenBundle_Free(mapgen_bundle_t *b)
{
    if (!b)
        return;
    free(b->owned_brush);
    free(b->owned_entity);
    free(b->brushes);
    free(b->entities);
    free(b->anchors);
    free(b->surfaces);
    free(b);
}

/* ---- what it knows ------------------------------------------------------------- */

bool MapGenBundle_Sealed(const mapgen_bundle_t *b)
{
    return b && b->sealed;
}

bool MapGenBundle_Movable(const mapgen_bundle_t *b)
{
    return b && b->sealed && b->unowned_solid == 0;
}

uint32_t MapGenBundle_Unaccounted(const mapgen_bundle_t *b)
{
    return b ? b->unaccounted : 0;
}

uint32_t MapGenBundle_UnownedSolid(const mapgen_bundle_t *b)
{
    return b ? b->unowned_solid : 0;
}

uint32_t MapGenBundle_UnownedExterior(const mapgen_bundle_t *b)
{
    return b ? b->unowned_exterior : 0;
}

uint32_t MapGenBundle_UnownedCorner(const mapgen_bundle_t *b)
{
    return b ? b->unowned_corner : 0;
}

uint32_t MapGenBundle_UnownedUnreached(const mapgen_bundle_t *b)
{
    return b ? b->unowned_unreached : 0;
}

uint32_t MapGenBundle_SealByMover(const mapgen_bundle_t *b)
{
    return b ? b->seal_by_mover : 0;
}

uint32_t MapGenBundle_NumUnownedWitness(const mapgen_bundle_t *b)
{
    return b ? b->num_unowned_witness : 0;
}

const mapgen_bundle_witness_t *MapGenBundle_UnownedWitness(
    const mapgen_bundle_t *b, uint32_t i)
{
    return (b && i < b->num_unowned_witness) ? &b->unowned_witness[i] : NULL;
}

uint32_t MapGenBundle_Undeclared(const mapgen_bundle_t *b)
{
    return b ? b->undeclared : 0;
}

uint32_t MapGenBundle_NookCells(const mapgen_bundle_t *b)
{
    return b ? b->nook_cells : 0;
}

uint32_t MapGenBundle_BlindCells(const mapgen_bundle_t *b)
{
    return b ? b->blind_cells : 0;
}

uint32_t MapGenBundle_Room(const mapgen_bundle_t *b)
{
    return b ? b->room : UINT32_MAX;
}

uint32_t MapGenBundle_AirCells(const mapgen_bundle_t *b)
{
    return b ? b->air_cells : 0;
}

uint32_t MapGenBundle_ShellCells(const mapgen_bundle_t *b)
{
    return b ? b->shell_cells : 0;
}

const float *MapGenBundle_Mins(const mapgen_bundle_t *b)
{
    return b ? b->mins : NULL;
}

const float *MapGenBundle_Maxs(const mapgen_bundle_t *b)
{
    return b ? b->maxs : NULL;
}

uint32_t MapGenBundle_NumBrushes(const mapgen_bundle_t *b)
{
    return b ? b->num_brushes : 0;
}

const mapgen_bundle_brush_t *MapGenBundle_Brush(const mapgen_bundle_t *b,
                                                uint32_t i)
{
    return b && i < b->num_brushes ? &b->brushes[i] : NULL;
}

uint32_t MapGenBundle_RoleCount(const mapgen_bundle_t *b,
                                mapgen_bundle_role_t role)
{
    uint32_t n = 0;
    if (b)
        for (uint32_t i = 0; i < b->num_brushes; i++)
            if (b->brushes[i].role == role)
                n++;
    return n;
}

uint32_t MapGenBundle_NumSockets(const mapgen_bundle_t *b)
{
    return b ? b->num_sockets : 0;
}

const mapgen_socket_t *MapGenBundle_Socket(const mapgen_bundle_t *b, uint32_t i)
{
    return b && i < b->num_sockets ? &b->sockets[i] : NULL;
}

uint32_t MapGenBundle_NumAnchors(const mapgen_bundle_t *b)
{
    return b ? b->num_anchors : 0;
}

const mapgen_bundle_anchor_t *MapGenBundle_Anchor(const mapgen_bundle_t *b,
                                                  uint32_t i)
{
    return b && i < b->num_anchors ? &b->anchors[i] : NULL;
}

uint32_t MapGenBundle_NumSurfaces(const mapgen_bundle_t *b)
{
    return b ? b->num_surfaces : 0;
}

const mapgen_bundle_surface_t *MapGenBundle_Surface(const mapgen_bundle_t *b,
                                                    uint32_t i)
{
    return b && i < b->num_surfaces ? &b->surfaces[i] : NULL;
}

uint32_t MapGenBundle_NumEntities(const mapgen_bundle_t *b)
{
    return b ? b->num_entities : 0;
}

uint32_t MapGenBundle_Entity(const mapgen_bundle_t *b, uint32_t i)
{
    return b && i < b->num_entities ? b->entities[i] : UINT32_MAX;
}

bool MapGenBundle_OwnsEntity(const mapgen_bundle_t *b, uint32_t entity)
{
    if (!b)
        return false;
    for (uint32_t i = 0; i < b->num_entities; i++)
        if (b->entities[i] == entity)
            return true;
    return false;
}

bool MapGenBundle_OwnsBrush(const mapgen_bundle_t *b, uint32_t brush)
{
    if (!b)
        return false;
    for (uint32_t i = 0; i < b->num_brushes; i++)
        if (b->brushes[i].brush == brush)
            return true;
    return false;
}

/* ---- the canonical text --------------------------------------------------------- */

typedef struct {
    char    *out;
    uint32_t size;
    uint32_t needed;
} canon_t;

static void put(canon_t *c, const char *text)
{
    for (const char *p = text; *p; p++) {
        if (c->out && c->needed + 1 < c->size)
            c->out[c->needed] = *p;
        c->needed++;
    }
}

static void put_u(canon_t *c, uint64_t v)
{
    char digits[24];
    snprintf(digits, sizeof(digits), "%llu", (unsigned long long)v);
    put(c, digits);
}

/* One quantum coarser than anything the compiler distinguishes, so two
   extractions of one donor cannot differ in the seventh decimal. */
static void put_f(canon_t *c, float v)
{
    char text[32];
    snprintf(text, sizeof(text), "%.3f", (double)v);
    put(c, text);
}

uint32_t MapGenBundle_CanonicalText(const mapgen_bundle_t *b, char *out,
                                    uint32_t size)
{
    canon_t c = { out, size, 0 };
    if (!b) {
        if (out && size)
            out[0] = '\0';
        return 0;
    }

    put(&c, "bundle 1 room=");
    put_u(&c, b->room);
    put(&c, b->sealed ? " sealed" : " unsealed");
    put(&c, MapGenBundle_Movable(b) ? " movable" : " fixed");
    put(&c, " air=");
    put_u(&c, b->air_cells);
    put(&c, " shell=");
    put_u(&c, b->shell_cells);
    put(&c, " open=");
    put_u(&c, b->unaccounted);
    put(&c, " unowned=");
    put_u(&c, b->unowned_solid);
    put(&c, " undeclared=");
    put_u(&c, b->undeclared);
    put(&c, " nooks=");
    put_u(&c, b->nook_cells);
    put(&c, "\n");

    for (uint32_t i = 0; i < b->num_brushes; i++) {
        put(&c, "B ");
        put_u(&c, b->brushes[i].brush);
        put(&c, " ");
        put(&c, MapGenBundle_RoleName(b->brushes[i].role));
        put(&c, " ");
        put_u(&c, b->brushes[i].boundary_cells);
        put(&c, "\n");
    }
    for (uint32_t i = 0; i < b->num_sockets; i++) {
        const mapgen_socket_t *s = &b->sockets[i];
        put(&c, "S ");
        put(&c, MapGenBundle_SocketName(s->kind));
        put(&c, " peer=");
        put_u(&c, s->peer);
        put(&c, " w=");
        put_f(&c, s->width);
        put(&c, " cells=");
        put_u(&c, s->cells);
        put(&c, s->obligation ? " obliged" : " free");
        put(&c, s->derived ? " derived" : " linked");
        put(&c, "\n");
    }
    for (uint32_t i = 0; i < b->num_anchors; i++) {
        const mapgen_bundle_anchor_t *a = &b->anchors[i];
        put(&c, "A ");
        put(&c, MapGenBundle_AnchorName(a->kind));
        put(&c, " ");
        put_u(&c, a->entity);
        put(&c, a->inside ? " inside" : " tied");
        put(&c, "\n");
    }
    put(&c, "M ");
    put_u(&c, b->num_surfaces);
    put(&c, "\n");

    if (out && size)
        out[c.needed < size ? c.needed : size - 1] = '\0';
    return c.needed + 1;
}

uint64_t MapGenBundle_Digest(const mapgen_bundle_t *b)
{
    const uint32_t needed = MapGenBundle_CanonicalText(b, NULL, 0);
    char *text = malloc(needed ? needed : 1);
    if (!text)
        return 0;
    MapGenBundle_CanonicalText(b, text, needed);

    uint64_t hash = 14695981039346656037ull;
    for (const char *p = text; *p; p++) {
        hash ^= (uint8_t)*p;
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}
