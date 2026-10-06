/*
 * MapGenGeometryEdit - what a fidelity below 100 actually does.
 *
 * The control the PO asked for runs from "a fork of q2dm1" to "nothing of
 * q2dm1 left". Above 0 every candidate still BEGINS as the donor's own
 * geometry, so the question this Module answers is not what to build but what
 * to change, in what order, and how far down that order a given fidelity is
 * allowed to go.
 *
 * Three properties make the number mean something rather than merely differ:
 *
 *   - the schedule is built ONCE from the donor and the seed, independent of
 *     the fidelity, so a lower fidelity receives a superset of the edits a
 *     higher one received. Contract 14.0 requires that nesting, and it is what
 *     lets a test say the control is monotonic instead of just noisy;
 *   - every operator is bounded and typed, owning named geometry, so an edit
 *     can be described, costed and undone;
 *   - every operator replaces a STRUCTURE with another structure that does
 *     the same job, and none of them moves a face that shares a plane with a
 *     neighbour. An earlier version could slide any structural plane outward.
 *     It could not open a sealed map - growing a solid only adds solid - and
 *     it was still wrong twice over: the seam where the moved face had been
 *     flush against its neighbour opened into a hairline crack right through
 *     the level, and a wall that thickened in the middle of a room read as a
 *     boulder somebody had left there. It changed the map without changing
 *     the architecture.
 *
 * What the operators can still do wrong is block a route, which is why the
 * compiled traversal gate is a separate and absolute check rather than a
 * property claimed here.
 */

#ifndef MAPGEN_GEOMETRY_EDIT_H
#define MAPGEN_GEOMETRY_EDIT_H

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

