r"""Destruction of a finished map (Fable's brief 11 D2, ledger row 412l) - the Studio's «Разрушения», 0..100.

    python tools/mapgen_destroy.py MAP.bsp --donor DONOR.bsp --destruction D --seed S [--game BASEQ2] [--work DIR]
                                   [--flags "..."] [--pack DIR]

MAP.bsp (a finished map, lit, its gates passed) is put D percent in ruins and replaced in place:
1. the texture pack (`tools/mapgen_textures.py`) is installed into the game's `textures/mapgen` - the map wears it;
2. `mapgen_destroy_driver` reads the map, builds the ruin from the seed's own substream (the ladder of kinds:
   cracks, rubble, craters, breaches and gouges, broken edges, collapses, ruin) and writes its .map, with the list of
   the map's own textures it now wears cracked;
3. those cracked copies are drawn into the game's `textures/mgd` (same size, same palette, a crack mask of the pack);
4. the .map is compiled (bsp, vis) and lit by the light pass under the donor's own calibration (its flags, its sun);
5. a leak (never expected: every carve keeps 16 of the map's own brush round it) or a failed compile drops the kinds
   that carve, then all but the paint, and says so;
6. MAP.bsp is replaced; `MAP.destroyed.json` holds what was destroyed by kind, and `MAP.textures.txt` the textures of
   the pack and the cracked ones the map needs (they travel with it into the library and the game).
Prints `destroyed: ...` (the driver's counts) and `DESTRUCTION OK` or `DESTRUCTION FAILED <why>`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_light_calibrate import donor_light, entity_text  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

DESTROYED = re.compile(r"^destroyed: (.*)$", re.M)
DRAWN = re.compile(r"^cracks drawn: (\d+), (\d+) without", re.M)
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
PACK = Path(r"O:\Claude2\_agent_temp\claude\mapgen_textures\pack")       # the authors' build of the pack


def install(game: Path, pack: Path) -> None:
    """The pack into the game's textures/mapgen - plain copies, nothing to import: a user's Python may have neither
    numpy nor Pillow, and needs neither here (the cracks are drawn by the driver)."""
    src = pack / "textures" / "mapgen"
    dst = game / "textures" / "mapgen"
    n = 0
    for p in src.rglob("*"):
        if p.is_file() and p.suffix in (".wal", ".jpg", ".json"):
            q = dst / p.relative_to(src)
            if not q.is_file() or q.stat().st_size != p.stat().st_size:
                q.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, q)
                n += 1
    print(f"the pack: {n} files copied into {dst}", flush=True)
# carving kinds by bit (MapGenGeometryEdit_DestroySkip): craters 4, breaches 8, broken 16, collapses 32, ruin 64
# (rubble 2, patches 128: built, never carved)
CARVES = 4 | 8 | 16 | 32 | 64


def game_file(game: Path, name: str) -> bytes | None:
    """A file of the game, loose or in one of its paks."""
    import struct
    loose = game / name
    if loose.is_file():
        return loose.read_bytes()
    for pak in sorted(game.glob("*.pak")):
        d = pak.read_bytes()
        if d[:4] != b"PACK":
            continue
        off, size = struct.unpack_from("<ii", d, 4)
        for i in range(size // 64):
            n, fo, fs = struct.unpack_from("<56sii", d, off + 64 * i)
            if n.split(b"\0")[0].decode("latin1").lower() == name.lower():
                return d[fo:fo + fs]
    return None


def driver(work: Path) -> Path:
    """The driver the released Studio ships (MAPGEN_HELPERS), else built from this tree."""
    folder = os.environ.get("MAPGEN_HELPERS", "")
    shipped = Path(folder) / "destroy_driver.exe" if folder else None
    if shipped and shipped.is_file():
        return shipped
    from check_mapgen_recut import SOURCES
    exe = work / "destroy_driver.exe"
    sources = ["tools/mapgen_destroy_driver.c"] + [s for s in SOURCES if s != "tools/mapgen_recut_driver.c"]
    run = guard.run(["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"), "-I" + str(REPO / "src" / "mapgen"),
                     "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                    + [str(REPO / s) for s in sources] + ["-o", str(exe), "-lz", "-lm"], capture_output=True, text=True)
    if run.returncode or not exe.is_file():
        raise SystemExit("cannot build the destroy driver:\n" + run.stderr[-1500:])
    return exe


def pack_dir(given: Path | None) -> Path:
    """The pack: asked for, or the released Studio's (MAPGEN_TEXTURE_PACK, engine/textures), or the authors' build."""
    for p in (given, Path(os.environ["MAPGEN_TEXTURE_PACK"]) if os.environ.get("MAPGEN_TEXTURE_PACK") else None,
              PACK):
        if p and (p / "textures" / "mapgen" / "catalogue.json").is_file():
            return p
    raise SystemExit("no texture pack: build it with `python tools/mapgen_textures.py build`")


def pack_list(pack: Path, out: Path) -> None:
    cat = json.loads((pack / "textures" / "mapgen" / "catalogue.json").read_text(encoding="utf-8"))
    out.write_text("".join(f"{t['name']} {t['material']} {t['variant']} {t['rgb'][0]} {t['rgb'][1]} {t['rgb'][2]}"
                           f" {t.get('coherence', 0.0)}\n" for t in cat["textures"]), encoding="utf-8")


def compile_lit(mapfile: Path, game: Path, into: Path, flags: str, keys: dict, work: Path) -> tuple[bool, str]:
    """bsp and vis by the pinned compiler, then the light pass under the donor's calibration."""
    exe, threads = pinned_compiler()
    out = ""
    # the fast visibility pass: the ruin's carves and debris split the map into far more portals - the full pass took
    # q2dm1 at 50 % past a quarter of an hour where the map's own took five minutes; the fast one's table is coarser
    # (a little more is drawn), never wrong
    for stage in (["-bsp"], ["-vis", "-fast"]):
        r = guard.run([str(exe), *stage, "-threads", threads, "-moddir", str(into), "-basedir", str(game),
                       "-gamedir", str(game), str(mapfile)], capture_output=True, text=True, errors="replace",
                      timeout=7200)
        out += r.stdout + r.stderr
        if r.returncode:
            return False, f"{stage[0]} failed ({r.returncode}): {out[-300:]}"
        if stage[0] == "-bsp" and not mapfile.with_suffix(".bsp").is_file():
            err = re.findall(r"\*+ ERROR \*+\s*(.+)", out)
            return False, "the bsp stage wrote no map: " + (err[-1].strip() if err else out[-400:])
    if re.search(r"leak", out, re.I) and re.search(r"leaked|LEAK", out):
        return False, "leaked"
    bsp = mapfile.with_suffix(".bsp")
    if not bsp.is_file():
        return False, "no bsp"
    from mapgen_room_light import relight
    try:
        relight(bsp, entity_text(bsp.read_bytes()), flags, work, keys, moddir=into, basedir=game)
    except SystemExit as e:
        return False, f"light: {e}"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("--donor", type=Path, required=True)
    ap.add_argument("--destruction", type=int, required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--game", type=Path, default=GAME, help="the client's baseq2: its textures and palette are read")
    ap.add_argument("--into", type=Path, help="where the map's textures are written (default: --game)")
    ap.add_argument("--work", type=Path)
    ap.add_argument("--flags")
    ap.add_argument("--pack", type=Path)
    a = ap.parse_args()
    if a.destruction <= 0:
        print("destruction 0: nothing to do")
        return 0
    guard.pin_self()
    work = a.work or (a.map.parent / "destroy")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    into = a.into or a.game
    pack = pack_dir(a.pack)
    install(into, pack)
    (into / "textures" / "mgd").mkdir(parents=True, exist_ok=True)
    if into.resolve() != a.game.resolve() and not (into / "pics" / "colormap.pcx").is_file():
        # the light pass reads the palette from the mod folder only: a folder apart from the game gets the game's
        pcx = game_file(a.game, "pics/colormap.pcx")
        if pcx:
            (into / "pics").mkdir(parents=True, exist_ok=True)
            (into / "pics" / "colormap.pcx").write_bytes(pcx)
    plist = work / "pack.txt"
    pack_list(pack, plist)
    exe = driver(work)
    own_flags, keys = donor_light(a.donor)
    flags = a.flags if a.flags is not None else own_flags
    said = ""
    for skip, what in ((0, ""), (CARVES, "the carving kinds left out"), (0xFE, "only the cracks kept")):
        mapfile = work / "q2mg.map"
        needs = work / "needs.txt"
        r = guard.run([str(exe), str(a.map), str(mapfile), "--destruction", str(a.destruction), "--seed",
                       str(a.seed), "--pack", str(plist), "--needs", str(needs), "--game", str(a.game), "--skip",
                       str(skip), "--masks", str(pack / "textures" / "mapgen" / "masks"), "--into", str(into)],
                      capture_output=True, text=True, errors="replace", timeout=3600)
        m = DESTROYED.search(r.stdout)
        if r.returncode or not m or not mapfile.is_file():
            said = f"the driver failed ({r.returncode}): {(r.stdout + r.stderr)[-300:]}"
            continue
        said = m.group(1)
        drawn = DRAWN.search(r.stdout)
        if drawn and int(drawn.group(2)):
            print(f"cracked copies: {drawn.group(1)} drawn, {drawn.group(2)} without an original (they keep the"
                  f" compiler's default look)", flush=True)
        ok, why = compile_lit(mapfile, a.game, into, flags, keys, work)
        if not ok:
            print(f"compile with {what or 'every kind'}: {why} - trying with fewer kinds", flush=True)
            said = why
            continue
        bsp = mapfile.with_suffix(".bsp")
        shutil.copy2(bsp, a.map)
        words = said.split(" wanted ")[0].split()
        counts = dict(zip(words[0::2], words[1::2]))
        report = {"percent": a.destruction, "seed": a.seed, "left_out": what, **counts}
        a.map.with_suffix(".destroyed.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        used = sorted(set(re.findall(r"\b((?:mapgen|mgd)/[\w/-]+)\b", mapfile.read_text(encoding="utf-8",
                                                                                         errors="replace"))))
        a.map.with_suffix(".textures.txt").write_text("\n".join(used) + "\n", encoding="utf-8")
        print(f"destroyed: {said}" + (f" ({what})" if what else ""), flush=True)
        print("DESTRUCTION OK", flush=True)
        return 0
    print(f"DESTRUCTION FAILED {said}", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
