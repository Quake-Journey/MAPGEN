"""Move one entity of a compiled map, and write the map again around it.

The PO, 2026-09-14: a small defect in a delivered map is fixed in THAT map within
minutes, not by regenerating it for an hour (memory/feedback_po_fix_small_defects_fast.md).
The first such defect was a spawn point whose pad the generator had left over a
lift's shaft; moving an entity needs no compile - lighting, visibility and every
brush stay byte for byte what they were.

    python tools/mapgen_patch_entity.py SRC.bsp DST.bsp --class CLASSNAME --at "X Y Z" --to "X Y Z"

Exactly one entity of that class must stand at that origin, or nothing is
written. The entity lump is replaced and every lump is laid out again in index
order, four-byte aligned; the header's offsets follow. The copy is read back and
its entity text compared with what was meant before the command reports success.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

LUMPS = 19


def lumps_of(data: bytes) -> list[bytes]:
    return [data[o:o + n] for o, n in (struct.unpack_from("<ii", data, 8 + i * 8) for i in range(LUMPS))]


def rebuild(data: bytes, entities: bytes) -> bytes:
    blobs = lumps_of(data)
    blobs[0] = entities
    out = bytearray(data[:8] + bytes(LUMPS * 8))
    for i, blob in enumerate(blobs):
        while len(out) % 4:
            out += b"\0"
        struct.pack_into("<ii", out, 8 + i * 8, len(out), len(blob))
        out += blob
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--class", dest="classname", required=True)
    ap.add_argument("--at", required=True, help='the origin it has now, "X Y Z"')
    ap.add_argument("--to", required=True, help='the origin to give it, "X Y Z"')
    a = ap.parse_args()

    data = a.src.read_bytes()
    if data[:4] != b"IBSP" or struct.unpack_from("<i", data, 4)[0] != 38:
        print(f"{a.src}: not an IBSP version 38 map")
        return 2
    text = lumps_of(data)[0].rstrip(b"\0").decode("latin1")
    at = tuple(float(v) for v in a.at.split())
    to = tuple(float(v) for v in a.to.split())

    hits = []
    for m in re.finditer(r"\{[^}]*\}", text):
        block = m.group(0)
        c = re.search(r'"classname"\s+"([^"]*)"', block)
        o = re.search(r'"origin"\s+"([^"]*)"', block)
        if c and o and c.group(1) == a.classname \
                and tuple(float(v) for v in o.group(1).split()) == at:
            hits.append((m, o))
    if len(hits) != 1:
        print(f"{len(hits)} {a.classname} at {a.at}; nothing written")
        return 1
    m, o = hits[0]
    value = " ".join(f"{v:g}" for v in to)
    start = m.start() + o.start(1)
    patched = text[:start] + value + text[m.start() + o.end(1):]
    out = rebuild(data, patched.encode("latin1") + b"\0")
    a.dst.write_bytes(out)

    back = lumps_of(a.dst.read_bytes())[0].rstrip(b"\0").decode("latin1")
    if back != patched:
        print(f"{a.dst}: the entity text read back is not what was written")
        return 1
    if [b for i, b in enumerate(lumps_of(out)) if i] != [b for i, b in enumerate(lumps_of(data)) if i]:
        print(f"{a.dst}: a lump other than the entities changed")
        return 1
    print(f"{a.classname} moved from {a.at} to {value}; {a.dst} written, {len(out)} bytes,"
          f" every other lump identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
