/*
 * The walk of a map made from another, taken from the other's walk where the edit could not reach - against the same
 * map walked whole (brief 16 D5, the PO 10.10: «чему тогда там было работать 2 часа 42 минуты»).
 *
 *     mapgen_reach_inherit_probe PARENT.bsp CHILD.bsp [workers]
 *
 * Walks PARENT keeping its simulations, then CHILD twice: from PARENT's walk, and whole. Prints each walk's time and
 * shape, the places taken and the brushes changed, both graph digests and the report fields the judge reads, and
 * exits 0 when the two walks of CHILD give the same graph, 1 when only the judge's numbers agree, 2 when they differ.
 */
#include "common/mapgen_bsp.h"
#include "common/mapgen_reach.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *data = size > 0 ? malloc((size_t)size) : NULL;
    const size_t got = data ? fread(data, 1, (size_t)size, f) : 0;
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    if (!data || got != (size_t)size || MapGenBsp_Load(data, (size_t)size, &bsp) != MAPGEN_BSP_OK)
        bsp = NULL;
    free(data);
    return bsp;
}

static double now_s(void)
{
    return (double)GetTickCount64() / 1000.0;
}

static void say(const char *what, const mapgen_reach_t *r, double seconds)
{
    const mapgen_reach_report_t *p = MapGenReach_Report(r);
    char digest[65];
    MapGenReach_GraphDigest(r, digest);
    printf("%-8s %6.1f s  states %u edges %u component %u trapped %u (lethal %u) items %u unreachable %u special %u"
           " landmarks %u/%u stranded %u movers %u inoperable %u  simulated %u reused %u inherited %u brushes_changed"
           " %d  digest %.16s\n",
           what, seconds, p->states, p->edges, p->component, p->trapped, p->trapped_lethal, p->items,
           p->items_unreachable, p->items_special, p->landmarks_unreachable, p->landmarks, p->spawns_stranded,
           p->movers, p->movers_inoperable, p->simulated, p->reused, p->inherited, (int)p->brushes_changed, digest);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s PARENT.bsp CHILD.bsp [workers]\n", argv[0]);
        return 3;
    }
    mapgen_bsp_t *a = load(argv[1]), *b = load(argv[2]);
    if (!a || !b) {
        fprintf(stderr, "cannot read the maps\n");
        return 3;
    }
    mapgen_reach_options_t o;
    memset(&o, 0, sizeof(o));
    o.workers = argc > 3 ? atoi(argv[3]) : 0;

    mapgen_reach_t *parent = NULL, *taken = NULL, *whole = NULL;
    o.keep = true;
    double t = now_s();
    if (MapGenReach_ExploreWith(a, 40000u, &o, &parent) != MAPGEN_REACH_OK || !parent) {
        fprintf(stderr, "the parent's walk failed\n");
        return 3;
    }
    say("parent", parent, now_s() - t);

    o.parent = parent;
    t = now_s();
    if (MapGenReach_ExploreWith(b, 40000u, &o, &taken) != MAPGEN_REACH_OK || !taken) {
        fprintf(stderr, "the child's walk from the parent failed\n");
        return 3;
    }
    const double t_taken = now_s() - t;
    say("taken", taken, t_taken);

    o.parent = NULL;
    o.keep = false;
    t = now_s();
    if (MapGenReach_ExploreWith(b, 40000u, &o, &whole) != MAPGEN_REACH_OK || !whole) {
        fprintf(stderr, "the child's whole walk failed\n");
        return 3;
    }
    const double t_whole = now_s() - t;
    say("whole", whole, t_whole);

    /* the floor: the child again from its own kept walk - nothing changed, every place taken */
    mapgen_reach_t *again = NULL;
    o.parent = taken;
    o.keep = false;
    t = now_s();
    if (MapGenReach_ExploreWith(b, 40000u, &o, &again) == MAPGEN_REACH_OK && again)
        say("again", again, now_s() - t);
    MapGenReach_Free(again);

    char da[65], db[65];
    MapGenReach_GraphDigest(taken, da);
    MapGenReach_GraphDigest(whole, db);
    const mapgen_reach_report_t *x = MapGenReach_Report(taken), *y = MapGenReach_Report(whole);
    const bool judged_same = x->component == y->component && x->trapped == y->trapped
                          && x->trapped_lethal == y->trapped_lethal && x->items_unreachable == y->items_unreachable
                          && x->landmarks_unreachable == y->landmarks_unreachable
                          && x->spawns_stranded == y->spawns_stranded && x->movers_inoperable == y->movers_inoperable
                          && MapGenReach_Passed(x) == MapGenReach_Passed(y);
    const int verdict = !strcmp(da, db) ? 0 : judged_same ? 1 : 2;
    printf("result %s  speed-up %.1fx\n", verdict == 0 ? "SAME GRAPH" : verdict == 1 ? "SAME VERDICTS, other graph"
                                                                                   : "DIFFERENT",
           t_taken > 0.0 ? t_whole / t_taken : 0.0);
    MapGenReach_Free(parent);
    MapGenReach_Free(taken);
    MapGenReach_Free(whole);
    MapGenBsp_Free(a);
    MapGenBsp_Free(b);
    return verdict;
}
