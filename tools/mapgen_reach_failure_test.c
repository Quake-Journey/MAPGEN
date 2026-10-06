/*
 * Which absolute a reach report fails first - the one question the product
 * verdict and a refusal's witness both answer - proved without a map.
 *
 *     gcc -std=c17 -Iinc tools/mapgen_reach_failure_test.c -o t && t
 *
 * Controlled RED: -DMAPGEN_REACH_LETHAL_IS_NO_TRAP=0 counts a place that kills
 * as a refusal again and must fail EXACTLY the two lethal cases.
 *
 * The numbers are round 27's (ledger row 272): the delivered mg_20 passed with
 * 77 one-way places, all of them lethal, and a stairs-to-lift beside the acid
 * was refused with a witness naming those 77, so what did refuse it was never
 * written down.
 */

#include <stdio.h>
#include <string.h>

#include "common/mapgen_reach.h"

static int failures;

static void expect(const char *name, mapgen_reach_failure_t got,
                   mapgen_reach_failure_t want)
{
    printf("  %s  %s\n", got == want ? "PASS" : "FAIL", name);
    if (got != want)
        failures++;
}

/* mg_20 as round 27 delivered it, before any case changes a number */
static mapgen_reach_report_t mg_20(void)
{
    mapgen_reach_report_t r;
    memset(&r, 0, sizeof(r));
    r.states = 7549;
    r.spawns = 10;
    r.component = 7472;
    r.reachable = 7549;
    r.movers = 13;
    r.items = 83;
    r.landmarks = 11;
    return r;
}

int main(void)
{
    printf("the first absolute a report fails\n");
    mapgen_reach_report_t r = mg_20();
    expect("a map with nothing wrong passes", MapGenReach_FirstFailure(&r),
           MAPGEN_REACH_PASSES);

    r = mg_20();
    r.trapped = r.trapped_lethal = 77;
    expect("mg_20's 77 one-way places, all lethal, pass",
           MapGenReach_FirstFailure(&r), MAPGEN_REACH_PASSES);

    r = mg_20();
    r.trapped = r.trapped_lethal = 77;
    r.movers_inoperable = 1;
    expect("77 lethal places and a machine nothing operates name the machine",
           MapGenReach_FirstFailure(&r), MAPGEN_REACH_FAILS_MOVERS);

    r = mg_20();
    r.trapped = 78;
    r.trapped_lethal = 77;
    expect("one place that does not kill and has no way back is a trap",
           MapGenReach_FirstFailure(&r), MAPGEN_REACH_FAILS_TRAPPED);

    r = mg_20();
    r.trapped = r.trapped_lethal = 77;
    r.spawns_stranded = 1;
    expect("a stranded start is named before anything else",
           MapGenReach_FirstFailure(&r), MAPGEN_REACH_FAILS_STRANDED);

    r = mg_20();
    r.items_unreachable = 2;
    r.landmarks_unreachable = 1;
    expect("pickups are named before landmarks",
           MapGenReach_FirstFailure(&r), MAPGEN_REACH_FAILS_ITEMS);

    r = mg_20();
    r.spawns = 0;
    expect("a map with no start fails on that",
           MapGenReach_FirstFailure(&r), MAPGEN_REACH_FAILS_SPAWNS);
    expect("and no report at all is no pass",
           MapGenReach_FirstFailure(NULL), MAPGEN_REACH_FAILS_SPAWNS);

    printf("%d failures\n", failures);
    return failures ? 1 : 0;
}
