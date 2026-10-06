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
 * MAPGEN-1 - BspDocument.
 *
 * Strict, self-contained, one arena per load, no globals, no `USE_REF`.
 * Contract sections 6.2 and 2.
 *
 * Reading order is deliberate: validate the header, then every lump's bounds
 * and element size, then every COUNT against a ceiling - and only then
 * allocate. A file is not permitted to make this reader allocate anything on
 * the strength of a number it supplied.
 */

#include "common/mapgen_bsp.h"

#include <stdlib.h>
#include <math.h>
#include <string.h>

/* On-disk lump indices. */
enum {
    LUMP_ENTITIES = 0, LUMP_PLANES, LUMP_VERTEXES, LUMP_VISIBILITY,
    LUMP_NODES, LUMP_TEXINFO, LUMP_FACES, LUMP_LIGHTING,
    LUMP_LEAFS, LUMP_LEAFFACES, LUMP_LEAFBRUSHES, LUMP_EDGES,
    LUMP_SURFEDGES, LUMP_MODELS, LUMP_BRUSHES, LUMP_BRUSHSIDES,
    LUMP_POP, LUMP_AREAS, LUMP_AREAPORTALS
};

#define CONTENTS_SOLID  1
/* No map this engine loads carries more; a larger lump is refused, not read. */
#define MAPGEN_BSP_VIS_LIMIT (16u << 20)

struct mapgen_bsp_s {
    bool     extended;
    size_t   file_bytes;

    uint32_t num_planes;      mapgen_bsp_plane_t     *planes;
    uint32_t num_nodes;       mapgen_bsp_node_t      *nodes;
    uint32_t num_leafs;       mapgen_bsp_leaf_t      *leafs;
    uint32_t num_leafbrushes; uint32_t               *leafbrushes;
    uint32_t num_leaffaces;   uint32_t               *leaffaces;
    uint32_t num_brushes;     mapgen_bsp_brush_t     *brushes;
    uint32_t num_brushsides;  mapgen_bsp_brushside_t *brushsides;
    uint32_t num_texinfo;     mapgen_bsp_texinfo_t   *texinfo;
    uint32_t num_models;      mapgen_bsp_model_t     *models;
    uint32_t num_vertices;    mapgen_bsp_vertex_t    *vertices;
    uint32_t num_edges;       mapgen_bsp_edge_t      *edges;
    uint32_t num_surfedges;   int32_t                *surfedges;
    uint32_t num_faces;       mapgen_bsp_face_t      *faces;

    uint32_t num_areas;         mapgen_bsp_area_t       *areas;
    uint32_t num_areaportals;   mapgen_bsp_areaportal_t *areaportals;
    uint32_t visibility_bytes;
    uint32_t lighting_bytes;
    /* The visibility lump itself, in the arena (ledger row 297): the gate that
       refuses an edit whose compiled map hides a surface in plain sight has to
       read the PVS, and a size is not a PVS. */
    uint8_t *visibility;
    uint8_t *lighting;          /* row 408 (brief 6): the lighting lump, for the light reference */

    uint32_t entity_length;   char *entities;

    /* One arena. Every array above points inside it, so a load either
       succeeds wholly or frees exactly one block. */
    uint8_t *arena;
    size_t   arena_size;
    size_t   arena_used;
};

/* ------------------------------------------------------------------------ */

static uint32_t rd_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static int32_t rd_i32(const uint8_t *p) { return (int32_t)rd_u32(p); }
static uint16_t rd_u16(const uint8_t *p) { return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8)); }
static int16_t rd_i16(const uint8_t *p) { return (int16_t)rd_u16(p); }

static float rd_f32(const uint8_t *p)
{
    uint32_t bits = rd_u32(p);
    float f;
    memcpy(&f, &bits, sizeof(f));
    return f;
}

static void *arena_alloc(mapgen_bsp_t *bsp, size_t bytes)
{
    /* 8-byte alignment is enough for every type here and keeps the arithmetic
       obvious. */
    size_t aligned = (bsp->arena_used + 7u) & ~(size_t)7u;
    if (aligned + bytes < aligned || aligned + bytes > bsp->arena_size)
        return NULL;
    void *p = bsp->arena + aligned;
    bsp->arena_used = aligned + bytes;
    return p;
}

/* ------------------------------------------------------------------------ */

typedef struct {
    uint32_t offset;
    uint32_t length;
} lump_span_t;

