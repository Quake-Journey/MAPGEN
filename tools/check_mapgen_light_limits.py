"""Brief 18 D1 guard: a large map's light pass is planned from its faces, and runs again past the light tool's limits.

The PO's mg_10_6695 (q3t2 at 1000 %, 11.10) went out unlit: the light tool stopped at «Exceeded MAX_PATCHES 65535»
(more patches of 64 across than it holds), and run again with larger patches it stopped at «lightdatasize 17665602 >
maxdata 8388608». Two things answer it, in the generator (`light_the_artifact`) and in the relight
(`mapgen_room_light.relight`: the ruin's light and the final light):

  the PLAN - before the first pass the patch size and the lightmap's room are chosen from the map's faces
  (`light_plan`): the smallest of 64/128/256/512 that keeps the patches under 60000, and `-maxdata` for the lightmap
  and a tenth over when that is past the tool's 8 MB;
  the NET - a pass that still stops at one of the two limits runs again with `-subdiv` doubled, or `-maxdata` raised
  to what the tool asked, rounded up to 16 MB.

Asked:
  1 the relight of a small map (q2dm1: the plan leaves the tool's defaults) against a stand-in light tool that
    refuses without `-subdiv` 128 or more, then without `-maxdata` 16 MB or more: it ends with a map, its log saying
    both retries;
  2 the stand-in was run three times: plain, with -subdiv 128, with -subdiv 128 and -maxdata 33554432;
  3 the relit map keeps its entities;
  4 the plan against the light tool's own count (q2tool, 13.10) on tools/fixtures/mapgen_prior_keep/
    mg_b18_q2dm3_final.bsp.gz: 36447 patches at 64, 17224 at 128, a lightmap of 1040397 bytes - within 8 %, 8 % and 2 %;
  5 the generator's plan (`pipeline.exe --light-plan`) says of that map what the relight's says;
  6 a map as large as the PO's q3t2 at 1000 % (his library's mg_b18_q3t2, else mg_10_6695): the plan says -subdiv 128
    or more and room for the lightmap the file holds - and relit against the stand-in, the light tool is run ONCE;
  7 the generator against the fake compiler (`light_limits`: the same two refusals): the light pass again with
    -subdiv 128, then with -maxdata 33554432, and the run ends with a lit map;
  8 a run's last measure takes its routes from the walks the run already took («oracle routes from the run's own
    walks»), not from two walks more. Studio 3.32 lost it (13.10: the walk's budget went 40000 -> 60000 in the
    generator and stayed 40000 in the request `pipeline.exe` makes, «the walks do not fit») and every generation
    walked its two maps again at the end - 202 s on mg_b18_q2dm3 (41:46 for the brief's 40 min), 331 s on the PO's
    q3t2 frame. Nothing asked it of a run to its end before (check_mapgen_pipeline.py reads the call's text). Asked
    of a small real run: the reach fixtures' open room through the pinned compiler at fidelity 50, in memory - three
    edits accepted, 14 s. (The fake compiler's run applies nothing and walks no candidate: it has no walks to give.)

RED: `--red` takes the retries out (the relight's loop once; the generator with --no-light-again) - 1, 2 and 7 fail.
     `--red-plan` takes the plan out of the relight - 6 fails. `--red-ents`: the retry's words over the entities - 3.
     `--red-walks`: the request's walk budget as 3.32 left it (`--walk-budget-old`) - 8 fails.

    python tools/check_mapgen_light_limits.py [--red] [--red-plan] [--red-ents] [--red-walks] [--no-pipeline]
"""
from __future__ import annotations

import argparse
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
FIXTURE = TOOLS / "fixtures" / "mapgen_prior_keep" / "mg_b18_q2dm3_final.bsp.gz"
TOOL_SAID = {"patches64": 36447, "patches128": 17224, "lightmap": 1040397}     # q2tool -rad on FIXTURE, 13.10
LARGE = [Path(r"O:\Claude2\MapgenStudio\data\bsp\mg_b18_q3t2.bsp"), Path(r"O:\Claude2\MapgenStudio\data\bsp\mg_10_6695.bsp")]
NO_WINDOW = 0x08000000
FAILED = 0

