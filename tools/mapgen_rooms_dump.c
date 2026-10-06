/*
 * What rooms a map has, how they connect, and how much rock is behind each of
 * their walls.
 *
 * A segmentation nobody has looked at is a segmentation nobody should build an
 * operator on: this prints it against maps whose rooms are known, so "seventeen
 * rooms" can be checked against a level people have played for thirty years
 * rather than believed.
 *
 *     mapgen_rooms_dump <map.bsp> [min clearance] [--push]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_rooms.h"

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <map.bsp> [min clearance] [persistence] [--push]\n",
                argv[0]);
        return 2;
    }
    float clearance = 64.0f;
    float persistence = MAPGEN_ROOMS_PERSISTENCE;
    bool push = false;
    int positional = 0;
    for (int a = 2; a < argc; a++) {
        if (!strcmp(argv[a], "--push"))
            push = true;
        else if (positional++ == 0)
            clearance = (float)atof(argv[a]);
        else
            persistence = (float)atof(argv[a]);
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

    mapgen_rooms_t *rooms = NULL;
    const mapgen_rooms_result_t rc = MapGenRooms_Find(bsp, clearance, persistence, &rooms);
    MapGenBsp_Free(bsp);
    if (rc != MAPGEN_ROOMS_OK) {
        printf("%s: %s\n", argv[1], MapGenRooms_ResultName(rc));
        return 1;
    }

    {
        uint32_t hist[24];
        memset(hist, 0, sizeof(hist));
        uint32_t total = MapGenRooms_ClearanceHistogram(rooms, hist, 24);
        printf("clearance, in cells, over %u open cells:", total);
        for (uint32_t i = 0; i < 24; i++)
            if (hist[i])
                printf("  %u:%u", i, hist[i]);
        printf("\n");
    }
    const uint32_t count = MapGenRooms_Count(rooms);
    printf("%s: %u rooms, %u ways between them  (digest %016llx)\n", argv[1],
           count, MapGenRooms_NumLinks(rooms),
           (unsigned long long)MapGenRooms_Digest(rooms));

    static const char *AXIS = "xyz";
    for (uint32_t i = 0; i < count; i++) {
        const mapgen_room_t *room = MapGenRooms_Room(rooms, i);
        printf("  %3u  %6.0f %6.0f %6.0f .. %6.0f %6.0f %6.0f"
               "  %5u cells  widest %4.0f  %u ways  %u items  %u starts\n", i,
               (double)room->mins[0], (double)room->mins[1],
               (double)room->mins[2], (double)room->maxs[0],
               (double)room->maxs[1], (double)room->maxs[2], room->cells,
               (double)room->clearance, room->links, room->items,
               room->spawns);
        if (push) {
            printf("       rock behind:");
            for (int axis = 0; axis < 3; axis++) {
                for (int sign = -1; sign <= 1; sign += 2) {
                    const float d = MapGenRooms_PushRoom(rooms, i, axis, sign);
                    printf("  %c%c %.0f", sign < 0 ? '-' : '+', AXIS[axis],
                           (double)d);
                }
            }
            printf("\n");
        }
    }

    const uint32_t links = MapGenRooms_NumLinks(rooms);
    for (uint32_t i = 0; i < links; i++) {
        const mapgen_room_link_t *l = MapGenRooms_Link(rooms, i);
        printf("  %3u -> %3u  at %6.0f %6.0f %6.0f  %.0f units wide\n",
               l->a, l->b, (double)l->at[0], (double)l->at[1],
               (double)l->at[2], (double)l->width);
    }

    MapGenRooms_Free(rooms);
    return 0;
}
