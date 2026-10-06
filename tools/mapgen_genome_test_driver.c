/*
 * MAPGEN-1 MapGenome layer 1 - self-asserting test.
 *
 * Compiled and run by tools/check_mapgen_genome_contract.py.
 *
 *   driver selftest                 -> the crafted cases, asserted here
 *   driver map <file.bsp>           -> one line of facts about a real map
 *   driver digest <file.bsp>        -> the genome digest
 *
 * The crafted cases exist because the one rule that matters most - a material's
 * role comes from FLAGS and never from its NAME - cannot be proven on real
 * maps, where name and flags almost always agree. It has to be tested where
 * they deliberately disagree.
 */

#include "common/mapgen_bsp.h"
#include "common/mapgen_genome.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_cases;
static int g_failed;

static bool ck(const char *name, bool ok, const char *detail)
{
    g_cases++;
    if (ok) {
        printf("  PASS  %s\n", name);
    } else {
        printf("  FAIL  %s%s%s\n", name, detail && *detail ? "  -- " : "", detail ? detail : "");
        g_failed++;
    }
    return ok;
}

/* ------------------------------------------------------------------------ */
/* A minimal synthetic BSP built in memory, so flags and names can disagree. */
/* ------------------------------------------------------------------------ */

#define LUMPS 19
enum { L_ENT = 0, L_PLANES, L_VERT, L_VIS, L_NODES, L_TEXINFO, L_FACES, L_LIGHT,
       L_LEAFS, L_LEAFFACES, L_LEAFBRUSHES, L_EDGES, L_SURFEDGES, L_MODELS,
       L_BRUSHES, L_BRUSHSIDES, L_POP, L_AREAS, L_AREAPORTALS };

typedef struct {
    const char *name;
    int32_t     flags;
    int32_t     contents;   /* applied to the brush that uses it */
    int32_t     nexttexinfo;
} synth_tex_t;

static void wr_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static uint8_t *build_bsp(const synth_tex_t *texes, uint32_t num_tex,
                          const char *entities, size_t *out_size)
{
    /* One brush per texture, six sides each referencing that one texinfo. */
    const uint32_t num_planes = 6;
    const uint32_t num_brushes = num_tex;
    const uint32_t num_sides = num_tex * 6;

    size_t ent_len = strlen(entities) + 1;
    size_t header = 8 + LUMPS * 8;

    size_t sz_planes = num_planes * 20;
    size_t sz_tex = num_tex * 76;
    size_t sz_brushes = num_brushes * 12;
    size_t sz_sides = num_sides * 4;
    size_t sz_models = 48;
    size_t sz_leafs = 28;

    size_t total = header + ent_len + sz_planes + sz_tex + sz_brushes + sz_sides
                 + sz_models + sz_leafs;
    uint8_t *buf = calloc(1, total);
    if (!buf)
        return NULL;

    wr_u32(buf, MAPGEN_BSP_IDENT_IBSP);
    wr_u32(buf + 4, MAPGEN_BSP_VERSION);

    size_t off = header;
    struct { int lump; size_t off; size_t len; } spans[8];
    int ns = 0;

    memcpy(buf + off, entities, ent_len);
    spans[ns].lump = L_ENT; spans[ns].off = off; spans[ns].len = ent_len; ns++;
    off += ent_len;

    /* Six axis planes; the exact geometry does not matter to this layer. */
    spans[ns].lump = L_PLANES; spans[ns].off = off; spans[ns].len = sz_planes; ns++;
    for (uint32_t i = 0; i < num_planes; i++) {
        uint8_t *p = buf + off + i * 20;
        float n[3] = { i == 0 ? 1.0f : 0.0f, i == 1 ? 1.0f : 0.0f, i == 2 ? 1.0f : 0.0f };
        memcpy(p, n, 12);
        float dist = 64.0f;
        memcpy(p + 12, &dist, 4);
        wr_u32(p + 16, (uint32_t)(i % 3));
    }
    off += sz_planes;

    spans[ns].lump = L_TEXINFO; spans[ns].off = off; spans[ns].len = sz_tex; ns++;
    for (uint32_t i = 0; i < num_tex; i++) {
        uint8_t *p = buf + off + i * 76;
        float axis[8] = { 1, 0, 0, 0, 0, 0, -1, 0 };
        memcpy(p, axis, 32);
        wr_u32(p + 32, (uint32_t)texes[i].flags);
        wr_u32(p + 36, 0);
        strncpy((char *)p + 40, texes[i].name, 31);
        wr_u32(p + 72, (uint32_t)texes[i].nexttexinfo);
    }
    off += sz_tex;

    spans[ns].lump = L_BRUSHES; spans[ns].off = off; spans[ns].len = sz_brushes; ns++;
    for (uint32_t i = 0; i < num_brushes; i++) {
        uint8_t *p = buf + off + i * 12;
        wr_u32(p, i * 6);
        wr_u32(p + 4, 6);
        wr_u32(p + 8, (uint32_t)texes[i].contents);
    }
    off += sz_brushes;

    spans[ns].lump = L_BRUSHSIDES; spans[ns].off = off; spans[ns].len = sz_sides; ns++;
    for (uint32_t i = 0; i < num_sides; i++) {
        uint8_t *p = buf + off + i * 4;
        p[0] = (uint8_t)(i % num_planes); p[1] = 0;
        uint16_t ti = (uint16_t)(i / 6);
        p[2] = (uint8_t)ti; p[3] = (uint8_t)(ti >> 8);
    }
    off += sz_sides;

    spans[ns].lump = L_LEAFS; spans[ns].off = off; spans[ns].len = sz_leafs; ns++;
    off += sz_leafs;

    spans[ns].lump = L_MODELS; spans[ns].off = off; spans[ns].len = sz_models; ns++;
    {
        uint8_t *p = buf + off;
        float mins[3] = { -128, -128, -64 };
        float maxs[3] = { 128, 128, 64 };
        memcpy(p, mins, 12);
        memcpy(p + 12, maxs, 12);
    }
    off += sz_models;

    for (int i = 0; i < ns; i++) {
        wr_u32(buf + 8 + spans[i].lump * 8, (uint32_t)spans[i].off);
        wr_u32(buf + 12 + spans[i].lump * 8, (uint32_t)spans[i].len);
    }

    *out_size = total;
    return buf;
}

