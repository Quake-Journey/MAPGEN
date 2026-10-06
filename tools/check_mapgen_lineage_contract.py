#!/usr/bin/env python3
"""MAPGEN-1 M3 - New, Extend, Rebuild and Rename.

Contract section 7's Training modes and section 8's copy-on-write rule.

Three halves:

  * STATIC - nothing in the module can modify an existing snapshot, identity is
    supplied rather than invented, and there is no clock, no RNG and no global
    state to make a result unrepeatable;

  * BEHAVIOUR - the compiled module against snapshots built from real maps,
    checking every property the contract names of each mode. Two carry the
    most weight: a Rebuild of the same sources reproduces the SAME payload
    hash, and a Rename leaves every learned chunk byte-identical;

  * SLUGS - "Russian names never become unsafe filesystem syntax", which is
    contract 8's wording and is tested with an actual Russian name.

Run: python tools/check_mapgen_lineage_contract.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_build_target as build_target  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

HEADER = REPO / "inc" / "common" / "mapgen_lineage.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_lineage.c"
DRIVER = REPO / "tools" / "mapgen_lineage_test_driver.c"
PARTS = [
    REPO / "src" / "mapgen" / "mapgen_training.c",
    REPO / "src" / "mapgen" / "mapgen_snapshot.c",
    REPO / "src" / "mapgen" / "mapgen_digest.c",
    REPO / "src" / "mapgen" / "mapgen_features.c",
    REPO / "src" / "mapgen" / "mapgen_wiring.c",
    REPO / "src" / "mapgen" / "mapgen_space.c",
    REPO / "src" / "mapgen" / "mapgen_trace.c",
    REPO / "src" / "mapgen" / "mapgen_genome.c",
    REPO / "src" / "mapgen" / "mapgen_bsp.c",
    REPO / "src" / "mapgen" / "mapgen_geometry.c",
    REPO / "src" / "mapgen" / "mapgen_blueprint.c",
]

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
]
MAPS = ["2box4.bsp", "redyard.bsp", "rcdm17.bsp", "lbrdm1.bsp"]

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


def test_static() -> None:
    head("static: copy-on-write by construction, not by intention")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    check(
        "the parent is taken as const everywhere",
        "mapgen_snapshot_t *parent" not in src.replace("const mapgen_snapshot_t *parent", ""),
        "a non-const parent is a parent something could write to",
    )
    check(
        "the module cannot write a file at all",
        not re.search(r"\b(fopen|CreateFile|WriteFile|MoveFile|remove|unlink)\w*\s*\(", src),
        "copy-on-write is easiest to guarantee by having no way to write over "
        "anything",
    )
    check(
        "identity is a parameter, never invented here",
        not re.search(r"\b(rand|srand|time|clock|GetSystemTime|UuidCreate)\w*\s*\(", src),
        "a mode that minted its own identity could not be reproduced, and a "
        "Rebuild that cannot be reproduced proves nothing",
    )
    check(
        "the created timestamp is supplied too",
        "uint64_t created_utc_ms" in hdr,
        "",
    )

    statics = [
        m.group(0).strip()
        for m in re.finditer(r"^static\s+[^;(){}]*;", src, re.MULTILINE)
        if "const" not in m.group(0)
    ]
    check("no mutable file-scope state", not statics, f"{statics[:3]}")

    check(
        "a derived revision may not reuse its parent's identity",
        "MAPGEN_LINEAGE_ERR_SAME_REVISION" in src
        and "memcmp(h->revision_uuid, revision, MAPGEN_SNAPSHOT_UUID_BYTES)" in src,
        "two revisions with one identity is a lineage nobody can follow",
    )
    check(
        "every derived revision records the parent's payload hash",
        src.count("MapGenSnapshot_SetIdentity(b, h->lineage_uuid, revision, h->payload_sha256)") == 2,
        "derive() and Rename() both, so a revision can always say what it came from",
    )
    check(
        "a new lineage records no parent",
        "MapGenSnapshot_SetIdentity(b, lineage, revision, NULL);" in src,
        "",
    )
    check(
        "Rename copies every chunk but META untouched",
        "if (type != MAPGEN_CHUNK_META) {" in src,
        "a rename must not be able to change what was learned",
    )
    check(
        "a title with a control byte is refused",
        "if (*p < 0x20 || *p == 0x7F)" in src,
        "the title reaches a UI, a report and a filename",
    )
    check(
        "the slug is built from ASCII alone",
        "(*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9')" in src,
        "contract 8: Russian names never become unsafe filesystem syntax",
    )
    # The rule protects the PO's binary, not the generator: a module the
    # packaged helper runs has to be linked somewhere, and mapgen_src is the
    # somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_lineage.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("lineage.exe" if os.name == "nt" else "lineage")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), *[str(x) for x in PARTS], "-o", str(exe), "-lz"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def find_map(name: str) -> Path | None:
    for root in MAP_ROOTS:
        if (root / name).exists():
            return root / name
    return None


def test_behaviour(exe: Path) -> None:
    head("behaviour: the four modes, on snapshots built from real maps")
    paths = [find_map(n) for n in MAPS]
    paths = [p for p in paths if p]
    if not check("the maps are available", len(paths) == len(MAPS),
                 f"{len(paths)} of {len(MAPS)}"):
        return

    p = subprocess.run([str(exe), "run", *[str(x) for x in paths]],
                       capture_output=True, text=True, timeout=1800)
    for line in p.stdout.splitlines():
        if line.startswith(("  PASS", "  FAIL")):
            print(line)
    m = re.search(r"=== (\d+) cases asserted, (\d+) failures", p.stdout)
    if not check("the behavioural suite reported a result", m is not None,
                 (p.stdout + p.stderr)[-600:]):
        return
    assert m is not None
    global CASES, FAILED
    CASES += int(m.group(1))
    FAILED += int(m.group(2))


def main() -> int:
    print("=== MAPGEN-1 M3 lineage contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_lineage_") as td:
        head("building")
        exe = build(cc, Path(td))
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
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
