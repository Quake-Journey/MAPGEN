/*
 * The flood family's obligation rules, as pure predicates.
 *
 * Kept apart from `mapgen_geometry_edit.c` for one reason: a rule that decides
 * whether a flood may take a way through the map must be testable in
 * milliseconds without compiling a map, and a `static` function eighteen
 * thousand lines into that file is not. `tools/mapgen_flood_rules_test.c`
 * includes this header and proves each rule, with a controlled RED built by
 * overriding the constant on its command line.
 */

#ifndef MAPGEN_FLOOD_RULES_H
#define MAPGEN_FLOOD_RULES_H

#include <stdbool.h>
#include <stdint.h>

/*
 * How high a Quake II player steps without jumping - `DIG_STEP_MAX` in the
 * geometry module, the same number the passage family's stairs are held to.
 * Overridable only so the fixture can build its controlled RED.
 */
#ifndef MAPGEN_FLOOD_STEP
#define MAPGEN_FLOOD_STEP 18.0f
#endif

/* How tall a standing player is; the head sample `Stands` asks is at +46. */
#define MAPGEN_FLOOD_BODY 56.0f

/*
 * Does a shell volume `[vol_lo, top]` over this column take the way at a
 * standing place whose floor is at `z`?
 *
 * Assignment 21 decision D12. The first version asked «does the new solid meet
 * the player at all», and a shell that rose one unit over a floor counted as a
 * wall - while the engine walks a player up eighteen. MEASURED 2026-09-13: that
 * refused the arena for the way at 1776 768 440, and the arena clears its cell
 * floor by only two cells, so any retreat ended it (ledger rows 200-202).
 *
 *   z >= top            nothing is taken: the shell stays under his feet;
 *   vol_lo <= z < top   his floor is INSIDE the new solid - a rise of a step
 *                       leaves a floor he steps up onto, more than that is a
 *                       wall;
 *   z < vol_lo          the shell is OVER his head - taken when his body
 *                       reaches its bottom, and no step allowance applies,
 *                       because nobody steps up into a ceiling. This is room
 *                       4's case at 1104 1120 624 (rows 160-161).
 */
static inline bool mapgen_flood_shell_takes_place(float z, float vol_lo,
                                                  float top)
{
    if (z >= top)
        return false;
    if (z >= vol_lo)
        return top - z > MAPGEN_FLOOD_STEP;
    return z + MAPGEN_FLOOD_BODY > vol_lo;
}

/*
 * Which rooms a flood may be tried in: every room JOINED to a room that holds a
 * player start through the room graph's ways.
 *
 * MEASURED 2026-09-13 (ledger row 220): the room finder's `reachable` has one
 * writer, and it sets the flag when a player START falls inside the room -
 * although its header calls it «a player can get here». On q2dm1 that is four
 * rooms of seventeen, so the passages the PO photographed empty («пустуют
 * проходы», `screenshots/quake150.jpg`) were never offered a drop of liquid.
 * Every one of q2dm1's rooms is joined to a start over its 25 ways.
 *
 * A way in the room graph is where two floods of clearance met, not a proof
 * that a player walks through it, so this is a CANDIDATE filter and nothing
 * more: every flood still has to pass the transaction's reach walk and route
 * proof on the compiled map. What it must not do is keep a room out that a
 * player plainly walks through.
 *
 * `start[r]` in, `joined[r]` out, `ways` is `num_ways` pairs of room indices;
 * a pair naming a room past `num_rooms` is ignored. Returns how many rooms are
 * joined. The define exists only for the fixture's RED, which restores the old
 * rule - a start in the room itself.
 */
#ifndef MAPGEN_FLOOD_JOIN_THROUGH_WAYS
#define MAPGEN_FLOOD_JOIN_THROUGH_WAYS 1
#endif

static inline uint32_t mapgen_flood_rooms_joined(uint32_t num_rooms,
                                                 const bool start[],
                                                 const uint32_t ways[][2],
                                                 uint32_t num_ways,
                                                 bool joined[])
{
    for (uint32_t r = 0; r < num_rooms; r++)
        joined[r] = start[r];
    /* a fixed point: each pass joins at least one more room or stops */
    bool grew = MAPGEN_FLOOD_JOIN_THROUGH_WAYS != 0;
    while (grew) {
        grew = false;
        for (uint32_t w = 0; w < num_ways; w++) {
            const uint32_t a = ways[w][0], b = ways[w][1];
            if (a >= num_rooms || b >= num_rooms || joined[a] == joined[b])
                continue;
            joined[a] = joined[b] = true;
            grew = true;
        }
    }
    uint32_t n = 0;
    for (uint32_t r = 0; r < num_rooms; r++)
        n += joined[r] ? 1u : 0u;
    return n;
}

