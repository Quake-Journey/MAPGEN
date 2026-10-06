#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_random_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

The mutations that carry the most weight are the ones nobody would notice by
reading the output:

  * `the-draw-folds-instead-of-rejecting` replaces the rejection loop with a
    modulo. Every value it returns is in range and looks random; only the
    distribution is wrong, and only at a bound where the remainder is large;

  * `the-rejection-limit-is-truncated` narrows the limit to 32 bits, which is
    correct for every bound except a power of two and hangs on those. It is
    one cast, and it is the defect this module was written around;

  * `every-purpose-shares-one-stream` and `attempts-are-mixed-in-one-word`
    break the two structural promises - that one pass cannot move another's
    draws, and that adjacent attempts are not adjacent streams.

One mutation is NOT in this matrix and is recorded rather than hidden:
replacing the 64-bit rejection in `MapGenRandom_Weighted` with a plain
modulo is an EQUIVALENT MUTANT in every reachable test. The region a
64-bit rejection discards is at most `total` values out of 2^64, so with
any weight table this code can be handed the two implementations agree for
far longer than any test could run - and with contract 9's caps (32 inputs,
weight at most 100) the branch is not reachable at all. It is kept because
it is correct and the function is general, and it is checked statically.

A mutation may trip more than one case; what is being proven is that the NAMED
case detects it. Exit 0 = every mutation detected on its own case, every file
restored byte-identically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mapgen_red_sandbox import Sandbox  # noqa: E402
from mapgen_red_support import resolve_anchor, sha256  # noqa: E402

# R1: every mutation happens in a disposable copy under the task's own
# temp root. The shared worktree is never opened for writing, so a killed
# process cannot leave a mutation behind - twice it did.
SANDBOX = Sandbox(REPO, Path(__file__).stem)

