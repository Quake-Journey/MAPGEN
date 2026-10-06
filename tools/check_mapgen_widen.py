"""GF6C: the first operator that takes solid away.

Codex's operator order, 2026-09-01 section 4.2: after the sealed bundles and
the typed sockets comes widening an explicit connector. It is the first edit
that CARVES, and every other operator here could only add.

The claim is not that it is safe to carve. The claim is that this one declines
whenever it cannot show that what is left still holds, and the three fixtures
are three ways of not being able to show it. Each is one map with both answers
in it, so the comparison is between two flanks of one doorway rather than
between two maps that might differ in some other way as well:

    widen_thick    both flanks have rock behind them; both move
    widen_thin     forty units of pier on one side; that one declines
    widen_clipped  an invisible brush flush against one flank; that one declines

The last is the one a test of SOLID walks straight past: a playerclip is a wall
for a player and nothing for the compiler, so taking the flank back would leave
it standing in the middle of the passage that was just widened.

    python tools/check_mapgen_widen.py [--work DIR] [--no-red]
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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\widen")

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

TRANSACTION = [
    "tools/mapgen_transaction_driver.c",
    "src/mapgen/mapgen_transaction.c",
    "src/mapgen/mapgen_equivalence.c",
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

FIXTURES = ("widen_thick", "widen_thin", "widen_clipped")

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


def build(root: Path, out: Path, sources: list[str]) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in sources] + ["-o", str(out), "-lm"],
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


EDIT = re.compile(r"^edit (\d+) widen-connector at (-?\d+) (-?\d+) (-?\d+)"
                  r" facing (-?\d+) (-?\d+) (-?\d+): (\w+)")


def flanks(exe: Path, bsp: Path, how_many: int = 4) -> list[dict]:
    """Every planned widen of a fixture, one run each, with what it did."""
    out = []
    for i in range(how_many):
        run = subprocess.run([str(exe), str(bsp), "1", "--only",
                              "widen-connector", "--apply", str(i)],
                             capture_output=True, text=True, timeout=600)
        for line in run.stdout.splitlines():
            m = EDIT.match(line)
            if m:
                out.append({"at": tuple(int(m.group(k)) for k in (2, 3, 4)),
                            "facing": tuple(int(m.group(k))
                                            for k in (5, 6, 7)),
                            "applied": m.group(8) == "applied"})
        if len(out) <= i:
            break
    return out


def static_contract() -> None:
    print("\n=== what the operator has to be able to show")

    impl = (REPO / "src" / "mapgen" / "mapgen_geometry_edit.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_geometry_edit.h").read_text(
        encoding="utf-8", errors="replace")

    # `ground`, not `donor_bsp`: since 2026-09-09 every question the planner asks
    # about what the MAP is like goes to the map the gates re-ask it of - the
    # baseline the transaction hands over - while the GEOMETRY stays the
    # donor's, because a plan addresses brushes by index.
    check("it is planned from the sockets a bundle typed",
          "MapGenBundle_Survey(ground, donor, rooms, &set)" in impl)
    check("a socket with no measured width is not widened",
          "sock->derived" in impl)
    check("each way through is considered once, from one end",
          "sock->peer <= r" in impl)
    check("it is recorded as a PLANE, not as a side index",
          "side_on_plane(" in impl and "widen.dist = side->dist;" in impl)
    check("the header says why an index would not do",
          "an accepted edit may have dropped a brush" in header)

    print("\n=== and it declines when it cannot")

    check("there has to be more brush than is being taken",
          "thickness_behind(candidate, brush, side) < w->depth + WIDEN_KEEP"
          in impl)
    check("what is taken has to be this brush's alone",
          "MapGenClosure_SolidWithout(closure, candidate, p)" in impl)
    check("the closure is what makes 'somebody else's' answerable",
          "MapGenClosure_Build(candidate, owner, 1, &closure)" in impl)
    check("nothing flush against the face may be left behind",
          "playerclip brush is not solid" in impl)
    check("the finding that the old test was self-satisfying is written down",
          "yes by construction" in impl)
    check("a mover is not widened", "brush->model != 0" in impl)


def behaviour(probe: Path, work: Path) -> dict[str, list[dict]]:
    seen: dict[str, list[dict]] = {}
    for name in FIXTURES:
        bsp = compile_fixture(work, name)
        if not check(f"the {name} fixture compiles", bsp is not None):
            continue
        seen[name] = flanks(probe, bsp)

    print("\n=== rock behind both flanks: both move")
    got = seen.get("widen_thick", [])
    check("two flanks were planned", len(got) == 2, str(got))
    check("both of them moved", all(f["applied"] for f in got), str(got))

    print("\n=== thirty-two units of pier: that flank declines")
    got = seen.get("widen_thin", [])
    check("two flanks were planned", len(got) == 2, str(got))
    short = [f for f in got if f["at"][1] == 288]
    long_one = [f for f in got if f["at"][1] == 192]
    check("the short pier was one of them", len(short) == 1, str(got))
    check("and it declined", bool(short) and not short[0]["applied"],
          str(short))
    check("while the long one moved",
          bool(long_one) and long_one[0]["applied"], str(long_one))

    print("\n=== an invisible brush flush against a flank: that one declines")
    got = seen.get("widen_clipped", [])
    check("two flanks were planned", len(got) == 2, str(got))
    clipped = [f for f in got if f["facing"] == (0, 1, 0)]
    clean = [f for f in got if f["facing"] == (0, -1, 0)]
    check("the clipped flank declined",
          bool(clipped) and not clipped[0]["applied"], str(clipped))
    check("the clean one moved", bool(clean) and clean[0]["applied"],
          str(clean))
    return seen


def through_the_transaction(work: Path) -> None:
    print("\n=== and what it produced compiles, plays, and moved something")

    exe = work / "bin" / "transaction.exe"
    err = build(REPO, exe, TRANSACTION)
    if not check("the transaction compiles", not err, err):
        return
    donor = work / "widen_thick" / "widen_thick.bsp"
    job = work / "txn"
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)

    run = subprocess.run([str(exe), str(COMPILER), str(donor), str(job),
                          "q2mg_wd", str(GAME), "1", "2", "--only",
                          "widen-connector"],
                         capture_output=True, text=True, timeout=3600)
    out = run.stdout
    check("something was accepted", " ACCEPTED " in out, out[-500:])
    check("and it moved the divergence",
          re.search(r"divergence\s+\d+ \(\+[1-9]", out) is not None,
          out[-500:])
    check("the accepted candidate never moved under a rejection",
          "immutability violations: 0" in out, out[-300:])


MUTATIONS = {
    "an operator that does not check how much brush is left": (
        b"""    if (thickness_behind(candidate, brush, side) < w->depth + WIDEN_KEEP) {
        SET(MAPGEN_WIDEN_TOO_THIN);
        return false;
    }""",
        b"""    if (thickness_behind(candidate, brush, side) < 0.0f) {
        SET(MAPGEN_WIDEN_TOO_THIN);
        return false;
    }""",
        "widen_thin", 288,
    ),
    "an operator that leaves what was flush against the face": (
        # The condition itself, so the anchor does not move every time the
        # reasoning beside it is written down.
        b"            if (apart <= 256.0f * 256.0f) {",
        b"            if (apart < 0.0f) {",
        "widen_clipped", -32,
    ),
}


def red(work: Path) -> None:
    print("\n=== and each refusal is load-bearing")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "widen")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_geometry_edit.c"
        pristine = target.read_bytes()
        exe = box.root / "red.exe"
        for name, (anchor, replacement, fixture, at_y) in MUTATIONS.items():
            found, patched, count = resolve_anchor(pristine, anchor,
                                                   replacement)
            if not check(f"{name}: the anchor is where it says", count == 1,
                         f"{count} occurrences"):
                continue
            target.write_bytes(pristine.replace(found, patched, 1))
            err = build(box.root, exe, PROBE)
            if not check(f"{name}: it still compiles", not err, err):
                target.write_bytes(pristine)
                continue

            got = flanks(exe, work / fixture / f"{fixture}.bsp")
            guilty = [f for f in got if f["at"][1] == at_y]
            check(f"{name}: the flank that should decline is carved",
                  bool(guilty) and guilty[0]["applied"], str(got))
            target.write_bytes(pristine)
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

    print("=== the widen operator")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()

    probe = args.work / "bin" / "probe.exe"
    err = build(REPO, probe, PROBE)
    if check("the probe compiles", not err, err):
        behaviour(probe, args.work)
        through_the_transaction(args.work)
        if not args.no_red:
            red(args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
