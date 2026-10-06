/*
 * MAPGEN-1 layout test driver.
 *
 * Compiled and run by tools/check_mapgen_layout_contract.py.
 *
 *   driver run <map.bsp> <map.bsp> <map.bsp>
 *
 * Every geometric claim is checked by measuring the boxes here, not by asking
 * the module whether it kept its promise. A failed embedding is an ordinary
 * attempt outcome, so the cases that matter are about what a SUCCESSFUL one
 * guarantees and about finding one inside contract 16's attempt budget.
 */

#include "common/mapgen_layout.h"
#include "common/mapgen_lineage.h"
#include "common/mapgen_features.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int CASES;
static int FAILED;

static void check(const char *name, bool ok, const char *detail)
{
    CASES++;
    if (ok) {
        printf("  PASS  %s\n", name);
        return;
    }
    FAILED++;
    printf("  FAIL  %s%s%s\n", name, detail && *detail ? "  -- " : "",
           detail ? detail : "");
}

/* -------------------------------------------------------------------------- */

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    const long size = ftell(f);
    if (size < 0) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) { fclose(f); return NULL; }
    const size_t got = fread(data, 1, (size_t)size, f);
    fclose(f);
    *out_size = got;
    return data;
}

static bool add_map(mapgen_training_t *t, const char *path)
{
    size_t size = 0;
    uint8_t *data = read_file(path, &size);
    if (!data)
        return false;
    uint8_t sha[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(data, size, sha);

    mapgen_bsp_t *bsp = NULL;
    mapgen_genome_t *genome = NULL;
    mapgen_space_t *space = NULL;
    mapgen_wiring_t *wiring = NULL;
    mapgen_features_t *features = NULL;
    mapgen_space_params_t p = MapGenSpace_DefaultParams();
    bool ok = false;

    if (MapGenBsp_Load(data, size, &bsp) == MAPGEN_BSP_OK &&
        MapGenGenome_Extract(bsp, &genome) == MAPGEN_GENOME_OK &&
        MapGenSpace_Build(bsp, &p, &space) == MAPGEN_SPACE_OK &&
        MapGenWiring_Build(genome, bsp, &wiring) == MAPGEN_WIRING_OK &&
        MapGenFeatures_Build(bsp, genome, space, wiring, &features)
            == MAPGEN_FEATURES_OK) {
        ok = MapGenTraining_AddSource(t, path, "baseq2", size, sha,
                                      features, genome, wiring,
                                      /* this driver learns statistics, not architecture:
                                         neither a shape nor a solid */
                                      NULL, NULL)
             == MAPGEN_TRAINING_OK;
    }
    MapGenFeatures_Free(features);
    MapGenWiring_Free(wiring);
    MapGenSpace_Free(space);
    MapGenGenome_Free(genome);
    MapGenBsp_Free(bsp);
    free(data);
    return ok;
}

/* -------------------------------------------------------------------------- */

static mapgen_mix_t *MODEL;
static mapgen_recipe_t *RECIPE;

static bool boxes_overlap(const mapgen_layout_box_t *a,
                          const mapgen_layout_box_t *b)
{
    for (int axis = 0; axis < 3; axis++)
        if (a->maxs[axis] <= b->mins[axis] || a->mins[axis] >= b->maxs[axis])
            return false;
    return true;
}

/* Do two boxes share any face area at all? A passage has to actually reach
   the room it claims to connect. */
static bool boxes_touch_or_overlap(const mapgen_layout_box_t *a,
                                   const mapgen_layout_box_t *b)
{
    for (int axis = 0; axis < 3; axis++)
        if (a->maxs[axis] < b->mins[axis] || a->mins[axis] > b->maxs[axis])
            return false;
    return true;
}

static mapgen_recipe_t *make_recipe(uint64_t seed, int32_t scale)
{
    mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
    if (!b)
        return NULL;
    uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
    memset(uuid, 0x33, sizeof(uuid));
    MapGenRecipe_SetIdentity(b, uuid, seed);
    MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA, 2, 16, 32, 0);
    MapGenRecipe_SetOutput(b, "Layout", "layout");

    mapgen_recipe_snapshot_t snap;
    memset(&snap, 0, sizeof(snap));
    memset(snap.revision_uuid, 0x11, sizeof(snap.revision_uuid));
    snap.weight = 50;
    MapGenRecipe_AddSnapshot(b, &snap);

    MapGenRecipe_AddControl(b, "map_scale", scale, scale);
    MapGenRecipe_AddControl(b, "arch_verticality", 2, 2);

    const char *added[MAPGEN_ROUTE_KIND_COUNT];
    uint32_t num_added = 0;
    for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
        const char *control = MapGenTopology_RouteControl((mapgen_route_kind_t)k);
        if (!control)
            continue;
        bool already = false;
        for (uint32_t i = 0; i < num_added && !already; i++)
            already = !strcmp(added[i], control);
        if (already)
            continue;
        added[num_added++] = control;
        const uint32_t role = MapGenTopology_RouteRole((mapgen_route_kind_t)k);
        const int32_t level = (!role || MapGenMix_RoleIsLearned(MODEL, role)) ? 2 : 0;
        MapGenRecipe_AddControl(b, control, level, level);
    }

    uint8_t *bytes = NULL;
    size_t size = 0;
    const mapgen_recipe_result_t r = MapGenRecipe_Finish(b, &bytes, &size);
    MapGenRecipe_BuilderFree(b);
    if (r != MAPGEN_RECIPE_OK)
        return NULL;
    mapgen_recipe_t *recipe = NULL;
    MapGenRecipe_Open(bytes, size, &recipe);
    free(bytes);
    return recipe;
}

