/*
Copyright (C) 2026 Q2PRO-X

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
*/

/*
==============================================================================

MAPGEN-1 - MapGenWiring: the target/targetname graph

Contract section 5.4 ("target/targetname, mover, key, door, trigger, train and
progression graphs") and 18.4.

--- Built from what the corpus actually contains -----------------------------

Measured over the 132 shipped maps, 21 622 entities, 94 distinct classnames:

  targetname   1013     target       997      team         71
  pathtarget      3     killtarget     1      combattarget  0

so `combattarget`, `deathtarget` and `movewith` are carried by nothing here and
are not invented. Three facts about the data shape this interface:

  * a link is ONE-TO-MANY. 77 targetnames in the corpus are shared by more than
    one entity, and a `target` naming such a name fires all of them;

  * links dangle. 46 `target` values and one `pathtarget` name nothing at all
    in their own map. A dangling link is RECORDED, with the name it wanted,
    rather than dropped - "this map has 3 targets that go nowhere" is a fact
    about the map, and silently discarding them would hide it;

  * cycles are legal. A `func_train` walking a ring of `path_corner`s is a
    cycle by design, so a cycle is counted, never refused.

--- Classnames are not texture names ----------------------------------------

Contract 7.7 forbids deciding what a surface IS from what it is CALLED, and
`MapGenome` obeys it. This layer does classify by classname, because a
classname is not a filename: it is the semantic label the entity format itself
defines, and it is what the game's own spawn table keys on. The distinction is
deliberate - an exact table first, and family prefixes only for the long tail.

==============================================================================
*/

#pragma once

#include "common/mapgen_genome.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Roles. A set rather than a label: `func_water` is a mover and a liquid,
   `misc_teleporter` is a teleporter and a brush model. */
/*
 * What an ENTITY is. Not what a material is used as - those are the
 * MAPGEN_ROLE_ bits in mapgen_genome.h, a different set over the same low
 * bit positions. They shared a prefix once, and asking the mixed model
 * about MAPGEN_ROLE_WATER silently answered about coop spawns.
 */
#define MAPGEN_ENTROLE_SPAWN_DM        0x00000001u
#define MAPGEN_ENTROLE_SPAWN_SP        0x00000002u
#define MAPGEN_ENTROLE_SPAWN_COOP      0x00000004u
#define MAPGEN_ENTROLE_INTERMISSION    0x00000008u
#define MAPGEN_ENTROLE_WEAPON          0x00000010u
#define MAPGEN_ENTROLE_AMMO            0x00000020u
#define MAPGEN_ENTROLE_ARMOR           0x00000040u
#define MAPGEN_ENTROLE_HEALTH          0x00000080u
#define MAPGEN_ENTROLE_POWERUP         0x00000100u
#define MAPGEN_ENTROLE_ITEM            0x00000200u  /* any pickup at all        */
#define MAPGEN_ENTROLE_MONSTER         0x00000400u
#define MAPGEN_ENTROLE_DOOR            0x00000800u
#define MAPGEN_ENTROLE_PLAT            0x00001000u
#define MAPGEN_ENTROLE_TRAIN           0x00002000u
#define MAPGEN_ENTROLE_BUTTON          0x00004000u
#define MAPGEN_ENTROLE_ROTATING        0x00008000u
#define MAPGEN_ENTROLE_MOVER           0x00010000u  /* any of the five above    */
#define MAPGEN_ENTROLE_TELEPORTER      0x00020000u
#define MAPGEN_ENTROLE_TELEPORT_DEST   0x00040000u
#define MAPGEN_ENTROLE_PUSH            0x00080000u
#define MAPGEN_ENTROLE_TRIGGER         0x00100000u
#define MAPGEN_ENTROLE_HAZARD          0x00200000u
#define MAPGEN_ENTROLE_PATH            0x00400000u
#define MAPGEN_ENTROLE_TIMER           0x00800000u
#define MAPGEN_ENTROLE_MARKER          0x01000000u
/* An entity that lights - not MAPGEN_ROLE_LIGHT, which is a SURFACE that
   emits. The two sets share this word and nothing else. */
#define MAPGEN_ENTROLE_LIGHT           0x02000000u
#define MAPGEN_ENTROLE_SOUND           0x04000000u
#define MAPGEN_ENTROLE_DECOR           0x08000000u
#define MAPGEN_ENTROLE_WORLDSPAWN      0x10000000u
#define MAPGEN_ENTROLE_AREAPORTAL      0x20000000u
#define MAPGEN_ENTROLE_CHANGELEVEL     0x40000000u
/* `func_group` is an editor construct that should never survive compilation,
   and 770 of them did, in 9 maps. Named so the fact stays visible. */
