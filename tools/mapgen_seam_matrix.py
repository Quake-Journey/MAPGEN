"""The controlled seam diagnosis: one variable at a time, on the fixture that
reproduces the defect in seconds.

A cause is established only when changing exactly one thing turns the same
named case GREEN and putting it back turns it RED again. Everything here is
built from the same sources with one define changed, so nothing else can be
responsible for a difference.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(r"O:\Claude2\q2pro")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\seam")
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")

FORK_SRC = ["tools/mapgen_geometry_fork.c", "src/mapgen/mapgen_geometry.c",
            "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_bsp.c",
            "src/mapgen/mapgen_trace.c"]
AUDIT_SRC = ["tools/mapgen_render_audit.c", "src/mapgen/mapgen_geometry.c",
             "src/mapgen/mapgen_bsp.c"]


def build(name: str, sources, defines=()) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    exe = WORK / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I" + str(REPO / "inc")]
        + [f"-D{d}" for d in defines]
        + [str(REPO / f) for f in sources] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[:1500])
        raise SystemExit(f"cannot build {name}")
    return exe


def compile_map(map_path: Path) -> bool:
    run = subprocess.run(
        [str(COMPILER), "-bsp", "-threads", "4", "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(map_path)],
        capture_output=True, text=True, timeout=1800)
    text = run.stdout + run.stderr
    return run.returncode == 0 and "ERROR" not in text \
        and "leaked" not in text.lower()


def fixture(name: str) -> Path:
    sys.path.insert(0, str(REPO / "tools"))
    import mapgen_geometry_fixtures as fixtures
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"{name}.map"
    fixtures.FIXTURES[name](path)
    if not compile_map(path):
        raise SystemExit(f"the fixture {name} will not compile")
    return path.with_suffix(".bsp")


def trial(label: str, donor: Path, defines=()) -> tuple[int, str]:
    fork = build("fork_" + label, FORK_SRC, defines)
    audit = build("audit_" + label, AUDIT_SRC, defines)
    again = WORK / f"{label}.map"
    run = subprocess.run([str(fork), str(donor), str(again), "100", "1"],
                         capture_output=True, text=True)
    if run.returncode != 0 or not compile_map(again):
        return -1, "the rebuild refused to compile"
    result = subprocess.run([str(audit), str(donor), str(again.with_suffix(".bsp"))],
                            capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    return result.returncode, lines[-2] if len(lines) >= 2 else ""


def main() -> int:
    import sys as _sys
    which = _sys.argv[1] if len(_sys.argv) > 1 else "faceted_wall"
    donor = fixture(which)
    print(f"donor {donor.name}\n")

    trials = [
        ("baseline", ()),
        ("synthetic_points", ("MAPGEN_PLANE_POINTS_FROM_WINDING=0",)),
        ("extent8192", ("MAPGEN_BASE_WINDING_EXTENT=8192.0f",)),
        ("extent1024", ("MAPGEN_BASE_WINDING_EXTENT=1024.0f",)),
        ("synth9", ("MAPGEN_PLANE_POINTS_FROM_WINDING=0",
                    "PLANE_POINT_DECIMALS=9")),
        ("synth12", ("MAPGEN_PLANE_POINTS_FROM_WINDING=0",
                     "PLANE_POINT_DECIMALS=12")),
        ("reversed", ("MAPGEN_REVERSE_BRUSH_ORDER=1",)),
        ("per_side_planes", ("MAPGEN_CANONICAL_PLANE_POINTS=0",)),
        ("decimals6", ("PLANE_POINT_DECIMALS=6",)),
        ("decimals9", ("PLANE_POINT_DECIMALS=9",)),
        ("decimals2", ("PLANE_POINT_DECIMALS=2",)),
        ("bevels", ("MAPGEN_WRITE_BEVELS=1",)),
        ("bevels9", ("MAPGEN_WRITE_BEVELS=1", "PLANE_POINT_DECIMALS=9")),
    ]
    for label, defines in trials:
        rc, summary = trial(label, donor, defines)
        verdict = "GREEN" if rc == 0 else "RED  "
        print(f"{verdict} {label:12s} {summary.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