mapgen_bsp_result_t MapGenBsp_Load(const uint8_t *data, size_t size, mapgen_bsp_t **out)
{
    if (!data || !out)
        return MAPGEN_BSP_ERR_ARGUMENT;
    *out = NULL;

    const size_t header_bytes = 8u + (size_t)MAPGEN_BSP_LUMPS * 8u;
    if (size < header_bytes)
        return MAPGEN_BSP_ERR_TOO_SMALL;
    if (size > MAPGEN_BSP_MAX_FILE_BYTES)
        return MAPGEN_BSP_ERR_TOO_LARGE;

    uint32_t ident = rd_u32(data);
    bool extended;
    if (ident == MAPGEN_BSP_IDENT_IBSP)
        extended = false;
    else if (ident == MAPGEN_BSP_IDENT_QBSP)
        extended = true;
    else
        return MAPGEN_BSP_ERR_BAD_IDENT;

    if (rd_u32(data + 4) != MAPGEN_BSP_VERSION)
        return MAPGEN_BSP_ERR_BAD_VERSION;

    lump_span_t lumps[MAPGEN_BSP_LUMPS];
    for (int i = 0; i < MAPGEN_BSP_LUMPS; i++) {
        uint32_t ofs = rd_u32(data + 8 + i * 8);
        uint32_t len = rd_u32(data + 12 + i * 8);
        /* 64-bit sum so a length near UINT32_MAX cannot wrap into range. */
        if ((uint64_t)ofs + (uint64_t)len > (uint64_t)size)
            return MAPGEN_BSP_ERR_LUMP_OUT_OF_BOUNDS;
        lumps[i].offset = ofs;
        lumps[i].length = len;
    }

    /* Record sizes differ between the standard and extended formats. */
    const uint32_t sz_plane      = 20;
    const uint32_t sz_node       = extended ? 44 : 28;
    const uint32_t sz_leaf       = extended ? 52 : 28;
    const uint32_t sz_leafbrush  = extended ? 4 : 2;
    const uint32_t sz_leafface   = extended ? 4 : 2;
    const uint32_t sz_brush      = 12;
    const uint32_t sz_brushside  = extended ? 8 : 4;
    const uint32_t sz_texinfo    = 76;
    const uint32_t sz_model      = 48;
    const uint32_t sz_vertex     = 12;
    const uint32_t sz_edge       = extended ? 8 : 4;
    const uint32_t sz_surfedge   = 4;
    const uint32_t sz_face       = extended ? 28 : 20;
    const uint32_t sz_area       = 8;
    const uint32_t sz_areaportal = 8;

    struct { int lump; uint32_t size; uint32_t limit; uint32_t *out; } table[] = {
        { LUMP_PLANES,      sz_plane,      MAPGEN_BSP_MAX_PLANES,      NULL },
        { LUMP_NODES,       sz_node,       MAPGEN_BSP_MAX_NODES,       NULL },
        { LUMP_LEAFS,       sz_leaf,       MAPGEN_BSP_MAX_LEAFS,       NULL },
        { LUMP_LEAFBRUSHES, sz_leafbrush,  MAPGEN_BSP_MAX_LEAFBRUSHES, NULL },
        { LUMP_LEAFFACES,   sz_leafface,   MAPGEN_BSP_MAX_LEAFFACES,   NULL },
        { LUMP_BRUSHES,     sz_brush,      MAPGEN_BSP_MAX_BRUSHES,     NULL },
        { LUMP_BRUSHSIDES,  sz_brushside,  MAPGEN_BSP_MAX_BRUSHSIDES,  NULL },
        { LUMP_TEXINFO,     sz_texinfo,    MAPGEN_BSP_MAX_TEXINFO,     NULL },
        { LUMP_MODELS,      sz_model,      MAPGEN_BSP_MAX_MODELS,      NULL },
        { LUMP_VERTEXES,    sz_vertex,     MAPGEN_BSP_MAX_VERTICES,    NULL },
        { LUMP_EDGES,       sz_edge,       MAPGEN_BSP_MAX_EDGES,       NULL },
        { LUMP_SURFEDGES,   sz_surfedge,   MAPGEN_BSP_MAX_SURFEDGES,   NULL },
        { LUMP_FACES,       sz_face,       MAPGEN_BSP_MAX_FACES,       NULL },
        { LUMP_AREAS,       sz_area,       MAPGEN_BSP_MAX_AREAS,       NULL },
        /* both eight bytes per record, and now both kept */
        { LUMP_AREAPORTALS, sz_areaportal, MAPGEN_BSP_MAX_AREAPORTALS, NULL },
    };
    const size_t table_count = sizeof(table) / sizeof(table[0]);

    uint32_t counts[MAPGEN_BSP_LUMPS];
    memset(counts, 0, sizeof(counts));

    for (size_t i = 0; i < table_count; i++) {
        uint32_t len = lumps[table[i].lump].length;
        if (len % table[i].size)
            return MAPGEN_BSP_ERR_LUMP_ODD_SIZE;
        uint32_t count = len / table[i].size;
        if (count > table[i].limit)
            return MAPGEN_BSP_ERR_LIMIT_EXCEEDED;
        counts[table[i].lump] = count;
    }

    uint32_t ent_len = lumps[LUMP_ENTITIES].length;
    if (ent_len > MAPGEN_BSP_MAX_ENTCHARS)
        return MAPGEN_BSP_ERR_LIMIT_EXCEEDED;

    /* Size the arena from validated counts only. */
    size_t need = 0;
    need += (size_t)counts[LUMP_PLANES]      * sizeof(mapgen_bsp_plane_t)     + 8;
    need += (size_t)counts[LUMP_NODES]       * sizeof(mapgen_bsp_node_t)      + 8;
    need += (size_t)counts[LUMP_LEAFS]       * sizeof(mapgen_bsp_leaf_t)      + 8;
    need += (size_t)counts[LUMP_LEAFBRUSHES] * sizeof(uint32_t)               + 8;
    need += (size_t)counts[LUMP_LEAFFACES]   * sizeof(uint32_t)               + 8;
    need += (size_t)counts[LUMP_BRUSHES]     * sizeof(mapgen_bsp_brush_t)     + 8;
    need += (size_t)counts[LUMP_BRUSHSIDES]  * sizeof(mapgen_bsp_brushside_t) + 8;
    need += (size_t)counts[LUMP_TEXINFO]     * sizeof(mapgen_bsp_texinfo_t)   + 8;
    need += (size_t)counts[LUMP_MODELS]      * sizeof(mapgen_bsp_model_t)     + 8;
    need += (size_t)counts[LUMP_VERTEXES]    * sizeof(mapgen_bsp_vertex_t)    + 8;
    need += (size_t)counts[LUMP_EDGES]       * sizeof(mapgen_bsp_edge_t)      + 8;
    need += (size_t)counts[LUMP_SURFEDGES]   * sizeof(int32_t)                + 8;
    need += (size_t)counts[LUMP_FACES]       * sizeof(mapgen_bsp_face_t)      + 8;
    /* The areas and their portals are kept, so their bytes are counted here.
       The arena is sized once from this list and nowhere else: a lump added
       to the load and not to this list runs the arena out. */
    need += (size_t)counts[LUMP_AREAS]       * sizeof(mapgen_bsp_area_t)      + 8;
    need += (size_t)counts[LUMP_AREAPORTALS] * sizeof(mapgen_bsp_areaportal_t) + 8;
    need += (size_t)ent_len + 1 + 8;
    if (lumps[LUMP_VISIBILITY].length > MAPGEN_BSP_VIS_LIMIT)
        return MAPGEN_BSP_ERR_LIMIT_EXCEEDED;
    need += (size_t)lumps[LUMP_VISIBILITY].length + 8;
    need += (size_t)lumps[LUMP_LIGHTING].length + 8;     /* row 408: kept for the light reference */

    mapgen_bsp_t *bsp = calloc(1, sizeof(*bsp));
    if (!bsp)
        return MAPGEN_BSP_ERR_OUT_OF_MEMORY;
    bsp->arena = calloc(1, need ? need : 1);
    if (!bsp->arena) {
        free(bsp);
        return MAPGEN_BSP_ERR_OUT_OF_MEMORY;
    }
    bsp->arena_size = need ? need : 1;
    bsp->extended = extended;
    bsp->file_bytes = size;

    bsp->num_planes      = counts[LUMP_PLANES];
    bsp->num_nodes       = counts[LUMP_NODES];
    bsp->num_leafs       = counts[LUMP_LEAFS];
    bsp->num_leafbrushes = counts[LUMP_LEAFBRUSHES];
    bsp->num_leaffaces   = counts[LUMP_LEAFFACES];
    bsp->num_brushes     = counts[LUMP_BRUSHES];
    bsp->num_brushsides  = counts[LUMP_BRUSHSIDES];
    bsp->num_texinfo     = counts[LUMP_TEXINFO];
    bsp->num_models      = counts[LUMP_MODELS];
    bsp->num_vertices    = counts[LUMP_VERTEXES];
    bsp->num_edges       = counts[LUMP_EDGES];
    bsp->num_surfedges   = counts[LUMP_SURFEDGES];
    bsp->num_faces       = counts[LUMP_FACES];
    bsp->num_areas       = counts[LUMP_AREAS];
    bsp->num_areaportals = counts[LUMP_AREAPORTALS];
    bsp->visibility_bytes = lumps[LUMP_VISIBILITY].length;
    bsp->lighting_bytes   = lumps[LUMP_LIGHTING].length;

#define ALLOC(field, type, count)                                  \
    do {                                                           \
        if (count) {                                               \
            bsp->field = arena_alloc(bsp, (size_t)(count) * sizeof(type)); \
            if (!bsp->field) { MapGenBsp_Free(bsp); return MAPGEN_BSP_ERR_OUT_OF_MEMORY; } \
        }                                                          \
    } while (0)

    ALLOC(planes,      mapgen_bsp_plane_t,     bsp->num_planes);
    ALLOC(nodes,       mapgen_bsp_node_t,      bsp->num_nodes);
    ALLOC(leafs,       mapgen_bsp_leaf_t,      bsp->num_leafs);
    ALLOC(leafbrushes, uint32_t,               bsp->num_leafbrushes);
    ALLOC(areas,       mapgen_bsp_area_t,       bsp->num_areas);
    ALLOC(areaportals, mapgen_bsp_areaportal_t, bsp->num_areaportals);
    ALLOC(leaffaces,   uint32_t,               bsp->num_leaffaces);
    ALLOC(brushes,     mapgen_bsp_brush_t,     bsp->num_brushes);
    ALLOC(brushsides,  mapgen_bsp_brushside_t, bsp->num_brushsides);
    ALLOC(texinfo,     mapgen_bsp_texinfo_t,   bsp->num_texinfo);
    ALLOC(models,      mapgen_bsp_model_t,     bsp->num_models);
    ALLOC(vertices,    mapgen_bsp_vertex_t,    bsp->num_vertices);
    ALLOC(edges,       mapgen_bsp_edge_t,      bsp->num_edges);
    ALLOC(surfedges,   int32_t,                bsp->num_surfedges);
    ALLOC(faces,       mapgen_bsp_face_t,      bsp->num_faces);
#undef ALLOC

    bsp->entities = arena_alloc(bsp, (size_t)ent_len + 1);
    if (!bsp->entities) {
        MapGenBsp_Free(bsp);
        return MAPGEN_BSP_ERR_OUT_OF_MEMORY;
    }
    if (bsp->visibility_bytes) {
        bsp->visibility = arena_alloc(bsp, bsp->visibility_bytes);
        if (!bsp->visibility) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_OUT_OF_MEMORY;
        }
        memcpy(bsp->visibility, data + lumps[LUMP_VISIBILITY].offset,
               bsp->visibility_bytes);
    }
    if (bsp->lighting_bytes) {
        bsp->lighting = arena_alloc(bsp, bsp->lighting_bytes);
        if (!bsp->lighting) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_OUT_OF_MEMORY;
        }
        memcpy(bsp->lighting, data + lumps[LUMP_LIGHTING].offset, bsp->lighting_bytes);
    }

    const uint8_t *p;

    p = data + lumps[LUMP_PLANES].offset;
    for (uint32_t i = 0; i < bsp->num_planes; i++, p += sz_plane) {
        bsp->planes[i].normal[0] = rd_f32(p);
        bsp->planes[i].normal[1] = rd_f32(p + 4);
        bsp->planes[i].normal[2] = rd_f32(p + 8);
        bsp->planes[i].dist = rd_f32(p + 12);
        bsp->planes[i].type = rd_i32(p + 16);
    }

    p = data + lumps[LUMP_NODES].offset;
    for (uint32_t i = 0; i < bsp->num_nodes; i++, p += sz_node) {
        bsp->nodes[i].planenum = rd_u32(p);
        bsp->nodes[i].children[0] = rd_i32(p + 4);
        bsp->nodes[i].children[1] = rd_i32(p + 8);
        for (int k = 0; k < 3; k++) {
            bsp->nodes[i].mins[k] = extended ? rd_i32(p + 12 + k * 4) : rd_i16(p + 12 + k * 2);
            bsp->nodes[i].maxs[k] = extended ? rd_i32(p + 24 + k * 4) : rd_i16(p + 18 + k * 2);
        }
    }

    p = data + lumps[LUMP_LEAFS].offset;
    for (uint32_t i = 0; i < bsp->num_leafs; i++, p += sz_leaf) {
        mapgen_bsp_leaf_t *lf = &bsp->leafs[i];
        lf->contents = rd_i32(p);
        if (extended) {
            lf->cluster = rd_i32(p + 4);
            lf->area = rd_i32(p + 8);
            for (int k = 0; k < 3; k++) {
                lf->mins[k] = rd_i32(p + 12 + k * 4);
                lf->maxs[k] = rd_i32(p + 24 + k * 4);
            }
            lf->firstleafface  = rd_u32(p + 36);
            lf->numleaffaces   = rd_u32(p + 40);
            lf->firstleafbrush = rd_u32(p + 44);
            lf->numleafbrushes = rd_u32(p + 48);
        } else {
            lf->cluster = rd_i16(p + 4);
            lf->area = rd_i16(p + 6);
            for (int k = 0; k < 3; k++) {
                lf->mins[k] = rd_i16(p + 8 + k * 2);
                lf->maxs[k] = rd_i16(p + 14 + k * 2);
            }
            lf->firstleafface  = rd_u16(p + 20);
            lf->numleaffaces   = rd_u16(p + 22);
            lf->firstleafbrush = rd_u16(p + 24);
            lf->numleafbrushes = rd_u16(p + 26);
        }
    }

    p = data + lumps[LUMP_LEAFBRUSHES].offset;
    for (uint32_t i = 0; i < bsp->num_leafbrushes; i++, p += sz_leafbrush)
        bsp->leafbrushes[i] = extended ? rd_u32(p) : rd_u16(p);

    p = data + lumps[LUMP_LEAFFACES].offset;
    for (uint32_t i = 0; i < bsp->num_leaffaces; i++, p += sz_leafface)
        bsp->leaffaces[i] = extended ? rd_u32(p) : rd_u16(p);

    p = data + lumps[LUMP_AREAS].offset;
    for (uint32_t i = 0; i < bsp->num_areas; i++, p += sz_area) {
        bsp->areas[i].numareaportals  = rd_i32(p);
        bsp->areas[i].firstareaportal = rd_i32(p + 4);
    }

    p = data + lumps[LUMP_AREAPORTALS].offset;
    for (uint32_t i = 0; i < bsp->num_areaportals; i++, p += sz_areaportal) {
        bsp->areaportals[i].portalnum = rd_i32(p);
        bsp->areaportals[i].otherarea = rd_i32(p + 4);
    }

    p = data + lumps[LUMP_BRUSHES].offset;
    for (uint32_t i = 0; i < bsp->num_brushes; i++, p += sz_brush) {
        bsp->brushes[i].firstside = rd_i32(p);
        bsp->brushes[i].numsides = rd_i32(p + 4);
        bsp->brushes[i].contents = rd_i32(p + 8);
    }

    p = data + lumps[LUMP_BRUSHSIDES].offset;
    for (uint32_t i = 0; i < bsp->num_brushsides; i++, p += sz_brushside) {
        if (extended) {
            bsp->brushsides[i].planenum = rd_u32(p);
            bsp->brushsides[i].texinfo = rd_i32(p + 4);
        } else {
            bsp->brushsides[i].planenum = rd_u16(p);
            bsp->brushsides[i].texinfo = rd_i16(p + 2);
        }
    }

    p = data + lumps[LUMP_TEXINFO].offset;
    for (uint32_t i = 0; i < bsp->num_texinfo; i++, p += sz_texinfo) {
        mapgen_bsp_texinfo_t *ti = &bsp->texinfo[i];
        for (int a = 0; a < 2; a++)
            for (int c = 0; c < 4; c++)
                ti->axis[a][c] = rd_f32(p + (a * 4 + c) * 4);
        ti->flags = rd_i32(p + 32);
        ti->value = rd_i32(p + 36);
        /* A texture name is UNTRUSTED: it may fill the field with no
           terminator, so it is copied bounded and terminated here. */
        memcpy(ti->texture, p + 40, MAPGEN_BSP_TEXNAME);
        ti->texture[MAPGEN_BSP_TEXNAME] = '\0';
        for (int c = 0; c < MAPGEN_BSP_TEXNAME; c++) {
            if (ti->texture[c] == '\0')
                break;
            /* Control bytes never belong in a texture reference and would go
               on to reach a log, a UI and a compiler command line. */
            if ((unsigned char)ti->texture[c] < 0x20)
                ti->texture[c] = '?';
        }
        ti->nexttexinfo = rd_i32(p + 72);
    }

    p = data + lumps[LUMP_MODELS].offset;
    for (uint32_t i = 0; i < bsp->num_models; i++, p += sz_model) {
        for (int k = 0; k < 3; k++) {
            bsp->models[i].mins[k] = rd_f32(p + k * 4);
            bsp->models[i].maxs[k] = rd_f32(p + 12 + k * 4);
            bsp->models[i].origin[k] = rd_f32(p + 24 + k * 4);
        }
        bsp->models[i].headnode = rd_i32(p + 36);
        bsp->models[i].firstface = rd_i32(p + 40);
        bsp->models[i].numfaces = rd_i32(p + 44);
    }

    p = data + lumps[LUMP_VERTEXES].offset;
    for (uint32_t i = 0; i < bsp->num_vertices; i++, p += sz_vertex) {
        bsp->vertices[i].point[0] = rd_f32(p);
        bsp->vertices[i].point[1] = rd_f32(p + 4);
        bsp->vertices[i].point[2] = rd_f32(p + 8);
    }

    p = data + lumps[LUMP_EDGES].offset;
    for (uint32_t i = 0; i < bsp->num_edges; i++, p += sz_edge) {
        bsp->edges[i].v[0] = extended ? rd_u32(p) : rd_u16(p);
        bsp->edges[i].v[1] = extended ? rd_u32(p + 4) : rd_u16(p + 2);
    }

    p = data + lumps[LUMP_SURFEDGES].offset;
    for (uint32_t i = 0; i < bsp->num_surfedges; i++, p += sz_surfedge)
        bsp->surfedges[i] = rd_i32(p);

    p = data + lumps[LUMP_FACES].offset;
    for (uint32_t i = 0; i < bsp->num_faces; i++, p += sz_face) {
        mapgen_bsp_face_t *f = &bsp->faces[i];
        if (extended) {
            f->planenum = rd_u32(p);
            f->side = rd_i32(p + 4);
            f->firstedge = rd_i32(p + 8);
            f->numedges = rd_i32(p + 12);
            f->texinfo = rd_i32(p + 16);
            memcpy(f->styles, p + 20, 4);
            f->lightofs = rd_i32(p + 24);
        } else {
            f->planenum = rd_u16(p);
            f->side = rd_i16(p + 2);
            f->firstedge = rd_i32(p + 4);
            f->numedges = rd_i16(p + 8);
            f->texinfo = rd_i16(p + 10);
            memcpy(f->styles, p + 12, 4);
            f->lightofs = rd_i32(p + 16);
        }
    }

    /* The entity string is untrusted text. An embedded NUL would truncate it
       for one consumer and not another, so the document keeps exactly the
       bytes up to the first NUL and terminates them itself. */
    if (ent_len) {
        const uint8_t *ents = data + lumps[LUMP_ENTITIES].offset;
        uint32_t used = ent_len;
        for (uint32_t i = 0; i < ent_len; i++) {
            if (ents[i] == '\0') {
                used = i;
                break;
            }
        }
        memcpy(bsp->entities, ents, used);
        bsp->entities[used] = '\0';
        bsp->entity_length = used;
    } else {
        bsp->entities[0] = '\0';
        bsp->entity_length = 0;
    }

    /* Index validation, once, over everything - AFTER parsing so the checks
       run on decoded values rather than on re-derived offsets. A file that
       points a leaf at leafbrushes it does not have must be REJECTED here,
       not discovered later by a tree walk crashing. */
    if (!bsp->num_models) {
        MapGenBsp_Free(bsp);
        return MAPGEN_BSP_ERR_NO_MODELS;
    }
    for (uint32_t i = 0; i < bsp->num_leafs; i++) {
        const mapgen_bsp_leaf_t *lf = &bsp->leafs[i];
        if ((uint64_t)lf->firstleafbrush + lf->numleafbrushes > bsp->num_leafbrushes ||
            (uint64_t)lf->firstleafface + lf->numleaffaces > bsp->num_leaffaces) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    /*
     * A leaf names the area it belongs to; an area names a run of portals; a
     * portal names the area on its far side. None of the three is trusted.
     *
     * The leaf's area is checked only when the file HAS areas. An index is an
     * index into something, and a file with no AREAS lump is not making a
     * claim about one - it is a map that was never sealed into areas, which
     * the rest of this reader handles by iterating zero of them. Rejecting it
     * would refuse files that load, in exchange for no safety at all.
     */
    if (bsp->num_areas) {
        for (uint32_t i = 0; i < bsp->num_leafs; i++) {
            const int32_t area = bsp->leafs[i].area;
            if (area < 0 || (uint32_t)area >= bsp->num_areas) {
                MapGenBsp_Free(bsp);
                return MAPGEN_BSP_ERR_BAD_INDEX;
            }
        }
    }
    for (uint32_t i = 0; i < bsp->num_areas; i++) {
        const mapgen_bsp_area_t *a = &bsp->areas[i];
        if (a->firstareaportal < 0 || a->numareaportals < 0 ||
            (uint64_t)a->firstareaportal + (uint64_t)a->numareaportals
                > bsp->num_areaportals) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_areaportals; i++) {
        const int32_t other = bsp->areaportals[i].otherarea;
        if (other < 0 || (uint32_t)other >= bsp->num_areas) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_leafbrushes; i++) {
        if (bsp->leafbrushes[i] >= bsp->num_brushes) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_leaffaces; i++) {
        if (bsp->leaffaces[i] >= bsp->num_faces) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_brushes; i++) {
        const mapgen_bsp_brush_t *b = &bsp->brushes[i];
        if (b->firstside < 0 || b->numsides < 0 ||
            (uint64_t)b->firstside + (uint64_t)b->numsides > bsp->num_brushsides) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_brushsides; i++) {
        if (bsp->brushsides[i].planenum >= bsp->num_planes ||
            bsp->brushsides[i].texinfo >= (int32_t)bsp->num_texinfo) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_nodes; i++) {
        const mapgen_bsp_node_t *n = &bsp->nodes[i];
        if (n->planenum >= bsp->num_planes) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
        for (int c = 0; c < 2; c++) {
            int32_t child = n->children[c];
            if (child >= 0) {
                if ((uint32_t)child >= bsp->num_nodes) {
                    MapGenBsp_Free(bsp);
                    return MAPGEN_BSP_ERR_BAD_INDEX;
                }
            } else if ((uint32_t)(-1 - child) >= bsp->num_leafs) {
                MapGenBsp_Free(bsp);
                return MAPGEN_BSP_ERR_BAD_INDEX;
            }
        }
    }
    for (uint32_t i = 0; i < bsp->num_faces; i++) {
        const mapgen_bsp_face_t *f = &bsp->faces[i];
        if (f->planenum >= bsp->num_planes ||
            f->texinfo >= (int32_t)bsp->num_texinfo ||
            f->numedges < 0 || f->firstedge < 0 ||
            (uint64_t)f->firstedge + (uint64_t)f->numedges > bsp->num_surfedges) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_surfedges; i++) {
        int32_t e = bsp->surfedges[i];
        uint32_t idx = (uint32_t)(e < 0 ? -e : e);
        if (idx >= bsp->num_edges) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_edges; i++) {
        if (bsp->edges[i].v[0] >= bsp->num_vertices || bsp->edges[i].v[1] >= bsp->num_vertices) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }
    for (uint32_t i = 0; i < bsp->num_models; i++) {
        int32_t hn = bsp->models[i].headnode;
        /* A submodel whose whole volume is one leaf encodes its headnode as
           -(leaf + 1), exactly like a node child. Real shipped maps do this:
           q2rdm2 has four such submodels. Rejecting a negative headnode was
           the first version of this check, and it refused four playable maps
           from the PO's own Release tree - which is why parity runs against
           132 real maps and not only against synthesized ones. */
        if (hn >= 0) {
            if (bsp->num_nodes && (uint32_t)hn >= bsp->num_nodes) {
                MapGenBsp_Free(bsp);
                return MAPGEN_BSP_ERR_BAD_INDEX;
            }
        } else if ((uint32_t)(-1 - hn) >= bsp->num_leafs) {
            MapGenBsp_Free(bsp);
            return MAPGEN_BSP_ERR_BAD_INDEX;
        }
    }

    *out = bsp;
    return MAPGEN_BSP_OK;
}

