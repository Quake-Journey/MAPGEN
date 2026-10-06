/*
 * Write the certificates a map produces, or check one against a map.
 *
 * Two halves of the same question. `--write` explores a compiled map and puts
 * down what it found, stamped with that map's own hash, which is what the
 * product path does. `--read` takes a file written that way and asks the map
 * in front of it whether it still does that - identity first, then a replay -
 * which is what an auditor does.
 *
 *   mapgen_certificate_driver <map.bsp> --write <file>
 *   mapgen_certificate_driver <map.bsp> --read <file> [--candidate HEX]
 *                                       [--physics HEX] [--any-map]
 *
 * `--candidate` and `--physics` override what the map and the build actually
 * say, so a stale certificate can be produced deliberately. `--any-map` keeps
 * the certificate's own hashes and asks THIS map to reproduce it, which is the
 * case where an edit carved away the ledge somebody launched from.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/mapgen_certificate.h"
#include "common/mapgen_digest.h"
#include "common/mapgen_reach.h"

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

/* The map's own identity, which is what a certificate about it must carry. */
static void map_sha256(const char *path, char out[65])
{
    out[0] = '\0';
    FILE *f = fopen(path, "rb");
    if (!f)
        return;
    mapgen_sha256_t ctx;
    MapGenDigest_Sha256Init(&ctx);
    uint8_t buffer[65536];
    size_t got;
    while ((got = fread(buffer, 1, sizeof(buffer), f)) > 0)
        MapGenDigest_Sha256Update(&ctx, buffer, got);
    fclose(f);
    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256Final(&ctx, digest);
    MapGenDigest_Sha256Hex(digest, out);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <map.bsp> --write FILE | --read FILE"
                        " [--candidate HEX] [--physics HEX] [--any-map]\n",
                argv[0]);
        return 2;
    }

    const char *map_path = argv[1];
    const char *write_to = NULL, *read_from = NULL;
    const char *candidate_override = NULL, *physics_override = NULL;
    bool any_map = false;
    for (int a = 2; a < argc; a++) {
        if (!strcmp(argv[a], "--write") && a + 1 < argc)
            write_to = argv[++a];
        else if (!strcmp(argv[a], "--read") && a + 1 < argc)
            read_from = argv[++a];
        else if (!strcmp(argv[a], "--candidate") && a + 1 < argc)
            candidate_override = argv[++a];
        else if (!strcmp(argv[a], "--physics") && a + 1 < argc)
            physics_override = argv[++a];
        else if (!strcmp(argv[a], "--any-map"))
            any_map = true;
    }

    char candidate_hash[65];
    map_sha256(map_path, candidate_hash);
    char physics[65];
    MapGenReach_PhysicsSha256(physics);

    mapgen_bsp_t *bsp = load(map_path);
    if (!bsp) {
        fprintf(stderr, "cannot read %s\n", map_path);
        return 2;
    }

    if (write_to) {
        mapgen_reach_t *reach = NULL;
        if (MapGenReach_Explore(bsp, 40000u, &reach) != MAPGEN_REACH_OK
            || !reach) {
            MapGenReach_Free(reach);
            MapGenBsp_Free(bsp);
            fprintf(stderr, "the exploration failed\n");
            return 2;
        }
        const mapgen_reach_report_t *r = MapGenReach_Report(reach);
        printf("%u pickups, %u out of a player's reach, %u by rocket jump\n",
               r->items, r->items_unreachable, r->items_special);

        mapgen_certificate_set_t set = *MapGenReach_Certificates(reach);
        MapGenReach_Free(reach);
        MapGenCertificate_Stamp(&set, candidate_hash, candidate_hash, physics);

        char *text = malloc(65536);
        if (!text) {
            MapGenBsp_Free(bsp);
            return 2;
        }
        MapGenCertificate_Render(&set, text, 65536);
        FILE *out = fopen(write_to, "wb");
        if (out) {
            fputs(text, out);
            fclose(out);
        }
        printf("%s", text);
        printf("wrote %u certificate%s\n", set.count,
               set.count == 1 ? "" : "s");
        free(text);
        MapGenBsp_Free(bsp);
        return 0;
    }

    if (!read_from) {
        MapGenBsp_Free(bsp);
        fprintf(stderr, "nothing to do: pass --write or --read\n");
        return 2;
    }

    FILE *f = fopen(read_from, "rb");
    if (!f) {
        MapGenBsp_Free(bsp);
        fprintf(stderr, "cannot read %s\n", read_from);
        return 2;
    }
    char *text = malloc(65536);
    if (!text) {
        fclose(f);
        MapGenBsp_Free(bsp);
        return 2;
    }
    const size_t got = fread(text, 1, 65535, f);
    text[got] = '\0';
    fclose(f);

    mapgen_certificate_set_t set;
    const uint32_t count = MapGenCertificate_Parse(text, &set);
    free(text);
    printf("read %u certificate%s\n", count, count == 1 ? "" : "s");
    if (!count) {
        MapGenBsp_Free(bsp);
        printf("replay ERR_ARGS\n");
        return 1;
    }

    /*
     * What the checker is TOLD the map and the physics are.
     *
     * `--any-map` is the case where somebody presents a certificate along with
     * the map it claims to be about: its own hashes are taken at face value
     * for the identity check, and the replay is what has to catch it.
     */
    const char *candidate = candidate_override ? candidate_override
                          : any_map ? set.entries[0].candidate_sha256
                          : candidate_hash;
    const char *donor = candidate_override ? set.entries[0].donor_sha256
                      : any_map ? set.entries[0].donor_sha256
                      : candidate_hash;
    const char *phys = physics_override ? physics_override : physics;

    const mapgen_certificate_result_t identity =
        MapGenCertificate_Verify(&set.entries[0], candidate, donor, phys);
    printf("verify %s\n", MapGenCertificate_ResultName(identity));
    if (identity != MAPGEN_CERT_OK) {
        MapGenBsp_Free(bsp);
        return 1;
    }

    const mapgen_certificate_result_t replayed =
        MapGenCertificate_Replay(&set.entries[0], bsp, candidate, donor, phys);
    printf("replay %s\n", MapGenCertificate_ResultName(replayed));
    MapGenBsp_Free(bsp);
    return replayed == MAPGEN_CERT_OK ? 0 : 1;
}
