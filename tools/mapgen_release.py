r"""A MAPGEN Studio release (Fable's brief 10, D2): a zip that works on its own for whoever downloads it.

    python tools/mapgen_release.py build   [--out DIR]     # the folder and the zip, nothing sent
    python tools/mapgen_release.py publish [--out DIR]     # the GitHub release v<version> with the zip and SHA256SUMS

`MapgenStudio-<version>-win-x64.zip` holds:
* `MapgenStudio.exe` - the Studio, self-contained;
* `engine/` - `pipeline.exe` (the generator), `q2tool.exe` (the pinned map compiler), `helpers/` (the five programs the
  map checks run and the destroy driver, BUILT here - a user has no C compiler), `textures/mapgen` (the generator's
  texture pack, brief 11 D3: game-format pairs, catalogue, masks), an empty `donors/` (no map is ours to give: the
  user adds any Quake II .bsp of his game);
* `tools/` - the Python scripts the map checks run and the data they read, nothing else of the tree;
* the guide (RU/EN, Markdown + DOCX + HTML, its pictures), `CHANGELOG.ru.md` / `CHANGELOG.en.md`, LICENSE,
  THIRD_PARTY.md.
`SHA256SUMS` beside the zip. The Studio finds its checks in `tools/` and passes `engine/helpers` and its own
`q2tool.exe` to them (MAPGEN_HELPERS, MAPGEN_Q2TOOL).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
STUDIO = TOOLS / "mapgen_studio" / "MapgenStudio"
OUT = Path(r"O:\Claude2\_agent_temp\claude\mapgen_release")
ROOTS = ["mapgen_delivery_gates.py", "mapgen_room_light.py", "mapgen_light_autofit.py", "mapgen_destroy.py"]


def version() -> str:
    m = re.search(r'new\("([\d.]+)", "', (STUDIO / "Versions.cs").read_text(encoding="utf-8"))
    return m.group(1)


def script_closure() -> list[str]:
    """The tools/*.py the checks import, from their roots, and every tools/*.json they name."""
    seen, todo = set(), list(ROOTS)
    while todo:
        n = todo.pop()
        if n in seen or not (TOOLS / n).is_file():
            continue
        seen.add(n)
        text = (TOOLS / n).read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"^\s*(?:from\s+([A-Za-z_]\w*)\s+import|import\s+([A-Za-z_]\w*))", text, re.M):
            mod = m.group(1) or m.group(2)
            if (TOOLS / f"{mod}.py").is_file():
                todo.append(f"{mod}.py")
        # and the scripts they RUN by name (`TOOLS / "check_mapgen_delivery.py"`): the first fresh unpacking failed
        # «finished» and «axes» on exactly these two, missing
        for m in re.finditer(r'"((?:check_)?mapgen_\w+\.py)"', text):
            if (TOOLS / m.group(1)).is_file():
                todo.append(m.group(1))
        for m in re.finditer(r'"([\w.-]+\.json)"', text):
            if (TOOLS / m.group(1)).is_file():
                seen.add(m.group(1))
    return sorted(seen)


def helpers(into: Path) -> None:
    """The five programs the checks run, built from this tree into engine/helpers under the names they look for."""
    into.mkdir(parents=True, exist_ok=True)
    from check_mapgen_lost_pickup import build as build_lost
    from check_mapgen_recut import build_driver
    from check_mapgen_visgate import build as build_vis
    from check_mapgen_standing_water import build as build_water, PROBE_SRC
    from check_mapgen_reach_gate import build_gate
    work = into.parent / "_helpers_build"
    work.mkdir(parents=True, exist_ok=True)
    if build_lost(REPO, into / "lost_pickup_oracle.exe"):
        raise SystemExit("the lost-pickup oracle did not build")
    if build_vis(REPO, into / "visgate_oracle.exe"):
        raise SystemExit("the visibility oracle did not build")
    shutil.copy2(build_driver(REPO, work), into / "recut_driver.exe")
    shutil.copy2(build_water(REPO, work, "water_probe", PROBE_SRC), into / "water_probe.exe")
    shutil.copy2(build_gate(work), into / "reach_gate.exe")
    # brief 11 D2: the destruction driver (it also draws the cracked textures - no numpy or Pillow at the user's)
    from mapgen_destroy import driver as build_destroy
    saved = os.environ.pop("MAPGEN_HELPERS", None)
    try:
        shutil.copy2(build_destroy(work), into / "destroy_driver.exe")
    finally:
        if saved is not None:
            os.environ["MAPGEN_HELPERS"] = saved
    shutil.rmtree(work, ignore_errors=True)


def build(out: Path) -> Path:
    from check_mapgen_pipeline import build as build_pipeline
    from mapgen_pinned_compiler import pinned_compiler
    from mapgen_github_sync import changelog, THIRD_PARTY
    v = version()
    stage = out / f"MapgenStudio-{v}"
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "engine" / "donors").mkdir(parents=True)
    run = subprocess.run(["dotnet", "publish", str(STUDIO / "MapgenStudio.csproj"), "-c", "Release", "-r", "win-x64",
                          "--self-contained", "true", "-o", str(out / "_studio"), "-nologo"], capture_output=True, text=True)
    exe = out / "_studio" / "MapgenStudio.exe"
    if run.returncode != 0 or not exe.is_file():
        raise SystemExit("the Studio did not build:\n" + run.stdout[-1500:])
    shutil.copy2(exe, stage / "MapgenStudio.exe")
    shutil.rmtree(out / "_studio", ignore_errors=True)
    pipe = build_pipeline(out / "_pipeline")
    if not pipe:
        raise SystemExit("the generator did not build")
    shutil.copy2(pipe, stage / "engine" / "pipeline.exe")
    shutil.rmtree(out / "_pipeline", ignore_errors=True)
    shutil.copy2(pinned_compiler()[0], stage / "engine" / "q2tool.exe")
    (stage / "engine" / "donors" / "README.txt").write_text(
        "Base maps go here. MAPGEN Studio ships no map: on the Generate page press «Choose maps…» (Выбрать карты…) and\n"
        "pick any Quake II .bsp of your game - it is copied here.\n", encoding="utf-8")
    helpers(stage / "engine" / "helpers")
    # brief 11 D3: the texture pack, as built (tools/mapgen_textures.py build): the destroyed maps wear it
    from mapgen_destroy import PACK
    pack = PACK / "textures" / "mapgen"
    if not (pack / "catalogue.json").is_file():
        raise SystemExit(f"no texture pack at {pack}: python tools/mapgen_textures.py build")
    shutil.copytree(pack, stage / "engine" / "textures" / "mapgen",
                    ignore=shutil.ignore_patterns("*.png"))       # the masks' pictures: their .raw is what is drawn
    (stage / "tools").mkdir()
    for n in script_closure():
        shutil.copy2(TOOLS / n, stage / "tools" / n)
    doc = stage / "doc"
    shutil.copytree(REPO / "doc" / "mapgen_studio", doc, ignore=shutil.ignore_patterns("*.tmp"))
    for lang in ("ru", "en"):
        (stage / f"CHANGELOG.{lang}.md").write_text(changelog(lang), encoding="utf-8")
    shutil.copy2(REPO / "LICENSE", stage / "LICENSE.txt")
    (stage / "THIRD_PARTY.md").write_text(THIRD_PARTY, encoding="utf-8")
    zip_path = out / f"MapgenStudio-{v}-win-x64.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, Path(stage.name) / p.relative_to(stage))
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (out / "SHA256SUMS").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    print(json.dumps({"version": v, "zip": str(zip_path), "mb": round(zip_path.stat().st_size / 2**20, 1),
                      "sha256": digest, "tools": len(script_closure())}))
    return zip_path


def publish(out: Path) -> None:
    from mapgen_github_sync import api, changelog, OWNER, NAME
    v = version()
    zip_path = out / f"MapgenStudio-{v}-win-x64.zip"
    sums = out / "SHA256SUMS"
    if not zip_path.is_file() or not sums.is_file():
        raise SystemExit("build first")
    def part(lang: str) -> str:
        text = changelog(lang)
        m = re.search(rf"^## {re.escape(v)} .*?(?=^## |\Z)", text, re.M | re.S)
        return m.group(0).strip() if m else ""
    body = part("ru") + "\n\n---\n\n" + part("en")
    tag = f"v{v}"
    rel = api("GET", f"/repos/{OWNER}/{NAME}/releases/tags/{tag}")
    if rel.get("_status") == 404:
        rel = api("POST", f"/repos/{OWNER}/{NAME}/releases",
                  {"tag_name": tag, "target_commitish": "main", "name": f"MAPGEN Studio {v} by ly", "body": body})
    names = {a["name"] for a in rel.get("assets", [])}
    fill = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                          capture_output=True, text=True)
    token = dict(l.split("=", 1) for l in fill.stdout.splitlines() if "=" in l).get("password", "")
    for f, kind in ((zip_path, "application/zip"), (sums, "text/plain")):
        if f.name in names:
            print("already there:", f.name)
            continue
        req = urllib.request.Request(
            f"https://uploads.github.com/repos/{OWNER}/{NAME}/releases/{rel['id']}/assets?name={f.name}",
            data=f.read_bytes(), method="POST",
            headers={"Authorization": "Bearer " + token, "Content-Type": kind, "User-Agent": "mapgen-release"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            print("uploaded", json.load(r)["browser_download_url"])
    print(rel.get("html_url"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["build", "publish"])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    build(a.out) if a.what == "build" else publish(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
