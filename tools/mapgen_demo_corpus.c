/*
 * What a corpus of recorded matches says, and whether the search agrees.
 *
 * Ingests every demo it is given, rejects the ones it must with a reason, and
 * then asks the question that makes the corpus worth having: of the places
 * real players occupied and the moves they were observed to make, how many
 * does the reachability search find?
 *
 * That comparison runs in one direction only, deliberately. A move somebody
 * made and the search does not have is a gap IN THE SEARCH - people are the
 * ground truth about a map people play. A place the search has and nobody
 * visited is not a defect in anything: a corpus of duels does not cover a map,
 * it covers the parts of it worth fighting over.
 *
 *     mapgen_demo_corpus <map.bsp> <demo.dm2> [more demos...]
 *                        [--map NAME] [--budget N] [--quiet]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_demo.h"
#include "common/mapgen_reach.h"

typedef struct {
    int32_t  cell[3];
    uint32_t frames;
    uint32_t contacts;
    bool     in_search;
} seen_cell_t;

typedef struct {
    int32_t  from[3];
    int32_t  to[3];
    uint32_t seen;
    bool     in_search;
} seen_move_t;

static seen_cell_t *g_cells;
static uint32_t g_num_cells, g_cap_cells;
static seen_move_t *g_moves;
static uint32_t g_num_moves, g_cap_moves;

static uint32_t find_or_add_cell(const int32_t c[3])
{
    for (uint32_t i = 0; i < g_num_cells; i++) {
        if (g_cells[i].cell[0] == c[0] && g_cells[i].cell[1] == c[1] &&
            g_cells[i].cell[2] == c[2])
            return i;
    }
    if (g_num_cells == g_cap_cells) {
        const uint32_t want = g_cap_cells ? g_cap_cells * 2 : 8192;
        seen_cell_t *grown = realloc(g_cells, want * sizeof(*grown));
        if (!grown)
            return UINT32_MAX;
        g_cells = grown;
        g_cap_cells = want;
    }
    const uint32_t id = g_num_cells++;
    memset(&g_cells[id], 0, sizeof(g_cells[id]));
    memcpy(g_cells[id].cell, c, sizeof(g_cells[id].cell));
    return id;
}

static void add_move(const int32_t from[3], const int32_t to[3], uint32_t seen)
{
    for (uint32_t i = 0; i < g_num_moves; i++) {
        if (!memcmp(g_moves[i].from, from, sizeof(g_moves[i].from)) &&
            !memcmp(g_moves[i].to, to, sizeof(g_moves[i].to))) {
            g_moves[i].seen += seen;
            return;
        }
    }
    if (g_num_moves == g_cap_moves) {
        const uint32_t want = g_cap_moves ? g_cap_moves * 2 : 16384;
        seen_move_t *grown = realloc(g_moves, want * sizeof(*grown));
        if (!grown)
            return;
        g_moves = grown;
        g_cap_moves = want;
    }
    seen_move_t *m = &g_moves[g_num_moves++];
    memcpy(m->from, from, sizeof(m->from));
    memcpy(m->to, to, sizeof(m->to));
    m->seen = seen;
    m->in_search = false;
}

static void quantize(const float p[3], int32_t out[3])
{
    for (int i = 0; i < 3; i++) {
        const float q = p[i] / MAPGEN_DEMO_CELL;
        out[i] = (int32_t)(q < 0 ? q - 0.999999f : q);
    }
}

static uint8_t *read_file(const char *path, size_t *size)
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
    *size = (size_t)n;
    return raw;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <map.bsp> <demo.dm2> [more...]"
                        " [--map NAME] [--budget N] [--quiet]\n", argv[0]);
        return 2;
    }

    const char *expect = NULL;
    uint32_t budget = 40000;
    bool quiet = false;
    for (int a = 2; a < argc; a++) {
        if (!strcmp(argv[a], "--map") && a + 1 < argc)
            expect = argv[++a];
        else if (!strcmp(argv[a], "--budget") && a + 1 < argc)
            budget = (uint32_t)strtoul(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--quiet"))
            quiet = true;
    }

    /* ---- the corpus ---------------------------------------------------- */

    uint32_t accepted = 0, rejected = 0;
    uint32_t rejects[16];
    memset(rejects, 0, sizeof(rejects));
    uint32_t events[MAPGEN_DEMO_EVENT_KINDS];
    memset(events, 0, sizeof(events));
    double total_seconds = 0.0;
    uint32_t total_samples = 0;

    for (int a = 2; a < argc; a++) {
        if (argv[a][0] == '-') {
            if (!strcmp(argv[a], "--map") || !strcmp(argv[a], "--budget"))
                a++;
            continue;
        }
        mapgen_demo_t *demo = NULL;
        const mapgen_demo_result_t rc =
            MapGenDemo_Read(argv[a], expect, argv[a], &demo);
        const mapgen_demo_provenance_t *p = MapGenDemo_Provenance(demo);
        if (rc != MAPGEN_DEMO_OK) {
            rejected++;
            if ((unsigned)rc < 16)
                rejects[rc]++;
            if (!quiet)
                printf("  rejected %-52s %s\n", argv[a],
                       MapGenDemo_ResultName(rc));
            MapGenDemo_Free(demo);
            continue;
        }
        accepted++;
        total_seconds += p->duration_ms / 1000.0;
        total_samples += p->samples;
        for (uint32_t k = 0; k < MAPGEN_DEMO_EVENT_KINDS; k++)
            events[k] += MapGenDemo_EventCount(demo,
                                               (mapgen_demo_event_kind_t)k);

        const uint32_t nc = MapGenDemo_NumCells(demo);
        for (uint32_t i = 0; i < nc; i++) {
            const mapgen_demo_cell_t *c = MapGenDemo_Cell(demo, i);
            const uint32_t id = find_or_add_cell(c->cell);
            if (id != UINT32_MAX) {
                g_cells[id].frames += c->frames;
                g_cells[id].contacts += c->contacts;
            }
        }
        const uint32_t nm = MapGenDemo_NumMoves(demo);
        for (uint32_t i = 0; i < nm; i++) {
            const mapgen_demo_move_t *m = MapGenDemo_Move(demo, i);
            const mapgen_demo_cell_t *f = MapGenDemo_Cell(demo, m->from);
            const mapgen_demo_cell_t *t = MapGenDemo_Cell(demo, m->to);
            if (f && t)
                add_move(f->cell, t->cell, m->seen);
        }
        MapGenDemo_Free(demo);
    }

    printf("corpus: %u accepted, %u rejected", accepted, rejected);
    if (rejected) {
        printf(" (");
        for (uint32_t i = 0; i < 16; i++) {
            if (rejects[i])
                printf("%s%s x%u",
                       i ? " " : "",
                       MapGenDemo_ResultName((mapgen_demo_result_t)i),
                       rejects[i]);
        }
        printf(")");
    }
    printf("\n  %.0f seconds of play, %u playerstates\n", total_seconds,
           total_samples);
    printf("  ");
    for (uint32_t k = 0; k < MAPGEN_DEMO_EVENT_KINDS; k++)
        printf("%s %u  ", MapGenDemo_EventName((mapgen_demo_event_kind_t)k),
               events[k]);
    printf("\n  %u places occupied, %u moves observed\n", g_num_cells,
           g_num_moves);

    if (!accepted) {
        printf("  nothing to compare against\n");
        return 1;
    }

    /* ---- the search ---------------------------------------------------- */

    size_t size = 0;
    uint8_t *raw = read_file(argv[1], &size);
    if (!raw) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    mapgen_bsp_t *bsp = NULL;
    if (MapGenBsp_Load(raw, size, &bsp) != MAPGEN_BSP_OK) {
        free(raw);
        fprintf(stderr, "not a map this can read\n");
        return 2;
    }
    free(raw);

    mapgen_reach_t *reach = NULL;
    const mapgen_reach_result_t rr = MapGenReach_Explore(bsp, budget, &reach);
    MapGenBsp_Free(bsp);
    if (rr != MAPGEN_REACH_OK && rr != MAPGEN_REACH_ERR_TOO_LARGE) {
        printf("  the search failed: %s\n", MapGenReach_ResultName(rr));
        MapGenReach_Free(reach);
        return 1;
    }

    const uint32_t states = MapGenReach_NumStates(reach);
    printf("  the search found %u places\n", states);

    for (uint32_t s = 0; s < states; s++) {
        const mapgen_reach_state_t *st = MapGenReach_State(reach, s);
        if (!st->reachable)
            continue;
        int32_t c[3];
        quantize(st->origin, c);
        for (uint32_t i = 0; i < g_num_cells; i++) {
            if (!memcmp(g_cells[i].cell, c, sizeof(c))) {
                g_cells[i].in_search = true;
                break;
            }
        }
    }

    /*
     * Two numbers, and only one of them means anything.
     *
     * A demo samples a player ten times a second WHEREVER HE IS, so a great
     * many of the cells he occupied are mid-jump and mid-fall - places nobody
     * stands, and the search, which records only where a burst came to rest,
     * cannot have them. Comparing against all of them measures how much of a
     * match is spent in the air, which is not a question about the map.
     *
     * The cells where his feet were on something are the comparable ones.
     */
    uint32_t covered = 0, covered_frames = 0, total_frames = 0;
    uint32_t stood = 0, stood_covered = 0;
    uint32_t contact_frames = 0, contact_covered = 0;
    for (uint32_t i = 0; i < g_num_cells; i++) {
        total_frames += g_cells[i].frames;
        if (g_cells[i].in_search) {
            covered++;
            covered_frames += g_cells[i].frames;
        }
        if (!g_cells[i].contacts)
            continue;
        stood++;
        contact_frames += g_cells[i].contacts;
        if (g_cells[i].in_search) {
            stood_covered++;
            contact_covered += g_cells[i].contacts;
        }
    }

    printf("\n  of the places people STOOD - feet on something - the search"
           " has %u of %u (%.1f%%)\n", stood_covered, stood,
           stood ? 100.0 * stood_covered / stood : 0.0);
    printf("  weighted by how long they stood there: %.1f%%\n",
           contact_frames ? 100.0 * contact_covered / contact_frames : 0.0);
    printf("  every place they occupied, in the air as well: %u of %u"
           " (%.1f%%), %.1f%% by time\n", covered, g_num_cells,
           g_num_cells ? 100.0 * covered / g_num_cells : 0.0,
           total_frames ? 100.0 * covered_frames / total_frames : 0.0);

    /* The busiest places the search does not know about, which is where to
       look when the number is not what it should be. */
    uint32_t shown = 0;
    for (uint32_t pass = 0; pass < 2 && shown < 8; pass++) {
        for (uint32_t i = 0; i < g_num_cells && shown < 8; i++) {
            if (g_cells[i].in_search || !g_cells[i].contacts)
                continue;
            if (pass == 0 && g_cells[i].contacts < 100)
                continue;
            printf("    they stood at %6d %6d %6d for %u frames and the"
                   " search has nothing there\n",
                   g_cells[i].cell[0] * 32, g_cells[i].cell[1] * 32,
                   g_cells[i].cell[2] * 32, g_cells[i].contacts);
            shown++;
        }
    }

    MapGenReach_Free(reach);
    free(g_cells);
    free(g_moves);
    return 0;
}
