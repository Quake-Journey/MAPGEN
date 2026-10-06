#!/usr/bin/env python3
"""MAPGEN-1 M1 - worker lifecycle: static contract plus a real process matrix.

The M1 deliverable is "fixed helper, IPC, cancellation, zero off-state,
crash/timeout tests" (contract section 27). Everything below is exercised
against a REAL child process launched by the REAL host, because none of the
things that matter here - a job object, an inherited pipe, a process that
aborts mid-conversation, a handshake that never arrives - exist inside an
injected seam (Hard Rule #51).

The worker is compiled once per selftest mode. Those modes are COMPILE-TIME
and default to 0, so a production worker contains none of them and the host is
never asked to pass an argument, which it is not allowed to do anyway
(contract section 24).

Every case asserts, and every case that launches anything ends by proving the
process is gone. Hard Rule #46: "N cases captured" is not a result.

Run: python tools/check_mapgen_worker_lifecycle.py
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
HOST_SRC = REPO / "src" / "windows" / "mapgen_process.c"
HOST_HDR = REPO / "inc" / "common" / "mapgen_process.h"
WORKER_SRC = REPO / "src" / "mapgen_worker" / "main.c"
CODEC_SRC = REPO / "src" / "mapgen" / "mapgen_ipc.c"
DRIVER_SRC = REPO / "tools" / "mapgen_host_test_driver.c"

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


# ---------------------------------------------------------------------------
# Static contract
# ---------------------------------------------------------------------------
def test_static() -> None:
    head("static: process ownership and containment")
    host = strip_c_comments(HOST_SRC.read_text(encoding="utf-8"))
    worker = strip_c_comments(WORKER_SRC.read_text(encoding="utf-8"))

    check(
        "the child is put in a job object",
        "CreateJobObjectW" in host and "AssignProcessToJobObject" in host,
        "",
    )
    check(
        "the job kills its contents when the host closes",
        "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in host,
        "without this, engine exit can leave a worker or a compiler running",
    )
    check(
        "the child is created suspended and assigned before it runs",
        "CREATE_SUSPENDED" in host
        and host.index("AssignProcessToJobObject") < host.index("ResumeThread(host->thread);"),
        "a child that runs outside the job could spawn a grandchild that outlives us",
    )
    check(
        "the child gets no window",
        "CREATE_NO_WINDOW" in host,
        "",
    )
    check(
        "no shell is ever invoked",
        not re.search(r"cmd\.exe|powershell|system\s*\(|ShellExecute", host, re.IGNORECASE),
        "contract section 24 forbids a shell and any string built from user input",
    )
    check(
        "only the child's pipe ends are inheritable",
        host.count("SetHandleInformation") >= 2 and "HANDLE_FLAG_INHERIT, 0" in host,
        "a handle the child does not need is a handle it must not have",
    )
    check(
        "inheritance is restricted to an explicit handle list",
        "PROC_THREAD_ATTRIBUTE_HANDLE_LIST" in host and "EXTENDED_STARTUPINFO_PRESENT" in host,
        "without a list the child inherits EVERY inheritable handle we own, "
        "including a harness pipe it would then hold open after we exit",
    )
    check(
        "the child does not get the parent's stderr",
        "GetStdHandle(STD_ERROR_HANDLE)" not in host,
        "a surviving child holding the parent's stderr keeps a harness waiting for EOF",
    )
    check(
        "the executable is verified before launch",
        "GetFileAttributesA(desc->exe_path)" in host,
        "",
    )
    check(
        "the token is compared exactly",
        "memcmp(hello, desc->token, MAPGEN_IPC_TOKEN_BYTES)" in host,
        "",
    )
    check(
        "the build id is compared exactly",
        "desc->expected_build_id" in host and host.count("memcmp") >= 3,
        "",
    )
    check(
        "the job uuid in HELLO must be the one the host chose",
        "memcmp(header.job_uuid, host->job_uuid, MAPGEN_IPC_UUID_BYTES)" in host,
        "binding to whatever the child sent would make the identity check circular",
    )
    check(
        "a protocol violation latches on the host",
        "if (host->protocol_failed)" in host and host.count("host->protocol_failed = true;") >= 4,
        "",
    )
    check(
        "close terminates the job when the child will not go",
        "TerminateJobObject" in host,
        "",
    )
    check(
        "the payload is bounded against the caller's buffer too",
        "header->payload_len > payload_capacity" in host,
        "",
    )
    check(
        "the host pulls in no engine headers",
        not re.search(r'#include\s+"(?!common/mapgen_process\.h)', host),
        "the lifecycle must be testable outside a running game",
    )

    head("static: the worker")
    check(
        "the worker links against no engine service",
        # Its own files - a bare name, no directory - and the mapgen modules.
        # Anything else with a path in it is an engine service, which is what
        # contract 5.3 forbids; a sibling header is not one.
        not re.search(r'#include\s+"(?![^"/]+"|common/mapgen_)', worker),
        "no client Z_*, UI, renderer, command buffer or AVFX pool (contract 5.3)",
    )
    check(
        "the worker sets its pipes to binary mode",
        "_O_BINARY" in worker,
        "text mode would translate 0x0A inside a payload and corrupt frames "
        "only for data that happens to contain one",
    )
    check(
        "cancellation is observed at a checkpoint",
        "if (w->cancelled)" in worker,
        "",
    )
    check(
        "the worker never reports success itself",
        "MAPGEN_IPC_STAGED_RESULT" in worker and "MAPGEN_IPC_SUCCEEDED" not in worker,
        "STAGED_RESULT is not success; the Controller alone commits (contract 5.1)",
    )
    check(
        "selftest modes are compile-time and default to zero",
        worker.count("#define MAPGEN_WORKER_SELFTEST_") >= 6
        and re.search(r"#define MAPGEN_WORKER_SELFTEST_[A-Z_]+ 0", worker) is not None,
        "Hard Rule #37: a diagnostic path costs zero by default or it does not ship",
    )
    check(
        "the worker takes no arguments at all",
        "int main(void)" in worker,
        "the host is not allowed to assemble a command line",
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def gcc() -> str | None:
    return shutil.which("gcc") or shutil.which("cc")


# What the worker is, as of the day it started hosting a job. The lifecycle is
# still main.c and the codec; the rest is what the generate job runs, and it is
# here because a worker that does not link cannot be asked about its lifecycle.
WORKER_PARTS = [
    "src/mapgen_worker/main.c",
    "src/mapgen_worker/host.c",
    "src/mapgen_worker/generate.c",
    "src/mapgen/mapgen_ipc.c",
    "src/mapgen/mapgen_pipeline.c",
    # The pipeline calls the fidelity-zero chain, so anything
    # that links the pipeline links what it invents maps with.
    "src/mapgen/mapgen_synthesis.c",
    "src/mapgen/mapgen_architecture.c",
    "src/mapgen/mapgen_blueprint.c",
    "src/mapgen/mapgen_brush.c",
    "src/mapgen/mapgen_entities.c",
    "src/mapgen/mapgen_mapfile.c",
    "src/mapgen/mapgen_layout.c",
    "src/mapgen/mapgen_topology.c",
    "src/mapgen/mapgen_recipe.c",
    "src/mapgen/mapgen_mix.c",
    "src/mapgen/mapgen_random.c",
    "src/mapgen/mapgen_lineage.c",
    "src/mapgen/mapgen_training.c",
    "src/mapgen/mapgen_snapshot.c",
    "src/mapgen/mapgen_features.c",
    "src/mapgen/mapgen_wiring.c",
    "src/mapgen/mapgen_space.c",
    "src/mapgen/mapgen_genome.c",
    "src/mapgen/mapgen_transaction.c",
    "src/mapgen/mapgen_equivalence.c",
    "src/mapgen/mapgen_generate.c",
    "src/mapgen/mapgen_compiler.c",
    "src/mapgen/mapgen_divergence.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_reach.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    # The same P-core detection AVFX uses, so the compiler gets the
    # machine's fast cores instead of a guessed number.
    "src/common/q2prox_cpu_topology.c",
    "src/common/math.c",
]


# The engine code the worker links but does not own. It is built the way the
# product builds it; -Werror on somebody else's warnings is a claim about
# somebody else's code.
WORKER_ENGINE_PARTS = {"src/shared/shared.c", "src/common/math.c",
                       "src/common/q2prox_cpu_topology.c"}

WORKER_FLAGS = ["-std=c17", "-O1", "-Wall", "-Wextra",
                "-I", str(REPO / "inc"),
                "-I", str(REPO / "src" / "mapgen"),
                "-I", str(REPO / "src" / "mapgen_worker"),
                "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
                "-DUSE_NEW_GAME_API=0"]


def build_worker(cc: str, out_dir: Path, name: str, defines: list[str]) -> Path | None:
    """Compile MAPGEN's own units with -Werror, the engine's without, then link.

    Returns None on any failure, having printed what the compiler said.
    """
    exe = out_dir / f"worker_{name}.exe"
    objects: list[str] = []
    flags = WORKER_FLAGS + [f"-D{d}" for d in defines]

    for part in WORKER_PARTS:
        obj = out_dir / f"{name}_{Path(part).stem}.o"
        own = part not in WORKER_ENGINE_PARTS
        cmd = [cc, *flags]
        if own:
            cmd.append("-Werror")
        cmd += ["-c", str(REPO / part), "-o", str(obj)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout + proc.stderr)
            return None
        objects.append(str(obj))

    proc = subprocess.run([cc, *objects, "-o", str(exe), "-lm", "-lz"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout + proc.stderr)
        return None
    return exe


def build_driver(cc: str, out_dir: Path) -> Path | None:
    exe = out_dir / "host_driver.exe"
    proc = subprocess.run(
        [cc, "-std=c17", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER_SRC), str(HOST_SRC), str(CODEC_SRC), "-o", str(exe)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout + proc.stderr)
        return None
    return exe


def run_scenario(driver: Path, worker: Path, workdir: Path, scenario: str,
                 timeout: float = 15.0) -> dict[str, str]:
    """Run one scenario. A driver that never returns is a FINDING, not a crash.

    A controlled-RED mutation can easily make the host wait forever; the matrix
    has to report that as a failed case rather than die with a traceback, and it
    must not leave the driver or its child running either.
    """
    # Output goes to FILES, never to a pipe.
    #
    # A pipe would be inherited by whatever the driver launches, so a worker
    # that survives its host keeps the read end open and the harness waits for
    # an EOF that never comes - even after the driver itself has exited, and
    # even after a timeout kills it. That hung the very first controlled-RED
    # run of this subsystem. A file has no such property.
    log = workdir / f"scenario_{scenario}.out"
    err = workdir / f"scenario_{scenario}.err"
    try:
        with open(log, "wb") as fo, open(err, "wb") as fe:
            proc = subprocess.run(
                [str(driver), str(worker), str(workdir), scenario],
                stdout=fo, stderr=fe, timeout=timeout, cwd=str(workdir),
            )
        code = str(proc.returncode)
    except subprocess.TimeoutExpired:
        _kill_stragglers()
        code = "timeout"
    out: dict[str, str] = {"_exit": code}
    if code == "timeout":
        out["_timeout"] = "1"
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    out["_stderr"] = err.read_text(encoding="utf-8", errors="replace").strip()
    return out


def _kill_stragglers() -> None:
    if os.name != "nt":
        return
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process -Name 'worker_*','host_driver' -ErrorAction SilentlyContinue | "
         "Stop-Process -Force -ErrorAction SilentlyContinue"],
        capture_output=True,
    )


def pid_alive(pid: int) -> bool:
    if os.name != "nt" or pid <= 0:
        return False
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue | Measure-Object).Count"],
        capture_output=True, text=True,
    )
    try:
        return int(proc.stdout.strip() or "0") > 0
    except ValueError:
        return False


def assert_gone(name: str, result: dict[str, str]) -> None:
    pid = int(result.get("pid_launched", result.get("pid", "0")) or 0)
    if pid == 0:
        check(f"{name}: nothing was left running", True, "")
        return
    check(f"{name}: pid {pid} is gone after close", not pid_alive(pid), "the child outlived its host")


# ---------------------------------------------------------------------------
def test_behaviour(driver: Path, workers: dict[str, Path], workdir: Path) -> None:
    head("behaviour: launch and handshake")
    r = run_scenario(driver, workers["normal"], workdir, "handshake_only")
    check("a good worker completes the handshake", r.get("launch") == "OK", str(r))
    check("the first frame after HELLO is READY", r.get("first_frame_type") == "READY", str(r))
    assert_gone("handshake", r)

    r = run_scenario(driver, workers["normal"], workdir, "missing_exe")
    check("a missing executable fails cleanly", r.get("launch") == "EXE_MISSING", str(r))
    check("a failed launch returns no host", r.get("host_null") == "1", str(r))

    head("behaviour: the child must prove it is ours")
    r = run_scenario(driver, workers["bad_token"], workdir, "handshake_only")
    check("a worker with the wrong token is refused", r.get("launch") == "HANDSHAKE", str(r))
    check("the refused launch returns no host", r.get("host_null") == "1", str(r))
    assert_gone("bad token", r)

    r = run_scenario(driver, workers["bad_build_id"], workdir, "handshake_only")
    check("a worker from another build is refused", r.get("launch") == "HANDSHAKE", str(r))
    assert_gone("bad build id", r)

    r = run_scenario(driver, workers["normal"], workdir, "wrong_expected_build_id")
    check("a host expecting another build refuses this worker", r.get("launch") == "HANDSHAKE", str(r))
    assert_gone("wrong expected build", r)

    r = run_scenario(driver, workers["not_hello"], workdir, "handshake_only")
    check(
        "a worker whose first frame is not HELLO is refused",
        r.get("launch") == "HANDSHAKE",
        str(r),
    )
    assert_gone("first frame not hello", r)

    r = run_scenario(driver, workers["bad_uuid"], workdir, "handshake_only")
    check(
        "a worker that stamps its own job uuid is refused",
        r.get("launch") == "HANDSHAKE",
        str(r),
    )
    assert_gone("bad uuid", r)

    head("behaviour: a worker that never identifies itself")
    r = run_scenario(driver, workers["no_hello"], workdir, "short_handshake_timeout")
    check("the handshake times out instead of hanging", r.get("launch") == "TIMEOUT", str(r))
    check("the timed-out launch returns no host", r.get("host_null") == "1", str(r))
    assert_gone("no hello", r)

    head("behaviour: a job that runs to a staged result")
    r = run_scenario(driver, workers["normal"], workdir, "run_to_staged_result")
    check("the job reaches STAGED_RESULT", r.get("staged") == "1", str(r))
    check("progress was reported along the way", int(r.get("progress_frames", "0")) >= 5, str(r))
    check("the job was not cancelled", r.get("cancelled") == "0", str(r))
    assert_gone("staged result", r)

    head("behaviour: cancellation")
    r = run_scenario(driver, workers["normal"], workdir, "cancel_mid_job")
    check("cancel was accepted by the host", r.get("cancel_sent") == "OK", str(r))
    check("the worker answered CANCELLED", r.get("cancelled") == "1", str(r))
    check("it stopped before finishing the job", r.get("staged") == "0", str(r))
    check(
        "it stopped at a checkpoint rather than immediately",
        3 <= int(r.get("progress_frames", "0")) < 20,
        f"progress_frames={r.get('progress_frames')} - cancel is observed between bounded batches",
    )
    assert_gone("cancel", r)

    head("behaviour: the child dies mid-conversation")
    r = run_scenario(driver, workers["crash"], workdir, "crash_after_hello")
    check("the host notices the child is gone", r.get("after_crash") == "CHILD_GONE", str(r))
    check("the exit is observed", r.get("exited") == "1", str(r))
    check("the host reports it as not alive", r.get("alive") == "0", str(r))
    assert_gone("crash", r)

    head("behaviour: the child hangs")
    r = run_scenario(driver, workers["hang"], workdir, "hang_then_close")
    check("a receive on a silent child times out", r.get("receive") == "TIMEOUT", str(r))
    check("the child was still alive before close", r.get("alive_before_close") == "1", str(r))
    assert_gone("hang", r)

    head("behaviour: a desynchronised worker")
    r = run_scenario(driver, workers["desync"], workdir, "desync_after_hello")
    check("a replayed sequence is refused", r.get("first_frame") == "PROTOCOL", str(r))
    check(
        "the refusal latches: the next receive is still refused",
        r.get("second_frame") == "PROTOCOL",
        "a transport that desynchronised once must not resynchronise itself",
    )
    assert_gone("desync", r)

    head("behaviour: the host refuses to send nonsense")
    r = run_scenario(driver, workers["normal"], workdir, "send_wrong_direction")
    check("sending a worker-to-controller type is refused", r.get("send_worker_type") == "ARGUMENT", str(r))
    check("sending a controller-to-worker type is allowed", r.get("send_controller_type") == "OK", str(r))
    assert_gone("direction", r)

    r = run_scenario(driver, workers["normal"], workdir, "oversized_send")
    check("an over-ceiling payload is refused before it is written", r.get("oversized") == "PAYLOAD_TOO_LARGE", str(r))
    assert_gone("oversized", r)

    head("behaviour: no residue")
    check("no worker process survived the matrix", _no_worker_processes(), "a worker_*.exe is still running")


def _no_worker_processes() -> bool:
    if os.name != "nt":
        return True
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process -Name 'worker_*' -ErrorAction SilentlyContinue | Measure-Object).Count"],
        capture_output=True, text=True,
    )
    try:
        return int(proc.stdout.strip() or "0") == 0
    except ValueError:
        return True


def main() -> int:
    print("=== MAPGEN-1 worker lifecycle")
    # A leftover test worker from an interrupted run would make the residue
    # check fail for a reason that has nothing to do with this run.
    _kill_stragglers()
    test_static()

    head("building the real host, worker and driver")
    cc = gcc()
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_m1_") as td:
        out = Path(td)
        driver = build_driver(cc, out)
        if not check("the host and driver compile with -Wall -Wextra -Werror", driver is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1

        modes = {
            "normal": [],
            "crash": ["MAPGEN_WORKER_SELFTEST_CRASH_AFTER_HELLO=1"],
            "hang": ["MAPGEN_WORKER_SELFTEST_HANG_AFTER_HELLO=1"],
            "bad_token": ["MAPGEN_WORKER_SELFTEST_BAD_TOKEN=1"],
            "bad_build_id": ["MAPGEN_WORKER_SELFTEST_BAD_BUILD_ID=1"],
            "bad_uuid": ["MAPGEN_WORKER_SELFTEST_BAD_UUID=1"],
            "not_hello": ["MAPGEN_WORKER_SELFTEST_FIRST_FRAME_NOT_HELLO=1"],
            "desync": ["MAPGEN_WORKER_SELFTEST_DESYNC=1"],
            "no_hello": ["MAPGEN_WORKER_SELFTEST_NO_HELLO=1"],
        }
        workers: dict[str, Path] = {}
        for name, defines in modes.items():
            exe = build_worker(cc, out, name, defines)
            if not check(f"worker builds: {name}", exe is not None, ""):
                print(f"\n=== {CASES} cases asserted, {FAILED} failures")
                print("RESULT: FAIL")
                return 1
            assert exe is not None
            workers[name] = exe

        assert driver is not None
        test_behaviour(driver, workers, out)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
