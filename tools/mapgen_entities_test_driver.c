/*
 * MAPGEN-1 entity placement test driver.
 *
 * Compiled and run by tools/check_mapgen_entities_contract.py.
 *
 *   driver run <map.bsp> <map.bsp> <map.bsp>
 *
 * Every placement is re-measured against the room it claims to be in. The
 * cases that matter most are contract 13's: an exact count is placed exactly,
 * `Custom 0` places none, and a count that cannot be met is refused with the
 * control named rather than quietly reduced.
 */

#include "common/mapgen_entities.h"
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

typedef struct {
    const char *control;
    int32_t     count;
} item_request_t;

static mapgen_recipe_t *make_recipe(uint64_t seed, mapgen_goal_t goal,
                                    uint32_t players_max, int32_t scale,
                                    const item_request_t *items,
                                    uint32_t num_items)
{
    mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
    if (!b)
        return NULL;
    uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
    memset(uuid, 0x55, sizeof(uuid));
    MapGenRecipe_SetIdentity(b, uuid, seed);

    uint32_t players_min = 2;
    if (goal == MAPGEN_GOAL_SINGLE_PLAYER)
        players_min = players_max = 1;
    else if (goal == MAPGEN_GOAL_DUEL)
        players_min = players_max = 2;
    else if (goal == MAPGEN_GOAL_TDM)
        players_min = 4;
    if (MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, goal, players_min,
                                players_max, 32, 0) != MAPGEN_RECIPE_OK) {
        MapGenRecipe_BuilderFree(b);
        return NULL;
    }
    MapGenRecipe_SetOutput(b, "Entities", "entities");

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

    for (uint32_t i = 0; i < num_items; i++)
        MapGenRecipe_AddControl(b, items[i].control, items[i].count,
                                items[i].count);

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

/* Topology and layout for one recipe, at the first attempt that embeds. */
static bool stage(const mapgen_recipe_t *recipe, mapgen_topology_t **topology,
                  mapgen_layout_t **layout, uint32_t *attempt_out)
{
    for (uint32_t attempt = 0; attempt < 32; attempt++) {
        mapgen_topology_t *t = NULL;
        if (MapGenTopology_Build(MODEL, recipe, attempt, NULL, &t)
            != MAPGEN_TOPOLOGY_OK)
            continue;
        mapgen_layout_t *l = NULL;
        if (MapGenLayout_Build(t, MODEL, recipe, attempt, &l) == MAPGEN_LAYOUT_OK) {
            *topology = t;
            *layout = l;
            if (attempt_out)
                *attempt_out = attempt;
            return true;
        }
        MapGenLayout_Free(l);
        MapGenTopology_Free(t);
    }
    return false;
}

