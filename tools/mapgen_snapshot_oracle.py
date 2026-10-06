#!/usr/bin/env python3
"""Independent reader and writer for the `.q2mgdb` container.

Written from the layout in `inc/common/mapgen_snapshot.h`, and it does two jobs
the C cannot do for itself:

  * it AGREES - a file the C wrote must parse here to the same header fields
    and the same payload hash, and a file this wrote must open in the C;

  * it LIES - it can produce a file with exactly one field corrupted, which is
    the only way to find out whether each refusal in the reader is reachable.
    A hostile-input test that cannot construct hostile input is a test of
    nothing.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass, field

MAGIC = b"Q2MGDB\0\0"
SCHEMA_MAJOR = 3
SCHEMA_MINOR = 0
HEADER_BYTES = 220
ENTRY_BYTES = 40

OFF_MAGIC = 0
OFF_SCHEMA_MAJOR = 8
OFF_SCHEMA_MINOR = 10
OFF_HEADER_BYTES = 12
OFF_FILE_BYTES = 16
OFF_FLAGS = 24
OFF_HEADER_CRC = 28
OFF_TABLE_OFFSET = 32
OFF_ENTRY_BYTES = 40
OFF_LINEAGE = 44
OFF_REVISION = 60
OFF_PARENT_HASH = 76
OFF_RECIPE_HASH = 108
OFF_CREATED_MS = 140
OFF_SOURCE_COUNT = 148
OFF_CHUNK_COUNT = 152
OFF_PHYSICS_HASH = 156
OFF_PAYLOAD_HASH = 188

ENT_TYPE = 0
ENT_FLAGS = 4
ENT_OFFSET = 8
ENT_STORED = 16
ENT_PLAIN = 24
ENT_CRC = 32
ENT_RESERVED = 36

FLAG_REQUIRED = 0x1
COMPRESSION_SHIFT = 8
COMPRESSION_MASK = 0x0000FF00

COMPRESSION_NONE = 0
COMPRESSION_DEFLATE = 1

CHUNK_META, CHUNK_SOURCES, CHUNK_MATERIALS = 1, 2, 3
CHUNK_REGIONS, CHUNK_ENTITIES, CHUNK_STATS, CHUNK_QUALITY = 4, 5, 6, 7
# Schema 2 added the shapes; schema 3 added the geometry those shapes describe.
CHUNK_SHAPES, CHUNK_GEOMETRY = 8, 9
REQUIRED_TYPES = (CHUNK_META, CHUNK_SOURCES, CHUNK_MATERIALS, CHUNK_REGIONS,
                  CHUNK_ENTITIES, CHUNK_STATS, CHUNK_QUALITY, CHUNK_SHAPES,
                  CHUNK_GEOMETRY)

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_CHUNKS = 64
MAX_CHUNK_BYTES = 64 * 1024 * 1024
MAX_SOURCES = 100000
MAX_RATIO = 1024


class SnapshotError(Exception):
    """Carries the same code name the C reader would print."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Chunk:
    type: int
    data: bytes
    compression: int = COMPRESSION_NONE


@dataclass
class Snapshot:
    schema_major: int = SCHEMA_MAJOR
    schema_minor: int = SCHEMA_MINOR
    flags: int = 0
    lineage_uuid: bytes = b"\0" * 16
    revision_uuid: bytes = b"\0" * 16
    parent_payload_sha256: bytes = b"\0" * 32
    training_recipe_hash: bytes = b"\0" * 32
    physics_schema_hash: bytes = b"\0" * 32
    created_utc_ms: int = 0
    source_count: int = 0
    payload_sha256: bytes = b"\0" * 32
    file_bytes: int = 0
    chunks: list[Chunk] = field(default_factory=list)

    def chunk(self, type_: int) -> bytes | None:
        for c in self.chunks:
            if c.type == type_:
                return c.data
        return None


def header_crc(header: bytes, table: bytes = b"") -> int:
    """The header's CRC, with its own field taken as zero, over the header
    AND the chunk table.

    The table was the one region no integrity check covered: chunk CRCs
    cover chunk bytes, this covered the header, and the payload hash does
    not see the table at all. A single flipped bit in an entry's flags was
    accepted by both readers until this was extended.
    """
    assert len(header) == HEADER_BYTES
    blanked = header[:OFF_HEADER_CRC] + b"\0\0\0\0" + header[OFF_HEADER_CRC + 4:]
    return zlib.crc32(blanked + table) & 0xFFFFFFFF


