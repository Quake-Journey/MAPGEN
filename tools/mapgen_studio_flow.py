r"""One map the whole way MAPGEN Studio makes it (ledger rows 412h..412l) - the evidence maps of brief 11.

    python tools/mapgen_studio_flow.py WORK --donor q2dm1 [--fidelity 20] [--seed 42] [--stairways N]
                                       [--destruction D] [--pipeline EXE] [--game BASEQ2]

The steps of `Generation.cs` in its order: the generator (`pipeline.exe`, the Studio's words, the donor's light
calibration if it has one) -> the finished map copied to WORK/candidate.bsp -> the donor's light fitted once if it has
no calibration (on a COPY of the donor in WORK/donors: the installed Studio's donors are not touched) -> each dug
room's lights brought to its door (`mapgen_room_light.py`, relit first under a new fit) -> the delivery gates -> with
D > 0 the destruction (`mapgen_destroy.py`) and the checks a ruin answers to, named «after destruction». All of it into
WORK/gates.txt as the Studio writes it; one line of summary at the end. Started through the load guard; one map, one
run - never a loop.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

ENGINE = Path(r"O:\Claude2\MapgenStudio\engine")
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
FINISH = re.compile(r'stage=finish result=(\S+) .*?bsp="([^"]+)"')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("work", type=Path)
    ap.add_argument("--donor", required=True)
    ap.add_argument("--fidelity", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stairways", type=int, default=0)
    ap.add_argument("--destruction", type=int, default=0)
    ap.add_argument("--pipeline", type=Path, default=ENGINE / "pipeline.exe")
    ap.add_argument("--game", type=Path, default=GAME)
    ap.add_argument("--relight", action="store_true",
                    help="relight the map under the donor's calibration as it stands now (a calibration changed since)")
    ap.add_argument("--after-generation", action="store_true",
                    help="the generation already finished in WORK/job: only the steps after it")
    a = ap.parse_args()
    guard.pin_self()
    a.work.mkdir(parents=True, exist_ok=True)
    donors = a.work / "donors"
    donors.mkdir(exist_ok=True)
    for f in ENGINE.joinpath("donors").glob(f"{a.donor}.*"):
        if not (donors / f.name).is_file():
            shutil.copy2(f, donors / f.name)
    base = donors / f"{a.donor}.bsp"
    job = a.work / "job"
    if not a.after_generation:
        if job.exists():
            shutil.rmtree(job)
        job.mkdir()
    words = [str(a.pipeline), str(pinned_compiler()[0]), str(base), str(job), "q2mg", str(a.fidelity), str(a.seed),
             "--moddir", str(a.game), "--final", "--hold-to-donor"]
    light = base.with_suffix(".light.txt")
    if light.is_file() and light.read_text(encoding="utf-8").strip():
        words += ["--light-flags", light.read_text(encoding="utf-8").strip()]
    keys = base.with_suffix(".light_keys.txt")
    if keys.is_file() and keys.read_text(encoding="utf-8").strip():
        words += ["--light-keys", keys.read_text(encoding="utf-8").strip()]
    if a.stairways:
        words += ["--stairways", str(a.stairways)]
    words += ["--checkpoints", "0"]
    (a.work / "words.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
    began = time.time()
    code = 0
    if not a.after_generation:
        with open(a.work / "pipeline_out.txt", "w", encoding="utf-8", errors="replace") as out:
            code = guard.run(words, stdout=out, stderr=out, timeout=4 * 3600).returncode
    took = int(time.time() - began)
    # the generator says its end in the job's progress file
    text = (job / "progress.txt").read_text(encoding="utf-8", errors="replace") if (job / "progress.txt").is_file() else ""
    m = None
    for m in FINISH.finditer(text):
        pass
    if not m or not Path(m.group(2)).is_file():
        print(f"FLOW FAILED: the generator gave no map (exit {code}, {took} s)")
        return 1
    cand = a.work / "candidate.bsp"
    shutil.copy2(m.group(2), cand)
    py = sys.executable
    env = dict(os.environ)
    env["MAPGEN_GAME"] = str(a.game)          # brief 13 W1: every step lights and checks against this game

    def step(args: list) -> subprocess.CompletedProcess:
        return subprocess.run([py, *map(str, args)], capture_output=True, text=True, errors="replace", env=env)

    fit = step([TOOLS / "mapgen_light_autofit.py", cand, base, a.work / "light_fit"])
    rooms = step([TOOLS / "mapgen_room_light.py", cand, "--job", job, "--donor", base]
                 + (["--relight-first"] if "FITTED" in fit.stdout or a.relight else []))
    # brief 12 L3: the fit asked again of the map as the room step left it (only when the gate reads it out of band)
    refit = step([TOOLS / "mapgen_light_autofit.py", cand, base, a.work / "light_refit", "--after-rooms"])
    # a refit moves the whole map's level: the rooms are brought to their doors once more under it
    if "REFITTED" in refit.stdout:
        again = step([TOOLS / "mapgen_room_light.py", cand, "--job", job, "--donor", base])
        refit.stdout += "\nROOM LIGHT AGAIN\n" + again.stdout + again.stderr
    gates = step([TOOLS / "mapgen_delivery_gates.py", cand, "--job", job, "--donor", base])
    after = ""
    if a.destruction > 0:
        d = step([TOOLS / "mapgen_destroy.py", cand, "--donor", base, "--destruction", a.destruction, "--seed",
                  a.seed, "--game", a.game, "--keep-from", job])   # brief 14 F2: its own building kept
        env["MAPGEN_GATE_PREFIX"] = "after destruction: "
        g2 = step([TOOLS / "mapgen_delivery_gates.py", cand, "--job", job, "--donor", base, "--only",
                   "finished,axes,water,starts,stairways"])
        after = "\nDESTRUCTION\n" + d.stdout + d.stderr + "\n" + g2.stdout + g2.stderr
    all_text = (gates.stdout + gates.stderr + "\nLIGHT FIT\n" + fit.stdout + fit.stderr + "\nROOM LIGHT\n"
                + rooms.stdout + rooms.stderr + "\nLIGHT REFIT\n" + refit.stdout + refit.stderr + after)
    (a.work / "gates.txt").write_text(all_text, encoding="utf-8")
    passed = len(re.findall(r"^\s+PASS\s", all_text, re.M))
    failed = re.findall(r"^\s+FAIL\s+(.*?)(?:  --|$)", all_text, re.M)
    print(f"FLOW {a.donor} {a.fidelity}/{a.seed} stairways {a.stairways} destruction {a.destruction}: "
          f"{m.group(1)} in {took} s; checks {passed} passed, {len(failed)} failed"
          + (": " + "; ".join(failed) if failed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
