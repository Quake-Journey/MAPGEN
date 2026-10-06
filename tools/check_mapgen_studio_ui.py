"""The Studio's window driven through a run, as the PO uses it (ledger row 410).

The PO, 05.10, in one morning: the Studio vanished when he went back to the run's page («The Control already has a
parent»), its window hung while a generation ran, every stage showed a tick on a failed run, a pause did not stop the
clocks, the plan closed the Studio on its first frame («Visual was invalidated during the render pass»), a restart put
q2dm1 back as the base, and the Studio's own self-test wrote its ticks into his settings - «делаешь крутые вещи но
лажаешь в очевидном». None of it was in a guard: the self-test lays pages out without a window, the generation test
runs without one.

Here the Studio is built into a work folder with a stand-in engine (tools/mapgen_studio/fixtures/fake_pipeline.c: the
real progress lines, ledger and maps in a few seconds), the donors q2dm1 and koldduel1, its own settings, and run with
`--ui-test`: the real window, off the screen's edge, through every page, a run left and come back to, paused, the plan
full screen and back, stopped, resumed and finished, no key in brackets on the window or in the description, the
bases kept across a restart (MainWindow.UiTest). RED: the same Studio without the run view taken off its old page -
the window dies on the way back, no END line.

    python tools/check_mapgen_studio_ui.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as load_guard  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "tools" / "mapgen_studio"
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\ui_guard")
DONORS = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors")
CLIENT = Path(r"O:\Claude2\q2pro-release")
CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def build_studio(src: Path, out: Path, root: Path) -> str:
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    if out.exists():
        shutil.rmtree(out)
    r = load_guard.run(["dotnet", "build", str(src / "MapgenStudio" / "MapgenStudio.csproj"), "-c", "Release",
                        "-o", str(out), f"-p:StudioBuildRoot={root}\\"], capture_output=True, text=True, env=env,
                       timeout=1800)
    return "" if r.returncode == 0 and (out / "MapgenStudio.exe").is_file() else (r.stdout + r.stderr)[-1500:]


def stage(studio: Path, fake: Path) -> None:
    engine = studio / "engine"
    (engine / "donors").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fake, engine / "pipeline.exe")
    shutil.copyfile(fake, engine / "q2tool.exe")          # named, never run by the stand-in
    for d in ("q2dm1.bsp", "koldduel1.bsp"):
        shutil.copyfile(DONORS / d, engine / "donors" / d)
    for d in ("data", "temp"):
        shutil.rmtree(studio / d, ignore_errors=True)
    # never a cover: the game is not launched by a test, whatever a run asks
    (studio / "MapgenStudio.ini").write_text(f"client={CLIENT}\nauto_covers=0\n", encoding="utf-8")
    (studio / "ui_test.txt").unlink(missing_ok=True)


def run(studio: Path) -> tuple[int, str]:
    # row 411: a second an attempt - at 300 ms a run under the machine's load could end before the walk stopped it
    env = dict(os.environ, FAKE_STEP_MS="1000")
    try:
        r = load_guard.run([str(studio / "MapgenStudio.exe"), "--ui-test"], cwd=studio, env=env, timeout=600,
                           capture_output=True, text=True)
        code = r.returncode
    except subprocess.TimeoutExpired:
        code = -1
    report = studio / "ui_test.txt"
    return code, report.read_text(encoding="utf-8") if report.is_file() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    fake = a.work / "fake_pipeline.exe"
    r = subprocess.run(["gcc", "-O2", str(SRC / "fixtures" / "fake_pipeline.c"), "-o", str(fake)],
                       capture_output=True, text=True)
    if not check("the stand-in engine builds", r.returncode == 0 and fake.is_file(), r.stderr[-400:]):
        return 1
    studio = a.work / "green"
    err = build_studio(SRC, studio, a.work / "build_green")
    if not check("the Studio builds", not err, err):
        return 1
    stage(studio, fake)
    code, report = run(studio)
    for ln in report.splitlines():
        if ln.startswith(("PASS", "FAIL")):
            check(ln[5:].split(" -- ")[0], ln.startswith("PASS"), ln.split(" -- ", 1)[1][:300] if " -- " in ln else "")
    check("the window ran its whole walk (END) and left with 0", "END" in report and code == 0, f"exit {code}")
    if not a.no_red:
        # RED: the run view not taken off the page it was last shown on
        sandbox = a.work / "red_src"
        shutil.rmtree(sandbox, ignore_errors=True)
        shutil.copytree(SRC, sandbox, ignore=shutil.ignore_patterns("bin", "obj"))
        mw = sandbox / "MapgenStudio" / "MainWindow.cs"
        text = mw.read_text(encoding="utf-8")
        anchor = "            if (_runView.Parent is Decorator old)\n                old.Child = null;\n"
        if check("RED: the mutation is where it says", text.count(anchor) == 1):
            mw.write_text(text.replace(anchor, ""), encoding="utf-8")
            red = a.work / "red"
            err = build_studio(sandbox, red, a.work / "build_red")
            if check("RED: the mutated Studio builds", not err, err):
                stage(red, fake)
                code, report = run(red)
                check("RED: back on the run page the window dies before its walk ends - the case above goes red",
                      "END" not in report or code != 0, f"exit {code}, END {'END' in report}")
    print(f"{CASES - FAILED}/{CASES} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
