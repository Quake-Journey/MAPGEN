r"""The public MAPGEN repository (Fable's brief 10, D2): https://github.com/Quake-Journey/MAPGEN.

    python tools/mapgen_github_sync.py prepare [--export DIR]      # the tree, the scan, a local commit - nothing sent
    python tools/mapgen_github_sync.py push    [--export DIR]      # the repository made if missing, a plain push

One way, local -> GitHub: an owned clone (EXPORT) receives the SCOPED paths of this tree - the generator's sources and
the few engine files it is built with, its tools and checks, the Studio's sources, the guide - and nothing else: no
map (`.bsp`, id Software's and others' maps are not ours to give), no `_agent_temp`, no reports, inboxes or memory,
no settings. README, LICENSE (the project's GPL-2.0), THIRD_PARTY, BUILD and the change log in both languages
(`CHANGELOG.ru.md` / `CHANGELOG.en.md`, from the Studio's `Versions.cs`, the newest on top - the Studio's update check
reads them) are written by this tool. Each sync is one snapshot commit named after the Studio's version; history on
GitHub is appended, never forced. Before the commit the outgoing tree is scanned (Codex's pinned gitleaks with the
cloud_backup rules when present, and this tool's own patterns); a finding stops it. GitHub access is the machine's
Git Credential Manager - no token is read, printed or stored by this tool except to call the API in memory.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
OWNER, NAME = "Quake-Journey", "MAPGEN"
URL = f"https://github.com/{OWNER}/{NAME}.git"
EXPORT = Path(r"O:\Claude2\_agent_temp\claude\mapgen_github\MAPGEN")
GITLEAKS = Path(r"O:\Claude2\_agent_temp\codex\github-beta11-20261004\tools\gitleaks.exe")
GITLEAKS_RULES = Path(r"O:\Claude2\q2pro\tools\cloud_backup\gitleaks.toml")     # Codex's rules, in the main checkout
STUDIO = REPO / "tools" / "mapgen_studio" / "MapgenStudio"

# what goes out (globs from the tree's root); the generator's own include closure is added by `scope()`
INCLUDE = [
    "src/mapgen/*", "inc/common/mapgen_*.h",
    "tools/mapgen_*.py", "tools/mapgen_*.c", "tools/check_mapgen_*.py", "tools/mapgen_host_stubs.c",
    "tools/build_pinned_compiler.py", "tools/validate_q2prox_docx.py",
    "tools/mapgen_studio/**",
    "doc/mapgen_studio/**",
]
EXCLUDE = ["**/bin/**", "**/obj/**", "**/*.bsp", "**/*.bak", "**/__pycache__/**", "**/*.pyc", "**/.vs/**",
           "**/*.user", "**/*.ini", "**/*.exe", "**/*.dll", "**/*.pdb"]
SECRET = re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}"
                    rb"|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abp]-[A-Za-z0-9-]{10,}")


def git(*args: str, cwd: Path, check: bool = True) -> str:
    run = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and run.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {run.stderr.strip()[-600:]}")
    return run.stdout


def scope() -> list[str]:
    """The paths that go out: INCLUDE less EXCLUDE, plus every file the generator's C sources include."""
    tracked = git("ls-files", cwd=REPO).splitlines()
    out = {p for p in tracked
           if any(fnmatch.fnmatch(p, g) for g in INCLUDE) and not any(fnmatch.fnmatch(p, g) for g in EXCLUDE)}
    todo = [p for p in out if p.endswith((".c", ".h"))]
    roots = [REPO / "inc", REPO / "src" / "mapgen", REPO / "src"]
    while todo:
        f = REPO / todo.pop()
        text = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
        for m in re.finditer(r'#\s*include\s*"([^"]+)"', text):
            for base in [f.parent, *roots]:
                hit = (base / m.group(1)).resolve()
                if hit.is_file() and REPO.resolve() in hit.parents:
                    rel = hit.relative_to(REPO.resolve()).as_posix()
                    if rel not in out and rel in tracked:
                        out.add(rel)
                        todo.append(rel)
                    break
    # the C sources the build lists name but do not include (pmove's .c, the shared .c)
    for extra in ("src/shared/shared.c", "src/common/q2prox_cpu_topology.c", "src/common/pmove/common.c",
                  "src/common/pmove/old.c", "src/common/pmove/template.c"):
        if extra in tracked:
            out.add(extra)
    return sorted(out)


def changelog(lang: str) -> str:
    """The Studio's history (Versions.cs) as Markdown, the newest on top - one `## <version> — <date>` per version."""
    text = (STUDIO / "Versions.cs").read_text(encoding="utf-8")
    entries = re.findall(r'new\("([\d.]+)", "([\d.]+)",\s*new\[\]\s*\{(.*?)\},\s*new\[\]\s*\{(.*?)\}\)', text, re.S)
    title = "# MAPGEN Studio by ly — история версий" if lang == "ru" else "# MAPGEN Studio by ly — change log"
    lines = [title, ""]
    for number, date, ru, en in entries:
        lines.append(f"## {number} — {date}")
        lines.append("")
        for item in re.findall(r'"((?:[^"\\]|\\.)*)"', ru if lang == "ru" else en):
            lines.append("- " + item.replace('\\"', '"'))
        lines.append("")
    return "\n".join(lines)


