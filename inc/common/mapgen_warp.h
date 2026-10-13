/*
 * MAPGEN-1 - THE WARP: the donor's own plan stretched and squeezed, part by part, before anything is built onto it.
 *
 * The PO, 10.10.2026, four times in an hour: «я только за если генератор будет расширять исходного донора под цели
 * генерации ... размер новой карты в пределах 10-1000% от оригинала где достижимо»; «мне не важно чтобы сохранялся
 * каркас донора, а наоборот, я только за ВАРИАТИВНОСТИ»; «хочется именно менять донора и уже к нему пристраивать»;
 * «нужно чтобы генератор делал анализ до начала работ и не тратил время на бесконечные тесты».
 *
 * So the base itself changes first, and at once: along X and along Y the map is cut into parts, and every part gets
 * a factor of its own - one room twice as long, the corridor beside it shorter, the yard wider. Heights are kept,
 * so every step, ledge, jump and lift is what it was; a run of stairs only gets longer treads. The cuts are placed
 * by looking at the map first - never through a machine (a door, a lift, a train and its path), an areaportal, or a
 * push - and the whole is checked once, by one compile and one walk, before the first edit.
 *
 * The size is asked as an AREA (10..1000 % of the donor's), the factors' spread as a share (0 - the same factor
 * everywhere, 100 - parts from about half to about twice the mean). What the map can take is what it gets: no part
 * squeezed below MAPGEN_WARP_MIN_FACTOR (a corridor would close under a player), and the whole kept inside the
 * game's coordinate range.
 */
#ifndef MAPGEN_WARP_H
#define MAPGEN_WARP_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#include "common/mapgen_geometry.h"

#define MAPGEN_WARP_MAX_PARTS   8u
#define MAPGEN_WARP_MIN_FACTOR  0.75f
#define MAPGEN_WARP_MAX_FACTOR  4.0f
/* the game's coordinates are 12.3 fixed point: -4096 .. 4095.875; the warped map keeps a margin inside them */
#define MAPGEN_WARP_WORLD_HALF  4032.0f

typedef struct {
    uint32_t num[3];                                /* parts along X, Y and Z; 0 - that axis is not touched */
    float    at[3][MAPGEN_WARP_MAX_PARTS + 1];      /* the parts' edges in the donor, ascending */
    float    to[3][MAPGEN_WARP_MAX_PARTS + 1];      /* ... and where each edge lands */
    /*
     * The SHIFT (the PO's «менять донора»): the parts slid sideways against each other - along X, every part's Y offset
     * `lean[0]` at its edges (a straight run between), along Y every part's X offset `lean[1]`. Between two parts with
     * different offsets the rooms of one stand beside the other's moved over, and what crosses between them bends: a
     * corridor along X through parts leaning differently becomes a corridor that turns. Floors stay level, walls stay
     * upright. A part holding a machine never leans - it only moves over whole.
     */
    float    lean[2][MAPGEN_WARP_MAX_PARTS + 1];
    uint32_t shift_pct;
    /* and then the whole turned about its middle: quarter turns about Z, mirrored across X after */
    uint32_t turns;
    bool     mirror;
    uint32_t height_pct;                            /* the room above the highest standing place, percent */
    float    tall;                                  /* brief 18 D2: the heights' factor, sqrt(area) (1 none) */
    /* what was asked and what the map could take */
    uint32_t asked_size, asked_shape;               /* percent of area; percent of spread */
    uint32_t area_permille;                         /* the warped plan's area against the donor's */
    uint32_t cuts_refused;                          /* places a cut was wanted and a machine stood */
} mapgen_warp_t;

/*
 * The CEILINGS (the third axis): everything above `z0` - the highest place a player stands or a pickup lies, with a
 * player's height and a margin over it - is lifted, stretched by `height_pct` percent: the rooms of the top level grow
 * taller and the sky with them; nothing a player stands on moves, so no step, ledge, jump or lift changes. `z_lo` and
 * `z_hi` the world's bottom and top.
 */
bool MapGenWarp_PlanHeight(mapgen_warp_t *w, float z_lo, float z0, float z_hi, uint32_t height_pct);

/*
 * Brief 18 D2 (the PO, 11.10: «масштабирование у тебя почему-то прошло более вширь … не сохраняя пропорции»): a map
 * grown in plan grows as tall - every height times sqrt(area), about the world's bottom. Call after MapGenWarp_Plan;
 * MapGenWarp_PlanHeight then lifts the ceilings OVER the proportional height. A map shrunk keeps its heights (a player's
 * height does not shrink). False when nothing grows.
 */
