"""GF6B-R: one edit at a time, and the accepted candidate proves it did not move.

The batch applier planned two hundred edits, applied all of them to one
candidate and compiled once at the end. Codex's ruling of 2026-09-02 is that
this is not a transaction however the outer sequence is named: no edit has a
cost, no edit can be discarded, and nothing measures what an edit was worth -
which is the whole reason a fork spends its budget on paint and comes back
looking like the donor.

This asserts the replacement. Three parts:

  * the static contract - a clone per attempt, exactly ONE edit applied to it,
    a directory created empty for it, a compile inside the attempt, every hard
    gate on what came out, and a ledger line whatever the verdict was;

  * the behaviour, against the real pinned compiler and a real donor - the
    verdicts are the ones the map earns, an accepted edit moved the divergence
    and a rejected one moved nothing at all;

  * the mandatory RED - a transaction that KEEPS a rejected candidate is
    detected by the transaction itself. Mutated in a disposable sandbox, never
    in the shared tree.

    python tools/check_mapgen_transaction.py [--work DIR] [--no-real]
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

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
from mapgen_load_guard import game_dir  # noqa: E402  (brief 13 W1: the game folder of this run)
GAME = Path(game_dir())
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831"
                    r"\transaction")

# The donor every behavioural case runs on. Small on purpose: each attempt
# costs a real compile, and a guard that took an hour is a guard nobody runs.
DONOR_FIXTURE = "faceted_wall"

SOURCES = [
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
    """Compile the driver out of `root`. Returns the compiler's complaint.

    The WHOLE complaint goes to `<out>.build.log` beside the binary, and the
    error lines come back to the caller. It used to return `stderr[-2000:]`, and
    this tree's standing warnings are longer than that: MEASURED 2026-09-13, a
    real `error: assignment of read-only variable` was truncated away and the
    caller saw a clean tail of warnings with no binary and no reason. Nobody
    should need a private copy of this function to see why a build failed.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in SOURCES] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    try:
        out.with_suffix(out.suffix + ".build.log").write_text(
            run.stderr, encoding="utf-8", errors="replace")
    except OSError:
        pass
    if run.returncode == 0 and out.is_file():
        return ""
    errs = [ln for ln in run.stderr.splitlines() if "error" in ln.lower()]
    return "\n".join(errs) if errs else run.stderr[-2000:]


def fresh(work: Path, name: str) -> Path:
    job = work / name
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    return job


# ---- the static contract ---------------------------------------------------


def body_of(source: str, name: str) -> str:
    """The text of one function, from its opening brace to the matching one.

    Skips forward declarations. Two functions that call each other need one of
    them declared first, and taking that declaration as the definition finds
    the next brace in the file - which belongs to somebody else, so every
    assertion afterwards is about the wrong function.
    """
    at = -1
    while True:
        at = source.find("\n" + name, at + 1)
        if at < 0:
            return ""
        close = source.find(")", at)
        if close < 0:
            return ""
        rest = source[close + 1:close + 40].lstrip()
        if rest.startswith("{"):
            break
    start = source.find("{", at)
    depth, i = 0, start
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    return source[start:]