void MapGenBsp_Free(mapgen_bsp_t *bsp)
{
    if (!bsp)
        return;
    free(bsp->arena);
    free(bsp);
}

/* ------------------------------------------------------------------------ */

bool MapGenBsp_IsExtended(const mapgen_bsp_t *b) { return b && b->extended; }

#define COUNT_FN(name, field) \
    uint32_t name(const mapgen_bsp_t *b) { return b ? b->field : 0; }

COUNT_FN(MapGenBsp_NumPlanes,      num_planes)
COUNT_FN(MapGenBsp_NumNodes,       num_nodes)
COUNT_FN(MapGenBsp_NumLeafs,       num_leafs)
COUNT_FN(MapGenBsp_NumLeafBrushes, num_leafbrushes)
COUNT_FN(MapGenBsp_NumLeafFaces,   num_leaffaces)
COUNT_FN(MapGenBsp_NumBrushes,     num_brushes)
COUNT_FN(MapGenBsp_NumBrushSides,  num_brushsides)
COUNT_FN(MapGenBsp_NumTexInfo,     num_texinfo)
COUNT_FN(MapGenBsp_NumModels,      num_models)
COUNT_FN(MapGenBsp_NumVertices,    num_vertices)
COUNT_FN(MapGenBsp_NumEdges,       num_edges)
COUNT_FN(MapGenBsp_NumSurfEdges,   num_surfedges)
COUNT_FN(MapGenBsp_NumFaces,       num_faces)
COUNT_FN(MapGenBsp_NumAreas,       num_areas)
COUNT_FN(MapGenBsp_NumAreaPortals, num_areaportals)
COUNT_FN(MapGenBsp_VisibilityBytes, visibility_bytes)
COUNT_FN(MapGenBsp_LightingBytes,   lighting_bytes)

const uint8_t *MapGenBsp_Lighting(const mapgen_bsp_t *bsp, uint32_t *bytes)
{
    if (bytes)
        *bytes = bsp ? bsp->lighting_bytes : 0;
    return bsp ? bsp->lighting : NULL;
}
#undef COUNT_FN