typedef enum {
    /* Every face carrying one texture takes another, so the map reads as the
       same architecture in a different material rather than as confetti. */
    MAPGEN_EDIT_RESKIN = 0,
    /* Withdrawn: a slab laid over a flight changes the heights a player moves
       between, and in q2dm1 those heights are the movement. Kept in the enum
       so a schedule recorded by an older build still reads. */
    MAPGEN_EDIT_STAIRS_RAMP,
    /* Or becomes a lift, built to the pattern of a func_plat the donor
       already has, so it moves like the map it came from. */
    MAPGEN_EDIT_STAIRS_LIFT,
    /* A pool rises and reaches somewhere it did not. Water seals nothing, so
       this cannot open the map. */
    MAPGEN_EDIT_RELEVEL,
    /* Withdrawn: most of the donor's detail is the clip that smooths movement
       over its stairs, and one of them is a real wall the compiler will let go
       without a word, because detail never seals. */
    MAPGEN_EDIT_DROP_DETAIL,
    /* A lamp gets brighter or dimmer. Changes the whole feel of a room and
       cannot change its shape. */
    MAPGEN_EDIT_RELIGHT,
    /* Two of the donor's own pedestals trade what stands on them. */
    MAPGEN_EDIT_SWAP_ITEM,
    /*
     * A platform built against one wall of a room, with a step onto it.
     *
     * The first operator here that edits a piece of ARCHITECTURE rather than a
     * piece of a brush. Every other one moves a side, a texture or an entity,
     * and a side is not a piece of architecture: pushing one out by twenty
     * units makes the boulder the PO called a torchashchy valun, and doing it
     * four hundred times makes four hundred boulders and the same map.
     *
     * It ADDS solid, and adding solid cannot open a hole in a map. Pushing a
     * wall into the rock behind it is the edit a designer would make and it is
     * not safe with what can be asked here: the solid behind a face is often
     * the very brush being carved, so removing it takes away the only thing
     * that was there. Two attempts at it leaked the map at every fidelity
     * below a hundred.
     *
     * What it needs to check is the other direction - that the space it fills
     * was empty, that it does not bury the floor a player walks on, and that
     * what is left is still a room. The first two are asked of the donor here;
     * the third is the reachability gate's, which is why an edit is a
     * transaction that can be discarded.
     */
    MAPGEN_EDIT_ROOM_BLOCK,
    /*
     * A way between two rooms gets wider.
     *
     * The first operator here that REMOVES world solid, and the first that
     * changes how a player moves rather than what he walks around. It is
     * allowed now because the three things that made carving unsafe are in
     * place: a bundle that knows which ways out the rest of the map depends
     * on, a closure that knows what solid belongs to the thing being cut, and
     * a transaction that discards an attempt whose map came out open.
     *
     * Planned from a SOCKET, because that is a way through the segmentation
     * found and the bundle typed; a brush index is an accident of the compile.
     * Recorded as a plane, because an accepted edit may have dropped a brush
     * and moved every index after it.
     *
     * It declines unless every unit of the volume the face sweeps through is
     * rock in the compiled donor, and there is more rock beyond it than the
     * map needs to stay shut. Declining costs nothing; the compile and the
     * reachability gate remain the authority on what actually happened.
     */
    MAPGEN_EDIT_WIDEN_CONNECTOR,
    /*
     * A sealed room turns or is mirrored, in place.
     *
     * First in Codex's operator order, and the only structural operator that
     * cannot change connectivity at all: it is legal only when the transform
     * maps every one of the bundle's sockets onto a socket of the same kind,
     * so every way in and out stays exactly where it was and the neighbours
     * never learn anything happened. What changed is the architecture inside.
     *
     * It moves the bundle's own brushes and entities about the room's centre,
     * with their texture axes, their anchors and their ANGLES - a door that
     * kept its old facing after its room turned is a door into a wall.
     */
    /*
     * A way through a wall that had none.
     *
     * The second half of Codex's operator two - the widen opens an existing
     * connector wider, this one opens a connector where the donor had only
     * rock. It is the ConnectorAdapter: new work, at a socket geometry proves
     * rather than a blueprint declares.
     *
     * A socket is proven by four measurements, all against the compiled donor:
     * the brush is a wall (an axis-aligned box thin on one axis); there is air
     * on both sides of it across the whole doorway rectangle and not merely at
     * its centre; sixteen units of wall remain on each side and above, so what
     * is left is three real brushes that still seal; and the floors the two
     * sides stand on are within one step of each other, because a doorway onto
     * a drop is a hole rather than a route.
     *
     * One box becomes three around a rectangle. Nothing is created and nothing
     * is destroyed.
     */
    MAPGEN_EDIT_OPEN_CONNECTOR,
    MAPGEN_EDIT_TURN_BUNDLE,
    /*
     * One wall of a room goes back into the rock behind it.
     *
     * Third in Codex's order, and the widen's primitive applied to a WALL: a
     * wall is many brushes and they move together or not at all, because a
     * wall moved one brush at a time is a staircase and every step of it is a
     * face somebody sees.
     *
     * It asks of every side what the widen asks of one - enough brush behind
     * it, the volume belonging to this closure alone, nothing flush against
     * it - and it refuses a wall a way out passes through, because moving
     * that moves the doorway and where a doorway goes is the socket
     * operators' business.
     */
    MAPGEN_EDIT_RESHAPE_ROOM,
    /*
     * Two rooms of the same donor change places.
     *
     * The first operator that moves whole PIECES of a map about rather than
     * editing one in place. That is what makes a fork read as a
     * different arrangement of the donor rather than a patched copy of it.
     *
     * It creates and destroys nothing: two compatible bundles are disjoint
     * sets, and exchanging them is two translations. Compatible means nothing
     * outside them can tell - the same ways out in the same directions with
     * the same kinds, each one's air fitting where the other's was, both able
     * to carry their own shells, and no obligation lost.
     */
    MAPGEN_EDIT_SWAP_BUNDLES,
    /*
     * Three or more rooms of one donor change places at once.
     *
     * The swap's idea done to a CYCLE, and the answer to a band the swap
     * cannot reach: a permutation of two leaves a map that is still the
     * donor's arrangement with one pair exchanged, however many pairs are
     * spent, because each edit only ever moves two. A cycle rearranges the
     * arrangement.
     *
     * It creates and destroys nothing - N translations of N disjoint sets -
     * and it asks the swap's own question of every pair in the cycle, so
     * nothing outside the cycle can tell that anything moved.
     */
    MAPGEN_EDIT_RECOMPOSE_BUNDLES,
    /*
     * A room from ANOTHER donor takes the place of one of ours.
     *
     * Sixth in Codex's operator order and the first that is not single-donor:
     * everything above rearranges or reshapes what one map already had, and
     * this brings in what a different map has instead.
     *
     * The question it asks is the swap's own - `interchangeable` - because a
     * bundle that can take another's place inside one map can take it across
     * two: the predicate reads ways out, their kinds, their directions and the
     * air, and none of that is a fact about which file the bundle came from.
     *
     * What it adds is provenance. Every grafted bundle records the donor it
     * came from, because GF7 requires the contribution to be attributable and
     * a graft that could not say where its geometry came from is one nobody
     * can audit.
     */
    MAPGEN_EDIT_GRAFT_BUNDLE,
    /*
     * A room emptied of what it is built of, and built again differently.
     *
     * Every other structural family here nibbles: a wall taken back thirty-two
     * units, a platform in a corner, a staircase that becomes a lift. Measured
     * on q2dm1 under the repaired divergence schema, the whole accepted set of
     * them at fidelity 90 comes to forty-three permille and one lift to eight,
     * so the bands at 250, 500 and 750 are not a few more edits away - they
     * are a different kind of edit away. A candidate is 500 permille from its
     * donor when half of what the donor is made of is not there any more.
     *
     * So: take the middle of a room - inset from its walls, clear of its floor
     * and its ceiling - empty it of world geometry, and stand new blocks in
     * it. The ways in are outside the region and are untouched, so the room is
     * still entered where it was entered; the floor and ceiling are outside it
     * too, so nobody falls out of the map; the machines stay, because a lift
     * is not what a room is built of.
     *
     * The region's outside layer is proved to hold no void before anything is
     * emptied (MapGenGraft_RegionIsSound), which is the same proof the graft
     * rests on and the reason neither of them can leak.
     *
     * How much it moves is the size of the room it is offered on, and q2dm1
     * has rooms from eight brushes to five hundred - so the family offers a
     * range of costs rather than one, and the band picks from it.
     */
    MAPGEN_EDIT_RECUT_ROOM,
    /*
     * A room's wall taken back into the rock behind it - not by thirty-two
     * units, which is what widen-connector offers, but by a room's worth.
     *
     * The same primitive as the recut and the same proof, pointed at a
     * different shape: a slab that runs the width of one wall, the height of
     * the room's air, and as deep into the rock as the proof allows. Emptying
     * it leaves the floor below it and the ceiling above it where they were,
     * so what comes out is the same room, bigger.
     *
     * It is the family that moves the metric most per compile, and the reason
     * is arithmetic rather than ambition: the divergence axes count the cells
     * where solid MEETS air, so a wall that moves changes its cells twice
     * over - once where it was and once where it now is - and the strip of
     * floor and ceiling it uncovers is new architecture on top of that. A
     * block standing in the middle of a room changes only its own faces.
     *
     * widen-connector stays as it is. It refuses a hundred and two of a
     * hundred and twenty-three candidates for want of provable rock, which is
     * the right answer to the question it asks; this family asks the question
     * the graft's region proof can actually answer.
     */
    MAPGEN_EDIT_PUSH_WALL,
    /*
     * A deathmatch start moved to another standing place.
     *
     * "A fork is not only architecture - it is also variations of weapons and
     * spawn points" (PO, 2026-09-07). The item swap has always been here and
     * has never once run below fidelity 100, because a family that cannot
     * move the architecture metric is skipped while a structural band is
     * unmet, and the band is always unmet. So the three forks he walked had
     * q2dm1's weapons on q2dm1's pedestals and q2dm1's spawns, exactly.
     *
     * This one moves a start to a place a player could already stand: dry,
     * with ground under it and room over it, within a couple of rooms of
     * where it was. It changes no geometry and takes no architectural credit
     * - TZ 14.0.1 gives spawns none, and Codex confirmed it - so it runs in
     * the finishing pass, after the band is settled, where its compile is
     * spent on the product rather than on the number.
     */
    MAPGEN_EDIT_MOVE_SPAWN,
    /*
     * A window: a hole cut through a wall with GLASS in it.
     *
     * The PO asked for this by name on 2026-09-10, of the one thing he liked
     * in the 93-permille map - «есть даже дырка в стенке - что топ... а можно
     * и разные варианты пробовать - чтобы в дырке стекло было».
     *
     * It is deliberately NOT a way through. The sill is 96 units above the
     * wall's base, which is higher than a player can step or jump onto, so
     * neither he nor the reachability walk can use the opening as a route -
     * which means the glass does not have to be understood by the walk for
     * the gates to stay honest. What the family adds is what a window adds:
     * the reveal around it, the light through it, and a room you can see into
     * before you are in it.
     */
    MAPGEN_EDIT_WINDOW,
    /*
     * A DIG: a passage cut through the rock between two floors the donor
     * already has, with stairs or a lift in it.
     *
     * This is the family the PO has asked for since the first round, and on
     * 2026-09-11 he asked for it with a verb: «Туннель под ареной - что мешает
     * прорыть с арены в туннель лестницу или лифт? Прорыть по стенке от
     * верхнего рокета вниз к рейлгану крутой тоннель, расставить там
     * лестницы/лифты, чтобы маршрут был достижим игроками и выглядел красиво.
     * Ну почему вы всё это не делаете? Зато уже кучу дней делали ящики, трибуны
     * и колонны - я за что вам плачу-то?»
     *
     * And, an hour later, what the three examples are FOR: «я тебе примеры на
     * видео показывал про туннели, лифты, лестницы - это просто самые очевидные
     * примеры... реально есть на много порядков больше вариантов, что и где
     * можно делать с картой, это же форк! Главное, чтобы она игралась, а
     * эксперименты - это то, что я от тебя жду». So the three places he named
     * are the first three CANDIDATES on this donor, and the generator is
     * general: every ordered pair of standing floor spots on the whole map that
     * passes the gates is a candidate, ordered by how much of a shortcut it is.
     *
     * It is a WAY by construction, which is what the purpose rule wants
     * (`memory/feedback_mapgen_constructions_need_a_purpose.md`): it connects
     * two floors that exist, a player walks or rides it in both directions, and
     * it arrives somewhere.
     */
    MAPGEN_EDIT_DIG,
    /*
     * A PIT: a hollow dug into a room's own floor and filled with water, slime
     * or lava.
     *
     * The PO, 2026-09-11, on the round that shipped no water at all:
     * «Наводнений хочется побольше чтоб было. И не обязательно же существующие
     * только бассейны увеличивать - на карте полно мест где можно вырыть яму и
     * залить её водой», and then «нужно больше смелости - у нас еще есть
     * кислота и лава, можно и их внедрять, грамотно только. Меньше процент от
     * оригинала - больше вариаций».
     *
     * «Грамотно» is what the family is held to: the hollow is cut where the
     * floor is one level and the rock under it is thick enough to hold it, it
     * buries nothing and takes no machine's room, its liquid stands below the
     * rim so no face of it is drawn in the air, and a pit that kills - slime or
     * lava - keeps its distance from every player start and wears a curb a
     * player can see. The reach explorer treats a hazard as a terminal state,
     * so a pit that cuts the only way to anything is refused as UNPLAYABLE by
     * the gate that already exists.
     */
    MAPGEN_EDIT_PIT,
    /*
     * A FLOOD: a room's own floor lowered across its real footprint and filled,
     * so the way across it is what the room already had - its crates, its
     * ledges, its platforms.
     *
     * The PO, 2026-09-12, on the two 128-unit squares the pit family put in one
     * room: «зачем эти две мелкие лунки тут да еще и рядом друг с другом?
     * Другое дело, если бы ты сделал на весь размер комнаты например воду или
     * кислоту или лаву и тогда был бы смысл в этом - что нужно пробираться по
     * имеющимся ящикам чтобы не утонуть или не сгореть», and on their shape:
     * «чего вообще ты в квадраты скатился этих лунок? У нас бассейны на q2dm1
     * вовсе не квадратные изначальные … Думаю о естественности, а не о
     * математической красоте».
     *
     * So this is not a bigger pit. The floor goes DOWN under the whole room
     * except a walkable margin at its edge - which is what keeps every doorway
     * standing on floor and every exit usable - the hollow is cut as the room's
     * own floor mask rather than as a rectangle, and the liquid stands below the
     * old floor line so no face of it is ever drawn in the air. Anything the
     * room had whose top is above the new waterline is left exactly where it
     * was, and that is the crossing.
     */
    MAPGEN_EDIT_FLOOD,
    /*
     * A SPAN: a bridge between two galleries across open air (row 405, Fable's brief 5 W5). The PO on mg_cor:
     * «Мне нужно чтобы архитектура менялась». cor is an arena - a keep in open air, galleries round it - with no
     * rock to dig, and a bridge over the arena is the change he sees from anywhere. Added solid only, so it cannot
     * leak; dealt where the walk between its two ends is at least twice its own length.
     */
    MAPGEN_EDIT_SPAN,
    /*
     * A RELIQUID (row 410, the PO 05.10): one of the map's own pools - its connected liquid brushes - made another
     * liquid, look and harm both: the contents bits the game reads (lava burns, slime eats, water is swum in) and
     * the warped surfaces' texture. Dealt only when the run is asked for it (`MapGenGeometryEdit_SetLiquids`), one
     * edit per pool, judged like any edit - a swap that strands a place or cuts a way is refused.
     */
    MAPGEN_EDIT_RELIQUID,
    MAPGEN_EDIT_KINDS
} mapgen_edit_kind_t;

