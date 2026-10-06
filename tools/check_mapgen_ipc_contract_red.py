#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_ipc_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect and passed again after byte-exact restoration.

Every mutation here removes one real protection from the C codec - the payload
ceiling, the magic, the version, the type range, the header CRC, the sequence
check, the job-identity check, the degraded-state latch, the completeness check,
the direction split, the byte order - and each must go RED on its OWN named
case. A case that several protections can satisfy proves none of them.

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

SUITE = SANDBOX.path("tools/check_mapgen_ipc_contract.py")
CODEC = SANDBOX.path("src/mapgen/mapgen_ipc.c")
HEADER = SANDBOX.path("inc/common/mapgen_protocol.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    (
        "decoder-drops-the-payload-ceiling",
        CODEC,
        b"    if (payload_len > MAPGEN_IPC_MAX_PAYLOAD)\n        return MAPGEN_IPC_DECODE_PAYLOAD_TOO_LARGE;\n",
        b"    if (false)\n        return MAPGEN_IPC_DECODE_PAYLOAD_TOO_LARGE;\n",
        "a payload one byte over the ceiling is refused",
    ),
    (
        "ceiling-boundary-made-exclusive",
        CODEC,
        b"    if (payload_len > MAPGEN_IPC_MAX_PAYLOAD)\n",
        b"    if (payload_len >= MAPGEN_IPC_MAX_PAYLOAD)\n",
        "exactly the ceiling is accepted",
    ),
    (
        "encoder-emits-what-the-decoder-rejects",
        CODEC,
        b"    if (header->payload_len > MAPGEN_IPC_MAX_PAYLOAD)\n        return false;\n",
        b"    if (false)\n        return false;\n",
        "encoding an over-ceiling payload fails",
    ),
    (
        "magic-not-checked",
        CODEC,
        b"    if (magic != MAPGEN_IPC_MAGIC)\n",
        b"    if (false)\n",
        "a wrong magic is refused",
    ),
    (
        "version-not-checked",
        CODEC,
        b"    if (version != MAPGEN_IPC_VERSION)\n",
        b"    if (false)\n",
        "a wrong version is refused",
    ),
    (
        "type-range-not-checked",
        CODEC,
        b"    if (type == 0 || type >= MAPGEN_IPC_TYPE_COUNT)\n        return MAPGEN_IPC_DECODE_BAD_TYPE;\n",
        b"    if (false)\n        return MAPGEN_IPC_DECODE_BAD_TYPE;\n",
        "type 0 is refused",
    ),
    (
        "header-crc-not-checked",
        CODEC,
        b"    if (crc != MapGenIpc_Crc32(in, OFS_CRC))\n",
        b"    if (false)\n",
        "a corrupt header CRC is refused",
    ),
    (
        "short-frame-treated-as-a-frame",
        CODEC,
        b"    if (in_bytes < MAPGEN_IPC_HEADER_BYTES)\n        return MAPGEN_IPC_DECODE_INCOMPLETE;\n",
        # Keeps `in_bytes` used so -Wunused-parameter does not pre-empt the
        # detector under test: a mutation that fails the BUILD proves nothing
        # about the check it was meant to disable.
        b"    if (in_bytes == (size_t)-1)\n        return MAPGEN_IPC_DECODE_INCOMPLETE;\n",
        "a short frame asks for more rather than failing",
    ),
    (
        "sequence-not-validated",
        CODEC,
        b"    if (header->sequence != stream->expect_sequence) {\n",
        b"    if (false) {\n",
        "a repeated sequence is rejected",
    ),
    (
        "job-identity-not-validated",
        CODEC,
        b"    } else if (memcmp(stream->job_uuid, header->job_uuid,\n"
        b"                      MAPGEN_IPC_UUID_BYTES) != 0) {\n",
        b"    } else if (false) {\n",
        "a frame for a different job is rejected even with the right sequence",
    ),
    (
        "degraded-stream-repairs-itself",
        CODEC,
        b"    if (stream->failed)\n        return false;\n",
        b"    if (false)\n        return false;\n",
        "a correct frame after a violation is STILL rejected",
    ),
    (
        "a-type-belongs-to-both-directions",
        CODEC,
        b"    case MAPGEN_IPC_CANCEL:\n    case MAPGEN_IPC_SHUTDOWN:\n        return true;",
        b"    case MAPGEN_IPC_CANCEL:\n    case MAPGEN_IPC_SHUTDOWN:\n    case MAPGEN_IPC_BYE:\n        return true;",
        "every type belongs to exactly one direction",
    ),
    (
        "byte-order-flipped",
        CODEC,
        b"static uint32_t get_u32(const uint8_t *p)\n{\n    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |\n",
        b"static uint32_t get_u32(const uint8_t *p)\n{\n    return (uint32_t)p[3] | ((uint32_t)p[1] << 8) |\n",
        "a good frame decodes",
    ),
    (
        "ceiling-raised-in-the-header",
        HEADER,
        b"#define MAPGEN_IPC_MAX_PAYLOAD      (1u << 20)\n",
        b"#define MAPGEN_IPC_MAX_PAYLOAD      (1u << 24)\n",
        "payload ceiling agrees",
    ),
    (
        "version-bumped-without-the-harness",
        HEADER,
        b"#define MAPGEN_IPC_VERSION          1u\n",
        b"#define MAPGEN_IPC_VERSION          2u\n",
        "version agrees",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True, cwd=str(REPO), timeout=1800
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 IPC controlled RED")

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
