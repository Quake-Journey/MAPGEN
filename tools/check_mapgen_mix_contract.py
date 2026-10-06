#!/usr/bin/env python3
"""MAPGEN-1 M4 - mixing several snapshots into one model.

Contract section 9, and section 15's provenance rule for the material
allowlist.

Two halves:

  * STATIC - the properties that must hold by construction rather than by
    testing. Mixing cannot write a file, cannot mutate an input, has no clock
    and no RNG, and works in integers, so "the same selection gives the same
    model" is a fact about the code and not a lucky run;

  * BEHAVIOUR - the compiled module against two snapshots trained from real
    maps on OVERLAPPING corpora, so the shared-source rule has real shared
    sources to act on. The material allowlist is compared against a union
    recomputed in the driver from the snapshots' own chunks, not against the
    module's own bookkeeping.

One clause is checked statically only and is recorded rather than claimed: a
schema_major disagreement takes the same `Needs Rebuild` path as a physics
disagreement, but every snapshot this tree can build carries schema_major 1, so
no behavioural case constructs the mismatch. The physics half of the same
branch IS exercised, with a constructed snapshot the reader accepts.

Run: python tools/check_mapgen_mix_contract.py
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

HEADER = REPO / "inc" / "common" / "mapgen_mix.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_mix.c"
DRIVER = REPO / "tools" / "mapgen_mix_test_driver.c"
PARTS = [
    REPO / "src" / "mapgen" / "mapgen_random.c",
    REPO / "src" / "mapgen" / "mapgen_lineage.c",
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
# Four maps, mixed into two snapshots over maps 0-2 and 1-3: two are shared.
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
    head("static: immutability, determinism and provenance by construction")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    check(
        "the module cannot write a file",
        not re.search(r"\b(fopen|fwrite|fputs|fprintf|remove|unlink|"
                      r"CreateFile|WriteFile|MoveFile|DeleteFile)\b", src),
        "'mixing does not mutate a snapshot' is a fact about the code",
    )
    check(
        "every snapshot it touches is const",
        "mapgen_snapshot_t *" not in src.replace("const mapgen_snapshot_t *", ""),
        "an input it cannot address non-const is an input it cannot change",
    )
    check(
        "the input array is const too",
        "const mapgen_mix_input_t *inputs" in src
        and "const mapgen_mix_input_t *inputs" in hdr,
        "",
    )
    check(
        "there is no clock",
        not re.search(r"\b(time|clock|GetTickCount|GetSystemTime|"
                      r"QueryPerformanceCounter)\s*\(", src),
        "a model that depends on when it was built is not reproducible",
    )
    check(
        "and no random source",
        not re.search(r"\b(rand|srand|random|arc4random)\s*\(", src),
        "",
    )
    check(
        "the arithmetic is integer throughout",
        not re.search(r"\b(float|double)\b", src),
        "parts per million, so a mix is bit-identical on every machine",
    )
    check(
        "no global or file-scope state carries between builds",
        not re.search(r"^static\s+(?!const\b)(?!void\b)(?!bool\b)(?!uint\w*\s+MapGen)"
                      r"[A-Za-z_][\w \*]*\s+[A-Za-z_]\w*\s*(=|;)", src, re.M),
        "two calls in one session must not influence each other",
    )

    # --- the pin ----------------------------------------------------------
    build = src[src.find("mapgen_mix_result_t MapGenMix_Build"):]
    check(
        "the pin compares the revision identity",
        "revision_uuid, inputs[i].revision_uuid" in build.replace("h->", ""),
        "",
    )
    check(
        "and the payload hash",
        "payload_sha256, inputs[i].payload_sha256" in build.replace("h->", ""),
        "a name is not an identity; both halves of the pin are checked",
    )
    check(
        "a mismatch is refused, never substituted",
        "MAPGEN_MIX_ERR_PIN_MISMATCH" in build
        and "MAPGEN_MIX_OK" not in build[:build.find("MAPGEN_MIX_ERR_PIN_MISMATCH")],
        "nothing succeeds before the pin has been checked",
    )

    # --- Needs Rebuild ----------------------------------------------------
    check(
        "a physics disagreement shows Needs Rebuild",
        "physics_schema_hash" in build and "MAPGEN_MIX_ERR_NEEDS_REBUILD" in build,
        "",
    )
    check(
        "and so does a schema disagreement",
        "schema_major" in build,
        "checked statically only: this tree builds one schema major",
    )

    # --- validation precedes construction ---------------------------------
    first_alloc = min(
        [i for i in (build.find("calloc"), build.find("malloc")) if i >= 0],
        default=-1,
    )
    last_refusal = max(
        build.rfind("return MAPGEN_MIX_ERR_PIN_MISMATCH"),
        build.rfind("return MAPGEN_MIX_ERR_NEEDS_REBUILD"),
        build.rfind("return MAPGEN_MIX_ERR_BAD_WEIGHT"),
    )
    check(
        "nothing is allocated until the whole selection has been validated",
        first_alloc >= 0 and last_refusal >= 0 and last_refusal < first_alloc,
        "a half-built model from an incompatible selection is worse than none",
    )
    check(
        "and the out-parameter is cleared before anything can fail",
        build.find("*out = NULL") >= 0
        and build.find("*out = NULL") < build.find("return MAPGEN_MIX_ERR_NO_INPUTS"),
        "a refused build must not leave a stale model in the caller's hands",
    )

    # --- weights ----------------------------------------------------------
    check(
        "the weight range comes from the named constants",
        "MAPGEN_MIX_MIN_WEIGHT" in build and "MAPGEN_MIX_MAX_WEIGHT" in build,
        "",
    )
    check(
        "and the header states what that range is",
        "MAPGEN_MIX_MIN_WEIGHT   1u" in hdr and "MAPGEN_MIX_MAX_WEIGHT   100u" in hdr,
        "contract 9's 1..100",
    )

    # --- provenance -------------------------------------------------------
    check(
        "materials are matched by exact name, never by prefix or substring",
        "strstr" not in src and "strncmp" not in src,
        "two textures that share a prefix are two textures",
    )
    check(
        "a material can only enter the allowlist from a snapshot chunk",
        src.count("mix->num_materials++") == 1
        and "collect_material" in src[:src.find("mix->num_materials++")],
        "contract 15: the allowlist is a union of what was learned",
    )
    check(
        "a materials row missing its role fields is refused",
        "if (!material_field(body, length, &at, &roles)" in src
        and "|| !material_field(body, length, &at, &light_value)\n        || !material_field(body, length, &at, &sources)\n        || !material_field(body, length, &at, &uses))\n        return;" in src,
        "checked statically only: every row the snapshots write has them, so "
        "no corpus can produce the input this refuses",
    )
    check(
        "a material is drawn as often as the corpus wears it",
        "const uint64_t draw = (uint64_t)(uses > 0 ? uses : 1) * m->weight;"
        in src
        and "m->mix->materials[i].weight += draw;" in src
        and "slot->weight = draw;" in src,
        "in that exact form. The weight used to be the SNAPSHOT's, which made "
        "every texture in the allowlist equally likely: a map learned from "
        "q2dm1 wore its incidentals instead of the ochre it is built from, and "
        "came out grey",
    )
    check(
        "the chunk it reads is the materials chunk",
        "MAPGEN_CHUNK_MATERIALS" in build and "MAPGEN_CHUNK_SOURCES" in build,
        "",
    )

    # --- repeated influence -----------------------------------------------
    check(
        "repeated influence is off unless the caller asks",
        "opts->allow_repeated_influence" in build
        and "const mapgen_mix_options_t defaults = { false, NULL, 0 };" in build,
        "the default must not quietly distort what the user asked for",
    )
    check(
        "and the effective source count actually reads the setting",
        "m->repeated_influence" in src[src.find("MapGenMix_EffectiveSourceCount"):],
        "a flag that changed only a displayed number would not be the setting",
    )
    check(
        "the canonical text records which setting produced the model",
        "repeated_influence=" in src and "effective_sources=" in src,
        "",
    )

    # --- canonical form ----------------------------------------------------
    canonical = src[src.find("size_t MapGenMix_CanonicalText"):]
    check(
        "the material table is sorted before it is rendered",
        "qsort" in canonical and "compare_materials" in canonical,
        "so the model does not depend on the order the user selected in",
    )
    check(
        "the digest is taken over the canonical text and nothing else",
        "MapGenMix_CanonicalText" in src[src.find("MapGenMix_CanonicalDigest"):],
        "",
    )

    # The rule protects the PO's binary, not the generator: a module
    # the packaged helper runs has to be linked somewhere, and
    # mapgen_src is the somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_mix.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("mix.exe" if os.name == "nt" else "mix")
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
    head("behaviour: two snapshots trained on overlapping halves of four real maps")
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
    print("=== MAPGEN-1 M4 snapshot mixing contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_mix_") as td:
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