def current_version() -> str:
    m = re.search(r'new\("([\d.]+)", "', (STUDIO / "Versions.cs").read_text(encoding="utf-8"))
    return m.group(1) if m else "0.0"


README = """# MAPGEN by ly

**MAPGEN** remakes an existing Quake II map into a new one: it digs passages through the rock, carries rooms over from
another map, floods low ground, changes the finish, moves items — and checks that the new map can be walked, is lit
and has nothing broken. **MAPGEN Studio** is its Windows program.

- Download: the latest build is in [Releases](https://github.com/Quake-Journey/MAPGEN/releases) — unpack the zip and
  start `MapgenStudio.exe`. You need Quake II (any client with its `baseq2`); Python 3.10+ for the map checks (the
  Studio offers to install it). No maps are shipped: add any Quake II `.bsp` of your game as a base.
- Guide: [English](doc/mapgen_studio/MAPGEN_Studio_Guide_EN.md) · [Русский](doc/mapgen_studio/MAPGEN_Studio_Guide_RU.md)
- Changes: [CHANGELOG.en.md](CHANGELOG.en.md) · [CHANGELOG.ru.md](CHANGELOG.ru.md)
- Building from source: [BUILD.md](BUILD.md)

---

**MAPGEN** переделывает готовую карту Quake II в новую: прокладывает проходы в скале, переносит комнаты из другой
карты, заливает низины, меняет отделку, переставляет предметы — и проверяет, что по новой карте можно пройти, что
она освещена и в ней ничего не сломано. **MAPGEN Studio** — программа для Windows.

- Скачать: свежая сборка в [Releases](https://github.com/Quake-Journey/MAPGEN/releases) — распакуйте архив и
  запустите `MapgenStudio.exe`. Нужен Quake II (любой клиент с папкой `baseq2`) и Python 3.10+ для проверок карт
  (студия сама предложит его установить). Карты не входят в сборку: основой можно взять любую карту `.bsp` вашей игры.
- Руководство: [Русский](doc/mapgen_studio/MAPGEN_Studio_Guide_RU.md) · [English](doc/mapgen_studio/MAPGEN_Studio_Guide_EN.md)
- Изменения: [CHANGELOG.ru.md](CHANGELOG.ru.md) · [CHANGELOG.en.md](CHANGELOG.en.md)

This repository is published one way from the authors' working tree; changes made here directly are not taken back.
"""

BUILD = """# Building MAPGEN from source

## The generator (`pipeline.exe`)

MinGW-w64 GCC (C17) and zlib. From the repository's root:

```
python -c "import sys; sys.path.insert(0, 'tools'); from pathlib import Path; from check_mapgen_pipeline import build; print(build(Path('build')))"
```

`tools/check_mapgen_pipeline.py` lists the sources (`SOURCES`) and the flags.

## The map compiler (`q2tool.exe`)

The generator compiles maps with a pinned, patched build of q2tools-220 (GPL-2.0): `tools/build_pinned_compiler.py`
with the patches `tools/mapgen_patch_*.py`; `tools/mapgen_pinned_compiler.py` names the qualified build.

## MAPGEN Studio

.NET 10 SDK:

```
dotnet publish tools/mapgen_studio/MapgenStudio/MapgenStudio.csproj -c Release -r win-x64 --self-contained true -o out
```

Put `engine/pipeline.exe` and `engine/q2tool.exe` beside `MapgenStudio.exe`, and the `tools/` scripts the map checks
use in `tools/` beside it.

## The guide

`tools/check_mapgen_studio_guide.py --shots` retakes the screenshots from the current build;
`tools/mapgen_studio_guide_docx.py` and `tools/mapgen_studio_guide_html.py` make the DOCX and HTML.
"""

THIRD_PARTY = """# Third-party parts

- **Q2PRO** (GPL-2.0) — the engine files the generator is built with (`inc/shared`, `src/shared`, `src/common/pmove`,
  `inc/common/pmove.h`): player movement for the reachability walk, shared definitions.
- **q2tools-220** (GPL-2.0) — the map compiler the generator runs; this repository holds the patches applied to it
  (`tools/mapgen_patch_*.py`) and the build script.
- **Avalonia**, **FluentAvalonia**, **.NET** — the Studio's UI framework and runtime (MIT).
- No map is distributed. Quake II and its maps are id Software's.
"""

GITIGNORE = """bin/
obj/
*.user
*.bsp
*.exe
*.dll
__pycache__/
"""


