r"""The Studio's update, end to end, offline (Fable's brief 10, D3).

A local HTTP server (127.0.0.1) stands for GitHub: `CHANGELOG.ru.md` / `CHANGELOG.en.md` and
`releases/download/v<V>/MapgenStudio-<V>-win-x64.zip` + `SHA256SUMS`. The Studio built from this tree is installed in
a folder of its own with the user's things beside it (data/, its settings, a donor) and pointed at the server by the
hidden `update_url`; `MapgenStudio.exe --update-test` checks and says «Да» without a window; the updater it hands
over to replaces the program and keeps the user's things - with no restart (MAPGEN_UPDATE_NO_RESTART: nothing opens
on the PO's screen).
* nothing newer on the server: «latest», nothing downloaded;
* a newer version: handed over; the program's files replaced (engine, tools, the change logs), the old program kept
  as MapgenStudio.previous.exe, data/, the settings and the user's donors untouched, the «what's new» note written;
* a wrong SHA-256: refused, the installation untouched.
RED (a sandbox build with the checksum's comparison taken out): the wrong zip is applied - the case above goes red.

    python tools/check_mapgen_studio_update.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from mapgen_red_sandbox import hash_tree  # noqa: E402

STUDIO = Path("tools") / "mapgen_studio" / "MapgenStudio" / "MapgenStudio.csproj"
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\update_guard")
NEW = "9.9"
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def publish(project: Path, out: Path) -> Path:
    shutil.rmtree(out, ignore_errors=True)
    run = subprocess.run(["dotnet", "publish", str(project), "-c", "Release", "-r", "win-x64", "--self-contained",
                          "true", "-o", str(out), "-nologo"], capture_output=True, text=True)
    exe = out / "MapgenStudio.exe"
    if run.returncode != 0 or not exe.is_file():
        raise SystemExit("the Studio did not build:\n" + run.stdout[-1500:])
    return exe


def serve(root: Path) -> tuple[socketserver.TCPServer, int]:
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **k)  # noqa: E731
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def release(server: Path, exe: Path, top: str, wrong_sum: bool = False) -> None:
    """The server's tree: the change logs with `top` as the newest, and release v9.9's zip and sums."""
    shutil.rmtree(server, ignore_errors=True)
    server.mkdir(parents=True)
    for lang in ("ru", "en"):
        (server / f"CHANGELOG.{lang}.md").write_text(
            f"# MAPGEN Studio\n\n## {top} — 01.01.2030\n\n- test line {lang}\n\n## 2.0 — 06.10.2026\n\n- older\n",
            encoding="utf-8")
    d = server / "releases" / "download" / f"v{NEW}"
    d.mkdir(parents=True)
    name = f"MapgenStudio-{NEW}-win-x64.zip"
    with zipfile.ZipFile(d / name, "w", zipfile.ZIP_DEFLATED) as z:
        base = f"MapgenStudio-{NEW}/"
        z.write(exe, base + "MapgenStudio.exe")
        z.writestr(base + "engine/pipeline.exe", b"NEW ENGINE")
        z.writestr(base + "engine/donors/README.txt", "add your maps here")
        z.writestr(base + "tools/marker_new.py", "# the new tools\n")
        z.writestr(base + "CHANGELOG.ru.md", "## 9.9\n")
    digest = hashlib.sha256((d / name).read_bytes()).hexdigest()
    if wrong_sum:
        digest = "0" * 64
    (d / "SHA256SUMS").write_text(f"{digest}  {name}\n", encoding="utf-8")


def install(folder: Path, exe: Path, port: int) -> None:
    """An installed Studio with the user's things beside it."""
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "engine" / "donors").mkdir(parents=True)
    (folder / "data").mkdir()
    (folder / "tools").mkdir()
    shutil.copy2(exe, folder / "MapgenStudio.exe")
    (folder / "engine" / "pipeline.exe").write_bytes(b"OLD ENGINE")
    (folder / "engine" / "donors" / "mine.bsp").write_bytes(b"IBSP-user-map")
    (folder / "tools" / "marker_old.py").write_text("# old\n", encoding="utf-8")
    (folder / "data" / "my_map.txt").write_text("the user's map\n", encoding="utf-8")
    (folder / "MapgenStudio.ini").write_text(
        f"[ui]\nlanguage=ru\n[folders]\ntemp=temp\nupdate_url=http://127.0.0.1:{port}\nupdate_check=1\n", encoding="utf-8")