int main(int argc, char **argv)
{
    if (argc < 4 || strcmp(argv[1], "run")) {
        printf("usage: driver run <3 map paths>\n");
        return 2;
    }

    /*
     * The table first, before anything can be built from it: a row with a
     * missing classname crashes the placement pass, and a case that never
     * runs proves nothing about the table it was written for.
     */
    /* --- the item table is complete --------------------------------------- */
    {
        bool paired = true;
        for (uint32_t i = 0; i < MapGenEntities_NumItemKinds(); i++)
            if (!MapGenEntities_ItemControl(i) || !MapGenEntities_ItemClassname(i))
                paired = false;
        check("every item row has both a control and a classname", paired,
              "one table, so neither can exist without the other");
        check("and there are enough rows to be contract 13's list",
              MapGenEntities_NumItemKinds() >= 20, "");
    }

    /*
     * And stop here if it is broken. A row with a missing classname crashes
     * the placement pass, and a crash on Windows loses everything still
     * sitting in stdout's buffer - including the case that just found the
     * fault. Reporting is worth more than continuing.
     */
    if (FAILED) {
        printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
        return 1;
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

    static const item_request_t WANTED[] = {
        { "item_quad", 1 },
        { "weapon_railgun", 2 },
        { "item_health", 5 },
        { "weapon_bfg", 0 },          /* Custom 0: none, and that is absolute */
    };

    mapgen_recipe_t *recipe = make_recipe(0xA5A5A5A5A5A5A5A5ull, MAPGEN_GOAL_FFA,
                                          8, 2, WANTED, 4);
    if (!recipe) {
        printf("RECIPE_FAILED\n");
        return 1;
    }

    mapgen_topology_t *topology = NULL;
    mapgen_layout_t *layout = NULL;
    uint32_t attempt = 0;
    if (!stage(recipe, &topology, &layout, &attempt)) {
        printf("STAGE_FAILED\n");
        return 1;
    }

    const char *conflict = NULL;
    mapgen_entities_t *entities = NULL;
    mapgen_entities_result_t rc = MapGenEntities_Build(layout, topology, MODEL,
                                                       recipe, attempt,
                                                       &conflict, &entities);
    check("the map is populated", rc == MAPGEN_ENTITIES_OK && entities != NULL,
          MapGenEntities_ResultName(rc));
    if (!entities)
        return 1;

    /* --- contract 13: an exact count is exact ----------------------------- */
    check("one quad was asked for and one was placed",
          MapGenEntities_CountOf(entities, "item_quad") == 1, "");
    check("two railguns likewise",
          MapGenEntities_CountOf(entities, "weapon_railgun") == 2, "");
    check("and five health",
          MapGenEntities_CountOf(entities, "item_health") == 5, "");
    check("Custom 0 places none at all",
          MapGenEntities_CountOf(entities, "weapon_bfg") == 0,
          "contract 13: None is a hard constraint");
    check("and nothing was placed that was never asked for",
          MapGenEntities_CountOf(entities, "item_armor_body") == 0
          && MapGenEntities_CountOf(entities, "ammo_slugs") == 0,
          "a control absent from the recipe resolves to none");

    /* --- spawns ------------------------------------------------------------ */
    {
        const uint32_t spawns =
            MapGenEntities_CountOf(entities, "info_player_deathmatch");
        check("there is one deathmatch spawn per player the envelope resolved to",
              spawns == MapGenRecipe_PlayersMax(recipe), "");
        check("and no single-player start in a deathmatch map",
              MapGenEntities_CountOf(entities, "info_player_start") == 0, "");
    }

    /* --- every placement is inside the room it claims --------------------- */
    {
        uint32_t outside = 0, wrong_height = 0;
        for (uint32_t i = 0; i < MapGenEntities_Count(entities); i++) {
            const mapgen_placement_t *ent = MapGenEntities_At(entities, i);
            if (ent->room == MAPGEN_PLACEMENT_NO_ROOM) {
                /* A light in a corridor, which says so rather than naming a
                   room it is nowhere near. */
                continue;
            }
            const mapgen_layout_room_t *room =
                MapGenLayout_Room(layout, ent->room);
            if (!room) {
                outside++;
                continue;
            }
            for (int axis = 0; axis < 3; axis++)
                if (ent->origin[axis] < room->space.mins[axis]
                    || ent->origin[axis] > room->space.maxs[axis])
                    outside++;

            /*
             * The engine's own numbers, written out.
             *
             * Checking `above != MAPGEN_PLACEMENT_FLOOR_OFFSET` would be a
             * tautology: that constant is exactly what a defect moves, so the
             * check would follow it wherever it went. 24 is the player's mins
             * in inc/shared/shared.h, and a pickup has to be within reach of
             * the floor rather than at head height.
             */
            const int32_t above = ent->origin[2] - room->space.mins[2];
            if (!strcmp(ent->classname, "info_player_deathmatch")
                || !strcmp(ent->classname, "info_player_start")) {
                if (above != 24)
                    wrong_height++;
            } else if (strcmp(ent->classname, "light")) {
                if (above < 0 || above > 32)
                    wrong_height++;
            }
        }
        check("every entity is inside the room it says it is in", outside == 0, "");
        check("and standing on that room's floor, not in it", wrong_height == 0,
              "the player's mins are at -24, so a spawn sits 24 up");
    }

    /* --- nothing shares a spot -------------------------------------------- */
    {
        /*
         * Over sixteen builds, not one. Two placements colliding is a
         * coincidence of two draws, and one build is far too small a sample:
         * a version with no clearance check at all passed a single-build
         * version of this case simply because those draws happened to differ.
         */
        uint32_t collisions = 0, builds = 0;
        for (uint32_t a2 = 0; a2 < 16; a2++) {
            mapgen_topology_t *sweep_topology = NULL;
            mapgen_layout_t *sweep_layout = NULL;
            if (MapGenTopology_Build(MODEL, recipe, a2, NULL, &sweep_topology)
                != MAPGEN_TOPOLOGY_OK)
                continue;
            if (MapGenLayout_Build(sweep_topology, MODEL, recipe, a2, &sweep_layout)
                == MAPGEN_LAYOUT_OK) {
                mapgen_entities_t *sweep = NULL;
                if (MapGenEntities_Build(sweep_layout, sweep_topology, MODEL,
                                         recipe, a2, NULL, &sweep)
                    == MAPGEN_ENTITIES_OK && sweep) {
                    builds++;
                    for (uint32_t i = 0; i < MapGenEntities_Count(sweep); i++) {
                        const mapgen_placement_t *x = MapGenEntities_At(sweep, i);
                        if (!strcmp(x->classname, "light"))
                            continue;
                        for (uint32_t j = 0; j < i; j++) {
                            const mapgen_placement_t *y =
                                MapGenEntities_At(sweep, j);
                            if (!strcmp(y->classname, "light"))
                                continue;
                            int32_t d = 0;
                            for (int axis = 0; axis < 3; axis++) {
                                const int32_t delta =
                                    x->origin[axis] - y->origin[axis];
                                d += delta < 0 ? -delta : delta;
                            }
                            if (d < 64)
                                collisions++;
                        }
                    }
                }
                MapGenEntities_Free(sweep);
            }
            MapGenLayout_Free(sweep_layout);
            MapGenTopology_Free(sweep_topology);
        }
        check("sixteen builds were available to look at", builds >= 8, "");
        check("no two placements share a spot, in any of them", collisions == 0,
              "contract 18.2: a spawn inside a pickup is a telefrag waiting");
    }

    /* --- lights ------------------------------------------------------------ */
    {
        /* Every room, and every passage too - lighting only the rooms left
           most of the map's surface lit by nothing, which is measurable in
           the compiled lightmap and was. */
        uint32_t lit_rooms = 0;
        for (uint32_t room = 0; room < MapGenLayout_NumRooms(layout); room++) {
            for (uint32_t i = 0; i < MapGenEntities_Count(entities); i++) {
                const mapgen_placement_t *ent = MapGenEntities_At(entities, i);
                if (ent->room == room && !strcmp(ent->classname, "light")) {
                    lit_rooms++;
                    break;
                }
            }
        }
        check("every room has a light",
              lit_rooms == MapGenLayout_NumRooms(layout), "");

        uint32_t corridor_lights = 0, unlit = 0;
        for (uint32_t i = 0; i < MapGenEntities_Count(entities); i++) {
            const mapgen_placement_t *ent = MapGenEntities_At(entities, i);
            if (strcmp(ent->classname, "light"))
                continue;
            if (ent->room == MAPGEN_PLACEMENT_NO_ROOM)
                corridor_lights++;
            if (!ent->light)
                unlit++;
        }
        check("every light carries the intensity that was learned",
              unlit == 0,
              "leaving it out is not choosing 300, it is declining to choose");

        /*
         * And they are not all the SAME intensity.
         *
         * Every light used to carry the learned median, so a map got one
         * number stamped ninety-seven times - which no map in the corpus does,
         * and which clamps the lightmap to white wherever two of them overlap
         * and leaves black between. Both extremes are grey, and that is how a
         * coloured lightmap ends up looking like no lightmap at all.
         */
        int32_t lowest = 0, highest = 0;
        uint32_t counted = 0;
        for (uint32_t i = 0; i < MapGenEntities_Count(entities); i++) {
            const mapgen_placement_t *ent = MapGenEntities_At(entities, i);
            if (strcmp(ent->classname, "light"))
                continue;
            if (!counted || ent->light < lowest)
                lowest = ent->light;
            if (!counted || ent->light > highest)
                highest = ent->light;
            counted++;
        }
        char spread[96];
        snprintf(spread, sizeof(spread), "%u lights, %d to %d",
                 counted, lowest, highest);
        check("and they are not every one of them the same intensity",
              counted < 2 || highest > lowest, spread);
        (void)corridor_lights;
    }

    /* --- the spread is by room, not by luck -------------------------------- */
    {
        uint32_t rooms_with_spawns = 0;
        for (uint32_t room = 0; room < MapGenLayout_NumRooms(layout); room++) {
            for (uint32_t i = 0; i < MapGenEntities_Count(entities); i++) {
                const mapgen_placement_t *ent = MapGenEntities_At(entities, i);
                if (ent->room == room
                    && !strcmp(ent->classname, "info_player_deathmatch")) {
                    rooms_with_spawns++;
                    break;
                }
            }
        }
        check("the spawns are spread over more than one room",
              rooms_with_spawns > 1
              || MapGenLayout_NumRooms(layout) == 1,
              "two spawns in one room is one room's worth of spread");
    }

    /* --- determinism -------------------------------------------------------- */
    {
        const uint64_t digest = MapGenEntities_CanonicalDigest(entities);
        mapgen_entities_t *again = NULL;
        MapGenEntities_Build(layout, topology, MODEL, recipe, attempt, NULL,
                             &again);
        check("the same layout and attempt place the same entities",
              again && MapGenEntities_CanonicalDigest(again) == digest, "");
        MapGenEntities_Free(again);
    }

    /* --- single player ------------------------------------------------------ */
    {
        mapgen_recipe_t *sp = make_recipe(0x5150ull, MAPGEN_GOAL_SINGLE_PLAYER,
                                          1, 1, NULL, 0);
        mapgen_topology_t *sp_topology = NULL;
        mapgen_layout_t *sp_layout = NULL;
        uint32_t sp_attempt = 0;
        if (sp && stage(sp, &sp_topology, &sp_layout, &sp_attempt)) {
            mapgen_entities_t *sp_entities = NULL;
            MapGenEntities_Build(sp_layout, sp_topology, MODEL, sp, sp_attempt,
                                 NULL, &sp_entities);
            check("a single-player map gets exactly one start",
                  sp_entities
                  && MapGenEntities_CountOf(sp_entities, "info_player_start") == 1,
                  "");
            check("and no deathmatch spawns at all",
                  sp_entities
                  && MapGenEntities_CountOf(sp_entities,
                                            "info_player_deathmatch") == 0, "");
            MapGenEntities_Free(sp_entities);
        } else {
            check("a single-player map could be staged", false, "");
        }
        MapGenLayout_Free(sp_layout);
        MapGenTopology_Free(sp_topology);
        MapGenRecipe_Free(sp);
    }

    /* --- a count the map cannot hold is refused, by name ------------------- */
    {
        static const item_request_t TOO_MANY[] = { { "item_health", 4000 } };
        mapgen_recipe_t *greedy = make_recipe(0xBEEFull, MAPGEN_GOAL_FFA, 4, 0,
                                              TOO_MANY, 1);
        mapgen_topology_t *g_topology = NULL;
        mapgen_layout_t *g_layout = NULL;
        uint32_t g_attempt = 0;
        if (greedy && stage(greedy, &g_topology, &g_layout, &g_attempt)) {
            const char *named = NULL;
            mapgen_entities_t *nope = (mapgen_entities_t *)1;
            const mapgen_entities_result_t r =
                MapGenEntities_Build(g_layout, g_topology, MODEL, greedy,
                                     g_attempt, &named, &nope);
            check("a count the map cannot hold is refused",
                  r == MAPGEN_ENTITIES_ERR_NO_SAFE_PLACE
                  || r == MAPGEN_ENTITIES_ERR_TOO_MANY,
                  MapGenEntities_ResultName(r));
            check("with the control named",
                  named && !strcmp(named, "item_health"),
                  "contract 14 wants the exact conflict");
            check("and nothing handed back",
                  nope == NULL,
                  "never a map with four thousand asked for and nine placed");
            MapGenEntities_Free(nope);
        } else {
            check("a crowded map could be staged", false, "");
        }
        MapGenLayout_Free(g_layout);
        MapGenTopology_Free(g_topology);
        MapGenRecipe_Free(greedy);
    }

    /* --- refusals ----------------------------------------------------------- */
    {
        mapgen_entities_t *nope = (mapgen_entities_t *)1;
        check("a missing layout is refused rather than dereferenced",
              MapGenEntities_Build(NULL, topology, MODEL, recipe, 0, NULL, &nope)
              == MAPGEN_ENTITIES_ERR_ARGS && nope == NULL, "");
        check("and a missing recipe",
              MapGenEntities_Build(layout, topology, MODEL, NULL, 0, NULL, &nope)
              == MAPGEN_ENTITIES_ERR_ARGS, "");
    }

    MapGenEntities_Free(entities);
    MapGenLayout_Free(layout);
    MapGenTopology_Free(topology);
    MapGenRecipe_Free(recipe);
    MapGenMix_Free(MODEL);
    MapGenSnapshot_Free(snap);
    free(image);

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}