/*
 * Can this family move the architecture metric at all?
 *
 * Section 4.1 settles it rather than leaving it to be discovered: "Reskins,
 * relights, item swaps, spawn swaps and repeated edits to the same structure
 * contribute zero to this architecture metric." A family that contributes zero
 * is a family whose every attempt, while a structural band is unmet, is a
 * compile spent to measure zero.
 *
 * Measured on q2dm1 at seed 1: of 292 planned edits 191 are paint, and 173 of
 * them were attempted, compiled and refused as having no effect - two thirds
 * of the budget and two thirds of the hour each anchor took.
 */
bool MapGenGeometryEdit_MovesArchitecture(mapgen_edit_kind_t kind);

/*
 * Can this family move the architecture metric at all?
 *
 * Section 4.1 settles it rather than leaving it to be discovered: "Reskins,
 * relights, item swaps, spawn swaps and repeated edits to the same structure
 * contribute zero to this architecture metric." A family that contributes zero
 * is a family whose every attempt, while a structural band is unmet, is a
 * compile spent to measure zero.
 *
 * Measured on q2dm1 at seed 1: of 292 planned edits 191 are paint, and 173 of
 * them were attempted, compiled and refused as having no effect - two thirds
 * of the budget and two thirds of the hour each anchor took.
 */
bool MapGenGeometryEdit_MovesArchitecture(mapgen_edit_kind_t kind);

const char *MapGenGeometryEdit_KindName(mapgen_edit_kind_t k);

/*
 * TEST SEAM. Whether the schedule deals the room block; it does not.
 *
 * The operator builds a platform against a wall with a step in front of it,
 * and the PO has rejected the result in every batch he has walked - on
 * 2026-09-10, of a photograph of q2dm1's main hall, «это не часть архитектуры
 * измененной, это просто мусорница». The family is therefore not dealt at any
 * fidelity, and no product path calls this.
 *
 * What calls it is `tools/mapgen_transaction_driver --crates`, so that
 * `check_mapgen_carving.py` still has an operator that builds brushwork on a
 * bare fixture to drive the transaction's fault, leak and playability gates
 * with. `check_mapgen_no_crates.py` asserts that nothing under src/ does.
 */
void MapGenGeometryEdit_DealRoomBlocks(bool on);

/*
 * TEST SEAM. Whether the schedule deals the RECUT; it does not.
 *
 * Four rounds of the PO's screenshots and one objection: the platform, the
 * room block and the recut's furniture are the same slab under three family
 * names, and on 2026-09-10 he walked a batch where the purpose rule had
 * pruned them and found them all back with a spawn pad on top - «аж четыре
 * точки спавна рядом друг с другом? Что за бред полный?». Fifteen of the
 * batch's fifteen new spawn points stood on recut furniture.
 *
 * The family's other half is the same objection from the other side: the
 * vertical slice down a wall in quake116, quake124 and quake126 is the
 * region's own face cutting through a pillar.
 *
 * So no product path deals it. What calls this is
 * `tools/mapgen_recut_driver --recuts` and
 * `tools/mapgen_transaction_driver --recuts`, so that
 * `check_mapgen_recut.py` and the construction guards still have the
 * operator to test. `check_mapgen_no_crates.py` asserts that nothing under
 * src/ does.
 */
