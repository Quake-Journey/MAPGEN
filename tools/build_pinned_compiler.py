"""Build the pinned map compiler from the source this repository carries.

MAPGEN's whole pipeline is defined against ONE compiler. Every divergence
number, every fidelity band and the baseline that fidelity 100 is measured
against are statements about what this program does with a `.map`, so shipping
a binary somebody downloaded would make all of them unverifiable.

The contract's own file list says `deps or subproject for pinned compiler
source`, and `deps/q2tools-220` is that source - GPLv2, the same licence as the
engine it ships beside, forked from the v220 tools distributed with J.A.C.K.

    python tools/build_pinned_compiler.py [--release DIR] [--build DIR]

It is a separate step from the meson build on purpose: the compiler is CMake's
and lives outside the engine's dependency graph, and a failure to build a tool
must not be able to fail the build of the game.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "deps" / "q2tools-220"
DEFAULT_BUILD = Path(r"O:\Claude2\q2pro-build\q2tools")
DEFAULT_RELEASE = Path(r"O:\Claude2\q2pro-release")

# Where it lands in the install, which is what the client's default points at.
INSTALL_SUBDIR = Path("baseq2") / "q2pro-x" / "utils"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_local_patches() -> bool:
    """Refuse to build a compiler whose source is missing a qualified patch.

    `deps/` is not under version control, so this source tree is the one thing
    in the chain that a clean checkout does not restore. Every local patch the
    pin has qualified - P7 through P12 - lives only here until somebody runs its
    script again, and a tree refreshed from upstream would build and deploy a
    compiler silently missing all of them.

    That is not hypothetical: P12 is the fix for a defect the PO reported for
    five days, P11 is why lightmaps are not grey, and P7 is why generated maps
    load at all. Losing them would look like the bugs coming back on their own.

    The list is read from the pin rather than written here, so a patch cannot be
    qualified without also being checked.
    """
    pin = json.loads((REPO / "tools" / "mapgen_compiler_pin.json")
                     .read_text(encoding="utf-8"))
    missing = []
    for patch in pin.get("local_patches", {}).get("applied", []):
        script = patch.get("applied_by")
        if not script:
            continue
        run = subprocess.run(
            [sys.executable, str(REPO / script), str(SOURCE), "--check"],
            capture_output=True, text=True)
        if run.returncode != 0:
            missing.append((patch.get("id", "?"), script,
                            (run.stdout + run.stderr).strip()[:120]))
    if not missing:
        return True
    print("the pinned compiler's source is missing patches the pin has qualified:")
    for pid, script, why in missing:
        print(f"  {pid}: {why or 'not applied'}")
        print(f"      python {script} {SOURCE}")
    print("Refusing to build. A compiler without these is not the pinned compiler.")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    ap.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    ap.add_argument("--skip-build", action="store_true",
                    help="install an existing binary without rebuilding it")
    args = ap.parse_args()

    if not (SOURCE / "CMakeLists.txt").is_file():
        print(f"the pinned compiler's source is not in {SOURCE}")
        return 1

    if not check_local_patches():
        return 1

    exe = args.build / "q2tool.exe"
    if not args.skip_build:
        args.build.mkdir(parents=True, exist_ok=True)
        configure = subprocess.run(
            ["cmake", "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
             "-S", str(SOURCE), "-B", str(args.build)],
            capture_output=True, text=True)
        if configure.returncode != 0:
            print((configure.stdout + configure.stderr)[-2000:])
            return 1
        build = subprocess.run(["cmake", "--build", str(args.build)],
                               capture_output=True, text=True)
        if build.returncode != 0:
            print((build.stdout + build.stderr)[-2000:])
            return 1

    if not exe.is_file():
        print(f"no compiler came out of the build: {exe}")
        return 1

    #
    # And the bytes about to be installed must be bytes M0Q has passed.
    #
    # Checking that the SOURCE carries its patches is not the same statement:
    # a local MinGW build is not bit-reproducible, so what comes out here is
    # never the binary the pin qualified, and --skip-build can install an
    # executable that was never built from this source at all. Codex,
    # 2026-09-06 section 4: reject a missing or mismatched receipt, including
    # the existing-binary path.
    #
    sys.path.insert(0, str(REPO / "tools"))
    from mapgen_qualified_compilers import why_not, RECEIPTS  # noqa: E402
    reason = why_not(exe)
    if reason:
        print(f"the compiler that came out of the build is not qualified: {reason}")
        print("Run the complete M0Q on these exact bytes and carry the result:")
        print(f"  python tools/run_mapgen_m0q_qualification.py --compiler {exe}"
              f" --source {SOURCE} --json {RECEIPTS}/m0q_<date>_<sha16>.json")
        print("Refusing to install an unqualified map compiler.")
        return 1

    target_dir = args.release / INSTALL_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "q2tool.exe"
    shutil.copy2(exe, target)

    print(f"pinned compiler: {target}")
    print(f"  sha256 {sha256_of(target)}  (M0Q receipt on file)")
    print(f"  from   {SOURCE} (GPLv2, carried in this repository)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
