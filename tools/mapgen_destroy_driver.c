/*
 * The destruction driver (Fable's brief 11 D2, ledger row 412l).
 *
 *   mapgen_destroy_driver FINISHED.bsp OUT.map --destruction D --seed S --pack PACK.txt --needs NEEDS.txt
 *                         [--game BASEQ2] [--skip MASK]
 *
 * Reads a finished map, puts D percent of it in ruins (`MapGenGeometryEdit_Destroy`) and writes the .map the
 * compiler takes; the cracked copies of the map's own textures it now wears go to NEEDS for
 * `tools/mapgen_textures.py crack`. Prints one line `destroyed: ...` the destroy tool and the Studio read.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

#include "common/mapgen_bsp.h"
#include "common/mapgen_geometry.h"
#include "common/mapgen_geometry_edit.h"

/* ---- brief 12: .png in and out (zlib), for the copies drawn at the game's own resolution ------------------------ */
static uint32_t be32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | (uint32_t)p[3];
}

static int paeth(int a, int b, int c)
{
    const int p = a + b - c, pa = abs(p - a), pb = abs(p - b), pc = abs(p - c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

/* 8-bit grey, grey+alpha, RGB, RGBA or paletted, not interlaced, to RGBA. NULL otherwise. */
static uint8_t *png_decode(const uint8_t *d, size_t n, uint32_t *w, uint32_t *h)
{
    static const uint8_t SIG[8] = { 137, 80, 78, 71, 13, 10, 26, 10 };
    if (n < 33 || memcmp(d, SIG, 8))
        return NULL;
    uint32_t W = 0, H = 0;
    int depth = 0, type = -1, interlace = 0;
    uint8_t pal[768] = { 0 }, trns[256];
    memset(trns, 255, sizeof(trns));
    uint8_t *idat = NULL;
    size_t ni = 0;
    for (size_t at = 8; at + 12 <= n;) {
        const uint32_t len = be32(d + at);
        const uint8_t *type4 = d + at + 4, *body = d + at + 8;
        if (at + 12 + (size_t)len > n)
            break;
        if (!memcmp(type4, "IHDR", 4) && len >= 13) {
            W = be32(body);
            H = be32(body + 4);
            depth = body[8];
            type = body[9];
            interlace = body[12];
        } else if (!memcmp(type4, "PLTE", 4)) {
            memcpy(pal, body, len < 768 ? len : 768);
        } else if (!memcmp(type4, "tRNS", 4) && type == 3) {
            memcpy(trns, body, len < 256 ? len : 256);
        } else if (!memcmp(type4, "IDAT", 4)) {
            uint8_t *grown = realloc(idat, ni + len);
            if (!grown) {
                free(idat);
                return NULL;
            }
            idat = grown;
            memcpy(idat + ni, body, len);
            ni += len;
        } else if (!memcmp(type4, "IEND", 4)) {
            break;
        }
        at += 12 + (size_t)len;
    }
    const int ch = type == 0 ? 1 : type == 2 ? 3 : type == 3 ? 1 : type == 4 ? 2 : type == 6 ? 4 : 0;
    if (!idat || depth != 8 || !ch || interlace || !W || !H || W > 8192 || H > 8192) {
        free(idat);
        return NULL;
    }
    const size_t stride = (size_t)W * ch;
    uLongf raw_len = (uLongf)((stride + 1) * H);
    uint8_t *raw = malloc(raw_len);
    uint8_t *out = malloc((size_t)W * H * 4);
    if (!raw || !out || uncompress(raw, &raw_len, idat, (uLong)ni) != Z_OK || raw_len != (stride + 1) * H) {
        free(idat);
        free(raw);
        free(out);
        return NULL;
    }
    free(idat);
    uint8_t *prev = NULL;
    for (uint32_t y = 0; y < H; y++) {
        uint8_t *row = raw + y * (stride + 1);
        const int filter = row[0];
        uint8_t *px = row + 1;
        for (size_t i = 0; i < stride; i++) {
            const int a = i >= (size_t)ch ? px[i - ch] : 0, b = prev ? prev[i] : 0;
            const int c = prev && i >= (size_t)ch ? prev[i - ch] : 0;
            int v = px[i];
            if (filter == 1)
                v += a;
            else if (filter == 2)
                v += b;
            else if (filter == 3)
                v += (a + b) / 2;
            else if (filter == 4)
                v += paeth(a, b, c);
            px[i] = (uint8_t)v;
        }
        for (uint32_t x = 0; x < W; x++) {
            uint8_t *o = out + ((size_t)y * W + x) * 4;
            const uint8_t *s = px + (size_t)x * ch;
            if (type == 0 || type == 4) {
                o[0] = o[1] = o[2] = s[0];
                o[3] = type == 4 ? s[1] : 255;
            } else if (type == 3) {
                memcpy(o, pal + 3 * s[0], 3);
                o[3] = trns[s[0]];
            } else {
                memcpy(o, s, 3);
                o[3] = type == 6 ? s[3] : 255;
            }
        }
        prev = px;
    }
    free(raw);
    *w = W;
    *h = H;
    return out;
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

static bool png_chunk(FILE *f, const char *type, const uint8_t *body, uint32_t len)
{
    uint8_t head[8];
    put32(head, len);
    memcpy(head + 4, type, 4);
    uLong crc = crc32(0L, (const Bytef *)type, 4);
    if (len)
        crc = crc32(crc, body, len);
    uint8_t tail[4];
    put32(tail, (uint32_t)crc);
    return fwrite(head, 1, 8, f) == 8 && (!len || fwrite(body, 1, len, f) == len) && fwrite(tail, 1, 4, f) == 4;
}

/* RGBA to an 8-bit RGBA .png (filter: none), written whole or not at all. */
static bool png_encode(const char *path, const uint8_t *rgba, uint32_t w, uint32_t h)
{
    static const uint8_t SIG[8] = { 137, 80, 78, 71, 13, 10, 26, 10 };
    const size_t stride = (size_t)w * 4;
    uint8_t *raw = malloc((stride + 1) * h);
    uLongf zl = compressBound((uLong)((stride + 1) * h));
    uint8_t *z = malloc(zl);
    bool ok = raw && z;
    for (uint32_t y = 0; ok && y < h; y++) {
        raw[y * (stride + 1)] = 0;
        memcpy(raw + y * (stride + 1) + 1, rgba + (size_t)y * stride, stride);
    }
    ok = ok && compress2(z, &zl, raw, (uLong)((stride + 1) * h), 6) == Z_OK;
    char tmp[1400];
    snprintf(tmp, sizeof(tmp), "%s.part", path);
    FILE *f = ok ? fopen(tmp, "wb") : NULL;
    if (f) {
        uint8_t ihdr[13] = { 0 };
        put32(ihdr, w);
        put32(ihdr + 4, h);
        ihdr[8] = 8;
        ihdr[9] = 6;
        ok = fwrite(SIG, 1, 8, f) == 8 && png_chunk(f, "IHDR", ihdr, 13) && png_chunk(f, "IDAT", z, (uint32_t)zl)
            && png_chunk(f, "IEND", NULL, 0);
        ok = fclose(f) == 0 && ok;
        remove(path);
        ok = ok && rename(tmp, path) == 0;
        if (!ok)
            remove(tmp);
    } else {
        ok = false;
    }
    free(raw);
    free(z);
    return ok;
}

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

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s FINISHED.bsp OUT.map --destruction D --seed S --pack PACK.txt --needs NEEDS.txt"
                        " [--game BASEQ2] [--skip MASK]\n", argv[0]);
        return 2;
    }
    uint32_t percent = 0, skip = 0;
    unsigned long long seed = 1;
    const char *pack = NULL, *needs = NULL, *masks = NULL, *into = NULL;
    for (int a = 3; a < argc; a++) {
        if (!strcmp(argv[a], "--destruction") && a + 1 < argc)
            percent = (uint32_t)strtoul(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--seed") && a + 1 < argc)
            seed = strtoull(argv[++a], NULL, 10);
        else if (!strcmp(argv[a], "--pack") && a + 1 < argc)
            pack = argv[++a];
        else if (!strcmp(argv[a], "--needs") && a + 1 < argc)
            needs = argv[++a];
        else if (!strcmp(argv[a], "--game") && a + 1 < argc)
            MapGenGeometryEdit_SetGameDir(argv[++a]);
        else if (!strcmp(argv[a], "--masks") && a + 1 < argc)
            masks = argv[++a];
        else if (!strcmp(argv[a], "--into") && a + 1 < argc)
            into = argv[++a];
        else if (!strcmp(argv[a], "--skip") && a + 1 < argc)
            skip = (uint32_t)strtoul(argv[++a], NULL, 10);
    }
    mapgen_bsp_t *bsp = load(argv[1]);
    mapgen_geometry_t *g = NULL;
    if (!bsp || MapGenGeometry_FromBsp(bsp, &g) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }
    MapGenGeometryEdit_DestroySkip(skip);
    MapGenGeometryEdit_SetImageCodec(png_decode, png_encode);
    mapgen_destroy_report_t r;
    const mapgen_geometry_result_t rc = MapGenGeometryEdit_Destroy(g, bsp, percent, seed, pack, needs, &r);
    if (rc != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "destruction failed: %s\n", MapGenGeometry_ResultName(rc));
        return 2;
    }
    printf("destroyed: percent %u cracks %u rubble %u craters %u breaches %u gouges %u broken %u collapses %u"
           " ruins %u patches %u refused %u budget %u rooms %u pack %u needs %u nearest %.0f wanted %u %u %u %u %u %u\n",
           percent, r.cracks, r.rubble, r.craters, r.breaches, r.gouges, r.broken, r.collapses, r.ruins, r.patches,
           r.refused, r.budget, r.rooms,
           r.pack, r.needs, (double)r.start_nearest,
           r.wanted[0], r.wanted[1], r.wanted[2], r.wanted[3], r.wanted[4], r.wanted[5]);
    if (masks && into && needs) {
        uint32_t missing = 0;
        const uint32_t drawn = MapGenGeometryEdit_DrawCracks(needs, masks, into, &missing);
        printf("cracks drawn: %u, %u without an original or a mask\n", drawn, missing);
    }
    if (MapGenGeometry_WriteValve220(g, argv[2]) != MAPGEN_GEOMETRY_OK) {
        fprintf(stderr, "cannot write %s\n", argv[2]);
        return 2;
    }
    MapGenGeometry_Free(g);
    MapGenBsp_Free(bsp);
    return 0;
}
