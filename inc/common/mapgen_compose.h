/*
 * An invented map COMPOSED of rooms that were built, not synthesised out of
 * boxes on a grid.
 *
 * "бессмыслененность этого 'творения' продолжается ... я же говорил что хочу
 * получить красивый воздушный открытый уровень, впечатления по которому даёт
 * q2dm1, а не это коридорное не пойми что ... нужен полный пересмотр
 * генерации таких карт как эта" - the PO, 2026-09-07, on the third invented
 * map in a row.
 *
 * He is right, and the reason is structural rather than a constant that wants
 * tuning. `mapgen_layout.c` puts one axis-aligned room in each 1536-unit cell
 * of a grid, on one band, with corridors between them; whatever the sky share
 * and the wall height are set to, the result is a box on a grid with tubes
 * between it. MEASURED on the map he was looking at: three flat pans over
 * three courtyards, a spread of 256 units, eleven wall planes to a box, and
 * a footprint of 3200 by 5184 where q2dm1's is 2496 by 2272.
 *
 * The corpus already holds the thing that is missing. q2dm8's room 34 is
 * 1216 by 896 by 608 with 404 brushes, three storeys of floor and 924 places
 * a player can stand; q2dm2's room 3 is 608 by 800 by 928 with 110 distinct
 * wall planes. Those are ledges, walkways, buttresses and stairs that a
 * designer built, and the survey can lift them out whole. So the invented map
 * is one of them for its main volume, three or four more from OTHER donors
 * around it as pockets, short generated ways between them, and a shell
 * generated around the whole from the air the rooms actually enclose.
 *
 * What is NOT here: the box synthesis. It is still in the tree - the shell
 * and the connector builder need it - but a composed map that cannot meet
 * `check_mapgen_arena_shape.py` is not handed over, and the F0 slot in a
 * batch stays empty instead.
 */

#ifndef MAPGEN_COMPOSE_H
#define MAPGEN_COMPOSE_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_geometry.h"

struct mapgen_bundle_s;

typedef enum {
    MAPGEN_COMPOSE_OK = 0,
    MAPGEN_COMPOSE_ERR_ARGS,
    MAPGEN_COMPOSE_ERR_MEMORY,
    MAPGEN_COMPOSE_ERR_DONOR,     /* a reference map would not read        */
    MAPGEN_COMPOSE_ERR_STOCK,     /* nothing in the corpus is an arena     */
    MAPGEN_COMPOSE_ERR_BUILD,     /* the pieces would not go together      */
    MAPGEN_COMPOSE_RESULT_COUNT
} mapgen_compose_result_t;

const char *MapGenCompose_ResultName(mapgen_compose_result_t r);

#define MAPGEN_COMPOSE_MAX_DONORS 8u
#define MAPGEN_COMPOSE_MAX_PARTS  8u
#define MAPGEN_COMPOSE_NAME       64u

/* One room the map is made of, and where it landed. */
typedef struct {
    char     donor[MAPGEN_COMPOSE_NAME];
    uint32_t room;
    uint32_t quarter_turns;
    bool     mirror_x;
    float    mins[3];
    float    maxs[3];
    uint32_t brushes;
    bool     main;
} mapgen_compose_part_t;

typedef struct {
    uint32_t              num_parts;
    mapgen_compose_part_t part[MAPGEN_COMPOSE_MAX_PARTS];
    uint32_t              connectors;
    uint32_t              shell_brushes;
    uint32_t              sky_brushes;
    uint32_t              spawns;
    float                 footprint[2];
    float                 sky_z;
} mapgen_compose_report_t;

/*
 * Can this room be carried at all?
 *
 * A brush model is a machine - a lift, a door - and the entity that owns it
 * refers to it by NUMBER, so carrying one into a map whose models are
 * numbered differently is how a lift becomes a wall somewhere else. A trigger
 * is the same problem one step removed. The composer will not take either,
 * and the stock probe prints the answer so the catalogue can be read.
 */
bool MapGenCompose_Carriable(const mapgen_geometry_t *geometry,
                             const struct mapgen_bundle_s *bundle);

/*
 * Build one, from the reference maps and a seed.
 *
 * The donors are compiled BSPs; the first is not special. Everything the
 * caller gets back is a geometry it owns and must free, ready to be written
 * with `MapGenGeometry_WriteValve220` and compiled like any other candidate.
 */
mapgen_compose_result_t MapGenCompose_Build(const char *const *donors,
                                            uint32_t num_donors,
                                            uint64_t seed,
                                            mapgen_geometry_t **out,
                                            mapgen_compose_report_t *report);

#endif /* MAPGEN_COMPOSE_H */
