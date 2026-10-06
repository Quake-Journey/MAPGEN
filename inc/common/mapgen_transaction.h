/*
 * MapGenTransaction - one edit at a time, and the map is never half-edited.
 *
 * Contract 17, and the binding ruling of 2026-09-02. The generator has been
 * planning a batch, applying all of it to one candidate, and compiling once at
 * the end. That is not a transaction however the outer sequence is named: there
 * is no accepted-candidate chain, no per-edit evidence, no actual cost, and
 * nothing to discard when one edit of two hundred is the one that broke the
 * map. It is also why cosmetic edits eat the budget - nothing measures what an
 * edit was worth, so nothing can prefer the ones that are worth something.
 *
 * So:
 *
 *     TryApplyTypedEdit(accepted candidate, typed edit)
 *         -> a new accepted candidate
 *          | a rejection, with a reason and the evidence for it
 *
 * and the last accepted candidate is IMMUTABLE. A rejected edit leaves it byte
 * for byte as it was; that is a property this asserts about itself rather than
 * one a caller has to trust.
 *
 * --- what one attempt does ------------------------------------------------
 *
 *   1. clone the last accepted candidate;
 *   2. apply exactly ONE typed edit to the clone;
 *   3. write it and compile it in a job directory created empty for this
 *      attempt;
 *   4. run every hard gate on what came out;
 *   5. measure what it cost and how far it moved the divergence;
 *   6. retain it or throw it away, atomically.
 *
 * Every step can refuse, and a refusal is a result rather than an error: an
 * operator that proposes an edit which would open the map has done its job by
 * proposing it, and this has done its job by not keeping it.
 *
 * --- what it costs --------------------------------------------------------
 *
 * A compile per attempt, and that is not an implementation detail to be
 * optimised away. The whole finding that made this necessary was that a batch
 * of edits compiles once and nobody can say which of them did what.
 */

#ifndef MAPGEN_TRANSACTION_H
#define MAPGEN_TRANSACTION_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_divergence.h"
#include "common/mapgen_equivalence.h"
#include "common/mapgen_geometry_edit.h"
#include "common/mapgen_reach.h"
#include "mapgen_compiler.h"

typedef enum {
    MAPGEN_TXN_OK = 0,
    MAPGEN_TXN_ERR_ARGS,
    MAPGEN_TXN_ERR_MEMORY,
    MAPGEN_TXN_ERR_DONOR,
    MAPGEN_TXN_ERR_JOB_ROOT,
    /*
     * The donor's own geometry did not survive being written, compiled and
     * read back. Nothing can be measured against a reference that is not
     * there, so this is where a run stops rather than at the first edit.
     */
    MAPGEN_TXN_ERR_BASELINE
} mapgen_transaction_result_t;

const char *MapGenTransaction_ResultName(mapgen_transaction_result_t r);

/*
 * Why an attempt did not become the accepted candidate.
 *
 * Each of these is a different thing to do about it, which is the reason they
 * are not one code: an edit the operator could not apply says nothing about
 * the map, an edit that leaked says the operator is unsafe, and an edit that
 * changed nothing says the schedule is spending its budget on air.
 */
