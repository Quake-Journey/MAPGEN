#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_trace_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Two mutations carry the weight of the module:

  * `shared-stamp-behind-a-function-local-static` puts the engine's actual
    defect back - one stamp array for every thread - and the concurrency case
    must be what notices;
  * `startsolid-decided-before-the-box-offset` breaks the geometry in a way no
    string comparison could see, so the cross-implementation case has to earn
    its place.

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

SUITE = SANDBOX.path("tools/check_mapgen_trace_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_trace.c")
HDR = SANDBOX.path("inc/common/mapgen_trace.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the reason the module exists ------------------------------------
    (
        "shared-stamp-behind-a-function-local-static",
        SRC,
        b"        if (s->ctx->stamps[brushnum] == s->ctx->generation)\n"
        b"            continue;\n"
        b"        s->ctx->stamps[brushnum] = s->ctx->generation;\n",
        b"        static uint32_t shared_stamps[65536];\n"
        b"        if (shared_stamps[brushnum & 65535] == s->ctx->generation)\n"
        b"            continue;\n"
        b"        shared_stamps[brushnum & 65535] = s->ctx->generation;\n",
        "q2rdm11.bsp: 8 threads reproduce the single-threaded answers",
    ),
    (
        "file-scope-mutable-state",
        SRC,
        b"static void clip_box_to_brush(sweep_t *s, const mapgen_bsp_brush_t *brush)\n"
        b"{\n    if (!brush->numsides)\n        return;\n",
        b"static uint32_t g_last_contents;\n\n"
        b"static void clip_box_to_brush(sweep_t *s, const mapgen_bsp_brush_t *brush)\n"
        b"{\n    if (!brush->numsides)\n        return;\n"
        b"    g_last_contents = (uint32_t)brush->contents;\n",
        "the tracer keeps no file-scope mutable state",
    ),
    (
        "traversal-state-in-a-function-local-static",
        SRC,
        b"    float enterfrac = -1.0f;\n",
        b"    static float enterfrac;\n    enterfrac = -1.0f;\n",
        "the tracer keeps no state in a function-local static",
    ),
    (
        "the-engine-global-stamp-comes-back",
        SRC,
        b"    bool getout = false;\n",
        b"    bool getout = false;\n    int checkcount = brush->numsides;\n    (void)checkcount;\n",
        "no checkcount anywhere",
    ),

    # --- the geometry, which only the reference can judge -----------------
    (
        "startsolid-decided-before-the-box-offset",
        SRC,
        b"                ofs[j] = plane->normal[j] < 0 ? s->maxs[j] : s->mins[j];\n",
        b"                ofs[j] = plane->normal[j] < 0 ? s->mins[j] : s->maxs[j];\n",
        "the C module and the reference agree on every ray, exactly",
    ),
    (
        "the-miss-test-loses-its-boundary",
        SRC,
        b"        if (d1 > 0 && d2 >= d1)\n            return;\n",
        b"        if (d1 > 0 && d2 > d1)\n            return;\n",
        "the C module and the reference agree on every ray, exactly",
    ),
    (
        "node-offset-drops-the-absolute-value",
        SRC,
        b"            offset = fabsf(s->extents[0] * plane->normal[0]) +\n"
        b"                     fabsf(s->extents[1] * plane->normal[1]) +\n"
        b"                     fabsf(s->extents[2] * plane->normal[2]);\n",
        b"            offset = (s->extents[0] * plane->normal[0]) +\n"
        b"                     (s->extents[1] * plane->normal[1]) +\n"
        b"                     (s->extents[2] * plane->normal[2]);\n",
        "the C module and the reference agree on every ray, exactly",
    ),
    (
        "the-far-half-of-the-split-is-traced-twice",
        SRC,
        b"    recursive_hull_check(s, node->children[side ^ 1], midf, p2f, mid, p2, depth + 1);\n",
        b"    recursive_hull_check(s, node->children[side], midf, p2f, mid, p2, depth + 1);\n",
        "the C module and the reference agree on every ray, exactly",
    ),
    (
        "hull-extents-ignore-the-mins",
        SRC,
        b"        s.extents[i] = -mins[i] > maxs[i] ? -mins[i] : maxs[i];\n",
        b"        s.extents[i] = maxs[i];\n",
        "the C module and the reference agree on every ray, exactly",
    ),
    (
        "a-zero-length-sweep-is-swept-instead-of-tested",
        SRC,
        b"    if (start[0] == end[0] && start[1] == end[1] && start[2] == end[2]) {\n",
        b"    if (false) {\n",
        "the C module and the reference agree on every ray, exactly",
    ),
    (
        "the-entry-fraction-is-not-clamped-to-zero",
        SRC,
        b"        if (enterfrac < 0)\n            enterfrac = 0;\n",
        b"        if (enterfrac < -1000.0f)\n            enterfrac = 0;\n",
        "no answer reports a fraction outside 0..1",
    ),

    # --- lifecycle and refusals ------------------------------------------
    (
        "allsolid-without-startsolid",
        SRC,
        b"        s->trace->startsolid = true;\n        if (!getout)\n"
        b"            s->trace->allsolid = true;\n",
        b"        if (!getout)\n            s->trace->allsolid = true;\n",
        "allsolid is never reported without startsolid",
    ),
    (
        "an-unbound-context-is-trusted",
        SRC,
        b"    if (!ctx || !ctx->bsp || !start || !end || !mins || !maxs)\n        return;\n",
        b"    if (!ctx || !start || !end || !mins || !maxs)\n        return;\n",
        "a null or unbound context is refused rather than trusted",
    ),
    (
        "the-result-is-left-undefined-on-refusal",
        SRC,
        b"    memset(out, 0, sizeof(*out));\n"
        b"    out->fraction = 1.0f;\n"
        b"    if (start) {\n"
        b"        out->endpos[0] = start[0];\n"
        b"        out->endpos[1] = start[1];\n"
        b"        out->endpos[2] = start[2];\n"
        b"    }\n"
        b"    if (!ctx || !ctx->bsp || !start || !end || !mins || !maxs)\n"
        b"        return;\n",
        b"    if (!ctx || !ctx->bsp || !start || !end || !mins || !maxs)\n"
        b"        return;\n"
        b"    memset(out, 0, sizeof(*out));\n"
        b"    out->fraction = 1.0f;\n"
        b"    if (start) {\n"
        b"        out->endpos[0] = start[0];\n"
        b"        out->endpos[1] = start[1];\n"
        b"        out->endpos[2] = start[2];\n"
        b"    }\n",
        "the result is initialised before any refusal can return",
    ),
    (
        "release-leaves-a-dangling-stamp-pointer",
        SRC,
        b"    ctx->stamps = NULL;\n",
        b"    ctx->capacity = ctx->capacity;\n",
        "releasing a context clears the pointer it freed",
    ),
    (
        "the-grown-stamp-array-is-not-zeroed",
        SRC,
        b"        memset(grown + ctx->capacity, 0, (size_t)(need - ctx->capacity) * sizeof(uint32_t));\n",
        b"        (void)need;\n",
        "binding grows the stamp array and zeroes only the new part",
    ),
    (
        "the-stamp-index-is-unbounded",
        SRC,
        b"        if (brushnum >= s->ctx->capacity)\n            continue;\n",
        b"        if (brushnum >= s->ctx->capacity + 1u)\n            continue;\n",
        "the stamp index is bounded by the context's own capacity",
    ),
    (
        "a-malformed-tree-can-recurse-forever",
        SRC,
        b"    if (s->trace->fraction <= p1f)\n        return;                 /* already hit something nearer */\n"
        b"    if (depth > 1024)\n        return;                 /* a malformed tree must not become a hang */\n",
        b"    if (s->trace->fraction <= p1f)\n        return;                 /* already hit something nearer */\n"
        b"    if (depth > 1024 * 1024)\n        return;\n",
        "both traversals have a depth ceiling",
    ),
    (
        "the-generation-wraps-onto-stale-stamps",
        SRC,
        b"    if (ctx->generation == 0) {\n",
        b"    if (ctx->generation == 0 && ctx->capacity == 0) {\n",
        "a wrapping generation clears the stamps rather than hoping",
    ),
    (
        "the-point-query-stops-delegating",
        SRC,
        b"    return MapGenBsp_PointContents(ctx->bsp, point);\n",
        b"    return (int32_t)(ctx->generation * 0u);\n",
        "the point query delegates rather than reimplementing a traversal",
    ),

    # --- identity: the mask must be the engine's -------------------------
    (
        "the-player-mask-drifts-from-the-engine",
        HDR,
        b"#define MAPGEN_TRACE_MONSTER      0x02000000\n",
        b"#define MAPGEN_TRACE_MONSTER      0x04000000\n",
        "MAPGEN_TRACE_MONSTER is the engine's bit",
    ),
    (
        "the-epsilon-drifts-from-the-engine",
        SRC,
        b"#define DIST_EPSILON  (0.03125f)\n",
        b"#define DIST_EPSILON  (0.0625f)\n",
        "the sweep uses the engine's own epsilon",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=2400,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 MapGenTraceContext controlled RED")

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