def static_contract(header: str, impl: str) -> None:
    print("\n=== the shape of one attempt")

    check("the interface takes ONE typed edit, not a plan",
          re.search(r"MapGenTransaction_Try\(mapgen_transaction_t \*txn,\s*"
                    r"const mapgen_typed_edit_t \*edit", header) is not None)
    check("a typed edit names its kind, its target and its amount",
          all(f in header for f in ("mapgen_edit_kind_t kind;",
                                    "uint32_t           target;",
                                    "int32_t            amount;")))

    attempt = body_of(impl, "try_one")
    judged = body_of(impl, "judge")
    # Steps three to six live in `judge`, which an attempt and a materialise
    # share: two copies of the gates would be two chances for them to drift.
    inner = attempt + judged
    check("the attempt is a function of its own", bool(attempt))
    check("its later steps are shared with materialising, not copied",
          bool(judged) and impl.count("MapCompile_RunProfile(txn->adapter") == 1)

    check("1: it works on a CLONE of the accepted candidate",
          "MapGenGeometry_Clone(txn->accepted, &candidate)" in attempt)
    check("2: exactly one edit is applied",
          attempt.count("MapGenGeometryEdit_ApplyOne(") == 1)
    check("the batch applier is not reachable from an attempt",
          "MapGenGeometryEdit_Apply(" not in inner)
    check("an operator that declined costs no compile",
          attempt.index("if (!changed)") < attempt.index("judge(txn,"))
    check("3: the attempt gets a directory created for it",
          "attempt_dir(txn, attempt" in inner)
    check("that directory is numbered by the attempt",
          'try_%04u' in impl)
    check("3: the candidate is written and compiled inside the attempt",
          "MapGenGeometry_WriteValve220(candidate" in inner
          and "MapCompile_RunProfile(txn->adapter" in inner)
    check("4: playability is judged on what CAME OUT, not on the candidate",
          "load_bsp(compiled.bsp_path)" in inner)
    check("4: it is the product verdict, not the donor-only one",
          "MapGenReach_Passed(&reach_report)" in inner
          and "ConnectivityOnly" not in impl)
    # Against the BASELINE, which is the donor's own geometry through this
    # compiler with nothing applied. Measuring against the file the donor
    # arrived in put fidelity 100 - a run that applies nothing - at fifty-six
    # permille of q2dm1, because no two compilers split a surface the same way.
    check("5: divergence is measured against the baseline, not the donor's file",
          "MapGenDivergence_Measure(txn->baseline_bsp, built" in inner
          and "MapGenDivergence_Measure(txn->donor_bsp" not in inner)
    check("an edit nobody could price is refused, not assumed harmless",
          "if (!measured)" in inner)
    # Codex, 2026-09-06 section 3: the cheap score is route-free and rounded to
    # integer permille, so a zero in it is six different findings and only one
    # of them is NO_EFFECT. It may open the question; it may not close it.
    check("the cheap score is taken with routes OFF - it is the scalar"
          " progress the schedule steers by, not an identity test",
          "MapGenDivergence_Measure(txn->baseline_bsp, built, 100, false," in inner)
    check("a zero from it escalates to evidence that can decide",
          "step->divergence_delta == 0" in inner
          and re.search(r"edit_effect\(txn, candidate, built, reach,"
                        r"\s+compiled\.bsp_sha256,\s+step\)", inner)
              is not None)
    check("and only a MEASURED nothing is named NO_EFFECT",
          "effect == EDIT_NOTHING" in inner
          and "MAPGEN_TXN_REJECTED_NO_EFFECT" in inner
          and "MAPGEN_TXN_REJECTED_UNMEASURED" in inner)
    effect = body_of(impl, "edit_effect")
    check("its sound bound is the compiled bytes, not a score",
          "strcmp(bsp_sha256, txn->accepted_sha256)" in effect)
    check("its authoritative measure is against the map the edit was applied"
          " to, with routes ON",
          "load_bsp(txn->accepted_bsp)" in effect
          and "MapGenDivergence_MeasureWalked(before, parent," in effect)

    # D19 (assignment 23): the routes come from the walks this attempt already
    # has - the parent's and the candidate's - and not from walking both files
    # again inside the measurement.
    def routes_from_walks(text: str) -> bool:
        body = body_of(text, "edit_effect")
        return ("MapGenDivergence_MeasureWalked(before, parent," in body
                and "parent_walk(txn, step)" in body
                and "MapGenDivergence_Measure(before, built, 100, true"
                    not in body)

    check("edit_effect measures routes from walks it is given, not from files",
          routes_from_walks(impl))
    # Controlled RED, in memory - nothing on disk is opened for writing: the
    # call assignment 22 made, put back.
    walked_call = ("MapGenDivergence_MeasureWalked(before, parent,\n"
                   "                                                   parent != NULL, built,\n"
                   "                                                   walk, walk != NULL, 100,\n"
                   "                                                   &d)")
    old_call = "MapGenDivergence_Measure(before, built, 100, true, &d)"
    if check("the walked call to put back is where it says",
             impl.count(walked_call) == 1,
             f"{impl.count(walked_call)} occurrences"):
        mutated = impl.replace(walked_call, old_call, 1)
        check("RED: the file-walking call put back is caught",
              not routes_from_walks(mutated))
    # D25 (assignment 24): a family that moves no architecture is judged by
    # the entities it names - after the identical-bytes bound, and before any
    # measure of cells or routes, which a swap can never move.
    def paint_on_entities(text: str) -> bool:
        body = body_of(text, "edit_effect")
        at_bytes = body.find("strcmp(bsp_sha256, txn->accepted_sha256)")
        at_named = body.find("MapGenGeometryEdit_NamedEntities(txn->plan,")
        at_cells = body.find("MapGenDivergence_MeasureWalked(")
        return (0 <= at_bytes < at_named < at_cells
                and "entity_differs(txn->accepted, candidate, named[k])"
                    in body
                and "step->structural_routes = false;" in body)

    check("a paint edit is measured on its entities, not on cells",
          paint_on_entities(impl))
    # Controlled RED, in memory: the paint branch taken out, so a swap goes
    # back to the cell measure that refused every one of them.
    paint_head = "    uint32_t named[2];\n"
    paint_tail = ("        return moved ? EDIT_MOVED : EDIT_NOTHING;\n"
                  "    }\n")
    head_at = impl.find(paint_head)
    tail_at = impl.find(paint_tail, head_at)
    if check("the paint branch to take out is where it says",
             impl.count(paint_head) == 1 and 0 <= head_at < tail_at,
             f"{impl.count(paint_head)} occurrences"):
        mutated = impl[:head_at] + impl[tail_at + len(paint_tail):]
        check("RED: a paint edit sent back to the cell measure is caught",
              not paint_on_entities(mutated))
    check("an incomplete measurement is never accepted as a complete one",
          "if (!d.complete)" in effect
          and "return EDIT_UNMEASURED;" in effect)
    check("the raw changed-cell count is carried on the ledger line, not only"
          " the rounded score",
          "step->structural_cells = d.changed_cells;" in effect
          and "structural_cells" in header)

    # Rows 297 and 299: an attempt whose compiled map HIDES a surface in plain
    # sight is refused - asked from the parent's places before its walk and from
    # its own after it - and the sightline stops where the compiler's visibility
    # can: every visible content, in a box a unit each way.
    hidden = "return step->verdict = MAPGEN_TXN_REJECTED_HIDDEN;"
    swept = ("sm->p, bmin, bmax,\n"
             "                            MAPGEN_TXN_HIDDEN_STOPS, &tr);")

    def hides_refused(text: str) -> bool:
        body = body_of(text, "judge")
        walk = body.find("MapGenReach_Explore(built,")
        before, after = body[:max(walk, 0)], body[max(walk, 0):]
        helper = body_of(text, "hidden_from_walk")
        return (walk > 0
                and "hidden_from_walk(txn->accepted_map, built,\n" in before
                and "before, vlo, vhi, witness);" in before and hidden in before
                and "hidden_from_walk(txn->accepted_map, built,\n" in after
                and "reach, vlo, vhi, witness);" in after and hidden in after
                and "MapGenTransaction_HiddenInSight(parent, candidate," in helper
                and "#define MAPGEN_TXN_HIDDEN_STOPS 0x7F\n" in text
                and "#define MAPGEN_TXN_HIDDEN_HALF  1.0f\n" in text
                and text.count(swept) == 1)

    check("an attempt that hides a surface in plain sight is refused, before and"
          " after its walk, the sightline stopped where visibility stops",
          hides_refused(impl))
    for label, anchor, broken in (
            ("the refusal before the walk",
             "lost);\n                MapGenBsp_Free(built);\n"
             "                MapGenGeometry_Free(candidate);\n"
             "                " + hidden + "\n",
             "lost);\n                MapGenBsp_Free(built);\n"
             "                MapGenGeometry_Free(candidate);\n"),
            ("the refusal after the walk",
             "                MapGenReach_Free(reach);\n"
             "                MapGenBsp_Free(built);\n"
             "                MapGenGeometry_Free(candidate);\n"
             "                " + hidden + "\n",
             "                MapGenReach_Free(reach);\n"
             "                MapGenBsp_Free(built);\n"
             "                MapGenGeometry_Free(candidate);\n"),
            ("the sightline's stops",
             "MAPGEN_TXN_HIDDEN_STOPS, &tr);",
             "MAPGEN_CONTENTS_SOLID, &tr);")):
        if check(f"{label}, to take out, is where it says",
                 impl.count(anchor) == 1, f"{impl.count(anchor)} occurrences"):
            check(f"RED: {label} taken out is caught",
                  not hides_refused(impl.replace(anchor, broken, 1)))

    # Row 302: an attempt whose compiled map loses a pickup at spawn that the
    # parent kept - inside a lift's resting deck - is refused before any walk.
    lost_return = ("            return step->verdict ="
                   " MAPGEN_TXN_REJECTED_LOST_PICKUP;\n")

    def loses_refused(text: str) -> bool:
        body = body_of(text, "judge")
        walk = body.find("MapGenReach_Explore(built,")
        before = body[:max(walk, 0)]
        return (walk > 0
                and "MapGenTransaction_PickupsLostAtSpawn(built, mine," in before
                and "MapGenTransaction_PickupsLostAtSpawn(txn->accepted_map,"
                in before
                and "return step->verdict = MAPGEN_TXN_REJECTED_LOST_PICKUP;"
                in before)

    check("an attempt that loses a pickup at spawn is refused before its walk",
          loses_refused(impl))
    if check("the lost-pickup refusal, to take out, is where it says",
             impl.count(lost_return) == 1,
             f"{impl.count(lost_return)} occurrences"):
        check("RED: the lost-pickup refusal taken out is caught",
              not loses_refused(impl.replace(lost_return, "", 1)))

    # Row 307: an attempt whose compiled map puts a spawn its parent kept clear
    # in the column a lift carries its rider through is refused before any walk.
    blocked_return = ("            return step->verdict ="
                      " MAPGEN_TXN_REJECTED_BLOCKED_SPAWN;\n")

    def blocks_refused(text: str) -> bool:
        body = body_of(text, "judge")
        walk = body.find("MapGenReach_Explore(built,")
        before = body[:max(walk, 0)]
        return (walk > 0
                and "MapGenTransaction_SpawnsInMoverColumns(built, mine," in before
                and "MapGenTransaction_SpawnsInMoverColumns(txn->accepted_map,"
                in before
                and "return step->verdict = MAPGEN_TXN_REJECTED_BLOCKED_SPAWN;"
                in before)

    check("an attempt that puts a spawn in a lift's column is refused before"
          " its walk", blocks_refused(impl))
    if check("the blocked-spawn refusal, to take out, is where it says",
             impl.count(blocked_return) == 1,
             f"{impl.count(blocked_return)} occurrences"):
        check("RED: the blocked-spawn refusal taken out is caught",
              not blocks_refused(impl.replace(blocked_return, "", 1)))

    print("\n=== and the accepted candidate is the only thing that advances")

    check("6: the accepted candidate is assigned in exactly one place",
          impl.count("txn->accepted = ") == 1)
    retain = judged[judged.index("txn->accepted = "):]
    check("it advances only after the gates have all been passed",
          judged.index("txn->accepted = ") > judged.index("if (!playable)")
          and judged.index("txn->accepted = ")
              > judged.index("step->divergence_delta == 0"))
    check("what it advances to is the artifact that was actually judged",
          "compiled.bsp_path" in retain)
    # Every rejection after the clone exists throws that clone away. Checked as
    # the text between one rejection and the one before it, because a leak here
    # is a leak per attempt and an attempt is a compile.
    pieces = judged.split("return step->verdict = MAPGEN_TXN_REJECTED")
    leaks = [n for n, piece in enumerate(pieces[1:-1], start=1)
             if "MapGenGeometry_Free(candidate)" not in piece]
    check("every rejection after the clone throws the clone away",
          not leaks, f"rejections {leaks} keep it")

    outer = body_of(impl, "MapGenTransaction_Try")
    check("the ledger records the attempt whatever the verdict was",
          "txn->steps[txn->num_steps++] = *step;" in outer
          and "txn->steps[txn->num_steps++]" not in judged)
    check("the ledger append is not conditional on acceptance",
          "if (verdict" not in outer.split("num_steps++")[0][-160:])

    print("\n=== building what it holds is not accepting anything")

    check("a run that spends nothing can still produce a map",
          "MapGenTransaction_Materialise" in header)
    check("nothing was applied, so nothing has to have moved",
          "require_movement && step->divergence_delta == 0" in impl)
    check("and it does not count as an acceptance",
          "if (require_movement)\n        txn->accepted_count++;" in impl)

    print("\n=== and an edit that jumps past the band is refused")

    check("a run can say what it is aiming at",
          "MapGenTransaction_SetBand" in header)
    check("an overshoot is measured against target plus tolerance",
          "> txn->band_target + txn->band_tolerance" in impl)
    check("it is discarded like any other refusal",
          "return step->verdict = MAPGEN_TXN_REJECTED_OVERSHOT" in impl)
    check("a run that named no band refuses nothing on this ground",
          "txn->has_band" in impl)

    print("\n=== the tenth mandatory RED, checked on every single attempt")

    check("the digest is taken before the attempt",
          "MapGenGeometry_CanonicalDigest(txn->accepted)" in
          outer.split("try_one(")[0])
    check("and again after it",
          "MapGenGeometry_CanonicalDigest(txn->accepted) != before" in outer)
    check("a rejection that moved it is counted against the transaction",
          "txn->violations++" in outer)
    check("only a rejection is held to it",
          "verdict != MAPGEN_TXN_ACCEPTED" in outer)
    check("the count is readable from outside",
          "MapGenTransaction_Violations" in header)

    print("\n=== no argument can switch a gate off")

    for forbidden in ("skip_", "relax", "ignore_", "allow_unplayable",
                      "no_gate", "force_accept"):
        check(f"nothing named {forbidden!r} reaches the transaction",
              forbidden not in impl and forbidden not in header)

    print("\n=== the verdicts are distinct, because each is a different thing "
          "to do about it")
    for verdict in ("ACCEPTED", "REJECTED_NOT_APPLIED", "REJECTED_WRITE",
                    "REJECTED_COMPILE", "REJECTED_UNPLAYABLE",
                    "REJECTED_NO_EFFECT", "REJECTED_OVERSHOT",
                    "REJECTED_SURFACE", "REJECTED_UNMEASURED"):
        check(f"MAPGEN_TXN_{verdict} is named and named back",
              f"MAPGEN_TXN_{verdict}" in header
              and f'return "{verdict}"' in impl)


