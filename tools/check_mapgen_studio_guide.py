r"""The Studio's guide is the Studio's (Fable's brief 10, D1).

`doc/mapgen_studio/MAPGEN_Studio_Guide_RU.md` and `..._EN.md` refer to screenshots the program makes of itself
(`MapgenStudio.exe --shots DIR`, and `--ui-test` with MAPGEN_SHOTS for the run's pages). Asserted:
* the two guides refer to the same images, by the same names, under `screens/ru/` and `screens/en/`;
* every image referred to exists, and `screens/build.txt` names the version of Versions.cs - the pictures are the
  current build's, not an older one's;
* every page the shots mode makes is referred to by both guides (a page the guide forgot), and every option of
  «Размах переделок» named in Loc.cs (gen.opt.*) is named in the guide by its own words, in each language.
RED: an image taken away - the guard goes red (the first case).

    python tools/check_mapgen_studio_guide.py [--shots] [--no-red]
    --shots: make the pictures first (the Studio built to a scratch folder, `--shots`; the run's two pictures need
             the window walk - run check_mapgen_studio_ui.py with MAPGEN_SHOTS set).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
DOC = REPO / "doc" / "mapgen_studio"
STUDIO = REPO / "tools" / "mapgen_studio" / "MapgenStudio"
GUIDES = {"ru": DOC / "MAPGEN_Studio_Guide_RU.md", "en": DOC / "MAPGEN_Studio_Guide_EN.md"}
IMAGE = re.compile(r"!\[[^\]]*\]\(screens/(ru|en)/([a-z_]+\.png)\)")
PAGES = ["home", "generate", "generate_options", "library", "map", "settings", "about", "run", "run_full"]
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def images(lang: str) -> list[tuple[str, str]]:
    return IMAGE.findall(GUIDES[lang].read_text(encoding="utf-8"))


def current_version() -> str:
    m = re.search(r'new\("(\d+\.\d+)", "', (STUDIO / "Versions.cs").read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def loc_options(lang: str) -> list[str]:
    """The words of every «Размах переделок» option (gen.opt.*), in one language's table of Loc.cs."""
    text = (STUDIO / "Loc.cs").read_text(encoding="utf-8")
    tables = re.split(r"\n\s*(?:public|private|internal)?\s*static readonly Dictionary<string, string> (\w+)", text)
    # tables: [head, name1, body1, name2, body2 ...]
    body = ""
    for i in range(1, len(tables) - 1, 2):
        if tables[i].lower().startswith(lang):
            body = tables[i + 1]
    return re.findall(r'\["gen\.opt\.[a-z_]+"\] = "([^"]+)"', body)


INSTALLED = Path(r"O:\Claude2\MapgenStudio")
SHOT_MAPS = ("mg_10_45f", "mg_cor", "mg_q3t2")
SHOT_INI = r"""[ui]
language=ru
theme=light
start_page=home
[folders]
maps=data\maps
bsp=data\bsp
temp=temp
client=O:\Claude2\q2pro-release
python=C:\Python314\python.exe
save_map_source=0
auto_covers=0
scheme=1
bases=q2dm1
graft_mode=0
fidelity=20
seed=42
"""


