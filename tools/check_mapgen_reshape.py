"""GF6C: a wall of a room goes back into the rock, whole or not at all.

Third in Codex's operator order: dependency-closed room reshape. It is the
widen's primitive applied to a WALL, and the difference is that a wall is many
brushes and a surface has two sides. Both facts were found by measurement
rather than argued:

  * a wall shared with the room next door cannot move its half. q2dm1's rooms
    share their walls, and moving half of one opens a seam down the middle of
    it - so the wall takes its continuation, transitively, bounded by contact;

  * a surface has two sides. The plain room's wall is the plane x = -256 facing
    in, and the FLOOR's edge is the same plane facing the other way. Move one
    and not the other and the corner between them opens. So every face on the
    plane travels, each along its own normal, and they land together.

The fixtures are one map each with the answer in it:

    reshape_plain   nothing against its walls          -> the wall goes back
    reshape_niche   one piece of the wall is too thin  -> none of it goes

    python tools/check_mapgen_reshape.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_geometry_fixtures as fixtures  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402
from mapgen_red_support import resolve_anchor  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\reshape")

PROBE = [
    "tools/mapgen_edit_probe.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
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
    return bool(ok)


def build(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in PROBE] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def compile_fixture(work: Path, name: str) -> Path | None:
    job = work / name
    bsp = job / f"{name}.bsp"
    if bsp.exists():
        return bsp
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    source = job / f"{name}.map"
    fixtures.FIXTURES[name](source)
    subprocess.run([str(COMPILER), "-bsp", "-threads", "4",
                    "-moddir", str(GAME), "-basedir", str(GAME),
                    "-gamedir", str(GAME), str(source)],
                   capture_output=True, text=True, timeout=1800)
    return bsp if bsp.exists() else None


EDIT = re.compile(r"^edit (\d+) reshape-room: (\w+)")


def walls(exe: Path, bsp: Path, how_many: int = 4) -> list[bool]:
    """Whether each planned wall moved, one run per wall."""
    out = []
    for i in range(how_many):
        run = subprocess.run([str(exe), str(bsp), "1", "--only",
                              "reshape-room", "--apply", str(i)],
                             capture_output=True, text=True, timeout=600)
        found = False
        for line in run.stdout.splitlines():
            m = EDIT.match(line)
            if m:
                out.append(m.group(2) == "applied")
                found = True
        if not found:
            break
    return out


def static_contract() -> None:
    print("\n=== a wall moves whole, or not at all")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry_edit.h").read_text(
        encoding="utf-8", errors="replace")

    check("every side is judged before any of them moves",
          "found_them_all" in impl and "all_clear" in impl)
    # One predicate, and it is the one that says WHY: the yes/no wrapper it
    # used to share with the widen is gone, because a wrapper that throws the
    # reason away is how the widen came to decline forty-one times a run
    # without saying anything.
    check("and they are judged on the same terms the widen uses",
          impl.count("static bool widen_is_safe_why(") == 1
          and "widen_is_safe_why(candidate, w, s, donor_bsp, &s, 1, &why)"
          in impl
          and "widen_is_safe_why(candidate, &one, chosen[i]," in impl)
    check("what travels together does not block",
          "travels_too" in impl)
    check("the wall takes its continuation past this room",
          "the same wall carries on past this room" in impl
          or "carries on past this room" in impl)
    check("both sides of the surface travel",
          "wall.sense[wall.num_sides] = sense;" in impl
          and "-depth * r->sense[i]" in impl)
    check("it backs off rather than refusing at one distance",
          "depth *= 0.5f" in impl)
    check("a wall a way out is cut into is left alone",
          "at_a_way_out" in impl)
    check("only a movable bundle is reshaped",
          impl.count("!MapGenBundle_Movable(bundle)") >= 2)
    check("the header says why a wall moves whole", "staircase" in header)


def behaviour(exe: Path, work: Path) -> None:
    print("\n=== nothing against its walls")
    plain = compile_fixture(work, "reshape_plain")
    if check("the plain fixture compiles", plain is not None):
        moved = walls(exe, plain)
        check("a wall of it goes back into the rock", any(moved), str(moved))

    print("\n=== one piece of the wall too thin to move")
    niche = compile_fixture(work, "reshape_niche")
    if check("the niche fixture compiles", niche is not None):
        moved = walls(exe, niche)
        check("the wall with the thin piece stays where it is",
              moved and not moved[0], str(moved))

    print("\n=== and on a donor whose walls have things against them")
    donor = CORPUS / "q2dm1.bsp"
    if check("q2dm1 is in the corpus", donor.exists()):
        moved = walls(exe, donor, how_many=4)
        check("it declines rather than carving something it cannot show",
              moved and not any(moved), str(moved))


# The three questions as a block. Switching off only the thickness test was
# tried first and the wall still declined - something else refuses it too - so
# asserting that one test alone was decisive would have been a claim the run
# does not support.
MUTATION = (
    # The first line of the safety block, which now carries a refusal reason
    # out for diagnosis. Returning true here switches every check below off,
    # which is what this mutation is for.
    b"""    const mapgen_geometry_side_t *side = MapGenGeometry_Side(candidate, s);
    if (!donor_bsp || !side || side->num_samples == 0) {
        SET(MAPGEN_WIDEN_NO_SAMPLES);
        return false;
    }""",
    b"""    const mapgen_geometry_side_t *side = MapGenGeometry_Side(candidate, s);
    if (!donor_bsp || !side || side->num_samples == 0) {
        SET(MAPGEN_WIDEN_NO_SAMPLES);
        return false;
    }
    return true;""",
)


def red(exe: Path, work: Path) -> None:
    print("\n=== and the thin piece is what stops the wall")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "reshape")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        data = target.read_bytes()
        anchor, replacement, count = resolve_anchor(data, *MUTATION)
        if not check("the safety block is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(data.replace(anchor, replacement, 1))
        red_exe = box.root / "red.exe"
        err = build(box.root, red_exe)
        if not check("the mutated operator still compiles", not err, err):
            return
        moved = walls(red_exe, work / "reshape_niche" / "reshape_niche.bsp")
        check("with them switched off the wall is carved anyway",
              moved and moved[0], str(moved))
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing",
              hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--no-red", action="store_true")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    print("=== reshaping a room")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()

    exe = args.work / "bin" / "probe.exe"
    err = build(REPO, exe)
    if check("the probe compiles", not err, err):
        behaviour(exe, args.work)
        if not args.no_red:
            red(exe, args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