SUITE = SANDBOX.path("tools/check_mapgen_random_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_random.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the draw -----------------------------------------------------------
    (
        "the-draw-folds-instead-of-rejecting",
        SRC,
        b"    const uint64_t limit = 0x100000000ull - (0x100000000ull % bound);\n"
        b"    uint64_t value;\n"
        b"    do {\n"
        b"        value = MapGenRandom_Next(r) >> 32;\n"
        b"    } while (value >= limit);\n"
        b"    return (uint32_t)(value % bound);\n",
        b"    const uint64_t value = MapGenRandom_Next(r) >> 32;\n"
        b"    return (uint32_t)(value % bound);\n",
        "an awkward bound is drawn without modulo bias",
    ),
    (
        "the-rejection-limit-is-truncated",
        SRC,
        b"    const uint64_t limit = 0x100000000ull - (0x100000000ull % bound);\n"
        b"    uint64_t value;\n",
        b"    const uint64_t limit = (uint32_t)(0x100000000ull - (0x100000000ull % bound));\n"
        b"    uint64_t value;\n",
        # A truncated limit is zero for a power-of-two bound, so the loop never
        # exits. This is the one mutation that does not produce a wrong value -
        # it produces no value at all - so the case that notices is the one
        # asking whether the driver answered, not the one comparing answers.
        "the driver answered every request",
    ),
    (
        "the-draw-uses-the-weak-low-bits",
        SRC,
        b"        value = MapGenRandom_Next(r) >> 32;\n",
        b"        value = MapGenRandom_Next(r) & 0xFFFFFFFFull;\n",
        "and every bounded draw, including the power-of-two bounds",
    ),

    # --- the stream ---------------------------------------------------------
    (
        "every-purpose-shares-one-stream",
        SRC,
        b"    x = splitmix64(&x) ^ ((uint64_t)purpose * 0xA24BAED4963EE407ull);\n",
        # `purpose` stays used: dropping it fails the BUILD under
        # -Werror=unused-parameter rather than the check under test.
        b"    x = splitmix64(&x) ^ ((uint64_t)(purpose & 0u)\n"
        b"                          * 0xA24BAED4963EE407ull);\n",
        "every attempt and purpose gets a stream of its own",
    ),
    (
        "attempts-are-mixed-in-one-word",
        SRC,
        b"    uint64_t x = seed;\n"
        b"    x = splitmix64(&x) ^ ((uint64_t)attempt * 0xD1342543DE82EF95ull);\n"
        b"    x = splitmix64(&x) ^ ((uint64_t)purpose * 0xA24BAED4963EE407ull);\n"
        b"\n"
        b"    for (int i = 0; i < 4; i++)\n"
        b"        r->s[i] = splitmix64(&x);\n",
        b"    uint64_t x = seed;\n"
        b"    x = splitmix64(&x) ^ ((uint64_t)purpose * 0xA24BAED4963EE407ull);\n"
        b"\n"
        b"    for (int i = 0; i < 4; i++)\n"
        b"        r->s[i] = splitmix64(&x);\n"
        b"    r->s[0] ^= attempt;\n",
        "attempt 1 and attempt 2 differ in every state word",
    ),
    (
        "only-part-of-the-seed-is-used",
        SRC,
        b"    uint64_t x = seed;\n",
        # Not `= 0`: that leaves `seed` unused and fails the build.
        b"    uint64_t x = seed & 0xFFull;\n",
        "every raw stream matches, over 280 streams of 64 values",
    ),
    (
        "the-all-zero-state-is-not-excluded",
        SRC,
        b"    if (!(r->s[0] | r->s[1] | r->s[2] | r->s[3]))\n"
        b"        r->s[0] = 0x9E3779B97F4A7C15ull;\n",
        b"    if (!(r->s[0] & r->s[1] & r->s[2] & r->s[3]))\n"
        b"        r->s[0] = 0x9E3779B97F4A7C15ull;\n",
        "every raw stream matches, over 280 streams of 64 values",
    ),

    # --- the generator itself -----------------------------------------------
    (
        "one-rotation-constant-is-wrong",
        SRC,
        b"    r->s[3] = rotl(r->s[3], 45);\n",
        b"    r->s[3] = rotl(r->s[3], 44);\n",
        "every raw stream matches, over 280 streams of 64 values",
    ),
    (
        "one-splitmix-constant-is-wrong",
        SRC,
        b"    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;\n",
        b"    z = (z ^ (z >> 27)) * 0x94D049BB133111EDull;\n",
        "every raw stream matches, over 280 streams of 64 values",
    ),
    (
        "the-state-update-shifts-when-it-should-not",
        SRC,
        b"    r->s[2] ^= t;\n",
        # Not `^= 0`: that leaves `t` set and unused, which the build
        # rejects before the check under test can run.
        b"    r->s[2] ^= t >> 1;\n",
        "every raw stream matches, over 280 streams of 64 values",
    ),

    # --- the derived draws --------------------------------------------------
    (
        "a-range-is-exclusive-at-the-top",
        SRC,
        b"    const uint64_t span = (uint64_t)((int64_t)hi - (int64_t)lo) + 1ull;\n",
        b"    const uint64_t span = (uint64_t)((int64_t)hi - (int64_t)lo);\n",
        "a range is inclusive at both ends and never leaves them",
    ),
    (
        "reversed-range-arguments-are-not-swapped",
        SRC,
        b"    if (lo > hi) {\n"
        b"        const int32_t swap = lo;\n"
        b"        lo = hi;\n"
        b"        hi = swap;\n"
        b"    }\n",
        b"    if (lo > hi)\n"
        b"        hi = lo;\n",
        "reversed arguments are swapped, not refused",
    ),
    (
        "a-zero-weight-can-still-be-chosen",
        SRC,
        b"        seen += weights[i];\n"
        b"        if (pick < seen)\n"
        b"            return i;\n",
        b"        if (pick < seen)\n"
        b"            return i;\n"
        b"        seen += weights[i];\n",
        "a zero weight is never chosen",
    ),
    (
        "an-empty-weight-table-reports-a-choice",
        SRC,
        b"    if (!total)\n"
        b"        return count;                       /* no meaningful pick exists */\n",
        b"    if (!total)\n"
        b"        return 0;                           /* no meaningful pick exists */\n",
        "a table with nothing in it reports no choice",
    ),
    # --- the shuffle --------------------------------------------------------
    (
        "the-shuffle-draws-from-the-wrong-window",
        SRC,
        b"        const size_t j = MapGenRandom_Below(r, (uint32_t)(i + 1));\n",
        b"        const size_t j = MapGenRandom_Below(r, (uint32_t)count);\n",
        "every element reaches every position about equally often",
    ),
    (
        "the-shuffle-does-nothing",
        SRC,
        b"    for (size_t i = count - 1; i > 0; i--) {\n",
        b"    for (size_t i = count - 1; i > count; i--) {\n",
        "and it actually moved something",
    ),

    # --- the coin -----------------------------------------------------------
    (
        "a-certain-chance-is-not-certain",
        SRC,
        b"    if (permille >= 1000u)\n"
        b"        return true;\n",
        b"    if (permille >= 1000u)\n"
        b"        return false;\n",
        "a certain chance always does",
    ),
    (
        "a-zero-chance-always-happens",
        SRC,
        b"    if (!permille)\n"
        b"        return false;\n",
        b"    if (!permille)\n"
        b"        return true;\n",
        "a zero chance never happens",
    ),
]


