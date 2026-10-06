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

MAPGEN-1 - BspDocument, the headless BSP reader

A strict, self-contained IBSP/QBSP v38 reader that the worker owns. It shares
no state with the engine loader and is not conditioned on `USE_REF`.

--- Why not just use bsp_t ------------------------------------------------

Because `bsp_t` cannot carry what the worker needs in the build the worker
runs in. In `inc/common/bsp.h` the faces, leaffaces, vertices, edges,
surfedges, lightmap and lightgrid all live inside `#if USE_REF`, and
`mtexinfo_t` keeps its texture AXES there too - while the material name sits
behind `USE_CLIENT`. A headless worker built without the renderer would lose
exactly the geometry and surface mapping that Training reads.

The Codex activation review of 2026-08-31 put it plainly: the `USE_REF=0` form
of `bsp_t` is not a geometry oracle, and a renderer-conditioned struct can be
neither the worker's persistence schema nor its IPC schema. So this document
parses the on-disk lumps into its own types, and its correctness is a result
to be proven rather than inherited.

Also: `BSP_Load` uses a global cache, a reference count, Zone/Hunk allocation
and intrusive lists, with no concurrent API and no synchronization contract.
Training parses many maps at once. This document owns ONE arena per load and
touches nothing global.

--- Strictness ------------------------------------------------------------

BSPs are UNTRUSTED input (contract section 2). Every count, offset, size and
index is validated before it is used, limits are imposed BEFORE allocation,
and the reader returns a stable error code rather than trusting anything the
file claims about itself.

==============================================================================
*/

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_BSP_IDENT_IBSP   0x50534249u  /* 'IBSP' */
#define MAPGEN_BSP_IDENT_QBSP   0x50534251u  /* 'QBSP' */
#define MAPGEN_BSP_VERSION      38
/* Quake II content flags, from inc/format/bsp.h.
   Here rather than in one of the modules because several of them need the
   same numbers, and two headers with their own copy is how the two copies
   stop agreeing. */
#define MAPGEN_CONTENTS_SOLID         0x00000001
#define MAPGEN_CONTENTS_WINDOW        0x00000002
#define MAPGEN_CONTENTS_AUX           0x00000004
#define MAPGEN_CONTENTS_LAVA          0x00000008
#define MAPGEN_CONTENTS_SLIME         0x00000010
#define MAPGEN_CONTENTS_WATER         0x00000020
#define MAPGEN_CONTENTS_MIST          0x00000040
#define MAPGEN_CONTENTS_AREAPORTAL    0x00008000
#define MAPGEN_CONTENTS_PLAYERCLIP    0x00010000
#define MAPGEN_CONTENTS_MONSTERCLIP   0x00020000
#define MAPGEN_CONTENTS_ORIGIN        0x01000000
#define MAPGEN_CONTENTS_DETAIL        0x08000000
#define MAPGEN_CONTENTS_TRANSLUCENT   0x10000000
#define MAPGEN_CONTENTS_LADDER        0x20000000

#define MAPGEN_BSP_LUMPS        19
#define MAPGEN_BSP_TEXNAME      32

/* Ceilings checked BEFORE allocation. They are the extended-format limits, so
   a legitimate QBSP map fits and a file claiming more is refused rather than
   believed. A hostile header is only ever an error, never an allocation. */
#define MAPGEN_BSP_MAX_FILE_BYTES   (512u * 1024u * 1024u)
#define MAPGEN_BSP_MAX_PLANES       1048576u
#define MAPGEN_BSP_MAX_NODES        1048576u
#define MAPGEN_BSP_MAX_LEAFS        1048576u
#define MAPGEN_BSP_MAX_LEAFBRUSHES  1048576u
#define MAPGEN_BSP_MAX_LEAFFACES    1048576u
#define MAPGEN_BSP_MAX_BRUSHES      1048576u
#define MAPGEN_BSP_MAX_BRUSHSIDES   4194304u
#define MAPGEN_BSP_MAX_TEXINFO      1048576u
#define MAPGEN_BSP_MAX_MODELS       131072u
#define MAPGEN_BSP_MAX_VERTICES     4194304u
#define MAPGEN_BSP_MAX_EDGES        4194304u
#define MAPGEN_BSP_MAX_SURFEDGES    8388608u
#define MAPGEN_BSP_MAX_FACES        1048576u
#define MAPGEN_BSP_MAX_ENTCHARS     (8u * 1024u * 1024u)
/* Never raised, never bypassed, including for QBSP output: this one is
   network-visible (contract section 18.1). */