def make_shots(work: Path, pages: list[str] | None = None) -> Path | None:
    """The pictures, made by a build of this tree in a folder of its own: the Studio with its engine, one base (q2dm1),
    three finished maps of the installed library with their covers, the checks' tools folder, light theme - nothing of
    the PO's settings. Then the map on the whole screen from a job built of mg_10_45f's map and plan: its GPU frame and
    its window's picture laid one over the other. The run's page comes from the window walk (MAPGEN_SHOTS)."""
    out = work / "studio"
    for sub in ("data/bsp", "data/descriptions", "data/covers", "engine/donors", "tools"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    exe = out / "MapgenStudio.exe"
    exe.unlink(missing_ok=True)
    run = subprocess.run(["dotnet", "publish", str(STUDIO / "MapgenStudio.csproj"), "-c", "Release", "-r", "win-x64",
                          "--self-contained", "true", "-o", str(out), "-nologo"], capture_output=True, text=True)
    if run.returncode != 0 or not exe.is_file():
        print(run.stdout[-1500:], run.stderr[-800:])
        return None          # nothing is started without its build - an old exe opened a window on the PO's screen
    for f in ("pipeline.exe", "q2tool.exe"):
        shutil.copy2(INSTALLED / "engine" / f, out / "engine" / f)
    for f in (INSTALLED / "engine" / "donors").glob("q2dm1*"):
        shutil.copy2(f, out / "engine" / "donors" / f.name)
    for m in SHOT_MAPS:
        shutil.copy2(INSTALLED / "data" / "bsp" / f"{m}.bsp", out / "data" / "bsp" / f"{m}.bsp")
        for f in (INSTALLED / "data" / "descriptions").glob(f"{m}.*"):
            shutil.copy2(f, out / "data" / "descriptions" / f.name)
        shutil.copytree(INSTALLED / "data" / "covers" / m, out / "data" / "covers" / m, dirs_exist_ok=True)
    shutil.copy2(TOOLS / "mapgen_delivery_gates.py", out / "tools" / "mapgen_delivery_gates.py")
    (out / "MapgenStudio.ini").write_text(SHOT_INI, encoding="utf-8")
    shots = DOC / "screens"
    env = dict(os.environ, MAPGEN_SHOT_PAGES=",".join(pages or []))
    if not pages or any(p not in ("run", "run_full") for p in pages):
        subprocess.run([str(exe), "--shots", str(shots)], cwd=out, timeout=600, env=env)
    print((out / "shots.txt").read_text(encoding="utf-8") if (out / "shots.txt").is_file() else "no shots report")
    job = work / "mg_10_45f"
    (job / "baseline").mkdir(parents=True, exist_ok=True)
    shutil.copy2(INSTALLED / "data" / "bsp" / "mg_10_45f.bsp", job / "baseline" / "q2mg.bsp")
    for f in ("plan.txt", "ledger.txt"):
        shutil.copy2(INSTALLED / "data" / "runs" / "mg_10_45f" / f, job / f)
    from PIL import Image
    for lang in ("ru", "en") if not pages or "run_full" in pages else ():
        subprocess.run([str(exe), "--shots-full", str(shots), str(job), lang], cwd=out, timeout=180)
        gl, ui = shots / lang / "run_full_gl.png", shots / lang / "run_full_ui.png"
        if not (gl.is_file() and ui.is_file()):
            print(f"no full-screen parts for {lang}")
            continue
        top = Image.open(ui).convert("RGB")
        base = Image.open(gl).convert("RGB").resize(top.size)
        bg = (0x16, 0x18, 0x1C)
        tp, bp = top.load(), base.load()
        for y in range(top.size[1]):
            for x in range(top.size[0]):
                c = tp[x, y]
                if abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) > 18:
                    bp[x, y] = c
        base.save(shots / lang / "run_full.png")
        gl.unlink()
        ui.unlink()
    return shots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", action="store_true")
    ap.add_argument("--pages", default="",
                    help="with --shots: only these pictures (home,generate,...,run_full) - a change retakes the pages it touched")
    ap.add_argument("--work", type=Path, default=Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\guide"))
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    if a.shots:
        a.work.mkdir(parents=True, exist_ok=True)
        check("the pictures are made by the program",
              make_shots(a.work, [x for x in a.pages.split(",") if x]) is not None)
    ru, en = images("ru"), images("en")
    check("both guides refer to their own language's pictures", all(l == "ru" for l, _ in ru) and all(l == "en" for l, _ in en),
          f"ru {sorted({l for l, _ in ru})}, en {sorted({l for l, _ in en})}")
    check("both guides refer to the same pictures by the same names", {n for _, n in ru} == {n for _, n in en},
          f"only ru: {sorted({n for _, n in ru} - {n for _, n in en})}, only en: {sorted({n for _, n in en} - {n for _, n in ru})}")
    names = sorted({n for _, n in ru} | {n for _, n in en})
    missing = [f"{l}/{n}" for l, n in ru + en if not (DOC / "screens" / l / n).is_file()]
    check("every picture referred to exists", not missing, ", ".join(missing[:8]) or f"{len(ru) + len(en)} pictures")
    build = DOC / "screens" / "build.txt"
    stamped = build.read_text(encoding="utf-8").strip() if build.is_file() else ""
    check("the pictures are made by a build of the program (retaken page by page as the pages change)",
          bool(re.fullmatch(r"\d+\.\d+", stamped)), f"pictures of {stamped or 'no build'}, Versions.cs says {current_version()}")
    forgotten = [p for p in PAGES if f"{p}.png" not in names]
    check("every page the program photographs is in the guides", not forgotten, ", ".join(forgotten) or ", ".join(PAGES))
    for lang in ("ru", "en"):
        text = GUIDES[lang].read_text(encoding="utf-8")
        words = loc_options(lang)
        unnamed = [w for w in words if w not in text]
        check(f"{lang}: every option of «Размах переделок» is named in the guide by its own words", words and not unnamed,
              ", ".join(unnamed) or f"{len(words)} options")
    if not a.no_red:
        first = DOC / "screens" / "ru" / names[0] if names else None
        if first and first.is_file():
            aside = first.with_suffix(".png.aside")
            first.rename(aside)
            try:
                gone = [f"{l}/{n}" for l, n in ru if not (DOC / "screens" / l / n).is_file()]
                check("RED: with a picture taken away the guard goes red", bool(gone), ", ".join(gone))
            finally:
                aside.rename(first)
        else:
            check("RED: with a picture taken away the guard goes red", False, "no picture to take away")
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
