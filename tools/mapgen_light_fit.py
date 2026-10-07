r"""A donor's light translated for q2tools-220, fitted on a built map of it (row 410, Fable's brief 7 decision 2).

    python tools/mapgen_light_fit.py LIT.bsp DONOR.bsp WORK_DIR GRID.json

GRID.json: {"keys": {"_sun_light": [...], "_sun_ambient": [...], "_sun_angle": [...], ...},
            "flags": ["", "-sunradscale 0.3", ...]} - every combination is a light-only rerun of LIT.bsp (the donor's
sun added as the pipeline adds it, these worldspawn keys replacing the donor's own, these switches), judged by
`mapgen_light_profile.faithful` against DONOR.bsp. Prints one line per try, its score (the worst |log ratio| over
the three orientations' channels and p90s) and FAITHFUL when decision 1 holds; the best last.

MEASURED on mg_cor (row 410): with no `_sun_color` q2tools paints the sun in the sky texture's colour - cor's old
faces came out B/R 0.27 of cor's; `_sun_ambient` lights walls and ceilings evenly (55 -> walls p50 68, 0 -> 6),
`_sun_light` falls on what faces the sun; `-bounce`, `-direct`, `-saturate`, `-sundiffuse` barely moved it.
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_light_calibrate import entity_text, with_entities, with_keys, with_sun  # noqa: E402
from mapgen_light_profile import faithful  # noqa: E402
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
from mapgen_memfile import compile_bsp_in_memory  # noqa: E402

from mapgen_load_guard import game_dir  # noqa: E402  (brief 13 W1: the game folder of this run)
GAME = game_dir()


def light_only(raw: bytes, own: str, keys: dict, flags: str, d: Path, donor: Path) -> tuple[int, bool, list]:
    """One light-only rerun of a finished map (RAW, its entity text OWN) with these worldspawn keys and switches,
    in directory D, on the P-cores of the hour; the result takes its own entity lump back and is judged against
    DONOR by `faithful`. Returns (exit code, faithful, rows)."""
    d.mkdir(parents=True, exist_ok=True)
    text = with_keys(own, keys)
    threads = str(bin(guard.affinity_mask()).count("1"))
    words = ["-rad", "-maxdata", "8388608", "-threads", threads, *flags.split(),
             "-moddir", GAME, "-basedir", GAME, "-gamedir", GAME]
    # row 411 (Fable's brief 8 D): the rerun in memory - only the lit result reaches the disk, once
    runs, lit = compile_bsp_in_memory(pinned_compiler()[0], [words], with_entities(raw, with_sun(text) or text),
                                      timeout=3600, label="lightfit")
    if runs is None:
        (d / "q2mg.bsp").write_bytes(with_entities(raw, with_sun(text) or text))
        r = guard.run([str(pinned_compiler()[0]), *words, str(d / "q2mg.map")],
                      capture_output=True, text=True, errors="replace", timeout=3600)
        lit = (d / "q2mg.bsp").read_bytes()
    else:
        r = runs[-1]
    (d / "rad.log").write_text(r.stdout, encoding="utf-8")
    (d / "q2mg.bsp").write_bytes(with_entities(lit or raw, own))
    ok, _, rows = faithful(d / "q2mg.bsp", donor)
    return r.returncode, ok, rows


def score(rows: list) -> float:
    worst = 0.0
    for r in rows:
        if r["kind"] == "all":
            continue
        for x in list(r["ratio"]) + [r["p90"][0] / max(1, r["p90"][1])]:
            worst = max(worst, abs(math.log(max(x, 1e-3))))
    return worst


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    guard.pin_self()
    lit, donor, work, grid = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), json.loads(Path(sys.argv[4]).read_text())
    raw = lit.read_bytes()
    own = entity_text(raw)
    names = list(grid.get("keys", {}))
    best = None
    for n, (values, flags) in enumerate(itertools.product(itertools.product(*[grid["keys"][k] for k in names]),
                                                          grid.get("flags", [""]))):
        keys = dict(zip(names, values))
        code, ok, rows = light_only(raw, own, keys, flags, work / f"t{n:03d}", donor)
        s = score(rows) if code == 0 else 99.0
        brief = " | ".join(f"{x['kind'][:4]} {x['ratio'][0]:.2f}/{x['ratio'][1]:.2f}/{x['ratio'][2]:.2f}"
                           f" p90 {x['p90'][0]}/{x['p90'][1]} burnt {x['burnt'][0]:.1f}" for x in rows if x["kind"] != "all")
        print(f"t{n:03d} score {s:.3f}{' FAITHFUL' if ok else ''} keys {keys} flags '{flags}' | {brief}", flush=True)
        if best is None or s < best[0]:
            best = (s, keys, flags, ok)
    if best:
        print(f"BEST score {best[0]:.3f}{' FAITHFUL' if best[3] else ''} keys {best[1]} flags '{best[2]}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
