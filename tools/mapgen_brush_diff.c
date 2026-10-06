/*
 * What a candidate BUILT that its baseline did not - and whether a mapper
 * would have built it.
 *
 *     mapgen_brush_diff <baseline.bsp> <candidate.bsp>
 *
 * One line per world brush the candidate has and the baseline does not, with
 * its box, the materials on its sides, what the BASELINE had where it now
 * stands, and what is holding it up. Two questions are being asked and they
 * are the two the PO asked on 2026-09-07 after walking three forks of q2dm1:
 *
 *   is it made of something the map DRAWS - the blocks came out wearing
 *   `e1u1/clip`, which is the name the .map writer gives a side with no
 *   texture, and the compiler drew it;
 *
 *   is it standing on anything - the recut's blocks were placed from the
 *   floor of the emptied REGION rather than from the ground, and hung in the
 *   air over a courtyard.
 *
 * A brush that stands where the baseline had SOLID is a piece of a wall the
 * hollow cut, not a construction: it is reported and is not held to the
 * second question, because a remnant of a wall is held up by the wall. A
 * LIQUID brush is neither of those, and it is no longer unjudged either: it
 * reports the clearance of the basin around it, because on 2026-09-07 an
 * operator raised one a hundred and ninety-five units out of a basin whose rim
 * is eight and the PO photographed the result.
 *
 * Exit 1 when any construction fails either question, so a guard can use the
 * status and a reader can use the lines.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_geometry.h"

#define MAX_ADDED 4096

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

/*
 * A brush's identity: its box, its contents, its model and its planes.
 *
 * The sum of the sides' hashes alone is not one, and this tool carried that
 * defect until 2026-09-07 evening: each side contributes a value that differs
 * only in the low bits its distance sets, and six of them add back together.
 * MEASURED on q2dm1 with the same shape of key: the step at 1184 1536 768 and
 * the pillar at 288 408 320 answer to one number. Two brushes that share a key
 * are one brush to a diff, so a construction could be reported as unchanged
 * geometry - the opposite of what this tool exists to find.
 *
 * The box is what separates them; the contents keep a player clip distinct
 * from the step it covers, which q2dm1 lays on exactly the same planes.
 */
static uint64_t key_of(const mapgen_geometry_t *g,
                       const mapgen_geometry_brush_t *b)
{
    uint64_t h = 1469598103934665603ull;
    #define DIFF_KEY_EAT(v) do {                                              \
        h ^= (uint64_t)(int64_t)(v);                                          \
        h *= 1099511628211ull;                                                \
    } while (0)

    DIFF_KEY_EAT(b->contents);
    DIFF_KEY_EAT(b->model);
    for (int a = 0; a < 3; a++) {
        DIFF_KEY_EAT(llround(b->mins[a] * 8.0));
        DIFF_KEY_EAT(llround(b->maxs[a] * 8.0));
    }

    uint64_t sum = 0;
    uint32_t real = 0;
    for (uint32_t s = 0; s < b->num_sides; s++) {
        const mapgen_geometry_side_t *side =
            MapGenGeometry_Side(g, b->first_side + s);
        if (!side || side->bevel)
            continue;
        uint64_t sh = 1469598103934665603ull;
        for (int a = 0; a < 3; a++) {
            const int64_t q = (int64_t)llround(side->normal[a] * 1024.0);
            sh ^= (uint64_t)q;
            sh *= 1099511628211ull;
        }
        const int64_t d = (int64_t)llround(side->dist * 8.0);
        sh ^= (uint64_t)d;
        sh *= 1099511628211ull;
        sum += sh;              /* order cannot matter: the compiler's is not
                                   the mapper's */
        real++;
    }
    DIFF_KEY_EAT(real);
    DIFF_KEY_EAT(sum);
    #undef DIFF_KEY_EAT
    return h ? h : 1ull;
}

/*
 * How far a pool could rise before it spills, measured in the map it sits in.
 *
 * The line below used to say a pool is held up by the basin it sits in and
 * judge nothing, which was true of every pool until an operator raised one out
 * of its basin: the PO photographed a hundred and ninety-five units of water
 * standing in the air on 2026-09-07. So a pool reports its clearance, and the
 * standing-water guard reports the faces.
 */
