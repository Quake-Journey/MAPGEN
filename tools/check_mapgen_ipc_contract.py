#!/usr/bin/env python3
"""MAPGEN-1 M1 - IPC frame contract: static checks plus a real property matrix.

Two halves, and the second is the one that matters:

  * STATIC checks over `inc/common/mapgen_protocol.h` and
    `src/mapgen/mapgen_ipc.c` - that the ceiling is enforced before any caller
    sees `payload_len`, that the sequence and job identity are validated by the
    transport, that a violation latches, and that the direction split exists.

  * A BEHAVIOURAL matrix that compiles the REAL C codec and drives thousands
    of frames through it. Hard Rule #51: an injected seam proves the algorithm
    and not the call. A Python reimplementation of the same wire layout would
    agree with the C exactly when both made the same mistake, so the C is what
    gets driven, and the harness only builds frames byte by byte.

The driver is compiled with a targeted throwaway gcc invocation. Hard Rule #30
forbids ad-hoc builds for artifacts that will be run, tested, deployed or given
to the PO; a test driver that never leaves tools/ is exactly the throwaway
syntax/behaviour check that rule permits.

Every case asserts. Run: python tools/check_mapgen_ipc_contract.py
"""

from __future__ import annotations

import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HEADER = REPO / "inc" / "common" / "mapgen_protocol.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_ipc.c"
DRIVER = REPO / "tools" / "mapgen_ipc_test_driver.c"

CASES = 0
FAILED = 0

