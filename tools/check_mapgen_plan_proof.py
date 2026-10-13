"""Brief 16 D1-D3 guard: the PO's own run, replayed dry through the new plan - what it would have built, and what not.

The PO, 10.10 (mg_10_6695, q2dm3, 2 h 42 min for 27 %): «вначале выкопаю яму, а потом проверю, а можно ли из неё
выбраться, а изначально можно было понимать можно ли из неё выбраться или нет». 72 of that run's 140 builds ended
REJECTED_NO_EFFECT, _UNPLAYABLE or _BURIED_ROUTE - each a compile and a minute's walk for a verdict the plan could have
known. This replays the run's own ledger (`pipeline.exe --replay-dry`: no generation - every accepted row compiled again
from its edit, every row's edit proved as an observer, the run stopped at the ledger's end) and asks:

  1 of those 72, at least 65 are known before a build: the proof refuses it (D1), its site was refused before (D3), or
    its family moves nothing the metric counts (D2: the liquids swapped);
  2 not one of the 64 accepted edits is refused by the proof;
  3 the plan says its word at every round (`stage=plan-value`), and the first later deal with nothing new worth
    building ends the edits (it says «worthy=0»): every deal before it brought a new proved edit worth half a permille
    or more, and the run deals fewer rounds than the 9 it dealt (its rounds 5..8 offered only what had been tried);
  4 (D2) the plan's first word - the difference it says its plan can reach - is within 5 points of what the run truly
    reached (the ledger's last line: 27.2 %).

Brief 17 D5 (Fable, 11.10): and on the two stretched runs at his options (q2dm3 6695 and q2dm1 6675, frame 150/50,
Studio 3.21) the plan's first word, as the run said it, is within 5 points of what the run reached.
A set of edits changes the UNION of their cells: two digs under one sky lift change most of the same cells, and the
sum said 89 % on warped q2dm1 where the run reached 66 %; and a large dig is built dry before it is counted (the
annex that opened high on every build was 5.4 points of that word).

RED: `--red` replays with `--no-proof` - the proof's own share of 1 (the buried places) comes back, and 1 fails. The
union's own RED is the q2dm1 trial of brief 17: summed edit by edit the word said 89.2 % where the run reached 66.4.

    python tools/check_mapgen_plan_proof.py [--work DIR] [--red] [--keep]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_equivalence import PIPELINE_SOURCES, build  # noqa: E402

# brief 18 D4: the reference is a run of THIS code (q2dm3 6695 at the 10.10 options, 140 builds); the 10.10 run
# itself is kept beside it for the record - brief 17 deals otherwise and it no longer replays past its row 73
RUN = Path(__file__).resolve().parent / "fixtures" / "mapgen_runs" / "mg_b18_ref_q2dm3"
OLD_RUN = Path(__file__).resolve().parent / "fixtures" / "mapgen_runs" / "mg_10_6695_q2dm3"
# brief 18: two rows of q2dm3 6695 at 150 % - the storey room, then the tunnel and lift under the same sky whose
# build ALONE leaks (its trial build at the plan fails) and after the storey room is sealed; the run of 12.10 15:49
# accepted both, the run of 22:34 answered the lift from its failed trial build after 27 edits and lost it
LIFT = Path(__file__).resolve().parent / "fixtures" / "mapgen_runs" / "mg_b18_q2dm3_lift"
STRETCHED = [Path(r"O:\Claude2\MapgenStudio\data\runs\mg_b18_q2dm3"),
             Path(r"O:\Claude2\MapgenStudio\data\runs\mg_b18_q2dm1")]
ENGINE = Path(r"O:\Claude2\MapgenStudio\engine")
MODDIR = Path(r"O:\Claude2\q2pro-release\baseq2")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen_plan_proof")
NO_WINDOW = 0x08000000
COSTLY = ("REJECTED_NO_EFFECT", "REJECTED_UNPLAYABLE", "REJECTED_BURIED_ROUTE")
FAILED = 0


def check(what: str, ok: bool, detail: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def launch_args(run: Path) -> list[str]:
    """The run's own engine arguments, from its launch line - the same plan, the same options."""
    line = [l for l in (run / "launches.txt").read_text(encoding="utf-8").splitlines() if "pipeline.exe" in l][-1]
    words = line.split(" pipeline.exe ", 1)[1].split(" ")
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if w == "--light-flags":                 # one argument of several words, up to the next option
            j = i + 1
            while j < len(words) and not words[j].startswith("--"):
                j += 1
            out += [w, " ".join(words[i + 1:j])]
            i = j
            continue
        out.append(w)
        i += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--red-measured", action="store_true",
                    help="RED: the word as estimated, not held to its trial builds' count - the stretched q2dm1 fails")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    if not (RUN / "ledger.txt").is_file():
        print(f"no ledger at {RUN}")
        return 2
    a.work.mkdir(parents=True, exist_ok=True)
    srcs = list(PIPELINE_SOURCES)
    if a.red:
        # brief 17 D5's RED: the word summed edit by edit
        text = (REPO / "src" / "mapgen" / "mapgen_pipeline.c").read_bytes()
        rule = b"static const bool g_plan_word_union = true;"
        if not check("RED: the union rule is where it says", text.count(rule) == 1):
            return 1
        red_src = a.work / "red_mapgen_pipeline.c"
        red_src.write_bytes(text.replace(rule, b"static const bool g_plan_word_union = false;"))
        srcs = [str(red_src) if s.endswith("mapgen_pipeline.c") else s for s in PIPELINE_SOURCES]
    if a.red_measured:
        text = (REPO / "src" / "mapgen" / "mapgen_pipeline.c").read_bytes()
        rule = b"static const bool g_plan_word_measured = true;"
        if not check("RED: the measured rule is where it says", text.count(rule) == 1):
            return 1
        red_src = a.work / "red_measured_mapgen_pipeline.c"
        red_src.write_bytes(text.replace(rule, b"static const bool g_plan_word_measured = false;"))
        srcs = [str(red_src) if s.endswith("mapgen_pipeline.c") else s for s in PIPELINE_SOURCES]
        exe = build(a.work, "pipeline_red_measured.exe", srcs, strict=False)
        for run in STRETCHED:
            if check(f"the stretched run {run.name} is on the disk", (run / "ledger.txt").is_file()):
                own_word(a, exe, run)
        print("FAIL" if FAILED else "PASS")
        return 1 if FAILED else 0
    exe = build(a.work, "pipeline_red.exe" if a.red else "pipeline.exe", srcs, strict=False)
    replay(a, exe, RUN, full=True)
    lift(a, exe)
    for run in STRETCHED:
        if check(f"the stretched run {run.name} is on the disk", (run / "ledger.txt").is_file()):
            own_word(a, exe, run)
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


