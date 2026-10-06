/*
 * The fidelity-zero chain, in one place.
 *
 * Lifted out of tools/mapgen_generate.c, which had been the only caller since
 * M4 and therefore the only copy of what a generated deathmatch map is
 * supposed to contain. The product path needed the same chain and the same
 * policy, and two copies of a loadout table would have drifted the week after
 * they were written.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_architecture.h"
#include "common/mapgen_blueprint.h"
#include "common/mapgen_brush.h"
#include "common/mapgen_entities.h"
#include "common/mapgen_layout.h"
#include "common/mapgen_mapfile.h"
#include "common/mapgen_synthesis.h"

const char *MapGenSynthesis_ResultName(mapgen_synthesis_result_t r)
{
    switch (r) {
    case MAPGEN_SYNTHESIS_OK:               return "OK";
    case MAPGEN_SYNTHESIS_ERR_ARGS:         return "ERR_ARGS";
    case MAPGEN_SYNTHESIS_ERR_MEMORY:       return "ERR_MEMORY";
    case MAPGEN_SYNTHESIS_ERR_NOT_ZERO:     return "ERR_NOT_ZERO";
    case MAPGEN_SYNTHESIS_ERR_RECIPE:       return "ERR_RECIPE";
    case MAPGEN_SYNTHESIS_ERR_TOPOLOGY:     return "ERR_TOPOLOGY";
    case MAPGEN_SYNTHESIS_ERR_LAYOUT:       return "ERR_LAYOUT";
    case MAPGEN_SYNTHESIS_ERR_BRUSHWORK:    return "ERR_BRUSHWORK";
    case MAPGEN_SYNTHESIS_ERR_ENTITIES:     return "ERR_ENTITIES";
    case MAPGEN_SYNTHESIS_ERR_WRITE:        return "ERR_WRITE";
    case MAPGEN_SYNTHESIS_ERR_NO_CANDIDATE: return "ERR_NO_CANDIDATE";
    }
    return "ERR_UNKNOWN";
}

/* A deathmatch loadout, so there is something to pick up. */
static const struct { const char *control; int32_t count; } LOADOUT[] = {
    { "weapon_shotgun", 2 },        { "weapon_supershotgun", 1 },
    { "weapon_machinegun", 1 },     { "weapon_chaingun", 1 },
    { "weapon_rocketlauncher", 1 }, { "weapon_railgun", 1 },
    { "item_armor_combat", 1 },     { "item_armor_shard", 6 },
    { "item_health", 6 },           { "item_health_large", 2 },
    { "ammo_shells", 4 },           { "ammo_bullets", 4 },
    { "ammo_rockets", 3 },          { "ammo_slugs", 3 },
    { "item_quad", 1 },
};

/*
 * The three liquid rows of contract 14. Each is Balanced when the corpus
 * actually learned a material in that role and None when it did not, so a
 * selection without lava produces a map without lava rather than a preflight
 * conflict nobody asked for.
 */
static const struct { const char *control; uint32_t role; } LIQUIDS[] = {
    { "arch_water", MAPGEN_ROLE_WATER },
    { "arch_lava",  MAPGEN_ROLE_LAVA  },
    { "arch_slime", MAPGEN_ROLE_SLIME },
};

