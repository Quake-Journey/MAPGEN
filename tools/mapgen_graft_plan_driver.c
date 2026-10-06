/*
 * What it would take to carry each room of a map - printed, not done.
 *
 *     mapgen_graft_plan_driver <map.bsp> [--room N]
 *
 * One line per room: how many of its brushes travel as they are, how many are
 * walls it shares with a neighbour and would be cut, how many stay, how many
 * block it and why. With --room, every brush of that one room individually,
 * including the exact plane each shared wall would be cut on.
 *
 * This exists so that Codex's section 5 point 1 can be checked on real donors
 * before any geometry moves: which geometry is wholly owned, which must be
 * split at a declared cut, and which cannot safely be extracted.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_bundle.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_graft.h"
#include "common/mapgen_rooms.h"

static mapgen_bsp_t *load(const char *path)
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
    const mapgen_bsp_result_t rc = MapGenBsp_Load(raw, (size_t)n, &bsp);
    free(raw);
    return rc == MAPGEN_BSP_OK ? bsp : NULL;
}

/*
 * Actually carry one room across, and write the map that comes out.
 *
 * Every complete plan on our side against every complete plan on theirs, kept
 * on whichever pair seals - `uncovered` zero - and lines the most ways out up.
 * Nothing is written when no pair does, because a graft that leaves the map
 * open is the defect this operator exists to avoid rather than a result.
 */