/*
 * Is a flood still worth dealing once its hollow has retreated from the ways
 * its shell would have taken?
 *
 * Two bars that measure different things. `min_cells` is the absolute floor
 * against a puddle, so it is asked of what the hollow KEEPS. The share asks
 * «is this the room's water or a hole in its corner», so it is asked of what
 * the room OFFERED before the retreat. MEASURED 2026-09-13 (row 220): the
 * arena offers 50 of the 168 cells of its floor that can go under water and
 * keeps 41 - it gives nine back so a passage under its edge keeps its
 * headroom - which is 24.4 per cent, one cell under the bar, and it was
 * refused for that alone. A retreat made to keep a way is the family doing its
 * job, not the room turning into a puddle; the PO: «вон арена голая»
 * (`screenshots/quake149.jpg`).
 *
 * Before any retreat `offered == kept`, and this is the rule it always was.
 * The define exists only for the fixture's RED, which judges the share on
 * what is kept.
 */
#ifndef MAPGEN_FLOOD_SHARE_BEFORE_RETREAT
#define MAPGEN_FLOOD_SHARE_BEFORE_RETREAT 1
#endif

static inline bool mapgen_flood_worth_dealing(uint32_t offered, uint32_t kept,
                                              uint32_t floor_cells,
                                              uint32_t min_cells,
                                              uint32_t min_share)
{
    if (kept < min_cells)
        return false;
    const uint64_t judged = MAPGEN_FLOOD_SHARE_BEFORE_RETREAT ? offered : kept;
    return !floor_cells
        || 100u * judged >= (uint64_t)min_share * floor_cells;
}

/*
 * Is this room a PASSAGE - a place a room-sized flood cannot fit across?
 *
 * A room's flood keeps `margin` of dry floor on every side of the room's box,
 * and the mask needs two cells of `pitch` across. MEASURED 2026-09-13 (ledger
 * rows 225, 228): ten of q2dm1's seventeen rooms - its corridors and
 * connectors, 128 to 256 units wide - come out under two cells across that
 * inset and were refused before a single cell was probed, which is exactly
 * where the PO sees «пустуют проходы» (`screenshots/quake150.jpg`).
 *
 * A passage floods differently (see `deal_floods`): no dry margin, a bottom a
 * player steps up out of, water only, and a count of its own. The test is the
 * same arithmetic the room flood refuses on, `floor(w / pitch) < 2`, so a room
 * the PO has already seen flooded - room 4 - stays a room. The define exists
 * only for the fixture's RED, which restores «no passage is ever flooded».
 */
#ifndef MAPGEN_FLOOD_PASSAGES
#define MAPGEN_FLOOD_PASSAGES 1
#endif

/* How deep a passage's hollow is: the engine's step, so the bottom is walked
   out of rather than jumped out of; the surface stands 8 under the floor, so
   the water over that bottom is 10 deep. */
#define MAPGEN_FLOOD_PASSAGE_DEPTH 18.0f

static inline bool mapgen_flood_is_passage(float min_x, float min_y,
                                           float max_x, float max_y,
                                           float margin, float pitch)
{
    if (!MAPGEN_FLOOD_PASSAGES)
        return false;
    return max_x - min_x - 2.0f * margin < 2.0f * pitch
        || max_y - min_y - 2.0f * margin < 2.0f * pitch;
}

/*
 * D17, its premise corrected (ledger row 273): is the floor under this air a
 * cell's own?
 *
 * A ROOM's cell is its floor when the finder gave the air over it to this very
 * room, and that stays. A PASSAGE's cell asked for air of ANY room, on the
 * premise that the watershed hands a corridor's cells to the rooms it leads out
 * of - and 79 of corridor 12's 168 cells stood under air of no room (row 267).
 * `segment` is one pass in falling clearance and leaves a narrow cell no
 * neighbour had claimed when its turn came, and the flood's cell centres fall
 * on the finder's lattice borders. For a passage the question is the one the
 * room id stood for: whether the air point over the floor is open.
 *
 * The define exists only for the fixture's RED, which asks the room id again.
 */
