#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_m0_contract.py.

Hard Rule #38: a guard is valid only after it has been demonstrated to FAIL on
the exact defect it claims to detect, and to pass again after byte-exact
restoration. The M0 deliverable list names this explicitly - "a controlled RED
that fails on a damaged/missing output, then restored GREEN" - and the same
treatment is applied here to every other load-bearing rule the harness carries.

Two rules this driver enforces on ITSELF, both learned the hard way:

  * Repository trap (entry packet section 6.1): the tree mixes CRLF and LF, so
    every mutation is applied to raw BYTES, every anchor must occur exactly
    once, the mutation is proven to have reached disk, and the original bytes
    plus their SHA-256 are restored and verified. An anchor that cannot be
    found FAILS the whole matrix instead of printing SKIP - six silent SKIPs in
    the perf-HUD RED matrix are why that rule exists.

  * A mutation must go RED on ITS OWN named case. The first run of this driver
    reported ten failures, and every one was a real hole: a suite case that
    several guards could satisfy cannot prove any single guard. Removing the
    leak-log scan stayed green because the .pts check caught the same fixture;
    removing the reread guard stayed green because the semantics guard raised
    first. The suite grew isolated cases so each mutation has exactly one
    detector.

Exit 0 = every mutation was detected on its own named case and everything was
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

SUITE = SANDBOX.path("tools/check_mapgen_m0_contract.py")
RUNNER = SANDBOX.path("tools/mapgen_qualification.py")
ORACLE = SANDBOX.path("tools/mapgen_bsp_oracle.py")
FAKE = SANDBOX.path("tools/mapgen_fake_compiler.py")
HEADER = SANDBOX.path("src/mapgen/mapgen_compiler.h")
FIXTURE_GEN = SANDBOX.path("tools/mapgen_make_fixtures.py")
FIXTURE_LIB = SANDBOX.path("tools/mapgen_fixture_lib.py")