static mapgen_genome_t *extract(const synth_tex_t *texes, uint32_t n,
                                const char *entities, mapgen_bsp_t **keep,
                                mapgen_genome_result_t *out_result)
{
    size_t size = 0;
    uint8_t *blob = build_bsp(texes, n, entities, &size);
    if (!blob)
        return NULL;
    mapgen_bsp_t *bsp = NULL;
    mapgen_bsp_result_t r = MapGenBsp_Load(blob, size, &bsp);
    free(blob);
    if (r != MAPGEN_BSP_OK) {
        printf("  ..    synthetic BSP rejected: %s\n", MapGenBsp_ResultName(r));
        return NULL;
    }
    mapgen_genome_t *g = NULL;
    mapgen_genome_result_t gr = MapGenGenome_Extract(bsp, &g);
    if (out_result)
        *out_result = gr;
    if (keep)
        *keep = bsp;
    else
        MapGenBsp_Free(bsp);
    return g;
}

/* ------------------------------------------------------------------------ */

static void test_roles_come_from_flags(void)
{
    printf("\n=== a material's role comes from its FLAGS, never its NAME\n");

    /* The names are deliberately misleading in both directions. */
    static const synth_tex_t texes[] = {
        /* called water, but a plain solid wall */
        { "e1u1/water_wall", 0, MAPGEN_CONTENTS_SOLID, -1 },
        /* called floor, but actually water */
        { "e1u1/floor3_3", MAPGEN_SURF_WARP, MAPGEN_CONTENTS_WATER, -1 },
        /* called lavafall, but a clip brush */
        { "e1u1/lavafall1", 0, MAPGEN_CONTENTS_PLAYERCLIP, -1 },
        /* called brick, but sky */
        { "e1u1/brick8", MAPGEN_SURF_SKY, MAPGEN_CONTENTS_SOLID, -1 },
        /* called sky, but an ordinary solid */
        { "e1u1/sky1", 0, MAPGEN_CONTENTS_SOLID, -1 },
        /* actually lava */
        { "e1u1/xrock", MAPGEN_SURF_WARP, MAPGEN_CONTENTS_LAVA, -1 },
    };

    mapgen_genome_t *g = extract(texes, 6, "{\n\"classname\" \"worldspawn\"\n}\n", NULL, NULL);
    if (!ck("the synthetic map extracts", g != NULL, ""))
        return;

    const mapgen_material_t *m;

    m = MapGenGenome_FindMaterial(g, "e1u1/water_wall");
    ck("a texture NAMED water with solid contents is not water",
       m && !(m->roles & MAPGEN_ROLE_WATER) && (m->roles & MAPGEN_ROLE_SOLID),
       m ? "roles disagree" : "material missing");

    m = MapGenGenome_FindMaterial(g, "e1u1/floor3_3");
    ck("a texture NAMED floor with water contents IS water",
       m && (m->roles & MAPGEN_ROLE_WATER),
       m ? "roles disagree" : "material missing");

    m = MapGenGenome_FindMaterial(g, "e1u1/lavafall1");
    ck("a texture NAMED lavafall with clip contents is clip, not lava",
       m && (m->roles & MAPGEN_ROLE_CLIP) && !(m->roles & MAPGEN_ROLE_LAVA),
       m ? "roles disagree" : "material missing");

    m = MapGenGenome_FindMaterial(g, "e1u1/brick8");
    ck("a texture NAMED brick with SURF_SKY IS sky",
       m && (m->roles & MAPGEN_ROLE_SKY),
       m ? "roles disagree" : "material missing");

    m = MapGenGenome_FindMaterial(g, "e1u1/sky1");
    ck("a texture NAMED sky without SURF_SKY is NOT sky",
       m && !(m->roles & MAPGEN_ROLE_SKY),
       m ? "roles disagree" : "material missing");

    m = MapGenGenome_FindMaterial(g, "e1u1/xrock");
    ck("lava is recognised from contents alone",
       m && (m->roles & MAPGEN_ROLE_LAVA),
       m ? "roles disagree" : "material missing");

    ck("an absent material is not fuzzily matched",
       MapGenGenome_FindMaterial(g, "e1u1/water") == NULL,
       "a prefix of a real name must not resolve");

    MapGenGenome_Free(g);
}

