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
==============================================================================

MAPGEN-1 - Controller <-> worker frame protocol

This is a PRIVATE implementation detail behind MapGen_Submit / MapGen_Observe /
MapGen_Cancel.  No caller sees it.  It is process IPC over inherited pipes, not
game networking: no socket, no server, no wire-format change, nothing that
touches the Quake II protocol (contract sections 2.5, 2.6 and 24).

It deliberately does NOT reuse the game32 bridge's ABI protocol.  That bridge
marshals a game DLL interface; this carries job control.  Sharing its frames
would couple two lifecycles that have nothing in common.

--- What every frame carries, and why ---------------------------------------

    magic          desynchronisation is detected at the first bad byte rather
                   than by allocating whatever the next four bytes claim
    version        a worker built from a different commit is refused at HELLO
    type           the message kind
    payload_len    bounded BEFORE allocation, always
    sequence       per-direction and strictly monotonic
    job_uuid       which job this frame belongs to
    header_crc32   catches a truncated or interleaved write on the pipe

Hard Rule #46 is the reason `sequence` and `job_uuid` are in the header rather
than in the payloads that happen to need them.  A ring or stream indexed by a
counter must carry the key it belongs to and EVERY reader must validate it:
a frame that arrives out of order, or for a job that has already terminated,
must be rejected by the transport, not interpreted by whatever handler happens
to be listening.

--- What this protocol never does -------------------------------------------

`STAGED_RESULT` is not success.  The worker can only ever stage a result; the
Controller alone revalidates it, performs the durable commit and emits the one
external terminal event (contract section 5.1).  A terminal JobId never
resumes, so a frame naming a terminal job is dropped.

==============================================================================
*/

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* 'Q','2','M','G' little-endian. */
#define MAPGEN_IPC_MAGIC            0x474D3251u

/* Bumped whenever a frame layout or a type's payload meaning changes. The
   Controller refuses a worker that does not answer HELLO with this exact
   value; there is no negotiation and no backward compatibility, because both
   ends ship in the same package. */
#define MAPGEN_IPC_VERSION          1u

/* Fixed header size on the wire. Asserted in the implementation. */
#define MAPGEN_IPC_HEADER_BYTES     36

/* Hard ceiling checked BEFORE any allocation. Progress and log frames are
   small; a staged result is a set of paths and hashes, not a payload of
   content. Anything larger is a malformed or hostile frame. */
#define MAPGEN_IPC_MAX_PAYLOAD      (1u << 20)

/*
 * How much verdict a worker may stage.
 *
 * Here, because both ends need the same answer: the worker fills a buffer of
 * this size and the Controller must be able to receive one. It was written
 * down separately on each side and in the contract, and the receiver's copy -
 * 256 bytes - quietly refused every real verdict.
 */
#define MAPGEN_IPC_SUMMARY_MAX      2048u

/* Random per-launch capability token. The Controller generates it, passes it
   to the child out of band, and the child must echo it in HELLO. A process
   that cannot produce it is not our worker, whatever its PID or path says. */
#define MAPGEN_IPC_TOKEN_BYTES      32

#define MAPGEN_IPC_UUID_BYTES       16

typedef enum {
    /* worker -> controller */
    MAPGEN_IPC_HELLO = 1,          /* version + capability token + build id   */
    MAPGEN_IPC_READY = 2,          /* idle, awaiting work                     */
    MAPGEN_IPC_PROGRESS = 3,       /* stage, percent, current item            */
    MAPGEN_IPC_LOG_SUMMARY = 4,    /* bounded, sanitized, with total + hash   */
    MAPGEN_IPC_CANCELLED = 5,      /* cancellation observed and honoured      */
    MAPGEN_IPC_STAGED_RESULT = 6,  /* NEVER success - see the header comment  */
    MAPGEN_IPC_ERROR = 7,          /* stable code + bounded detail            */
    MAPGEN_IPC_BYE = 8,            /* clean shutdown acknowledged             */

    /* controller -> worker */
    MAPGEN_IPC_START_TRAIN = 9,
    MAPGEN_IPC_START_GENERATE = 10,
    MAPGEN_IPC_START_VALIDATE = 11,
    MAPGEN_IPC_CANCEL = 12,
    MAPGEN_IPC_SHUTDOWN = 13,

    MAPGEN_IPC_TYPE_COUNT
} mapgen_ipc_type_t;