static float pool_rim(const mapgen_bsp_t *bsp, const float mins[3],
                      const float maxs[3])
{
    float rim = 512.0f;
    for (int axis = 0; axis < 2; axis++) {
        const int across = axis ^ 1;
        for (int dir = 0; dir < 2; dir++) {
            const float at = dir ? maxs[axis] + 8.0f : mins[axis] - 8.0f;
            for (float s = mins[across] + 4.0f; s < maxs[across]; s += 16.0f) {
                float p[3];
                p[axis] = at;
                p[across] = s;
                float here = 512.0f;
                for (float z = maxs[2]; z <= maxs[2] + 512.0f; z += 4.0f) {
                    p[2] = z;
                    if (!(MapGenBsp_PointContents(bsp, p) & 1)) {
                        here = z - maxs[2];
                        break;
                    }
                }
                if (here < rim)
                    rim = here;
            }
        }
    }
    return rim;
}

static bool inside_box(const float p[3], const float mins[3],
                       const float maxs[3])
{
    for (int a = 0; a < 3; a++)
        if (p[a] < mins[a] || p[a] > maxs[a])
            return false;
    return true;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <baseline.bsp> <candidate.bsp>\n", argv[0]);
        return 2;
    }
    mapgen_bsp_t *base = load(argv[1]), *cand = load(argv[2]);
    mapgen_geometry_t *gb = NULL, *gc = NULL;
    if (!base || !cand
        || MapGenGeometry_FromBsp(base, &gb) != MAPGEN_GEOMETRY_OK
        || MapGenGeometry_FromBsp(cand, &gc) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot read the pair\n");
        return 2;
    }

    const uint32_t nb = MapGenGeometry_NumBrushes(gb);
    uint64_t *keys = malloc((nb + 1) * sizeof(uint64_t));
    if (!keys)
        return 2;
    for (uint32_t i = 0; i < nb; i++)
        keys[i] = key_of(gb, MapGenGeometry_Brush(gb, i));

    /* Two passes: collect what was added, then judge it - a construction may
       be standing on another construction from the same edit. */
    static float added_mins[MAX_ADDED][3], added_maxs[MAX_ADDED][3];
    uint32_t num_added = 0;
    const uint32_t nc = MapGenGeometry_NumBrushes(gc);
    for (uint32_t i = 0; i < nc && num_added < MAX_ADDED; i++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(gc, i);
        if (!br)
            continue;
        const uint64_t k = key_of(gc, br);
        bool seen = false;
        for (uint32_t j = 0; j < nb && !seen; j++)
            seen = keys[j] == k;
        if (seen)
            continue;
        memcpy(added_mins[num_added], br->mins, sizeof(float) * 3);
        memcpy(added_maxs[num_added], br->maxs, sizeof(float) * 3);
        num_added++;
    }

    uint32_t constructions = 0, unmaterial = 0, floating = 0, remnants = 0;
    for (uint32_t i = 0; i < nc; i++) {
        const mapgen_geometry_brush_t *br = MapGenGeometry_Brush(gc, i);
        if (!br)
            continue;
        const uint64_t k = key_of(gc, br);
        bool seen = false;
        for (uint32_t j = 0; j < nb && !seen; j++)
            seen = keys[j] == k;
        if (seen)
            continue;

        /* Every material on it, and whether every drawn one is a material. */
        char names[512] = "";
        bool any_material = false, all_material = true;
        for (uint32_t s = 0; s < br->num_sides; s++) {
            const mapgen_geometry_side_t *side =
                MapGenGeometry_Side(gc, br->first_side + s);
            if (!side || side->bevel)
                continue;
            if (MapGenGeometry_TextureIsMaterial(side->texture))
                any_material = true;
            else
                all_material = false;
            if (!strstr(names, side->texture[0] ? side->texture : "(none)")) {
                if (names[0])
                    strncat(names, ",", sizeof(names) - strlen(names) - 1);
                strncat(names, side->texture[0] ? side->texture : "(none)",
                        sizeof(names) - strlen(names) - 1);
            }
        }

        const float centre[3] = {
            0.5f * (br->mins[0] + br->maxs[0]),
            0.5f * (br->mins[1] + br->maxs[1]),
            0.5f * (br->mins[2] + br->maxs[2]),
        };
        const bool was_solid =
            (MapGenBsp_PointContents(base, centre) & 1) != 0;

        /*
         * A brush that fills space the baseline had solid in is a piece of a
         * wall that was cut, and the wall holds it up. Only something built
         * where there was AIR is a construction.
         */
        const bool liquid = (br->contents & (MAPGEN_CONTENTS_WATER
                                             | MAPGEN_CONTENTS_LAVA
                                             | MAPGEN_CONTENTS_SLIME)) != 0;

        /* Every added brush, in one shape, said as what it IS - so that two
           candidates' sets can be compared, and so that a decoration two
           forks share is not confused with a wall remnant they share because
           the same hollow cut the same wall. */
        /*
         * Three kinds, not two.
         *
         * A lift's deck belongs to a brush MODEL, so it used to be spelled a
         * remnant and a remnant is not held to anything - two forks that
         * turned the same staircase into the same lift shared a deck and the
         * variety guard called it the operator working. It is not: it is the
         * same machine in the same place in two maps, which is the clone the
         * PO reported wearing another operator's name.
         */
        printf("add %s %.0f %.0f %.0f %.0f %.0f %.0f\n",
               br->model ? "machine"
                         : ((was_solid || liquid) ? "remnant" : "construction"),
               br->mins[0], br->mins[1], br->mins[2],
               br->maxs[0], br->maxs[1], br->maxs[2]);

        if (was_solid || br->model || liquid) {
            remnants++;
            if (liquid)
                printf("  pool %6.0f %6.0f %6.0f .. %6.0f %6.0f %6.0f"
                       "  rim %4.0f  [%s]\n",
                       br->mins[0], br->mins[1], br->mins[2],
                       br->maxs[0], br->maxs[1], br->maxs[2],
                       pool_rim(cand, br->mins, br->maxs), names);
            continue;
        }
        constructions++;

        /* Is anything under it - the map's own solid, or another new brush? */
        bool held = false;
        for (int c = 0; c < 5 && !held; c++) {
            static const float CORNER[5][2] = {
                { 0.1f, 0.1f }, { 0.9f, 0.1f }, { 0.1f, 0.9f },
                { 0.9f, 0.9f }, { 0.5f, 0.5f }
            };
            const float p[3] = {
                br->mins[0] + (br->maxs[0] - br->mins[0]) * CORNER[c][0],
                br->mins[1] + (br->maxs[1] - br->mins[1]) * CORNER[c][1],
                br->mins[2] - 4.0f,
            };
            if (MapGenBsp_PointContents(base, p) & 1)
                held = true;
            for (uint32_t o = 0; o < num_added && !held; o++)
                if (added_maxs[o][2] > p[2] - 8.0f
                    && inside_box(p, added_mins[o], added_maxs[o]))
                    held = true;
        }

        const bool bad = !all_material || !held;
        if (!all_material)
            unmaterial++;
        if (!held)
            floating++;
        printf("  %s %6.0f %6.0f %6.0f .. %6.0f %6.0f %6.0f  %4.0fx%4.0fx%4.0f"
               "  %s  [%s]\n",
               bad ? "BAD " : "ok  ",
               br->mins[0], br->mins[1], br->mins[2],
               br->maxs[0], br->maxs[1], br->maxs[2],
               br->maxs[0] - br->mins[0], br->maxs[1] - br->mins[1],
               br->maxs[2] - br->mins[2],
               held ? "grounded" : "FLOATING",
               names);
        (void)any_material;
    }

    printf("added %u (%u constructions, %u remnants and pools):"
           " %u not a material, %u floating\n",
           num_added, constructions, remnants, unmaterial, floating);
    free(keys);
    return (unmaterial || floating) ? 1 : 0;
}
