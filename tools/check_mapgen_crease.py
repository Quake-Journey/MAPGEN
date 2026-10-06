"""Do two wall panels that meet at a shallow angle still meet after a rebuild?

This is the defect the PO reported for five days and filmed on 2026-09-06: a
vertical strip of sky in the middle of a wall in a fidelity-100 fork of q2dm1.
It is not a hole in the solid - the collision hull is intact - and it is not
the writer. It is the position of the edge where two panels meet.

q2dm1's courtyard has two panels 1.1 degrees apart, at x = 896, y = 150. The
edge they share is the intersection of two nearly-parallel planes, so an error
of e in either plane moves it by e / sin(1.1 deg) = 52 e. The pinned compiler
cut every winding out of a quad 2^20 units wide in SINGLE precision, which puts
up to 0.0625 units into every winding, and 52 x 0.0625 is three units of wall
that nothing draws. Local patch P12 sizes that quad to the world instead.

    python tools/check_mapgen_crease.py [--work DIR] [--skip-red]

Cases:
    the compiler carries P12 and is the binary the pin names;
    a two-brush fixture, spelled the way the WRITER spells it, closes;
    the same fixture spelled the way an EDITOR would, closes;
    q2dm1 forked at fidelity 100 closes, and draws every point of its donor.

Then a controlled RED on the cause itself: a compiler built from the same
source with P12 removed must reopen the fixture crease by more than a unit -
and the writer, unchanged, cannot close it. That is what makes this a compiler
defect rather than a writer defect, and it is asserted rather than argued.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard          # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
SOURCE = REPO / "deps" / "q2tools-220"
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260906\creasegate")

FORK_SRC = ["tools/mapgen_geometry_fork.c", "src/mapgen/mapgen_geometry.c",
            "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c", "src/mapgen/mapgen_bsp.c",
            "src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_rooms.c",
            "src/mapgen/mapgen_bundle.c", "src/mapgen/mapgen_closure.c"]
HOLES_SRC = ["tools/mapgen_visible_holes.c", "src/mapgen/mapgen_bsp.c"]

# The two panels, as q2dm1 has them.
PANEL_C = ((-0.4856429312, -0.8741572761, 0.0), -566.2596)
PANEL_B = ((-0.5010362705, -0.8654262855, 0.0), -578.7424)
# Along the wall, how far apart the two faces may end and still be "meeting".
# The donor's own faces share the vertex exactly; a tenth of a unit is the
# slack for the compiler's arithmetic, and the defect was 1.8 to 2.7.
CREASE_MAX = 0.10
# What the RED must reopen it to, so that a smaller wobble cannot pass for the
# defect coming back.
CREASE_RED_MIN = 1.0

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    return ok


# ---- the fixture ----------------------------------------------------------

TEX = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"


def box(x0, y0, z0, x1, y1, z1, tex="e2u3/blum12_1"):
    t = f"{tex} {TEX}"
    return "\n".join([
        "{",
        f"( {x0} 0 0 ) ( {x0} 1 0 ) ( {x0} 0 1 ) {t}",
        f"( {x1} 0 0 ) ( {x1} 0 1 ) ( {x1} 1 0 ) {t}",
        f"( 0 {y0} 0 ) ( 0 {y0} 1 ) ( 1 {y0} 0 ) {t}",
        f"( 0 {y1} 0 ) ( 1 {y1} 0 ) ( 0 {y1} 1 ) {t}",
        f"( 0 0 {z0} ) ( 1 0 {z0} ) ( 0 1 {z0} ) {t}",
        f"( 0 0 {z1} ) ( 0 1 {z1} ) ( 1 0 {z1} ) {t}",
        "}",
    ])


def panels(spelling: str) -> list[str]:
    """The two panels, in one of the two spellings under test.

    `editor` is three integer points on each plane, which is what q2dm1.map
    itself contained. `writer` is what MapGenGeometry_WriteValve220 emits for
    these two brushes: a point at the plane's foot from the origin, 750 units
    away from the brush, and two arms of 512, rounded to four decimals.
    """
    t = f"e2u3/blum12_1 {TEX}"
    if spelling == "editor":
        c = "\n".join([
            "{",
            f"( 860 0 0 ) ( 860 1 0 ) ( 860 0 1 ) {t}",
            f"( 896 0 0 ) ( 896 0 1 ) ( 896 1 0 ) {t}",
            f"( 0 0 896 ) ( 1 0 896 ) ( 0 1 896 ) {t}",
            f"( 0 0 1216 ) ( 0 1 1216 ) ( 1 0 1216 ) {t}",
            f"( 896 150 512 ) ( 896 150 0 ) ( 860 170 0 ) {t}",
            f"( 860 174 0 ) ( 896 154 0 ) ( 896 154 512 ) {t}",
            "}",
        ])
        b = "\n".join([
            "{",
            f"( 896 0 0 ) ( 896 1 0 ) ( 896 0 1 ) {t}",
            f"( 934 0 0 ) ( 934 0 1 ) ( 934 1 0 ) {t}",
            f"( 0 0 896 ) ( 1 0 896 ) ( 0 1 896 ) {t}",
            f"( 0 0 1216 ) ( 0 1 1216 ) ( 1 0 1216 ) {t}",
            f"( 934 128 512 ) ( 934 128 0 ) ( 896 150 0 ) {t}",
            f"( 896 154 0 ) ( 934 132 0 ) ( 934 132 512 ) {t}",
            "}",
        ])
        return [c, b]

    c = "\n".join([
        "{",
        f"( 860 0 512 ) ( 860 0 0 ) ( 860 512 0 ) {t}",
        f"( 896 512 0 ) ( 896 0 0 ) ( 896 0 512 ) {t}",
        f"( 0 512 896 ) ( 0 0 896 ) ( 512 0 896 ) {t}",
        f"( 512 0 1216 ) ( 0 0 1216 ) ( 0 512 1216 ) {t}",
        f"( 722.5685 246.3508 0 ) ( 275 495 0 ) ( 275 495 512 ) {t}",
        f"( 276.6981 498.0566 512 ) ( 276.6981 498.0566 0 ) ( 724.2666 249.4074 0 ) {t}",
        f"( 0 149.9844 -512 ) ( 0 149.9844 0 ) ( 512 149.9844 0 ) {t}",
        f"( 512 174.0156 0 ) ( 0 174.0156 0 ) ( 0 174.0156 -512 ) {t}",
        "}",
    ])
    b = "\n".join([
        "{",
        f"( 896 0 512 ) ( 896 0 0 ) ( 896 512 0 ) {t}",
        f"( 934 512 0 ) ( 934 0 0 ) ( 934 0 512 ) {t}",
        f"( 0 512 896 ) ( 0 0 896 ) ( 512 0 896 ) {t}",
        f"( 512 0 1216 ) ( 0 0 1216 ) ( 0 512 1216 ) {t}",
        f"( 733.0692 244.3283 0 ) ( 289.971 500.8589 0 ) ( 289.971 500.8589 512 ) {t}",
        f"( 291.7054 503.8548 512 ) ( 291.7054 503.8548 0 ) ( 734.8037 247.3242 0 ) {t}",
        f"( 0 127.9844 -512 ) ( 0 127.9844 0 ) ( 512 127.9844 0 ) {t}",
        f"( 512 154.0156 0 ) ( 0 154.0156 0 ) ( 0 154.0156 -512 ) {t}",
        "}",
    ])
    return [c, b]


def write_fixture(path: Path, spelling: str) -> None:
    shell = [
        box(600, -200, 700, 1200, 400, 800, "e2u3/floor1_6"),
        box(600, -200, 1300, 1200, 400, 1400),
        box(600, -200, 700, 640, 400, 1400),
        box(1160, -200, 700, 1200, 400, 1400),
        box(600, -200, 700, 1200, -160, 1400),
        box(600, 360, 700, 1200, 400, 1400),
    ]
    path.write_text(
        "// Game: Quake 2\n// Format: Valve\n"
        "{\n\"classname\" \"worldspawn\"\n\"mapversion\" \"220\"\n"
        + "\n".join(shell + panels(spelling)) + "\n}\n"
        "{\n\"classname\" \"info_player_start\"\n\"origin\" \"800 -60 850\"\n}\n")


# ---- measuring the crease --------------------------------------------------

def lump(raw: bytes, i: int) -> bytes:
    off, ln = struct.unpack_from("<ii", raw, 8 + i * 8)
    return raw[off:off + ln]


def faces_on(raw: bytes, plane, z_at: float):
    n0, d0 = plane
    planes, verts = lump(raw, 1), lump(raw, 2)
    faces, edges, surfedges = lump(raw, 6), lump(raw, 11), lump(raw, 12)
    out = []
    for f in range(len(faces) // 20):
        pl, side, first, count, _ = struct.unpack_from("<HHihh", faces, f * 20)
        if count < 3:
            continue
        nx, ny, nz, d, _ = struct.unpack_from("<ffffi", planes, pl * 20)
        s = -1.0 if side else 1.0
        n = (nx * s, ny * s, nz * s)
        if sum(n[k] * n0[k] for k in range(3)) < 0.9999 or abs(d * s - d0) > 0.05:
            continue
        pts = []
        for k in range(count):
            se = struct.unpack_from("<i", surfedges, (first + k) * 4)[0]
            v0, v1 = struct.unpack_from("<HH", edges, abs(se) * 4)
            pts.append(struct.unpack_from("<fff", verts, (v1 if se < 0 else v0) * 12))
        zs = [p[2] for p in pts]
        if min(zs) <= z_at <= max(zs) and max(zs) - min(zs) > 8:
            out.append(pts)
    return out


def crease_gap(bsp: Path, z_at: float = 1000.0) -> float:
    """How far apart the two panels' faces end, along the wall.

    Panel C runs to x = 896 and panel B starts there. Their x readings are
    converted to a distance along the wall by the y-component of C's normal,
    which is what a player sees as the width of the strip.
    """
    raw = bsp.read_bytes()
    b = faces_on(raw, PANEL_B, z_at)
    c = faces_on(raw, PANEL_C, z_at)
    if not b or not c:
        return float("nan")
    b_min = min(p[0] for pts in b for p in pts)
    c_max = max(p[0] for pts in c for p in pts)
    return abs(b_min - c_max) / abs(PANEL_C[0][1])


# ---- building --------------------------------------------------------------

def build_tool(work: Path, name: str, sources, defines=()) -> Path:
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    exe = out / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I" + str(REPO / "inc")] + [f"-D{d}" for d in defines]
        + [str(REPO / f) for f in sources] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-1500:])
        raise SystemExit(f"cannot build {name}")
    return exe


def pinned_threads() -> str:
    """The compiler thread count the pin qualified, not a number of our own.

    MEASURED and recorded in the pin: the semantic digest does not depend on
    this, but the time does - the compiler waits a fixed second per parallel
    batch, so one thread is 0.3s where sixteen is 12.8s. Asking for a count the
    pin did not qualify is calling three configurations one pinned one.
    """
    pin = json.loads((REPO / "tools" / "mapgen_compiler_pin.json")
                     .read_text(encoding="utf-8"))
    return str(pin["thread_policy"]["value"])


def compile_map(compiler: Path, path: Path) -> str | None:
    run = subprocess.run(
        [str(compiler), "-bsp", "-threads", pinned_threads(), "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)
    text = run.stdout + run.stderr
    if run.returncode != 0 or "ERROR" in text:
        return "refused"
    if "leaked" in text.lower():
        return "leaked"
    return None


def pinned_compiler() -> Path:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler as resolve
    return resolve()[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    args = ap.parse_args()
    work = args.work
    work.mkdir(parents=True, exist_ok=True)

    pin = json.loads(PIN.read_text(encoding="utf-8"))
    compiler = pinned_compiler()
    if not compiler.exists():
        print(f"  the pinned compiler is not at {compiler}")
        return 2

    # --- the compiler is one a complete M0Q passed, and carries P12 ---------
    got = hashlib.sha256(compiler.read_bytes()).hexdigest()
    qualified = {pin["build"]["qualified_binary"]["sha256"]} | {
        a["sha256"] for a in pin["build"].get("qualified_artifacts", {})
                                         .get("artifacts", [])}
    check("the compiler on disk is a binary the pin qualified",
          got in qualified, f"{got[:16]} of {len(qualified)} qualified")
    ids = [p["id"] for p in pin["local_patches"]["applied"]]
    check("the pin records P12", "P12" in ids, str(ids))
    p12 = subprocess.run(
        [sys.executable, str(REPO / "tools" / "mapgen_patch_p12_base_winding_precision.py"),
         str(SOURCE), "--check"], capture_output=True, text=True)
    check("P12 is applied to the source the compiler is built from",
          p12.returncode == 0, p12.stdout.strip())

    # --- the fixture, in both spellings -------------------------------------
    for spelling in ("writer", "editor"):
        m = work / f"crease_{spelling}.map"
        write_fixture(m, spelling)
        why = compile_map(compiler, m)
        if not check(f"the {spelling} fixture compiles", why is None, why or ""):
            continue
        gap = crease_gap(m.with_suffix(".bsp"))
        check(f"the {spelling} fixture's panels still meet",
              gap == gap and gap <= CREASE_MAX, f"{gap:.3f} units apart")

    # --- q2dm1 itself --------------------------------------------------------
    donor = CORPUS / "q2dm1.bsp"
    if donor.exists():
        fork = build_tool(work, "fork", FORK_SRC)
        holes = build_tool(work, "holes", HOLES_SRC)
        out = work / "q2dm1.map"
        run = subprocess.run([str(fork), str(donor), str(out), "100", "1"],
                             capture_output=True, text=True)
        why = compile_map(compiler, out) if run.returncode == 0 else "the fork refused"
        if check("q2dm1 forks and compiles", why is None, why or ""):
            gap = crease_gap(out.with_suffix(".bsp"))
            check("q2dm1's courtyard panels still meet",
                  gap == gap and gap <= CREASE_MAX, f"{gap:.3f} units apart")
            h = subprocess.run([str(holes), str(donor), str(out.with_suffix(".bsp")),
                                "1", "0.35"], capture_output=True, text=True)
            import re
            m = re.search(r"(\d+) no longer drawn on their own plane", h.stdout)
            undrawn = int(m.group(1)) if m else -1
            check("and every point q2dm1 draws is drawn on its own plane",
                  undrawn == 0, str(undrawn))
    else:
        check("q2dm1 is in the corpus", False, str(donor))

    # --- controlled RED: the same source with P12 taken out ------------------
    if not args.skip_red:
        print("controlled RED -- the compiler built without P12:")
        red_src = work / "src_no_p12"
        if red_src.exists():
            shutil.rmtree(red_src)
        shutil.copytree(SOURCE, red_src)
        # The patch undoes itself, so this guard does not carry a second copy
        # of the block it is trying to remove - cutting the text out from the
        # outside would break the day that comment is reflowed.
        rv = subprocess.run(
            [sys.executable,
             str(REPO / "tools" / "mapgen_patch_p12_base_winding_precision.py"),
             str(red_src), "--revert"], capture_output=True, text=True)
        if not check("  P12 can be taken back out of a copy of the source",
                     rv.returncode == 0, (rv.stdout + rv.stderr).strip()[:120]):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        #
        # Built from nothing, and identified once it is there.
        #
        # This used to accept `red_exe.exists()`, which is true of last run's
        # binary after a build that failed - so a RED could "reproduce" the
        # defect with the wrong compiler and nobody would know. The tree goes
        # first, both commands have to succeed, and the binary that comes out
        # must not be one M0Q has qualified: if it hashes to a qualified
        # artifact then P12 is still in it and the mutation did not happen.
        # (Codex, 2026-09-06 section 4.)
        #
        red_build = work / "build_no_p12"
        if red_build.exists():
            shutil.rmtree(red_build)
        cm = load_guard.run(["cmake", "-S", str(red_src), "-B", str(red_build),
                             "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                             "-DCMAKE_C_COMPILER=O:/gcc/bin/gcc.exe"],
                            capture_output=True, text=True)
        nj = load_guard.run(["ninja", "-C", str(red_build)],
                            capture_output=True, text=True)
        red_exe = red_build / "q2tool.exe"
        built = (cm.returncode == 0 and nj.returncode == 0 and red_exe.is_file())
        sys.path.insert(0, str(REPO / "tools"))
        from mapgen_qualified_compilers import sha256_of, receipts  # noqa: E402
        red_sha = sha256_of(red_exe) if red_exe.is_file() else ""
        check("  the mutated compiler builds from an empty tree",
              built, f"cmake {cm.returncode}, ninja {nj.returncode}, "
                     f"{(cm.stderr + nj.stderr)[-120:]}")
        check("  and is not a binary M0Q has qualified",
              bool(red_sha) and red_sha not in receipts(), red_sha[:16])
        if built:
            for spelling in ("writer", "editor"):
                m = work / f"red_{spelling}.map"
                write_fixture(m, spelling)
                why = compile_map(red_exe, m)
                if not check(f"  the {spelling} fixture still compiles",
                             why is None, why or ""):
                    continue
                gap = crease_gap(m.with_suffix(".bsp"))
                check(f"  and the {spelling} fixture's crease reopens",
                      gap == gap and gap >= CREASE_RED_MIN,
                      f"{gap:.3f} units apart")

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    print("RESULT: " + ("PASS" if FAILED == 0 else "FAIL"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