typedef enum {
    MAPGEN_IPC_DECODE_OK = 0,
    /* fewer bytes than a header: not an error, ask for more */
    MAPGEN_IPC_DECODE_INCOMPLETE,
    MAPGEN_IPC_DECODE_BAD_MAGIC,
    MAPGEN_IPC_DECODE_BAD_VERSION,
    MAPGEN_IPC_DECODE_BAD_TYPE,
    MAPGEN_IPC_DECODE_PAYLOAD_TOO_LARGE,
    MAPGEN_IPC_DECODE_BAD_CRC,
    MAPGEN_IPC_DECODE_BAD_ARGUMENT,

    MAPGEN_IPC_DECODE_COUNT
} mapgen_ipc_decode_t;

typedef struct {
    uint32_t magic;
    uint16_t version;
    uint16_t type;
    uint32_t payload_len;
    uint32_t sequence;
    uint8_t  job_uuid[MAPGEN_IPC_UUID_BYTES];
    uint32_t header_crc32;
} mapgen_ipc_header_t;

/*
 * One end of a conversation. Both the Controller and the worker keep one of
 * these per direction and validate against it.
 *
 * `expect_sequence` is the identity check Hard Rule #46 demands: a frame whose
 * sequence is not exactly the next one is a desynchronised or replayed frame,
 * and it is rejected by the transport rather than handed to a handler that
 * would treat it as fresh.
 */
typedef struct {
    uint32_t expect_sequence;
    uint8_t  job_uuid[MAPGEN_IPC_UUID_BYTES];
    bool     job_bound;      /* false until the first frame binds the job    */
    bool     failed;         /* latches on the first violation               */
} mapgen_ipc_stream_t;

/* Encode `header` into `out`. Returns false on a bad argument or a payload
   over the ceiling; never writes past `out_bytes`. */
bool MapGenIpc_EncodeHeader(uint8_t *out, size_t out_bytes,
                            const mapgen_ipc_header_t *header);

/* Decode a header from `in`. Validates magic, version, type, payload ceiling
   and header CRC, in that order, before the caller may trust `payload_len`. */
mapgen_ipc_decode_t MapGenIpc_DecodeHeader(const uint8_t *in, size_t in_bytes,
                                           mapgen_ipc_header_t *out);

/* Initialise a stream for a job. */
void MapGenIpc_StreamInit(mapgen_ipc_stream_t *stream);

/*
 * Accept `header` on `stream`.
 *
 * Enforces, in order: the stream has not already failed; the sequence is
 * exactly the expected one; the job uuid matches the one this stream is bound
 * to (the first accepted frame binds it). Any violation LATCHES `failed` -
 * a degraded transport does not repair itself frame by frame, it is torn down
 * and the job is failed (Hard Rule #46, lifecycle).
 */
bool MapGenIpc_StreamAccept(mapgen_ipc_stream_t *stream,
                            const mapgen_ipc_header_t *header);

/* Stable identifier for logs and tests. Never NULL. */
const char *MapGenIpc_TypeName(uint16_t type);
const char *MapGenIpc_DecodeName(mapgen_ipc_decode_t result);

/* True for a type the worker may send, and for one the Controller may send.
   A frame arriving in the wrong direction is a protocol violation, not an
   unexpected message: it means the peer is not what it claims to be. */
bool MapGenIpc_IsWorkerToController(uint16_t type);
bool MapGenIpc_IsControllerToWorker(uint16_t type);

/* CRC-32 (IEEE) over `bytes`. Exposed so tests can build a valid header
   independently of the encoder they are testing. */
uint32_t MapGenIpc_Crc32(const uint8_t *bytes, size_t count);
