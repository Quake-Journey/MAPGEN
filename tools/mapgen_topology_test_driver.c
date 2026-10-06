/*
 * MAPGEN-1 topology test driver.
 *
 * Compiled and run by tools/check_mapgen_topology_contract.py.
 *
 *   driver run <map.bsp> <map.bsp> <map.bsp> <map.bsp>
 *
 * The graph is built from a real mixed model trained on real maps, and every
 * structural claim is checked by walking the graph here rather than by asking
 * the module whether it kept its promise.
 */

#include "common/mapgen_topology.h"
#include "common/mapgen_lineage.h"
#include "common/mapgen_features.h"
#include "common/mapgen_wiring.h"

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

static const char *basename_of(const char *path)
{
    const char *slash = strrchr(path, '/');
    const char *back = strrchr(path, '\\');
    const char *last = slash > back ? slash : back;
    return last ? last + 1 : path;
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
        ok = MapGenTraining_AddSource(t, basename_of(path), "baseq2", size, sha,
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

static mapgen_snapshot_t *make_snapshot(char **paths, int count, uint8_t tag,
                                        uint8_t **owned)
{
    mapgen_training_t *t = MapGenTraining_Create();
    if (!t)
        return NULL;
    for (int i = 0; i < count; i++) {
        if (!add_map(t, paths[i])) {
            MapGenTraining_Free(t);
            return NULL;
        }
    }
    uint8_t lineage[MAPGEN_SNAPSHOT_UUID_BYTES], revision[MAPGEN_SNAPSHOT_UUID_BYTES];
    memset(lineage, tag, sizeof(lineage));
    memset(revision, tag, sizeof(revision));

    size_t size = 0;
    const mapgen_lineage_result_t r =
        MapGenLineage_New(t, lineage, revision, 1756600000000ull,
                          MAPGEN_COMPRESSION_DEFLATE, owned, &size);
    MapGenTraining_Free(t);
    if (r != MAPGEN_LINEAGE_OK)
        return NULL;

    mapgen_snapshot_t *snap = NULL;
    if (MapGenSnapshot_Open(*owned, size, &snap) != MAPGEN_SNAPSHOT_OK)
        return NULL;
    return snap;
}

/* -------------------------------------------------------------------------- */

/*
 * A recipe built here, with every architecture control at a chosen level, so
 * a case can say exactly what it is asking for.
 */
typedef struct {
    mapgen_goal_t goal;
    uint32_t players_min, players_max;
    int32_t  scale;
    int32_t  verticality;
    int32_t  levels[MAPGEN_ROUTE_KIND_COUNT];   /* indexed by route kind */
    uint64_t seed;
} request_t;

static const mapgen_mix_t *MODEL;

/*
 * Balanced for everything this corpus actually taught, None for the rest.
 *
 * Asking for a motif the corpus never learned is a REFUSAL, and a correct one -
 * so the ordinary cases must not ask for it, or every one of them would be
 * testing the refusal instead of what it says it tests. The refusal has a case
 * of its own further down.
 */
static request_t default_request(void)
{
    request_t r;
    memset(&r, 0, sizeof(r));
    r.goal = MAPGEN_GOAL_FFA;
    r.players_min = 2;
    r.players_max = 16;
    r.scale = 1;                                /* Medium    */
    r.verticality = 2;                          /* Balanced  */
    r.seed = 0x5EED5EED5EED5EEDull;
    for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
        const uint32_t role = MapGenTopology_RouteRole((mapgen_route_kind_t)k);
        r.levels[k] = (!role || MapGenMix_RoleIsLearned(MODEL, role)) ? 2 : 0;
    }
    return r;
}

static mapgen_recipe_t *make_recipe(const request_t *req, uint8_t tag)
{
    mapgen_recipe_builder_t *b = MapGenRecipe_BuilderCreate();
    if (!b)
        return NULL;

    uint8_t uuid[MAPGEN_RECIPE_UUID_BYTES];
    memset(uuid, tag, sizeof(uuid));
    MapGenRecipe_SetIdentity(b, uuid, req->seed);
    MapGenRecipe_SetRequest(b, MAPGEN_GEN_AUTO, req->goal, req->players_min,
                            req->players_max, 32, 0);
    MapGenRecipe_SetOutput(b, "Topology", "topology");

    mapgen_recipe_snapshot_t snap;
    memset(&snap, 0, sizeof(snap));
    memset(snap.revision_uuid, 0x11, sizeof(snap.revision_uuid));
    snap.weight = 50;
    MapGenRecipe_AddSnapshot(b, &snap);

    MapGenRecipe_AddControl(b, "map_scale", req->scale, req->scale);
    MapGenRecipe_AddControl(b, "arch_verticality", req->verticality,
                            req->verticality);
    /* Jumps and drops are one row in the UI, so they share a control. Adding
       it twice would be refused by the builder; the request keeps them as
       separate levels and the first one written is the one that counts, so a
       case that means to turn the row off sets both. */
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
        MapGenRecipe_AddControl(b, control, req->levels[k], req->levels[k]);
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

/* -------------------------------------------------------------------------- */

/* Reachability over the graph, walked here rather than trusted. */
static uint32_t reachable_count(const mapgen_topology_t *t, bool directed)
{
    const uint32_t n = MapGenTopology_NumNodes(t);
    if (!n)
        return 0;
    bool *seen = calloc(n, sizeof(bool));
    uint32_t *stack = malloc((size_t)n * sizeof(uint32_t));
    if (!seen || !stack) {
        free(seen);
        free(stack);
        return 0;
    }
    uint32_t top = 0, found = 0;
    stack[top++] = 0;
    seen[0] = true;
    while (top) {
        const uint32_t at = stack[--top];
        found++;
        for (uint32_t i = 0; i < MapGenTopology_NumRoutes(t); i++) {
            const mapgen_topology_route_t *e = MapGenTopology_Route(t, i);
            uint32_t next = UINT32_MAX;
            if (e->from == at)
                next = e->to;
            else if (e->to == at && !(directed &&
                     MapGenTopology_RouteIsOneWay((mapgen_route_kind_t)e->kind)))
                next = e->from;
            if (next != UINT32_MAX && next < n && !seen[next]) {
                seen[next] = true;
                stack[top++] = next;
            }
        }
    }
    free(seen);
    free(stack);
    return found;
}

/* Strong connectivity: reachable from 0 and 0 reachable from everywhere. */
static bool strongly_connected(const mapgen_topology_t *t)
{
    const uint32_t n = MapGenTopology_NumNodes(t);
    if (reachable_count(t, true) != n)
        return false;

    /* And back: a breadth walk along reversed routes. */
    bool *seen = calloc(n, sizeof(bool));
    uint32_t *stack = malloc((size_t)n * sizeof(uint32_t));
    if (!seen || !stack) {
        free(seen);
        free(stack);
        return false;
    }
    uint32_t top = 0, found = 0;
    stack[top++] = 0;
    seen[0] = true;
    while (top) {
        const uint32_t at = stack[--top];
        found++;
        for (uint32_t i = 0; i < MapGenTopology_NumRoutes(t); i++) {
            const mapgen_topology_route_t *e = MapGenTopology_Route(t, i);
            uint32_t prev = UINT32_MAX;
            if (e->to == at)
                prev = e->from;
            else if (e->from == at &&
                     !MapGenTopology_RouteIsOneWay((mapgen_route_kind_t)e->kind))
                prev = e->to;
            if (prev != UINT32_MAX && prev < n && !seen[prev]) {
                seen[prev] = true;
                stack[top++] = prev;
            }
        }
    }
    free(seen);
    free(stack);
    return found == n;
}

static char *render(const mapgen_topology_t *t)
{
    const size_t n = MapGenTopology_CanonicalText(t, NULL, 0);
    char *text = malloc(n + 1);
    if (text)
        MapGenTopology_CanonicalText(t, text, n + 1);
    return text;
}

/* -------------------------------------------------------------------------- */

static mapgen_topology_t *build(const request_t *req, uint32_t attempt,
                                mapgen_topology_result_t *rc,
                                const char **conflict)
{
    mapgen_recipe_t *recipe = make_recipe(req, 0x22);
    if (!recipe) {
        *rc = MAPGEN_TOPOLOGY_ERR_ARGS;
        return NULL;
    }
    mapgen_topology_t *t = NULL;
    *rc = MapGenTopology_Build(MODEL, recipe, attempt, conflict, &t);
    MapGenRecipe_Free(recipe);
    return t;
}

int main(int argc, char **argv)
{
    if (argc < 6 || strcmp(argv[1], "run")) {
        printf("usage: driver run <4 map paths>\n");
        return 2;
    }

    uint8_t *bytes_a = NULL, *bytes_b = NULL;
    mapgen_snapshot_t *a = make_snapshot(&argv[2], 3, 0xA0, &bytes_a);
    mapgen_snapshot_t *b = make_snapshot(&argv[3], 3, 0xB0, &bytes_b);
    if (!a || !b) {
        printf("TRAIN_FAILED\n");
        return 1;
    }

    mapgen_mix_input_t inputs[2];
    for (int i = 0; i < 2; i++) {
        const mapgen_snapshot_t *snap = i ? b : a;
        const mapgen_snapshot_header_t *h = MapGenSnapshot_Header(snap);
        memset(&inputs[i], 0, sizeof(inputs[i]));
        inputs[i].snapshot = snap;
        memcpy(inputs[i].revision_uuid, h->revision_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);
        memcpy(inputs[i].payload_sha256, h->payload_sha256, MAPGEN_SHA256_BYTES);
        inputs[i].weight = 50;
    }
    mapgen_mix_t *model = NULL;
    if (MapGenMix_Build(inputs, 2, NULL, &model) != MAPGEN_MIX_OK || !model) {
        printf("MIX_FAILED\n");
        return 1;
    }
    MODEL = model;

    request_t req = default_request();
    mapgen_topology_result_t rc;
    const char *conflict = NULL;

    mapgen_topology_t *t = build(&req, 0, &rc, &conflict);
    check("a graph is built from a real mixed model",
          rc == MAPGEN_TOPOLOGY_OK && t != NULL,
          MapGenTopology_ResultName(rc));
    if (!t)
        return 1;

    /* --- it is a map, not a pile of nodes --------------------------------- */
    check("it has regions and routes",
          MapGenTopology_NumNodes(t) >= MAPGEN_TOPOLOGY_MIN_NODES
          && MapGenTopology_NumRoutes(t) > 0, "");
    check("every node is reachable from every other, ignoring direction",
          reachable_count(t, false) == MapGenTopology_NumNodes(t),
          "a graph a player cannot walk around is not a candidate");
    check("and reachable both ways once direction is respected",
          strongly_connected(t),
          "a route you can fall down but not climb out of is a trap");

    /*
     * Over two hundred graphs, not one.
     *
     * A single graph is far too small a sample for this: the first version of
     * this case looked at one graph, and a mutation that allowed both a
     * self-loop and a duplicate survived it simply because those particular
     * draws never collided.
     */
    {
        uint32_t self_loops = 0, duplicates = 0, graphs = 0;
        for (uint32_t attempt = 0; attempt < 200; attempt++) {
            mapgen_topology_result_t rcx;
            mapgen_topology_t *g = build(&req, attempt, &rcx, NULL);
            if (!g)
                continue;
            graphs++;
            for (uint32_t i = 0; i < MapGenTopology_NumRoutes(g); i++) {
                const mapgen_topology_route_t *e = MapGenTopology_Route(g, i);
                if (e->from == e->to)
                    self_loops++;
                for (uint32_t j = 0; j < i; j++) {
                    const mapgen_topology_route_t *f = MapGenTopology_Route(g, j);
                    if ((f->from == e->from && f->to == e->to)
                        || (f->from == e->to && f->to == e->from))
                        duplicates++;
                }
            }
            MapGenTopology_Free(g);
        }
        check("two hundred graphs were built to look at", graphs == 200, "");
        check("no node connects to itself, in any of them", self_loops == 0, "");
        check("and no pair is connected twice, in any of them",
              duplicates == 0, "");
    }

    bool in_range = true;
    for (uint32_t i = 0; i < MapGenTopology_NumRoutes(t); i++) {
        const mapgen_topology_route_t *e = MapGenTopology_Route(t, i);
        if (e->from >= MapGenTopology_NumNodes(t)
            || e->to >= MapGenTopology_NumNodes(t)
            || e->kind >= MAPGEN_ROUTE_KIND_COUNT)
            in_range = false;
    }
    check("every route names real regions and a real kind", in_range, "");

    check("there is more than one way around",
          MapGenTopology_CyclomaticNumber(t) >= 1,
          "contract 12 wants route redundancy for a multiplayer goal");

    /* --- the size came from a map that exists ----------------------------- */
    {
        const char *source = MapGenTopology_SampleSource(t);
        bool known = false;
        for (uint32_t i = 0; i < MapGenMix_NumSamples(model); i++)
            if (source && !strcmp(MapGenMix_SampleSource(model, i), source))
                known = true;
        check("the graph records which learned map it was sized from", known,
              "contract 19: measured evidence, not an invented target");

        /*
         * The COUNT does not come from that sample, and must not: `regions`
         * counts connected components of the stance graph - aerowalk has 63 -
         * and reading it as a room count is what built forty small boxes
         * where the corpus has a dozen places. The sample still decides the
         * band count and the largest area's share; the count is a control.
         */
        int64_t learned = -1;
        for (uint32_t i = 0; i < MapGenMix_NumSamples(model); i++)
            if (source && !strcmp(MapGenMix_SampleSource(model, i), source))
                learned = MapGenMix_SampleValue(model, i, MAPGEN_MIX_STAT_REGIONS);
        check("the sample it was sized from has a region count at all",
              learned >= 0, "");

        uint32_t at_scale[4] = { 0, 0, 0, 0 };
        bool stable = true, rising = true, inside = true;
        for (int32_t scale = 0; scale < 4; scale++) {
            for (uint64_t seed = 1; seed <= 6; seed++) {
                request_t r = req;
                r.seed = seed * 0x9E3779B97F4A7C15ull;
                r.scale = scale;
                mapgen_topology_result_t rc = MAPGEN_TOPOLOGY_OK;
                mapgen_topology_t *probe = build(&r, 0, &rc, NULL);
                if (!probe) {
                    stable = false;
                    break;
                }
                const uint32_t n = MapGenTopology_NumNodes(probe);
                if (!at_scale[scale])
                    at_scale[scale] = n;
                else if (at_scale[scale] != n)
                    stable = false;         /* a different sample moved it */
                /*
                 * The world is +/-4096 and a cell is 1536, so twenty-five
                 * rooms is all that fits however many regions a sample
                 * reports. This is the regression the old case allowed.
                 */
                if (n < MAPGEN_TOPOLOGY_MIN_NODES || n > 25)
                    inside = false;
                MapGenTopology_Free(probe);
            }
        }
        for (int32_t scale = 1; scale < 4; scale++)
            if (at_scale[scale] <= at_scale[scale - 1])
                rising = false;

        char detail[96];
        snprintf(detail, sizeof(detail), "%u, %u, %u, %u areas",
                 at_scale[0], at_scale[1], at_scale[2], at_scale[3]);
        check("the area count is the same for every seed at one scale",
              stable, detail);
        check("and rises with the scale", rising, detail);
        check("and stays inside what the world can hold, whatever the sample "
              "says its region count was", inside, detail);
    }

    /* --- determinism ------------------------------------------------------ */
    {
        const uint64_t digest = MapGenTopology_CanonicalDigest(t);
        mapgen_topology_result_t rc2;
        mapgen_topology_t *again = build(&req, 0, &rc2, NULL);
        check("the same request and attempt give the same graph",
              again && MapGenTopology_CanonicalDigest(again) == digest, "");
        MapGenTopology_Free(again);

        mapgen_topology_t *other = build(&req, 1, &rc2, NULL);
        check("and a different attempt gives a different one",
              other && MapGenTopology_CanonicalDigest(other) != digest,
              "attempts must explore, not repeat");
        if (other) {
            check("which is still connected",
                  reachable_count(other, false) == MapGenTopology_NumNodes(other)
                  && strongly_connected(other), "");
        }
        MapGenTopology_Free(other);

        /* Attempt 7 is the same graph whether or not 0..6 were built. */
        mapgen_topology_t *seventh = build(&req, 7, &rc2, NULL);
        mapgen_topology_t *seventh_again = build(&req, 7, &rc2, NULL);
        check("attempt seven is the same graph however many ran beside it",
              seventh && seventh_again
              && MapGenTopology_CanonicalDigest(seventh)
                 == MapGenTopology_CanonicalDigest(seventh_again), "");
        MapGenTopology_Free(seventh);
        MapGenTopology_Free(seventh_again);

        request_t reseeded = req;
        reseeded.seed = req.seed ^ 0xFFFFFFFFull;
        mapgen_topology_t *elsewhere = build(&reseeded, 0, &rc2, NULL);
        check("a different seed gives a different graph",
              elsewhere && MapGenTopology_CanonicalDigest(elsewhere) != digest, "");
        MapGenTopology_Free(elsewhere);
    }

    /* --- None is absolute, for every kind in turn ------------------------- */
    {
        uint32_t violations = 0;
        const char *first = NULL;
        for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
            const char *control = MapGenTopology_RouteControl((mapgen_route_kind_t)k);
            if (!control)
                continue;

            request_t none = default_request();
            /* A control the corpus could not satisfy is already None here, and
               turning it off proves nothing. */
            bool already_off = true;
            for (uint32_t j = 0; j < MAPGEN_ROUTE_KIND_COUNT; j++) {
                const char *other = MapGenTopology_RouteControl((mapgen_route_kind_t)j);
                if (other && !strcmp(other, control) && none.levels[j] > 0)
                    already_off = false;
            }
            if (already_off)
                continue;

            /* Every kind sharing this control goes to None together, which is
               what the UI would do - they are one row. */
            for (uint32_t j = 0; j < MAPGEN_ROUTE_KIND_COUNT; j++) {
                const char *other = MapGenTopology_RouteControl((mapgen_route_kind_t)j);
                if (other && !strcmp(other, control))
                    none.levels[j] = 0;
            }

            mapgen_topology_result_t rc3;
            mapgen_topology_t *g = build(&none, 0, &rc3, NULL);
            if (!g) {
                violations++;
                if (!first)
                    first = control;
                continue;
            }
            for (uint32_t j = 0; j < MAPGEN_ROUTE_KIND_COUNT; j++) {
                const char *other = MapGenTopology_RouteControl((mapgen_route_kind_t)j);
                if (other && !strcmp(other, control)
                    && MapGenTopology_NumRoutesOfKind(g, (mapgen_route_kind_t)j)) {
                    violations++;
                    if (!first)
                        first = MapGenTopology_RouteName((mapgen_route_kind_t)j);
                }
            }
            /* And it must still be a map. */
            if (reachable_count(g, false) != MapGenTopology_NumNodes(g)
                || !strongly_connected(g)) {
                violations++;
                if (!first)
                    first = control;
            }
            MapGenTopology_Free(g);
        }
        check("None emits zero routes of that kind, for every control in turn",
              violations == 0, first ? first : "");
    }

    /* --- everything off at once still produces a map ---------------------- */
    {
        request_t bare = default_request();
        for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++)
            bare.levels[k] = 0;
        bare.verticality = 0;

        mapgen_topology_result_t rc4;
        mapgen_topology_t *g = build(&bare, 0, &rc4, NULL);
        check("with every architecture control at None a map is still built",
              rc4 == MAPGEN_TOPOLOGY_OK && g != NULL,
              MapGenTopology_ResultName(rc4));
        if (g) {
            check("and it is connected, out of plain corridors",
                  reachable_count(g, false) == MapGenTopology_NumNodes(g)
                  && MapGenTopology_NumRoutesOfKind(g, MAPGEN_ROUTE_WALK)
                     == MapGenTopology_NumRoutes(g), "");
            check("on one level, because verticality was None too",
                  MapGenTopology_Node(g, MapGenTopology_NumNodes(g) - 1)->band == 0,
                  "");
            MapGenTopology_Free(g);
        }
    }

    /* --- a motif the corpus never learned is refused by name -------------- */
    {
        /* Whichever gated role this corpus lacks; if it lacks none, the case
           says so rather than pretending to have tested it. */
        uint32_t missing = 0;
        uint32_t refused = 0, named_right = 0;
        for (uint32_t k = 0; k < MAPGEN_ROUTE_KIND_COUNT; k++) {
            const uint32_t role = MapGenTopology_RouteRole((mapgen_route_kind_t)k);
            if (!role || MapGenMix_RoleIsLearned(model, role))
                continue;
            missing++;

            request_t asked = default_request();
            asked.levels[k] = 2;                /* ask for it anyway */
            mapgen_topology_result_t rc5;
            const char *named = NULL;
            mapgen_topology_t *g = build(&asked, 0, &rc5, &named);
            if (rc5 == MAPGEN_TOPOLOGY_ERR_UNLEARNED_MOTIF)
                refused++;
            if (named && !strcmp(named,
                                 MapGenTopology_RouteControl((mapgen_route_kind_t)k)))
                named_right++;
            MapGenTopology_Free(g);
        }
        check("this corpus is missing at least one gated motif to ask for",
              missing > 0,
              "without one the refusal path would go untested and the case "
              "would be reporting nothing");
        check("asking for a motif the corpus never learned is refused, every time",
              missing > 0 && refused == missing, "");
        check("and the conflict is named exactly",
              missing > 0 && named_right == missing,
              "contract 14 wants the exact conflict, not that one exists");
    }

    /* --- map scale actually scales ---------------------------------------- */
    {
        request_t compact = default_request();
        compact.scale = 0;
        request_t huge = default_request();
        huge.scale = 3;

        mapgen_topology_result_t rc6;
        mapgen_topology_t *small = build(&compact, 0, &rc6, NULL);
        mapgen_topology_t *large = build(&huge, 0, &rc6, NULL);
        check("a compact map has fewer regions than a very large one",
              small && large
              && MapGenTopology_NumNodes(small) < MapGenTopology_NumNodes(large),
              "");
        if (small && large) {
            check("and both are still connected",
                  reachable_count(small, false) == MapGenTopology_NumNodes(small)
                  && reachable_count(large, false) == MapGenTopology_NumNodes(large),
                  "");
        }
        MapGenTopology_Free(small);
        MapGenTopology_Free(large);
    }

    /* --- verticality ------------------------------------------------------ */
    {
        request_t flat = default_request();
        flat.verticality = 0;
        mapgen_topology_result_t rc7;
        mapgen_topology_t *g = build(&flat, 0, &rc7, NULL);
        bool all_ground = true;
        for (uint32_t i = 0; g && i < MapGenTopology_NumNodes(g); i++)
            if (MapGenTopology_Node(g, i)->band != 0)
                all_ground = false;
        check("verticality None puts every region on one level", g && all_ground,
              "");
        MapGenTopology_Free(g);

        request_t tall = default_request();
        tall.verticality = 3;
        mapgen_topology_t *h = build(&tall, 0, &rc7, NULL);
        uint32_t highest = 0;
        for (uint32_t i = 0; h && i < MapGenTopology_NumNodes(h); i++)
            if (MapGenTopology_Node(h, i)->band > highest)
                highest = MapGenTopology_Node(h, i)->band;
        check("and High uses more than one", h && highest > 0, "");
        MapGenTopology_Free(h);
    }

    /* --- the goal changes the shape --------------------------------------- */
    {
        request_t duel = default_request();
        duel.goal = MAPGEN_GOAL_DUEL;
        duel.players_min = duel.players_max = 2;
        request_t sp = default_request();
        sp.goal = MAPGEN_GOAL_SINGLE_PLAYER;
        sp.players_min = sp.players_max = 1;

        mapgen_topology_result_t rc8;
        mapgen_topology_t *d = build(&duel, 0, &rc8, NULL);
        mapgen_topology_t *s = build(&sp, 0, &rc8, NULL);
        check("a duel graph has more loops than a single-player one",
              d && s && MapGenTopology_CyclomaticNumber(d)
                        > MapGenTopology_CyclomaticNumber(s),
              "duel control loops against a progression");
        if (d) {
            check("and the duel graph is still strongly connected",
                  strongly_connected(d), "");
        }
        MapGenTopology_Free(d);
        MapGenTopology_Free(s);
    }

    /* --- the canonical rendering ------------------------------------------ */
    {
        char *text = render(t);
        check("the canonical text names the learned map it was sized from",
              text && MapGenTopology_SampleSource(t)
              && strstr(text, MapGenTopology_SampleSource(t)) != NULL, "");
        check("and every route by kind name, not by number",
              text && strstr(text, ",walk\n") != NULL, "");
        free(text);
    }

    MapGenTopology_Free(t);
    MapGenMix_Free(model);
    MapGenSnapshot_Free(a);
    MapGenSnapshot_Free(b);
    free(bytes_a);
    free(bytes_b);

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
    return FAILED ? 1 : 0;
}
