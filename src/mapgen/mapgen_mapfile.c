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
 * MAPGEN-1 - writing the `.map`.
 *
 * Integers printed by hand, LF line endings, and a winding derived from the
 * face rather than remembered from a convention.
 */

#include "common/mapgen_mapfile.h"

#include <stdlib.h>
#include <string.h>

const char *MapGenMapFile_ResultName(mapgen_mapfile_result_t r)
{
    switch (r) {
    case MAPGEN_MAPFILE_OK:             return "OK";
    case MAPGEN_MAPFILE_ERR_ARGS:       return "ERR_ARGS";
    case MAPGEN_MAPFILE_ERR_MEMORY:     return "ERR_MEMORY";
    case MAPGEN_MAPFILE_ERR_NO_BRUSHES: return "ERR_NO_BRUSHES";
    case MAPGEN_MAPFILE_ERR_NO_MATERIAL: return "ERR_NO_MATERIAL";
    }
    return "ERR_UNKNOWN";
}

/* ---- the winding --------------------------------------------------------- */

/*
 * Which axis a face looks along, and which way.
 *
 * The three points are built from that rather than written out six times:
 * with `u` and `v` the other two axes in order, `e_u x e_v = e_a`, so laying
 * p0 along u and p2 along v gives a normal along +a, and swapping them gives
 * -a. qbsp3 computes the plane as `(p0 - p1) x (p2 - p1)`, which is what this
 * is arranged for.
 */
static void face_axis(mapgen_face_t face, int *axis, int *sign)
{
    switch (face) {
    case MAPGEN_FACE_EAST:   *axis = 0; *sign = +1; break;
    case MAPGEN_FACE_WEST:   *axis = 0; *sign = -1; break;
    case MAPGEN_FACE_NORTH:  *axis = 1; *sign = +1; break;
    case MAPGEN_FACE_SOUTH:  *axis = 1; *sign = -1; break;
    case MAPGEN_FACE_TOP:    *axis = 2; *sign = +1; break;
    case MAPGEN_FACE_BOTTOM:
    default:                 *axis = 2; *sign = -1; break;
    }
}

void MapGenMapFile_FacePoints(const mapgen_brush_t *brush, mapgen_face_t face,
                              int32_t points[3][3])
{
    if (!brush || !points)
        return;

    int axis = 0, sign = 1;
    face_axis(face, &axis, &sign);
    const int u = (axis + 1) % 3;
    const int v = (axis + 2) % 3;
    const int32_t plane = sign > 0 ? brush->maxs[axis] : brush->mins[axis];

    for (int p = 0; p < 3; p++) {
        points[p][axis] = plane;
        points[p][u] = brush->mins[u];
        points[p][v] = brush->mins[v];
    }
    /* p1 stays at the low corner; p0 and p2 step out along u and v, in the
       order that puts the normal on the outside. */
    if (sign > 0) {
        points[0][u] = brush->maxs[u];
        points[2][v] = brush->maxs[v];
    } else {
        points[0][v] = brush->maxs[v];
        points[2][u] = brush->maxs[u];
    }
}

/*
 * Valve 220 texture axes, from the face's dominant normal - the conventional
 * Quake mapping, so a texture on a floor runs the way a mapper expects.
 */
static void face_texture_axes(mapgen_face_t face, int32_t u_axis[3],
                              int32_t v_axis[3])
{
    memset(u_axis, 0, 3 * sizeof(int32_t));
    memset(v_axis, 0, 3 * sizeof(int32_t));
    switch (face) {
    case MAPGEN_FACE_TOP:
    case MAPGEN_FACE_BOTTOM:
        u_axis[0] = 1;
        v_axis[1] = -1;
        break;
    case MAPGEN_FACE_EAST:
    case MAPGEN_FACE_WEST:
        u_axis[1] = 1;
        v_axis[2] = -1;
        break;
    case MAPGEN_FACE_NORTH:
    case MAPGEN_FACE_SOUTH:
    default:
        u_axis[0] = 1;
        v_axis[2] = -1;
        break;
    }
}

/* ---- the sink ------------------------------------------------------------ */

typedef struct {
    char  *text;
    size_t length;
    size_t capacity;
    bool   failed;
} out_t;

static void emit(out_t *o, const char *text)
{
    if (o->failed)
        return;
    const size_t n = strlen(text);
    if (o->length + n + 1 > o->capacity) {
        size_t want = o->capacity ? o->capacity * 2 : 65536;
        while (want < o->length + n + 1)
            want *= 2;
        char *grown = realloc(o->text, want);
        if (!grown) {
            o->failed = true;
            return;
        }
        o->text = grown;
        o->capacity = want;
    }
    memcpy(o->text + o->length, text, n);
    o->length += n;
    o->text[o->length] = '\0';
}

/* By hand, because printf's %d is fine but %f is not, and one of them being
   locale-free is not worth the other being locale-dependent. */