# ---- the behaviour ---------------------------------------------------------

LINE = re.compile(r"^\s+(\d+) (\S+)\s+(\S+)(.*)$")
MOVED = re.compile(r"divergence\s+(\d+) \(([+-]\d+)\)")


def parse(out: str) -> tuple[list[dict], dict]:
    steps, tail = [], {}
    for line in out.splitlines():
        m = LINE.match(line)
        if m:
            row = {"i": int(m.group(1)), "kind": m.group(2),
                   "verdict": m.group(3), "rest": m.group(4)}
            moved = MOVED.search(m.group(4))
            if moved:
                row["after"] = int(moved.group(1))
                row["delta"] = int(moved.group(2))
            steps.append(row)
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            tail[k.strip()] = v.strip()
    return steps, tail


def make_donor(work: Path) -> Path | None:
    job = fresh(work, "donor")
    source = job / "donor.map"
    fixtures.FIXTURES[DONOR_FIXTURE](source)
    subprocess.run([str(COMPILER), "-bsp", "-threads", "4",
                    "-moddir", str(GAME), "-basedir", str(GAME),
                    "-gamedir", str(GAME), str(source)],
                   capture_output=True, text=True, timeout=1800)
    bsp = source.with_suffix(".bsp")
    return bsp if bsp.exists() else None


