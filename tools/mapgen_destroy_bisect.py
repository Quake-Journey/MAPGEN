r"""Which kind of the ruin leaks (brief 11 D2, ledger row 412l) - a diagnosis, one map.

    python tools/mapgen_destroy_bisect.py MAP.bsp --destruction D --seed S [--game BASEQ2] --work DIR

The destroy driver's ruin of MAP compiled (the bsp stage only) with ONE carving kind at a time - craters, breaches
and gouges, broken edges, collapses, ruin - and with all of them; for a leak the compiler's own leak line and, when it
writes one, the first point of its leak trail. One line a try.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_destroy as md  # noqa: E402
import mapgen_load_guard as guard  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402

KINDS = {"craters": 4, "breaches": 8, "broken": 16, "collapses": 32, "ruin": 64}
ALL = 1 | 2 | 4 | 8 | 16 | 32 | 64


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("--destruction", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--game", type=Path, default=md.GAME)
    ap.add_argument("--work", type=Path, required=True)
    a = ap.parse_args()
    guard.pin_self()
    a.work.mkdir(parents=True, exist_ok=True)
    pack = md.pack_dir(None)
    into = a.work / "into"
    md.install(into, pack)
    (into / "textures" / "mgd").mkdir(parents=True, exist_ok=True)
    plist = a.work / "pack.txt"
    md.pack_list(pack, plist)
    exe = md.driver(a.work)
    q2tool, threads = pinned_compiler()
    tries = [("all", 0)] + [(k, ALL & ~(1 | 2 | bit)) for k, bit in KINDS.items()]
    for name, skip in tries:
        mp = a.work / f"try_{name}.map"
        r = guard.run([str(exe), str(a.map), str(mp), "--destruction", str(a.destruction), "--seed", str(a.seed),
                       "--pack", str(plist), "--needs", str(a.work / "needs.txt"), "--game", str(a.game), "--skip",
                       str(skip), "--masks", str(pack / "textures" / "mapgen" / "masks"), "--into", str(into)],
                      capture_output=True, text=True, errors="replace", timeout=3600)
        said = (md.DESTROYED.search(r.stdout).group(1).split(" wanted ")[0] if md.DESTROYED.search(r.stdout) else "?")
        c = guard.run([str(q2tool), "-bsp", "-threads", threads, "-moddir", str(into), "-basedir", str(a.game),
                       "-gamedir", str(a.game), str(mp)], capture_output=True, text=True, errors="replace",
                      timeout=3600)
        out = c.stdout + c.stderr
        leaked = bool(re.search(r"leaked", out))
        trail = ""
        for ext in (".pts", ".lin"):
            f = mp.with_suffix(ext)
            if f.is_file():
                first = f.read_text(errors="replace").split("\n", 1)[0].strip()
                trail = f" trail {ext} starts at {first}"
                break
        print(f"{name}: {'LEAKED' if leaked else 'sealed'}{trail} | {said}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