mapgen_synthesis_result_t
MapGenSynthesis_Recipe(const mapgen_mix_t *mix, uint64_t seed, int32_t scale,
                       mapgen_goal_t goal, int32_t fidelity, const char *slug,
                       mapgen_recipe_t **out)
{
    if (!mix || !slug || !out)
        return MAPGEN_SYNTHESIS_ERR_ARGS;
    *out = NULL;
    if (fidelity != 0)
        return MAPGEN_SYNTHESIS_ERR_NOT_ZERO;

    mapgen_recipe_builder_t *rb = MapGenRecipe_BuilderCreate();
    if (!rb)
        return MAPGEN_SYNTHESIS_ERR_MEMORY;

    uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
    memset(uuid, 0x77, sizeof(uuid));
    MapGenRecipe_SetIdentity(rb, uuid, seed);

    uint32_t players_min = 2, players_max = 8;
    if (goal == MAPGEN_GOAL_SINGLE_PLAYER)
        players_min = players_max = 1;
    else if (goal == MAPGEN_GOAL_DUEL)
        players_min = players_max = 2;
    else if (goal == MAPGEN_GOAL_TDM)
        players_min = 4;
    if (MapGenRecipe_SetRequest(rb, MAPGEN_GEN_AUTO, goal, players_min,
                                players_max, 64, 0) != MAPGEN_RECIPE_OK) {
        MapGenRecipe_BuilderFree(rb);
        return MAPGEN_SYNTHESIS_ERR_RECIPE;
    }
    MapGenRecipe_SetOutput(rb, "Generated", slug);

    mapgen_recipe_snapshot_t rs;
    memset(&rs, 0, sizeof(rs));
    memset(rs.revision_uuid, 0x11, sizeof(rs.revision_uuid));
    rs.weight = 50;
    MapGenRecipe_AddSnapshot(rb, &rs);
    MapGenRecipe_AddControl(rb, "map_scale", scale, scale);
    MapGenRecipe_AddControl(rb, "architecture_fidelity", 0, 0);
    /*
     * An arena, not a warren.
     *
     * MEASURED on what this profile used to build, and handed to the PO on
     * 2026-09-07: thirty-eight rooms over 3,344 by 4,544 units - twice
     * q2dm1's footprint - with thirty-nine sky sides of 4,632 and eight
     * distinct floor levels. He called it a corridor map and asked for
     * q2dm1's shape: open, roofless over much of it, four levels above the
     * water and one below.
     *
     * Balanced gave each connection a 450-in-1000 chance of being an opening
     * rather than a tube, and the sky share came from whatever the corpus
     * happened to average. Both are now design rather than accident: most
     * connections are openings, most of the map is outdoors, and the height
     * bands are held to two so that the levels a player counts stay near
     * q2dm1's five.
     */
    MapGenRecipe_AddControl(rb, "arch_verticality", 2, 2);
    MapGenRecipe_AddControl(rb, "arch_corridors_vs_arenas", 2, 2);
    MapGenRecipe_AddControl(rb, "arch_open_sky", 4, 4);
    MapGenRecipe_AddControl(rb, "arch_material_family", 1, 1);

    for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
        const char *control = MapGenTopology_RouteControl((mapgen_route_kind_t)k);
        if (!control)
            continue;
        const uint32_t role = MapGenTopology_RouteRole((mapgen_route_kind_t)k);
        int32_t level = (!role || MapGenMix_RoleIsLearned(mix, role)) ? 2 : 0;
        /*
         * PO rule, 2026-08-31: anything that moves a player against their
         * input is forbidden by default and only allowed when the option says
         * so. A push that fires you into a ceiling is not a route, it is a
         * place you cannot get past and die in.
         */
        if (level && MapGenTopology_RouteMovesThePlayer((mapgen_route_kind_t)k))
            level = 0;
        MapGenRecipe_AddControl(rb, control, level, level);
    }

    for (size_t i = 0; i < sizeof(LIQUIDS) / sizeof(LIQUIDS[0]); i++) {
        const int32_t level =
            MapGenMix_MaterialRoleIsLearned(mix, LIQUIDS[i].role) ? 2 : 0;
        MapGenRecipe_AddControl(rb, LIQUIDS[i].control, level, level);
    }
    for (size_t i = 0; i < sizeof(LOADOUT) / sizeof(LOADOUT[0]); i++)
        MapGenRecipe_AddControl(rb, LOADOUT[i].control, LOADOUT[i].count,
                                LOADOUT[i].count);

    uint8_t *bytes = NULL;
    size_t size = 0;
    const mapgen_recipe_result_t rr = MapGenRecipe_Finish(rb, &bytes, &size);
    MapGenRecipe_BuilderFree(rb);
    if (rr != MAPGEN_RECIPE_OK) {
        free(bytes);
        return MAPGEN_SYNTHESIS_ERR_RECIPE;
    }

    mapgen_recipe_t *recipe = NULL;
    const mapgen_recipe_result_t orc = MapGenRecipe_Open(bytes, size, &recipe);
    free(bytes);
    if (orc != MAPGEN_RECIPE_OK)
        return MAPGEN_SYNTHESIS_ERR_RECIPE;

    *out = recipe;
    return MAPGEN_SYNTHESIS_OK;
}

static void refused(mapgen_synthesis_report_t *report, const char *what,
                    const char *why)
{
    if (report)
        snprintf(report->refusal, sizeof(report->refusal), "%s: %s", what,
                 why ? why : "refused");
}