typedef enum {
    MAPGEN_TXN_ACCEPTED = 0,
    MAPGEN_TXN_REJECTED_NOT_APPLIED,   /* the operator declined it          */
    MAPGEN_TXN_REJECTED_WRITE,
    MAPGEN_TXN_REJECTED_COMPILE,       /* including a leak                  */
    MAPGEN_TXN_REJECTED_UNPLAYABLE,
    MAPGEN_TXN_REJECTED_NO_EFFECT,     /* compiled, playable, moved nothing */
    MAPGEN_TXN_REJECTED_OVERSHOT,      /* past the target it was aiming at  */
    /*
     * It left a surface a compiler cannot build cleanly - a face cut away to
     * nothing, planes enclosing nothing, or a vertex stranded in the middle of
     * a neighbour's edge. Refused before the compile, because the compiler
     * will build the crack rather than complain about it.
     */
    MAPGEN_TXN_REJECTED_SURFACE,
    /*
     * Nobody could say what it did.
     *
     * Distinct from NO_EFFECT on purpose. "It moved nothing" is a measurement;
     * "the measurement did not run" is a resource failure, and a run that
     * reports the second as the first is claiming a geometric identity it
     * never established (Codex, 2026-09-06 section 3: resource/budget
     * failures remain explicitly unmeasured). The edit is still refused -
     * an edit nobody can price is not kept on the assumption that it was
     * harmless - but the ledger says which of the two happened.
     */
    MAPGEN_TXN_REJECTED_UNMEASURED,
    /*
     * It left an entity owning a brush model with no brushes in it.
     *
     * The engine answers that with "PF_setmodel: NULL" and refuses to spawn
     * the server at all, so the map is not a bad map - it is not a map. And
     * nothing else in this tree sees it: the compiler builds the file, the
     * reachability gate walks it, the see-through oracle finds nothing to
     * see, and the first refusal comes from the game.
     *
     * MEASURED: q2dm1, seed 3, fidelity 90, an accepted set that between them
     * emptied one of the donor's own func_plats. It compiled, it measured 106
     * permille against a target of 100 - the best result this generator has
     * produced - and it would not load.
     */
    MAPGEN_TXN_REJECTED_ORPHANED_MODEL,
    /*
     * It put a player, or something he has to pick up, under water.
     *
     * The flood raises a pool and moves nothing; on q2dm1 at fidelity 90 that
     * left one deathmatch start, the railgun, its slugs, two large healths
     * and four armour shards under the new surface, and the PO spawned in it.
     * Every gate above passed: the map compiled, it was lit, and the
     * reachability explorer SWIMS - so a drowned pickup reports as reachable.
     *
     * A spawn in liquid is refused always. A pickup is refused unless the
     * DONOR had that pickup in liquid too, because a map whose designer put a
     * weapon in the water is a map this may fork.
     */
    MAPGEN_TXN_REJECTED_DROWNED,
    /*
     * It stood water in the air.
     *
     * The flood raised a pool out of the basin that holds it, and the PO said
     * what anyone would: water does not lie like that, it would run off at
     * once. The spelling in a compiled map is exact - the compiler draws no
     * face between water and solid, so a pool in a basin has no vertical
     * faces and one standing in the air has as many as it has sides.
     *
     * Held against the DONOR's own count, like surface faults and drowning: a
     * map whose designer left a waterfall may be forked, and an edit is held
     * only to not adding to it. q2dm1's count is zero.
     */
    MAPGEN_TXN_REJECTED_STANDING_WATER,
    /*
     * It took a piece out of a machine.
     *
     * MEASURED on q2dm1, seed 3, 2026-09-07: a stairs-to-lift edit removed
     * two brushes of the donor's OWN func_plat and left it as a twentieth of
     * itself - 20 x 32 x 20 where the donor had 68 x 96 x 256. The plan
     * records brush INDICES, every accepted edit that drops a brush
     * renumbers what follows, and by the time this one applied its indices
     * belonged to somebody else.
     *
     * The orphan gate above cannot see it: the entity still owns a brush. So
     * every model the donor has keeps its brushes and its bounds, or the
     * candidate is refused.
     */
    MAPGEN_TXN_REJECTED_MUTILATED_MODEL,
    /*
     * Or it built something in a machine's way.
     *
     * A lift is a shaft with nothing in it. An operator that stands a block
     * where an accepted lift travels leaves a deck that rises through
     * architecture, which is what the PO filmed on 2026-09-07 - and the
     * machine that carries him is the last thing in the map that should
     * surprise him.
     *
     * Measured on the compiled candidate as the share of the deck's own
     * volume that is inside world solid anywhere other than where it rests,
     * against the donor's own worst: q2dm1's is one permille, its big lift
     * grazing the shaft it sits in.
     */
    MAPGEN_TXN_REJECTED_BLOCKED_MACHINE,
    /*
     * It built over a way through the map.
     *
     * The reachability gate asks whether every pickup can be reached from
     * every spawn, and a map with two ways up passes it with one of them
     * filled in. MEASURED on the fork the PO walked on 2026-09-07 evening:
     * three blocks in one stairwell, sixty-eight of q2dm1's 1,762 climb
     * places turned to solid, four units of daylight beside them, and every
     * gate green.
     *
     * A CLIMB is a standing place with three or more floor heights within
     * sixty-four units - a stair, a step, a ledge to hop - and it is what a
     * map is played on. A candidate may bury a corner or a shelf; it may not
     * bury a way.
     */
    MAPGEN_TXN_REJECTED_BURIED_ROUTE,
    /*
     * Or it built something nobody can use.
     *
     * Every other verdict here asks whether an edit BROKE something. None of
     * them asks whether it was worth making, and on 2026-09-08 the PO walked
     * three forks that passed all of them and were pointless: square columns
     * two hundred and forty units tall standing in the middles of rooms, four
     * of them the same in every seed, one map with nine constructions and NINE
     * FEWER standing places than the donor it forked. "What such artistry is
     * for I do not understand" - and no gate in the tree could disagree with
     * him, because none of them was measuring what he was looking at.
     *
     * So the two families that ADD architecture - the block and the recut -
     * are held to the reach explorer's own answer: after the edit a player can
     * get to MORE places than before, and at least one of them is ON the thing
     * that was built. A column whose top is out of reach adds nothing and
     * takes away the floor it stands on; a platform with a step onto it adds
     * itself.
     */
    MAPGEN_TXN_REJECTED_WORTHLESS,
    /*
     * Or it dug a passage that is not a way.
     *
     * A dig is a WAY by construction - that is its whole purpose - and nothing
     * asked whether the one that was built is one. MEASURED on the four maps of
     * 2026-09-11 that carry the dig 1888 1128 1024 -> 1960 160 640: its top was
     * closed by 32 units of the donor's wall and the shell's slab, so a player
     * went up it from the slugs and met a metal chamber with no way on - «вырытый
     * тоннель упирается в непроходимое препятствие». It compiled, it sealed, every
     * pickup was reachable (the passage is simply a room off the lower corridor),
     * and the hull probe walked its inside end to end.
     *
     * Asked of the explorer on the compiled candidate (`MapGenReach_WayThrough`):
     * from the upper end, through the dig's box, to the lower end, using nothing
     * but the box and the two ends' own neighbourhoods. The ledger says which end
     * failed.
     */
    MAPGEN_TXN_REJECTED_DEAD_END,
    /*
     * Or its compiled map HIDES a surface a player can see.
     *
     * The renderer draws what the map's own visibility lets it, and nothing
     * else. MEASURED 2026-09-14 (ledger row 297): the flood of corridor 12
     * left its geometry sealed and every face drawn, and the compiler's
     * visibility then no longer joined the stair below it to the step a
     * player stands over - so the step was not drawn and the PO saw «дыра за
     * пределы уровня», on three maps. Asked of the candidate against its
     * parent: from the reachable places near the edit, a drawn face in plain
     * sight whose cluster the parent's PVS showed and the candidate's does not.
     */
    MAPGEN_TXN_REJECTED_HIDDEN,
    /*
     * Or a pickup the parent kept is FREED by the game at spawn - see
     * `MapGenTransaction_PickupsLostAtSpawn`. The PO, 2026-09-14, on mg_20e:
     * «Не нашел где теперь лежит chaingun» (ledger row 302).
     */
    MAPGEN_TXN_REJECTED_LOST_PICKUP,
    /*
     * Or a spawn its parent kept clear stands in the column a lift or a train
     * carries its rider through - see `MapGenTransaction_SpawnsInMoverColumns`.
     * The PO, 2026-09-14, on mg_20f: «лифт ... упирается в место респавна и не
     * поднимается из за этого выше» (ledger rows 306 and 307).
     */
    MAPGEN_TXN_REJECTED_BLOCKED_SPAWN,
    /*
     * Or a dig's new space is SEEN THROUGH THE SKY: from where a player's eye
     * can be in the old map's air under a sky face, a straight line passes a
     * sky brush and meets no drawn face before the new space. The renderer
     * draws the sky behind everything, so what stands behind it shows - the
     * PO on mg_20q: «у тебя в них как будто небо вместо стенок/потолка снаружи
     * лежит» (ledger rows 350-371, Fable's brief C6). Asked of a dig that wore
     * a sky skin, on the attempt's own compile.
     */
    MAPGEN_TXN_REJECTED_SKY,
    /*
     * Or a dig's new space OPENS HIGH sideways into the old map's air - a hole in a wall higher than a doorway, out of
     * its ends' doorways (row 412, Fable's brief 9 section 5): the delivery gate `digwalls` (row 343) asked it of
     * the finished map only, so a tunnel with a lift on q3t2 was accepted with a gap 184..232 over the floor into the
     * room beside it - the PO's first Studio map and its repeat both failed the gate on it. The gate's own rule,
     * asked of the attempt's compile against the map before it.
     */
    MAPGEN_TXN_REJECTED_OPEN_HIGH
} mapgen_transaction_verdict_t;