def drive(exe: Path, donor: Path, job: Path, attempts: int = 12,
          only: str = "") -> str:
    args = [str(exe), str(COMPILER), str(donor), str(job), "q2mg_t",
            str(GAME), "1", str(attempts)]
    if only:
        args += ["--only", only]
    run = subprocess.run(args, capture_output=True, text=True, timeout=3600)
    return run.stdout + run.stderr


def behaviour(work: Path) -> str:
    print("\n=== against the real compiler, one edit at a time")

    exe = work / "bin" / "transaction.exe"
    err = build(REPO, exe)
    if not check("the transaction compiles", not err, err):
        return ""

    donor = make_donor(work)
    if not check(f"the {DONOR_FIXTURE} donor compiles", donor is not None):
        return ""
    assert donor

    out = drive(exe, donor, fresh(work, "green"))
    steps, tail = parse(out)
    if not check("the schedule was spent", bool(steps), out[-600:]):
        return out

    # The ledger must account for EVERY attempt, whatever the verdict. This
    # caught a printing loop that stopped one verdict short of the enum, so
    # REJECTED_SURFACE was counted and never shown.
    ledger_total = sum(int(p.split("=")[1]) for p in
                       tail.get("ledger", "").split() if "=" in p)
    check("every attempt is in the ledger",
          bool(tail.get("ledger")) and ledger_total == len(steps),
          f"{tail.get('ledger', '')} totals {ledger_total}, "
          f"{len(steps)} attempts were made")
    check("the ledger and the attempt counter agree",
          f"{len(steps)} attempted" in out, out[-400:])

    accepted = [s for s in steps if s["verdict"] == "ACCEPTED"]
    check("something was accepted", bool(accepted))
    check("every accepted edit MOVED the divergence",
          all(s.get("delta", 0) != 0 for s in accepted),
          str([s.get("delta") for s in accepted]))
    check("the divergence the run reports is the last accepted one",
          bool(accepted) and f"divergence {accepted[-1]['after']} permille"
          in out)

    rejected = [s for s in steps if s["verdict"] != "ACCEPTED"]
    check("a refusal is a result, not a stop",
          bool(rejected) and len(accepted) > 0)
    check("a refusal reports which kind of refusal it was",
          all(s["verdict"].startswith("REJECTED_") for s in rejected))
    check("no refusal claims a divergence it did not earn",
          all("delta" not in s for s in rejected))

    check("the accepted candidate never moved under a rejection",
          tail.get("immutability violations") == "0",
          tail.get("immutability violations", "absent"))
    check("the accepted candidate has a digest to be held to",
          len(tail.get("accepted digest", "")) == 16,
          tail.get("accepted digest", "absent"))
    check("the artifact it points at is the one that was judged",
          Path(tail.get("accepted candidate", "")).exists(),
          tail.get("accepted candidate", "absent"))

    # The finding this whole mechanism was built to make.
    # The finding this whole mechanism exists for, asserted where it is now
    # observable: the schedule is ordered structural-first, so the edits that
    # move nothing are at the end of it and a run of the first dozen no longer
    # reaches them. Spending the relights alone says the same thing more
    # directly - every one of them compiles, stays playable, and moves the
    # divergence by zero.
    paint = fresh(work, "paint")
    only = subprocess.run(
        [str(exe), str(COMPILER), str(donor), str(paint), "q2mg_p", str(GAME),
         "1", "3", "--only", "relight"],
        capture_output=True, text=True, timeout=3600).stdout
    spent, _ = parse(only)
    check("an edit that compiles, stays playable and moves nothing is named "
          "as such",
          any(s["verdict"] == "REJECTED_NO_EFFECT" for s in spent),
          str([s["verdict"] for s in spent]))
    return out