void MapGenGeometryEdit_DealRecuts(bool on);

/*
 * TEST SEAM. Whether a pane may be dealt as BREAKABLE; it may not.
 *
 * `SP_func_explosive` frees itself at spawn in deathmatch (id's own code,
 * `src/game/g_misc.c:740`), so a breakable pane is deleted before the first
 * frame of a deathmatch map - which q2dm1 is. The PO shot at three delivered
 * maps and found «не вижу никаких стёкол нигде» while the lumps were
 * perfectly correct.
 *
 * Nothing is deleted: the pane is still built the way base1 builds its own,
 * and this seam is what lets the deathmatch launch guard REGENERATE a map
 * whose panes are supposed to be missing, so its red case does not depend on
 * one surviving artifact. `tools/mapgen_recut_driver --breakable` and
 * `tools/mapgen_transaction_driver --breakable` are the callers;
 * `check_mapgen_no_crates.py` asserts that nothing under src/ is.
 */
void MapGenGeometryEdit_DealBreakableGlass(bool on);

/*
 * TEST SEAM. Whether the schedule deals the 128 x 128 PIT; it does not.
 *
 * The PO's decision, said three times across rounds seven and eight: «какой
 * смысл в этих двух малых квадратах», «чего вообще ты в квадраты скатился этих
 * лунок», «опять тут в комнате эта прорубь с водой мелка, говорил же так не
 * делать». On q2dm1 the family can only ever deal that square - nine of 194
 * footprints survive «the floor it would cut is not one level» and all nine are
 * the smallest size - so the liquid he asked for comes from the FLOOD family,
 * which takes a whole room's outline.
 *
 * `tools/mapgen_recut_driver --pits` and `tools/mapgen_transaction_driver
 * --pits` ask for it back, so the pit's own guards still have their operator.
 * `check_mapgen_no_crates.py` asserts that nothing under src/ does.
 */
void MapGenGeometryEdit_DealPits(bool on);

/*
 * How many tunnels the dig deal takes: 0 for the ambition's own count, or an
 * explicit number for a map made to show the family off (the PO's showcase,
 * ledger row 247). A driver switch like the three above.
 */
void MapGenGeometryEdit_WantDigs(uint32_t count);

/*
 * Glass for a showcase map: walls up to 128 thick, four panes a room, 48 in
 * all (ledger rows 249-250). Off unless a driver turns it on.
 */
void MapGenGeometryEdit_ShowcaseGlass(bool on);

typedef struct {
    uint8_t  kind;
    uint32_t target;      /* RESKIN: texture. STAIRS: staircase. FLOOD:    */
                          /* the pool's top face. DROP: brush.             */
    int32_t  amount;      /* RESKIN: replacement texture. FLOOD: units.    */
    /*
     * Where the seeded deal put it.
     *
     * The schedule is sorted structural-first so a fidelity does not spend its
     * whole budget on paint, and WITHIN a weight it follows this ordinal - the
     * order the seed dealt. Without it the sort's tie-break fell back to kind
     * and target, which do not depend on the seed, and every seed produced the
     * same schedule and therefore the same map.
     */
    uint32_t schedule;
} mapgen_geometry_edit_t;

typedef struct mapgen_geometry_edit_plan_s mapgen_geometry_edit_plan_t;

/*
 * Build the whole ordered schedule for one donor and one seed.
 *
 * `donor_bsp` is what an operator's preconditions are tested against - whether
 * there is air beyond a face, and how much - so the plan is only as honest as
 * the compiled donor it was measured from.
 */
mapgen_geometry_result_t MapGenGeometryEdit_Plan(const mapgen_geometry_t *donor,
                                                 const mapgen_bsp_t *donor_bsp,
                                                 uint64_t seed,
                                                 mapgen_geometry_edit_plan_t **out);

/*
 * One donor, and the others a room may be brought in from.
 *
 * `_Plan` above is this with no other donors, and it stays because most of the
 * schedule has nothing to do with a second map - a caller that has only one
 * should not have to say so twice.
 *
 * The others are borrowed, not owned: they must outlive the plan, because the
 * graft reads their geometry when the edit is applied rather than copying every
 * candidate up front. A plan built from donors that were freed is a plan that
 * reads freed memory, and that is the caller's contract to keep.
 *
 * `names` is what each other donor is CALLED - the map name, not a path - and
 * it is what provenance is recorded as. A graft whose provenance was a pointer
 * would be a graft nobody can audit after the run.
 */
mapgen_geometry_result_t MapGenGeometryEdit_PlanWith(
    const mapgen_geometry_t *donor, const mapgen_bsp_t *donor_bsp,
    uint64_t seed,
    const mapgen_geometry_t *const *others,
    const mapgen_bsp_t *const *other_bsps,
    const char *const *names, uint32_t num_others,
    mapgen_geometry_edit_plan_t **out);

/*
 * The same, against the map the operators will be JUDGED by.
 *
 * The transaction hands the operators the BASELINE - the donor written back
 * out and compiled again - because that is the map a candidate's own compile
 * produces. A plan dealt against the donor's own file and then judged against
 * the baseline is a plan charged for the round trip: places move, and a
 * construction the schedule offered is refused after its compile for burying
 * a climb that only exists in the baseline. Pass the baseline here and the
 * questions are put to it from the first draw. NULL means the donor's own
 * file, which is what `PlanWith` passes.
 *
 * `ambition` is 100 - fidelity and it is a planning input too: it says how wide
 * to search, and a planner told afterwards has already thrown away everything
 * the extra breadth would have found. `PlanWith` passes zero.
 */
mapgen_geometry_result_t MapGenGeometryEdit_PlanOn(
    const mapgen_geometry_t *donor, const mapgen_bsp_t *donor_bsp,
    const mapgen_bsp_t *ground_bsp, int32_t ambition,
    uint64_t seed,
    const mapgen_geometry_t *const *others,
    const mapgen_bsp_t *const *other_bsps,
    const char *const *names, uint32_t num_others,
    mapgen_geometry_edit_plan_t **out);

/*
 * The same, dealt AFTER another plan of the same run.
 *
 * D27 (assignment 24, ledger row 286): a pool is offered a relevel once per
 * run, and a re-deal is the same run asked again - MEASURED on round 30's
 * button, two pools offered on each of four deals, each declining after a
 * fill of 3 to 16 s. `previous` hands on every pool it and the plans before
 * it offered; it is read before this returns, so the caller may free it
 * afterwards. `PlanOn` is this with no previous plan.
 */
mapgen_geometry_result_t MapGenGeometryEdit_PlanAfter(
    const mapgen_geometry_edit_plan_t *previous,
    const mapgen_geometry_t *donor, const mapgen_bsp_t *donor_bsp,
    const mapgen_bsp_t *ground_bsp, int32_t ambition,
    uint64_t seed,
    const mapgen_geometry_t *const *others,
    const mapgen_bsp_t *const *other_bsps,
    const char *const *names, uint32_t num_others,
    mapgen_geometry_edit_plan_t **out);

