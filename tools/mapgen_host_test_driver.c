/*
 * MAPGEN-1 worker-host test driver.
 *
 * Drives the REAL process host against a REAL worker child, so the lifecycle
 * matrix exercises actual process creation, an actual job object, actual pipes
 * and an actual crash - none of which an injected seam can represent
 * (Hard Rule #51).
 *
 * Compiled on demand by tools/check_mapgen_worker_lifecycle.py with a targeted
 * throwaway gcc invocation. It never leaves tools/ and is never handed to
 * anyone, which is exactly the throwaway check Hard Rule #30 permits.
 *
 * usage: mapgen_host_driver <worker-exe> <work-dir> <scenario>
 *
 * Scenarios print one `key=value` line each and exit 0 when the scenario
 * completed as a scenario (not when the worker succeeded); the Python side
 * asserts on the keys. Every scenario ends by closing the host, and the last
 * line is always `pid=<n>` so the harness can prove the process is gone.
 */

#include "common/mapgen_process.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

static const char BUILD_ID[] = "q2prox-mapgen-worker-1";

static void fill_desc(mapgen_process_desc_t *desc, const char *exe, const char *dir,
                      const uint8_t *token, const uint8_t *uuid, const char *build_id)
{
    memset(desc, 0, sizeof(*desc));
    desc->exe_path = exe;
    desc->work_dir = dir;
    desc->token = token;
    desc->job_uuid = uuid;
    desc->handshake_timeout_ms = 4000;
    strncpy(desc->expected_build_id, build_id, MAPGEN_PROCESS_BUILD_ID_BYTES);
}

