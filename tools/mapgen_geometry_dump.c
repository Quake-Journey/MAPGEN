/*
 * Print a donor's canonical geometry text.
 *
 * Exists so the independent oracle in tools/mapgen_geometry_oracle.py has
 * something to compare against byte for byte. Two readings of the same bytes
 * that share no code either agree or one of them is wrong, and this is the
 * half that is written in C.
 *
 *     mapgen_geometry_dump <map.bsp>
 */
#include <stdio.h>
#include <stdlib.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"

int main(int argc, char **argv)
{
    if (argc < 2)
        return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f)
        return 2;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *raw = malloc((size_t)n);
    if (!raw || fread(raw, 1, (size_t)n, f) != (size_t)n)
        return 2;
    fclose(f);

    mapgen_bsp_t *bsp = NULL;
    MapGenBsp_Load(raw, (size_t)n, &bsp);
    free(raw);

    mapgen_geometry_t *g = NULL;
    MapGenGeometry_FromBsp(bsp, &g);

    const size_t need = MapGenGeometry_CanonicalText(g, NULL, 0);
    char *text = malloc(need ? need : 1);
    MapGenGeometry_CanonicalText(g, text, need);
    fputs(text, stdout);
    return 0;
}