/*
 * Which donor each grafted bundle came from, and how much of the map it is.
 *
 * GF7 requires a major intact contribution from every active donor and forbids
 * silent omission, so both halves have to be answerable after a run: which
 * donors contributed, and how much. `MapGenGeometryEdit_GraftedFrom` names the
 * donor of the i-th graft in the schedule; `MapGenGeometryEdit_NumGrafts` says
 * how many there are.
 */
/*
 * The box a recut or a pushed wall would empty, so that it can be checked
 * without applying it.
 *
 * An operator whose region is only visible by watching what it did is one
 * nobody can audit: the whole safety argument is about a bounded box, and a
 * reader has to be able to see the box.
 */
bool MapGenGeometryEdit_RegionOf(const mapgen_geometry_edit_plan_t *p,
                                 uint32_t target, float lo[3], float hi[3]);

/*
 * WHERE an edit in the schedule is, whatever family it belongs to.
 *
 * Every family that changes geometry already answers this for itself -
 * `RegionOf` for a recut or a push, `ConstructionOf` for a block,
 * `ReplacedFlight` for a lift, the opening for a doorway or a window - and a
 * caller that wants to write down what a run built had to know which one to
 * ask. That is how attributing four screenshots to three families cost the PO
 * two rounds of asking on 2026-09-10.
 *
 * So: one box, or false for a family that has no place (a reskin, a relight).
 * `donor_bsp` and `donor` may be NULL, and the families that need them are the
 * ones that answer false without them.
 */
bool MapGenGeometryEdit_BoxOf(const mapgen_geometry_edit_plan_t *p,
                              const struct mapgen_bsp_s *donor_bsp,
                              const struct mapgen_geometry_s *donor,
                              uint32_t schedule, float lo[3], float hi[3]);

/*
 * WHICH ENTITIES a paint edit changes - a swap's two pickups, a spawn move's
 * start - by their index in the geometry, which is the index the apply writes.
 *
 * D25 (assignment 24, ledger row 286): a family that moves no architecture is
 * judged by what it does move, and the transaction compares these entities
 * with the parent's. Returns how many were written to `out`, at most `cap`;
 * zero for every family that names none and for an index past the schedule.
 */
uint32_t MapGenGeometryEdit_NamedEntities(const mapgen_geometry_edit_plan_t *p,
                                          uint32_t schedule, uint32_t out[],
                                          uint32_t cap);

/*
 * A flood's WHOLE footprint: its liquid boxes and every piece of its shell,
 * from under the slab to the highest shell top.
 *
 * `BoxOf` answers the water alone, and the gate used it to decide which buried
 * places a flood answers for - so a place under the SHELL, one cell outside the
 * water, was refused as someone else's. MEASURED 2026-09-13 (ledger rows
 * 242-243): the arena's lake answered 48 of 48 places and proved 26 of 26
 * pairs, and was refused for 1776 768 432, under its own ring. False for any
 * edit that is not a flood.
 */
bool MapGenGeometryEdit_FloodFootprint(const mapgen_geometry_edit_plan_t *p,
                                       uint32_t schedule, float lo[3],
                                       float hi[3]);


/*
 * The staircase a lift edit REPLACES, so a gate can tell a way that was taken
 * away from a way that was rebuilt as a machine.
 *
 * A lift is a flight of stairs removed and a func_plat put where it was. It
 * serves the same two heights by the same route, and a player uses it to go
 * where the steps used to take him - but every standing place ON the steps is
 * gone, and a rule that counts those as ways lost refuses every lift there
 * will ever be. MEASURED on q2dm1: seventeen and eighteen places per flight,
 * three lifts refused per run, and the three forks the PO walked on 2026-09-08
 * had no machines in them at all.
 *
 * `schedule` is the position in the schedule, which is what ApplyOne takes.
 * True only for a flight THIS SEED turns into a lift; the box is the flight's
 * own footprint and height, widened by what a standing player occupies.
 */
bool MapGenGeometryEdit_ReplacedFlight(const mapgen_geometry_edit_plan_t *p,
                                       const struct mapgen_geometry_s *donor,
                                       uint32_t schedule,
                                       float lo[3], float hi[3], float *rise);

/*
 * And where a construction will stand, before it is built.
 *
 * The block and the recut are the two families that ADD architecture to a
 * room, and TZ 14 says nothing about whether what they add is worth having.
 * The PO does: "add interesting moments of architecture, rework it
 * interestingly, and do not stick in things nobody needs" (2026-09-08). A gate
 * that means to ask whether a player can USE what was built has to know where
 * it is, and the answer must be the builder's own - `block_stands` decides
 * both, so the box a gate reads is the box that gets built.
 *
 * For a block that is the platform with its step, dropped onto the ground
 * under its footprint; for a recut, the region it empties and refills.
 */
bool MapGenGeometryEdit_ConstructionOf(const mapgen_geometry_edit_plan_t *p,
                                       const struct mapgen_bsp_s *donor_bsp,
                                       uint32_t schedule,
                                       float lo[3], float hi[3]);

uint32_t    MapGenGeometryEdit_NumGrafts(const mapgen_geometry_edit_plan_t *p);
/*
 * Brief 9 (row 412): the second map a dig owes to - the map a room of it was brought from ("room-of") or whose
 * room's skin it wears - or NULL; and the plan's tally of the second map: [0] its rooms dealt, [1] the generated
 * rooms in its skin, [2] its rooms tried, [3] too big or too small, [4] with nothing inside their walls, [5] with no
 * rock site of their size, [6] sites with no pickup to give.
 */
const char *MapGenGeometryEdit_DigFrom(const mapgen_geometry_edit_plan_t *p, uint32_t dig);
const char *MapGenGeometryEdit_DigShape(const mapgen_geometry_edit_plan_t *p, uint32_t dig);
void MapGenGeometryEdit_SecondTally(const mapgen_geometry_edit_plan_t *p, uint32_t out[8]);

/*
 * Row 412, the PO: «Можно также это вынести в параметры». How many of the base's own wall pieces - its lamps and the
 * ornaments it repeats - the digs hang, in percent of the rule's: 0 none, 100 the rule (one every 128 along a run),
 * up to 200. Process-wide, like the dig seams; 100 until set.
 */
void MapGenGeometryEdit_SetWallDecor(uint32_t percent);

/*
 * Row 412, the PO: «А добавление новых жидкостей можно регулировать?», «аналогичные параметры для заливки лавой и
 * кислотой». How much NEW liquid the floods lay, per kind (0 water, 1 slime, 2 lava): a percent of the rooms a flood
 * may take - 0 none (water at 0 raises no pool either), 100 every room that passes the floods' gates - or -1, the
 * default (the ambition decides). Any kind at 50 or more puts the floods first in the schedule.
 */
