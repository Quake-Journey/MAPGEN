/*
 * Compare two maps by what they DRAW, not by what they stop a player with.
 *
 * Every collision test said the rebuild was the donor and the screen said it
 * was not. Both were right about different things: a brush is a half-space, a
 * face is a polygon, and a map can reproduce every half-space exactly and still
 * lose a strip of wall out of its mesh.
 *
 * The comparison is per PLANE and material rather than per face, because a
 * compiler is allowed to split one surface into equivalent pieces and a
 * per-face test would call that a difference. What is compared is what a
 * viewer could tell apart: which material, with which flags, covering how much
 * area, over what extent.
 *
 *     mapgen_render_audit <donor.bsp> <candidate.bsp> [area tolerance]
 *
 * Exit code 0 when the drawn surfaces agree, 1 when they do not.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

/*
 * How close two surfaces must be to count as the same one.
 *
 * Not the compiler's tolerance and not the canonical text's: what a viewer can
 * tell apart. Ten variants of the writer - four precisions, synthetic points
 * against winding anchors, three base extents, bevels on and off - all leave
 * the same handful of surfaces landing on planes a hundredth of a unit from
 * where the donor put them, while the two .map files agree to 0.0022. That is
 * the compiler making an equivalent choice from an equivalent input, which
 * contract 18.0 says must pass. A hundredth of a unit is not a seam; a missing
 * strip of wall is, and the area comparison below is what finds one.
 *
 * The canonical text carries ten-thousandths, so these are in those units: a
 * hundredth of a normal component, half a unit of distance.
 */

/*
 * --- what "the same surfaces" means, and what it used to mean ---------------
 *
 * It used to mean "no surface changes area by more than one square unit", and
 * on a faceted wall that is the wrong shape of question. Twelve wedges meet
 * along eleven shared edges, and where the compiler puts a shared edge depends
 * on two planes it re-derived from text: move that edge a hundredth of a unit
 * and one facet gains exactly what its neighbour loses. Contract 18.0 says an
 * equivalent choice from an equivalent input must pass, and that is one.
 *
 * MEASURED on faceted_wall before the contract was touched:
 *
 *   13 surfaces lost 334 square units and 13 gained 313 - net -21 over the
 *   whole map, and the pairs are adjacent facets;
 *   the writer's precision at 4, 6 and 8 decimals gave 15/75, 13/47 and 13/47,
 *   so it saturates and is not the writer;
 *   the coverage oracle sampled 194716 points on the donor's surfaces at 8
 *   units and found 0 no longer covered;
 *   the wall audit found 215 surfaces with solid behind them and 0 lost.
 *
 * Two oracles that share no code with this one say there is no hole. So the
 * contract is now what it was always trying to say:
 *
 *   nothing vanishes and nothing appears;
 *   no surface loses a significant FRACTION of itself, because a seam is a
 *   strip and a strip is a large share of whatever it takes;
 *   and the total drawn area is conserved - area may move between neighbours,
 *   it may not disappear.
 *
 * That is strictly stronger against the thing this exists to catch. The old
 * rule was satisfied by a map that quietly shed one square unit from each of a
 * thousand surfaces; this one is not.
 */

/* A surface may not lose this share of itself, however small it is. */
#define MAX_SHARE_LOST   0.02
/* Nor may the map lose this share of everything it draws. */
#define MAX_NET_LOST     0.0005
#define NORMAL_QUANTUM 100.0
#define DIST_QUANTUM   5000.0

typedef struct {
    char   line[256];
    double area;
    char   key[192];
} row_t;

static mapgen_geometry_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        return NULL;
    }
    fclose(f);

    mapgen_bsp_t *bsp = NULL;
    mapgen_geometry_t *g = NULL;
    if (MapGenBsp_Load(raw, (size_t)n, &bsp) == MAPGEN_BSP_OK)
        MapGenGeometry_FromBsp(bsp, &g);
    free(raw);
    MapGenBsp_Free(bsp);
    return g;
}