bool MapGenBsp_ClusterSees(const mapgen_bsp_t *bsp, int32_t from, int32_t to)
{
    if (!bsp || !bsp->visibility || bsp->visibility_bytes < 4 || from < 0
        || to < 0)
        return true;
    const int32_t clusters = rd_i32(bsp->visibility);
    if (clusters <= 0 || from >= clusters || to >= clusters
        || 8u + (uint64_t)(uint32_t)from * 8u > bsp->visibility_bytes)
        return true;
    uint32_t i = rd_u32(bsp->visibility + 4 + (uint32_t)from * 8);
    int32_t bit = 0;
    while (i < bsp->visibility_bytes && bit < clusters) {
        const uint8_t v = bsp->visibility[i++];
        if (v) {
            if (to < bit + 8)
                return (v >> (to - bit)) & 1u;
            bit += 8;
        } else {
            if (i >= bsp->visibility_bytes)
                return true;
            const int32_t zeros = 8 * (int32_t)bsp->visibility[i++];
            if (to < bit + zeros)
                return false;
            bit += zeros;
        }
    }
    return true;
}

#define ITEM_FN(name, type, array, count) \
    const type *name(const mapgen_bsp_t *b, uint32_t i) \
    { return (b && i < b->count) ? &b->array[i] : NULL; }

ITEM_FN(MapGenBsp_Plane,     mapgen_bsp_plane_t,     planes,     num_planes)
ITEM_FN(MapGenBsp_Node,      mapgen_bsp_node_t,      nodes,      num_nodes)
ITEM_FN(MapGenBsp_Leaf,      mapgen_bsp_leaf_t,      leafs,      num_leafs)
ITEM_FN(MapGenBsp_Brush,     mapgen_bsp_brush_t,     brushes,    num_brushes)
ITEM_FN(MapGenBsp_BrushSide, mapgen_bsp_brushside_t, brushsides, num_brushsides)
ITEM_FN(MapGenBsp_TexInfo,   mapgen_bsp_texinfo_t,   texinfo,    num_texinfo)
ITEM_FN(MapGenBsp_Model,     mapgen_bsp_model_t,     models,     num_models)
ITEM_FN(MapGenBsp_Face,      mapgen_bsp_face_t,      faces,      num_faces)
ITEM_FN(MapGenBsp_Vertex,    mapgen_bsp_vertex_t,    vertices,   num_vertices)
ITEM_FN(MapGenBsp_Edge,      mapgen_bsp_edge_t,      edges,      num_edges)
ITEM_FN(MapGenBsp_Area,      mapgen_bsp_area_t,      areas,      num_areas)
ITEM_FN(MapGenBsp_AreaPortal, mapgen_bsp_areaportal_t, areaportals, num_areaportals)
#undef ITEM_FN

uint32_t MapGenBsp_LeafBrush(const mapgen_bsp_t *b, uint32_t i)
{
    return (b && i < b->num_leafbrushes) ? b->leafbrushes[i] : 0;
}

uint32_t MapGenBsp_LeafFace(const mapgen_bsp_t *b, uint32_t i)
{
    return (b && i < b->num_leaffaces) ? b->leaffaces[i] : 0;
}

int32_t MapGenBsp_SurfEdge(const mapgen_bsp_t *b, uint32_t i)
{
    return (b && i < b->num_surfedges) ? b->surfedges[i] : 0;
}

const char *MapGenBsp_Entities(const mapgen_bsp_t *b, uint32_t *out_length)
{
    if (out_length)
        *out_length = b ? b->entity_length : 0;
    return b ? b->entities : NULL;
}

/* ------------------------------------------------------------------------ */

static const mapgen_bsp_leaf_t *point_leaf_from(const mapgen_bsp_t *b,
                                                int32_t num,
                                                const float point[3]);

const mapgen_bsp_leaf_t *MapGenBsp_PointLeaf(const mapgen_bsp_t *b, const float point[3])
{
    if (!b || !point || !b->num_leafs)
        return NULL;
    if (!b->num_nodes)
        return &b->leafs[0];

    int32_t num = b->models[0].headnode;
    return point_leaf_from(b, num, point);
}

/* The same walk, from any subtree - a door and a lift each have their own. */
static const mapgen_bsp_leaf_t *point_leaf_from(const mapgen_bsp_t *b,
                                                int32_t num,
                                                const float point[3])
{
    /* A headnode may itself be a leaf reference; the walk below already
       handles that shape, so nothing special is needed here beyond not
       assuming it is a node. */
    /* Bounded by the node count: the tree was validated at load, but a walk
       that could not terminate would still be a hang rather than an error. */
    for (uint32_t guard = 0; num >= 0 && guard <= b->num_nodes; guard++) {
        const mapgen_bsp_node_t *n = &b->nodes[num];
        const mapgen_bsp_plane_t *pl = &b->planes[n->planenum];
        float d = point[0] * pl->normal[0] + point[1] * pl->normal[1] +
                  point[2] * pl->normal[2] - pl->dist;
        /* The engine's tie-break, not a plausible one: `BSP_PointLeaf`
           (src/common/bsp.c:1127-1136) does `children[d < 0]`, so a point
           exactly ON a node plane goes to the FRONT. 4.5% of the stances
           MAPGEN queries land exactly on a plane, and every one of them
           resolved to a different leaf under `d > 0`. */
        num = n->children[d < 0];
    }
    if (num >= 0)
        return NULL;
    uint32_t leaf = (uint32_t)(-1 - num);
    return leaf < b->num_leafs ? &b->leafs[leaf] : NULL;
}

int32_t MapGenBsp_PointContents(const mapgen_bsp_t *b, const float point[3])
{
    return b ? MapGenBsp_PointContentsAt(b, b->models[0].headnode, point) : 0;
}

/* ---- where a player stands, and which of those places are a way ------------ */

bool MapGenBsp_Stands(const mapgen_bsp_t *b, const float point[3])
{
    if (!b || !point)
        return false;
    const float below[3] = { point[0], point[1], point[2] - 8.0f };
    /*
     * Forty-six, and the two that are missing are the whole point.
     *
     * A standing place is sampled on the world's own eight-unit lattice, so a
     * head sample forty-EIGHT units up lands on the same eight-unit grid the
     * mapper drew his ceilings on - which is to say, exactly on a plane. A
     * point on a plane belongs to whichever side the compiler's tree put it,
     * and two compiles of the same room can disagree about it.
     *
     * MEASURED on 2026-09-08: a lift built at 1424 600 took away four
     * standing places at 1776..1872, 32, 512 - four hundred units away, in a
     * room it did not touch. Nothing was built there; the ceiling is at 560,
     * the head sample was at 560, the donor's tree called that air and the
     * candidate's called it solid. The route gate read four ways through the
     * map buried and refused the lift.
     *
     * Forty-six is not on the grid, so the answer is about the room instead
     * of about the tree. It is also the honest headroom: a Quake II player
     * standing is fifty-six units tall with his eyes at forty-six.
     */
    const float head[3] = { point[0], point[1], point[2] + 46.0f };
    return !(MapGenBsp_PointContents(b, point) & 1)
        && (MapGenBsp_PointContents(b, below) & 1)
        && !(MapGenBsp_PointContents(b, head) & 1);
}

uint32_t MapGenBsp_PlacesIn(const mapgen_bsp_t *b, const float lo[3],
                            const float hi[3], float grid,
                            float (*out)[3], uint32_t cap)
{
    if (!b || grid < 1.0f || !lo || !hi)
        return 0;
    const mapgen_bsp_model_t *world = MapGenBsp_Model(b, 0);
    if (!world)
        return 0;
    /*
     * On the WORLD's lattice, not on the box's.
     *
     * Two samplings of the same map that start at different places find
     * different standing places, and an operator that asks "is there a stair
     * under me" has to be asking about the same stairs the gate counts.
     * MEASURED: a box-phased grid missed one climb place of q2dm1's and a
     * block was built on it.
     */
    float from[3], step_z = 0.0f;
    for (int a = 0; a < 3; a++) {
        const float base = a < 2 ? world->mins[a] + grid * 0.5f
                                 : world->mins[2] + 8.0f;
        const float pitch = a < 2 ? grid : 8.0f;
        float n = floorf((lo[a] - base) / pitch);
        if (n < 0.0f)
            n = 0.0f;
        from[a] = base + n * pitch;
        if (a == 2)
            step_z = pitch;
    }
    (void)step_z;
    uint32_t found = 0;
    for (float x = from[0]; x < hi[0]; x += grid)
      for (float y = from[1]; y < hi[1]; y += grid)
        for (float z = from[2]; z < hi[2]; z += 8.0f) {
            const float p[3] = { x, y, z };
            if (!MapGenBsp_Stands(b, p))
                continue;
            if (out && found < cap)
                memcpy(out[found], p, sizeof(p));
            found++;
            z += 40.0f;      /* one place per shelf, not one per unit */
        }
    return found;
}

uint32_t MapGenBsp_Places(const mapgen_bsp_t *b, float grid,
                          float (*out)[3], uint32_t cap)
{
    if (!b)
        return 0;
    const mapgen_bsp_model_t *world = MapGenBsp_Model(b, 0);
    if (!world)
        return 0;
    return MapGenBsp_PlacesIn(b, world->mins, world->maxs, grid, out, cap);
}

#define CLIMB_REACH 64.0f

uint32_t MapGenBsp_Climbs(const float (*places)[3], uint32_t count,
                          uint8_t *out_is_climb)
{
    if (!places || !out_is_climb)
        return 0;
    uint32_t climbs = 0;
    for (uint32_t i = 0; i < count; i++) {
        float heights[16];
        uint32_t num = 0;
        for (uint32_t j = 0; j < count && num < 16; j++) {
            if (fabsf(places[j][0] - places[i][0]) > CLIMB_REACH
                || fabsf(places[j][1] - places[i][1]) > CLIMB_REACH
                || fabsf(places[j][2] - places[i][2]) > 192.0f)
                continue;
            bool seen = false;
            for (uint32_t k = 0; k < num && !seen; k++)
                seen = fabsf(heights[k] - places[j][2]) <= 4.0f;
            if (!seen)
                heights[num++] = places[j][2];
        }
        out_is_climb[i] = num >= 3;
        climbs += out_is_climb[i];
    }
    return climbs;
}

/* ---- water that is not in anything ----------------------------------------- */

#define STANDING_LIQUID  (0x00000008 | 0x00000010 | 0x00000020)
#define STANDING_SOLID   0x00000001
#define STANDING_VERTICAL 0.5f      /* within thirty degrees of vertical */

/* ---- T-junctions in the compiled map -------------------------------------- */

/* How far off the line a vertex may be and still be ON it, and how far from
   either end it has to be to be INSIDE rather than a shared corner. Both are
   in units and both are the tolerances the seam contract already uses. */
#define TJUNC_ON_LINE  0.5f
#define TJUNC_INSIDE   1.0f
/* The grid the vertices are bucketed into. Big enough that an edge crosses
   few cells, small enough that a cell holds few vertices. */