void MapGenGeometryEdit_SetNewLiquid(uint32_t which, int32_t percent);

const char *MapGenGeometryEdit_GraftedFrom(const mapgen_geometry_edit_plan_t *p,
                                           uint32_t i);

/*
 * Which staircases the schedule is allowed to touch, as a bitmask.
 *
 * A staircase is the one operator whose safety cannot be argued from the
 * geometry alone: the steps of a flight built against the outer wall are part
 * of what seals the map, and a replacement that does not fill exactly the same
 * volume opens it to the void. So each one is COMPILED on its own, once, and
 * the ones that leak are struck out of every fidelity. Contract 27.0: propose
 * one typed edit, compile it, keep it only if every gate stays green.
 */
/*
 * The map the operators measure against.
 *
 * A plan is dealt once and applied many times, and every accepted edit moves
 * the map underneath it. Until 2026-09-08 every check an operator made - is
 * this space clear, is there ground under this footprint, is this shaft empty
 * - read the DONOR's own compiled map, so the second round's block saw the
 * same empty stairwell the first one had filled: MEASURED on q2dm1 seed 3,
 * three blocks in one stairwell over three rounds, 160 x 128 x 344 of solid
 * where a flight of stairs had been.
 *
 * The transaction hands the accepted map here after every accepted attempt.
 * Until it does, the donor's own is what the operators see, which is right
 * for the first round and for every caller that applies one edit.
 */
void     MapGenGeometryEdit_SetGround(mapgen_geometry_edit_plan_t *plan,
                                      const mapgen_bsp_t *ground);

/*
 * How far from the donor this run may go, as (100 - fidelity).
 *
 * A fork at ninety per cent of its donor moves a water level by a stride; one
 * at nothing moves it by a storey. The operators that can be more or less
 * ambitious read it; the rest do not care. The pipeline sets it, because the
 * fidelity is its own.
 */
void     MapGenGeometryEdit_SetAmbition(mapgen_geometry_edit_plan_t *plan,
                                        int32_t ambition);

/*
 * Is there a way through the map in this box - a stair, a step, a ledge?
 *
 * The question every construction asks before it is built, exposed so that a
 * guard can ask it of the same box and compare its answer with the one the
 * route probe gives for the compiled file. They disagreed once, on a block
 * that stood on a climb the operator had just been told was not there, and
 * an answer nobody can ask for from outside is an answer nobody can check.
 */
bool     MapGenGeometryEdit_RegionHasClimb(const struct mapgen_bsp_s *ground,
                                           const float mins[3],
                                           const float maxs[3]);

void     MapGenGeometryEdit_SetStairMask(mapgen_geometry_edit_plan_t *plan,
                                         uint64_t mask);
uint32_t MapGenGeometryEdit_NumStairs(const mapgen_geometry_edit_plan_t *plan);

/* Where one staircase stands. A replacement is allowed to change what is
   inside this box and nothing outside it, which is how the qualification pass
   tells a lift shaft from a hole in somebody else's wall. */
bool MapGenGeometryEdit_StairBounds(const mapgen_geometry_edit_plan_t *plan,
                                    uint32_t stair, float mins[3], float maxs[3]);

/*
 * Why a widen would be refused.
 *
 * `widen-connector` is the largest structural family on q2dm1 and it refuses
 * 41 of its 43 candidates. Nothing branches on this: it exists because a bare
 * `false` makes "no rock behind it" and "somebody else's brush is in the way"
 * the same answer, and a number with no reason under it cannot be worked on.
 */
typedef enum {
    MAPGEN_WIDEN_OK = 0,
    MAPGEN_WIDEN_NO_SIDE,      /* the plane the plan named is not a face now */
    MAPGEN_WIDEN_NO_SAMPLES,   /* the face carries no points to test          */
    MAPGEN_WIDEN_FLUSH,        /* a coplanar face is not coming along         */
    MAPGEN_WIDEN_BACKFACE,     /* the wall's own far side is within 256       */
    MAPGEN_WIDEN_NOT_WORLD,    /* the face belongs to a brush model           */
    MAPGEN_WIDEN_TOO_THIN,     /* less rock behind it than the cut wants      */
    MAPGEN_WIDEN_INTRUDER,     /* somebody else's solid inside the cut        */
    MAPGEN_WIDEN_REASONS
} mapgen_widen_refusal_t;

const char *MapGenGeometryEdit_WidenRefusalName(mapgen_widen_refusal_t why);

/*
 * Ask of ONE planned widen what would happen to it, without applying it.
 *
 * The candidate is passed because the answer depends on the map as it stands:
 * a face that had rock behind it before an earlier edit may not now.
 */
mapgen_widen_refusal_t MapGenGeometryEdit_WhyWidenRefused(
    const mapgen_geometry_edit_plan_t *plan, mapgen_geometry_t *candidate,
    const mapgen_bsp_t *donor_bsp, uint32_t widen);

/* Apply nothing but one staircase, which is how that staircase gets its
   verdict. */
mapgen_geometry_result_t MapGenGeometryEdit_ApplyOneStair(const mapgen_geometry_edit_plan_t *plan,
                                                          mapgen_geometry_t *candidate,
                                                          const mapgen_geometry_t *donor,
                                                          uint32_t stair);

void     MapGenGeometryEdit_Free(mapgen_geometry_edit_plan_t *plan);
/*
 * Apply exactly ONE of the planned edits, by index.
 *
 * What a per-edit transaction needs and what the batch applier could never
 * offer: `out_changed` says whether the operator actually did anything, which
 * is not the same as whether it was asked to. An edit that declines - a
 * staircase the compiler struck out, a room too small for a platform - has
 * spent nothing, and a schedule that counted it would be counting air.
 */
mapgen_geometry_result_t MapGenGeometryEdit_ApplyOne(const mapgen_geometry_edit_plan_t *plan,
                                                     mapgen_geometry_t *candidate,
                                                     const mapgen_geometry_t *donor,
                                                     uint32_t index,
                                                     bool *out_changed);

/*
 * Why the operator that just ran declined, in its own words.
 *
 * Valid immediately after an ApplyOne that came back `changed` false, and
 * empty before the first one. An operator that answers only "changed no"
 * tells a reader nothing: on 2026-09-08 that was four hundred
 * REJECTED_NOT_APPLIED per run, turn-bundle refusing twelve of twelve and
 * reshape-room twelve of twelve, and no way to say whether a family was
 * refusing for one reason or for fifty without reading the source and
 * guessing. The transaction records it on the step and the ledger tallies by
 * it.
 */
const char *MapGenGeometryEdit_WhyDeclined(void);

/*
 * And why the plan does not CONTAIN something.
 *
 * `WhyDeclined` answers for an edit that was offered and then refused itself
 * at apply time. This answers the other half: an edit the planner considered
 * and did not offer at all. A family that returns an empty schedule is
 * otherwise indistinguishable from a family that was never asked, and the
 * recut spent a delivery in that state - three regions grown, zero
 * constructions built, three silent `continue`s.
 *
 * `Refusal` returns line `i` of at most MAPGEN_EDIT_REFUSALS kept;
 * `RefusalsSeen` is how many there were in all.
 */
