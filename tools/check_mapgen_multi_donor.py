"""GF8: the cross-donor path reaches the product, and says what each donor gave.

GF7's operator can put a room from another map into ours. Until the REQUEST
could name other donors, only a driver in the geometry layer could ask for that
- the generator could not - and an operator the product cannot reach is a
prototype, which is what the 2026-09-01 directive rejected GF1-GF6 for.

So this guard is about the PATH, not the operator:

  the request carries them   by path, because a request crosses a process
                             boundary to the worker and a pointer would not
                             survive it
  the transaction keeps them for as long as it lives, because the plan holds
                             borrowed pointers into their geometry and reads
                             them when a graft is applied
  the report says what each  gave. Section 4.2 requires a major intact
                             contribution from every active donor and forbids
                             silent omission, and neither half is answerable
                             from a run that only counts accepted edits.

Measured, q2dm1 at fidelity 90 seed 1 with q2dm2 and q2dm3 offered:

    donors     2 offered, 1 contributed, 1 grafts kept
    donor      q2dm2.bsp contributed
    donor      q2dm3.bsp gave nothing
    compiled   710412 bytes, sha256 fc0240736eedc301
    playable   6211 places, component 6211, 0 of 83 pickups out of reach

and the same run with no other donor offered produces a DIFFERENT map -
sha256 c2b32ed3e1a8a500 - which is what says the donors reached the schedule
rather than being carried and ignored.

    python tools/check_mapgen_multi_donor.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260904"
                    r"\multi_donor")

PIPELINE = [
    "tools/mapgen_pipeline_driver.c",
    "src/mapgen/mapgen_pipeline.c",
    "src/mapgen/mapgen_synthesis.c",
    "src/mapgen/mapgen_architecture.c",
    "src/mapgen/mapgen_blueprint.c",
    "src/mapgen/mapgen_brush.c",
    "src/mapgen/mapgen_entities.c",
    "src/mapgen/mapgen_mapfile.c",
    "src/mapgen/mapgen_layout.c",
    "src/mapgen/mapgen_topology.c",
    "src/mapgen/mapgen_recipe.c",
    "src/mapgen/mapgen_mix.c",
    "src/mapgen/mapgen_random.c",
    "src/mapgen/mapgen_lineage.c",
    "src/mapgen/mapgen_training.c",
    "src/mapgen/mapgen_snapshot.c",
    "src/mapgen/mapgen_features.c",
    "src/mapgen/mapgen_wiring.c",
    "src/mapgen/mapgen_space.c",
    "src/mapgen/mapgen_genome.c",
    "src/mapgen/mapgen_transaction.c",
    "src/mapgen/mapgen_equivalence.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_generate.c",
    "src/mapgen/mapgen_compiler.c",
    "src/mapgen/mapgen_divergence.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_reach.c",
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
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in PIPELINE] + ["-o", str(out), "-lm", "-lz"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


def run_pipeline(exe: Path, job: Path, donors: list[str],
                 fidelity: str = "75") -> dict:
    """
    Fidelity 75 by default, because that is where the band has the most room
    for a whole foreign room and the case is therefore the clearest.

    A fidelity's band is what the map is ALLOWED to differ by: 90 means 100
    permille from the donor, plus or minus 50, and 75 means 250 plus or minus
    50. A grafted room is a whole room from another map, so the tighter the
    band the harder the obligation is to meet.

    What this docstring used to say - that requiring a donor to contribute at
    90 is requiring the band to be broken, so a run naming `q2dm2.bsp gave
    nothing` has satisfied GF7 - is the reading Codex rejected on 2026-09-06.
    A selected donor contributes or the run returns a named conflict; it does
    not report OK. The 90 case is asserted that way below.
    """
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    argv = [str(exe), str(COMPILER), str(CORPUS / "q2dm1.bsp"), str(job),
            "q2mg_md", fidelity, "1", "--moddir", str(GAME)]
    for d in donors:
        argv += ["--donor", str(CORPUS / d)]
    run = subprocess.run(argv, capture_output=True, text=True, timeout=7200)
    out: dict = {"verdict": "?", "gave": {}, "text": run.stdout + run.stderr}
    lines = run.stdout.splitlines()
    if lines:
        out["verdict"] = lines[0].strip()
    for line in lines:
        m = re.match(r"\s+donors\s+(\d+) offered, (\d+) contributed,"
                     r" (\d+) grafts kept", line)
        if m:
            out["offered"] = int(m.group(1))
            out["contributed"] = int(m.group(2))
            out["kept"] = int(m.group(3))
        m = re.match(r"\s+donor\s+(\S+) (contributed|gave nothing)", line)
        if m:
            out["gave"][m.group(1)] = m.group(2) == "contributed"
        m = re.match(r"\s+compiled\s+\S+\s+(\d+) bytes, sha256 (\S+)", line)
        if m:
            out["bytes"] = int(m.group(1))
            out["sha256"] = m.group(2)
        m = re.match(r"\s+playable\s+(\d+) places, (\d+) spawns,"
                     r" component (\d+), (\d+) one-way", line)
        if m:
            out["places"] = int(m.group(1))
            out["component"] = int(m.group(3))
            out["one_way"] = int(m.group(4))
        m = re.search(r"(\d+) of (\d+) pickups out of reach", line)
        if m:
            out["pickups_lost"] = int(m.group(1))
    return out


def static_contract() -> None:
    print("\n=== the path, from the request to the report")

    ph = (REPO / "inc" / "common" / "mapgen_pipeline.h").read_text(
        encoding="utf-8", errors="replace")
    pc = (REPO / "src" / "mapgen" / "mapgen_pipeline.c").read_text(
        encoding="utf-8", errors="replace")
    tc = (REPO / "src" / "mapgen" / "mapgen_transaction.c").read_text(
        encoding="utf-8", errors="replace")
    th = (REPO / "inc" / "common" / "mapgen_transaction.h").read_text(
        encoding="utf-8", errors="replace")

    check("the request carries other donors by path",
          "other_donors[MAPGEN_PIPELINE_MAX_DONORS]" in ph)
    check("and says why a pointer would not do",
          "a pointer would not survive it" in ph)
    check("the pipeline passes them to the transaction",
          "MapGenTransaction_BeginWithDonors(" in pc)
    check("the transaction keeps them for its whole life",
          "the plan holds borrowed" in tc)
    #
    # One implementation behind the three ways to open a transaction. Adding a
    # third that forwarded to a second WITHOUT the donors is how they reached
    # the transaction and never reached the plan.
    #
    check("one implementation behind every way to open one",
          "static mapgen_transaction_result_t\nbegin_impl(" in tc)
    check("and why that matters is written down",
          "never reached the plan" in tc)

    print("\n=== and a contribution is a room in the FINISHED map")
    check("it is recorded where the edit and the verdict are both known",
          "verdict == MAPGEN_TXN_ACCEPTED" in tc
          and "MapGenGeometryEdit_GraftedFrom(txn->plan, planned->target)"
          in tc)
    check("not by the schedule position, and the trap is written down",
          "position in the SCHEDULE" in tc)
    check("a floor met by a discarded edit is refused as a floor",
          "not a floor" in tc)
    check("the report can name a donor that gave nothing",
          "donors_offered" in ph and "donor_used" in ph)
    check("and the transaction is what is asked",
          "MapGenTransaction_DonorContributed" in th)


def behaviour(work: Path) -> dict:
    print("\n=== two donors offered, and what the finished map contains")

    exe = work / "bin" / "pipeline.exe"
    err = build(REPO, exe)
    if not check("the pipeline compiles", not err, err):
        return {}

    both = run_pipeline(exe, work / "both", ["q2dm2.bsp", "q2dm3.bsp"])
    #
    # Two donors, and the contract wants a major intact bundle from EACH.
    #
    # It does not get one today: the schedule reaches a graft from q2dm2 and
    # not from q2dm3, so the run returns ERR_DONOR_OMITTED naming the second.
    # That is the honest verdict Codex asked for and it is a failure of reach
    # rather than of reporting - the case below is written to accept either the
    # contract being met or the conflict being named, and never a run that
    # publishes while a selected donor gave nothing.
    #
    if not check("the run either meets the contract or names the conflict",
                 both["verdict"] in ("OK", "ERR_DONOR_OMITTED"),
                 both["text"][-400:]):
        return {}
    check("it never reports OK with a donor that gave nothing",
          not (both["verdict"] == "OK"
               and any(v is False for v in both["gave"].values())),
          f"verdict {both['verdict']}, gave {both['gave']}")
    check("both donors are accounted for", both.get("offered") == 2,
          str(both.get("offered")))
    #
    # The two numbers that have to agree. The first version of this recorded
    # the contribution by the schedule position instead of the graft's own
    # index, and the report said something impossible - one graft kept and no
    # donor having contributed. A counter alone would have hidden that.
    #
    check("a kept graft means a donor contributed",
          both.get("kept", 0) > 0
          and both.get("contributed", 0) > 0,
          f"{both.get('kept')} kept, {both.get('contributed')} contributed")
    check("q2dm2 contributed a room", both["gave"].get("q2dm2.bsp") is True,
          str(both["gave"]))
    # Named, either way: a donor that gave nothing has to be visible by name,
    # because that is what makes the refusal a conflict somebody can act on.
    check("every donor offered is named in the report either way",
          set(both["gave"]) == {"q2dm2.bsp", "q2dm3.bsp"}, str(both["gave"]))

    print("\n=== and the map it made is one a player can be in")
    check("it compiled", both.get("bytes", 0) > 0, str(both.get("bytes")))
    check("every place a player can stand is in one component",
          both.get("places") == both.get("component")
          and both.get("places", 0) > 0,
          f"{both.get('places')} places, component {both.get('component')}")
    check("nothing is one-way", both.get("one_way") == 0,
          str(both.get("one_way")))
    check("and no pickup is out of reach", both.get("pickups_lost") == 0,
          str(both.get("pickups_lost")))

    print("\n=== and offering a donor is what changed the map")
    solo = run_pipeline(exe, work / "solo", [])
    check("the control run succeeds", solo["verdict"] == "OK",
          solo["text"][-300:])
    #
    # Same donor, same fidelity, same seed. If the map were identical the
    # donors would have been carried and ignored - which is exactly the
    # "prototype the product cannot reach" this section exists to close.
    #
    check("and it produced a different map",
          solo.get("sha256") and both.get("sha256")
          and solo["sha256"] != both["sha256"],
          f"{solo.get('sha256')} against {both.get('sha256')}")
    check("with no donors offered, none is reported",
          solo.get("offered", 0) == 0, str(solo.get("offered")))

    #
    # And where the band leaves little room for a foreign room, a donor that
    # gave nothing is a CONFLICT rather than a footnote.
    #
    # This guard used to assert the opposite - that such a run succeeds while
    # naming the omission - on the reading that GF7 forbids only SILENT
    # omission. Codex rejected that reading on 2026-09-06 (section 5): every
    # explicitly selected donor must contribute a major intact bundle, "or
    # return a named donor/constraint conflict without publication". Naming it
    # is how the conflict is reported, not permission to publish anyway.
    #
    print("\n=== a donor that gave nothing is a conflict, not a footnote")
    tight = run_pipeline(exe, work / "tight", ["q2dm2.bsp"], fidelity="90")
    gave = tight["gave"].get("q2dm2.bsp")
    check("the run either uses the donor it was given or refuses by name",
          (gave is True) or tight["verdict"] == "ERR_DONOR_OMITTED",
          f"verdict {tight['verdict']}, gave {tight['gave']}")
    check("and it never reports OK while a selected donor gave nothing",
          not (tight["verdict"] == "OK" and gave is False),
          f"verdict {tight['verdict']}, gave {tight['gave']}")
    # Whatever it decided, it decided it on a map that exists and is playable.
    check("the tight run still produced a compiled candidate",
          "compiled   OK" in tight["text"], tight["text"][-200:])

    return {"exe": exe, "both": both}


# The contract: a contribution is looked up by the GRAFT's own index, never by
# the edit's position in the schedule.
#
# This mutation used to substitute `edit->target` - the schedule position - for
# `planned->target`, which is the defect exactly as it happened. It stopped
# discriminating when grafts were ranked first among structural edits so that a
# donor's contribution is always reached (GF7 forbids silent omission): with a
# graft at schedule position 0, the schedule position and the graft index are
# BOTH 0, and the substitution became an equivalent rewrite. The gate reported
# a donor credited where it required none, which is the mutation failing to
# fire and not the contract failing to hold.
#
# It is repaired rather than dropped, and repaired to something strictly
# stronger: the lookup must use the graft's own index EXACTLY. An index one
# past it names no graft, so the run keeps a graft and credits nobody - the
# same impossible pair, provable again.
MUTATION = (
    b"""            const char *from =
                MapGenGeometryEdit_GraftedFrom(txn->plan, planned->target);""",
    b"""            const char *from =
                MapGenGeometryEdit_GraftedFrom(txn->plan, planned->target + 1u);""",
)


def red(work: Path) -> None:
    print("\n=== and the two numbers are what caught the index being wrong")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "multi-donor")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_transaction.c"
        pristine = target.read_bytes()
        anchor, replacement, count = resolve_anchor(pristine, *MUTATION)
        if not check("the lookup is where it says", count == 1,
                     f"{count} occurrences"):
            return
        target.write_bytes(pristine.replace(anchor, replacement, 1))
        red_exe = box.root / "red_pipeline.exe"
        err = build(box.root, red_exe)
        if not check("it still compiles with the wrong index", not err, err):
            target.write_bytes(pristine)
            return

        bad = run_pipeline(red_exe, work / "red", ["q2dm2.bsp", "q2dm3.bsp"])
        #
        # The defect exactly as it happened: the graft is still kept, and no
        # donor is credited for it. A run that only counted accepted edits
        # would look perfectly healthy.
        #
        check("the graft is still kept", bad.get("kept", 0) > 0,
              str(bad.get("kept")))
        check("but no donor is credited, which cannot be true",
              bad.get("contributed", -1) == 0, str(bad.get("contributed")))
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

    print("=== MAPGEN-1 GF8: the cross-donor path through the product")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()
    got = behaviour(args.work)
    if got and not args.no_red:
        red(args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("PASS" if not FAILURES else "FAIL"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
