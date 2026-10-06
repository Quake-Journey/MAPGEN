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

MAPGEN-1 - MapGenMapFile: the `source.map` a compiler can read

Contract section 16 stage 10: serialize a deterministic Quake II Valve 220
`.map`.

--- Deterministic means byte-identical -------------------------------------

Contract 10 asks for the same `source.map` from the same recipe regardless of
locale, timezone, CPU count or anything else. Every number here is an integer
printed by hand: no `printf("%f")`, which a comma-decimal locale would ruin,
and no floating point to round differently on another machine. Line endings
are LF, chosen rather than inherited.

--- Winding is derived, not remembered --------------------------------------

A brush face's three points have to be ordered so the plane's normal points
OUT of the brush, and which order that is depends on the compiler's own
formula. Rather than trust a remembered convention, the points are constructed
from the face's axis and sign, and the guard recomputes the normal with
qbsp3's own arithmetic - `(p0 - p1) x (p2 - p1)` - and checks it against the
face it is supposed to be. A wrong winding produces a map that compiles into
an inside-out room.

--- What is deliberately not in the file ------------------------------------

The map's display name. It may be Russian, the file is read by a compiler
whose UTF-8 behaviour is not qualified until M0Q's pin is exercised, and a
`message` key is not worth finding that out through a corrupted map. The slug
goes in instead, and the display name stays in the recipe where it is already
stored exactly.

==============================================================================
*/

#pragma once

#include "common/mapgen_brush.h"
#include "common/mapgen_entities.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    MAPGEN_MAPFILE_OK = 0,
    MAPGEN_MAPFILE_ERR_ARGS,
    MAPGEN_MAPFILE_ERR_MEMORY,
    MAPGEN_MAPFILE_ERR_NO_BRUSHES,
    MAPGEN_MAPFILE_ERR_NO_MATERIAL,
} mapgen_mapfile_result_t;

const char *MapGenMapFile_ResultName(mapgen_mapfile_result_t r);

/*
 * Write the whole file. The caller owns `*out_text` and frees it with `free`;
 * `*out_size` is the length in bytes, and the text is NUL-terminated past it
 * so it can also be treated as a string.
 */
mapgen_mapfile_result_t MapGenMapFile_Write(const mapgen_brushwork_t *work,
                                            const mapgen_entities_t *entities,
                                            const mapgen_mix_t *model,
                                            const mapgen_recipe_t *recipe,
                                            char **out_text, size_t *out_size);

/*
 * The three points of one face of one brush, in the order the file writes
 * them. Exposed so a test can recompute the plane the compiler will and check
 * the normal points outward - the one property of this file that cannot be
 * checked by reading it.
 */
void MapGenMapFile_FacePoints(const mapgen_brush_t *brush, mapgen_face_t face,
                              int32_t points[3][3]);
