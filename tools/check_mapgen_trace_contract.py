#!/usr/bin/env python3
"""MAPGEN-1 M2 - MapGenTraceContext, reentrant player-hull tracing.

The claim this guard has to establish is narrow and unusual: the tracer gives
the same answers as an independently written reference, AND gives them from
many threads at once. The second half is the reason the module exists, since
`CM_BoxTrace` cannot make that promise - it keeps its traversal in file-scope
scratch (`src/common/cmodel.c:448-455`) and stamps brushes against a global
counter (`:38`).

Four halves, then:

  * STATIC   - no file-scope mutable state, the stamp belongs to the context,
               the mask is the ENGINE's mask rather than a plausible one, and
               the engine's collision code is neither called nor copied in;
  * REFERENCE- every one of the shipped maps, traced by the C module and by
               tools/mapgen_trace_oracle.py, must agree EXACTLY. Both read the
               same ray file and both work in float32, so a disagreement can
               only be about the algorithm. The reference is also run in
               double, which is how a ray whose answer is decided by rounding
               rather than by geometry identifies itself - see the oracle's
               header for the ray on kaktus.bsp that made this necessary;
  * PARALLEL - the same rays on many threads must reproduce the single-threaded
               answers exactly, and two contexts on two different documents,
               interleaved, must not see each other;
  * EDGES    - null and unbound contexts are refused rather than trusted.

Contract section 18.3.

Run: python tools/check_mapgen_trace_contract.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import mapgen_bsp_oracle as oracle  # noqa: E402
import mapgen_trace_oracle as tracer  # noqa: E402

# The one rule for what belongs to the fixed corpus; see mapgen_corpus.py.
from mapgen_corpus import is_generated  # noqa: E402

HEADER = REPO / "inc" / "common" / "mapgen_trace.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_trace.c"
DRIVER = REPO / "tools" / "mapgen_trace_test_driver.c"
BSPDOC = REPO / "src" / "mapgen" / "mapgen_bsp.c"
SHARED = REPO / "inc" / "shared" / "shared.h"

MAP_ROOTS = [
    Path(r"O:\Claude2\q2pro-release\baseq2\maps"),
    Path(r"O:\Claude2\q2pro-release\action\maps"),
]

RAYS_PER_MAP = 200
GRAZING_PER_MAP = 40
RAY_SEED = 777

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
    head("static: every byte of traversal state belongs to the caller")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    # A file-scope `static` variable is exactly the defect that makes the
    # engine's tracer unusable here. Functions are fine; variables are not, so
    # the pattern excludes anything with a parameter list.
    bad_statics = [
        m.group(0).strip()
        for m in re.finditer(r"^static\s+[^;(){}]*;", src, re.MULTILINE)
    ]
    check(
        "the tracer keeps no file-scope mutable state",
        not bad_statics,
        f"found {bad_statics[:3]}; that is the very defect this module exists to avoid",
    )

    # A `static` inside a function body is shared between threads exactly like
    # a file-scope one, and slips past a rule anchored at column zero.
    local_statics = [
        m.group(0).strip()
        for m in re.finditer(r"^[ \t]+static\s+[^;{]*;", src, re.MULTILINE)
    ]
    check(
        "the tracer keeps no state in a function-local static",
        not local_statics,
        f"found {local_statics[:3]}; indented does not mean per-thread",
    )

    check(
        "the brush stamp is written into the context, not into the brush",
        "s->ctx->stamps[brushnum] = s->ctx->generation;" in src,
        "a stamp stored in the brush is shared between threads",
    )
    check(
        "the stamp is also READ from the context",
        "s->ctx->stamps[brushnum] == s->ctx->generation" in src,
        "",
    )
    check(
        "no checkcount anywhere",
        "checkcount" not in src,
        "the engine's global stamp must not be reachable from here",
    )
    check(
        "a wrapping generation clears the stamps rather than hoping",
        "if (ctx->generation == 0) {" in src and "memset(ctx->stamps, 0," in src,
        "2^32 traces is a number a Training run can reach",
    )
    check(
        "the stamp index is bounded by the context's own capacity",
        "if (brushnum >= s->ctx->capacity)" in src,
        "a document with more brushes than the array would write past it",
    )

    check(
        "the engine's collision code is not called",
        not re.search(r"\bCM_[A-Za-z_]+\s*\(", src),
        "MapValidator must not reach into cmodel.c's static workspace",
    )
    check(
        "the engine's collision header is not included",
        "cmodel.h" not in src and "cmodel.h" not in hdr,
        "",
    )
    check(
        "the module is headless",
        "USE_REF" not in src and "refresh" not in src,
        "it runs on the Training threads, where there is no renderer",
    )

    check(
        "the sweep uses the engine's own epsilon",
        "#define DIST_EPSILON  (0.03125f)" in src,
        "a different epsilon means different answers from the game",
    )
    ceilings = len(re.findall(r"depth > 1024\)", src))
    check(
        "both traversals have a depth ceiling",
        ceilings >= 2,
        f"found {ceilings}; a malformed tree must not become a hang",
    )
    check(
        "the box sweep and the position test are separate paths",
        "position_test" in src and "test_box_in_brush" in src,
        "a zero-length sweep is a containment question, not a sweep",
    )

    # The mask is an IDENTITY claim: it must be the engine's mask, not a
    # plausible one. Read the engine's own bits and compare.
    shared = SHARED.read_text(encoding="utf-8", errors="replace")
    bits = {}
    for name in ("SOLID", "WINDOW", "PLAYERCLIP", "MONSTER", "LAVA", "SLIME", "WATER"):
        m = re.search(rf"^#define CONTENTS_{name}\s+BIT\((\d+)\)", shared, re.MULTILINE)
        if m:
            bits[name] = 1 << int(m.group(1))
    check("the engine's contents bits were readable", len(bits) == 7, str(sorted(bits)))

    for name, value in bits.items():
        m = re.search(rf"^#define MAPGEN_TRACE_{name}\s+(0x[0-9a-fA-F]+)", hdr, re.MULTILINE)
        got = int(m.group(1), 16) if m else None
        check(
            f"MAPGEN_TRACE_{name} is the engine's bit",
            got == value,
            f"engine {value:#x}, mapgen {got if got is None else hex(got)}",
        )

    engine_mask = bits.get("SOLID", 0) | bits.get("PLAYERCLIP", 0) | \
        bits.get("WINDOW", 0) | bits.get("MONSTER", 0)
    check(
        "the reference's player mask is the engine's MASK_PLAYERSOLID",
        tracer.MASK_PLAYERSOLID == engine_mask,
        f"engine {engine_mask:#x}, reference {tracer.MASK_PLAYERSOLID:#x}",
    )
    check(
        "MAPGEN_MASK_PLAYERSOLID is defined after the bits it uses",
        hdr.index("#define MAPGEN_TRACE_MONSTER") < hdr.index("#define MAPGEN_MASK_PLAYERSOLID"),
        "valid C either way, but a reader must not have to know that",
    )

    # The reentrant POINT trace already in the engine must be reused, not
    # reimplemented; the review was explicit about it.
    check(
        "the point query delegates rather than reimplementing a traversal",
        "return MapGenBsp_PointContents(ctx->bsp, point);" in src,
        "",
    )


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("trace.exe" if os.name == "nt" else "trace")
    p = subprocess.run(
        [cc, "-std=c17", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), str(BSPDOC), "-o", str(exe)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def run(exe: Path, *args: str) -> str:
    p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=600)
    return p.stdout.strip()


def materially_differs(a: tuple, b: tuple) -> bool:
    """Do two answers differ in a way a reachability decision would notice?

    Comparing float32 against double at full precision would flag half the
    corpus, because of course the last bits differ. What matters is whether
    the ANSWER changed: a different verdict on solidity, a different brush, or
    a hit somewhere else entirely.
    """
    return (a[1] != b[1] or a[2] != b[2] or a[3] != b[3] or a[4] != b[4]
            or abs(a[0] - b[0]) > 1e-4)


def corpus() -> list[Path]:
    return [p for root in MAP_ROOTS if root.is_dir() for p in sorted(root.glob("*.bsp"))
            # The generator publishes into this directory under contract 22's
            # reserved `q2mg_` basename. Those are legal training input but they are
            # not part of the fixed corpus these checks count, and a count that moves
            # every time somebody generates a map is not a count.
            if not is_generated(p.name)]


def test_reference(exe: Path, work: Path) -> list[Path]:
    head("reference: two independent implementations on the shipped maps")
    maps = corpus()
    if not check("real maps are available", len(maps) >= 100, f"found {len(maps)}"):
        return []

    rayfile = work / "rays.txt"
    load_failures: list[str] = []
    shape_failures: list[str] = []
    exact_diffs: list[str] = []      # C disagrees with the float32 reference
    precision_rays: list[str] = []   # float32 and double disagree with each other
    compared = 0
    traced_maps = 0
    grazing_total = 0
    negative_entry = 0

    for path in maps:
        try:
            bsp = oracle.load(path)
        except Exception as exc:  # noqa: BLE001
            load_failures.append(f"{path.name}: {exc}")
            continue
        if not bsp.models:
            continue

        grazing = tracer.generate_grazing_rays(bsp, GRAZING_PER_MAP)
        grazing_total += len(grazing)
        rays = tracer.generate_rays(bsp, RAY_SEED, RAYS_PER_MAP) + grazing
        tracer.write_rays(rays, rayfile)
        out = run(exe, "trace", str(path), str(rayfile))
        lines = [ln.split() for ln in out.splitlines() if ln]
        if len(lines) != len(rays):
            shape_failures.append(
                f"{path.name}: {len(lines)} lines for {len(rays)} rays :: {out[:120]}")
            continue
        traced_maps += 1

        for i, (start, end, mins, maxs, mask) in enumerate(rays):
            c = lines[i]
            # The driver prints floats with %.9g, which round-trips a float32
            # exactly - but only back THROUGH float32. Parsing to a double and
            # comparing would fail on every single ray for no reason at all.
            got = (tracer.f32(float(c[1])), int(c[2]), int(c[3]),
                   int(c[4]), int(c[5]),
                   tuple(tracer.f32(float(c[6 + k])) for k in range(3)))
            single = tracer.box_trace(bsp, start, end, mins, maxs, mask, tracer.f32).key()
            compared += 1

            # fraction 0 without startsolid can only come from an entry
            # fraction that was negative and got clamped.
            if got[0] == 0.0 and got[2] == 0 and got[3] != 0:
                negative_entry += 1

            if got != single:
                exact_diffs.append(f"{path.name}#{i} C={got} ref32={single}")
                continue

            # The C matched the float32 reference. Where the double reference
            # says something else, this ray's answer is decided by rounding -
            # worth counting and reporting, but not a defect in either.
            double = tracer.box_trace(bsp, start, end, mins, maxs, mask, tracer.f64).key()
            if materially_differs(single, double):
                precision_rays.append(f"{path.name}#{i}")

    probe_bsp = oracle.load(maps[0])
    probe = tracer.generate_rays(probe_bsp, RAY_SEED, RAYS_PER_MAP)
    check(
        "the ray set reaches the containment path as well as the sweep",
        sum(1 for s, e, *_ in probe if tuple(s) == tuple(e)) >= RAYS_PER_MAP // 16,
        "without zero-length sweeps the position test is never executed",
    )
    check(
        "the ray set includes sweeps that start resting on a face",
        grazing_total >= 100,
        f"only {grazing_total} grazing rays across the corpus; without them the "
        "entry-fraction clamp is never exercised",
    )
    check(
        "some grazing sweep really does produce a negative entry fraction",
        negative_entry > 0,
        "the clamp at the heart of the sweep would otherwise be untested code",
    )
    check("every map in the corpus loaded", not load_failures, "; ".join(load_failures[:3]))
    check("every map produced one answer per ray", not shape_failures,
          "; ".join(shape_failures[:3]))
    check("the whole corpus was traced", traced_maps >= 100, f"traced {traced_maps}")
    check(
        "the C module and the reference agree on every ray, exactly",
        not exact_diffs,
        f"{len(exact_diffs)} of {compared}: {exact_diffs[:2]}",
    )
    # This is a MEASUREMENT, asserted so it cannot creep: a handful of rays out
    # of tens of thousands land on a plane the two precisions read differently.
    # If that number moves, something about the arithmetic moved with it.
    check(
        "precision-decided rays stay vanishingly rare",
        len(precision_rays) <= compared // 1000,
        f"{len(precision_rays)} of {compared}: {precision_rays[:5]}",
    )
    print(f"  ..    {compared} rays compared across {traced_maps} maps; "
          f"{len(precision_rays)} decided by float32 rounding "
          f"({', '.join(precision_rays[:3])})")
    return maps


def test_parallel(exe: Path, work: Path, maps: list[Path]) -> None:
    head("parallel: the property the engine's tracer cannot offer")
    if not maps:
        check("maps were available for the parallel cases", False, "")
        return

    sized = sorted(maps, key=lambda p: p.stat().st_size)
    small, large = sized[0], sized[-1]
    picks = [p for p in (maps[0], maps[len(maps) // 2], large) if p]

    rayfile = work / "prays.txt"
    for path in picks:
        bsp = oracle.load(path)
        if not bsp.models:
            continue
        tracer.write_rays(tracer.generate_rays(bsp, RAY_SEED, 400), rayfile)
        for threads in (2, 8):
            out = run(exe, "concurrent", str(path), str(rayfile), str(threads))
            check(
                f"{path.name}: {threads} threads reproduce the single-threaded answers",
                out.startswith("IDENTICAL"),
                out[:200],
            )

    # Two documents at once. If any traversal state escaped the context, the
    # answers would be a blend of the two maps.
    bsp = oracle.load(large)
    tracer.write_rays(tracer.generate_rays(bsp, RAY_SEED, 300), rayfile)
    out = run(exe, "interleave", str(large), str(small), str(rayfile))
    check(
        "two contexts on two documents, alternating, do not interfere",
        out.startswith("IDENTICAL"),
        out[:200],
    )

    out = run(exe, "rebind", str(large), str(small), str(rayfile))
    check(
        "one context rebound between a large and a small map stays correct",
        out.startswith("IDENTICAL"),
        out[:200],
    )


def test_edges(exe: Path, work: Path, maps: list[Path]) -> None:
    head("edges: what the tracer refuses")
    if not maps:
        return
    path = maps[0]
    bsp = oracle.load(path)
    rayfile = work / "erays.txt"

    # Determinism: the same rays twice, same process, same answers. The
    # grazing rays are here too, because they are the ones that can produce a
    # fraction outside 0..1 if the entry clamp ever goes.
    tracer.write_rays(tracer.generate_rays(bsp, RAY_SEED, 150)
                      + tracer.generate_grazing_rays(bsp, GRAZING_PER_MAP), rayfile)
    a = run(exe, "trace", str(path), str(rayfile))
    b = run(exe, "trace", str(path), str(rayfile))
    check("the same rays give the same answers", a == b and bool(a), "")

    # A sweep that starts and ends at the same point is a containment test and
    # must never report a fraction other than 1 or 0.
    lines = [ln.split() for ln in a.splitlines()]
    check(
        "no answer reports a fraction outside 0..1",
        all(0.0 <= float(c[1]) <= 1.0 for c in lines),
        "",
    )
    # `allsolid` is only ever set inside the branch that also sets
    # `startsolid`; a sweep that never left a solid necessarily began in one.
    # (Quake II does NOT force the fraction to zero in that case, and asserting
    # that it does would be asserting something the engine does not do.)
    check(
        "allsolid is never reported without startsolid",
        all(not int(c[2]) or int(c[3]) for c in lines),
        f"{sum(1 for c in lines if int(c[2]) and not int(c[3]))} rows claim to have "
        "ended in a solid they never started in",
    )

    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    check(
        "a null or unbound context is refused rather than trusted",
        "if (!ctx || !ctx->bsp || !start || !end || !mins || !maxs)" in src,
        "an unbound context would index a NULL document",
    )
    check(
        "the result is initialised before any refusal can return",
        src.index("memset(out, 0, sizeof(*out));") < src.index("if (!ctx || !ctx->bsp"),
        "a caller that ignores the refusal must still see a defined result",
    )
    check(
        "a sweep against a model refuses a null result rather than writing one",
        "!mins || !maxs || !out)" in src,
        "MapGenTrace_BoxModel REFINES a result instead of initialising one - "
        "that is what lets the world and every mover go through the same "
        "trace - so it has to check the result it was handed",
    )
    check(
        "and it is defined after the entry point that does the initialising",
        src.index("void MapGenTrace_Box(") < src.index("void MapGenTrace_BoxModel("),
        "the ordering is what makes the check above land on the right one",
    )
    check(
        "releasing a context clears the pointer it freed",
        "ctx->stamps = NULL;" in src and "ctx->bsp = NULL;" in src,
        "a released context must not look bound",
    )
    check(
        "binding grows the stamp array and zeroes only the new part",
        "memset(grown + ctx->capacity, 0," in src,
        "",
    )
    client, helper = _build_lists()
    check(
        "the module is not in the client",
        "mapgen_trace.c" not in client,
        "the PO's binary must be untouched; MAPGEN ships as its own helper",
    )
    check(
        "and it IS in the MAPGEN helper",
        "mapgen_trace.c" in helper,
        "a helper that does not contain the module cannot run a job",
    )


def main() -> int:
    print("=== MAPGEN-1 M2 MapGenTraceContext contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_trace_") as td:
        work = Path(td)
        head("building")
        exe = build(cc, work)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        maps = test_reference(exe, work)
        test_parallel(exe, work, maps)
        test_edges(exe, work, maps)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