# (case, file, anchor, replacement, substring of the suite case that must FAIL)
CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # ---- the one law: a zero exit code is never success --------------------
    (
        "ok-without-reread-allowed",
        RUNNER,
        b"        if not self.reread_performed:\n",
        b"        if False:\n",
        "finish_ok refuses without a reread",
    ),
    (
        "ok-without-semantic-check-allowed",
        RUNNER,
        b"        if not self.semantics_checked:\n",
        b"        if False:\n",
        "finish_ok refuses without a semantic check",
    ),
    # ---- damaged / missing / stale output ---------------------------------
    (
        "damaged-output-accepted",
        RUNNER,
        b'        report.fail("MAPCOMPILE_ERR_OUTPUT_UNREADABLE", f"oracle rejected the output: {exc}")\n        return report\n',
        b"        report.reread_performed = True\n        report.semantics_checked = True\n        return report\n",
        "behavior damaged_output",
    ),
    (
        "missing-output-accepted",
        RUNNER,
        b'        report.fail("MAPCOMPILE_ERR_NO_OUTPUT", f"{request.bsp_path.name} was never written")\n',
        b'        report.failures.append("note: no output")\n',
        "behavior zero_exit_no_output",
    ),
    (
        "later-stage-noop-accepted",
        RUNNER,
        b"        if last_output_sha is not None and stage_sha == last_output_sha:\n",
        b"        if False:\n",
        "behavior vis_noop",
    ),
    (
        "dirty-job-dir-accepted",
        RUNNER,
        b"    if request.bsp_path.exists():\n",
        b"    if False:\n",
        "a pre-existing BSP is refused before the run",
    ),
    # ---- zero exit that is not success ------------------------------------
    (
        "leak-marker-ignored",
        RUNNER,
        b"        if LEAK_MARKER in stage_report.stdout_captured:\n",
        b"        if False:\n",
        "behavior zero_exit_leak_marker_only",
    ),
    (
        "leak-file-ignored",
        RUNNER,
        b"    if request.pts_path.exists():\n",
        b"    if False:\n",
        "behavior zero_exit_leak_pts_only",
    ),
    (
        "missing-texture-warning-ignored",
        RUNNER,
        b"        if MISSING_TEXTURE_MARKER in stage_report.stdout_captured:\n",
        b"        if False:\n",
        "behavior zero_exit_missing_texture",
    ),
    # ---- containment and budgets ------------------------------------------
    (
        "job-root-escape-ignored",
        RUNNER,
        b"        if report.escaped_paths:\n",
        b"        if False:\n",
        "behavior escape_path",
    ),
    (
        "timeout-not-enforced",
        RUNNER,
        b"        if stage_report.timed_out:\n",
        b"        if False:\n",
        "behavior hang",
    ),
    (
        "crash-not-enforced",
        RUNNER,
        b"        if stage_report.crashed:\n",
        b"        if False:\n",
        "behavior crash",
    ),
    (
        "nonzero-exit-ignored",
        RUNNER,
        b"        if stage_report.exit_code != 0:\n",
        b"        if False:\n",
        "behavior nonzero_exit",
    ),
    # ---- semantics ---------------------------------------------------------
    (
        "degenerate-output-accepted",
        RUNNER,
        b"    problems.extend(structural_floor(bsp))\n",
        b"    pass\n",
        "the degenerate-output failure names what is missing",
    ),
    (
        "entity-counts-not-checked",
        RUNNER,
        b'    want_classes = expectations.get("entity_classnames")\n',
        b"    want_classes = None\n",
        "behavior zero_exit_wrong_semantics",
    ),
    (
        "wrong-format-accepted",
        RUNNER,
        b"    if got_format != request.expect_format:\n",
        b"    if False:\n",
        "a format mismatch is a failure",
    ),
    (
        "final-profile-skips-lighting",
        RUNNER,
        b"        if bsp.lighting_bytes <= 0:\n",
        b"        if False:\n",
        "final profile refuses output with no lighting",
    ),
    (
        "final-profile-skips-visibility",
        RUNNER,
        b"        if bsp.visibility_bytes <= 0:\n",
        b"        if False:\n",
        "final profile refuses output with no visibility",
    ),
    # ---- thread policy -----------------------------------------------------
    (
        "thread-count-left-to-the-machine",
        RUNNER,
        b'        argv += ["-threads", str(request.threads)]\n',
        b"        pass\n",
        "-threads is always passed explicitly",
    ),
    # ---- the oracle --------------------------------------------------------
    (
        "oracle-accepts-any-ident",
        ORACLE,
        b'        raise BspError(f"unknown ident 0x{ident:08x} (expected IBSP or QBSP)")\n',
        b"        extended = False\n",
        "oracle rejects a wrong ident on an otherwise valid file",
    ),
    (
        "oracle-accepts-any-version",
        ORACLE,
        b'        raise BspError(f"version {version}, expected {BSPVERSION}")\n',
        b"        pass\n",
        "oracle rejects a wrong version",
    ),
    (
        "oracle-ignores-lump-bounds",
        ORACLE,
        b'            raise BspError(f"lump {i} out of bounds: ofs={ofs} len={length} file={len(data)}")\n',
        b"            length = max(0, len(data) - ofs)\n",
        "oracle rejects a lump that runs past the end of the file",
    ),
    (
        "oracle-skips-index-validation",
        ORACLE,
        b"        if leaf.firstleafbrush + leaf.numleafbrushes > len(bsp.leafbrushes):\n",
        b"        if False:\n",
        "oracle rejects an out-of-range leafbrush reference",
    ),
    (
        "oracle-tolerates-broken-entity-string",
        ORACLE,
        b'            raise BspError("unterminated entity block")\n',
        b"            out.append(current)\n",
        "oracle rejects an unterminated entity block",
    ),
    # ---- contract / implementation agreement -------------------------------
    (
        "header-drifts-from-runner",
        HEADER,
        b"    MAPCOMPILE_ERR_WRONG_FORMAT,\n",
        b"",
        "header result codes match the runner",
    ),
    (
        "header-loses-the-zero-exit-law",
        HEADER,
        b"A zero exit code is NEVER success.",
        b"A zero exit code is usually fine.",
        "header states the zero-exit law",
    ),
    # ---- fixtures ----------------------------------------------------------
    (
        "fixture-drops-explicit-contents",
        FIXTURE_LIB,
        b'                f"0 1 1 {contents} {flags} {value}"\n',
        b'                f"0 1 1 0 0 0"\n',
        "fixtures regenerate byte-identically",
    ),
    (
        "fake-compiler-stops-announcing-the-leak",
        FAKE,
        b"        # so that removing the stdout scan cannot hide behind the .pts check.\n        print(LEAK_MARKER)\n",
        b"        # so that removing the stdout scan cannot hide behind the .pts check.\n        print('all good')\n",
        "behavior zero_exit_leak_marker_only",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=1800,
    )
    return proc.returncode, proc.stdout + proc.stderr


def regenerate_fixtures() -> None:
    subprocess.run([sys.executable, str(FIXTURE_GEN)], capture_output=True, cwd=str(REPO))


def main() -> int:
    print("=== MAPGEN-1 M0 controlled RED")

    regenerate_fixtures()
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
            if path is FIXTURE_LIB:
                regenerate_fixtures()

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