static int do_graft(const mapgen_bsp_t *bsp, const mapgen_geometry_t *geometry,
                    const mapgen_bundle_set_t *set, int64_t want_room,
                    const char *donor_path, int64_t want_donor_room,
                    const char *out_map)
{
    mapgen_bsp_t *donor_bsp = load(donor_path);
    if (!donor_bsp) {
        printf("cannot read the donor %s\n", donor_path);
        return 2;
    }
    mapgen_geometry_t *donor = NULL;
    mapgen_rooms_t *donor_rooms = NULL;
    mapgen_bundle_set_t *donor_set = NULL;
    if (MapGenGeometry_FromBsp(donor_bsp, &donor) != MAPGEN_GEOMETRY_OK
        || MapGenRooms_Find(donor_bsp, 64.0f, MAPGEN_ROOMS_PERSISTENCE,
                            &donor_rooms) != MAPGEN_ROOMS_OK
        || MapGenBundle_Survey(donor_bsp, donor, donor_rooms, &donor_set)
           != MAPGEN_BUNDLE_OK) {
        printf("cannot survey the donor %s\n", donor_path);
        MapGenBundleSet_Free(donor_set);
        MapGenRooms_Free(donor_rooms);
        MapGenGeometry_Free(donor);
        MapGenBsp_Free(donor_bsp);
        return 2;
    }

    uint32_t best_mine = 0, best_theirs = 0;
    mapgen_graft_fit_t best;
    memset(&best, 0, sizeof(best));
    bool have = false;
    uint32_t pairs = 0;

    for (uint32_t r = 0; r < MapGenBundleSet_Count(set); r++) {
        if (want_room >= 0 && (uint32_t)want_room != r)
            continue;
        mapgen_graft_plan_t *mine = NULL;
        if (MapGenGraft_Describe(set, geometry, r, &mine) != MAPGEN_GRAFT_OK)
            continue;
        if (!MapGenGraft_Complete(mine)) {
            MapGenGraft_Free(mine);
            continue;
        }
        for (uint32_t d = 0; d < MapGenBundleSet_Count(donor_set); d++) {
            if (want_donor_room >= 0 && (uint32_t)want_donor_room != d)
                continue;
            mapgen_graft_plan_t *theirs = NULL;
            if (MapGenGraft_Describe(donor_set, donor, d, &theirs)
                != MAPGEN_GRAFT_OK)
                continue;
            if (!MapGenGraft_Complete(theirs)) {
                MapGenGraft_Free(theirs);
                continue;
            }
            mapgen_graft_fit_t fit;
            pairs++;
            if (MapGenGraft_Fit(bsp, geometry, mine, MapGenBundleSet_At(set, r),
                                donor, theirs,
                                MapGenBundleSet_At(donor_set, d), &fit)
                == MAPGEN_GRAFT_OK
                && (!have
                    || ((fit.fits && fit.brings_nothing_outside)
                        && !(best.fits && best.brings_nothing_outside
                             && best.region_is_sound))
                    || ((fit.fits && fit.brings_nothing_outside)
                        == (best.fits && best.brings_nothing_outside
                            && best.region_is_sound)
                        && fit.sockets_aligned > best.sockets_aligned))) {
                best = fit;
                best_mine = r;
                best_theirs = d;
                have = true;
            }
            MapGenGraft_Free(theirs);
        }
        MapGenGraft_Free(mine);
    }

    printf("pairs tried: %u\n", pairs);
    if (!have) {
        printf("no pair of complete plans\n");
        MapGenBundleSet_Free(donor_set);
        MapGenRooms_Free(donor_rooms);
        MapGenGeometry_Free(donor);
        MapGenBsp_Free(donor_bsp);
        return 1;
    }
    printf("best: our room %u <- their room %u, %u quarter turns%s, %s,"
           " %u of %u ways out still lead somewhere\n",
           best_mine, best_theirs, best.quarter_turns,
           best.mirror_x ? " mirrored" : "",
           !best.region_is_sound ? "the region holds void"
                                 : best.fits
           ? (best.brings_nothing_outside ? "fits"
                        : "fits but brings something outside")
                     : "DOES NOT FIT",
           best.sockets_aligned, best.sockets_wanted);
    printf("region: %.0f %.0f %.0f .. %.0f %.0f %.0f\n",
           best.region_lo[0], best.region_lo[1], best.region_lo[2],
           best.region_hi[0], best.region_hi[1], best.region_hi[2]);

    int status = 1;
    if (best.fits && best.brings_nothing_outside
        && best.region_is_sound) {
        mapgen_geometry_t *candidate = NULL;
        mapgen_graft_plan_t *mine = NULL, *theirs = NULL;
        if (MapGenGeometry_Clone(geometry, &candidate) == MAPGEN_GEOMETRY_OK
            && MapGenGraft_Describe(set, geometry, best_mine, &mine)
               == MAPGEN_GRAFT_OK
            && MapGenGraft_Describe(donor_set, donor, best_theirs, &theirs)
               == MAPGEN_GRAFT_OK) {
            const mapgen_bundle_t *their_bundle =
                MapGenBundleSet_At(donor_set, best_theirs);
            const uint32_t donor_entities =
                MapGenGeometry_NumEntities(donor);
            uint8_t *closure = calloc(donor_entities ? donor_entities : 1, 1);
            for (uint32_t i = 0;
                 closure && i < MapGenBundle_NumEntities(their_bundle); i++) {
                const uint32_t at = MapGenBundle_Entity(their_bundle, i);
                if (at < donor_entities)
                    closure[at] = 1;
            }
            const mapgen_graft_result_t rc =
                closure ? MapGenGraft_Apply(candidate, mine, donor, theirs,
                                            closure, donor_entities, &best)
                        : MAPGEN_GRAFT_ERR_MEMORY;
            free(closure);
            printf("apply: %s\n", MapGenGraft_ResultName(rc));
            if (rc == MAPGEN_GRAFT_OK) {
                printf("brushes: %u before, %u after\n",
                       MapGenGeometry_NumBrushes(geometry),
                       MapGenGeometry_NumBrushes(candidate));
                printf("entities: %u before, %u after\n",
                       MapGenGeometry_NumEntities(geometry),
                       MapGenGeometry_NumEntities(candidate));
                for (uint32_t e = MapGenGeometry_NumEntities(geometry);
                     e < MapGenGeometry_NumEntities(candidate); e++) {
                    const mapgen_geometry_entity_t *ent =
                        MapGenGeometry_Entity(candidate, e);
                    if (!ent || !ent->has_origin)
                        continue;
                    bool out_of_region = false;
                    for (int a = 0; a < 3; a++)
                        if (ent->origin[a] < best.region_lo[a]
                            || ent->origin[a] > best.region_hi[a])
                            out_of_region = true;
                    if (out_of_region)
                        printf("  arrived OUTSIDE: %s at %.0f %.0f %.0f\n",
                               MapGenGeometry_EntityValue(candidate, e,
                                                          "classname"),
                               ent->origin[0], ent->origin[1], ent->origin[2]);
                }
                status = MapGenGeometry_WriteValve220(candidate, out_map)
                         == MAPGEN_GEOMETRY_OK ? 0 : 1;
                printf("written: %s\n", status ? "no" : out_map);
            }
        }
        MapGenGraft_Free(mine);
        MapGenGraft_Free(theirs);
        MapGenGeometry_Free(candidate);
    }

    MapGenBundleSet_Free(donor_set);
    MapGenRooms_Free(donor_rooms);
    MapGenGeometry_Free(donor);
    MapGenBsp_Free(donor_bsp);
    return status;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        printf("usage: mapgen_graft_plan_driver <map.bsp> [--room N]\n"
               "       mapgen_graft_plan_driver <map.bsp> --graft <donor.bsp>"
               " <out.map> [--room N] [--donor-room M]\n");
        return 2;
    }
    int64_t only = -1;
    const char *donor_path = NULL, *out_map = NULL;
    int64_t donor_room = -1;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--room") && i + 1 < argc)
            only = strtoll(argv[i + 1], NULL, 10);
        else if (!strcmp(argv[i], "--donor-room") && i + 1 < argc)
            donor_room = strtoll(argv[i + 1], NULL, 10);
        else if (!strcmp(argv[i], "--graft") && i + 2 < argc) {
            donor_path = argv[i + 1];
            out_map = argv[i + 2];
        }
    }

    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        printf("cannot read %s\n", argv[1]);
        return 2;
    }
    mapgen_geometry_t *geometry = NULL;
    if (MapGenGeometry_FromBsp(bsp, &geometry) != MAPGEN_GEOMETRY_OK) {
        printf("cannot read the brushes of %s\n", argv[1]);
        MapGenBsp_Free(bsp);
        return 2;
    }
    mapgen_rooms_t *rooms = NULL;
    if (MapGenRooms_Find(bsp, 64.0f, MAPGEN_ROOMS_PERSISTENCE, &rooms)
        != MAPGEN_ROOMS_OK) {
        printf("cannot segment %s into rooms\n", argv[1]);
        MapGenGeometry_Free(geometry);
        MapGenBsp_Free(bsp);
        return 2;
    }
    mapgen_bundle_set_t *set = NULL;
    if (MapGenBundle_Survey(bsp, geometry, rooms, &set) != MAPGEN_BUNDLE_OK) {
        printf("cannot survey %s\n", argv[1]);
        MapGenRooms_Free(rooms);
        MapGenGeometry_Free(geometry);
        MapGenBsp_Free(bsp);
        return 2;
    }

    const uint32_t count = MapGenBundleSet_Count(set);
    printf("rooms: %u\n", count);

    /*
     * Every declared cut has to be a plane a reader can check: axial, on the
     * eighth of a unit the writer can spell exactly, and strictly INSIDE the
     * brush it splits. A plane outside the brush splits nothing and would
     * hand the whole wall to one side while the plan said it was shared.
     */
    uint32_t cuts = 0, violations = 0;
    uint32_t complete = 0, blocked_by[MAPGEN_GRAFT_REASON_COUNT] = { 0 };
    for (uint32_t r = 0; r < count; r++) {
        if (only >= 0 && (uint32_t)only != r)
            continue;
        mapgen_graft_plan_t *plan = NULL;
        const mapgen_graft_result_t rc =
            MapGenGraft_Describe(set, geometry, r, &plan);
        if (rc != MAPGEN_GRAFT_OK) {
            printf("room %3u  %s\n", r, MapGenGraft_ResultName(rc));
            continue;
        }
        const bool ok = MapGenGraft_Complete(plan);
        complete += ok ? 1 : 0;
        blocked_by[MapGenGraft_Why(plan)]++;
        printf("room %3u  %-8s  travels %4u  cut %3u  stays %3u  blocked %4u"
               "  %s\n", r, ok ? "COMPLETE" : "REFUSED",
               MapGenGraft_Count(plan, MAPGEN_GRAFT_TRAVELS),
               MapGenGraft_Count(plan, MAPGEN_GRAFT_CUT),
               MapGenGraft_Count(plan, MAPGEN_GRAFT_STAYS),
               MapGenGraft_Count(plan, MAPGEN_GRAFT_BLOCKED),
               MapGenGraft_ReasonName(MapGenGraft_Why(plan)));

        for (uint32_t i = 0; i < MapGenGraft_NumBrushes(plan); i++) {
            const mapgen_graft_brush_t *e = MapGenGraft_Brush(plan, i);
            if (e->disposition != MAPGEN_GRAFT_CUT)
                continue;
            cuts++;
            int axis = -1;
            bool axial = true;
            for (int a = 0; a < 3; a++) {
                if (e->cut_normal[a] == 1.0f || e->cut_normal[a] == -1.0f) {
                    if (axis >= 0)
                        axial = false;
                    axis = a;
                } else if (e->cut_normal[a] != 0.0f) {
                    axial = false;
                }
            }
            const mapgen_geometry_brush_t *gb =
                MapGenGeometry_Brush(geometry, e->brush);
            if (!axial || axis < 0 || !gb) {
                violations++;
                continue;
            }
            const float at = e->cut_normal[axis] * e->cut_dist;
            if (at * 8.0f != (float)(int32_t)(at * 8.0f)
                || at <= gb->mins[axis] || at >= gb->maxs[axis])
                violations++;
        }

        if (only >= 0) {
            for (uint32_t i = 0; i < MapGenGraft_NumBrushes(plan); i++) {
                const mapgen_graft_brush_t *e = MapGenGraft_Brush(plan, i);
                printf("  brush %5u  %-9s  %-8s", e->brush,
                       MapGenBundle_RoleName(e->role),
                       MapGenGraft_DispositionName(e->disposition));
                if (e->disposition == MAPGEN_GRAFT_CUT)
                    printf("  cut ( %.4f %.4f %.4f ) %.4f  with room %u",
                           e->cut_normal[0], e->cut_normal[1],
                           e->cut_normal[2], e->cut_dist, e->shared_with);
                else if (e->disposition == MAPGEN_GRAFT_BLOCKED)
                    printf("  %s", MapGenGraft_ReasonName(e->reason));
                else if (e->shared_with != UINT32_MAX)
                    printf("  with room %u", e->shared_with);
                printf("\n");
            }
        }
        MapGenGraft_Free(plan);
    }

    printf("cuts: %u checked, %u violations\n", cuts, violations);
    printf("complete: %u of %u\n", complete,
           only >= 0 ? 1u : count);
    for (uint32_t i = 1; i < MAPGEN_GRAFT_REASON_COUNT; i++)
        if (blocked_by[i])
            printf("refused %s: %u\n",
                   MapGenGraft_ReasonName((mapgen_graft_reason_t)i),
                   blocked_by[i]);

    int status = 0;
    if (donor_path && out_map)
        status = do_graft(bsp, geometry, set, only, donor_path, donor_room,
                          out_map);

    MapGenBundleSet_Free(set);
    MapGenRooms_Free(rooms);
    MapGenGeometry_Free(geometry);
    MapGenBsp_Free(bsp);
    return status;
}
