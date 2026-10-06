/*
 * The flood family's obligation rules, proved without compiling a map.
 *
 *     gcc -std=c17 -Isrc/mapgen tools/mapgen_flood_rules_test.c -o t && t
 *
 * Controlled RED, one define per rule, and each must fail EXACTLY its own
 * cases - a rule whose fixture passes with the rule removed proves nothing:
 *
 *     -DMAPGEN_FLOOD_STEP=0.0f                 2 failures (the step cases)
 *     -DMAPGEN_FLOOD_JOIN_THROUGH_WAYS=0       3 failures (passage 5,
 *                                              connector 11, the count)
 *     -DMAPGEN_FLOOD_SHARE_BEFORE_RETREAT=0    1 failure  (the arena)
 *     -DMAPGEN_FLOOD_PASSAGES=0                3 failures (corridors 12 and
 *                                              14, connector 9)
 *     -DMAPGEN_FLOOD_RING_YIELDS=0             2 failures (the two outer
 *                                              cells that take something)
 *     -DMAPGEN_FLOOD_OVER_ROOMS=0              2 failures (the arena's middle
 *                                              at 32, the room deeper than
 *                                              the slab)
 *     -DMAPGEN_FLOOD_DEPTH_BY_CELLS=0          1 failure  (the arena goes
 *                                              shallow)
 *     -DMAPGEN_FLOOD_PAIRS_AGAINST_BASELINE=0  1 failure  (the excused pair)
 *     -DMAPGEN_FLOOD_PASSAGE_OPEN_AIR=0        2 failures (corridor 12's cell
 *                                              under no room's air, the
 *                                              passage cell under rock)
 *     -DMAPGEN_FLOOD_PASSAGE_KEEPS_PICKUPS=0   1 failure  (corridor 12's
 *                                              item_health)
 *     -DMAPGEN_FLOOD_PASSAGE_CLASH_TAKES_HEIGHT=0
 *                                          1 failure  (corridor 14 under
 *                                              the arena's lake)
 *
 * The heights are real ones, and the first version of this file got them
 * wrong in a way worth keeping written down: it set the shell's TOP to the
 * hollow's floor (679), so «a floor 17 under the top» fell BELOW the volume's
 * bottom and landed in the ceiling branch - GREEN and RED failed identically,
 * which is how it was caught. A ring cell's shell reaches the water line.
 *
 * Room 4: floor 768, depth 89, so the shell starts at 663 (768 - 89 - 16) and
 * a ring cell's top is the water line, 760. The arena: floor 448, depth 90, the
 * shell starts at 342 and its top at the way that refused it was 440 (S0).
 *
 * The room graph is q2dm1's own, printed by `tools/mapgen_rooms_dump.c` on
 * 2026-09-13 (ledger row 220): 17 rooms, 25 ways, starts in rooms 0, 1, 2 and
 * 4. Room 17 is invented - a room no way reaches.
 */

#include <stdio.h>

#include "mapgen_flood_rules.h"

static int failures;

static void expect(const char *name, bool got, bool want)
{
    printf("  %s  %s\n", got == want ? "PASS" : "FAIL", name);
    if (got != want)
        failures++;
}

