r"""The donors the PO ordered besides q2dm1 - cor and q3t2, Quake III layouts made for Quake II - are taken, and q2dm1
is untouched by what it took (ledger row 400, Fable's brief 4 G5-1..G5-6).

    python tools/check_mapgen_donors.py [--work DIR] [--only NAME[,NAME]]

Every case builds the generator (or its oracle, or its walk) from this tree, asks its question of the PO's own
files, and then asks it again of a sandbox copy with the one rule the case is about taken out - the RED:

  q2dm1      the baseline rebuilt from q2dm1 is byte-for-byte the one the engine built before row 400 (sha256 of
             the .bsp and the .map recorded on 2026-10-03 from mg_20u's own job)
  faithful   cor's first step: the plain rebuild is refused for what it draws, the faithful one accepted with its
             residue said, and the plan dealt (RED: the retry taken out - ERR_BASELINE)
  bare       cor's rebuilt copy draws no clip texture (RED: the bare sides undressed - it draws clip again)
  mist       cor's rebuilt copy agrees on space (RED: the rule for bits riding along with rock taken out - the space
             axis fails)
  sealing    q3t2's rebuilt copy misses no more than 13 drawn planes (RED: faces facing the other compiler's sealing
             compared again - 19 or more)
  hurts      the walk counts cor's kill volumes as lethal ground (RED: the volumes not read - none lethal)
  held       a candidate of cor is accepted: held to the donor's own walk (RED: held to the absolutes - none is)
  slab       mg_20u's own job replayed: it differs only at dig 82, by the slab pulled back to the old wall (G5-7, row
             402; RED: the dig's boxes not kept out of the old air - the replay passes dig 82 unchanged)

Row 404 - what mg_cor's first delivery failed on (MGCOR_JOB, the job the Studio ran at 15:22 on 2026-10-03):
  pickups    its two lost pickups are cor's own and named so (RED: judged against q2dm1, which does not lose them -
             it fails)
  reach      its walk passes held to cor's own, the teleporters (12 of cor's 16 lead somewhere) and pads (4) crossed
             named (RED: no donor named - it fails)
  light      cor's rebuilt copy lights with the light stage's own flags, over 2 MB of light (RED: `-maxdata` taken
             out of the stage - the light tool refuses it)
  axes       cor's rebuilt copy wears its textures on every drawn face (RED: `respan_sides` taken out - one under 0.5)
  heldgates  mg_q3t2's water and static checks pass held to q3t2 - its killsky warp faces and func_wall panes are the
             donor's own, named (row 405, brief 5 W7; RED: judged against cor - both fail)
  window     mg_cor's job replayed (sides re-spanned off in both trees, so the baseline is its own): it differs at
             attempt 84 by the 0.8-unit remainder of x 1048..1049.6 taken out of the window's run (RED: remainders
             kept - attempt 84 replays unchanged)
  annexair   mg_cor's second delivery (MGCOR2_JOB): its annex built in air is read from the plan («, built in air»)
             and judged as a building - air inside, a roof where the donor had air, a back wall - holding a pickup
             worth the walk (row 405, brief 5 W2; RED: judged as a dug hall, new air where the donor had rock - NOT
             BUILT)
  span       a bridge across a pit (fixture `span_pit`, the test seam asking one, row 405, brief 5 W5): one span dealt,
             the walk between its ends at least twice its length or no walk at all; the transaction ACCEPTS it and its
             deck is solid with air over it (RED: the span's deal taken out - none); and cor's own plan deals one
  traps      no trap of the map's own (row 409): cor held to itself shows none and passes; mg_cor of row 408 - its pool
             reached through a shot pane and left by nothing - fails the reach gate by place (RED: the old rule, by count,
             holds it to the donor and passes)
  roomlight  q3t2's first annex built by the transaction and lit as the finished map is (`mapgen_dig_light_lab.py`): its
             new faces read like this map's light round its door - level 0.8..1.25, tint within 0.15, unevenness, its
             ceiling not over its floor (row 408, Fable's brief 6; RED: the old white lamps - it fails on tint)
  light4     the light gate (row 405, brief 5 L4): q3t2 against itself passes; mg_q3t2's first delivery, its new
             rooms lit 3 to 10 against the donor's 44, fails naming them DARK
  storey1    q3t2's plan (MGQ3T2_JOB's baseline, this tree's driver): no pair of sites qualifies at any size, and a
             storey with one door is dealt - its room, terrace, flight and pickup (row 405, brief 5 W6c; dug alone by
             the transaction it was built: hall, terrace and tread solid, the combat armour on the terrace) (RED: the
             one-door storey taken out - none dealt)
  digwalls   mg_q3t2's dig walls judged against the job's rebuilt baseline pass (row 405, brief 5 W4.1: its four
             «open high» points lie on the corner edge of a pier, rock in q3t2.bsp and air in the rebuilt copy before
             any dig; no carve reaches them) (RED: judged against q3t2.bsp - FAIL at -184 1720)
  courses    a wall of three 64-high courses between two rooms (fixture `courses_wall`, brief 5 W3): glazed, every
             pane's foot 96 over the floor beside it and its jambs clear of the side walls, and the window family's
             attempt accepted (RED: the sill a third of the slab - a foot at 64; RED: the jambs not asked - an
             opening flush on the side wall at -320)

Heavy launches go through the load guard. Exit 1 on any failure.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import mapgen_load_guard as load_guard  # noqa: E402
from check_mapgen_pipeline import SOURCES as PIPELINE_SOURCES  # noqa: E402
from check_mapgen_reach_gate import SOURCES as REACH_SOURCES  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\donors\guard")
MAPS = Path(r"O:\Claude2\q2pro-release\baseq2\maps")
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
Q2DM1 = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
Q2DM1_BASELINE_BSP = "6a553ec3a216d863c643040f62cdd477be5b75220f659ece772abc6e0a2e8d18"
Q2DM1_BASELINE_MAP = "ca24e44e63fc0f86ec6831344a3f9d8e7a55a1044bc64fbee74aae58aab8c4e3"
MG20U_JOBS = Path(r"O:\Claude2\MapgenStudio\temp")
MGCOR_JOB = MG20U_JOBS / "mg_cor_20261003_152239"
MGQ3T2_JOB = MG20U_JOBS / "mg_q3t2_20261003_193336"
MGCOR2_JOB = MG20U_JOBS / "mg_cor_20261003_223340"       # row 405: the generation with W1 and W2
MGCOR3_JOB = MG20U_JOBS / "mg_cor_20261004_141621"       # row 408: the one with the pool the PO could not leave
EQUIV_SOURCES = ["tools/mapgen_equivalence_driver.c", "src/mapgen/mapgen_equivalence.c", "src/mapgen/mapgen_bsp.c",
                 "src/mapgen/mapgen_movers.c", "src/mapgen/mapgen_trace.c"]

CASES = FAILED = 0
STALE: list[str] = []


def no_lights(text: str) -> str:
    """Row 410: a .map without its point-light entities - the replays of jobs older than row 408 (its room lights)
    differ there and nowhere else (the pipeline's --replay-any-lights)."""
    return re.sub(r'\{\n[^{}]*\}\n', lambda m: "" if '"classname" "light"\n' in m.group(0) else m.group(0), text)


def stale(prog: str, target: int, name: str) -> bool:
    """Row 410: a replay of a job the generator has since changed before its target attempt is no evidence either
    way - neither the green case nor its RED (which then «passes» for the wrong reason). Said as STALE, listed at the
    end, not counted: measured 05.10, mg_20u's job diverges at attempt 80 by a lamp housing's brushes (brief 5 L1,
    brief 6), mg_cor's at attempt 3 by a window's run (brief 5 W3). The rule needs a job of today's generator."""
    m = re.search(r'stage=resume-diverged why="attempt (\d+):', prog)
    if not m or int(m.group(1)) >= target:
        return False
    said = f"{name}: the job diverges at attempt {m.group(1)}, before attempt {target} - made by an older generator"
    print(f"  STALE {said}", flush=True)
    STALE.append(said)
    return True


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def tree(work: Path, name: str, mutation) -> Path | None:
    """This tree, or a copy of its sources with lines taken out: one (file, the text, what replaces it) or a list."""
    if mutation is None:
        return REPO
    root = work / name
    if root.exists():
        shutil.rmtree(root)
    for part in ("src", "inc", "tools"):
        shutil.copytree(REPO / part, root / part,
                        ignore=shutil.ignore_patterns("__pycache__", "mapgen_studio", "*.exe", "*.o"))
    for rel, old, new in ([mutation] if isinstance(mutation, tuple) else mutation):
        target = root / rel
        text = target.read_bytes().decode("utf-8")
        hit = old if old in text else old.replace("\n", "\r\n")
        if not check(f"RED {name}: the line is where the mutation says ({rel})", text.count(hit) == 1,
                     f"{text.count(hit)} occurrences"):
            return None
        target.write_bytes(text.replace(hit, new, 1).encode("utf-8"))
    return root


def gcc(root: Path, sources: list[str], exe: Path, extra: list[str] = ()) -> bool:
    exe.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(["gcc", "-std=c17", "-O2", "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
                          "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                         + [str(root / s) for s in sources] + ["-o", str(exe), *extra, "-lm", "-lz"],
                         capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stderr[-1500:])
    return run.returncode == 0


def pipeline(exe: Path, donor: Path, job: Path, attempts: str, *extra: str) -> str:
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    compiler, _ = pinned_compiler(quiet=True)
    load_guard.run([str(exe), str(compiler), str(donor), str(job), "q2mg", "20", "42", "--max-attempts", attempts,
                    "--moddir", str(GAME), *extra], capture_output=True, text=True, timeout=7200)
    p = job / "progress.txt"
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def clip_faces(bsp: Path) -> int:
    d = bsp.read_bytes()
    lumps = [struct.unpack_from("<ii", d, 8 + 8 * i) for i in range(19)]
    o, n = lumps[5]
    clip = {i for i in range(n // 76) if b"clip" in d[o + i * 76 + 40:o + i * 76 + 72].split(b"\0")[0].lower()}
    o, n = lumps[6]
    return sum(1 for i in range(n // 20) if struct.unpack_from("<h", d, o + i * 20 + 10)[0] in clip)


def equiv(exe: Path, donor: Path, baseline: Path) -> str:
    return load_guard.run([str(exe), str(donor), str(baseline)], capture_output=True, text=True, timeout=3600).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = set(filter(None, a.only.split(",")))
    want = (lambda n: not only or n in only)
    a.work.mkdir(parents=True, exist_ok=True)
    cor, q3t2 = MAPS / "cor.bsp", MAPS / "q3t2.bsp"
    green = a.work / "green" / "pipeline.exe"
    if not check("the generator builds from this tree", gcc(REPO, PIPELINE_SOURCES, green)):
        return 1

    if want("q2dm1"):
        print("\n=== q2dm1 is untouched")
        job = a.work / "q2dm1_job"
        pipeline(green, Q2DM1, job, "1")
        check("q2dm1's rebuilt baseline is byte-for-byte the one built before row 400",
              sha(job / "baseline" / "q2mg.bsp") == Q2DM1_BASELINE_BSP
              and sha(job / "baseline" / "q2mg.map") == Q2DM1_BASELINE_MAP,
              f"bsp {sha(job / 'baseline' / 'q2mg.bsp')[:16]}, map {sha(job / 'baseline' / 'q2mg.map')[:16]}")

    def red_pipeline(name, mutation, donor, attempts, *extra):
        root = tree(a.work, name, mutation)
        if root is None:
            return None, None
        exe = a.work / name / "bin" / "pipeline.exe"
        if not check(f"RED {name}: the mutated generator builds", gcc(root, PIPELINE_SOURCES, exe)):
            return None, None
        job = a.work / f"{name}_job"
        return pipeline(exe, donor, job, attempts, *extra), job

    if want("faithful") or want("bare") or want("mist"):
        print("\n=== cor's first step")
        job = a.work / "cor_job"
        prog = pipeline(green, cor, job, "1")
        check("cor's plain rebuild refused for what it draws, the faithful one accepted with its residue said",
              "stage=baseline-faithful" in prog and "stage=plan" in prog,
              next((ln for ln in prog.splitlines() if "faithful" in ln or "finish" in ln), "")[:200])
        if want("bare"):
            check("cor's rebuilt copy draws no clip texture", clip_faces(job / "baseline" / "q2mg.bsp") == 0,
                  f"{clip_faces(job / 'baseline' / 'q2mg.bsp')} clip faces")
        if want("mist"):
            eq = a.work / "green" / "equiv.exe"
            if gcc(REPO, EQUIV_SOURCES, eq):
                out = equiv(eq, cor, job / "baseline" / "q2mg.bsp")
                check("cor's rebuilt copy agrees on space", "axis DIFF_SPACE         ok" in out,
                      next((ln for ln in out.splitlines() if "DIFF_SPACE" in ln), ""))
        if want("faithful"):
            prog, _ = red_pipeline("red_faithful", ("src/mapgen/mapgen_transaction.c",
                                                    "        const uint32_t failed = txn->equivalence.failed_axes;",
                                                    "        const uint32_t failed = 0;"), cor, "1")
            if prog is not None:
                check("RED: with the faithful retry taken out cor is refused at its first step",
                      "result=ERR_BASELINE" in prog and "stage=plan" not in prog,
                      next((ln for ln in prog.splitlines() if "finish" in ln), "")[:160])
        if want("bare"):
            prog, rjob = red_pipeline("red_bare", ("src/mapgen/mapgen_geometry.c", "    dress_untextured(g, bsp);\n", ""),
                                      cor, "1")
            if prog is not None:
                n = clip_faces(rjob / "baseline" / "q2mg.bsp")
                check("RED: with the bare sides undressed cor's copy draws clip again", n > 0, f"{n} clip faces")
        if want("mist"):
            root = tree(a.work, "red_mist", ("src/mapgen/mapgen_equivalence.c",
                                             "    if ((cd & BIT_SOLID) && (cb & BIT_SOLID)) {",
                                             "    if (0) {"))
            exe = a.work / "red_mist" / "equiv.exe"
            if root is not None and check("RED mist: the mutated oracle builds", gcc(root, EQUIV_SOURCES, exe)):
                out = equiv(exe, cor, job / "baseline" / "q2mg.bsp")
                check("RED: with the riders compared again cor's space axis fails",
                      "axis DIFF_SPACE         FAILED" in out,
                      next((ln for ln in out.splitlines() if "DIFF_SPACE" in ln), ""))

    if want("sealing"):
        print("\n=== q3t2's sealed niches")
        job = a.work / "q3t2_job"
        prog = pipeline(green, q3t2, job, "1")
        eq = a.work / "green" / "equiv.exe"
        if check("q3t2's first step passes", "stage=plan" in prog) and gcc(REPO, EQUIV_SOURCES, eq):
            m = re.search(r"^planes \d+ \d+ missing (\d+)", equiv(eq, q3t2, job / "baseline" / "q2mg.bsp"), re.M)
            missing = int(m.group(1)) if m else -1
            check("q3t2's rebuilt copy misses no more than 13 drawn planes", 0 <= missing <= 13, f"{missing}")
            root = tree(a.work, "red_seal", ("src/mapgen/mapgen_equivalence.c", "    if (!other)\n        return;\n",
                                             "    return;\n"))
            exe = a.work / "red_seal" / "equiv.exe"
            if root is not None and check("RED sealing: the mutated oracle builds", gcc(root, EQUIV_SOURCES, exe)):
                m = re.search(r"^planes \d+ \d+ missing (\d+)", equiv(exe, q3t2, job / "baseline" / "q2mg.bsp"), re.M)
                red_missing = int(m.group(1)) if m else -1
                check("RED: with faces facing the other compiler's sealing compared again, 19 or more are missing",
                      red_missing >= 19, f"{red_missing}")

    if want("hurts"):
        print("\n=== cor's kill volumes")
        gate = a.work / "green" / "reach_gate.exe"
        if gcc(REPO, REACH_SOURCES, gate, ["-I" + str(REPO / "inc")]):
            out = load_guard.run([str(gate), str(cor), "--connectivity-only"], capture_output=True, text=True,
                                 timeout=3600).stdout
            m = re.search(r"one-way \d+ \((\d+) lethal\)", out)
            lethal = int(m.group(1)) if m else -1
            check("the walk counts cor's kill volumes as lethal ground", lethal > 1000, f"{lethal} lethal")
            root = tree(a.work, "red_hurts", ("src/mapgen/mapgen_movers.c",
                                              '    if (!strcmp(classname, "trigger_hurt")) {',
                                              '    if (0) {'))
            exe = a.work / "red_hurts" / "reach_gate.exe"
            if root is not None and check("RED hurts: the mutated walk builds", gcc(root, REACH_SOURCES, exe)):
                out = load_guard.run([str(exe), str(cor), "--connectivity-only"], capture_output=True, text=True,
                                     timeout=3600).stdout
                m = re.search(r"one-way \d+ \((\d+) lethal\)", out)
                red = int(m.group(1)) if m else -1
                check("RED: with the kill volumes not read, none of cor's places is lethal", 0 <= red < 100,
                      f"{red} lethal")

    if want("held"):
        print("\n=== cor's candidates held to the donor")
        prog = pipeline(green, cor, a.work / "cor_held_job", "1")
        accepted = re.findall(r"verdict=ACCEPTED", prog)
        check("a candidate of cor is accepted, held to the donor's own walk", len(accepted) > 0,
              f"{len(accepted)} accepted")
        prog, _ = red_pipeline("red_held", ("src/mapgen/mapgen_reach.c",
                                            "    if (!report || !donor || report->spawns == 0 || MapGenReach_Passed(donor))",
                                            "    if (1)"), cor, "1")
        if prog is not None:
            check("RED: held to the absolutes, no candidate of cor is accepted",
                  "verdict=ACCEPTED" not in prog, f"{len(re.findall(r'verdict=ACCEPTED', prog))} accepted")

    if want("slab"):
        print("\n=== mg_20u's slab (G5-7)")
        source = next(iter(sorted(MG20U_JOBS.glob("mg_20u_*/job"))), None)
        if check("mg_20u's own job is there to replay", source is not None and (source / "ledger.txt").is_file(),
                 str(MG20U_JOBS)):
            def replay(exe: Path, name: str) -> tuple[str, Path]:
                job = a.work / name
                if job.exists():
                    shutil.rmtree(job)
                shutil.copytree(source, job)
                (job / "progress.txt").unlink(missing_ok=True)
                compiler, _ = pinned_compiler(quiet=True)
                load_guard.run([str(exe), str(compiler), str(Q2DM1), str(job), "q2mg", "20", "1020", "--final",
                                "--moddir", str(GAME), "--hold-to-donor", "--resume",
                                "--replay-any-lights"],
                               capture_output=True, text=True, timeout=3600)
                prog = job / "progress.txt"
                return (prog.read_text(encoding="utf-8", errors="replace") if prog.is_file() else ""), job

            prog, job = replay(green, "slab_job")
            slab_stale = stale(prog, 219, "mg_20u's slab replay (row 402)")
            diff = ""
            rep = job / "try_0219" / "q2mg.replay.map"
            if rep.is_file():
                old_lines = no_lights((job / "try_0219" / "q2mg.map").read_text(encoding="latin1")).splitlines()
                new_lines = no_lights(rep.read_text(encoding="latin1")).splitlines()
                diff = "; ".join(f"{x.split(' e2u3')[0]} -> {y.split(' e2u3')[0]}"
                                 for x, y in zip(old_lines, new_lines) if x != y)
            slab_stale or check("replayed, mg_20u's run keeps every edit before dig 82 and differs at dig 82 only by the slab's face "
                  "pulled back from y 800 to the old wall at 768",
                  "attempt 219:" in prog and "( 512 800 0 )" in diff and "( 512 768 0 )" in diff and diff.count("->") == 1,
                  diff[:200] or next((ln for ln in prog.splitlines() if "diverged" in ln), "")[:200])
            root = tree(a.work, "red_slab", ("src/mapgen/mapgen_geometry_edit.c",
                                             "static const bool g_dig_keep_out_of_old_air = true;",
                                             "static const bool g_dig_keep_out_of_old_air = false;"))
            exe = a.work / "red_slab" / "bin" / "pipeline.exe"
            if not slab_stale and root is not None and check("RED slab: the mutated generator builds",
                                                             gcc(root, PIPELINE_SOURCES, exe)):
                prog, _ = replay(exe, "red_slab_job")
                check("RED: with the dig's boxes not kept out of the old air, the replay passes dig 82 unchanged",
                      "attempt 219:" not in prog,
                      next((ln for ln in prog.splitlines() if "diverged" in ln), "no divergence")[:200])

    # ---- row 404 -----------------------------------------------------------------------------------------------
    candidate = MGCOR_JOB / "candidate.bsp"
    if (want("pickups") or want("reach")) and not check("mg_cor's first delivery is there", candidate.is_file(),
                                                        str(candidate)):
        return 1

    if want("pickups"):
        print("\n=== mg_cor's lost pickups are cor's own")
        def pickups(donor: Path) -> str:
            out = load_guard.run([sys.executable, str(REPO / "tools" / "mapgen_delivery_gates.py"), str(candidate),
                                  "--job", str(MGCOR_JOB / "job"), "--donor", str(donor),
                                  "--work", str(a.work / "pickups"), "--only", "pickups"],
                                 capture_output=True, text=True, timeout=1800).stdout
            return next((ln.strip() for ln in out.splitlines() if "lost at spawn" in ln), "")
        line = pickups(cor)
        check("held to cor, the pickups check passes and names the two cor loses itself",
              line.startswith("PASS") and "the donor's own" in line and "ammo_grenades" in line, line[:220])
        line = pickups(Q2DM1)
        check("RED: judged against q2dm1, which loses neither, it fails", line.startswith("FAIL"), line[:220])

    if want("reach"):
        print("\n=== mg_cor's walk held to cor's")
        gate = a.work / "green" / "reach_gate.exe"
        if check("the reach gate builds from this tree", gcc(REPO, REACH_SOURCES, gate)):
            out = load_guard.run([str(gate), str(candidate), "40000", "--donor", str(cor)], capture_output=True,
                                 text=True, timeout=7200)
            said = out.stdout
            check("held to cor's own walk mg_cor passes, saying so",
                  out.returncode == 0 and "HELD TO THE DONOR" in said and "  PASS" in said,
                  next((ln.strip() for ln in said.splitlines() if "HELD" in ln or "FAIL" in ln), "")[:220])
            tele = next((ln.strip() for ln in said.splitlines() if "teleporter" in ln), "")
            m = re.search(r"(\d+) teleporters?, (\d+) crossed; (\d+) jump pads?, (\d+) crossed", tele)
            check("the line names cor's twelve teleporters that lead somewhere (of 16) and four pads, and how many a "
                  "player crosses", bool(m) and m.group(1) == "12" and m.group(3) == "4", tele)
            out = load_guard.run([str(gate), str(candidate), "40000"], capture_output=True, text=True, timeout=7200)
            check("RED: with no donor named it fails on cor's own stranded start", out.returncode != 0
                  and "FAIL" in out.stdout,
                  next((ln.strip() for ln in out.stdout.splitlines() if "FAIL" in ln), "")[:160])

    if want("light") or want("axes"):
        print("\n=== cor's rebuilt copy, lit and textured")
        job = a.work / "cor_job"
        if not (job / "baseline" / "q2mg.bsp").is_file():
            pipeline(green, cor, job, "1")
        base = job / "baseline"
        if want("axes"):
            def axes(bsp: Path) -> str:
                return load_guard.run([sys.executable, str(REPO / "tools" / "check_mapgen_texture_axes.py"), "--map",
                                       str(bsp), "--work", str(a.work / "axes")], capture_output=True, text=True,
                                      timeout=1800).stdout
            out = axes(base / "q2mg.bsp")
            check("cor's rebuilt copy wears its textures on every drawn face", "0 failures" in out,
                  next((ln.strip() for ln in out.splitlines() if "FAIL" in ln), "")[:200])
            prog, rjob = red_pipeline("red_axes", ("src/mapgen/mapgen_geometry.c", "    respan_sides(g, bsp);\n", ""),
                                      cor, "1")
            if prog is not None:
                out = axes(rjob / "baseline" / "q2mg.bsp")
                check("RED: with the sides not re-spanned a drawn face of cor's copy is smeared", "1 failures" in out,
                      next((ln.strip() for ln in out.splitlines() if "FAIL" in ln), "")[:200])
        if want("light"):
            src = (REPO / "tools" / "mapgen_pipeline_driver.c").read_text(encoding="utf-8")
            m = re.search(r'case MAPCOMPILE_STAGE_RAD:\s+return "([^"]+)";', src)
            flags = m.group(1).split() if m else []
            compiler, _ = pinned_compiler(quiet=True)
            def light(name: str, stage: list[str]) -> tuple[int, str, int]:
                d = a.work / name
                if d.exists():
                    shutil.rmtree(d)
                d.mkdir(parents=True)
                for ext in (".bsp", ".map", ".prt"):
                    shutil.copyfile(base / f"q2mg{ext}", d / f"q2mg{ext}")
                r = load_guard.run([str(compiler), *stage, "-threads", "8", "-moddir", str(GAME), "-basedir",
                                    str(GAME), "-gamedir", str(GAME), str(d / "q2mg.map")], capture_output=True,
                                   text=True, timeout=3600)
                raw = (d / "q2mg.bsp").read_bytes()
                return r.returncode, r.stdout, struct.unpack_from("<ii", raw, 8 + 8 * 7)[1]
            rc, out, lit = light("light", flags)
            check(f"cor's copy lights with the stage's own flags ({' '.join(flags)}), over 2 MB of light",
                  rc == 0 and lit > 2097152, f"exit {rc}, lighting {lit} bytes")
            plain = [f for i, f in enumerate(flags) if f != "-maxdata" and (i == 0 or flags[i - 1] != "-maxdata")]
            rc, out, lit = light("red_light", plain)
            check("RED: without -maxdata the light tool refuses cor's copy", lit == 0 and "maxdata" in out,
                  next((ln.strip() for ln in out.splitlines() if "maxdata" in ln), f"exit {rc}, lighting {lit}"))

    if want("heldgates"):
        print("\n=== mg_q3t2's water and static held to q3t2")
        cand = MGQ3T2_JOB / "candidate.bsp"
        if check("mg_q3t2's first delivery is there", cand.is_file(), str(cand)):
            def held(donor: Path) -> list[str]:
                out = load_guard.run([sys.executable, str(REPO / "tools" / "mapgen_delivery_gates.py"), str(cand),
                                      "--job", str(MGQ3T2_JOB / "job"), "--donor", str(donor),
                                      "--work", str(a.work / "heldgates"), "--only", "water,static"],
                                     capture_output=True, text=True, timeout=1800).stdout
                return [ln.strip() for ln in out.splitlines() if ln.strip().startswith(("PASS", "FAIL"))]
            lines = held(q3t2)
            check("held to q3t2, water and static pass and name the donor's own",
                  len(lines) == 2 and all(ln.startswith("PASS") and "the donor's own" in ln for ln in lines),
                  " | ".join(x[:110] for x in lines))
            lines = held(cor)
            check("RED: judged against cor, which has neither, both fail",
                  len(lines) == 2 and all(ln.startswith("FAIL") for ln in lines), " | ".join(x[:110] for x in lines))

    if want("window"):
        print("\n=== mg_cor's window at attempt 84")
        source = MGCOR_JOB / "job"
        if check("mg_cor's own job is there to replay", (source / "ledger.txt").is_file(), str(source)):
            def replay_cor(exe: Path, name: str) -> tuple[str, Path]:
                job = a.work / name
                if job.exists():
                    shutil.rmtree(job)
                shutil.copytree(source, job, ignore=shutil.ignore_patterns("lit"))
                (job / "progress.txt").unlink(missing_ok=True)
                compiler, _ = pinned_compiler(quiet=True)
                load_guard.run([str(exe), str(compiler), str(cor), str(job), "q2mg", "20", "42", "--final",
                                "--moddir", str(GAME), "--hold-to-donor", "--resume",
                                "--replay-any-lights"],
                               capture_output=True, text=True, timeout=7200)
                prog = job / "progress.txt"
                return (prog.read_text(encoding="utf-8", errors="replace") if prog.is_file() else ""), job

            no_respan = ("src/mapgen/mapgen_geometry.c", "    respan_sides(g, bsp);\n", "")
            window_stale = False
            root = tree(a.work, "window_green", [no_respan])
            exe = a.work / "window_green" / "bin" / "pipeline.exe"
            if root is not None and check("the generator without re-spanning builds", gcc(root, PIPELINE_SOURCES, exe)):
                prog, job = replay_cor(exe, "window_job")
                window_stale = stale(prog, 84, "mg_cor's window replay (row 404)")
                rep = job / "try_0084" / "q2mg.replay.map"
                gone = rep.is_file() and "1049.6" in (job / "try_0084" / "q2mg.map").read_text(encoding="latin1") \
                    and "1049.6" not in rep.read_text(encoding="latin1")
                window_stale or check("replayed, mg_cor's run keeps every edit before attempt 84 and differs there by the window's "
                      "run taking the 0.8 left of the brush at x 1048..1049.6",
                      "attempt 84:" in prog and gone,
                      next((ln for ln in prog.splitlines() if "diverged" in ln), "no divergence")[:200])
            root = tree(a.work, "window_red", [no_respan, (
                "src/mapgen/mapgen_geometry_edit.c",
                "        if (thin_cut[2] < thin_cut[3] && thin_cut[3] - thin_cut[2] < 4.0f)\n",
                "        if (0)\n")])
            exe = a.work / "window_red" / "bin" / "pipeline.exe"
            if not window_stale and root is not None and check(
                    "RED window: the mutated generator builds", gcc(root, PIPELINE_SOURCES, exe)):
                prog, _ = replay_cor(exe, "window_red_job")
                check("RED: with the remainder kept the replay passes attempt 84 unchanged", "attempt 84:" not in prog,
                      next((ln for ln in prog.splitlines() if "diverged" in ln), "no divergence")[:200])

    if want("annexair"):
        print("\n=== mg_cor's annex built in air")
        cand = MGCOR2_JOB / "candidate.bsp"
        if check("mg_cor's second delivery is there", cand.is_file(), str(cand)):
            def annex(root: Path, name: str) -> str:
                code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                        "import mapgen_delivery_gates as g; "
                        "ok, said = g.ask_annex(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), "
                        "Path(sys.argv[5])); print(said)")
                w = a.work / name
                w.mkdir(parents=True, exist_ok=True)
                return load_guard.run([sys.executable, "-c", code, str(root / "tools"), str(cand),
                                       str(MGCOR2_JOB / "job"), str(cor), str(w)], capture_output=True, text=True,
                                      timeout=1800).stdout.strip()
            said = annex(REPO, "annexair")
            check("its plan's annex line is read, the annex is built - air inside, a roof, a back wall - and holds "
                  "a pickup worth the walk", "1 on accepted digs, 1 built, 1 worth the walk" in said
                  and "built in air:" in said, said[:240])
            root = tree(a.work, "annexair_red", ("tools/mapgen_delivery_gates.py",
                                                 "        air, how = (building_built(cand, don, a[\"room\"], a[\"ends\"][:3])"
                                                 " if a.get(\"air\")\n",
                                                 "        air, how = (building_built(cand, don, a[\"room\"], a[\"ends\"][:3])"
                                                 " if False\n"))
            if root is not None:
                said = annex(root, "annexair_red")
                check("RED: asked as a dug hall - new air where the donor had rock - the building is NOT BUILT",
                      "NOT BUILT" in said, said[:240])

    if want("span"):
        print("\n=== spans: a bridge across a pit, and cor's")
        from mapgen_geometry_fixtures import FIXTURES
        from check_mapgen_recut import build_driver, compile_map
        fx = a.work / "span"
        fx.mkdir(parents=True, exist_ok=True)
        FIXTURES["span_pit"](fx / "span_pit.map")
        compile_map(fx / "span_pit.map")
        bsp = fx / "span_pit.bsp"
        dealt = re.compile(r"^  span: .* deck (-?\d+) (-?\d+) (-?\d+) \.\. (-?\d+) (-?\d+) (-?\d+), the walk (-?\d+) before,"
                           r" (\d+) across", re.M)

        def spans(root: Path, name: str) -> list:
            out = fx / name
            out.mkdir(parents=True, exist_ok=True)
            exe = build_driver(root, out)
            text = load_guard.run([str(exe), str(bsp), "--seed", "42", "--ambition", "80", "--list", "--spans", "1"],
                                  capture_output=True, text=True, timeout=600).stdout
            return [[int(v) for v in m.groups()] for m in dealt.finditer(text)]

        if check("the fixture compiles", bsp.is_file(), str(bsp)):
            got = spans(REPO, "green")
            check("one span dealt across the pit, the walk between its ends at least twice its length (or none)",
                  len(got) == 1 and (got[0][6] < 0 or got[0][6] >= 2 * got[0][7]), f"{got}")
            txn = fx / "txn.exe"
            src = [s if s != "tools/mapgen_pipeline_driver.c" else "tools/mapgen_transaction_driver.c"
                   for s in PIPELINE_SOURCES]
            if got and check("the transaction driver builds", gcc(REPO, src, txn)):
                job = fx / "txn_job"
                if job.exists():
                    shutil.rmtree(job)
                job.mkdir()
                compiler, _ = pinned_compiler(quiet=True)
                out = load_guard.run([str(txn), str(compiler), str(bsp), str(job), "q2mg", str(GAME), "42", "1",
                                      "--only", "span", "--spans", "1", "--ambition", "80"], capture_output=True,
                                     text=True, timeout=1800).stdout
                tries = sorted(job.glob("try_*/q2mg.bsp"))
                built = ""
                if tries:
                    from check_mapgen_static import Bsp
                    b, d = Bsp(tries[0]), got[0]
                    mx, my = (d[0] + d[3]) / 2.0, (d[1] + d[4]) / 2.0
                    built = (f"deck {'solid' if b.solid((mx, my, d[5] - 8.0)) else 'NOT SOLID'},"
                             f" {'air' if not b.solid((mx, my, d[5] + 40.0)) else 'NO AIR'} over it")
                check("the span's attempt is ACCEPTED and built - its deck solid, air over it",
                      "ledger: ACCEPTED=1" in out and built == "deck solid, air over it", built or "no try")
            root = tree(a.work, "span_red", ("src/mapgen/mapgen_geometry_edit.c",
                                             "    deal_spans(plan, donor, ground, &walk, &dig_stream, ceiling);\n",
                                             ""))
            if root is not None:
                got = spans(root, "span_red")
                check("RED: without the span's deal the pit has none", not got, f"{got}")
        # the product: cor, an arena, deals one; its plan as the pipeline dealt it, by this tree's driver
        code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                "import mapgen_delivery_gates as g; "
                "text, err = g.plan_listing(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])); "
                "print(err or ''); print(text)")
        w = a.work / "span_cor"
        w.mkdir(parents=True, exist_ok=True)
        text = load_guard.run([sys.executable, "-c", code, str(REPO / "tools"), str(MGCOR2_JOB / "job"), str(w),
                               str(REPO)], capture_output=True, text=True, timeout=1800).stdout
        got = [m.group(0).strip() for m in dealt.finditer(text)]
        check("cor's plan deals a span across its arena", len(got) >= 1, "; ".join(x[:150] for x in got[:2])
              or next((ln.strip() for ln in text.splitlines() if "spans refused" in ln), "no tally"))

    if want("traps"):
        print("\n=== no trap of the map's own (row 409)")
        from check_mapgen_reach_gate import SOURCES as GATE_SOURCES

        def gate(root: Path, name: str, bsp: Path, donor: Path) -> tuple[int, str]:
            exe = a.work / name / "reach_gate.exe"
            if not gcc(root, GATE_SOURCES, exe):
                return -1, "does not build"
            r = load_guard.run([str(exe), str(bsp), "--donor", str(donor)], capture_output=True, text=True,
                               timeout=3600)
            return r.returncode, " | ".join(ln.strip() for ln in r.stdout.splitlines()
                                            if "trap" in ln or "DONOR" in ln or "fails too" in ln)[:300]

        rc, said = gate(REPO, "traps", cor, cor)
        check("cor held to itself has no trap of its own and passes", rc == 0 and "new traps: 0" in said, said)
        cand = MGCOR3_JOB / "candidate.bsp"
        if check("mg_cor of row 408 is there", cand.is_file(), str(cand)):
            rc, said = gate(REPO, "traps", cand, MGCOR3_JOB / "job" / "baseline" / "q2mg.bsp")
            check("it fails: its pool, reached through a shot pane and left by nothing, is a trap cor has none of",
                  rc != 0 and "new traps:" in said and "new traps: 0 " not in said, said)
            root = tree(a.work, "traps_red", ("inc/common/mapgen_reach.h",
                                              "#define MAPGEN_REACH_NEW_TRAP_SLACK  8u",
                                              "#define MAPGEN_REACH_NEW_TRAP_SLACK  100000u"))
            if root is not None:
                rc, said = gate(root, "traps_red", cand, MGCOR3_JOB / "job" / "baseline" / "q2mg.bsp")
                check("RED: by count alone (the old rule) it passes, held to the donor", rc == 0 and "HELD" in said,
                      said)

    if want("roomlight"):
        print("\n=== a new room lit like the place at its door (row 408, brief 6)")

        def lab(root: Path, name: str) -> list[str]:
            out = load_guard.run([sys.executable, str(REPO / "tools" / "mapgen_dig_light_lab.py"), str(q3t2),
                                  str(a.work / name), "--tree", str(root), "--attempts", "1"],
                                 capture_output=True, text=True, timeout=7200).stdout
            return [ln.strip() for ln in out.splitlines() if ln.strip().startswith(("PASS", "FAIL"))]

        lines = lab(REPO, "roomlight")
        check("q3t2's first annex, built and lit as the finished map is, reads like the light at its door - level,"
              " tint, unevenness, its ceiling not over its floor", len(lines) == 1 and lines[0].startswith("PASS"),
              " | ".join(x[:200] for x in lines))
        # row 408 (decision 5): its trim wears a texture q3t2 draws - q3t2 draws no e2u3/metal5_1, the old trim
        built = sorted((a.work / "roomlight" / "job").glob("try_*/q2mg.map"))
        trim = built[0].read_text(encoding="latin-1").count("e2u3/metal5_1") if built else -1
        check("its trim wears a texture of q3t2's own - no e2u3/metal5_1, which q3t2 does not draw", trim == 0,
              f"{trim} sides of it in the built map")
        root = tree(a.work, "roomlight_red", ("src/mapgen/mapgen_geometry_edit.c",
                                              "    const bool referenced = lit_donor && dig_light_reference(d, lit_donor,"
                                              " &ref);\n",
                                              "    const bool referenced = false;\n"))
        if root is not None:
            lines = lab(root, "roomlight_red")
            check("RED: lit by the old white lamps it fails on its tint", len(lines) == 1 and lines[0].startswith("FAIL")
                  and "tint" in lines[0], " | ".join(x[:200] for x in lines))

    if want("light4"):
        print("\n=== the light gate (L4)")
        def light(bsp: Path, job: Path | None, donor: Path) -> str:
            code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                    "import mapgen_delivery_gates as g; "
                    "job = Path(sys.argv[3]) if sys.argv[3] != '-' else None; "
                    "ok, said = g.ask_light(Path(sys.argv[2]), job, Path(sys.argv[4])); "
                    "print('PASS' if ok else 'FAIL', said)")
            return load_guard.run([sys.executable, "-c", code, str(REPO / "tools"), str(bsp),
                                   str(job) if job else "-", str(donor)], capture_output=True, text=True,
                                  timeout=1800).stdout.strip()
        said = light(q3t2, None, q3t2)
        check("q3t2 against itself is lit like its donor", said.startswith("PASS") and "sides 1.00" in said,
              said[:200])
        first = MGQ3T2_JOB / "candidate.bsp"
        if check("mg_q3t2's first delivery is there", first.is_file(), str(first)):
            said = light(first, MGQ3T2_JOB / "job", q3t2)
            check("RED: mg_q3t2's first delivery - its new rooms lit 3 to 10 against the donor's 44 - fails",
                  said.startswith("FAIL") and "level x" in said, said[:240])

    if want("storey1"):
        print("\n=== q3t2's storey with one door")
        if check("mg_q3t2's job is there", (MGQ3T2_JOB / "job" / "ledger.txt").is_file(), str(MGQ3T2_JOB)):
            def storeys(root: Path, name: str) -> tuple[list, str]:
                code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                        "import mapgen_delivery_gates as g; "
                        "text, err = g.plan_listing(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])); "
                        "print(err or ''); print(text)")
                w = a.work / name
                w.mkdir(parents=True, exist_ok=True)
                text = load_guard.run([sys.executable, "-c", code, str(root / "tools"), str(MGQ3T2_JOB / "job"),
                                       str(w), str(root)], capture_output=True, text=True, timeout=1800).stdout
                said = next((ln.strip() for ln in text.splitlines() if "dig storeys dealt:" in ln), "no tally")
                return [ln.strip() for ln in text.splitlines() if ln.startswith("  dig storeys doorway: ")], said
            one, said = storeys(REPO, "storey1")
            check("no pair of q3t2's sites qualifies, and one storey is dealt with one door", len(one) == 1
                  and "0 pairs qualify" in said and "dealt: 1 of" in said, f"{said[:120]} | {one[:1]}")
            root = tree(a.work, "storey1_red", ("src/mapgen/mapgen_geometry_edit.c",
                                                "                deal_storey_one_door(plan, donor, ground, rooms, walk,"
                                                " &rc, skins, num_skins, site, zn, used_room,\n",
                                                "                if (0) deal_storey_one_door(plan, donor, ground,"
                                                " rooms, walk, &rc, skins, num_skins, site, zn, used_room,\n"))
            if root is not None:
                one, said = storeys(root, "storey1_red")
                check("RED: without the one-door storey q3t2 deals none", not one and "dealt: 0 of" in said,
                      said[:120])

    if want("digwalls"):
        print("\n=== mg_q3t2's walls judged against the map its digs were dug into")
        cand = MGQ3T2_JOB / "candidate.bsp"
        if check("mg_q3t2's first delivery is there", cand.is_file(), str(cand)):
            def walls(root: Path) -> str:
                code = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                        "import mapgen_delivery_gates as g; "
                        "ok, said = g.ask_digwalls(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])); "
                        "print('PASS' if ok else 'FAIL', said)")
                return load_guard.run([sys.executable, "-c", code, str(root / "tools"), str(cand),
                                       str(MGQ3T2_JOB / "job"), str(q3t2)], capture_output=True, text=True,
                                      timeout=1800).stdout.strip()
            said = walls(REPO)
            check("against the rebuilt baseline no point opens high and none stands in the old air",
                  said.startswith("PASS"), said[:220])
            root = tree(a.work, "digwalls_red", ("tools/mapgen_delivery_gates.py",
                                                 "    return base[0] if base else donor\n", "    return donor\n"))
            if root is not None:
                said = walls(root)
                check("RED: against q3t2.bsp the pier's corner edge at -184 1720 reads as an opening",
                      said.startswith("FAIL") and "-184 1720" in said, said[:220])

    if want("courses"):
        print("\n=== a wall of courses glazed")
        from mapgen_geometry_fixtures import FIXTURES
        from check_mapgen_recut import build_driver, compile_map
        fx = a.work / "courses"
        fx.mkdir(parents=True, exist_ok=True)
        FIXTURES["courses_wall"](fx / "courses_wall.map")
        compile_map(fx / "courses_wall.map")
        bsp = fx / "courses_wall.bsp"
        offered = re.compile(r"window offered: opening \d+, WALL of room \d+ x thin, -8\.\.8, open (-?\d+)\.\.(-?\d+), "
                             r"sill (\d+)")

        def courses(root: Path, name: str) -> list[tuple[int, int, int]]:
            out = fx / name
            out.mkdir(parents=True, exist_ok=True)
            exe = build_driver(root, out)
            text = load_guard.run([str(exe), str(bsp), "--seed", "42", "--ambition", "80", "--list"],
                                  capture_output=True, text=True, timeout=600).stdout
            return [tuple(int(x) for x in m.groups()) for m in offered.finditer(text)]

        def proper(wins) -> bool:
            return bool(wins) and all(s >= 96 and lo >= -320 + 16 and hi <= 320 - 16 for lo, hi, s in wins)

        if check("the fixture compiles", bsp.is_file(), str(bsp)):
            wins = courses(REPO, "green")
            check("glazed, every pane's foot 96 over the floor and its jambs clear of the side walls", proper(wins),
                  f"{wins}")
            txn = fx / "txn.exe"
            src = [s if s != "tools/mapgen_pipeline_driver.c" else "tools/mapgen_transaction_driver.c"
                   for s in PIPELINE_SOURCES]
            if check("the transaction driver builds", gcc(REPO, src, txn)):
                job = fx / "txn_job"
                if job.exists():
                    shutil.rmtree(job)
                job.mkdir()
                compiler, _ = pinned_compiler(quiet=True)
                out = load_guard.run([str(txn), str(compiler), str(bsp), str(job), "q2mg", str(GAME), "42", "1",
                                      "--only", "window", "--ambition", "80"], capture_output=True, text=True,
                                     timeout=1800).stdout
                check("the window family's attempt on it is cut and accepted", "ledger: ACCEPTED=1" in out,
                      next((ln.strip() for ln in out.splitlines() if " window " in ln), "no window attempt")[:200])
            for name, old, new, says in (
                    ("courses_red_sill", "                    if (wpass == 1) {\n                        if (up > 0)\n",
                     "                    if (0) {\n                        if (up > 0)\n", "a foot at 64"),
                    ("courses_red_jamb", "                    if (wpass == 1) {\n                        bool jambs = true;\n",
                     "                    if (0) {\n                        bool jambs = true;\n",
                     "an opening on the side wall")):
                root = tree(a.work, name, ("src/mapgen/mapgen_geometry_edit.c", old, new))
                if root is not None:
                    wins = courses(root, name)
                    check(f"RED: {says} - the wall of courses is glazed wrong", bool(wins) and not proper(wins),
                          f"{wins}")

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    for s in STALE:
        print(f"STALE: {s}")
    print("RESULT:", "PASS" if not FAILED else "FAIL")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