/* One past the last verdict, so a caller that tallies the ledger does not
   carry its own copy of where the enum ends. */
#define MAPGEN_TXN_NUM_VERDICTS \
    ((uint32_t)MAPGEN_TXN_REJECTED_OPEN_HIGH + 1u)

const char *MapGenTransaction_VerdictName(mapgen_transaction_verdict_t v);

/*
 * Row 371: the REJECTED_SKY rule - is new space in the box (air in `built`, rock
 * in `donor`, under a roof) seen through the sky from a player's eye in the
 * donor's air? `witness` gets the target and the viewer. No PVS is used.
 */
bool MapGenTransaction_SeenThroughSky(const mapgen_bsp_t *built,
                                     const mapgen_bsp_t *donor, const float lo[3],
                                     const float hi[3], float witness[6]);

/*
 * Row 382: the donor's seams the transaction keeps as witnesses - every seam of
 * the donor's file taken twice as far off an edge's line as a candidate's is
 * judged, opaque and within one model - and whether one of a candidate's seams
 * is NEW: opaque, within one model, and named by none of them. The skin-gap
 * discount (row 369) is the judge's own and is not applied here.
 */
mapgen_bsp_seams_result_t MapGenTransaction_DonorSeams(const mapgen_bsp_t *donor,
                                                       mapgen_bsp_seam_t *out,
                                                       uint32_t cap,
                                                       uint32_t *out_count);