def own_word(a, exe: Path, run: Path) -> None:
    """Brief 17 D5: the plan's first word against what the run reached.

    The word is dealt AGAIN here by this code (`--plan-only` at the run's own options: the same seed, the same deal -
    brief 16 D2's measure of a ledger by an engine other than the one that made it), not read from the run's
    progress: the word is said and steers nothing, so a build that only says it better makes the same map, and the
    map need not be made again for its record to carry the new number. The run's own word is said beside it.

    Replaying a stretched run dry to its end is not asked here."""
    progress = (run / "progress.txt").read_text(encoding="utf-8", errors="replace")
    words = [dict(re.findall(r"(\w+)=(\S+)", l)) for l in progress.splitlines() if "stage=plan-value" in l]
    reached = re.search(r"divergence (\d+) of target", (run / "ledger.txt").read_text(encoding="utf-8"))
    recorded = int(words[0]["can"]) if words and "can" in words[0] else None
    job, keep = job_of(a, run)
    subprocess.run([str(exe)] + keep + ["--plan-only"], capture_output=True, text=True, creationflags=NO_WINDOW,
                   timeout=3600)
    dealt = [dict(re.findall(r"(\w+)=(\S+)", l))
             for l in (job / "progress.txt").read_text(encoding="utf-8", errors="replace").splitlines()
             if "stage=plan-value" in l]
    first = int(dealt[0]["can"]) if dealt and "can" in dealt[0] else None
    turns = [l.split("first=", 1)[1].split()[0] for l in progress.splitlines() if "stage=plan-turns round=0" in l]
    again = [l.split("first=", 1)[1].split()[0]
             for l in (job / "progress.txt").read_text(encoding="utf-8", errors="replace").splitlines()
             if "stage=plan-turns round=0" in l]
    check(f"{run.name}: dealt again, the plan is the run's own (its first turns)",
          bool(again) and (not turns or turns[0] == again[0]),
          f"the run {turns[0] if turns else '(a record older than the turns line)'}, now {again[0] if again else '-'}")
    check(f"{run.name}: the plan's first word is within 5 points of what the run reached",
          reached is not None and first is not None and abs(first - int(reached.group(1))) <= 50,
          f"says {first / 10 if first is not None else '-'}% (measured against estimated cells "
          f"{dealt[0].get('tried', '-') if dealt else '-'}), reached {int(reached.group(1)) / 10 if reached else '-'}%; "
          f"the run's own record said {recorded / 10 if recorded is not None else '-'}%")
    if not a.keep:
        shutil.rmtree(job, ignore_errors=True)


