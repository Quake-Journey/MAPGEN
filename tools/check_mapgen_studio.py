"""MAPGEN Studio builds, publishes portable, and every page stands in both languages and both themes.

Ledger row 393 (Fable's brief 3, Studio P1). `tools/mapgen_studio/MapgenStudio` (.NET 10, Avalonia 12, FluentAvaloniaUI
3) is published self-contained into a work folder and asked `--selftest`: each page - home, generate, library, the
map card, settings, about - in Russian and English, light and dark, built and laid out at the window's size without
being shown; a text the string table lacks shows as `[key]` and fails the page. RED in a sandbox copy with one Russian
string taken out of the table: that page fails.

Row 405 (the PO, 2026-10-03: «толпа DLL в папке студии ... выглядит как свинарник»): the published folder holds the
program and nothing it runs on - no DLL, no symbols, no runtime file beside MapgenStudio.exe. RED in a copy published
without PublishSingleFile: the runtime's two hundred files lie beside it again.

    python tools/check_mapgen_studio.py [--work DIR]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "tools" / "mapgen_studio"
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\guard")
CLIENT = Path(r"O:\Claude2\q2pro-release")
CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def publish(src: Path, out: Path, build_root: Path) -> str:
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    if out.exists():
        shutil.rmtree(out)
    r = subprocess.run(["dotnet", "publish", str(src / "MapgenStudio" / "MapgenStudio.csproj"), "-c", "Release",
                        "-r", "win-x64", "--self-contained", "true", "-o", str(out),
                        f"-p:StudioBuildRoot={build_root}\\"], capture_output=True, text=True, env=env, timeout=1800)
    return "" if r.returncode == 0 and (out / "MapgenStudio.exe").is_file() else (r.stdout + r.stderr)[-1500:]


DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
GATES_SAMPLE = SRC / "fixtures" / "gates_sample.txt"


def seed_library(out: Path) -> None:
    """Row 401: a map with a checks report in the library, so the selftest builds its card - in Russian every
    check must have its plain words (S-1)."""
    (out / "data" / "bsp").mkdir(parents=True, exist_ok=True)
    (out / "data" / "descriptions").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DONOR, out / "data" / "bsp" / "gate_probe.bsp")
    shutil.copyfile(GATES_SAMPLE, out / "data" / "descriptions" / "gate_probe.gates.txt")


def selftest(out: Path) -> tuple[int, str]:
    (out / "selftest.txt").unlink(missing_ok=True)
    r = subprocess.run([str(out / "MapgenStudio.exe"), "--selftest"], capture_output=True, text=True, timeout=600)
    report = (out / "selftest.txt").read_text(encoding="utf-8") if (out / "selftest.txt").is_file() else ""
    return r.returncode, report


S5_GUARD = '"+set", "q2prox_config_readonly", "1", "+set", "net_clientport", "-1"'


def client_launches(studio_src: Path) -> tuple[bool, str]:
    """S5 in the sources: the one ProcessStartInfo that is not Explorer is Client.Launch's, its argument list begins
    with the guard, and the guard is the install tool's two settings."""
    others = []
    for cs in sorted((studio_src / "MapgenStudio").glob("*.cs")):
        for n, ln in enumerate(cs.read_text(encoding="utf-8").splitlines(), 1):
            if "new ProcessStartInfo(" in ln and "explorer.exe" not in ln and cs.name != "Client.cs":
                others.append(f"{cs.name}:{n}")
    client = (studio_src / "MapgenStudio" / "Client.cs").read_text(encoding="utf-8")
    first = "foreach (var a in Guard.Concat(args))" in client
    flags = S5_GUARD in client
    return (not others and first and flags,
            f"launches elsewhere {others}, guard first {first}, guard flags {flags}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-generate", action="store_true", help="skip the short generation (minutes of CPU)")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    out = a.work / "green"
    err = publish(SRC, out, a.work / "build_green")
    if check("the Studio publishes as a portable folder", not err, err):
        loose = sorted(f.name for f in out.iterdir() if f.is_file() and f.name != "MapgenStudio.exe")
        check("the folder holds the program alone - no DLL, symbols or runtime file beside it (row 405)", not loose,
              f"{len(loose)} beside it: {loose[:6]}")
        seed_library(out)
        code, report = selftest(out)
        passes = re.findall(r"^PASS (\w+) (\w+) (\w+)$", report, re.M)
        fails = [ln for ln in report.splitlines() if ln.startswith("FAIL")]
        check("every page stands in Russian and English, light and dark - 20 or more, none failing",
              code == 0 and len(passes) >= 20 and not fails,
              f"exit {code}, {len(passes)} PASS, {fails[:3]}")
        check("and the settings file is written beside the program", (out / "MapgenStudio.ini").is_file())
        check("the map card is among them, every check of its report in plain words (S-1, row 401)",
              "PASS ru light map" in report and "PASS en dark map" in report,
              next((ln for ln in report.splitlines() if " map" in ln and not ln.startswith("PASS")), ""))

    # row 405's RED: published without PublishSingleFile, the runtime lies beside the program again
    tidy_red = a.work / "red_tidy_src"
    if tidy_red.exists():
        shutil.rmtree(tidy_red)
    shutil.copytree(SRC, tidy_red, ignore=shutil.ignore_patterns("bin", "obj"))
    proj = tidy_red / "MapgenStudio" / "MapgenStudio.csproj"
    ptext = proj.read_text(encoding="utf-8")
    if check("RED: the one-file publish is where the mutation says",
             ptext.count("<PublishSingleFile>true</PublishSingleFile>") == 1):
        proj.write_text(ptext.replace("<PublishSingleFile>true</PublishSingleFile>",
                                      "<PublishSingleFile>false</PublishSingleFile>"), encoding="utf-8")
        tidy_out = a.work / "red_tidy"
        err = publish(tidy_red, tidy_out, a.work / "build_red_tidy")
        if check("the mutated Studio still publishes (not one file)", not err, err):
            dlls = sorted(f.name for f in tidy_out.glob("*.dll"))
            check("RED: not one file, DLLs lie beside the program again", len(dlls) > 100, f"{len(dlls)} DLLs")
    shutil.rmtree(tidy_red, ignore_errors=True)

    #
    # S5 (brief 3): every launch of the game client passes `+set q2prox_config_readonly 1 +set net_clientport -1`
    # first and hashes the configs around it (Client.cs); the sources hold no other launch of it. The run itself is
    # `--cover-test NAME` - one watched launch, never in this guard (no unattended client runs on the PO machine).
    # RED in a copy with the guard dropped from the argument list.
    #
    ok, detail = client_launches(SRC)
    check("every launch of the game client goes through Client.Launch with the S5 guard first", ok, detail)
    s5_red = a.work / "red_s5_src"
    if s5_red.exists():
        shutil.rmtree(s5_red)
    shutil.copytree(SRC, s5_red, ignore=shutil.ignore_patterns("bin", "obj"))
    ctext = (s5_red / "MapgenStudio" / "Client.cs").read_text(encoding="utf-8")
    (s5_red / "MapgenStudio" / "Client.cs").write_text(
        ctext.replace("foreach (var a in Guard.Concat(args))", "foreach (var a in args)", 1), encoding="utf-8")
    ok, detail = client_launches(s5_red)
    check("RED: with the guard dropped from the launch the case above goes red", not ok, detail)
    shutil.rmtree(s5_red, ignore_errors=True)

    #
    # Row 401 (S-1, S-6): two REDs in sandbox copies - one check's Russian words taken out of the table (the card
    # shows the tool's English line and the selftest names the missing key), and one Russian text turned English
    # (the selftest's English-on-a-Russian-page audit names it).
    #
    for label, old, new, expect in (
            ("the Russian words of the «reach» check taken out",
             '        ["gate.reach"] = "Из каждой точки появления можно дойти до каждого предмета и места",\n',
             "", "[gate.reach]"),
            ("a Russian section title turned English",
             '        ["lib.gates"] = "Проверки карты",\n',
             '        ["lib.gates"] = "Map checks",\n', "[english: Map checks]")):
        red401 = a.work / "red401_src"
        if red401.exists():
            shutil.rmtree(red401)
        shutil.copytree(SRC, red401, ignore=shutil.ignore_patterns("bin", "obj"))
        loc401 = red401 / "MapgenStudio" / "Loc.cs"
        t401 = loc401.read_text(encoding="utf-8")
        hit401 = old if old in t401 else old.replace("\n", "\r\n")
        if check(f"RED: {label} - the line is where the mutation says", t401.count(hit401) == 1,
                 f"{t401.count(hit401)} occurrences"):
            loc401.write_text(t401.replace(hit401, new.replace("\n", "\r\n") if "\r\n" in hit401 else new, 1),
                              encoding="utf-8")
            out401 = a.work / "red401"
            err = publish(red401, out401, a.work / "build_red401")
            if check(f"the mutated Studio still publishes ({label})", not err, err):
                seed_library(out401)
                code, report = selftest(out401)
                check(f"RED: {label} - the Russian map card fails the selftest naming it",
                      code != 0 and expect in report,
                      next((ln for ln in report.splitlines() if ln.startswith("FAIL")), report[-200:]))
        shutil.rmtree(red401, ignore_errors=True)

    #
    # Row 404: a run another Studio carries is shown as running and refuses a resume (the PO was offered to resume
    # the generation running from the command line). RED: the interrupted list not asking who carries a run - the
    # selftest's live run is listed as interrupted and its line fails.
    #
    red404 = a.work / "red404_src"
    if red404.exists():
        shutil.rmtree(red404)
    shutil.copytree(SRC, red404, ignore=shutil.ignore_patterns("bin", "obj"))
    gen404 = red404 / "MapgenStudio" / "Generation.cs"
    t404 = gen404.read_bytes().decode("utf-8")
    old404 = "        Unfinished(s).Where(x => !LiveElsewhere(x.runDir)).ToList();"
    if check("RED: the interrupted list's question who carries a run is where the mutation says",
             t404.count(old404) == 1, f"{t404.count(old404)} occurrences"):
        gen404.write_bytes(t404.replace(old404, "        Unfinished(s).ToList();", 1).encode("utf-8"))
        out404 = a.work / "red404"
        err = publish(red404, out404, a.work / "build_red404")
        if check("the mutated Studio still publishes (who carries a run not asked)", not err, err):
            code, report = selftest(out404)
            check("RED: not asking who carries a run, the selftest's live run is listed as interrupted",
                  code != 0 and "FAIL a run a live Studio carries is shown as running" in report,
                  next((ln for ln in report.splitlines() if ln.startswith("FAIL")), report[-200:]))
    shutil.rmtree(red404, ignore_errors=True)

    sandbox = a.work / "red_src"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    shutil.copytree(SRC, sandbox, ignore=shutil.ignore_patterns("bin", "obj"))
    loc = sandbox / "MapgenStudio" / "Loc.cs"
    text = loc.read_text(encoding="utf-8")
    line = '        ["home.title"] = "Добро пожаловать",\n'
    crlf = line.replace("\n", "\r\n")
    hit = crlf if crlf in text else line
    if check("RED: the home page's Russian title is where the mutation says", text.count(hit) == 1,
             f"{text.count(hit)} occurrences"):
        loc.write_text(text.replace(hit, "", 1), encoding="utf-8")
        red_out = a.work / "red"
        err = publish(sandbox, red_out, a.work / "build_red")
        if check("the mutated Studio still publishes", not err, err):
            code, report = selftest(red_out)
            check("RED: without that string the Russian home page fails the selftest - the case above goes red",
                  code != 0 and "FAIL ru light home: missing [home.title]" in report,
                  f"exit {code}; {[ln for ln in report.splitlines() if ln.startswith('FAIL')][:2]}")
    shutil.rmtree(sandbox, ignore_errors=True)

    #
    # Row 394 (P2): one short generation driven as the window drives it (`--generate-test`): the engine built from
    # this tree beside the published Studio, the client the PO's Release (its baseq2 holds the textures), a draft of
    # q2dm1 at likeness 50 with two builds; paused three seconds while building edits - the job's CPU time must stand
    # still and no progress line be added; then the stages in order and the map in the library with its source and
    # both descriptions. RED with the pause's suspend taken out (`--pause-only`, the run stopped after the pause):
    # the CPU runs on through the pause.
    #
    if not a.no_generate and (out / "MapgenStudio.exe").is_file():
        def engine_and_client(studio: Path) -> str:
            r = subprocess.run([sys.executable, str(REPO / "tools" / "mapgen_studio_engine.py"), str(studio)],
                               capture_output=True, text=True, timeout=1800)
            ini = studio / "MapgenStudio.ini"
            text = ini.read_text(encoding="utf-8") if ini.is_file() else ""
            # a fresh folder has no ini until the program first runs: then the line is added, not replaced
            text = (re.sub(r"^client=.*$", lambda _m: f"client={CLIENT}", text, flags=re.M)
                    if re.search(r"^client=", text, re.M) else text + f"\n[folders]\nclient={CLIENT}\n")
            ini.write_text(text, encoding="utf-8")
            return "" if r.returncode == 0 else (r.stdout + r.stderr)[-800:]

        def generate(studio: Path, *extra: str) -> tuple[int, str]:
            (studio / "generate_test.txt").unlink(missing_ok=True)
            r = subprocess.run([str(studio / "MapgenStudio.exe"), "--generate-test", *extra], capture_output=True,
                               text=True, timeout=3600)
            rep = studio / "generate_test.txt"
            return r.returncode, rep.read_text(encoding="utf-8") if rep.is_file() else ""

        err = engine_and_client(out)
        if check("the engine is built beside the Studio and the client set", not err, err):
            code, report = generate(out)
            lines = [ln for ln in report.splitlines() if ln.startswith(("PASS", "FAIL"))]
            for ln in lines:
                check("generate: " + ln[5:].split(" -- ")[0], ln.startswith("PASS"), ln.partition(" -- ")[2][:200])
            check("the short generation's report has every question", len(lines) >= 8, f"{len(lines)} lines, exit {code}")
        red_src = a.work / "red_pause_src"
        if red_src.exists():
            shutil.rmtree(red_src)
        shutil.copytree(SRC, red_src, ignore=shutil.ignore_patterns("bin", "obj"))
        gen = red_src / "MapgenStudio" / "Generation.cs"
        gtext = gen.read_text(encoding="utf-8")
        hook = "        (_gatesJob ?? _job)?.Suspend(pause);"
        if check("RED: the pause's suspend is where the mutation says", gtext.count(hook) == 1,
                 f"{gtext.count(hook)} occurrences"):
            gen.write_text(gtext.replace(hook, "", 1), encoding="utf-8")
            red_out = a.work / "red_pause"
            err = publish(red_src, red_out, a.work / "build_red_pause")
            red_err = engine_and_client(red_out) if not err else "the Studio did not publish"
            if check("the pauseless Studio still publishes, with its engine", not err and not red_err, err or red_err):
                code, report = generate(red_out, "--pause-only")
                held = [ln for ln in report.splitlines() if "CPU time stood still" in ln]
                check("RED: with the suspend taken out the CPU runs on through the pause - the case above goes red",
                      bool(held) and held[0].startswith("FAIL"), held[0] if held else report[-300:])
        shutil.rmtree(red_src, ignore_errors=True)

    print(f"\nSUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