bool MapGenTransaction_NewSeam(const mapgen_bsp_seam_t *seam,
                               const mapgen_bsp_seam_t *donor, uint32_t num_donor);

/*
 * The REJECTED_HIDDEN question, asked of any two compiled maps.
 *
 * `eyes` are where a player's eye can be; the faces asked about are the
 * candidate's drawn faces within `grow` of the box `lo`..`hi`, sampled at the
 * middle and half-way to each corner, a unit and a half in front. A pair is
 * LOST when the candidate's PVS does not join the eye to the sample, the
 * parent's PVS does, and a box a unit each way swept through the candidate
 * between them meets no content the compiler's visibility can stop at -
 * solid, glass or any liquid (row 299: the eye stops at an opaque liquid as
 * the PVS does, and a line that grazes an edge is not plain sight). Returns
 * how many were lost; `witness` is the first eye and sample.
 */
uint32_t MapGenTransaction_HiddenInSight(const mapgen_bsp_t *parent,
                                         const mapgen_bsp_t *candidate,
                                         const float (*eyes)[3],
                                         uint32_t num_eyes, const float lo[3],
                                         const float hi[3], float grow,
                                         float witness[6]);

/*
 * A pickup the game frees at spawn (ledger row 302).
 *
 * `droptofloor` (g_items.c:871-894) gives every weapon, item and ammo box a
 * box 15 units each way, sweeps it 128 units down against solid and window,
 * and FREES the pickup when that sweep starts solid - two frames after
 * spawn, when every other solid stands where the game put it: a lift nothing
 * targets at its bottom. MEASURED 2026-09-14: mg_20e's own server freed its
 * chaingun, its jacket armour, a box of bullets and three armour shards,
 * each inside the resting deck of a dig's lift, from a file whose every lump
 * was right.
 */
typedef struct {
    char  classname[64];
    float origin[3];
    char  inside[112];   /* what its box starts inside                  */
} mapgen_lost_pickup_t;

/* Every pickup of `bsp` the game frees at spawn, the first `max_out` of them
   written to `out`. Returns how many there are. */
uint32_t MapGenTransaction_PickupsLostAtSpawn(const mapgen_bsp_t *bsp,
                                              mapgen_lost_pickup_t *out,
                                              uint32_t max_out);

/*
 * A spawn point a carrying mover runs into (ledger row 307).
 *
 * A spawn's pad is a solid box 32 units each way, 24..16 under its origin
 * (g_misc.c:1703-1707). A lift or a train pressing its rider into that pad is
 * blocked by him, and a plat blocked on its way up goes back down
 * (g_func.c:376-393). MEASURED 2026-09-14 on mg_20f: a dig dealt to q2dm1's
 * spawn spot at 1888 736 536 dug the floor from under that spawn, and the PO
 * rode the lift into its pad.
 */
typedef struct {
    char  classname[64];
    float origin[3];
    char  mover[96];     /* the mover whose column it stands in         */
} mapgen_blocked_spawn_t;

/* Every spawn of `bsp` whose pad or spawned player stands in the column a
   carrying mover sweeps between its stops - 16 wider each way, and a rider's
   56 over its highest deck - the first `max_out` written to `out`. Returns
   how many there are. */
uint32_t MapGenTransaction_SpawnsInMoverColumns(const mapgen_bsp_t *bsp,
                                                mapgen_blocked_spawn_t *out,
                                                uint32_t max_out);

typedef struct {
    mapgen_edit_kind_t kind;
    uint32_t           target;
    int32_t            amount;
} mapgen_typed_edit_t;

/*
 * One line of the ledger: what was attempted, what happened, and what it was
 * worth. `divergence_after` is the whole candidate's divergence from the
 * donor, and `divergence_delta` is what this one edit moved it by - which is
 * the actual cost vector the schedule has never had.
 */