def lift(a, exe: Path) -> None:
    """Brief 18: a trial build that FAILED says it of the map it stood on - the edit is built again at its turn once
    the map has changed. RED (`--dry-failed-stands`): the lift the run accepted is refused from its trial build."""
    job, keep = job_of(a, LIFT)
    keep += ["--dry-failed-stands"] if a.red else []
    print(f"replaying {LIFT.name} dry{' (RED)' if a.red else ''}", flush=True)
    r = subprocess.run([str(exe)] + keep, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=3600)
    progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace")
    rows = [dict(re.findall(r'(\w+)=("[^"]*"|\S+)', l)) for l in progress.splitlines() if "stage=dry-row" in l]
    if not check(f"{LIFT.name}: the ledger replays to its end", "the dry replay is over" in progress,
                 f"{len(rows)} rows"):
        print(r.stdout[-1500:], r.stderr[-1500:])
        return
    failed = [dict(re.findall(r'(\w+)=("[^"]*"|\S+)', l)) for l in progress.splitlines()
              if "stage=plan-dry" in l and "its build alone failed" in l]
    mine = [d for d in rows if d["was"] == "ACCEPTED" and any(f["edit"] == d["edit"] for f in failed)]
    check(f"{LIFT.name}: the case is in it - an accepted dig whose trial build alone failed", len(mine) >= 1,
          f"{len(mine)} of {len(rows)} rows; trial builds failed: " + ", ".join(f["edit"] for f in failed))
    wrong = [d for d in mine if d["proof"] not in ("passed", "-")]
    check("a dig whose trial build failed is built again once the map has changed, not refused from the plan",
          not wrong, f"{len(wrong)} of {len(mine)}"
          + (": " + "; ".join(f"{d['edit']} {d['family']} {d['why']}" for d in wrong[:3]) if wrong else ""))
    # ... and keeps its turn by its value: the run of 12.10 15:49 built the lift second, right after the storey room;
    # put last, it waits for the plan's small edits to build about its site
    turns = next((l.split("first=", 1)[1].split()[0].split(",") for l in progress.splitlines()
                  if "stage=plan-turns round=0" in l), [])
    check("a dig whose trial build failed keeps its turn by its value (the lift: second of the plan)",
          bool(mine) and all(d["edit"] in turns[:2] for d in mine), "the first turns: " + ", ".join(turns))
    if not a.keep:
        shutil.rmtree(job, ignore_errors=True)


def job_of(a, run: Path) -> tuple[Path, list[str]]:
    """A job folder for the run's ledger and the run's own engine arguments for a dry replay in it."""
    job = a.work / (("red_" if a.red else "job_") + run.name)
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True)
    shutil.copy(run / "ledger.txt", job / "ledger.txt")
    args = launch_args(run)
    # the run's compiler, donor and moddir as installed; its job folder this one; no checkpoints, a share of memory
    args[0], args[1], args[2] = str(ENGINE / "q2tool.exe"), str(ENGINE / "donors" / Path(args[1]).name), str(job)
    keep, i = [], 0
    while i < len(args):
        if args[i] in ("--memory", "--checkpoints"):
            i += 2
            continue
        if args[i] == "--moddir":
            keep += ["--moddir", str(MODDIR)]
            i += 2
            continue
        keep.append(args[i])
        i += 1
    return job, keep + ["--memory", "4000", "--checkpoints", "0", "--replay-dry"]


