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

MAPGEN-1 - MapGenome, layer 1: materials and entities

The typed intermediate representation Training extracts from one compiled BSP.
This layer covers what the map is MADE of - its material vocabulary and its
entity population - and it is deliberately separate from the spatial and
traversal grammar, which needs collision tracing and arrives next.

--- The rule that shapes the whole material model ---------------------------

Contract section 7.7: **never classify only from a filename substring.**

A texture called `e1u1/water4` may be a decorative wall, and a texture called
`e1u1/floor3_3` may be the surface of a lava pit. What a surface IS lives in
its compiled `SURF_*` flags and in the `CONTENTS_*` of the brushes that use
it - so that is the only thing this reads. Names are recorded as provenance
and as the allowlist key (contract section 15), never as evidence.

That is also why a role is a SET, not a single label: one texture can be
`CONTENTS_WATER` on one brush and a plain solid on another, and flattening
that would lose the fact the generator needs.

--- Untrusted input ---------------------------------------------------------

The entity string comes out of a file we did not write. It is parsed strictly
and boundedly: an unterminated block, a key without a value or a stray token is
an ERROR, not something to guess past, and every count and length is capped
before anything is stored.

==============================================================================
*/

#pragma once

#include "common/mapgen_bsp.h"

#include <stdbool.h>
#include <stdint.h>

/* Quake II's content flags come with mapgen_bsp.h, included above. */

/* Surface flags. */
#define MAPGEN_SURF_LIGHT             0x0001
#define MAPGEN_SURF_SLICK             0x0002
#define MAPGEN_SURF_SKY               0x0004
#define MAPGEN_SURF_WARP              0x0008
#define MAPGEN_SURF_TRANS33           0x0010
#define MAPGEN_SURF_TRANS66           0x0020
#define MAPGEN_SURF_FLOWING           0x0040
#define MAPGEN_SURF_NODRAW            0x0080
#define MAPGEN_SURF_HINT              0x0100
#define MAPGEN_SURF_SKIP              0x0200

/*
 * Roles a material can play. A material may hold SEVERAL at once: the same
 * texture can be water on one brush and plain solid on another, and losing
 * that would lose the fact the generator needs.
 */
/*
 * What a MATERIAL was used as. The entity roles in mapgen_wiring.h are a
 * different set - MAPGEN_ENTROLE_ - over the same low bit positions.
 */
typedef enum {
    MAPGEN_ROLE_SOLID       = 1u << 0,
    MAPGEN_ROLE_SKY         = 1u << 1,
    MAPGEN_ROLE_WATER       = 1u << 2,
    MAPGEN_ROLE_LAVA        = 1u << 3,
    MAPGEN_ROLE_SLIME       = 1u << 4,
    MAPGEN_ROLE_MIST        = 1u << 5,
    MAPGEN_ROLE_CLIP        = 1u << 6,   /* player or monster clip           */
    MAPGEN_ROLE_TRANSLUCENT = 1u << 7,
    MAPGEN_ROLE_NODRAW      = 1u << 8,   /* hint, skip and nodraw           */
    MAPGEN_ROLE_LIGHT       = 1u << 9,   /* a surface that emits            */
    MAPGEN_ROLE_FLOWING     = 1u << 10,
    MAPGEN_ROLE_ANIMATED    = 1u << 11,  /* part of a nexttexinfo chain     */
    MAPGEN_ROLE_LADDER      = 1u << 12
} mapgen_role_t;

#define MAPGEN_GENOME_MAX_MATERIALS   4096
#define MAPGEN_GENOME_MAX_ENTITIES    16384
#define MAPGEN_GENOME_MAX_KEYS        32
/*
 * These two are the FORMAT's own limits from inc/format/bsp.h - MAX_KEY 32 and
 * MAX_VALUE 1024 - not numbers chosen for comfort.
 *
 * The first version used 256 for a value and refused `urbanjungle.bsp`, a real
 * shipped map whose worldspawn carries a 999-character `_tb_textures` list
 * written by TrenchBroom. A cap tighter than the format rejects legitimate
 * content, and the map is not wrong for using the room the format gives it.
 */