static void test_animation_and_refs(void)
{
    printf("\n=== animation chains and reference counts\n");
    static const synth_tex_t texes[] = {
        { "e1u1/anim0", 0, MAPGEN_CONTENTS_SOLID, 1 },
        { "e1u1/anim1", 0, MAPGEN_CONTENTS_SOLID, -1 },
    };
    mapgen_genome_t *g = extract(texes, 2, "{\n\"classname\" \"worldspawn\"\n}\n", NULL, NULL);
    if (!ck("the synthetic map extracts", g != NULL, ""))
        return;

    const mapgen_material_t *a = MapGenGenome_FindMaterial(g, "e1u1/anim0");
    const mapgen_material_t *b = MapGenGenome_FindMaterial(g, "e1u1/anim1");
    ck("a texinfo with a next link marks its material animated",
       a && (a->roles & MAPGEN_ROLE_ANIMATED), "");
    ck("a texinfo without one does not",
       b && !(b->roles & MAPGEN_ROLE_ANIMATED), "");
    ck("brushside references are counted", a && a->brushside_refs == 6,
       a ? "wrong count" : "missing");
    MapGenGenome_Free(g);
}

static void test_entities(void)
{
    printf("\n=== entities are parsed strictly\n");
    static const synth_tex_t texes[] = { { "e1u1/wall", 0, MAPGEN_CONTENTS_SOLID, -1 } };

    const char *ents =
        "{\n\"classname\" \"worldspawn\"\n\"sky\" \"unit1_\"\n}\n"
        "{\n\"classname\" \"info_player_deathmatch\"\n\"origin\" \"16 -32 24\"\n\"angle\" \"90\"\n}\n"
        "{\n\"classname\" \"func_door\"\n\"targetname\" \"door1\"\n}\n"
        "{\n\"classname\" \"info_player_deathmatch\"\n\"origin\" \"1 2 3\"\n}\n";

    mapgen_genome_t *g = extract(texes, 1, ents, NULL, NULL);
    if (!ck("the synthetic map extracts", g != NULL, ""))
        return;

    ck("every entity block is seen", MapGenGenome_NumEntities(g) == 4, "");
    ck("classnames are counted exactly",
       MapGenGenome_CountClassname(g, "info_player_deathmatch") == 2, "");
    ck("an absent classname counts zero",
       MapGenGenome_CountClassname(g, "info_player_start") == 0, "");

    const mapgen_entity_t *e = MapGenGenome_Entity(g, 1);
    ck("origin is parsed", e && e->has_origin, "");
    ck("origin values are exact",
       e && e->origin[0] == 16.0f && e->origin[1] == -32.0f && e->origin[2] == 24.0f, "");
    const char *angle = MapGenGenome_EntityValue(e, "angle");
    ck("keys are retrievable by exact name", angle && !strcmp(angle, "90"), "");
    ck("an absent key is NULL", MapGenGenome_EntityValue(e, "angles") == NULL,
       "a near-miss key must not resolve");

    const mapgen_entity_t *door = MapGenGenome_Entity(g, 2);
    const char *tn = MapGenGenome_EntityValue(door, "targetname");
    ck("targetname survives intact", tn && !strcmp(tn, "door1"), "");
    ck("an entity without an origin says so", door && !door->has_origin, "");

    MapGenGenome_Free(g);

    printf("\n=== malformed entity strings are refused, not guessed past\n");
    struct { const char *name; const char *text; } bad[] = {
        { "unterminated block",  "{\n\"classname\" \"worldspawn\"\n" },
        { "key without value",   "{\n\"classname\"\n}\n" },
        { "stray token",         "{\n classname \"worldspawn\"\n}\n" },
        { "text outside a block", "\"classname\" \"worldspawn\"\n" },
        { "unterminated quote",  "{\n\"classname\" \"worldspawn\n}\n" },
    };
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        mapgen_genome_result_t r = MAPGEN_GENOME_OK;
        mapgen_genome_t *g2 = extract(texes, 1, bad[i].text, NULL, &r);
        char name[128];
        snprintf(name, sizeof(name), "%s is refused", bad[i].name);
        ck(name, g2 == NULL && r != MAPGEN_GENOME_OK, MapGenGenome_ResultName(r));
        MapGenGenome_Free(g2);
    }

    /* An overlong value must be an ERROR, never a silent truncation: a
       truncated targetname would quietly rewire a map. */
    {
        char big[MAPGEN_GENOME_VALUE_BYTES + 128];
        size_t n = 0;
        n += (size_t)snprintf(big + n, sizeof(big) - n, "{\n\"classname\" \"worldspawn\"\n\"message\" \"");
        for (size_t i = 0; i < MAPGEN_GENOME_VALUE_BYTES + 16; i++)
            big[n++] = 'x';
        snprintf(big + n, sizeof(big) - n, "\"\n}\n");
        mapgen_genome_result_t r = MAPGEN_GENOME_OK;
        mapgen_genome_t *g3 = extract(texes, 1, big, NULL, &r);
        ck("an overlong value is an error, not a truncation",
           g3 == NULL && r == MAPGEN_GENOME_ERR_ENTITY_TOO_LONG,
           MapGenGenome_ResultName(r));
        MapGenGenome_Free(g3);
    }
}

