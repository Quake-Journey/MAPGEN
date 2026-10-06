/*
 * MapGenBundle - a room and everything that has to move with it.
 *
 * Codex, 2026-09-01, section 4.2: before any structural operator, extract a
 * single-donor GeometryBundle foundation. This is that foundation, and the
 * reason it comes first is the fork the PO rejected: an operator that works on
 * one brush side at a time cannot move a room, because it does not know what a
 * room IS. It pushes four hundred walls out by twenty units and the map is
 * still the donor with lumps on it.
 *
 * A bundle answers one question - if this room moved, what else would have to
 * move - and it answers it from the compiled donor rather than from the recipe
 * that made it, so it works on a map nobody annotated.
 *
 * --- what is in one --------------------------------------------------------
 *
 *   the boundary      every lattice cell of the room's air, and every cell of
 *                     solid touching it;
 *   ownership         which brushes those cells belong to, and in what role;
 *   the closure       the brushes that hold those brushes up, and the entities
 *                     that would be left pointing at nothing;
 *   anchors           the spawns, items, lights and movers inside it;
 *   sockets           every way out, typed by what fits through it;
 *   obligations       which of those ways out the rest of the map depends on.
 *
 * --- sealed, or refused ----------------------------------------------------
 *
 * A bundle is SEALED when every cell bounding its air is either solid this
 * bundle owns or a socket this bundle declares. An unsealed bundle is one with
 * a hole in it that nothing accounts for, and moving it would take the hole
 * along and leave the map open - which is exactly the defect the PO reported
 * as "BSP ne zamknuta, prosvechivaet skvoz uroven tonkoi liniei".
 *
 * So `sealed` is not advice. An operator may not transform an unsealed bundle,
 * and this reports how many cells were unaccounted for so the refusal can be
 * diagnosed instead of retried.
 *
 * On a donor it will nearly always be true, and that is the point rather than
 * a weakness: a donor was compiled without a leak. Where it earns its keep is
 * on a CANDIDATE - a map this generator just made - because a bundle that no
 * longer closes is precisely the defect the PO reported, and it is cheaper to
 * find here than in the compiler's leak file.
 *
 * --- what a compiled map cannot tell you -----------------------------------
 *
 * `func_detail` is a compile-time instruction, not a content flag: by the time
 * a BSP exists, a detail brush is world solid like any other and no amount of
 * reading can recover the author's intent. So a brush is classified by what it
 * DOES here - it bounds this room's air, it holds up something that does, it
 * clips a player without being drawn, or it belongs to a mover - and never by
 * a guess about what it was called in the editor.
 */

#ifndef MAPGEN_BUNDLE_H
#define MAPGEN_BUNDLE_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_rooms.h"

/* The same thirty-two units the rooms, the reachability search, the demo
   corpus and the divergence oracle use. One lattice, so all five can be
   talked about in one sentence. */
#define MAPGEN_BUNDLE_CELL      32.0f

/*
 * A place where a room's boundary is closed by solid no brush provides, and
 * the air cell it was seen from.
 *
 * Kept because "part of the seal is no brush" was a count and a count cannot
 * be argued with: eleven of q2dm1's seventeen rooms were refused on it, one of
 * them on a single cell, and the only way to tell a wall the measurement
 * missed from the world outside the map is to go and look at the place.
 */
typedef struct {
    float air[3];          /* the owned air cell this was seen from          */
    float solid[3];        /* where the crossing first met solid             */
    bool  entered;         /* whether it met any solid at all                */
} mapgen_bundle_witness_t;
#define MAPGEN_BUNDLE_WITNESSES 8u
#define MAPGEN_BUNDLE_MAX_CELLS 4194304u

#define MAPGEN_BUNDLE_MAX_BRUSHES 8192u
#define MAPGEN_BUNDLE_MAX_ENTITIES 512u
#define MAPGEN_BUNDLE_MAX_SOCKETS 64u
#define MAPGEN_BUNDLE_MAX_ANCHORS 256u
#define MAPGEN_BUNDLE_MAX_SURFACES 4096u