#define MAPGEN_GENOME_KEY_BYTES       64
#define MAPGEN_GENOME_VALUE_BYTES     1024
#define MAPGEN_GENOME_MAX_CLASSNAMES  512

typedef struct {
    char     name[MAPGEN_BSP_TEXNAME + 1];
    /* Every SURF_* bit ever seen on a texinfo naming this material. */
    int32_t  surface_flags;
    /* Every CONTENTS_* bit ever seen on a brush whose side names it. */
    int32_t  contents;
    /*
     * The brightest a SURF_LIGHT texinfo naming this material was used at.
     *
     * The .wal usually says 0 and the MAP says how bright this fitting is, so
     * a generator that omits the value gets an emitting surface that emits
     * nothing. The brightest rather than the last, because a texture used as a
     * 10000 ceiling panel in one place and a 200 trim in another is capable of
     * both and the panel is what it is for.
     */
    int32_t  light_value;
    uint32_t roles;
    uint32_t texinfo_refs;
    uint32_t brushside_refs;
    uint32_t face_refs;
} mapgen_material_t;

typedef struct {
    char key[MAPGEN_GENOME_KEY_BYTES];
    char value[MAPGEN_GENOME_VALUE_BYTES];
} mapgen_kv_t;

typedef struct {
    char        classname[MAPGEN_GENOME_KEY_BYTES];
    bool        has_origin;
    float       origin[3];
    uint32_t    num_keys;
    mapgen_kv_t keys[MAPGEN_GENOME_MAX_KEYS];
} mapgen_entity_t;

typedef enum {
    MAPGEN_GENOME_OK = 0,
    MAPGEN_GENOME_ERR_ARGUMENT,
    MAPGEN_GENOME_ERR_OUT_OF_MEMORY,
    MAPGEN_GENOME_ERR_TOO_MANY_MATERIALS,
    MAPGEN_GENOME_ERR_TOO_MANY_ENTITIES,
    MAPGEN_GENOME_ERR_ENTITY_SYNTAX,
    MAPGEN_GENOME_ERR_ENTITY_TOO_LONG,

    MAPGEN_GENOME_RESULT_COUNT
} mapgen_genome_result_t;

typedef struct mapgen_genome_s mapgen_genome_t;

/* Extract from an already-validated document. The genome copies what it needs
   and does not reference `bsp` afterwards. */
mapgen_genome_result_t MapGenGenome_Extract(const mapgen_bsp_t *bsp, mapgen_genome_t **out);
void MapGenGenome_Free(mapgen_genome_t *genome);

uint32_t MapGenGenome_NumMaterials(const mapgen_genome_t *g);
const mapgen_material_t *MapGenGenome_Material(const mapgen_genome_t *g, uint32_t i);
/* Look up by exact name. NULL when absent - never a fuzzy match. */
const mapgen_material_t *MapGenGenome_FindMaterial(const mapgen_genome_t *g, const char *name);

uint32_t MapGenGenome_NumEntities(const mapgen_genome_t *g);
const mapgen_entity_t *MapGenGenome_Entity(const mapgen_genome_t *g, uint32_t i);
/* How many entities carry this exact classname. */
uint32_t MapGenGenome_CountClassname(const mapgen_genome_t *g, const char *classname);
/* Exact key lookup on one entity; NULL when the key is absent. */
const char *MapGenGenome_EntityValue(const mapgen_entity_t *ent, const char *key);

/* World bounds taken from model 0. */
void MapGenGenome_WorldBounds(const mapgen_genome_t *g, float mins[3], float maxs[3]);

/*
 * A deterministic per-map digest of everything this layer extracted.
 *
 * Same map, same digest, on any machine and in any locale (contract section
 * 10): materials are emitted in sorted name order rather than in the order
 * the texinfo lump happened to mention them, and floats go through the same
 * locale-free rendering as the document's.
 */
uint64_t MapGenGenome_Digest(const mapgen_genome_t *g);
size_t   MapGenGenome_CanonicalText(const mapgen_genome_t *g, char *out, size_t capacity);

const char *MapGenGenome_ResultName(mapgen_genome_result_t result);
/* Role names, for reports and tests. Returns the number written. */
uint32_t MapGenGenome_RoleNames(uint32_t roles, const char **out, uint32_t capacity);
