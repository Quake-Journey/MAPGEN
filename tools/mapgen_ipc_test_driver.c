/*
 * MAPGEN-1 IPC test driver.
 *
 * A throwaway executable that exposes the REAL C codec to the Python property
 * matrix in tools/check_mapgen_ipc_contract.py. It is compiled on demand by
 * that script with gcc and never by the canonical deploy path: Hard Rule #30
 * permits a targeted throwaway compile for checking, and forbids it only for
 * an artifact that will be run, tested, deployed or given to the PO.
 *
 * Testing the codec through the actual compiled C - rather than through a
 * Python reimplementation of the same layout - is the point. A second
 * implementation of a spec agrees with the first exactly when both authors
 * made the same mistake.
 *
 * Protocol on stdin/stdout, one line per command, so the harness can drive
 * thousands of cases without a process launch each:
 *
 *   encode <type> <payload_len> <sequence> <uuid-hex-32>
 *       -> "ok <hex of the 36 header bytes>" | "err"
 *   decode <hex>
 *       -> "<DECODE_NAME> <type> <payload_len> <sequence> <uuid-hex>"
 *   stream_reset
 *   stream_accept <hex>
 *       -> "accept" | "reject"
 *   stream_failed
 *       -> "0" | "1"
 *   dir <type>
 *       -> "<w2c 0|1> <c2w 0|1>"
 *   consts
 *       -> "<header_bytes> <magic> <version> <max_payload> <type_count>"
 *   quit
 */

#include "common/mapgen_protocol.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LINE_MAX_BYTES 262144

static int hex_value(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static size_t hex_decode(const char *text, uint8_t *out, size_t out_max)
{
    size_t n = 0;
    while (text[0] && text[1] && n < out_max) {
        int hi = hex_value((unsigned char)text[0]);
        int lo = hex_value((unsigned char)text[1]);
        if (hi < 0 || lo < 0)
            break;
        out[n++] = (uint8_t)((hi << 4) | lo);
        text += 2;
    }
    return n;
}

static void hex_print(const uint8_t *bytes, size_t count)
{
    for (size_t i = 0; i < count; i++)
        printf("%02x", bytes[i]);
}

int main(void)
{
    static char line[LINE_MAX_BYTES];
    static uint8_t buffer[LINE_MAX_BYTES / 2];
    mapgen_ipc_stream_t stream;

    MapGenIpc_StreamInit(&stream);

    while (fgets(line, sizeof(line), stdin)) {
        char *nl = strpbrk(line, "\r\n");
        if (nl)
            *nl = '\0';

        if (!strcmp(line, "quit"))
            break;

        if (!strcmp(line, "consts")) {
            printf("%d %u %u %u %d\n",
                   MAPGEN_IPC_HEADER_BYTES,
                   (unsigned)MAPGEN_IPC_MAGIC,
                   (unsigned)MAPGEN_IPC_VERSION,
                   (unsigned)MAPGEN_IPC_MAX_PAYLOAD,
                   (int)MAPGEN_IPC_TYPE_COUNT);
            fflush(stdout);
            continue;
        }

        if (!strncmp(line, "encode ", 7)) {
            unsigned type = 0, payload = 0, sequence = 0;
            char uuid_hex[64] = { 0 };
            if (sscanf(line + 7, "%u %u %u %63s", &type, &payload, &sequence, uuid_hex) != 4) {
                printf("err\n");
                fflush(stdout);
                continue;
            }
            mapgen_ipc_header_t header;
            memset(&header, 0, sizeof(header));
            header.type = (uint16_t)type;
            header.payload_len = payload;
            header.sequence = sequence;
            hex_decode(uuid_hex, header.job_uuid, MAPGEN_IPC_UUID_BYTES);

            uint8_t out[MAPGEN_IPC_HEADER_BYTES];
            if (!MapGenIpc_EncodeHeader(out, sizeof(out), &header)) {
                printf("err\n");
            } else {
                printf("ok ");
                hex_print(out, sizeof(out));
                printf("\n");
            }
            fflush(stdout);
            continue;
        }

        if (!strncmp(line, "decode ", 7)) {
            size_t n = hex_decode(line + 7, buffer, sizeof(buffer));
            mapgen_ipc_header_t header;
            memset(&header, 0, sizeof(header));
            mapgen_ipc_decode_t r = MapGenIpc_DecodeHeader(buffer, n, &header);
            printf("%s %u %u %u ", MapGenIpc_DecodeName(r),
                   (unsigned)header.type, (unsigned)header.payload_len,
                   (unsigned)header.sequence);
            hex_print(header.job_uuid, MAPGEN_IPC_UUID_BYTES);
            printf("\n");
            fflush(stdout);
            continue;
        }

        if (!strcmp(line, "stream_reset")) {
            MapGenIpc_StreamInit(&stream);
            printf("ok\n");
            fflush(stdout);
            continue;
        }

        if (!strncmp(line, "stream_accept ", 14)) {
            size_t n = hex_decode(line + 14, buffer, sizeof(buffer));
            mapgen_ipc_header_t header;
            memset(&header, 0, sizeof(header));
            mapgen_ipc_decode_t r = MapGenIpc_DecodeHeader(buffer, n, &header);
            if (r != MAPGEN_IPC_DECODE_OK) {
                printf("reject\n");
            } else {
                printf("%s\n", MapGenIpc_StreamAccept(&stream, &header) ? "accept" : "reject");
            }
            fflush(stdout);
            continue;
        }

        if (!strcmp(line, "stream_failed")) {
            printf("%d\n", stream.failed ? 1 : 0);
            fflush(stdout);
            continue;
        }

        if (!strncmp(line, "dir ", 4)) {
            unsigned type = (unsigned)strtoul(line + 4, NULL, 10);
            printf("%d %d\n",
                   MapGenIpc_IsWorkerToController((uint16_t)type) ? 1 : 0,
                   MapGenIpc_IsControllerToWorker((uint16_t)type) ? 1 : 0);
            fflush(stdout);
            continue;
        }

        printf("err\n");
        fflush(stdout);
    }
    return 0;
}
