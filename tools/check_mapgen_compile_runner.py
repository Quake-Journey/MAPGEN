"""M5: the compile runner decides from artifacts, not from exit codes.

`MapCompile_RunProfile` is the half of the Adapter contract that judges. Its
whole reason for existing is that a compiler exits ZERO when it leaks, when a
texture is missing, when it writes nothing at all and when it writes a map
nobody can play - so every case below drives it against a REAL child process
and asserts the result code, because an in-process seam has no concept of an
exit code or a flooded pipe (Hard Rule #51).

The two things this cannot drive through a real child are a timeout and a
crash: `popen` reports neither, and both belong to the process Adapter in
src/windows, which owns job objects and exit-status decoding and is qualified
separately. The runner's handling of each is asserted through the flags that
Adapter would set.

    python tools/check_mapgen_compile_runner.py [--work DIR]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAKE = REPO / "tools" / "mapgen_fake_compiler.py"
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\compile")
SEED_MAP = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\gf6b\f100.map")

SOURCES = [
    "tools/mapgen_compile_driver.c",
    "src/mapgen/mapgen_compiler.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

# Every behaviour the fake compiler can produce, and what the runner must say
# about it. The ones that exit ZERO are the point of the whole file.
BEHAVIOURS = [
    ("success",                    "OK"),
    ("zero_exit_no_output",        "ERR_NO_OUTPUT"),
    ("zero_exit_leak",             "ERR_LEAKED"),
    ("zero_exit_leak_marker_only", "ERR_LEAKED"),
    ("zero_exit_leak_pts_only",    "ERR_LEAKED"),
    ("zero_exit_missing_texture",  "ERR_MISSING_ASSET"),
    ("zero_exit_wrong_semantics",  "ERR_SEMANTICS"),
    ("degenerate_output",          "ERR_SEMANTICS"),
    ("damaged_output",             "ERR_OUTPUT_UNREADABLE"),
    ("wrong_format",               "ERR_WRONG_FORMAT"),
    ("escape_path",                "ERR_ESCAPED_JOB_ROOT"),
    ("nonzero_exit",               "ERR_NONZERO_EXIT"),
    # Flooding must be SURVIVABLE: the evidence is bounded on the way in and
    # the whole stream is still counted, so a noisy compiler cannot fail a
    # build nor destroy the record of what it said first.
    ("log_flood",                  "OK"),
]

SIMULATED = [("timeout", "ERR_TIMEOUT"), ("crash", "ERR_CRASH"),
             ("launch", "ERR_LAUNCH")]

CASES = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
        FAILURES.append(name)
    return ok


def build(work: Path) -> Path | None:
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "compile_driver.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(REPO / "inc"), "-I" + str(REPO / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0"]
        + [str(REPO / s) for s in SOURCES] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2500:])
        return None
    return exe


def fresh_job(work: Path) -> Path:
    """A directory created empty for THIS attempt, with only the map in it.

    Also clears anything an earlier escape left beside it: a stale escaped file
    makes the containment check compare a listing with itself and see nothing,
    which is how that case first passed when it should not have.
    """
    for stray in work.glob("escaped*"):
        stray.unlink()
    job = work / "job"
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    shutil.copy2(SEED_MAP, job / "test.map")
    return job


def run_driver(exe: Path, work: Path, behaviour: str,
               extra: list[str] | None = None) -> str:
    job = fresh_job(work)
    run = subprocess.run(
        [str(exe), sys.executable, str(FAKE), behaviour, str(job), "test"]
        + (extra or []), capture_output=True, text=True, timeout=1800)
    return (run.stdout.splitlines() or [""])[0].strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    args = ap.parse_args()
    work = args.work
    work.mkdir(parents=True, exist_ok=True)

    print("=== MAPGEN-1 compile runner")
    if not check("the fake compiler and a seed map are present",
                 FAKE.exists() and SEED_MAP.exists(),
                 f"{FAKE} / {SEED_MAP}"):
        return 1

    exe = build(work)
    if not check("the runner compiles", exe is not None):
        return 1
    assert exe

    print("\n=== a real child process, one behaviour at a time")
    for behaviour, expected in BEHAVIOURS:
        got = run_driver(exe, work, behaviour)
        check(f"{behaviour} -> {expected}", got == expected, f"got {got!r}")

    print("\n=== what the process Adapter reports, and this must act on")
    for simulate, expected in SIMULATED:
        got = run_driver(exe, work, "success", ["--simulate", simulate])
        check(f"a {simulate} -> {expected}", got == expected, f"got {got!r}")

    print("\n=== budgets and a dirty directory")
    got = run_driver(exe, work, "success", ["--tiny-disk"])
    check("a run over its disk budget -> ERR_DISK_BUDGET",
          got == "ERR_DISK_BUDGET", f"got {got!r}")

    job = fresh_job(work)
    shutil.copy2(SEED_MAP, job / "test.bsp")
    run = subprocess.run(
        [str(exe), sys.executable, str(FAKE), "success", str(job), "test"],
        capture_output=True, text=True, timeout=1800)
    got = (run.stdout.splitlines() or [""])[0].strip()
    check("an output already in the directory -> ERR_DIRTY_JOB_DIR",
          got == "ERR_DIRTY_JOB_DIR", f"got {got!r}")

    print("\n=== the post-condition")
    job = fresh_job(work)
    run = subprocess.run(
        [str(exe), sys.executable, str(FAKE), "success", str(job), "test"],
        capture_output=True, text=True, timeout=1800)
    check("OK is only returned after a reread and a semantic check",
          "OK" in run.stdout and "reread 1  semantics 1" in run.stdout,
          run.stdout[:300])
    check("and it carries both digests",
          "sha256" in run.stdout and "semantic" in run.stdout,
          run.stdout[:300])

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