/* The first attempt that embeds, or none inside the budget. */
static mapgen_layout_t *first_success(const mapgen_recipe_t *recipe,
                                      uint32_t budget, uint32_t *at,
                                      mapgen_topology_t **topology_out)
{
    for (uint32_t attempt = 0; attempt < budget; attempt++) {
        mapgen_topology_t *topology = NULL;
        if (MapGenTopology_Build(MODEL, recipe, attempt, NULL, &topology)
            != MAPGEN_TOPOLOGY_OK)
            continue;
        mapgen_layout_t *l = NULL;
        const mapgen_layout_result_t r =
            MapGenLayout_Build(topology, MODEL, recipe, attempt, &l);
        if (r == MAPGEN_LAYOUT_OK) {
            if (at)
                *at = attempt;
            if (topology_out)
                *topology_out = topology;
            else
                MapGenTopology_Free(topology);
            return l;
        }
        MapGenLayout_Free(l);
        MapGenTopology_Free(topology);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    if (argc < 4 || strcmp(argv[1], "run")) {
        printf("usage: driver run <3 map paths>\n");
        return 2;
    }

    mapgen_training_t *t = MapGenTraining_Create();
    for (int i = 2; i < argc; i++) {
        if (!add_map(t, argv[i])) {
            printf("TRAIN_FAILED\n");
            return 1;
        }
    }
    uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES], revision[MAPGEN_SNAPSHOT_UUID_BYTES];
    memset(lineage, 0xA0, sizeof(lineage));
    memset(revision, 0xA0, sizeof(revision));
    uint8_t *image = NULL;
    size_t image_size = 0;
    if (MapGenLineage_New(t, lineage, revision, 1756600000000ull,
                          MAPGEN_COMPRESSION_DEFLATE, &image, &image_size)
        != MAPGEN_LINEAGE_OK) {
        printf("LINEAGE_FAILED\n");
        return 1;
    }
    MapGenTraining_Free(t);

    mapgen_snapshot_t *snap = NULL;
    MapGenSnapshot_Open(image, image_size, &snap);
    mapgen_mix_input_t input;
    memset(&input, 0, sizeof(input));
    input.snapshot = snap;
    memcpy(input.revision_uuid, MapGenSnapshot_Header(snap)->revision_uuid,
           MAPGEN_SNAPSHOT_UUID_BYTES);
    memcpy(input.payload_sha256, MapGenSnapshot_Header(snap)->payload_sha256,
           MAPGEN_SHA256_BYTES);
    input.weight = 100;
    if (MapGenMix_Build(&input, 1, NULL, &MODEL) != MAPGEN_MIX_OK) {
        printf("MIX_FAILED\n");
        return 1;
    }

    RECIPE = make_recipe(0x1234567890ABCDEFull, 1);
    if (!RECIPE) {
        printf("RECIPE_FAILED\n");
        return 1;
    }

    /* --- a candidate is found inside the attempt budget -------------------- */
    {
        uint32_t found_at = 0;
        mapgen_topology_t *topology = NULL;
        mapgen_layout_t *l = first_success(RECIPE, 32, &found_at, &topology);
        check("an embedding is found inside contract 16's 32 attempts",
              l != NULL, "a refusal is an attempt outcome, not a failure");
        if (!l)
            return 1;

        /* --- every room ---------------------------------------------------- */
        bool on_grid = true, big_enough = true, in_world = true;
        for (uint32_t i = 0; i < MapGenLayout_NumRooms(l); i++) {
            const mapgen_layout_room_t *room = MapGenLayout_Room(l, i);
            for (int axis = 0; axis < 3; axis++) {
                if (room->space.mins[axis] % MAPGEN_LAYOUT_GRID
                    || room->space.maxs[axis] % MAPGEN_LAYOUT_GRID)
                    on_grid = false;
                if (room->space.mins[axis] < -MAPGEN_LAYOUT_WORLD_LIMIT
                    || room->space.maxs[axis] > MAPGEN_LAYOUT_WORLD_LIMIT)
                    in_world = false;
            }
            if (room->space.maxs[0] - room->space.mins[0] < MAPGEN_LAYOUT_MIN_ROOM
                || room->space.maxs[1] - room->space.mins[1] < MAPGEN_LAYOUT_MIN_ROOM
                || room->space.maxs[2] - room->space.mins[2]
                   < MAPGEN_LAYOUT_MIN_ROOM_HEIGHT)
                big_enough = false;
        }
        check("every room corner is on the 16-unit grid", on_grid,
              "no rounding to get wrong is how the same recipe stays the same map");
        check("every room is inside Quake II's world", in_world, "");
        check("and big enough to hold a fight, not just a player", big_enough, "");

        bool rooms_disjoint = true;
        for (uint32_t i = 0; i < MapGenLayout_NumRooms(l); i++)
            for (uint32_t j = 0; j < i; j++)
                if (boxes_overlap(&MapGenLayout_Room(l, i)->space,
                                  &MapGenLayout_Room(l, j)->space))
                    rooms_disjoint = false;
        check("no two rooms occupy the same space", rooms_disjoint, "");

        bool cells_distinct = true;
        for (uint32_t i = 0; i < MapGenLayout_NumRooms(l); i++)
            for (uint32_t j = 0; j < i; j++)
                if (MapGenLayout_Room(l, i)->cell[0] == MapGenLayout_Room(l, j)->cell[0]
                    && MapGenLayout_Room(l, i)->cell[1] == MapGenLayout_Room(l, j)->cell[1]
                    && MapGenTopology_Node(topology, i)->band
                       == MapGenTopology_Node(topology, j)->band)
                    cells_distinct = false;
        check("no two rooms on one level share a cell", cells_distinct, "");

        /* --- every passage -------------------------------------------------- */
        check("there is one passage per planned route",
              MapGenLayout_NumPassages(l) == MapGenTopology_NumRoutes(topology),
              "the graph is what every later stage reasons about");

        bool segments_ok = true, reaches_both = true, wide_enough = true;
        for (uint32_t p = 0; p < MapGenLayout_NumPassages(l); p++) {
            const mapgen_layout_passage_t *pass = MapGenLayout_Passage(l, p);
            if (!pass->num_segments || pass->num_segments > MAPGEN_LAYOUT_MAX_SEGMENTS)
                segments_ok = false;
            bool touches_from = false, touches_to = false;
            for (uint32_t s = 0; s < pass->num_segments; s++) {
                const mapgen_layout_box_t *seg = &pass->segments[s];
                for (int axis = 0; axis < 3; axis++)
                    if (seg->mins[axis] % MAPGEN_LAYOUT_GRID
                        || seg->maxs[axis] % MAPGEN_LAYOUT_GRID)
                        on_grid = false;
                /* Two of the three axes have to admit a player. */
                int passable = 0;
                if (seg->maxs[0] - seg->mins[0] >= MAPGEN_LAYOUT_HULL_WIDTH)
                    passable++;
                if (seg->maxs[1] - seg->mins[1] >= MAPGEN_LAYOUT_HULL_WIDTH)
                    passable++;
                if (seg->maxs[2] - seg->mins[2] >= MAPGEN_LAYOUT_HULL_HEIGHT)
                    passable++;
                if (passable < 3)
                    wide_enough = false;
                if (boxes_touch_or_overlap(seg,
                        &MapGenLayout_Room(l, pass->from_room)->space))
                    touches_from = true;
                if (boxes_touch_or_overlap(seg,
                        &MapGenLayout_Room(l, pass->to_room)->space))
                    touches_to = true;
            }
            if (!touches_from || !touches_to)
                reaches_both = false;
        }
        check("every passage is made of one to four segments", segments_ok, "");
        check("every passage segment is on the grid too", on_grid, "");
        check("and admits a standing player in all three axes", wide_enough,
              "a corridor narrower than the hull is not a corridor");
        check("every passage reaches both of the rooms it connects",
              reaches_both, "");

        /* --- the check the module exists for, verified independently -------- */
        {
            uint32_t through_rooms = 0, through_passages = 0;
            for (uint32_t p = 0; p < MapGenLayout_NumPassages(l); p++) {
                const mapgen_layout_passage_t *pass = MapGenLayout_Passage(l, p);
                for (uint32_t s = 0; s < pass->num_segments; s++) {
                    for (uint32_t i = 0; i < MapGenLayout_NumRooms(l); i++) {
                        if (i == pass->from_room || i == pass->to_room)
                            continue;
                        if (boxes_overlap(&pass->segments[s],
                                          &MapGenLayout_Room(l, i)->space))
                            through_rooms++;
                    }
                    for (uint32_t q = 0; q < p; q++) {
                        const mapgen_layout_passage_t *other =
                            MapGenLayout_Passage(l, q);
                        const bool share =
                            pass->from_room == other->from_room
                            || pass->from_room == other->to_room
                            || pass->to_room == other->from_room
                            || pass->to_room == other->to_room;
                        if (share)
                            continue;
                        for (uint32_t u = 0; u < other->num_segments; u++)
                            if (boxes_overlap(&pass->segments[s],
                                              &other->segments[u]))
                                through_passages++;
                    }
                }
            }
            check("no passage breaches a room it does not connect",
                  through_rooms == 0,
                  "lane routing makes it impossible; this is the proof");
            check("and every crossing between unrelated passages is counted",
                  through_passages == MapGenLayout_NumJunctions(l),
                  "a junction is real map-making, but the number is stated "
                  "rather than left implied");
        }

        /* --- the bounds are the bounds ------------------------------------- */
        {
            const mapgen_layout_box_t *bounds = MapGenLayout_Bounds(l);
            bool contains_all = true;
            for (uint32_t i = 0; i < MapGenLayout_NumRooms(l); i++)
                for (int axis = 0; axis < 3; axis++)
                    if (MapGenLayout_Room(l, i)->space.mins[axis] < bounds->mins[axis]
                        || MapGenLayout_Room(l, i)->space.maxs[axis] > bounds->maxs[axis])
                        contains_all = false;
            for (uint32_t p = 0; p < MapGenLayout_NumPassages(l); p++) {
                const mapgen_layout_passage_t *pass = MapGenLayout_Passage(l, p);
                for (uint32_t s = 0; s < pass->num_segments; s++)
                    for (int axis = 0; axis < 3; axis++)
                        if (pass->segments[s].mins[axis] < bounds->mins[axis]
                            || pass->segments[s].maxs[axis] > bounds->maxs[axis])
                            contains_all = false;
            }
            check("the reported bounds contain everything", contains_all, "");
        }

        /* --- determinism --------------------------------------------------- */
        {
            const uint64_t digest = MapGenLayout_CanonicalDigest(l);
            mapgen_layout_t *again = NULL;
            MapGenLayout_Build(topology, MODEL, RECIPE, found_at, &again);
            check("the same topology and attempt give the same layout",
                  again && MapGenLayout_CanonicalDigest(again) == digest, "");
            MapGenLayout_Free(again);
        }

        MapGenTopology_Free(topology);
        MapGenLayout_Free(l);
    }

    /* --- the budget holds across seeds ------------------------------------ */
    {
        uint32_t found = 0, tried = 0;
        for (uint64_t seed = 1; seed <= 8; seed++) {
            mapgen_recipe_t *recipe = make_recipe(seed * 0x9E3779B97F4A7C15ull, 1);
            if (!recipe)
                continue;
            tried++;
            uint32_t at = 0;
            mapgen_layout_t *l = first_success(recipe, 32, &at, NULL);
            if (l)
                found++;
            MapGenLayout_Free(l);
            MapGenRecipe_Free(recipe);
        }
        check("eight different seeds each find an embedding within 32 attempts",
              tried == 8 && found == 8,
              "contract 16's Auto budget has to be enough in practice");
    }

    /* --- a bigger map still places --------------------------------------- */
    {
        mapgen_recipe_t *large = make_recipe(0xC0FFEEull, 3);
        uint32_t at = 0;
        mapgen_layout_t *l = large ? first_success(large, 64, &at, NULL) : NULL;
        check("a Very Large map finds an embedding within the Full Random budget",
              l != NULL, "64 attempts, contract 16's other default");
        if (l) {
            check("and it is the first attempt, not the sixty-fourth",
                  at == 0,
                  "lane routing embeds every graph it is given; the budget is "
                  "headroom, not the mechanism");
        }
        MapGenLayout_Free(l);
        MapGenRecipe_Free(large);
    }

    /* --- the junction counter is a real measurement ----------------------- */
    {
        uint32_t with_junctions = 0, examined = 0;
        for (uint32_t attempt = 0; attempt < 32; attempt++) {
            mapgen_topology_t *topology = NULL;
            if (MapGenTopology_Build(MODEL, RECIPE, attempt, NULL, &topology)
                != MAPGEN_TOPOLOGY_OK)
                continue;
            mapgen_layout_t *l = NULL;
            if (MapGenLayout_Build(topology, MODEL, RECIPE, attempt, &l)
                == MAPGEN_LAYOUT_OK && l) {
                examined++;
                if (MapGenLayout_NumJunctions(l))
                    with_junctions++;
            }
            MapGenLayout_Free(l);
            MapGenTopology_Free(topology);
        }
        check("thirty-two attempts all embed", examined == 32,
              "lane routing cannot breach a room, so nothing refuses them");
        check("and some of them really do have junctions to count",
              with_junctions > 0,
              "a counter that is always zero has not been tested");
    }

    /* --- refusals are refusals -------------------------------------------- */
    {
        mapgen_layout_t *l = (mapgen_layout_t *)1;
        check("a missing topology is refused rather than dereferenced",
              MapGenLayout_Build(NULL, MODEL, RECIPE, 0, &l) == MAPGEN_LAYOUT_ERR_ARGS
              && l == NULL, "");
        check("and a missing recipe too",
              MapGenLayout_Build((const mapgen_topology_t *)&l, MODEL, NULL, 0, &l)
              == MAPGEN_LAYOUT_ERR_ARGS, "");
    }

    MapGenRecipe_Free(RECIPE);
    MapGenMix_Free(MODEL);
    MapGenSnapshot_Free(snap);
    free(image);

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}