int main(void)
{
    const float vol_lo = 663.0f, top = 760.0f;

    printf("D12: a step is not a wall\n");
    expect("a floor 17 under the shell top is a step, not a wall",
           mapgen_flood_shell_takes_place(top - 17.0f, vol_lo, top), false);
    expect("a floor 19 under the shell top is a wall",
           mapgen_flood_shell_takes_place(top - 19.0f, vol_lo, top), true);
    expect("a floor AT the shell top is untouched",
           mapgen_flood_shell_takes_place(top, vol_lo, top), false);
    expect("a floor over the shell top is untouched",
           mapgen_flood_shell_takes_place(top + 40.0f, vol_lo, top), false);
    expect("room 4's place at 624 loses its headroom (rows 160-161)",
           mapgen_flood_shell_takes_place(624.0f, vol_lo, top), true);
    expect("a passage 60 under the shell keeps its headroom",
           mapgen_flood_shell_takes_place(vol_lo - 60.0f, vol_lo, top), false);
    expect("no step allowance under a ceiling: 40 under the shell is taken",
           mapgen_flood_shell_takes_place(vol_lo - 40.0f, vol_lo, top), true);
    expect("the arena's way at 439.875 under a shell top of 440 is a step (S0)",
           mapgen_flood_shell_takes_place(439.875f, 342.0f, 440.0f), false);

    printf("H1: a room joined to a start through the ways may flood\n");
    static const uint32_t ways[25][2] = {
        { 1, 3 },  { 0, 14 }, { 0, 1 },  { 0, 15 }, { 15, 16 },
        { 0, 16 }, { 3, 8 },  { 8, 11 }, { 0, 9 },  { 0, 10 },
        { 9, 10 }, { 0, 2 },  { 1, 4 },  { 0, 4 },  { 4, 5 },
        { 0, 5 },  { 1, 6 },  { 1, 12 }, { 2, 12 }, { 1, 7 },
        { 6, 7 },  { 7, 12 }, { 6, 12 }, { 10, 13 }, { 0, 13 },
    };
    bool start[18] = { false };
    start[0] = start[1] = start[2] = start[4] = true;
    bool joined[18];
    const uint32_t n = mapgen_flood_rooms_joined(18u, start, ways, 25u, joined);
    expect("room 4, which holds a start, is joined", joined[4], true);
    expect("passage 5, one way from room 4, is joined", joined[5], true);
    expect("connector 11, three ways from room 1 (1-3-8-11), is joined",
           joined[11], true);
    expect("room 17, which no way reaches, is not joined", joined[17], false);
    expect("q2dm1 joins all 17 of its rooms", n == 17u, true);

    printf("H2: the share on what was offered, the floor on what is kept\n");
    expect("the arena, 50 offered and 41 kept of 168, is worth dealing",
           mapgen_flood_worth_dealing(50u, 41u, 168u, 32u, 25u), true);
    expect("room 2, 38 offered and 30 kept of 128, is under the floor of 32",
           mapgen_flood_worth_dealing(38u, 30u, 128u, 32u, 25u), false);
    expect("a puddle of 20 cells is refused whatever its share",
           mapgen_flood_worth_dealing(20u, 20u, 40u, 32u, 25u), false);
    expect("room 4, 146 offered and 135 kept of 213, is worth dealing",
           mapgen_flood_worth_dealing(146u, 135u, 213u, 32u, 25u), true);
    expect("40 of 200 with no retreat is under the share",
           mapgen_flood_worth_dealing(40u, 40u, 200u, 32u, 25u), false);

    printf("H3: a room a room-sized flood cannot cross is a passage\n");
    expect("corridor 12, 896 by 192, is a passage",
           mapgen_flood_is_passage(1008, -112, 1904, 80, 96, 32), true);
    expect("corridor 14, 160 by 480, is a passage",
           mapgen_flood_is_passage(1392, 592, 1552, 1072, 96, 32), true);
    expect("connector 9, 256 by 224, is a passage (one cell across)",
           mapgen_flood_is_passage(1776, 784, 2032, 1008, 96, 32), true);
    expect("room 4, the flood the PO accepted, stays a room",
           mapgen_flood_is_passage(400, 848, 1168, 1776, 96, 32), false);
    expect("room 3, 352 by 608, stays a room",
           mapgen_flood_is_passage(16, -304, 368, 304, 96, 32), false);
    expect("a 256 by 256 box keeps two cells across and stays a room",
           mapgen_flood_is_passage(0, 0, 256, 256, 96, 32), false);

    printf("H4: an outer ring cell yields, a cell touching the hollow does not\n");
    expect("the arena's cell two out, in lift *1's travel, is left out",
           mapgen_flood_ring_cell_yields(2, true), true);
    expect("a cell three out over a passage's headroom is left out",
           mapgen_flood_ring_cell_yields(3, true), true);
    expect("a cell touching the hollow that takes a way still pushes it back",
           mapgen_flood_ring_cell_yields(1, true), false);
    expect("an outer cell that takes nothing is built as before",
           mapgen_flood_ring_cell_yields(3, false), false);

    printf("H5: a floor over a room floods when the room keeps its headroom\n");
    /* the arena's middle: floor 448, slab 10 (ceiling 438), corridor floor 326 */
    expect("the arena's middle keeps 74 under a flood 32 deep",
           mapgen_flood_room_under_keeps_headroom(
               mapgen_flood_headroom_after(448, 32, 16, 438, 326)), true);
    expect("but only 16 under the ambition's 89.6 - refused",
           mapgen_flood_room_under_keeps_headroom(
               mapgen_flood_headroom_after(448, 89.6f, 16, 438, 326)), false);
    expect("a room under with 30 left under the slab is refused",
           mapgen_flood_room_under_keeps_headroom(
               mapgen_flood_headroom_after(448, 32, 16, 438, 370)), false);
    expect("a room deeper than the slab keeps its own ceiling and floods",
           mapgen_flood_room_under_keeps_headroom(
               mapgen_flood_headroom_after(448, 32, 16, 380, 300)), true);
    expect("the arena, 47 cells at 90 and 300 at 32, goes shallow",
           mapgen_flood_goes_shallow(47u, 300u), true);
    expect("room 4, 146 at both depths, stays 90 deep",
           mapgen_flood_goes_shallow(146u, 146u), false);

    printf("H6: D9 charges a flood only for the pairs it separates\n");
    expect("a pair the candidate joins is answered",
           mapgen_flood_pair_answered(true, true), true);
    expect("a pair the baseline joined and the candidate does not is refused",
           mapgen_flood_pair_answered(false, true), false);
    expect("a pair the baseline could not join inside the box is excused",
           mapgen_flood_pair_answered(false, false), true);

    printf("D17: a passage's floor stands under open air, whoever's it is\n");
    expect("corridor 12's cell under open air the finder gave no room is floor",
           mapgen_flood_air_ours(true, UINT32_MAX, 12u, true), true);
    expect("a passage cell under the air of a room it joins is floor",
           mapgen_flood_air_ours(true, 0u, 12u, true), true);
    expect("a passage cell whose air point is rock is not, whatever the lattice",
           mapgen_flood_air_ours(true, 12u, 12u, false), false);
    expect("a room's cell under another room's air is not its floor",
           mapgen_flood_air_ours(false, 0u, 4u, true), false);
    expect("a room's cell under its own air is",
           mapgen_flood_air_ours(false, 4u, 4u, true), true);

    printf("D23: a passage keeps its pickups; starts and rooms are unchanged\n");
    expect("the item_health in corridor 12 leaves its cell to the water",
           mapgen_flood_thing_refuses(true, true), false);
    expect("a player start in a passage still refuses its cell",
           mapgen_flood_thing_refuses(true, false), true);
    expect("a pickup in a room still refuses its cell",
           mapgen_flood_thing_refuses(false, true), true);
    expect("anything else in a room still refuses its cell",
           mapgen_flood_thing_refuses(false, false), true);

    printf("D29: a passage clashes with an earlier flood on its own storey only\n");
    {
        /* the arena's flood at ambition 80: 816 304 .. 1744 1008, 32 deep
           under its floor at 448 (row 286) */
        const float arena_lo[3] = { 816.0f, 304.0f, 416.0f };
        const float arena_hi[3] = { 1744.0f, 1008.0f, 448.0f };
        expect("corridor 14's cell 1470 830 at 336 runs under the arena's lake",
               mapgen_flood_passage_clashes(1470.0f, 830.0f, 336.0f, 16.0f,
                                            96.0f, arena_lo, arena_hi), false);
        /* a flood 90 deep under a floor at 896, over corridor 12's own box */
        const float level_lo[3] = { 1008.0f, -112.0f, 806.0f };
        const float level_hi[3] = { 1904.0f, 80.0f, 896.0f };
        expect("corridor 12's cell at 896 against a flood at its own height"
               " clashes",
               mapgen_flood_passage_clashes(1456.0f, -16.0f, 896.0f, 16.0f,
                                            96.0f, level_lo, level_hi), true);
        expect("a cell outside the flood's box grown by the margin does not"
               " clash",
               mapgen_flood_passage_clashes(1470.0f, 1200.0f, 440.0f, 16.0f,
                                            96.0f, arena_lo, arena_hi), false);
    }

    printf("%d failures\n", failures);
    return failures ? 1 : 0;
}