#define MAPGEN_BSP_MAX_AREAS        256u
#define MAPGEN_BSP_MAX_AREAPORTALS  4096u

typedef enum {
    MAPGEN_BSP_OK = 0,

    MAPGEN_BSP_ERR_ARGUMENT,
    MAPGEN_BSP_ERR_TOO_SMALL,
    MAPGEN_BSP_ERR_TOO_LARGE,
    MAPGEN_BSP_ERR_BAD_IDENT,
    MAPGEN_BSP_ERR_BAD_VERSION,
    MAPGEN_BSP_ERR_LUMP_OUT_OF_BOUNDS,
    MAPGEN_BSP_ERR_LUMP_ODD_SIZE,
    MAPGEN_BSP_ERR_LIMIT_EXCEEDED,
    MAPGEN_BSP_ERR_BAD_INDEX,
    MAPGEN_BSP_ERR_NO_MODELS,
    MAPGEN_BSP_ERR_ENTSTRING,
    MAPGEN_BSP_ERR_OUT_OF_MEMORY,

    MAPGEN_BSP_RESULT_COUNT
} mapgen_bsp_result_t;

typedef struct { float normal[3]; float dist; int32_t type; } mapgen_bsp_plane_t;
typedef struct { uint32_t planenum; int32_t children[2]; int32_t mins[3]; int32_t maxs[3]; } mapgen_bsp_node_t;

typedef struct {
    int32_t  contents;
    int32_t  cluster;
    int32_t  area;
    int32_t  mins[3];
    int32_t  maxs[3];
    uint32_t firstleafface;
    uint32_t numleaffaces;
    uint32_t firstleafbrush;
    uint32_t numleafbrushes;
} mapgen_bsp_leaf_t;

typedef struct { int32_t firstside; int32_t numsides; int32_t contents; } mapgen_bsp_brush_t;
typedef struct { uint32_t planenum; int32_t texinfo; } mapgen_bsp_brushside_t;

typedef struct {
    /* The texture AXES the renderer-gated struct would have hidden. Training
       reads surface orientation and scale, so they are not optional here. */
    float   axis[2][4];
    int32_t flags;
    int32_t value;
    char    texture[MAPGEN_BSP_TEXNAME + 1];
    int32_t nexttexinfo;
} mapgen_bsp_texinfo_t;

typedef struct {
    float    mins[3];
    float    maxs[3];
    float    origin[3];
    int32_t  headnode;
    int32_t  firstface;
    int32_t  numfaces;
} mapgen_bsp_model_t;

typedef struct {
    uint32_t planenum;
    int32_t  side;
    int32_t  firstedge;
    int32_t  numedges;
    int32_t  texinfo;
    uint8_t  styles[4];
    int32_t  lightofs;
} mapgen_bsp_face_t;

/*
 * An area, and the portals that join it to its neighbours.
 *
 * Q2 seals a map into areas and connects them through areaportals, which a
 * door can close. Two maps that agree on how many areas and portals they have
 * can still join them up differently, so the records are kept and not just
 * counted.
 */
typedef struct { int32_t numareaportals; int32_t firstareaportal; } mapgen_bsp_area_t;
typedef struct { int32_t portalnum; int32_t otherarea; } mapgen_bsp_areaportal_t;

typedef struct { float point[3]; } mapgen_bsp_vertex_t;
typedef struct { uint32_t v[2]; } mapgen_bsp_edge_t;