bool MapGenWarp_PlanTall(mapgen_warp_t *w, float z_lo, float z_hi, float max_k);

/*
 * Brief 18 D2: what a player climbs in the donor and could not once the heights grow - a riser of a step, a ledge
 * jumped onto (up to 48) - gets a wedge on the floor in front of it, its slope 40 degrees once warped (walkable to 45),
 * its run on the lower floor; a flight becomes a saw of ramps with flats, the slope the stairs had. Added to `g` (the
 * donor's copy) before MapGenWarp_Apply; `ground` the donor's BSP, asked where the floors and the air are. The wedges
 * added.
 */
uint32_t MapGenWarp_AddRamps(mapgen_geometry_t *g, const mapgen_bsp_t *ground, const mapgen_warp_t *w);

/* Brief 18 D2: each pickup with a floor within the game's drop under it moved, in the donor before the warp, to
   where the warp leaves it as high over that floor as it was (a pickup grown 128 away from its floor hangs there).
   Returns how many moved. `MapGenWarp_SetKeepDrops(false)` is the RED: pickups grow away with the map. */
uint32_t MapGenWarp_KeepDrops(mapgen_geometry_t *g, const mapgen_bsp_t *ground, const mapgen_warp_t *w);
void MapGenWarp_SetKeepDrops(bool keep);
/* ... and RED: false - a player's start grows away from its floor with the map (q3t2 at x3.11: 46.6 over it,
   «over no floor»), the pickups kept. */
void MapGenWarp_SetKeepStarts(bool keep);
/* Brief 18 D2 RED: false - the ramps ask a point's LEAF what is there (a detail clip that touches the leaf closes
   every tread in it); true, the rule - the brushes the point is inside. */
void MapGenWarp_SetRampExact(bool exact);

/*
 * The TURN: the whole base turned about its middle - `turn` 0 none, 1..3 quarter turns, 4 mirrored, 5..7 mirrored and
 * turned, 8 one of the seven drawn from `seed`. Facings, doors, pushes and textures turn with it.
 */
void MapGenWarp_PlanTurn(mapgen_warp_t *w, uint64_t seed, int32_t turn);

/* The identity: nothing moves. */
void MapGenWarp_Identity(mapgen_warp_t *w);
bool MapGenWarp_IsIdentity(const mapgen_warp_t *w);

/* Where a donor coordinate lands on `axis` (0 X, 1 Y, 2 Z - only above the ceilings' line), and the factor of its part.
   Outside the edges the end parts carry on. Before the turn. */
float MapGenWarp_Point(const mapgen_warp_t *w, int axis, float v);
float MapGenWarp_Factor(const mapgen_warp_t *w, int axis, float v);

/*
 * `shift_pct` 0..100: how far the parts slide sideways against each other (a part leans up to ~24 degrees at 100).
 * The plan of the warp, from the donor's geometry: its world's extent, the bands no cut may cross (machines with
 * their travel, a train's path, areaportals, pushes, teleporters), the cuts in the bands left, the parts' factors
 * drawn from `seed`. `size_pct` 100 and `shape_pct` 0 give the identity.
 */
bool MapGenWarp_Plan(const mapgen_geometry_t *g, uint64_t seed, uint32_t size_pct, uint32_t shape_pct,
                     uint32_t shift_pct, mapgen_warp_t *out);

/*
 * The donor's geometry warped into a new one: every world brush a cut crosses split there into convex pieces (the
 * cut faces lie between two pieces of one solid - nothing draws them), every piece and every brush model moved by
 * its part's own straight map, textures keeping their size on a wall and travelling with their brush (a small brush -
 * a lamp, a button, a sign - and a machine keep theirs stretched with it), and the entities with the floor under
 * them: origins, facings turned by unequal factors, a push's flight stretched with its part, a light's reach.
 */
mapgen_geometry_result_t MapGenWarp_Apply(const mapgen_geometry_t *g, const mapgen_warp_t *w,
                                          mapgen_geometry_t **out);

/* One line for the progress and the map's description: the parts and their factors on each axis, the area. */
void MapGenWarp_Describe(const mapgen_warp_t *w, char *out, size_t cap);

#endif /* MAPGEN_WARP_H */
