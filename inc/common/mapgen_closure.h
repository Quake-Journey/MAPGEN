/*
 * MapGenClosure - everything one logical structure is made of.
 *
 * Codex, 2026-09-02, binding ruling Q2: self-exclusion must apply to the
 * ENTIRE dependency closure of a proposed edit, not to one brush index.
 *
 * The reason is a pair of opposite failures that come from the same mistake.
 * Ask "is there solid behind this wall, ignoring this brush" of a wall the
 * compiler split into four brushes, and three of them answer yes - the wall
 * blocks its own edit, and the operator concludes there is rock there. Ask it
 * of a staircase whose steps are separate brushes and remove one, and the
 * others say the map is still sealed, which it is, right up until a player
 * walks through the gap where a step used to be.
 *
 * So the unit an edit reasons about is not a brush. It is a CLOSURE: one
 * logical structure and everything that would have to go with it.
 *
 * --- what pulls something into a closure -----------------------------------
 *
 *   coplanar and split siblings   a wall the compiler cut into four is one
 *                                 wall, and the cut is an artifact of the
 *                                 compile rather than a fact about the map;
 *   touching support              a brush the seed holds up, or is held up by,
 *                                 with no other solid under it;
 *   clip and nodraw companions    the invisible brush that stops a player
 *                                 where the visible one is only decoration;
 *   model geometry                every brush of a mover the seed belongs to,
 *                                 because half a door is not a door;
 *   anchored entities             the entities standing on it, and the ones
 *                                 tied to those by target, targetname and
 *                                 killtarget, in both directions.
 *
 * Each of those is a rule about what the compiled map SAYS, not about what the
 * author meant. Nothing here reads a name, a recipe or an annotation.
 *
 * --- what it is for --------------------------------------------------------
 *
 * Two questions, and every carving operator asks both:
 *
 *     is there other solid here?      MapGenClosure_SolidWithout
 *     would removing this open the map?  MapGenClosure_Seals
 *
 * "Other" is the whole content of the first: solid that is not this closure.
 * A query that counted the closure's own brushes is the false-blockage defect,
 * and one that counted only the seed brush is the unsafe-deletion defect.
 */

#ifndef MAPGEN_CLOSURE_H
#define MAPGEN_CLOSURE_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

#define MAPGEN_CLOSURE_MAX_BRUSHES 4096u
#define MAPGEN_CLOSURE_MAX_ENTITIES 256u

typedef enum {
    MAPGEN_CLOSURE_OK = 0,
    MAPGEN_CLOSURE_ERR_ARGS,
    MAPGEN_CLOSURE_ERR_MEMORY,
    MAPGEN_CLOSURE_ERR_NO_SEED,
    MAPGEN_CLOSURE_ERR_TOO_LARGE   /* the closure ran away into the map */
} mapgen_closure_result_t;

const char *MapGenClosure_ResultName(mapgen_closure_result_t r);

/*
 * Why a brush is in the closure.
 *
 * Kept per brush because the reasons are not interchangeable when an edit is
 * refused: "your own wall blocked you" and "a door hinges on this" are
 * different things for an operator to do about it.
 */
typedef enum {
    MAPGEN_CLOSURE_SEED = 0,
    MAPGEN_CLOSURE_COPLANAR,   /* the same surface, cut by the compiler     */
    MAPGEN_CLOSURE_TOUCHING,   /* face to face with something already in    */
    MAPGEN_CLOSURE_MODEL,      /* the rest of a mover's own geometry        */
    MAPGEN_CLOSURE_REASON_COUNT
} mapgen_closure_reason_t;

const char *MapGenClosure_ReasonName(mapgen_closure_reason_t reason);

typedef struct mapgen_closure_s mapgen_closure_t;

/*
 * Build the closure around one brush.
 *
 * `depth` bounds how far the touching rule may travel: at one, only what the
 * seed itself touches; at two, what those touch, and so on. It is bounded
 * because "touching" is transitive and a Quake II map is one connected mass of
 * solid - an unbounded closure is the whole map, which is a true answer and a
 * useless one.
 */
mapgen_closure_result_t MapGenClosure_Build(const mapgen_geometry_t *geometry,
                                            uint32_t seed_brush,
                                            uint32_t depth,
                                            mapgen_closure_t **out);

void MapGenClosure_Free(mapgen_closure_t *closure);

uint32_t MapGenClosure_NumBrushes(const mapgen_closure_t *c);
uint32_t MapGenClosure_Brush(const mapgen_closure_t *c, uint32_t i);
mapgen_closure_reason_t MapGenClosure_Reason(const mapgen_closure_t *c,
                                             uint32_t brush);
bool MapGenClosure_Contains(const mapgen_closure_t *c, uint32_t brush);

uint32_t MapGenClosure_NumEntities(const mapgen_closure_t *c);
uint32_t MapGenClosure_Entity(const mapgen_closure_t *c, uint32_t i);

/*
 * Is there solid at this point that this closure is not made of?
 *
 * The question every carving operator has to ask before it removes anything,
 * and the reason the closure exists: asked of a brush index it answers wrongly
 * in both directions, and the two wrong answers are a refusal that should have
 * been allowed and a removal that should have been refused.
 */
bool MapGenClosure_SolidWithout(const mapgen_closure_t *c,
                                const mapgen_geometry_t *geometry,
                                const float point[3]);

/*
 * Does this closure hold the map shut?
 *
 * Sampled over the shell of the closure's own volume: for every cell of solid
 * the closure fills, is there other solid beside it, or would taking it away
 * put open space against open space that was not joined before. True means
 * removing it opens the map, and an operator that carves it anyway is the
 * "prosvechivaet skvoz uroven" defect.
 */
bool MapGenClosure_Seals(const mapgen_closure_t *c,
                         const mapgen_geometry_t *geometry,
                         const mapgen_bsp_t *bsp);

/* The bounds of everything in it. */
const float *MapGenClosure_Mins(const mapgen_closure_t *c);
const float *MapGenClosure_Maxs(const mapgen_closure_t *c);

#endif /* MAPGEN_CLOSURE_H */