typedef struct mapgen_bsp_s mapgen_bsp_t;

/* Load from a memory image the caller owns. The document copies what it needs
   into its own arena and never references `data` afterwards. */
mapgen_bsp_result_t MapGenBsp_Load(const uint8_t *data, size_t size, mapgen_bsp_t **out);
void MapGenBsp_Free(mapgen_bsp_t *bsp);

bool     MapGenBsp_IsExtended(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_Count(const mapgen_bsp_t *bsp, int lump);

uint32_t MapGenBsp_NumPlanes(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumNodes(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumLeafs(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumLeafBrushes(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumLeafFaces(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumBrushes(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumBrushSides(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumTexInfo(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumModels(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumVertices(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumEdges(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumSurfEdges(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumFaces(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumAreas(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_NumAreaPortals(const mapgen_bsp_t *bsp);
uint32_t MapGenBsp_VisibilityBytes(const mapgen_bsp_t *bsp);

/*
 * Does cluster `from` see cluster `to` by the map's own PVS?
 *
 * The compiled visibility decides what the renderer draws, and a cluster it
 * leaves out is not drawn - the smear the PO recorded on the stair under
 * corridor 12 (ledger row 297). True when the map carries no visibility or
 * either cluster is outside it: an unknown answer refuses nothing.
 */
bool     MapGenBsp_ClusterSees(const mapgen_bsp_t *bsp, int32_t from,
                               int32_t to);
uint32_t MapGenBsp_LightingBytes(const mapgen_bsp_t *bsp);
/* The lighting lump itself (row 408): RGB luxels a face's `lightofs` points into; NULL for an unlit map. */
const uint8_t *MapGenBsp_Lighting(const mapgen_bsp_t *bsp, uint32_t *bytes);

const mapgen_bsp_plane_t     *MapGenBsp_Plane(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_node_t      *MapGenBsp_Node(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_leaf_t      *MapGenBsp_Leaf(const mapgen_bsp_t *bsp, uint32_t i);
uint32_t                      MapGenBsp_LeafBrush(const mapgen_bsp_t *bsp, uint32_t i);
uint32_t                      MapGenBsp_LeafFace(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_brush_t     *MapGenBsp_Brush(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_brushside_t *MapGenBsp_BrushSide(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_texinfo_t   *MapGenBsp_TexInfo(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_model_t     *MapGenBsp_Model(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_face_t      *MapGenBsp_Face(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_area_t      *MapGenBsp_Area(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_areaportal_t *MapGenBsp_AreaPortal(const mapgen_bsp_t *bsp,
                                                    uint32_t i);
const mapgen_bsp_vertex_t    *MapGenBsp_Vertex(const mapgen_bsp_t *bsp, uint32_t i);
const mapgen_bsp_edge_t      *MapGenBsp_Edge(const mapgen_bsp_t *bsp, uint32_t i);
int32_t                       MapGenBsp_SurfEdge(const mapgen_bsp_t *bsp, uint32_t i);

/* The entity string, NUL-terminated and guaranteed free of embedded NULs. */
const char *MapGenBsp_Entities(const mapgen_bsp_t *bsp, uint32_t *out_length);

/*
 * Walk the collision tree of model 0 exactly as the engine does, and return
 * the leaf a point falls in. Read-only and reentrant: no global scratch, no
 * checkcount, so independent calls may run concurrently (contract 18.3).
 */
const mapgen_bsp_leaf_t *MapGenBsp_PointLeaf(const mapgen_bsp_t *bsp, const float point[3]);

/* Leaf contents OR the contents of any brush in that leaf containing the
   point. Detail brushes keep their contents on the brush, which is why the
   leaf alone is not the answer. */
int32_t MapGenBsp_PointContents(const mapgen_bsp_t *bsp, const float point[3]);

/* The same, but in ONE subtree: model zero is the map, and every door, lift
   and train has a headnode of its own. */
/*
 * Water standing in the air, measured on what the compiler produced.
 *
 * A drawn face with liquid on one side and open air on the other, within
 * thirty degrees of vertical. The compiler draws no face between water and
 * solid, so a pool in a basin has none of these and q2dm1 has none; a
 * vertical face of water is water meeting air, which the PO put in one
 * sentence on 2026-09-07: it would run off at once.
 *
 * Returns how many there are and, through `out_area`, how much of them.
 */
uint32_t MapGenBsp_StandingWater(const mapgen_bsp_t *bsp, double *out_area);

/*
 * T-junctions in the map the COMPILER produced.
 *
 * A vertex of one drawn face lying strictly inside the edge of another is the
 * hairline this whole family of rules is about: the two surfaces disagree
 * about where they are by a fraction of a unit and the crack between them
 * sparkles. Until 2026-09-08 the transaction counted them in the SOURCE
 * brushes and refused an edit that added to the donor's 892 - and the
 * compiler's own FixTjuncs pass, which is on by default and runs over the
 * world and every submodel, had already stitched them. MEASURED on candidates
 * the source rule refused: a pushed wall at +18 in the source, a recut at +4,
 * a lift at +5, all three compile to exactly the fourteen q2dm1's own file
 * has, and those fourteen are its big lift's edges against world faces, which
 * FixTjuncs does not stitch across models.
 *
 * So the question is asked of the artifact. `liquid` counts the ones where the
 * split edge belongs only to liquid faces: two water surfaces are drawn
 * translucent and coincident and a vertex in the middle of one changes
 * nothing anybody can see, which is what a raised pool leaves behind.
 *
 * Bounded and read-only: a uniform grid over the vertices, so an edge asks
 * only the cells it crosses.
 */
/*
 * One seam, named by WHERE it is rather than by an index.
 *
 * A count cannot tell a candidate that removed an old crack and made a new one
 * from a candidate that changed nothing: both come out equal. And a bsp index
 * is not identity - the compiler renumbers everything on every run - so the
 * name has to be geometric. The split point, rounded to a quarter unit,
 * addresses it stably across two compiles of the same room; the edge's own
 * ends order the comparison.
 */
typedef struct {
    float split[3];             /* where the vertex lands inside the edge   */
    float from[3], to[3];       /* the edge it splits                       */
    bool  opaque_edge;          /* an opaque face draws the split edge      */
    bool  opaque_vertex;        /* an opaque face carries the vertex        */
    /*
     * And which model each side belongs to.
     *
     * A T-junction between the world and a BRUSH MODEL is not a crack the
     * compiler could have closed: FixTjuncs runs over the world and over each
     * submodel separately, deliberately, because a door or a lift MOVES and a
     * vertex welded across that boundary would tear the moment it did. All
     * fourteen of q2dm1's own are of this kind, at its big lift.
     */
    uint32_t edge_model;
    uint32_t vertex_model;
} mapgen_bsp_seam_t;

typedef enum {
    MAPGEN_SEAMS_OK = 0,
    MAPGEN_SEAMS_ERR_ARGS,
    MAPGEN_SEAMS_ERR_MEMORY,    /* it could not be measured: NOT zero seams */
    MAPGEN_SEAMS_ERR_FULL       /* more than the caller's cap              */
} mapgen_bsp_seams_result_t;

/*
 * T-junctions in the map the COMPILER produced, as witnesses.
 *
 * A vertex of one drawn face lying strictly inside the edge of another is the
 * hairline this whole family of rules is about. Until 2026-09-08 the
 * transaction counted them in the SOURCE brushes and refused an edit that
 * added to the donor's 892 - and the compiler's own FixTjuncs pass, on by
 * default over the world and every submodel, had already stitched them.
 * MEASURED on candidates the source rule refused: a pushed wall at +18 in the
 * source, a recut at +4, a lift at +5 and an opened connector at +9 all
 * compile to exactly the fourteen q2dm1's own file has - its big lift's edges
 * against world faces, which FixTjuncs does not stitch across models.
 *
 * `out` receives up to `cap` witnesses and `out_count` how many there are.
 * A result other than OK means the answer is UNKNOWN and the caller must
 * refuse the candidate: an allocation failure that returned zero would read
 * as a map with no cracks in it.
 */
mapgen_bsp_seams_result_t MapGenBsp_Seams(const mapgen_bsp_t *bsp,
                                          mapgen_bsp_seam_t *out, uint32_t cap,
                                          uint32_t *out_count);

/*
 * The same, with a vertex counted ON an edge up to `on_line` units off its line
 * (MapGenBsp_Seams: 0.5). Ledger row 382: q2dm1's own floor sliver at a diagonal
 * wall reads 0.517 off in the donor and 0.481 in a later compile - one place on
 * both sides of the rule. A list of WITNESSES is taken with a wider reach than
 * the candidate's judgement, so such a place is named whichever side it falls.
 */
mapgen_bsp_seams_result_t MapGenBsp_SeamsWithin(const mapgen_bsp_t *bsp,
                                                float on_line,
                                                mapgen_bsp_seam_t *out,
                                                uint32_t cap,
                                                uint32_t *out_count);

const char *MapGenBsp_SeamsResultName(mapgen_bsp_seams_result_t r);

/* True when the two name the same seam: the split point to a quarter unit and
   the edge's own ends, in either order. Indices are not compared - the
   compiler renumbers them on every run. */
bool MapGenBsp_SameSeam(const mapgen_bsp_seam_t *a,
                        const mapgen_bsp_seam_t *b);

/*
 * Where a player's feet can rest, and which of those places are a WAY.
 *
 * `Stands` is the rule the whole toolchain uses: air here, solid eight units
 * under, room for a standing player above.
 *
 * `Places` walks a lattice of that rule over the whole map and writes the
 * places it finds; it returns how many there are, which may exceed `cap` -
 * the caller sizes for it or knows its answer is partial.
 *
 * `Climbs` marks the ones that are part of a climb: three or more distinct
 * floor heights within sixty-four units, which is a stair, a step or a ledge
 * to hop, and is what a map is played ON rather than furnished with. A
 * construction that turns one into solid has taken away a way through the
 * map, and no count of reachable pickups will say so - q2dm1 has another way
 * up, which is why the fork the PO could not walk through passed every gate.
 */
bool     MapGenBsp_Stands(const mapgen_bsp_t *bsp, const float point[3]);
/* The same, over a box rather than the whole map: what an operator asks
   about the piece of the world it is holding. */
uint32_t MapGenBsp_PlacesIn(const mapgen_bsp_t *bsp, const float lo[3],
                            const float hi[3], float grid,
                            float (*out)[3], uint32_t cap);

uint32_t MapGenBsp_Places(const mapgen_bsp_t *bsp, float grid,
                          float (*out)[3], uint32_t cap);
uint32_t MapGenBsp_Climbs(const float (*places)[3], uint32_t count,
                          uint8_t *out_is_climb);

int32_t MapGenBsp_PointContentsAt(const mapgen_bsp_t *bsp, int32_t headnode,
                                  const float point[3]);

/*
 * A canonical text describing the document's MEANING, for cross-implementation
 * comparison. It excludes lightmap bytes, vis bytes, padding and lump offsets,
 * exactly like the digest in contract section 10.
 *
 * Writes at most `capacity` bytes including the terminator and returns the
 * number of bytes the full text WOULD need, so a caller can size a buffer.
 */
size_t MapGenBsp_CanonicalText(const mapgen_bsp_t *bsp, char *out, size_t capacity);

/* FNV-1a 64 over the canonical text. Two independent readers of the same file
   must produce the same value. */
uint64_t MapGenBsp_CanonicalDigest(const mapgen_bsp_t *bsp);

const char *MapGenBsp_ResultName(mapgen_bsp_result_t result);
