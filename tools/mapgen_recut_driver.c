/*
 * The recut operator, one piece at a time, so each piece can be checked.
 *
 *     mapgen_recut_driver <donor.bsp> [--seed N] [--out FILE.map]
 *                         [--list]
 *                         [--apply N]
 *                         [--grow X Y Z]
 *                         [--sound X0 Y0 Z0 X1 Y1 Z1]
 *                         [--floor X0 Y0 Z0 X1 Y1 Z1]
 *                         [--hollow X0 Y0 Z0 X1 Y1 Z1 [--models]]
 *
 * `--list` prints what the schedule offers and where; `--grow` and `--sound`
 * ask the two questions the operator rests on without changing anything;
 * `--apply` and `--hollow` do the work and write a .map a compiler can be run
 * on, which is the only way to find out whether the result still seals.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_geometry_edit.h"
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
    uint8_t *raw = malloc((size_t)(n > 0 ? n : 1));
    if (!raw || n <= 0 || fread(raw, 1, (size_t)n, f) != (size_t)n) {
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

/* Is this point inside any brush of this geometry? The same question
   real_solid asks of the graft's own geometry, asked here of both sides. */
static bool covered(const mapgen_geometry_t *g, const float p[3])
{
    for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(g); b++) {
        const mapgen_geometry_brush_t *gb = MapGenGeometry_Brush(g, b);
        if (!gb || gb->model)
            continue;
        if (p[0] < gb->mins[0] || p[0] > gb->maxs[0]
            || p[1] < gb->mins[1] || p[1] > gb->maxs[1]
            || p[2] < gb->mins[2] || p[2] > gb->maxs[2])
            continue;
        bool in = true;
        for (uint32_t s = 0; s < gb->num_sides && in; s++) {
            const mapgen_geometry_side_t *side =
                MapGenGeometry_Side(g, gb->first_side + s);
            if (!side || side->bevel)
                continue;
            const float d = side->normal[0] * p[0] + side->normal[1] * p[1]
                          + side->normal[2] * p[2] - side->dist;
            if (d > 0.03125f)
                in = false;
        }
        if (in)
            return true;
    }
    return false;
}