def prepare(export: Path) -> dict:
    if git("status", "--porcelain", cwd=REPO).strip():
        raise SystemExit("the working tree has uncommitted changes - commit them first: the export is a commit's")
    head = git("rev-parse", "--short", "HEAD", cwd=REPO).strip()
    if not (export / ".git").is_dir():
        export.parent.mkdir(parents=True, exist_ok=True)
        probe = subprocess.run(["git", "ls-remote", URL], capture_output=True, text=True)
        if probe.returncode == 0 and probe.stdout.strip():
            git("clone", URL, str(export), cwd=export.parent)
        else:
            export.mkdir(parents=True, exist_ok=True)
            git("init", "-b", "main", cwd=export)
            git("remote", "add", "origin", URL, cwd=export)
    # the tree is the scope exactly: everything else in the export goes
    for p in sorted(export.rglob("*"), reverse=True):
        rel = p.relative_to(export).as_posix()
        if rel.startswith(".git"):
            continue
        if p.is_file():
            p.unlink()
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    files = scope()
    for rel in files:
        dest = export / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dest)
    (export / "README.md").write_text(README, encoding="utf-8")
    (export / "BUILD.md").write_text(BUILD, encoding="utf-8")
    (export / "THIRD_PARTY.md").write_text(THIRD_PARTY, encoding="utf-8")
    (export / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (export / "CHANGELOG.ru.md").write_text(changelog("ru"), encoding="utf-8")
    (export / "CHANGELOG.en.md").write_text(changelog("en"), encoding="utf-8")
    shutil.copy2(REPO / "LICENSE", export / "LICENSE")
    # the scan: no map, no secret, nothing from the agents' folders
    bad = []
    for p in export.rglob("*"):
        if ".git" in p.relative_to(export).parts or not p.is_file():
            continue
        rel = p.relative_to(export).as_posix()
        if p.suffix.lower() in (".bsp", ".pak", ".ini", ".exe", ".dll"):
            bad.append(f"{rel}: a {p.suffix} file")
        if SECRET.search(p.read_bytes()):
            bad.append(f"{rel}: looks like a secret")
    if GITLEAKS.is_file() and GITLEAKS_RULES.is_file():
        report = export.parent / "gitleaks.json"
        run = subprocess.run([str(GITLEAKS), "dir", str(export), "--config", str(GITLEAKS_RULES), "--redact",
                              "--no-banner", "--no-color", "--report-format", "json", "--report-path", str(report)],
                             capture_output=True, text=True)
        if run.returncode != 0:
            found = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else []
            bad += [f"gitleaks: {f.get('File')} {f.get('RuleID')}" for f in found] or ["gitleaks failed to run"]
    if bad:
        raise SystemExit("the outgoing tree is refused:\n  " + "\n  ".join(bad[:30]))
    git("add", "--all", cwd=export)
    version = current_version()
    changed = git("status", "--porcelain", cwd=export).strip()
    if changed:
        git("-c", "user.name=Quake-Journey", "-c", "user.email=noreply@github.com", "commit", "-q", "-m",
            f"MAPGEN Studio {version} (source {head})\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
            cwd=export)
    said = {"version": version, "source": head, "files": len(files), "changed": bool(changed),
            "scanned_with_gitleaks": GITLEAKS.is_file() and GITLEAKS_RULES.is_file()}
    print(json.dumps(said))
    return said


def api(method: str, path: str, body: dict | None = None) -> dict:
    """GitHub's REST API with the machine's Git credential (in memory only)."""
    fill = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                          capture_output=True, text=True)
    token = dict(l.split("=", 1) for l in fill.stdout.splitlines() if "=" in l).get("password", "")
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token, "User-Agent": "mapgen-sync",
                                          "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"_status": 404}
        raise SystemExit(f"GitHub {method} {path}: {e.code} {e.read()[:300]!r}")


def push(export: Path) -> None:
    repo = api("GET", f"/repos/{OWNER}/{NAME}")
    if repo.get("_status") == 404:
        repo = api("POST", f"/orgs/{OWNER}/repos", {
            "name": NAME, "private": False, "has_wiki": False, "has_projects": False,
            "description": "MAPGEN by ly: remakes Quake II maps - the generator and MAPGEN Studio",
        })
        print("created", repo.get("html_url"))
    if repo.get("private"):
        raise SystemExit("the repository is private - this tool publishes the public one only")
    api("PATCH", f"/repos/{OWNER}/{NAME}", {"description": "MAPGEN by ly: remakes Quake II maps - the generator and MAPGEN Studio"})
    api("PUT", f"/repos/{OWNER}/{NAME}/actions/permissions", {"enabled": False})
    git("push", "origin", "main", cwd=export)       # never --force
    print("pushed", git("rev-parse", "--short", "HEAD", cwd=export).strip(), "to", URL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["prepare", "push"])
    ap.add_argument("--export", type=Path, default=EXPORT)
    a = ap.parse_args()
    if a.what == "prepare":
        prepare(a.export)
    else:
        push(a.export)
    return 0


if __name__ == "__main__":
    sys.exit(main())
