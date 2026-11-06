r"""Brief 25 A4: the factory presets of the shape «Открытый космос» (islands in the void) - the table the Studio's
presets are written from (tools/mapgen_scratch_presets_codegen.py), in the form of Fable's oracle table of 06.11
(`tools/fable_oracles/mapgen_2026-11-06_presets_x10.py`: `add(category, key, P(players, ...))`, values as the form's
rows give them). Each goes through `make_plan` on 12 seeds by `python tools/mapgen_scratch_presets_space.py` (the
gate of the 160: failed on 6 or fewer, no refusal on every seed made).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fable_oracles"))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("presets_x10", Path(__file__).resolve().parent / "fable_oracles" / "mapgen_2026-11-06_presets_x10.py")
_ox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ox)
P, G = _ox.P, _ox.G

PRESETS: list[tuple[str, str, dict]] = []


def add(cat: str, key: str, q: dict) -> None:
    PRESETS.append((cat, key, q))


add("space", "space_duel", P(2, shape="space"))
add("space", "space_yard", P(4, shape="space", islands=12, pad_only=3, height_spread=1300, pad_reach="long", ships=2))
add("space", "space_arena8", P(8, shape="space", islands=12, pad_only=2))
add("space", "space_bridges", P(4, shape="space", bridges="many", pad_reach="short", islands=8))
add("space", "space_rails", P(2, shape="space", edges="railings"))
# spread 400 with short pads made 4 of 12 (06.11): the low islands keep the medium pads
add("space", "space_low", P(4, shape="space", height_spread=400))
add("space", "space_high", P(4, shape="space", height_spread=1300, pad_only=4, pad_reach="long"))
add("space", "space_tele", P(8, shape="space", teleporters=3, islands=12))
add("space", "space_small", P(2, shape="space", islands=6, pad_only=1))
add("space", "space_quad_hunt", P(4, shape="space", pad_only=3, stack="2ya_adren_quad"))
add("space", "space_planet", P(4, shape="space", style=G("planet"), edges="some"))
add("space", "space_tech", P(2, shape="space", style=G("tech"), edges="some", bridges="many", ships=3))
add("space", "space_industrial", P(8, shape="space", style=G("industrial"), islands=16, height_spread=1000))


def main() -> int:
    import mapgen_load_guard
    import mapgen_scratch_plan as pm
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    bad = []
    for cat, key, q in PRESETS:
        t0 = time.time()
        failed, made, refused = 0, 0, {}
        for s in range(700, 712):
            Pl = pm.make_plan(dict(q), s)
            if Pl.failed:
                failed += 1
                continue
            made += 1
            for r in set(Pl.params.get("refused") or []):
                refused[r] = refused.get(r, 0) + 1
        always = [r for r, n in refused.items() if made and n == made]
        ok = failed <= 6 and not always
        bad += [] if ok else [key]
        print(f"{'PASS' if ok else 'FAIL'} {key:18s} failed {failed:2d} of 12, {time.time() - t0:4.1f} s"
              + (f"; refused on every seed: {always[0]}" if always else ""))
    print("PASS" if not bad else "FAIL " + ", ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