MAGIC = 0x474D3251
VERSION = 1
HEADER_BYTES = 36
MAX_PAYLOAD = 1 << 20
OFS_CRC = 32


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
    """Checks run on CODE, never on comments.

    memory/feedback_never_corrupt_po_preset_and_config_data.md item (d): an
    exemption that matched a COMMENT let a mutant through unnoticed.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


# ---------------------------------------------------------------------------
# Static contract
# ---------------------------------------------------------------------------
def test_static() -> None:
    head("static: the frame contract")
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))

    check("header declares a magic", "#define MAPGEN_IPC_MAGIC" in hdr, "")
    check("header declares a version", "#define MAPGEN_IPC_VERSION" in hdr, "")
    check("header declares a fixed frame size", "#define MAPGEN_IPC_HEADER_BYTES" in hdr, "")
    check("header declares a payload ceiling", "#define MAPGEN_IPC_MAX_PAYLOAD" in hdr, "")
    check("header declares a capability token", "#define MAPGEN_IPC_TOKEN_BYTES" in hdr, "")

    for field in ("magic", "version", "type", "payload_len", "sequence", "job_uuid", "header_crc32"):
        check(f"frame carries {field}", re.search(rf"\b{field}\b", hdr) is not None, "")

    check(
        "the ceiling is enforced in the decoder",
        "if (payload_len > MAPGEN_IPC_MAX_PAYLOAD)" in src,
        "payload_len must be bounded before any caller can allocate on it",
    )
    guard_at = src.find("if (payload_len > MAPGEN_IPC_MAX_PAYLOAD)")
    publish_at = src.find("out->payload_len = payload_len;")
    check(
        "the ceiling is checked BEFORE the caller sees payload_len",
        guard_at >= 0 and publish_at >= 0 and guard_at < publish_at,
        "a caller must never read an unbounded length",
    )
    check(
        "the encoder refuses what the decoder would reject",
        "if (header->payload_len > MAPGEN_IPC_MAX_PAYLOAD)" in src,
        "a codec that emits frames it will not accept hides its own bug in the peer",
    )
    check(
        "the sequence is validated by the transport",
        "if (header->sequence != stream->expect_sequence)" in src,
        "Hard Rule #46: every reader validates the key",
    )
    check(
        "the job identity is validated by the transport",
        "memcmp(stream->job_uuid, header->job_uuid," in src,
        "a frame for another job must not reach a handler",
    )
    check(
        "the first accepted frame binds the job",
        "stream->job_bound = true;" in src,
        "",
    )
    check(
        "a violation latches",
        "if (stream->failed)" in src and src.count("stream->failed = true;") >= 2,
        "a degraded transport must not repair itself frame by frame",
    )
    check(
        "the direction split exists",
        "MapGenIpc_IsWorkerToController" in src and "MapGenIpc_IsControllerToWorker" in src,
        "",
    )
    check(
        "the codec pulls in no engine headers",
        not re.search(r'#include\s+"(?!common/mapgen_protocol\.h)', src),
        "the codec links into the client, the worker and the driver; it must stay pure",
    )
    check(
        "the codec does not allocate",
        not re.search(r"\b(malloc|calloc|realloc|Z_Malloc|Z_TagMalloc)\b", src),
        "frame decoding must never allocate on a length it has not yet validated",
    )


# ---------------------------------------------------------------------------
# The real codec
# ---------------------------------------------------------------------------
class Driver:
    def __init__(self, exe: Path):
        self.proc = subprocess.Popen(
            [str(exe)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def cmd(self, text: str) -> str:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        return line.strip()

    def close(self) -> None:
        try:
            self.cmd("quit")
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def crc32(data: bytes) -> int:
    import zlib

    return zlib.crc32(data) & 0xFFFFFFFF


def build_header(type_: int, payload: int, seq: int, uuid: bytes,
                 magic: int = MAGIC, version: int = VERSION,
                 crc: int | None = None) -> bytes:
    """Assemble a frame BYTE BY BYTE, independently of the encoder under test."""
    blob = bytearray(HEADER_BYTES)
    struct.pack_into("<I", blob, 0, magic)
    struct.pack_into("<H", blob, 4, version)
    struct.pack_into("<H", blob, 6, type_)
    struct.pack_into("<I", blob, 8, payload)
    struct.pack_into("<I", blob, 12, seq)
    blob[16:32] = uuid
    struct.pack_into("<I", blob, OFS_CRC, crc32(bytes(blob[:OFS_CRC])) if crc is None else crc)
    return bytes(blob)


def compile_driver(workdir: Path) -> Path | None:
    gcc = shutil.which("gcc") or shutil.which("cc")
    if not gcc:
        return None
    exe = workdir / ("mapgen_ipc_driver.exe" if os.name == "nt" else "mapgen_ipc_driver")
    proc = subprocess.run(
        [gcc, "-std=c17", "-O1", "-Wall", "-Wextra", "-Werror",
         "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), "-o", str(exe)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout + proc.stderr)
        return None
    return exe


def test_behaviour(exe: Path) -> None:
    d = Driver(exe)
    try:
        head("behaviour: constants agree between C and the harness")
        consts = d.cmd("consts").split()
        check("driver answers consts", len(consts) == 5, str(consts))
        if len(consts) == 5:
            hb, magic, version, maxp, tcount = (int(x) for x in consts)
            check("header size agrees", hb == HEADER_BYTES, f"C={hb} harness={HEADER_BYTES}")
            check("magic agrees", magic == MAGIC, f"C={magic:#x} harness={MAGIC:#x}")
            check("version agrees", version == VERSION, f"C={version}")
            check("payload ceiling agrees", maxp == MAX_PAYLOAD, f"C={maxp}")
            check("type count is what the header declares", tcount == 14, f"C={tcount}")

        head("behaviour: round trip")
        rng = random.Random(20260831)
        mismatches = 0
        for _ in range(400):
            type_ = rng.randint(1, 13)
            payload = rng.randint(0, MAX_PAYLOAD)
            seq = rng.randint(0, 0xFFFFFFFF)
            uuid = bytes(rng.randrange(256) for _ in range(16))
            enc = d.cmd(f"encode {type_} {payload} {seq} {uuid.hex()}")
            if not enc.startswith("ok "):
                mismatches += 1
                continue
            wire = bytes.fromhex(enc[3:])
            if wire != build_header(type_, payload, seq, uuid):
                mismatches += 1
                continue
            dec = d.cmd(f"decode {wire.hex()}").split()
            if dec[0] != "OK" or int(dec[1]) != type_ or int(dec[2]) != payload \
                    or int(dec[3]) != seq or dec[4] != uuid.hex():
                mismatches += 1
        check("400 random frames round-trip byte-exactly", mismatches == 0, f"{mismatches} mismatches")

        head("behaviour: every malformed frame is refused")
        uuid = bytes(range(16))
        good = build_header(3, 128, 0, uuid)

        check("a good frame decodes", d.cmd(f"decode {good.hex()}").split()[0] == "OK", "")
        check(
            "a short frame asks for more rather than failing",
            d.cmd(f"decode {good[:HEADER_BYTES - 1].hex()}").split()[0] == "INCOMPLETE",
            "",
        )
        check("an empty frame is incomplete", d.cmd("decode ").split()[0] == "INCOMPLETE", "")
        check(
            "a wrong magic is refused",
            d.cmd(f"decode {build_header(3, 128, 0, uuid, magic=MAGIC ^ 1).hex()}").split()[0] == "BAD_MAGIC",
            "",
        )
        check(
            "a wrong version is refused",
            d.cmd(f"decode {build_header(3, 128, 0, uuid, version=VERSION + 1).hex()}").split()[0] == "BAD_VERSION",
            "",
        )
        check(
            "type 0 is refused",
            d.cmd(f"decode {build_header(0, 128, 0, uuid).hex()}").split()[0] == "BAD_TYPE",
            "",
        )
        check(
            "a type above the table is refused",
            d.cmd(f"decode {build_header(14, 128, 0, uuid).hex()}").split()[0] == "BAD_TYPE",
            "",
        )
        check(
            "a payload one byte over the ceiling is refused",
            d.cmd(f"decode {build_header(3, MAX_PAYLOAD + 1, 0, uuid).hex()}").split()[0] == "PAYLOAD_TOO_LARGE",
            "",
        )
        check(
            "a payload of 0xffffffff is refused",
            d.cmd(f"decode {build_header(3, 0xFFFFFFFF, 0, uuid).hex()}").split()[0] == "PAYLOAD_TOO_LARGE",
            "",
        )
        check(
            "exactly the ceiling is accepted",
            d.cmd(f"decode {build_header(3, MAX_PAYLOAD, 0, uuid).hex()}").split()[0] == "OK",
            "the boundary must be inclusive, or a legal frame is dropped",
        )
        check(
            "a corrupt header CRC is refused",
            d.cmd(f"decode {build_header(3, 128, 0, uuid, crc=0).hex()}").split()[0] == "BAD_CRC",
            "",
        )

        head("behaviour: the encoder will not emit what the decoder refuses")
        check("encoding type 0 fails", d.cmd(f"encode 0 0 0 {uuid.hex()}") == "err", "")
        check("encoding type 14 fails", d.cmd(f"encode 14 0 0 {uuid.hex()}") == "err", "")
        check(
            "encoding an over-ceiling payload fails",
            d.cmd(f"encode 3 {MAX_PAYLOAD + 1} 0 {uuid.hex()}") == "err",
            "",
        )

        head("behaviour: single-bit corruption anywhere is caught")
        survivors: list[int] = []
        for bit in range(HEADER_BYTES * 8):
            flipped = bytearray(good)
            flipped[bit // 8] ^= 1 << (bit % 8)
            if d.cmd(f"decode {bytes(flipped).hex()}").split()[0] == "OK":
                survivors.append(bit)
        check(
            "no single-bit flip in a frame header decodes as OK",
            not survivors,
            f"{len(survivors)} bit positions decoded cleanly after corruption: {survivors[:12]}",
        )

        head("behaviour: sequence and job identity")
        d.cmd("stream_reset")
        check("the first frame binds the job", d.cmd(f"stream_accept {build_header(2, 0, 0, uuid).hex()}") == "accept", "")
        check("the next sequence is accepted", d.cmd(f"stream_accept {build_header(3, 0, 1, uuid).hex()}") == "accept", "")
        check("a repeated sequence is rejected", d.cmd(f"stream_accept {build_header(3, 0, 1, uuid).hex()}") == "reject", "")
        check("the violation latched", d.cmd("stream_failed") == "1", "")
        check(
            "a correct frame after a violation is STILL rejected",
            d.cmd(f"stream_accept {build_header(3, 0, 2, uuid).hex()}") == "reject",
            "a degraded transport must not repair itself",
        )

        d.cmd("stream_reset")
        check("stream_reset clears the latch", d.cmd("stream_failed") == "0", "")
        check("a fresh stream accepts sequence 0", d.cmd(f"stream_accept {build_header(2, 0, 0, uuid).hex()}") == "accept", "")
        check(
            "a skipped sequence is rejected",
            d.cmd(f"stream_accept {build_header(3, 0, 2, uuid).hex()}") == "reject",
            "a gap means a lost frame, not a fast peer",
        )

        d.cmd("stream_reset")
        other = bytes(range(16, 32))
        d.cmd(f"stream_accept {build_header(2, 0, 0, uuid).hex()}")
        check(
            "a frame for a different job is rejected even with the right sequence",
            d.cmd(f"stream_accept {build_header(3, 0, 1, other).hex()}") == "reject",
            "this is the reused-slot defect Hard Rule #46 was written for",
        )
        check("the identity violation latched", d.cmd("stream_failed") == "1", "")

        head("behaviour: message direction")
        worker_only = {1, 2, 3, 4, 5, 6, 7, 8}
        controller_only = {9, 10, 11, 12, 13}
        bad = []
        for type_ in range(0, 16):
            w2c, c2w = (x == "1" for x in d.cmd(f"dir {type_}").split())
            if w2c != (type_ in worker_only) or c2w != (type_ in controller_only):
                bad.append(type_)
            if w2c and c2w:
                bad.append(type_)
        check("every type belongs to exactly one direction", not bad, f"wrong for {bad}")

        head("behaviour: fuzz")
        rng = random.Random(31082026)
        crashes = 0
        accepted_garbage = 0
        for _ in range(3000):
            n = rng.choice([0, 1, 17, 35, 36, 37, 64, 200])
            blob = bytes(rng.randrange(256) for _ in range(n))
            try:
                out = d.cmd(f"decode {blob.hex()}")
            except Exception:
                crashes += 1
                break
            if not out:
                crashes += 1
                break
            if out.split()[0] == "OK":
                accepted_garbage += 1
        check("3000 random buffers never crash the decoder", crashes == 0, "")
        check(
            "random bytes are essentially never accepted as a frame",
            accepted_garbage == 0,
            f"{accepted_garbage} random buffers decoded as valid frames",
        )
    finally:
        d.close()


def main() -> int:
    print("=== MAPGEN-1 IPC frame contract")
    test_static()

    head("compiling the real codec for the behavioural matrix")
    with tempfile.TemporaryDirectory(prefix="mapgen_ipc_") as td:
        exe = compile_driver(Path(td))
        if not check("test driver compiles with -Wall -Wextra -Werror", exe is not None, "gcc missing or the build failed"):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_behaviour(exe)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
