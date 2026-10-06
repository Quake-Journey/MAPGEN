"""GF5R: does the reachability gate say the right thing, and can it say no?

The gate's verdict is only worth anything if each answer has a case that
produces it. So every fixture is compiled by the pinned compiler and run
through the real gate, and the guard asserts the verdict - including the ones
that must FAIL. A gate that passed everything would pass q2dm1 too.

Most cases come in pairs that differ by one thing: a door with a targetname
nothing fires, a lift whose button was never placed, a teleporter whose
destination entity is not in the map. That difference is the controlled RED.

    python tools/check_mapgen_reach_gate.py [--work DIR] [--only NAME]
                                            [--donors] [--budget N]

`--donors` additionally requires the three donor maps to pass, which is the
other half of the claim: the gate is strict enough to catch a locked door and
loose enough not to reject a map people actually play.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\gf5r")
DONORS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")

SOURCES = [
    "tools/mapgen_reach_gate.c",
    "src/mapgen/mapgen_reach.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    # The physics identity a certificate carries is a SHA-256 of the traversal
    # constants, and this is where SHA-256 lives.
    "src/mapgen/mapgen_digest.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

CASES = 0
FAILURES: list[str] = []


def case(name: str, ok: bool, detail: str = "") -> None:
    global CASES
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
        FAILURES.append(name)


def build_gate(work: Path) -> Path:
    out = work / "bin"
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "reach_gate.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(REPO / "inc"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / f) for f in SOURCES] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-3000:])
        raise SystemExit("cannot build the gate")
    return exe


def compile_map(map_path: Path) -> str | None:
    common = ["-threads", "4", "-moddir", str(GAME), "-basedir", str(GAME),
              "-gamedir", str(GAME)]
    run = subprocess.run([str(COMPILER), "-bsp"] + common + [str(map_path)],
                         capture_output=True, text=True, timeout=1800)
    text = run.stdout + run.stderr
    if run.returncode != 0 or "ERROR" in text:
        return "the compiler refused it"
    if "leaked" in text.lower():
        return "it leaks"
    if not map_path.with_suffix(".bsp").exists():
        return "no bsp came out"
    return None


def run_gate(exe: Path, bsp: Path, budget: int,
             extra: tuple[str, ...] = ()) -> tuple[bool, str]:
    run = subprocess.run([str(exe), str(bsp), str(budget), *extra],
                         capture_output=True, text=True, timeout=3600)
    text = (run.stdout + run.stderr).strip()
    if run.returncode not in (0, 1):
        return False, f"the gate itself failed: {text[-400:]}"
    return run.returncode == 0, text


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# Each one takes a single condition out of the product verdict, and names the
# fixture that must stop being refused when it is gone. The landmark case is
# the odd one: it removes the segmentation the rule depends on, and the map it
# names is one that PASSES - because the contract there is that a gate which
# could not measure refuses rather than passing on an absence.
MUTATIONS = {
    "a verdict that does not require every pickup to be reachable": (
        "inc/common/mapgen_reach.h",
        b"""    if (report->items_unreachable)""",
        b"""    if (false)""",
        "item_sealed", True,
    ),
    "a verdict that does not require the machines to work": (
        "inc/common/mapgen_reach.h",
        b"""    if (report->movers_inoperable)""",
        b"""    if (false)""",
        "cupboard_dead", True,
    ),
    "a gate that could not segment the map and passed anyway": (
        "src/mapgen/mapgen_reach.c",
        b"""            if (MapGenRooms_Find(bsp, 64.0f, 0.0f, &rooms) == MAPGEN_ROOMS_OK) {""",
        b"""            if (false) {""",
        "open_room", False,
    ),
}


def red(work: Path, budget: int) -> None:
    """Rebuild the gate with one condition missing and rerun one fixture."""
    sys.path.insert(0, str(REPO / "tools"))
    from mapgen_red_sandbox import Sandbox, hash_tree
    from mapgen_red_support import resolve_anchor

    print("\n=== and each condition of the verdict is load-bearing")
    before = hash_tree(REPO)
    box = Sandbox(REPO, "reach")
    try:
        for name, (where, anchor, replacement, fixture, was_refused) in \
                MUTATIONS.items():
            target = box.root / where
            pristine = target.read_bytes()
            found, patched, count = resolve_anchor(pristine, anchor,
                                                   replacement)
            if count != 1:
                case(f"{name}: the condition is where it says", False,
                     f"{count} occurrences")
                continue
            target.write_bytes(pristine.replace(found, patched, 1))
            run = subprocess.run(
                ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
                 "-I" + str(box.root / "inc"),
                 "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
                 "-DUSE_NEW_GAME_API=0"]
                + [str(box.root / f) for f in SOURCES]
                + ["-o", str(box.root / "red.exe"), "-lm"],
                capture_output=True, text=True)
            target.write_bytes(pristine)
            if run.returncode != 0:
                case(f"{name}: it still compiles", False,
                     run.stderr[-400:])
                continue
            passed, text = run_gate(box.root / "red.exe",
                                    work / f"{fixture}.bsp", budget)
            case(f"{name}: {fixture} is now "
                 f"{'accepted' if was_refused else 'refused'}",
                 passed == was_refused,
                 "\n        " + "\n        ".join(text.splitlines()[:5]))
    finally:
        box.dispose()
        case("the shared worktree was never opened for writing",
             hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--only")
    ap.add_argument("--donors", action="store_true")
    ap.add_argument("--budget", type=int, default=40000)
    ap.add_argument("--no-red", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(REPO / "tools"))
    import mapgen_reach_fixtures as fixtures

    work = args.work
    work.mkdir(parents=True, exist_ok=True)
    exe = build_gate(work)
    print(f"gate {exe}  {digest(exe)}")

    names = [args.only] if args.only else list(fixtures.FIXTURES)
    for name in names:
        if name not in fixtures.FIXTURES:
            raise SystemExit(f"no fixture named {name!r}")
        target = work / f"{name}.map"
        fixtures.FIXTURES[name](target)

        why = compile_map(target)
        if why:
            case(f"{name}: compiles", False, why)
            continue

        bsp = target.with_suffix(".bsp")
        # Every fixture is asked the PRODUCT question. There is no looser
        # verdict to opt into any more: pickups, landmarks and operable
        # machines are absolute, and a fixture that only passed the
        # connectivity half would be testing a gate the product does not use.
        passed, text = run_gate(exe, bsp, args.budget)
        want = fixtures.EXPECTED[name]
        detail = "\n        " + "\n        ".join(text.splitlines()[:6])
        case(f"{name}: the gate {'passes' if want else 'refuses'} it"
             f"  [{digest(bsp)}]", passed == want, detail)

    if args.donors:
        for donor in ("q2dm1", "q2dm2", "q2dm3"):
            bsp = DONORS / f"{donor}.bsp"
            if not bsp.exists():
                case(f"{donor}: present", False, str(bsp))
                continue
            # A donor is asked the SURVEY question, which is the only one it
            # can answer: maps people play put a few pickups where ordinary
            # movement cannot reach them, and that is not a defect in them.
            passed, text = run_gate(exe, bsp, args.budget,
                                    ("--connectivity-only",))
            detail = "\n        " + "\n        ".join(text.splitlines()[:8])
            case(f"{donor}: players can reach each other and get back"
                 f"  [{digest(bsp)}]", passed, detail)

    if not args.no_red and not args.only:
        red(work, args.budget)

    print(f"\n{CASES - len(FAILURES)}/{CASES} cases")
    if FAILURES:
        print("failed: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