typedef enum {
    MAPGEN_BUNDLE_OK = 0,
    MAPGEN_BUNDLE_ERR_ARGS,
    MAPGEN_BUNDLE_ERR_MEMORY,
    MAPGEN_BUNDLE_ERR_NO_ROOM,
    MAPGEN_BUNDLE_ERR_TOO_LARGE
} mapgen_bundle_result_t;

const char *MapGenBundle_ResultName(mapgen_bundle_result_t r);

/*
 * What a brush is doing in this bundle.
 *
 * Ordered by precedence, because one brush can qualify for several and the
 * strongest claim wins: a mover is a mover even where it bounds the room, and
 * a brush the compiler drew nothing for is clip however it sits.
 */
typedef enum {
    MAPGEN_BUNDLE_ROLE_MOVER = 0,  /* belongs to a brush model, not the world */
    MAPGEN_BUNDLE_ROLE_CLIP,       /* world solid the compiler drew no face for */
    MAPGEN_BUNDLE_ROLE_BOUNDARY,   /* it bounds this room's air                */
    MAPGEN_BUNDLE_ROLE_SUPPORT,    /* it holds up something that does          */
    MAPGEN_BUNDLE_ROLE_COUNT
} mapgen_bundle_role_t;

const char *MapGenBundle_RoleName(mapgen_bundle_role_t role);

typedef struct {
    uint32_t             brush;
    mapgen_bundle_role_t role;
    uint32_t             boundary_cells;  /* cells of this room's shell it fills */
    uint32_t             faces;           /* render faces the compiler emitted   */
} mapgen_bundle_brush_t;

/*
 * A way out, typed by what actually fits through it.
 *
 * The width is the rooms segmentation's own: twice the clearance at the
 * narrowest point, which is the diameter of the largest sphere that passes.
 * A standing player is 32 wide and 56 tall, so the thresholds are his and not
 * round numbers chosen for looking tidy.
 */
typedef enum {
    MAPGEN_SOCKET_CRAWL = 0,   /* narrower than a standing player           */
    MAPGEN_SOCKET_DOORWAY,     /* one player wide                           */
    MAPGEN_SOCKET_HALL,        /* wide enough that it is not a door at all  */
    MAPGEN_SOCKET_SHAFT,       /* the way through it points up or down      */
    MAPGEN_SOCKET_COUNT
} mapgen_socket_kind_t;

const char *MapGenBundle_SocketName(mapgen_socket_kind_t kind);

typedef struct {
    mapgen_socket_kind_t kind;
    uint32_t link;             /* the rooms link this came from             */
    uint32_t peer;             /* the room on the other side                */
    float    at[3];
    float    normal[3];        /* out of the bundle, towards the peer       */
    float    width;

    /* How much of the bundle's own shell this way out actually is, in cells.
       The segmentation's width is measured at one point; this is the size of
       the whole opening, which is what an operator meaning to narrow or close
       it has to deal with. */
    uint32_t cells;

    /*
     * The rest of the map depends on this way out.
     *
     * Established by removing this room from the room graph and asking whether
     * the peer is still reachable from the rest of it. A socket that is the
     * peer's only way to everywhere else may not be narrowed or removed, and
     * that is a fact about the graph rather than a preference.
     */
    bool     obligation;

    /*
     * The bundle found this way out itself; the segmentation's link table does
     * not have it.
     *
     * Two rooms can be joined through space too tight for the watershed to
     * have flooded a basin into, and that connection exists whatever the table
     * says. A derived socket has no `width` - nothing measured one there, and
     * a plausible number is the kind that gets believed later - and states its
     * size in `cells` instead.
     */
    bool     derived;
} mapgen_socket_t;

typedef enum {
    MAPGEN_ANCHOR_SPAWN = 0,
    MAPGEN_ANCHOR_ITEM,
    MAPGEN_ANCHOR_LIGHT,
    MAPGEN_ANCHOR_MOVER,
    MAPGEN_ANCHOR_TRIGGER,
    MAPGEN_ANCHOR_OTHER,
    MAPGEN_ANCHOR_COUNT
} mapgen_anchor_kind_t;

const char *MapGenBundle_AnchorName(mapgen_anchor_kind_t kind);

