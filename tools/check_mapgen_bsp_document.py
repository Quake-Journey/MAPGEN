#!/usr/bin/env python3
"""MAPGEN-1 M2 - the headless BspDocument.

The Codex activation review of 2026-08-31 required a headless `USE_REF=0`
parser proving worker independence, plus semantic parity against an
independent reading of the same files. This is that proof.

Three halves:

  * STATIC - the document is genuinely independent: it never mentions
    `USE_REF`, includes no engine header, touches no global, and validates
    every count against a ceiling BEFORE allocating;

  * PARITY - the compiled C document and the Python oracle read all 132 real
    shipped Quake II maps and must produce the IDENTICAL canonical digest.
    Neither of us wrote the BSP format; two independent readers agreeing on
    every real map is the only evidence either is right. A single disagreement
    is a finding about one of them, not a rounding difference - the two share a
    deliberately identical float and hash algorithm so a tie cannot manufacture
    one;

  * STRICTNESS - malformed and hostile files are refused with a stable code
    rather than crashing, including the ones that only differ from a valid
    file by one field.

Run: python tools/check_mapgen_bsp_document.py
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_bsp_synth as synth  # noqa: E402

# The one rule for what belongs to the fixed corpus; see mapgen_corpus.py.
from mapgen_corpus import is_generated  # noqa: E402

HEADER = REPO / "inc" / "common" / "mapgen_bsp.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_bsp.c"
DRIVER = REPO / "tools" / "mapgen_bsp_test_driver.c"

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
    head("static: the document owes the renderer nothing")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    check(
        "the document never mentions USE_REF",
        "USE_REF" not in src and "USE_REF" not in hdr,
        "a renderer-conditioned reader is exactly what this replaces",
    )
    check(
        "it includes no engine header",
        not re.search(r'#include\s+"(?!common/mapgen_bsp\.h)', src),
        "",
    )
    check(
        "it carries the texture axes the gated struct would hide",
        "float   axis[2][4];" in hdr,
        "mtexinfo_t keeps axis/offset behind USE_REF; Training reads them",
    )
    check(
        "it holds no global state",
        not re.search(r"^static\s+(?!const\b)(?!void\b)(?!bool\b)(?!uint)(?!int)(?!float)(?!size_t)\w+\s+\w+\s*(=|;)",
                      src, re.MULTILINE)
        and "static mapgen_bsp_t" not in src,
        "BSP_Load's global cache is why Training cannot use it concurrently",
    )
    check(
        "one arena per load",
        src.count("bsp->arena = calloc") == 1 and src.count("free(bsp->arena)") == 1,
        "a load either succeeds wholly or frees exactly one block",
    )

    # The ordering is the promise: a file must not be able to make this reader
    # allocate on the strength of a number it supplied.
    limit_at = src.find("count > table[i].limit")
    alloc_at = src.find("bsp->arena = calloc")
    check(
        "every count is checked against a ceiling BEFORE any allocation",
        0 <= limit_at < alloc_at,
        f"limit check at {limit_at}, allocation at {alloc_at}",
    )
    check(
        "lump bounds are summed in 64 bits",
        "(uint64_t)ofs + (uint64_t)len > (uint64_t)size" in src,
        "a 32-bit sum lets a huge length wrap back into range",
    )
    check(
        "odd lump sizes are refused",
        "MAPGEN_BSP_ERR_LUMP_ODD_SIZE" in src and "len % table[i].size" in src,
        "",
    )
    check(
        "MAX_MAP_AREAS stays at 256 even for QBSP",
        "#define MAPGEN_BSP_MAX_AREAS        256u" in hdr,
        "this limit is network-visible and is never raised (contract 18.1)",
    )
    check(
        "texture names are bounded and sanitized",
        "ti->texture[MAPGEN_BSP_TEXNAME] = '\\0';" in src
        and "ti->texture[c] = '?';" in src,
        "an untrusted name reaches a log, a UI and a compiler command line",
    )
    check(
        "the entity string is cut at the first NUL and terminated",
        "bsp->entities[used] = '\\0';" in src,
        "an embedded NUL would truncate it for one consumer and not another",
    )
    check(
        "indices are validated after parsing",
        src.count("MAPGEN_BSP_ERR_BAD_INDEX") >= 8,
        "a bad index must be an error, not a crash during a later walk",
    )
    check(
        "a submodel headnode may be a leaf reference",
        "-(leaf + 1)" in SOURCE.read_text(encoding="utf-8")
        and "} else if ((uint32_t)(-1 - hn) >= bsp->num_leafs) {" in src,
        "real shipped maps encode single-leaf submodels this way",
    )
    check(
        "the tree walk is bounded",
        "guard <= b->num_nodes" in src,
        "a cyclic tree must be an error rather than a hang",
    )
    check(
        "float text is written without printf",
        "fmt_float" in src and '"%f"' not in src and '"%.6f"' not in src,
        "a locale that uses a comma would change the digest (contract 10)",
    )


def build(cc: str, out: Path, extra: list[str] | None = None) -> Path | None:
    exe = out / ("bspdoc.exe" if os.name == "nt" else "bspdoc")
    cmd = [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc")]
    cmd += extra or []
    cmd += [str(DRIVER), str(SOURCE), "-o", str(exe)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def run(exe: Path, *args: str) -> str:
    p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=300)
    return p.stdout.strip()


def test_parity(exe: Path) -> None:
    head("parity: two independent readers, every real map")
    maps = [p for root in MAP_ROOTS if root.is_dir() for p in sorted(root.glob("*.bsp"))
            # The generator publishes into this directory under contract 22's
            # reserved `q2mg_` basename. Those are legal training input but they are
            # not part of the fixed corpus these checks count, and a count that moves
            # every time somebody generates a map is not a count.
            if not is_generated(p.name)]
    if not check("real maps are available", len(maps) >= 100, f"found {len(maps)}"):
        return

    mismatches: list[str] = []
    c_errors: list[str] = []
    compared = 0
    for path in maps:
        out = run(exe, "digest", str(path))
        if not out.startswith("OK "):
            c_errors.append(f"{path.name}: {out}")
            continue
        parts = out.split()
        c_digest = parts[1]
        try:
            bsp = oracle.load(path)
            py_digest = "%016x" % bsp.canonical_digest()
        except Exception as exc:  # noqa: BLE001
            mismatches.append(f"{path.name}: python raised {type(exc).__name__}: {exc}")
            continue
        compared += 1
        if c_digest != py_digest:
            mismatches.append(f"{path.name}: C={c_digest} py={py_digest}")

    check(
        f"the C document loads all {len(maps)} shipped maps",
        not c_errors,
        "; ".join(c_errors[:4]),
    )
    check(
        f"both readers agree on the canonical digest for all {compared} maps",
        not mismatches and compared >= 100,
        "; ".join(mismatches[:4]) or f"compared {compared}",
    )

    # Counts, not just the digest: a digest that happened to collide would
    # still have to agree on every count.
    sample = next((p for p in maps if p.name == "aerowalk.bsp"), maps[0])
    parts = run(exe, "digest", str(sample)).split()
    bsp = oracle.load(sample)
    want = [
        len(bsp.planes), len(bsp.nodes), len(bsp.leafs), len(bsp.leafbrushes),
    ]
    got = [int(x) for x in parts[2:6]]
    check(f"{sample.name}: counts agree", want == got, f"py={want} C={got}")

    head("parity: the same point classification")
    disagreements = 0
    checked = 0
    for ent in bsp.entities():
        if ent.get("classname", "").startswith(("info_player", "item_", "weapon_")) and "origin" in ent:
            x, y, z = (float(v) for v in ent["origin"].split())
            py = bsp.point_contents((x, y, z + 1))
            c = int(run(exe, "point", str(sample), str(x), str(y), str(z + 1)))
            checked += 1
            if py != c:
                disagreements += 1
    check(
        f"point contents agree at {checked} real spawn/item points",
        checked >= 10 and disagreements == 0,
        f"{disagreements} disagreements",
    )


def test_plane_ties(exe: Path) -> None:
    """The tie-break the parity check could never see.

    Both readers descend the tree for a point query, and both used to send a
    point that lands EXACTLY on a node plane to the back child. The engine
    sends it to the front (`BSP_PointLeaf`, src/common/bsp.c:1127-1136). Two
    implementations sharing a wrong assumption agree perfectly, so this is
    checked against the ENGINE'S SOURCE, and then exercised on points that are
    on a plane by construction - 4.5% of real player stances are.
    """
    head("identity: the point descent is the engine's, not a plausible one")

    engine = (REPO / "src" / "common" / "bsp.c").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"BSP_PointLeaf\(const mnode_t \*node, const vec3_t p\)\s*\{(.*?)\n\}",
                  engine, re.DOTALL)
    body = m.group(1) if m else ""
    check("the engine's point descent was readable", bool(body), "BSP_PointLeaf not found")
    check(
        "the engine sends a point ON the plane to the front child",
        "node->children[d < 0]" in body,
        f"engine body: {body.strip()[:200]}",
    )

    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    check(
        "the document uses that same tie-break",
        "num = n->children[d < 0];" in src,
        "`d > 0 ? 0 : 1` sends an on-plane point to the BACK, which is a "
        "different leaf 100% of the time it happens",
    )

    maps = [p for root in MAP_ROOTS if root.is_dir() for p in sorted(root.glob("*.bsp"))
            if not is_generated(p.name)]
    if not maps:
        return

    tied = 0
    disagreements: list[str] = []
    for path in maps[:6]:
        bsp = oracle.load(path)
        for node in bsp.nodes[:4000]:
            plane = bsp.planes[node.planenum]
            if plane.type >= 3:
                continue           # only axial planes give an EXACT point
            axis = plane.type
            pt = [
                (node.mins[0] + node.maxs[0]) // 2,
                (node.mins[1] + node.maxs[1]) // 2,
                (node.mins[2] + node.maxs[2]) // 2,
            ]
            pt[axis] = plane.dist
            if abs(pt[axis]) > 1e6 or pt[axis] != int(pt[axis]):
                continue
            point = tuple(float(v) for v in pt)
            tied += 1
            py = bsp.point_contents(point)
            got = int(run(exe, "point", str(path),
                          str(point[0]), str(point[1]), str(point[2])))
            if py != got:
                disagreements.append(f"{path.name} {point} py={py} C={got}")
            if tied >= 400:
                break
        if tied >= 400:
            break

    check("points exactly on a node plane were actually tested", tied >= 100, f"{tied}")
    check(
        "on-plane points classify the same in both readers",
        not disagreements,
        f"{len(disagreements)}: {disagreements[:3]}",
    )


def test_strictness(exe: Path, out: Path) -> None:
    head("strictness: malformed and hostile files")
    good = synth.synth_solid_cube()

    def probe(name: str, blob: bytes) -> str:
        p = out / f"{name}.bsp"
        p.write_bytes(blob)
        return run(exe, "digest", str(p))

    check("a valid synthesized map loads", probe("good", good).startswith("OK "), "")
    check("an empty file is TOO_SMALL", probe("empty", b"") == "TOO_SMALL", "")
    check("a 4-byte file is TOO_SMALL", probe("tiny", b"IBSP") == "TOO_SMALL", "")

    bad_ident = bytearray(good)
    bad_ident[0:4] = b"XBSP"
    check("a wrong ident is BAD_IDENT", probe("ident", bytes(bad_ident)) == "BAD_IDENT", "")

    bad_ver = bytearray(good)
    bad_ver[4:8] = (37).to_bytes(4, "little")
    check("a wrong version is BAD_VERSION", probe("ver", bytes(bad_ver)) == "BAD_VERSION", "")

    oob = bytearray(good)
    off = 8 + oracle.LUMP_LIGHTING * 8 + 4
    oob[off:off + 4] = (len(good) * 4).to_bytes(4, "little")
    check("a lump past EOF is LUMP_OUT_OF_BOUNDS",
          probe("oob", bytes(oob)) == "LUMP_OUT_OF_BOUNDS", "")

    wrap = bytearray(good)
    off = 8 + oracle.LUMP_PLANES * 8
    wrap[off:off + 4] = (0xFFFFFFF0).to_bytes(4, "little")
    wrap[off + 4:off + 8] = (0x20).to_bytes(4, "little")
    check("an offset+length that would wrap 32 bits is refused",
          probe("wrap", bytes(wrap)) == "LUMP_OUT_OF_BOUNDS",
          "a 32-bit sum here would wrap back into range")

    odd = bytearray(good)
    off = 8 + oracle.LUMP_PLANES * 8 + 4
    odd[off:off + 4] = (21).to_bytes(4, "little")
    check("a lump with an odd size is LUMP_ODD_SIZE",
          probe("odd", bytes(odd)) == "LUMP_ODD_SIZE", "")

    no_models = bytearray(good)
    off = 8 + oracle.LUMP_MODELS * 8 + 4
    no_models[off:off + 4] = (0).to_bytes(4, "little")
    check("a file with no models is NO_MODELS",
          probe("nomodels", bytes(no_models)) == "NO_MODELS", "")

    bad_leafbrush = bytearray(good)
    off = 8 + oracle.LUMP_LEAFBRUSHES * 8 + 4
    bad_leafbrush[off:off + 4] = (0).to_bytes(4, "little")
    check("a leaf pointing at leafbrushes that do not exist is BAD_INDEX",
          probe("leafbrush", bytes(bad_leafbrush)) == "BAD_INDEX", "")

    # A control byte in a texture name: it must never survive to a log, a UI
    # or a compiler command line, and BOTH readers must agree on what it
    # became. No real map has one, so only a crafted file proves the rule.
    dirty = bytearray(good)
    ti_off = int.from_bytes(dirty[8 + oracle.LUMP_TEXINFO * 8 : 12 + oracle.LUMP_TEXINFO * 8], "little")
    dirty[ti_off + 40] = 0x07          # BEL, inside the texture name field
    p_dirty = out / "dirtytexture.bsp"
    p_dirty.write_bytes(bytes(dirty))
    c_text = subprocess.run([str(exe), "text", str(p_dirty)], capture_output=True, text=True,
                            timeout=120).stdout
    py_text = oracle.load(p_dirty).canonical_text()
    check(
        "a control byte in a texture name is replaced",
        "" not in c_text and "tex=?" in c_text,
        f"C text still carries the raw byte: {c_text[:0]!r}",
    )
    check(
        "both readers sanitize it the same way",
        c_text == py_text,
        "a difference here is a difference in hygiene, not in parsing",
    )

    truncated = good[: len(good) // 2]
    result = probe("trunc", truncated)
    check("a truncated file is refused", result != "OK" and not result.startswith("OK "), result)

    # A fuzzing sweep: random mutation must never produce a crash, only an
    # error or a load the reader is prepared to stand behind.
    import random

    rng = random.Random(20260831)
    crashes = 0
    for i in range(400):
        blob = bytearray(good)
        for _ in range(rng.randint(1, 8)):
            blob[rng.randrange(len(blob))] = rng.randrange(256)
        p = out / "fuzz.bsp"
        p.write_bytes(bytes(blob))
        proc = subprocess.run([str(exe), "digest", str(p)], capture_output=True, text=True, timeout=60)
        if proc.returncode not in (0, 1) or not proc.stdout.strip():
            crashes += 1
            break
    check("400 mutated files never crash the reader", crashes == 0, "")


def test_use_ref_independence(cc: str, out: Path) -> None:
    head("independence: the same answers with USE_REF forced either way")
    results = {}
    for flag in ("-DUSE_REF=0", "-DUSE_REF=1"):
        exe = build(cc, out, [flag])
        if not check(f"the document compiles with {flag}", exe is not None, ""):
            return
        assert exe is not None
        sample = next(
            (p for root in MAP_ROOTS if root.is_dir()
             for p in sorted(root.glob("*.bsp"))
             if not is_generated(p.name)),
            None,
        )
        if sample is None:
            check("a map is available for the independence check", False, "")
            return
        results[flag] = run(exe, "digest", str(sample))
    check(
        "USE_REF changes nothing about the result",
        results.get("-DUSE_REF=0") == results.get("-DUSE_REF=1")
        and results.get("-DUSE_REF=0", "").startswith("OK "),
        f"{results}",
    )


def main() -> int:
    print("=== MAPGEN-1 BspDocument")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_bsp_") as td:
        out = Path(td)
        head("building the document")
        exe = build(cc, out)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None

        test_parity(exe)
        test_plane_ties(exe)
        test_strictness(exe, out)
        test_use_ref_independence(cc, out)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