STAND_IN = r'''import sys, pathlib
args = sys.argv[1:]
log = pathlib.Path(sys.argv[0]).with_suffix(".calls")
with log.open("a", encoding="utf-8") as f:
    f.write(" ".join(a for a in args if a.startswith("-") or a.isdigit()) + "\n")
def last(flag, default):
    v = default
    for i, a in enumerate(args[:-1]):
        if a == flag:
            v = int(float(args[i + 1]))
    return v
if last("-subdiv", 64) < 128:
    print("************ ERROR ************\nExceeded MAX_PATCHES 65535")
    sys.exit(1)
if last("-maxdata", 2097152) < 16777216:
    print("************ ERROR ************\nlightdatasize 17665602 > maxdata 8388608")
    sys.exit(1)
print("lit")
'''


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def within(mine: int, theirs: int, share: float) -> bool:
    return abs(mine - theirs) <= share * theirs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--red-plan", action="store_true", help="RED: the relight's first pass at the tool's defaults")
    ap.add_argument("--red-ents", action="store_true",
                    help="RED: the retry's words written over the map's entity text (mg_b18_q3t2, mg_10_6695 relit)")
    ap.add_argument("--red-walks", action="store_true",
                    help="RED: the request's walk budget as Studio 3.32 left it - the last measure walks again")
    ap.add_argument("--no-pipeline", action="store_true", help="the relight alone: the generator is not built")
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="light_limits_"))
    try:
        script = work / "q2tool.py"
        script.write_text(STAND_IN, encoding="utf-8")
        tool = work / "q2tool.cmd"
        tool.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
        source = (TOOLS / "mapgen_room_light.py").read_text(encoding="utf-8")
        red = source
        if a.red_ents:
            anchor = '        told = r.stdout or ""\n'
            if not check("RED: the tool's words are where they say", source.count(anchor) == 1):
                return 1
            red = red.replace(anchor, '        text = told = r.stdout or ""\n')
        if a.red:
            anchor = "    for _ in range(6):\n        these = words"
            if not check("RED: the retry loop is where it says", source.count(anchor) == 1):
                return 1
            red = red.replace(anchor, "    for _ in range(1):\n        these = words")
        if a.red_plan:
            anchor = "    subdiv, maxdata, patches, lightmap = light_plan(raw)\n"
            if not check("RED: the plan is where it says", source.count(anchor) == 1):
                return 1
            red = red.replace(anchor, "    subdiv, maxdata, patches, lightmap = 64, 0, [0, 0, 0, 0], 0\n")
        if red != source:
            (work / "mapgen_room_light.py").write_text(red, encoding="utf-8")
            sys.path.insert(0, str(work))
        sys.path.insert(1 if red != source else 0, str(TOOLS))
        os.environ["MAPGEN_Q2TOOL"] = str(tool)
        import mapgen_memfile
        mapgen_memfile.compiler_has_memory_files = lambda compiler: False     # the stand-in works in files
        import mapgen_room_light as rl
        from mapgen_light_calibrate import entity_text
        calls_file = work / "q2tool.calls"

        def relit(bsp: Path, where: str) -> tuple[str, str, list[str]]:
            calls_file.unlink(missing_ok=True)
            failed = ""
            try:
                rl.relight(bsp, entity_text(bsp.read_bytes()), "-scale 1", work / where)
            except SystemExit as e:
                failed = str(e)[:200]
            log = work / where / "relight" / "rad.log"
            return (failed, log.read_text(encoding="utf-8") if log.is_file() else "",
                    calls_file.read_text(encoding="utf-8").splitlines() if calls_file.is_file() else [])

        bsp = work / "q2mg.bsp"
        shutil.copyfile(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp", bsp)
        before = entity_text(bsp.read_bytes())
        failed, said, calls = relit(bsp, "relight_work")
        check("the relight ends with a map, its log saying both retries",
              not failed and "again with -subdiv 128" in said and "again with -maxdata 33554432" in said,
              failed or said.splitlines()[:2].__repr__())
        check("the light tool was run plain, with -subdiv 128, then with -subdiv 128 and -maxdata 33554432 (17.7 MB rounded up to 16 MB)",
              len(calls) == 3 and "-subdiv" not in calls[0] and "-subdiv 128" in calls[1]
              and "-subdiv 128" in calls[2] and calls[2].rstrip().endswith("-maxdata 33554432"),
              " | ".join(calls))
        # 12.10: the retry once wrote the light tool's words over the entity text - the relit q3t2 had no starts
        after = entity_text(bsp.read_bytes()) if bsp.is_file() else ""
        check("the relit map keeps its entities: the text it was given, every start and light in it",
              after == before and after.count('"info_player_deathmatch"') > 0,
              f"{after.count('classname')} entities of {before.count('classname')}")

        # the plan against the light tool's own count
        fixture = work / "fixture.bsp"
        fixture.write_bytes(gzip.open(FIXTURE).read())
        subdiv, maxdata, patches, lightmap = rl.light_plan(fixture.read_bytes())
        check("the plan counts as the light tool does: patches at 64 and at 128 within 8 %, the lightmap within 2 %",
              within(patches[0], TOOL_SAID["patches64"], 0.08) and within(patches[1], TOOL_SAID["patches128"], 0.08)
              and within(lightmap, TOOL_SAID["lightmap"], 0.02) and subdiv == 64 and maxdata == 0,
              f"{patches[0]} for {TOOL_SAID['patches64']}, {patches[1]} for {TOOL_SAID['patches128']}, "
              f"{lightmap} for {TOOL_SAID['lightmap']}; -subdiv {subdiv}, -maxdata {maxdata}")

        exe = None
        if not a.no_pipeline:
            import check_mapgen_pipeline as cp
            exe = cp.build(work)
            if check("the generator builds", exe is not None):
                r = subprocess.run([str(exe), "--light-plan", str(fixture)], capture_output=True, text=True,
                                   creationflags=NO_WINDOW)
                got = dict(re.findall(r"(\w+)=(\d+)", r.stdout))
                check("the generator's plan says of that map what the relight's says",
                      got and int(got.get("subdiv", 0)) == subdiv and int(got.get("maxdata", -1)) == maxdata
                      and [int(got.get(k, -1)) for k in ("patches64", "patches128", "patches256", "patches512")] == patches
                      and within(int(got.get("lightmap", -1)), lightmap, 0.001), r.stdout.strip()[:200])

        large = next((p for p in LARGE if p.is_file()), None)
        if check("a map as large as the PO's q3t2 at 1000 % is in his library", large is not None,
                 " / ".join(p.name for p in LARGE)):
            import struct
            raw = large.read_bytes()
            holds = struct.unpack_from("<ii", raw, 8 + 8 * 7)[1]
            ls, lm, lp, ll = rl.light_plan(raw)
            check(f"{large.stem}: the plan says larger patches and room for its lightmap",
                  ls >= 128 and lp[(64, 128, 256, 512).index(ls)] <= rl.PATCHES_WANTED and lm >= max(holds, ll)
                  and lm % (16 << 20) == 0 and lm <= 128 << 20,
                  f"{lp[0]} patches at 64, {lp[1]} at 128 -> -subdiv {ls}; lightmap {ll} (the file holds {holds}) -> "
                  f"-maxdata {lm}")
            big = work / "big.bsp"
            shutil.copyfile(large, big)
            failed, said, calls = relit(big, "relight_big")
            check(f"{large.stem} relit: the light tool is run ONCE, with the plan's -subdiv and -maxdata",
                  not failed and len(calls) == 1 and f"-subdiv {ls}" in calls[0] and f"-maxdata {lm}" in calls[0]
                  and "light plan:" in said, failed or " | ".join(calls)[:300])

        if exe is not None:
            # the generator against the fake compiler: fidelity 100 on the fake's own cube, the final profile
            seed = cp.fresh(work, "seed_donor")
            cp.verdict(exe, [str(cp.FAKE), str(cp.DONOR), str(seed), "test", "100", "1", "--fake", sys.executable,
                             "success"])
            donor = work / "fake_donor.bsp"
            if (seed / "baseline" / "test.bsp").is_file():
                donor.write_bytes((seed / "baseline" / "test.bsp").read_bytes())
            if check("the fake compiler produced a donor to fork", donor.is_file()):
                job = cp.fresh(work, "light_limits")
                fake_calls = work / "fake.calls"
                os.environ["MAPGEN_FAKE_CALLS"] = str(fake_calls)
                got, out = cp.verdict(exe, [str(cp.FAKE), str(donor), str(job), "test", "100", "1", "--fake",
                                            sys.executable, "light_limits", "--final"]
                                      + (["--no-light-again"] if a.red else []))
                os.environ.pop("MAPGEN_FAKE_CALLS", None)
                progress = (job / "progress.txt").read_text(encoding="utf-8", errors="replace") \
                    if (job / "progress.txt").is_file() else out
                rad = [l for l in (fake_calls.read_text(encoding="utf-8").splitlines() if fake_calls.is_file() else [])
                       if "rad" in l]
                check("the generator's light pass runs again past both limits: -subdiv 128, then -maxdata 33554432",
                      "stage=light-again subdiv=128 maxdata=33554432" in progress + out and len(rad) >= 3
                      and "subdiv=64" in rad[0] and "subdiv=128 maxdata=8388608" in rad[-2]
                      and "subdiv=128 maxdata=33554432" in rad[-1],
                      f"{got}; light passes: " + " | ".join(rad)[:300])
                # the fake's map says its stages in its worldspawn, so the generator never takes its lit copy for the
                # judged map («the lit compile is not the judged map», `success` too): the light compile's own word
                # is what is asked here - a real map lit past both limits is the PO's q3t2 run (stage=light lit=1)
                rad_log = (job / "lit" / "rad.log").read_text(encoding="utf-8", errors="replace") \
                    if (job / "lit" / "rad.log").is_file() else ""
                check("and the light compile ends OK with both flags, its log saying the two passes it ran again",
                      rad_log.startswith("light compile: OK") and "-subdiv 128 -maxdata 33554432" in rad_log[:200]
                      and rad_log.count("light pass stopped") == 2, rad_log[:160].replace("\n", " | "))
            # 8: a small real run to its end - where its last measure's routes came from. The pinned compiler
            # itself: the stand-in light tool this guard put in its place is taken out for it
            import mapgen_reach_fixtures as fixtures
            from mapgen_pinned_compiler import pinned_compiler
            stand_in = os.environ.pop("MAPGEN_Q2TOOL", None)
            try:
                real = Path(pinned_compiler()[0])
                room = cp.fresh(work, "walks_room")
                source = room / "open_room.map"
                fixtures.FIXTURES["open_room"](source)
                made = subprocess.run([str(real), "-bsp", "-threads", "4", "-moddir", str(cp.GAME), "-basedir",
                                       str(cp.GAME), "-gamedir", str(cp.GAME), str(source)], capture_output=True,
                                      text=True, timeout=1800, creationflags=NO_WINDOW)
                if check("the open room compiles as a donor", source.with_suffix(".bsp").is_file(),
                         (made.stdout + made.stderr)[-300:].replace("\n", " | ")):
                    got, out = cp.verdict(exe, [str(real), str(source.with_suffix(".bsp")),
                                                str(cp.fresh(work, "walks_job")), "open_room", "50", "1",
                                                "--moddir", str(cp.GAME), "--memory", "1024"]
                                          + (["--walk-budget-old"] if a.red_walks else []))
                    routes = next((l.strip() for l in out.splitlines() if l.strip().startswith("oracle")),
                                  "no such line")
                    check("a run's last measure takes its routes from the walks the run already took, not two more",
                          got == "OK" and "routes from the run's own walks" in routes, f"{got}; {routes}")
            finally:
                if stand_in is not None:
                    os.environ["MAPGEN_Q2TOOL"] = stand_in
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