#define TJUNC_CELL    64.0f
/* SURF_WARP: the flag the compiler sets on a turbulent liquid surface. */
#define TJUNC_SURF_WARP 0x00000008

typedef struct {
    uint32_t *idx;
    uint32_t  n, cap;
} tjunc_cell_t;

static bool tjunc_add(tjunc_cell_t *c, uint32_t i)
{
    if (c->n == c->cap) {
        const uint32_t want = c->cap ? c->cap * 2u : 8u;
        uint32_t *grown = realloc(c->idx, (size_t)want * sizeof(*grown));
        if (!grown)
            return false;
        c->idx = grown;
        c->cap = want;
    }
    c->idx[c->n++] = i;
    return true;
}

/* Is this face one a player swims in - drawn translucent over what is behind
   it, rather than in front of it? */
static bool tjunc_face_is_liquid(const mapgen_bsp_t *b, const mapgen_bsp_face_t *f)
{
    if (!f || f->texinfo < 0)
        return false;
    const mapgen_bsp_texinfo_t *tex = MapGenBsp_TexInfo(b, (uint32_t)f->texinfo);
    if (!tex)
        return false;
    if (tex->flags & TJUNC_SURF_WARP)
        return true;
    /* A liquid texture names itself: Quake II marks them with a leading * or
       ! in the wad, and the compiler keeps the name. */
    return tex->texture[0] == '*' || tex->texture[0] == '!';
}

const char *MapGenBsp_SeamsResultName(mapgen_bsp_seams_result_t r)
{
    switch (r) {
    case MAPGEN_SEAMS_OK:         return "OK";
    case MAPGEN_SEAMS_ERR_ARGS:   return "ERR_ARGS";
    case MAPGEN_SEAMS_ERR_MEMORY: return "ERR_MEMORY";
    case MAPGEN_SEAMS_ERR_FULL:   return "ERR_FULL";
    }
    return "ERR_UNKNOWN";
}

/* A quarter unit: finer than any tolerance in this file and coarser than the
   float noise two compiles of one room disagree by. */
static bool same_point(const float a[3], const float b[3])
{
    for (int k = 0; k < 3; k++)
        if (fabsf(a[k] - b[k]) > 0.25f)
            return false;
    return true;
}

bool MapGenBsp_SameSeam(const mapgen_bsp_seam_t *a, const mapgen_bsp_seam_t *b)
{
    if (!a || !b || !same_point(a->split, b->split))
        return false;
    return (same_point(a->from, b->from) && same_point(a->to, b->to))
        || (same_point(a->from, b->to) && same_point(a->to, b->from));
}

mapgen_bsp_seams_result_t MapGenBsp_Seams(const mapgen_bsp_t *b,
                                          mapgen_bsp_seam_t *out, uint32_t cap,
                                          uint32_t *out_count)
{
    return MapGenBsp_SeamsWithin(b, TJUNC_ON_LINE, out, cap, out_count);
}

mapgen_bsp_seams_result_t MapGenBsp_SeamsWithin(const mapgen_bsp_t *b,
                                                float on_line,
                                                mapgen_bsp_seam_t *out,
                                                uint32_t cap,
                                                uint32_t *out_count)
{
    if (out_count)
        *out_count = 0;
    if (!b)
        return MAPGEN_SEAMS_ERR_ARGS;

    const uint32_t nv = MapGenBsp_NumVertices(b);
    const uint32_t ne = MapGenBsp_NumEdges(b);
    const uint32_t nf = MapGenBsp_NumFaces(b);
    if (!nv || !ne || !nf)
        return MAPGEN_SEAMS_OK;

    /* Only the vertices some drawn face uses, and which edges an OPAQUE face
       draws: the lump can hold more than the faces refer to. */
    /* `used` marks a vertex some drawn face refers to; `opaque_vertex` marks
       one an OPAQUE face carries, which is the provenance the liquid rule
       needs on the other side of the pair. */
    uint8_t *used = calloc(nv, 1);
    uint8_t *opaque_vertex = calloc(nv, 1);
    uint8_t *opaque_edge = calloc(ne, 1);
    uint8_t *seen = calloc(ne, 1);
    /* Which model draws each face, so a seam can say whether it crosses one.
       A face belongs to the model whose firstface..numfaces range holds it. */
    uint32_t *face_model = calloc(nf, sizeof(*face_model));
    uint32_t *vertex_model = calloc(nv, sizeof(*vertex_model));
    uint32_t *edge_model = calloc(ne, sizeof(*edge_model));
    uint8_t *edge_model_known = calloc(ne, 1);
    if (!used || !opaque_vertex || !opaque_edge || !seen || !face_model
        || !vertex_model || !edge_model || !edge_model_known) {
        free(used); free(opaque_vertex); free(opaque_edge); free(seen);
        free(face_model); free(vertex_model);
        free(edge_model); free(edge_model_known);
        return MAPGEN_SEAMS_ERR_MEMORY;
    }
    for (uint32_t m = 0; m < MapGenBsp_NumModels(b); m++) {
        const mapgen_bsp_model_t *mod = MapGenBsp_Model(b, m);
        if (!mod)
            continue;
        for (int32_t f = mod->firstface;
             f < mod->firstface + mod->numfaces && f >= 0; f++)
            if ((uint32_t)f < nf)
                face_model[f] = m;
    }
    for (uint32_t i = 0; i < nf; i++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(b, i);
        if (!face)
            continue;
        const bool liquid = tjunc_face_is_liquid(b, face);
        for (int32_t e = 0; e < face->numedges; e++) {
            const int32_t se =
                MapGenBsp_SurfEdge(b, (uint32_t)(face->firstedge + e));
            const uint32_t ei = (uint32_t)(se < 0 ? -se : se);
            if (ei >= ne)
                continue;
            const mapgen_bsp_edge_t *edge = MapGenBsp_Edge(b, ei);
            if (!edge)
                continue;
            if (!liquid)
                opaque_edge[ei] = 1;
            if (edge->v[0] < nv) {
                used[edge->v[0]] = 1;
                vertex_model[edge->v[0]] = face_model[i];
                if (!liquid) opaque_vertex[edge->v[0]] = 1;
            }
            if (edge->v[1] < nv) {
                used[edge->v[1]] = 1;
                vertex_model[edge->v[1]] = face_model[i];
                if (!liquid) opaque_vertex[edge->v[1]] = 1;
            }
            if (!edge_model_known[ei]) {
                edge_model_known[ei] = 1;
                edge_model[ei] = face_model[i];
            }
        }
    }

    float lo[3] = { 1e9f, 1e9f, 1e9f }, hi[3] = { -1e9f, -1e9f, -1e9f };
    for (uint32_t i = 0; i < nv; i++) {
        if (!used[i])
            continue;
        const mapgen_bsp_vertex_t *v = MapGenBsp_Vertex(b, i);
        if (!v)
            continue;
        for (int a = 0; a < 3; a++) {
            if (v->point[a] < lo[a]) lo[a] = v->point[a];
            if (v->point[a] > hi[a]) hi[a] = v->point[a];
        }
    }
    if (lo[0] > hi[0]) {
        free(used); free(opaque_vertex); free(opaque_edge); free(seen);
        free(face_model); free(vertex_model);
        free(edge_model); free(edge_model_known);
        return MAPGEN_SEAMS_OK;
    }

    const int gx = (int)((hi[0] - lo[0]) / TJUNC_CELL) + 2;
    const int gy = (int)((hi[1] - lo[1]) / TJUNC_CELL) + 2;
    const int gz = (int)((hi[2] - lo[2]) / TJUNC_CELL) + 2;
    tjunc_cell_t *grid = calloc((size_t)gx * gy * gz, sizeof(*grid));
    if (!grid) {
        free(used); free(opaque_vertex); free(opaque_edge); free(seen);
        free(face_model); free(vertex_model);
        free(edge_model); free(edge_model_known);
        return MAPGEN_SEAMS_ERR_MEMORY;
    }
    bool grid_ok = true;
    for (uint32_t i = 0; i < nv && grid_ok; i++) {
        if (!used[i])
            continue;
        const mapgen_bsp_vertex_t *v = MapGenBsp_Vertex(b, i);
        const int x = (int)((v->point[0] - lo[0]) / TJUNC_CELL);
        const int y = (int)((v->point[1] - lo[1]) / TJUNC_CELL);
        const int z = (int)((v->point[2] - lo[2]) / TJUNC_CELL);
        /* A vertex that could not be bucketed is a vertex nothing will be
           tested against, and a seam missed for want of memory is a seam
           reported as absent. */
        grid_ok = tjunc_add(&grid[((size_t)z * gy + y) * gx + x], i);
    }
    if (!grid_ok) {
        for (size_t i = 0; i < (size_t)gx * gy * gz; i++)
            free(grid[i].idx);
        free(grid);
        free(used); free(opaque_vertex); free(opaque_edge); free(seen);
        free(face_model); free(vertex_model);
        free(edge_model); free(edge_model_known);
        return MAPGEN_SEAMS_ERR_MEMORY;
    }

    uint32_t found = 0;
    bool overflowed = false;
    for (uint32_t i = 0; i < nf; i++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(b, i);
        if (!face)
            continue;
        for (int32_t e = 0; e < face->numedges; e++) {
            const int32_t se =
                MapGenBsp_SurfEdge(b, (uint32_t)(face->firstedge + e));
            const uint32_t ei = (uint32_t)(se < 0 ? -se : se);
            if (ei >= ne || seen[ei])
                continue;
            seen[ei] = 1;
            const mapgen_bsp_edge_t *edge = MapGenBsp_Edge(b, ei);
            if (!edge || edge->v[0] >= nv || edge->v[1] >= nv)
                continue;
            const mapgen_bsp_vertex_t *pv = MapGenBsp_Vertex(b, edge->v[0]);
            const mapgen_bsp_vertex_t *qv = MapGenBsp_Vertex(b, edge->v[1]);
            if (!pv || !qv)
                continue;
            const float *P = pv->point, *Q = qv->point;
            const float d[3] = { Q[0] - P[0], Q[1] - P[1], Q[2] - P[2] };
            const float len = sqrtf(d[0]*d[0] + d[1]*d[1] + d[2]*d[2]);
            if (len < 2.0f * TJUNC_INSIDE)
                continue;

            int c0[3], c1[3];
            for (int a = 0; a < 3; a++) {
                const float m = P[a] < Q[a] ? P[a] : Q[a];
                const float M = P[a] < Q[a] ? Q[a] : P[a];
                c0[a] = (int)((m - lo[a] - on_line) / TJUNC_CELL);
                c1[a] = (int)((M - lo[a] + on_line) / TJUNC_CELL);
                if (c0[a] < 0) c0[a] = 0;
            }
            if (c1[0] >= gx) c1[0] = gx - 1;
            if (c1[1] >= gy) c1[1] = gy - 1;
            if (c1[2] >= gz) c1[2] = gz - 1;

            bool split = false;
            uint32_t splitter = 0;
            for (int z = c0[2]; z <= c1[2] && !split; z++)
              for (int y = c0[1]; y <= c1[1] && !split; y++)
                for (int x = c0[0]; x <= c1[0] && !split; x++) {
                    const tjunc_cell_t *c = &grid[((size_t)z * gy + y) * gx + x];
                    for (uint32_t k = 0; k < c->n && !split; k++) {
                        const uint32_t vi = c->idx[k];
                        if (vi == edge->v[0] || vi == edge->v[1])
                            continue;
                        const mapgen_bsp_vertex_t *vv = MapGenBsp_Vertex(b, vi);
                        if (!vv)
                            continue;
                        const float w[3] = { vv->point[0] - P[0],
                                             vv->point[1] - P[1],
                                             vv->point[2] - P[2] };
                        const float t = (w[0]*d[0] + w[1]*d[1] + w[2]*d[2])
                                      / (len * len);
                        if (t * len < TJUNC_INSIDE
                            || (1.0f - t) * len < TJUNC_INSIDE)
                            continue;
                        const float off[3] = { w[0] - t*d[0], w[1] - t*d[1],
                                               w[2] - t*d[2] };
                        if (sqrtf(off[0]*off[0] + off[1]*off[1] + off[2]*off[2])
                            > on_line)
                            continue;
                        split = true;
                        splitter = vi;
                    }
                }
            if (split) {
                /*
                 * One crack, once.
                 *
                 * Two faces that do not share an edge RECORD can still draw
                 * the same edge - the compiler emits a second edge with the
                 * same two vertices - and `seen` is per record, so the same
                 * hairline was counted twice. MEASURED on a flooded
                 * candidate: two entries with one split point and the ends
                 * swapped, which is one seam seen from both sides.
                 */
                bool already = false;
                if (out) {
                    mapgen_bsp_seam_t probe;
                    memcpy(probe.split, MapGenBsp_Vertex(b, splitter)->point,
                           sizeof(probe.split));
                    memcpy(probe.from, P, sizeof(probe.from));
                    memcpy(probe.to, Q, sizeof(probe.to));
                    for (uint32_t k = 0; k < found && k < cap && !already; k++)
                        already = MapGenBsp_SameSeam(&probe, &out[k]);
                }
                if (already)
                    continue;
                if (out && found < cap) {
                    mapgen_bsp_seam_t *s = &out[found];
                    memcpy(s->split, MapGenBsp_Vertex(b, splitter)->point,
                           sizeof(s->split));
                    memcpy(s->from, P, sizeof(s->from));
                    memcpy(s->to, Q, sizeof(s->to));
                    s->opaque_edge = opaque_edge[ei] != 0;
                    s->opaque_vertex = opaque_vertex[splitter] != 0;
                    s->edge_model = edge_model[ei];
                    s->vertex_model = vertex_model[splitter];
                } else if (out) {
                    overflowed = true;
                }
                found++;
            }
        }
    }

    for (size_t i = 0; i < (size_t)gx * gy * gz; i++)
        free(grid[i].idx);
    free(grid);
    free(used);
    free(opaque_vertex);
    free(opaque_edge);
    free(seen);
    free(face_model);
    free(vertex_model);
    free(edge_model);
    free(edge_model_known);

    if (out_count)
        *out_count = found;
    return overflowed ? MAPGEN_SEAMS_ERR_FULL : MAPGEN_SEAMS_OK;
}

