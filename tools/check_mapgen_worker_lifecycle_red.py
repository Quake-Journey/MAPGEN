#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_worker_lifecycle.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect and passed again after byte-exact restoration.

Every mutation removes one real protection from the worker host or the worker -
the job object's kill-on-close, the assign-before-resume ordering, the token,
the build id, the job uuid, the protocol latch, the sequence validation, the
direction check, the payload ceiling, the teardown kill, the cancellation
checkpoint - and each must go RED on its OWN named case.

Exit 0 = every mutation detected, everything restored byte-identically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mapgen_red_sandbox import Sandbox  # noqa: E402
from mapgen_red_support import resolve_anchor, sha256  # noqa: E402

# R1: every mutation happens in a disposable copy under the task's own
# temp root. The shared worktree is never opened for writing, so a killed
# process cannot leave a mutation behind - twice it did.
SANDBOX = Sandbox(REPO, Path(__file__).stem)

SUITE = SANDBOX.path("tools/check_mapgen_worker_lifecycle.py")
HOST = SANDBOX.path("src/windows/mapgen_process.c")
WORKER = SANDBOX.path("src/mapgen_worker/main.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # ---- containment -------------------------------------------------------
    (
        "job-does-not-kill-on-close",
        HOST,
        b"    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;\n",
        b"    limits.BasicLimitInformation.LimitFlags = 0;\n",
        "the job kills its contents when the host closes",
    ),
    (
        "child-inherits-every-handle",
        HOST,
        b"                             CREATE_NO_WINDOW | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT,\n",
        b"                             CREATE_NO_WINDOW | CREATE_SUSPENDED,\n",
        "inheritance is restricted to an explicit handle list",
    ),
    (
        "child-runs-before-it-is-contained",
        HOST,
        b"                             CREATE_NO_WINDOW | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT,\n",
        b"                             CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,\n",
        "the child is created suspended and assigned before it runs",
    ),
    (
        "close-does-not-kill-a-child-that-will-not-go",
        HOST,
        b"            TerminateJobObject(host->job, 1);\n",
        b"            (void)0;\n",
        "close terminates the job when the child will not go",
    ),
    # ---- identity ----------------------------------------------------------
    (
        "token-not-verified",
        HOST,
        b"    if (memcmp(hello, desc->token, MAPGEN_IPC_TOKEN_BYTES) != 0) {\n",
        b"    if (false) {\n",
        "a worker with the wrong token is refused",
    ),
    (
        "build-id-not-verified",
        HOST,
        b"    if (memcmp(hello + MAPGEN_IPC_TOKEN_BYTES, desc->expected_build_id,\n"
        b"               MAPGEN_PROCESS_BUILD_ID_BYTES) != 0) {\n",
        b"    if (false) {\n",
        "a worker from another build is refused",
    ),
    (
        "hello-uuid-not-verified",
        HOST,
        b"    if (memcmp(header.job_uuid, host->job_uuid, MAPGEN_IPC_UUID_BYTES) != 0) {\n",
        b"    if (false) {\n",
        "a worker that stamps its own job uuid is refused",
    ),
    (
        "handshake-accepts-any-frame-type",
        HOST,
        b"    if (header.type != MAPGEN_IPC_HELLO || !MapGenIpc_StreamAccept(&host->recv, &header)) {\n",
        b"    if (!MapGenIpc_StreamAccept(&host->recv, &header)) {\n",
        "a worker whose first frame is not HELLO is refused",
    ),
    # ---- transport ---------------------------------------------------------
    (
        "receive-does-not-validate-the-stream",
        HOST,
        b"    if (!MapGenIpc_StreamAccept(&host->recv, header)) {\n",
        b"    if (false) {\n",
        "a replayed sequence is refused",
    ),
    (
        "protocol-failure-does-not-latch",
        HOST,
        b"    if (host->protocol_failed)\n        return MAPGEN_PROC_ERR_PROTOCOL;\n",
        b"    if (false)\n        return MAPGEN_PROC_ERR_PROTOCOL;\n",
        "the refusal latches: the next receive is still refused",
    ),
    (
        "send-ignores-message-direction",
        HOST,
        b"    if (!MapGenIpc_IsControllerToWorker(type))\n        return MAPGEN_PROC_ERR_ARGUMENT;\n",
        b"    if (false)\n        return MAPGEN_PROC_ERR_ARGUMENT;\n",
        "sending a worker-to-controller type is refused",
    ),
    (
        "send-ignores-the-payload-ceiling",
        HOST,
        b"    if (payload_len > MAPGEN_IPC_MAX_PAYLOAD)\n        return MAPGEN_PROC_ERR_PAYLOAD_TOO_LARGE;\n",
        b"    if (false)\n        return MAPGEN_PROC_ERR_PAYLOAD_TOO_LARGE;\n",
        "an over-ceiling payload is refused before it is written",
    ),
    (
        "receive-ignores-the-callers-buffer-size",
        HOST,
        b"    if (!payload || header->payload_len > payload_capacity) {\n",
        b"    if (!payload) {\n",
        "the payload is bounded against the caller's buffer too",
    ),
    # ---- the worker --------------------------------------------------------
    (
        "worker-ignores-cancellation",
        WORKER,
        b"        /* Cancellation is observed HERE, at a checkpoint, and nowhere else. */\n"
        b"        if (w->cancelled) {\n",
        b"        /* Cancellation is observed HERE, at a checkpoint, and nowhere else. */\n"
        b"        if (false) {\n",
        "the worker answered CANCELLED",
    ),
    (
        "worker-leaves-its-pipes-in-text-mode",
        WORKER,
        b"    _setmode(_fileno(stdin), _O_BINARY);\n    _setmode(_fileno(stdout), _O_BINARY);\n",
        b"    (void)0;\n",
        "the worker sets its pipes to binary mode",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True, cwd=str(REPO), timeout=2400
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 worker lifecycle controlled RED")

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  baseline is not GREEN; refusing to mutate anything")
        print(out[-4000:])
        return 1
    print("  OK    baseline GREEN")

    failures = 0
    for name, path, anchor, replacement, expected_fail in CASES:
        original = path.read_bytes()
        original_hash = sha256(path)

        anchor, replacement, occurrences = resolve_anchor(original, anchor, replacement)
        if occurrences != 1:
            print(
                f"  FAIL  {name}: anchor occurs {occurrences} times in {path.name} "
                "(need exactly 1); the matrix is invalid, not skipped"
            )
            failures += 1
            continue

        mutated = original.replace(anchor, replacement, 1)
        if mutated == original:
            print(f"  FAIL  {name}: mutation did not change {path.name}")
            failures += 1
            continue

        try:
            path.write_bytes(mutated)
            if path.read_bytes() == original:
                print(f"  FAIL  {name}: mutation did not reach disk")
                failures += 1
                continue

            rc, out = run_suite()
            if rc == 0:
                print(f"  FAIL  {name}: suite stayed GREEN under the mutation")
                failures += 1
            elif f"FAIL  {expected_fail}" not in out:
                shown = [ln.strip() for ln in out.splitlines() if ln.startswith("  FAIL")][:4]
                print(f"  FAIL  {name}: went RED but not on '{expected_fail}'; got {shown}")
                failures += 1
            else:
                print(f"  RED   {name} -> {expected_fail}")
        finally:
            # From the pristine tree, not from a value this run computed.
            SANDBOX.restore(SANDBOX.relative(path))

        if sha256(path) != original_hash:
            print(f"  FAIL  {name}: {path.name} was not restored byte-identically")
            failures += 1

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  suite is not GREEN again after restoration")
        print(out[-4000:])
        failures += 1
    else:
        print("  OK    restored GREEN")

    print(f"\n=== {len(CASES)} controlled-RED cases, {failures} failures")
    if failures:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