def payload_hash(chunks: list[Chunk]) -> bytes:
    """Chunk-type order, uncompressed bytes, and nothing about how or where
    they were stored."""
    h = hashlib.sha256()
    h.update(struct.pack("<I", len(chunks)))
    for c in sorted(chunks, key=lambda c: c.type):
        h.update(struct.pack("<I", c.type))
        h.update(struct.pack("<Q", len(c.data)))
        h.update(c.data)
    return h.digest()


def build(snap: Snapshot) -> bytes:
    """Serialize, laying chunks out in the order given and the table last."""
    stored: list[bytes] = []
    for c in snap.chunks:
        if c.compression == COMPRESSION_DEFLATE:
            stored.append(zlib.compress(c.data, 9))
        else:
            stored.append(c.data)

    body = b"".join(stored)
    table_offset = HEADER_BYTES + len(body)
    total = table_offset + len(snap.chunks) * ENTRY_BYTES

    table = bytearray()
    cursor = HEADER_BYTES
    for c, blob in zip(snap.chunks, stored):
        entry = bytearray(ENTRY_BYTES)
        struct.pack_into("<I", entry, ENT_TYPE, c.type)
        flags = (FLAG_REQUIRED if c.type in REQUIRED_TYPES else 0)
        flags |= (c.compression << COMPRESSION_SHIFT)
        struct.pack_into("<I", entry, ENT_FLAGS, flags)
        struct.pack_into("<Q", entry, ENT_OFFSET, cursor)
        struct.pack_into("<Q", entry, ENT_STORED, len(blob))
        struct.pack_into("<Q", entry, ENT_PLAIN, len(c.data))
        struct.pack_into("<I", entry, ENT_CRC, zlib.crc32(blob) & 0xFFFFFFFF)
        struct.pack_into("<I", entry, ENT_RESERVED, 0)
        table += entry
        cursor += len(blob)

    header = bytearray(HEADER_BYTES)
    header[OFF_MAGIC:OFF_MAGIC + 8] = MAGIC
    struct.pack_into("<H", header, OFF_SCHEMA_MAJOR, snap.schema_major)
    struct.pack_into("<H", header, OFF_SCHEMA_MINOR, snap.schema_minor)
    struct.pack_into("<I", header, OFF_HEADER_BYTES, HEADER_BYTES)
    struct.pack_into("<Q", header, OFF_FILE_BYTES, total)
    struct.pack_into("<I", header, OFF_FLAGS, snap.flags)
    struct.pack_into("<Q", header, OFF_TABLE_OFFSET, table_offset)
    struct.pack_into("<I", header, OFF_ENTRY_BYTES, ENTRY_BYTES)
    header[OFF_LINEAGE:OFF_LINEAGE + 16] = snap.lineage_uuid
    header[OFF_REVISION:OFF_REVISION + 16] = snap.revision_uuid
    header[OFF_PARENT_HASH:OFF_PARENT_HASH + 32] = snap.parent_payload_sha256
    header[OFF_RECIPE_HASH:OFF_RECIPE_HASH + 32] = snap.training_recipe_hash
    struct.pack_into("<Q", header, OFF_CREATED_MS, snap.created_utc_ms)
    struct.pack_into("<I", header, OFF_SOURCE_COUNT, snap.source_count)
    struct.pack_into("<I", header, OFF_CHUNK_COUNT, len(snap.chunks))
    header[OFF_PHYSICS_HASH:OFF_PHYSICS_HASH + 32] = snap.physics_schema_hash
    header[OFF_PAYLOAD_HASH:OFF_PAYLOAD_HASH + 32] = payload_hash(snap.chunks)
    struct.pack_into("<I", header, OFF_HEADER_CRC,
                     header_crc(bytes(header), bytes(table)))

    return bytes(header) + body + bytes(table)