uint32_t MapGenBsp_StandingWater(const mapgen_bsp_t *b, double *out_area)
{
    if (out_area)
        *out_area = 0.0;
    if (!b)
        return 0;

    uint32_t count = 0;
    double area = 0.0;
    const uint32_t faces = MapGenBsp_NumFaces(b);
    for (uint32_t f = 0; f < faces; f++) {
        const mapgen_bsp_face_t *face = MapGenBsp_Face(b, f);
        if (!face || face->numedges < 3)
            continue;
        const mapgen_bsp_plane_t *pl = MapGenBsp_Plane(b, face->planenum);
        if (!pl || fabsf(pl->normal[2]) > STANDING_VERTICAL)
            continue;

        /* Its corners, its middle, and its area - one pass over the fan. */
        float first[3] = { 0, 0, 0 }, prev[3] = { 0, 0, 0 };
        float centre[3] = { 0, 0, 0 };
        float sum[3] = { 0, 0, 0 };
        uint32_t n = 0;
        for (int32_t e = 0; e < face->numedges; e++) {
            const int32_t se =
                MapGenBsp_SurfEdge(b, (uint32_t)(face->firstedge + e));
            const mapgen_bsp_edge_t *edge =
                MapGenBsp_Edge(b, (uint32_t)(se < 0 ? -se : se));
            if (!edge)
                break;
            const mapgen_bsp_vertex_t *v =
                MapGenBsp_Vertex(b, se < 0 ? edge->v[1] : edge->v[0]);
            if (!v)
                break;
            if (!n) {
                memcpy(first, v->point, sizeof(first));
            } else if (n >= 2) {
                const float u[3] = { prev[0] - first[0], prev[1] - first[1],
                                     prev[2] - first[2] };
                const float w[3] = { v->point[0] - first[0],
                                     v->point[1] - first[1],
                                     v->point[2] - first[2] };
                sum[0] += u[1] * w[2] - u[2] * w[1];
                sum[1] += u[2] * w[0] - u[0] * w[2];
                sum[2] += u[0] * w[1] - u[1] * w[0];
            }
            for (int a = 0; a < 3; a++)
                centre[a] += v->point[a];
            memcpy(prev, v->point, sizeof(prev));
            n++;
        }
        if (n < 3)
            continue;
        for (int a = 0; a < 3; a++)
            centre[a] /= (float)n;

        float front[3], back[3];
        for (int a = 0; a < 3; a++) {
            front[a] = centre[a] + pl->normal[a] * 2.0f;
            back[a] = centre[a] - pl->normal[a] * 2.0f;
        }
        const int32_t cf = MapGenBsp_PointContents(b, front);
        const int32_t cb = MapGenBsp_PointContents(b, back);
        const bool water_air =
            ((cf & STANDING_LIQUID) && !(cb & (STANDING_LIQUID | STANDING_SOLID)))
            || ((cb & STANDING_LIQUID) && !(cf & (STANDING_LIQUID | STANDING_SOLID)));
        if (!water_air)
            continue;

        count++;
        area += 0.5 * sqrt((double)sum[0] * sum[0] + (double)sum[1] * sum[1]
                           + (double)sum[2] * sum[2]);
    }
    if (out_area)
        *out_area = area;
    return count;
}

int32_t MapGenBsp_PointContentsAt(const mapgen_bsp_t *b, int32_t headnode,
                                  const float point[3])
{
    if (!b || !point)
        return 0;
    const mapgen_bsp_leaf_t *lf = point_leaf_from(b, headnode, point);
    if (!lf)
        return 0;

    int32_t contents = lf->contents;
    for (uint32_t i = 0; i < lf->numleafbrushes; i++) {
        const mapgen_bsp_brush_t *br = &b->brushes[b->leafbrushes[lf->firstleafbrush + i]];
        bool inside = true;
        for (int32_t s = 0; s < br->numsides; s++) {
            const mapgen_bsp_brushside_t *side = &b->brushsides[br->firstside + s];
            const mapgen_bsp_plane_t *pl = &b->planes[side->planenum];
            float d = point[0] * pl->normal[0] + point[1] * pl->normal[1] +
                      point[2] * pl->normal[2] - pl->dist;
            if (d > 0) {
                inside = false;
                break;
            }
        }
        if (inside)
            contents |= br->contents;
    }
    return contents;
}

/* ------------------------------------------------------------------------ */

/* Canonical float text: fixed precision, no negative zero, locale-free.
   Written by hand rather than with printf("%f") so a locale that uses a comma
   for the decimal separator cannot change a digest (contract section 10). */
static size_t fmt_float(char *out, size_t cap, float value)
{
    double v = (double)value;
    bool negative = v < 0.0;
    if (negative)
        v = -v;

    /* Six decimals, matching the Python oracle. */
    double scaled = v * 1000000.0 + 0.5;
    if (!(scaled < 9.0e18))
        scaled = 0.0;                       /* NaN or absurd: canonicalize */
    uint64_t units = (uint64_t)scaled;
    uint64_t whole = units / 1000000u;
    uint64_t frac = units % 1000000u;

    if (whole == 0 && frac == 0)
        negative = false;                   /* kills -0.000000 */

    char buf[64];
    size_t n = 0;
    if (negative)
        buf[n++] = '-';

    char digits[24];
    size_t d = 0;
    if (whole == 0) {
        digits[d++] = '0';
    } else {
        while (whole && d < sizeof(digits)) {
            digits[d++] = (char)('0' + (whole % 10u));
            whole /= 10u;
        }
    }
    while (d)
        buf[n++] = digits[--d];

    buf[n++] = '.';
    for (int place = 100000; place >= 1; place /= 10) {
        buf[n++] = (char)('0' + (frac / (uint64_t)place) % 10u);
    }
    buf[n] = '\0';

    if (out && cap) {
        size_t copy = n < cap - 1 ? n : cap - 1;
        memcpy(out, buf, copy);
        out[copy] = '\0';
    }
    return n;
}

typedef struct {
    char  *out;
    size_t capacity;
    size_t needed;
} sink_t;

static void sink_str(sink_t *s, const char *text)
{
    size_t n = strlen(text);
    if (s->out && s->needed < s->capacity) {
        size_t room = s->capacity - 1 - s->needed;
        size_t copy = n < room ? n : room;
        memcpy(s->out + s->needed, text, copy);
    }
    s->needed += n;
}

static void sink_u64(sink_t *s, uint64_t v)
{
    char buf[24];
    size_t n = 0;
    if (!v) {
        buf[n++] = '0';
    } else {
        char tmp[24];
        size_t t = 0;
        while (v) {
            tmp[t++] = (char)('0' + (v % 10u));
            v /= 10u;
        }
        while (t)
            buf[n++] = tmp[--t];
    }
    buf[n] = '\0';
    sink_str(s, buf);
}

static void sink_i64(sink_t *s, int64_t v)
{
    if (v < 0) {
        sink_str(s, "-");
        sink_u64(s, (uint64_t)(-(v + 1)) + 1u);
    } else {
        sink_u64(s, (uint64_t)v);
    }
}

static void sink_f(sink_t *s, float v)
{
    char buf[64];
    fmt_float(buf, sizeof(buf), v);
    sink_str(s, buf);
}

