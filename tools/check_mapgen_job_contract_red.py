#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_job_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect and passed again after byte-exact restoration.

Every mutation removes one of the state machine's promises - the terminal
lock, the slot's key, the never-reused id, the commit boundary, the single
foreground job, an edge, the drop accounting - and each must go RED on its OWN
named case.

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

SUITE = SANDBOX.path("tools/check_mapgen_job_contract.py")
JOB = SANDBOX.path("src/mapgen/mapgen_job.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    (
        "terminal-jobs-resume",
        JOB,
        b"    if (MapGenState_IsTerminal(slot->state))\n        return false;   /* a terminal JobId never resumes */\n",
        b"    if (false)\n        return false;   /* a terminal JobId never resumes */\n",
        "no transition is accepted after a terminal state",
    ),
    (
        "ring-slot-forgets-its-key",
        JOB,
        b"        if (jobs->slots[i].id == id)\n            return &jobs->slots[i];\n",
        b"        if (jobs->slots[i].id != 0 && (jobs->slots[i].id & 0xF) == (id & 0xF))\n"
        b"            return &jobs->slots[i];\n",
        "a stale id whose slot was reused cannot be observed",
    ),
    (
        "job-ids-are-reused",
        JOB,
        b"    slot->id = jobs->next_id++;      /* never reused */\n",
        b"    slot->id = (jobs->next_id++ % MAPGEN_JOB_RING_SLOTS) + 1;\n",
        "48 jobs across a 16-slot ring all have distinct ids",
    ),
    (
        "commit-boundary-ignored-by-cancel",
        JOB,
        b"    if (MapGenState_IsCommitting(slot->state))\n        return MAPGEN_CANCEL_TOO_LATE_COMMITTING;\n",
        b"    if (false)\n        return MAPGEN_CANCEL_TOO_LATE_COMMITTING;\n",
        "cancel returns the exact contract result in every reachable state",
    ),
    (
        "recovering-is-not-treated-as-committing",
        JOB,
        b"    case MAPGEN_STATE_RECOVERING:\n        return true;\n    default:\n        return false;\n    }\n}\n\n/*\n * The canonical state machines",
        b"    default:\n        return false;\n    }\n}\n\n/*\n * The canonical state machines",
        "cancelling a recovery is TOO_LATE_COMMITTING",
    ),
    (
        "a-commit-can-be-abandoned-as-failed",
        JOB,
        b"    if (next == MAPGEN_STATE_FAILED || next == MAPGEN_STATE_CRASHED)\n        return !MapGenState_IsCommitting(slot->state);\n",
        b"    if (next == MAPGEN_STATE_FAILED || next == MAPGEN_STATE_CRASHED)\n        return true;\n",
        "the implementation agrees with an independently written oracle",
    ),
    (
        "two-jobs-at-once",
        JOB,
        b"        if (slot && !MapGenState_IsTerminal(slot->state))\n            return MAPGEN_SUBMIT_BUSY;\n",
        # Keeps `slot` used, so -Werror does not fail the BUILD instead of the
        # check under test.
        b"        if (slot && MapGenState_IsTerminal(slot->state))\n            return MAPGEN_SUBMIT_BUSY;\n",
        "a second submit is BUSY",
    ),
    (
        "an-edge-goes-missing",
        JOB,
        b"    { MAPGEN_STATE_FINAL_VALIDATION,   MAPGEN_STATE_COMMITTING_PROJECT },\n",
        b"",
        "the implementation agrees with an independently written oracle",
    ),
    (
        "an-edge-is-invented",
        JOB,
        b"    { MAPGEN_STATE_QUEUED,     MAPGEN_STATE_PREFLIGHT },\n"
        b"    { MAPGEN_STATE_PREFLIGHT,  MAPGEN_STATE_VALIDATION },\n",
        b"    { MAPGEN_STATE_QUEUED,     MAPGEN_STATE_PREFLIGHT },\n"
        b"    { MAPGEN_STATE_QUEUED,     MAPGEN_STATE_SUCCEEDED },\n"
        b"    { MAPGEN_STATE_PREFLIGHT,  MAPGEN_STATE_VALIDATION },\n",
        "the implementation agrees with an independently written oracle",
    ),
    (
        "dropped-events-are-hidden",
        JOB,
        b"        slot->events_dropped++;\n",
        b"        (void)0;\n",
        "dropped events are counted",
    ),
    (
        "the-event-log-is-unbounded",
        JOB,
        b"    if (slot->event_count == MAPGEN_JOB_EVENT_SLOTS) {\n",
        b"    if (false) {\n",
        "the log stays bounded",
    ),
    (
        "progress-is-not-clamped",
        JOB,
        b"    if (percent > 100)\n        percent = 100;\n",
        b"    if (false)\n        percent = 100;\n",
        "the clamped percent is 100",
    ),
    (
        "sequences-are-not-monotonic",
        JOB,
        b"    e->sequence = slot->next_sequence++;\n",
        b"    e->sequence = slot->next_sequence; slot->next_sequence += 2;\n",
        "sequences are monotonic and gapless",
    ),
    (
        "a-terminal-job-keeps-the-controller",
        JOB,
        b"    if (MapGenState_IsTerminal(next) && jobs->active == id)\n        jobs->active = MAPGEN_JOB_ID_NONE;\n",
        b"    if (false)\n        jobs->active = MAPGEN_JOB_ID_NONE;\n",
        "a terminal job releases the controller",
    ),
    (
        "progress-continues-after-terminal",
        JOB,
        b"    if (!slot || MapGenState_IsTerminal(slot->state))\n        return false;\n    if (percent > 100)\n",
        b"    if (!slot)\n        return false;\n    if (percent > 100)\n",
        "no transition is accepted after a terminal state",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True, cwd=str(REPO), timeout=1200
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 job state machine controlled RED")

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