def replay(a, exe: Path, run: Path, full: bool) -> None:
    job, keep = job_of(a, run)
    # brief 18: RED also builds again what the plan's trial builds refused (a leak, a machine nothing can operate)
    keep += ["--no-proof", "--no-dry-refusals"] if a.red and full else []
    print(f"replaying {run.name} dry{' (RED)' if a.red else ''}", flush=True)
    r = subprocess.run([str(exe)] + keep, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=3600)
    progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace")
    rows = [dict(re.findall(r'(\w+)=("[^"]*"|\S+)', l)) for l in progress.splitlines() if "stage=dry-row" in l]
    if not check(f"{run.name}: the ledger replays to its end", "the dry replay is over" in progress,
                 f"{len(rows)} rows"):
        print(r.stdout[-1500:], r.stderr[-1500:])
        return
    # brief 17: a row the plan now deals otherwise (mg_10_6695's windows: their kind was the draw's then, the plan's
    # now) is gone past and said - few, or the replay measures another run
    skips = [l.split("stage=dry-skip ", 1)[1][:120] for l in progress.splitlines() if "stage=dry-skip" in l]
    check(f"{run.name}: the rows the plan now deals otherwise are few (at most 5 %)",
          len(skips) <= max(2, len(rows) // 20), f"{len(skips)} of {len(rows)}" + ("; " + "; ".join(skips[:4])
                                                                                 if skips else ""))
    words = [dict(re.findall(r"(\w+)=(\S+)", l)) for l in progress.splitlines() if "stage=plan-value" in l]
    reached = re.search(r"divergence (\d+) of target", (run / "ledger.txt").read_text(encoding="utf-8"))
    first = int(words[0]["can"]) if words and "can" in words[0] else None
    if not full:
        check(f"{run.name}: the plan's first word is within 5 points of what the run reached",
              reached is not None and first is not None and abs(first - int(reached.group(1))) <= 50,
              f"said {first / 10 if first is not None else '-'}%, reached "
              f"{int(reached.group(1)) / 10 if reached else '-'}%")
        if not a.keep:
            shutil.rmtree(job, ignore_errors=True)
        return
    costly = [d for d in rows if d["was"] in COSTLY]
    known = [d for d in costly if d["proof"] not in ("passed", "-") or d["repeat"] == "1" or d["family"] == "reliquid"]
    proof = [d for d in costly if d["proof"] not in ("passed", "-")]
    check("of the costly builds at least 90 % are known before a build", len(known) >= 0.9 * len(costly),
          f"{len(known)} of {len(costly)} (the proof {len(proof)}, the rest refused before or liquids)")
    accepted = [d for d in rows if d["was"] == "ACCEPTED"]
    wrong = [d for d in accepted if d["proof"] not in ("passed", "-")]
    check("no accepted edit is refused by the proof", not wrong, f"{len(wrong)} of {len(accepted)}"
          + (": " + "; ".join(f"{d['edit']} {d['family']} {d['why']}" for d in wrong[:3]) if wrong else ""))
    ended = next((int(w["round"]) for w in words if int(w["round"]) > 0 and w.get("worthy") == "0"), None)
    check("the plan says its word at every round", len(words) >= 1 and all("can" in w for w in words),
          ", ".join(f"round {w['round']}: up to {int(w['can']) / 10:.0f}% with {w['builds']}" for w in words[:4]))
    check("the plan's first word is within 5 points of what the run reached",
          reached is not None and first is not None and abs(first - int(reached.group(1))) <= 50,
          f"said {first / 10 if first is not None else '-'}%, reached "
          f"{int(reached.group(1)) / 10 if reached else '-'}%")
    dealt = 1 + max((int(w["round"]) for w in words), default=0)
    check("the edits end at the first deal with nothing new worth building, before the run's own last round",
          ended is not None and ended < dealt and all(w.get("worthy", "0") != "0" for w in words
                                                       if 0 < int(w["round"]) < ended),
          f"round {ended} of the {dealt} the run dealt")
    if not a.keep:
        shutil.rmtree(job, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
