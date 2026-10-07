r"""The game folder of a run is the run's (Fable's brief 13 W1).

The light tools (`mapgen_room_light.py`, `mapgen_light_fit.py`, `mapgen_light_profile.py`, `mapgen_light_calibrate.py`)
and several checks had the PO's own `O:\Claude2\q2pro-release\baseq2` hard-wired: off his machine the released Studio's
light step lit nothing it could read. Now every released script takes `mapgen_load_guard.game_dir()` - MAPGEN_GAME,
which the Studio sets from its client folder and the flow tool from --game. Asserted:
* no released script (the release's own closure, `mapgen_release.script_closure`) names `q2pro-release` but the one
  fallback in `mapgen_load_guard.py`;
* with MAPGEN_GAME set to another game folder (a scratch baseq2 whose paks and palette are hard links of the real
  ones - nothing copied), the room light's relight and the light fit's light-only pass run the light compiler with
  that folder as its moddir, basedir and gamedir (the compiler's own rad.log says so), and the map comes out lit.
RED, two, in a sandbox copy: the room light's GAME put back to the literal - its rad.log names the PO's folder; a
literal put into a released script - the scan finds it.

    python tools/check_mapgen_game_path.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

REPO = TOOLS.parent
REAL = Path(r"O:\Claude2\q2pro-release\baseq2")
MAP = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\fixtures\gen_q2dm1_20_42.bsp")
DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen_studio\MapgenStudio\engine\donors\q2dm1.bsp")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\game_path")
LITERAL = "q2pro-release"
FAILED = TOTAL = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED, TOTAL
    TOTAL += 1
    FAILED += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def scan(tools: Path) -> list[str]:
    """The released scripts that name the PO's folder (the load guard's one fallback aside)."""
    sys.path.insert(0, str(tools))
    import mapgen_release
    found = []
    for name in mapgen_release.script_closure():
        p = tools / Path(name).name
        if p.suffix != ".py" or not p.is_file():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if LITERAL in line and not (p.name == "mapgen_load_guard.py" and line.startswith("GAME_DEFAULT")):
                found.append(f"{p.name}:{n}")
    return found


def scratch_game(at: Path) -> Path:
    """A baseq2 of hard links: the real paks and palette, nothing copied (one volume)."""
    game = at / "baseq2"
    if game.exists():
        shutil.rmtree(game)
    (game / "pics").mkdir(parents=True)
    for pak in REAL.glob("*.pak"):
        os.link(pak, game / pak.name)
    pcx = REAL / "pics" / "colormap.pcx"
    if pcx.is_file():
        os.link(pcx, game / "pics" / "colormap.pcx")
    return game


def dirs_of(log: Path) -> dict:
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    return {k: v.strip().rstrip("\\/") for k, v in re.findall(r"^(moddir|basedir|gamedir)\s*=\s*(.+)$", text, re.M)}


def room_light(tools: Path, game: Path, work: Path) -> dict:
    """The room light's relight on a copy of a generated map, under MAPGEN_GAME: the light compiler's folders."""
    work.mkdir(parents=True, exist_ok=True)
    bsp = work / "map.bsp"
    shutil.copy2(MAP, bsp)
    digs = work / "digs.json"
    digs.write_text("[]", encoding="utf-8")
    env = dict(os.environ, MAPGEN_GAME=str(game))
    r = subprocess.run([sys.executable, str(tools / "mapgen_room_light.py"), str(bsp), "--digs", str(digs), "--donor",
                        str(DONOR), "--work", str(work / "rl"), "--relight-first", "--rounds", "0"],
                       capture_output=True, text=True, errors="replace", env=env, timeout=3600)
    return {"rc": r.returncode, "dirs": dirs_of(work / "rl" / "relight" / "rad.log"), "tail": (r.stdout + r.stderr)[-300:]}


def light_fit(tools: Path, game: Path, work: Path) -> dict:
    """The light fit's light-only pass under MAPGEN_GAME."""
    work.mkdir(parents=True, exist_ok=True)
    code = ("import sys; sys.path.insert(0, r'%s'); from pathlib import Path; import mapgen_light_fit as f;"
            " from mapgen_light_calibrate import entity_text; raw = Path(r'%s').read_bytes();"
            " print(f.light_only(raw, entity_text(raw), {}, '-scale 1.0', Path(r'%s'), Path(r'%s'))[0])"
            % (tools, MAP, work / "lf", DONOR))
    env = dict(os.environ, MAPGEN_GAME=str(game))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, errors="replace", env=env,
                       timeout=3600)
    return {"rc": r.returncode, "dirs": dirs_of(work / "lf" / "rad.log"), "tail": (r.stdout + r.stderr)[-300:]}


def under(dirs: dict, game: Path) -> bool:
    want = str(game).rstrip("\\/").lower()
    return len(dirs) == 3 and all(v.lower() == want for v in dirs.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--no-red", action="store_true")
    a = ap.parse_args()
    if a.work.exists():
        shutil.rmtree(a.work)
    a.work.mkdir(parents=True)
    found = scan(TOOLS)
    check("no released script names the PO's game folder but the load guard's fallback", not found, ", ".join(found))
    game = scratch_game(a.work / "game")
    rl = room_light(TOOLS, game, a.work / "green")
    check("the room light lights under MAPGEN_GAME (the compiler's moddir, basedir, gamedir)",
          rl["rc"] == 0 and under(rl["dirs"], game), f"{rl['dirs']}" + (f" rc {rl['rc']}: {rl['tail']}" if rl["rc"] else ""))
    lf = light_fit(TOOLS, game, a.work / "green")
    check("the light fit's light-only pass lights under MAPGEN_GAME", lf["rc"] == 0 and under(lf["dirs"], game),
          f"{lf['dirs']}" + (f" rc {lf['rc']}: {lf['tail']}" if lf["rc"] else ""))
    if not a.no_red:
        before = hash_tree(REPO)
        box = Sandbox(REPO, "game_path")
        try:
            target = box.root / "tools" / "mapgen_room_light.py"
            data = target.read_bytes()
            line = b"GAME = game_dir()"
            if check("RED: the room light's game folder is where the mutation says", data.count(line) == 1):
                target.write_bytes(data.replace(line, b'GAME = r"O:\\Claude2\\q2pro-release\\baseq2"', 1))
                red = room_light(box.root / "tools", game, a.work / "red")
                check("RED: hard-wired again, its light names the PO's folder - the case above goes red",
                      bool(red["dirs"]) and not under(red["dirs"], game), str(red["dirs"]))
                check("RED: and the scan finds the literal", any(f.startswith("mapgen_room_light.py")
                                                                for f in scan(box.root / "tools")))
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    shutil.rmtree(a.work / "game", ignore_errors=True)
    print(f"{TOTAL - FAILED}/{TOTAL} passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
