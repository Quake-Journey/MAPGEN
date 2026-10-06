"""The product's generator entry point produces exactly what the tool did.

Moving a pipeline behind an interface is the kind of change that is obviously
safe and occasionally is not. The only way to show it here is to run both over
the same donor, fidelity and seed and require the two `.map` files to be
identical byte for byte - not similar, not equivalent, identical - because the
writer is deterministic and anything else means something moved.

Also asserted: fidelity 100 writes the donor's own geometry, a request outside
0..100 is refused rather than clamped, and a donor that is not a map is refused
with its own code instead of producing an empty candidate.

    python tools/check_mapgen_generate_contract.py [--work DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\generate")

MODULES = [
    "src/mapgen/mapgen_generate.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_trace.c",
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


def build(work: Path, driver: str, name: str) -> Path | None:
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    exe = out / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I" + str(REPO / "inc"), "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0",
         "-DUSE_SERVER=0", str(REPO / driver)]
        + [str(REPO / m) for m in MODULES if m != "src/mapgen/mapgen_generate.c"
           or name == "module"]
        + ["-o", str(exe), "-lm"], capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2500:])
        return None
    return exe


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    args = ap.parse_args()
    work = args.work
    work.mkdir(parents=True, exist_ok=True)

    print("=== MAPGEN-1 generator entry point")
    if not check("the donor is where it should be", DONOR.exists(), str(DONOR)):
        return 1

    module = build(work, "tools/mapgen_generate_driver.c", "module")
    tool = build(work, "tools/mapgen_geometry_fork.c", "tool")
    if not check("both drivers compile with -Wall -Wextra -Werror",
                 module is not None and tool is not None):
        return 1
    assert module and tool

    print("\n=== the same request produces the same candidate")
    for fidelity in (100, 90, 75, 50, 25, 0):
        a = work / f"module_{fidelity}.map"
        b = work / f"tool_{fidelity}.map"
        ra = subprocess.run([str(module), str(DONOR), str(a), str(fidelity), "1"],
                            capture_output=True, text=True, timeout=1800)
        rb = subprocess.run([str(tool), str(DONOR), str(b), str(fidelity), "1"],
                            capture_output=True, text=True, timeout=1800)
        if not check(f"fidelity {fidelity}: both wrote a candidate",
                     ra.returncode == 0 and rb.returncode == 0 and a.exists()
                     and b.exists(), (ra.stderr + rb.stderr)[-300:]):
            continue
        check(f"fidelity {fidelity}: identical byte for byte  [{digest(a)}]",
              a.read_bytes() == b.read_bytes(),
              "the interface changed what the pipeline produces")

    print("\n=== what it refuses")
    out = work / "refused.map"
    for bad in ("101", "-1"):
        run = subprocess.run([str(module), str(DONOR), str(out), bad, "1"],
                             capture_output=True, text=True, timeout=600)
        check(f"a fidelity of {bad} is refused rather than clamped",
              run.returncode != 0 and "ERR_ARGS" in run.stdout,
              run.stdout[-200:])

    missing = work / "not_a_map.bsp"
    missing.write_bytes(b"this is not a bsp")
    run = subprocess.run([str(module), str(missing), str(out), "50", "1"],
                         capture_output=True, text=True, timeout=600)
    check("a donor that is not a map is refused with its own code",
          run.returncode != 0 and "ERR_DONOR_REFUSED" in run.stdout,
          run.stdout[-200:])

    absent = work / "no_such_file.bsp"
    run = subprocess.run([str(module), str(absent), str(out), "50", "1"],
                         capture_output=True, text=True, timeout=600)
    check("a donor that is not there is refused with its own code",
          run.returncode != 0 and "ERR_DONOR_UNREADABLE" in run.stdout,
          run.stdout[-200:])

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
