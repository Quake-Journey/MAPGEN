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

MAPGEN-1 - worker process host

Owns the worker child: launch, authentication, framed conversation, cancellation
and reaping.  Private behind MapGen_Submit / MapGen_Observe / MapGen_Cancel;
no caller sees a handle, a PID or a pipe.

Contract section 24.  The rules this interface exists to make unavoidable:

  * the executable path is FIXED and absolute, and is verified before launch;
  * the child is authenticated by a random per-launch capability token, so a
    process that merely has the right PID or path is still not our worker;
  * the child lives in a Job Object with KILL_ON_JOB_CLOSE and breakaway
    forbidden, so closing the host cannot leave a worker - or a compiler the
    worker spawned - behind;
  * no shell is ever involved: no cmd.exe, no PowerShell, no string built from
    user input;
  * every frame is validated by the stream before its payload is read, and the
    payload length is bounded before anything is allocated.

Zero off-state cost (contract section 2.11): nothing in here runs, allocates,
opens a handle or starts a thread until a Map Generator operation launches a
worker.  There is no background process, no idle poller and no lazy singleton.

==============================================================================
*/

#pragma once

#include "common/mapgen_protocol.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MAPGEN_PROCESS_BUILD_ID_BYTES   32

/*
 * What a worker answers HELLO with, and what a Controller accepts.
 *
 * ONE definition, in the header both ends already include. The worker had its
 * own and the client was configured with the engine's version string, so every
 * handshake failed and every job died at submit with nothing to say why.
 *
 * It changes when the conversation changes, not when the engine's version
 * does: a Controller and a worker from the same build of this protocol
 * understand each other, and one from another build must not be trusted to.
 */
#define MAPGEN_WORKER_BUILD_ID          "q2prox-mapgen-worker-1"

typedef enum {
    MAPGEN_PROC_OK = 0,

    MAPGEN_PROC_ERR_ARGUMENT,
    MAPGEN_PROC_ERR_EXE_MISSING,
    MAPGEN_PROC_ERR_LAUNCH,
    MAPGEN_PROC_ERR_PIPE,
    MAPGEN_PROC_ERR_JOB_OBJECT,

    /* The child answered, but it is not our worker: no HELLO, the wrong
       protocol version, the wrong build id, or a token it could not have
       known. */
    MAPGEN_PROC_ERR_HANDSHAKE,

    MAPGEN_PROC_ERR_TIMEOUT,
    /* A frame the stream refused: bad magic/version/type/CRC, a sequence that
       is not the next one, or a job uuid that is not this stream's. */
    MAPGEN_PROC_ERR_PROTOCOL,
    MAPGEN_PROC_ERR_CHILD_GONE,
    MAPGEN_PROC_ERR_WRITE,
    MAPGEN_PROC_ERR_PAYLOAD_TOO_LARGE,

    MAPGEN_PROC_RESULT_COUNT
} mapgen_process_result_t;

typedef struct mapgen_process_s mapgen_process_t;

typedef struct {
    /* Absolute path to the packaged helper. Never searched for on PATH and
       never assembled from user input (contract section 4). */
    const char *exe_path;
    /* Working directory for the child; must exist. */
    const char *work_dir;
    /* Exactly MAPGEN_IPC_TOKEN_BYTES of caller-generated randomness. It is
       written to the child's stdin BEFORE any frame, so it never appears in a
       command line where another local process could read it. */
    const uint8_t *token;
    /* The uuid this conversation stamps on every frame in both directions,
       chosen by the HOST and handed to the child right after the token. The
       receive stream binds to it, so a frame carrying any other uuid - a
       delayed frame from a previous worker, say - is refused by the transport
       instead of being read as fresh. */
    const uint8_t *job_uuid;
    /* The build id this host will accept, zero-padded. A worker from another
       commit is refused rather than negotiated with. */
    char expected_build_id[MAPGEN_PROCESS_BUILD_ID_BYTES];
    /* How long the child has to answer HELLO. */
    uint32_t handshake_timeout_ms;
} mapgen_process_desc_t;

/*
 * Launch, authenticate and return a live host, or fail having left NOTHING
 * behind: no process, no handle, no job object.
 *
 * On success the child has already sent a valid HELLO carrying the exact token
 * and build id, and the receive stream is positioned on the frame after it.
 */
mapgen_process_result_t MapGenProcess_Launch(const mapgen_process_desc_t *desc,
                                             mapgen_process_t **out);

/* Send one frame. `payload` may be NULL when `payload_len` is 0. */
mapgen_process_result_t MapGenProcess_Send(mapgen_process_t *host,
                                           uint16_t type,
                                           const uint8_t *payload,
                                           uint32_t payload_len);

/*
 * Receive one frame, waiting at most `wait_ms`.
 *
 * Returns MAPGEN_PROC_ERR_TIMEOUT when nothing arrived - which is not a
 * failure of the host, only of this call. A frame the stream refuses is
 * MAPGEN_PROC_ERR_PROTOCOL and LATCHES: the conversation is over, because a
 * transport that has desynchronised once cannot be trusted to resynchronise.
 */
mapgen_process_result_t MapGenProcess_Receive(mapgen_process_t *host,
                                              uint32_t wait_ms,
                                              mapgen_ipc_header_t *header,
                                              uint8_t *payload,
                                              uint32_t payload_capacity,
                                              uint32_t *payload_len);

/* Ask the child to stop. Idempotent; safe after the child is already gone. */
mapgen_process_result_t MapGenProcess_RequestCancel(mapgen_process_t *host);

bool     MapGenProcess_IsAlive(mapgen_process_t *host);
uint32_t MapGenProcess_Pid(const mapgen_process_t *host);

/*
 * Wait for the child to exit on its own, at most `wait_ms`.
 * Returns true and fills `exit_code` when it has exited.
 */
bool MapGenProcess_WaitExit(mapgen_process_t *host, uint32_t wait_ms, int32_t *exit_code);

/*
 * Close the host. Terminates the whole job tree if anything is still alive,
 * closes every handle and frees the host. After this call no process the host
 * created - worker or compiler - is running.
 *
 * Cancellation or engine exit can never leave a child behind (contract
 * section 24), which is why this is the only teardown path and why it does the
 * killing itself rather than trusting a cooperative shutdown.
 */
void MapGenProcess_Close(mapgen_process_t *host);

const char *MapGenProcess_ResultName(mapgen_process_result_t result);