def run_update(folder: Path) -> tuple[str, bool]:
    """The update test; True when the updater finished (its note written) within a minute."""
    env = dict(os.environ, MAPGEN_UPDATE_NO_RESTART="1")
    subprocess.run([str(folder / "MapgenStudio.exe"), "--update-test"], cwd=folder, env=env, timeout=300)
    said = (folder / "update_test.txt").read_text(encoding="utf-8") if (folder / "update_test.txt").is_file() else ""
    if "HANDED OVER" not in said:
        return said, False
    end = time.time() + 90
    while time.time() < end and not (folder / "update.txt").is_file():
        time.sleep(0.5)
    time.sleep(1.0)
    return said, (folder / "update.txt").is_file()


def cases(exe: Path, work: Path, tag: str) -> dict:
    server = work / f"{tag}_server"
    srv, port = serve(server)
    try:
        out = {}
        server.mkdir(parents=True, exist_ok=True)
        # nothing newer
        release(server, exe, top="0.1")
        f = work / f"{tag}_latest"
        install(f, exe, port)
        out["latest"] = run_update(f)[0]
        # newer, right sum
        release(server, exe, top=NEW)
        f = work / f"{tag}_newer"
        install(f, exe, port)
        said, done = run_update(f)
        out["newer"] = (said, done, f)
        # newer, wrong sum
        release(server, exe, top=NEW, wrong_sum=True)
        f = work / f"{tag}_badsum"
        install(f, exe, port)
        said, done = run_update(f)
        out["badsum"] = (said, done, f)
        return out
    finally:
        srv.shutdown()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    exe = publish(REPO / STUDIO, a.work / "green_build")
    g = cases(exe, a.work, "green")
    check("nothing newer on the server: the Studio says it is the latest, nothing downloaded",
          "LATEST" in g["latest"] and "HANDED OVER" not in g["latest"], g["latest"].strip().replace("\n", " | ")[:200])
    said, done, f = g["newer"]
    replaced = (f / "engine" / "pipeline.exe").read_bytes() == b"NEW ENGINE" if (f / "engine" / "pipeline.exe").is_file() else False
    check("a newer version: handed over to the new Studio, which finished", "HANDED OVER" in said and done,
          said.strip().replace("\n", " | ")[:220])
    check("the program's files are replaced: the engine, the tools, the change log",
          replaced and (f / "tools" / "marker_new.py").is_file() and not (f / "tools" / "marker_old.py").is_file()
          and (f / "CHANGELOG.ru.md").is_file(), f"engine new {replaced}")
    check("the user's things stay: data/, the settings, his donors; the old program kept as previous",
          (f / "data" / "my_map.txt").is_file() and "update_url" in (f / "MapgenStudio.ini").read_text(encoding="utf-8")
          and (f / "engine" / "donors" / "mine.bsp").is_file() and (f / "MapgenStudio.previous.exe").is_file())
    check("the «what's new» note names the version updated from",
          (f / "update.txt").is_file() and (f / "update.txt").read_text(encoding="utf-8").strip() not in ("", NEW))
    said, done, f = g["badsum"]
    check("a wrong checksum: refused, the installation untouched",
          "REFUSED" in said and (f / "engine" / "pipeline.exe").read_bytes() == b"OLD ENGINE"
          and not (f / "update.txt").is_file(), said.strip().replace("\n", " | ")[:200])
    if not a.no_red:
        before = hash_tree(REPO)
        red_src = a.work / "red_src"
        shutil.rmtree(red_src, ignore_errors=True)
        shutil.copytree(REPO / STUDIO.parent, red_src, ignore=shutil.ignore_patterns("bin", "obj"))
        try:
            target = red_src / "Update.cs"
            data = target.read_bytes()
            line = b"if (!got.Equals(want.Groups[1].Value, StringComparison.OrdinalIgnoreCase))"
            if check("RED: the checksum's comparison is where the mutation says", data.count(line) == 1):
                target.write_bytes(data.replace(line, b"if (false)", 1))
                red_exe = publish(red_src / STUDIO.name, a.work / "red_build")
                r = cases(red_exe, a.work, "red")
                said, done, f = r["badsum"]
                check("RED: with the comparison taken out, the wrong zip is applied - the case above goes red",
                      (f / "engine" / "pipeline.exe").read_bytes() == b"NEW ENGINE",
                      said.strip().replace("\n", " | ")[:160])
        finally:
            shutil.rmtree(red_src, ignore_errors=True)
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
