"""Does walking a level on several threads produce the same walk?

Codex conditionally approved the shape of the parallel walk on 2026-09-03 and
required it to be requalified before it counts: a sequential reference against
one, two and every performance core; narrow and wide frontiers; every reach
fixture; real donors including a mover-rich one; identical graphs and
certificates rather than similar numbers; the thread-creation and allocation
failure paths; and cancellation.

    python tools/check_mapgen_reach_parallel.py [--work DIR] [--quick]
        [--only NAME]

`--quick` runs the fixtures and the failure paths but not the donors, which
take about twenty minutes because the sequential reference of q2dm1 alone is
three and a half.

The measure of "the same walk" is a SHA-256 over every state in id order with
its origin, flags and degrees, followed by every edge in the order the walk
recorded it, plus the rendered certificates and the whole report. Two walks
that agree on those agree on the answer, not on its size.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_reach_fixtures as fixtures                        # noqa: E402

REPO = Path(__file__).resolve().parent.parent
from mapgen_pinned_compiler import pinned_compiler             # noqa: E402

# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and the guard stopped on its first compile
# with «file not found» (assignment 23 S1, 2026-09-14).
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260903"
                    r"\parallel")

SOURCES = [
    "tools/mapgen_reach_matrix.c",
    "src/mapgen/mapgen_reach.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/common/q2prox_cpu_topology.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  -- {detail}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


def build(work: Path, name: str, defines: list[str]) -> Path:
    exe = work / name
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-DUSE_LITTLE_ENDIAN=1",
         *defines, "-I" + str(REPO / "inc")]
        + [str(REPO / f) for f in SOURCES] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-2500:])
        raise SystemExit(f"cannot build {name}")
    return exe


def compile_map(path: Path) -> Path | None:
    bsp = path.with_suffix(".bsp")
    if bsp.is_file():
        return bsp
    run = subprocess.run(
        [str(COMPILER), "-bsp", "-threads", "8", "-moddir", str(GAME),
         "-basedir", str(GAME), "-gamedir", str(GAME), str(path)],
        capture_output=True, text=True, timeout=3600)
    if not bsp.is_file():
        print((run.stdout + run.stderr)[-800:])
        return None
    return bsp


def walk(exe: Path, bsp: Path, workers: int, extra: list[str] = []) -> dict:
    run = subprocess.run([str(exe), str(bsp), "--workers", str(workers),
                          *extra], capture_output=True, text=True,
                         timeout=7200)
    out = {"result": "?", "graph": "", "report": [], "certificates": "",
           "asked": 0, "ms": 0.0, "code": run.returncode,
           "levels": 0, "wide": 0}
    for line in run.stdout.splitlines():
        if line.startswith("result "):
            out["result"] = line.split()[1]
        elif line.startswith("graph "):
            out["graph"] = line.split()[1]
        elif line.startswith("report levels "):
            out["report"].append(line)
            parts = line.split()
            out["levels"], out["wide"] = int(parts[2]), int(parts[4])
        elif line.startswith("report "):
            out["report"].append(line)
        elif line.startswith("certificates "):
            out["certificates"] = line
        elif line.startswith("cancel asked "):
            out["asked"] = int(line.split()[2])
        elif line.startswith("elapsed "):
            out["ms"] = float(line.split()[1])
    return out


def concurrent(exe: Path, maps: list[Path], workers: int) -> list[dict]:
    """Several walks at once in one process, one row each.

    Each row is what that walk produced while the others were running. The
    caller compares every row with what the same map produces alone: anything
    two walks could be sharing shows up as one of them coming back different.
    """
    run = subprocess.run([str(exe), str(maps[0]), "--workers", str(workers),
                          "--quiet", "--concurrent",
                          *[str(m) for m in maps[1:]]],
                         capture_output=True, text=True, timeout=7200)
    rows: dict[int, dict] = {}
    for line in run.stdout.splitlines():
        if not line.startswith("concurrent "):
            continue
        parts = line.split()
        if parts[1] == "walks":
            continue
        index = int(parts[1])
        row = rows.setdefault(index, {"result": "?", "graph": "",
                                      "certificates": "", "states": 0,
                                      "map": ""})
        if parts[2] == "map":
            row["map"] = parts[3]
        elif parts[2] == "result":
            row["result"] = parts[3]
        elif parts[2] == "graph":
            row["graph"] = parts[3] if len(parts) > 3 else ""
        elif parts[2] == "states":
            row["states"] = int(parts[3])
        elif parts[2] == "certificates":
            row["certificates"] = " ".join(parts[3:])
    return [rows[i] for i in sorted(rows)]


def same(a: dict, b: dict) -> tuple[bool, str]:
    if a["result"] != b["result"]:
        return False, f"result {a['result']} vs {b['result']}"
    if a["graph"] != b["graph"]:
        return False, f"graph {a['graph'][:16]} vs {b['graph'][:16]}"
    if a["report"] != b["report"]:
        return False, "the reports differ"
    if a["certificates"] != b["certificates"]:
        return False, f"{a['certificates']} vs {b['certificates']}"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    exe = build(args.work, "matrix.exe", [])

    print("every fixture, sequential against parallel", flush=True)
    names = [args.only] if args.only else sorted(fixtures.FIXTURES)
    narrow = wide = 0
    for name in names:
        if name not in fixtures.FIXTURES:
            raise SystemExit(f"no fixture named {name!r}")
        target = args.work / f"{name}.map"
        fixtures.FIXTURES[name](target)
        bsp = compile_map(target)
        if bsp is None:
            check(f"{name} compiles", False, "the compiler refused it")
            continue
        one = walk(exe, bsp, 1)
        many = walk(exe, bsp, 0)
        two = walk(exe, bsp, 2)
        ok, detail = same(one, many)
        ok2, detail2 = same(one, two)
        check(f"{name}: one worker and every core agree", ok, detail)
        check(f"{name}: one worker and two agree", ok2, detail2)
        # How wide the search got is now a number the walk reports, so which
        # fixtures exercise the parallel path is measured rather than argued.
        # It must be the same number sequentially and in parallel - the width
        # of a level is a property of the map - and `same()` above already
        # requires that, because it compares every report line.
        if one["result"] == "OK":
            if one["wide"]:
                wide += 1
            else:
                narrow += 1
    print(f"        {narrow} fixtures are narrow frontiers - never eight "
          f"states in a level, so the walk stays on one thread by design - "
          f"and {wide} reach the width at which it splits")
    check("at least one fixture actually exercises the parallel path",
          wide >= 1,
          "every fixture is narrow, so the whole matrix above is one thread "
          "agreeing with one thread")

    # ----------------------------------------------------------------
    # the same map, again and again
    # ----------------------------------------------------------------
    #
    # A race that shows up one run in ten is not caught by running once. The
    # schedule is the operating system's to choose and it chooses differently
    # every time; the digest must not be.
    print("\nthe same schedule repeated", flush=True)
    wide_map = args.work / "wide_hall.map"
    fixtures.FIXTURES["wide_hall"](wide_map)
    wide_bsp = compile_map(wide_map)
    if wide_bsp is None:
        check("wide_hall compiles", False, "the compiler refused it")
    else:
        first = walk(exe, wide_bsp, 0)
        check("wide_hall is a wide frontier", first["wide"] >= 1,
              f"{first['wide']} of {first['levels']} levels reach eight "
              f"states; a narrow map cannot prove anything about threads")
        stable, why = True, ""
        for run_index in range(5):
            again = walk(exe, wide_bsp, 0)
            ok, detail = same(first, again)
            if not ok:
                stable, why = False, f"run {run_index + 2}: {detail}"
                break
        check("six walks of the same map on every core give one digest",
              stable, why)

        # ------------------------------------------------------------
        # several walks at once, in one process
        # ------------------------------------------------------------
        #
        # Everything above runs one walk at a time, so nothing above could see
        # two of them treading on each other. This is that case: each walk on
        # its own thread with its own pool, and each required to produce
        # exactly what it produces alone. The wide map appears twice on
        # purpose - two walks over identical data is where a shared buffer
        # shows first.
        print("\nseveral independent walks at once, in one process",
              flush=True)
        door_map = args.work / "door.map"
        fixtures.FIXTURES["door"](door_map)
        tele_map = args.work / "teleporter.map"
        fixtures.FIXTURES["teleporter"](tele_map)
        others = [p for p in (compile_map(door_map), compile_map(tele_map))
                  if p is not None]
        maps = [wide_bsp, wide_bsp] + others
        # What each of them produces ALONE, which is the thing the
        # concurrent rows have to match. The same map named twice is walked
        # once here: its two concurrent rows both answer to this one result.
        solo = {str(m): walk(exe, m, 0) for m in dict.fromkeys(maps)}
        rows = concurrent(exe, maps, 0)
        check("every walk that was asked for came back",
              len(rows) == len(maps), f"{len(rows)} of {len(maps)}")
        for index, row in enumerate(rows):
            alone = solo.get(row["map"])
            if alone is None:
                check(f"walk {index} names a map that was asked for", False,
                      row["map"])
                continue
            ok = (row["result"] == alone["result"]
                  and row["graph"] == alone["graph"])
            check(f"walk {index} of {Path(row['map']).stem} is unchanged by "
                  f"the {len(maps) - 1} beside it", ok,
                  f"result {row['result']} vs {alone['result']}, "
                  f"graph {row['graph'][:16]} vs {alone['graph'][:16]}")
            check(f"walk {index} of {Path(row['map']).stem} witnesses the "
                  f"same certificates",
                  bool(row["certificates"])
                  and alone["certificates"].endswith(row["certificates"]),
                  f"{row['certificates']} vs {alone['certificates']}")

    print("\nthe failure paths, in builds that are not the product",
          flush=True)
    fixture = args.work / "door.map"
    fixtures.FIXTURES["door"](fixture)
    door = compile_map(fixture)
    donor = CORPUS / "q2dm1.bsp"

    no_threads = build(args.work, "matrix_nothreads.exe",
                       ["-DMAPGEN_REACH_TEST_THREAD_FAILURE=1"])
    if door:
        a = walk(exe, door, 0)
        b = walk(no_threads, door, 0)
        ok, detail = same(a, b)
        check("a thread that will not start is done inline, same graph", ok,
              detail)
    for nth in (1, 2, 3):
        starved = build(args.work, f"matrix_alloc{nth}.exe",
                        [f"-DMAPGEN_REACH_TEST_ALLOC_FAILURE={nth}"])
        if not door:
            break
        out = walk(starved, door, 0)
        # Codex, section 2.5: accepting OK here accepted a case where the
        # injected failure was never reached, which proves nothing. The
        # allocation must fire and the walk must refuse.
        check(f"allocation {nth} failing is ERR_MEMORY, not a crash",
              out["result"] == "ERR_MEMORY",
              f"result {out['result']}, exit {out['code']}")

    print("\ncancellation is bounded, not merely checked", flush=True)
    #
    # Codex, section 2.2: the token was asked before a level and before each
    # state, and not inside the burst - two hundred and fifty-six settles - nor
    # anywhere in the analysis that follows the walk. A cancel could therefore
    # wait for minutes and still return OK. This measures it on a real map.
    #
    donor_map = CORPUS / "q2dm1.bsp"
    if donor_map.is_file():
        plain = walk(exe, donor_map, 0)
        late = walk(exe, donor_map, 0, ["--cancel-after", "5000"])
        check("a cancel deep inside a real walk stops it in a fraction of the "
              "time",
              late["result"] == "CANCELLED"
              and late["ms"] < max(plain["ms"] * 0.25, 250.0),
              f"{late['ms']:.0f} ms against an uncancelled {plain['ms']:.0f}")
        print(f"        q2dm1: uncancelled {plain['ms']:.0f} ms, "
              f"cancelled after 5000 checks {late['ms']:.0f} ms")

    print("\ncancellation", flush=True)
    if door:
        stopped = walk(exe, door, 0, ["--cancel-after", "0"])
        check("a token that says stop immediately stops the walk",
              stopped["result"] == "CANCELLED",
              f"result {stopped['result']}")
        check("and it was asked", stopped["asked"] > 0,
              f"asked {stopped['asked']} times")
        late = walk(exe, door, 0, ["--cancel-after", "100000000"])
        plain = walk(exe, door, 0)
        ok, detail = same(late, plain)
        check("a token that never fires changes nothing", ok, detail)

    if not args.quick:
        print("\nthe donors, sequential against parallel", flush=True)
        # q2dm8 is in the binding matrix and was absent from the corpus; it
        # is extracted from the game's own pak rather than left out.
        for name in ("q2dm1", "q2dm2", "q2dm3", "q2dm8"):
            bsp = CORPUS / f"{name}.bsp"
            if not bsp.is_file():
                print(f"  SKIP  {name} is not in the corpus")
                continue
            one = walk(exe, bsp, 1)
            two = walk(exe, bsp, 2)
            many = walk(exe, bsp, 0)
            ok, detail = same(one, many)
            ok2, detail2 = same(one, two)
            check(f"{name}: one worker and every core agree", ok, detail)
            check(f"{name}: one worker and two agree", ok2, detail2)
            print(f"        {name}: {one['ms']:.0f} ms on one, "
                  f"{two['ms']:.0f} on two, {many['ms']:.0f} on every core; "
                  f"graph {many['graph'][:16]}")
    else:
        print("\n  SKIP  the donors (--quick)")
    if donor.is_file() and args.quick:
        pass

    print(f"\n{CASES} cases, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
