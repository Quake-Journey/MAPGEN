#!/usr/bin/env python3
"""MAPGEN-1 M2 - MapGenFeatures, the deterministic per-map feature vector.

Contract section 27's closing item for M2, serving 7.1-7.4 and 5.4's
"line-of-sight, cover, chokepoint, loop, verticality and route redundancy
descriptors".

Five halves:

  * IDENTITY - the eye is the engine's eye and the sight mask is what blocks a
    shot, both read out of the game's own source;

  * STATIC - not one float leaves the interface, nothing is sampled by a
    generator, and the module holds no global state. Contract section 7
    requires stable integer bins, and a feature that drifted in its last bits
    would make two Training runs disagree about a map neither changed;

  * REFERENCE - the C and an independently written Python computation must
    agree exactly on real maps;

  * REAL - all 132 shipped maps produce a vector, and every arithmetic
    relationship the vector claims about itself holds on every one of them;

  * DETERMINISM - the same map twice, and eight threads at once.

Run: python tools/check_mapgen_features_contract.py
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
sys.path.insert(0, str(REPO / "tools"))

import mapgen_features_oracle as features  # noqa: E402

# The one rule for what belongs to the fixed corpus; see mapgen_corpus.py.
from mapgen_corpus import is_generated  # noqa: E402

HEADER = REPO / "inc" / "common" / "mapgen_features.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_features.c"
DRIVER = REPO / "tools" / "mapgen_features_test_driver.c"
PARTS = [
    REPO / "src" / "mapgen" / "mapgen_wiring.c",
    REPO / "src" / "mapgen" / "mapgen_space.c",
    REPO / "src" / "mapgen" / "mapgen_trace.c",
    REPO / "src" / "mapgen" / "mapgen_genome.c",
    REPO / "src" / "mapgen" / "mapgen_bsp.c",
]
PMOVE = REPO / "src" / "common" / "pmove" / "template.c"
SHARED = REPO / "inc" / "shared" / "shared.h"

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
]

# Chosen for what they reach, not for size. `redyard` is the smallest map with
# liquid; `rcdm17` the smallest with a ducked stance; `ztn2dm1` is the only
# small map whose depth-first search has a ROOT with two children, which is the
# one branch of the articulation-point rule the others never execute.
REFERENCE_MAPS = ["2box4.bsp", "redyard.bsp", "rcdm17.bsp", "ztn2dm1.bsp"]

# `2box4` has 12 entities with two stances exactly equidistant from them. The
# vector carries only COUNTS, so the tie-break rule is observable nowhere
# except in the binding list itself.
BINDING_MAPS = ["2box4.bsp", "lbrdm1.bsp"]

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


def header_int(hdr: str, name: str) -> int | None:
    m = re.search(rf"^#define {name}\s+\(?(-?\d+)\)?\s*$", hdr, re.MULTILINE)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------


def test_identity() -> None:
    head("identity: the eye and what blocks it")
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    pmove = PMOVE.read_text(encoding="utf-8", errors="replace")
    shared = SHARED.read_text(encoding="utf-8", errors="replace")

    m = re.search(r"pm->viewheight = (\d+);", pmove)
    engine_view = int(m.group(1)) if m else None
    check(
        "MAPGEN_FEATURES_VIEWHEIGHT is the engine's standing view height",
        header_int(hdr, "MAPGEN_FEATURES_VIEWHEIGHT") == engine_view,
        f"engine {engine_view}, header {header_int(hdr, 'MAPGEN_FEATURES_VIEWHEIGHT')}",
    )
    # The whole argument, not a prefix of it: adding another bit on the next
    # line would leave a substring test perfectly satisfied.
    check(
        "a sight line is stopped by solid and by window, and nothing else",
        "MAPGEN_TRACE_SOLID | MAPGEN_TRACE_WINDOW, &tr);" in src
        and "#define CONTENTS_WINDOW" in shared,
        "water does not block a shot, and a playerclip is not a wall to a bullet",
    )
    check(
        "the sight line is a point trace",
        "static const float zero[3] = { 0.0f, 0.0f, 0.0f };" in src,
        "a player's eye is a point, not a box",
    )


def test_static() -> None:
    head("static: integers, arithmetic sampling, no state")
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))

    vector = hdr[hdr.find("typedef struct {"):hdr.find("} mapgen_features_vector_t;")]
    check(
        "not one float leaves the interface",
        "float" not in vector and "double" not in vector,
        "contract 7: stable integer/fixed-point bins",
    )
    check(
        "the vector is named fields, not an array",
        vector.count(";") > 20 and "[MAPGEN" in vector,
        "a feature that can only be read by index is one nobody can check",
    )

    check(
        "nothing is sampled by a generator",
        not re.search(r"\b(rand|srand|random|time|clock|GetTickCount)\s*\(", src),
        "a feature chosen by an RNG is not one two runs can compare",
    )
    check(
        "the sample is chosen by stride arithmetic",
        "observer_stride" in src and "partner_stride" in src,
        "",
    )
    check(
        "the counts the ratios are OF are reported too",
        "sight_pairs" in src and "sight_open" in src,
        "a ratio without its denominator cannot be judged",
    )

    file_statics = [
        m.group(0).strip()
        for m in re.finditer(r"^static\s+[^;(){}]*;", src, re.MULTILINE)
        if "const" not in m.group(0)
    ]
    check("no mutable file-scope state", not file_statics, f"{file_statics[:3]}")

    check(
        "height bands use floor division",
        "floor_div" in src and "value % divisor != 0" in src,
        "truncation towards zero makes the band across z=0 twice as tall",
    )
    check(
        "a symmetric connection becomes one undirected edge",
        "e->from > e->to" in src,
        "counting it twice inflates the cyclomatic number and hides every bridge",
    )
    check(
        "the lowpoint walk is iterative",
        "cursor[top]" in src and "while (true)" in src,
        "a component with 25000 stances is deeper than any stack wants",
    )
    check(
        "an entity binds only inside a stated radius",
        "MAPGEN_FEATURES_BIND_RADIUS_XY" in src and "MAPGEN_FEATURES_BIND_RADIUS_Z" in src,
        "a 'nearest' stance 900 units away is an answer that means nothing",
    )
    check(
        "the square root is integer",
        "isqrt32" in src and "math.h" not in src,
        "a length must not depend on which libm was linked",
    )
    # The rule protects the PO's binary, not the generator: a module the
    # packaged helper runs has to be linked somewhere, and mapgen_src is the
    # somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_features.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("features.exe" if os.name == "nt" else "features")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), *[str(x) for x in PARTS], "-o", str(exe)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def run(exe: Path, *args: str) -> str:
    p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=900)
    return p.stdout


def find_map(name: str) -> Path | None:
    for root in MAP_ROOTS:
        if (root / name).exists():
            return root / name
    return None


def corpus() -> list[Path]:
    return [p for root in MAP_ROOTS if root.is_dir() for p in sorted(root.glob("*.bsp"))
            # The generator publishes into this directory under contract 22's
            # reserved `q2mg_` basename. Those are legal training input but they are
            # not part of the fixed corpus these checks count, and a count that moves
            # every time somebody generates a map is not a count.
            if not is_generated(p.name)]


def test_reference(exe: Path) -> None:
    head("reference: two independent computations")
    for name in REFERENCE_MAPS:
        path = find_map(name)
        if not check(f"{name} is available", path is not None, ""):
            continue
        assert path is not None
        py = features.canonical_text(features.build(path))
        c = run(exe, "text", str(path))
        if c == py:
            check(f"{name}: the two vectors are identical", True, "")
            continue
        cl, pl = c.splitlines(), py.splitlines()
        diffs = [f"C={cl[i] if i < len(cl) else '<eof>'} "
                 f"py={pl[i] if i < len(pl) else '<eof>'}"
                 for i in range(max(len(cl), len(pl)))
                 if (cl[i] if i < len(cl) else None) != (pl[i] if i < len(pl) else None)]
        check(f"{name}: the two vectors are identical", False, "; ".join(diffs[:4]))


def test_bindings(exe: Path) -> None:
    """Which stance each entity stands on, which the vector cannot show."""
    head("bindings: the stance under each entity")
    for name in BINDING_MAPS:
        path = find_map(name)
        if not check(f"{name} is available", path is not None, ""):
            continue
        assert path is not None
        py = [f"{cls} {node}" for cls, node in features.bindings(path)]
        c = [ln for ln in run(exe, "bindings", str(path)).splitlines() if ln]
        if c == py:
            check(f"{name}: the two agree on which stance each entity stands on",
                  True, f"{len(py)} entities")
            continue
        diffs = [f"C={c[i] if i < len(c) else '<eof>'} py={py[i] if i < len(py) else '<eof>'}"
                 for i in range(max(len(c), len(py)))
                 if (c[i] if i < len(c) else None) != (py[i] if i < len(py) else None)]
        check(f"{name}: the two agree on which stance each entity stands on",
              False, f"{len(diffs)} differ: {diffs[:3]}")


def parse_vector(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, val = line.partition("=")
            try:
                out[k] = int(val)
            except ValueError:
                pass
    return out


def test_real(exe: Path) -> list[Path]:
    head("real: every shipped map, and what the vector claims about itself")
    maps = corpus()
    if not check("real maps are available", len(maps) >= 100, f"found {len(maps)}"):
        return []

    failures: list[str] = []
    broken: dict[str, list[str]] = {}

    def violate(rule: str, where: str) -> None:
        broken.setdefault(rule, []).append(where)

    for path in maps:
        v = parse_vector(run(exe, "text", str(path)))
        if "nodes" not in v:
            failures.append(path.name)
            continue

        for key in v:
            if key.endswith("_permille") and not 0 <= v[key] <= 1000:
                violate("every permille is between 0 and 1000", f"{path.name}:{key}={v[key]}")
        if v["sight_open"] > v["sight_pairs"]:
            violate("no more pairs can see than were sampled", path.name)
        if v["sight_pairs"]:
            expected = 1000 - v["sight_open"] * 1000 // v["sight_pairs"]
            if v["cover_permille"] != expected:
                violate("cover follows from the sample it names", path.name)
        if v["mean_sight_length"] > v["max_sight_length"]:
            violate("the mean sight line is no longer than the longest", path.name)
        if v["bound_entities"] + v["unbound_entities"] != v["positioned_entities"]:
            violate("every positioned entity is either bound or not", path.name)
        if v["items_bound"] + v["items_unbound"] > v["positioned_entities"]:
            violate("items are a subset of the positioned entities", path.name)
        if v["chokepoints"] > v["nodes"]:
            violate("there are no more chokepoints than stances", path.name)
        if v["liquid_nodes"] > v["nodes"] or v["hazard_nodes"] > v["nodes"]:
            violate("liquid and hazard stances are a subset of all stances", path.name)
        if v["largest_region_nodes"] > v["nodes"]:
            violate("the largest region is no bigger than the map", path.name)
        if v["regions"] and not v["largest_region_nodes"]:
            violate("a map with regions has a largest one", path.name)
        if v["vertical_span"] != v["extent_z"]:
            violate("the vertical span is the z extent", path.name)
        if v["edges"] != sum(v[f"edges_{k}"] for k in
                             ("walk", "step", "jump", "fall", "swim")):
            violate("the edge kinds account for every edge", path.name)

    check("every map produced a vector", not failures, "; ".join(failures[:4]))
    for rule in (
        "every permille is between 0 and 1000",
        "no more pairs can see than were sampled",
        "cover follows from the sample it names",
        "the mean sight line is no longer than the longest",
        "every positioned entity is either bound or not",
        "items are a subset of the positioned entities",
        "there are no more chokepoints than stances",
        "liquid and hazard stances are a subset of all stances",
        "the largest region is no bigger than the map",
        "a map with regions has a largest one",
        "the vertical span is the z extent",
        "the edge kinds account for every edge",
    ):
        offenders = broken.get(rule, [])
        check(rule, not offenders, f"{len(offenders)}: {offenders[:3]}")
    return maps


def test_discrimination(exe: Path, maps: list[Path]) -> None:
    """A feature that is the same for every map has learned nothing."""
    head("discrimination: the vector actually distinguishes maps")
    if not maps:
        return
    vectors = [parse_vector(run(exe, "text", str(p))) for p in maps[::4]]
    vectors = [v for v in vectors if "nodes" in v]
    if not check("vectors were collected", len(vectors) >= 20, f"{len(vectors)}"):
        return

    constant = [k for k in vectors[0]
                if len({v.get(k) for v in vectors}) == 1
                and k not in ("sight_pairs", "edges_swim", "hazard_nodes",
                              "hazard_permille", "liquid_nodes", "items_unbound",
                              "spawns_unbound")]
    check(
        "no feature is the same for every map",
        not constant,
        f"constant across {len(vectors)} maps: {constant}",
    )
    digests = {run(exe, "digest", str(p)).split()[1] for p in maps[::4]
               if run(exe, "digest", str(p)).startswith("OK ")}
    check(
        "different maps get different vectors",
        len(digests) >= len(vectors) - 2,
        f"{len(digests)} distinct digests for {len(vectors)} maps",
    )


def test_determinism(exe: Path, maps: list[Path]) -> None:
    head("determinism: twice, and on eight threads at once")
    if not maps:
        return
    for path in (maps[0], maps[len(maps) // 2], maps[-1]):
        out = run(exe, "stable", str(path)).strip()
        check(f"{path.name}: two computations give the same digest",
              out.startswith("STABLE"), out[:120])
    for path in (maps[0], maps[len(maps) // 2]):
        out = run(exe, "threads", str(path), "8").strip()
        check(f"{path.name}: eight concurrent computations are identical",
              out.startswith("IDENTICAL"), out[:120])


def main() -> int:
    print("=== MAPGEN-1 M2 MapGenFeatures contract")
    test_identity()
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_features_") as td:
        work = Path(td)
        head("building")
        exe = build(cc, work)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_reference(exe)
        test_bindings(exe)
        maps = test_real(exe)
        test_discrimination(exe, maps)
        test_determinism(exe, maps)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