typedef struct {
    mapgen_typed_edit_t          edit;
    mapgen_transaction_verdict_t verdict;
    mapcompile_result_t          compile_result;

    uint32_t divergence_after;
    int32_t  divergence_delta;
    uint32_t brushes_after;
    uint32_t compile_ms;
    /*
     * D18 (assignment 22): where an attempt's time goes, in wall milliseconds
     * on the same clock as `compile_ms`. MEASURED 2026-09-13 on the showcase:
     * 19 attempts took 1692 s and the compiler 22.5 s of them, so the rest was
     * never measured. `total_ms` is the whole attempt; what the named phases do
     * not cover is the rest. `parent_ms` is the parent map's reach explore,
     * taken lazily for D9 and D16 and counted apart from `pairs_ms`.
     */
    uint32_t apply_ms, load_ms, reach_ms, seams_ms, water_ms, pairs_ms,
             parent_ms, divergence_ms, accept_ms, total_ms;
    /*
     * D28 (assignment 24): the whole attempt and its walk again, in this
     * process's CPU milliseconds - user plus kernel, every thread, the walk's
     * workers among them, and never the compiler, which is another process.
     * A slowdown in wall that is not in CPU is the machine's.
     */
    uint32_t total_cpu_ms, reach_cpu_ms;

    /*
     * What this edit actually changed, in cells, against the map it was
     * applied to - not against the baseline, and not rounded.
     *
     * `divergence_delta` above is scalar progress toward the target: it is a
     * difference of two integer-permille aggregates measured with routes off,
     * so a zero in it means any of six things (Codex, 2026-09-06 section 3)
     * and only one of them is "nothing changed". This is the other quantity,
     * and the two are reported separately because they are different
     * questions.
     *
     * Measured only when the cheap score could not decide - which is exactly
     * when it is worth a reachability exploration - so `structural_measured`
     * false on an ACCEPTED step means the cheap score already answered, and
     * false on a REJECTED_UNMEASURED step means nothing answered.
     */
    uint32_t structural_cells;
    bool     structural_measured;
    bool     structural_routes;

    /* Coplanar seams counted in the SOURCE brushes, before the edit was
       written out. RECORDED and no longer judged: the compiler's own tjunc
       pass stitches them, and the candidates this number refused compile to
       the donor's own fourteen. `tjunctions_after` is the gate. */
    uint32_t faults_after;

    /* And the seams the COMPILER left, which is what the gate judges: how
       many, and how many of those are liquid against liquid and forgiven.
       Zero on a step that never reached a compile. */
    uint32_t tjunctions_after;
    uint32_t tjunctions_liquid;
    /* Of those, the ones between two different models - the world against a
       door or a lift. Not cracks the compiler could close, and not this
       gate's business; reported so a reader can see them. */
    uint32_t tjunctions_cross_model;
    /* Row 369: and those inside a skinned dig's gap - faces that face into a
       sealed gap, seen by no player; counted, not refused. */
    uint32_t tjunctions_skin;
    /* And where the first seam the donor does not have was found, when that
       is why the candidate was refused. A count would not say. */
    float    new_seam[3];

    /*
     * Why this step was refused, in the words of whoever refused it.
     *
     * The OPERATOR's own reason when it declined to apply
     * (`MapGenGeometryEdit_WhyDeclined`), and a GATE's reason when a gate
     * refused the compiled candidate: the buried climb place and which question
     * it failed, the machine that lost room, the blocking mover. It used to be
     * documented and printed as the operator's field alone, so every gate's
     * reason was computed and thrown away (ledger rows 126, 144, 153). Empty
     * only when nothing refused, or when what refused has not learned to say.
     */
    char     declined[160];

    /*
     * And, for a FLOOD, the two numbers behind a buried-route verdict.
     *
     * `flood_places` is how many of the baseline's climb places the compiled
     * candidate no longer lets a player stand on AND that fall inside this
     * flood's own footprint; `flood_replaced` is how many of those had a place a
     * player can reach and return from within `MAPGEN_TXN_FLOOD_REACH` of them,
     * which is what retires the old one (assignment 18's D4, ledger row 152).
     * Equal means the flood replaced every way it took away. Zero and zero on
     * every family that is not a flood, which never asks.
     */
    uint32_t flood_places;
    uint32_t flood_replaced;

    /*
     * And how the flood PROVED it, which proximity never did.
     *
     * `flood_entrances` is how many ways into the flooded room the baseline
     * had - standing places inside the flood's grown box but outside its
     * liquid, one per cluster - and `flood_pairs_proved` is how many of them
     * the compiled candidate still connects to the first one and back, by the
     * engine's own movement through the flood's own box
     * (`MapGenReach_WayThrough`). Equal to `flood_entrances - 1` is the proof;
     * anything less names the entrance that lost its way across.
     *
     * A nearby safe state was the old test and it proves nothing of the kind:
     * one point 32 units away behind a wall satisfies it while the passage
     * through the water is walled (Codex, 2026-09-13 §3). Zero on a flood of
     * slime or lava, which forgives nothing at all.
     */
    uint32_t flood_entrances;
    uint32_t flood_pairs_proved;
    /* and the pairs the candidate does not join that the BASELINE did not join
       inside the same box either: not separated by the flood, so not charged
       to it (H6, ledger row 239). Proved plus excused equal to
       `flood_entrances - 1` is the proof. */
    uint32_t flood_pairs_excused;

    /*
     * D16 (assignment 22): a tunnel's MOUTH proved like a flood's box. For each
     * segment box of the attempted tunnel, grown by 24, the baseline's standing
     * places inside it that still stand are entrances, and every pair must walk
     * both ways inside the box; a direction the PARENT does not walk either is
     * excused. `dig_pairs_lost` counts pairs the parent joined and the candidate
     * does not, and the first one is named.
     */
    uint32_t dig_entrances, dig_pairs_proved, dig_pairs_excused, dig_pairs_lost;
    float    dig_lost_from[3], dig_lost_to[3];

    /* And, for a construction, how many places a player can get to ON it -
       the evidence behind REJECTED_WORTHLESS, so a ledger says whether the
       thing that was built could be stood on rather than only that it was
       refused. Zero on every other family, which never asks. */
    uint32_t places_on_construction;

    /*
     * D20 (assignment 23): the shape of this attempt's walk of the candidate -
     * places, moves, frontier levels and how many of them were wide enough to
     * go to every core, explorations, machines. Zero when the walk did not
     * finish.
     */
    uint32_t walk_states, walk_edges, walk_levels, walk_levels_wide,
             walk_rounds, walk_movers;
    /* row 331: places the walk simulated, and places a later round reused */
    uint32_t walk_simulated, walk_reused;
    /*
     * D21: how much of the PARENT's walk an edit of this size can touch - its
     * states, and those within 512 and within 1024 units of the edit's box.
     * Zero when the attempt did not compile or had no box.
     */
    uint32_t parent_states, parent_near_512, parent_near_1024;

    char     bsp_sha256[MAPCOMPILE_SHA256_HEX];
} mapgen_transaction_step_t;