int main(int argc, char **argv)
{
    const char *second_path = NULL;     /* brief 9: --second MAP.bsp */
    if (argc < 2) {
        fprintf(stderr, "usage: %s <donor.bsp> [--seed N] [--out FILE.map]"
                        " [--list] [--apply N] [--grow X Y Z] [--crates] [--recuts]"
                        " [--breakable]"
                        " [--contents X Y Z] [--sound X0 Y0 Z0 X1 Y1 Z1]"
                        " [--ambition N] [--ground BASE.bsp]"
                        " [--hollow X0 Y0 Z0 X1 Y1 Z1] [--models]\n", argv[0]);
        return 2;
    }

    uint64_t seed = 1;
    const char *out = NULL;
    bool list = false, models = false, do_floor = false;
    long apply = -1;
    /* Every edit the caller asked to apply, in order. */
    uint32_t applies[64];
    uint32_t num_applies = 0;
    float grow_at[3] = { 0, 0, 0 };
    bool do_grow = false;
    float probe[3] = { 0, 0, 0 };
    bool do_probe = false;
    float lo[3] = { 0, 0, 0 }, hi[3] = { 0, 0, 0 };
    bool do_sound = false, do_hollow = false, do_lost = false;
    float lost_step = 16.0f;
    float lost_lo[3] = { 0, 0, 0 }, lost_hi[3] = { 0, 0, 0 };
    bool lost_boxed = false;
    long ambition = -1;
    float climb_lo[3] = { 0, 0, 0 }, climb_hi[3] = { 0, 0, 0 };
    bool do_climb = false;
    const char *ground_path = NULL;
    const char *after_path = NULL;    /* row 364: ground for the applies only */
    float gapat[16][3];               /* row 369: points asked of the skin gaps */
    uint32_t num_gapat = 0;

    for (int a = 2; a < argc; a++) {
        /* brief 9: a second map the plan may take rooms and skins from */
        if (!strcmp(argv[a], "--second") && a + 1 < argc)
            second_path = argv[++a];
        else if (!strcmp(argv[a], "--seed") && a + 1 < argc)
            seed = strtoull(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--out") && a + 1 < argc)
            out = argv[++a];
        else if (!strcmp(argv[a], "--list"))
            list = true;
        /* The room block is not dealt into any product schedule;
           this asks for it back, and is what
           `check_mapgen_no_crates.py` uses to prove the gate is what
           is doing the work rather than a map that happens to have
           no room for one. */
        else if (!strcmp(argv[a], "--crates"))
            MapGenGeometryEdit_DealRoomBlocks(true);
        /* The recut is not dealt into any product schedule either, since the
           PO's fourth round of screenshots; this asks for it back so the
           family can still be tested. */
        else if (!strcmp(argv[a], "--recuts"))
            MapGenGeometryEdit_DealRecuts(true);
        /* And the breakable pane is not dealt, because the stock game frees
           it at spawn in deathmatch; this asks for it back so the launch
           guard can regenerate the map its red case needs. */
        else if (!strcmp(argv[a], "--breakable"))
            MapGenGeometryEdit_DealBreakableGlass(true);
        /* And the 128 x 128 pit, refused by the PO three times: not dealt in
           any product schedule, asked back here for the pit's own guards. */
        else if (!strcmp(argv[a], "--pits"))
            MapGenGeometryEdit_DealPits(true);
        /*
         * The three digs the PO named on 2026-09-11, watched through the plan
         * so the ledger says which stage refuses one instead of losing it in a
         * tally. The coordinates are his own landmarks out of the donor's
         * entity lump: the arena floor over the corridor, the ledge over the
         * room below it, and the upper rocket launcher down to the railgun.
         */
        else if (!strcmp(argv[a], "--norouter"))
            MapGenGeometryEdit_DigRouter(false);
        /* and the passage WITHOUT its mouth, which is the tunnel the PO walked
           into on 2026-09-11 and found closed at the top */
        else if (!strcmp(argv[a], "--nomouth"))
            MapGenGeometryEdit_DigMouths(false);
        else if (!strcmp(argv[a], "--powatch")) {
            /*
             * Where the PO actually stood and looked, read out of his own demo
             * of the test (2026-09-11-00.08-mg_20.dm2, origin and view ray per
             * server frame, the HUD clock matching the video's):
             *   (a) clock 0:37..0:44 - in the corridor at 1465 850 (floor 328),
             *       looking up; then on the arena at 1207 892, looking down at
             *       its floor 1325..1451 x 843..903, z 448, over that corridor.
             *   (b) clock 1:46..1:54 - on the ledge at 927 346 (floor 750),
             *       looking down; he drops to the floor at 510, walks to
             *       1446 294 and looks UP for six seconds at 1414 266 617 - the
             *       underside of the platform at 640 over him. «Аналогично»:
             *       like (a), the level above and the level below joined.
             *   (c) clock 2:30..2:53 - he starts at 1093 -81 on the rocket
             *       launcher's walkway (896), walks it to the launcher, jumps
             *       into the courtyard (~230), climbs the ramp to the railgun
             *       room (444) and picks the railgun up at 2:53. The walkway
             *       is a diagonal strip ~150 across with the courtyard on BOTH
             *       sides, so no passage-wide mouth fits beside the launcher
             *       itself (MEASURED: every anchor round 704 104 is refused);
             *       the watch is the walkway's east end, where he started.
             * The first guesses (a 1488 520, b 1304 1344) were not where he was.
             */
            const float a_from[3] = { 1430.0f, 870.0f, 448.0f };
            const float a_to[3]   = { 1465.0f, 850.0f, 328.0f };
            const float b_from[3] = { 1330.0f, 300.0f, 640.0f };
            const float b_to[3]   = { 1440.0f, 290.0f, 510.0f };
            const float c_from[3] = { 1150.0f, -40.0f, 896.0f };
            const float c_to[3]   = { 300.0f, -400.0f, 444.0f };
            MapGenGeometryEdit_WatchDig(a_from, a_to, "a arena->corridor");
            MapGenGeometryEdit_WatchDig(b_from, b_to, "b ledge->room below");
            MapGenGeometryEdit_WatchDig(c_from, c_to, "c rocket->railgun");
        }
        /* Which of the dig's four passes run: bit 1 shell, 2 carve, 4 fill,
           8 fit. The bisection instrument, and the controlled RED's lever. */
        else if (!strcmp(argv[a], "--showcase-glass"))
            MapGenGeometryEdit_ShowcaseGlass(true);
        /* a showcase count for the tunnel deal (ledger row 248) */
        else if (!strcmp(argv[a], "--digs") && a + 1 < argc)
            MapGenGeometryEdit_WantDigs((uint32_t)strtoul(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--digpass") && a + 1 < argc)
            MapGenGeometryEdit_DigPasses((uint32_t)strtoul(argv[++a], NULL, 10));
        /* brief 14 F5: `--halls N` as the pipeline (and the ledger's plan-options) says it, `--halls N W H` as the
           guards do - the size only when two numbers follow; it used to swallow the next option whole (the PO's
           `--halls 6 --stairways 10` dealt no stairway in the checks' re-deal) */
        else if (!strcmp(argv[a], "--halls") && a + 1 < argc) {
            const uint32_t count = (uint32_t)strtoul(argv[++a], NULL, 10);
            float wide = 0.0f, high = 0.0f;
            if (a + 2 < argc && argv[a + 1][0] != '-' && argv[a + 2][0] != '-') {
                wide = strtof(argv[++a], NULL);
                high = strtof(argv[++a], NULL);
            }
            MapGenGeometryEdit_DigHalls(count, wide, high);
        }
        else if (!strcmp(argv[a], "--liquids") && a + 1 < argc)          /* brief 14 F5: the pipeline's words too */
            MapGenGeometryEdit_SetLiquids(argv[++a]);
        else if (!strcmp(argv[a], "--decor") && a + 1 < argc)
            MapGenGeometryEdit_SetWallDecor((uint32_t)strtoul(argv[++a], NULL, 10));
        else if ((!strcmp(argv[a], "--annex") || !strcmp(argv[a], "--annexes")) && a + 4 < argc) {
            const uint32_t count = (uint32_t)strtoul(argv[++a], NULL, 10);
            const float wide = strtof(argv[++a], NULL);
            const float deep = strtof(argv[++a], NULL);
            const float high = strtof(argv[++a], NULL);
            MapGenGeometryEdit_DigAnnexes(count, wide, deep, high);
        }
        else if (!strcmp(argv[a], "--new-water") && a + 1 < argc)      /* row 412 */
            MapGenGeometryEdit_SetNewLiquid(0u, (int32_t)strtol(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--new-slime") && a + 1 < argc)
            MapGenGeometryEdit_SetNewLiquid(1u, (int32_t)strtol(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--new-lava") && a + 1 < argc)
            MapGenGeometryEdit_SetNewLiquid(2u, (int32_t)strtol(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--real-rooms") && a + 1 < argc)     /* row 412 */
            MapGenGeometryEdit_DigRealRooms((uint32_t)strtoul(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--annex-uncapped"))     /* row 412 */
            MapGenGeometryEdit_DigAnnexUncapped(true);
        else if (!strcmp(argv[a], "--annexgap") && a + 1 < argc)
            MapGenGeometryEdit_DigAnnexGap(strtof(argv[++a], NULL));
        else if (!strcmp(argv[a], "--storeys") && a + 1 < argc)
            MapGenGeometryEdit_DigStoreys((uint32_t)strtoul(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--spans") && a + 1 < argc)
            MapGenGeometryEdit_DigSpans((uint32_t)strtoul(argv[++a], NULL, 10));
        /* brief 11 D1: stairways up the rooms' walls, 0..10 */
        else if (!strcmp(argv[a], "--stairways") && a + 1 < argc)
            MapGenGeometryEdit_DigStairways((uint32_t)strtoul(argv[++a], NULL, 10));
        else if (!strcmp(argv[a], "--lost"))
            do_lost = true;
        else if (!strcmp(argv[a], "--step") && a + 1 < argc)
            lost_step = strtof(argv[++a], NULL);
        else if (!strcmp(argv[a], "--lostbox") && a + 6 < argc) {
            for (int i = 0; i < 3; i++)
                lost_lo[i] = strtof(argv[++a], NULL);
            for (int i = 0; i < 3; i++)
                lost_hi[i] = strtof(argv[++a], NULL);
            do_lost = true;
            lost_boxed = true;
        }
        else if (!strcmp(argv[a], "--models"))
            models = true;
        else if (!strcmp(argv[a], "--ground") && a + 1 < argc)
            ground_path = argv[++a];
        /*
         * Row 364: the plan dealt as before and the edits then applied over
         * ANOTHER map - the accepted map a round has reached when a later edit
         * of the same plan is applied, which is how the transaction does it.
         */
        else if (!strcmp(argv[a], "--ground-after") && a + 1 < argc)
            after_path = argv[++a];
        else if (!strcmp(argv[a], "--gapat") && a + 3 < argc) {
            if (num_gapat < 16u) {
                gapat[num_gapat][0] = strtof(argv[a + 1], NULL);
                gapat[num_gapat][1] = strtof(argv[a + 2], NULL);
                gapat[num_gapat][2] = strtof(argv[a + 3], NULL);
                num_gapat++;
            }
            a += 3;
        }
        /* row 384: the RED's switch - a skinned dig lifts no courtyard's sky */
        else if (!strcmp(argv[a], "--nolift"))
            MapGenGeometryEdit_SetSkyLift(false);
        else if (!strcmp(argv[a], "--ambition") && a + 1 < argc)
            ambition = strtol(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--climb") && a + 6 < argc) {
            for (int i = 0; i < 3; i++)
                climb_lo[i] = strtof(argv[++a], NULL);
            for (int i = 0; i < 3; i++)
                climb_hi[i] = strtof(argv[++a], NULL);
            do_climb = true;
        }
        else if (!strcmp(argv[a], "--apply") && a + 1 < argc) {
            apply = strtol(argv[++a], NULL, 10);
            if (apply >= 0 && num_applies < 64)
                applies[num_applies++] = (uint32_t)apply;
        }
        else if (!strcmp(argv[a], "--contents") && a + 3 < argc) {
            for (int i = 0; i < 3; i++)
                probe[i] = strtof(argv[++a], NULL);
            do_probe = true;
        }
        else if (!strcmp(argv[a], "--grow") && a + 3 < argc) {
            for (int i = 0; i < 3; i++)
                grow_at[i] = strtof(argv[++a], NULL);
            do_grow = true;
        } else if (!strcmp(argv[a], "--sound") && a + 6 < argc) {
            for (int i = 0; i < 3; i++)
                lo[i] = strtof(argv[++a], NULL);
            for (int i = 0; i < 3; i++)
                hi[i] = strtof(argv[++a], NULL);
            do_sound = true;
        } else if (!strcmp(argv[a], "--floor") && a + 6 < argc) {
            for (int i = 0; i < 3; i++)
                lo[i] = strtof(argv[++a], NULL);
            for (int i = 0; i < 3; i++)
                hi[i] = strtof(argv[++a], NULL);
            do_floor = true;
        } else if (!strcmp(argv[a], "--hollow") && a + 6 < argc) {
            for (int i = 0; i < 3; i++)
                lo[i] = strtof(argv[++a], NULL);
            for (int i = 0; i < 3; i++)
                hi[i] = strtof(argv[++a], NULL);
            do_hollow = true;
        }
    }

    mapgen_bsp_t *bsp = load(argv[1]);
    /*
     * What the operators measure against, when it is not the donor's own file.
     *
     * The transaction hands them the BASELINE - the donor written back out and
     * compiled again - because that is the map a candidate's own compile
     * produces, and a gate that judges against one map while the operator asks
     * another is a gate charging the operator for the compiler. A guard that
     * wants to reproduce what the product does has to hand over the same map.
     */
    mapgen_bsp_t *ground = ground_path ? load(ground_path) : NULL;
    mapgen_geometry_t *donor = NULL;
    if (!bsp || MapGenGeometry_FromBsp(bsp, &donor) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    printf("donor %u brushes\n", MapGenGeometry_NumBrushes(donor));
    if (ground_path && !ground)
        fprintf(stderr, "cannot read ground %s\n", ground_path);

    /* Who is standing in the water. Asked of the geometry, which is what the
       transaction asks before it spends a compile. */
    {
        char who[128] = "";
        const uint32_t wet =
            MapGenGeometry_DrownedEntities(donor, false, who, sizeof(who));
        printf("drowned %u%s%s\n", wet, wet ? ": " : "", who);
    }

    /* What a player would walk into at one point, straight out of the tree. */
    if (do_probe)
        printf("contents %s at %.0f %.0f %.0f\n",
               (MapGenBsp_PointContents(bsp, probe) & 1) ? "solid" : "empty",
               probe[0], probe[1], probe[2]);

    if (do_climb)
        printf("climb in box %s\n",
               MapGenGeometryEdit_RegionHasClimb(bsp, climb_lo, climb_hi)
                   ? "yes" : "no");

    if (do_sound) {
        (void)0;
        const bool sound = MapGenGraft_RegionIsSound(bsp, donor, lo, hi);
        printf("sound %s\n", sound ? "yes" : "no");
        if (!sound) {
            /* Where, and what covered it. A proof that answers only "no"
               cost a day to read on 2026-09-08. */
            const mapgen_graft_refusal_t *w = MapGenGraft_LastRefusal();
            printf("  refused at %.4f %.4f %.4f  leaf contents %#x"
                   "  brush %d  %s\n",
                   (double)w->point[0], (double)w->point[1],
                   (double)w->point[2], (unsigned)w->leaf_contents,
                   w->brush == UINT32_MAX ? -1 : (int)w->brush, w->why);
        }
    }

    if (do_grow) {
        float glo[3], ghi[3];
        if (MapGenGraft_GrowSoundRegion(bsp, donor, grow_at, 64u, glo, ghi))
            printf("grown %.0f %.0f %.0f  %.0f %.0f %.0f  span %.0f %.0f %.0f\n",
                   glo[0], glo[1], glo[2], ghi[0], ghi[1], ghi[2],
                   ghi[0] - glo[0], ghi[1] - glo[1], ghi[2] - glo[2]);
        else
            printf("grown no\n");
    }

    if (do_floor) {
        /*
         * The builder's OWN nine samples under a footprint, printed.
         *
         * Not a second copy of the scan: a scratch probe that reimplements
         * `footprint_ground` proves the probe. `MapGenGeometryEdit_OneFloor`
         * asks the question and the accessors hand back what it saw.
         */
        const bool one = MapGenGeometryEdit_OneFloor(bsp, lo, hi);
        const float *box = MapGenGeometryEdit_LastGroundBox();
        printf("floor under %.0f %.0f %.0f .. %.0f %.0f %.0f: %s\n",
               box[0], box[1], box[2], box[3], box[4], box[5],
               one ? "ONE floor" : "not one floor");
        float lowest = 0.0f, highest = 0.0f;
        bool any = false, missed = false;
        for (uint32_t i = 0; i < 9; i++) {
            float at = 0.0f;
            if (!MapGenGeometryEdit_LastGround(i, &at)) {
                printf("  sample %u: no ground within 1024 below %.0f\n",
                       i, box[5]);
                missed = true;
                continue;
            }
            printf("  sample %u: ground %.0f, %.0f below the box top\n",
                   i, at, box[5] - at);
            if (!any || at < lowest) lowest = at;
            if (!any || at > highest) highest = at;
            any = true;
        }
        if (any)
            printf("lowest %.0f highest %.0f spread %.0f\n",
                   lowest, highest, highest - lowest);
        if (missed)
            printf("a footprint over a pit is refused, not floated\n");
    }

    mapgen_bsp_t *second_bsp = second_path ? load(second_path) : NULL;
    mapgen_geometry_t *second = NULL;
    if (second_bsp && MapGenGeometry_FromBsp(second_bsp, &second) != MAPGEN_GEOMETRY_OK)
        second = NULL;
    const char *second_name = NULL;
    if (second_path) {
        const char *slash = strrchr(second_path, '/'), *back = strrchr(second_path, 0x5C);
        second_name = back > slash ? back + 1 : slash ? slash + 1 : second_path;
    }
    const mapgen_geometry_t *second_g[1] = { second };
    const mapgen_bsp_t *second_b[1] = { second_bsp };
    const char *second_n[1] = { second_name };
    mapgen_geometry_edit_plan_t *plan = NULL;
    /* Planned ON the ground and ON the ambition when either is given, which is
       what the transaction does: a schedule dealt against the donor's own file
       and then judged against the baseline is charged for the round trip, and a
       schedule dealt at ambition zero and then told to be ambitious has already
       thrown away the places the extra breadth would have searched. */
    if ((list || apply >= 0)
        && MapGenGeometryEdit_PlanOn(donor, bsp, ground,
                                     ambition >= 0 ? (int32_t)ambition : 0,
                                     seed, second ? second_g : NULL, second ? second_b : NULL,
                                     second ? second_n : NULL, second ? 1u : 0u, &plan)
           != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot plan\n");
        return 2;
    }
    if (plan && ambition >= 0)
        MapGenGeometryEdit_SetAmbition(plan, (int32_t)ambition);
    /* The plan is DEALT from the donor - which is what the product does, so
       that the schedule is the same one - and the operators then measure
       against the ground they are given. */
    if (plan && ground)
        MapGenGeometryEdit_SetGround(plan, ground);
    mapgen_bsp_t *after = after_path ? load(after_path) : NULL;
    if (after_path && !after)
        fprintf(stderr, "cannot read ground-after %s\n", after_path);
    if (plan && after)
        MapGenGeometryEdit_SetGround(plan, after);

    if (list) {
        /* What the family did NOT offer, and why - which is the half of a
           schedule that a silent `continue` used to hide. */
        const uint32_t refusals = MapGenGeometryEdit_NumRefusals(plan);
        if (MapGenGeometryEdit_RefusalsSeen(plan)) {
            printf("refused %u (showing %u):\n",
                   MapGenGeometryEdit_RefusalsSeen(plan), refusals);
            for (uint32_t i = 0; i < refusals; i++)
                printf("  %s\n", MapGenGeometryEdit_Refusal(plan, i));
        }
        const uint32_t n = MapGenGeometryEdit_Count(plan);
        /* Every family the schedule deals, by name and count. A guard
           that asks "does the product still offer crates" should not
           have to infer it from the lines this driver happens to
           print in full. */
        printf("families:");
        for (uint32_t k = 0; k < MAPGEN_EDIT_KINDS; k++) {
            const uint32_t c =
                MapGenGeometryEdit_CountOfKind(plan,
                                               (mapgen_edit_kind_t)k);
            if (c)
                printf(" %s=%u",
                       MapGenGeometryEdit_KindName(
                           (mapgen_edit_kind_t)k), c);
        }
        printf("\n");
        printf("recuts %u, pushes %u of %u edits\n",
               MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_RECUT_ROOM),
               MapGenGeometryEdit_CountOfKind(plan, MAPGEN_EDIT_PUSH_WALL), n);
        for (uint32_t i = 0; i < n; i++) {
            const mapgen_geometry_edit_t *e = MapGenGeometryEdit_At(plan, i);
            if (!e)
                continue;
            if (e->kind == MAPGEN_EDIT_RELEVEL) {
                printf("  edit %u  relevel %4d\n", i, e->amount);
                continue;
            }
            /* D25 (assignment 24): a swap's two pickups by class, so the
               listing shows no pair of one class */
            if (e->kind == MAPGEN_EDIT_SWAP_ITEM) {
                const char *a =
                    MapGenGeometry_EntityValue(donor, e->target, "classname");
                const char *b = MapGenGeometry_EntityValue(
                    donor, (uint32_t)e->amount, "classname");
                printf("  edit %u  swap-item  %u %s <-> %d %s\n", i,
                       e->target, a ? a : "?", e->amount, b ? b : "?");
                continue;
            }
            /*
             * A PIT, with the hollow it cuts and what fills it: the line a
             * script applies by index and a reader walks to by coordinate.
             */
            /* brief 11 D1: a STAIRWAY by its box - applied by index, read against the plan's own lines */
            if (e->kind == MAPGEN_EDIT_STAIRWAY) {
                float plo[3] = { 0, 0, 0 }, phi[3] = { 0, 0, 0 };
                if (MapGenGeometryEdit_BoxOf(plan, bsp, donor, i, plo, phi))
                    printf("  edit %u  stairway  %.0f %.0f %.0f .. %.0f %.0f %.0f  %d high\n", i, (double)plo[0],
                           (double)plo[1], (double)plo[2], (double)phi[0], (double)phi[1], (double)phi[2], e->amount);
                continue;
            }
            if (e->kind == MAPGEN_EDIT_PIT) {
                float plo[3] = { 0, 0, 0 }, phi[3] = { 0, 0, 0 };
                if (MapGenGeometryEdit_BoxOf(plan, bsp, donor, i, plo, phi))
                    printf("  edit %u  pit  %.0f %.0f %.0f .. %.0f %.0f %.0f"
                           "  %d deep\n", i, (double)plo[0], (double)plo[1],
                           (double)plo[2], (double)phi[0], (double)phi[1],
                           (double)phi[2], e->amount);
                continue;
            }
            /*
             * A FLOOD, by the room it drowns: the same shape of line as the
             * pit's, so a script applies it by index and a reader walks to it
             * by coordinate.
             */
            if (e->kind == MAPGEN_EDIT_FLOOD) {
                float plo[3] = { 0, 0, 0 }, phi[3] = { 0, 0, 0 };
                if (MapGenGeometryEdit_BoxOf(plan, bsp, donor, i, plo, phi))
                    printf("  edit %u  flood  %.0f %.0f %.0f .. %.0f %.0f %.0f"
                           "  %d deep\n", i, (double)plo[0], (double)plo[1],
                           (double)plo[2], (double)phi[0], (double)phi[1],
                           (double)phi[2], e->amount);
                continue;
            }
            /*
             * A construction with the box it will occupy, so a gate that has
             * to ask what a player can do ON it does not have to guess where
             * it is. The box is the operator's own - `ConstructionOf` reads
             * what `block_stands` decides - and an edit that will decline
             * where it was dealt says so here rather than printing a box
             * nothing will ever stand in.
             */
            if (e->kind == MAPGEN_EDIT_ROOM_BLOCK
                || e->kind == MAPGEN_EDIT_RECUT_ROOM) {
                float clo[3] = { 0, 0, 0 }, chi[3] = { 0, 0, 0 };
                const char *what = e->kind == MAPGEN_EDIT_ROOM_BLOCK
                                 ? "block" : "recut";
                /* Asked of the GROUND, which is the map the operator was
                   planned on and will be judged by. */
                if (!MapGenGeometryEdit_ConstructionOf(plan, ground ? ground
                                                                    : bsp,
                                                       i, clo, chi)) {
                    printf("  edit %u  %s declines\n", i, what);
                    continue;
                }
                printf("  edit %u  %-5s %6.0f %6.0f %6.0f .. %6.0f %6.0f"
                       " %6.0f  amount %d\n", i, what,
                       (double)clo[0], (double)clo[1], (double)clo[2],
                       (double)chi[0], (double)chi[1], (double)chi[2],
                       e->amount);
                continue;
            }
            /*
             * A DIG, with both its endpoints: the line a script applies by
             * index and a reader walks by coordinate. Printed for the same
             * reason as the window - a family that is offered and never listed
             * cannot be applied by hand.
             */
            if (e->kind == MAPGEN_EDIT_DIG) {
                mapgen_dig_report_t dig;
                if (MapGenGeometryEdit_DigAt(plan, e->target, &dig)) {
                    char halls[32] = "";
                    if (dig.halls)
                        snprintf(halls, sizeof(halls), "  %u halls", dig.halls);
                    printf("  edit %u  dig  %u  %.0f %.0f %.0f -> %.0f %.0f"
                           " %.0f  %s  %u steps  %u landings  %u lights"
                           "  ratio %u%s%s%s\n", i, e->target,
                           (double)dig.from[0], (double)dig.from[1],
                           (double)dig.from[2], (double)dig.to[0],
                           (double)dig.to[1], (double)dig.to[2], dig.shape,
                           dig.steps, dig.landings, dig.lights, dig.ratio,
                           dig.lift ? "  lift" : "",
                           dig.hatch ? "  hatch" : "", halls);
                } else
                    printf("  edit %u  dig  %u  unreadable\n", i,
                           e->target);
                /*
                 * And the BOX the run's own ledger prints for this edit, so a
                 * delivered map's accepted digs can be matched back to their
                 * endpoints and landmarks by something exact rather than by
                 * order.
                 */
                {
                    float blo[3] = { 0, 0, 0 }, bhi[3] = { 0, 0, 0 };
                    if (MapGenGeometryEdit_BoxOf(plan, bsp, donor, i, blo, bhi))
                        printf("  digbox %u %.0f %.0f %.0f %.0f %.0f %.0f\n",
                               i, (double)blo[0], (double)blo[1],
                               (double)blo[2], (double)bhi[0],
                               (double)bhi[1], (double)bhi[2]);
                    /*
                     * And SEGMENT by segment, in the order a player walks them.
                     * The dead-end gate asks about the passage rather than
                     * about the box round it: the bounding box of a passage
                     * that bends holds rooms that are not in it.
                     */
                    float segs[6 * 32];
                    const uint32_t ns =
                        MapGenGeometryEdit_DigBoxes(plan, e->target, segs, 32u);
                    for (uint32_t s = 0; s < ns; s++)
                        printf("  digseg %u %u %.0f %.0f %.0f %.0f %.0f %.0f\n",
                               i, s, (double)segs[6 * s + 0],
                               (double)segs[6 * s + 1], (double)segs[6 * s + 2],
                               (double)segs[6 * s + 3], (double)segs[6 * s + 4],
                               (double)segs[6 * s + 5]);
                }
                /* and the waypoints a player walks, for the hull probe */
                /* a routed dig is a long chain: room for every segment */
                float chain[3 * 64];
                const uint32_t n =
                    MapGenGeometryEdit_DigChain(plan, e->target, chain, 64u);
                printf("  chain %u %u", i, n);
                for (uint32_t w = 0; w < n; w++)
                    printf(" %.0f %.0f %.0f", (double)chain[w * 3],
                           (double)chain[w * 3 + 1], (double)chain[w * 3 + 2]);
                printf("\n");
                continue;
            }
            /* A window: the wall it is cut into and where the
               opening sits in it. Printed because a family that is
               offered and never listed cannot be applied by hand. */
            if (e->kind == MAPGEN_EDIT_WINDOW) {
                /*
                 * The OPENING it belongs to, and not just the amount.
                 *
                 * The schedule is dealt round-robin by kind and shuffled
                 * within each kind, so the order the offers were PLANNED in
                 * is not the order the edits come out in - and a guard that
                 * paired the k-th offer with the k-th window edit applied a
                 * row of three where it meant to apply one doorway. The
                 * opening index is the identity both sides can agree on.
                 */
                printf("  edit %u  window  opening %u  amount %d\n", i,
                       e->target, e->amount);
                continue;
            }
            if (e->kind == MAPGEN_EDIT_STAIRS_LIFT) {
                float slo[3] = { 0, 0, 0 }, shi[3] = { 0, 0, 0 };
                float rise = 0.0f;
                /* The box the MACHINE replaces, which is the flight plus
                   everything the shaft absorbs with it - not the steps'
                   own bounds, which stop short of the landing under them. */
                if (MapGenGeometryEdit_ReplacedFlight(plan, donor, i, slo, shi,
                                                      &rise))
                    printf("  edit %u  lift  %6.0f %6.0f %6.0f .. %6.0f %6.0f"
                           " %6.0f  rise %.0f\n", i,
                           (double)slo[0], (double)slo[1], (double)slo[2],
                           (double)shi[0], (double)shi[1], (double)shi[2],
                           (double)rise);
                else {
                    MapGenGeometryEdit_StairBounds(plan, e->target, slo, shi);
                    printf("  edit %u  stair %u stays a stair  %.0f %.0f %.0f"
                           " .. %.0f %.0f %.0f\n", i, e->target,
                           slo[0], slo[1], slo[2], shi[0], shi[1], shi[2]);
                }
                continue;
            }
            if (e->kind != MAPGEN_EDIT_PUSH_WALL)
                continue;
            float rlo[3] = { 0, 0, 0 }, rhi[3] = { 0, 0, 0 };
            MapGenGeometryEdit_RegionOf(plan, e->target, rlo, rhi);
            printf("  edit %u  push  %4d  region %.0f %.0f %.0f .."
                   " %.0f %.0f %.0f\n", i,
                   e->amount, rlo[0], rlo[1], rlo[2], rhi[0], rhi[1], rhi[2]);
        }
    }

    mapgen_geometry_t *candidate = NULL;
    if (MapGenGeometry_Clone(donor, &candidate) != MAPGEN_GEOMETRY_OK)
        return 2;

    if (do_hollow) {
        const mapgen_graft_result_t rc =
            models ? MapGenGraft_Hollow(candidate, lo, hi)
                   : MapGenGraft_HollowWorld(candidate, lo, hi);
        printf("hollow %s, %u brushes\n", MapGenGraft_ResultName(rc),
               MapGenGeometry_NumBrushes(candidate));
    }

    /*
     * EVERY `--apply`, in the order given.
     *
     * It took one. A demo map the PO walks carries several edits - `mg_glass`
     * is a doorway pane and a row of three on one clean donor - and a .map is
     * not something a second run can be chained onto, so "apply one edit and
     * write the map" could never build it. The edits are applied to the one
     * candidate in the order they were asked for, which is also the order the
     * schedule would have applied them in when they are given in ascending
     * order.
     */
    for (uint32_t k = 0; k < num_applies; k++) {
        bool changed = false;
        const mapgen_geometry_result_t rc =
            MapGenGeometryEdit_ApplyOne(plan, candidate, donor,
                                        applies[k], &changed);
        printf("apply %u: %s, changed %s, %u brushes\n", applies[k],
               MapGenGeometry_ResultName(rc), changed ? "yes" : "no",
               MapGenGeometry_NumBrushes(candidate));
        /* And, when it did nothing, WHY - in the operator's own words rather
           than as a silent "changed no". */
        if (!changed && MapGenGeometryEdit_WhyDeclined())
            printf("declined: %s\n", MapGenGeometryEdit_WhyDeclined());
    }
    if (num_applies) {
        /*
         * And what the transaction's surface gate will say about it.
         *
         * A candidate whose sides the compiler cannot build is refused
         * before it is ever compiled, and the count is against the DONOR's
         * own - an edit may not add to it. Printing it here is what turns
         * "the run rejected something" into "this edit adds N faults".
         */
        printf("faults %u, donor %u\n",
               MapGenGeometry_SurfaceFaults(candidate, bsp),
               MapGenGeometry_SurfaceFaults(donor, bsp));
    }

    /*
     * Where did the solid go?
     *
     * An operator that empties a bounded region is allowed to remove solid
     * INSIDE it and nowhere else. Every piece of every crossing brush that
     * lies outside the region has to be put back, and the suspicion this
     * answers is that some of them are not - that a clip calls a thin piece
     * degenerate and drops it, which takes a sliver out of a wall that seals
     * the map.
     *
     * So: every point on a sixteen-unit lattice over the donor's own bounds
     * that a donor brush covered and no candidate brush covers now. The
     * bounding box of what is reported is the answer - if it is the region,
     * the operator did what it said; if there are points outside it, they are
     * the hole.
     */
    if (do_lost) {
        /* The donor's own extent, from its brushes, because the geometry
           module does not publish one. */
        float mins[3] = { 1e9f, 1e9f, 1e9f }, maxs[3] = { -1e9f, -1e9f, -1e9f };
        for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(donor); b++) {
            const mapgen_geometry_brush_t *gb = MapGenGeometry_Brush(donor, b);
            if (!gb || gb->model)
                continue;
            for (int i = 0; i < 3; i++) {
                if (gb->mins[i] < mins[i]) mins[i] = gb->mins[i];
                if (gb->maxs[i] > maxs[i]) maxs[i] = gb->maxs[i];
            }
        }
        if (lost_boxed) {
            for (int i = 0; i < 3; i++) {
                mins[i] = lost_lo[i];
                maxs[i] = lost_hi[i];
            }
        }
        uint32_t lost = 0;
        float lo2[3] = { 0, 0, 0 }, hi2[3] = { 0, 0, 0 };
        for (float x = mins[0] + lost_step * 0.5f; x < maxs[0]; x += lost_step)
          for (float y = mins[1] + lost_step * 0.5f; y < maxs[1]; y += lost_step)
            for (float z = mins[2] + lost_step * 0.5f; z < maxs[2];
                 z += lost_step) {
                const float pt[3] = { x, y, z };
                if (!covered(donor, pt) || covered(candidate, pt))
                    continue;
                if (!lost) {
                    for (int i = 0; i < 3; i++)
                        lo2[i] = hi2[i] = pt[i];
                } else {
                    for (int i = 0; i < 3; i++) {
                        if (pt[i] < lo2[i]) lo2[i] = pt[i];
                        if (pt[i] > hi2[i]) hi2[i] = pt[i];
                    }
                }
                lost++;
            }
        printf("lost solid %u points, box %.0f %.0f %.0f .. %.0f %.0f %.0f\n",
               lost, lo2[0], lo2[1], lo2[2], hi2[0], hi2[1], hi2[2]);
    }

    /*
     * An entity that owns a brush model, with no brushes left in it.
     *
     * The engine answers that with "PF_setmodel: NULL" and refuses to spawn
     * the server. Nothing else sees it: the compiler builds the map, the
     * reachability gate walks it, the see-through oracle finds nothing, and
     * only the game says no. MEASURED on q2dm1 seed 3 at fidelity 90.
     */
    {
        uint32_t orphans = 0;
        for (uint32_t e = 0; e < MapGenGeometry_NumEntities(candidate); e++) {
            const mapgen_geometry_entity_t *ent =
                MapGenGeometry_Entity(candidate, e);
            if (!ent || !ent->model)
                continue;
            uint32_t owned = 0;
            for (uint32_t b = 0; b < MapGenGeometry_NumBrushes(candidate); b++) {
                const mapgen_geometry_brush_t *gb =
                    MapGenGeometry_Brush(candidate, b);
                if (gb && gb->model == ent->model)
                    owned++;
            }
            if (!owned) {
                printf("orphan entity %u, model %u\n", e, ent->model);
                orphans++;
            }
        }
        printf("orphan brush entities %u\n", orphans);
    }

    {
        char who[128] = "";
        const uint32_t wet =
            MapGenGeometry_DrownedEntities(candidate, false, who, sizeof(who));
        printf("candidate drowned %u%s%s\n", wet, wet ? ": " : "", who);
    }

    {
        uint32_t faults = MapGenGeometry_SurfaceFaults(candidate, bsp);
        printf("surface faults %u\n", faults);
    }
    /* row 354: the applied digs that wore a sky skin */
    printf("sky skins %u\n", MapGenGeometryEdit_SkySkins());
    printf("skin rock refusals %u\n", MapGenGeometryEdit_SkinRockRefusals());
    /* row 384: the courtyards' skies lifted, and what each laid */
    printf("sky lifts %u, floor brushes %u, clip brushes %u, sky slabs %u\n",
           MapGenGeometryEdit_SkyLifts(), MapGenGeometryEdit_SkyLiftFloorBrushes(),
           MapGenGeometryEdit_SkyLiftClipBrushes(), MapGenGeometryEdit_SkyLiftSkyBrushes());
    if (MapGenGeometryEdit_SkyLifts())
        printf("sky lift: %s\n", MapGenGeometryEdit_SkyLiftSaid());
    /* row 369: whether these points lie in a skinned dig's gap, as the
       transaction's crack rule asks it */
    for (uint32_t i = 0; i < num_gapat; i++)
        printf("in skin gap %.0f %.0f %.0f: %d\n", (double)gapat[i][0],
               (double)gapat[i][1], (double)gapat[i][2],
               MapGenGeometryEdit_InSkinGap(candidate, gapat[i]) ? 1 : 0);

    if (out) {
        if (MapGenGeometry_WriteValve220(candidate, out)
            != MAPGEN_GEOMETRY_OK) {
            fprintf(stderr, "cannot write %s\n", out);
            return 2;
        }
        printf("wrote %s\n", out);
    }
    return 0;
}