def parse(image: bytes) -> Snapshot:
    """Validate in the same order the C does, raising the same code names."""
    if len(image) < HEADER_BYTES:
        raise SnapshotError("ERR_TOO_SMALL")
    if len(image) > MAX_FILE_BYTES:
        raise SnapshotError("ERR_FILE_TOO_LARGE")
    if image[OFF_MAGIC:OFF_MAGIC + 8] != MAGIC:
        raise SnapshotError("ERR_BAD_MAGIC")

    major = struct.unpack_from("<H", image, OFF_SCHEMA_MAJOR)[0]
    if major != SCHEMA_MAJOR:
        raise SnapshotError("ERR_UNSUPPORTED_MAJOR")
    if struct.unpack_from("<I", image, OFF_HEADER_BYTES)[0] != HEADER_BYTES:
        raise SnapshotError("ERR_BAD_HEADER_BYTES")
    if struct.unpack_from("<Q", image, OFF_FILE_BYTES)[0] != len(image):
        raise SnapshotError("ERR_BAD_FILE_BYTES")
    if struct.unpack_from("<I", image, OFF_ENTRY_BYTES)[0] != ENTRY_BYTES:
        raise SnapshotError("ERR_BAD_ENTRY_BYTES")

    chunk_count = struct.unpack_from("<I", image, OFF_CHUNK_COUNT)[0]
    if chunk_count > MAX_CHUNKS:
        raise SnapshotError("ERR_TOO_MANY_CHUNKS")
    source_count = struct.unpack_from("<I", image, OFF_SOURCE_COUNT)[0]
    if source_count > MAX_SOURCES:
        raise SnapshotError("ERR_TOO_MANY_SOURCES")

    table_offset = struct.unpack_from("<Q", image, OFF_TABLE_OFFSET)[0]
    table_bytes = chunk_count * ENTRY_BYTES
    if (table_offset < HEADER_BYTES or table_offset > len(image)
            or table_bytes > len(image) - table_offset):
        raise SnapshotError("ERR_TABLE_OUT_OF_BOUNDS")

    # Only now, with the table known to lie inside the buffer, can the CRC
    # that covers it be computed at all.
    if (header_crc(image[:HEADER_BYTES],
                   image[table_offset:table_offset + table_bytes])
            != struct.unpack_from("<I", image, OFF_HEADER_CRC)[0]):
        raise SnapshotError("ERR_BAD_HEADER_CRC")

    entries = []
    for i in range(chunk_count):
        base = table_offset + i * ENTRY_BYTES
        e = {
            "type": struct.unpack_from("<I", image, base + ENT_TYPE)[0],
            "flags": struct.unpack_from("<I", image, base + ENT_FLAGS)[0],
            "offset": struct.unpack_from("<Q", image, base + ENT_OFFSET)[0],
            "stored": struct.unpack_from("<Q", image, base + ENT_STORED)[0],
            "plain": struct.unpack_from("<Q", image, base + ENT_PLAIN)[0],
            "crc": struct.unpack_from("<I", image, base + ENT_CRC)[0],
            "reserved": struct.unpack_from("<I", image, base + ENT_RESERVED)[0],
        }
        if e["reserved"] != 0:
            raise SnapshotError("ERR_RESERVED_NOT_ZERO")
        if (e["offset"] < HEADER_BYTES or e["offset"] > len(image)
                or e["stored"] > len(image) - e["offset"]):
            raise SnapshotError("ERR_CHUNK_OUT_OF_BOUNDS")
        if e["plain"] > MAX_CHUNK_BYTES or e["stored"] > MAX_CHUNK_BYTES:
            raise SnapshotError("ERR_CHUNK_TOO_LARGE")

        method = (e["flags"] & COMPRESSION_MASK) >> COMPRESSION_SHIFT
        if method not in (COMPRESSION_NONE, COMPRESSION_DEFLATE):
            raise SnapshotError("ERR_BAD_COMPRESSION")
        if method == COMPRESSION_NONE and e["plain"] != e["stored"]:
            raise SnapshotError("ERR_BAD_COMPRESSION")
        if e["stored"] and e["plain"] // e["stored"] > MAX_RATIO:
            raise SnapshotError("ERR_RATIO_TOO_HIGH")
        if not e["stored"] and e["plain"]:
            raise SnapshotError("ERR_RATIO_TOO_HIGH")

        for other in entries:
            if other["type"] == e["type"]:
                raise SnapshotError("ERR_DUPLICATE_CHUNK")
            if (e["offset"] < other["offset"] + other["stored"]
                    and other["offset"] < e["offset"] + e["stored"]):
                raise SnapshotError("ERR_CHUNK_OVERLAP")
        if (e["offset"] < table_offset + table_bytes
                and table_offset < e["offset"] + e["stored"]):
            raise SnapshotError("ERR_CHUNK_OVERLAP")
        entries.append(e)

    present = {e["type"] for e in entries}
    for e in entries:
        if e["type"] not in REQUIRED_TYPES and (e["flags"] & FLAG_REQUIRED):
            raise SnapshotError("ERR_UNKNOWN_REQUIRED_CHUNK")
    for t in REQUIRED_TYPES:
        if t not in present:
            raise SnapshotError("ERR_MISSING_CHUNK")

    chunks: list[Chunk] = []
    for e in entries:
        blob = image[e["offset"]:e["offset"] + e["stored"]]
        if (zlib.crc32(blob) & 0xFFFFFFFF) != e["crc"]:
            raise SnapshotError("ERR_BAD_CHUNK_CRC")
        method = (e["flags"] & COMPRESSION_MASK) >> COMPRESSION_SHIFT
        if method == COMPRESSION_NONE:
            data = blob
        else:
            try:
                data = zlib.decompress(blob)
            except zlib.error:
                raise SnapshotError("ERR_DECOMPRESS_FAILED") from None
            if len(data) != e["plain"]:
                raise SnapshotError("ERR_DECOMPRESS_FAILED")
        chunks.append(Chunk(e["type"], data, method))

    declared = image[OFF_PAYLOAD_HASH:OFF_PAYLOAD_HASH + 32]
    if payload_hash(chunks) != declared:
        raise SnapshotError("ERR_BAD_PAYLOAD_HASH")

    return Snapshot(
        schema_major=major,
        schema_minor=struct.unpack_from("<H", image, OFF_SCHEMA_MINOR)[0],
        flags=struct.unpack_from("<I", image, OFF_FLAGS)[0],
        lineage_uuid=image[OFF_LINEAGE:OFF_LINEAGE + 16],
        revision_uuid=image[OFF_REVISION:OFF_REVISION + 16],
        parent_payload_sha256=image[OFF_PARENT_HASH:OFF_PARENT_HASH + 32],
        training_recipe_hash=image[OFF_RECIPE_HASH:OFF_RECIPE_HASH + 32],
        physics_schema_hash=image[OFF_PHYSICS_HASH:OFF_PHYSICS_HASH + 32],
        created_utc_ms=struct.unpack_from("<Q", image, OFF_CREATED_MS)[0],
        source_count=source_count,
        payload_sha256=declared,
        file_bytes=len(image),
        chunks=chunks,
    )


