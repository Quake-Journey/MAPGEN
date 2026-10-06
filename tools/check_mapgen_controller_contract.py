#!/usr/bin/env python3
"""MAPGEN-1 - the Controller contract.

Static checks over `src/mapgen/mapgen_controller.c` plus a compiled test that
drives the REAL Controller against the REAL worker helper.

What it has to prove (contract sections 5.1, 5.2, 2.11, 2.12):

  * off-state costs nothing - creating the Controller starts no process and
    ticking an idle one does nothing at all;
  * discovery, preflight, recovery and the snapshot library are Controller-local
    and never launch a worker;
  * `STAGED_RESULT` is never reported as success;
  * a job that cannot even launch its worker still emits exactly ONE terminal
    event, rather than vanishing;
  * cancellation reaches the worker, the worker is released with the job, and
    the Controller is free again;
  * `Observe(after)` is a cursor.

Run: python tools/check_mapgen_controller_contract.py
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
HEADER = REPO / "inc" / "common" / "mapgen.h"
SOURCE = REPO / "src" / "mapgen" / "mapgen_controller.c"
DRIVER = REPO / "tools" / "mapgen_controller_test_driver.c"
WORKER = REPO / "src" / "mapgen_worker" / "main.c"

# What the worker is. Imported from the lifecycle guard so there is one answer
# to that question: two copies of it drift, and the way they drift is that one
# of them keeps passing.
sys.path.insert(0, str(REPO / "tools"))
from check_mapgen_worker_lifecycle import build_worker  # noqa: E402
DEPS = [
    REPO / "src" / "mapgen" / "mapgen_job.c",
    REPO / "src" / "mapgen" / "mapgen_ipc.c",
    REPO / "src" / "windows" / "mapgen_process.c",
    # Publication is a Project commit now, and a Project is bound by hashes.
    REPO / "src" / "mapgen" / "mapgen_publish.c",
    REPO / "src" / "mapgen" / "mapgen_digest.c",
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
    head("static: the Seam and the off-state promise")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))
    hdr_raw = HEADER.read_text(encoding="utf-8")

    check(
        "the external Seam is exactly three calls plus a tick",
        all(f"{fn}(" in hdr_raw for fn in
            ("MapGen_Submit", "MapGen_Observe", "MapGen_Cancel", "MapGen_Tick")),
        "",
    )
    check(
        "the header says off-state costs nothing",
        "Off-state costs nothing" in hdr_raw,
        "the promise belongs where the contract lives",
    )
    check(
        "creating the Controller launches nothing",
        "MapGenProcess_Launch" not in src.split("mapgen_submit_result_t MapGen_Submit")[0],
        "MapGen_Create must not start a process",
    )
    check(
        "the idle early-out is the first statement of Tick",
        re.search(r"void MapGen_Tick\(mapgen_t \*mapgen\)\s*\{\s*if \(!mapgen \|\| !mapgen->worker\)\s*return;", src) is not None,
        "an idle tick must cost nothing, so nothing may run before the check",
    )
    check(
        "Controller-local kinds never reach the worker",
        "kind_needs_worker" in src and "case MAPGEN_REQ_VALIDATE:\n        return true;" in src,
        "discovery, preflight, recovery and the library never cross the IPC",
    )
    check(
        "a staged result is not success by itself",
        "mapgen->staged = true;" in src
        and "staged_is_publishable(mapgen->summary)" in src
        # and success is reached only through the publish state, so the
        # durable-commit boundary is visible to whoever is watching - and only
        # when the publish actually happened, because the state used to be the
        # whole of it and the artifact never left the job directory
        and re.search(
            r"walk_to\(mapgen, id, MAPGEN_STATE_PUBLISHING_MAP\).*?"
            r"if \(publish_artifact\(mapgen\) &&\s*"
            r"walk_to\(mapgen, id, MAPGEN_STATE_FINALIZING_PROJECT\)\) \{"
            r"\s*terminate_job\(mapgen, id, MAPGEN_STATE_SUCCEEDED\);",
            src, re.S) is not None
        and src.count("terminate_job(mapgen, id, MAPGEN_STATE_SUCCEEDED)") == 1,
        "the Controller reads the verdict and publishes before anything is"
        " called SUCCEEDED",
    )
    check(
        "and both halves of the verdict have to say so",
        'strncmp(at, "result ", 7)' in src
        and 'strncmp(at, "publishable ", 12)' in src
        and "return result_ok && publishable;" in src,
        "a diagnostic run reports every gate it ran and is explicitly not"
        " publishable; reading only the result would make one a product answer",
    )
    check(
        "every ending goes through one function",
        src.count("static void terminate_job(") == 1
        and len(re.findall(r"terminate_job\(mapgen", src)) >= 5,
        "one terminal event per job is a property of one function, not of memory",
    )
    check(
        "a generate is walked along its route, never jumped",
        "generate_route[]" in src
        and "static bool walk_to(mapgen_t *mapgen, mapgen_job_id_t id," in src
        and "MapGenJobs_Advance(mapgen->jobs, id, generate_route[i])" in src,
        "PUBLISHING_MAP is not one edge from wherever a job happens to be, so "
        "a jump moved nothing and no generate could reach SUCCEEDED",
    )
    check(
        "the walk is answerable to the verdict's own evidence",
        "summary_accounts_for_route" in src
        and 'MAPGEN_DIAG_VERDICT_INCOMPLETE' in src,
        "a stage nobody can show happened is not walked past",
    )
    check(
        "publication is a Project commit, not a file copy",
        "MapGenPublish_Commit(&request, &report)" in src
        and "MAPGEN_PUBLISH_ERR_COLLISION" in src,
        "the map, its certificates, its recipe and its receipt are one set: "
        "either all of them are published under one manifest or none is",
    )
    check(
        "the Controller no longer moves files itself",
        "copy_file(" not in src and "rename(" not in src,
        "it used to copy the map, try the sidecars, ignore whether they "
        "arrived and return success",
    )
    check(
        "and it never replaces a map that is already there",
        "remove(dest" not in src and "remove(to)" not in src,
        "the old copy called remove() on the destination first, so a second "
        "job with the same name silently replaced the first",
    )
    check(
        "a name already taken becomes a new Project, not an overwrite",
        '"%s_%u"' in src and "mapgen->publish_name, attempt + 1" in src,
        "rebuilding into a new identity is the only replacement the player "
        "has agreed to",
    )
    check(
        "the verdict's own evidence must travel with the map",
        '"certificates"' in src and '"receipt"' in src
        and "m->required = certificates > 0" in src,
        "a certificate file that failed to copy must be distinguishable from "
        "a map that needed none",
    )
    check(
        "a publish that did not publish is not a success",
        "MAPGEN_DIAG_PUBLISH_FAILED" in src
        and "terminate_job(mapgen, id, MAPGEN_STATE_FAILED);" in src,
        "",
    )
    check(
        "a job directory is named for THIS job, not just its number",
        '"%08x_%02x%02x%02x%02x"' in src and '"%s/job_%s"' in src,
        "JobIds start at 1 every session, so the second session's first job "
        "inherited the first session's baseline and died with ERR_BASELINE",
    )
    check(
        "a worker starts in its own job directory",
        "desc.work_dir = mapgen->job_dir;" in src
        and "make_path(mapgen->job_dir);" in src,
        "the child used to start in the parent of every job, so a file it "
        "wrote 'here' landed beside other jobs rather than inside its own - "
        "and publication could not prove an artifact belonged to this job",
    )
    check(
        "and publication is told which directory that was",
        "request.job_dir" in src,
        "the artifact paths come from the worker's own summary; without the "
        "directory there is nothing to check them against",
    )
    check(
        "the published name outlives the request that asked for it",
        "mapgen->publish_name" in src
        and "request->generate.map_name" in src,
        "the request is deep-copied and gone before there is anything to "
        "publish",
    )
    check(
        "the worker is released with the job",
        "if (mapgen->worker_job == id) {" in src
        and "release_worker(mapgen);" in src,
        "",
    )
    check(
        "a failed launch still ends its job",
        "terminate_job(mapgen, id, MAPGEN_STATE_FAILED);" in src,
        "a job that vanishes has emitted no terminal event",
    )
    check(
        "a dead child is CRASHED however the death was observed",
        "static mapgen_state_t terminal_for(" in src
        and "!MapGenProcess_IsAlive(mapgen->worker) ||" in src
        and "MapGenProcess_WaitExit(mapgen->worker, MAPGEN_DEATH_SETTLE_MS, NULL)" in src,
        "a worker can die between HELLO and START, so the same death shows up "
        "as a failed read or a failed write depending on timing",
    )
    check(
        "the tick is bounded",
        "MAPGEN_TICK_MAX_FRAMES" in src and "for (int i = 0; i < MAPGEN_TICK_MAX_FRAMES; i++)" in src,
        "the client frame loop calls this; it must always return",
    )
    check(
        "cancel asks rather than kills",
        "MapGenProcess_RequestCancel(mapgen->worker)" in src
        and "TerminateProcess" not in src,
        "the worker stops at a checkpoint; the Controller decides the meaning",
    )
    check(
        "the Controller pulls in no client header",
        not re.search(r'#include\s+"(?!common/mapgen)', src),
        "the Seam must be testable without a running game",
    )
    # Hard Rule #22/#26 in miniature: an unfinished field sitting in a shipped
    # struct is a placeholder, and a placeholder is not a deliverable. The
    # request carries only what this milestone can actually honour.
    hdr_code = strip_c_comments(hdr_raw)
    request_body = ""
    # Non-greedy from the LAST `typedef struct {` before the closing tag, so a
    # preceding struct cannot be swept into the match.
    m = re.search(r"typedef struct \{((?:(?!typedef struct \{).)*?)\} mapgen_request_t;",
                  hdr_code, re.DOTALL)
    if m:
        request_body = m.group(1)
    # Every field of the request has to be acted on by the Controller. A
    # request carrying something nobody reads is a promise the Seam does not
    # keep, which is what "only what this milestone honours" was protecting.
    HONOURED = {
        "kind": "request->kind",
        "generate": "&request->generate",
    }
    unhonoured = [name for name, needle in HONOURED.items()
                  if name in request_body and needle not in src]
    check(
        "the request struct exists and every field of it is acted on",
        bool(request_body) and "kind;" in request_body and not unhonoured,
        f"fields: {request_body.strip()!r}; unread: {unhonoured}",
    )
    check(
        "and the job it carries is names, not paths",
        "donor_map[MAPGEN_REQUEST_NAME]" in hdr_code
        and "/" not in request_body and "\\" not in request_body,
        "contract 5.1: no caller supplies an OS path",
    )
    check(
        "no placeholder vocabulary anywhere in the public header",
        not re.search(r"\b(reserved|TODO|placeholder|not implemented|coming soon)\b",
                      hdr_code, re.IGNORECASE),
        "a reserved field is an unfinished item in a shipped interface",
    )


def build(cc: str, out: Path) -> tuple[Path, Path, Path, Path, Path, Path] | None:
    worker = out / ("worker.exe" if os.name == "nt" else "worker")
    crash = out / ("worker_crash.exe" if os.name == "nt" else "worker_crash")
    driver = out / ("ctl.exe" if os.name == "nt" else "ctl")
    flags = ["-std=c17", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc")]

    # The worker is built by the one place that knows what the worker is, so
    # the Controller's guard cannot drift from the lifecycle's.
    built = build_worker(cc, out, "ctl", [])
    if built is None:
        return None
    worker = built

    # A worker that dies right after HELLO, so the Controller's CHILD_GONE path
    # is exercised against a real process rather than reasoned about.
    built = build_worker(cc, out, "ctl_crash",
                         ["MAPGEN_WORKER_SELFTEST_CRASH_AFTER_HELLO=1"])
    if built is None:
        return None
    crash = built

    # A worker that stages a verdict of contract size. The synthetic job stages
    # an EMPTY result, so without this the delivery path is only ever proven
    # against a frame that carries nothing - which is how a receive buffer
    # eight times too small shipped.
    built = build_worker(cc, out, "ctl_summary",
                         ["MAPGEN_WORKER_SELFTEST_MAX_SUMMARY=1"])
    if built is None:
        return None
    summary_worker = built

    # A worker that stages a PUBLISHABLE verdict naming a file it wrote, so the
    # publish step answers to real bytes rather than to a state transition.
    built = build_worker(cc, out, "ctl_publish",
                         ["MAPGEN_WORKER_SELFTEST_PUBLISH=1"])
    if built is None:
        return None
    publish_worker = built

    # And one that stages a verdict accounting for nothing, so the requirement
    # is proven by behaviour rather than by the presence of a function name.
    built = build_worker(cc, out, "ctl_thin",
                         ["MAPGEN_WORKER_SELFTEST_PUBLISH=2"])
    if built is None:
        return None
    thin_worker = built
    p = subprocess.run([cc, "--version"], capture_output=True, text=True)
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None

    p = subprocess.run(
        [cc, *flags, str(DRIVER), str(SOURCE), *[str(d) for d in DEPS], "-o", str(driver)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return worker, crash, driver, summary_worker, publish_worker, thin_worker


def test_compiled() -> None:
    head("compiled: the Controller against a real worker")
    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        return
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_ctl_") as td:
        out = Path(td)
        built = build(cc, out)
        if not check("the Controller and worker compile with -Wall -Wextra -Werror", built is not None, ""):
            return
        assert built is not None
        worker, crash, driver, summary_worker, publish_worker, thin_worker = built

        log = out / "controller.out"
        with open(log, "wb") as fo:
            proc = subprocess.run(
                [str(driver), str(worker), str(out), str(crash),
                 str(summary_worker), str(publish_worker), str(thin_worker)],
                stdout=fo, stderr=subprocess.STDOUT, timeout=300, cwd=str(out),
            )
        text = log.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith(("  PASS", "  FAIL", "===")):
                print(line)

        m = re.search(r"=== (\d+) cases asserted, (\d+) failures", text)
        if not check("the test reported a result", m is not None, text[-800:]):
            return
        assert m is not None
        global CASES, FAILED
        CASES += int(m.group(1))
        FAILED += int(m.group(2))
        check("the compiled test passed", int(m.group(2)) == 0 and proc.returncode == 0, "")

        check("no worker process survived", _no_workers(), "a worker.exe is still running")


def _no_workers() -> bool:
    if os.name != "nt":
        return True
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process -Name 'worker','worker_crash','worker_ctl_summary',"
         "'worker_ctl_publish','worker_ctl_thin'"
         " -ErrorAction SilentlyContinue | Measure-Object).Count"],
        capture_output=True, text=True,
    )
    try:
        return int(p.stdout.strip() or "0") == 0
    except ValueError:
        return True


def main() -> int:
    print("=== MAPGEN-1 Controller contract")
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
