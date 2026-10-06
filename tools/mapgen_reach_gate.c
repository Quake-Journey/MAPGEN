/*
 * GF5R - can every player who starts here reach the others, and can everyone
 * who gets anywhere get back?
 *
 * Answered by walking the map with the engine's own player movement rather
 * than by a graph MAPGEN built for itself. Exit code 0 passes, 1 fails, and a
 * failure says where to stand to see it.
 *
 *     mapgen_reach_gate <map.bsp> [state budget] [--connectivity-only]
 *                       [--way fx fy fz  tx ty tz  lx ly lz  hx hy hz]...
 *
 * `--way` asks the dead-end gate's own question (`MapGenReach_WayThrough`) of a
 * passage: from the floor point f, through the box l..h, to the floor point t.
 * One line per way, WAY or DEAD END; any dead end makes the exit status 1.
 *
 * The default is the PRODUCT verdict: starts, safe return, pickups, landmarks
 * and operable machines, none of them optional. `--connectivity-only` asks the
 * survey question instead - can players reach each other and get back - which
 * is what a DONOR can answer, and its result is explicitly not publishable.
 *
 * `--donor D.bsp` (row 404, the generator's own rule since row 400): a map that fails the absolutes passes when
 * the donor it was made from fails them too and it is no worse (`MapGenReach_NoWorseThan`: no more stranded
 * starts, stuck places within a fiftieth, no pickup, landmark or machine the donor has in reach lost). cor's own
 * walk strands a start on a ledge its straight-up pad cannot reach and lets a player jump from a balcony past the
 * kill curtains; a map made from it inherits both. The line says it was held, and to what.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_certificate.h"
#include "common/mapgen_reach.h"

static mapgen_bsp_t *load_map(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    if (MapGenBsp_Load(raw, (size_t)n, &bsp) != MAPGEN_BSP_OK)
        bsp = NULL;
    free(raw);
    return bsp;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp> [budget]\n", argv[0]);
        return 2;
    }
    bool connectivity_only = false;
    /* The account behind the count of special traversals. Behind a flag: the
       ordinary run of this tool is read by a guard that counts lines. */
    bool show_certificates = false;
    /* What the transaction's own standing-water gate counts on this file: a
       vertical liquid face with AIR on the other side of it. A pit's wall has
       rock there and is not one, and «водой в воздухе» is what the PO filmed. */
    bool standing = false;
    uint32_t budget = 40000u;
    const char *donor_path = NULL;
    /* the passages to ask about: two ends, a count and that many boxes */
    struct { float from[3], to[3], box[6 * 32]; uint32_t boxes; } way[16];
    uint32_t num_ways = 0;
    for (int a = 2; a < argc; a++) {
        if (!strcmp(argv[a], "--way") && a + 7 < argc && num_ways < 16) {
            for (int k = 0; k < 3; k++) {
                way[num_ways].from[k] = strtof(argv[a + 1 + k], NULL);
                way[num_ways].to[k] = strtof(argv[a + 4 + k], NULL);
            }
            uint32_t boxes = (uint32_t)strtoul(argv[a + 7], NULL, 10);
            if (boxes > 32u)
                boxes = 32u;
            if (a + 7 + (int)(6u * boxes) >= argc) {
                fprintf(stderr, "--way wants %u boxes and there are not that"
                                " many numbers after it\n", boxes);
                return 2;
            }
            for (uint32_t k = 0; k < 6u * boxes; k++)
                way[num_ways].box[k] = strtof(argv[a + 8 + (int)k], NULL);
            way[num_ways].boxes = boxes;
            num_ways++;
            a += 7 + (int)(6u * boxes);
        }
        else if (!strcmp(argv[a], "--donor") && a + 1 < argc)
            donor_path = argv[++a];
        else if (!strcmp(argv[a], "--standing"))
            standing = true;
        else if (!strcmp(argv[a], "--connectivity-only"))
            connectivity_only = true;
        else if (!strcmp(argv[a], "--certificates"))
            show_certificates = true;
        else if (!strcmp(argv[a], "--physics")) {
            /* The identity of the movement rules this build computes with,
               which is what a certificate has to carry. */
            char physics[65];
            MapGenReach_PhysicsSha256(physics);
            printf("physics %s\n", physics);
            return 0;
        }
        else
            budget = (uint32_t)strtoul(argv[a], NULL, 10);
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    fclose(f);

    mapgen_bsp_t *bsp = NULL;
    if (MapGenBsp_Load(raw, (size_t)n, &bsp) != MAPGEN_BSP_OK) {
        free(raw);
        fprintf(stderr, "not a map this can read\n");
        return 2;
    }
    free(raw);

    if (standing) {
        double area = 0.0;
        const uint32_t faces = MapGenBsp_StandingWater(bsp, &area);
        printf("%s: %u vertical liquid face(s) with air behind them,"
               " %.0f square units\n", argv[1], faces, area);
    }

    mapgen_reach_t *reach = NULL;
    const mapgen_reach_result_t rc = MapGenReach_Explore(bsp, budget, &reach);
    MapGenBsp_Free(bsp);

    if (rc != MAPGEN_REACH_OK && rc != MAPGEN_REACH_ERR_TOO_LARGE) {
        printf("%s: %s\n", argv[1], MapGenReach_ResultName(rc));
        MapGenReach_Free(reach);
        return 1;
    }

    const mapgen_reach_report_t *r = MapGenReach_Report(reach);
    const mapgen_certificate_set_t *certificates =
        MapGenReach_Certificates(reach);
    printf("%s: %u places a player can stand, %u moves between them,"
           " %u spawns\n", argv[1], r->states, r->edges, r->spawns);
    printf("  component %u, reachable %u, one-way %u (%u lethal)\n",
           r->component, r->reachable, r->trapped, r->trapped_lethal);
    if (r->movers)
        printf("  %u movers, %u opened, %u that nothing can fire;"
               " %u exploration%s\n", r->movers, r->movers_open,
               r->movers_inoperable, r->rounds, r->rounds == 1 ? "" : "s");

    /* row 404: the teleporters and pads, and how many a player in the starts' component steps into */
    if (r->portals || r->pushes)
        printf("  %u teleporter%s, %u crossed; %u jump pad%s, %u crossed\n", r->portals,
               r->portals == 1 ? "" : "s", r->portals_crossed, r->pushes, r->pushes == 1 ? "" : "s",
               r->pushes_crossed);
    if (r->items_special)
        printf("  %u pickup%s reached by rocket jump, replayed on this map\n",
               r->items_special, r->items_special == 1 ? "" : "s");
    if (show_certificates && certificates && certificates->count) {
        char *text = malloc(65536);
        if (text) {
            MapGenCertificate_Render(certificates, text, 65536);
            fputs(text, stdout);
            free(text);
        }
    }
    if (r->items)
        printf("  %u pickups, %u of them out of a player's reach%s\n",
               r->items, r->items_unreachable,
               connectivity_only ? " (surveyed, not judged)" : "");
    if (r->landmarks)
        printf("  %u landmarks, %u of them out of a player's reach%s\n",
               r->landmarks, r->landmarks_unreachable,
               connectivity_only ? " (surveyed, not judged)" : "");

    int status = 0;
    if (rc == MAPGEN_REACH_ERR_TOO_LARGE) {
        printf("  INCONCLUSIVE: the exploration hit its budget of %u places;"
               " raise it or the answer is about part of the map\n", budget);
        status = 1;
    }
    bool passed = connectivity_only ? MapGenReach_ConnectivityOnly(r)
                                    : MapGenReach_Passed(r);
    /* row 404: held to the donor, when it was named and fails the same way */
    if (!passed && !connectivity_only && donor_path && rc == MAPGEN_REACH_OK) {
        mapgen_bsp_t *donor = load_map(donor_path);
        mapgen_reach_t *donor_reach = NULL;
        if (donor && MapGenReach_Explore(donor, budget, &donor_reach) == MAPGEN_REACH_OK) {
            const mapgen_reach_report_t *d = MapGenReach_Report(donor_reach);
            char why[200];
            /* row 409: and no trap the donor does not have, by place */
            float at[3] = { 0, 0, 0 };
            const uint32_t fresh = MapGenReach_NewTraps(reach, donor_reach, MAPGEN_REACH_NEW_TRAP_RADIUS, at);
            printf("  new traps: %u place(s) a player reaches and cannot leave that the donor has none of within %.0f%s",
                   fresh, (double)MAPGEN_REACH_NEW_TRAP_RADIUS, fresh ? "" : "\n");
            if (fresh)
                printf(", the first at %.0f %.0f %.0f\n", (double)at[0], (double)at[1], (double)at[2]);
            if (fresh > MAPGEN_REACH_NEW_TRAP_SLACK)
                printf("  the donor fails too, and this map has traps of its own\n");
            else if (MapGenReach_NoWorseThanWhy(r, d, why, sizeof(why))) {
                passed = true;
                printf("  HELD TO THE DONOR: %u stranded start(s) and %u place(s) a player can reach and not leave,"
                       " the donor %u and %u; pickups out of reach %u, the donor %u\n", r->spawns_stranded,
                       r->trapped - r->trapped_lethal, d->spawns_stranded, d->trapped - d->trapped_lethal,
                       r->items_unreachable, d->items_unreachable);
            } else {
                printf("  the donor fails too, and this map is worse: %s\n", why);
            }
        } else {
            printf("  the donor %s could not be walked\n", donor_path);
        }
        MapGenReach_Free(donor_reach);
        MapGenBsp_Free(donor);
    }
    if (connectivity_only)
        printf("  NOT A PRODUCT VERDICT: connectivity only, not publishable\n");
    if (!passed) {
        if (r->spawns_stranded) {
            printf("  FAIL: %u player start(s) cannot reach the others\n",
                   r->spawns_stranded);
            const uint32_t total = MapGenReach_NumStates(reach);
            for (uint32_t i = 0; i < total; i++) {
                const mapgen_reach_state_t *s = MapGenReach_State(reach, i);
                if (!s->from_spawn || (s->reachable && s->can_return))
                    continue;
                printf("    start at %.2f %.2f %.2f  %s the first start\n",
                       (double)s->origin[0], (double)s->origin[1],
                       (double)s->origin[2],
                       !s->reachable && !s->can_return
                           ? "neither reaches nor is reached from"
                           : (s->reachable ? "cannot get back to"
                                           : "cannot be reached from"));
            }
        }
        const uint32_t traps = r->trapped - r->trapped_lethal;
        if (traps) {
            printf("  FAIL: %u place(s) a player can reach and not leave\n",
                   traps);
            /*
             * Named, with their degrees. A count sends someone looking; a
             * coordinate and an out-degree of zero says what to look at, and
             * which of the two failures it is - a pocket in the map, or a
             * place the exploration itself could not leave.
             */
            uint32_t shown = 0;
            const uint32_t total = MapGenReach_NumStates(reach);
            for (uint32_t i = 0; i < total && shown < 8; i++) {
                const mapgen_reach_state_t *s = MapGenReach_State(reach, i);
                if (!s->reachable || s->can_return || s->hazard)
                    continue;
                printf("    at %.2f %.2f %.2f  in %u  out %u%s\n",
                       (double)s->origin[0], (double)s->origin[1],
                       (double)s->origin[2], s->in_degree, s->out_degree,
                       s->liquid ? "  (in liquid)" : "");
                shown++;
            }
            if (traps > shown)
                printf("    ... and %u more\n", traps - shown);
        }
        if (!connectivity_only && r->items_unreachable)
            printf("  FAIL: %u of %u pickup(s) are where no player can get"
                   " to them, one at %.0f %.0f %.0f\n", r->items_unreachable,
                   r->items, (double)r->worst_item[0],
                   (double)r->worst_item[1], (double)r->worst_item[2]);
        if (!connectivity_only && r->landmarks_unreachable)
            printf("  FAIL: %u of %u landmark(s) are where no player can get"
                   " to them, one at %.0f %.0f %.0f\n",
                   r->landmarks_unreachable, r->landmarks,
                   (double)r->worst_landmark[0], (double)r->worst_landmark[1],
                   (double)r->worst_landmark[2]);
        if (!connectivity_only && r->movers_inoperable)
            printf("  FAIL: %u machine(s) that nothing in the map can ever"
                   " operate\n", r->movers_inoperable);
        status = 1;
    } else if (!status) {
        printf("  PASS\n");
    }

    for (uint32_t w = 0; w < num_ways; w++) {
        mapgen_reach_way_t got;
        const bool ok = MapGenReach_WayThrough(reach, way[w].from, way[w].to,
                                               way[w].box, way[w].boxes,
                                               256.0f, &got);
        printf("  %s  %.0f %.0f %.0f -> %.0f %.0f %.0f through %u segment(s),"
               " the first %.0f %.0f %.0f .. %.0f %.0f %.0f%s\n",
               ok ? "WAY     " : "DEAD END",
               (double)way[w].from[0], (double)way[w].from[1],
               (double)way[w].from[2], (double)way[w].to[0],
               (double)way[w].to[1], (double)way[w].to[2], way[w].boxes,
               (double)way[w].box[0], (double)way[w].box[1],
               (double)way[w].box[2], (double)way[w].box[3],
               (double)way[w].box[4], (double)way[w].box[5],
               ok ? ""
               : got.start == UINT32_MAX ? " - nobody stands at the upper end"
               : got.goal == UINT32_MAX ? " - nobody stands at the lower end"
               : !got.entered ? " - no way from the upper end into it"
               : " - no way from inside it to the lower end");
        if (got.start != UINT32_MAX && got.goal != UINT32_MAX) {
            const mapgen_reach_state_t *s = MapGenReach_State(reach, got.start);
            const mapgen_reach_state_t *t = MapGenReach_State(reach, got.goal);
            printf("            ends stood at %.0f %.0f %.0f and %.0f %.0f %.0f;"
                   " %u of %u places in the box reached",
                   (double)s->origin[0], (double)s->origin[1],
                   (double)s->origin[2], (double)t->origin[0],
                   (double)t->origin[1], (double)t->origin[2],
                   got.box_reached, got.box_states);
            if (got.entered)
                printf("; entered at %.0f %.0f %.0f, nearest the lower end at"
                       " %.0f %.0f %.0f", (double)got.entry[0],
                       (double)got.entry[1], (double)got.entry[2],
                       (double)got.stuck[0], (double)got.stuck[1],
                       (double)got.stuck[2]);
            printf("\n");
        }
        if (!ok)
            status = 1;
    }

    MapGenReach_Free(reach);
    return status;
}
