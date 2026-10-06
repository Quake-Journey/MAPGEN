#!/usr/bin/env python3
"""MAPGEN-1 compiler qualification runner (phase M0).

This module is the executable form of the `MapCompilerAdapter` contract in
src/mapgen/mapgen_compiler.h. It runs a compile profile through SOME adapter -
the fake process adapter at M0, the real pinned compiler at M0Q - and then
decides the result from ARTIFACTS, never from the adapter's exit code.

The single law it enforces:

    A zero exit code is not success. A result is OK only when the produced BSP
    was reread by the independent oracle AND its semantic expectations were
    checked. Both facts are recorded as flags on the report and the final gate
    refuses to emit OK unless both are true.

That refusal is not a comment. `CompileReport.finish()` raises if asked to
return OK without `reread_performed` and `semantics_checked`, so the invariant
cannot be lost by editing a branch somewhere else.

Contract references: sections 16 (pipeline), 17 (adapter and qualification),
18 (hard validation profiles), 10 (determinism).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_bsp_oracle as oracle  # noqa: E402

LEAK_MARKER = "**** leaked ****"
MISSING_TEXTURE_MARKER = "WARNING: couldn't locate texture"

# Result codes. These mirror mapcompile_result_t in
# src/mapgen/mapgen_compiler.h and must stay in step with it; the M0 acceptance
# suite asserts that the two lists agree.
RESULTS = (
    "MAPCOMPILE_OK",
    "MAPCOMPILE_ERR_INVALID_REQUEST",
    "MAPCOMPILE_ERR_DIRTY_JOB_DIR",
    "MAPCOMPILE_ERR_LAUNCH",
    "MAPCOMPILE_ERR_TIMEOUT",
    "MAPCOMPILE_ERR_CRASH",
    "MAPCOMPILE_ERR_NONZERO_EXIT",
    "MAPCOMPILE_ERR_LEAKED",
    "MAPCOMPILE_ERR_MISSING_ASSET",
    "MAPCOMPILE_ERR_NO_OUTPUT",
    "MAPCOMPILE_ERR_STALE_OUTPUT",
    "MAPCOMPILE_ERR_OUTPUT_UNREADABLE",
    "MAPCOMPILE_ERR_WRONG_FORMAT",
    "MAPCOMPILE_ERR_SEMANTICS",
    "MAPCOMPILE_ERR_ESCAPED_JOB_ROOT",
    "MAPCOMPILE_ERR_DISK_BUDGET",
    "MAPCOMPILE_ERR_LOG_BUDGET",
    "MAPCOMPILE_ERR_CANCELLED",
    "MAPCOMPILE_ERR_IDENTITY",
)

PROFILE_DRAFT = "draft"
PROFILE_FINAL = "final"


class QualificationError(Exception):
    """The runner was asked to do something the contract forbids."""


@dataclass
class CompileRequest:
    job_dir: Path
    map_name: str
    profile: str = PROFILE_DRAFT
    threads: int = 1
    moddir: Path | None = None
    basedir: Path | None = None
    gamedir: Path | None = None
    timeout_s: float = 120.0
    max_log_bytes: int = 256 * 1024
    disk_budget_bytes: int = 64 * 1024 * 1024
    expect_format: str = "IBSP"
    expectations: dict = field(default_factory=dict)

    @property
    def map_path(self) -> Path:
        return self.job_dir / f"{self.map_name}.map"

    @property
    def bsp_path(self) -> Path:
        return self.job_dir / f"{self.map_name}.bsp"

    @property
    def pts_path(self) -> Path:
        return self.job_dir / f"{self.map_name}.pts"

    def stages(self) -> list[str]:
        # Draft: BSP plus a fast VIS, never LIGHT (contract section 18).
        # Final: BSP, full VIS and LIGHT on the accepted lineage.
        if self.profile == PROFILE_DRAFT:
            return ["bsp", "vis-fast"]
        if self.profile == PROFILE_FINAL:
            return ["bsp", "vis", "rad"]
        raise QualificationError(f"unknown profile {self.profile!r}")


@dataclass
class StageReport:
    stage: str
    argv: list[str]
    exit_code: int | None
    timed_out: bool
    crashed: bool
    duration_s: float
    stdout_total_bytes: int
    stdout_rolling_sha256: str
    stdout_truncated: bool
    stdout_captured: str


@dataclass
class CompileReport:
    request: CompileRequest
    stages: list[StageReport] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    result: str = "MAPCOMPILE_ERR_INVALID_REQUEST"
    reread_performed: bool = False
    semantics_checked: bool = False
    bsp_sha256: str | None = None
    bsp_bytes: int | None = None
    semantic_digest: str | None = None
    oracle_summary: dict | None = None
    job_dir_bytes: int = 0
    escaped_paths: list[str] = field(default_factory=list)

    def fail(self, code: str, detail: str) -> str:
        if code not in RESULTS:
            raise QualificationError(f"unknown result code {code!r}")
        self.failures.append(f"{code}: {detail}")
        self.result = code
        return code

    def finish_ok(self) -> str:
        """Emit success - only if the artifact was actually reread and judged.

        This is where "a zero exit code is never success" is enforced
        structurally rather than by convention.
        """
        if not self.reread_performed:
            raise QualificationError(
                "refusing MAPCOMPILE_OK: the compiled BSP was never reread by the oracle"
            )
        if not self.semantics_checked:
            raise QualificationError(
                "refusing MAPCOMPILE_OK: the semantic expectations were never checked"
            )
        self.result = "MAPCOMPILE_OK"
        return self.result

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "profile": self.request.profile,
            "map": self.request.map_name,
            "reread_performed": self.reread_performed,
            "semantics_checked": self.semantics_checked,
            "bsp_sha256": self.bsp_sha256,
            "bsp_bytes": self.bsp_bytes,
            "semantic_digest": self.semantic_digest,
            "job_dir_bytes": self.job_dir_bytes,
            "escaped_paths": self.escaped_paths,
            "failures": self.failures,
            "stages": [
                {
                    "stage": s.stage,
                    "argv": s.argv,
                    "exit_code": s.exit_code,
                    "timed_out": s.timed_out,
                    "crashed": s.crashed,
                    "duration_s": round(s.duration_s, 3),
                    "stdout_total_bytes": s.stdout_total_bytes,
                    "stdout_rolling_sha256": s.stdout_rolling_sha256,
                    "stdout_truncated": s.stdout_truncated,
                }
                for s in self.stages
            ],
        }


# ---------------------------------------------------------------------------
# Process adapter
# ---------------------------------------------------------------------------


class ProcessAdapter:
    """Launches a compiler executable and captures a BOUNDED log.

    The capture keeps a rolling hash and a total byte count of the WHOLE
    stream even when the retained text is truncated, because contract section
    17 requires the evidence to survive output flooding without letting the
    flood consume the disk budget.
    """

    def __init__(self, exe: list[str], name: str = "process"):
        self.exe = list(exe)
        self.name = name

    def build_argv(self, request: CompileRequest, stage: str) -> list[str]:
        argv = list(self.exe)
        if stage == "bsp":
            argv.append("-bsp")
        elif stage == "vis-fast":
            argv += ["-vis", "-fast"]
        elif stage == "vis":
            argv.append("-vis")
        elif stage == "rad":
            argv.append("-rad")
        else:
            raise QualificationError(f"unknown stage {stage!r}")
        if request.expect_format == "QBSP":
            argv.append("-qbsp")
        # Never rely on the default thread count: it is the machine's core
        # count (C0 finding F5) and contract section 10 forbids a result that
        # depends on the worker count.
        argv += ["-threads", str(request.threads)]
        if request.moddir is not None:
            argv += ["-moddir", str(request.moddir)]
        if request.basedir is not None:
            argv += ["-basedir", str(request.basedir)]
        # Without an explicit -gamedir the tool derives one from the input path
        # and walks upward out of the job root; contract section 5.6 forbids the
        # compiler resolving anything from a live or ambient location.
        if request.gamedir is not None:
            argv += ["-gamedir", str(request.gamedir)]
        argv.append(str(request.map_path))
        return argv

    def run_stage(self, request: CompileRequest, stage: str) -> StageReport:
        argv = self.build_argv(request, stage)
        started = time.monotonic()
        digest = hashlib.sha256()
        total = 0
        kept: list[bytes] = []
        kept_bytes = 0
        truncated = False
        timed_out = False
        crashed = False
        exit_code: int | None = None

        proc = subprocess.Popen(
            argv,
            cwd=str(request.job_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        # The reader MUST live on its own thread. A blocking read on a pipe does
        # not return until data arrives, so draining the child from this loop
        # would park here forever the moment the child goes quiet - and a
        # compiler that hangs after printing its banner is exactly the case the
        # timeout exists for. Found the hard way: the first version of this loop
        # never timed out on Windows and left an orphaned child behind.
        import queue
        import threading

        chunks: "queue.Queue[bytes | None]" = queue.Queue(maxsize=256)

        def _drain(stream, sink: "queue.Queue[bytes | None]") -> None:
            try:
                while True:
                    data = stream.read(65536)
                    if not data:
                        break
                    sink.put(data)
            except Exception:
                pass
            finally:
                sink.put(None)

        assert proc.stdout is not None
        reader = threading.Thread(target=_drain, args=(proc.stdout, chunks), daemon=True)
        reader.start()

        try:
            deadline = started + request.timeout_s
            eof = False
            while True:
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                try:
                    chunk = chunks.get(timeout=0.05)
                except queue.Empty:
                    if eof and proc.poll() is not None:
                        break
                    continue
                if chunk is None:
                    eof = True
                    if proc.poll() is not None:
                        break
                    continue
                total += len(chunk)
                digest.update(chunk)
                if kept_bytes < request.max_log_bytes:
                    room = request.max_log_bytes - kept_bytes
                    kept.append(chunk[:room])
                    kept_bytes += min(room, len(chunk))
                    if len(chunk) > room:
                        truncated = True
                else:
                    truncated = True
            if timed_out:
                _kill_tree(proc)
            else:
                exit_code = proc.wait()
        finally:
            if proc.poll() is None:
                _kill_tree(proc)
            try:
                proc.stdout.close()
            except Exception:
                pass
            reader.join(timeout=5)

        if exit_code is not None and exit_code < 0:
            crashed = True
        if os.name == "nt" and exit_code is not None and exit_code not in (0, 1, 2) and exit_code > 0x40000000:
            crashed = True

        return StageReport(
            stage=stage,
            argv=argv,
            exit_code=exit_code,
            timed_out=timed_out,
            crashed=crashed,
            duration_s=time.monotonic() - started,
            stdout_total_bytes=total,
            stdout_rolling_sha256=digest.hexdigest(),
            stdout_truncated=truncated,
            stdout_captured=b"".join(kept).decode("utf-8", "replace"),
        )


def _kill_tree(proc: subprocess.Popen) -> None:
    """Terminate a child and anything it spawned.

    The real compiler is the worker's child and belongs to the same bounded job
    tree (contract section 24); a timeout that leaves grandchildren alive is
    the orphan-process failure that section 24 forbids.
    """
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def fake_adapter(behavior: str) -> ProcessAdapter:
    script = Path(__file__).resolve().parent / "mapgen_fake_compiler.py"
    return ProcessAdapter([sys.executable, str(script), "--behavior", behavior], name=f"fake:{behavior}")


# ---------------------------------------------------------------------------
# Semantic checks against the independent oracle
# ---------------------------------------------------------------------------


def _flood_connected(bsp: oracle.Bsp, start, goal, step: int = 32, max_cells: int = 200000) -> bool:
    """Structural empty-space connectivity by a bounded grid flood.

    Explicitly NOT a playability proof: it ignores step height, hull size,
    gravity, movers and triggers. Contract section 18.3 requires a pmove-based
    state graph for that, which is M2/M5 work. This exists only so an M0
    fixture can assert that a doorway actually joins two rooms.
    """
    solid = oracle.CONTENTS["CONTENTS_SOLID"]

    def blocked(p) -> bool:
        return bool(bsp.point_contents(p) & solid)

    start_cell = tuple(int(round(v / step)) for v in start)
    goal_cell = tuple(int(round(v / step)) for v in goal)
    if blocked(tuple(c * step for c in start_cell)) or blocked(tuple(c * step for c in goal_cell)):
        return False
    seen = {start_cell}
    stack = [start_cell]
    while stack and len(seen) < max_cells:
        cell = stack.pop()
        if cell == goal_cell:
            return True
        for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            nxt = (cell[0] + d[0], cell[1] + d[1], cell[2] + d[2])
            if nxt in seen:
                continue
            if blocked(tuple(c * step for c in nxt)):
                continue
            seen.add(nxt)
            stack.append(nxt)
    return False


def structural_floor(bsp: oracle.Bsp) -> list[str]:
    """What every compiled map must have, whatever the recipe asked for.

    MEASURED on q2tools-220 07d8d893: a worldspawn with zero brushes compiles
    with exit code ZERO into a "map" with 0 nodes, 0 faces and one leaf, and
    only the VIS pass refuses it afterwards. Any profile that ever ran the BSP
    pass alone would otherwise publish an empty world, so this floor is
    unconditional rather than a per-fixture expectation.
    """
    problems: list[str] = []
    if not bsp.models:
        problems.append("compiled BSP has no models: there is no world")
    if not bsp.brushes:
        problems.append("compiled BSP has no brushes: nothing is solid")
    if not bsp.nodes:
        problems.append("compiled BSP has no nodes: the tree is degenerate")
    if bsp.num_faces == 0:
        problems.append("compiled BSP has no faces: nothing would render")
    return problems


def check_semantics(bsp: oracle.Bsp, expectations: dict) -> list[str]:
    """Compare the COMPILED artifact with expectations derived from the source.

    Every check reconstructs its answer from the BSP. Nothing here consults the
    compiler's log, its exit code, or the candidate graph that produced the map.
    """
    problems: list[str] = []

    problems.extend(structural_floor(bsp))

    want_classes = expectations.get("entity_classnames")
    if want_classes:
        got: dict[str, int] = {}
        for ent in bsp.entities():
            cn = ent.get("classname", "<none>")
            got[cn] = got.get(cn, 0) + 1
        for cn, count in sorted(want_classes.items()):
            if got.get(cn, 0) != count:
                problems.append(f"entity {cn}: expected {count}, compiled BSP has {got.get(cn, 0)}")

    allowed = expectations.get("textures_allowed")
    if allowed is not None:
        allowed_set = set(allowed)
        for name in bsp.texture_names():
            if name and name not in allowed_set:
                problems.append(f"texture {name!r} is outside the allowed set")

    for point in expectations.get("interior_points_empty", []):
        c = bsp.point_contents(tuple(point))
        if c & oracle.CONTENTS["CONTENTS_SOLID"]:
            problems.append(f"point {point} should be open space but is solid")

    for point in expectations.get("solid_points", []):
        c = bsp.point_contents(tuple(point))
        if not (c & oracle.CONTENTS["CONTENTS_SOLID"]):
            problems.append(f"point {point} should be solid but is not")

    for point in expectations.get("water_points", []):
        c = bsp.point_contents(tuple(point))
        if not (c & oracle.CONTENTS["CONTENTS_WATER"]):
            problems.append(f"point {point} should be water, contents are {bsp.contents_names(c)}")

    for point in expectations.get("lava_points", []):
        c = bsp.point_contents(tuple(point))
        if not (c & oracle.CONTENTS["CONTENTS_LAVA"]):
            problems.append(f"point {point} should be lava, contents are {bsp.contents_names(c)}")

    seen_contents = 0
    for leaf in bsp.leafs:
        seen_contents |= leaf.contents
    for brush in bsp.brushes:
        seen_contents |= brush.contents
    for name in expectations.get("required_contents", []):
        if not (seen_contents & oracle.CONTENTS[name]):
            problems.append(f"{name} is required but appears nowhere in the compiled BSP")
    for name in expectations.get("forbidden_contents", []):
        if seen_contents & oracle.CONTENTS[name]:
            problems.append(f"{name} is forbidden but appears in the compiled BSP")

    have_flags = set(bsp.surface_flag_names())
    for name in expectations.get("required_surface_flags", []):
        if name not in have_flags:
            problems.append(f"{name} is required but no texinfo carries it")

    bounds = expectations.get("world_bounds_contains")
    if bounds and bsp.models:
        want_mins, want_maxs = bounds
        m = bsp.models[0]
        for axis in range(3):
            if m.mins[axis] > want_mins[axis] or m.maxs[axis] < want_maxs[axis]:
                problems.append(
                    f"world model bounds {m.mins}..{m.maxs} do not contain {want_mins}..{want_maxs}"
                )
                break

    min_models = expectations.get("min_models")
    if min_models is not None and len(bsp.models) < min_models:
        problems.append(f"expected at least {min_models} models, compiled BSP has {len(bsp.models)}")

    for pair in expectations.get("connected_point_pairs", []):
        a, b = pair
        if not _flood_connected(bsp, tuple(a), tuple(b)):
            problems.append(f"points {a} and {b} are not connected through open space")

    return problems


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


def _inventory(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for p in root.rglob("*"):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return out


def run_profile(adapter: ProcessAdapter, request: CompileRequest, sandbox_root: Path | None = None) -> CompileReport:
    """Run every stage of a profile and judge the result from artifacts."""
    report = CompileReport(request=request)

    if not request.job_dir.is_dir():
        report.fail("MAPCOMPILE_ERR_INVALID_REQUEST", f"job dir does not exist: {request.job_dir}")
        return report
    if not request.map_path.is_file():
        report.fail("MAPCOMPILE_ERR_INVALID_REQUEST", f"input map missing: {request.map_path}")
        return report

    # C0 finding F1 made this load-bearing: this compiler deletes .prt/.pts at
    # start but never a stale .bsp, so a leaked run inside a reused directory
    # would present an OLD map as this attempt's output.
    if request.bsp_path.exists():
        report.fail(
            "MAPCOMPILE_ERR_DIRTY_JOB_DIR",
            f"{request.bsp_path.name} already exists before the attempt started",
        )
        return report

    before_job = _inventory(request.job_dir)
    before_sandbox = _inventory(sandbox_root) if sandbox_root is not None else None
    last_output_sha: str | None = None

    for stage in request.stages():
        try:
            stage_report = adapter.run_stage(request, stage)
        except OSError as exc:
            report.fail("MAPCOMPILE_ERR_LAUNCH", f"stage {stage}: {exc}")
            return report
        report.stages.append(stage_report)

        if stage_report.timed_out:
            report.fail("MAPCOMPILE_ERR_TIMEOUT", f"stage {stage} exceeded {request.timeout_s}s")
            return report
        if stage_report.crashed:
            report.fail("MAPCOMPILE_ERR_CRASH", f"stage {stage} terminated abnormally ({stage_report.exit_code})")
            return report
        if stage_report.exit_code != 0:
            report.fail("MAPCOMPILE_ERR_NONZERO_EXIT", f"stage {stage} exited {stage_report.exit_code}")
            return report

        # Exit code 0 says nothing. These two markers are the compiler telling
        # us it failed while claiming success (C0 findings F1 and F2).
        if LEAK_MARKER in stage_report.stdout_captured:
            report.fail("MAPCOMPILE_ERR_LEAKED", f"stage {stage} reported a leak with exit code 0")
            return report
        if MISSING_TEXTURE_MARKER in stage_report.stdout_captured:
            missing = [
                line.strip()
                for line in stage_report.stdout_captured.splitlines()
                if MISSING_TEXTURE_MARKER in line
            ]
            report.fail("MAPCOMPILE_ERR_MISSING_ASSET", "; ".join(missing[:8]))
            return report
        # Every pass after the BSP pass must actually rewrite the map: VIS adds
        # the visibility lump, LIGHT adds the lighting lump. A later stage that
        # leaves the file byte-identical did not run, whatever it printed, and
        # contract section 17 requires stale or unexpected output to be
        # rejected rather than carried forward.
        stage_sha: str | None = None
        if request.bsp_path.is_file():
            stage_sha = hashlib.sha256(request.bsp_path.read_bytes()).hexdigest()
        if last_output_sha is not None and stage_sha == last_output_sha:
            report.fail(
                "MAPCOMPILE_ERR_STALE_OUTPUT",
                f"stage {stage} left {request.bsp_path.name} byte-identical to the previous stage",
            )
            return report
        if stage_sha is not None:
            last_output_sha = stage_sha

        if stage_report.stdout_total_bytes > request.max_log_bytes:
            # Not fatal by itself: the rolling hash and total count preserve the
            # evidence. It is recorded so a flooding compiler is visible.
            report.failures.append(
                f"note: stage {stage} produced {stage_report.stdout_total_bytes} bytes of output, "
                f"retained {request.max_log_bytes}, rolling sha256 {stage_report.stdout_rolling_sha256}"
            )

    if request.pts_path.exists():
        report.fail("MAPCOMPILE_ERR_LEAKED", f"{request.pts_path.name} was produced")
        return report

    if sandbox_root is not None:
        after_sandbox = _inventory(sandbox_root)
        job_rel = str(request.job_dir.relative_to(sandbox_root)) if request.job_dir.is_relative_to(sandbox_root) else None
        for rel in sorted(set(after_sandbox) - set(before_sandbox or {})):
            if job_rel is None or not rel.startswith(job_rel):
                report.escaped_paths.append(rel)
        if report.escaped_paths:
            report.fail(
                "MAPCOMPILE_ERR_ESCAPED_JOB_ROOT",
                f"wrote outside the job root: {report.escaped_paths[:8]}",
            )
            return report

    after_job = _inventory(request.job_dir)
    report.job_dir_bytes = sum(size for size, _ in after_job.values())
    if report.job_dir_bytes > request.disk_budget_bytes:
        report.fail(
            "MAPCOMPILE_ERR_DISK_BUDGET",
            f"job directory grew to {report.job_dir_bytes} bytes, budget {request.disk_budget_bytes}",
        )
        return report

    if not request.bsp_path.is_file():
        report.fail("MAPCOMPILE_ERR_NO_OUTPUT", f"{request.bsp_path.name} was never written")
        return report
    rel_bsp = str(request.bsp_path.relative_to(request.job_dir))
    if rel_bsp in before_job and before_job[rel_bsp] == after_job[rel_bsp]:
        report.fail("MAPCOMPILE_ERR_STALE_OUTPUT", f"{rel_bsp} is unchanged from before the attempt")
        return report

    blob = request.bsp_path.read_bytes()
    report.bsp_bytes = len(blob)
    report.bsp_sha256 = hashlib.sha256(blob).hexdigest()

    try:
        bsp = oracle.load(request.bsp_path)
    except oracle.BspError as exc:
        report.fail("MAPCOMPILE_ERR_OUTPUT_UNREADABLE", f"oracle rejected the output: {exc}")
        return report
    except Exception as exc:  # a malformed file must never crash the runner
        report.fail("MAPCOMPILE_ERR_OUTPUT_UNREADABLE", f"oracle raised {type(exc).__name__}: {exc}")
        return report
    report.reread_performed = True

    got_format = "QBSP" if bsp.extended else "IBSP"
    if got_format != request.expect_format:
        report.fail("MAPCOMPILE_ERR_WRONG_FORMAT", f"expected {request.expect_format}, produced {got_format}")
        return report

    try:
        report.oracle_summary = bsp.summary()
        report.semantic_digest = report.oracle_summary["semantic_digest"]
    except oracle.BspError as exc:
        report.fail("MAPCOMPILE_ERR_OUTPUT_UNREADABLE", f"oracle could not summarize the output: {exc}")
        return report

    if request.profile == PROFILE_FINAL:
        if bsp.visibility_bytes <= 0:
            report.fail("MAPCOMPILE_ERR_SEMANTICS", "final profile requires visibility data")
            return report
        if bsp.lighting_bytes <= 0:
            report.fail("MAPCOMPILE_ERR_SEMANTICS", "final profile requires lighting data")
            return report

    problems = check_semantics(bsp, request.expectations)
    report.semantics_checked = True
    if problems:
        report.fail("MAPCOMPILE_ERR_SEMANTICS", "; ".join(problems[:8]))
        return report

    return_code = report.finish_ok()
    assert return_code == "MAPCOMPILE_OK"
    return report


def prepare_job_dir(root: Path, name: str, map_source: Path) -> Path:
    """Create a fresh, empty, non-reparse job directory and copy the input in."""
    job = root / name
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    st = job.lstat()
    if hasattr(st, "st_file_attributes"):
        reparse = 0x400
        if st.st_file_attributes & reparse:
            raise QualificationError(f"job dir is a reparse point: {job}")
    shutil.copyfile(map_source, job / map_source.name)
    return job


def main(argv: list[str]) -> int:
    print(json.dumps({"results": list(RESULTS), "profiles": [PROFILE_DRAFT, PROFILE_FINAL]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