typedef struct mapgen_transaction_s mapgen_transaction_t;

/* Row 400: was the donor rebuilt with faithful skins (its plain rebuild refused for what it draws)? */
bool MapGenTransaction_FaithfulSkins(const mapgen_transaction_t *txn);

/*
 * Open a transaction over a donor. The accepted candidate starts as the
 * donor's own geometry, which is the only starting point that makes fidelity
 * 100 exactly zero by construction rather than by tolerance.
 *
 * `job_root` must exist; each attempt gets a fresh directory beneath it.
 * `moddir` is the frozen material mirror the compiler reads.
 *
 * Opening also builds the BASELINE: the donor's own geometry, written and
 * compiled with nothing applied to it, in `job_root/baseline`. Every
 * divergence afterwards is measured against that and not against the file the
 * donor arrived in, because no two compilers agree on how to split a surface
 * or where to put a leaf boundary, and a fidelity-100 run - which applies
 * nothing - was being told it had changed fifty-six permille of q2dm1. What
 * the number has to answer is how much the EDITS changed, and the compiler is
 * not an edit.
 *
 * A donor whose own geometry does not survive that round trip is refused here
 * rather than blamed on the first edit.
 */
mapgen_transaction_result_t
/* Enough for a corpus; a run that wanted more than this is a run that wanted a
   different design, not a bigger array. */
#define MAPGEN_TXN_MAX_OTHER_DONORS 8

MapGenTransaction_Begin(const char *donor_bsp, const char *job_root,
                        const char *map_name, const char *moddir,
                        const mapcompile_adapter_t *adapter,
                        uint64_t seed, mapgen_transaction_t **out);

/*
 * The same, and the other donors a room may be brought in from.
 *
 * GF7's operator lives in the geometry layer, and until this existed nothing
 * the product runs could tell it about a second map - so a cross-donor graft
 * could be planned by a driver and never by the generator. An operator the
 * product cannot reach is a prototype, which is what the whole of this
 * directive exists to stop.
 *
 * Each path is loaded here and kept for as long as the transaction lives: the
 * plan holds borrowed pointers into those geometries and reads them when an
 * edit is applied, so a transaction that freed them early would be a plan
 * reading freed memory.
 *
 * `_Begin` above is this with none, and every existing caller means exactly
 * that.
 */
/* Row 412: why the last base was refused (MAPGEN_TXN_ERR_BASELINE) - the copy against the original, axis by axis;
   false when none was. */
bool MapGenTransaction_LastBaselineWhy(mapgen_equiv_report_t *out);

mapgen_transaction_result_t
MapGenTransaction_BeginWithDonors(const char *donor_bsp, const char *job_root,
                                  const char *map_name, const char *moddir,
                                  const mapcompile_adapter_t *adapter,
                                  uint64_t seed,
                                  const char *const *other_donors,
                                  uint32_t num_others,
                                  mapgen_transaction_t **out);

/* How many other donors this transaction was opened with, and which of them
   could offer a room at all. GF7 forbids a donor being silently left out. */
uint32_t    MapGenTransaction_NumOtherDonors(const mapgen_transaction_t *txn);

/*
 * How many grafts this transaction RETAINED, and from which donors.
 *
 * Not how many were planned or attempted: what a contribution floor is about
 * is what is in the finished map. `MapGenTransaction_DonorContributed` answers
 * for one of the donors the transaction was opened with, so a donor that was
 * offered and gave nothing is visible as such rather than absent.
 */