# ---- the mandatory RED -----------------------------------------------------

KEEP_A_REJECT = (
    b"""    if (require_movement && step->divergence_delta == 0) {""",
    b"""    if (require_movement && step->divergence_delta == 0) {
        MapGenGeometry_Free(txn->accepted);
        txn->accepted = candidate;
        return step->verdict = MAPGEN_TXN_REJECTED_NO_EFFECT;
    }
    if (false) {""",
)


def red(work: Path, green: str) -> None:
    """A transaction that keeps what it rejected must say so about itself.

    The mutation is the defect in its exact shape: the candidate that compiled,
    stayed playable and moved the divergence by zero is REJECTED - the verdict
    is untouched - and retained anyway. Nothing about the verdicts changes; the
    only thing that changes is that the accepted candidate moved under one, and
    that is precisely what the transaction is supposed to notice about itself.
    """
    print("\n=== and a transaction that kept a rejected candidate would say so")

    if not check("the run to mutate was GREEN", "immutability violations: 0"
                 in green):
        return

    before = hash_tree(REPO)
    box = Sandbox(REPO, "transaction")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_transaction.c"
        data = target.read_bytes()
        anchor, replacement, count = _resolve(data, *KEEP_A_REJECT)
        if not check("the retain branch is where the mutation says it is",
                     count == 1, f"{count} occurrences"):
            return
        target.write_bytes(data.replace(anchor, replacement, 1))

        exe = box.root / "red.exe"
        err = build(box.root, exe)
        if not check("the mutated transaction still compiles", not err, err):
            return

        donor = work / "donor" / "donor.bsp"
        # Spending relights, because the branch the mutation breaks is the one
        # that refuses an edit which moved nothing - and the schedule is
        # ordered structural-first, so a run of the first dozen edits no longer
        # reaches one.
        out = drive(exe, donor, fresh(work, "red"), attempts=3,
                    only="relight")
        _, tail = parse(out)
        violations = tail.get("immutability violations", "absent")
        check("keeping a rejected candidate is caught by the transaction",
              violations.isdigit() and int(violations) > 0, violations)
        check("and it is caught while the verdict still says REJECTED",
              "REJECTED_NO_EFFECT" in out, out[-400:])
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing",
              hash_tree(REPO) == before)


def _resolve(data: bytes, anchor: bytes, replacement: bytes):
    from mapgen_red_support import resolve_anchor
    return resolve_anchor(data, anchor, replacement)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--no-real", action="store_true")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    header = (REPO / "inc" / "common" / "mapgen_transaction.h").read_text(
        encoding="utf-8", errors="replace")
    impl = (REPO / "src" / "mapgen" / "mapgen_transaction.c").read_text(
        encoding="utf-8", errors="replace")
    static_contract(header, impl)

    if not args.no_real:
        if check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
            green = behaviour(args.work)
            if green:
                red(args.work, green)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