typedef struct {
    mapgen_anchor_kind_t kind;
    uint32_t entity;
    float    origin[3];
    bool     inside;           /* it is IN the room, rather than pulled in by
                                  a target it is tied to */
} mapgen_bundle_anchor_t;

/*
 * A surface a player stands on, climbs or is carried by.
 *
 * Kept apart from the rest of the ownership because these are the sides an
 * operator may not move without re-proving the reachability it was serving:
 * the floor under a jump, the ladder out of a pit, the deck of a lift.
 */
typedef struct {
    uint32_t side;
    float    center[3];
    float    area;
    bool     ladder;
} mapgen_bundle_surface_t;

typedef struct mapgen_bundle_s mapgen_bundle_t;
typedef struct mapgen_bundle_set_s mapgen_bundle_set_t;

/*
 * Survey a compiled map: every room's bundle, from one reading of the map.
 *
 * One reading and not one per room, because the answer has to be consistent.
 * Extracting rooms independently produced a map in which rooms 6 and 7 of
 * q2dm1 each opened onto room 0 and room 0 opened onto neither of them: each
 * extraction looked at a different piece of the map and reached a different
 * conclusion about the same tight passage. The lattice and the pockets of
 * space no room owns are facts about the MAP, so they are established once and
 * every bundle reads the same ones.
 *
 * `geometry` must be the same donor `bsp` read as brushes - they are two views
 * of one map and a bundle needs both: the BSP knows where the air is and what
 * the compiler drew, and the geometry knows which brush a piece of solid
 * belongs to.
 */
mapgen_bundle_result_t MapGenBundle_Survey(const mapgen_bsp_t *bsp,
                                           const mapgen_geometry_t *geometry,
                                           const mapgen_rooms_t *rooms,
                                           mapgen_bundle_set_t **out);

void     MapGenBundleSet_Free(mapgen_bundle_set_t *set);
uint32_t MapGenBundleSet_Count(const mapgen_bundle_set_t *set);
const mapgen_bundle_t *MapGenBundleSet_At(const mapgen_bundle_set_t *set,
                                          uint32_t room);

/* How many pockets of space belonging to no room the map turned out to have.
   A diagnostic: a map with a great many of them is one the segmentation
   understood poorly. */
uint32_t MapGenBundleSet_Pockets(const mapgen_bundle_set_t *set);

/* Bundles belong to the survey that made them; this is for a bundle a caller
   owns outright, which for now is none of them. */
void MapGenBundle_Free(mapgen_bundle_t *bundle);

/*
 * Sealed: every cell bounding this bundle's air is accounted for.
 *
 * False is a refusal, not a warning. `MapGenBundle_Unaccounted` says how many
 * cells could not be attributed to owned solid or to a declared socket, which
 * is the number to diagnose rather than to tolerate.
 */
bool     MapGenBundle_Sealed(const mapgen_bundle_t *b);

/*
 * Sealed, AND every piece of that seal is a brush this bundle owns, AND every
 * way out is a socket it declares.
 *
 * The stronger property, and the one a relocation needs: a bundle can be
 * perfectly closed and still be unmovable, because part of what closes it is
 * the world outside the map - solid the tree asserts and no brush provides.
 * Reshaping inside a sealed bundle is legal; carrying one that is merely
 * sealed is not.
 *
 * Every way out being declared is not part of this, because it is not a
 * property a bundle can fail: a way out the link table missed becomes a
 * derived socket rather than a hole.
 */
bool     MapGenBundle_Movable(const mapgen_bundle_t *b);

/* Shell cells that are open space belonging to no pocket at all - which the
   survey cannot produce and which therefore means the lattice and the map have
   come apart. Zero on anything sound. */
uint32_t MapGenBundle_BlindCells(const mapgen_bundle_t *b);
uint32_t MapGenBundle_Unaccounted(const mapgen_bundle_t *b);

/* Of those, the cells where the compiled map HAS solid and no brush of this
   bundle accounts for it. A different defect from an open cell, and worth
   separating: the shell is there, and the bundle cannot carry it. */
uint32_t MapGenBundle_UnownedSolid(const mapgen_bundle_t *b);
/* And the breakdown: how many of those the crossing walked into solid for and
   found no brush in, how many it never reached solid in, how much of the
   boundary a brush model closes, and witnesses for the first few. */
