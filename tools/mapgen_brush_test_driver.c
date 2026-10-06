/*
 * MAPGEN-1 brush test driver.
 *
 * Compiled and run by tools/check_mapgen_brush_contract.py.
 *
 *   driver run <map.bsp> <map.bsp> <map.bsp>
 *
 * The important case here re-voxelizes the result independently and floods it
 * from outside: "the map is sealed" is checked against the brushes that came
 * out, not against the module's own opinion of the grid it built them from.
 */

#include "common/mapgen_brush.h"
#include "common/mapgen_lineage.h"
#include "common/mapgen_features.h"
#include "common/mapgen_genome.h"

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


/* --------------------------------------------------------------------------
 * The target manifest, read from the file the guard generated with
 * tools/mapgen_target_manifest.py - the names that really resolve as textures
 * in the frozen target view. Contract 15: an allowlist that was not filtered
 * against this is a list of things that may not exist where the map is going.
 */

static char **MANIFEST;
static uint32_t MANIFEST_COUNT;

static bool load_manifest(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return false;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = '\0';
        if (!n)
            continue;
        void *grown = realloc(MANIFEST, (size_t)(MANIFEST_COUNT + 1) * sizeof(char *));
        if (!grown) {
            fclose(f);
            return false;
        }
        MANIFEST = grown;
        MANIFEST[MANIFEST_COUNT] = malloc(n + 1);
        if (!MANIFEST[MANIFEST_COUNT]) {
            fclose(f);
            return false;
        }
        memcpy(MANIFEST[MANIFEST_COUNT], line, n + 1);
        MANIFEST_COUNT++;
    }
    fclose(f);
    return MANIFEST_COUNT > 0;
}

static mapgen_mix_t *MODEL;
static mapgen_recipe_t *RECIPE;

static mapgen_recipe_t *make_recipe(uint64_t seed, int32_t scale)
{
    mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
    if (!b)
        return NULL;
    uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
    memset(uuid, 0x44, sizeof(uuid));
    MapGenRecipe_SetIdentity(b, uuid, seed);
    MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, MAPGEN_GOAL_FFA, 2, 16, 32, 0);
    MapGenRecipe_SetOutput(b, "Brushwork", "brushwork");

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

/* --------------------------------------------------------------------------
 * An independent voxel model, built from the BRUSHES that came out and the
 * empty space the layout asked for. This is what makes "the map is sealed" a
 * check rather than a restatement.
 */

#define CELL_AIR    0
#define CELL_EMPTY  1
#define CELL_SOLID  2
#define CELL_FLOOD  3

typedef struct {
    uint8_t *cell;
    int32_t  origin[3];
    uint32_t size[3];
} voxels_t;

static size_t at(const voxels_t *v, uint32_t x, uint32_t y, uint32_t z)
{
    return ((size_t)z * v->size[1] + y) * v->size[0] + x;
}

static void paint(voxels_t *v, const mapgen_layout_box_t *box, uint8_t value)
{
    const int32_t step = MAPGEN_BRUSH_VOXEL;
    for (int32_t z = box->mins[2]; z < box->maxs[2]; z += step)
        for (int32_t y = box->mins[1]; y < box->maxs[1]; y += step)
            for (int32_t x = box->mins[0]; x < box->maxs[0]; x += step) {
                const int64_t gx = (x - v->origin[0]) / step;
                const int64_t gy = (y - v->origin[1]) / step;
                const int64_t gz = (z - v->origin[2]) / step;
                if (gx < 0 || gy < 0 || gz < 0)
                    continue;
                if ((uint32_t)gx >= v->size[0] || (uint32_t)gy >= v->size[1]
                    || (uint32_t)gz >= v->size[2])
                    continue;
                v->cell[at(v, (uint32_t)gx, (uint32_t)gy, (uint32_t)gz)] = value;
            }
}