#ifndef MAPGEN_FLOOD_PASSAGE_OPEN_AIR
#define MAPGEN_FLOOD_PASSAGE_OPEN_AIR 1
#endif

static inline bool mapgen_flood_air_ours(bool passage, uint32_t owner,
                                         uint32_t room, bool air_open)
{
    if (!passage)
        return owner == room;
    return MAPGEN_FLOOD_PASSAGE_OPEN_AIR ? air_open : owner != UINT32_MAX;
}

/*
 * D23 (a) (assignment 23, ledger row 279): does a thing standing in a cell
 * refuse the cell?
 *
 * For a ROOM anything standing there refuses it, as it always has. A PASSAGE's
 * water is ten units over a bottom sunk eighteen, and a pickup dropped to that
 * bottom stands with its origin five units over the surface: waded to, not
 * drowned. `MapGenGeometry_DrownedEntities` tests an entity's written origin
 * against the liquid, and the flood's build moves no entity. A player start
 * and every other entity still refuse the cell.
 *
 * The define exists only for the fixture's RED, which refuses pickups again.
 */
#ifndef MAPGEN_FLOOD_PASSAGE_KEEPS_PICKUPS
#define MAPGEN_FLOOD_PASSAGE_KEEPS_PICKUPS 1
#endif

static inline bool mapgen_flood_thing_refuses(bool passage, bool pickup)
{
    if (passage && pickup)
        return !MAPGEN_FLOOD_PASSAGE_KEEPS_PICKUPS;
    return true;
}

/*
 * A ring cell whose shell would take something - a way, a pickup, a machine's
 * travel: is that cell LEFT OUT, or does the hollow retreat from it?
 *
 * `near` is the Chebyshev distance, in cells, from the ring cell to the nearest
 * cell of the hollow: 1 for a cell touching it (corners included), 2 or 3 for
 * the ring's extra thickness. The inner cell is the seal - it stands from under
 * the hollow's slab up to the line or the floor, all the way round - so when
 * IT would take something the hollow has to move away. An outer cell is
 * thickness only, and it yields.
 *
 * MEASURED 2026-09-13 (ledger rows 229-230): the arena's outer ring cells at
 * 1776 960..992 stood in lift `*1`'s travel and the gate refused the flood,
 * and the ring's answer to every other obligation - a way, a pickup - was to
 * push the whole hollow back three cells: six cells of the arena, eighteen of
 * room 2, eleven of room 4. The three-cell width itself answered a leak whose
 * cause was later found to be q2dm1's own pool under room 1 (row 230).
 *
 * Returns true when the cell is left out. The define exists only for the
 * fixture's RED, which restores «every obligation pushes the hollow back».
 */
#ifndef MAPGEN_FLOOD_RING_YIELDS
#define MAPGEN_FLOOD_RING_YIELDS 1
#endif

/* (`cells_out`, not `near`: MinGW's windef.h still defines `near` away) */
static inline bool mapgen_flood_ring_cell_yields(int cells_out, bool takes)
{
    return MAPGEN_FLOOD_RING_YIELDS && takes && cells_out >= 2;
}

/*
 * A floor over a ROOM: may it flood, and how deep?
 *
 * MEASURED 2026-09-13 (ledger rows 237-238): the arena's big middle floor -
 * 190 cells, the floor the PO photographed and called «огромная площадь» -
 * is a slab 10 units thick over a corridor with 112 units of headroom, and the
 * mask refused every cell of it for «a room under» at every depth. A flood's
 * own slab closes a hollow from below whatever is under it; the question is
 * only what the room under it has left.
 *
 * `mapgen_flood_headroom_after`: the room under a floor at `floor_z`, whose
 * ceiling is `room_ceiling` and floor `room_floor`, once a hollow `depth` deep
 * with a slab `slab` thick is cut above it - its ceiling becomes the slab's
 * underside where that is the lower of the two.
 *
 * `mapgen_flood_room_under_keeps_headroom`: at least 72 left - a player's 56
 * and a step. The ring's D8 test keeps every place under a ring cell; this
 * keeps every place under the hollow itself.
 *
 * `mapgen_flood_goes_shallow`: a room is counted at the ambition's depth and
 * at 32, and floods at 32 only when that puts MORE of its floor under water -
 * at equal counts the deeper stays, so a room over rock keeps its 90.
 *
 * The two defines exist only for the fixture's REDs.
 */
