#!/usr/bin/env python3
"""MAPGEN-1 M3 - the `.q2mgdb` snapshot container, and its digests.

Contract section 8.

Five halves:

  * DIGEST - SHA-256 against the FIPS 180-4 published vectors and against
    Python's `hashlib` on hundreds of random buffers; CRC32 against the
    standard check value and against `zlib`. Neither rests on agreement with
    anything else in this repository;

  * STATIC - both modules hold no state, every count is checked against a
    ceiling BEFORE anything is allocated on a file's word, and the payload
    hash is computed over what was learned rather than over how it was stored;

  * ROUNDTRIP - the compiled C builds and reopens a snapshot in both
    compression modes, and the two produce the SAME payload hash;

  * HOSTILE - one file per refusal the reader claims to have, each corrupted in
    exactly one field, each asserted to produce that exact result code. A
    hostile-input test that cannot construct hostile input tests nothing;

  * CROSS - what the C writes, the reference reads, and the reverse.

Run: python tools/check_mapgen_snapshot_contract.py
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import mapgen_snapshot_oracle as oracle  # noqa: E402

HEADER = REPO / "inc" / "common" / "mapgen_snapshot.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_snapshot.c"
DIGEST_HEADER = REPO / "inc" / "common" / "mapgen_digest.h"
DIGEST_SOURCE = REPO / "src" / "mapgen" / "mapgen_digest.c"
DRIVER = REPO / "tools" / "mapgen_snapshot_test_driver.c"

# FIPS 180-4, appendix B. Published, not borrowed from this tree.
FIPS_VECTORS = [
    ("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    ("abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    ("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
     "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"),
]

CASES = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if condition:
        print(f"  PASS  {name}")
        return True
    print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    FAILED += 1
    return False


def head(text: str) -> None:
    print(f"\n=== {text}")


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


# --------------------------------------------------------------------------


import mapgen_build_target as build_target  # noqa: E402


def _build_lists() -> tuple[str, str]:
    """The client's sources and the MAPGEN helper's, separately.

    `meson.build` declares `mapgen_src` for the helper and lists the client's
    own sources elsewhere; a module that is in the first and not the second is
    exactly what "the PO's binary must be untouched" means now that MAPGEN has
    a target of its own.
    """
    text = (REPO / "meson.build").read_text(encoding="utf-8")
    match = re.search(r"^mapgen_src = \[(.*?)^\]", text, re.S | re.M)
    helper = match.group(1) if match else ""
    return text.replace(helper, ""), helper


def test_static() -> None:
    head("static: no state, and nothing believed before it is checked")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    dig = strip_c_comments(DIGEST_SOURCE.read_text(encoding="utf-8"))

    for name, text in (("container", src), ("digest", dig)):
        statics = [
            m.group(0).strip()
            for m in re.finditer(r"^static\s+[^;(){}]*;", text, re.MULTILINE)
            if "const" not in m.group(0)
        ]
        check(f"the {name} module holds no mutable file-scope state",
              not statics, f"{statics[:3]}")

    check(
        "the CRC has no lazily-built table",
        "crc32_table" not in dig and "_ready" not in dig,
        "a table filled on first use is shared mutable state; "
        "MapGenIpc_Crc32 has one and that is why this module does not use it",
    )

    # The ordering IS the promise: a file must not be able to make this reader
    # allocate on the strength of a number it supplied.
    open_fn = src[src.find("mapgen_snapshot_result_t MapGenSnapshot_Open"):]
    open_fn = open_fn[:open_fn.find("\nvoid MapGenSnapshot_Free")]
    first_alloc = open_fn.find("calloc(1, sizeof(*snap))")
    for label, needle in (
        ("the file's own size", "rd_u64(bytes + OFF_FILE_BYTES) != (uint64_t)size"),
        ("the chunk ceiling", "chunk_count > MAPGEN_SNAPSHOT_MAX_CHUNKS"),
        ("the table's bounds", "MAPGEN_SNAPSHOT_ERR_TABLE_OUT_OF_BOUNDS"),
        ("every chunk's bounds", "MAPGEN_SNAPSHOT_ERR_CHUNK_OUT_OF_BOUNDS"),
        ("the decompression ratio", "MAPGEN_SNAPSHOT_ERR_RATIO_TOO_HIGH"),
        ("the required chunks", "MAPGEN_SNAPSHOT_ERR_MISSING_CHUNK"),
    ):
        at = open_fn.find(needle)
        check(f"{label} is checked before anything is allocated",
              0 <= at < first_alloc, f"check at {at}, first allocation at {first_alloc}")

    check(
        "the header CRC is computed with its own field taken as zero",
        "const uint8_t zero[4] = { 0, 0, 0, 0 };" in src,
        "otherwise the field would have to contain a hash of itself",
    )
    check(
        "the payload hash is over uncompressed bytes in type order",
        "qsort(sorted, count, sizeof(chunk_t), compare_chunks)" in src
        and "sorted[i].size" in src,
        "contract 8: it excludes compressor output, table offsets and padding",
    )
    check(
        "the payload hash never sees an offset or a compression method",
        "ENT_OFFSET" not in src[src.find("static void payload_hash"):
                                src.find("static void free_chunks")],
        "",
    )
    check(
        "the reserved entry field must be zero",
        "if (rd_u32(e + ENT_RESERVED) != 0)" in src,
        "a field with no meaning yet must not quietly carry one; naming "
        "the error code is not the same as making the comparison",
    )
    check(
        "the writer refuses to write what the reader would refuse to read",
        "Refuse to WRITE what the reader would refuse to read" in
        SOURCE.read_text(encoding="utf-8"),
        "",
    )
    check(
        "the container is not SQLite",
        "sqlite" not in src.lower(),
        "contract 8 forbids adding SQLite for this",
    )
    #
    # The corpus trainer has no business in the PO's binary, and that has not
    # changed. The digest has: the client refuses to list or play anything
    # that is not a manifest verifying against every member on disk, and that
    # check has to run where the refusal happens. So the digest is asked the
    # Seam question, and the trainer is still asked the flat one.
    #
    check(
        "the corpus trainer is not in the client",
        "mapgen_snapshot.c" not in _build_lists()[0],
        "the PO's binary must be untouched; MAPGEN ships as its own helper",
    )
    in_helper, why = build_target.only_in_helper("mapgen_digest.c")
    check(
        "the digest is in the client only as part of the declared Seam",
        in_helper, why,
    )
    #
    # And the Seam cannot be widened by editing one list: what
    # `mapgen_build_target.py` declares and what meson.build actually builds
    # must name the same modules. This is the check that would have caught
    # three modules crossing without the rule being updated with them.
    #
    agree, detail = build_target.seam_matches_build()
    check("the declared Seam and the build agree", agree, detail)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("snapshot.exe" if os.name == "nt" else "snapshot")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), str(DIGEST_SOURCE), "-o", str(exe), "-lz"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def run(exe: Path, *args: str) -> str:
    p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=600)
    return p.stdout


def test_digests(exe: Path) -> None:
    head("digest: against the standard, not against ourselves")
    for message, expected in FIPS_VECTORS:
        got = hashlib.sha256(message.encode()).hexdigest()
        check(f"the FIPS vector for {message[:8]!r} is what we think it is",
              got == expected, f"{got} vs {expected}")

    # Deterministic buffers the C and this file both generate, so the digests
    # are compared against hashlib and zlib rather than against each other.
    lines = [ln.split() for ln in run(exe, "digests", "400", "987654321").splitlines() if ln]
    check("the driver produced digests", len(lines) == 400, f"{len(lines)}")

    state = 987654321
    sha_bad = crc_bad = stream_bad = 0
    for parts in lines:
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        length = state % 4096
        data = bytearray()
        for _ in range(length):
            state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            data.append((state >> 33) & 0xFF)
        if int(parts[0]) != length:
            sha_bad += 1
            continue
        if parts[1] != hashlib.sha256(bytes(data)).hexdigest():
            sha_bad += 1
        if int(parts[2], 16) != (zlib.crc32(bytes(data)) & 0xFFFFFFFF):
            crc_bad += 1
        if parts[3] != "1":
            stream_bad += 1

    check("SHA-256 matches hashlib on 400 random buffers", sha_bad == 0, f"{sha_bad} differ")
    check("CRC32 matches zlib on 400 random buffers", crc_bad == 0, f"{crc_bad} differ")
    check("the incremental SHA-256 matches the one-shot", stream_bad == 0,
          f"{stream_bad} differ")


def test_selftest(exe: Path) -> None:
    head("builder: what it refuses to make")
    out = run(exe, "selftest")
    for line in out.splitlines():
        if line.startswith(("  PASS", "  FAIL")):
            print(line)
    m = re.search(r"=== (\d+) cases asserted, (\d+) failures", out)
    if not check("the selftest reported a result", m is not None, out[-400:]):
        return
    assert m is not None
    global CASES, FAILED
    CASES += int(m.group(1))
    FAILED += int(m.group(2))


def test_roundtrip(exe: Path, work: Path) -> None:
    head("roundtrip: build, reopen, and hash the same either way")
    out = run(exe, "roundtrip", str(work).replace("\\", "/"))
    for line in out.splitlines():
        if line.startswith(("  PASS", "  FAIL")):
            print(line)
    m = re.search(r"=== (\d+) cases asserted, (\d+) failures", out)
    if not check("the roundtrip reported a result", m is not None, out[-400:]):
        return
    assert m is not None
    global CASES, FAILED
    CASES += int(m.group(1))
    FAILED += int(m.group(2))


def test_hostile(exe: Path, work: Path) -> None:
    head("hostile: one file per refusal, each corrupted in exactly one field")
    wrong: list[str] = []
    for name, expected in oracle.CORRUPTIONS.items():
        image = oracle.corrupt(name)
        path = work / f"bad_{name}.q2mgdb"
        path.write_bytes(image)
        got = run(exe, "open", str(path)).strip().splitlines()
        got = got[0] if got else "<nothing>"
        if got != expected:
            wrong.append(f"{name}: got {got}, wanted {expected}")
    check(
        f"all {len(oracle.CORRUPTIONS)} corruptions produce their own result code",
        not wrong,
        "; ".join(wrong[:4]),
    )

    # And the reference agrees about every one of them, which is what makes
    # the expected codes above evidence rather than a transcription of the C.
    disagree: list[str] = []
    for name, expected in oracle.CORRUPTIONS.items():
        try:
            oracle.parse(oracle.corrupt(name))
            got = "OK"
        except oracle.SnapshotError as exc:
            got = exc.code
        if got != expected:
            disagree.append(f"{name}: reference says {got}")
    check("the reference refuses each one for the same reason", not disagree,
          "; ".join(disagree[:4]))


def test_cross(exe: Path, work: Path) -> None:
    head("cross: each writes what the other reads")
    for label in ("store", "deflate"):
        path = work / f"c_{label}.q2mgdb"
        out = run(exe, "build", str(path), label).strip()
        if not check(f"the C wrote a {label} snapshot", out.startswith("OK "), out):
            continue
        try:
            parsed = oracle.parse(path.read_bytes())
        except oracle.SnapshotError as exc:
            check(f"the reference reads the C's {label} snapshot", False, exc.code)
            continue
        check(f"the reference reads the C's {label} snapshot", True,
              f"{len(parsed.chunks)} chunks")
        c_hash = run(exe, "hash", str(path)).strip().split()[-1]
        check(f"both agree on the {label} payload hash",
              c_hash == parsed.payload_sha256.hex(),
              f"C {c_hash[:16]} vs reference {parsed.payload_sha256.hex()[:16]}")

    for method, label in ((oracle.COMPRESSION_NONE, "store"),
                          (oracle.COMPRESSION_DEFLATE, "deflate")):
        path = work / f"py_{label}.q2mgdb"
        path.write_bytes(oracle.build(oracle.reference_snapshot(method)))
        out = run(exe, "open", str(path)).strip().splitlines()
        check(f"the C reads the reference's {label} snapshot",
              bool(out) and out[0].startswith("OK "), out[0] if out else "<nothing>")

    # The same content stored two ways must hash the same, in the reference as
    # well as in the C - that is the contract's claim, not an implementation
    # detail of either.
    stored = oracle.payload_hash(oracle.reference_snapshot(oracle.COMPRESSION_NONE).chunks)
    deflated = oracle.payload_hash(
        oracle.reference_snapshot(oracle.COMPRESSION_DEFLATE).chunks)
    check("the reference's payload hash ignores the compressor too",
          stored == deflated, "")


def test_fuzz(exe: Path, work: Path) -> None:
    head("fuzz: a damaged file is refused, never a crash")
    good = oracle.build(oracle.reference_snapshot())
    rng = random.Random(20260831)
    crashes: list[str] = []
    accepted = 0
    path = work / "fuzz.q2mgdb"

    for i in range(400):
        image = bytearray(good)
        for _ in range(rng.randint(1, 6)):
            image[rng.randrange(len(image))] = rng.randrange(256)
        path.write_bytes(bytes(image))
        p = subprocess.run([str(exe), "open", str(path)], capture_output=True,
                           text=True, timeout=120)
        if p.returncode not in (0, 1):
            crashes.append(f"#{i} exit {p.returncode}")
        elif p.stdout.startswith("OK "):
            accepted += 1

    check("400 randomly damaged files never crash the reader", not crashes,
          "; ".join(crashes[:3]))
    # Every byte of the file is now covered by something: the header and the
    # chunk table by the header CRC, chunk bytes by their own CRC and by the
    # payload hash. There is no region left where a flipped bit can hide, so
    # the honest assertion is zero rather than "almost none".
    #
    # It was not zero before this run. A flipped bit in a chunk entry's flags
    # survived, because nothing validated the field and the payload hash never
    # sees the table; the header CRC was extended to cover the table, and
    # `table_flags_bit_flipped` in the hostile set now pins that.
    check("every damaged file is refused", accepted == 0,
          f"{accepted} of 400 still opened")


def main() -> int:
    print("=== MAPGEN-1 M3 snapshot container contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_snapshot_") as td:
        work = Path(td)
        head("building")
        exe = build(cc, work)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_digests(exe)
        test_selftest(exe)
        test_roundtrip(exe, work)
        test_hostile(exe, work)
        test_cross(exe, work)
        test_fuzz(exe, work)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