mapgen_synthesis_result_t
MapGenSynthesis_Write(const mapgen_mix_t *mix, const mapgen_recipe_t *recipe,
                      mapgen_goal_t goal, uint32_t first_attempt,
                      const char *out_map_path,
                      mapgen_synthesis_report_t *report)
{
    if (!mix || !recipe || !out_map_path)
        return MAPGEN_SYNTHESIS_ERR_ARGS;
    if (report)
        memset(report, 0, sizeof(*report));

    const uint32_t budget = MapGenRecipe_AttemptLimit(recipe);
    for (uint32_t attempt = first_attempt; attempt < budget; attempt++) {
        mapgen_topology_t *topology = NULL;
        const char *conflict = NULL;
        if (MapGenTopology_Build(mix, recipe, attempt, &conflict, &topology)
            != MAPGEN_TOPOLOGY_OK) {
            refused(report, "topology", conflict);
            return MAPGEN_SYNTHESIS_ERR_TOPOLOGY;
        }

        /*
         * The plan.
         *
         * At fidelity zero there is no donor architecture to lower, so the
         * grid the topology asked for is what gets built. A corpus that DOES
         * hold an architecture donor is not a reason to use it here: this path
         * is the one that invents, and the fidelity that borrows is the
         * transaction's.
         */
        mapgen_layout_t *layout = NULL;
        if (MapGenLayout_Build(topology, mix, recipe, attempt, &layout)
            != MAPGEN_LAYOUT_OK) {
            refused(report, "layout", "no embedding");
            MapGenTopology_Free(topology);
            continue;
        }

        mapgen_brushwork_t *work = NULL;
        const mapgen_brush_result_t brc =
            MapGenBrush_Build(layout, mix, recipe, attempt, &work);
        if (brc != MAPGEN_BRUSH_OK) {
            /* Named, not swallowed: "no candidate inside N attempts" with no
               reason is a diagnosis nobody can act on. */
            refused(report, "brushwork", MapGenBrush_ResultName(brc));
            MapGenLayout_Free(layout);
            MapGenTopology_Free(topology);
            continue;
        }

        mapgen_entities_t *entities = NULL;
        if (MapGenEntities_Build(layout, topology, mix, recipe, attempt,
                                 &conflict, &entities) != MAPGEN_ENTITIES_OK) {
            refused(report, "entities", conflict);
            MapGenBrush_Free(work);
            MapGenLayout_Free(layout);
            MapGenTopology_Free(topology);
            continue;
        }

        char *text = NULL;
        size_t size = 0;
        if (MapGenMapFile_Write(work, entities, mix, recipe, &text, &size)
            != MAPGEN_MAPFILE_OK) {
            refused(report, "mapfile", "could not be written");
            MapGenEntities_Free(entities);
            MapGenBrush_Free(work);
            MapGenLayout_Free(layout);
            MapGenTopology_Free(topology);
            return MAPGEN_SYNTHESIS_ERR_WRITE;
        }

        FILE *f = fopen(out_map_path, "wb");
        const bool wrote = f && fwrite(text, 1, size, f) == size;
        if (f)
            fclose(f);

        if (report && wrote) {
            report->attempt = attempt;
            report->rooms = MapGenLayout_NumRooms(layout);
            report->passages = MapGenLayout_NumPassages(layout);
            report->junctions = MapGenLayout_NumJunctions(layout);
            report->pools = MapGenLayout_NumPools(layout);
            report->fixtures = MapGenBrush_NumFixtures(work);
            report->brushes = MapGenBrush_Count(work);
            report->entities = MapGenEntities_Count(entities);
            report->spawns = MapGenEntities_CountOf(entities,
                goal == MAPGEN_GOAL_SINGLE_PLAYER ? "info_player_start"
                                                  : "info_player_deathmatch");
            report->map_bytes = size;
        }

        free(text);
        MapGenEntities_Free(entities);
        MapGenBrush_Free(work);
        MapGenLayout_Free(layout);
        MapGenTopology_Free(topology);

        if (!wrote) {
            refused(report, "output", out_map_path);
            return MAPGEN_SYNTHESIS_ERR_WRITE;
        }
        return MAPGEN_SYNTHESIS_OK;
    }

    if (report && !report->refusal[0])
        refused(report, "attempts", "none produced a candidate");
    return MAPGEN_SYNTHESIS_ERR_NO_CANDIDATE;
}
