#!/usr/bin/env python3
"""MAPGEN-1 M4 - the one documented PRNG.

Contract section 10: one fixed generator, streams assigned by attempt index
before parallel execution, and a result that does not depend on worker count,
schedule or completion order.

Three halves:

  * STATIC - the properties that make determinism structural. No global state,
    no clock, no libc generator, no floating point, and the published
    constants present verbatim so a future reader can check them against the
    paper rather than against this file;

  * PARITY - every entry point held against tools/mapgen_random_oracle.py,
    an implementation written from the published definitions rather than from
    the C. Two readings of one paper agreeing is worth more than one reading
    tested against itself. The oracle also carries what a MODULO-folding
    implementation would produce, and the guard proves the C does not match
    it: a rejection loop nobody can distinguish from a fold is a rejection
    loop nobody has tested;

  * PROPERTIES - what a value dump cannot show, asserted in the driver against
    the compiled module: streams that cannot disturb each other, creation
    order that leaves no trace, and an unbiased draw at the one bound where
    bias is visible.

Run: python tools/check_mapgen_random_contract.py
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

from mapgen_random_oracle import Random, naive_below  # noqa: E402

HEADER = REPO / "inc" / "common" / "mapgen_random.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_random.c"
DRIVER = REPO / "tools" / "mapgen_random_test_driver.c"

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
    head("static: determinism is structural, not a habit")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    check(
        "there is no file-scope state of any kind",
        not re.search(r"^static\s+(?!const\b)[A-Za-z_][\w ]*\s+[A-Za-z_]\w*\s*(=|;)",
                      src, re.M),
        "every bit of state lives in the caller's struct",
    )
    check(
        "the libc generator is nowhere near it",
        not re.search(r"\b(rand|srand|random|srandom|arc4random|rand_r)\s*\(", src),
        "per-process, per-libc and unspecified",
    )
    check(
        "there is no clock and no entropy source",
        not re.search(r"\b(time|clock|getpid|GetTickCount|QueryPerformanceCounter|"
                      r"CryptGenRandom|RtlGenRandom)\s*\(", src),
        "a seed is the only input; anything else is unreproducible",
    )
    check(
        "and no floating point",
        not re.search(r"\b(float|double)\b", src),
        "a probability in permille, not in an FPU rounding mode",
    )
    check(
        "the SplitMix64 constants are the published ones",
        "0x9E3779B97F4A7C15" in src and "0xBF58476D1CE4E5B9" in src
        and "0x94D049BB133111EB" in src,
        "written out so they can be checked against the paper",
    )
    check(
        "and so is the xoshiro256** output function",
        "rotl(r->s[1] * 5ull, 7) * 9ull" in src and "rotl(r->s[3], 45)" in src
        and "r->s[1] << 17" in src,
        "",
    )
    check(
        "the all-zero state, which would emit zero forever, is excluded",
        "if (!(r->s[0] | r->s[1] | r->s[2] | r->s[3]))" in src,
        "",
    )
    check(
        "a stream is derived from seed, attempt AND purpose",
        "uint64_t seed, uint32_t attempt" in src
        and "mapgen_random_purpose_t purpose" in src
        and "* 0xD1342543DE82EF95ull" in src
        and "* 0xA24BAED4963EE407ull" in src,
        "so no consumer can move another consumer's draws",
    )
    check(
        "the draw rejects rather than folds",
        "while (value >= limit)" in src and "0x100000000ull % bound" in src,
        "modulo bias would quietly distort every learned distribution",
    )
    check(
        "and the rejection bound is computed in 64 bits",
        "const uint64_t limit = 0x100000000ull" in src,
        "truncated to 32 bits it is zero for a power-of-two bound, and hangs",
    )
    check(
        "a weight total past 32 bits rejects rather than folds too",
        "0xFFFFFFFFFFFFFFFFull % total" in src,
        "checked statically only: the region a 64-bit rejection discards is at "
        "most `total` out of 2^64, so no run could tell the two apart",
    )
    check(
        "the purpose numbering is documented as frozen",
        "never reorder" in HEADER.read_text(encoding="utf-8")
        and "MAPGEN_RANDOM_PURPOSE_COUNT" in hdr,
        "it is an input to the derivation; renumbering rewrites every map",
    )
    # The rule protects the PO's binary, not the generator: a module
    # the packaged helper runs has to be linked somewhere, and
    # mapgen_src is the somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_random.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("rng.exe" if os.name == "nt" else "rng")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), "-o", str(exe)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def run_batch(exe: Path, requests: list[list[object]]) -> list[list[str]] | None:
    """Answer every request in one process, or nothing at all.

    Launching the driver once per request cost close to three hundred process
    creations for a single run, and the RED matrix pays that for every
    mutation. Nothing is proven differently by batching: each request still
    gets a stream derived from scratch inside the driver.

    A timeout returns None rather than raising, because a timeout IS a result
    here - a rejection loop whose limit was truncated does not return a wrong
    value, it never returns. Swallowing that would turn a hang into an
    infrastructure error instead of the RED it is.
    """
    script = "".join(" ".join(str(a) for a in req) + "\n" for req in requests)
    try:
        p = subprocess.run([str(exe), "batch"], input=script,
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None

    answers: list[list[str]] = []
    current: list[str] | None = None
    for line in p.stdout.splitlines():
        if line.startswith("#"):
            if current is not None:
                answers.append(current)
            current = []
        elif current is not None and line.strip():
            current.append(line.strip())
    if len(answers) != len(requests):
        return None
    return answers


SEEDS = [0, 1, 2, 0xFFFFFFFFFFFFFFFF, 0x0123456789ABCDEF, 20260831, 7919]
PURPOSES = list(range(1, 9))

BOUNDS = (1, 2, 3, 7, 8, 10, 64, 100, 255, 256, 1000, 65536,
          0x7FFFFFFF, 0x80000000, 0xC0000000, 0xFFFFFFFF)
RANGES = ((-64, 64), (0, 0), (12, 12), (5, -5), (-2147483648, 2147483647),
          (-1, 1), (100, 10000))
WEIGHTS = ([1, 0, 3, 6], [1], [0, 0, 0], [5, 5], [1000000, 1, 1],
           [4294967295, 4294967295, 4294967295])
SHUFFLES = (1, 2, 3, 8, 32, 257)
PERMILLES = (0, 1, 250, 500, 999, 1000, 5000)


def test_parity(exe: Path) -> None:
    head("parity: the C against an implementation written from the paper")

    requests: list[list[object]] = []
    for seed in SEEDS:
        for attempt in (0, 1, 2, 17, 4095):
            for purpose in PURPOSES:
                requests.append(["emit", seed, attempt, purpose, 64])
    streams = len(requests)
    for bound in BOUNDS:
        requests.append(["below", 424242, 1, 2, bound, 400])
    for lo, hi in RANGES:
        requests.append(["range", 99, 3, 5, lo, hi, 300])
    for weights in WEIGHTS:
        requests.append(["weighted", 606, 0, 4, 300, *weights])
    for count in SHUFFLES:
        requests.append(["shuffle", 777, 0, 8, count])
    for permille in PERMILLES:
        requests.append(["chance", 606, 0, 7, permille, 300])

    answers = run_batch(exe, requests)
    if not check("the driver answered every request",
                 answers is not None,
                 "a hang or a refusal; either way there is nothing to compare"):
        return
    assert answers is not None

    at = 0
    mismatch = None
    for seed in SEEDS:
        for attempt in (0, 1, 2, 17, 4095):
            for purpose in PURPOSES:
                r = Random(seed, attempt, purpose)
                want = [str(r.next()) for _ in range(64)]
                if answers[at] != want and mismatch is None:
                    mismatch = f"seed={seed} attempt={attempt} purpose={purpose}"
                at += 1
    check(f"every raw stream matches, over {streams} streams of 64 values",
          mismatch is None, mismatch or "")

    mismatch = None
    folded_seen = None
    for bound in BOUNDS:
        r = Random(424242, 1, 2)
        want = [str(r.below(bound)) for _ in range(400)]
        if answers[at] != want and mismatch is None:
            mismatch = f"bound={bound}"
        if bound == 0xC0000000:
            folded_seen = answers[at]
        at += 1
    check("and every bounded draw, including the power-of-two bounds",
          mismatch is None, mismatch or "")

    # The one that proves the rejection is real rather than decorative.
    folded = [str(v) for v in naive_below(424242, 1, 2, 0xC0000000, 400)]
    check("the C does NOT match what a modulo fold would have produced",
          folded_seen is not None and folded_seen != folded
          and len(folded_seen) == 400,
          "at this bound a fold and a rejection diverge within a few draws")

    mismatch = None
    for lo, hi in RANGES:
        r = Random(99, 3, 5)
        want = [str(r.range(lo, hi)) for _ in range(300)]
        if answers[at] != want and mismatch is None:
            mismatch = f"[{lo},{hi}]"
        at += 1
    check("every range matches, including the widest one", mismatch is None,
          mismatch or "")

    mismatch = None
    for weights in WEIGHTS:
        r = Random(606, 0, 4)
        want = [str(r.weighted(weights)) for _ in range(300)]
        if answers[at] != want and mismatch is None:
            mismatch = f"weights={weights}"
        at += 1
    check("every weighted pick matches, including a total past 32 bits",
          mismatch is None, mismatch or "")

    mismatch = None
    for count in SHUFFLES:
        r = Random(777, 0, 8)
        want = [str(v) for v in r.shuffle(list(range(count)))]
        if answers[at] != want and mismatch is None:
            mismatch = f"count={count}"
        at += 1
    check("every shuffle matches element for element", mismatch is None,
          mismatch or "")

    mismatch = None
    for permille in PERMILLES:
        r = Random(606, 0, 7)
        want = ["1" if r.chance(permille) else "0" for _ in range(300)]
        if answers[at] != want and mismatch is None:
            mismatch = f"permille={permille}"
        at += 1
    check("and every coin flip", mismatch is None, mismatch or "")


def test_properties(exe: Path) -> None:
    head("properties: what a value dump cannot show")
    try:
        p = subprocess.run([str(exe), "props"], capture_output=True, text=True,
                           timeout=60)
    except subprocess.TimeoutExpired:
        check("the property suite reported a result", False, "timed out")
        return
    for line in p.stdout.splitlines():
        if line.startswith(("  PASS", "  FAIL")):
            print(line)
    m = re.search(r"=== (\d+) cases asserted, (\d+) failures", p.stdout)
    if not check("the property suite reported a result", m is not None,
                 (p.stdout + p.stderr)[-600:]):
        return
    assert m is not None
    global CASES, FAILED
    CASES += int(m.group(1))
    FAILED += int(m.group(2))


def main() -> int:
    print("=== MAPGEN-1 M4 PRNG contract")
    test_static()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_random_") as td:
        head("building")
        exe = build(cc, Path(td))
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_parity(exe)
        test_properties(exe)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