# --- building the files a reader has to refuse -----------------------------

BODIES = {
    CHUNK_META: b"title=Reference Snapshot\nslug=reference_snapshot\n",
    CHUNK_SOURCES: b"count=1\naerowalk.bsp\n",
    CHUNK_MATERIALS: b"e1u1/floor3_3 roles=floor\n",
    CHUNK_REGIONS: b"regions=63\n",
    CHUNK_ENTITIES: b"spawn_dm=9\n",
    CHUNK_STATS: b"cover_permille=863\n",
    CHUNK_QUALITY: b"sources=1\n",
    CHUNK_SHAPES: b"max_volumes=1024\nbasis=16\n",
    CHUNK_GEOMETRY: b"max_donors=256\nmax_brushes=262144\n",
}


def reference_snapshot(compression: int = COMPRESSION_NONE) -> Snapshot:
    return Snapshot(
        lineage_uuid=bytes(range(0x10, 0x20)),
        revision_uuid=bytes(range(0x20, 0x30)),
        parent_payload_sha256=bytes(range(32)),
        training_recipe_hash=bytes(range(0x40, 0x60)),
        physics_schema_hash=bytes(range(0x80, 0xA0)),
        created_utc_ms=1756600000000,
        source_count=1,
        chunks=[Chunk(t, BODIES[t] * 40, compression) for t in REQUIRED_TYPES],
    )


def _repair_crc(out: bytearray) -> None:
    table_offset = struct.unpack_from("<Q", out, OFF_TABLE_OFFSET)[0]
    count = struct.unpack_from("<I", out, OFF_CHUNK_COUNT)[0]
    table = bytes(out[table_offset:table_offset + count * ENTRY_BYTES])
    struct.pack_into("<I", out, OFF_HEADER_CRC,
                     header_crc(bytes(out[:HEADER_BYTES]), table))


def _patch(image: bytes, offset: int, blob: bytes, fix_crc: bool = True) -> bytes:
    """Corrupt one field, then repair the header CRC unless the CRC is the
    point of the case - otherwise every corruption would be caught by it
    first and prove nothing about the check it was aimed at.

    That CRC now covers the chunk table too, so a table edit needs repairing
    as well; only `table_flags_bit_flipped` deliberately leaves it broken.
    """
    out = bytearray(image)
    out[offset:offset + len(blob)] = blob
    if fix_crc:
        _repair_crc(out)
    return bytes(out)