static void test_determinism(void)
{
    printf("\n=== the digest is deterministic and order-independent\n");
    static const synth_tex_t forward[] = {
        { "e1u1/aaa", 0, MAPGEN_CONTENTS_SOLID, -1 },
        { "e1u1/bbb", MAPGEN_SURF_SKY, MAPGEN_CONTENTS_SOLID, -1 },
        { "e1u1/ccc", MAPGEN_SURF_WARP, MAPGEN_CONTENTS_WATER, -1 },
    };
    static const synth_tex_t shuffled[] = {
        { "e1u1/ccc", MAPGEN_SURF_WARP, MAPGEN_CONTENTS_WATER, -1 },
        { "e1u1/aaa", 0, MAPGEN_CONTENTS_SOLID, -1 },
        { "e1u1/bbb", MAPGEN_SURF_SKY, MAPGEN_CONTENTS_SOLID, -1 },
    };
    const char *ents = "{\n\"classname\" \"worldspawn\"\n}\n";

    mapgen_genome_t *a = extract(forward, 3, ents, NULL, NULL);
    mapgen_genome_t *b = extract(forward, 3, ents, NULL, NULL);
    mapgen_genome_t *c = extract(shuffled, 3, ents, NULL, NULL);
    if (!ck("all three extract", a && b && c, "")) {
        MapGenGenome_Free(a); MapGenGenome_Free(b); MapGenGenome_Free(c);
        return;
    }

    ck("the same map digests identically twice",
       MapGenGenome_Digest(a) == MapGenGenome_Digest(b), "");
    ck("the texinfo lump's ORDER does not change the digest",
       MapGenGenome_Digest(a) == MapGenGenome_Digest(c),
       "materials must be emitted in sorted name order (contract 10)");

    MapGenGenome_Free(a);
    MapGenGenome_Free(b);
    MapGenGenome_Free(c);
}

