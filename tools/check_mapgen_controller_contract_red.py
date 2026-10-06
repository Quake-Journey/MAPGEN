#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_controller_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect and passed again after byte-exact restoration.

Every mutation removes one Controller promise - the off-state early-out, the
Controller-local routing, the single terminal event on a failed launch, the
worker release, the staged-result refusal, the bounded tick, the ask-don't-kill
cancel - and each must go RED on its OWN named case.

Exit 0 = every mutation detected, everything restored byte-identically.
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

SUITE = SANDBOX.path("tools/check_mapgen_controller_contract.py")
CTL = SANDBOX.path("src/mapgen/mapgen_controller.c")
HDR = SANDBOX.path("inc/common/mapgen.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    (
        "idle-tick-does-work",
        CTL,
        b"    if (!mapgen || !mapgen->worker)\n        return;\n\n    mapgen_job_id_t id = mapgen->worker_job;\n",
        b"    mapgen_job_id_t id = mapgen->worker_job;\n    if (!mapgen || !mapgen->worker)\n        return;\n",
        "the idle early-out is the first statement of Tick",
    ),
    (
        "discovery-launches-a-worker",
        CTL,
        # Mutate the ROUTING, not the branch: `if (false)` would leave
        # kind_needs_worker unused and fail the BUILD instead of the check.
        b"    switch (kind) {\n    case MAPGEN_REQ_TRAIN:\n",
        b"    switch (kind) {\n    case MAPGEN_REQ_DISCOVER:\n    case MAPGEN_REQ_TRAIN:\n",
        "discovery launched no worker",
    ),
    (
        "a-failed-launch-loses-its-job",
        CTL,
        b"        MapGenJobs_Diagnostic(mapgen->jobs, id, (uint32_t)pr);\n"
        b"        terminate_job(mapgen, id, MAPGEN_STATE_FAILED);\n"
        b"        if (out_id)\n            *out_id = id;\n"
        b"        return MAPGEN_SUBMIT_ACCEPTED;\n",
        b"        MapGenJobs_Diagnostic(mapgen->jobs, id, (uint32_t)pr);\n"
        b"        if (out_id)\n            *out_id = id;\n"
        b"        return MAPGEN_SUBMIT_ACCEPTED;\n",
        "it terminated as FAILED",
    ),
    (
        "the-worker-outlives-its-job",
        CTL,
        b"    if (mapgen->worker_job == id) {\n",
        b"    if (false) {\n",
        "the worker was released with the job",
    ),
    (
        "a-staged-result-is-called-success",
        CTL,
        b"            mapgen->staged = true;\n"
        b"            copy_bounded(mapgen->summary, sizeof(mapgen->summary),\n",
        b"            terminate_job(mapgen, id, MAPGEN_STATE_SUCCEEDED);\n"
        b"            return;\n            copy_bounded(mapgen->summary, sizeof(mapgen->summary),\n",
        "a staged result is not success",
    ),
    (
        "cancel-never-reaches-the-worker",
        CTL,
        b"    if (mapgen->worker && mapgen->worker_job == id)\n        MapGenProcess_RequestCancel(mapgen->worker);\n",
        b"    if (false)\n        MapGenProcess_RequestCancel(mapgen->worker);\n",
        "that state is CANCELLED",
    ),
    (
        "the-tick-is-unbounded",
        CTL,
        b"    for (int i = 0; i < MAPGEN_TICK_MAX_FRAMES; i++) {\n",
        b"    for (int i = 0; i >= 0; i++) {\n",
        "the tick is bounded",
    ),
    (
        "cancel-kills-instead-of-asking",
        CTL,
        b"    if (mapgen->worker && mapgen->worker_job == id)\n        MapGenProcess_RequestCancel(mapgen->worker);\n    return r;\n",
        b"    if (mapgen->worker && mapgen->worker_job == id)\n        MapGenProcess_Close(mapgen->worker), mapgen->worker = NULL;\n    return r;\n",
        "cancel asks rather than kills",
    ),
    (
        "a-vanished-worker-is-not-noticed",
        CTL,
        # The whole decision, because noticing a dead child has TWO paths on
        # purpose - the error code and the settle window - and that redundancy
        # is what fixed a real timing flake. Disabling one leaves the other
        # correctly reporting CRASHED, so only removing the decision itself
        # tests the promise.
        b"    if (r == MAPGEN_PROC_ERR_CHILD_GONE)\n"
        b"        return MAPGEN_STATE_CRASHED;\n"
        b"    if (!mapgen->worker)\n"
        b"        return MAPGEN_STATE_FAILED;\n",
        b"    (void)r;\n    if (mapgen->worker == NULL || mapgen->worker != NULL)\n"
        b"        return MAPGEN_STATE_FAILED;\n",
        "a vanished worker is CRASHED, not merely FAILED",
    ),
    (
        "create-touches-the-worker-path",
        CTL,
        b"    mapgen->handshake_timeout_ms = config->handshake_timeout_ms;\n    mapgen->worker_job = MAPGEN_JOB_ID_NONE;\n",
        b"    mapgen->handshake_timeout_ms = config->handshake_timeout_ms;\n    mapgen->worker_job = MAPGEN_JOB_ID_NONE;\n"
        b"    { mapgen_process_desc_t probe; memset(&probe, 0, sizeof(probe));\n"
        b"      probe.exe_path = mapgen->worker_exe; probe.work_dir = mapgen->work_dir;\n"
        b"      probe.token = (const uint8_t *)mapgen->build_id;\n"
        b"      probe.job_uuid = (const uint8_t *)mapgen->build_id;\n"
        b"      mapgen_process_t *w = NULL;\n"
        b"      if (MapGenProcess_Launch(&probe, &w) == MAPGEN_PROC_OK) { mapgen->worker = w; } }\n",
        "creating the Controller launches nothing",
    ),
    (
        "a-placeholder-field-appears",
        HDR,
        b"    mapgen_generate_request_t generate;\n} mapgen_request_t;\n",
        b"    mapgen_generate_request_t generate;\n    uint32_t reserved[4];\n} mapgen_request_t;\n",
        "no placeholder vocabulary anywhere in the public header",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True, cwd=str(REPO), timeout=1800
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 Controller controlled RED")

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