def corrupt(name: str) -> bytes:
    """One file per refusal the reader claims to have.

    Header edits repair the header CRC afterwards, otherwise every one of them
    would be caught by the CRC first and prove nothing about the check it was
    aimed at.
    """
    good = build(reference_snapshot())
    table_offset = struct.unpack_from("<Q", good, OFF_TABLE_OFFSET)[0]

    if name == "truncated":
        return good[:HEADER_BYTES - 1]
    if name == "bad_magic":
        return _patch(good, OFF_MAGIC, b"Q2MGDC\0\0")
    if name == "unsupported_major":
        return _patch(good, OFF_SCHEMA_MAJOR, struct.pack("<H", 99))
    if name == "bad_header_bytes":
        return _patch(good, OFF_HEADER_BYTES, struct.pack("<I", 219))
    if name == "bad_header_crc":
        return _patch(good, OFF_HEADER_CRC, struct.pack("<I", 0xDEADBEEF), fix_crc=False)
    if name == "bad_file_bytes":
        return _patch(good, OFF_FILE_BYTES, struct.pack("<Q", len(good) + 1))
    if name == "bad_entry_bytes":
        return _patch(good, OFF_ENTRY_BYTES, struct.pack("<I", 41))
    if name == "too_many_chunks":
        return _patch(good, OFF_CHUNK_COUNT, struct.pack("<I", MAX_CHUNKS + 1))
    if name == "too_many_sources":
        return _patch(good, OFF_SOURCE_COUNT, struct.pack("<I", MAX_SOURCES + 1))
    if name == "table_past_eof":
        return _patch(good, OFF_TABLE_OFFSET, struct.pack("<Q", len(good) + 8))
    if name == "table_inside_header":
        return _patch(good, OFF_TABLE_OFFSET, struct.pack("<Q", 8))
    if name == "chunk_past_eof":
        return _patch(good, table_offset + ENT_OFFSET, struct.pack("<Q", len(good) - 2))
    if name == "chunk_overlap":
        second = table_offset + ENTRY_BYTES + ENT_OFFSET
        first = struct.unpack_from("<Q", good, table_offset + ENT_OFFSET)[0]
        return _patch(good, second, struct.pack("<Q", first))
    if name == "duplicate_chunk":
        return _patch(good, table_offset + ENTRY_BYTES + ENT_TYPE,
                      struct.pack("<I", CHUNK_META))
    if name == "missing_chunk":
        snap = reference_snapshot()
        snap.chunks = [c for c in snap.chunks if c.type != CHUNK_QUALITY]
        return build(snap)
    if name == "unknown_required_chunk":
        snap = reference_snapshot()
        snap.chunks.append(Chunk(9999, b"optional"))
        image = bytearray(build(snap))
        # The APPENDED chunk, wherever the required set ends - hard-coding
        # index seven marked SHAPES required once schema 3 arrived, and a
        # corruption that corrupts a legitimate chunk tests nothing.
        base = (struct.unpack_from("<Q", image, OFF_TABLE_OFFSET)[0]
                + len(REQUIRED_TYPES) * ENTRY_BYTES)
        struct.pack_into("<I", image, base + ENT_FLAGS, FLAG_REQUIRED)
        _repair_crc(image)
        return bytes(image)
    if name == "bad_compression":
        return _patch(good, table_offset + ENT_FLAGS,
                      struct.pack("<I", FLAG_REQUIRED | (7 << COMPRESSION_SHIFT)))
    if name == "store_size_mismatch":
        return _patch(good, table_offset + ENT_PLAIN, struct.pack("<Q", 4))
    if name == "ratio_too_high":
        image = bytearray(good)
        base = table_offset
        struct.pack_into("<I", image, base + ENT_FLAGS,
                         FLAG_REQUIRED | (COMPRESSION_DEFLATE << COMPRESSION_SHIFT))
        struct.pack_into("<Q", image, base + ENT_PLAIN, MAX_RATIO * 4096)
        struct.pack_into("<Q", image, base + ENT_STORED, 8)
        # The chunk CRC is made correct for the eight bytes now claimed,
        # so the ratio is the ONLY thing wrong with this file. Otherwise
        # the case would pass on a CRC failure and prove nothing about
        # the ratio ceiling.
        offset = struct.unpack_from("<Q", image, base + ENT_OFFSET)[0]
        blob = bytes(image[offset:offset + 8])
        struct.pack_into("<I", image, base + ENT_CRC, zlib.crc32(blob) & 0xFFFFFFFF)
        _repair_crc(image)
        return bytes(image)
    if name == "chunk_overlaps_table":
        # A chunk that sits on top of the chunk table. No other case
        # reaches that check: `chunk_overlap` only overlaps two chunks.
        image = bytearray(good)
        struct.pack_into("<Q", image, table_offset + ENT_OFFSET,
                         table_offset + 8)
        struct.pack_into("<Q", image, table_offset + ENT_STORED, 16)
        struct.pack_into("<Q", image, table_offset + ENT_PLAIN, 16)
        blob = bytes(image[table_offset + 8:table_offset + 24])
        struct.pack_into("<I", image, table_offset + ENT_CRC,
                         zlib.crc32(blob) & 0xFFFFFFFF)
        _repair_crc(image)
        return bytes(image)
    if name == "bad_chunk_crc":
        return _patch(good, table_offset + ENT_CRC, struct.pack("<I", 0x12345678))
    if name == "decompress_failed":
        snap = reference_snapshot(COMPRESSION_DEFLATE)
        image = bytearray(build(snap))
        offset = struct.unpack_from("<Q", image, struct.unpack_from(
            "<Q", image, OFF_TABLE_OFFSET)[0] + ENT_OFFSET)[0]
        image[offset + 2] ^= 0xFF
        base = struct.unpack_from("<Q", image, OFF_TABLE_OFFSET)[0]
        stored = struct.unpack_from("<Q", image, base + ENT_STORED)[0]
        blob = bytes(image[offset:offset + stored])
        struct.pack_into("<I", image, base + ENT_CRC, zlib.crc32(blob) & 0xFFFFFFFF)
        _repair_crc(image)
        return bytes(image)
    if name == "bad_payload_hash":
        return _patch(good, OFF_PAYLOAD_HASH, b"\xff" * 32)
    if name == "reserved_not_zero":
        return _patch(good, table_offset + ENT_RESERVED, struct.pack("<I", 1))
    if name == "table_flags_bit_flipped":
        # The case the fuzz run earned: a spare bit in an entry's flags,
        # which nothing validated and the payload hash never saw.
        # Deliberately NOT CRC-repaired - being caught by that CRC is the
        # whole point of the case.
        flags = struct.unpack_from("<I", good, table_offset + ENT_FLAGS)[0]
        return _patch(good, table_offset + ENT_FLAGS,
                      struct.pack("<I", flags | 0x80000000), fix_crc=False)

    raise KeyError(name)