static void emit_i32(out_t *o, int32_t value)
{
    char buf[16], tmp[16];
    size_t n = 0, t = 0;
    uint32_t u = value < 0 ? (uint32_t)(-(int64_t)value) : (uint32_t)value;
    if (value < 0)
        buf[n++] = '-';
    if (!u) {
        tmp[t++] = '0';
    } else {
        while (u) {
            tmp[t++] = (char)('0' + (u % 10u));
            u /= 10u;
        }
    }
    while (t)
        buf[n++] = tmp[--t];
    buf[n] = '\0';
    emit(o, buf);
}

static void emit_point(out_t *o, const int32_t p[3])
{
    emit(o, "( ");
    for (int axis = 0; axis < 3; axis++) {
        emit_i32(o, p[axis]);
        emit(o, " ");
    }
    emit(o, ")");
}

/* ---- writing ------------------------------------------------------------- */

/*
 * One brush, faces and all. Shared by worldspawn and by every brush entity,
 * so a door's faces are wound exactly the way the world's are.
 *
 * Returns false when a material has no name in the model, which is the one
 * failure this can have and the caller turns into ERR_NO_MATERIAL.
 */
static bool emit_brush(out_t *o, const mapgen_brush_t *b,
                       const mapgen_mix_t *model)
{
    emit(o, "{\n");
        for (uint32_t f = 0; f < MAPGEN_FACE_COUNT; f++) {
            const char *texture = MapGenMix_MaterialName(model, b->material[f]);
            if (!texture) {
                return false;
            }

            int32_t points[3][3];
            MapGenMapFile_FacePoints(b, (mapgen_face_t)f, points);
            for (int p = 0; p < 3; p++) {
                emit_point(o, points[p]);
                emit(o, " ");
            }

            emit(o, texture);

            int32_t u_axis[3], v_axis[3];
            face_texture_axes((mapgen_face_t)f, u_axis, v_axis);
            emit(o, " [ ");
            for (int axis = 0; axis < 3; axis++) {
                emit_i32(o, u_axis[axis]);
                emit(o, " ");
            }
            emit(o, "0 ] [ ");
            for (int axis = 0; axis < 3; axis++) {
                emit_i32(o, v_axis[axis]);
                emit(o, " ");
            }
            /*
             * Rotation, then both scales.
             *
             * Then nothing, for almost every face. The optional
             * contents/flags/value triple OVERRIDES what the texture itself
             * declares (`map.c:626-634`), and the point of choosing a material
             * the corpus used is to inherit what that material IS - a light
             * texture that stops emitting because a generator wrote three
             * zeroes after it is a texture nobody chose.
             *
             * An EMITTING face is the exception, and it has to be. A .wal
             * almost always carries value 0 and the map says how bright this
             * fitting is; a face that inherits gets SURF_LIGHT with no
             * brightness, which is a light that emits nothing. MEASURED: maps
             * lit that way came out at a lightmap mean of 0.1 to 11 where a
             * real map sits near 55. So the triple is written here, with the
             * flags the material already declares and the value the corpus
             * used it at - nothing invented, and nothing else touched.
             */
            const int32_t emits =
                MapGenMix_MaterialLightValue(model, b->material[f]);
            if (emits > 0) {
                /*
                 * And the material's OWN contents in the first slot, not zero.
                 *
                 * The triple overrides all three, and a zero there is not
                 * "nothing to say": the compiler reads it as a brush with no
                 * visible contents and makes it SOLID (`map.c:643`). MEASURED
                 * on the invented map of 2026-09-07 evening: every pool the
                 * layout sank into a floor came out a solid block, because
                 * `e2u3/sewer1` is a slime that EMITS - value 500 - so it took
                 * this branch and lost the contents its own .wal declares. The
                 * map the PO walked had no water in it at all, and this is
                 * why.
                 */
                emit(o, "0 ] 0 1 1 ");
                emit_i32(o, MapGenMix_MaterialContents(model, b->material[f]));
                emit(o, " ");
                emit_i32(o, MapGenMix_MaterialSurfaceFlags(model, b->material[f]));
                emit(o, " ");
                emit_i32(o, emits);
                emit(o, "\n");
            } else {
                emit(o, "0 ] 0 1 1\n");
            }
        }
    emit(o, "}\n");
    return true;
}

