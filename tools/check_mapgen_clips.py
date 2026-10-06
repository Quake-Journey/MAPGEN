"""No player-clip brush in space the generator opened.

The PO, 2026-10-01, on mg_20m and mg_20n: «Есть открытая область в проеме стены, но я не могу в нее пройти напрямую,
могу пройти только если прижимаюсь к одной из стенок» - two q2dm1 player-clip beams that stood against a wall the
doorway was cut through, left standing in the doorway because the carve cut only solid brushes (ledger row 337).
A clip brush is invisible: no gate that reads faces, lights or the walk's places from the spawns' side of it says
anything, and the walk only finds the way round it.

    python tools/check_mapgen_clips.py MAP.bsp [--donor q2dm1.bsp]
    python tools/check_mapgen_clips.py --red      the controlled RED

For every brush of the compiled map whose contents carry CONTENTS_PLAYERCLIP and not CONTENTS_SOLID, its box from
its axial sides, and twelve units out from the middle of each of its four upright faces: where a point is ROCK in
the donor and AIR in the map beside two or more faces, the generator opened space round it - refused (row 338) - where the brush reaches into a
standing player's band over the floor there, 58 high (row 339). `--red` asks it of the mg_20m that was
delivered with the beams (kept as evidence) and must find them.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_mapgen_static import Bsp  # noqa: E402

DONOR = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")
EVIDENCE = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\round41\evidence\mg_20m_clip_beams.bsp")
PLAYERCLIP = 0x10000
SOLID = 0x1
OUT = 12.0


def clip_boxes(b: Bsp) -> list:
    """The box of every player-clip brush that is not solid, from its axial sides."""
    sides = b._arr(15, "<Hh", 4)
    out = []
    for first, num, contents in b._arr(14, "<iii", 12):
        if not contents & PLAYERCLIP or contents & SOLID:
            continue
        lo, hi = [None] * 3, [None] * 3
        for s in range(first, first + num):
            nx, ny, nz, dist, _ = b.planes[sides[s][0]]
            for a, n in enumerate((nx, ny, nz)):
                if abs(n - 1.0) < 1e-4 and abs(sum(abs(v) for v in (nx, ny, nz)) - 1.0) < 1e-4:
                    hi[a] = dist
                elif abs(n + 1.0) < 1e-4 and abs(sum(abs(v) for v in (nx, ny, nz)) - 1.0) < 1e-4:
                    lo[a] = -dist
        if None not in lo and None not in hi:
            out.append((lo, hi))
    return out


def in_band(cand: Bsp, p: list, lo: list, hi: list) -> bool:
    """Row 339: does the clip brush reach into a standing player's band over the floor under `p` - its bottom
    below that floor plus 58, its top above the floor?"""
    z = p[2]
    while z > p[2] - 512.0 and not cand.solid([p[0], p[1], z]):
        z -= 2.0
    return lo[2] < z + 58.0 and hi[2] > z


def lifted(b: Bsp) -> list:
    """Row 384: the volumes a sky lift made, as its `info_null` records them - over the lid and the near box."""
    out = []
    for e in b.ents:
        for key in ("mapgen_sky_lift", "mapgen_sky_lift_near"):
            v = e.get(key, "").split()
            if len(v) == 6:
                out.append([float(x) for x in v])
    return out


def exposed(bsp: Path, donor: Path = DONOR) -> list:
    """Every clip box with space opened beside at least TWO of its four upright faces - a point 12 out from the
    face's middle that the donor had as rock and the map has as air (row 338: a piece the carve cut off a large clip
    brush borders the opened space on its one cut face and stands in nobody's way). The air of a sky lift is no
    opened space here: the lift lays player clip where the sky it took stood, so no player reaches it, and q2dm1's own
    tall clip posts and the lift's clips stand beside it by design (rows 384, 387)."""
    cand, don = Bsp(bsp), Bsp(donor)
    lifts = lifted(cand)
    bad = []
    for lo, hi in clip_boxes(cand):
        mid = [(lo[i] + hi[i]) / 2.0 for i in range(3)]
        opened = []
        for ax in (0, 1):
            for sgn in (-1.0, 1.0):
                p = list(mid)
                p[ax] = (hi[ax] if sgn > 0 else lo[ax]) + sgn * OUT
                if any(all(v[i] <= p[i] <= v[3 + i] for i in range(3)) for v in lifts):
                    continue
                if don.solid(p) and not cand.solid(p) and in_band(cand, p, lo, hi):
                    opened.append(p)
        if len(opened) >= 2:
            bad.append((lo, hi, opened[0]))
    return bad


def said(bad: list) -> str:
    return "; ".join(f"{' '.join(f'{v:.0f}' for v in lo)} .. {' '.join(f'{v:.0f}' for v in hi)}"
                     f" (opened beside it at {' '.join(f'{v:.0f}' for v in p)})" for lo, hi, p in bad[:4])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", nargs="?", type=Path)
    ap.add_argument("--donor", type=Path, default=DONOR)
    ap.add_argument("--red", action="store_true")
    a = ap.parse_args()
    target = EVIDENCE if a.red else a.map
    if not target or not target.is_file():
        print(f"no map at {target}")
        return 2
    bad = exposed(target, a.donor)
    if a.red:
        ok = bool(bad)
        print(f"  {'PASS' if ok else 'FAIL'}  RED: the mg_20m delivered with the beams has clip brushes in space the"
              f" generator opened  -- {len(bad)}: {said(bad)}")
        print(f"SUMMARY 1 cases asserted, {0 if ok else 1} failures")
        return 0 if ok else 1
    ok = not bad
    print(f"  {'PASS' if ok else 'FAIL'}  {target.name}: no player-clip brush in space the generator opened"
          f"  -- {len(bad)} found" + (f": {said(bad)}" if bad else ""))
    print(f"SUMMARY 1 cases asserted, {0 if ok else 1} failures")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
