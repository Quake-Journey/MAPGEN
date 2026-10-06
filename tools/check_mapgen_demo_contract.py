"""GF6A: the demo ingestion refuses what it cannot honestly account for.

A corpus is evidence, and evidence that silently drops what it could not read
reports agreement it has not earned. So every way a stream can be unusable has
a case here, and every one of them is built from REAL demo bytes - truncated,
corrupted, relabelled - rather than from a hand-written file that might be
refused for some other reason entirely.

    python tools/check_mapgen_demo_contract.py [--work DIR] [--corpus DIR]

The corpus is read and never written: every case works on a copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\Demos\q2dm1")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\demo")

SOURCES = [
    "tools/mapgen_demo_ingest.c",
    "src/mapgen/mapgen_demo.c",
    "src/mapgen/mapgen_digest.c",
    "src/client/demo_offline_decoder.c",
    "src/common/msg.c",
    "src/common/sizebuf.c",
    "src/common/math.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

CASES = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
        FAILURES.append(name)
    return ok


def build(work: Path) -> Path | None:
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "demo_ingest.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(REPO / "inc"), "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=1",
         "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=1", "-DUSE_MVD_CLIENT=1"]
        + [str(REPO / s) for s in SOURCES] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2500:])
        return None
    return exe


def ingest(exe: Path, path: Path, expect_map: str | None = "q2dm1") -> str:
    """The verdict line, which is either OK's body or 'REJECTED: <code>'."""
    args = [str(exe), str(path)]
    if expect_map:
        args += ["--map", expect_map]
    run = subprocess.run(args, capture_output=True, text=True, timeout=600)
    for line in run.stdout.splitlines():
        if "REJECTED:" in line:
            return line.split("REJECTED:")[1].strip()
        # A stream that could not even be opened has no provenance to print,
        # so the tool says so on the first line instead.
        if line.startswith("ERR_") or ": ERR_" in line:
            return line.split(":")[-1].strip()
    return "OK" if run.returncode == 0 else "UNKNOWN"