def run_suite() -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(SUITE)], capture_output=True, text=True,
            cwd=str(REPO), timeout=2400,
        )
    except subprocess.TimeoutExpired:
        # A mutation that hangs the generator is a RED, not an infrastructure
        # failure: the suite could not produce the values it expected.
        return 1, "  FAIL  the driver answered every request  -- timed out"
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 M4 PRNG controlled RED")

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  baseline is not GREEN; refusing to mutate anything")
        print(out[-4000:])
        return 1
    print("  OK    baseline GREEN")

    failures = 0
    for name, path, anchor, replacement, expected_fail in CASES:
        original = path.read_bytes()
        original_hash = sha256(path)

        anchor, replacement, occurrences = resolve_anchor(original, anchor, replacement)
        if occurrences != 1:
            print(
                f"  FAIL  {name}: anchor occurs {occurrences} times in {path.name} "
                "(need exactly 1); the matrix is invalid, not skipped"
            )
            failures += 1
            continue

        mutated = original.replace(anchor, replacement, 1)
        if mutated == original:
            print(f"  FAIL  {name}: mutation did not change {path.name}")
            failures += 1
            continue

        try:
            path.write_bytes(mutated)
            if path.read_bytes() == original:
                print(f"  FAIL  {name}: mutation did not reach disk")
                failures += 1
                continue

            rc, out = run_suite()
            if rc == 0:
                print(f"  FAIL  {name}: suite stayed GREEN under the mutation")
                failures += 1
            elif f"FAIL  {expected_fail}" not in out:
                shown = [ln.strip() for ln in out.splitlines() if ln.startswith("  FAIL")][:4]
                print(f"  FAIL  {name}: went RED but not on '{expected_fail}'; got {shown}")
                failures += 1
            else:
                print(f"  RED   {name} -> {expected_fail}")
        finally:
            # From the pristine tree, not from a value this run computed.
            SANDBOX.restore(SANDBOX.relative(path))

        if sha256(path) != original_hash:
            print(f"  FAIL  {name}: {path.name} was not restored byte-identically")
            failures += 1

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  suite is not GREEN again after restoration")
        print(out[-4000:])
        failures += 1
    else:
        print("  OK    restored GREEN")

    print(f"\n=== {len(CASES)} controlled-RED cases, {failures} failures")
    if failures:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