size_t MapGenBsp_CanonicalText(const mapgen_bsp_t *b, char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!b) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }

    sink_str(&s, "format="); sink_str(&s, b->extended ? "QBSP" : "IBSP"); sink_str(&s, "\n");
    sink_str(&s, "planes="); sink_u64(&s, b->num_planes); sink_str(&s, "\n");
    for (uint32_t i = 0; i < b->num_planes; i++) {
        const mapgen_bsp_plane_t *pl = &b->planes[i];
        sink_str(&s, "plane=");
        sink_f(&s, pl->normal[0]); sink_str(&s, ",");
        sink_f(&s, pl->normal[1]); sink_str(&s, ",");
        sink_f(&s, pl->normal[2]); sink_str(&s, ",");
        sink_f(&s, pl->dist); sink_str(&s, ",");
        sink_i64(&s, pl->type); sink_str(&s, "\n");
    }

    sink_str(&s, "brushes="); sink_u64(&s, b->num_brushes); sink_str(&s, "\n");
    for (uint32_t i = 0; i < b->num_brushes; i++) {
        sink_str(&s, "brush=");
        sink_i64(&s, b->brushes[i].firstside); sink_str(&s, ",");
        sink_i64(&s, b->brushes[i].numsides); sink_str(&s, ",");
        sink_i64(&s, b->brushes[i].contents); sink_str(&s, "\n");
    }

    sink_str(&s, "brushsides="); sink_u64(&s, b->num_brushsides); sink_str(&s, "\n");
    for (uint32_t i = 0; i < b->num_brushsides; i++) {
        sink_str(&s, "side=");
        sink_u64(&s, b->brushsides[i].planenum); sink_str(&s, ",");
        sink_i64(&s, b->brushsides[i].texinfo); sink_str(&s, "\n");
    }

    sink_str(&s, "texinfo="); sink_u64(&s, b->num_texinfo); sink_str(&s, "\n");
    for (uint32_t i = 0; i < b->num_texinfo; i++) {
        sink_str(&s, "tex=");
        sink_str(&s, b->texinfo[i].texture); sink_str(&s, ",");
        sink_i64(&s, b->texinfo[i].flags); sink_str(&s, ",");
        sink_i64(&s, b->texinfo[i].value); sink_str(&s, ",");
        sink_i64(&s, b->texinfo[i].nexttexinfo); sink_str(&s, "\n");
    }

    sink_str(&s, "nodes="); sink_u64(&s, b->num_nodes); sink_str(&s, "\n");
    for (uint32_t i = 0; i < b->num_nodes; i++) {
        sink_str(&s, "node=");
        sink_u64(&s, b->nodes[i].planenum); sink_str(&s, ",");
        sink_i64(&s, b->nodes[i].children[0]); sink_str(&s, ",");
        sink_i64(&s, b->nodes[i].children[1]); sink_str(&s, "\n");
    }

    sink_str(&s, "leafs="); sink_u64(&s, b->num_leafs); sink_str(&s, "\n");
    for (uint32_t i = 0; i < b->num_leafs; i++) {
        const mapgen_bsp_leaf_t *lf = &b->leafs[i];
        sink_str(&s, "leaf=");
        sink_i64(&s, lf->contents); sink_str(&s, ",");
        sink_i64(&s, lf->cluster); sink_str(&s, ",");
        sink_i64(&s, lf->area); sink_str(&s, ",");
        sink_u64(&s, lf->firstleafbrush); sink_str(&s, ",");
        sink_u64(&s, lf->numleafbrushes); sink_str(&s, "\n");
    }

    sink_str(&s, "leafbrushes="); sink_u64(&s, b->num_leafbrushes); sink_str(&s, "\n");
    sink_str(&s, "lb=");
    for (uint32_t i = 0; i < b->num_leafbrushes; i++) {
        if (i)
            sink_str(&s, ",");
        sink_u64(&s, b->leafbrushes[i]);
    }
    sink_str(&s, "\n");

    sink_str(&s, "models="); sink_u64(&s, b->num_models); sink_str(&s, "\n");
    for (uint32_t i = 0; i < b->num_models; i++) {
        const mapgen_bsp_model_t *m = &b->models[i];
        sink_str(&s, "model=");
        sink_f(&s, m->mins[0]); sink_str(&s, ",");
        sink_f(&s, m->mins[1]); sink_str(&s, ",");
        sink_f(&s, m->mins[2]); sink_str(&s, ",");
        sink_f(&s, m->maxs[0]); sink_str(&s, ",");
        sink_f(&s, m->maxs[1]); sink_str(&s, ",");
        sink_f(&s, m->maxs[2]); sink_str(&s, ",");
        sink_i64(&s, m->headnode); sink_str(&s, "\n");
    }

    sink_str(&s, "faces="); sink_u64(&s, b->num_faces); sink_str(&s, "\n");
    sink_str(&s, "entitychars="); sink_u64(&s, b->entity_length); sink_str(&s, "\n");

    if (out && capacity) {
        size_t end = s.needed < capacity - 1 ? s.needed : capacity - 1;
        out[end] = '\0';
    }
    return s.needed;
}

uint64_t MapGenBsp_CanonicalDigest(const mapgen_bsp_t *b)
{
    size_t needed = MapGenBsp_CanonicalText(b, NULL, 0);
    char *text = malloc(needed + 1);
    if (!text)
        return 0;
    MapGenBsp_CanonicalText(b, text, needed + 1);

    uint64_t hash = 1469598103934665603ull;      /* FNV-1a 64 offset basis */
    for (size_t i = 0; i < needed; i++) {
        hash ^= (uint8_t)text[i];
        hash *= 1099511628211ull;
    }
    free(text);
    return hash;
}

const char *MapGenBsp_ResultName(mapgen_bsp_result_t r)
{
    switch (r) {
    case MAPGEN_BSP_OK:                     return "OK";
    case MAPGEN_BSP_ERR_ARGUMENT:           return "ARGUMENT";
    case MAPGEN_BSP_ERR_TOO_SMALL:          return "TOO_SMALL";
    case MAPGEN_BSP_ERR_TOO_LARGE:          return "TOO_LARGE";
    case MAPGEN_BSP_ERR_BAD_IDENT:          return "BAD_IDENT";
    case MAPGEN_BSP_ERR_BAD_VERSION:        return "BAD_VERSION";
    case MAPGEN_BSP_ERR_LUMP_OUT_OF_BOUNDS: return "LUMP_OUT_OF_BOUNDS";
    case MAPGEN_BSP_ERR_LUMP_ODD_SIZE:      return "LUMP_ODD_SIZE";
    case MAPGEN_BSP_ERR_LIMIT_EXCEEDED:     return "LIMIT_EXCEEDED";
    case MAPGEN_BSP_ERR_BAD_INDEX:          return "BAD_INDEX";
    case MAPGEN_BSP_ERR_NO_MODELS:          return "NO_MODELS";
    case MAPGEN_BSP_ERR_ENTSTRING:          return "ENTSTRING";
    case MAPGEN_BSP_ERR_OUT_OF_MEMORY:      return "OUT_OF_MEMORY";
    default:                                return "UNKNOWN";
    }
}

/* ==== file or memory (ledger row 411, Fable's brief 8) - inc/common/mapgen_fs.h ================================ */

#include "common/mapgen_fs.h"
#include <errno.h>
#ifdef _WIN32
#include <direct.h>
#include <io.h>
#include <fcntl.h>
#include <process.h>
#include <windows.h>
#else
#include <sys/stat.h>
#endif

typedef struct {
    char magic[8];
    uint64_t room, size, present;
} mapgen_fs_head_t;

#define MAPGEN_FS_MAX_SECTIONS 96
#define MAPGEN_FS_KEY 600

typedef struct {
    char key[MAPGEN_FS_KEY];        /* the path after "mem:", slashes forward */
#ifdef _WIN32
    HANDLE handle;
#endif
    mapgen_fs_head_t *head;
    uint64_t room;
} mapgen_fs_section_t;

static mapgen_fs_section_t g_fs_sections[MAPGEN_FS_MAX_SECTIONS];
static uint64_t g_fs_room = 32ull << 20, g_fs_live, g_fs_peak;
#ifdef _WIN32
static CRITICAL_SECTION g_fs_lock;

/* made before main runs: the walk's threads and the stream collectors may come here at once */
static void fs_init(void) __attribute__((constructor));
static void fs_init(void)
{
    InitializeCriticalSection(&g_fs_lock);
}

static void fs_lock(void)
{
    EnterCriticalSection(&g_fs_lock);
}

static void fs_unlock(void)
{
    LeaveCriticalSection(&g_fs_lock);
}
#else
static void fs_lock(void) {}
static void fs_unlock(void) {}
#endif

bool MapGenFs_IsMem(const char *path)
{
    return path && !strncmp(path, "mem:", 4);
}

void MapGenFs_SetRoom(uint64_t bytes)
{
    if (bytes >= (1ull << 20))
        g_fs_room = bytes;
}

uint64_t MapGenFs_Room(void)
{
    return g_fs_room;
}

uint64_t MapGenFs_LiveBytes(void)
{
    return g_fs_live;
}

uint64_t MapGenFs_PeakBytes(void)
{
    return g_fs_peak;
}

static volatile long long g_fs_pipe;

void MapGenFs_NotePipe(uint64_t bytes)
{
#ifdef _WIN32
    InterlockedExchangeAdd64(&g_fs_pipe, (long long)bytes);
#else
    g_fs_pipe += (long long)bytes;
#endif
}

uint64_t MapGenFs_PipeBytes(void)
{
    return (uint64_t)g_fs_pipe;
}

uint64_t MapGenFs_SelfWritten(void)
{
#ifdef _WIN32
    IO_COUNTERS io;
    return GetProcessIoCounters(GetCurrentProcess(), &io) ? io.WriteTransferCount : 0;
#else
    return 0;
#endif
}

static void fs_key(const char *path, char *key)
{
    snprintf(key, MAPGEN_FS_KEY, "%s", path + 4);
    for (char *p = key; *p; p++)
        if (*p == '\\')
            *p = '/';
}

static mapgen_fs_section_t *fs_find(const char *path)
{
    char key[MAPGEN_FS_KEY];
    fs_key(path, key);
    for (int i = 0; i < MAPGEN_FS_MAX_SECTIONS; i++)
        if (g_fs_sections[i].head && !strcmp(g_fs_sections[i].key, key))
            return &g_fs_sections[i];
    return NULL;
}