CORRUPTIONS = {
    "truncated": "ERR_TOO_SMALL",
    "bad_magic": "ERR_BAD_MAGIC",
    "unsupported_major": "ERR_UNSUPPORTED_MAJOR",
    "bad_header_bytes": "ERR_BAD_HEADER_BYTES",
    "bad_header_crc": "ERR_BAD_HEADER_CRC",
    "bad_file_bytes": "ERR_BAD_FILE_BYTES",
    "bad_entry_bytes": "ERR_BAD_ENTRY_BYTES",
    "too_many_chunks": "ERR_TOO_MANY_CHUNKS",
    "too_many_sources": "ERR_TOO_MANY_SOURCES",
    "table_past_eof": "ERR_TABLE_OUT_OF_BOUNDS",
    "table_inside_header": "ERR_TABLE_OUT_OF_BOUNDS",
    "chunk_past_eof": "ERR_CHUNK_OUT_OF_BOUNDS",
    "chunk_overlap": "ERR_CHUNK_OVERLAP",
    "duplicate_chunk": "ERR_DUPLICATE_CHUNK",
    "missing_chunk": "ERR_MISSING_CHUNK",
    "unknown_required_chunk": "ERR_UNKNOWN_REQUIRED_CHUNK",
    "bad_compression": "ERR_BAD_COMPRESSION",
    "store_size_mismatch": "ERR_BAD_COMPRESSION",
    "ratio_too_high": "ERR_RATIO_TOO_HIGH",
    "bad_chunk_crc": "ERR_BAD_CHUNK_CRC",
    "decompress_failed": "ERR_DECOMPRESS_FAILED",
    "bad_payload_hash": "ERR_BAD_PAYLOAD_HASH",
    "reserved_not_zero": "ERR_RESERVED_NOT_ZERO",
    "table_flags_bit_flipped": "ERR_BAD_HEADER_CRC",
    "chunk_overlaps_table": "ERR_CHUNK_OVERLAP",
}
