/*
 * Drive a Project publication from the outside.
 *
 *   mapgen_publish_driver commit --maps DIR --name N [--job J]
 *                                --member ROLE:SUFFIX:PATH[:required[:SHA]]
 *   mapgen_publish_driver verify --maps DIR --name N
 *   mapgen_publish_driver list   --maps DIR
 *
 * Prints what happened in lines a guard can read. Exit code 0 when the
 * operation succeeded, 1 when it was refused, 2 when the arguments were wrong -
 * a refusal is an answer, not an error.
 */
#include "common/mapgen_publish.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void report(const mapgen_publish_report_t *r)
{
    printf("name %s\n", r->name);
    printf("job %s\n", r->job_identity);
    printf("manifest %s\n", r->manifest_sha256);
    printf("members %u\n", r->num_members);
    for (uint32_t i = 0; i < r->num_members; i++)
        printf("member %s %s %s\n", r->role[i], r->file[i], r->sha256[i]);
    printf("detail %s\n", r->detail);
}

/* ROLE:SUFFIX:PATH[:required[:SHA]] - split on ':' but not on the one inside
   a Windows drive letter, which is what the length test is for. */
static bool parse_member(char *text, mapgen_publish_member_t *out)
{
    memset(out, 0, sizeof(*out));
    char *role = text;
    char *suffix = strchr(role, ':');
    if (!suffix)
        return false;
    *suffix++ = '\0';
    char *path = strchr(suffix, ':');
    if (!path)
        return false;
    *path++ = '\0';

    /* The path may itself contain ':' after a drive letter, so the optional
       fields are taken from the END. */
    char *required = NULL, *sha = NULL;
    for (char *at = path + 2; *at; at++) {
        if (*at != ':')
            continue;
        if (!required)
            required = at;
        else
            sha = at;
    }
    if (sha) {
        *sha++ = '\0';
        snprintf(out->declared_sha256, sizeof(out->declared_sha256), "%s", sha);
    }
    if (required) {
        *required++ = '\0';
        out->required = !strcmp(required, "required");
    }
    snprintf(out->role, sizeof(out->role), "%s", role);
    snprintf(out->suffix, sizeof(out->suffix), "%s", suffix);
    snprintf(out->source, sizeof(out->source), "%s", path);
    return true;
}

int main(int argc, char **argv)
{
    if (argc < 2)
        return 2;
    const char *verb = argv[1];
    /* For `bind`: the file whose CONTENT is offered, which is not required to
       be the Project's own map - that is the case worth testing. */
    const char *bytes_from = NULL;

    mapgen_publish_request_t request;
    memset(&request, 0, sizeof(request));
    const char *maps = NULL, *name = NULL;

    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--maps") && i + 1 < argc)
            maps = argv[++i];
        else if (!strcmp(argv[i], "--name") && i + 1 < argc)
            name = argv[++i];
        else if (!strcmp(argv[i], "--jobdir") && i + 1 < argc)
            snprintf(request.job_dir, sizeof(request.job_dir), "%s",
                     argv[++i]);
        else if (!strcmp(argv[i], "--job") && i + 1 < argc)
            snprintf(request.job_identity, sizeof(request.job_identity), "%s",
                     argv[++i]);
        else if (!strcmp(argv[i], "--bytes") && i + 1 < argc)
            bytes_from = argv[++i];
        else if (!strcmp(argv[i], "--member") && i + 1 < argc) {
            if (request.num_members >= MAPGEN_PUBLISH_MEMBERS)
                return 2;
            if (!parse_member(argv[++i],
                              &request.members[request.num_members]))
                return 2;
            request.num_members++;
        }
    }
    if (!maps)
        return 2;

    mapgen_publish_report_t out;
    if (!strcmp(verb, "commit")) {
        if (!name)
            return 2;
        snprintf(request.maps_dir, sizeof(request.maps_dir), "%s", maps);
        snprintf(request.name, sizeof(request.name), "%s", name);
        const mapgen_publish_result_t rc =
            MapGenPublish_Commit(&request, &out);
        printf("result %s\n", MapGenPublish_ResultName(rc));
        report(&out);
        return rc == MAPGEN_PUBLISH_OK ? 0 : 1;
    }
    if (!strcmp(verb, "verify")) {
        if (!name)
            return 2;
        const mapgen_publish_result_t rc =
            MapGenPublish_Verify(maps, name, &out);
        printf("result %s\n", MapGenPublish_ResultName(rc));
        report(&out);
        return rc == MAPGEN_PUBLISH_OK ? 0 : 1;
    }
    /*
     * `bind FILE` - the question a loader asks.
     *
     * The bytes come from a file NAMED ON THE COMMAND LINE, which need not be
     * the Project's own map. That is deliberate: it is how a caller holding
     * something other than what the path holds is expressed, which is what a
     * load in the window between verifying and reading would be.
     */
    if (!strcmp(verb, "bind")) {
        if (!name || !bytes_from)
            return 2;
        FILE *f = fopen(bytes_from, "rb");
        if (!f) {
            printf("result ERR_SOURCE\n");
            printf("detail cannot read %s\n", bytes_from);
            return 1;
        }
        fseek(f, 0, SEEK_END);
        long size = ftell(f);
        fseek(f, 0, SEEK_SET);
        void *buf = size > 0 ? malloc((size_t)size) : malloc(1);
        if (!buf || (size > 0
                     && fread(buf, 1, (size_t)size, f) != (size_t)size)) {
            free(buf);
            fclose(f);
            printf("result ERR_SOURCE\n");
            printf("detail cannot read %s\n", bytes_from);
            return 1;
        }
        fclose(f);
        const mapgen_publish_result_t rc =
            MapGenPublish_BindBytes(maps, name, buf, (size_t)(size > 0 ? size : 0),
                                    &out);
        free(buf);
        printf("result %s\n", MapGenPublish_ResultName(rc));
        report(&out);
        return rc == MAPGEN_PUBLISH_OK ? 0 : 1;
    }
    if (!strcmp(verb, "list")) {
        char names[64][MAPGEN_PUBLISH_NAME];
        const uint32_t n = MapGenPublish_List(maps, names, 64);
        printf("result OK\n");
        printf("projects %u\n", n);
        for (uint32_t i = 0; i < n; i++)
            printf("project %s\n", names[i]);
        return 0;
    }
    return 2;
}
