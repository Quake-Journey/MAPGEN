#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_snapshot_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Three mutations carry the weight:

  * `the-table-is-not-covered-by-the-crc` reverts the fix the fuzz run earned -
    a flipped bit in a chunk entry's flags was accepted by both readers,
    because nothing validated the field and the payload hash never sees the
    table;
  * `the-payload-hash-sees-how-a-chunk-was-stored` makes the same learned
    content hash differently depending on the compressor, which contract 8
    forbids and which no static check could notice;
  * `crc32-uses-the-wrong-polynomial` proves the digests are checked against
    zlib and hashlib rather than against themselves.

A mutation may trip more than one case; what is being proven is that the NAMED
case detects it. Exit 0 = every mutation detected on its own case, every file
restored byte-identically.
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

SUITE = SANDBOX.path("tools/check_mapgen_snapshot_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_snapshot.c")
DIG = SANDBOX.path("src/mapgen/mapgen_digest.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- integrity ---------------------------------------------------------
    (
        "the-table-is-not-covered-by-the-crc",
        SRC,
        b"    state = MapGenDigest_Crc32Update(state, image + table_offset, (size_t)table_bytes);\n",
        b"    (void)table_offset; (void)table_bytes;\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "the-chunk-crc-is-not-checked",
        SRC,
        b"        if (MapGenDigest_Crc32(stored_bytes, (size_t)stored) != rd_u32(e + ENT_CRC)) {\n",
        b"        if (false && MapGenDigest_Crc32(stored_bytes, (size_t)stored) != rd_u32(e + ENT_CRC)) {\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "the-payload-hash-is-not-verified-on-open",
        SRC,
        b"    if (memcmp(computed, bytes + OFF_PAYLOAD_HASH, MAPGEN_SHA256_BYTES)) {\n",
        b"    if (false && memcmp(computed, bytes + OFF_PAYLOAD_HASH, MAPGEN_SHA256_BYTES)) {\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "the-magic-is-not-checked",
        SRC,
        b"    if (memcmp(bytes + OFF_MAGIC, MAPGEN_SNAPSHOT_MAGIC, MAPGEN_SNAPSHOT_MAGIC_BYTES))\n",
        b"    if (memcmp(bytes + OFF_MAGIC, MAPGEN_SNAPSHOT_MAGIC, 0))\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "the-declared-file-size-is-not-checked",
        SRC,
        b"    if (rd_u64(bytes + OFF_FILE_BYTES) != (uint64_t)size)\n",
        b"    if (rd_u64(bytes + OFF_FILE_BYTES) != rd_u64(bytes + OFF_FILE_BYTES))\n",
        "the file's own size is checked before anything is allocated",
    ),
    (
        "the-reserved-field-may-carry-anything",
        SRC,
        b"        if (rd_u32(e + ENT_RESERVED) != 0)\n",
        b"        if (false)\n",
        "all 25 corruptions produce their own result code",
    ),

    # --- the canonical payload hash ---------------------------------------
    (
        "the-payload-hash-sees-how-a-chunk-was-stored",
        SRC,
        b"        wr_u32(scratch, sorted[i].type);\n",
        b"        wr_u32(scratch, sorted[i].type + (uint32_t)sorted[i].compression);\n",
        "the payload hash does not depend on the compressor",
    ),
    (
        "chunks-are-hashed-in-the-order-the-file-happened-to-store-them",
        SRC,
        b"        qsort(sorted, count, sizeof(chunk_t), compare_chunks);\n",
        b"        (void)compare_chunks;\n",
        "the payload hash is over uncompressed bytes in type order",
    ),
    (
        "the-payload-hash-forgets-the-chunk-length",
        SRC,
        b"        wr_u64(scratch, (uint64_t)sorted[i].size);\n"
        b"        MapGenDigest_Sha256Update(&ctx, scratch, 8);\n",
        b"        wr_u64(scratch, 0);\n"
        b"        MapGenDigest_Sha256Update(&ctx, scratch, 8);\n",
        "the reference reads the C's store snapshot",
    ),

    # --- structural refusals ----------------------------------------------
    (
        "a-chunk-may-sit-on-top-of-the-table",
        SRC,
        b"        if (offset < table_offset + table_bytes && table_offset < offset + stored)\n"
        b"            return MAPGEN_SNAPSHOT_ERR_CHUNK_OVERLAP;\n",
        b"        if (false)\n"
        b"            return MAPGEN_SNAPSHOT_ERR_CHUNK_OVERLAP;\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "two-chunks-may-share-a-type",
        SRC,
        b"            if (rd_u32(o + ENT_TYPE) == type)\n"
        b"                return MAPGEN_SNAPSHOT_ERR_DUPLICATE_CHUNK;\n",
        b"            if (rd_u32(o + ENT_TYPE) == type + 1u)\n"
        b"                return MAPGEN_SNAPSHOT_ERR_DUPLICATE_CHUNK;\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "a-required-chunk-may-be-missing",
        SRC,
        b"    for (uint32_t t = MAPGEN_CHUNK_META; t <= MAPGEN_CHUNK_GEOMETRY; t++)\n"
        b"        if (!present[t])\n"
        b"            return MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK;\n",
        b"    for (uint32_t t = MAPGEN_CHUNK_META; t <= MAPGEN_CHUNK_GEOMETRY; t++)\n"
        b"        if (!present[t] && false)\n"
        b"            return MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK;\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "an-unknown-chunk-may-declare-itself-required",
        SRC,
        b"        else if (flags & MAPGEN_CHUNK_FLAG_REQUIRED)\n"
        b"            return MAPGEN_SNAPSHOT_ERR_UNKNOWN_REQUIRED_CHUNK;\n",
        b"        else if (flags & 0u)\n"
        b"            return MAPGEN_SNAPSHOT_ERR_UNKNOWN_REQUIRED_CHUNK;\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "a-stored-chunk-need-not-be-its-own-length",
        SRC,
        b"        if (method == MAPGEN_COMPRESSION_NONE && plain != stored)\n",
        b"        if (false)\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "a-decompression-bomb-is-allowed",
        SRC,
        b"        if (stored && plain / (stored ? stored : 1) > MAPGEN_SNAPSHOT_MAX_RATIO)\n",
        b"        if (stored && plain / (stored ? stored : 1) > 0xFFFFFFFFu)\n",
        "all 25 corruptions produce their own result code",
    ),
    (
        "the-writer-may-emit-what-the-reader-refuses",
        SRC,
        b"        /* Refuse to WRITE what the reader would refuse to read. */\n",
        b"        /* removed */\n",
        "the writer refuses to write what the reader would refuse to read",
    ),

    # --- the digests -------------------------------------------------------
    (
        "crc32-uses-the-wrong-polynomial",
        DIG,
        b"#define CRC32_POLY  0xEDB88320u\n",
        b"#define CRC32_POLY  0x82F63B78u\n",
        "CRC32 matches zlib on 400 random buffers",
    ),
    (
        "sha256-drops-the-message-length-padding",
        DIG,
        b"        length[i] = (unsigned char)((bits >> (56 - i * 8)) & 0xFFu);\n",
        b"        length[i] = (unsigned char)((bits >> (i * 8)) & 0xFFu);\n",
        "SHA-256 matches hashlib on 400 random buffers",
    ),
    (
        "the-incremental-sha-loses-a-partial-block",
        DIG,
        # Mutating the buffered prologue instead of the tail: the tail
        # owns `pending`, and breaking it used to make the padding loop
        # spin forever, which HUNG the suite rather than failing it. The
        # padding is arithmetic now, but a mutation that only corrupts a
        # digest is still the better instrument.
        b"        const size_t take = size < room ? size : room;\n",
        b"        const size_t take = size < room ? size : 0;\n",
        "the incremental SHA-256 matches the one-shot",
    ),
    (
        "the-crc-grows-a-lazily-built-table",
        DIG,
        b"uint32_t MapGenDigest_Crc32Init(void)\n{\n",
        b"static uint32_t g_crc32_table[256];\n\n"
        b"uint32_t MapGenDigest_Crc32Init(void)\n{\n"
        b"    g_crc32_table[0] = 0;\n",
        "the CRC has no lazily-built table",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=3600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 snapshot container controlled RED")

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