uint32_t MapGenTransaction_GraftsAccepted(const mapgen_transaction_t *txn);
bool     MapGenTransaction_DonorContributed(const mapgen_transaction_t *txn,
                                            uint32_t i);
const char *MapGenTransaction_OtherDonor(const mapgen_transaction_t *txn,
                                         uint32_t i);

void MapGenTransaction_Free(mapgen_transaction_t *txn);

/*
 * What this run is aiming at, and how close is close enough.
 *
 * Without it a transaction takes every edit that moves the divergence at all,
 * which is how fidelity 90 asked for a hundred permille, was handed a hundred
 * and fifty-one by an edit nobody could refuse, and failed the band at the
 * very end with every compile already paid for.
 *
 * With it, an attempt whose result lands past `target + tolerance` is
 * discarded as REJECTED_OVERSHOT and the schedule tries the next edit, which
 * may be smaller. A transaction with no band set behaves exactly as before: a
 * qualification run that wants the number rather than a verdict is not aiming
 * at anything.
 */
void MapGenTransaction_SetBand(mapgen_transaction_t *txn, uint32_t target,
                               uint32_t tolerance);

/*
 * Attempt one typed edit. Returns the verdict and fills `step`.
 *
 * On acceptance the transaction's candidate and its compiled artifact advance;
 * on any rejection they do not move at all.
 */
mapgen_transaction_verdict_t
MapGenTransaction_Try(mapgen_transaction_t *txn, const mapgen_typed_edit_t *edit,
                      mapgen_transaction_step_t *step);

/*
 * Build what it is holding, without applying anything.
 *
 * Fidelity 100 spends no edits, and a run that spent none would otherwise hand
 * back the donor's own file: correct about the geometry and wrong about the
 * product, because the path of the map you were given is not a map you made,
 * and every gate downstream would be judging the donor.
 *
 * Writes, compiles and gates the accepted candidate exactly as an attempt
 * does. On success the accepted artifact becomes its own; on failure nothing
 * moves, as with any other attempt.
 */
mapgen_transaction_verdict_t
MapGenTransaction_Materialise(mapgen_transaction_t *txn,
                              mapgen_transaction_step_t *step);

/*
 * Deal again, from a new seed, against what the map is NOW.
 *
 * The schedule is built once from the donor, and when it runs out the run
 * stops - which is why every fidelity below a hundred returned the same file:
 * the stopping point is a property of the catalogue, not of the target. A run
 * still short of its band has not finished, it has run out of ideas, and a
 * new deal against the geometry as it now stands is a new set of them,
 * because the rooms it plans over are the ones the accepted edits left.
 *
 * The accepted geometry, its artifact and every ledger count are kept: this
 * replaces the PLAN and nothing else. The caller counts the rounds.
 */
mapgen_transaction_result_t MapGenTransaction_Redeal(mapgen_transaction_t *txn,
                                                     uint64_t seed);

/*
 * How far from the donor this run may go, as (100 - fidelity).
 *
 * The operators that can be more or less ambitious - so far the relevel - read
 * it; the rest do not care. It survives a redeal, because the fidelity does.
 * The caller sets it, because the fidelity is the caller's.
 */
void MapGenTransaction_SetAmbition(mapgen_transaction_t *txn, int32_t ambition);

/* The plan the transaction offers, in the order it means to spend it. */
const mapgen_geometry_edit_plan_t *
MapGenTransaction_Plan(const mapgen_transaction_t *txn);

/* Where the accepted candidate stands now. */
uint32_t MapGenTransaction_Divergence(const mapgen_transaction_t *txn);
uint32_t MapGenTransaction_Accepted(const mapgen_transaction_t *txn);
/*
 * The floor every attempt is held to: surfaces of the DONOR that a compiler
 * cannot build cleanly. An edit may not add to it.
 */
uint32_t MapGenTransaction_DonorFaults(const mapgen_transaction_t *txn);

/*
 * Build the reference on its own: the donor's own geometry, written and
 * compiled with nothing applied to it, in `job_root/baseline`.
 *
 * A transaction does this when it opens. Fidelity zero has no transaction and
 * needs the same file for the same reason, so it is a function rather than a
 * private step - two ways of producing the reference would be two references.
 */
/*
 * Build the reference for a caller that has no transaction - fidelity zero
 * invents its map instead of forking one - and prove it is the donor before
 * handing it back. `why` may be NULL.
 */
bool MapGenTransaction_BuildBaselineChecked(const char *donor_bsp,
                                            const char *job_root,
                                            const char *map_name,
                                            const char *moddir,
                                            const mapcompile_adapter_t *adapter,
                                            mapgen_equiv_report_t *why,
                                            char out_path[MAPCOMPILE_MAX_PATH],
                                            char out_sha256[MAPCOMPILE_SHA256_HEX]);

