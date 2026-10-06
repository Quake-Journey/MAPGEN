/*
Copyright (C) 2026 Q2PRO-X

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
*/

/*
 * MAPGEN-1 - Controller <-> worker frame codec.
 *
 * Pure and dependency-free on purpose: it links into the client, into the
 * worker executable, and into the test driver without dragging any of them
 * into each other. Contract sections 5.3 and 24.
 *
 * Everything here validates BEFORE it trusts. `payload_len` in particular is
 * checked against the ceiling before any caller is allowed to see it, because
 * the caller's next move is to allocate that many bytes.
 */

#include "common/mapgen_protocol.h"

#include <string.h>

/* ------------------------------------------------------------------------ */

static uint32_t crc32_table[256];
static bool     crc32_ready;

static void crc32_build(void)
{
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++)
            c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        crc32_table[i] = c;
    }
    crc32_ready = true;
}

uint32_t MapGenIpc_Crc32(const uint8_t *bytes, size_t count)
{
    if (!crc32_ready)
        crc32_build();
    if (!bytes)
        return 0;

    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < count; i++)
        c = crc32_table[(c ^ bytes[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

/* ------------------------------------------------------------------------ */

static void put_u16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
}

static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
    p[2] = (uint8_t)((v >> 16) & 0xFF);
    p[3] = (uint8_t)((v >> 24) & 0xFF);
}

static uint16_t get_u16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/*
 * Wire layout, little-endian, 36 bytes:
 *
 *   0  magic        u32
 *   4  version      u16
 *   6  type         u16
 *   8  payload_len  u32
 *  12  sequence     u32
 *  16  job_uuid     16 bytes
 *  32  header_crc32 u32   (over bytes 0..31)
 */
#define OFS_MAGIC       0
#define OFS_VERSION     4
#define OFS_TYPE        6
#define OFS_PAYLOAD     8
#define OFS_SEQUENCE    12
#define OFS_UUID        16
#define OFS_CRC         32

bool MapGenIpc_EncodeHeader(uint8_t *out, size_t out_bytes,
                            const mapgen_ipc_header_t *header)
{
    if (!out || !header)
        return false;
    if (out_bytes < MAPGEN_IPC_HEADER_BYTES)
        return false;
    /* Refuse to PRODUCE a frame the decoder would have to reject. A codec
       that can emit something it will not accept turns a local bug into a
       peer-side protocol error, which is much harder to attribute. */
    if (header->payload_len > MAPGEN_IPC_MAX_PAYLOAD)
        return false;
    if (header->type == 0 || header->type >= MAPGEN_IPC_TYPE_COUNT)
        return false;

    put_u32(out + OFS_MAGIC, MAPGEN_IPC_MAGIC);
    put_u16(out + OFS_VERSION, MAPGEN_IPC_VERSION);
    put_u16(out + OFS_TYPE, header->type);
    put_u32(out + OFS_PAYLOAD, header->payload_len);
    put_u32(out + OFS_SEQUENCE, header->sequence);
    memcpy(out + OFS_UUID, header->job_uuid, MAPGEN_IPC_UUID_BYTES);
    put_u32(out + OFS_CRC, MapGenIpc_Crc32(out, OFS_CRC));
    return true;
}

mapgen_ipc_decode_t MapGenIpc_DecodeHeader(const uint8_t *in, size_t in_bytes,
                                           mapgen_ipc_header_t *out)
{
    if (!in || !out)
        return MAPGEN_IPC_DECODE_BAD_ARGUMENT;
    if (in_bytes < MAPGEN_IPC_HEADER_BYTES)
        return MAPGEN_IPC_DECODE_INCOMPLETE;

    uint32_t magic = get_u32(in + OFS_MAGIC);
    if (magic != MAPGEN_IPC_MAGIC)
        return MAPGEN_IPC_DECODE_BAD_MAGIC;

    uint16_t version = get_u16(in + OFS_VERSION);
    if (version != MAPGEN_IPC_VERSION)
        return MAPGEN_IPC_DECODE_BAD_VERSION;

    uint16_t type = get_u16(in + OFS_TYPE);
    if (type == 0 || type >= MAPGEN_IPC_TYPE_COUNT)
        return MAPGEN_IPC_DECODE_BAD_TYPE;

    uint32_t payload_len = get_u32(in + OFS_PAYLOAD);
    if (payload_len > MAPGEN_IPC_MAX_PAYLOAD)
        return MAPGEN_IPC_DECODE_PAYLOAD_TOO_LARGE;

    uint32_t crc = get_u32(in + OFS_CRC);
    if (crc != MapGenIpc_Crc32(in, OFS_CRC))
        return MAPGEN_IPC_DECODE_BAD_CRC;

    out->magic = magic;
    out->version = version;
    out->type = type;
    out->payload_len = payload_len;
    out->sequence = get_u32(in + OFS_SEQUENCE);
    memcpy(out->job_uuid, in + OFS_UUID, MAPGEN_IPC_UUID_BYTES);
    out->header_crc32 = crc;
    return MAPGEN_IPC_DECODE_OK;
}

/* ------------------------------------------------------------------------ */

void MapGenIpc_StreamInit(mapgen_ipc_stream_t *stream)
{
    if (!stream)
        return;
    memset(stream, 0, sizeof(*stream));
}

bool MapGenIpc_StreamAccept(mapgen_ipc_stream_t *stream,
                            const mapgen_ipc_header_t *header)
{
    if (!stream || !header)
        return false;

    /* A degraded transport LATCHES. Re-accepting frames after a violation is
       how a desynchronised stream quietly becomes a trusted one again. */
    if (stream->failed)
        return false;

    if (header->sequence != stream->expect_sequence) {
        stream->failed = true;
        return false;
    }

    if (!stream->job_bound) {
        memcpy(stream->job_uuid, header->job_uuid, MAPGEN_IPC_UUID_BYTES);
        stream->job_bound = true;
    } else if (memcmp(stream->job_uuid, header->job_uuid,
                      MAPGEN_IPC_UUID_BYTES) != 0) {
        stream->failed = true;
        return false;
    }

    stream->expect_sequence++;
    return true;
}

/* ------------------------------------------------------------------------ */

const char *MapGenIpc_TypeName(uint16_t type)
{
    switch (type) {
    case MAPGEN_IPC_HELLO:          return "HELLO";
    case MAPGEN_IPC_READY:          return "READY";
    case MAPGEN_IPC_PROGRESS:       return "PROGRESS";
    case MAPGEN_IPC_LOG_SUMMARY:    return "LOG_SUMMARY";
    case MAPGEN_IPC_CANCELLED:      return "CANCELLED";
    case MAPGEN_IPC_STAGED_RESULT:  return "STAGED_RESULT";
    case MAPGEN_IPC_ERROR:          return "ERROR";
    case MAPGEN_IPC_BYE:            return "BYE";
    case MAPGEN_IPC_START_TRAIN:    return "START_TRAIN";
    case MAPGEN_IPC_START_GENERATE: return "START_GENERATE";
    case MAPGEN_IPC_START_VALIDATE: return "START_VALIDATE";
    case MAPGEN_IPC_CANCEL:         return "CANCEL";
    case MAPGEN_IPC_SHUTDOWN:       return "SHUTDOWN";
    default:                        return "UNKNOWN";
    }
}

const char *MapGenIpc_DecodeName(mapgen_ipc_decode_t result)
{
    switch (result) {
    case MAPGEN_IPC_DECODE_OK:                 return "OK";
    case MAPGEN_IPC_DECODE_INCOMPLETE:         return "INCOMPLETE";
    case MAPGEN_IPC_DECODE_BAD_MAGIC:          return "BAD_MAGIC";
    case MAPGEN_IPC_DECODE_BAD_VERSION:        return "BAD_VERSION";
    case MAPGEN_IPC_DECODE_BAD_TYPE:           return "BAD_TYPE";
    case MAPGEN_IPC_DECODE_PAYLOAD_TOO_LARGE:  return "PAYLOAD_TOO_LARGE";
    case MAPGEN_IPC_DECODE_BAD_CRC:            return "BAD_CRC";
    case MAPGEN_IPC_DECODE_BAD_ARGUMENT:       return "BAD_ARGUMENT";
    default:                                   return "UNKNOWN";
    }
}

bool MapGenIpc_IsWorkerToController(uint16_t type)
{
    switch (type) {
    case MAPGEN_IPC_HELLO:
    case MAPGEN_IPC_READY:
    case MAPGEN_IPC_PROGRESS:
    case MAPGEN_IPC_LOG_SUMMARY:
    case MAPGEN_IPC_CANCELLED:
    case MAPGEN_IPC_STAGED_RESULT:
    case MAPGEN_IPC_ERROR:
    case MAPGEN_IPC_BYE:
        return true;
    default:
        return false;
    }
}

bool MapGenIpc_IsControllerToWorker(uint16_t type)
{
    switch (type) {
    case MAPGEN_IPC_START_TRAIN:
    case MAPGEN_IPC_START_GENERATE:
    case MAPGEN_IPC_START_VALIDATE:
    case MAPGEN_IPC_CANCEL:
    case MAPGEN_IPC_SHUTDOWN:
        return true;
    default:
        return false;
    }
}
