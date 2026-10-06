/*
 * GF6B - did the candidate change the right AMOUNT of the donor?
 *
 * Not the right things, which is what every other gate is for. This one asks
 * the question contract 14.0.1 added after the PO was handed a near-copy of
 * q2dm1 three times running: a maximum divergence with no minimum is satisfied
 * by changing nothing.
 *
 *     mapgen_divergence_gate <donor.bsp> <candidate.bsp> <fidelity>
 *                            [--routes] [--cells FILE]
 *
 * Exit 0 when the compiled divergence is within fifty permille of
 * 10 * (100 - F). `--routes` adds the reachability axis, which costs a full
 * exploration of both maps. `--cells` writes every differing cell with the
 * axes that differ and the two construction identities, which is what turns
 * an argument about the metric into a thing that can be checked.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_divergence.h"

static mapgen_bsp_t *load(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot read %s\n", path);
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *raw = n > 0 ? malloc((size_t)n) : NULL;
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(raw);
        fprintf(stderr, "cannot read %s\n", path);
        return NULL;
    }
    fclose(f);
    mapgen_bsp_t *bsp = NULL;
    const mapgen_bsp_result_t rc = MapGenBsp_Load(raw, (size_t)n, &bsp);
    free(raw);
    if (rc != MAPGEN_BSP_OK) {
        fprintf(stderr, "%s: %s\n", path, MapGenBsp_ResultName(rc));
        return NULL;
    }
    return bsp;
}

/* One line per differing cell: where it is, which axes moved, and - for the
   motif axis - the construction identity on each side. */
static void witness(void *user, const int32_t c[3], const float w[3],
                    uint32_t donor_axes, uint32_t cand_axes,
                    uint32_t donor_motif, uint32_t cand_motif)
{
    static const struct { uint32_t bit; char tag; } AXES[] = {
        { MAPGEN_DIVERGENCE_AXIS_SOLID,    'S' },
        { MAPGEN_DIVERGENCE_AXIS_SURFACE,  'F' },
        { MAPGEN_DIVERGENCE_AXIS_VERTICAL, 'V' },
        { MAPGEN_DIVERGENCE_AXIS_ROUTE,    'R' },
        { MAPGEN_DIVERGENCE_AXIS_MOTIF,    'M' },
    };
    char moved[8];
    size_t n = 0;
    for (size_t i = 0; i < sizeof(AXES) / sizeof(AXES[0]); i++) {
        const bool differ = ((donor_axes ^ cand_axes) & AXES[i].bit) != 0
                         || (AXES[i].bit == MAPGEN_DIVERGENCE_AXIS_MOTIF
                             && donor_motif != cand_motif
                             && ((donor_axes | cand_axes) & AXES[i].bit));
        if (differ)
            moved[n++] = AXES[i].tag;
    }
    moved[n] = 0;
    fprintf((FILE *)user, "cell %d %d %d  at %.0f %.0f %.0f  %s"
            "  donor %02x/%08x  candidate %02x/%08x\n",
            c[0], c[1], c[2], w[0], w[1], w[2], n ? moved : "-",
            donor_axes, donor_motif, cand_axes, cand_motif);
}

int main(int argc, char **argv)
{
    if (argc < 4) {
        fprintf(stderr, "usage: %s <donor.bsp> <candidate.bsp> <fidelity>"
                        " [--routes] [--cells FILE]\n", argv[0]);
        return 2;
    }
    bool routes = false;
    const char *cells = NULL;
    for (int a = 4; a < argc; a++) {
        if (!strcmp(argv[a], "--routes"))
            routes = true;
        else if (!strcmp(argv[a], "--cells") && a + 1 < argc)
            cells = argv[++a];
    }

    mapgen_bsp_t *donor = load(argv[1]);
    if (!donor)
        return 2;
    mapgen_bsp_t *candidate = load(argv[2]);
    if (!candidate) {
        MapGenBsp_Free(donor);
        return 2;
    }

    FILE *dump = NULL;
    if (cells) {
        dump = fopen(cells, "wb");
        if (!dump) {
            fprintf(stderr, "cannot write %s\n", cells);
            MapGenBsp_Free(donor);
            MapGenBsp_Free(candidate);
            return 2;
        }
        fprintf(dump, "# schema %u %s\n# donor %s\n# candidate %s\n",
                MAPGEN_DIVERGENCE_SCHEMA, MAPGEN_DIVERGENCE_SCHEMA_ID,
                argv[1], argv[2]);
    }

    mapgen_divergence_t d;
    const mapgen_divergence_result_t rc = MapGenDivergence_MeasureWitness(
        donor, candidate, (uint32_t)strtoul(argv[3], NULL, 10), routes, &d,
        dump ? witness : NULL, dump);
    MapGenBsp_Free(donor);
    MapGenBsp_Free(candidate);
    if (dump)
        fclose(dump);

    if (rc != MAPGEN_DIVERGENCE_OK) {
        printf("%s\n", MapGenDivergence_ResultName(rc));
        return 2;
    }

    printf("schema %u (%s)\n", d.schema, MAPGEN_DIVERGENCE_SCHEMA_ID);
    printf("fidelity %u, target %u permille\n", d.fidelity, d.target_permille);
    printf("  solid     %4u permille  (%u of %u cells)\n", d.solid_permille,
           d.solid_changed, d.solid_cells);
    printf("  surface   %4u permille  (%u of %u)\n", d.surface_permille,
           d.surface_changed, d.surface_cells);
    printf("  floors    %4u permille  (%u of %u)\n", d.vertical_permille,
           d.vertical_changed, d.vertical_cells);
    if (d.routes_measured)
        printf("  routes    %4u permille  (%u of %u)\n", d.route_permille,
               d.route_changed, d.route_cells);
    else
        printf("  routes    NOT MEASURED (pass --routes)\n");
    if (d.motifs_measured)
        printf("  motifs    %4u permille  (%u of %u)\n", d.motif_permille,
               d.motif_changed, d.motif_cells);
    else
        printf("  motifs    NOT MEASURED\n");
    printf("  together  %4u permille  (%u of %u cells, counted once each)\n",
           d.aggregate_permille, d.changed_cells, d.donor_cells);
    /* Whether the instrument finished, said before the verdict, because a
       verdict from an unfinished measurement is not a verdict. */
    printf("  complete  %s  (routes truncated %s, faces skipped %u)\n",
           d.complete ? "yes" : "NO", d.routes_truncated ? "YES" : "no",
           d.surfaces_skipped);

    if (d.within_band) {
        printf("  PASS: within fifty permille of the target\n");
        return 0;
    }
    if (d.aggregate_permille < d.target_permille)
        printf("  FAIL: %u permille short of the target - this is too much"
               " like the donor\n", d.target_permille - d.aggregate_permille);
    else
        printf("  FAIL: %u permille past the target - this changed more than"
               " the fidelity asked for\n",
               d.aggregate_permille - d.target_permille);
    return 1;
}
