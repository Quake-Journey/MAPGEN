/*
 * Every bundle of a compiled map, and whether it is sealed.
 *
 * The number to read first is how many of the rooms come out sealed: an
 * unsealed bundle is one no structural operator may touch, so that fraction is
 * the size of the map this generator is allowed to work on.
 *
 *     mapgen_bundle_dump <map.bsp> [room]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bundle.h"

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

static void report(const mapgen_bundle_t *b, bool verbose)
{
    printf("room %3u  %-7s %-7s air %5u shell %5u  blind %4u "
           "undecl %3u unowned %4u nook %4u  brushes %3u (b%u s%u c%u m%u) "
           "sock %2u anch %2u surf %3u  %016llx\n",
           MapGenBundle_Room(b),
           MapGenBundle_Sealed(b) ? "sealed" : "OPEN",
           MapGenBundle_Movable(b) ? "movable" : "fixed",
           MapGenBundle_AirCells(b), MapGenBundle_ShellCells(b),
           MapGenBundle_BlindCells(b),
           MapGenBundle_Undeclared(b), MapGenBundle_UnownedSolid(b),
           MapGenBundle_NookCells(b),
           MapGenBundle_NumBrushes(b),
           MapGenBundle_RoleCount(b, MAPGEN_BUNDLE_ROLE_BOUNDARY),
           MapGenBundle_RoleCount(b, MAPGEN_BUNDLE_ROLE_SUPPORT),
           MapGenBundle_RoleCount(b, MAPGEN_BUNDLE_ROLE_CLIP),
           MapGenBundle_RoleCount(b, MAPGEN_BUNDLE_ROLE_MOVER),
           MapGenBundle_NumSockets(b), MapGenBundle_NumAnchors(b),
           MapGenBundle_NumSurfaces(b),
           (unsigned long long)MapGenBundle_Digest(b));
    /*
     * And, whenever the seal is not all ours, WHERE.
     *
     * "part of the seal is no brush" was a count and a count cannot be
     * argued with: it refused eleven of q2dm1's seventeen rooms, one of them
     * on a single cell, and the only way to tell a thin wall the measurement
     * walked past from the world outside the map is to print the place and go
     * and look at it.
     */
    if (MapGenBundle_UnownedSolid(b) || MapGenBundle_SealByMover(b))
        printf("    seal: %u unowned - %u the world outside lying against"
               " the room, %u at a cell corner away from it, %u unreached;"
               " %u cells closed by a mover\n",
               MapGenBundle_UnownedSolid(b),
               MapGenBundle_UnownedExterior(b),
               MapGenBundle_UnownedCorner(b),
               MapGenBundle_UnownedUnreached(b),
               MapGenBundle_SealByMover(b));
    for (uint32_t i = 0; i < MapGenBundle_NumUnownedWitness(b); i++) {
        const mapgen_bundle_witness_t *w = MapGenBundle_UnownedWitness(b, i);
        printf("      witness %u: air %.0f %.0f %.0f -> %s %.0f %.0f %.0f\n", i,
               (double)w->air[0], (double)w->air[1], (double)w->air[2],
               w->entered ? "solid at" : "cell centre",
               (double)w->solid[0], (double)w->solid[1], (double)w->solid[2]);
    }

    if (!verbose)
        return;

    for (uint32_t i = 0; i < MapGenBundle_NumSockets(b); i++) {
        const mapgen_socket_t *s = MapGenBundle_Socket(b, i);
        printf("    socket %-8s -> room %-3u width %6.1f cells %4u"
               " at %.0f %.0f %.0f %s\n",
               MapGenBundle_SocketName(s->kind), s->peer, (double)s->width,
               s->cells, (double)s->at[0], (double)s->at[1], (double)s->at[2],
               s->obligation ? "OBLIGED" : "free");
    }
    for (uint32_t i = 0; i < MapGenBundle_NumAnchors(b); i++) {
        const mapgen_bundle_anchor_t *a = MapGenBundle_Anchor(b, i);
        printf("    anchor %-8s entity %-4u %s\n",
               MapGenBundle_AnchorName(a->kind), a->entity,
               a->inside ? "inside" : "tied in");
    }
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp> [room | -v]\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    mapgen_geometry_t *geometry = NULL;
    if (MapGenGeometry_FromBsp(bsp, &geometry) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot read its brushes\n");
        return 2;
    }
    mapgen_rooms_t *rooms = NULL;
    if (MapGenRooms_Find(bsp, 64.0f, MAPGEN_ROOMS_PERSISTENCE, &rooms)
        != MAPGEN_ROOMS_OK) {
        fprintf(stderr, "cannot segment it\n");
        return 2;
    }

    mapgen_bundle_set_t *set = NULL;
    const mapgen_bundle_result_t rc =
        MapGenBundle_Survey(bsp, geometry, rooms, &set);
    if (rc != MAPGEN_BUNDLE_OK) {
        fprintf(stderr, "%s\n", MapGenBundle_ResultName(rc));
        return 2;
    }

    const uint32_t count = MapGenBundleSet_Count(set);
    const bool all = argc > 2 && !strcmp(argv[2], "-v");
    const bool one = argc > 2 && !all;
    const uint32_t first = one ? (uint32_t)strtoul(argv[2], NULL, 10) : 0;
    const uint32_t last = one ? first + 1 : count;

    printf("%u rooms, %u pockets of unowned space\n", count,
           MapGenBundleSet_Pockets(set));
    uint32_t sealed = 0, movable = 0, obliged = 0;
    for (uint32_t r = first; r < last && r < count; r++) {
        const mapgen_bundle_t *bundle = MapGenBundleSet_At(set, r);
        if (!bundle)
            continue;
        if (MapGenBundle_Sealed(bundle))
            sealed++;
        if (MapGenBundle_Movable(bundle))
            movable++;
        for (uint32_t i = 0; i < MapGenBundle_NumSockets(bundle); i++)
            if (MapGenBundle_Socket(bundle, i)->obligation)
                obliged++;
        report(bundle, one || all);
    }
    printf("\n%u of %u extracted, %u sealed, %u movable, %u obliged sockets\n",
           count, count, sealed, movable, obliged);

    MapGenBundleSet_Free(set);
    MapGenRooms_Free(rooms);
    MapGenGeometry_Free(geometry);
    MapGenBsp_Free(bsp);
    return 0;
}