#ifdef _WIN32
/* a section of this process, made if it is not yet */
static mapgen_fs_section_t *fs_make(const char *path)
{
    mapgen_fs_section_t *s = fs_find(path);
    if (s)
        return s;
    for (int i = 0; i < MAPGEN_FS_MAX_SECTIONS && !s; i++)
        if (!g_fs_sections[i].head)
            s = &g_fs_sections[i];
    if (!s)
        return NULL;
    fs_key(path, s->key);
    char name[MAPGEN_FS_KEY + 32];
    snprintf(name, sizeof(name), "Local\\q2mem_%s", s->key);
    const uint64_t total = g_fs_room + sizeof(mapgen_fs_head_t);
    s->handle = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, (DWORD)(total >> 32),
                                   (DWORD)(total & 0xffffffffu), name);
    if (!s->handle) {
        s->key[0] = 0;
        return NULL;
    }
    s->head = (mapgen_fs_head_t *)MapViewOfFile(s->handle, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    if (!s->head) {
        CloseHandle(s->handle);
        s->key[0] = 0;
        return NULL;
    }
    if (memcmp(s->head->magic, "Q2MEM1\0\0", 8)) {
        memcpy(s->head->magic, "Q2MEM1\0\0", 8);
        s->head->room = g_fs_room;
        s->head->size = 0;
        s->head->present = 0;
    }
    s->room = s->head->room;
    g_fs_live += s->room;
    if (g_fs_live > g_fs_peak)
        g_fs_peak = g_fs_live;
    return s;
}

static void fs_drop(mapgen_fs_section_t *s)
{
    UnmapViewOfFile(s->head);
    CloseHandle(s->handle);
    g_fs_live -= s->room;
    memset(s, 0, sizeof(*s));
}
#endif

static const char *const g_fs_exts[] = { ".map", ".bsp", ".prt", ".pts", ".replay.map" };

bool MapGenFs_MakeDir(const char *dir, const char *name)
{
    if (!MapGenFs_IsMem(dir)) {
#ifdef _WIN32
        return _mkdir(dir) == 0 || errno == EEXIST;
#else
        return mkdir(dir, 0777) == 0 || errno == EEXIST;
#endif
    }
#ifdef _WIN32
    fs_lock();
    bool ok = true;
    for (size_t i = 0; i < sizeof(g_fs_exts) / sizeof(g_fs_exts[0]) && ok; i++) {
        char path[MAPGEN_FS_KEY + 64];
        snprintf(path, sizeof(path), "%s/%s%s", dir, name, g_fs_exts[i]);
        ok = fs_make(path) != NULL;
    }
    fs_unlock();
    return ok;
#else
    (void)name;
    return false;
#endif
}

static bool fs_in_dir(const char *key, const char *dirkey)
{
    const size_t n = strlen(dirkey);
    return !strncmp(key, dirkey, n) && key[n] == '/' && !strchr(key + n + 1, '/');
}

void MapGenFs_EmptyDir(const char *dir)
{
    if (!MapGenFs_IsMem(dir)) {
#ifdef _WIN32
        char pattern[1100];
        snprintf(pattern, sizeof(pattern), "%s/*", dir);
        struct _finddata_t fd;
        intptr_t h = _findfirst(pattern, &fd);
        if (h == -1)
            return;
        do {
            if (fd.attrib & _A_SUBDIR)
                continue;
            char path[1400];
            snprintf(path, sizeof(path), "%s/%s", dir, fd.name);
            remove(path);
        } while (_findnext(h, &fd) == 0);
        _findclose(h);
#endif
        return;
    }
    char dirkey[MAPGEN_FS_KEY];
    fs_key(dir, dirkey);
    fs_lock();
    for (int i = 0; i < MAPGEN_FS_MAX_SECTIONS; i++)
        if (g_fs_sections[i].head && fs_in_dir(g_fs_sections[i].key, dirkey)) {
            g_fs_sections[i].head->present = 0;
            g_fs_sections[i].head->size = 0;
        }
    fs_unlock();
}

void MapGenFs_ReleaseDir(const char *dir)
{
#ifdef _WIN32
    if (!MapGenFs_IsMem(dir))
        return;
    char dirkey[MAPGEN_FS_KEY];
    fs_key(dir, dirkey);
    fs_lock();
    for (int i = 0; i < MAPGEN_FS_MAX_SECTIONS; i++)
        if (g_fs_sections[i].head && fs_in_dir(g_fs_sections[i].key, dirkey))
            fs_drop(&g_fs_sections[i]);
    fs_unlock();
#else
    (void)dir;
#endif
}

void MapGenFs_ReleaseTries(const char *root, const char *keep)
{
#ifdef _WIN32
    if (!MapGenFs_IsMem(root))
        return;
    char rootkey[MAPGEN_FS_KEY], keepkey[MAPGEN_FS_KEY] = "";
    fs_key(root, rootkey);
    if (MapGenFs_IsMem(keep))
        fs_key(keep, keepkey);
    const size_t n = strlen(rootkey), k = strlen(keepkey);
    fs_lock();
    for (int i = 0; i < MAPGEN_FS_MAX_SECTIONS; i++) {
        mapgen_fs_section_t *s = &g_fs_sections[i];
        if (!s->head || strncmp(s->key, rootkey, n) || strncmp(s->key + n, "/try_", 5))
            continue;
        if (k && !strncmp(s->key, keepkey, k) && s->key[k] == '/')
            continue;
        fs_drop(s);
    }
    fs_unlock();
#else
    (void)root;
    (void)keep;
#endif
}

bool MapGenFs_Read(const char *path, uint8_t **data, size_t *size)
{
    *data = NULL;
    *size = 0;
    if (!MapGenFs_IsMem(path)) {
        FILE *f = fopen(path, "rb");
        if (!f)
            return false;
        if (fseek(f, 0, SEEK_END) != 0) {
            fclose(f);
            return false;
        }
        const long n = ftell(f);
        if (n < 0 || fseek(f, 0, SEEK_SET) != 0) {
            fclose(f);
            return false;
        }
        uint8_t *raw = malloc((size_t)n + 1);
        if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
            fclose(f);
            free(raw);
            return false;
        }
        fclose(f);
        raw[n] = 0;
        *data = raw;
        *size = (size_t)n;
        return true;
    }
    fs_lock();
    mapgen_fs_section_t *s = fs_find(path);
    bool ok = false;
    if (s && s->head->present && s->head->size <= s->room) {
        uint8_t *raw = malloc((size_t)s->head->size + 1);
        if (raw) {
            memcpy(raw, (const uint8_t *)(s->head + 1), (size_t)s->head->size);
            raw[s->head->size] = 0;
            *data = raw;
            *size = (size_t)s->head->size;
            ok = true;
        }
    }
    fs_unlock();
    return ok;
}

bool MapGenFs_Write(const char *path, const void *data, size_t size)
{
    if (!MapGenFs_IsMem(path)) {
        FILE *f = fopen(path, "wb");
        if (!f)
            return false;
        const bool ok = fwrite(data, 1, size, f) == size;
        return fclose(f) == 0 && ok;
    }
    fs_lock();
    mapgen_fs_section_t *s = fs_find(path);
    bool ok = false;
    if (s && size <= s->room) {
        s->head->present = 0;
        memcpy((uint8_t *)(s->head + 1), data, size);
        s->head->size = size;
        s->head->present = 1;
        ok = true;
    }
    fs_unlock();
    return ok;
}

bool MapGenFs_Exists(const char *path, uint64_t *size)
{
    if (size)
        *size = 0;
    if (!MapGenFs_IsMem(path)) {
        FILE *f = fopen(path, "rb");
        if (!f)
            return false;
        if (size && fseek(f, 0, SEEK_END) == 0) {
            const long n = ftell(f);
            *size = n > 0 ? (uint64_t)n : 0;
        }
        fclose(f);
        return true;
    }
    fs_lock();
    mapgen_fs_section_t *s = fs_find(path);
    const bool here = s && s->head->present;
    if (here && size)
        *size = s->head->size;
    fs_unlock();
    return here;
}

void MapGenFs_Remove(const char *path)
{
    if (!MapGenFs_IsMem(path)) {
        remove(path);
        return;
    }
    fs_lock();
    mapgen_fs_section_t *s = fs_find(path);
    if (s) {
        s->head->present = 0;
        s->head->size = 0;
    }
    fs_unlock();
}

/* ---- a stdio stream onto a section ---- */

#ifdef _WIN32
typedef struct {
    FILE *f;
    int rd;
    HANDLE thread;
    uint8_t *buf;
    size_t len, cap;
    char path[MAPGEN_FS_KEY + 8];
} mapgen_fs_stream_t;

static mapgen_fs_stream_t g_fs_streams[8];

static unsigned __stdcall fs_collect(void *arg)
{
    mapgen_fs_stream_t *s = (mapgen_fs_stream_t *)arg;
    uint8_t chunk[65536];
    int n;
    while ((n = _read(s->rd, chunk, sizeof(chunk))) > 0) {
        if (s->len + (size_t)n > s->cap) {
            size_t cap = (s->len + (size_t)n) * 2;
            uint8_t *grown = realloc(s->buf, cap);
            if (!grown)
                break;
            s->buf = grown;
            s->cap = cap;
        }
        memcpy(s->buf + s->len, chunk, (size_t)n);
        s->len += (size_t)n;
        MapGenFs_NotePipe((uint64_t)n);
    }
    _close(s->rd);
    return 0;
}
#endif

FILE *MapGenFs_OpenWrite(const char *path, const char *mode)
{
    if (!MapGenFs_IsMem(path))
        return fopen(path, mode);
#ifdef _WIN32
    if (!MapGenFs_Exists(path, NULL)) {
        /* the section must have been made: a write to one nobody made is refused, as the compiler refuses it */
        fs_lock();
        const bool made = fs_find(path) != NULL;
        fs_unlock();
        if (!made)
            return NULL;
    }
    fs_lock();
    mapgen_fs_stream_t *s = NULL;
    for (int i = 0; i < 8 && !s; i++)
        if (!g_fs_streams[i].f)
            s = &g_fs_streams[i];
    fs_unlock();
    if (!s)
        return NULL;
    memset(s, 0, sizeof(*s));
    snprintf(s->path, sizeof(s->path), "%s", path);
    int fds[2];
    const bool text = strchr(mode, 'b') == NULL;
    if (_pipe(fds, 1 << 16, text ? _O_TEXT : _O_BINARY))
        return NULL;
    s->rd = fds[0];
    _setmode(s->rd, _O_BINARY);
    s->thread = (HANDLE)_beginthreadex(NULL, 0, fs_collect, s, 0, NULL);
    s->f = _fdopen(fds[1], mode);
    if (!s->f) {
        _close(fds[1]);
        WaitForSingleObject(s->thread, INFINITE);
        CloseHandle(s->thread);
        free(s->buf);
        memset(s, 0, sizeof(*s));
        return NULL;
    }
    return s->f;
#else
    return NULL;
#endif
}

int MapGenFs_Close(FILE *f)
{
#ifdef _WIN32
    for (int i = 0; f && i < 8; i++) {
        mapgen_fs_stream_t *s = &g_fs_streams[i];
        if (s->f != f)
            continue;
        int r = fclose(f);
        WaitForSingleObject(s->thread, INFINITE);
        CloseHandle(s->thread);
        if (!MapGenFs_Write(s->path, s->buf ? s->buf : (const uint8_t *)"", s->len))
            r = EOF;
        free(s->buf);
        memset(s, 0, sizeof(*s));
        return r;
    }
#endif
    return f ? fclose(f) : EOF;
}
