r"""A donor's light fitted once, by itself, on the first map built from it (row 410; the PO: «и что мы будем каждый
раз по 10 раз генерировать карту чтобы подобрать ей свет???»).

    python tools/mapgen_light_autofit.py LIT.bsp DONOR.bsp WORK_DIR [--rounds N] [--force]

A donor already calibrated - by its sha256 in `tools/mapgen_donor_light.json`, or by its own fit beside it
(`DONOR.light_fit.json`, this tool's) - is left alone: prints KNOWN and exits 0. Otherwise light-only reruns of LIT.bsp
(a finished map of that donor: no generation, the light pass alone, the P-cores of the hour) are steered towards
`mapgen_light_profile.faithful`, up to N rounds:

* level - `-scale` by the inverse of the three channels' geometric mean ratio (measured on mg_20u from q2dm1: -scale
  1.4 took the red ratio 0.52 -> 0.69, about the power 0.85);
* colour - a donor with a sun and no `_sun_color` gets one, white first (q2tools-220 paints an uncoloured sun in the
  sky texture's colour: cor's faces came out B/R 0.27 of cor's), each channel then moved by its own ratio;
* colour without a sun - the bounce: `-saturation` (the help says -saturate; the tool reads -saturation), by the
  secant on log B/R against the donor's (mg_20u from q2dm1, no coloured light in either: saturation 0.5 -> B/R 3.3 of
  q2dm1's, 1 -> 1.3, 2 -> 0.5; its ceilings stay bluer at every one);
* burn - when ours burns more than the donor (decision 1), `-maxlight` at the donor's own brightest luxel (the old
  qrad's default 196 on q2dm1 and q3t2; q2tools-220 clips at 255).

The fit (flags, keys, FAITHFUL or not, every round's line) goes to DONOR.light_fit.json beside the donor, and the
Studio's DONOR.light.txt / DONOR.light_keys.txt with it; prints FITTED. Not faithful after N rounds is said - the best
round is kept and the table shows how far (brief 7 decision 2: a stop-and-report, never a looser band).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from mapgen_light_calibrate import donor_light, entity_text  # noqa: E402
from mapgen_light_fit import light_only, score  # noqa: E402
from mapgen_light_profile import BURNT_SLACK, lit_faces  # noqa: E402

LEVEL_POWER = 0.85          # ratio ~ scale ** 0.85, measured (above)
SCALE_RANGE = (0.3, 4.0)


def fit_path(donor: Path) -> Path:
    return donor.with_suffix(".light_fit.json")


def flags_of(scale: float, maxlight: int | None, saturate: float | None) -> str:
    return (f"-scale {scale:.3f}" + (f" -maxlight {maxlight}" if maxlight else "")
            + (f" -saturation {saturate:.2f}" if saturate is not None else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lit", type=Path)
    ap.add_argument("donor", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--force", action="store_true", help="fit even when the donor is calibrated")
    a = ap.parse_args()
    sha = hashlib.sha256(a.donor.read_bytes()).hexdigest()
    flags, keys = donor_light(a.donor)
    if not a.force and (flags or keys):
        print(f"KNOWN '{flags}' {keys}")
        return 0
    guard.pin_self()
    world = entity_text(a.donor.read_bytes())
    world = world[world.index("{"):world.index("}")]
    sunny = bool(re.search(r'"_sun(_angle)?"\s', world))
    colour = None
    if sunny and not re.search(r'"_sun_color"\s', world):
        colour = [1.0, 1.0, 1.0]
    top = max((max(f["tops"]) for f in lit_faces(a.donor) if f["tops"]), default=255)
    scale, maxlight, saturate = 1.0, None, None
    raw = a.lit.read_bytes()
    own = entity_text(raw)
    table, best, tint = [], None, []
    for rnd in range(a.rounds):
        keys = {"_sun_color": " ".join(f"{c:.2f}" for c in colour)} if colour else {}
        fl = flags_of(scale, maxlight, saturate)
        code, ok, rows = light_only(raw, own, keys, fl, a.work / f"r{rnd}", a.donor)
        s = score(rows) if code == 0 else 99.0
        al = next((r for r in rows if r["kind"] == "all"), None)
        line = (f"round {rnd} score {s:.3f}{' FAITHFUL' if ok else ''} flags '{fl}' keys {keys} | "
                + " | ".join(f"{r['kind'][:4]} {r['ratio'][0]:.2f}/{r['ratio'][1]:.2f}/{r['ratio'][2]:.2f}"
                             f" p90 {r['p90'][0]}/{r['p90'][1]} burnt {r['burnt'][0]:.1f}/{r['burnt'][1]:.1f}"
                             for r in rows))
        print(line, flush=True)
        table.append(line)
        if best is None or s < best[0]:
            best = (s, fl, keys, ok)
        if ok or not al or code:
            break
        g = math.exp(sum(math.log(max(x, 1e-3)) for x in al["ratio"]) / 3)
        scale = min(SCALE_RANGE[1], max(SCALE_RANGE[0], scale * (1.0 / g) ** (1.0 / LEVEL_POWER)))
        if colour:
            colour = [c * g / max(al["ratio"][i], 1e-3) for i, c in enumerate(colour)]
            colour = [c / max(colour) for c in colour]
        else:
            # no sun to colour: what tints is the bounce off the textures. log(B/R against the donor's) over
            # log(saturation), by the secant through the last two tries; the first step doubles it when ours is the
            # bluer (measured on mg_20u from q2dm1: saturation 0.5 -> B/R 3.3, 1 -> 1.3, 2 -> 0.5)
            br = math.log(max(al["ratio"][2], 1e-3) / max(al["ratio"][0], 1e-3))
            x = math.log(1.0 if saturate is None else saturate)
            tint.append((x, br))
            if abs(br) > math.log(1.1):
                if len(tint) >= 2 and abs(tint[-1][1] - tint[-2][1]) > 1e-3:
                    (x0, y0), (x1, y1) = tint[-2], tint[-1]
                    nx = x1 - y1 * (x1 - x0) / (y1 - y0)
                else:
                    nx = x + (math.log(2.0) if br > 0 else -math.log(2.0))
                saturate = math.exp(min(math.log(8.0), max(math.log(0.125), nx)))
        if maxlight is None and top < 255 and al["burnt"][0] > al["burnt"][1] + BURNT_SLACK:
            maxlight = int(top)
    s, fl, keys, ok = best
    fit = {"sha256": sha, "name": a.donor.stem, "flags": fl, "keys": keys, "faithful": ok, "score": round(s, 3),
           "table": table}
    fit_path(a.donor).write_text(json.dumps(fit, indent=1), encoding="utf-8")
    a.donor.with_suffix(".light.txt").write_text(fl + "\n", encoding="utf-8")
    kp = a.donor.with_suffix(".light_keys.txt")
    if keys:
        kp.write_text(";".join(f"{k}={v}" for k, v in keys.items()) + "\n", encoding="utf-8")
    elif kp.exists():
        kp.unlink()
    print(f"FITTED{' FAITHFUL' if ok else ' NOT FAITHFUL'} score {s:.3f} flags '{fl}' keys {keys}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