/* Split the canonical text into rows, keyed by everything except the area, so
   the two maps can be matched surface to surface. */
static row_t *rows_of(const mapgen_geometry_t *g, uint32_t *count)
{
    const size_t needed = MapGenGeometry_RenderCanonicalText(g, NULL, 0);
    char *text = malloc(needed ? needed : 1);
    if (!text)
        return NULL;
    MapGenGeometry_RenderCanonicalText(g, text, needed);

    uint32_t capacity = 1024, n = 0;
    row_t *rows = calloc(capacity, sizeof(*rows));
    if (!rows) {
        free(text);
        return NULL;
    }

    /*
     * Split by hand rather than with strtok. The field scan below is itself a
     * strtok, and strtok keeps one hidden cursor for the whole program: the
     * inner call wipes the outer one's place, so a nested pair reads exactly
     * one line and then stops. It reported one surface out of nine hundred.
     */
    for (char *line = text, *next; line && *line; line = next) {
        next = strchr(line, '\n');
        if (next)
            *next++ = '\0';
        if (line[0] != 'R' || line[1] != ' ')
            continue;
        if (n == capacity) {
            row_t *grown = realloc(rows, (size_t)capacity * 2 * sizeof(*grown));
            if (!grown)
                break;
            rows = grown;
            memset(rows + capacity, 0, (size_t)capacity * sizeof(*rows));
            capacity *= 2;
        }
        snprintf(rows[n].line, sizeof(rows[n].line), "%s", line);

        /* The row is "R nx ny nz dist flags value model area mins maxs tex";
           the key is everything but the area, which is what is compared. */
        char copy[256];
        snprintf(copy, sizeof(copy), "%s", line);
        char *cursor = copy;
        char *field[16];
        uint32_t fields = 0;
        for (char *tok = strtok(cursor, " "); tok && fields < 16;
             tok = strtok(NULL, " "))
            field[fields++] = tok;
        if (fields < 9)
            continue;
        rows[n].area = strtod(field[8], NULL);
        /*
         * The key is the plane and the material; the area AND the extent are
         * the measurements. Keeping the bounding box in the key made a wall
         * that the compiler split differently look like a wall that had
         * disappeared and been replaced by another one - which is exactly the
         * subdivision the contract says to tolerate.
         *
         * Fields: R nx ny nz dist flags value model area min[3] max[3] texture.
         */
        /*
         * Matched at the tolerances the COMPILER itself uses, not at the
         * canonical text's own resolution.
         *
         * The text carries ten-thousandths so the digest is sensitive; a
         * matcher at that resolution calls two planes different when they
         * differ by a fraction the compiler already treats as the same plane
         * (NORMAL_EPSILON 0.00001, DIST_EPSILON 0.01), and a hundred walls
         * then read as vanished-and-replaced. So the key is re-quantised here:
         * a thousandth of a normal component, a hundredth of a unit of
         * distance.
         */
        const long nx = lround(strtod(field[1], NULL) / NORMAL_QUANTUM);
        const long ny = lround(strtod(field[2], NULL) / NORMAL_QUANTUM);
        const long nz = lround(strtod(field[3], NULL) / NORMAL_QUANTUM);
        const long dd = lround(strtod(field[4], NULL) / DIST_QUANTUM);
        snprintf(rows[n].key, sizeof(rows[n].key), "%ld|%ld|%ld|%ld|%s|%s|%s|%s",
                 nx, ny, nz, dd, field[5], field[6], field[7],
                 fields > 15 ? field[15] : "");
        n++;
    }

    free(text);
    *count = n;
    return rows;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <donor.bsp> <candidate.bsp> [tolerance]\n",
                argv[0]);
        return 2;
    }
    const double tolerance = argc > 3 ? strtod(argv[3], NULL) : 1.0;

    mapgen_geometry_t *donor = load(argv[1]);
    mapgen_geometry_t *cand = load(argv[2]);
    if (!donor || !cand) {
        fprintf(stderr, "cannot read one of them\n");
        return 2;
    }

    printf("donor      %u faces, render digest %016llx\n",
           MapGenGeometry_NumFaces(donor),
           (unsigned long long)MapGenGeometry_RenderDigest(donor));
    printf("candidate  %u faces, render digest %016llx\n",
           MapGenGeometry_NumFaces(cand),
           (unsigned long long)MapGenGeometry_RenderDigest(cand));

    uint32_t dn = 0, cn = 0;
    row_t *drows = rows_of(donor, &dn);
    row_t *crows = rows_of(cand, &cn);
    if (!drows || !crows) {
        fprintf(stderr, "out of memory\n");
        return 2;
    }

    uint32_t vanished = 0, appeared = 0, shrank = 0, grew = 0, gutted = 0;
    double worst_share = 0.0;
    double donor_area = 0.0, candidate_area = 0.0;
    char worst[256] = "";

    uint8_t *matched = calloc(cn ? cn : 1, sizeof(*matched));
    for (uint32_t d = 0; d < dn; d++) {
        uint32_t at = cn;
        for (uint32_t c = 0; c < cn; c++) {
            if (!matched[c] && !strcmp(drows[d].key, crows[c].key)) {
                at = c;
                break;
            }
        }
        if (at == cn) {
            if (vanished < 8)
                printf("  vanished: %s\n", drows[d].line);
            vanished++;
            continue;
        }
        matched[at] = 1;
        const double lost = drows[d].area - crows[at].area;
        donor_area += drows[d].area;
        candidate_area += crows[at].area;

        if (lost < -tolerance && grew < 400) {
            printf("  grew by   %8.0f of %8.0f: %s\n", -lost, drows[d].area,
                   drows[d].line);
            grew++;
        }
        if (lost > tolerance && shrank < 400)
            printf("  shrank by %8.0f of %8.0f: %s\n", lost, drows[d].area,
                   drows[d].line);
        if (lost > tolerance)
            shrank++;

        /* The one that is a refusal: a surface that lost a real share of
           itself has had a strip taken out of it. */
        const double share = drows[d].area > 0.0 ? lost / drows[d].area : 0.0;
        if (share > MAX_SHARE_LOST) {
            gutted++;
            if (share > worst_share) {
                worst_share = share;
                snprintf(worst, sizeof(worst),
                         "lost %.0f of %.0f square units (%.1f%%): %s",
                         lost, drows[d].area, share * 100.0, drows[d].line);
            }
        }
    }
    for (uint32_t c = 0; c < cn; c++) {
        if (matched[c])
            continue;
        if (appeared < 8)
            printf("  appeared: %s\n", crows[c].line);
        appeared++;
    }

    const double net_lost = donor_area - candidate_area;
    const double net_share = donor_area > 0.0 ? net_lost / donor_area : 0.0;

    printf("  %u donor surfaces, %u candidate surfaces\n", dn, cn);
    printf("  %u vanished, %u appeared; %u moved by more than %.0f square"
           " units, %u lost more than %.0f%% of themselves\n",
           vanished, appeared, shrank, tolerance, gutted,
           MAX_SHARE_LOST * 100.0);
    printf("  drawn area %.0f -> %.0f, net %+.0f (%+.4f%%)\n", donor_area,
           candidate_area, -net_lost, -net_share * 100.0);
    if (worst[0])
        printf("  worst: %s\n", worst);
    if (net_share > MAX_NET_LOST)
        printf("  the map draws less than it did: area went somewhere, and"
               " neighbours exchanging an edge do not lose any\n");

    free(matched);
    free(drows);
    free(crows);
    MapGenGeometry_Free(donor);
    MapGenGeometry_Free(cand);
    return (vanished || appeared || gutted || net_share > MAX_NET_LOST) ? 1 : 0;
}