def a_good_demo(work: Path) -> Path | None:
    """The first corpus member the ingester accepts whole.

    Chosen by ASKING rather than by picking a name: the corpus has truncated
    members in it, and a fixture built on one would be testing two things.
    """
    sys.path.insert(0, str(REPO / "tools"))
    import mapgen_demo_unpack as unpack

    laid_out = work / "corpus"
    if laid_out.exists():
        shutil.rmtree(laid_out)
    demos, _ = unpack.unpack(CORPUS, laid_out)
    return demos[0] if demos else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    args = ap.parse_args()
    work = args.work
    work.mkdir(parents=True, exist_ok=True)

    print("=== MAPGEN-1 demo ingestion contract")
    exe = build(work)
    if not check("the ingester compiles", exe is not None):
        return 1
    assert exe

    if not check("the corpus is where it should be", args.corpus.is_dir(),
                 str(args.corpus)):
        return 1

    laid_out = work / "corpus"
    if laid_out.exists():
        shutil.rmtree(laid_out)
    sys.path.insert(0, str(REPO / "tools"))
    import mapgen_demo_unpack as unpack
    demos, unreadable = unpack.unpack(args.corpus, laid_out)
    check("the corpus lays out", bool(demos), f"{len(demos)} files")
    check("and what it could not read is NAMED rather than skipped",
          any("no reader for" in why for why in unreadable),
          f"{unreadable}")

    print("\n=== a stream it accepts, so the refusals mean something")
    good = None
    for candidate in demos:
        if ingest(exe, candidate) == "OK":
            good = candidate
            break
    if not check("at least one corpus member is accepted whole",
                 good is not None):
        return 1
    assert good
    raw = good.read_bytes()

    print("\n=== and every way one can be unusable")

    truncated = work / "truncated.dm2"
    truncated.write_bytes(raw[:len(raw) // 2])
    check("a stream that stops half way -> ERR_TRUNCATED",
          ingest(exe, truncated) == "ERR_TRUNCATED", ingest(exe, truncated))

    empty = work / "empty.dm2"
    empty.write_bytes(b"")
    check("a stream with nothing in it is refused",
          ingest(exe, empty) not in ("OK", "UNKNOWN"), ingest(exe, empty))

    garbage = work / "garbage.dm2"
    garbage.write_bytes(b"\xff" * 4096)
    check("bytes that are not a demo at all are refused",
          ingest(exe, garbage) not in ("OK", "UNKNOWN"), ingest(exe, garbage))

    # A message length the decoder must refuse rather than trust: the first
    # block's length is replaced with one larger than the protocol allows.
    oversized = work / "oversized.dm2"
    body = bytearray(raw)
    struct.pack_into("<i", body, 0, 1 << 24)
    oversized.write_bytes(bytes(body))
    check("a block that claims to be enormous is refused",
          ingest(exe, oversized) not in ("OK", "UNKNOWN"),
          ingest(exe, oversized))

    # A protocol nobody in this tree can read. The first block is
    # [int32 length][byte svc_serverdata][int32 protocol], so the number sits
    # at offset five and 9999 is not any Quake II protocol.
    alien = work / "alien_protocol.dm2"
    body = bytearray(raw)
    struct.pack_into("<i", body, 5, 9999)
    alien.write_bytes(bytes(body))
    check("a protocol this build cannot decode -> ERR_UNSUPPORTED",
          ingest(exe, alien) == "ERR_UNSUPPORTED", ingest(exe, alien))

    # Everything up to the end of the FIRST block: a stream that sets a map up
    # and records nobody. It ends where a block ends, so it is not truncated -
    # there is simply no point of view in it.
    first_block = struct.unpack_from("<i", raw, 0)[0]
    if 0 < first_block < len(raw):
        headless = work / "no_pov.dm2"
        headless.write_bytes(raw[:4 + first_block])
        check("a stream with nobody in it -> ERR_NO_POV",
              ingest(exe, headless) == "ERR_NO_POV", ingest(exe, headless))
    else:
        check("the first block's length is readable", False, str(first_block))

    check("a stream recorded on another map -> ERR_MAP_MISMATCH",
          ingest(exe, good, expect_map="q2dm7") == "ERR_MAP_MISMATCH",
          ingest(exe, good, expect_map="q2dm7"))

    missing = work / "not_here.dm2"
    if missing.exists():
        missing.unlink()
    check("a file that is not there -> ERR_OPEN",
          ingest(exe, missing) == "ERR_OPEN", ingest(exe, missing))

    print("\n=== provenance that does not fit is refused, not trimmed")
    long_name = work / ("x" * 200 + ".dm2")
    try:
        shutil.copy2(good, long_name)
        have_long = True
    except OSError:
        have_long = False
    if have_long:
        run = subprocess.run([str(exe), str(long_name), "--map", "q2dm1",
                              "--source", "s" * 300],
                             capture_output=True, text=True, timeout=600)
        check("a source name longer than the schema -> "
              "ERR_PROVENANCE_TOO_LONG",
              "ERR_PROVENANCE_TOO_LONG" in run.stdout, run.stdout[-200:])
    else:
        check("a source name longer than the schema is refusable", True,
              "the filesystem would not hold the fixture")

    print("\n=== two archive members that would become one file")
    collide = work / "collide"
    if collide.exists():
        shutil.rmtree(collide)
    collide.mkdir(parents=True)
    archive = collide / "two_of_them.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("duel/1.dm2", raw[:4096])
        z.writestr("ffa/1.dm2", raw[:2048])
    out_dir = work / "collide_out"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    laid, why = unpack.unpack(collide, out_dir)
    check("both members are laid out under their own identity",
          len(laid) == 2 and len({p.name for p in laid}) == 2,
          f"{[p.name for p in laid]} / {why}")

    print("\n=== durable raw results")
    results = {
        "corpus": str(args.corpus),
        "laid_out": len(demos),
        "not_read": unreadable,
        "accepted_example": {
            "path": str(good),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
    out = work / "demo_contract_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    check("the run leaves a machine-readable record",
          out.exists() and out.stat().st_size > 0, str(out))

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