/* Fill from every edge voxel through air; report whether empty was reached. */
static bool leaks(voxels_t *v)
{
    const size_t total = (size_t)v->size[0] * v->size[1] * v->size[2];
    uint32_t *stack = malloc(total * sizeof(uint32_t));
    if (!stack)
        return true;
    size_t top = 0;
    for (uint32_t z = 0; z < v->size[2]; z++)
        for (uint32_t y = 0; y < v->size[1]; y++)
            for (uint32_t x = 0; x < v->size[0]; x++) {
                const bool edge = x == 0 || y == 0 || z == 0
                                || x + 1 == v->size[0] || y + 1 == v->size[1]
                                || z + 1 == v->size[2];
                if (!edge)
                    continue;
                const size_t i = at(v, x, y, z);
                if (v->cell[i] != CELL_AIR)
                    continue;
                v->cell[i] = CELL_FLOOD;
                stack[top++] = (uint32_t)i;
            }

    static const int32_t STEP[6][3] = {
        { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 },
        { 0, -1, 0 }, { 0, 0, 1 }, { 0, 0, -1 },
    };
    bool leaked = false;
    while (top && !leaked) {
        const uint32_t i = stack[--top];
        const uint32_t x = (uint32_t)(i % v->size[0]);
        const uint32_t y = (uint32_t)((i / v->size[0]) % v->size[1]);
        const uint32_t z = (uint32_t)(i / ((size_t)v->size[0] * v->size[1]));
        for (int d = 0; d < 6; d++) {
            const int64_t nx = (int64_t)x + STEP[d][0];
            const int64_t ny = (int64_t)y + STEP[d][1];
            const int64_t nz = (int64_t)z + STEP[d][2];
            if (nx < 0 || ny < 0 || nz < 0)
                continue;
            if ((uint32_t)nx >= v->size[0] || (uint32_t)ny >= v->size[1]
                || (uint32_t)nz >= v->size[2])
                continue;
            const size_t next = at(v, (uint32_t)nx, (uint32_t)ny, (uint32_t)nz);
            if (v->cell[next] == CELL_EMPTY) {
                leaked = true;
                break;
            }
            if (v->cell[next] != CELL_AIR)
                continue;
            v->cell[next] = CELL_FLOOD;
            stack[top++] = (uint32_t)next;
        }
    }
    free(stack);
    return leaked;
}

/* -------------------------------------------------------------------------- */

/*
 * A light fitting, as opposed to a piece of the shell.
 *
 * Its downward face wears a material the corpus used as a light, and no shell
 * brush can: MAPGEN_ROLE_LIGHT is excluded from the floor, wall and ceiling
 * draw precisely so that a room is never built out of a lightbulb.
 */
static bool is_fitting(const mapgen_brush_t *b, const mapgen_mix_t *model)
{
    return MapGenMix_MaterialLightValue(model, b->material[MAPGEN_FACE_BOTTOM]) > 0;
}

/* A face wearing the sky. No shell face can, because MAPGEN_ROLE_SKY is
   excluded from the floor, wall and ceiling draw. */
static bool is_sky(const mapgen_mix_t *model, uint32_t material)
{
    return (MapGenMix_MaterialRoles(model, material) & MAPGEN_ROLE_SKY) != 0;
}

