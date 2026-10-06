"""An invented map has to feel OPEN, and q2dm1 is what open measures as.

`check_mapgen_arena.py` asks whether there is sky straight up. The map handed
to the PO on 2026-09-07 answered 411 permille to that and he called it running
in a box whose lid had been opened a crack: nobody standing anywhere in it
could see sky below thirty degrees of elevation, and the lid was a thousand
units above his head behind twelve hundred units of wall.

    python tools/check_mapgen_openness.py [MAP.bsp] [--red MAP.bsp]

So this asks the question he was asking, from the standing places a player
uses, with `tools/mapgen_open_probe.c`:

    HORIZON     the lowest elevation at which half the compass reaches sky.
                Zero means the parapet is at eye level and you are outside.
    ELEVATION   the share of rays that reach sky at thirty degrees.
    STOREYS     how many floor heights have places that are outdoors.
    HEIGHT      where the sky is straight up, how far above the eye.

Every threshold is a number q2dm1 itself meets, and q2dm1 is measured here
rather than quoted.

The RED is the box the PO walked, and this guard BUILDS it: one room with a
crack of sky a thousand units over the head, compiled with the pinned compiler
and cached beside the probe. It used to be an artifact in a dated batch folder
under `_agent_temp`, and when that folder was cleaned the guard reported "the
RED artifact is still on disk" as a FAILURE - four of them per handover, on
maps that were fine. A guard whose RED evaporates is a guard that stopped
proving its thresholds bite; a guard that fails because a temporary file was
tidied away is worse than that, because it teaches everyone to read past a
FAIL. `--red MAP.bsp` still names a real artifact when there is one.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907\openness_gate")
RED_DEFAULT = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260907"
                   r"\arena_courtyard\synth\try_0001\q2mg_f0.bsp")
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")

# The RED, as brushwork: one room 1024 across, walls to 1200, and a crack of
# sky 256 units square in the lid. Every threshold this guard holds is failed
# by it - one storey, no azimuth that sees sky at thirty degrees, and the sky
# itself 1136 units over the eye against a limit of 768 - which is the map of
# 2026-09-07 said in six brushes instead of a gigabyte of batch folder.
RED_AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"
RED_SKY_AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 4 0"
RED_WALL = "e2u3/blum12_1"
RED_FLOOR = "e2u3/floor1_6"
RED_SKY = "e2u3/sky1"

PROBE_SRC = ["tools/mapgen_open_probe.c", "src/mapgen/mapgen_bsp.c",
             "src/mapgen/mapgen_trace.c", "src/shared/shared.c",
             "tools/mapgen_host_stubs.c"]

OUTSIDE = re.compile(r"^outside (\d+) permille$", re.M)
AT30 = re.compile(r"^elevation 30 sky (\d+) permille$", re.M)
STOREYS = re.compile(r"^outdoor storeys (\d+) of", re.M)
HEIGHT = re.compile(r"^sky height median (\d+)", re.M)

# What an arena is, as numbers q2dm1 answers: it stands 134 permille of its
# floor outside, sees sky on 152 permille of azimuths at thirty degrees, has
# four outdoor storeys, and its sky is 544 units over the eye.
OUTSIDE_MIN = 100
AT30_MIN = 100
STOREYS_MIN = 3
HEIGHT_MAX = 768

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def build(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "open_probe.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / s) for s in PROBE_SRC] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the openness probe")
    return exe


def measure(exe: Path, bsp: Path) -> dict:
    run = subprocess.run([str(exe), str(bsp)], capture_output=True, text=True,
                         timeout=7200)
    out = run.stdout + run.stderr
    def one(rx, default=-1):
        m = rx.search(out)
        return int(m.group(1)) if m else default
    return {
        "outside": one(OUTSIDE),
        "at30": one(AT30),
        "storeys": one(STOREYS),
        "height": one(HEIGHT),
        "text": out,
    }


def red_box(x0, y0, z0, x1, y1, z1, tex, axes=RED_AXES) -> str:
    faces = [
        [(x0, 0, 0), (x0, 1, 0), (x0, 0, 1)],
        [(x1, 0, 0), (x1, 0, 1), (x1, 1, 0)],
        [(0, y0, 0), (0, y0, 1), (1, y0, 0)],
        [(0, y1, 0), (1, y1, 0), (0, y1, 1)],
        [(0, 0, z0), (1, 0, z0), (0, 1, z0)],
        [(0, 0, z1), (0, 1, z1), (1, 0, z1)],
    ]
    out = ["{"]
    for f in faces:
        out.append(" ".join(f"( {q[0]} {q[1]} {q[2]} )" for q in f)
                   + f" {tex} {axes}")
    out.append("}")
    return "\n".join(out)


def write_red_fixture(path: Path) -> None:
    """The box, sealed, with a crack of sky in the lid."""
    t = 32
    lo, hi, lid = 0, 1024, 1200
    ho0, ho1 = 384, 640          # the crack, 256 square, in the middle
    brushes = [
        red_box(lo, lo, lo - t, hi, hi, lo, RED_FLOOR),
        red_box(lo - t, lo, lo, lo, hi, lid, RED_WALL),
        red_box(hi, lo, lo, hi + t, hi, lid, RED_WALL),
        red_box(lo - t, lo - t, lo, hi + t, lo, lid, RED_WALL),
        red_box(lo - t, hi, lo, hi + t, hi + t, lid, RED_WALL),
        # the lid, in four slabs around the crack
        red_box(lo - t, lo - t, lid, hi + t, ho0, lid + t, RED_WALL),
        red_box(lo - t, ho1, lid, hi + t, hi + t, lid + t, RED_WALL),
        red_box(lo - t, ho0, lid, ho0, ho1, lid + t, RED_WALL),
        red_box(ho1, ho0, lid, hi + t, ho1, lid + t, RED_WALL),
        # and sky in the crack itself, so the map is sealed and the probe has
        # something to find straight up
        red_box(ho0, ho0, lid, ho1, ho1, lid + t, RED_SKY, RED_SKY_AXES),
    ]
    text = ["// Game: Quake 2", "// Format: Valve",
            "{", '"classname" "worldspawn"', '"mapversion" "220"',
            "\n".join(brushes), "}",
            "{", '"classname" "info_player_start"',
            '"origin" "128 128 32"', "}",
            "{", '"classname" "info_player_deathmatch"',
            '"origin" "896 128 32"', "}",
            "{", '"classname" "info_player_deathmatch"',
            '"origin" "512 896 32"', "}",
            "{", '"classname" "light"', '"origin" "512 512 900"',
            '"light" "600"', "}"]
    path.write_text("\n".join(text) + "\n", encoding="ascii")


def pinned() -> tuple[Path, str]:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler
    return pinned_compiler()


def red_map(work: Path, named: Path | None) -> tuple[Path, str]:
    """The RED artifact if one was named and is there; otherwise the box,
    compiled once and kept."""
    if named and named.is_file():
        return named, "the artifact of 2026-09-07"
    work.mkdir(parents=True, exist_ok=True)
    src = work / "red_box.map"
    bsp = work / "red_box.bsp"
    if not bsp.is_file():
        write_red_fixture(src)
        exe, threads = pinned()
        subprocess.run(
            [str(exe), "-bsp", "-threads", threads, "-moddir", str(GAME),
             "-basedir", str(GAME), "-gamedir", str(GAME), str(src)],
            capture_output=True, text=True, timeout=3600)
    return bsp, "the box, built by this guard"


def judged_by_default(maps: Path) -> Path | None:
    """The most-changed map installed - the lowest fidelity there is."""
    best: tuple[int, Path] | None = None
    for bsp in sorted(maps.glob("mgtest_f*.bsp")):
        m = re.match(r"mgtest_f(\d+)", bsp.stem)
        if m and (best is None or int(m.group(1)) < best[0]):
            best = (int(m.group(1)), bsp)
    return best[1] if best else None


def judge(name: str, got: dict, expect_open: bool) -> None:
    wrong = []
    if got["outside"] < OUTSIDE_MIN:
        wrong.append(f"{got['outside']} permille of its floor stands outside,"
                     f" under {OUTSIDE_MIN}")
    if got["at30"] < AT30_MIN:
        wrong.append(f"{got['at30']} permille of its azimuths see sky at"
                     f" thirty degrees, under {AT30_MIN}")
    if got["storeys"] < STOREYS_MIN:
        wrong.append(f"{got['storeys']} outdoor storeys, under {STOREYS_MIN}")
    if got["height"] > HEIGHT_MAX:
        wrong.append(f"its sky is {got['height']} units over the eye, over"
                     f" {HEIGHT_MAX}")
    summary = (f"outside {got['outside']}, at thirty degrees {got['at30']},"
               f" storeys {got['storeys']}, sky {got['height']} up")
    if expect_open:
        check(f"{name} is open the way q2dm1 is", not wrong,
              summary if not wrong else "; ".join(wrong))
    else:
        check(f"{name} is the box the PO walked - the RED", bool(wrong),
              summary)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?", type=Path, default=None)
    ap.add_argument("--red", type=Path, default=RED_DEFAULT)
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()

    exe = build(a.work)

    print("the reference, measured rather than quoted")
    ref = measure(exe, CORPUS / "q2dm1.bsp")
    judge("q2dm1", ref, True)

    red, whence = red_map(a.work, a.red)
    print(f"the box the PO walked, which is the RED - {whence}")
    if red.is_file():
        judge("the box with a crack of sky in the lid", measure(exe, red),
              False)
    else:
        check("the RED can be built at all", False, str(red))

    print("and the invented map as it is built today")
    target = a.map or judged_by_default(MAPS)
    if target is None:
        print("  note  no invented map is installed, so there is none to"
              " judge - the thresholds above are what this run proves")
    elif not target.is_file():
        check(f"{target.name} is there to be judged", False, str(target))
    else:
        judge(target.name, measure(exe, target), True)

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
