r"""Brief 25 B: the factory presets of the shape «Башня» (whole storeys round an atrium, pro_q2t4) - the table the
Studio's presets are written from (tools/mapgen_scratch_presets_codegen.py), in the form of Fable's oracle table of
06.11 (`tools/fable_oracles/mapgen_2026-11-06_presets_x10.py`: `add(category, key, P(players, ...))`, values as the
form's rows give them). Each goes through `make_plan` on 12 seeds by `python tools/mapgen_scratch_presets_tower.py`
(the gate of the 160: failed on 6 or fewer, no refusal on every seed made).
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


add("tower", "tower_duel", P(2, shape="tower"))
add("tower", "tower_tight", P(2, shape="tower", storey_height=160))
add("tower", "tower_2", P(4, shape="tower", storeys=2))
add("tower", "tower_3", P(4, shape="tower"))
add("tower", "tower_roomy", P(4, shape="tower", storey_height=224))
add("tower", "tower_atrium", P(4, shape="tower", shafts=1, perches=3))
add("tower", "tower_quad", P(4, shape="tower", perches=3, stack="2ya_adren_quad"))
add("tower", "tower_tech", P(4, shape="tower", style=G("tech")))
add("tower", "tower_8", P(8, shape="tower", shafts=3))
add("tower", "tower_4", P(8, shape="tower", storeys=4))
add("tower", "tower_16", P(16, shape="tower", storeys=4, shafts=3))


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