/* 1024, not 256: a showcase listing's tunnels and panes spent the 256 before
   the passages' flood lines were reached (assignment 22 S0, ledger row 266);
   the plan is heap-allocated and 160 bytes a line */
#define MAPGEN_EDIT_REFUSALS 1024u
uint32_t MapGenGeometryEdit_NumRefusals(const mapgen_geometry_edit_plan_t *p);
uint32_t MapGenGeometryEdit_RefusalsSeen(const mapgen_geometry_edit_plan_t *p);
const char *MapGenGeometryEdit_Refusal(const mapgen_geometry_edit_plan_t *p,
                                       uint32_t i);

/* And which of the builder's own questions refused the last construction it
   was asked about. Set by every path that says a block does not stand. */
const char *MapGenGeometryEdit_WhyNotStanding(void);

/* And which question refused the last pair of rooms offered as each other's
   replacement - the swap, the recomposition and the graft all ask it. */
const char *MapGenGeometryEdit_WhyNotInterchangeable(void);

/*
 * The nine ground heights under the last footprint the builder measured, and
 * the box they were measured over.
 *
 * "Not one floor" is a verdict; these are what it was reached from. Returns
 * false for a sample that found no ground at all within a thousand units,
 * which is a footprint over a pit. Index is i*3+j over the footprint's three
 * x positions and three y positions, low to high.
 */
bool MapGenGeometryEdit_LastGround(uint32_t i, float *out_height);
const float *MapGenGeometryEdit_LastGroundBox(void);
/* And the question itself: is the ground under this footprint ONE floor? */
bool MapGenGeometryEdit_OneFloor(const mapgen_bsp_t *ground, const float lo[3],
                                 const float hi[3]);

/*
 * Where a planned widen is: the plane it will move and the point on it the
 * planner was looking at.
 *
 * A diagnostic, and the reason it is in the interface rather than in a printf:
 * a fixture that says "both flanks were widened" cannot be argued with until
 * somebody can see which two walls those were.
 */
bool MapGenGeometryEdit_WidenAt(const mapgen_geometry_edit_plan_t *plan,
                                uint32_t target, float normal[3], float *dist,
                                float center[3]);

/*
 * Which room a planned turn belongs to, and which turn it is.
 *
 * A diagnostic with the same reason as the widen's: "three turns were planned"
 * is not a finding until somebody can see which rooms they were for.
 */
bool MapGenGeometryEdit_TurnAt(const mapgen_geometry_edit_plan_t *plan,
                               uint32_t target, uint32_t *room,
                               uint32_t *quarter_turns, bool *mirror_x);

/* The i-th planned edit, so a caller can attempt them in its own order. */
const mapgen_geometry_edit_t *MapGenGeometryEdit_At(const mapgen_geometry_edit_plan_t *plan,
                                                    uint32_t index);

uint32_t MapGenGeometryEdit_Count(const mapgen_geometry_edit_plan_t *plan);
/*
 * How many seconds a SHOT pane of this plan's map stays down, in 2..30.
 *
 * Published so a guard can assert that the number in the file is the number
 * the plan dealt, rather than assert a constant: «не ровно через 10 секунд, а
 * варьировалось от карты к карте - от 2 до 30» (PO, 2026-09-11). Dealt from the
 * seed AND the ambition, so one seed at five fidelities gives five numbers.
 */
uint32_t MapGenGeometryEdit_GlassWait(const mapgen_geometry_edit_plan_t *plan);

/*
 * One DIG, as the plan holds it, so a guard and a README can say where it goes
 * without re-deriving it.
 *
 * `from`/`to` are the two standing spots, on their floors; `shape` is what was
 * built between them ("shaft+lift", "stair", "ell", "stair+lift"); `ratio` is
 * the shortcut ratio x100 over the ROOM-LINK graph; `steps`, `landings`,
 * `lights` and `lift` are what is in it.
 */
typedef struct {
    float    from[3];
    float    to[3];
    uint32_t room_from, room_to;
    uint32_t ratio;
    uint32_t steps;
    uint32_t landings;
    uint32_t lights;
    bool     lift;
    bool     hatch;
    uint32_t halls;       /* rooms grown on the passage (ledger row 310) */
    char     shape[16];
    bool     air;         /* row 405: an annex built in the map's free air */
} mapgen_dig_report_t;

/*
 * WATCH a pair of endpoints through the dig planner.
 *
 * The plan's ledger then carries a line per stage for that pair - laid out,
 * shortcut ratio, swept volume, accepted - so an example that cannot be dug
 * names the stage and the coordinates that refused it instead of disappearing
 * into a tally. Assignment 14 requires exactly that of the PO's three examples.
 *
 * At most four watches; they are process-wide and `ClearDigWatches` removes
 * them, which a guard that plans several donors in one process must do.
 */
void MapGenGeometryEdit_WatchDig(const float from[3], const float to[3],
                                 const char *name);
void MapGenGeometryEdit_ClearDigWatches(void);

/*
 * TEST SEAM: which of the dig's four passes run - bit 1 shell, 2 carve, 4 fill,
 * 8 fit. All four by default; nothing under `src/` calls this.
 *
 * It is what a controlled RED needs: take the shell away and a fixture whose
 * passage runs through the void must stop sealing. It is also how the leak of
 * 2026-09-11 was found, three compiles at a time.
 */
void MapGenGeometryEdit_DigPasses(uint32_t mask);

/*
 * How many digs of this process wore a sky skin (ledger row 354): a dig whose
 * roof rises past a sky brush near it gets a detail shell inside an enclosure
 * of sky, so its outer faces are drawn. Observed work, for a driver to print
 * and a guard to require.
 */
uint32_t MapGenGeometryEdit_SkySkins(void);

/* Digs a sky skin declined: rock it could not clear lay against the sky (row 366). */
uint32_t MapGenGeometryEdit_SkinRockRefusals(void);

/* Whether a point lies in a skinned dig's gap - between its shell and its
   enclosure's outer face (row 369). Read from the bands the digs record. */
bool MapGenGeometryEdit_InSkinGap(const mapgen_geometry_t *g, const float p[3]);

/*
 * The SKY LIFT (ledger row 384): a skinned dig whose roof rises past a
 * courtyard's lid lifts the sky over that courtyard, so the building stands in
 * real air the visibility carries. Observed work: lifts made, and the floor,
 * clip and sky brushes they laid. `SetSkyLift(false)` is the RED's switch -
 * only `tools/mapgen_recut_driver --nolift` calls it.
 */
