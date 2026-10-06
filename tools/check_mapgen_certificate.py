"""Codex's certificate REDs: a claim about a special traversal has to be
checkable, and checking it has to be able to fail.

The ruling of 2026-09-02 widened "reachable" to include the traversals Quake II
actually has, and then asked what makes such a claim auditable afterwards. A
certificate is the answer - what entity, from where, at what cost, under which
physics, on which map - and the three cases below are the ones that decide
whether it is evidence or decoration:

    7  a certificate about another map is refused, not believed
    8  the entity is the same and the ledge he launched from is gone: refused
    9  a pickup nothing witnesses fails the map, certificate or no certificate

Eight is the one that needs the map itself. Identity is a string comparison and
would pass: the item still has the same classname at the same coordinates. What
changed is the floor a hundred units below it, and only replaying the traversal
against the compiled candidate can see that.

    python tools/check_mapgen_certificate.py [--work DIR] [--no-red]
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831"
                    r"\certificate")

SOURCES = [
    "tools/mapgen_certificate_driver.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_reach.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_geometry.c",
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
    return bool(ok)


def build(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in SOURCES] + ["-o", str(out), "-lm"],
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


RESULT = re.compile(r"^(?:verify|replay) (\w+)", re.M)
WROTE = re.compile(r"^wrote (\d+) certificate", re.M)


def run_driver(exe: Path, args: list[str]) -> tuple[str, str]:
    """The outcome is the LAST word the driver said about the certificate.

    It says `verify` first and `replay` second, and the second is the one that
    stands: an identity that passes is not an answer, it is permission to ask
    the expensive question."""
    run = subprocess.run([str(exe)] + args, capture_output=True, text=True,
                         timeout=3600)
    found = RESULT.findall(run.stdout)
    return (found[-1] if found else ""), run.stdout + run.stderr


def static_contract() -> None:
    print("\n=== a certificate is evidence, not a permission")

    impl = (REPO / "src" / "mapgen" / "mapgen_certificate.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_certificate.h").read_text(
        encoding="utf-8", errors="replace")
    reach = (REPO / "src" / "mapgen" / "mapgen_reach.c").read_text(
        encoding="utf-8", errors="replace")

    check("the gate never reads one",
          "MapGenCertificate_Verify" not in reach
          and "MapGenCertificate_Replay" not in reach)
    check("and the header says why that is the point",
          "is NOT is an input" in header)
    check("an empty hash matches nothing, including another empty one",
          "a && b && *a && *b && !strcmp(a, b)" in impl)
    check("identity is checked before the map is explored",
          impl.index("MapGenCertificate_Verify(cert, candidate_sha256")
          < impl.index("MapGenReach_Explore"))
    check("a replay re-derives rather than re-checks",
          "MapGenReach_Explore(bsp" in impl
          and "MapGenReach_Certificates(reach)" in impl)
    check("what a file says about its own replay is not trusted",
          "c->replayed = false;" in impl)
    check("the physics is the constants themselves",
          "rocket_radius_damage %.6f" in reach
          and "MapGenReach_PhysicsSha256" in reach)


def behaviour(exe: Path, work: Path) -> None:
    print("\n=== on a map with a ledge only a rocket reaches")
    ledge = compile_fixture(work, "rocketjump_ledge")
    if not check("the fixture compiles", ledge is not None):
        return

    got, out = run_driver(exe, [str(ledge), "--write",
                                str(work / "ledge.txt")])
    m = WROTE.search(out)
    check("the search writes a certificate for it",
          bool(m) and int(m.group(1)) == 1, out[-300:])
    check("and it names the entity, the launch and the landing",
          "launch" in out and "landing" in out and "weapon" in out
          or "item" in out or "ammo" in out, out[-300:])

    print("\n=== RED 7: a certificate about another map")
    got, out = run_driver(exe, [str(ledge), "--read", str(work / "ledge.txt"),
                                "--candidate", "0" * 64])
    check("a candidate hash that is not this map -> ERR_STALE",
          got == "ERR_STALE", f"got {got!r}\n{out[-300:]}")
    got, out = run_driver(exe, [str(ledge), "--read", str(work / "ledge.txt"),
                                "--physics", "0" * 64])
    check("physics that are not these physics -> ERR_STALE",
          got == "ERR_STALE", f"got {got!r}\n{out[-300:]}")

    print("\n=== and the same map still reproduces it")
    got, out = run_driver(exe, [str(ledge), "--read", str(work / "ledge.txt")])
    check("replayed against the map it is about -> OK", got == "OK",
          f"got {got!r}\n{out[-300:]}")

    print("\n=== RED 8: the entity is the same and the launch is gone")
    pit = compile_fixture(work, "rocketjump_pit")
    if check("the map with nowhere to come down compiles", pit is not None):
        got, out = run_driver(exe, [str(pit), "--read",
                                    str(work / "ledge.txt"), "--any-map"])
        check("the certificate does not survive it -> ERR_NOT_REPRODUCED",
              got == "ERR_NOT_REPRODUCED", f"got {got!r}\n{out[-300:]}")

    print("\n=== RED 9: a pickup nothing witnesses")
    dry = compile_fixture(work, "rocketjump_dry")
    if check("the map with no rockets compiles", dry is not None):
        got, out = run_driver(exe, [str(dry), "--write", str(work / "dry.txt")])
        m = WROTE.search(out)
        check("no certificate is written for it",
              bool(m) and int(m.group(1)) == 0, out[-300:])
        check("and the map fails its own item gate",
              "out of a player's reach" in out and " 1 " in out, out[-300:])


MUTATION = (
    b"""    if (!same_hash(cert->candidate_sha256, candidate_sha256)""",
    b"""    if (false""",
)


def red(exe: Path, work: Path) -> None:
    print("\n=== and the identity check is what refuses a stale one")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "certificate")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_certificate.c"
        data = target.read_bytes()
        anchor, patched, count = resolve_anchor(data, *MUTATION)
        if not check("the identity test is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(data.replace(anchor, patched, 1))
        red_exe = box.root / "red.exe"
        err = build(box.root, red_exe)
        if not check("the mutated check still compiles", not err, err):
            return
        got, out = run_driver(red_exe,
                              [str(work / "rocketjump_ledge"
                                   / "rocketjump_ledge.bsp"),
                               "--read", str(work / "ledge.txt"),
                               "--candidate", "0" * 64])
        check("without it a certificate about another map is accepted",
              got == "OK", f"got {got!r}\n{out[-300:]}")
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

    print("=== why a pickup nobody can walk to is still reachable")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()

    exe = args.work / "bin" / "certificate.exe"
    err = build(REPO, exe)
    if check("the driver compiles", not err, err):
        behaviour(exe, args.work)
        if not args.no_red:
            red(exe, args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
