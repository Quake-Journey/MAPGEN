#!/usr/bin/env python3
"""MAPGEN-1 M4 - the recipe file.

Contract section 10: one immutable request per generation, requested AND
resolved values both stored, `Generate Again` running the resolved ones, and a
reuse that is refused rather than approximated when the toolchain has moved.
Contract 13's `Custom 0` and contract 22's slug rules land here too.

Two halves:

  * STATIC - what must hold by construction. The module cannot write a file,
    has no clock and no RNG (identity is supplied), and has no way to edit a
    recipe in place, because contract 10's migration is copy-on-write;

  * BEHAVIOUR - the compiled module against real `.q2mgrec` images built in
    memory. Damaged files are CONSTRUCTED - truncated at every length, one bit
    flipped at every offset - rather than described, and the reuse check is
    exercised on each pinned component separately, in both the "different" and
    the "missing" direction.

Run: python tools/check_mapgen_recipe_contract.py
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

HEADER = REPO / "inc" / "common" / "mapgen_recipe.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_recipe.c"
DRIVER = REPO / "tools" / "mapgen_recipe_test_driver.c"
PARTS = [REPO / "src" / "mapgen" / "mapgen_digest.c"]

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
    head("static: immutable by construction, resolved by construction")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    check(
        "the module cannot write a file",
        not re.search(r"\b(fopen|fwrite|fputs|fprintf|remove|unlink|"
                      r"CreateFile|WriteFile|MoveFile|DeleteFile)\b", src),
        "it serializes; the store layer is what writes",
    )
    check(
        "it has no clock and no RNG",
        not re.search(r"\b(time|clock|rand|srand|GetSystemTime|"
                      r"QueryPerformanceCounter)\s*\(", src),
        "identity and the seed are supplied, never invented",
    )
    check(
        "and no floating point anywhere in it",
        not re.search(r"\b(float|double)\b", src),
        "",
    )
    non_const = set(re.findall(r"MapGenRecipe_(\w+)\(\s*mapgen_recipe_t \*", src))
    check(
        "a parsed recipe is const to every function but Free",
        non_const <= {"Free"},
        f"these take it mutable: {sorted(non_const - {'Free'})}; contract 10's "
        "migration is copy-on-write, so there is no in-place edit",
    )
    check(
        "no accessor can reach into a recipe and change it",
        not re.search(r"^\s*(void|[a-z_]+)\s+MapGenRecipe_Set\w+\(mapgen_recipe_t",
                      src, re.M),
        "every setter takes a BUILDER, which is a different type on purpose",
    )
    check(
        "there is no file-scope state",
        not re.search(r"^static\s+(?!const\b)(?!void\b)(?!bool\b)(?!uint\w*\s)"
                      r"(?!int\w*\s)(?!size_t\s)(?!mapgen)"
                      r"[A-Za-z_][\w \*]*\s+[A-Za-z_]\w*\s*(=|;)", src, re.M),
        "",
    )

    # --- Auto is a sentinel, not an absence -------------------------------
    check(
        "Auto is a sentinel with a value of its own",
        "#define MAPGEN_RECIPE_AUTO            INT32_MIN" in hdr,
        "contract 13's Custom 0 is a real number and must not collide with it",
    )
    check(
        "a resolved Auto is refused when the recipe is built",
        "resolved == MAPGEN_RECIPE_AUTO" in src
        and "MAPGEN_RECIPE_ERR_UNRESOLVED" in src,
        "a recipe that has run has no Auto left in it",
    )
    check(
        "and again when one is read back from a file",
        src.count("resolved == MAPGEN_RECIPE_AUTO") >= 2,
        "the file came from a disk, not from this process",
    )
    check(
        "the generator is handed the resolved value only",
        "int32_t MapGenRecipe_ResolvedValue" in hdr
        and "MapGenRecipe_RequestedValue" not in hdr,
        "a generator that could see `requested` could re-resolve an old Auto",
    )

    # --- the reuse check ---------------------------------------------------
    reuse = src[src.find("mapgen_recipe_reuse_t MapGenRecipe_CheckReuse"):]
    for part in ("generator_version", "compiler_build_sha256",
                 "entity_schema_version", "entity_schema_sha256",
                 "physics_profile_id", "physics_profile_sha256"):
        check(
            f"the reuse check compares {part}",
            part in reuse,
            "contract 10 names all of them",
        )
    check(
        "an unreadable component is UNAVAILABLE rather than a match",
        "hash_is_present" in reuse
        and reuse.find("MAPGEN_REUSE_UNAVAILABLE_VERSION")
            < reuse.find("MAPGEN_REUSE_NEEDS_MIGRATION"),
        "an all-zero hash is what a failed read looks like",
    )

    # --- the file ----------------------------------------------------------
    check(
        "the checksum covers the tables, not only the header",
        "size - (OFF_CRC + 4)" in src,
        "the snapshot container shipped with exactly that gap until a test "
        "found it",
    )
    open_fn = src[src.find("mapgen_recipe_result_t MapGenRecipe_Open"):]
    crc_at = open_fn.find("MAPGEN_RECIPE_ERR_BAD_CRC")
    counts_at = open_fn.find("OFF_SNAPSHOT_COUNT")
    alloc_at = min([i for i in (open_fn.find("calloc"), open_fn.find("malloc"))
                    if i >= 0], default=-1)
    check(
        "the checksum is verified before any count is believed",
        crc_at >= 0 and counts_at >= 0 and crc_at < counts_at,
        "a corrupted count is exactly what a checksum is for",
    )
    check(
        "and nothing is allocated until every count has been checked",
        alloc_at >= 0 and counts_at >= 0 and counts_at < alloc_at,
        "",
    )
    check(
        "the declared size must equal the bytes that are there",
        "declared != (uint64_t)size" in src,
        "",
    )
    check(
        "and the tables must fill the file exactly",
        "needed != size" in src,
        "a file with slack after its tables is not this format",
    )
    check(
        "the reserved field must be zero",
        "MAPGEN_RECIPE_ERR_RESERVED_NOT_ZERO" in src,
        "it is how a later version will be told apart",
    )

    # --- the slug ----------------------------------------------------------
    check(
        "the slug alphabet is a whitelist, not a blacklist",
        "c >= 'a' && c <= 'z'" in src and "c == '_'" in src,
        "contract 22: nothing that could become path syntax",
    )
    check(
        "which is why no dot can appear in one",
        "'.'" not in src,
        "`..` needs no special case when no dot is legal at all",
    )

    # The rule protects the PO's binary, not the generator: a module
    # the packaged helper runs has to be linked somewhere, and
    # mapgen_src is the somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_recipe.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("recipe.exe" if os.name == "nt" else "recipe")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), *[str(x) for x in PARTS], "-o", str(exe)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def test_behaviour(exe: Path) -> None:
    head("behaviour: real images, and damage constructed byte by byte")
    try:
        p = subprocess.run([str(exe), "run"], capture_output=True, text=True,
                           timeout=600)
    except subprocess.TimeoutExpired:
        check("the behavioural suite reported a result", False, "timed out")
        return
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
    print("=== MAPGEN-1 M4 recipe contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_recipe_") as td:
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
