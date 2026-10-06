#!/usr/bin/env python3
"""MAPGEN-1 - job state machine contract.

Two halves:

  * a STATIC pass over `src/mapgen/mapgen_job.c` and `inc/common/mapgen_job.h`
    confirming the module stays pure and that the invariants live where they
    can be enforced rather than remembered;

  * the compiled C test `tools/mapgen_job_test_driver.c`, which enumerates
    every request kind against every state against every next state and
    compares the implementation with a transition oracle written
    INDEPENDENTLY from contract section 5.1. Checking a table against itself
    proves only that it is a table.

The four promises under test (contract section 5.1):

  1. exactly one terminal event per accepted JobId;
  2. a terminal JobId never resumes;
  3. event sequences are monotonic and gapless, so Observe(after) is a cursor;
  4. cancellation is honest about the durable-commit boundary.

Run: python tools/check_mapgen_job_contract.py
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
HEADER = REPO / "inc" / "common" / "mapgen_job.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_job.c"
DRIVER = REPO / "tools" / "mapgen_job_test_driver.c"

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
    head("static: the module stays pure and the invariants are enforced")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr = strip_c_comments(HEADER.read_text(encoding="utf-8"))

    check(
        "the state machine pulls in no engine or OS header",
        not re.search(r'#include\s+"(?!common/mapgen_job\.h)', src)
        and not re.search(r"#include\s+<(windows|unistd)\.h>", src),
        "this module must be provable without a game, a worker or a compiler",
    )
    check(
        "it allocates only in create/destroy",
        src.count("calloc(") == 1 and src.count("free(") == 1 and "malloc(" not in src,
        "a state machine that allocates per transition is not a state machine",
    )
    check(
        "a terminal state refuses every transition",
        "if (MapGenState_IsTerminal(slot->state))\n        return false;" in src,
        "a terminal JobId never resumes (contract 5.1)",
    )
    check(
        "the ring slot stores its own key",
        "if (jobs->slots[i].id == id)" in src,
        "Hard Rule #46: a ring indexed by a wrapping counter must carry the key",
    )
    check(
        "job ids are never reused",
        "slot->id = jobs->next_id++;" in src,
        "",
    )
    check(
        "a durable commit cannot be cancelled",
        "if (MapGenState_IsCommitting(slot->state))\n        return MAPGEN_CANCEL_TOO_LATE_COMMITTING;" in src,
        "cancel after a commit began cannot promise rollback",
    )
    check(
        "RECOVERING counts as committing",
        re.search(r"case MAPGEN_STATE_RECOVERING:\s*return true;", src) is not None,
        "RECOVER begins inside the commit boundary and is noncancellable",
    )
    check(
        "a committing state cannot jump to FAILED or CRASHED",
        "return !MapGenState_IsCommitting(slot->state);" in src,
        "once a commit began, the outcome is reconciled, not abandoned",
    )
    check(
        "one foreground job is enforced",
        "return MAPGEN_SUBMIT_BUSY;" in src,
        "an argument-less menu action must address an unambiguous job",
    )
    check(
        "dropped events are counted rather than hidden",
        "slot->events_dropped++;" in src,
        "a cursor that silently skips is worse than one that admits the gap",
    )
    check(
        "the machines are declared as data",
        "static const mapgen_machine_t machines[MAPGEN_REQ_COUNT]" in src,
        "so the whole machine can be enumerated by a test",
    )
    check(
        "the header states the four promises",
        "ONE terminal event per accepted JobId" in HEADER.read_text(encoding="utf-8")
        and "never resumes" in HEADER.read_text(encoding="utf-8"),
        "",
    )
    check(
        "job id zero is reserved",
        "#define MAPGEN_JOB_ID_NONE" in hdr,
        "",
    )


def test_compiled() -> int:
    head("compiled: the enumerated state machine")
    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_job_") as td:
        exe = Path(td) / ("jobtest.exe" if os.name == "nt" else "jobtest")
        build = subprocess.run(
            [cc, "-std=c17", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
             str(DRIVER), str(SOURCE), "-o", str(exe)],
            capture_output=True, text=True,
        )
        if not check("the test compiles with -Wall -Wextra -Werror", build.returncode == 0,
                     (build.stdout + build.stderr)[-1500:]):
            return 1

        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=300)
        out = run.stdout + run.stderr
        for line in run.stdout.splitlines():
            if line.startswith("  PASS") or line.startswith("  FAIL") or line.startswith("  .."):
                print(line)
            elif line.startswith("==="):
                print(line)

        m = re.search(r"=== (\d+) cases asserted, (\d+) failures", out)
        if not check("the test reported a result", m is not None, out[-800:]):
            return 1
        assert m is not None
        asserted, failures = int(m.group(1)), int(m.group(2))
        global CASES, FAILED
        CASES += asserted
        FAILED += failures
        check("the compiled test passed", failures == 0 and run.returncode == 0, f"{failures} failures")

        m2 = re.search(r"(\d+) transitions compared", out)
        check(
            "the enumeration really covered the machine",
            m2 is not None and int(m2.group(1)) > 2000,
            f"only {m2.group(1) if m2 else 0} transitions compared",
        )
    return 0


def main() -> int:
    print("=== MAPGEN-1 job state machine contract")
    test_static()
    test_compiled()
    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