mapgen_mapfile_result_t MapGenMapFile_Write(const mapgen_brushwork_t *work,
                                            const mapgen_entities_t *entities,
                                            const mapgen_mix_t *model,
                                            const mapgen_recipe_t *recipe,
                                            char **out_text, size_t *out_size)
{
    if (out_text)
        *out_text = NULL;
    if (out_size)
        *out_size = 0;
    if (!work || !entities || !model || !recipe || !out_text || !out_size)
        return MAPGEN_MAPFILE_ERR_ARGS;
    if (!MapGenBrush_Count(work))
        return MAPGEN_MAPFILE_ERR_NO_BRUSHES;

    out_t o;
    memset(&o, 0, sizeof(o));

    emit(&o, "// Game: Quake 2\n// Format: Valve\n");
    emit(&o, "// Generated by Q2PRO-X MAPGEN-1\n");

    /* --- worldspawn -------------------------------------------------------- */
    emit(&o, "{\n\"classname\" \"worldspawn\"\n");
    /*
     * Without this the compiler parses the file as the OLD texture format
     * and dies on the first brush - `map.c:565` branches on it and it
     * defaults to 0. The parser strips the key again, so it never reaches
     * the BSP.
     */
    emit(&o, "\"mapversion\" \"220\"\n");
    /*
     * The slug, not the display name: the display name may be Russian, and the
     * compiler's UTF-8 behaviour is not qualified. It is stored exactly in the
     * recipe, which is where it belongs anyway.
     */
    emit(&o, "\"message\" \"");
    emit(&o, MapGenRecipe_Slug(recipe) ? MapGenRecipe_Slug(recipe) : "q2mg");
    emit(&o, "\"\n");

    for (uint32_t i = 0; i < MapGenBrush_Count(work); i++) {
        if (!emit_brush(&o, MapGenBrush_At(work, i), model)) {
            free(o.text);
            return MAPGEN_MAPFILE_ERR_NO_MATERIAL;
        }
    }
    emit(&o, "}\n");

    /* --- brush entities ---------------------------------------------------
     *
     * Doors, lifts, jump pads and teleport triggers: each is a brush of its
     * own, owned by its own entity. That ownership is the whole difference
     * between a door and a wall, and until now the generator had no way to
     * express it - so a map's doors and lifts existed only in the plan.
     */
    for (uint32_t i = 0; i < MapGenBrush_NumFixtures(work); i++) {
        const mapgen_fixture_t *f = MapGenBrush_Fixture(work, i);
        emit(&o, "{\n\"classname\" \"");
        emit(&o, f->classname);
        emit(&o, "\"\n");
        for (uint32_t k = 0; k < f->num_keys; k++) {
            emit(&o, "\"");
            emit(&o, f->keys[k].key);
            emit(&o, "\" \"");
            emit(&o, f->keys[k].value);
            emit(&o, "\"\n");
        }
        if (!emit_brush(&o, &f->brush, model)) {
            free(o.text);
            return MAPGEN_MAPFILE_ERR_NO_MATERIAL;
        }
        emit(&o, "}\n");
    }

    /* --- and the point entities those fixtures need ------------------------ */
    for (uint32_t i = 0; i < MapGenBrush_NumMarkers(work); i++) {
        const mapgen_fixture_t *m = MapGenBrush_Marker(work, i);
        emit(&o, "{\n\"classname\" \"");
        emit(&o, m->classname);
        emit(&o, "\"\n\"origin\" \"");
        for (int axis = 0; axis < 3; axis++) {
            emit_i32(&o, m->brush.mins[axis]);
            if (axis < 2)
                emit(&o, " ");
        }
        emit(&o, "\"\n");
        for (uint32_t k = 0; k < m->num_keys; k++) {
            emit(&o, "\"");
            emit(&o, m->keys[k].key);
            emit(&o, "\" \"");
            emit(&o, m->keys[k].value);
            emit(&o, "\"\n");
        }
        emit(&o, "}\n");
    }

    /* --- point entities ---------------------------------------------------- */
    for (uint32_t i = 0; i < MapGenEntities_Count(entities); i++) {
        const mapgen_placement_t *e = MapGenEntities_At(entities, i);
        emit(&o, "{\n\"classname\" \"");
        emit(&o, e->classname);
        emit(&o, "\"\n\"origin\" \"");
        for (int axis = 0; axis < 3; axis++) {
            emit_i32(&o, e->origin[axis]);
            if (axis < 2)
                emit(&o, " ");
        }
        emit(&o, "\"\n");
        if (e->angle) {
            emit(&o, "\"angle\" \"");
            emit_i32(&o, e->angle);
            emit(&o, "\"\n");
        }
        if (e->light) {
            /* Written out rather than left to the compiler's default, because
               the value was learned and a default is not a choice. */
            emit(&o, "\"light\" \"");
            emit_i32(&o, e->light);
            emit(&o, "\"\n");
        }
        if (e->light_colour) {
            /*
             * In the 0..255 convention, which the corpus also uses and which
             * needs no fractions - this writer has no floating point in it and
             * is not about to acquire any for three bytes.
             */
            emit(&o, "\"_color\" \"");
            emit_i32(&o, (int32_t)((e->light_colour >> 16) & 0xFFu));
            emit(&o, " ");
            emit_i32(&o, (int32_t)((e->light_colour >> 8) & 0xFFu));
            emit(&o, " ");
            emit_i32(&o, (int32_t)(e->light_colour & 0xFFu));
            emit(&o, "\"\n");
        }
        emit(&o, "}\n");
    }

    if (o.failed) {
        free(o.text);
        return MAPGEN_MAPFILE_ERR_MEMORY;
    }

    *out_text = o.text;
    *out_size = o.length;
    return MAPGEN_MAPFILE_OK;
}
