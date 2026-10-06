r"""Brief 11 step 1 (ledger row 412h): the shared ceilings of a first q2dm1 map stay at 0.62..0.72 of q2dm1's own under
every scale the fit tries (sides and floors at 0.98..1.01) - a balance one multiplier cannot move. This asks the light
pass alone (no generation: `mapgen_light_fit.light_only` on a finished map) what moves the ceilings against the walls:
the bounces, the surface lights' share, the point lights' share. One line a try: the three orientations' ratios.

    python tools/mapgen_light_ceiling_ab.py MAP.bsp DONOR.bsp WORK [--base "-scale 2.289 -maxlight 196"]
                                            [--try "-bounce 16" --try "-direct 1.5" ...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_light_calibrate import donor_light, entity_text  # noqa: E402
from mapgen_light_fit import light_only  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=Path)
    ap.add_argument("donor", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--base", default="-scale 2.289 -maxlight 196")
    ap.add_argument("--try", dest="tries", action="append", default=[])
    a = ap.parse_args()
    guard.pin_self()
    raw = a.map.read_bytes()
    own = entity_text(raw)
    _, keys = donor_light(a.donor)
    for i, extra in enumerate([""] + a.tries):
        flags = f"{a.base} {extra}".strip()
        code, ok, rows = light_only(raw, own, keys, flags, a.work / f"t{i}", a.donor)
        said = " | ".join(f"{r['kind'][:4]} {r['ratio'][0]:.2f}/{r['ratio'][1]:.2f}/{r['ratio'][2]:.2f}" for r in rows)
        print(f"'{flags}': {'FAITHFUL ' if ok else ''}{said}" + (f" (exit {code})" if code else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