/* ------------------------------------------------------------------------ */

static uint8_t *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    rewind(f);
    if (size < 0) { fclose(f); return NULL; }
    uint8_t *data = malloc((size_t)size ? (size_t)size : 1);
    if (!data) { fclose(f); return NULL; }
    *out_size = fread(data, 1, (size_t)size, f);
    fclose(f);
    return data;
}

static int run_map(const char *path, bool digest_only)
{
    size_t size = 0;
    uint8_t *data = read_file(path, &size);
    if (!data) {
        printf("READ_FAILED\n");
        return 1;
    }
    mapgen_bsp_t *bsp = NULL;
    mapgen_bsp_result_t r = MapGenBsp_Load(data, size, &bsp);
    free(data);
    if (r != MAPGEN_BSP_OK) {
        printf("BSP_%s\n", MapGenBsp_ResultName(r));
        return 0;
    }
    mapgen_genome_t *g = NULL;
    mapgen_genome_result_t gr = MapGenGenome_Extract(bsp, &g);
    if (gr != MAPGEN_GENOME_OK) {
        printf("GENOME_%s\n", MapGenGenome_ResultName(gr));
        MapGenBsp_Free(bsp);
        return 0;
    }

    if (digest_only) {
        printf("OK %016llx\n", (unsigned long long)MapGenGenome_Digest(g));
    } else {
        uint32_t sky = 0, water = 0, lava = 0, slime = 0, clip = 0, anim = 0;
        for (uint32_t i = 0; i < MapGenGenome_NumMaterials(g); i++) {
            const mapgen_material_t *m = MapGenGenome_Material(g, i);
            if (m->roles & MAPGEN_ROLE_SKY) sky++;
            if (m->roles & MAPGEN_ROLE_WATER) water++;
            if (m->roles & MAPGEN_ROLE_LAVA) lava++;
            if (m->roles & MAPGEN_ROLE_SLIME) slime++;
            if (m->roles & MAPGEN_ROLE_CLIP) clip++;
            if (m->roles & MAPGEN_ROLE_ANIMATED) anim++;
        }
        printf("OK %u %u %u %u %u %u %u %u %u\n",
               MapGenGenome_NumMaterials(g), MapGenGenome_NumEntities(g),
               sky, water, lava, slime, clip, anim,
               MapGenGenome_CountClassname(g, "worldspawn"));
    }

    MapGenGenome_Free(g);
    MapGenBsp_Free(bsp);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc >= 2 && !strcmp(argv[1], "selftest")) {
        printf("=== MAPGEN-1 MapGenome layer 1\n");
        test_roles_come_from_flags();
        test_animation_and_refs();
        test_entities();
        test_determinism();
        printf("\n=== %d cases asserted, %d failures\n", g_cases, g_failed);
        printf("%s\n", g_failed ? "RESULT: FAIL" : "RESULT: PASS");
        return g_failed ? 1 : 0;
    }
    if (argc >= 3 && !strcmp(argv[1], "map"))
        return run_map(argv[2], false);
    if (argc >= 3 && !strcmp(argv[1], "digest"))
        return run_map(argv[2], true);

    printf("usage: driver selftest | map <bsp> | digest <bsp>\n");
    return 2;
}