#ifndef MAPGEN_FLOOD_OVER_ROOMS
#define MAPGEN_FLOOD_OVER_ROOMS 1
#endif
#ifndef MAPGEN_FLOOD_DEPTH_BY_CELLS
#define MAPGEN_FLOOD_DEPTH_BY_CELLS 1
#endif

#define MAPGEN_FLOOD_HEADROOM_MIN   72.0f
#define MAPGEN_FLOOD_SHALLOW_DEPTH  32.0f

static inline float mapgen_flood_headroom_after(float floor_z, float depth,
                                                float slab, float room_ceiling,
                                                float room_floor)
{
    const float slab_under = floor_z - depth - slab;
    const float ceiling = slab_under < room_ceiling ? slab_under : room_ceiling;
    return ceiling - room_floor;
}

static inline bool mapgen_flood_room_under_keeps_headroom(float headroom)
{
    return MAPGEN_FLOOD_OVER_ROOMS && headroom >= MAPGEN_FLOOD_HEADROOM_MIN;
}

static inline bool mapgen_flood_goes_shallow(uint32_t deep_cells,
                                             uint32_t shallow_cells)
{
    return MAPGEN_FLOOD_DEPTH_BY_CELLS && shallow_cells > deep_cells;
}

/*
 * D9 against the baseline: is an entrance pair answered?
 *
 * MEASURED 2026-09-13 (ledger rows 234, 239): D9 asked every entrance of a
 * flood's box to reach entrance 0 and back INSIDE the box, and the arena's box
 * holds places the baseline itself cannot join there - a raised block crosses
 * it - so the arena failed 23 of 62 pairs with or without water. A pair the
 * candidate does not join is charged to the flood only when the BASELINE joins
 * it inside the same box; a pair the baseline could not join either was not
 * separated by the flood. A walled passage - Codex's counterexample, joined
 * before and not after - is still refused.
 *
 * The define exists only for the fixture's RED: every pair must be joined.
 */
#ifndef MAPGEN_FLOOD_PAIRS_AGAINST_BASELINE
#define MAPGEN_FLOOD_PAIRS_AGAINST_BASELINE 1
#endif

static inline bool mapgen_flood_pair_answered(bool candidate_joins,
                                              bool baseline_joins)
{
    if (candidate_joins)
        return true;
    return MAPGEN_FLOOD_PAIRS_AGAINST_BASELINE && !baseline_joins;
}

/*
 * D29 (assignment 24, ledger row 286): does a PASSAGE's cell clash with an
 * earlier flood - on the same storey?
 *
 * D17's test asked x and y alone, grown by the dry margin, so corridor 14 -
 * floor 336, running under the arena's lake at 416..448 - was refused «75 by
 * an earlier flood» at ambition 80 (assignment 23, `round30/s0`). A passage's
 * column runs from its floor less its sunk depth and the rock under it, up to
 * its floor plus a standing player; a flood's from its hollow's bottom less the
 * rock under it, up to its floor. They clash where the footprints meet AND the
 * columns overlap. A ROOM keeps the two-dimensional test, which is not asked
 * here.
 *
 * `lo`/`hi` are the flood's box: x and y its footprint, `lo[2]` its hollow's
 * bottom and `hi[2]` its floor. The define exists only for the fixture's RED,
 * which asks x and y alone again.
 */
#ifndef MAPGEN_FLOOD_PASSAGE_CLASH_TAKES_HEIGHT
#define MAPGEN_FLOOD_PASSAGE_CLASH_TAKES_HEIGHT 1
#endif

static inline bool mapgen_flood_passage_clashes(float x, float y, float floor_z,
                                                float rock_under, float margin,
                                                const float lo[3],
                                                const float hi[3])
{
    if (x < lo[0] - margin || x > hi[0] + margin
        || y < lo[1] - margin || y > hi[1] + margin)
        return false;
    if (!MAPGEN_FLOOD_PASSAGE_CLASH_TAKES_HEIGHT)
        return true;
    const float mine_lo = floor_z - MAPGEN_FLOOD_PASSAGE_DEPTH - rock_under;
    const float mine_hi = floor_z + MAPGEN_FLOOD_BODY;
    const float theirs_lo = lo[2] - rock_under;
    const float theirs_hi = hi[2];
    return mine_lo < theirs_hi && theirs_lo < mine_hi;
}

#endif /* MAPGEN_FLOOD_RULES_H */
