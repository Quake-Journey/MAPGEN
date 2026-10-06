/*
 * MAPGEN-1 MapGenWiring test driver.
 *
 * Compiled and run by tools/check_mapgen_wiring_contract.py.
 *
 *   driver summary  <map.bsp>          counts and the digest
 *   driver text     <map.bsp>          the canonical text
 *   driver dangling <map.bsp>          one line per link that goes nowhere
 *   driver classify <classname>...     the roles for names given on the
 *                                      command line, including ones no
 *                                      shipped map contains
 */

#include "common/mapgen_wiring.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    long size = ftell(f);
    if (size < 0) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) { fclose(f); return NULL; }
    size_t got = fread(data, 1, (size_t)size, f);
    fclose(f);
    *out_size = got;
    return data;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        printf("usage\n");
        return 2;
    }
    const char *mode = argv[1];

    if (!strcmp(mode, "classify")) {
        for (int i = 2; i < argc; i++) {
            const uint32_t roles = MapGenWiring_RolesForClassname(argv[i]);
            const char *names[MAPGEN_WIRING_MAX_ROLE_NAMES];
            const uint32_t n = MapGenWiring_RoleNames(roles, names,
                                                      MAPGEN_WIRING_MAX_ROLE_NAMES);
            printf("%s %u", argv[i], roles);
            for (uint32_t k = 0; k < n && k < MAPGEN_WIRING_MAX_ROLE_NAMES; k++)
                printf(" %s", names[k]);
            printf("\n");
        }
        return 0;
    }

    size_t size = 0;
    uint8_t *data = read_file(argv[2], &size);
    if (!data) {
        printf("READ_FAILED\n");
        return 1;
    }
    mapgen_bsp_t *bsp = NULL;
    if (MapGenBsp_Load(data, size, &bsp) != MAPGEN_BSP_OK) {
        free(data);
        printf("LOAD_FAILED\n");
        return 1;
    }
    free(data);

    mapgen_genome_t *genome = NULL;
    if (MapGenGenome_Extract(bsp, &genome) != MAPGEN_GENOME_OK) {
        MapGenBsp_Free(bsp);
        printf("GENOME_FAILED\n");
        return 1;
    }

    mapgen_wiring_t *w = NULL;
    const mapgen_wiring_result_t r = MapGenWiring_Build(genome, bsp, &w);
    if (r != MAPGEN_WIRING_OK) {
        printf("%s\n", MapGenWiring_ResultName(r));
        MapGenGenome_Free(genome);
        MapGenBsp_Free(bsp);
        return 0;
    }

    if (!strcmp(mode, "summary")) {
        printf("OK %016llx entities %u links %u dangling %u teams %u "
               "shared %u cycle %u badmodel %u movers %u teleporters %u "
               "dests %u push %u triggers %u spawns %u items %u leftovers %u\n",
               (unsigned long long)MapGenWiring_CanonicalDigest(w),
               MapGenWiring_NumEntities(w), MapGenWiring_NumLinks(w),
               MapGenWiring_NumDangling(w), MapGenWiring_NumTeams(w),
               MapGenWiring_NumSharedNames(w), MapGenWiring_NumOnCycle(w),
               MapGenWiring_NumBadSubmodels(w),
               MapGenWiring_CountRole(w, MAPGEN_ENTROLE_MOVER),
               MapGenWiring_CountRole(w, MAPGEN_ENTROLE_TELEPORTER),
               MapGenWiring_CountRole(w, MAPGEN_ENTROLE_TELEPORT_DEST),
               MapGenWiring_CountRole(w, MAPGEN_ENTROLE_PUSH),
               MapGenWiring_CountRole(w, MAPGEN_ENTROLE_TRIGGER),
               MapGenWiring_CountRole(w, MAPGEN_ENTROLE_SPAWN_DM),
               MapGenWiring_CountRole(w, MAPGEN_ENTROLE_ITEM),
               MapGenWiring_CountRole(w, MAPGEN_ENTROLE_EDITOR_LEFTOVER));
    } else if (!strcmp(mode, "text")) {
        size_t needed = MapGenWiring_CanonicalText(w, NULL, 0);
        char *text = malloc(needed + 1);
        if (text) {
            MapGenWiring_CanonicalText(w, text, needed + 1);
            fwrite(text, 1, needed, stdout);
            free(text);
        }
    } else if (!strcmp(mode, "dangling")) {
        for (uint32_t i = 0; i < MapGenWiring_NumDangling(w); i++) {
            const mapgen_wiring_dangling_t *d = MapGenWiring_Dangling(w, i);
            const mapgen_entity_t *ent = MapGenGenome_Entity(genome, d->from);
            printf("%s %s -> %s\n", ent ? ent->classname : "?",
                   MapGenWiring_LinkKindName((mapgen_link_kind_t)d->kind), d->name);
        }
    } else {
        printf("BAD_MODE\n");
    }

    MapGenWiring_Free(w);
    MapGenGenome_Free(genome);
    MapGenBsp_Free(bsp);
    return 0;
}
