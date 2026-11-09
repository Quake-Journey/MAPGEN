r"""Brief 34 item 12 (the PO 08.11: «нужно проявлять мозги, а не просто напихивать на уровне кучу повторяемых объектов,
которые смотреть невозможно»; «пресеты под это делать новые заводские»): every factory preset of a map from scratch
re-read for counts - what it asks of the ways up against what the plan makes under brief 34's rules.

For each preset (the Studio's dump, `MapgenStudio.exe --presets-dump DIR`: DIR\scratch\<key>.json) over seeds
700.. (`--seeds`, 3 by default), through `make_plan`:
  * asked: the request's pads and teleporter pairs as the plan resolves them (a preset that leaves them to the player
    count gets the class's defaults);
  * made: the plan's pads (a tower's: from the ground, to the ledges), teleporter pairs, flights, lifts - the mean;
  * the plan's own measures: the nearest two pads on one floor (cells), pads with no reason (a stair or a door to the
    same place is right there), the most teleporter discs near one disc, as the judge's «repetition» row counts them.
A preset is FLAGGED when it asks pads or teleporters and no seed makes a third of them (it asks a count the rules
refuse - the record of every map it makes says «не сделано») or when a measure breaks (two pads nearer than three
cells, a pad without a reason, three teleporter discs together).

    python tools/check_mapgen_presets_ways.py DIR [--seeds 3] [--jobs N]

`--jobs N` checks N presets at a time, pinned by tools/mapgen_load_guard.py as check_mapgen_presets.py is.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_scratch_plan as pm  # noqa: E402


def nearest_pads(P) -> int | None:
    """The nearest two take-offs on one floor, in cells (Chebyshev), or None with fewer than two."""
    best = None
    pads = list(P.pads)
    for i in range(len(pads)):
        a, za = pads[i][0], pads[i][6]
        for j in range(i + 1, len(pads)):
            b, zb = pads[j][0], pads[j][6]
            if pm.same_floor(P, a, b, za, zb):
                pa, pb = pm.phys(a), pm.phys(b)
                d = max(abs(pa[0] - pb[0]), abs(pa[1] - pb[1]))
                best = d if best is None else min(best, d)
    return best


def discs_together(P) -> int:
    """The most teleporter discs near one disc (itself counted), as the judge's «repetition» row counts like things
    (mapgen_scratch_fixtures.crowded: within REPEAT_CELLS cells, on one floor - |dz| < 64)."""
    import math
    import mapgen_scratch_fixtures as fx
    pts = []
    for (a, b, _da, _db) in P.teleports:
        for c in (a, b):
            pc = pm.phys(c)
            z = P.spaces[P.owner[c]].floor[c][0] if c in P.owner else 0
            pts.append(((pc[0] + 0.5) * pm.CELL, (pc[1] + 0.5) * pm.CELL, z))
    reach = fx.REPEAT_CELLS * pm.CELL
    return max((sum(1 for o in pts if abs(o[2] - q[2]) < 64 and math.hypot(o[0] - q[0], o[1] - q[1]) <= reach)
                for q in pts), default=0)


def check_one(args: tuple[str, str, list[int]]) -> tuple[str, bool, str]:
    stem, text, seeds = args
    q = json.loads(text)
    t0 = time.time()
    shape = q.get("shape") or "rooms"
    asked_pads = asked_tp = 0
    made = failed = 0
    pads = tps = 0
    ways: dict[str, int] = {}
    near, no_reason, together = None, 0, 0
    for s in seeds:
        P = pm.make_plan(dict(q), s)
        if P.failed:
            failed += 1
            continue
        made += 1
        asked_pads, asked_tp = int(P.params.get("pads") or 0), int(P.params.get("teleporters") or 0)
        w = P.metrics.get("ways") or {}
        for k, v in w.items():
            ways[k] = ways.get(k, 0) + int(v)
        # a tower's «pads» row asks the pads from the atrium's floor; its ledges' pads are by design
        pads += int(w["pads"]) if shape == "tower" and "pads" in w else len(P.pads)
        tps += len(P.teleports)
        n_ = nearest_pads(P)
        near = n_ if near is None or (n_ is not None and n_ < near) else near
        no_reason = max(no_reason, int(P.metrics.get("pads_no_reason") or 0))
        together = max(together, discs_together(P))
    mean = (lambda v: v / made if made else 0.0)
    short = []
    if asked_pads and made and mean(pads) < asked_pads / 3:
        short.append(f"pads {mean(pads):.1f} of {asked_pads}")
    if asked_tp and made and mean(tps) < asked_tp / 3:
        short.append(f"teleporters {mean(tps):.1f} of {asked_tp}")
    broken = []
    if near is not None and near < pm.PAD_APART:
        broken.append(f"pads {near} cells apart")
    if no_reason:
        broken.append(f"{no_reason} pads without a reason")
    if together > 2:
        broken.append(f"{together} teleporter discs together")
    ok = not short and not broken
    tw = ""
    if shape == "tower" and made:
        tw = (f"; stairs {mean(ways.get('stairs', 0)):.1f}, lifts {mean(ways.get('lifts', 0)):.1f}, "
              f"ledge pads {mean(ways.get('perch_pads', 0)):.1f}")
    line = (f"{'PASS' if ok else 'FLAG'} {stem:20s} {shape:6s} failed {failed} of {len(seeds)}; "
            f"pads {mean(pads):4.1f} of {asked_pads}, teleporters {mean(tps):3.1f} of {asked_tp}{tw}; "
            f"nearest pads {near if near is not None else '-'}, no reason {no_reason}, discs together {together}; "
            f"{time.time() - t0:4.1f} s" + (f"; ASKS A COUNT: {', '.join(short)}" if short else "")
            + (f"; BROKEN: {', '.join(broken)}" if broken else ""))
    return stem, ok, line


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    files = sorted((a.dump / "scratch").glob("*.json"), key=lambda f: (f.stem != "default", f.stem))
    if not files:
        print(f"FAIL no presets in {a.dump / 'scratch'}")
        return 1
    seeds = list(range(700, 700 + a.seeds))
    work = [(f.stem, f.read_text(encoding="utf-8"), seeds) for f in files]
    t_all = time.time()
    if a.jobs > 1:
        import multiprocessing
        import mapgen_load_guard
        mapgen_load_guard.pin_self()
        with multiprocessing.Pool(a.jobs) as pool:
            results = pool.map(check_one, work, chunksize=1)
    else:
        results = [check_one(w) for w in work]
    flagged = []
    for stem, ok, line in results:
        print(line, flush=True)
        if not ok:
            flagged.append(stem)
    print(f"{len(results)} presets in {time.time() - t_all:.0f} s")
    print("PASS" if not flagged else f"FLAGGED ({len(flagged)}): {', '.join(flagged)}")
    return 0 if not flagged else 1


if __name__ == "__main__":
    sys.exit(main())