bool MapGenTransaction_BuildBaseline(const char *donor_bsp,
                                     const char *job_root,
                                     const char *map_name, const char *moddir,
                                     const mapcompile_adapter_t *adapter,
                                     char out_path[MAPCOMPILE_MAX_PATH],
                                     char out_sha256[MAPCOMPILE_SHA256_HEX]);

/*
 * What the equivalence gate found when it compared the donor with the
 * baseline. Valid after Begin, whether it succeeded or returned ERR_BASELINE.
 * Returns false when there is no transaction to ask.
 */
bool MapGenTransaction_Equivalence(const mapgen_transaction_t *txn,
                                   mapgen_equiv_report_t *out);

/*
 * The same as Begin, and it says why it refused.
 *
 * A transaction that fails its baseline is destroyed before the caller can ask
 * it anything, so the reason has to come out separately. `why` is filled in
 * whenever the equivalence gate ran, whether it passed or not.
 */
mapgen_transaction_result_t
MapGenTransaction_BeginWith(const char *donor_bsp, const char *job_root,
                            const char *map_name, const char *moddir,
                            const mapcompile_adapter_t *adapter,
                            uint64_t seed, mapgen_equiv_report_t *why,
                            mapgen_transaction_t **out);

/* The compiled baseline every divergence is measured against, and its hash. */
const char *MapGenTransaction_BaselineBsp(const mapgen_transaction_t *txn);
const char *MapGenTransaction_BaselineSha256(const mapgen_transaction_t *txn);

uint32_t MapGenTransaction_Attempted(const mapgen_transaction_t *txn);
const char *MapGenTransaction_AcceptedBsp(const mapgen_transaction_t *txn);

/*
 * The canonical digest of the accepted candidate.
 *
 * What makes "immutable between attempts" checkable instead of promised: it is
 * taken before every attempt and again after, and a rejection that moved it is
 * a defect in the transaction itself.
 */
uint64_t MapGenTransaction_AcceptedDigest(const mapgen_transaction_t *txn);

/* How many times a rejected attempt left the accepted candidate different from
   how it found it. Anything but zero means this module is broken. */
uint32_t MapGenTransaction_Violations(const mapgen_transaction_t *txn);
const mapgen_reach_report_t *
MapGenTransaction_Reach(const mapgen_transaction_t *txn);

/*
 * The baseline's walk, when this transaction took one, handed to the caller -
 * who owns it from then on. NULL when it was never taken, or already taken.
 *
 * D19 (assignment 23): the pipeline's complete oracle measures routes against
 * the baseline, and this is a walk of that very file at the same budget.
 */
mapgen_reach_t *MapGenTransaction_TakeBaselineWalk(mapgen_transaction_t *txn);

/* The ledger, one line per attempt, in the order they were attempted. */
uint32_t MapGenTransaction_Steps(const mapgen_transaction_t *txn);
const mapgen_transaction_step_t *
MapGenTransaction_Step(const mapgen_transaction_t *txn, uint32_t i);

/*
 * RESUME (ledger row 395, Fable's brief 3 G3).
 *
 * `Replay` restores, without compiling or walking, what one attempt of an earlier run of the same job left in the
 * transaction: a NOT_APPLIED is tried for real (no compile); any other refusal is counted; an ACCEPTED edit is
 * applied again and must write byte for byte the .map its attempt directory holds, whose .bsp then becomes the
 * accepted map. On any disagreement it fills `why` and returns MAPGEN_TXN_REJECTED_WRITE - the resume has diverged.
 * `ReplayDone` takes the walk of the last replayed map and clears the next attempt's directory before the first real
 * attempt. `VerdictFromName` is `VerdictName` read back; MAPGEN_TXN_NUM_VERDICTS for a name it does not know.
 */
mapgen_transaction_verdict_t
MapGenTransaction_Replay(mapgen_transaction_t *txn, const mapgen_typed_edit_t *edit,
                         mapgen_transaction_verdict_t was, uint32_t divergence_after,
                         mapgen_transaction_step_t *step, char *why, size_t why_size);
bool MapGenTransaction_ReplayDone(mapgen_transaction_t *txn);

/* Row 410: a replay's .map may differ from the one built in its point lights alone (the guards' replays of jobs
   older than row 408's room lights); never set by a real resume. */
void MapGenTransaction_SetReplayAnyLights(bool any);

/* Row 411 (Fable's brief 8): with the job root in memory ("mem:..."), each accepted try's .map and .bsp
   written once under `disk_root`/try_NNNN when `on` - the checkpoints a resume replays against. */
void MapGenTransaction_SetCheckpoints(const char *disk_root, bool on);
mapgen_transaction_verdict_t MapGenTransaction_VerdictFromName(const char *name);

#endif /* MAPGEN_TRANSACTION_H */