uint32_t MapGenGeometryEdit_SkyLifts(void);
uint32_t MapGenGeometryEdit_SkyLiftFloorBrushes(void);
uint32_t MapGenGeometryEdit_SkyLiftClipBrushes(void);
uint32_t MapGenGeometryEdit_SkyLiftSkyBrushes(void);
void MapGenGeometryEdit_SetSkyLift(bool on);
/* The last lift planned, in words: its lid, F, top, the brushes it laid. */
const char *MapGenGeometryEdit_SkyLiftSaid(void);

/*
 * TEST SEAM: whether the dig planner ROUTES pairs no straight shape can lay -
 * an A* through the rock that goes round another room instead of breaking into
 * it. On by default; nothing in the product turns it off. The dig guard's
 * controlled RED does, to show the routed candidates are the router's.
 */
void MapGenGeometryEdit_DigRouter(bool on);

/*
 * TEST SEAM: how many HALLS a long passage gets, how wide and how tall
 * (ledger row 310). Zero for each is the ambition's own; nothing in the
 * product calls this. `tools/mapgen_recut_driver --halls C W H` and the dig
 * guard's case 6 do, to make the proof that keeps a hall in rock refuse.
 */
void MapGenGeometryEdit_DigHalls(uint32_t count, float wide, float high);

/*
 * TEST SEAM: how many ANNEX rooms a plan deals and how big (ledger row 315).
 * Zero for each is the ambition's own; nothing in the product calls this.
 * `tools/mapgen_recut_driver --annex C W D H` and the dig guard's case 7 do, to
 * make the proof that keeps an annex in rock refuse.
 */
/* Row 412, a test seam: the annexes' footprints as they were before row 412 capped them by the base's own rooms -
   the dig guard's staged cases stand on them. Off unless asked. */
void MapGenGeometryEdit_DigAnnexUncapped(bool on);
/* Row 412, a test seam: how many real rooms a plan deals (UINT32_MAX: by its ambition, the default). */
void MapGenGeometryEdit_DigRealRooms(uint32_t count);
void MapGenGeometryEdit_DigAnnexes(uint32_t count, float wide, float deep,
                                   float high);

/*
 * TEST SEAM: the widest gap a WING's link between two annex rooms may span
 * (ledger row 324). Zero is the product's own; nothing in the product calls
 * this. `tools/mapgen_recut_driver --annexgap G` and the dig guard do.
 */
void MapGenGeometryEdit_DigAnnexGap(float gap);

/*
 * TEST SEAM: how many STOREYS a plan wants (ledger row 327). Zero is the
 * ambition's own; nothing in the product calls this.
 * `tools/mapgen_recut_driver --storeys N` and the dig guard's case 8 do.
 */
void MapGenGeometryEdit_DigStoreys(uint32_t count);

/*
 * TEST SEAM: how many SPANS a plan wants (row 405, brief 5 W5). Zero is the product's own - spans on an arena only
 * (a donor whose annexes were built in its free air), as many as the ambition gives; nothing in the product calls
 * this. `tools/mapgen_recut_driver --spans N` and the donors guard's span fixture do.
 */
void MapGenGeometryEdit_DigSpans(uint32_t count);

/*
 * Row 410: which liquids the plan turns into which - "water-lava", "water-slime", "lava-water", "slime-water",
 * "lava-slime", "slime-lava", or "mix" (each pool another liquid, by the seed); empty or NULL: none dealt.
 */
void MapGenGeometryEdit_SetLiquids(const char *mode);

/*
 * The game folder a dig reads its textures' colours from (row 408, brief 6): the .wal under it or in any .pak there,
 * through pics/colormap.pcx - the colour a panel emits in, which q2tools takes from the same file. Set by the
 * transaction from its moddir; empty, a panel's colour is unknown and it is kept as before.
 */
void MapGenGeometryEdit_SetGameDir(const char *dir);

/*
 * The finished map's light pass words (row 408): a dig's downlight is valued for the light it gives AFTER that pass
 * scales every light (`-scale`, the donor's calibration in tools/mapgen_donor_light.json - 0.64 on q3t2, 1.15 on
 * cor). Set by the pipeline from its --light-flags; empty is a scale of 1.
 */
void MapGenGeometryEdit_SetLightFlags(const char *flags);

/*
 * The waypoints a player walks through one dig, as x,y,z triples, and how many
 * were written. `capacity` is in waypoints, not floats.
 *
 * What it is for: a player hull swept along the STRAIGHT LINE between a dig's
 * two ends leaves the passage wherever it bends, and reports the rock beside it
 * as «no ground». The chain is the passage.
 */
uint32_t MapGenGeometryEdit_DigChain(const mapgen_geometry_edit_plan_t *plan,
                                     uint32_t index, float *out,
                                     uint32_t capacity);

uint32_t MapGenGeometryEdit_NumDigs(const mapgen_geometry_edit_plan_t *plan);

/*
 * One dig, segment by segment: six floats each, the first at its upper end and
 * the last at its lower one, in the order a player walks them.
 *
 * What it is for: the dead-end gate walks the compiled candidate through the
 * passage, and the bounding box of a passage that bends holds rooms that are
 * not in it - a walk through THOSE is not a walk through the passage.
 */
uint32_t MapGenGeometryEdit_DigBoxes(const mapgen_geometry_edit_plan_t *plan,
                                     uint32_t index, float *out,
                                     uint32_t capacity);

/*
 * TEST SEAM: whether a routed passage gets its MOUTH - the rock between the
 * room it starts from and its first carved cell, cut away. On by default;
 * nothing in the product turns it off. `tools/mapgen_recut_driver --nomouth`
 * and the dig guard's controlled RED do, to rebuild the closed tunnel the PO
 * walked into on 2026-09-11.
 */
void MapGenGeometryEdit_DigMouths(bool on);
bool MapGenGeometryEdit_DigAt(const mapgen_geometry_edit_plan_t *plan,
                              uint32_t index, mapgen_dig_report_t *out);

uint32_t MapGenGeometryEdit_CountOfKind(const mapgen_geometry_edit_plan_t *plan,
                                        mapgen_edit_kind_t kind);

/* How many of one kind a given fidelity would actually spend - which is what
   a report should say, rather than how many the schedule could have offered. */
uint32_t MapGenGeometryEdit_SpentOfKind(const mapgen_geometry_edit_plan_t *plan,
                                        int32_t fidelity,
                                        mapgen_edit_kind_t kind);

/*
 * Spend the schedule down to the requested fidelity, on a candidate that is
 * already a clone of the donor.
 *
 * `fidelity` is 0..100 and decides how much of the schedule runs: none of it
 * at 100, all of it at 0. `out_spent` receives how many edits were applied,
 * which is what the report shows and what a test compares between two
 * fidelities to prove the nesting.
 */
mapgen_geometry_result_t MapGenGeometryEdit_Apply(const mapgen_geometry_edit_plan_t *plan,
                                                  mapgen_geometry_t *candidate,
                                                  const mapgen_geometry_t *donor,
                                                  int32_t fidelity,
                                                  uint32_t *out_spent);

#endif /* MAPGEN_GEOMETRY_EDIT_H */
