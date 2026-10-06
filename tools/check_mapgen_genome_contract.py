#!/usr/bin/env python3
"""MAPGEN-1 M2 - MapGenome layer 1: materials and entities.

Three halves:

  * STATIC - the classifier reads FLAGS and never NAMES, the module stays pure,
    and the caps are the format's own limits rather than numbers chosen for
    comfort;

  * CRAFTED - the compiled selftest, where texture names and flags deliberately
    disagree. That rule cannot be proven on real maps, because there name and
    flags almost always agree; it has to be tested where they do not;

  * REAL - every one of the 132 shipped maps extracts, and re-extracting gives
    the same digest.

Contract sections 7.7 (never classify from a substring), 15 (material
provenance) and 10 (determinism).

Run: python tools/check_mapgen_genome_contract.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
# The one rule for what belongs to the fixed corpus; see mapgen_corpus.py.
from mapgen_corpus import is_generated  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
HEADER = REPO / "inc" / "common" / "mapgen_genome.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_genome.c"
DRIVER = REPO / "tools" / "mapgen_genome_test_driver.c"
BSPDOC = REPO / "src" / "mapgen" / "mapgen_bsp.c"

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
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


def test_static() -> None:
    head("static: roles come from flags, not from names")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    # The classifier is one function. Extracting it means the "no names" rule
    # can be checked on a bounded piece of code rather than on a whole file.
    m = re.search(r"static uint32_t roles_from\([^)]*\)\s*\{(.*?)\n\}", src, re.DOTALL)
    body = m.group(1) if m else ""
    check("the role classifier exists as one function", bool(body), "roles_from not found")
    check(
        "the classifier never looks at a name",
        bool(body) and not re.search(r"\b(strstr|strcmp|strncmp|strcasecmp|name)\b", body),
        "contract 7.7: never classify only from a filename substring",
    )
    check(
        "the classifier reads surface flags and contents",
        "surface_flags &" in body and "contents &" in body,
        "",
    )
    check(
        "no substring matching anywhere in the module",
        "strstr(" not in src,
        "a substring test on a texture name is the defect this layer exists to avoid",
    )
    check(
        "material lookup is exact",
        "if (!strcmp(g->materials[i].name, name))" in src,
        "a fuzzy lookup would resurrect name-based classification through the back door",
    )
    check(
        "contents come from the brushes, not from the texinfo",
        "g->materials[index].contents |= brush->contents;" in src,
        "a texture is only water when a water brush uses it",
    )
    check(
        "the module is pure",
        not re.search(r'#include\s+"(?!common/mapgen_)', src)
        and not re.search(r"#include\s+<(windows|unistd)\.h>", src),
        "",
    )
    check(
        "entity values are capped at the FORMAT's limit",
        "#define MAPGEN_GENOME_VALUE_BYTES     1024" in hdr,
        "inc/format/bsp.h sets MAX_VALUE 1024; a tighter cap refuses real maps",
    )
    check(
        "an overlong value is an error rather than a truncation",
        "MAPGEN_GENOME_ERR_ENTITY_TOO_LONG" in src and "*too_long = true;" in src,
        "a truncated targetname would silently rewire a map",
    )
    check(
        "control bytes are stripped from entity values",
        "out[n++] = ((unsigned char)c < 0x20) ? '?' : c;" in src,
        "",
    )
    check(
        "materials are digested in sorted name order",
        "strcmp(g->materials[order[j - 1]].name, g->materials[key].name) > 0" in src,
        "the texinfo lump's order must not reach the digest (contract 10)",
    )
    check(
        "float text is locale-free",
        '"%f"' not in src and "sprintf" not in src,
        "",
    )


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("genome.exe" if os.name == "nt" else "genome")
    p = subprocess.run(
        [cc, "-std=c17", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), str(BSPDOC), "-o", str(exe)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def test_crafted(exe: Path) -> None:
    head("crafted: where names and flags deliberately disagree")
    p = subprocess.run([str(exe), "selftest"], capture_output=True, text=True, timeout=300)
    for line in p.stdout.splitlines():
        if line.startswith(("  PASS", "  FAIL", "===")):
            print(line)
    m = re.search(r"=== (\d+) cases asserted, (\d+) failures", p.stdout)
    if not check("the selftest reported a result", m is not None, p.stdout[-600:]):
        return
    assert m is not None
    global CASES, FAILED
    CASES += int(m.group(1))
    FAILED += int(m.group(2))
    check("the crafted cases passed", int(m.group(2)) == 0 and p.returncode == 0, "")
    check("the crafted set is not trivial", int(m.group(1)) >= 25, f"only {m.group(1)} cases")


def test_real_maps(exe: Path) -> None:
    head("real: every shipped map extracts, and does so stably")
    maps = [p for root in MAP_ROOTS if root.is_dir() for p in sorted(root.glob("*.bsp"))
            # The generator publishes into this directory under contract 22's
            # reserved `q2mg_` basename. Those are legal training input but they are
            # not part of the fixed corpus these checks count, and a count that moves
            # every time somebody generates a map is not a count.
            if not is_generated(p.name)]
    if not check("real maps are available", len(maps) >= 100, f"found {len(maps)}"):
        return

    failures: list[str] = []
    digests: dict[str, str] = {}
    totals = {"materials": 0, "entities": 0, "sky": 0, "water": 0, "lava": 0}
    for path in maps:
        out = subprocess.run([str(exe), "map", str(path)], capture_output=True,
                             text=True, timeout=300).stdout.strip()
        if not out.startswith("OK "):
            failures.append(f"{path.name}: {out}")
            continue
        parts = out.split()
        totals["materials"] += int(parts[1])
        totals["entities"] += int(parts[2])
        totals["sky"] += int(parts[3])
        totals["water"] += int(parts[4])
        totals["lava"] += int(parts[5])
        d = subprocess.run([str(exe), "digest", str(path)], capture_output=True,
                           text=True, timeout=300).stdout.strip()
        digests[path.name] = d

    check(
        f"all {len(maps)} shipped maps extract",
        not failures,
        "; ".join(failures[:4]),
    )
    print(f"  ..    {totals['materials']} materials, {totals['entities']} entities, "
          f"{totals['sky']} sky, {totals['water']} water, {totals['lava']} lava")

    # The population has to be plausible: a classifier that silently returned
    # nothing would also produce zero failures.
    check("materials were actually found", totals["materials"] > 1000, f"{totals['materials']}")
    check("entities were actually found", totals["entities"] > 5000, f"{totals['entities']}")
    check("sky surfaces were found on real maps", totals["sky"] > 20, f"{totals['sky']}")
    check("liquids were found on real maps", totals["water"] + totals["lava"] > 10,
          f"water={totals['water']} lava={totals['lava']}")

    sample = maps[0]
    again = subprocess.run([str(exe), "digest", str(sample)], capture_output=True,
                           text=True, timeout=300).stdout.strip()
    check("re-extracting a map gives the same digest", again == digests.get(sample.name), "")
    # Distinct FILES, not distinct filenames. Five pairs in the shipped set are
    # byte-identical maps under different names - aerowalk/q2duel1,
    # ikdm3/q2duel6, q2duel3/q2rdm5, q2duel8/ztn2dm3, ztn2dm1/ztn2dm1_c - and
    # identical content giving an identical digest is the digest WORKING.
    import hashlib

    by_content: dict[str, set[str]] = {}
    for path in maps:
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        by_content.setdefault(file_hash, set()).add(digests.get(path.name, ""))
    collisions = [
        digests[path.name]
        for file_hash, digest_set in by_content.items()
        for path in [next(m for m in maps if hashlib.sha256(m.read_bytes()).hexdigest() == file_hash)]
        if len(digest_set) != 1
    ]
    distinct_files = len(by_content)
    distinct_digests = len({d for s in by_content.values() for d in s})
    check(
        "each distinct map file gets its own digest",
        not collisions and distinct_digests == distinct_files,
        f"{distinct_digests} digests for {distinct_files} distinct files",
    )
    check(
        "identical files give identical digests",
        all(len(s) == 1 for s in by_content.values()),
        "byte-identical content must digest identically",
    )


def main() -> int:
    print("=== MAPGEN-1 MapGenome contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_genome_") as td:
        out = Path(td)
        head("building")
        exe = build(cc, out)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_crafted(exe)
        test_real_maps(exe)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
