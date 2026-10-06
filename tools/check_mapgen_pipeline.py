"""GF8: the product path gives one verdict, and the right one.

Generate, compile, validate, measure. The cases below drive each of the four
places it can refuse, and the point of every one of them is that a candidate
which passed some of the gates has not passed.

Most of them use the qualification harness's fake compiler, because a guard
that ran the real one would take two and a half minutes a case. Two do not: a
map that compiles and cannot be PLAYED can only be produced by really compiling
one, so the reachability fixture with a pit in it goes through the real pinned
compiler and must come back ERR_UNPLAYABLE, and the same fixture without the
pit must come back OK.

    python tools/check_mapgen_pipeline.py [--work DIR] [--no-real]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAKE = REPO / "tools" / "mapgen_fake_compiler.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, so every real case below had stopped at «the
# pinned compiler is where it should be» (found 2026-09-13, ledger row 274).
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\pipeline")

SOURCES = [
    "tools/mapgen_pipeline_driver.c",
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
    "src/common/q2prox_cpu_topology.c",
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
    "tools/mapgen_host_stubs.c",
]

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
    exe = out / "pipeline.exe"
    # Row 392: the linker map beside the executable, which is what a crash record's offsets are read against
    # (`tools/mapgen_crash_symbolicate.py`) - the same link, not a rebuild with symbols.
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(REPO / "inc"), "-I" + str(REPO / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / s) for s in SOURCES] + ["-o", str(exe), "-Wl,-Map=" + str(out / "pipeline.map"),
                                              "-lm", "-lz"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2500:])
        return None
    return exe


def fresh(work: Path, name: str) -> Path:
    job = work / name
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    return job


def verdict(exe: Path, args: list[str]) -> tuple[str, str]:
    run = subprocess.run([str(exe), *args], capture_output=True, text=True,
                         timeout=3600)
    lines = run.stdout.splitlines()
    return (lines[0].strip() if lines else ""), run.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--no-real", action="store_true")
    args = ap.parse_args()
    work = args.work
    work.mkdir(parents=True, exist_ok=True)

    print("=== MAPGEN-1 product path")
    if not check("the fake compiler and a donor are present",
                 FAKE.exists() and DONOR.exists()):
        return 1
    exe = build(work)
    if not check("the pipeline compiles", exe is not None):
        return 1
    assert exe

    print("\n=== a donor this compiler could have produced")
    #
    # The baseline gate compares the donor with the donor's own geometry
    # through THIS compiler. The fake answers every request with the same
    # synthetic cube, so q2dm1 as the donor is refused - rightly. One
    # throwaway run produces the cube; it is the donor for everything below,
    # and then the pipeline is being asked about verdicts rather than about a
    # baseline that was never going to match.
    #
    seed_job = fresh(work, "seed_donor")
    verdict(exe, [str(FAKE), str(DONOR), str(seed_job), "test", "100", "1",
                  "--fake", sys.executable, "success"])
    produced = seed_job / "baseline" / "test.bsp"
    # Kept out of the job tree, which belongs to the run that made it and is
    # not somewhere a later case may assume anything still is.
    fake_donor = work / "fake_donor.bsp"
    if produced.is_file():
        fake_donor.write_bytes(produced.read_bytes())
    if not check("the fake compiler produced a donor to fork",
                 fake_donor.is_file(), str(fake_donor)):
        print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
        return 1

    print("\n=== where it refuses, against a real child process")
    # The first compile a run does is the BASELINE - the donor's own geometry
    # through this compiler - so a compiler that cannot build anything fails
    # there, and the refusal names the reference rather than the schedule.
    for behaviour, expected in (("success", "OK"),
                                ("zero_exit_leak", "ERR_BASELINE"),
                                ("zero_exit_no_output", "ERR_BASELINE"),
                                ("zero_exit_missing_texture", "ERR_BASELINE"),
                                ("nonzero_exit", "ERR_BASELINE")):
        job = fresh(work, f"fake_{behaviour}")
        # Fidelity 100 against a compiler that returns the same map every time
        # is exactly on target, which is what makes `success` an OK rather than
        # an argument about the band.
        got, _ = verdict(exe, [str(FAKE), str(fake_donor), str(job), "test", "100",
                               "1", "--fake", sys.executable, behaviour])
        check(f"{behaviour} -> {expected}", got == expected, f"got {got!r}")

    job = fresh(work, "no_donor")
    got, _ = verdict(exe, [str(FAKE), str(work / "nothing.bsp"), str(job),
                           "test", "90", "1", "--fake", sys.executable,
                           "success"])
    check("a donor that is not there -> ERR_GENERATE", got == "ERR_GENERATE",
          f"got {got!r}")

    print("\n=== and the candidate answers to the DONOR, not only the baseline")
    #
    # Codex, section 1.6: divergence is measured from the baseline, so a loss
    # already tolerated in D-to-B is the zero everything else is measured from
    # and could be repeated without the number moving. At fidelity 100 nothing
    # is applied, so the candidate must BE the donor - the strongest form of
    # the check, and the one that can be asserted.
    #
    job = fresh(work, "candidate_is_donor")
    got, out = verdict(exe, [str(FAKE), str(fake_donor), str(job), "test",
                             "100", "1", "--fake", sys.executable, "success"])
    check("fidelity 100 produces a map that IS the donor",
          got == "OK", f"got {got!r}\n{out[-300:]}")

    print("\n=== and where it refuses a candidate that is not a fork")
    job = fresh(work, "band")
    got, out = verdict(exe, [str(FAKE), str(fake_donor), str(job), "test", "50",
                             "1", "--fake", sys.executable,
                             "success"])
    # Nothing was asked for and the band still bit: this is the case that says
    # a request which mentions no gate gets all of them.
    check("a candidate too like its donor, with nothing asked for"
          " -> ERR_TARGET_UNREACHABLE",
          got == "ERR_TARGET_UNREACHABLE", f"got {got!r}\n{out[-300:]}")

    if args.no_real:
        print("\n(the real compiler was not asked for)")
    elif not COMPILER.exists() or not GAME.exists():
        check("the pinned compiler is where it should be", False, str(COMPILER))
    else:
        print("\n=== and a map that compiles and cannot be played")
        sys.path.insert(0, str(REPO / "tools"))
        import mapgen_reach_fixtures as fixtures

        for name, expected in (("pocket", "ERR_UNPLAYABLE"),
                               ("open_room", "OK")):
            job = fresh(work, f"real_{name}")
            source = job / f"{name}.map"
            fixtures.FIXTURES[name](source)
            build_run = subprocess.run(
                [str(COMPILER), "-bsp", "-threads", "4", "-moddir", str(GAME),
                 "-basedir", str(GAME), "-gamedir", str(GAME), str(source)],
                capture_output=True, text=True, timeout=1800)
            donor = source.with_suffix(".bsp")
            if not check(f"the {name} fixture compiles as a donor",
                         donor.exists(), build_run.stdout[-300:]):
                continue

            run_job = fresh(work, f"real_{name}_job")
            got, out = verdict(exe, [str(COMPILER), str(donor), str(run_job),
                                     name, "100", "1", "--moddir", str(GAME)])
            check(f"{name} at fidelity 100 -> {expected}", got == expected,
                  f"got {got!r}\n{out[-400:]}")

    print("\n=== the product path spends one edit at a time")

    product = (REPO / "src" / "mapgen" / "mapgen_pipeline.c").read_text(
        encoding="utf-8", errors="replace")
    #
    # Either entry point opens a transaction on the donor. The pipeline uses
    # the one that also takes the other donors a room may be grafted from, and
    # which of the two it is was never what this case was about - the donor
    # being the map it opens on is.
    #
    check("it opens a transaction on the donor",
          "MapGenTransaction_Begin(donor_bsp, job_dir, map_name" in product
          or ("MapGenTransaction_BeginWithDonors(" in product
              and "donor_bsp, job_dir, map_name" in product))
    # row 395: every pass's attempt goes through attempt_or_replay, which
    # replays a resumed run's ledger and otherwise makes the one Try
    check("it attempts the schedule one edit at a time",
          "MapGenTransaction_Try(txn, &edit, &step)" in product
          or ("*verdict = MapGenTransaction_Try(txn, edit, step);" in product
              and product.count("attempt_or_replay(&replay, txn, ledger, i, planned, &edit, &verdict,"
                                " &step, &replayed)") == 3))
    check("the batch fork is not on the product path",
          "MapGenGenerate_Fork" not in product)
    check("it stops as soon as the target is reached",
          "if (MapGenTransaction_Divergence(txn) >= target)" in product)
    check("a run that spent nothing still builds a map",
          "MapGenTransaction_Materialise(txn, NULL)" in product)
    check("where the budget went is in the report",
          "report->by_verdict[verdict]++" in product)
    check("a schedule that ran out short is a refusal",
          "MAPGEN_PIPELINE_ERR_TARGET_UNREACHABLE" in product)
    check("and a compiler that built nothing is a different one",
          "if (report->by_verdict[MAPGEN_TXN_REJECTED_COMPILE])" in product)

    if not args.no_real:
        print("\n=== a fidelity this donor cannot reach is refused")
        name = "open_room"
        job = fresh(work, f"real_{name}")
        source = job / f"{name}.map"
        fixtures.FIXTURES[name](source)
        subprocess.run(
            [str(COMPILER), "-bsp", "-threads", "4", "-moddir", str(GAME),
             "-basedir", str(GAME), "-gamedir", str(GAME), str(source)],
            capture_output=True, text=True, timeout=1800)
        donor = source.with_suffix(".bsp")
        if check("the donor for it compiles", donor.exists()):
            run_job = fresh(work, "unreachable")
            got, out = verdict(exe, [str(COMPILER), str(donor), str(run_job),
                                     name, "50", "1",
                                     "--moddir", str(GAME)])
            check("fidelity 50 on a room with nothing in it"
                  " -> ERR_TARGET_UNREACHABLE",
                  got == "ERR_TARGET_UNREACHABLE", f"got {got!r}\n{out[-400:]}")
            check("and it says how much was missing",
                  "missing" in out, out[-300:])

            from mapgen_red_sandbox import Sandbox, hash_tree
            from mapgen_red_support import resolve_anchor
            before = hash_tree(REPO)
            box = Sandbox(REPO, "pipeline_band")
            try:
                target = box.root / "src" / "mapgen" / "mapgen_pipeline.c"
                data = target.read_bytes()
                anchor, replacement, count = resolve_anchor(
                    data,
                    b"        if (report->divergence.aggregate_permille\n"
                    b"            < report->divergence.target_permille)",
                    b"        if (false)")
                if check("the refusal to remove is where it says", count == 1,
                         f"{count} occurrences"):
                    target.write_bytes(data.replace(anchor, replacement, 1))
                    red = box.root / "red.exe"
                    red_run = subprocess.run(
                        ["gcc", "-std=c17", "-O2",
                         "-I" + str(box.root / "inc"),
                         "-I" + str(box.root / "src" / "mapgen"),
                         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
                         "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                        + [str(box.root / s) for s in SOURCES]
                        # zlib, because the pipeline links the snapshot the
                        # fidelity-zero chain learns from.
                        + ["-o", str(red), "-lm", "-lz"],
                        capture_output=True, text=True)
                    if check("the mutated path still compiles",
                             red_run.returncode == 0,
                             red_run.stderr[-600:]):
                        run_job = fresh(work, "near_copy")
                        got, out = verdict(red, [str(COMPILER), str(donor),
                                                 str(run_job), name, "50", "1",
                                                 "--moddir",
                                                 str(GAME)])
                        check("without it a run that fell short is blamed for"
                              " changing too much",
                              got == "ERR_CHANGED_TOO_MUCH",
                              f"got {got!r}\n{out[-300:]}")
            finally:
                box.dispose()
                check("the shared worktree was never opened for writing",
                      hash_tree(REPO) == before)

    if not args.no_real:
        print("\n=== and every attempt it makes is written down")
        #
        # Ledger row 272: the finishing pass and the graft pass ran after the
        # job's ledger was closed, so 6 of round 27's 604 attempts - an
        # UNPLAYABLE among them - were in neither the ledger nor its time sums.
        #
        # A room with a rocket launcher and two starts, one attempt of the
        # schedule: the finishing pass then tries to move a start (measured on
        # round 28, ledger row 274). The fake compiler's cube has one start and
        # no pickup, so no pass after the schedule ever tries anything there,
        # and a count taken on it cannot tell the defect from its fix.
        #
        import re
        import mapgen_reach_fixtures as fixtures
        from mapgen_red_sandbox import Sandbox, hash_tree
        from mapgen_red_support import resolve_anchor

        name = "item_reachable"
        job = fresh(work, f"real_{name}_ledger")
        source = job / f"{name}.map"
        fixtures.FIXTURES[name](source)
        subprocess.run(
            [str(COMPILER), "-bsp", "-threads", "4", "-moddir", str(GAME),
             "-basedir", str(GAME), "-gamedir", str(GAME), str(source)],
            capture_output=True, text=True, timeout=1800)
        donor = source.with_suffix(".bsp")

        def written_down(pipeline: Path, run_name: str) -> tuple[int, list[str]]:
            """What the run counted by verdict, and the attempts its ledger
            names."""
            run_job = fresh(work, run_name)
            _, out = verdict(pipeline, [str(COMPILER), str(donor), str(run_job),
                                        name, "50", "1", "--max-attempts", "1",
                                        "--moddir", str(GAME)])
            counted = re.search(r"^\s*ledger\s+(.*)$", out, re.M)
            total = (sum(int(n) for n in re.findall(r"=(\d+)", counted.group(1)))
                     if counted else -1)
            ledger_file = run_job / "ledger.txt"
            lines = (ledger_file.read_text(encoding="utf-8", errors="replace")
                     .splitlines() if ledger_file.is_file() else [])
            return total, [line for line in lines if re.match(
                r"\s*\d+ \S+\s+(ACCEPTED|REJECTED_[A-Z_]+)\s", line)]

        if check("the fixture for it compiles", donor.exists()):
            total, attempts = written_down(exe, "ledger")
            check("every verdict the run counts is a line in its ledger",
                  total > 0 and total == len(attempts),
                  f"counted {total}, written {len(attempts)}")
            check("and the finishing pass is among them",
                  any(" move-spawn " in line or " swap-item " in line
                      for line in attempts), "\n".join(attempts))

            before = hash_tree(REPO)
            box = Sandbox(REPO, "pipeline_ledger")
            try:
                target = box.root / "src" / "mapgen" / "mapgen_pipeline.c"
                data = target.read_bytes()
                anchor, replacement, count = resolve_anchor(
                    data,
                    b"            if (!replayed)\n"
                    b"                write_attempt(ledger, phase_ms, walk_sum, plan,"
                    b" i, planned,\n"
                    b"                              verdict, &step);\n"
                    b"            progress_attempt(replayed ? \"replay\" : \"finishing\",",
                    b"            progress_attempt(replayed ? \"replay\" : \"finishing\",")
                if check("the finishing pass's line to remove is where it says",
                         count == 1, f"{count} occurrences"):
                    target.write_bytes(data.replace(anchor, replacement, 1))
                    red = box.root / "red.exe"
                    red_run = subprocess.run(
                        ["gcc", "-std=c17", "-O2",
                         "-I" + str(box.root / "inc"),
                         "-I" + str(box.root / "src" / "mapgen"),
                         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
                         "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                        + [str(box.root / s) for s in SOURCES]
                        + ["-o", str(red), "-lm", "-lz"],
                        capture_output=True, text=True)
                    if check("the unwritten pass still compiles",
                             red_run.returncode == 0, red_run.stderr[-600:]):
                        total, attempts = written_down(red, "ledger_red")
                        check("without it the ledger is short of what the run"
                              " counted", total > len(attempts),
                              f"counted {total}, written {len(attempts)}")
            finally:
                box.dispose()
                check("the shared worktree was never opened for writing",
                      hash_tree(REPO) == before)

            #
            # Row 391 (Fable's brief 3, G1): the PROGRESS stream. MAPGEN Studio
            # shows what is being done from `progress.txt`, so a line must be
            # readable while the run is alive, and every attempt the ledger
            # names must be in it, in order, with the same verdict, between
            # the run's start and finish. RED with the stream's writer taken out:
            # the run leaves no account. (A flush-only RED cannot be made: the C
            # runtime flushes every stream before it spawns the compiler, so the
            # lines appear while the run is alive even unflushed - measured.)
            #
            import time as _time

            def streamed(pipeline: Path, run_name: str) -> tuple[int, list[str], list[str]]:
                """(lines read while the run was alive, the stream after it, the ledger's attempts)."""
                run_job = fresh(work, run_name)
                proc = subprocess.Popen([str(pipeline), str(COMPILER), str(donor), str(run_job), name, "50", "1",
                                         "--max-attempts", "2", "--moddir", str(GAME)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                alive_lines = 0
                stream = run_job / "progress.txt"
                while proc.poll() is None:
                    if stream.is_file():
                        alive_lines = max(alive_lines, sum(1 for ln in stream.read_text(
                            encoding="utf-8", errors="replace").splitlines() if ln.startswith("PROGRESS ")))
                    _time.sleep(0.01)
                lines = (stream.read_text(encoding="utf-8", errors="replace").splitlines()
                         if stream.is_file() else [])
                ledger_file = run_job / "ledger.txt"
                ledger = [ln for ln in (ledger_file.read_text(encoding="utf-8", errors="replace").splitlines()
                                        if ledger_file.is_file() else [])
                          if re.match(r"\s*\d+ \S+\s+(ACCEPTED|REJECTED_[A-Z_]+)\s", ln)]
                return alive_lines, lines, ledger

            alive, lines, ledger = streamed(exe, "progress")
            stages = [m.group(1) for m in (re.match(r"PROGRESS stage=(\S+)", ln) for ln in lines) if m]
            from_stream = [(m.group(1), m.group(2)) for m in (
                re.search(r"stage=attempt .*?edit=(\d+) .*?verdict=(\S+)", ln) for ln in lines) if m]
            from_ledger = [(m.group(1), m.group(2)) for m in (
                re.match(r"\s*(\d+) \S+\s+(\S+)", ln) for ln in ledger) if m]
            check("the progress stream is readable while the run is alive", alive > 0,
                  f"{alive} lines read before the run ended")
            check("it opens with the start, the baseline and the plan and closes with the finish",
                  stages[:3] == ["start", "baseline", "plan"] and stages[-1:] == ["finish"]
                  and "judge" in stages, " ".join(stages))
            check("every attempt the ledger names is in it, in order, with the same verdict",
                  bool(from_ledger) and from_stream == from_ledger,
                  f"stream {from_stream}; ledger {from_ledger}")
            before_p = hash_tree(REPO)
            pbox = Sandbox(REPO, "pipeline_progress")
            try:
                target = pbox.root / "src" / "mapgen" / "mapgen_pipeline.c"
                data = target.read_bytes()
                flag = b"static const bool g_progress_written = true;"
                if check("RED: the stream's writer is where the mutation says", data.count(flag) == 1,
                         f"{data.count(flag)} occurrences"):
                    target.write_bytes(data.replace(flag, b"static const bool g_progress_written = false;", 1))
                    red_p = pbox.root / "red_progress.exe"
                    built_p = subprocess.run(
                        ["gcc", "-std=c17", "-O2", "-I" + str(pbox.root / "inc"),
                         "-I" + str(pbox.root / "src" / "mapgen"), "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
                         "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                        + [str(pbox.root / s) for s in SOURCES] + ["-o", str(red_p), "-lm", "-lz"],
                        capture_output=True, text=True)
                    if check("the unwritten stream still compiles", built_p.returncode == 0, built_p.stderr[-600:]):
                        red_alive, red_lines, red_ledger = streamed(red_p, "progress_red")
                        check("RED: with the writer taken out the run leaves no account while alive or after,"
                              " its ledger still written - the case above goes red",
                              red_alive == 0 and not [ln for ln in red_lines if ln.startswith("PROGRESS ")]
                              and bool(red_ledger),
                              f"{red_alive} lines read while alive, {len(red_lines)} after, ledger {len(red_ledger)}")
            finally:
                pbox.dispose()
                check("the shared worktree was never opened for writing", hash_tree(REPO) == before_p)

            #
            # Row 392 (Fable's brief 3, G2): the CRASH RECORD. Rows 341 and 348
            # lost two 0xC0000005 crashes to «Windows kept no crash record». The
            # driver's test seam `--crash-at 1` faults at the first candidate:
            # the run ends with the fault's own code and leaves `crash.txt`
            # (the code, the last PROGRESS line, the offsets) and a minidump,
            # and the offsets read against the build name the seam. RED with
            # the filter not installed: the same fault leaves nothing.
            #
            from mapgen_crash_symbolicate import symbolicate

            def crashed(pipeline: Path, run_name: str) -> tuple[int, Path]:
                run_job = fresh(work, run_name)
                r = subprocess.run([str(pipeline), str(COMPILER), str(donor), str(run_job), name, "50", "1",
                                    "--max-attempts", "1", "--crash-at", "1", "--moddir", str(GAME)],
                                   capture_output=True, text=True, timeout=1800)
                return r.returncode & 0xFFFFFFFF, run_job

            code, cjob = crashed(exe, "crash")
            record = cjob / "crash.txt"
            dumps = list(cjob.glob("crash_*.dmp"))
            text = record.read_text(encoding="utf-8", errors="replace") if record.is_file() else ""
            check("a fault ends the run with its own code, 0xC0000005", code == 0xC0000005, f"exit 0x{code:08X}")
            check("and leaves crash.txt with the code and the last PROGRESS line, and a minidump",
                  "crash code 0xc0000005" in text and "last stage=" in text
                  and bool(dumps) and dumps[0].stat().st_size > 0,
                  f"{text[:200]!r}; dumps {[d.name for d in dumps]}")
            said = symbolicate(record, exe, exe.parent / "pipeline.map") if record.is_file() else []
            check("and its offsets read against the build name the fault's place - the seam",
                  any(ln.startswith("at crash_seam+") for ln in said), "; ".join(said[:6]))
            before_c = hash_tree(REPO)
            cbox = Sandbox(REPO, "pipeline_crash")
            try:
                target = cbox.root / "tools" / "mapgen_pipeline_driver.c"
                data = target.read_bytes()
                flag = b"static const bool g_crash_filter = true;"
                if check("RED: the crash filter is where the mutation says", data.count(flag) == 1,
                         f"{data.count(flag)} occurrences"):
                    target.write_bytes(data.replace(flag, b"static const bool g_crash_filter = false;", 1))
                    red_c = cbox.root / "red_crash.exe"
                    built_c = subprocess.run(
                        ["gcc", "-std=c17", "-O2", "-I" + str(cbox.root / "inc"),
                         "-I" + str(cbox.root / "src" / "mapgen"), "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
                         "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                        + [str(cbox.root / s) for s in SOURCES] + ["-o", str(red_c), "-lm", "-lz"],
                        capture_output=True, text=True)
                    if check("the filterless driver still compiles", built_c.returncode == 0, built_c.stderr[-600:]):
                        red_code, red_job = crashed(red_c, "crash_red")
                        check("RED: with the filter not installed the same fault leaves no record - the case"
                              " above goes red", red_code == 0xC0000005 and not (red_job / "crash.txt").exists()
                              and not list(red_job.glob("crash_*.dmp")),
                              f"exit 0x{red_code:08X}, {[p.name for p in red_job.iterdir()]}")
            finally:
                cbox.dispose()
                check("the shared worktree was never opened for writing", hash_tree(REPO) == before_c)

            #
            # Row 394 (MAPGEN Studio's «what may change»): `--skip-family NAME`
            # keeps the run from trying that family in any pass. The fixture's
            # finishing pass tries swap-item and move-spawn (asserted above);
            # with both skipped the ledger names neither. RED with the skip rule
            # taken out: they are tried again.
            #
            def families_tried(pipeline: Path, run_name: str) -> set:
                run_job = fresh(work, run_name)
                subprocess.run([str(pipeline), str(COMPILER), str(donor), str(run_job), name, "50", "1",
                                "--max-attempts", "1", "--skip-family", "swap-item", "--skip-family", "move-spawn",
                                "--moddir", str(GAME)], capture_output=True, text=True, timeout=1800)
                led = run_job / "ledger.txt"
                return {m.group(1) for m in re.finditer(r"^\s*\d+ (\S+)\s+(?:ACCEPTED|REJECTED_[A-Z_]+)\s",
                        led.read_text(encoding="utf-8", errors="replace") if led.is_file() else "", re.M)}

            tried = families_tried(exe, "skip_family")
            check("with swap-item and move-spawn skipped the run tries neither",
                  "swap-item" not in tried and "move-spawn" not in tried, f"tried {sorted(tried)}")
            before_s = hash_tree(REPO)
            sbox = Sandbox(REPO, "pipeline_skip")
            try:
                target = sbox.root / "src" / "mapgen" / "mapgen_pipeline.c"
                data = target.read_bytes()
                rule = b"        if (name && !strcmp(request->excluded_families[k], name))"
                if check("RED: the skip rule is where the mutation says", data.count(rule) == 1,
                         f"{data.count(rule)} occurrences"):
                    target.write_bytes(data.replace(rule, b"        if (false && name)", 1))
                    red_s = sbox.root / "red_skip.exe"
                    built_s = subprocess.run(
                        ["gcc", "-std=c17", "-O2", "-I" + str(sbox.root / "inc"),
                         "-I" + str(sbox.root / "src" / "mapgen"), "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
                         "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                        + [str(sbox.root / s) for s in SOURCES] + ["-o", str(red_s), "-lm", "-lz"],
                        capture_output=True, text=True)
                    if check("the skipless pipeline still compiles", built_s.returncode == 0, built_s.stderr[-600:]):
                        red_tried = families_tried(red_s, "skip_family_red")
                        check("RED: with the skip rule taken out the finishing pass tries them again - the case"
                              " above goes red", "swap-item" in red_tried or "move-spawn" in red_tried,
                              f"tried {sorted(red_tried)}")
            finally:
                sbox.dispose()
                check("the shared worktree was never opened for writing", hash_tree(REPO) == before_s)

            #
            # Row 395 (Fable's brief 3, G3): RESUME. The fixture run whole, then
            # the same run made to fault after its first accepted edit
            # (`--crash-at`) and resumed (`--resume`) on the same job folder: the
            # final map is the same file, byte for byte, and the ledger names the
            # same attempts with the same verdicts and divergences. RED with the
            # accepted attempt's .map altered on disk, and RED with the ledger
            # one row short: the resume stops, says it diverged and where.
            #
            import hashlib as _hashlib

            def run_job(job: Path, *extra: str) -> tuple[int, str]:
                import mapgen_load_guard as _load_guard
                r = _load_guard.run([str(exe), str(COMPILER), str(donor), str(job), name, "50", "1",
                                     "--max-attempts", "3", "--moddir", str(GAME), *extra],
                                    capture_output=True, text=True, timeout=1800)
                prog = job / "progress.txt"
                return r.returncode & 0xFFFFFFFF, prog.read_text(encoding="utf-8", errors="replace") if prog.is_file() else ""

            def ledger_rows(job: Path) -> list[str]:
                led = job / "ledger.txt"
                return [ln.split("  ms ")[0].rstrip()
                        for ln in (led.read_text(encoding="utf-8", errors="replace").splitlines() if led.is_file() else [])
                        if re.match(r"\s*\d+ \S+\s+(ACCEPTED|REJECTED_\S+)", ln)]

            def artifact_sha(progress: str) -> str:
                m = re.search(r'stage=finish .*?bsp="([^"]*)"', progress)
                p = Path(m.group(1)) if m and m.group(1) else None
                return _hashlib.sha256(p.read_bytes()).hexdigest() if p and p.is_file() else ""

            whole = fresh(work, "resume_whole")
            _, whole_prog = run_job(whole)
            whole_rows = ledger_rows(whole)
            first_acc = next((int(r.split()[0]) for r in whole_rows if " ACCEPTED " in r), None)
            if check("the whole run accepts an edit to replay", first_acc is not None, f"{len(whole_rows)} rows"):
                broken = fresh(work, "resume_broken")
                code, _ = run_job(broken, "--crash-at", str(first_acc + 2))
                before_rows = ledger_rows(broken)
                check("the run made to fault after its first accepted edit faults, that edit in its ledger",
                      code == 0xC0000005 and any(" ACCEPTED " in r for r in before_rows),
                      f"exit 0x{code:08X}, {len(before_rows)} rows")
                rcode, resumed_prog = run_job(broken, "--resume")
                check("resumed, it replays its ledger and goes on", rcode == 0 and "stage=resume replayed=" in resumed_prog,
                      f"exit {rcode}")
                check("and makes the same map, byte for byte, as the whole run",
                      artifact_sha(resumed_prog) != "" and artifact_sha(resumed_prog) == artifact_sha(whole_prog),
                      f"{artifact_sha(resumed_prog)[:16]} vs {artifact_sha(whole_prog)[:16]}")
                check("with the same attempts, verdicts and divergences in its ledger",
                      ledger_rows(broken) == whole_rows, f"{len(ledger_rows(broken))} vs {len(whole_rows)} rows")
                # RED: the accepted attempt's .map altered - the record and the files disagree
                red = fresh(work, "resume_red")
                run_job(red, "--crash-at", str(first_acc + 2))
                # an attempt's folder is numbered by its place in the ledger (every try counts, compiled or not)
                red_rows = ledger_rows(red)
                at = next((k for k, r in enumerate(red_rows) if " ACCEPTED " in r), None)
                target_map = red / f"try_{at:04d}" / f"{name}.map" if at is not None else None
                if target_map and target_map.is_file():
                    with open(target_map, "ab") as f:
                        f.write(b"// altered\n")
                rcode, red_prog = run_job(red, "--resume")
                check("RED: with an accepted attempt's .map altered the resume stops and says it diverged, and"
                      " where - the case above goes red",
                      rcode != 0 and "stage=resume-diverged" in red_prog and "differs" in red_prog,
                      next((ln for ln in red_prog.splitlines() if "diverged" in ln), red_prog[-200:]))
                # RED (the brief's own): the ledger one row short - the record skips an attempt the schedule makes
                red2 = fresh(work, "resume_red_row")
                run_job(red2, "--crash-at", str(first_acc + 2))
                led = red2 / "ledger.txt"
                lines = led.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                first_row = next((k for k, ln in enumerate(lines) if re.match(r"\s*\d+ \S+\s+(ACCEPTED|REJECTED_\S+)", ln)), None)
                if first_row is not None:
                    del lines[first_row]
                    led.write_text("".join(lines), encoding="utf-8")
                rcode, red2_prog = run_job(red2, "--resume")
                check("RED: with the ledger one row short the resume stops and says which attempt the record lacks",
                      rcode != 0 and "stage=resume-diverged" in red2_prog and "the schedule offers" in red2_prog,
                      next((ln for ln in red2_prog.splitlines() if "diverged" in ln), red2_prog[-200:]))

    print("\n=== and the gates are not optional")

    header = (REPO / "inc" / "common" / "mapgen_pipeline.h").read_text(
        encoding="utf-8", errors="replace")
    # the whole struct, from its own opening (row 410: a fixed 4000 characters before its end stopped reaching
    # diagnostic_no_band once the light flags and keys and their comments grew the struct)
    end = header.index("} mapgen_pipeline_request_t")
    request = header[header.rindex("typedef struct {", 0, end):end]
    check("a zeroed request is the FULLY gated one",
          "bool                      diagnostic_no_band;" in request
          and "bool                      require_band;" not in request)
    check("and there is no other way to switch a gate off",
          not any(word in request for word in
                  ("require_items", "skip_", "no_reach", "check_items",
                   "require_landmarks", "enable_")))

    job = fresh(work, "diagnostic")
    got, out = verdict(exe, [str(FAKE), str(fake_donor), str(job), "test", "50",
                             "1", "--diagnostic", "--fake", sys.executable,
                             "success"])
    check("a run that asked for the number says DIAGNOSTIC, not OK",
          got == "DIAGNOSTIC", f"got {got!r}\n{out[-300:]}")

    print("\n=== and a candidate nobody measured does not pass")

    impl = (REPO / "src" / "mapgen" / "mapgen_pipeline.c").read_text(
        encoding="utf-8", errors="replace")
    check("the diagnostic verdict is not reachable from the product one",
          "return MAPGEN_PIPELINE_DIAGNOSTIC;" in impl
          and impl.index("return MAPGEN_PIPELINE_DIAGNOSTIC;")
              < impl.index("return MAPGEN_PIPELINE_OK;\n}"))
    check("the product path runs the COMPLETE oracle",
          "true, &report->divergence)" in impl)
    check("and takes its routes from the walks the run already has, when it"
          " has both (D19)",
          "MapGenTransaction_TakeBaselineWalk(txn)" in impl
          and "MapGenDivergence_MeasureWalked(donor, baseline_walk, true,"
              " candidate," in impl
          and "rr == MAPGEN_REACH_OK" in impl)
    check("a donor that will not load is a refusal, not a pass",
          "if (!donor) {" in impl and "MAPGEN_PIPELINE_ERR_NOT_MEASURED" in impl)
    check("an incomplete measurement is a refusal too",
          "!report->divergence.complete" in impl)

    if not args.no_real:
        # One variable: the oracle runs with an axis missing. Everything that
        # passed has to stop passing, because nothing measured it.
        from mapgen_red_sandbox import Sandbox, hash_tree
        from mapgen_red_support import resolve_anchor

        before = hash_tree(REPO)
        box = Sandbox(REPO, "pipeline")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_divergence.c"
            data = target.read_bytes()
            anchor, replacement, count = resolve_anchor(
                data,
                b"    out->motifs_measured = true;",
                b"    out->motifs_measured = false;")
            if check("the axis to switch off is where it says", count == 1,
                     f"{count} occurrences"):
                target.write_bytes(data.replace(anchor, replacement, 1))
                red = box.root / "red.exe"
                red_run = subprocess.run(
                    ["gcc", "-std=c17", "-O2",
                     "-I" + str(box.root / "inc"),
                     "-I" + str(box.root / "src" / "mapgen"),
                     "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
                     "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                    + [str(box.root / s) for s in SOURCES]
                    # zlib, because the pipeline links the snapshot the
                        # fidelity-zero chain learns from.
                        + ["-o", str(red), "-lm", "-lz"],
                    capture_output=True, text=True)
                if check("the incomplete oracle still compiles",
                         red_run.returncode == 0, red_run.stderr[-600:]):
                    job = fresh(work, "unmeasured")
                    got, _ = verdict(red, [str(FAKE), str(fake_donor), str(job),
                                           "test", "90", "1", "--fake",
                                           sys.executable, "success"])
                    check("a candidate measured with an axis missing"
                          " -> ERR_NOT_MEASURED",
                          got == "ERR_NOT_MEASURED", f"got {got!r}")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing",
                  hash_tree(REPO) == before)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