#define MAPGEN_ENTROLE_EDITOR_LEFTOVER 0x80000000u

typedef enum {
    MAPGEN_LINK_TARGET = 0,
    MAPGEN_LINK_KILLTARGET,
    MAPGEN_LINK_PATHTARGET,
    MAPGEN_LINK_KIND_COUNT,
} mapgen_link_kind_t;

const char *MapGenWiring_LinkKindName(mapgen_link_kind_t kind);
const char *MapGenWiring_LinkKindKey(mapgen_link_kind_t kind);

/* How many roles one entity may report by name. */
#define MAPGEN_WIRING_MAX_ROLE_NAMES  8
#define MAPGEN_WIRING_NAME_BYTES      MAPGEN_GENOME_KEY_BYTES

#define MAPGEN_WIRING_MAX_LINKS       (1u << 20)
#define MAPGEN_WIRING_MAX_DANGLING    (1u << 16)

typedef struct {
    uint32_t roles;
    /* Brush model index from a `model` value of "*N", or -1 for a point
       entity. Validated against the document's model count, because the value
       comes out of a file we did not write. */
    int32_t  submodel;
    uint32_t out_links;
    uint32_t in_links;
    /* Index of the `team` group, or UINT32_MAX. Doors that open together
       share one. */
    uint32_t team;
    bool     on_cycle;
} mapgen_wiring_entity_t;

typedef struct {
    uint32_t from;
    uint32_t to;
    uint8_t  kind;
} mapgen_wiring_link_t;

typedef struct {
    uint32_t from;
    uint8_t  kind;
    char     name[MAPGEN_WIRING_NAME_BYTES];
} mapgen_wiring_dangling_t;

typedef enum {
    MAPGEN_WIRING_OK = 0,
    MAPGEN_WIRING_ERR_ARGS,
    MAPGEN_WIRING_ERR_MEMORY,
    MAPGEN_WIRING_ERR_TOO_MANY_LINKS,
} mapgen_wiring_result_t;

const char *MapGenWiring_ResultName(mapgen_wiring_result_t r);

typedef struct mapgen_wiring_s mapgen_wiring_t;

/*
 * Build the link graph from an extracted genome.
 *
 * `bsp` is used for one thing only - checking that a `model` of "*N" names a
 * submodel that exists - and may be NULL, in which case submodel indices are
 * recorded but not validated.
 */
mapgen_wiring_result_t MapGenWiring_Build(const mapgen_genome_t *genome,
                                          const mapgen_bsp_t *bsp,
                                          mapgen_wiring_t **out);
void MapGenWiring_Free(mapgen_wiring_t *w);

uint32_t MapGenWiring_NumEntities(const mapgen_wiring_t *w);
uint32_t MapGenWiring_NumLinks(const mapgen_wiring_t *w);
uint32_t MapGenWiring_NumDangling(const mapgen_wiring_t *w);
uint32_t MapGenWiring_NumTeams(const mapgen_wiring_t *w);
uint32_t MapGenWiring_NumSharedNames(const mapgen_wiring_t *w);
uint32_t MapGenWiring_NumOnCycle(const mapgen_wiring_t *w);
uint32_t MapGenWiring_NumBadSubmodels(const mapgen_wiring_t *w);

const mapgen_wiring_entity_t   *MapGenWiring_Entity(const mapgen_wiring_t *w, uint32_t i);
const mapgen_wiring_link_t     *MapGenWiring_Link(const mapgen_wiring_t *w, uint32_t i);
const mapgen_wiring_dangling_t *MapGenWiring_Dangling(const mapgen_wiring_t *w, uint32_t i);

/* How many entities carry every bit in `roles`. */
uint32_t MapGenWiring_CountRole(const mapgen_wiring_t *w, uint32_t roles);

/* Classify one classname. Exposed so the classification can be tested on
   names the corpus does not happen to contain. */
uint32_t MapGenWiring_RolesForClassname(const char *classname);

/* Names for a role set, for reports and canonical text. Returns how many were
   written, at most `capacity`. */
uint32_t MapGenWiring_RoleNames(uint32_t roles, const char **out, uint32_t capacity);

size_t   MapGenWiring_CanonicalText(const mapgen_wiring_t *w, char *out, size_t capacity);
uint64_t MapGenWiring_CanonicalDigest(const mapgen_wiring_t *w);
