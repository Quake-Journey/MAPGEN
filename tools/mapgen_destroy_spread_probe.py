r"""How evenly the ruin covers the map (the PO, 08.10, mg_5_6675 at 100 times, quake238 at -128 932 814: «в этой
части карты почти не заметно каких то изменений архитектуры и разрушений»).

Runs the destroy driver on a donor at a percent and seed, reads the boxes it made (`--boxes`) and says, over the
256 x 256 columns of the map where the ruin made anything at all, how many columns hold none of its pieces within 256
of their middle - the empty stretches - and the pieces' count. Two trees (a baseline and the work) give the before and
after of a change to the ruin's placement.

    python tools/mapgen_destroy_spread_probe.py --donor q2dm1 --percent 10000 --seed 6686 [--tree DIR] [--work DIR]

Measured 08.10 on q2dm1 at 100 times, seed 6686: 260 pieces in 54 columns, 16 of 93 near columns empty; drawing four
places and taking the one farthest from what the ruin had made gave 248 pieces in 53 columns, 18 of 92 empty - no
better, and was not kept. What bounds the ruin at 100 times is the map's room for brush sides (240 pieces of 14 600).
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_recut import SOURCES  # noqa: E402

DONORS = Path(r"O:\Claude2\MapgenStudio\engine\donors")
PACK = Path(r"O:\Claude2\MapgenStudio\engine")


def build(tree: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "destroy_driver.exe"
    sources = ["tools/mapgen_destroy_driver.c"] + [s for s in SOURCES if s != "tools/mapgen_recut_driver.c"]
    run = subprocess.run(["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"), "-I" + str(tree / "src" / "mapgen"),
                          "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0", "-DUSE_NEW_GAME_API=0"]
                         + [str(tree / s) for s in sources] + ["-o", str(exe), "-lz", "-lm"],
                         capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if run.returncode or not exe.is_file():
        raise SystemExit("cannot build the destroy driver:\n" + run.stderr[-1500:])
    return exe


def boxes_of(exe: Path, donor: Path, percent: str, seed: str, work: Path) -> list[tuple[str, list[float]]]:
    import json
    cat = json.loads((PACK / "textures" / "mapgen" / "catalogue.json").read_text(encoding="utf-8"))
    pack = work / "pack.txt"
    pack.write_text("".join(f"{t['name']} {t['material']} {t['variant']} {t['rgb'][0]} {t['rgb'][1]} {t['rgb'][2]}"
                            f" {t.get('coherence', 0.0)}\n" for t in cat["textures"]), encoding="utf-8")
    boxes = work / "boxes.txt"
    boxes.unlink(missing_ok=True)
    run = subprocess.run([str(exe), str(donor), str(work / "out.map"), "--destruction", percent, "--seed", seed,
                          "--pack", str(pack), "--needs", str(work / "needs.txt"), "--boxes", str(boxes)],
                         capture_output=True, text=True, timeout=3600,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not boxes.is_file():
        raise SystemExit("the driver wrote no boxes:\n" + (run.stdout + run.stderr)[-1500:])
    out = []
    for line in boxes.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) == 7:
            out.append((p[0], [float(v) for v in p[1:]]))
    return out


def spread(boxes: list[tuple[str, list[float]]]) -> tuple[int, int, float]:
    """The columns of 256 with a piece; of the columns within the pieces' whole extent that a piece's neighbourhood
    reaches, how many hold none within 256; the mean distance from each such column's middle to its nearest piece."""
    mids = [((b[0] + b[3]) / 2, (b[1] + b[4]) / 2) for _, b in boxes]
    cols = {(math.floor(x / 256), math.floor(y / 256)) for x, y in mids}
    # the map's floors reached: every column within one column of a piece (the ruin reaches the whole walk at 100 x)
    near = {(cx + dx, cy + dy) for cx, cy in cols for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    empty = 0
    for cx, cy in near:
        mx, my = (cx + 0.5) * 256, (cy + 0.5) * 256
        if not any(abs(x - mx) <= 256 and abs(y - my) <= 256 for x, y in mids):
            empty += 1
    return len(cols), len(near), empty


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--donor", default="q2dm1")
    ap.add_argument("--percent", default="10000")
    ap.add_argument("--seed", default="6686")
    ap.add_argument("--tree", type=Path, action="append", default=[])
    ap.add_argument("--work", type=Path, default=Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\spread"))
    a = ap.parse_args()
    trees = a.tree or [TOOLS.parent]
    for k, tree in enumerate(trees):
        work = a.work / f"t{k}"
        work.mkdir(parents=True, exist_ok=True)
        exe = build(tree, work)
        b = boxes_of(exe, DONORS / f"{a.donor}.bsp", a.percent, a.seed, work)
        cols, near, empty = spread(b)
        kinds = {}
        for kind, _ in b:
            kinds[kind] = kinds.get(kind, 0) + 1
        print(f"{tree}: {len(b)} pieces ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))}); "
              f"{cols} columns of 256 with a piece; {empty} of {near} columns near them with no piece within 256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