uint32_t MapGenBundle_UnownedExterior(const mapgen_bundle_t *b);
uint32_t MapGenBundle_UnownedCorner(const mapgen_bundle_t *b);
uint32_t MapGenBundle_UnownedUnreached(const mapgen_bundle_t *b);
uint32_t MapGenBundle_SealByMover(const mapgen_bundle_t *b);
uint32_t MapGenBundle_NumUnownedWitness(const mapgen_bundle_t *b);
const mapgen_bundle_witness_t *MapGenBundle_UnownedWitness(
    const mapgen_bundle_t *b, uint32_t i);

/* Shell cells that open into a neighbouring room the segmentation's link table
   does not mention. They are accounted for - by a socket the bundle derives -
   and the count is kept because a room with many of them is one the
   segmentation understood poorly. */
uint32_t MapGenBundle_Undeclared(const mapgen_bundle_t *b);

/*
 * Cells of open space the segmentation named nobody's, which turn out to lead
 * back into this room and nowhere else.
 *
 * The watershed floods what it can flood and leaves the tight places - the
 * skin along a wall, the gap under a step, the corner behind a pillar -
 * belonging to no basin. Those are this room's, and establishing it by
 * following them rather than assuming it is the difference between six of
 * q2dm1's seventeen rooms being sealed and all of them being holes.
 */
uint32_t MapGenBundle_NookCells(const mapgen_bundle_t *b);

uint32_t MapGenBundle_Room(const mapgen_bundle_t *b);
uint32_t MapGenBundle_AirCells(const mapgen_bundle_t *b);
uint32_t MapGenBundle_ShellCells(const mapgen_bundle_t *b);
const float *MapGenBundle_Mins(const mapgen_bundle_t *b);
const float *MapGenBundle_Maxs(const mapgen_bundle_t *b);

uint32_t MapGenBundle_NumBrushes(const mapgen_bundle_t *b);
const mapgen_bundle_brush_t *MapGenBundle_Brush(const mapgen_bundle_t *b,
                                                uint32_t i);
/* How many brushes this bundle owns in one role. */
uint32_t MapGenBundle_RoleCount(const mapgen_bundle_t *b,
                                mapgen_bundle_role_t role);

uint32_t MapGenBundle_NumSockets(const mapgen_bundle_t *b);
const mapgen_socket_t *MapGenBundle_Socket(const mapgen_bundle_t *b,
                                           uint32_t i);

uint32_t MapGenBundle_NumAnchors(const mapgen_bundle_t *b);
const mapgen_bundle_anchor_t *MapGenBundle_Anchor(const mapgen_bundle_t *b,
                                                  uint32_t i);

uint32_t MapGenBundle_NumSurfaces(const mapgen_bundle_t *b);
const mapgen_bundle_surface_t *MapGenBundle_Surface(const mapgen_bundle_t *b,
                                                    uint32_t i);

/*
 * The entities that must travel with this bundle.
 *
 * Not only the ones standing in the room: the transitive closure over target,
 * targetname and killtarget in BOTH directions, because a door inside a room
 * that a button outside it opens is half a mechanism, and moving either half
 * alone leaves a map where the button does nothing.
 */
uint32_t MapGenBundle_NumEntities(const mapgen_bundle_t *b);
uint32_t MapGenBundle_Entity(const mapgen_bundle_t *b, uint32_t i);

/* Whether one entity is in the closure at all. */
bool MapGenBundle_OwnsEntity(const mapgen_bundle_t *b, uint32_t entity);
bool MapGenBundle_OwnsBrush(const mapgen_bundle_t *b, uint32_t brush);

/*
 * The canonical text of the bundle and its digest.
 *
 * Two extractions of the same room of the same donor produce the same text,
 * so a Snapshot can carry a bundle and a transaction can say which bundle an
 * edit was applied to.
 */
uint32_t MapGenBundle_CanonicalText(const mapgen_bundle_t *b, char *out,
                                    uint32_t size);
uint64_t MapGenBundle_Digest(const mapgen_bundle_t *b);

#endif /* MAPGEN_BUNDLE_H */