int main(int argc, char **argv)
{
    if (argc < 4) {
        printf("usage=missing\n");
        return 2;
    }
    const char *exe = argv[1];
    const char *dir = argv[2];
    const char *scenario = argv[3];

    uint8_t token[MAPGEN_IPC_TOKEN_BYTES];
    uint8_t uuid[MAPGEN_IPC_UUID_BYTES];
    for (int i = 0; i < MAPGEN_IPC_TOKEN_BYTES; i++)
        token[i] = (uint8_t)(0x5A ^ (i * 7 + 3));
    for (int i = 0; i < MAPGEN_IPC_UUID_BYTES; i++)
        uuid[i] = (uint8_t)(0xA5 ^ (i * 11 + 1));

    mapgen_process_desc_t desc;
    const char *build_id = BUILD_ID;
    if (!strcmp(scenario, "wrong_expected_build_id"))
        build_id = "some-other-build-id";
    fill_desc(&desc, exe, dir, token, uuid, build_id);

    if (!strcmp(scenario, "missing_exe")) {
        desc.exe_path = "O:\\Claude2\\_agent_temp\\claude\\definitely-not-here.exe";
        mapgen_process_t *host = NULL;
        mapgen_process_result_t r = MapGenProcess_Launch(&desc, &host);
        printf("launch=%s\n", MapGenProcess_ResultName(r));
        printf("host_null=%d\n", host == NULL ? 1 : 0);
        printf("pid=0\n");
        return 0;
    }

    if (!strcmp(scenario, "short_handshake_timeout"))
        desc.handshake_timeout_ms = 300;

    mapgen_process_t *host = NULL;
    mapgen_process_result_t r = MapGenProcess_Launch(&desc, &host);
    printf("launch=%s\n", MapGenProcess_ResultName(r));
    if (r != MAPGEN_PROC_OK) {
        printf("host_null=%d\n", host == NULL ? 1 : 0);
        printf("pid=0\n");
        return 0;
    }

    unsigned pid = MapGenProcess_Pid(host);
    printf("pid_launched=%u\n", pid);
    printf("alive_after_launch=%d\n", MapGenProcess_IsAlive(host) ? 1 : 0);

    mapgen_ipc_header_t header;
    uint8_t payload[4096];
    uint32_t payload_len = 0;

    if (!strcmp(scenario, "handshake_only")) {
        r = MapGenProcess_Receive(host, 3000, &header, payload, sizeof(payload), &payload_len);
        printf("first_frame=%s\n", MapGenProcess_ResultName(r));
        printf("first_frame_type=%s\n", MapGenIpc_TypeName(header.type));
        MapGenProcess_Close(host);
        printf("pid=%u\n", pid);
        return 0;
    }

    if (!strcmp(scenario, "desync_after_hello")) {
        r = MapGenProcess_Receive(host, 3000, &header, payload, sizeof(payload), &payload_len);
        printf("first_frame=%s\n", MapGenProcess_ResultName(r));
        /* A second receive on a latched stream must stay refused. */
        mapgen_process_result_t again =
            MapGenProcess_Receive(host, 500, &header, payload, sizeof(payload), &payload_len);
        printf("second_frame=%s\n", MapGenProcess_ResultName(again));
        MapGenProcess_Close(host);
        printf("pid=%u\n", pid);
        return 0;
    }

    if (!strcmp(scenario, "crash_after_hello")) {
        r = MapGenProcess_Receive(host, 3000, &header, payload, sizeof(payload), &payload_len);
        printf("after_crash=%s\n", MapGenProcess_ResultName(r));
        int32_t code = 0;
        printf("exited=%d\n", MapGenProcess_WaitExit(host, 3000, &code) ? 1 : 0);
        printf("alive=%d\n", MapGenProcess_IsAlive(host) ? 1 : 0);
        MapGenProcess_Close(host);
        printf("pid=%u\n", pid);
        return 0;
    }

    if (!strcmp(scenario, "hang_then_close")) {
        r = MapGenProcess_Receive(host, 400, &header, payload, sizeof(payload), &payload_len);
        printf("receive=%s\n", MapGenProcess_ResultName(r));
        printf("alive_before_close=%d\n", MapGenProcess_IsAlive(host) ? 1 : 0);
        MapGenProcess_Close(host);
        printf("pid=%u\n", pid);
        return 0;
    }

    if (!strcmp(scenario, "run_to_staged_result") || !strcmp(scenario, "cancel_mid_job")) {
        /* READY */
        r = MapGenProcess_Receive(host, 3000, &header, payload, sizeof(payload), &payload_len);
        printf("ready=%s\n", MapGenProcess_ResultName(r));
        printf("ready_type=%s\n", MapGenIpc_TypeName(header.type));

        r = MapGenProcess_Send(host, MAPGEN_IPC_START_VALIDATE, NULL, 0);
        printf("start=%s\n", MapGenProcess_ResultName(r));

        int progress = 0;
        int cancelled = 0;
        int staged = 0;
        bool sent_cancel = false;
        for (int i = 0; i < 200; i++) {
            r = MapGenProcess_Receive(host, 3000, &header, payload, sizeof(payload), &payload_len);
            if (r != MAPGEN_PROC_OK) {
                printf("loop_end=%s\n", MapGenProcess_ResultName(r));
                break;
            }
            if (header.type == MAPGEN_IPC_PROGRESS) {
                progress++;
                if (!strcmp(scenario, "cancel_mid_job") && progress == 3 && !sent_cancel) {
                    sent_cancel = true;
                    printf("cancel_sent=%s\n", MapGenProcess_ResultName(MapGenProcess_RequestCancel(host)));
                }
            } else if (header.type == MAPGEN_IPC_CANCELLED) {
                cancelled = 1;
                break;
            } else if (header.type == MAPGEN_IPC_STAGED_RESULT) {
                staged = 1;
                break;
            }
        }
        printf("progress_frames=%d\n", progress);
        printf("cancelled=%d\n", cancelled);
        printf("staged=%d\n", staged);
        MapGenProcess_Close(host);
        printf("pid=%u\n", pid);
        return 0;
    }

    /*
     * A real generate job, end to end.
     *
     * The request is argv[4..] joined with newlines, so the harness decides
     * what to generate and this stays a driver. What comes back is printed
     * whole: a summary nobody can read is a result nobody can act on, and the
     * point of the scenario is what the summary SAYS.
     */
    if (!strcmp(scenario, "generate")) {
        r = MapGenProcess_Receive(host, 3000, &header, payload, sizeof(payload), &payload_len);
        printf("ready=%s\n", MapGenProcess_ResultName(r));

        char request[4096];
        size_t at = 0;
        for (int i = 4; i < argc && at + 2 < sizeof(request); i++) {
            const size_t n = strlen(argv[i]);
            if (at + n + 2 >= sizeof(request))
                break;
            memcpy(request + at, argv[i], n);
            at += n;
            request[at++] = '\n';
        }
        request[at] = '\0';

        r = MapGenProcess_Send(host, MAPGEN_IPC_START_GENERATE,
                               (const uint8_t *)request, (uint32_t)at + 1);
        printf("start=%s\n", MapGenProcess_ResultName(r));

        int progress = 0;
        for (int i = 0; i < 400; i++) {
            /* Generously long: a real compile is minutes, not milliseconds,
               and a timeout here would be the harness failing the worker for
               doing the work it was asked to do. */
            r = MapGenProcess_Receive(host, 1800000, &header, payload,
                                      sizeof(payload), &payload_len);
            if (r != MAPGEN_PROC_OK) {
                printf("loop_end=%s\n", MapGenProcess_ResultName(r));
                break;
            }
            if (header.type == MAPGEN_IPC_PROGRESS) {
                progress++;
            } else if (header.type == MAPGEN_IPC_STAGED_RESULT) {
                printf("staged=1\n");
                printf("summary_bytes=%u\n", payload_len);
                if (payload_len && payload_len < sizeof(payload)) {
                    payload[payload_len - 1] = 0;
                    printf("--- summary ---\n%s--- end ---\n",
                           (const char *)payload);
                }
                break;
            } else if (header.type == MAPGEN_IPC_ERROR) {
                printf("error=1\n");
                if (payload_len && payload_len < sizeof(payload)) {
                    payload[payload_len - 1] = 0;
                    printf("error_detail=%s\n", (const char *)payload);
                }
                break;
            } else if (header.type == MAPGEN_IPC_CANCELLED) {
                printf("cancelled=1\n");
                break;
            }
        }
        printf("progress_frames=%d\n", progress);
        MapGenProcess_Close(host);
        printf("pid=%u\n", pid);
        return 0;
    }

    if (!strcmp(scenario, "send_wrong_direction")) {
        /* The host must refuse to SEND a worker-to-controller type. */
        r = MapGenProcess_Send(host, MAPGEN_IPC_PROGRESS, NULL, 0);
        printf("send_worker_type=%s\n", MapGenProcess_ResultName(r));
        r = MapGenProcess_Send(host, MAPGEN_IPC_CANCEL, NULL, 0);
        printf("send_controller_type=%s\n", MapGenProcess_ResultName(r));
        MapGenProcess_Close(host);
        printf("pid=%u\n", pid);
        return 0;
    }

    if (!strcmp(scenario, "oversized_send")) {
        static uint8_t big[MAPGEN_IPC_MAX_PAYLOAD + 16];
        r = MapGenProcess_Send(host, MAPGEN_IPC_START_TRAIN, big, (uint32_t)sizeof(big));
        printf("oversized=%s\n", MapGenProcess_ResultName(r));
        MapGenProcess_Close(host);
        printf("pid=%u\n", pid);
        return 0;
    }

    printf("scenario=unknown\n");
    MapGenProcess_Close(host);
    printf("pid=%u\n", pid);
    return 0;
}