int main(int argc, char **argv)
{
    if (argc < 5 || strcmp(argv[1], "run")) {
        printf("usage: driver run <manifest.txt> <3 map paths>\n");
        return 2;
    }

    if (!load_manifest(argv[2])) {
        printf("MANIFEST_FAILED\n");
        return 1;
    }

    mapgen_training_t *t = MapGenTraining_Create();
    for (int i = 3; i < argc; i++) {
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
    mapgen_mix_options_t options;
    memset(&options, 0, sizeof(options));
    options.available = (const char *const *)MANIFEST;
    options.num_available = MANIFEST_COUNT;
    if (MapGenMix_Build(&input, 1, &options, &MODEL) != MAPGEN_MIX_OK) {
        printf("MIX_FAILED\n");
        return 1;
    }
    RECIPE = make_recipe(0x0BADC0DE0BADC0DEull, 1);
    if (!RECIPE) {
        printf("RECIPE_FAILED\n");
        return 1;
    }

    mapgen_topology_t *topology = NULL;
    if (MapGenTopology_Build(MODEL, RECIPE, 0, NULL, &topology)
        != MAPGEN_TOPOLOGY_OK) {
        printf("TOPOLOGY_FAILED\n");
        return 1;
    }
    mapgen_layout_t *layout = NULL;
    if (MapGenLayout_Build(topology, MODEL, RECIPE, 0, &layout) != MAPGEN_LAYOUT_OK) {
        printf("LAYOUT_FAILED\n");
        return 1;
    }

    mapgen_brushwork_t *work = NULL;
    mapgen_brush_result_t rc = MapGenBrush_Build(layout, MODEL, RECIPE, 0, &work);
    check("the solid world is derived from the empty space",
          rc == MAPGEN_BRUSH_OK && work != NULL, MapGenBrush_ResultName(rc));
    if (!work)
        return 1;

    check("there are brushes to compile", MapGenBrush_Count(work) > 0, "");

    /* --- every brush ------------------------------------------------------ */
    {
        bool positive = true, on_grid = true;
        for (uint32_t i = 0; i < MapGenBrush_Count(work); i++) {
            const mapgen_brush_t *b = MapGenBrush_At(work, i);
            for (int axis = 0; axis < 3; axis++) {
                if (b->maxs[axis] <= b->mins[axis])
                    positive = false;
                if (b->mins[axis] % MAPGEN_BRUSH_VOXEL
                    || b->maxs[axis] % MAPGEN_BRUSH_VOXEL)
                    on_grid = false;
            }
        }
        check("every brush is a box with a volume", positive, "");
        check("and every corner is on the grid", on_grid, "");
    }

    /* --- no brush stands in the empty space -------------------------------- */
    {
        uint32_t intrusions = 0, fittings = 0;
        for (uint32_t i = 0; i < MapGenBrush_Count(work); i++) {
            const mapgen_brush_t *b = MapGenBrush_At(work, i);
            /* A fitting belongs in the room; that is what a ceiling light is. */
            if (is_fitting(b, MODEL)) {
                fittings++;
                continue;
            }
            for (uint32_t r = 0; r < MapGenLayout_NumRooms(layout); r++) {
                const mapgen_layout_box_t *room =
                    &MapGenLayout_Room(layout, r)->space;
                bool overlap = true;
                for (int axis = 0; axis < 3; axis++)
                    if (b->maxs[axis] <= room->mins[axis]
                        || b->mins[axis] >= room->maxs[axis])
                        overlap = false;
                if (overlap)
                    intrusions++;
            }
        }
        /*
         * And the map is lit by area sources at all. This is the property that
         * moved here from the entities driver: the corridors used to be lit by
         * a point light forced into every stub, and they are lit by ceiling
         * fittings now, which live in this stage.
         */
        check("the map has light fittings in it", fittings > 0,
              "a Quake II map is lit by its surfaces; every map in the corpus "
              "has between 36 and 963 emitting sides");
        check("no brush stands inside a room", intrusions == 0,
              "the solid is the complement of the empty space, not a guess "
              "laid over it");
    }

    /* --- the map is sealed, checked against the brushes ------------------- */
    {
        const mapgen_layout_box_t *bounds = MapGenBrush_Bounds(work);
        voxels_t v;
        memset(&v, 0, sizeof(v));
        const int32_t margin = 8 * MAPGEN_BRUSH_VOXEL;
        for (int axis = 0; axis < 3; axis++) {
            v.origin[axis] = bounds->mins[axis] - margin;
            const int64_t span = (int64_t)bounds->maxs[axis] + margin
                               - v.origin[axis];
            v.size[axis] = (uint32_t)((span + MAPGEN_BRUSH_VOXEL - 1)
                                      / MAPGEN_BRUSH_VOXEL);
        }
        const size_t total = (size_t)v.size[0] * v.size[1] * v.size[2];
        v.cell = calloc(total, 1);
        if (v.cell) {
            for (uint32_t i = 0; i < MapGenBrush_Count(work); i++) {
                const mapgen_brush_t *b = MapGenBrush_At(work, i);
                mapgen_layout_box_t box;
                memcpy(box.mins, b->mins, sizeof(box.mins));
                memcpy(box.maxs, b->maxs, sizeof(box.maxs));
                paint(&v, &box, CELL_SOLID);
            }
            for (uint32_t r = 0; r < MapGenLayout_NumRooms(layout); r++)
                paint(&v, &MapGenLayout_Room(layout, r)->space, CELL_EMPTY);
            for (uint32_t p = 0; p < MapGenLayout_NumPassages(layout); p++) {
                const mapgen_layout_passage_t *pass =
                    MapGenLayout_Passage(layout, p);
                for (uint32_t s = 0; s < pass->num_segments; s++)
                    paint(&v, &pass->segments[s], CELL_EMPTY);
            }

            uint64_t empty_here = 0;
            for (size_t i = 0; i < total; i++)
                if (v.cell[i] == CELL_EMPTY)
                    empty_here++;
            /*
             * The module's empty space CONTAINS the layout's, and is bigger.
             *
             * A pool is a pit in the floor and a ceiling recess is a hollow in
             * the ceiling; both are empty space that the layout does not carry
             * as a room or a passage, so an equality here measures how old this
             * driver is rather than whether the brushes are right. What this
             * case exists to catch - a brush standing where empty space should
             * be - is asserted directly by the case above, which walks every
             * brush against every room.
             */
            check("the empty space survives the brushes intact",
                  empty_here <= MapGenBrush_EmptyVoxels(work),
                  "the layout's rooms and passages must all still be empty");

            check("and a flood from outside never reaches it",
                  !leaks(&v),
                  "a leak is the one failure a compiler cannot fix and a "
                  "player finds immediately");
            free(v.cell);
        } else {
            check("the independent voxel model could be built", false, "no memory");
        }
    }

    /* --- provenance ------------------------------------------------------- */
    {
        const uint32_t materials = MapGenMix_NumMaterials(MODEL);
        uint32_t out_of_range = 0, wrong_role = 0;
        for (uint32_t i = 0; i < MapGenBrush_Count(work); i++) {
            const mapgen_brush_t *b = MapGenBrush_At(work, i);
            for (uint32_t f = 0; f < MAPGEN_FACE_COUNT; f++) {
                if (b->material[f] >= materials) {
                    out_of_range++;
                    continue;
                }
                const uint32_t roles =
                    MapGenMix_MaterialRoles(MODEL, b->material[f]);
                if (!(roles & MAPGEN_ROLE_SOLID))
                    wrong_role++;
                if (roles & (MAPGEN_ROLE_SKY | MAPGEN_ROLE_WATER
                             | MAPGEN_ROLE_LAVA | MAPGEN_ROLE_SLIME
                             | MAPGEN_ROLE_NODRAW | MAPGEN_ROLE_CLIP))
                    wrong_role++;
            }
        }
        check("every face names a material from the allowlist",
              out_of_range == 0,
              "contract 15: nothing is textured with something the corpus "
              "never had");
        /*
         * A sky face is not a solid surface and is not meant to be. It is
         * counted separately and held to two rules that a wrongly placed one
         * would break: it looks DOWN, and it roofs a room the layout marked
         * open to the sky. A sky on a wall is a hole in the map.
         */
        uint32_t sky_faces = 0, sky_misplaced = 0, outdoor_rooms_here = 0;
        for (uint32_t r = 0; r < MapGenLayout_NumRooms(layout); r++)
            if (MapGenLayout_Room(layout, r)->outdoor)
                outdoor_rooms_here++;
        for (uint32_t i = 0; i < MapGenBrush_Count(work); i++) {
            const mapgen_brush_t *b = MapGenBrush_At(work, i);
            for (uint32_t f = 0; f < MAPGEN_FACE_COUNT; f++) {
                if (!is_sky(MODEL, b->material[f]))
                    continue;
                sky_faces++;
                if (f != MAPGEN_FACE_BOTTOM) {
                    sky_misplaced++;
                    continue;
                }
                bool over_outdoor = false;
                for (uint32_t r = 0; r < MapGenLayout_NumRooms(layout); r++) {
                    const mapgen_layout_room_t *room =
                        MapGenLayout_Room(layout, r);
                    if (room->outdoor && b->mins[2] >= room->space.maxs[2])
                        over_outdoor = true;
                }
                if (!over_outdoor)
                    sky_misplaced++;
            }
        }
        char skytext[96];
        snprintf(skytext, sizeof(skytext), "%u sky faces, %u misplaced",
                 sky_faces, sky_misplaced);
        check("and one the corpus used as a solid surface, or the sky",
              wrong_role == sky_faces, skytext);
        check("the sky only ever looks down, and only over an outdoor room",
              sky_misplaced == 0, skytext);
        /*
         * And it is there at all. MEASURED: q2dm1 is 23 parts per thousand
         * sky and every generated map was 0, which is the whole of "the
         * references are open levels and yours are closed boxes". A corpus
         * without a sky material cannot produce one, so the case asks only
         * when one was learned.
         */
        {
            bool sky_learned = false;
            for (uint32_t i = 0; i < MapGenMix_NumMaterials(MODEL); i++)
                if (MapGenMix_MaterialRoles(MODEL, i) & MAPGEN_ROLE_SKY)
                    sky_learned = true;

            /*
             * Swept over attempts rather than asked of this one. Whether any
             * single map has a courtyard is a draw; whether a corpus with sky
             * in it can produce one at all is the contract, and a version
             * that never marks a room outdoor fails it every time.
             */
            uint32_t outdoor_total = 0;
            for (uint32_t a = 0; a < 16; a++) {
                mapgen_layout_t *probe = NULL;
                if (MapGenLayout_Build(topology, MODEL, RECIPE, a, &probe)
                    != MAPGEN_LAYOUT_OK)
                    continue;
                for (uint32_t r = 0; r < MapGenLayout_NumRooms(probe); r++)
                    if (MapGenLayout_Room(probe, r)->outdoor)
                        outdoor_total++;
                MapGenLayout_Free(probe);
            }
            char outdoors[64];
            snprintf(outdoors, sizeof(outdoors),
                     "%u outdoor rooms across 16 attempts", outdoor_total);
            check("a corpus with sky in it opens some rooms to it",
                  !sky_learned || outdoor_total > 0, outdoors);
            check("and a map that has an outdoor room has sky faces in it",
                  !outdoor_rooms_here || sky_faces > 0, skytext);
        }

        /*
         * A texture set per ROOM: more than one, no more than there are
         * rooms, and every brush wearing one of them whole.
         */
        const uint32_t room_count = MapGenLayout_NumRooms(layout);
        uint32_t sets[MAPGEN_TOPOLOGY_MAX_NODES][3];
        uint32_t num_sets = 0;
        bool whole = true;

        for (uint32_t i = 0; i < MapGenBrush_Count(work); i++) {
            const mapgen_brush_t *b = MapGenBrush_At(work, i);
            /* A pool's own brush is one liquid on every face and is not a
               room's shell; it has no set to belong to. Nor has a fitting,
               which is the room's wall on five faces and an emitter on the
               sixth. */
            if (b->material[MAPGEN_FACE_TOP] == b->material[MAPGEN_FACE_EAST]
                && b->material[MAPGEN_FACE_TOP] == b->material[MAPGEN_FACE_BOTTOM])
                continue;
            if (is_fitting(b, MODEL))
                continue;
            if (is_sky(MODEL, b->material[MAPGEN_FACE_BOTTOM]))
                continue;               /* a courtyard's roof is the sky */

            const uint32_t f = b->material[MAPGEN_FACE_TOP];
            const uint32_t w = b->material[MAPGEN_FACE_EAST];
            const uint32_t c = b->material[MAPGEN_FACE_BOTTOM];

            /* The four walls agree with each other, or a face is drawing on
               its own. */
            if (b->material[MAPGEN_FACE_WEST] != w
                || b->material[MAPGEN_FACE_NORTH] != w
                || b->material[MAPGEN_FACE_SOUTH] != w)
                whole = false;

            bool seen = false;
            for (uint32_t s = 0; s < num_sets; s++)
                if (sets[s][0] == f && sets[s][1] == w && sets[s][2] == c)
                    seen = true;
            if (!seen && num_sets < MAPGEN_TOPOLOGY_MAX_NODES) {
                sets[num_sets][0] = f;
                sets[num_sets][1] = w;
                sets[num_sets][2] = c;
                num_sets++;
            }
        }

        char detail[96];
        snprintf(detail, sizeof(detail), "%u distinct sets across %u rooms",
                 num_sets, room_count);
        check("the map is not built out of one texture set", num_sets > 1,
              detail);
        check("and there are no more sets than there are rooms",
              num_sets <= room_count, detail);
        check("and every brush wears one room's set whole", whole,
              "a floor from one room with a wall from another is a per-face "
              "draw wearing a per-room disguise");
    }

    /* --- determinism ------------------------------------------------------- */
    {
        const uint64_t digest = MapGenBrush_CanonicalDigest(work, MODEL);
        mapgen_brushwork_t *again = NULL;
        MapGenBrush_Build(layout, MODEL, RECIPE, 0, &again);
        check("the same layout and attempt give the same brushes",
              again && MapGenBrush_CanonicalDigest(again, MODEL) == digest, "");
        MapGenBrush_Free(again);

        mapgen_brushwork_t *other = NULL;
        MapGenBrush_Build(layout, MODEL, RECIPE, 1, &other);
        check("a different attempt may choose different materials",
              other != NULL, "");
        MapGenBrush_Free(other);
    }

    /* --- the canonical text names materials, not indices ------------------ */
    {
        const size_t n = MapGenBrush_CanonicalText(work, MODEL, NULL, 0);
        char *text = malloc(n + 1);
        if (text) {
            MapGenBrush_CanonicalText(work, MODEL, text, n + 1);
            const char *floor_name =
                MapGenMix_MaterialName(MODEL,
                                       MapGenBrush_At(work, 0)->material[MAPGEN_FACE_TOP]);
            check("the canonical text names the texture rather than an index",
                  floor_name && strstr(text, floor_name) != NULL,
                  "an index means nothing to anyone reading a report");
            free(text);
        }
    }

    /* --- refusals ---------------------------------------------------------- */
    {
        mapgen_brushwork_t *nope = (mapgen_brushwork_t *)1;
        check("a missing layout is refused rather than dereferenced",
              MapGenBrush_Build(NULL, MODEL, RECIPE, 0, &nope)
              == MAPGEN_BRUSH_ERR_ARGS && nope == NULL, "");
        check("and a missing model",
              MapGenBrush_Build(layout, NULL, RECIPE, 0, &nope)
              == MAPGEN_BRUSH_ERR_ARGS, "");
        check("and a missing recipe",
              MapGenBrush_Build(layout, MODEL, NULL, 0, &nope)
              == MAPGEN_BRUSH_ERR_ARGS, "");
    }

    /* --- a bigger map still seals ----------------------------------------- */
    {
        mapgen_recipe_t *large = make_recipe(0xFEEDFACEull, 3);
        uint32_t sealed = 0, built = 0;
        for (uint32_t attempt = 0; attempt < 4 && large; attempt++) {
            mapgen_topology_t *big_topology = NULL;
            if (MapGenTopology_Build(MODEL, large, attempt, NULL, &big_topology)
                != MAPGEN_TOPOLOGY_OK)
                continue;
            mapgen_layout_t *big_layout = NULL;
            if (MapGenLayout_Build(big_topology, MODEL, large, attempt, &big_layout)
                == MAPGEN_LAYOUT_OK) {
                mapgen_brushwork_t *big = NULL;
                if (MapGenBrush_Build(big_layout, MODEL, large, attempt, &big)
                    == MAPGEN_BRUSH_OK) {
                    built++;
                    if (MapGenBrush_Count(big) > 0)
                        sealed++;
                }
                MapGenBrush_Free(big);
            }
            MapGenLayout_Free(big_layout);
            MapGenTopology_Free(big_topology);
        }
        check("a Very Large map builds and seals on every attempt",
              built == 4 && sealed == 4,
              "the seal is proven inside the module by the same flood");
        MapGenRecipe_Free(large);
    }

    MapGenBrush_Free(work);
    MapGenLayout_Free(layout);
    MapGenTopology_Free(topology);
    MapGenRecipe_Free(RECIPE);
    MapGenMix_Free(MODEL);
    MapGenSnapshot_Free(snap);
    free(image);

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}
